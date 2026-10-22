"""Sealed virtual instrument for the MultiMS2 lab."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from spectrapilot.models import Measurement
from spectrapilot.paths import ORACLE_PRIVATE
from spectrapilot.planning.actions import ACTION_SPECS, MeasurementAction


class OracleAccessError(RuntimeError):
    pass


class OracleStore:
    def __init__(self, payload: dict, *, log_path: Path | None = None):
        self._cases = payload
        self._log_path = Path(log_path or (ORACLE_PRIVATE / "access_log.jsonl"))
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @classmethod
    def load(
        cls,
        path: Path = ORACLE_PRIVATE / "cases.json",
        *,
        log_path: Path | None = None,
    ) -> "OracleStore":
        if not Path(path).exists():
            raise FileNotFoundError(
                f"sealed oracle missing at {path}; run `make prepare-multims2`"
            )
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), log_path=log_path)

    def __len__(self) -> int:
        return len(self._cases)

    def has_case(self, case_id: str) -> bool:
        return case_id in self._cases

    def available_action_keys(self, case_id: str) -> list[str]:
        if case_id not in self._cases:
            raise OracleAccessError(f"unknown case: {case_id}")
        return sorted(self._cases[case_id]["hidden"])

    def initial(self, case_id: str, *, actor: str = "case_start") -> Measurement:
        if case_id not in self._cases:
            raise OracleAccessError(f"unknown case: {case_id}")
        payload = self._cases[case_id]["initial"]
        measurement = self._measurement(case_id, payload, role="initial")
        self._append_log(case_id, measurement.action, actor)
        return measurement

    def measure(
        self, case_id: str, action_key: str, *, actor: str = "explicit_measure"
    ) -> Measurement:
        if case_id not in self._cases:
            raise OracleAccessError(f"unknown case: {case_id}")
        hidden = self._cases[case_id]["hidden"]
        if action_key not in hidden:
            raise OracleAccessError(
                f"{action_key} is not available for {case_id}; available {sorted(hidden)}"
            )
        measurement = self._measurement(case_id, hidden[action_key], role="measured")
        self._append_log(case_id, action_key, actor)
        return measurement

    def evaluator_hidden(self, case_id: str) -> dict:
        """Evaluator-only access.  Never pass this object to a planner or agent."""
        return self._cases[case_id]["hidden"]

    @staticmethod
    def _measurement(case_id: str, payload: dict, *, role: str) -> Measurement:
        return Measurement(
            case_id=case_id,
            action=str(payload["action"]),
            fragmentation=str(payload["fragmentation"]),
            energy_ev=float(payload["energy_ev"]),
            accession=str(payload["accession"]),
            mz=np.asarray(payload["peaks_mz"], float),
            intensity=np.asarray(payload["peaks_intensity"], float),
            role=role,
        )

    def _append_log(self, case_id: str, action: str, actor: str) -> None:
        entry = {
            "utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "case_id": case_id,
            "action": action,
            "actor": actor,
        }
        with self._lock:
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")


class VirtualInstrument:
    def __init__(self, oracle: OracleStore, *, default_budget: int = 1) -> None:
        self.__oracle = oracle
        self.default_budget = int(default_budget)
        self._started: set[str] = set()
        self._budgets: dict[str, int] = {}
        self._measured: dict[str, set[str]] = {}
        self._initial: dict[str, Measurement] = {}

    @property
    def oracle(self):
        raise PermissionError("The oracle is sealed. Use start/measure/available_actions only.")

    def available_actions(self, case_id: str) -> list[MeasurementAction]:
        return [
            MeasurementAction.for_key(key)
            for key in self.__oracle.available_action_keys(case_id)
            if key in ACTION_SPECS
        ]

    def start(self, case_id: str, *, budget: int | None = None) -> Measurement:
        if case_id in self._started:
            raise OracleAccessError(f"case already started: {case_id}")
        measurement = self.__oracle.initial(case_id)
        self._started.add(case_id)
        self._budgets[case_id] = int(self.default_budget if budget is None else budget)
        self._measured[case_id] = set()
        self._initial[case_id] = measurement
        return measurement

    def measure(self, case_id: str, action: MeasurementAction | str) -> Measurement:
        if case_id not in self._started:
            raise OracleAccessError("case has not been started")
        key = action.key if isinstance(action, MeasurementAction) else str(action)
        if key == "STOP":
            raise OracleAccessError("STOP is not a measurement")
        allowed = {item.key for item in self.available_actions(case_id)}
        if key not in allowed:
            raise OracleAccessError(f"{key} is not an available action; choose from {sorted(allowed)}")
        if key in self._measured[case_id]:
            raise OracleAccessError(f"{key} has already been measured for this case")
        if self._budgets[case_id] <= 0:
            raise OracleAccessError("measurement budget exhausted")
        measurement = self.__oracle.measure(case_id, key)
        self._measured[case_id].add(key)
        self._budgets[case_id] -= 1
        return measurement

    def remaining_budget(self, case_id: str) -> int:
        return int(self._budgets.get(case_id, 0))

    def observed_actions(self, case_id: str) -> list[str]:
        if case_id not in self._initial:
            return []
        return ["CID20"] + sorted(self._measured.get(case_id, set()))

    def initial(self, case_id: str) -> Measurement:
        if case_id not in self._initial:
            raise OracleAccessError("case has not been started")
        return self._initial[case_id]

    def reset(self, case_id: str) -> None:
        self._started.discard(case_id)
        self._budgets.pop(case_id, None)
        self._measured.pop(case_id, None)
        self._initial.pop(case_id, None)

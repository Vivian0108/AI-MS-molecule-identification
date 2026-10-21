"""Sealed virtual instrument.

``OracleStore`` is the only object that holds the hidden 20/30/40 eV experimental
observations.  ``VirtualInstrument`` wraps it, consumes the measurement budget
and is the sole public reveal endpoint.  No planner, retriever, template builder
or agent receives a reference to either object.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ValidationError

from unknownid.core.models import PeakList, PrivateOracleCase
from unknownid.core.spectra import ProcessedSpectrum, preprocess_peaks
from unknownid.paths import ORACLE_LOG

Energy = Literal[20, 30, 40]


class OracleAccessError(RuntimeError):
    pass


@dataclass(frozen=True)
class Measurement:
    case_id: str
    energy: int
    accession: str
    spectrum: ProcessedSpectrum

    def peak_list(self) -> PeakList:
        return PeakList(mz=self.spectrum.mz.tolist(), intensity=self.spectrum.intensity.tolist())

    def public_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "energy_ev": self.energy,
            "accession": self.accession,
            "spectrum": self.peak_list().model_dump(),
            "kind": "measured",
        }


class OracleStore:
    """Read-only hidden observations with an append-only access log."""

    def __init__(self, cases: dict[str, PrivateOracleCase], log_path: Path | None = None):
        self._cases = dict(cases)
        self._log_path = Path(log_path or ORACLE_LOG)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: str | Path, log_path: Path | None = None) -> "OracleStore":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        cases: dict[str, PrivateOracleCase] = {}
        for case_id, item in payload.items():
            try:
                cases[case_id] = PrivateOracleCase.model_validate(item)
            except ValidationError as exc:  # pragma: no cover - corrupted artefact
                raise ValueError(f"invalid private oracle case {case_id}: {exc}") from exc
        return cls(cases, log_path=log_path)

    def __len__(self) -> int:
        return len(self._cases)

    def has_case(self, case_id: str) -> bool:
        return case_id in self._cases

    def measure(self, case_id: str, energy: int, *, actor: str = "virtual_instrument") -> Measurement:
        """Reveal one measured observation and append the access to the log."""
        if case_id not in self._cases:
            raise OracleAccessError(f"unknown case: {case_id}")
        case = self._cases[case_id]
        if int(energy) not in case.hidden_spectra:
            raise OracleAccessError(
                f"{energy} eV is not available for {case_id}; available "
                f"{sorted(case.hidden_spectra)}"
            )
        peak_list = case.hidden_spectra[int(energy)]
        spectrum = preprocess_peaks(peak_list.mz, peak_list.intensity, rel_floor=0.0)
        measurement = Measurement(
            case_id=case_id,
            energy=int(energy),
            accession=case.hidden_accessions[int(energy)],
            spectrum=spectrum,
        )
        self._append_log(case_id, int(energy), actor)
        return measurement

    def _append_log(self, case_id: str, energy: int, actor: str) -> None:
        entry = {
            "utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "case_id": case_id,
            "energy_ev": energy,
            "actor": actor,
        }
        with self._lock:
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")

    # Evaluator-only.  Deliberately named so accidental agent use is obvious.
    def evaluator_truth(self, case_id: str) -> PrivateOracleCase:
        return self._cases[case_id]

    def split(self, case_id: str) -> str:
        return self._cases[case_id].split


class VirtualInstrument:
    """Budget-enforcing facade around :class:`OracleStore`."""

    def __init__(
        self,
        oracle: OracleStore,
        *,
        allowed_energies: tuple[int, ...] = (30, 40),
        default_budget: int = 1,
    ) -> None:
        self.__oracle = oracle
        self.allowed_energies = tuple(int(e) for e in allowed_energies)
        self.default_budget = int(default_budget)
        self._started: set[str] = set()
        self._budgets: dict[str, int] = {}
        self._measured: dict[str, set[int]] = {}
        self._initial: dict[str, Measurement] = {}

    @property
    def oracle(self):
        raise PermissionError(
            "The oracle is sealed.  Use VirtualInstrument.start/measure only."
        )

    def start(self, case_id: str, *, budget: int | None = None) -> Measurement:
        if case_id in self._started:
            raise OracleAccessError(f"case already started: {case_id}")
        if not self.__oracle.has_case(case_id):
            raise OracleAccessError(f"unknown case: {case_id}")
        measurement = self.__oracle.measure(case_id, 20, actor="case_start")
        self._started.add(case_id)
        self._budgets[case_id] = int(self.default_budget if budget is None else budget)
        self._measured[case_id] = set()
        self._initial[case_id] = measurement
        return measurement

    def measure(self, case_id: str, energy: int) -> Measurement:
        if case_id not in self._started:
            raise OracleAccessError("case has not been started")
        energy = int(energy)
        if energy not in self.allowed_energies:
            raise OracleAccessError(
                f"energy {energy} eV is not an allowed action; choose from {self.allowed_energies}"
            )
        if energy in self._measured[case_id]:
            raise OracleAccessError(f"energy {energy} eV has already been measured for this case")
        if self._budgets[case_id] <= 0:
            raise OracleAccessError("measurement budget exhausted")
        measurement = self.__oracle.measure(case_id, energy, actor="explicit_measure")
        self._measured[case_id].add(energy)
        self._budgets[case_id] -= 1
        return measurement

    def remaining_budget(self, case_id: str) -> int:
        return int(self._budgets.get(case_id, 0))

    def reset(self, case_id: str) -> None:
        """Forget one case's budget state (used only when an investigation is discarded)."""
        self._started.discard(case_id)
        self._budgets.pop(case_id, None)
        self._measured.pop(case_id, None)
        self._initial.pop(case_id, None)

    def observed_energies(self, case_id: str) -> list[int]:
        if case_id not in self._initial:
            return []
        return [20] + sorted(self._measured.get(case_id, set()))

    def initial_measurement(self, case_id: str) -> Measurement:
        if case_id not in self._initial:
            raise OracleAccessError("case has not been started")
        return self._initial[case_id]

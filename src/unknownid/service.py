"""Application service shared by the FastAPI app and the Streamlit UI.

The service owns the sealed instrument and the reference library.  It never
returns hidden 30/40 eV spectra before an explicit ``measure`` call and never
returns the true identity at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from unknownid.config import load_config
from unknownid.core.evidence import EvidenceEvaluator
from unknownid.core.models import Investigation, Plan, Ranking
from unknownid.core.retrieve import ReferenceStore
from unknownid.paths import (
    AUDIT_PARQUET,
    CALIBRATION_JSON,
    CURATED,
    LIBRARY_PARQUET,
    MANIFEST_JSON,
    PRIVATE_ORACLE_JSON,
    PUBLIC_CASES_PARQUET,
    ROOT,
)
from unknownid.planner.acquisition import AcquisitionPlanner, PlannerConfig
from unknownid.planner.error_model import ErrorModel
from unknownid.simulator.episodes import CaseRepository, InvestigationSession
from unknownid.simulator.oracle import Measurement, OracleAccessError, OracleStore, VirtualInstrument


class ServiceError(RuntimeError):
    pass


class UnknownIDService:
    def __init__(self, *, default_split: str = "dev") -> None:
        self.selection_cfg = load_config("selection")
        self.acquisition_cfg = load_config("acquisition")
        self.default_split = default_split
        self._sessions: dict[str, InvestigationSession] = {}
        self._choice_index = 0
        self._load()

    def _load(self) -> None:
        if not LIBRARY_PARQUET.exists() or not PUBLIC_CASES_PARQUET.exists():
            raise ServiceError(
                "Curated artefacts are missing. Run `make fetch-data && make prepare` first."
            )
        if not PRIVATE_ORACLE_JSON.exists():
            raise ServiceError("Sealed oracle is missing. Run `make prepare`.")
        self.references = ReferenceStore(
            pd.read_parquet(LIBRARY_PARQUET),
            reference_energies=tuple(self.selection_cfg.get_path("energies.reference", [10, 50])),
            tolerance_da=float(self.selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
            template_method=str(self.selection_cfg.get_path("templates.method", "linear")),
            ppm_tolerance=float(self.selection_cfg.get_path("filters.ppm_precursor", 10.0)),
        )
        self.references.assert_reference_only()
        self.error_model = ErrorModel.load(CURATED / "error_model.json")
        if CALIBRATION_JSON.exists():
            self.calibration = json.loads(CALIBRATION_JSON.read_text(encoding="utf-8"))
        else:
            self.calibration = {
                "method": "disagreement_heuristic",
                "use_monte_carlo_ig": False,
                "reason": "calibration file missing; conservative heuristic fallback",
            }
        self.evaluator = EvidenceEvaluator(
            tolerance_da=float(self.selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
            kappa=float(self.acquisition_cfg.get_path("likelihood.kappa_default", 8.0)),
            neutral_loss_weight=float(self.acquisition_cfg.get_path("scoring.neutral_loss_weight", 0.05)),
            unmatched_penalty=float(self.acquisition_cfg.get_path("scoring.unmatched_penalty", 0.35)),
            min_matched_peaks=int(self.selection_cfg.get_path("filters.min_matched_peaks", 2)),
            prior_floor=float(self.acquisition_cfg.get_path("scoring.prior_floor", 0.0)),
        )
        self.planner_config = PlannerConfig(
            budget=int(self.acquisition_cfg.get_path("measurement_budget", 1)),
            allowed_energies=tuple(self.acquisition_cfg.get_path("allowed_energies", [30, 40])),
            cost=float(self.acquisition_cfg.get_path("cost_per_measurement", 1.0)),
            monte_carlo_samples=int(self.acquisition_cfg.get_path("monte_carlo.samples", 500)),
            seed=int(self.acquisition_cfg.get_path("monte_carlo.seed", 20261020)),
            tempering=float(self.acquisition_cfg.get_path("likelihood.likelihood_tempering", 0.85)),
            stop_ig_threshold=float(self.acquisition_cfg.get_path("confidence.stop_ig_threshold", 0.02)),
            identified_min_support=float(self.acquisition_cfg.get_path("confidence.identified_min_support", 0.72)),
            identified_min_margin=float(self.acquisition_cfg.get_path("confidence.identified_min_margin", 0.22)),
            stop_min_support=float(self.acquisition_cfg.get_path("confidence.stop_min_support", 0.90)),
            stop_min_margin=float(self.acquisition_cfg.get_path("confidence.stop_min_margin", 0.70)),
            tolerance_da=float(self.selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
            max_candidates=int(self.acquisition_cfg.get_path("monte_carlo.max_candidates", 12)),
        )
        self.planner = AcquisitionPlanner(
            self.planner_config,
            method=self.calibration.get("method", "disagreement_heuristic"),
            error_model=self.error_model,
        )
        self.oracle = OracleStore.load(PRIVATE_ORACLE_JSON)
        self.instrument = VirtualInstrument(
            self.oracle,
            allowed_energies=tuple(self.acquisition_cfg.get_path("allowed_energies", [30, 40])),
            default_budget=int(self.acquisition_cfg.get_path("measurement_budget", 1)),
        )
        self.repository = CaseRepository.load(self.references)

    # -- discovery ---------------------------------------------------------
    def case_ids(self, split: str | None = None) -> list[str]:
        split = self.default_split if split is None else split
        return self.repository.case_ids(split)

    def next_case_id(self, split: str | None = None) -> str:
        ids = self.case_ids(split)
        if not ids:
            raise ServiceError(f"no cases available for split {split or self.default_split}")
        unstarted = [case_id for case_id in ids if case_id not in self._sessions]
        pool = unstarted or ids
        case_id = pool[self._choice_index % len(pool)]
        self._choice_index += 1
        return case_id

    def case_summary(self, case_id: str) -> dict:
        case = self.repository.case(case_id)
        return {
            "case_id": case_id,
            "split": self.repository.split(case_id),
            "precursor_mz": case.precursor_mz,
            "adduct": case.adduct,
            "instrument_model": case.instrument_model,
            "n_candidates": len(case.candidate_ids),
            "measurement_budget": case.measurement_budget,
            "available_energies": case.available_energies,
        }

    # -- session lifecycle -------------------------------------------------
    def start_case(self, case_id: str | None = None, split: str | None = None) -> dict:
        if case_id is None:
            case_id = self.next_case_id(split)
        if not self.repository.has_case(case_id):
            raise ServiceError(f"unknown case: {case_id}")
        session = self._sessions.get(case_id)
        if session is None:
            session = InvestigationSession(
                case_id,
                self.repository,
                self.instrument,
                self.evaluator,
                self.planner,
                self.error_model,
            )
            self._sessions[case_id] = session
        return self._state_payload(session, include_initial=True)

    def session(self, case_id: str) -> InvestigationSession:
        if case_id not in self._sessions:
            raise ServiceError(f"case has not been started: {case_id}")
        return self._sessions[case_id]

    def _state_payload(self, session: InvestigationSession, *, include_initial: bool = False) -> dict:
        payload = {
            "case": self.case_summary(session.case_id),
            "candidates": [self.references.metadata(cid) for cid in session.public_case.candidate_ids],
            "observed_energies": session.observed_energies,
            "remaining_budget": session.remaining_budget,
            "ranking": session.ranking().model_dump(),
            "plan": session.plan().model_dump(),
            "calibration_method": self.planner.method,
            "calibration_validated": bool(self.calibration.get("dev_ig_validation")),
        }
        if include_initial:
            measurement = session.observation(20)
            measurement.pop("accession", None)
            measurement["accession"] = None
            measurement["note"] = "Initial measured 20 eV spectrum. The source accession is embargoed until the investigation is stopped."
            payload["observation"] = measurement
        return payload

    def ranking(self, case_id: str) -> dict:
        return self.session(case_id).ranking().model_dump()

    def plan(self, case_id: str) -> dict:
        session = self.session(case_id)
        plan = session.plan()
        payload = plan.model_dump()
        payload["labels"] = {
            "measured": "real archived measurement revealed by the virtual instrument",
            "reference": "static 10/50 eV library spectrum",
            "interpolated": "template constructed from 10/50 eV references",
            "predicted": "hypothetical Monte-Carlo spectrum used only for planning",
        }
        return payload

    def measure(self, case_id: str, energy_ev: int) -> dict:
        session = self.session(case_id)
        measurement = session.measure(int(energy_ev))
        payload = measurement.public_dict()
        payload.pop("accession", None)
        payload["accession"] = None
        payload["note"] = "Measured 30/40 eV spectrum. Accession is embargoed until the investigation is stopped."
        return {
            "measurement": payload,
            "ranking": session.ranking().model_dump(),
            "plan": session.plan().model_dump(),
            "remaining_budget": session.remaining_budget,
        }

    def stop(self, case_id: str) -> dict:
        session = self.session(case_id)
        investigation = session.stop()
        return {
            "investigation": investigation.model_dump(),
            "report_markdown": session.export_markdown(),
        }

    def reset_case(self, case_id: str) -> None:
        """Discard a finished session so the same case can be investigated again."""
        self._sessions.pop(case_id, None)
        self.instrument.reset(case_id)

    def template(self, case_id: str, candidate_id: str, energy_ev: int) -> dict:
        """Return an energy-interpolated library template.

        Templates are built only from the static 10/50 eV references, so this
        never exposes a hidden 30/40 eV measurement.
        """
        session = self.session(case_id)
        if int(energy_ev) not in (10, 20, 30, 40, 50):
            raise ServiceError("template energy must be one of 10/20/30/40/50 eV")
        try:
            template = session.template(candidate_id, int(energy_ev))
        except KeyError as exc:
            raise ServiceError(str(exc)) from exc
        return {
            "candidate_id": candidate_id,
            "energy_ev": int(energy_ev),
            "kind": "interpolated",
            "note": "Constructed from the static 10/50 eV library references; not a measurement.",
            "spectrum": {"mz": template.mz.tolist(), "intensity": template.intensity.tolist()},
        }

    def report(self, case_id: str) -> dict:
        session = self.session(case_id)
        investigation = session.investigation()
        return {
            "investigation": investigation.model_dump(),
            "report_markdown": session.export_markdown(),
            "provenance": investigation.provenance,
        }

    # -- provenance --------------------------------------------------------
    def provenance(self) -> dict:
        manifest = {}
        if MANIFEST_JSON.exists():
            manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
        audit = {}
        if AUDIT_PARQUET.exists():
            frame = pd.read_parquet(AUDIT_PARQUET)
            audit = {
                row["metric"]: row["value"]
                for _, row in frame.iterrows()
                if row["category"] in {"snapshot", "difficulty", "splits", "identity_qc", "spectra"}
            }
        return {
            "source_repository": manifest.get("source_repository"),
            "source_commit": manifest.get("source_commit"),
            "retrieved_at_utc": manifest.get("retrieved_at_utc"),
            "record_count": manifest.get("record_count"),
            "instrument": self.selection_cfg.get_path("instrument"),
            "energies": self.selection_cfg.get_path("energies"),
            "library_molecules": len(self.references),
            "cases": {
                "train": len(self.repository.case_ids("train")),
                "dev": len(self.repository.case_ids("dev")),
                "test": len(self.repository.case_ids("test")),
            },
            "audit": audit,
            "banner": "Virtual instrument uses archived experimental measurements. No spectra are generated for identification.",
        }

"""Application service shared by the SpectraPilot UI and API."""

from __future__ import annotations

import json
from pathlib import Path

from spectrapilot.data.repository import CaseRepository
from spectrapilot.paths import CURATED, load_config
from spectrapilot.planning.oracle import OracleStore, VirtualInstrument
from spectrapilot.planning.separation import SeparationPlanner
from spectrapilot.planning.session import InvestigationSession
from spectrapilot.science.scoring import CandidateScorer
from spectrapilot.science.templates import ReferenceStore


class ServiceError(RuntimeError):
    pass


class SpectraPilotService:
    def __init__(self, *, default_split: str = "dev") -> None:
        self.default_split = default_split
        self.selection_cfg = load_config("multims2")
        self.policy_cfg = load_config("policies")
        self._sessions: dict[str, InvestigationSession] = {}
        self._choice_index = 0
        self._load()

    def _load(self) -> None:
        try:
            self.references = ReferenceStore.load(
                ppm_tolerance=float(self.selection_cfg.get_path("candidate_pool.ppm", 10.0))
            )
            self.repository = CaseRepository.load(self.references)
            self.oracle = OracleStore.load()
        except FileNotFoundError as exc:
            raise ServiceError(str(exc)) from exc
        self.instrument = VirtualInstrument(self.oracle, default_budget=1)
        self.scorer = CandidateScorer(
            tolerance_da=float(self.selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
            tempering=0.85,
        )
        self.planner = SeparationPlanner(
            stop_support=float(self.policy_cfg.get_path("planner.stop_support", 0.90)),
            stop_margin=float(self.policy_cfg.get_path("planner.stop_margin", 0.65)),
            stop_score=float(self.policy_cfg.get_path("planner.stop_score", 0.01)),
            identified_min_support=float(self.policy_cfg.get_path("confidence.identified_min_support", 0.72)),
            identified_min_margin=float(self.policy_cfg.get_path("confidence.identified_min_margin", 0.22)),
            identified_min_fit=float(self.policy_cfg.get_path("confidence.identified_min_fit", 0.30)),
            identified_min_matched_peaks=int(self.policy_cfg.get_path("confidence.identified_min_matched_peaks", 2)),
            ead_cost_ratio=float(self.policy_cfg.get_path("planner.ead_cost_ratio", 1.0)),
            tolerance_da=float(self.selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
        )

    # -- discovery ---------------------------------------------------------
    def case_ids(self, split: str | None = None) -> list[str]:
        return self.repository.case_ids(self.default_split if split is None else split)

    def case_summary(self, case_id: str) -> dict:
        return self.repository.case(case_id).public_dict()

    def next_case_id(self, split: str | None = None) -> str:
        ids = self.case_ids(split)
        if not ids:
            raise ServiceError(f"no cases for split {split or self.default_split}")
        unstarted = [case_id for case_id in ids if case_id not in self._sessions]
        pool = unstarted or ids
        case_id = pool[self._choice_index % len(pool)]
        self._choice_index += 1
        return case_id

    # -- lifecycle ---------------------------------------------------------
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
                self.scorer,
                self.planner,
            )
            self._sessions[case_id] = session
        return self._state(session, include_initial=True)

    def session(self, case_id: str) -> InvestigationSession:
        if case_id not in self._sessions:
            raise ServiceError(f"case has not been started: {case_id}")
        return self._sessions[case_id]

    def _state(self, session: InvestigationSession, *, include_initial: bool = False) -> dict:
        case = self.case_summary(session.case_id)
        payload = {
            "case": case,
            "candidates": [self.references.metadata(cid) for cid in case["candidate_ids"]],
            "observed_actions": session.observed_actions,
            "remaining_budget": session.remaining_budget,
            "ranking": session.ranking().model_dump(),
            "plan": session.plan().model_dump(),
            "calibration_method": "separation_heuristic",
            "calibration_validated": False,
            "labels": {
                "measured": "real archived MultiMS2 measurement",
                "reference": "explicitly allowed CID60 reference",
                "predicted": "train-only structure-kNN template",
            },
        }
        if include_initial:
            measurement = session.observation("CID20").public_dict(include_accession=False)
            measurement["note"] = "Initial measured CID20 spectrum; accession embargoed until stop."
            payload["observation"] = measurement
        return payload

    def ranking(self, case_id: str) -> dict:
        return self.session(case_id).ranking().model_dump()

    def plan(self, case_id: str) -> dict:
        return self.session(case_id).plan().model_dump()

    def measure(self, case_id: str, action_key: str) -> dict:
        session = self.session(case_id)
        measurement = session.measure(action_key)
        payload = measurement.public_dict(include_accession=False)
        payload["note"] = "Measured spectrum; accession embargoed until the investigation is stopped."
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
        self._sessions.pop(case_id, None)
        self.instrument.reset(case_id)

    def template(self, case_id: str, candidate_id: str, action: str) -> dict:
        session = self.session(case_id)
        try:
            return session.template_payload(candidate_id, action)
        except KeyError as exc:
            raise ServiceError(str(exc)) from exc

    def report(self, case_id: str) -> dict:
        session = self.session(case_id)
        investigation = session.investigation()
        return {
            "investigation": investigation.model_dump(),
            "report_markdown": session.export_markdown(),
            "provenance": investigation.provenance,
        }

    def provenance(self) -> dict:
        manifest = {}
        path = CURATED / "manifest.json"
        if path.exists():
            manifest = json.loads(path.read_text(encoding="utf-8"))
        return {
            "dataset": "MultiMS2",
            "source_repository": manifest.get("source_repository"),
            "source_commit": manifest.get("source_commit"),
            "paper_doi": manifest.get("paper_doi"),
            "license": manifest.get("license"),
            "record_count": manifest.get("qc_pass_records"),
            "selected_records": manifest.get("selected_records"),
            "library_molecules": len(self.references),
            "sealed_cases": len(self.oracle),
            "cases": {
                split: len(self.repository.case_ids(split))
                for split in ("train", "dev", "test")
            },
            "actions": ["CID40", "EAD16", "STOP"],
            "banner": (
                "Virtual instrument replays archived experimental measurements. "
                "CID40 and EAD16 peaks are invisble until measure()."
            ),
        }

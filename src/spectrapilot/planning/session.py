"""Budgeted investigation session: plan first, reveal second, update third."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import numpy as np

from spectrapilot.data.repository import CaseRepository
from spectrapilot.models import Evidence, Investigation, Measurement, Plan, Ranking
from spectrapilot.paths import CURATED, ORACLE_PRIVATE, load_config
from spectrapilot.planning.actions import MeasurementAction, stop_action
from spectrapilot.planning.oracle import OracleAccessError, VirtualInstrument
from spectrapilot.planning.separation import SeparationPlanner
from spectrapilot.science.scoring import CandidateScorer, merge_evidence
from spectrapilot.science.templates import ReferenceStore
from unknownid.core.posterior import rank_candidates, top2_margin
from unknownid.core.spectra import preprocess_peaks


class ActionLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or (ORACLE_PRIVATE / "actions.jsonl"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, entry: dict) -> None:
        payload = {
            "utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            **entry,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")


class InvestigationSession:
    def __init__(
        self,
        case_id: str,
        repository: CaseRepository,
        instrument: VirtualInstrument,
        scorer: CandidateScorer,
        planner: SeparationPlanner,
        *,
        action_log: ActionLog | None = None,
        decision_overrides: dict | None = None,
        budget: int | None = None,
    ) -> None:
        self.case_id = case_id
        self.repository = repository
        self.instrument = instrument
        self.scorer = scorer
        self.planner = planner
        self.action_log = action_log or ActionLog()
        self.decision_overrides = dict(decision_overrides or {})
        self.budget = budget
        self.case = repository.case(case_id)
        self.candidates = repository.candidates(case_id)
        self.templates = repository.references
        self._evidence: dict[str, Evidence] = {}
        self._weights: dict[str, float] = {}
        self._actions: list[MeasurementAction] = []
        self._observations: dict[str, Measurement] = {}
        self._stopped = False
        self._decision = "AMBIGUOUS"
        self._qc: dict = {}
        initial = self.instrument.start(
            case_id, budget=self.budget if self.budget is not None else self.case.measurement_budget
        )
        self._observe(initial, initial=True)
        self._initial_weights = dict(self._weights)
        self._initial_order = rank_candidates(self._weights)

    # -- state -------------------------------------------------------------
    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def observed_actions(self) -> list[str]:
        return self.instrument.observed_actions(self.case_id)

    @property
    def remaining_budget(self) -> int:
        return self.instrument.remaining_budget(self.case_id)

    def _observe(self, measurement: Measurement, *, initial: bool = False) -> None:
        self._observations[measurement.action] = measurement
        spectrum = preprocess_peaks(measurement.mz, measurement.intensity, rel_floor=0.0)
        if initial:
            evidence, weights = self.scorer.initial_rank(
                spectrum,
                self.candidates,
                self.templates,
                "CID20",
                precursor_mz=self.case.precursor_mz,
            )
            self._evidence = evidence
            self._weights = weights
        else:
            fresh, weights = self.scorer.update(
                self._weights,
                spectrum,
                self.candidates,
                self.templates,
                measurement.action,
                precursor_mz=self.case.precursor_mz,
            )
            self._evidence = merge_evidence(self._evidence, fresh)
            self._weights = weights
            for cid, item in self._evidence.items():
                item.weight = float(weights.get(cid, 0.0))

    def _ordered(self) -> list[Evidence]:
        return [
            self._evidence[cid]
            for cid in rank_candidates(self._weights)
            if cid in self._evidence
        ]

    # -- public ------------------------------------------------------------
    def ranking(self) -> Ranking:
        return Ranking(
            case_id=self.case_id,
            observed_actions=self.observed_actions,
            candidates=[item.public_dict() for item in self._ordered()],
        )

    def plan(self) -> Plan:
        available = self.instrument.available_actions(self.case_id)
        top_fit, top_matched = 0.0, 0
        if self._weights:
            top = rank_candidates(self._weights)[0]
            evidence = self._evidence.get(top)
            if evidence is not None:
                top_fit = max(evidence.similarity_by_action.values(), default=0.0)
                top_matched = max(evidence.matched_peaks_by_action.values(), default=0)
        return self.planner.plan(
            self.case_id,
            weights=self._weights,
            candidates=self.candidates,
            store=self.templates,
            observed_actions=self.observed_actions,
            remaining_budget=self.remaining_budget,
            available_actions=available,
            top_fit=top_fit,
            top_matched=top_matched,
        )

    def measure(self, action_key: str) -> Measurement:
        if self._stopped:
            raise OracleAccessError("investigation is already stopped")
        if action_key == "STOP":
            raise OracleAccessError("STOP is not a measurement; call stop()")
        action = MeasurementAction.for_key(action_key)
        # Log the premeasurement plan and evidence hash before revealing peaks.
        self.action_log.write(
            {
                "case_id": self.case_id,
                "kind": "plan_before_measure",
                "chosen_action": action.key,
                "observed_before": self.observed_actions,
                "remaining_budget_before": self.remaining_budget,
                "weights": {cid: round(float(w), 8) for cid, w in self._weights.items()},
            }
        )
        try:
            measurement = self.instrument.measure(self.case_id, action)
        except Exception as exc:
            self.action_log.write(
                {
                    "case_id": self.case_id,
                    "kind": "measure_rejected",
                    "action": action.key,
                    "error": str(exc),
                }
            )
            raise
        self._actions.append(action)
        self._observe(measurement)
        return measurement

    def stop(self) -> Investigation:
        if self._stopped:
            return self.investigation()
        self.action_log.write(
            {
                "case_id": self.case_id,
                "kind": "stop",
                "observed_actions": self.observed_actions,
                "remaining_budget": self.remaining_budget,
            }
        )
        self._actions.append(stop_action())
        self._stopped = True
        self._decision, self._qc = self._final_decision()
        return self.investigation()

    def investigation(self) -> Investigation:
        top = rank_candidates(self._weights)[0] if self._weights else None
        identified = self._decision == "IDENTIFIED"
        return Investigation(
            case_id=self.case_id,
            observed_actions=self.observed_actions,
            candidate_evidence=[item.public_dict() for item in self._ordered()],
            selected_actions=[action.public_dict() for action in self._actions],
            decision=self._decision if self._stopped else "AMBIGUOUS",
            predicted_identity=top if identified else None,
            confidence=float(self._weights.get(top, 0.0)) if identified and top else None,
            limitations=self._limitations(),
            qc=self._qc or self.qc(),
            provenance=self._provenance(),
        )

    def observation(self, action: str) -> Measurement:
        return self._observations[str(action)]

    def template_payload(self, candidate_id: str, action: str) -> dict:
        template = self.templates.template(candidate_id, action)
        return {
            "candidate_id": candidate_id,
            "action": action,
            "kind": "predicted" if template.source != "reference_cid60" else "reference",
            "source": template.source,
            "reliability": template.reliability,
            "n_donors": template.n_donors,
            "spectrum": {
                "mz": template.mz.tolist(),
                "intensity": template.intensity.tolist(),
            },
        }

    # -- decision ----------------------------------------------------------
    def qc(self) -> dict:
        checks = {
            "n_candidates": len(self.candidates),
            "initial_peaks": int(self._observations.get("CID20").mz.size) if "CID20" in self._observations else 0,
            "all_candidates_within_ppm": all(
                abs(c.precursor_mz - self.case.precursor_mz) / self.case.precursor_mz * 1e6
                <= self.templates.ppm_tolerance
                for c in self.candidates
            ),
            "adduct_consistent": all(c.adduct == self.case.adduct for c in self.candidates),
            "observed_actions": self.observed_actions,
            "template_actions": ["CID20", "CID40", "EAD16"],
        }
        reasons = []
        if not checks["all_candidates_within_ppm"]:
            reasons.append("candidate_precursor_outside_tolerance")
        if not checks["adduct_consistent"]:
            reasons.append("adduct_mismatch")
        if checks["initial_peaks"] < 3:
            reasons.append("initial_spectrum_too_sparse")
        checks["passed"] = not reasons
        checks["rejection_reasons"] = reasons
        return checks

    def _final_decision(self) -> tuple[str, dict]:
        cfg = load_config("policies")
        qc = self.qc()
        if not self._weights:
            return "OUT_OF_LIBRARY", qc
        if not qc["passed"]:
            return "INSUFFICIENT_DATA", qc
        top = rank_candidates(self._weights)[0]
        evidence = self._evidence.get(top)
        if evidence is None:
            return "OUT_OF_LIBRARY", qc
        best_fit = max(evidence.similarity_by_action.values(), default=0.0)
        best_matched = max(evidence.matched_peaks_by_action.values(), default=0)
        support = float(self._weights.get(top, 0.0))
        margin = top2_margin(self._weights)
        min_fit = float(self._policy("confidence.identified_min_fit", 0.30))
        min_support = float(self._policy("confidence.identified_min_support", 0.72))
        min_margin = float(self._policy("confidence.identified_min_margin", 0.22))
        min_matched = int(self._policy("confidence.identified_min_matched_peaks", 2))
        ool_fit = float(self._policy("confidence.out_of_library_max_fit", 0.20))
        ool_matched = int(self._policy("confidence.out_of_library_max_matched_peaks", 1))
        if best_fit < ool_fit and best_matched <= ool_matched:
            return "OUT_OF_LIBRARY", qc
        if best_fit < min_fit or best_matched < min_matched:
            return "OUT_OF_LIBRARY", qc
        # A single precursor-consistent library entry is a legitimate
        # accurate-mass identification, but it is reported as a separate
        # "precursor-unique" stratum and never as MS/MS confirmation.
        if len(self.candidates) == 1 and support >= min_support:
            return "IDENTIFIED", qc
        # Same-connectivity competitors are not separable by achiral MS/MS.
        connectivity = top.split("-")[0]
        stereo_competitor = any(
            cid != top
            and cid.split("-")[0] == connectivity
            and self._weights.get(cid, 0.0) >= 0.10
            for cid in self._weights
        )
        if support >= min_support and margin >= min_margin and not stereo_competitor:
            return "IDENTIFIED", qc
        return "AMBIGUOUS", qc

    def _policy(self, dotted: str, default):
        if dotted in self.decision_overrides:
            return self.decision_overrides[dotted]
        cfg = load_config("policies")
        return cfg.get_path(dotted, default)

    def _limitations(self) -> list[str]:
        limitations = [
            "Closed-world candidate set: the true structure is assumed to be present unless the open-world test removes it.",
            "The CID40 template is a CID60 reference when available; this is an explicitly labelled reference-anchored track with an energy mismatch.",
            "The EAD16 template is a train-only structure-kNN prediction, not a measured target spectrum.",
            "Candidate weights are relative support, not calibrated molecular-identity probabilities.",
            "MS/MS cannot distinguish stereoisomers without orthogonal evidence.",
            "This is single-compound standard identification, not an end-to-end LC-MS mixture workflow.",
        ]
        if self._stopped and self._decision == "AMBIGUOUS":
            limitations.append("The evidence did not satisfy the precommitted identification rule; the result is abstained.")
        if self._stopped and self._decision == "OUT_OF_LIBRARY":
            limitations.append("No candidate produced sufficient matched evidence at the chosen evidence standard.")
        if self._stopped and self._decision == "INSUFFICIENT_DATA":
            limitations.append("The observation or candidate templates were insufficient for a supported decision.")
        return limitations

    def _provenance(self) -> dict:
        manifest = {}
        manifest_path = CURATED / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {
            "case_id": self.case_id,
            "observed_accessions": {
                action: measurement.accession
                for action, measurement in sorted(self._observations.items())
            },
            "template_sources": {
                candidate_id: {
                    action: self.templates.template(candidate_id, action).source
                    for action in ("CID20", "CID40", "EAD16")
                }
                for candidate_id in self.case.candidate_ids[:8]
            },
            "source_repository": "https://github.com/zamboni-lab/MultiMS2",
            "source_commit": manifest.get("source_commit", "9219d19d8ef370a1ef0eadf0594b7dfe5e2bf83a"),
            "instrument_model": self.case.instrument_model,
            "adduct": self.case.adduct,
            "weights_are_calibrated": False,
            "planner_method": "separation_heuristic",
            "note": "Observed accessions are released after the investigation is stopped.",
        }

    def export_markdown(self) -> str:
        investigation = self.investigation()
        lines = [
            f"# SpectraPilot investigation report — {investigation.case_id}",
            "",
            f"**Decision:** `{investigation.decision}`",
            f"**Observed actions:** {', '.join(investigation.observed_actions)}",
            f"**Predicted identity:** {investigation.predicted_identity or '—'}",
            "",
            "| Rank | Candidate | Formula | Relative support | Cosine by action | Matched peaks |",
            "|---:|---|---|---:|---|---|",
        ]
        for index, item in enumerate(investigation.candidate_evidence[:10], start=1):
            cosine = ", ".join(
                f"{action}: {value:.3f}" for action, value in sorted(item["similarity_by_action"].items())
            )
            matched = ", ".join(
                f"{action}: {value}" for action, value in sorted(item["matched_peaks_by_action"].items())
            )
            lines.append(
                f"| {index} | {item['name'] or item['candidate_id']} | {item['formula']} | "
                f"{item['weight']:.3f} | {cosine} | {matched} |"
            )
        lines += [
            "",
            "## Provenance",
            "",
        ]
        for action, accession in investigation.provenance.get("observed_accessions", {}).items():
            lines.append(f"- **{action} measured observation:** {accession}")
        lines += ["", "## Limitations", ""]
        lines += [f"- {item}" for item in investigation.limitations]
        lines += [
            "",
            "> Relative support is not a calibrated identity probability. "
            "MS/MS similarity alone is not proof of molecular identity.",
            "",
        ]
        return "\n".join(lines)

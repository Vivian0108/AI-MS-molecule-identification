"""Budgeted investigation session: plan first, reveal second, update third."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from spectrapilot.data.repository import CaseRepository
from spectrapilot.models import Evidence, Investigation, Measurement, Plan, Ranking
from spectrapilot.paths import CURATED, ORACLE_PRIVATE, load_config
from spectrapilot.planning.actions import MeasurementAction, stop_action
from spectrapilot.planning.interventions import (
    InterventionError,
    PeakExclusion,
    spectrum_sha256,
    validate_reason,
)
from spectrapilot.planning.oracle import OracleAccessError, VirtualInstrument
from spectrapilot.planning.separation import SeparationPlanner
from spectrapilot.science.scoring import CandidateScorer, merge_evidence
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
        self._active_exclusions: dict[str, PeakExclusion] = {}
        self._intervention_history: list[dict] = []
        self._next_intervention = 1
        self._stopped = False
        self._decision = "AMBIGUOUS"
        self._qc: dict = {}
        initial = self.instrument.start(
            case_id, budget=self.budget if self.budget is not None else self.case.measurement_budget
        )
        self._observe(initial)
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

    def _observe(self, measurement: Measurement) -> None:
        # Own a copy: edits and caller mutations must not alter archived data.
        self._observations[measurement.action] = deepcopy(measurement)
        self._replay_evidence()

    def _effective_observation(self, action: str) -> Measurement:
        original = self._observations[action]
        keep = np.ones(original.mz.size, dtype=bool)
        for exclusion in self._active_exclusions.values():
            if exclusion.action == action:
                keep[exclusion.peak_index] = False
        effective = deepcopy(original)
        effective.mz = original.mz[keep].copy()
        effective.intensity = original.intensity[keep].copy()
        return effective

    def _replay_evidence(self) -> None:
        """Recompute locally, in acquisition order, without any oracle calls.

        Build a fresh state before assigning it, so a failed edit can roll back
        its mask without partially mutating the current evidence.
        """
        evidence, weights = {}, {}
        for index, action in enumerate(self._observations):
            measurement = self._effective_observation(action)
            spectrum = preprocess_peaks(measurement.mz, measurement.intensity, rel_floor=0.0)
            if index == 0:
                evidence, weights = self.scorer.initial_rank(
                    spectrum,
                    self.candidates,
                    self.templates,
                    "CID20",
                    precursor_mz=self.case.precursor_mz,
                )
            else:
                fresh, weights = self.scorer.update(
                    weights,
                    spectrum,
                    self.candidates,
                    self.templates,
                    action,
                    precursor_mz=self.case.precursor_mz,
                )
                evidence = merge_evidence(evidence, fresh)
                for cid, item in evidence.items():
                    item.weight = float(weights.get(cid, 0.0))
        self._evidence, self._weights = evidence, weights

    def exclude_observed_peak(self, action: str, peak_index: int, reason: str) -> dict:
        if self._stopped:
            raise InterventionError("cannot edit a stopped investigation")
        if action not in self._observations:
            raise InterventionError("can only edit an already observed action")
        original = self._observations[action]
        if type(peak_index) is not int or not 0 <= peak_index < original.mz.size:
            raise InterventionError("peak_index must address the original observed peak array")
        reason = validate_reason(reason)
        if any(
            e.action == action and e.peak_index == peak_index
            for e in self._active_exclusions.values()
        ):
            raise InterventionError("peak already has an active exclusion")
        intervention_id = f"exclusion-{self._next_intervention:04d}"
        exclusion = PeakExclusion(
            intervention_id=intervention_id,
            case_id=self.case_id,
            action=action,
            peak_index=peak_index,
            mz=float(original.mz[peak_index]),
            intensity=float(original.intensity[peak_index]),
            original_spectrum_sha256=spectrum_sha256(original),
            reason=reason,
        )
        self._active_exclusions[intervention_id] = exclusion
        try:
            self._replay_evidence()
        except Exception:
            self._active_exclusions.pop(intervention_id)
            raise
        self._next_intervention += 1
        event = {"kind": "exclude_observed_peak", **exclusion.public_dict()}
        self._intervention_history.append(event)
        self.action_log.write(event)
        return deepcopy(event)

    def undo_intervention(self, intervention_id: str, reason: str) -> dict:
        if self._stopped:
            raise InterventionError("cannot edit a stopped investigation")
        reason = validate_reason(reason)
        if intervention_id not in self._active_exclusions:
            raise InterventionError("unknown or already undone intervention")
        previous = dict(self._active_exclusions)
        exclusion = self._active_exclusions.pop(intervention_id)
        try:
            self._replay_evidence()
        except Exception:
            self._active_exclusions = previous
            raise
        event = {
            "kind": "undo_peak_exclusion",
            "case_id": self.case_id,
            "intervention_id": intervention_id,
            "reason": reason,
            "action": exclusion.action,
            "original_spectrum_sha256": exclusion.original_spectrum_sha256,
        }
        self._intervention_history.append(event)
        self.action_log.write(event)
        return deepcopy(event)

    def evidence_state(self) -> dict:
        """Public observed-evidence snapshot; the decision is a preview until stop."""
        decision, qc = self._final_decision()
        return {
            "case_id": self.case_id,
            "observed_actions": self.observed_actions,
            "remaining_budget": self.remaining_budget,
            "stopped": self.stopped,
            "ranking": self.ranking().model_dump(),
            "plan": self.plan().model_dump(),
            "decision_if_stopped": decision,
            "qc": qc,
            "active_peak_exclusions": [e.public_dict() for e in self._active_exclusions.values()],
            "intervention_history": deepcopy(self._intervention_history),
            "observations": {
                action: {
                    "original_spectrum_sha256": spectrum_sha256(original),
                    "original_peak_count": int(original.mz.size),
                    "effective_peak_count": int(self._effective_observation(action).mz.size),
                }
                for action, original in self._observations.items()
            },
        }

    def _ordered(self) -> list[Evidence]:
        return [
            self._evidence[cid] for cid in rank_candidates(self._weights) if cid in self._evidence
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
            active_peak_exclusions=[e.public_dict() for e in self._active_exclusions.values()],
            intervention_history=deepcopy(self._intervention_history),
        )

    def observation(self, action: str) -> Measurement:
        return deepcopy(self._observations[str(action)])

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
            "initial_peaks": int(self._effective_observation("CID20").mz.size)
            if "CID20" in self._observations
            else 0,
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
            cid != top and cid.split("-")[0] == connectivity and self._weights.get(cid, 0.0) >= 0.10
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
            limitations.append(
                "The evidence did not satisfy the precommitted identification rule; the result is abstained."
            )
        if self._stopped and self._decision == "OUT_OF_LIBRARY":
            limitations.append(
                "No candidate produced sufficient matched evidence at the chosen evidence standard."
            )
        if self._stopped and self._decision == "INSUFFICIENT_DATA":
            limitations.append(
                "The observation or candidate templates were insufficient for a supported decision."
            )
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
            }
            if self._stopped
            else {},
            "template_sources": {
                candidate_id: {
                    action: self.templates.template(candidate_id, action).source
                    for action in ("CID20", "CID40", "EAD16")
                }
                for candidate_id in self.case.candidate_ids[:8]
            },
            "source_repository": "https://github.com/zamboni-lab/MultiMS2",
            "source_commit": manifest.get(
                "source_commit", "9219d19d8ef370a1ef0eadf0594b7dfe5e2bf83a"
            ),
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
                f"{action}: {value:.3f}"
                for action, value in sorted(item["similarity_by_action"].items())
            )
            matched = ", ".join(
                f"{action}: {value}"
                for action, value in sorted(item["matched_peaks_by_action"].items())
            )
            lines.append(
                f"| {index} | {item['name'] or item['candidate_id']} | {item['formula']} | "
                f"{item['weight']:.3f} | {cosine} | {matched} |"
            )
        lines += [
            "",
            "## Evidence interventions",
            "",
            "Peak exclusions are user-directed sensitivity edits, not proof of contamination. "
            "Original observations are preserved; active exclusions affect scoring and QC.",
            "",
        ]
        active_ids = set(self._active_exclusions)
        if not self._intervention_history:
            lines.append("No evidence interventions.")
        for event in self._intervention_history:
            reason = event["reason"].replace("\\", "\\\\").replace("`", "\\`").replace("\n", " ")
            if event["kind"] == "exclude_observed_peak":
                status = "active" if event["intervention_id"] in active_ids else "undone"
                lines.append(
                    f"- {event['intervention_id']}: exclude {event['action']} peak index "
                    f"{event['peak_index']} (m/z {event['mz']:.6f}; {status}); reason: {reason}. "
                    f"Original spectrum SHA-256: `{event['original_spectrum_sha256']}`."
                )
            else:
                lines.append(f"- Undo {event['intervention_id']}; reason: {reason}.")
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

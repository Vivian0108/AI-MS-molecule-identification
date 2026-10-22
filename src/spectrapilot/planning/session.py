"""Budgeted investigation session: plan first, reveal second, update third.

v3 separates four things v2 conflated (see spec §1.1):

1. **ranking** — always produced;
2. **retrieval uniqueness** — a unique precursor match is not proof of structure;
3. **spectral support** — requires a *trustworthy* template, not just a cosine;
4. **open-world rejection** — only from reliable experimental evidence or a
   validated risk model, never from a weak predicted template.

The frozen v2 decision rule is retained verbatim under ``decision_version=
"v2_legacy"`` so the published v2 numbers stay reproducible.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import numpy as np

from spectrapilot.data.repository import CaseRepository
from spectrapilot.models import (
    ACCEPTED_STATUSES,
    LEGACY_STATUS_MAP,
    PROOF_TIER,
    Evidence,
    EvidenceStatus,
    Investigation,
    Measurement,
    Plan,
    Ranking,
)
from spectrapilot.paths import CURATED, ORACLE_PRIVATE, load_config
from spectrapilot.planning.actions import MeasurementAction, stop_action
from spectrapilot.planning.oracle import OracleAccessError, VirtualInstrument
from spectrapilot.planning.separation import SeparationPlanner
from spectrapilot.science.scoring import CandidateScorer, merge_evidence
from spectrapilot.science.templates import ReferenceStore
from unknownid.core.posterior import rank_candidates, top2_margin
from unknownid.core.spectra import preprocess_peaks

DECISION_VERSIONS = ("v3", "v2_legacy")


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


def observation_digest(observations: Mapping[str, Measurement]) -> str:
    """Stable digest of the *public* observations seen so far."""
    payload = []
    for action in sorted(observations):
        measurement = observations[action]
        payload.append(
            {
                "action": action,
                "mz": np.round(np.asarray(measurement.mz, float), 6).tolist(),
                "intensity": np.round(np.asarray(measurement.intensity, float), 6).tolist(),
            }
        )
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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
        decision_version: str = "v3",
        hypotheses_generator=None,
        open_world_model=None,
        precommit_model_digest: str | None = None,
        template_store=None,
        calibrator=None,
    ) -> None:
        if decision_version not in DECISION_VERSIONS:
            raise ValueError(f"unknown decision_version: {decision_version}")
        self.case_id = case_id
        self.repository = repository
        self.instrument = instrument
        self.scorer = scorer
        self.planner = planner
        self.action_log = action_log or ActionLog()
        self.decision_overrides = dict(decision_overrides or {})
        self.budget = budget
        self.decision_version = decision_version
        self.hypotheses_generator = hypotheses_generator
        self.open_world_model = open_world_model
        self.calibrator = calibrator
        self.precommit_model_digest = precommit_model_digest or "unversioned"
        self.case = repository.case(case_id)
        self.candidates = repository.candidates(case_id)
        self.templates = template_store if template_store is not None else repository.references
        self._evidence: dict[str, Evidence] = {}
        self._weights: dict[str, float] = {}
        self._actions: list[MeasurementAction] = []
        self._observations: dict[str, Measurement] = {}
        self._spectra: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._stopped = False
        self._decision = "AMBIGUOUS"
        self._status_reasons: list[str] = []
        self._qc: dict = {}
        self._precommits: dict[str, dict] = {}
        self._hypotheses: dict | None = None
        self._unknown_risk: float | None = None
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

    @property
    def precommits(self) -> dict[str, dict]:
        return dict(self._precommits)

    def _observe(self, measurement: Measurement, *, initial: bool = False) -> None:
        self._observations[measurement.action] = measurement
        self._spectra[measurement.action] = (
            np.asarray(measurement.mz, float),
            np.asarray(measurement.intensity, float),
        )
        self._evidence, self._weights = self.scorer.rank_sequence(
            self._spectra,
            self.candidates,
            self.templates,
            self.case.precursor_mz,
        )
        for cid, item in self._evidence.items():
            item.weight = float(self._weights.get(cid, 0.0))
            item.relative_weight = float(self._weights.get(cid, 0.0))
        if self.calibrator is not None and self._weights:
            top = rank_candidates(self._weights)[0]
            if top in self._evidence:
                support = float(self._weights.get(top, 0.0))
                self._evidence[top].estimated_error = float(
                    1.0 - self.calibrator.p_correct(support)
                )

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
            evidence=self._evidence,
            observations=self._observations,
            observations_peak_counts={
                action: int(np.asarray(m.mz).size)
                for action, m in self._observations.items()
            },
        )

    def hypotheses(self, action_key: str | None = None) -> dict | None:
        """Pre-measurement, falsifiable fragment hypotheses (v3 signature feature)."""
        if self.hypotheses_generator is None:
            return None
        if self._hypotheses is None:
            try:
                self._hypotheses = self.hypotheses_generator.generate(
                    case=self.case,
                    candidates=self.candidates,
                    weights=self._weights,
                    store=self.templates,
                    observed_actions=self.observed_actions,
                    available_actions=self.instrument.available_actions(self.case_id),
                    observations=self._observations,
                )
            except Exception as exc:  # never let a narration layer break the run
                self.action_log.write(
                    {
                        "case_id": self.case_id,
                        "kind": "hypothesis_generation_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                self._hypotheses = None
        return self._hypotheses

    def _seal_precommit(self, action_key: str) -> dict:
        """Immutable prediction bound to case + observation + model + action."""
        hypotheses = self.hypotheses(action_key)
        payload = {
            "case_id": self.case_id,
            "action": action_key,
            "observation_digest": observation_digest(self._observations),
            "model_digest": self.precommit_model_digest,
            "hypotheses": hypotheses or {},
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        record = {
            **payload,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "precommit_sha256": digest,
        }
        self._precommits[action_key] = record
        self.action_log.write({"case_id": self.case_id, "kind": "precommit", **record})
        return record

    def measure(self, action_key: str) -> Measurement:
        if self._stopped:
            raise OracleAccessError("investigation is already stopped")
        if action_key == "STOP":
            raise OracleAccessError("STOP is not a measurement; call stop()")
        action = MeasurementAction.for_key(action_key)
        # Seal the prediction BEFORE the hidden peaks are revealed.
        precommit = self._seal_precommit(action.key)
        self.action_log.write(
            {
                "case_id": self.case_id,
                "kind": "plan_before_measure",
                "chosen_action": action.key,
                "observed_before": self.observed_actions,
                "remaining_budget_before": self.remaining_budget,
                "precommit_sha256": precommit["precommit_sha256"],
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
        # Post-measurement validation of the sealed prediction.
        if self._hypotheses is not None:
            self._hypotheses = self._validate_hypotheses(self._hypotheses, measurement)
        return measurement

    def _validate_hypotheses(self, hypotheses: dict, measurement: Measurement) -> dict:
        from spectrapilot.planning.hypotheses import validate_against_measurement

        return validate_against_measurement(hypotheses, measurement)

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
        if self.decision_version == "v2_legacy":
            decision, self._qc = self._final_decision_v2_legacy()
            # Preserve v2 behaviour but normalise its status vocabulary so the
            # rest of the system only ever sees the v3 contract.
            self._decision = LEGACY_STATUS_MAP[decision].value
        else:
            self._decision, self._qc = self._final_decision_v3()
        return self.investigation()

    def investigation(self) -> Investigation:
        top = rank_candidates(self._weights)[0] if self._weights else None
        status = EvidenceStatus(self._decision)
        accepted = status in ACCEPTED_STATUSES
        return Investigation(
            case_id=self.case_id,
            observed_actions=self.observed_actions,
            candidate_evidence=[item.public_dict() for item in self._ordered()],
            selected_actions=[action.public_dict() for action in self._actions],
            decision=status.value,
            predicted_identity=top if accepted and top else None,
            confidence=float(self._weights.get(top, 0.0)) if accepted and top else None,
            limitations=self._limitations(),
            qc=self._qc or self.qc(),
            provenance=self._provenance(),
            evidence_status=status,
            proof_level=PROOF_TIER[status],
            accept_identity=accepted,
            status_reasons=list(self._status_reasons),
            estimated_error=self._estimated_error(status),
            unknown_risk=self._unknown_risk,
            hypotheses=(self._hypotheses or {}).get("hypotheses", []),
            precommit=next(iter(self._precommits.values()), None),
            scorer_version=getattr(self.scorer, "version", "unknown"),
            policy_version=self.decision_version,
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
            "expected_energy_ev": template.expected_energy_ev,
            "spectrum": {
                "mz": template.mz.tolist(),
                "intensity": template.intensity.tolist(),
            },
        }

    # -- decision ----------------------------------------------------------
    def qc(self, *, legacy: bool = False) -> dict:
        per_action_peaks = {
            action: int(np.asarray(measurement.mz).size)
            for action, measurement in self._observations.items()
        }
        checks = {
            "n_candidates": len(self.candidates),
            "initial_peaks": per_action_peaks.get("CID20", 0),
            "peaks_by_observed_action": per_action_peaks,
            # Insufficiency is a property of the *available* evidence, not of the
            # first scan alone: a 2-peak CID20 followed by a 15-peak CID40 is not
            # insufficient data.
            "best_observation_peaks": max(per_action_peaks.values(), default=0),
            "total_peaks": int(sum(per_action_peaks.values())),
            "all_candidates_within_ppm": all(
                abs(c.precursor_mz - self.case.precursor_mz) / self.case.precursor_mz * 1e6
                <= self.templates.ppm_tolerance
                for c in self.candidates
            ),
            "adduct_consistent": all(c.adduct == self.case.adduct for c in self.candidates),
            "observed_actions": self.observed_actions,
            "template_actions": ["CID20", "CID40", "EAD16"],
            "templates_available": sum(
                1
                for candidate in self.candidates
                for action in self.observed_actions
                if (candidate.molecule_id, action) in getattr(self.templates, "_templates", {})
            ),
        }
        if "CID20" in self._observations:
            mz = np.asarray(self._observations["CID20"].mz, float)
            intensity = np.asarray(self._observations["CID20"].intensity, float)
            checks["initial_peak_count"] = int(mz.size)
            checks["initial_base_peak_fraction"] = (
                float(intensity.max() / intensity.sum())
                if intensity.size and intensity.sum() > 0
                else 0.0
            )
        reasons = []
        if not checks["all_candidates_within_ppm"]:
            reasons.append("candidate_precursor_outside_tolerance")
        if not checks["adduct_consistent"]:
            reasons.append("adduct_mismatch")
        if checks["best_observation_peaks"] < 3:
            reasons.append("observation_too_sparse")
        if legacy and checks["initial_peaks"] < 3:
            # Frozen v2 rule: the first scan had to be informative on its own.
            reasons.append("initial_spectrum_too_sparse")
        checks["passed"] = not reasons
        checks["rejection_reasons"] = reasons
        return checks

    # -- v2 frozen rule ----------------------------------------------------
    def _final_decision_v2_legacy(self) -> tuple[str, dict]:
        qc = self.qc(legacy=True)
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
        if len(self.candidates) == 1 and support >= min_support:
            return "IDENTIFIED", qc
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

    # -- v3 rule -----------------------------------------------------------
    def _v3(self, dotted: str, default):
        if dotted in self.decision_overrides:
            return self.decision_overrides[dotted]
        return load_config("v3").get_path(dotted, default)

    def _template_is_reliable(self, action: str, evidence: Evidence) -> bool:
        try:
            template = self.templates.template(evidence.candidate_id, action)
        except KeyError:
            return False
        if template.is_experimental:
            return True
        threshold = float(self._v3("decision.min_template_reliability_for_msms", 0.30))
        return bool(template.n_peaks) and float(template.reliability) >= threshold

    def _spectral_support(self, evidence: Evidence) -> tuple[float, int, list[str]]:
        """(best fit, best matched peaks, actions with independent support)."""
        min_fit = float(self._v3("decision.msms_min_fit", 0.30))
        min_matched = int(self._v3("decision.msms_min_matched_peaks", 2))
        best_fit = max(evidence.similarity_by_action.values(), default=0.0)
        best_matched = max(evidence.matched_peaks_by_action.values(), default=0)
        independent = [
            action
            for action, cosine in evidence.similarity_by_action.items()
            if cosine >= min_fit
            and evidence.matched_peaks_by_action.get(action, 0) >= min_matched
            and self._template_is_reliable(action, evidence)
        ]
        return float(best_fit), int(best_matched), independent

    def _validated_open_world_rejection(self, evidence: Evidence) -> bool:
        """Reject only on reliable experimental contradiction or a validated model."""
        if self.open_world_model is not None:
            try:
                risk = self.open_world_model.predict(
                    case=self.case,
                    candidates=self.candidates,
                    evidence=self._evidence,
                    weights=self._weights,
                    store=self.templates,
                    observations=self._observations,
                )
            except Exception:
                risk = None
            if risk is not None:
                self._unknown_risk = float(risk)
                if float(risk) >= float(self._v3("open_world.unknown_cutoff", 0.50)):
                    return True
        requires_experimental = bool(
            self._v3("decision.ool_requires_experimental_source", True)
        )
        max_fit = float(self._v3("decision.ool_max_fit", 0.20))
        max_matched = int(self._v3("decision.ool_max_matched_peaks", 1))
        has_experimental = any(
            source == "reference_cid60" for source in evidence.template_sources.values()
        )
        best_fit, best_matched, _ = self._spectral_support(evidence)
        if requires_experimental and not has_experimental:
            return False
        return best_fit < max_fit and best_matched <= max_matched

    def _final_decision_v3(self) -> tuple[str, dict]:
        reasons: list[str] = []
        qc = self.qc()
        self._status_reasons = reasons

        # 1. Observation validity.
        if not qc["passed"]:
            reasons.extend(qc["rejection_reasons"])
            reasons.append("invalid_observation")
            return EvidenceStatus.INSUFFICIENT_DATA.value, qc

        # 2. No chemically plausible candidate in the scoped library at all.
        if not self.candidates:
            reasons.append("empty_candidate_pool")
            return EvidenceStatus.OUT_OF_LIBRARY.value, qc

        # 3. Candidates exist but the evidence model has nothing to say.
        if not self._weights or not self._evidence:
            reasons.append("no_candidate_template")
            return EvidenceStatus.INSUFFICIENT_DATA.value, qc

        top = rank_candidates(self._weights)[0]
        evidence = self._evidence.get(top)
        if evidence is None:
            reasons.append("top_candidate_has_no_evidence")
            return EvidenceStatus.INSUFFICIENT_DATA.value, qc

        support = float(self._weights.get(top, 0.0))
        margin = top2_margin(self._weights)
        best_fit, best_matched, independent = self._spectral_support(evidence)

        # Calibrated risk gate: only a *calibrated* model may lower the bar, and
        # even then independent spectral support is still required for MS/MS.
        calibrated_risk_ok = True
        if evidence.estimated_error is not None:
            acceptable = float(self._v3("open_world.acceptable_risk", 0.15))
            calibrated_risk_ok = float(evidence.estimated_error) <= acceptable
            if not calibrated_risk_ok:
                reasons.append(
                    f"calibrated_error_above_budget:{evidence.estimated_error:.3f}"
                )

        # 4. Open-world rejection requires a validated mechanism.
        if self._validated_open_world_rejection(evidence):
            reasons.append("validated_open_world_rejection")
            return EvidenceStatus.OUT_OF_LIBRARY.value, qc

        # 5. Independent spectral support -> MS/MS identification.
        min_support = float(self._v3("decision.msms_min_support", 0.72))
        min_margin = float(self._v3("decision.msms_min_margin", 0.22))
        if independent and support >= min_support and margin >= min_margin and calibrated_risk_ok:
            reasons.append("independent_spectral_support")
            reasons.extend(f"support_action:{action}" for action in independent)
            return EvidenceStatus.MSMS_SUPPORTED.value, qc

        # 6. A unique precursor-consistent library candidate is a mass-only match.
        #    This is a retrieval result, explicitly NOT MS/MS confirmation.
        if len(self.candidates) == 1 and calibrated_risk_ok:
            reasons.append("unique_precursor_match")
            reasons.append("no_independent_spectral_support")
            return EvidenceStatus.MASS_ONLY_MATCH.value, qc

        # 7. Otherwise abstain honestly.
        if not independent:
            reasons.append("no_independent_spectral_support")
        if support < min_support:
            reasons.append("insufficient_support")
        if margin < min_margin:
            reasons.append("insufficient_margin")
        connectivity = top.split("-")[0]
        if any(
            cid != top and cid.split("-")[0] == connectivity and self._weights.get(cid, 0.0) >= 0.10
            for cid in self._weights
        ):
            reasons.append("same_connectivity_stereoisomer_competitor")
        return EvidenceStatus.AMBIGUOUS.value, qc

    def _policy(self, dotted: str, default):
        if dotted in self.decision_overrides:
            return self.decision_overrides[dotted]
        cfg = load_config("policies")
        return cfg.get_path(dotted, default)

    def _estimated_error(self, status: EvidenceStatus) -> float | None:
        if status not in ACCEPTED_STATUSES:
            return None
        top = rank_candidates(self._weights)[0] if self._weights else None
        if top is None:
            return None
        evidence = self._evidence.get(top)
        if evidence is not None and evidence.estimated_error is not None:
            return float(evidence.estimated_error)
        # Uncalibrated fallback: 1 - relative support is NOT a probability.
        return float(1.0 - self._weights.get(top, 0.0))

    def _limitations(self) -> list[str]:
        limitations = [
            "Closed-world candidate set: the true structure is assumed to be present unless the open-world test removes it.",
            "The CID40 template is a CID60 reference when available; this is an explicitly labelled reference-anchored track with a 20 eV mismatch.",
            "The EAD16 template is a train-only structure-kNN prediction, not a measured target spectrum.",
            "Candidate weights are relative support, not calibrated molecular-identity probabilities.",
            "MS/MS cannot distinguish stereoisomers without orthogonal evidence.",
            "This is single-compound standard identification, not an end-to-end LC-MS mixture workflow.",
            "MASS_ONLY_MATCH means a unique precursor-consistent library hit, not MS/MS confirmation.",
        ]
        if self._stopped and self._decision == EvidenceStatus.AMBIGUOUS.value:
            limitations.append("The evidence did not satisfy the precommitted identification rule; the result is abstained.")
        if self._stopped and self._decision == EvidenceStatus.OUT_OF_LIBRARY.value:
            limitations.append("Reliable evidence contradicted the scoped candidate library.")
        if self._stopped and self._decision == EvidenceStatus.INSUFFICIENT_DATA.value:
            limitations.append("The observation or candidate templates were insufficient for a supported decision.")
        if self._stopped and self._decision == EvidenceStatus.MASS_ONLY_MATCH.value:
            limitations.append("The reported structure rests on accurate mass and library uniqueness only.")
        return limitations

    def _provenance(self) -> dict:
        manifest = {}
        manifest_path = CURATED / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        def _info(candidate_id: str, action: str) -> dict:
            try:
                template = self.templates.template(candidate_id, action)
            except KeyError:
                return {"source": "missing", "expected_energy_ev": None}
            return {
                "source": template.source,
                "expected_energy_ev": template.expected_energy_ev,
            }

        return {
            "case_id": self.case_id,
            "observed_accessions": {
                action: measurement.accession
                for action, measurement in sorted(self._observations.items())
            },
            "template_sources": {
                candidate_id: {
                    action: _info(candidate_id, action)["source"]
                    for action in ("CID20", "CID40", "EAD16")
                }
                for candidate_id in self.case.candidate_ids[:8]
            },
            "template_expected_energy_ev": {
                candidate_id: {
                    action: _info(candidate_id, action)["expected_energy_ev"]
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
            "decision_version": self.decision_version,
            "precommits": self.precommits,
            "note": "Observed accessions are released after the investigation is stopped.",
        }

    def export_markdown(self) -> str:
        investigation = self.investigation()
        lines = [
            f"# SpectraPilot investigation report — {investigation.case_id}",
            "",
            f"**Status:** `{investigation.decision}` (proof level: `{investigation.proof_level}`)",
            f"**Observed actions:** {', '.join(investigation.observed_actions)}",
            f"**Predicted identity:** {investigation.predicted_identity or '—'}",
            f"**Identity accepted:** {'yes' if investigation.accept_identity else 'no'}",
            f"**Status reasons:** {', '.join(investigation.status_reasons) or '—'}",
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
        if investigation.hypotheses:
            lines += ["", "## Precommitted fragment hypotheses", ""]
            for item in investigation.hypotheses:
                window = item.get("fragment_mz_window") or [None, None]
                lines.append(
                    f"- **{item.get('hypothesis_id')}** {item.get('action')}: "
                    f"m/z {window[0]:.4f}–{window[1]:.4f} supports "
                    f"`{item.get('candidate_supported')}` over "
                    f"`{item.get('candidate_challenged')}`; outcome: {item.get('outcome') or 'pending'}"
                )
        lines += ["", "## Provenance", ""]
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

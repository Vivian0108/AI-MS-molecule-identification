"""Decision-aware action selection (SpectraPilot v3, P4).

The v2 ``SeparationPlanner`` is retained as a **named baseline** in
``planning/separation.py``.  This module adds a planner that optimises the thing
that actually matters: *expected decision risk after one more experiment*, and
the *proof tier* the decision can reach, subject to a scan budget.

It is deliberately honest about what it is:

* ``score_type = "SUPERVISED_RISK_PROXY"`` — an analytic proxy for expected
  risk reduction, **not** a calibrated expected information gain.
* The proxy is driven by (a) current risk, calibrated by the isotonic support
  calibrator when one is present and otherwise explicitly uncalibrated,
  (b) pairwise template separation among the surviving candidates,
  (c) template trust learned from provenance and donor similarity, and
  (d) relative scan cost.
* A separate ``proof_tier_value`` term prices the upgrade from
  ``MASS_ONLY_MATCH`` to ``MSMS_SUPPORTED``.  It is a stated utility weight, not
  a measured probability gain.
* Template trust is why EAD16 is rarely chosen: its train-only structure-kNN
  templates have a median reliability of ~0.08, so they rarely move a decision.
  That is a data-driven consequence of the frozen templates, not a hard-coded
  preference.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from spectrapilot.models import Candidate, Evidence, Plan
from spectrapilot.planning.actions import MeasurementAction, stop_action
from spectrapilot.science.scoring import template_trust
from spectrapilot.science.templates import ReferenceStore
from unknownid.core.posterior import entropy, rank_candidates, top2_margin
from unknownid.core.spectra import cosine_greedy


def _sigmoid(value: float) -> float:
    return float(1.0 / (1.0 + np.exp(-value)))


class RiskAwareDecisionPolicy:
    """One-step lookahead over an expected-risk / proof-tier proxy."""

    name = "decision_aware_risk_reduction"
    score_type = "SUPERVISED_RISK_PROXY"

    def __init__(
        self,
        *,
        acceptable_risk: float = 0.15,
        min_gain: float = 0.02,
        separation_center: float = 0.25,
        separation_slope: float = 6.0,
        ead_cost_ratio: float = 1.0,
        tolerance_da: float = 0.02,
        max_candidates: int = 20,
        msms_min_fit: float = 0.55,
        msms_min_support: float = 0.72,
        msms_min_margin: float = 0.22,
        min_matched: int = 2,
        proof_tier_value: float = 0.30,
        sparse_peak_threshold: int = 3,
    ) -> None:
        self.acceptable_risk = float(acceptable_risk)
        self.min_gain = float(min_gain)
        self.separation_center = float(separation_center)
        self.separation_slope = float(separation_slope)
        self.ead_cost_ratio = float(ead_cost_ratio)
        self.tolerance_da = float(tolerance_da)
        self.max_candidates = int(max_candidates)
        self.msms_min_fit = float(msms_min_fit)
        self.msms_min_support = float(msms_min_support)
        self.msms_min_margin = float(msms_min_margin)
        self.min_matched = int(min_matched)
        self.proof_tier_value = float(proof_tier_value)
        self.sparse_peak_threshold = int(sparse_peak_threshold)

    # -- helpers -----------------------------------------------------------
    def _usable(self, candidate_id: str, action: str, store: ReferenceStore) -> bool:
        try:
            template = store.template(candidate_id, action)
        except KeyError:
            return False
        return template.n_peaks >= 2

    def _weighted_separation(
        self,
        weights: Mapping[str, float],
        usable: Sequence[str],
        action: str,
        store: ReferenceStore,
    ) -> float:
        total = sum(weights.get(cid, 0.0) for cid in usable)
        if total <= 0 or len(usable) < 2:
            return 0.0
        normalised = {cid: weights.get(cid, 0.0) / total for cid in usable}
        separation = 0.0
        for index, left in enumerate(usable):
            left_template = store.template(left, action)
            for right in usable[index + 1 :]:
                right_template = store.template(right, action)
                distance = 1.0 - cosine_greedy(
                    left_template.mz,
                    left_template.intensity,
                    right_template.mz,
                    right_template.intensity,
                    self.tolerance_da,
                )[0]
                separation += normalised[left] * normalised[right] * max(distance, 0.0)
        return float(separation)

    def _current_risk(
        self,
        weights: Mapping[str, float],
        evidence: Mapping[str, Evidence] | None,
    ) -> float:
        if not weights:
            return 1.0
        top = rank_candidates(weights)[0]
        if evidence and top in evidence and evidence[top].estimated_error is not None:
            return float(evidence[top].estimated_error)
        return float(1.0 - weights.get(top, 0.0))

    def _has_independent_support(
        self,
        *,
        weights: Mapping[str, float],
        top_fit: float,
        top_matched: int,
    ) -> bool:
        if not weights:
            return False
        top = rank_candidates(weights)[0]
        return bool(
            weights.get(top, 0.0) >= self.msms_min_support
            and top2_margin(weights) >= self.msms_min_margin
            and top_fit >= self.msms_min_fit
            and top_matched >= self.min_matched
        )

    # -- main API ----------------------------------------------------------
    def plan(
        self,
        case_id: str,
        *,
        weights: Mapping[str, float],
        candidates: Sequence[Candidate],
        store: ReferenceStore,
        observed_actions: Sequence[str],
        remaining_budget: int,
        available_actions: Sequence[MeasurementAction],
        top_fit: float = 0.0,
        top_matched: int = 0,
        evidence: Mapping[str, Evidence] | None = None,
        observations: Mapping[str, object] | None = None,
        observations_peak_counts: Mapping[str, int] | None = None,
        **_: object,
    ) -> Plan:
        observed = list(observed_actions)
        available = [a for a in available_actions if a.key not in observed]
        h0 = entropy(weights)
        options: list[dict] = []
        peak_counts = dict(observations_peak_counts or {})
        best_peaks = max(peak_counts.values(), default=0)
        sparse = best_peaks < self.sparse_peak_threshold
        risk_now = self._current_risk(weights, evidence)
        calibrated = bool(
            evidence
            and any(item.estimated_error is not None for item in evidence.values())
        )
        unique_pool = len(candidates) <= 1
        independent = self._has_independent_support(
            weights=weights, top_fit=top_fit, top_matched=top_matched
        )

        if remaining_budget <= 0 or not available:
            return self._stop(
                case_id, observed, available, remaining_budget, h0, options,
                note="budget exhausted" if remaining_budget <= 0 else "no unobserved action available",
                risk=risk_now,
            )

        # A unique candidate is already accepted by the contract as a mass-only
        # match; a further scan can only upgrade the *proof tier*.
        if unique_pool and not sparse:
            pass  # handled by the proof-tier term below
        elif independent and (not calibrated or risk_now <= self.acceptable_risk):
            return self._stop(
                case_id, observed, available, remaining_budget, h0, options,
                note="expected risk is already within budget and independent support exists",
                risk=risk_now,
            )

        ranked = rank_candidates(weights)[: self.max_candidates]
        for action in available:
            usable = [cid for cid in ranked if self._usable(cid, action.key, store)]
            if not usable:
                continue
            trusts = [template_trust(store.template(cid, action.key)) for cid in usable]
            trust = float(np.mean(trusts))
            separation = self._weighted_separation(weights, usable, action.key, store)
            if len(usable) < 2:
                # A scan with no competitor can still confirm or refute the
                # single candidate; assume a 50% chance conditional on a
                # trustworthy template.
                p_resolve = trust * 0.5
            else:
                p_resolve = _sigmoid(
                    self.separation_slope * (separation - self.separation_center)
                ) * trust
            risk_gain = risk_now - risk_now * (1.0 - p_resolve)
            tier_gain = 0.0
            if not independent:
                # Price the MASS_ONLY_MATCH -> MSMS_SUPPORTED upgrade.
                tier_gain = self.proof_tier_value * p_resolve
            cost = action.estimated_cost * (
                self.ead_cost_ratio if action.key == "EAD16" else 1.0
            )
            gain = risk_gain + tier_gain
            options.append(
                {
                    "action": action.public_dict(),
                    "separation": float(separation),
                    "reliability": float(trust),
                    "p_resolve": float(p_resolve),
                    "risk_before": float(risk_now),
                    "expected_risk_after": float(risk_now * (1.0 - p_resolve)),
                    "expected_risk_gain": float(risk_gain),
                    "expected_tier_gain": float(tier_gain),
                    "cost": float(cost),
                    "score": float(gain / max(cost, 1e-9)),
                    "score_type": self.score_type,
                    "note": (
                        "proxy = current risk x P(resolve) + proof-tier bonus, "
                        "divided by cost; not a calibrated information gain"
                    ),
                }
            )
        if not options:
            return self._stop(
                case_id, observed, available, remaining_budget, h0, options,
                note="no action has a candidate template with at least two peaks",
                risk=risk_now,
            )
        options.sort(key=lambda item: (-item["score"], item["action"]["key"]))
        best = options[0]

        if sparse and best["score"] <= 0:
            best = max(options, key=lambda item: (item["reliability"], item["action"]["key"]))
            best["note"] += "; selected to escape observation sparsity"
        elif (best["expected_risk_gain"] + best["expected_tier_gain"]) < self.min_gain:
            return self._stop(
                case_id, observed, available, remaining_budget, h0, options,
                note="best proxy gain is below the predeclared threshold",
                risk=risk_now,
            )

        action = MeasurementAction.for_key(
            best["action"]["key"],
            estimated_cost=best["cost"],
            policy_score=best["score"],
            score_type=self.score_type,
        )
        return Plan(
            case_id=case_id,
            observed_actions=observed,
            available_actions=[item.public_dict() for item in available],
            remaining_budget=remaining_budget,
            recommended=action.public_dict(),
            options=options,
            method=self.name,
            score_type="HEURISTIC",
            current_entropy=h0,
            note=(
                "One-step lookahead over a supervised expected-risk / proof-tier "
                "proxy. Hidden peaks are never read. The score is a stated utility "
                "function, not a calibrated expected information gain."
            ),
        )

    def _stop(
        self,
        case_id: str,
        observed: list[str],
        available: Sequence[MeasurementAction],
        remaining_budget: int,
        h0: float,
        options: list[dict],
        *,
        note: str,
        risk: float,
    ) -> Plan:
        return Plan(
            case_id=case_id,
            observed_actions=observed,
            available_actions=[item.public_dict() for item in available],
            remaining_budget=max(remaining_budget, 0),
            recommended=stop_action().public_dict(),
            options=options,
            method=self.name,
            score_type="SUPERVISED_RISK_PROXY",
            current_entropy=h0,
            note=f"{note} (current decision risk proxy = {risk:.3f}).",
        )

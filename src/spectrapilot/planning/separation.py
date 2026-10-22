"""Cost-aware separation planner for CID40 versus EAD16.

This is Planner 1 from the specification.  It is deliberately labelled a
heuristic: template separation is not reported as information gain in bits.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from spectrapilot.models import Candidate, Plan, Template
from spectrapilot.planning.actions import MeasurementAction, stop_action
from spectrapilot.science.templates import ReferenceStore
from unknownid.core.posterior import entropy, rank_candidates, top2_margin
from unknownid.core.spectra import cosine_greedy


class SeparationPlanner:
    def __init__(
        self,
        *,
        stop_support: float = 0.90,
        stop_margin: float = 0.65,
        stop_score: float = 0.01,
        identified_min_support: float = 0.72,
        identified_min_margin: float = 0.22,
        identified_min_fit: float = 0.30,
        identified_min_matched_peaks: int = 2,
        ead_cost_ratio: float = 1.0,
        tolerance_da: float = 0.02,
        max_candidates: int = 20,
    ) -> None:
        self.stop_support = float(stop_support)
        self.stop_margin = float(stop_margin)
        self.stop_score = float(stop_score)
        self.identified_min_support = float(identified_min_support)
        self.identified_min_margin = float(identified_min_margin)
        self.identified_min_fit = float(identified_min_fit)
        self.identified_min_matched_peaks = int(identified_min_matched_peaks)
        self.ead_cost_ratio = float(ead_cost_ratio)
        self.tolerance_da = float(tolerance_da)
        self.max_candidates = int(max_candidates)

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
        **_: object,
    ) -> Plan:
        observed = list(observed_actions)
        available = [
            action for action in available_actions if action.key not in observed
        ]
        h0 = entropy(weights)
        options: list[dict] = []
        if remaining_budget <= 0 or not available:
            return self._stop(
                case_id, observed, available, remaining_budget, h0, options,
                note="budget exhausted" if remaining_budget <= 0 else "no unobserved action available",
            )
        if len(weights) <= 1:
            return self._stop(
                case_id, observed, available, remaining_budget, h0, options,
                note="a single candidate remains",
            )
        top = rank_candidates(weights)[0]
        if (
            weights.get(top, 0.0) >= self.stop_support
            and top2_margin(weights) >= self.stop_margin
            and top_fit >= self.identified_min_fit
            and top_matched >= self.identified_min_matched_peaks
        ):
            return self._stop(
                case_id, observed, available, remaining_budget, h0, options,
                note="current support and spectral evidence already satisfy the STOP rule",
            )

        for action in available:
            usable = [
                cid
                for cid in rank_candidates(weights)[: self.max_candidates]
                if self._usable(cid, action.key, store)
            ]
            if len(usable) < 2:
                continue
            separation = self._weighted_separation(weights, usable, action.key, store)
            reliabilities = [store.template(cid, action.key).reliability for cid in usable]
            reliability = float(np.mean(reliabilities)) if reliabilities else 0.0
            cost = action.estimated_cost * (
                self.ead_cost_ratio if action.key == "EAD16" else 1.0
            )
            score = separation * max(reliability, 0.0) / max(cost, 1e-9)
            options.append(
                {
                    "action": action.public_dict(),
                    "separation": float(separation),
                    "reliability": float(reliability),
                    "cost": float(cost),
                    "score": float(score),
                    "score_type": "HEURISTIC",
                    "note": (
                        "weighted pairwise template separation x template reliability / relative cost; "
                        "not a calibrated information gain"
                    ),
                }
            )
        if not options:
            return self._stop(
                case_id, observed, available, remaining_budget, h0, options,
                note="no action has two scoreable candidate templates",
            )
        options.sort(key=lambda item: (-item["score"], item["action"]["key"]))
        best = options[0]
        if best["score"] <= self.stop_score:
            return self._stop(
                case_id, observed, available, remaining_budget, h0, options,
                note="best expected separation is below the predeclared STOP threshold",
            )
        action = MeasurementAction.for_key(
            best["action"]["key"],
            estimated_cost=best["cost"],
            policy_score=best["score"],
            score_type="HEURISTIC",
        )
        return Plan(
            case_id=case_id,
            observed_actions=observed,
            available_actions=[item.public_dict() for item in available],
            remaining_budget=remaining_budget,
            recommended=action.public_dict(),
            options=options,
            method="separation_heuristic",
            score_type="HEURISTIC",
            current_entropy=h0,
            note=(
                "Planner uses only candidate structures, allowed templates and current support. "
                "Hidden CID40/EAD16 peaks are not read."
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
    ) -> Plan:
        return Plan(
            case_id=case_id,
            observed_actions=observed,
            available_actions=[item.public_dict() for item in available],
            remaining_budget=max(remaining_budget, 0),
            recommended=stop_action().public_dict(),
            options=options,
            method="separation_heuristic",
            score_type="HEURISTIC",
            current_entropy=h0,
            note=note,
        )

    def _usable(self, candidate_id: str, action: str, store: ReferenceStore) -> bool:
        try:
            template = store.template(candidate_id, action)
        except KeyError:
            return False
        return template.n_peaks > 0

    def _weighted_separation(
        self,
        weights: Mapping[str, float],
        candidate_ids: Sequence[str],
        action: str,
        store: ReferenceStore,
    ) -> float:
        total = sum(weights.get(cid, 0.0) for cid in candidate_ids) or 1.0
        normalized = {cid: weights.get(cid, 0.0) / total for cid in candidate_ids}
        value = 0.0
        for i, first in enumerate(candidate_ids):
            a = store.template(first, action)
            for second in candidate_ids[i + 1 :]:
                b = store.template(second, action)
                cosine, _ = cosine_greedy(a.mz, a.intensity, b.mz, b.intensity, self.tolerance_da)
                value += normalized[first] * normalized[second] * (1.0 - float(cosine))
        return float(value)

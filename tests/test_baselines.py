"""Metric, abstention, bootstrap and policy-registry tests."""

from __future__ import annotations

import numpy as np
import pytest

from unknownid.core.models import Evidence
from unknownid.eval.baselines import (
    FixedEnergy,
    RandomPolicy,
    SingleScan,
    default_policies,
)
from unknownid.eval.bootstrap import bootstrap_mean_ci, paired_bootstrap_difference
from unknownid.eval.metrics import (
    abstention_summary,
    decide,
    reciprocal_rank,
    top1,
    topk,
)


def _evidence(candidate: str, *, similarity: float, matched: int) -> Evidence:
    return Evidence(
        candidate_id=candidate,
        similarity_by_energy={20: similarity},
        matched_peaks_by_energy={20: matched},
        weight=0.0,
    )


def test_ranking_metrics() -> None:
    order = ["A", "B", "C"]
    assert top1(order, "A") == 1
    assert top1(order, "B") == 0
    assert topk(order, "B", 2) == 1
    assert topk(order, "C", 2) == 0
    assert reciprocal_rank(order, "A") == 1.0
    assert reciprocal_rank(order, "C") == pytest.approx(1 / 3)
    assert reciprocal_rank(order, "Z") == 0.0


def test_decide_identifies_with_strong_support_and_margin() -> None:
    weights = {"A": 0.8, "B": 0.2}
    evidence = {
        "A": _evidence("A", similarity=0.8, matched=4),
        "B": _evidence("B", similarity=0.3, matched=1),
    }
    decision = decide(weights, evidence)

    assert decision.decision == "identified"
    assert decision.top_candidate == "A"
    assert decision.reasons == []


def test_decide_abstains_on_low_support_or_margin() -> None:
    weights = {"A": 0.5, "B": 0.5}
    evidence = {
        "A": _evidence("A", similarity=0.8, matched=4),
        "B": _evidence("B", similarity=0.7, matched=3),
    }
    decision = decide(weights, evidence)

    assert decision.decision == "ambiguous"
    assert any("margin" in reason for reason in decision.reasons)


def test_decide_rejects_out_of_library_when_spectral_evidence_is_weak() -> None:
    weights = {"A": 0.9, "B": 0.1}
    evidence = {
        "A": _evidence("A", similarity=0.05, matched=0),
        "B": _evidence("B", similarity=0.0, matched=0),
    }
    decision = decide(weights, evidence)

    assert decision.decision == "out_of_library"
    assert "insufficient matched spectral evidence" in decision.reasons


def test_decide_abstains_for_same_connectivity_stereoisomers() -> None:
    weights = {"AAAA-BBBB-CCCC-D": 0.55, "AAAA-BBBB-CCCC-E": 0.45}
    evidence = {
        "AAAA-BBBB-CCCC-D": _evidence("AAAA-BBBB-CCCC-D", similarity=0.8, matched=4),
        "AAAA-BBBB-CCCC-E": _evidence("AAAA-BBBB-CCCC-E", similarity=0.75, matched=4),
    }
    decision = decide(weights, evidence)

    assert decision.decision == "ambiguous"
    assert any("stereoisomer" in reason for reason in decision.reasons)


def test_abstention_summary_counts_coverage_and_risk() -> None:
    summary = abstention_summary(
        ["identified", "identified", "ambiguous", "out_of_library"],
        ["A", "B", "C", None],
        ["A", "A", "C", "D"],
    )

    assert summary["n"] == 4
    assert summary["identified"] == 2
    assert summary["coverage"] == pytest.approx(0.5)
    assert summary["accepted_correct"] == 1
    assert summary["accepted_errors"] == 1
    assert summary["risk"] == pytest.approx(0.5)
    assert summary["ambiguous"] == 1
    assert summary["out_of_library"] == 1


def test_bootstrap_ci_and_paired_difference_are_deterministic() -> None:
    mean, low, high = bootstrap_mean_ci([1.0, 1.0, 1.0, 1.0], n_boot=200, seed=3)
    assert (mean, low, high) == (1.0, 1.0, 1.0)

    first = {"a": 1.0, "b": 1.0, "c": 1.0}
    second = {"a": 0.0, "b": 0.0, "c": 0.0}
    diff = paired_bootstrap_difference(first, second, n_boot=300, seed=3)
    assert diff["n"] == 3
    assert diff["mean_difference"] == 1.0
    assert diff["ci_low"] == 1.0
    assert diff["ci_high"] == 1.0
    assert diff["wins"] == 3

    # Resampling unit is the molecule, so paired keys must align.
    partial = paired_bootstrap_difference({"a": 1.0}, {"b": 0.0}, n_boot=10)
    assert partial["n"] == 0


class _FakeState:
    def __init__(self) -> None:
        self.actions: list[int] = []

    def measure(self, energy: int) -> None:
        if energy not in (30, 40):
            raise AssertionError("policy attempted a non-allowed energy")
        self.actions.append(energy)


def test_fixed_and_random_policies_respect_budget_and_energy_set() -> None:
    state = _FakeState()
    FixedEnergy(30).run(state, budget=1)
    assert state.actions == [30]

    state = _FakeState()
    FixedEnergy(40).run(state, budget=2)
    assert state.actions == [40, 30]

    state = _FakeState()
    SingleScan().run(state, budget=2)
    assert state.actions == []

    first, second = _FakeState(), _FakeState()
    RandomPolicy().run(first, budget=2, rng=np.random.default_rng(0))
    RandomPolicy().run(second, budget=2, rng=np.random.default_rng(0))
    assert first.actions == second.actions
    assert sorted(first.actions) == [30, 40]


def test_policy_registry_has_all_required_baselines() -> None:
    class _PlannerStub:
        pass

    policies = default_policies(_PlannerStub(), truth="A")
    assert [policy.name for policy in policies] == [
        "precursor_only",
        "single_scan",
        "always_30",
        "always_40",
        "random",
        "cheap_disagreement",
        "unknownid",
        "oracle_best_action",
    ]

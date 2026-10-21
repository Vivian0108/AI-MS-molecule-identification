"""Planner behaviour on synthetic templates (no oracle access)."""

from __future__ import annotations

import numpy as np
import pytest

from unknownid.core.spectra import ProcessedSpectrum
from unknownid.planner.acquisition import AcquisitionPlanner, PlannerConfig
from unknownid.planner.error_model import EnergyNoise, ErrorModel


@pytest.fixture
def templates():
    return {
        "AAAA-BBBB-CCCC-D": {
            20: ProcessedSpectrum(np.array([50.0, 100.0, 150.0]), np.array([1.0, 0.8, 0.4])),
            30: ProcessedSpectrum(np.array([50.0, 100.0, 150.0]), np.array([1.0, 0.7, 0.3])),
            40: ProcessedSpectrum(np.array([50.0, 100.0, 170.0]), np.array([1.0, 0.5, 0.6])),
        },
        "EEEE-FFFF-GGGG-H": {
            20: ProcessedSpectrum(np.array([50.0, 100.0, 150.0]), np.array([0.9, 1.0, 0.3])),
            30: ProcessedSpectrum(np.array([50.0, 100.0, 150.0]), np.array([1.0, 0.7, 0.3])),
            40: ProcessedSpectrum(np.array([60.0, 120.0, 190.0]), np.array([1.0, 0.9, 0.8])),
        },
    }


@pytest.fixture
def precursors():
    return {"AAAA-BBBB-CCCC-D": 200.0, "EEEE-FFFF-GGGG-H": 200.0}


def _config(**overrides) -> PlannerConfig:
    base = dict(
        budget=1,
        allowed_energies=(30, 40),
        cost=1.0,
        monte_carlo_samples=40,
        seed=11,
        tempering=0.85,
        stop_ig_threshold=0.0,
        tolerance_da=0.02,
    )
    base.update(overrides)
    return PlannerConfig(**base)


def test_heuristic_prefers_the_energy_with_the_largest_disagreement(templates, precursors) -> None:
    noise = {
        energy: EnergyNoise(n=20, mean_cosine=0.7, kappa=10.0, calibrated=False)
        for energy in (20, 30, 40)
    }
    planner = AcquisitionPlanner(
        _config(), method="disagreement_heuristic", error_model=ErrorModel(noise)
    )
    plan = planner.plan(
        "case-synthetic",
        weights={"AAAA-BBBB-CCCC-D": 0.5, "EEEE-FFFF-GGGG-H": 0.5},
        templates=templates,
        precursors=precursors,
        observed_energies=[20],
        remaining_budget=1,
    )

    assert plan.method == "disagreement_heuristic"
    assert plan.options
    assert plan.recommended.kind == "measure"
    # 30 eV templates are identical, 40 eV templates differ.
    assert plan.recommended.energy_ev == 40
    assert {option.energy_ev for option in plan.options} == {30, 40}
    assert "not calibrated information gain" in plan.note or "heuristic" in plan.note


def test_single_candidate_returns_stop(templates, precursors) -> None:
    planner = AcquisitionPlanner(_config(), method="disagreement_heuristic")
    plan = planner.plan(
        "case-synthetic",
        weights={"AAAA-BBBB-CCCC-D": 1.0},
        templates=templates,
        precursors=precursors,
        observed_energies=[20],
        remaining_budget=1,
    )

    assert plan.recommended.kind == "stop"
    assert "single candidate" in plan.note
    assert plan.options == []


def test_exhausted_budget_returns_stop(templates, precursors) -> None:
    planner = AcquisitionPlanner(_config(), method="disagreement_heuristic")
    plan = planner.plan(
        "case-synthetic",
        weights={"AAAA-BBBB-CCCC-D": 0.5, "EEEE-FFFF-GGGG-H": 0.5},
        templates=templates,
        precursors=precursors,
        observed_energies=[20],
        remaining_budget=0,
    )

    assert plan.recommended.kind == "stop"
    assert plan.note == "budget exhausted"


def test_already_observed_energy_is_not_offered(templates, precursors) -> None:
    planner = AcquisitionPlanner(_config(), method="disagreement_heuristic")
    plan = planner.plan(
        "case-synthetic",
        weights={"AAAA-BBBB-CCCC-D": 0.5, "EEEE-FFFF-GGGG-H": 0.5},
        templates=templates,
        precursors=precursors,
        observed_energies=[20, 30],
        remaining_budget=1,
    )

    assert plan.available_energies == [40]
    assert all(option.energy_ev == 40 for option in plan.options)


def test_monte_carlo_method_is_labelled_and_bounded(templates, precursors) -> None:
    noise = {
        energy: EnergyNoise(
            n=25,
            mean_cosine=0.65,
            kappa=11.0,
            calibrated=True,
            spurious_pool=[0.25, 0.5, 0.75],
        )
        for energy in (20, 30, 40)
    }
    planner = AcquisitionPlanner(_config(), method="monte_carlo_ig", error_model=ErrorModel(noise))
    plan = planner.plan(
        "case-synthetic",
        weights={"AAAA-BBBB-CCCC-D": 0.6, "EEEE-FFFF-GGGG-H": 0.4},
        templates=templates,
        precursors=precursors,
        observed_energies=[20],
        remaining_budget=1,
    )

    assert plan.method == "monte_carlo_ig"
    assert plan.recommended.kind in {"measure", "stop"}
    for option in plan.options:
        assert option.method == "monte_carlo_ig"
        assert option.predicted_information_gain >= 0.0
        assert option.cost == 1.0


def test_stop_rule_fires_when_shortlist_is_resolved(templates, precursors) -> None:
    planner = AcquisitionPlanner(
        _config(stop_min_support=0.9, stop_min_margin=0.7),
        method="disagreement_heuristic",
    )
    plan = planner.plan(
        "case-synthetic",
        weights={"AAAA-BBBB-CCCC-D": 0.95, "EEEE-FFFF-GGGG-H": 0.05},
        templates=templates,
        precursors=precursors,
        observed_energies=[20],
        remaining_budget=1,
    )

    assert plan.recommended.kind == "stop"
    assert "resolved" in plan.note

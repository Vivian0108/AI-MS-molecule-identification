"""Direction, denominators, independent branches and generated report checks."""

import importlib.util
import json
from pathlib import Path

import pytest

from spectrapilot.data.repository import CaseRepository
from spectrapilot.service import SpectraPilotService

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "modality_headroom", ROOT / "scripts/check_modality_headroom.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.mark.parametrize(
    "a,b,expected,wins,losses",
    [
        (1, 0, 1.0, 4, 0),
        (0, 1, -1.0, 0, 4),
        (1, 1, 0.0, 0, 0),
    ],
)
def test_paired_direction_intervals_and_mcnemar(a, b, expected, wins, losses):
    left, right = [{"accepted_correct": a}] * 4, [{"accepted_correct": b}] * 4
    result = runner.paired_difference(left, right, "accepted_correct", seed=20261021, resamples=100)
    assert result["mean_difference_per_case"] == expected
    assert result["ci95"] == [expected, expected]
    test = runner.exact_mcnemar(left, right, "accepted_correct")
    assert test["planner_only_success"] == wins
    assert test["fixed_only_success"] == losses
    assert test["p_two_sided"] == (0.125 if wins + losses else 1.0)


def test_cost_direction_and_invalid_pairing():
    result = runner.paired_difference(
        [{"optional_scans": 0}], [{"optional_scans": 1}], "optional_scans", seed=1, resamples=100
    )
    assert result["mean_difference_per_case"] == -1
    assert result["ci95"] == [-1, -1]
    with pytest.raises(ValueError):
        runner.paired_difference([{}], [], "accepted_correct", seed=1, resamples=100)


def test_selective_risk_denominator_and_zero_acceptance():
    rows = [
        {
            "top1_correct": 1,
            "accepted_correct": 1,
            "accepted": 1,
            "accepted_error": 0,
            "optional_scans": 1,
        },
        {
            "top1_correct": 0,
            "accepted_correct": 0,
            "accepted": 1,
            "accepted_error": 1,
            "optional_scans": 1,
        },
        {
            "top1_correct": 1,
            "accepted_correct": 0,
            "accepted": 0,
            "accepted_error": 0,
            "optional_scans": 0,
        },
    ]
    result = runner.summarize(rows)
    assert result["selective_risk"] == 0.5
    assert result["coverage"] == 2 / 3
    assert result["mean_total_acquisitions"] == 1 + 2 / 3
    assert runner.summarize(rows[2:])["selective_risk"] is None


def test_complementarity_ties_and_stop_handling():
    rows = []
    for index, (cid, ead, action, initial) in enumerate(
        [
            (1, 0, "CID40", 0),
            (0, 1, "STOP", 1),
            (1, 1, "EAD16", 0),
            (0, 0, "STOP", 0),
        ]
    ):
        outcomes = {
            "cid20_only": initial,
            "always_cid40": cid,
            "always_ead16": ead,
            "separation": {"STOP": initial, "CID40": cid, "EAD16": ead}[action],
        }
        rows.append(
            {
                "case_id": str(index),
                "policies": {
                    policy: {
                        "top1_correct": value,
                        "chosen_action": action if policy == "separation" else "STOP",
                    }
                    for policy, value in outcomes.items()
                },
            }
        )
    result = runner.complementarity(rows, "top1_correct")
    assert result["counts"] == {"cid40_only": 1, "ead16_only": 1, "both": 1, "neither": 1}
    assert result["hindsight_best_measurement_count"] == 3
    choice = runner.choice_diagnostic(rows, "top1_correct")
    assert choice["n_sensitive"] == 2
    assert choice["n_ties_excluded"] == 2
    assert choice["n_sensitive_stopped"] == 1
    assert choice["choice_accuracy_among_measured_sensitive"] == 1
    assert choice["choice_success_fraction_including_stops_as_nonselection"] == 0.5
    assert choice["planner_regret_count"] == 0  # STOP was correct, not a regret.


def test_independent_real_dev_branches(tmp_path):
    cases, identities, oracle = runner.load_dev_inputs()
    assert len(cases) == len(identities) == len(oracle) == 72
    assert set(cases.split) == {"dev"}
    oracle_path = tmp_path / "dev_cases.json"
    oracle_path.write_text(json.dumps(oracle))
    service = SpectraPilotService(oracle_path=oracle_path)
    service.repository = CaseRepository(cases, service.references)
    case_id = cases.iloc[0].case_id
    results = {policy: runner.run_branch(service, case_id, policy) for policy in runner.POLICIES}
    assert len({r["initial_hash"] for r in results.values()}) == 1
    assert results["cid20_only"]["investigation"]["observed_actions"] == ["CID20"]
    assert results["always_cid40"]["investigation"]["observed_actions"] == ["CID20", "CID40"]
    assert results["always_ead16"]["investigation"]["observed_actions"] == ["CID20", "EAD16"]
    for result in results.values():
        assert not result["investigation"]["intervention_history"]
        assert len(result["investigation"]["observed_actions"]) <= 2


def test_generated_fields_recompute_from_per_case_rows():
    payload = json.loads((runner.OUTPUT / "dev_modality_headroom.json").read_text())
    recomputed = runner.analyze(payload["rows"], seed=20261021, resamples=2000)
    for key in recomputed:
        assert payload[key] == recomputed[key]
    assert (runner.OUTPUT / "dev_modality_headroom.md").read_text() == runner.render_markdown(
        payload
    )
    assert len({r["case_id"] for r in payload["rows"]}) == payload["n"] == 72
    assert all(r["split"] == "dev" for r in payload["rows"])

"""Product-path controls and recomputation of the train-only stage-one study."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from spectrapilot.data.repository import CaseRepository
from spectrapilot.paths import load_config
from spectrapilot.planning.oracle import OracleStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "train_stage1_reference", ROOT / "scripts/check_train_stage1_reference.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reference_inputs():
    metadata = pd.DataFrame(
        [
            {
                "compound_full_inchikey": cid,
                "canonical_smiles": "CCO",
                "precursor_mz": 200,
                "exact_mass": 198.992723533379,
                "adduct": "[M+H]+",
            }
            for cid in ("A", "B")
        ]
    )

    class Predictor:
        records = {
            ("A", "CID60"): {
                "record_id": "a-60",
                "mz": np.array([80, 100, 180]),
                "intensity": np.array([1, 0.3, 0.1]),
            },
            ("A", "CID40"): {"record_id": "a-40"},
        }

        def predict(self, candidate, action, fold):
            return {
                "methods": {
                    "current_conditional": (np.array([50, 100, 140]), np.array([1, 0.5, 0.2])),
                    "donor_agreement": (np.array([50, 100, 140]), np.array([0.5, 1, 0.2])),
                },
                "reliability": {"current_conditional": 0.03, "donor_agreement": 0.03},
                "donor_ids": ["training-donor"],
            }

    return metadata, Predictor()


def test_same_reserved_anchors_but_changed_predictions(runner, reference_inputs):
    metadata, predictor = reference_inputs
    old, old_anchors = runner.make_references(
        metadata, predictor, "fold0", {"A", "B"}, "current_conditional", "training_cid60_anchored"
    )
    new, new_anchors = runner.make_references(
        metadata, predictor, "fold0", {"A", "B"}, "donor_agreement", "training_cid60_anchored"
    )
    assert old_anchors == new_anchors == ["A"]
    for action in ("CID20", "EAD16"):
        assert not np.array_equal(
            old.template("A", action).intensity, new.template("A", action).intensity
        )
        assert (
            old.template("A", action).reliability == new.template("A", action).reliability == 0.03
        )
    np.testing.assert_array_equal(old.template("A", "CID40").mz, new.template("A", "CID40").mz)
    assert old.template("A", "CID40").reliability == new.template("A", "CID40").reliability == 0.75
    assert new.template("B", "CID40").source == "oof_donor_agreement"
    native, anchors = runner.make_references(
        metadata, predictor, "fold0", {"A", "B"}, "donor_agreement", "native_predicted"
    )
    assert not anchors
    assert native.template("A", "CID40").source == "oof_donor_agreement"


def test_actual_product_sessions_independent_and_budgeted(runner, reference_inputs, tmp_path):
    metadata, predictor = reference_inputs
    references, _ = runner.make_references(
        metadata, predictor, "fold0", {"A", "B"}, "current_conditional", "native_predicted"
    )
    cases = pd.DataFrame(
        [
            {
                "case_id": "synthetic",
                "precursor_mz": 200,
                "candidate_ids": ["A", "B"],
                "available_actions": ["CID40", "EAD16"],
                "split": "train",
            }
        ]
    )
    observations = {
        action: {
            "action": action,
            "fragmentation": fragment,
            "energy_ev": energy,
            "accession": "synthetic-" + action,
            "peaks_mz": [50, 100, 140, 160],
            "peaks_intensity": [1, 0.5, 0.2, 0.1],
        }
        for action, fragment, energy in (
            ("CID20", "CID", 20),
            ("CID40", "CID", 40),
            ("EAD16", "EAD", 16),
        )
    }
    oracle = OracleStore(
        {"synthetic": {"initial": observations.pop("CID20"), "hidden": observations}},
        log_path=tmp_path / "access.jsonl",
    )
    scorer, planner = runner.create_components(load_config("multims2"), load_config("policies"))
    runtime = SimpleNamespace(
        repository=CaseRepository(cases, references), oracle=oracle, scorer=scorer, planner=planner
    )
    results = {
        policy: runner.run_branch(runtime, "synthetic", policy) for policy in runner.POLICIES
    }
    assert len({item["initial_observation_hash"] for item in results.values()}) == 1
    assert len({item["initial_ranking_hash"] for item in results.values()}) == 1
    assert results["cid20_only"]["investigation"]["observed_actions"] == ["CID20"]
    assert results["always_cid40"]["investigation"]["observed_actions"] == ["CID20", "CID40"]
    assert results["always_ead16"]["investigation"]["observed_actions"] == ["CID20", "EAD16"]
    assert all(len(item["investigation"]["observed_actions"]) <= 2 for item in results.values())
    assert scorer.tempering == 0.85 and planner.stop_support == 0.90
    assert planner.identified_min_support == 0.72 and planner.identified_min_fit == 0.30


def test_zero_acceptance_risk_is_undefined_not_zero(runner):
    empty = [{"accepted_error": 0, "accepted": 0}]
    result = runner.risk_difference(empty, empty, ["group"], seed=1, resamples=100)
    assert result["difference"] is None
    assert result["ci95_valid_resamples"] is None
    assert result["valid_resamples"] == 0 and result["undefined_resamples"] == 100


@pytest.mark.parametrize("sign", [-1, 0, 1])
def test_paired_signs_intervals_and_risk(runner, sign):
    positive = {
        "top1_correct": 1,
        "accepted_correct": 1,
        "accepted_error": 0,
        "accepted": 1,
        "optional_scans": 0,
    }
    negative = {
        "top1_correct": 0,
        "accepted_correct": 0,
        "accepted_error": 1,
        "accepted": 1,
        "optional_scans": 1,
    }
    a, b = (
        (positive, negative)
        if sign > 0
        else (negative, positive)
        if sign < 0
        else (positive, positive)
    )
    result = runner.compare([a] * 3, [b] * 3, ["g0", "g0", "g1"], seed=20261021, resamples=100)
    assert result["accepted_correct"]["ci95"] == [sign, sign]
    assert result["optional_scans"]["ci95"] == [-sign, -sign]
    assert result["selective_risk"]["difference"] == -sign


def test_random_comparator_is_exact_expected_counts(runner):
    rows = [
        {
            "policies": {
                "always_cid40": {
                    "top1_correct": 1,
                    "accepted_correct": 1,
                    "accepted_error": 0,
                    "accepted": 1,
                    "optional_scans": 1,
                },
                "always_ead16": {
                    "top1_correct": 0,
                    "accepted_correct": 0,
                    "accepted_error": 0,
                    "accepted": 0,
                    "optional_scans": 1,
                },
            }
        }
    ]
    expected = runner.policy_rows(rows, "random_expected_50_50")[0]
    assert expected["accepted_correct"] == expected["accepted"] == 0.5
    assert expected["accepted_error"] == 0 and expected["optional_scans"] == 1


def test_saved_cohorts_recompute_and_audit_train_folds(runner):
    payload = json.loads((runner.OUTPUT / "train_stage1_reference.json").read_text())
    assert payload["cohorts"] == runner.analyze(payload["rows"], 20261021, 2000)
    assert (runner.OUTPUT / "train_stage1_reference.md").read_text() == runner.render_markdown(
        payload
    )
    folds = payload["fold_assignment"]
    anchor_sets = {}
    for entry in payload["anchor_audit"]:
        assert all(candidate in folds for candidate in entry["anchored_candidates"])
        key = (entry["fold"], entry["track"])
        anchor_sets.setdefault(key, []).append(entry["anchored_candidates"])
    assert all(pair[0] == pair[1] for pair in anchor_sets.values())
    for item in payload["donor_audit"]:
        assert all(
            donor in folds and folds[donor] != item["fold"] and donor != item["candidate_id"]
            for donor in item["donor_ids"]
        )
    previous = json.loads((ROOT / "reports/spectrapilot/train_reference_quality.json").read_text())
    assert folds == previous["fold_assignment"]
    hashes = {}
    for track in runner.TRACKS:
        for method in runner.METHODS:
            subset = [
                row for row in payload["rows"] if row["track"] == track and row["method"] == method
            ]
            assert len(subset) == len({row["case_id"] for row in subset}) == 737
            assert sum(row["ambiguous"] for row in subset) == 277
            for row in subset:
                assert row["split"] == "train" and row["true_id"] in folds
                assert row["fold"] == folds[row["true_id"]]
                hashes.setdefault(row["case_id"], set()).add(row["initial_observation_sha256"])
                assert row["true_id"] in row["candidate_ids"]
                assert all(outcome["optional_scans"] <= 1 for outcome in row["policies"].values())
    assert all(len(values) == 1 for values in hashes.values())

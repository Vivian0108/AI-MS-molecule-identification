"""Controls for fold isolation, consensus fidelity, uncertainty and reports."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator

from spectrapilot.data.prepare import _merge_donor_spectra, _morgan, _split_groups
from spectrapilot.paths import load_config

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "train_reference_quality", ROOT / "scripts/check_train_reference_quality.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_fast_current_consensus_matches_original_clustering():
    rng = np.random.default_rng(20261021)
    for _ in range(25):
        donors = []
        for _ in range(5):
            mz = np.sort(rng.integers(40, 70, size=20) + rng.uniform(-0.025, 0.025, size=20))
            donors.append((float(rng.uniform(0.1, 1)), mz, rng.uniform(0.01, 1, size=20)))
        expected_mz, expected_intensity, _ = _merge_donor_spectra(donors, 0.02)
        mz, intensity, agreement = runner.consensus_pair(donors, 0.02)
        np.testing.assert_array_equal(mz, expected_mz)
        np.testing.assert_allclose(intensity, expected_intensity, rtol=0, atol=1e-12)
        assert np.all((agreement >= 0) & (agreement <= 1))


def test_agreement_downweights_single_donor_peaks_and_empty_input():
    mz, current, agreement = runner.consensus_pair(
        [
            (1, [50, 100], [1, 0.8]),
            (1, [70, 100], [1, 0.8]),
        ],
        0.02,
    )
    np.testing.assert_array_equal(mz, [50, 70, 100])
    np.testing.assert_allclose(current, [1, 1, 0.8])
    np.testing.assert_allclose(agreement, [0.625, 0.625, 1])
    assert all(len(value) == 0 for value in runner.consensus_pair([], 0.02))


def test_fingerprint_generator_preserves_original_bits():
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    for smiles in ("CCO", "c1ccccc1O", "CC[C@H](O)C"):
        assert (
            generator.GetFingerprint(Chem.MolFromSmiles(smiles)).ToBitString()
            == _morgan(smiles, 2, 2048).ToBitString()
        )


def test_all_held_out_donors_and_candidate_self_are_excluded():
    metadata = pd.DataFrame(
        [
            {"compound_full_inchikey": cid, "canonical_smiles": smiles}
            for cid, smiles in (("A", "CCO"), ("B", "CCCO"), ("C", "CCCCO"))
        ]
    )
    records = pd.DataFrame(
        [
            {
                "compound_full_inchikey": cid,
                "action": action,
                "record_id": cid + action,
                "peaks_mz": [999.0] if cid != "C" else [50.0],
                "peaks_intensity": [1.0],
            }
            for cid in ("A", "B", "C")
            for action in runner.ACTIONS
        ]
    )
    predictor = runner.Predictor(
        metadata,
        metadata,
        records,
        {"A": "fold0", "B": "fold0", "C": "fold1"},
        load_config("multims2"),
    )
    for action in runner.ACTIONS:
        result = predictor.predict("A", action, "fold0")
        assert result["donor_ids"] == ["C"]
        for mz, intensity in result["methods"].values():
            np.testing.assert_array_equal(mz, [50.0])
            np.testing.assert_array_equal(intensity, [1.0])
        assert not predictor.predict("C", action, "fold0")["donor_ids"]


def test_group_bootstrap_sign_ties_and_group_count():
    groups = ["scaffold-a", "scaffold-a", "scaffold-b"]
    for difference in (-0.2, 0, 0.2):
        result = runner.grouped_interval([difference] * 3, groups, seed=20261021, resamples=100)
        assert result["n_scaffold_groups"] == 2
        np.testing.assert_allclose(result["ci95"], [difference, difference], rtol=0, atol=1e-12)
        assert result["mean_difference"] == pytest.approx(difference)
    with pytest.raises(ValueError):
        runner.grouped_interval([], [], seed=1, resamples=10)


def test_real_inputs_project_metadata_and_only_load_training_queries(monkeypatch):
    calls = []
    original = pd.read_parquet

    def record_call(path, **kwargs):
        calls.append((Path(path).name, kwargs))
        return original(path, **kwargs)

    monkeypatch.setattr(runner.pd, "read_parquet", record_call)
    metadata, train, records, targets = runner.load_inputs()
    assert len(train) == 1481 and len(targets) == 737
    assert sum(target["ambiguous"] for target in targets) == 277
    assert set(records.split) == {"train"}
    for name, kwargs in calls:
        if name == "candidate_universe.parquet":
            assert (
                "peaks_mz" not in kwargs["columns"] and "peaks_intensity" not in kwargs["columns"]
            )
        if name in ("records.parquet", "cases.parquet"):
            assert ("split", "==", "train") in kwargs["filters"]
    assert metadata.attrs["source_split_audit"][
        "stored_split_exactly_reproduced_by_connectivity_fallback"
    ]
    assert (train.scaffold != "").any()
    folds = _split_groups(train, 20261021, {f"fold{i}": 0.2 for i in range(5)})
    groups = {}
    for row in train.itertuples():
        groups.setdefault(runner.scaffold_group(row), set()).add(folds[row.compound_full_inchikey])
    assert all(len(values) == 1 for values in groups.values())


@pytest.mark.parametrize("agreement_gain,expected", [(0.10, "GO"), (0.02, "NO-GO")])
def test_gate_is_primary_and_requires_both_outcomes(agreement_gain, expected):
    quality, retrieval = [], []
    for index in range(5):
        for action in runner.ACTIONS:
            for method in runner.METHODS:
                quality.append(
                    {
                        "case_id": str(index),
                        "action": action,
                        "method": method,
                        "group": str(index),
                        "cosine": 0.1
                        + (
                            agreement_gain
                            if method == "donor_agreement"
                            else 0.7
                            if method == "nearest_neighbor"
                            else 0
                        ),
                        "reliability_proxy": 0.1,
                        "predicted_peak_count": 3,
                    }
                )
                retrieval.append(
                    {
                        "case_id": str(index),
                        "action": action,
                        "method": method,
                        "group": str(index),
                        "top1_correct": int(method != "current_conditional"),
                        "reciprocal_rank": 1 if method != "current_conditional" else 0.5,
                    }
                )
    result = runner.summarize(quality, retrieval, seed=20261021, resamples=100)
    assert result["next_step_gate"]["result"] == expected
    assert result["methods"]["EAD16"]["nearest_neighbor"]["mean_cosine"] > 0.7


def test_saved_rows_recompute_and_donors_are_fold_isolated():
    payload = json.loads((runner.OUTPUT / "train_reference_quality.json").read_text())
    result = runner.summarize(payload["quality_rows"], payload["retrieval_rows"], 20261021, 2000)
    for key in result:
        assert payload[key] == result[key]
    assert (runner.OUTPUT / "train_reference_quality.md").read_text() == runner.render_markdown(
        payload
    )
    folds = payload["fold_assignment"]
    for item in payload["donor_audit"]:
        assert all(
            folds[donor] != item["fold"] and donor != item["candidate_id"]
            for donor in item["donor_ids"]
        )
    for action in runner.ACTIONS:
        for method in runner.METHODS:
            rows = [
                row
                for row in payload["quality_rows"]
                if row["action"] == action and row["method"] == method
            ]
            assert len(rows) == len({row["case_id"] for row in rows}) == 737
            assert all(
                row["true_id"] in folds and folds[row["true_id"]] == row["fold"] for row in rows
            )

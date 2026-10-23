"""Train-only scaffold-held-out reference comparison; no production model edits."""

from __future__ import annotations

import gzip
import hashlib
import importlib.metadata
import json
import math
import platform
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold
from scipy.stats import spearmanr

from spectrapilot.data.prepare import _split_groups
from spectrapilot.paths import CURATED, ORACLE_PRIVATE, ROOT, load_config
from unknownid.core.ids import make_case_id
from unknownid.core.spectra import cosine_greedy

METHODS = ("current_conditional", "donor_agreement", "nearest_neighbor")
ACTIONS = ("CID20", "CID40", "EAD16")
OUTPUT = ROOT / "reports" / "spectrapilot"
PRIVATE = ORACLE_PRIVATE / "train_reference_quality"
INPUT_PATHS = (
    "configs/multims2.yaml",
    "configs/policies.yaml",
    "data/multims2/curated/records.parquet",
    "data/multims2/curated/cases.parquet",
    "data/multims2/curated/candidate_universe.parquet",
    "data/multims2/curated/split_manifest.json",
    "data/multims2/reference/templates.parquet",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scaffold_group(row):
    return str(row.scaffold or "") or f"ACYCLIC:{row.connectivity_key}"


def consensus_pair(donors, tolerance):
    """Reproduce first-created-cluster matching with a mass-bin lookup.

    Existing centroids never move. Choosing the lowest matching cluster index
    reproduces the original nested loop, including ties within tolerance.
    """
    mz_values, weighted_intensities, contributing_weights = [], [], []
    bins = defaultdict(list)
    total_weight = sum(weight for weight, _, _ in donors)
    for weight, mz, intensity in donors:
        for mass, height in zip(mz, intensity):
            mass, height = float(mass), float(height)
            bucket = math.floor(mass / tolerance)
            matches = [
                index
                for key in (bucket - 1, bucket, bucket + 1)
                for index in bins[key]
                if abs(mz_values[index] - mass) <= tolerance
            ]
            if matches:
                index = min(matches)
                weighted_intensities[index] += weight * height
                contributing_weights[index] += weight
            else:
                bins[bucket].append(len(mz_values))
                mz_values.append(mass)
                weighted_intensities.append(weight * height)
                contributing_weights.append(weight)
    order = np.argsort(mz_values)
    mz = np.asarray(mz_values, float)[order]
    numerator = np.asarray(weighted_intensities, float)[order]
    denominator = np.asarray(contributing_weights, float)[order]
    conditional = numerator / np.maximum(denominator, 1e-12)
    agreement = numerator / max(total_weight, 1e-12)
    for values in (conditional, agreement):
        if values.size and values.max() > 0:
            values /= values.max()
    return mz, conditional, agreement


def load_inputs():
    # The candidate-universe artifact also contains peak arrays. Explicit
    # column projection prevents reading dev/test measurements through it.
    columns = [
        "compound_full_inchikey",
        "canonical_smiles",
        "precursor_mz",
        "connectivity_key",
        "split",
    ]
    metadata = pd.read_parquet(CURATED / "candidate_universe.parquet", columns=columns)
    saved_assignments = _split_groups(metadata, 20261021, {"train": 0.7, "dev": 0.15, "test": 0.15})
    source_split_matches_connectivity_fallback = all(
        saved_assignments[str(row.compound_full_inchikey)] == row.split
        for row in metadata.itertuples()
    )
    scaffolds = []
    for row in metadata.itertuples():
        molecule = Chem.MolFromSmiles(str(row.canonical_smiles))
        if molecule is None:
            raise ValueError("invalid structure while deriving scaffold groups")
        scaffolds.append(MurckoScaffold.MurckoScaffoldSmiles(mol=molecule))
    metadata["scaffold"] = scaffolds
    metadata.attrs["source_split_audit"] = {
        "saved_candidate_universe_has_scaffold_column": False,
        "stored_split_exactly_reproduced_by_connectivity_fallback": source_split_matches_connectivity_fallback,
        "study_scaffolds_derived_from_smiles": True,
        "saved_split_changed": False,
    }
    train = metadata[metadata.split == "train"].copy()
    cases = pd.read_parquet(
        CURATED / "cases.parquet", filters=[("split", "==", "train")]
    ).sort_values("case_id")
    records = pd.read_parquet(CURATED / "records.parquet", filters=[("split", "==", "train")])
    if (
        not cases.case_id.is_unique
        or records.duplicated(["compound_full_inchikey", "action"]).any()
    ):
        raise ValueError("duplicate training cases or retained observation records")
    id_map = {
        make_case_id(str(row.compound_full_inchikey), float(row.precursor_mz)): str(
            row.compound_full_inchikey
        )
        for row in train.itertuples()
    }
    targets = []
    groups = {str(row.compound_full_inchikey): scaffold_group(row) for row in train.itertuples()}
    for case in cases.itertuples():
        true_id = id_map[case.case_id]
        if true_id not in case.candidate_ids:
            raise ValueError("truth absent from original closed-world candidate set")
        targets.append(
            {
                "case_id": case.case_id,
                "true_id": true_id,
                "candidate_ids": case.candidate_ids.tolist(),
                "group": groups[true_id],
                "ambiguous": bool(case.precursor_ambiguous),
            }
        )
    return metadata, train, records, targets


class Predictor:
    def __init__(self, metadata, train, records, folds, config):
        self.folds = folds
        self.tolerance = float(config.get_path("preprocessing.match_tolerance_da"))
        self.minimum = float(config.get_path("template_model.min_similarity"))
        self.k = {
            action: int(
                config.get_path(
                    "template_model.k_ead" if action.startswith("EAD") else "template_model.k_cid"
                )
            )
            for action in ACTIONS
        }
        generator = rdFingerprintGenerator.GetMorganGenerator(
            radius=int(config.get_path("template_model.fingerprint_radius")),
            fpSize=int(config.get_path("template_model.fingerprint_bits")),
        )
        self.fingerprints = {}
        for row in metadata.itertuples():
            molecule = Chem.MolFromSmiles(str(row.canonical_smiles))
            if molecule is not None:
                self.fingerprints[str(row.compound_full_inchikey)] = generator.GetFingerprint(
                    molecule
                )
        self.donor_ids = sorted(set(train.compound_full_inchikey) & set(self.fingerprints))
        self.donor_fps = [self.fingerprints[cid] for cid in self.donor_ids]
        self.records = {
            (str(row.compound_full_inchikey), str(row.action)): {
                "mz": np.asarray(row.peaks_mz, float),
                "intensity": np.asarray(row.peaks_intensity, float),
                "record_id": str(row.record_id),
            }
            for row in records.itertuples()
            if row.action in ACTIONS + ("CID60",)
        }
        self.similarities = {}
        self.cache = {}

    def predict(self, candidate_id, action, fold):
        key = (str(fold), candidate_id, action)
        if key in self.cache:
            return self.cache[key]
        if candidate_id not in self.similarities:
            self.similarities[candidate_id] = np.asarray(
                DataStructs.BulkTanimotoSimilarity(self.fingerprints[candidate_id], self.donor_fps)
                if candidate_id in self.fingerprints
                else np.zeros(len(self.donor_ids)),
                float,
            )
        similarity = self.similarities[candidate_id]
        eligible = [
            index
            for index, donor in enumerate(self.donor_ids)
            if self.folds[donor] != fold
            and donor != candidate_id
            and (donor, action) in self.records
            and similarity[index] >= self.minimum
        ]
        eligible.sort(key=lambda index: (-similarity[index], self.donor_ids[index]))
        selected = eligible[: self.k[action]]
        donor_ids = [self.donor_ids[index] for index in selected]
        assert all(self.folds[cid] != fold and cid != candidate_id for cid in donor_ids)
        weighted = [
            (
                float(similarity[index]) ** 2,
                self.records[(self.donor_ids[index], action)]["mz"],
                self.records[(self.donor_ids[index], action)]["intensity"],
            )
            for index in selected
        ]
        mz, conditional, agreement = consensus_pair(weighted, self.tolerance)
        nearest = (
            self.records[(donor_ids[0], action)]
            if donor_ids
            else {"mz": np.array([]), "intensity": np.array([])}
        )
        proxy = float(np.mean([weight for weight, _, _ in weighted])) if weighted else 0.0
        nearest_proxy = float(similarity[selected[0]] ** 2) if selected else 0.0
        scale = 0.75 if action.startswith("EAD") else 1.0
        result = {
            "methods": {
                "current_conditional": (mz, conditional),
                "donor_agreement": (mz, agreement),
                "nearest_neighbor": (nearest["mz"], nearest["intensity"]),
            },
            "reliability": {
                "current_conditional": scale * proxy,
                "donor_agreement": scale * proxy,
                "nearest_neighbor": scale * nearest_proxy,
            },
            "donor_ids": donor_ids,
            "donor_similarities": [float(similarity[index]) for index in selected],
        }
        self.cache[key] = result
        return result


def grouped_interval(values, groups, seed, resamples):
    values = np.asarray(values, float)
    if not len(values) or len(values) != len(groups):
        raise ValueError("nonempty paired values and matching groups required")
    keys = sorted(set(groups))
    grouped = {key: [] for key in keys}
    for value, group in zip(values, groups):
        grouped[group].append(value)
    sums = np.array([sum(grouped[key]) for key in keys])
    counts = np.array([len(grouped[key]) for key in keys])
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, len(keys), size=(resamples, len(keys)))
    means = sums[samples].sum(axis=1) / counts[samples].sum(axis=1)
    return {
        "mean_difference": float(values.mean()),
        "ci95": np.quantile(means, [0.025, 0.975]).tolist(),
        "n_molecules": len(values),
        "n_scaffold_groups": len(keys),
        "resampling_unit": "whole scaffold group",
        "seed": seed,
        "resamples": resamples,
    }


def reliability_summary(rows):
    x = np.array([row["reliability_proxy"] for row in rows])
    y = np.array([row["cosine"] for row in rows])
    correlation = float(spearmanr(x, y).statistic) if np.std(x) > 0 and np.std(y) > 0 else None
    bins = []
    edges = [0, 0.1, 0.2, 0.3, 0.5, 1]
    for index, (lower, upper) in enumerate(zip(edges, edges[1:])):
        mask = (x >= lower) & ((x <= upper) if index == len(edges) - 2 else (x < upper))
        bins.append(
            {
                "lower": lower,
                "upper": upper,
                "n": int(mask.sum()),
                "mean_proxy": float(x[mask].mean()) if mask.any() else None,
                "mean_observed_cosine": float(y[mask].mean()) if mask.any() else None,
            }
        )
    return {
        "spearman_proxy_vs_cosine": correlation,
        "bins": bins,
        "calibrated_probability": False,
        "fitted_calibration_map": False,
    }


def summarize(quality, retrieval, seed, resamples):
    summaries, comparisons = {}, {}
    for action in ACTIONS:
        summaries[action] = {}
        for method in METHODS:
            rows = [row for row in quality if row["action"] == action and row["method"] == method]
            ranks = [
                row for row in retrieval if row["action"] == action and row["method"] == method
            ]
            values = np.array([row["cosine"] for row in rows])
            summaries[action][method] = {
                "n": len(rows),
                "mean_cosine": float(values.mean()),
                "median_cosine": float(np.median(values)),
                "q25_cosine": float(np.quantile(values, 0.25)),
                "q75_cosine": float(np.quantile(values, 0.75)),
                "empty_predictions": sum(row["predicted_peak_count"] == 0 for row in rows),
                "ambiguous_n": len(ranks),
                "ambiguous_top1_correct": sum(row["top1_correct"] for row in ranks),
                "ambiguous_top1_rate": float(np.mean([row["top1_correct"] for row in ranks])),
                "ambiguous_mrr": float(np.mean([row["reciprocal_rank"] for row in ranks])),
                "reliability": reliability_summary(rows),
            }
        comparisons[action] = {}
        for method in METHODS[1:]:
            by_case = {
                row["case_id"]: row
                for row in quality
                if row["action"] == action and row["method"] == method
            }
            base = [
                row for row in quality if row["action"] == action and row["method"] == METHODS[0]
            ]
            quality_diff = grouped_interval(
                [by_case[row["case_id"]]["cosine"] - row["cosine"] for row in base],
                [row["group"] for row in base],
                seed,
                resamples,
            )
            by_case = {
                row["case_id"]: row
                for row in retrieval
                if row["action"] == action and row["method"] == method
            }
            base = [
                row for row in retrieval if row["action"] == action and row["method"] == METHODS[0]
            ]
            rank_diff = grouped_interval(
                [by_case[row["case_id"]]["top1_correct"] - row["top1_correct"] for row in base],
                [row["group"] for row in base],
                seed,
                resamples,
            )
            comparisons[action][method] = {
                "direction": "alternative minus current conditional consensus",
                "mean_cosine_difference": quality_diff,
                "native_top1_rate_difference": rank_diff,
            }
    primary = comparisons["EAD16"]["donor_agreement"]
    quality_pass = (
        primary["mean_cosine_difference"]["mean_difference"] >= 0.05
        and primary["mean_cosine_difference"]["ci95"][0] > 0
    )
    rank_pass = (
        primary["native_top1_rate_difference"]["mean_difference"] >= 0.05
        and primary["native_top1_rate_difference"]["ci95"][0] > 0
    )
    return {
        "methods": summaries,
        "paired_vs_current": comparisons,
        "next_step_gate": {
            "primary_contrast": "EAD16 donor_agreement minus current_conditional",
            "cosine_gain_at_least_0_05_with_positive_lower_ci": bool(quality_pass),
            "native_top1_gain_at_least_0_05_with_positive_lower_ci": bool(rank_pass),
            "result": "GO" if quality_pass and rank_pass else "NO-GO",
            "meaning": "practical gate for a learned-selector follow-up; not intrinsic EAD feasibility",
        },
    }


def render_markdown(payload):
    lines = [
        "# Train-only reference quality and reliability",
        "",
        "**Grouped cross-validated training estimate; not an independent test.**",
        "",
        f"{payload['n_targets']} complete training molecules, {payload['n_ambiguous']} precursor-ambiguous training cases, "
        "five scaffold-held-out folds. No development/test query spectra, fitting on outer outcomes or production changes.",
        "",
        "All methods predict native-action references from non-held-out training donors. "
        "Retrieval is native-action cosine-only ranking over each ambiguous case's original candidates; "
        "it is not stage-one accepted-correct identification.",
        "",
        "| Action | Method | n | Mean cosine | Median cosine | Ambiguous top-1 | Ambiguous MRR | Reliability Spearman |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for action, methods in payload["methods"].items():
        for method, item in methods.items():
            correlation = item["reliability"]["spearman_proxy_vs_cosine"]
            rho = f"{correlation:.3f}" if correlation is not None else "undefined"
            lines.append(
                f"| {action} | {method} | {item['n']} | {item['mean_cosine']:.4f} | "
                f"{item['median_cosine']:.4f} | {item['ambiguous_top1_correct']}/{item['ambiguous_n']} | "
                f"{item['ambiguous_mrr']:.4f} | {rho} |"
            )
    lines += [
        "",
        "## Paired alternatives minus current consensus",
        "",
        "Intervals resample whole scaffold groups, preserving all molecules in each sampled group.",
        "",
        "| Action | Alternative | Mean cosine gain | 95% CI | Native retrieval top-1 gain | 95% CI |",
        "|---|---|---:|---|---:|---|",
    ]
    for action, methods in payload["paired_vs_current"].items():
        for method, item in methods.items():
            quality, rank = item["mean_cosine_difference"], item["native_top1_rate_difference"]
            lines.append(
                f"| {action} | {method} | {quality['mean_difference']:+.4f} | "
                f"[{quality['ci95'][0]:+.4f}, {quality['ci95'][1]:+.4f}] | "
                f"{rank['mean_difference']:+.4f} | [{rank['ci95'][0]:+.4f}, {rank['ci95'][1]:+.4f}] |"
            )
    gate = payload["next_step_gate"]
    lines += [
        "",
        "## Predeclared next-step gate",
        "",
        f"**{gate['result']}** for a learned-selector follow-up under this protocol.",
        "",
        f"- EAD donor-agreement mean cosine gain ≥0.05 and positive lower CI: {gate['cosine_gain_at_least_0_05_with_positive_lower_ci']}.",
        f"- EAD native-action top-1 gain ≥0.05 and positive lower CI: {gate['native_top1_gain_at_least_0_05_with_positive_lower_ci']}.",
        "- Both conditions must pass. Nearest-neighbour results are secondary and do not automatically pass this gate.",
        "",
        "## Source split audit",
        "",
        "The saved candidate-universe table lacks the scaffold column computed during QC. "
        "The source split is labelled scaffold-grouped but the preparation function therefore "
        "uses connectivity fallback for every compound. Stored split reproduced exactly by "
        f"that fallback: {payload['source_split_audit']['stored_split_exactly_reproduced_by_connectivity_fallback']}. "
        "The saved split was not changed. This study derives real Bemis-Murcko scaffolds "
        "from SMILES for its five training-only folds.",
        "",
        "## Replicates and measured reference diagnostic",
        "",
        f"Retained independent same-compound/action duplicate rows: {payload['replicate_audit']['separately_retained_duplicate_rows']}. "
        f"Rows with metadata replicate_count >1: {payload['replicate_audit']['rows_with_multiple_source_replicates']}. "
        "The curated artifact keeps one representative; independent replicate validation was not performed.",
        "",
        f"CID40 query versus same-compound CID60 reference (different energies, diagnostic only): "
        f"n={payload['cid60_anchor_diagnostic']['n']}, median cosine={payload['cid60_anchor_diagnostic']['median_cosine']:.4f}.",
        "",
        "## Limitations",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines += ["", "Reproduce: `make reference-quality` after dependency installation.", ""]
    return "\n".join(lines)


def run():
    hashes = {path: sha256(ROOT / path) for path in INPUT_PATHS}
    cfg = load_config("multims2")
    seed = int(cfg.get_path("evaluation.seed"))
    resamples = int(cfg.get_path("evaluation.bootstrap_resamples"))
    metadata, train, records, targets = load_inputs()
    folds = _split_groups(train, seed, {f"fold{i}": 0.2 for i in range(5)})
    group_folds = defaultdict(set)
    for row in train.itertuples():
        group_folds[scaffold_group(row)].add(folds[str(row.compound_full_inchikey)])
    assert all(len(assigned) == 1 for assigned in group_folds.values())
    predictor = Predictor(metadata, train, records, folds, cfg)
    quality, retrieval, anchor_values = [], [], []
    for index, target in enumerate(targets):
        cid, fold = target["true_id"], folds[target["true_id"]]
        for action in ACTIONS:
            observed = predictor.records[(cid, action)]
            predicted = predictor.predict(cid, action, fold)
            for method in METHODS:
                mz, intensity = predicted["methods"][method]
                cosine, matched = cosine_greedy(
                    observed["mz"], observed["intensity"], mz, intensity, predictor.tolerance
                )
                quality.append(
                    {
                        "case_id": target["case_id"],
                        "true_id": cid,
                        "group": target["group"],
                        "fold": fold,
                        "action": action,
                        "method": method,
                        "cosine": cosine,
                        "matched_peaks": matched,
                        "predicted_peak_count": len(mz),
                        "donor_count": min(1, len(predicted["donor_ids"]))
                        if method == "nearest_neighbor"
                        else len(predicted["donor_ids"]),
                        "nearest_donor_similarity": predicted["donor_similarities"][0]
                        if predicted["donor_ids"]
                        else None,
                        "reliability_proxy": predicted["reliability"][method],
                    }
                )
            if target["ambiguous"]:
                candidate_predictions = {
                    candidate: predictor.predict(candidate, action, fold)
                    for candidate in target["candidate_ids"]
                }
                for method in METHODS:
                    scores = {}
                    for candidate, prediction in candidate_predictions.items():
                        mz, intensity = prediction["methods"][method]
                        scores[candidate] = cosine_greedy(
                            observed["mz"],
                            observed["intensity"],
                            mz,
                            intensity,
                            predictor.tolerance,
                        )[0]
                    order = sorted(scores, key=lambda candidate: (-scores[candidate], candidate))
                    rank = order.index(cid) + 1
                    retrieval.append(
                        {
                            "case_id": target["case_id"],
                            "true_id": cid,
                            "group": target["group"],
                            "fold": fold,
                            "action": action,
                            "method": method,
                            "top1_id": order[0],
                            "top1_correct": int(order[0] == cid),
                            "reciprocal_rank": 1 / rank,
                            "scores": scores,
                            "n_candidates": len(scores),
                        }
                    )
        if (cid, "CID60") in predictor.records:
            observed, reference = (
                predictor.records[(cid, "CID40")],
                predictor.records[(cid, "CID60")],
            )
            assert observed["record_id"] != reference["record_id"]
            anchor_values.append(
                cosine_greedy(
                    observed["mz"],
                    observed["intensity"],
                    reference["mz"],
                    reference["intensity"],
                    predictor.tolerance,
                )[0]
            )
        if (index + 1) % 100 == 0:
            print(f"Scored {index + 1}/{len(targets)} training targets", flush=True)
    assert len({row["case_id"] for row in quality}) == len(targets)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    audit = []
    predictions = []
    for (fold, candidate, action), result in sorted(predictor.cache.items()):
        audit.append(
            {
                "fold": fold,
                "candidate_id": candidate,
                "action": action,
                "donor_ids": result["donor_ids"],
                "donor_similarities": result["donor_similarities"],
            }
        )
        predictions.append(
            {
                **audit[-1],
                "methods": {
                    method: {"mz": mz.tolist(), "intensity": intensity.tolist()}
                    for method, (mz, intensity) in result["methods"].items()
                },
            }
        )
    predicted_path = PRIVATE / "predictions.json.gz"
    with gzip.open(predicted_path, "wt") as handle:
        json.dump(predictions, handle, separators=(",", ":"))
    summary = summarize(quality, retrieval, seed, resamples)
    assert hashes == {path: sha256(ROOT / path) for path in INPUT_PATHS}
    payload = {
        "study": "Train-only reference quality and reliability",
        "label": "grouped cross-validated TRAINING estimate; not an independent test",
        "protocol_commit": "0d6ccbe",
        "protocol_clarification_commit": "d0c66c2",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "pyarrow", "scipy", "rdkit")
        },
        "dataset_version": cfg.get_path("dataset.commit"),
        "source_sha256": {
            path: sha256(ROOT / path)
            for path in (
                "scripts/check_train_reference_quality.py",
                "docs/train_reference_quality_protocol.md",
                "src/spectrapilot/data/prepare.py",
                "src/unknownid/core/spectra.py",
            )
        },
        "input_sha256": hashes,
        "source_split_audit": metadata.attrs["source_split_audit"],
        "inputs_unchanged": True,
        "n_training_donor_compounds": len(train),
        "n_targets": len(targets),
        "n_ambiguous": sum(target["ambiguous"] for target in targets),
        "fold_assignment": folds,
        "scaffold_group_by_training_compound": {
            str(row.compound_full_inchikey): scaffold_group(row) for row in train.itertuples()
        },
        "fold_target_counts": dict(Counter(folds[target["true_id"]] for target in targets)),
        "fold_groups_disjoint": True,
        "donor_audit": audit,
        "predictions_artifact": {
            "path": "data/multims2/oracle_private/train_reference_quality/predictions.json.gz",
            "sha256": sha256(predicted_path),
            "contains_test_query_spectra": False,
        },
        "replicate_audit": {
            "training_records": len(records),
            "separately_retained_duplicate_rows": int(
                records.duplicated(["compound_full_inchikey", "action"]).sum()
            ),
            "rows_with_multiple_source_replicates": int((records.replicate_count > 1).sum()),
            "independent_replicate_validation": "not performed; individual repeats are not retained",
        },
        "cid60_anchor_diagnostic": {
            "n": len(anchor_values),
            "median_cosine": float(np.median(anchor_values)),
            "mean_cosine": float(np.mean(anchor_values)),
            "energy_mismatch": True,
        },
        **summary,
        "quality_rows": quality,
        "retrieval_rows": retrieval,
        "limitations": [
            "Train-only grouped cross-validation estimates; development and frozen test queries were not loaded.",
            "Fixed three-method comparison with one predeclared primary contrast; no tuning or selected-model generalization claim.",
            "Native-action cosine retrieval is a predictor diagnostic, not stage-one product acceptance or a planner benchmark.",
            "Same candidate sets and chemical filters; non-training library structure metadata is allowed, but no non-training measured peaks.",
            "Proxy reliability is descriptive, not a calibrated probability; no fitted calibration map or learned selector.",
            "Consensus spectra are structure-neighbour transfers, not a mechanistic fragmentation model.",
            "Stored predicted spectra are ignored local study artifacts; source/input hashes and donor provenance are recorded.",
            "No independently retained replicate pairs; metadata repeat counts do not establish independent validation.",
        ],
    }
    (OUTPUT / "train_reference_quality.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUTPUT / "train_reference_quality.md").write_text(render_markdown(payload))
    print(
        json.dumps(
            {
                "n_targets": len(targets),
                "n_ambiguous": payload["n_ambiguous"],
                "EAD16": payload["methods"]["EAD16"],
                "next_step_gate": payload["next_step_gate"],
            },
            indent=2,
        )
    )
    return payload


if __name__ == "__main__":
    run()

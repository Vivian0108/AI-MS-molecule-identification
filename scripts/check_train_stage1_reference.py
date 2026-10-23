"""Frozen product workflow with two OOF reference methods; training queries only."""

from __future__ import annotations

import importlib.metadata
import hashlib
import json
import platform
import subprocess
from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

import check_modality_headroom as headroom
import check_train_reference_quality as quality
from spectrapilot.data.prepare import _split_groups
from spectrapilot.data.repository import CaseRepository
from spectrapilot.paths import CURATED, ORACLE_PRIVATE, ROOT, load_config
from spectrapilot.planning.oracle import OracleStore, VirtualInstrument
from spectrapilot.planning.separation import SeparationPlanner
from spectrapilot.planning.session import InvestigationSession
from spectrapilot.science.scoring import CandidateScorer
from spectrapilot.science.templates import ReferenceStore

METHODS = ("current_conditional", "donor_agreement")
TRACKS = ("native_predicted", "training_cid60_anchored")
POLICIES = headroom.POLICIES
OUTPUT = ROOT / "reports" / "spectrapilot"
PRIVATE = ORACLE_PRIVATE / "train_stage1_reference"
INPUT_PATHS = quality.INPUT_PATHS + ("reports/spectrapilot/train_reference_quality.json",)


def create_components(config, policy):
    scorer = CandidateScorer(
        tolerance_da=float(config.get_path("preprocessing.match_tolerance_da", 0.02)),
        tempering=0.85,
    )
    planner = SeparationPlanner(
        stop_support=float(policy.get_path("planner.stop_support", 0.90)),
        stop_margin=float(policy.get_path("planner.stop_margin", 0.65)),
        stop_score=float(policy.get_path("planner.stop_score", 0.01)),
        identified_min_support=float(policy.get_path("confidence.identified_min_support", 0.72)),
        identified_min_margin=float(policy.get_path("confidence.identified_min_margin", 0.22)),
        identified_min_fit=float(policy.get_path("confidence.identified_min_fit", 0.30)),
        identified_min_matched_peaks=int(
            policy.get_path("confidence.identified_min_matched_peaks", 2)
        ),
        ead_cost_ratio=float(policy.get_path("planner.ead_cost_ratio", 1)),
        tolerance_da=float(config.get_path("preprocessing.match_tolerance_da", 0.02)),
    )
    return scorer, planner


def make_references(metadata, predictor, fold, candidate_ids, method, track):
    templates, anchors = [], []
    for candidate in sorted(candidate_ids):
        for action in quality.ACTIONS:
            prediction = predictor.predict(candidate, action, fold)
            mz, intensity = prediction["methods"][method]
            source, reliability = f"oof_{method}", prediction["reliability"][method]
            donor_count = len(prediction["donor_ids"])
            mean_similarity = reliability / (0.75 if action.startswith("EAD") else 1)
            if (
                track == "training_cid60_anchored"
                and action == "CID40"
                and (candidate, "CID60") in predictor.records
            ):
                reference = predictor.records[(candidate, "CID60")]
                if (candidate, "CID40") in predictor.records:
                    assert (
                        reference["record_id"]
                        != predictor.records[(candidate, "CID40")]["record_id"]
                    )
                mz, intensity = reference["mz"], reference["intensity"]
                source, reliability, donor_count, mean_similarity = "reference_cid60", 0.75, 1, 1.0
                anchors.append(candidate)
            templates.append(
                {
                    "candidate_id": candidate,
                    "action": action,
                    "peaks_mz": mz,
                    "peaks_intensity": intensity,
                    "source": source,
                    "reliability": reliability,
                    "n_donors": donor_count,
                    "mean_similarity": mean_similarity,
                }
            )
    references = ReferenceStore(
        metadata[metadata.compound_full_inchikey.isin(candidate_ids)],
        pd.DataFrame(templates),
        ppm_tolerance=10.0,
    )
    return references, sorted(anchors)


def run_branch(runtime, case_id, policy):
    session = InvestigationSession(
        case_id,
        runtime.repository,
        VirtualInstrument(runtime.oracle),
        runtime.scorer,
        runtime.planner,
        action_log=headroom.NullLog(),
        budget=1,
    )
    observation = session.observation("CID20").public_dict(include_accession=False)
    initial_hash = hashlib.sha256(json.dumps(observation, sort_keys=True).encode()).hexdigest()
    rank_hash = hashlib.sha256(
        json.dumps(session.ranking().model_dump(), sort_keys=True).encode()
    ).hexdigest()
    plan = session.plan().model_dump() if policy == "separation" else None
    action = {"cid20_only": "STOP", "always_cid40": "CID40", "always_ead16": "EAD16"}.get(policy)
    if policy == "separation":
        action = plan["recommended"]["key"]
    if action not in {"STOP", "CID40", "EAD16"}:
        raise ValueError("unknown policy/action")
    if action != "STOP":
        session.measure(action)
    investigation = session.stop().model_dump()
    assert len(investigation["observed_actions"]) == 1 + int(action != "STOP")
    assert not investigation["intervention_history"]
    return {
        "investigation": investigation,
        "chosen_action": action,
        "initial_plan": plan,
        "initial_observation_hash": initial_hash,
        "initial_ranking_hash": rank_hash,
    }


def policy_rows(rows, policy):
    if policy != "random_expected_50_50":
        return [row["policies"][policy] for row in rows]
    return [
        {
            key: (row["policies"]["always_cid40"][key] + row["policies"]["always_ead16"][key]) / 2
            for key in (
                "top1_correct",
                "accepted_correct",
                "accepted",
                "accepted_error",
                "optional_scans",
            )
        }
        for row in rows
    ]


def risk_difference(a, b, groups, seed, resamples):
    keys = sorted(set(groups))
    totals = {group: np.zeros(4) for group in keys}
    for left, right, group in zip(a, b, groups):
        totals[group] += [
            left["accepted_error"],
            left["accepted"],
            right["accepted_error"],
            right["accepted"],
        ]
    values = np.array([totals[key] for key in keys])
    samples = np.random.default_rng(seed).integers(0, len(keys), size=(resamples, len(keys)))
    sums = values[samples].sum(axis=1)
    valid = (sums[:, 1] > 0) & (sums[:, 3] > 0)
    delta = sums[valid, 0] / sums[valid, 1] - sums[valid, 2] / sums[valid, 3]
    observed = values.sum(axis=0)
    point = (
        observed[0] / observed[1] - observed[2] / observed[3]
        if observed[1] and observed[3]
        else None
    )
    return {
        "difference": float(point) if point is not None else None,
        "ci95_valid_resamples": np.quantile(delta, [0.025, 0.975]).tolist() if len(delta) else None,
        "valid_resamples": int(valid.sum()),
        "undefined_resamples": int((~valid).sum()),
        "resampling_unit": "whole scaffold group",
        "note": "Risk is undefined for zero acceptances; interval conditions on both resampled denominators being nonzero.",
    }


def compare(a, b, groups, seed, resamples):
    if len(a) != len(b) or len(a) != len(groups) or not a:
        raise ValueError("paired methods must evaluate identical nonempty cohorts")
    result = {
        metric: quality.grouped_interval(
            [x[metric] - y[metric] for x, y in zip(a, b)], groups, seed, resamples
        )
        for metric in ("accepted_correct", "top1_correct", "accepted_error", "optional_scans")
    }
    result["selective_risk"] = risk_difference(a, b, groups, seed, resamples)
    return result


def analyze(rows, seed, resamples):
    result = {}
    all_policies = POLICIES + ("random_expected_50_50",)
    for cohort in ("ambiguous_primary", "all_complete_secondary"):
        selected = [row for row in rows if row["ambiguous"] or cohort == "all_complete_secondary"]
        result[cohort] = {}
        for track in TRACKS:
            methods, by_method = {}, {}
            for method in METHODS:
                subset = sorted(
                    [row for row in selected if row["track"] == track and row["method"] == method],
                    key=lambda row: row["case_id"],
                )
                by_method[method] = subset
                groups = [row["group"] for row in subset]
                planner_rows, fixed_rows = (
                    policy_rows(subset, "separation"),
                    policy_rows(subset, "always_cid40"),
                )
                methods[method] = {
                    "n": len(subset),
                    "policies": {
                        policy: headroom.summarize(policy_rows(subset, policy))
                        for policy in all_policies
                    },
                    "planner_actions": dict(Counter(row["chosen_action"] for row in planner_rows)),
                    "complementarity": {
                        metric: headroom.complementarity(subset, metric)
                        for metric in ("top1_correct", "accepted_correct")
                    },
                    "planner_vs_always_cid40": compare(
                        planner_rows, fixed_rows, groups, seed, resamples
                    ),
                }
            alternative, current = by_method[METHODS[1]], by_method[METHODS[0]]
            assert [row["case_id"] for row in alternative] == [row["case_id"] for row in current]
            groups = [row["group"] for row in current]
            result[cohort][track] = {
                "methods": methods,
                "method_difference_direction": "donor_agreement minus current_conditional; negative optional scans means savings",
                "method_differences": {
                    policy: compare(
                        policy_rows(alternative, policy),
                        policy_rows(current, policy),
                        groups,
                        seed,
                        resamples,
                    )
                    for policy in all_policies
                },
            }
    return result


def signed_interval(item):
    return f"{item['mean_difference']:+.4f} [{item['ci95'][0]:+.4f}, {item['ci95'][1]:+.4f}]"


def render_markdown(payload):
    primary = payload["cohorts"]["ambiguous_primary"]["native_predicted"]["method_differences"][
        "separation"
    ]
    lines = [
        "# End-to-end stage-one reference comparison",
        "",
        "**EXPLORATORY grouped cross-validated TRAINING estimate; not independent validation.**",
        "",
        "All branches use real CID20 followed by STOP or at most one real archived CID40/EAD16 measurement. "
        "Scorer, acceptance thresholds, planner, budgets, candidate sets and reliability proxy are fixed. "
        "Random is the exact 50:50 expected measured-branch outcome.",
        "",
        "## Primary contrast: planner on ambiguous cases with native predicted references",
        "",
        f"Accepted-correct rate difference (donor agreement minus current): {signed_interval(primary['accepted_correct'])}.",
        f"Accepted-error rate difference: {signed_interval(primary['accepted_error'])}.",
        f"Optional scans per case difference: {signed_interval(primary['optional_scans'])}.",
        "",
        "These are paired whole-scaffold bootstrap 95% intervals. More accepted-correct outcomes alone "
        "do not establish an acceptable error rate or a better adaptive policy.",
        "",
    ]
    for cohort, tracks in payload["cohorts"].items():
        lines += [f"## {cohort}", ""]
        for track, item in tracks.items():
            lines += [
                f"### {track}",
                "",
                "| Reference method | Policy | n | Top-1 | Accepted-correct | Accepted errors | Coverage | Selective risk | Optional scans total / mean | Total acquisitions mean |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
            for method, method_result in item["methods"].items():
                for policy, summary in method_result["policies"].items():
                    risk = (
                        "undefined"
                        if summary["selective_risk"] is None
                        else f"{summary['selective_risk']:.1%}"
                    )
                    lines.append(
                        f"| {method} | {policy} | {summary['n']} | {summary['top1_correct']:g} | "
                        f"{summary['accepted_correct']:g} | {summary['accepted_error']:g} | {summary['coverage']:.1%} | "
                        f"{risk} | {summary['optional_scans']:g} / {summary['mean_optional_scans']:.3f} | "
                        f"{summary['mean_total_acquisitions']:.3f} |"
                    )
            lines += [
                "",
                "Donor-agreement minus current; changes are per case except selective risk.",
                "",
                "| Policy | Accepted-correct Δ [95% CI] | Accepted-error Δ [95% CI] | Optional scans Δ [95% CI] | Risk Δ [valid-resample 95% CI] | Undefined risk resamples |",
                "|---|---|---|---|---|---:|",
            ]
            for policy, change in item["method_differences"].items():
                risk = change["selective_risk"]
                risk_text = (
                    "undefined" if risk["difference"] is None else f"{risk['difference']:+.4f}"
                )
                if risk["ci95_valid_resamples"]:
                    low, high = risk["ci95_valid_resamples"]
                    risk_text += f" [{low:+.4f}, {high:+.4f}]"
                lines.append(
                    f"| {policy} | {signed_interval(change['accepted_correct'])} | "
                    f"{signed_interval(change['accepted_error'])} | {signed_interval(change['optional_scans'])} | "
                    f"{risk_text} | {risk['undefined_resamples']} |"
                )
            lines.append("")
    lines += [
        "",
        "## Does adaptive selection help? Ambiguous-cohort diagnostic",
        "",
        "| Track | References | Planner actions | CID40-only / EAD16-only / both accepted-correct | Best measurement accepted-correct ceiling | Planner-minus-always-CID40 accepted-correct [95% CI] | Planner-minus-always-CID40 scans [95% CI] |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for track, item in payload["cohorts"]["ambiguous_primary"].items():
        for method, method_result in item["methods"].items():
            diagnostic = method_result["complementarity"]["accepted_correct"]
            counts = diagnostic["counts"]
            comparisons = method_result["planner_vs_always_cid40"]
            lines.append(
                f"| {track} | {method} | {json.dumps(method_result['planner_actions'], sort_keys=True)} | "
                f"{counts['cid40_only']} / {counts['ead16_only']} / {counts['both']} | "
                f"{diagnostic['hindsight_best_measurement_count']} | {signed_interval(comparisons['accepted_correct'])} | "
                f"{signed_interval(comparisons['optional_scans'])} |"
            )
    lines += [
        "",
        "Hindsight ceilings and exclusive-success subsets use truth and are diagnostic only. "
        "Top-1 complementarity, full outcomes, selective-risk contrasts and donor provenance are in JSON.",
        "",
        "## Interpretation limits",
        "",
    ]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines += ["", "Reproduce: `make stage1-reference` after dependency installation.", ""]
    return "\n".join(lines)


def run():
    input_hashes = {path: quality.sha256(ROOT / path) for path in INPUT_PATHS}
    config, policy = load_config("multims2"), load_config("policies")
    seed, resamples = (
        int(config.get_path("evaluation.seed")),
        int(config.get_path("evaluation.bootstrap_resamples")),
    )
    metadata, train, records, targets = quality.load_inputs()
    saved_quality = json.loads(
        (ROOT / "reports/spectrapilot/train_reference_quality.json").read_text()
    )
    folds = _split_groups(train, seed, {f"fold{i}": 0.2 for i in range(5)})
    assert folds == saved_quality["fold_assignment"]
    for path, digest in saved_quality["input_sha256"].items():
        assert quality.sha256(ROOT / path) == digest
    extra = pd.read_parquet(
        CURATED / "candidate_universe.parquet",
        columns=["compound_full_inchikey", "name", "formula", "exact_mass", "adduct"],
    )
    metadata = metadata.merge(extra, on="compound_full_inchikey", validate="one_to_one")
    cases = pd.read_parquet(CURATED / "cases.parquet", filters=[("split", "==", "train")])
    predictor = quality.Predictor(metadata, train, records, folds, config)
    oracle_payload = {}
    for target in targets:
        observations = {}
        for action in quality.ACTIONS:
            record = predictor.records[(target["true_id"], action)]
            observations[action] = {
                "action": action,
                "fragmentation": "EAD" if action.startswith("EAD") else "CID",
                "energy_ev": int(action[3:]),
                "accession": record["record_id"],
                "peaks_mz": record["mz"].tolist(),
                "peaks_intensity": record["intensity"].tolist(),
            }
        oracle_payload[target["case_id"]] = {
            "initial": observations.pop("CID20"),
            "hidden": observations,
        }
    PRIVATE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    oracle = OracleStore(oracle_payload, log_path=PRIVATE / "access.jsonl")
    scorer, planner = create_components(config, policy)
    rows, anchor_audit = [], []
    observed_hashes = {}
    for fold in sorted(set(folds.values())):
        fold_targets = [target for target in targets if folds[target["true_id"]] == fold]
        needed = {candidate for target in fold_targets for candidate in target["candidate_ids"]}
        fold_cases = cases[cases.case_id.isin({target["case_id"] for target in fold_targets})]
        for track in TRACKS:
            anchor_sets = []
            for method in METHODS:
                references, anchors = make_references(
                    metadata, predictor, fold, needed, method, track
                )
                anchor_sets.append(anchors)
                anchor_audit.append(
                    {"fold": fold, "track": track, "method": method, "anchored_candidates": anchors}
                )
                runtime = SimpleNamespace(
                    repository=CaseRepository(fold_cases, references),
                    oracle=oracle,
                    scorer=scorer,
                    planner=planner,
                )
                for target in fold_targets:
                    raw = {name: run_branch(runtime, target["case_id"], name) for name in POLICIES}
                    assert len({branch["initial_ranking_hash"] for branch in raw.values()}) == 1
                    hashes = {branch["initial_observation_hash"] for branch in raw.values()}
                    assert len(hashes) == 1
                    observed_hashes.setdefault(target["case_id"], set()).update(hashes)
                    outcomes = {
                        name: headroom.score_outcome(branch, target["true_id"])
                        for name, branch in raw.items()
                    }
                    selected = {
                        "STOP": "cid20_only",
                        "CID40": "always_cid40",
                        "EAD16": "always_ead16",
                    }[outcomes["separation"]["chosen_action"]]
                    assert outcomes["separation"] == outcomes[selected]
                    rows.append(
                        {
                            "case_id": target["case_id"],
                            "true_id": target["true_id"],
                            "group": target["group"],
                            "fold": fold,
                            "split": "train",
                            "ambiguous": target["ambiguous"],
                            "n_candidates": len(target["candidate_ids"]),
                            "candidate_ids": target["candidate_ids"],
                            "method": method,
                            "track": track,
                            "initial_observation_sha256": next(iter(hashes)),
                            "policies": outcomes,
                            "planner_initial_plan": raw["separation"]["initial_plan"],
                        }
                    )
                print(
                    f"Completed {fold}: {track}, {method}, {len(fold_targets)} training cases",
                    flush=True,
                )
            assert anchor_sets[0] == anchor_sets[1]
    assert all(len(hashes) == 1 for hashes in observed_hashes.values())
    assert len(rows) == len(targets) * len(METHODS) * len(TRACKS)
    cohorts = analyze(rows, seed, resamples)
    donor_audit = [
        {
            "fold": fold,
            "candidate_id": candidate,
            "action": action,
            "donor_ids": prediction["donor_ids"],
        }
        for (fold, candidate, action), prediction in sorted(predictor.cache.items())
    ]
    assert input_hashes == {path: quality.sha256(ROOT / path) for path in INPUT_PATHS}
    payload = {
        "study": "End-to-end stage-one OOF training reference comparison",
        "label": "EXPLORATORY grouped cross-validated TRAINING estimate, not independent validation",
        "protocol_commit": "90259d9",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(),
        "dependency_lock_sha256": quality.sha256(ROOT / "uv.lock")
        if (ROOT / "uv.lock").exists()
        else None,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "pyarrow", "scipy", "rdkit", "pydantic")
        },
        "input_sha256": input_hashes,
        "source_sha256": {
            path: quality.sha256(ROOT / path)
            for path in (
                "scripts/check_train_stage1_reference.py",
                "scripts/check_train_reference_quality.py",
                "scripts/check_modality_headroom.py",
                "docs/train_stage1_reference_protocol.md",
                "src/spectrapilot/planning/session.py",
                "src/spectrapilot/planning/separation.py",
                "src/spectrapilot/science/scoring.py",
                "src/spectrapilot/service.py",
            )
        },
        "fold_assignment": folds,
        "n_targets": len(targets),
        "n_ambiguous": sum(target["ambiguous"] for target in targets),
        "dataset_version": config.get_path("dataset.commit"),
        "inputs_unchanged": True,
        "identical_observations_across_methods_and_tracks": True,
        "donor_audit": donor_audit,
        "anchor_audit": anchor_audit,
        "cohorts": cohorts,
        "rows": rows,
        "limitations": [
            "Exploratory follow-up to training-CV reference findings; no independent validation or frozen-test claim.",
            "Primary cohort is 277 ambiguous training cases; all-complete results include precursor-unique cases and are secondary.",
            "Native track uses only predicted references; anchored track uses reserved measured CID60 references for training-library candidates only, with energy mismatch.",
            "The anchored track is identity-library-assisted, including held-out target CID60 when available; it is not unseen-compound prediction and does not reproduce full production reference coverage.",
            "All query spectra and predictor donors are train-only; non-training candidate structures/masses remain in original candidate sets, but their measured spectra are not read.",
            "Reference intensity aggregation is the only changed scoring input. Original reliability proxy, scorer, planner and uncalibrated acceptance thresholds are fixed.",
            "Risk is errors/accepted; random risk is a ratio of expected counts. Bootstrap risk intervals condition on nonzero acceptance denominators; undefined resamples are disclosed.",
            "Higher coverage can increase accepted errors; neither a correct-count gain nor an interval overlapping zero proves safety or non-inferiority.",
            "No fitted selector, calibration model, production reference update, MCP or UI work.",
            "Original MultiMS2 split is connectivity-grouped despite its label; this study reuses genuinely scaffold-held-out training folds without rewriting that split.",
        ],
    }
    (OUTPUT / "train_stage1_reference.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUTPUT / "train_stage1_reference.md").write_text(render_markdown(payload))
    print(
        json.dumps(
            {
                track: {
                    method: result["policies"]["separation"]
                    for method, result in item["methods"].items()
                }
                for track, item in cohorts["ambiguous_primary"].items()
            },
            indent=2,
        )
    )
    return payload


if __name__ == "__main__":
    run()

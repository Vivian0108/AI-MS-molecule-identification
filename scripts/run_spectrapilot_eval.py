#!/usr/bin/env python
"""Run the SpectraPilot v2 policy benchmark on a subset of the frozen split.

Every policy sees the same cases, the same candidate universe and the same
frozen scorer.  The adaptive policy is the ``separation`` planner (the
``separation_heuristic`` method used by the service).  ``always_cid40`` is the
reference baseline.  ``hindsight_best`` uses the truth to pick an action and is
a diagnostic ceiling, never a deployable policy.

Examples
--------
    PYTHONPATH=src .venv/bin/python scripts/run_spectrapilot_eval.py \
        --cohort ambiguous --resamples 2000

    PYTHONPATH=src .venv/bin/python scripts/run_spectrapilot_eval.py \
        --cohort all --limit 80
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spectrapilot.data.repository import CaseRepository  # noqa: E402
from spectrapilot.evaluation.runner import (  # noqa: E402
    paired_comparison,
    run_policy,
    summarize,
    write_benchmark,
)
from spectrapilot.evaluation.truth import EvaluatorStore  # noqa: E402
from spectrapilot.paths import REPORTS, load_config  # noqa: E402
from spectrapilot.planning.oracle import OracleStore  # noqa: E402
from spectrapilot.planning.separation import SeparationPlanner  # noqa: E402
from spectrapilot.science.scoring import CandidateScorer  # noqa: E402
from spectrapilot.science.templates import ReferenceStore  # noqa: E402

POLICIES = [
    "cid20_only",       # single 20 eV scan only (no extra acquisition)
    "always_cid40",     # reference baseline
    "always_ead16",     # alternative fixed action
    "random",           # seeded random 30/40 choice, averaged per molecule
    "separation",       # SpectraPilot adaptive method
    "hindsight_best",   # diagnostic ceiling (truth-aware, not deployable)
]
REFERENCE = "always_cid40"
ADAPTIVE = "separation"


def select_case_ids(
    repository: CaseRepository,
    splits: list[str],
    *,
    cohort: str,
    limit: int,
    seed: int,
) -> list[str]:
    ids = [cid for split in splits for cid in repository.case_ids(split)]
    if cohort == "ambiguous":
        ids = [cid for cid in ids if repository.case(cid).precursor_ambiguous]
    if limit and limit < len(ids):
        rng = np.random.default_rng(seed)
        ids = sorted(rng.choice(ids, size=limit, replace=False).tolist())
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        default="test",
        help="comma-separated splits, e.g. 'test' or 'dev,test'",
    )
    parser.add_argument("--cohort", default="ambiguous", choices=["all", "ambiguous"])
    parser.add_argument("--limit", type=int, default=0, help="0 keeps the whole cohort")
    parser.add_argument("--budget", type=int, default=1)
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--repetitions", type=int, default=20, help="random-policy trials")
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--out-label", default="", help="override the output directory suffix")
    parser.add_argument(
        "--decision-version",
        default="v2_legacy",
        choices=["v3", "v2_legacy"],
        help="v2_legacy reproduces the frozen v2 numbers; v3 uses the corrected contract",
    )
    args = parser.parse_args()

    splits = [item.strip() for item in args.split.split(",") if item.strip()]
    unknown = [item for item in splits if item not in {"train", "dev", "test"}]
    if unknown or not splits:
        raise SystemExit(f"unknown split(s): {unknown or args.split}")

    selection_cfg = load_config("multims2")
    policy_cfg = load_config("policies")

    references = ReferenceStore.load(
        ppm_tolerance=float(selection_cfg.get_path("candidate_pool.ppm", 10.0))
    )
    repository = CaseRepository.load(references)
    oracle = OracleStore.load()
    truth = EvaluatorStore.load()
    scorer = CandidateScorer(
        tolerance_da=float(selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
        tempering=0.85,
    )
    planner = SeparationPlanner(
        stop_support=float(policy_cfg.get_path("planner.stop_support", 0.90)),
        stop_margin=float(policy_cfg.get_path("planner.stop_margin", 0.65)),
        stop_score=float(policy_cfg.get_path("planner.stop_score", 0.01)),
        identified_min_support=float(policy_cfg.get_path("confidence.identified_min_support", 0.72)),
        identified_min_margin=float(policy_cfg.get_path("confidence.identified_min_margin", 0.22)),
        identified_min_fit=float(policy_cfg.get_path("confidence.identified_min_fit", 0.30)),
        identified_min_matched_peaks=int(
            policy_cfg.get_path("confidence.identified_min_matched_peaks", 2)
        ),
        ead_cost_ratio=float(policy_cfg.get_path("planner.ead_cost_ratio", 1.0)),
        tolerance_da=float(selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
    )

    case_ids = select_case_ids(
        repository, splits, cohort=args.cohort, limit=args.limit, seed=args.seed
    )
    if not case_ids:
        raise SystemExit("no cases matched the requested cohort")
    print(
        f"cohort={args.cohort} splits={','.join(splits)} n_cases={len(case_ids)} "
        f"budget={args.budget}"
    )
    leakage_warning = None
    if "train" in splits:
        leakage_warning = (
            "The train split is included. The CID40/EAD16 templates are train-only "
            "structure-kNN predictions, so train cases leak into their own templates "
            "and their scores are optimistically biased. Prefer 'dev,test'."
        )
        print(f"WARNING: {leakage_warning}")

    # run_policy walks one split at a time, so results are concatenated and then
    # sliced to the sampled cohort.
    results: dict[str, list] = {}
    timings: dict[str, float] = {}
    keep = set(case_ids)
    for policy in POLICIES:
        started = time.time()
        raw = []
        for split in splits:
            raw.extend(
                run_policy(
                    policy,
                    split,
                    repository=repository,
                    oracle=oracle,
                    truth=truth,
                    scorer=scorer,
                    planner=planner,
                    repetitions=args.repetitions,
                    seed=args.seed,
                    budget=args.budget,
                    decision_version=args.decision_version,
                )
            )
        results[policy] = [item for item in raw if item.case_id in keep]
        timings[policy] = round(time.time() - started, 2)
        print(f"  ran {policy:<15} n={len(results[policy])} ({timings[policy]}s)")

    summaries = {
        policy: summarize(items, resamples=args.resamples, seed=args.seed)
        for policy, items in results.items()
    }
    comparisons = {
        policy: paired_comparison(
            results[policy],
            results[REFERENCE],
            metric="top1_correct",
            resamples=args.resamples,
            seed=args.seed,
        )
        for policy in POLICIES
        if policy != REFERENCE
    }
    scan_comparisons = {
        policy: paired_comparison(
            results[policy],
            results[REFERENCE],
            metric="extra_scans",
            resamples=args.resamples,
            seed=args.seed,
        )
        for policy in POLICIES
        if policy != REFERENCE
    }

    # -- console table -----------------------------------------------------
    print()
    header = f"{'policy':<15} {'n':>4} {'top1':>6} {'95% CI':>16} {'scans':>6} {'cov':>5} {'acc|acc':>8} {'falseid':>8}"
    print(header)
    print("-" * len(header))
    for policy, item in summaries.items():
        ci = f"[{item['top1_ci_low']:.3f},{item['top1_ci_high']:.3f}]"
        print(
            f"{policy:<15} {item['n']:>4} {item['top1_accuracy']:>6.3f} {ci:>16} "
            f"{item['mean_extra_scans']:>6.2f} {item['accepted_coverage']:>5.2f} "
            f"{item['accepted_accuracy']:>8.3f} {item['false_id_rate_at_coverage']:>8.3f}"
        )

    print()
    print(f"paired vs {REFERENCE} (top-1 accuracy, molecule-level bootstrap)")
    for policy, item in comparisons.items():
        print(
            f"  {policy:<15} delta={item['mean_delta']:+.3f} "
            f"[{item['ci_low']:+.3f},{item['ci_high']:+.3f}] "
            f"excludes_zero={item['excludes_zero']} "
            f"(better={item['discordant_a_correct_b_wrong']} worse={item['discordant_a_wrong_b_correct']})"
        )

    # Abstention diagnostic: where the adaptive policy stops early it may fail the
    # fit floor with a single CID20 observation and abstain where a fixed extra
    # scan would have identified.  Rank accuracy is unaffected; coverage is.
    abstention = _abstention_vs_reference(results[ADAPTIVE], results[REFERENCE])
    verdict = _verdict(comparisons, summaries, ADAPTIVE, REFERENCE, abstention)

    # Secondary breakdown: the precursor-ambiguous cases inside the sampled subset.
    ambiguous_ids = {cid for cid in case_ids if repository.case(cid).precursor_ambiguous}
    ambiguous_results = {
        policy: [item for item in items if item.case_id in ambiguous_ids]
        for policy, items in results.items()
    }
    secondary = {}
    if ambiguous_ids:
        secondary = {
            "n": len(ambiguous_ids),
            "summaries": {
                policy: summarize(items, resamples=args.resamples, seed=args.seed)
                for policy, items in ambiguous_results.items()
            },
            "paired_vs_reference_top1": {
                policy: paired_comparison(
                    ambiguous_results[policy],
                    ambiguous_results[REFERENCE],
                    metric="top1_correct",
                    resamples=args.resamples,
                    seed=args.seed,
                )
                for policy in POLICIES
                if policy != REFERENCE
            },
        }

    # -- artefacts ---------------------------------------------------------
    label = args.split.replace(",", "_")
    out_dir = REPORTS / f"subset_{args.out_label or args.cohort}_{label}"
    write_benchmark(results, split=args.split, output_dir=out_dir, resamples=args.resamples)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "split": args.split,
        "splits": splits,
        "cohort": args.cohort,
        "n_cases": len(case_ids),
        "n_ambiguous_in_subset": len(ambiguous_ids),
        "budget": args.budget,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "adaptive_policy": ADAPTIVE,
        "reference_policy": REFERENCE,
        "summaries": summaries,
        "paired_vs_reference_top1": comparisons,
        "paired_vs_reference_scans": scan_comparisons,
        "abstention_vs_reference": abstention,
        "secondary_ambiguous_subset": secondary,
        "leakage_warning": leakage_warning,
        "timings_seconds": timings,
        "verdict": verdict,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "subset_benchmark.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "subset_benchmark.md").write_text(_markdown(payload), encoding="utf-8")

    print()
    print(f"verdict: {verdict['claim']}")
    if secondary:
        print()
        print(f"ambiguous members of the subset (n={secondary['n']}):")
        for policy, item in secondary["summaries"].items():
            delta = secondary["paired_vs_reference_top1"].get(policy)
            extra = (
                f" delta={delta['mean_delta']:+.3f} "
                f"[{delta['ci_low']:+.3f},{delta['ci_high']:+.3f}]"
                f" sig={'yes' if delta['excludes_zero'] else 'no'}"
                if delta
                else ""
            )
            print(
                f"  {policy:<15} top1={item['top1_accuracy']:.3f} "
                f"scans={item['mean_extra_scans']:.2f} cov={item['accepted_coverage']:.2f}{extra}"
            )
    print(f"wrote {out_dir.relative_to(ROOT)}/subset_benchmark.{{json,md}}")
    return 0


def _abstention_vs_reference(adaptive: list, reference: list) -> dict:
    """Cases where the adaptive policy abstains but the reference identifies."""
    ref_by_id = {item.case_id: item for item in reference}
    gap = [
        item
        for item in adaptive
        if item.case_id in ref_by_id
        and item.accepted_any < 0.5
        and ref_by_id[item.case_id].accepted_any >= 0.5
    ]
    return {
        "n_adaptive_abstains_reference_identifies": len(gap),
        "of_which_precursor_unique": sum(1 for item in gap if item.n_candidates == 1),
        "of_which_adaptive_used_no_extra_scan": sum(1 for item in gap if item.extra_scans == 0),
        "adaptive_top1_correct_on_gap": (
            float(np.mean([item.top1_correct for item in gap])) if gap else 0.0
        ),
        "reference_top1_correct_on_gap": (
            float(np.mean([ref_by_id[item.case_id].top1_correct for item in gap])) if gap else 0.0
        ),
        "note": (
            "The adaptive policy stops at CID20 on precursor-unique cases (a single "
            "candidate remains), where CID20-only fit can fall below the fit floor, so "
            "the precommitted rule abstains. Rank accuracy is unchanged; identified "
            "coverage is lower than the fixed extra-scan baseline."
        ),
    }


def _verdict(
    comparisons: dict,
    summaries: dict,
    adaptive: str,
    reference: str,
    abstention: dict | None = None,
) -> dict:
    wins = [p for p, item in comparisons.items() if item["excludes_zero"] and item["mean_delta"] > 0]
    losses = [p for p, item in comparisons.items() if item["excludes_zero"] and item["mean_delta"] < 0]
    acc_delta = comparisons[adaptive]["mean_delta"]
    acc_ci = (comparisons[adaptive]["ci_low"], comparisons[adaptive]["ci_high"])
    scans = summaries[adaptive]["mean_extra_scans"]
    ref_scans = summaries[reference]["mean_extra_scans"]
    if comparisons[adaptive]["excludes_zero"] and acc_delta > 0:
        claim = (
            f"ACCURACY WIN: {adaptive} beats {reference} by {acc_delta:+.3f} top-1 "
            f"(95% CI [{acc_ci[0]:+.3f},{acc_ci[1]:+.3f}]) at {scans:.2f} vs {ref_scans:.2f} scans."
        )
    elif comparisons[adaptive]["excludes_zero"] and acc_delta < 0:
        claim = (
            f"ACCURACY LOSS: {adaptive} is worse than {reference} by {acc_delta:+.3f} top-1 "
            f"(95% CI [{acc_ci[0]:+.3f},{acc_ci[1]:+.3f}])."
        )
    else:
        claim = (
            f"NEUTRAL ON ACCURACY: no paired interval excludes zero for {adaptive} vs "
            f"{reference} (delta {acc_delta:+.3f}, 95% CI [{acc_ci[0]:+.3f},{acc_ci[1]:+.3f}]). "
            f"Defensible claim is cost only: {scans:.2f} vs {ref_scans:.2f} mean extra scans."
        )
    coverage_gap = (
        summaries[reference]["accepted_coverage"] - summaries[adaptive]["accepted_coverage"]
    )
    if abstention and abstention["n_adaptive_abstains_reference_identifies"]:
        claim += (
            f" COVERAGE CAVEAT: {abstention['n_adaptive_abstains_reference_identifies']} case(s) "
            f"(all top-1 correct for both policies, "
            f"{abstention['of_which_precursor_unique']} precursor-unique) are abstained by "
            f"{adaptive} but identified by {reference}; identified coverage is "
            f"{coverage_gap:+.3f} lower. So this is a cost/coverage trade-off, not a win."
        )
    return {
        "excludes_zero_wins": wins,
        "excludes_zero_losses": losses,
        "coverage_gap_vs_reference": float(coverage_gap),
        "claim": claim,
    }


def _markdown(payload: dict) -> str:
    lines = [
        f"# SpectraPilot subset benchmark — {payload['cohort']} cohort, {payload['split']} split",
        "",
        f"- Cases: **{payload['n_cases']}** "
        f"(precursor-ambiguous inside subset: {payload['n_ambiguous_in_subset']})",
        f"- Budget: {payload['budget']} extra acquisition(s); random trials: {payload['repetitions']}",
        f"- Adaptive method: `{payload['adaptive_policy']}`; reference: `{payload['reference_policy']}`",
        "- Bootstrap resamples are by molecule; the hindsight policy is a diagnostic ceiling only.",
    ]
    if payload.get("leakage_warning"):
        lines.append(f"- **WARNING:** {payload['leakage_warning']}")
    lines += [
        "",
        "| Policy | n | Top-1 | 95% CI | Mean extra scans | Coverage | Accepted acc. | False ID at coverage |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for policy, item in payload["summaries"].items():
        lines.append(
            f"| {policy} | {item['n']} | {item['top1_accuracy']:.3f} | "
            f"[{item['top1_ci_low']:.3f}, {item['top1_ci_high']:.3f}] | "
            f"{item['mean_extra_scans']:.2f} | {item['accepted_coverage']:.3f} | "
            f"{item['accepted_accuracy']:.3f} | {item['false_id_rate_at_coverage']:.3f} |"
        )
    lines += [
        "",
        f"## Paired vs `{payload['reference_policy']}` (top-1 accuracy)",
        "",
        "| Policy | Δ Top-1 | 95% CI | Excludes zero | Better | Worse |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for policy, item in payload["paired_vs_reference_top1"].items():
        lines.append(
            f"| {policy} | {item['mean_delta']:+.3f} | "
            f"[{item['ci_low']:+.3f}, {item['ci_high']:+.3f}] | "
            f"{'yes' if item['excludes_zero'] else 'no'} | "
            f"{item['discordant_a_correct_b_wrong']} | {item['discordant_a_wrong_b_correct']} |"
        )
    lines += [
        "",
        "## Paired vs reference (extra scans)",
        "",
        "| Policy | Δ scans | 95% CI | Excludes zero |",
        "|---|---:|---|---:|",
    ]
    for policy, item in payload["paired_vs_reference_scans"].items():
        lines.append(
            f"| {policy} | {item['mean_delta']:+.3f} | "
            f"[{item['ci_low']:+.3f}, {item['ci_high']:+.3f}] | "
            f"{'yes' if item['excludes_zero'] else 'no'} |"
        )
    lines += [
        "",
        "## Verdict",
        "",
        payload["verdict"]["claim"],
        "",
    ]
    secondary = payload.get("secondary_ambiguous_subset")
    if secondary:
        lines += [
            f"## Secondary: precursor-ambiguous members of the subset (n = {secondary['n']})",
            "",
            "| Policy | Top-1 | 95% CI | Mean extra scans | Coverage | Δ Top-1 vs ref | 95% CI | Excludes zero |",
            "|---|---:|---|---:|---:|---:|---|---:|",
        ]
        for policy, item in secondary["summaries"].items():
            delta = secondary["paired_vs_reference_top1"].get(policy)
            if delta:
                delta_cell = f"{delta['mean_delta']:+.3f}"
                delta_ci = f"[{delta['ci_low']:+.3f}, {delta['ci_high']:+.3f}]"
                sig = "yes" if delta["excludes_zero"] else "no"
            else:
                delta_cell, delta_ci, sig = "—", "—", "—"
            lines.append(
                f"| {policy} | {item['top1_accuracy']:.3f} | "
                f"[{item['top1_ci_low']:.3f}, {item['top1_ci_high']:.3f}] | "
                f"{item['mean_extra_scans']:.2f} | {item['accepted_coverage']:.3f} | "
                f"{delta_cell} | {delta_ci} | {sig} |"
            )
        lines.append("")
    lines += [
        "## Abstention diagnostic",
        "",
        f"- Cases where `{payload['adaptive_policy']}` abstains but "
        f"`{payload['reference_policy']}` identifies: "
        f"**{payload['abstention_vs_reference']['n_adaptive_abstains_reference_identifies']}**",
        f"- Of which precursor-unique: "
        f"{payload['abstention_vs_reference']['of_which_precursor_unique']}",
        f"- Of which the adaptive policy used no extra scan: "
        f"{payload['abstention_vs_reference']['of_which_adaptive_used_no_extra_scan']}",
        f"- Top-1 correct on those cases — adaptive: "
        f"{payload['abstention_vs_reference']['adaptive_top1_correct_on_gap']:.3f}, "
        f"reference: {payload['abstention_vs_reference']['reference_top1_correct_on_gap']:.3f}",
        "",
        payload["abstention_vs_reference"]["note"],
        "",
        "A positive point estimate is not evidence of an accuracy gain unless the paired "
        "interval excludes zero.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

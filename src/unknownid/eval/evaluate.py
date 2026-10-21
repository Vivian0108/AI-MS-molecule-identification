"""Held-out evaluation of acquisition policies with molecule-level uncertainty."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from unknownid.core.evidence import EvidenceEvaluator
from unknownid.core.posterior import entropy, top2_margin
from unknownid.core.retrieve import ReferenceStore
from unknownid.eval.baselines import (
    EvalCase,
    FixedEnergy,
    OracleBestAction,
    Policy,
    PolicyState,
    RandomPolicy,
    SingleScan,
    UnknownIDPolicy,
    default_policies,
)
from unknownid.eval.bootstrap import bootstrap_mean_ci, paired_bootstrap_difference
from unknownid.eval.metrics import abstention_summary, decide, reciprocal_rank, top1, topk
from unknownid.planner.acquisition import AcquisitionPlanner
from unknownid.planner.error_model import ErrorModel
from unknownid.paths import CALIBRATION_JSON, EVALUATION_MD, REPORTS

BUDGET_EVAL = 2  # evaluation curve only; the API default budget is 1


@dataclass
class CaseRun:
    case_id: str
    n_candidates: int
    metrics: dict


def _case_metrics(
    state: PolicyState,
    truth: str,
    *,
    budget: int,
    confidence: dict,
) -> dict:
    stage0 = state.stage(0)
    stage1 = state.stage(1)
    stage2 = state.stage(min(budget, 2))
    final = state.stage(budget)
    order_final = final.order()
    decision = decide(
        final.weights,
        final.evidence,
        min_support=confidence["min_support"],
        min_margin=confidence["min_margin"],
        min_similarity=confidence["min_similarity"],
        min_matched=confidence["min_matched"],
    )
    return {
        "top1_0": top1(stage0.order(), truth),
        "top1_1": top1(stage1.order(), truth),
        "top1_2": top1(stage2.order(), truth),
        "mrr_2": reciprocal_rank(order_final, truth),
        "top3_2": topk(order_final, truth, 3),
        "scans": len(final.actions),
        "scans_1": min(1, len(final.actions)),
        "scans_2": min(2, len(final.actions)),
        "identified": float(decision.decision == "identified"),
        "accepted_correct": float(decision.decision == "identified" and decision.top_candidate == truth),
        "accepted_error": float(decision.decision == "identified" and decision.top_candidate != truth),
        "coverage": float(decision.decision == "identified"),
        "out_of_library": float(decision.decision == "out_of_library"),
        "ambiguous": float(decision.decision == "ambiguous"),
        "support": float(decision.support),
        "margin": float(decision.margin),
        "best_similarity": float(decision.best_similarity),
        "entropy_0": float(stage0.entropy),
        "entropy_final": float(final.entropy),
        "entropy_reduction": float(max(stage0.entropy - final.entropy, 0.0)),
        "decision": decision.decision,
        "predicted": decision.top_candidate,
        "reasons": decision.reasons,
        "order": order_final,
    }


def run_policy_once(
    case: EvalCase,
    policy: Policy,
    *,
    references: ReferenceStore,
    evaluator: EvidenceEvaluator,
    error_model: ErrorModel,
    budget: int,
    confidence: dict,
    tempering: float,
    rng: np.random.Generator | None = None,
) -> tuple[dict, float]:
    state = PolicyState(
        case,
        references=references,
        evaluator=evaluator,
        error_model=error_model,
        tempering=tempering,
    )
    started = time.perf_counter()
    policy.run(state, budget=budget, rng=rng)
    runtime = time.perf_counter() - started
    return _case_metrics(state, case.molecule_id, budget=budget, confidence=confidence), runtime


NUMERIC_KEYS = [
    "top1_0",
    "top1_1",
    "top1_2",
    "mrr_2",
    "top3_2",
    "scans",
    "scans_1",
    "scans_2",
    "identified",
    "accepted_correct",
    "accepted_error",
    "coverage",
    "out_of_library",
    "ambiguous",
    "support",
    "margin",
    "best_similarity",
    "entropy_0",
    "entropy_final",
    "entropy_reduction",
    "runtime_s",
]


def run_policy_suite(
    cases: Sequence[EvalCase],
    *,
    policies: Sequence[Policy],
    references: ReferenceStore,
    evaluator: EvidenceEvaluator,
    error_model: ErrorModel,
    planner: AcquisitionPlanner,
    budget: int,
    confidence: dict,
    tempering: float,
    random_trials: int = 20,
    random_seed: int = 20261020,
) -> dict[str, dict[str, dict]]:
    results: dict[str, dict[str, dict]] = {policy.name: {} for policy in policies}
    for case in cases:
        for policy in policies:
            if policy.name == "random":
                trials = []
                runtimes = []
                for trial in range(random_trials):
                    digest = hashlib.sha256(
                        f"{random_seed}|{case.case_id}|{trial}".encode()
                    ).digest()
                    seed = int.from_bytes(digest[:4], "big")
                    rng = np.random.default_rng(seed)
                    metrics, runtime = run_policy_once(
                        case,
                        policy,
                        references=references,
                        evaluator=evaluator,
                        error_model=error_model,
                        budget=budget,
                        confidence=confidence,
                        tempering=tempering,
                        rng=rng,
                    )
                    trials.append(metrics)
                    runtimes.append(runtime)
                averaged = {
                    key: float(np.mean([trial[key] for trial in trials]))
                    for key in NUMERIC_KEYS
                    if key in trials[0]
                }
                averaged["runtime_s"] = float(np.mean(runtimes))
                averaged["decision"] = "mixed"
                averaged["reasons"] = []
                averaged["order"] = []
                averaged["predicted"] = None
                results[policy.name][case.case_id] = {
                    "n_candidates": case.n_candidates,
                    **averaged,
                }
            else:
                if policy.name == "oracle_best_action":
                    policy = OracleBestAction(case.molecule_id)
                metrics, runtime = run_policy_once(
                    case,
                    policy,
                    references=references,
                    evaluator=evaluator,
                    error_model=error_model,
                    budget=budget,
                    confidence=confidence,
                    tempering=tempering,
                )
                metrics["runtime_s"] = runtime
                results[policy.name][case.case_id] = {
                    "n_candidates": case.n_candidates,
                    **metrics,
                }
    return results


def subset_ids(
    results: Mapping[str, Mapping[str, dict]],
    cases: Sequence[EvalCase],
    subset: str,
) -> list[str]:
    by_case = {case.case_id: case for case in cases}
    if subset == "all":
        return [case.case_id for case in cases]
    if subset == "ambiguous":
        return [case.case_id for case in cases if case.n_candidates >= 2]
    if subset == "easy":
        return [case.case_id for case in cases if case.n_candidates == 1]
    if subset == "close_call":
        # Initial top-2 support margin is policy-independent; use single_scan.
        reference = results.get("single_scan", {})
        return [
            case_id
            for case_id, metrics in reference.items()
            if metrics["n_candidates"] >= 2 and metrics["margin"] <= 0.15
        ]
    return [case.case_id for case in cases]


def summarize_policy(
    per_case: Mapping[str, dict],
    case_ids: Sequence[str],
    *,
    seed: int,
) -> dict:
    ids = [case_id for case_id in case_ids if case_id in per_case]
    if not ids:
        return {"n": 0}
    def values(key):
        return [per_case[case_id][key] for case_id in ids]
    summary: dict = {"n": len(ids)}
    for key in ("top1_0", "top1_1", "top1_2", "mrr_2", "top3_2", "scans", "scans_1", "scans_2"):
        mean, low, high = bootstrap_mean_ci(values(key), seed=seed)
        summary[key] = round(mean, 4)
        summary[f"{key}_ci"] = [round(low, 4), round(high, 4)]
    summary["coverage"] = round(float(np.mean(values("coverage"))), 4)
    summary["out_of_library_rate"] = round(float(np.mean(values("out_of_library"))), 4)
    summary["ambiguous_rate"] = round(float(np.mean(values("ambiguous"))), 4)
    identified = float(np.sum(values("identified")))
    accepted_errors = float(np.sum(values("accepted_error")))
    summary["identified_count"] = int(round(identified))
    summary["accepted_errors"] = int(round(accepted_errors))
    summary["risk"] = round(accepted_errors / identified, 4) if identified > 0 else None
    summary["precision_among_accepted"] = (
        round(1.0 - accepted_errors / identified, 4) if identified > 0 else None
    )
    summary["mean_entropy_reduction"] = round(float(np.mean(values("entropy_reduction"))), 4)
    summary["mean_runtime_s"] = round(float(np.mean(values("runtime_s"))), 4)
    summary["mean_support"] = round(float(np.mean(values("support"))), 4)
    return summary


def pairwise_comparisons(
    results: Mapping[str, Mapping[str, dict]],
    case_ids: Sequence[str],
    *,
    baseline: str = "unknownid",
    metrics: Sequence[str] = ("top1_1", "top1_2", "mrr_2"),
    seed: int = 20261020,
) -> dict:
    comparisons = {}
    reference = results.get(baseline, {})
    for policy_name, per_case in results.items():
        if policy_name == baseline:
            continue
        entry = {}
        for metric in metrics:
            first = {
                case_id: float(per_case[case_id][metric])
                for case_id in case_ids
                if case_id in per_case and case_id in reference
            }
            second = {
                case_id: float(reference[case_id][metric])
                for case_id in case_ids
                if case_id in per_case and case_id in reference
            }
            # Benefit: focal UnknownID minus comparison policy. Cost: savings.
            if metric.startswith("scans"):
                entry[metric] = paired_bootstrap_difference(first, second, seed=seed)
                entry[metric]["direction"] = "baseline minus UnknownID (optional scan savings)"
            else:
                entry[metric] = paired_bootstrap_difference(second, first, seed=seed)
                entry[metric]["direction"] = "UnknownID minus baseline"
            entry[metric]["differing_molecules"] = entry[metric]["wins"] + entry[metric]["losses"]
        comparisons[policy_name] = entry
    return comparisons


def entropy_validation(
    cases: Sequence[EvalCase],
    *,
    references: ReferenceStore,
    evaluator: EvidenceEvaluator,
    error_model: ErrorModel,
    planner: AcquisitionPlanner,
    confidence: dict,
    tempering: float,
    seed: int = 20261020,
) -> dict:
    """Compare predicted acquisition value with observed entropy reduction.

    Both 30 and 40 eV are revealed *for evaluation only*; the planner never sees
    them before choosing.  This is a validation diagnostic, not a policy.
    """
    rows = []
    for case in cases:
        state = PolicyState(
            case,
            references=references,
            evaluator=evaluator,
            error_model=error_model,
            tempering=tempering,
        )
        options = planner.rank_options(
            weights=state.weights,
            templates=case.templates,
            precursors={c.molecule_id: c.precursor_mz for c in case.candidates},
            energies=[30, 40],
        )
        predicted = {option.energy_ev: option for option in options}
        actual = {}
        for energy in (30, 40):
            trial = PolicyState(
                case,
                references=references,
                evaluator=evaluator,
                error_model=error_model,
                tempering=tempering,
            )
            trial.measure(energy)
            actual[energy] = max(trial.stage(0).entropy - trial.stage(1).entropy, 0.0)
        for energy in (30, 40):
            option = predicted.get(energy)
            if option is None:
                continue
            rows.append(
                {
                    "case_id": case.case_id,
                    "energy": energy,
                    "predicted": (
                        option.predicted_information_gain
                        if option.method == "monte_carlo_ig"
                        else option.score
                    ),
                    "actual_entropy_reduction": actual[energy],
                    "separation": option.separation,
                    "reliability": option.reliability,
                }
            )
    if len(rows) < 4:
        return {"n_pairs": len(rows), "spearman": None, "note": "insufficient pairs"}
    predicted = np.array([row["predicted"] for row in rows], float)
    actual = np.array([row["actual_entropy_reduction"] for row in rows], float)
    coefficient, pvalue = spearmanr(predicted, actual)
    # Regret of the planner's chosen energy against the best actual energy.
    by_case: dict[str, list[dict]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row)
    regrets = []
    for items in by_case.values():
        if len(items) < 2:
            continue
        chosen = max(items, key=lambda item: item["predicted"])
        best = max(item["actual_entropy_reduction"] for item in items)
        regrets.append(best - chosen["actual_entropy_reduction"])
    return {
        "n_pairs": len(rows),
        "spearman": float(coefficient) if coefficient is not None and np.isfinite(coefficient) else None,
        "pvalue": float(pvalue) if pvalue is not None and np.isfinite(pvalue) else None,
        "mean_regret": float(np.mean(regrets)) if regrets else None,
        "n_cases": len(regrets),
        "method": planner.method,
        "note": "Predicted values are acquisition scores; actual values are entropy reductions from revealing both real 30 and 40 eV spectra for evaluation only.",
    }


def failure_breakdown(
    cases: Sequence[EvalCase],
    results: Mapping[str, Mapping[str, dict]],
    references: ReferenceStore,
    *,
    policy: str = "unknownid",
    limit: int = 20,
) -> list[dict]:
    by_case = {case.case_id: case for case in cases}
    failures = []
    for case_id, metrics in results.get(policy, {}).items():
        if metrics.get("top1_2", 1.0) >= 1.0:
            continue
        case = by_case[case_id]
        top = metrics.get("predicted") or (metrics.get("order") or [None])[0]
        top_name = references.candidate(top).name if top and top in references.candidate_ids else top
        truth_name = references.candidate(case.molecule_id).name
        reasons = metrics.get("reasons") or []
        failures.append(
            {
                "case_id": case_id,
                "true_name": truth_name,
                "predicted_name": top_name,
                "n_candidates": case.n_candidates,
                "scans": metrics.get("scans"),
                "decision": metrics.get("decision"),
                "support": round(metrics.get("support", 0.0), 4),
                "margin": round(metrics.get("margin", 0.0), 4),
                "stereo_connectivity_ambiguity": any(
                    cid.split("-")[0] == case.molecule_id.split("-")[0] and cid != case.molecule_id
                    for cid in case.candidate_ids
                ),
                "reason": "; ".join(reasons) if reasons else "ranking error",
            }
        )
    return failures[:limit]


def _headline(
    summaries: Mapping[str, Mapping[str, dict]],
    comparisons: Mapping[str, Mapping[str, dict]],
    n_cases: Mapping[str, int],
) -> str:
    ambiguous = summaries.get("ambiguous", {})
    adaptive = ambiguous.get("unknownid", {})
    names = ("always_30", "always_40", "random", "cheap_disagreement", "single_scan")
    conclusive = []
    for baseline in names:
        entry = comparisons.get("ambiguous", {}).get(baseline, {})
        for metric in ("top1_1", "top1_2"):
            diff = entry.get(metric, {})
            low, high = diff.get("ci_low"), diff.get("ci_high")
            if low is None or high is None:
                continue
            if low > 0:
                conclusive.append(f"adaptive beats {baseline} on {metric} (diff {diff['mean_difference']:+.3f}, CI [{low:+.3f}, {high:+.3f}])")
            elif high < 0:
                conclusive.append(f"adaptive loses to {baseline} on {metric} (diff {diff['mean_difference']:+.3f}, CI [{low:+.3f}, {high:+.3f}])")
    scans_adaptive = adaptive.get("scans_1")
    scans_fixed = ambiguous.get("always_40", {}).get("scans_1")
    base = (
        f"Ambiguous test cohort: n={n_cases.get('ambiguous (>=2 precursor-consistent candidates)', 0)}. "
        f"Adaptive top-1@1={adaptive.get('top1_1')}; single-scan={ambiguous.get('single_scan', {}).get('top1_1')}; "
        f"always-40={ambiguous.get('always_40', {}).get('top1_1')}. "
        f"Adaptive used {scans_adaptive} scans on average by the first decision, versus {scans_fixed} for always-40."
    )
    if conclusive:
        return base + " Statistically conclusive paired differences: " + "; ".join(conclusive) + "."
    return (
        base
        + " No paired 95% confidence interval excludes zero for top-1 accuracy against fixed or random "
        "energy choice. The defensible finding is therefore a cost/efficiency result (equal accuracy with "
        "fewer acquisitions on this cohort), not an accuracy improvement. The test ambiguous subset is small, "
        "so this is a proof-of-concept and not a general claim."
    )


def build_report(
    *,
    summaries: Mapping[str, Mapping[str, dict]],
    comparisons: Mapping[str, dict],
    ig: Mapping[str, dict],
    failures: Sequence[dict],
    calibration: Mapping,
    config: Mapping,
    n_cases: Mapping[str, int],
    open_world: Mapping | None,
    generated_at: str,
) -> str:
    policy_order = [
        "precursor_only",
        "single_scan",
        "always_30",
        "always_40",
        "random",
        "cheap_disagreement",
        "unknownid",
        "oracle_best_action",
    ]
    lines = [
        "# UnknownID evaluation",
        "",
        f"*Generated {generated_at}.  Frozen split and policies; no test-set tuning.*",
        "",
        "## Claim tested",
        "",
        "For genuinely ambiguous, closed-world known-library cases, does an adaptive collision-energy "
        "choice improve identification per additional acquisition versus fixed and random-energy policies?",
        "",
        "## Frozen design",
        "",
        "- Test molecules only; no train/dev molecule appears in the test split.",
        "- Initial query: measured 20 eV spectrum. Reference library: 10/50 eV only. Hidden measurements: 30/40 eV.",
        "- Candidate universe: all precursor-consistent library molecules at 10 ppm, same `[M+H]+` adduct.",
        f"- Acquisition method selected on dev: `{calibration.get('method')}`.",
        f"- Default measurement budget in the API: {config.get('default_budget')}; the evaluation curve uses up to {config.get('budget_eval')} acquisitions.",
        "- Random policy averages 20 seeded trials per molecule.",
        "- Confidence intervals resample molecules, not spectra or energies.",
        "",
        "## Cohorts",
        "",
        "| Cohort | Cases |",
        "|---|---:|",
    ]
    for name, count in n_cases.items():
        lines.append(f"| {name} | {count} |")

    # Headline: only claim an accuracy difference if a paired 95% CI excludes zero.
    headline = _headline(summaries, comparisons, n_cases)
    lines += ["", "## Headline result", "", headline, ""]

    for cohort in ("all", "ambiguous", "close_call", "easy"):
        if cohort not in summaries:
            continue
        lines += [
            "",
            f"## Results — {cohort}",
            "",
            "| Policy | Top-1 @0 | Top-1 @1 | Top-1 @2 | MRR @2 | Top-3 @2 | Scans @1 | Scans @2 | Coverage | Risk |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for policy in policy_order:
            summary = summaries[cohort].get(policy)
            if not summary or not summary.get("n"):
                continue
            risk = "—" if summary.get("risk") is None else f"{summary['risk']:.3f}"
            lines.append(
                f"| {policy} | {summary['top1_0']:.3f} | {summary['top1_1']:.3f} | "
                f"{summary['top1_2']:.3f} | {summary['mrr_2']:.3f} | {summary['top3_2']:.3f} | "
                f"{summary['scans_1']:.2f} | {summary['scans_2']:.2f} | {summary['coverage']:.3f} | {risk} |"
            )

    lines += [
        "",
        "## Paired differences versus the UnknownID policy",
        "",
        "Positive values favour UnknownID; negative values favour the baseline.  "
        "CIs are 95% molecule-level paired bootstrap intervals.  An interval spanning zero "
        "is reported as inconclusive, not as a win.",
        "",
        "| Cohort | Baseline | Metric | Difference | 95% CI | Wins/Losses |",
        "|---|---|---|---:|---|---|",
    ]
    for cohort in ("all", "ambiguous"):
        if cohort not in comparisons:
            continue
        for policy, entry in comparisons[cohort].items():
            for metric, diff in entry.items():
                lines.append(
                    f"| {cohort} | {policy} | {metric} | {diff['mean_difference']:+.4f} | "
                    f"[{diff['ci_low']:+.4f}, {diff['ci_high']:+.4f}] | "
                    f"{diff['wins']}/{diff['losses']} |"
                )

    lines += [
        "",
        "## Information-gain validation (test split, diagnostic only)",
        "",
        f"- Method: `{ig.get('method')}`",
        f"- Pairwise predictions: {ig.get('n_pairs')} ({ig.get('n_cases')} molecules × 30/40 eV)",
        f"- Spearman correlation between predicted acquisition value and actual entropy reduction: "
        f"**{ig.get('spearman')}** (p={ig.get('pvalue')})",
        f"- Mean regret versus the best actual energy: **{ig.get('mean_regret')}**",
        "",
        "Both 30 and 40 eV spectra are revealed here only to validate the planner's prediction. "
        "The planner itself never reads them before choosing.",
        "",
        "## Calibration status",
        "",
        f"- Probabilities calibrated: **{config.get('calibrated_probabilities')}**",
        "- Reported candidate `weight` is relative support, not a probability of chemical identity.",
        "- No reliability diagram, ECE or Brier score is claimed because no probability calibration was validated.",
        "",
        "## Failure inspection (UnknownID, top-1 error after two scans)",
        "",
        "| Case | True | Predicted | Candidates | Scans | Decision | Margin | Failure mode |",
        "|---|---|---|---:|---:|---|---:|---|",
    ]
    if failures:
        for failure in failures:
            lines.append(
                f"| `{failure['case_id']}` | {failure['true_name']} | {failure['predicted_name']} | "
                f"{failure['n_candidates']} | {failure['scans']} | {failure['decision']} | "
                f"{failure['margin']:.3f} | {failure['reason']} |"
            )
    else:
        lines.append("| — | — | — | — | — | — | — | no top-1 failures in this cohort |")

    if open_world:
        attempted = [
            row for row in open_world.get("cases", []) if row.get("n_remaining", 0) > 0
        ]
        n_attempted = len(attempted)
        wrong_with_alternatives = sum(
            1 for row in attempted if row.get("decision_after_action") == "identified"
        )
        lines += [
            "",
            "## Open-world stress test",
            "",
            "The true molecule is removed from the candidate library before ranking.  "
            "A confident ``identified`` decision here is a false library match.",
            "",
            f"- Cases evaluated: {open_world.get('n')}",
            f"- Cases with at least one remaining candidate: {n_attempted}",
            f"- Out-of-library at 20 eV (all cases): {open_world.get('out_of_library_at_20_rate', 0):.3f}",
            f"- Out-of-library after optional measurement (all cases): "
            f"{open_world.get('out_of_library_after_action_rate', 0):.3f}",
            f"- Confident wrong library match (all cases): "
            f"{open_world.get('identified_wrong_library_match_rate', 0):.3f}"
            + (
                f"; among cases with alternatives: {wrong_with_alternatives}/{n_attempted}"
                if n_attempted
                else ""
            ),
            f"- Mean optional scans: {open_world.get('mean_scans', 0.0):.2f}",
            "",
            "The all-case rate is dominated by precursor-unique cases that are rejected without "
            "any spectrum comparison.  The cases with alternatives are the informative stress test; "
            "confident wrong matches there are the failure mode that matters.",
        ]

    lines += [
        "",
        "## What may and may not be claimed",
        "",
        "**Supported by this evaluation if the intervals above exclude zero:** "
        "on this homogeneous Bruker maXis Impact cohort, the selected policy changes identification "
        "per acquisition relative to the named baseline.",
        "",
        "**Not supported:** de novo structure elucidation, identification of compounds outside the "
        "reference library, cross-instrument generalization, enantiomer discrimination, clinical or "
        "regulatory validity, or automatic control of a real mass spectrometer.",
        "",
        "**Structural limitations:**",
        "- The true compound is in the candidate library by construction (closed world).",
        "- 20/30/40 eV templates are interpolations from 10/50 eV references; the query spectra are experimental.",
        "- Only two optional energies exist, so this is a 30-vs-40-or-stop decision, not general acquisition optimization.",
        f"- Accurate-mass filtering makes {n_cases.get('easy (precursor-unique)', 0) / max(n_cases.get('all test', 1), 1):.1%} of test cases precursor-unique; the ambiguous subset is the scientifically relevant one.",
        "- Test-split ambiguous cases are few, so confidence intervals are wide and a null result must be reported as such.",
        "",
        "## Reproducibility",
        "",
        "- Fixed split seed: `20261020`; random-policy trials: 20 per molecule.",
        "- Policies and thresholds were frozen before test evaluation; calibration used dev only.",
        "- `reports/evaluation.json` contains every per-case metric and comparison shown above.",
        "",
    ]
    return "\n".join(lines)

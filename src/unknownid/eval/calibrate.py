"""Dev-only selection of the acquisition method.

This is the only place where the planner implementation is chosen.  It must be
run before ``reports/evaluation.md`` is produced; the test split is not touched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from unknownid.core.evidence import EvidenceEvaluator
from unknownid.core.retrieve import ReferenceStore
from unknownid.eval.baselines import (
    EvalCase,
    FixedEnergy,
    SingleScan,
    UnknownIDPolicy,
)
from unknownid.eval.evaluate import (
    entropy_validation,
    run_policy_suite,
    subset_ids,
    summarize_policy,
)
from unknownid.paths import CALIBRATION_JSON, CALIBRATION_MD, REPORTS
from unknownid.planner.acquisition import AcquisitionPlanner, PlannerConfig
from unknownid.planner.error_model import ErrorModel


def calibrate(
    dev_cases: list[EvalCase],
    *,
    references: ReferenceStore,
    evaluator: EvidenceEvaluator,
    error_model: ErrorModel,
    planner_config: PlannerConfig,
    confidence: dict,
    random_seed: int = 20261020,
    random_trials: int = 5,
) -> dict:
    methods = ["monte_carlo_ig", "disagreement_heuristic"]
    summaries: dict[str, dict] = {}
    validation: dict[str, dict] = {}
    for method in methods:
        planner = AcquisitionPlanner(planner_config, method=method, error_model=error_model)
        policies = [SingleScan(), FixedEnergy(30), FixedEnergy(40), UnknownIDPolicy(planner)]
        results = run_policy_suite(
            dev_cases,
            policies=policies,
            references=references,
            evaluator=evaluator,
            error_model=error_model,
            planner=planner,
            budget=1,
            confidence=confidence,
            tempering=planner_config.tempering,
            random_trials=random_trials,
            random_seed=random_seed,
        )
        ambiguous = subset_ids(results, dev_cases, "ambiguous")
        summaries[method] = {
            policy: summarize_policy(per_case, ambiguous, seed=random_seed)
            for policy, per_case in results.items()
        }
        validation[method] = entropy_validation(
            dev_cases,
            references=references,
            evaluator=evaluator,
            error_model=error_model,
            planner=planner,
            confidence=confidence,
            tempering=planner_config.tempering,
            seed=random_seed,
        )

    mc = summaries["monte_carlo_ig"].get("unknownid", {})
    heuristic = summaries["disagreement_heuristic"].get("unknownid", {})
    single = summaries["monte_carlo_ig"].get("single_scan", {})
    mc_ig = validation["monte_carlo_ig"]
    n_ambiguous = mc.get("n", 0)

    calibrated = error_model.can_use_monte_carlo()
    spearman = mc_ig.get("spearman")
    mc_accuracy = mc.get("top1_1", 0.0)
    heuristic_accuracy = heuristic.get("top1_1", 0.0)
    single_accuracy = single.get("top1_1", 0.0)

    if not calibrated:
        method = "disagreement_heuristic"
        reason = "Error model did not meet calibration requirements on train; the labelled heuristic is used."
    elif n_ambiguous < 5:
        method = "disagreement_heuristic"
        reason = "Fewer than five dev ambiguous cases; the heuristic is the conservative default."
    elif spearman is None or spearman < 0.10:
        method = "disagreement_heuristic"
        reason = "Monte-Carlo IG did not positively rank actual entropy reduction on dev; heuristic selected."
    elif mc_accuracy < single_accuracy - 0.02:
        method = "disagreement_heuristic"
        reason = (
            "Monte-Carlo policy lost more than 0.02 top-1 accuracy versus no extra scan on dev."
        )
    elif mc_accuracy + 1e-12 < heuristic_accuracy:
        method = "disagreement_heuristic"
        reason = "Heuristic had higher dev top-1 accuracy than Monte-Carlo IG."
    else:
        method = "monte_carlo_ig"
        reason = "Error model calibrated, dev IG rank correlation positive, and no accuracy loss versus the heuristic."

    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "method": method,
        "use_monte_carlo_ig": method == "monte_carlo_ig",
        "reason": reason,
        "error_model_calibrated": calibrated,
        "n_dev_cases": len(dev_cases),
        "n_dev_ambiguous": n_ambiguous,
        "dev_summaries": summaries,
        "dev_ig_validation": validation,
        "policy_config": {
            "budget": planner_config.budget,
            "allowed_energies": list(planner_config.allowed_energies),
            "cost": planner_config.cost,
            "monte_carlo_samples": planner_config.monte_carlo_samples,
            "tempering": planner_config.tempering,
            "stop_ig_threshold": planner_config.stop_ig_threshold,
            "seed": planner_config.seed,
        },
        "error_model_kappa": {
            str(energy): error_model.by_energy[energy].kappa for energy in (20, 30, 40)
        },
        "error_model_reliability": {
            str(energy): error_model.by_energy[energy].mean_cosine for energy in (20, 30, 40)
        },
    }
    CALIBRATION_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(payload)
    return payload


def _write_markdown(payload: dict) -> None:
    lines = [
        "# Acquisition-method calibration (dev only)",
        "",
        f"*Generated {payload['created_at_utc']}. The test split was not used.*",
        "",
        f"**Selected method:** `{payload['method']}`",
        "",
        f"**Reason:** {payload['reason']}",
        "",
        f"- Dev cases: {payload['n_dev_cases']}; dev ambiguous cases: {payload['n_dev_ambiguous']}",
        f"- Error model calibrated: {payload['error_model_calibrated']}",
        "",
        "## Dev ambiguous-subset results",
        "",
        "| Method | Policy | Top-1 @1 | Scans | Coverage |",
        "|---|---|---:|---:|---:|",
    ]
    for method, policies in payload["dev_summaries"].items():
        for policy in ("single_scan", "always_30", "always_40", "unknownid"):
            summary = policies.get(policy, {})
            if not summary.get("n"):
                continue
            lines.append(
                f"| {method} | {policy} | {summary.get('top1_1', 0):.3f} | "
                f"{summary.get('scans', 0):.2f} | {summary.get('coverage', 0):.3f} |"
            )
    lines += [
        "",
        "## IG validation on dev",
        "",
        "| Method | Spearman(predicted, actual entropy reduction) | Pairs | Mean regret |",
        "|---|---:|---:|---:|",
    ]
    for method, result in payload["dev_ig_validation"].items():
        lines.append(
            f"| {method} | {result.get('spearman')} | {result.get('n_pairs')} | {result.get('mean_regret')} |"
        )
    lines += [
        "",
        "## Error model (fitted on train identities only)",
        "",
        "| Energy | kappa | Mean interpolation cosine |",
        "|---|---:|---:|",
    ]
    for energy in ("20", "30", "40"):
        lines.append(
            f"| {energy} eV | {payload['error_model_kappa'][energy]:.3f} | "
            f"{payload['error_model_reliability'][energy]:.3f} |"
        )
    lines += [
        "",
        "The heuristic is always labelled as a template-disagreement heuristic, never as calibrated "
        "information gain.  The Monte-Carlo method is selected only when its dev predictions positively "
        "rank actual entropy reduction.",
        "",
    ]
    REPORTS.mkdir(parents=True, exist_ok=True)
    CALIBRATION_MD.write_text("\n".join(lines), encoding="utf-8")

#!/usr/bin/env python
"""Evaluate every acquisition policy on the frozen test split."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unknownid.config import load_config
from unknownid.core.evidence import EvidenceEvaluator
from unknownid.core.retrieve import ReferenceStore
from unknownid.eval.artifacts import generation_metadata, render_report, write_pareto
from unknownid.eval.baselines import default_policies, load_eval_cases
from unknownid.eval.diagnostics import energy_stop_diagnostics
from unknownid.eval.evaluate import (
    BUDGET_EVAL,
    entropy_validation,
    failure_breakdown,
    pairwise_comparisons,
    run_policy_suite,
    subset_ids,
    summarize_policy,
)
from unknownid.eval.open_world import run_open_world
from unknownid.paths import (
    CALIBRATION_JSON,
    CURATED,
    EVALUATION_MD,
    LIBRARY_PARQUET,
    PUBLIC_CASES_PARQUET,
    REPORTS,
    existing_oracle_path,
)
from unknownid.planner.acquisition import AcquisitionPlanner, PlannerConfig
from unknownid.planner.error_model import ErrorModel


def main() -> int:
    if not CALIBRATION_JSON.exists():
        raise SystemExit("Missing data/curated/calibration.json. Run `make calibrate` first.")
    calibration = json.loads(CALIBRATION_JSON.read_text(encoding="utf-8"))
    selection_cfg = load_config("selection")
    acquisition_cfg = load_config("acquisition")

    references = ReferenceStore(
        pd.read_parquet(LIBRARY_PARQUET),
        reference_energies=tuple(selection_cfg.get_path("energies.reference", [10, 50])),
        tolerance_da=float(selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
        template_method=str(selection_cfg.get_path("templates.method", "linear")),
        ppm_tolerance=float(selection_cfg.get_path("filters.ppm_precursor", 10.0)),
    )
    references.assert_reference_only()
    error_model = ErrorModel.load(CURATED / "error_model.json")
    evaluator = EvidenceEvaluator(
        tolerance_da=float(selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
        kappa=float(acquisition_cfg.get_path("likelihood.kappa_default", 8.0)),
        neutral_loss_weight=float(acquisition_cfg.get_path("scoring.neutral_loss_weight", 0.05)),
        unmatched_penalty=float(acquisition_cfg.get_path("scoring.unmatched_penalty", 0.35)),
        min_matched_peaks=int(selection_cfg.get_path("filters.min_matched_peaks", 2)),
        prior_floor=float(acquisition_cfg.get_path("scoring.prior_floor", 0.0)),
    )
    planner_config = PlannerConfig(
        budget=int(acquisition_cfg.get_path("measurement_budget", 1)),
        allowed_energies=tuple(acquisition_cfg.get_path("allowed_energies", [30, 40])),
        cost=float(acquisition_cfg.get_path("cost_per_measurement", 1.0)),
        monte_carlo_samples=int(acquisition_cfg.get_path("monte_carlo.samples", 500)),
        seed=int(acquisition_cfg.get_path("monte_carlo.seed", 20261020)),
        tempering=float(acquisition_cfg.get_path("likelihood.likelihood_tempering", 0.85)),
        stop_ig_threshold=float(acquisition_cfg.get_path("confidence.stop_ig_threshold", 0.02)),
        identified_min_support=float(
            acquisition_cfg.get_path("confidence.identified_min_support", 0.72)
        ),
        identified_min_margin=float(
            acquisition_cfg.get_path("confidence.identified_min_margin", 0.22)
        ),
        stop_min_support=float(acquisition_cfg.get_path("confidence.stop_min_support", 0.90)),
        stop_min_margin=float(acquisition_cfg.get_path("confidence.stop_min_margin", 0.70)),
        tolerance_da=float(selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
        max_candidates=int(acquisition_cfg.get_path("monte_carlo.max_candidates", 12)),
    )
    planner = AcquisitionPlanner(
        planner_config, method=calibration["method"], error_model=error_model
    )
    confidence = {
        "min_support": float(acquisition_cfg.get_path("confidence.identified_min_support", 0.72)),
        "min_margin": float(acquisition_cfg.get_path("confidence.identified_min_margin", 0.22)),
        "min_similarity": float(
            acquisition_cfg.get_path("confidence.identified_min_similarity", 0.30)
        ),
        "min_matched": int(acquisition_cfg.get_path("confidence.min_matched_peaks", 2)),
    }

    test_cases = load_eval_cases(
        references=references,
        public_cases_path=PUBLIC_CASES_PARQUET,
        oracle_path=existing_oracle_path(),
        split="test",
    )
    print(f"==> evaluating {len(test_cases)} test cases with frozen method {planner.method}")

    # Dummy truth for the policy factory; OracleBestAction is rebuilt per case.
    policies = default_policies(planner, truth="")
    results = run_policy_suite(
        test_cases,
        policies=policies,
        references=references,
        evaluator=evaluator,
        error_model=error_model,
        planner=planner,
        budget=BUDGET_EVAL,
        confidence=confidence,
        tempering=planner_config.tempering,
        random_trials=20,
        random_seed=int(selection_cfg.get_path("splits.seed", 20261020)),
    )

    subsets = ("all", "ambiguous", "close_call", "easy")
    summaries = {
        subset: {
            policy: summarize_policy(
                per_case, subset_ids(results, test_cases, subset), seed=20261020
            )
            for policy, per_case in results.items()
        }
        for subset in subsets
    }
    comparisons = {
        subset: pairwise_comparisons(
            results, subset_ids(results, test_cases, subset), baseline="unknownid"
        )
        for subset in ("all", "ambiguous", "close_call")
    }
    ig = entropy_validation(
        test_cases,
        references=references,
        evaluator=evaluator,
        error_model=error_model,
        planner=planner,
        confidence=confidence,
        tempering=planner_config.tempering,
    )
    diagnostics = energy_stop_diagnostics(
        test_cases,
        references=references,
        evaluator=evaluator,
        error_model=error_model,
        planner=planner,
        confidence=confidence,
        tempering=planner_config.tempering,
    )
    failures = failure_breakdown(test_cases, results, references, policy="unknownid")
    open_world = run_open_world(
        test_cases,
        references=references,
        evaluator=evaluator,
        error_model=error_model,
        planner=planner,
        confidence=confidence,
        tempering=planner_config.tempering,
    )

    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    n_cases = {
        "all test": len(test_cases),
        "ambiguous (>=2 precursor-consistent candidates)": len(
            subset_ids(results, test_cases, "ambiguous")
        ),
        "close-call (top-2 margin <= 0.15)": len(subset_ids(results, test_cases, "close_call")),
        "easy (precursor-unique)": len(subset_ids(results, test_cases, "easy")),
    }
    report_config = {
        "default_budget": planner_config.budget,
        "budget_eval": BUDGET_EVAL,
        "calibrated_probabilities": bool(
            acquisition_cfg.get_path("confidence.calibrated_probabilities", False)
        ),
        "match_tolerance_da": evaluator.tolerance_da,
        "ppm_tolerance": references.ppm_tolerance,
        "split_seed": int(selection_cfg.get_path("splits.seed", 20261020)),
        "calibration_method": calibration["method"],
    }
    payload = {
        "generated_at_utc": generated_at,
        "generation_metadata": generation_metadata(),
        "split": "test",
        "method": planner.method,
        "config": report_config,
        "n_cases": n_cases,
        "summaries": summaries,
        "paired_comparisons": comparisons,
        "ig_validation": ig,
        "energy_stop_diagnostics": diagnostics,
        "failures": failures,
        "open_world": open_world,
        "calibration": calibration,
        "per_case": results,
    }
    (REPORTS / "evaluation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    REPORTS.mkdir(parents=True, exist_ok=True)
    EVALUATION_MD.write_text(render_report(payload), encoding="utf-8")
    write_pareto(payload, REPORTS / "pareto.svg")
    print(f"==> wrote {EVALUATION_MD} and reports/evaluation.json")
    print(
        f"    test all: unknownid top1@1={summaries['all']['unknownid']['top1_1']:.3f} "
        f"single={summaries['all']['single_scan']['top1_1']:.3f}"
    )
    print(
        f"    test ambiguous: n={summaries['ambiguous']['unknownid'].get('n')} "
        f"unknownid top1@1={summaries['ambiguous']['unknownid'].get('top1_1')} "
        f"always40={summaries['ambiguous']['always_40'].get('top1_1')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

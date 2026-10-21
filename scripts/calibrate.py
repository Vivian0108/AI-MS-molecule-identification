#!/usr/bin/env python
"""Select the acquisition method on dev only.  Must run before run_eval.py."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unknownid.config import load_config  # noqa: E402
from unknownid.core.evidence import EvidenceEvaluator  # noqa: E402
from unknownid.core.retrieve import ReferenceStore  # noqa: E402
from unknownid.eval.baselines import load_eval_cases  # noqa: E402
from unknownid.eval.calibrate import calibrate  # noqa: E402
from unknownid.paths import (  # noqa: E402
    CURATED,
    LIBRARY_PARQUET,
    PRIVATE_ORACLE_JSON,
    PUBLIC_CASES_PARQUET,
)
from unknownid.planner.acquisition import PlannerConfig  # noqa: E402
from unknownid.planner.error_model import ErrorModel  # noqa: E402


def main() -> int:
    selection_cfg = load_config("selection")
    acquisition_cfg = load_config("acquisition")
    references = ReferenceStore(
        __import__("pandas").read_parquet(LIBRARY_PARQUET),
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
    dev_cases = load_eval_cases(
        references=references,
        public_cases_path=PUBLIC_CASES_PARQUET,
        oracle_path=PRIVATE_ORACLE_JSON,
        split="dev",
    )
    planner_config = PlannerConfig(
        budget=int(acquisition_cfg.get_path("measurement_budget", 1)),
        allowed_energies=tuple(acquisition_cfg.get_path("allowed_energies", [30, 40])),
        cost=float(acquisition_cfg.get_path("cost_per_measurement", 1.0)),
        monte_carlo_samples=int(acquisition_cfg.get_path("monte_carlo.samples", 500)),
        seed=int(acquisition_cfg.get_path("monte_carlo.seed", 20261020)),
        tempering=float(acquisition_cfg.get_path("likelihood.likelihood_tempering", 0.85)),
        stop_ig_threshold=float(acquisition_cfg.get_path("confidence.stop_ig_threshold", 0.02)),
        identified_min_support=float(acquisition_cfg.get_path("confidence.identified_min_support", 0.72)),
        identified_min_margin=float(acquisition_cfg.get_path("confidence.identified_min_margin", 0.22)),
        stop_min_support=float(acquisition_cfg.get_path("confidence.stop_min_support", 0.90)),
        stop_min_margin=float(acquisition_cfg.get_path("confidence.stop_min_margin", 0.70)),
        tolerance_da=float(selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
        max_candidates=int(acquisition_cfg.get_path("monte_carlo.max_candidates", 12)),
    )
    confidence = {
        "min_support": float(acquisition_cfg.get_path("confidence.identified_min_support", 0.72)),
        "min_margin": float(acquisition_cfg.get_path("confidence.identified_min_margin", 0.22)),
        "min_similarity": float(acquisition_cfg.get_path("confidence.identified_min_similarity", 0.30)),
        "min_matched": int(acquisition_cfg.get_path("confidence.min_matched_peaks", 2)),
    }
    print(f"==> calibrating on {len(dev_cases)} dev cases (test untouched)")
    payload = calibrate(
        dev_cases,
        references=references,
        evaluator=evaluator,
        error_model=error_model,
        planner_config=planner_config,
        confidence=confidence,
        random_seed=int(selection_cfg.get_path("splits.seed", 20261020)),
    )
    print(f"    selected method: {payload['method']}")
    print(f"    reason: {payload['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

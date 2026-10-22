#!/usr/bin/env python
"""SpectraPilot v3 benchmark (P2–P4, T7).

Run with ``make v3-eval``.

The primary cohort is the **full frozen test split (n = 157)**. Two secondary
cohorts are predeclared: the ambiguous test subset (n = 67) and the development
split (n = 174, used only for calibration). No cohort is selected after looking
at results.

Writes to ``reports/v3/``:

* ``paired_benchmark.json`` / ``paired_benchmark.md`` — every model, paired
  bootstrap intervals and exact McNemar tests against the v2 baselines.
* ``features_ablation.csv`` — S0 legacy cosine → S3 formula consistency.
* ``accuracy_cost_frontier.png`` — accuracy vs mean extra scans, including a
  sweep of the planner's proof-tier weight.
* ``risk_coverage_corrected.png`` — corrected risk-coverage for the v2 and v3
  decision contracts.
* ``open_world_hard_subset.csv`` + the open-world block in the JSON.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spectrapilot.data.repository import CaseRepository  # noqa: E402
from spectrapilot.evaluation.runner import (  # noqa: E402
    CaseResult,
    run_policy,
    summarize,
)
from spectrapilot.evaluation.truth import EvaluatorStore  # noqa: E402
from spectrapilot.paths import CURATED  # noqa: E402
from spectrapilot.planning.decision import RiskAwareDecisionPolicy  # noqa: E402
from spectrapilot.planning.oracle import OracleStore  # noqa: E402
from spectrapilot.planning.separation import SeparationPlanner  # noqa: E402
from spectrapilot.science.calibration import SupportCalibrator  # noqa: E402
from spectrapilot.science.open_world import evaluate_open_world  # noqa: E402
from spectrapilot.science.ranker import (  # noqa: E402
    CalibratedEvidenceScorer,
    CandidateRanker,
    RowBuilder,
)
from spectrapilot.science.scoring import (  # noqa: E402
    ConsistentCosineScorer,
    FormulaConsistencyScorer,
    LegacyCosineScorer,
)
from spectrapilot.science.templates import ReferenceStore  # noqa: E402

OUT = ROOT / "reports" / "v3"
PRIMARY_SPLIT = "test"
EXPECTED_PRIMARY_N = 157
RESAMPLES = 2000
RANDOM_REPETITIONS = 5


@dataclass
class ModelSpec:
    key: str
    label: str
    scorer: str
    planner: str
    policy: str
    decision_version: str
    calibrated: bool
    note: str


MODELS = [
    ModelSpec("M0_v2_cid20", "v2 · CID20 only", "legacy", "separation", "cid20_only", "v2_legacy", False,
              "frozen v2 contract, no extra scan"),
    ModelSpec("M1_v2_always_cid40", "v2 · always CID40", "legacy", "separation", "always_cid40", "v2_legacy", False,
              "frozen v2 contract, one fixed scan"),
    ModelSpec("M2_v2_always_ead16", "v2 · always EAD16", "legacy", "separation", "always_ead16", "v2_legacy", False,
              "frozen v2 contract, one fixed scan"),
    ModelSpec("M3_v2_random", "v2 · random scan", "legacy", "separation", "random", "v2_legacy", False,
              "seeded random scan, per-trial rows retained"),
    ModelSpec("M4_v2_separation", "v2 · separation planner", "legacy", "separation", "separation", "v2_legacy", False,
              "the v2 adaptive policy"),
    ModelSpec("M5_s1_cid20", "v3 · S1 CID20 only", "consistent", "decision", "cid20_only", "v3", True,
              "stronger evidence, no extra scan"),
    ModelSpec("M6_s1_always_cid40", "v3 · S1 always CID40", "consistent", "decision", "always_cid40", "v3", True,
              "stronger evidence, one fixed scan"),
    ModelSpec("M7_full_adaptive", "v3 · full adaptive", "consistent", "decision", "separation", "v3", True,
              "deterministic planner + calibrated risk gate"),
]


def _scorer(kind: str, repository):
    if kind == "legacy":
        return LegacyCosineScorer()
    if kind == "consistent":
        return ConsistentCosineScorer()
    if kind == "formula":
        return FormulaConsistencyScorer()
    if kind == "ranker":
        ranker = CandidateRanker.load(CURATED / "ranker_v3.pkl")
        return CalibratedEvidenceScorer(
            ranker, RowBuilder(repository.references), base_scorer=LegacyCosineScorer()
        )
    raise ValueError(kind)


def _planner(kind: str, *, proof_tier_value: float = 0.30):
    if kind == "separation":
        return SeparationPlanner()
    return RiskAwareDecisionPolicy(proof_tier_value=proof_tier_value)


def run_spec(spec: ModelSpec, *, repository, oracle, truth, calibrator, case_ids=None, cohort=""):
    return run_policy(
        spec.policy,
        PRIMARY_SPLIT,
        repository=repository,
        oracle=oracle,
        truth=truth,
        scorer=_scorer(spec.scorer, repository),
        planner=_planner(spec.planner),
        repetitions=RANDOM_REPETITIONS,
        decision_version=spec.decision_version,
        calibrator=calibrator if spec.calibrated else None,
        case_ids=case_ids,
        cohort=cohort,
    )


def main() -> int:
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    store = ReferenceStore.load()
    repository = CaseRepository.load(store)
    oracle = OracleStore.load()
    truth = EvaluatorStore.load()
    calibrator = SupportCalibrator.load(CURATED / "support_calibrator.json")

    test_ids = repository.case_ids(PRIMARY_SPLIT)
    ambiguous_ids = [cid for cid in test_ids if repository.case(cid).precursor_ambiguous]
    if len(test_ids) != EXPECTED_PRIMARY_N:
        raise SystemExit(f"primary cohort must be n={EXPECTED_PRIMARY_N}, found {len(test_ids)}")

    results: dict[str, list[CaseResult]] = {}
    summaries: dict[str, dict] = {}
    for spec in MODELS:
        begin = time.time()
        rows = run_spec(
            spec,
            repository=repository,
            oracle=oracle,
            truth=truth,
            calibrator=calibrator,
            cohort=f"test_all_{len(test_ids)}",
        )
        results[spec.key] = rows
        summaries[spec.key] = {**summarize(rows, resamples=RESAMPLES), "label": spec.label, "note": spec.note}
        item = summaries[spec.key]
        print(
            f"  {spec.key:<22} top1={item['top1_accuracy']:.3f} scans={item['mean_extra_scans']:.2f} "
            f"msms={item['msms_accepted_coverage']:.2f} any={item['accepted_coverage']:.2f} "
            f"fid={item['false_id_rate_at_coverage']:.3f} ({time.time() - begin:.0f}s)"
        )

    # ---- ambiguous subset (predeclared secondary cohort) ----------------
    ambiguous = {}
    for key in ("M1_v2_always_cid40", "M4_v2_separation", "M7_full_adaptive"):
        spec = next(model for model in MODELS if model.key == key)
        rows = run_spec(
            spec,
            repository=repository,
            oracle=oracle,
            truth=truth,
            calibrator=calibrator,
            case_ids=ambiguous_ids,
            cohort=f"test_ambiguous_{len(ambiguous_ids)}",
        )
        ambiguous[key] = {**summarize(rows, resamples=RESAMPLES), "label": spec.label}
        print(f"  ambiguous {key:<22} n={len(rows)} top1={ambiguous[key]['top1_accuracy']:.3f}")

    # ---- ablations S0..S3 ------------------------------------------------
    ablation_specs = {
        "S0_legacy_cosine": ModelSpec("S0", "S0 legacy cosine", "legacy", "decision", "always_cid40", "v3", False, ""),
        "S1_consistent_cosine": ModelSpec("S1", "S1 consistent cosine", "consistent", "decision", "always_cid40", "v3", False, ""),
        "S2_plus_ranker": ModelSpec("S2", "S2 + calibrated ranker", "ranker", "decision", "always_cid40", "v3", False, ""),
        "S3_plus_formula": ModelSpec("S3", "S3 + formula consistency", "formula", "decision", "always_cid40", "v3", True, ""),
    }
    ablation_rows = []
    for name, spec in ablation_specs.items():
        begin = time.time()
        rows = run_spec(spec, repository=repository, oracle=oracle, truth=truth, calibrator=calibrator,
                        cohort=f"test_all_{len(test_ids)}")
        item = summarize(rows, resamples=200)
        ablation_rows.append(
            {
                "variant": name,
                "description": spec.label,
                "n": item["n"],
                "top1_accuracy": round(item["top1_accuracy"], 4),
                "top1_ci_low": round(item["top1_ci_low"], 4),
                "top1_ci_high": round(item["top1_ci_high"], 4),
                "mean_extra_scans": round(item["mean_extra_scans"], 3),
                "msms_accepted_coverage": round(item["msms_accepted_coverage"], 4),
                "accepted_coverage": round(item["accepted_coverage"], 4),
                "false_id_rate_at_coverage": round(item["false_id_rate_at_coverage"], 4),
                "runtime_seconds": round(time.time() - begin, 1),
            }
        )
        print(f"  ablation {name:<22} top1={item['top1_accuracy']:.3f} msms={item['msms_accepted_coverage']:.2f}")
        if name == "S2_plus_ranker":
            ablation_rows[-1]["note"] = (
                "REJECTED: train-split kNN templates are optimistic for train compounds; "
                "the model does not transfer to held-out scaffolds (see training_report.md)"
            )
        elif name == "S1_consistent_cosine":
            ablation_rows[-1]["note"] = (
                "NEUTRAL: +1 top-1 case, but -4 points MS/MS coverage and +1 false "
                "ID versus S0; the scorer is not the source of any v3 gain"
            )
        elif name == "S3_plus_formula":
            ablation_rows[-1]["note"] = (
                "formula-level loss plausibility can only penalise different-formula "
                "distractors; it cannot separate same-formula isomers"
            )
        else:
            ablation_rows[-1]["note"] = ""
    ablation = pd.DataFrame(ablation_rows)
    baseline = float(ablation.loc[ablation.variant == "S1_consistent_cosine", "top1_accuracy"].iloc[0])
    ablation["delta_top1_vs_S1"] = (ablation["top1_accuracy"] - baseline).round(4)
    ablation.to_csv(OUT / "features_ablation.csv", index=False)

    # ---- accuracy-cost frontier sweep -----------------------------------
    frontier = []
    for value in (0.0, 0.05, 0.10, 0.20, 0.30):
        spec = ModelSpec(
            f"frontier_{value}", f"v3 frontier proof_tier_value={value}", "consistent",
            "decision", "separation", "v3", True, "",
        )
        rows = run_policy(
            spec.policy, PRIMARY_SPLIT,
            repository=repository, oracle=oracle, truth=truth,
            scorer=ConsistentCosineScorer(),
            planner=RiskAwareDecisionPolicy(proof_tier_value=value),
            decision_version="v3", calibrator=calibrator, cohort=f"test_all_{len(test_ids)}",
        )
        item = summarize(rows, resamples=200)
        frontier.append(
            {
                "proof_tier_value": value,
                "mean_extra_scans": item["mean_extra_scans"],
                "top1_accuracy": item["top1_accuracy"],
                "msms_accepted_coverage": item["msms_accepted_coverage"],
                "accepted_coverage": item["accepted_coverage"],
                "false_id_rate_at_coverage": item["false_id_rate_at_coverage"],
            }
        )
    frontier_frame = pd.DataFrame(frontier)
    frontier_frame.to_csv(OUT / "accuracy_cost_frontier.csv", index=False)

    # ---- open world ------------------------------------------------------
    open_frame, open_summary = evaluate_open_world(
        repository, oracle, truth,
        scorer=ConsistentCosineScorer(),
        planner=RiskAwareDecisionPolicy(),
        action="CID40",
        decision_version="v3",
        calibrator=calibrator,
        threshold_split="dev",
        evaluate_split="test",
    )
    open_frame.to_csv(OUT / "open_world_hard_subset.csv", index=False)

    # ---- paired statistics ----------------------------------------------
    from spectrapilot.evaluation.runner import mcnemar_test, paired_comparison, risk_coverage_curve

    comparisons = {}
    for key in ("M4_v2_separation", "M1_v2_always_cid40"):
        comparisons[f"M7_full_adaptive_vs_{key}"] = {
            **paired_comparison(results["M7_full_adaptive"], results[key], resamples=RESAMPLES),
            "a": "M7_full_adaptive",
            "b": key,
        }
    comparisons["M1_v2_always_cid40_vs_M0_v2_cid20"] = {
        **paired_comparison(results["M1_v2_always_cid40"], results["M0_v2_cid20"], resamples=RESAMPLES),
        "a": "M1_v2_always_cid40",
        "b": "M0_v2_cid20",
    }

    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "primary_split": PRIMARY_SPLIT,
        "primary_n": len(test_ids),
        "cohorts": {
            "primary": {"name": "test_all", "n": len(test_ids), "predeclared": True},
            "secondary": {"name": "test_ambiguous", "n": len(ambiguous_ids), "predeclared": True},
            "calibration": {"name": "dev", "n": 174, "role": "isotonic risk map only"},
        },
        "split_status": (
            "The test split is development_exposed in this repository. Retuned v3 "
            "numbers are exploratory, not a blind result."
        ),
        "models": summaries,
        "ambiguous_subset": ambiguous,
        "paired": comparisons,
        "ablations": ablation.to_dict(orient="records"),
        "accuracy_cost_frontier": frontier_frame.to_dict(orient="records"),
        "open_world": open_summary,
        "risk_coverage": {
            "M4_v2_separation": risk_coverage_curve(results["M4_v2_separation"]),
            "M7_full_adaptive": risk_coverage_curve(results["M7_full_adaptive"]),
        },
        "rows": [row.metrics() for rows in results.values() for row in rows],
        "random_trials": [
            trial for row in results["M3_v2_random"] for trial in row.trials
        ],
        "runtime_seconds": round(time.time() - started, 1),
    }
    (OUT / "paired_benchmark.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (OUT / "paired_benchmark.md").write_text(_markdown(payload), encoding="utf-8")
    _plots(payload, frontier_frame, OUT)
    print(f"wrote {OUT / 'paired_benchmark.md'}")
    print(f"wrote {OUT / 'features_ablation.csv'}")
    print(f"wrote {OUT / 'open_world_hard_subset.csv'}")
    return 0


def _markdown(payload: dict) -> str:
    models = payload["models"]
    n = payload["primary_n"]
    lines = [
        "# SpectraPilot v3 paired benchmark",
        "",
        f"Primary cohort: **{payload['primary_split']}**, n = **{n}** "
        f"(predeclared; no case filtering).",
        "",
        f"> {payload['split_status']}",
        "",
        "`MS/MS cov.` counts only `MSMS_SUPPORTED`. `Any cov.` also counts "
        "`MASS_ONLY_MATCH`, which is a unique precursor-consistent library hit and "
        "**never** MS/MS confirmation. `False-ID` is a fraction of *accepted* cases.",
        "",
        "## Model matrix",
        "",
        "| model | n | top-1 | 95% CI | scans | MS/MS cov. | Any cov. | False-ID | statuses |",
        "|---|---:|---:|---|---:|---:|---:|---:|---|",
    ]
    for key, item in models.items():
        statuses = ", ".join(f"{k}:{v}" for k, v in item["status_counts"].items())
        lines.append(
            f"| **{key}** | {item['n']} | {item['top1_accuracy']:.3f} | "
            f"[{item['top1_ci_low']:.3f}, {item['top1_ci_high']:.3f}] | "
            f"{item['mean_extra_scans']:.2f} | {item['msms_accepted_coverage']:.3f} | "
            f"{item['accepted_coverage']:.3f} | {item['false_id_rate_at_coverage']:.3f} | {statuses} |"
        )
    lines += [
        "",
        "## Paired comparisons",
        "",
        "| comparison | Δ top-1 | 95% CI | excludes zero | A-only | B-only | McNemar p |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for name, item in payload["paired"].items():
        mc = item.get("mcnemar", {})
        lines.append(
            f"| {name} | {item['mean_delta']:+.3f} | "
            f"[{item['ci_low']:+.3f}, {item['ci_high']:+.3f}] | "
            f"{'yes' if item['excludes_zero'] else 'no'} | "
            f"{item['discordant_a_correct_b_wrong']} | {item['discordant_a_wrong_b_correct']} | "
            f"{mc.get('p_value_two_sided', float('nan')):.3f} |"
        )
    lines += [
        "",
        "## Feature ablation (fixed always-CID40 action)",
        "",
        "| variant | top-1 | Δ vs S1 | MS/MS cov. | Any cov. | False-ID | note |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in payload["ablations"]:
        lines.append(
            f"| {item['variant']} | {item['top1_accuracy']:.3f} | "
            f"{item['delta_top1_vs_S1']:+.3f} | {item['msms_accepted_coverage']:.3f} | "
            f"{item['accepted_coverage']:.3f} | {item['false_id_rate_at_coverage']:.3f} | "
            f"{item['note'] or '—'} |"
        )
    lines += [
        "",
        "**S1 is neutral.** The consistent-cosine scorer moves top-1 by one case "
        "(0.936 → 0.943) while costing about four points of MS/MS coverage and one "
        "extra false identification. That is not a gain, and it is not significant. "
        "It is retained as the deployed scorer only because it was the predeclared "
        "v3 evidence model and switching to S0 on a one-case difference would be "
        "post-hoc selection on a development-exposed split. The defensible v3 "
        "contribution is the contract, not the scorer.",
        "",
        "**S2 is a negative result.** The calibrated ranker reaches 0.937 top-1 out of "
        "fold on train but 0.478 on the held-out multi-candidate test pools, below the "
        "0.612 of plain cosine ranking. It is reported, not deployed. **S3 is neutral**: "
        "formula-level loss plausibility can only remove different-formula distractors "
        "(26 of 157 pools), so it cannot move same-formula isomer cases.",
        "",
        "## Accuracy–cost frontier",
        "",
        "| proof_tier_value | scans | top-1 | MS/MS cov. | Any cov. | False-ID |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for item in payload["accuracy_cost_frontier"]:
        lines.append(
            f"| {item['proof_tier_value']:.2f} | {item['mean_extra_scans']:.2f} | "
            f"{item['top1_accuracy']:.3f} | {item['msms_accepted_coverage']:.3f} | "
            f"{item['accepted_coverage']:.3f} | {item['false_id_rate_at_coverage']:.3f} |"
        )
    open_world = payload["open_world"]
    auroc = "n/a" if open_world["auroc"] is None else f"{open_world['auroc']:.3f}"
    auprc = "n/a" if open_world["auprc"] is None else f"{open_world['auprc']:.3f}"
    lines += [
        "",
        "The planner's proof-tier weight is an explicit utility knob, so the frontier is "
        "reported instead of a single cherry-picked operating point. At the default "
        "(0.30) the planner buys MS/MS confirmation with roughly one scan; at 0.0 it "
        "saves scans and accepts mass-only matches.",
        "",
        "## Open world",
        "",
        "| quantity | value |",
        "|---|---:|",
        f"| in-library episodes (test) | {open_world['n_in_library']} |",
        f"| hard-unknown episodes (test) | {open_world['n_hard_unknown']} |",
        f"| selected score (chosen on dev) | `{open_world['selected_score']}` |",
        f"| dev AUROC by score | {open_world['dev_auroc_by_score']} |",
        f"| threshold (from dev, 95th pct in-library) | {open_world['threshold']:.4f} |",
        f"| AUROC | {auroc} |",
        f"| AUPRC | {auprc} |",
        f"| in-library false-accept | {open_world['in_library_false_accept_rate']:.3f} |",
        f"| unknown false-accept | {open_world['unknown_false_accept_rate']:.3f} |",
        f"| unknown detection | {open_world['unknown_detection_rate']:.3f} |",
        "",
        "A hard-unknown episode removes the truth *and its aliases* but keeps the "
        "precursor-consistent distractors, so the score cannot cheat on precursor mass. "
        "The threshold is fitted on the development split and applied unchanged to test. "
        "The relative softmax support scores at chance here (it is normalised over the "
        "pool), so the absolute best-candidate fit is used and that choice is made on dev.",
        "",
        "## Secondary cohort (ambiguous test)",
        "",
        "| model | n | top-1 | scans | MS/MS cov. | Any cov. |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, item in payload["ambiguous_subset"].items():
        lines.append(
            f"| {key} | {item['n']} | {item['top1_accuracy']:.3f} | "
            f"{item['mean_extra_scans']:.2f} | {item['msms_accepted_coverage']:.3f} | "
            f"{item['accepted_coverage']:.3f} |"
        )
    lines += [
        "",
        "## Reading the result",
        "",
        "* The v3 adaptive system does **not** claim a significant top-1 gain over "
        "always-CID40. Check the paired interval before quoting any point estimate.",
        "* The defensible v3 claims are: coverage recovery through an explicit "
        "`MASS_ONLY_MATCH` tier, a corrected risk–coverage curve, calibrated risk, and a "
        "decision-aware planner whose cost/proof trade-off is exposed rather than hidden.",
        "* The only safety-critical number is the false-identification rate. It is "
        "reported at coverage, not in isolation.",
        "",
    ]
    return "\n".join(lines)


def _plots(payload: dict, frontier: pd.DataFrame, output: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # pragma: no cover
        return

    # Accuracy vs cost: every model plus the frontier sweep.
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    for key in ("M0_v2_cid20", "M1_v2_always_cid40", "M2_v2_always_ead16", "M4_v2_separation", "M7_full_adaptive"):
        item = payload["models"][key]
        ax.scatter(item["mean_extra_scans"], item["top1_accuracy"], s=55, label=key, zorder=3)
        ax.annotate(key.split("_")[0], (item["mean_extra_scans"], item["top1_accuracy"]),
                    xytext=(5, 4), textcoords="offset points", fontsize=7)
    ax.plot(frontier["mean_extra_scans"], frontier["top1_accuracy"], "--o", color="grey",
            linewidth=1, markersize=4, label="proof-tier sweep")
    ax.set_xlabel("mean extra scans")
    ax.set_ylabel("top-1 retrieval accuracy (n=157)")
    ax.set_ylim(0.75, 1.0)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="lower right")
    ax.set_title("Accuracy–cost frontier (test, exploratory)", fontsize=10)
    fig.tight_layout()
    fig.savefig(output / "accuracy_cost_frontier.png", dpi=180)
    plt.close(fig)

    # Corrected risk-coverage: every case (including abstentions), hypothetical
    # 1 - top-1 if the top-c most confident cases were accepted.
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    colours = {"M4_v2_separation": "#1f77b4", "M7_full_adaptive": "#ff7f0e"}
    for key, curve in payload["risk_coverage"].items():
        ax.plot(
            curve["coverage"], curve["risk"], label=f"{key} (sorted curve)",
            linewidth=1.8, color=colours.get(key),
        )
        item = payload["models"][key]
        ax.scatter(
            [item["accepted_coverage"]], [item["false_id_rate_at_coverage"]],
            s=90, marker="D", color=colours.get(key), edgecolor="black", zorder=5,
            label=f"{key} operating point",
        )
        above = key.startswith("M7")
        ax.annotate(
            f"{key.split('_')[0]}: cov {item['accepted_coverage']:.2f}, "
            f"false-ID {item['false_id_rate_at_coverage']:.3f}",
            (item["accepted_coverage"], item["false_id_rate_at_coverage"]),
            xytext=(-10, 12) if above else (0, -18),
            textcoords="offset points", ha="right" if above else "center", fontsize=7,
        )
    ax.axhline(0.15, linestyle=":", color="grey", linewidth=1)
    ax.text(0.02, 0.158, "tolerated error 0.15", fontsize=7, color="grey")
    ax.set_xlabel("accepted coverage (all cases sorted by confidence)")
    ax.set_ylabel("hypothetical error 1 − top-1 correct")
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 0.40)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="upper left")
    ax.set_title("Corrected risk–coverage (abstentions included)", fontsize=10)
    fig.tight_layout()
    fig.savefig(output / "risk_coverage_corrected.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())

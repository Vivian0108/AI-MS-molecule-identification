#!/usr/bin/env python
"""Failure atlas + oracle-ceiling diagnosis (SpectraPilot v3, P1).

Run with ``make v3-failures``.

Writes to ``reports/v3/``:

* ``failure_atlas.parquet`` / ``failure_atlas.csv`` — one row per test case with
  the per-action outcomes, pool separability, template fidelity and failure class.
* ``failure_atlas_summary.json`` — the aggregate used by every number in the report.
* ``failure_atlas.png`` — class counts.
* ``oracle_ceiling.md`` — the diagnosis, with the negative results stated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spectrapilot.data.repository import CaseRepository  # noqa: E402
from spectrapilot.evaluation.atlas import (  # noqa: E402
    FAILURE_CLASSES,
    build_atlas,
    write_atlas,
)
from spectrapilot.evaluation.truth import EvaluatorStore  # noqa: E402
from spectrapilot.paths import CURATED  # noqa: E402
from spectrapilot.planning.decision import RiskAwareDecisionPolicy  # noqa: E402
from spectrapilot.planning.oracle import OracleStore  # noqa: E402
from spectrapilot.science.calibration import SupportCalibrator  # noqa: E402
from spectrapilot.science.scoring import ConsistentCosineScorer  # noqa: E402
from spectrapilot.science.templates import ReferenceStore  # noqa: E402

OUT = ROOT / "reports" / "v3"


def main() -> int:
    split = sys.argv[1] if len(sys.argv) > 1 else "test"
    store = ReferenceStore.load()
    repository = CaseRepository.load(store)
    oracle = OracleStore.load()
    truth = EvaluatorStore.load()
    calibrator = SupportCalibrator.load(CURATED / "support_calibrator.json")

    frame, summary = build_atlas(
        repository,
        oracle,
        truth,
        split=split,
        scorer=ConsistentCosineScorer(),
        planner=RiskAwareDecisionPolicy(),
        decision_version="v3",
        calibrator=calibrator,
        progress=True,
    )
    summary["split"] = split
    summary["scorer"] = "consistent_cosine (deployed S1)"
    summary["planner"] = "decision_aware_risk_reduction"
    summary["calibration"] = "isotonic support calibrator fitted on dev"
    write_atlas(frame, summary, OUT, title="SpectraPilot v3 failure atlas (test, n=157)")

    md = _report(frame, summary)
    (OUT / "oracle_ceiling.md").write_text(md, encoding="utf-8")
    print(f"wrote {OUT / 'failure_atlas.parquet'}")
    print(f"wrote {OUT / 'oracle_ceiling.md'}")
    print(json.dumps(summary["failure_counts"], indent=2))
    return 0


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _report(frame, summary: dict) -> str:
    counts = summary["failure_counts"]
    sub = summary.get("status_subclass_counts", {})
    n = summary["n"]
    lines = [
        "# Oracle-ceiling diagnosis",
        "",
        f"Frozen **{summary.get('split', 'test')}** cohort, **n = {n}**. "
        f"Deployed scorer: `{summary.get('scorer')}`; planner: `{summary.get('planner')}`. "
        f"Risk calibration: {summary.get('calibration')}.",
        "",
        "This report answers *where the residual error lives*, not *how to inflate the "
        "headline number*. Every ceiling below is a diagnostic and is marked as such.",
        "",
        "## 1. Failure taxonomy",
        "",
        "| class | meaning | cases | share |",
        "|---|---|---:|---:|",
    ]
    for key, meaning in FAILURE_CLASSES.items():
        lines.append(f"| **{key}** | {meaning} | {counts.get(key, 0)} | {_pct(counts.get(key, 0) / n)} |")
    lines += [
        "",
        "Classification order is deterministic and documented in "
        "`src/spectrapilot/evaluation/atlas.py`. A false identification is always "
        "class **F**; a correct top-1 followed by an abstention is also **F** but is "
        "reported separately below, because abstaining on a correct retrieval is a "
        "*coverage* outcome, not automatically a decision bug.",
        "",
        "### Status subclasses",
        "",
        "| subclass | cases | reading |",
        "|---|---:|---|",
        f"| recovered | {sub.get('recovered', 0)} | retrieved and accepted |",
        f"| abstained after correct retrieval | {sub.get('abstained_after_correct_retrieval', 0)} | conservative; costs coverage, not accuracy |",
        f"| insufficient data | {sub.get('insufficient_data', 0)} | the available observations are too sparse |",
        f"| retrieval error | {sub.get('retrieval_error', 0)} | the truth is not ranked first |",
        f"| false identification | {sub.get('false_identification', 0)} | a wrong identity was accepted — the only true safety failure |",
        "",
        "## 2. Ceilings",
        "",
        "| quantity | value | what it bounds |",
        "|---|---:|---|",
        f"| policy top-1 (deployed sequence) | {summary['retrieval_top1_policy']:.3f} | the system |",
        f"| best oracle-selected action (`hindsight_best`) | {summary['action_ceiling']:.3f} | the best a deployable action choice could reach with truth |",
        f"| CID20 only | {summary['retrieval_top1_initial']:.3f} | free evidence |",
        f"| always CID40 | {summary['retrieval_top1_cid40']:.3f} | one fixed extra scan |",
        f"| always EAD16 | {summary['retrieval_top1_ead16']:.3f} | one fixed extra scan |",
        f"| both extra scans | {summary['retrieval_top1_combined']:.3f} | two extra scans |",
        "",
        f"The action ceiling is **{summary['action_ceiling'] - summary['retrieval_top1_policy']:+.3f}** "
        "above the deployed policy. That is the entire remaining value of perfect "
        "action selection on this cohort; it is small, and it is **not** deployable.",
        "",
        "## 3. Is the residual gap chemistry-limited or template-limited?",
        "",
        "`measured_separability` is the cosine gap between the truth and its strongest "
        "competitor when every candidate is scored against **its own measured spectrum** "
        "for the same action. A near-zero gap means the observation cannot separate the "
        "pool even with a perfect predictor — a chemical limit. `template_fidelity` is the "
        "cosine between the observed spectrum and the *predicted* template of the truth; "
        "a low value means the predictor, not the chemistry, is the problem.",
        "",
        "| diagnostic | value |",
        "|---|---:|",
        f"| cases whose pool is separable (gap ≥ 0.10) | {_pct(summary['pool_separable_share'])} |",
        f"| median measured separability (multi-candidate) | {summary['median_measured_separability']:.3f} |",
        f"| median measured separability, same-formula pools (n={summary['n_same_formula_multi']}) | {summary['median_measured_separability_same_formula']:.3f} |",
        f"| median template fidelity | {summary['median_template_fidelity']:.3f} |",
        f"| median template fidelity on failing cases | {summary['median_failing_template_fidelity']:.3f} |",
        f"| failures with information present but poor templates | {summary['failures_with_information_present']} |",
        f"| failures that are chemistry-limited | {summary['failures_chemistry_limited']} |",
        "",
        "**Verdict.** Of the "
        f"{summary['n_failures']} non-recovered cases, "
        f"{summary['failures_with_information_present']} have a separable pool "
        f"(gap ≥ 0.10) yet a truth-template fidelity below 0.30: these are "
        "**template-limited** and could in principle be repaired by a better predictor. "
        f"{summary['failures_chemistry_limited']} have a measured separability below 0.10: "
        "the observations do not separate the pool even with perfect templates, so they are "
        "**chemistry-limited** and no template improvement will fix them. The remaining "
        "failures are decision/coverage outcomes rather than evidence failures.",
        "",
        "Same-formula pools have a median separability of "
        f"{summary['median_measured_separability_same_formula']:.3f} versus "
        f"{summary['median_measured_separability']:.3f} overall: isomer ambiguity is real, "
        "but it is **not** the dominant failure mode on this cohort.",
        "",
        "## 4. What this licenses and what it does not",
        "",
        "Licensed:",
        "",
        "* The observation set contains enough information for most cases; a better "
        "template would move a measurable subset of the template-limited failures.",
        "* Formula-level evidence can only falsify different-formula distractors. It can "
        "never separate isomers, so it must not be sold as structure confirmation.",
        "* Abstention on a correct top-1 is the main coverage cost, and it is conservative.",
        "",
        "Not licensed:",
        "",
        "* The `measured_separability` diagnostic cannot be used as an achievable accuracy "
        "ceiling. It uses each compound's own measured spectrum, which is unavailable for "
        "an unknown; the truth's cosine to itself is 1.0 by construction, so only the "
        "*margin* over the best distractor is meaningful.",
        "* No number here is a blind result. The test split is `development_exposed` in this "
        "repository; every retuned v3 number is exploratory.",
        "",
        "## 5. Reproduce",
        "",
        "```bash",
        "make v3-failures",
        "```",
        "",
        "Case-level rows: `reports/v3/failure_atlas.parquet`.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

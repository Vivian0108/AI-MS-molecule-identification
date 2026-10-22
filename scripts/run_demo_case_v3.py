#!/usr/bin/env python
"""Six-screen counterfactual demo dossier (SpectraPilot v3, T5).

Run with ``make v3-demo``.

For one recovered case and one honest abstention, the dossier walks:

1. case intake (public fields only),
2. the evidence already available and its template provenance,
3. the **precommitted** fragment hypotheses, with the sha256 of the sealed record,
4. the measurement,
5. hypothesis validation against the measured peaks,
6. the decision, plus a counterfactual comparison of the action choices.

Truth is disclosed only after the precommit hash is printed, and the counterfactual
section is explicitly labelled post-hoc/evaluator-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spectrapilot.data.repository import CaseRepository  # noqa: E402
from spectrapilot.evaluation.runner import NullLog, run_policy_case  # noqa: E402
from spectrapilot.evaluation.truth import EvaluatorStore  # noqa: E402
from spectrapilot.paths import CURATED  # noqa: E402
from spectrapilot.planning.decision import RiskAwareDecisionPolicy  # noqa: E402
from spectrapilot.planning.hypotheses import FragmentHypothesisGenerator  # noqa: E402
from spectrapilot.planning.oracle import OracleStore, VirtualInstrument  # noqa: E402
from spectrapilot.planning.session import InvestigationSession  # noqa: E402
from spectrapilot.science.calibration import SupportCalibrator  # noqa: E402
from spectrapilot.science.scoring import ConsistentCosineScorer  # noqa: E402
from spectrapilot.science.templates import ReferenceStore  # noqa: E402

OUT = ROOT / "reports" / "v3"
CASES = ["case-0217e6b5044e", "case-0450558c55a6"]
ACTIONS = ["CID40", "EAD16"]


def _fmt_peaks(mz, intensity, limit=8) -> str:
    order = np.argsort(-np.asarray(intensity, float))[:limit]
    return ", ".join(
        f"{float(mz[i]):.3f} ({float(intensity[i]):.2f})" for i in sorted(order)
    )


def run_case(case_id, *, repository, oracle, truth, scorer, planner, calibrator) -> dict:
    instrument = VirtualInstrument(oracle)
    generator = FragmentHypothesisGenerator()
    session = InvestigationSession(
        case_id,
        repository,
        instrument,
        scorer,
        planner,
        action_log=NullLog(),
        budget=1,
        decision_version="v3",
        calibrator=calibrator,
        hypotheses_generator=generator,
    )
    pre_decision = None
    pre_evidence = session.investigation()
    plan = session.plan()
    action = plan.recommended.get("key") if plan.recommended.get("kind") == "MEASURE" else "CID40"
    available = {item.key for item in instrument.available_actions(case_id)}
    if action not in available:
        action = "CID40" if "CID40" in available else next(iter(available), None)
    hypotheses = session.hypotheses(action) if action else None
    measurement = session.measure(action) if action else None
    investigation = session.stop()
    # ``validate_against_measurement`` returns a new dict, so re-read the
    # session's copy after the scan instead of keeping the pre-commit object.
    hypotheses = session.hypotheses(action) if action else hypotheses
    counterfactuals = {}
    for alternative in ACTIONS:
        if alternative not in available:
            continue
        result = run_policy_case(
            case_id,
            "always_cid40" if alternative == "CID40" else "always_ead16",
            repository=repository,
            oracle=oracle,
            truth=truth,
            scorer=scorer,
            planner=planner,
            decision_version="v3",
            calibrator=calibrator,
        )
        counterfactuals[alternative] = {
            "status": result.status,
            "top1_id": result.top1_id,
            "top1_correct": result.top1_correct,
            "msms": result.accepted,
            "any": result.accepted_any,
        }
    return {
        "case_id": case_id,
        "case": session.case.public_dict(),
        "initial": session.instrument.initial(case_id),
        "plan": plan,
        "action": action,
        "hypotheses": hypotheses,
        "pre_evidence": pre_evidence,
        "investigation": investigation,
        "measurement": measurement,
        "counterfactuals": counterfactuals,
        "truth": truth.truth(case_id),
        "truth_name": truth.name(case_id),
    }


def main() -> int:
    store = ReferenceStore.load()
    repository = CaseRepository.load(store)
    oracle = OracleStore.load()
    truth = EvaluatorStore.load()
    calibrator = SupportCalibrator.load(CURATED / "support_calibrator.json")
    scorer = ConsistentCosineScorer()
    planner = RiskAwareDecisionPolicy()

    dossiers = [
        run_case(
            case_id,
            repository=repository,
            oracle=oracle,
            truth=truth,
            scorer=scorer,
            planner=planner,
            calibrator=calibrator,
        )
        for case_id in CASES
        if oracle.has_case(case_id)
    ]

    lines = [
        "# Demo case dossier",
        "",
        "Two cases: one that reaches `MSMS_SUPPORTED` and one where the system "
        "honestly abstains. Every hypothesis hash below was sealed **before** the "
        "hidden spectrum was requested; the truth is printed only after the hash.",
        "",
        "> The demo is a CLI dossier, not a web UI. The same six screens are "
        "available programmatically through `InvestigationSession`.",
        "",
    ]
    for dossier in dossiers:
        case = dossier["case"]
        investigation = dossier["investigation"]
        initial = dossier["initial"]
        lines += [
            f"## `{dossier['case_id']}`",
            "",
            "### 1. Case intake (public)",
            "",
            f"* precursor m/z **{case['precursor_mz']:.4f}**, adduct `{case['adduct']}`, "
            f"instrument `{case['instrument_model']}`",
            f"* candidate pool: **{case['n_candidates']}** precursor-consistent structures",
            f"* available actions: `{', '.join(case['available_actions'])}`; "
            f"budget **{case['measurement_budget']}**",
            f"* no truth field is present in the public case record",
            "",
            "### 2. Evidence available before the extra scan",
            "",
            f"* CID20 peaks: {_fmt_peaks(initial.mz, initial.intensity)}",
            f"* plan: `{dossier['plan'].method}` → "
            f"**{dossier['plan'].recommended.get('key')}** ({dossier['plan'].score_type})",
            f"* plan note: {dossier['plan'].note}",
            "",
            "### 3. Precommitted hypotheses (sealed)",
            "",
        ]
        hypotheses = dossier["hypotheses"] or {}
        lines += [
            f"* action: `{hypotheses.get('action')}`",
            f"* **precommit sha256**: `{hypotheses.get('precommit_sha256', 'n/a')}`",
            f"* method: `{hypotheses.get('method')}`; predicted from templates only",
            "",
            "| id | candidate | template source | reliability | predicted peaks (m/z) | rule |",
            "|---|---|---|---:|---|---|",
        ]
        for item in hypotheses.get("hypotheses", []):
            peaks = ", ".join(str(peak["mz"]) for peak in item["predicted_diagnostic_peaks"])
            lines.append(
                f"| {item['hypothesis_id']} | `{item['candidate_id'][:14]}…` | "
                f"{item['template_source']} | {item['template_reliability']:.3f} | "
                f"{peaks} | {item['falsification_rule']} |"
            )
        measurement = dossier.get("measurement")
        lines += [
            "",
            "### 4. Measurement",
            "",
        ]
        if measurement is not None:
            lines += [
                f"* action `{measurement.action}`: "
                f"{_fmt_peaks(measurement.mz, measurement.intensity)}",
                f"* peaks: **{len(measurement.mz)}**; hidden until the precommit hash existed",
            ]
        else:
            lines.append("* no measurement was taken")
        lines += [
            "",
            "### 5. Hypothesis validation (after the scan)",
            "",
            "| id | candidate | status | matched / predicted | forbidden hits |",
            "|---|---|---|---:|---:|",
        ]
        for item in (dossier["hypotheses"] or {}).get("hypotheses", []):
            lines.append(
                f"| {item['hypothesis_id']} | `{item['candidate_id'][:14]}…` | "
                f"**{item['status']}** | {item.get('match_count', 0)} / "
                f"{len(item['predicted_diagnostic_peaks'])} | {item.get('forbidden_hits', 0)} |"
            )
        lines += [
            "",
            "### 6. Decision and counterfactuals",
            "",
            f"* status: **`{investigation.decision}`** "
            f"(proof tier: `{investigation.proof_level}`)",
            f"* top-1: `{investigation.predicted_identity or '—'}`; "
            f"confidence {investigation.confidence if investigation.confidence is None else round(investigation.confidence, 3)}; "
            f"calibrated error {investigation.estimated_error if investigation.estimated_error is None else round(investigation.estimated_error, 3)}",
            f"* reasons: {', '.join(investigation.status_reasons) or '—'}",
            "",
            "| action taken | status | retrieval top-1 correct | MS/MS accepted | any accepted |",
            "|---|---|---|---:|---:|",
        ]
        for action, item in dossier["counterfactuals"].items():
            lines.append(
                f"| {action} | {item['status']} | {item['top1_correct']:.0f} | "
                f"{item['msms']:.0f} | {item['any']:.0f} |"
            )
        supported = [
            item
            for item in (dossier["hypotheses"] or {}).get("hypotheses", [])
            if item.get("status") == "supported"
        ]
        if len(supported) >= 2:
            signature = {
                tuple(peak["mz"] for peak in item["predicted_diagnostic_peaks"])
                for item in supported
            }
            lines.append(
                ""
            )
            lines.append(
                f"> **Why this abstains:** {len(supported)} candidates have "
                + (
                    "*identical* precommitted peak sets, so the evidence cannot "
                    "separate them even though both hypotheses are supported. "
                    if len(signature) == 1
                    else "overlapping precommitted peak sets, so the evidence does "
                    "not establish a unique structure. "
                )
                + "The contract abstains rather than guessing; a `supported` "
                "hypothesis is a rule outcome, not structural proof."
            )
        lines += [
            "",
            f"> Truth (evaluator-only, printed after the precommit): "
            f"`{dossier['truth']}` — {dossier['truth_name']}.",
            "",
            "> The counterfactual table is post-hoc and uses evaluator truth to score "
            "the alternatives. It is a diagnostic, not a deployable policy.",
            "",
        ]
    lines += [
        "## What the demo does not claim",
        "",
        "* A `supported` hypothesis is a predeclared rule outcome, not structural proof.",
        "* A `MASS_ONLY_MATCH` is not an MS/MS confirmation.",
        "* The predicted templates inherit their provenance; a kNN template is a "
        "prediction, not a measurement.",
        "",
        "```bash",
        "make v3-demo",
        "```",
        "",
    ]
    (OUT / "demo_case_dossier.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "demo_case_dossier.json").write_text(
        json.dumps(
            [
                {
                    "case_id": dossier["case_id"],
                    "action": dossier["action"],
                    "decision": dossier["investigation"].decision,
                    "proof_level": dossier["investigation"].proof_level,
                    "precommit_sha256": (dossier["hypotheses"] or {}).get("precommit_sha256"),
                    "hypothesis_statuses": [
                        item["status"]
                        for item in (dossier["hypotheses"] or {}).get("hypotheses", [])
                    ],
                    "truth": dossier["truth"],
                }
                for dossier in dossiers
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUT / 'demo_case_dossier.md'}")
    for dossier in dossiers:
        print(f"  {dossier['case_id']} -> {dossier['investigation'].decision} "
              f"(precommit {(dossier['hypotheses'] or {}).get('precommit_sha256', 'n/a')[:12]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

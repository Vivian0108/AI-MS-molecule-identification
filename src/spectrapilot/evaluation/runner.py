"""Frozen benchmark runner for SpectraPilot.

All policies see the same case, candidate universe and evidence scorer.  The
hindsight policy is evaluator-only and is clearly marked as a diagnostic ceiling.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from spectrapilot.data.repository import CaseRepository
from spectrapilot.evaluation.truth import EvaluatorStore
from spectrapilot.paths import CURATED, REPORTS
from spectrapilot.planning.oracle import OracleStore, VirtualInstrument
from spectrapilot.planning.separation import SeparationPlanner
from spectrapilot.planning.session import InvestigationSession
from spectrapilot.science.scoring import CandidateScorer
from spectrapilot.science.templates import ReferenceStore


class NullLog:
    def write(self, entry: dict) -> None:
        return None


@dataclass
class CaseResult:
    case_id: str
    policy: str
    split: str
    true_id: str
    top1_id: str
    top1_correct: float
    top3_correct: float
    reciprocal_rank: float
    status: str
    accepted: int
    correct_accepted: int
    false_id: int
    confidence: float
    fit: float
    extra_scans: float
    actions: list[str] = field(default_factory=list)
    n_candidates: int = 0
    precursor_ambiguous: bool = False
    formula_collision: bool = False

    def metrics(self) -> dict:
        return asdict(self)


def _case_flags(repository: CaseRepository, case_id: str, true_id: str) -> tuple[bool, bool]:
    case = repository.case(case_id)
    formula = repository.references.candidate(true_id).formula if true_id in repository.references.candidate_ids else ""
    collision = False
    if formula:
        collision = sum(
            1
            for cid in case.candidate_ids
            if cid in repository.references.candidate_ids
            and repository.references.candidate(cid).formula == formula
        ) >= 2
    return case.precursor_ambiguous, collision


def _result_from_session(
    session: InvestigationSession,
    policy: str,
    truth: EvaluatorStore,
    repository: CaseRepository,
    *,
    runtime: float = 0.0,
) -> CaseResult:
    investigation = session.investigation()
    evidence = investigation.candidate_evidence
    true_id = truth.truth(session.case_id)
    top1 = str(evidence[0]["candidate_id"]) if evidence else ""
    order = [str(item["candidate_id"]) for item in evidence]
    rank = order.index(true_id) + 1 if true_id in order else 10_000
    accepted = int(investigation.decision == "IDENTIFIED")
    predicted = investigation.predicted_identity
    correct_accepted = int(accepted and predicted == true_id)
    false_id = int(accepted and predicted != true_id)
    confidence = float(evidence[0]["weight"]) if evidence else 0.0
    fit = float(max(evidence[0]["similarity_by_action"].values(), default=0.0)) if evidence else 0.0
    ambiguous, collision = _case_flags(repository, session.case_id, true_id)
    return CaseResult(
        case_id=session.case_id,
        policy=policy,
        split=truth.split(session.case_id),
        true_id=true_id,
        top1_id=top1,
        top1_correct=float(top1 == true_id),
        top3_correct=float(true_id in order[:3]),
        reciprocal_rank=float(1.0 / rank) if rank < 10_000 else 0.0,
        status=investigation.decision,
        accepted=accepted,
        correct_accepted=correct_accepted,
        false_id=false_id,
        confidence=confidence,
        fit=fit,
        extra_scans=float(
            sum(1 for action in investigation.selected_actions if action["kind"] == "MEASURE")
        ),
        actions=[action["key"] for action in investigation.selected_actions if action["kind"] == "MEASURE"],
        n_candidates=len(session.case.candidate_ids),
        precursor_ambiguous=ambiguous,
        formula_collision=collision,
    )


def run_policy_case(
    case_id: str,
    policy: str,
    *,
    repository: CaseRepository,
    oracle: OracleStore,
    truth: EvaluatorStore,
    scorer: CandidateScorer,
    planner: SeparationPlanner,
    rng: np.random.Generator | None = None,
    budget: int = 1,
    decision_overrides: dict | None = None,
) -> CaseResult:
    true_id = truth.truth(case_id)
    if policy == "precursor_only":
        case = repository.case(case_id)
        top1 = case.candidate_ids[0] if case.candidate_ids else ""
        accepted = int(bool(top1))
        false_id = int(accepted and top1 != true_id)
        ambiguous, collision = _case_flags(repository, case_id, true_id)
        return CaseResult(
            case_id=case_id,
            policy=policy,
            split=truth.split(case_id),
            true_id=true_id,
            top1_id=top1,
            top1_correct=float(top1 == true_id),
            top3_correct=float(true_id in case.candidate_ids[:3]),
            reciprocal_rank=float(1.0 / (case.candidate_ids.index(true_id) + 1))
            if true_id in case.candidate_ids
            else 0.0,
            status="IDENTIFIED" if accepted else "OUT_OF_LIBRARY",
            accepted=accepted,
            correct_accepted=int(accepted and top1 == true_id),
            false_id=false_id,
            confidence=1.0,
            fit=0.0,
            extra_scans=0.0,
            n_candidates=len(case.candidate_ids),
            precursor_ambiguous=ambiguous,
            formula_collision=collision,
        )

    instrument = VirtualInstrument(oracle)
    session = InvestigationSession(
        case_id,
        repository,
        instrument,
        scorer,
        planner,
        action_log=NullLog(),
        decision_overrides=decision_overrides,
        budget=budget,
    )
    if policy == "cid20_only":
        pass
    elif policy == "always_cid40":
        if "CID40" in {action.key for action in instrument.available_actions(case_id)}:
            session.measure("CID40")
    elif policy == "always_ead16":
        if "EAD16" in {action.key for action in instrument.available_actions(case_id)}:
            session.measure("EAD16")
    elif policy == "random":
        assert rng is not None
        choices = ["CID40", "EAD16"]
        available = {action.key for action in instrument.available_actions(case_id)}
        choices = [choice for choice in choices if choice in available]
        if choices:
            session.measure(str(rng.choice(choices)))
    elif policy == "separation":
        plan = session.plan()
        if plan.recommended["kind"] == "MEASURE":
            session.measure(plan.recommended["key"])
    elif policy == "all_measurements":
        available = {action.key for action in instrument.available_actions(case_id)}
        for key in ("CID40", "EAD16"):
            if key in available:
                session.measure(key)
    elif policy == "hindsight_best":
        # Offline diagnostic only.  The truth is used to select the action, so
        # this is never a deployable policy.
        best: CaseResult | None = None
        for key in ("CID40", "EAD16"):
            if key not in {action.key for action in instrument.available_actions(case_id)}:
                continue
            instrument = VirtualInstrument(oracle)
            trial = InvestigationSession(
                case_id,
                repository,
                instrument,
                scorer,
                planner,
                action_log=NullLog(),
                decision_overrides=decision_overrides,
                budget=budget,
            )
            trial.measure(key)
            trial.stop()
            result = _result_from_session(trial, policy, truth, repository)
            if best is None or (result.top1_correct, result.confidence) > (
                best.top1_correct,
                best.confidence,
            ):
                best = result
        if best is None:
            session.stop()
            return _result_from_session(session, policy, truth, repository)
        return best
    else:
        raise ValueError(f"unknown policy: {policy}")
    session.stop()
    return _result_from_session(session, policy, truth, repository)


def run_policy(
    policy: str,
    split: str,
    *,
    repository: CaseRepository,
    oracle: OracleStore,
    truth: EvaluatorStore,
    scorer: CandidateScorer,
    planner: SeparationPlanner,
    repetitions: int = 1,
    seed: int = 20261021,
    budget: int = 1,
    decision_overrides: dict | None = None,
) -> list[CaseResult]:
    case_ids = repository.case_ids(split)
    results: list[CaseResult] = []
    for index, case_id in enumerate(case_ids):
        if policy == "random":
            repeats = []
            for repetition in range(repetitions):
                rng = np.random.default_rng(seed + index * 1009 + repetition)
                repeats.append(
                    run_policy_case(
                        case_id,
                        policy,
                        repository=repository,
                        oracle=oracle,
                        truth=truth,
                        scorer=scorer,
                        planner=planner,
                        rng=rng,
                        budget=budget,
                        decision_overrides=decision_overrides,
                    )
                )
            results.append(_average_repeats(repeats))
        else:
            results.append(
                run_policy_case(
                    case_id,
                    policy,
                    repository=repository,
                    oracle=oracle,
                    truth=truth,
                    scorer=scorer,
                    planner=planner,
                    budget=budget,
                    decision_overrides=decision_overrides,
                )
            )
    return results


def _average_repeats(results: Sequence[CaseResult]) -> CaseResult:
    base = results[0]
    return CaseResult(
        case_id=base.case_id,
        policy=base.policy,
        split=base.split,
        true_id=base.true_id,
        top1_id=base.top1_id,
        top1_correct=float(np.mean([r.top1_correct for r in results])),
        top3_correct=float(np.mean([r.top3_correct for r in results])),
        reciprocal_rank=float(np.mean([r.reciprocal_rank for r in results])),
        status="MIXED" if len({r.status for r in results}) > 1 else base.status,
        accepted=float(np.mean([r.accepted for r in results])),
        correct_accepted=float(np.mean([r.correct_accepted for r in results])),
        false_id=float(np.mean([r.false_id for r in results])),
        confidence=float(np.mean([r.confidence for r in results])),
        fit=float(np.mean([r.fit for r in results])),
        extra_scans=float(np.mean([r.extra_scans for r in results])),
        actions=sorted({action for r in results for action in r.actions}),
        n_candidates=base.n_candidates,
        precursor_ambiguous=base.precursor_ambiguous,
        formula_collision=base.formula_collision,
    )


def bootstrap_ci(values: Iterable[float], *, resamples: int = 2000, seed: int = 20261021) -> tuple[float, float, float]:
    array = np.asarray(list(values), float)
    if array.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    means = np.empty(resamples)
    for index in range(resamples):
        sample = rng.choice(array, size=array.size, replace=True)
        means[index] = sample.mean()
    return float(array.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return p, centre - half, centre + half


def summarize(results: Sequence[CaseResult], *, resamples: int = 2000, seed: int = 20261021) -> dict:
    n = len(results)
    top1 = np.array([r.top1_correct for r in results], float)
    accepted = np.array([r.accepted for r in results], float)
    false_id = np.array([r.false_id for r in results], float)
    correct_accepted = np.array([r.correct_accepted for r in results], float)
    scans = np.array([r.extra_scans for r in results], float)
    mean, low, high = bootstrap_ci(top1, resamples=resamples, seed=seed)
    coverage = float(accepted.mean()) if n else 0.0
    accepted_count = float(accepted.sum())
    false_rate = float(false_id.sum() / accepted_count) if accepted_count > 0 else 0.0
    accepted_accuracy = (
        float(correct_accepted.sum() / accepted_count) if accepted_count > 0 else 0.0
    )
    return {
        "n": n,
        "top1_accuracy": mean,
        "top1_ci_low": low,
        "top1_ci_high": high,
        "top3_accuracy": float(np.mean([r.top3_correct for r in results])) if n else 0.0,
        "mrr": float(np.mean([r.reciprocal_rank for r in results])) if n else 0.0,
        "mean_extra_scans": float(scans.mean()) if n else 0.0,
        "accepted_coverage": coverage,
        "accepted_accuracy": accepted_accuracy,
        "false_id_rate_at_coverage": false_rate,
        "selective_risk": float(false_id.mean()) if n else 0.0,
        "status_counts": {
            status: sum(1 for r in results if r.status == status)
            for status in sorted({r.status for r in results})
        },
    }


def paired_comparison(
    results_a: Sequence[CaseResult],
    results_b: Sequence[CaseResult],
    *,
    metric: str = "top1_correct",
    resamples: int = 2000,
    seed: int = 20261021,
) -> dict:
    by_id_b = {r.case_id: r for r in results_b}
    paired = [(r, by_id_b[r.case_id]) for r in results_a if r.case_id in by_id_b]
    deltas = np.array([getattr(a, metric) - getattr(b, metric) for a, b in paired], float)
    mean, low, high = bootstrap_ci(deltas, resamples=resamples, seed=seed)
    a_correct = np.array([r.top1_correct >= 0.5 for r, _ in paired])
    b_correct = np.array([r.top1_correct >= 0.5 for _, r in paired])
    return {
        "metric": metric,
        "n_pairs": len(paired),
        "mean_delta": mean,
        "ci_low": low,
        "ci_high": high,
        "excludes_zero": bool(low > 0 or high < 0),
        "discordant_a_correct_b_wrong": int(np.sum(a_correct & ~b_correct)),
        "discordant_a_wrong_b_correct": int(np.sum(~a_correct & b_correct)),
    }


def write_benchmark(
    policy_results: dict[str, list[CaseResult]],
    *,
    split: str,
    output_dir: Path = REPORTS,
    resamples: int = 2000,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = {
        policy: summarize(results, resamples=resamples)
        for policy, results in policy_results.items()
    }
    comparisons = {}
    reference = "always_cid40" if "always_cid40" in policy_results else next(iter(policy_results))
    for policy, results in policy_results.items():
        if policy == reference:
            continue
        comparisons[policy] = paired_comparison(
            results, policy_results[reference], resamples=resamples
        )
    payload = {
        "split": split,
        "reference_policy": reference,
        "policies": summaries,
        "paired_vs_reference": comparisons,
        "rows": [r.metrics() for results in policy_results.values() for r in results],
    }
    (output_dir / "benchmark.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(payload, output_dir / "benchmark.md")
    _write_plots(policy_results, summaries, output_dir)
    return payload


def _write_markdown(payload: dict, path: Path) -> None:
    lines = [
        f"# SpectraPilot benchmark — {payload['split']} split",
        "",
        "All policies use the same candidate universe and the same frozen scorer. "
        "The random policy is averaged over seeded repetitions by molecule. "
        "The hindsight policy uses truth to choose an action and is not deployable.",
        "",
        "| Policy | n | Top-1 | 95% CI | Mean extra scans | Coverage | Accepted acc. | False ID at coverage |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for policy, item in payload["policies"].items():
        lines.append(
            f"| {policy} | {item['n']} | {item['top1_accuracy']:.3f} | "
            f"[{item['top1_ci_low']:.3f}, {item['top1_ci_high']:.3f}] | "
            f"{item['mean_extra_scans']:.2f} | {item['accepted_coverage']:.3f} | "
            f"{item['accepted_accuracy']:.3f} | {item['false_id_rate_at_coverage']:.3f} |"
        )
    lines += [
        "",
        "## Paired differences",
        "",
        f"Reference: `{payload['reference_policy']}`. Bootstrap resamples are by molecule.",
        "",
        "| Policy | Δ Top-1 | 95% CI | Excludes zero | Discordant (policy correct / ref wrong) | Discordant (policy wrong / ref correct) |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for policy, item in payload["paired_vs_reference"].items():
        lines.append(
            f"| {policy} | {item['mean_delta']:+.3f} | "
            f"[{item['ci_low']:+.3f}, {item['ci_high']:+.3f}] | "
            f"{'yes' if item['excludes_zero'] else 'no'} | "
            f"{item['discordant_a_correct_b_wrong']} | {item['discordant_a_wrong_b_correct']} |"
        )
    lines += [
        "",
        "## Reading the result",
        "",
        "A positive point estimate is not evidence of an accuracy gain unless the paired interval excludes zero. "
        "If intervals overlap zero, the defensible claim is cost or a case study, not improved identification.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_plots(
    policy_results: dict[str, list[CaseResult]],
    summaries: dict[str, dict],
    output_dir: Path,
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # pragma: no cover
        return
    labels = list(summaries)
    scans = [summaries[p]["mean_extra_scans"] for p in labels]
    accuracy = [summaries[p]["top1_accuracy"] for p in labels]
    low = [summaries[p]["top1_ci_low"] for p in labels]
    high = [summaries[p]["top1_ci_high"] for p in labels]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.errorbar(
        scans,
        accuracy,
        yerr=[np.array(accuracy) - np.array(low), np.array(high) - np.array(accuracy)],
        fmt="o",
        capsize=3,
    )
    for x, y, label in zip(scans, accuracy, labels):
        ax.annotate(label, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7)
    ax.set_xlabel("mean extra scans")
    ax.set_ylabel("top-1 accuracy")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_dir / "accuracy_vs_scans.png", dpi=180)
    plt.close(fig)

    # Risk-coverage curve for accepted cases.
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for policy, results in policy_results.items():
        ordered = sorted(results, key=lambda r: -r.confidence)
        coverage = np.arange(1, len(ordered) + 1) / max(len(ordered), 1)
        false = np.cumsum([r.false_id for r in ordered]) / np.arange(1, len(ordered) + 1)
        ax.plot(coverage, false, label=policy, linewidth=1.5)
    ax.set_xlabel("accepted coverage")
    ax.set_ylabel("false identification rate among accepted")
    ax.set_ylim(0, 1.0)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(output_dir / "risk_coverage.png", dpi=180)
    plt.close(fig)

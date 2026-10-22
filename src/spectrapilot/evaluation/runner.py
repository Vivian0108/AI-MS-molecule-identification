"""Benchmark runner for SpectraPilot v3.

Correctness fixes over v2 (spec §1.2–§1.4):

* **Risk–coverage curve** — sorted hypothetical risk ``1 - top1_correct`` for
  *every* case, including abstained ones.  v2 computed the cumulative mean of
  ``false_id``, which is zero whenever the system abstains; the curve was
  therefore drawn on the wrong sample and made abstention look free.
* **Retrieval vs acceptance** — top-1 retrieval, MS/MS-verified acceptance and
  mass-only acceptance are separate metrics.
* **Random policy** — the aggregated row no longer claims a molecular
  ``top1_id``; every trial is retained for audit.
* **Cohorts** — every summary carries its cohort label and n, so a subset can
  never be quoted as if it were the frozen test cohort.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from spectrapilot.data.repository import CaseRepository
from spectrapilot.evaluation.truth import EvaluatorStore
from spectrapilot.models import EvidenceStatus
from spectrapilot.paths import REPORTS
from spectrapilot.planning.oracle import OracleStore, VirtualInstrument
from spectrapilot.planning.separation import SeparationPlanner
from spectrapilot.planning.session import InvestigationSession
from spectrapilot.science.scoring import CandidateScorer
from spectrapilot.science.templates import ReferenceStore

MSMS = EvidenceStatus.MSMS_SUPPORTED.value
MASS_ONLY = EvidenceStatus.MASS_ONLY_MATCH.value
ACCEPTED = {MSMS, MASS_ONLY}


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
    # identity acceptance, split by proof tier
    accepted: float = 0.0            # MS/MS-verified acceptance only
    correct_accepted: float = 0.0
    false_id: float = 0.0
    accepted_any: float = 0.0        # MS/MS + mass-only
    correct_any: float = 0.0
    false_id_any: float = 0.0
    mass_only: float = 0.0
    confidence: float = 0.0
    fit: float = 0.0
    extra_scans: float = 0.0
    actions: list[str] = field(default_factory=list)
    n_candidates: int = 0
    precursor_ambiguous: bool = False
    formula_collision: bool = False
    # v3 diagnostics
    proof_level: str = "abstained"
    status_reasons: list[str] = field(default_factory=list)
    estimated_error: float | None = None
    unknown_risk: float | None = None
    top1_id_defined: bool = True
    trials: list[dict] = field(default_factory=list)
    runtime_ms: float = 0.0
    cohort: str = ""

    def metrics(self) -> dict:
        return asdict(self)

    @property
    def error(self) -> float:
        """Hypothetical error if this case were accepted at its confidence."""
        return float(1.0 - self.top1_correct)


def _case_flags(repository: CaseRepository, case_id: str, true_id: str) -> tuple[bool, bool]:
    case = repository.case(case_id)
    formula = (
        repository.references.candidate(true_id).formula
        if true_id in repository.references.candidate_ids
        else ""
    )
    collision = False
    if formula:
        collision = (
            sum(
                1
                for cid in case.candidate_ids
                if cid in repository.references.candidate_ids
                and repository.references.candidate(cid).formula == formula
            )
            >= 2
        )
    return case.precursor_ambiguous, collision


def _result_from_session(
    session: InvestigationSession,
    policy: str,
    truth: EvaluatorStore,
    repository: CaseRepository,
    *,
    runtime_ms: float = 0.0,
    cohort: str = "",
) -> CaseResult:
    investigation = session.investigation()
    evidence = investigation.candidate_evidence
    true_id = truth.truth(session.case_id)
    top1 = str(evidence[0]["candidate_id"]) if evidence else ""
    order = [str(item["candidate_id"]) for item in evidence]
    rank = order.index(true_id) + 1 if true_id in order else 10_000
    # The frozen v2 engine emitted "IDENTIFIED"; normalise it to the strict
    # v3 tier so legacy and v3 rows are summarised on the same scale.
    status = MSMS if investigation.decision == "IDENTIFIED" else investigation.decision
    accepted_msms = int(status == MSMS)
    accepted_any = int(status in ACCEPTED)
    predicted = investigation.predicted_identity
    confidence = float(evidence[0]["relative_weight"] or evidence[0]["weight"]) if evidence else 0.0
    fit = (
        float(max(evidence[0]["similarity_by_action"].values(), default=0.0))
        if evidence
        else 0.0
    )
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
        status=status,
        accepted=float(accepted_msms),
        correct_accepted=float(accepted_msms and predicted == true_id),
        false_id=float(accepted_msms and predicted != true_id),
        accepted_any=float(accepted_any),
        correct_any=float(accepted_any and predicted == true_id),
        false_id_any=float(accepted_any and predicted != true_id),
        mass_only=float(status == MASS_ONLY),
        confidence=confidence,
        fit=fit,
        extra_scans=float(
            sum(1 for action in investigation.selected_actions if action["kind"] == "MEASURE")
        ),
        actions=[
            action["key"]
            for action in investigation.selected_actions
            if action["kind"] == "MEASURE"
        ],
        n_candidates=len(session.case.candidate_ids),
        precursor_ambiguous=ambiguous,
        formula_collision=collision,
        proof_level=investigation.proof_level,
        status_reasons=list(investigation.status_reasons),
        estimated_error=investigation.estimated_error,
        unknown_risk=investigation.unknown_risk,
        runtime_ms=float(runtime_ms),
        cohort=cohort,
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
    decision_version: str = "v3",
    hypotheses_generator=None,
    open_world_model=None,
    calibrator=None,
    cohort: str = "",
) -> CaseResult:
    true_id = truth.truth(case_id)
    if policy == "precursor_only":
        case = repository.case(case_id)
        top1 = case.candidate_ids[0] if case.candidate_ids else ""
        ambiguous, collision = _case_flags(repository, case_id, true_id)
        return CaseResult(
            case_id=case_id,
            policy=policy,
            split=truth.split(case_id),
            true_id=true_id,
            top1_id=top1,
            top1_correct=float(top1 == true_id),
            top3_correct=float(true_id in case.candidate_ids[:3]),
            reciprocal_rank=(
                float(1.0 / (case.candidate_ids.index(true_id) + 1))
                if true_id in case.candidate_ids
                else 0.0
            ),
            status="RETRIEVAL_ONLY",
            accepted=0.0,
            correct_accepted=0.0,
            false_id=0.0,
            accepted_any=0.0,
            correct_any=0.0,
            false_id_any=0.0,
            confidence=1.0,
            n_candidates=len(case.candidate_ids),
            precursor_ambiguous=ambiguous,
            formula_collision=collision,
            cohort=cohort,
        )

    def _session():
        return InvestigationSession(
            case_id,
            repository,
            VirtualInstrument(oracle),
            scorer,
            planner,
            action_log=NullLog(),
            decision_overrides=decision_overrides,
            budget=budget,
            decision_version=decision_version,
            hypotheses_generator=hypotheses_generator,
            open_world_model=open_world_model,
            calibrator=calibrator,
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
        decision_version=decision_version,
        hypotheses_generator=hypotheses_generator,
        open_world_model=open_world_model,
        calibrator=calibrator,
    )
    available = {action.key for action in instrument.available_actions(case_id)}
    if policy == "cid20_only":
        pass
    elif policy == "always_cid40":
        if "CID40" in available:
            session.measure("CID40")
    elif policy == "always_ead16":
        if "EAD16" in available:
            session.measure("EAD16")
    elif policy == "random":
        assert rng is not None
        choices = [choice for choice in ("CID40", "EAD16") if choice in available]
        if choices:
            session.measure(str(rng.choice(choices)))
    elif policy == "separation":
        plan = session.plan()
        if plan.recommended["kind"] == "MEASURE":
            session.measure(plan.recommended["key"])
    elif policy == "decision_planner":
        plan = session.plan()
        if plan.recommended["kind"] == "MEASURE":
            session.measure(plan.recommended["key"])
    elif policy == "all_measurements":
        for key in ("CID40", "EAD16"):
            if key in available:
                session.measure(key)
    elif policy == "hindsight_best":
        # Diagnostic ceiling only: truth selects the action, never deployable.
        best: CaseResult | None = None
        for key in ("CID40", "EAD16"):
            if key not in available:
                continue
            trial = _session()
            trial.measure(key)
            trial.stop()
            result = _result_from_session(trial, policy, truth, repository, cohort=cohort)
            if best is None or (result.top1_correct, result.confidence) > (
                best.top1_correct,
                best.confidence,
            ):
                best = result
        if best is None:
            session.stop()
            return _result_from_session(session, policy, truth, repository, cohort=cohort)
        return best
    elif policy == "both_actions":
        for key in ("CID40", "EAD16"):
            if key in available:
                session.measure(key)
    else:
        raise ValueError(f"unknown policy: {policy}")
    session.stop()
    return _result_from_session(session, policy, truth, repository, cohort=cohort)


def run_policy(
    policy: str,
    split: str,
    *,
    repository: CaseRepository,
    oracle: OracleStore,
    truth: EvaluatorStore,
    scorer: CandidateScorer,
    planner: SeparationPlanner,
    repetitions: int = 20,
    seed: int = 20261021,
    budget: int = 1,
    decision_overrides: dict | None = None,
    decision_version: str = "v3",
    hypotheses_generator=None,
    open_world_model=None,
    calibrator=None,
    case_ids: Sequence[str] | None = None,
    cohort: str = "",
) -> list[CaseResult]:
    ids = list(case_ids if case_ids is not None else repository.case_ids(split))
    results: list[CaseResult] = []
    for index, case_id in enumerate(ids):
        if policy == "random":
            trials = []
            for repetition in range(repetitions):
                rng = np.random.default_rng(seed + index * 1009 + repetition)
                trials.append(
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
                        decision_version=decision_version,
                        hypotheses_generator=hypotheses_generator,
                        open_world_model=open_world_model,
                        calibrator=calibrator,
                        cohort=cohort,
                    )
                )
            results.append(_average_repeats(trials, cohort=cohort))
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
                    decision_version=decision_version,
                    hypotheses_generator=hypotheses_generator,
                    open_world_model=open_world_model,
                    calibrator=calibrator,
                    cohort=cohort,
                )
            )
    return results


def _average_repeats(results: Sequence[CaseResult], *, cohort: str = "") -> CaseResult:
    base = results[0]
    return CaseResult(
        case_id=base.case_id,
        policy=base.policy,
        split=base.split,
        true_id=base.true_id,
        # A stochastic policy has no single molecular top-1 answer.
        top1_id="",
        top1_id_defined=False,
        top1_correct=float(np.mean([r.top1_correct for r in results])),
        top3_correct=float(np.mean([r.top3_correct for r in results])),
        reciprocal_rank=float(np.mean([r.reciprocal_rank for r in results])),
        status="MIXED" if len({r.status for r in results}) > 1 else base.status,
        accepted=float(np.mean([r.accepted for r in results])),
        correct_accepted=float(np.mean([r.correct_accepted for r in results])),
        false_id=float(np.mean([r.false_id for r in results])),
        accepted_any=float(np.mean([r.accepted_any for r in results])),
        correct_any=float(np.mean([r.correct_any for r in results])),
        false_id_any=float(np.mean([r.false_id_any for r in results])),
        mass_only=float(np.mean([r.mass_only for r in results])),
        confidence=float(np.mean([r.confidence for r in results])),
        fit=float(np.mean([r.fit for r in results])),
        extra_scans=float(np.mean([r.extra_scans for r in results])),
        actions=sorted({action for r in results for action in r.actions}),
        n_candidates=base.n_candidates,
        precursor_ambiguous=base.precursor_ambiguous,
        formula_collision=base.formula_collision,
        proof_level=base.proof_level,
        trials=[r.metrics() for r in results],
        cohort=cohort or base.cohort,
    )


def bootstrap_ci(
    values: Iterable[float], *, resamples: int = 2000, seed: int = 20261021
) -> tuple[float, float, float]:
    array = np.asarray(list(values), float)
    if array.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    means = np.empty(resamples)
    for index in range(resamples):
        sample = rng.choice(array, size=array.size, replace=True)
        means[index] = sample.mean()
    return float(array.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def wilson_interval(successes: float, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return p, centre - half, centre + half


def mcnemar_test(a: Sequence[CaseResult], b: Sequence[CaseResult]) -> dict:
    """Exact-ish McNemar test on paired top-1 correctness."""
    by_id_b = {r.case_id: r for r in b}
    pairs = [(r, by_id_b[r.case_id]) for r in a if r.case_id in by_id_b]
    a_correct = np.array([r.top1_correct >= 0.5 for r, _ in pairs])
    b_correct = np.array([r.top1_correct >= 0.5 for _, r in pairs])
    b_only = int(np.sum(~a_correct & b_correct))
    a_only = int(np.sum(a_correct & ~b_correct))
    n = a_only + b_only
    if n == 0:
        p_value = 1.0
    else:
        # Two-sided binomial McNemar (exact).
        from math import comb

        tail = sum(comb(n, k) for k in range(0, min(a_only, b_only) + 1)) / 2**n
        p_value = float(min(1.0, 2 * tail))
    return {
        "n_pairs": len(pairs),
        "discordant_a_only": a_only,
        "discordant_b_only": b_only,
        "p_value_two_sided": p_value,
    }


def summarize(
    results: Sequence[CaseResult], *, resamples: int = 2000, seed: int = 20261021
) -> dict:
    n = len(results)
    if n == 0:
        return {"n": 0, "cohort": ""}
    top1 = np.array([r.top1_correct for r in results], float)
    top3 = np.array([r.top3_correct for r in results], float)
    mrr = np.array([r.reciprocal_rank for r in results], float)
    scans = np.array([r.extra_scans for r in results], float)
    accepted = np.array([r.accepted for r in results], float)
    correct_accepted = np.array([r.correct_accepted for r in results], float)
    false_id = np.array([r.false_id for r in results], float)
    accepted_any = np.array([r.accepted_any for r in results], float)
    correct_any = np.array([r.correct_any for r in results], float)
    false_any = np.array([r.false_id_any for r in results], float)
    mean, low, high = bootstrap_ci(top1, resamples=resamples, seed=seed)
    coverage = float(accepted.mean())
    coverage_any = float(accepted_any.mean())

    def _rate(values: np.ndarray, denom: float) -> float:
        return float(values.sum() / denom) if denom > 0 else 0.0

    return {
        "n": n,
        "cohort": results[0].cohort,
        "splits": sorted({r.split for r in results}),
        # Retrieval: always defined.
        "top1_accuracy": mean,
        "top1_ci_low": low,
        "top1_ci_high": high,
        "top3_accuracy": float(top3.mean()),
        "mrr": float(mrr.mean()),
        "mean_extra_scans": float(scans.mean()),
        # Strict MS/MS-verified acceptance.
        "msms_accepted_coverage": coverage,
        "msms_accepted_accuracy": _rate(correct_accepted, accepted.sum()),
        "msms_false_id_rate_at_coverage": _rate(false_id, accepted.sum()),
        "msms_selective_risk": _rate(false_id, n),
        # Any acceptance (includes mass-only).
        "accepted_coverage": coverage_any,
        "accepted_accuracy": _rate(correct_any, accepted_any.sum()),
        "false_id_rate_at_coverage": _rate(false_any, accepted_any.sum()),
        "selective_risk": _rate(false_any, n),
        "mass_only_fraction": _rate(
            np.array([r.mass_only for r in results], float), n
        ),
        "abstention_rate": _rate(
            np.array(
                [int(r.status not in ACCEPTED) for r in results], float
            ),
            n,
        ),
        "status_counts": {
            status: sum(1 for r in results if r.status == status)
            for status in sorted({r.status for r in results})
        },
        "proof_tier_counts": {
            tier: sum(1 for r in results if r.proof_level == tier)
            for tier in sorted({r.proof_level for r in results})
        },
    }


def risk_coverage_curve(results: Sequence[CaseResult]) -> dict:
    """Corrected risk–coverage curve.

    Sorts **every** case by confidence and reports the hypothetical error rate
    if the system accepted the top-k.  This is the curve v2 should have drawn:
    abstained cases are not silently excluded.
    """
    ordered = sorted(results, key=lambda r: (-r.confidence, r.case_id))
    errors = np.array([r.error for r in ordered], float)
    cumulative = np.cumsum(errors) / np.arange(1, len(ordered) + 1)
    coverage = np.arange(1, len(ordered) + 1) / max(len(ordered), 1)
    return {
        "coverage": coverage.tolist(),
        "risk": cumulative.tolist(),
        "n": len(ordered),
    }


def accepted_risk_coverage_curve(results: Sequence[CaseResult]) -> dict:
    """Empirical risk among accepted cases only (descriptive, not a guarantee)."""
    accepted = [r for r in results if r.accepted_any >= 0.5]
    if not accepted:
        return {"coverage": [], "risk": [], "n": 0}
    ordered = sorted(accepted, key=lambda r: (-r.confidence, r.case_id))
    false = np.array([r.false_id_any for r in ordered], float)
    cumulative = np.cumsum(false) / np.arange(1, len(ordered) + 1)
    coverage = np.arange(1, len(ordered) + 1) / max(len(ordered), 1)
    return {
        "coverage": coverage.tolist(),
        "risk": cumulative.tolist(),
        "n": len(ordered),
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
        "mcnemar": mcnemar_test(results_a, results_b),
    }


def write_benchmark(
    policy_results: dict[str, list[CaseResult]],
    *,
    split: str,
    output_dir: Path = REPORTS,
    resamples: int = 2000,
    cohort: str = "",
    title: str = "SpectraPilot benchmark",
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = {
        policy: summarize(results, resamples=resamples)
        for policy, results in policy_results.items()
    }
    comparisons = {}
    reference = (
        "always_cid40" if "always_cid40" in policy_results else next(iter(policy_results))
    )
    for policy, results in policy_results.items():
        if policy == reference:
            continue
        comparisons[policy] = paired_comparison(
            results, policy_results[reference], resamples=resamples
        )
    payload = {
        "title": title,
        "split": split,
        "cohort": cohort,
        "reference_policy": reference,
        "policies": summaries,
        "paired_vs_reference": comparisons,
        "risk_coverage": {
            policy: risk_coverage_curve(results)
            for policy, results in policy_results.items()
        },
        "accepted_risk_coverage": {
            policy: accepted_risk_coverage_curve(results)
            for policy, results in policy_results.items()
        },
        "rows": [r.metrics() for results in policy_results.values() for r in results],
        "random_trials": [
            trial
            for results in policy_results.values()
            for row in results
            for trial in row.trials
        ],
    }
    (output_dir / "benchmark.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(payload, output_dir / "benchmark.md")
    _write_plots(policy_results, summaries, output_dir)
    return payload


def _write_markdown(payload: dict, path: Path) -> None:
    lines = [
        f"# {payload.get('title', 'SpectraPilot benchmark')} — {payload['split']} split",
        "",
        f"**Cohort:** `{payload.get('cohort') or 'all'}` · **n = "
        f"{next(iter(payload['policies'].values()))['n']}**",
        "",
        "All policies use the same candidate universe, the same scorer and the same "
        "frozen templates. The random policy is averaged over seeded repetitions; "
        "its molecular top-1 is undefined and per-trial rows are retained. The "
        "hindsight policy uses truth to choose an action and is a diagnostic ceiling "
        "only.",
        "",
        "| Policy | n | Top-1 | 95% CI | Scans | MS/MS cov. | MS/MS acc. | MS/MS false-ID | Any cov. | Mass-only |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for policy, item in payload["policies"].items():
        lines.append(
            f"| {policy} | {item['n']} | {item['top1_accuracy']:.3f} | "
            f"[{item['top1_ci_low']:.3f}, {item['top1_ci_high']:.3f}] | "
            f"{item['mean_extra_scans']:.2f} | {item['msms_accepted_coverage']:.3f} | "
            f"{item['msms_accepted_accuracy']:.3f} | "
            f"{item['msms_false_id_rate_at_coverage']:.3f} | "
            f"{item['accepted_coverage']:.3f} | {item['mass_only_fraction']:.3f} |"
        )
    lines += [
        "",
        "`Top-1` is retrieval accuracy on every case. `MS/MS cov.` counts only "
        "`MSMS_SUPPORTED`. `Any cov.` also counts `MASS_ONLY_MATCH`, which is a "
        "unique precursor-consistent library hit and **not** MS/MS confirmation.",
        "",
        "## Paired differences (top-1 retrieval)",
        "",
        f"Reference: `{payload['reference_policy']}`. Bootstrap resamples are by molecule. "
        "McNemar is the exact two-sided test on discordant pairs.",
        "",
        "| Policy | Δ Top-1 | 95% CI | Excludes zero | A-only | B-only | McNemar p |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for policy, item in payload["paired_vs_reference"].items():
        mc = item.get("mcnemar", {})
        lines.append(
            f"| {policy} | {item['mean_delta']:+.3f} | "
            f"[{item['ci_low']:+.3f}, {item['ci_high']:+.3f}] | "
            f"{'yes' if item['excludes_zero'] else 'no'} | "
            f"{item['discordant_a_correct_b_wrong']} | "
            f"{item['discordant_a_wrong_b_correct']} | "
            f"{mc.get('p_value_two_sided', float('nan')):.3f} |"
        )
    lines += [
        "",
        "## Reading the result",
        "",
        "A positive point estimate is not evidence of an accuracy gain unless the "
        "paired interval excludes zero. If intervals overlap zero, the defensible "
        "claim is cost, coverage, or a case study — not improved identification.",
        "",
        "The risk–coverage curve in `risk_coverage_corrected.png` sorts **every** "
        "case by confidence and reports hypothetical `1 - top1_correct`. v2 drew "
        "the curve from `false_id`, which is zero for every abstained case.",
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
    ax.set_ylabel("top-1 retrieval accuracy")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_dir / "accuracy_vs_scans.png", dpi=180)
    plt.close(fig)

    # Corrected risk-coverage: every case, hypothetical 1 - top1_correct.
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for policy, results in policy_results.items():
        curve = risk_coverage_curve(results)
        ax.plot(curve["coverage"], curve["risk"], label=policy, linewidth=1.5)
    ax.set_xlabel("accepted coverage (all cases sorted by confidence)")
    ax.set_ylabel("hypothetical error 1 - top-1 correct")
    ax.set_ylim(0, 1.0)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(output_dir / "risk_coverage_corrected.png", dpi=180)
    plt.close(fig)

    # Legacy v2 plot kept but renamed so nobody mistakes it for the corrected one.
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for policy, results in policy_results.items():
        curve = accepted_risk_coverage_curve(results)
        if curve["n"]:
            ax.plot(curve["coverage"], curve["risk"], label=policy, linewidth=1.5)
    ax.set_xlabel("accepted coverage (accepted cases only)")
    ax.set_ylabel("false identification rate among accepted")
    ax.set_ylim(0, 1.0)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(output_dir / "risk_coverage_accepted.png", dpi=180)
    plt.close(fig)

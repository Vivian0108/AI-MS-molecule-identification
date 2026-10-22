"""Hard open-world evaluation (SpectraPilot v3, T6).

An unknown compound is simulated by removing the true structure **and every
connectivity/stereo alias of it** from the candidate pool.  That is the hard
version of the problem: the pool still contains plausible precursor-consistent
distractors, so the system cannot succeed by noticing that no candidate shares
the precursor mass.

Two quantities are reported and nothing more:

``auroc`` / ``auprc``
    How well ``1 - calibrated support of the top candidate`` separates unknown
    episodes from in-library episodes.

``false_accept_at_95_in_library_coverage``
    Choose the threshold that keeps 95% of *in-library* episodes accepted, then
    report the fraction of unknown episodes that are still accepted.  This is
    the operational number that matters and it is reported with its n.

A score is only useful if it beats the trivial baseline; the baseline here is
"accept everything", whose unknown detection rate is 0.  No threshold is tuned
on the test split: the operating point comes from the in-library *development*
split and is then applied unchanged to test, which is stated in the report.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

import numpy as np
import pandas as pd

from spectrapilot.data.repository import Case, CaseRepository
from spectrapilot.evaluation.runner import run_policy, NullLog
from spectrapilot.evaluation.truth import EvaluatorStore
from spectrapilot.planning.oracle import OracleStore
from spectrapilot.planning.session import InvestigationSession
from unknownid.core.posterior import rank_candidates


class UnknownPoolRepository:
    """Repository proxy whose candidate pool excludes the truth and its aliases."""

    def __init__(
        self,
        base: CaseRepository,
        truth: EvaluatorStore,
        *,
        case_ids: Sequence[str] | None = None,
    ) -> None:
        self.base = base
        self.truth = truth
        self.references = base.references
        self._case_ids = list(case_ids) if case_ids is not None else None

    def case_ids(self, split: str) -> list[str]:
        ids = self.base.case_ids(split)
        if self._case_ids is None:
            return ids
        allowed = set(self._case_ids)
        return [case_id for case_id in ids if case_id in allowed]

    def case(self, case_id: str) -> Case:
        base_case = self.base.case(case_id)
        removed = self.truth.aliases(case_id) | {self.truth.truth(case_id)}
        kept = [cid for cid in base_case.candidate_ids if cid not in removed]
        return replace(base_case, candidate_ids=kept)

    def candidates(self, case_id: str):
        kept = self.case(case_id).candidate_ids
        return [self.references.candidate(cid) for cid in kept if cid in self.references.candidate_ids]


@dataclass
class OpenWorldRow:
    case_id: str
    split: str
    condition: str  # "in_library" | "hard_unknown"
    n_pool: int
    top1_id: str
    support: float
    best_fit: float
    absolute_score: float
    relative_score: float
    unknown_score: float
    accepted: float
    status: str

    def public_dict(self) -> dict:
        return self.__dict__


def _run(
    case_ids: Sequence[str],
    *,
    repository,
    oracle: OracleStore,
    truth: EvaluatorStore,
    scorer,
    planner,
    action: str,
    decision_version: str = "v3",
    calibrator=None,
    cohort: str = "",
) -> list[OpenWorldRow]:
    rows: list[OpenWorldRow] = []
    for case_id in case_ids:
        pool = repository.case(case_id).candidate_ids
        if not pool:
            continue
        session = InvestigationSession(
            case_id,
            repository,
            __import__("spectrapilot.planning.oracle", fromlist=["VirtualInstrument"]).VirtualInstrument(oracle),
            scorer,
            planner,
            action_log=NullLog(),
            budget=1,
            decision_version=decision_version,
            calibrator=calibrator,
        )
        available = {item.key for item in session.instrument.available_actions(case_id)}
        if action in available:
            session.measure(action)
        investigation = session.stop()
        evidence = investigation.candidate_evidence
        if not evidence:
            continue
        top = str(evidence[0]["candidate_id"])
        support = float(evidence[0]["relative_weight"] or evidence[0]["weight"])
        # Absolute fit: the best cosine reached by *any* candidate.  A softmax
        # support always sums to one and therefore cannot say "nothing fits";
        # the maximum fit is the quantity that can.
        best_fit = 0.0
        unexplained = 1.0
        for item in evidence:
            similarity = item.get("similarity_by_action") or {}
            if similarity:
                best_fit = max(best_fit, float(max(similarity.values())))
            values = item.get("unexplained_intensity_by_action") or {}
            if values:
                unexplained = min(unexplained, float(min(values.values())))
        absolute_score = float(1.0 - best_fit)
        relative_score = float(1.0 - support)
        rows.append(
            OpenWorldRow(
                case_id=case_id,
                split=truth.split(case_id),
                condition=cohort,
                n_pool=len(pool),
                top1_id=top,
                support=support,
                best_fit=best_fit,
                absolute_score=absolute_score,
                relative_score=relative_score,
                unknown_score=absolute_score,
                accepted=float(investigation.decision in {"MSMS_SUPPORTED", "MASS_ONLY_MATCH"}),
                status=investigation.decision,
            )
        )
    return rows


def _auc(scores: np.ndarray, labels: np.ndarray) -> tuple[float | None, float | None]:
    """AUROC/AUPRC where label 1 = unknown."""
    if len(set(labels.tolist())) < 2:
        return None, None
    from sklearn.metrics import average_precision_score, roc_auc_score

    return float(roc_auc_score(labels, scores)), float(average_precision_score(labels, scores))


def evaluate_open_world(
    repository: CaseRepository,
    oracle: OracleStore,
    truth: EvaluatorStore,
    *,
    scorer,
    planner,
    action: str = "CID40",
    decision_version: str = "v3",
    calibrator=None,
    threshold_split: str = "dev",
    evaluate_split: str = "test",
) -> tuple[pd.DataFrame, dict]:
    """Score in-library vs hard-unknown episodes with an honest operating point."""
    in_lib_dev = _run(
        repository.case_ids(threshold_split),
        repository=repository,
        oracle=oracle,
        truth=truth,
        scorer=scorer,
        planner=planner,
        action=action,
        decision_version=decision_version,
        calibrator=calibrator,
        cohort="in_library",
    )
    unknown_dev_repo = UnknownPoolRepository(
        repository, truth, case_ids=repository.case_ids(threshold_split)
    )
    unknown_dev = _run(
        repository.case_ids(threshold_split),
        repository=unknown_dev_repo,
        oracle=oracle,
        truth=truth,
        scorer=scorer,
        planner=planner,
        action=action,
        decision_version=decision_version,
        calibrator=calibrator,
        cohort="hard_unknown",
    )
    # Choose the detection score on the development split, never on test.
    dev_scores = {}
    for name in ("absolute_score", "relative_score"):
        scores_dev = np.array(
            [getattr(row, name) for row in in_lib_dev + unknown_dev], float
        )
        labels_dev = np.array(
            [1 if row.condition == "hard_unknown" else 0 for row in in_lib_dev + unknown_dev],
            float,
        )
        dev_scores[name] = _auc(scores_dev, labels_dev)[0]
    usable = {name: value for name, value in dev_scores.items() if value is not None}
    selected = max(usable, key=usable.get) if usable else "absolute_score"
    threshold = float(
        np.quantile([getattr(row, selected) for row in in_lib_dev], 0.95)
    )

    in_lib = _run(
        repository.case_ids(evaluate_split),
        repository=repository,
        oracle=oracle,
        truth=truth,
        scorer=scorer,
        planner=planner,
        action=action,
        decision_version=decision_version,
        calibrator=calibrator,
        cohort="in_library",
    )
    unknown_repo = UnknownPoolRepository(repository, truth, case_ids=repository.case_ids(evaluate_split))
    unknown = _run(
        repository.case_ids(evaluate_split),
        repository=unknown_repo,
        oracle=oracle,
        truth=truth,
        scorer=scorer,
        planner=planner,
        action=action,
        decision_version=decision_version,
        calibrator=calibrator,
        cohort="hard_unknown",
    )
    frame = pd.DataFrame([row.public_dict() for row in in_lib + unknown])
    scores = np.array([getattr(row, selected) for row in in_lib + unknown], float)
    labels = np.array(
        [1 if row.condition == "hard_unknown" else 0 for row in in_lib + unknown], float
    )
    auroc, auprc = _auc(scores, labels)
    in_lib_accept = (
        float(np.mean([getattr(row, selected) <= threshold for row in in_lib])) if in_lib else 0.0
    )
    unknown_accept = (
        float(np.mean([getattr(row, selected) <= threshold for row in unknown]))
        if unknown
        else 0.0
    )
    summary = {
        "action": action,
        "n_in_library": len(in_lib),
        "n_hard_unknown": len(unknown),
        "selected_score": selected,
        "score_selection": f"chosen on {threshold_split} by AUROC; {dev_scores}",
        "threshold": threshold,
        "threshold_source": f"{threshold_split} in-library 95th percentile of {selected}",
        "auroc": auroc,
        "auprc": auprc,
        "in_library_false_accept_rate": float(1.0 - in_lib_accept),
        "unknown_false_accept_rate": unknown_accept,
        "unknown_detection_rate": float(1.0 - unknown_accept),
        "median_score_in_library": float(
            np.median([getattr(row, selected) for row in in_lib]) if in_lib else 0.0
        ),
        "median_score_unknown": float(
            np.median([getattr(row, selected) for row in unknown]) if unknown else 0.0
        ),
        "dev_auroc_by_score": dev_scores,
        "claim": (
            "A hard-unknown episode removes the truth and its aliases but keeps "
            "precursor-consistent distractors. The relative softmax support is "
            "useless here (it always sums to one); the absolute fit of the best "
            "candidate is the usable signal. The score and its threshold are "
            "chosen on the development split and applied unchanged to test."
        ),
    }
    return frame, summary

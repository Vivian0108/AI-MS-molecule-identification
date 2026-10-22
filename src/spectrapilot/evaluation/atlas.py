"""Failure atlas and oracle-ceiling diagnosis (SpectraPilot v3, P1).

The question this module answers is **not** "how do we get more accuracy?" but
"where does the residual error live?".  Three ceilings are separated:

``action ceiling``
    Best extra action chosen with evaluator truth (``hindsight_best``).  Shows
    how much is lost purely by not knowing which experiment to run.

``measured-template ceiling``
    Every candidate is scored against **its own measured** spectrum for the
    action, taken from the curation table and used only here.  If this ceiling is
    near 1.0, the observations contain enough information and the gap is
    template/model-limited.  If it stays low, the ambiguity is chemical.

``same-formula ceiling``
    The measured-template ceiling restricted to cases whose candidate pool
    contains two or more structures with the same formula — the ambiguity class
    that formula-level evidence can never resolve.

Every ceiling is marked ``diagnostic_only`` and no ceiling value is ever used by
the deployed system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from spectrapilot.data.repository import CaseRepository
from spectrapilot.evaluation.runner import CaseResult, NullLog, run_policy_case
from spectrapilot.evaluation.truth import EvaluatorStore
from spectrapilot.models import Template
from spectrapilot.paths import CURATED
from spectrapilot.planning.oracle import OracleStore
from spectrapilot.planning.separation import SeparationPlanner
from spectrapilot.planning.session import InvestigationSession
from spectrapilot.science.scoring import LegacyCosineScorer
from spectrapilot.science.templates import ReferenceStore

FAILURE_CLASSES: dict[str, str] = {
    "A": "Action-choice failure — exactly one extra action would have identified the truth.",
    "B": "Evidence-fusion failure — a correct single-action result is lost when evidence is combined.",
    "C": "Template failure — predicted templates fit too poorly, while a measured-template oracle would succeed.",
    "D": "Unresolvable chemical ambiguity — the observations do not separate the candidate pool.",
    "E": "Connectivity-equivalent / isomer ambiguity — competitors share the molecular skeleton.",
    "F": "Status failure — retrieval is right but the decision contract rejects it, or a wrong identity is accepted.",
    "RECOVERED": "Not a failure: the system retrieves the truth and accepts it.",
}

ATLAS_COLUMNS = [
    "case_id",
    "split",
    "n_candidates",
    "precursor_ambiguous",
    "same_formula_competitors",
    "connectivity_equivalent_competitors",
    "true_id",
    "initial_top1",
    "initial_correct",
    "initial_status",
    "initial_support",
    "initial_fit",
    "cid40_top1",
    "cid40_correct",
    "cid40_status",
    "ead16_top1",
    "ead16_correct",
    "ead16_status",
    "combined_top1",
    "combined_correct",
    "combined_status",
    "any_single_action_correct",
    "best_action_correct",
    "policy_top1",
    "policy_correct",
    "policy_status",
    "policy_false_id",
    "oracle_measured_correct",
    "measured_separability",
    "predicted_separability",
    "template_fidelity",
    "best_distractor_measured_cosine",
    "truth_template_reliability",
    "truth_template_source",
    "failure_class",
    "failure_detail",
    "status_subclass",
]


class MeasuredTemplateStore:
    """Evaluator-only template store built from each candidate's own measurement.

    This is an *oracle ceiling*: it answers "would perfect template prediction
    have identified the compound?"  It must never be handed to a deployable
    session.
    """

    diagnostic_only = True

    def __init__(self, records: pd.DataFrame, *, ppm_tolerance: float = 10.0) -> None:
        self.ppm_tolerance = float(ppm_tolerance)
        self._templates: dict[tuple[str, str], Template] = {}
        for row in records.itertuples(index=False):
            candidate_id = str(row.compound_full_inchikey)
            action = str(row.action)
            if action not in {"CID20", "CID40", "EAD16"}:
                continue
            self._templates[(candidate_id, action)] = Template(
                candidate_id=candidate_id,
                action=action,
                mz=np.asarray(row.peaks_mz, float),
                intensity=np.asarray(row.peaks_intensity, float),
                source="evaluator_measured_oracle",
                reliability=1.0,
                n_donors=1,
                mean_similarity=1.0,
                expected_energy_ev=float(row.energy_value),
            )

    def template(self, candidate_id: str, action: str) -> Template:
        return self._templates[(candidate_id, action)]

    def templates_for_action(self, action: str) -> list[Template]:
        return [t for (cid, act), t in self._templates.items() if act == action]

    @property
    def candidate_ids(self) -> set[str]:
        return {cid for cid, _ in self._templates}


@dataclass
class ActionOutcome:
    top1: str
    correct: float
    status: str
    support: float
    fit: float


def _outcomes_for_case(
    case_id: str,
    *,
    repository: CaseRepository,
    oracle: OracleStore,
    truth: EvaluatorStore,
    scorer,
    planner: SeparationPlanner,
    decision_version: str = "v3",
) -> dict[str, ActionOutcome]:
    """Run CID20-only, CID40-only, EAD16-only and both-action branches."""
    from spectrapilot.planning.oracle import VirtualInstrument

    outcomes: dict[str, ActionOutcome] = {}

    def branch(actions: Sequence[str], key: str) -> None:
        instrument = VirtualInstrument(oracle)
        session = InvestigationSession(
            case_id,
            repository,
            instrument,
            scorer,
            planner,
            action_log=NullLog(),
            budget=max(1, len(actions)),
            decision_version=decision_version,
        )
        available = {action.key for action in instrument.available_actions(case_id)}
        for action in actions:
            if action in available:
                session.measure(action)
        investigation = session.stop()
        evidence = investigation.candidate_evidence
        top1 = str(evidence[0]["candidate_id"]) if evidence else ""
        support = float(evidence[0]["relative_weight"] or evidence[0]["weight"]) if evidence else 0.0
        fit = (
            float(max(evidence[0]["similarity_by_action"].values(), default=0.0))
            if evidence
            else 0.0
        )
        outcomes[key] = ActionOutcome(
            top1=top1,
            correct=float(top1 == truth.truth(case_id)),
            status=investigation.decision,
            support=support,
            fit=fit,
        )

    branch([], "initial")
    branch(["CID40"], "cid40")
    branch(["EAD16"], "ead16")
    branch(["CID40", "EAD16"], "combined")
    return outcomes


def _pool_diagnostics(
    case_id: str,
    *,
    repository: CaseRepository,
    oracle: OracleStore,
    truth: EvaluatorStore,
    measured: MeasuredTemplateStore,
    scorer,
) -> dict:
    """How separable is the pool, with perfect vs predicted templates?

    For each available action we compare the **observed** spectrum against

    * every candidate's *measured* spectrum at the same action (perfect template
      prediction), and
    * every candidate's *predicted* template (what the system actually uses).

    ``measured_separability`` is the cosine gap between the truth and its
    strongest competitor under perfect templates.  A near-zero gap means the
    observation cannot separate the pool even with a perfect predictor, which is
    a chemical limit, not a modelling failure.
    """
    from unknownid.core.spectra import cosine_greedy

    true_id = truth.truth(case_id)
    hidden = oracle.evaluator_hidden(case_id)
    candidates = repository.candidates(case_id)
    result = {
        "measured_separability": None,
        "predicted_separability": None,
        "template_fidelity": None,
        "best_distractor_measured_cosine": None,
        "actions_checked": [],
    }
    best_measured: float | None = None
    best_predicted: float | None = None
    best_fidelity: float | None = None

    for action in ("CID40", "EAD16"):
        payload = hidden.get(action)
        if not payload:
            continue
        observed_mz = np.asarray(payload["peaks_mz"], float)
        observed_intensity = np.asarray(payload["peaks_intensity"], float)
        keep = observed_intensity >= 0.01
        if keep.sum() < 2:
            continue
        observed_mz, observed_intensity = observed_mz[keep], observed_intensity[keep]

        measured_sims: dict[str, float] = {}
        predicted_sims: dict[str, float] = {}
        for candidate in candidates:
            try:
                template = measured.template(candidate.molecule_id, action)
                measured_sims[candidate.molecule_id] = cosine_greedy(
                    observed_mz, observed_intensity, template.mz, template.intensity, 0.02
                )[0]
            except KeyError:
                pass
            try:
                template = repository.references.template(candidate.molecule_id, action)
                predicted_sims[candidate.molecule_id] = cosine_greedy(
                    observed_mz, observed_intensity, template.mz, template.intensity, 0.02
                )[0]
            except KeyError:
                pass

        if true_id in measured_sims and len(measured_sims) > 1:
            distractor = max(
                (value for cid, value in measured_sims.items() if cid != true_id),
                default=0.0,
            )
            separability = float(measured_sims[true_id] - distractor)
            if best_measured is None or separability > best_measured:
                best_measured = separability
                result["best_distractor_measured_cosine"] = float(distractor)
        if true_id in predicted_sims:
            fidelity = float(predicted_sims[true_id])
            if best_fidelity is None or fidelity > best_fidelity:
                best_fidelity = fidelity
        if true_id in predicted_sims and len(predicted_sims) > 1:
            distractor = max(
                (value for cid, value in predicted_sims.items() if cid != true_id),
                default=0.0,
            )
            separability = float(predicted_sims[true_id] - distractor)
            if best_predicted is None or separability > best_predicted:
                best_predicted = separability
        result["actions_checked"].append(action)

    result["measured_separability"] = best_measured
    result["predicted_separability"] = best_predicted
    result["template_fidelity"] = best_fidelity
    return result


def _competitor_counts(
    repository: CaseRepository, case_id: str
) -> tuple[int, int]:
    case = repository.case(case_id)
    candidates = repository.candidates(case_id)
    formulas: dict[str, int] = {}
    connectivity: dict[str, int] = {}
    for candidate in candidates:
        formulas[candidate.formula] = formulas.get(candidate.formula, 0) + 1
        connectivity[candidate.connectivity_key] = connectivity.get(candidate.connectivity_key, 0) + 1
    same_formula = max(formulas.values()) if formulas else 1
    same_connectivity = max(connectivity.values()) if connectivity else 1
    return int(same_formula), int(same_connectivity)


def _status_subclass(row: dict) -> str:
    """Separate a wrong acceptance from a conservative abstention.

    A correct top-1 followed by an abstention is a *coverage* outcome, not
    automatically a decision bug; the report keeps the two apart.
    """
    if row["policy_false_id"]:
        return "false_identification"
    if row["policy_correct"] and not row["policy_accepted"]:
        if row["policy_status"] == "INSUFFICIENT_DATA":
            return "insufficient_data"
        return "abstained_after_correct_retrieval"
    if row["policy_correct"]:
        return "recovered"
    return "retrieval_error"


def classify_failure(row: dict) -> tuple[str, str]:
    """Deterministic A–F taxonomy.  Order matters and is documented in the report."""
    if row["policy_false_id"]:
        return "F", "wrong identity accepted at the decision stage"
    if row["policy_correct"] and not row["policy_accepted"]:
        return "F", "top-1 correct but the decision contract abstained"
    if row["policy_correct"]:
        return "RECOVERED", "retrieved and accepted"
    # The deployed sequence failed to retrieve the truth.  Diagnose why.
    if row["combined_correct"]:
        return "A", "evidence fusion ranks the truth first, but the selected action sequence did not"
    singles_correct = int(row["cid40_correct"]) + int(row["ead16_correct"])
    if singles_correct == 1:
        return "A", "exactly one extra action ranks the truth first"
    if singles_correct >= 2:
        return "B", "both single actions rank the truth first but fusion does not"
    if row["connectivity_equivalent_competitors"] > 1 and (row["measured_separability"] or 0) < 0.10:
        return "E", "competitors share the molecular skeleton and measured spectra are not separable"
    if row["same_formula_competitors"] > 1 and (row["measured_separability"] or 0) < 0.10:
        return "D", "isomeric structures whose measured spectra are not separable"
    if (row["template_fidelity"] is not None and row["template_fidelity"] < 0.30
            and (row["measured_separability"] or 0) >= 0.10):
        return "C", "the observation is separable with measured spectra, but the predicted template fits poorly"
    if row["connectivity_equivalent_competitors"] > 1:
        return "E", "competitors share the molecular skeleton"
    if row["same_formula_competitors"] > 1:
        return "D", "candidate pool contains isomeric structures"
    return "D", "no single action or perfect template recovers the truth"


def build_atlas(
    repository: CaseRepository,
    oracle: OracleStore,
    truth: EvaluatorStore,
    *,
    split: str = "test",
    case_ids: Sequence[str] | None = None,
    scorer=None,
    planner: SeparationPlanner | None = None,
    decision_version: str = "v3",
    calibrator=None,
    records_path: Path | None = None,
    progress: bool = False,
) -> tuple[pd.DataFrame, dict]:
    from spectrapilot.planning.oracle import VirtualInstrument

    scorer = scorer or LegacyCosineScorer()
    planner = planner or SeparationPlanner()
    ids = list(case_ids if case_ids is not None else repository.case_ids(split))
    records = pd.read_parquet(records_path or (CURATED / "records.parquet"))
    measured = MeasuredTemplateStore(records, ppm_tolerance=repository.references.ppm_tolerance)

    rows: list[dict] = []
    for index, case_id in enumerate(ids):
        outcomes = _outcomes_for_case(
            case_id,
            repository=repository,
            oracle=oracle,
            truth=truth,
            scorer=scorer,
            planner=planner,
            decision_version=decision_version,
        )
        # Deployable policy row: the v3 decision planner is evaluated separately;
        # here "policy" is the adaptive separation branch so the atlas can compare
        # like with like across actions.
        policy_result = run_policy_case(
            case_id,
            "separation",
            repository=repository,
            oracle=oracle,
            truth=truth,
            scorer=scorer,
            planner=planner,
            budget=1,
            decision_version=decision_version,
            calibrator=calibrator,
            cohort=split,
        )
        oracle_correct = _pool_diagnostics(
            case_id,
            repository=repository,
            oracle=oracle,
            truth=truth,
            measured=measured,
            scorer=scorer,
        )
        same_formula, same_connectivity = _competitor_counts(repository, case_id)
        true_id = truth.truth(case_id)
        try:
            truth_template = repository.references.template(true_id, "CID40")
            reliability = float(truth_template.reliability)
            source = truth_template.source
        except KeyError:
            reliability, source = 0.0, "missing"

        singles = [outcomes["cid40"].correct, outcomes["ead16"].correct]
        row = {
            "case_id": case_id,
            "split": split,
            "n_candidates": len(repository.case(case_id).candidate_ids),
            "precursor_ambiguous": bool(repository.case(case_id).precursor_ambiguous),
            "same_formula_competitors": same_formula,
            "connectivity_equivalent_competitors": same_connectivity,
            "true_id": true_id,
            "initial_top1": outcomes["initial"].top1,
            "initial_correct": outcomes["initial"].correct,
            "initial_status": outcomes["initial"].status,
            "initial_support": outcomes["initial"].support,
            "initial_fit": outcomes["initial"].fit,
            "cid40_top1": outcomes["cid40"].top1,
            "cid40_correct": outcomes["cid40"].correct,
            "cid40_status": outcomes["cid40"].status,
            "ead16_top1": outcomes["ead16"].top1,
            "ead16_correct": outcomes["ead16"].correct,
            "ead16_status": outcomes["ead16"].status,
            "combined_top1": outcomes["combined"].top1,
            "combined_correct": outcomes["combined"].correct,
            "combined_status": outcomes["combined"].status,
            "any_single_action_correct": float(any(value >= 0.5 for value in singles)),
            "best_action_correct": float(any(value >= 0.5 for value in singles)),
            "any_two_correct": float(sum(value >= 0.5 for value in singles) >= 2),
            "policy_top1": policy_result.top1_id,
            "policy_correct": policy_result.top1_correct,
            "policy_status": policy_result.status,
            "policy_accepted": policy_result.accepted_any,
            "policy_false_id": policy_result.false_id_any,
            "oracle_measured_correct": (
                float(oracle_correct["measured_separability"] >= 0.10)
                if oracle_correct["measured_separability"] is not None
                else float("nan")
            ),
            "measured_separability": oracle_correct["measured_separability"],
            "predicted_separability": oracle_correct["predicted_separability"],
            "template_fidelity": oracle_correct["template_fidelity"],
            "best_distractor_measured_cosine": oracle_correct[
                "best_distractor_measured_cosine"
            ],
            "truth_template_reliability": reliability,
            "truth_template_source": source,
        }
        row["failure_class"], row["failure_detail"] = classify_failure(row)
        row["status_subclass"] = _status_subclass(row)
        rows.append(row)
        if progress and (index + 1) % 25 == 0:
            print(f"  atlas {index + 1}/{len(ids)}")

    frame = pd.DataFrame(rows)
    summary = summarize_atlas(frame)
    return frame, summary


def summarize_atlas(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {}
    counts = frame["failure_class"].value_counts().to_dict()
    same_formula = frame[frame["same_formula_competitors"] > 1]
    multi = frame[frame["n_candidates"] > 1]
    failures = frame[frame["failure_class"] != "RECOVERED"]
    sep = frame["measured_separability"].dropna()
    fidelity = frame["template_fidelity"].dropna()
    failing_sep = failures["measured_separability"].dropna()
    failing_fidelity = failures["template_fidelity"].dropna()
    return {
        "n": int(len(frame)),
        "diagnostic_only": True,
        "failure_counts": {key: int(counts.get(key, 0)) for key in FAILURE_CLASSES},
        "failure_share": {
            key: float(counts.get(key, 0) / len(frame)) for key in FAILURE_CLASSES
        },
        "retrieval_top1_initial": float(frame["initial_correct"].mean()),
        "retrieval_top1_cid40": float(frame["cid40_correct"].mean()),
        "retrieval_top1_ead16": float(frame["ead16_correct"].mean()),
        "retrieval_top1_combined": float(frame["combined_correct"].mean()),
        "retrieval_top1_policy": float(frame["policy_correct"].mean()),
        "action_ceiling": float(frame["best_action_correct"].mean()),
        # Pool separability under perfect (measured) templates.
        "pool_separable_share": float((sep >= 0.10).mean()) if len(sep) else 0.0,
        "median_measured_separability": float(sep.median()) if len(sep) else 0.0,
        "median_measured_separability_same_formula": (
            float(same_formula["measured_separability"].dropna().median())
            if not same_formula.empty
            else 0.0
        ),
        "median_template_fidelity": float(fidelity.median()) if len(fidelity) else 0.0,
        "n_same_formula_multi": int(len(same_formula)),
        "n_multi_candidate": int(len(multi)),
        # Decomposition of the residual failures.
        "failures_with_information_present": int(
            sum(
                1
                for _, row in failures.iterrows()
                if (row["measured_separability"] or 0) >= 0.10
                and row["template_fidelity"] is not None
                and row["template_fidelity"] < 0.30
            )
        ),
        "failures_chemistry_limited": int(
            sum(
                1
                for _, row in failures.iterrows()
                if (row["measured_separability"] or 0) < 0.10
            )
        ),
        "n_failures": int(len(failures)),
        "status_subclass_counts": (
            {k: int(v) for k, v in frame["status_subclass"].value_counts().items()}
            if "status_subclass" in frame
            else {}
        ),
        "median_failing_template_fidelity": (
            float(failing_fidelity.median()) if len(failing_fidelity) else 0.0
        ),
        "median_failing_measured_separability": (
            float(failing_sep.median()) if len(failing_sep) else 0.0
        ),
        "cid40_reference_share": float(
            (frame["truth_template_source"] == "reference_cid60").mean()
        ),
        "cid40_template_reliability_median": float(
            frame["truth_template_reliability"].median()
        ),
    }


def write_atlas(
    frame: pd.DataFrame,
    summary: dict,
    output_dir: Path,
    *,
    title: str = "SpectraPilot v3 failure atlas",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output_dir / "failure_atlas.parquet", index=False)
    frame.to_csv(output_dir / "failure_atlas.csv", index=False)
    (output_dir / "failure_atlas_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    _plot(frame, output_dir / "failure_atlas.png", title=title)


def _plot(frame: pd.DataFrame, path: Path, *, title: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # pragma: no cover
        return
    counts = frame["failure_class"].value_counts()
    order = [key for key in FAILURE_CLASSES if key in counts.index]
    values = [int(counts[key]) for key in order]
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(order, values, color="#4c72b0")
    for bar, value in zip(bars, values):
        ax.annotate(str(value), (bar.get_x() + bar.get_width() / 2, value), ha="center", va="bottom")
    ax.set_ylabel("cases")
    ax.set_title(title, fontsize=10)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)

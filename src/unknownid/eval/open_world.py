"""Open-world abstention test: remove each true molecule from the library.

A correct system should flag ``out_of_library`` rather than confidently identify
a different compound.  This is a deliberately pessimistic test because the
remaining library can contain close isomers.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from unknownid.core.evidence import EvidenceEvaluator
from unknownid.core.retrieve import ReferenceStore
from unknownid.eval.baselines import EvalCase, PolicyState
from unknownid.eval.evaluate import _case_metrics
from unknownid.eval.metrics import decide
from unknownid.planner.acquisition import AcquisitionPlanner
from unknownid.planner.error_model import ErrorModel


def run_open_world(
    cases: Sequence[EvalCase],
    *,
    references: ReferenceStore,
    evaluator: EvidenceEvaluator,
    error_model: ErrorModel,
    planner: AcquisitionPlanner,
    confidence: dict,
    tempering: float,
) -> dict:
    rows = []
    for case in cases:
        remaining = [cid for cid in case.candidate_ids if cid != case.molecule_id]
        if not remaining:
            rows.append(
                {
                    "case_id": case.case_id,
                    "n_remaining": 0,
                    "decision_20": "out_of_library",
                    "decision_after_action": "out_of_library",
                    "scans": 0,
                    "top_similarity": 0.0,
                }
            )
            continue
        stripped = EvalCase(
            case_id=case.case_id,
            molecule_id=case.molecule_id,
            split=case.split,
            precursor_mz=case.precursor_mz,
            candidate_ids=remaining,
            observations=case.observations,
            candidates=[references.candidate(cid) for cid in remaining],
            templates={cid: case.templates[cid] for cid in remaining},
        )
        state = PolicyState(
            stripped,
            references=references,
            evaluator=evaluator,
            error_model=error_model,
            tempering=tempering,
        )
        initial = _case_metrics(state, case.molecule_id, budget=0, confidence=confidence)
        plan = planner.plan(
            case.case_id,
            weights=state.weights,
            templates=stripped.templates,
            precursors={c.molecule_id: c.precursor_mz for c in stripped.candidates},
            observed_energies=[20],
            remaining_budget=1,
        )
        if plan.recommended.kind == "measure" and plan.recommended.energy_ev is not None:
            state.measure(int(plan.recommended.energy_ev))
        final = _case_metrics(state, case.molecule_id, budget=1, confidence=confidence)
        rows.append(
            {
                "case_id": case.case_id,
                "n_remaining": len(remaining),
                "decision_20": initial["decision"],
                "decision_after_action": final["decision"],
                "scans": final["scans"],
                "top_similarity": final["best_similarity"],
                "predicted": final["predicted"],
            }
        )
    n = len(rows)
    summary = {
        "n": n,
        "out_of_library_at_20": sum(1 for row in rows if row["decision_20"] == "out_of_library"),
        "out_of_library_after_action": sum(
            1 for row in rows if row["decision_after_action"] == "out_of_library"
        ),
        "identified_wrong_library_match": sum(
            1 for row in rows if row["decision_after_action"] == "identified"
        ),
        "ambiguous": sum(1 for row in rows if row["decision_after_action"] == "ambiguous"),
        "mean_scans": float(np.mean([row["scans"] for row in rows])) if rows else 0.0,
        "cases": rows,
        "note": (
            "The true molecule is removed from the candidate library. A confident identification "
            "here is a false library match, not a correct open-world identification."
        ),
    }
    for key in ("out_of_library_at_20", "out_of_library_after_action", "identified_wrong_library_match", "ambiguous"):
        summary[f"{key}_rate"] = summary[key] / n if n else 0.0
    return summary

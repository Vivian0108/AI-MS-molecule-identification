"""Counterfactual evidence and premeasurement diagnostic challenge.

All computations use public reference templates and *already acquired* spectra.
Peak deletion is a sensitivity analysis, not contamination detection or chemical
causation. Reference fingerprints are not fragment-structure assignments.
"""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import numpy as np
from unknownid.core.posterior import rank_candidates

if TYPE_CHECKING:
    from spectrapilot.planning.session import InvestigationSession


def sensitivity_audit(session: "InvestigationSession", action: str = "CID20", limit: int = 12) -> dict:
    """Single-peak leave-one-out stability without editing the saved observation."""
    if action not in session.observed_actions:
        raise ValueError("Only acquired spectra may be challenged")
    original = session.observation(action)
    active = {e.peak_index for e in session._active_exclusions.values() if e.action == action}
    candidates = [
        i for i, (mz, intensity) in enumerate(zip(original.mz, original.intensity))
        if i not in active
        and abs(float(mz) - session.case.precursor_mz) > session.scorer.tolerance_da
        and float(intensity) >= 0.01
    ]
    candidates.sort(key=lambda i: (-float(original.intensity[i]), i))
    baseline_order = rank_candidates(session._weights)
    leader = baseline_order[0] if baseline_order else None
    baseline_support = float(session._weights.get(leader, 0.0)) if leader else 0.0
    rows = []
    for i in candidates[:limit]:
        _, weights = session._score_evidence(mask_edits=True, extra_exclusion=(action, i))
        order = rank_candidates(weights)
        other = order[0] if order else None
        rows.append({
            "original_peak_index": i,
            "mz": round(float(original.mz[i]), 6),
            "relative_intensity": round(float(original.intensity[i]), 6),
            "leader_without_peak": other,
            "top1_changed": other != leader,
            "original_leader_support_without_peak": round(float(weights.get(leader, 0.0)), 6) if leader else 0.0,
            "support_drop": round(baseline_support - float(weights.get(leader, 0.0)), 6) if leader else 0.0,
        })
    rows.sort(key=lambda row: (-int(row["top1_changed"]), -row["support_drop"], -row["relative_intensity"]))
    return {
        "method": "single_peak_leave_one_out",
        "observed_action": action,
        "baseline_leader": leader,
        "baseline_relative_support": round(baseline_support, 6),
        "peaks_tested": len(rows),
        "leader_flip_count": sum(int(row["top1_changed"]) for row in rows),
        "fragile_under_tested_deletions": any(row["top1_changed"] for row in rows),
        "peak_challenges": rows,
        "scientific_limit": "Sensitivity to deleting an acquired peak; not a causal fragment assignment, contamination diagnosis, or calibrated identity probability.",
    }


def _diagnostic_peaks(first, second, precursor: float, tolerance: float, limit: int = 5) -> list[float]:
    selected = []
    for mz, intensity in sorted(
        zip(first.mz, first.intensity), key=lambda x: -float(x[1])
    ):
        mz = float(mz)
        if mz <= 0 or abs(mz - precursor) <= tolerance or float(intensity) < 0.05:
            continue
        if not any(abs(mz - float(value)) <= tolerance for value in second.mz):
            selected.append(round(mz, 5))
        if len(selected) >= limit:
            break
    return selected


def make_precommit(session: "InvestigationSession", action: str) -> dict:
    """Immutable hypothesis constructed without reading the hidden instrument."""
    ordered = rank_candidates(session._weights)[:2]
    predictions = []
    if len(ordered) == 2:
        for first_id, second_id in ((ordered[0], ordered[1]), (ordered[1], ordered[0])):
            try:
                first = session.templates.template(first_id, action)
                second = session.templates.template(second_id, action)
            except KeyError:
                continue
            predictions.append({
                "candidate_id": first_id,
                "against": second_id,
                "template_source": first.source,
                "reference_reliability_proxy": round(float(first.reliability), 5),
                "diagnostic_mz": _diagnostic_peaks(first, second, session.case.precursor_mz, session.scorer.tolerance_da),
            })
    observations = {
        key: {
            "mz": [float(v) for v in session._effective_observation(key).mz],
            "intensity": [float(v) for v in session._effective_observation(key).intensity],
        }
        for key in session.observed_actions
    }
    record = {
        "case_id": session.case_id,
        "action": action,
        "observed_sha256": hashlib.sha256(json.dumps(observations, sort_keys=True).encode()).hexdigest(),
        "candidate_order": ordered,
        "predictions": predictions,
        "method": "template_only_diagnostic_peak_disagreement",
        "scope": "Predicted mass peaks, not bonded fragments or proof of molecule identity",
    }
    record["sha256"] = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return record


def verify_precommit(precommit: dict, measurement, tolerance: float) -> dict:
    if measurement.action != precommit["action"]:
        raise ValueError("Measurement action does not match precommit")
    verdicts = []
    for prediction in precommit["predictions"]:
        expected = prediction["diagnostic_mz"]
        hits = [mz for mz in expected if any(abs(mz - float(obs)) <= tolerance for obs in measurement.mz)]
        verdicts.append({
            "candidate_id": prediction["candidate_id"],
            "proposed": len(expected),
            "observed_matches": len(hits),
            "matched_mz": hits,
            "outcome": "consistent" if hits else ("no_diagnostic_match" if expected else "no_testable_prediction"),
        })
    return {
        "precommit_sha256": precommit["sha256"],
        "action": measurement.action,
        "evaluated": True,
        "candidate_outcomes": verdicts,
        "scientific_limit": "Peak presence supports a fingerprint hypothesis only; absence may reflect sensitivity and mechanism. Neither proves or refutes a molecular structure.",
    }

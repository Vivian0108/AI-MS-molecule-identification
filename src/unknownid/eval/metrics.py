"""Evaluation metrics and the shared abstention rule."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from unknownid.core.models import Evidence
from unknownid.core.posterior import rank_candidates, top2_margin


def top1(order: Sequence[str], truth: str) -> int:
    return int(bool(order) and order[0] == truth)


def topk(order: Sequence[str], truth: str, k: int) -> int:
    return int(truth in list(order)[:k])


def reciprocal_rank(order: Sequence[str], truth: str) -> float:
    try:
        return 1.0 / (list(order).index(truth) + 1)
    except ValueError:
        return 0.0


def entropy_reduction(before: float, after: float) -> float:
    return float(max(before - after, 0.0))


@dataclass
class Decision:
    decision: str
    top_candidate: str | None
    support: float
    margin: float
    best_similarity: float
    matched_peaks: int
    reasons: list[str]


def decide(
    weights: Mapping[str, float],
    evidence: Mapping[str, Evidence],
    *,
    min_support: float = 0.72,
    min_margin: float = 0.22,
    min_similarity: float = 0.30,
    min_matched: int = 2,
) -> Decision:
    """Shared, deterministic abstention rule for the session and evaluation."""
    if not weights:
        return Decision("out_of_library", None, 0.0, 0.0, 0.0, 0, ["no candidates"])
    order = rank_candidates(weights)
    top = order[0]
    support = float(weights[top])
    margin = float(top2_margin(weights))
    item = evidence.get(top)
    best_similarity = max(item.similarity_by_energy.values(), default=0.0) if item else 0.0
    matched = max(item.matched_peaks_by_energy.values(), default=0) if item else 0
    reasons: list[str] = []

    if best_similarity < min_similarity or matched < min_matched:
        reasons.append("insufficient matched spectral evidence")
        return Decision("out_of_library", top, support, margin, best_similarity, matched, reasons)

    connectivity = top.split("-")[0]
    stereo = any(
        cid != top and cid.split("-")[0] == connectivity and weights.get(cid, 0.0) >= 0.10
        for cid in order
    )
    if stereo:
        reasons.append("same-connectivity (stereoisomer) competitor cannot be separated by MS/MS")
    if support < min_support:
        reasons.append(f"top relative support {support:.3f} < {min_support:.2f}")
    if margin < min_margin:
        reasons.append(f"top-2 margin {margin:.3f} < {min_margin:.2f}")
    if reasons:
        return Decision("ambiguous", top, support, margin, best_similarity, matched, reasons)
    return Decision("identified", top, support, margin, best_similarity, matched, [])


def abstention_summary(
    decisions: Sequence[str],
    predicted: Sequence[str | None],
    truths: Sequence[str],
) -> dict:
    n = len(decisions)
    identified = [i for i, decision in enumerate(decisions) if decision == "identified"]
    correct = sum(1 for i in identified if predicted[i] == truths[i])
    out = sum(1 for decision in decisions if decision == "out_of_library")
    ambiguous = sum(1 for decision in decisions if decision == "ambiguous")
    return {
        "n": n,
        "identified": len(identified),
        "coverage": len(identified) / n if n else 0.0,
        "accepted_correct": correct,
        "accepted_errors": len(identified) - correct,
        "risk": (len(identified) - correct) / len(identified) if identified else 0.0,
        "precision_among_accepted": correct / len(identified) if identified else None,
        "ambiguous": ambiguous,
        "out_of_library": out,
    }


def mean(values: Sequence[float]) -> float:
    return float(np.mean(values)) if len(values) else 0.0

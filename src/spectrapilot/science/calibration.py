"""Calibrated decision risk from the evidence support score (SpectraPilot v3).

The candidate-level ranker in :mod:`spectrapilot.science.ranker` did not
transfer to held-out scaffolds (see ``reports/v3/features_ablation.csv``), so the
deployed scorer is the reliability-aware consistent-cosine model.  That left the
risk estimate uncalibrated, which makes the risk-coverage curve meaningless.

This module fits a **one-dimensional isotonic** mapping

    support(top candidate)  ->  P(top-1 is correct)

on a held-out development split, and exports the step function as JSON so the
calibration is auditable and reproducible without pickling.  It is deliberately
low-capacity: a monotone map on a single score cannot overfit a scaffold split
the way a 36-feature tree ensemble did, and the reliability diagram on the test
split is reported alongside it.

Nothing here reads hidden spectra; it only uses outcomes observed on the
development split at training time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


@dataclass
class SupportCalibrator:
    """Monotone map from support to calibrated P(top-1 correct)."""

    thresholds: list[float] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    n: int = 0
    brier: float | None = None
    split: str = ""
    score: str = "support"
    notes: list[str] = field(default_factory=list)

    def p_correct(self, support: float) -> float:
        if not self.thresholds:
            return 0.0
        # Piecewise-constant interpolation matching numpy's isotonic output.
        value = self.values[0]
        for threshold, mapped in zip(self.thresholds, self.values):
            if support >= threshold:
                value = mapped
            else:
                break
        return float(value)

    def risk(self, support: float) -> float:
        return float(1.0 - self.p_correct(support))

    # -- persistence -------------------------------------------------------
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "thresholds": self.thresholds,
                    "values": self.values,
                    "n": self.n,
                    "brier": self.brier,
                    "split": self.split,
                    "score": self.score,
                    "notes": self.notes,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "SupportCalibrator":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            thresholds=list(payload["thresholds"]),
            values=list(payload["values"]),
            n=int(payload.get("n", 0)),
            brier=payload.get("brier"),
            split=str(payload.get("split", "")),
            score=str(payload.get("score", "support")),
            notes=list(payload.get("notes", [])),
        )

    # -- fitting -----------------------------------------------------------
    @classmethod
    def fit(
        cls,
        supports: Sequence[float],
        labels: Sequence[float],
        *,
        split: str = "",
    ) -> "SupportCalibrator":
        supports = [float(value) for value in supports]
        labels = [float(value) for value in labels]
        if len(supports) != len(labels) or len(supports) == 0:
            raise ValueError("supports and labels must be non-empty and aligned")
        from sklearn.isotonic import IsotonicRegression
        from sklearn.metrics import brier_score_loss

        model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        model.fit(list(supports), list(labels))
        unique = sorted({float(value) for value in supports})
        mapped = [float(model.predict([value])[0]) for value in unique]
        # Collapse consecutive duplicates into a compact step function.
        thresholds: list[float] = []
        values: list[float] = []
        for threshold, value in zip(unique, mapped):
            if values and abs(value - values[-1]) < 1e-12:
                continue
            thresholds.append(threshold)
            values.append(value)
        if not thresholds:  # pragma: no cover - degenerate input
            thresholds, values = [0.0], [float(sum(labels) / len(labels))]
        fitted = [float(model.predict([value])[0]) for value in supports]
        return cls(
            thresholds=thresholds,
            values=values,
            n=len(supports),
            brier=float(brier_score_loss(list(labels), fitted)),
            split=split,
            notes=[
                "Isotonic regression on a single support score.",
                "Fitted on a held-out development split, never on test.",
                "Low capacity by design: no feature interactions to overfit.",
            ],
        )


def reliability_table(
    supports: Sequence[float],
    labels: Sequence[float],
    *,
    bins: int = 5,
) -> list[dict]:
    """Binned reliability data for the report (no plotting dependency)."""
    pairs = sorted(zip(supports, labels), key=lambda item: item[0])
    if not pairs:
        return []
    size = max(1, len(pairs) // bins)
    rows: list[dict] = []
    for start in range(0, len(pairs), size):
        chunk = pairs[start : start + size]
        if not chunk:
            continue
        rows.append(
            {
                "lo": float(chunk[0][0]),
                "hi": float(chunk[-1][0]),
                "n": len(chunk),
                "mean_support": float(sum(item[0] for item in chunk) / len(chunk)),
                "observed_accuracy": float(sum(item[1] for item in chunk) / len(chunk)),
            }
        )
    return rows


def brier(supports: Iterable[float], labels: Iterable[float]) -> float:
    supports = list(supports)
    labels = list(labels)
    if not supports:
        return 0.0
    return float(
        sum((support - label) ** 2 for support, label in zip(supports, labels))
        / len(supports)
    )

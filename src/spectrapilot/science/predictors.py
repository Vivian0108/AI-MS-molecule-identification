"""Optional spectrum predictors and a train-only peak-presence model.

Three honest positions are represented here:

1. **No validated MS/MS predictor is installed.**  ``UnavailablePredictor``
   reports that explicitly instead of substituting a template and calling it a
   prediction.  ``predictors_available()`` is what the demo prints.
2. **A method-aware presence model** (``PeakPresenceModel``) can say how likely
   a peak is to be observed at a given m/z for a given activation method.  It is
   fitted on *train* spectra only, per method, and is used to validate the
   predicted templates — not to invent diagnostic peaks.
3. **Fragment validation** compares each predicted template peak against the
   compound's own measured spectrum on held-out data, so the trust score the
   system assigns to a template can be checked against reality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from spectrapilot.models import Template


class PredictorUnavailable(RuntimeError):
    """Raised when a requested spectrum predictor is not installed."""


@dataclass
class UnavailablePredictor:
    """Explicit no-op predictor; never fabricates a spectrum."""

    name: str = "unavailable"
    reason: str = "no validated MS/MS predictor is configured for this action"
    available: bool = False

    def predict(self, smiles: str, action: str) -> None:  # noqa: ARG002
        return None

    def public_dict(self) -> dict:
        return {"name": self.name, "available": False, "reason": self.reason}


def predictors_available() -> list[dict]:
    """The system ships no learned spectrum predictor; say so."""
    return [UnavailablePredictor(name="cfm_id", reason="not installed").public_dict(),
            UnavailablePredictor(name="neims", reason="not installed").public_dict()]


@dataclass
class PeakPresenceModel:
    """Per-method Gaussian kernel density over observed peak m/z values."""

    action: str
    centres: np.ndarray = field(default_factory=lambda: np.array([]))
    bandwidth: float = 0.05
    floor: float = 0.01
    n_spectra: int = 0

    @classmethod
    def fit(
        cls,
        records: pd.DataFrame,
        action: str,
        *,
        split: str = "train",
        bandwidth: float = 0.05,
        max_peaks_per_spectrum: int = 20,
    ) -> "PeakPresenceModel":
        subset = records[(records["action"] == action) & (records["split"] == split)]
        centres: list[float] = []
        spectra = 0
        for row in subset.itertuples(index=False):
            intensity = np.asarray(row.peaks_intensity, float)
            mz = np.asarray(row.peaks_mz, float)
            if mz.size == 0:
                continue
            spectra += 1
            keep = intensity >= 0.01
            order = np.argsort(-intensity[keep])[:max_peaks_per_spectrum]
            centres.extend(mz[keep][order].tolist())
        return cls(
            action=action,
            centres=np.asarray(sorted(centres), float),
            bandwidth=float(bandwidth),
            n_spectra=spectra,
        )

    def presence(self, mz_values: Sequence[float] | np.ndarray) -> np.ndarray:
        values = np.atleast_1d(np.asarray(mz_values, float))
        if self.centres.size == 0:
            return np.full(values.shape, self.floor)
        distances = (values[:, None] - self.centres[None, :]) / self.bandwidth
        density = np.exp(-0.5 * distances**2).sum(axis=1)
        density /= self.centres.size * np.sqrt(2 * np.pi) * self.bandwidth
        return np.clip(density / max(density.max(), 1e-12), self.floor, 1.0)


def validate_template_peaks(
    records: pd.DataFrame,
    *,
    action: str,
    template_store,
    split: str = "dev",
    tolerance_da: float = 0.02,
    min_relative_intensity: float = 0.05,
    presence: PeakPresenceModel | None = None,
    max_compounds: int = 400,
) -> pd.DataFrame:
    """Check predicted template peaks against each compound's measured spectrum."""
    subset = records[(records["action"] == action) & (records["split"] == split)]
    rows: list[dict] = []
    for row in subset.head(max_compounds).itertuples(index=False):
        compound = str(row.compound_full_inchikey)
        try:
            template = template_store.template(compound, action)
        except KeyError:
            continue
        measured_mz = np.asarray(row.peaks_mz, float)
        measured_intensity = np.asarray(row.peaks_intensity, float)
        if measured_mz.size == 0 or template.n_peaks == 0:
            continue
        intensity = np.asarray(template.intensity, float)
        mz = np.asarray(template.mz, float)
        keep = intensity >= min_relative_intensity
        if keep.sum() == 0:
            continue
        predicted_mz = mz[keep]
        hits = [
            bool(np.min(np.abs(measured_mz - value)) <= tolerance_da) for value in predicted_mz
        ]
        presence_score = (
            float(presence.presence(predicted_mz).mean()) if presence is not None else None
        )
        rows.append(
            {
                "compound": compound,
                "action": action,
                "template_source": template.source,
                "reliability": float(template.reliability),
                "n_predicted_peaks": int(predicted_mz.size),
                "fraction_observed": float(np.mean(hits)),
                "presence_model_mean_probability": presence_score,
                "measured_peak_count": int(measured_mz.size),
            }
        )
    return pd.DataFrame(rows)


def summarize_validation(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    grouped = (
        frame.groupby(["action", "template_source"], dropna=False)
        .agg(
            n_compounds=("compound", "nunique"),
            mean_fraction_observed=("fraction_observed", "mean"),
            median_fraction_observed=("fraction_observed", "median"),
            mean_reliability=("reliability", "mean"),
            mean_predicted_peaks=("n_predicted_peaks", "mean"),
            mean_presence_probability=("presence_model_mean_probability", "mean"),
        )
        .reset_index()
    )
    return grouped

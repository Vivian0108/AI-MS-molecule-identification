"""Energy-conditioned reference templates.

The static library only ever contains the 10 and 50 eV reference spectra.  All
templates at 20/30/40 eV are interpolations of those two endpoints, so the
planner has no access to the hidden 20/30/40 eV observations by construction.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from unknownid.core.spectra import ProcessedSpectrum, align_spectra, preprocess_peaks


@dataclass
class TemplateResult:
    spectrum: ProcessedSpectrum
    method: str
    endpoint_agreement: float  # cosine between the 10 and 50 eV references
    n_peaks_10: int
    n_peaks_50: int


def _weighted_mz(mz_a: float, i_a: float, mz_b: float, i_b: float, t: float) -> float:
    denom = i_a * (1.0 - t) + i_b * t
    if denom <= 0:
        return 0.5 * (mz_a + mz_b)
    return (mz_a * i_a * (1.0 - t) + mz_b * i_b * t) / denom


def interpolate_linear(
    ref_low: ProcessedSpectrum,
    ref_high: ProcessedSpectrum,
    target_ev: float,
    *,
    low_ev: float = 10.0,
    high_ev: float = 50.0,
    tolerance: float = 0.02,
) -> ProcessedSpectrum:
    """First-order interpolation of both m/z and intensity across energy.

    Peaks present at only one endpoint fade in/out linearly.  This is a
    transparent baseline, not a replacement for the published interpolation
    models; the audit/report compare it against nearest-endpoint templates.
    """
    t = (target_ev - low_ev) / (high_ev - low_ev)
    t = min(max(t, 0.0), 1.0)
    aligned = align_spectra(
        ref_low.mz, ref_low.intensity, ref_high.mz, ref_high.intensity, tolerance
    )
    mz_out: list[float] = []
    int_out: list[float] = []
    for low_index, high_index in aligned:
        if low_index is not None and high_index is not None:
            mz_low = float(ref_low.mz[low_index])
            mz_high = float(ref_high.mz[high_index])
            i_low = float(ref_low.intensity[low_index])
            i_high = float(ref_high.intensity[high_index])
            intensity = i_low * (1.0 - t) + i_high * t
            if intensity <= 0:
                continue
            mz_out.append(_weighted_mz(mz_low, i_low, mz_high, i_high, t))
            int_out.append(intensity)
        elif low_index is not None:
            intensity = float(ref_low.intensity[low_index]) * (1.0 - t)
            if intensity > 0:
                mz_out.append(float(ref_low.mz[low_index]))
                int_out.append(intensity)
        else:
            intensity = float(ref_high.intensity[high_index]) * t
            if intensity > 0:
                mz_out.append(float(ref_high.mz[high_index]))
                int_out.append(intensity)
    if not int_out:
        return ProcessedSpectrum(np.array([]), np.array([]))
    mz_arr = np.asarray(mz_out)
    int_arr = np.asarray(int_out)
    order = np.argsort(mz_arr)
    mz_arr, int_arr = mz_arr[order], int_arr[order]
    int_arr = int_arr / int_arr.max()
    return preprocess_peaks(mz_arr, int_arr, rel_floor=0.0, normalize=True)


def nearest_endpoint(
    ref_low: ProcessedSpectrum,
    ref_high: ProcessedSpectrum,
    target_ev: float,
    *,
    low_ev: float = 10.0,
    high_ev: float = 50.0,
) -> ProcessedSpectrum:
    return ref_low if abs(target_ev - low_ev) <= abs(target_ev - high_ev) else ref_high


def build_template(
    ref_low: Sequence[float],
    int_low: Sequence[float],
    ref_high: Sequence[float],
    int_high: Sequence[float],
    target_ev: float,
    *,
    method: str = "linear",
    tolerance: float = 0.02,
) -> TemplateResult:
    low = preprocess_peaks(ref_low, int_low, rel_floor=0.0)
    high = preprocess_peaks(ref_high, int_high, rel_floor=0.0)
    if method == "nearest":
        spectrum = nearest_endpoint(low, high, target_ev)
    else:
        spectrum = interpolate_linear(low, high, target_ev, tolerance=tolerance)
    from unknownid.core.spectra import cosine_greedy

    agreement, _ = cosine_greedy(low.mz, low.intensity, high.mz, high.intensity, tolerance)
    return TemplateResult(
        spectrum=spectrum,
        method=method,
        endpoint_agreement=agreement,
        n_peaks_10=low.n_peaks,
        n_peaks_50=high.n_peaks,
    )


def build_all_templates(
    ref_low: Sequence[float],
    int_low: Sequence[float],
    ref_high: Sequence[float],
    int_high: Sequence[float],
    energies: Iterable[int] = (20, 30, 40),
    *,
    method: str = "linear",
    tolerance: float = 0.02,
) -> dict[int, ProcessedSpectrum]:
    return {
        int(ev): build_template(
            ref_low,
            int_low,
            ref_high,
            int_high,
            ev,
            method=method,
            tolerance=tolerance,
        ).spectrum
        for ev in energies
    }

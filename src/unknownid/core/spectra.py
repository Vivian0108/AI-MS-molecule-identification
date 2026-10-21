"""Deterministic spectral processing and matching.

CosineGreedy follows the standard matchms algorithm: all peak pairs inside the
m/z tolerance are greedily consumed in descending product order.  ``matchms``
itself is used by the test-suite as an independent cross-check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

PROTON_MASS = 1.007276466621


@dataclass
class ProcessedSpectrum:
    mz: np.ndarray
    intensity: np.ndarray

    @property
    def n_peaks(self) -> int:
        return int(self.mz.size)

    def as_lists(self) -> tuple[list[float], list[float]]:
        return [float(x) for x in self.mz], [float(x) for x in self.intensity]


def preprocess_peaks(
    mz: Sequence[float],
    intensity: Sequence[float],
    *,
    rel_floor: float = 0.01,
    normalize: bool = True,
) -> ProcessedSpectrum:
    """Remove invalid peaks, drop tiny peaks and normalise to base peak = 1.

    The rule is applied identically to reference, query and oracle spectra and
    is frozen before any evaluation.
    """
    mz_arr = np.asarray(mz, dtype=float)
    int_arr = np.asarray(intensity, dtype=float)
    finite = np.isfinite(mz_arr) & np.isfinite(int_arr) & (mz_arr > 0) & (int_arr >= 0)
    mz_arr, int_arr = mz_arr[finite], int_arr[finite]
    if int_arr.size == 0:
        return ProcessedSpectrum(mz_arr, int_arr)
    base = float(int_arr.max())
    if base <= 0:
        return ProcessedSpectrum(np.array([]), np.array([]))
    keep = int_arr >= rel_floor * base
    mz_arr, int_arr = mz_arr[keep], int_arr[keep]
    if normalize and int_arr.size:
        int_arr = int_arr / int_arr.max()
    order = np.argsort(mz_arr)
    return ProcessedSpectrum(mz_arr[order], int_arr[order])


def _greedy_pairs(
    mz1: np.ndarray, i1: np.ndarray, mz2: np.ndarray, i2: np.ndarray, tol: float
) -> list[tuple[int, int]]:
    if mz1.size == 0 or mz2.size == 0:
        return []
    candidates: list[tuple[float, int, int]] = []
    # Both arrays are sorted; a vectorised difference is fine at these sizes.
    delta = np.abs(mz1[:, None] - mz2[None, :])
    rows, cols = np.where(delta <= tol)
    for row, col in zip(rows.tolist(), cols.tolist()):
        candidates.append((float(i1[row] * i2[col]), row, col))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    used1: set[int] = set()
    used2: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, row, col in candidates:
        if row in used1 or col in used2:
            continue
        used1.add(row)
        used2.add(col)
        pairs.append((row, col))
    return pairs


def cosine_greedy(
    mz1: Sequence[float],
    i1: Sequence[float],
    mz2: Sequence[float],
    i2: Sequence[float],
    tolerance: float = 0.02,
) -> tuple[float, int]:
    """Return ``(cosine, n_matched)`` for two centroided spectra."""
    a_mz, b_mz = np.asarray(mz1, float), np.asarray(mz2, float)
    a_i, b_i = np.asarray(i1, float), np.asarray(i2, float)
    denom = float(np.sqrt(np.sum(a_i**2) * np.sum(b_i**2)))
    if denom == 0:
        return 0.0, 0
    pairs = _greedy_pairs(a_mz, a_i, b_mz, b_i, tolerance)
    if not pairs:
        return 0.0, 0
    numerator = sum(float(a_i[row] * b_i[col]) for row, col in pairs)
    return float(numerator / denom), len(pairs)


def cosine_hungarian(
    mz1: Sequence[float],
    i1: Sequence[float],
    mz2: Sequence[float],
    i2: Sequence[float],
    tolerance: float = 0.02,
) -> tuple[float, int]:
    """Optional optimal assignment variant (small spectra only)."""
    from scipy.optimize import linear_sum_assignment

    a_mz, b_mz = np.asarray(mz1, float), np.asarray(mz2, float)
    a_i, b_i = np.asarray(i1, float), np.asarray(i2, float)
    denom = float(np.sqrt(np.sum(a_i**2) * np.sum(b_i**2)))
    if denom == 0:
        return 0.0, 0
    if a_i.size == 0 or b_i.size == 0:
        return 0.0, 0
    delta = np.abs(a_mz[:, None] - b_mz[None, :])
    gain = np.outer(a_i, b_i)
    gain = np.where(delta <= tolerance, gain, 0.0)
    rows, cols = linear_sum_assignment(-gain)
    matched = gain[rows, cols] > 0
    return float(gain[rows, cols][matched].sum() / denom), int(matched.sum())


def matched_peaks(
    mz1: Sequence[float],
    i1: Sequence[float],
    mz2: Sequence[float],
    i2: Sequence[float],
    tolerance: float = 0.02,
) -> list[dict[str, float]]:
    a_mz, b_mz = np.asarray(mz1, float), np.asarray(mz2, float)
    a_i, b_i = np.asarray(i1, float), np.asarray(i2, float)
    pairs = _greedy_pairs(a_mz, a_i, b_mz, b_i, tolerance)
    return [
        {
            "observed_mz": float(a_mz[r]),
            "template_mz": float(b_mz[c]),
            "delta_da": float(a_mz[r] - b_mz[c]),
            "observed_intensity": float(a_i[r]),
            "template_intensity": float(b_i[c]),
        }
        for r, c in pairs
    ]


def neutral_losses(
    mz: Sequence[float],
    intensity: Sequence[float],
    precursor_mz: float,
    *,
    max_peaks: int = 60,
) -> list[tuple[float, float]]:
    """Return plausible neutral losses ``(loss_da, relative_intensity)``.

    Losses below 5 Da are dominated by isotope/rounding artefacts and are not
    treated as diagnostics.
    """
    mz_arr = np.asarray(mz, float)
    i_arr = np.asarray(intensity, float)
    if precursor_mz <= 0:
        return []
    order = np.argsort(-i_arr)[:max_peaks]
    losses = []
    for index in order:
        loss = float(precursor_mz - mz_arr[index])
        if 5.0 <= loss <= precursor_mz - 1.0:
            losses.append((loss, float(i_arr[index])))
    return sorted(losses, key=lambda item: item[0])


def neutral_loss_agreement(
    observed_losses: Sequence[tuple[float, float]],
    template_losses: Sequence[tuple[float, float]],
    tolerance: float = 0.02,
) -> tuple[float, int]:
    """Intensity-weighted Jaccard-style agreement of neutral-loss series."""
    if not observed_losses or not template_losses:
        return 0.0, 0
    used: set[int] = set()
    matched_weight = 0.0
    n_matched = 0
    for loss, intensity in observed_losses:
        best_index, best_delta = None, tolerance
        for index, (tloss, _) in enumerate(template_losses):
            if index in used:
                continue
            delta = abs(loss - tloss)
            if delta <= best_delta:
                best_index, best_delta = index, delta
        if best_index is not None:
            used.add(best_index)
            matched_weight += intensity
            n_matched += 1
    total = sum(i for _, i in observed_losses)
    return (matched_weight / total if total else 0.0), n_matched


def align_spectra(
    mz_a: Sequence[float],
    i_a: Sequence[float],
    mz_b: Sequence[float],
    i_b: Sequence[float],
    tolerance: float = 0.02,
) -> list[tuple[int | None, int | None]]:
    """Greedy one-to-one alignment, returning index pairs with ``None`` gaps."""
    a_mz, b_mz = np.asarray(mz_a, float), np.asarray(mz_b, float)
    a_i, b_i = np.asarray(i_a, float), np.asarray(i_b, float)
    pairs = _greedy_pairs(a_mz, a_i, b_mz, b_i, tolerance)
    used_a = {r for r, _ in pairs}
    used_b = {c for _, c in pairs}
    aligned: list[tuple[int | None, int | None]] = [(r, c) for r, c in pairs]
    aligned += [(r, None) for r in range(a_mz.size) if r not in used_a]
    aligned += [(None, c) for c in range(b_mz.size) if c not in used_b]
    aligned.sort(key=lambda pair: (a_mz[pair[0]] if pair[0] is not None else 1e9))
    return aligned


def spectrum_cosine(
    first: ProcessedSpectrum, second: ProcessedSpectrum, tolerance: float = 0.02
) -> tuple[float, int]:
    return cosine_greedy(first.mz, first.intensity, second.mz, second.intensity, tolerance)


def iter_top_peaks(
    mz: Iterable[float], intensity: Iterable[float], n: int = 10
) -> list[tuple[float, float]]:
    pairs = sorted(zip(mz, intensity), key=lambda item: -item[1])
    return pairs[:n]

"""Molecule-level bootstrap confidence intervals.

The resampling unit is the molecule/case, never an individual spectrum or
collision energy.  Paired differences resample the same molecules for both
policies.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    n_boot: int = 2000,
    seed: int = 20261020,
    level: float = 0.95,
) -> tuple[float, float, float]:
    array = np.asarray(values, float)
    if array.size == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    means = np.array(
        [rng.choice(array, size=array.size, replace=True).mean() for _ in range(n_boot)]
    )
    alpha = (1.0 - level) / 2.0
    return (
        float(array.mean()),
        float(np.quantile(means, alpha)),
        float(np.quantile(means, 1 - alpha)),
    )


def paired_bootstrap_difference(
    first: Mapping[str, float],
    second: Mapping[str, float],
    *,
    n_boot: int = 2000,
    seed: int = 20261020,
    level: float = 0.95,
) -> dict:
    common = sorted(set(first) & set(second))
    if not common:
        return {
            "n": 0,
            "mean_difference": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "wins": 0,
            "losses": 0,
        }
    a = np.asarray([first[key] for key in common], float)
    b = np.asarray([second[key] for key in common], float)
    diff = a - b
    rng = np.random.default_rng(seed)
    stats = np.array([rng.choice(diff, size=diff.size, replace=True).mean() for _ in range(n_boot)])
    alpha = (1.0 - level) / 2.0
    return {
        "n": len(common),
        "mean_difference": float(diff.mean()),
        "ci_low": float(np.quantile(stats, alpha)),
        "ci_high": float(np.quantile(stats, 1 - alpha)),
        "wins": int((diff > 0).sum()),
        "losses": int((diff < 0).sum()),
        "ties": int((diff == 0).sum()),
    }

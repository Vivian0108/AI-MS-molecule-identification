"""Probability-like utilities.

We deliberately expose ``relative support`` rather than calibrated identity
probabilities.  The likelihood multipliers are fitted on train identities; the
UI and reports state whether calibration was validated.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np


def entropy(weights: Mapping[str, float] | np.ndarray) -> float:
    values = np.array(list(weights.values()) if isinstance(weights, Mapping) else weights, float)
    values = values[values > 0]
    if values.size == 0:
        return 0.0
    total = values.sum()
    if total <= 0:
        return 0.0
    probs = values / total
    return float(-np.sum(probs * np.log(probs)))


def softmax(scores: Mapping[str, float], temperature: float = 1.0) -> dict[str, float]:
    if not scores:
        return {}
    items = list(scores.items())
    values = np.array([v for _, v in items], float) / max(temperature, 1e-9)
    values -= values.max()
    exp = np.exp(values)
    total = exp.sum()
    if total <= 0 or not np.isfinite(total):
        uniform = 1.0 / len(items)
        return {key: uniform for key, _ in items}
    return {key: float(value / total) for (key, _), value in zip(items, exp)}


def normalize(weights: Mapping[str, float], floor: float = 0.0) -> dict[str, float]:
    if not weights:
        return {}
    values = {k: max(float(v), 0.0) + floor for k, v in weights.items()}
    total = sum(values.values())
    if total <= 0:
        uniform = 1.0 / len(values)
        return {k: uniform for k in values}
    return {k: v / total for k, v in values.items()}


def top2_margin(weights: Mapping[str, float]) -> float:
    if len(weights) < 2:
        return 1.0
    ordered = sorted(weights.values(), reverse=True)
    return float(ordered[0] - ordered[1])


def rank_candidates(weights: Mapping[str, float]) -> list[str]:
    return sorted(weights, key=lambda key: (-weights[key], key))


def update_weights(
    prior: Mapping[str, float],
    observed: tuple[np.ndarray, np.ndarray],
    templates: Mapping[str, tuple[np.ndarray, np.ndarray]],
    *,
    kappa: float,
    tolerance: float = 0.02,
    tempering: float = 1.0,
) -> dict[str, float]:
    """Multiplicative likelihood update on cosine evidence.

    ``q(c | D, Y, e) ∝ q(c | D) * exp(kappa_e * cos(Y, S(c,e)))`` with optional
    tempering to acknowledge correlated evidence across collision energies.
    """
    from unknownid.core.spectra import cosine_greedy

    mz_obs, i_obs = observed
    log_weights: dict[str, float] = {}
    for candidate_id, prior_weight in prior.items():
        if candidate_id not in templates:
            log_weights[candidate_id] = -np.inf
            continue
        mz_t, i_t = templates[candidate_id]
        cosine, _ = cosine_greedy(mz_obs, i_obs, mz_t, i_t, tolerance)
        log_weights[candidate_id] = np.log(max(prior_weight, 1e-12)) + tempering * kappa * cosine
    finite = {k: v for k, v in log_weights.items() if np.isfinite(v)}
    if not finite:
        return normalize(prior)
    maximum = max(finite.values())
    exp = {k: float(np.exp(v - maximum)) for k, v in finite.items()}
    return normalize(exp)


def credible_interval(weights: Mapping[str, float], mass: float = 0.95) -> tuple[list[str], float]:
    """Return the smallest candidate set reaching ``mass`` support."""
    ordered = rank_candidates(weights)
    cumulative = 0.0
    chosen: list[str] = []
    for candidate_id in ordered:
        chosen.append(candidate_id)
        cumulative += weights[candidate_id]
        if cumulative >= mass:
            break
    return chosen, cumulative

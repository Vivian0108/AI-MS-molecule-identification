"""Explainable candidate scoring for CID and EAD observations.

The score is a deterministic weighted cosine plus neutral-loss agreement.  Its
softmax is called *relative support*; no identity probability calibration is
claimed unless a separate calibration report says so.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from spectrapilot.models import Candidate, Evidence, Template
from spectrapilot.science.templates import ReferenceStore
from unknownid.core.spectra import (
    ProcessedSpectrum,
    cosine_greedy,
    matched_peaks,
    neutral_loss_agreement,
    neutral_losses,
)


def _softmax(scores: Mapping[str, float], temperature: float = 1.0) -> dict[str, float]:
    if not scores:
        return {}
    keys = list(scores)
    values = np.asarray([scores[key] for key in keys], float) / max(temperature, 1e-9)
    values -= values.max()
    exp = np.exp(values)
    total = exp.sum()
    if not np.isfinite(total) or total <= 0:
        return {key: 1.0 / len(keys) for key in keys}
    return {key: float(value / total) for key, value in zip(keys, exp)}


class CandidateScorer:
    def __init__(
        self,
        *,
        tolerance_da: float = 0.02,
        kappa_cid: float = 8.0,
        kappa_ead: float = 6.0,
        neutral_loss_weight: float = 0.05,
        unmatched_penalty: float = 0.35,
        min_matched_peaks: int = 2,
        tempering: float = 0.85,
    ) -> None:
        self.tolerance_da = float(tolerance_da)
        self.kappa_cid = float(kappa_cid)
        self.kappa_ead = float(kappa_ead)
        self.neutral_loss_weight = float(neutral_loss_weight)
        self.unmatched_penalty = float(unmatched_penalty)
        self.min_matched_peaks = int(min_matched_peaks)
        self.tempering = float(tempering)

    def kappa(self, action: str) -> float:
        return self.kappa_ead if str(action).startswith("EAD") else self.kappa_cid

    def explain(
        self,
        observed: ProcessedSpectrum,
        candidate: Candidate,
        template: Template,
        action: str,
        *,
        precursor_mz: float,
    ) -> Evidence:
        cosine, n_matched = cosine_greedy(
            observed.mz, observed.intensity, template.mz, template.intensity, self.tolerance_da
        )
        matches = matched_peaks(
            observed.mz, observed.intensity, template.mz, template.intensity, self.tolerance_da
        )
        matched_mz = [item["observed_mz"] for item in matches]
        unexplained = [
            float(mz)
            for mz in observed.mz
            if not any(abs(mz - other) <= self.tolerance_da for other in matched_mz)
        ]
        observed_losses = neutral_losses(observed.mz, observed.intensity, precursor_mz)
        template_losses = neutral_losses(template.mz, template.intensity, precursor_mz)
        nl_agreement, _ = neutral_loss_agreement(
            observed_losses, template_losses, self.tolerance_da
        )
        log_score = self.kappa(action) * cosine + self.neutral_loss_weight * nl_agreement
        if n_matched < self.min_matched_peaks:
            log_score -= self.unmatched_penalty
        return Evidence(
            candidate_id=candidate.molecule_id,
            similarity_by_action={action: float(cosine)},
            matched_peaks_by_action={action: int(n_matched)},
            matched_fragments=matches,
            unexplained_peaks=unexplained,
            neutral_loss_agreement=float(nl_agreement),
            log_score=float(log_score),
            name=candidate.name,
            formula=candidate.formula,
            smiles=candidate.smiles,
            exact_mass=candidate.exact_mass,
            precursor_ppm=(
                (candidate.precursor_mz - precursor_mz) / precursor_mz * 1e6
                if precursor_mz
                else 0.0
            ),
        )

    def initial_rank(
        self,
        observed: ProcessedSpectrum,
        candidates: Sequence[Candidate],
        store: ReferenceStore,
        action: str,
        *,
        precursor_mz: float,
    ) -> tuple[dict[str, Evidence], dict[str, float]]:
        evidence: dict[str, Evidence] = {}
        scores: dict[str, float] = {}
        for candidate in candidates:
            try:
                template = store.template(candidate.molecule_id, action)
            except KeyError:
                continue
            item = self.explain(
                observed, candidate, template, action, precursor_mz=precursor_mz
            )
            evidence[candidate.molecule_id] = item
            scores[candidate.molecule_id] = item.log_score
        weights = _softmax(scores, temperature=max(self.tempering, 1e-6))
        self._attach_weights(evidence, weights)
        return evidence, weights

    def update(
        self,
        prior: Mapping[str, float],
        observed: ProcessedSpectrum,
        candidates: Sequence[Candidate],
        store: ReferenceStore,
        action: str,
        *,
        precursor_mz: float,
    ) -> tuple[dict[str, Evidence], dict[str, float]]:
        log_weights: dict[str, float] = {}
        fresh: dict[str, Evidence] = {}
        for candidate in candidates:
            cid = candidate.molecule_id
            if cid not in prior:
                continue
            try:
                template = store.template(cid, action)
            except KeyError:
                log_weights[cid] = -np.inf
                continue
            item = self.explain(
                observed, candidate, template, action, precursor_mz=precursor_mz
            )
            fresh[cid] = item
            log_weights[cid] = (
                np.log(max(prior[cid], 1e-12))
                + self.tempering * self.kappa(action) * item.similarity_by_action[action]
                + self.tempering * self.neutral_loss_weight * item.neutral_loss_agreement
            )
        finite = {key: value for key, value in log_weights.items() if np.isfinite(value)}
        if not finite:
            return fresh, dict(prior)
        maximum = max(finite.values())
        exp = {key: float(np.exp(value - maximum)) for key, value in finite.items()}
        total = sum(exp.values()) or 1.0
        weights = {key: value / total for key, value in exp.items()}
        self._attach_weights(fresh, weights)
        return fresh, weights

    @staticmethod
    def _attach_weights(evidence: dict[str, Evidence], weights: Mapping[str, float]) -> None:
        for cid, item in evidence.items():
            item.weight = float(weights.get(cid, 0.0))


def merge_evidence(
    existing: Mapping[str, Evidence], fresh: Mapping[str, Evidence]
) -> dict[str, Evidence]:
    merged = dict(existing)
    for cid, item in fresh.items():
        previous = merged.get(cid)
        if previous is None:
            merged[cid] = item
            continue
        similarity = dict(previous.similarity_by_action)
        similarity.update(item.similarity_by_action)
        matched = dict(previous.matched_peaks_by_action)
        matched.update(item.matched_peaks_by_action)
        previous.similarity_by_action = similarity
        previous.matched_peaks_by_action = matched
        previous.matched_fragments = item.matched_fragments
        previous.unexplained_peaks = item.unexplained_peaks
        previous.neutral_loss_agreement = item.neutral_loss_agreement
        previous.log_score = item.log_score
        previous.weight = item.weight
    return merged

"""Explainable candidate evidence: cosine, matched peaks, neutral losses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from unknownid.core.models import Evidence, MatchedPeak
from unknownid.core.posterior import softmax
from unknownid.core.retrieve import Candidate
from unknownid.core.spectra import (
    ProcessedSpectrum,
    cosine_greedy,
    matched_peaks,
    neutral_loss_agreement,
    neutral_losses,
)


class EvidenceEvaluator:
    """Deterministic, independently testable candidate scorer.

    The score is intentionally low-dimensional::

        score(c, e) = kappa_e * cosine(S_obs(e), S_hat(c, e))
                      + w_nl * neutral_loss_agreement
                      - penalty if too few peaks matched

    A softmax of these scores is *relative support*, never a calibrated
    molecular-identity probability.
    """

    def __init__(
        self,
        *,
        tolerance_da: float = 0.02,
        kappa: float = 8.0,
        neutral_loss_weight: float = 0.05,
        unmatched_penalty: float = 0.35,
        min_matched_peaks: int = 2,
        prior_floor: float = 0.0,
    ) -> None:
        self.tolerance_da = float(tolerance_da)
        self.kappa = float(kappa)
        self.neutral_loss_weight = float(neutral_loss_weight)
        self.unmatched_penalty = float(unmatched_penalty)
        self.min_matched_peaks = int(min_matched_peaks)
        self.prior_floor = float(prior_floor)

    def explain(
        self,
        observed: ProcessedSpectrum,
        candidate: Candidate,
        template: ProcessedSpectrum,
        energy: int,
        *,
        kappa: float | None = None,
        precursor_mz: float | None = None,
    ) -> Evidence:
        kappa_value = self.kappa if kappa is None else float(kappa)
        cosine, n_matched = cosine_greedy(
            observed.mz, observed.intensity, template.mz, template.intensity, self.tolerance_da
        )
        matches = matched_peaks(
            observed.mz, observed.intensity, template.mz, template.intensity, self.tolerance_da
        )
        matched_mz = [match["observed_mz"] for match in matches]
        unexplained = [
            float(mz)
            for mz in observed.mz
            if not any(abs(mz - other) <= self.tolerance_da for other in matched_mz)
        ]

        precursor = precursor_mz if precursor_mz is not None else candidate.precursor_mz
        observed_losses = neutral_losses(observed.mz, observed.intensity, precursor)
        template_losses = neutral_losses(template.mz, template.intensity, precursor)
        nl_agreement, _ = neutral_loss_agreement(
            observed_losses, template_losses, self.tolerance_da
        )

        log_score = kappa_value * cosine + self.neutral_loss_weight * nl_agreement
        if n_matched < self.min_matched_peaks:
            log_score -= self.unmatched_penalty

        return Evidence(
            candidate_id=candidate.molecule_id,
            similarity_by_energy={int(energy): float(cosine)},
            matched_peaks_by_energy={int(energy): int(n_matched)},
            matched_fragments=[MatchedPeak(**match) for match in matches],
            unexplained_peaks=unexplained,
            neutral_loss_agreement=float(nl_agreement),
            log_score=float(log_score),
            weight=0.0,
            name=candidate.name,
            formula=candidate.formula,
            smiles=candidate.smiles,
            exact_mass=candidate.exact_mass,
            precursor_ppm=(
                (candidate.precursor_mz - precursor) / precursor * 1e6 if precursor else 0.0
            ),
            reference_accessions=dict(candidate.reference_accessions),
        )

    def rank(
        self,
        observed: ProcessedSpectrum,
        candidates: Sequence[Candidate],
        templates: Mapping[str, ProcessedSpectrum],
        energy: int,
        *,
        kappa: float | None = None,
        precursor_mz: float | None = None,
    ) -> tuple[list[Evidence], dict[str, float]]:
        evidence = [
            self.explain(
                observed,
                candidate,
                templates[candidate.molecule_id],
                energy,
                kappa=kappa,
                precursor_mz=precursor_mz,
            )
            for candidate in candidates
            if candidate.molecule_id in templates
        ]
        scores = {item.candidate_id: item.log_score for item in evidence}
        weights = softmax(scores, temperature=1.0)
        weights = {key: max(value, self.prior_floor) for key, value in weights.items()}
        total = sum(weights.values()) or 1.0
        weights = {key: value / total for key, value in weights.items()}
        evidence = [
            item.model_copy(update={"weight": weights.get(item.candidate_id, 0.0)})
            for item in evidence
        ]
        evidence.sort(key=lambda item: (-item.weight, item.candidate_id))
        return evidence, weights


def merge_evidence(
    current: Mapping[str, Evidence],
    observed: ProcessedSpectrum,
    candidates: Sequence[Candidate],
    templates: Mapping[str, ProcessedSpectrum],
    energy: int,
    evaluator: EvidenceEvaluator,
    *,
    kappa: float,
    precursor_mz: float,
) -> list[Evidence]:
    """Append one energy's evidence while retaining prior similarities."""
    merged: dict[str, Evidence] = dict(current)
    for candidate in candidates:
        molecule_id = candidate.molecule_id
        if molecule_id not in templates:
            continue
        fresh = evaluator.explain(
            observed,
            candidate,
            templates[molecule_id],
            energy,
            kappa=kappa,
            precursor_mz=precursor_mz,
        )
        previous = merged.get(molecule_id)
        if previous is None:
            merged[molecule_id] = fresh
        else:
            similarity = dict(previous.similarity_by_energy)
            similarity.update(fresh.similarity_by_energy)
            matched = dict(previous.matched_peaks_by_energy)
            matched.update(fresh.matched_peaks_by_energy)
            merged[molecule_id] = previous.model_copy(
                update={
                    "similarity_by_energy": similarity,
                    "matched_peaks_by_energy": matched,
                    "matched_fragments": fresh.matched_fragments,
                    "unexplained_peaks": fresh.unexplained_peaks,
                    "neutral_loss_agreement": fresh.neutral_loss_agreement,
                    "log_score": fresh.log_score,
                }
            )
    return list(merged.values())

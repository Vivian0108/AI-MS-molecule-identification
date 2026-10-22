"""Explainable candidate scoring for CID and EAD observations.

Three scorers live here, on purpose:

``LegacyCosineScorer``
    The frozen v2 scorer.  It is preserved byte-for-byte in behaviour so the v2
    benchmark stays reproducible.

``ConsistentCosineScorer``
    The v3 "S1" scorer.  Both the initial and the follow-up update use the same
    :func:`spectrapilot.science.features` extraction, the same unmatched-peak
    penalty, and a template-trust factor derived from real provenance
    (``reference_cid60`` vs structure-kNN) and reliability.

``CalibratedEvidenceScorer`` (in ``ranker``)
    The supervised candidate-level ranker.

A softmax over spectral scores is **relative support**, never a calibrated
identity probability.  Nothing here produces a probability unless a calibration
report explicitly says so.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from spectrapilot.models import Candidate, Evidence, Template
from spectrapilot.science.features import (
    DEFAULT_ACTIONS,
    EvidenceFeatureExtractor,
    EvidenceFeatures,
)
from spectrapilot.science.templates import ReferenceStore
from unknownid.core.spectra import ProcessedSpectrum, preprocess_peaks


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


def template_trust(template: Template | None) -> float:
    """How much a template deserves to move the posterior.

    A real experimental reference is trusted at 1.0.  A structure-kNN consensus
    is trusted in proportion to how similar its donors actually are; a template
    built from unrelated structures cannot manufacture support.
    """
    if template is None or template.n_peaks == 0:
        return 0.0
    if template.is_experimental:
        return 1.0
    return float(np.clip(template.reliability, 0.0, 1.0))


class EvidenceScorerBase:
    """Shared machinery: one feature extractor for every observation stage."""

    name = "base"
    version = "v3"
    #: Legacy scoring must see every observed peak for exact v2 reproduction.
    truncate_peaks: bool = True

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
        extractor: EvidenceFeatureExtractor | None = None,
        ppm_tolerance: float = 10.0,
    ) -> None:
        self.tolerance_da = float(tolerance_da)
        self.kappa_cid = float(kappa_cid)
        self.kappa_ead = float(kappa_ead)
        self.neutral_loss_weight = float(neutral_loss_weight)
        self.unmatched_penalty = float(unmatched_penalty)
        self.min_matched_peaks = int(min_matched_peaks)
        self.tempering = float(tempering)
        self.extractor = extractor or EvidenceFeatureExtractor(
            tolerance_da=self.tolerance_da, ppm_tolerance=ppm_tolerance
        )
        self.extractor.truncate_peaks = self.truncate_peaks
    # -- helpers -----------------------------------------------------------
    def kappa(self, action: str) -> float:
        return self.kappa_ead if str(action).startswith("EAD") else self.kappa_cid

    def _trust(self, template: Template | None) -> float:
        return 1.0

    def _score(self, features: EvidenceFeatures, action: str, template: Template | None) -> float:
        cosine = features.cosine or 0.0
        agreement = features.neutral_loss_support or 0.0
        log_score = (
            self.kappa(action) * cosine + self.neutral_loss_weight * agreement
        )
        if features.matched_peak_count < self.min_matched_peaks:
            log_score -= self.unmatched_penalty
        return float(log_score)

    def _evidence(self, features: EvidenceFeatures, candidate: Candidate, action: str,
                  template: Template | None) -> Evidence:
        return Evidence(
            candidate_id=candidate.molecule_id,
            similarity_by_action={action: float(features.cosine or 0.0)},
            matched_peaks_by_action={action: int(features.matched_peak_count)},
            matched_intensity_by_action={action: float(features.matched_intensity_fraction)},
            unexplained_intensity_by_action={
                action: float(features.unexplained_high_intensity_fraction)
            },
            subformula_support_by_action=(
                {action: float(features.chemically_valid_subformula_fraction)}
                if features.chemically_valid_subformula_fraction is not None
                else {}
            ),
            neutral_loss_agreement=float(features.neutral_loss_support or 0.0),
            log_score=self._score(features, action, template),
            name=candidate.name,
            formula=candidate.formula,
            smiles=candidate.smiles,
            exact_mass=candidate.exact_mass,
            precursor_ppm=float(features.precursor_ppm),
            template_sources={action: features.template_source},
            template_reliability_by_action={
                action: float(features.predicted_template_reliability)
            },
        )

    def _initial_evidence(
        self, observed: ProcessedSpectrum, candidate: Candidate, store: ReferenceStore,
        action: str, precursor_mz: float,
    ) -> Evidence | None:
        try:
            template = store.template(candidate.molecule_id, action)
        except KeyError:
            return None
        features = self.extractor.extract(
            action_key=action,
            observed_mz=observed.mz,
            observed_intensity=observed.intensity,
            candidate=candidate,
            template=template,
            precursor_mz=precursor_mz,
        )
        return self._evidence(features, candidate, action, template)

    # -- public API (v2-compatible) ---------------------------------------
    def rank_sequence(
        self,
        observations: Mapping[str, tuple[np.ndarray, np.ndarray]],
        candidates: Sequence[Candidate],
        store: ReferenceStore,
        precursor_mz: float,
    ) -> tuple[dict[str, Evidence], dict[str, float]]:
        """Score a candidate pool from the full set of observations seen so far.

        Scorers that model the whole sequence (e.g. the calibrated ranker)
        override this.  The sequential default is numerically identical to the
        v2 initial-then-update path, so the frozen baseline is preserved.
        """
        order = [a for a in DEFAULT_ACTIONS if a in observations]
        evidence: dict[str, Evidence] = {}
        weights: dict[str, float] = {}
        for index, action in enumerate(order):
            observed = preprocess_peaks(
                np.asarray(observations[action][0], float),
                np.asarray(observations[action][1], float),
                rel_floor=0.0,
            )
            if index == 0:
                evidence, weights = self.initial_rank(
                    observed, candidates, store, action, precursor_mz=precursor_mz
                )
            else:
                fresh, weights = self.update(
                    weights,
                    observed,
                    candidates,
                    store,
                    action,
                    precursor_mz=precursor_mz,
                )
                evidence = merge_evidence(evidence, fresh)
        return evidence, weights

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
            item = self._initial_evidence(observed, candidate, store, action, precursor_mz)
            if item is None:
                continue
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
        evidence_by_id = {candidate.molecule_id: candidate for candidate in candidates}
        for cid, prior_weight in prior.items():
            candidate = evidence_by_id.get(cid)
            if candidate is None:
                continue
            try:
                template = store.template(cid, action)
            except KeyError:
                log_weights[cid] = -np.inf
                continue
            features = self.extractor.extract(
                action_key=action,
                observed_mz=observed.mz,
                observed_intensity=observed.intensity,
                candidate=candidate,
                template=template,
                precursor_mz=precursor_mz,
            )
            item = self._evidence(features, candidate, action, template)
            fresh[cid] = item
            log_weights[cid] = (
                np.log(max(prior_weight, 1e-12)) + self._delta_log_weight(features, action, template)
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

    def _delta_log_weight(
        self, features: EvidenceFeatures, action: str, template: Template | None
    ) -> float:
        raise NotImplementedError

    def explain(
        self,
        observed: ProcessedSpectrum,
        candidate: Candidate,
        template: Template,
        action: str,
        *,
        precursor_mz: float,
    ) -> Evidence:
        features = self.extractor.extract(
            action_key=action,
            observed_mz=observed.mz,
            observed_intensity=observed.intensity,
            candidate=candidate,
            template=template,
            precursor_mz=precursor_mz,
        )
        return self._evidence(features, candidate, action, template)

    @staticmethod
    def _attach_weights(evidence: dict[str, Evidence], weights: Mapping[str, float]) -> None:
        for cid, item in evidence.items():
            item.weight = float(weights.get(cid, 0.0))
            item.relative_weight = float(weights.get(cid, 0.0))


class LegacyCosineScorer(EvidenceScorerBase):
    """Frozen v2 scorer.  Do not change: v2 results depend on this behaviour."""

    name = "legacy_cosine"
    version = "v2_legacy"
    truncate_peaks = False

    def _score(self, features: EvidenceFeatures, action: str, template: Template | None) -> float:
        # v2: kappa*cosine + loss_weight*agreement - unmatched penalty.
        return super()._score(features, action, template)

    def _delta_log_weight(
        self, features: EvidenceFeatures, action: str, template: Template | None
    ) -> float:
        # v2 follow-up: kappa*cosine + loss_weight*agreement, NO penalty.
        # Kept unfixed on purpose so the frozen baseline is honest about it.
        cosine = features.cosine or 0.0
        agreement = features.neutral_loss_support or 0.0
        return self.tempering * (
            self.kappa(action) * cosine + self.neutral_loss_weight * agreement
        )


class ConsistentCosineScorer(EvidenceScorerBase):
    """S1: same features and penalty at every stage, trust-weighted by provenance."""

    name = "consistent_cosine"
    version = "v3_s1"

    def _trust(self, template: Template | None) -> float:
        return template_trust(template)

    def _score(self, features: EvidenceFeatures, action: str, template: Template | None) -> float:
        cosine = features.cosine or 0.0
        agreement = features.neutral_loss_support or 0.0
        trust = self._trust(template)
        log_score = trust * self.kappa(action) * cosine + self.neutral_loss_weight * agreement
        if features.matched_peak_count < self.min_matched_peaks:
            log_score -= self.unmatched_penalty
        return float(log_score)

    def _delta_log_weight(
        self, features: EvidenceFeatures, action: str, template: Template | None
    ) -> float:
        return self.tempering * self._score(features, action, template)


# Backwards-compatible name used by the v2 service and tests.
CandidateScorer = LegacyCosineScorer


def merge_evidence(
    existing: Mapping[str, Evidence], fresh: Mapping[str, Evidence]
) -> dict[str, Evidence]:
    merged = dict(existing)
    for cid, item in fresh.items():
        previous = merged.get(cid)
        if previous is None:
            merged[cid] = item
            continue
        for field_name in (
            "similarity_by_action",
            "matched_peaks_by_action",
            "matched_intensity_by_action",
            "unexplained_intensity_by_action",
            "subformula_support_by_action",
            "template_sources",
            "template_reliability_by_action",
        ):
            combined = dict(getattr(previous, field_name))
            combined.update(getattr(item, field_name))
            setattr(previous, field_name, combined)
        previous.matched_fragments = item.matched_fragments
        previous.unexplained_peaks = item.unexplained_peaks
        previous.neutral_loss_agreement = item.neutral_loss_agreement
        previous.log_score = item.log_score
        previous.weight = item.weight
        previous.relative_weight = item.relative_weight
        previous.estimated_error = item.estimated_error
        previous.reasons = list(item.reasons)
    return merged


class FormulaConsistencyScorer(ConsistentCosineScorer):
    """S3 ablation: consistent cosine plus a formula-plausibility penalty.

    Every major neutral loss in an observation must be a sub-formula mass of the
    candidate's molecular formula.  This is a *necessary* condition, so it can
    only ever penalise a candidate whose formula cannot explain what was
    observed.  It therefore cannot separate same-formula isomers, which is the
    point the ablation reports.
    """

    name = "formula_consistent_cosine"
    version = "v3_s3"

    def __init__(self, *, penalty_strength: float = 1.0, tolerance_da: float = 0.02, **kwargs) -> None:
        super().__init__(**kwargs)
        self.penalty_strength = float(penalty_strength)
        self.penalty_tolerance = float(tolerance_da)

    def _penalty(
        self,
        observations: Mapping[str, tuple[np.ndarray, np.ndarray]],
        candidate: Candidate,
        precursor_mz: float,
    ) -> float:
        from spectrapilot.science.fragments import SubformulaBackend

        if not candidate.formula:
            return 1.0
        backend = SubformulaBackend(enabled=False)
        plausible = 0
        total = 0
        for action in DEFAULT_ACTIONS:
            if action not in observations:
                continue
            mz, intensity = observations[action]
            mz = np.asarray(mz, float)
            intensity = np.asarray(intensity, float)
            if mz.size == 0:
                continue
            keep = intensity >= 0.01
            order = np.argsort(-intensity[keep])[:5]
            for peak_mz in mz[keep][order]:
                loss = float(precursor_mz - peak_mz)
                if loss <= 0:
                    continue
                result = backend.loss_is_plausible(
                    loss, formula=candidate.formula, tolerance_da=self.penalty_tolerance
                )
                if result is None:
                    continue
                total += 1
                plausible += int(bool(result))
        if total == 0:
            return 1.0
        implausible_fraction = 1.0 - plausible / total
        return float(np.exp(-self.penalty_strength * implausible_fraction))

    def rank_sequence(
        self,
        observations: Mapping[str, tuple[np.ndarray, np.ndarray]],
        candidates: Sequence[Candidate],
        store: ReferenceStore,
        precursor_mz: float,
    ) -> tuple[dict[str, Evidence], dict[str, float]]:
        evidence, weights = super().rank_sequence(observations, candidates, store, precursor_mz)
        if not weights:
            return evidence, weights
        logits = {}
        for candidate in candidates:
            cid = candidate.molecule_id
            if cid not in weights:
                continue
            base = float(np.log(max(weights.get(cid, 1e-12), 1e-12)))
            penalty = self._penalty(observations, candidate, precursor_mz)
            logits[cid] = base + float(np.log(max(penalty, 1e-12)))
        if not logits:
            return evidence, weights
        values = np.array(list(logits.values()), float)
        values -= values.max()
        exponent = np.exp(values)
        total = float(exponent.sum())
        adjusted = {
            cid: float(value / total) for cid, value in zip(logits, exponent)
        }
        for cid, weight in adjusted.items():
            if cid in evidence:
                evidence[cid].weight = weight
                evidence[cid].relative_weight = weight
                evidence[cid].reasons = list(evidence[cid].reasons) + [
                    "formula_loss_plausibility_penalty"
                ]
        return evidence, adjusted

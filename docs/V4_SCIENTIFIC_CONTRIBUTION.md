# SpectraPilot v4 — counterfactual evidence certificate

## Research claim (hypothesis, not established performance)

Can a budgeted library-identification system expose **the minimal fragile evidence in an existing MS/MS assignment**, issue a falsifiable, hash-sealed prediction about a diagnostic *measured fragment m/z*, and verify it after acquiring an archived CID/EAD spectrum, while preserving an unedited scientist-facing audit trail?

This integrates three independently established ideas (spectral matching; peak perturbation; active experiment selection). It is **not** a claim to have invented peak perturbation, first-ever counterfactual spectroscopy, or new bond-fragment reasoning. See related work: [SpecReBoot-related 2026 library-match reliability](https://www.biorxiv.org/content/10.64898/2026.07.30.741704v1); [2026 counterfactual peak deletion in spectral LLMs](https://openreview.net/pdf/26ed1cc71d4d027d874580205fd465564b68ef0d.pdf).

## What is implemented

- `science/evidence_challenge.py`: observed-peak leave-one-out audit on the *current acquired evidence*; deterministic replay, no oracle calls, no model changes. Peak contribution is a sensitivity statistic, **not causality**.
- Before `measure`: propose which public-reference diagnostic mass peaks might distinguish the current two leading candidates, SHA256-seal the observation and predicted mass peaks, append the commitment to the action log.
- After `measure`: compare observed masses with precommitted diagnostic m/z hypotheses and export each match. A hit is **consistent** with a reference-fingerprint prediction, never structural proof.
- Original unedited score/verdict is recomputed in parallel to edited analyses. The user edit cannot silently replace the baseline.
- Evidence status explicitly distinguishes `REFERENCE_SUPPORTED` (CID60 proxy comparison at CID40), `RANKED_ONLY_MATCH` (predicted-template relative ranking), `MASS_ONLY_MATCH` (unique precursor library hit), `AMBIGUOUS` and `INSUFFICIENT_DATA`. Weak kNN agreement is never sufficient proof of `OUT_OF_LIBRARY`.
- Relative support is never exported as calibrated identity confidence.

## Limits and open work

- CID60 comparison with CID40 is energy-mismatched; EAD16 predictions are weak and not a mechanistic fragment model.
- The current reference fingerprints do not assign fragment chemical formula, bond cleavage or reliable predictive probabilities.
- Perturbing an individual observed peak is not a valid instrumental counterfactual experiment; the counterfactual is **algorithmic evidence sensitivity** only.
- The SHA256 commitment proves the recorded bytes were not altered after committing; it does not establish that the predictor is accurate or that the local bundle is secret.
- Historical benchmark reports are frozen legacy artifacts, **not v4 accuracy validation**.
- Original dataset split is not scaffold-disjoint (it fell back to connectivity grouping). A future fresh truly scaffold-held-out cohort is required before performance claims.
- This branch does not demonstrate a new state-of-the-art accuracy result. Demo cases were selected on development outcomes.

## Suggested falsifiable experiment

Predeclare a challenge's top two candidates, action and expected peaks BEFORE revealing hidden data. On a fresh scaffold-disjoint cohort, compare peak-disagreement challenge to intensity-only and random diagnostic peaks; report diagnostic hit precision, rank-change attribution, predictive discrimination, query-level false-ID rate and total acquisition cost. Perform paired molecule/scaffold bootstrap. Report even if the proposed diagnostics fail.

**Related sources**: MultiMS2 (https://github.com/zamboni-lab/MultiMS2), matchms (https://github.com/matchms/matchms), 2026 SpecReBoot reliability (above).

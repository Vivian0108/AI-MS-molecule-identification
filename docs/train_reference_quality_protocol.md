# Train-only reference quality and reliability check

Recorded before computing predictor outcomes. This is a grouped cross-validated
training estimate, not a new test set. Do not use development or test spectra,
change the frozen benchmark, or build MCP/UI features in this experiment.

## Frozen design

- Donor population: 1,481 training compounds in the committed MultiMS2 split.
- Quality targets: all 737 complete training cases, scored out-of-fold once at
  CID20, CID40 and EAD16. Discrimination cohort: the 277 complete training cases
  with at least two candidates under the existing precursor filter, chosen from
  metadata before looking at predictions.
- Assign all training compounds to five balanced scaffold groups using the
  existing grouping rule (Bemis-Murcko scaffold; acyclic connectivity fallback),
  deterministic grouping implementation and configured seed 20261021. Every
  target is held out exactly once; exclude the entire outer fold from donors.
- Retain the existing fingerprints, radius 2, 2,048 bits, minimum similarity
  0.05, top 15 CID / top 20 EAD donors, squared similarity weights and 0.02 Da
  matching tolerance. Do not tune these values on out-of-fold outcomes.
- Preserve each ambiguous case's original candidate set. Non-training candidate
  structures/masses may be read as library metadata, but not their peak arrays.
  Predict every candidate from permitted training donors; exclude its own exact
  identity from donors. All query spectra come only from training rows.

## Three fixed prediction methods

1. **Current conditional consensus:** reproduce the existing peak clustering
   and per-cluster weighted mean intensity, then base-peak normalization. This
   is reconstructed within each outer fold, not loaded from full-data templates.
2. **Donor-agreement consensus (primary contrast):** identical donors/clusters,
   but divide each cluster's weighted intensity by total weight of all donors
   before normalization. Peaks supported by few donors lose relative intensity.
3. **Nearest neighbour (secondary diagnostic):** use the single most similar
   permitted donor's observed spectrum at the same action; identical donor
   eligibility and deterministic tie handling. No spectrum is its own reference.

This is a predictor-only track. All three methods predict native energies and
modalities. Do not give the CID method a measured CID60 reference in the primary
comparison. Separately report CID40-query versus same-compound CID60-reference
cosine, where available, as an allowed-library diagnostic with an energy mismatch.

## Metrics and reliability

- True-compound predicted-versus-measured cosine at each action: mean, median,
  quantiles, empty-prediction count, nearest-donor similarity and donor counts.
- On the 277 ambiguous cases: native-action cosine-only library retrieval top-1
  and MRR, using every original candidate; ties broken by candidate ID. This is
  a reference-discrimination diagnostic, not the product's stage-one acceptance
  result and not evidence of improved accepted-correct identification.
- Paired donor-agreement-minus-current mean cosine and retrieval top-1 changes
  with 2,000 percentile 95% bootstrap intervals resampling whole scaffold groups
  (configured seed). Nearest neighbour is reported separately, not selected by
  searching outcomes. Do not report a selected model's interval as independent
  validation.
- Assess the current reliability proxy descriptively against actual out-of-fold
  cosine: Spearman correlation and fixed [0,.1,.2,.3,.5,1] bins. The existing
  proxy is mean squared donor similarity, scaled by 0.75 for EAD; it is not a
  calibrated probability. No fitted calibration map is claimed here.
- Audit retained replicate counts; use independent pairs only if separately
  retained and provenance-distinct. Never compare a query with itself.

## Predeclared next-step gate

Proceed toward a learned selector only if the **primary** donor-agreement
contrast achieves BOTH on EAD16:

1. Mean out-of-fold cosine improvement at least 0.05 and the paired scaffold
   bootstrap 95% lower endpoint greater than zero.
2. Native-action ambiguous-cohort top-1 improvement at least 0.05 and the paired
   scaffold bootstrap 95% lower endpoint greater than zero.

These are practical screening thresholds for further engineering, not universal
definitions of a useful spectrum predictor. A secondary nearest-neighbour win
does not automatically pass this primary gate. If the gate fails, report the
findings and stop; do not train a selector or tune references to these outcomes.
If it passes, any selector calibration must use additional nested, non-held-out
training data only; outer-fold outcomes cannot be used for fitting.

Generate new `reports/spectrapilot/train_reference_quality.json` and `.md` from
code, including fold membership, per-target metrics, donor provenance, hashes
and environment metadata. Put large predicted spectra in ignored private study
artifacts. Preserve all existing configurations, data, planner and reports.

## Implementation clarification before predictor outcomes

The first run stopped at schema validation before any predictions: the saved
candidate-universe artifact has no `scaffold` column. Preparation computes
`QCResult.scaffold` but drops it in `_record_row`, so the original split function
uses its connectivity fallback for all compounds despite the saved scaffold
label. Do not rewrite that historical split. For this study derive Bemis-Murcko
scaffolds from canonical SMILES and apply the already declared five-fold
grouping rule to training compounds only. Record whether the original split is
exactly reproduced by connectivity fallback. Thresholds, comparison methods,
cohorts and seeds above remain unchanged. No predictor outcomes were available
when this clarification was recorded.

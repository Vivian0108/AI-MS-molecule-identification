# End-to-end stage-one reference comparison

Exploratory grouped cross-validated TRAINING estimate. This follow-up was
requested after reviewing the predictor-only results; it is not independent
validation and does not override that study's failed selector-training gate.
No learned selector, calibration fitting, MCP or UI work in this experiment.

## Design frozen before workflow outcomes

- Reuse the 1,481 training-compound fold assignments from the reference-quality
  protocol: real Bemis-Murcko scaffolds derived from SMILES, connectivity fallback
  for acyclic structures, seed 20261021. Confirm equality to saved assignments.
- Evaluate all 737 complete training cases exactly once out-of-fold. Primary
  reporting cohort is the 277 precursor-ambiguous cases, fixed using metadata.
  Report all 737 separately so precursor-unique cases cannot inflate the headline.
- All measured query spectra and predictor donors come from training rows only.
  Preserve each case's complete original candidate list, precursor filter,
  chemistry, preprocessing, scorer, planner, acceptance thresholds and budget.
- Compare `current_conditional` with `donor_agreement` references using the same
  donors and clusters; change only consensus intensity aggregation. No fitted
  reliability map: keep the original donor-based reliability proxy unchanged.

## Two separate reference tracks

1. **Native predicted references (primary):** CID20, CID40 and EAD16 are predicted
   from non-held-out training donors, as in the preceding reference-quality
   study. Every candidate is predicted and the target's entire outer fold is
   excluded from donors.
2. **Training-library CID60 anchored (secondary):** use the same predicted
   references, except CID40 is replaced with a measured CID60 reference for
   training library candidates where one exists, with the existing 0.75
   reliability. Both methods get identical anchors. Reserved CID60 spectra may
   belong to the held-out query identity, as an explicitly allowed library
   reference, not predictor training data. Do not read dev/test measured
   references to fill gaps. Thus this track approximates the current product's
   reference strategy using only the training library, not its full production
   reference coverage and not unseen-compound generalization.

Do not pool tracks or compare unlike reference conditions as a method gain.

## Product workflow

For every method/track/case start fresh independent sessions with real CID20.
Run CID20-only, always-CID40, always-EAD16, and the existing separation planner
(STOP or one recommended acquisition). The random comparator is the exact
50:50 expected outcome of the two measured branches. Truth is evaluator-side
after each investigation; never supply it to the planner or scorer. No peak
interventions. Verify identical measured CID20 hashes across every branch and
that the planner's outcome equals its independently evaluated chosen branch.

## Metrics and interpretation

- Stage-one accepted-correct, top-1, accepted errors, coverage, selective risk
  (errors / accepted; undefined when no acceptance), optional scans and total
  acquisitions (1 initial scan plus optional scans).
- Paired donor-agreement-minus-current differences per policy and track, using
  2,000 whole-scaffold-group bootstrap resamples and configured seed. Include
  accepted-correct, accepted errors, top-1, optional scans and selective-risk
  differences; report undefined resampled risks rather than setting them to zero.
- Primary contrast: planner accepted-correct change on 277 ambiguous cases in
  the native-prediction track. Report risk/error/cost tradeoffs alongside it.
  Other policies/tracks are explicitly exploratory secondary comparisons.
- Report CID40/EAD16 complementarity and metric-specific hindsight ceilings as
  diagnostic only. Also compare the unchanged planner to always-CID40 within
  each method/track. Reference improvements are not evidence for adaptive choice.
- Positive accepted-correct gain with a paired interval above zero supports a
  training-CV benefit, not a held-out-test claim. Do not declare practical safety
  or non-inferiority from overlapping intervals, or hide increases in errors.
- No automatic deployment, selector fitting or threshold tuning follows from
  these results. Report whether the observed benefit is identification, cost,
  or a risk/coverage tradeoff, then stop.

Generate new `reports/spectrapilot/train_stage1_reference.json` and `.md` from
code. Record folds, per-case outcomes, donor provenance and source/input hashes.
Preserve every existing report and frozen input.

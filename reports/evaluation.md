# UnknownID evaluation

*Generated 2026-10-21T06:16:58+00:00.  Frozen split and policies; no test-set tuning.*

## Claim tested

For genuinely ambiguous, closed-world known-library cases, does an adaptive collision-energy choice improve identification per additional acquisition versus fixed and random-energy policies?

## Frozen design

- Test molecules only; no train/dev molecule appears in the test split.
- Initial query: measured 20 eV spectrum. Reference library: 10/50 eV only. Hidden measurements: 30/40 eV.
- Candidate universe: all precursor-consistent library molecules at 10 ppm, same `[M+H]+` adduct.
- Acquisition method selected on dev: `monte_carlo_ig`.
- Default measurement budget in the API: 1; the evaluation curve uses up to 2 acquisitions.
- Random policy averages 20 seeded trials per molecule.
- Confidence intervals resample molecules, not spectra or energies.

## Cohorts

| Cohort | Cases |
|---|---:|
| all test | 100 |
| ambiguous (>=2 precursor-consistent candidates) | 11 |
| close-call (top-2 margin <= 0.15) | 4 |
| easy (precursor-unique) | 89 |

## Headline result

Ambiguous test cohort: n=11. Adaptive top-1@1=0.8182; single-scan=0.8182; always-40=0.8182. Adaptive used 0.6364 scans on average by the first decision, versus 1.0 for always-40. No paired 95% confidence interval excludes zero for top-1 accuracy against fixed or random energy choice. The defensible finding is therefore a cost/efficiency result (equal accuracy with fewer acquisitions on this cohort), not an accuracy improvement. The test ambiguous subset is small, so this is a proof-of-concept and not a general claim.


## Results — all

| Policy | Top-1 @0 | Top-1 @1 | Top-1 @2 | MRR @2 | Top-3 @2 | Scans @1 | Scans @2 | Coverage | Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| precursor_only | 0.930 | 0.930 | 0.930 | 0.960 | 1.000 | 0.00 | 0.00 | 0.890 | 0.000 |
| single_scan | 0.980 | 0.980 | 0.980 | 0.988 | 1.000 | 0.00 | 0.00 | 0.930 | 0.000 |
| always_30 | 0.980 | 0.980 | 0.980 | 0.990 | 1.000 | 1.00 | 2.00 | 0.980 | 0.000 |
| always_40 | 0.980 | 0.980 | 0.980 | 0.990 | 1.000 | 1.00 | 2.00 | 0.980 | 0.000 |
| random | 0.980 | 0.980 | 0.980 | 0.990 | 1.000 | 1.00 | 2.00 | 0.980 | 0.000 |
| cheap_disagreement | 0.980 | 0.980 | 0.980 | 0.990 | 1.000 | 0.11 | 0.22 | 0.950 | 0.000 |
| unknownid | 0.980 | 0.980 | 0.980 | 0.990 | 1.000 | 0.07 | 0.08 | 0.950 | 0.000 |
| oracle_best_action | 0.980 | 0.980 | 0.980 | 0.988 | 1.000 | 1.00 | 1.00 | 0.950 | 0.000 |

## Results — ambiguous

| Policy | Top-1 @0 | Top-1 @1 | Top-1 @2 | MRR @2 | Top-3 @2 | Scans @1 | Scans @2 | Coverage | Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| precursor_only | 0.364 | 0.364 | 0.364 | 0.636 | 1.000 | 0.00 | 0.00 | 0.273 | 0.000 |
| single_scan | 0.818 | 0.818 | 0.818 | 0.894 | 1.000 | 0.00 | 0.00 | 0.636 | 0.000 |
| always_30 | 0.818 | 0.818 | 0.818 | 0.909 | 1.000 | 1.00 | 2.00 | 0.818 | 0.000 |
| always_40 | 0.818 | 0.818 | 0.818 | 0.909 | 1.000 | 1.00 | 2.00 | 0.818 | 0.000 |
| random | 0.818 | 0.818 | 0.818 | 0.909 | 1.000 | 1.00 | 2.00 | 0.818 | 0.000 |
| cheap_disagreement | 0.818 | 0.818 | 0.818 | 0.909 | 1.000 | 1.00 | 2.00 | 0.818 | 0.000 |
| unknownid | 0.818 | 0.818 | 0.818 | 0.909 | 1.000 | 0.64 | 0.73 | 0.818 | 0.000 |
| oracle_best_action | 0.818 | 0.818 | 0.818 | 0.894 | 1.000 | 1.00 | 1.00 | 0.727 | 0.000 |

## Results — close_call

| Policy | Top-1 @0 | Top-1 @1 | Top-1 @2 | MRR @2 | Top-3 @2 | Scans @1 | Scans @2 | Coverage | Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| precursor_only | 0.250 | 0.250 | 0.250 | 0.583 | 1.000 | 0.00 | 0.00 | 0.250 | 0.000 |
| single_scan | 0.500 | 0.500 | 0.500 | 0.708 | 1.000 | 0.00 | 0.00 | 0.000 | — |
| always_30 | 0.500 | 0.500 | 0.500 | 0.750 | 1.000 | 1.00 | 2.00 | 0.500 | 0.000 |
| always_40 | 0.500 | 0.500 | 0.500 | 0.750 | 1.000 | 1.00 | 2.00 | 0.500 | 0.000 |
| random | 0.500 | 0.500 | 0.500 | 0.750 | 1.000 | 1.00 | 2.00 | 0.500 | 0.000 |
| cheap_disagreement | 0.500 | 0.500 | 0.500 | 0.750 | 1.000 | 1.00 | 2.00 | 0.500 | 0.000 |
| unknownid | 0.500 | 0.500 | 0.500 | 0.750 | 1.000 | 1.00 | 1.25 | 0.500 | 0.000 |
| oracle_best_action | 0.500 | 0.500 | 0.500 | 0.708 | 1.000 | 1.00 | 1.00 | 0.250 | 0.000 |

## Results — easy

| Policy | Top-1 @0 | Top-1 @1 | Top-1 @2 | MRR @2 | Top-3 @2 | Scans @1 | Scans @2 | Coverage | Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| precursor_only | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.00 | 0.00 | 0.966 | 0.000 |
| single_scan | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.00 | 0.00 | 0.966 | 0.000 |
| always_30 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 | 2.00 | 1.000 | 0.000 |
| always_40 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 | 2.00 | 1.000 | 0.000 |
| random | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 | 2.00 | 1.000 | 0.000 |
| cheap_disagreement | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.00 | 0.00 | 0.966 | 0.000 |
| unknownid | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.00 | 0.00 | 0.966 | 0.000 |
| oracle_best_action | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 | 1.00 | 0.978 | 0.000 |

## Paired differences versus the UnknownID policy

Positive values favour UnknownID; negative values favour the baseline.  CIs are 95% molecule-level paired bootstrap intervals.  An interval spanning zero is reported as inconclusive, not as a win.

| Cohort | Baseline | Metric | Difference | 95% CI | Wins/Losses |
|---|---|---|---:|---|---|
| all | precursor_only | top1_1 | -0.0500 | [-0.1000, -0.0100] | 0/5 |
| all | precursor_only | top1_2 | -0.0500 | [-0.1000, -0.0100] | 0/5 |
| all | precursor_only | mrr_2 | -0.0300 | [-0.0583, -0.0067] | 0/5 |
| all | single_scan | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | single_scan | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | single_scan | mrr_2 | -0.0017 | [-0.0050, +0.0000] | 0/1 |
| all | always_30 | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | always_30 | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | always_30 | mrr_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | always_40 | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | always_40 | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | always_40 | mrr_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | random | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | random | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | random | mrr_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | cheap_disagreement | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | cheap_disagreement | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | cheap_disagreement | mrr_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | oracle_best_action | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | oracle_best_action | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| all | oracle_best_action | mrr_2 | -0.0017 | [-0.0050, +0.0000] | 0/1 |
| ambiguous | precursor_only | top1_1 | -0.4545 | [-0.7273, -0.1818] | 0/5 |
| ambiguous | precursor_only | top1_2 | -0.4545 | [-0.7273, -0.1818] | 0/5 |
| ambiguous | precursor_only | mrr_2 | -0.2727 | [-0.4545, -0.0909] | 0/5 |
| ambiguous | single_scan | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | single_scan | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | single_scan | mrr_2 | -0.0152 | [-0.0455, +0.0000] | 0/1 |
| ambiguous | always_30 | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | always_30 | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | always_30 | mrr_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | always_40 | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | always_40 | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | always_40 | mrr_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | random | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | random | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | random | mrr_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | cheap_disagreement | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | cheap_disagreement | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | cheap_disagreement | mrr_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | oracle_best_action | top1_1 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | oracle_best_action | top1_2 | +0.0000 | [+0.0000, +0.0000] | 0/0 |
| ambiguous | oracle_best_action | mrr_2 | -0.0152 | [-0.0455, +0.0000] | 0/1 |

## Information-gain validation (test split, diagnostic only)

- Method: `monte_carlo_ig`
- Pairwise predictions: 22 (11 molecules × 30/40 eV)
- Spearman correlation between predicted acquisition value and actual entropy reduction: **0.7240892692018118** (p=0.0001389988565957412)
- Mean regret versus the best actual energy: **0.001368083731806736**

Both 30 and 40 eV spectra are revealed here only to validate the planner's prediction. The planner itself never reads them before choosing.

## Calibration status

- Probabilities calibrated: **False**
- Reported candidate `weight` is relative support, not a probability of chemical identity.
- No reliability diagram, ECE or Brier score is claimed because no probability calibration was validated.

## Failure inspection (UnknownID, top-1 error after two scans)

| Case | True | Predicted | Candidates | Scans | Decision | Margin | Failure mode |
|---|---|---|---:|---:|---|---:|---|
| `case-9d0ce7563ea4` | 2-Aminobenzimidazole | 1-Methylbenzotriazole | 3 | 2 | ambiguous | 0.000 | top relative support 0.369 < 0.72; top-2 margin 0.000 < 0.22 |
| `case-6debb13e35d8` | Androsterone | Dihydrotestosterone | 3 | 1 | ambiguous | 0.000 | top relative support 0.500 < 0.72; top-2 margin 0.000 < 0.22 |

## Open-world stress test

The true molecule is removed from the candidate library before ranking.  A confident ``identified`` decision here is a false library match.

- Cases evaluated: 100
- Cases with at least one remaining candidate: 11
- Out-of-library at 20 eV (all cases): 0.930
- Out-of-library after optional measurement (all cases): 0.930
- Confident wrong library match (all cases): 0.060; among cases with alternatives: 6/11
- Mean optional scans: 0.04

The all-case rate is dominated by precursor-unique cases that are rejected without any spectrum comparison.  The cases with alternatives are the informative stress test; confident wrong matches there are the failure mode that matters.

## What may and may not be claimed

**Supported by this evaluation if the intervals above exclude zero:** on this homogeneous Bruker maXis Impact cohort, the selected policy changes identification per acquisition relative to the named baseline.

**Not supported:** de novo structure elucidation, identification of compounds outside the reference library, cross-instrument generalization, enantiomer discrimination, clinical or regulatory validity, or automatic control of a real mass spectrometer.

**Structural limitations:**
- The true compound is in the candidate library by construction (closed world).
- 20/30/40 eV templates are interpolations from 10/50 eV references; the query spectra are experimental.
- Only two optional energies exist, so this is a 30-vs-40-or-stop decision, not general acquisition optimization.
- Accurate-mass filtering makes 89.0% of test cases precursor-unique; the ambiguous subset is the scientifically relevant one.
- Test-split ambiguous cases are few, so confidence intervals are wide and a null result must be reported as such.

## Reproducibility

- Fixed split seed: `20261020`; random-policy trials: 20 per molecule.
- Policies and thresholds were frozen before test evaluation; calibration used dev only.
- `reports/evaluation.json` contains every per-case metric and comparison shown above.

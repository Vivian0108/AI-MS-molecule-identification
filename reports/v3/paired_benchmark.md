# SpectraPilot v3 paired benchmark

Primary cohort: **test**, n = **157** (predeclared; no case filtering).

> The test split is development_exposed in this repository. Retuned v3 numbers are exploratory, not a blind result.

`MS/MS cov.` counts only `MSMS_SUPPORTED`. `Any cov.` also counts `MASS_ONLY_MATCH`, which is a unique precursor-consistent library hit and **never** MS/MS confirmation. `False-ID` is a fraction of *accepted* cases.

## Model matrix

| model | n | top-1 | 95% CI | scans | MS/MS cov. | Any cov. | False-ID | statuses |
|---|---:|---:|---|---:|---:|---:|---:|---|
| **M0_v2_cid20** | 157 | 0.834 | [0.771, 0.892] | 0.00 | 0.032 | 0.032 | 0.200 | AMBIGUOUS:4, INSUFFICIENT_DATA:18, MSMS_SUPPORTED:5, OUT_OF_LIBRARY:130 |
| **M1_v2_always_cid40** | 157 | 0.936 | [0.892, 0.968] | 1.00 | 0.701 | 0.701 | 0.018 | AMBIGUOUS:10, INSUFFICIENT_DATA:18, MSMS_SUPPORTED:110, OUT_OF_LIBRARY:19 |
| **M2_v2_always_ead16** | 157 | 0.834 | [0.771, 0.892] | 1.00 | 0.032 | 0.032 | 0.200 | AMBIGUOUS:4, INSUFFICIENT_DATA:18, MSMS_SUPPORTED:5, OUT_OF_LIBRARY:130 |
| **M3_v2_random** | 157 | 0.883 | [0.836, 0.924] | 1.00 | 0.376 | 0.376 | 0.024 | AMBIGUOUS:4, INSUFFICIENT_DATA:18, MIXED:107, MSMS_SUPPORTED:7, OUT_OF_LIBRARY:21 |
| **M4_v2_separation** | 157 | 0.936 | [0.898, 0.968] | 0.37 | 0.268 | 0.268 | 0.048 | AMBIGUOUS:6, INSUFFICIENT_DATA:18, MSMS_SUPPORTED:42, OUT_OF_LIBRARY:91 |
| **M5_s1_cid20** | 157 | 0.841 | [0.777, 0.892] | 0.00 | 0.013 | 0.516 | 0.000 | AMBIGUOUS:58, INSUFFICIENT_DATA:18, MASS_ONLY_MATCH:79, MSMS_SUPPORTED:2 |
| **M6_s1_always_cid40** | 157 | 0.943 | [0.904, 0.975] | 1.00 | 0.701 | 0.809 | 0.024 | AMBIGUOUS:30, MASS_ONLY_MATCH:17, MSMS_SUPPORTED:110 |
| **M7_full_adaptive** | 157 | 0.943 | [0.904, 0.975] | 0.95 | 0.701 | 0.809 | 0.024 | AMBIGUOUS:30, MASS_ONLY_MATCH:17, MSMS_SUPPORTED:110 |

## Paired comparisons

| comparison | Δ top-1 | 95% CI | excludes zero | A-only | B-only | McNemar p |
|---|---:|---|---:|---:|---:|---:|
| M7_full_adaptive_vs_M4_v2_separation | +0.006 | [-0.019, +0.032] | no | 3 | 2 | 1.000 |
| M7_full_adaptive_vs_M1_v2_always_cid40 | +0.006 | [-0.013, +0.032] | no | 2 | 1 | 1.000 |
| M1_v2_always_cid40_vs_M0_v2_cid20 | +0.102 | [+0.051, +0.159] | yes | 19 | 3 | 0.001 |

## Feature ablation (fixed always-CID40 action)

| variant | top-1 | Δ vs S1 | MS/MS cov. | Any cov. | False-ID | note |
|---|---:|---:|---:|---:|---:|---|
| S0_legacy_cosine | 0.936 | -0.006 | 0.739 | 0.847 | 0.015 | — |
| S1_consistent_cosine | 0.943 | +0.000 | 0.701 | 0.809 | 0.024 | NEUTRAL: +1 top-1 case, but -4 points MS/MS coverage and +1 false ID versus S0; the scorer is not the source of any v3 gain |
| S2_plus_ranker | 0.898 | -0.045 | 0.624 | 0.733 | 0.043 | REJECTED: train-split kNN templates are optimistic for train compounds; the model does not transfer to held-out scaffolds (see training_report.md) |
| S3_plus_formula | 0.943 | +0.000 | 0.701 | 0.809 | 0.024 | formula-level loss plausibility can only penalise different-formula distractors; it cannot separate same-formula isomers |

**S1 is neutral.** The consistent-cosine scorer moves top-1 by one case (0.936 → 0.943) while costing about four points of MS/MS coverage and one extra false identification. That is not a gain, and it is not significant. It is retained as the deployed scorer only because it was the predeclared v3 evidence model and switching to S0 on a one-case difference would be post-hoc selection on a development-exposed split. The defensible v3 contribution is the contract, not the scorer.

**S2 is a negative result.** The calibrated ranker reaches 0.937 top-1 out of fold on train but 0.478 on the held-out multi-candidate test pools, below the 0.612 of plain cosine ranking. It is reported, not deployed. **S3 is neutral**: formula-level loss plausibility can only remove different-formula distractors (26 of 157 pools), so it cannot move same-formula isomer cases.

## Accuracy–cost frontier

| proof_tier_value | scans | top-1 | MS/MS cov. | Any cov. | False-ID |
|---:|---:|---:|---:|---:|---:|
| 0.00 | 0.45 | 0.949 | 0.280 | 0.809 | 0.024 |
| 0.05 | 0.91 | 0.949 | 0.694 | 0.796 | 0.024 |
| 0.10 | 0.92 | 0.943 | 0.694 | 0.796 | 0.024 |
| 0.20 | 0.94 | 0.943 | 0.701 | 0.803 | 0.024 |
| 0.30 | 0.95 | 0.943 | 0.701 | 0.809 | 0.024 |

The planner's proof-tier weight is an explicit utility knob, so the frontier is reported instead of a single cherry-picked operating point. At the default (0.30) the planner buys MS/MS confirmation with roughly one scan; at 0.0 it saves scans and accepts mass-only matches.

## Open world

| quantity | value |
|---|---:|
| in-library episodes (test) | 157 |
| hard-unknown episodes (test) | 67 |
| selected score (chosen on dev) | `absolute_score` |
| dev AUROC by score | {'absolute_score': 0.731920498084291, 'relative_score': 0.5687260536398469} |
| threshold (from dev, 95th pct in-library) | 0.9471 |
| AUROC | 0.774 |
| AUPRC | 0.693 |
| in-library false-accept | 0.038 |
| unknown false-accept | 0.537 |
| unknown detection | 0.463 |

A hard-unknown episode removes the truth *and its aliases* but keeps the precursor-consistent distractors, so the score cannot cheat on precursor mass. The threshold is fitted on the development split and applied unchanged to test. The relative softmax support scores at chance here (it is normalised over the pool), so the absolute best-candidate fit is used and that choice is made on dev.

## Secondary cohort (ambiguous test)

| model | n | top-1 | scans | MS/MS cov. | Any cov. |
|---|---:|---:|---:|---:|---:|
| M1_v2_always_cid40 | 67 | 0.851 | 1.00 | 0.627 | 0.627 |
| M4_v2_separation | 67 | 0.851 | 0.87 | 0.612 | 0.612 |
| M7_full_adaptive | 67 | 0.866 | 1.00 | 0.552 | 0.552 |

## Reading the result

* The v3 adaptive system does **not** claim a significant top-1 gain over always-CID40. Check the paired interval before quoting any point estimate.
* The defensible v3 claims are: coverage recovery through an explicit `MASS_ONLY_MATCH` tier, a corrected risk–coverage curve, calibrated risk, and a decision-aware planner whose cost/proof trade-off is exposed rather than hidden.
* The only safety-critical number is the false-identification rate. It is reported at coverage, not in isolation.

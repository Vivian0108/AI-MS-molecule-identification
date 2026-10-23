# End-to-end stage-one reference comparison

**EXPLORATORY grouped cross-validated TRAINING estimate; not independent validation.**

All branches use real CID20 followed by STOP or at most one real archived CID40/EAD16 measurement. Scorer, acceptance thresholds, planner, budgets, candidate sets and reliability proxy are fixed. Random is the exact 50:50 expected measured-branch outcome.

## Primary contrast: planner on ambiguous cases with native predicted references

Accepted-correct rate difference (donor agreement minus current): +0.1047 [+0.0636, +0.1514].
Accepted-error rate difference: +0.0000 [-0.0144, +0.0141].
Optional scans per case difference: -0.2094 [-0.2701, -0.1541].

These are paired whole-scaffold bootstrap 95% intervals. More accepted-correct outcomes alone do not establish an acceptable error rate or a better adaptive policy.

## ambiguous_primary

### native_predicted

| Reference method | Policy | n | Top-1 | Accepted-correct | Accepted errors | Coverage | Selective risk | Optional scans total / mean | Total acquisitions mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| current_conditional | cid20_only | 277 | 142 | 6 | 0 | 2.2% | 0.0% | 0 / 0.000 | 1.000 |
| current_conditional | always_cid40 | 277 | 155 | 23 | 3 | 9.4% | 11.5% | 277 / 1.000 | 2.000 |
| current_conditional | always_ead16 | 277 | 148 | 8 | 1 | 3.2% | 11.1% | 277 / 1.000 | 2.000 |
| current_conditional | separation | 277 | 154 | 20 | 3 | 8.3% | 13.0% | 220 / 0.794 | 1.794 |
| current_conditional | random_expected_50_50 | 277 | 151.5 | 15.5 | 2 | 6.3% | 11.4% | 277 / 1.000 | 2.000 |
| donor_agreement | cid20_only | 277 | 157 | 21 | 2 | 8.3% | 8.7% | 0 / 0.000 | 1.000 |
| donor_agreement | always_cid40 | 277 | 172 | 60 | 3 | 22.7% | 4.8% | 277 / 1.000 | 2.000 |
| donor_agreement | always_ead16 | 277 | 155 | 36 | 2 | 13.7% | 5.3% | 277 / 1.000 | 2.000 |
| donor_agreement | separation | 277 | 174 | 49 | 3 | 18.8% | 5.8% | 162 / 0.585 | 1.585 |
| donor_agreement | random_expected_50_50 | 277 | 163.5 | 48 | 2.5 | 18.2% | 5.0% | 277 / 1.000 | 2.000 |

Donor-agreement minus current; changes are per case except selective risk.

| Policy | Accepted-correct Δ [95% CI] | Accepted-error Δ [95% CI] | Optional scans Δ [95% CI] | Risk Δ [valid-resample 95% CI] | Undefined risk resamples |
|---|---|---|---|---|---:|
| cid20_only | +0.0542 [+0.0237, +0.0894] | +0.0072 [+0.0000, +0.0189] | +0.0000 [+0.0000, +0.0000] | +0.0870 [+0.0000, +0.2277] | 4 |
| always_cid40 | +0.1336 [+0.0888, +0.1811] | +0.0000 [-0.0175, +0.0173] | +0.0000 [+0.0000, +0.0000] | -0.0678 [-0.2388, +0.0526] | 0 |
| always_ead16 | +0.1011 [+0.0606, +0.1470] | +0.0036 [+0.0000, +0.0119] | +0.0000 [+0.0000, +0.0000] | -0.0585 [-0.2727, +0.0715] | 0 |
| separation | +0.1047 [+0.0636, +0.1514] | +0.0000 [-0.0144, +0.0141] | -0.2094 [-0.2701, -0.1541] | -0.0727 [-0.2311, +0.0450] | 0 |
| random_expected_50_50 | +0.1173 [+0.0830, +0.1546] | +0.0018 [-0.0081, +0.0130] | +0.0000 [+0.0000, +0.0000] | -0.0648 [-0.2025, +0.0321] | 0 |

### training_cid60_anchored

| Reference method | Policy | n | Top-1 | Accepted-correct | Accepted errors | Coverage | Selective risk | Optional scans total / mean | Total acquisitions mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| current_conditional | cid20_only | 277 | 142 | 6 | 0 | 2.2% | 0.0% | 0 / 0.000 | 1.000 |
| current_conditional | always_cid40 | 277 | 228 | 147 | 11 | 57.0% | 7.0% | 277 / 1.000 | 2.000 |
| current_conditional | always_ead16 | 277 | 148 | 8 | 1 | 3.2% | 11.1% | 277 / 1.000 | 2.000 |
| current_conditional | separation | 277 | 224 | 146 | 11 | 56.7% | 7.0% | 264 / 0.953 | 1.953 |
| current_conditional | random_expected_50_50 | 277 | 188 | 77.5 | 6 | 30.1% | 7.2% | 277 / 1.000 | 2.000 |
| donor_agreement | cid20_only | 277 | 157 | 21 | 2 | 8.3% | 8.7% | 0 / 0.000 | 1.000 |
| donor_agreement | always_cid40 | 277 | 227 | 157 | 15 | 62.1% | 8.7% | 277 / 1.000 | 2.000 |
| donor_agreement | always_ead16 | 277 | 155 | 36 | 2 | 13.7% | 5.3% | 277 / 1.000 | 2.000 |
| donor_agreement | separation | 277 | 224 | 156 | 15 | 61.7% | 8.8% | 243 / 0.877 | 1.877 |
| donor_agreement | random_expected_50_50 | 277 | 191 | 96.5 | 8.5 | 37.9% | 8.1% | 277 / 1.000 | 2.000 |

Donor-agreement minus current; changes are per case except selective risk.

| Policy | Accepted-correct Δ [95% CI] | Accepted-error Δ [95% CI] | Optional scans Δ [95% CI] | Risk Δ [valid-resample 95% CI] | Undefined risk resamples |
|---|---|---|---|---|---:|
| cid20_only | +0.0542 [+0.0237, +0.0894] | +0.0072 [+0.0000, +0.0189] | +0.0000 [+0.0000, +0.0000] | +0.0870 [+0.0000, +0.2277] | 4 |
| always_cid40 | +0.0361 [+0.0085, +0.0674] | +0.0144 [-0.0155, +0.0418] | +0.0000 [+0.0000, +0.0000] | +0.0176 [-0.0302, +0.0618] | 0 |
| always_ead16 | +0.1011 [+0.0606, +0.1470] | +0.0036 [+0.0000, +0.0119] | +0.0000 [+0.0000, +0.0000] | -0.0585 [-0.2727, +0.0715] | 0 |
| separation | +0.0361 [+0.0068, +0.0679] | +0.0144 [-0.0155, +0.0418] | -0.0758 [-0.1155, -0.0410] | +0.0177 [-0.0302, +0.0618] | 0 |
| random_expected_50_50 | +0.0686 [+0.0397, +0.1000] | +0.0090 [-0.0065, +0.0244] | +0.0000 [+0.0000, +0.0000] | +0.0091 [-0.0345, +0.0516] | 0 |

## all_complete_secondary

### native_predicted

| Reference method | Policy | n | Top-1 | Accepted-correct | Accepted errors | Coverage | Selective risk | Optional scans total / mean | Total acquisitions mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| current_conditional | cid20_only | 737 | 602 | 7 | 0 | 0.9% | 0.0% | 0 / 0.000 | 1.000 |
| current_conditional | always_cid40 | 737 | 615 | 67 | 3 | 9.5% | 4.3% | 737 / 1.000 | 2.000 |
| current_conditional | always_ead16 | 737 | 608 | 9 | 1 | 1.4% | 10.0% | 737 / 1.000 | 2.000 |
| current_conditional | separation | 737 | 614 | 21 | 3 | 3.3% | 12.5% | 220 / 0.299 | 1.299 |
| current_conditional | random_expected_50_50 | 737 | 611.5 | 38 | 2 | 5.4% | 5.0% | 737 / 1.000 | 2.000 |
| donor_agreement | cid20_only | 737 | 617 | 51 | 2 | 7.2% | 3.8% | 0 / 0.000 | 1.000 |
| donor_agreement | always_cid40 | 737 | 632 | 175 | 3 | 24.2% | 1.7% | 737 / 1.000 | 2.000 |
| donor_agreement | always_ead16 | 737 | 615 | 221 | 2 | 30.3% | 0.9% | 737 / 1.000 | 2.000 |
| donor_agreement | separation | 737 | 634 | 79 | 3 | 11.1% | 3.7% | 162 / 0.220 | 1.220 |
| donor_agreement | random_expected_50_50 | 737 | 623.5 | 198 | 2.5 | 27.2% | 1.2% | 737 / 1.000 | 2.000 |

Donor-agreement minus current; changes are per case except selective risk.

| Policy | Accepted-correct Δ [95% CI] | Accepted-error Δ [95% CI] | Optional scans Δ [95% CI] | Risk Δ [valid-resample 95% CI] | Undefined risk resamples |
|---|---|---|---|---|---:|
| cid20_only | +0.0597 [+0.0375, +0.0860] | +0.0027 [+0.0000, +0.0070] | +0.0000 [+0.0000, +0.0000] | +0.0377 [+0.0000, +0.0980] | 2 |
| always_cid40 | +0.1465 [+0.1189, +0.1758] | +0.0000 [-0.0067, +0.0065] | +0.0000 [+0.0000, +0.0000] | -0.0260 [-0.0875, +0.0204] | 0 |
| always_ead16 | +0.2877 [+0.2490, +0.3258] | +0.0014 [+0.0000, +0.0043] | +0.0000 [+0.0000, +0.0000] | -0.0910 [-0.3241, +0.0125] | 0 |
| separation | +0.0787 [+0.0552, +0.1053] | +0.0000 [-0.0055, +0.0053] | -0.0787 [-0.1034, -0.0541] | -0.0884 [-0.2415, +0.0263] | 0 |
| random_expected_50_50 | +0.2171 [+0.1911, +0.2431] | +0.0007 [-0.0033, +0.0048] | +0.0000 [+0.0000, +0.0000] | -0.0375 [-0.0950, +0.0048] | 0 |

### training_cid60_anchored

| Reference method | Policy | n | Top-1 | Accepted-correct | Accepted errors | Coverage | Selective risk | Optional scans total / mean | Total acquisitions mean |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| current_conditional | cid20_only | 737 | 602 | 7 | 0 | 0.9% | 0.0% | 0 / 0.000 | 1.000 |
| current_conditional | always_cid40 | 737 | 688 | 462 | 11 | 64.2% | 2.3% | 737 / 1.000 | 2.000 |
| current_conditional | always_ead16 | 737 | 608 | 9 | 1 | 1.4% | 10.0% | 737 / 1.000 | 2.000 |
| current_conditional | separation | 737 | 684 | 147 | 11 | 21.4% | 7.0% | 264 / 0.358 | 1.358 |
| current_conditional | random_expected_50_50 | 737 | 648 | 235.5 | 6 | 32.8% | 2.5% | 737 / 1.000 | 2.000 |
| donor_agreement | cid20_only | 737 | 617 | 51 | 2 | 7.2% | 3.8% | 0 / 0.000 | 1.000 |
| donor_agreement | always_cid40 | 737 | 687 | 481 | 15 | 67.3% | 3.0% | 737 / 1.000 | 2.000 |
| donor_agreement | always_ead16 | 737 | 615 | 221 | 2 | 30.3% | 0.9% | 737 / 1.000 | 2.000 |
| donor_agreement | separation | 737 | 684 | 186 | 15 | 27.3% | 7.5% | 243 / 0.330 | 1.330 |
| donor_agreement | random_expected_50_50 | 737 | 651 | 351 | 8.5 | 48.8% | 2.4% | 737 / 1.000 | 2.000 |

Donor-agreement minus current; changes are per case except selective risk.

| Policy | Accepted-correct Δ [95% CI] | Accepted-error Δ [95% CI] | Optional scans Δ [95% CI] | Risk Δ [valid-resample 95% CI] | Undefined risk resamples |
|---|---|---|---|---|---:|
| cid20_only | +0.0597 [+0.0375, +0.0860] | +0.0027 [+0.0000, +0.0070] | +0.0000 [+0.0000, +0.0000] | +0.0377 [+0.0000, +0.0980] | 2 |
| always_cid40 | +0.0258 [+0.0114, +0.0403] | +0.0054 [-0.0055, +0.0158] | +0.0000 [+0.0000, +0.0000] | +0.0070 [-0.0092, +0.0220] | 0 |
| always_ead16 | +0.2877 [+0.2490, +0.3258] | +0.0014 [+0.0000, +0.0043] | +0.0000 [+0.0000, +0.0000] | -0.0910 [-0.3241, +0.0125] | 0 |
| separation | +0.0529 [+0.0307, +0.0784] | +0.0054 [-0.0055, +0.0158] | -0.0285 [-0.0430, -0.0145] | +0.0050 [-0.0422, +0.0447] | 0 |
| random_expected_50_50 | +0.1567 [+0.1357, +0.1781] | +0.0034 [-0.0023, +0.0091] | +0.0000 [+0.0000, +0.0000] | -0.0012 [-0.0170, +0.0127] | 0 |


## Does adaptive selection help? Ambiguous-cohort diagnostic

| Track | References | Planner actions | CID40-only / EAD16-only / both accepted-correct | Best measurement accepted-correct ceiling | Planner-minus-always-CID40 accepted-correct [95% CI] | Planner-minus-always-CID40 scans [95% CI] |
|---|---|---|---:|---:|---|---|
| native_predicted | current_conditional | {"CID40": 220, "STOP": 57} | 17 / 2 / 6 | 25 | -0.0108 [-0.0234, +0.0000] | -0.2058 [-0.2624, -0.1467] |
| native_predicted | donor_agreement | {"CID40": 162, "STOP": 115} | 28 / 4 / 32 | 64 | -0.0397 [-0.0660, -0.0158] | -0.4152 [-0.4778, -0.3446] |
| training_cid60_anchored | current_conditional | {"CID40": 263, "EAD16": 1, "STOP": 13} | 140 / 1 / 7 | 148 | -0.0036 [-0.0116, +0.0000] | -0.0469 [-0.0717, -0.0231] |
| training_cid60_anchored | donor_agreement | {"CID40": 243, "STOP": 34} | 125 / 4 / 32 | 161 | -0.0036 [-0.0121, +0.0000] | -0.1227 [-0.1738, -0.0775] |

Hindsight ceilings and exclusive-success subsets use truth and are diagnostic only. Top-1 complementarity, full outcomes, selective-risk contrasts and donor provenance are in JSON.

## Interpretation limits

- Exploratory follow-up to training-CV reference findings; no independent validation or frozen-test claim.
- Primary cohort is 277 ambiguous training cases; all-complete results include precursor-unique cases and are secondary.
- Native track uses only predicted references; anchored track uses reserved measured CID60 references for training-library candidates only, with energy mismatch.
- The anchored track is identity-library-assisted, including held-out target CID60 when available; it is not unseen-compound prediction and does not reproduce full production reference coverage.
- All query spectra and predictor donors are train-only; non-training candidate structures/masses remain in original candidate sets, but their measured spectra are not read.
- Reference intensity aggregation is the only changed scoring input. Original reliability proxy, scorer, planner and uncalibrated acceptance thresholds are fixed.
- Risk is errors/accepted; random risk is a ratio of expected counts. Bootstrap risk intervals condition on nonzero acceptance denominators; undefined resamples are disclosed.
- Higher coverage can increase accepted errors; neither a correct-count gain nor an interval overlapping zero proves safety or non-inferiority.
- No fitted selector, calibration model, production reference update, MCP or UI work.
- Original MultiMS2 split is connectivity-grouped despite its label; this study reuses genuinely scaffold-held-out training folds without rewriting that split.

Reproduce: `make stage1-reference` after dependency installation.

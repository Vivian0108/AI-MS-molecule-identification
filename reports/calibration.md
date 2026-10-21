# Acquisition-method calibration (dev only)

*Generated 2026-10-21T06:16:28+00:00. The test split was not used.*

**Selected method:** `monte_carlo_ig`

**Reason:** Error model calibrated, dev IG rank correlation positive, and no accuracy loss versus the heuristic.

- Dev cases: 101; dev ambiguous cases: 12
- Error model calibrated: True

## Dev ambiguous-subset results

| Method | Policy | Top-1 @1 | Scans | Coverage |
|---|---|---:|---:|---:|
| monte_carlo_ig | single_scan | 0.667 | 0.00 | 0.417 |
| monte_carlo_ig | always_30 | 0.667 | 1.00 | 0.500 |
| monte_carlo_ig | always_40 | 0.833 | 1.00 | 0.583 |
| monte_carlo_ig | unknownid | 0.833 | 0.67 | 0.583 |
| disagreement_heuristic | single_scan | 0.667 | 0.00 | 0.417 |
| disagreement_heuristic | always_30 | 0.667 | 1.00 | 0.500 |
| disagreement_heuristic | always_40 | 0.833 | 1.00 | 0.583 |
| disagreement_heuristic | unknownid | 0.833 | 0.67 | 0.583 |

## IG validation on dev

| Method | Spearman(predicted, actual entropy reduction) | Pairs | Mean regret |
|---|---:|---:|---:|
| monte_carlo_ig | 0.8278565420546219 | 24 | 0.0007400047128755527 |
| disagreement_heuristic | 0.8356911465535615 | 24 | 0.0007400047128755527 |

## Error model (fitted on train identities only)

| Energy | kappa | Mean interpolation cosine |
|---|---:|---:|
| 20 eV | 11.925 | 0.694 |
| 30 eV | 11.523 | 0.597 |
| 40 eV | 24.506 | 0.828 |

The heuristic is always labelled as a template-disagreement heuristic, never as calibrated information gain.  The Monte-Carlo method is selected only when its dev predictions positively rank actual entropy reduction.

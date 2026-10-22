# Oracle-ceiling diagnosis

Frozen **test** cohort, **n = 157**. Deployed scorer: `consistent_cosine (deployed S1)`; planner: `decision_aware_risk_reduction`. Risk calibration: isotonic support calibrator fitted on dev.

This report answers *where the residual error lives*, not *how to inflate the headline number*. Every ceiling below is a diagnostic and is marked as such.

## 1. Failure taxonomy

| class | meaning | cases | share |
|---|---|---:|---:|
| **A** | Action-choice failure — exactly one extra action would have identified the truth. | 2 | 1.3% |
| **B** | Evidence-fusion failure — a correct single-action result is lost when evidence is combined. | 0 | 0.0% |
| **C** | Template failure — predicted templates fit too poorly, while a measured-template oracle would succeed. | 1 | 0.6% |
| **D** | Unresolvable chemical ambiguity — the observations do not separate the candidate pool. | 3 | 1.9% |
| **E** | Connectivity-equivalent / isomer ambiguity — competitors share the molecular skeleton. | 0 | 0.0% |
| **F** | Status failure — retrieval is right but the decision contract rejects it, or a wrong identity is accepted. | 27 | 17.2% |
| **RECOVERED** | Not a failure: the system retrieves the truth and accepts it. | 124 | 79.0% |

Classification order is deterministic and documented in `src/spectrapilot/evaluation/atlas.py`. A false identification is always class **F**; a correct top-1 followed by an abstention is also **F** but is reported separately below, because abstaining on a correct retrieval is a *coverage* outcome, not automatically a decision bug.

### Status subclasses

| subclass | cases | reading |
|---|---:|---|
| recovered | 124 | retrieved and accepted |
| abstained after correct retrieval | 24 | conservative; costs coverage, not accuracy |
| insufficient data | 0 | the available observations are too sparse |
| retrieval error | 6 | the truth is not ranked first |
| false identification | 3 | a wrong identity was accepted — the only true safety failure |

## 2. Ceilings

| quantity | value | what it bounds |
|---|---:|---|
| policy top-1 (deployed sequence) | 0.943 | the system |
| best oracle-selected action (`hindsight_best`) | 0.962 | the best a deployable action choice could reach with truth |
| CID20 only | 0.841 | free evidence |
| always CID40 | 0.943 | one fixed extra scan |
| always EAD16 | 0.834 | one fixed extra scan |
| both extra scans | 0.943 | two extra scans |

The action ceiling is **+0.019** above the deployed policy. That is the entire remaining value of perfect action selection on this cohort; it is small, and it is **not** deployable.

## 3. Is the residual gap chemistry-limited or template-limited?

`measured_separability` is the cosine gap between the truth and its strongest competitor when every candidate is scored against **its own measured spectrum** for the same action. A near-zero gap means the observation cannot separate the pool even with a perfect predictor — a chemical limit. `template_fidelity` is the cosine between the observed spectrum and the *predicted* template of the truth; a low value means the predictor, not the chemistry, is the problem.

| diagnostic | value |
|---|---:|
| cases whose pool is separable (gap ≥ 0.10) | 75.8% |
| median measured separability (multi-candidate) | 0.955 |
| median measured separability, same-formula pools (n=47) | 0.487 |
| median template fidelity | 0.501 |
| median template fidelity on failing cases | 0.323 |
| failures with information present but poor templates | 10 |
| failures that are chemistry-limited | 13 |

**Verdict.** Of the 33 non-recovered cases, 10 have a separable pool (gap ≥ 0.10) yet a truth-template fidelity below 0.30: these are **template-limited** and could in principle be repaired by a better predictor. 13 have a measured separability below 0.10: the observations do not separate the pool even with perfect templates, so they are **chemistry-limited** and no template improvement will fix them. The remaining failures are decision/coverage outcomes rather than evidence failures.

Same-formula pools have a median separability of 0.487 versus 0.955 overall: isomer ambiguity is real, but it is **not** the dominant failure mode on this cohort.

## 4. What this licenses and what it does not

Licensed:

* The observation set contains enough information for most cases; a better template would move a measurable subset of the template-limited failures.
* Formula-level evidence can only falsify different-formula distractors. It can never separate isomers, so it must not be sold as structure confirmation.
* Abstention on a correct top-1 is the main coverage cost, and it is conservative.

Not licensed:

* The `measured_separability` diagnostic cannot be used as an achievable accuracy ceiling. It uses each compound's own measured spectrum, which is unavailable for an unknown; the truth's cosine to itself is 1.0 by construction, so only the *margin* over the best distractor is meaningful.
* No number here is a blind result. The test split is `development_exposed` in this repository; every retuned v3 number is exploratory.

## 5. Reproduce

```bash
make v3-failures
```

Case-level rows: `reports/v3/failure_atlas.parquet`.

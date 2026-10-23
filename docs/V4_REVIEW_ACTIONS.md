# v4 severity remediation and follow-up

| Severity | Finding | Work |
|---|---|---|
| High | Predicted templates spuriously labelled missing library, unique mass incorrectly IDENTIFIED | Evidence-tier decision contract in session.py. Weak template evidence is AMBIGUOUS; unique mass is MASS_ONLY_MATCH |
| High | No separation of edited and raw scientific verdicts | Parallel replay of immutable raw scans, exposure of original verdict, audit trail and tests |
| Medium | Data split labeled scaffold-grouped but actual fallback connectivity | **Not retroactively fixed**: historical reports frozen. For new experiments build truly scaffold-disjoint versioned splits; any generalization claim blocked until then |
| Medium | Uncalibrated support reported as confidence | Investigation confidence=None. Relative support retained for ranking only |
| Medium | EAD vs CID comparability and CID60 proxy | Evidence-tier label REFERENCE_SUPPORTED explicitly reflects CID60 proxy, not native same-energy validation |
| Medium | Adaptive EAD gain unsupported | No gain claimed; challenge predictions explicitly heuristic and sealed |
| Medium | Local demo truth files accessible | Application-level separation unchanged; never call local bundle a cryptographically blinded evaluation |

## Claim guardrails

Keep frozen pre-v4 reports for historical comparisons only. Do not use the new decision contract with old metric numerators without rerunning evaluations and explicitly labeling the new cohort. Never call REFERENCE_SUPPORTED verified molecular truth.

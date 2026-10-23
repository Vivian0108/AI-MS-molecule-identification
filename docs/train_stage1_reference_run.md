# Stage-one reference workflow: execution record

Protocol `90259d9` preceded workflow outcomes; executable experiment is committed
as `a433dcc`. This is the requested end-to-end follow-up to the predictor-only
study, not independent confirmation or an override of its selector-training gate.

```sh
make stage1-reference PY=/private/tmp/unknownid-feas-env/.venv/bin/python
make verify PY=/private/tmp/unknownid-feas-env/.venv/bin/python
```

Another installed interpreter can be supplied through `PY`. No new dependency
was added; the existing Python 3.12 research environment was used.

Generated [Markdown](../reports/spectrapilot/train_stage1_reference.md) and
[JSON](../reports/spectrapilot/train_stage1_reference.json) contain the paired
reference-method comparison, fixed-policy baselines, risk/coverage/cost tradeoffs,
fold assignments, donor/anchor provenance and source/input hashes. The primary
contrast is the unchanged planner on ambiguous training cases with native
predicted references. The training-library CID60-anchor track and all-complete
cohort are reported separately. Reserved CID60 anchors are explicitly allowed
library measurements, not held-out predictor training data or query spectra.

The native-reference result supports a training-CV accepted-correct gain and
fewer optional acquisitions with the revised reference construction. The
anchored-track gain also increases observed accepted errors. Neither result
establishes a safe error rate, generalization to an independent test, or a
superior adaptive energy chooser. No selector or calibration model was fitted;
production references, scorer, planner, thresholds and data were not modified.

Validation: **89 tests passed in 8.90 s**, plus imports/config checks, Ruff lint
(E4/E7/E9/F), formatting and Git whitespace checks. The eight new tests cover
identical reserved anchors/reliability, actual independent product sessions and
budgets, positive/negative/tied paired intervals, undefined selective risk,
exact random-policy expectations, full report recomputation, fold isolation and
original observation hashes. All prior data/config/source/scientific report
paths have no diff against `c4dc0ee`. Existing evaluation reports remain intact.

Only ignored access logs are generated under
`data/multims2/oracle_private/train_stage1_reference/`; no full evaluation oracle
or frozen-test queries were loaded or published by this study.

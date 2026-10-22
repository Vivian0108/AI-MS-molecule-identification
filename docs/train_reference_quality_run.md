# Reference-quality check: execution record

Protocol committed as `0d6ccbe`; missing-scaffold clarification recorded as
`d0c66c2` before predictor outcomes. Executable comparison committed as
`b179c25`. Work remains on `interactive-mcp-spike`.

```sh
make reference-quality PY=/private/tmp/unknownid-feas-env/.venv/bin/python
make verify PY=/private/tmp/unknownid-feas-env/.venv/bin/python
```

Use another installed interpreter via `PY` if needed. This session used the
existing Python 3.12 research environment; no new dependencies were added.

Results are generated in
[Markdown](../reports/spectrapilot/train_reference_quality.md) and
[JSON](../reports/spectrapilot/train_reference_quality.json). Large predicted
spectra are reproducible local artifacts under the ignored
`data/multims2/oracle_private/train_reference_quality/` directory. The JSON
contains input/source hashes, fold membership, all per-target metrics and donor
provenance; it does not require the private prediction artifact for summary
recomputation or report consistency tests.

The primary weighting change substantially improved EAD spectral cosine, but
did not pass the predeclared EAD retrieval gate. No selector or calibration map
was fitted. Production references, scorer, planner, thresholds, seeds, curated
data and historical reports were left unchanged. The new check uses genuine
scaffolds derived from structures; the original MultiMS2 split's misleading
scaffold label is documented rather than rewritten.

Validation: `make verify` passed **81 tests in 5.52 s**, plus import/config checks.
The nine new tests cover clustering equivalence against the original method,
fingerprint equivalence, donor-fold/self exclusion, agreement weighting,
group-bootstrap signs, metadata projection/train-only queries, both gate
conditions, per-target summary recomputation and Markdown/JSON consistency.
Ruff lint (E4/E7/E9/F), formatting and Git whitespace checks passed. A path diff
against `128e268` verified all existing data/config/source/scientific-report
paths were unchanged by this study.

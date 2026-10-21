# Exact reproduction

## Clean clone and demo

Install uv 0.9.26 (or compatible), git and make. Python 3.12 is the reference environment;
uv can install it. Python 3.11 is also checked in CI.

```bash
git clone --branch hackathon-ready https://github.com/Vivian0108/AI_MS_molecule_identification_draft.git
cd AI_MS_molecule_identification_draft
uv sync --frozen --extra dev --python 3.12
make verify
make demo
```

Open http://localhost:8501. No fetch/prepare step is required. `make demo` forces demo
mode even when a full research oracle exists. `make app` and `make api` automatically
use demo mode when neither current nor legacy research oracle exists.

```bash
UNKNOWNID_MODE=demo make api
# In another terminal:
curl http://127.0.0.1:8000/health
.venv/bin/python scripts/rehearse_demo.py
```

The rehearsal binds temporary localhost ports, launches `make demo` and uvicorn,
checks Streamlit and API health, runs one investigation and validates both exports.
It keeps exports/logs in a temporary directory and removes them afterwards.
Tests also execute all five real Streamlit views with AppTest and check API leakage.

## Regenerate corrected benchmark without refitting

The committed curated spectra, library, split, calibration and error model are the
historical frozen artifacts. They are research inputs, separate from the demo bundle.
Do not call `make prepare` or `make calibrate` to reproduce the corrected report:

```bash
make restore-oracle
# Must print SHA256 70e29d39c875a01bc856a4d9572ec85e333eca26e3986301b341c8379416f2b0
make eval
.venv/bin/python -m pytest -q tests/test_report_consistency.py tests/test_frozen_inputs.py
```

Restoration invokes the original case/oracle construction against frozen curated
spectra. It refuses a byte-hash mismatch. It neither resplits nor refits. The full
oracle is written only to gitignored `data/oracle/private_oracle_cases.json`.
The old `.parquet` filename contained JSON bytes. Reads accept that legacy filename
when `.json` is absent; all new writes use `.json`. No Parquet decoder is used on it.

Reports and the Pareto plot regenerate from code. The Markdown consistency test
renders the JSON into the entire expected Markdown, then checks primary coverage
and accepted-correct counts from per-case rows. Never hand-edit generated tables.

For strict comparisons, use the lockfile and frozen inputs. Timestamp, runtime,
source commit and environment provenance naturally differ on a later run; scientific
metrics must not be changed manually to obtain a desired headline.

## Full research workflow

In a disposable checkout, to rebuild upstream curation and historical calibration:

```bash
make fetch-data       # pinned MassBank snapshot
make prepare          # curation, audit, split and train-only error model
make calibrate        # dev-only method choice
make eval             # frozen test evaluation
UNKNOWNID_MODE=research make app
```

These commands intentionally overwrite derived local artifacts. Preserve any frozen
benchmark files before rebuilding; this is separate from corrected-report reproduction.
The original baseline is `e5b6ad80aeb904c8bd6faed03002a8e94f1dac72` on main.
No split, filters, scoring thresholds, random seeds or fitted parameters changed on
hackathon-ready. `reports/readiness/baseline.json` records their hashes and test identities.

## Metrics and diagnostics

Stage k caps optional acquisitions at k, for k=0,1,2. Stopped policies carry their
last state forward. Optional scans count acquired 30/40 eV observations. Total
acquisitions = 1 + optional scans. Coverage counts accepted identifications, risk
is accepted errors divided by accepted identifications (undefined when none).
Accepted-correct/error per-case indicators average to rates; summaries also store
counts. Random-policy trial averages can yield fractional expected counts.
Unsuffixed JSON fields remain legacy stage-two aliases for compatibility; all
primary tables and the UI use suffixed stage-aligned fields.

Paired benefit differences are UnknownID minus comparison policy. `scans_1`
differences mean comparison-policy scans minus UnknownID scans (savings).
Wins/losses count molecules with positive/negative differences in that direction.
The diagnostics predeclare epsilon=0.02 nats, use signed entropy reductions, and
label outcome-conditioned energy-sensitive subsets as diagnostic only. Full
definitions and denominator counts are stored alongside diagnostic rows.

## Privacy and licenses

`make verify` scans the tracked tree for known credential patterns and personal
filesystem prefixes. This is a pattern scan plus review of the retained transcript,
not a guarantee against every possible secret. The raw historical session export is
removed from this branch's tree, without rewriting main or prior commits.
Original MassBank author/copyright/license fields and hashes remain with the demo.
Code MIT terms do not relicense the data. See DATA_LICENSE.md and CITATION.cff.

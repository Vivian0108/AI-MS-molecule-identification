# UnknownID

Closed-world LC-ESI-MS/MS identification with **budgeted collision-energy
selection**, an explicit abstention rule, and an honest evaluation.

The system asks a single practical question: after a 20 eV query has been
measured, is it worth spending one more acquisition at **30 or 40 eV**, or
should the investigation stop? The reference library is deliberately poor —
it contains only archived **10 and 50 eV** spectra — so every mid-energy
reference is an interpolation and every mid-energy query is a real archived
measurement revealed only on request.

> **Virtual instrument uses archived experimental measurements.** No spectra
> are generated for identification. The 30/40 eV peaks do not exist in any
> agent-facing payload until `measure` is called.

**Build transcript:** the full OpenCode session that produced this repository is
in [`chat_history/`](chat_history/). See the readable
[`transcript.md`](chat_history/transcript.md), or import the raw
[`session.json`](chat_history/session.json) into OpenCode.

---

## Headline result (read this before the tables)

On the frozen test split, the adaptive policy matched the best fixed-energy
baseline on the ambiguous cohort and used fewer acquisitions:

| Ambiguous test cohort (n = 11) | Top-1 @1 | Mean scans by first decision |
|---|---:|---:|
| Always 30 eV | 0.818 | 1.00 |
| Always 40 eV | 0.818 | 1.00 |
| Random 30/40 | 0.818 | 1.00 |
| **UnknownID adaptive** | **0.818** | **0.64** |
| Single 20 eV scan only | 0.818 | 0.00 |

No paired, molecule-level 95% bootstrap interval excludes zero for top-1
accuracy against fixed or random energy choice. **The defensible claim is
therefore cost/efficiency, not an accuracy improvement.** With only 11
ambiguous test molecules this is a proof-of-concept; the intervals are wide and
the result must not be generalized to other instruments or libraries.

The full, automatically generated report is [`reports/evaluation.md`](reports/evaluation.md).
The data audit and go/no-go gate is [`reports/data_audit.md`](reports/data_audit.md).

---

## Data

| Item | Value |
|---|---:|
| Source | [`MassBank/MassBank-data`](https://github.com/MassBank/MassBank-data), contributor `Athens_Univ` |
| Pinned commit | `befc8a1e2f2aef899747797c081a5d80fab12fe7` |
| Raw records parsed | 5,633 |
| Records passing every metadata rule | 3,707 |
| Selected molecule/energy spectra | 3,245 (724 molecules) |
| Molecules with both 10 and 50 eV references (library) | 561 |
| Complete five-energy cases | 503 |
| Cases with ≥2 precursor-consistent candidates at 10 ppm | 71 |
| Cases where 30 vs 40 eV template separation differs materially | 35 |
| Splits (scaffold-disjoint) | 302 train / 101 dev / 100 test |

Fixed stratum: Bruker maXis Impact, LC-ESI-QTOF, positive ESI, CID, `[M+H]+`,
fixed collision energy in {10, 20, 30, 40, 50} eV, reference-standard compounds
only, 10 ppm precursor consistency, redistributable licence, RDKit identity and
formula checks.

The parser never infers metadata from file names. Collision-energy ramps, NCE
percentages and ambiguous units are excluded rather than silently mapped onto
the fixed eV grid.

---

## Design

```
20 eV measured query
        │
        ▼
candidate retrieval (same [M+H]+, 10 ppm)
        │
        ▼
evidence: greedy cosine + matched fragments + neutral-loss agreement
        │
        ▼
relative support (NOT a calibrated probability)
        │
        ├── planner: expected information gain (Monte Carlo) or a labelled
        │            disagreement heuristic; chooses 30, 40, or stop
        │
        ▼
explicit measure ──► one real archived 30/40 eV spectrum
        │
        ▼
precommitted decision rule ──► identified | ambiguous | out_of_library
```

### Leakage boundary

- `ReferenceStore` accepts **only** 10 and 50 eV rows and raises on 20/30/40.
- 20/30/40 eV query records live in `data/oracle/private_oracle_cases.parquet`.
- Only `VirtualInstrument.measure` can reveal a hidden 30/40 eV spectrum. It
  enforces the budget and records every reveal in `data/oracle/access_log.jsonl`.
- The planner receives interpolated templates and relative weights. It has no
  oracle handle, no accession and no truth argument.
- The API strips the accession from the initial and measured observation until
  the investigation is stopped.
- `data/oracle/` and `data/raw/` are gitignored.
- Evaluation artefacts (`data/curated/audit_cases.parquet`,
  `reports/evaluation.*`) contain truth for scoring only. They are never loaded
  by the API or the UI; neither process reads the private oracle for ranking.

The interpolation is a transparent first-order model of both m/z and intensity
across the 10→50 eV endpoints. It is a baseline, not a replacement for the
published interpolation methods.

---

## Quick start

Requires Python 3.11 or 3.12 and `git`.

```bash
make setup          # create .venv and install the package + dev tools
make fetch-data     # sparse, pinned MassBank checkout (~5,633 records)
make prepare        # curate, audit, split, build cases and fit the error model
make demo-cases     # optional: anonymised demo case IDs
make calibrate      # choose the acquisition method on dev ONLY
make eval           # frozen test evaluation with bootstrap intervals
make test           # synthetic tests, including anti-leakage checks
```

Launch the app and API in separate terminals:

```bash
make app            # Streamlit on http://localhost:8501
make api            # FastAPI on http://127.0.0.1:8000/docs
```

`make prepare` can take a few minutes because it parses every record with RDKit.
It writes all artefacts under `data/curated/`, the sealed oracle under
`data/oracle/`, and reports under `reports/`.

---

## The five screens

1. **Provenance** — pinned commit, filter cascade, split sizes, licences,
   example records, and the explicit “archived measurements” banner.
2. **Investigation** — anonymised case browser, measured 20 eV stick spectrum,
   ranked candidates with RDKit structures, exact mass, relative support,
   per-energy cosine, matched fragments, and links to the **reference**
   accessions (10/50 eV only). Includes measured-vs-interpolated mirror plots.
3. **Next experiment** — predicted IG or labelled separation heuristic for 30
   and 40 eV, interpolation reliability, cost, budget, and explicit Measure
   buttons. Prediction is visually separated from measurement.
4. **Final report** — before/after ranking, spectral evidence, QC checks,
   released measurement accessions, honest verdict, limitations, and Markdown /
   JSON export.
5. **Evaluation** — test-split policy tables, accuracy@0/1/2, scans, paired
   bootstrap intervals, planner validation, failure breakdown, and the
   open-world stress test.

Candidate support is always labelled **relative support, not a calibrated
identity probability**. No ECE, Brier score or reliability diagram is claimed
because no probability calibration was validated.

---

## API

Start the server with `make api`. Interactive docs: `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | library size, sealed cases, planner method |
| `GET` | `/provenance` | source commit, filters, split sizes, audit values |
| `GET` | `/cases?split=test` | anonymised case summaries |
| `POST` | `/cases/start` | start a case (`case_id` optional, `split` optional) |
| `GET` | `/cases/{id}/ranking` | current candidate evidence |
| `POST` | `/cases/{id}/plan` | recommended 30/40 eV action, or stop |
| `POST` | `/cases/{id}/measure` | reveal **one** hidden measurement |
| `POST` | `/cases/{id}/stop` | freeze the verdict and release accessions |
| `GET` | `/cases/{id}/report` | final JSON, only after stop |
| `GET` | `/cases/{id}/report.md` | final Markdown, only after stop |

`measure` returns `409` for a second reveal of the same energy, an exhausted
budget, a disallowed energy, or a stopped investigation.

---

## Evaluation

Policies: precursor-only, single 20 eV scan, always-30, always-40, random,
cheap disagreement, UnknownID adaptive, and a truth-aware diagnostic ceiling.
Random averages 20 seeded trials per molecule. CIs resample **molecules**, not
spectra or energies.

Selected on dev: `monte_carlo_ig`. Error-model reliability is highest at 40 eV
(mean cosine 0.828), lower at 20 eV (0.694) and 30 eV (0.597). The planner's
predicted acquisition value has a dev Spearman correlation of ≈0.83 with the
actual entropy reduction. Test thresholds were frozen before evaluation.

Known failure modes, reported rather than hidden:

- Two ambiguous test cases are same-connectivity / stereoisomer pairs that
  MS/MS cannot separate; the system abstains instead of guessing.
- In the open-world stress test (true molecule removed), 6 of 11 cases with an
  alternative candidate were confidently matched to a wrong library compound.
  This is the most important negative result in the project: open-world
  rejection is **not** solved.
- Accuracy is saturated on precursor-unique cases (89% of test), so the
  ambiguous subset is the only scientifically informative one.

### What may not be claimed

De novo structure elucidation, open-world identification, cross-instrument
generalization, enantiomer discrimination, clinical/regulatory validity, or
control of a real mass spectrometer. The true compound is in the library by
construction.

---

## Tests

```bash
make test
# 44 passed
```

Six synthetic suites cover the parser, RDKit/chemical QC, energy and split
boundaries, oracle isolation, planner behaviour, and metrics/baselines. The
tests use artificial spectra only; they are never mixed with the MassBank
evaluation. Anti-leakage tests assert that a fresh instrument exposes only the
20 eV observation, that budget and allowed energies are enforced, that the
oracle property raises, and that the public-case contract has no truth fields.

---

## Repository layout

```
app/streamlit_app.py              five-screen UI
chat_history/                     readable transcript + full OpenCode session export
config/selection.yaml             fixed data stratum
config/acquisition.yaml           planner, likelihood, confidence rule
data/curated/                     manifests, library, cases, splits, audit
data/oracle/                      private hidden spectra + access log (gitignored)
reports/data_audit.md             real filter counts and go/no-go gate
reports/calibration.md            dev-only method selection
reports/evaluation.md             frozen test results
src/unknownid/
  io/massbank_parser.py           conservative tag parser
  data/curate.py                  RDKit QC and curation
  data/splits.py                  scaffold-disjoint splits
  core/                           spectra, templates, retrieval, evidence, posterior
  planner/                        Monte-Carlo IG + heuristic + error model
  simulator/oracle.py             sealed oracle and budgeted instrument
  simulator/episodes.py           investigation session and report export
  eval/                           baselines, metrics, bootstrap, open-world test
  api/app.py                      FastAPI backend
  service.py                      shared service for API and UI
scripts/                          fetch, prepare, calibrate, evaluate, demo cases
tests/                            synthetic tests (44)
```

---

## Reproducibility

- Snapshot commit and record hashes are stored in `data/manifest.json`.
- Split seed `20261020`; planner Monte-Carlo seed `20261020`; 20 random-policy
  trials per molecule.
- Every curated artefact and report is regenerated by the commands above.
- `reports/evaluation.json` contains per-case metrics, paired comparisons,
  planner validation, failures and open-world rows.
- Environment: Python 3.12, RDKit 2026.09.1, matchms 0.33.1, pandas 3.0.6,
  numpy 2.5.4, Streamlit 1.66.0, FastAPI 0.156.4 (see `pyproject.toml`).

## Licence and attribution

Code: MIT. MassBank records retain their original CC BY / CC BY-SA licences;
see each record and the upstream repository. If you use the data, cite
MassBank and the spectral-interpolation paper referenced in
`config/selection.yaml`.

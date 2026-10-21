# Hackathon readiness

Work is on `hackathon-ready`. Historical `main` remains at
`e5b6ad80aeb904c8bd6faed03002a8e94f1dac72`; no history was rewritten or merged.

## Completed work

- [x] Read the baseline README, implementation specification, evaluation, audit and calibration.
- [x] Confirmed clean checkout and created hackathon-ready from main (no remote branch existed).
- [x] Recorded baseline configuration/model/calibration hashes and all frozen test identities in [baseline.json](reports/readiness/baseline.json).
- [x] Corrected paired comparison signs, intervals and wins/losses, with artificial win/loss/tie tests.
- [x] Corrected independent oracle 30/40 branches, deterministic ties and zero budget.
- [x] Added ranking, selective metrics and optional-scan counts at stages 0/1/2.
- [x] Regenerated evaluation JSON, Markdown and Pareto visualization from code.
- [x] Added exact Markdown/JSON rendering consistency and frozen-input tests.
- [x] Added energy-choice and stop diagnostics with predeclared epsilon and explicit denominators.
- [x] Bundled four attributed train/dev demonstrations with no frozen-test identities or spectra, including endpoint references.
- [x] Added automatic demo fallback, explicit mode banner, one-command launch and end-to-end smoke tests.
- [x] Added Python 3.12 lockfile and GitHub Actions matrix for 3.11/3.12.
- [x] Added formatting, lint, import/config checks and publication scan.
- [x] Added MIT code license, data-license notice and citation file.
- [x] Added JSON filename migration with legacy-read compatibility.
- [x] Sanitized readable transcript and removed raw session export from this tree.
- [x] Rewrote README, captured all five screens, and prepared three-minute script and judge answers.
- [x] Rehearsed a clean temporary clone with locked dependency installation and no pre-existing private oracle.

## Verification results

| Environment / check | Exact result |
|---|---|
| Unmodified baseline, Python 3.12.12 | 44 passed in 1.58s (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`) |
| Final local suite before clean clone | 61 passed, 1 warning in 5.12s |
| Clean clone, locked Python 3.12.12, `make verify` | 61 passed, 1 warning in 47.40s; Ruff check/format, imports, configs and publication scan passed |
| Clean clone, locked Python 3.11.14, `make verify PY=…` | 61 passed, 1 warning in 42.23s; same checks passed |
| Real HTTP clean-clone rehearsal | PASS: make demo, Streamlit health, API /health, plan, archived measurement, stop, JSON/Markdown exports |
| Five real Streamlit screens | AppTest passed; actual Safari screenshots captured and reviewed |
| Demo isolation | 4 train/dev cases, 9 reference molecules, 18 endpoint spectra; all 30 raw source hashes/licenses checked; no frozen-test identity/reference/observation in bundle |
| Frozen inputs | Selection, acquisition, split, error model and calibration hashes unchanged |
| Historical oracle restoration | Byte-exact SHA256 `70e29d39c875a01bc856a4d9572ec85e333eca26e3986301b341c8379416f2b0` |
| Frozen-report regeneration in clean clone | Pending final comparison; see final verification update below |

The one warning is the installed Starlette/FastAPI TestClient deprecation of its
httpx compatibility transport. It does not fail any test. CI is configured; the
results above are local matrix results, not a claim that hosted Actions has run.
No untracked file was needed for demo startup. Tests create gitignored local logs.

## Demo command

```bash
make setup
make demo
```

Open [the local demo](http://localhost:8501). No dataset fetch/preparation is needed.
Force the API into demo mode with `UNKNOWNID_MODE=demo make api`.
No hosted demo is configured.

## Supported scientific claims

The frozen ambiguous test cohort contains **11 molecules**, defined without hidden
energy outcomes. At stage one, UnknownID and always-40 each accept 9 correct
identifications, with zero observed accepted errors. UnknownID uses 7 optional
measurements versus 11. Mean savings are **0.3636 optional scans/molecule**, with
paired molecule-bootstrap 95% CI **[0.0909, 0.6364]**. Four molecules differ in scan
use. Total acquisitions average **1.6364 versus 2.0**.

The observed efficiency result supports the project's uncertainty-aware stopping
story on this cohort. Top-1 remains 9/11 across spectral policies. The corrected
stage-one table reveals always-30 accepts 8/11, not the 9/11 stage-two count that
was previously mixed with stage-one scan cost. The corrected oracle accepts 9/11
at stage one, compared with 8/11 in the historical sequential diagnostic.

## Unsupported claims and known limitations

- No supported accuracy advantage over fixed/random energy selection; no proof of equivalence or noninferiority.
- Zero observed selective errors does not establish zero population risk.
- Only 11 ambiguous frozen test molecules, one homogeneous instrument cohort and two optional energies.
- Relative support is not calibrated identity probability; correlated acquisitions may overstate evidence.
- Under the declared diagnostic help rule, 2/4 stops miss potential entropy/decision benefit; this is reported rather than hidden.
- Energy-sensitive subsets are outcome-conditioned diagnostics only; they do not redefine evaluation eligibility.
- Open-world rejection remains unsolved: 6/11 cases with alternative library candidates are confidently wrong when truth is removed.
- No de novo identification, cross-instrument generalization, clinical/regulatory validity or real instrument control.
- Demo includes training examples and is curated for illustration. Its outcomes are not independent evidence.
- No optional grouped cross-validation estimate is included.
- Filesystem readers can inspect demo sealed data; isolation is an application boundary, not encryption.
- The publication scan checks known patterns and retained content. Historical main/commits retain their original transcript; history was deliberately not rewritten.

## Review links

- [Judge-facing README](README.md)
- [Exact reproduction commands](REPRODUCIBILITY.md)
- [Generated scientific report](reports/evaluation.md) and [JSON](reports/evaluation.json)
- [Pareto visualization](reports/pareto.svg)
- [Five screenshots](docs/screenshots/)
- [Three-minute judge presentation](docs/JUDGE_DEMO.md)
- [Judge questions and answers](docs/JUDGE_QA.md)
- [Demo bundle and case origins](data/demo/README.md)
- [Data attribution](DATA_LICENSE.md) and [MIT code license](LICENSE)

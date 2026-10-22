# SpectraPilot hackathon readiness

**Status: local demonstration ready.** Work is on `hackathon-measurement-triage`, created from `interactive-mcp-spike` at `5fb4d99`. No merge or push to main was performed.

## Completed

- [x] One investigation screen: observe → choose/stop → report.
- [x] Three curated development examples: resolve, stop and abstain.
- [x] One optional acquisition; total acquisitions include the initial CID20.
- [x] Observed-peak exclusion with reason, reversible undo and audit history.
- [x] JSON and Markdown downloads; explicit source-identity check after stopping.
- [x] Standalone 310,341-byte demo bundle with accession attribution, pinned source, CC0 notice and checksums.
- [x] Application boundary keeps unrevealed measured spectra and evaluator identity out of initial evidence/planning responses.
- [x] Minimal locked dependencies, separate research lock, Python 3.11/3.12 demo CI and Python 3.12 full-suite CI.
- [x] MIT code license, data-license notice, sanitized historical transcript. Raw session omitted from this branch.
- [x] Judge README, screenshots, three-minute script, FAQ and reproducibility commands.
- [x] Existing `reports/`, `configs/` and `data/multims2/` unchanged relative to `5fb4d99`.

## Exact verification results

Rehearsal date: 2026-10-22. A temporary **local clean Git clone** was created from this branch, without private research oracles or untracked files. Network installation used hash verification against the committed lockfiles. The working directory's user data and any existing service on port 8501 were preserved.

| Check | Result |
|---|---|
| Before demo implementation, historical test suite | 89 passed in 8.90 s |
| Clean Python 3.12.12 research-lock environment, `make verify` | 100 passed in 7.16 s; imports and configs passed |
| Clean Python 3.12.12 demo-lock environment, `make demo-verify` | 11 passed in 1.76 s |
| Clean Python 3.11.14 compatible demo-lock environment | 11 passed in 2.76 s |
| Formatting and Ruff E4/E7/E9/F for new/refactored demo Python files | Passed |
| Clean-clone Streamlit startup via `make demo DEMO_PORT=18502` | Passed |
| Clean-clone API startup and `/health`, port 18001 | Passed; demo mode, three cases |
| Live API start → measure → stop → JSON/Markdown export | Passed, including two fresh runs and pre-stop identity rejection |
| Headless Chrome against clean-clone Streamlit | All three cases and actual JSON/Markdown downloads passed |
| Bundle-only runtime | Passed with research Parquet access explicitly prohibited by tests |
| Bundle report fields vs existing scientific JSON | Passed |
| Bundle cases vs dev split, exact three-case oracle, nine source accessions | Passed |
| Tracked text scan for personal home paths and common credential patterns | No matches; best-effort pattern scan plus transcript cleanup |

All pytest runs emitted one upstream Starlette/httpx deprecation warning. Tests pass; runtime requests work. GitHub Actions are configured but have not run on a remote host because this branch has not been pushed. The final UI change collapses the audit expander by default so report downloads remain prominent; the final clean-clone full-suite run at source commit `5157cc6` includes that presentation change. A separate final local demo run passed 11 tests in 1.67 s.

The existing numerical research reports were deliberately **not regenerated** for this demo task. Full scientific regeneration needs the separately prepared research inputs and oracle. The bundle builder was run successfully from the available training/development inputs; it does not require reading frozen test spectra. The three demo cases were chosen openly using development outcomes, without tuning thresholds.

## Run and show

From this repository directory after installing `requirements-demo.lock` with Python 3.12:

```bash
make demo
```

Local UI: **http://127.0.0.1:8502**. This is not a hosted public demo. Optional API: `make demo-api`, port 8001. The UI does not require the API.

- [README and quick start](README.md)
- [Three-minute presentation script and FAQ](docs/JUDGE_DEMO.md)
- [Reproducibility](docs/DEMO_REPRODUCIBILITY.md)
- [Screenshots](docs/screenshots/02-observe.png): [measure](docs/screenshots/03-measure.png), [report](docs/screenshots/04-report.png), [stop](docs/screenshots/05-stop.png), [abstain](docs/screenshots/06-abstain.png), [results](docs/screenshots/07-results.png)
- [Generated scientific report](reports/spectrapilot/train_stage1_reference.md)
- [Bundle provenance](data/demo/build_manifest.json)
- [Code license](LICENSE) and [data licenses](DATA_LICENSE.md)

## Presentation simplification

The default screen now focuses on **What do we know? → What should we do? → What changed?**. The main action is **Collect one more spectrum** or **Finish & create report**. A before/after comparison explains resolution or continued uncertainty; the stop example states the optional measurement avoided. Technical spectra, scores, alternative actions, interventions and audit data are collapsed. Judge instructions and all seven screenshots were updated.

Verification after this UI change: 11 demo tests passed; Ruff formatting/lint checks passed; headless Chrome completed all three outcomes and both report downloads, and confirmed scientific evidence is initially collapsed. The scientific model, configurations, data bundle and generated scientific reports were unchanged.

## Supported claims

The application demonstrates archived measurement reveal, candidate rescoring, a stop decision, abstention, reversible observed-peak interventions and evidence exports. It can run from the committed development bundle without a full dataset rebuild.

In the existing exploratory grouped training-CV estimate of 277 ambiguous MultiMS2 molecules, the library-assisted planner used **243 optional scans versus 277** for always-CID40, with **156 versus 157 accepted-correct and 15 accepted errors each**. That is a 12.3% scan reduction with one fewer accepted-correct outcome in this sample. The separate predicted-reference comparison increased accepted-correct from 20 to 49 with three errors each; it must not be conflated with the library-assisted tradeoff.

## Unsupported claims and remaining limits

- No new independent accuracy validation, equivalence guarantee, or established adaptive energy/modality-choice advantage. The studied planner chose CID40 or stop, never EAD.
- Closed-world candidate library; no de novo or validated open-world identification, stereoisomer resolution, hardware translation or live instrument control.
- Curated development cases are not independent evidence. Their labels intentionally preview demonstration roles.
- Support is an uncalibrated relative score. Accepted identifications can be wrong.
- The demo uses permitted development CID60 library anchors; the energy mismatch is disclosed. Reference prediction remains experimental.
- The oracle boundary is application-level. Anyone with filesystem access can inspect the redistributable development data. The API is local and single-user; starting a case replaces its earlier session.
- No hosted deployment or remote CI execution yet. Full research reproduction requires separate source inputs.
- The removed raw historical session remains in earlier Git history; this work did not rewrite history. No credential-pattern matches were found, but the scan is not a guarantee against every secret format.

## Dependency lock checksums (SHA-256)

- `requirements-demo.lock`: `2841757f05a562f715985231a6b7e27b46098d10b7a746e185e2620bb6d36128`
- `requirements-demo-py311.lock`: `cc7adfefc5b8419764e1dcb935dbc7d9319e0fab06f89a21520d3047866aa693`
- `requirements-research.lock`: `83971afba4e7e816377c7fea0364e6d70e7873bd6cc7e32f09b3e3eaa8d2a7b1`

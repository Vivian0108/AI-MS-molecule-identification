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

## Original clean-clone verification results

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

All pytest runs emitted one upstream Starlette/httpx deprecation warning. Tests pass; runtime requests work. GitHub Actions are configured but have not run on a remote host because this branch has not been pushed. These clean-clone results predate the presentation-only workspace redesign; post-redesign tests and browser checks are reported below.

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
- [Workspace](docs/screenshots/01-workspace.png), [measurement](docs/screenshots/03-measured.png), [fragment evidence](docs/screenshots/04-evidence-cid40.png), [report](docs/screenshots/05-report.png), [validation](docs/screenshots/06-validation.png), [stop](docs/screenshots/10-stop.png), [abstain](docs/screenshots/11-abstain.png)
- [Generated scientific report](reports/spectrapilot/train_stage1_reference.md)
- [Bundle provenance](data/demo/build_manifest.json)
- [Code license](LICENSE) and [data licenses](DATA_LICENSE.md)

## Workspace redesign

The demo is now a single analysis workspace rather than a staged, role-play flow. Each sample opens on the acquired CID20 spectrum, the mass-compatible shortlist and a live assessment. The right rail states the current decision, support, margin, best fit and the recommended next step. The primary actions are **Acquire CID40** or **Create report**; after an extra scan the shortlist updates in place and labels the leader change. Supporting detail sits behind **Method**, **Validation**, **Reference library**, **Peak tools** and **Report preview** dialogs instead of occupying the main flow.

The screen uses neutral **Sample 1/2/3** labels, thin rules, tabular numbers and a restrained teal/green/amber status system. It does not use narrative steps, progress games or fictional instrument controls. Every score, candidate ordering and measurement comes from the unchanged scientific service.

Verification after the redesign: **14 demo tests passed** in the existing Python 3.12 demo environment; Ruff E4/E7/E9/F and formatting checks passed. Headless Chrome reviewed the initial workspace, post-measurement ranking, CID40 evidence comparison, report export, validation, method, peak tools, reference library, stop and abstain states, plus the settled 900 px narrow layout. The scientific model, configurations, data bundle and generated scientific reports were unchanged.

### Structure and evidence explanation

All 15 public candidate structures are rendered from SMILES and committed as SVGs, with source/output hashes and the RDKit build version. No RDKit is required at runtime. Chemical names are shown where provided; entries without a supplied common name are labelled by structure family and ring-OH pattern. For the resolve case, OH positions distinguish five structures that share formula C15H12O4. The evidence dialog compares measured peaks with the selected and comparison references, reports per-observation cosine similarity, and lists matches for the three strongest non-precursor peaks. Exclusions and undo are reflected in the display. Unacquired actions are rejected; the explanation performs no measurement and cannot access truth.

The CID40/CID60 mismatch and the distinction between a fingerprint match and a bond-level fragment assignment are disclosed in the dialog and method notes.

### Guided investigation story

The interaction is now **workspace → assessment → recommended acquisition or stop → report**. Sample 1/2/3 labels replace outcome spoilers in the UI and API catalog. The optional experimental spectrum is revealed only after the measurement action. The Reference library dialog exposes the 15 bundled structures and distinguishes predicted fingerprints from CID60 library proxies. The curation audit remains intact for reproducibility.

Verification: **14 demo tests** cover neutral API labels, automatic workspace startup, ranking changes after measurement, report downloads, identity reveal, reset, stop and abstention. The research suite targets the unchanged scientific code and was not rerun for this presentation-only redesign. Numerical science, frozen configurations and reports were not changed.

### Visual presentation

The workspace is a light, instrument-like console: a narrow sample rail, a measured-spectrum panel, an inline candidate table with structure drawings and support bars, and a right-hand assessment rail. There are no hero panels, numbered journey strips, candidate cards or before/after game cards. Green/amber status styling reflects the current decision rule; it does not assert source-identity correctness. Layouts adapt to narrower screens and keep the Method/Validation controls available.

All spectra and structure drawings remain based on the existing data; no decorative spectrum or fabricated result was introduced. Chrome verified all three outcomes, evidence dialogs, report downloads and the narrow-screen layout. The original scientific configuration and reports were unchanged.

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

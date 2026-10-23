# SpectraPilot

**Molecule identification from mass spectra, with a stop-or-measure decision.**

Mass spectrometry often produces several candidate structures that all fit the same precursor mass. SpectraPilot combines fragment evidence with a measurement planner. It shows which candidates the data support, recommends one additional archived scan when that scan is likely to separate them, and stops when more data is not worth the instrument time.

`measured spectrum → mass-compatible candidates → fragment evidence → measure again or stop → auditable report`

## Why it matters

Every optional MS/MS acquisition costs instrument time. A useful identification assistant should do more than return a ranked database hit: it should show the evidence, say when the candidates remain unresolved, and record why it continued or stopped.

## What the demo shows

The local Streamlit demo contains three curated development samples. Together they illustrate the three possible outcomes:

- one extra scan resolves the leading candidates;
- the current evidence is already sufficient, so the system stops;
- the candidates remain ambiguous even after the optional scan, and the report says so.

The app shows the measured spectrum, candidate structures, fragment-level evidence, a live assessment and the recommended next step. Final reports are available as Markdown and JSON. The samples are labelled neutrally, so the outcome is not revealed before the analysis.

## Run it

Requirements: Python 3.12, Git and Make.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-demo.lock
make demo
```

Open **http://127.0.0.1:8502** and choose a sample. The demo bundle is committed under [`data/demo/`](data/demo/README.md); no full dataset, private oracle or research download is needed.

Useful commands:

```bash
make demo-verify          # 14 demo and evidence checks
make demo-api             # optional API on :8001
make demo DEMO_PORT=8503  # if :8502 is already in use
```

## What we measured

In an exploratory scaffold-grouped training cross-validation study of **277 ambiguous molecules**, the library-assisted planner used:

- **243 optional acquisitions vs 277** when always collecting CID40 (**12.3% fewer**)
- **156 vs 157 accepted-correct identifications** (correct results among the cases it chose to identify)
- **15 accepted errors in each arm**

This is a measured tradeoff, not evidence of equivalent accuracy. See the [generated scientific report](reports/spectrapilot/train_stage1_reference.md).

## How it works

1. **Shortlist** candidates whose precursor mass matches within 10 ppm.
2. **Score** each candidate against the measured fragment peaks and reference fingerprints.
3. **Decide** whether support, margin, fit and matched peaks meet the identification rule.
4. **Plan** one additional archived measurement when it is expected to separate the top candidates; otherwise stop.
5. **Record** the spectra, ranking, evidence, interventions and limitations in a report.

The contribution is the measurement-triage and audit layer. Spectral-library matching, cosine scoring, spectral interpolation and the source MassBank/MultiMS2 data are prior work. This prototype is not a validated new fragmentation predictor or an autonomous laboratory agent.

## Scope and limitations

- **Closed-world library identification**, not de novo structure elucidation.
- The three demo samples are **curated development illustrations**, not independent validation.
- **No live instrument** and no hosted deployment; the demo runs locally on archived spectra.
- CID60 library spectra are used as **CID40 proxies**, and the energy mismatch is disclosed in the app.
- Relative support is a ranking score, **not a calibrated identity probability**.
- No general accuracy advantage is claimed. The planner chose CID40 or stop; an adaptive CID-versus-EAD advantage was not established.
- The older frozen MassBank benchmark is separate and must not be pooled with these results.

## Repository map

- `app/spectrapilot_demo.py` — demo UI
- `src/spectrapilot/` — scientific code and planner
- `src/unknownid/` — earlier UnknownID implementation
- `data/demo/` — committed demo bundle and licenses
- `reports/spectrapilot/` — generated scientific reports
- `scripts/` — research and data-preparation scripts

More detail:

- [Screenshots](docs/screenshots/)
- [Three-minute judge script and FAQ](docs/JUDGE_DEMO.md)
- [Reproducibility and provenance](docs/DEMO_REPRODUCIBILITY.md)
- [Readiness checklist](HACKATHON_READINESS.md)
- [Historical UnknownID research workflow](docs/UNKNOWNID_RESEARCH.md)

For the research environment, use `requirements-research.lock` and run `make verify`. Regenerating the scientific reports requires the separately prepared source dataset and private oracle.

## License

Code is [MIT](LICENSE). The bundled MultiMS2 data is CC0-1.0 with accession-level attribution; historical MassBank licensing is separate. See [DATA_LICENSE.md](DATA_LICENSE.md).

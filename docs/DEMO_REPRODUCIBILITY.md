# Demo reproducibility

Use the `hackathon-measurement-triage` branch. Code uses Python 3.12 for the demo rehearsal. Hash-locked demo and research dependencies were generated on Python 3.12 using `uv pip compile --python-version 3.12 --universal --generate-hashes`; installing the demo needs no uv and no full dataset. Python 3.11 CI uses the separately resolved `requirements-demo-py311.lock`; the local clean-clone rehearsal uses Python 3.12. Dependency versions are frozen in the lockfiles, rather than re-resolved by `make setup`.

## Minimal clean installation

```bash
git clone --branch hackathon-measurement-triage <repository-url> spectrapilot
cd spectrapilot
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-demo.lock
make demo-verify
make demo
```

The committed bundle under `data/demo/` contains three development cases and all reference and query data needed for the interaction. It contains no frozen test spectra and no full private evaluation oracle. The runtime neither reads the research Parquet tables nor accesses external services. `make demo` uses port 8502 and `make demo-api` uses 8001. `/health` returns demo mode. The API is a local, single-user demonstration: posting `/investigations` starts that case afresh and replaces its previous local session; it is not a multi-user investigation server.

## Full tests and research environment

In a separate Python 3.12 virtual environment:

```bash
python3.12 -m venv .research-venv
.research-venv/bin/python -m pip install --require-hashes -r requirements-research.lock
make verify PY=.research-venv/bin/python
```

This runs unit, integration, UI, configuration and import checks. Demo tests also compare the committed results panel with the existing generated scientific JSON. No test requires fetching a private oracle. `.research-venv/` should be kept outside the repository or excluded locally.

## Rebuilding the curated bundle (research maintainers only)

Not required to launch or verify the demo. It requires the existing prepared MultiMS2 research dataset and separate development oracle. Run with the full research environment:

```bash
PYTHONPATH=src .research-venv/bin/python scripts/build_spectrapilot_demo.py
```

The builder uses development cases, training donors and permitted train/development CID60 library references; it does not load frozen test spectra. It explicitly selects development outcomes for resolve/stop/abstain illustrations. The build manifest stores source/config hashes, builder hash, build commit, timestamp and artifact hashes. The source commit identifies the checkout used to generate the bundle; the builder hash identifies the precise script, including any changes made before its commit. Runtime verifies public/instrument artifact and configuration hashes, and checks evaluator identity only on an explicit post-stop request.

The underlying scientific reports are existing generated artifacts and are not regenerated or altered for the demo. Their protocols and runner commands are in `docs/train_stage1_reference_protocol.md`, `docs/train_stage1_reference_run.md`, `docs/train_reference_quality_protocol.md` and `docs/train_reference_quality_run.md`. Re-running those studies requires the separately prepared full research inputs and is outside demo setup. No new training or threshold selection occurred during demo implementation.

## Provenance and licenses

MultiMS2 is pinned in `configs/multims2.yaml` and the bundle manifest to source commit `9219d19d8ef370a1ef0eadf0594b7dfe5e2bf83a`. The upstream data notice is retained in `data/demo/DATA_LICENSE.txt`; per-query record IDs, USIs, scan IDs and source attribution are retained in `data/demo/instrument/attribution.json`. Public reference donor/anchor provenance is in `data/demo/public/reference_provenance.json`. Code is MIT; MultiMS2 data is CC0-1.0. Historical MassBank data retains its individual record licenses. See `DATA_LICENSE.md`.

Truth separation is an application boundary, not cryptographic secrecy. Local users can inspect the bundle. A curated source identity check never changes a decision that has already been stopped.

## Structure and fingerprint display

Committed SVG structures in `app/assets/structures/` are generated from the public candidate SMILES by `scripts/render_demo_structures.py`, using RDKit only at build time. Launching the demo needs no RDKit. The adjacent manifest records the source hash, each SVG hash, SMILES and RDKit version. OH-ring counts are derived from public connectivity; unnamed entries remain explicitly unnamed. Rebuild, if needed, with the research Python environment:

```bash
.research-venv/bin/python scripts/render_demo_structures.py
```

The visible fingerprint comparison reads only an already acquired observation and public references. It reapplies active peak exclusions and uses the existing scorer to reproduce per-observation peak matches and cosine similarity. It cannot collect a new measurement or select an unobserved spectrum. Whole-fingerprint similarity is distinct from the combined ranking, and matched peaks are not validated bond/fragment assignments.

## Discovery-led investigation

The UI and `/cases` API catalog use neutral Sample 1/2/3 titles. The original bundle retains its curation audit for reproducibility, but role labels do not name samples in the application. The workspace opens on the initial measured spectrum, the mass-compatible shortlist and the live assessment; the optional measurement is revealed only on request. This is presentation over the unchanged scientific service; it does not change thresholds or reveal optional spectra. The Reference library dialog shows the 15 bundled structures and reference sources.

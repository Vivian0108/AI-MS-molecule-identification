# SpectraPilot curated development bundle

This bundle contains three real MultiMS2 development examples: resolving an
ambiguity, stopping with sufficient evidence, and abstaining after measurement.
They were chosen using known development outcomes to illustrate those paths.
They are not independent evaluation evidence or an accuracy estimate.

- `public/`: candidate metadata, predicted/allowed reference templates, case
  metadata, result summaries and reference provenance. No truth mapping or
  hidden target spectra.
- `instrument/`: initial CID20 and hidden CID40/EAD16 measurements for exactly
  these three development cases, plus acquisition attribution. Only the virtual
  instrument reads hidden measurement payloads.
- `evaluator/`: source identity and selection audit. The app reads identity only
  on an explicit request after stopping; the planner never receives this data.
- `build_manifest.json`: hashes and build provenance. Research data is not needed
  at runtime. Rebuild intentionally with `scripts/build_spectrapilot_demo.py`
  only when the local curated research data is available.

All query spectra are archived experimental data. Reference spectra use the
experimental donor-agreement consensus trained on training donors, plus allowed
CID60 library references from train/development records. The reference has an
explicit energy mismatch when used for CID40. No frozen test spectra are read
by the builder.

The sealing is an application/API boundary. A person with repository filesystem
access can inspect the intentionally redistributable development bundle. It is
not a cryptographic access-control system. No arbitrary-file tool is exposed.

Data is CC0-1.0; preserve the upstream notice in `DATA_LICENSE.txt` and the
accessions/attribution. See the repository's `DATA_LICENSE.md`.

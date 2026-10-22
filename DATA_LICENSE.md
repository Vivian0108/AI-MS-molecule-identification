# Data and attribution

The code license is [MIT](LICENSE); it does not relicense third-party data.

The small SpectraPilot demo uses MultiMS2 data from Zamboni Lab, pinned to commit
`9219d19d8ef370a1ef0eadf0594b7dfe5e2bf83a`. The upstream data directory is released
under CC0-1.0. The verified upstream notice is preserved at
[data/demo/DATA_LICENSE.txt](data/demo/DATA_LICENSE.txt).

- Source: https://github.com/zamboni-lab/MultiMS2
- Dataset paper: https://doi.org/10.1093/gigascience/giag069
- Acquisition accessions, scan IDs, collection labels, USIs and license fields:
  `data/demo/instrument/attribution.json` (instrument-side provenance).
- Permitted library-reference accessions and prediction donor identities:
  `data/demo/public/reference_provenance.json`.
- Selection and original source identity: separate `data/demo/evaluator/` files.

Three outcome-selected development cases illustrate behavior; they are not
independent evaluation evidence. No frozen test measurements or full private
evaluation oracle are in the demo bundle. Predicted spectra are labelled as
structure-neighbour references; they are not new experimental measurements.

The separate historical UnknownID workflow uses MassBank records with their own
per-record LICENSE and attribution fields, including CC BY and CC BY-SA records.
Keep those notices and attribution when redistributing records or adaptations;
CC BY-SA adaptations retain their applicable share-alike terms. These MassBank
records are not included in the new MultiMS2 demo bundle. Their licenses are
not replaced by the code's MIT license or MultiMS2's CC0 notice.

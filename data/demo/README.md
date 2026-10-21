# Demo mode — curated development examples

Four curated **train/dev** cases illustrate mechanics, not independent evidence.
No frozen test identities, test endpoint references or test observations are bundled.
Selection inspected development outcomes only, without changing evaluation filters.
Two resolving examples originate in training data and must not be described as validation.

| Case | Original split | Illustration |
|---|---|---|
| case-127895a5f433 | train | Initial ambiguity resolved at 40 eV; 30 eV remains ambiguous |
| case-250b6ac895d0 | dev | Correct identification and stop from initial evidence |
| case-e40ea5350560 | dev | More evidence, but continued ambiguity and abstention |
| case-f1a2b961ba46 | train | Both energies help; 40 eV has materially larger entropy reduction |

`public_cases.parquet` contains metadata and candidate IDs. `library.parquet` contains
only 10/50 eV reference spectra, with the original complete candidate lists.
`sealed_observations.json` is server-side virtual-instrument data. The application
never returns truth, and reveals hidden peaks only through an explicit measurement.
`source_records/` and `attribution.json` preserve original attribution and license
information and are not loaded by the planner or returned in agent payloads.

This is an application boundary, not encryption against a judge reading repository files.
The full research oracle stays gitignored. Frozen fitted model and calibration remain
in `data/curated/` and are reused without refitting. Full research data are never read by
the demo reference store or instrument.

Run `make demo` after `make setup`. See [data licensing](../../DATA_LICENSE.md).

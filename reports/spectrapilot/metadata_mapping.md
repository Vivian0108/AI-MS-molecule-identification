# MultiMS2 metadata mapping

The parser reads MGF key/value headers and never infers identity from a file name.
Required fields are rejected if absent. Values are preserved in `records.parquet`.

| MGF header | Canonical field | Use |
|---|---|---|
| `FILENAME` | `filename` | source provenance and scan grouping |
| `EXTRACTSCAN` | `scan_id` | source scan provenance |
| `COMPOUND_NAME` | `name` | display only; exact identity comes from InChIKey |
| `INCHIAUX` | `compound_full_inchikey` | identity and split grouping |
| `SMILES` | `canonical_smiles` | RDKit structure validation |
| `FORMULA` | `formula` | formula cross-check |
| `PRECURSOR_MZ` | `precursor_mz` | 10 ppm precursor filter |
| `ADDUCT` | `adduct` | fixed to `[M+H]+` |
| `IONMODE` | `ion_mode` | fixed to positive |
| `FRAGMENTATION_METHOD` | `fragmentation_method` | CID or EAD |
| `COLLISION_ENERGY` | `energy_value` | modality-specific numeric grid |
| `INSTRUMENT_NAME` | `instrument_model` | fixed to ZENOTOF7600 |
| `DESCRIPTION` | `source_collection` | MSMLS/NEXUS/SELLECK covariate |
| `SOURCE_SCAN_USI` | `usi` | independent accession |
| `QUALITY_CHIMERIC` | `quality_chimeric` | requires `PASSED` |
| `QUALITY_EXPLAINED_INTENSITY` | quality flag | reported, not hidden |
| `NUM_PEAKS` | peak-count check | must match parsed peaks |

No raw-header value is silently repaired. Missing or contradictory required fields
fail closed and are counted in `data/multims2/curated/audit.parquet`.

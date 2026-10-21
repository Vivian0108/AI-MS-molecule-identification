# UnknownID data audit

*Generated 2026-10-21T06:15:54+00:00 from the frozen MassBank `Athens_Univ` snapshot.*

## Snapshot

- Source: `https://github.com/MassBank/MassBank-data` (`Athens_Univ/`)
- Commit: `befc8a1e2f2aef899747797c081a5d80fab12fe7`
- Retrieved: 2026-10-21T06:15:53+00:00
- Raw record files: **5633**
- Parsed records: **5633**
- Records passing every rule: **3707**
- Citation: Augmentation of MS/MS Libraries with Spectral Interpolation for Improved Identification, J. Chem. Inf. Model. 2022, doi:10.1021/acs.jcim.2c00620

> This snapshot count is not the 549-compound literature cohort.  The 549 figure belongs to the published study; this audit reports only what survived the frozen filters below.

## Inclusion cascade

| Rule (cumulative) | Records surviving |
|---|---:|
| same instrument model | 5158 |
| LC-ESI-QTOF | 5158 |
| MS2 | 5158 |
| positive ion mode | 4467 |
| ESI | 4467 |
| CID | 4467 |
| [M+H]+ | 4320 |
| reference standard | 4320 |
| redistributable license | 4320 |
| fixed eV collision energy | 3747 |
| CE on 10/20/30/40/50 grid | 3747 |
| peak count consistency | 3747 |
| non-empty spectrum | 3747 |
| chemical QC | 3707 |

Individual exclusion reasons overlap; the cascade above is the authoritative count.

### Most frequent exclusion reasons

| Reason | Records |
|---|---:|
| `wrong_adduct` | 1074 |
| `precursor_mass_inconsistent` | 1074 |
| `wrong_ion_mode` | 691 |
| `collision_energy_not_fixed_ev` | 629 |
| `wrong_instrument_model` | 475 |
| `wrong_ionization` | 475 |
| `wrong_instrument_type` | 475 |
| `charged_parent` | 47 |

## Cohort composition

| Collision energy | Selected spectra |
|---|---:|
| 10 eV | 689 |
| 20 eV | 682 |
| 30 eV | 663 |
| 40 eV | 619 |
| 50 eV | 592 |

- Instrument model: `Bruker maXis Impact` (all selected spectra)
- Ionisation / mode / fragmentation: `ESI`, `POSITIVE`, `CID`
- Adduct: `[M+H]+` (all selected spectra)
- Fixed collision energies only; ramps and NCE were excluded (`629` records).

### Licenses (raw records)

| License | Records |
|---|---:|
| CC BY | 4687 |
| CC BY-SA | 946 |

Only CC BY / CC BY-SA records were curated. Raw peaks remain in `data/raw/`; derived artefacts preserve per-record accession, license and SHA256 in `data/manifest.json`.

## Chemical identity and mass QC

- Distinct full InChIKeys: **724**
- Distinct 2D connectivity blocks: **719**
- Distinct molecular formulas: **666**
- Reference library molecules with both 10 and 50 eV spectra: **561**
- Complete five-energy cases: **503**
- Partial cases (kept separately, never imputed): **221**
- Median absolute precursor mass error ([M+H]+, 10 ppm gate): **0.090 ppm**
- 95th percentile: **0.220 ppm**; maximum: **0.397 ppm**

Adducts other than `[M+H]+`, GC-APCI records, multi-component salts and records with inconsistent formula/SMILES/mass were excluded rather than repaired.  The proton mass (1.007276466621 Da) was used for ion correction.

## Spectral QC

| CE | Records | Mean peaks | Min | Median | Blank | <3 peaks |
|---|---:|---:|---:|---:|---:|---:|
| 10 eV | 689 | 6.3 | 1 | 4 | 0 | 107 |
| 20 eV | 682 | 15.2 | 1 | 8 | 0 | 44 |
| 30 eV | 663 | 27.3 | 1 | 12 | 0 | 52 |
| 40 eV | 619 | 35.3 | 1 | 16 | 0 | 54 |
| 50 eV | 592 | 38.5 | 1 | 18 | 0 | 54 |

- Molecule/energy pairs: **3245**; pairs with replicate records: **436**; maximum replicates: **3**.
- Representative selection is precommitted and outcome-blind: highest retained peak count, then earliest accession.  Replicates never straddle reference and oracle.
- Preprocessing: invalid peaks removed, peaks below 1% base peak removed, base peak normalised to 1. The same rule is applied to reference, query and oracle spectra.

## Difficulty analysis

| Quantity | Value |
|---|---:|
| Complete cases | 503 |
| Cases with >=2 precursor-consistent candidates at 10 ppm | 71 |
| Cases with >=3 candidates | 31 |
| Precursor-only unique cases | 432 (85.9%) |
| Initial 20 eV top-1 accuracy | 483/503 (96.0%) |
| Close-call ambiguous (>=2 candidates and top-2 support margin <= 0.15) | 27 |
| Primary ambiguous subset (>=2 precursor-consistent candidates) | 71 |
| Close-call subset (>=2 candidates and top-2 support margin <= 0.15) | 27 |
| Cases where top-2 template separation differs by >=0.05 between 30 and 40 eV | 35 |
| Diagnostic: cases where the 30 vs 40 oracle gives a different top-1 outcome | 6 |

The initial ranking uses only the 20 eV observation and templates interpolated from the 10/50 eV references.  The 20/30/40 eV oracle spectra are not used to choose cases.

### Split summary

| Split | Molecules | Cases | Ambiguous cases |
|---|---:|---:|---:|
| train | 302 | 302 | 48 |
| dev | 101 | 101 | 12 |
| test | 100 | 100 | 11 |

Deterministic seed: `20261020`; scheme: `bemis_murcko_scaffold_then_identity`.  No molecule ID is shared between splits.

## Go / no-go gate

| Target | Required | Observed | Status |
|---|---:|---:|---|
| Complete cases | >=100 | 503 | PASS |
| Precursor-ambiguous cases | >=30 | 71 | PASS |
| Cases with nontrivial 30/40 choice | >=15 | 35 | PASS |

**Decision:** GO for a proof-of-concept active-identification evaluation.

The 549-compound/5-energy figure in the literature is a cohort description, not this audit's post-filter count.  No mass tolerance was widened to manufacture ambiguity.

## Sample provenance

| Accession | CE | Compound | License | URL |
|---|---:|---|---|---|
| `MSBNK-Athens_Univ-AU101101` | 10 eV | Sulfadiazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU101101 |
| `MSBNK-Athens_Univ-AU101501` | 10 eV | Sulfamethoxypyridazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU101501 |
| `MSBNK-Athens_Univ-AU101806` | 10 eV | Sulfamethoxazole | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU101806 |
| `MSBNK-Athens_Univ-AU100802` | 20 eV | Sulfamethazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU100802 |
| `MSBNK-Athens_Univ-AU100902` | 20 eV | Sulfadimethoxine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU100902 |
| `MSBNK-Athens_Univ-AU101102` | 20 eV | Sulfadiazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU101102 |
| `MSBNK-Athens_Univ-AU100803` | 30 eV | Sulfamethazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU100803 |
| `MSBNK-Athens_Univ-AU100903` | 30 eV | Sulfadimethoxine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU100903 |
| `MSBNK-Athens_Univ-AU101103` | 30 eV | Sulfadiazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU101103 |
| `MSBNK-Athens_Univ-AU100804` | 40 eV | Sulfamethazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU100804 |
| `MSBNK-Athens_Univ-AU100904` | 40 eV | Sulfadimethoxine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU100904 |
| `MSBNK-Athens_Univ-AU101104` | 40 eV | Sulfadiazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU101104 |
| `MSBNK-Athens_Univ-AU100805` | 50 eV | Sulfamethazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU100805 |
| `MSBNK-Athens_Univ-AU100905` | 50 eV | Sulfadimethoxine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU100905 |
| `MSBNK-Athens_Univ-AU101505` | 50 eV | Sulfamethoxypyridazine | CC BY-SA | https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU101505 |

## Audit artefacts

- `data/curated/audit.parquet` — tidy metric table
- `data/curated/audit_cases.parquet` — per-case difficulty and diagnostics
- `data/curated/splits.json` — frozen molecular splits
- `data/manifest.json` — snapshot commit and per-record SHA256/license
- `data/curated/public_cases.parquet` — anonymised cases, no hidden peaks
- `data/oracle/private_oracle_cases.json` — evaluator-only hidden observations

## Audit limitations

- The candidate universe is the 561-molecule endpoint-reference library; this is a closed-world, library-supported identification task, not de novo structure elucidation.
- Accurate-mass filtering substantially reduces ambiguity; the ambiguous subset here is smaller than the cohort and is reported separately.
- 20/30/40 eV templates are interpolated from 10/50 eV references.  The oracle spectra are authentic measurements, but the reference templates are not independent measurements at those energies.
- Stereo- and constitution-isomer ambiguity can remain unresolved by MS/MS alone.

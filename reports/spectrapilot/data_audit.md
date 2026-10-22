# SpectraPilot data audit — MultiMS2

Pinned commit: `9219d19d8ef370a1ef0eadf0594b7dfe5e2bf83a`  
MGF SHA-256: `4ef86f75a12ad2fdadbd63732e2d6690f4e506a6ff08f171758c1808d1249673`

| Stage | Count |
|---|---:|
| Raw MGF blocks | 43,728 |
| Positive `[M+H]+` records | 23,660 |
| Records passing QC | 22,326 |
| One representative per compound × action | 9,235 |
| Compounds in candidate universe | 2,115 |
| Complete CID20/CID40/EAD16 cases | 1,068 |

## Split sizes

| Split | Cases |
|---|---:|
| train | 737 |
| dev | 174 |
| test | 157 |

## Ambiguity

- Cases with at least two candidates at 10 ppm: **416 / 1,068**.
- Median candidate count: **1**; max **8**.
- Same-formula structural-isomer cases: **416** precursor-ambiguous; exact formula overlap is reported in the casebook.

## Go/no-go

- Two-action complete cases: **1,068** (preferred target ≥100).
- Predeclared precursor-ambiguous cases: **416** (preferred target ≥30).
- The primary cohort is complete and large enough for a held-out benchmark. The
  EAD template is a train-only structure-kNN prediction, not a hidden target spectrum.

The complete case list and truth are in `data/multims2/evaluator_private/truth.parquet`.
Agent-facing artefacts never contain the truth column.

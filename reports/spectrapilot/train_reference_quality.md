# Train-only reference quality and reliability

**Grouped cross-validated training estimate; not an independent test.**

737 complete training molecules, 277 precursor-ambiguous training cases, five scaffold-held-out folds. No development/test query spectra, fitting on outer outcomes or production changes.

All methods predict native-action references from non-held-out training donors. Retrieval is native-action cosine-only ranking over each ambiguous case's original candidates; it is not stage-one accepted-correct identification.

| Action | Method | n | Mean cosine | Median cosine | Ambiguous top-1 | Ambiguous MRR | Reliability Spearman |
|---|---|---:|---:|---:|---:|---:|---:|
| CID20 | current_conditional | 737 | 0.0366 | 0.0005 | 137/277 | 0.7213 | 0.440 |
| CID20 | donor_agreement | 737 | 0.0878 | 0.0004 | 155/277 | 0.7532 | 0.463 |
| CID20 | nearest_neighbor | 737 | 0.0828 | 0.0000 | 145/277 | 0.7339 | 0.434 |
| CID40 | current_conditional | 737 | 0.1200 | 0.0549 | 158/277 | 0.7639 | 0.514 |
| CID40 | donor_agreement | 737 | 0.2378 | 0.0739 | 175/277 | 0.7966 | 0.487 |
| CID40 | nearest_neighbor | 737 | 0.2187 | 0.0096 | 143/277 | 0.7292 | 0.451 |
| EAD16 | current_conditional | 737 | 0.0547 | 0.0429 | 133/277 | 0.7114 | 0.240 |
| EAD16 | donor_agreement | 737 | 0.3079 | 0.2616 | 142/277 | 0.7314 | 0.160 |
| EAD16 | nearest_neighbor | 737 | 0.1353 | 0.0952 | 133/277 | 0.7076 | 0.271 |

## Paired alternatives minus current consensus

Intervals resample whole scaffold groups, preserving all molecules in each sampled group.

| Action | Alternative | Mean cosine gain | 95% CI | Native retrieval top-1 gain | 95% CI |
|---|---|---:|---|---:|---|
| CID20 | donor_agreement | +0.0512 | [+0.0355, +0.0689] | +0.0650 | [+0.0292, +0.1020] |
| CID20 | nearest_neighbor | +0.0462 | [+0.0276, +0.0686] | +0.0289 | [-0.0307, +0.0842] |
| CID40 | donor_agreement | +0.1178 | [+0.0979, +0.1419] | +0.0614 | [+0.0157, +0.1116] |
| CID40 | nearest_neighbor | +0.0987 | [+0.0730, +0.1250] | -0.0542 | [-0.1200, +0.0072] |
| EAD16 | donor_agreement | +0.2533 | [+0.2372, +0.2694] | +0.0325 | [-0.0076, +0.0785] |
| EAD16 | nearest_neighbor | +0.0806 | [+0.0719, +0.0897] | +0.0000 | [-0.0732, +0.0751] |

## Predeclared next-step gate

**NO-GO** for a learned-selector follow-up under this protocol.

- EAD donor-agreement mean cosine gain ≥0.05 and positive lower CI: True.
- EAD native-action top-1 gain ≥0.05 and positive lower CI: False.
- Both conditions must pass. Nearest-neighbour results are secondary and do not automatically pass this gate.

## Source split audit

The saved candidate-universe table lacks the scaffold column computed during QC. The source split is labelled scaffold-grouped but the preparation function therefore uses connectivity fallback for every compound. Stored split reproduced exactly by that fallback: True. The saved split was not changed. This study derives real Bemis-Murcko scaffolds from SMILES for its five training-only folds.

## Replicates and measured reference diagnostic

Retained independent same-compound/action duplicate rows: 0. Rows with metadata replicate_count >1: 3912. The curated artifact keeps one representative; independent replicate validation was not performed.

CID40 query versus same-compound CID60 reference (different energies, diagnostic only): n=614, median cosine=0.5798.

## Limitations

- Train-only grouped cross-validation estimates; development and frozen test queries were not loaded.
- Fixed three-method comparison with one predeclared primary contrast; no tuning or selected-model generalization claim.
- Native-action cosine retrieval is a predictor diagnostic, not stage-one product acceptance or a planner benchmark.
- Same candidate sets and chemical filters; non-training library structure metadata is allowed, but no non-training measured peaks.
- Proxy reliability is descriptive, not a calibrated probability; no fitted calibration map or learned selector.
- Consensus spectra are structure-neighbour transfers, not a mechanistic fragmentation model.
- Stored predicted spectra are ignored local study artifacts; source/input hashes and donor provenance are recorded.
- No independently retained replicate pairs; metadata repeat counts do not establish independent validation.

Reproduce: `make reference-quality` after dependency installation.

# Training and evidence-quality report

Generated from the current tree in 67.1 s.

## 1. Risk calibration (deployed)

A one-dimensional isotonic map from the support of the top candidate to P(top-1 correct), fitted on the **development** split and applied unchanged to test. The support score comes from the deployed consistent-cosine scorer, not from the ranker.

| quantity | value |
|---|---:|
| dev Brier | 0.0636 |
| dev rows | 522 |
| test Brier (map applied unchanged) | 0.0676 |
| mean calibrated P(top-1) on test | 0.889 |
| observed top-1 on test | 0.873 |

The map transfers: dev and test Brier differ by 0.0040. This is the opposite of the ranker result below, and the contrast is the point.

### Calibration step function

| support ≥ | calibrated P(correct) |
|---:|---:|
| 0.171 | 0.000 |
| 0.207 | 0.500 |
| 0.295 | 0.600 |
| 0.520 | 0.750 |
| 0.536 | 0.778 |
| 0.560 | 0.800 |
| 0.577 | 0.828 |
| 0.622 | 0.917 |
| 0.982 | 1.000 |

### Reliability on test (applied map)

| support range | n | mean support | observed accuracy |
|---|---:|---:|---:|
| [0.170, 0.519] | 94 | 0.431 | 0.479 |
| [0.519, 0.983] | 94 | 0.708 | 0.883 |
| [0.985, 1.000] | 94 | 0.999 | 1.000 |
| [1.000, 1.000] | 94 | 1.000 | 1.000 |
| [1.000, 1.000] | 94 | 1.000 | 1.000 |
| [1.000, 1.000] | 1 | 1.000 | 1.000 |

## 2. Candidate ranker (negative result — not deployed)

A histogram-gradient-boosting candidate classifier with scaffold-grouped out-of-fold calibration. Full detail: `data/multims2/curated/ranker_v3.report.json`.

| quantity | value |
|---|---:|
| training rows | 4788 |
| training episodes | 737 |
| scaffolds | 527 |
| features kept | 36 |
| OOF AUROC | 0.9668301280160463 |
| OOF Brier | 0.07170045173039231 |
| OOF top-1 | 0.9365671641791045 |
| fit time | 27.3 s |

**Verdict: rejected.** On the multi-candidate test pools the ranker reaches top-1 0.478, while simply ranking by cosine reaches 0.612. Train OOF is 0.937, so the gap is generalisation, not optimisation: train-only kNN templates are optimistically good for train compounds, and the model learns pool-composition features that do not transfer to held-out scaffolds. We therefore deploy the low-capacity support calibrator above and report the ranker as a negative result rather than tuning it on test.

### Transfer check (multi-candidate test pools)

| scorer | n pools | top-1 on pools | top-1 overall |
|---|---:|---:|---:|
| raw_cosine | 67 | 0.612 | 0.834 |
| calibrated_ranker | 67 | 0.478 | 0.777 |

## 3. Do predicted template peaks actually appear?

For every dev compound, the template peaks above 5% relative intensity are checked against that compound's own measured spectrum (20 mDa tolerance). This is the evidence behind the template-trust score.

| action | source | compounds | mean fraction observed | median | mean reliability | mean presence-model P |
|---|---|---:|---:|---:|---:|---:|
| CID20 | train_only_structure_knn | 274 | 0.037 | 0.029 | 0.164 | 0.253 |
| CID40 | reference_cid60 | 240 | 0.717 | 0.714 | 0.750 | 0.508 |
| CID40 | train_only_structure_knn | 46 | 0.090 | 0.072 | 0.200 | 0.312 |
| EAD16 | train_only_structure_knn | 211 | 0.171 | 0.170 | 0.101 | 0.147 |

Interpretation: the `reference_cid60` track validates well; the structure-kNN tracks, especially EAD16, do not. That is why the decision contract only lets a trustworthy, provenance-recorded action contribute independent MS/MS support, and why the planner rarely spends a scan on EAD16.

## 4. Reproduce

```bash
make v3-train
```

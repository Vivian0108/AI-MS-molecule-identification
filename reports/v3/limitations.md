# Limitations

Everything below is a limit of the **current evidence, code state, and evaluation
protocol**, not a roadmap of intentions. Where a number is quoted it is
reproducible from a file in `reports/v3/` and the command that produced it is
listed at the end of the section.

---

## 1. The headline result is a negative one

v3 does **not** produce a significant top-1 retrieval gain.

| comparison | Δ top-1 | 95% paired bootstrap | McNemar p |
|---|---:|---|---:|
| v3 full adaptive (M7) vs v2 always-CID40 (M1) | **+0.006** | [−0.013, +0.032] | 1.000 |
| v3 full adaptive (M7) vs v2 separation (M4) | **+0.006** | [−0.019, +0.032] | 1.000 |
| v2 always-CID40 (M1) vs v2 CID20-only (M0) | +0.102 | [+0.051, +0.159] | 0.001 |

The only significant retrieval effect is the old one: **one extra CID40 scan is
worth about ten points**, and that was already true in v2. Everything v3 adds on
top of that is within noise on this cohort.

What v3 *does* change is measured and reproducible:

* the decision contract no longer reports a unique mass match as
  `OUT_OF_LIBRARY` (v2 CID20-only accepted **3%** of cases; v3 accepts **52%**
  at the same retrieval accuracy — see `coverage_regression_cases.csv`);
* **68 of 68** cases that v2's separation policy abstained on while
  always-CID40 identified are accepted under the v3 contract, at unchanged
  retrieval accuracy;
* accepted coverage rises from 0.70 (v2 always-CID40) to 0.81, at the cost of a
  slightly higher false-identification rate at coverage (0.018 → 0.024). That is
  a real trade-off, not a free win: the extra 11 points of coverage come from
  mass-only matches, 17 of which are accepted without MS/MS support. The v2
  *separation* baseline accepts far fewer cases (0.27) and is wrong on 4.8% of
  them, so it looks better only because it almost never answers;
* the "stronger evidence" scorer (S1, consistent cosine) is a **wash**: it moves
  top-1 by one case and costs ~4 points of MS/MS coverage plus one false ID;
* risk is calibrated instead of being a raw softmax weight;
* the cost / proof-tier trade-off is exposed as an explicit frontier rather
  than a single operating point.

Read `paired_benchmark.md` before quoting any single number.

**Artifacts:** `paired_benchmark.json` (`paired`, `models`).

---

## 2. The test split is `development_exposed`, so nothing here is blind

The repository froze the test split *before* v3 work began, but the same 157
cases have been used for v1, v2 and now v3 development. Every v3 number on
`test` is therefore **exploratory**, not a blind holdout result. The v2 numbers
that were frozen earlier remain the only pre-registered ones.

We mitigate this by:

* fitting the calibrator on **dev** and applying it unchanged to test;
* selecting the open-world detection score on **dev**;
* predeclaring the cohorts (full test n=157; ambiguous test n=67; dev n=174 for
  calibration only) and never filtering cases after seeing outcomes;
* reporting the failure atlas on the full cohort, not a success subset.

Mitigation is not a substitute for a truly held-out cohort. A genuine v3 claim
would need a fresh, never-inspected split.

**Artifacts:** `paired_benchmark.json` (`cohorts`, `split_status`).

---

## 3. Predicted templates are the weak link

Measured on dev, the fraction of a template's high-intensity predicted peaks
that actually appear in that compound's own spectrum (20 mDa tolerance):

| action | template source | compounds | mean fraction observed | mean reliability |
|---|---|---:|---:|---:|
| CID20 | `train_only_structure_knn` | 274 | **0.037** | 0.164 |
| CID40 | `reference_cid60` (real reference) | 240 | **0.717** | 0.750 |
| CID40 | `train_only_structure_knn` | 46 | 0.090 | 0.200 |
| EAD16 | `train_only_structure_knn` | 211 | **0.171** | 0.101 |

The consequence is structural, not cosmetic:

* **CID40 support is real only when a CID60 reference exists.** That covers
  88.5% of test cases. Where it does not, CID40 has the same near-useless
  structure-kNN template as everything else.
* **CID20 kNN predicts almost nothing at peak level (3.7%).** The v2 system
  nevertheless used it as if it were evidence. v3 keeps it for ranking (its
  *relative* ordering is weak but not zero) and stops treating a low fit as
  proof of absence.
* **EAD16 templates are effectively unusable.** Median reliability 0.082,
  only 0.8% of candidate templates reach 0.30, and 17.1% of predicted peaks are
  observed. This is why the planner almost never spends a scan on EAD16, and why
  the "always EAD16" arm is indistinguishable from CID20-only (0.834 top-1,
  3% MS/MS coverage under the strict contract).
* Template reliability medians for test candidates: CID20 0.139 (12.9% ≥ 0.30);
  CID40 kNN 0.153 (16.7% ≥ 0.30); EAD16 0.082 (0.8% ≥ 0.30).

### The S1 scorer did not help

With the action fixed at CID40 and the same v3 contract:

| scorer (S) | top-1 | MS/MS cov. | any cov. | false-ID |
|---|---:|---:|---:|---:|
| S0 legacy cosine | 0.936 | 0.739 | 0.847 | 0.015 |
| S1 consistent cosine (deployed) | 0.943 | 0.701 | 0.809 | 0.024 |

S1 moves one case in top-1 and loses about six MS/MS acceptances. The differences
are all within noise. S1 remains the deployed scorer only because it was the
predeclared v3 model; choosing S0 now, after seeing the comparison on a
development-exposed split, would be post-hoc selection. **No v3 gain is
attributed to the scorer.**

**Artifacts:** `features_ablation.csv` (S0/S1 rows),
`fragment_prediction_validation.csv`,
`fragment_prediction_validation_summary.csv`, `training_report.md` §3.

---

## 4. The learned candidate ranker failed and is not deployed

This was the largest expected win in the spec (P2) and it did not work.

| quantity | value |
|---|---:|
| training rows / episodes / scaffolds | 4,788 / 737 / 527 |
| out-of-fold AUROC | 0.967 |
| out-of-fold Brier | 0.072 |
| out-of-fold top-1 | 0.937 |
| **test multi-candidate top-1** | **0.478** |
| **plain cosine ranking on the same pools** | **0.612** |

Why: train-only structure-kNN templates are optimistically good for train
compounds (their nearest donors are close analogues), so a model fitted on train
learns template-quality and pool-composition shortcuts that do not transfer to
held-out scaffolds. The decisive comparison is in
`ranker_transfer_check.csv`, holding the policy fixed at CID20-only.

We report the ranker as a **negative result** and deploy the low-capacity
consistent-cosine scorer instead. It is possible that a listwise ranking
objective, hard-negative mining, or a genuinely held-out template source would
help; we did not demonstrate that, and tuning on test would not demonstrate it.

**Artifacts:** `ranker_transfer_check.csv`, `training_report.md` §2,
`features_ablation.csv` (S2 row),
`data/multims2/curated/ranker_v3.report.json`.

---

## 5. Risk calibration is valid but low-capacity

The deployed risk is a **one-dimensional isotonic map** from the support of the
top candidate to P(top-1 correct), fitted on dev (n = 522 case × sequence rows)
and applied unchanged to test.

| quantity | dev | test |
|---|---:|---:|
| Brier score | 0.0636 | **0.0676** |
| mean calibrated P(correct) | 0.893 | 0.889 |
| observed top-1 | 0.893 | 0.873 |

The map transfers, which is exactly what the 36-feature ranker did not do. But:

* It is **marginal** calibration over the whole cohort, not per-case. It cannot
  know that a particular support = 0.75 case is wrong.
* Support saturates at 1.0 whenever the precursor-consistent pool has one
  candidate. The map therefore assigns P = 1.0 to 90 of 157 test cases, and the
  3 false identifications all live in that saturated region. The calibrated
  error of 0.0 is *not* a guarantee.
* Because it is one-dimensional, it cannot express "the top candidate fits, but
  the runner-up fits equally well"; the decision engine handles that with a
  separate margin/support rule, not with the calibrator.

**Artifacts:** `training_report.md` §1, `training_summary.json`.

---

## 6. The decision-aware planner optimises a stated utility, not expected information gain

`RiskAwareDecisionPolicy` reports `score_type = "SUPERVISED_RISK_PROXY"`. Its
score is

```
( current_risk × P(resolve) + proof_tier_value × P(resolve) ) / cost
```

where `P(resolve)` is a sigmoid of pairwise template separation times average
template trust, and `proof_tier_value` (default **0.30**) is a utility weight for
upgrading `MASS_ONLY_MATCH` → `MSMS_SUPPORTED`. This is **not** a calibrated
expected information gain, and the `P(resolve)` term is a heuristic.

The consequence is visible in the frontier:

| proof_tier_value | mean scans | top-1 | MS/MS coverage | any coverage |
|---:|---:|---:|---:|---:|
| 0.00 | 0.45 | **0.949** | 0.28 | 0.81 |
| 0.05 | 0.91 | 0.949 | 0.69 | 0.80 |
| 0.30 (default) | 0.95 | 0.943 | 0.70 | 0.81 |

At the default the planner is essentially "always CID40" (0.95 vs 1.00 scans)
because most cases have a unique candidate and the proof-tier term makes
confirming them worth a scan. The cost saving only appears when the operator
prices MS/MS confirmation at zero — at which point the system honestly accepts
mass-only matches. **We do not claim the planner saves scans at equal proof
quality.** We claim the trade-off is explicit and sweepable.

The planner also never explores a two-scan policy (the budget is 1), so the
"both actions" arm is an offline ceiling, not a deployable behaviour.

**Artifacts:** `accuracy_cost_frontier.csv`, `paired_benchmark.md`.
**Code:** `src/spectrapilot/planning/decision.py`.

---

## 7. Open-world detection works only with an absolute-fit score, and it is not deployment-grade

Hard-unknown episodes remove the truth **and every alias of it** from the
candidate pool, keeping the precursor-consistent distractors. That is a
deliberately hard test: the system cannot notice that no candidate shares the
precursor mass.

| score | dev AUROC | selected |
|---|---:|---|
| relative softmax support (1 − support) | 0.569 | no |
| absolute best-candidate fit (1 − max cosine) | **0.732** | **yes** |

Applied unchanged to test:

| quantity | value |
|---|---:|
| AUROC | **0.774** |
| AUPRC | 0.693 |
| in-library false-accept (at dev 95th pct) | 0.038 |
| unknown false-accept | 0.537 |
| **unknown detection** | **0.463** |

So the absolute fit carries real signal, unlike the relative support (which is
normalised over the pool and is at chance). But a detection rate of 46% at a 4%
in-library false-accept rate means **more than half of hard unknowns are still
accepted**. This is a diagnostic, not a validated open-world gate: the system
does not currently use it to override a decision, and it should not until a
larger unknown set is available. The 67 hard-unknown episodes are exactly the
test cases with ≥ 2 candidates; single-candidate cases cannot be made "hard
unknown" without emptying the pool, so the unknown set is not representative of
all unknowns either.

**Artifacts:** `open_world_hard_subset.csv`, `paired_benchmark.json`
(`open_world`).

---

## 8. `MASS_ONLY_MATCH` is a coverage tier, never MS/MS confirmation

The v3 contract separates:

* `MSMS_SUPPORTED` — independent spectral support from a provenance-recorded
  action (currently: a real `reference_cid60` CID40 spectrum, or a sufficiently
  reliable predicted template, plus support and margin thresholds);
* `MASS_ONLY_MATCH` — a unique precursor-consistent library candidate with no
  independent spectral support;
* `AMBIGUOUS`, `INSUFFICIENT_DATA`, `OUT_OF_LIBRARY` — abstentions.

`MASS_ONLY_MATCH` is counted in `accepted_coverage` and **never** in
`msms_accepted_coverage`. This is the single most important semantic difference
from v2, where the same situation was either silently `IDENTIFIED` or
`OUT_OF_LIBRARY` depending on an unrelated cosine threshold.

Two limits follow:

* The `any coverage` number (0.81) is *not* a structural identification rate.
  It is "the system returned a unique mass-consistent answer". On this cohort
  17 of the 127 accepted cases are mass-only.
* False identifications are reported **at coverage**, because coverage and
  accuracy trade off directly. At the default operating point the v3 system
  accepts 127/157 cases and is wrong on 3 (0.024). Those 3 are the entire safety
  budget; see §5 for why calibration does not exclude them.

**Artifacts:** `paired_benchmark.md` (model matrix), `failure_atlas.parquet`
(`status_subclass_counts`).

---

## 9. The oracle-ceiling diagnostic is a diagnostic, not an achievable bound

`oracle_ceiling.md` reports:

* 124/157 recovered; 33 non-recovered (27 F, 3 D, 2 A, 1 C);
* of the 33, **10 have information present but poor templates** and **13 are
  chemistry-limited** (measured separability < 0.10);
* action ceiling 0.962 vs deployed 0.943 (+0.019) — the total value of perfect
  action selection on this cohort;
* pool separable in 75.8% of cases; median measured separability 0.955 overall
  but **0.487 for same-formula pools** (47 cases);
* median template fidelity 0.501; 0.323 on failures.

Caveats that must travel with those numbers:

* `measured_separability` scores each candidate against **its own measured
  spectrum**. The truth's cosine to itself is 1.0 by construction, so only the
  *margin over the best distractor* is meaningful. It is not an accuracy
  ceiling and cannot be converted into one.
* The failure taxonomy is a deterministic heuristic (`evaluation/atlas.py`). A
  correct top-1 followed by abstention is class F, which is why F (27) is much
  larger than the 3 false identifications. Read the status subclasses, not the
  letter, for safety questions.
* "Chemistry-limited" assumes the measured reference spectrum is itself
  informative; a bad reference spectrum would be misclassified as chemistry.
* The +0.019 action ceiling is measured with `hindsight_best`, which uses the
  hidden truth to choose the action. It is an upper bound on what better action
  selection could buy, not something a policy can reach.

**Artifacts:** `oracle_ceiling.md`, `failure_atlas_summary.json`,
`failure_atlas.parquet`.

---

## 10. Data, chemistry and instrument scope

* **One instrument, one adduct, one polarity.** All 1,068 cases are
  `[M+H]+` on `ZENOTOF7600`. Nothing here validates negative mode, other
  adducts, or other instruments.
* **Three source collections** (NEXUS 1,062; SELLECK 5; MSMLS 1), so the cohort
  is effectively one collection. Collection-specific artefacts cannot be
  separated from chemistry.
* **The candidate pool is built from precursor mass only.** A compound absent
  from the library and every isomer of it cannot be retrieved; the open-world
  result in §7 is the only measurement of that failure mode, and it is weak.
* **Sub-formula (MSBuddy) evidence is CID-only.** `SubformulaBackend` refuses
  EAD, so no fragment-level claim is made for EAD16. The S3 ablation therefore
  uses neutral-loss plausibility (pure formula arithmetic), which can only
  penalise different-formula candidates — it is structurally incapable of
  separating isomers, and indeed moves top-1 by 0.000.
* **Library spectra are reference measurements, not ground-truth structures.**
  A "correct" retrieval means "matches the curated InChIKey", which inherits any
  curation error in MassBank/MultiMS2.

---

## 11. Reproducibility limits

* All v3 changes are **uncommitted working-tree changes** on branch
  `spectrapilot-v3` at the time of writing. Hashes of the data artifacts are in
  `v2_reproduction.json`, but the code hash must be taken from the commit that
  follows.
* `v2_reproduction.md` regenerates the frozen v2 numbers from the current tree
  behind `decision_version="v2_legacy"`. It matches the previously frozen
  results exactly (always-CID40 0.936 top-1, separation 0.936 / 0.268 coverage),
  which is the regression guard for every refactor.
* The random-scan baseline uses 5 repetitions in `v3-eval` (20 in `v3-audit`)
  for runtime; its interval is correspondingly wider.
* `.venv` is local. `make v3-*` assumes dependencies from `make setup` are
  installed, plus `matplotlib` and `scikit-learn`.

---

## 12. The demo is a CLI dossier, not the specified web UI

`make v3-demo` writes `demo_case_dossier.md`: six sections per case (intake,
available evidence, sealed precommit hash, measurement, hypothesis validation,
decision + counterfactual). It exercises the same `InvestigationSession` API a
UI would call, and the precommit hash is computed before the hidden spectrum is
requested.

It is **not** a Streamlit/FastAPI six-screen application. There is no upload
flow, no interactive counterfactual control, and no persistence layer. Treat the
dossier as evidence that the workflow and the precommit mechanism work, not as a
product surface.

**Artifacts:** `demo_case_dossier.md`, `demo_case_dossier.json`.

---

## 13. What would actually be needed to move the needle

In rough order of expected value, and none of it is done here:

1. **A real CID40 template source for the 11.5% of cases without a CID60
   reference.** The reference track is the only evidence that predicts peaks
   (71.7%); extending it is worth more than any reranker.
2. **A held-out, never-inspected cohort** so the v3 contract changes can be
   measured blind.
3. **A calibrated, per-case error model with an interaction between support and
   margin** — the 1-D isotonic map saturates and cannot separate "unique
   candidate" from "unique candidate that is wrong".
4. **A larger hard-unknown set** (including single-candidate pools constructed
   by removing the truth and adding a near-isomer distractor) to validate any
   open-world gate.
5. **A method-aware EAD template source.** Until then, EAD16 should be treated as
   unavailable rather than as a cheap alternative scan.

---

## Reproduce everything

```bash
make v3-train      # calibrator (dev), ranker artefact, fragment validation
make v3-audit      # frozen v2 reproduction + 68 coverage-regression cases
make v3-failures   # failure atlas + oracle-ceiling diagnosis
make v3-eval       # M0–M7, ablations, paired stats, frontier, open world
make v3-demo       # six-screen precommit dossier
make v3-test       # 12 v3 contract tests
make test          # 56 tests total (44 legacy + 12 v3)
```

Outputs land only in `reports/v3/` (plus the two fitted artefacts under
`data/multims2/curated/`). Frozen v1/v2 reports are untouched.

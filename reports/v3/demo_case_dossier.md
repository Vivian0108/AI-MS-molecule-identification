# Demo case dossier

Two cases: one that reaches `MSMS_SUPPORTED` and one where the system honestly abstains. Every hypothesis hash below was sealed **before** the hidden spectrum was requested; the truth is printed only after the hash.

> The demo is a CLI dossier, not a web UI. The same six screens are available programmatically through `InvestigationSession`.

## `case-0217e6b5044e`

### 1. Case intake (public)

* precursor m/z **342.1700**, adduct `[M+H]+`, instrument `ZENOTOF7600`
* candidate pool: **3** precursor-consistent structures
* available actions: `CID40, EAD16`; budget **1**
* no truth field is present in the public case record

### 2. Evidence available before the extra scan

* CID20 peaks: 122.097 (0.01), 256.135 (0.37), 296.166 (0.11), 342.172 (1.00)
* plan: `decision_aware_risk_reduction` → **CID40** (HEURISTIC)
* plan note: One-step lookahead over a supervised expected-risk / proof-tier proxy. Hidden peaks are never read. The score is a stated utility function, not a calibrated expected information gain.

### 3. Precommitted hypotheses (sealed)

* action: `CID40`
* **precommit sha256**: `27e558e5151004920c228ac41d2e94f708f51519ebd045648416f2da71ea96c0`
* method: `diagnostic_peak_precommit`; predicted from templates only

| id | candidate | template source | reliability | predicted peaks (m/z) | rule |
|---|---|---|---:|---|---|
| H1_CID40 | `MMDMTPSUPYIQCD…` | reference_cid60 | 0.750 | 77.0387, 79.0539, 135.0448, 146.0608, 165.0701 | supported if >= 3 of 5 predicted peaks are observed within 0.02 Da and no expected-absent peak appears; refuted otherwise when the measurement has >= 3 peaks |
| H2_CID40 | `JEFWFORHNKXGAL…` | train_only_structure_knn | 0.147 | 132.0816, 137.024, 165.0551, 168.9645, 243.0617 | supported if >= 3 of 5 predicted peaks are observed within 0.02 Da and no expected-absent peak appears; refuted otherwise when the measurement has >= 3 peaks |
| H3_CID40 | `BNFRJXLZYUTIII…` | reference_cid60 | 0.750 | 59.0495, 105.0698, 106.0648, 107.0679, 122.0967 | supported if >= 3 of 5 predicted peaks are observed within 0.02 Da and no expected-absent peak appears; refuted otherwise when the measurement has >= 3 peaks |

### 4. Measurement

* action `CID40`: 59.049 (0.05), 69.034 (0.02), 87.044 (0.03), 107.052 (0.14), 122.096 (1.00), 147.080 (0.05), 256.133 (0.40), 296.165 (0.04)
* peaks: **16**; hidden until the precommit hash existed

### 5. Hypothesis validation (after the scan)

| id | candidate | status | matched / predicted | forbidden hits |
|---|---|---|---:|---:|
| H1_CID40 | `MMDMTPSUPYIQCD…` | **refuted** | 0 / 5 | 0 |
| H2_CID40 | `JEFWFORHNKXGAL…` | **refuted** | 0 / 5 | 0 |
| H3_CID40 | `BNFRJXLZYUTIII…` | **supported** | 3 / 5 | 0 |

### 6. Decision and counterfactuals

* status: **`MSMS_SUPPORTED`** (proof tier: `msms_supported`)
* top-1: `BNFRJXLZYUTIII-UHFFFAOYSA-N`; confidence 0.986; calibrated error 0.0
* reasons: independent_spectral_support, support_action:CID40

| action taken | status | retrieval top-1 correct | MS/MS accepted | any accepted |
|---|---|---|---:|---:|
| CID40 | MSMS_SUPPORTED | 1 | 1 | 1 |
| EAD16 | AMBIGUOUS | 0 | 0 | 0 |

> Truth (evaluator-only, printed after the precommit): `BNFRJXLZYUTIII-UHFFFAOYSA-N` — BNFRJXLZYUTIII-UHFFFAOYSA-N.

> The counterfactual table is post-hoc and uses evaluator truth to score the alternatives. It is a diagnostic, not a deployable policy.

## `case-0450558c55a6`

### 1. Case intake (public)

* precursor m/z **399.1286**, adduct `[M+H]+`, instrument `ZENOTOF7600`
* candidate pool: **2** precursor-consistent structures
* available actions: `CID40, EAD16`; budget **1**
* no truth field is present in the public case record

### 2. Evidence available before the extra scan

* CID20 peaks: 138.073 (0.02), 181.113 (1.00), 191.026 (0.01), 219.022 (0.51), 398.877 (0.01), 399.128 (0.34), 400.596 (0.02)
* plan: `decision_aware_risk_reduction` → **CID40** (HEURISTIC)
* plan note: One-step lookahead over a supervised expected-risk / proof-tier proxy. Hidden peaks are never read. The score is a stated utility function, not a calibrated expected information gain.

### 3. Precommitted hypotheses (sealed)

* action: `CID40`
* **precommit sha256**: `0aa91051f2ebd6218ce475907f8aff1e90b25fad6c0cbec4621b1cca9a7dd7fe`
* method: `diagnostic_peak_precommit`; predicted from templates only

| id | candidate | template source | reliability | predicted peaks (m/z) | rule |
|---|---|---|---:|---|---|
| H1_CID40 | `JEMBKQSZZOKYTO…` | reference_cid60 | 0.750 | 132.0454, 138.0724 | supported if >= 2 of 2 predicted peaks are observed within 0.02 Da and no expected-absent peak appears; refuted otherwise when the measurement has >= 3 peaks |
| H2_CID40 | `OHKRLDZFQRHQGE…` | reference_cid60 | 0.750 | 132.0454, 138.0724 | supported if >= 2 of 2 predicted peaks are observed within 0.02 Da and no expected-absent peak appears; refuted otherwise when the measurement has >= 3 peaks |

### 4. Measurement

* action `CID40`: 132.044 (0.62), 138.071 (0.11), 180.534 (0.02), 181.113 (0.66), 188.071 (0.01), 191.026 (0.36), 218.407 (0.01), 219.022 (1.00)
* peaks: **11**; hidden until the precommit hash existed

### 5. Hypothesis validation (after the scan)

| id | candidate | status | matched / predicted | forbidden hits |
|---|---|---|---:|---:|
| H1_CID40 | `JEMBKQSZZOKYTO…` | **supported** | 2 / 2 | 0 |
| H2_CID40 | `OHKRLDZFQRHQGE…` | **supported** | 2 / 2 | 0 |

### 6. Decision and counterfactuals

* status: **`AMBIGUOUS`** (proof tier: `abstained`)
* top-1: `—`; confidence None; calibrated error None
* reasons: insufficient_support

| action taken | status | retrieval top-1 correct | MS/MS accepted | any accepted |
|---|---|---|---:|---:|
| CID40 | AMBIGUOUS | 1 | 0 | 0 |
| EAD16 | AMBIGUOUS | 1 | 0 | 0 |

> **Why this abstains:** 2 candidates have *identical* precommitted peak sets, so the evidence cannot separate them even though both hypotheses are supported. The contract abstains rather than guessing; a `supported` hypothesis is a rule outcome, not structural proof.

> Truth (evaluator-only, printed after the precommit): `JEMBKQSZZOKYTO-UHFFFAOYSA-N` — JEMBKQSZZOKYTO-UHFFFAOYSA-N.

> The counterfactual table is post-hoc and uses evaluator truth to score the alternatives. It is a diagnostic, not a deployable policy.

## What the demo does not claim

* A `supported` hypothesis is a predeclared rule outcome, not structural proof.
* A `MASS_ONLY_MATCH` is not an MS/MS confirmation.
* The predicted templates inherit their provenance; a kNN template is a prediction, not a measurement.

```bash
make v3-demo
```

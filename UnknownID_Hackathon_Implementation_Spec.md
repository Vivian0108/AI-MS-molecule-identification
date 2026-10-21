# UnknownID — Hackathon Implementation Specification

**Version:** 1.0 | **Prepared:** October 20, 2026  
**Intended recipient:** Autonomous software-engineering agent / hackathon team  
**Target build window:** 48 hours, October 21–22, 2026  
**Deliverable:** Working web UI, reproducible experimental-data pipeline, adaptive virtual MS/MS measurement planner, scientifically honest evaluation and exportable investigation reports.

> **Agent mandate:** Implement a narrow, rigorous **closed-world, single-compound LC-ESI-MS/MS identification assistant** that actively requests the next collision energy when an initial spectrum is ambiguous. Use real, independent public experimental spectra for the virtual instrument. Do **not** claim novel structure elucidation, an instrument driver, or general commercial Compound Discoverer parity. Do not fabricate accuracy or dataset sizes. Complete the data audit before committing to the active-identification result.

## 0. Executive product specification

**User story.** A researcher has an MS/MS spectrum from an unknown small molecule. The program searches a known reference-candidate library, explains why different compounds are plausible, and — if the evidence is insufficient — selects a collision energy for an additional spectrum that is expected to reduce uncertainty. In the hackathon a *virtual mass spectrometer* reveals the corresponding **previously hidden measured spectrum**, rather than an AI-generated spectrum. A separate module handles spectral prediction for *planning* and must never access that hidden observation. The program updates its ranking, either reports an identity with appropriate limitations or abstains, and exports an evidence trail.

**Scientific hypothesis to evaluate:** For a genuinely ambiguous known-library identification subset, an adaptive collision-energy choice can improve identification per additional acquisition compared with fixed-energy and random-energy policies.

**Scope:** small molecules (not peptides, polymers, complex mixtures), positive-ion ESI, singly charged `[M+H]+`, collision-induced dissociation (CID), one verified Bruker maXis Impact LC-QTOF cohort, experimental reference standards. Initially support only fixed collision energies 10/20/30/40/50 eV. No automatic hardware control.

**Novel capability:** budgeted experiment planning in the presence of competing molecular hypotheses, with evidence-backed abstention. Existing library search, spectral interpolation, and MS/MS predictors are *components*, not claimed inventions.

**Success depends on the data audit.** If the selected public cohort does not contain enough nontrivial, precursor-ambiguous identities, report this and switch to the explicitly labeled fallback (§3.8). Do not weaken the mass tolerance merely to create harder identification examples.

---

## 1. Verified scientific sources and software dependencies

### 1.1 Primary dataset — intentionally narrow and homogeneous

**MassBank, University of Athens contributor:**
- Repository: https://github.com/MassBank/MassBank-data
- Data location: `Athens_Univ/` directory in that repository.
- Record specification: https://github.com/MassBank/MassBank-web/blob/dev/Documentation/MassBankRecordFormat.md
- Stable public MassBank archive: https://doi.org/10.5281/zenodo.3378723
- Example *individual* candidate record: https://massbank.eu/MassBank/RecordDisplay?id=MSBNK-Athens_Univ-AU260701 — Ethion; LC-ESI-QTOF; CID; `[M+H]+`; CE 10 eV; standard compound, CC BY.
- Published multi-energy cohort description: https://pmc.ncbi.nlm.nih.gov/articles/PMC9400100/ and https://doi.org/10.1021/acs.jcim.2c00620 — 2022 paper *Augmentation of MS/MS Libraries with Spectral Interpolation for Improved Identification*. This study reports **549 compounds**, measured on a Bruker maXis Impact LC-ESI-QTOF with `[M+H]+`, at **10, 20, 30, 40, and 50 eV**. The authors use a reduced reference library and evaluate held-out energy spectra. **549 is the literature cohort, NOT the guaranteed post-filter count of our current snapshot.**

**Why this source:** It supplies genuine experimental alternatives at a known collision-energy grid with comparatively consistent instrumentation. It is far more defensible for an experiment-selection simulation than arbitrary GNPS/MassBank pooling. The 2022 paper already establishes interpolation is possible; our independent question is **which energy to acquire next**.

### 1.2 Core code

| Role | Source | How used |
|---|---|---|
| Source records | https://github.com/MassBank/MassBank-data | Download primary raw .txt records and pin commit |
| MassBank format | https://github.com/MassBank/MassBank-web/blob/dev/Documentation/MassBankRecordFormat.md | Parse record and analytical-method metadata correctly |
| Spectral parsing, normalization, matching | https://github.com/matchms/matchms and https://matchms.readthedocs.io/en/latest/ | Cosine/modified cosine, MS/MS processing |
| Molecular normalization | https://github.com/rdkit/rdkit and https://www.rdkit.org/docs/ | Canonical SMILES, InChIKey, neutral exact mass, chemical validity |
| Statistics | https://scipy.org/ and https://scikit-learn.org/stable/ | Interpolation, calibration, bootstrapping, analysis |
| Optional MGF parsing | https://pyteomics.readthedocs.io/en/latest/data.html | Read MGF for later user uploads; raw MassBank parser is required first |
| UI | https://docs.streamlit.io/ and https://plotly.com/python/ | Interactive dashboard and mirror spectra |
| Optional agent coordinator | https://langchain-ai.github.io/langgraph/ | Constrained workflow; state machine is preferable if faster |
| Optional spectral prediction stretch | https://3dmolms.readthedocs.io/en/latest/usage/msms_prediction.html | Energy-conditioned structure→MS/MS templates on wider candidate pools; separate optional milestone and validate licensing/model support |
| Optional harder benchmark | https://github.com/pluskal-lab/MassSpecGym | External retrieval benchmark; **not** substitute for the multi-CE primary dataset |
| Optional raw-data processing | https://github.com/mzmine/mzmine | Out-of-scope for first 48 hours; avoid raw mzML import complexity |
| Optional broader library | https://library.gnps2.org/libraries | P2 expansion only after harmonizing instrument, provenance and licensing |

**Prior work to acknowledge:** The 2022 JCIM spectral-interpolation study above. Do not claim interpolating across collision energies is novel. MassBank record licenses are **per record** (`LICENSE` metadata may include CC BY, CC BY-SA, NC, etc.); check and attribute each reused record. Do not download or redistribute the proprietary NIST20 library.

---

## 2. Architecture and trust boundary

```
                      SCIENTIST / STREAMLIT UI
                                  |
                      spectra + precursor metadata
                                  v
                  +--------------------------------+
                  | CandidateRetriever             |
                  | exact adduct/mass + ref spectra|
                  +--------------------------------+
                                  |
                       shortlist + scores
                                  v
                  +--------------------------------+
                  | EvidenceEvaluator              |
                  | cosine, diagnostic fragments,  |
                  | neutral losses, uncertainty    |
                  +--------------------------------+
                                  |
                  +--------------------------------+
                  | Planner                        |
                  | simulate possible outcomes at  |
                  | each AVAILABLE energy; choose  |
                  | expected information gain      |
                  +--------------------------------+
                                  |
                         choose 30 or 40 eV
                                  |
                         VirtualInstrument
                       [SEALED EXPERIMENT ORACLE]
                                  |
                   measured observation at CE
                                  v
                  +--------------------------------+
                  | PosteriorUpdater + Critic      |
                  | reconcile, QC, abstain, report |
                  +--------------------------------+
                                  |
                    rank + evidence + export
```

**Hard isolation rule:** `OracleStore` stores experimental observations at hidden energies. `Planner`, `CandidateRetriever`, `ReferenceStore`, `LLM`, all embeddings, caches and training/calibration processes cannot read the oracle for evaluation compounds. `VirtualInstrument.measure(case_id, energy)` is the **only** endpoint that reveals an observation, and only after an explicit action. Log every call. `ground_truth_identity` is readable by the benchmark scoring process only, never by agent or candidate scoring.

**No deceptive “agent” layers.** Deterministic scientific functions do the numerical work. An LLM may summarize candidate evidence, propose tests through a bounded tool schema, and explain non-identifiability. For v1 the numerical acquisition rule is implemented in Python and may be invoked by the LLM agent. The LLM must not invent peak masses, formula assignments, measured spectra or posterior probabilities.

---

## 3. DATA SELECTION: implement this first, before writing the UI

### 3.1 Acquire and freeze a source snapshot

```bash
mkdir -p data/raw
# Sparse clone minimizes transfer; preserve commit SHA in dataset manifest.
git clone --filter=blob:none --sparse https://github.com/MassBank/MassBank-data.git data/raw/massbank
cd data/raw/massbank
git sparse-checkout set Athens_Univ
git rev-parse HEAD
```

If sparse checkout is unsupported, use the archive or release referenced above and record its DOI/version. Preserve original `.txt` files. In `data/manifest.json`, include source URL, commit SHA/release, retrieval date, processing config version, per-record accession, license, and SHA256 of raw bytes. Never silently refresh the source after evaluation is frozen.

### 3.2 Parse **raw record fields**, not filename guesses

Required fields (original MassBank tags):

```
ACCESSION
LICENSE
COMMENT (especially standard/reference confirmation)
CH$SMILES
CH$LINK: INCHIKEY
CH$FORMULA
CH$EXACT_MASS
AC$INSTRUMENT
AC$INSTRUMENT_TYPE
AC$MASS_SPECTROMETRY: MS_TYPE
AC$MASS_SPECTROMETRY: ION_MODE
AC$MASS_SPECTROMETRY: IONIZATION
AC$MASS_SPECTROMETRY: FRAGMENTATION_MODE
AC$MASS_SPECTROMETRY: COLLISION_ENERGY
MS$FOCUSED_ION: PRECURSOR_M/Z
MS$FOCUSED_ION: PRECURSOR_TYPE OR ION_TYPE
PK$NUM_PEAK
PK$PEAK (multiline mz, intensity, relative intensity)
```

Handle escaped/whitespace variants, repeatable `COMMENT`, `CH$NAME`, `CH$LINK` lines, and `PK$PEAK` ending at `//`. Preserve the original collision-energy **string**, parsed numerical value **and unit**. MassBank permits `eV`, volts, normalized percentages and ramps; these **must not** be blindly combined. MassBank record format is the source of truth.

### 3.3 Inclusion criteria (strict experiment-cohort policy)

Accept a molecule/record only if all relevant conditions are met:

1. **MS2** data, **LC-ESI-QTOF**, **positive** ionization, **CID**, `[M+H]+`, single-charged. Require the same validated instrument *model* (Bruker maXis Impact) across compared spectra, not just generic QTOF. Exclude GC-APCI and other Athens records even if they share directory/contributor.
2. CE reported as **one fixed numeric value in eV**, exactly one of `{10,20,30,40,50}` within a small parsing tolerance. Exclude missing CE, collision-energy ramps, percent NCE, unspecified volts, and ambiguous units. Do not convert NCE to eV generically.
3. A real standard/reference compound where metadata supports it (e.g., `CONFIDENCE standard compound` / reference-standard designation). Do not treat tentative level-2/propagated annotations as ground truth.
4. Valid RDKit structure and a stable identity key. Prefer full InChIKey (including stereochemistry); preserve 2D connectivity key separately. Do **not** conflate stereoisomers, tautomers, salts and neutral structures automatically. If ambiguous, exclude the record or flag it and remove from primary evaluation.
5. Formula, SMILES-derived neutral monoisotopic mass, and measured `[M+H]+` precursor m/z are mutually consistent within **10 ppm** by default (configurable, recorded, grounded in instrument/QC). Use proton mass for ion correction; not just +1.0 Da. Where data handling of radicals/adducts is unclear, exclude.
6. For primary complete-case evaluation, the exact molecule has a valid experimental spectrum at **all five energies**, with stable adduct/instrument/fragmentation metadata. Keep a separate partial-case table, but don't silently impute a missing oracle energy.
7. Peaks are finite, m/z > 0, intensity nonnegative, precursor m/z > 0; at least **3 nontrivial peaks** at each oracle energy 20/30/40 after a fixed preprocessing rule; endpoints 10/50 may be sparser and must be logged. Do not selectively remove challenging compounds because the identity model fails.
8. Preserve per-record licensing, and release only data/derived artifacts compatible with the license. Even publicly accessible files may have NC or share-alike conditions.

**Replicates:** If multiple records correspond to identical compound+energy+instrument+adduct, identify whether they are independent runs. Do not count replicates as independent compounds; do not let a replica of the same scan straddle oracle and reference. For MVP, select a documented, precommitted representative per condition by acquisition/QC criteria independent of identification outcomes, or construct a robust consensus within a non-overlapping acquisition group.

### 3.4 Normalization (fixed before testing)

- Keep raw peaks immutable.
- Primary processing: remove invalid peaks, optionally remove tiny peaks below **1% base-peak intensity**, normalize vector to base peak=1, and apply the same rule to library, query and oracle spectra. Do not remove a diagnostically useful peak merely because it is near precursor without reporting it.
- Use matched fragment tolerance **0.02 Da** as a **starting configuration** for high-resolution QTOF and test sensitivity at 0.01 and 0.05 Da; don't claim universal physical optimality.
- Record total/retained peak counts per energy, instrument and identity.
- Matchms `CosineGreedy`/`CosineHungarian` for **same precursor/adduct**; `ModifiedCosineGreedy` is optional for analog matching where mass shifts are intended. Report matched-peak count along with similarity. Do **not** call a cosine score a calibrated molecular identity probability.
- Add validity checks: duplicate peaks, masses above possible precursor where relevant, implausible adduct/charge assignments, different collision/ionization methods.

### 3.5 Split data along TWO orthogonal axes

**Axis A — molecular partition (for tuning/generalization):** Split complete cases by **molecular identity**, preferably grouped by Bemis–Murcko scaffold where chemically meaningful. Train/dev/test target 60/20/20 compounds if size permits; if scaffold bins are too imbalanced, document stratification and use identity-level groups instead. Tune interpolation/calibration only on train/dev. Never use **test molecules' hidden-energy spectra** to train acquisition likelihoods or optimize thresholds.

**Axis B — acquisition energy (the virtual laboratory):** For *every* evaluation molecule:

| Availability | Collision energies | Visible to |
|---|---|---|
| Static candidate reference library | **10, 50 eV only** | Retriever + evidence + planner |
| Initial measured query | **20 eV**, revealed at case start | Agent and UI after case starts |
| Queryable, hidden measured observations | **30, 40 eV** | Only `VirtualInstrument.measure(30\|40)` after action |
| True compound ID | Not an input feature | Benchmark evaluator only |

This deliberate energy separation is necessary because the Athens dataset may supply only one spectrum per molecule per CE; copying the 30-eV reference spectrum into the 30-eV “oracle” would create a false near-perfect identification. Using 10/50-eV reference spectra for all candidate structures is a valid **known-reference-library** scenario. It is not independent blind *de novo* identification. State this clearly.

**Limitation of five energy levels:** There are only **two optional next energy choices** (30 and 40 eV) after the fixed 20-eV initial scan. Therefore the most defensible decision is **choose 30, choose 40, or stop** (possibly both sequentially). Do not claim unconstrained acquisition optimization over dozens of energies.

### 3.6 Mandatory dataset audit report — stop/go decision

Before training, generate `reports/data_audit.md` plus `data/curated/audit.parquet` with:

- Counts: raw files, valid parsed records, records surviving each exclusion rule, distinct molecules, and exact 5-energy complete cases.
- Counts by collision energy, instrument model, adduct, fragmentation method, license and standard-confidence field.
- Unique full InChIKeys and 2D connectivity groups, formula groups, precursor m/z distribution, mass-calculation discrepancies and adduct anomalies.
- Average/minimum/median fragment peaks per CE, blank/sparse spectra, duplicates and spectrum-matching sanity checks.
- **Difficulty analysis:** For each test case, how many **other reference-library molecules** are plausible at the measured precursor m/z within 10 ppm and the same adduct? How many share the molecular formula? How often does a precursor-only baseline already identify the molecule uniquely? How many initially have a close top-2 spectral-ranking margin?
- Demonstration eligibility: number of cases with >=2 chemically plausible identities, number with >=3, and number where two candidate spectra predict significantly different outcomes at 30 vs 40 eV.
- Sample provenance table with at least 10 real accessions spread across energies (no invented accession IDs) and exact URLs.
- License summary and final train/dev/test identities + deterministic split seed.

**Go/no-go gate (proposed minimum, adjustable only before test freeze):** Prefer >=100 complete cases, >=30 scientifically ambiguous 20-eV identification cases, and >=15 cases with nontrivial 30-versus-40 acquisition choices. These are **feasibility targets**, not claims that the data meets them. If much smaller, present the project as proof-of-concept with an explicit limited sample size; do not imply a broadly reliable active-identification result.

**Do not artificially use a 0.5–1 Da mass window with high-resolution QTOF and then describe the resulting problem as realistic.** A deliberately nominal-mass/low-resolution scenario is acceptable only as a distinct, clearly labeled sensitivity experiment, not the primary scientific claim.

### 3.7 Candidate universe and unknown/closed-world status

- **Closed-world v1:** The true compound exists in the known candidate reference library; candidate identity and molecular reference templates at 10/50 eV are available. The query identity is hidden, not the existence of candidates.
- **Retrieval:** filter by exact precursor/adduct plausibility; prefer experimentally supported candidates over hypothetical ones. Rank by 20-eV observation versus an energy-conditioned **interpolated 20-eV template** from 10/50-eV references, plus diagnostic evidence. If no independent reference candidate lies within mass tolerance, mark case as easy/unambiguous and do not include in the *ambiguous-case* primary metric (but report its prevalence in the full-cohort metric).
- Use full InChIKey as distinct candidate when stereo evidence can resolve it; **do not claim MS/MS can distinguish enantiomers without appropriate chiral separation**.
- **Open-world/abstention test:** Remove a subset of molecules' reference templates entirely from the candidate library, then check that the model flags “none of the above”; it cannot honestly identify them from this limited library.

### 3.8 Fallbacks if the primary cohort is not sufficiently ambiguous

**Fallback A (scientifically strongest):** Keep the Athens virtual-lab dataset; evaluate *collision-energy-dependent identity verification* rather than open-ended identification. Supply a curated shortlist of **chemically plausible structural hypotheses** generated using independent chemical structure databases or independent spectrum predictions, with exactly stated evidence. Evaluate whether an extra scan rejects an erroneous candidate, not whether an inherently unique precursor magically becomes identifiable. Do not fabricate spectra.

**Fallback B:** Locate a second *separate*, homogeneous, multi-CE experimental cohort in MassBank/GNPS. Repeat ALL metadata checks and never compare absolute CE across dissimilar instrument/fragmentation modalities. State whether cross-instrument generalization is a separate study.

**Fallback C (ambitious extension):** Use an openly licensed energy-conditioned spectral predictor such as 3DMolMS for candidate structures, with measured Athens scans as the oracle. Verify checkpoint training provenance/leakage and energy/instrument covariate support before using it. Treat predicted spectra as fallible; run error analysis. This broadens candidate coverage, but requires more compute and cannot be assumed reliable in 48 hours.

**Decision rule:** Prefer a rigorous limited demo over a misleading large dataset. If no valid multi-energy cohort or sufficient ambiguity survives, document the blocker and ship a functioning spectral-library evidence explorer without making the active-optimization claim.

---

## 4. Data model and internal API contracts

Use Pydantic models or typed dataclasses, and serialize JSON/Parquet. Example canonical entities:

```python
class SpectrumRecord(BaseModel):
    accession: str
    molecule_id: str                  # full standardized InChIKey or audited ID
    smiles: str
    formula: str
    precursor_mz: float
    adduct: str                       # [M+H]+
    ion_mode: Literal['POSITIVE']
    instrument_model: str
    fragmentation_mode: Literal['CID']
    collision_energy_ev: int
    mz: list[float]
    intensity: list[float]
    license: str
    source_sha256: str
    is_reference_standard: bool

class PublicCase(BaseModel):
    case_id: str
    observed_20ev_spectrum: dict       # peaks + instrument/CE, NO source accession
    candidate_ids: list[str]         # public reference candidates only
    measurement_budget: int = 1      # v1 supports 0, 1 or 2

class PrivateOracleCase(BaseModel):
    case_id: str
    true_molecule_id: str             # evaluator-only, never serialized to agent
    hidden_accessions: dict[int, str] # 20,30,40 energy records, oracle-only

class Evidence(BaseModel):
    candidate_id: str
    similarity_by_energy: dict[int,float]
    matched_peaks_by_energy: dict[int,int]
    matched_fragments: list[dict]
    unexplained_peaks: list[dict]
    log_score: float
    weight: float                     # pseudo-posterior until calibrated

class Action(BaseModel):
    kind: Literal['measure','stop']
    energy_ev: Optional[Literal[30,40]] = None
    predicted_information_gain: Optional[float] = None

class Investigation(BaseModel):
    case_id: str
    observations: list[dict]
    candidate_evidence: list[Evidence]
    selected_actions: list[Action]
    decision: Literal['identified','ambiguous','out_of_library']
    predicted_identity: Optional[str] = None
    limitations: list[str]
```

Use different read permissions for `ReferenceStore`, `OracleStore`, and `EvaluatorStore` (truth identity and ground-truth labels). In a hackathon single-process build, make the separation testable via dependency injection and explicit API boundaries; passing a full DataFrame with all 5 CEs into an agent function is forbidden.

**Required backend operations:**

```
POST /cases/start           -> observation at 20eV + candidate list + initial ranking
GET  /cases/{id}/ranking    -> current top candidates, scores, evidence
POST /cases/{id}/plan       -> allowed energies + cost + recommended energy + IG
POST /cases/{id}/measure    -> {energy_ev:30|40} -> authentic previously hidden measured spectrum
POST /cases/{id}/stop       -> final decision and limitations
GET  /cases/{id}/report     -> downloadable machine-readable evidence record
```

`/plan` MUST NOT reveal test-oracle peaks or truth labels. The API should reject repeated measurement of the same energy, unsupported energy, a consumed budget, and requests for a nonexistent observation.

---

## 5. Identification and active-acquisition algorithms

### 5.1 Precursor filtering and initial ranking

1. Use measured precursor m/z and known `[M+H]+` ion to restrict candidates to matching precursor m/z within an explicitly specified ppm tolerance. Do not compare ion species with different adducts.
2. For each candidate `c`, construct a **predicted 20-eV** reference template `S_hat(c,20)` using only its **10- and 50-eV reference** spectra. Start with m/z-aware peak alignment + intensity interpolation. Avoid unconstrained exact-mass binning that mistakenly merges separate high-resolution fragments.
3. Compare observed `S_obs(20)` to predicted template with cosine similarity and minimum matched-peak criteria. Add simple explainable evidence (presence/absence of plausible neutral losses, shared fragments). Formula-constrained fragment checks must be algorithmic, not invented by LLM.
4. Convert similarity to a *ranking score*. For a probability-like weight, calibrate a temperature / likelihood model on training+development groups only. Until verified, label normalized scores **relative support**, not `P(true chemical identity)`.

For interpolation use the 2022 paper's method as a baseline/reference (its supplementary code is linked from the DOI/PMC page), but **do not assume it provides scientifically accurate spectra for every molecule and intermediate CE**. Compare against linear interpolation and nearest-energy templates on dev data.

### 5.2 Information gain (mathematically correct formulation)

Let `C` be the candidate identity (or `NONE_OF_ABOVE`), and let current observations be `D`. Suppose the current estimated candidate weights are `q(c|D)`. For each available next energy `e ∈ {30,40}`:

\[
\operatorname{IG}(e)=H[q(C\mid D)]-\mathbb{E}_{Y\sim p(Y\mid D,e)}\left[H[q(C\mid D,Y,e)]\right].
\]

The expectation is over **possible future measured spectra Y**, not the hidden actual spectrum. Choose

\[
e^*=\arg\max_{e\in E_\mathrm{available}} \frac{\max(0,\widehat{IG}(e))}{\mathrm{cost}(e)}.
\]

Use equal measurement cost as the default unless instrument-specific evidence supports differences. Include a **STOP action** if estimated information gain is too small, the shortlist is already sufficiently resolved, or budget is exhausted.

**Implementable Monte Carlo approximation:**

```python
def choose_next_energy(current_weights, candidate_templates, error_model, allowed):
    h0 = entropy(current_weights)
    values = {}
    for e in allowed:
        entropies = []
        for _ in range(N_MONTE_CARLO):
            c = sample_categorical(current_weights)
            # Simulate a *hypothetical* spectrum using a template AND
            # uncertainty learned only from train/dev molecules.
            y = error_model.sample(template=candidate_templates[c][e], energy=e)
            updated = update_candidate_weights(
                old=current_weights, hypothetical_spectrum=y,
                energy=e, templates=candidate_templates,
                error_model=error_model)
            entropies.append(entropy(updated))
        values[e] = (h0 - mean(entropies)) / acquisition_cost(e)
    return max(values, key=values.get), values
```

**Critical:** Never sample `y` from the real test oracle before calling `measure`. This would leak the answer.

### 5.3 Define a probabilistic observation model, not a handwavy IG number

A practical first model:
- Project observed and template spectra onto a fixed fragment m/z grid or a sparse matched-peak feature vector, using validated resolution.
- Learn interpolation residual distributions **from train identities** at 20/30/40 eV, conditional on energy and ideally precursor mass/peak-density bins.
- Sample noisy spectra around the predicted templates with this error model. Ensure nonnegative intensities and realistic peak dropout.
- Build the pseudo-likelihood `log L(Y|c,e) = κ_e × cosine(Y, S_hat(c,e)) + peak_count_terms`, or use a fitted low-dimensional Gaussian likelihood. Estimate `κ_e` and noise scales exclusively from train/dev; explicitly track poor fit.
- Update `q(c|D,Y,e) ∝ q(c|D) L(Y|c,e)`. Spectra at different energies are correlated: independent likelihood multiplication may overcount information. Calibrate/temper likelihoods based on dev outcomes, and avoid presenting unverified posteriors as calibrated probabilities.
- If data are insufficient to fit a credible likelihood, fall back to an **uncertainty/disagreement acquisition heuristic** (which CE maximizes expected pairwise candidate-template separation weighted by current ranks), and **label it a heuristic, not exact information gain**.

### 5.4 A strong nonprobabilistic fallback acquisition function

If uncertainty calibration fails, use:

\[
U(e)=\sum_{i<j} w_i w_j\;d(\widehat S_{i,e},\widehat S_{j,e})\;\times r_e,
\]

where `d = 1 - cosine`, weights `w_i` are current candidate support, and `r_e` is a reliability factor derived from held-out interpolation error at that energy (not oracle labels). This encourages an energy where plausible candidates predict different spectra, **discounting poorly modeled energies**. Compare this to random/fixed even if formal IG is unavailable.

### 5.5 Final identification / abstention

After acquiring at most two additional real spectra, rerank candidates using the same precommitted scoring/calibration. Output `identified` **only if** held-out calibrated selection criteria are satisfied; otherwise `ambiguous`. Include `out_of_library` where no acceptable candidate matches. Always show accession IDs for each observed reference and clearly identify whether evidence is experimental, interpolated, simulated or inferred. Never generate a fabricated measured spectrum.

---

## 6. Scientific evaluation: claims the agent may and may not make

### 6.1 Baselines — all use the exact same candidate universe and initial query

1. **Precursor-only:** rank from accurate mass/adduct; quantifies easy cases.
2. **Single-scan:** 20-eV observation versus reference-interpolated 20-eV templates, no additional action.
3. **Always-30:** request 30 eV when allowed, otherwise stop.
4. **Always-40:** request 40 eV when allowed.
5. **Random:** choose 30 or 40 at random, repeat over ≥20 seeded trials.
6. **Cheap disagreement:** choose energy maximizing weighted template separation.
7. **UnknownID planner:** information gain when calibrated; otherwise the explicitly labeled reliability-aware acquisition heuristic.
8. **Oracle best action (diagnostic upper bound only):** hindsight maximum accuracy from trying both real observations. **Not a deployable baseline** and excluded from reported planner performance except as a ceiling.

### 6.2 Primary results

Evaluate separately on **all held-out complete cases** and the **predefined ambiguous subset**. Ambiguous subset membership MUST be determined from initial 20-eV evidence and calibration rules fixed on dev, NOT from whether adaptive planner later succeeds.

| Metric | Definition |
|---|---|
| Top-1 accuracy@0, @1, @2 | Correct structure after 0/1/2 extra acquisitions |
| MRR / Top-3 accuracy | Candidate ranking quality |
| Accuracy-vs-number-of-scans curve | Primary cost/benefit story |
| Additional acquisitions to reach threshold | Sample efficiency |
| Abstention risk/coverage | Error among accepted identifications vs share accepted |
| Calibration | Reliability diagram / ECE / Brier only if probability predictions genuinely calibrated |
| Information-gain validation | Predictive IG vs observed posterior entropy reduction; avoid using true labels in planning |
| Scientific QC rejection rate | Invalid/adduct-confounded cases excluded and their reasons |
| Computational runtime | Per case; no invented GPU savings |

Report uncertainty by **molecule-level bootstrap** (not spectrum-level bootstrap) with 95% confidence intervals on *paired differences*. Never represent 5 collision energies for one molecule as five independent test compounds. If multiple outcomes use one source acquisition, preserve grouping.

**Honest limitations:** A gain on a 549-compound homogeneous reference cohort is *not* proof of de novo structure discovery, cross-instrument robustness, improved clinical diagnostics, or automatic control of a real spectrometer. Mass-spec-only structural identification can be ambiguous for stereoisomers and molecules with similar fragmentation.

### 6.3 Anti-leakage tests (mandatory in CI)

- Unit test: `Planner` cannot call `OracleStore.read` and receives no oracle handles.
- Unit test: for a held-out case, replace hidden 30/40-eV measured peaks with randomized arrays *after planning*; the planned action must remain identical.
- Verify selected action energy is logged **before** measurement is revealed.
- Verify only 10/50-eV spectra are accessed as references for an evaluation compound.
- Verify train/dev/test share no molecule IDs, and no test 20/30/40 measured spectra are used in predictive interpolation fitting or likelihood calibration.
- No accession/record duplication across folds that silently encodes the same experimental spectrum.
- Verify that precursor mass and formula alone do not dominate the reported ambiguous subset.
- Never tune hyperparameters or thresholds against test results.

---

## 7. Multi-agent behaviors (bounded, demonstrable, useful)

Use a thin workflow with **three roles**, not an uncontrolled swarm:

**Agent A — Chemical Evidence Analyst** (RDKit + matchms): obtain precursor-consistent structures, plot shared/unexplained fragments and neutral losses, flag questionable matches. Tools: `retrieve_candidates`, `compare_spectra`, `inspect_fragments`.

**Agent B — Experimentalist / Planner** (SciPy/NumPy policy): propose measuring 30 eV, 40 eV, or stopping; output evidence-driven expected gain, cost, and constraints. Tools: `available_measurements`, `score_acquisitions`, `measure`. **Only `measure` can invoke the oracle** after checking policy and budget.

**Agent C — Scientific Critic & Reporter**: reject unsupported confidence claims, verify adduct/instrument consistency, ensure no unsupported structure assignment, cite provenance, and export report. Tools: `qc_check`, `report_evidence`, `export_report`.

Require every LLM agent output to parse against a strict schema. Scientific scoring must remain deterministic and independently testable. Do not allow arbitrary LLM Python execution, model-generated fake spectra, or mutation of frozen data.

---

## 8. UI specification

**Screen 1: Dataset provenance** — visible source/commit, experimental cohort, filter counts, restrictions, and example records. Include an explicit banner “Virtual instrument uses archived experimental measurements.”

**Screen 2: Investigation** — select a hidden case (UI shows random case ID, not compound), initial 20-eV stick spectrum with precursor metadata, candidate table (structures rendered with RDKit, exact mass, evidence weights), and mirrored spectrum overlays versus energy-interpolated references. Each evidence row links to MassBank accession for **reference** evidence; hidden truth accession remains embargoed until scoring/completion.

**Screen 3: Choose next experiment** — energies 30 and 40 eV with expected IG / separation, interpolation reliability, measurement cost; a **Measure** button or **Stop**. Show budget and a clear “prediction vs measured” distinction.

**Screen 4: Final report** — before/after ranking, spectral comparisons, diagnostic fragments, validation status, provenance, and an honest `identified/ambiguous/out_of_library` verdict. Export JSON and Markdown.

**Screen 5: Evaluation dashboard** — table and plots for real measured results: accuracy@0/1/2, paired gains with bootstrap confidence intervals, fixed/random/heuristic/adaptive baselines, fraction of easy cases, failure breakdown.

Visual clarity is useful; don't spend hours on animated molecular graphics or full chromatogram pipelines.

---

## 9. Repository layout and executable commands

```
unknownid/
  README.md
  environment.yml                 # or pyproject.toml + lockfile
  config/selection.yaml
  config/acquisition.yaml
  data/raw/massbank/              # gitignored raw checkout
  data/curated/                   # manifests, indexed Parquet/NPZ
  reports/data_audit.md
  reports/evaluation.md
  src/unknownid/
    io/massbank_parser.py
    data/curate.py
    data/audit.py
    data/splits.py
    core/models.py
    core/spectra.py
    core/templates.py
    core/retrieve.py
    core/evidence.py
    core/posterior.py
    planner/acquisition.py
    planner/error_model.py
    simulator/oracle.py
    simulator/episodes.py
    agents/workflow.py
    eval/baselines.py
    eval/metrics.py
    eval/bootstrap.py
    api/app.py
  app/streamlit_app.py
  scripts/fetch_data.sh
  scripts/prepare_data.py
  scripts/run_eval.py
  scripts/make_demo_cases.py
  tests/test_massbank_parser.py
  tests/test_chemical_qc.py
  tests/test_energy_split.py
  tests/test_oracle_isolation.py
  tests/test_acquisition_policy.py
  tests/test_baselines.py
```

Suggested commands:

```bash
make setup
make fetch-data
make audit               # MUST complete before committing to active-ID pitch
make prepare             # freeze curated manifest and splits
make test                # includes anti-leakage tests
make eval                # all baselines with fixed seeds and bootstrap intervals
make app                 # launch web demo
```

Persist outputs under fixed versioned paths. Log Python package versions, snapshot SHA, random seeds, inference model version, and complete acquisition trace. For tests, create a tiny **synthetic fixture** with known spectra only to verify APIs; keep its results separate from scientific experimental evidence.

---

## 10. Build schedule, critical path, and stop conditions

### First 6 hours: highest-risk data task

1. Fetch Athens source snapshot and inspect real examples across energy values. Implement parser and chemistry/instrument filters.
2. Reproduce the 10/20/30/40/50 complete-case inventory and generate the first audit.
3. Run the **precursor-ambiguity audit immediately**. Report actual counts and decide whether adaptive identification is feasible.
4. Freeze experimental design and reserve test molecules. Do not write model code until this checkpoint is passed.

**Checkpoint deliverable:** `reports/data_audit.md`; one test `Case` with genuine observed spectrum at 20 eV, hidden 30/40-eV oracles, and 10/50-eV references.

### Hours 6–16: scientific retrieval MVP

Implement matchms similarity, exact precursor/adduct filtering, RDKit candidate handling, cross-energy templates and evidence table. Validate a few real cases manually against MassBank raw records. Add best fixed-energy baseline.

### Hours 16–28: experiment-selection loop

Create `VirtualInstrument` with strict access, baseline choose-30/choose-40/random, uncertainty-aware template separation; if sufficient dev data, fit an observation-noise model and Monte Carlo IG. Verify query-budget enforcement and leak-proof tests.

### Hours 28–38: scientist interface and multi-agent explanations

Streamlit case browser, ranked candidates, before/after spectra, rationale and decision state. Add bounded LLM analyst/critic only if the core numerical loop works. Do not waste time on complicated orchestration frameworks.

### Hours 38–48: rigorous evaluation and submission

Freeze policies. Run all metrics against held-out molecules, molecule-level bootstrap, failure inspection, reproducible demo with 2–3 real cases selected using DEV data only. Export evidence report. Document claims that are and are not justified.

**Failure policies:**
- No homogeneous multi-energy data? Stop the active planner and report the limitation.
- Too few ambiguous candidates? Ship case-specific evidence verification or escalate to a documented wider candidate model, not fake difficulty.
- No credible probabilistic likelihood? Ship template-disagreement heuristic; do not label it calibrated information gain.
- No LLM integration? Deterministic software is acceptable if it solves the scientific task and has clean scientific evidence.
- No significant improvement? Show negative results and failure examples; don't massage the test cohort.

---

## 11. Acceptance criteria / definition of done

**Must pass:**

- [ ] Real licensed experimental MS/MS dataset downloaded, commit pinned, citations recorded.
- [ ] `data_audit.md` identifies the exact surviving multi-energy count and candidate-ambiguity rate; no fabricated 549 post-QC count.
- [ ] Same-instrument/same-adduct/fixed-CE filtering enforced; no NCE/eV mixing.
- [ ] Hidden observed 30/40-eV spectra inaccessible to the planner before `measure`.
- [ ] Repeatable 20-eV initial ranking of chemically plausible candidates.
- [ ] One-click choice of 30/40 eV with rationale, real oracle reveal, and updated ranking.
- [ ] Separate evidence for **measured**, **reference**, **interpolated**, **predicted** fragments.
- [ ] Correct stop/abstain behavior for ambiguous and out-of-library cases.
- [ ] Baselines: no-extra-scan, fixed-30, fixed-40, random, and active heuristic (plus IG if scientifically calibrated).
- [ ] Quantitative results with molecule-level confidence intervals and failure cases.
- [ ] One command runs test suite and one launches app; README reproduces environment and data processing.
- [ ] Exportable provenance/evidence report with full raw accession links and license metadata.

**Stretch goals:** calibrated expected information gain, third-party energy-conditioned spectral model, experimental-data oracles from an independently acquired replicate cohort, compound-isomer candidate generation, instrument-specific acquisition costs, generic uploaded MGF workflow, spectrum-based out-of-library detection, or real instrument API. These are **not** prerequisites.

**User-facing pitch after results exist:**

> UnknownID combines open chemical libraries and MS/MS scoring with an active virtual experiment planner. Instead of committing to a molecular identity from one ambiguous fragmentation spectrum, it chooses between available experimental collision energies and shows whether the additional authentic measurement resolves the uncertainty. We validate improvements against fixed and random energy choices on a homogeneous, publicly documented experimental cohort, with full provenance and explicit abstention.

---

## 12. Important scientific nuance and novelty boundaries

1. **Known-library identification is not de novo molecular structure elucidation.** This MVP ranks reference compounds, not arbitrary new unknown chemistry.
2. **A high library similarity is not proof of molecular identity.** Co-elution, stereochemistry, isomers, shared fragmentation and contamination can cause ambiguity. The product needs an abstention option.
3. **A real alternate-energy spectrum is not necessarily an independent replicate.** Here it is a different acquisition condition, and evidence correlation must be considered in scoring/calibration.
4. **The agent cannot ask for measurements not present in the virtual laboratory**; the available actions are fixed and visible.
5. **Information gain requires an observation likelihood model.** Predicted candidate separation by itself is a heuristic and must be labeled accordingly.
6. **Reference endpoints for the test compound are available by construction.** Evaluation tests a *library-supported identification workflow*, not unseen-structure generalization.
7. **Spectral interpolation across CE has prior art.** The research contribution, if verified, is adaptive resource-aware next-measurement selection and robust evidence handling.
8. **MassBank records differ in per-record Creative Commons licenses.** Observe attribution/redistribution conditions; exclude restrictive records if licensing would block planned distribution.
9. **Cohort selection is not proof of generalizability.** Test on a second independently collected and harmonized cohort before making a broad practical claim.
10. **If mass-only identification uniquely determines almost every case, there is no meaningful active experiment to optimize.** The first-day audit may correctly falsify the project hypothesis. Treat that as a scientific finding and pivot transparently.

---

## 13. Initial research references (verify access at setup)

- MassBank source: https://github.com/MassBank/MassBank-data
- MassBank field schema: https://github.com/MassBank/MassBank-web/blob/dev/Documentation/MassBankRecordFormat.md
- MassBank persistent archive: https://doi.org/10.5281/zenodo.3378723
- Published Athens 549-compound/5-energy subset: https://pmc.ncbi.nlm.nih.gov/articles/PMC9400100/ ; https://doi.org/10.1021/acs.jcim.2c00620
- Matching methods: https://matchms.readthedocs.io/en/latest/api/matchms.similarity.html
- Matchms filtering: https://matchms.readthedocs.io/en/latest/api/matchms.filtering.html
- RDKit: https://www.rdkit.org/docs/
- GNPS2 library list (secondary only): https://library.gnps2.org/libraries
- MassSpecGym retrieval benchmark (secondary only): https://github.com/pluskal-lab/MassSpecGym
- Optional 3DMolMS energy-conditioned model: https://3dmolms.readthedocs.io/en/latest/usage/msms_prediction.html
- Original GNPS licensing warning: https://ccms-ucsd.github.io/GNPSDocumentation/downloadlibraries/

**Final instruction to implementation agent:** Build the data audit first. Return the actual 5-energy inventory and the count of scientifically ambiguous identification problems. Use those results to choose the smallest credible scope. Never optimize against a hidden spectrum before paying for that virtual measurement, and never report scientifically unsupported confidence or discovery claims.

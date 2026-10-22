# SpectraPilot: three-minute judge demonstration

Preparation: `make demo`, open http://127.0.0.1:8502. Select **Sample 1** and restart. Keep the generated scientific report available. The samples are curated development examples, not test evidence. Do not announce the expected outcome before the analysis.

| Time | Action and narration |
|---|---|
| 0:00–0:20 | “We have an unknown sample. More spectra cost instrument time; a leading database hit is not automatically an identification. Can we decide what evidence to collect next?” |
| 0:20–0:40 | Click **Load unknown spectrum**. Point to the initial spectrum and precursor m/z 257.08083. “This is the measurement we have. We have not revealed another experimental spectrum.” |
| 0:40–1:00 | Click **Search the reference library**. Show the five structures and shared formula C15H12O4. “They fit the same mass, but their OH positions differ. Mass alone has not identified the sample.” The **Reference library** tab is available if a judge asks what was searched. |
| 1:00–1:25 | Click **Compare fragment fingerprints**. Point to the unresolved decision and the recommendation. “The current evidence does not separate these candidates sufficiently; the planner proposes another measurement from the allowed actions.” |
| 1:25–1:55 | Click **Collect one more spectrum**. Show the before/after conclusion and changed leading structure. In **Why does a structure have evidence?**, compare the acquired CID40 fingerprint with the current and former leader’s references: cosine 0.57 vs 0.04. Disclose that these are CID60 reference proxies; matched peaks are not proven bond assignments. |
| 1:55–2:20 | Click **Finish & create report**. Download Markdown or JSON under **Record the conclusion**. Only after stopping, optionally check the curated source identity. “This records the evidence and limitations behind our conclusion.” |
| 2:20–2:40 | If time permits, investigate another neutrally labelled sample with the same steps. Let its recommendation and result emerge; do not introduce it as the scan-saving or abstention example. |
| 2:40–3:00 | Open **Evidence & results**. “In exploratory training CV, 243 versus 277 optional scans gave 156 versus 157 accepted-correct identifications, with 15 errors each. The contribution is an inspectable measurement-decision workflow; we have not established a general accuracy advantage or live-instrument performance.” |

Leave detailed scores, interventions and audit controls collapsed unless asked. Never substitute the curated sample outcomes for aggregate evaluation. The current prototype does not accept arbitrary uploads, operate an instrument, or use an LLM to calculate scientific scores.

## Concise answers

**What uses AI?** Structure-neighbour, donor-agreement reference construction supplies predicted evidence; a scored experiment-selection policy chooses an action. The demo runs deterministic scientific tools. It does not need an LLM or a multi-agent conversation.

**What is scientifically novel?** This prototype integrates measurement triage, abstention, reversible human intervention and a sealed application interface for archived experiments. Individual library matching and cosine methods are established. Broad scientific novelty remains to be demonstrated against prior work.

**How is leakage prevented?** Hidden measured queries are in the instrument store; only acquired observations reach evidence and planning. Evaluator identity is separate and is accessed explicitly after stopping. Reference studies reconstruct held-out scaffolds; the demonstration uses training donors and allowed development library references. Development outcomes select the three illustrations openly. Tests cover payload boundaries. Filesystem access can reveal local demo data.

**Why not de novo?** The system ranks an existing precursor-compatible candidate library and assumes it contains the true structure. It does not propose or validate arbitrary new molecular structures.

**How many ambiguous test molecules?** The historical frozen MassBank benchmark contains 11 ambiguous test molecules. The displayed MultiMS2 study instead contains 277 ambiguous training molecules assessed by grouped cross-validation; the three demo examples are development cases. These are different populations.

**Why trust it?** Generated reports, frozen configurations, a pinned source snapshot, accession attribution, molecule-level records, explicit errors and abstentions, automated checks, and downloadable audit trails make the claim inspectable. These do not replace independent validation.

**What fails in an open world?** A missing true candidate, poor predicted references, domain-shifted spectra or similar isomers can make a closed-world ranking misleading. Abstention is useful but is not validated proof of out-of-library detection.

**Real-instrument deployment?** Vendor integration, validated energy and instrument calibration, latency and acquisition controls, prospective blinded evaluation, calibrated acceptance thresholds and an operational human approval workflow are still needed.

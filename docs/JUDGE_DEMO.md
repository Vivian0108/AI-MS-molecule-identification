# SpectraPilot: three-minute judge demonstration

Preparation: `make demo`, open http://127.0.0.1:8502. **Sample 1** opens automatically. Keep the generated scientific report available. The samples are curated development examples, not test evidence. Do not announce the expected outcome before the analysis.

| Time | Action and narration |
|---|---|
| 0:00–0:20 | `make demo`, open http://127.0.0.1:8502. **Sample 1** is already open. “One measured spectrum, five mass-compatible structures, and a decision to make. More spectra cost instrument time; a leading database hit is not automatically an identification.” |
| 0:20–0:50 | Point to the spectrum (precursor m/z **257.08083**) and the shortlist (shared formula **C15H12O4**). “All five fit the mass; their OH positions differ. Mass alone has not identified the sample.” Point to **Assessment**: *Unresolved*, support 0.26, margin 0.03, rule not met. |
| 0:50–1:20 | Point to **Next step: Acquire CID40**. “The planner proposes a scan expected to separate these candidates. It sees only the acquired spectrum and public references, not the hidden measurement.” Click **Acquire CID40**. Show the two-scan view: the leader changes, support rises to 0.76 and margin to 0.58. |
| 1:20–1:50 | Click **Compare fragment evidence**. The default comparison is the new leader versus the former leader at CID40: cosine **0.57 vs 0.04**. “The acquired fingerprint supports the new leader; the former leader does not explain it.” Open **Reference library** if asked; disclose that CID40 uses permitted CID60 proxies and that matched peaks are not proven bond assignments. |
| 1:50–2:15 | Click **Create report**. Download Markdown or JSON. “The report records the spectra, ranking, peak-level evidence, interventions and limitations.” Only after stopping, optionally click **Check curated source identity**. |
| 2:15–2:40 | Open **Validation**. “In exploratory training cross-validation, one planned extra scan raises accepted-correct identifications from 21 to 156 of 277. The planner uses 243 versus 277 optional scans and records 156 versus 157 accepted-correct, with 15 errors in each arm. This is a measured tradeoff, not proven equivalence.” |
| 2:40–3:00 | If time, select **Sample 2**: the current evidence already supports identification and the recommendation is to stop, avoiding the optional scan. Or open **Peak tools** to show a reversible sensitivity check. “The contribution is an inspectable measurement-decision workflow with abstention; we have not established a general accuracy advantage or live-instrument performance.” |

Leave detailed scores, interventions and audit controls in their dialogs unless asked. Never substitute the curated sample outcomes for aggregate evaluation. The current prototype does not accept arbitrary uploads, operate an instrument, or use an LLM to calculate scientific scores.

## Concise answers

**What uses AI?** Structure-neighbour, donor-agreement reference construction supplies predicted evidence; a scored experiment-selection policy chooses an action. The demo runs deterministic scientific tools. It does not need an LLM or a multi-agent conversation.

**What is scientifically novel?** This prototype integrates measurement triage, abstention, reversible human intervention and a sealed application interface for archived experiments. Individual library matching and cosine methods are established. Broad scientific novelty remains to be demonstrated against prior work.

**How is leakage prevented?** Hidden measured queries are in the instrument store; only acquired observations reach evidence and planning. Evaluator identity is separate and is accessed explicitly after stopping. Reference studies reconstruct held-out scaffolds; the demonstration uses training donors and allowed development library references. Development outcomes select the three illustrations openly. Tests cover payload boundaries. Filesystem access can reveal local demo data.

**Why not de novo?** The system ranks an existing precursor-compatible candidate library and assumes it contains the true structure. It does not propose or validate arbitrary new molecular structures.

**How many ambiguous test molecules?** The historical frozen MassBank benchmark contains 11 ambiguous test molecules. The displayed MultiMS2 study instead contains 277 ambiguous training molecules assessed by grouped cross-validation; the three demo examples are development cases. These are different populations.

**Why trust it?** Generated reports, frozen configurations, a pinned source snapshot, accession attribution, molecule-level records, explicit errors and abstentions, automated checks, and downloadable audit trails make the claim inspectable. These do not replace independent validation.

**What fails in an open world?** A missing true candidate, poor predicted references, domain-shifted spectra or similar isomers can make a closed-world ranking misleading. Abstention is useful but is not validated proof of out-of-library detection.

**Real-instrument deployment?** Vendor integration, validated energy and instrument calibration, latency and acquisition controls, prospective blinded evaluation, calibrated acceptance thresholds and an operational human approval workflow are still needed.

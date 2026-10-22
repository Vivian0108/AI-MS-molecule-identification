# SpectraPilot: three-minute judge demonstration

Preparation: `make demo`, open http://127.0.0.1:8502. Select **Resolve uncertainty** and reset. Keep the generated scientific report available. The cases are curated development examples, not test evidence.

| Time | Action and narration |
|---|---|
| 0:00–0:20 | “Mass spectrometers can collect more spectra, but every extra acquisition costs time. Similar library candidates should not become a confident answer without sufficient evidence.” |
| 0:20–0:50 | Start the resolve case. Show CID20, five competing candidates, one optional acquisition remaining and the ambiguous decision. “Only the initial archived spectrum is visible.” |
| 0:50–1:10 | Scroll to the recommendation and its candidate-separation rationale. “The planner can choose a measurement or stop; support is a ranking score, not an identity probability.” |
| 1:10–1:40 | Click **Measure CID40**. Show the newly revealed experimental spectrum, changed leading candidate and updated decision. “This is archived experimental evidence, not a spectrum invented by the assistant.” |
| 1:40–2:00 | Optional: expand the observed-peak intervention, exclude one peak with a reason, show changed evidence, then undo. Do not claim an arbitrary excluded peak is chemically invalid. |
| 2:00–2:20 | Stop, download JSON and Markdown. Show the evidence and intervention audit trail. Curated source identity is an explicit post-stop check. |
| 2:20–2:40 | Select **Save a measurement**, start and show stop. Select **Abstain responsibly**, start, measure CID40 and stop: ambiguity remains. |
| 2:40–3:00 | Open Measured results. “In exploratory training CV, 243 versus 277 optional scans gave 156 versus 157 accepted-correct identifications, with 15 errors each. This is closed-world triage; we have not established a general accuracy advantage or live-instrument performance.” |

If time is tight, skip the peak intervention and show the other two cases with their screenshots. Never substitute demo outcomes for aggregate evaluation.

## Concise answers

**What uses AI?** Structure-neighbour, donor-agreement reference construction supplies predicted evidence; a scored experiment-selection policy chooses an action. The demo runs deterministic scientific tools. It does not need an LLM or a multi-agent conversation.

**What is scientifically novel?** This prototype integrates measurement triage, abstention, reversible human intervention and a sealed application interface for archived experiments. Individual library matching and cosine methods are established. Broad scientific novelty remains to be demonstrated against prior work.

**How is leakage prevented?** Hidden measured queries are in the instrument store; only acquired observations reach evidence and planning. Evaluator identity is separate and is accessed explicitly after stopping. Reference studies reconstruct held-out scaffolds; the demonstration uses training donors and allowed development library references. Development outcomes select the three illustrations openly. Tests cover payload boundaries. Filesystem access can reveal local demo data.

**Why not de novo?** The system ranks an existing precursor-compatible candidate library and assumes it contains the true structure. It does not propose or validate arbitrary new molecular structures.

**How many ambiguous test molecules?** The historical frozen MassBank benchmark contains 11 ambiguous test molecules. The displayed MultiMS2 study instead contains 277 ambiguous training molecules assessed by grouped cross-validation; the three demo examples are development cases. These are different populations.

**Why trust it?** Generated reports, frozen configurations, a pinned source snapshot, accession attribution, molecule-level records, explicit errors and abstentions, automated checks, and downloadable audit trails make the claim inspectable. These do not replace independent validation.

**What fails in an open world?** A missing true candidate, poor predicted references, domain-shifted spectra or similar isomers can make a closed-world ranking misleading. Abstention is useful but is not validated proof of out-of-library detection.

**Real-instrument deployment?** Vendor integration, validated energy and instrument calibration, latency and acquisition controls, prospective blinded evaluation, calibrated acceptance thresholds and an operational human approval workflow are still needed.

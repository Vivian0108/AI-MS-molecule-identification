# Reversible peak exclusion: development feasibility spike

**Technical result: GO for the development replay mechanism**. Sensitivity experiment only; no truth evaluation or accuracy claim.

Same three development cases as the baseline. Fixed intervention: exclude the strongest non-precursor CID20 peak (distance > 0.02 Da; ties by original index), then replay only acquired spectra and undo. No threshold or planner changes.

| Case | Original peak index | Excluded m/z | Top-1 changed | Ranking changed | Recommendation before → excluded | Decision preview before → excluded | Max support change | Undo restored |
|---|---:|---:|---|---|---|---|---:|---|
| case-07a97a0a6a07 | 1 | 109.044672 | False | False | STOP → STOP | OUT_OF_LIBRARY → OUT_OF_LIBRARY | 0.000404 | True |
| case-0a1e06ef187c | 2 | 223.028140 | True | True | CID40 → CID40 | AMBIGUOUS → OUT_OF_LIBRARY | 0.123963 | True |
| case-0b7596d031d3 | 0 | 172.075495 | False | False | CID40 → CID40 | OUT_OF_LIBRARY → OUT_OF_LIBRARY | 0.119164 | True |

## Replay after the original recommended measurement

| Case | Acquired optional action | Top-1 changed by exclusion | Recommendation changed | Decision preview changed | Undo restored |
|---|---|---|---|---|---|
| case-07a97a0a6a07 | none (original plan STOP) | — | — | — | — |
| case-0a1e06ef187c | CID40 | False | False | True | True |
| case-0b7596d031d3 | CID40 | False | False | False | True |

## Checks and interpretation

- development_cases_completed: 3.
- initial_stage_undo_restored: 3.
- after_measurement_undo_restored: 2.
- replay_made_no_oracle_reads: True.
- budget_and_acquired_actions_preserved: True.
- hidden_payload_checks_passed: True.
- inputs_unchanged: True.
- json_and_markdown_exports_include_history: True.

## Limitations

- Synthetic and three fixed development cases demonstrate software behavior, not accuracy or user benefit.
- Peak exclusion is a sensitivity edit; no excluded peak was established to be contamination.
- Decision-if-stopped is a preview using existing uncalibrated support and frozen thresholds.
- Underlying CID60/CID40 mismatch, kNN template limitations and closed-world assumptions remain.
- Application-level sealing only: committed curated records contain target spectra and identities.
- No MCP, LLM client, interactive canvas, or broader security certification in this step.

Run: `make peak-exclusion-spike` after dependency installation.

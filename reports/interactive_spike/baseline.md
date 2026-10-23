# Interactive evidence spike: baseline

Development-only runtime check, not scientific evaluation. No truth-based scoring.

Selection: first three lexicographically sorted precursor-ambiguous dev case IDs.

| Case | Candidates | Recommended | Optional scans | Final decision |
|---|---:|---|---:|---|
| case-07a97a0a6a07 | 2 | STOP | 0 | OUT_OF_LIBRARY |
| case-0a1e06ef187c | 8 | CID40 | 1 | IDENTIFIED |
| case-0b7596d031d3 | 2 | CID40 | 1 | IDENTIFIED |

All cases exported JSON and Markdown successfully.

- Runtime smoke check only; no truth evaluation or identification accuracy claim.
- No MCP, interventions or canvas implemented at this baseline stage.
- Original service thresholds, references and planner unchanged.
- Committed curated records include target spectra and identities: application-level sealing only.
- Reference CID40 uses CID60 spectra; EAD16 uses train-only kNN templates.

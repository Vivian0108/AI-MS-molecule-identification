# Interactive evidence feasibility spike

## Step 1: development baseline

Branch `interactive-mcp-spike` starts from GitHub main `166f03c`.
This step tests runtime feasibility, not scientific accuracy. It adds no MCP
server, intervention engine, canvas or model training yet.

After installing the existing project dependencies:

```sh
make interactive-baseline
```

The command selects the first three lexicographically sorted precursor-ambiguous
development case IDs before looking at outcomes. It reconstructs their sealed
measurements from existing committed MultiMS2 records using the original case-ID
rule and compound precursor. It never reads test query records, downloads raw
data, refits references, changes thresholds/seeds, or writes historical reports.
The candidate reference library remains the existing closed-world library.

Outputs:

- `reports/interactive_spike/baseline.json` and `.md`: generated runtime summaries,
  dependency versions and input hashes.
- `data/multims2/oracle_private/interactive_spike/`: ignored dev-only oracle and
  full JSON/Markdown traces for subsequent intervention comparisons.

### Validation on 2026-10-22

- Before edits: 44 tests passed in 11.66 s.
- After edits: `make verify` passed, including 47 tests in 2.67 s, original
  API/service imports and original config checks.
- Ruff check and format check passed for the added runner and tests.
- All three selected development cases completed and exported JSON and Markdown.
  One recommended STOP; two recommended CID40; one of the measured cases changed
  its top-ranked candidate. Correctness was not evaluated.
- Used Python 3.12.12 and the previously installed locked research environment
  at `/private/tmp/unknownid-feas-env/.venv`; no fresh dependency installation was
  rehearsed. Package versions are in the generated JSON. Main currently has no
  dependency lockfile.

Exact command in this session (override `PY` for another environment):

```sh
make interactive-baseline PY=/private/tmp/unknownid-feas-env/.venv/bin/python
make verify PY=/private/tmp/unknownid-feas-env/.venv/bin/python
```

The original service could not start from a clean clone because its private
oracle is ignored, and `_state` incorrectly expected candidate IDs in the public
case summary. The spike supplies a separate dev oracle path and obtains candidate
IDs from the internal session. The default research-oracle path is unchanged.

The baseline uses the real service: start, inspect evidence, request a plan,
measure its recommendation when applicable, stop and export. STOP is respected;
it does not force a scan to make an example look successful. IDENTIFIED is a
runtime decision, not verified correctness; truth is not evaluated here.

## Boundaries before MCP work

The repository's committed `records.parquet` includes target spectra and compound
identities despite the manifest's claim that targets exist only in the private
oracle. The sealing is at the application boundary, not a protection against an
agent with unrestricted repository/filesystem access. A future MCP server must
expose only typed, allowlisted operations and no arbitrary file access. A public
demo needs a separate restricted development bundle.

The existing report/provenance functions also need review before MCP exposure;
passing the baseline checks does not certify every service method as safe. The
spike's tests cover the start/plan/measure payloads and measurement budget/stopped
session restrictions. Existing CID60/CID40 mismatch and uncalibrated support
limitations remain.

## Step 2: reversible observed-peak exclusion

The [protocol](peak_exclusion_protocol.md) was committed as `eb63d88` before the
intervention experiment. Run the same three development cases with:

```sh
make peak-exclusion-spike PY=/private/tmp/unknownid-feas-env/.venv/bin/python
```

For another installed environment, override `PY` with its interpreter. No new
dependencies are required. No MCP server, LLM client or canvas is included yet.

The service now supports:

```python
before = service.get_evidence(case_id)
edit = service.exclude_observed_peak(
    case_id, action="CID20", peak_index=0,
    reason="Scientist requests a sensitivity check; contamination is not established.",
)
restored = service.undo_intervention(
    case_id, edit["intervention"]["intervention_id"], reason="Restore original evidence.",
)
```

`peak_index` refers to the original archived peak order, even after other peaks
are excluded. The raw observation is preserved. Replay masks peaks before the
existing preprocessing/scoring and recomputes all acquired observations in order.
It makes no new oracle reads and neither spends nor refunds acquisition budget.
The evidence response includes active exclusions, original spectrum hashes,
history and a clearly named `decision_if_stopped` preview. Exclusion/undo reasons
and hashes are retained in JSON and Markdown exports. Edits are prohibited after
stop. Original accessions are now also withheld from report provenance until
stop, matching the existing documented embargo.

### Development findings

- The fixed strongest-non-precursor exclusion changed support in all three
  cases and the initial leading candidate in one of three.
- No acquisition recommendation changed on these three real cases. One initial
  decision preview changed from AMBIGUOUS to OUT_OF_LIBRARY.
- Both originally recommended CID40 measurements were retained during subsequent
  replay; exclusion changed the decision preview in one of these two cases.
- Undo restored all three initial states and both states with CID40 acquired.
  Comparisons check full rankings, scores/support, plans and QC at absolute
  tolerance 1e-12, with no relative tolerance.
- A synthetic distinguishing-peak control changed support in the expected
  direction, flipped the leading candidate and changed the recommendation.
- Invalid edits, duplicate exclusions, multiple exclusions with non-LIFO undo,
  scoring-failure rollback, sparse/empty edited spectra and stopped-session
  guards are covered by tests. Sparse edited CID20 spectra fail existing QC.
- An explicit comparison against the pre-intervention `512b49b` session matched
  unedited rankings, plans, decisions, QC and final JSON investigations exactly
  on all three cases, including both optional measurements.

Generated [Markdown](../reports/interactive_spike/peak_exclusion.md) and
[JSON](../reports/interactive_spike/peak_exclusion.json) contain the before,
excluded and restored evidence. Full stopped-case exports remain ignored under
`data/multims2/oracle_private/peak_exclusion_spike/`. Historical baseline and
scientific reports, curated data, split, seeds, thresholds, references and
planner code are unchanged.

**Technical GO for reversible replay.** This does not show improved accuracy,
that excluded peaks were contaminants, or that scientists benefit from the
interaction. A real-case recommendation change was not demonstrated.

## Next gate

Wrap the observed-evidence operations in a restricted MCP server and exercise
the workflow through a client. Preserve the application-boundary restrictions
above. Build a minimal UI only after that check. No identification accuracy
improvement follows from a successful software smoke check.

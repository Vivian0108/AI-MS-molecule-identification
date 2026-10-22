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

## Next gate

Only after the baseline succeeds: implement one reversible observed-peak
exclusion, replay from original evidence, check synthetic positive controls and
baseline restoration, then wrap the allowlisted operations in MCP. Build a
minimal UI only if that spike is reproducible and useful. No identification
accuracy improvement follows from a successful software smoke check.

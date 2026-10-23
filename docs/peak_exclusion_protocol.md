# Reversible peak exclusion: feasibility protocol

This is a software sensitivity experiment, not an accuracy evaluation. Use only
the same three development cases selected by the baseline rule; no truth-based
case selection or scoring. No model fitting, planner changes, threshold changes,
new acquisitions, or MCP/UI work is part of this step.

## Intervention and replay

- Exclude exactly one already observed peak, addressed by its zero-based index
  in the original archived observation. Record the observation/action, original
  spectrum SHA-256, index, m/z, intensity, reason and intervention ID.
- Preserve the original observation. Recompute from CID20 followed by all
  already acquired observations in acquisition order, using the existing
  preprocessing, scorer, thresholds and planner. Mask before preprocessing.
- Exclusions never reveal another spectrum or refund/consume acquisition budget.
- Undo deactivates the requested exclusion; the exclusion and undo remain in
  append-only intervention history and exported evidence reports.
- Reject unobserved actions, invalid indices, duplicate active exclusions,
  blank reasons, unknown/already-undone IDs, and edits after stop.

## Development experiment

For each case, exclude the strongest non-precursor CID20 peak (absolute distance
from precursor greater than the existing 0.02 Da matching tolerance). Break ties
by the lowest original index. This rule is fixed before inspecting intervention
outcomes. Label the reason as a synthetic sensitivity intervention; do not claim
the peak is contamination.

Record before, excluded and restored scores/support, ranking, recommendation,
and decision-if-stopped. The latter is explicitly a preview, not an accepted
identification. Undo, then follow the original measurement recommendation if
it requests an acquisition. Repeat exclusion/replay/undo with the additional
measurement retained, then stop and export JSON and Markdown. If the original
plan is STOP, do not force a measurement.

## Technical go/no-go

- All three cases run and export, with no hidden measurement or truth in public
  intervention/evidence payloads.
- At least one synthetic positive control has analytically expected support
  changes and a ranking change when a distinguishing observed peak is excluded.
- Undo restores candidate order, scores/support, recommendation and
  decision-if-stopped within absolute tolerance 1e-12 (zero relative tolerance).
- Replay performs no oracle reads and preserves budget and acquired actions.
- Invalid edits are rejected without changing evidence or intervention history.
- Sparse edited initial spectra fail the existing three-peak QC requirement.

Changed real-case rankings/recommendations are not required for technical GO.
Report their observed frequency without treating it as accuracy or utility.
Frozen test measurements and historical scientific reports remain untouched.

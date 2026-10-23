"""Inspect observed evidence without accessing hidden experiments or truth."""

from __future__ import annotations

from unknownid.core.spectra import preprocess_peaks


def compare_observed_candidates(service, case_id, action, candidate_ids):
    """Reproduce per-observation matches for display, with active peak masks.

    Only an already acquired observation and public candidate references are
    consulted. Per-action similarity is not the combined ranking or probability.
    """
    state = service.get_evidence(case_id)
    if action not in state["observed_actions"]:
        raise ValueError("Only acquired spectra can be explained.")
    original = service.session(case_id).observation(action)
    excluded = {
        row["peak_index"] for row in state["active_peak_exclusions"] if row["action"] == action
    }
    keep = [index for index in range(len(original.mz)) if index not in excluded]
    observed = preprocess_peaks(original.mz[keep], original.intensity[keep], rel_floor=0.0)
    precursor = service.case_summary(case_id)["precursor_mz"]
    rows = []
    for candidate_id in candidate_ids:
        candidate = service.references.candidate(candidate_id)
        template = service.references.template(candidate_id, action)
        item = service.scorer.explain(observed, candidate, template, action, precursor_mz=precursor)
        rows.append(
            {
                "candidate_id": candidate_id,
                "name": candidate.name,
                "cosine": item.similarity_by_action[action],
                "matched_peaks": item.matched_peaks_by_action[action],
                "matches": item.matched_fragments,
                "reference_source": template.source,
                "reference_mz": template.mz.tolist(),
                "reference_intensity": template.intensity.tolist(),
            }
        )
    # Show the strongest acquired fragment peaks, omitting the intact precursor.
    strongest = sorted(
        (
            (float(mz), float(intensity))
            for mz, intensity in zip(observed.mz, observed.intensity)
            if abs(mz - precursor) > service.scorer.tolerance_da
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )[:3]
    return {
        "action": action,
        "observed_mz": observed.mz.tolist(),
        "observed_intensity": observed.intensity.tolist(),
        "strongest_fragments": strongest,
        "candidates": rows,
        "tolerance_da": service.scorer.tolerance_da,
    }

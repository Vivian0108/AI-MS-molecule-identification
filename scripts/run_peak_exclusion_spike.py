"""Fixed dev-only sensitivity protocol; no accuracy evaluation or MCP/UI work."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import subprocess
from datetime import UTC, datetime

import numpy as np

from run_interactive_baseline import build_dev_oracle, sha256
from spectrapilot.paths import ORACLE_PRIVATE, ROOT
from spectrapilot.service import SpectraPilotService

OUTPUT = ROOT / "reports" / "interactive_spike"
PRIVATE = ORACLE_PRIVATE / "peak_exclusion_spike"
TOLERANCE = 1e-12
REASON = "Protocol sensitivity experiment: exclude strongest non-precursor peak; contamination not established."


def compare(before: dict, after: dict) -> dict:
    old = before["ranking"]["candidates"]
    new = after["ranking"]["candidates"]
    old_order = [row["candidate_id"] for row in old]
    new_order = [row["candidate_id"] for row in new]
    old_by_id = {row["candidate_id"]: row for row in old}
    new_by_id = {row["candidate_id"]: row for row in new}
    keys = set(old_by_id) & set(new_by_id)
    max_support_delta = max(
        (abs(new_by_id[cid]["weight"] - old_by_id[cid]["weight"]) for cid in keys), default=0.0
    )
    max_cosine_delta = max(
        (
            abs(value - old_by_id[cid]["similarity_by_action"][action])
            for cid in keys
            for action, value in new_by_id[cid]["similarity_by_action"].items()
        ),
        default=0.0,
    )
    return {
        "candidate_set_changed": set(old_by_id) != set(new_by_id),
        "ranking_changed": old_order != new_order,
        "top1_changed": old_order[:1] != new_order[:1],
        "max_absolute_support_change": max_support_delta,
        "max_absolute_cosine_change": max_cosine_delta,
        "recommendation_changed": before["plan"]["recommended"]["key"]
        != after["plan"]["recommended"]["key"],
        "decision_preview_changed": before["decision_if_stopped"] != after["decision_if_stopped"],
    }


def assert_restored(before: dict, restored: dict) -> None:
    """Compare full evidence/plan/QC, with no tolerance for structural differences."""

    def check(a, b):
        if isinstance(a, dict):
            assert isinstance(b, dict) and a.keys() == b.keys()
            for key in a:
                check(a[key], b[key])
        elif isinstance(a, list):
            assert isinstance(b, list) and len(a) == len(b)
            for av, bv in zip(a, b):
                check(av, bv)
        elif isinstance(a, float):
            assert np.isclose(a, b, atol=TOLERANCE, rtol=0, equal_nan=False)
        else:
            assert a == b

    for key in before:
        if key not in {"active_peak_exclusions", "intervention_history"}:
            check(before[key], restored[key])


def _exercise(service: SpectraPilotService, case_id: str, peak_index: int) -> dict:
    session = service.session(case_id)
    before = service.get_evidence(case_id)
    observed = session.observation("CID20")
    original_mz, original_intensity = observed.mz.copy(), observed.intensity.copy()
    edited = service.exclude_observed_peak(case_id, "CID20", peak_index, REASON)
    event = edited["intervention"]
    after = edited["evidence"]
    assert before["observed_actions"] == after["observed_actions"]
    assert before["remaining_budget"] == after["remaining_budget"]
    assert np.array_equal(session.observation("CID20").mz, original_mz)
    assert np.array_equal(session.observation("CID20").intensity, original_intensity)
    undone = service.undo_intervention(
        case_id, event["intervention_id"], "Protocol undo: restore original evidence."
    )
    restored = undone["evidence"]
    assert_restored(before, restored)
    assert not restored["active_peak_exclusions"]
    return {
        "before": before,
        "excluded": after,
        "restored": restored,
        "intervention": event,
        "undo": undone["intervention"],
        "changes": compare(before, after),
        "undo_restored": True,
    }


def render_markdown(payload: dict) -> str:
    lines = [
        "# Reversible peak exclusion: development feasibility spike",
        "",
        "**Technical result: " + payload["technical_result"] + "**. "
        "Sensitivity experiment only; no truth evaluation or accuracy claim.",
        "",
        "Same three development cases as the baseline. Fixed intervention: exclude "
        "the strongest non-precursor CID20 peak (distance > 0.02 Da; ties by original index), "
        "then replay only acquired spectra and undo. No threshold or planner changes.",
        "",
        "| Case | Original peak index | Excluded m/z | Top-1 changed | Ranking changed | Recommendation before → excluded | Decision preview before → excluded | Max support change | Undo restored |",
        "|---|---:|---:|---|---|---|---|---:|---|",
    ]
    for row in payload["cases"]:
        trial = row["initial_stage"]
        before, after = trial["before"], trial["excluded"]
        lines.append(
            f"| {row['case_id']} | {row['peak_index']} | {row['excluded_mz']:.6f} | "
            f"{trial['changes']['top1_changed']} | {trial['changes']['ranking_changed']} | "
            f"{before['plan']['recommended']['key']} → {after['plan']['recommended']['key']} | "
            f"{before['decision_if_stopped']} → {after['decision_if_stopped']} | "
            f"{trial['changes']['max_absolute_support_change']:.6f} | {trial['undo_restored']} |"
        )
    lines += [
        "",
        "## Replay after the original recommended measurement",
        "",
        "| Case | Acquired optional action | Top-1 changed by exclusion | Recommendation changed | Decision preview changed | Undo restored |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["cases"]:
        trial = row["after_measurement_stage"]
        if trial is None:
            lines.append(f"| {row['case_id']} | none (original plan STOP) | — | — | — | — |")
        else:
            changes = trial["changes"]
            lines.append(
                f"| {row['case_id']} | {row['acquired_action']} | {changes['top1_changed']} | "
                f"{changes['recommendation_changed']} | {changes['decision_preview_changed']} | "
                f"{trial['undo_restored']} |"
            )
    lines += ["", "## Checks and interpretation", ""]
    lines += [f"- {key}: {value}." for key, value in payload["checks"].items()]
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines += ["", "Run: `make peak-exclusion-spike` after dependency installation.", ""]
    return "\n".join(lines)


def run() -> dict:
    selected_ids, oracle = build_dev_oracle()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    oracle_path = PRIVATE / "cases.json"
    oracle_path.write_text(json.dumps(oracle, separators=(",", ":")) + "\n")
    service = SpectraPilotService(oracle_path=oracle_path)
    source_paths = [
        "configs/multims2.yaml",
        "configs/policies.yaml",
        "data/multims2/curated/split_manifest.json",
        "data/multims2/curated/records.parquet",
        "data/multims2/curated/cases.parquet",
        "data/multims2/reference/templates.parquet",
    ]
    input_hashes = {path: sha256(ROOT / path) for path in source_paths}
    rows = []
    for case_id in selected_ids:
        started = service.start_case(case_id)
        assert started["case"]["split"] == "dev"
        original = service.session(case_id).observation("CID20")
        tolerance = service.scorer.tolerance_da
        eligible = np.flatnonzero(np.abs(original.mz - started["case"]["precursor_mz"]) > tolerance)
        if not len(eligible):
            raise RuntimeError(
                f"no non-precursor peak in preselected case {case_id}; do not replace it"
            )
        peak_index = int(eligible[np.argmax(original.intensity[eligible])])
        log_path = service.oracle._log_path  # evaluator-side check only; never in a public payload
        oracle_log_before = log_path.read_bytes()
        initial = _exercise(service, case_id, peak_index)
        assert log_path.read_bytes() == oracle_log_before
        acquired_action = initial["before"]["plan"]["recommended"]["key"]
        after_measurement = None
        if acquired_action != "STOP":
            service.measure(case_id, acquired_action)
            oracle_log_before = log_path.read_bytes()
            after_measurement = _exercise(service, case_id, peak_index)
            assert log_path.read_bytes() == oracle_log_before
        # Responses before stop may name available actions/templates, but must
        # not reveal source accessions or numeric arrays of hidden measurements.
        public = json.dumps({"initial": initial, "after_measurement": after_measurement})
        assert "true_molecule_id" not in public and '"hidden"' not in public
        for action, hidden in oracle[case_id]["hidden"].items():
            assert hidden["accession"] not in public
            if action not in service.session(case_id).observed_actions:
                assert json.dumps(hidden["peaks_mz"]) not in public
        stopped = service.stop(case_id)
        exported = service.report(case_id)
        assert stopped["investigation"] == exported["investigation"]
        assert not exported["investigation"]["active_peak_exclusions"]
        history = exported["investigation"]["intervention_history"]
        assert len(history) == (4 if after_measurement else 2)
        for event in history:
            assert event["intervention_id"] in exported["report_markdown"]
        (PRIVATE / f"{case_id}.json").write_text(json.dumps(exported, indent=2) + "\n")
        (PRIVATE / f"{case_id}.md").write_text(exported["report_markdown"])
        rows.append(
            {
                "case_id": case_id,
                "split": "dev",
                "peak_index": peak_index,
                "excluded_mz": float(original.mz[peak_index]),
                "initial_stage": initial,
                "acquired_action": acquired_action,
                "after_measurement_stage": after_measurement,
                "final_decision": exported["investigation"]["decision"],
                "optional_scans": int(acquired_action != "STOP"),
                "export_history_events": len(history),
            }
        )
    assert input_hashes == {path: sha256(ROOT / path) for path in source_paths}
    payload = {
        "study": "Reversible peak exclusion: development sensitivity experiment",
        "technical_result": "GO for the development replay mechanism",
        "scientific_evaluation": False,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {
            path: sha256(ROOT / path)
            for path in (
                "scripts/run_peak_exclusion_spike.py",
                "docs/peak_exclusion_protocol.md",
                "src/spectrapilot/planning/interventions.py",
                "src/spectrapilot/planning/session.py",
                "src/spectrapilot/models.py",
                "src/spectrapilot/service.py",
            )
        },
        "input_sha256": input_hashes,
        "python": platform.python_version(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "pyarrow", "pydantic", "rdkit", "pytest")
        },
        "protocol_commit": "eb63d88",
        "restoration_absolute_tolerance": TOLERANCE,
        "checks": {
            "development_cases_completed": len(rows),
            "initial_stage_undo_restored": sum(
                row["initial_stage"]["undo_restored"] for row in rows
            ),
            "after_measurement_undo_restored": sum(
                row["after_measurement_stage"]["undo_restored"]
                for row in rows
                if row["after_measurement_stage"]
            ),
            "replay_made_no_oracle_reads": True,
            "budget_and_acquired_actions_preserved": True,
            "hidden_payload_checks_passed": True,
            "inputs_unchanged": True,
            "json_and_markdown_exports_include_history": True,
        },
        "cases": rows,
        "limitations": [
            "Synthetic and three fixed development cases demonstrate software behavior, not accuracy or user benefit.",
            "Peak exclusion is a sensitivity edit; no excluded peak was established to be contamination.",
            "Decision-if-stopped is a preview using existing uncalibrated support and frozen thresholds.",
            "Underlying CID60/CID40 mismatch, kNN template limitations and closed-world assumptions remain.",
            "Application-level sealing only: committed curated records contain target spectra and identities.",
            "No MCP, LLM client, interactive canvas, or broader security certification in this step.",
        ],
    }
    (OUTPUT / "peak_exclusion.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUTPUT / "peak_exclusion.md").write_text(render_markdown(payload))
    print(
        json.dumps(
            {
                "technical_result": payload["technical_result"],
                "checks": payload["checks"],
                "report": "reports/interactive_spike/peak_exclusion.md",
            },
            indent=2,
        )
    )
    return payload


if __name__ == "__main__":
    run()

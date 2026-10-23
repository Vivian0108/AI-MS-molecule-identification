"""Run the fixed three-development-case protocol and verify generated reports."""

import importlib.util
import json
from pathlib import Path


def test_development_experiment_and_report_consistency(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "peak_exclusion_spike", root / "scripts" / "run_peak_exclusion_spike.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, "PRIVATE", tmp_path / "private")
    monkeypatch.setattr(runner, "OUTPUT", tmp_path / "reports")
    baseline_path = root / "reports" / "interactive_spike" / "baseline.json"
    baseline_hash = runner.sha256(baseline_path)
    baseline = json.loads(baseline_path.read_text())
    payload = runner.run()
    assert runner.sha256(baseline_path) == baseline_hash
    assert [case["case_id"] for case in payload["cases"]] == [
        case["case_id"] for case in baseline["cases"]
    ]
    assert all(case["split"] == "dev" for case in payload["cases"])
    assert payload["checks"]["initial_stage_undo_restored"] == 3
    assert payload["checks"]["after_measurement_undo_restored"] == 2
    assert payload["scientific_evaluation"] is False
    saved = json.loads((runner.OUTPUT / "peak_exclusion.json").read_text())
    assert saved == payload
    assert (runner.OUTPUT / "peak_exclusion.md").read_text() == runner.render_markdown(saved)
    for case in payload["cases"]:
        exported = json.loads((runner.PRIVATE / f"{case['case_id']}.json").read_text())
        history = exported["investigation"]["intervention_history"]
        assert len(history) == case["export_history_events"]
        assert exported["investigation"]["active_peak_exclusions"] == []
        assert (runner.PRIVATE / f"{case['case_id']}.md").read_text() == exported["report_markdown"]
        # Comparisons use the original spectrum indices in both stages.
        event = case["initial_stage"]["intervention"]
        assert event["peak_index"] == case["peak_index"]
        assert event["mz"] == case["excluded_mz"]
        if case["after_measurement_stage"]:
            later = case["after_measurement_stage"]
            assert (
                later["intervention"]["original_spectrum_sha256"]
                == event["original_spectrum_sha256"]
            )
            assert later["restored"]["remaining_budget"] == 0


def test_checked_in_report_is_generated_from_json(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "peak_exclusion_spike_report", root / "scripts" / "run_peak_exclusion_spike.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    reports = root / "reports" / "interactive_spike"
    source = json.loads((reports / "peak_exclusion.json").read_text())
    assert (reports / "peak_exclusion.md").read_text() == runner.render_markdown(source)

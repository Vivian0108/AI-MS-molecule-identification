"""Real dev-only service smoke checks; not an accuracy evaluation."""

import importlib.util
import json
from pathlib import Path

import pytest

from spectrapilot.planning.oracle import OracleAccessError
from spectrapilot.service import SpectraPilotService

SPEC = importlib.util.spec_from_file_location(
    "interactive_baseline",
    Path(__file__).resolve().parents[1] / "scripts/run_interactive_baseline.py",
)
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


@pytest.fixture(scope="module")
def dev_oracle():
    return baseline.build_dev_oracle()


@pytest.fixture
def service(dev_oracle, tmp_path):
    _, payload = dev_oracle
    path = tmp_path / "dev_oracle.json"
    path.write_text(json.dumps(payload))
    return SpectraPilotService(oracle_path=path)


def test_start_case_uses_internal_candidate_ids(service, dev_oracle):
    """Regression: Case.public_dict deliberately omits candidate_ids."""
    ids, _ = dev_oracle
    state = service.start_case(ids[0])
    assert state["case"]["split"] == "dev"
    assert "candidate_ids" not in state["case"]
    assert len(state["candidates"]) == state["case"]["n_candidates"] >= 2
    assert state["observed_actions"] == ["CID20"]
    assert state["observation"]["accession"] is None


def test_dev_only_reconstruction_and_measurement_boundaries(service, dev_oracle):
    ids, payload = dev_oracle
    assert len(ids) == 3
    assert set(payload) == set(ids)
    for case_id in ids:
        assert service.repository.case(case_id).split == "dev"
        state = service.start_case(case_id)
        # Public start/plan payloads may name available energies and predicted
        # templates, but contain no hidden observation arrays or truth labels.
        assert not ({"truth", "true_molecule_id", "hidden"} & set(state))
        encoded = json.dumps(state)
        for hidden in payload[case_id]["hidden"].values():
            assert hidden["accession"] not in encoded
            assert json.dumps(hidden["peaks_mz"]) not in encoded
        measured = service.measure(case_id, "CID40")
        assert measured["measurement"]["mz"] == payload[case_id]["hidden"]["CID40"]["peaks_mz"]
        assert measured["remaining_budget"] == 0
        assert measured["measurement"]["accession"] is None
        with pytest.raises(OracleAccessError, match="budget exhausted"):
            service.measure(case_id, "EAD16")
        with pytest.raises(OracleAccessError, match="already been measured"):
            service.measure(case_id, "CID40")
        service.stop(case_id)
        with pytest.raises(OracleAccessError, match="already stopped"):
            service.measure(case_id, "EAD16")
        exported = service.report(case_id)
        assert exported["investigation"]["observed_actions"] == ["CID20", "CID40"]
        assert "# SpectraPilot investigation report" in exported["report_markdown"]
        assert "EAD16" not in exported["provenance"]["observed_accessions"]


def test_baseline_exports_and_report_consistency(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "PRIVATE", tmp_path / "private")
    monkeypatch.setattr(baseline, "OUTPUT", tmp_path / "reports")
    result = baseline.run()
    saved = json.loads((baseline.OUTPUT / "baseline.json").read_text())
    assert result == saved
    markdown = (baseline.OUTPUT / "baseline.md").read_text()
    for row in result["cases"]:
        assert row["split"] == "dev"
        assert (
            f"| {row['case_id']} | {row['n_candidates']} | {row['recommended_action']} | "
            in markdown
        )
        trace = json.loads((baseline.PRIVATE / f"{row['case_id']}.json").read_text())
        assert trace["initial"]["observed_actions"] == ["CID20"]
        assert (baseline.PRIVATE / f"{row['case_id']}.md").read_text() == trace["final"][
            "report_markdown"
        ]

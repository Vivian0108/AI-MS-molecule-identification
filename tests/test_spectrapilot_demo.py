"""Offline demo, reveal boundaries, real UI flows and export smoke tests."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from spectrapilot.demo import DEMO, DemoService
from spectrapilot.demo_api import create_app
from spectrapilot.planning.interventions import InterventionError
from spectrapilot.planning.oracle import OracleAccessError
from spectrapilot.service import ServiceError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pilot():
    service = DemoService()
    yield service
    service.close()


def forbidden_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            assert key not in {"true_id", "true_molecule_id", "truth", "hidden"}
            forbidden_keys(child)
    elif isinstance(value, list):
        for child in value:
            forbidden_keys(child)


def test_bundle_checksums_license_and_development_only():
    manifest = json.loads((DEMO / "build_manifest.json").read_text())
    for relative, expected in manifest["files"].items():
        assert hashlib.sha256((DEMO / relative).read_bytes()).hexdigest() == expected
    cases = json.loads((DEMO / "public/cases.json").read_text())
    oracle = json.loads((DEMO / "instrument/cases.json").read_text())
    assert len(cases) == len(oracle) == 3
    assert {row["split"] for row in cases} == {"dev"}
    assert set(oracle) == {row["case_id"] for row in cases}
    for row in cases:
        assert len(row["candidate_ids"]) >= 2
    for filename in (
        "cases.json",
        "candidates.json",
        "templates.json",
        "manifest.json",
        "reference_provenance.json",
    ):
        forbidden_keys(json.loads((DEMO / "public" / filename).read_text()))
    attribution = json.loads((DEMO / "instrument/attribution.json").read_text())
    assert len(attribution) == 9 and {row["license"] for row in attribution} == {"CC0-1.0"}
    assert "CC0" in (DEMO / "DATA_LICENSE.txt").read_text()


def test_runtime_needs_no_research_parquet_or_oracle(monkeypatch):
    original = Path.read_text

    def guard(path, *args, **kwargs):
        assert "data/multims2" not in str(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guard)

    def no_parquet(*args, **kwargs):
        raise AssertionError("demo attempted to load research data")

    monkeypatch.setattr(pd, "read_parquet", no_parquet)
    service = DemoService()
    for example in service.manifest["cases"]:
        cid = example["case_id"]
        service.start_case(cid)
        plan = service.plan(cid)["recommended"]
        if plan["kind"] == "MEASURE":
            service.measure(cid, plan["key"])
        assert service.stop(cid)["demo"]["data_license"] == "CC0-1.0"
    service.close()


@pytest.mark.parametrize(
    "role,decision,action",
    [
        ("resolve", "IDENTIFIED", "CID40"),
        ("stop", "IDENTIFIED", "STOP"),
        ("abstain", "AMBIGUOUS", "CID40"),
    ],
)
def test_complete_curated_investigations(pilot, monkeypatch, role, decision, action):
    case_id = next(row["case_id"] for row in pilot.manifest["cases"] if row["role"] == role)
    read = pilot._read

    def no_evaluator(relative):
        assert not relative.startswith("evaluator/")
        return read(relative)

    monkeypatch.setattr(pilot, "_read", no_evaluator)
    start = pilot.start_case(case_id)
    assert start["observed_actions"] == ["CID20"]
    assert [row["action"] for row in pilot.observations(case_id)] == ["CID20"]
    before = pilot.get_evidence(case_id)
    forbidden_keys(before)
    assert before["plan"]["recommended"]["key"] == action
    with pytest.raises(ServiceError):
        pilot.report(case_id)
    with pytest.raises(ServiceError):
        pilot.reveal_identity(case_id)
    with pytest.raises(InterventionError):
        pilot.exclude_observed_peak(case_id, "EAD16", 0, "unobserved control")
    edit = pilot.exclude_observed_peak(case_id, "CID20", 0, "automated sensitivity control")
    forbidden_keys(edit)
    restored = pilot.undo_intervention(
        case_id, edit["intervention"]["intervention_id"], "restore baseline"
    )
    assert restored["evidence"]["ranking"] == before["ranking"]
    if action != "STOP":
        measured = pilot.measure(case_id, action)
        forbidden_keys(measured)
        assert measured["remaining_budget"] == 0
        with pytest.raises(OracleAccessError):
            pilot.measure(case_id, "EAD16")
    exported = pilot.stop(case_id)
    assert exported["investigation"]["decision"] == decision
    assert len(exported["investigation"]["intervention_history"]) == 2
    assert "automated sensitivity control" in exported["report_markdown"]
    assert pilot.plan(case_id)["recommended"]["kind"] == "STOP"
    if role == "resolve":
        assert (
            before["ranking"]["candidates"][0]["candidate_id"]
            != exported["investigation"]["candidate_evidence"][0]["candidate_id"]
        )
    assert "curated_identity_check" not in exported
    monkeypatch.setattr(pilot, "_read", read)
    revealed = pilot.reveal_identity(case_id)
    assert revealed["outcome"] == ("abstained" if role == "abstain" else "accepted-correct")
    assert "curated_identity_check" in pilot.report(case_id)
    assert "EAD16" not in exported["investigation"]["provenance"]["observed_accessions"]
    with pytest.raises(InterventionError):
        pilot.exclude_observed_peak(case_id, "CID20", 0, "too late")


def test_planning_does_not_call_optional_oracle(pilot, monkeypatch):
    cid = pilot.manifest["cases"][0]["case_id"]
    seen = []
    original = pilot.oracle.measure

    def measure(case_id, action_key, **kwargs):
        seen.append(action_key)
        return original(case_id, action_key, **kwargs)

    monkeypatch.setattr(pilot.oracle, "measure", measure)
    pilot.start_case(cid)
    pilot.plan(cid)
    pilot.get_evidence(cid)
    assert seen == []
    pilot.measure(cid, "CID40")
    assert seen == ["CID40"]


def test_api_health_boundaries_and_both_exports():
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok", "mode": "demo", "cases": 3}
        catalog = client.get("/cases").json()["cases"]
        assert [row["title"] for row in catalog] == ["Sample 1", "Sample 2", "Sample 3"]
        assert all("role" not in row for row in catalog)
        started = client.post("/investigations", json={}).json()
        cid = started["case"]["case_id"]
        assert started["observed_actions"] == ["CID20"]
        assert client.get(f"/investigations/{cid}/report").status_code == 400
        assert client.post(f"/investigations/{cid}/reveal-identity").status_code == 400
        assert (
            client.post(
                f"/investigations/{cid}/exclude",
                json={"action": "EAD16", "peak_index": 0, "reason": "control"},
            ).status_code
            == 400
        )
        assert (
            client.post(f"/investigations/{cid}/measure", json={"action": "CID40"}).status_code
            == 200
        )
        assert (
            client.post(f"/investigations/{cid}/measure", json={"action": "EAD16"}).status_code
            == 400
        )
        assert client.post(f"/investigations/{cid}/stop").status_code == 200
        assert (
            client.get(f"/investigations/{cid}/report").json()["investigation"]["decision"]
            == "IDENTIFIED"
        )
        assert (
            "SpectraPilot investigation report"
            in client.get(f"/investigations/{cid}/report.md").text
        )
        assert (
            client.post(f"/investigations/{cid}/reveal-identity").json()["outcome"]
            == "accepted-correct"
        )
        restarted = client.post("/investigations", json={"case_id": cid}).json()
        assert restarted["observed_actions"] == ["CID20"]
        assert restarted["remaining_budget"] == 1
        assert "curated_identity_check" not in restarted
        assert client.get(f"/investigations/{cid}/report").status_code == 400
        assert client.post(f"/investigations/{cid}/reveal-identity").status_code == 400
        assert client.get("/oracle").status_code == client.get("/truth").status_code == 404


def test_results_snapshot_matches_generated_scientific_source(pilot):
    source = json.loads((ROOT / "reports/spectrapilot/train_stage1_reference.json").read_text())
    assert pilot.results["n"] == source["n_ambiguous"] == 277
    expected = source["cohorts"]["ambiguous_primary"]["training_cid60_anchored"]["methods"][
        "donor_agreement"
    ]["policies"]
    assert pilot.results["library_assisted"] == expected


def test_streamlit_resolution_intervention_and_exports():
    at = AppTest.from_file(str(ROOT / "app/spectrapilot_demo.py"), default_timeout=20).run()
    assert not at.exception
    assert [option for option in at.radio(key="case_selector").options] == [
        "Sample 1",
        "Sample 2",
        "Sample 3",
    ]
    at.button(key="start_case").click().run()
    assert not any(button.key == "measure_recommended" for button in at.button)
    assert any(heading.value == "1 · Start with the unknown spectrum" for heading in at.subheader)
    at.button(key="analyze_case").click().run()
    assert not any(button.key == "measure_recommended" for button in at.button)
    at.button(key="compare_case").click().run()
    assert not at.exception
    baseline = at.session_state["pilot"].get_evidence(at.session_state["active_case"])["ranking"]
    at.button(key="exclude_peak").click().run()
    assert not at.exception
    at.button(key="undo_exclusion-0001").click().run()
    assert (
        at.session_state["pilot"].get_evidence(at.session_state["active_case"])["ranking"]
        == baseline
    )
    at.button(key="measure_recommended").click().run()
    assert not at.exception
    at.button(key="stop_case").click().run()
    assert not at.exception
    assert len(at.get("download_button")) >= 3
    at.button(key="reveal_identity").click().run()
    assert at.session_state["identity"]["outcome"] == "accepted-correct"
    at.session_state["pilot"].close()


@pytest.mark.parametrize("index,expected", [(1, "IDENTIFIED"), (2, "AMBIGUOUS")])
def test_streamlit_stop_and_abstain(index, expected):
    at = AppTest.from_file(str(ROOT / "app/spectrapilot_demo.py"), default_timeout=20).run()
    at.radio(key="case_selector").set_value(index).run()
    at.button(key="start_case").click().run()
    at.button(key="analyze_case").click().run()
    at.button(key="compare_case").click().run()
    if index == 2:
        at.button(key="measure_recommended").click().run()
    at.button(key="stop_case").click().run()
    assert not at.exception
    assert (
        at.session_state["pilot"].report(at.session_state["active_case"])["investigation"][
            "decision"
        ]
        == expected
    )
    at.session_state["pilot"].close()

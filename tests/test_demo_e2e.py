import json

import pytest
from fastapi.testclient import TestClient

from unknownid.api.app import app
from unknownid.paths import CURATED, DEMO
from unknownid.service import UnknownIDService


def assert_sealed(payload):
    if isinstance(payload, dict):
        assert (
            not {"true_molecule_id", "ground_truth_identity", "hidden_spectra", "hidden_accessions"}
            & payload.keys()
        )
        for value in payload.values():
            assert_sealed(value)
    elif isinstance(payload, list):
        for value in payload:
            assert_sealed(value)


@pytest.fixture
def demo_client():
    service = UnknownIDService(demo=True)
    app.dependency_overrides.clear()
    # _service uses get_service directly rather than FastAPI dependency injection.
    import unknownid.api.app as api

    original = api.get_service
    api.get_service = lambda: service
    with TestClient(app) as client:
        yield client, service
    api.get_service = original


def test_demo_investigation_and_exports(demo_client, tmp_path):
    client, service = demo_client
    assert client.get("/health").json()["demo_mode"]
    cid = "case-127895a5f433"
    started = client.post("/cases/start", json={"case_id": cid}).json()
    assert_sealed(started)
    assert started["observed_energies"] == [20]
    assert started["observation"]["accession"] is None
    assert client.get(f"/cases/{cid}/report").status_code == 409
    plan = client.post(f"/cases/{cid}/plan").json()
    assert_sealed(plan)
    assert plan["recommended"]["kind"] == "measure"
    energy = plan["recommended"]["energy_ev"]
    measured = client.post(f"/cases/{cid}/measure", json={"energy_ev": energy})
    assert measured.status_code == 200
    payload = measured.json()
    assert_sealed(payload)
    assert payload["measurement"]["energy_ev"] == energy
    assert payload["measurement"]["accession"] is None
    assert service.session(cid).observed_energies == [20, energy]
    assert (
        client.post(
            f"/cases/{cid}/measure", json={"energy_ev": 30 if energy == 40 else 40}
        ).status_code
        == 409
    )
    stopped = client.post(f"/cases/{cid}/stop")
    assert stopped.status_code == 200
    report = client.get(f"/cases/{cid}/report")
    markdown = client.get(f"/cases/{cid}/report.md")
    assert report.status_code == markdown.status_code == 200
    assert_sealed(report.json())
    assert report.json()["investigation"]["decision"] == "identified"
    assert set(report.json()["provenance"]["observed_accessions"]) == {"20", str(energy)}
    (tmp_path / "report.json").write_text(json.dumps(report.json()))
    (tmp_path / "report.md").write_text(markdown.text)
    assert "Decision" in markdown.text


def test_demo_stops_and_abstains(demo_client):
    _, s = demo_client
    stopped = "case-250b6ac895d0"
    s.start_case(stopped)
    assert s.plan(stopped)["recommended"]["kind"] == "stop"
    s.stop(stopped)
    assert s.report(stopped)["investigation"]["decision"] == "identified"
    cid = "case-e40ea5350560"
    s.start_case(cid)
    energy = s.plan(cid)["recommended"]["energy_ev"]
    s.measure(cid, energy)
    s.stop(cid)
    assert s.report(cid)["investigation"]["decision"] == "ambiguous"


def test_demo_contains_no_frozen_test_identity_or_observation():
    splits = json.loads((CURATED / "splits.json").read_text())["assignment"]
    private = json.loads((DEMO / "sealed_observations.json").read_text())
    assert len(private) in range(3, 6)
    assert all(splits[c["true_molecule_id"]] in {"train", "dev"} for c in private.values())
    import pandas as pd

    library = pd.read_parquet(DEMO / "library.parquet")
    assert set(library.collision_energy_ev) == {10, 50}
    assert all(splits.get(cid) != "test" for cid in library.molecule_id)
    public = pd.read_parquet(DEMO / "public_cases.parquet")
    assert not {"true_molecule_id", "hidden_spectra", "hidden_accessions"} & set(public.columns)
    import hashlib

    attribution = json.loads((DEMO / "attribution.json").read_text())
    for record in attribution:
        assert record["license"] in {"CC BY", "CC BY-SA"}
        raw = DEMO / "source_records" / f"{record['accession']}.txt"
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == record["source_sha256"]
        assert record["original_attribution"]


def test_default_service_falls_back_to_demo(monkeypatch, tmp_path):
    import unknownid.service as module

    monkeypatch.delenv("UNKNOWNID_MODE", raising=False)
    monkeypatch.setattr(module, "existing_oracle_path", lambda: tmp_path / "absent.json")
    service = UnknownIDService()
    assert service.demo_mode
    assert len(service.case_ids()) == 4

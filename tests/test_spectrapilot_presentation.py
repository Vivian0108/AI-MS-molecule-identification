"""Verify public structure provenance and acquired-only explanation correctness."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from spectrapilot.demo import DEMO, DemoService
from spectrapilot.presentation import compare_observed_candidates

ROOT = Path(__file__).resolve().parents[1]


def test_structure_drawings_are_complete_and_derived_from_public_smiles():
    folder = ROOT / "app/assets/structures"
    manifest = json.loads((folder / "manifest.json").read_text())
    public = DEMO / "public/candidates.json"
    assert hashlib.sha256(public.read_bytes()).hexdigest() == manifest["source_sha256"]
    records = json.loads(public.read_text())
    assert set(manifest["candidates"]) == {row["compound_full_inchikey"] for row in records}
    for row in records:
        asset = manifest["candidates"][row["compound_full_inchikey"]]
        assert asset["smiles"] == row["canonical_smiles"]
        svg = (folder / asset["file"]).read_bytes()
        assert b"<svg" in svg
        assert hashlib.sha256(svg).hexdigest() == asset["sha256"]
    # This annotation describes public connectivity, not the curated identity.
    assert manifest["candidates"]["MSDGTBGJKOTHCN-SOFGYWHQSA-N"]["ring_oh_counts"] == [3, 0]


def test_explanation_matches_scoring_without_revealing_or_changing_evidence(monkeypatch):
    pilot = DemoService()
    try:
        cid = pilot.manifest["cases"][0]["case_id"]
        pilot.start_case(cid)
        before = deepcopy(pilot.get_evidence(cid))
        ids = [row["candidate_id"] for row in before["ranking"]["candidates"][:2]]
        measure = pilot.oracle.measure

        def forbidden(*args, **kwargs):
            raise AssertionError("presentation attempted a new measurement")

        monkeypatch.setattr(pilot.oracle, "measure", forbidden)
        with pytest.raises(ValueError, match="Only acquired"):
            compare_observed_candidates(pilot, cid, "CID40", ids)
        result = compare_observed_candidates(pilot, cid, "CID20", ids)
        assert pilot.get_evidence(cid) == before
        for actual, ranked in zip(result["candidates"], before["ranking"]["candidates"]):
            assert actual["cosine"] == pytest.approx(ranked["similarity_by_action"]["CID20"])
            assert actual["matched_peaks"] == ranked["matched_peaks_by_action"]["CID20"]
            assert actual["matches"] == ranked["matched_fragments"]
        assert set(result["observed_mz"]) == set(pilot.observations(cid)[0]["mz"])
        monkeypatch.setattr(pilot.oracle, "measure", measure)
        pilot.measure(cid, "CID40")
        after = pilot.get_evidence(cid)
        top = after["ranking"]["candidates"][0]
        result = compare_observed_candidates(pilot, cid, "CID40", [top["candidate_id"], ids[0]])
        assert result["candidates"][0]["cosine"] == pytest.approx(
            top["similarity_by_action"]["CID40"]
        )
        assert result["candidates"][0]["cosine"] > result["candidates"][1]["cosine"]
        assert all(row["reference_source"] == "reference_cid60" for row in result["candidates"])
    finally:
        pilot.close()


def test_explanation_honors_exclusions_and_undo():
    pilot = DemoService()
    try:
        cid = pilot.manifest["cases"][0]["case_id"]
        pilot.start_case(cid)
        ids = [row["candidate_id"] for row in pilot.ranking(cid)["candidates"][:2]]
        original = compare_observed_candidates(pilot, cid, "CID20", ids)
        excluded_mz = original["observed_mz"][0]
        edit = pilot.exclude_observed_peak(cid, "CID20", 0, "display consistency test")
        changed = compare_observed_candidates(pilot, cid, "CID20", ids)
        assert excluded_mz not in changed["observed_mz"]
        assert len(changed["observed_mz"]) == len(original["observed_mz"]) - 1
        ranked = {row["candidate_id"]: row for row in pilot.ranking(cid)["candidates"]}
        for row in changed["candidates"]:
            assert row["cosine"] == pytest.approx(
                ranked[row["candidate_id"]]["similarity_by_action"]["CID20"]
            )
        pilot.undo_intervention(cid, edit["intervention"]["intervention_id"], "restore original")
        assert compare_observed_candidates(pilot, cid, "CID20", ids) == original
    finally:
        pilot.close()

"""Synthetic controls for reversible evidence edits; no scientific test data."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from spectrapilot.data.repository import CaseRepository
from spectrapilot.planning.interventions import InterventionError, spectrum_sha256
from spectrapilot.planning.oracle import OracleStore, VirtualInstrument
from spectrapilot.planning.separation import SeparationPlanner
from spectrapilot.planning.session import ActionLog, InvestigationSession
from spectrapilot.science.scoring import CandidateScorer
from spectrapilot.science.templates import ReferenceStore


@pytest.fixture
def session_factory(tmp_path):
    def make():
        candidates = pd.DataFrame(
            [
                {
                    "compound_full_inchikey": cid,
                    "name": cid,
                    "canonical_smiles": "CCO",
                    "formula": "C2H6O",
                    "exact_mass": 198.992723533379,
                    "precursor_mz": 200.0,
                }
                for cid in ("A-SYNTHETIC", "B-SYNTHETIC")
            ]
        )
        templates = pd.DataFrame(
            [
                {
                    "candidate_id": cid,
                    "action": action,
                    "peaks_mz": peaks,
                    "peaks_intensity": [1.0, 0.2, 0.1, 0.05],
                    "source": "synthetic_control",
                    "reliability": 1.0,
                    "n_donors": 1,
                    "mean_similarity": 1.0,
                }
                for cid, peaks in (
                    ("A-SYNTHETIC", [50.0, 90.0, 110.0, 130.0]),
                    ("B-SYNTHETIC", [70.0, 90.0, 110.0, 140.0]),
                )
                for action in ("CID20", "CID40", "EAD16")
            ]
        )
        references = ReferenceStore(candidates, templates)
        repository = CaseRepository(
            pd.DataFrame(
                [
                    {
                        "case_id": "synthetic",
                        "precursor_mz": 200.0,
                        "candidate_ids": ["A-SYNTHETIC", "B-SYNTHETIC"],
                        "available_actions": ["CID40", "EAD16"],
                        "split": "dev",
                    }
                ]
            ),
            references,
        )
        payload = {
            "synthetic": {
                "initial": {
                    "action": "CID20",
                    "fragmentation": "CID",
                    "energy_ev": 20,
                    "accession": "SYNTH-INITIAL",
                    "peaks_mz": [50.0, 70.0, 90.0, 110.0],
                    "peaks_intensity": [1.0, 0.8, 0.2, 0.1],
                },
                "hidden": {
                    action: {
                        "action": action,
                        "fragmentation": fragmentation,
                        "energy_ev": energy,
                        "accession": f"SEALED-{action}",
                        "peaks_mz": [70.0, 90.0, 110.0, 173.123456],
                        "peaks_intensity": [1.0, 0.2, 0.1, 0.05],
                    }
                    for action, fragmentation, energy in (
                        ("CID40", "CID", 40),
                        ("EAD16", "EAD", 16),
                    )
                },
            }
        }
        oracle = OracleStore(payload, log_path=tmp_path / "access.jsonl")
        return InvestigationSession(
            "synthetic",
            repository,
            VirtualInstrument(oracle),
            CandidateScorer(),
            SeparationPlanner(),
            action_log=ActionLog(tmp_path / "actions.jsonl"),
        )

    return make


def scientific_state(session):
    state = session.evidence_state()
    return {
        key: value
        for key, value in state.items()
        if key not in {"active_peak_exclusions", "intervention_history", "premeasurement_commit", "experimental_challenge_result"}
    }


def test_positive_control_and_exact_undo(session_factory, tmp_path):
    session = session_factory()
    before = scientific_state(session)
    oracle_log = (tmp_path / "access.jsonl").read_bytes()
    original = session.observation("CID20")
    original_hash = spectrum_sha256(original)
    event = session.exclude_observed_peak("CID20", 0, "synthetic distinguishing peak")
    edited = scientific_state(session)
    assert before["ranking"]["candidates"][0]["candidate_id"] == "A-SYNTHETIC"
    assert edited["ranking"]["candidates"][0]["candidate_id"] == "B-SYNTHETIC"
    old_scores = {r["candidate_id"]: r["weight"] for r in before["ranking"]["candidates"]}
    new_scores = {r["candidate_id"]: r["weight"] for r in edited["ranking"]["candidates"]}
    assert new_scores["A-SYNTHETIC"] < old_scores["A-SYNTHETIC"]
    assert new_scores["B-SYNTHETIC"] > old_scores["B-SYNTHETIC"]
    assert before["plan"]["recommended"]["key"] != edited["plan"]["recommended"]["key"]
    assert edited["qc"]["initial_peaks"] == 3
    assert event["original_spectrum_sha256"] == original_hash
    assert spectrum_sha256(session.observation("CID20")) == original_hash
    # Callers cannot mutate the preserved original through a returned object.
    original.mz[0] = 9999
    assert spectrum_sha256(session.observation("CID20")) == original_hash
    session.undo_intervention(event["intervention_id"], "restore original evidence")
    assert scientific_state(session) == before
    assert (tmp_path / "access.jsonl").read_bytes() == oracle_log
    assert [e["kind"] for e in session.evidence_state()["intervention_history"]] == [
        "exclude_observed_peak",
        "undo_peak_exclusion",
    ]


def test_replay_preserves_acquired_evidence_and_budget(session_factory, tmp_path):
    edited, reference = session_factory(), session_factory()
    event = edited.exclude_observed_peak("CID20", 0, "synthetic sensitivity")
    edited.measure("CID40")
    reference.measure("CID40")
    log_before_undo = (tmp_path / "access.jsonl").read_bytes()
    edited.undo_intervention(event["intervention_id"], "restore with CID40 retained")
    assert scientific_state(edited) == scientific_state(reference)
    assert edited.observed_actions == ["CID20", "CID40"]
    assert edited.remaining_budget == 0
    assert (tmp_path / "access.jsonl").read_bytes() == log_before_undo
    # Editing the optional observation also replays both acquired observations.
    event2 = edited.exclude_observed_peak("CID40", 0, "optional spectrum sensitivity")
    assert scientific_state(edited) != scientific_state(reference)
    edited.undo_intervention(event2["intervention_id"], "restore optional observation")
    assert scientific_state(edited) == scientific_state(reference)


@pytest.mark.parametrize(
    "action,index,reason",
    [
        ("EAD16", 0, "unobserved"),
        ("CID40", 0, "unobserved"),
        ("CID20", -1, "bad index"),
        ("CID20", 4, "bad index"),
        ("CID20", True, "bad type"),
        ("CID20", 0.0, "bad type"),
        ("CID20", 0, "   "),
        ("CID20", 0, None),
        ("CID20", 0, "x" * 501),
    ],
)
def test_invalid_edits_leave_state_unchanged(session_factory, action, index, reason):
    session = session_factory()
    before = session.evidence_state()
    with pytest.raises(InterventionError):
        session.exclude_observed_peak(action, index, reason)
    assert session.evidence_state() == before


def test_original_indices_multiple_masks_and_sparse_qc(session_factory):
    session = session_factory()
    first = session.exclude_observed_peak("CID20", 0, "first")
    before_duplicate = session.evidence_state()
    with pytest.raises(InterventionError, match="active exclusion"):
        session.exclude_observed_peak("CID20", 0, "duplicate")
    assert session.evidence_state() == before_duplicate
    second = session.exclude_observed_peak("CID20", 1, "second original index")
    assert session.evidence_state()["decision_if_stopped"] == "INSUFFICIENT_DATA"
    assert session.qc()["initial_peaks"] == 2
    session.undo_intervention(first["intervention_id"], "non-LIFO undo")
    np.testing.assert_array_equal(session._effective_observation("CID20").mz, [50, 90, 110])
    assert session.qc()["passed"]
    with pytest.raises(InterventionError, match="already undone"):
        session.undo_intervention(first["intervention_id"], "duplicate undo")
    session.undo_intervention(second["intervention_id"], "restore all")
    assert session.qc()["initial_peaks"] == 4


def test_empty_initial_observation_abstains_and_is_reversible(session_factory):
    session = session_factory()
    before = scientific_state(session)
    events = [session.exclude_observed_peak("CID20", i, "stress control") for i in range(4)]
    assert session.evidence_state()["decision_if_stopped"] == "INSUFFICIENT_DATA"
    for event in events:
        session.undo_intervention(event["intervention_id"], "restore")
    assert scientific_state(session) == before


def test_failed_replay_rolls_back_mask_and_state(session_factory, monkeypatch):
    session = session_factory()
    before = session.evidence_state()
    original_rank = session.scorer.initial_rank

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic scoring failure")

    monkeypatch.setattr(session.scorer, "initial_rank", fail)
    with pytest.raises(RuntimeError, match="scoring failure"):
        session.exclude_observed_peak("CID20", 0, "rollback control")
    monkeypatch.setattr(session.scorer, "initial_rank", original_rank)
    assert session.evidence_state() == before
    event = session.exclude_observed_peak("CID20", 0, "undo rollback control")
    before_undo = session.evidence_state()
    monkeypatch.setattr(session.scorer, "initial_rank", fail)
    with pytest.raises(RuntimeError, match="scoring failure"):
        session.undo_intervention(event["intervention_id"], "rollback control")
    monkeypatch.setattr(session.scorer, "initial_rank", original_rank)
    assert session.evidence_state() == before_undo


def test_exports_audit_and_stop_guards(session_factory):
    session = session_factory()
    before = deepcopy(session.evidence_state())
    event = session.exclude_observed_peak("CID20", 0, "scientist sensitivity check")
    assert session.investigation().provenance["observed_accessions"] == {}
    assert before["active_peak_exclusions"] == []
    with pytest.raises(InterventionError, match="unknown"):
        session.undo_intervention("missing", "invalid undo")
    session.stop()
    report = session.investigation().model_dump()
    assert report["active_peak_exclusions"][0]["intervention_id"] == event["intervention_id"]
    markdown = session.export_markdown()
    assert event["original_spectrum_sha256"] in markdown
    assert "scientist sensitivity check" in markdown
    assert "SEALED-CID40" not in markdown and "SEALED-EAD16" not in markdown
    stopped = session.evidence_state()
    with pytest.raises(InterventionError, match="stopped"):
        session.exclude_observed_peak("CID20", 1, "late edit")
    with pytest.raises(InterventionError, match="stopped"):
        session.undo_intervention(event["intervention_id"], "late undo")
    assert session.evidence_state() == stopped

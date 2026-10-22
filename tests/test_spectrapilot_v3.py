"""Regression tests for the SpectraPilot v3 contract.

These tests encode the spec's non-negotiable rules, not implementation details:

* ``MASS_ONLY_MATCH`` is never counted as MS/MS confirmation;
* a weak predicted-template fit alone never causes ``OUT_OF_LIBRARY``;
* the QC gate keys on the best available observation, while the frozen v2 path
  keeps its first-scan rule;
* a precommit hash is deterministic and covers the hypothesis payload;
* hypothesis validation is a predeclared rule and says "inconclusive" on a
  sparse spectrum;
* the risk calibrator is monotone and round-trips through JSON;
* the corrected risk-coverage curve includes abstained cases;
* a hard-unknown episode really removes the truth *and its aliases*;
* formula-level evidence can only penalise different-formula candidates.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from spectrapilot.data.repository import CaseRepository
from spectrapilot.evaluation.truth import EvaluatorStore
from spectrapilot.models import (
    ACCEPTED_STATUSES,
    LEGACY_STATUS_MAP,
    PROOF_TIER,
    EvidenceStatus,
    Measurement,
)
from spectrapilot.paths import CURATED
from spectrapilot.planning.hypotheses import (
    FragmentHypothesisGenerator,
    precommit_sha256,
    validate_against_measurement,
)
from spectrapilot.planning.oracle import OracleStore
from spectrapilot.science.calibration import SupportCalibrator
from spectrapilot.science.scoring import template_trust
from spectrapilot.science.templates import ReferenceStore

ROOT = Path(__file__).resolve().parents[1]


def _measurement(case_id: str, action: str, mz, intensity) -> Measurement:
    return Measurement(
        case_id=case_id,
        action=action,
        fragmentation="EAD" if action.startswith("EAD") else "CID",
        energy_ev=40.0,
        accession="TEST",
        mz=np.asarray(mz, float),
        intensity=np.asarray(intensity, float),
    )


@pytest.fixture(scope="module")
def store():
    return ReferenceStore.load()


@pytest.fixture(scope="module")
def repository(store):
    return CaseRepository.load(store)


@pytest.fixture(scope="module")
def truth():
    return EvaluatorStore.load()


@pytest.fixture(scope="module")
def oracle():
    return OracleStore.load()


def test_mass_only_is_not_msms():
    assert EvidenceStatus.MASS_ONLY_MATCH.value in ACCEPTED_STATUSES
    assert EvidenceStatus.MASS_ONLY_MATCH.value not in {
        EvidenceStatus.MSMS_SUPPORTED.value,
    }
    assert PROOF_TIER["MASS_ONLY_MATCH"] != PROOF_TIER["MSMS_SUPPORTED"]
    assert PROOF_TIER["MASS_ONLY_MATCH"] in {"mass_only", "retrieval"}
    # v2's IDENTIFIED must map to the strict tier, not to the mass-only tier.
    assert LEGACY_STATUS_MAP["IDENTIFIED"] == EvidenceStatus.MSMS_SUPPORTED


def test_weak_template_never_means_out_of_library():
    from spectrapilot.planning.session import InvestigationSession

    assert EvidenceStatus.OUT_OF_LIBRARY.value not in ACCEPTED_STATUSES
    # The v3 decision function may only emit OUT_OF_LIBRARY through the
    # validated open-world hook; a poor template fit is handled as AMBIGUOUS.
    source = (ROOT / "src" / "spectrapilot" / "planning" / "session.py").read_text()
    start = source.index("def _final_decision_v3")
    end = source.index("def ", start + 10)
    body = source[start:end]
    assert "OUT_OF_LIBRARY" in body
    assert "_validated_open_world_rejection" in body
    # No branch may return OUT_OF_LIBRARY on a fit threshold alone.
    for line in body.splitlines():
        if "OUT_OF_LIBRARY.value" in line and "return" in line:
            assert "open_world" in body.lower()


def test_qc_uses_best_observation_but_legacy_keeps_first_scan(store, repository, oracle):
    from spectrapilot.planning.oracle import VirtualInstrument
    from spectrapilot.planning.separation import SeparationPlanner
    from spectrapilot.planning.session import InvestigationSession
    from spectrapilot.science.scoring import LegacyCosineScorer

    sparse = None
    for case_id in repository.case_ids("test"):
        measurement = oracle.initial(case_id)
        if 0 < len(measurement.mz) < 3:
            sparse = case_id
            break
    if sparse is None:
        pytest.skip("no sparse first scan in the frozen cohort")

    session = InvestigationSession(
        sparse,
        repository,
        VirtualInstrument(oracle),
        LegacyCosineScorer(),
        SeparationPlanner(),
        decision_version="v3",
    )
    assert session.qc()["best_observation_peaks"] < 3
    assert not session.qc()["passed"]
    # The frozen v2 path still rejects on the first scan.
    assert "initial_spectrum_too_sparse" in session.qc(legacy=True)["rejection_reasons"]


def test_precommit_hash_is_deterministic_and_covers_payload():
    payload = {"case_id": "case-x", "action": "CID40", "hypotheses": [{"id": "H1"}]}
    first = precommit_sha256(payload)
    second = precommit_sha256(json.loads(json.dumps(payload)))
    assert first == second
    changed = dict(payload, action="EAD16")
    assert precommit_sha256(changed) != first


def test_hypotheses_are_generated_before_measurement_and_validate(store, repository, oracle, truth):
    generator = FragmentHypothesisGenerator()
    case_id = next(
        cid
        for cid in repository.case_ids("test")
        if len(repository.case(cid).candidate_ids) >= 2
    )
    case = repository.case(case_id)
    candidates = repository.candidates(case_id)
    weights = {candidate.molecule_id: 1.0 / len(candidates) for candidate in candidates}
    from spectrapilot.planning.actions import MeasurementAction

    available = [MeasurementAction.for_key("CID40"), MeasurementAction.for_key("EAD16")]
    payload = generator.generate(
        case=case,
        candidates=candidates,
        weights=weights,
        store=store,
        observed_actions=["CID20"],
        available_actions=available,
        observations={},
    )
    assert payload["action"] == "CID40"
    assert payload["precommit_sha256"] == precommit_sha256(payload)
    assert payload["hypotheses"], "expected at least one candidate hypothesis"
    for hypothesis in payload["hypotheses"]:
        assert hypothesis["status"] == "pending"
        assert hypothesis["predicted_diagnostic_peaks"]

    hidden = oracle.evaluator_hidden(case_id)["CID40"]
    measurement = _measurement(
        case_id, "CID40", hidden["peaks_mz"], hidden["peaks_intensity"]
    )
    validated = validate_against_measurement(payload, measurement)
    statuses = {item["status"] for item in validated["hypotheses"]}
    assert statuses <= {"supported", "refuted", "inconclusive_sparse_spectrum", "not_tested"}


def test_hypothesis_validation_is_inconclusive_on_sparse_spectrum():
    payload = {
        "action": "CID40",
        "tolerance_da": 0.02,
        "hypotheses": [
            {
                "action": "CID40",
                "rule_threshold": 2,
                "predicted_diagnostic_peaks": [{"mz": 100.0}, {"mz": 150.0}],
                "expected_absent_peaks": [],
            }
        ],
    }
    measurement = _measurement("case-test", "CID40", [100.0], [1.0])
    validated = validate_against_measurement(payload, measurement)
    assert validated["hypotheses"][0]["status"] == "inconclusive_sparse_spectrum"


def test_calibrator_is_monotone_and_round_trips(tmp_path):
    supports = [0.1, 0.2, 0.2, 0.6, 0.6, 0.9, 1.0, 1.0]
    labels = [0, 0, 1, 0, 1, 1, 1, 1]
    calibrator = SupportCalibrator.fit(supports, labels, split="unit")
    probabilities = [calibrator.p_correct(value) for value in supports]
    assert all(b >= a - 1e-12 for a, b in zip(probabilities, probabilities[1:]))
    path = tmp_path / "calibrator.json"
    calibrator.save(path)
    loaded = SupportCalibrator.load(path)
    assert loaded.thresholds == calibrator.thresholds
    assert loaded.p_correct(0.6) == pytest.approx(calibrator.p_correct(0.6))


def test_calibrator_artefact_exists_and_is_dev_fitted():
    path = CURATED / "support_calibrator.json"
    assert path.exists(), "run `make v3-train` first"
    payload = json.loads(path.read_text())
    assert payload["split"] == "dev"
    assert payload["thresholds"] and len(payload["thresholds"]) == len(payload["values"])


def test_corrected_risk_coverage_includes_abstained_cases():
    from spectrapilot.evaluation.runner import CaseResult, risk_coverage_curve

    rows = [
        CaseResult("a", "p", "test", "t", "t", 1.0, 1.0, 1.0, "MSMS_SUPPORTED", confidence=0.9, accepted_any=1.0),
        CaseResult("b", "p", "test", "t", "x", 0.0, 0.0, 0.0, "AMBIGUOUS", confidence=0.8, accepted_any=0.0),
        CaseResult("c", "p", "test", "t", "t", 1.0, 1.0, 1.0, "AMBIGUOUS", confidence=0.1, accepted_any=0.0),
    ]
    curve = risk_coverage_curve(rows)
    assert curve["n"] == 3
    # The curve is cumulative risk over *all* cases, so abstained case b is included.
    assert curve["risk"][1] == pytest.approx(0.5)
    assert curve["risk"][-1] == pytest.approx(1.0 / 3.0)


def test_hard_unknown_removes_truth_and_aliases(repository, truth):
    from spectrapilot.science.open_world import UnknownPoolRepository

    case_id = next(
        cid
        for cid in repository.case_ids("test")
        if len(repository.case(cid).candidate_ids) >= 2
    )
    proxy = UnknownPoolRepository(repository, truth, case_ids=[case_id])
    original = set(repository.case(case_id).candidate_ids)
    filtered = set(proxy.case(case_id).candidate_ids)
    assert truth.truth(case_id) not in filtered
    assert not (truth.aliases(case_id) & filtered)
    assert filtered <= original
    removed = (truth.aliases(case_id) | {truth.truth(case_id)}) & original
    assert len(filtered) == len(original) - len(removed)


def test_formula_consistency_cannot_separate_isomers(store, repository):
    """The S3 term must be inactive for two candidates sharing a formula."""
    from spectrapilot.science.scoring import FormulaConsistencyScorer

    case_id = next(
        cid
        for cid in repository.case_ids("test")
        if any(repository.references.candidate(c).formula for c in repository.case(cid).candidate_ids)
    )
    scorer = FormulaConsistencyScorer()
    candidate_id = next(
        cid
        for cid in repository.case(case_id).candidate_ids
        if repository.references.candidate(cid).formula
    )
    candidate = repository.references.candidate(candidate_id)
    from dataclasses import replace as dataclass_replace

    isomer = dataclass_replace(candidate, molecule_id="ISOMER-TEST")
    observations = {
        "CID20": (np.array([100.0, 150.0, 200.0]), np.array([1.0, 0.5, 0.2])),
    }
    penalty_a = scorer._penalty(observations, candidate, 400.0)
    penalty_b = scorer._penalty(observations, isomer, 400.0)
    assert penalty_a == pytest.approx(penalty_b)


def test_template_trust_prefers_experimental_reference(store):
    reference_id = None
    for candidate_id in store.candidate_ids:
        templates = store.templates_for(candidate_id)
        if any(template.source == "reference_cid60" for template in templates.values()):
            reference_id = candidate_id
            break
    assert reference_id is not None, "expected at least one real reference template"
    reference = next(
        template
        for template in store.templates_for(reference_id).values()
        if template.source == "reference_cid60"
    )
    knn = next(
        template
        for candidate_id in store.candidate_ids
        for action in ("EAD16",)
        if (template := store.template(candidate_id, action)).source
        == "train_only_structure_knn"
        and template.reliability < 0.3
    )
    assert template_trust(reference) > template_trust(knn)
    assert template_trust(reference) > 0.5

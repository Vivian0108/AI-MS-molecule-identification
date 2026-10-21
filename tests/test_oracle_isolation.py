"""Anti-leakage tests for the sealed virtual instrument."""

from __future__ import annotations

import json

import numpy as np
import pytest

from unknownid.core.models import PeakList, PrivateOracleCase, PublicCase
from unknownid.core.spectra import ProcessedSpectrum
from unknownid.planner.acquisition import AcquisitionPlanner, PlannerConfig
from unknownid.simulator.oracle import (
    OracleAccessError,
    OracleStore,
    VirtualInstrument,
)


@pytest.fixture
def sealed_oracle(tmp_path) -> tuple[OracleStore, dict[str, PrivateOracleCase]]:
    case = PrivateOracleCase(
        case_id="case-synthetic",
        true_molecule_id="AAAA-BBBB-CCCC-D",
        precursor_mz=200.0,
        split="test",
        hidden_accessions={20: "MSBNK-SYNTH-20", 30: "MSBNK-SYNTH-30", 40: "MSBNK-SYNTH-40"},
        hidden_spectra={
            20: PeakList(mz=[50.0, 100.0, 150.0], intensity=[1.0, 0.8, 0.4]),
            30: PeakList(mz=[50.0, 100.0, 155.0], intensity=[1.0, 0.7, 0.6]),
            40: PeakList(mz=[50.0, 110.0, 170.0], intensity=[1.0, 0.9, 0.5]),
        },
        reference_accessions={10: "MSBNK-SYNTH-10", 50: "MSBNK-SYNTH-50"},
    )
    payload = {case.case_id: case}
    store = OracleStore(payload, log_path=tmp_path / "access.jsonl")
    return store, payload


def test_start_reveals_only_the_20ev_observation(sealed_oracle) -> None:
    store, _ = sealed_oracle
    instrument = VirtualInstrument(store, allowed_energies=(30, 40), default_budget=1)

    measurement = instrument.start("case-synthetic")

    assert measurement.energy == 20
    assert measurement.accession == "MSBNK-SYNTH-20"
    assert measurement.spectrum.mz.tolist() == [50.0, 100.0, 150.0]
    assert instrument.observed_energies("case-synthetic") == [20]
    assert instrument.remaining_budget("case-synthetic") == 1

    # The instrument has no public path to hidden spectra or evaluator truth.
    with pytest.raises(PermissionError):
        _ = instrument.oracle
    assert not hasattr(instrument, "evaluator_truth")
    assert not hasattr(instrument, "hidden_spectra")
    assert not hasattr(instrument, "truth")


def test_measure_reveals_one_energy_and_enforces_budget(sealed_oracle) -> None:
    store, _ = sealed_oracle
    instrument = VirtualInstrument(store, allowed_energies=(30, 40), default_budget=1)
    instrument.start("case-synthetic")

    measurement = instrument.measure("case-synthetic", 30)
    assert measurement.energy == 30
    assert measurement.accession == "MSBNK-SYNTH-30"
    assert instrument.remaining_budget("case-synthetic") == 0

    with pytest.raises(OracleAccessError, match="already been measured"):
        instrument.measure("case-synthetic", 30)
    with pytest.raises(OracleAccessError, match="budget exhausted"):
        instrument.measure("case-synthetic", 40)


def test_only_30_and_40_are_valid_actions(sealed_oracle) -> None:
    store, _ = sealed_oracle
    instrument = VirtualInstrument(store, allowed_energies=(30, 40), default_budget=2)
    instrument.start("case-synthetic")

    with pytest.raises(OracleAccessError, match="not an allowed action"):
        instrument.measure("case-synthetic", 20)
    with pytest.raises(OracleAccessError, match="not an allowed action"):
        instrument.measure("case-synthetic", 50)
    with pytest.raises(OracleAccessError, match="already started"):
        instrument.start("case-synthetic")


def test_budget_two_permits_both_hidden_energies(sealed_oracle) -> None:
    store, _ = sealed_oracle
    instrument = VirtualInstrument(store, allowed_energies=(30, 40), default_budget=2)
    instrument.start("case-synthetic")

    instrument.measure("case-synthetic", 30)
    instrument.measure("case-synthetic", 40)
    assert instrument.observed_energies("case-synthetic") == [20, 30, 40]
    assert instrument.remaining_budget("case-synthetic") == 0


def test_access_log_records_every_reveal(sealed_oracle, tmp_path) -> None:
    store, _ = sealed_oracle
    instrument = VirtualInstrument(store, allowed_energies=(30, 40), default_budget=1)
    instrument.start("case-synthetic")
    instrument.measure("case-synthetic", 30)

    lines = [
        json.loads(line)
        for line in (tmp_path / "access.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [entry["actor"] for entry in lines] == ["case_start", "explicit_measure"]
    assert [entry["energy_ev"] for entry in lines] == [20, 30]


def test_public_case_contract_has_no_truth_fields() -> None:
    fields = set(PublicCase.model_fields)
    assert not {field for field in fields if "hidden" in field or "truth" in field}
    assert "observed_20ev_spectrum" in fields
    assert "candidate_ids" in fields

    private_fields = set(PrivateOracleCase.model_fields)
    assert {"true_molecule_id", "hidden_spectra", "hidden_accessions"} <= private_fields


def test_plan_is_invariant_to_hidden_measurements(sealed_oracle) -> None:
    """Spec 6 anti-leakage test: randomise hidden 30/40 peaks *after* planning."""
    store, _ = sealed_oracle
    instrument = VirtualInstrument(store, allowed_energies=(30, 40), default_budget=1)
    instrument.start("case-synthetic")

    templates = {
        "AAAA-BBBB-CCCC-D": {
            20: ProcessedSpectrum(np.array([50.0, 100.0]), np.array([1.0, 0.8])),
            30: ProcessedSpectrum(np.array([50.0, 100.0]), np.array([1.0, 0.7])),
            40: ProcessedSpectrum(np.array([50.0, 120.0]), np.array([1.0, 0.6])),
        },
        "EEEE-FFFF-GGGG-H": {
            20: ProcessedSpectrum(np.array([50.0, 100.0]), np.array([0.9, 1.0])),
            30: ProcessedSpectrum(np.array([50.0, 100.0]), np.array([1.0, 0.7])),
            40: ProcessedSpectrum(np.array([60.0, 140.0]), np.array([1.0, 0.9])),
        },
    }
    planner = AcquisitionPlanner(
        PlannerConfig(allowed_energies=(30, 40), monte_carlo_samples=20, seed=5),
        method="disagreement_heuristic",
    )

    def plan():
        return planner.plan(
            "case-synthetic",
            weights={"AAAA-BBBB-CCCC-D": 0.5, "EEEE-FFFF-GGGG-H": 0.5},
            templates=templates,
            precursors={"AAAA-BBBB-CCCC-D": 200.0, "EEEE-FFFF-GGGG-H": 200.0},
            observed_energies=[20],
            remaining_budget=1,
        )

    before = plan()
    truth = store.evaluator_truth("case-synthetic")
    truth.hidden_spectra[30] = PeakList(mz=[13.37, 77.77, 199.99], intensity=[0.1, 0.2, 0.3])
    truth.hidden_spectra[40] = PeakList(mz=[11.11, 88.88, 177.77], intensity=[0.3, 0.2, 0.1])
    after = plan()

    assert before.model_dump() == after.model_dump()
    assert instrument.observed_energies("case-synthetic") == [20]

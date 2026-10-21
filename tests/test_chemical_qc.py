"""Chemical quality control: RDKit identity, formula and precursor checks."""

from __future__ import annotations

import pytest

from unknownid.config import load_config
from unknownid.data.curate import chemical_qc
from unknownid.io.massbank_parser import parse_record_text
from tests.conftest import massbank_text


@pytest.fixture(scope="module")
def selection_config():
    return load_config("selection")


def test_valid_standard_passes_all_chemical_checks(selection_config) -> None:
    record = parse_record_text(massbank_text())
    qc = chemical_qc(record, ppm_tolerance=10.0)

    assert qc.ok, qc.reasons
    assert qc.formula == "C2H6O"
    assert qc.inchikey == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert qc.exact_mass == pytest.approx(46.0419, abs=1e-3)
    assert abs(qc.ppm_error) < 10.0
    assert qc.scaffold == ""


def test_wrong_precursor_is_rejected_with_reason() -> None:
    record = parse_record_text(massbank_text(precursor_mz=60.0))
    qc = chemical_qc(record, ppm_tolerance=10.0)

    assert not qc.ok
    assert "precursor_mass_inconsistent" in qc.reasons


def test_invalid_smiles_is_rejected() -> None:
    record = parse_record_text(massbank_text(smiles="this-is-not-a-smiles"))
    qc = chemical_qc(record)

    assert not qc.ok
    assert "rdkit_invalid_smiles" in qc.reasons


def test_multi_component_smiles_is_rejected() -> None:
    record = parse_record_text(massbank_text(smiles="CCO.CCO"))
    qc = chemical_qc(record)

    assert not qc.ok
    assert "multi_component_smiles" in qc.reasons


def test_inchikey_mismatch_is_not_silently_repaired() -> None:
    record = parse_record_text(
        massbank_text(inchikey="XLYOFNOQVPJJNP-UHFFFAOYSA-N")
    )
    qc = chemical_qc(record)

    assert not qc.ok
    assert "inchikey_mismatch" in qc.reasons


def test_missing_metadata_is_reported() -> None:
    text = massbank_text().replace(
        "CH$LINK: INCHIKEY LFQSCWFLJHTTHZ-UHFFFAOYSA-N\n", ""
    )
    record = parse_record_text(text)
    qc = chemical_qc(record)

    assert not qc.ok
    assert "missing_inchikey" in qc.reasons

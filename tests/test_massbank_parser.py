"""Parser regression tests on a synthetic MassBank record."""

from __future__ import annotations

import pytest

from unknownid.io.massbank_parser import parse_record_text
from tests.conftest import massbank_text


def test_parses_identity_metadata_and_peaks(ethanol_record_text: str) -> None:
    record = parse_record_text(ethanol_record_text)

    assert record.accession == "MSBNK-TEST-0001"
    assert record.names == ["Ethanol"]
    assert record.smiles == "CCO"
    assert record.formula == "C2H6O"
    assert record.inchikey == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert record.precursor_mz == pytest.approx(47.0491)
    assert record.instrument == "Bruker maXis Impact"
    assert record.instrument_type == "LC-ESI-QTOF"
    assert record.ms_type.upper() == "MS2"
    assert record.ion_mode.upper() == "POSITIVE"
    assert record.fragmentation_mode.upper() == "CID"
    assert record.is_standard_compound
    assert record.license_is_redistributable
    assert len(record.peaks) == 3
    assert record.peaks[1].mz == pytest.approx(45.0340)
    assert record.num_peak_tagged == 3


@pytest.mark.parametrize(
    ("raw", "value", "unit", "fixed"),
    [
        ("10 eV", 10.0, "eV", True),
        ("40 eV", 40.0, "eV", True),
        ("35 eV", 35.0, "eV", True),
        ("20 eV ramped", None, "ramped", False),
        ("50 % NCE", None, "NCE", False),
        ("", None, "", False),
    ],
)
def test_collision_energy_parsing_is_conservative(
    raw: str, value: float | None, unit: str, fixed: bool
) -> None:
    record = parse_record_text(massbank_text(collision_energy=raw))
    if value is None:
        assert record.collision_energy_value is None
    else:
        assert record.collision_energy_value == pytest.approx(value)
    assert record.collision_energy_unit == unit
    assert record.collision_energy_is_fixed_ev is fixed


def test_peak_count_mismatch_is_preserved_not_repaired() -> None:
    record = parse_record_text(massbank_text(num_peak=9))
    assert record.num_peak_tagged == 9
    assert len(record.peaks) == 3


def test_non_redistributable_license_is_detected() -> None:
    record = parse_record_text(massbank_text(license="All Rights Reserved"))
    assert not record.license_is_redistributable


def test_missing_confidence_comment_is_not_a_standard() -> None:
    record = parse_record_text(massbank_text(standard=False))
    assert not record.is_standard_compound


def test_sha256_is_computed_from_content() -> None:
    text = massbank_text()
    first = parse_record_text(text)
    second = parse_record_text(text)
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64

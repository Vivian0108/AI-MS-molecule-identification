"""Synthetic fixtures for the test-suite.

These fixtures are deliberately small and artificial.  They verify code paths
and leakage boundaries; they are **not** scientific evidence and are never
mixed with the MassBank evaluation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from unknownid.core.spectra import ProcessedSpectrum


def massbank_text(
    *,
    accession: str = "MSBNK-TEST-0001",
    name: str = "Ethanol",
    smiles: str = "CCO",
    formula: str = "C2H6O",
    exact_mass: float = 46.0418648,
    inchikey: str = "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    precursor_mz: float = 47.0491413,
    collision_energy: str = "10 eV",
    license: str = "CC BY",
    standard: bool = True,
    peaks: tuple[tuple[float, float], ...] = (
        (31.0184, 120.0),
        (45.0340, 999.0),
        (47.0491, 80.0),
    ),
    num_peak: int | None = None,
) -> str:
    peak_lines = "\n".join(
        f"  {mz:.4f} {intensity:.1f} {intensity / max(p[1] for p in peaks) * 999:.1f}"
        for mz, intensity in peaks
    )
    declared = len(peaks) if num_peak is None else num_peak
    comment = "COMMENT: CONFIDENCE standard compound" if standard else "COMMENT: CONFIDENCE tentative"
    return f"""ACCESSION: {accession}
LICENSE: {license}
CH$NAME: {name}
CH$SMILES: {smiles}
CH$FORMULA: {formula}
CH$EXACT_MASS: {exact_mass}
CH$LINK: INCHIKEY {inchikey}
AC$INSTRUMENT: Bruker maXis Impact
AC$INSTRUMENT_TYPE: LC-ESI-QTOF
AC$MASS_SPECTROMETRY: MS_TYPE MS2
AC$MASS_SPECTROMETRY: ION_MODE POSITIVE
AC$MASS_SPECTROMETRY: IONIZATION ESI
AC$MASS_SPECTROMETRY: FRAGMENTATION_MODE CID
AC$MASS_SPECTROMETRY: COLLISION_ENERGY {collision_energy}
MS$FOCUSED_ION: PRECURSOR_TYPE [M+H]+
MS$FOCUSED_ION: PRECURSOR_M/Z {precursor_mz:.4f}
MS$FOCUSED_ION: BASE_PEAK 45.0340
{comment}
PK$NUM_PEAK: {declared}
PK$PEAK:
{peak_lines}
//  
"""


@pytest.fixture
def ethanol_record_text() -> str:
    return massbank_text()


def _row(
    molecule_id: str,
    name: str,
    energy: int,
    mz: list[float],
    intensity: list[float],
    *,
    prefix: str,
    precursor_mz: float,
) -> dict:
    return {
        "accession": f"MSBNK-SYNTH-{prefix}{energy}",
        "molecule_id": molecule_id,
        "name": name,
        "smiles": "CCO",
        "formula": "C2H6O",
        "exact_mass": 46.0418648,
        "precursor_mz": precursor_mz,
        "adduct": "[M+H]+",
        "scaffold": "c1ccccc1",
        "collision_energy_ev": energy,
        "mz": mz,
        "intensity": intensity,
    }


@pytest.fixture
def synthetic_library() -> pd.DataFrame:
    rows = [
        _row(
            "AAAA-BBBB-CCCC-D",
            "Molecule A",
            10,
            [50.0, 100.0, 150.0],
            [1.0, 0.8, 0.4],
            prefix="A",
            precursor_mz=200.0,
        ),
        _row(
            "AAAA-BBBB-CCCC-D",
            "Molecule A",
            50,
            [50.0, 100.0, 170.0],
            [1.0, 0.5, 0.6],
            prefix="A",
            precursor_mz=200.0,
        ),
        _row(
            "EEEE-FFFF-GGGG-H",
            "Molecule B",
            10,
            [50.0, 100.0, 150.0],
            [0.9, 1.0, 0.3],
            prefix="B",
            precursor_mz=200.0,
        ),
        _row(
            "EEEE-FFFF-GGGG-H",
            "Molecule B",
            50,
            [50.0, 100.0, 160.0],
            [0.7, 1.0, 0.5],
            prefix="B",
            precursor_mz=200.0,
        ),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def spectrum_a_30() -> ProcessedSpectrum:
    return ProcessedSpectrum(np.array([50.0, 100.0, 150.0]), np.array([1.0, 0.7, 0.3]))


@pytest.fixture
def spectrum_b_30() -> ProcessedSpectrum:
    return ProcessedSpectrum(np.array([50.0, 100.0, 150.0]), np.array([0.9, 0.8, 0.4]))


@pytest.fixture
def spectrum_a_40() -> ProcessedSpectrum:
    return ProcessedSpectrum(np.array([50.0, 100.0, 170.0]), np.array([1.0, 0.5, 0.6]))


@pytest.fixture
def spectrum_b_40() -> ProcessedSpectrum:
    # Strongly separated from A at 40 eV, unlike the 30 eV pair.
    return ProcessedSpectrum(np.array([60.0, 120.0, 190.0]), np.array([1.0, 0.9, 0.8]))

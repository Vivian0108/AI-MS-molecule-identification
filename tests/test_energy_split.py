"""Energy boundary and molecular split tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from unknownid.core.retrieve import ReferenceStore
from unknownid.data.splits import assign_splits, assert_disjoint


def test_reference_store_loads_only_endpoint_energies(synthetic_library: pd.DataFrame) -> None:
    store = ReferenceStore(synthetic_library, reference_energies=(10, 50))
    store.assert_reference_only()

    assert len(store) == 2
    assert store.reference_spectrum("AAAA-BBBB-CCCC-D", 10).n_peaks == 3
    assert store.reference_spectrum("AAAA-BBBB-CCCC-D", 50).n_peaks == 3
    with pytest.raises(PermissionError):
        store.reference_spectrum("AAAA-BBBB-CCCC-D", 30)
    with pytest.raises(PermissionError):
        store.reference_spectrum("AAAA-BBBB-CCCC-D", 20)


def test_store_refuses_non_reference_energy_rows(synthetic_library: pd.DataFrame) -> None:
    contaminated = synthetic_library.copy()
    extra = contaminated.iloc[[0]].copy()
    extra["collision_energy_ev"] = 30
    extra["accession"] = "MSBNK-SYNTH-LEAK30"
    contaminated = pd.concat([contaminated, extra], ignore_index=True)

    with pytest.raises(ValueError, match="non-reference energy"):
        ReferenceStore(contaminated, reference_energies=(10, 50))


def test_templates_exist_at_mid_energies_and_are_interpolations(
    synthetic_library: pd.DataFrame,
) -> None:
    store = ReferenceStore(synthetic_library, reference_energies=(10, 50), template_method="linear")
    templates = store.templates("AAAA-BBBB-CCCC-D", (20, 30, 40))

    assert sorted(templates) == [20, 30, 40]
    for energy, spectrum in templates.items():
        assert spectrum.n_peaks >= 2, energy
        assert np.isclose(spectrum.intensity.max(), 1.0)

    # The 150 eV-only and 170 eV-only peaks fade in/out across the endpoints.
    # At 20 eV the 150 peak dominates; at 40 eV the 170 peak dominates.
    def intensity_at(spectrum, target: float) -> float:
        return float(spectrum.intensity[np.isclose(spectrum.mz, target)].max())

    assert intensity_at(templates[20], 150.0) > intensity_at(templates[20], 170.0)
    assert intensity_at(templates[40], 170.0) > intensity_at(templates[40], 150.0)
    assert intensity_at(templates[30], 150.0) > 0.0
    assert intensity_at(templates[30], 170.0) > 0.0

    candidate = store.candidate("AAAA-BBBB-CCCC-D")
    assert set(candidate.reference_accessions) == {10, 50}


def test_scaffold_groups_never_cross_splits() -> None:
    rows = []
    for group in range(5):
        for index in range(4):
            rows.append(
                {
                    "molecule_id": f"MOL-{group}-{index}",
                    "scaffold": f"scaffold-{group}",
                }
            )
    frame = pd.DataFrame(rows)

    result = assign_splits(frame, seed=7, train=0.6, dev=0.2, test=0.2)
    assert_disjoint(result)
    assert set(result.assignment) == set(frame["molecule_id"])
    assert sum(result.counts.values()) == len(frame)

    for group in range(5):
        splits = {
            result.assignment[f"MOL-{group}-{index}"] for index in range(4)
        }
        assert len(splits) == 1, f"scaffold {group} crossed splits: {splits}"


def test_split_ratios_must_sum_to_one() -> None:
    frame = pd.DataFrame({"molecule_id": ["A", "B"], "scaffold": ["x", "y"]})
    with pytest.raises(ValueError):
        assign_splits(frame, train=0.7, dev=0.2, test=0.2)

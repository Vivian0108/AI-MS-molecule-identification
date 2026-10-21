"""Reference-library retrieval.

Hard boundary: this module only ever loads the 10 and 50 eV reference spectra.
It has no parameter, path or attribute that can reach the oracle store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from unknownid.core.spectra import ProcessedSpectrum, preprocess_peaks
from unknownid.core.templates import build_all_templates


@dataclass(frozen=True)
class Candidate:
    molecule_id: str
    name: str
    smiles: str
    formula: str
    exact_mass: float
    precursor_mz: float
    adduct: str
    scaffold: str
    reference_accessions: dict[int, str] = field(default_factory=dict)

    def public_dict(self) -> dict:
        return {
            "candidate_id": self.molecule_id,
            "name": self.name,
            "smiles": self.smiles,
            "formula": self.formula,
            "exact_mass": self.exact_mass,
            "precursor_mz": self.precursor_mz,
            "adduct": self.adduct,
            "reference_accessions": {str(k): v for k, v in self.reference_accessions.items()},
        }


class ReferenceStore:
    """In-memory static library built exclusively from 10/50 eV records."""

    def __init__(
        self,
        library: pd.DataFrame,
        *,
        reference_energies: Sequence[int] = (10, 50),
        tolerance_da: float = 0.02,
        template_method: str = "linear",
        ppm_tolerance: float = 10.0,
    ) -> None:
        self.reference_energies = tuple(int(e) for e in reference_energies)
        self.tolerance_da = float(tolerance_da)
        self.template_method = template_method
        self.ppm_tolerance = float(ppm_tolerance)
        self._spectra: dict[tuple[str, int], ProcessedSpectrum] = {}
        self._candidates: dict[str, Candidate] = {}
        self._template_cache: dict[tuple[str, int], ProcessedSpectrum] = {}
        self._load(library)

    # -- construction ------------------------------------------------------
    def _load(self, library: pd.DataFrame) -> None:
        grouped: dict[str, list[pd.Series]] = {}
        for _, row in library.iterrows():
            energy = int(row["collision_energy_ev"])
            if energy not in self.reference_energies:
                raise ValueError(
                    f"ReferenceStore received a non-reference energy: {energy} eV. "
                    "The 20/30/40 eV observations must stay in the oracle store."
                )
            molecule_id = str(row["molecule_id"])
            mz = [float(x) for x in row["mz"]]
            intensity = [float(x) for x in row["intensity"]]
            spectrum = preprocess_peaks(mz, intensity, rel_floor=0.0)
            self._spectra[(molecule_id, energy)] = spectrum
            grouped.setdefault(molecule_id, []).append(row)

        for molecule_id, rows in grouped.items():
            by_energy = {int(r["collision_energy_ev"]): r for r in rows}
            if not all(e in by_energy for e in self.reference_energies):
                continue
            row = by_energy[self.reference_energies[0]]
            self._candidates[molecule_id] = Candidate(
                molecule_id=molecule_id,
                name=str(row.get("name", "")),
                smiles=str(row.get("smiles", "")),
                formula=str(row.get("formula", "")),
                exact_mass=float(row.get("exact_mass", np.nan)),
                precursor_mz=float(row.get("precursor_mz", np.nan)),
                adduct=str(row.get("adduct", "[M+H]+")),
                scaffold=str(row.get("scaffold", "")),
                reference_accessions={
                    int(e): str(by_energy[e]["accession"]) for e in self.reference_energies
                },
            )

    # -- retrieval ---------------------------------------------------------
    @property
    def candidate_ids(self) -> list[str]:
        return sorted(self._candidates)

    def __len__(self) -> int:
        return len(self._candidates)

    def candidate(self, molecule_id: str) -> Candidate:
        return self._candidates[molecule_id]

    def metadata(self, molecule_id: str) -> dict:
        return self._candidates[molecule_id].public_dict()

    def candidates_within_ppm(
        self, precursor_mz: float, *, ppm: float | None = None
    ) -> list[Candidate]:
        if not precursor_mz or precursor_mz <= 0:
            return []
        tolerance = self.ppm_tolerance if ppm is None else float(ppm)
        out = []
        for candidate in self._candidates.values():
            error_ppm = (
                abs(candidate.precursor_mz - precursor_mz) / precursor_mz * 1e6
            )
            if error_ppm <= tolerance:
                out.append(candidate)
        out.sort(key=lambda c: (abs(c.precursor_mz - precursor_mz), c.molecule_id))
        return out

    def precursor_ppm(self, molecule_id: str, precursor_mz: float) -> float:
        candidate = self._candidates[molecule_id]
        return (candidate.precursor_mz - precursor_mz) / precursor_mz * 1e6

    def reference_spectrum(self, molecule_id: str, energy: int) -> ProcessedSpectrum:
        if int(energy) not in self.reference_energies:
            raise PermissionError(
                f"{energy} eV is not a reference energy; only {self.reference_energies} are readable."
            )
        key = (molecule_id, int(energy))
        if key not in self._spectra:
            raise KeyError(f"No {energy} eV reference spectrum for {molecule_id}")
        return self._spectra[key]

    def template(self, molecule_id: str, energy: int) -> ProcessedSpectrum:
        """Energy-conditioned template interpolated from the two endpoints."""
        key = (molecule_id, int(energy))
        if key in self._template_cache:
            return self._template_cache[key]
        low, high = self.reference_energies
        templates = build_all_templates(
            self.reference_spectrum(molecule_id, low).mz,
            self.reference_spectrum(molecule_id, low).intensity,
            self.reference_spectrum(molecule_id, high).mz,
            self.reference_spectrum(molecule_id, high).intensity,
            energies=(energy,),
            method=self.template_method,
            tolerance=self.tolerance_da,
        )
        self._template_cache[key] = templates[int(energy)]
        return templates[int(energy)]

    def templates(
        self,
        molecule_id: str,
        energies: Iterable[int] = (20, 30, 40),
    ) -> dict[int, ProcessedSpectrum]:
        return {int(e): self.template(molecule_id, int(e)) for e in energies}

    def endpoint_agreement(self, molecule_id: str) -> float:
        from unknownid.core.spectra import cosine_greedy

        low, high = self.reference_energies
        a = self.reference_spectrum(molecule_id, low)
        b = self.reference_spectrum(molecule_id, high)
        return cosine_greedy(a.mz, a.intensity, b.mz, b.intensity, self.tolerance_da)[0]

    # -- guard -------------------------------------------------------------
    def assert_reference_only(self) -> None:
        forbidden = {20, 30, 40} - set(self.reference_energies)
        loaded = {energy for _, energy in self._spectra}
        leaked = loaded & forbidden
        if leaked:
            raise AssertionError(f"ReferenceStore contains oracle energies: {sorted(leaked)}")

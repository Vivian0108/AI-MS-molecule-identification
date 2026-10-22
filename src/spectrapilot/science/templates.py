"""Agent-facing structure and template store.

This object never reads the oracle directory.  Its template file contains only
train-only structure-kNN predictions plus explicitly allowed CID60 references.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from spectrapilot.models import Candidate, Template
from spectrapilot.paths import CURATED, REFERENCE


def _nominal_energy(action: str) -> float | None:
    """Nominal collision energy encoded in an action key ('CID40' -> 40.0)."""
    digits = "".join(char for char in str(action) if char.isdigit())
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


class ReferenceStore:
    def __init__(
        self,
        candidates: pd.DataFrame,
        templates: pd.DataFrame,
        *,
        ppm_tolerance: float = 10.0,
        reference_only_actions: Iterable[str] = ("CID20", "CID40", "EAD16", "CID60"),
    ) -> None:
        self.ppm_tolerance = float(ppm_tolerance)
        self.reference_only_actions = tuple(reference_only_actions)
        self._candidates: dict[str, Candidate] = {}
        self._masses: dict[str, float] = {}
        self._templates: dict[tuple[str, str], Template] = {}
        self._load_candidates(candidates)
        self._load_templates(templates)
        self.assert_reference_only()

    def _load_candidates(self, frame: pd.DataFrame) -> None:
        for _, row in frame.iterrows():
            cid = str(row["compound_full_inchikey"])
            self._candidates[cid] = Candidate(
                molecule_id=cid,
                name=str(row.get("name", "")),
                smiles=str(row.get("canonical_smiles", "")),
                formula=str(row.get("formula", "")),
                exact_mass=float(row.get("exact_mass", np.nan)),
                precursor_mz=float(row.get("precursor_mz", np.nan)),
                adduct=str(row.get("adduct", "[M+H]+")),
                scaffold=str(row.get("scaffold", "")),
                connectivity_key=str(row.get("connectivity_key", "")),
                source_collection=str(row.get("source_collections", "")),
            )
            self._masses[cid] = float(row.get("exact_mass", np.nan)) + 1.007276466621

    def _load_templates(self, frame: pd.DataFrame) -> None:
        for _, row in frame.iterrows():
            candidate_id = str(row["candidate_id"])
            action = str(row["action"])
            if action not in self.reference_only_actions:
                raise ValueError(f"ReferenceStore received disallowed action {action}")
            source = str(row["source"])
            # v3 provenance: a CID60 reference used as a CID40 template is an
            # explicit +20 eV surrogate, not a true conditional prediction.
            if source == "reference_cid60":
                expected_energy = 60.0
            else:
                expected_energy = _nominal_energy(action)
            self._templates[(candidate_id, action)] = Template(
                candidate_id=candidate_id,
                action=action,
                mz=np.asarray(row["peaks_mz"], float),
                intensity=np.asarray(row["peaks_intensity"], float),
                source=source,
                reliability=float(row["reliability"]),
                n_donors=int(row["n_donors"]),
                mean_similarity=float(row["mean_similarity"]),
                expected_energy_ev=expected_energy,
            )

    @classmethod
    def load(
        cls,
        *,
        candidates_path: Path = CURATED / "candidate_universe.parquet",
        templates_path: Path = REFERENCE / "templates.parquet",
        ppm_tolerance: float = 10.0,
    ) -> "ReferenceStore":
        return cls(
            pd.read_parquet(candidates_path),
            pd.read_parquet(templates_path),
            ppm_tolerance=ppm_tolerance,
        )

    @property
    def candidate_ids(self) -> list[str]:
        return sorted(self._candidates)

    def __len__(self) -> int:
        return len(self._candidates)

    def candidate(self, candidate_id: str) -> Candidate:
        return self._candidates[candidate_id]

    def metadata(self, candidate_id: str) -> dict:
        return self._candidates[candidate_id].public_dict()

    def candidates_within_ppm(self, precursor_mz: float, *, ppm: float | None = None) -> list[Candidate]:
        if not precursor_mz or precursor_mz <= 0:
            return []
        tolerance = self.ppm_tolerance if ppm is None else float(ppm)
        out = []
        for candidate in self._candidates.values():
            error = abs(candidate.precursor_mz - precursor_mz) / precursor_mz * 1e6
            if error <= tolerance:
                out.append(candidate)
        out.sort(key=lambda c: (abs(c.precursor_mz - precursor_mz), c.molecule_id))
        return out

    def template(self, candidate_id: str, action: str) -> Template:
        key = (str(candidate_id), str(action))
        if key not in self._templates:
            raise KeyError(f"no {action} template for {candidate_id}")
        return self._templates[key]

    def templates_for(self, candidate_id: str) -> dict[str, Template]:
        return {
            action: template
            for (cid, action), template in self._templates.items()
            if cid == candidate_id
        }

    def assert_reference_only(self) -> None:
        forbidden = {"CID40_MEASURED", "EAD16_MEASURED"}
        sources = {template.source for template in self._templates.values()}
        leaked = sources & forbidden
        if leaked:
            raise AssertionError(f"ReferenceStore contains target measurements: {sorted(leaked)}")

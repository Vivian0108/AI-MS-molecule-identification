"""Public case repository.  It never reads oracle or evaluator truth."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from spectrapilot.models import Candidate
from spectrapilot.paths import CURATED
from spectrapilot.science.templates import ReferenceStore


@dataclass(frozen=True)
class Case:
    case_id: str
    precursor_mz: float
    adduct: str
    instrument_model: str
    candidate_ids: list[str]
    available_actions: list[str]
    measurement_budget: int
    split: str
    source_collection: str
    precursor_ambiguous: bool

    def public_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "precursor_mz": self.precursor_mz,
            "adduct": self.adduct,
            "instrument_model": self.instrument_model,
            "n_candidates": len(self.candidate_ids),
            "available_actions": self.available_actions,
            "measurement_budget": self.measurement_budget,
            "split": self.split,
            "precursor_ambiguous": self.precursor_ambiguous,
        }


class CaseRepository:
    def __init__(self, cases: pd.DataFrame, references: ReferenceStore):
        self.references = references
        self._cases: dict[str, Case] = {}
        for _, row in cases.iterrows():
            candidate_ids = row["candidate_ids"]
            if isinstance(candidate_ids, np.ndarray):
                candidate_ids = candidate_ids.tolist()
            actions = row["available_actions"]
            if isinstance(actions, np.ndarray):
                actions = actions.tolist()
            case = Case(
                case_id=str(row["case_id"]),
                precursor_mz=float(row["precursor_mz"]),
                adduct=str(row.get("adduct", "[M+H]+")),
                instrument_model=str(row.get("instrument_model", "ZENOTOF7600")),
                candidate_ids=[str(cid) for cid in candidate_ids],
                available_actions=[str(action) for action in actions],
                measurement_budget=int(row.get("measurement_budget", 1)),
                split=str(row.get("split", "")),
                source_collection=str(row.get("source_collection", "")),
                precursor_ambiguous=bool(row.get("precursor_ambiguous", len(candidate_ids) >= 2)),
            )
            self._cases[case.case_id] = case

    @classmethod
    def load(
        cls,
        references: ReferenceStore,
        path: Path = CURATED / "cases.parquet",
    ) -> "CaseRepository":
        return cls(pd.read_parquet(path), references)

    def __len__(self) -> int:
        return len(self._cases)

    def case_ids(self, split: str | None = None) -> list[str]:
        ids = sorted(self._cases)
        if split is None:
            return ids
        return [case_id for case_id in ids if self._cases[case_id].split == split]

    def has_case(self, case_id: str) -> bool:
        return case_id in self._cases

    def case(self, case_id: str) -> Case:
        return self._cases[case_id]

    def candidates(self, case_id: str) -> list[Candidate]:
        return [self.references.candidate(cid) for cid in self.case(case_id).candidate_ids]

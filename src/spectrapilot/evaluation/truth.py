"""Evaluator-only truth store.

Nothing in the runtime service imports this module.  Tests assert that the
public case repository has no truth field and that the reference directory has
no target spectrum.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from spectrapilot.paths import EVALUATOR_PRIVATE


class EvaluatorStore:
    def __init__(self, truth: pd.DataFrame):
        self._truth = truth.set_index("case_id")

    @classmethod
    def load(cls, path: Path = EVALUATOR_PRIVATE / "truth.parquet") -> "EvaluatorStore":
        return cls(pd.read_parquet(path))

    def __len__(self) -> int:
        return len(self._truth)

    def truth(self, case_id: str) -> str:
        return str(self._truth.loc[case_id, "true_molecule_id"])

    def name(self, case_id: str) -> str:
        return str(self._truth.loc[case_id, "true_name"])

    def split(self, case_id: str) -> str:
        return str(self._truth.loc[case_id, "split"])

    def aliases(self, case_id: str) -> set[str]:
        """Return the true full InChIKey and its stereo/connectivity aliases."""
        row = self._truth.loc[case_id]
        true_id = str(row["true_molecule_id"])
        connectivity = str(row["connectivity_key"])
        aliases = {true_id, connectivity}
        # The candidate universe may contain stereoisomers with the same first
        # InChIKey block.  Those are aliases for open-world removal.
        return aliases

    def rows(self) -> pd.DataFrame:
        return self._truth.reset_index()

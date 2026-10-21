"""Molecular (Axis A) train/dev/test splits.

Scaffold groups are assigned greedily to the split with the largest remaining
capacity.  Molecule IDs are never shared between splits.  The split is frozen
before any test evaluation; the seed is recorded in ``splits.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from unknownid.paths import SPLITS_JSON


@dataclass
class SplitResult:
    assignment: dict[str, str]
    groups: dict[str, list[str]]
    seed: int
    scheme: str
    counts: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "scheme": self.scheme,
            "counts": self.counts,
            "assignment": self.assignment,
            "groups": self.groups,
        }

    def save(self, path: Path = SPLITS_JSON) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = SPLITS_JSON) -> "SplitResult":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            assignment=data["assignment"],
            groups=data.get("groups", {}),
            seed=data.get("seed", 0),
            scheme=data.get("scheme", ""),
            counts=data.get("counts", {}),
        )


def assign_splits(
    complete: pd.DataFrame,
    *,
    seed: int = 20261020,
    train: float = 0.60,
    dev: float = 0.20,
    test: float = 0.20,
    scheme: str = "bemis_murcko_scaffold_then_identity",
) -> SplitResult:
    if not np.isclose(train + dev + test, 1.0):
        raise ValueError("split ratios must sum to 1")
    rng = np.random.default_rng(seed)

    frame = complete.copy()
    # Empty scaffolds fall back to the molecule itself, preventing cross-split
    # leakage of undefined chemotypes.
    frame["group_key"] = frame["scaffold"].fillna("").replace("", np.nan)
    frame["group_key"] = frame["group_key"].fillna("ID:" + frame["molecule_id"])

    grouped = {
        key: sorted(group["molecule_id"].tolist())
        for key, group in frame.groupby("group_key")
    }
    # Deterministic order: largest groups first, shuffled within equal size.
    keys = sorted(grouped)
    rng.shuffle(keys)
    keys.sort(key=lambda key: -len(grouped[key]))

    n = len(frame)
    targets = {"train": train * n, "dev": dev * n, "test": test * n}
    counts = {"train": 0, "dev": 0, "test": 0}
    assignment: dict[str, str] = {}
    assigned_groups: dict[str, list[str]] = {"train": [], "dev": [], "test": []}

    for key in keys:
        molecules = grouped[key]
        # Choose the split with the most remaining room; ties prefer train then
        # dev then test so all splits are populated.
        split = max(
            ("train", "dev", "test"),
            key=lambda name: (targets[name] - counts[name], -("train", "dev", "test").index(name)),
        )
        assigned_groups[split].append(key)
        counts[split] += len(molecules)
        for molecule_id in molecules:
            assignment[molecule_id] = split

    return SplitResult(
        assignment=assignment,
        groups=assigned_groups,
        seed=seed,
        scheme=scheme,
        counts=counts,
    )


def assert_disjoint(result: SplitResult) -> None:
    sets = {
        split: {
            molecule_id
            for molecule_id, assigned in result.assignment.items()
            if assigned == split
        }
        for split in ("train", "dev", "test")
    }
    if sets["train"] & sets["dev"] or sets["train"] & sets["test"] or sets["dev"] & sets["test"]:
        raise AssertionError("molecule leakage between splits")

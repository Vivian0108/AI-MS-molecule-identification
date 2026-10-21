#!/usr/bin/env python
"""Write a small, anonymised demo-case list for the Streamlit app and README.

The selection is deterministic and uses only public case metadata.  Compound
names and hidden spectra are deliberately excluded.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unknownid.paths import AUDIT_CASES_PARQUET, CURATED  # noqa: E402


def pick(frame: pd.DataFrame, split: str, cohort: str, predicate, sort_by, ascending) -> dict | None:
    candidates = frame[(frame["split"] == split) & predicate(frame)].copy()
    if candidates.empty:
        return None
    candidates = candidates.sort_values(sort_by, ascending=ascending, kind="mergesort")
    row = candidates.iloc[0]
    return {
        "case_id": str(row["case_id"]),
        "split": split,
        "cohort": cohort,
        "n_candidates": int(row["n_candidates"]),
        "precursor_mz": round(float(row["precursor_mz"]), 4),
        "why": {
            "ambiguous": "multiple precursor-consistent candidates; tests evidence accumulation",
            "close_call": "top-2 margin <= 0.15; tests abstention versus forced choice",
            "easy": "precursor-unique; tests the low-cost stop path",
        }[cohort],
    }


def main() -> int:
    if not AUDIT_CASES_PARQUET.exists():
        print("error: run `make prepare` first", file=sys.stderr)
        return 1
    frame = pd.read_parquet(AUDIT_CASES_PARQUET)
    selections: list[dict] = []
    for split in ("test", "dev", "train"):
        picks = [
            pick(frame, split, "ambiguous", lambda d: d["n_candidates"] >= 2, ["n_candidates"], [False]),
            pick(
                frame,
                split,
                "close_call",
                lambda d: (d["n_candidates"] >= 2) & (d["top2_margin"] <= 0.15),
                ["top2_margin"],
                [True],
            ),
            pick(frame, split, "easy", lambda d: d["n_candidates"] == 1, ["case_id"], [True]),
        ]
        seen: set[str] = set()
        for item in picks:
            if item and item["case_id"] not in seen:
                seen.add(item["case_id"])
                selections.append(item)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "Anonymised demo case identifiers only. No compound names, source accessions, "
            "hidden spectra or true identities are included. The UI resolves each case at runtime."
        ),
        "cases": selections,
    }
    path = CURATED / "demo_cases.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"==> wrote {path} ({len(selections)} cases)")
    for item in selections:
        print(f"    {item['split']:5s} {item['cohort']:10s} {item['case_id']} "
              f"({item['n_candidates']} candidates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

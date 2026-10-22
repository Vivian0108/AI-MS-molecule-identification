"""Dev-only runtime feasibility check; no model fitting or scientific evaluation.

Reconstructs the first three precursor-ambiguous dev cases from already curated
archived records. All hidden payloads and full exports stay in an ignored private
directory. Does not read test query records or write existing reports/configs.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from spectrapilot.paths import CURATED, ORACLE_PRIVATE, ROOT
from spectrapilot.service import SpectraPilotService
from unknownid.core.ids import make_case_id

OUTPUT = ROOT / "reports" / "interactive_spike"
PRIVATE = ORACLE_PRIVATE / "interactive_spike"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dev_oracle() -> tuple[list[str], dict]:
    cases = (
        pd.read_parquet(
            CURATED / "cases.parquet",
            filters=[("split", "==", "dev"), ("precursor_ambiguous", "==", True)],
        )
        .sort_values("case_id")
        .head(3)
    )
    if len(cases) != 3:
        raise RuntimeError("need at least three ambiguous development cases")
    selected_ids = cases.case_id.tolist()
    # Predicate pushdown excludes all train/test experimental records.
    records = pd.read_parquet(CURATED / "records.parquet", filters=[("split", "==", "dev")])
    # Case IDs use the compound representative precursor, not necessarily each
    # action's measured precursor. Reconstruct that mapping from dev metadata.
    compounds = pd.read_parquet(
        CURATED / "candidate_universe.parquet",
        filters=[("split", "==", "dev")],
        columns=["compound_full_inchikey", "precursor_mz"],
    )
    ids = {
        str(row.compound_full_inchikey): make_case_id(
            str(row.compound_full_inchikey), float(row.precursor_mz)
        )
        for row in compounds.itertuples()
    }
    records["case_id"] = records.compound_full_inchikey.map(ids)
    records = records[records.case_id.isin(selected_ids)]
    payload = {}
    for case_id in selected_ids:
        measurements = {}
        for action in ("CID20", "CID40", "EAD16"):
            rows = records[(records.case_id == case_id) & (records.action == action)]
            if len(rows) != 1:
                raise RuntimeError(f"expected one archived {action} record for {case_id}")
            row = rows.iloc[0]
            if row["license"] != "CC0-1.0":
                raise RuntimeError("unexpected source data license")
            measurements[action] = {
                "action": action,
                "fragmentation": row.fragmentation_method,
                "energy_ev": float(row.energy_value),
                "accession": row.record_id,
                "peaks_mz": row.peaks_mz.tolist(),
                "peaks_intensity": row.peaks_intensity.tolist(),
            }
        payload[case_id] = {
            "case_id": case_id,
            "initial": measurements.pop("CID20"),
            "hidden": measurements,
        }
    return selected_ids, payload


def run() -> dict:
    selected_ids, oracle = build_dev_oracle()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    oracle_path = PRIVATE / "cases.json"
    oracle_path.write_text(json.dumps(oracle, separators=(",", ":")) + "\n")
    service = SpectraPilotService(oracle_path=oracle_path)
    summaries = []
    for case_id in selected_ids:
        initial = service.start_case(case_id)
        assert initial["case"]["split"] == "dev"
        assert initial["observed_actions"] == ["CID20"]
        assert initial["observation"]["energy_ev"] == 20
        assert initial["observation"]["accession"] is None
        plan = service.plan(case_id)
        recommended = plan["recommended"]["key"]
        measurement = None
        if recommended != "STOP":
            measurement = service.measure(case_id, recommended)
            assert measurement["measurement"]["action"] == recommended
            assert measurement["measurement"]["accession"] is None
            assert measurement["remaining_budget"] == 0
        stopped = service.stop(case_id)
        exported = service.report(case_id)
        assert stopped["investigation"] == exported["investigation"]
        assert "# SpectraPilot investigation report" in exported["report_markdown"]
        # Full observation/evidence exports contain only revealed measurements;
        # keep them local for follow-up intervention comparisons.
        trace = {"initial": initial, "plan": plan, "measurement": measurement, "final": exported}
        (PRIVATE / f"{case_id}.json").write_text(json.dumps(trace, indent=2) + "\n")
        (PRIVATE / f"{case_id}.md").write_text(exported["report_markdown"])
        summaries.append(
            {
                "case_id": case_id,
                "split": "dev",
                "n_candidates": initial["case"]["n_candidates"],
                "initial_top1": initial["ranking"]["candidates"][0]["candidate_id"],
                "recommended_action": recommended,
                "observed_actions": exported["investigation"]["observed_actions"],
                "final_top1": exported["investigation"]["candidate_evidence"][0]["candidate_id"],
                "decision": exported["investigation"]["decision"],
                "optional_scans": int(measurement is not None),
                "json_export_ok": True,
                "markdown_export_ok": True,
            }
        )
    protected_paths = [
        "configs/multims2.yaml",
        "configs/policies.yaml",
        "data/multims2/curated/split_manifest.json",
        "data/multims2/curated/records.parquet",
        "data/multims2/curated/cases.parquet",
        "data/multims2/reference/templates.parquet",
    ]
    result = {
        "study": "interactive evidence feasibility spike — baseline only",
        "scientific_evaluation": False,
        "selection_rule": "first three lexicographically sorted precursor-ambiguous dev case IDs",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "pyarrow", "pydantic", "rdkit", "pytest")
        },
        "input_sha256": {path: sha256(ROOT / path) for path in protected_paths},
        "cases": summaries,
        "limitations": [
            "Runtime smoke check only; no truth evaluation or identification accuracy claim.",
            "No MCP, interventions or canvas implemented at this baseline stage.",
            "Original service thresholds, references and planner unchanged.",
            "Committed curated records include target spectra and identities: application-level sealing only.",
            "Reference CID40 uses CID60 spectra; EAD16 uses train-only kNN templates.",
        ],
    }
    (OUTPUT / "baseline.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# Interactive evidence spike: baseline",
        "",
        "Development-only runtime check, not scientific evaluation. No truth-based scoring.",
        "",
        f"Selection: {result['selection_rule']}.",
        "",
        "| Case | Candidates | Recommended | Optional scans | Final decision |",
        "|---|---:|---|---:|---|",
    ]
    lines.extend(
        f"| {r['case_id']} | {r['n_candidates']} | {r['recommended_action']} | "
        f"{r['optional_scans']} | {r['decision']} |"
        for r in summaries
    )
    lines += ["", "All cases exported JSON and Markdown successfully.", ""]
    lines += [f"- {limitation}" for limitation in result["limitations"]]
    (OUTPUT / "baseline.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {"cases": summaries, "report": "reports/interactive_spike/baseline.md"}, indent=2
        )
    )
    return result


if __name__ == "__main__":
    run()

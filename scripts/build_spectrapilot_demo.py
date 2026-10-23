"""Curate three real development examples; no frozen test spectra or tuning."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

import pandas as pd

import check_modality_headroom as headroom
import check_train_reference_quality as quality
import check_train_stage1_reference as stage1
from spectrapilot.paths import CURATED, ROOT, load_config

DEST = ROOT / "data" / "demo"
ROLES = {
    "resolve": ("Resolve uncertainty", "Competing candidates, then one archived measurement."),
    "stop": ("Save a measurement", "Sufficient current evidence: stop and report."),
    "abstain": (
        "Abstain responsibly",
        "Inspect more evidence and acknowledge remaining ambiguity.",
    ),
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def run():
    cfg = load_config("multims2")
    metadata, train, train_records, _ = quality.load_inputs()
    extra = pd.read_parquet(
        CURATED / "candidate_universe.parquet",
        columns=["compound_full_inchikey", "name", "formula", "exact_mass", "adduct"],
    )
    metadata = metadata.merge(extra, on="compound_full_inchikey", validate="one_to_one")
    cases, identities, oracle_payload = headroom.load_dev_inputs()
    predictor = quality.Predictor(
        metadata, train, train_records, {cid: "train" for cid in train.compound_full_inchikey}, cfg
    )
    # CID60 is a permitted library reference, not a hidden query. Include train
    # and dev references only; frozen test spectra are never read at any energy.
    dev_refs = pd.read_parquet(
        CURATED / "records.parquet", filters=[("split", "==", "dev"), ("action", "==", "CID60")]
    )
    import numpy as np

    for row in dev_refs.itertuples():
        predictor.records[(str(row.compound_full_inchikey), "CID60")] = {
            "record_id": str(row.record_id),
            "mz": np.asarray(row.peaks_mz, float),
            "intensity": np.asarray(row.peaks_intensity, float),
        }
    needed = {candidate for values in cases.candidate_ids for candidate in values}
    refs, _ = stage1.make_references(
        metadata, predictor, "dev", needed, "donor_agreement", "training_cid60_anchored"
    )
    from types import SimpleNamespace
    from spectrapilot.data.repository import CaseRepository
    from spectrapilot.planning.oracle import OracleStore

    scorer, planner = stage1.create_components(cfg, load_config("policies"))
    runtime = SimpleNamespace(
        repository=CaseRepository(cases, refs),
        oracle=OracleStore(oracle_payload),
        scorer=scorer,
        planner=planner,
    )
    outcomes = []
    for case_id in cases.case_id:
        initial = stage1.run_branch(runtime, case_id, "cid20_only")
        adaptive = stage1.run_branch(runtime, case_id, "separation")
        true_id = identities[case_id]["true_id"]
        before, after = (
            headroom.score_outcome(initial, true_id),
            headroom.score_outcome(adaptive, true_id),
        )
        outcomes.append(
            {
                "case_id": case_id,
                "before": before,
                "after": after,
                "rank_changed": before["top1_id"] != after["top1_id"],
            }
        )
    selected = {}
    resolved = [
        row
        for row in outcomes
        if row["before"]["decision"] == "AMBIGUOUS"
        and row["after"]["accepted_correct"]
        and row["after"]["optional_scans"] == 1
    ]
    # Prefer a visibly changed ranking, then stable case ID. This is openly
    # outcome-conditioned development curation, not independent evidence.
    resolved.sort(key=lambda row: (not row["rank_changed"], row["case_id"]))
    stopped = [
        row
        for row in outcomes
        if row["before"]["accepted_correct"] and row["after"]["chosen_action"] == "STOP"
    ]
    abstained = [
        row
        for row in outcomes
        if row["before"]["decision"] == "AMBIGUOUS"
        and row["after"]["decision"] == "AMBIGUOUS"
        and row["after"]["optional_scans"] == 1
    ]
    for role, eligible in (("resolve", resolved), ("stop", stopped), ("abstain", abstained)):
        used = {row["case_id"] for row in selected.values()}
        candidates = [row for row in eligible if row["case_id"] not in used]
        if not candidates:
            raise RuntimeError(
                f"no genuine development example for {role}; do not manufacture an outcome"
            )
        selected[role] = candidates[0]
    chosen = {row["case_id"] for row in selected.values()}
    public_cases = []
    for row in cases[cases.case_id.isin(chosen)].to_dict(orient="records"):
        public_cases.append(
            {
                key: value.tolist() if hasattr(value, "tolist") else value
                for key, value in row.items()
            }
        )
    candidate_ids = {candidate for row in public_cases for candidate in row["candidate_ids"]}
    candidates = metadata[metadata.compound_full_inchikey.isin(candidate_ids)].to_dict(
        orient="records"
    )
    templates, reference_provenance = [], []
    for candidate in sorted(candidate_ids):
        for action in quality.ACTIONS:
            template = refs.template(candidate, action)
            prediction = predictor.predict(candidate, action, "dev")
            templates.append(
                {
                    "candidate_id": candidate,
                    "action": action,
                    "peaks_mz": template.mz.tolist(),
                    "peaks_intensity": template.intensity.tolist(),
                    "source": template.source,
                    "reliability": template.reliability,
                    "n_donors": template.n_donors,
                    "mean_similarity": template.mean_similarity,
                }
            )
            reference_provenance.append(
                {
                    "candidate_id": candidate,
                    "action": action,
                    "source": template.source,
                    "donor_ids": prediction["donor_ids"]
                    if template.source != "reference_cid60"
                    else [],
                    "reference_accession": predictor.records[(candidate, "CID60")]["record_id"]
                    if template.source == "reference_cid60"
                    else None,
                }
            )
    write(DEST / "public" / "cases.json", public_cases)
    write(DEST / "public" / "candidates.json", candidates)
    write(DEST / "public" / "templates.json", templates)
    write(DEST / "public" / "reference_provenance.json", reference_provenance)
    write(DEST / "instrument" / "cases.json", {cid: oracle_payload[cid] for cid in sorted(chosen)})
    write(DEST / "evaluator" / "truth.json", {cid: identities[cid] for cid in sorted(chosen)})
    write(
        DEST / "evaluator" / "selection_audit.json",
        {
            "label": "Outcome-conditioned curated DEVELOPMENT examples, not evaluation evidence",
            "selection_rule": "First stable case ID per role; resolve prefers changed ranking; no test outcomes or parameter tuning",
            "eligible_dev_ambiguous_cases": len(cases),
            "selected": selected,
        },
    )
    # Archive acquisition provenance separately from public pre-stop payloads.
    source_records = pd.read_parquet(
        CURATED / "records.parquet",
        filters=[
            ("split", "==", "dev"),
            ("compound_full_inchikey", "in", [identities[cid]["true_id"] for cid in chosen]),
        ],
        columns=[
            "compound_full_inchikey",
            "record_id",
            "action",
            "usi",
            "license",
            "source_collection",
            "filename",
            "scan_id",
        ],
    )
    write(
        DEST / "instrument" / "attribution.json",
        source_records[source_records.action.isin(quality.ACTIONS)].to_dict(orient="records"),
    )
    manifest = {
        "product": "SpectraPilot",
        "mode": "demo",
        "banner": "Demo mode — curated development examples",
        "scope": "Closed-world library identification; archived measurements; not de novo elucidation",
        "reference_method": "Experimental donor-agreement consensus; train-only donors, allowed train/dev CID60 library anchors",
        "dataset": "MultiMS2",
        "source_repository": cfg.get_path("dataset.source_repo"),
        "source_commit": cfg.get_path("dataset.commit"),
        "doi": cfg.get_path("dataset.paper_doi"),
        "data_license": "CC0-1.0",
        "cases": [
            {
                "case_id": selected[role]["case_id"],
                "role": role,
                "title": title,
                "description": description,
            }
            for role, (title, description) in ROLES.items()
        ],
    }
    write(DEST / "public" / "manifest.json", manifest)
    study = json.loads((ROOT / "reports/spectrapilot/train_stage1_reference.json").read_text())
    write(
        DEST / "public" / "results.json",
        {
            "label": study["label"],
            "n": study["n_ambiguous"],
            "source_report": "reports/spectrapilot/train_stage1_reference.md",
            "library_assisted": study["cohorts"]["ambiguous_primary"]["training_cid60_anchored"][
                "methods"
            ]["donor_agreement"]["policies"],
            "predicted_reference_comparison": {
                method: study["cohorts"]["ambiguous_primary"]["native_predicted"]["methods"][
                    method
                ]["policies"]["separation"]
                for method in ("current_conditional", "donor_agreement")
            },
            "primary_interval": study["cohorts"]["ambiguous_primary"]["native_predicted"][
                "method_differences"
            ]["separation"]["accepted_correct"],
            "limitations": [
                "Training cross-validation, not independent test validation.",
                "Demo cases are outcome-selected development illustrations.",
                "Library anchors use a different CID energy; demo includes permitted development CID60 references.",
                "No proven adaptive energy-choice advantage; support is not calibrated probability.",
            ],
        },
    )
    (DEST / "public" / "scientific_report.md").write_text(
        (ROOT / "reports/spectrapilot/train_stage1_reference.md").read_text()
    )
    write(
        DEST / "build_manifest.json",
        {
            "generated_utc": datetime.now(UTC).isoformat(),
            "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "inputs": {path: quality.sha256(ROOT / path) for path in quality.INPUT_PATHS},
            "builder_sha256": quality.sha256(ROOT / "scripts/build_spectrapilot_demo.py"),
            "files": {
                str(path.relative_to(DEST)): quality.sha256(path)
                for path in sorted(DEST.rglob("*"))
                if path.suffix in {".json", ".md", ".txt"} and path.name != "build_manifest.json"
            },
        },
    )
    print(
        json.dumps(
            {
                role: {
                    "case_id": row["case_id"],
                    "initial": row["before"]["decision"],
                    "final": row["after"]["decision"],
                    "action": row["after"]["chosen_action"],
                    "rank_changed": row["rank_changed"],
                }
                for role, row in selected.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    run()

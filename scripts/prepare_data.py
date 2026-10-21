#!/usr/bin/env python
"""Build the frozen curated dataset, audit, splits, cases and error model.

Run after ``scripts/fetch_data.sh``::

    PYTHONPATH=src python scripts/prepare_data.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unknownid.config import load_config
from unknownid.core.retrieve import ReferenceStore
from unknownid.core.spectra import ProcessedSpectrum
from unknownid.data.audit import build_audit
from unknownid.data.curate import (
    build_case_specs,
    build_case_tables,
    build_reference_library,
    curate_raw,
    select_representatives,
)
from unknownid.data.splits import SplitResult, assert_disjoint, assign_splits
from unknownid.paths import (
    COMPLETE_CASES_PARQUET,
    CURATED,
    LIBRARY_PARQUET,
    ORACLE_DIR,
    PARTIAL_CASES_PARQUET,
    PRIVATE_ORACLE_JSON,
    PUBLIC_CASES_PARQUET,
    RAW_ATHENS,
    RECORDS_PARQUET,
    SPECTRA_PARQUET,
    SPLITS_JSON,
    ensure_dirs,
)
from unknownid.planner.error_model import ErrorModel, TrainingObservation


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _environment() -> dict[str, str]:
    """Record the numerical stack; missing optional packages are marked."""
    packages = (
        "numpy",
        "pandas",
        "pyarrow",
        "scipy",
        "scikit-learn",
        "rdkit",
        "matchms",
        "pydantic",
        "fastapi",
        "streamlit",
    )
    recorded = {"python": platform.python_version()}
    for package in packages:
        try:
            recorded[package] = version(package)
        except PackageNotFoundError:
            recorded[package] = "not installed"
    return recorded


def _parquet_safe(frame: pd.DataFrame) -> pd.DataFrame:
    """Serialise mixed dict columns to JSON strings for Arrow compatibility."""
    out = frame.copy()
    for column in out.columns:
        if out[column].dtype == object:
            sample = out[column].dropna()
            if len(sample) and isinstance(sample.iloc[0], dict):
                out[column] = out[column].apply(
                    lambda value: (
                        json.dumps(value, sort_keys=True) if isinstance(value, dict) else value
                    )
                )
    return out


def build_public_cases(case_specs: pd.DataFrame, splits: SplitResult) -> pd.DataFrame:
    public = case_specs.copy()
    public["split"] = public["molecule_id"].map(splits.assignment)
    public = public.drop(columns=["molecule_id", "n_candidates"])
    return public[
        [
            "case_id",
            "precursor_mz",
            "adduct",
            "instrument_model",
            "candidate_ids",
            "measurement_budget",
            "available_energies",
            "split",
        ]
    ]


def build_private_oracle(
    case_specs: pd.DataFrame,
    splits: SplitResult,
    selected: pd.DataFrame,
    library: pd.DataFrame,
) -> dict:
    observed = {
        (row.molecule_id, int(row.collision_energy_ev)): row for _, row in selected.iterrows()
    }
    references: dict[str, dict[int, str]] = {}
    for _, row in library.iterrows():
        references.setdefault(row.molecule_id, {})[int(row.collision_energy_ev)] = row.accession

    payload = {}
    for _, spec in case_specs.iterrows():
        molecule_id = spec.molecule_id
        hidden_spectra = {}
        hidden_accessions = {}
        for energy in (20, 30, 40):
            row = observed[(molecule_id, energy)]
            hidden_spectra[str(energy)] = {
                "mz": [float(x) for x in row.mz],
                "intensity": [float(x) for x in row.intensity],
            }
            hidden_accessions[str(energy)] = row.accession
        payload[spec.case_id] = {
            "case_id": spec.case_id,
            "true_molecule_id": molecule_id,
            "precursor_mz": float(spec.precursor_mz),
            "split": splits.assignment[molecule_id],
            "hidden_accessions": hidden_accessions,
            "hidden_spectra": hidden_spectra,
            "reference_accessions": {
                str(k): v for k, v in sorted(references.get(molecule_id, {}).items())
            },
        }
    return payload


def fit_error_model(
    selected: pd.DataFrame, train_ids: set[str], references: ReferenceStore
) -> ErrorModel:
    observations = []
    for _, row in selected.iterrows():
        if row.molecule_id not in train_ids:
            continue
        if int(row.collision_energy_ev) not in (20, 30, 40):
            continue
        observations.append(
            TrainingObservation(
                molecule_id=row.molecule_id,
                energy=int(row.collision_energy_ev),
                spectrum=ProcessedSpectrum(
                    np.asarray(row.mz, float), np.asarray(row.intensity, float)
                ),
            )
        )
    return ErrorModel.fit(observations, references)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--skip-error-model", action="store_true")
    args = parser.parse_args()

    ensure_dirs()
    selection_cfg = load_config("selection")
    acquisition_cfg = load_config("acquisition")

    print("==> parsing raw MassBank records")
    raw, manifest = curate_raw(RAW_ATHENS, selection_cfg)
    raw.to_parquet(RECORDS_PARQUET, index=False)
    print(f"    raw={len(raw)} passed={int(raw['passed'].sum())}")

    print("==> selecting replicates")
    selected = select_representatives(raw, selection_cfg)
    selected.to_parquet(SPECTRA_PARQUET, index=False)
    print(f"    selected spectra={len(selected)} molecules={selected.molecule_id.nunique()}")

    print("==> building complete and partial case tables")
    complete, partial = build_case_tables(selected, selection_cfg)
    _parquet_safe(complete).to_parquet(COMPLETE_CASES_PARQUET, index=False)
    _parquet_safe(partial).to_parquet(PARTIAL_CASES_PARQUET, index=False)
    print(f"    complete cases={len(complete)} partial={len(partial)}")

    print("==> building 10/50 eV reference library")
    library = build_reference_library(selected, selection_cfg)
    library.to_parquet(LIBRARY_PARQUET, index=False)
    print(f"    library spectra={len(library)} molecules={library.molecule_id.nunique()}")

    print("==> deterministic molecular splits")
    splits = assign_splits(
        complete,
        seed=int(selection_cfg.get_path("splits.seed", 20261020)),
        train=float(selection_cfg.get_path("splits.train", 0.6)),
        dev=float(selection_cfg.get_path("splits.dev", 0.2)),
        test=float(selection_cfg.get_path("splits.test", 0.2)),
        scheme=str(selection_cfg.get_path("splits.scheme", "bemis_murcko_scaffold_then_identity")),
    )
    assert_disjoint(splits)
    splits.save(SPLITS_JSON)
    print(f"    split counts={splits.counts}")

    print("==> building anonymised public cases and sealed oracle")
    case_specs = build_case_specs(complete, library, selection_cfg)
    public = build_public_cases(case_specs, splits)
    public.to_parquet(PUBLIC_CASES_PARQUET, index=False)
    private = build_private_oracle(case_specs, splits, selected, library)
    ORACLE_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(PRIVATE_ORACLE_JSON, private)
    print(f"    public cases={len(public)} private oracle cases={len(private)}")

    references = ReferenceStore(
        library,
        reference_energies=tuple(selection_cfg.get_path("energies.reference", [10, 50])),
        tolerance_da=float(selection_cfg.get_path("preprocessing.match_tolerance_da", 0.02)),
        template_method=str(selection_cfg.get_path("templates.method", "linear")),
        ppm_tolerance=float(selection_cfg.get_path("filters.ppm_precursor", 10.0)),
    )
    references.assert_reference_only()

    version_payload = {
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "selection_config_sha256": _sha256(ROOT / "config" / "selection.yaml"),
        "acquisition_config_sha256": _sha256(ROOT / "config" / "acquisition.yaml"),
        "source_commit": manifest.get("source_commit"),
        "counts": {
            "raw_records": len(raw),
            "selected_spectra": len(selected),
            "complete_cases": len(complete),
            "partial_cases": len(partial),
            "library_molecules": library.molecule_id.nunique(),
        },
        "split_counts": splits.counts,
        "artefact_sha256": {
            "spectra": _sha256(SPECTRA_PARQUET),
            "library": _sha256(LIBRARY_PARQUET),
            "public_cases": _sha256(PUBLIC_CASES_PARQUET),
            "private_oracle": _sha256(PRIVATE_ORACLE_JSON),
        },
        "replicates": selection_cfg.get_path("replicates.rule"),
        "seed": int(selection_cfg.get_path("splits.seed", 20261020)),
        "environment": _environment(),
        "inference_model": (
            "deterministic cosine/template evidence with a precommitted abstention rule; "
            "no LLM participates in the numerical identification loop"
        ),
    }
    _atomic_write_json(CURATED / "dataset_version.json", version_payload)

    if not args.skip_audit:
        print("==> auditing dataset and difficulty")
        audit = build_audit(
            raw,
            selected,
            complete,
            partial,
            library,
            case_specs,
            references,
            splits,
            cfg=selection_cfg,
            acquisition_cfg=acquisition_cfg,
            manifest=manifest,
            raw_file_count=len(list(RAW_ATHENS.glob("*.txt"))),
        )
        print(f"    audit metrics={len(audit.metrics)} cases={len(audit.cases)}")
        print(f"    wrote {Path('reports/data_audit.md')}")

    if not args.skip_error_model:
        print("==> fitting observation-error model on train identities only")
        train_ids = {mid for mid, split in splits.assignment.items() if split == "train"}
        model = fit_error_model(selected, train_ids, references)
        model.save(CURATED / "error_model.json")
        print("    kappa=" + ", ".join(f"{e}:{model.by_energy[e].kappa:.2f}" for e in (20, 30, 40)))

    print("==> done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

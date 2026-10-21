"""Chemical quality control and curation of raw MassBank records.

Nothing here is inferred from file names.  Every exclusion is recorded with a
stable reason code so the audit can count records surviving each rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Chem.inchi import MolToInchiKey
from rdkit.Chem.Scaffolds import MurckoScaffold

from unknownid.core.ids import make_case_id
from unknownid.core.spectra import PROTON_MASS, preprocess_peaks
from unknownid.io.massbank_parser import MassBankRecord, iter_record_files, parse_record_file

RDLogger.DisableLog("rdApp.*")

MASSBANK_RECORD_URL = "https://massbank.eu/MassBank/RecordDisplay?id={accession}"


@dataclass
class ChemicalQC:
    ok: bool
    canonical_smiles: str = ""
    formula: str = ""
    exact_mass: float = 0.0
    inchikey: str = ""
    scaffold: str = ""
    ppm_error: float = 0.0
    reasons: list[str] = field(default_factory=list)


def chemical_qc(record: MassBankRecord, *, ppm_tolerance: float = 10.0) -> ChemicalQC:
    reasons: list[str] = []
    if not record.smiles:
        return ChemicalQC(ok=False, reasons=["missing_smiles"])
    if not record.formula:
        reasons.append("missing_formula")
    if not record.inchikey:
        reasons.append("missing_inchikey")
    if record.precursor_mz is None or record.precursor_mz <= 0:
        return ChemicalQC(ok=False, reasons=reasons + ["invalid_precursor"])

    mol = Chem.MolFromSmiles(record.smiles)
    if mol is None:
        return ChemicalQC(ok=False, reasons=reasons + ["rdkit_invalid_smiles"])
    if len(Chem.GetMolFrags(mol)) != 1:
        return ChemicalQC(ok=False, reasons=reasons + ["multi_component_smiles"])
    if Chem.GetFormalCharge(mol) != 0:
        return ChemicalQC(ok=False, reasons=reasons + ["charged_parent"])

    formula = rdMolDescriptors.CalcMolFormula(mol)
    exact_mass = float(Descriptors.ExactMolWt(mol))
    canonical_smiles = Chem.MolToSmiles(mol, isomericSmiles=True)
    inchikey = MolToInchiKey(mol)

    if record.formula and record.formula != formula and formula not in record.formula:
        reasons.append("formula_mismatch")
    if not inchikey:
        reasons.append("inchikey_unavailable")
    elif record.inchikey and inchikey != record.inchikey:
        # Connectivity-only equality is flagged separately: a stereo mismatch is
        # not silently repaired.
        if inchikey.split("-")[0] == record.inchikey.split("-")[0]:
            reasons.append("stereo_inchikey_mismatch")
        else:
            reasons.append("inchikey_mismatch")

    theoretical_precursor = exact_mass + PROTON_MASS
    ppm_error = (record.precursor_mz - theoretical_precursor) / theoretical_precursor * 1e6
    if abs(ppm_error) > ppm_tolerance:
        reasons.append("precursor_mass_inconsistent")

    scaffold = ""
    try:
        scaffold = MurckoScaffold.MurckoScaffoldSmiles(mol=mol)
    except Exception:  # pragma: no cover - defensive
        scaffold = ""

    return ChemicalQC(
        ok=not reasons,
        canonical_smiles=canonical_smiles,
        formula=formula,
        exact_mass=exact_mass,
        inchikey=inchikey,
        scaffold=scaffold,
        ppm_error=ppm_error,
        reasons=reasons,
    )


def _metadata_reasons(record: MassBankRecord, cfg: Any) -> list[str]:
    reasons: list[str] = []
    expected = cfg.get_path("instrument", {})
    if record.instrument != expected.get("model"):
        reasons.append("wrong_instrument_model")
    if record.instrument_type != expected.get("type"):
        reasons.append("wrong_instrument_type")
    if record.ms_type.upper() != expected.get("ms_type", "MS2").upper():
        reasons.append("not_ms2")
    if record.ion_mode.upper() != expected.get("ion_mode", "POSITIVE").upper():
        reasons.append("wrong_ion_mode")
    if record.ionization.upper() != expected.get("ionization", "ESI").upper():
        reasons.append("wrong_ionization")
    if record.fragmentation_mode.upper() != expected.get("fragmentation", "CID").upper():
        reasons.append("wrong_fragmentation")
    if record.precursor_type != expected.get("adduct", "[M+H]+"):
        reasons.append("wrong_adduct")
    if cfg.get_path("filters.require_standard", True) and not record.is_standard_compound:
        reasons.append("not_reference_standard")
    if not record.license_is_redistributable:
        reasons.append("license_not_redistributable")
    if not record.collision_energy_is_fixed_ev:
        reasons.append("collision_energy_not_fixed_ev")
    else:
        energies = [int(e) for e in cfg.get_path("energies.all", [])]
        tolerance = float(cfg.get_path("energies.tolerance_ev", 0.5))
        if not any(abs(record.collision_energy_value - e) <= tolerance for e in energies):
            reasons.append("collision_energy_outside_grid")
    if record.num_peak_tagged is not None and record.num_peak_tagged != len(record.peaks):
        reasons.append("peak_count_mismatch")
    if len(record.peaks) < 1:
        reasons.append("empty_spectrum")
    return reasons


def _assigned_energy(record: MassBankRecord, cfg: Any) -> int | None:
    if not record.collision_energy_is_fixed_ev:
        return None
    tolerance = float(cfg.get_path("energies.tolerance_ev", 0.5))
    for energy in cfg.get_path("energies.all", []):
        if abs(record.collision_energy_value - energy) <= tolerance:
            return int(energy)
    return None


def record_row(record: MassBankRecord, qc: ChemicalQC, cfg: Any) -> dict[str, Any]:
    floor = float(cfg.get_path("filters.relative_intensity_floor", 0.01))
    processed = preprocess_peaks(
        [p.mz for p in record.peaks],
        [p.intensity for p in record.peaks],
        rel_floor=floor,
    )
    metadata_reasons = _metadata_reasons(record, cfg)
    reasons = metadata_reasons + qc.reasons
    energy = _assigned_energy(record, cfg)
    return {
        "accession": record.accession,
        "source_path": record.path,
        "source_sha256": record.sha256,
        "license": record.license,
        "name": record.names[0] if record.names else "",
        "smiles_record": record.smiles,
        "smiles": qc.canonical_smiles if qc.ok else record.smiles,
        "formula_record": record.formula,
        "formula": qc.formula if qc.ok else "",
        "exact_mass": qc.exact_mass if qc.ok else np.nan,
        "molecule_id": qc.inchikey if qc.ok else "",
        "scaffold": qc.scaffold,
        "precursor_mz": record.precursor_mz,
        "adduct": record.precursor_type,
        "ion_mode": record.ion_mode,
        "instrument_model": record.instrument,
        "instrument_type": record.instrument_type,
        "fragmentation_mode": record.fragmentation_mode,
        "collision_energy_raw": record.collision_energy_raw,
        "collision_energy_ev": energy,
        "collision_energy_parsed": record.collision_energy_value,
        "collision_energy_unit": record.collision_energy_unit,
        "retention_time_min": record.retention_time_min,
        "is_reference_standard": record.is_standard_compound,
        "num_peaks_raw": len(record.peaks),
        "num_peaks_retained": processed.n_peaks,
        "raw_mz": [float(p.mz) for p in record.peaks],
        "raw_intensity": [float(p.intensity) for p in record.peaks],
        "mz": processed.mz.tolist(),
        "intensity": processed.intensity.tolist(),
        "ppm_error": qc.ppm_error,
        "passed": not reasons,
        "reasons": reasons,
        "record_url": MASSBANK_RECORD_URL.format(accession=record.accession),
    }


def curate_raw(raw_dir: Path, cfg: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    from unknownid.paths import MANIFEST_JSON, RAW_MASSBANK

    rows: list[dict[str, Any]] = []
    manifest_records: list[dict[str, Any]] = []
    files = list(iter_record_files(raw_dir))
    for path in files:
        record = parse_record_file(path)
        qc = chemical_qc(record, ppm_tolerance=float(cfg.get_path("filters.ppm_precursor", 10.0)))
        rows.append(record_row(record, qc, cfg))
        manifest_records.append(
            {
                "accession": record.accession,
                "path": str(Path(path).relative_to(raw_dir.parent.parent)),
                "license": record.license,
                "sha256": record.sha256,
            }
        )
    df = pd.DataFrame(rows)

    commit = ""
    try:
        import subprocess

        commit = subprocess.check_output(
            ["git", "-C", str(RAW_MASSBANK), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        commit = "unknown"
    manifest = {
        "source_repository": cfg.get_path("dataset.source_repo"),
        "source_directory": cfg.get_path("dataset.contributor"),
        "source_commit": commit,
        "persistent_archive": cfg.get_path("dataset.persistent_archive"),
        "retrieved_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "record_count": len(files),
        "processing_config_version": cfg.get_path("version"),
        "parser": "unknownid.io.massbank_parser",
        "records": manifest_records,
    }
    MANIFEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_JSON.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return df, manifest


def select_representatives(df: pd.DataFrame, cfg: Any) -> pd.DataFrame:
    """Choose one acquisition per molecule+energy using an outcome-blind rule.

    Rule (precommitted, independent of identification outcome): highest number
    of retained peaks, then earliest accession.  Replicates never straddle the
    reference/oracle boundary because the same chosen record is used everywhere.
    """
    candidates = df[df["passed"]].copy()
    candidates = candidates.sort_values(
        ["molecule_id", "collision_energy_ev", "num_peaks_retained", "accession"],
        ascending=[True, True, False, True],
    )
    chosen = candidates.drop_duplicates(["molecule_id", "collision_energy_ev"], keep="first")
    chosen = chosen.copy()
    chosen["replicate_count"] = chosen.set_index(["molecule_id", "collision_energy_ev"]).index.map(
        candidates.groupby(["molecule_id", "collision_energy_ev"]).size()
    )
    return chosen.sort_values(["molecule_id", "collision_energy_ev"]).reset_index(drop=True)


def build_case_tables(spectra: pd.DataFrame, cfg: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    energies = [int(e) for e in cfg.get_path("energies.all", [])]
    mid_energies = [int(e) for e in cfg.get_path("energies.mid", [20, 30, 40])]
    min_mid = int(cfg.get_path("filters.min_retained_peaks_mid", 3))
    min_endpoint = int(cfg.get_path("filters.min_retained_peaks_endpoint", 1))

    grouped = spectra.groupby("molecule_id")
    rows = []
    partial = []
    for molecule_id, group in grouped:
        by_energy = {int(row.collision_energy_ev): row for _, row in group.iterrows()}
        present = sorted(by_energy)
        first = group.iloc[0]
        missing = [e for e in energies if e not in by_energy]
        peak_counts = {
            e: int(by_energy[e].num_peaks_retained) if e in by_energy else 0 for e in energies
        }
        reasons: list[str] = []
        if missing:
            reasons.append("missing_energy")
        if any(peak_counts[e] < min_mid for e in mid_energies if e in by_energy):
            reasons.append("too_few_mid_energy_peaks")
        if any(peak_counts[e] < min_endpoint for e in (10, 50) if e in by_energy):
            reasons.append("too_few_endpoint_peaks")
        if len(group) != len(energies):
            reasons.append("unexpected_energy_duplicates")
        row = {
            "molecule_id": molecule_id,
            "smiles": first.smiles,
            "formula": first.formula,
            "exact_mass": first.exact_mass,
            "scaffold": first.scaffold,
            "name": first["name"],
            "precursor_mz": first.precursor_mz,
            "adduct": first.adduct,
            "license": first.license,
            "n_energies": len(present),
            "energies": present,
            "missing_energies": missing,
            "peak_counts": peak_counts,
            "complete": not reasons,
            "reasons": reasons,
            "accessions": {int(e): by_energy[e].accession for e in present},
        }
        if reasons:
            row["partial_reasons"] = reasons
            partial.append(row)
        else:
            rows.append(row)
    complete = pd.DataFrame(rows)
    partial_df = pd.DataFrame(partial)
    return complete, partial_df


def build_reference_library(spectra: pd.DataFrame, cfg: Any) -> pd.DataFrame:
    """Molecules with both endpoint reference spectra (10 and 50 eV).

    The candidate universe does not require the query energies 20/30/40; partial
    molecules with valid endpoints are legitimate reference-library entries.
    """
    endpoints = [int(e) for e in cfg.get_path("energies.endpoints", [10, 50])]
    rows = spectra[spectra["collision_energy_ev"].isin(endpoints)]
    counts = rows.groupby("molecule_id")["collision_energy_ev"].nunique()
    eligible = set(counts[counts == len(endpoints)].index)
    return rows[rows["molecule_id"].isin(eligible)].copy().reset_index(drop=True)


def build_case_specs(
    complete: pd.DataFrame,
    library: pd.DataFrame,
    cfg: Any,
) -> pd.DataFrame:
    """Attach a deterministic case ID and the precursor-consistent candidate list."""
    ppm = float(cfg.get_path("filters.ppm_precursor", 10.0))
    budget = int(cfg.get_path("measurement_budget", 1))
    available = [int(e) for e in cfg.get_path("energies.hidden", [30, 40])]
    per_molecule = library.groupby("molecule_id").first()
    ids = list(per_molecule.index)
    masses = per_molecule["precursor_mz"].to_dict()
    rows = []
    for _, row in complete.iterrows():
        precursor = float(row.precursor_mz)
        candidate_ids = sorted(
            molecule_id
            for molecule_id in ids
            if abs(masses[molecule_id] - precursor) / precursor * 1e6 <= ppm
        )
        rows.append(
            {
                "case_id": make_case_id(row.molecule_id, precursor),
                "molecule_id": row.molecule_id,
                "precursor_mz": precursor,
                "adduct": row.adduct,
                "instrument_model": cfg.get_path("instrument.model"),
                "candidate_ids": candidate_ids,
                "measurement_budget": budget,
                "available_energies": available,
                "n_candidates": len(candidate_ids),
            }
        )
    return pd.DataFrame(rows)

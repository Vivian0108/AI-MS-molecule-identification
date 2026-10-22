"""Build the frozen MultiMS2 SpectraPilot cohort, templates, splits and oracle.

The pipeline is deliberately conservative:

* only positive-mode [M+H]+ records are considered;
* structure, formula and precursor consistency are checked with RDKit;
* one outcome-blind representative is chosen per compound x action;
* query compounds are split by Bemis-Murcko scaffold group;
* EAD/CID templates for agent-facing use are predicted from training compounds
  only (leave-one-compound-out), never copied from the evaluation target.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Chem.AllChem import GetMorganFingerprintAsBitVect
from rdkit.Chem.Scaffolds import MurckoScaffold
from rdkit.Chem.inchi import MolToInchiKey

from unknownid.core.ids import make_case_id
from unknownid.core.spectra import PROTON_MASS, preprocess_peaks
from spectrapilot.data.multims2_parser import MGFRecord, iter_mgf, missing_required_headers
from spectrapilot.paths import (
    CURATED,
    EVALUATOR_PRIVATE,
    MGF_PATH,
    ORACLE_PRIVATE,
    REFERENCE,
    REPORTS,
    ROOT,
    load_config,
)

RDLogger.DisableLog("rdApp.*")

ACTION_KEYS = ("CID20", "CID40", "EAD16")
ACTION_META = {
    "CID20": ("CID", 20, "initial"),
    "CID40": ("CID", 40, "action"),
    "EAD16": ("EAD", 16, "action"),
    "CID60": ("CID", 60, "reference"),
    "EAD12": ("EAD", 12, "optional"),
    "EAD24": ("EAD", 24, "optional"),
}


@dataclass
class QCResult:
    ok: bool
    canonical_smiles: str = ""
    formula: str = ""
    exact_mass: float = 0.0
    inchikey: str = ""
    connectivity: str = ""
    scaffold: str = ""
    precursor_ppm: float = 0.0
    reasons: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.reasons is None:
            self.reasons = []


def _parse_action(record: MGFRecord) -> str | None:
    if record.method == "CID" and record.energy is not None:
        for energy in (20, 40, 60):
            if abs(record.energy - energy) <= 0.5:
                return f"CID{energy}"
    if record.method == "EAD" and record.energy is not None:
        for energy in (12, 16, 24):
            if abs(record.energy - energy) <= 0.5:
                return f"EAD{energy}"
    return None


def chemical_qc(record: MGFRecord, *, ppm_tolerance: float = 10.0) -> QCResult:
    reasons: list[str] = []
    if missing_required_headers(record):
        return QCResult(False, reasons=["missing_required_header"] + [
            f"missing:{key}" for key in missing_required_headers(record)
        ])
    if record.ion_mode != "positive":
        reasons.append("wrong_ion_mode")
    if record.adduct != "[M+H]+":
        reasons.append("wrong_adduct")
    if record.method not in {"CID", "EAD"}:
        reasons.append("wrong_fragmentation")
    if _parse_action(record) is None:
        reasons.append("energy_outside_grid")
    if record.header("INSTRUMENT_NAME") != "ZENOTOF7600":
        reasons.append("wrong_instrument")
    if record.header("MSLEVEL") != "2":
        reasons.append("not_ms2")
    if record.header("QUALITY_CHIMERIC") != "PASSED":
        reasons.append("chimeric")
    if len(record.peaks) < 3:
        reasons.append("too_few_peaks")
    if record.n_peaks_header is not None and record.n_peaks_header != len(record.peaks):
        reasons.append("peak_count_mismatch")
    if record.precursor_mz is None or record.precursor_mz <= 0:
        reasons.append("invalid_precursor")
    if not record.smiles:
        reasons.append("missing_smiles")
    if not record.inchikey:
        reasons.append("missing_inchikey")

    mol = Chem.MolFromSmiles(record.smiles) if record.smiles else None
    if mol is None:
        return QCResult(False, reasons=reasons + ["rdkit_invalid_smiles"])
    if len(Chem.GetMolFrags(mol)) != 1:
        reasons.append("multi_component")
    if Chem.GetFormalCharge(mol) != 0:
        reasons.append("charged_parent")

    formula = rdMolDescriptors.CalcMolFormula(mol)
    exact_mass = float(Descriptors.ExactMolWt(mol))
    canonical_smiles = Chem.MolToSmiles(mol, isomericSmiles=True)
    inchikey = MolToInchiKey(mol)
    if not inchikey:
        reasons.append("inchikey_unavailable")
    elif record.inchikey and inchikey != record.inchikey:
        if inchikey.split("-")[0] == record.inchikey.split("-")[0]:
            reasons.append("stereo_inchikey_mismatch")
        else:
            reasons.append("inchikey_mismatch")
    if record.formula and record.formula != formula:
        reasons.append("formula_rdkit_mismatch")
    precursor_ppm = 0.0
    if record.precursor_mz:
        theoretical = exact_mass + PROTON_MASS
        precursor_ppm = (record.precursor_mz - theoretical) / theoretical * 1e6
        if abs(precursor_ppm) > ppm_tolerance:
            reasons.append("precursor_ppm")

    scaffold = ""
    try:
        scaffold = MurckoScaffold.MurckoScaffoldSmiles(mol=mol)
    except Exception:  # pragma: no cover
        scaffold = ""
    return QCResult(
        ok=not reasons,
        canonical_smiles=canonical_smiles,
        formula=formula,
        exact_mass=exact_mass,
        inchikey=inchikey,
        connectivity=inchikey.split("-")[0],
        scaffold=scaffold,
        precursor_ppm=precursor_ppm,
        reasons=reasons,
    )


def _record_row(record: MGFRecord, qc: QCResult, action: str) -> dict[str, Any]:
    processed = preprocess_peaks(
        [p[0] for p in record.peaks],
        [p[1] for p in record.peaks],
        rel_floor=0.01,
    )
    fragmentation, energy, role = ACTION_META[action]
    return {
        "record_id": f"{record.filename}:{record.scan}:{action}",
        "compound_full_inchikey": qc.inchikey,
        "connectivity_key": qc.connectivity,
        "canonical_smiles": qc.canonical_smiles,
        "formula": qc.formula,
        "exact_mass": qc.exact_mass,
        "precursor_mz": float(record.precursor_mz or 0.0),
        "precursor_ppm": qc.precursor_ppm,
        "charge": int(record.header("CHARGE").replace("+", "") or 1),
        "adduct": record.adduct,
        "ion_mode": record.ion_mode.upper(),
        "acquisition_id": record.header("DATASET_ID"),
        "scan_id": record.scan,
        "filename": record.filename,
        "source_collection": record.header("DESCRIPTION"),
        "instrument_model": record.header("INSTRUMENT_NAME"),
        "fragmentation_method": fragmentation,
        "energy_value": float(energy),
        "action": action,
        "action_role": role,
        "energy_units": "eV",
        "peaks_mz": processed.mz.tolist(),
        "peaks_intensity": processed.intensity.tolist(),
        "n_peaks": processed.n_peaks,
        "source_file": record.source_file,
        "source_row": record.source_block,
        "sha256": record.sha256,
        "usi": record.header("SOURCE_SCAN_USI"),
        "quality_chimeric": record.header("QUALITY_CHIMERIC"),
        "quality_explained_intensity": record.header("QUALITY_EXPLAINED_INTENSITY"),
        "quality_explained_signals": record.header("QUALITY_EXPLAINED_SIGNALS"),
        "claimed_spectrum_id": record.header("SPECTRUM_ID"),
        "is_reference_standard": True,
        "license": "CC0-1.0",
        "name": record.compound_name,
    }


def _morgan(smiles: str, radius: int, bits: int):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return GetMorganFingerprintAsBitVect(mol, radius=radius, nBits=bits)


def _merge_donor_spectra(
    donors: list[tuple[float, list[float], list[float]]], tolerance: float = 0.02
) -> tuple[np.ndarray, np.ndarray, float]:
    """Weighted consensus of donor peaks, clustered at ``tolerance`` Da."""
    clusters: list[dict[str, float]] = []
    total_weight = sum(weight for weight, _, _ in donors)
    for weight, mz, intensity in donors:
        for mz_value, int_value in zip(mz, intensity):
            placed = False
            for cluster in clusters:
                if abs(cluster["mz"] - mz_value) <= tolerance:
                    cluster["weight"] += weight
                    cluster["intensity"] += weight * int_value
                    cluster["n"] += 1
                    placed = True
                    break
            if not placed:
                clusters.append(
                    {"mz": mz_value, "weight": weight, "intensity": weight * int_value, "n": 1}
                )
    if not clusters:
        return np.array([]), np.array([]), 0.0
    clusters.sort(key=lambda item: item["mz"])
    mz = np.array([item["mz"] for item in clusters], float)
    intensity = np.array([item["intensity"] / max(item["weight"], 1e-12) for item in clusters], float)
    if intensity.size and intensity.max() > 0:
        intensity = intensity / intensity.max()
    mean_similarity = float(np.mean([w for w, _, _ in donors])) if donors else 0.0
    return mz, intensity, mean_similarity


def build_templates(
    compounds: pd.DataFrame,
    selected: pd.DataFrame,
    splits: dict[str, str],
    cfg: Any,
) -> pd.DataFrame:
    """Build agent-facing templates from train compounds only."""
    radius = int(cfg.get_path("template_model.fingerprint_radius", 2))
    bits = int(cfg.get_path("template_model.fingerprint_bits", 2048))
    k_cid = int(cfg.get_path("template_model.k_cid", 15))
    k_ead = int(cfg.get_path("template_model.k_ead", 20))
    min_sim = float(cfg.get_path("template_model.min_similarity", 0.05))
    tolerance = float(cfg.get_path("preprocessing.match_tolerance_da", 0.02))

    fingerprints = {}
    for _, row in compounds.iterrows():
        fp = _morgan(str(row["canonical_smiles"]), radius, bits)
        if fp is not None:
            fingerprints[str(row["compound_full_inchikey"])] = fp
    ids = [cid for cid in compounds["compound_full_inchikey"].astype(str) if cid in fingerprints]
    fp_matrix = [fingerprints[cid] for cid in ids]
    index = {cid: i for i, cid in enumerate(ids)}

    action_records: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in selected.iterrows():
        action_records[(str(row["compound_full_inchikey"]), str(row["action"]))] = row

    train_ids = [cid for cid in ids if splits.get(cid) == "train"]
    outputs = []
    for cid in ids:
        candidate_fp = fingerprints[cid]
        for action in ACTION_KEYS + ("CID60",):
            row = action_records.get((cid, action))
            if action == "CID60" and row is not None:
                outputs.append(
                    {
                        "candidate_id": cid,
                        "action": action,
                        "source": "reference_cid60",
                        "n_donors": 1,
                        "mean_similarity": 1.0,
                        "reliability": 0.75,
                        "peaks_mz": row["peaks_mz"],
                        "peaks_intensity": row["peaks_intensity"],
                    }
                )
                continue
            if action == "CID60":
                continue
            donors = []
            for donor_id in train_ids:
                if donor_id == cid:
                    continue
                donor_row = action_records.get((donor_id, action))
                if donor_row is None:
                    continue
                similarity = float(DataStructs.TanimotoSimilarity(candidate_fp, fingerprints[donor_id]))
                if similarity >= min_sim:
                    donors.append(
                        (
                            similarity,
                            list(donor_row["peaks_mz"]),
                            list(donor_row["peaks_intensity"]),
                        )
                    )
            donors.sort(key=lambda item: -item[0])
            k = k_ead if action.startswith("EAD") else k_cid
            donors = donors[:k]
            if not donors:
                outputs.append(
                    {
                        "candidate_id": cid,
                        "action": action,
                        "source": "knn_empty",
                        "n_donors": 0,
                        "mean_similarity": 0.0,
                        "reliability": 0.0,
                        "peaks_mz": [],
                        "peaks_intensity": [],
                    }
                )
                continue
            # Weight similar structures more strongly, but keep the consensus stable.
            weighted = [(max(sim, 0.0) ** 2, mz, intensity) for sim, mz, intensity in donors]
            mz, intensity, mean_sim = _merge_donor_spectra(weighted, tolerance)
            reliability = float(np.clip(mean_sim, 0.0, 1.0))
            if action.startswith("EAD"):
                reliability *= 0.75
            outputs.append(
                {
                    "candidate_id": cid,
                    "action": action,
                    "source": "train_only_structure_knn",
                    "n_donors": len(donors),
                    "mean_similarity": mean_sim,
                    "reliability": reliability,
                    "peaks_mz": mz.tolist(),
                    "peaks_intensity": intensity.tolist(),
                }
            )
    # Use the real CID60 reference as the CID40 template where it exists.  This is
    # the explicitly labelled reference-anchored track, never a test target.
    out = pd.DataFrame(outputs)
    ref = out[out["action"] == "CID60"].set_index("candidate_id")
    cid40 = out[out["action"] == "CID40"].set_index("candidate_id")
    for cid in cid40.index.intersection(ref.index):
        position = cid40.index.get_loc(cid)
        if not isinstance(position, int):
            position = int(np.where(cid40.index == cid)[0][0])
        cid40.iat[position, cid40.columns.get_loc("peaks_mz")] = list(ref.at[cid, "peaks_mz"])
        cid40.iat[position, cid40.columns.get_loc("peaks_intensity")] = list(
            ref.at[cid, "peaks_intensity"]
        )
        cid40.iat[position, cid40.columns.get_loc("source")] = "reference_cid60"
        cid40.iat[position, cid40.columns.get_loc("n_donors")] = 1
        cid40.iat[position, cid40.columns.get_loc("mean_similarity")] = 1.0
        cid40.iat[position, cid40.columns.get_loc("reliability")] = 0.75
    out = pd.concat(
        [out[out["action"] != "CID40"], cid40.reset_index()], ignore_index=True
    )
    return out


def _split_groups(compounds: pd.DataFrame, seed: int, fractions: dict[str, float]) -> dict[str, str]:
    groups: dict[str, list[str]] = defaultdict(list)
    for _, row in compounds.iterrows():
        cid = str(row["compound_full_inchikey"])
        scaffold = str(row.get("scaffold") or "")
        group = scaffold if scaffold else f"ACYCLIC:{row['connectivity_key']}"
        groups[group].append(cid)
    rng = np.random.default_rng(seed)
    keys = sorted(groups)
    rng.shuffle(keys)
    keys.sort(key=lambda key: -len(groups[key]))
    totals = {name: 0 for name in fractions}
    assignments: dict[str, str] = {}
    total_target = sum(fractions.values())
    total = len(compounds)
    for key in keys:
        deficits = {
            name: fractions[name] / total_target * total - totals[name] for name in fractions
        }
        split = max(deficits, key=lambda name: (deficits[name], name == "test"))
        assignments[key] = split
        totals[split] += len(groups[key])
    return {
        cid: assignments[
            (str(row.get("scaffold") or ""))
            or f"ACYCLIC:{row['connectivity_key']}"
        ]
        for _, row in compounds.iterrows()
        for cid in [str(row["compound_full_inchikey"])]
    }


def _candidate_ids(
    precursor: float, ids: list[str], masses: dict[str, float], ppm: float
) -> list[str]:
    tolerance = precursor * ppm * 1e-6
    return sorted(
        [cid for cid in ids if abs(masses[cid] - precursor) <= tolerance],
        key=lambda cid: (abs(masses[cid] - precursor), cid),
    )


def _audit_rows(stage_counts: dict[str, int], extra: dict[str, Any]) -> pd.DataFrame:
    rows = [{"category": "cascade", "metric": key, "value": value} for key, value in stage_counts.items()]
    for category, values in extra.items():
        if isinstance(values, dict):
            rows.extend(
                {"category": category, "metric": str(key), "value": value}
                for key, value in values.items()
            )
        else:
            rows.append({"category": category, "metric": "value", "value": values})
    return pd.DataFrame(rows)


def prepare(config_name: str = "multims2") -> dict[str, Any]:
    cfg = load_config(config_name)
    for directory in (CURATED, REFERENCE, ORACLE_PRIVATE, EVALUATOR_PRIVATE):
        directory.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    if not MGF_PATH.exists():
        raise SystemExit(
            f"MultiMS2 MGF not found at {MGF_PATH}. Run `bash scripts/fetch_multims2.sh`."
        )

    stage_counts = Counter()
    all_rows: list[dict[str, Any]] = []
    qc_reasons = Counter()
    for record in iter_mgf(MGF_PATH):
        stage_counts["raw_mgf_blocks"] += 1
        if record.ion_mode == "positive" and record.adduct == "[M+H]+":
            stage_counts["positive_M_H"] += 1
        qc = chemical_qc(record, ppm_tolerance=float(cfg.get_path("filters.ppm_precursor", 10.0)))
        action = _parse_action(record) if qc.ok else None
        if qc.ok and action is not None and action in ACTION_META:
            row = _record_row(record, qc, action)
            row["split"] = ""  # filled after the compound split
            all_rows.append(row)
            stage_counts["qc_pass"] += 1
        else:
            for reason in qc.reasons:
                qc_reasons[reason] += 1
    frame = pd.DataFrame(all_rows)
    if frame.empty:
        raise SystemExit("No MultiMS2 records passed QC")
    # Outcome-blind representative: largest retained spectrum, then stable file/scan.
    frame = frame.sort_values(
        ["compound_full_inchikey", "action", "n_peaks", "filename", "scan_id"],
        ascending=[True, True, False, True, True],
    )
    counts = frame.groupby(["compound_full_inchikey", "action"]).size()
    selected = frame.drop_duplicates(["compound_full_inchikey", "action"], keep="first").copy()
    selected["replicate_count"] = selected.set_index(["compound_full_inchikey", "action"]).index.map(counts)
    selected = selected.reset_index(drop=True)

    compounds = (
        selected.sort_values("n_peaks", ascending=False)
        .drop_duplicates("compound_full_inchikey")
        .copy()
    )
    compounds["actions"] = compounds["compound_full_inchikey"].map(
        selected.groupby("compound_full_inchikey")["action"].apply(lambda x: sorted(set(x)))
    )
    compounds["source_collections"] = compounds["compound_full_inchikey"].map(
        selected.groupby("compound_full_inchikey")["source_collection"].apply(lambda x: sorted(set(x)))
    )
    ppm_tol = float(cfg.get_path("filters.ppm_precursor", 10.0))
    splits = _split_groups(
        compounds,
        seed=int(cfg.get_path("splits.seed", 20261021)),
        fractions={
            "train": float(cfg.get_path("splits.train", 0.70)),
            "dev": float(cfg.get_path("splits.dev", 0.15)),
            "test": float(cfg.get_path("splits.test", 0.15)),
        },
    )
    selected["split"] = selected["compound_full_inchikey"].map(splits)
    compounds["split"] = compounds["compound_full_inchikey"].map(splits)

    templates = build_templates(compounds, selected, splits, cfg)
    template_map = {
        (str(row.candidate_id), str(row.action)): row for _, row in templates.iterrows()
    }
    masses = dict(zip(compounds["compound_full_inchikey"], compounds["exact_mass"] + PROTON_MASS))
    all_ids = sorted(masses)
    complete = compounds[
        compounds["actions"].map(lambda actions: all(a in actions for a in ACTION_KEYS))
    ].copy()
    # Case tables keep candidate universes identical for every policy.
    cases = []
    oracle_cases = {}
    truth_rows = []
    for _, compound in complete.iterrows():
        cid = str(compound["compound_full_inchikey"])
        action_rows = {
            action: selected[
                (selected["compound_full_inchikey"] == cid) & (selected["action"] == action)
            ].iloc[0]
            for action in ACTION_KEYS
        }
        precursor = float(compound["precursor_mz"])
        candidates = _candidate_ids(precursor, all_ids, masses, ppm_tol)
        case_id = make_case_id(cid, precursor)
        cases.append(
            {
                "case_id": case_id,
                "precursor_mz": precursor,
                "adduct": "[M+H]+",
                "ion_mode": "POSITIVE",
                "instrument_model": "ZENOTOF7600",
                "candidate_ids": candidates,
                "n_candidates": len(candidates),
                "available_actions": ["CID40", "EAD16"],
                "measurement_budget": 1,
                "split": splits[cid],
                "source_collection": compound["source_collections"][0],
                "precursor_ambiguous": len(candidates) >= 2,
            }
        )
        truth_rows.append(
            {
                "case_id": case_id,
                "true_molecule_id": cid,
                "true_name": str(compound["name"]),
                "split": splits[cid],
                "connectivity_key": str(compound["connectivity_key"]),
                "n_candidates": len(candidates),
            }
        )
        oracle_cases[case_id] = {
            "case_id": case_id,
            "initial": {
                "action": "CID20",
                "fragmentation": "CID",
                "energy_ev": 20,
                "accession": str(action_rows["CID20"]["record_id"]),
                "peaks_mz": action_rows["CID20"]["peaks_mz"],
                "peaks_intensity": action_rows["CID20"]["peaks_intensity"],
            },
            "hidden": {
                "CID40": {
                    "action": "CID40",
                    "fragmentation": "CID",
                    "energy_ev": 40,
                    "accession": str(action_rows["CID40"]["record_id"]),
                    "peaks_mz": action_rows["CID40"]["peaks_mz"],
                    "peaks_intensity": action_rows["CID40"]["peaks_intensity"],
                },
                "EAD16": {
                    "action": "EAD16",
                    "fragmentation": "EAD",
                    "energy_ev": 16,
                    "accession": str(action_rows["EAD16"]["record_id"]),
                    "peaks_mz": action_rows["EAD16"]["peaks_mz"],
                    "peaks_intensity": action_rows["EAD16"]["peaks_intensity"],
                },
            },
        }

    cases_df = pd.DataFrame(cases)
    truth_df = pd.DataFrame(truth_rows)
    # Ensure no target spectra are written to the reference directory.  The
    # reference file is built only from CID60 + train-only predictions.
    templates.to_parquet(REFERENCE / "templates.parquet", index=False)
    selected.to_parquet(CURATED / "records.parquet", index=False)
    compounds.to_parquet(CURATED / "candidate_universe.parquet", index=False)
    cases_df.to_parquet(CURATED / "cases.parquet", index=False)
    truth_df.to_parquet(EVALUATOR_PRIVATE / "truth.parquet", index=False)
    (ORACLE_PRIVATE / "cases.json").write_text(
        json.dumps(oracle_cases, separators=(",", ":")), encoding="utf-8"
    )
    (CURATED / "split_manifest.json").write_text(
        json.dumps(
            {
                "seed": int(cfg.get_path("splits.seed", 20261021)),
                "unit": "Bemis-Murcko scaffold group; acyclic compounds grouped by connectivity key",
                "molecule_counts": {
                    split: int((compounds["split"] == split).sum())
                    for split in ("train", "dev", "test")
                },
                "case_counts": {
                    split: int((cases_df["split"] == split).sum())
                    for split in ("train", "dev", "test")
                },
                "molecule_ids": {split: sorted(compounds.loc[compounds["split"] == split, "compound_full_inchikey"].tolist()) for split in ("train", "dev", "test")},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = {
        "dataset": "MultiMS2",
        "source_repository": cfg.get_path("dataset.source_repo"),
        "source_commit": cfg.get_path("dataset.commit"),
        "paper_doi": cfg.get_path("dataset.paper_doi"),
        "license": cfg.get_path("dataset.license"),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mgf_sha256": hashlib.sha256(MGF_PATH.read_bytes()).hexdigest(),
        "config_version": cfg.get_path("version"),
        "raw_mgf_blocks": int(stage_counts["raw_mgf_blocks"]),
        "positive_M_H": int(stage_counts["positive_M_H"]),
        "qc_pass_records": int(stage_counts["qc_pass"]),
        "selected_records": len(selected),
        "compounds": len(compounds),
        "complete_cases": len(cases_df),
        "templates": len(templates),
        "action_counts": {str(key): int(value) for key, value in selected.groupby("action").size().items()},
        "qc_reasons": {str(key): int(value) for key, value in qc_reasons.items()},
        "splits": {
            split: int((cases_df["split"] == split).sum()) for split in ("train", "dev", "test")
        },
        "notes": [
            "All query records are archived experimental measurements.",
            "CID40/EAD16 target peaks are stored only in data/multims2/oracle_private.",
            "Agent-facing templates are train-only structure-kNN predictions, except CID40 where a CID60 reference is explicitly used.",
            "No spectra were generated by a language model.",
        ],
    }
    (CURATED / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    audit = _audit_rows(
        {
            "raw_mgf_blocks": int(stage_counts["raw_mgf_blocks"]),
            "positive_M_H": int(stage_counts["positive_M_H"]),
            "qc_pass": int(stage_counts["qc_pass"]),
            "selected_spectra": len(selected),
            "compounds": len(compounds),
            "complete_CID20_CID40_EAD16": len(cases_df),
        },
        {
            "splits": {
                split: int((cases_df["split"] == split).sum()) for split in ("train", "dev", "test")
            },
            "candidate_prevalence_10ppm": {
                "cases_with_ge2_candidates": int((cases_df["n_candidates"] >= 2).sum()),
                "cases_with_ge3_candidates": int((cases_df["n_candidates"] >= 3).sum()),
                "median_candidates": float(cases_df["n_candidates"].median()),
                "max_candidates": int(cases_df["n_candidates"].max()),
            },
            "qc_exclusions": dict(qc_reasons),
        },
    )
    audit.to_parquet(CURATED / "audit.parquet", index=False)
    _write_reports(manifest, audit, cases_df, compounds, selected, templates)
    return {"manifest": manifest, "cases": cases_df, "compounds": compounds, "templates": templates}


def _write_reports(
    manifest: dict[str, Any],
    audit: pd.DataFrame,
    cases: pd.DataFrame,
    compounds: pd.DataFrame,
    selected: pd.DataFrame,
    templates: pd.DataFrame,
) -> None:
    mapping = """# MultiMS2 metadata mapping

The parser reads MGF key/value headers and never infers identity from a file name.
Required fields are rejected if absent. Values are preserved in `records.parquet`.

| MGF header | Canonical field | Use |
|---|---|---|
| `FILENAME` | `filename` | source provenance and scan grouping |
| `EXTRACTSCAN` | `scan_id` | source scan provenance |
| `COMPOUND_NAME` | `name` | display only; exact identity comes from InChIKey |
| `INCHIAUX` | `compound_full_inchikey` | identity and split grouping |
| `SMILES` | `canonical_smiles` | RDKit structure validation |
| `FORMULA` | `formula` | formula cross-check |
| `PRECURSOR_MZ` | `precursor_mz` | 10 ppm precursor filter |
| `ADDUCT` | `adduct` | fixed to `[M+H]+` |
| `IONMODE` | `ion_mode` | fixed to positive |
| `FRAGMENTATION_METHOD` | `fragmentation_method` | CID or EAD |
| `COLLISION_ENERGY` | `energy_value` | modality-specific numeric grid |
| `INSTRUMENT_NAME` | `instrument_model` | fixed to ZENOTOF7600 |
| `DESCRIPTION` | `source_collection` | MSMLS/NEXUS/SELLECK covariate |
| `SOURCE_SCAN_USI` | `usi` | independent accession |
| `QUALITY_CHIMERIC` | `quality_chimeric` | requires `PASSED` |
| `QUALITY_EXPLAINED_INTENSITY` | quality flag | reported, not hidden |
| `NUM_PEAKS` | peak-count check | must match parsed peaks |

No raw-header value is silently repaired. Missing or contradictory required fields
fail closed and are counted in `data/multims2/curated/audit.parquet`.
"""
    (REPORTS / "metadata_mapping.md").write_text(mapping, encoding="utf-8")
    audit_lines = [
        "# SpectraPilot data audit — MultiMS2",
        "",
        f"Pinned commit: `{manifest['source_commit']}`  ",
        f"MGF SHA-256: `{manifest['mgf_sha256']}`",
        "",
        "| Stage | Count |",
        "|---|---:|",
        f"| Raw MGF blocks | {manifest['raw_mgf_blocks']:,} |",
        f"| Positive `[M+H]+` records | {manifest['positive_M_H']:,} |",
        f"| Records passing QC | {manifest['qc_pass_records']:,} |",
        f"| One representative per compound × action | {manifest['selected_records']:,} |",
        f"| Compounds in candidate universe | {manifest['compounds']:,} |",
        f"| Complete CID20/CID40/EAD16 cases | {manifest['complete_cases']:,} |",
        "",
        "## Split sizes",
        "",
        "| Split | Cases |",
        "|---|---:|",
    ]
    for split in ("train", "dev", "test"):
        audit_lines.append(f"| {split} | {manifest['splits'][split]:,} |")
    n2 = int((cases["n_candidates"] >= 2).sum())
    audit_lines += [
        "",
        "## Ambiguity",
        "",
        f"- Cases with at least two candidates at 10 ppm: **{n2:,} / {len(cases):,}**.",
        f"- Median candidate count: **{cases['n_candidates'].median():.0f}**; max **{cases['n_candidates'].max()}**.",
        f"- Same-formula structural-isomer cases: **{int((cases['n_candidates'] >= 2).sum()):,}** precursor-ambiguous; exact formula overlap is reported in the casebook.",
        "",
        "## Go/no-go",
        "",
        f"- Two-action complete cases: **{manifest['complete_cases']:,}** (preferred target ≥100).",
        f"- Predeclared precursor-ambiguous cases: **{n2:,}** (preferred target ≥30).",
        "- The primary cohort is complete and large enough for a held-out benchmark. The",
        "  EAD template is a train-only structure-kNN prediction, not a hidden target spectrum.",
        "",
        "The complete case list and truth are in `data/multims2/evaluator_private/truth.parquet`.",
        "Agent-facing artefacts never contain the truth column.",
    ]
    (REPORTS / "data_audit.md").write_text("\n".join(audit_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = prepare()
    print(json.dumps(result["manifest"], indent=2))

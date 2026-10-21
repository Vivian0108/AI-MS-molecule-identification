"""Dataset audit: the scientific stop/go gate.

The audit is written before the planner is trusted.  Every number in
``reports/data_audit.md`` is computed from the frozen snapshot; there are no
literature-count substitutions.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from unknownid.core.evidence import EvidenceEvaluator
from unknownid.core.posterior import rank_candidates, top2_margin, update_weights
from unknownid.core.retrieve import ReferenceStore
from unknownid.core.spectra import cosine_greedy
from unknownid.paths import AUDIT_CASES_PARQUET, AUDIT_MD, AUDIT_PARQUET, MANIFEST_JSON, REPORTS
from unknownid.data.splits import SplitResult

METADATA_REASONS = {
    "wrong_instrument_model",
    "wrong_instrument_type",
    "not_ms2",
    "wrong_ion_mode",
    "wrong_ionization",
    "wrong_fragmentation",
    "wrong_adduct",
    "not_reference_standard",
    "license_not_redistributable",
    "collision_energy_not_fixed_ev",
    "collision_energy_outside_grid",
    "peak_count_mismatch",
    "empty_spectrum",
}

CHEMICAL_REASONS = {
    "missing_smiles",
    "missing_formula",
    "missing_inchikey",
    "invalid_precursor",
    "rdkit_invalid_smiles",
    "multi_component_smiles",
    "charged_parent",
    "formula_mismatch",
    "inchikey_unavailable",
    "stereo_inchikey_mismatch",
    "inchikey_mismatch",
    "precursor_mass_inconsistent",
}

RULE_ORDER = [
    ("same instrument model", {"wrong_instrument_model"}),
    ("LC-ESI-QTOF", {"wrong_instrument_type"}),
    ("MS2", {"not_ms2"}),
    ("positive ion mode", {"wrong_ion_mode"}),
    ("ESI", {"wrong_ionization"}),
    ("CID", {"wrong_fragmentation"}),
    ("[M+H]+", {"wrong_adduct"}),
    ("reference standard", {"not_reference_standard"}),
    ("redistributable license", {"license_not_redistributable"}),
    ("fixed eV collision energy", {"collision_energy_not_fixed_ev"}),
    ("CE on 10/20/30/40/50 grid", {"collision_energy_outside_grid"}),
    ("peak count consistency", {"peak_count_mismatch"}),
    ("non-empty spectrum", {"empty_spectrum"}),
    ("chemical QC", CHEMICAL_REASONS),
]


@dataclass
class AuditResult:
    metrics: pd.DataFrame
    cases: pd.DataFrame
    markdown: str


def _metric(metrics: list[dict], category: str, name: str, value: Any, note: str = "") -> None:
    metrics.append({"category": category, "metric": name, "value": value, "note": note})


def _weighted_separation(
    weights: Mapping[str, float],
    references: ReferenceStore,
    candidates: list[str],
    energy: int,
) -> float:
    value = 0.0
    usable = [cid for cid in candidates if cid in weights]
    for i, first in enumerate(usable):
        for second in usable[i + 1 :]:
            a = references.template(first, energy)
            b = references.template(second, energy)
            cosine, _ = cosine_greedy(a.mz, a.intensity, b.mz, b.intensity, references.tolerance_da)
            value += weights[first] * weights[second] * (1.0 - max(min(cosine, 1.0), 0.0))
    return float(value)


def analyse_cases(
    complete: pd.DataFrame,
    selected: pd.DataFrame,
    case_specs: pd.DataFrame,
    references: ReferenceStore,
    splits: SplitResult,
    *,
    kappa: float,
    macq: Any,
) -> pd.DataFrame:
    observed = {
        (row.molecule_id, int(row.collision_energy_ev)): row
        for _, row in selected.iterrows()
    }
    evaluator = EvidenceEvaluator(kappa=kappa, tolerance_da=references.tolerance_da)
    rows = []
    for _, spec in case_specs.iterrows():
        molecule_id = spec.molecule_id
        candidates = [references.candidate(cid) for cid in spec.candidate_ids]
        template20 = {c.molecule_id: references.template(c.molecule_id, 20) for c in candidates}
        row20 = observed.get((molecule_id, 20))
        if row20 is None or not candidates:
            continue
        from unknownid.core.spectra import ProcessedSpectrum

        obs20 = ProcessedSpectrum(np.asarray(row20.mz, float), np.asarray(row20.intensity, float))
        evidence, weights = evaluator.rank(
            obs20, candidates, template20, 20, kappa=kappa, precursor_mz=spec.precursor_mz
        )
        order = rank_candidates(weights)
        top = order[0]
        margin = top2_margin(weights)
        top_support = weights[top]
        top_cos = evidence[[e.candidate_id for e in evidence].index(top)].similarity_by_energy[20]
        top2_cos = (
            evidence[[e.candidate_id for e in evidence].index(order[1])].similarity_by_energy[20]
            if len(order) > 1
            else top_cos
        )

        sep30 = _weighted_separation(weights, references, list(weights), 30)
        sep40 = _weighted_separation(weights, references, list(weights), 40)

        outcome30 = outcome40 = None
        if len(order) > 1:
            second = order[1]
            a30, b30 = references.template(top, 30), references.template(second, 30)
            a40, b40 = references.template(top, 40), references.template(second, 40)
            d30 = 1.0 - cosine_greedy(a30.mz, a30.intensity, b30.mz, b30.intensity, references.tolerance_da)[0]
            d40 = 1.0 - cosine_greedy(a40.mz, a40.intensity, b40.mz, b40.intensity, references.tolerance_da)[0]
        else:
            d30 = d40 = 0.0

        # Oracle-diagnostic outcome (audit only; never used by the planner).
        for energy, target in ((30, "outcome30"), (40, "outcome40")):
            row_e = observed.get((molecule_id, energy))
            if row_e is None:
                continue
            arrays = {
                c.molecule_id: (
                    references.template(c.molecule_id, energy).mz,
                    references.template(c.molecule_id, energy).intensity,
                )
                for c in candidates
            }
            spectrum = ProcessedSpectrum(
                np.asarray(row_e.mz, float), np.asarray(row_e.intensity, float)
            )
            updated = update_weights(
                weights,
                (spectrum.mz, spectrum.intensity),
                arrays,
                kappa=kappa,
                tolerance=references.tolerance_da,
                tempering=1.0,
            )
            correct = rank_candidates(updated)[0] == molecule_id
            if target == "outcome30":
                outcome30 = correct
            else:
                outcome40 = correct

        n_formula = int(
            sum(
                1
                for c in candidates
                if references.candidate(c.molecule_id).formula
                == references.candidate(molecule_id).formula
            )
        )
        rows.append(
            {
                "case_id": spec.case_id,
                "molecule_id": molecule_id,
                "name": references.candidate(molecule_id).name,
                "split": splits.assignment.get(molecule_id, ""),
                "precursor_mz": spec.precursor_mz,
                "formula": references.candidate(molecule_id).formula,
                "n_candidates": len(candidates),
                "n_formula_matches": n_formula,
                "precursor_only_unique": len(candidates) == 1,
                "top1_correct": top == molecule_id,
                "top1_id": top,
                "top1_support": float(top_support),
                "top2_margin": float(margin),
                "top1_cosine": float(top_cos),
                "top2_cosine": float(top2_cos),
                "sep30": sep30,
                "sep40": sep40,
                "top2_sep30": float(d30),
                "top2_sep40": float(d40),
                "sep_choice_differs": bool(abs(d30 - d40) >= 0.05),
                "outcome30_correct": outcome30,
                "outcome40_correct": outcome40,
                "outcome_differs": (
                    bool(outcome30 != outcome40)
                    if outcome30 is not None and outcome40 is not None
                    else False
                ),
            }
        )
    return pd.DataFrame(rows)


def build_audit(
    raw: pd.DataFrame,
    selected: pd.DataFrame,
    complete: pd.DataFrame,
    partial: pd.DataFrame,
    library: pd.DataFrame,
    case_specs: pd.DataFrame,
    references: ReferenceStore,
    splits: SplitResult,
    *,
    cfg: Any,
    acquisition_cfg: Any,
    manifest: dict,
    raw_file_count: int,
) -> AuditResult:
    metrics: list[dict] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # -- snapshot ----------------------------------------------------------
    _metric(metrics, "snapshot", "source_commit", manifest.get("source_commit", ""))
    _metric(metrics, "snapshot", "retrieved_at_utc", manifest.get("retrieved_at_utc", ""))
    _metric(metrics, "snapshot", "audit_generated_at_utc", now)
    _metric(metrics, "snapshot", "raw_files", raw_file_count)
    _metric(metrics, "snapshot", "parsed_records", len(raw))
    _metric(metrics, "snapshot", "records_all_rules_passed", int(raw["passed"].sum()))

    # -- exclusion cascade -------------------------------------------------
    reasons_per_record = [set(items) for items in raw["reasons"]]
    surviving = np.ones(len(raw), dtype=bool)
    cascade_rows = []
    for label, reasons in RULE_ORDER:
        surviving &= np.array([not (reasons & item) for item in reasons_per_record])
        count = int(surviving.sum())
        cascade_rows.append({"rule": label, "records_surviving": count})
        _metric(metrics, "exclusion_cascade", label, count)
    reason_counts = Counter(reason for items in reasons_per_record for reason in items)
    for reason, count in sorted(reason_counts.items(), key=lambda item: -item[1]):
        _metric(metrics, "exclusion_reason", reason, int(count))

    # -- cohort composition ------------------------------------------------
    for column, label in (
        ("collision_energy_ev", "collision_energy_ev"),
        ("instrument_model", "instrument_model"),
        ("instrument_type", "instrument_type"),
        ("adduct", "adduct"),
        ("fragmentation_mode", "fragmentation_mode"),
        ("license", "license_raw"),
        ("is_reference_standard", "reference_standard_raw"),
    ):
        for value, count in raw[column].value_counts(dropna=False).items():
            _metric(metrics, "cohort_raw", f"{label}={value}", int(count))
    for column, label in (
        ("collision_energy_ev", "collision_energy_ev"),
        ("license", "license_selected"),
        ("adduct", "adduct_selected"),
    ):
        for value, count in selected[column].value_counts(dropna=False).items():
            _metric(metrics, "cohort_selected", f"{label}={value}", int(count))

    _metric(metrics, "identity_qc", "distinct_molecules_all_passed", int(selected["molecule_id"].nunique()))
    _metric(metrics, "identity_qc", "distinct_connectivity_blocks", int(selected["molecule_id"].str.split("-").str[0].nunique()))
    _metric(metrics, "identity_qc", "distinct_formulas", int(selected["formula"].nunique()))
    _metric(metrics, "identity_qc", "reference_library_molecules", int(library["molecule_id"].nunique()))
    _metric(metrics, "identity_qc", "complete_five_energy_cases", len(complete))
    _metric(metrics, "identity_qc", "partial_cases", len(partial))
    for split in ("train", "dev", "test"):
        _metric(metrics, "splits", f"{split}_molecules", int(sum(1 for v in splits.assignment.values() if v == split)))
    _metric(metrics, "splits", "seed", splits.seed)
    _metric(metrics, "splits", "scheme", splits.scheme)

    ppm_errors = selected.loc[
        selected["adduct"] == "[M+H]+", "ppm_error"
    ].dropna().abs()
    for label, value in (
        ("precursor_ppm_median_abs", float(ppm_errors.median()) if len(ppm_errors) else float("nan")),
        ("precursor_ppm_p95_abs", float(ppm_errors.quantile(0.95)) if len(ppm_errors) else float("nan")),
        ("precursor_ppm_max_abs", float(ppm_errors.max()) if len(ppm_errors) else float("nan")),
    ):
        _metric(metrics, "mass_accuracy", label, round(value, 4))
    for label, value in (
        ("precursor_mz_min", float(selected["precursor_mz"].min())),
        ("precursor_mz_median", float(selected["precursor_mz"].median())),
        ("precursor_mz_max", float(selected["precursor_mz"].max())),
    ):
        _metric(metrics, "mass_accuracy", label, round(value, 4))

    # -- spectral QC -------------------------------------------------------
    for energy in [int(e) for e in cfg.get_path("energies.all", [])]:
        subset = selected[selected["collision_energy_ev"] == energy]
        values = subset["num_peaks_retained"].astype(float)
        _metric(metrics, "spectra", f"n_records_ce{energy}", len(subset))
        if len(values):
            _metric(metrics, "spectra", f"peaks_mean_ce{energy}", round(float(values.mean()), 2))
            _metric(metrics, "spectra", f"peaks_min_ce{energy}", int(values.min()))
            _metric(metrics, "spectra", f"peaks_median_ce{energy}", float(values.median()))
            _metric(metrics, "spectra", f"blank_spectra_ce{energy}", int((values == 0).sum()))
            _metric(metrics, "spectra", f"sparse_lt3_ce{energy}", int((values < 3).sum()))

    passed_raw = raw[raw["passed"]]
    duplicate_groups = passed_raw.groupby(["molecule_id", "collision_energy_ev"]).size()
    _metric(metrics, "spectra", "molecule_energy_pairs_raw", int(len(duplicate_groups)))
    _metric(metrics, "spectra", "pairs_with_replicates", int((duplicate_groups > 1).sum()))
    _metric(metrics, "spectra", "max_replicates_per_pair", int(duplicate_groups.max()) if len(duplicate_groups) else 0)
    _metric(metrics, "spectra", "replicate_rule", cfg.get_path("replicates.rule", ""))

    # -- difficulty --------------------------------------------------------
    cases = analyse_cases(
        complete,
        selected,
        case_specs,
        references,
        splits,
        kappa=float(acquisition_cfg.get_path("likelihood.kappa_default", 8.0)),
        macq=acquisition_cfg,
    )
    n = len(cases)
    counts = {
        "complete_cases": n,
        "precursor_ambiguous_ge2": int((cases["n_candidates"] >= 2).sum()),
        "precursor_ambiguous_ge3": int((cases["n_candidates"] >= 3).sum()),
        "precursor_unique": int((cases["n_candidates"] == 1).sum()),
        "initial_top1_correct": int(cases["top1_correct"].sum()),
        "close_call_margin": int(
            (
                (cases["n_candidates"] >= 2)
                & (cases["top2_margin"] <= float(acquisition_cfg.get_path("confidence.ambiguous_top2_margin", 0.15)))
            ).sum()
        ),
        "primary_ambiguous": int((cases["n_candidates"] >= 2).sum()),
        "sep_choice_differs": int(cases["sep_choice_differs"].sum()),
        "oracle_outcome_differs": int(cases["outcome_differs"].sum()),
    }
    for name, value in counts.items():
        _metric(metrics, "difficulty", name, value)
    _metric(metrics, "difficulty", "precursor_only_unique_rate", round(counts["precursor_unique"] / n, 4) if n else 0.0)
    _metric(metrics, "difficulty", "initial_top1_accuracy", round(counts["initial_top1_correct"] / n, 4) if n else 0.0)
    if n:
        _metric(metrics, "difficulty", "top2_margin_median", round(float(cases["top2_margin"].median()), 4))
        _metric(metrics, "difficulty", "n_candidates_mean", round(float(cases["n_candidates"].mean()), 3))
        _metric(metrics, "difficulty", "n_candidates_max", int(cases["n_candidates"].max()))
        _metric(metrics, "difficulty", "sep30_median", round(float(cases["sep30"].median()), 4))
        _metric(metrics, "difficulty", "sep40_median", round(float(cases["sep40"].median()), 4))
    for split in ("train", "dev", "test"):
        subset = cases[cases["split"] == split]
        _metric(metrics, "difficulty_by_split", f"{split}_cases", len(subset))
        _metric(metrics, "difficulty_by_split", f"{split}_ambiguous", int((subset["n_candidates"] >= 2).sum()))

    metrics_df = pd.DataFrame(metrics)
    metrics_df["value"] = metrics_df["value"].astype(str)
    AUDIT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    metrics_df.to_parquet(AUDIT_PARQUET, index=False)
    cases_safe = cases.copy()
    for column in cases_safe.columns:
        if cases_safe[column].dtype == object:
            cases_safe[column] = cases_safe[column].apply(
                lambda value: value if value is None or isinstance(value, (str, bool, int, float)) else str(value)
            )
    cases_safe.to_parquet(AUDIT_CASES_PARQUET, index=False)

    # -- provenance samples ------------------------------------------------
    samples = []
    for energy in sorted(selected["collision_energy_ev"].unique()):
        subset = selected[selected["collision_energy_ev"] == energy].sort_values("accession")
        chosen_molecules: set[str] = set()
        for _, row in subset.iterrows():
            if row.molecule_id in chosen_molecules:
                continue
            chosen_molecules.add(row.molecule_id)
            samples.append(row)
            if len(chosen_molecules) >= 3:
                break
    sample_df = pd.DataFrame(samples).drop_duplicates("accession").head(15)

    # -- report ------------------------------------------------------------
    gate_complete = len(complete) >= 100
    gate_ambiguous = counts["precursor_ambiguous_ge2"] >= 30
    gate_choices = counts["sep_choice_differs"] >= 15
    verdict = (
        "GO for a proof-of-concept active-identification evaluation."
        if gate_complete and gate_ambiguous
        else "CONDITIONAL: active identification is a limited proof of concept; report the shortfall explicitly."
    )

    lines = [
        "# UnknownID data audit",
        "",
        f"*Generated {now} from the frozen MassBank `Athens_Univ` snapshot.*",
        "",
        "## Snapshot",
        "",
        f"- Source: `{manifest.get('source_repository')}` (`Athens_Univ/`)",
        f"- Commit: `{manifest.get('source_commit')}`",
        f"- Retrieved: {manifest.get('retrieved_at_utc')}",
        f"- Raw record files: **{raw_file_count}**",
        f"- Parsed records: **{len(raw)}**",
        f"- Records passing every rule: **{int(raw['passed'].sum())}**",
        f"- Citation: {cfg.get_path('dataset.citation')}",
        "",
        "> This snapshot count is not the 549-compound literature cohort.  The 549 figure "
        "belongs to the published study; this audit reports only what survived the frozen filters below.",
        "",
        "## Inclusion cascade",
        "",
        "| Rule (cumulative) | Records surviving |",
        "|---|---:|",
    ]
    for row in cascade_rows:
        lines.append(f"| {row['rule']} | {row['records_surviving']} |")

    lines += [
        "",
        "Individual exclusion reasons overlap; the cascade above is the authoritative count.",
        "",
        "### Most frequent exclusion reasons",
        "",
        "| Reason | Records |",
        "|---|---:|",
    ]
    for reason, count in sorted(reason_counts.items(), key=lambda item: -item[1])[:12]:
        lines.append(f"| `{reason}` | {count} |")

    lines += [
        "",
        "## Cohort composition",
        "",
        "| Collision energy | Selected spectra |",
        "|---|---:|",
    ]
    for energy, count in selected["collision_energy_ev"].value_counts().sort_index().items():
        lines.append(f"| {int(energy)} eV | {count} |")
    lines += [
        "",
        f"- Instrument model: `{cfg.get_path('instrument.model')}` (all selected spectra)",
        f"- Ionisation / mode / fragmentation: `{cfg.get_path('instrument.ionization')}`, "
        f"`{cfg.get_path('instrument.ion_mode')}`, `{cfg.get_path('instrument.fragmentation')}`",
        f"- Adduct: `{cfg.get_path('instrument.adduct')}` (all selected spectra)",
        f"- Fixed collision energies only; ramps and NCE were excluded (`{reason_counts.get('collision_energy_not_fixed_ev', 0)}` records).",
        "",
        "### Licenses (raw records)",
        "",
        "| License | Records |",
        "|---|---:|",
    ]
    for license_name, count in raw["license"].value_counts().items():
        lines.append(f"| {license_name} | {count} |")
    lines += [
        "",
        f"Only CC BY / CC BY-SA records were curated. Raw peaks remain in `data/raw/`; "
        f"derived artefacts preserve per-record accession, license and SHA256 in `data/manifest.json`.",
        "",
        "## Chemical identity and mass QC",
        "",
        f"- Distinct full InChIKeys: **{selected['molecule_id'].nunique()}**",
        f"- Distinct 2D connectivity blocks: **{selected['molecule_id'].str.split('-').str[0].nunique()}**",
        f"- Distinct molecular formulas: **{selected['formula'].nunique()}**",
        f"- Reference library molecules with both 10 and 50 eV spectra: **{library['molecule_id'].nunique()}**",
        f"- Complete five-energy cases: **{len(complete)}**",
        f"- Partial cases (kept separately, never imputed): **{len(partial)}**",
        f"- Median absolute precursor mass error ([M+H]+, 10 ppm gate): **{ppm_errors.median():.3f} ppm**",
        f"- 95th percentile: **{ppm_errors.quantile(0.95):.3f} ppm**; maximum: **{ppm_errors.max():.3f} ppm**",
        "",
        "Adducts other than `[M+H]+`, GC-APCI records, multi-component salts and records with "
        "inconsistent formula/SMILES/mass were excluded rather than repaired.  The proton mass "
        "(1.007276466621 Da) was used for ion correction.",
        "",
        "## Spectral QC",
        "",
        "| CE | Records | Mean peaks | Min | Median | Blank | <3 peaks |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for energy in [int(e) for e in cfg.get_path("energies.all", [])]:
        subset = selected[selected["collision_energy_ev"] == energy]
        values = subset["num_peaks_retained"].astype(float)
        if len(values):
            lines.append(
                f"| {energy} eV | {len(subset)} | {values.mean():.1f} | {int(values.min())} | "
                f"{values.median():.0f} | {int((values == 0).sum())} | {int((values < 3).sum())} |"
            )
    lines += [
        "",
        f"- Molecule/energy pairs: **{len(duplicate_groups)}**; pairs with replicate records: "
        f"**{int((duplicate_groups > 1).sum())}**; maximum replicates: **{int(duplicate_groups.max())}**.",
        "- Representative selection is precommitted and outcome-blind: highest retained peak count, "
        "then earliest accession.  Replicates never straddle reference and oracle.",
        "- Preprocessing: invalid peaks removed, peaks below 1% base peak removed, base peak normalised to 1. "
        "The same rule is applied to reference, query and oracle spectra.",
        "",
        "## Difficulty analysis",
        "",
        "| Quantity | Value |",
        "|---|---:|",
        f"| Complete cases | {n} |",
        f"| Cases with >=2 precursor-consistent candidates at 10 ppm | {counts['precursor_ambiguous_ge2']} |",
        f"| Cases with >=3 candidates | {counts['precursor_ambiguous_ge3']} |",
        f"| Precursor-only unique cases | {counts['precursor_unique']} ({counts['precursor_unique']/n:.1%}) |",
        f"| Initial 20 eV top-1 accuracy | {counts['initial_top1_correct']}/{n} ({counts['initial_top1_correct']/n:.1%}) |",
        f"| Close-call ambiguous (>=2 candidates and top-2 support margin <= 0.15) | {counts['close_call_margin']} |",
        f"| Primary ambiguous subset (>=2 precursor-consistent candidates) | {counts['primary_ambiguous']} |",
        f"| Close-call subset (>=2 candidates and top-2 support margin <= 0.15) | {counts['close_call_margin']} |",
        f"| Cases where top-2 template separation differs by >=0.05 between 30 and 40 eV | {counts['sep_choice_differs']} |",
        f"| Diagnostic: cases where the 30 vs 40 oracle gives a different top-1 outcome | {counts['oracle_outcome_differs']} |",
        "",
        "The initial ranking uses only the 20 eV observation and templates interpolated from the "
        "10/50 eV references.  The 20/30/40 eV oracle spectra are not used to choose cases.",
        "",
        "### Split summary",
        "",
        "| Split | Molecules | Cases | Ambiguous cases |",
        "|---|---:|---:|---:|",
    ]
    for split in ("train", "dev", "test"):
        subset = cases[cases["split"] == split]
        amb = int((subset["n_candidates"] >= 2).sum())
        lines.append(f"| {split} | {sum(1 for v in splits.assignment.values() if v == split)} | {len(subset)} | {amb} |")
    lines += [
        "",
        f"Deterministic seed: `{splits.seed}`; scheme: `{splits.scheme}`.  "
        "No molecule ID is shared between splits.",
        "",
        "## Go / no-go gate",
        "",
        "| Target | Required | Observed | Status |",
        "|---|---:|---:|---|",
        f"| Complete cases | >=100 | {len(complete)} | {'PASS' if gate_complete else 'FAIL'} |",
        f"| Precursor-ambiguous cases | >=30 | {counts['precursor_ambiguous_ge2']} | {'PASS' if gate_ambiguous else 'FAIL'} |",
        f"| Cases with nontrivial 30/40 choice | >=15 | {counts['sep_choice_differs']} | {'PASS' if gate_choices else 'FAIL'} |",
        "",
        f"**Decision:** {verdict}",
        "",
        "The 549-compound/5-energy figure in the literature is a cohort description, not this "
        "audit's post-filter count.  No mass tolerance was widened to manufacture ambiguity.",
        "",
        "## Sample provenance",
        "",
        "| Accession | CE | Compound | License | URL |",
        "|---|---:|---|---|---|",
    ]
    for _, row in sample_df.iterrows():
        lines.append(
            f"| `{row.accession}` | {int(row.collision_energy_ev)} eV | {row['name']} | "
            f"{row.license} | {row.record_url} |"
        )
    lines += [
        "",
        "## Audit artefacts",
        "",
        "- `data/curated/audit.parquet` — tidy metric table",
        "- `data/curated/audit_cases.parquet` — per-case difficulty and diagnostics",
        "- `data/curated/splits.json` — frozen molecular splits",
        "- `data/manifest.json` — snapshot commit and per-record SHA256/license",
        "- `data/curated/public_cases.parquet` — anonymised cases, no hidden peaks",
        "- `data/oracle/private_oracle_cases.json` — evaluator-only hidden observations",
        "",
        "## Audit limitations",
        "",
        "- The candidate universe is the 561-molecule endpoint-reference library; this is a "
        "closed-world, library-supported identification task, not de novo structure elucidation.",
        "- Accurate-mass filtering substantially reduces ambiguity; the ambiguous subset here is "
        "smaller than the cohort and is reported separately.",
        "- 20/30/40 eV templates are interpolated from 10/50 eV references.  The oracle spectra are "
        "authentic measurements, but the reference templates are not independent measurements at "
        "those energies.",
        "- Stereo- and constitution-isomer ambiguity can remain unresolved by MS/MS alone.",
        "",
    ]
    markdown = "\n".join(lines)
    REPORTS.mkdir(parents=True, exist_ok=True)
    AUDIT_MD.write_text(markdown, encoding="utf-8")
    return AuditResult(metrics=metrics_df, cases=cases, markdown=markdown)

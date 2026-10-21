"""Case repository and the budgeted investigation session."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from unknownid.core.evidence import EvidenceEvaluator, merge_evidence
from unknownid.core.models import (
    Action,
    Evidence,
    Investigation,
    Plan,
    PublicCase,
    Ranking,
)
from unknownid.core.posterior import (
    rank_candidates,
    top2_margin,
    update_weights,
)
from unknownid.core.retrieve import Candidate, ReferenceStore
from unknownid.core.spectra import ProcessedSpectrum
from unknownid.paths import (
    MANIFEST_JSON,
    ORACLE_DIR,
    PUBLIC_CASES_PARQUET,
)
from unknownid.planner.acquisition import AcquisitionPlanner
from unknownid.planner.error_model import ErrorModel
from unknownid.simulator.oracle import Measurement, OracleAccessError, VirtualInstrument


class CaseRepository:
    def __init__(self, public_cases: pd.DataFrame, references: ReferenceStore):
        self._cases: dict[str, PublicCase] = {}
        self._splits: dict[str, str] = {}
        for _, row in public_cases.iterrows():
            candidate_ids = row["candidate_ids"]
            if isinstance(candidate_ids, np.ndarray):
                candidate_ids = candidate_ids.tolist()
            case = PublicCase(
                case_id=str(row["case_id"]),
                observed_20ev_spectrum={"mz": [], "intensity": []},
                precursor_mz=float(row["precursor_mz"]),
                adduct=str(row.get("adduct", "[M+H]+")),
                instrument_model=str(row.get("instrument_model", "")),
                candidate_ids=[str(c) for c in candidate_ids],
                measurement_budget=int(row.get("measurement_budget", 1)),
                available_energies=[int(e) for e in row.get("available_energies", [30, 40])],
            )
            self._cases[case.case_id] = case
            self._splits[case.case_id] = str(row.get("split", ""))
        self.references = references

    @classmethod
    def load(cls, references: ReferenceStore, path: Path = PUBLIC_CASES_PARQUET) -> CaseRepository:
        return cls(pd.read_parquet(path), references)

    def __len__(self) -> int:
        return len(self._cases)

    def case_ids(self, split: str | None = None) -> list[str]:
        ids = sorted(self._cases)
        if split is None:
            return ids
        return [case_id for case_id in ids if self._splits.get(case_id) == split]

    def split(self, case_id: str) -> str:
        return self._splits.get(case_id, "")

    def has_case(self, case_id: str) -> bool:
        return case_id in self._cases

    def case(self, case_id: str) -> PublicCase:
        return self._cases[case_id]

    def candidates(self, case_id: str) -> list[Candidate]:
        return [self.references.candidate(cid) for cid in self.case(case_id).candidate_ids]


class ActionLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or (ORACLE_DIR / "actions.jsonl"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, entry: dict) -> None:
        payload = {"utc": datetime.now(UTC).isoformat(timespec="milliseconds"), **entry}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")


class InvestigationSession:
    def __init__(
        self,
        case_id: str,
        repository: CaseRepository,
        instrument: VirtualInstrument,
        evaluator: EvidenceEvaluator,
        planner: AcquisitionPlanner,
        error_model: ErrorModel,
        *,
        action_log: ActionLog | None = None,
    ) -> None:
        self.case_id = case_id
        self.repository = repository
        self.instrument = instrument
        self.evaluator = evaluator
        self.planner = planner
        self.error_model = error_model
        self.action_log = action_log or ActionLog()
        self.public_case = repository.case(case_id)
        self.candidates = repository.candidates(case_id)
        self._templates: dict[str, dict[int, ProcessedSpectrum]] = {
            candidate.molecule_id: repository.references.templates(
                candidate.molecule_id, tuple(self.public_case.available_energies) + (20,)
            )
            for candidate in self.candidates
        }
        self._precursors = {c.molecule_id: c.precursor_mz for c in self.candidates}
        self._observations: dict[int, Measurement] = {}
        self._evidence: dict[str, Evidence] = {}
        self._weights: dict[str, float] = {}
        self._actions: list[Action] = []
        self._stopped = False
        self._decision = "ambiguous"
        self._qc: dict = {}

        self._observe(
            self.instrument.start(case_id, budget=self.public_case.measurement_budget), initial=True
        )
        self._initial_weights = dict(self._weights)
        self._initial_order = rank_candidates(self._weights)

    # -- observations ------------------------------------------------------
    def _observe(self, measurement: Measurement, *, initial: bool = False) -> None:
        self._observations[measurement.energy] = measurement
        if initial:
            evidence, weights = self.evaluator.rank(
                measurement.spectrum,
                self.candidates,
                {cid: by_energy[20] for cid, by_energy in self._templates.items()},
                20,
                kappa=self.error_model.kappa(20),
                precursor_mz=self.public_case.precursor_mz,
            )
            self._evidence = {item.candidate_id: item for item in evidence}
            self._weights = weights
        else:
            prior = dict(self._weights)
            arrays = {
                cid: (
                    by_energy[measurement.energy].mz,
                    by_energy[measurement.energy].intensity,
                )
                for cid, by_energy in self._templates.items()
            }
            self._weights = update_weights(
                prior,
                (measurement.spectrum.mz, measurement.spectrum.intensity),
                arrays,
                kappa=self.error_model.kappa(measurement.energy),
                tolerance=self.evaluator.tolerance_da,
                tempering=self.planner.config.tempering,
            )
            merged = merge_evidence(
                self._evidence,
                measurement.spectrum,
                self.candidates,
                {cid: by_energy[measurement.energy] for cid, by_energy in self._templates.items()},
                measurement.energy,
                self.evaluator,
                kappa=self.error_model.kappa(measurement.energy),
                precursor_mz=self.public_case.precursor_mz,
            )
            self._evidence = {item.candidate_id: item for item in merged}
            self._evidence = {
                cid: item.model_copy(update={"weight": self._weights.get(cid, 0.0)})
                for cid, item in self._evidence.items()
            }

    def _ordered_evidence(self) -> list[Evidence]:
        ranked = rank_candidates(self._weights)
        return [self._evidence[cid] for cid in ranked if cid in self._evidence]

    # -- public operations -------------------------------------------------
    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def observed_energies(self) -> list[int]:
        return sorted(self._observations)

    @property
    def remaining_budget(self) -> int:
        return self.instrument.remaining_budget(self.case_id)

    def observation(self, energy: int) -> dict:
        measurement = self._observations[int(energy)]
        return measurement.public_dict()

    def template(self, candidate_id: str, energy: int) -> ProcessedSpectrum:
        """Interpolated reference template; safe to expose (built from 10/50 eV only)."""
        if candidate_id not in self._templates:
            raise KeyError(f"candidate {candidate_id} is not part of case {self.case_id}")
        by_energy = self._templates[candidate_id]
        if int(energy) not in by_energy:
            raise KeyError(f"no {energy} eV template for {candidate_id}")
        return by_energy[int(energy)]

    def ranking(self) -> Ranking:
        return Ranking(
            case_id=self.case_id,
            observations=self.observed_energies,
            evidence=self._ordered_evidence(),
            weights_are_calibrated=False,
        )

    def plan(self) -> Plan:
        plan = self.planner.plan(
            self.case_id,
            weights=self._weights,
            templates=self._templates,
            precursors=self._precursors,
            observed_energies=self.observed_energies,
            remaining_budget=self.remaining_budget,
        )
        return plan

    def measure(self, energy: int) -> Measurement:
        if self._stopped:
            raise OracleAccessError("investigation is already stopped")
        energy = int(energy)
        if energy not in self.public_case.available_energies:
            raise OracleAccessError(
                f"unsupported energy {energy}; allowed {self.public_case.available_energies}"
            )
        # Log the chosen action *before* the reveal.
        self.action_log.write(
            {
                "case_id": self.case_id,
                "kind": "measure",
                "energy_ev": energy,
                "observed_before": self.observed_energies,
                "remaining_budget_before": self.remaining_budget,
            }
        )
        try:
            measurement = self.instrument.measure(self.case_id, energy)
        except Exception as exc:
            self.action_log.write(
                {
                    "case_id": self.case_id,
                    "kind": "measure_rejected",
                    "energy_ev": energy,
                    "error": str(exc),
                }
            )
            raise
        self._actions.append(Action(kind="measure", energy_ev=energy))
        self._observe(measurement)
        return measurement

    def stop(self) -> Investigation:
        if self._stopped:
            return self.investigation()
        self.action_log.write(
            {
                "case_id": self.case_id,
                "kind": "stop",
                "observed_energies": self.observed_energies,
                "remaining_budget": self.remaining_budget,
            }
        )
        self._actions.append(Action(kind="stop"))
        self._stopped = True
        self._decision, self._qc = self._final_decision()
        return self.investigation()

    def investigation(self) -> Investigation:
        top = rank_candidates(self._weights)[0] if self._weights else None
        identified = self._decision == "identified"
        return Investigation(
            case_id=self.case_id,
            observations=self.observed_energies,
            candidate_evidence=self._ordered_evidence(),
            selected_actions=self._actions,
            decision=self._decision if self._stopped else "ambiguous",
            predicted_identity=top if identified else None,
            confidence=(self._weights.get(top) if identified and top else None),
            limitations=self._limitations(),
            qc=self._qc or self.qc_check(),
            provenance=self._provenance(),
        )

    # -- decision ----------------------------------------------------------
    def qc_check(self) -> dict:
        candidates = self.candidates
        precursor = self.public_case.precursor_mz
        checks = {
            "n_candidates": len(candidates),
            "all_candidates_within_ppm": all(
                abs(c.precursor_mz - precursor) / precursor * 1e6
                <= self.repository.references.ppm_tolerance
                for c in candidates
            ),
            "adduct_consistent": all(c.adduct == self.public_case.adduct for c in candidates),
            "measured_energies": self.observed_energies,
            "reference_energies_only": list(self.repository.references.reference_energies),
            "interpolation_method": self.repository.references.template_method,
        }
        reasons = []
        if not checks["all_candidates_within_ppm"]:
            reasons.append("candidate_precursor_outside_tolerance")
        if not checks["adduct_consistent"]:
            reasons.append("adduct_mismatch")
        checks["passed"] = not reasons
        checks["rejection_reasons"] = reasons
        return checks

    def _final_decision(self) -> tuple[str, dict]:
        qc = self.qc_check()
        if not self._weights:
            return "out_of_library", qc
        ordered = rank_candidates(self._weights)
        top = ordered[0]
        top_evidence = self._evidence[top]
        best_similarity = max(top_evidence.similarity_by_energy.values(), default=0.0)
        best_matched = max(top_evidence.matched_peaks_by_energy.values(), default=0)
        support = self._weights[top]
        margin = top2_margin(self._weights)

        min_similarity = float(self._config_value("confidence.identified_min_similarity", 0.30))
        min_support = float(self._config_value("confidence.identified_min_support", 0.72))
        min_margin = float(self._config_value("confidence.identified_min_margin", 0.22))
        min_matched = int(self._config_value("confidence.min_matched_peaks", 2))

        if best_similarity < min_similarity or best_matched < min_matched:
            return "out_of_library", qc

        # Same-connectivity competitors (stereoisomers) cannot be separated by
        # achiral LC-MS/MS.  Abstain rather than over-claim.
        connectivity = top.split("-")[0]
        stereo_competitor = any(
            cid != top and cid.split("-")[0] == connectivity and self._weights.get(cid, 0.0) >= 0.10
            for cid in ordered
        )
        if support >= min_support and margin >= min_margin and not stereo_competitor:
            return "identified", qc
        return "ambiguous", qc

    def _config_value(self, dotted: str, default):
        config = getattr(self, "_confidence_config", None)
        if config is None:
            try:
                from unknownid.config import load_config

                config = load_config("acquisition")
            except Exception:  # pragma: no cover
                config = {}
            self._confidence_config = config
        return config.get_path(dotted, default) if hasattr(config, "get_path") else default

    def _limitations(self) -> list[str]:
        limitations = [
            "Closed-world evaluation: the true compound is assumed to be present in the reference candidate library.",
            "Reference spectra are limited to 10 and 50 eV; 20/30/40 eV templates are interpolated, while query spectra are experimental.",
            "Candidate weights are relative support, not calibrated molecular-identity probabilities.",
            "MS/MS cannot distinguish stereoisomers without additional chromatographic or chiral evidence.",
            "This is known-library identification, not de novo structure elucidation.",
        ]
        if self._stopped and self._decision == "ambiguous":
            limitations.append(
                "The evidence did not satisfy the precommitted identification rule; the result is abstained."
            )
        if self._stopped and self._decision == "out_of_library":
            limitations.append(
                "No candidate produced sufficient matched evidence; the closed-world library is reported as inadequate."
            )
        if self.remaining_budget > 0:
            limitations.append(
                "The investigation stopped before exhausting the measurement budget."
            )
        block = (
            self._evidence.get(rank_candidates(self._weights)[0], None) if self._weights else None
        )
        if block is not None:
            connectivity = block.candidate_id.split("-")[0]
            if any(
                cid.split("-")[0] == connectivity and cid != block.candidate_id
                for cid in self._weights
            ):
                limitations.append(
                    "A same-connectivity (stereoisomer) candidate is present; its MS/MS spectrum may be indistinguishable."
                )
        return limitations

    def _provenance(self) -> dict:
        manifest = {}
        if MANIFEST_JSON.exists():
            manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
        used = {m.accession for m in self._observations.values()}
        used.update(a for c in self.candidates for a in c.reference_accessions.values())
        licenses = {
            r["accession"]: r["license"]
            for r in manifest.get("records", [])
            if r["accession"] in used
        }
        return {
            "optional_scans": max(len(self._observations) - 1, 0),
            "total_acquisitions": len(self._observations),
            "scans_definition": "Optional acquisitions at 30/40 eV; total includes initial 20 eV",
            "licenses_by_accession": licenses,
            "data_license_notice": "MassBank / University of Athens; per-record CC BY / CC BY-SA, see DATA_LICENSE.md",
            "case_id": self.case_id,
            "observed_accessions": {
                str(energy): measurement.accession
                for energy, measurement in sorted(self._observations.items())
            },
            "reference_accessions": {
                candidate.molecule_id: {
                    str(k): v for k, v in candidate.reference_accessions.items()
                }
                for candidate in self.candidates
            },
            "source_commit": manifest.get("source_commit"),
            "source_repository": manifest.get("source_repository"),
            "instrument_model": self.public_case.instrument_model,
            "adduct": self.public_case.adduct,
            "acquisition_method": self.planner.method,
            "error_model_calibrated": bool(self.planner.error_model.calibrated),
            "weights_are_calibrated": False,
            "probability_calibration": "not performed; weights are relative support",
            "template_method": self.repository.references.template_method,
            "match_tolerance_da": self.evaluator.tolerance_da,
            "truth_identity_released": False,
            "note": "Observed 20/30/40 eV accessions are experimental measurements; reference accessions are 10/50 eV library records.",
        }

    # -- export ------------------------------------------------------------
    def export_markdown(self) -> str:
        investigation = self.investigation()
        lines = [
            f"# UnknownID investigation report — {investigation.case_id}",
            "",
            f"**Decision:** `{investigation.decision}`",
            f"**Observed energies:** {', '.join(str(e) + ' eV' for e in investigation.observations)}",
            f"**Predicted identity:** {'`' + investigation.predicted_identity + '`' if investigation.predicted_identity else '—'}",
            "",
            f"**Optional scans:** {investigation.provenance['optional_scans']}",
            f"**Total acquisitions (including initial 20 eV):** {investigation.provenance['total_acquisitions']}",
            "",
            "## Candidate ranking",
            "",
            "| # | candidate | support | cosine by energy | matched peaks | reference accessions |",
            "|---|---|---|---|---|---|",
        ]
        for index, item in enumerate(investigation.candidate_evidence, start=1):
            cosine = ", ".join(
                f"{e} eV: {v:.3f}" for e, v in sorted(item.similarity_by_energy.items())
            )
            matched = ", ".join(
                f"{e} eV: {v}" for e, v in sorted(item.matched_peaks_by_energy.items())
            )
            accessions = ", ".join(
                f"{e} eV {a}" for e, a in sorted(item.reference_accessions.items())
            )
            lines.append(
                f"| {index} | {item.name} (`{item.candidate_id}`) | {item.weight:.3f} | {cosine} | {matched} | {accessions} |"
            )
        lines += [
            "",
            "## Evidence provenance",
            "",
        ]
        for energy, accession in investigation.provenance.get("observed_accessions", {}).items():
            lines.append(f"- **{energy} eV measured observation:** {accession}")
        for cid, accessions in investigation.provenance.get("reference_accessions", {}).items():
            for energy, accession in accessions.items():
                lines.append(
                    f"- **{energy} eV experimental endpoint reference for {cid}:** {accession}"
                )
        lines += ["", "### Data attribution", "", investigation.provenance["data_license_notice"]]
        lines += [
            f"- {accession}: {license}"
            for accession, license in sorted(
                investigation.provenance["licenses_by_accession"].items()
            )
        ]
        lines += ["", "## Limitations", ""]
        lines += [f"- {item}" for item in investigation.limitations]
        lines += [
            "",
            "> Weights are relative support, not calibrated identity probabilities. "
            "MS/MS similarity alone is not proof of molecular identity.",
            "",
        ]
        return "\n".join(lines)

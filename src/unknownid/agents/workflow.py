"""Bounded three-role scientific workflow.

The numerical work remains deterministic and independently testable.  The roles
only summarise, propose and criticise using a fixed tool schema.  No role can
read the oracle, invent a peak, invent a posterior, or execute arbitrary Python.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from unknownid.service import UnknownIDService


class CandidateNote(BaseModel):
    candidate_id: str
    name: str
    formula: str
    support: float
    cosine_by_energy: dict[int, float]
    matched_peaks_by_energy: dict[int, int]
    neutral_loss_agreement: float | None = None
    unexplained_peak_count: int = 0
    reference_accessions: dict[int, str] = Field(default_factory=dict)


class AnalystNote(BaseModel):
    case_id: str
    summary: str
    candidates: list[CandidateNote]
    evidence_labels: dict[str, str]
    warnings: list[str] = Field(default_factory=list)


class ExperimentalistNote(BaseModel):
    case_id: str
    recommendation: Literal["measure", "stop"]
    energy_ev: int | None = None
    predicted_information_gain: float | None = None
    separation: float | None = None
    reliability: float | None = None
    cost: float | None = None
    method: str
    rationale: str
    alternatives: list[dict] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class CriticReport(BaseModel):
    case_id: str
    passed: bool
    decision: str
    claims_allowed: list[str]
    claims_blocked: list[str]
    qc_passed: bool
    qc_reasons: list[str] = Field(default_factory=list)
    provenance_checks: dict[str, bool]
    notes: list[str] = Field(default_factory=list)


class WorkflowOutput(BaseModel):
    analyst: AnalystNote
    experimentalist: ExperimentalistNote
    critic: CriticReport


class ToolError(RuntimeError):
    pass


class BoundedToolRegistry:
    """Fixed, named tools; no arbitrary code execution and no oracle leak."""

    def __init__(self, service: UnknownIDService) -> None:
        self.service = service
        self._tools: dict[str, Callable[..., Any]] = {
            "retrieve_candidates": self._retrieve_candidates,
            "compare_spectra": self._compare_spectra,
            "inspect_fragments": self._inspect_fragments,
            "available_measurements": self._available_measurements,
            "score_acquisitions": self._score_acquisitions,
            "measure": self._measure,
            "qc_check": self._qc_check,
            "report_evidence": self._report_evidence,
            "export_report": self._export_report,
        }

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self._tools:
            raise ToolError(f"tool not allowed: {name}")
        return self._tools[name](**kwargs)

    # -- tools -------------------------------------------------------------
    def _retrieve_candidates(self, case_id: str) -> list[dict]:
        session = self.service.session(case_id)
        return [self.service.references.metadata(cid) for cid in session.public_case.candidate_ids]

    def _compare_spectra(self, case_id: str) -> list[dict]:
        return [item.model_dump() for item in self.service.session(case_id).ranking().evidence]

    def _inspect_fragments(self, case_id: str) -> dict:
        session = self.service.session(case_id)
        ranking = session.ranking()
        if not ranking.evidence:
            return {"matches": [], "unexplained": []}
        top = ranking.evidence[0]
        return {
            "candidate_id": top.candidate_id,
            "matched_fragments": [match.model_dump() for match in top.matched_fragments],
            "unexplained_peaks": top.unexplained_peaks,
            "neutral_loss_agreement": top.neutral_loss_agreement,
        }

    def _available_measurements(self, case_id: str) -> dict:
        return self.service.plan(case_id)

    def _score_acquisitions(self, case_id: str) -> dict:
        return self.service.plan(case_id)

    def _measure(self, case_id: str, energy_ev: int) -> dict:
        # The service enforces policy/budget; this is the only tool that can
        # reveal a hidden observation.
        return self.service.measure(case_id, energy_ev)

    def _qc_check(self, case_id: str) -> dict:
        return self.service.session(case_id).qc_check()

    def _report_evidence(self, case_id: str) -> dict:
        return self.service.session(case_id).investigation().model_dump()

    def _export_report(self, case_id: str) -> str:
        return self.service.session(case_id).export_markdown()


class UnknownIDWorkflow:
    """Agent A (analyst), Agent B (experimentalist), Agent C (critic)."""

    def __init__(self, service: UnknownIDService) -> None:
        self.service = service
        self.tools = BoundedToolRegistry(service)

    def analyst(self, case_id: str) -> AnalystNote:
        session = self.service.session(case_id)
        evidence = session.ranking().evidence
        notes = []
        for item in evidence[:8]:
            notes.append(
                CandidateNote(
                    candidate_id=item.candidate_id,
                    name=item.name,
                    formula=item.formula,
                    support=item.weight,
                    cosine_by_energy=item.similarity_by_energy,
                    matched_peaks_by_energy=item.matched_peaks_by_energy,
                    neutral_loss_agreement=item.neutral_loss_agreement,
                    unexplained_peak_count=len(item.unexplained_peaks),
                    reference_accessions=item.reference_accessions,
                )
            )
        warnings = []
        if len(evidence) > 1 and evidence[0].weight - evidence[1].weight < 0.15:
            warnings.append(
                "Top-2 relative support is close; do not present a confident identity yet."
            )
        if any(
            cid.split("-")[0] == evidence[0].candidate_id.split("-")[0]
            for cid in session.public_case.candidate_ids
            if evidence and cid != evidence[0].candidate_id
        ):
            warnings.append(
                "A same-connectivity (stereoisomer) candidate is present; MS/MS may be blind to it."
            )
        summary = (
            f"{len(evidence)} precursor-consistent candidates; top relative support "
            f"{evidence[0].weight:.3f} for {evidence[0].name}."
            if evidence
            else "No candidate evidence available."
        )
        return AnalystNote(
            case_id=case_id,
            summary=summary,
            candidates=notes,
            evidence_labels={
                "measured": "real archived 20/30/40 eV spectra revealed by the virtual instrument",
                "reference": "static 10/50 eV library spectra",
                "interpolated": "templates constructed from 10/50 eV references",
                "predicted": "hypothetical spectra used only for planning; not observations",
            },
            warnings=warnings,
        )

    def experimentalist(self, case_id: str) -> ExperimentalistNote:
        plan = self.service.session(case_id).plan()
        options = sorted(plan.options, key=lambda option: -option.score)
        recommended = plan.recommended
        rationale = (
            plan.note or "The planner selected the highest reliability-aware expected value."
        )
        if recommended.kind == "measure" and options:
            best = options[0]
            if plan.method == "monte_carlo_ig":
                rationale = (
                    f"Expected information gain {best.predicted_information_gain:.3f} at "
                    f"{best.energy_ev} eV with interpolation reliability {best.reliability:.3f}. "
                    "Hypothetical spectra were sampled from templates; no oracle spectrum was read."
                )
            else:
                rationale = (
                    f"Weighted template separation {best.separation:.3f} at {best.energy_ev} eV "
                    f"discounted by reliability {best.reliability:.3f}. This is a heuristic, "
                    "not a calibrated information gain."
                )
        return ExperimentalistNote(
            case_id=case_id,
            recommendation=recommended.kind,
            energy_ev=recommended.energy_ev,
            predicted_information_gain=recommended.predicted_information_gain,
            separation=options[0].separation if options else None,
            reliability=options[0].reliability if options else None,
            cost=options[0].cost if options else None,
            method=plan.method,
            rationale=rationale,
            alternatives=[
                {
                    "energy_ev": option.energy_ev,
                    "predicted_information_gain": option.predicted_information_gain,
                    "separation": option.separation,
                    "reliability": option.reliability,
                    "score": option.score,
                    "method": option.method,
                }
                for option in options
            ],
            constraints=[
                f"Remaining budget: {plan.remaining_budget}",
                f"Allowed energies: {plan.available_energies}",
                "No hardware control; all observations are archived experimental spectra.",
            ],
        )

    def critic(self, case_id: str) -> CriticReport:
        session = self.service.session(case_id)
        investigation = session.investigation()
        qc = investigation.qc or session.qc_check()
        provenance = investigation.provenance
        provenance_checks = {
            "source_commit_recorded": bool(provenance.get("source_commit")),
            "reference_accessions_recorded": bool(provenance.get("reference_accessions")),
            "observed_accessions_recorded": bool(provenance.get("observed_accessions")),
            "truth_identity_withheld": not bool(provenance.get("truth_identity_released")),
            "weights_not_claimed_calibrated": not bool(provenance.get("weights_are_calibrated")),
        }
        claims_allowed = [
            "ranked known-library candidate structures with relative support",
            "authentic measured spectra at the revealed collision energies",
            "explicit abstention when the precommitted evidence rule is not met",
        ]
        claims_blocked = [
            "de novo structure elucidation",
            "calibrated probability of molecular identity",
            "stereoisomer or enantiomer discrimination without chiral evidence",
            "identification outside the reference library",
            "instrument control or a new physical measurement",
        ]
        notes = []
        if investigation.decision == "identified":
            notes.append(
                "Identification is conditional on the closed-world reference library and admitted evidence."
            )
        else:
            notes.append(f"Decision is `{investigation.decision}`; no identity claim is made.")
        if not qc.get("passed", False):
            notes.append("QC checks failed; the result must not be used as an identification.")
        return CriticReport(
            case_id=case_id,
            passed=bool(qc.get("passed", False)),
            decision=investigation.decision,
            claims_allowed=claims_allowed,
            claims_blocked=claims_blocked,
            qc_passed=bool(qc.get("passed", False)),
            qc_reasons=list(qc.get("rejection_reasons", [])),
            provenance_checks=provenance_checks,
            notes=notes,
        )

    def run(self, case_id: str) -> WorkflowOutput:
        return WorkflowOutput(
            analyst=self.analyst(case_id),
            experimentalist=self.experimentalist(case_id),
            critic=self.critic(case_id),
        )

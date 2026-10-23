"""Typed entities for the SpectraPilot v2 lab."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, Field, field_validator

Status = Literal["IDENTIFIED", "REFERENCE_SUPPORTED", "RANKED_ONLY_MATCH", "MASS_ONLY_MATCH", "AMBIGUOUS", "OUT_OF_LIBRARY", "INSUFFICIENT_DATA"]
ActionKey = Literal["CID40", "EAD16"]


class PeakList(BaseModel):
    mz: list[float]
    intensity: list[float]

    @field_validator("intensity")
    @classmethod
    def _nonnegative(cls, value: list[float]) -> list[float]:
        if any(v < 0 for v in value):
            raise ValueError("intensities must be non-negative")
        return value


@dataclass(frozen=True)
class Candidate:
    molecule_id: str
    name: str
    smiles: str
    formula: str
    exact_mass: float
    precursor_mz: float
    adduct: str
    scaffold: str
    connectivity_key: str
    source_collection: str

    def public_dict(self) -> dict:
        return {
            "candidate_id": self.molecule_id,
            "name": self.name,
            "smiles": self.smiles,
            "formula": self.formula,
            "exact_mass": self.exact_mass,
            "precursor_mz": self.precursor_mz,
            "adduct": self.adduct,
            "scaffold": self.scaffold,
        }


@dataclass(frozen=True)
class Template:
    candidate_id: str
    action: str
    mz: np.ndarray
    intensity: np.ndarray
    source: str
    reliability: float
    n_donors: int
    mean_similarity: float

    @property
    def n_peaks(self) -> int:
        return int(self.mz.size)


@dataclass
class Evidence:
    candidate_id: str
    similarity_by_action: dict[str, float] = field(default_factory=dict)
    matched_peaks_by_action: dict[str, int] = field(default_factory=dict)
    matched_fragments: list[dict[str, float]] = field(default_factory=list)
    unexplained_peaks: list[float] = field(default_factory=list)
    neutral_loss_agreement: float = 0.0
    log_score: float = 0.0
    weight: float = 0.0
    name: str = ""
    formula: str = ""
    smiles: str = ""
    exact_mass: float = 0.0
    precursor_ppm: float = 0.0

    def public_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "formula": self.formula,
            "smiles": self.smiles,
            "exact_mass": self.exact_mass,
            "precursor_ppm": self.precursor_ppm,
            "similarity_by_action": self.similarity_by_action,
            "matched_peaks_by_action": self.matched_peaks_by_action,
            "matched_fragments": self.matched_fragments,
            "unexplained_peaks": self.unexplained_peaks,
            "neutral_loss_agreement": self.neutral_loss_agreement,
            "log_score": self.log_score,
            "weight": self.weight,
        }


@dataclass
class Measurement:
    case_id: str
    action: str
    fragmentation: str
    energy_ev: float
    accession: str
    mz: np.ndarray
    intensity: np.ndarray
    role: str = "measured"

    def public_dict(self, *, include_accession: bool = False) -> dict:
        return {
            "case_id": self.case_id,
            "action": self.action,
            "fragmentation": self.fragmentation,
            "energy_ev": self.energy_ev,
            "mz": self.mz.tolist(),
            "intensity": self.intensity.tolist(),
            "n_peaks": int(self.mz.size),
            "kind": "measured",
            "accession": self.accession if include_accession else None,
        }


class Ranking(BaseModel):
    case_id: str
    observed_actions: list[str]
    candidates: list[dict]
    weights_are_calibrated: bool = False
    note: str = "weights are relative support, not calibrated identity probabilities"


class Plan(BaseModel):
    case_id: str
    observed_actions: list[str]
    available_actions: list[dict]
    remaining_budget: int
    recommended: dict
    options: list[dict]
    method: str
    score_type: Literal["EIG", "HEURISTIC", "NONE"] = "HEURISTIC"
    current_entropy: float = 0.0
    note: str = ""


class Investigation(BaseModel):
    case_id: str
    observed_actions: list[str]
    candidate_evidence: list[dict]
    selected_actions: list[dict]
    decision: Status = "AMBIGUOUS"
    predicted_identity: Optional[str] = None
    confidence: Optional[float] = None
    limitations: list[str] = Field(default_factory=list)
    qc: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict)
    active_peak_exclusions: list[dict] = Field(default_factory=list)
    intervention_history: list[dict] = Field(default_factory=list)
    original_automated_decision: Optional[str] = None
    user_modified_evidence: bool = False
    premeasurement_commit: Optional[dict] = None
    experimental_challenge_result: Optional[dict] = None
    evidence_tier_note: str = ''

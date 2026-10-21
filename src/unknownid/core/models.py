"""Canonical typed entities shared by the pipeline, API and UI.

These mirror the contracts in section 4 of the specification.  Pydantic is used
so that every artefact written to disk and every API payload is validated.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Adduct = Literal["[M+H]+"]


class PeakList(BaseModel):
    mz: list[float]
    intensity: list[float]

    @field_validator("intensity")
    @classmethod
    def _nonnegative(cls, value: list[float]) -> list[float]:
        if any(v < 0 for v in value):
            raise ValueError("intensities must be non-negative")
        return value


class SpectrumRecord(BaseModel):
    """One curated experimental spectrum, normalised to base peak = 1."""

    accession: str
    molecule_id: str  # full InChIKey
    smiles: str
    formula: str
    exact_mass: float
    precursor_mz: float
    adduct: str = "[M+H]+"
    ion_mode: Literal["POSITIVE"] = "POSITIVE"
    instrument_model: str
    instrument_type: str
    fragmentation_mode: Literal["CID"] = "CID"
    collision_energy_ev: int
    mz: list[float]
    intensity: list[float]
    license: str
    source_sha256: str
    is_reference_standard: bool
    name: str = ""
    scaffold: str = ""
    retention_time_min: float | None = None
    source_path: str = ""


class PublicCase(BaseModel):
    """What an agent sees at case start (never contains the source accession)."""

    case_id: str
    observed_20ev_spectrum: PeakList
    precursor_mz: float
    adduct: str = "[M+H]+"
    instrument_model: str
    candidate_ids: list[str]
    measurement_budget: int = 1
    available_energies: list[int] = Field(default_factory=lambda: [30, 40])


class PrivateOracleCase(BaseModel):
    """Evaluator-only.  Never serialised into an agent-facing payload."""

    case_id: str
    true_molecule_id: str
    precursor_mz: float
    split: Literal["train", "dev", "test"]
    hidden_accessions: dict[int, str]
    hidden_spectra: dict[int, PeakList]
    reference_accessions: dict[int, str]


class MatchedPeak(BaseModel):
    observed_mz: float
    template_mz: float
    delta_da: float
    observed_intensity: float
    template_intensity: float


class Evidence(BaseModel):
    candidate_id: str
    similarity_by_energy: dict[int, float]
    matched_peaks_by_energy: dict[int, int]
    matched_fragments: list[MatchedPeak] = Field(default_factory=list)
    unexplained_peaks: list[float] = Field(default_factory=list)
    neutral_loss_agreement: float | None = None
    log_score: float = 0.0
    weight: float = 0.0  # relative support, NOT a calibrated identity probability
    name: str = ""
    formula: str = ""
    smiles: str = ""
    exact_mass: float = 0.0
    precursor_ppm: float = 0.0
    reference_accessions: dict[int, str] = Field(default_factory=dict)
    is_true_identity_visible_to_evaluator: bool = False


class AcquisitionOption(BaseModel):
    energy_ev: int
    predicted_information_gain: float
    separation: float
    reliability: float
    cost: float
    score: float
    method: Literal["monte_carlo_ig", "disagreement_heuristic"]
    note: str = ""


class Action(BaseModel):
    kind: Literal["measure", "stop"]
    energy_ev: int | None = None
    predicted_information_gain: float | None = None

    @field_validator("energy_ev")
    @classmethod
    def _allowed_energy(cls, value: int | None) -> int | None:
        if value is not None and value not in (30, 40):
            raise ValueError("v1 only allows the 30 and 40 eV actions")
        return value


class Ranking(BaseModel):
    case_id: str
    observations: list[int]
    evidence: list[Evidence]
    weights_are_calibrated: bool = False
    note: str = "weights are relative support, not calibrated identity probabilities"


class Plan(BaseModel):
    case_id: str
    observed_energies: list[int]
    available_energies: list[int]
    remaining_budget: int
    recommended: Action
    options: list[AcquisitionOption]
    method: Literal["monte_carlo_ig", "disagreement_heuristic"]
    current_entropy: float
    note: str = ""


class Investigation(BaseModel):
    case_id: str
    observations: list[int]
    candidate_evidence: list[Evidence]
    selected_actions: list[Action]
    decision: Literal["identified", "ambiguous", "out_of_library"] = "ambiguous"
    predicted_identity: str | None = None
    confidence: float | None = None
    limitations: list[str] = Field(default_factory=list)
    qc: dict | None = None
    provenance: dict = Field(default_factory=dict)

"""Typed entities for the SpectraPilot v3 lab.

v3 separates four things that v2 conflated:

* **retrieval** — the ranked candidate list (always produced);
* **identity acceptance** — whether the system claims an identified structure;
* **proof level** — what kind of evidence backs that claim;
* **open-world risk** — an explicit hypothesis that the truth is absent.

`MASS_ONLY_MATCH` is a first-class outcome: a unique precursor-consistent
library hit is a legitimate closed-world *retrieval*, but it is not MS/MS
confirmation and must never be reported as one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Evidence status: the decision contract introduced in v3.
# ---------------------------------------------------------------------------


class EvidenceStatus(str, Enum):
    """What the evidence actually supports.

    ``MASS_ONLY_MATCH``
        A unique precursor-consistent library candidate.  Not MS/MS verified.
    ``MSMS_SUPPORTED``
        Independent, trustworthy spectral evidence supports the reported
        candidate.  Only this status may be described as an MS/MS identification.
    ``AMBIGUOUS``
        Two or more plausible candidates remain; the system abstains.
    ``OUT_OF_LIBRARY``
        A *validated* rejection: reliable evidence contradicts the scoped library.
    ``INSUFFICIENT_DATA``
        Observation or model quality too poor to decide either way.
    """

    MASS_ONLY_MATCH = "MASS_ONLY_MATCH"
    MSMS_SUPPORTED = "MSMS_SUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    OUT_OF_LIBRARY = "OUT_OF_LIBRARY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Legacy literal kept so v2 artefacts and callers keep working.
Status = Literal[
    "IDENTIFIED",
    "MASS_ONLY_MATCH",
    "MSMS_SUPPORTED",
    "AMBIGUOUS",
    "OUT_OF_LIBRARY",
    "INSUFFICIENT_DATA",
]

# Statuses that count as an accepted identity claim, and their proof tier.
ACCEPTED_STATUSES = frozenset(
    {EvidenceStatus.MSMS_SUPPORTED, EvidenceStatus.MASS_ONLY_MATCH}
)

PROOF_TIER = {
    EvidenceStatus.MSMS_SUPPORTED: "msms_supported",
    EvidenceStatus.MASS_ONLY_MATCH: "mass_only",
    EvidenceStatus.AMBIGUOUS: "abstained",
    EvidenceStatus.OUT_OF_LIBRARY: "abstained",
    EvidenceStatus.INSUFFICIENT_DATA: "abstained",
}

# Maps v2 status strings onto v3 statuses for preserved baselines.
LEGACY_STATUS_MAP = {
    "IDENTIFIED": EvidenceStatus.MSMS_SUPPORTED,
    "MASS_ONLY_MATCH": EvidenceStatus.MASS_ONLY_MATCH,
    "MSMS_SUPPORTED": EvidenceStatus.MSMS_SUPPORTED,
    "AMBIGUOUS": EvidenceStatus.AMBIGUOUS,
    "OUT_OF_LIBRARY": EvidenceStatus.OUT_OF_LIBRARY,
    "INSUFFICIENT_DATA": EvidenceStatus.INSUFFICIENT_DATA,
}


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
    # v3 additions: explicit provenance so a CID60 surrogate for a CID40 query is
    # never silently treated as a true conditional prediction.
    expected_energy_ev: float | None = None

    @property
    def n_peaks(self) -> int:
        return int(self.mz.size)

    @property
    def is_experimental(self) -> bool:
        """True when the template is a real measurement, not a prediction."""
        return self.source == "reference_cid60"


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
    # v3: relative support is not a probability; keep them apart on purpose.
    relative_weight: float = 0.0
    estimated_error: float | None = None
    template_sources: dict[str, str] = field(default_factory=dict)
    template_reliability_by_action: dict[str, float] = field(default_factory=dict)
    independent_support_actions: list[str] = field(default_factory=list)
    matched_intensity_by_action: dict[str, float] = field(default_factory=dict)
    unexplained_intensity_by_action: dict[str, float] = field(default_factory=dict)
    subformula_support_by_action: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

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
            "relative_weight": self.relative_weight or self.weight,
            "estimated_error": self.estimated_error,
            "template_sources": self.template_sources,
            "template_reliability_by_action": self.template_reliability_by_action,
            "independent_support_actions": self.independent_support_actions,
            "matched_intensity_by_action": self.matched_intensity_by_action,
            "unexplained_intensity_by_action": self.unexplained_intensity_by_action,
            "subformula_support_by_action": self.subformula_support_by_action,
            "reasons": self.reasons,
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


class RankingResult(BaseModel):
    """Retrieval output.  Distinct from identity acceptance."""

    case_id: str
    observed_actions: list[str]
    candidates: list[dict]
    relative_support_is_calibrated: bool = False
    risk_score: float | None = None
    note: str = (
        "Candidates are ranked by relative support. Unless a calibration report is "
        "present these are not molecular-identity probabilities."
    )


class Ranking(BaseModel):
    case_id: str
    observed_actions: list[str]
    candidates: list[dict]
    weights_are_calibrated: bool = False
    note: str = "weights are relative support, not calibrated identity probabilities"


class FragmentHypothesis(BaseModel):
    """A falsifiable, pre-measurement statement about one diagnostic window.

    The wording is deliberately limited: a fragment formula does not determine a
    bond-cleavage pathway, and a predicted window is a hypothesis until the
    sealed measurement is revealed.
    """

    hypothesis_id: str
    candidate_supported: str
    candidate_challenged: str
    action: str
    fragment_mz_window: tuple[float, float]
    fragment_formula_options: list[str] = Field(default_factory=list)
    predicted_detection_probability: float | None = None
    detected: bool | None = None
    outcome: str | None = None  # supported | contradicted | indeterminate
    provenance: str = "train_only_method_aware_model"
    validity: str = "candidate_discriminating_hypothesis"
    caveats: list[str] = Field(default_factory=list)


class HypothesisSet(BaseModel):
    case_id: str
    top_candidates: list[str]
    initial_action: str = "CID20"
    hypotheses: list[FragmentHypothesis]
    recommended_action: str
    score_type: str = "RELIABILITY_AWARE_HEURISTIC"
    precommit_sha256: str | None = None
    notes: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    case_id: str
    observed_actions: list[str]
    available_actions: list[dict]
    remaining_budget: int
    recommended: dict
    options: list[dict]
    method: str
    score_type: Literal["EIG", "HEURISTIC", "SUPERVISED_RISK_PROXY", "NONE"] = "HEURISTIC"
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
    # v3 additions.
    evidence_status: EvidenceStatus = EvidenceStatus.AMBIGUOUS
    proof_level: str = "abstained"
    accept_identity: bool = False
    status_reasons: list[str] = Field(default_factory=list)
    estimated_error: float | None = None
    unknown_risk: float | None = None
    hypotheses: list[dict] = Field(default_factory=list)
    precommit: dict | None = None
    scorer_version: str = "v2_legacy"
    policy_version: str = "v2_legacy"

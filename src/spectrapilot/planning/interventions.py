"""Auditable edits to observed evidence; never reads a sealed measurement."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from spectrapilot.models import Measurement


class InterventionError(ValueError):
    """An evidence edit was rejected without changing the investigation."""


def validate_reason(reason: str) -> str:
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise InterventionError("reason must be nonblank text of at most 500 characters")
    return reason.strip()


def spectrum_sha256(observation: Measurement) -> str:
    """Hash the original numeric observation, without accession or identity."""
    payload = {
        "case_id": observation.case_id,
        "action": observation.action,
        "fragmentation": observation.fragmentation,
        "energy_ev": observation.energy_ev,
        "mz": observation.mz.tolist(),
        "intensity": observation.intensity.tolist(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class PeakExclusion:
    intervention_id: str
    case_id: str
    action: str
    peak_index: int
    mz: float
    intensity: float
    original_spectrum_sha256: str
    reason: str

    def public_dict(self) -> dict:
        return asdict(self)

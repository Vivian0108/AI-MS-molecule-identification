"""Versioned action schema and helpers."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

ACTION_SPECS = {
    "CID40": {"fragmentation": "CID", "energy_ev": 40},
    "EAD16": {"fragmentation": "EAD", "energy_ev": 16},
}


class MeasurementAction(BaseModel):
    kind: Literal["MEASURE", "STOP"]
    fragmentation: Optional[Literal["CID", "EAD"]] = None
    energy_ev: Optional[float] = None
    polarity: Literal["POSITIVE"] = "POSITIVE"
    adduct: str = "[M+H]+"
    estimated_cost: float = 1.0
    policy_score: Optional[float] = None
    score_type: Literal["EIG", "HEURISTIC", "NONE"] = "NONE"

    @model_validator(mode="after")
    def _check_shape(self):
        if self.kind == "STOP":
            if self.fragmentation is not None or self.energy_ev is not None:
                raise ValueError("STOP actions must not specify a measurement")
            return self
        if self.fragmentation is None or self.energy_ev is None:
            raise ValueError("MEASURE actions require fragmentation and energy_ev")
        if self.fragmentation == "CID" and int(self.energy_ev) != 40:
            raise ValueError("the v2 CID action is fixed to 40 eV")
        if self.fragmentation == "EAD" and int(self.energy_ev) != 16:
            raise ValueError("the v2 EAD action is fixed to 16 eV")
        return self

    @property
    def key(self) -> str:
        if self.kind == "STOP":
            return "STOP"
        return f"{self.fragmentation}{int(self.energy_ev)}"

    def public_dict(self) -> dict:
        return {
            "kind": self.kind,
            "fragmentation": self.fragmentation,
            "energy_ev": self.energy_ev,
            "polarity": self.polarity,
            "adduct": self.adduct,
            "estimated_cost": self.estimated_cost,
            "policy_score": self.policy_score,
            "score_type": self.score_type,
            "key": self.key,
        }

    @classmethod
    def for_key(
        cls,
        key: str,
        *,
        estimated_cost: float = 1.0,
        policy_score: float | None = None,
        score_type: Literal["EIG", "HEURISTIC", "NONE"] = "NONE",
    ) -> "MeasurementAction":
        if key == "STOP":
            return cls(kind="STOP")
        spec = ACTION_SPECS[key]
        return cls(
            kind="MEASURE",
            fragmentation=spec["fragmentation"],
            energy_ev=spec["energy_ev"],
            estimated_cost=estimated_cost,
            policy_score=policy_score,
            score_type=score_type,
        )


def stop_action() -> MeasurementAction:
    return MeasurementAction(kind="STOP", score_type="NONE")

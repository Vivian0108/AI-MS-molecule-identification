"""Budgeted next-experiment selection.

Two policies are implemented:

* ``monte_carlo_ig`` — the expected-information-gain approximation from the
  specification.  Hypothetical spectra are sampled from interpolated candidate
  templates plus a train-fitted noise model.  The hidden oracle is never read.
* ``disagreement_heuristic`` — weighted pairwise template separation discounted
  by held-out interpolation reliability.  It is *not* information gain and is
  labelled as a heuristic everywhere it surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from unknownid.core.models import AcquisitionOption, Action, Plan
from unknownid.core.posterior import (
    entropy,
    rank_candidates,
    top2_margin,
    update_weights,
)
from unknownid.core.spectra import ProcessedSpectrum, cosine_greedy
from unknownid.planner.error_model import ErrorModel

STOP_NOTE = "no measurement expected to reduce uncertainty enough to justify the cost"


@dataclass
class PlannerConfig:
    budget: int = 1
    allowed_energies: Sequence[int] = (30, 40)
    cost: float = 1.0
    monte_carlo_samples: int = 500
    seed: int = 20261020
    tempering: float = 0.85
    stop_ig_threshold: float = 0.02
    stop_heuristic_threshold: float = 0.01
    identified_min_support: float = 0.72
    identified_min_margin: float = 0.22
    stop_min_support: float = 0.90
    stop_min_margin: float = 0.70
    tolerance_da: float = 0.02
    max_candidates: int = 12


class AcquisitionPlanner:
    def __init__(
        self,
        config: PlannerConfig,
        *,
        method: str = "auto",
        error_model: ErrorModel | None = None,
    ) -> None:
        self.config = config
        self.error_model = error_model or ErrorModel()
        if method == "auto":
            self.method = (
                "monte_carlo_ig"
                if self.error_model.can_use_monte_carlo()
                else "disagreement_heuristic"
            )
        else:
            self.method = method
        if self.method not in {"monte_carlo_ig", "disagreement_heuristic"}:
            raise ValueError(f"unknown acquisition method: {method}")

    # -- public ------------------------------------------------------------
    def plan(
        self,
        case_id: str,
        *,
        weights: Mapping[str, float],
        templates: Mapping[str, Mapping[int, ProcessedSpectrum]],
        precursors: Mapping[str, float],
        observed_energies: Sequence[int],
        remaining_budget: int,
    ) -> Plan:
        observed = sorted(int(e) for e in observed_energies)
        available = [
            int(e)
            for e in self.config.allowed_energies
            if int(e) not in observed and int(e) in _energies_in(templates)
        ]
        current_entropy = entropy(weights)

        if remaining_budget <= 0 or not available:
            return self._stop_plan(
                case_id,
                observed,
                available,
                remaining_budget,
                current_entropy,
                note="budget exhausted"
                if remaining_budget <= 0
                else "no unobserved energy available",
            )
        if len(weights) <= 1:
            return self._stop_plan(
                case_id,
                observed,
                available,
                remaining_budget,
                current_entropy,
                note="a single candidate remains; no acquisition can distinguish identities",
            )

        options = self._score_options(
            weights=weights,
            templates=templates,
            precursors=precursors,
            energies=available,
        )
        options.sort(key=lambda option: (-option.score, option.energy_ev))
        best = options[0]

        resolved = (
            max(weights.values()) >= self.config.stop_min_support
            and top2_margin(weights) >= self.config.stop_min_margin
        )
        if resolved:
            return self._stop_plan(
                case_id,
                observed,
                available,
                remaining_budget,
                current_entropy,
                note="shortlist already resolved under the precommitted confidence rule",
                options=options,
            )
        if (
            self.method == "monte_carlo_ig"
            and best.predicted_information_gain <= self.config.stop_ig_threshold
        ):
            return self._stop_plan(
                case_id,
                observed,
                available,
                remaining_budget,
                current_entropy,
                note=STOP_NOTE,
                options=options,
            )
        if (
            self.method == "disagreement_heuristic"
            and best.score <= self.config.stop_heuristic_threshold
        ):
            return self._stop_plan(
                case_id,
                observed,
                available,
                remaining_budget,
                current_entropy,
                note=STOP_NOTE,
                options=options,
            )

        action = Action(
            kind="measure",
            energy_ev=best.energy_ev,
            predicted_information_gain=best.predicted_information_gain,
        )
        return Plan(
            case_id=case_id,
            observed_energies=observed,
            available_energies=available,
            remaining_budget=remaining_budget,
            recommended=action,
            options=options,
            method=self.method,
            current_entropy=current_entropy,
            note=self._method_note(),
        )

    # -- internals ---------------------------------------------------------
    def rank_options(
        self,
        *,
        weights: Mapping[str, float],
        templates: Mapping[str, Mapping[int, ProcessedSpectrum]],
        precursors: Mapping[str, float],
        energies: Sequence[int],
    ) -> list[AcquisitionOption]:
        """Public diagnostic: score every allowed energy without taking an action."""
        return sorted(
            self._score_options(
                weights=weights,
                templates=templates,
                precursors=precursors,
                energies=energies,
            ),
            key=lambda option: (-option.score, option.energy_ev),
        )

    def _method_note(self) -> str:
        if self.method == "monte_carlo_ig":
            return (
                "Expected information gain estimated by Monte Carlo; noise model "
                "fitted on train identities only and validated on dev."
            )
        return "Reliability-aware template-disagreement heuristic; not calibrated information gain."

    def _stop_plan(
        self,
        case_id: str,
        observed: list[int],
        available: list[int],
        remaining_budget: int,
        current_entropy: float,
        *,
        note: str,
        options: list[AcquisitionOption] | None = None,
    ) -> Plan:
        return Plan(
            case_id=case_id,
            observed_energies=observed,
            available_energies=available,
            remaining_budget=max(remaining_budget, 0),
            recommended=Action(kind="stop"),
            options=options or [],
            method=self.method,
            current_entropy=current_entropy,
            note=note,
        )

    def _score_options(
        self,
        *,
        weights: Mapping[str, float],
        templates: Mapping[str, Mapping[int, ProcessedSpectrum]],
        precursors: Mapping[str, float],
        energies: Sequence[int],
    ) -> list[AcquisitionOption]:
        ranked = rank_candidates(weights)[: self.config.max_candidates]
        weights = {cid: weights[cid] for cid in ranked if cid in templates}
        total = sum(weights.values()) or 1.0
        weights = {cid: value / total for cid, value in weights.items()}
        rng = np.random.default_rng(self.config.seed)

        options: list[AcquisitionOption] = []
        for energy in energies:
            usable = [
                cid
                for cid in weights
                if energy in templates[cid] and templates[cid][energy].mz.size > 0
            ]
            if len(usable) < 2:
                continue
            separation = self._weighted_separation(weights, templates, energy)
            reliability = float(self.error_model.reliability.get(energy, 0.0))

            if self.method == "monte_carlo_ig":
                ig = self._monte_carlo_ig(weights, templates, precursors, energy, rng)
                option = AcquisitionOption(
                    energy_ev=int(energy),
                    predicted_information_gain=float(max(ig, 0.0)),
                    separation=float(separation),
                    reliability=reliability,
                    cost=self.config.cost,
                    score=float(max(ig, 0.0) / max(self.config.cost, 1e-9)),
                    method="monte_carlo_ig",
                    note="IG estimated over hypothetical sampled spectra; not oracle peaks",
                )
            else:
                proxy = separation * reliability
                option = AcquisitionOption(
                    energy_ev=int(energy),
                    predicted_information_gain=0.0,
                    separation=float(separation),
                    reliability=reliability,
                    cost=self.config.cost,
                    score=float(proxy / max(self.config.cost, 1e-9)),
                    method="disagreement_heuristic",
                    note="separation x reliability; not a calibrated IG estimate",
                )
            options.append(option)
        return options

    def _weighted_separation(
        self,
        weights: Mapping[str, float],
        templates: Mapping[str, Mapping[int, ProcessedSpectrum]],
        energy: int,
    ) -> float:
        ids = [cid for cid in weights if energy in templates[cid]]
        value = 0.0
        for i, first in enumerate(ids):
            for second in ids[i + 1 :]:
                a = templates[first][energy]
                b = templates[second][energy]
                cosine, _ = cosine_greedy(
                    a.mz, a.intensity, b.mz, b.intensity, self.config.tolerance_da
                )
                value += weights[first] * weights[second] * (1.0 - max(min(cosine, 1.0), 0.0))
        return float(value)

    def _monte_carlo_ig(
        self,
        weights: Mapping[str, float],
        templates: Mapping[str, Mapping[int, ProcessedSpectrum]],
        precursors: Mapping[str, float],
        energy: int,
        rng: np.random.Generator,
    ) -> float:
        h0 = entropy(weights)
        ids = [cid for cid in weights if energy in templates[cid]]
        probs = np.array([weights[cid] for cid in ids], float)
        if probs.sum() <= 0:
            return 0.0
        probs = probs / probs.sum()
        template_arrays = {
            cid: (templates[cid][energy].mz, templates[cid][energy].intensity) for cid in ids
        }
        entropies: list[float] = []
        for _ in range(self.config.monte_carlo_samples):
            draw = int(rng.choice(len(ids), p=probs))
            sampled_id = ids[draw]
            hypothetical = self.error_model.sample(
                templates[sampled_id][energy],
                energy,
                rng,
                precursor_mz=precursors.get(sampled_id, 500.0),
            )
            updated = update_weights(
                weights,
                (hypothetical.mz, hypothetical.intensity),
                template_arrays,
                kappa=self.error_model.kappa(energy),
                tolerance=self.config.tolerance_da,
                tempering=self.config.tempering,
            )
            entropies.append(entropy(updated))
        return float(max(h0 - float(np.mean(entropies)), 0.0))


def _energies_in(templates: Mapping[str, Mapping[int, ProcessedSpectrum]]) -> set[int]:
    energies: set[int] = set()
    for by_energy in templates.values():
        energies.update(int(e) for e in by_energy)
    return energies

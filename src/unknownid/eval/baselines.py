"""Held-out policies and the shared evaluation episode.

All policies receive the same initial 20 eV observation and candidate universe.
Only the adaptive policy consults :class:`AcquisitionPlanner`; the planner never
sees the oracle spectra or the true identity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from unknownid.core.evidence import EvidenceEvaluator, merge_evidence
from unknownid.core.ids import make_case_id
from unknownid.core.models import Evidence
from unknownid.core.posterior import entropy, rank_candidates, update_weights
from unknownid.core.retrieve import Candidate, ReferenceStore
from unknownid.core.spectra import ProcessedSpectrum, preprocess_peaks
from unknownid.planner.acquisition import AcquisitionPlanner, PlannerConfig
from unknownid.planner.error_model import ErrorModel

POLICY_NAMES = [
    "precursor_only",
    "single_scan",
    "always_30",
    "always_40",
    "random",
    "cheap_disagreement",
    "unknownid",
    "oracle_best_action",
]


@dataclass
class EvalCase:
    case_id: str
    molecule_id: str
    split: str
    precursor_mz: float
    candidate_ids: list[str]
    observations: dict[int, ProcessedSpectrum]
    candidates: list[Candidate] = field(default_factory=list)
    templates: dict[str, dict[int, ProcessedSpectrum]] = field(default_factory=dict)

    @property
    def n_candidates(self) -> int:
        return len(self.candidate_ids)


@dataclass
class Snapshot:
    stage: int
    weights: dict[str, float]
    evidence: dict[str, Evidence]
    actions: list[int]
    entropy: float

    def order(self) -> list[str]:
        return rank_candidates(self.weights)


def load_eval_cases(
    *,
    references: ReferenceStore,
    public_cases_path,
    oracle_path,
    split: str | None = None,
) -> list[EvalCase]:
    public = pd.read_parquet(public_cases_path)
    oracle = json.loads(open(oracle_path, encoding="utf-8").read())
    cases: list[EvalCase] = []
    for _, row in public.iterrows():
        case_id = str(row["case_id"])
        private = oracle.get(case_id)
        if private is None:
            raise KeyError(f"missing private oracle for {case_id}")
        if split is not None and private.get("split") != split:
            continue
        candidate_ids = row["candidate_ids"]
        if isinstance(candidate_ids, np.ndarray):
            candidate_ids = candidate_ids.tolist()
        observations = {
            int(energy): preprocess_peaks(
                payload["mz"], payload["intensity"], rel_floor=0.0
            )
            for energy, payload in private["hidden_spectra"].items()
        }
        candidates = [references.candidate(cid) for cid in candidate_ids]
        templates = {
            cid: references.templates(cid, (20, 30, 40)) for cid in candidate_ids
        }
        cases.append(
            EvalCase(
                case_id=case_id,
                molecule_id=private["true_molecule_id"],
                split=private.get("split", ""),
                precursor_mz=float(row["precursor_mz"]),
                candidate_ids=[str(c) for c in candidate_ids],
                observations=observations,
                candidates=candidates,
                templates=templates,
            )
        )
    return cases


class PolicyState:
    """Mutable evidence state for one policy run.  No truth and no oracle."""

    def __init__(
        self,
        case: EvalCase,
        *,
        references: ReferenceStore,
        evaluator: EvidenceEvaluator,
        error_model: ErrorModel,
        tempering: float = 0.85,
    ) -> None:
        self.case = case
        self.references = references
        self.evaluator = evaluator
        self.error_model = error_model
        self.tempering = tempering
        self.weights: dict[str, float] = {}
        self.evidence: dict[str, Evidence] = {}
        self.actions: list[int] = []
        self.snapshots: list[Snapshot] = []
        self._initialise()

    def _initialise(self) -> None:
        observed = self.case.observations[20]
        templates20 = {cid: self.case.templates[cid][20] for cid in self.case.candidate_ids}
        evidence, weights = self.evaluator.rank(
            observed,
            self.case.candidates,
            templates20,
            20,
            kappa=self.error_model.kappa(20),
            precursor_mz=self.case.precursor_mz,
        )
        self.weights = dict(weights)
        self.evidence = {item.candidate_id: item for item in evidence}
        self.snapshots = [
            Snapshot(
                stage=0,
                weights=dict(self.weights),
                evidence=dict(self.evidence),
                actions=[],
                entropy=entropy(self.weights),
            )
        ]

    def set_precursor_only(self) -> None:
        scores = {}
        for candidate in self.case.candidates:
            ppm = abs(candidate.precursor_mz - self.case.precursor_mz) / self.case.precursor_mz * 1e6
            scores[candidate.molecule_id] = -ppm
        maximum = max(scores.values())
        exp = {key: float(np.exp(value - maximum)) for key, value in scores.items()}
        total = sum(exp.values()) or 1.0
        self.weights = {key: value / total for key, value in exp.items()}
        for item in self.evidence.values():
            item.weight = self.weights.get(item.candidate_id, 0.0)
        self.snapshots[0] = Snapshot(
            stage=0,
            weights=dict(self.weights),
            evidence=dict(self.evidence),
            actions=[],
            entropy=entropy(self.weights),
        )

    def measure(self, energy: int) -> None:
        energy = int(energy)
        if energy in self.actions:
            raise ValueError(f"energy {energy} already measured in this run")
        spectrum = self.case.observations[energy]
        arrays = {
            cid: (self.case.templates[cid][energy].mz, self.case.templates[cid][energy].intensity)
            for cid in self.case.candidate_ids
        }
        self.weights = update_weights(
            self.weights,
            (spectrum.mz, spectrum.intensity),
            arrays,
            kappa=self.error_model.kappa(energy),
            tolerance=self.references.tolerance_da,
            tempering=self.tempering,
        )
        merged = merge_evidence(
            self.evidence,
            spectrum,
            self.case.candidates,
            {cid: self.case.templates[cid][energy] for cid in self.case.candidate_ids},
            energy,
            self.evaluator,
            kappa=self.error_model.kappa(energy),
            precursor_mz=self.case.precursor_mz,
        )
        self.evidence = {
            item.candidate_id: item.model_copy(
                update={"weight": self.weights.get(item.candidate_id, 0.0)}
            )
            for item in merged
        }
        self.actions.append(energy)
        self.snapshots.append(
            Snapshot(
                stage=len(self.actions),
                weights=dict(self.weights),
                evidence=dict(self.evidence),
                actions=list(self.actions),
                entropy=entropy(self.weights),
            )
        )

    def stage(self, index: int) -> Snapshot:
        return self.snapshots[min(max(index, 0), len(self.snapshots) - 1)]


# -- policies --------------------------------------------------------------
class Policy:
    name = "base"

    def run(self, state: PolicyState, *, budget: int, rng: np.random.Generator | None = None) -> None:
        raise NotImplementedError


class PrecursorOnly(Policy):
    name = "precursor_only"

    def run(self, state, *, budget, rng=None):
        state.set_precursor_only()


class SingleScan(Policy):
    name = "single_scan"

    def run(self, state, *, budget, rng=None):
        return


class FixedEnergy(Policy):
    def __init__(self, energy: int):
        self.energy = int(energy)
        self.name = f"always_{energy}"

    def run(self, state, *, budget, rng=None):
        order = [self.energy] + [e for e in (30, 40) if e != self.energy]
        for energy in order[:budget]:
            state.measure(energy)


class RandomPolicy(Policy):
    name = "random"

    def run(self, state, *, budget, rng=None):
        rng = rng or np.random.default_rng(0)
        available = [30, 40]
        for _ in range(budget):
            remaining = [e for e in available if e not in state.actions]
            if not remaining:
                break
            state.measure(int(rng.choice(remaining)))


class CheapDisagreement(Policy):
    name = "cheap_disagreement"

    def __init__(self, planner: AcquisitionPlanner):
        self.planner = planner

    def run(self, state, *, budget, rng=None):
        for _ in range(budget):
            remaining = [e for e in (30, 40) if e not in state.actions]
            if not remaining:
                break
            options = self.planner.rank_options(
                weights=state.weights,
                templates=state.case.templates,
                precursors={c.molecule_id: c.precursor_mz for c in state.case.candidates},
                energies=remaining,
            )
            if not options:
                break
            state.measure(options[0].energy_ev)


class UnknownIDPolicy(Policy):
    name = "unknownid"

    def __init__(self, planner: AcquisitionPlanner):
        self.planner = planner

    def run(self, state, *, budget, rng=None):
        for _ in range(budget):
            plan = self.planner.plan(
                state.case.case_id,
                weights=state.weights,
                templates=state.case.templates,
                precursors={c.molecule_id: c.precursor_mz for c in state.case.candidates},
                observed_energies=[20] + state.actions,
                remaining_budget=budget - len(state.actions),
            )
            if plan.recommended.kind != "measure" or plan.recommended.energy_ev is None:
                break
            state.measure(int(plan.recommended.energy_ev))


class OracleBestAction(Policy):
    """Diagnostic ceiling only; requires truth to choose between 30 and 40."""

    name = "oracle_best_action"

    def __init__(self, truth: str):
        self.truth = truth

    def run(self, state, *, budget, rng=None):
        for energy in (30, 40):
            state.measure(energy)
        # Choose the revealed branch with the best truth-aware outcome.
        branches = [
            snapshot for snapshot in state.snapshots if snapshot.actions and len(snapshot.actions) == 1
        ]
        if branches:
            chosen = max(
                branches,
                key=lambda snapshot: (
                    int(snapshot.order()[0] == self.truth),
                    snapshot.weights.get(self.truth, 0.0),
                ),
            )
            state.weights = dict(chosen.weights)
            state.evidence = dict(chosen.evidence)
            state.actions = list(chosen.actions)
            state.snapshots = [state.snapshots[0], chosen]


def default_policies(
    planner: AcquisitionPlanner,
    *,
    truth: str,
) -> list[Policy]:
    return [
        PrecursorOnly(),
        SingleScan(),
        FixedEnergy(30),
        FixedEnergy(40),
        RandomPolicy(),
        CheapDisagreement(planner),
        UnknownIDPolicy(planner),
        OracleBestAction(truth),
    ]

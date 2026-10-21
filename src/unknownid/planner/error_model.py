"""Empirical observation-error model.

Fitted *only* on train identities at 20/30/40 eV.  The model is used for two
things:

1. Monte-Carlo simulation of hypothetical future spectra for information-gain
   planning.  Sampled spectra come from interpolated templates + learned noise,
   never from the hidden test oracle.
2. A tempered cosine likelihood ``exp(kappa_e * cos)`` used when a real
   measurement is revealed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

from unknownid.core.posterior import softmax
from unknownid.core.retrieve import ReferenceStore
from unknownid.core.spectra import (
    ProcessedSpectrum,
    cosine_greedy,
    matched_peaks,
    preprocess_peaks,
)


@dataclass
class TrainingObservation:
    molecule_id: str
    energy: int
    spectrum: ProcessedSpectrum


@dataclass
class EnergyNoise:
    n: int = 0
    mean_cosine: float = 0.0
    median_cosine: float = 0.0
    kappa: float = 8.0
    mz_sigma: float = 0.003
    intensity_log_sigma: float = 0.45
    dropout_prob: float = 0.25
    spurious_fraction: float = 0.15
    spurious_pool: list[float] = field(default_factory=list)  # m/z / precursor
    calibrated: bool = False

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "mean_cosine": self.mean_cosine,
            "median_cosine": self.median_cosine,
            "kappa": self.kappa,
            "mz_sigma": self.mz_sigma,
            "intensity_log_sigma": self.intensity_log_sigma,
            "dropout_prob": self.dropout_prob,
            "spurious_fraction": self.spurious_fraction,
            "spurious_pool": self.spurious_pool,
            "calibrated": self.calibrated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EnergyNoise:
        return cls(**data)


class ErrorModel:
    def __init__(self, by_energy: dict[int, EnergyNoise] | None = None) -> None:
        self.by_energy = by_energy or {energy: EnergyNoise() for energy in (20, 30, 40)}

    @property
    def reliability(self) -> dict[int, float]:
        return {energy: max(noise.mean_cosine, 0.0) for energy, noise in self.by_energy.items()}

    def kappa(self, energy: int) -> float:
        return self.by_energy[int(energy)].kappa

    @property
    def calibrated(self) -> bool:
        return all(noise.calibrated for noise in self.by_energy.values())

    def can_use_monte_carlo(self) -> bool:
        return all(self.by_energy[e].calibrated and self.by_energy[e].n >= 10 for e in (20, 30, 40))

    # -- fitting -----------------------------------------------------------
    @classmethod
    def fit(
        cls,
        observations: Iterable[TrainingObservation],
        references: ReferenceStore,
        *,
        kappa_bounds: tuple[float, float] = (0.5, 40.0),
        min_cases: int = 10,
    ) -> ErrorModel:
        observations = list(observations)
        frames: dict[int, list[TrainingObservation]] = {}
        for obs in observations:
            frames.setdefault(int(obs.energy), []).append(obs)
        by_molecule_20 = {obs.molecule_id: obs for obs in frames.get(20, [])}

        model = cls()
        noise20 = model._fit_energy(
            frames.get(20, []),
            references,
            by_molecule_20=None,
            prior_kappa=None,
            kappa_bounds=kappa_bounds,
            min_cases=min_cases,
        )
        model.by_energy[20] = noise20
        for energy in (30, 40):
            model.by_energy[energy] = model._fit_energy(
                frames.get(energy, []),
                references,
                by_molecule_20=by_molecule_20,
                prior_kappa=noise20.kappa,
                kappa_bounds=kappa_bounds,
                min_cases=min_cases,
            )
        return model

    def _fit_energy(
        self,
        observations: Sequence[TrainingObservation],
        references: ReferenceStore,
        *,
        by_molecule_20: Mapping[str, TrainingObservation] | None,
        prior_kappa: float | None,
        kappa_bounds: tuple[float, float],
        min_cases: int,
    ) -> EnergyNoise:
        if len(observations) < min_cases:
            return EnergyNoise(n=len(observations), calibrated=False)

        cosines: list[float] = []
        mz_deltas: list[float] = []
        log_ratios: list[float] = []
        template_counts: list[int] = []
        unmatched_counts: list[int] = []
        spurious_pool: list[float] = []
        cases: list[tuple[dict[str, float], dict[str, float], str]] = []

        for obs in observations:
            candidate = references.candidate(obs.molecule_id)
            template = references.template(obs.molecule_id, obs.energy)
            cosine, _ = cosine_greedy(
                obs.spectrum.mz,
                obs.spectrum.intensity,
                template.mz,
                template.intensity,
                references.tolerance_da,
            )
            cosines.append(cosine)
            matches = matched_peaks(
                obs.spectrum.mz,
                obs.spectrum.intensity,
                template.mz,
                template.intensity,
                references.tolerance_da,
            )
            matched_template_mz = {round(float(m["template_mz"]), 6) for m in matches}
            template_counts.append(int(template.mz.size))
            unmatched_counts.append(int(template.mz.size) - len(matches))
            for match in matches:
                mz_deltas.append(abs(float(match["delta_da"])))
                if match["observed_intensity"] > 0 and match["template_intensity"] > 0:
                    log_ratios.append(
                        float(np.log(match["observed_intensity"] / match["template_intensity"]))
                    )
            for mz in obs.spectrum.mz:
                if round(float(mz), 6) not in matched_template_mz:
                    spurious_pool.append(float(mz) / candidate.precursor_mz)

            candidates = references.candidates_within_ppm(candidate.precursor_mz)
            cos_e = {
                c.molecule_id: cosine_greedy(
                    obs.spectrum.mz,
                    obs.spectrum.intensity,
                    references.template(c.molecule_id, obs.energy).mz,
                    references.template(c.molecule_id, obs.energy).intensity,
                    references.tolerance_da,
                )[0]
                for c in candidates
            }
            if (
                prior_kappa is None
                or by_molecule_20 is None
                or obs.molecule_id not in by_molecule_20
            ):
                prior = {c.molecule_id: 1.0 / len(candidates) for c in candidates}
            else:
                obs20 = by_molecule_20[obs.molecule_id]
                cos20 = {
                    c.molecule_id: cosine_greedy(
                        obs20.spectrum.mz,
                        obs20.spectrum.intensity,
                        references.template(c.molecule_id, 20).mz,
                        references.template(c.molecule_id, 20).intensity,
                        references.tolerance_da,
                    )[0]
                    for c in candidates
                }
                prior = softmax({k: prior_kappa * v for k, v in cos20.items()}, 1.0)
            cases.append((prior, cos_e, obs.molecule_id))

        def nll(kappa: float) -> float:
            total = 0.0
            for prior, cos_e, true_id in cases:
                maximum = max(kappa * value for value in cos_e.values())
                denom = sum(
                    prior.get(cid, 1e-12) * np.exp(kappa * value - maximum)
                    for cid, value in cos_e.items()
                )
                numerator = prior.get(true_id, 1e-12) * np.exp(kappa * cos_e[true_id] - maximum)
                total -= float(np.log(max(numerator / max(denom, 1e-300), 1e-12)))
            return total / max(len(cases), 1)

        result = minimize_scalar(
            nll, bounds=kappa_bounds, method="bounded", options={"xatol": 1e-3}
        )
        kappa = float(result.x) if result.success else 8.0

        dropout = float(np.sum(unmatched_counts) / max(np.sum(template_counts), 1))
        mz_sigma = float(1.4826 * np.median(np.abs(mz_deltas)) if mz_deltas else 0.003)
        mz_sigma = max(min(mz_sigma, 0.02), 0.0005)
        intensity_sigma = float(min(max(np.std(log_ratios), 0.15), 1.5) if log_ratios else 0.45)
        return EnergyNoise(
            n=len(observations),
            mean_cosine=float(np.mean(cosines)),
            median_cosine=float(np.median(cosines)),
            kappa=max(min(kappa, kappa_bounds[1]), kappa_bounds[0]),
            mz_sigma=mz_sigma,
            intensity_log_sigma=intensity_sigma,
            dropout_prob=float(min(max(dropout, 0.05), 0.8)),
            spurious_fraction=0.15,
            spurious_pool=[round(x, 5) for x in spurious_pool[:20000]],
            calibrated=len(observations) >= min_cases,
        )

    # -- simulation --------------------------------------------------------
    def sample(
        self,
        template: ProcessedSpectrum,
        energy: int,
        rng: np.random.Generator,
        *,
        precursor_mz: float,
    ) -> ProcessedSpectrum:
        noise = self.by_energy.get(int(energy), EnergyNoise())
        n = template.mz.size
        if n == 0:
            return preprocess_peaks([], [])
        dropout = noise.dropout_prob * (1.0 - 0.7 * template.intensity)
        keep = rng.random(n) >= dropout
        if not keep.any():
            keep[int(np.argmax(template.intensity))] = True
        mz = template.mz[keep] + rng.normal(0.0, noise.mz_sigma, int(keep.sum()))
        intensity = template.intensity[keep] * np.exp(
            rng.normal(0.0, noise.intensity_log_sigma, int(keep.sum()))
        )
        n_spurious = int(rng.binomial(n, noise.spurious_fraction))
        if n_spurious and noise.spurious_pool:
            rel = rng.choice(noise.spurious_pool, size=n_spurious, replace=True)
            spurious_mz = np.asarray(rel, float) * precursor_mz
            spurious_mz = spurious_mz[(spurious_mz > 40.0) & (spurious_mz < precursor_mz + 1.5)]
            if spurious_mz.size:
                spurious_int = rng.uniform(0.02, 0.35, spurious_mz.size)
                mz = np.concatenate([mz, spurious_mz])
                intensity = np.concatenate([intensity, spurious_int])
        mz = np.clip(mz, 1e-3, None)
        intensity = np.clip(intensity, 0.0, None)
        if intensity.size == 0 or intensity.max() <= 0:
            return preprocess_peaks([], [])
        return preprocess_peaks(mz, intensity, rel_floor=0.01, normalize=True)

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict:
        return {str(k): v.to_dict() for k, v in self.by_energy.items()}

    @classmethod
    def from_dict(cls, data: dict) -> ErrorModel:
        return cls({int(k): EnergyNoise.from_dict(v) for k, v in data.items()})

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> ErrorModel:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

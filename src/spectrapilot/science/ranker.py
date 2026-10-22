"""Calibrated candidate-level ranker (SpectraPilot v3, P2).

Why candidate-level and not case-level: the quantity a chemist needs is
"how likely is *this* structure given the evidence", and it has to be usable
when the candidate pool changes.  We therefore learn a binary model

    P(candidate is the true structure | features for this observation sequence)

from **train-split episodes only**, with:

* **grouped cross-fitting** by Bemis-Murcko scaffold, so a scaffold never
  appears in both the fitting and the out-of-fold calibration set;
* **same-formula and within-ppm negatives**, i.e. the hard distractors that are
  actually in the pool;
* **isotonic calibration** of the out-of-fold scores;
* explicit **missing-evidence masks**, so the same model scores a CID20-only
  observation and a CID20+CID40 observation without imputation.

The model is *not* a language model and never sees evaluator truth at
inference time.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from spectrapilot.data.repository import CaseRepository
from spectrapilot.models import Candidate, Evidence, Template
from spectrapilot.paths import CURATED
from spectrapilot.science.features import (
    DEFAULT_ACTIONS,
    CaseFeatures,
    EvidenceFeatureExtractor,
    build_sequence_row,
    case_features,
    feature_columns,
)
from spectrapilot.science.templates import ReferenceStore
from unknownid.core.spectra import preprocess_peaks

SEQUENCES: dict[str, tuple[str, ...]] = {
    "cid20": ("CID20",),
    "cid20+cid40": ("CID20", "CID40"),
    "cid20+ead16": ("CID20", "EAD16"),
    "cid20+cid40+ead16": ("CID20", "CID40", "EAD16"),
}


@lru_cache(maxsize=20000)
def bemis_murcko_scaffold(smiles: str) -> str:
    """Bemis-Murcko scaffold used to group cross-fitting folds.

    The frozen curation table does not store a scaffold column, so it is derived
    deterministically here.  An empty scaffold (acyclic molecule) falls back to
    the molecule itself so that it still forms its own group.
    """
    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem.Scaffolds import MurckoScaffold

        RDLogger.DisableLog("rdApp.*")
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return smiles
        scaffold = MurckoScaffold.MurckoScaffoldSmiles(mol=mol, includeChirality=False)
        return scaffold or Chem.MolToSmiles(mol)
    except Exception:  # pragma: no cover
        return smiles


@dataclass
class Episode:
    """One training episode: a case, its true structure, and measured spectra."""

    case_id: str
    true_id: str
    precursor_mz: float
    group: str
    candidates: list[Candidate]
    observations: dict[str, tuple[np.ndarray, np.ndarray]]
    split: str = "train"
    ppm_by_candidate: dict[str, float] = field(default_factory=dict)


def load_episodes(
    repository: CaseRepository,
    records: pd.DataFrame,
    truth,
    *,
    split: str = "train",
    actions: Sequence[str] = DEFAULT_ACTIONS,
    max_candidates: int = 20,
) -> list[Episode]:
    """Build episodes from *train* cases and their archived measurements."""
    wanted = set(actions)
    by_compound: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
    for row in records.itertuples(index=False):
        if str(row.split) != split or str(row.action) not in wanted:
            continue
        by_compound.setdefault(str(row.compound_full_inchikey), {})[str(row.action)] = (
            np.asarray(row.peaks_mz, float),
            np.asarray(row.peaks_intensity, float),
        )

    episodes: list[Episode] = []
    for case_id in repository.case_ids(split):
        true_id = truth.truth(case_id)
        observations = by_compound.get(true_id, {})
        if "CID20" not in observations:
            continue
        case = repository.case(case_id)
        candidates = [
            repository.references.candidate(cid)
            for cid in case.candidate_ids[:max_candidates]
            if cid in repository.references.candidate_ids
        ]
        if true_id not in {c.molecule_id for c in candidates}:
            continue
        true_candidate = repository.references.candidate(true_id)
        group = true_candidate.scaffold or bemis_murcko_scaffold(true_candidate.smiles)
        ppm = {
            c.molecule_id: abs(c.precursor_mz - case.precursor_mz) / case.precursor_mz * 1e6
            for c in candidates
        }
        episodes.append(
            Episode(
                case_id=case_id,
                true_id=true_id,
                precursor_mz=case.precursor_mz,
                group=group,
                candidates=candidates,
                observations=observations,
                split=split,
                ppm_by_candidate=ppm,
            )
        )
    return episodes


class RowBuilder:
    """Deterministic feature rows shared by training and inference."""

    def __init__(
        self,
        store: ReferenceStore,
        *,
        extractor: EvidenceFeatureExtractor | None = None,
        actions: Sequence[str] = DEFAULT_ACTIONS,
        base_scorer=None,
    ) -> None:
        self.store = store
        self.extractor = extractor or EvidenceFeatureExtractor()
        self.actions = tuple(actions)
        self.base_scorer = base_scorer

    def rows_for(
        self,
        *,
        case_id: str,
        candidates: Sequence[Candidate],
        observations: Mapping[str, tuple[np.ndarray, np.ndarray]],
        precursor_mz: float,
        ppm_by_candidate: Mapping[str, float] | None = None,
        sequence: Sequence[str] | None = None,
        true_id: str | None = None,
    ) -> list[dict]:
        sequence = tuple(sequence or tuple(observations)) 
        sequence = tuple(action for action in self.actions if action in sequence)
        if "CID20" not in sequence:
            return []

        per_candidate: dict[str, dict] = {c.molecule_id: {} for c in candidates}
        reliabilities: dict[str, float] = {}
        for action in sequence:
            if action not in observations:
                continue
            observed_mz, observed_intensity = observations[action]
            for candidate in candidates:
                try:
                    template = self.store.template(candidate.molecule_id, action)
                except KeyError:
                    continue
                features = self.extractor.extract(
                    action_key=action,
                    observed_mz=observed_mz,
                    observed_intensity=observed_intensity,
                    candidate=candidate,
                    template=template,
                    precursor_mz=precursor_mz,
                )
                per_candidate[candidate.molecule_id][action] = features
                reliabilities[f"{candidate.molecule_id}:{action}"] = float(
                    template.reliability
                )

        predecessor_peaks = int(
            np.asarray(observations.get("CID20", (np.array([]),))[0]).size
        )
        case_feat = case_features(
            candidates=candidates,
            precursor_ppm_by_candidate=ppm_by_candidate or {},
            template_reliabilities=reliabilities,
            predecessor_peaks=predecessor_peaks,
        )
        rows = []
        for candidate in candidates:
            row = build_sequence_row(
                per_action=per_candidate[candidate.molecule_id],
                case=case_feat,
                actions=self.actions,
            )
            row.update(
                {
                    "case_id": case_id,
                    "candidate_id": candidate.molecule_id,
                    "true_id": true_id or "",
                    "label": int(true_id == candidate.molecule_id) if true_id else 0,
                    "sequence": "+".join(sequence),
                    "present_actions": "+".join(
                        a for a in self.actions if a in per_candidate[candidate.molecule_id]
                    ),
                }
            )
            rows.append(row)
        return rows


def build_training_frame(
    episodes: Sequence[Episode],
    builder: RowBuilder,
    *,
    sequences: Mapping[str, Sequence[str]] | None = None,
) -> pd.DataFrame:
    sequences = sequences or SEQUENCES
    frames = []
    for episode in episodes:
        for sequence in sequences.values():
            if not set(sequence) <= set(episode.observations):
                continue
            rows = builder.rows_for(
                case_id=episode.case_id,
                candidates=episode.candidates,
                observations=episode.observations,
                precursor_mz=episode.precursor_mz,
                ppm_by_candidate=episode.ppm_by_candidate,
                sequence=sequence,
                true_id=episode.true_id,
            )
            if not rows:
                continue
            frame = pd.DataFrame(rows)
            frame["group"] = episode.group
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


@dataclass
class RankerReport:
    n_rows: int
    n_episodes: int
    n_features: int
    n_groups: int
    oof_auc: float | None
    oof_brier: float | None
    oof_top1_accuracy: float | None
    calibration: str
    model: str
    folds: int
    notes: list[str] = field(default_factory=list)

    def public_dict(self) -> dict:
        return {
            "n_rows": self.n_rows,
            "n_episodes": self.n_episodes,
            "n_features": self.n_features,
            "n_groups": self.n_groups,
            "oof_auc": self.oof_auc,
            "oof_brier": self.oof_brier,
            "oof_top1_accuracy": self.oof_top1_accuracy,
            "calibration": self.calibration,
            "model": self.model,
            "folds": self.folds,
            "notes": self.notes,
        }


class CandidateRanker:
    """Gradient-boosted candidate classifier with isotonic calibration."""

    def __init__(
        self,
        *,
        actions: Sequence[str] = DEFAULT_ACTIONS,
        folds: int = 5,
        seed: int = 20261021,
        model: str = "hist_gradient_boosting",
    ) -> None:
        self.actions = tuple(actions)
        self.folds = int(folds)
        self.seed = int(seed)
        self.model_name = model
        self.columns: list[str] = feature_columns(self.actions)
        self.model = None
        self.calibrator = None
        self.report: RankerReport | None = None
        self.metadata: dict = {}

    # -- fitting -----------------------------------------------------------
    def _make_model(self):
        from sklearn.ensemble import HistGradientBoostingClassifier

        if self.model_name == "lightgbm":  # pragma: no cover - optional
            try:
                from lightgbm import LGBMClassifier

                return LGBMClassifier(
                    n_estimators=300,
                    learning_rate=0.05,
                    num_leaves=15,
                    min_child_samples=20,
                    subsample=0.9,
                    colsample_bytree=0.9,
                    random_state=self.seed,
                    verbose=-1,
                )
            except Exception:
                pass
        return HistGradientBoostingClassifier(
            max_iter=250,
            learning_rate=0.06,
            max_leaf_nodes=15,
            min_samples_leaf=20,
            l2_regularization=1.0,
            random_state=self.seed,
        )

    def fit(self, frame: pd.DataFrame, *, group_column: str = "group") -> RankerReport:
        if frame.empty:
            raise ValueError("no training rows")
        columns = [column for column in self.columns if column in frame.columns]
        # Drop columns with no usable variance.  sklearn's histogram binner
        # rejects all-NaN features, and a constant feature carries no signal.
        keep = []
        dropped = []
        for column in columns:
            values = frame[column].astype(float)
            if values.isna().all() or values.nunique(dropna=True) <= 1:
                dropped.append(column)
            else:
                keep.append(column)
        self.columns = keep
        X = frame[keep].astype(float)
        y = frame["label"].astype(int).to_numpy()
        groups = frame[group_column].astype(str).to_numpy()
        weights = 1.0 / frame.groupby(["case_id", "sequence"])["label"].transform("count")

        from sklearn.isotonic import IsotonicRegression
        from sklearn.metrics import brier_score_loss, roc_auc_score
        from sklearn.model_selection import GroupKFold

        n_groups = len(set(groups))
        n_splits = max(2, min(self.folds, n_groups))
        oof = np.full(len(frame), np.nan)
        splitter = GroupKFold(n_splits=n_splits)
        for train_index, test_index in splitter.split(X, y, groups):
            model = self._make_model()
            fit_kwargs = {}
            if hasattr(model, "fit"):
                try:
                    model.fit(X.iloc[train_index], y[train_index], sample_weight=weights.iloc[train_index])
                except TypeError:  # pragma: no cover - model without sample_weight
                    model.fit(X.iloc[train_index], y[train_index])
            oof[test_index] = model.predict_proba(X.iloc[test_index])[:, 1]

        valid = np.isfinite(oof)
        auc = float(roc_auc_score(y[valid], oof[valid])) if len(set(y[valid])) > 1 else None
        brier = float(brier_score_loss(y[valid], oof[valid])) if valid.any() else None
        top1 = _oof_top1(frame[valid], oof[valid])
        calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        calibrator.fit(oof[valid], y[valid])

        self.calibrator = calibrator
        self.model = self._make_model()
        try:
            self.model.fit(X, y, sample_weight=weights)
        except TypeError:  # pragma: no cover
            self.model.fit(X, y)
        self.report = RankerReport(
            n_rows=int(len(frame)),
            n_episodes=int(frame["case_id"].nunique()),
            n_features=len(keep),
            n_groups=int(n_groups),
            oof_auc=auc,
            oof_brier=brier,
            oof_top1_accuracy=top1,
            calibration="isotonic (out-of-fold, grouped by scaffold)",
            model=self.model_name,
            folds=n_splits,
            notes=[
                "Trained on train-split episodes only.",
                "Negatives are the real precursor-consistent distractors.",
                "Out-of-fold scores are grouped by Bemis-Murcko scaffold.",
            ],
        )
        self.metadata = {
            "actions": list(self.actions),
            "columns": list(self.columns),
            "dropped_columns": dropped,
            "seed": self.seed,
            "model": self.model_name,
        }
        return self.report

    # -- inference ---------------------------------------------------------
    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.model is None or self.calibrator is None:
            raise RuntimeError("ranker is not fitted")
        X = frame[self.columns].astype(float)
        raw = self.model.predict_proba(X)[:, 1]
        return np.clip(self.calibrator.predict(raw), 1e-6, 1 - 1e-6)

    def score_rows(self, rows: Sequence[dict]) -> np.ndarray:
        return self.predict(pd.DataFrame(rows))

    # -- persistence -------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "calibrator": self.calibrator,
            "columns": self.columns,
            "actions": list(self.actions),
            "report": self.report.public_dict() if self.report else None,
            "metadata": self.metadata,
        }
        with path.open("wb") as handle:
            pickle.dump(payload, handle)

    @classmethod
    def load(cls, path: Path) -> "CandidateRanker":
        path = Path(path)
        with path.open("rb") as handle:
            payload = pickle.load(handle)
        ranker = cls(actions=payload["actions"])
        ranker.columns = payload["columns"]
        ranker.model = payload["model"]
        ranker.calibrator = payload["calibrator"]
        ranker.metadata = payload.get("metadata", {})
        report = payload.get("report")
        if report:
            ranker.report = RankerReport(**report)
        return ranker


def _oof_top1(frame: pd.DataFrame, scores: np.ndarray) -> float:
    """Top-1 accuracy of out-of-fold scores, averaged over case/sequence groups."""
    work = frame[["case_id", "sequence", "label"]].copy()
    work["score"] = scores
    correct = []
    for _, group in work.groupby(["case_id", "sequence"], sort=False):
        ranked = group.sort_values("score", ascending=False)
        correct.append(float(ranked.iloc[0]["label"] == 1))
    return float(np.mean(correct)) if correct else 0.0


class CalibratedEvidenceScorer:
    """Adapts :class:`CandidateRanker` to the investigation-session interface.

    Candidate weights are calibrated probabilities of being the true structure
    *within the candidate pool*, not probabilities over all of chemical space.
    """

    name = "calibrated_ranker"
    version = "v3_s2"

    def __init__(
        self,
        ranker: CandidateRanker,
        builder: RowBuilder,
        *,
        base_scorer,
        ppm_tolerance: float = 10.0,
    ) -> None:
        self.ranker = ranker
        self.builder = builder
        self.base_scorer = base_scorer
        self.ppm_tolerance = float(ppm_tolerance)

    def _rank_sequence(
        self,
        observations: Mapping[str, tuple[np.ndarray, np.ndarray]],
        candidates: Sequence[Candidate],
        store: ReferenceStore,
        precursor_mz: float,
    ):
        base_evidence: dict[str, Evidence] = {}
        base_weights: dict[str, float] = {}
        if self.base_scorer is not None:
            order = [a for a in ("CID20", "CID40", "EAD16") if a in observations]
            for index, action in enumerate(order):
                spectrum = preprocess_peaks(*observations[action], rel_floor=0.0)
                if index == 0:
                    base_evidence, base_weights = self.base_scorer.initial_rank(
                        spectrum, candidates, store, action, precursor_mz=precursor_mz
                    )
                else:
                    fresh, base_weights = self.base_scorer.update(
                        base_weights,
                        spectrum,
                        candidates,
                        store,
                        action,
                        precursor_mz=precursor_mz,
                    )
                    base_evidence.update(fresh)

        ppm = {
            c.molecule_id: abs(c.precursor_mz - precursor_mz) / precursor_mz * 1e6
            for c in candidates
        }
        rows = self.builder.rows_for(
            case_id="",
            candidates=candidates,
            observations=observations,
            precursor_mz=precursor_mz,
            ppm_by_candidate=ppm,
        )
        probabilities = self.ranker.score_rows(rows)
        total = float(probabilities.sum()) if len(probabilities) else 0.0
        weights = {
            row["candidate_id"]: float(prob / total) if total > 0 else 0.0
            for row, prob in zip(rows, probabilities)
        }
        evidence: dict[str, Evidence] = {}
        for row, prob in zip(rows, probabilities):
            cid = row["candidate_id"]
            candidate = next(c for c in candidates if c.molecule_id == cid)
            previous = base_evidence.get(cid)
            item = previous or Evidence(candidate_id=cid)
            item.name = candidate.name
            item.formula = candidate.formula
            item.smiles = candidate.smiles
            item.exact_mass = candidate.exact_mass
            item.estimated_error = float(1.0 - prob)
            item.weight = float(weights.get(cid, 0.0))
            item.relative_weight = item.weight
            item.reasons = [
                f"calibrated_candidate_probability={prob:.4f}",
                "probability is conditional on the candidate pool",
            ]
            evidence[cid] = item
        return evidence, weights

    def rank_sequence(self, observations, candidates, store, precursor_mz):
        return self._rank_sequence(observations, candidates, store, precursor_mz)

    # Kept for interface compatibility; the session prefers rank_sequence.
    def initial_rank(self, observed, candidates, store, action, *, precursor_mz):
        arrays = (np.asarray(observed.mz, float), np.asarray(observed.intensity, float))
        return self._rank_sequence({action: arrays}, candidates, store, precursor_mz)

    def update(self, prior, observed, candidates, store, action, *, precursor_mz):
        arrays = (np.asarray(observed.mz, float), np.asarray(observed.intensity, float))
        return self._rank_sequence({action: arrays}, candidates, store, precursor_mz)


def train_ranker(
    repository: CaseRepository,
    records: pd.DataFrame,
    truth,
    *,
    output: Path | None = None,
    folds: int = 5,
    seed: int = 20261021,
    model: str = "hist_gradient_boosting",
    fragments=None,
) -> tuple[CandidateRanker, pd.DataFrame]:
    extractor = EvidenceFeatureExtractor(fragments=fragments) if fragments is not None else EvidenceFeatureExtractor()
    builder = RowBuilder(repository.references, extractor=extractor)
    episodes = load_episodes(repository, records, truth, split="train")
    frame = build_training_frame(episodes, builder)
    ranker = CandidateRanker(folds=folds, seed=seed, model=model)
    ranker.fit(frame)
    ranker.metadata["n_episodes_available"] = len(episodes)
    if output is not None:
        ranker.save(Path(output))
        report_path = Path(output).with_suffix(".report.json")
        report_path.write_text(json.dumps(ranker.report.public_dict(), indent=2), encoding="utf-8")
    return ranker, frame

"""Precommitted, falsifiable fragment hypotheses (SpectraPilot v3, T5).

Before a hidden spectrum is revealed, the system writes down what it expects to
see and what would prove it wrong.  The record is hashed and attached to the
investigation, so a hypothesis can never be edited after the fact.

Two things are deliberately *not* done here:

* no measured peak from the target action is ever read while generating a
  hypothesis (only already-observed actions and predicted templates are used);
* a hypothesis is never promoted to "confirmed" by a template that was itself
  derived from the target measurement.  ``template_source`` is recorded on every
  hypothesis and reported with its validation status.

The validation rule is intentionally simple and predeclared::

    supported   at least half of the predicted diagnostic peaks (and at least
                two) are observed within tolerance, and none of the
                "expected-absent" peaks appears.
    refuted     fewer than that are observed, while the measurement itself has
                at least three peaks (a sparse scan can neither support nor
                refute).
    pending     the action has not been measured.
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

import numpy as np

from spectrapilot.models import Candidate, Evidence, Measurement, Template


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def observation_digest(observations: Mapping[str, Measurement]) -> str:
    payload = {
        action: {
            "mz": [round(float(value), 6) for value in measurement.mz],
            "intensity": [round(float(value), 6) for value in measurement.intensity],
        }
        for action, measurement in sorted(observations.items())
    }
    return _digest(payload)


class FragmentHypothesisGenerator:
    """Builds precommitted diagnostic-peak hypotheses for the next action."""

    name = "diagnostic_peak_precommit"
    max_candidates = 3
    max_predicted_peaks = 5
    intensity_floor = 0.05
    tolerance_da = 0.02

    def _template(self, store, candidate_id: str, action: str) -> Template | None:
        try:
            return store.template(candidate_id, action)
        except KeyError:
            return None

    def generate(
        self,
        *,
        case,
        candidates: Sequence[Candidate],
        weights: Mapping[str, float],
        store,
        observed_actions: Sequence[str],
        available_actions: Sequence[object],
        observations: Mapping[str, Measurement],
    ) -> dict:
        observed = set(observed_actions)
        actions: list[str] = []
        for action in available_actions:
            key = getattr(action, "key", None) or str(action)
            if key in observed or key == "STOP":
                continue
            actions.append(key)
        action = actions[0] if actions else None
        ranked = sorted(
            (candidate for candidate in candidates if candidate.molecule_id in weights),
            key=lambda candidate: -float(weights.get(candidate.molecule_id, 0.0)),
        )[: self.max_candidates]
        if action is None or not ranked:
            return {
                "case_id": case.case_id,
                "action": None,
                "hypotheses": [],
                "precommit_sha256": _digest({"case_id": case.case_id, "hypotheses": []}),
                "note": "no unobserved action or no ranked candidate",
            }

        hypotheses: list[dict] = []
        for index, candidate in enumerate(ranked, start=1):
            template = self._template(store, candidate.molecule_id, action)
            if template is None or template.n_peaks < 2:
                continue
            intensity = np.asarray(template.intensity, float)
            mz = np.asarray(template.mz, float)
            order = np.argsort(-intensity)[: self.max_predicted_peaks]
            order.sort()
            predicted = [
                {
                    "mz": round(float(mz[position]), 4),
                    "relative_intensity": round(float(intensity[position]), 3),
                }
                for position in order
                if intensity[position] >= self.intensity_floor
            ]
            if len(predicted) < 2:
                continue
            # A high-intensity precursor-region loss that the template predicts
            # should be absent for this candidate is a useful negative control.
            expected_absent = [
                {
                    "mz": round(float(mz[position]), 4),
                    "why": "template assigns <1% relative intensity here",
                }
                for position in np.argsort(intensity)[:1]
                if intensity[position] < 0.01 * max(float(intensity.max()), 1e-9)
            ]
            rule_threshold = max(2, int(np.ceil(0.5 * len(predicted))))
            hypotheses.append(
                {
                    "hypothesis_id": f"H{index}_{action}",
                    "candidate_id": candidate.molecule_id,
                    "candidate_name": candidate.name,
                    "action": action,
                    "template_source": template.source,
                    "template_reliability": float(template.reliability),
                    "template_is_experimental": bool(template.is_experimental),
                    "predicted_diagnostic_peaks": predicted,
                    "expected_absent_peaks": expected_absent,
                    "falsification_rule": (
                        f"supported if >= {rule_threshold} of {len(predicted)} predicted "
                        f"peaks are observed within {self.tolerance_da} Da and no "
                        "expected-absent peak appears; refuted otherwise when the "
                        "measurement has >= 3 peaks"
                    ),
                    "rule_threshold": rule_threshold,
                    "status": "pending",
                    "observed_matches": [],
                }
            )
        payload = {
            "case_id": case.case_id,
            "action": action,
            "method": self.name,
            "tolerance_da": self.tolerance_da,
            "candidate_order": [candidate.molecule_id for candidate in ranked],
            "hypotheses": hypotheses,
            "note": (
                "Generated from predicted templates only; no hidden peak of the "
                "target action is read before the hash is sealed."
            ),
        }
        payload["precommit_sha256"] = precommit_sha256(payload)
        return payload


def precommit_sha256(payload: Mapping) -> str:
    body = {key: value for key, value in payload.items() if key != "precommit_sha256"}
    return _digest(body)


def validate_against_measurement(hypotheses: Mapping, measurement: Measurement) -> dict:
    """Attach measured outcomes to each precommitted hypothesis."""
    payload = json.loads(json.dumps(hypotheses, default=str))
    action = payload.get("action")
    tolerance = float(payload.get("tolerance_da", 0.02))
    observed_mz = np.asarray(measurement.mz, float)
    observed_intensity = np.asarray(measurement.intensity, float)
    usable = int(observed_mz.size)

    for hypothesis in payload.get("hypotheses", []):
        if hypothesis.get("action") != action or action != measurement.action:
            hypothesis["status"] = "not_tested"
            continue
        matches = []
        for peak in hypothesis.get("predicted_diagnostic_peaks", []):
            if observed_mz.size == 0:
                continue
            distances = np.abs(observed_mz - float(peak["mz"]))
            index = int(np.argmin(distances))
            if distances[index] <= tolerance:
                matches.append(
                    {
                        "predicted_mz": peak["mz"],
                        "observed_mz": round(float(observed_mz[index]), 4),
                        "observed_intensity": round(float(observed_intensity[index]), 4),
                        "delta_da": round(float(distances[index]), 5),
                    }
                )
        hypothesis["observed_matches"] = matches
        forbidden = 0
        for peak in hypothesis.get("expected_absent_peaks", []):
            if observed_mz.size and float(np.min(np.abs(observed_mz - float(peak["mz"])))) <= tolerance:
                forbidden += 1
        threshold = int(hypothesis.get("rule_threshold", 2))
        if usable < 3:
            hypothesis["status"] = "inconclusive_sparse_spectrum"
        elif len(matches) >= threshold and forbidden == 0:
            hypothesis["status"] = "supported"
        else:
            hypothesis["status"] = "refuted"
        hypothesis["match_count"] = len(matches)
        hypothesis["forbidden_hits"] = forbidden
    payload["validated_against_action"] = measurement.action
    payload["validation_note"] = (
        "Status is a predeclared rule outcome on the measured peaks; it is not "
        "structural proof and inherits the reliability of the predicted template."
    )
    return payload

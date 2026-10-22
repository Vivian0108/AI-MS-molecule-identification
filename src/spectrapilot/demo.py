"""Restricted local demo service. Runtime never loads the research dataset."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pandas as pd

from spectrapilot.data.repository import CaseRepository
from spectrapilot.paths import ROOT
from spectrapilot.planning.actions import stop_action
from spectrapilot.planning.oracle import OracleStore
from spectrapilot.planning.session import ActionLog
from spectrapilot.science.templates import ReferenceStore
from spectrapilot.service import ServiceError, SpectraPilotService

DEMO = ROOT / "data" / "demo"


class DemoService(SpectraPilotService):
    def __init__(self, bundle: Path = DEMO):
        self.bundle = Path(bundle)
        self._temporary = tempfile.TemporaryDirectory(prefix="spectrapilot-demo-")
        self._log_dir = Path(self._temporary.name)
        self._identity_checks = {}
        super().__init__(default_split="dev", action_log=ActionLog(self._log_dir / "actions.jsonl"))

    def _read(self, relative):
        return json.loads((self.bundle / relative).read_text())

    def _load(self):
        self.manifest = self._read("public/manifest.json")
        self.provenance_manifest = self.manifest
        self.results = self._read("public/results.json")
        self._verify_bundle()
        cases = pd.DataFrame(self._read("public/cases.json"))
        if set(cases.split) != {"dev"}:
            raise ServiceError("demo bundle must contain development cases only")
        self.references = ReferenceStore(
            pd.DataFrame(self._read("public/candidates.json")),
            pd.DataFrame(self._read("public/templates.json")),
            ppm_tolerance=float(self.selection_cfg.get_path("candidate_pool.ppm")),
        )
        self.repository = CaseRepository(cases, self.references)
        self.oracle = OracleStore.load(
            self.bundle / "instrument/cases.json", log_path=self._log_dir / "access.jsonl"
        )
        self._configure_science()

    def _verify_bundle(self):
        built = self._read("build_manifest.json")
        for relative, expected in built["files"].items():
            if relative.startswith("evaluator/"):
                continue  # do not read evaluator identity before an explicit post-stop request
            path = (self.bundle / relative).resolve()
            if not path.is_relative_to(self.bundle.resolve()):
                raise ServiceError("invalid demo artifact path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ServiceError(f"demo artifact checksum mismatch: {relative}")
        for relative in ("configs/multims2.yaml", "configs/policies.yaml"):
            if (
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                != built["inputs"][relative]
            ):
                raise ServiceError("demo configuration differs from its frozen bundle")

    def discovery_manifest(self):
        """Neutral sample catalog; curation roles never label an investigation."""
        return {
            **{key: value for key, value in self.manifest.items() if key != "cases"},
            "cases": [
                {
                    "case_id": row["case_id"],
                    "title": f"Sample {index}",
                    "description": "Unknown sample; inspect the acquired evidence to investigate.",
                }
                for index, row in enumerate(self.manifest["cases"], 1)
            ],
        }

    def _closed_plan(self, plan):
        return {
            **plan,
            "recommended": stop_action().public_dict(),
            "options": [],
            "note": "Investigation closed. Export the evidence report or reset this example.",
        }

    def _state(self, session, *, include_initial=False):
        state = super()._state(session, include_initial=include_initial)
        state["demo"] = {"banner": self.manifest["banner"], "scope": self.manifest["scope"]}
        if session.stopped:
            state["plan"] = self._closed_plan(state["plan"])
        return state

    def get_evidence(self, case_id):
        state = super().get_evidence(case_id)
        if state["stopped"]:
            state["plan"] = self._closed_plan(state["plan"])
        return state

    def plan(self, case_id):
        return self.get_evidence(case_id)["plan"]

    def observations(self, case_id):
        session = self.session(case_id)
        return [
            session.observation(action).public_dict(include_accession=session.stopped)
            for action in session.observed_actions
        ]

    def report(self, case_id):
        session = self.session(case_id)
        if not session.stopped:
            raise ServiceError("Stop the investigation before exporting its final report.")
        result = super().report(case_id)
        result["demo"] = {
            key: self.manifest[key]
            for key in (
                "banner",
                "scope",
                "reference_method",
                "source_repository",
                "source_commit",
                "doi",
                "data_license",
            )
        }
        result["report_markdown"] = (
            "> Demo mode — curated development example, not independent evaluation evidence.\n\n"
            "> Reference spectra use experimental donor-agreement consensus and permitted CID60 library anchors. "
            "Measurements are archived MultiMS2 data (CC0-1.0).\n\n" + result["report_markdown"]
        )
        if case_id in self._identity_checks:
            result["curated_identity_check"] = self._identity_checks[case_id]
            result["report_markdown"] += (
                f"\n## Curated identity check (requested after stop)\n\n"
                f"Source identity: {self._identity_checks[case_id]['name']} "
                f"(`{self._identity_checks[case_id]['true_id']}`).\n"
                f"Outcome: {self._identity_checks[case_id]['outcome']}.\n"
            )
        return result

    def stop(self, case_id):
        self.session(case_id).stop()
        return self.report(case_id)

    def reveal_identity(self, case_id):
        session = self.session(case_id)
        if not session.stopped:
            raise ServiceError("Curated source identity is available only after stopping.")
        # Evaluator data is read only at this explicit post-stop operation.
        expected = self._read("build_manifest.json")["files"]["evaluator/truth.json"]
        if (
            hashlib.sha256((self.bundle / "evaluator/truth.json").read_bytes()).hexdigest()
            != expected
        ):
            raise ServiceError("curated identity checksum mismatch")
        identity = self._read("evaluator/truth.json")[case_id]
        investigation = session.investigation()
        outcome = (
            "abstained"
            if investigation.predicted_identity is None
            else (
                "accepted-correct"
                if investigation.predicted_identity == identity["true_id"]
                else "accepted-error"
            )
        )
        self._identity_checks[case_id] = {**identity, "outcome": outcome}
        return dict(self._identity_checks[case_id])

    def reset_case(self, case_id):
        super().reset_case(case_id)
        self._identity_checks.pop(case_id, None)

    def close(self):
        self._temporary.cleanup()

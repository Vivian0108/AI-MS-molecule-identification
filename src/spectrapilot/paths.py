"""Path and configuration helpers for the SpectraPilot v2 lab."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs"
DATA = ROOT / "data" / "multims2"
CURATED = DATA / "curated"
REFERENCE = DATA / "reference"
ORACLE_PRIVATE = DATA / "oracle_private"
EVALUATOR_PRIVATE = DATA / "evaluator_private"
REPORTS = ROOT / "reports" / "spectrapilot"
EXTERNAL = ROOT / "external"

MGF_PATH = EXTERNAL / "MultiMS2" / "data" / "multims2_spectra.mgf"


class Config:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def get_path(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.payload
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_config(name: str = "multims2") -> Config:
    path = CONFIG_DIR / f"{name}.yaml"
    return Config(yaml.safe_load(path.read_text(encoding="utf-8")))

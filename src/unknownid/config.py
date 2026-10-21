"""Configuration loading for data selection and acquisition policies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


class Config(dict):
    """Small dict wrapper with dotted access and provenance tracking."""

    def get_path(self, dotted: str, default: Any = None) -> Any:
        node: Any = self
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_config(name: str = "selection") -> Config:
    path = CONFIG_DIR / f"{name}.yaml"
    with path.open("r", encoding="utf-8") as handle:
        return Config(yaml.safe_load(handle))


def load_all() -> tuple[Config, Config]:
    return load_config("selection"), load_config("acquisition")

"""Stable, anonymised case identifiers."""

from __future__ import annotations

import hashlib


def make_case_id(molecule_id: str, precursor_mz: float, version: str = "v1") -> str:
    digest = hashlib.sha256(
        f"{molecule_id}|{precursor_mz:.6f}|{version}".encode()
    ).hexdigest()
    return f"case-{digest[:12]}"

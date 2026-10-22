"""Conservative MultiMS2 MGF parser.

The parser does not infer identity or acquisition conditions from file names.
Every decision is made from an explicit MGF header key and is recorded with the
raw value so the mapping can be audited.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np

REQUIRED_HEADERS = (
    "FILENAME",
    "COMPOUND_NAME",
    "FORMULA",
    "SMILES",
    "INCHIAUX",
    "IONMODE",
    "ADDUCT",
    "PRECURSOR_MZ",
    "FRAGMENTATION_METHOD",
    "COLLISION_ENERGY",
    "INSTRUMENT_NAME",
    "MSLEVEL",
)

_ENERGY_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass
class MGFRecord:
    headers: dict[str, str]
    peaks: list[tuple[float, float]]
    source_file: str
    source_block: int
    sha256: str

    def header(self, key: str, default: str = "") -> str:
        return self.headers.get(key, default)

    @property
    def filename(self) -> str:
        return self.header("FILENAME")

    @property
    def scan(self) -> str:
        return self.header("EXTRACTSCAN")

    @property
    def compound_name(self) -> str:
        return self.header("COMPOUND_NAME")

    @property
    def inchikey(self) -> str:
        return self.header("INCHIAUX")

    @property
    def smiles(self) -> str:
        return self.header("SMILES")

    @property
    def formula(self) -> str:
        return self.header("FORMULA")

    @property
    def ion_mode(self) -> str:
        return self.header("IONMODE").strip().lower()

    @property
    def adduct(self) -> str:
        return self.header("ADDUCT").strip()

    @property
    def method(self) -> str:
        return self.header("FRAGMENTATION_METHOD").strip().upper()

    @property
    def energy(self) -> float | None:
        raw = self.header("COLLISION_ENERGY").strip()
        match = _ENERGY_RE.search(raw)
        return float(match.group(0)) if match else None

    @property
    def precursor_mz(self) -> float | None:
        try:
            return float(self.header("PRECURSOR_MZ"))
        except ValueError:
            return None

    @property
    def n_peaks_header(self) -> int | None:
        try:
            return int(self.header("NUM_PEAKS"))
        except ValueError:
            return None

    def public_metadata(self) -> dict:
        return dict(self.headers)


def _parse_peaks(lines: list[str]) -> list[tuple[float, float]]:
    peaks: list[tuple[float, float]] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            mz, intensity = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if np.isfinite(mz) and np.isfinite(intensity) and mz > 0 and intensity >= 0:
            peaks.append((mz, intensity))
    return peaks


def iter_mgf(path: str | Path) -> Iterator[MGFRecord]:
    path = Path(path)
    block_no = 0
    in_block = False
    in_peaks = False
    headers: dict[str, str] = {}
    peak_lines: list[str] = []
    block_lines: list[str] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line == "BEGIN IONS":
                in_block = True
                in_peaks = False
                headers = {}
                peak_lines = []
                block_lines = [line]
                block_no += 1
                continue
            if line == "END IONS" and in_block:
                block_lines.append(line)
                payload = "\n".join(block_lines).encode("utf-8")
                yield MGFRecord(
                    headers=headers,
                    peaks=_parse_peaks(peak_lines),
                    source_file=str(path),
                    source_block=block_no,
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
                in_block = False
                continue
            if not in_block:
                continue
            block_lines.append(line)
            if in_peaks:
                if line.strip():
                    peak_lines.append(line)
                continue
            if not line.strip():
                if headers:
                    in_peaks = True
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                headers[key.strip().upper()] = value.strip()
            elif headers and line[0].isdigit():
                in_peaks = True
                peak_lines.append(line)
    if in_block:
        raise ValueError(f"unterminated MGF block {block_no} in {path}")


def missing_required_headers(record: MGFRecord) -> list[str]:
    return [key for key in REQUIRED_HEADERS if not record.header(key)]

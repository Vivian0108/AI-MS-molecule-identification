"""Parser for raw MassBank ``.txt`` records.

The parser deliberately reads the *original tags* and never infers metadata from
file names.  Collision energy is preserved as the original string, a parsed
numeric value and a unit so that ``eV``, ramps and percent NCE can never be
silently combined.

MassBank tags have the shape ``NAMESPACE: SUBKEY value`` for many namespaces
(e.g. ``AC$MASS_SPECTROMETRY: COLLISION_ENERGY 10 eV``); ``PK$PEAK`` stores its
peak table on subsequent indented lines.  Both forms are handled explicitly.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

_TAG_RE = re.compile(r"^([A-Z][A-Z0-9$_.\-]*):[ \t]?(.*)$")
_CE_RE = re.compile(
    r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>eV|ev|EV|volts?|V)\s*$"
)


@dataclass
class ParsedPeak:
    mz: float
    intensity: float
    relative_intensity: float


@dataclass
class Field:
    key: str
    value: str
    continuation: list[str] = field(default_factory=list)


@dataclass
class MassBankRecord:
    accession: str
    path: str
    sha256: str
    license: str = ""
    comments: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    smiles: str = ""
    formula: str = ""
    exact_mass: Optional[float] = None
    inchikey: str = ""
    instrument: str = ""
    instrument_type: str = ""
    ms_type: str = ""
    ion_mode: str = ""
    ionization: str = ""
    fragmentation_mode: str = ""
    collision_energy_raw: str = ""
    collision_energy_value: Optional[float] = None
    collision_energy_unit: str = ""
    precursor_mz: Optional[float] = None
    precursor_type: str = ""
    base_peak: Optional[float] = None
    retention_time_min: Optional[float] = None
    num_peak_tagged: Optional[int] = None
    peaks: list[ParsedPeak] = field(default_factory=list)
    raw_fields: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_standard_compound(self) -> bool:
        return any(
            "CONFIDENCE standard compound" in c
            or "CONFIDENCE Reference Standard" in c
            for c in self.comments
        )

    @property
    def license_is_redistributable(self) -> bool:
        return self.license.strip().upper() in {
            "CC BY",
            "CC BY-SA",
            "CC BY 4.0",
            "CC0",
        }

    @property
    def collision_energy_is_fixed_ev(self) -> bool:
        return (
            self.collision_energy_value is not None
            and self.collision_energy_unit.lower() in {"ev", "v", "volt", "volts"}
        )

    def comment_value(self, prefix: str) -> Optional[str]:
        for comment in self.comments:
            if comment.startswith(prefix):
                return comment[len(prefix) :].strip()
        return None


def _split_fields(text: str) -> list[Field]:
    fields: list[Field] = []
    current: Optional[Field] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("//"):
            continue
        match = _TAG_RE.match(line)
        if match:
            current = Field(key=match.group(1), value=match.group(2).strip())
            fields.append(current)
        elif current is not None:
            current.continuation.append(line.strip())
    return fields


class _Accessor:
    def __init__(self, fields: Iterable[Field]):
        self.fields = list(fields)

    def first(self, key: str, default: str = "") -> str:
        for fld in self.fields:
            if fld.key == key:
                return fld.value
        return default

    def all(self, key: str) -> list[str]:
        return [fld.value for fld in self.fields if fld.key == key]

    def sub(self, namespace: str, subkey: str, default: str = "") -> str:
        """Return the value of ``NAMESPACE: SUBKEY value``."""
        wanted = subkey.upper()
        for fld in self.fields:
            if fld.key != namespace:
                continue
            parts = fld.value.split(None, 1)
            if parts and parts[0].upper() == wanted:
                return parts[1].strip() if len(parts) > 1 else ""
        return default

    def sub_all(self, namespace: str, subkey: str) -> list[str]:
        wanted = subkey.upper()
        values = []
        for fld in self.fields:
            if fld.key != namespace:
                continue
            parts = fld.value.split(None, 1)
            if parts and parts[0].upper() == wanted:
                values.append(parts[1].strip() if len(parts) > 1 else "")
        return values

    def continuation(self, key: str) -> list[str]:
        lines: list[str] = []
        for fld in self.fields:
            if fld.key == key:
                lines.extend(fld.continuation)
        return lines


def _parse_ce(raw: str) -> tuple[Optional[float], str]:
    if not raw:
        return None, ""
    match = _CE_RE.match(raw)
    if not match:
        # ramps, NCE percentages and anything ambiguous stay unparsed
        parts = raw.split()
        return None, parts[-1] if parts else ""
    return float(match.group("value")), match.group("unit")


def _parse_peaks(lines: list[str], declared: Optional[int]) -> list[ParsedPeak]:
    peaks: list[ParsedPeak] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            mz = float(parts[0])
            intensity = float(parts[1])
            rel = float(parts[2]) if len(parts) > 2 else intensity
        except ValueError:
            continue
        peaks.append(ParsedPeak(mz=mz, intensity=intensity, relative_intensity=rel))
    # A declared/actual mismatch is surfaced by the audit, never silently fixed.
    _ = declared
    return peaks


def parse_record_text(text: str, *, path: str = "", sha256: str = "") -> MassBankRecord:
    fields = _split_fields(text)
    acc = _Accessor(fields)

    record = MassBankRecord(
        accession=acc.first("ACCESSION"),
        path=path,
        sha256=sha256 or hashlib.sha256(text.encode("utf-8")).hexdigest(),
        license=acc.first("LICENSE"),
        comments=acc.all("COMMENT"),
        names=acc.all("CH$NAME"),
        smiles=acc.first("CH$SMILES"),
        formula=acc.first("CH$FORMULA"),
        inchikey=acc.sub("CH$LINK", "INCHIKEY"),
        instrument=acc.first("AC$INSTRUMENT"),
        instrument_type=acc.first("AC$INSTRUMENT_TYPE"),
        ms_type=acc.sub("AC$MASS_SPECTROMETRY", "MS_TYPE"),
        ion_mode=acc.sub("AC$MASS_SPECTROMETRY", "ION_MODE"),
        ionization=acc.sub("AC$MASS_SPECTROMETRY", "IONIZATION"),
        fragmentation_mode=acc.sub("AC$MASS_SPECTROMETRY", "FRAGMENTATION_MODE"),
        collision_energy_raw=acc.sub("AC$MASS_SPECTROMETRY", "COLLISION_ENERGY"),
        precursor_type=acc.sub("MS$FOCUSED_ION", "PRECURSOR_TYPE")
        or acc.sub("MS$FOCUSED_ION", "ION_TYPE"),
        raw_fields={fld.key: [fld.value] for fld in fields},
    )

    try:
        record.exact_mass = float(acc.first("CH$EXACT_MASS"))
    except ValueError:
        record.exact_mass = None

    for raw, attr in (
        (acc.sub("MS$FOCUSED_ION", "PRECURSOR_M/Z"), "precursor_mz"),
        (acc.sub("MS$FOCUSED_ION", "BASE_PEAK"), "base_peak"),
        (acc.sub("AC$CHROMATOGRAPHY", "RETENTION_TIME"), "retention_time_min"),
    ):
        if raw:
            try:
                setattr(record, attr, float(raw.split()[0]))
            except (ValueError, IndexError):
                pass

    try:
        record.num_peak_tagged = int(acc.first("PK$NUM_PEAK"))
    except ValueError:
        record.num_peak_tagged = None

    record.collision_energy_value, record.collision_energy_unit = _parse_ce(
        record.collision_energy_raw
    )
    record.peaks = _parse_peaks(acc.continuation("PK$PEAK"), record.num_peak_tagged)
    return record


def parse_record_file(path: str | Path) -> MassBankRecord:
    path = Path(path)
    data = path.read_bytes()
    return parse_record_text(
        data.decode("utf-8", errors="replace"),
        path=str(path),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def iter_record_files(directory: str | Path, pattern: str = "*.txt") -> Iterable[Path]:
    yield from sorted(Path(directory).glob(pattern))

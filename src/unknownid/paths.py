"""Filesystem locations used across the project."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW_MASSBANK = DATA / "raw" / "massbank"
RAW_ATHENS = RAW_MASSBANK / "Athens_Univ"
CURATED = DATA / "curated"
ORACLE_DIR = DATA / "oracle"
REPORTS = ROOT / "reports"
CONFIG = ROOT / "config"

RECORDS_PARQUET = CURATED / "records.parquet"
SPECTRA_PARQUET = CURATED / "spectra.parquet"
LIBRARY_PARQUET = CURATED / "library.parquet"
COMPLETE_CASES_PARQUET = CURATED / "complete_cases.parquet"
PARTIAL_CASES_PARQUET = CURATED / "partial_cases.parquet"
PUBLIC_CASES_PARQUET = CURATED / "public_cases.parquet"
SPLITS_JSON = CURATED / "splits.json"
AUDIT_PARQUET = CURATED / "audit.parquet"
AUDIT_CASES_PARQUET = CURATED / "audit_cases.parquet"
CALIBRATION_JSON = CURATED / "calibration.json"
MANIFEST_JSON = DATA / "manifest.json"
PRIVATE_ORACLE_JSON = ORACLE_DIR / "private_oracle_cases.json"
LEGACY_PRIVATE_ORACLE_JSON = ORACLE_DIR / "private_oracle_cases.parquet"
DEMO = DATA / "demo"


def existing_oracle_path() -> Path:
    """Accept historical JSON bytes with the old .parquet suffix."""
    return PRIVATE_ORACLE_JSON if PRIVATE_ORACLE_JSON.exists() else LEGACY_PRIVATE_ORACLE_JSON


ORACLE_LOG = ORACLE_DIR / "access_log.jsonl"
AUDIT_MD = REPORTS / "data_audit.md"
EVALUATION_MD = REPORTS / "evaluation.md"
EVALUATION_JSON = REPORTS / "evaluation.json"
CALIBRATION_MD = REPORTS / "calibration.md"


def ensure_dirs() -> None:
    for path in (CURATED, ORACLE_DIR, REPORTS, DATA / "raw"):
        path.mkdir(parents=True, exist_ok=True)

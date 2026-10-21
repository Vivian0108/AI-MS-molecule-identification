#!/usr/bin/env python
"""Restore ONLY the gitignored oracle from frozen curated spectra; never refit or resplit."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / 'src'))
sys.path.insert(0,str(ROOT / 'scripts'))
import pandas as pd
from prepare_data import build_private_oracle
from unknownid.config import load_config
from unknownid.data.curate import build_case_specs
from unknownid.data.splits import SplitResult
from unknownid.paths import CURATED, PRIVATE_ORACLE_JSON


def main():
    selected = pd.read_parquet(CURATED / 'spectra.parquet')
    library = pd.read_parquet(CURATED / 'library.parquet')
    complete = pd.read_parquet(CURATED / 'complete_cases.parquet')
    specs = build_case_specs(complete, library, load_config('selection'))
    payload = build_private_oracle(specs, SplitResult.load(), selected, library)
    raw = json.dumps(payload, indent=2).encode()
    expected = json.loads((CURATED/'dataset_version.json').read_text())['artefact_sha256']['private_oracle']
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise SystemExit(f'Frozen oracle hash mismatch: {actual} != {expected}; refusing restore')
    PRIVATE_ORACLE_JSON.parent.mkdir(parents=True,exist_ok=True)
    PRIVATE_ORACLE_JSON.write_bytes(raw)
    print(f'Restored frozen oracle; SHA256 {actual}')


if __name__ == '__main__':
    main()

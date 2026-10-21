import hashlib
import json

from unknownid.paths import ROOT


def test_frozen_configuration_and_test_split_unchanged():
    baseline = json.loads((ROOT / "reports/readiness/baseline.json").read_text())
    for path, expected in baseline["hashes"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    split = json.loads((ROOT / "data/curated/splits.json").read_text())
    assert set(baseline["frozen_test_molecules"]) == {
        m for m, s in split["assignment"].items() if s == "test"
    }


def test_oracle_filename_migration(monkeypatch, tmp_path):
    from unknownid import paths

    current = tmp_path / "private_oracle_cases.json"
    legacy = tmp_path / "private_oracle_cases.parquet"
    monkeypatch.setattr(paths, "PRIVATE_ORACLE_JSON", current)
    monkeypatch.setattr(paths, "LEGACY_PRIVATE_ORACLE_JSON", legacy)
    legacy.write_text("{}")
    assert paths.existing_oracle_path() == legacy
    current.write_text("{}")
    assert paths.existing_oracle_path() == current

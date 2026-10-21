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

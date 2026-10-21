#!/usr/bin/env python
"""List the committed curated train/dev examples (no frozen test selection)."""

import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "data/demo/manifest.json").read_text())
    print(manifest["label"])
    for case_id, description in manifest["cases"].items():
        print(f"{case_id}: {description}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Build a fixed, curated train/dev-only demonstration bundle; never evaluation evidence."""

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pandas as pd

from unknownid.paths import CURATED, DEMO, existing_oracle_path

CASES = {
    "case-127895a5f433": "Initial ambiguity resolved at 40 eV; 30 eV remains ambiguous.",
    "case-250b6ac895d0": "Confident initial evidence: planner stops and saves an optional scan.",
    "case-e40ea5350560": "Remains ambiguous after measurement: responsible abstention.",
    "case-f1a2b961ba46": "Both energies help, but 40 eV gives larger entropy reduction.",
}


def main():
    splits = json.loads((CURATED / "splits.json").read_text())["assignment"]
    oracle = json.loads(existing_oracle_path().read_text())
    private = {cid: oracle[cid] for cid in CASES}
    assert all(
        c["split"] in {"train", "dev"} and splits[c["true_molecule_id"]] in {"train", "dev"}
        for c in private.values()
    )
    public = pd.read_parquet(CURATED / "public_cases.parquet")
    public = public[public.case_id.isin(CASES)].copy()
    public["original_split"] = public["split"]
    public["split"] = "demo"
    candidate_ids = set(cid for ids in public.candidate_ids for cid in ids)
    # Exclude even endpoint references for frozen test identities from demo.
    test_ids = {m for m, s in splits.items() if s == "test"}
    assert not candidate_ids & test_ids
    library = pd.read_parquet(CURATED / "library.parquet")
    library = library[library.molecule_id.isin(candidate_ids)].copy()
    DEMO.mkdir(parents=True, exist_ok=True)
    library.to_parquet(DEMO / "library.parquet", index=False)
    public.to_parquet(DEMO / "public_cases.parquet", index=False)
    (DEMO / "sealed_observations.json").write_text(json.dumps(private, indent=2) + "\n")
    accessions = set(library.accession)
    for c in private.values():
        accessions.update(c["hidden_accessions"].values())
    records = pd.read_parquet(CURATED / "records.parquet")
    provenance = [
        dict(
            accession=r.accession,
            license=r.license,
            source_sha256=r.source_sha256,
            url=r.record_url,
            attribution="MassBank / University of Athens contributor",
            source_commit="befc8a1e2f2aef899747797c081a5d80fab12fe7",
            modifications="Invalid/low peaks removed; intensities base-peak normalized; see frozen selection config.",
        )
        for _, r in records[records.accession.isin(accessions)].sort_values("accession").iterrows()
    ]
    for record in provenance:
        raw_path = DEMO / "source_records" / f"{record['accession']}.txt"
        raw = raw_path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record["source_sha256"]
        record["original_attribution"] = [
            line
            for line in raw.decode().splitlines()
            if line.startswith(("AUTHORS:", "COPYRIGHT:", "LICENSE:", "PUBLICATION:"))
        ]
    for name in ("error_model.json", "calibration.json"):
        shutil.copyfile(CURATED / name, DEMO / name)
    (DEMO / "attribution.json").write_text(json.dumps(provenance, indent=2) + "\n")
    manifest = dict(
        label="Demo mode — curated development examples",
        evidence_status="Curated development demonstrations, selected for illustration; not independent evaluation evidence.",
        selection="Four explicit train/dev IDs; curated using train/dev outcomes only. Training examples illustrate mechanics and are not validation. No frozen test identities, endpoints or observations included.",
        cases=CASES,
        hashes={
            str(p.relative_to(DEMO)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in DEMO.rglob("*")
            if p.is_file() and p.name != "manifest.json"
        },
    )
    (DEMO / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Built {len(public)} development cases, {len(candidate_ids)} reference molecules, {len(provenance)} attributed records"
    )


if __name__ == "__main__":
    main()

"""Draw public candidate structures; requires research RDKit only at build time."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rdkit import Chem, rdBase
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/demo/public/candidates.json"
DEST = ROOT / "app/assets/structures"


def run():
    DEST.mkdir(parents=True, exist_ok=True)
    records = json.loads(SOURCE.read_text())
    manifest = {
        "source": "data/demo/public/candidates.json",
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "generator": "scripts/render_demo_structures.py",
        "rdkit_version": rdBase.rdkitVersion,
        "candidates": {},
    }
    chalcone = Chem.MolFromSmarts("O=C(C=Cc1ccccc1)c1ccccc1")
    for record in sorted(records, key=lambda row: row["compound_full_inchikey"]):
        cid = record["compound_full_inchikey"]
        molecule = Chem.MolFromSmiles(record["canonical_smiles"])
        if molecule is None:
            raise ValueError(f"invalid public SMILES: {cid}")
        rdDepictor.Compute2DCoords(molecule)
        drawer = rdMolDraw2D.MolDraw2DSVG(420, 230)
        drawer.drawOptions().padding = 0.12
        drawer.DrawMolecule(molecule)
        drawer.FinishDrawing()
        path = DEST / f"{cid}.svg"
        path.write_text(drawer.GetDrawingText())
        info = {
            "smiles": record["canonical_smiles"],
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if molecule.HasSubstructMatch(chalcone):
            counts = []
            for ring in molecule.GetRingInfo().AtomRings():
                if len(ring) != 6 or not all(
                    molecule.GetAtomWithIdx(i).GetIsAromatic() for i in ring
                ):
                    continue
                count = sum(
                    neighbor.GetAtomicNum() == 8 and neighbor.GetTotalNumHs() > 0
                    for index in ring
                    for neighbor in molecule.GetAtomWithIdx(index).GetNeighbors()
                    if neighbor.GetIdx() not in ring
                )
                counts.append(count)
            if len(counts) == 2:
                info["ring_oh_counts"] = sorted(counts, reverse=True)
                info["description"] = (
                    f"OH groups across the two rings: {max(counts)} + {min(counts)}."
                )
                if sum(counts) == 3:
                    info["family"] = "Trihydroxychalcone"
        manifest["candidates"][cid] = info
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Rendered {len(records)} structures from public candidate SMILES; no spectra or truth read."
    )


if __name__ == "__main__":
    run()

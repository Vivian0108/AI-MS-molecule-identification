"""Single-source report rendering, plot and generation provenance."""

import hashlib
import json
import platform
import subprocess
from pathlib import Path

from unknownid.eval.evaluate import build_report
from unknownid.paths import ROOT


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generation_metadata():
    paths = [
        "config/selection.yaml",
        "config/acquisition.yaml",
        "data/curated/splits.json",
        "data/curated/error_model.json",
        "data/curated/calibration.json",
        "uv.lock",
    ]
    return {
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        ),
        "python": platform.python_version(),
        "hashes": {p: sha256(ROOT / p) for p in paths},
        "dataset_version": json.loads((ROOT / "data/curated/dataset_version.json").read_text()),
        "metric_schema": "stage-aligned-v2; benefit UnknownID-baseline; scans baseline-UnknownID; unsuffixed fields are legacy stage-two aliases",
    }


def render_report(payload):
    markdown = build_report(
        summaries=payload["summaries"],
        comparisons=payload["paired_comparisons"],
        ig=payload["ig_validation"],
        failures=payload["failures"],
        calibration=payload["calibration"],
        config=payload["config"],
        n_cases=payload["n_cases"],
        open_world=payload["open_world"],
        generated_at=payload["generated_at_utc"],
    )
    markdown += (
        "\n## Energy and stop diagnostics (not primary evidence)\n\n```json\n"
        + json.dumps(payload.get("energy_stop_diagnostics", {}), indent=2)
        + "\n```\n"
    )
    return (
        markdown
        + "\n## Generation metadata\n\n```json\n"
        + json.dumps(payload["generation_metadata"], indent=2)
        + "\n```\n"
    )


def write_pareto(payload, output):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 6))
    for index, (name, row) in enumerate(payload["summaries"]["ambiguous"].items()):
        x, y = row["scans_1"], row["accepted_correct_1"]
        xc, yc = row["scans_1_ci"], row["accepted_correct_1_ci"]
        ax.errorbar(
            x,
            y,
            xerr=[[max(0, x - xc[0])], [max(0, xc[1] - x)]],
            yerr=[[max(0, y - yc[0])], [max(0, yc[1] - y)]],
            fmt="o",
            capsize=3,
            label=name,
        )
    ax.set(
        xlabel="Mean optional measurements (stage one)",
        ylabel="Accepted-correct identification rate",
        title="Frozen ambiguous test cohort (n=11); 95% molecule bootstrap intervals",
    )
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)
    output = Path(output)
    if output.suffix == ".svg":
        output.write_text("\n".join(line.rstrip() for line in output.read_text().splitlines()) + "\n")

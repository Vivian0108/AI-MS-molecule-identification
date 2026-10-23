"""Exploratory dev-only CID40/EAD16 complementarity and frozen-planner check."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
from collections import Counter
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from spectrapilot.data.repository import CaseRepository
from spectrapilot.paths import CURATED, ORACLE_PRIVATE, ROOT
from spectrapilot.planning.oracle import VirtualInstrument
from spectrapilot.planning.session import InvestigationSession
from spectrapilot.service import SpectraPilotService
from unknownid.core.ids import make_case_id

OUTPUT = ROOT / "reports" / "spectrapilot"
PRIVATE = ORACLE_PRIVATE / "dev_modality_headroom"
POLICIES = ("cid20_only", "always_cid40", "always_ead16", "separation")
INPUT_PATHS = (
    "configs/multims2.yaml",
    "configs/policies.yaml",
    "data/multims2/curated/cases.parquet",
    "data/multims2/curated/records.parquet",
    "data/multims2/curated/candidate_universe.parquet",
    "data/multims2/curated/split_manifest.json",
    "data/multims2/reference/templates.parquet",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NullLog:
    def write(self, entry):
        pass


def load_dev_inputs():
    """Truth reconstruction is evaluator-side; test query rows are not loaded."""
    cases = (
        pd.read_parquet(
            CURATED / "cases.parquet",
            filters=[
                ("split", "==", "dev"),
                ("precursor_ambiguous", "==", True),
            ],
        )
        .sort_values("case_id")
        .reset_index(drop=True)
    )
    if not cases.case_id.is_unique:
        raise ValueError("duplicate development case IDs")
    compounds = pd.read_parquet(
        CURATED / "candidate_universe.parquet",
        filters=[
            ("split", "==", "dev"),
        ],
        columns=["compound_full_inchikey", "precursor_mz", "name"],
    )
    identities = {}
    selected = set(cases.case_id)
    for compound in compounds.itertuples():
        case_id = make_case_id(str(compound.compound_full_inchikey), float(compound.precursor_mz))
        if case_id in selected:
            if case_id in identities:
                raise ValueError("duplicate dev compound identity")
            identities[case_id] = {
                "true_id": str(compound.compound_full_inchikey),
                "name": str(compound.name),
            }
    if not selected or set(identities) != selected:
        raise ValueError("missing eligible development identities")
    target_ids = [row["true_id"] for row in identities.values()]
    records = pd.read_parquet(
        CURATED / "records.parquet",
        filters=[
            ("split", "==", "dev"),
            ("compound_full_inchikey", "in", target_ids),
        ],
    )
    oracle = {}
    for case in cases.itertuples():
        true_id = identities[case.case_id]["true_id"]
        if true_id not in case.candidate_ids:
            raise ValueError("true dev identity absent from frozen closed-world candidates")
        observations = {}
        for action in ("CID20", "CID40", "EAD16"):
            selected_records = records[
                (records.compound_full_inchikey == true_id) & (records.action == action)
            ]
            if len(selected_records) != 1:
                raise ValueError(f"expected exactly one {action} record for {case.case_id}")
            row = selected_records.iloc[0]
            observations[action] = {
                "action": action,
                "fragmentation": str(row.fragmentation_method),
                "energy_ev": float(row.energy_value),
                "accession": str(row.record_id),
                "peaks_mz": row.peaks_mz.tolist(),
                "peaks_intensity": row.peaks_intensity.tolist(),
            }
        oracle[case.case_id] = {
            "case_id": case.case_id,
            "initial": observations.pop("CID20"),
            "hidden": observations,
        }
    return cases, identities, oracle


def run_branch(service, case_id, policy):
    # A new virtual instrument and session ensure independent one-scan branches.
    session = InvestigationSession(
        case_id,
        service.repository,
        VirtualInstrument(service.oracle),
        service.scorer,
        service.planner,
        action_log=NullLog(),
        budget=1,
    )
    initial = session.ranking().model_dump()
    initial_hash = hashlib.sha256(json.dumps(initial, sort_keys=True).encode()).hexdigest()
    plan = session.plan().model_dump()
    action = {
        "cid20_only": "STOP",
        "always_cid40": "CID40",
        "always_ead16": "EAD16",
        "separation": plan["recommended"]["key"],
    }[policy]
    if action != "STOP":
        session.measure(action)
    investigation = session.stop().model_dump()
    assert len([a for a in investigation["selected_actions"] if a["kind"] == "MEASURE"]) <= 1
    assert not investigation["intervention_history"]
    return {
        "investigation": investigation,
        "initial_hash": initial_hash,
        "chosen_action": action,
        "initial_plan": plan,
    }


def score_outcome(raw, true_id):
    """Only called after the independent policy investigation has finished."""
    result = raw["investigation"]
    evidence = result["candidate_evidence"]
    order = [item["candidate_id"] for item in evidence]
    top1 = order[0] if order else None
    accepted = int(result["decision"] == "IDENTIFIED")
    correct = int(top1 == true_id)
    return {
        "top1_id": top1,
        "top1_correct": correct,
        "accepted": accepted,
        "accepted_correct": int(accepted and correct),
        "accepted_error": int(accepted and not correct),
        "decision": result["decision"],
        "chosen_action": raw["chosen_action"],
        "optional_scans": int(raw["chosen_action"] != "STOP"),
        "top1_support": evidence[0]["weight"] if evidence else None,
        "true_candidate_cosine": next(
            (item["similarity_by_action"] for item in evidence if item["candidate_id"] == true_id),
            {},
        ),
    }


def summarize(rows):
    n = len(rows)
    if not n:
        raise ValueError("cannot summarize an empty cohort")
    accepted = sum(r["accepted"] for r in rows)
    errors = sum(r["accepted_error"] for r in rows)
    optional = sum(r["optional_scans"] for r in rows)
    return {
        "n": n,
        "top1_correct": sum(r["top1_correct"] for r in rows),
        "top1_rate": sum(r["top1_correct"] for r in rows) / n,
        "accepted_correct": sum(r["accepted_correct"] for r in rows),
        "accepted_correct_rate": sum(r["accepted_correct"] for r in rows) / n,
        "accepted": accepted,
        "accepted_error": errors,
        "coverage": accepted / n,
        "selective_risk": errors / accepted if accepted else None,
        "optional_scans": optional,
        "mean_optional_scans": optional / n,
        "total_acquisitions": n + optional,
        "mean_total_acquisitions": 1 + optional / n,
    }


def paired_difference(a, b, metric, seed, resamples):
    if not a or len(a) != len(b):
        raise ValueError("paired results must have the same nonzero length")
    delta = np.array([x[metric] - y[metric] for x, y in zip(a, b)], dtype=float)
    rng = np.random.default_rng(seed)
    samples = delta[rng.integers(0, len(delta), size=(resamples, len(delta)))].mean(axis=1)
    return {
        "metric": metric,
        "direction": "planner minus fixed policy; negative optional scans means savings",
        "mean_difference_per_case": float(delta.mean()),
        "ci95": np.quantile(samples, [0.025, 0.975]).tolist(),
        "bootstrap_unit": "molecule",
        "resamples": resamples,
        "seed": seed,
    }


def exact_mcnemar(a, b, metric):
    if not a or len(a) != len(b):
        raise ValueError("paired results must have the same nonzero length")
    wins = sum(x[metric] == 1 and y[metric] == 0 for x, y in zip(a, b))
    losses = sum(x[metric] == 0 and y[metric] == 1 for x, y in zip(a, b))
    return {
        "metric": metric,
        "planner_only_success": wins,
        "fixed_only_success": losses,
        "p_two_sided": float(binomtest(wins, wins + losses).pvalue) if wins + losses else 1.0,
    }


def complementarity(rows, metric):
    groups = {name: [] for name in ("cid40_only", "ead16_only", "both", "neither")}
    for row in rows:
        cid = row["policies"]["always_cid40"][metric]
        ead = row["policies"]["always_ead16"][metric]
        group = (
            "both" if cid and ead else "cid40_only" if cid else "ead16_only" if ead else "neither"
        )
        groups[group].append(row["case_id"])
    return {
        "metric": metric,
        "counts": {key: len(value) for key, value in groups.items()},
        "case_ids": groups,
        "hindsight_best_measurement_count": sum(
            len(groups[k]) for k in ("both", "cid40_only", "ead16_only")
        ),
        "diagnostic_only": True,
    }


def choice_diagnostic(rows, metric):
    sensitive = [
        row
        for row in rows
        if row["policies"]["always_cid40"][metric] != row["policies"]["always_ead16"][metric]
    ]
    chose_better = 0
    measured = 0
    stopped = 0
    for row in sensitive:
        outcome = row["policies"]["separation"]
        if outcome["chosen_action"] == "STOP":
            stopped += 1
        else:
            measured += 1
            chose_better += outcome[metric]
    best_stop_or_measure = [
        max(row["policies"][policy][metric] for policy in POLICIES[:3]) for row in rows
    ]
    planner_values = [row["policies"]["separation"][metric] for row in rows]
    regret = [best - actual for best, actual in zip(best_stop_or_measure, planner_values)]
    assert all(value >= 0 for value in regret)
    return {
        "metric": metric,
        "diagnostic_only": True,
        "n_sensitive": len(sensitive),
        "n_ties_excluded": len(rows) - len(sensitive),
        "n_sensitive_measured": measured,
        "n_sensitive_stopped": stopped,
        "n_chose_successful_modality": chose_better,
        "choice_accuracy_among_measured_sensitive": chose_better / measured if measured else None,
        "choice_success_fraction_including_stops_as_nonselection": chose_better / len(sensitive)
        if sensitive
        else None,
        "note": "STOP can be appropriate; it is not counted as choosing a measurement modality.",
        "hindsight_best_stop_or_measure_count": sum(best_stop_or_measure),
        "planner_success_count": sum(planner_values),
        "planner_regret_count": sum(regret),
        "mean_planner_regret": float(np.mean(regret)),
    }


def analyze(rows, seed, resamples):
    summaries = {
        policy: summarize([row["policies"][policy] for row in rows]) for policy in POLICIES
    }
    random_rows = [
        {
            key: (row["policies"]["always_cid40"][key] + row["policies"]["always_ead16"][key]) / 2
            for key in (
                "top1_correct",
                "accepted",
                "accepted_correct",
                "accepted_error",
                "optional_scans",
            )
        }
        for row in rows
    ]
    summaries["random_expected_50_50"] = summarize(random_rows)
    comparisons = {}
    a = [row["policies"]["separation"] for row in rows]
    for fixed in ("cid20_only", "always_cid40", "always_ead16"):
        b = [row["policies"][fixed] for row in rows]
        comparisons[fixed] = {
            "paired_differences": {
                metric: paired_difference(a, b, metric, seed, resamples)
                for metric in ("top1_correct", "accepted_correct", "optional_scans")
            },
            "mcnemar": {
                metric: exact_mcnemar(a, b, metric)
                for metric in ("top1_correct", "accepted_correct")
            },
        }
    discordant = [
        {
            "case_id": row["case_id"],
            "name": row["name"],
            "true_id": row["true_id"],
            "outcomes": {
                policy: {
                    key: row["policies"][policy][key]
                    for key in (
                        "top1_id",
                        "top1_correct",
                        "accepted_correct",
                        "decision",
                        "chosen_action",
                    )
                }
                for policy in POLICIES
            },
        }
        for row in rows
        if any(
            row["policies"]["always_cid40"][key] != row["policies"]["always_ead16"][key]
            for key in ("top1_correct", "accepted_correct")
        )
    ]
    return {
        "policies": summaries,
        "planner_action_counts": dict(
            Counter(row["policies"]["separation"]["chosen_action"] for row in rows)
        ),
        "complementarity": {
            metric: complementarity(rows, metric) for metric in ("top1_correct", "accepted_correct")
        },
        "choice_diagnostics": {
            metric: choice_diagnostic(rows, metric)
            for metric in ("top1_correct", "accepted_correct")
        },
        "paired_planner_vs_fixed": comparisons,
        "discordant_cases_diagnostic_only": discordant,
        "top1_identity_differs_between_measurements": sum(
            row["policies"]["always_cid40"]["top1_id"] != row["policies"]["always_ead16"]["top1_id"]
            for row in rows
        ),
        "status_differs_between_measurements": sum(
            row["policies"]["always_cid40"]["decision"]
            != row["policies"]["always_ead16"]["decision"]
            for row in rows
        ),
        "illustration_diagnostics": {
            "diagnostic_only": True,
            "ead_only_top1_rescues_of_wrong_initial_ranking": [
                row["case_id"]
                for row in rows
                if row["policies"]["cid20_only"]["top1_correct"] == 0
                and row["policies"]["always_cid40"]["top1_correct"] == 0
                and row["policies"]["always_ead16"]["top1_correct"] == 1
            ],
            "planner_uses_ead_and_rescues_wrong_initial_ranking": [
                row["case_id"]
                for row in rows
                if row["policies"]["cid20_only"]["top1_correct"] == 0
                and row["policies"]["separation"]["chosen_action"] == "EAD16"
                and row["policies"]["separation"]["top1_correct"] == 1
            ],
            "planner_ead_selected_accepted_correct_count": sum(
                row["policies"]["separation"]["accepted_correct"]
                for row in rows
                if row["policies"]["separation"]["chosen_action"] == "EAD16"
            ),
            "planner_chooses_ead_on_ead_only_accepted_correct_cases": sum(
                row["policies"]["separation"]["chosen_action"] == "EAD16"
                for row in rows
                if row["policies"]["always_ead16"]["accepted_correct"] == 1
                and row["policies"]["always_cid40"]["accepted_correct"] == 0
            ),
        },
    }


def render_markdown(payload):
    n = payload["n"]
    lines = [
        "# CID40 versus EAD16: development-only headroom check",
        "",
        f"**Exploratory development diagnostic, n = {n}. Not a held-out test.** "
        "Frozen test queries were not loaded. No fitting or tuning.",
        "",
        "All policies start from identical CID20 evidence with at most one optional acquisition. "
        "Random is the exact 50:50 expected outcome, not a rounded Monte Carlo result.",
        "",
        "| Policy | Top-1 correct | Accepted-correct | Coverage | Selective risk | Optional scans (total / mean) | Total acquisitions (mean) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for policy, summary in payload["policies"].items():
        risk = (
            "undefined" if summary["selective_risk"] is None else f"{summary['selective_risk']:.1%}"
        )
        lines.append(
            f"| {policy} | {summary['top1_correct']:g}/{n} | {summary['accepted_correct']:g}/{n} | "
            f"{summary['coverage']:.1%} | {risk} | {summary['optional_scans']:g} / "
            f"{summary['mean_optional_scans']:.3f} | {summary['mean_total_acquisitions']:.3f} |"
        )
    lines += [
        "",
        "Selective risk = accepted errors / accepted cases. For random, this is the ratio of expected counts, "
        "not the expectation of the risk ratio. Top-1 alone does not mean an accepted identification.",
        "",
        "## Do the modalities complement each other? (truth-aware diagnostic)",
        "",
        "| Success definition | CID40 only | EAD16 only | Both | Neither | Hindsight best measurement |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for metric, item in payload["complementarity"].items():
        counts = item["counts"]
        lines.append(
            f"| {metric} | {counts['cid40_only']} | {counts['ead16_only']} | {counts['both']} | "
            f"{counts['neither']} | {item['hindsight_best_measurement_count']} |"
        )
    lines += [
        "",
        f"Top-ranked identity differs between measurements on {payload['top1_identity_differs_between_measurements']}/{n} cases; "
        f"decision status differs on {payload['status_differs_between_measurements']}/{n}.",
        "",
        "## Does the existing planner exploit it?",
        "",
        f"Chosen actions: `{json.dumps(payload['planner_action_counts'], sort_keys=True)}`.",
        "",
        "| Success definition | Sensitive cases | Ties excluded | Measured / stopped on sensitive cases | Successful modality choices | Best stop-or-measure count | Planner count | Regret count |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric, item in payload["choice_diagnostics"].items():
        lines.append(
            f"| {metric} | {item['n_sensitive']} | {item['n_ties_excluded']} | "
            f"{item['n_sensitive_measured']} / {item['n_sensitive_stopped']} | "
            f"{item['n_chose_successful_modality']} | {item['hindsight_best_stop_or_measure_count']} | "
            f"{item['planner_success_count']} | {item['planner_regret_count']} |"
        )
    lines += [
        "",
        "Sensitive subsets and hindsight ceilings use hidden outcomes and are diagnostic only. "
        "STOP is not counted as a modality choice and can still be appropriate.",
        "",
        "### Is there a successful adaptive EAD rescue to demonstrate?",
        "",
        f"EAD16 repairs a wrong initial top-ranked identity where CID40 does not on "
        f"{len(payload['illustration_diagnostics']['ead_only_top1_rescues_of_wrong_initial_ranking'])} development cases. "
        f"The existing planner chooses EAD16 and repairs a wrong initial ranking on "
        f"{len(payload['illustration_diagnostics']['planner_uses_ead_and_rescues_wrong_initial_ranking'])} cases. "
        f"Its EAD-selected investigations produce "
        f"{payload['illustration_diagnostics']['planner_ead_selected_accepted_correct_count']} accepted-correct identifications.",
        "",
        "## Paired planner-minus-fixed differences",
        "",
        "Positive benefit differences favor the planner; negative optional-scan differences mean fewer scans. "
        "Intervals are molecule bootstrap 95%; p-values are unadjusted exact two-sided McNemar tests.",
        "",
        "| Fixed comparator | Metric | Difference per case | 95% CI | Planner-only / fixed-only successes | McNemar p |",
        "|---|---|---:|---|---:|---:|",
    ]
    for fixed, comparison in payload["paired_planner_vs_fixed"].items():
        for metric, item in comparison["paired_differences"].items():
            test = comparison["mcnemar"].get(metric)
            counts = (
                f"{test['planner_only_success']} / {test['fixed_only_success']}" if test else "—"
            )
            p = f"{test['p_two_sided']:.6g}" if test else "—"
            lines.append(
                f"| {fixed} | {metric} | {item['mean_difference_per_case']:+.4f} | "
                f"[{item['ci95'][0]:+.4f}, {item['ci95'][1]:+.4f}] | {counts} | {p} |"
            )
    lines += [
        "",
        "## True-candidate template fit (diagnostic)",
        "",
        "| Action | Median cosine | Template sources |",
        "|---|---:|---|",
    ]
    for action, item in payload["true_reference_diagnostics"].items():
        cosine = "undefined" if item["median_cosine"] is None else f"{item['median_cosine']:.4f}"
        lines.append(f"| {action} | {cosine} | {json.dumps(item['sources'], sort_keys=True)} |")
    lines += [
        "",
        "## Discordant development cases (outcome-conditioned illustrations only)",
        "",
        "CID/EAD cells are top-1 correctness / accepted-correct. Full identities, scores, plans "
        "and outcomes are in the JSON. Cases below do not define the primary dev cohort.",
        "",
        "| Case | Compound | CID40 | EAD16 | Planner action | Planner accepted-correct |",
        "|---|---|---:|---:|---|---:|",
    ]
    for row in payload["discordant_cases_diagnostic_only"]:
        outcomes = row["outcomes"]
        cid, ead, planner = (
            outcomes[key] for key in ("always_cid40", "always_ead16", "separation")
        )
        name = row["name"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {row['case_id']} | {name} | {cid['top1_correct']} / {cid['accepted_correct']} | "
            f"{ead['top1_correct']} / {ead['accepted_correct']} | {planner['chosen_action']} | {planner['accepted_correct']} |"
        )
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines += ["", "Reproduce: `make modality-headroom` after dependency installation.", ""]
    return "\n".join(lines)


def run():
    input_hashes = {path: sha256(ROOT / path) for path in INPUT_PATHS}
    cases, identities, oracle = load_dev_inputs()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    oracle_path = PRIVATE / "cases.json"
    oracle_path.write_text(json.dumps(oracle, separators=(",", ":")) + "\n")
    service = SpectraPilotService(oracle_path=oracle_path)
    service.repository = CaseRepository(cases, service.references)
    seed = int(service.selection_cfg.get_path("evaluation.seed"))
    resamples = int(service.selection_cfg.get_path("evaluation.bootstrap_resamples"))
    rows = []
    for index, case in enumerate(cases.itertuples()):
        raw = {policy: run_branch(service, case.case_id, policy) for policy in POLICIES}
        assert len({branch["initial_hash"] for branch in raw.values()}) == 1
        truth = identities[case.case_id]
        outcomes = {
            policy: score_outcome(branch, truth["true_id"]) for policy, branch in raw.items()
        }
        chosen = {"STOP": "cid20_only", "CID40": "always_cid40", "EAD16": "always_ead16"}[
            outcomes["separation"]["chosen_action"]
        ]
        assert outcomes["separation"] == outcomes[chosen]
        rows.append(
            {
                "case_id": case.case_id,
                "split": "dev",
                "n_candidates": len(case.candidate_ids),
                **truth,
                "policies": outcomes,
                "initial_evidence_sha256": raw["separation"]["initial_hash"],
                "planner_initial_plan": raw["separation"]["initial_plan"],
            }
        )
        if (index + 1) % 12 == 0:
            print(f"Evaluated {index + 1}/{len(cases)} development cases", flush=True)
    summary = analyze(rows, seed, resamples)
    references = {}
    for action, policy in (
        ("CID20", "cid20_only"),
        ("CID40", "always_cid40"),
        ("EAD16", "always_ead16"),
    ):
        values = [row["policies"][policy]["true_candidate_cosine"].get(action) for row in rows]
        values = [value for value in values if value is not None]
        sources = Counter(
            service.references.template(row["true_id"], action).source for row in rows
        )
        references[action] = {
            "n": len(values),
            "median_cosine": float(np.median(values)) if values else None,
            "sources": dict(sources),
        }
    assert input_hashes == {path: sha256(ROOT / path) for path in INPUT_PATHS}
    payload = {
        "study": "CID40 versus EAD16 modality headroom",
        "label": "EXPLORATORY DEVELOPMENT DIAGNOSTIC; not a held-out test",
        "n": len(rows),
        "cohort_rule": "all complete precursor-ambiguous development cases",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "protocol_commit": "e84247c",
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(),
        "dataset": {
            "name": service.selection_cfg.get_path("dataset.name"),
            "source_repository": service.selection_cfg.get_path("dataset.source_repo"),
            "source_commit": service.selection_cfg.get_path("dataset.commit"),
        },
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "pyarrow", "scipy", "pydantic")
        },
        "dependency_lock_sha256": sha256(ROOT / "uv.lock") if (ROOT / "uv.lock").exists() else None,
        "input_sha256": input_hashes,
        "source_sha256": {
            path: sha256(ROOT / path)
            for path in (
                "scripts/check_modality_headroom.py",
                "docs/dev_modality_headroom_protocol.md",
                "src/spectrapilot/service.py",
                "src/spectrapilot/planning/session.py",
                "src/spectrapilot/planning/separation.py",
                "src/spectrapilot/science/scoring.py",
            )
        },
        "inputs_unchanged": True,
        "initial_states_identical_across_policies": True,
        "true_reference_diagnostics": references,
        **summary,
        "rows": rows,
        "limitations": [
            "Development-only exploratory analysis, not an independent test or generalization estimate.",
            "Closed-world library: true identity is present; no open-world identification claim.",
            "CID40 can use measured CID60 references; EAD16 uses predicted kNN templates. Pipeline comparison is confounded by reference quality.",
            "Relative support is uncalibrated; all existing acceptance thresholds were left unchanged.",
            "Hindsight ceilings and sensitive-case subsets use truth only inside this evaluator and are not deployable policies.",
            "Random numbers are exact expected outcomes of equal-probability measurement choice.",
            "No fitting, tuning, peak interventions, MCP work or canvas work was performed.",
            "Main has no dependency lockfile; package versions are recorded, using the existing research environment.",
        ],
    }
    (OUTPUT / "dev_modality_headroom.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUTPUT / "dev_modality_headroom.md").write_text(render_markdown(payload))
    print(
        json.dumps(
            {
                "n": payload["n"],
                "policies": payload["policies"],
                "complementarity": {
                    key: value["counts"] for key, value in payload["complementarity"].items()
                },
                "planner_action_counts": payload["planner_action_counts"],
            },
            indent=2,
        )
    )
    return payload


if __name__ == "__main__":
    run()

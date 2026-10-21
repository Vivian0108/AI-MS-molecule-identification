"""Outcome-conditioned diagnostics only; never define the primary cohort."""

import numpy as np

from unknownid.eval.baselines import PolicyState
from unknownid.eval.metrics import decide

# Predeclared before the corrected test run, in natural entropy units (nats).
ENTROPY_EPSILON = 0.02


def energy_stop_diagnostics(
    cases, *, references, evaluator, error_model, planner, confidence, tempering
):
    rows = []
    for case in cases:
        if case.n_candidates < 2:
            continue

        def fresh():
            return PolicyState(
                case,
                references=references,
                evaluator=evaluator,
                error_model=error_model,
                tempering=tempering,
            )

        initial = fresh()
        plan = planner.plan(
            case.case_id,
            weights=initial.weights,
            templates=case.templates,
            precursors={c.molecule_id: c.precursor_mz for c in case.candidates},
            observed_energies=[20],
            remaining_budget=1,
        )
        options = planner.rank_options(
            weights=initial.weights,
            templates=case.templates,
            precursors={c.molecule_id: c.precursor_mz for c in case.candidates},
            energies=[30, 40],
        )
        selected = options[0].energy_ev if options else None
        gains, accepted = {}, {}
        d0 = decide(initial.weights, initial.evidence, **confidence)
        initial_correct = int(d0.decision == "identified" and d0.top_candidate == case.molecule_id)
        for energy in (30, 40):
            branch = fresh()
            branch.measure(energy)
            gains[energy] = initial.stage(0).entropy - branch.stage(1).entropy
            decision = decide(branch.weights, branch.evidence, **confidence)
            accepted[energy] = int(
                decision.decision == "identified" and decision.top_candidate == case.molecule_id
            )
        sensitive = abs(gains[30] - gains[40]) > ENTROPY_EPSILON
        stopping = plan.recommended.kind == "stop"
        best_gain = max(gains.values())
        # A measurement is materially helpful if it improves the accepted-correct
        # decision, or reduces relative-support entropy by > epsilon without losing one.
        helps = {
            e: accepted[e] > initial_correct
            or (accepted[e] >= initial_correct and gains[e] > ENTROPY_EPSILON)
            for e in (30, 40)
        }
        chosen = plan.recommended.energy_ev
        # Net entropy utility charges epsilon per optional measurement; stop utility is zero.
        utilities = {e: gains[e] - ENTROPY_EPSILON for e in (30, 40)}
        chosen_utility = 0 if stopping else utilities[chosen]
        rows.append(
            dict(
                case_id=case.case_id,
                actual_entropy_reduction={str(e): gains[e] for e in gains},
                accepted_correct_initial=initial_correct,
                accepted_correct_by_energy={str(e): accepted[e] for e in accepted},
                selected_energy=selected,
                action=plan.recommended.kind,
                measured_energy=chosen,
                energy_sensitive=sensitive,
                tie=not sensitive,
                selection_correct=(gains[selected] >= best_gain - ENTROPY_EPSILON)
                if selected
                else None,
                chosen_energy_regret=best_gain - gains[selected] if selected else None,
                stopped=stopping,
                neither_helps=not any(helps.values()),
                missed_benefit=stopping and any(helps.values()),
                unnecessary_measurement=(not stopping and not helps[chosen]),
                stop_30_40_regret=max(0, *utilities.values()) - chosen_utility,
            )
        )

    def aggregate(items):
        stopped = [r for r in items if r["stopped"]]
        measured = [r for r in items if not r["stopped"]]
        sensitive = [r for r in items if r["energy_sensitive"]]

        def avg(key, subset=items):
            vals = [r[key] for r in subset if r[key] is not None]
            return float(np.mean(vals)) if vals else None

        return dict(
            n=len(items),
            n_stopped=len(stopped),
            n_measured=len(measured),
            energy_sensitive_fraction=len(sensitive) / len(items) if items else None,
            ties=sum(r["tie"] for r in items),
            selection_accuracy_ties_count_correct=avg("selection_correct"),
            mean_chosen_energy_regret=avg("chosen_energy_regret"),
            fraction_scans_avoided=len(stopped) / len(items) if items else None,
            stop_neither_helps_fraction=avg("neither_helps", stopped),
            missed_benefit_rate_among_stops=avg("missed_benefit", stopped),
            unnecessary_measurement_rate_among_measurements=avg(
                "unnecessary_measurement", measured
            ),
            mean_regret_best_stop_30_40=avg("stop_30_40_regret"),
        )

    return dict(
        epsilon_nats=ENTROPY_EPSILON,
        definitions="Signed entropy reductions. Energy tie: absolute 30/40 difference <= epsilon; ties count correct in selection accuracy. Material help: gains accepted-correct, or entropy reduction > epsilon without losing accepted-correct. Net entropy utility = reduction minus epsilon per scan; stop utility = 0. Regret compares stop/30/40. Conditional rates use explicitly named denominators. Entropy is relative-support uncertainty, not identity probability.",
        all_ambiguous=aggregate(rows),
        energy_sensitive_diagnostic_only=aggregate([r for r in rows if r["energy_sensitive"]]),
        rows=rows,
    )

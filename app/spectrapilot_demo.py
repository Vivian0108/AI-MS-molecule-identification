"""One-screen local SpectraPilot investigation demo."""

from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from spectrapilot.demo import DemoService

st.set_page_config(page_title="SpectraPilot · Measurement triage", page_icon="🧪", layout="wide")
st.markdown(
    """<style>
.stApp {background:#f6f8f7;color:#142e35} .block-container {padding-top:2rem;max-width:1400px}
h1,h2,h3 {letter-spacing:-.035em} h1 {font-size:2.7rem!important}
[data-testid="stMetric"] {background:white;border:1px solid #dce7e2;border-radius:12px;padding:14px}
[data-testid="stSidebar"] {background:#eaf1ee}
.eyebrow {color:#087b70;font:600 12px monospace;letter-spacing:.16em;margin-bottom:8px}
.scope {color:#536a6c;font-size:14px;margin-bottom:18px}
.flow {background:#122f36;color:#e5f4ed;border-radius:14px;padding:16px 22px;margin:18px 0}
</style>""",
    unsafe_allow_html=True,
)


def service():
    if "pilot" not in st.session_state:
        st.session_state.pilot = DemoService()
    return st.session_state.pilot


def reset():
    current = st.session_state.get("active_case")
    if current:
        service().reset_case(current)
    for key in (
        "active_case",
        "baseline",
        "change",
        "identity",
        "spectrum_action",
        "peak_index",
        "edit_action",
    ):
        st.session_state.pop(key, None)


def start(case_id):
    service().reset_case(case_id)
    service().start_case(case_id)
    st.session_state.active_case = case_id
    st.session_state.baseline = service().get_evidence(case_id)
    st.session_state.spectrum_action = "CID20"


def measure(case_id, action):
    before = service().get_evidence(case_id)
    service().measure(case_id, action)
    st.session_state.change = (
        before,
        service().get_evidence(case_id),
        f"Archived {action} measurement revealed",
    )
    st.session_state.spectrum_action = action


def exclude(case_id, action, index, reason):
    if not reason.strip():
        st.session_state.edit_error = "Add a reason before excluding a peak."
        return
    before = service().get_evidence(case_id)
    try:
        result = service().exclude_observed_peak(case_id, action, index, reason)
        st.session_state.change = (
            before,
            result["evidence"],
            "Peak excluded from scoring; original preserved",
        )
    except ValueError as exc:
        st.session_state.edit_error = str(exc)


def undo(case_id, intervention_id):
    before = service().get_evidence(case_id)
    result = service().undo_intervention(
        case_id, intervention_id, "Scientist restored the original evidence."
    )
    st.session_state.change = (before, result["evidence"], "Exclusion undone; evidence replayed")


def stop(case_id):
    service().stop(case_id)


def identity(case_id):
    st.session_state.identity = service().reveal_identity(case_id)


def spectrum_plot(observation, excluded):
    colors = [
        "#b8c3c1" if index in excluded else "#087f74" for index in range(observation["n_peaks"])
    ]
    figure = go.Figure(
        go.Bar(
            x=observation["mz"],
            y=observation["intensity"],
            marker_color=colors,
            width=max(0.12, (max(observation["mz"]) - min(observation["mz"])) / 240),
            customdata=list(range(observation["n_peaks"])),
            hovertemplate="Peak #%{customdata}<br>m/z %{x:.5f}<br>Relative intensity %{y:.3f}<extra></extra>",
        )
    )
    figure.update_layout(
        height=310,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis_title="m/z",
        yaxis_title="Relative intensity",
        font=dict(color="#183d43"),
        showlegend=False,
    )
    figure.update_yaxes(range=[0, 1.08], gridcolor="#eef3f1")
    return figure


pilot = service()
examples = pilot.manifest["cases"]
with st.sidebar:
    st.markdown("### 🧪 SpectraPilot")
    st.caption("Know when to measure. Know when to stop.")
    selected = st.radio(
        "Try a different outcome",
        range(len(examples)),
        format_func=lambda index: examples[index]["title"],
        key="case_selector",
        on_change=reset,
    )
    example = examples[selected]
    st.button("Restart this example", key="reset_case", on_click=reset, width="stretch")
    st.divider()
    st.caption("Real archived spectra, replayed on request. No live instrument is connected.")
    st.caption("Three selected development examples, not an accuracy test.")

st.title("Do we need another measurement?")
st.write(
    "A spectrum is a molecular fingerprint. When several molecules look alike, "
    "SpectraPilot helps a scientist choose: measure again, stop, or leave the answer unresolved."
)
st.caption("Demo mode — curated development examples · Closed-world library identification")

investigation_tab, results_tab, scope_tab = st.tabs(
    ["Try the demo", "Evidence & results", "About the science"]
)
with investigation_tab:
    if not st.session_state.get("active_case"):
        st.subheader(example["title"])
        st.write(
            "Start with one measured fingerprint and a shortlist of possible molecules. "
            "Then see whether another measurement is worth taking."
        )
        st.button(
            "Start with the first measurement",
            key="start_case",
            type="primary",
            on_click=start,
            args=(example["case_id"],),
        )
        st.caption("You can reveal at most one extra archived spectrum in each example.")
    else:
        case_id = st.session_state.active_case
        evidence = pilot.get_evidence(case_id)
        case = pilot.case_summary(case_id)
        stopped = evidence["stopped"]
        plan = evidence["plan"]
        recommendation = plan["recommended"]
        observations = {item["action"]: item for item in pilot.observations(case_id)}
        preview = evidence["decision_if_stopped"]
        candidates = evidence["ranking"]["candidates"]
        baseline_candidates = st.session_state.baseline["ranking"]["candidates"]
        names = {
            candidate: f"Candidate {chr(65 + index)}"
            for index, candidate in enumerate(sorted(item["candidate_id"] for item in candidates))
        }
        lead = names[candidates[0]["candidate_id"]]
        initial_lead = names[baseline_candidates[0]["candidate_id"]]
        initial_decision = st.session_state.baseline["decision_if_stopped"]
        enough = preview == "IDENTIFIED"
        measured_extra = len(observations) > 1
        answer = "Identification supported" if enough else "Not enough evidence to identify"
        if measured_extra and not enough:
            answer = "Still unresolved — no identification"

        current, next_step = st.columns([1.1, 1], gap="large")
        with current:
            st.subheader("1 · What do we know?")
            if enough:
                st.success(answer)
                st.write(f"**{lead}** meets the current identification rule.")
            else:
                st.warning(answer)
                st.write(
                    f"**{lead}** ranks first, but the evidence does not justify choosing it as the answer."
                )
            st.caption(
                f"{len(observations)} measurement{'s' if len(observations) != 1 else ''} used · "
                f"{len(observations) - 1} extra · {case['n_candidates']} possible library molecules"
            )
            if not measured_extra:
                st.write(
                    "The candidates are possible molecular structures. Their labels stay the same throughout this example."
                )
        with next_step:
            st.subheader("2 · What should we do?")
            if stopped:
                st.write("**Investigation finished.**")
                st.write(
                    "Report the supported identification."
                    if enough
                    else "Report the uncertainty rather than force an answer."
                )
            elif recommendation["kind"] == "MEASURE":
                st.write("**Collect one more spectrum.**")
                st.write(
                    "The planner expects a different measurement to help separate the competing candidates."
                )
                st.button(
                    "Collect one more spectrum",
                    key="measure_recommended",
                    type="primary",
                    on_click=measure,
                    args=(case_id, recommendation["key"]),
                    width="stretch",
                )
                st.caption(
                    f"Reveals real archived {recommendation['key']} data · costs one extra measurement"
                )
                st.button(
                    "Stop here instead",
                    key="stop_case",
                    on_click=stop,
                    args=(case_id,),
                )
            else:
                st.write("**Stop measuring.**")
                if not measured_extra and enough:
                    st.write("The current evidence meets the rule. No extra scan is recommended.")
                    st.caption("Following this recommendation avoids one optional measurement.")
                elif evidence["remaining_budget"] == 0:
                    st.write(
                        "The one-extra-measurement budget is used. Record what the evidence supports."
                    )
                else:
                    st.write(
                        "No extra measurement is recommended. Record what the evidence supports."
                    )
                st.button(
                    "Finish & create report",
                    key="stop_case",
                    type="primary",
                    on_click=stop,
                    args=(case_id,),
                    width="stretch",
                )

        if measured_extra:
            st.subheader("3 · What changed?")
            earlier, now = st.columns(2)
            with earlier:
                with st.container(border=True):
                    st.markdown("**After the first measurement**")
                    st.write(
                        "Identification supported"
                        if initial_decision == "IDENTIFIED"
                        else "Unresolved"
                    )
                    st.caption(f"Leading match: {initial_lead}")
            with now:
                with st.container(border=True):
                    st.markdown("**After the extra measurement**")
                    st.write("Identification supported" if enough else "Still unresolved")
                    st.caption(f"Leading match: {lead}")
            if enough and initial_decision != "IDENTIFIED":
                st.write(
                    "**The extra measurement supplied enough evidence to support an identification.**"
                )
            elif not enough:
                st.write(
                    "**The evidence is still insufficient. The responsible result is to leave the answer unresolved.**"
                )
            else:
                st.write(
                    "The evidence was updated; the current identification rule is still satisfied."
                )
            if initial_lead != lead:
                st.caption(f"The leading match changed from {initial_lead} to {lead}.")
        elif stopped and enough:
            st.subheader("3 · What was saved?")
            st.write(
                "**One optional measurement avoided.** The report uses only the first spectrum."
            )
        if st.session_state.get("change"):
            st.caption(st.session_state.change[2])
        st.caption(
            "An accepted identification can still be wrong. This example assumes the true molecule is in the library."
        )

        if stopped:
            st.subheader("Save the outcome")
            st.button(
                "Check curated source identity",
                key="reveal_identity",
                on_click=identity,
                args=(case_id,),
            )
            if st.session_state.get("identity"):
                check = st.session_state.identity
                st.info(
                    f"Curated source: {check['name']} · outcome: {check['outcome']}. This is a selected development illustration."
                )
            exported = pilot.report(case_id)
            json_col, md_col = st.columns(2)
            json_col.download_button(
                "Download JSON report",
                json.dumps(exported, indent=2),
                file_name=f"spectrapilot-{case_id}.json",
                mime="application/json",
                key="download_json",
                width="stretch",
            )
            md_col.download_button(
                "Download Markdown report",
                exported["report_markdown"],
                file_name=f"spectrapilot-{case_id}.md",
                mime="text/markdown",
                key="download_md",
                width="stretch",
            )

        st.divider()
        with st.expander("Inspect the scientific evidence"):
            st.caption("Optional detail: spectra, candidate scores and the planner's calculation.")
            left, right = st.columns(2)
            with left:
                st.subheader("Measured fingerprint")
                action = st.selectbox(
                    "Acquired observation", list(observations), key="spectrum_action"
                )
                excluded_indices = {
                    item["peak_index"]
                    for item in evidence["active_peak_exclusions"]
                    if item["action"] == action
                }
                st.plotly_chart(
                    spectrum_plot(observations[action], excluded_indices),
                    width="stretch",
                    key="observed_spectrum",
                )
                st.caption(
                    f"{action} · archived experimental spectrum · {case['precursor_mz']:.5f} m/z"
                )
            with right:
                st.subheader("Candidate evidence")
                baseline = {item["candidate_id"]: item["weight"] for item in baseline_candidates}
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Candidate": names[item["candidate_id"]],
                                "Formula": item["formula"],
                                "Support": item["weight"],
                                "Change": item["weight"] - baseline.get(item["candidate_id"], 0),
                                "Best cosine": max(item["similarity_by_action"].values()),
                            }
                            for item in candidates
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
                st.caption(
                    "Support is a relative ranking score, not a calibrated identity probability."
                )
            for item in candidates:
                st.write(f"{names[item['candidate_id']]} · {item['name']} · {item['candidate_id']}")
            st.write("Planner calculation: " + plan["note"])
            if plan["options"]:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Action": row["action"]["key"],
                                "Separation": row["separation"],
                                "Reference reliability": row["reliability"],
                                "Heuristic score": row["score"],
                            }
                            for row in plan["options"]
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
            st.caption(
                "The planner uses predicted references; it cannot read the unrevealed measured spectrum."
            )

        if not stopped:
            with st.expander("Choose a different measurement (advanced)"):
                available = [action for action in ("CID40", "EAD16") if action not in observations]
                manual = st.selectbox("Optional action", available, key="manual_action")
                st.button(
                    "Reveal selected measurement",
                    key="manual_measure",
                    disabled=evidence["remaining_budget"] == 0,
                    on_click=measure,
                    args=(case_id, manual),
                )
        with st.expander("Scientist control · test a peak exclusion", expanded=False):
            st.caption(
                "Sensitivity analysis, not proof of contamination. Original peaks and every edit remain auditable. Indices refer to the original spectrum."
            )
            edit_action = st.selectbox(
                "Observation to edit", list(observations), key="edit_action", disabled=stopped
            )
            current = observations[edit_action]
            index = st.selectbox(
                "Original peak",
                list(range(current["n_peaks"])),
                format_func=lambda index: (
                    f"#{index} · m/z {current['mz'][index]:.5f} · intensity {current['intensity'][index]:.3f}"
                ),
                key=f"peak_index_{case_id}_{edit_action}",
                disabled=stopped,
            )
            reason = st.text_input(
                "Reason for exclusion",
                value="Sensitivity check: investigate a possible contaminant.",
                max_chars=500,
                key="edit_reason",
                disabled=stopped,
            )
            already_excluded = index in {
                item["peak_index"]
                for item in evidence["active_peak_exclusions"]
                if item["action"] == edit_action
            }
            st.button(
                "Exclude peak & recompute",
                key="exclude_peak",
                on_click=exclude,
                args=(case_id, edit_action, index, reason),
                disabled=stopped or already_excluded,
            )
            if st.session_state.get("edit_error"):
                st.error(st.session_state.pop("edit_error"))
            for entry in evidence["active_peak_exclusions"]:
                st.button(
                    f"Undo {entry['intervention_id']} · {entry['action']} peak #{entry['peak_index']}",
                    key=f"undo_{entry['intervention_id']}",
                    on_click=undo,
                    args=(case_id, entry["intervention_id"]),
                    disabled=stopped,
                )

        with st.expander("Audit trail"):
            st.write(
                {
                    "observed_actions": evidence["observed_actions"],
                    "remaining_budget": evidence["remaining_budget"],
                    "active_exclusions": evidence["active_peak_exclusions"],
                    "intervention_history": evidence["intervention_history"],
                    "original_observation_hashes": evidence["observations"],
                }
            )

with results_tab:
    st.subheader("Measured tradeoffs, with their limits")
    st.warning(
        "Exploratory grouped cross-validated TRAINING estimate · 277 ambiguous molecules · not independent test validation."
    )
    st.write("With donor-agreement references and the training-library CID60 strategy:")
    values = pilot.results["library_assisted"]
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Policy": label,
                    "Accepted-correct": values[key]["accepted_correct"],
                    "Accepted errors": values[key]["accepted_error"],
                    "Optional acquisitions": values[key]["optional_scans"],
                }
                for key, label in (("separation", "Planner"), ("always_cid40", "Always CID40"))
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    saved = 1 - values["separation"]["optional_scans"] / values["always_cid40"]["optional_scans"]
    st.write(
        f"**{saved:.0%} fewer optional acquisitions**, with {values['always_cid40']['accepted_correct'] - values['separation']['accepted_correct']:g} fewer accepted-correct identifications in this sample. This is a measured tradeoff, not proof of equivalent accuracy."
    )
    with st.expander("Reference-construction experiment"):
        st.caption("Different track: all references predicted from non-held-out training donors.")
        compare = pilot.results["predicted_reference_comparison"]
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Reference method": key,
                        "Accepted-correct": row["accepted_correct"],
                        "Accepted errors": row["accepted_error"],
                        "Optional acquisitions": row["optional_scans"],
                    }
                    for key, row in compare.items()
                ]
            ),
            hide_index=True,
        )
        interval = pilot.results["primary_interval"]
        st.write(
            f"Paired accepted-correct gain: {100 * interval['mean_difference']:.1f} percentage points (95% scaffold bootstrap interval {100 * interval['ci95'][0]:.1f}–{100 * interval['ci95'][1]:.1f})."
        )
    st.download_button(
        "Download scientific report",
        (pilot.bundle / "public/scientific_report.md").read_text(),
        file_name="spectrapilot-scientific-report.md",
        mime="text/markdown",
        key="download_science",
    )
    for limitation in pilot.results["limitations"]:
        st.caption("• " + limitation)
    st.caption(
        "The demo additionally uses allowed development CID60 references. Its three curated examples are not the training-CV benchmark."
    )

with scope_tab:
    st.subheader("What this demonstration supports")
    st.write(
        "Closed-world identification assumes the true structure is in the candidate library. SpectraPilot replays archived measurements; it does not perform de novo structure elucidation or control a live instrument."
    )
    st.write(
        "The three examples were selected from development outcomes to illustrate resolving, stopping and abstention. They are not an independent test or an accuracy estimate."
    )
    st.write(
        "Predicted references use structure-neighbour donor-agreement consensus. CID40 can use an explicitly allowed CID60 library reference with an energy mismatch. Both are displayed as evidence, not as unrevealed target measurements."
    )
    st.caption(
        "The original MultiMS2 split has a scaffold-labeling issue; reported follow-up studies derive genuine training-only scaffold folds. No frozen benchmark was rewritten."
    )
    st.markdown(
        f"Source: [MultiMS2](https://github.com/zamboni-lab/MultiMS2/tree/{pilot.manifest['source_commit']}) · DOI [{pilot.manifest['doi']}](https://doi.org/{pilot.manifest['doi']}) · data CC0-1.0"
    )

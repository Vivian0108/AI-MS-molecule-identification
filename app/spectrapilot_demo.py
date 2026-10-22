"""One-screen local SpectraPilot investigation demo."""

from __future__ import annotations

import json

import pandas as pd
from html import escape
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from spectrapilot.demo import DemoService
from spectrapilot.presentation import compare_observed_candidates

ASSETS = Path(__file__).resolve().parent / "assets/structures"
STRUCTURES = json.loads((ASSETS / "manifest.json").read_text())["candidates"]

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
        "compare_action",
        "compare_other",
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
    st.session_state.compare_action = action
    st.session_state.pop("compare_other", None)


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


def candidate_title(item, names):
    label = names[item["candidate_id"]]
    if item["name"] == item["candidate_id"]:
        family = STRUCTURES[item["candidate_id"]].get("family", "Library structure")
        return f"{family} · {label}"
    return f"{item['name']} · {label}"


def structure_gallery(candidates, names, leader):
    for offset in range(0, len(candidates), 5):
        group = candidates[offset : offset + 5]
        for column, item in zip(st.columns(len(group)), group):
            with column:
                st.markdown(f"**{names[item['candidate_id']]}**")
                info = STRUCTURES[item["candidate_id"]]
                st.image(str(ASSETS / info["file"]), width="stretch")
                title = candidate_title(item, names).split(" · ")[0]
                st.markdown(
                    f'<div style="font-size:13px;line-height:1.35;min-height:38px">{escape(title)}</div>',
                    unsafe_allow_html=True,
                )
                if info.get("description"):
                    st.caption(
                        "OH groups: " + " + ".join(str(count) for count in info["ring_oh_counts"])
                    )
                if item["name"] == item["candidate_id"]:
                    st.caption("No common name supplied.")
                if item["candidate_id"] == leader:
                    st.caption("↑ Leading fingerprint match")


def fingerprint_comparison(data, names):
    labels = [f"Sample — measured {data['action']}"]
    for row in data["candidates"]:
        source = (
            "CID60 library proxy"
            if row["reference_source"] == "reference_cid60"
            else "predicted reference"
        )
        labels.append(f"{names[row['candidate_id']]} — {source}")
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.13, subplot_titles=labels
    )
    spectra = [(data["observed_mz"], data["observed_intensity"])] + [
        (row["reference_mz"], row["reference_intensity"]) for row in data["candidates"]
    ]
    for index, ((mz, intensity), color) in enumerate(
        zip(spectra, ["#163c46", "#087f74", "#b5752a"]), 1
    ):
        x, y = [], []
        for mass, height in zip(mz, intensity):
            x.extend([mass, mass, None])
            y.extend([0, height, None])
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                line=dict(color=color, width=2),
                hovertemplate="m/z %{x:.4f}<br>Relative intensity %{y:.2f}<extra></extra>",
            ),
            row=index,
            col=1,
        )
    for mass, _ in data["strongest_fragments"]:
        fig.add_vline(x=mass, line_color="#becdca", line_dash="dot", line_width=1)
    fig.update_layout(
        height=390,
        showlegend=False,
        margin=dict(l=15, r=15, t=35, b=30),
        paper_bgcolor="#f6f8f7",
        plot_bgcolor="white",
    )
    fig.update_yaxes(range=[0, 1.08], showticklabels=False, gridcolor="#eef3f1")
    fig.update_xaxes(title_text="Fragment mass-to-charge (m/z)", row=3, col=1)
    return fig


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

st.title("Which molecule is in this sample?")
st.write(
    "Compare possible structures with the sample’s measured fingerprint. "
    "Then decide: collect more evidence, identify a library match, or leave it unresolved."
)
st.caption("Demo mode — curated development examples · Closed-world library identification")

investigation_tab, results_tab, scope_tab = st.tabs(
    ["Try the demo", "Evidence & results", "About the science"]
)
with investigation_tab:
    if not st.session_state.get("active_case"):
        st.subheader(example["title"])
        intro = pilot.case_summary(example["case_id"])
        st.write(
            f"An unknown sample has an ion at m/z {intro['precursor_mz']:.5f}. "
            f"{intro['n_candidates']} library structures fit that mass. Which one, if any, does its fragmentation fingerprint support?"
        )
        st.caption(
            "We identify a match within this library; we do not infer a new structure from scratch."
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
        by_id = {item["candidate_id"]: item for item in candidates}
        lead = candidate_title(candidates[0], names)
        initial_lead = candidate_title(baseline_candidates[0], names)
        formulas = sorted({item["formula"] for item in candidates})
        st.markdown(
            "**The question: which of these structures produced the sample’s fingerprint?**"
        )
        st.write(
            f"The measured intact ion is at **m/z {case['precursor_mz']:.5f}**. "
            f"All {case['n_candidates']} candidates fit its mass within 10 ppm. "
            + (
                f"They share formula **{formulas[0]}**, so mass alone cannot distinguish their atom arrangements."
                if len(formulas) == 1
                else "Mass alone does not choose among them."
            )
        )
        stable_candidates = sorted(candidates, key=lambda item: item["candidate_id"])
        structure_gallery(stable_candidates, names, candidates[0]["candidate_id"])
        if all(
            STRUCTURES[item["candidate_id"]].get("family") == "Trihydroxychalcone"
            for item in candidates
        ):
            st.caption(
                "Compare the red oxygen / OH groups: these structures differ in where those groups sit on the two rings. That structural difference is real; its fragmentation mechanism is not assigned here."
            )
        st.divider()
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

        st.subheader("Why does a structure have evidence?")
        st.write(
            "We compare the measured fragment peaks with a reference fingerprint associated with each structure. "
            "Matching peak masses and relative heights support a candidate; a shared mass alone is not proof."
        )
        first_id = candidates[0]["candidate_id"]
        preferred_other = (
            baseline_candidates[0]["candidate_id"]
            if measured_extra
            else candidates[1]["candidate_id"]
        )
        others = [item["candidate_id"] for item in candidates if item["candidate_id"] != first_id]
        if preferred_other not in others:
            preferred_other = others[0]
        action = st.selectbox(
            "Compare a measurement already collected",
            list(observations),
            index=len(observations) - 1,
            key="compare_action",
        )
        other_id = st.selectbox(
            "Compare the leading match with",
            others,
            index=others.index(preferred_other),
            format_func=lambda cid: candidate_title(by_id[cid], names),
            key=f"compare_other_{case_id}_{first_id}_{len(observations)}",
        )
        comparison = compare_observed_candidates(pilot, case_id, action, [first_id, other_id])
        a, b = comparison["candidates"]
        st.write(
            f"**{candidate_title(by_id[first_id], names)}** vs **{candidate_title(by_id[other_id], names)}**"
        )
        st.write(
            f"At {action}, whole-fingerprint similarity is **{a['cosine']:.2f} for {names[a['candidate_id']]}** "
            f"and **{b['cosine']:.2f} for {names[b['candidate_id']]}**. "
            "Higher means peak positions and relative heights fit better; it is not an identity probability."
        )
        if not enough:
            st.caption(
                "The collected evidence still does not meet the identification rule, even though one candidate ranks first."
            )
        st.plotly_chart(
            fingerprint_comparison(comparison, names), width="stretch", key="fingerprint_compare"
        )
        peak_rows = []
        for mass, intensity in comparison["strongest_fragments"]:
            row = {"Observed fragment m/z": f"{mass:.4f}"}
            for candidate in comparison["candidates"]:
                match = next(
                    (pair for pair in candidate["matches"] if pair["observed_mz"] == mass), None
                )
                row[names[candidate["candidate_id"]]] = (
                    f"Matches {match['template_mz']:.4f}" if match else "No matching peak"
                )
            peak_rows.append(row)
        if peak_rows:
            st.dataframe(pd.DataFrame(peak_rows), hide_index=True, width="stretch")
        if any(row["reference_source"] == "reference_cid60" for row in comparison["candidates"]):
            st.caption(
                "Reference limitation: the CID40 comparison uses an allowed CID60 library spectrum as a proxy. The energies differ; it is not a measured CID40 reference for that candidate."
            )
        else:
            st.caption(
                "These are predicted reference fingerprints from training structure-neighbours, not experimental spectra of each candidate at this energy."
            )
        st.caption(
            f"Rows show the three strongest measured fragment peaks, excluding the intact ion; match tolerance ±{comparison['tolerance_da']:.2f} Da. The score uses the whole spectrum, including intensity agreement. Matching a peak does not prove a particular bond break or fragment structure. The final ranking combines all collected measurements."
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

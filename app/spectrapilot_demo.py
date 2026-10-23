"""One-screen local SpectraPilot investigation demo."""

from __future__ import annotations

import base64
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
    "<style>" + (ASSETS.parent / "demo.css").read_text() + "</style>",
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
        "analyzed_case",
        "compared_case",
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


def analyze(case_id):
    st.session_state.analyzed_case = case_id


def compare(case_id):
    st.session_state.compared_case = case_id


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
        font=dict(color="#3b596e", size=12, family="sans-serif"),
        showlegend=False,
    )
    figure.update_yaxes(range=[0, 1.08], gridcolor="#eef3f1")
    figure.update_xaxes(range=[min(observation["mz"]) - 5, max(observation["mz"]) + 8])
    return figure


def candidate_title(item, names):
    label = names[item["candidate_id"]]
    if item["name"] == item["candidate_id"]:
        family = STRUCTURES[item["candidate_id"]].get("family", "Library structure")
        return f"{family} · {label}"
    return f"{item['name']} · {label}"


def structure_image(candidate_id):
    svg = (ASSETS / STRUCTURES[candidate_id]["file"]).read_bytes()
    encoded = base64.b64encode(svg).decode("ascii")
    return f'<img src="data:image/svg+xml;base64,{encoded}" alt="Molecular structure {candidate_id}" />'


def structure_gallery(candidates, names, leader):
    cards = []
    for item in candidates:
        cid = item["candidate_id"]
        info = STRUCTURES[cid]
        title = candidate_title(item, names).split(" · ")[0]
        badge = '<span class="rank-tag">Leading match</span>' if cid == leader else ""
        oh = ""
        if info.get("ring_oh_counts"):
            oh = (
                '<span class="oh-tag">OH groups: '
                + " + ".join(str(count) for count in info["ring_oh_counts"])
                + "</span>"
            )
        note = (
            '<div class="source-note">No common name supplied</div>' if item["name"] == cid else ""
        )
        cards.append(
            f'<article class="molecule-card {"leader" if cid == leader else ""}">'
            f'<div class="card-id">{escape(names[cid])}{badge}</div>'
            f'<div role="img" aria-label="Structure of {escape(title, quote=True)}">{structure_image(cid)}</div>'
            f'<div class="compound-name" title="{escape(title, quote=True)}">{escape(title)}</div>{oh}{note}</article>'
        )
    st.html('<div class="structure-grid">' + "".join(cards) + "</div>")


def story_header(pilot, example):
    cid = st.session_state.get("active_case")
    stage, status, closed = 0, "Awaiting sample", False
    if cid:
        stage, status = 1, "Initial spectrum loaded"
        if st.session_state.get("analyzed_case") == cid:
            stage, status = 2, "Mass-compatible structures found"
        if st.session_state.get("compared_case") == cid:
            state = pilot.get_evidence(cid)
            stage, status = 3, "Evidence compared"
            if len(state["observed_actions"]) > 1:
                stage, status = 4, "Additional spectrum acquired"
            if state["stopped"]:
                stage, status, closed = 4, "Investigation closed", True
    st.markdown(
        f'<section class="hero {"compact" if cid else ""}"><div class="hero-top"><span class="hero-kicker">SpectraPilot / Measurement triage</span>'
        f'<span class="session-tag">{escape(example["title"])} · {status}</span></div>'
        '<h1>Which molecule is<br><span class="hero-accent">in this sample?</span></h1>'
        "<p>Follow the spectral evidence. Decide whether another measurement is worth taking. "
        "Record a conclusion you can inspect.</p>"
        '<div class="hero-foot"><span>Archived experimental spectra</span><span>One optional acquisition</span>'
        "<span>Auditable evidence report</span></div></section>"
        '<div class="scope-note">Demo mode — curated development examples · Closed-world library identification</div>',
        unsafe_allow_html=True,
    )
    labels = ["Observe", "Find matches", "Compare evidence", "Decide", "Conclude"]
    steps = []
    for index, label in enumerate(labels):
        done = index < stage or closed
        style = "done" if done else "active" if index == stage else ""
        number = "✓" if done else f"{index + 1:02d}"
        steps.append(f'<div class="journey-step {style}"><b>{number}</b><span>{label}</span></div>')
    st.markdown(
        '<nav class="journey" aria-label="Investigation progress">' + "".join(steps) + "</nav>",
        unsafe_allow_html=True,
    )


def verdict_card(title, supported):
    st.markdown(
        f'<div class="verdict {"good" if supported else ""}"><div class="verdict-kicker">Current evidence</div>'
        f'<div class="verdict-title">{escape(title)}</div></div>',
        unsafe_allow_html=True,
    )


def result_comparison(initial, current, names, initial_decision, enough, action):
    def card(item, title, outcome, style):
        return (
            f'<article class="result-card {style}"><div class="result-label">{title}</div>'
            f"<h3>{outcome}</h3>{structure_image(item['candidate_id'])}"
            f"<p>Leading match: {escape(candidate_title(item, names))}</p></article>"
        )

    before = card(
        initial,
        "Initial 20 eV measurement",
        "Library match supported" if initial_decision in {"REFERENCE_SUPPORTED", "RANKED_ONLY_MATCH", "MASS_ONLY_MATCH"} else "Unresolved",
        "",
    )
    after = card(
        current,
        f"After additional {escape(action)} measurement",
        "Library match supported" if enough else "Still unresolved",
        "final" if enough else "unresolved",
    )
    st.html(
        '<div class="result-pair">'
        + before
        + '<div class="result-arrow">→</div>'
        + after
        + "</div>"
    )


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
        paper_bgcolor="#f4f7fa",
        plot_bgcolor="white",
    )
    fig.update_yaxes(range=[0, 1.08], showticklabels=False, gridcolor="#eef3f1")
    fig.update_xaxes(title_text="Fragment mass-to-charge (m/z)", row=3, col=1)
    return fig


pilot = service()
examples = pilot.discovery_manifest()["cases"]
with st.sidebar:
    st.markdown(
        '<div class="brand"><span class="brand-mark">SP</span>SpectraPilot</div><div class="brand-sub">From spectra to decisions</div>',
        unsafe_allow_html=True,
    )
    selected = st.radio(
        "Choose an unknown sample",
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

story_header(pilot, example)

investigation_tab, library_tab, results_tab, scope_tab = st.tabs(
    ["Investigate", "Reference library", "Evidence & results", "About the science"]
)
with investigation_tab:
    if not st.session_state.get("active_case"):
        st.markdown(
            f'<section class="intro-card"><div class="eyebrow">Case file / {escape(example["title"])}</div>'
            "<h2>Start with what you measured.</h2>"
            "<p>An unknown sample. A measured spectrum. Several possible structures. "
            "Your task is to follow the evidence and choose the next step.</p>"
            '<div class="brief"><div><strong>01 / Observe</strong>Inspect a real archived MS/MS spectrum.</div>'
            "<div><strong>02 / Investigate</strong>Find structures that fit the measured evidence.</div>"
            "<div><strong>03 / Decide</strong>Collect more evidence or record a conclusion.</div></div></section>",
            unsafe_allow_html=True,
        )
        st.button(
            "Load unknown spectrum",
            key="start_case",
            type="primary",
            on_click=start,
            args=(example["case_id"],),
            width="stretch",
        )
        st.caption("You can reveal at most one extra archived spectrum in each example.")
    else:
        case_id = st.session_state.active_case
        if st.session_state.get("analyzed_case") != case_id:
            case = pilot.case_summary(case_id)
            observed = pilot.observations(case_id)[0]
            st.subheader("1 · Start with the unknown spectrum")
            st.markdown(
                f'<div class="spectrum-strip"><div><label>Measured precursor m/z</label><strong>{case["precursor_mz"]:.5f}</strong></div>'
                "<div><label>Acquired spectrum</label><strong>20 eV · CID</strong></div>"
                f'<span class="tag">{escape(case["adduct"])} · 1 measurement collected</span></div>',
                unsafe_allow_html=True,
            )
            figure = spectrum_plot(observed, set())
            figure.add_vline(
                x=case["precursor_mz"],
                line_dash="dot",
                line_color="#a55e20",
                annotation_text="Intact precursor ion",
                annotation_position="top left",
            )
            st.plotly_chart(
                figure, width="stretch", key="unknown_spectrum", config={"displayModeBar": False}
            )
            st.write(
                "Each peak represents an ion detected from this sample. Which library structures could explain this fingerprint?"
            )
            st.button(
                "Search the reference library",
                key="analyze_case",
                type="primary",
                on_click=analyze,
                args=(case_id,),
            )
            st.caption(
                f"Search {len(pilot.references)} known structures by precursor mass (10 ppm), then compare the matching candidates’ fragment patterns."
            )
        else:
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
                for index, candidate in enumerate(
                    sorted(item["candidate_id"] for item in candidates)
                )
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
            st.subheader("2 · Discover the mass-compatible structures")
            structure_gallery(
                stable_candidates,
                names,
                candidates[0]["candidate_id"]
                if st.session_state.get("compared_case") == case_id
                else None,
            )
            if all(
                STRUCTURES[item["candidate_id"]].get("family") == "Trihydroxychalcone"
                for item in candidates
            ):
                st.caption(
                    "Compare the red oxygen / OH groups: these structures differ in where those groups sit on the two rings. That structural difference is real; its fragmentation mechanism is not assigned here."
                )
            st.divider()
            if st.session_state.get("compared_case") != case_id:
                st.subheader("Same mass. Different structures. What separates them?")
                st.write(
                    "Accurate mass gives a shortlist, not an identification. "
                    "Next, compare the sample’s measured fragments with the fingerprints associated with these structures."
                )
                st.button(
                    "Compare fragment fingerprints",
                    key="compare_case",
                    type="primary",
                    on_click=compare,
                    args=(case_id,),
                )
                st.caption(
                    "This analysis uses only the spectrum already collected. It does not reveal an extra measurement."
                )
            else:
                initial_decision = st.session_state.baseline["decision_if_stopped"]
                enough = preview in {"REFERENCE_SUPPORTED", "RANKED_ONLY_MATCH", "MASS_ONLY_MATCH"}
                measured_extra = len(observations) > 1
                answer = ("Reference-supported library match" if preview == "REFERENCE_SUPPORTED" else "Provisional library match") if enough else "Not enough evidence to identify"
                if measured_extra and not enough:
                    answer = "Still unresolved — no identification"

                current, next_step = st.columns([1.1, 1], gap="large")
                with current:
                    st.subheader("3 · What does the evidence support?")
                    if enough:
                        verdict_card(answer, True)
                        st.write(f"**{lead}** meets the current library-ranking rule, not necessarily MS/MS confirmation.")
                        st.caption("Evidence tier: " + preview + ". Relative support is not an identity probability.")
                    else:
                        verdict_card(answer, False)
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
                    st.subheader("4 · What should we measure next?")
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
                            st.write(
                                "The current evidence meets the rule. No extra scan is recommended."
                            )
                            st.caption(
                                "Following this recommendation avoids one optional measurement."
                            )
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

                if evidence["user_modified_evidence"]:
                    st.warning("Scientist-edited sensitivity analysis. Original unedited verdict: " + evidence["original_decision_if_stopped"] + ". Current edited verdict: " + preview + ".")
                if measured_extra:
                    st.subheader("What changed after the extra measurement?")
                    result_comparison(
                        baseline_candidates[0],
                        candidates[0],
                        names,
                        initial_decision,
                        enough,
                        list(observations)[-1],
                    )
                    if enough and initial_decision not in {"REFERENCE_SUPPORTED", "RANKED_ONLY_MATCH", "MASS_ONLY_MATCH"}:
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
                    st.subheader("What was saved?")
                    st.markdown(
                        '<div class="saved-card"><strong>1</strong><p><b>optional measurement avoided</b><br>The conclusion uses the initial spectrum alone.</p></div>',
                        unsafe_allow_html=True,
                    )
                if st.session_state.get("change"):
                    st.caption(st.session_state.change[2])
                st.caption(
                    "An accepted identification can still be wrong. This example assumes the true molecule is in the library."
                )

                if stopped:
                    st.subheader("5 · Record the conclusion")
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

                with st.expander("Counterfactual evidence challenge", expanded=False):
                    audit = pilot.session(case_id).counterfactual_audit("CID20")
                    st.write(f"Removing one acquired peak at a time changes the leading candidate in {audit['leader_flip_count']} of {audit['peaks_tested']} tested cases.")
                    st.caption(audit["scientific_limit"])
                    if audit["peak_challenges"]:
                        st.dataframe(pd.DataFrame(audit["peak_challenges"][:8]), hide_index=True, width="stretch")
                    commit = evidence.get("premeasurement_commit")
                    if commit:
                        st.write("**Premeasurement SHA256 commitment:** `" + commit["sha256"] + "`")
                        st.caption("Diagnostic m/z values were predicted from reference fingerprints before the archived measurement was accessed.")
                        for prediction in commit["predictions"]:
                            st.write(f"Candidate {names.get(prediction['candidate_id'], prediction['candidate_id'])}: diagnostic m/z {prediction['diagnostic_mz']}")
                    verification = evidence.get("experimental_challenge_result")
                    if verification:
                        st.write("**Measured challenge results**")
                        st.dataframe(pd.DataFrame(verification["candidate_outcomes"]), hide_index=True)
                        st.caption(verification["scientific_limit"])
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
                others = [
                    item["candidate_id"] for item in candidates if item["candidate_id"] != first_id
                ]
                if preferred_other not in others:
                    preferred_other = others[0]
                action = st.selectbox(
                    "Compare a measurement already collected",
                    list(observations),
                    key="compare_action",
                )
                other_id = st.selectbox(
                    "Compare the leading match with",
                    others,
                    index=others.index(preferred_other),
                    format_func=lambda cid: candidate_title(by_id[cid], names),
                    key=f"compare_other_{case_id}_{first_id}_{len(observations)}",
                )
                comparison = compare_observed_candidates(
                    pilot, case_id, action, [first_id, other_id]
                )
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
                    fingerprint_comparison(comparison, names),
                    width="stretch",
                    key="fingerprint_compare",
                )
                peak_rows = []
                for mass, intensity in comparison["strongest_fragments"]:
                    row = {"Observed fragment m/z": f"{mass:.4f}"}
                    for candidate in comparison["candidates"]:
                        match = next(
                            (pair for pair in candidate["matches"] if pair["observed_mz"] == mass),
                            None,
                        )
                        row[names[candidate["candidate_id"]]] = (
                            f"Matches {match['template_mz']:.4f}" if match else "No matching peak"
                        )
                    peak_rows.append(row)
                if peak_rows:
                    st.dataframe(pd.DataFrame(peak_rows), hide_index=True, width="stretch")
                if any(
                    row["reference_source"] == "reference_cid60" for row in comparison["candidates"]
                ):
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
                    st.caption(
                        "Optional detail: spectra, candidate scores and the planner's calculation."
                    )
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
                        baseline = {
                            item["candidate_id"]: item["weight"] for item in baseline_candidates
                        }
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "Candidate": names[item["candidate_id"]],
                                        "Formula": item["formula"],
                                        "Support": item["weight"],
                                        "Change": item["weight"]
                                        - baseline.get(item["candidate_id"], 0),
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
                        st.write(
                            f"{names[item['candidate_id']]} · {item['name']} · {item['candidate_id']}"
                        )
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
                        available = [
                            action for action in ("CID40", "EAD16") if action not in observations
                        ]
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
                        "Observation to edit",
                        list(observations),
                        key="edit_action",
                        disabled=stopped,
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

with library_tab:
    st.subheader("What is in the reference library?")
    st.write(
        f"This demonstration bundles **{len(pilot.references)} known candidate structures**. "
        "The sample spectrum is compared with reference fingerprints associated with these structures. "
        "Only a mass-compatible subset is considered for each investigation."
    )
    library_ids = pilot.references.candidate_ids
    entry_id = st.selectbox(
        "Inspect a library structure",
        library_ids,
        format_func=lambda cid: pilot.references.candidate(cid).name,
        key="library_entry",
    )
    entry = pilot.references.candidate(entry_id)
    image_column, metadata_column = st.columns([1, 2])
    with image_column:
        st.image(str(ASSETS / STRUCTURES[entry_id]["file"]), width="stretch")
    with metadata_column:
        st.write(f"**{entry.name}**")
        st.write(f"Formula: {entry.formula} · precursor m/z {entry.precursor_mz:.5f}")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Compared observation": action,
                        "Reference source": "Measured CID60 library spectrum used as an energy-mismatched proxy"
                        if template.source == "reference_cid60"
                        else "Predicted fingerprint from training structure-neighbours",
                    }
                    for action, template in pilot.references.templates_for(entry_id).items()
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    st.caption(
        "This is the small bundled demonstration library, not a comprehensive chemical database. Library entries are possible matches; listing a structure does not establish that it is present in the sample."
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
        "These are outcome-selected development illustrations, not an independent test or an accuracy estimate. Sample labels do not disclose the selected outcomes; each investigation displays what its current evidence supports."
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

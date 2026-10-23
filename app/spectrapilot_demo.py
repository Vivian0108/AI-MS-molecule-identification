"""SpectraPilot measurement-triage workspace.

One screen: the acquired spectra, the mass-compatible candidates, and the next
measurement decision. Supporting science lives behind the Method, Validation,
Reference library and Peak tools dialogs.
"""

from __future__ import annotations

import base64
import json
from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from spectrapilot.demo import DemoService
from spectrapilot.presentation import compare_observed_candidates
from spectrapilot.service import ServiceError

APP = Path(__file__).resolve().parent
ASSETS = APP / "assets"
STRUCTURES = json.loads((ASSETS / "structures/manifest.json").read_text())["candidates"]

st.set_page_config(
    page_title="SpectraPilot · Measurement triage",
    page_icon=str(ASSETS / "mark.svg"),
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    "<style>" + (ASSETS / "demo.css").read_text() + "</style>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Service and session state
# ---------------------------------------------------------------------------
def service() -> DemoService:
    if "pilot" not in st.session_state:
        st.session_state.pilot = DemoService()
    return st.session_state.pilot


def reset_current(pilot: DemoService, case_id: str) -> None:
    pilot.reset_case(case_id)
    pilot.start_case(case_id)
    st.session_state.pop(f"baseline_{case_id}", None)
    st.session_state.pop(f"identity_{case_id}", None)


def acquire(pilot: DemoService, case_id: str, action: str) -> None:
    pilot.measure(case_id, action)
    st.session_state.pop(f"identity_{case_id}", None)


def stop_case(pilot: DemoService, case_id: str) -> None:
    pilot.stop(case_id)


def reveal(pilot: DemoService, case_id: str) -> None:
    st.session_state[f"identity_{case_id}"] = pilot.reveal_identity(case_id)


def exclude_peak(pilot: DemoService, case_id: str, action: str, index: int, reason: str) -> None:
    key = f"peak_error_{case_id}"
    if not reason.strip():
        st.session_state[key] = "Add a reason before excluding a peak."
        return
    try:
        pilot.exclude_observed_peak(case_id, action, index, reason)
    except ValueError as exc:
        st.session_state[key] = str(exc)
        return
    st.session_state.pop(key, None)


def undo_peak(pilot: DemoService, case_id: str, intervention_id: str) -> None:
    try:
        pilot.undo_intervention(
            case_id, intervention_id, "Scientist restored the original evidence."
        )
    except ValueError as exc:
        st.session_state[f"peak_error_{case_id}"] = str(exc)
        return
    st.session_state.pop(f"peak_error_{case_id}", None)


def session_status(pilot: DemoService, case_id: str) -> str:
    try:
        evidence = pilot.get_evidence(case_id)
    except ServiceError:
        return "Not started"
    if evidence["stopped"]:
        return "Report ready"
    if len(evidence["observed_actions"]) > 1:
        return "Extra scan acquired"
    return "Evidence ready"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
ACTION_LABELS = {
    "CID20": "CID 20 eV",
    "CID40": "CID 40 eV",
    "EAD16": "EAD 16 eV",
}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def display_name(item: dict) -> str:
    candidate_id = item["candidate_id"]
    name = item.get("name") or ""
    if name and name != candidate_id:
        return name
    info = STRUCTURES.get(candidate_id, {})
    family = info.get("family")
    counts = info.get("ring_oh_counts")
    if family and counts:
        return f"{family} · OH {'+'.join(str(count) for count in counts)}"
    return f"Unnamed structure {candidate_id[:6]}"


def short_name(item: dict, limit: int = 34) -> str:
    name = display_name(item)
    return name if len(name) <= limit else name[: limit - 1].rstrip() + "…"


def short_text(text: str, limit: int = 34) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def scan_label(action: str) -> str:
    return action_label(action)


def structure_image(candidate_id: str, *, size: str = "row") -> str:
    info = STRUCTURES.get(candidate_id)
    if info is None:
        return ""
    svg = (ASSETS / "structures" / info["file"]).read_bytes()
    encoded = base64.b64encode(svg).decode("ascii")
    return (
        f'<img class="{size}" src="data:image/svg+xml;base64,{encoded}" '
        f'alt="Molecular structure of library entry {escape(candidate_id, quote=True)}" />'
    )


def oh_tag(candidate_id: str) -> str:
    info = STRUCTURES.get(candidate_id, {})
    counts = info.get("ring_oh_counts")
    if not counts:
        return ""
    return f'<span class="oh">OH {"+".join(str(c) for c in counts)}</span>'


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def stacked_spectra(
    series: list[dict],
    *,
    height: int,
    precursor: float | None = None,
    guide_masses: list[float] | None = None,
) -> go.Figure:
    rows = len(series)
    figure = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.07)
    masses = [value for row in series for value in row["mz"]]
    low, high = min(masses), max(masses)
    span = max(high - low, 1.0)
    for index, row in enumerate(series, 1):
        x, y = [], []
        for mass, intensity in zip(row["mz"], row["intensity"]):
            x.extend([mass, mass, None])
            y.extend([0.0, intensity, None])
        figure.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                line=dict(color=row.get("color", "#0b6b63"), width=1.45),
                hovertemplate=(
                    f"{escape(row['label'])}<br>m/z %{{x:.4f}}"
                    "<br>relative intensity %{y:.2f}<extra></extra>"
                ),
            ),
            row=index,
            col=1,
        )
        xref = "x domain" if index == 1 else f"x{index} domain"
        yref = "y domain" if index == 1 else f"y{index} domain"
        figure.add_annotation(
            text=escape(row["label"]),
            xref=xref,
            yref=yref,
            x=0.008,
            y=0.96,
            xanchor="left",
            yanchor="top",
            showarrow=False,
            font=dict(size=9.5, color="#687b86"),
        )
        if precursor is not None:
            figure.add_vline(
                x=precursor,
                line=dict(color="#c3cdd2", width=1, dash="dot"),
                row=index,
                col=1,
            )
        if guide_masses:
            for mass in guide_masses:
                figure.add_vline(
                    x=mass,
                    line=dict(color="#cbd5d9", width=0.7, dash="dot"),
                    row=index,
                    col=1,
                )
    figure.update_layout(
        height=height,
        margin=dict(l=6, r=8, t=14, b=26),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        showlegend=False,
        font=dict(
            family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
            size=10,
            color="#5d707b",
        ),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor="#d8e0e4", font_size=10),
    )
    figure.update_xaxes(
        range=[low - span * 0.06, high + span * 0.09],
        showgrid=False,
        zeroline=False,
        linecolor="#d8e0e4",
        tickfont=dict(size=9, color="#71838d"),
        ticks="outside",
        ticklen=3,
        tickcolor="#d8e0e4",
    )
    figure.update_yaxes(
        range=[0, 1.06],
        tickvals=[0, 0.5, 1],
        tickfont=dict(size=8.5, color="#8a9aa3"),
        gridcolor="#eef1f3",
        zeroline=False,
        showline=False,
    )
    figure.update_xaxes(
        title_text="m/z",
        title_font=dict(size=10, color="#687b86"),
        row=rows,
        col=1,
    )
    return figure


def measured_figure(observations: list[dict], precursor: float) -> go.Figure:
    series = [
        {
            "label": f"{action_label(row['action'])} · {row['n_peaks']} peaks",
            "mz": row["mz"],
            "intensity": row["intensity"],
            "color": "#0b6b63",
        }
        for row in observations
    ]
    return stacked_spectra(
        series,
        height=234 if len(series) == 1 else 340,
        precursor=precursor,
    )


def evidence_figure(comparison: dict, selected_name: str, other_name: str) -> go.Figure:
    action = comparison["action"]
    first, second = comparison["candidates"]
    series = [
        {
            "label": f"Sample · {action}",
            "mz": comparison["observed_mz"],
            "intensity": comparison["observed_intensity"],
            "color": "#123f43",
        },
        {
            "label": f"Selected · {short_text(selected_name, 30)}",
            "mz": first["reference_mz"],
            "intensity": first["reference_intensity"],
            "color": "#0b6b63",
        },
        {
            "label": f"Comparison · {short_text(other_name, 30)}",
            "mz": second["reference_mz"],
            "intensity": second["reference_intensity"],
            "color": "#b5792a",
        },
    ]
    return stacked_spectra(
        series,
        height=344,
        guide_masses=[mass for mass, _ in comparison["strongest_fragments"]],
    )


# ---------------------------------------------------------------------------
# Candidate table
# ---------------------------------------------------------------------------
def candidate_table(candidates: list[dict], observed: list[str]) -> str:
    if not candidates:
        return ""
    leader = candidates[0]["candidate_id"]
    top_support = max(item["weight"] for item in candidates) or 1.0
    rows = []
    for rank, item in enumerate(candidates, 1):
        cid = item["candidate_id"]
        name = display_name(item)
        support = item["weight"]
        width = max(2.0, 100 * support / top_support)
        tag = "" if "· OH" in name else oh_tag(cid)
        fit_parts = []
        for action in observed:
            value = item["similarity_by_action"].get(action)
            label = action.replace("CID", "CID ").replace("EAD", "EAD ")
            fit_parts.append(
                f"<span>{escape(label)} <b>{value:.2f}</b></span>"
                if value is not None
                else f'<span class="missing">{escape(label)} —</span>'
            )
        lead = cid == leader
        lead_tag = '<span class="lead-tag">Lead</span>' if lead else ""
        rows.append(
            f'<div class="cand-row {"lead" if lead else ""}">'
            f'<div class="cand-rank">{rank}</div>'
            f'<div class="cand-img">{structure_image(cid)}</div>'
            f'<div class="cand-body">'
            f'<div class="cand-name" title="{escape(name, quote=True)}">{escape(name)}'
            f"{lead_tag}</div>"
            f'<div class="cand-sub"><span>{escape(item["formula"])}</span>'
            f"<span>{item['exact_mass']:.4f} Da</span>{tag}</div>"
            f"</div>"
            f'<div class="support"><b>{support:.2f}</b>'
            f'<span class="bar"><i style="width:{width:.1f}%"></i></span></div>'
            f'<div class="fit">{"".join(fit_parts)}</div>'
            f"</div>"
        )
    return (
        '<div class="cand-table">'
        '<div class="cand-head"><span></span><span>Structure</span><span>Candidate</span>'
        '<span>Support</span><span class="fit-head">Fit</span></div>' + "".join(rows) + "</div>"
    )


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------
@st.dialog("Method & scope", width="large")
def method_dialog(pilot: DemoService) -> None:
    support_rule = float(pilot.policy_cfg.get_path("confidence.identified_min_support", 0.72))
    margin_rule = float(pilot.policy_cfg.get_path("confidence.identified_min_margin", 0.22))
    fit_rule = float(pilot.policy_cfg.get_path("confidence.identified_min_fit", 0.30))
    peaks_rule = int(pilot.policy_cfg.get_path("confidence.identified_min_matched_peaks", 2))
    rule = (
        f"Support ≥ {support_rule:.2f}, margin ≥ {margin_rule:.2f}, "
        f"best fit ≥ {fit_rule:.2f} and at least {peaks_rule} matched peaks."
    )
    st.html(
        '<div class="dialog-kicker">How the recommendation is produced</div>'
        '<div class="pipeline">'
        "<div><span>01</span><b>Shortlist</b><small>Precursor mass within 10 ppm</small></div>"
        "<div><span>02</span><b>Score</b><small>Fragment fit, matched peaks, neutral losses</small></div>"
        "<div><span>03</span><b>Decide</b><small>Support, margin and fit thresholds</small></div>"
        "<div><span>04</span><b>Act</b><small>Acquire the most separating scan, or stop</small></div>"
        "</div>"
        '<div class="note">'
        "<p><b>Closed-world.</b> The true structure is assumed to be in the bundled candidate "
        "library. This is not de novo structure elucidation.</p>"
        "<p><b>Evidence.</b> The CID20 spectrum is the measured query. The optional CID40 "
        "measurement is archived data revealed only when requested. References are predicted "
        "from training structure-neighbours, or permitted CID60 library spectra used as CID40 "
        "proxies. That energy mismatch is disclosed.</p>"
        f"<p><b>Decision rule.</b> {rule} Support is a relative ranking score, not a calibrated "
        "identity probability.</p>"
        "<p><b>Demo.</b> Three curated development illustrations, not independent validation. "
        "No live instrument is connected. Measurements are archived MultiMS2 data "
        "(CC0-1.0).</p>"
        "</div>"
    )


@st.dialog("Validation", width="large")
def validation_dialog(pilot: DemoService) -> None:
    library = pilot.results["library_assisted"]
    single = library["cid20_only"]
    planned = library["separation"]
    always = library["always_cid40"]
    saved = 1 - planned["optional_scans"] / always["optional_scans"]
    st.html(
        '<div class="dialog-kicker">Exploratory grouped cross-validation · '
        f"{pilot.results['n']} ambiguous molecules</div>"
        '<div class="val-grid">'
        f'<div class="accent"><b>{single["accepted_correct"]} → {planned["accepted_correct"]}</b>'
        "<span>Accepted-correct</span><small>Single scan → one planned extra scan</small></div>"
        f"<div><b>{single['coverage']:.0%} → {planned['coverage']:.0%}</b>"
        "<span>Coverage</span><small>Molecules with an accepted answer</small></div>"
        f"<div><b>{planned['optional_scans']} / {always['optional_scans']}</b>"
        f"<span>Optional scans</span><small>Planner vs always-CID40 · {saved:.1%} fewer</small></div>"
        f"<div><b>{planned['accepted_correct']} / {always['accepted_correct']}</b>"
        "<span>Accepted-correct</span>"
        f"<small>{planned['accepted_error']} accepted errors in each arm</small></div>"
        "</div>"
        '<div class="note">'
        "<p>The planner recovers most of the value of always acquiring a second spectrum while "
        f"skipping {always['optional_scans'] - planned['optional_scans']} of "
        f"{always['optional_scans']} optional scans. This is a measured tradeoff, not proof of "
        "equivalent accuracy.</p>"
        "<p><b>Limits.</b> Training cross-validation, not independent test validation. The three "
        "demo samples are outcome-selected development illustrations. Permitted CID60 references "
        "are used as CID40 proxies.</p>"
        "</div>"
    )
    st.download_button(
        "Download scientific report",
        (pilot.bundle / "public/scientific_report.md").read_text(),
        file_name="spectrapilot-scientific-report.md",
        mime="text/markdown",
        key="download_science",
    )


@st.dialog("Reference library", width="large")
def library_dialog(pilot: DemoService, case_id: str | None = None) -> None:
    candidate_ids = pilot.references.candidate_ids
    default = 0
    if case_id is not None:
        try:
            leader = pilot.get_evidence(case_id)["ranking"]["candidates"][0]["candidate_id"]
            default = candidate_ids.index(leader)
        except (ServiceError, ValueError, IndexError):
            default = 0

    def candidate_label(cid: str) -> str:
        return display_name({"candidate_id": cid, "name": pilot.references.candidate(cid).name})

    entry_id = st.selectbox(
        "Structure",
        candidate_ids,
        index=default,
        format_func=candidate_label,
        key=f"library_entry_{case_id or 'all'}",
    )
    entry = pilot.references.candidate(entry_id)
    left, right = st.columns([0.8, 1.6], gap="large")
    with left:
        st.html(f'<div class="lib-struct">{structure_image(entry_id, size="lib")}</div>')
    with right:
        st.html(
            f'<div class="lib-name">{escape(candidate_label(entry_id))}</div>'
            f'<div class="lib-meta">{escape(entry.formula)} · {entry.exact_mass:.4f} Da · '
            f"precursor {entry.precursor_mz:.5f} m/z</div>"
            f'<div class="lib-key">Library key · {escape(entry_id)}</div>'
        )
        rows = []
        for action, template in pilot.references.templates_for(entry_id).items():
            if template.source == "reference_cid60":
                source = "Measured CID60 library spectrum · CID40 proxy"
            else:
                source = (
                    f"Predicted · donor agreement ({template.n_donors} donors)"
                    if template.n_donors
                    else "Predicted · donor agreement"
                )
            rows.append(
                f'<div class="source-row"><span class="source-key">{escape(action)}</span>'
                f'<span class="source-val">{escape(source)}</span></div>'
            )
        st.html("".join(rows))
    st.caption(
        f"{len(candidate_ids)} structures are bundled for this demo. A sample considers only the "
        "entries within 10 ppm of its precursor. Listing a structure does not establish that it is "
        "present in the sample. Entries without a supplied common name are labelled by family and "
        "ring-OH pattern."
    )


@st.dialog("Fragment evidence", width="large")
def evidence_dialog(pilot: DemoService, case_id: str) -> None:
    evidence = pilot.get_evidence(case_id)
    candidates = evidence["ranking"]["candidates"]
    by_id = {item["candidate_id"]: item for item in candidates}
    candidate_ids = list(by_id)
    leader = candidates[0]["candidate_id"]
    observed = evidence["observed_actions"]
    action = st.segmented_control(
        "Acquired scan",
        observed,
        default=observed[-1],
        format_func=scan_label,
        key=f"evidence_scan_{case_id}",
    )
    if action is None:
        action = observed[-1]
    left, right = st.columns(2)
    with left:
        selected = st.selectbox(
            "Candidate",
            candidate_ids,
            index=candidate_ids.index(leader),
            format_func=lambda cid: display_name(by_id[cid]),
            key=f"evidence_focus_{case_id}_{action}",
        )
    others = [cid for cid in candidate_ids if cid != selected]
    if not others:
        st.info("This sample has only one candidate.")
        return
    baseline = st.session_state.get(f"baseline_{case_id}")
    default_other = None
    if baseline:
        previous = baseline[0]["candidate_id"]
        if previous != selected and previous in others:
            default_other = previous
    with right:
        other = st.selectbox(
            "Compare with",
            others,
            index=others.index(default_other) if default_other else 0,
            format_func=lambda cid: display_name(by_id[cid]),
            key=f"evidence_other_{case_id}_{action}_{selected}",
        )
    if selected == other:
        return
    comparison = compare_observed_candidates(pilot, case_id, action, [selected, other])
    first, second = comparison["candidates"]
    label = "Leading candidate" if selected == leader else "Selected candidate"
    st.html(
        '<div class="dialog-stats">'
        f'<div class="dialog-stat"><span>{label} · {escape(action)}</span>'
        f"<b>{first['cosine']:.2f}</b><small>{escape(short_name(by_id[selected], 44))}</small></div>"
        f'<div class="dialog-stat alt"><span>Comparison · {escape(action)}</span>'
        f"<b>{second['cosine']:.2f}</b><small>{escape(short_name(by_id[other], 44))}</small></div>"
        "</div>"
    )
    st.plotly_chart(
        evidence_figure(
            comparison,
            display_name(by_id[selected]),
            display_name(by_id[other]),
        ),
        width="stretch",
        config={"displayModeBar": False},
        key=f"fragment_figure_{case_id}_{action}_{selected}_{other}",
    )
    sources = []
    for item in (first, second):
        source = (
            "CID60 library proxy"
            if item["reference_source"] == "reference_cid60"
            else "predicted reference"
        )
        sources.append(f"{display_name(by_id[item['candidate_id']])}: {source}")
    st.caption(" · ".join(sources))
    if any(item["reference_source"] == "reference_cid60" for item in (first, second)):
        st.caption(
            "CID60 library spectra are used as proxies for CID40. The collision energy differs; "
            "this is not a measured CID40 reference for that candidate."
        )
    else:
        st.caption(
            "Predicted references come from training structure-neighbours, not experimental "
            "spectra of each candidate at this energy."
        )
    rows = []
    for mass, intensity in comparison["strongest_fragments"]:
        match = next(
            (pair for pair in first["matches"] if pair["observed_mz"] == mass),
            None,
        )
        rows.append(
            {
                "Observed m/z": f"{mass:.4f}",
                "Reference m/z": f"{match['template_mz']:.4f}" if match else "—",
                "Δ mDa": f"{1000 * match['delta_da']:+.1f}" if match else "—",
                "Observed rel.": f"{intensity:.2f}",
                "Reference rel.": f"{match['template_intensity']:.2f}" if match else "—",
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Three strongest observed fragments, excluding the intact ion. Match tolerance "
        f"±{comparison['tolerance_da']:.2f} Da. Cosine compares the whole peak pattern; it is not "
        "an identity probability, and a matching peak is not a bond assignment."
    )


@st.dialog("Peak tools", width="large")
def peak_tools_dialog(pilot: DemoService, case_id: str) -> None:
    evidence = pilot.get_evidence(case_id)
    stopped = evidence["stopped"]
    observations = {item["action"]: item for item in pilot.observations(case_id)}
    st.caption(
        "Exclude an observed peak to test sensitivity. The original spectrum is preserved and "
        "every edit is reversible. This is a sensitivity check, not proof of contamination."
    )
    action = st.selectbox(
        "Acquired scan",
        list(observations),
        format_func=scan_label,
        key=f"peak_scan_{case_id}",
        disabled=stopped,
    )
    current = observations[action]
    excluded = {
        row["peak_index"] for row in evidence["active_peak_exclusions"] if row["action"] == action
    }
    index = st.selectbox(
        "Peak",
        range(current["n_peaks"]),
        format_func=lambda value: (
            f"#{value} · m/z {current['mz'][value]:.5f} · "
            f"relative intensity {current['intensity'][value]:.3f}"
        ),
        key=f"peak_index_{case_id}_{action}",
        disabled=stopped,
    )
    reason = st.text_input(
        "Reason",
        value="Sensitivity check: investigate a possible contaminant.",
        max_chars=500,
        key=f"edit_reason_{case_id}",
        disabled=stopped,
    )
    st.button(
        "Exclude peak & recompute",
        key="exclude_peak",
        disabled=stopped or index in excluded,
        on_click=exclude_peak,
        args=(pilot, case_id, action, index, reason),
    )
    if st.session_state.get(f"peak_error_{case_id}"):
        st.error(st.session_state.pop(f"peak_error_{case_id}"))
    for entry in evidence["active_peak_exclusions"]:
        st.button(
            f"Undo · {entry['action']} peak #{entry['peak_index']}",
            key=f"undo_{entry['intervention_id']}",
            type="tertiary",
            disabled=stopped,
            on_click=undo_peak,
            args=(pilot, case_id, entry["intervention_id"]),
        )
    with st.expander("Audit trail"):
        st.json(
            {
                "observed_actions": evidence["observed_actions"],
                "remaining_budget": evidence["remaining_budget"],
                "active_exclusions": evidence["active_peak_exclusions"],
                "intervention_history": evidence["intervention_history"],
                "original_observation_hashes": evidence["observations"],
            }
        )
    if stopped:
        st.caption("The report is frozen after stopping. Reset the sample to run another analysis.")


@st.dialog("Report preview", width="large")
def report_dialog(pilot: DemoService, case_id: str) -> None:
    report = pilot.report(case_id)
    st.caption(
        "Generated from the recorded spectra, interventions and provenance. Markdown and JSON "
        "versions are available in the assessment panel."
    )
    st.markdown(report["report_markdown"])


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
pilot = service()
examples = pilot.discovery_manifest()["cases"]

with st.sidebar:
    st.html(
        '<div class="brand"><div class="brand-mark">SP</div>'
        '<div><div class="brand-name">SpectraPilot</div>'
        '<div class="brand-sub">Measurement triage</div></div></div>'
    )
    st.html('<div class="nav-label">Samples</div>')
    default_index = next(
        (
            index
            for index, example in enumerate(examples)
            if example["case_id"] == st.session_state.get("active_case")
        ),
        0,
    )
    pending = st.session_state.get("case_selector", default_index)
    if not isinstance(pending, int) or not 0 <= pending < len(examples):
        pending = default_index
    pilot.start_case(examples[pending]["case_id"])
    selected_index = st.radio(
        "Samples",
        range(len(examples)),
        index=default_index,
        format_func=lambda index: f"Sample {index + 1}",
        captions=[session_status(pilot, example["case_id"]) for example in examples],
        label_visibility="collapsed",
        key="case_selector",
    )
    if selected_index is None:
        selected_index = 0
    case_id = examples[selected_index]["case_id"]
    st.session_state.active_case = case_id
    pilot.start_case(case_id)
    st.button(
        "Reset sample",
        key="reset_case",
        width="stretch",
        on_click=reset_current,
        args=(pilot, case_id),
    )
    st.html(
        '<div class="side-foot"><b>3 curated samples</b><br>Archived MS/MS · no live instrument'
        "<br>MultiMS2 · CC0-1.0</div>"
    )

case = pilot.case_summary(case_id)
evidence = pilot.get_evidence(case_id)
ranking = evidence["ranking"]["candidates"]
top = ranking[0]
second = ranking[1] if len(ranking) > 1 else top
support = float(top["weight"])
margin = support - float(second["weight"])
fits = top["similarity_by_action"]
best_fit = max(fits.values()) if fits else 0.0
decision = evidence["decision_if_stopped"]
stopped = evidence["stopped"]
observed = evidence["observed_actions"]
observations = pilot.observations(case_id)
report = pilot.report(case_id) if stopped else None

baseline_key = f"baseline_{case_id}"
if baseline_key not in st.session_state and len(observed) == 1:
    st.session_state[baseline_key] = ranking

support_rule = float(pilot.policy_cfg.get_path("confidence.identified_min_support", 0.72))
margin_rule = float(pilot.policy_cfg.get_path("confidence.identified_min_margin", 0.22))
fit_rule = float(pilot.policy_cfg.get_path("confidence.identified_min_fit", 0.30))

# Header -------------------------------------------------------------------
head_left, head_right = st.columns([7.2, 2.8], vertical_alignment="top")
with head_left:
    st.html(
        f'<div class="crumb">Samples <span>/</span> Sample {selected_index + 1}</div>'
        f'<div class="page-title">Sample {selected_index + 1}</div>'
        '<div class="meta-line">'
        '<span>Unknown sample</span><span class="sep">·</span>'
        f"<span>precursor m/z <b>{case['precursor_mz']:.5f}</b></span>"
        f'<span class="sep">·</span><span>{escape(case["adduct"])}</span>'
        f'<span class="sep">·</span><span>{escape(case["instrument_model"])}</span>'
        "</div>"
        f'<div class="purpose">Which of {case["n_candidates"]} mass-compatible structures do '
        "the measured fragments support?</div>"
    )
with head_right:
    with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
        with st.popover("Demo data", type="tertiary"):
            st.markdown("**Curated development demo**")
            st.caption(
                "Three development samples from MultiMS2. Archived measurements are revealed on "
                "request; no live instrument is connected."
            )
            st.caption(
                "Closed-world library identification, not an accuracy benchmark or de novo "
                "structure elucidation."
            )
        if st.button("Method", key="open_method", type="tertiary"):
            method_dialog(pilot)
        if st.button("Validation", key="open_validation", type="tertiary"):
            validation_dialog(pilot)

st.html('<div class="head-rule"></div>')

main_col, rail_col = st.columns([2.18, 0.92], gap="large")

with main_col:
    # Spectra --------------------------------------------------------------
    st.html(
        '<div class="section-head"><span class="section-title">Measured spectra</span>'
        f'<span class="section-meta">{len(observations)} scan'
        f"{'s' if len(observations) != 1 else ''} · archived</span></div>"
    )
    st.plotly_chart(
        measured_figure(observations, case["precursor_mz"]),
        width="stretch",
        config={"displayModeBar": False},
        key=f"measured_{case_id}_{len(observations)}",
    )
    caption_col, tools_col = st.columns([5, 1.2], vertical_alignment="center")
    with caption_col:
        st.caption(
            "Dotted line marks the intact precursor ion. Intensities are normalized per scan."
        )
    with tools_col:
        if st.button("Peak tools", key="open_peaks", type="tertiary", width="stretch"):
            peak_tools_dialog(pilot, case_id)

    # Candidates -----------------------------------------------------------
    formulas = sorted({item["formula"] for item in ranking})
    if len(formulas) == 1:
        lede = (
            f"All {len(ranking)} candidates share <b>{escape(formulas[0])}</b> and fit the "
            "precursor within 10 ppm. Fragment evidence separates them."
        )
    else:
        lede = (
            f"All {len(ranking)} candidates fit the precursor within 10 ppm. Fragment evidence "
            "separates them."
        )
    st.html(
        '<div class="section-head"><span class="section-title">Candidate shortlist</span>'
        f'<span class="section-meta">{len(ranking)} structures · ±10 ppm</span></div>'
        f'<p class="lede">{lede}</p>'
    )

    baseline = st.session_state.get(baseline_key)
    if len(observed) > 1 and baseline:
        previous = baseline[0]
        if previous["candidate_id"] != top["candidate_id"]:
            change = (
                f"{escape(short_name(previous, 38))} ({previous['weight']:.2f}) → "
                f"<b>{escape(short_name(top, 38))}</b> ({support:.2f})"
            )
        else:
            change = (
                f"Leading match unchanged: <b>{escape(short_name(top, 38))}</b> "
                f"({previous['weight']:.2f} → {support:.2f} support)"
            )
        st.html(
            '<div class="change-line"><span class="change-tag">Updated</span>'
            f"<span>{escape(scan_label(observed[-1]))} changed the ranking. {change}</span></div>"
        )

    st.html(candidate_table(ranking, observed))

    with st.container(horizontal=True, vertical_alignment="center", gap="medium", width="content"):
        if st.button("Compare fragment evidence", key="open_evidence", type="secondary"):
            evidence_dialog(pilot, case_id)
        if st.button("Reference library", key="open_library", type="tertiary"):
            library_dialog(pilot, case_id)

with rail_col:
    with st.container(key="rail"):
        status_label = "Identification supported" if decision == "IDENTIFIED" else "Unresolved"
        tone = "good" if decision == "IDENTIFIED" else "warn"
        status_note = (
            "The current evidence meets the identification rule."
            if decision == "IDENTIFIED"
            else "The top candidate does not meet the identification rule."
        )
        if stopped:
            status_note = (
                "Report ready. The evidence supports an identification."
                if decision == "IDENTIFIED"
                else "Report ready. No candidate meets the identification rule."
            )
        st.html(
            '<div class="section-head"><span class="section-title">Assessment</span>'
            f'<span class="section-meta">{"Final" if stopped else "Live"}</span></div>'
            f'<div class="status"><span class="dot {tone}"></span>'
            f'<span class="status-text">{status_label}</span></div>'
            f'<div class="status-note">{status_note}</div>'
            '<div class="topmatch">'
            '<div class="tm-label">Top match</div>'
            f'<div class="tm-name" title="{escape(display_name(top), quote=True)}">'
            f"{escape(display_name(top))}</div>"
            f'<div class="tm-sub">{escape(top["formula"])} · rank 1 of {len(ranking)}</div>'
            "</div>"
            '<div class="metric-grid">'
            f"<div><span>Support</span><b>{support:.2f}</b></div>"
            f"<div><span>Margin</span><b>{margin:.2f}</b></div>"
            f"<div><span>Best fit</span><b>{best_fit:.2f}</b></div>"
            "</div>"
            f'<div class="rule-line">{"<b>Rule met</b>" if decision == "IDENTIFIED" else "<b>Rule not met</b>"}'
            f" · support ≥ {support_rule:.2f} · margin ≥ {margin_rule:.2f}"
            f" · fit ≥ {fit_rule:.2f}</div>"
        )

        st.html('<div class="rail-rule"></div>')

        recommendation = evidence["plan"]["recommended"]
        if not stopped and recommendation["kind"] == "MEASURE":
            action = recommendation["key"]
            st.html(
                '<div class="section-title">Next step</div>'
                f'<div class="next-title">Acquire {escape(action)}</div>'
                '<div class="next-note">The planner estimates this scan will separate the top '
                "candidates.</div>"
            )
            st.button(
                f"Acquire {action}",
                key="measure_recommended",
                type="primary",
                width="stretch",
                on_click=acquire,
                args=(pilot, case_id, action),
            )
            st.caption("Uses the one optional acquisition.")
            st.button(
                "Stop without the extra scan",
                key="stop_case",
                type="tertiary",
                width="stretch",
                on_click=stop_case,
                args=(pilot, case_id),
            )
            st.html(
                '<div class="rail-foot">The planner sees only acquired spectra and candidate '
                "references. It cannot read the hidden measurement.</div>"
            )
        elif not stopped:
            label = "Create report" if decision == "IDENTIFIED" else "Create report · unresolved"
            note = (
                "Current evidence meets the identification rule. No extra scan is needed."
                if decision == "IDENTIFIED"
                else "The scan budget is spent. The evidence remains insufficient for an identification."
            )
            st.html(
                '<div class="section-title">Next step</div>'
                '<div class="next-title">Stop measuring</div>'
                f'<div class="next-note">{note}</div>'
            )
            st.button(
                label,
                key="stop_case",
                type="primary",
                width="stretch",
                on_click=stop_case,
                args=(pilot, case_id),
            )
            st.html(
                '<div class="rail-foot">The report records the evidence, any interventions and '
                "the limitations behind the conclusion.</div>"
            )
        else:
            st.html(
                '<div class="section-title">Report</div>'
                '<div class="next-title">Report ready</div>'
                '<div class="next-note">'
                + (
                    f"The evidence supports <b>{escape(display_name(top))}</b>."
                    if decision == "IDENTIFIED"
                    else "The responsible result is to report the remaining ambiguity."
                )
                + "</div>"
            )
            st.download_button(
                "Download Markdown report",
                report["report_markdown"],
                file_name=f"spectrapilot-{case_id}.md",
                mime="text/markdown",
                key="download_md",
                type="primary",
                width="stretch",
            )
            st.download_button(
                "Download JSON report",
                json.dumps(report, indent=2),
                file_name=f"spectrapilot-{case_id}.json",
                mime="application/json",
                key="download_json",
                width="stretch",
            )
            if st.button("Preview report", key="preview_report", type="tertiary", width="stretch"):
                report_dialog(pilot, case_id)
            st.html('<div class="rail-rule"></div>')
            identity = st.session_state.get(f"identity_{case_id}")
            if identity is None:
                st.button(
                    "Check curated source identity",
                    key="reveal_identity",
                    type="tertiary",
                    width="stretch",
                    on_click=reveal,
                    args=(pilot, case_id),
                )
                st.html(
                    '<div class="rail-foot">Post-stop check only. The identity is not used by the '
                    "analysis or the planner.</div>"
                )
            else:
                outcome = identity["outcome"].replace("-", " ").capitalize()
                name = display_name({"candidate_id": identity["true_id"], "name": identity["name"]})
                st.html(
                    '<div class="source-check">'
                    f"<b>Curated source:</b> {escape(name)}<br>"
                    f"<b>Outcome:</b> {escape(outcome)}</div>"
                    '<div class="rail-foot">Selected development illustration, not evaluation '
                    "evidence.</div>"
                )

st.html(
    '<div class="page-foot">SpectraPilot · closed-world library identification · archived '
    "MultiMS2 measurements · demo mode</div>"
)

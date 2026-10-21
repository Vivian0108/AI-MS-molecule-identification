"""UnknownID — five-screen Streamlit client.

Run with::

    streamlit run app/streamlit_app.py

The app talks to :class:`unknownid.service.UnknownIDService` in-process.  It
never renders a hidden 30/40 eV spectrum before the investigator presses
Measure, and it never renders the true identity (the service has no accessor
for it).
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from unknownid.paths import (  # noqa: E402
    CALIBRATION_MD,
    CURATED,
    EVALUATION_MD,
    EVALUATION_JSON,
    MANIFEST_JSON,
    REPORTS,
)
from unknownid.service import ServiceError, UnknownIDService  # noqa: E402

st.set_page_config(
    page_title="UnknownID",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

ACCENT = "#2f6f62"
MUTED = "#6b7280"
MEASURED = "#1f77b4"
TEMPLATE = "#d97706"
REFERENCE_URL = "https://massbank.eu/MassBank/RecordDisplay?id={accession}"

st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2.2rem; max-width: 1320px; }}
      div[data-testid="stMetric"] {{
          background: #f7f9f8; border: 1px solid #e3e8e6;
          border-radius: 10px; padding: 0.7rem 0.9rem;
      }}
      .uid-banner {{
          background: #eef6f3; border-left: 5px solid {ACCENT};
          padding: 0.8rem 1rem; border-radius: 6px; margin-bottom: 1rem;
      }}
      .uid-warn {{
          background: #fff7e6; border-left: 5px solid #d97706;
          padding: 0.7rem 1rem; border-radius: 6px; margin: 0.6rem 0;
      }}
      .uid-muted {{ color: {MUTED}; font-size: 0.9rem; }}
      .uid-pill {{
          display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
          font-size: 0.82rem; font-weight: 600; letter-spacing: 0.02em;
      }}
      .uid-identified {{ background: #dcfce7; color: #166534; }}
      .uid-ambiguous {{ background: #fef3c7; color: #92400e; }}
      .uid-out {{ background: #fee2e2; color: #991b1b; }}
    </style>
    """,
    unsafe_allow_html=True,
)

BANNER = (
    '<div class="uid-banner"><strong>Virtual instrument uses archived experimental '
    "measurements.</strong> Query spectra are real MassBank records, not generated. "
    "Reference templates at 20/30/40 eV are interpolated from the static 10/50 eV "
    "library; a 30/40 eV action reveals a real archived measurement only after an "
    "explicit request.</div>"
)


@st.cache_resource(show_spinner="Loading curated library and sealed oracle…")
def get_service() -> UnknownIDService:
    return UnknownIDService(default_split="dev")


@st.cache_data(show_spinner=False)
def load_json(path: str) -> dict:
    file = Path(path)
    if not file.exists():
        return {}
    return json.loads(file.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_text(path: str) -> str:
    file = Path(path)
    return file.read_text(encoding="utf-8") if file.exists() else ""


@st.cache_data(show_spinner=False)
def load_frame(path: str, limit: int | None = None) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    return frame.head(limit) if limit else frame


@st.cache_data(show_spinner=False)
def molecule_image(smiles: str, width: int = 180, height: int = 130):
    try:
        from rdkit import Chem
        from rdkit.Chem import Draw

        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            return None
        return Draw.MolToImage(molecule, size=(width, height))
    except Exception:  # pragma: no cover - optional rendering path
        return None


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def decision_pill(decision: str) -> str:
    css = {
        "identified": "uid-identified",
        "ambiguous": "uid-ambiguous",
        "out_of_library": "uid-out",
    }.get(decision, "uid-ambiguous")
    return f'<span class="uid-pill {css}">{esc(decision.replace("_", " ").upper())}</span>'


def stick_plot(
    traces: Sequence[tuple[str, Iterable[float], Iterable[float], str]],
    *,
    title: str,
    mirror: bool = False,
    height: int = 360,
) -> go.Figure:
    figure = go.Figure()
    for index, (label, mz, intensity, color) in enumerate(traces):
        mz = list(mz)
        intensity = list(intensity)
        sign = -1.0 if mirror and index % 2 == 1 else 1.0
        figure.add_trace(
            go.Bar(
                x=mz,
                y=[sign * value for value in intensity],
                name=label,
                marker_color=color,
                marker_line_width=0,
                width=None,
                opacity=0.85,
                hovertemplate="m/z %{x:.3f}<br>%{customdata:.3f}<extra>" + esc(label) + "</extra>",
                customdata=intensity,
            )
        )
    figure.update_layout(
        title=title,
        height=height,
        margin=dict(l=10, r=10, t=48, b=10),
        barmode="overlay",
        bargap=0.0,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0.0),
        xaxis_title="m/z",
        yaxis_title="relative intensity",
        hovermode="closest",
    )
    if mirror:
        figure.update_yaxes(range=[-1.05, 1.05])
    figure.update_xaxes(showgrid=False)
    return figure


def spectrum_frame(spectrum: dict) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "m/z": spectrum.get("mz", []),
            "relative intensity": spectrum.get("intensity", []),
        }
    )


def energy_value(mapping: dict, energy: int, default: float = 0.0) -> float:
    """Read a per-energy mapping whether JSON gave string or int keys."""
    if not mapping:
        return default
    value = mapping.get(energy)
    if value is None:
        value = mapping.get(str(energy))
    return default if value is None else float(value)


def ranking_table(ranking: dict) -> pd.DataFrame:
    rows = []
    for index, evidence in enumerate(ranking.get("evidence", []), start=1):
        cosine = evidence.get("similarity_by_energy", {})
        matched = evidence.get("matched_peaks_by_energy", {})
        rows.append(
            {
                "#": index,
                "candidate": evidence.get("name") or evidence.get("candidate_id"),
                "InChIKey": evidence.get("candidate_id"),
                "formula": evidence.get("formula"),
                "exact mass": round(float(evidence.get("exact_mass", 0.0)), 4),
                "support": round(float(evidence.get("weight", 0.0)), 4),
                "cosine 20 eV": round(energy_value(cosine, 20), 4),
                "cosine 30 eV": (
                    round(energy_value(cosine, 30), 4) if energy_value(cosine, 30, -1) >= 0 else None
                ),
                "cosine 40 eV": (
                    round(energy_value(cosine, 40), 4) if energy_value(cosine, 40, -1) >= 0 else None
                ),
                "matched peaks": sum(int(v) for v in matched.values()),
                "precursor ppm": round(float(evidence.get("precursor_ppm", 0.0)), 3),
            }
        )
    return pd.DataFrame(rows)


def reference_links(evidence: dict) -> str:
    accessions = evidence.get("reference_accessions") or {}
    if not accessions:
        return '<span class="uid-muted">no reference accession recorded</span>'
    links = []
    for energy, accession in sorted(accessions.items(), key=lambda item: int(item[0])):
        url = REFERENCE_URL.format(accession=accession)
        links.append(f'[{int(energy)} eV · {esc(accession)}]({url})')
    return " · ".join(links)


def candidate_structures(evidence_rows: Sequence[dict], limit: int = 4) -> None:
    usable = [row for row in evidence_rows if row.get("smiles")][:limit]
    if not usable:
        return
    columns = st.columns(len(usable))
    for column, row in zip(columns, usable):
        with column:
            image = molecule_image(row["smiles"])
            if image is not None:
                st.image(image, width="stretch")
            st.markdown(
                f"**{esc(row.get('name') or row.get('candidate_id'))}**  \n"
                f"<span class='uid-muted'>{esc(row.get('formula'))} · "
                f"{float(row.get('exact_mass', 0.0)):.4f} Da</span>",
                unsafe_allow_html=True,
            )


def state_case_id() -> str | None:
    return st.session_state.get("active_case")


def start_case(service: UnknownIDService, case_id: str) -> None:
    if st.session_state.get("active_case") == case_id and "initial_ranking" in st.session_state:
        return
    payload = service.start_case(case_id)
    st.session_state["active_case"] = case_id
    st.session_state["initial_ranking"] = payload["ranking"]
    st.session_state["last_measure"] = None
    st.session_state.pop("final_report", None)


def restart_case(service: UnknownIDService, case_id: str) -> None:
    try:
        service.reset_case(case_id)
    except Exception:
        pass
    st.session_state.pop("active_case", None)
    st.session_state.pop("initial_ranking", None)
    st.session_state.pop("last_measure", None)
    st.session_state.pop("final_report", None)
    start_case(service, case_id)


def require_case(service: UnknownIDService) -> str | None:
    case_id = state_case_id()
    if not case_id:
        st.info("Start an investigation on the **Investigation** screen first.")
        return None
    try:
        service.session(case_id)
    except ServiceError:
        st.warning("The investigation session is no longer available. Start it again.")
        st.session_state.pop("active_case", None)
        return None
    return case_id


# ---------------------------------------------------------------------------
# Screen 1 — dataset provenance
# ---------------------------------------------------------------------------
def screen_provenance(service: UnknownIDService) -> None:
    st.title("1 · Dataset provenance")
    st.markdown(BANNER, unsafe_allow_html=True)

    provenance = service.provenance()
    columns = st.columns(4)
    columns[0].metric("Library molecules", f"{provenance['library_molecules']:,}")
    columns[1].metric("Curated spectra", f"{len(load_frame(str(CURATED / 'library.parquet'))):,}")
    columns[2].metric("Complete 5-energy cases", f"{sum(provenance['cases'].values()):,}")
    columns[3].metric("Raw MassBank records", f"{provenance.get('record_count', 0):,}")

    st.subheader("Source snapshot")
    left, right = st.columns([1.25, 1])
    with left:
        st.markdown(
            f"""
- **Repository:** [{esc(provenance.get('source_repository'))}]({esc(provenance.get('source_repository'))})
- **Pinned commit:** `{esc(provenance.get('source_commit'))}`
- **Contributor:** `Athens_Univ`
- **Retrieved (UTC):** {esc(provenance.get('retrieved_at_utc'))}
- **Persistent archive:** [Zenodo 3378723](https://doi.org/10.5281/zenodo.3378723)
- **Citation:** Augmentation of MS/MS Libraries with Spectral Interpolation for Improved Identification,
  *J. Chem. Inf. Model.* 2022, [doi:10.1021/acs.jcim.2c00620](https://doi.org/10.1021/acs.jcim.2c00620)
            """
        )
        st.markdown(
            '<div class="uid-warn"><strong>Restrictions.</strong> No spectra are generated for '
            "identification. The static library contains only 10/50 eV reference spectra. "
            "The 20/30/40 eV query spectra are real archived measurements with embargoed "
            "accessions until an investigation is stopped.</div>",
            unsafe_allow_html=True,
        )
    with right:
        instrument = provenance.get("instrument", {})
        st.markdown("**Fixed experimental stratum**")
        st.dataframe(
            pd.DataFrame(
                [
                    ("Instrument", instrument.get("model")),
                    ("Type", instrument.get("type")),
                    ("Ionization", instrument.get("ionization")),
                    ("Ion mode", instrument.get("ion_mode")),
                    ("Fragmentation", instrument.get("fragmentation")),
                    ("Adduct", instrument.get("adduct")),
                    ("Collision energies", "10, 20, 30, 40, 50 eV"),
                    ("Precursor tolerance", "10 ppm"),
                    ("Standards only", "yes"),
                    ("License", "CC BY / CC BY-SA"),
                ],
                columns=["field", "value"],
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Split sizes")
    st.dataframe(
        pd.DataFrame(
            [{"split": key, "complete cases": value} for key, value in provenance["cases"].items()]
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Splits are scaffold-disjoint; a molecule appears in exactly one split. "
        "No test molecule is used for calibration."
    )

    st.subheader("Filter cascade")
    audit = pd.read_parquet(CURATED / "audit.parquet")
    cascade = audit[audit["category"] == "exclusion_cascade"].reset_index(drop=True)
    if not cascade.empty:
        cascade = cascade.rename(columns={"metric": "filter", "value": "records remaining"})
        st.dataframe(cascade[["filter", "records remaining"]], hide_index=True, width="stretch")
    with st.expander("Exclusion reasons and full audit table"):
        reasons = audit[audit["category"].isin(["exclusion_reason", "identity_qc", "difficulty", "spectra"])]
        st.dataframe(reasons, hide_index=True, width="stretch")
        audit_md = load_text(str(REPORTS / "data_audit.md"))
        if audit_md:
            st.markdown("---")
            st.markdown(audit_md)

    st.subheader("Example curated records")
    records = load_frame(str(CURATED / "records.parquet"), limit=200)
    if not records.empty:
        sample = records[
            ["accession", "name", "formula", "collision_energy_ev", "precursor_mz", "license"]
        ].head(12)
        st.dataframe(sample, hide_index=True, width="stretch")
    st.caption(
        "Every record above is a real experimental MassBank spectrum. Peak arrays were "
        "filtered to ≥1% relative intensity; precursor and identity metadata were retained."
    )


# ---------------------------------------------------------------------------
# Screen 2 — investigation
# ---------------------------------------------------------------------------
def screen_investigation(service: UnknownIDService) -> None:
    st.title("2 · Investigation")
    st.markdown(BANNER, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### Case browser")
        split = st.selectbox("Split", ["test", "dev", "train"], index=0, key="case_split")
        ids = service.case_ids(split)
        case_id = st.selectbox(
            f"{len(ids)} anonymised cases",
            ids,
            index=ids.index(state_case_id()) if state_case_id() in ids else 0,
            key="case_picker",
        )
        col_a, col_b = st.columns(2)
        if col_a.button("Start", width="stretch", type="primary"):
            start_case(service, case_id)
            st.rerun()
        if col_b.button("Random", width="stretch"):
            start_case(service, service.next_case_id(split))
            st.rerun()

    active = require_case(service)
    if not active:
        return

    payload = service.start_case(active)
    case = payload["case"]
    ranking = payload["ranking"]
    observation = payload["observation"]

    top = st.columns(4)
    top[0].metric("Case", active.replace("case-", "…"))
    top[1].metric("Precursor m/z", f"{case['precursor_mz']:.4f}")
    top[2].metric("Candidates", case["n_candidates"])
    top[3].metric("Remaining budget", payload["remaining_budget"])

    st.markdown(
        f"**Split:** `{case['split']}` &nbsp;·&nbsp; **Adduct:** `{esc(case['adduct'])}` "
        f"&nbsp;·&nbsp; **Instrument:** {esc(case['instrument_model'])} "
        f"&nbsp;·&nbsp; **Observed:** {', '.join(str(e) + ' eV' for e in payload['observed_energies'])}"
    )
    st.caption("The compound name and the source accession are withheld until the investigation is stopped.")

    st.subheader("Initial 20 eV stick spectrum")
    left, right = st.columns([1.6, 1])
    with left:
        st.plotly_chart(
            stick_plot(
                [("measured 20 eV", observation["spectrum"]["mz"], observation["spectrum"]["intensity"], MEASURED)],
                title="Measured query spectrum",
            ),
            width="stretch",
        )
    with right:
        frame = spectrum_frame(observation["spectrum"])
        st.markdown(
            f"**{len(frame)} retained peaks** · base peak normalised · "
            f"precursor **{case['precursor_mz']:.4f}** m/z"
        )
        st.dataframe(frame.head(80), hide_index=True, width="stretch", height=300)
        st.caption("Accession embargoed during the investigation.")

    st.subheader("Candidate ranking")
    if ranking.get("evidence"):
        table = ranking_table(ranking)
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={
                "support": st.column_config.ProgressColumn(
                    "support", min_value=0.0, max_value=1.0, format="%.3f"
                ),
            },
        )
        st.caption(
            "Support is relative evidence weight, **not** a calibrated probability of identity. "
            "Cosine values at 30/40 eV appear only after those energies are measured; "
            "reference templates are interpolations."
        )
        st.markdown("**Top candidate structures** (RDKit, from reference SMILES)")
        candidate_structures(ranking["evidence"])

        with st.expander("Evidence detail and reference accessions"):
            for index, evidence in enumerate(ranking["evidence"][:8], start=1):
                st.markdown(
                    f"**{index}. {esc(evidence.get('name'))}** · `{esc(evidence.get('candidate_id'))}`  \n"
                    f"{reference_links(evidence)}",
                    unsafe_allow_html=True,
                )
                if evidence.get("matched_fragments"):
                    fragments = pd.DataFrame(evidence["matched_fragments"])
                    st.dataframe(fragments, hide_index=True, width="stretch")
                if evidence.get("unexplained_peaks"):
                    st.caption(
                        "Unexplained observed m/z: "
                        + ", ".join(f"{value:.3f}" for value in evidence["unexplained_peaks"][:10])
                    )
                st.divider()
    else:
        st.warning("No candidate evidence was produced for this case.")

    with st.expander("Mirror plot: measured 20 eV vs interpolated template for the top candidate"):
        top_evidence = ranking["evidence"][0] if ranking.get("evidence") else None
        if top_evidence:
            template = service.template(active, top_evidence["candidate_id"], 20)
            st.plotly_chart(
                stick_plot(
                    [
                        ("measured 20 eV", observation["spectrum"]["mz"], observation["spectrum"]["intensity"], MEASURED),
                        (
                            f"interpolated 20 eV · {top_evidence.get('name')}",
                            template["spectrum"]["mz"],
                            template["spectrum"]["intensity"],
                            TEMPLATE,
                        ),
                    ],
                    title="Measured (up) vs interpolated reference (down)",
                    mirror=True,
                ),
                width="stretch",
            )
            st.caption(template["note"])

    st.divider()
    if st.button("Restart this case", type="secondary"):
        restart_case(service, active)
        st.rerun()


# ---------------------------------------------------------------------------
# Screen 3 — next experiment
# ---------------------------------------------------------------------------
def screen_next_experiment(service: UnknownIDService) -> None:
    st.title("3 · Choose the next experiment")
    st.markdown(BANNER, unsafe_allow_html=True)
    active = require_case(service)
    if not active:
        return

    payload = service.start_case(active)
    plan = service.plan(active)
    case = payload["case"]

    method = plan.get("method")
    validated = payload.get("calibration_validated")
    label = "Monte-Carlo expected information gain" if method == "monte_carlo_ig" else "Disagreement heuristic (not IG)"
    st.markdown(
        f"**Policy:** {label} &nbsp;·&nbsp; **Dev-validated:** "
        f"{'yes' if validated else 'no'} &nbsp;·&nbsp; **Budget left:** {payload['remaining_budget']}"
    )
    if method != "monte_carlo_ig":
        st.warning(
            "The error model is not calibrated, so the planner is using a clearly labelled "
            "template-disagreement heuristic. Scores are not information gain."
        )

    recommended = plan.get("recommended", {})
    if recommended.get("kind") == "measure":
        st.success(
            f"Recommended action: measure **{recommended.get('energy_ev')} eV** "
            f"(predicted IG ≈ {recommended.get('predicted_information_gain', 0.0):.4f})."
        )
    else:
        st.info(f"No measurement recommended: {plan.get('note')}")

    st.subheader("Predicted value of each allowed measurement")
    options = plan.get("options") or []
    if options:
        table = pd.DataFrame(
            [
                {
                    "energy (eV)": option["energy_ev"],
                    "predicted IG": round(option["predicted_information_gain"], 4),
                    "template separation": round(option["separation"], 4),
                    "interpolation reliability": round(option["reliability"], 4),
                    "cost": option["cost"],
                    "score": round(option["score"], 4),
                    "method": option["method"],
                }
                for option in options
            ]
        )
        st.dataframe(table, hide_index=True, width="stretch")
        st.caption(
            "These are **predictions**, computed from 10/50 eV references plus the train-fitted "
            "noise model. No hidden measurement is read to produce them."
        )
    else:
        st.caption("No unobserved energy remains available under the current budget.")

    st.subheader("Request a measurement")
    observed = set(payload["observed_energies"])
    budget = payload["remaining_budget"]
    columns = st.columns(2)
    for column, energy in zip(columns, [30, 40]):
        with column:
            disabled = budget <= 0 or energy in observed
            reason = (
                "already measured"
                if energy in observed
                else ("budget exhausted" if budget <= 0 else "reveals one real archived measurement")
            )
            st.markdown(f"**{energy} eV**  \n<span class='uid-muted'>{reason}</span>", unsafe_allow_html=True)
            if st.button(
                f"Measure {energy} eV",
                key=f"measure_{energy}",
                disabled=disabled,
                type="primary" if recommended.get("energy_ev") == energy else "secondary",
                width="stretch",
            ):
                try:
                    result = service.measure(active, energy)
                except Exception as exc:  # noqa: BLE001 - shown to the investigator
                    st.error(str(exc))
                else:
                    st.session_state["last_measure"] = {
                        "energy": energy,
                        "measurement": result["measurement"],
                        "remaining_budget": result["remaining_budget"],
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    }
                    st.rerun()

    last = st.session_state.get("last_measure")
    if last:
        st.markdown(
            f'<div class="uid-warn"><strong>Measured {last["energy"]} eV.</strong> '
            "This spectrum is a real experimental observation. Its accession remains embargoed.</div>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(
            stick_plot(
                [
                    (
                        f"measured {last['energy']} eV",
                        last["measurement"]["spectrum"]["mz"],
                        last["measurement"]["spectrum"]["intensity"],
                        MEASURED,
                    )
                ],
                title=f"Measured {last['energy']} eV query spectrum",
            ),
            width="stretch",
        )

    st.subheader("Current ranking after measurements")
    ranking = service.ranking(active)
    if ranking.get("evidence"):
        st.dataframe(ranking_table(ranking), hide_index=True, width="stretch")
    st.caption(
        "When the precommitted confidence rule is satisfied, or no measurement is predicted "
        "to help, the recommendation becomes **Stop**. You may stop at any time on screen 4."
    )

    if st.button("Stop and write final report", type="primary"):
        st.session_state["final_report"] = service.stop(active)
        st.success("Investigation stopped. Open **4 · Final report**.")


# ---------------------------------------------------------------------------
# Screen 4 — final report
# ---------------------------------------------------------------------------
def screen_report(service: UnknownIDService) -> None:
    st.title("4 · Final report")
    active = require_case(service)
    if not active:
        return

    session = service.session(active)
    if not session.stopped:
        st.info(
            "The investigation is still open. Stop it to freeze the verdict and release "
            "the measurement accessions."
        )
        if st.button("Stop investigation", type="primary"):
            st.session_state["final_report"] = service.stop(active)
            st.rerun()
        ranking = service.ranking(active)
        if ranking.get("evidence"):
            st.subheader("Provisional ranking")
            st.dataframe(ranking_table(ranking), hide_index=True, width="stretch")
        return

    report = st.session_state.get("final_report") or service.report(active)
    investigation = report["investigation"]
    decision = investigation["decision"]

    st.markdown(
        f"### Verdict &nbsp; {decision_pill(decision)}",
        unsafe_allow_html=True,
    )
    columns = st.columns(4)
    predicted_id = investigation.get("predicted_identity")
    predicted_name = next(
        (
            item.get("name")
            for item in investigation.get("candidate_evidence", [])
            if item.get("candidate_id") == predicted_id
        ),
        predicted_id,
    )
    columns[0].metric("Observed energies", ", ".join(f"{e} eV" for e in investigation["observations"]))
    columns[1].metric("Scans used", max(len(investigation["observations"]) - 1, 0))
    columns[2].metric("Predicted identity", predicted_name or "abstained")
    columns[3].metric(
        "Support",
        "—" if investigation.get("confidence") is None else f"{investigation['confidence']:.3f}",
    )
    if predicted_id:
        st.caption(f"Full InChIKey: `{predicted_id}`")
    if decision == "identified":
        st.success(
            "The precommitted support and margin rule was satisfied and no same-connectivity "
            "stereoisomer competitor remained. This is a closed-world library identification."
        )
    elif decision == "ambiguous":
        st.warning(
            "Evidence did not satisfy the precommitted identification rule. The system abstains "
            "rather than guessing."
        )
    else:
        st.error(
            "No candidate produced enough matched evidence. The closed-world library is reported "
            "as inadequate for this query."
        )

    st.subheader("Before vs after")
    initial = st.session_state.get("initial_ranking")
    final = {"evidence": investigation["candidate_evidence"]}
    left, right = st.columns(2)
    with left:
        st.markdown("**At case start (20 eV only)**")
        if initial and initial.get("evidence"):
            st.dataframe(
                ranking_table(initial)[["#", "candidate", "support", "cosine 20 eV"]].head(6),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("Initial ranking snapshot unavailable in this session.")
    with right:
        st.markdown("**Final**")
        st.dataframe(
            ranking_table(final)[["#", "candidate", "support", "cosine 20 eV", "cosine 30 eV", "cosine 40 eV"]].head(6),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Spectral evidence")
    for energy in investigation["observations"]:
        observation = session.observation(int(energy))
        top = investigation["candidate_evidence"][0] if investigation["candidate_evidence"] else None
        traces = [
            (
                f"measured {energy} eV",
                observation["spectrum"]["mz"],
                observation["spectrum"]["intensity"],
                MEASURED,
            )
        ]
        if top:
            template = service.template(active, top["candidate_id"], int(energy))
            traces.append(
                (
                    f"interpolated {energy} eV · {top['name']}",
                    template["spectrum"]["mz"],
                    template["spectrum"]["intensity"],
                    TEMPLATE,
                )
            )
        with st.expander(f"{energy} eV — measured vs interpolated reference", expanded=energy == 20):
            st.plotly_chart(
                stick_plot(traces, title=f"{energy} eV", mirror=len(traces) > 1, height=320),
                width="stretch",
            )
            st.caption(
                "Downward bars are interpolated from static 10/50 eV references. "
                "Upward bars are measurements."
            )

    st.subheader("Full candidate evidence")
    st.dataframe(ranking_table(final), hide_index=True, width="stretch")
    with st.expander("Reference accessions and diagnostic fragments"):
        for evidence in investigation["candidate_evidence"][:8]:
            st.markdown(
                f"**{esc(evidence.get('name'))}** · `{esc(evidence.get('candidate_id'))}`  \n"
                f"{reference_links(evidence)}",
                unsafe_allow_html=True,
            )
            if evidence.get("matched_fragments"):
                st.dataframe(
                    pd.DataFrame(evidence["matched_fragments"]),
                    hide_index=True,
                    width="stretch",
                )
            st.divider()

    st.subheader("Quality control")
    qc = investigation.get("qc") or {}
    st.dataframe(
        pd.DataFrame([{"check": key, "value": json.dumps(value) if isinstance(value, (dict, list)) else value} for key, value in qc.items()]),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Provenance")
    provenance = investigation.get("provenance", {})
    st.markdown(
        f"- **Source commit:** `{esc(provenance.get('source_commit'))}`\n"
        f"- **Instrument:** {esc(provenance.get('instrument_model'))}\n"
        f"- **Acquisition method:** `{esc(provenance.get('acquisition_method'))}`\n"
        f"- **Error model calibrated:** {esc(provenance.get('error_model_calibrated'))}\n"
        f"- **Candidate weights calibrated:** {esc(provenance.get('weights_are_calibrated'))} "
        f"({esc(provenance.get('probability_calibration'))})\n"
        f"- **Template method:** `{esc(provenance.get('template_method'))}` "
        f"({esc(provenance.get('match_tolerance_da'))} Da matching)\n"
        f"- **Truth identity released:** {esc(provenance.get('truth_identity_released'))}"
    )
    accessions = provenance.get("observed_accessions", {})
    st.markdown("**Released measurement accessions**")
    for energy, accession in sorted(accessions.items(), key=lambda item: int(item[0])):
        url = REFERENCE_URL.format(accession=accession)
        st.markdown(f"- {energy} eV: [{esc(accession)}]({url})")
    st.caption(provenance.get("note", ""))

    st.subheader("Limitations")
    for limitation in investigation.get("limitations", []):
        st.markdown(f"- {limitation}")

    st.subheader("Export")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    download_a, download_b = st.columns(2)
    download_a.download_button(
        "Download Markdown report",
        data=report["report_markdown"],
        file_name=f"unknownid_{active}_{stamp}.md",
        mime="text/markdown",
        width="stretch",
    )
    download_b.download_button(
        "Download JSON report",
        data=json.dumps(report["investigation"], indent=2, default=str),
        file_name=f"unknownid_{active}_{stamp}.json",
        mime="application/json",
        width="stretch",
    )

    with st.expander("Rendered Markdown report"):
        st.markdown(report["report_markdown"])

    if st.button("Investigate this case again"):
        restart_case(service, active)
        st.rerun()


# ---------------------------------------------------------------------------
# Screen 5 — evaluation dashboard
# ---------------------------------------------------------------------------
def screen_evaluation(service: UnknownIDService) -> None:
    st.title("5 · Evaluation dashboard")
    st.caption(
        "Frozen test-split results. Thresholds and the acquisition method were selected on dev; "
        "no test-set tuning. Small cohorts mean wide confidence intervals."
    )
    report = load_json(str(EVALUATION_JSON))
    if not report:
        st.error("`reports/evaluation.json` is missing. Run `make eval`.")
        return

    markdown = load_text(str(EVALUATION_MD))
    headline = ""
    if "## Headline result" in markdown:
        block = markdown.split("## Headline result", 1)[1].split("\n## ", 1)[0]
        headline = " ".join(line.strip() for line in block.strip().splitlines() if line.strip())
    if headline:
        st.markdown(f'<div class="uid-banner">{esc(headline)}</div>', unsafe_allow_html=True)

    n_cases = report.get("n_cases", {})
    columns = st.columns(4)
    columns[0].metric("Test cases", n_cases.get("all test", 0))
    columns[1].metric("Ambiguous", n_cases.get("ambiguous (>=2 precursor-consistent candidates)", 0))
    columns[2].metric("Close calls", n_cases.get("close-call (top-2 margin <= 0.15)", 0))
    easy_fraction = (
        n_cases.get("easy (precursor-unique)", 0) / max(n_cases.get("all test", 1), 1)
    )
    columns[3].metric("Precursor-unique", f"{easy_fraction:.1%}")

    st.markdown(
        f"**Acquisition method:** `{report.get('method')}` &nbsp;·&nbsp; "
        f"**Generated:** {report.get('generated_at_utc')} &nbsp;·&nbsp; "
        f"**Random trials per molecule:** 20"
    )

    cohorts = list(report.get("summaries", {}))
    cohort_labels = {
        "all": "All test cases",
        "ambiguous": "Ambiguous (≥2 candidates)",
        "close_call": "Close calls (margin ≤ 0.15)",
        "easy": "Precursor-unique",
    }
    selected = st.selectbox(
        "Cohort",
        cohorts,
        index=cohorts.index("ambiguous") if "ambiguous" in cohorts else 0,
        format_func=lambda key: cohort_labels.get(key, key),
    )
    summary = report["summaries"][selected]
    policies = list(summary)

    rows = []
    for policy in policies:
        entry = summary[policy]
        rows.append(
            {
                "policy": policy,
                "n": entry.get("n"),
                "top-1 @0": entry.get("top1_0"),
                "top-1 @1": entry.get("top1_1"),
                "top-1 @2": entry.get("top1_2"),
                "MRR @2": entry.get("mrr_2"),
                "top-3 @2": entry.get("top3_2"),
                "scans @1": entry.get("scans_1"),
                "scans @2": entry.get("scans_2"),
                "coverage": entry.get("coverage"),
                "risk": entry.get("risk"),
            }
        )
    frame = pd.DataFrame(rows)
    st.subheader(f"Policy metrics — {cohort_labels.get(selected, selected)}")
    st.dataframe(
        frame.style.format(
            {
                "top-1 @0": "{:.3f}",
                "top-1 @1": "{:.3f}",
                "top-1 @2": "{:.3f}",
                "MRR @2": "{:.3f}",
                "top-3 @2": "{:.3f}",
                "scans @1": "{:.2f}",
                "scans @2": "{:.2f}",
                "coverage": "{:.3f}",
                "risk": "{:.3f}",
            },
            na_rep="—",
        ),
        hide_index=True,
        width="stretch",
    )

    chart_left, chart_right = st.columns(2)
    with chart_left:
        figure = go.Figure()
        for metric, color in (("top-1 @1", "#2f6f62"), ("top-1 @2", "#7aa89f")):
            figure.add_trace(go.Bar(x=frame["policy"], y=frame[metric], name=metric, marker_color=color))
        figure.update_layout(
            title="Top-1 accuracy after 1 and 2 optional scans",
            barmode="group",
            height=360,
            yaxis_range=[0, 1.05],
            margin=dict(l=10, r=10, t=48, b=10),
            legend=dict(orientation="h", y=1.12),
        )
        st.plotly_chart(figure, width="stretch")
    with chart_right:
        figure = go.Figure()
        figure.add_trace(
            go.Bar(
                x=frame["policy"],
                y=frame["scans @2"],
                name="mean scans",
                marker_color="#d97706",
                text=frame["scans @2"],
                textposition="outside",
            )
        )
        figure.update_layout(
            title="Mean optional acquisitions by the second decision",
            height=360,
            margin=dict(l=10, r=10, t=48, b=10),
            yaxis_title="scans",
        )
        st.plotly_chart(figure, width="stretch")
    st.caption(
        "Scans @1 counts acquisitions before the first stop/identification check; Scans @2 is "
        "the total under the two-scan evaluation budget. Coverage is the fraction of cases "
        "the policy was willing to call; risk is the error rate among those calls."
    )

    st.subheader("Paired differences versus UnknownID (molecule-level bootstrap)")
    comparisons = report.get("paired_comparisons", {})
    comparison_rows = []
    for cohort, entries in comparisons.items():
        for baseline, metrics in entries.items():
            for metric, diff in metrics.items():
                comparison_rows.append(
                    {
                        "cohort": cohort,
                        "baseline": baseline,
                        "metric": metric,
                        "difference": diff.get("mean_difference"),
                        "CI low": diff.get("ci_low"),
                        "CI high": diff.get("ci_high"),
                        "wins": diff.get("wins"),
                        "losses": diff.get("losses"),
                        "verdict": (
                            "inconclusive"
                            if (diff.get("ci_low") or 0) <= 0 <= (diff.get("ci_high") or 0)
                            else ("UnknownID better" if (diff.get("mean_difference") or 0) > 0 else "baseline better")
                        ),
                    }
                )
    if comparison_rows:
        comparison_frame = pd.DataFrame(comparison_rows)
        cohort_filter = st.multiselect(
            "Filter cohort", sorted(comparison_frame["cohort"].unique()), default=["ambiguous", "all"]
        )
        metric_filter = st.multiselect(
            "Filter metric", sorted(comparison_frame["metric"].unique()), default=["top1_1", "top1_2"]
        )
        shown = comparison_frame[
            comparison_frame["cohort"].isin(cohort_filter) & comparison_frame["metric"].isin(metric_filter)
        ]
        st.dataframe(
            shown.style.format({"difference": "{:+.4f}", "CI low": "{:+.4f}", "CI high": "{:+.4f}"}),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "An interval spanning zero is reported as inconclusive, not as a win. "
            "Positive differences favour UnknownID."
        )

    st.subheader("Planner validation")
    ig = report.get("ig_validation", {})
    ig_columns = st.columns(4)
    ig_columns[0].metric("Prediction pairs", ig.get("n_pairs", 0))
    ig_columns[1].metric("Spearman ρ", f"{ig.get('spearman', 0):.3f}")
    ig_columns[2].metric("p-value", f"{ig.get('pvalue', 0):.3g}")
    ig_columns[3].metric("Mean regret", f"{ig.get('mean_regret', 0):.3f}")
    st.caption(
        "Both 30 and 40 eV spectra are revealed **after** the plan only to score its prediction. "
        "The planner never reads them before choosing."
    )

    st.subheader("Failure breakdown")
    failures = report.get("failures", [])
    if failures:
        st.dataframe(pd.DataFrame(failures), hide_index=True, width="stretch")
    else:
        st.success("No top-1 failures in this cohort.")

    open_world = report.get("open_world", {})
    if open_world:
        st.subheader("Open-world stress test (true molecule removed)")
        attempted = [row for row in open_world.get("cases", []) if row.get("n_remaining", 0) > 0]
        wrong_attempted = sum(1 for row in attempted if row.get("decision_after_action") == "identified")
        columns = st.columns(4)
        columns[0].metric("Out-of-library @20 eV", f"{open_world.get('out_of_library_at_20_rate', 0):.1%}")
        columns[1].metric(
            "Out-of-library after action", f"{open_world.get('out_of_library_after_action_rate', 0):.1%}"
        )
        columns[2].metric(
            "Confident wrong match", f"{open_world.get('identified_wrong_library_match_rate', 0):.1%}"
        )
        columns[3].metric(
            "Wrong among alternatives", f"{wrong_attempted}/{len(attempted)}" if attempted else "—"
        )
        st.caption(open_world.get("note", ""))

    with st.expander("Full evaluation report and calibration record"):
        if markdown:
            st.markdown(markdown)
        calibration = load_text(str(CALIBRATION_MD))
        if calibration:
            st.markdown("---")
            st.markdown(calibration)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    with st.sidebar:
        st.markdown("## 🧪 UnknownID")
        st.caption("Closed-world MS/MS identification with budgeted collision-energy selection")
        screen = st.radio(
            "Screen",
            [
                "1 · Provenance",
                "2 · Investigation",
                "3 · Next experiment",
                "4 · Final report",
                "5 · Evaluation",
            ],
        )
        st.divider()
        try:
            service = get_service()
        except ServiceError as exc:
            st.error(str(exc))
            st.stop()
        active = state_case_id()
        if active:
            st.markdown(f"**Active case:** `{active}`")
            try:
                session = service.session(active)
                st.caption(
                    f"{'stopped' if session.stopped else 'open'} · "
                    f"{session.remaining_budget} measurement(s) left · "
                    f"observed {', '.join(str(e) for e in session.observed_energies)} eV"
                )
            except ServiceError:
                pass
        st.divider()
        st.caption(
            "Weights are relative support, not calibrated identity probabilities. "
            "Closed-world only; no de novo structure elucidation."
        )

    if screen.startswith("1"):
        screen_provenance(service)
    elif screen.startswith("2"):
        screen_investigation(service)
    elif screen.startswith("3"):
        screen_next_experiment(service)
    elif screen.startswith("4"):
        screen_report(service)
    else:
        screen_evaluation(service)


if __name__ == "__main__":
    main()

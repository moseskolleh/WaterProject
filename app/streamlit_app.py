"""Groundwater toolkit web interface.

Lets the field team upload data files in the standard templates and
produces the analysis figures and client-ready reports without
touching code. Covers the full project lifecycle: VES siting surveys,
pumping tests, water quality, borehole design, cost estimation and
drilling supervision checklists.

Run from the repository root:

    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import streamlit as st
import yaml

import groundwater
from groundwater.config import Config
from groundwater.costing import (
    CostingInputs,
    RateItem,
    estimate_borehole_cost,
    estimate_programme_cost,
    inputs_from_design,
    load_rates,
    plot_cost_breakdown,
    plot_programme_gantt,
    write_boq_workbook,
)
from groundwater.design import design_borehole, draw_borehole_design
from groundwater.hydraulics import analyse_pumping_test
from groundwater.hydraulics.plots import (
    plot_cooper_jacob,
    plot_recovery,
    plot_step_test,
    plot_test_overview,
)
from groundwater.ingestion import (
    check_all,
    read_drilling_workbook,
    read_pumping_docx,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.ingestion.templates import write_all_templates
from groundwater.mapping import (
    plot_admin_map,
    plot_geological_map,
    plot_hydrogeology_map,
)
from groundwater.models import SiteMetadata
from groundwater.quality import assess_sample, plot_piper, plot_stiff
from groundwater.reporting.costing import CostReportInputs, build_cost_report
from groundwater.reporting.handover import (
    CommitteeMember,
    HandoverReportInputs,
    build_handover_report,
)
from groundwater.reporting.geophysical import (
    GeophysicalReportInputs,
    build_geophysical_report,
)
from groundwater.reporting.pumping import PumpingReportInputs, build_pumping_report
from groundwater.reporting.quality import QualityReportInputs, build_quality_report
from groundwater.reporting.supervision import (
    SupervisionReportInputs,
    build_supervision_report,
)
from groundwater.supervision import (
    ChecklistResponse,
    annular_space_check,
    disinfection_dose,
    evaluate_checklist,
    handpump_corrosion_check,
    load_checklists,
    load_separation_distances,
    metres_reconciliation_check,
    sand_content_check,
    specific_capacity_check,
    stage_title,
    verticality_check,
)
from groundwater.utils import fmt_num
from groundwater.ves import interpret_model, invert_sounding
from groundwater.ves.interpret import drilling_preference_table
from groundwater.ves.plots import plot_sounding_curve

# ---------------------------------------------------------------------------
# Page setup and branding
# ---------------------------------------------------------------------------

_BRAND_DIR = Path(groundwater.__file__).resolve().parent / "data" / "brand"


def _brand(name: str) -> str | None:
    path = _BRAND_DIR / name
    return str(path) if path.exists() else None


_ICON = _brand("icon.png")
_LOGO = _brand("logo.png")

st.set_page_config(
    page_title="Groundwater Toolkit",
    page_icon=_ICON or ":droplet:",
    layout="wide",
    menu_items={
        "About": (
            "Groundwater Investigation Toolkit - analysis and reporting "
            "for rural water supply borehole projects in Sierra Leone. "
            "Methods follow RWSN/UNICEF professional drilling guidance "
            "and WHO drinking water quality guidelines."
        ),
    },
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 2.4rem; }
      div[data-testid="stMetric"] {
        background: var(--secondary-background-color, #F2F6FA);
        border: 1px solid rgba(31, 92, 139, 0.18);
        border-radius: 0.6rem;
        padding: 0.65rem 0.9rem;
      }
      div[data-testid="stMetric"] label { color: #1F5C8B; }
      button[data-baseweb="tab"] { font-size: 0.95rem; }
      div[data-testid="stSidebarUserContent"] .stCaption p { line-height: 1.35; }
    </style>
    """,
    unsafe_allow_html=True,
)

if _LOGO:
    try:
        st.logo(_LOGO, icon_image=_ICON)
    except Exception:
        pass

CONFIG = Config()
IN_BROWSER = sys.platform == "emscripten"  # running under Pyodide (GitHub Pages demo)


# Static catalogues, parsed once per session (the script reruns on
# every widget interaction; without caching each rerun re-reads the
# bundled CSVs).
@st.cache_data
def cached_rates():
    return load_rates()


@st.cache_data
def cached_checklists():
    return load_checklists()


@st.cache_data
def cached_separation_distances():
    return load_separation_distances()


def workdir() -> Path:
    if "workdir" not in st.session_state:
        st.session_state.workdir = Path(tempfile.mkdtemp(prefix="gw_"))
    return st.session_state.workdir


def save_upload(uploaded) -> Path:
    path = workdir() / uploaded.name
    path.write_bytes(uploaded.getbuffer())
    return path


def sample_data_dir() -> Path | None:
    """Bundled sample datasets, when present (repo checkout or web demo)."""
    here = Path(__file__).resolve().parent
    for candidate in (
        here.parent / "examples" / "data",
        here / "examples" / "data",
        Path("examples/data"),
    ):
        if candidate.is_dir():
            return candidate
    return None


def choose_input(label: str, key: str, types: list[str], samples: list[str]) -> Path | None:
    """File uploader with an optional bundled-sample fallback.

    Returns the path of the uploaded file, the chosen sample, or None.
    """
    upload = st.file_uploader(label, type=types, key=f"upload_{key}")
    if upload is not None:
        return save_upload(upload)
    root = sample_data_dir()
    if root is not None:
        available = [s for s in samples if (root / s).exists()]
        if available:
            none_option = "(or pick a bundled sample to try)"
            pick = st.selectbox(
                "No file uploaded yet", [none_option] + available, key=f"sample_{key}"
            )
            if pick != none_option:
                return root / pick
    return None


def show_flags(flags, collapse_after: int = 4) -> None:
    """Data check flags, folded into an expander when there are many."""
    flags = list(flags)
    if not flags:
        return

    def _render(items) -> None:
        for flag in items:
            text = str(flag)
            if flag.level == "error":
                st.error(text)
            elif flag.level == "warning":
                st.warning(text)
            else:
                st.info(text)

    if len(flags) <= collapse_after:
        _render(flags)
        return
    worst = "error" if any(f.level == "error" for f in flags) else (
        "warning" if any(f.level == "warning" for f in flags) else "info"
    )
    icon = {"error": "🚫", "warning": "⚠️", "info": "ℹ️"}[worst]
    with st.expander(f"{icon} Data checks ({len(flags)})", expanded=(worst == "error")):
        _render(flags)


def offer_download(path: Path, label: str) -> None:
    with open(path, "rb") as fh:
        st.download_button(label, fh.read(), file_name=path.name)


def site_from_state() -> SiteMetadata:
    """Site metadata from the shared sidebar site details."""
    get = st.session_state.get

    def num(key):
        value = get(key, 0.0)
        return float(value) if value else None

    return SiteMetadata(
        community=get("meta_community", "") or "",
        chiefdom=get("meta_chiefdom", "") or "",
        district=get("meta_district", "") or "",
        client=get("meta_client", "") or "",
        project=get("meta_project", "") or "",
        contractor=get("meta_contractor", "") or "",
        supervisor=get("meta_supervisor", "") or "",
        date=get("meta_date", "") or "",
        easting=num("meta_easting"),
        northing=num("meta_northing"),
        utm_zone=int(get("meta_zone", "29N").rstrip("N")),
    )


# ---------------------------------------------------------------------------
# Project file: save and restore the whole working state
# ---------------------------------------------------------------------------

_PERSIST_PREFIXES = ("org_", "meta_", "chk_", "rmk_", "cost_", "fx_", "ho_")


def project_file_bytes() -> bytes:
    """Serialize the widget state that makes up a project."""
    state = {
        key: value
        for key, value in st.session_state.items()
        if key.startswith(_PERSIST_PREFIXES)
        and isinstance(value, (str, int, float, bool))
    }
    payload = {
        "groundwater_toolkit_project": groundwater.__version__,
        "rates_overrides": st.session_state.get("rates_overrides", {}),
        "state": state,
    }
    return yaml.safe_dump(payload, sort_keys=True).encode("utf-8")


def _load_project() -> None:
    """Apply an uploaded project file (button callback, runs pre-render)."""
    upload = st.session_state.get("project_upload")
    if upload is None:
        return
    try:
        payload = yaml.safe_load(upload.getvalue().decode("utf-8"))
        assert isinstance(payload, dict) and "state" in payload
    except Exception:
        st.session_state.project_load_error = True
        return
    for key, value in payload["state"].items():
        if key.startswith(_PERSIST_PREFIXES) and isinstance(
            value, (str, int, float, bool)
        ):
            st.session_state[key] = value
    overrides = payload.get("rates_overrides") or {}
    if isinstance(overrides, dict):
        st.session_state.rates_overrides = {
            str(code): float(rate) for code, rate in overrides.items()
        }
    # reset the rate editor so it shows the loaded values
    st.session_state.pop("rates_editor", None)
    st.session_state.project_loaded = True


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 💧 Groundwater Toolkit")
    st.caption(
        "Field data in, client-ready reports out - for rural water "
        "supply borehole projects in Sierra Leone."
    )
    with st.expander("🧭 Suggested workflow", expanded=False):
        st.markdown(
            "1. **VES survey** - siting and drilling depth\n"
            "2. **Costing** - budget and bill of quantities\n"
            "3. **Supervision** - checklists while drilling\n"
            "4. **Borehole design** - from the drilling log\n"
            "5. **Pumping test** - safe yield and pump depth\n"
            "6. **Water quality** - WHO/national verdict\n\n"
            "Every tab offers bundled sample data, so you can try "
            "each step without your own files."
        )
    with st.expander("📍 Site details (used by all tabs)"):
        st.text_input("Community", key="meta_community")
        st.text_input("Chiefdom", key="meta_chiefdom")
        st.text_input("District", key="meta_district")
        st.text_input("Client", key="meta_client")
        st.text_input("Project", key="meta_project")
        st.text_input("Drilling contractor", key="meta_contractor")
        st.text_input("Supervisor", key="meta_supervisor")
        st.text_input("Date", key="meta_date")
        col_e, col_n = st.columns(2)
        col_e.number_input("GPS East (UTM m)", min_value=0.0, step=100.0,
                           key="meta_easting", format="%.0f")
        col_n.number_input("GPS North (UTM m)", min_value=0.0, step=100.0,
                           key="meta_northing", format="%.0f")
        st.selectbox("UTM zone", ["28N", "29N"], index=1, key="meta_zone")
    with st.expander("📄 Report branding"):
        st.text_input(
            "Organisation name",
            key="org_name",
            help="Shown in the headers of generated reports.",
        )
        st.text_input("Organisation details", key="org_details",
                      help="Address or contact line under the name.")
    with st.expander("💾 Project file"):
        st.caption(
            "Save the whole working state (site details, checklist "
            "answers, costing inputs and edited rates) and load it "
            "back later or on another machine."
        )
        st.download_button(
            "Save project (.yaml)",
            project_file_bytes(),
            file_name=(
                (st.session_state.get("meta_community") or "groundwater")
                .replace(" ", "_") + "_project.yaml"
            ),
            key="project_download",
        )
        st.file_uploader("Project file", type=["yaml", "yml"],
                         key="project_upload")
        st.button("Load project", key="project_load", on_click=_load_project)
        if st.session_state.pop("project_loaded", False):
            st.success("Project loaded.")
        if st.session_state.pop("project_load_error", False):
            st.error("That file is not a toolkit project file.")
    st.caption(
        "Methods follow RWSN/UNICEF professional drilling guidance "
        "and WHO water quality guidelines. "
        f"Toolkit version {groundwater.__version__}."
    )


def app_config() -> Config:
    """Config with the sidebar branding applied (per rerun, not global)."""
    cfg = Config()
    cfg.style.organisation = st.session_state.get("org_name", "") or ""
    cfg.style.organisation_details = st.session_state.get("org_details", "") or ""
    return cfg


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("Groundwater Investigation Toolkit")
st.caption(
    "Vertical electrical soundings, pumping tests, water quality, "
    "borehole design, costing and drilling supervision for rural water "
    "supply projects in Sierra Leone."
)
if IN_BROWSER:
    st.info(
        "This demo runs entirely in your browser; nothing is uploaded to any "
        "server. Heavy steps such as the VES inversion take noticeably longer "
        "here than in the full installation. Every tab has bundled sample "
        "data so you can try it without your own files."
    )

(
    tab_ves,
    tab_pump,
    tab_quality,
    tab_design,
    tab_cost,
    tab_supervision,
    tab_handover,
    tab_maps,
    tab_extract,
    tab_templates,
) = st.tabs(
    [
        "📈 VES survey",
        "⏱️ Pumping test",
        "🧪 Water quality",
        "🛠️ Borehole design",
        "💰 Costing",
        "✅ Supervision",
        "🤝 Handover",
        "🗺️ Maps",
        "📄 Scanned sheets",
        "📋 Templates",
    ]
)

# ---------------------------------------------------------------------------
# VES
# ---------------------------------------------------------------------------
with tab_ves:
    st.header("VES survey analysis")
    st.caption(
        "Upload the VES workbook, run the inversion and get sounding "
        "curves, water zones and a drilling preference table."
    )
    path = choose_input(
        "VES workbook (standard template)", "ves", ["xlsx"],
        ["rokel/rokel_ves.xlsx"],
    )
    if path is not None:
        soundings = read_ves_workbook(path)
        if not soundings:
            st.error("No soundings found in the workbook.")
        else:
            st.success(f"Parsed {len(soundings)} sounding(s).")
            for s in soundings:
                show_flags(s.flags)
            show_flags(check_all([(s.sounding_id, s.site) for s in soundings]))

            if st.button("Run inversion and interpretation", key="run_ves",
                         type="primary"):
                results = []
                interps = []
                progress = st.progress(0.0)
                for i, sounding in enumerate(soundings):
                    result = invert_sounding(sounding, CONFIG.ves)
                    interp = interpret_model(sounding, result.model, CONFIG.ves)
                    results.append(result)
                    interps.append(interp)
                    progress.progress((i + 1) / len(soundings))
                st.session_state.ves_results = (soundings, results, interps)

    if "ves_results" in st.session_state:
        soundings, results, interps = st.session_state.ves_results
        for sounding, result, interp in zip(soundings, results, interps):
            with st.container(border=True):
                st.subheader(f"{sounding.sounding_id}")
                col_fig, col_txt = st.columns([3, 2])
                fig_path = workdir() / f"curve_{sounding.sounding_id.replace(' ', '_')}.png"
                plot_sounding_curve(
                    sounding, result.model, result.rho_calc, result.ab2, path=fig_path
                )
                col_fig.image(str(fig_path))
                col_txt.metric("Model fit (ERR)", f"{result.fit_error_percent:.1f}%")
                col_txt.metric(
                    "Water bearing zones",
                    ", ".join(f"{int(t)}-{int(b)} m" for t, b in interp.water_zones)
                    or "none",
                )
                col_txt.write(interp.narrative)
        st.subheader("Drilling preference")
        st.table(drilling_preference_table(interps))

        if st.button("Build geophysical survey report", key="build_geo_report"):
            report_path = build_geophysical_report(
                GeophysicalReportInputs(
                    soundings=soundings,
                    inversions=results,
                    interpretations=interps,
                    figures_dir=workdir(),
                    flags=check_all([(s.sounding_id, s.site) for s in soundings]),
                    include_qa_annex=True,
                ),
                workdir() / "Geophysical_Survey_Report.docx",
                app_config(),
            )
            offer_download(report_path, "Download geophysical survey report (.docx)")

# ---------------------------------------------------------------------------
# Pumping test
# ---------------------------------------------------------------------------
with tab_pump:
    st.header("Pumping test analysis")
    st.caption(
        "Constant discharge, step and recovery tests; missing discharges "
        "can be entered here and the yield analysis completes on the spot."
    )
    path = choose_input(
        "Pumping test sheet (template .xlsx or field .docx)", "pump", ["xlsx", "docx"],
        ["dr_timbo/dr_timbo_constant_test.xlsx", "kuntolo/kuntolo_step_test.xlsx"],
    )
    if path is not None:
        test = (
            read_pumping_docx(path) if path.suffix == ".docx" else read_pumping_workbook(path)
        )
        st.success(
            f"Parsed {test.test_type} test with {len(test.steps)} pumping series "
            f"and {'a' if test.recovery_time_min is not None else 'no'} recovery record."
        )
        show_flags(test.flags)

        missing = [s for s in test.steps if s.discharge_m3_per_h is None]
        if missing:
            st.info("Enter discharge rates to complete the analysis (m3/h).")
            cols = st.columns(len(test.steps))
            for col, step in zip(cols, test.steps):
                with col:
                    q = st.number_input(
                        f"{step.label} Q", min_value=0.0, value=0.0, step=0.1,
                        key=f"q_{step.step_number}",
                    )
                    if q > 0:
                        step.discharge_m3_per_h = q

        analysis = analyse_pumping_test(test, CONFIG.pumping)
        st.session_state.pump_analysis = analysis

        overview = workdir() / "overview.png"
        plot_test_overview(test, path=overview)
        st.image(str(overview))

        col1, col2 = st.columns(2)
        with col1:
            if analysis.cooper_jacob is not None:
                cj_path = workdir() / "cj.png"
                swl = test.static_water_level_m
                step = test.steps[0]
                plot_cooper_jacob(step.time_min, step.water_level_m - swl,
                                  analysis.cooper_jacob, path=cj_path)
                st.image(str(cj_path))
        with col2:
            if analysis.recovery is not None:
                rec_path = workdir() / "rec.png"
                plot_recovery(test.recovery_time_min, test.residual_drawdown(),
                              test.pumping_duration_min, analysis.recovery, path=rec_path)
                st.image(str(rec_path))
        if test.test_type.startswith("step"):
            st_path = workdir() / "steps.png"
            plot_step_test(test, analysis.step_test, path=st_path)
            st.image(str(st_path))

        st.subheader("Results")
        yr = analysis.yield_recommendation
        cols = st.columns(4)
        cols[0].metric(
            "Transmissivity",
            f"{analysis.transmissivity_m2_per_day:.1f} m2/day"
            if analysis.transmissivity_m2_per_day
            else "pending",
        )
        if yr is not None:
            cols[1].metric(
                "Available drawdown",
                f"{fmt_num(yr.available_drawdown_m)} m" if yr.available_drawdown_m else "n/a",
            )
            cols[2].metric(
                "Safe yield",
                f"{fmt_num(yr.safe_yield_m3_per_h)} m3/h" if yr.safe_yield_m3_per_h else "pending",
            )
            cols[3].metric(
                "Pump depth",
                f"{fmt_num(yr.pump_installation_depth_m)} m"
                if yr.pump_installation_depth_m
                else "pending",
            )
            st.caption(yr.basis)

        if st.button("Build pumping test report", key="build_pump_report"):
            report_path = build_pumping_report(
                PumpingReportInputs(analysis=analysis, figures_dir=workdir()),
                workdir() / "Pumping_Test_Report.docx",
                app_config(),
            )
            offer_download(report_path, "Download pumping test report (.docx)")

# ---------------------------------------------------------------------------
# Water quality
# ---------------------------------------------------------------------------
with tab_quality:
    st.header("Water quality assessment")
    st.caption(
        "Laboratory results against WHO and national standards, with "
        "ionic balance checks and Piper/Stiff diagrams."
    )
    path = choose_input(
        "Laboratory results (standard template)", "wq", ["xlsx"],
        ["dr_timbo/dr_timbo_water_quality.xlsx"],
    )
    if path is not None:
        sample = read_quality_workbook(path)
        assessment = assess_sample(sample)
        st.session_state.wq_assessment = assessment
        show_flags(assessment.flags)
        st.subheader("Verdict")
        if assessment.health_exceedances:
            st.error(assessment.verdict)
        elif assessment.aesthetic_exceedances:
            st.warning(assessment.verdict)
        else:
            st.success(assessment.verdict)

        ph_result = sample.get("pH")
        if ph_result is not None and ph_result.value is not None:
            corrosion = handpump_corrosion_check(ph_result.value)
            if corrosion.passed is False:
                st.warning(f"Handpump corrosion risk ({corrosion.measured}): "
                           f"{corrosion.message}")

        rows = [
            {
                "Parameter": r.parameter,
                "Value": "< DL" if (r.below_detection and r.value is None) else r.value,
                "Unit": r.unit,
                "WHO health": r.who_health,
                "National": r.sl_standard,
                "Status": r.status,
            }
            for r in assessment.rows
        ]
        st.dataframe(rows, use_container_width=True)

        if assessment.ionic is not None:
            st.write(
                f"Ionic balance: cations {assessment.ionic.sum_cations_meq:.2f} meq/L, "
                f"anions {assessment.ionic.sum_anions_meq:.2f} meq/L, "
                f"error {assessment.ionic.error_percent:+.1f}%"
            )
            col1, col2 = st.columns(2)
            piper = workdir() / "piper.png"
            stiff = workdir() / "stiff.png"
            plot_piper([sample], path=piper)
            plot_stiff(sample, path=stiff)
            col1.image(str(piper))
            col2.image(str(stiff))

        if st.button("Build water quality report", key="build_wq_report"):
            report_path = build_quality_report(
                QualityReportInputs(assessment=assessment, figures_dir=workdir()),
                workdir() / "Water_Quality_Report.docx",
                app_config(),
            )
            offer_download(report_path, "Download water quality report (.docx)")

# ---------------------------------------------------------------------------
# Borehole design
# ---------------------------------------------------------------------------
with tab_design:
    st.header("Borehole design")
    st.caption(
        "A to-scale construction design from the drilling log, following "
        "the configured design rules."
    )
    path = choose_input(
        "Drilling log (standard template)", "log", ["xlsx"],
        ["dr_timbo/dr_timbo_drilling_log.xlsx"],
    )
    swl_input = st.number_input("Static water level (m)", min_value=0.0, value=0.0, step=0.1)
    if path is not None:
        log = read_drilling_workbook(path)
        show_flags(log.flags)
        design = design_borehole(
            log=log,
            static_water_level_m=swl_input or None,
            rules=CONFIG.design,
        )
        st.session_state.borehole_design = design
        st.session_state.drilling_log = log
        col_table, col_draw = st.columns([2, 3])
        with col_table:
            st.table(design.summary_rows())
            annulus = annular_space_check(
                design.borehole_diameter_in,
                design.casing_diameter_in * 25.4,
            )
            note = f"Annular space {annulus.measured}: {annulus.message}"
            if annulus.passed:
                st.caption(note)
            else:
                st.warning(note)
        with col_draw:
            drawing = workdir() / "design.png"
            draw_borehole_design(
                design, log, path=drawing,
                title=f"Borehole design - {log.site.community or 'site'}",
            )
            st.image(str(drawing))
            offer_download(drawing, "Download design drawing (.png)")
        st.info(
            "The Costing tab can price this design: casing, screen and "
            "gravel quantities carry over automatically."
        )

# ---------------------------------------------------------------------------
# Costing
# ---------------------------------------------------------------------------
with tab_cost:
    st.header("Borehole costing")
    st.caption(
        "Cost estimate and bill of quantities following the RWSN "
        "Cost-Effective Boreholes methodology: cost first, price "
        "separately, both stage and resource breakdowns."
    )

    design = st.session_state.get("borehole_design")
    use_design = False
    if design is not None:
        use_design = st.toggle(
            f"Use the design from the Borehole design tab "
            f"({design.total_depth_m:g} m, {design.casing_diameter_in:g} inch casing)",
            value=True,
            key="cost_use_design",
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        depth = st.number_input(
            "Total depth (m)", min_value=1.0,
            value=float(design.total_depth_m) if use_design else 60.0,
            step=1.0, key="cost_depth", disabled=use_design,
        )
    with col2:
        overburden = st.number_input(
            "Overburden thickness (m)", min_value=0.0, value=0.0, step=1.0,
            key="cost_overburden",
            help="Weathered zone drilled by rotary; 0 applies the rule of "
            "thumb (half the depth, at most 30 m).",
        )
    with col3:
        distance = st.number_input(
            "Mobilisation distance, one way (km)", min_value=0.0, value=100.0,
            step=10.0, key="cost_distance",
        )

    with st.expander("Adjust assumptions and percentages"):
        c1, c2, c3, c4 = st.columns(4)
        overheads_pct = c1.number_input("Overheads (%)", 0.0, 100.0, 15.0, 1.0,
                                        key="cost_overheads",
                                        help="RWSN: usually 10 to 20 percent of contract value.")
        margin_pct = c2.number_input("Margin (%)", 0.0, 100.0, 20.0, 1.0,
                                     key="cost_margin")
        contingency_pct = c3.number_input("Contingency (%)", 0.0, 100.0, 10.0, 1.0,
                                          key="cost_contingency")
        fx = c4.number_input("Exchange rate (SLE per USD)", 1.0, 1000.0, 23.0, 0.5,
                             key="cost_fx")
        c5, c6, c7, c8 = st.columns(4)
        handpumps = c5.number_input("Handpumps", 0, 5, 1, key="cost_handpumps")
        samples = c6.number_input("Water quality samples", 0, 10, 1, key="cost_samples")
        dev_hours = c7.number_input("Development (h)", 0.0, 200.0, 6.0, 1.0,
                                    key="cost_dev_hours")
        test_hours = c8.number_input("Test pumping (h)", 0.0, 200.0, 30.0, 1.0,
                                     key="cost_test_hours")
        c9, c10 = st.columns(2)
        vat_pct = c9.number_input(
            "VAT/GST (%) - optional", 0.0, 50.0, 0.0, 1.0, key="cost_vat",
            help="Optional; leave at 0 to keep tax out of the price. "
            "Sierra Leone GST is 15 percent where it applies.",
        )
        success_rate = c10.number_input(
            "Expected success rate (%)", 1.0, 100.0, 100.0, 5.0,
            key="cost_success",
            help="Under a no water no pay contract the successful wells "
            "must carry the failures: price / success rate.",
        )

    with st.expander("Unit rate catalogue (edit to match local prices)"):
        st.caption(
            "Bundled rates are indicative; confirm against local quotations. "
            "Rates are in USD."
        )
        base_rates = cached_rates()
        overrides = st.session_state.get("rates_overrides", {})
        rate_rows = [
            {
                "Code": r.code,
                "Stage": r.stage,
                "Item": r.item,
                "Unit": r.unit,
                "Rate (USD)": float(overrides.get(r.code, r.unit_cost_usd)),
            }
            for r in base_rates
        ]
        try:
            edited = st.data_editor(
                rate_rows,
                key="rates_editor",
                hide_index=True,
                disabled=["Code", "Stage", "Item", "Unit"],
                use_container_width=True,
            )
        except Exception:
            # very old or limited runtimes: show read-only rates instead
            st.dataframe(rate_rows, use_container_width=True)
            edited = rate_rows
        edited_by_code = {row["Code"]: row for row in edited}
        rates = [
            RateItem(
                code=r.code, stage=r.stage, category=r.category, item=r.item,
                unit=r.unit, quantity_basis=r.quantity_basis,
                unit_cost_usd=float(
                    edited_by_code.get(r.code, {}).get(
                        "Rate (USD)", overrides.get(r.code, r.unit_cost_usd)
                    )
                ),
                note=r.note,
            )
            for r in base_rates
        ]
        # remember the working rates so the project file carries them
        st.session_state.rates_overrides = {
            r.code: r.unit_cost_usd for r in rates
        }

    if st.button("Estimate cost", key="run_cost", type="primary"):
        if use_design and design is not None:
            inputs = inputs_from_design(
                design, mobilisation_distance_km=distance,
                overburden_m=overburden or None,
            )
        else:
            inputs = CostingInputs(
                total_depth_m=depth,
                overburden_m=overburden or None,
                mobilisation_distance_km=distance,
            )
        inputs.handpumps = int(handpumps)
        inputs.wq_samples = int(samples)
        inputs.development_hours = float(dev_hours)
        inputs.test_pumping_hours = float(test_hours)
        new_estimate = estimate_borehole_cost(
            inputs, rates,
            overheads_percent=overheads_pct,
            margin_percent=margin_pct,
            contingency_percent=contingency_pct,
            vat_percent=vat_pct,
            exchange_rate_sle_per_usd=fx,
        )
        st.session_state.cost_estimate = new_estimate
        # build the artifacts once per estimate, not on every rerun
        chart_path = workdir() / "cost_breakdown.png"
        plot_cost_breakdown(new_estimate, chart_path, app_config().style)
        boq_path = workdir() / "Bill_of_Quantities.xlsx"
        write_boq_workbook(new_estimate, boq_path)
        st.session_state.cost_artifacts = (chart_path, boq_path)

    estimate = st.session_state.get("cost_estimate")
    if estimate is not None:
        show_flags(estimate.flags)
        cols = st.columns(4)
        cols[0].metric("Direct works cost", f"${estimate.direct_cost_usd:,.0f}")
        cols[1].metric(
            "Total cost",
            f"${estimate.total_cost_usd:,.0f}",
            help="Direct works plus overheads - what the job costs the contractor.",
        )
        cols[2].metric("Cost per metre", f"${estimate.cost_per_meter_usd:,.0f}/m")
        cols[3].metric(
            "Contract price",
            f"${estimate.price_usd:,.0f}",
            help="Total cost plus margin; the contingency for budgeting sits on top.",
        )
        st.caption(
            f"Planning budget with contingency: "
            f"**${estimate.budget_usd:,.0f}** "
            f"(SLE {estimate.in_local(estimate.budget_usd):,.0f} at "
            f"{estimate.exchange_rate_sle_per_usd:g} SLE/USD)."
        )
        if st.session_state.get("cost_success", 100.0) < 100.0:
            rate = st.session_state["cost_success"]
            st.warning(
                f"No water no pay at {rate:g}% success: each successful "
                f"well must be priced at "
                f"${estimate.price_per_successful_well_usd(rate):,.0f} "
                "to carry the expected failures."
            )

        if "cost_artifacts" not in st.session_state:
            chart_path = workdir() / "cost_breakdown.png"
            plot_cost_breakdown(estimate, chart_path, app_config().style)
            boq_path = workdir() / "Bill_of_Quantities.xlsx"
            write_boq_workbook(estimate, boq_path)
            st.session_state.cost_artifacts = (chart_path, boq_path)
        chart_path, boq_path = st.session_state.cost_artifacts
        st.image(str(chart_path))

        col_boq, col_sum = st.columns([3, 2])
        with col_boq:
            st.subheader("Bill of quantities")
            st.dataframe(estimate.boq_rows(), use_container_width=True)
        with col_sum:
            st.subheader("Summary")
            st.table(
                [
                    {"Item": label, "USD": usd, "SLE": sle}
                    for label, usd, sle in estimate.summary_rows()
                ]
            )
        if estimate.assumptions:
            with st.expander("Assumptions applied"):
                for assumption in estimate.assumptions:
                    st.markdown(f"- {assumption}")

        st.caption(
            "The report cover uses the site details from the sidebar."
        )
        dl1, dl2 = st.columns(2)
        with dl1:
            offer_download(boq_path, "Download bill of quantities (.xlsx)")
        with dl2:
            if st.button("Build cost estimate report", key="build_cost_report"):
                report_path = build_cost_report(
                    CostReportInputs(
                        estimate=estimate,
                        site=site_from_state(),
                        figures_dir=workdir(),
                    ),
                    workdir() / "Cost_Estimate_Report.docx",
                    app_config(),
                )
                offer_download(report_path, "Download cost estimate report (.docx)")

    st.divider()
    with st.expander("📦 Programme: a package of boreholes"):
        st.caption(
            "Costs a multi-borehole contract with one mobilisation, moves "
            "between nearby sites, and dry attempts carried by the "
            "successful wells, following the procurement guide's contract "
            "packaging rules. Uses the single borehole inputs and rates "
            "above."
        )
        p1, p2, p3 = st.columns(3)
        n_wells = p1.number_input("Successful boreholes required", 1, 500, 10,
                                  key="cost_prog_n")
        inter_km = p2.number_input("Average distance between sites (km)",
                                   0.0, 200.0, 15.0, 1.0, key="cost_prog_km")
        prog_success = p3.number_input("Siting success rate (%)", 1.0, 100.0,
                                       80.0, 5.0, key="cost_prog_success")
        if st.button("Estimate programme", key="run_programme"):
            per_well = CostingInputs(
                total_depth_m=depth,
                overburden_m=overburden or None,
                mobilisation_distance_km=distance,
                handpumps=int(handpumps),
                wq_samples=int(samples),
                development_hours=float(dev_hours),
                test_pumping_hours=float(test_hours),
            )
            programme = estimate_programme_cost(
                per_well, int(n_wells), rates=rates,
                inter_site_distance_km=inter_km,
                success_rate_percent=prog_success,
                overheads_percent=overheads_pct,
                margin_percent=margin_pct,
                contingency_percent=contingency_pct,
                vat_percent=vat_pct,
                exchange_rate_sle_per_usd=fx,
            )
            gantt_path = workdir() / "programme_gantt.png"
            plot_programme_gantt(programme, gantt_path, app_config().style)
            st.session_state.programme_estimate = (programme, gantt_path)
        if "programme_estimate" in st.session_state:
            programme, gantt_path = st.session_state.programme_estimate
            g1, g2, g3 = st.columns(3)
            g1.metric("Attempts planned", programme.n_attempted)
            g2.metric("Contract price",
                      f"${programme.price_with_vat_usd:,.0f}")
            g3.metric("Per successful borehole",
                      f"${programme.price_per_successful_well_usd:,.0f}")
            st.table(
                [
                    {"Item": label, "USD": usd, "SLE": sle}
                    for label, usd, sle in programme.summary_rows()
                ]
            )
            st.image(str(gantt_path))
            with st.expander("Programme assumptions"):
                for assumption in programme.assumptions:
                    st.markdown(f"- {assumption}")

# ---------------------------------------------------------------------------
# Supervision
# ---------------------------------------------------------------------------
with tab_supervision:
    st.header("Drilling supervision")
    st.caption(
        "Stage by stage checklists from the RWSN/UNICEF supervision "
        "guidance, plus the numeric acceptance checks a supervisor "
        "needs on site. Critical items stop acceptance when they fail."
    )

    checklist_items = cached_checklists()

    def _responses() -> dict[str, ChecklistResponse]:
        responses: dict[str, ChecklistResponse] = {}
        for item in checklist_items:
            status = st.session_state.get(f"chk_{item.item_id}", "Pending")
            remark = st.session_state.get(f"rmk_{item.item_id}", "")
            responses[item.item_id] = ChecklistResponse(
                item.item_id,
                {"Pending": "pending", "Yes": "yes", "No": "no", "N/A": "na"}[status],
                remark,
            )
        return responses

    responses = _responses()
    assessment = evaluate_checklist(checklist_items, responses)
    top1, top2, top3 = st.columns([1, 1, 2])
    top1.metric("Items answered", f"{assessment.answered}/{assessment.total}")
    top2.metric("Critical failures", assessment.critical_failures)
    with top3:
        st.progress(assessment.percent / 100.0)
        if assessment.critical_failures:
            st.error(assessment.verdict)
        else:
            st.info(assessment.verdict)

    stage_keys: list[str] = []
    for item in checklist_items:
        if item.checklist not in stage_keys:
            stage_keys.append(item.checklist)
    progress_by_stage = {s.stage: s for s in assessment.stages}
    stage_pick = st.selectbox(
        "Supervision stage",
        stage_keys,
        format_func=lambda k: (
            f"{stage_title(k)}  "
            f"({progress_by_stage[k].answered}/{progress_by_stage[k].total})"
        ),
        key="sup_stage",
    )

    current_section = None
    for item in [i for i in checklist_items if i.checklist == stage_pick]:
        if item.section != current_section:
            current_section = item.section
            st.markdown(f"**{current_section}**")
        with st.container(border=True):
            label = item.text + (" 🔴 *critical*" if item.critical else "")
            st.markdown(label)
            if item.guidance:
                st.caption(item.guidance)
            st.radio(
                "Status",
                ["Pending", "Yes", "No", "N/A"],
                horizontal=True,
                key=f"chk_{item.item_id}",
                label_visibility="collapsed",
            )
            if st.session_state.get(f"chk_{item.item_id}") == "No":
                st.text_input(
                    "Remark / action", key=f"rmk_{item.item_id}",
                    placeholder="What failed and what happens next",
                )

    st.divider()
    with st.expander("🧮 Field acceptance checks"):
        fc1, fc2 = st.columns(2)
        with fc1:
            st.markdown("**Chlorine disinfection dose (WHO 20 mg/L)**")
            d1, d2 = st.columns(2)
            water_col = d1.number_input("Water column (m)", 0.0, 200.0, 40.0, 1.0,
                                        key="fx_watercol")
            casing_id = d2.number_input("Casing ID (mm)", 50.0, 400.0, 103.0, 1.0,
                                        key="fx_casingid")
            st.caption(disinfection_dose(water_col, casing_id).summary())

            st.markdown("**Verticality (plumb test)**")
            v1, v2 = st.columns(2)
            dev = v1.number_input("Deviation (mm)", 0.0, 1000.0, 50.0, 5.0, key="fx_dev")
            vdepth = v2.number_input("Depth (m)", 1.0, 300.0, 60.0, 1.0, key="fx_vdepth")
            v = verticality_check(dev, vdepth, casing_id)
            (st.success if v.passed else st.error)(f"{v.measured} vs {v.limit}: {v.message}")

        with fc2:
            st.markdown("**Sand content (three 20 L samples)**")
            s1, s2, s3 = st.columns(3)
            sand = [
                s1.number_input("S1 (cm3)", 0.0, 10.0, 0.1, 0.05, key="fx_sand1"),
                s2.number_input("S2 (cm3)", 0.0, 10.0, 0.1, 0.05, key="fx_sand2"),
                s3.number_input("S3 (cm3)", 0.0, 10.0, 0.1, 0.05, key="fx_sand3"),
            ]
            sc = sand_content_check(sand)
            (st.success if sc.passed else st.error)(f"{sc.measured}: {sc.message}")

            st.markdown("**Specific capacity (handpump rule)**")
            q1, q2 = st.columns(2)
            q_test = q1.number_input("Discharge (m3/h)", 0.0, 100.0, 3.0, 0.1, key="fx_q")
            dd = q2.number_input("Drawdown (m)", 0.0, 100.0, 2.0, 0.1, key="fx_dd")
            spc = specific_capacity_check(q_test, dd)
            if spc.passed is None:
                st.info(spc.message)
            else:
                (st.success if spc.passed else st.warning)(f"{spc.measured}: {spc.message}")

            st.markdown("**Drilled metres reconciliation**")
            r1, r2 = st.columns(2)
            logged = r1.number_input("Metres in signed daily logs", 0.0,
                                     2000.0, 60.0, 1.0, key="fx_logged")
            claimed = r2.number_input("Metres invoiced", 0.0, 2000.0, 60.0,
                                      1.0, key="fx_claimed")
            recon = metres_reconciliation_check(logged, claimed)
            (st.success if recon.passed else st.error)(recon.message)
            st.caption(
                "The daily report template for the driller is in the "
                "Templates tab."
            )

    with st.expander("📏 Minimum separation distances"):
        st.table(
            [
                {
                    "Structure": d.structure,
                    "Minimum distance (m)": f"{d.min_distance_m:g}",
                    "Note": d.note,
                }
                for d in cached_separation_distances()
            ]
        )
        st.caption("Adapted from FGN/NWRI 2010 via the RWSN supervision guide.")

    with st.expander("📝 Checklist record and sign off"):
        st.caption(
            "Community, client, contractor and supervisor come from the "
            "site details in the sidebar."
        )
        st.text_input("Community representative (sign off)",
                      key="meta_community_rep")
        if st.button("Build supervision checklist report", key="build_sup_report"):
            site = site_from_state()
            report_path = build_supervision_report(
                SupervisionReportInputs(
                    site=site,
                    items=checklist_items,
                    responses=responses,
                    assessment=assessment,
                    supervisor=site.supervisor,
                    driller=site.contractor,
                    community_rep=st.session_state.get("meta_community_rep", ""),
                ),
                workdir() / "Supervision_Checklist_Report.docx",
                app_config(),
            )
            offer_download(report_path, "Download supervision report (.docx)")

# ---------------------------------------------------------------------------
# Handover
# ---------------------------------------------------------------------------
with tab_handover:
    st.header("Project handover report")
    st.caption(
        "The closing deliverable for the client and the community. Answer "
        "the questions below; results already produced in the other tabs "
        "(design, pumping test, water quality) attach automatically."
    )

    design = st.session_state.get("borehole_design")
    log = st.session_state.get("drilling_log")
    pumping = st.session_state.get("pump_analysis")
    quality = st.session_state.get("wq_assessment")
    a1, a2, a3 = st.columns(3)
    a1.metric("Borehole design", "attached" if design is not None else "not yet",
              help="Produce it in the Borehole design tab and it attaches here.")
    a2.metric("Pumping test", "attached" if pumping is not None else "not yet",
              help="Analyse a test in the Pumping test tab.")
    a3.metric("Water quality", "attached" if quality is not None else "not yet",
              help="Assess a sample in the Water quality tab.")
    st.caption(
        "Community, district, client, contractor and supervisor come from "
        "the site details in the sidebar."
    )

    st.subheader("1. The water point")
    h1, h2 = st.columns(2)
    pump_type = h1.text_input(
        "Pump installed (type and model)", key="ho_pump_type",
        placeholder="e.g. India Mark II handpump",
    )
    tariff = h2.text_input(
        "Tariff arrangement agreed with the community", key="ho_tariff",
        placeholder="e.g. 5 SLE per household per month",
    )

    st.subheader("2. WASH committee")
    st.caption("Who is responsible for the water point? Add one row per member.")
    committee_rows = st.data_editor(
        st.session_state.get(
            "ho_committee_rows",
            [
                {"Role": "Chair", "Name": "", "Phone": ""},
                {"Role": "Secretary", "Name": "", "Phone": ""},
                {"Role": "Treasurer", "Name": "", "Phone": ""},
                {"Role": "Caretaker", "Name": "", "Phone": ""},
            ],
        ),
        key="ho_committee",
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
    )
    committee_notes = st.text_input(
        "Notes on the committee (training received, bank account, ...)",
        key="ho_committee_notes",
    )

    st.subheader("3. Works and sign off")
    works_text = st.text_area(
        "Works completed (one per line; leave empty for the standard list "
        "built from the attached results)",
        key="ho_works",
        height=100,
    )
    recs_text = st.text_area(
        "Extra recommendations (one per line, optional)",
        key="ho_recs",
        height=80,
    )
    s1, s2, s3 = st.columns(3)
    contractor_rep = s1.text_input("Contractor representative", key="ho_contractor_rep")
    client_rep = s2.text_input("Client representative", key="ho_client_rep")
    community_rep = s3.text_input("Community representative", key="ho_community_rep")

    if st.button("Build handover report", key="build_handover", type="primary"):
        committee = [
            CommitteeMember(
                role=str(row.get("Role") or "").strip(),
                name=str(row.get("Name") or "").strip(),
                phone=str(row.get("Phone") or "").strip(),
            )
            for row in committee_rows
            if str(row.get("Role") or "").strip() or str(row.get("Name") or "").strip()
        ]
        report_path = build_handover_report(
            HandoverReportInputs(
                site=site_from_state(),
                log=log,
                design=design,
                pumping=pumping,
                quality=quality,
                figures_dir=workdir(),
                works_completed=[w.strip() for w in works_text.splitlines() if w.strip()],
                committee=committee,
                committee_notes=committee_notes,
                tariff_note=tariff,
                pump_type=pump_type,
                extra_recommendations=[r.strip() for r in recs_text.splitlines() if r.strip()],
                contractor_rep=contractor_rep,
                client_rep=client_rep,
                community_rep=community_rep,
            ),
            workdir() / "Handover_Report.docx",
            app_config(),
        )
        offer_download(report_path, "Download handover report (.docx)")

# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------
with tab_maps:
    st.header("Location, geology and aquifer maps")
    st.caption(
        "Report-ready context maps built from real, freely licensed "
        "datasets: district boundaries from geoBoundaries (CC BY 4.0), "
        "geology from the USGS Geologic Map of Africa (public domain) and "
        "aquifer type and productivity from the BGS Africa Groundwater "
        "Atlas (CC BY-SA 4.0). These maps also embed automatically into "
        "the geophysical survey and handover reports when the site has "
        "coordinates."
    )
    site = site_from_state()
    if site.latlon is None:
        st.info(
            "Enter the GPS coordinates (UTM East, North and zone) in the "
            "sidebar site details to place the site on the maps; without "
            "them the national maps are drawn unmarked."
        )
    else:
        lat, lon = site.latlon
        st.caption(f"Site at {lat:.5f} N, {abs(lon):.5f} W "
                   f"({site.community or 'unnamed site'}).")
    radius = st.slider(
        "Local map window (km around the site)", 10, 150, 40, 5,
        key="map_radius",
        help="Used for the local geological and aquifer maps when "
        "coordinates are entered.",
    )
    if st.button("Generate maps", key="run_maps", type="primary"):
        marked = site if site.latlon is not None else None
        style = app_config().style
        admin_path = workdir() / "admin_map.png"
        plot_admin_map(marked, path=admin_path, style=style)
        paths = [admin_path]
        if marked is not None:
            hydro_path = workdir() / "hydro_local_map.png"
            plot_hydrogeology_map(marked, path=hydro_path, style=style,
                                  radius_km=float(radius))
            geo_path = workdir() / "geology_local_map.png"
            plot_geological_map(marked, path=geo_path, style=style,
                                radius_km=float(radius))
            paths += [hydro_path, geo_path]
        else:
            hydro_path = workdir() / "hydro_map.png"
            plot_hydrogeology_map(None, path=hydro_path, style=style)
            geo_path = workdir() / "geology_map.png"
            plot_geological_map(None, path=geo_path, style=style)
            paths += [hydro_path, geo_path]
        st.session_state.map_paths = paths
    for map_path in st.session_state.get("map_paths", []):
        st.image(str(map_path))
        offer_download(map_path, f"Download {map_path.name}")

# ---------------------------------------------------------------------------
# Scanned sheets
# ---------------------------------------------------------------------------
with tab_extract:
    st.header("Scanned field sheet extraction")
    st.write(
        "Upload a scanned sheet or PDF. Text PDFs are extracted directly; "
        "photos and image scans use the AI assisted extractor when an "
        "Anthropic API key is configured. Uncertain values are highlighted "
        "in the review workbook, never silently accepted."
    )
    import importlib.util

    # probe availability without importing (imports happen on Extract click)
    extraction_available = importlib.util.find_spec("pdfplumber") is not None
    if not extraction_available:
        st.info(
            "Extraction is not available in this installation. It needs the "
            "optional dependencies: pip install groundwater-toolkit[extract] "
            "for text PDFs and [ai] for photographed sheets."
        )
    upload = st.file_uploader("Scan or PDF", type=["pdf", "png", "jpg", "jpeg"], key="scan")
    use_ai = st.checkbox("Use AI assisted extraction (needs ANTHROPIC_API_KEY)")
    if not IN_BROWSER:
        st.caption(
            "On Streamlit Community Cloud: open the app's Settings, choose "
            "Secrets and add a line ANTHROPIC_API_KEY = \"sk-ant-...\" to "
            "enable the AI assisted extraction."
        )
    if upload is not None and st.button("Extract", key="run_extract"):
        path = save_upload(upload)
        try:
            if use_ai or path.suffix.lower() != ".pdf":
                from groundwater.extraction import ClaudeExtractor

                document = ClaudeExtractor().extract(path)
            else:
                from groundwater.extraction import extract_pdf_text

                document = extract_pdf_text(path)
        except Exception as exc:  # surfaced to the operator
            st.error(str(exc))
        else:
            st.success(
                f"Extracted a {document.document_kind} sheet: "
                f"{len(document.header)} header fields, {len(document.tables)} table(s), "
                f"{len(document.review_items)} item(s) to review."
            )
            from groundwater.extraction import write_review_workbook

            review_path = workdir() / (path.stem + "_review.xlsx")
            write_review_workbook(document, review_path)
            offer_download(review_path, "Download review workbook (.xlsx)")
            if document.document_kind == "ves" and document.tables:
                from groundwater.extraction import fill_ves_template

                template_path = workdir() / (path.stem + "_ves_template.xlsx")
                fill_ves_template(document, template_path)
                offer_download(template_path, "Download filled VES template (.xlsx)")

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
with tab_templates:
    st.header("Blank field data templates")
    st.write("Download the standard templates for the field team.")
    template_dir = workdir() / "templates"
    if st.button("Generate templates", key="gen_templates"):
        for template in write_all_templates(template_dir):
            offer_download(template, f"Download {template.name}")

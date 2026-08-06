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

import html as _html
import sys
import tempfile
from pathlib import Path

# Always import the groundwater package from the repository checkout
# this app ships with, not from a previously installed copy. Streamlit
# Community Cloud pulls new source on every push but only reinstalls
# packages when requirements.txt changes, so without this the app file
# can be newer than the installed package and imports break.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
    for _mod in [m for m in list(sys.modules) if m.split(".")[0] == "groundwater"]:
        del sys.modules[_mod]

import streamlit as st
import streamlit.components.v1 as components
import yaml

import groundwater
from datetime import date

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
from groundwater.geo import geographic_to_utm, parse_latlon, utm_to_geographic
from groundwater.mapping import (
    chiefdom_of,
    district_of,
    plot_admin_map,
    plot_coverage_choropleth,
    plot_geological_map,
    plot_hydrogeology_map,
    plot_portfolio_map,
    suitability_map,
)
from groundwater.planning import (
    AGEING_YEARS,
    CENSUS_YEAR,
    DEFAULT_GROWTH_RATE,
    planning_rows,
    planning_stats,
)
from groundwater.coverage import (
    group_points_by_chiefdom,
    group_points_by_district,
    POPULATION_CREDIT,
    chiefdom_coverage_rows,
    chiefdom_population,
    count_points_by_chiefdom,
    count_points_by_district,
    coverage_rows,
    coverage_stats,
    choropleth_values,
    expand_district_values,
    load_chiefdom_district,
    load_chiefdom_polys,
    load_district_population,
)
from groundwater.readiness import assess_readiness
from groundwater.procurement import (
    Contract,
    ContractLine,
    Measurement,
    Variation,
    certify,
    contract_from_estimate,
    contract_summary,
)
from groundwater.reporting.procurement import (
    PaymentCertificateInputs,
    build_payment_certificate,
)
from groundwater.seasonal import MONTH_NAMES, month_of, seasonal_yield
from groundwater.registry import (
    EVENT_KINDS,
    AssetEvent,
    asset_from_dict,
    asset_from_project,
    asset_state,
    merge_events,
    parse_asset_id,
    registry_rows,
    registry_stats,
    validate_asset_id,
)
from groundwater.reporting.registry import (
    AssetReportInputs,
    build_asset_placard,
    build_asset_record,
)
from groundwater.portfolio import (
    STATUS_LABELS,
    VERDICT_SCHEMA,
    classify_status,
    portfolio_points,
    portfolio_rows,
    portfolio_stats,
    site_detail,
    site_label,
    site_one_pager,
)
from groundwater.waterpoints import (
    ASSESS_REHAB,
    DEFAULT_SEARCH_RADIUS_M,
    VERIFY_NEED,
    WPDX_CREDIT,
    WaterPointFetchError,
    fetch_water_points,
    functionality_summary,
    parse_wpdx_csv,
    parse_wpdx_records,
    rehab_vs_drill,
    water_points_near,
)
from groundwater.siting import assess_siting, suitability_map_points
from groundwater.models import SiteMetadata
from groundwater.project_io import (
    committee_records,
    deserialize_project,
    serialize_project,
    stale_on_load,
)
from groundwater.recompute import recompute_results
from groundwater.quality import (
    PROVISIONAL_NATIONAL_NOTE,
    STATUS_LABELS as WQ_STATUS_LABELS,
    VERDICT_LONG,
    VERDICT_SHORT,
    assess_sample,
    plot_piper,
    plot_stiff,
    provisional_national_parameters,
)

#: Chip colour per verdict state. Both failures are red - neither supply may
#: be accepted - and the label carries the difference between them. An
#: unproven result is blue: it is a question, not a finding.
_VERDICT_CHIP = {
    "health_fail": "gw-chip-red",
    "national_fail": "gw-chip-red",
    "indeterminate": "gw-chip-blue",
    "aesthetic": "gw-chip-amber",
    "pass": "gw-chip-green",
}
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
from groundwater.ves.interpret import (
    drilling_preference_table,
    rank_interpretations,
)
from groundwater.ves.plots import plot_sounding_curve

# The Depth Spine workspace renders two ways. The custom component is
# interactive but needs a server to serve its frontend, so the in-browser
# (WebAssembly) demo gets the static build through st.components.v1.html
# instead - same workspace, screens edited with ordinary inputs. Import
# defensively so a deployment with neither still runs every other page.
try:
    from groundwater.depth_spine import (
        build_view as build_spine_view,
        component_available,
        depth_spine,
        render_static,
        static_build_available,
    )
    from groundwater.depth_spine.view import SpineInputs

    SPINE_ERROR = ""
except Exception as _spine_exc:  # pragma: no cover - depends on the deployment
    build_spine_view = depth_spine = SpineInputs = None
    component_available = static_build_available = lambda: False
    render_static = None
    SPINE_ERROR = str(_spine_exc)

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

# Design language (from the "Groundwater Toolkit Redesign" study, direction
# 1b "Project Workspace"): warm paper canvas, white result cards, deep
# green-teal accents, Space Grotesk display over IBM Plex Sans/Mono.
_INK = "#152220"
_GREEN = "#2B6850"        # oklch(0.47 0.075 165)
_GREEN_DARK = "#184735"   # oklch(0.36 0.06 165)
_GREEN_MID = "#1B5A43"    # oklch(0.42 0.075 165)
_SUCCESS = "#5BBE62"      # oklch(0.72 0.16 145)
_SUCCESS_TEXT = "#006925"
_AMBER = "#E48E26"
_AMBER_TEXT = "#994A00"
_FIELD_RED = "#B14E49"    # measured field data accent

st.markdown(
    """
    <style>
      /* No webfont @import here. A CSS @import is render-blocking, so on a
         slow or captive-portal link the whole app waited on
         fonts.googleapis.com - and everything else in the toolkit works
         offline. The stacks below fall back to the platform UI font. */

      html, body, [data-testid="stAppViewContainer"], .stMarkdown,
      button, input, textarea, select {
        font-family: 'IBM Plex Sans', system-ui, sans-serif;
      }
      h1, h2, h3, h4,
      [data-testid="stMetricValue"] {
        font-family: 'Space Grotesk', 'IBM Plex Sans', sans-serif !important;
        letter-spacing: -0.01em;
        color: #152220;
      }
      code, pre, kbd { font-family: 'IBM Plex Mono', monospace; }

      .block-container { padding-top: 2.4rem; }
      [data-testid="stAppViewContainer"] h1 {
        font-size: 1.7rem; font-weight: 600; margin-bottom: 0.1rem;
      }
      [data-testid="stAppViewContainer"] h2 {
        font-size: 1.3rem; font-weight: 600;
      }
      [data-testid="stAppViewContainer"] h3 {
        font-size: 1.05rem; font-weight: 600;
      }

      /* Result cards: white on the warm paper canvas */
      div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid rgba(0, 0, 0, 0.09);
        border-radius: 11px;
        padding: 0.65rem 0.9rem;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
      }
      div[data-testid="stMetric"] label p {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.66rem; font-weight: 600;
        text-transform: uppercase; letter-spacing: 0.09em;
        color: rgba(0, 0, 0, 0.45);
      }
      div[data-testid="stSidebarUserContent"] .stCaption p { line-height: 1.35; }

      /* Sidebar: brand, active-project card and grouped navigation */
      section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"] {
        padding-top: 1.1rem;
      }
      /* Group label above each navigation radio */
      section[data-testid="stSidebar"] .stRadio
        [data-testid="stWidgetLabel"] p {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.62rem; font-weight: 600;
        text-transform: uppercase; letter-spacing: 0.11em;
        color: rgba(0, 0, 0, 0.38);
      }
      /* Navigation items. Two selector sets: react-aria markup
         (stRadioOption, Streamlit >= 1.59) and baseweb markup
         (label[data-baseweb=radio], Streamlit <= 1.58 / stlite).
         The baseweb active-state rules use :has() and are kept in
         separate rules so a browser without :has() only loses that
         branch, not the react-aria one. */
      section[data-testid="stSidebar"] label[data-testid="stRadioOption"],
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"] {
        display: flex; align-items: center;
        width: 100%; margin: 0 0 2px; padding: 6px 10px;
        border-radius: 7px; cursor: pointer;
      }
      section[data-testid="stSidebar"] label[data-testid="stRadioOption"]
        > div > div > div:first-child,
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"] > div:first-of-type {
        width: 5px; height: 5px; min-width: 5px; min-height: 5px;
        margin-right: 9px; border-width: 0; border-radius: 50%;
        background: rgba(0, 0, 0, 0.18);
      }
      section[data-testid="stSidebar"] label[data-testid="stRadioOption"]
        > div > div > div:first-child > div,
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"] > div:first-of-type > div {
        display: none;
      }
      section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p,
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"] div[data-testid="stMarkdownContainer"] p {
        font-size: 0.83rem; font-weight: 500; color: rgba(0, 0, 0, 0.66);
      }
      section[data-testid="stSidebar"]
        label[data-testid="stRadioOption"][data-selected="true"] {
        background: rgba(43, 104, 80, 0.13);
      }
      section[data-testid="stSidebar"]
        label[data-testid="stRadioOption"][data-selected="true"]
        > div > div > div:first-child {
        background: #2B6850;
      }
      section[data-testid="stSidebar"]
        label[data-testid="stRadioOption"][data-selected="true"] p {
        font-weight: 600; color: #184735;
      }
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"]:has(input:checked) {
        background: rgba(43, 104, 80, 0.13);
      }
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"]:has(input:checked) > div:first-of-type {
        background: #2B6850;
      }
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"]:has(input:checked)
        div[data-testid="stMarkdownContainer"] p {
        font-weight: 600; color: #184735;
      }
      section[data-testid="stSidebar"] .stRadio { margin-bottom: 0.35rem; }

      /* Shared design pieces (overview dashboard, callouts, chips) */
      .gw-brand { display: flex; align-items: center; gap: 10px; }
      .gw-brand-mark {
        width: 28px; height: 28px; border-radius: 7px; background: #2B6850;
        display: flex; align-items: center; justify-content: center;
        color: #fff; font: 700 14px 'Space Grotesk', sans-serif;
      }
      .gw-brand-name {
        font: 600 14px 'Space Grotesk', sans-serif; color: #152220;
        line-height: 1.15;
      }
      .gw-brand-sub {
        font: 400 9.5px 'IBM Plex Mono', monospace;
        color: rgba(0, 0, 0, 0.45); letter-spacing: 0.05em;
      }
      .gw-project-card {
        background: #fff; border: 1px solid rgba(0, 0, 0, 0.1);
        border-radius: 9px; padding: 9px 11px; margin: 4px 0 6px;
      }
      .gw-cap {
        font: 600 10px 'IBM Plex Mono', monospace;
        text-transform: uppercase; letter-spacing: 0.09em;
        color: rgba(0, 0, 0, 0.45);
      }
      .gw-chip {
        display: inline-block; font: 600 10px 'IBM Plex Mono', monospace;
        text-transform: uppercase; letter-spacing: 0.06em;
        border-radius: 20px; padding: 3px 10px; vertical-align: middle;
      }
      .gw-chip-green { color: #184735; background: rgba(43, 104, 80, 0.14); }
      .gw-chip-amber { color: #994A00; background: rgba(228, 142, 38, 0.18); }
      .gw-chip-red { color: #8C2F2B; background: rgba(177, 78, 73, 0.15); }
      .gw-chip-grey { color: rgba(0, 0, 0, 0.55); background: rgba(0, 0, 0, 0.07); }
      .gw-chip-blue { color: #1F5C8B; background: rgba(31, 92, 139, 0.14); }
      .gw-card {
        background: #fff; border: 1px solid rgba(0, 0, 0, 0.09);
        border-radius: 11px; padding: 14px 15px;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
        margin-bottom: 14px;
      }
      .gw-card .gw-cap { display: block; margin-bottom: 8px; }
      .gw-big {
        font: 600 26px 'Space Grotesk', sans-serif; color: #152220;
        line-height: 1.1;
      }
      .gw-big small {
        font: 500 12px 'IBM Plex Mono', monospace; color: rgba(0, 0, 0, 0.5);
      }
      .gw-row {
        display: flex; justify-content: space-between; gap: 10px;
        font-size: 0.78rem; color: rgba(0, 0, 0, 0.65); padding: 2.5px 0;
      }
      .gw-row b { color: #152220; font-weight: 500;
        font-family: 'IBM Plex Mono', monospace; }
      .gw-callout {
        background: #2B6850; border-radius: 11px; padding: 14px 16px;
        color: #fff; margin: 4px 0 12px;
      }
      .gw-callout .gw-cap { color: rgba(255, 255, 255, 0.7); }
      .gw-callout .gw-big { color: #fff; }
      .gw-callout .gw-big small { color: rgba(255, 255, 255, 0.65); }
      .gw-callout p {
        margin: 4px 0 0; font-size: 0.75rem; line-height: 1.4;
        color: rgba(255, 255, 255, 0.82);
      }
      .gw-steps { display: flex; align-items: flex-start; margin: 6px 0 4px; }
      .gw-step { display: flex; flex-direction: column; align-items: center;
        gap: 5px; flex: none; min-width: 58px; }
      .gw-step-dot {
        width: 26px; height: 26px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font: 700 12px sans-serif;
      }
      .gw-step-done .gw-step-dot { background: #2B6850; color: #fff; }
      .gw-step-todo .gw-step-dot {
        background: #fff; border: 2px dashed rgba(43, 104, 80, 0.6);
        color: #2B6850; font-size: 11px;
      }
      .gw-step-label { font-size: 0.68rem; font-weight: 600; color: #152220; }
      .gw-step-todo .gw-step-label { color: rgba(0, 0, 0, 0.5); }
      .gw-step-line { flex: 1; height: 2px; background: #2B6850;
        margin: 12px 6px 0; }
      .gw-step-line-todo {
        background: repeating-linear-gradient(90deg, rgba(0, 0, 0, 0.2) 0 4px,
          transparent 4px 8px);
      }
      .gw-bar { display: flex; height: 9px; border-radius: 5px;
        overflow: hidden; margin: 8px 0; }
      .gw-legend { display: flex; flex-wrap: wrap; gap: 3px 12px;
        font-size: 0.66rem; color: rgba(0, 0, 0, 0.6); }
      .gw-legend i { display: inline-block; width: 8px; height: 8px;
        border-radius: 2px; margin-right: 4px; }
      .gw-report-row {
        display: flex; justify-content: space-between; align-items: center;
        font-size: 0.78rem; color: rgba(0, 0, 0, 0.72); padding: 4px 0;
        border-bottom: 1px solid rgba(0, 0, 0, 0.05);
      }
      .gw-report-row:last-child { border-bottom: none; }
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


@st.cache_data
def cov_population():
    return load_district_population()


@st.cache_data
def cov_crosswalk():
    return load_chiefdom_district()


@st.cache_data
def cov_chiefdom_population():
    """(population per chiefdom polygon, census members) from the 2015 census."""
    return chiefdom_population()


@st.cache_resource
def cov_polys():
    """Chiefdom polygons for coverage point-in-polygon (numpy-heavy, cached by
    reference)."""
    return load_chiefdom_polys()


@st.cache_data
def cached_districts():
    """(provinces, [(district, province), ...]) from the bundled table."""
    import csv as _csv
    from importlib import resources

    text = (
        resources.files("groundwater") / "data" / "sl_districts.csv"
    ).read_text(encoding="utf-8")
    rows = list(_csv.DictReader(text.splitlines()))
    provinces: list[str] = []
    for row in rows:
        if row["province"] not in provinces:
            provinces.append(row["province"])
    return provinces, [(row["district"], row["province"]) for row in rows]


def workdir() -> Path:
    if "workdir" not in st.session_state:
        st.session_state.workdir = Path(tempfile.mkdtemp(prefix="gw_"))
    return st.session_state.workdir


def save_upload(uploaded) -> Path:
    # Use only the basename of the browser-supplied name so a crafted filename
    # (e.g. "../../x") cannot write outside the per-session working directory.
    safe_name = Path(uploaded.name).name or "upload"
    path = workdir() / safe_name
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
        # remember the raw upload so it can be saved with the project and the
        # analysis recomputed on load without re-uploading
        st.session_state[f"src_{key}"] = {
            "name": upload.name, "bytes": bytes(upload.getvalue())
        }
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
                st.session_state[f"src_{key}"] = {"sample": pick}
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


def offer_download(path: Path, label: str, keep: bool = True) -> None:
    """Download button for a produced file, and remember it as a deliverable.

    Build buttons are true for exactly one rerun, so a report's download
    button used to vanish the moment the user touched anything else and the
    report had to be rebuilt. Remembering it keeps it available from the
    Deliverables panel for the rest of the session.
    """
    if keep:
        st.session_state.setdefault("artifacts", {})[label] = str(path)
    with open(path, "rb") as fh:
        st.download_button(label, fh.read(), file_name=path.name,
                           key=f"dl_{_html.escape(label)}_{path.name}")


def _deliverables() -> list[tuple[str, Path]]:
    """Everything built this session that still exists on disk."""
    out = []
    for label, raw in (st.session_state.get("artifacts") or {}).items():
        path = Path(raw)
        if path.exists():
            out.append((label, path))
    return out


def _working(message: str):
    """Status block for a slow operation, so the app never looks frozen."""
    return st.status(message, expanded=False)


def parse_upload(reader, path: Path):
    """Run a parser on an uploaded file, surfacing failures as errors.

    A malformed or mislabelled workbook should show a readable message
    instead of crashing the page.
    """
    try:
        return reader(path)
    except Exception as exc:
        st.error(
            f"Could not read {path.name}: {exc}. Check that the file "
            "follows the standard template (Templates page)."
        )
        return None


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
        utm_zone=int(str(get("meta_zone", "29N")).rstrip("N") or "29"),
    )


def _project_summary() -> dict:
    """Headline summary of the current project, saved for the portfolio view."""
    site = site_from_state()
    summary = {
        "community": site.community, "district": site.district,
        "chiefdom": site.chiefdom, "easting": site.easting,
        "northing": site.northing, "utm_zone": site.utm_zone,
    }
    log = st.session_state.get("drilling_log")
    if log is not None:
        if log.status:
            summary["status"] = log.status
        if log.total_depth_m:
            summary["total_depth_m"] = log.total_depth_m
    analysis = st.session_state.get("pump_analysis")
    yr = analysis.yield_recommendation if analysis is not None else None
    if yr is not None and yr.safe_yield_m3_per_h:
        summary["safe_yield_m3_per_h"] = yr.safe_yield_m3_per_h
    wq = st.session_state.get("wq_assessment")
    if wq is not None:
        # The full five-state verdict. The old three states folded a national
        # standard failure into "aesthetic" and had no way to say "we cannot
        # tell", so a breached or unevaluable supply read as merely a matter
        # of taste. The schema marker lets a reader tell a new file from an
        # old one and translate the old vocabulary safely.
        summary["water_verdict"] = wq.verdict_state
        summary["verdict_schema"] = VERDICT_SCHEMA
    cost = st.session_state.get("cost_estimate")
    if cost is not None:
        summary["cost_per_meter_usd"] = cost.cost_per_meter_usd
    if "ves_results" in st.session_state and "status" not in summary:
        summary["status"] = "sited"
    return {k: v for k, v in summary.items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Certification gate
# ---------------------------------------------------------------------------

def _project_state() -> dict:
    """The session, keyed as groundwater.readiness expects it."""
    return {
        "site": site_from_state(),
        "drilling_log": st.session_state.get("drilling_log"),
        "pump_analysis": st.session_state.get("pump_analysis"),
        "wq_assessment": st.session_state.get("wq_assessment"),
        "borehole_design": st.session_state.get("borehole_design"),
        "cost_estimate": st.session_state.get("cost_estimate"),
    }


def _overrides_for(report: str) -> dict:
    """Overrides the analyst recorded for this report, from session state."""
    return st.session_state.get(f"_override_{report}") or {}


def report_gate(report: str):
    """Show what this report can and cannot stand behind, and return it.

    Deliberately never disables the button. An analyst who needs an interim
    document will produce one either way; the useful thing is that the
    document says what it rests on, so this renders the outstanding items,
    offers a recorded override, and hands the result to the report builder
    to stamp on its own cover.
    """
    readiness = assess_readiness(_project_state(), report, _overrides_for(report))
    if readiness.state == "ready":
        st.success("Ready to certify: " + readiness.summary)
    else:
        renderer = st.warning if readiness.state == "ready_with_overrides" else st.error
        renderer(readiness.summary)
        with st.expander("What this report cannot yet stand behind", expanded=True):
            for req in readiness.unmet:
                st.markdown(f"**{req.title}** — {req.detail}")
            for req in readiness.overridden:
                who = f" ({req.override_by})" if req.override_by else ""
                st.markdown(
                    f"**{req.title}** — {req.detail}  \n"
                    f"_Overridden{who}: {req.override_reason or 'no reason recorded'}_"
                )
            if readiness.unmet:
                st.caption(
                    "The report will still be produced, stamped PROVISIONAL and "
                    "listing these items. To issue it as an interim document "
                    "instead, record who is issuing it and why."
                )
                with st.form(f"override_{report}"):
                    by = st.text_input("Issued by", key=f"ovr_by_{report}")
                    reason = st.text_area("Reason", key=f"ovr_why_{report}")
                    picked = st.multiselect(
                        "Requirements to issue on override",
                        [r.key for r in readiness.unmet],
                        format_func=lambda k: dict(
                            (r.key, r.title) for r in readiness.unmet)[k],
                        key=f"ovr_keys_{report}",
                    )
                    if st.form_submit_button("Record override") and picked and reason:
                        st.session_state[f"_override_{report}"] = {
                            key: {"reason": reason.strip(), "by": by.strip()}
                            for key in picked
                        }
                        st.rerun()
    if readiness.assumptions:
        st.caption("Assumptions carried into this report: "
                   + "; ".join(readiness.assumptions))
    return readiness


def _apply_latlon() -> None:
    """Convert the decimal lat/lon entry into the UTM site fields.

    Runs as a widget callback (before the script reruns) so it can write
    the meta_easting / meta_northing / meta_zone widget state safely. Field
    crews read decimal degrees off a phone or handheld GPS; this removes the
    UTM-typing friction and the wrong-zone errors it causes.
    """
    raw = (st.session_state.get("latlon_paste", "") or "").strip()
    lat = st.session_state.get("latlon_lat", 0.0)
    lon = st.session_state.get("latlon_lon", 0.0)
    if raw:
        # parse_latlon reads N/S/E/W as signs. Discarding them and taking the
        # number at face value put every W longitude 26 degrees east of the
        # site, silently and on the wrong side of the continent.
        parsed = parse_latlon(raw)
        if parsed is None:
            st.session_state["latlon_error"] = (
                "Could not read those coordinates. Enter 'lat, lon' in decimal "
                "degrees - 8.4657, -13.2317 or 8.4657 N, 13.2317 W."
            )
            return
        lat, lon = parsed
    if not lat or not lon:
        st.session_state["latlon_error"] = (
            "Enter a latitude and longitude (or paste them) first."
        )
        return
    utm = geographic_to_utm(lat, lon)
    st.session_state["meta_easting"] = float(round(utm.easting))
    st.session_state["meta_northing"] = float(round(utm.northing))
    st.session_state["meta_zone"] = f"{28 if utm.zone <= 28 else 29}N"
    st.session_state["latlon_error"] = ""


# ---------------------------------------------------------------------------
# Project file: save and restore the whole working state
# ---------------------------------------------------------------------------

def project_file_bytes() -> bytes:
    """Serialize the widget state that makes up a project."""
    return serialize_project(dict(st.session_state), groundwater.__version__)


def _load_project() -> None:
    """Apply an uploaded project file (button callback, runs pre-render)."""
    upload = st.session_state.get("project_upload")
    if upload is None:
        return
    try:
        updates = deserialize_project(upload.getvalue())
    except ValueError:
        st.session_state.project_load_error = True
        return
    # a loaded project fully replaces the working state: drop the previous
    # data sources, recompute inputs and computed results first, so a stale
    # dataset from earlier in the session cannot bleed into the loaded project
    for stale in stale_on_load(st.session_state):
        st.session_state.pop(stale, None)
    for result_key in (
        "ves_results", "pump_analysis", "wq_assessment", "borehole_design",
        "drilling_log", "cost_estimate", "cost_artifacts",
        "wp_result", "handover_built",
        # cleared too, so a project with no sources at all cannot inherit the
        # previous project's rebuild banner
        "recompute_diagnostics",
    ):
        st.session_state.pop(result_key, None)
    overrides = updates.pop("rates_overrides", None)
    committee = updates.pop("committee", None)
    sources = updates.pop("sources", None)
    # the file names it "asset"; the session key it belongs under is the one
    # serialize_project reads back, so the round trip has to be closed here
    asset = updates.pop("asset", None)
    for key, value in updates.items():
        st.session_state[key] = value
    if isinstance(overrides, dict):
        st.session_state.rates_overrides = overrides
    if isinstance(asset, dict) and asset:
        st.session_state["asset_record"] = asset
    # restore the saved data files and flag a recompute so the analyses and
    # reports are rebuilt without re-uploading
    if isinstance(sources, dict) and sources:
        for skey, src in sources.items():
            st.session_state[f"src_{skey}"] = src
        st.session_state["_recompute_pending"] = True
    # restore the WASH committee: set the data_editor base and clear its
    # stale edit delta so the saved rows show cleanly after loading
    if isinstance(committee, list) and committee:
        st.session_state["ho_committee_rows"] = committee
        st.session_state["ho_committee_data"] = committee
        st.session_state.pop("ho_committee", None)
    # reset the rate editor so it shows the loaded values
    st.session_state.pop("rates_editor", None)
    st.session_state.project_loaded = True
    # protect restored inputs from the prefill-reset checks for one run
    st.session_state.project_just_loaded = True
    # the wizard costing block only executes on its step, so it carries
    # its own grace marker, consumed when that block first runs
    st.session_state["_wiz_load_grace"] = True


# ---------------------------------------------------------------------------
# Navigation: one workspace, pages grouped by lifecycle stage
# ---------------------------------------------------------------------------

NAV_GROUPS: list[tuple[str, list[str]]] = [
    ("Project", ["Overview", "Guided start", "Site maps"]),
    ("Investigation", ["Geophysics (VES)", "Borehole design", "Depth Spine",
                       "Scanned sheets"]),
    ("Testing", ["Pumping test", "Water quality"]),
    ("Delivery", ["Costing & BoQ", "Procurement", "Supervision", "Handover",
                  "Templates"]),
    ("Area analysis", ["Water points", "Coverage gap", "Portfolio",
                       "Asset registry"]),
]
_ALL_PAGES = [p for _, pages in NAV_GROUPS for p in pages]
DEFAULT_PAGE = "Overview"


def _page_key(name: str) -> str:
    return "page_" + "".join(c if c.isalnum() else "_" for c in name.lower())


def _group_key(group: str) -> str:
    return "nav_" + "".join(c if c.isalnum() else "_" for c in group.lower())


def _nav_changed(group_key: str) -> None:
    """A page picked in one sidebar group becomes the single active page."""
    choice = st.session_state.get(group_key)
    if choice:
        st.session_state["nav"] = choice


def _goto(page: str) -> None:
    st.session_state["nav"] = page


def _next_step(label: str, page: str, note: str = "", key: str = "") -> None:
    """Bottom-of-page route to the next lifecycle step.

    Every page except the Overview used to dead-end: having read the
    recommended drilling depth there was no way on to Costing except hunting
    through the sidebar.

    ``key`` disambiguates when two pages route to the same destination - the
    key is otherwise derived from the destination alone, which would collide.
    """
    st.divider()
    col_a, col_b = st.columns([3, 1])
    col_a.caption(note or f"Next: {page}")
    col_b.button(label, key=key or f"next_{_page_key(page)}", width="stretch",
                 on_click=_goto, args=(page,))


def _spine_iframe(html: str, height: int) -> None:
    """Put the static workspace in an iframe, whichever API this runtime has.

    ``st.components.v1.html`` is deprecated in favour of ``st.iframe``, but the
    in-browser demo pins an older Streamlit that has only the former, and the
    project supports streamlit>=1.57. Use whichever exists.
    """
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:  # pragma: no cover - older runtimes, including the browser demo
        components.html(html, height=height, scrolling=True)


def _spine_frame_height(view: dict) -> int:
    """Tall enough for the workspace without a scrollbar in the common case.

    The section is a fixed-height track; what varies is how far the rail runs,
    and the water-quality stage is the longest of the three. Erring tall costs
    whitespace, erring short costs a nested scrollbar, so err tall.
    """
    base = 780
    if view.get("quality"):
        base = 1180
    return base


def _spine_screen_editor(view: dict, state_key: str, placed) -> None:
    """Edit the screened intervals without the drag handles.

    The static workspace cannot hand anything back, so the same edit is offered
    as numbers. It goes through design_borehole exactly as a dragged interval
    does - this is a different gesture, not a different calculation.
    """
    screens = view["design"]["screens"]
    limits = view["section"]["screenLimits"]
    with st.expander("Edit the screened intervals", expanded=False):
        st.caption(
            "Dragging needs the full application; here the same intervals are "
            "typed. They are re-derived through the same design rules, and "
            "anything that does not fit is clipped or dropped with a flag."
        )
        edited: list[tuple[float, float]] = []
        for index, screen in enumerate(screens):
            col_top, col_base = st.columns(2)
            top = col_top.number_input(
                f"Screen {index + 1} top (m)",
                min_value=float(limits["top"]),
                max_value=float(limits["base"]),
                value=float(screen["top"]),
                step=0.5,
                key=f"{state_key}_top_{index}",
            )
            base = col_base.number_input(
                f"Screen {index + 1} base (m)",
                min_value=float(limits["top"]),
                max_value=float(limits["base"]),
                value=float(screen["base"]),
                step=0.5,
                key=f"{state_key}_base_{index}",
            )
            edited.append((float(top), float(base)))

        apply_col, reset_col = st.columns([1, 1])
        if apply_col.button("Apply to the design", key=f"{state_key}_apply"):
            if edited != placed:
                st.session_state[state_key] = edited
                st.rerun()
        if placed and reset_col.button(
            "Back to the generated design", key=f"{state_key}_reset_editor"
        ):
            del st.session_state[state_key]
            st.rerun()


def _band(value, bands: list[tuple[float, str]], above: str) -> str:
    """First label whose upper bound the value falls under, else ``above``.

    A number with no interpretation is not useful to a drilling supervisor:
    12 percent model fit or 4 m2/day transmissivity mean nothing on their own.
    """
    if value is None:
        return ""
    for limit, label in bands:
        if float(value) < limit:
            return label
    return above


def _page(name: str):
    """Keyed container for one workspace page.

    Every page renders on every run - matching the previous flat-tab
    behaviour, so cross-page state (and the app tests) keep working -
    while the sidebar navigation controls which page is visible through
    a per-key CSS rule.
    """
    return st.container(key=_page_key(name))


def _status_chip() -> tuple[str, str]:
    """(label, css class) for the current project's lifecycle status."""
    summary = _project_summary()
    if "status" not in summary:
        return "New", "gw-chip-grey"
    status = classify_status(summary)
    label = {
        "successful": "Successful",
        "dry": "Dry / failed",
        "sited": "Sited",
    }.get(status) or STATUS_LABELS.get(
        status, str(summary.get("status", "")).title()
    )
    css = {
        "successful": "gw-chip-green",
        "dry": "gw-chip-red",
        "sited": "gw-chip-amber",
    }.get(status, "gw-chip-grey")
    return label, css


# After loading a project, rebuild the analysis objects from the saved data
# files so the pages and reports are populated without re-uploading. Runs
# before the sidebar so the active-project status reflects the loaded state
# on the same run.
if st.session_state.pop("_recompute_pending", False):
    _sources = {
        key[len("src_"):]: value
        for key, value in st.session_state.items()
        if key.startswith("src_") and isinstance(value, dict)
    }
    _discharges = {
        key[len("q_"):]: value
        for key, value in st.session_state.items()
        if key.startswith("q_") and isinstance(value, (int, float)) and value
    }
    if _sources:
        try:
            with st.spinner("Rebuilding the analyses from the loaded project..."):
                st.session_state.update(
                    recompute_results(
                        _sources,
                        discharges=_discharges,
                        design_swl=st.session_state.get("design_swl"),
                        config=CONFIG,
                        sample_root=sample_data_dir(),
                        tmp_dir=workdir(),
                    )
                )
        except Exception as exc:  # noqa: BLE001 - last resort, still reported
            # recompute_results contains its own failures, so reaching here
            # means something outside them broke. One render path speaks for
            # every failure mode, so write a diagnostic rather than only
            # warning: a dropped result otherwise reads as "never sampled".
            st.session_state["recompute_diagnostics"] = {
                "ok": [],
                "issues": [{
                    "source": "", "result": "", "label": "Saved project",
                    "level": "error", "code": "recompute_crashed",
                    "message": "The saved analyses could not be rebuilt. "
                               "Re-upload the data files on the affected pages.",
                    "context": "", "detail": f"{type(exc).__name__}: {exc}"[:300],
                }],
            }

# A source that failed to rebuild leaves its page looking untouched, and an
# untouched water-quality page is indistinguishable from a borehole nobody
# sampled. Say which file failed, on every run, until the missing result is
# supplied by hand or another project is loaded - an issue whose result is
# now in session state has been resolved and stops being reported.
_diagnostics = st.session_state.get("recompute_diagnostics") or {}
for _issue in _diagnostics.get("issues", []):
    if _issue.get("result") and st.session_state.get(_issue["result"]) is not None:
        continue
    _text = f"**{_issue['label']}** - {_issue['message']}"
    if _issue.get("context"):
        _text += f"  \n_File: {_issue['context']}_"
    if _issue.get("detail"):
        _text += f"  \n`{_issue['detail']}`"
    (st.error if _issue.get("level") == "error" else st.warning)(_text)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(
        """
        <div class="gw-brand">
          <div class="gw-brand-mark">G</div>
          <div>
            <div class="gw-brand-name">Groundwater Toolkit</div>
            <div class="gw-brand-sub">FIELD DATA → REPORTS</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Field data in, client-ready reports out - for rural water "
        "supply borehole projects in Sierra Leone."
    )
    # detect the district from the coordinates entered on the previous
    # run, so the dropdown can pre-fill before the widgets render
    provinces, district_rows = cached_districts()
    all_districts = [d for d, _ in district_rows]
    detected_district = ""
    detected_latlon = None
    _e = st.session_state.get("meta_easting", 0.0)
    _n = st.session_state.get("meta_northing", 0.0)
    if _e and _n:
        _zone = int(str(st.session_state.get("meta_zone", "29N")).rstrip("N"))
        _lat, _lon = utm_to_geographic(_e, _n, _zone)
        detected_latlon = (_lat, _lon)
        detected_district = district_of(_lat, _lon)
        if detected_district in all_districts and not st.session_state.get(
            "meta_district"
        ):
            st.session_state["meta_district"] = detected_district
            st.session_state["meta_province"] = dict(district_rows)[
                detected_district
            ]
        # auto-fill the chiefdom from the GPS as well, when not already set
        if not st.session_state.get("meta_chiefdom"):
            _chiefdom, _chief_district = chiefdom_of(_lat, _lon)
            if _chiefdom:
                st.session_state["meta_chiefdom"] = _chiefdom

    _probe = site_from_state()
    _chip_label, _chip_css = _status_chip()
    if _probe.community:
        _proj_name = _html.escape(_probe.community)
        if _probe.district:
            _proj_name += f" — {_html.escape(_probe.district)}"
    else:
        _proj_name = "New project"
    st.markdown(
        f"""
        <div class="gw-project-card">
          <div class="gw-cap">Active project</div>
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:2px">
            <span style="font-weight:600;font-size:0.82rem">{_proj_name}</span>
            <span class="gw-chip {_chip_css}">{_chip_label}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not (_probe.community and _probe.latlon is not None):
        st.caption(
            "📍 Set the site details below - community, area and GPS - "
            "or load a saved project file. Every page, map and report "
            "uses them."
        )

    # Grouped navigation: one radio per lifecycle group, kept consistent
    # with the single active page before the widgets render.
    _nav_current = st.session_state.setdefault("nav", DEFAULT_PAGE)
    if _nav_current not in _ALL_PAGES:
        _nav_current = st.session_state["nav"] = DEFAULT_PAGE
    for _group, _pages in NAV_GROUPS:
        _gkey = _group_key(_group)
        st.session_state[_gkey] = _nav_current if _nav_current in _pages else None
        st.radio(
            _group,
            _pages,
            index=None,
            key=_gkey,
            on_change=_nav_changed,
            args=(_gkey,),
        )
    st.divider()

    with st.expander("📍 Site details (used by all pages)",
                     expanded=not _probe.community):
        st.text_input("Community / town", key="meta_community")
        province_options = [""] + provinces
        if st.session_state.get("meta_province") not in province_options:
            st.session_state.pop("meta_province", None)
        st.selectbox(
            "Area / province", province_options, key="meta_province",
            format_func=lambda v: v or "(select)",
            help="Western Area covers Freetown (Urban) and the rest of "
            "the peninsula (Rural).",
        )
        _chosen_province = st.session_state.get("meta_province", "")
        district_options = [""] + [
            d for d, p in district_rows
            if not _chosen_province or p == _chosen_province
        ]
        if st.session_state.get("meta_district") not in district_options:
            st.session_state.pop("meta_district", None)
        st.selectbox(
            "District", district_options, key="meta_district",
            format_func=lambda v: v or "(select)",
        )
        st.text_input("Chiefdom", key="meta_chiefdom")
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
        # A loaded project may carry meta_zone as a bare int/str (e.g. 29);
        # coerce it to the "NN N" option and drop anything unrecognised so the
        # selectbox never raises on a value outside its options.
        _zone_val = st.session_state.get("meta_zone")
        if _zone_val is not None and _zone_val not in ("28N", "29N"):
            _z = str(_zone_val).upper().rstrip("N").strip()
            st.session_state["meta_zone"] = f"{_z}N" if _z in ("28", "29") else "29N"
        st.selectbox("UTM zone", ["28N", "29N"], index=1, key="meta_zone",
                     help="28N west of 12 degrees W (Freetown, Port Loko), "
                     "29N further east.")
        st.caption(
            "Phone or handheld GPS reads decimal degrees? Enter or paste "
            "lat/lon and convert to the UTM fields above:"
        )
        _lat_col, _lon_col = st.columns(2)
        _lat_col.number_input("Latitude (deg N)", key="latlon_lat",
                              format="%.6f", step=0.0001)
        _lon_col.number_input("Longitude (deg, W negative)", key="latlon_lon",
                              format="%.6f", step=0.0001)
        st.text_input("or paste 'lat, lon'", key="latlon_paste",
                      placeholder="8.4657, -13.2317",
                      help="Signed decimals or hemisphere letters both work: "
                      "8.4657, -13.2317 and 8.4657 N, 13.2317 W are the same "
                      "point.")
        st.button("Convert to UTM", on_click=_apply_latlon,
                  width="stretch")
        if st.session_state.get("latlon_error"):
            st.warning(st.session_state["latlon_error"])
        if detected_latlon is not None:
            lat, lon = detected_latlon
            if detected_district:
                st.caption(
                    f"Coordinates fall in **{detected_district}** District "
                    f"({lat:.4f} N, {abs(lon):.4f} W)."
                )
            else:
                st.caption(
                    "These coordinates fall outside every district - "
                    "check the values and the UTM zone."
                )
    with st.expander("🧭 Suggested workflow", expanded=False):
        st.markdown(
            "1. **Geophysics (VES)** - siting and drilling depth\n"
            "2. **Costing & BoQ** - budget and bill of quantities\n"
            "3. **Supervision** - checklists while drilling\n"
            "4. **Borehole design** - from the drilling log\n"
            "5. **Pumping test** - safe yield and pump depth\n"
            "6. **Water quality** - WHO/national verdict\n\n"
            "Every page offers bundled sample data, so you can try "
            "each step without your own files."
        )
    with st.expander("📄 Report branding"):
        st.text_input(
            "Organisation name",
            key="org_name",
            help="Shown in the headers of generated reports.",
        )
        st.text_input("Organisation details", key="org_details",
                      help="Address or contact line under the name.")
    # The sidebar runs before every page body, so a download button built here
    # would carry the state as it was *before* this run's analyses. Reserve the
    # slot now and fill it at the end of the script, once the pages have run:
    # otherwise "Save project" straight after an analysis wrote a file with no
    # results in it, and the Portfolio page then showed the site as unstarted.
    _project_panel = st.expander("💾 Project file")
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
        "here than in the full installation. Every page has bundled sample "
        "data so you can try it without your own files."
    )

# Workspace pages. Each is a keyed container that renders on every run
# (like the flat tabs this replaces); the active page from the sidebar
# navigation stays visible and the rest are hidden by the rule below.
tab_overview = _page("Overview")
tab_guide = _page("Guided start")
tab_ves = _page("Geophysics (VES)")
tab_cost = _page("Costing & BoQ")
tab_procurement = _page("Procurement")
tab_supervision = _page("Supervision")
tab_design = _page("Borehole design")
tab_spine = _page("Depth Spine")
tab_pump = _page("Pumping test")
tab_quality = _page("Water quality")
tab_handover = _page("Handover")
tab_maps = _page("Site maps")
tab_waterpoints = _page("Water points")
tab_coverage = _page("Coverage gap")
tab_extract = _page("Scanned sheets")
tab_templates = _page("Templates")
tab_portfolio = _page("Portfolio")
tab_registry = _page("Asset registry")

_active_page = st.session_state.get("nav", DEFAULT_PAGE)
st.markdown(
    "<style>"
    + "".join(
        f".st-key-{_page_key(name)}{{display:none}}"
        for name in _ALL_PAGES
        if name != _active_page
    )
    + "</style>",
    unsafe_allow_html=True,
)


def run_ves_inversion(soundings) -> None:
    """Invert and interpret the soundings, storing the shared results."""
    # a fresh siting result is a genuine source change: the wizard
    # costing prefill must follow it, not a previously loaded project
    st.session_state.pop("_wiz_load_grace", None)
    results = []
    interps = []
    progress = st.progress(0.0)
    for i, sounding in enumerate(soundings):
        result = invert_sounding(sounding, CONFIG.ves)
        interp = interpret_model(sounding, result.model, CONFIG.ves)
        results.append(result)
        interps.append(interp)
        progress.progress((i + 1) / len(soundings))
    # rank before anything reads interp.rank: the Overview renders earlier in
    # the run than the VES page that used to be the only thing ranking them,
    # so it named whichever sounding was parsed first as the drill target
    rank_interpretations(interps)
    st.session_state.ves_results = (soundings, results, interps)


def compute_cost_estimate(inputs: CostingInputs, rates, **kwargs) -> None:
    """Estimate and build the shared artifacts (chart and BoQ workbook)."""
    estimate = estimate_borehole_cost(inputs, rates, **kwargs)
    st.session_state.cost_estimate = estimate
    chart_path = workdir() / "cost_breakdown.png"
    plot_cost_breakdown(estimate, chart_path, app_config().style)
    boq_path = workdir() / "Bill_of_Quantities.xlsx"
    write_boq_workbook(estimate, boq_path)
    st.session_state.cost_artifacts = (chart_path, boq_path)


# ---------------------------------------------------------------------------
# Overview - the project dashboard (design direction 1b, Project Workspace)
# ---------------------------------------------------------------------------

# Upper bound of the guided start's depth fields. Streamlit raises on a
# prefilled value outside a number_input's range, so anything derived from a
# survey result has to be clamped into it before it is passed in.
WIZ_MAX_DEPTH_M = 300.0


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def _source_signature(source) -> tuple:
    """A cheap identity for an uploaded file or bundled sample.

    Used to notice that a page is now looking at a different borehole's
    sheet, so inputs typed for the previous one are not carried over.
    """
    if not isinstance(source, dict):
        return ()
    if source.get("sample"):
        return ("sample", str(source["sample"]))
    blob = source.get("bytes") or b""
    return ("upload", str(source.get("name") or ""), len(blob))


def _rows_html(rows: list[tuple[str, str]]) -> str:
    return "".join(
        f"<div class='gw-row'><span>{_html.escape(str(k))}</span>"
        f"<b>{_html.escape(str(v))}</b></div>"
        for k, v in rows
    )


def _stepper_html(steps: list[tuple[str, bool]]) -> str:
    parts = ["<div class='gw-steps'>"]
    for i, (label, done) in enumerate(steps):
        if i:
            joined = steps[i - 1][1] and done
            parts.append(
                "<div class='gw-step-line"
                + ("" if joined else " gw-step-line-todo")
                + "'></div>"
            )
        cls = "gw-step-done" if done else "gw-step-todo"
        dot = "✓" if done else str(i + 1)
        parts.append(
            f"<div class='gw-step {cls}'><span class='gw-step-dot'>{dot}</span>"
            f"<span class='gw-step-label'>{_html.escape(label)}</span></div>"
        )
    parts.append("</div>")
    return "".join(parts)


with tab_overview:
    _ov_site = site_from_state()
    _ov_ves = st.session_state.get("ves_results")
    _ov_log = st.session_state.get("drilling_log")
    _ov_pump = st.session_state.get("pump_analysis")
    _ov_wq = st.session_state.get("wq_assessment")
    _ov_design = st.session_state.get("borehole_design")
    _ov_cost = st.session_state.get("cost_estimate")

    _chip_label, _chip_css = _status_chip()
    _ov_title = _html.escape(_ov_site.community or "New project")
    if _ov_site.district:
        _ov_title += f" — {_html.escape(_ov_site.district)} District"
    _head_l, _head_r = st.columns([3, 1])
    with _head_l:
        st.markdown(
            f"<h2 style='margin:0 0 2px'>{_ov_title} "
            f"<span class='gw-chip {_chip_css}'>{_chip_label}</span></h2>",
            unsafe_allow_html=True,
        )
        _sub = []
        if _ov_site.latlon is not None:
            _lat, _lon = _ov_site.latlon
            _sub.append(f"{_lat:.4f}° N, {abs(_lon):.4f}° W")
        if _ov_site.chiefdom:
            _sub.append(f"{_ov_site.chiefdom} Chiefdom")
        if _ov_site.client:
            _sub.append(_ov_site.client)
        st.caption(" · ".join(_sub) or
                   "The whole borehole lifecycle in one workspace.")
    with _head_r:
        st.button("Generate handover →", key="ov_go_handover",
                  type="primary", width="stretch",
                  on_click=_goto, args=("Handover",))

    # Lifecycle state, derived from what has actually been produced
    st.markdown(
        _stepper_html([
            ("Sited", _ov_ves is not None),
            ("Drilled", _ov_log is not None),
            ("Tested", _ov_pump is not None),
            ("Assessed", _ov_wq is not None),
            ("Handover", bool(st.session_state.get("handover_built"))),
        ]),
        unsafe_allow_html=True,
    )

    _has_results = any(x is not None for x in (
        _ov_ves, _ov_log, _ov_pump, _ov_wq, _ov_cost,
    ))
    if not _has_results:
        st.markdown(
            "<div class='gw-card'><span class='gw-cap'>Getting started</span>"
            "<div style='font-size:0.86rem;color:rgba(0,0,0,.7);line-height:1.5'>"
            "Nothing has been analysed yet. Work through the guided start, "
            "or open any page from the sidebar - every page offers bundled "
            "sample data (Rokel, Dr Timbo, Kuntolo) so you can try the whole "
            "lifecycle without your own files. Loading a saved project file "
            "from the sidebar restores a previous session, analyses and "
            "all.</div></div>",
            unsafe_allow_html=True,
        )
        _cta1, _cta2, _cta3 = st.columns(3)
        _cta1.button("🚀 Open guided start", key="ov_go_guide",
                     width="stretch",
                     on_click=_goto, args=("Guided start",))
        _cta2.button("📈 Run a VES analysis", key="ov_go_ves",
                     width="stretch",
                     on_click=_goto, args=("Geophysics (VES)",))
        _cta3.button("💰 Estimate a borehole", key="ov_go_cost",
                     width="stretch",
                     on_click=_goto, args=("Costing & BoQ",))
    else:
        _col1, _col2, _col3 = st.columns(3)

        with _col1:
            # Site card
            _site_rows: list[tuple[str, str]] = []
            if _ov_site.district:
                _site_rows.append(("District", _ov_site.district))
            if _ov_site.chiefdom:
                _site_rows.append(("Chiefdom", _ov_site.chiefdom))
            if _ov_site.easting and _ov_site.northing:
                _site_rows.append((
                    "UTM",
                    f"{_ov_site.easting:.0f} E · {_ov_site.northing:.0f} N "
                    f"({_ov_site.utm_zone}N)",
                ))
            _wp = st.session_state.get("wp_result")
            if _wp and _wp.get("decision"):
                _wp_sum = _wp["decision"].get("summary", {})
                if _wp_sum.get("total") is not None:
                    _site_rows.append((
                        "Water points nearby",
                        f"{_wp_sum['total']} "
                        f"({_wp_sum.get('functional', 0)} functional)",
                    ))
            st.markdown(
                "<div class='gw-card'><span class='gw-cap'>Site</span>"
                + (_rows_html(_site_rows) or
                   "<div class='gw-row'><span>No site details yet - set "
                   "them in the sidebar.</span></div>")
                + "</div>",
                unsafe_allow_html=True,
            )

            # Siting / geophysics card
            if _ov_ves is not None:
                _soundings, _results, _interps = _ov_ves
                _best = min(
                    _interps, key=lambda i: (i.rank or 99, -i.score),
                ) if _interps else None
                _ves_rows = [("Soundings analysed", str(len(_results)))]
                if _best is not None:
                    _ves_rows.append(("Preferred site", _best.sounding_id))
                    if _best.depth_to_basement_m:
                        _ves_rows.append((
                            "Depth to basement",
                            f"{_best.depth_to_basement_m:.1f} m",
                        ))
                    if _best.max_drilling_depth_m:
                        _ves_rows.append((
                            "Recommended drilling depth",
                            f"{_best.max_drilling_depth_m:.0f} m",
                        ))
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Geophysics"
                    "</span>" + _rows_html(_ves_rows) + "</div>",
                    unsafe_allow_html=True,
                )

        with _col2:
            # Borehole card (design first, else the drilling log)
            if _ov_design is not None:
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Borehole"
                    "</span>" + _rows_html(_ov_design.summary_rows()[:6])
                    + "</div>",
                    unsafe_allow_html=True,
                )
            elif _ov_log is not None:
                # total_depth_m is optional: a partially filled log template
                # parses with no depth
                _log_rows = [(
                    "Drilled depth",
                    f"{_ov_log.total_depth_m:.0f} m"
                    if _ov_log.total_depth_m else "pending",
                )]
                if _ov_log.status:
                    _log_rows.append(("Outcome", _ov_log.status))
                if _ov_log.water_strikes_m:
                    _log_rows.append((
                        "Water strikes",
                        ", ".join(f"{w:g} m" for w in _ov_log.water_strikes_m),
                    ))
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Borehole"
                    "</span>" + _rows_html(_log_rows) + "</div>",
                    unsafe_allow_html=True,
                )

            # Pumping test card
            if _ov_pump is not None:
                _yr = _ov_pump.yield_recommendation
                if _yr is not None and _yr.safe_yield_m3_per_h:
                    _pump_head = (
                        f"<div class='gw-big'>{_yr.safe_yield_m3_per_h:.2f} "
                        "<small>m³/h safe yield</small></div>"
                    )
                else:
                    _reason = (_yr.pending_reason if _yr is not None else
                               "discharge pending")
                    _pump_head = (
                        "<span class='gw-chip gw-chip-amber'>Pending</span>"
                        f"<div style='font-size:0.75rem;color:rgba(0,0,0,.55);"
                        f"margin-top:6px'>{_html.escape(_reason)}</div>"
                    )
                _pump_rows = []
                _t = _ov_pump.transmissivity_m2_per_day
                if _t:
                    _pump_rows.append(("Transmissivity", f"{_t:.1f} m²/day"))
                if _ov_pump.max_drawdown_m:
                    _pump_rows.append(
                        ("Max drawdown", f"{_ov_pump.max_drawdown_m:.2f} m"))
                if _yr is not None and _yr.pump_installation_depth_m:
                    _pump_rows.append((
                        "Pump setting",
                        f"{_yr.pump_installation_depth_m:.0f} m",
                    ))
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Pumping test"
                    "</span>" + _pump_head + _rows_html(_pump_rows) + "</div>",
                    unsafe_allow_html=True,
                )

        with _col3:
            # Water quality card
            if _ov_wq is not None:
                _wq_state = _ov_wq.verdict_state
                _wq_chip = (_VERDICT_CHIP[_wq_state], VERDICT_SHORT[_wq_state])
                if _wq_state == "health_fail":
                    _wq_note = ", ".join(
                        r.parameter for r in _ov_wq.health_exceedances[:4])
                elif _wq_state == "national_fail":
                    _wq_note = ", ".join(
                        r.parameter for r in _ov_wq.national_exceedances[:4])
                elif _wq_state == "indeterminate":
                    _wq_note = "; ".join(_ov_wq.uncertainties[:2])
                elif _wq_state == "aesthetic":
                    _wq_note = ", ".join(
                        r.parameter for r in _ov_wq.aesthetic_exceedances[:4])
                else:
                    _wq_note = "All measured parameters within guideline"
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Water quality"
                    " — WHO</span>"
                    f"<span class='gw-chip {_wq_chip[0]}'>{_wq_chip[1]}</span>"
                    f"<div style='font-size:0.75rem;color:rgba(0,0,0,.55);"
                    f"margin-top:6px'>{_html.escape(_wq_note)}</div>"
                    + _rows_html([
                        ("Parameters assessed", str(len(_ov_wq.rows))),
                    ])
                    + "</div>",
                    unsafe_allow_html=True,
                )

            # Cost card with the by-stage breakdown bar
            if _ov_cost is not None:
                _stages = [(s, v) for s, v in _ov_cost.by_stage() if v > 0]
                _total = sum(v for _, v in _stages) or 1.0
                _bar_colors = ["#2B6850", "#4C8A6F", "#6FAC90",
                               "#B0A365", "#C98A4B", "#8C8C7A"]
                _bar = "".join(
                    f"<div style='width:{100 * v / _total:.1f}%;"
                    f"background:{_bar_colors[i % len(_bar_colors)]}'></div>"
                    for i, (_, v) in enumerate(_stages)
                )
                _legend = "".join(
                    f"<span><i style='background:"
                    f"{_bar_colors[i % len(_bar_colors)]}'></i>"
                    f"{_html.escape(s)}</span>"
                    for i, (s, _) in enumerate(_stages)
                )
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Cost estimate"
                    "</span>"
                    f"<div class='gw-big'>US$ {_ov_cost.price_usd:,.0f} "
                    "<small>price</small></div>"
                    f"<div style='font:400 10px \"IBM Plex Mono\",monospace;"
                    f"color:rgba(0,0,0,.45)'>RWSN model · "
                    f"US$ {_ov_cost.cost_per_meter_usd:,.0f}/m</div>"
                    f"<div class='gw-bar'>{_bar}</div>"
                    f"<div class='gw-legend'>{_legend}</div></div>",
                    unsafe_allow_html=True,
                )

            # Report readiness card
            _chk_done = any(
                str(v) in ("Yes", "No", "N/A")
                for k, v in st.session_state.items() if k.startswith("chk_")
            )
            _report_state = [
                ("Geophysical survey", _ov_ves is not None),
                ("Borehole completion", _ov_log is not None),
                ("Pumping test", _ov_pump is not None),
                ("Water quality", _ov_wq is not None),
                ("Cost estimate", _ov_cost is not None),
                ("Supervision record", _chk_done),
                ("Handover", bool(st.session_state.get("handover_built"))),
            ]
            _n_ready = sum(1 for _, ready in _report_state if ready)
            _report_rows = "".join(
                "<div class='gw-report-row'><span>" + _html.escape(name)
                + "</span><span class='gw-chip "
                + ("gw-chip-green'>Ready" if ready else "gw-chip-grey'>—")
                + "</span></div>"
                for name, ready in _report_state
            )
            st.markdown(
                "<div class='gw-card'><span class='gw-cap'>Reports — "
                f"{_n_ready} / {len(_report_state)} ready</span>"
                + _report_rows + "</div>",
                unsafe_allow_html=True,
            )

    # Everything built this session, in one place. A build button is true for
    # a single rerun, so its download button used to disappear as soon as the
    # user touched anything else and the report had to be rebuilt to get it.
    # Filled at the end of the script: the Overview renders before the pages
    # that produce the files, so reading the list here would lag a run behind.
    _deliverables_slot = st.container()


# ---------------------------------------------------------------------------
# Guided start
# ---------------------------------------------------------------------------
with tab_guide:
    _WIZ_STEPS = ("Site details", "Siting (VES)", "Costing", "Ready to drill")
    wiz_step = int(st.session_state.get("wiz_step", 0))

    st.header("Guided project setup")
    st.caption(
        "Three short steps to a sited, costed borehole project. Every "
        "result carries over to the full pages, where you can fine tune."
    )
    st.progress(
        wiz_step / (len(_WIZ_STEPS) - 1),
        text=f"Step {min(wiz_step, 2) + 1} of 3: {_WIZ_STEPS[wiz_step]}"
        if wiz_step < 3
        else "Setup complete",
    )

    def _wiz_go(step: int) -> None:
        st.session_state.wiz_step = step

    def _top_interp():
        """Best ranked interpretation, read fresh from session state.

        Called where needed rather than once per rerun, so the step
        that has just run the inversion sees its own result.
        """
        if "ves_results" not in st.session_state:
            return None
        _, _, interps = st.session_state.ves_results
        ranked = sorted(interps, key=lambda i: (i.rank or 99, -i.score))
        return ranked[0] if ranked else None

    site = site_from_state()

    if wiz_step == 0:
        st.subheader("1. Who and where")
        st.write(
            "Fill the **Site details** panel in the sidebar (already "
            "open). The wizard checks it off as you go; a saved project "
            "file loads everything at once."
        )
        checks = [
            ("Community", bool(site.community)),
            ("Area and district", bool(site.district)),
            ("Client", bool(site.client)),
            ("GPS coordinates", site.latlon is not None),
        ]
        for label, done in checks:
            st.markdown(("✅ " if done else "⬜ ") + label)
        ready = bool(site.community and site.district)
        if not ready:
            st.info("Community and district are needed to continue.")
        elif site.latlon is None:
            st.warning(
                "No GPS coordinates yet: maps and report locations will "
                "be blank until they are entered. You can continue."
            )
        st.button(
            "Next: Siting (VES) →", key="wiz_next", type="primary",
            disabled=not ready, on_click=_wiz_go, args=(1,),
        )

    elif wiz_step == 1:
        st.subheader("2. Where to drill and how deep")
        st.write(
            "Upload the VES field workbook (or try the bundled sample) "
            "and run the inversion. The best ranked sounding sets the "
            "drilling depth for the cost estimate."
        )
        wiz_path = choose_input(
            "VES workbook (standard template)", "wiz_ves", ["xlsx"],
            ["rokel/rokel_ves.xlsx"],
        )
        if wiz_path is not None:
            wiz_soundings = parse_upload(read_ves_workbook, wiz_path)
            if wiz_soundings:
                st.success(f"Parsed {len(wiz_soundings)} sounding(s).")
                if st.button("Run siting analysis", key="wiz_run_ves",
                             type="primary"):
                    run_ves_inversion(wiz_soundings)
            else:
                st.error("No soundings found in the workbook.")
        # read after the run button so a fresh result unlocks Next now
        top_interp = _top_interp()
        if top_interp is not None:
            st.metric(
                f"Recommended site: {top_interp.sounding_id}",
                f"drill to {top_interp.max_drilling_depth_m:g} m",
                help="Best ranked sounding; see the Geophysics (VES) page for "
                "curves, water zones and the full preference table.",
            )
        with st.expander("No VES data? Enter the planned depth directly"):
            st.number_input(
                "Planned drilling depth (m)", 0.0, 300.0, 0.0, 5.0,
                key="wiz_manual_depth",
                on_change=lambda: st.session_state.pop("_wiz_load_grace", None),
            )
        depth_known = (
            top_interp is not None
            or st.session_state.get("wiz_manual_depth", 0.0) > 0
        )
        col_b, col_n = st.columns([1, 3])
        col_b.button("← Back", key="wiz_back", on_click=_wiz_go, args=(0,))
        col_n.button(
            "Next: Costing →", key="wiz_next", type="primary",
            disabled=not depth_known, on_click=_wiz_go, args=(2,),
        )

    elif wiz_step == 2:
        st.subheader("3. What it will cost")
        top_interp = _top_interp()
        if top_interp is not None:
            default_depth = float(top_interp.max_drilling_depth_m)
            default_over = float(top_interp.depth_to_basement_m or 0.0)
            st.caption(
                f"Depth prefilled from the siting result "
                f"({top_interp.sounding_id}); adjust if needed."
            )
        else:
            default_depth = float(st.session_state.get("wiz_manual_depth", 60.0))
            default_over = 0.0
        # refresh the prefill when a new siting result arrives. The
        # signature is a string so the project file carries it and a
        # loaded project's adjusted values survive the first rerun.
        prefill_sig = f"{default_depth:.1f}:{default_over:.1f}"
        if st.session_state.get("wiz_prefill_sig") != prefill_sig:
            st.session_state["wiz_prefill_sig"] = prefill_sig
            # consume the load grace here, not at end of run: this block
            # only executes on the costing step, which a loaded project
            # may reach many runs after the load itself
            if not st.session_state.pop("_wiz_load_grace", False):
                st.session_state.pop("wiz_cost_depth", None)
                st.session_state.pop("wiz_cost_over", None)
        else:
            st.session_state.pop("_wiz_load_grace", None)
        c1, c2, c3 = st.columns(3)
        # A sounding that resolved nothing water bearing falls back to its
        # investigated depth (max AB/2), which on a deep survey can exceed
        # these bounds. Streamlit raises on a value outside them, so clamp:
        # an unusable prefill must not take the whole page down.
        wiz_depth = c1.number_input("Total depth (m)", 1.0, WIZ_MAX_DEPTH_M,
                                    _clamp(default_depth or 60.0,
                                           1.0, WIZ_MAX_DEPTH_M), 1.0,
                                    key="wiz_cost_depth")
        wiz_over = c2.number_input(
            "Overburden (m)", 0.0, WIZ_MAX_DEPTH_M,
            _clamp(default_over, 0.0, WIZ_MAX_DEPTH_M), 1.0,
            key="wiz_cost_over",
            help="0 applies the rule of thumb (half the depth, up to 30 m).",
        )
        if default_depth > WIZ_MAX_DEPTH_M:
            st.warning(
                f"The siting result recommends {default_depth:.0f} m, beyond "
                f"the {WIZ_MAX_DEPTH_M:.0f} m this step accepts - it is the "
                "depth the sounding investigated, not a target zone. Check "
                "the interpretation on the Geophysics page, or cost the "
                "planned depth on the Costing & BoQ page, which is unbounded."
            )
        wiz_dist = c3.number_input(
            "Distance from contractor base, one way (km)", 0.0, 1000.0,
            100.0, 10.0, key="wiz_cost_dist",
        )
        if st.button("Estimate the cost", key="wiz_cost_run", type="primary"):
            compute_cost_estimate(
                CostingInputs(
                    total_depth_m=wiz_depth,
                    overburden_m=wiz_over or None,
                    mobilisation_distance_km=wiz_dist,
                ),
                cached_rates(),
            )
        wiz_est = st.session_state.get("cost_estimate")
        if wiz_est is not None:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total cost", f"${wiz_est.total_cost_usd:,.0f}")
            m2.metric("Contract price", f"${wiz_est.price_usd:,.0f}")
            m3.metric("Per metre", f"${wiz_est.cost_per_meter_usd:,.0f}/m")
            st.caption(
                "Using the bundled indicative rates and default "
                "percentages; open the Costing & BoQ page to edit unit rates, "
                "margins, VAT and the bill of quantities."
            )
        col_b, col_n = st.columns([1, 3])
        col_b.button("← Back", key="wiz_back", on_click=_wiz_go, args=(1,))
        col_n.button(
            "Finish →", key="wiz_next", type="primary",
            disabled=wiz_est is None, on_click=_wiz_go, args=(3,),
        )

    else:
        st.subheader("Ready to drill")
        top_interp = _top_interp()
        est = st.session_state.get("cost_estimate")
        summary = [
            f"**Site**: {site.community or 'not set'}"
            + (f", {site.district} District" if site.district else ""),
        ]
        if top_interp is not None:
            summary.append(
                f"**Siting**: drill at {top_interp.sounding_id} to "
                f"{top_interp.max_drilling_depth_m:g} m"
            )
        if est is not None:
            summary.append(
                f"**Budget**: planning budget ${est.budget_usd:,.0f} "
                f"(price ${est.price_usd:,.0f})"
            )
        st.success("\n\n".join(summary))
        st.markdown(
            "**What happens next**\n"
            "1. **Supervision** page: work the checklists from procurement "
            "through drilling to handover; critical items gate acceptance.\n"
            "2. **Borehole design** page: once the drilling log exists, "
            "generate the as-built design (it feeds the costing and the "
            "reports).\n"
            "3. **Pumping test** and **Water quality** pages: safe yield "
            "and the WHO/national verdict.\n"
            "4. **Handover** page: the closing report with the committee "
            "and sign off.\n"
            "5. **Site maps** page: location, geology and aquifer maps for the "
            "reports.\n\n"
            "Save your work with **Project file** in the sidebar - it "
            "carries everything you have entered."
        )
        col_b, col_r = st.columns([1, 3])
        col_b.button("← Back", key="wiz_back", on_click=_wiz_go, args=(2,))
        col_r.button("Start a new guided setup", key="wiz_restart",
                     on_click=_wiz_go, args=(0,))

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
        soundings = parse_upload(read_ves_workbook, path)
        if soundings is None:
            pass
        elif not soundings:
            st.error("No soundings found in the workbook.")
        else:
            st.success(f"Parsed {len(soundings)} sounding(s).")
            for s in soundings:
                show_flags(s.flags)
            show_flags(check_all([(s.sounding_id, s.site) for s in soundings]))

            if st.button("Run inversion and interpretation", key="run_ves",
                         type="primary"):
                run_ves_inversion(soundings)

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
                col_txt.metric(
                    "Model fit (ERR)", f"{result.fit_error_percent:.1f}%",
                    help="Root-mean-square difference between the measured "
                    "curve and the layered model. Under 5% is an excellent "
                    "fit; 5-10% is acceptable; above 10% treat the layer "
                    "depths as indicative and weight the drilling decision "
                    "on the curve shape and local knowledge.",
                )
                col_txt.caption(
                    "Fit: " + _band(
                        result.fit_error_percent,
                        [(5.0, "excellent - depths well constrained"),
                         (10.0, "acceptable for siting")],
                        "poor - treat the layer depths as indicative only",
                    )
                )
                col_txt.metric(
                    "Water bearing zones",
                    ", ".join(f"{int(t)}-{int(b)} m" for t, b in interp.water_zones)
                    or "none",
                )
                col_txt.write(interp.narrative)
        st.subheader("Drilling preference")
        st.table(drilling_preference_table(interps))

        # The headline the client actually asks for, promoted first-class
        _best_interp = min(
            interps, key=lambda i: (i.rank or 99, -i.score),
        ) if interps else None
        if _best_interp is not None and _best_interp.max_drilling_depth_m:
            _zones = ", ".join(
                f"{int(t)}-{int(b)} m" for t, b in _best_interp.water_zones
            )
            st.markdown(
                "<div class='gw-callout'>"
                "<span class='gw-cap'>Recommended drilling depth — "
                f"{_html.escape(_best_interp.sounding_id)}</span>"
                f"<div class='gw-big'>{_best_interp.max_drilling_depth_m:.0f} "
                "<small>m</small></div>"
                + (f"<p>Water bearing zones at {_html.escape(_zones)}.</p>"
                   if _zones else "")
                + "</div>",
                unsafe_allow_html=True,
            )

        with st.expander("🎯 Drill-target suitability (prototype)", expanded=True):
            st.caption(
                "A transparent 0-100 suitability score per point, combining "
                "aquifer thickness, resistivity fit, overburden and any "
                "fracture at the basement contact. It answers 'where should I "
                "drill?' and, as real drilling outcomes accumulate, the weights "
                "can be replaced by a fitted model."
            )
            suitability = assess_siting(interps)
            st.dataframe(
                [
                    {
                        "Rank": s.rank,
                        "Point": s.sounding_id,
                        "Suitability": f"{s.suitability:.0f}/100",
                        "Grade": s.grade,
                        "Why": s.rationale,
                    }
                    for s in suitability
                ],
                hide_index=True,
                width="stretch",
            )
            best = suitability[0]
            st.success(
                f"Recommended drill target: **{best.sounding_id}** "
                f"({best.suitability:.0f}/100, {best.grade}).",
                icon="🎯",
            )
            map_points = suitability_map_points(suitability)
            if map_points:
                zone = site_from_state().utm_zone or 29
                smap = workdir() / "suitability_map.png"
                suitability_map(map_points, zone, path=smap)
                st.image(str(smap))
            else:
                st.info(
                    "Add GPS coordinates to the VES points (sidebar site "
                    "details) to draw the drill-target map."
                )

        if st.button("Build geophysical survey report", key="build_geo_report"):
          with _working("Building the geophysical survey report - drawing the context maps and writing the document..."):
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

    _next_step("Cost this borehole →", "Costing & BoQ",
               "Siting done. Price the borehole at the recommended depth.")

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
        test = parse_upload(
            read_pumping_docx if path.suffix == ".docx" else read_pumping_workbook,
            path,
        )
    if path is not None and test is not None:
        st.success(
            f"Parsed {test.test_type} test with {len(test.steps)} pumping series "
            f"and {'a' if test.recovery_time_min is not None else 'no'} recovery record."
        )
        show_flags(test.flags)

        # The discharge boxes are keyed by step number, so they outlive the
        # sheet they were typed for: opening a second borehole whose sheet
        # also lacks discharges silently reused the first one's rates, and
        # transmissivity, safe yield and pump depth are all proportional to
        # them. Clear them when the source changes - but not on the run a
        # saved project is restored, which brings back both together.
        pump_sig = repr(_source_signature(st.session_state.get("src_pump")))
        if st.session_state.get("pump_source_sig") != pump_sig:
            st.session_state["pump_source_sig"] = pump_sig
            if not st.session_state.get("project_just_loaded"):
                for stale_q in [k for k in list(st.session_state)
                                if k.startswith("q_")]:
                    st.session_state.pop(stale_q, None)

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
        if yr is not None and yr.safe_yield_m3_per_h:
            st.markdown(
                "<div class='gw-callout' style='display:flex;gap:26px;"
                "align-items:center'>"
                "<div><span class='gw-cap'>Recommended safe yield</span>"
                f"<div class='gw-big'>{fmt_num(yr.safe_yield_m3_per_h)} "
                "<small>m³/h</small></div></div>"
                + (
                    "<div><span class='gw-cap'>Pump setting depth</span>"
                    f"<div class='gw-big'>"
                    f"{fmt_num(yr.pump_installation_depth_m)} "
                    "<small>m</small></div></div>"
                    if yr.pump_installation_depth_m else ""
                )
                + "</div>",
                unsafe_allow_html=True,
            )
        if yr is not None and yr.safe_yield_low_m3_per_h is not None:
            st.caption(
                f"Plausible range **{yr.safe_yield_low_m3_per_h:.2g} to "
                f"{yr.safe_yield_high_m3_per_h:.2g} m³/h**. "
                + yr.envelope_basis
            )
        cols = st.columns(4)
        cols[0].metric(
            "Transmissivity",
            f"{analysis.transmissivity_m2_per_day:.1f} m2/day"
            if analysis.transmissivity_m2_per_day
            else "pending",
            help="Aquifer productivity class (BGS Africa Groundwater Atlas "
            "bands for basement aquifers). A handpump serving a village "
            "typically needs about 1 m3/h.",
        )
        if analysis.transmissivity_m2_per_day:
            cols[0].caption(
                _band(
                    analysis.transmissivity_m2_per_day,
                    [(1.0, "very low - handpump only, if at all"),
                     (10.0, "low to moderate - ample for a handpump"),
                     (100.0, "moderate to high - could support a small scheme")],
                    "high - motorised supply feasible",
                )
            )
        if yr is not None:
            cols[1].metric(
                "Available drawdown",
                f"{fmt_num(yr.available_drawdown_m)} m" if yr.available_drawdown_m else "n/a",
            )
            cols[2].metric(
                "Safe yield",
                f"{fmt_num(yr.safe_yield_m3_per_h)} m3/h" if yr.safe_yield_m3_per_h else "pending",
                help="Rate the borehole can be pumped at continuously over "
                "the design period, with the safety factor applied. It rests "
                "on assumed storativity and well radius, so design to the "
                "lower end of the range where the supply must not fail.",
            )
            if yr.safe_yield_m3_per_h:
                cols[2].caption(
                    _band(
                        yr.safe_yield_m3_per_h,
                        [(0.5, "below a handpump's working rate"),
                         (1.0, "marginal for a village handpump")],
                        "comfortable for a handpump supply",
                    )
                )
            cols[3].metric(
                "Pump depth",
                f"{fmt_num(yr.pump_installation_depth_m)} m"
                if yr.pump_installation_depth_m
                else "pending",
            )
            st.caption(yr.basis)

        # --- through the year ------------------------------------------
        # A test measures one day; the borehole has to supply the village on
        # the worst one, and those are months apart.
        st.subheader("Through the year")
        _read_month, _month_note = month_of(test.site.date)
        _choices = [0] + list(range(1, 13))
        _picked = st.selectbox(
            "Month the test was run",
            _choices,
            index=_choices.index(_read_month) if _read_month else 0,
            format_func=lambda m: ("not known" if m == 0 else MONTH_NAMES[m - 1]),
            key="seasonal_month",
            help="The water table is highest at the end of the rains and "
                 "lowest in April or May, so when the test was run changes "
                 "what it proves. Read from the field sheet where it can be.",
        )
        # not named _band: that is a module-level helper used above, and
        # shadowing it here would break the yield bands on the next rerun
        _swing = st.number_input(
            "Annual water-table swing (m)",
            min_value=0.0, max_value=30.0, step=0.5,
            value=float(app_config().pumping.seasonal_allowance_m),
            key="seasonal_range",
            help="Wet-season high to dry-season low in this borehole. A single "
                 "test cannot measure it; two readings six months apart can. "
                 "Every figure below moves with it.",
        )
        if _month_note:
            st.warning(_month_note)
        _seasonal = seasonal_yield(
            analysis, app_config().pumping,
            month=(_picked or None), annual_range_m=_swing)
        if not _seasonal.is_established:
            st.info(_seasonal.pending_reason or
                    "The seasonal projection is not available for this test.")
        else:
            st.write(_seasonal.summary)
            st.dataframe(
                [{"Scenario": sc.title,
                  "Further decline (m)": round(sc.decline_m, 1),
                  "Static level (m)": round(sc.static_water_level_m, 2),
                  "Available drawdown (m)": round(sc.available_drawdown_m, 1)
                  if sc.available_drawdown_m else None,
                  "Safe yield (m3/h)": round(sc.safe_yield_m3_per_h, 2)
                  if sc.safe_yield_m3_per_h else None,
                  "Pump intake (m)": sc.pump_installation_depth_m}
                 for sc in _seasonal.scenarios],
                hide_index=True, width="stretch",
            )
            _loss = _seasonal.dry_season_loss_percent
            if _loss and _loss > 1:
                st.warning(
                    f"By the end of the dry season this borehole yields about "
                    f"{_loss:.0f}% less than it did on the day of the test. "
                    "Size the supply on the dry-season figure."
                )
            if _seasonal.pump_installation_depth_m is not None:
                st.info(
                    "Set the pump intake at "
                    f"{fmt_num(_seasonal.pump_installation_depth_m)} m - deep "
                    "enough for the drought case. The pump is fitted once, and "
                    "one that draws air in a bad year loses the village its "
                    "borehole in the year it is needed most."
                )
            st.caption(
                f"The annual range used is {_seasonal.annual_range_m:.1f} m - "
                f"{_seasonal.range_source}."
            )

        _pump_gate = report_gate("pumping")
        if st.button("Build pumping test report", key="build_pump_report"):
          with _working("Building the pumping test report..."):
            report_path = build_pumping_report(
                PumpingReportInputs(analysis=analysis, figures_dir=workdir(),
                                    readiness=_pump_gate, seasonal=_seasonal),
                workdir() / "Pumping_Test_Report.docx",
                app_config(),
            )
          offer_download(report_path, "Download pumping test report (.docx)")

    _next_step("Assess water quality →", "Water quality",
               "Yield established. Check the water is safe to drink.")

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
    if path is not None and (sample := parse_upload(read_quality_workbook, path)) is not None:
        assessment = assess_sample(sample)
        st.session_state.wq_assessment = assessment
        show_flags(assessment.flags)
        st.subheader("Verdict")
        _state = assessment.verdict_state
        st.markdown(f"**{VERDICT_LONG[_state]}**")
        if _state in ("health_fail", "national_fail"):
            st.error(assessment.verdict)
        elif _state == "indeterminate":
            # Not a warning and never a success: the toolkit is saying it
            # cannot tell, and the operator has to resolve that before the
            # supply is signed off.
            st.info(assessment.verdict)
        elif _state == "aesthetic":
            st.warning(assessment.verdict)
        else:
            st.success(assessment.verdict)

        ph_result = sample.get("pH")
        if ph_result is not None and ph_result.value is not None:
            corrosion = handpump_corrosion_check(ph_result.value)
            if corrosion.passed is False:
                st.warning(f"Handpump corrosion risk ({corrosion.measured}): "
                           f"{corrosion.message}")

        def _wq_value(r) -> str:
            """One text column: mixing floats with "< DL" breaks Arrow."""
            if r.value is None:
                return "< DL" if r.below_detection else ""
            # 10 significant figures: lossless for laboratory values while
            # keeping binary-float artefacts (0.30000000000000004) out
            return f"{r.value:.10g}"

        rows = [
            {
                "Parameter": r.parameter,
                "Value": _wq_value(r),
                "Unit": r.unit,
                "WHO health": r.who_health,
                "National": r.sl_standard,
                "Status": WQ_STATUS_LABELS.get(r.status, r.status),
            }
            for r in assessment.rows
        ]
        st.dataframe(rows, width="stretch")

        # A national exceedance reads as a compliance failure, so say plainly
        # when the limit it was judged against is not yet confirmed.
        if provisional := provisional_national_parameters():
            st.warning(
                f"{PROVISIONAL_NATIONAL_NOTE}\n\n"
                f"Unconfirmed: {', '.join(provisional)}."
            )

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

        _quality_gate = report_gate("quality")
        if st.button("Build water quality report", key="build_wq_report"):
          with _working("Building the water quality report - drawing the Piper and Stiff diagrams..."):
            report_path = build_quality_report(
                QualityReportInputs(assessment=assessment, figures_dir=workdir(),
                                    readiness=_quality_gate),
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
    swl_input = st.number_input("Static water level (m)", min_value=0.0, step=0.1,
                                key="design_swl")
    if path is not None and (log := parse_upload(read_drilling_workbook, path)) is not None:
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
            "The Costing & BoQ page can price this design: casing, screen and "
            "gravel quantities carry over automatically."
        )

# ---------------------------------------------------------------------------
# Depth Spine
# ---------------------------------------------------------------------------
with tab_spine:
    st.header("Depth Spine")
    st.caption(
        "The whole borehole on one depth axis: the cuttings log, the casing "
        "string and the water levels registered against the same ruler, with "
        "the screened intervals editable. Everything shown is computed here, "
        "by the same functions that write the reports."
    )

    spine_log = st.session_state.get("drilling_log")

    if build_spine_view is None:
        st.info(
            "The Depth Spine workspace is not available in this deployment. "
            "Every figure it would show is on the Borehole design, Pumping "
            "test, Water quality and Costing pages."
        )
        if SPINE_ERROR:
            st.caption(f"Workspace unavailable: {SPINE_ERROR}")
    elif spine_log is None:
        st.info(
            "Load a drilling log on the Borehole design page first — the spine "
            "is drawn from the logged hole."
        )
        st.button(
            "Go to Borehole design", key="spine_goto_design",
            on_click=_goto, args=("Borehole design",),
        )
    else:
        analysis = st.session_state.get("pump_analysis")
        assessment = st.session_state.get("wq_assessment")

        # The screens the analyst has placed on the section, if any. Keyed by
        # the borehole so one hole's screens never land on another's.
        spine_key = f"spine_screens_{spine_log.borehole_ref or 'bh'}"
        placed = st.session_state.get(spine_key)

        spine_view = build_spine_view(
            SpineInputs(
                name=spine_log.site.community or "Borehole",
                log=spine_log,
                analysis=analysis,
                assessment=assessment,
                config=CONFIG,
            ),
            screens_m=placed,
        )

        missing = []
        if analysis is None:
            missing.append("a pumping test")
        if assessment is None:
            missing.append("a water quality analysis")
        if missing:
            st.caption(
                "Showing the section and the bill of quantities. Load "
                + " and ".join(missing)
                + " to fill in the remaining stages."
            )

        interactive = component_available()
        result = None

        if interactive:
            result = depth_spine(spine_view, key="spine_workspace")

            # The component reports the intervals it moved; re-deriving them is
            # this script's job, not the browser's.
            if result and "screens" in result:
                incoming = result.get("screens")
                moved = (
                    [(float(a), float(b)) for a, b in incoming] if incoming else None
                )
                if moved != placed:
                    st.session_state[spine_key] = moved
                    st.rerun()
        elif static_build_available():
            # No server to serve a component from - the browser demo. The same
            # workspace goes into an iframe with the payload baked in, and the
            # screens are edited below instead of by dragging. Every figure is
            # still computed by the toolkit; only the gesture changes.
            _spine_iframe(render_static(spine_view), _spine_frame_height(spine_view))
            _spine_screen_editor(spine_view, spine_key, placed)
        else:
            st.warning(
                "The workspace needs either the component build or the static "
                "build. Both ship inside the package, so reinstall with "
                "`pip install --force-reinstall groundwater-toolkit`; in a "
                "source checkout run `npm install && npm run build:all` in "
                "ui/depth-spine/."
            )

        # An analyst-placed design is the project's design: the drawing, the
        # bill of quantities and the completion report all follow from the same
        # object, so a screen moved here is a screen moved everywhere.
        if placed:
            st.session_state.borehole_design = design_borehole(
                log=spine_log,
                static_water_level_m=(
                    analysis.test.static_water_level_m if analysis else None
                ),
                pump_intake_m=(
                    analysis.yield_recommendation.pump_installation_depth_m
                    if analysis and analysis.yield_recommendation
                    else None
                ),
                rules=CONFIG.design,
                screens_m=placed,
            )
            col_note, col_reset = st.columns([4, 1])
            col_note.success(
                "Screens placed on the section. The Borehole design drawing, the "
                "Costing & BoQ page and the completion report now use this design."
            )
            if col_reset.button("Reset", key="spine_reset"):
                del st.session_state[spine_key]
                st.rerun()

        ledger = (result or {}).get("ledger") or {}
        if ledger:
            st.subheader("Decisions signed here")
            labels = {
                "design": "Design",
                "quality": "Water quality",
                "costing": "Costing & BoQ",
            }
            for stage_id, record in ledger.items():
                overridden = record["status"] == "overridden"
                with st.container(border=True):
                    head, meta = st.columns([3, 2])
                    head.markdown(
                        f"**{labels.get(stage_id, stage_id)}** — {record['value']}"
                        + (
                            "  ·  :orange[overridden]"
                            if overridden
                            else "  ·  :green[accepted]"
                        )
                    )
                    meta.caption(f"{record['signatory']} · {record['at']}")
                    if overridden:
                        st.caption(
                            f"Toolkit recommended **{record['recommended']}**. "
                            f"Reason given: {record['reason']}"
                        )
                    if not record["clean"]:
                        st.caption(":orange[Signed with a flag still open.]")
            st.session_state.spine_ledger = ledger

    _next_step("Price this design →", "Costing & BoQ",
               "Next: price the design on the section.",
               key="next_spine_costing")

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
            f"Use the design from the Borehole design page "
            f"({design.total_depth_m:g} m, {design.casing_diameter_in:g} inch casing)",
            value=True,
            key="cost_use_design",
        )

    # a keyed widget ignores a changed value= once it has state, so
    # reset the field when the design source changes or is toggled.
    # The signature is a string so the project file carries it and a
    # loaded project's depth is not wiped by a false "source changed".
    design_sig = (
        f"{bool(use_design)}:"
        f"{float(design.total_depth_m) if design else 0.0:.1f}"
    )
    if st.session_state.get("cost_design_sig") != design_sig:
        st.session_state["cost_design_sig"] = design_sig
        if not st.session_state.get("project_just_loaded"):
            st.session_state.pop("cost_depth", None)

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
                width="stretch",
            )
        except Exception:
            # very old or limited runtimes: show read-only rates instead
            st.dataframe(rate_rows, width="stretch")
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
        compute_cost_estimate(
            inputs, rates,
            overheads_percent=overheads_pct,
            margin_percent=margin_pct,
            contingency_percent=contingency_pct,
            vat_percent=vat_pct,
            exchange_rate_sle_per_usd=fx,
        )

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
            st.dataframe(estimate.boq_rows(), width="stretch")
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

    _next_step("Start supervision →", "Supervision",
               "Budget agreed. Work the checklists as the rig arrives.")

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

    # Only the picked stage's widgets are rendered, and Streamlit discards the
    # state of a widget that a run does not draw. Answering a stage and moving
    # on therefore wiped the answers behind you. The widgets are keyed
    # "chkw_"/"rmkw_" and write through, on change, to the "chk_"/"rmk_" keys
    # that hold the answers and go into the project file; those are plain
    # state, so they survive a stage the run never drew.
    CHK_OPTIONS = ["Pending", "Yes", "No", "N/A"]

    def _store_answer(item_id: str) -> None:
        st.session_state[f"chk_{item_id}"] = st.session_state[f"chkw_{item_id}"]

    def _store_remark(item_id: str) -> None:
        st.session_state[f"rmk_{item_id}"] = st.session_state[f"rmkw_{item_id}"]

    def _responses() -> dict[str, ChecklistResponse]:
        responses: dict[str, ChecklistResponse] = {}
        for item in checklist_items:
            status = st.session_state.get(f"chk_{item.item_id}", "Pending")
            mapped = {"Pending": "pending", "Yes": "yes", "No": "no",
                      "N/A": "na"}.get(status, "pending")
            # a remark typed while the item was No must not linger on a
            # later Yes/N/A answer
            remark = (
                st.session_state.get(f"rmk_{item.item_id}", "")
                if mapped == "no"
                else ""
            )
            responses[item.item_id] = ChecklistResponse(item.item_id, mapped, remark)
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
            saved = st.session_state.get(f"chk_{item.item_id}", "Pending")
            st.radio(
                "Status",
                CHK_OPTIONS,
                index=CHK_OPTIONS.index(saved) if saved in CHK_OPTIONS else 0,
                horizontal=True,
                key=f"chkw_{item.item_id}",
                on_change=_store_answer,
                args=(item.item_id,),
                label_visibility="collapsed",
            )
            if st.session_state.get(f"chk_{item.item_id}") == "No":
                st.text_input(
                    "Remark / action", key=f"rmkw_{item.item_id}",
                    value=st.session_state.get(f"rmk_{item.item_id}", ""),
                    on_change=_store_remark, args=(item.item_id,),
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
                "Templates page."
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

    _next_step("Build the handover →", "Handover",
               "Quality assessed. Close the project out with the community.")

# ---------------------------------------------------------------------------
# Handover
# ---------------------------------------------------------------------------
with tab_handover:
    st.header("Project handover report")
    st.caption(
        "The closing deliverable for the client and the community. Answer "
        "the questions below; results already produced in the other pages "
        "(design, pumping test, water quality) attach automatically."
    )

    design = st.session_state.get("borehole_design")
    log = st.session_state.get("drilling_log")
    pumping = st.session_state.get("pump_analysis")
    quality = st.session_state.get("wq_assessment")
    a1, a2, a3 = st.columns(3)
    a1.metric("Borehole design", "attached" if design is not None else "not yet",
              help="Produce it in the Borehole design page and it attaches here.")
    a2.metric("Pumping test", "attached" if pumping is not None else "not yet",
              help="Analyse a test in the Pumping test page.")
    a3.metric("Water quality", "attached" if quality is not None else "not yet",
              help="Assess a sample in the Water quality page.")
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
        width="stretch",
    )
    # keep a clean, serialisable copy of the committee so it survives reruns
    # and is saved with the project (the data_editor key holds only an edit
    # delta, which is not itself persistable)
    st.session_state["ho_committee_data"] = committee_records(committee_rows)
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

    _handover_gate = report_gate("handover")
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
                readiness=_handover_gate,
                contractor_rep=contractor_rep,
                client_rep=client_rep,
                community_rep=community_rep,
            ),
            workdir() / "Handover_Report.docx",
            app_config(),
        )
        # feeds the lifecycle stepper on the Overview page
        st.session_state["handover_built"] = True
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
# Existing water points (rehabilitate or drill?)
# ---------------------------------------------------------------------------
with tab_waterpoints:
    st.header("Existing water points near the site")
    st.caption(
        "Before drilling, check what is already on the ground. A broken but "
        "improved handpump nearby is usually far cheaper to rehabilitate than "
        "a new borehole, and a working source inside the service radius may "
        "mean the community is already served. Points come live from the "
        "Water Point Data Exchange (WPdx+, CC BY 4.0), so this page needs "
        "internet access; coverage is not exhaustive, so always field-verify."
    )
    site = site_from_state()
    if site.latlon is None:
        st.info(
            "Enter the GPS coordinates (UTM East, North and zone) in the "
            "sidebar site details to look up water points around the site."
        )
    else:
        lat, lon = site.latlon
        st.caption(f"Site at {lat:.5f} N, {abs(lon):.5f} W "
                   f"({site.community or 'unnamed site'}).")
        radius = st.slider(
            "Search radius (m around the site)", 250, 5000,
            int(DEFAULT_SEARCH_RADIUS_M), 250, key="wp_radius",
            help="Existing working sources inside 500 m are treated as "
            "already serving the site.",
        )
        if st.button("Look up water points", key="run_waterpoints",
                     type="primary"):
            try:
                with st.spinner("Querying the Water Point Data Exchange..."):
                    points = water_points_near(lat, lon, float(radius))
            except WaterPointFetchError as exc:
                st.session_state.pop("wp_result", None)
                st.error(
                    f"{exc} Check the internet connection and try again; the "
                    "rest of the toolkit works offline."
                )
            else:
                decision = rehab_vs_drill(points, lat, lon,
                                          search_radius_m=float(radius))
                st.session_state["wp_result"] = {
                    "decision": decision,
                    "rows": [p.as_row() for p in points],
                }
        result = st.session_state.get("wp_result")
        if result:
            decision = result["decision"]
            banner = {
                VERIFY_NEED: st.warning,
                ASSESS_REHAB: st.info,
            }.get(decision["recommendation"], st.success)
            banner(decision["headline"])
            st.write(decision["rationale"])
            summary = decision["summary"]
            cols = st.columns(4)
            cols[0].metric("Points nearby", summary["total"])
            cols[1].metric("Functional", summary["functional"])
            cols[2].metric("Non-functional", summary["non_functional"])
            cols[3].metric(
                "Functional rate",
                f"{summary['functional_rate']:.0f}%"
                if summary["functional_rate"] is not None else "n/a",
            )
            if decision["rehab_candidates"]:
                st.subheader("Rehabilitation candidates")
                st.dataframe(
                    [{k: v for k, v in c.items() if not k.startswith("_")}
                     for c in decision["rehab_candidates"]],
                    width="stretch", hide_index=True,
                )
            if result["rows"]:
                st.subheader("All water points in range")
                st.dataframe(result["rows"], width="stretch",
                             hide_index=True)
            st.caption(WPDX_CREDIT)

# ---------------------------------------------------------------------------
# Coverage gap (population per functional water point, by district)
# ---------------------------------------------------------------------------
with tab_coverage:
    st.header("Water coverage gap by district")
    st.caption(
        "Where are the underserved people? This ranks Sierra Leone's 16 "
        "districts by population per functional water point, joining the 2015 "
        "census district populations (Statistics Sierra Leone) with mapped "
        "water points from the Water Point Data Exchange (WPdx+, CC BY 4.0). "
        "Higher = more people per working source = higher priority. WPDx "
        "coverage is not exhaustive, so treat it as a planning signal, not a "
        "census of points."
    )
    cov_input = st.radio(
        "Water points source",
        ["Upload WPDx CSV export", "Live WPDx (national)"],
        key="cov_source", horizontal=True,
        help="Download your country's export from waterpointdata.org for a "
        "fully offline analysis, or fetch live (needs internet).",
    )
    cov_points = None
    if cov_input == "Upload WPDx CSV export":
        up = st.file_uploader("WPDx CSV export (.csv)", type=["csv"], key="cov_csv")
        if up is not None:
            try:
                cov_points = parse_wpdx_csv(
                    up.getvalue().decode("utf-8", "replace")
                )
            except Exception as exc:  # surfaced to the operator
                st.error(f"Could not read that CSV: {exc}")
    else:
        cov_limit = 200000
        if st.button("Fetch national water points", key="cov_fetch",
                     type="primary"):
            try:
                with st.spinner("Querying the Water Point Data Exchange..."):
                    # a bounding box around the country's centre; a high limit
                    # because a national pull (plus the box's Guinea/Liberia
                    # fringe, which the chiefdom join later discards) is tens of
                    # thousands of points
                    st.session_state["cov_points_raw"] = fetch_water_points(
                        8.46, -11.79, 300000.0, limit=cov_limit
                    )
            except WaterPointFetchError as exc:
                st.session_state.pop("cov_points_raw", None)
                st.error(
                    f"{exc} Try the CSV upload option instead - the rest of "
                    "the toolkit works offline."
                )
        raw = st.session_state.get("cov_points_raw")
        if raw is not None:
            if len(raw) >= cov_limit:
                st.warning(
                    f"The national pull hit the {cov_limit:,}-row cap, so the "
                    "ranking may be partial. Prefer a filtered WPDx CSV export "
                    "for a complete, reproducible analysis."
                )
            cov_points = parse_wpdx_records(raw)

    resolution = st.radio(
        "Resolution", ["District", "Chiefdom"], key="cov_resolution",
        horizontal=True,
        help="District population is exact; chiefdom aggregates the 2015 "
        "census onto the chiefdom polygons (district totals conserved).",
    )
    if cov_points is not None and not cov_points:
        st.warning("No water points found in that source.")
    elif cov_points:
        chiefdom = resolution == "Chiefdom"
        members = None
        rows = None
        grouped = None
        area_population = None
        if chiefdom:
            unit = "chiefdom"
            try:
                counts, unassigned = count_points_by_chiefdom(
                    cov_points, cov_polys()
                )
                grouped, _ = group_points_by_chiefdom(cov_points, cov_polys())
                chief_pop, members = cov_chiefdom_population()
                area_population = chief_pop
                rows = chiefdom_coverage_rows(chief_pop, counts, cov_crosswalk())
            except Exception as exc:  # e.g. a hand-edited crosswalk
                st.error(
                    f"Could not build the chiefdom view: {exc}. "
                    "Fix data/sl_census_crosswalk.csv or use District resolution."
                )
        else:
            unit = "district"
            counts, unassigned = count_points_by_district(
                cov_points, cov_polys(), cov_crosswalk()
            )
            grouped, _ = group_points_by_district(
                cov_points, cov_polys(), cov_crosswalk()
            )
            area_population = cov_population()
            rows = coverage_rows(area_population, counts)
    if cov_points and rows is not None:
        stats = coverage_stats(rows)
        _plan_year = st.number_input(
            "Plan for year", min_value=CENSUS_YEAR, max_value=2050,
            value=max(date.today().year, CENSUS_YEAR), step=1, key="cov_year",
            help="The census is from 2015. A people-per-point figure without "
                 "a year attached is a wrong number nobody notices.",
        )
        _plan_rate = st.number_input(
            "Annual population growth (%)", min_value=0.0, max_value=10.0,
            value=round(DEFAULT_GROWTH_RATE * 100, 2), step=0.1,
            key="cov_rate",
            help="The default is the rate implied by the 2004 and 2015 census "
                 "totals. It is higher than recent international projections; "
                 "use your programme's own figure if you have one.",
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"{unit.title()}s", stats["n_areas"])
        c2.metric(
            "Highest need",
            f"{stats['worst_served_people_per_point']:,.0f}/pt"
            if stats["worst_served_people_per_point"] is not None else "n/a",
            help=f"worst measurable ratio, in {stats['worst_served_area']}"
            if stats["worst_served_area"] else f"no {unit} has a functional "
            "mapped source",
        )
        c3.metric("No mapped source", stats["n_no_source"],
                  help=f"{unit}s with no functional point in WPDx")
        c4.metric(
            "National avg",
            f"{stats['national_people_per_point']:,.0f}/pt"
            if stats["national_people_per_point"] is not None else "n/a",
        )
        # --- planning view -------------------------------------------------
        # The census is a decade old and the survey behind each point is
        # older than it looks. Both are made visible rather than folded into
        # one figure that reads as current.
        _plan_rows, _projection = planning_rows(
            area_population, grouped or {},
            as_of_year=int(_plan_year), rate=_plan_rate / 100.0)
        _plan_stats = planning_stats(_plan_rows, _projection)
        st.caption(_projection.note)
        p1, p2, p3 = st.columns(3)
        p1.metric(
            f"Population {int(_plan_year)}",
            f"{_plan_stats['population']:,.0f}",
            delta=f"{_plan_stats['population'] - _plan_stats['census_population']:+,.0f}"
                  " since the census",
        )
        p2.metric(
            f"People per point ({int(_plan_year)})",
            f"{_plan_stats['national_people_per_point']:,.0f}"
            if _plan_stats["national_people_per_point"] is not None else "n/a",
        )
        p3.metric(
            "...counting recent surveys only",
            f"{_plan_stats['national_people_per_recent_point']:,.0f}"
            if _plan_stats["national_people_per_recent_point"] is not None
            else "n/a",
            help="A point reported functional years ago is evidence about "
                 "then. The gap between these two figures is the size of the "
                 "assumption in the one on the left.",
        )
        if _plan_stats["n_stale_areas"]:
            st.warning(
                f"{_plan_stats['n_stale_areas']} {unit}(s) rest on surveys "
                f"more than {AGEING_YEARS} years old: "
                + ", ".join(_plan_stats["stale_areas"][:8])
                + ("..." if _plan_stats["n_stale_areas"] > 8 else "")
                + ". Their coverage figures describe the year they were "
                "surveyed, not this one."
            )
        if not _plan_stats["n_seasonality_recorded"]:
            st.info(
                f"None of these {_plan_stats['n_seasonality_unknown']:,} "
                "functional points records how many months of the year it "
                "yields water, so dry-season service cannot be separated from "
                "wet-season service. Silence is not a year-round supply."
            )
        else:
            st.caption(
                f"{_plan_stats['n_seasonality_recorded']:,} points record "
                f"their seasonality and {_plan_stats['n_seasonality_unknown']:,} "
                "do not; the dry-season column below is a band between "
                "counting the unrecorded ones and not counting them."
            )
        with st.expander("Planning table: freshness and dry-season service"):
            st.dataframe(
                [{"Rank": r.rank, unit.title(): r.name,
                  f"Population {int(_plan_year)}": int(r.population),
                  "Functional": r.functional_points,
                  "Recently surveyed": r.recent_functional_points,
                  "People / point": round(r.people_per_point)
                  if r.people_per_point is not None else None,
                  "...recent only": round(r.people_per_recent_point)
                  if r.people_per_recent_point is not None else None,
                  "Survey": r.freshness.label,
                  "Year-round points": r.seasonal.n_year_round,
                  "Seasonal points": r.seasonal.n_seasonal}
                 for r in _plan_rows],
                hide_index=True, width="stretch",
            )

        cov_map = workdir() / "coverage_map.png"
        if chiefdom:
            plot_coverage_choropleth(
                choropleth_values(rows), path=cov_map, style=app_config().style,
                title="Water coverage gap by chiefdom",
            )
        else:
            plot_coverage_choropleth(
                expand_district_values(choropleth_values(rows), cov_crosswalk()),
                path=cov_map, style=app_config().style,
                group_labels=cov_crosswalk(),
            )
        st.image(str(cov_map))
        offer_download(cov_map, "Download coverage map")
        st.subheader(f"{unit.title()} ranking (highest unmet need first)")
        st.dataframe(
            [({"Rank": r.rank, unit.title(): r.name}
              | ({"District": r.district} if chiefdom else {})
              | {"Population": int(r.population),
                 "Water points": r.water_points,
                 "Functional": r.functional_points,
                 "People / functional point":
                     round(r.people_per_point) if r.people_per_point is not None
                     else None,
                 "Status": r.status}) for r in rows],
            hide_index=True, width="stretch",
        )
        if unassigned:
            st.caption(
                f"{len(unassigned)} water point(s) fell outside every chiefdom "
                "polygon (border, offshore or simplified geometry) and were "
                "not counted."
            )
        if chiefdom and members:
            aggregated = {gb: names for gb, names in sorted(members.items())
                          if len(names) > 1}
            with st.expander(
                f"How chiefdoms were reconciled ({len(aggregated)} polygons "
                "aggregate 2+ census chiefdoms)"
            ):
                st.caption(
                    "The boundary polygons predate the 2017 chiefdom split, so "
                    "post-2017 census chiefdoms fold into their pre-2017 parent. "
                    "District totals are exact; only which polygon a new "
                    "chiefdom joins is best-effort. Edit "
                    "data/sl_census_crosswalk.csv to correct any assignment."
                )
                st.dataframe(
                    [{"Chiefdom polygon": gb, "Census chiefdoms": ", ".join(names)}
                     for gb, names in aggregated.items()],
                    hide_index=True, width="stretch",
                )
        st.caption(f"{WPDX_CREDIT}. {POPULATION_CREDIT}.")

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

# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------
with tab_portfolio:
    st.header("Borehole portfolio")
    st.caption(
        "See many boreholes side by side. Save a project from the sidebar "
        "(each file carries a short summary), then drop several of them here "
        "for a status map, a comparison table and headline figures - the "
        "programme view a water manager needs."
    )
    files = st.file_uploader(
        "Saved project files (.yaml)", type=["yaml", "yml"],
        accept_multiple_files=True, key="portfolio_upload",
    )
    summaries = []
    skipped = 0
    for uploaded in files or []:
        try:
            updates = deserialize_project(uploaded.getvalue())
        except Exception:
            skipped += 1
            continue
        summary = updates.get("summary")
        if not isinstance(summary, dict) or not summary:
            # an older project file without a summary: fall back to site inputs
            summary = {
                "community": updates.get("meta_community"),
                "district": updates.get("meta_district"),
                "easting": updates.get("meta_easting"),
                "northing": updates.get("meta_northing"),
                "utm_zone": int(str(updates.get("meta_zone") or "29N").rstrip("N")),
            }
        summaries.append(summary)
    if skipped:
        st.warning(f"{skipped} file(s) could not be read as a project and were skipped.")
    if not summaries:
        st.info("Upload two or more saved project files to build the portfolio.")
    else:
        stats = portfolio_stats(summaries)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Projects", stats["n_projects"])
        c2.metric("Successful", stats["n_successful"],
                  help=f"of {stats['n_drilled']} drilled")
        if stats["success_rate"] is not None:
            c3.metric("Success rate", f"{stats['success_rate']:.0f}%")
        if stats["mean_cost_per_meter_usd"] is not None:
            c4.metric("Mean cost/m", f"${stats['mean_cost_per_meter_usd']:.0f}")
        if stats["n_status_unrecognised"]:
            st.warning(
                f"{stats['n_status_unrecognised']} project(s) carry a status "
                "this toolkit does not recognise; they are counted as neither "
                "successful nor dry. Correct the status on the drilling log."
            )
        if stats["n_wq_assessed"]:
            # Three rates, not one. A single "pass rate" counted an aesthetic
            # exceedance as safe and hid national-standard failures inside it.
            w1, w2, w3 = st.columns(3)
            w1.metric(
                "Water: compliant", f"{stats['wq_compliant_rate']:.0f}%",
                help="Meets every health and national limit "
                     f"({stats['n_wq_assessed']} sampled)",
            )
            w2.metric(
                "Water: failing", f"{stats['wq_fail_rate']:.0f}%",
                help="Exceeds a health guideline or a national standard limit",
            )
            w3.metric(
                "Water: unproven", f"{stats['wq_unproven_rate']:.0f}%",
                help="Results incomplete or not evaluable - safety not established",
            )
        points = portfolio_points(summaries)
        if points:
            pmap = workdir() / "portfolio_map.png"
            plot_portfolio_map(points, path=pmap, style=app_config().style)
            st.image(str(pmap))
        else:
            st.info("Add GPS coordinates to the projects to place them on the map.")
        st.subheader("Comparison")
        st.dataframe(
            portfolio_rows(summaries), hide_index=True, width="stretch"
        )

        st.subheader("Site detail")
        st.caption("Drill into one site for its full record and a one-page brief.")
        choice = st.selectbox(
            "Select a site", list(range(len(summaries))),
            format_func=lambda i: site_label(summaries[i], i),
            key="portfolio_site",
        )
        chosen = summaries[choice]
        st.table(
            [{"Field": field, "Value": value}
             for field, value in site_detail(chosen)]
        )
        _brief_name = (chosen.get("community") or "site").strip().replace(" ", "_")
        st.download_button(
            "Download site brief (.txt)", site_one_pager(chosen),
            file_name=f"{_brief_name}_brief.txt", mime="text/plain",
            key="portfolio_onepager",
        )

with tab_registry:
    st.header("Borehole asset registry")
    st.caption(
        "A drilling project ends; the borehole does not. This page holds the "
        "other half: a stable identifier that outlives the project file, the "
        "maintenance history recorded against it, and what that history says "
        "is true today. Nothing here is assumed - a borehole nobody has "
        "reported on is not working, it is unknown."
    )

    _asset = st.session_state.get("asset_record")
    _draft = asset_from_project(_project_state())
    if not _asset and _draft is not None:
        _asset = _draft.as_dict()
    _live = asset_from_dict(_asset) if _asset else None

    st.subheader("This borehole")
    if _live is None:
        st.info(
            "This project has no recorded position yet, so it cannot be given "
            "an identifier - there would be nothing to find the borehole by. "
            "Enter the GPS position in the site details in the sidebar."
        )
    else:
        _state = asset_state(_live)
        _c1, _c2, _c3 = st.columns([2, 1, 1])
        _c1.metric("Identifier", _live.asset_id)
        _c2.metric("Status", _state.label)
        if _state.days_out_of_service is not None:
            _c3.metric("Out of service", f"{_state.days_out_of_service} days")
        st.caption(
            "The identifier is derived from the position, so two teams at the "
            "same wellhead with no connection between them arrive at the same "
            "one. The last character is a check character: it catches every "
            "single mistyped character and every transposition of two."
        )
        st.write(_state.detail)
        _outstanding = [i for i in _state.due if i.state in ("overdue", "unknown")]
        if _outstanding:
            for _item in _outstanding:
                st.warning(_item.detail)
        else:
            for _item in _state.due:
                st.caption(_item.detail)

        with st.form("asset_event_form", clear_on_submit=True):
            st.markdown("**Record what happened**")
            _f1, _f2, _f3 = st.columns([1, 1, 2])
            _when = _f1.date_input("Date", key="asset_event_when")
            _kind = _f2.selectbox(
                "What happened", list(EVENT_KINDS),
                format_func=lambda k: EVENT_KINDS[k][0], key="asset_event_kind")
            _by = _f3.text_input("Recorded by", key="asset_event_by",
                                 placeholder="Name")
            _note = st.text_input("Note", key="asset_event_note",
                                  placeholder="What was found or done")
            if st.form_submit_button("Add to the history"):
                _events = merge_events(
                    _live.asset_id, _live.events,
                    [AssetEvent(when=_when.isoformat(), kind=_kind,
                                note=_note, by=_by)])
                _live.events = _events
                st.session_state["asset_record"] = _live.as_dict()
                st.success("Recorded. The history is append-only: a mistake is "
                           "corrected by recording the correction.")
        st.caption(
            "The history travels inside the saved project file, so a record "
            "kept only in this browser is one bad laptop away from gone."
        )

        if _live.events:
            st.subheader("History")
            st.dataframe(
                [{"Date": e.when or "(no date)", "Event": e.label,
                  "Note": e.note, "Recorded by": e.by} for e in _live.events],
                hide_index=True, width="stretch",
            )

        _r1, _r2 = st.columns(2)
        if _r1.button("Build identification plate (.docx)", key="asset_placard"):
            _inputs = AssetReportInputs(asset=_live, figures_dir=workdir(),
                                        readiness=report_gate("completion"))
            offer_download(
                build_asset_placard(_inputs,
                                    workdir() / f"placard_{_live.asset_id}.docx",
                                    app_config()),
                "Borehole identification plate")
        if _r2.button("Build asset record (.docx)", key="asset_record_report"):
            _inputs = AssetReportInputs(asset=_live, figures_dir=workdir(),
                                        readiness=report_gate("completion"))
            offer_download(
                build_asset_record(_inputs,
                                   workdir() / f"asset_{_live.asset_id}.docx",
                                   app_config()),
                "Borehole asset record")

    st.divider()
    st.subheader("Look up an identifier")
    _typed = st.text_input(
        "Identifier from a headworks plate", key="asset_lookup",
        placeholder="SL-WAR-8FEEVKQ-T")
    if _typed:
        _ok, _reason = validate_asset_id(_typed)
        if _ok:
            st.success(f"That is a valid identifier: {parse_asset_id(_typed)}")
        else:
            st.error(_reason)

    st.divider()
    st.subheader("Many boreholes")
    st.caption(
        "Drop in saved project files to see the whole register: what is "
        "working, what is not, and what is overdue a visit."
    )
    _files = st.file_uploader(
        "Saved project files (.yaml)", type=["yaml", "yml"],
        accept_multiple_files=True, key="registry_upload")
    _assets, _dropped = [], 0
    for _uploaded in _files or []:
        try:
            _updates = deserialize_project(_uploaded.getvalue())
        except Exception:
            _dropped += 1
            continue
        _record = asset_from_dict(_updates.get("asset") or {})
        if _record is None:
            _dropped += 1
            continue
        _assets.append(_record)
    if _dropped:
        st.warning(
            f"{_dropped} file(s) carried no readable asset record and were "
            "skipped. A project file only carries one once the borehole has "
            "been given an identifier on this page."
        )
    if not _assets:
        st.info("Upload saved project files that carry an asset record.")
    else:
        _stats = registry_stats(_assets)
        _s1, _s2, _s3, _s4 = st.columns(4)
        _s1.metric("Boreholes", _stats["n_assets"])
        _s2.metric("Working", _stats["n_functional"])
        _s3.metric("Not working", _stats["n_non_functional"])
        _s4.metric("Condition unknown", _stats["n_unknown"])
        if _stats["functionality_rate"] is not None:
            st.metric("Functionality rate", f"{_stats['functionality_rate']:.0f}%",
                      help="Over the boreholes whose condition is actually "
                           "known. A rate computed over silence is the number "
                           "that makes these registers untrustworthy.")
        if _stats["n_unknown"]:
            st.warning(
                f"{_stats['n_unknown']} borehole(s) have nothing recorded "
                "against them at all. That is not the same as nothing having "
                "happened to them."
            )
        _chase = _stats["n_overdue_inspection"] + _stats["n_overdue_sample"]
        if _chase:
            st.info(
                f"{_stats['n_overdue_inspection']} overdue a sanitary "
                f"inspection, {_stats['n_overdue_sample']} overdue a water "
                "quality sample."
            )
        st.dataframe(registry_rows(_assets), hide_index=True, width="stretch")


with tab_procurement:
    st.header("Procurement: planned against actual")
    st.caption(
        "A bill of quantities is an estimate until somebody signs it, and a "
        "contract afterwards. This page tracks what was measured against what "
        "was authorised, records the variation orders that move the line, and "
        "produces the interim payment certificate. Work that was done but "
        "nobody authorised is shown and withheld - not because it was "
        "unnecessary, but because paying for it is a decision somebody signs."
    )

    _estimate = st.session_state.get("cost_estimate")
    _contract_lines = st.session_state.get("proc_contract_lines")
    if _contract_lines is None and _estimate is not None:
        st.info(
            "The cost estimate from the Costing page is not a contract until "
            "it is awarded. Freeze it here and the certificate is measured "
            "against the frozen copy, so a later change to the design cannot "
            "move what was signed."
        )
    a1, a2, a3 = st.columns([2, 1, 1])
    _ref = a1.text_input("Contract reference", key="proc_ref",
                         placeholder="WSD/2024/017")
    _retention = a2.number_input("Retention (%)", min_value=0.0, max_value=25.0,
                                 value=10.0, step=0.5, key="proc_retention")
    _advance = a3.number_input("Advance (%)", min_value=0.0, max_value=50.0,
                               value=0.0, step=5.0, key="proc_advance")
    if _estimate is not None and st.button("Award this estimate as the contract",
                                           key="proc_award"):
        _frozen = contract_from_estimate(
            _estimate, ref=_ref or "(unreferenced)",
            contractor=st.session_state.get("meta_contractor", ""),
            client=st.session_state.get("meta_client", ""),
            retention_percent=_retention, advance_percent=_advance)
        st.session_state["proc_contract_lines"] = [
            line.as_dict() for line in _frozen.lines]
        st.success(
            f"Contract frozen at ${_frozen.sum_usd:,.0f} across "
            f"{len(_frozen.lines)} lines.")
        _contract_lines = st.session_state["proc_contract_lines"]

    if not _contract_lines:
        st.info(
            "No contract yet. Build a cost estimate on the Costing & BoQ page, "
            "then award it here."
        )
    else:
        _contract = Contract(
            ref=_ref or "(unreferenced)",
            contractor=st.session_state.get("meta_contractor", ""),
            client=st.session_state.get("meta_client", ""),
            lines=[ContractLine(
                code=row["code"], item=row["item"], unit=row["unit"],
                quantity=float(row["quantity"]),
                rate_usd=float(row["rate_usd"]),
                stage=row.get("stage", ""), category=row.get("category", ""))
                for row in _contract_lines],
            retention_percent=_retention, advance_percent=_advance)
        st.metric("Contract sum", f"${_contract.sum_usd:,.0f}")

        st.subheader("Measured to date")
        st.caption(
            "Cumulative quantities, not increments: this is everything done "
            "so far on each line. The certificate works out what is new."
        )
        _measured_rows = st.data_editor(
            st.session_state.get("proc_measured") or [
                {"Code": line.code, "Item": line.item, "Unit": line.unit,
                 "Contract": line.quantity, "Measured to date": 0.0}
                for line in _contract.lines],
            key="proc_measure_editor", hide_index=True, width="stretch",
            disabled=["Code", "Item", "Unit", "Contract"],
        )
        st.session_state["proc_measured"] = (
            _measured_rows.to_dict("records")
            if hasattr(_measured_rows, "to_dict") else list(_measured_rows))

        st.subheader("Variation orders")
        st.caption(
            "A variation is what makes extra work payable. It needs a reason "
            "and a name: an unsigned variation is a request, not an "
            "instruction."
        )
        _variation_rows = st.data_editor(
            st.session_state.get("proc_variations") or [
                {"Ref": "", "Date": "", "Code": "", "Quantity change": 0.0,
                 "New rate (USD)": None, "Reason": "", "Authorised by": ""}],
            key="proc_variation_editor", hide_index=True, width="stretch",
            num_rows="dynamic",
        )
        st.session_state["proc_variations"] = (
            _variation_rows.to_dict("records")
            if hasattr(_variation_rows, "to_dict") else list(_variation_rows))

        st.subheader("Certificate")
        c1, c2, c3 = st.columns(3)
        _number = c1.number_input("Certificate number", min_value=1, step=1,
                                  value=1, key="proc_number")
        _cert_date = c2.text_input("Date", key="proc_date",
                                   placeholder="2024-04-01")
        _previous = c3.number_input(
            "Previously certified (USD)", min_value=0.0, step=100.0, value=0.0,
            key="proc_previous",
            help="Everything net-certified on earlier certificates. Leave it "
                 "at zero on a later certificate and the contractor is paid "
                 "for that work twice.")

        _measurements = [
            Measurement(code=str(row.get("Code") or ""),
                        quantity=float(row.get("Measured to date") or 0.0))
            for row in st.session_state["proc_measured"]
            if str(row.get("Code") or "").strip()
        ]
        _variations = [
            Variation(
                ref=str(row.get("Ref") or ""), date=str(row.get("Date") or ""),
                code=str(row.get("Code") or ""),
                quantity_delta=float(row.get("Quantity change") or 0.0),
                rate_usd=(float(row["New rate (USD)"])
                          if row.get("New rate (USD)") not in (None, "") else None),
                reason=str(row.get("Reason") or ""),
                authorised_by=str(row.get("Authorised by") or ""))
            for row in st.session_state["proc_variations"]
            if str(row.get("Code") or "").strip()
        ]
        _certificate = certify(
            _contract, _measurements, number=int(_number),
            date=_cert_date or "(undated)", variations=_variations,
            previously_certified_usd=float(_previous))

        for _problem in _certificate.problems:
            st.warning(_problem)
        st.success(_certificate.summary)
        st.dataframe(
            [{"": label, " ": value}
             for label, value in contract_summary(_contract, _certificate)],
            hide_index=True, width="stretch",
        )
        if _certificate.overmeasure_usd:
            st.error(
                f"${_certificate.overmeasure_usd:,.0f} of work has been "
                "measured but not authorised, so it is not certified here. "
                "Record a variation order against those lines and it becomes "
                "payable on the next certificate."
            )
        st.dataframe(
            [{"Code": line.code, "Item": line.item, "Unit": line.unit,
              "Contract": line.contract_quantity,
              "Varied": line.variation_quantity,
              "Authorised": line.authorised_quantity,
              "Measured": line.measured_quantity,
              "Payable": line.payable_quantity,
              "Rate": round(line.rate_usd, 2),
              "Amount (USD)": round(line.payable_amount_usd),
              "% done": round(line.percent_complete)
              if line.percent_complete is not None else None}
             for line in _certificate.lines],
            hide_index=True, width="stretch",
        )
        if st.button("Build interim payment certificate (.docx)",
                     key="proc_build"):
            with _working("Building the certificate..."):
                _path = build_payment_certificate(
                    PaymentCertificateInputs(
                        contract=_contract, certificate=_certificate,
                        prepared_by=st.session_state.get("meta_supervisor", ""),
                        readiness=report_gate("costing")),
                    workdir() / f"IPC_{int(_number)}.docx", app_config())
            offer_download(_path,
                           f"Interim payment certificate {int(_number)}")


# ---------------------------------------------------------------------------
# Deliverables, filled last for the same reason: the Overview renders before
# the pages that build the files.
# ---------------------------------------------------------------------------
_built = _deliverables()
if _built:
    with _deliverables_slot:
        st.divider()
        st.subheader("📦 Deliverables")
        st.caption(
            f"{len(_built)} file(s) built this session. They live only in this "
            "session - download what you need before closing the tab, or save "
            "the project file and rebuild them later."
        )
        for _i, (_label, _path) in enumerate(_built):
            _c1, _c2 = st.columns([3, 1])
            _c1.write(f"**{_path.name}**  \n{_label}")
            with open(_path, "rb") as _fh:
                _c2.download_button(
                    "Download", _fh.read(), file_name=_path.name,
                    key=f"deliverable_{_i}", width="stretch",
                )


# ---------------------------------------------------------------------------
# Sidebar project file panel, filled last so the saved file carries the
# results this run produced rather than the state the sidebar started with.
# ---------------------------------------------------------------------------
with _project_panel:
    st.caption(
        "Save the whole project - your inputs, the WASH committee and the "
        "uploaded data files - and load it back later or on another "
        "machine to restore the analyses and reports. Saved projects can "
        "also be combined on the Portfolio page."
    )
    # capture a headline summary so the saved file feeds the portfolio view
    st.session_state["project_summary"] = _project_summary()
    # and the asset identifier, so a located borehole carries one into the
    # registry without anybody having to visit that page first
    if not st.session_state.get("asset_record"):
        _drafted = asset_from_project(_project_state())
        if _drafted is not None:
            st.session_state["asset_record"] = _drafted.as_dict()
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

# the post-load grace flag protects restored inputs for exactly one
# full run; every page has rendered by this point
st.session_state.pop("project_just_loaded", None)

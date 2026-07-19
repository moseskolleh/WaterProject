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
from groundwater.geo import geographic_to_utm, utm_to_geographic
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
from groundwater.coverage import (
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
from groundwater.portfolio import (
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
)
from groundwater.recompute import recompute_results
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


def offer_download(path: Path, label: str) -> None:
    with open(path, "rb") as fh:
        st.download_button(label, fh.read(), file_name=path.name)


def parse_upload(reader, path: Path):
    """Run a parser on an uploaded file, surfacing failures as errors.

    A malformed or mislabelled workbook should show a readable message
    instead of crashing the tab.
    """
    try:
        return reader(path)
    except Exception as exc:
        st.error(
            f"Could not read {path.name}: {exc}. Check that the file "
            "follows the standard template (Templates tab)."
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
        utm_zone=int(get("meta_zone", "29N").rstrip("N")),
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
        summary["water_verdict"] = (
            "fail" if wq.health_exceedances
            else "aesthetic" if wq.aesthetic_exceedances else "pass"
        )
    cost = st.session_state.get("cost_estimate")
    if cost is not None:
        summary["cost_per_meter_usd"] = cost.cost_per_meter_usd
    if "ves_results" in st.session_state and "status" not in summary:
        summary["status"] = "sited"
    return {k: v for k, v in summary.items() if v not in (None, "")}


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
        parts = [
            p for p in raw.replace(";", ",").replace(" ", ",").split(",")
            if p and p.upper() not in ("N", "S", "E", "W")
        ]
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            st.session_state["latlon_error"] = (
                "Could not read those coordinates. Enter 'lat, lon' in decimal "
                "degrees, for example 8.4657, -13.2317."
            )
            return
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
    for stale in [
        k for k in list(st.session_state)
        if k.startswith(("src_", "q_")) or k == "design_swl"
    ]:
        st.session_state.pop(stale, None)
    for result_key in (
        "ves_results", "pump_analysis", "wq_assessment", "borehole_design",
        "drilling_log", "cost_estimate", "cost_artifacts",
    ):
        st.session_state.pop(result_key, None)
    overrides = updates.pop("rates_overrides", None)
    committee = updates.pop("committee", None)
    sources = updates.pop("sources", None)
    for key, value in updates.items():
        st.session_state[key] = value
    if isinstance(overrides, dict):
        st.session_state.rates_overrides = overrides
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
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 💧 Groundwater Toolkit")
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
    if _probe.community and _probe.latlon is not None:
        st.success(
            f"Site: {_probe.community}"
            + (f", {_probe.district} District" if _probe.district else ""),
            icon="📍",
        )
    else:
        st.warning(
            "Set the site details below - community, area and GPS - or "
            "load a saved project file. Every tab, map and report uses "
            "them.",
            icon="📍",
        )
    with st.expander("📍 Site details (used by all tabs)", expanded=True):
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
                      placeholder="8.4657, -13.2317")
        st.button("Convert to UTM", on_click=_apply_latlon,
                  use_container_width=True)
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
            "1. **VES survey** - siting and drilling depth\n"
            "2. **Costing** - budget and bill of quantities\n"
            "3. **Supervision** - checklists while drilling\n"
            "4. **Borehole design** - from the drilling log\n"
            "5. **Pumping test** - safe yield and pump depth\n"
            "6. **Water quality** - WHO/national verdict\n\n"
            "Every tab offers bundled sample data, so you can try "
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
    with st.expander("💾 Project file"):
        st.caption(
            "Save the whole project - your inputs, the WASH committee and the "
            "uploaded data files - and load it back later or on another "
            "machine to restore the analyses and reports. Saved projects can "
            "also be combined in the Portfolio tab."
        )
        # capture a headline summary so the saved file feeds the portfolio view
        st.session_state["project_summary"] = _project_summary()
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

# After loading a project, rebuild the analysis objects from the saved data
# files so the tabs and reports are populated without re-uploading.
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
        except Exception:
            st.warning(
                "Some analyses could not be rebuilt from the loaded project. "
                "Re-upload the data files on the affected tabs if needed."
            )

(
    tab_guide,
    tab_ves,
    tab_cost,
    tab_supervision,
    tab_design,
    tab_pump,
    tab_quality,
    tab_handover,
    tab_maps,
    tab_waterpoints,
    tab_coverage,
    tab_extract,
    tab_templates,
    tab_portfolio,
) = st.tabs(
    [
        "🚀 Guided start",
        "📈 VES survey",
        "💰 Costing",
        "✅ Supervision",
        "🛠️ Borehole design",
        "⏱️ Pumping test",
        "🧪 Water quality",
        "🤝 Handover",
        "🗺️ Maps",
        "🚱 Water points",
        "📊 Coverage gap",
        "📄 Scanned sheets",
        "📋 Templates",
        "📁 Portfolio",
    ]
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
# Guided start
# ---------------------------------------------------------------------------
with tab_guide:
    _WIZ_STEPS = ("Site details", "Siting (VES)", "Costing", "Ready to drill")
    wiz_step = int(st.session_state.get("wiz_step", 0))

    st.header("Guided project setup")
    st.caption(
        "Three short steps to a sited, costed borehole project. Every "
        "result carries over to the full tabs, where you can fine tune."
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
                help="Best ranked sounding; see the VES survey tab for "
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
        wiz_depth = c1.number_input("Total depth (m)", 1.0, 300.0,
                                    default_depth or 60.0, 1.0,
                                    key="wiz_cost_depth")
        wiz_over = c2.number_input(
            "Overburden (m)", 0.0, 300.0, default_over, 1.0,
            key="wiz_cost_over",
            help="0 applies the rule of thumb (half the depth, up to 30 m).",
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
                "percentages; open the Costing tab to edit unit rates, "
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
            "1. **Supervision** tab: work the checklists from procurement "
            "through drilling to handover; critical items gate acceptance.\n"
            "2. **Borehole design** tab: once the drilling log exists, "
            "generate the as-built design (it feeds the costing and the "
            "reports).\n"
            "3. **Pumping test** and **Water quality** tabs: safe yield "
            "and the WHO/national verdict.\n"
            "4. **Handover** tab: the closing report with the committee "
            "and sign off.\n"
            "5. **Maps** tab: location, geology and aquifer maps for the "
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
                col_txt.metric("Model fit (ERR)", f"{result.fit_error_percent:.1f}%")
                col_txt.metric(
                    "Water bearing zones",
                    ", ".join(f"{int(t)}-{int(b)} m" for t, b in interp.water_zones)
                    or "none",
                )
                col_txt.write(interp.narrative)
        st.subheader("Drilling preference")
        st.table(drilling_preference_table(interps))

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
                use_container_width=True,
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
    if path is not None and (sample := parse_upload(read_quality_workbook, path)) is not None:
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
# Existing water points (rehabilitate or drill?)
# ---------------------------------------------------------------------------
with tab_waterpoints:
    st.header("Existing water points near the site")
    st.caption(
        "Before drilling, check what is already on the ground. A broken but "
        "improved handpump nearby is usually far cheaper to rehabilitate than "
        "a new borehole, and a working source inside the service radius may "
        "mean the community is already served. Points come live from the "
        "Water Point Data Exchange (WPdx+, CC BY 4.0), so this tab needs "
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
                    use_container_width=True, hide_index=True,
                )
            if result["rows"]:
                st.subheader("All water points in range")
                st.dataframe(result["rows"], use_container_width=True,
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
        if chiefdom:
            unit = "chiefdom"
            try:
                counts, unassigned = count_points_by_chiefdom(
                    cov_points, cov_polys()
                )
                chief_pop, members = cov_chiefdom_population()
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
            rows = coverage_rows(cov_population(), counts)
    if cov_points and rows is not None:
        stats = coverage_stats(rows)
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
            hide_index=True, use_container_width=True,
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
                    hide_index=True, use_container_width=True,
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
        points = portfolio_points(summaries)
        if points:
            pmap = workdir() / "portfolio_map.png"
            plot_portfolio_map(points, path=pmap, style=app_config().style)
            st.image(str(pmap))
        else:
            st.info("Add GPS coordinates to the projects to place them on the map.")
        st.subheader("Comparison")
        st.dataframe(
            portfolio_rows(summaries), hide_index=True, use_container_width=True
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

# the post-load grace flag protects restored inputs for exactly one
# full run; every tab has rendered by this point
st.session_state.pop("project_just_loaded", None)

"""Groundwater toolkit web interface.

Lets the field team upload data files in the standard templates and
produces the analysis figures and client-ready reports without
touching code. Covers the full project lifecycle: VES siting surveys,
pumping tests, water quality, borehole design, cost estimation and
drilling supervision checklists.

Run from the repository root:

    streamlit run app/streamlit_app.py

This file is the frame every page shares: the page set-up and styles, the
rebuild after a project is loaded, the sidebar, and the navigation that
picks the one page to run. Each page is a function in ``app/views/``,
the helpers they share are in ``app/shared.py``, and the session state
they share is described in ``app/state.py``. Only the page on screen runs
(PLAN.md step 1.1); before, every page ran on every rerun and was hidden.
"""

from __future__ import annotations

import html as _html
import sys
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
# The pages and the helpers they share sit beside this file. Streamlit puts
# the script's folder on the path when it runs one, but AppTest and the
# browser demo are not obliged to, so it is put there here.
_APP = Path(__file__).resolve().parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import streamlit as st

import groundwater
from groundwater.geo import (
    infer_zone_for_sierra_leone,
    parse_utm_zone,
    utm_to_geographic,
)
from groundwater.mapping import chiefdom_of, district_of
from groundwater.registry import asset_from_project
from groundwater.recompute import recompute_results

import state
from views import page_functions
from shared import (
    _BRAND_DIR,
    _ICON,
    _LOGO,
    CONFIG,
    DEFAULT_PAGE,
    IN_BROWSER,
    NAV_GROUPS,
    _apply_latlon,
    _group_key,
    _load_project,
    _loaded_sources,
    _nav_changed,
    _project_state,
    _project_summary,
    _status_chip,
    cached_districts,
    fill_defaults,
    project_file_bytes,
    refresh_derived,
    sample_data_dir,
    site_from_state,
    workdir,
)

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

# Design language: the sustaintheworld style. A near-black ground with
# cards one step lighter, one neon green accent, Space Grotesk for headings
# and controls, Inter for text and IBM Plex Mono for the small uppercase
# labels. The printed reports keep their own house style (config.HouseStyle).
# The colours the pages draw with are named in shared.py.


@st.cache_resource(show_spinner=False)
def _font_faces() -> str:
    """The three faces as @font-face rules with the files inlined.

    They ship as package data (Latin subsets, SIL Open Font License, see
    THIRD_PARTY_NOTICES.md), so the app sets its type without a request
    to a font service - it works offline and in the browser demo alike.
    A missing file falls through to the system stack in the rules below.
    """
    import base64

    faces = (
        ("Space Grotesk", "400 700", "space-grotesk-latin.woff2"),
        ("Inter", "400 600", "inter-latin.woff2"),
        ("IBM Plex Mono", "400", "ibm-plex-mono-latin-400.woff2"),
        ("IBM Plex Mono", "500", "ibm-plex-mono-latin-500.woff2"),
    )
    rules = []
    for family, weight, name in faces:
        path = _BRAND_DIR / "fonts" / name
        if not path.exists():
            continue
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        rules.append(
            f"@font-face{{font-family:'{family}';font-style:normal;"
            f"font-weight:{weight};font-display:swap;"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');}}"
        )
    return "".join(rules)


st.markdown(
    "<style>" + _font_faces() + "</style>",
    unsafe_allow_html=True,
)

st.markdown(
    """
    <style>
      html, body, [data-testid="stAppViewContainer"], .stMarkdown,
      button, input, textarea, select {
        font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
      }
      h1, h2, h3, h4,
      [data-testid="stMetricValue"] {
        font-family: 'Space Grotesk', 'Segoe UI', sans-serif !important;
        font-weight: 700; line-height: 1.15; letter-spacing: 0.01em;
        color: #ffffff;
      }
      code, pre, kbd { font-family: 'IBM Plex Mono', monospace; }
      a { color: #7CFC00; transition: all 0.3s ease; }
      a:hover { color: #9FFF4D; }

      .block-container { padding-top: 2.4rem; }
      [data-testid="stAppViewContainer"] h1 {
        font-size: 1.75rem; text-transform: uppercase; margin-bottom: 0.1rem;
      }
      [data-testid="stAppViewContainer"] h2 { font-size: 1.3rem; }
      [data-testid="stAppViewContainer"] h3 { font-size: 1.05rem; font-weight: 600; }

      /* Pill buttons: the primary is the green one, the rest are bordered */
      .stButton > button, .stDownloadButton > button,
      [data-testid="stFormSubmitButton"] > button {
        font-family: 'Space Grotesk', sans-serif; font-weight: 600;
        font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase;
        border-radius: 999px; padding: 0.45rem 1.1rem;
        transition: all 0.3s ease;
      }
      .stButton > button:hover, .stDownloadButton > button:hover,
      [data-testid="stFormSubmitButton"] > button:hover {
        transform: translateY(-3px);
      }
      .stButton > button[kind="primary"],
      [data-testid="stFormSubmitButton"] > button[kind="primary"] {
        color: #051000;
      }
      .stButton > button[kind="primary"]:hover {
        box-shadow: 0 10px 30px rgba(124, 252, 0, 0.3);
      }

      /* Inputs on the darker card surface with the green focus ring */
      [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
      [data-testid="stTextArea"] textarea,
      [data-baseweb="select"] > div, [data-baseweb="input"] {
        background: #141414 !important; border-radius: 8px;
      }
      [data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within,
      [data-baseweb="textarea"]:focus-within {
        box-shadow: 0 0 0 3px rgba(124, 252, 0, 0.12);
      }

      /* Result cards: one step lighter than the ground, hairline in green */
      div[data-testid="stMetric"] {
        background: #1a1a1a;
        border: 1px solid rgba(124, 252, 0, 0.08);
        border-radius: 12px;
        padding: 0.75rem 0.95rem;
        box-shadow: 0 8px 30px rgba(124, 252, 0, 0.1);
        transition: all 0.3s ease;
      }
      div[data-testid="stMetric"]:hover { border-color: rgba(124, 252, 0, 0.18); }
      div[data-testid="stMetric"] label p {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.68rem; font-weight: 500;
        text-transform: uppercase; letter-spacing: 0.08em;
        color: #b0b0b0;
      }
      div[data-testid="stSidebarUserContent"] .stCaption p { line-height: 1.35; }

      /* Expanders, tabs and tables pick up the same hairline and label */
      [data-testid="stExpander"] details {
        border: 1px solid rgba(124, 252, 0, 0.08); border-radius: 12px;
        background: #1a1a1a;
      }
      [data-testid="stExpander"] summary p {
        font-family: 'Space Grotesk', sans-serif; font-weight: 600;
        letter-spacing: 0.02em;
      }
      .stTabs [data-baseweb="tab"] {
        font-family: 'Space Grotesk', sans-serif; font-size: 0.78rem;
        font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase;
      }
      .stTabs [data-baseweb="tab-highlight"] { background-color: #7CFC00; }
      [data-testid="stDataFrame"], [data-testid="stTable"] {
        border-radius: 12px; overflow: hidden;
      }

      /* Sidebar: brand, active-project card and grouped navigation */
      section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(124, 252, 0, 0.08);
      }
      section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"] {
        padding-top: 1.1rem;
      }
      /* Group label above each navigation radio */
      section[data-testid="stSidebar"] .stRadio
        [data-testid="stWidgetLabel"] p {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.62rem; font-weight: 500;
        text-transform: uppercase; letter-spacing: 0.11em;
        color: #8c8c8c;
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
        width: 100%; margin: 0 0 2px; padding: 7px 10px;
        border-radius: 8px; cursor: pointer;
        border-left: 2px solid transparent;
        transition: all 0.3s ease;
      }
      section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover,
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"]:hover {
        transform: translateX(4px);
      }
      section[data-testid="stSidebar"] label[data-testid="stRadioOption"]
        > div > div > div:first-child,
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"] > div:first-of-type {
        width: 6px; height: 6px; min-width: 6px; min-height: 6px;
        margin-right: 10px; border-width: 0; border-radius: 50%;
        background: rgba(124, 252, 0, 0.18);
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
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.78rem; font-weight: 500; letter-spacing: 0.06em;
        text-transform: uppercase; color: #b0b0b0;
      }
      section[data-testid="stSidebar"]
        label[data-testid="stRadioOption"][data-selected="true"] {
        background: rgba(124, 252, 0, 0.1); border-left-color: #7CFC00;
      }
      section[data-testid="stSidebar"]
        label[data-testid="stRadioOption"][data-selected="true"]
        > div > div > div:first-child {
        background: #7CFC00;
      }
      section[data-testid="stSidebar"]
        label[data-testid="stRadioOption"][data-selected="true"] p {
        font-weight: 600; color: #7CFC00;
      }
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"]:has(input:checked) {
        background: rgba(124, 252, 0, 0.1); border-left-color: #7CFC00;
      }
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"]:has(input:checked) > div:first-of-type {
        background: #7CFC00;
      }
      section[data-testid="stSidebar"] div[role="radiogroup"]
        label[data-baseweb="radio"]:has(input:checked)
        div[data-testid="stMarkdownContainer"] p {
        font-weight: 600; color: #7CFC00;
      }
      section[data-testid="stSidebar"] .stRadio { margin-bottom: 0.35rem; }

      /* Shared design pieces (overview dashboard, callouts, chips) */
      .gw-brand { display: flex; align-items: center; gap: 10px; }
      .gw-brand-mark {
        width: 30px; height: 30px; border-radius: 8px; background: #7CFC00;
        display: flex; align-items: center; justify-content: center;
        color: #051000; font: 700 15px 'Space Grotesk', sans-serif;
      }
      .gw-brand-name {
        font: 700 14px 'Space Grotesk', sans-serif; color: #ffffff;
        letter-spacing: 0.04em; text-transform: uppercase; line-height: 1.15;
      }
      .gw-brand-sub {
        font: 400 9.5px 'IBM Plex Mono', monospace;
        color: #8c8c8c; letter-spacing: 0.08em;
      }
      .gw-project-card {
        background: #1a1a1a; border: 1px solid rgba(124, 252, 0, 0.08);
        border-radius: 12px; padding: 10px 12px; margin: 4px 0 6px;
      }
      .gw-cap {
        font: 500 10px 'IBM Plex Mono', monospace;
        text-transform: uppercase; letter-spacing: 0.08em;
        color: #b0b0b0;
      }
      .gw-chip {
        display: inline-block; font: 500 10px 'IBM Plex Mono', monospace;
        text-transform: uppercase; letter-spacing: 0.06em;
        border-radius: 999px; padding: 3px 10px; vertical-align: middle;
      }
      .gw-chip-green { color: #7CFC00; background: rgba(124, 252, 0, 0.12); }
      .gw-chip-amber { color: #f2b705; background: rgba(242, 183, 5, 0.14); }
      .gw-chip-red { color: #e07a5f; background: rgba(224, 122, 95, 0.16); }
      .gw-chip-grey { color: #b0b0b0; background: rgba(255, 255, 255, 0.08); }
      .gw-chip-blue { color: #2ea3e0; background: rgba(46, 163, 224, 0.14); }
      .gw-card {
        background: #1a1a1a; border: 1px solid rgba(124, 252, 0, 0.08);
        border-radius: 12px; padding: 15px 16px;
        box-shadow: 0 8px 30px rgba(124, 252, 0, 0.1);
        margin-bottom: 14px; transition: all 0.3s ease;
      }
      .gw-card:hover { border-color: rgba(124, 252, 0, 0.18); }
      .gw-card .gw-cap { display: block; margin-bottom: 8px; }
      .gw-big {
        font: 700 26px 'Space Grotesk', sans-serif; color: #ffffff;
        line-height: 1.1;
      }
      .gw-big small {
        font: 500 12px 'IBM Plex Mono', monospace; color: #b0b0b0;
      }
      .gw-row {
        display: flex; justify-content: space-between; gap: 10px;
        font-size: 0.78rem; color: #b0b0b0; padding: 2.5px 0;
      }
      .gw-row b { color: #ffffff; font-weight: 500;
        font-family: 'IBM Plex Mono', monospace; }
      .gw-callout {
        background: #7CFC00; border-radius: 12px; padding: 15px 17px;
        color: #051000; margin: 4px 0 12px;
        box-shadow: 0 8px 30px rgba(124, 252, 0, 0.2);
      }
      .gw-callout .gw-cap { color: rgba(5, 16, 0, 0.7); }
      .gw-callout .gw-big { color: #051000; }
      .gw-callout .gw-big small { color: rgba(5, 16, 0, 0.65); }
      .gw-callout p {
        margin: 4px 0 0; font-size: 0.75rem; line-height: 1.4;
        color: rgba(5, 16, 0, 0.82);
      }
      .gw-steps { display: flex; align-items: flex-start; margin: 6px 0 4px; }
      .gw-step { display: flex; flex-direction: column; align-items: center;
        gap: 5px; flex: none; min-width: 58px; }
      .gw-step-dot {
        width: 26px; height: 26px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font: 500 12px 'IBM Plex Mono', monospace;
      }
      .gw-step-done .gw-step-dot { background: #7CFC00; color: #051000; }
      .gw-step-todo .gw-step-dot {
        background: #141414; border: 2px dashed rgba(124, 252, 0, 0.45);
        color: #7CFC00; font-size: 11px;
      }
      .gw-step-label { font-size: 0.68rem; font-weight: 600; color: #ffffff;
        font-family: 'Space Grotesk', sans-serif; letter-spacing: 0.04em;
        text-transform: uppercase; }
      .gw-step-todo .gw-step-label { color: #8c8c8c; }
      .gw-step-line { flex: 1; height: 2px; background: #7CFC00;
        margin: 12px 6px 0; }
      .gw-step-line-todo {
        background: repeating-linear-gradient(90deg, rgba(124, 252, 0, 0.3) 0 4px,
          transparent 4px 8px);
      }
      .gw-bar { display: flex; height: 9px; border-radius: 5px;
        overflow: hidden; margin: 8px 0; background: #141414; }
      .gw-legend { display: flex; flex-wrap: wrap; gap: 3px 12px;
        font-size: 0.66rem; color: #b0b0b0; }
      .gw-legend i { display: inline-block; width: 8px; height: 8px;
        border-radius: 2px; margin-right: 4px; }
      .gw-report-row {
        display: flex; justify-content: space-between; align-items: center;
        font-size: 0.78rem; color: #b0b0b0; padding: 4px 0;
        border-bottom: 1px solid rgba(124, 252, 0, 0.08);
      }
      .gw-report-row:last-child { border-bottom: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

if _LOGO:
    try:
        st.logo(_LOGO, icon_image=_ICON)
    except Exception:  # noqa: BLE001 - a missing logo is cosmetic, not a result
        pass


# ---------------------------------------------------------------------------
# Navigation: the one page this run executes
# ---------------------------------------------------------------------------

def resolve_page():
    """The page to run this time, and the page to switch the address to.

    ``nav`` in session state names the page on screen; the sidebar radios,
    the "next step" buttons and the tests all set it. ``st.navigation``
    knows the pages and hands back the one the browser's address asks for.
    The page ``nav`` names is made the default, so an address that asks for
    none (a new session, or a test) opens it. When the two disagree, either
    the address moved (a link, the browser's back button), and the page
    follows it, or ``nav`` moved (a button's callback), and the address is
    switched to it once the sidebar is drawn: ``st.switch_page`` ends the
    run, and a widget a run does not draw loses its value.
    """
    session = st.session_state
    registry = page_functions()
    titles = [title for title, _, _ in registry]
    current = session.get(state.NAV)
    if current not in titles:
        current = DEFAULT_PAGE
    session[state.NAV] = current
    pages = [st.Page(render, title=title, url_path=url, default=(title == current))
             for title, url, render in registry]
    shown = st.navigation(pages, position="hidden")
    switch_to = None
    if shown.title != current:
        if shown.title != session.get(state.PAGE_URL):
            current = session[state.NAV] = shown.title
        else:
            switch_to = next(p for p in pages if p.title == current)
    session[state.PAGE_URL] = shown.title
    # the widgets of every page but this one are not drawn this run, and
    # Streamlit would drop their values at its end
    state.carry_widget_values(session)
    return shown, switch_to


_page_to_run, _switch_to = resolve_page()


# After loading a project, rebuild the analysis objects from the saved data
# files so the pages and reports are populated without re-uploading. Runs
# before the sidebar so the active-project status reflects the loaded state
# on the same run.
if st.session_state.pop("_recompute_pending", False):
    _sources = _loaded_sources()
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
                        # the inversions the file carried: a survey saved
                        # and reopened is not inverted again
                        inversion_cache=st.session_state.get("inversion_cache"),
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


# Results that follow from other results (the design from the pumping test,
# the costing depth from the design) are brought up to date before any page
# reads them. A page used to rely on another having run earlier in the same
# rerun; now only one page runs.
fill_defaults()
refresh_derived()

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
        # A zone the state cannot be read for is inferred from the easting,
        # as SiteMetadata.utm infers it, rather than read as 29N: the same
        # easting in the other zone is a site 660 km away, in Guinea.
        _zone = (parse_utm_zone(st.session_state.get("meta_zone", "29N"))
                 or infer_zone_for_sierra_leone(_e))
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
    # with the single active page before the widgets render. The page itself
    # was settled by resolve_page above; the radios only show and change it.
    _nav_current = st.session_state[state.NAV]
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
        # A loaded project may carry meta_zone as a bare int/str (e.g. 29) or
        # with the label the sheet used ("Zone 28"): read the number that
        # follows the label and coerce it to the "NN N" option, so the
        # selectbox never raises on a value outside its options. A zone that
        # cannot be read has to show one of the two options, but relabelling
        # it keeps the easting and moves the site 660 km into the next zone,
        # so the relabel is said out loud rather than done quietly.
        _zone_val = st.session_state.get("meta_zone")
        if _zone_val is not None and _zone_val not in ("28N", "29N"):
            _z = parse_utm_zone(_zone_val)
            st.session_state["meta_zone"] = f"{_z}N" if _z in (28, 29) else "29N"
            if _z not in (28, 29):
                st.warning(
                    f"The saved UTM zone ({_zone_val}) is not 28N or 29N and "
                    "could not be read, so the zone below shows 29N. Check it "
                    "against the easting and northing before a report carries "
                    "them - the same easting in the other zone is a different "
                    "site, 660 km away."
                )
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
        elif st.session_state.get("latlon_assumed"):
            # the position was converted, but on a sign the parser supplied
            # rather than one the crew typed, so it is shown with the site
            st.warning(st.session_state["latlon_assumed"])
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
    # slot now and fill it at the end of the script, once the page has run:
    # otherwise "Save project" straight after an analysis wrote a file with no
    # results in it, and the Portfolio page then showed the site as unstarted.
    _project_panel = st.expander("💾 Project file")
    st.caption(
        "Methods follow RWSN/UNICEF professional drilling guidance "
        "and WHO water quality guidelines. "
        f"Toolkit version {groundwater.__version__}."
    )



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

# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

if _switch_to is not None:
    # after the sidebar, whose widgets this run has drawn and so keeps
    st.switch_page(_switch_to)

_page_to_run.run()

# The page may have produced a result another follows from; bring those up
# to date before the project file is built from them.
refresh_derived(_page_to_run.title)


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

# the post-load grace flag protects restored inputs for exactly one full
# run. The pages that used to read it on that run now leave the check to
# refresh_derived, which has run by this point; the guided start keeps its
# own marker, _wiz_load_grace, because its costing step may be reached many
# runs later.
st.session_state.pop("project_just_loaded", None)

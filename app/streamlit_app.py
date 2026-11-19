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
    degrees_in_utm_boxes,
    infer_zone_for_sierra_leone,
    parse_utm_zone,
    utm_to_geographic,
)
from groundwater.mapping import chiefdom_of, district_of
from groundwater.registry import asset_from_dict, asset_from_project, asset_with_rising_main
from groundwater.recompute import recompute_results

import state
import style
from views import page_functions
from shared import (
    _BRAND_DIR,
    _ICON,
    DEFAULT_PAGE,
    IN_BROWSER,
    NAV_GROUPS,
    NAV_STEPS,
    _apply_degree_boxes,
    _apply_latlon,
    _group_key,
    _load_project,
    _loaded_sources,
    _nav_changed,
    _project_state,
    _project_summary,
    _status_chip,
    active_theme,
    app_config,
    cached_districts,
    fill_defaults,
    project_file_bytes,
    refresh_derived,
    sample_data_dir,
    site_from_state,
    steps_done,
    theme_sync,
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

# Design language: quiet neutral surfaces with the brand green as an accent
# only, sentence case, Space Grotesk for titles, Inter for text and IBM Plex
# Mono for numbers and identifiers. The stylesheet, its colours and the
# theme it follows are in style.py; .streamlit/config.toml carries the same
# colours for Streamlit's own widgets. The printed reports keep their own
# house style (config.HouseStyle).


@st.cache_resource(show_spinner=False)
def _font_faces() -> str:
    """The bundled faces as @font-face rules, read and encoded once."""
    return style.font_faces(_BRAND_DIR)


@st.cache_resource(show_spinner=False)
def _brand_icon() -> str:
    return style.brand_icon(_BRAND_DIR)


# in a container the stylesheet gives no room, so that the page starts at
# its first line and not two empty rows down
with st.container(key="gw_style"):
    st.markdown("<style>" + _font_faces() + "</style>", unsafe_allow_html=True)
    st.markdown(style.stylesheet(active_theme()), unsafe_allow_html=True)


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
                        # the calibration set in force reads the survey
                        config=app_config(),
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
    # The one brand mark: the droplet and the product's name, in the row
    # the sidebar's close button sits in.
    _icon = _brand_icon()
    st.markdown(
        '<div class="gw-brand">'
        + (f'<img src="{_icon}" alt="">' if _icon else "")
        + '<span class="gw-brand-name">Groundwater Toolkit</span></div>',
        unsafe_allow_html=True,
    )
    # detect the district from the coordinates entered on the previous
    # run, so the dropdown can pre-fill before the widgets render
    provinces, district_rows = cached_districts()
    all_districts = [d for d, _ in district_rows]
    detected_district = ""
    detected_latlon = None
    _e = st.session_state.get("meta_easting", 0.0)
    _n = st.session_state.get("meta_northing", 0.0)
    # degrees in the two boxes are no position until the operator converts
    # them, below; projected as metres they are a point near the equator
    _degrees = degrees_in_utm_boxes(_e, _n) if _e and _n else ""
    if _e and _n and not _degrees:
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
    # the project in hand, on one line; the same line heads the page on a
    # phone, where the sidebar is a drawer (see the header below)
    _project_line = (
        f'<span class="gw-project-name">{_proj_name}</span>'
        f'<span class="gw-chip {_chip_css}">{_chip_label}</span>'
    )
    st.markdown(
        f'<div class="gw-project" title="Active project">{_project_line}</div>',
        unsafe_allow_html=True,
    )

    # Grouped navigation: one radio per group, kept consistent with the
    # single active page before the widgets render. The page itself was
    # settled by resolve_page above; the radios only show and change it.
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
    # the steps of the Borehole group that are done carry a tick in place of
    # their number; which they are is written as rules for the stylesheet
    _done = steps_done()
    _done_css = style.nav_done_css([_done[page] for page in dict(NAV_GROUPS)[NAV_STEPS]])
    if _done_css:
        st.markdown(_done_css, unsafe_allow_html=True)

    # Below the navigation, each closed until asked for: the site's details,
    # the name the reports go out under, and the project file.
    if not (_probe.community and _probe.latlon is not None):
        st.caption(
            "Set the site details below - community, area and GPS - "
            "or load a saved project file. Every page, map and report "
            "uses them."
        )
    with st.expander("Site details", expanded=False):
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
        if _degrees:
            st.warning(_degrees)
            st.button("Convert these degrees to UTM", on_click=_apply_degree_boxes,
                      key="convert_degree_boxes", width="stretch")
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
    with st.expander("Report branding"):
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
    _project_panel = st.expander("Project file")
    st.caption(
        "Methods follow RWSN/UNICEF professional drilling guidance "
        "and WHO water quality guidelines. "
        f"Toolkit version {groundwater.__version__}."
    )
    theme_sync()



# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

# The product's name stays the page's first heading, set as a small line
# above the page's own header, which is the title the eye lands on. On a
# phone the project's name heads the page in a bar that stays put.
with st.container(key="gw_eyebrow"):
    st.markdown(f'<div class="gw-topbar">{_project_line}</div>',
                unsafe_allow_html=True)
    st.title("Groundwater Investigation Toolkit")
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
    else:
        # with the rising main the design now specifies, as the registry page
        # shows it: the routine inspection is due by its interval (PLAN.md
        # step 7.3), and a record drafted before the water was analysed
        # would otherwise go out with the interval for no chemistry
        _record = asset_from_dict(st.session_state["asset_record"])
        _rising = getattr(st.session_state.get("borehole_design"), "rising_main", None)
        if _record is not None and _rising is not None:
            _kept = asset_with_rising_main(_record, _rising).as_dict()
            if _kept != st.session_state["asset_record"]:
                st.session_state["asset_record"] = _kept
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

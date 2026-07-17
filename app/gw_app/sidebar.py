"""Sidebar: site details, workflow guide, branding and the project file."""

from __future__ import annotations

import streamlit as st

import groundwater
from groundwater.geo import utm_to_geographic
from groundwater.mapping import district_of

from .common import (
    cached_districts,
    load_project_upload,
    project_file_bytes,
    site_from_state,
)


def render() -> None:
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
            st.button("Load project", key="project_load",
                      on_click=load_project_upload)
            if st.session_state.pop("project_loaded", False):
                st.success("Project loaded.")
            if st.session_state.pop("project_load_error", False):
                st.error("That file is not a toolkit project file.")
        st.caption(
            "Methods follow RWSN/UNICEF professional drilling guidance "
            "and WHO water quality guidelines. "
            f"Toolkit version {groundwater.__version__}."
        )

"""Sidebar: site details, workflow guide, branding and the project file."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import streamlit as st

import groundwater
from groundwater.geo import utm_to_geographic
from groundwater.mapping import district_of

from . import bundle
from .common import (
    IN_BROWSER,
    cached_districts,
    list_autosaves,
    load_project_upload,
    offer_download,
    project_file_bytes,
    project_state_digest,
    restore_autosave,
    site_from_state,
    workdir,
)


def _sync_date() -> None:
    picked = st.session_state.get("meta_date_widget")
    st.session_state["meta_date"] = picked.isoformat() if picked else ""


def _autosave_label(path_str: str) -> str:
    # label must be a pure function of the option string: anything
    # time-dependent (the file's mtime) breaks widget-state replay
    return Path(path_str).stem.replace("_", " ")


def _autosave_stamp(path_str: str) -> str:
    try:
        stamp = datetime.fromtimestamp(Path(path_str).stat().st_mtime)
    except OSError:
        return ""
    return f"{stamp:%d %b %Y %H:%M}"


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
            # the date is stored as an ISO string (project files, report
            # covers); the picker widget mirrors it and old free-text
            # dates from earlier project files are kept and shown below
            raw_date = str(st.session_state.get("meta_date", "") or "")
            if "meta_date_widget" not in st.session_state:
                try:
                    seed = date.fromisoformat(raw_date)
                except ValueError:
                    seed = None
                st.session_state["meta_date_widget"] = seed
            st.date_input("Date", key="meta_date_widget", on_change=_sync_date,
                          format="DD/MM/YYYY")
            if raw_date and st.session_state.get("meta_date_widget") is None:
                st.caption(f"Recorded date: {raw_date}")
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
            logo_file = st.file_uploader(
                "Logo (PNG or JPG, shown on report covers)",
                type=["png", "jpg", "jpeg"], key="org_logo_upload",
            )
            if logo_file is not None:
                suffix = Path(logo_file.name).suffix.lower() or ".png"
                logo_path = workdir() / f"org_logo{suffix}"
                logo_path.write_bytes(logo_file.getbuffer())
                st.session_state["org_logo_path"] = str(logo_path)
            _logo = st.session_state.get("org_logo_path", "")
            if _logo and Path(_logo).exists():
                st.image(_logo, width=140)
                st.button(
                    "Remove logo", key="org_logo_remove",
                    on_click=lambda: st.session_state.pop("org_logo_path", None),
                )
        with st.expander("💾 Project file"):
            st.caption(
                "Save the whole working state (site details, checklist "
                "answers, costing inputs and edited rates) and load it "
                "back later or on another machine."
            )
            payload = project_file_bytes()
            current_digest = project_state_digest(payload)
            if st.download_button(
                "Save project (.yaml)",
                payload,
                file_name=(
                    (st.session_state.get("meta_community") or "groundwater")
                    .replace(" ", "_") + "_project.yaml"
                ),
                key="project_download",
            ):
                st.session_state["_project_saved_hash"] = current_digest
            named = bool(
                (st.session_state.get("meta_community") or "").strip()
                or (st.session_state.get("meta_project") or "").strip()
            )
            if named and st.session_state.get("_project_saved_hash") != current_digest:
                if IN_BROWSER:
                    st.caption(
                        "💾 Unsaved changes - this browser demo loses its "
                        "state when the page reloads; save the project "
                        "file to keep them."
                    )
                else:
                    st.caption(
                        "💾 Unsaved changes (autosaved on this computer; "
                        "save the file to move them elsewhere)."
                    )
            st.file_uploader("Project file", type=["yaml", "yml"],
                             key="project_upload")
            st.button("Load project", key="project_load",
                      on_click=load_project_upload)
            autosaves = [] if IN_BROWSER else list_autosaves()
            if autosaves:
                autosave_options = [str(p) for p in autosaves]
                if st.session_state.get("autosave_pick") not in autosave_options:
                    st.session_state.pop("autosave_pick", None)
                st.selectbox(
                    "Autosaves on this computer",
                    autosave_options,
                    key="autosave_pick",
                    format_func=_autosave_label,
                )
                picked = st.session_state.get("autosave_pick")
                if picked:
                    stamp = _autosave_stamp(picked)
                    if stamp:
                        st.caption(f"Saved {stamp}.")
                st.button("Restore autosave", key="autosave_restore",
                          on_click=restore_autosave)
            if st.session_state.pop("project_loaded", False):
                st.success("Project loaded.")
            if st.session_state.pop("project_load_error", False):
                st.error("That file is not a toolkit project file.")
        with st.expander("🗂️ Reports bundle"):
            st.caption(
                "Build every report the session has inputs for and "
                "download them as one zip, with the bill of quantities "
                "and all generated figures."
            )
            if st.button("Build all available reports", key="build_all_reports"):
                bundle_path = bundle.build_reports_bundle()
                if bundle_path is None:
                    st.info("Nothing to bundle yet - run an analysis in any tab first.")
                else:
                    offer_download(bundle_path, "Download reports bundle (.zip)")
        st.caption(
            "Methods follow RWSN/UNICEF professional drilling guidance "
            "and WHO water quality guidelines. "
            f"Toolkit version {groundwater.__version__}."
        )

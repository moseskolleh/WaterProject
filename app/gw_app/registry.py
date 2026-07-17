"""Registry tab: the portfolio of boreholes across projects."""

from __future__ import annotations

import streamlit as st

from groundwater.registry import (
    REGISTRY_FIELDS,
    district_summary,
    parse_registry_csv,
    registry_csv_bytes,
)

from .common import (
    IN_BROWSER,
    autosave_dir,
    site_from_state,
    top_interpretation,
)


def _server_registry_path():
    return autosave_dir() / "registry.csv"


def _store_rows(rows: list[dict]) -> None:
    """Set the records and refresh the editor to show them."""
    st.session_state["registry_records"] = rows
    st.session_state["registry_base"] = [dict(r) for r in rows] or None
    if not rows:
        st.session_state.pop("registry_base", None)
    st.session_state.pop("registry_editor", None)


def _load_registry_upload() -> None:
    upload = st.session_state.get("registry_upload")
    if upload is None:
        return
    try:
        rows = parse_registry_csv(upload.getvalue().decode("utf-8-sig"))
    except Exception:
        st.session_state["registry_load_error"] = True
        return
    _store_rows(rows)
    st.session_state["registry_loaded"] = len(rows)


def _current_project_record() -> dict:
    site = site_from_state()
    interp = top_interpretation()
    design = st.session_state.get("borehole_design")
    pumping = st.session_state.get("pump_analysis")
    quality = st.session_state.get("wq_assessment")
    estimate = st.session_state.get("cost_estimate")

    depth = None
    if design is not None:
        depth = float(design.total_depth_m)
    elif interp is not None:
        depth = float(interp.max_drilling_depth_m)
    elif estimate is not None:
        depth = float(estimate.inputs.total_depth_m)

    safe_yield = None
    if pumping is not None and pumping.yield_recommendation is not None:
        safe_yield = pumping.yield_recommendation.safe_yield_m3_per_h

    lat, lon = site.latlon if site.latlon is not None else (None, None)
    return {
        "community": site.community,
        "district": site.district,
        "latitude": round(lat, 5) if lat is not None else None,
        "longitude": round(lon, 5) if lon is not None else None,
        "date": site.date,
        "total_depth_m": depth,
        "safe_yield_m3_per_h": safe_yield,
        "quality_verdict": quality.verdict if quality is not None else "",
        "price_usd": round(estimate.price_usd) if estimate is not None else None,
        "contractor": site.contractor,
        "remarks": "",
    }


def _add_current_project() -> None:
    rows = list(st.session_state.get("registry_records") or [])
    rows.append(_current_project_record())
    _store_rows(rows)


def render() -> None:
    st.header("Borehole registry")
    st.caption(
        "The portfolio across projects: every completed (or attempted) "
        "borehole with its depth, yield, quality verdict and price. It "
        "builds district statistics, maps the portfolio, and sanity "
        "checks new sitings against what the district has needed before."
    )

    # a server install keeps the registry across sessions automatically
    if (
        not IN_BROWSER
        and "registry_records" not in st.session_state
        and _server_registry_path().exists()
    ):
        try:
            _store_rows(parse_registry_csv(
                _server_registry_path().read_text(encoding="utf-8")
            ))
        except OSError:
            pass

    top1, top2 = st.columns(2)
    with top1:
        st.button(
            "➕ Add the current project", key="registry_add",
            help="Site, depth, yield, verdict and price from this "
            "session's results become one registry row.",
            on_click=_add_current_project,
        )
    with top2:
        st.file_uploader("Registry file (.csv)", type=["csv"],
                         key="registry_upload")
        st.button("Load registry", key="registry_load",
                  on_click=_load_registry_upload)
    loaded = st.session_state.pop("registry_loaded", None)
    if loaded is not None:
        st.success(f"Loaded {loaded} registry record(s).")
    if st.session_state.pop("registry_load_error", False):
        st.error("That file could not be read as a registry CSV.")

    if "registry_base" in st.session_state:
        edited = st.data_editor(
            st.session_state["registry_base"],
            key="registry_editor",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
        )
        st.session_state["registry_records"] = [
            {k: row.get(k) for k in REGISTRY_FIELDS}
            for row in edited
            if any(str(v or "").strip() for v in row.values())
        ]

    rows = st.session_state.get("registry_records") or []
    if not rows:
        st.info(
            "The registry is empty. Add the current project, or load a "
            "registry CSV saved earlier."
        )
        return

    st.download_button(
        "Save registry (.csv)",
        registry_csv_bytes(rows),
        file_name="borehole_registry.csv",
        key="registry_download",
        help="One file for the whole programme - keep it with the team "
        "and load it in any session.",
    )

    summary = district_summary(rows)
    if summary:
        st.subheader("By district")
        st.dataframe(summary, use_container_width=True)

    mappable = [
        {"lat": r["latitude"], "lon": r["longitude"],
         "label": r.get("community") or ""}
        for r in rows
        if isinstance(r.get("latitude"), (int, float))
        and isinstance(r.get("longitude"), (int, float))
    ]
    if mappable:
        try:
            import pandas as pd

            st.map(pd.DataFrame(mappable), latitude="lat", longitude="lon",
                   size=80)
        except Exception:
            pass  # the table above carries the same information

    # keep the server-side copy current, quietly
    if not IN_BROWSER:
        try:
            path = _server_registry_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(registry_csv_bytes(rows))
        except OSError:
            pass

"""Water points: what is already on the ground near the site."""

from __future__ import annotations

import streamlit as st

from groundwater.waterpoints import (
    ASSESS_REHAB,
    DEFAULT_SEARCH_RADIUS_M,
    rehab_vs_drill,
    VERIFY_NEED,
    water_points_near,
    WaterPointFetchError,
    WPDX_CREDIT,
)

from shared import (
    show_flags,
    site_from_state,
)

def render() -> None:
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
                _wp_skipped: list = []
                with st.spinner("Querying the Water Point Data Exchange..."):
                    points = water_points_near(
                        lat, lon, float(radius), skipped=_wp_skipped)
                st.session_state["wp_skipped"] = _wp_skipped
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
                    # kept as objects too, so the GeoLibre project can put
                    # them on the map rather than re-fetching them
                    "points": points,
                }
        result = st.session_state.get("wp_result")
        if result:
            # Rows the reader could not use, beside the ones it could. The
            # point count is what the rehabilitate-or-drill call is argued
            # from, so an export that arrived half unusable must not read the
            # same as a complete one.
            show_flags(st.session_state.get("wp_skipped") or [])
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

"""Maps tab: location, geology and aquifer context maps."""

from __future__ import annotations

import streamlit as st

from groundwater.mapping import (
    plot_admin_map,
    plot_geological_map,
    plot_hydrogeology_map,
)

from .common import app_config, offer_download, site_from_state, workdir


def render() -> None:
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

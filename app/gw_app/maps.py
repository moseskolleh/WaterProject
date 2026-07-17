"""Maps tab: location, geology and aquifer context maps, GIS export."""

from __future__ import annotations

import importlib.util

import streamlit as st

from groundwater.geo import utm_to_geographic
from groundwater.mapping import (
    MapPoint,
    export_geojson,
    export_gpkg,
    plot_admin_map,
    plot_geological_map,
    plot_hydrogeology_map,
)

from .common import app_config, offer_download, site_from_state, workdir


def _survey_points(site):
    """(points, zone, extra properties, latlon rows) for site + soundings."""
    points: list[MapPoint] = []
    latlon_rows: list[dict] = []
    extra: dict[str, dict] = {}
    zone = site.utm_zone
    if site.easting and site.northing:
        points.append(MapPoint(label=site.community or "site",
                               easting=site.easting, northing=site.northing,
                               kind="site"))
        lat, lon = utm_to_geographic(site.easting, site.northing, zone)
        latlon_rows.append({"lat": lat, "lon": lon,
                            "label": site.community or "site"})
    ves = st.session_state.get("ves_results")
    if ves:
        soundings, _, interps = ves
        for sounding, interp in zip(soundings, interps):
            s_site = sounding.site
            if not (s_site.easting and s_site.northing):
                continue
            points.append(MapPoint(label=sounding.sounding_id,
                                   easting=s_site.easting,
                                   northing=s_site.northing,
                                   kind="VES point"))
            extra[sounding.sounding_id] = {
                "max_drilling_depth_m": interp.max_drilling_depth_m,
                "water_zones": "; ".join(
                    f"{t:g}-{b:g} m" for t, b in interp.water_zones
                ),
            }
            lat, lon = utm_to_geographic(
                s_site.easting, s_site.northing, s_site.utm_zone or zone
            )
            latlon_rows.append({"lat": lat, "lon": lon,
                                "label": sounding.sounding_id})
    return points, zone, extra, latlon_rows


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

    points, zone, extra, latlon_rows = _survey_points(site)
    if latlon_rows:
        with st.expander("🧭 Interactive map (pan and zoom)"):
            try:
                import pandas as pd

                st.map(pd.DataFrame(latlon_rows), latitude="lat",
                       longitude="lon", size=60)
                st.caption(
                    "Site and sounding positions; the static maps above "
                    "carry the geology and aquifer layers."
                )
            except Exception:
                st.dataframe(latlon_rows, use_container_width=True)

    with st.expander("🗃️ GIS export (QGIS, Google Earth)"):
        if not points:
            st.info(
                "Enter the site GPS coordinates in the sidebar, or run a "
                "VES analysis with surveyed coordinates, and the points "
                "export here as GIS layers."
            )
        else:
            geojson_path = workdir() / "survey_points.geojson"
            export_geojson(points, zone, geojson_path,
                           extra_properties=extra)
            offer_download(geojson_path,
                           "Download survey points (GeoJSON)")
            if importlib.util.find_spec("geopandas") is not None:
                if st.button("Build GeoPackage (.gpkg)", key="run_gpkg"):
                    gpkg_path = workdir() / "survey_points.gpkg"
                    export_gpkg(points, zone, gpkg_path)
                    offer_download(gpkg_path,
                                   "Download survey points (.gpkg)")
            else:
                st.caption(
                    "GeoPackage export needs geopandas (pip install "
                    "groundwater-toolkit[gis]); the GeoJSON opens in QGIS "
                    "and Google Earth just the same."
                )

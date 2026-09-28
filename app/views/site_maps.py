"""Site maps: where the site is, what the ground is, and what is under it."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from groundwater.geo import infer_zone_for_sierra_leone
from groundwater.mapping import (
    apparent_resistivity_pseudosection,
    aquifer_thickness_map,
    area_window,
    bedrock_elevation_map,
    common_ab2_spacings,
    depth_to_bedrock_map,
    geoelectric_section_along_traverse,
    geolibre,
    ground_profile_along_traverse,
    iso_resistivity_map,
    iso_resistivity_points,
    load_chiefdoms,
    load_elevation,
    load_geology,
    load_hydrogeology,
    MapPoint,
    plot_admin_map,
    plot_geological_map,
    plot_hydrogeology_map,
    plot_study_area_map,
    plot_topographic_map,
    protective_capacity_map,
    site_location_map,
    transverse_resistance_map,
    traverse_profile,
)
from groundwater.siting import assess_siting

from shared import (
    app_config,
    _file_stem,
    kept_upload,
    offer_download,
    _offer_raster,
    site_from_state,
    workdir,
)

def render() -> None:
    st.header("Maps of the study area")
    st.caption(
        "Four scales, and a section through the ground beneath them. "
        "**Where it is**: the study area with a national locator inset, "
        "and the administrative location map. **What the ground is**: "
        "geology from the USGS Geologic Map of Africa (public domain), "
        "aquifer type and productivity from the BGS Africa Groundwater "
        "Atlas (CC BY-SA 4.0), boundaries from geoBoundaries (CC BY 4.0). "
        "**The shape of it**: a topographic map, from an elevation model "
        "you supply. **What is under it**: depth to bedrock, aquifer "
        "thickness, protective capacity and the pseudo-section, all from "
        "this survey's own soundings. The area maps embed automatically "
        "into the geophysical survey and handover reports."
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
        "Local map window (km around the site)", 5, 150, 40, 5,
        key="map_radius",
        help="Used for the study area, topographic, geological and "
        "aquifer maps when coordinates are entered.",
    )

    _survey = st.session_state.get("ves_results")
    _interps = _survey[2] if _survey else []
    _soundings = _survey[0] if _survey else []

    tab_area, tab_topo, tab_under, tab_live = st.tabs(
        ["Study area & setting", "Topography", "Subsurface", "Interactive"]
    )

    # -- where it is, and what the ground is -------------------------------
    with tab_area:
        st.caption(
            "The study area map is the one a report opens on: the chiefdom "
            "boundaries around the site, the survey points and any water "
            "points found nearby, at a scale where the distances between "
            "them can be read off the scale bar, with a thumbnail of the "
            "country showing where in it this is."
        )
        _area_geology = st.checkbox(
            "Tint the study area with the geological units",
            value=False, key="study_area_geology",
            help="Off by default: at this scale the 1:5,000,000 units are "
            "large flat washes, and the regional geology has its own map "
            "below.",
        )
        if st.button("Generate area maps", key="run_maps", type="primary"):
            marked = site if site.latlon is not None else None
            style = app_config().style
            paths = []
            _overlay = [
                {"lat": s.site.latlon[0], "lon": s.site.latlon[1],
                 "label": s.sounding_id, "kind": "VES point"}
                for s in _soundings if s.site.latlon is not None
            ]
            _wp_points = (st.session_state.get("wp_result") or {}).get("points") or []
            for _p in _wp_points[:40]:
                _lat = getattr(_p, "lat", None)
                _lon = getattr(_p, "lon", None)
                if _lat is not None and _lon is not None:
                    _overlay.append({"lat": _lat, "lon": _lon,
                                     "kind": "water point"})
            try:
                study_path = workdir() / "study_area_map.png"
                plot_study_area_map(
                    marked or site, path=study_path, style=style,
                    radius_km=float(radius), points=_overlay,
                    show_geology=bool(_area_geology),
                )
                paths.append(study_path)
            except ValueError as exc:
                st.info(f"No study area map: {exc}")
            admin_path = workdir() / "admin_map.png"
            plot_admin_map(site, path=admin_path, style=style)
            paths.append(admin_path)
            # the same maps the reports embed: a site without a fix is
            # centred on its chiefdom or district by area_window, and only
            # a site with neither falls back to the national map
            hydro_path = workdir() / "hydro_local_map.png"
            plot_hydrogeology_map(site, path=hydro_path, style=style,
                                  radius_km=float(radius))
            geo_path = workdir() / "geology_local_map.png"
            plot_geological_map(site, path=geo_path, style=style,
                                radius_km=float(radius))
            paths += [hydro_path, geo_path]
            st.session_state.map_paths = paths
        for map_path in st.session_state.get("map_paths", []):
            st.image(str(map_path))
            offer_download(map_path, f"Download {map_path.name}")

    # -- the shape of the ground -------------------------------------------
    with tab_topo:
        st.caption(
            "No elevation model is bundled with this toolkit and none is "
            "downloaded, so a topographic map is drawn from a file you "
            "supply and the figure names its source. An SRTM tile "
            "(`.hgt`, free from NASA Earthdata or viewfinderpanoramas), an "
            "ESRI ASCII grid (`.asc`, what any GIS exports) or "
            "longitude/latitude/elevation columns (`.xyz`, `.csv`) are all "
            "read here, without GDAL. A GeoTIFF converts with "
            "`gdal_translate -of AAIGrid`."
        )
        _dem_file = kept_upload(
            "Elevation model covering the site", "dem_upload",
            type=["hgt", "asc", "grd", "xyz", "csv", "txt"],
            help="One tile or grid. SRTM tiles are named for their "
            "south-west corner, as in N08W013.hgt; keep the name, because "
            "the file itself carries no header saying where on Earth it is.",
        )
        if _dem_file is not None and st.button(
            "Draw the topographic map", key="run_topo", type="primary"
        ):
            dem_path = workdir() / _dem_file.name
            dem_path.write_bytes(_dem_file.getvalue())
            try:
                grid = load_elevation(dem_path)
            except ValueError as exc:
                st.error(str(exc))
            else:
                try:
                    topo_path = workdir() / "topographic_map.png"
                    plot_topographic_map(
                        grid, site if site.latlon is not None else None,
                        path=topo_path, style=app_config().style,
                        radius_km=float(radius),
                        spot_heights=[
                            (s.site.latlon[1], s.site.latlon[0],
                             f"{s.sounding_id} {s.site.elevation_m:.0f} m")
                            for s in _soundings
                            if s.site.latlon is not None
                            and s.site.elevation_m is not None
                        ],
                    )
                    st.session_state["topo_path"] = str(topo_path)
                    st.session_state["topo_source"] = grid.source
                except ValueError as exc:
                    st.error(str(exc))
        if st.session_state.get("topo_path"):
            st.image(st.session_state["topo_path"])
            offer_download(Path(st.session_state["topo_path"]),
                           "Download topographic map")
            st.caption(f"Elevation from {st.session_state.get('topo_source', '')}.")

        st.divider()
        st.subheader("Ground profile along the traverse")
        st.caption(
            "The topographic figure a survey can always draw: the elevation "
            "recorded at each sounding, in order along the traverse. It is "
            "measured at the pegs and straight between them, which is what "
            "the field sheet supports."
        )
        _levelled = [
            i for i in _interps
            if getattr(i, "site_elevation_m", None) is not None
            and getattr(i, "site_easting", None) is not None
        ]
        if len(_levelled) < 2:
            st.info(
                f"{len(_levelled)} of {len(_interps)} soundings carry both a "
                "position and an elevation. Two are needed for a ground "
                "profile; record them on the field sheet."
            )
        elif st.button("Draw the ground profile", key="run_profile"):
            # the report's profile, under the section's rules: every
            # positioned station, no line across a gap nothing was levelled
            # in, and a reason rather than a figure where there is none
            profile_path = workdir() / "ground_profile.png"
            try:
                ground_profile_along_traverse(
                    _interps, path=profile_path, style=app_config().style)
                st.session_state["profile_path"] = str(profile_path)
            except ValueError as exc:
                st.session_state.pop("profile_path", None)
                st.info(f"No ground profile: {exc}")
        if st.session_state.get("profile_path"):
            st.image(st.session_state["profile_path"])
            offer_download(Path(st.session_state["profile_path"]),
                           "Download ground profile")

    # -- what is under it ---------------------------------------------------
    with tab_under:
        st.caption(
            "Maps of this site rather than of the country: every one is "
            "drawn from the soundings themselves. The interpolated surfaces "
            "are masked to the ground the survey actually covered, so a "
            "contour never runs past the last peg."
        )
        _placed = [i for i in _interps
                   if getattr(i, "site_easting", None) is not None]
        if not _interps:
            st.info(
                "Upload and invert a VES survey on the Geophysics page "
                "first: these maps are built from the interpretations."
            )
        elif len(_placed) < 3:
            st.warning(
                f"{len(_placed)} of {len(_interps)} soundings carry a "
                "position. A surface needs three; record the GPS position "
                "of every sounding on the field sheet.",
                icon="📍",
            )
        _spacings = common_ab2_spacings(_soundings)
        _iso_ab2 = None
        if _spacings:
            _iso_ab2 = st.select_slider(
                "Iso-resistivity map at AB/2 (m)",
                options=_spacings,
                value=_spacings[min(len(_spacings) - 1, len(_spacings) * 2 // 3)],
                key="iso_ab2",
                help="Only the spacings every sounding measured are offered: "
                "a map at a spacing two of five curves skipped would be "
                "interpolated from three points and labelled as five.",
            )
        elif _soundings:
            st.caption(
                "The soundings share no AB/2 spacing, so there is none to "
                "draw an iso-resistivity map at."
            )
        if _placed and st.button("Generate subsurface maps",
                                 key="run_subsurface", type="primary"):
            style = app_config().style
            zone = site.utm_zone or infer_zone_for_sierra_leone(
                float(_placed[0].site_easting))
            made: list[Path] = []
            plan = [
                ("depth_to_bedrock_map.png", depth_to_bedrock_map, {}),
                ("aquifer_thickness_map.png", aquifer_thickness_map, {}),
                ("bedrock_elevation_map.png", bedrock_elevation_map, {}),
                ("protective_capacity_map.png", protective_capacity_map, {}),
                ("transverse_resistance_map.png", transverse_resistance_map, {}),
            ]
            for name, fn, kwargs in plan:
                try:
                    made.append(fn(_placed, zone,
                                   path=workdir() / name, style=style, **kwargs))
                except (ValueError, RuntimeError) as exc:
                    st.caption(f"No {name.replace('_', ' ')[:-4]}: {exc}")
            # the site plan and the iso-resistivity surface, from the survey
            _pts = [
                MapPoint(label=i.sounding_id, easting=float(i.site_easting),
                         northing=float(i.site_northing))
                for i in _placed
            ]
            try:
                made.insert(0, site_location_map(
                    _pts, zone, path=workdir() / "site_location_map.png",
                    style=style, title="Survey point location map"))
            except ValueError as exc:
                st.caption(f"No site location map: {exc}")
            if _iso_ab2 is not None:
                try:
                    made.append(iso_resistivity_map(
                        iso_resistivity_points(_soundings, float(_iso_ab2)),
                        zone, ab2=float(_iso_ab2),
                        path=workdir() / "iso_resistivity_map.png", style=style))
                except ValueError as exc:
                    st.caption(f"No iso-resistivity map: {exc}")
            st.session_state["subsurface_paths"] = [str(p) for p in made]
            try:
                profile = traverse_profile(_placed)
                st.session_state["traverse"] = {
                    "length_m": profile.length_m,
                    "max_offset_m": profile.max_offset_m,
                    "straightness": profile.straightness,
                    "bearing_deg": profile.bearing_deg,
                    "collinear": profile.is_collinear,
                }
                pseudo = apparent_resistivity_pseudosection(
                    _soundings, profile,
                    path=workdir() / "pseudosection.png", style=style)
                st.session_state["pseudosection_path"] = str(pseudo)
            except ValueError as exc:
                st.session_state.pop("pseudosection_path", None)
                st.caption(f"No pseudo-section: {exc}")
            try:
                section = geoelectric_section_along_traverse(
                    _placed, path=workdir() / "geoelectric_section.png",
                    style=style)
                st.session_state["section_path"] = str(section)
            except (ValueError, RuntimeError) as exc:
                st.session_state.pop("section_path", None)
                st.caption(f"No geoelectric section: {exc}")
        _traverse = st.session_state.get("traverse")
        if _traverse:
            st.caption(
                f"Traverse {_traverse['length_m']:.0f} m long, bearing "
                f"{_traverse['bearing_deg']:.0f} degrees; the soundings sit "
                f"up to {_traverse['max_offset_m']:.0f} m off the line "
                f"({_traverse['straightness'] * 100:.0f}% of its length)."
            )
            if not _traverse["collinear"]:
                st.warning(
                    "The soundings are too scattered to read as one "
                    "section: a line through them cuts across the survey "
                    "rather than along it. The pseudo-section says so on "
                    "its own face.",
                    icon="📐",
                )
        for map_path in st.session_state.get("subsurface_paths", []):
            st.image(map_path)
            offer_download(Path(map_path), f"Download {Path(map_path).name}")
            _offer_raster(Path(map_path))
        if st.session_state.get("section_path"):
            st.image(st.session_state["section_path"])
            offer_download(Path(st.session_state["section_path"]),
                           "Download geoelectric section")
        if st.session_state.get("pseudosection_path"):
            st.image(st.session_state["pseudosection_path"])
            offer_download(Path(st.session_state["pseudosection_path"]),
                           "Download pseudo-section")

    with tab_live:
        st.caption(
            "The maps above are pictures, which is what a report needs. This "
            "writes the same survey as a GeoLibre project file - an open, "
            "plain-JSON map format - so it can be panned, zoomed, clicked and "
            "put over satellite imagery instead. "
            "[GeoLibre](https://geolibre.app) is free and open source, and the "
            "file opens in its web app, its desktop app, its phone apps and in "
            "a Jupyter notebook. Nothing is uploaded: the file is written here "
            "and downloaded to this machine. With a GPS fix it also draws the "
            "separation distances as rings round the wellhead: the ground a "
            "latrine, a burial ground or another well has to stay out of. "
            "Each continuous surface clipped to the surveyed ground, and the "
            "drill-target score, is also kept as a GeoTIFF beside its "
            "picture, offered under it, for sampling or contouring in a GIS. "
            "A surface along a single line of soundings or with a "
            "lower-bound point stays a picture, and so does the "
            "protective-capacity map, which is drawn in classes. The browser "
            "app draws the surfaces only as pictures."
        )
        _area = area_window(site, float(st.session_state.get("map_radius") or 40))
        if _area is None:
            st.info(
                "Enter the site coordinates above, or its chiefdom or district, to "
                "build the project. With none of the three there is nothing for it "
                "to open on, and the bundled geology and boundary layers alone "
                "would write a megabyte of Sierra Leone with the site missing "
                "from it."
            )
        elif st.button("Build GeoLibre project", key="run_geolibre"):
            survey = st.session_state.get("ves_results")
            suitability = assess_siting(survey[2]) if survey else None
            wp = st.session_state.get("wp_result") or {}
            radius = float(st.session_state.get("map_radius") or 40)
            project = geolibre.site_project(
                site=site,
                zone=site.utm_zone,
                suitability=suitability,
                water_points=wp.get("points"),
                area=_area,
                chiefdoms=load_chiefdoms(),
                geology=load_geology(),
                hydrogeology=load_hydrogeology(),
                window_km=radius,
            )
            path = geolibre.write_project(
                project, workdir() / f"{_file_stem(site.community)}.geolibre.json"
            )
            st.session_state["geolibre_path"] = str(path)
            st.session_state["geolibre_area"] = (
                "" if _area.exact else _area.label
            )
            st.session_state["geolibre_layers"] = [
                (layer["name"], len(layer["geojson"]["features"]))
                for layer in project["layers"]
            ]
        if st.session_state.get("geolibre_path"):
            offer_download(Path(st.session_state["geolibre_path"]),
                           "Download GeoLibre project")
            if st.session_state.get("geolibre_area"):
                st.warning(
                    f"This site has no GPS fix, so the project is centred on "
                    f"{st.session_state['geolibre_area']} and marks no position. "
                    "An area centroid is not a wellhead, and a dot drawn at one "
                    "would be measured from as though it were.",
                    icon="📍",
                )
            st.dataframe(
                [{"Layer": name, "Features": count}
                 for name, count in st.session_state.get("geolibre_layers", [])],
                hide_index=True, width="stretch",
            )
            st.markdown(
                f"Open [{geolibre.GEOLIBRE_WEB_APP}]({geolibre.GEOLIBRE_WEB_APP}) "
                "and use **Project -> Open** on the downloaded file, or drag it "
                "onto the map. A file on this machine has no address, so there is "
                "no link that can carry it - publish the project somewhere and "
                "`geolibre.project_link(url)` builds the link that opens it "
                "directly."
            )
            st.caption(
                "The project opens on a blank background, not a basemap: "
                "switching one on is the first request it makes to the network, "
                "and that is the operator's decision rather than this app's. "
                "Layer attributions travel inside the file - the aquifer layer is "
                "CC BY-SA 4.0, so a project carrying it inherits ShareAlike."
            )

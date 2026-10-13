"""Site maps: where the site is, what the ground is, and what is under it."""

from __future__ import annotations

import dataclasses
import shutil
import tempfile
from pathlib import Path

import numpy as np
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
    analyse_terrain,
    drainage_geojson,
    plot_admin_map,
    plot_curvature,
    plot_geological_map,
    plot_hillshade_directions,
    plot_hydrogeology_map,
    plot_study_area_map,
    plot_terrain_relief,
    plot_topographic_map,
    plot_wetness_index,
    protective_capacity_map,
    read_elevation,
    site_location_map,
    terrain_captions,
    transverse_resistance_map,
    traverse_profile,
)
from groundwater.mapping.elevation import ElevationFile, file_notes, open_elevation_file, wgs84_cell_size
from groundwater.mapping.terrain import geojson_meta, grid_analysis_window, uncovered_cells, uncovered_note
from groundwater.siting import assess_siting
from groundwater.text import phrase

from shared import (
    app_config,
    discard_terrain_result,
    _file_stem,
    kept_upload,
    KeptPath,
    offer_download,
    _offer_raster,
    save_upload,
    site_from_state,
    workdir,
)

#: What the operator may say an elevation model is, as the elevation layer
#: names it, and as the picker shows it
_SOURCES = {
    "detect": "Detect from the file names",
    "copernicus_glo30": "Copernicus GLO-30",
    "srtm": "SRTM",
    "other": "Another source",
}

#: Grids read whole, one file at a time, by the Python app alone; every
#: other file is a tile, read a window at a time and joined to the others
_GRID_SUFFIXES = {".asc", ".grd", ".xyz", ".csv", ".txt"}

#: The topographic map and what was said of it: the figure, its credit, its
#: read report, and the files and declared source it was drawn from
_TOPO_KEYS = ("topo_path", "topo_source", "topo_report", "topo_inputs")

#: The terrain figures: the key of each in the captions, which also names
#: its title (``title_<key>``) and its file, and the function that draws it
_TERRAIN_FIGURES = (
    ("relief", plot_terrain_relief),
    ("wetness", plot_wetness_index),
    ("curvature", plot_curvature),
    ("directions", plot_hillshade_directions),
)


def _open_tile(kept: KeptPath) -> ElevationFile:
    """A kept GeoTIFF or ``.hgt`` tile opened for its layout alone: only the
    bytes that describe it are read, not its heights."""
    with kept.path.open("rb") as handle:
        def read_at(offset: int, length: int) -> bytes:
            handle.seek(offset)
            return handle.read(length)

        return open_elevation_file(kept.name, kept.size, read_at)


def _grid_notes(name: str, analysis, centre, meta: dict) -> list[str]:
    """The read report of a grid read whole (an ESRI ASCII or XYZ file), in
    the sentences the read of tiles gives: the file, the cells of the square
    shown, their size and its radius, where the window is centred, and the
    margin.

    The window is cut to the grid, so none of it lies outside the file to
    be counted as a gap. Where the grid does not reach as far as the radius
    asked for, the square shown is cut with it, and the radius and the
    margin are those measured from the window, as the captions and the
    GeoJSON give them (``meta``, from :func:`geojson_meta`).
    """
    window = analysis.grid
    r0, r1, c0, c1 = analysis.core.shown
    # the cells' size as the figures' credit line works it out for a grid
    step_lon = (float(window.lons[-1]) - float(window.lons[0])) / max(len(window.lons) - 1, 1)
    step_lat = (float(window.lats[-1]) - float(window.lats[0])) / max(len(window.lats) - 1, 1)
    dx, dy = wgs84_cell_size(float(np.mean(window.lats)), step_lon, step_lat)
    notes = [phrase("terrain.read_summary", n=1, names=name, cells=(r1 - r0) * (c1 - c0), dx=dx, dy=dy,
                    where=centre.label, radius=meta["radius"])]
    if centre.note:
        notes.append(centre.note)
    if meta["margin"] > 0:
        notes.append(phrase("terrain.read_margin", margin=meta["margin"]))
    return notes


def _analyse_terrain(tiles, grids, site, radius_km: float, area_km2: float, declared, heard) -> dict:
    """Read the window, analyse it, draw the four figures and write the
    drainage lines, and return what the page keeps of it all.

    ``tiles`` are GeoTIFF and ``.hgt`` files, read as one window with its
    margin; ``grids`` one ESRI ASCII or XYZ grid, read whole and cut to the
    same window, under the same cap. ``heard(start, width)`` gives the
    progress callback for a part of the run, ``start`` to ``start + width``
    of the bar. The analysis itself is dropped once the figures and the
    GeoJSON are written: the session keeps only their paths, the summary,
    the captions and the read report, so a new threshold is another run.

    The files are written to a folder of this run's own in ``workdir()``,
    so the files of the result on show are never written over. A click
    anywhere on the page stops a run at its next progress update; a run
    stopped part-way leaves that result whole, and its own folder is
    removed.
    """
    cfg = dataclasses.replace(app_config().terrain, drainage_area_km2=float(area_km2))
    style = app_config().style
    if grids:
        # the grid readers name the file in what they say, so it is read
        # under the name it was uploaded with
        grid = load_elevation(save_upload(grids[0]))
        window, shown, centre = grid_analysis_window(grid, site, radius_km, cfg)
        read, notice = None, None
        analysis = analyse_terrain(window, cfg, shown=shown, progress=heard(0.05, 0.75), precision="float32")
    else:
        read = read_elevation([(f.name, f.path) for f in tiles], site, radius_km, cfg, declared=declared,
                              progress=heard(0.0, 0.1))
        centre, notice = read.centre, read.notice
        analysis = analyse_terrain(read.grid, cfg, assumed_sea=read.assumed_sea, shown=read.shown,
                                   progress=heard(0.1, 0.7), precision="float32")
    meta = geojson_meta(analysis, read, centre)
    notes = list(read.notes) if read is not None else _grid_notes(Path(grids[0].name).name, analysis, centre, meta)
    captions = terrain_captions(analysis, read, centre.label)
    credit = read.figure_credit if read is not None else None
    folder = Path(tempfile.mkdtemp(prefix="terrain_", dir=workdir()))
    try:
        # each figure is announced by its title while it is drawn
        drawing = heard(0.8, 0.2)
        figures = []
        for n, (key, draw) in enumerate(_TERRAIN_FIGURES):
            drawing(n / len(_TERRAIN_FIGURES), captions[f"title_{key}"])
            png = draw(analysis, captions, site, folder / f"terrain_{key}.png", style, svg=True, credit=credit)
            figures.append((key, str(png), str(png.with_suffix(".svg"))))
        geojson = folder / "drainage_lines.geojson"
        geojson.write_text(drainage_geojson(analysis.core, analysis.parts, meta), encoding="utf-8")
    except BaseException:
        # stopped or failed part-way: nothing of this run is kept
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return {"figures": figures, "geojson": str(geojson), "folder": str(folder), "summary": dict(analysis.summary),
            "captions": captions, "notes": notes, "notice": notice}


def _show_terrain(result: dict) -> None:
    """The terrain figures as the page keeps them: the read report, each
    figure with the engine's captions under it and its PNG and SVG, the
    drainage lines' GeoJSON, and the Copernicus liability sentence under
    the downloads when the files hold a Copernicus tile."""
    for note in result.get("notes", []):
        st.caption(note)
    captions = result["captions"]
    for key, png, svg in result["figures"]:
        st.image(png)
        st.caption(captions[key])
        offer_download(Path(png), f"Download {Path(png).name}")
        offer_download(Path(svg), f"Download {Path(svg).name}")
    offer_download(Path(result["geojson"]), "Download the drainage lines (GeoJSON)")
    if result.get("notice"):
        st.caption(result["notice"])


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
            "downloaded, so a topographic map is drawn from files you supply, "
            "and the figure names their source. GeoTIFF tiles (`.tif`) in "
            "longitude and latitude, as Copernicus GLO-30 and USGS "
            "EarthExplorer SRTM tiles are published and as QGIS saves a "
            "clip, and SRTM-format tiles (`.hgt`) are read a window at a "
            "time, several tiles joined into one model. An ESRI ASCII grid "
            "(`.asc`, what any GIS exports) or longitude/latitude/elevation "
            "columns (`.xyz`, `.csv`) are read one file at a time. None of "
            "it needs GDAL. Copernicus GLO-30 tiles can be downloaded by hand "
            "from the copernicus-dem-30m bucket of the Registry of Open Data "
            "on AWS, and NASA SRTM and NASADEM tiles from NASA Earthdata or "
            "USGS EarthExplorer. The tiles on viewfinderpanoramas are "
            "void-filled compilations of several sources: declare them as "
            "Another source."
        )
        st.caption(phrase("terrain.python_only"))
        st.caption(phrase("terrain.not_in_reports"))
        _dem_files = kept_upload(
            "Elevation models covering the site", "dem_upload",
            type=["tif", "tiff", "hgt", "asc", "grd", "xyz", "csv", "txt"],
            accept_multiple_files=True, on_disk=True,
            help="One or more GeoTIFF or .hgt tiles, or one grid. Keep the "
            "names the tiles came with: an SRTM .hgt tile is placed by its "
            "name alone (N08W013.hgt is the one whose south-west corner is "
            "8 N, 13 W), and a Copernicus tile is credited as one only when "
            "its name and its georeferencing agree.",
        ) or []
        _source = st.selectbox(
            "Source of the elevation model", list(_SOURCES),
            format_func=_SOURCES.__getitem__, key="terrain_source",
            help="What the figure credits for GeoTIFF and .hgt tiles. "
            "Detected, a tile is credited as Copernicus GLO-30 or SRTM only "
            "when its name and its georeferencing agree; a source stated "
            "here wins over what the names say.",
        )
        _source_text = ""
        if _source == "other":
            _source_text = st.text_input(
                "The source, in your own words", key="terrain_source_text",
                help="Named in the figure's credit line as you write it.",
            )
        _declared = (_source, _source_text)
        # what a map drawn now would be drawn from: the files in the
        # uploader, by the ids kept_upload gives them (the same ids when it
        # hands them back after a visit to another page), and their source
        _drawn_from = ((st.session_state.get("dem_upload_kept") or {}).get("ids"), _declared)
        _grids = [f for f in _dem_files if Path(f.name).suffix.lower() in _GRID_SUFFIXES]
        _tiles = [f for f in _dem_files if f not in _grids]
        # each tile is opened for its layout alone as soon as it is
        # uploaded, so a file that cannot be read says so beside its name
        # rather than when the map is asked for
        _refused = False
        for _tile in _tiles:
            try:
                _found = _open_tile(_tile)
            except ValueError as exc:
                st.error(str(exc))
                _refused = True
            else:
                for _note in file_notes(_found, _declared):
                    st.warning(_note)
        if _grids and len(_dem_files) > 1:
            st.error(
                f"{', '.join(f.name for f in _grids)}: an ESRI ASCII or XYZ "
                "grid is read on its own and is not joined to other files. "
                "Upload one grid alone, or GeoTIFF and .hgt tiles only."
            )
            _refused = True
        if _dem_files and st.button(
            "Draw the topographic map", key="run_topo", type="primary",
            disabled=_refused,
        ):
            topo_path = workdir() / "topographic_map.png"
            _spots = [
                (s.site.latlon[1], s.site.latlon[0],
                 f"{s.sounding_id} {s.site.elevation_m:.0f} m")
                for s in _soundings
                if s.site.latlon is not None and s.site.elevation_m is not None
            ]
            try:
                if _grids:
                    # the grid readers name the file in what they say, so
                    # it is read under the name it was uploaded with
                    grid = load_elevation(save_upload(_grids[0]))
                    plot_topographic_map(
                        grid, site, path=topo_path, style=app_config().style,
                        radius_km=float(radius), spot_heights=_spots)
                    note = uncovered_note(*uncovered_cells(grid, site, float(radius)))
                    report = {"notes": [note] if note else [], "notice": None}
                    source = grid.source
                else:
                    # every tile read at once for the square asked for, one
                    # cell in every few where the files are finer than the
                    # cap on cells allows at this width
                    read = read_elevation(
                        [(f.name, f.path) for f in _tiles], site, float(radius),
                        app_config().terrain, stride=0, margin_km=0,
                        declared=_declared)
                    plot_topographic_map(
                        read, site, path=topo_path, style=app_config().style,
                        spot_heights=_spots)
                    report = {"notes": list(read.notes), "notice": read.notice}
                    source = read.grid.source
            except ValueError as exc:
                # the previous map was of other files, or of another window
                for stale in _TOPO_KEYS:
                    st.session_state.pop(stale, None)
                st.error(str(exc))
            else:
                st.session_state["topo_path"] = str(topo_path)
                st.session_state["topo_source"] = source
                st.session_state["topo_report"] = report
                st.session_state["topo_inputs"] = _drawn_from
        # a map is shown only beside the files it was drawn from, under the
        # source declared for them: once they are refused, replaced or
        # removed, or another source is declared, its figure, credit and read
        # report no longer describe what the page holds. A refusal at upload
        # never reaches the except branch above, as it disables the button.
        if _refused or st.session_state.get("topo_inputs") != _drawn_from:
            for stale in _TOPO_KEYS:
                st.session_state.pop(stale, None)
        if st.session_state.get("topo_path"):
            st.image(st.session_state["topo_path"])
            offer_download(Path(st.session_state["topo_path"]),
                           "Download topographic map")
            st.caption(f"Elevation from {st.session_state.get('topo_source', '')}.")
            _report = st.session_state.get("topo_report") or {}
            for _note in _report.get("notes", []):
                st.caption(_note)
            if _report.get("notice"):
                st.caption(_report["notice"])

        # -- the terrain analysis of the same files: drainage lines, the
        # wetness index, curvature, and the relief lit four ways
        st.divider()
        st.subheader("Terrain analysis")
        _terrain = app_config().terrain
        _radius_col, _area_col = st.columns(2)
        _terrain_radius = _radius_col.number_input(
            "Radius of the square shown (km)", min_value=1.0, max_value=50.0,
            value=float(_terrain.analysis_radius_km), step=1.0, key="terrain_radius_km",
        )
        _terrain_area = _area_col.number_input(
            "Drainage threshold (km²)", min_value=0.05, max_value=100.0,
            value=float(_terrain.drainage_area_km2), step=0.05, format="%.2f",
            key="terrain_area_km2",
        )
        if _dem_files and st.button(
            "Analyse the terrain", key="run_terrain", type="primary",
            disabled=_refused,
        ):
            _result, _failed = None, None
            # open while the run lasts, so the bar in it is seen, and cleared
            # once the figures are drawn below it
            _working_slot = st.empty()
            with _working_slot.status(phrase("terrain.stage_read"), expanded=True) as _status:
                _bar = st.progress(0.0, text=phrase("terrain.stage_read"))

                def _heard(start: float, width: float):
                    def progress(fraction: float, label: str) -> None:
                        _status.update(label=label)
                        _bar.progress(min(1.0, start + width * fraction), text=label)
                    return progress

                try:
                    _result = _analyse_terrain(
                        _tiles, _grids, site, float(_terrain_radius),
                        float(_terrain_area), _declared, _heard)
                except ValueError as exc:
                    _failed = str(exc)
                    _status.update(state="error")
            if _result is None:
                # the figures shown before were of other files or another
                # window, and a refusal is said in their place
                discard_terrain_result(st.session_state.pop("terrain_result", None))
                st.error(_failed)
            else:
                _working_slot.empty()
                _result["inputs"] = _drawn_from
                # the figures shown before are deleted once these are kept
                _previous = st.session_state.get("terrain_result")
                st.session_state["terrain_result"] = _result
                discard_terrain_result(_previous)
        # shown, as the map is, only beside the files and the declared source
        # it was worked out from
        _kept_terrain = st.session_state.get("terrain_result")
        if _kept_terrain and (_refused or _kept_terrain.get("inputs") != _drawn_from):
            st.session_state.pop("terrain_result", None)
            discard_terrain_result(_kept_terrain)
        elif _kept_terrain:
            _show_terrain(_kept_terrain)

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

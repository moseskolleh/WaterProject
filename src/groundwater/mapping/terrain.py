"""Topography: elevation grids read from the field, and the maps drawn from them.

This module draws the land surface. It does not carry one. No digital
elevation model is bundled with the toolkit and none is downloaded, so
every topographic map here is drawn from a file the operator supplied,
and the figure names that file's source on its own face.

That is deliberate. A topographic map is read as measurement - a
hydrogeologist looking at a contour will site a borehole in the valley it
draws - and an elevation surface interpolated from the handful of spot
heights a survey happens to record is not a measurement of the landscape.
It is a guess about the ground between the pegs. So the survey's own
elevations are drawn as spot heights and as a ground profile along the
traverse, where they are exactly what they claim to be, and the contoured
map waits for a real elevation model.

The grid and the readers for the formats an operator has are in
:mod:`.elevation`, which loads no pyplot, so that reading a model does not
import the plotting stack. They are re-exported here, and every import from
this module keeps working.

The terrain figures (PLAN.md step 4.1) are drawn here too, from an analysis
:mod:`.terrain_analysis` worked out: the shaded relief with its drainage
lines, the wetness index, the curvature and the relief lit from four
directions, each with the captions the analysis wrote and the model's
credit and the analysis's caveat drawn inside the figure; and the
lineament candidates :mod:`.lineaments` found in it, over the shaded relief
and as a rose of their strikes (step 4.2).
"""

from __future__ import annotations

import math
import textwrap
from collections.abc import Sequence
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize, to_rgb
from matplotlib.lines import Line2D
from matplotlib.transforms import ScaledTranslation

from ..config import HouseStyle, TerrainConfig
from ..models import SiteMetadata
from ..plotting import figure_context, save_figure
from ..text import phrase
from . import cartography as carto
from .elevation import (  # noqa: F401 - the moved names, re-exported
    _HGT_SIDES,
    _READERS,
    _SRTM_VOID,
    ElevationGrid,
    ElevationRead,
    WindowCentre,
    _bounds_text,
    _coordinates,
    grid_fill_probe,
    load_elevation,
    read_esri_ascii,
    read_srtm_hgt,
    read_xyz,
    row_metric,
    sin_cos_deg,
    wgs84_cell_size,
)
from .lineaments import ROSE_BANDS, LineamentAnalysis, lineament_lonlat
from .regional import (
    ADMIN_CREDIT,
    AreaWindow,
    _geo_axes_finish,
    _mark_site,
    area_window,
    load_admin,
)
from .survey import SurveyPlan, line_station
from .terrain_analysis import (
    LAND,
    SEA,
    VOID,
    DrainagePart,
    TerrainAnalysis,
    _measured_window,
    _surface_note,
    contour_interval,
    hillshade_layer,
    horn_gradients,
)


def _land_cmap():
    """Matplotlib's ``terrain`` ramp with its bathymetry cut off.

    The lower quarter of ``terrain`` is blue, because the ramp is built
    for maps that carry the sea bed as well as the land. Used on a land
    elevation map it draws everything under about 25 m as water - which
    over the Sierra Leone coastal plain is most of the ground a borehole
    gets drilled into, and reads as a lagoon that is not there.
    """
    from matplotlib.colors import LinearSegmentedColormap

    base = plt.get_cmap("terrain")
    return LinearSegmentedColormap.from_list(
        "terrain_land", base(np.linspace(0.25, 1.0, 256))
    )


# ---------------------------------------------------------------------------
# Derived surfaces
# ---------------------------------------------------------------------------

def hillshade(
    grid: ElevationGrid,
    azimuth_deg: float = 315.0,
    altitude_deg: float = 45.0,
    vertical_exaggeration: float = 1.0,
) -> np.ndarray:
    """Shaded relief from the grid: the cosine of the angle between the sun
    and the ground, 0 in shadow to 1 facing the sun.

    The standard north-west sun, because relief lit from any other
    quarter reads as inverted to most people - valleys become ridges. The
    azimuth is measured clockwise from north, as GDAL's is: this used to
    light 315 from the north-east, a quarter turn out.

    It is GDAL's hillshade with Horn's gradients, worked out by the terrain
    analysis's own kernels (:func:`.terrain_analysis.horn_gradients` and
    :func:`.terrain_analysis.hillshade_layer`) on each row's cell size in
    metres on the WGS 84 ellipsoid, so the slopes are real slopes and not a
    function of how far north the tile happens to be. A cell on the edge of
    the grid or beside a void is NaN: shading it from a stand-in height
    drew a cliff around every gap.
    """
    p, q, _ = horn_gradients(grid.z, row_metric(grid.lons, grid.lats))
    return hillshade_layer(p, q, azimuth_deg, altitude_deg, vertical_exaggeration)


def slope_percent(grid: ElevationGrid) -> np.ndarray:
    """Ground slope as a percentage (100 times its tangent), for siting and
    access notes: Horn's slope on each row's cell size in metres, NaN on
    the edge of the grid and beside a void, where the slope is not known."""
    _, _, tanb = horn_gradients(grid.z, row_metric(grid.lons, grid.lats))
    return 100.0 * tanb


def _contour_interval(z: np.ndarray) -> float:
    """A round contour interval giving roughly a dozen lines over the
    finite heights of ``z`` (:func:`.terrain_analysis.contour_interval`).

    Sierra Leone's basement plains and the Freetown peninsula differ by
    two orders of magnitude in relief, so a fixed interval draws either
    two contours or four hundred.
    """
    finite = z[np.isfinite(z)]
    if finite.size == 0:
        return contour_interval(math.nan)
    return contour_interval(float(finite.max() - finite.min()))


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------

def _square(grid: ElevationGrid, site: SiteMetadata | None, radius_km: float,
            admin_path: str | Path | None = None
            ) -> tuple[AreaWindow | None, float, float, tuple[float, float, float, float]]:
    """The square a topographic map of ``grid`` is framed on: its centre
    (the site's area window, else the middle of the grid) and its
    ``(west, east, south, north)``, ``radius_km`` each way, worked out as
    :meth:`ElevationGrid.window` cuts its window."""
    window = area_window(site, radius_km, admin_path) if site is not None else None
    if window is not None:
        lon, lat = float(window.lon), float(window.lat)
    else:
        lon, lat = float(np.mean(grid.lons)), float(np.mean(grid.lats))
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 1e-6))
    return window, lon, lat, (lon - dlon, lon + dlon, lat - dlat, lat + dlat)


def _lattice_span(axis: np.ndarray, lo: float, hi: float) -> tuple[int, int]:
    """How many points of the axis's lattice, carried on past its ends,
    fall between ``lo`` and ``hi``, and how many of those the axis holds."""
    n = len(axis)
    step = (float(axis[-1]) - float(axis[0])) / (n - 1)
    first = math.ceil((lo - float(axis[0])) / step - 1e-9)
    last = math.floor((hi - float(axis[0])) / step + 1e-9)
    if last < first:
        return 0, 0
    return last - first + 1, max(0, min(last, n - 1) - max(first, 0) + 1)


def uncovered_cells(grid: ElevationGrid, site: SiteMetadata | None, radius_km: float,
                    admin_path: str | Path | None = None) -> tuple[int, int]:
    """How many cells of the square a topographic map of ``grid`` is framed
    on the grid does not reach, and how many cells the square holds, both
    counted on the grid's own spacing: ``(count, cells)``.

    It is what a window read from tiles counts as uncovered, counted for a
    single ESRI ASCII or XYZ grid, whose map is cut from the whole grid
    rather than read as a window. Counts rather than a share, so that
    :func:`uncovered_note` can choose its sentence in whole numbers, as
    the read report of tiles does: a share in floating point rounds a gap
    of a few cells to "0%". A grid with no spacing along an axis, or a
    square narrower than one of its cells, holds no cells to count, and
    gives ``(0, 0)``.
    """
    _, _, _, (west, east, south, north) = _square(grid, site, radius_km, admin_path)
    if len(grid.lons) < 2 or len(grid.lats) < 2:
        return 0, 0
    across, covered_x = _lattice_span(grid.lons, west, east)
    down, covered_y = _lattice_span(grid.lats, south, north)
    cells = across * down
    return cells - covered_x * covered_y, cells


def uncovered_note(count: int, cells: int) -> str | None:
    """What the read report says of ``count`` cells of the ``cells`` in a
    map's square that the elevation model does not reach, or None when it
    reaches them all.

    The share is rounded to a whole per cent in integers, half up, by the
    rule the read report of tiles follows in both engines. A gap of under
    half a per cent would round to "0%", which says no ground is missing in
    the one sentence printed because some is, so its cells are counted
    instead; and a square the model reaches at all is not called 100%
    uncovered, so a share that rounds up to the whole is given as 99%.
    """
    if count <= 0 or cells <= 0:
        return None
    if 200 * count < cells:
        return phrase("terrain.read_uncovered_little", count=count)
    pct = (200 * count + cells) // (2 * cells)
    if count < cells and pct == 100:
        pct = 99
    return phrase("terrain.read_uncovered", pct=pct)


def _grid_credit(grid: ElevationGrid) -> str:
    """The credit line of a figure drawn from a grid that was not read as a
    window: its label, the credit its licence asks for, and its cell size
    in metres where it is."""
    lat = float(np.mean(grid.lats))
    step_lon = (float(grid.lons[-1]) - float(grid.lons[0])) / max(len(grid.lons) - 1, 1)
    step_lat = (float(grid.lats[-1]) - float(grid.lats[0])) / max(len(grid.lats) - 1, 1)
    dx, dy = wgs84_cell_size(lat, step_lon, step_lat)
    if grid.credit:
        return phrase("terrain.figure_credit", label=grid.source, credit=grid.credit, dx=dx, dy=dy)
    return phrase("terrain.figure_credit_bare", label=grid.source, dx=dx, dy=dy)


def _window_run(axis: np.ndarray, centre: float, half: float) -> slice | None:
    """The run of ``axis`` that :meth:`ElevationGrid.window` keeps around
    ``centre``, ``half`` degrees each way: the points inside, and one more
    beyond each end where the axis has one. None when fewer than two points
    lie inside, which the window refuses."""
    inside = np.flatnonzero((axis >= centre - half) & (axis <= centre + half))
    if inside.size < 2:
        return None
    return slice(max(int(inside[0]) - 1, 0), min(int(inside[-1]) + 2, axis.size))


def grid_analysis_window(grid: ElevationGrid, site: SiteMetadata | None, radius_km: float,
                         cfg: TerrainConfig | None = None, admin_path: str | Path | None = None
                         ) -> tuple[ElevationGrid, tuple[int, int, int, int], WindowCentre]:
    """The window of a grid read whole (an ESRI ASCII or XYZ file) that the
    terrain analysis takes, the square shown inside it, and where it is
    centred.

    The window is :meth:`ElevationGrid.window` cut ``radius_km`` plus
    ``cfg.analysis_buffer_km`` each way of the site, as a topographic map
    of the grid is centred (:func:`_square`), or of the middle of the grid
    when the project records no location; the margin is whatever of it the
    grid holds. The square shown is the cells of the window ``radius_km``
    each way, as rows ``r0:r1`` and columns ``c0:c1``.

    A grid is not planned and read as tiles are, but it is held to the same
    cap on the cells analysed, with the same sentences: the radius offered
    is the largest, to a tenth of a kilometre, whose window the grid's own
    cells were counted for and found to fit, and when the margin alone is
    over the cap, no radius is offered. A window under 3 cells a side, or
    a square shown with no height in it, is refused as a window of tiles
    is.
    """
    cfg = TerrainConfig() if cfg is None else cfg
    area = area_window(site, radius_km, admin_path) if site is not None else None
    if area is not None:
        note = None if area.exact else phrase("terrain.centre_area", label=area.label)
        centre = WindowCentre(float(area.lon), float(area.lat), area.label, bool(area.exact), note)
    else:
        lon, lat = float(np.mean(grid.lons)), float(np.mean(grid.lats))
        centre = WindowCentre(lon, lat, _coordinates(lon, lat), False, phrase("terrain.centre_no_site"))
    lon, lat = centre.lon, centre.lat
    margin = cfg.analysis_buffer_km

    # the half sides in degrees, as ElevationGrid.window works them out
    def halves(radius: float) -> tuple[float, float]:
        return radius / (111.32 * max(math.cos(math.radians(lat)), 1e-6)), radius / 111.32

    def cells(radius: float) -> int:
        dlon, dlat = halves(radius + margin)
        across, down = _window_run(grid.lons, lon, dlon), _window_run(grid.lats, lat, dlat)
        if across is None or down is None:
            return 0
        return (across.stop - across.start) * (down.stop - down.start)

    if cells(radius_km) > cfg.max_cells:
        if cells(0.0) > cfg.max_cells:
            raise ValueError(phrase("terrain.margin_too_many_cells", margin=margin, cap=cfg.max_cells))
        # tenths of a kilometre: the window at fit / 10 fits, at wide / 10 it does not
        fit, wide = 0, math.ceil(radius_km * 10)
        while wide - fit > 1:
            middle = (fit + wide) // 2
            if cells(middle / 10) <= cfg.max_cells:
                fit = middle
            else:
                wide = middle
        raise ValueError(phrase("terrain.too_many_cells", radius=radius_km, margin=margin, cap=cfg.max_cells,
                                fit=fit / 10))
    window = grid.window(lon, lat, radius_km + margin)
    rows, cols = window.z.shape
    if rows < 3 or cols < 3:
        raise ValueError(phrase("terrain.too_small", w=cols, h=rows))
    dlon, dlat = halves(radius_km)
    across = np.flatnonzero((window.lons >= lon - dlon) & (window.lons <= lon + dlon))
    down = np.flatnonzero((window.lats >= lat - dlat) & (window.lats <= lat + dlat))
    if across.size < 2 or down.size < 2:
        # the square shown misses the grid though its margin does not, and
        # the window says so in its own words
        grid.window(lon, lat, radius_km)
    shown = (int(down[0]), int(down[-1]) + 1, int(across[0]), int(across[-1]) + 1)
    if not np.isfinite(window.z[shown[0]:shown[1], shown[2]:shown[3]]).any():
        raise ValueError(phrase("terrain.no_elevations", radius=radius_km, where=centre.label))
    return window, shown, centre


def geojson_meta(analysis: TerrainAnalysis, read: ElevationRead | None = None,
                 centre: WindowCentre | None = None, credit: str | None = None) -> dict:
    """What :func:`.terrain_analysis.drainage_geojson` is told about an
    analysis, as the app tells it, so that the download says what the
    captions say; :func:`.lineaments.lineament_geojson` is told the same.

    For a window read from tiles, ``read`` gives the label, the credit line,
    the Copernicus notice, the surface note, the radius and the margin and
    the centre. For a grid read whole (``read`` None), the label is the
    grid's, the credit line ``credit`` (by default the one the figures work
    out from the grid), there is no notice, and the radius and the margin
    are measured from the analysed window, as
    :func:`.terrain_analysis.terrain_captions` measures them; ``centre`` is
    where the window was centred (:func:`grid_analysis_window`).
    """
    grid, settings = analysis.grid, analysis.settings
    if read is not None:
        label, figure_credit, notice, centre = read.grid.source, read.figure_credit, read.notice, read.centre
    else:
        if centre is None:
            raise ValueError("a grid read whole needs the centre its window was cut around")
        label, figure_credit, notice = grid.source, credit or _grid_credit(grid), None
    surface = read.surface if read is not None and read.surface else _surface_note(grid.source_id)
    if read is not None and read.plan is not None:
        radius, margin = read.plan.radius_km, read.plan.margin_km
    else:
        radius, margin = _measured_window(analysis.core)
    return {"label": label, "figure_credit": figure_credit, "notice": notice, "surface": surface,
            "area": settings.drainage_area_km2, "radius": radius, "margin": margin, "centre": centre,
            "fill_note_m": settings.fill_note_m, "sea_clean": grid.sea_clean,
            "sea_cells": int(np.count_nonzero(analysis.core.cls == SEA)), "sea_level_m": settings.sea_level_m}


def plot_topographic_map(
    data: ElevationRead | ElevationGrid,
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    radius_km: float | None = None,
    title: str | None = None,
    contour_interval_m: float | None = None,
    spot_heights: list[tuple[float, float, str]] | None = None,
    show_hillshade: bool = True,
    admin_path: str | Path | None = None,
):
    """Topographic map of the study area: relief, contours and spot heights.

    ``data`` is a window read from GeoTIFF or ``.hgt`` tiles
    (:func:`.elevation.read_elevation`), drawn as it is and framed on the
    square it was read for, or a whole grid (an ESRI ASCII or XYZ file),
    out of which ``radius_km`` cuts a window around the site, framed on the
    square asked for even where the grid stops short of it: ground the
    model does not cover is left blank inside the frame, not cut off the
    map. Either way the figure carries the model's credit line and cell
    size, because a contour drawn from 90 m SRTM through a 5 km window is
    a 90 m contour however finely it is plotted, and a reader deciding
    where to put a borehole is entitled to know that. ``site`` is marked;
    for a whole grid it also centres the window.

    ``spot_heights`` are ``(lon, lat, label)`` triples - the survey's own
    levelled points. They are drawn as measured values on top of the
    modelled surface, not blended into it: where the two disagree the
    reader can see both and the survey is the one that was on the ground.
    """
    style = style or HouseStyle()
    if isinstance(data, ElevationRead):
        # the read is the square asked for, and the square shown is all of
        # it when no margin was read around it
        r0, r1, c0, c1 = data.shown
        whole = data.grid
        grid = ElevationGrid(
            whole.lons[c0:c1], whole.lats[r0:r1], whole.z[r0:r1, c0:c1], source=whole.source,
            resolution_note=whole.resolution_note, credit=whole.credit, source_id=whole.source_id,
            files=whole.files, sea_clean=whole.sea_clean,
        )
        frame = (float(grid.lons[0]), float(grid.lons[-1]), float(grid.lats[0]), float(grid.lats[-1]))
        where = data.centre.label
        stride = data.plan.stride if data.plan is not None else 1
        # a map wider than the cap on cells allows at the files' own spacing
        # is read one cell in every few, which is not an average of them,
        # and the figure says so
        credit = data.figure_credit
        if stride > 1:
            credit += f" One cell in {stride} each way is drawn, without averaging."
    else:
        grid = data
        if radius_km is not None:
            window, lon, lat, frame = _square(grid, site, radius_km, admin_path)
            grid = grid.window(lon, lat, radius_km)
        else:
            window = area_window(site, None, admin_path) if site is not None else None
            frame = (float(grid.lons.min()), float(grid.lons.max()),
                     float(grid.lats.min()), float(grid.lats.max()))
        where = _where_label(site, window)
        credit = _grid_credit(grid)

    finite = grid.z[np.isfinite(grid.z)]
    if finite.size == 0:
        raise ValueError(
            "the elevation model holds no values over this window - every "
            "sample is a void. A map of voids is not a map of the ground."
        )
    interval = contour_interval_m or _contour_interval(grid.z)
    lo = math.floor(float(finite.min()) / interval) * interval
    hi = math.ceil(float(finite.max()) / interval) * interval
    levels = np.arange(lo, hi + interval, interval)

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.6))
        extent = (
            float(grid.lons.min()), float(grid.lons.max()),
            float(grid.lats.min()), float(grid.lats.max()),
        )
        land = _land_cmap()
        ax.imshow(
            grid.z, extent=extent, origin="lower", cmap=land,
            vmin=float(finite.min()), vmax=float(finite.max()),
            interpolation="bilinear", zorder=1, aspect="auto",
        )
        if show_hillshade:
            # NaN on the edge and beside a gap, so a gap the files do not
            # cover reads as a gap rather than as shaded ground; drawn on
            # the fixed scale 0 to 1 rather than stretched to the window's
            # own range, so a gentle plain is not shaded as deeply as a
            # mountain range
            ax.imshow(
                hillshade(grid), extent=extent, origin="lower", cmap="gray",
                vmin=0.0, vmax=1.0, alpha=0.35, interpolation="bilinear",
                zorder=2, aspect="auto",
            )
        mesh_lon, mesh_lat = np.meshgrid(grid.lons, grid.lats)
        if len(levels) > 1:
            cs = ax.contour(
                mesh_lon, mesh_lat, grid.z, levels=levels,
                colors="#5A3A1E", linewidths=0.6, zorder=3,
            )
            ax.clabel(cs, np.asarray(cs.levels)[::2], fmt="%g", fontsize=6.5, inline=True)
        sm = plt.cm.ScalarMappable(
            cmap=land,
            norm=Normalize(vmin=float(finite.min()), vmax=float(finite.max())),
        )
        cbar = fig.colorbar(sm, ax=ax, pad=0.02, shrink=0.85)
        cbar.set_label("Ground elevation (m)")

        # the survey's own levelled points, over the modelled surface
        for lon, lat, label in spot_heights or []:
            ax.plot(lon, lat, "o", ms=5, mfc="white", mec="#222222", mew=1.1,
                    zorder=7)
            ax.annotate(label, xy=(lon, lat), xytext=(5, 4),
                        textcoords="offset points", fontsize=7.5,
                        fontweight="bold", color="#222222", zorder=7)

        outline, _ = load_admin(admin_path)
        for ring in outline.rings:
            ax.plot(ring[:, 0], ring[:, 1], color="#333333", lw=1.0, zorder=5)
        if site is not None:
            _mark_site(ax, site, "#C1272D")
        # the square asked for, whatever part of it the model covers
        ax.set_xlim(frame[0], frame[1])
        ax.set_ylim(frame[2], frame[3])
        _geo_axes_finish(ax, float(np.mean(ax.get_ylim())), f"{credit} {ADMIN_CREDIT}")
        ax.text(
            0.01, 0.985,
            f"Contour interval {interval:g} m",
            transform=ax.transAxes, ha="left", va="top", fontsize=7,
            color="#333333", zorder=9,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#CCCCCC",
                      alpha=0.9),
        )
        if title is None:
            title = f"Topographic map - {where}" if where else "Topographic map"
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def _where_label(site: SiteMetadata | None, window: AreaWindow | None) -> str:
    if window is not None:
        return window.label
    if site is not None and (site.community or ""):
        return site.community
    return ""


# ---------------------------------------------------------------------------
# The terrain figures
# ---------------------------------------------------------------------------
#
# Four figures of one analysed window, each cropped to the square shown and
# composited as the browser's figures are (gwt-charts.js), so that the two
# apps draw the same thing: the colours of each layer, the sea, the gaps and
# the tint over filled hollows, the contours, the drainage lines with their
# paler and dashed stretches, the colour bars' labels, and the credit and
# the caveat inside the figure, where the PNG and the SVG carry them. The
# browser draws from layers decimated to a side of 1,024 cells; these are
# given every cell of the square shown, and the PNG and the SVG both draw
# them resampled to the pixels the axes have at figure_dpi: a square wider
# than its axes is drawn with the cell nearest each pixel, so some cells
# are not drawn, and a narrower one with each cell over one pixel or more.

#: Sea with a height, and a missing tile taken as open sea, which is
#: hatched: a cell whose column plus its row from the top leaves 0 or 1 in
#: 6 takes the hatch's darker blue
_SEA_COLOUR = "#CFE3F2"
_HATCH = 6
_SEA_HATCH = "#9DBDD8"
#: A cell with no height to analyse: no data, ground no file covers, or a
#: zero-filled gap
_GAP_COLOUR = "#E6E6E6"
#: The share of the relief colour the four-way shading takes
_SHADE_SHARE = 0.35
#: The tint over land the fill raised by fill_note_m or more, and its share
_FILL_TINT = "#7B5EA7"
_FILL_SHARE = 0.25
#: How far a cell of uncertain area, one that receives water from beyond
#: the analysed square or from behind a gap, is lightened towards white on
#: the wetness map
_LIGHTEN = 0.35
#: The drainage lines: their colour, and the opacity of a stretch routed
#: across a flat or a filled hollow
_LINE_COLOUR = "#1F5C99"
_FLAT_OPACITY = 0.45
#: The contours: their colour and opacity, and the most cells a side of the
#: heights they are traced on, taken one cell in every few
_CONTOUR_COLOUR = "#5A3A1E"
_CONTOUR_OPACITY = 0.7
_CONTOUR_CELLS = 300
#: The lineament candidates: the colour of a valley and of a ridge, the
#: width they are drawn at, and how far the grey relief under them is
#: lightened towards white, so that the lines stand out on it
_VALLEY_COLOUR = "#1D4E89"
_RIDGE_COLOUR = "#C15A2A"
_LINEAMENT_WIDTH = 1.6
_LINEAMENT_GROUND = 0.4
#: The rose: the opacity of a petal, and the shares of the longest band its
#: rings are drawn at
_PETAL_OPACITY = 0.85
_ROSE_RINGS = (0.25, 0.5, 0.75, 1.0)


def _shown_axes(analysis: TerrainAnalysis) -> tuple[tuple[slice, slice], np.ndarray, np.ndarray,
                                                    tuple[float, float, float, float]]:
    """The square shown: as a view of the analysed grid, the centres of its
    columns and rows, and its outer edges ``(west, east, south, north)``."""
    core = analysis.core
    r0, r1, c0, c1 = core.shown
    lons, lats = core.lons[c0:c1], core.lats[r0:r1]
    # half a cell, from the analysed grid's own spacing (3 cells or more)
    half_x = (float(core.lons[-1]) - float(core.lons[0])) / (2 * (core.cols - 1))
    half_y = (float(core.lats[-1]) - float(core.lats[0])) / (2 * (core.rows - 1))
    frame = (float(lons[0]) - half_x, float(lons[-1]) + half_x, float(lats[0]) - half_y, float(lats[-1]) + half_y)
    return (slice(r0, r1), slice(c0, c1)), lons, lats, frame


def _coloured(values: np.ndarray, cmap, lo: float, hi: float) -> np.ndarray:
    """``values`` through a colour ramp from ``lo`` to ``hi`` as RGBA in
    float64, row 0 south; a NaN is transparent. A range that is not finite
    (a square with no value to draw) colours nothing."""
    if not (math.isfinite(lo) and math.isfinite(hi)):
        lo, hi = 0.0, 1.0
    masked = np.ma.masked_invalid(np.asarray(values, dtype=np.float64))
    rgba = np.asarray(plt.get_cmap(cmap)(Normalize(vmin=lo, vmax=hi, clip=True)(masked)), dtype=np.float64)
    rgba[np.ma.getmaskarray(masked)] = 0.0
    return rgba


def _paint_ground(rgba: np.ndarray, analysis: TerrainAnalysis, view: tuple[slice, slice]) -> np.ndarray:
    """Paint over a layer's colours what is not land: sea, a missing tile
    taken as open sea hatched in a darker blue, and gaps in grey.

    The assumed sea is the sea with no height: the read leaves it NaN in
    the grid, where every other sea cell has a height."""
    cls = analysis.core.cls[view]
    sea = cls == SEA
    assumed = sea & np.isnan(analysis.grid.z[view])
    rows, cols = cls.shape
    # the hatch counts rows from the top of the picture, as the browser's
    # canvas does, and row 0 of the grid is the bottom
    from_top = (rows - 1 - np.arange(rows))[:, None]
    hatch = (np.arange(cols)[None, :] + from_top) % _HATCH < 2
    rgba[sea] = (*to_rgb(_SEA_COLOUR), 1.0)
    rgba[assumed & hatch] = (*to_rgb(_SEA_HATCH), 1.0)
    rgba[cls == VOID] = (*to_rgb(_GAP_COLOUR), 1.0)
    return rgba


def _draw_raster(ax, rgba: np.ndarray, frame: tuple[float, float, float, float]) -> None:
    """A composited layer, one image cell to a grid cell, framed on the
    square shown.

    The image is handed over in bytes, as matplotlib turns a float colour
    into one (``(rgba * 255).astype(np.uint8)``), so the figure draws the
    same pixels while the image it holds until it is saved is an eighth of
    the size of the float64 one: the figures are drawn while the analysis
    is still held."""
    image = (np.clip(rgba, 0.0, 1.0) * 255).astype(np.uint8)
    ax.imshow(image, extent=frame, origin="lower", interpolation="nearest", zorder=1, aspect="auto")
    ax.set_xlim(frame[0], frame[1])
    ax.set_ylim(frame[2], frame[3])


class _RunsOn(LineCollection):
    """Runs of the drainage lines with flat ends, each dashed run taking up
    its pattern where the run before it on its part left off.

    matplotlib starts each line's pattern again, and lays it out in points,
    which are known only once the axes are placed; so each dashed run's
    offset is worked out as it is drawn: the length in points of its part
    before it, divided by the run's width, by which matplotlib scales a
    pattern (``lines.scale_dashes``). ``dashes`` holds for each run None, if
    it is solid, or its pattern, the part's points and the number of the
    run's first point among them."""

    def __init__(self, runs, widths, dashes, **kwargs):
        super().__init__(runs, linewidths=widths, **kwargs)
        self._widths, self._dashes = widths, dashes

    def draw(self, renderer):
        pixels = renderer.points_to_pixels(1.0)
        along: dict[int, np.ndarray] = {}
        styles = []
        for width, dash in zip(self._widths, self._dashes, strict=True):
            if dash is None:
                styles.append("solid")
                continue
            pattern, points, first = dash
            if id(points) not in along:
                steps = np.diff(self.get_transform().transform(points), axis=0)
                along[id(points)] = np.concatenate(([0.0], np.cumsum(np.hypot(steps[:, 0], steps[:, 1])))) / pixels
            styles.append((float(along[id(points)][first]) / width, pattern))
        self.set_linestyle(styles)
        super().draw(renderer)


def _draw_parts(ax, parts: Sequence[DrainagePart], lons: np.ndarray, lats: np.ndarray) -> None:
    """The drainage lines shown, wider with Strahler order, dashed where the
    upslope area is uncertain, and paler where a stretch was routed across
    a flat or a filled hollow rather than by slope. ``lons`` and ``lats``
    are the analysed grid's, which the vertices index.

    A line ``w`` points wide is dashed ``2.6w + 1.4`` on and ``1.6w + 0.9``
    off, as the browser draws it. Each run of stretches routed alike is a
    line of its own: a dashed run takes up the pattern where the run before
    it left off (:class:`_RunsOn`), so a short run is not drawn solid by
    starting it again. A dashed run and one routed by slope end square, so
    their ends do not cover a flat-routed run beside them; a flat-routed run
    keeps round ends, which fall on the darker run and fill the outside of
    the corner between them."""
    base = to_rgb(_LINE_COLOUR)
    # the runs that end square, each with its dash, and the flat-routed
    # solid ones, which end round
    square, square_colours, square_widths, dashes = [], [], [], []
    rounded, rounded_widths = [], []
    for part in parts:
        points = np.array([(float(lons[c]), float(lats[r])) for r, c in part.vertices])
        width = 0.6 + 0.5 * (part.strahler - 1)
        # matplotlib draws a dash pattern this many times the line's width
        pattern = (2.6 + 1.4 / width, 1.6 + 0.9 / width) if part.edge_contaminated else None
        start = 0
        for v in range(1, len(points)):
            if v == len(points) - 1 or part.stretch_flat[v] != part.stretch_flat[start]:
                if pattern is None and part.stretch_flat[start]:
                    rounded.append(points[start:v + 1])
                    rounded_widths.append(width)
                else:
                    square.append(points[start:v + 1])
                    square_colours.append((*base, _FLAT_OPACITY if part.stretch_flat[start] else 1.0))
                    square_widths.append(width)
                    dashes.append(None if pattern is None else (pattern, points, start))
                start = v
    if rounded:
        ax.add_collection(LineCollection(rounded, colors=[(*base, _FLAT_OPACITY)], linewidths=rounded_widths,
                                         capstyle="round", joinstyle="round", zorder=4))
    if square:
        ax.add_collection(_RunsOn(square, square_widths, dashes, colors=square_colours, capstyle="butt",
                                  joinstyle="round", zorder=4))


def _draw_contours(ax, analysis: TerrainAnalysis, view: tuple[slice, slice], lons: np.ndarray,
                   lats: np.ndarray) -> None:
    """Contours of the land heights of the square shown at the analysis's
    own interval, on one cell in every few so that neither side has more
    than _CONTOUR_CELLS. Sea and gaps are left out, so a contour stops at
    the coast and at a gap, as the browser draws them."""
    z = np.where(analysis.core.cls[view] == LAND, analysis.grid.z[view], np.nan)
    step = max(1, math.ceil(max(z.shape) / _CONTOUR_CELLS))
    z, lons, lats = z[::step, ::step], lons[::step], lats[::step]
    finite = z[np.isfinite(z)]
    interval = float(analysis.summary["contour_interval"])
    if finite.size == 0 or min(z.shape) < 2:
        return
    lo = math.floor(float(finite.min()) / interval) * interval
    hi = math.ceil(float(finite.max()) / interval) * interval
    levels = np.arange(lo, hi + interval, interval)
    if len(levels) > 1:
        # solid below sea level too, where matplotlib would dash them: a
        # dashed line on these figures is a drainage line of uncertain area
        ax.contour(lons, lats, z, levels=levels, colors=_CONTOUR_COLOUR, alpha=_CONTOUR_OPACITY, linewidths=0.5,
                   linestyles="solid", zorder=3)


def _caveat(ax, below: float, caveat: str) -> None:
    """The analysis's caveat, inside the figure under its credit line, which
    ends at ``below`` (axes fraction)."""
    ax.text(1.0, below, textwrap.fill(caveat, 104), transform=ax.transAxes, ha="right", va="top",
            fontsize=5.8, color=carto.INK_MUTED, linespacing=1.4)


def _panel_finish(ax, mean_lat: float) -> None:
    """The furniture of one panel of a figure of several: what
    :func:`.regional._geo_axes_finish` draws on a map but the credit, which
    the figure carries once, under all its panels (:func:`_small_print`)."""
    ax.set_aspect(1.0 / math.cos(math.radians(mean_lat)))
    # half as many lines as on a map the width of the figure, whose labels
    # would run into each other across a panel half as wide
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    carto.graticule(ax, interval=carto._nice_interval(2.0 * max(x1 - x0, y1 - y0)), label_size=6.0)
    carto.scale_bar(ax, mean_lat)
    carto.north_arrow(ax)
    carto.neatline(ax)
    ax.set_xlabel("")
    ax.set_ylabel("")


def _small_print(fig, credit: str, caveat: str) -> None:
    """The credit line and then the caveat, under every panel of a figure,
    set as a map's attribution is set and right-aligned on the figure."""
    drop = 4.0
    for text, colour, italic in ((credit, carto.INK_FAINT, True), (caveat, carto.INK_MUTED, False)):
        wrapped = textwrap.fill(text, 124)
        fig.text(0.99, 0.0, wrapped, ha="right", va="top", fontsize=5.8, color=colour,
                 style="italic" if italic else "normal", linespacing=1.4,
                 transform=fig.transFigure + ScaledTranslation(0.0, -drop / 72.0, fig.dpi_scale_trans))
        drop += (wrapped.count("\n") + 1) * 5.8 * 1.4 + 2.0


def _finished(fig, path: str | Path | None, style: HouseStyle, svg: bool):
    """Save the figure (and its SVG, with ``svg``) and return the PNG's
    path, or return the figure itself when there is no path."""
    if path is not None:
        return save_figure(fig, path, style, svg=svg)
    return fig


def plot_terrain_relief(
    analysis: TerrainAnalysis,
    captions: dict[str, str],
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    svg: bool = False,
    credit: str | None = None,
):
    """The shaded relief of the square shown, with its contours and its
    drainage lines: the first terrain figure.

    The land is coloured by height on the ``terrain`` ramp without its
    bathymetry (:func:`_land_cmap`), the four-way shading taking 35% of
    each cell's colour, and land the fill raised by ``fill_note_m`` or more
    is tinted, so that a filled hollow reads as one. Sea, a missing tile
    taken as open sea (hatched) and gaps are painted over
    (:func:`_paint_ground`). Contours are drawn at the analysis's interval,
    and the drainage lines shown (``analysis.parts``) wider with Strahler order,
    dashed where their area is uncertain and paler where they were routed
    across a flat or a filled hollow.

    ``captions`` is what :func:`.terrain_analysis.terrain_captions` gave,
    for the title and the caveat; the captions to print under the figure
    are ``captions["relief"]``. ``credit`` is the figure's credit line as
    the read gives it (:attr:`.elevation.ElevationRead.figure_credit`); by
    default it is worked out from the analysed grid, as for a grid read
    whole. The credit and the caveat are drawn inside the figure. With a
    ``path`` the figure is saved there (and beside it as an SVG with
    ``svg``) and the PNG's path returned; without one, the figure is.
    """
    style = style or HouseStyle()
    view, lons, lats, frame = _shown_axes(analysis)
    core = analysis.core
    z = analysis.grid.z[view]
    land = core.cls[view] == LAND
    heights = z[land & np.isfinite(z)]
    if heights.size == 0:
        heights = z[np.isfinite(z)]
    lo, hi = (float(heights.min()), float(heights.max())) if heights.size else (0.0, 1.0)
    land_ramp = _land_cmap()
    rgba = _coloured(np.where(land, z, np.nan), land_ramp, lo, hi)
    shade = np.asarray(analysis.hillshade_multi[view], dtype=np.float64)
    lit = land & np.isfinite(shade)
    rgba[lit, :3] = (1.0 - _SHADE_SHARE) * rgba[lit, :3] + _SHADE_SHARE * shade[lit][:, None]
    raised = core.raised[view].astype(bool)
    rgba[raised, :3] = (1.0 - _FILL_SHARE) * rgba[raised, :3] + _FILL_SHARE * np.asarray(to_rgb(_FILL_TINT))
    _paint_ground(rgba, analysis, view)

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 6.0))
        _draw_raster(ax, rgba, frame)
        _draw_contours(ax, analysis, view, lons, lats)
        _draw_parts(ax, analysis.parts, core.lons, core.lats)
        if site is not None:
            _mark_site(ax, site, carto.SITE)
        sm = plt.cm.ScalarMappable(cmap=land_ramp, norm=Normalize(vmin=lo, vmax=hi))
        fig.colorbar(sm, ax=ax, pad=0.02, shrink=0.85).set_label("Ground elevation (m)")
        ax.set_xlim(frame[0], frame[1])
        ax.set_ylim(frame[2], frame[3])
        below = _geo_axes_finish(ax, float(np.mean(lats)), credit or _grid_credit(analysis.grid))
        _caveat(ax, below, captions["figure_caveat"])
        ax.set_title(captions["title_relief"])
        fig.tight_layout()
        return _finished(fig, path, style, svg)


def plot_wetness_index(
    analysis: TerrainAnalysis,
    captions: dict[str, str],
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    svg: bool = False,
    credit: str | None = None,
):
    """The topographic wetness index of the square shown: the second
    terrain figure.

    Drawn on ``GnBu`` between the display limits the analysis chose
    (``summary["twi_range"]``); every cell whose upslope area is
    uncertain, because it receives water from beyond the analysed square
    or from behind a gap (``core.flag``), is lightened 35% towards white,
    as the caption says. Sea and gaps are painted as on the relief.
    ``captions``, ``credit``, ``path`` and ``svg`` are as
    :func:`plot_terrain_relief` takes them; the captions to print under it
    are ``captions["wetness"]``.
    """
    style = style or HouseStyle()
    view, lons, lats, frame = _shown_axes(analysis)
    lo, hi = analysis.summary["twi_range"]
    rgba = _coloured(analysis.twi[view], "GnBu", lo, hi)
    uncertain = analysis.core.flag[view].astype(bool) & np.isfinite(analysis.twi[view])
    rgba[uncertain, :3] = (1.0 - _LIGHTEN) * rgba[uncertain, :3] + _LIGHTEN
    _paint_ground(rgba, analysis, view)

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 6.0))
        _draw_raster(ax, rgba, frame)
        if site is not None:
            _mark_site(ax, site, carto.SITE)
        if not (math.isfinite(lo) and math.isfinite(hi)):
            lo, hi = 0.0, 1.0
        sm = plt.cm.ScalarMappable(cmap="GnBu", norm=Normalize(vmin=lo, vmax=hi))
        fig.colorbar(sm, ax=ax, pad=0.02, shrink=0.85).set_label("Wetness index")
        below = _geo_axes_finish(ax, float(np.mean(lats)), credit or _grid_credit(analysis.grid))
        _caveat(ax, below, captions["figure_caveat"])
        ax.set_title(captions["title_wetness"])
        fig.tight_layout()
        return _finished(fig, path, style, svg)


def plot_curvature(
    analysis: TerrainAnalysis,
    captions: dict[str, str],
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    svg: bool = False,
    credit: str | None = None,
):
    """The curvature of the square shown, down the slope (profile) and
    across it (tangential), per km: the third terrain figure.

    Both panels are drawn on ``BrBG`` reversed, between the same symmetric
    limits (``summary["curvature_limit"]``, the 98th percentile of either
    curvature's size over the square shown), so convex ground and spurs are
    brown and concave ground and hollows green in both; ground too flat for
    a direction is left blank. ``captions``, ``credit``, ``path`` and
    ``svg`` are as :func:`plot_terrain_relief` takes them; the captions to
    print under it are ``captions["curvature"]``.
    """
    style = style or HouseStyle()
    view, lons, lats, frame = _shown_axes(analysis)
    limit = 1000.0 * float(analysis.summary["curvature_limit"])
    if not (math.isfinite(limit) and limit > 0.0):
        limit = 1.0
    panels = (("Down the slope (profile)", analysis.profile),
              ("Across the slope (tangential)", analysis.tangential))

    with figure_context(style):
        fig, axes = plt.subplots(1, 2, figsize=(style.figure_width_in, 4.4))
        for ax, (name, layer) in zip(axes, panels, strict=True):
            per_km = 1000.0 * np.asarray(layer[view], dtype=np.float64)
            _draw_raster(ax, _paint_ground(_coloured(per_km, "BrBG_r", -limit, limit), analysis, view), frame)
            if site is not None:
                _mark_site(ax, site, carto.SITE)
            sm = plt.cm.ScalarMappable(cmap="BrBG_r", norm=Normalize(vmin=-limit, vmax=limit))
            fig.colorbar(sm, ax=ax, orientation="horizontal", pad=0.12, shrink=0.9,
                         fraction=0.05).set_label("Curvature (per km)", fontsize=7)
            _panel_finish(ax, float(np.mean(lats)))
            ax.set_title(name, fontsize=9)
        fig.suptitle(captions["title_curvature"], fontsize=11, fontweight="bold")
        fig.tight_layout()
        _small_print(fig, credit or _grid_credit(analysis.grid), captions["figure_caveat"])
        return _finished(fig, path, style, svg)


def plot_hillshade_directions(
    analysis: TerrainAnalysis,
    captions: dict[str, str],
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    svg: bool = False,
    credit: str | None = None,
):
    """The relief of the square shown lit from each of the panel azimuths,
    two panels to a row: the fourth terrain figure, for picking out straight
    features that one light hides.

    Each panel is the analysis's hillshade from one azimuth, grey from 0
    (in shadow) to 1 (facing the light), titled with its direction
    (``captions["panel_0"]`` onwards); sea and gaps are painted as on the
    relief. ``captions``, ``credit``, ``path`` and ``svg`` are as
    :func:`plot_terrain_relief` takes them; the captions to print under it
    are ``captions["directions"]``.
    """
    style = style or HouseStyle()
    view, lons, lats, frame = _shown_axes(analysis)
    count = len(analysis.hillshades)
    across = 2 if count > 1 else 1
    down = -(-count // across)

    with figure_context(style):
        fig, axes = plt.subplots(down, across, figsize=(style.figure_width_in, 3.4 * down + 0.4), squeeze=False)
        for n, ax in enumerate(axes.ravel()):
            if n >= count:
                ax.set_visible(False)
                continue
            layer = np.asarray(analysis.hillshades[n][view], dtype=np.float64)
            _draw_raster(ax, _paint_ground(_coloured(layer, "gray", 0.0, 1.0), analysis, view), frame)
            if site is not None:
                _mark_site(ax, site, carto.SITE)
            _panel_finish(ax, float(np.mean(lats)))
            ax.set_title(captions[f"panel_{n}"], fontsize=9)
        fig.suptitle(captions["title_directions"], fontsize=11, fontweight="bold")
        fig.tight_layout()
        _small_print(fig, credit or _grid_credit(analysis.grid), captions["figure_caveat"])
        return _finished(fig, path, style, svg)


def _lineament_note(captions: dict[str, str]) -> str:
    """What both lineament figures carry inside them under the credit: that
    the candidates are inferred from terrain, then the analysis's caveat,
    as one paragraph."""
    return f"{captions['figure_note']} {captions['figure_caveat']}"


def plot_lineaments(
    analysis: TerrainAnalysis,
    captions: dict[str, str],
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    svg: bool = False,
    credit: str | None = None,
    *,
    lineaments: LineamentAnalysis,
):
    """The lineament candidates over the shaded relief of the square shown:
    the fifth terrain figure (PLAN.md step 4.2).

    The land is the multidirectional hillshade in grey, lightened 40%
    towards white, with sea and gaps painted as on the relief; each
    candidate is a straight line from its start to its end, a valley in
    blue and a ridge in orange, keyed in the upper left. ``captions`` is
    what :func:`.terrain_analysis.terrain_captions` gave with what
    :func:`.lineaments.lineament_captions` gave merged into it: the title
    is ``captions["title_lineaments"]``, and the note that the candidates
    are inferred from terrain is drawn inside the figure before the caveat;
    the captions to print under it are ``captions["lineaments"]``.
    ``credit``, ``path`` and ``svg`` are as :func:`plot_terrain_relief`
    takes them.
    """
    style = style or HouseStyle()
    view, lons, lats, frame = _shown_axes(analysis)
    land = analysis.core.cls[view] == LAND
    shade = np.asarray(analysis.hillshade_multi[view], dtype=np.float64)
    rgba = _coloured(np.where(land, shade, np.nan), "gray", 0.0, 1.0)
    lit = land & np.isfinite(shade)
    rgba[lit, :3] = (1.0 - _LINEAMENT_GROUND) * rgba[lit, :3] + _LINEAMENT_GROUND
    _paint_ground(rgba, analysis, view)
    grid = analysis.grid
    segments = {"valley": [], "ridge": []}
    for item in lineaments.lineaments:
        segments[item.kind].append([lineament_lonlat(lineaments, grid.lons, grid.lats, item.start),
                                    lineament_lonlat(lineaments, grid.lons, grid.lats, item.end)])

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 6.0))
        _draw_raster(ax, rgba, frame)
        for kind, colour in (("valley", _VALLEY_COLOUR), ("ridge", _RIDGE_COLOUR)):
            if segments[kind]:
                ax.add_collection(LineCollection(segments[kind], colors=colour, linewidths=_LINEAMENT_WIDTH,
                                                 capstyle="round", zorder=4, label=kind))
        if site is not None:
            _mark_site(ax, site, carto.SITE)
        ax.legend(handles=[Line2D([0], [0], color=_VALLEY_COLOUR, lw=2.0, label="Straight valley"),
                           Line2D([0], [0], color=_RIDGE_COLOUR, lw=2.0, label="Straight ridge")],
                  loc="upper left", fontsize=7, framealpha=0.85)
        ax.set_xlim(frame[0], frame[1])
        ax.set_ylim(frame[2], frame[3])
        below = _geo_axes_finish(ax, float(np.mean(lats)), credit or _grid_credit(analysis.grid))
        _caveat(ax, below, _lineament_note(captions))
        ax.set_title(captions["title_lineaments"])
        fig.tight_layout()
        return _finished(fig, path, style, svg)


def _rose_label(metres: float) -> str:
    """A ring's length, in km to a tenth below 10 km and whole above."""
    km = metres / 1000.0
    return f"{km:.1f} km" if km < 10.0 else f"{km:.0f} km"


def plot_lineament_rose(
    analysis: TerrainAnalysis,
    captions: dict[str, str],
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    svg: bool = False,
    credit: str | None = None,
    *,
    lineaments: LineamentAnalysis,
):
    """The strikes of the lineament candidates as two roses, valleys and
    ridges side by side: the sixth terrain figure (PLAN.md step 4.2).

    Each 10-degree band of strike is a petal drawn twice, opposite itself,
    because a strike has no way along it, with north up and bearings
    clockwise. A petal's reach is the square root of its band's length over
    the longest band's, of either rose, so that its area is in proportion
    to the length and the two roses are on one scale; the rings are at a
    quarter, a half, three quarters and all of the longest band's length,
    which they name. Each rose is headed with its count and length
    (``captions["rose_valleys"]`` and ``captions["rose_ridges"]``). The
    figure needs a candidate to draw: ``lineaments`` with none is refused.
    ``captions``, ``credit``, ``path`` and ``svg`` are as
    :func:`plot_lineaments` takes them; ``site`` is taken so that every
    terrain figure is called alike, and a rose has nowhere to mark it. The
    captions to print under it are ``captions["rose"]``.
    """
    del site
    longest = max((*lineaments.rose_valley_m, *lineaments.rose_ridge_m), default=0.0)
    if not longest > 0.0:
        raise ValueError("a rose of the lineament candidates needs a candidate to draw")
    style = style or HouseStyle()
    width = math.radians(180.0 / ROSE_BANDS)
    roses = ((lineaments.rose_valley_m, _VALLEY_COLOUR, captions["rose_valleys"]),
             (lineaments.rose_ridge_m, _RIDGE_COLOUR, captions["rose_ridges"]))

    with figure_context(style):
        fig, axes = plt.subplots(1, 2, figsize=(style.figure_width_in, 3.9), subplot_kw={"projection": "polar"})
        for ax, (lengths, colour, heading) in zip(axes, roses, strict=True):
            ax.set_theta_zero_location("N")
            ax.set_theta_direction(-1)
            for band, length in enumerate(lengths):
                if length <= 0.0:
                    continue
                reach = math.sqrt(length / longest)
                for start in (band * 10.0, band * 10.0 + 180.0):
                    # under the axis (2.5), so the rings and their lengths read over them
                    ax.bar(math.radians(start + 5.0), reach, width=width, bottom=0.0, color=colour,
                           alpha=_PETAL_OPACITY, edgecolor="white", linewidth=0.5, zorder=2)
            ax.set_ylim(0.0, 1.0)
            ax.set_yticks([math.sqrt(share) for share in _ROSE_RINGS])
            ax.set_yticklabels([])
            for share in _ROSE_RINGS:
                ax.text(math.radians(22.5), math.sqrt(share), _rose_label(share * longest), fontsize=6,
                        color=carto.INK_MUTED, ha="left", va="bottom", zorder=5, path_effects=carto.halo())
            ax.set_xticks([math.radians(a) for a in (0.0, 90.0, 180.0, 270.0)])
            ax.set_xticklabels(["N", "E", "S", "W"], fontsize=8)
            ax.grid(color=carto.INK_FAINT, linewidth=0.4, alpha=0.6)
            ax.set_title(heading, fontsize=9, pad=12)
        fig.suptitle(captions["title_rose"], fontsize=11, fontweight="bold")
        fig.tight_layout()
        _small_print(fig, credit or _grid_credit(analysis.grid), _lineament_note(captions))
        return _finished(fig, path, style, svg)


# The survey plan's figure (PLAN.md step 4.3): the profiling lines in purple,
# apart from the candidates' blue and orange; the separation rings thin,
# dashed and brown; the service radius dashed in near-black; the mapped
# water points in the blue the GeoLibre project gives a survey point.
_PLAN_LINE = "#5B2A86"
_PLAN_RING = "#8A5A2B"
_PLAN_RADIUS = "#333333"
_PLAN_WATER = "#17527E"
#: The view's half side, in service radii: the radius and its rings with a
#: margin round them.
_PLAN_VIEW = 1.25


def _plan_ring(plan: SurveyPlan, lons, lats, x: float, y: float, d: float) -> np.ndarray:
    """A circle of ``d`` metres round ``(x, y)`` of the candidates' frame,
    in longitude and latitude, closed, from the vertices the GeoJSON writes."""
    points = []
    for k in range(65):
        sin, cos = sin_cos_deg(360.0 * (k % 64) / 64)
        points.append(lineament_lonlat(plan, lons, lats, (x + d * sin, y + d * cos)))
    return np.asarray(points)


def plot_survey_plan(
    analysis: TerrainAnalysis,
    captions: dict[str, str],
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    svg: bool = False,
    credit: str | None = None,
    *,
    lineaments: LineamentAnalysis,
    plan: SurveyPlan,
):
    """The survey plan round the site: the seventh terrain figure (PLAN.md
    step 4.3).

    The ground is the lineament map's, the multidirectional hillshade in
    grey lightened towards white, cut to a square a quarter wider than the
    service radius each way, with the drainage lines over it as the relief
    draws them and the candidates as the lineament map draws them. Over
    those: the service radius, dashed; each mapped water point within reach
    with its separation ring; each profiling line with a dot at each
    station and its name at its start; and each proposed sounding as a
    numbered ring, with its spread drawn dashed along its candidate's
    strike to the AB/2 it is planned to. The note that the candidates are
    inferred from terrain and the pegs are proposals is drawn inside with
    the analysis's caveat. ``captions`` holds the terrain captions with the
    lineaments' and :func:`.survey.survey_plan_captions`'s merged in:
    the title is ``captions["title_plan"]``, and the caption to print under
    it ``captions["plan"]``. ``credit``, ``path`` and ``svg`` are as
    :func:`plot_terrain_relief` takes them.
    """
    style = style or HouseStyle()
    core = analysis.core
    lons, lats = core.lons, core.lats
    dx, dy = plan.frame
    sx, sy = plan.site
    half = _PLAN_VIEW * plan.radius_m
    c_lo, c_hi = max(0, math.floor((sx - half) / dx)), min(core.cols - 1, math.ceil((sx + half) / dx))
    r_lo, r_hi = max(0, math.floor((sy - half) / dy)), min(core.rows - 1, math.ceil((sy + half) / dy))
    view = (slice(r_lo, r_hi + 1), slice(c_lo, c_hi + 1))
    land = core.cls[view] == LAND
    shade = np.asarray(analysis.hillshade_multi[view], dtype=np.float64)
    rgba = _coloured(np.where(land, shade, np.nan), "gray", 0.0, 1.0)
    lit = land & np.isfinite(shade)
    rgba[lit, :3] = (1.0 - _LINEAMENT_GROUND) * rgba[lit, :3] + _LINEAMENT_GROUND
    _paint_ground(rgba, analysis, view)
    half_x = (float(lons[-1]) - float(lons[0])) / (2 * (core.cols - 1))
    half_y = (float(lats[-1]) - float(lats[0])) / (2 * (core.rows - 1))
    cells = (float(lons[c_lo]) - half_x, float(lons[c_hi]) + half_x, float(lats[r_lo]) - half_y,
             float(lats[r_hi]) + half_y)
    west, south = lineament_lonlat(plan, lons, lats, (sx - half, sy - half))
    east, north = lineament_lonlat(plan, lons, lats, (sx + half, sy + half))
    parts = [part for part in analysis.parts
             if any(r_lo <= r <= r_hi and c_lo <= c <= c_hi for r, c in part.vertices)]
    segments = {"valley": [], "ridge": []}
    for item in lineaments.lineaments:
        segments[item.kind].append([lineament_lonlat(lineaments, lons, lats, item.start),
                                    lineament_lonlat(lineaments, lons, lats, item.end)])
    reach = float(plan.ab2["max_ab2"])

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 6.4))
        _draw_raster(ax, rgba, cells)
        _draw_parts(ax, parts, lons, lats)
        for kind, colour in (("valley", _VALLEY_COLOUR), ("ridge", _RIDGE_COLOUR)):
            if segments[kind]:
                ax.add_collection(LineCollection(segments[kind], colors=colour, linewidths=_LINEAMENT_WIDTH,
                                                 capstyle="round", zorder=4))
        ring = _plan_ring(plan, lons, lats, sx, sy, plan.radius_m)
        ax.plot(ring[:, 0], ring[:, 1], color=_PLAN_RADIUS, linewidth=1.2, linestyle=(0, (5, 3)), zorder=5)
        for x, y, _, d in plan.rings:
            ring = _plan_ring(plan, lons, lats, x, y, d)
            ax.plot(ring[:, 0], ring[:, 1], color=_PLAN_RING, linewidth=0.9, linestyle=(0, (2, 2)), zorder=5)
            lon, lat = lineament_lonlat(plan, lons, lats, (x, y))
            ax.plot(lon, lat, marker="s", markersize=4.5, color=_PLAN_WATER, markeredgecolor="white", zorder=6)
        for line in plan.lines:
            points = np.asarray([lineament_lonlat(plan, lons, lats, line_station(line, k))
                                 for k in range(line.first, line.last + 1)])
            ax.plot(points[[0, -1], 0], points[[0, -1], 1], color=_PLAN_LINE, linewidth=2.0,
                    solid_capstyle="butt", zorder=6)
            ax.scatter(points[:, 0], points[:, 1], s=3.0, color=_PLAN_LINE, zorder=6, linewidths=0)
            ax.text(points[0, 0], points[0, 1], f" {phrase('survey_plan.line_name', line=line.id)} ", fontsize=7,
                    color=_PLAN_LINE, fontweight="bold", ha="right" if line.direction[0] >= 0 else "left",
                    va="center", zorder=8, path_effects=carto.halo())
        for x in plan.soundings:
            sin, cos = sin_cos_deg(x.spread_deg)
            a = lineament_lonlat(plan, lons, lats, (x.point[0] - reach * sin, x.point[1] - reach * cos))
            b = lineament_lonlat(plan, lons, lats, (x.point[0] + reach * sin, x.point[1] + reach * cos))
            ax.plot([a[0], b[0]], [a[1], b[1]], color=_PLAN_LINE, linewidth=0.8, linestyle=(0, (3, 2)),
                    alpha=0.75, zorder=6)
            lon, lat = lineament_lonlat(plan, lons, lats, x.point)
            ax.plot(lon, lat, marker="o", markersize=10, markerfacecolor="white", markeredgecolor=_PLAN_LINE,
                    markeredgewidth=1.6, zorder=7)
            ax.text(lon, lat, str(x.id), fontsize=6.5, fontweight="bold", color=_PLAN_LINE, ha="center",
                    va="center", zorder=8)
        if site is not None:
            _mark_site(ax, site, carto.SITE)
        handles = [
            Line2D([0], [0], color=_VALLEY_COLOUR, lw=2.0, label="Straight valley"),
            Line2D([0], [0], color=_RIDGE_COLOUR, lw=2.0, label="Straight ridge"),
            Line2D([0], [0], color=_PLAN_LINE, lw=2.0, label="Profiling line"),
            Line2D([0], [0], color=_PLAN_LINE, lw=0, marker="o", markersize=8, markerfacecolor="white",
                   markeredgewidth=1.6, label="Proposed sounding"),
            Line2D([0], [0], color=_PLAN_RING, lw=0.9, linestyle=(0, (2, 2)), label="Separation ring"),
            Line2D([0], [0], color=_PLAN_RADIUS, lw=1.2, linestyle=(0, (5, 3)), label="Service radius"),
        ]
        ax.legend(handles=handles, loc="upper left", fontsize=7, framealpha=0.85)
        ax.set_xlim(west, east)
        ax.set_ylim(south, north)
        below = _geo_axes_finish(ax, float(np.mean(lats[r_lo:r_hi + 1])), credit or _grid_credit(analysis.grid))
        _caveat(ax, below, f"{captions['plan_note']} {captions['figure_caveat']}")
        ax.set_title(captions["title_plan"])
        fig.tight_layout()
        return _finished(fig, path, style, svg)


def plot_ground_profile(
    chainage_m: list[float] | np.ndarray,
    elevation_m: list[float] | np.ndarray,
    labels: list[str] | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Ground surface along the survey traverse",
    grid: ElevationGrid | None = None,
    lonlats: list[tuple[float, float]] | None = None,
    max_gap_m: float | None = None,
):
    """The land surface along the traverse, from the survey's own levels.

    This is the honest topographic figure a survey can always draw: the
    elevations are measured at the pegs, and between them the line is
    drawn straight and says so. Where an elevation model is also
    supplied, its surface is drawn behind as a second line, so the two
    can be compared rather than silently averaged - a metre of
    disagreement over 200 m of traverse changes which end of the line
    the water runs to.

    ``max_gap_m`` is the widest gap the line is drawn across. Two levels
    further apart than that have nothing between them, and a straight
    line across the gap is a slope nobody measured: Rokel's was a 3 m fall
    drawn across 20.7 km. Such a gap is left open and the figure says so.
    """
    style = style or HouseStyle()
    chainage = np.asarray(chainage_m, dtype=float)
    elevation = np.asarray(elevation_m, dtype=float)
    if chainage.size != elevation.size:
        raise ValueError(
            f"{chainage.size} chainages and {elevation.size} elevations: a "
            "ground profile needs one elevation per station."
        )
    known = np.isfinite(elevation)
    if known.sum() < 2:
        raise ValueError(
            f"{int(known.sum())} of {elevation.size} stations carry an "
            "elevation. A ground profile needs at least two levelled "
            "points; record them on the field sheet."
        )
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 2.6))
        if grid is not None and lonlats is not None:
            modelled = np.array([
                grid.elevation_at(lon, lat) if grid.covers(lon, lat) else np.nan
                for lon, lat in lonlats
            ], dtype=float)
            if np.isfinite(modelled).sum() >= 2:
                ax.plot(chainage, modelled, "-", color="#888888", lw=1.2,
                        label=f"Elevation model ({grid.source})", zorder=2)
        # the levelled stations in runs the line may join: a gap wider than
        # max_gap_m starts a new run, so no line and no fill crosses it
        xs = chainage[known]
        ys = elevation[known]
        names = [name for name, k in zip(labels or [""] * chainage.size, known,
                                         strict=True) if k]
        runs: list[list[int]] = [[0]]
        open_gaps: list[str] = []
        for k in range(1, xs.size):
            gap = float(xs[k] - xs[k - 1])
            if max_gap_m is not None and gap > max_gap_m:
                runs.append([k])
                open_gaps.append(f"{names[k - 1] or 'station'} to "
                                 f"{names[k] or 'station'} ({gap:,.0f} m)")
            else:
                runs[-1].append(k)
        base = float(np.nanmin(elevation)) - 2.0
        for n_run, run in enumerate(runs):
            ax.plot(xs[run], ys[run], "-o", color=style.accent_color,
                    lw=1.8, ms=5, mfc="white", mew=1.4,
                    label="Levelled at the station" if n_run == 0 else None,
                    zorder=3)
            ax.fill_between(xs[run], ys[run], base,
                            color=style.accent_color, alpha=0.08, zorder=1)
        for x, y, label in zip(
            chainage, elevation, labels or [""] * chainage.size, strict=True
        ):
            if not math.isfinite(y) or not label:
                continue
            ax.annotate(label, xy=(x, y), xytext=(0, 7),
                        textcoords="offset points", ha="center", fontsize=7.5,
                        fontweight="bold", color="#222222")
        notes = []
        if known.sum() < elevation.size:
            notes.append(
                f"{int(elevation.size - known.sum())} of {elevation.size} "
                "stations recorded no elevation and are not drawn."
            )
        if open_gaps:
            notes.append(
                "The line is not drawn across " + "; ".join(open_gaps)
                + ": nothing was levelled between those stations."
            )
        if notes:
            ax.text(
                0.5, 0.02, textwrap.fill(" ".join(notes), 120),
                transform=ax.transAxes, ha="center", va="bottom", fontsize=7,
                color="#B00020",
            )
        ax.set_xlabel("Distance along traverse (m)")
        ax.set_ylabel("Elevation (m)")
        ax.set_title(title)
        ax.legend(loc="best", fontsize=7.5)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig

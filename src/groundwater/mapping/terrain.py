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
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize

from ..config import HouseStyle
from ..models import SiteMetadata
from ..plotting import figure_context, save_figure
from ..text import phrase
from .elevation import (  # noqa: F401 - the moved names, re-exported
    _HGT_SIDES,
    _READERS,
    _SRTM_VOID,
    ElevationGrid,
    ElevationRead,
    _bounds_text,
    grid_fill_probe,
    load_elevation,
    read_esri_ascii,
    read_srtm_hgt,
    read_xyz,
    wgs84_cell_size,
)
from .regional import (
    ADMIN_CREDIT,
    AreaWindow,
    _geo_axes_finish,
    _mark_site,
    area_window,
    load_admin,
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
    """Shaded relief from the grid, 0 (shadow) to 1 (lit).

    The standard north-west sun, because relief lit from any other
    quarter reads as inverted to most people - valleys become ridges.

    The cell size is computed in metres at the grid's own latitude, so
    the slopes are real slopes and not a function of how far north the
    tile happens to be.
    """
    mean_lat = float(np.mean(grid.lats))
    dx = float(np.mean(np.diff(grid.lons))) * 111320.0 * math.cos(math.radians(mean_lat))
    dy = float(np.mean(np.diff(grid.lats))) * 110574.0
    z = np.where(np.isfinite(grid.z), grid.z, np.nanmean(grid.z))
    if not np.any(np.isfinite(z)):
        return np.full(grid.z.shape, 0.5)
    gy, gx = np.gradient(z * vertical_exaggeration, dy, dx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az = math.radians(360.0 - azimuth_deg + 90.0)
    alt = math.radians(altitude_deg)
    shaded = (
        math.sin(alt) * np.cos(slope)
        + math.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    )
    return np.clip((shaded + 1.0) / 2.0, 0.0, 1.0)


def slope_percent(grid: ElevationGrid) -> np.ndarray:
    """Ground slope as a percentage, for siting and access notes."""
    mean_lat = float(np.mean(grid.lats))
    dx = float(np.mean(np.diff(grid.lons))) * 111320.0 * math.cos(math.radians(mean_lat))
    dy = float(np.mean(np.diff(grid.lats))) * 110574.0
    gy, gx = np.gradient(grid.z, dy, dx)
    return np.hypot(gx, gy) * 100.0


def _contour_interval(z: np.ndarray) -> float:
    """A round contour interval giving roughly a dozen lines.

    Sierra Leone's basement plains and the Freetown peninsula differ by
    two orders of magnitude in relief, so a fixed interval draws either
    two contours or four hundred.
    """
    finite = z[np.isfinite(z)]
    if finite.size == 0:
        return 10.0
    relief = float(finite.max() - finite.min())
    if relief <= 0:
        return 10.0
    target = relief / 12.0
    nice = 10 ** math.floor(math.log10(target))
    for mult in (10, 5, 2, 1):
        if nice * mult <= target * 2:
            return max(nice * mult, 1.0)
    return max(nice, 1.0)


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
            # hillshade() shades a gap as flat ground at the mean height;
            # left out here, a gap the files do not cover reads as a gap
            shade = np.where(np.isfinite(grid.z), hillshade(grid), np.nan)
            ax.imshow(
                shade, extent=extent, origin="lower", cmap="gray",
                alpha=0.35, interpolation="bilinear", zorder=2, aspect="auto",
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

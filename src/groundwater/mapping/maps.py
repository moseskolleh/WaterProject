"""Publication-quality static maps without heavy GIS dependencies.

Maps are drawn in projected UTM coordinates (metres), which keeps
scale bars honest. Administrative or geological boundary layers can be
overlaid from user-supplied GeoJSON files (in geographic WGS84
coordinates; they are projected on the fly). District boundary data
for Sierra Leone can be downloaded from GADM or HDX; the toolkit does
not bundle these datasets.

Every map gets a scale bar, north arrow, legend, coordinate grid and
the UTM zone note, per the house mapping rules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator
from scipy.interpolate import griddata

from ..config import HouseStyle
from ..geo import geographic_to_utm
from ..plotting import figure_context, save_figure


@dataclass
class MapPoint:
    label: str
    easting: float
    northing: float
    value: float | None = None  # attribute for interpolated maps
    kind: str = "VES point"
    #: 1 for the recommended drill target on a suitability map, so the
    #: figure can distinguish it from the alternatives
    rank: int | None = None


def points_enclose_an_area(e, n, tolerance: float = 1e-6) -> bool:
    """True when the points span a two-dimensional patch of ground.

    Three pegs on one line - the standard VES layout, and what a tape-and-
    compass traverse or chainages typed by hand produce exactly - enclose
    no area. Handed to a triangulation they raise a Qhull precision error,
    which is a RuntimeError and walked straight past every ``except
    ValueError`` between the map and the report, so the standard field
    layout took the whole geophysical report down. The test is the smaller
    singular value of the centred coordinates against the larger: below the
    tolerance the points are a line to numerical precision.
    """
    e = np.asarray(e, float)
    n = np.asarray(n, float)
    if len(e) < 3:
        return False
    coords = np.column_stack([e - e.mean(), n - n.mean()])
    singular = np.linalg.svd(coords, compute_uv=False)
    if singular[0] <= 0:
        return False
    return bool(singular[-1] / singular[0] > tolerance)


def _surface(e, n, v, gx, gy):
    """The interpolated surface, or None when the points cannot support one.

    The linear interpolant needs a triangulation, which needs an area; the
    nearest-neighbour fill outside it is what the maps show at the edges.
    Any triangulation failure is reported as "no surface" rather than as an
    exception, because the figure is one of several in a report and none
    of them should cost the document the others.
    """
    if not points_enclose_an_area(e, n):
        return None
    try:
        grid_lin = griddata((e, n), v, (gx, gy), method="linear")
        grid_near = griddata((e, n), v, (gx, gy), method="nearest")
    except Exception:  # noqa: BLE001 - Qhull raises a RuntimeError subclass
        return None
    return np.where(np.isnan(grid_lin), grid_near, grid_lin)


def _no_surface_note(ax, n_points: int) -> None:
    ax.text(
        0.5, 0.012,
        ("Surface not drawn: the survey points lie on one line and enclose "
         "no area, so only the values at the points are shown."
         if n_points >= 3 else
         "Surface not drawn: fewer than three points carry a value."),
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=7.5, color="#B00020", zorder=8,
    )


def _extent(points: list["MapPoint"], pad_frac=0.25, min_pad=150.0):
    e = np.array([p.easting for p in points])
    n = np.array([p.northing for p in points])
    pe = max((e.max() - e.min()) * pad_frac, min_pad)
    pn = max((n.max() - n.min()) * pad_frac, min_pad)
    pad = max(pe, pn)
    return e.min() - pad, e.max() + pad, n.min() - pad, n.max() + pad


def _figsize(style: HouseStyle, x0, x1, y0, y1) -> tuple[float, float]:
    """A figure shaped like the ground it shows.

    A fixed 5.4 in height squashed a traverse three times longer than it is
    wide into a strip a third of the figure tall, beside a colour bar that
    ran the full height. The height follows the extent's aspect within
    limits a page can hold.
    """
    aspect = (y1 - y0) / max(x1 - x0, 1e-9)
    height = style.figure_width_in * 0.82 * aspect + 0.9
    return style.figure_width_in, float(min(max(height, 3.4), 6.6))


def _scale_bar(ax, style: HouseStyle) -> None:
    """Draw a scale bar sized to a round number near 1/4 of the width."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    span = x1 - x0
    target = span / 4.0
    nice = 10 ** np.floor(np.log10(target))
    for mult in (5, 2, 1):
        if nice * mult <= target:
            nice *= mult
            break
    bx = x0 + span * 0.06
    by = y0 + (y1 - y0) * 0.05
    ax.plot([bx, bx + nice], [by, by], color="#222222", lw=3, solid_capstyle="butt")
    ax.plot([bx, bx + nice / 2], [by, by], color="white", lw=1.4, solid_capstyle="butt")
    label = f"{nice / 1000:g} km" if nice >= 1000 else f"{nice:g} m"
    ax.text(bx + nice / 2, by + (y1 - y0) * 0.015, label, ha="center", fontsize=8)


def _north_arrow(ax) -> None:
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    x = x1 - (x1 - x0) * 0.07
    y = y1 - (y1 - y0) * 0.16
    dy = (y1 - y0) * 0.09
    ax.annotate(
        "", xy=(x, y + dy), xytext=(x, y),
        arrowprops=dict(arrowstyle="-|>", color="#222222", lw=1.6),
    )
    ax.text(x, y + dy * 1.15, "N", ha="center", fontsize=10, fontweight="bold")


def _plot_boundary(ax, geojson_path: str | Path, zone: int, color="#888888") -> None:
    """Overlay polygon/line features from a WGS84 GeoJSON file."""
    with open(geojson_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    features = data.get("features", [data] if data.get("type") == "Feature" else [])

    def draw_ring(ring):
        coords = np.array(
            [
                (geographic_to_utm(lat, lon, zone).easting,
                 geographic_to_utm(lat, lon, zone).northing)
                for lon, lat in ring
            ]
        )
        ax.plot(coords[:, 0], coords[:, 1], color=color, lw=1.0)

    for feature in features:
        geom = feature.get("geometry", {})
        gtype = geom.get("type")
        coords = geom.get("coordinates", [])
        if gtype == "Polygon":
            for ring in coords:
                draw_ring(ring)
        elif gtype == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    draw_ring(ring)
        elif gtype == "LineString":
            draw_ring(coords)
        elif gtype == "MultiLineString":
            for line in coords:
                draw_ring(line)


def _format_grid(ax, zone: int) -> None:
    # at most five or six round-numbered grid lines an axis: a seven-digit
    # northing label every 25 m printed nine of them on top of one another
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]))
    ax.ticklabel_format(style="plain", useOffset=False)
    ax.tick_params(labelsize=7.5)
    for label in ax.get_yticklabels():
        label.set_rotation(90)
        label.set_va("center")
    ax.set_xlabel(f"Easting (m), UTM zone {zone}N / WGS84", fontsize=8.5)
    ax.set_ylabel("Northing (m)", fontsize=8.5)
    ax.grid(True, color="#CCCCCC", lw=0.5)
    ax.set_aspect("equal")


def _pad_limits(ax, points: list[MapPoint], pad_frac=0.25, min_pad=150.0) -> None:
    x0, x1, y0, y1 = _extent(points, pad_frac, min_pad)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)


def site_location_map(
    points: list[MapPoint],
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Site location map",
    boundary_geojson: str | Path | None = None,
):
    """Survey point location map on a UTM grid."""
    if not points:
        raise ValueError("site_location_map needs at least one survey point")
    style = style or HouseStyle()
    with figure_context(style):
        fig, ax = plt.subplots(figsize=_figsize(style, *_extent(points)))
        _pad_limits(ax, points)
        if boundary_geojson:
            _plot_boundary(ax, boundary_geojson, zone)
        kinds = {}
        markers = {"VES point": "o", "borehole": "^", "water point": "s"}
        for p in points:
            marker = markers.get(p.kind, "o")
            handle, = ax.plot(
                p.easting, p.northing, marker, ms=8, mfc=style.secondary_color,
                mec="white", mew=1.0, zorder=5,
            )
            kinds.setdefault(p.kind, handle)
            ax.annotate(
                p.label, xy=(p.easting, p.northing), xytext=(6, 6),
                textcoords="offset points", fontsize=8.5, fontweight="bold",
                color=style.accent_color,
            )
        _format_grid(ax, zone)
        _scale_bar(ax, style)
        _north_arrow(ax)
        ax.legend(kinds.values(), kinds.keys(), loc="lower right", fontsize=8)
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def _clip_to_surveyed_ground(ax, grid, e, n, gx, gy):
    """Blank the interpolated surface outside the ground the survey covered.

    An interpolated resistivity or thickness surface is read as data: a
    hydrogeologist looking at a contour 400 m from the nearest sounding will
    site a borehole on it. Outside the hull of the points there is no
    measurement behind the colour at all - it is the interpolator continuing a
    trend - so the surface is blanked there rather than drawn in a shade that
    looks like every other shade on the map.

    Points along a single traverse line enclose no area and so have no hull to
    clip to. That is an ordinary survey, not an error, so the surface is drawn
    and the figure says on its own face that the values away from the line are
    extrapolated. A caption can be skipped; a line across the middle of the
    figure cannot.
    """
    try:
        from matplotlib.path import Path as MplPath
        from scipy.spatial import ConvexHull

        hull = ConvexHull(np.column_stack([e, n]))
        poly = np.column_stack([e, n])[hull.vertices]
        inside = MplPath(poly).contains_points(
            np.column_stack([gx.ravel(), gy.ravel()])
        ).reshape(gx.shape)
        return np.where(inside, grid, np.nan), True
    except Exception:  # noqa: BLE001 - said on the map itself
        ax.text(
            0.5, 0.012,
            "Surface not clipped: the survey points enclose no "
            "area, so values away from them are extrapolated.",
            transform=ax.transAxes, ha="center", va="bottom",
            fontsize=7.5, color="#B00020", zorder=8,
        )
        return grid, False


def _interpolated_map(
    points: list[MapPoint],
    zone: int,
    title: str,
    cbar_label: str,
    path: str | Path | None,
    style: HouseStyle | None,
    log_scale: bool = False,
    cmap: str = "viridis",
):
    style = style or HouseStyle()
    valued = [p for p in points if p.value is not None]
    if len(valued) < 3:
        raise ValueError(
            "Interpolated maps need at least three points with values; "
            f"got {len(valued)}. Produce a site location map instead."
        )
    e = np.array([p.easting for p in valued])
    n = np.array([p.northing for p in valued])
    v = np.array([p.value for p in valued], dtype=float)
    if log_scale:
        v = np.log10(v)
    pad = max(max(e.max() - e.min(), n.max() - n.min()) * 0.25, 100.0)
    gx, gy = np.meshgrid(
        np.linspace(e.min() - pad, e.max() + pad, 220),
        np.linspace(n.min() - pad, n.max() + pad, 220),
    )
    grid = _surface(e, n, v, gx, gy)

    with figure_context(style):
        fig, ax = plt.subplots(
            figsize=_figsize(style, gx.min(), gx.max(), gy.min(), gy.max()))
        if grid is not None:
            grid, _clipped = _clip_to_surveyed_ground(ax, grid, e, n, gx, gy)
            cs = ax.contourf(gx, gy, grid, levels=12, cmap=cmap, alpha=0.9)
            ax.contour(gx, gy, grid, levels=cs.levels, colors="white", linewidths=0.5)
            cbar = fig.colorbar(cs, ax=ax, pad=0.02, shrink=0.85)
            if log_scale:
                ticks = cbar.get_ticks()
                cbar.set_ticks(ticks)
                cbar.set_ticklabels([f"{10**t:.0f}" for t in ticks])
            cbar.set_label(cbar_label)
        else:
            # a line of pegs: the values are printed at the points instead
            _no_surface_note(ax, len(valued))
        for p in valued:
            ax.plot(p.easting, p.northing, "o", ms=7, mfc="white",
                    mec="#222222", mew=1.2, zorder=5)
            text = p.label
            if grid is None:
                # p.value is the value as measured; only the gridded array was
                # ever log10'd. Exponentiating it again labelled a 250 ohm-m
                # point "1e+250", and a 1000 ohm-m point raised OverflowError,
                # which is neither ValueError nor RuntimeError and so walked
                # past the geophysical report's per-figure guard and took the
                # whole document down.
                shown = p.value
                text += f"\n{shown:.3g}" if shown is not None else ""
            ax.annotate(
                text, xy=(p.easting, p.northing), xytext=(6, 6),
                textcoords="offset points", fontsize=8.5, fontweight="bold",
                color="#222222",
            )
        ax.set_xlim(gx.min(), gx.max())
        ax.set_ylim(gy.min(), gy.max())
        _format_grid(ax, zone)
        _scale_bar(ax, style)
        _north_arrow(ax)
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def suitability_map(
    points: list[MapPoint],
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Drill-target suitability",
):
    """Drill-target suitability map from scored VES points.

    Each point carries its confidence-weighted suitability as ``value``
    (the number the ranking is decided on), its grade as ``kind`` and its
    rank. Points are coloured red (poor) to green (good). The recommended
    target - rank 1 - is drawn as a star with its grid coordinates written
    beside it, because the point of this map is that somebody walks to
    that peg and not to the other one; two points that cannot be told
    apart on geophysical grounds are said to be a tie. With three or more
    points that enclose an area a suitability surface is interpolated,
    masked to the convex hull of the surveyed points so it never
    extrapolates a drill-target confidence beyond where data exists.
    """
    style = style or HouseStyle()
    valued = [p for p in points if p.value is not None]
    if not points:
        raise ValueError("suitability_map needs at least one point")
    cmap = plt.get_cmap("RdYlGn")
    with figure_context(style):
        fig, ax = plt.subplots(figsize=_figsize(style, *_extent(points)))
        _pad_limits(ax, points)
        if len(valued) >= 3:
            e = np.array([p.easting for p in valued])
            n = np.array([p.northing for p in valued])
            v = np.array([p.value for p in valued], dtype=float)
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            gx, gy = np.meshgrid(np.linspace(x0, x1, 200), np.linspace(y0, y1, 200))
            grid = _surface(e, n, v, gx, gy)
            if grid is not None:
                grid, _clipped = _clip_to_surveyed_ground(ax, grid, e, n, gx, gy)
                cs = ax.contourf(
                    gx, gy, grid, levels=np.linspace(0, 100, 11),
                    cmap=cmap, alpha=0.75, vmin=0, vmax=100,
                )
                cbar = fig.colorbar(cs, ax=ax, pad=0.02, shrink=0.85)
                cbar.set_label("Drilling suitability, confidence weighted (0-100)")
            else:
                _no_surface_note(ax, len(valued))
        ranked = sorted((p for p in valued if p.rank is not None), key=lambda p: p.rank)
        tie = (
            len(ranked) >= 2
            and abs(float(ranked[0].value) - float(ranked[1].value)) < 3.0
        )
        handles: dict[str, object] = {}
        for p in points:
            colour = cmap(p.value / 100.0) if p.value is not None else "#888888"
            recommended = p.rank == 1 and not tie
            marker = "*" if recommended else "o"
            handle, = ax.plot(
                p.easting, p.northing, marker, ms=20 if recommended else 12,
                mfc=colour, mec="#222222", mew=1.3, zorder=6,
            )
            handles.setdefault(
                "recommended drill target" if recommended else "surveyed point",
                handle,
            )
            label = p.label
            if p.value is not None:
                label += f"\n{p.value:.0f} - {p.kind}"
            if recommended:
                label += f"\nE {p.easting:.0f}  N {p.northing:.0f}"
            ax.annotate(
                label, xy=(p.easting, p.northing), xytext=(11, 6),
                textcoords="offset points", fontsize=8.5,
                fontweight="bold" if recommended else "normal",
                color="#222222", zorder=7,
            )
        if tie:
            ax.text(
                0.5, 0.965,
                f"{ranked[0].label} and {ranked[1].label} are indistinguishable on "
                "geophysical grounds; choose between them on access and sanitary distances.",
                transform=ax.transAxes, ha="center", va="top", fontsize=7.5,
                color="#B00020", zorder=8,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.9),
            )
        _format_grid(ax, zone)
        _scale_bar(ax, style)
        _north_arrow(ax)
        if handles:
            ax.legend(handles.values(), handles.keys(), loc="lower right", fontsize=7.5,
                      framealpha=0.95)
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def suitability_map_state(points: list[MapPoint]) -> dict:
    """What a suitability map of these points will show, for its caption.

    A caption used to promise "the interpolated surface is blanked outside
    the ground the survey covered" over a figure of two dots with no
    surface at all. The caption is written from this, so it describes the
    figure it sits under.
    """
    valued = [p for p in points if p.value is not None]
    e = [p.easting for p in valued]
    n = [p.northing for p in valued]
    ranked = sorted((p for p in valued if p.rank is not None), key=lambda p: p.rank)
    return {
        "n_points": len(valued),
        "surface": len(valued) >= 3 and points_enclose_an_area(e, n),
        "tie": (len(ranked) >= 2
                and abs(float(ranked[0].value) - float(ranked[1].value)) < 3.0),
        "recommended": ranked[0].label if ranked else None,
    }


def iso_resistivity_map(
    points: list[MapPoint],
    zone: int,
    ab2: float,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
):
    """Iso-apparent-resistivity map for one AB/2 spacing.

    ``points`` carry the apparent resistivity at that spacing as their
    value. Needs at least three sounding positions.
    """
    return _interpolated_map(
        points,
        zone,
        title=f"Iso-resistivity map at AB/2 = {ab2:g} m",
        cbar_label="Apparent resistivity (ohm-m)",
        path=path,
        style=style,
        log_scale=True,
    )


def overburden_thickness_map(
    points: list[MapPoint],
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
):
    """Overburden (depth to bedrock) thickness map from the VES models."""
    return _interpolated_map(
        points,
        zone,
        title="Overburden thickness map",
        cbar_label="Overburden thickness (m)",
        path=path,
        style=style,
        log_scale=False,
        cmap="YlGnBu",
    )

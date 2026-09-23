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
import textwrap
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator
from scipy.interpolate import griddata

from ..config import HouseStyle, VESConfig
from ..geo import geographic_to_utm, infer_zone_for_sierra_leone, utm_to_geographic
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
    #: True when ``value`` is a lower bound rather than a measurement: an
    #: aquifer thickness at a sounding that never reached the base of its
    #: water-bearing zone. The map labels it "at least", because a contour
    #: through it reads as the thickness itself.
    minimum: bool = False


def to_zone(easting: float, northing: float, zone: int) -> tuple[float, float]:
    """A recorded position re-expressed in the UTM zone ``zone``.

    Sierra Leone straddles the 28N/29N boundary at 12 degrees W, and a
    survey on that line can record its soundings in both zones: 829580 E in
    zone 28 and 170420 E in zone 29 are 400 m apart on the ground and 659 km
    apart as numbers. Every survey-scale figure subtracts eastings, so each
    sounding is brought into one zone, through its latitude and longitude,
    before any of them is drawn. The zone a position was recorded in is
    read off its easting, which in Sierra Leone identifies it.
    """
    own = infer_zone_for_sierra_leone(float(easting))
    if own == zone:
        return float(easting), float(northing)
    lat, lon = utm_to_geographic(float(easting), float(northing), own)
    utm = geographic_to_utm(lat, lon, zone)
    return utm.easting, utm.northing


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
    # northing label every 25 m printed nine of them on top of one another.
    # The northings are printed on end, and one is about half an inch long,
    # so the northing axis gets no more grid lines than its drawn height
    # holds: an elongated survey's map is an inch tall, and five northings
    # on it still ran into each other.
    ax.set_aspect("equal")
    ax.apply_aspect()
    height_in = ax.get_position().height * ax.figure.get_figheight()
    y_bins = int(min(5, max(1, height_in // 0.6)))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=y_bins, steps=[1, 2, 2.5, 5, 10]))
    ax.ticklabel_format(style="plain", useOffset=False)
    ax.tick_params(labelsize=7.5)
    for label in ax.get_yticklabels():
        label.set_rotation(90)
        label.set_va("center")
    ax.set_xlabel(f"Easting (m), UTM zone {zone}N / WGS84", fontsize=8.5)
    ax.set_ylabel("Northing (m)", fontsize=8.5)
    ax.grid(True, color="#CCCCCC", lw=0.5)
    ax.set_aspect("equal")


def _colour_bar(fig, ax, mappable):
    """A colour bar exactly as tall as the map it sits beside.

    Sized as a share of the figure, the bar kept the height of the space
    the map was given rather than of the map, and a map of an elongated
    survey - drawn an inch tall to keep a metre east equal to a metre
    north - stood beside a bar three times its height. A bar cut from the
    map's own side follows the map.
    """
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    cax = make_axes_locatable(ax).append_axes("right", size="3.5%", pad=0.08)
    return fig.colorbar(mappable, cax=cax)


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


def interpolated_label(p: MapPoint, surface: bool) -> str:
    """What an interpolated map writes beside a point."""
    text = p.label
    if p.minimum:
        # a lower bound is said to be one beside its peg whether or not a
        # surface is drawn: the contour there is a floor, and without the
        # words it reads as the value itself
        text += f"\nat least {p.value:.3g}"
    elif not surface and p.value is not None:
        # p.value is the value as measured; only the gridded array was ever
        # log10'd. Exponentiating it again labelled a 250 ohm-m point
        # "1e+250", and a 1000 ohm-m point raised OverflowError, which is
        # neither ValueError nor RuntimeError and so walked past the
        # geophysical report's per-figure guard and took the whole document
        # down.
        text += f"\n{p.value:.3g}"
    return text


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
            cbar = _colour_bar(fig, ax, cs)
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
            ax.annotate(
                interpolated_label(p, grid is not None),
                xy=(p.easting, p.northing), xytext=(6, 6),
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


def _suitability_ranking(
    points: list[MapPoint],
    tie: bool | None = None,
    ranking: list[str] | None = None,
) -> dict:
    """What the ranking lets a suitability map say about which peg to drill.

    ``tie`` is the ranking's own verdict on its two leaders, from
    :func:`groundwater.siting.ranking_tie` with the project's
    ``ranking_tie_points``. The map used to decide it again, three points
    apart on the rounded values it prints, and a project with a different
    tie margin got a report calling two points indistinguishable over a map
    that starred one of them. Left unset, as by a caller drawing points on
    their own, it is decided here by the same rule on the points' values,
    and only between the points ranked first and second.

    ``ranking`` is every scored sounding in rank order, placed or not. The
    points on the map are only the ones with a recorded position, and a
    recommended point that has none is not on the map at all: the caption
    used to promise a star over a map with no star on it, naming the
    runner-up as the target. Left unset, every ranked point is taken to be
    on the map.
    """
    valued = [p for p in points if p.value is not None]
    ranked = sorted((p for p in valued if p.rank is not None), key=lambda p: p.rank)
    if ranking is None:
        ranking = [p.label for p in ranked]
    if tie is None:
        tie = (
            len(ranked) >= 2 and ranked[0].rank == 1 and ranked[1].rank == 2
            and abs(float(ranked[0].value) - float(ranked[1].value))
            < VESConfig().ranking_tie_points
        )
    leaders = list(ranking[: 2 if tie else 1])
    on_map = {p.label for p in points}
    unplaced = [label for label in leaders if label not in on_map]
    return {
        "tie": bool(tie),
        "leaders": leaders,
        "unplaced": unplaced,
        "recommended": leaders[0] if leaders and not tie and not unplaced else None,
    }


def unplaced_text(unplaced: list[str], where: str = "this map") -> str:
    """The sentence a map owes its reader for a leading point it cannot show."""
    if not unplaced:
        return ""
    if len(unplaced) == 1:
        return f"{unplaced[0]} has no recorded position and is not on {where}."
    return (f"{' and '.join(unplaced)} have no recorded position and are not "
            f"on {where}.")


def suitability_map(
    points: list[MapPoint],
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Drill-target suitability",
    tie: bool | None = None,
    ranking: list[str] | None = None,
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

    ``tie`` and ``ranking`` are the ranking's own verdict and order, as
    :func:`_suitability_ranking` reads them; a report passes both, so the
    map, its caption and the text around it say the same thing.

    Each point is labelled with its rank and weighted score, and with its
    grade named as the grade of its suitability. The label used to pair
    the weighted score with that grade - "29 - Good" - when 29 is Poor on
    the grade's own scale: the grade is of the score before the confidence
    discount, and the label now says which score it grades.
    """
    style = style or HouseStyle()
    valued = [p for p in points if p.value is not None]
    if not points:
        raise ValueError("suitability_map needs at least one point")
    verdict = _suitability_ranking(points, tie, ranking)
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
                cbar = _colour_bar(fig, ax, cs)
                cbar.set_label("Drilling suitability, confidence weighted (0-100)")
            else:
                _no_surface_note(ax, len(valued))
        handles: dict[str, object] = {}
        for p in points:
            colour = cmap(p.value / 100.0) if p.value is not None else "#888888"
            recommended = p.rank == 1 and not verdict["tie"]
            marker = "*" if recommended else "o"
            handle, = ax.plot(
                p.easting, p.northing, marker, ms=20 if recommended else 12,
                mfc=colour, mec="#222222", mew=1.3, zorder=6,
            )
            handles.setdefault(
                "recommended drill target" if recommended else "surveyed point",
                handle,
            )
            ax.annotate(
                suitability_label(p, recommended), xy=(p.easting, p.northing),
                xytext=(11, 6),
                textcoords="offset points", fontsize=8.5,
                fontweight="bold" if recommended else "normal",
                color="#222222", zorder=7,
            )
        note = suitability_map_note(verdict)
        if note:
            # why there is no star, on the face of the map: a reader who sees
            # the pegs and no star reads the omission as an oversight. Kept
            # narrow and left of centre, clear of the north arrow.
            ax.text(
                0.46, 0.965, textwrap.fill(note, 70),
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


def suitability_label(p: MapPoint, recommended: bool) -> str:
    """What a suitability map writes beside a point.

    The rank and the weighted score, and the grade named as the grade of
    the suitability; the grid coordinates too at the recommended target.
    """
    label = p.label
    if p.value is not None:
        label += ("\n" + (f"Rank {p.rank}, " if p.rank is not None else "")
                  + f"weighted {p.value:.0f}\n{p.kind} suitability")
    if recommended:
        label += f"\nE {p.easting:.0f}  N {p.northing:.0f}"
    return label


def suitability_map_note(verdict: dict) -> str:
    """The line across the top of a suitability map that has no star."""
    if verdict["tie"]:
        note = (
            f"{verdict['leaders'][0]} and {verdict['leaders'][1]} are "
            "indistinguishable on geophysical grounds; choose between them on "
            "access and sanitary distances."
        )
        if verdict["unplaced"]:
            note += " " + unplaced_text(verdict["unplaced"])
        return note
    if verdict["unplaced"]:
        return (f"The recommended point, {verdict['unplaced'][0]}, has no recorded "
                "position and is not on this map.")
    return ""


def suitability_map_state(
    points: list[MapPoint],
    tie: bool | None = None,
    ranking: list[str] | None = None,
) -> dict:
    """What a suitability map of these points will show, for its caption.

    A caption used to promise "the interpolated surface is blanked outside
    the ground the survey covered" over a figure of two dots with no
    surface at all, and "the star is the recommended target" over a map
    whose recommended point had no position and so no star. The caption is
    written from this, so it describes the figure it sits under. ``tie``
    and ``ranking`` are the ones the map is drawn with.
    """
    valued = [p for p in points if p.value is not None]
    e = [p.easting for p in valued]
    n = [p.northing for p in valued]
    return {
        "n_points": len(valued),
        "surface": len(valued) >= 3 and points_enclose_an_area(e, n),
        **_suitability_ranking(points, tie, ranking),
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

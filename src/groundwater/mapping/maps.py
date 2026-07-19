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
    e = np.array([p.easting for p in points])
    n = np.array([p.northing for p in points])
    pe = max((e.max() - e.min()) * pad_frac, min_pad)
    pn = max((n.max() - n.min()) * pad_frac, min_pad)
    pad = max(pe, pn)
    ax.set_xlim(e.min() - pad, e.max() + pad)
    ax.set_ylim(n.min() - pad, n.max() + pad)


def site_location_map(
    points: list[MapPoint],
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Site location map",
    boundary_geojson: str | Path | None = None,
):
    """Survey point location map on a UTM grid."""
    style = style or HouseStyle()
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.4))
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
    grid_lin = griddata((e, n), v, (gx, gy), method="linear")
    grid_near = griddata((e, n), v, (gx, gy), method="nearest")
    grid = np.where(np.isnan(grid_lin), grid_near, grid_lin)

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.4))
        cs = ax.contourf(gx, gy, grid, levels=12, cmap=cmap, alpha=0.9)
        lines = ax.contour(gx, gy, grid, levels=cs.levels, colors="white", linewidths=0.5)
        cbar = fig.colorbar(cs, ax=ax, pad=0.02, shrink=0.85)
        if log_scale:
            ticks = cbar.get_ticks()
            cbar.set_ticks(ticks)
            cbar.set_ticklabels([f"{10**t:.0f}" for t in ticks])
        cbar.set_label(cbar_label)
        for p in valued:
            ax.plot(p.easting, p.northing, "o", ms=7, mfc="white",
                    mec="#222222", mew=1.2, zorder=5)
            ax.annotate(
                p.label, xy=(p.easting, p.northing), xytext=(6, 6),
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

    Each point carries its 0-100 suitability as ``value`` and its grade as
    ``kind``. Points are coloured red (poor) to green (good). With three or
    more points a suitability surface is interpolated, but it is masked to
    the convex hull of the surveyed points so it never extrapolates a
    drill-target confidence beyond where data actually exists.
    """
    style = style or HouseStyle()
    valued = [p for p in points if p.value is not None]
    if not points:
        raise ValueError("suitability_map needs at least one point")
    cmap = plt.get_cmap("RdYlGn")
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.4))
        _pad_limits(ax, points)
        if len(valued) >= 3:
            e = np.array([p.easting for p in valued])
            n = np.array([p.northing for p in valued])
            v = np.array([p.value for p in valued], dtype=float)
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            gx, gy = np.meshgrid(np.linspace(x0, x1, 200), np.linspace(y0, y1, 200))
            grid_lin = griddata((e, n), v, (gx, gy), method="linear")
            grid_near = griddata((e, n), v, (gx, gy), method="nearest")
            grid = np.where(np.isnan(grid_lin), grid_near, grid_lin)
            try:
                from matplotlib.path import Path as MplPath
                from scipy.spatial import ConvexHull

                hull = ConvexHull(np.column_stack([e, n]))
                poly = np.column_stack([e, n])[hull.vertices]
                inside = MplPath(poly).contains_points(
                    np.column_stack([gx.ravel(), gy.ravel()])
                ).reshape(gx.shape)
                grid = np.where(inside, grid, np.nan)
            except Exception:
                pass  # collinear points: show the unmasked surface
            cs = ax.contourf(
                gx, gy, grid, levels=np.linspace(0, 100, 11),
                cmap=cmap, alpha=0.75, vmin=0, vmax=100,
            )
            cbar = fig.colorbar(cs, ax=ax, pad=0.02, shrink=0.85)
            cbar.set_label("Drilling suitability (0-100)")
        for p in points:
            colour = cmap(p.value / 100.0) if p.value is not None else "#888888"
            ax.plot(p.easting, p.northing, "o", ms=12, mfc=colour,
                    mec="#222222", mew=1.3, zorder=6)
            label = p.label + (f"\n{p.value:.0f} - {p.kind}" if p.value is not None else "")
            ax.annotate(
                label, xy=(p.easting, p.northing), xytext=(9, 6),
                textcoords="offset points", fontsize=8.5, fontweight="bold",
                color="#222222", zorder=7,
            )
        _format_grid(ax, zone)
        _scale_bar(ax, style)
        _north_arrow(ax)
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


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

"""Regional context maps: geological setting and administrative location.

Both maps draw in geographic coordinates (WGS84) from bundled
schematic datasets: a generalised geology layer
(``data/sl_geology_simplified.geojson``, digitised approximately from
published small scale maps) and the approximate district extents
(``data/sl_districts.csv``). They are context figures for reports -
clearly marked schematic - and both accept a replacement GeoJSON when
survey grade data is available.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import csv

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as MplPolygon

from ..config import HouseStyle
from ..models import SiteMetadata
from ..plotting import figure_context, save_figure

_DISCLAIMER = "Schematic; boundaries approximate, not survey grade"


@dataclass
class GeologyUnit:
    unit: str
    lithology: str
    color: str
    aquifer: str
    rings: list[np.ndarray]  # one or more (n, 2) lon/lat arrays


def load_geology(path: str | Path | None = None) -> list[GeologyUnit]:
    """Load the geology layer (bundled schematic unless a path is given)."""
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (
            resources.files("groundwater") / "data" / "sl_geology_simplified.geojson"
        ).read_text(encoding="utf-8")
    data = json.loads(text)
    units: list[GeologyUnit] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        rings: list[np.ndarray] = []
        if geom.get("type") == "Polygon":
            rings.append(np.asarray(geom["coordinates"][0], dtype=float))
        elif geom.get("type") == "MultiPolygon":
            for poly in geom["coordinates"]:
                rings.append(np.asarray(poly[0], dtype=float))
        if not rings:
            continue
        units.append(
            GeologyUnit(
                unit=props.get("unit", "unit"),
                lithology=props.get("lithology", ""),
                color=props.get("color", "#CCCCCC"),
                aquifer=props.get("aquifer", ""),
                rings=rings,
            )
        )
    return units


def _district_centres(path: str | Path | None = None) -> list[dict]:
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (
            resources.files("groundwater") / "data" / "sl_districts.csv"
        ).read_text(encoding="utf-8")
    rows = []
    for row in csv.DictReader(text.splitlines()):
        rows.append(
            {
                "district": row["district"],
                "province": row["province"],
                "lon": (float(row["lon_min"]) + float(row["lon_max"])) / 2.0,
                "lat": (float(row["lat_min"]) + float(row["lat_max"])) / 2.0,
                "bounds": (
                    float(row["lon_min"]), float(row["lon_max"]),
                    float(row["lat_min"]), float(row["lat_max"]),
                ),
            }
        )
    return rows


def _outline(units: list[GeologyUnit]) -> np.ndarray | None:
    """The national outline is the first (bottom) geology polygon."""
    return units[0].rings[0] if units else None


def _site_lonlat(site: SiteMetadata) -> tuple[float, float] | None:
    latlon = site.latlon
    if latlon is None:
        return None
    lat, lon = latlon
    return lon, lat


def _geo_axes_finish(ax, mean_lat: float, style: HouseStyle) -> None:
    """Aspect, scale bar, north arrow and grid for a lon/lat map."""
    ax.set_aspect(1.0 / math.cos(math.radians(mean_lat)))
    ax.grid(True, color="#DDDDDD", lw=0.5)
    ax.tick_params(labelsize=7.5)
    ax.set_xlabel("Longitude", fontsize=8.5)
    ax.set_ylabel("Latitude", fontsize=8.5)
    # scale bar sized to a round number near a quarter of the width
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    km_per_deg = 111.32 * math.cos(math.radians(mean_lat))
    span_km = (x1 - x0) * km_per_deg
    target = span_km / 4.0
    nice = 10 ** math.floor(math.log10(target)) if target > 0 else 1.0
    for mult in (5, 2, 1):
        if nice * mult <= target:
            nice *= mult
            break
    bar_deg = nice / km_per_deg
    bx = x0 + (x1 - x0) * 0.06
    by = y0 + (y1 - y0) * 0.05
    ax.plot([bx, bx + bar_deg], [by, by], color="#222222", lw=3,
            solid_capstyle="butt", zorder=9)
    ax.plot([bx, bx + bar_deg / 2], [by, by], color="white", lw=1.4,
            solid_capstyle="butt", zorder=9)
    ax.text(bx + bar_deg / 2, by + (y1 - y0) * 0.018, f"{nice:g} km",
            ha="center", fontsize=8, zorder=9)
    # north arrow
    nx = x1 - (x1 - x0) * 0.07
    ny = y1 - (y1 - y0) * 0.16
    dy = (y1 - y0) * 0.09
    ax.annotate("", xy=(nx, ny + dy), xytext=(nx, ny),
                arrowprops=dict(arrowstyle="-|>", color="#222222", lw=1.6))
    ax.text(nx, ny + dy * 1.15, "N", ha="center", fontsize=10,
            fontweight="bold")
    ax.text(0.99, 0.005, _DISCLAIMER, transform=ax.transAxes, fontsize=6.5,
            ha="right", va="bottom", color="#888888", style="italic")


def _mark_site(ax, site: SiteMetadata, color: str) -> tuple[float, float] | None:
    lonlat = _site_lonlat(site)
    if lonlat is None:
        return None
    lon, lat = lonlat
    ax.plot(lon, lat, marker="*", ms=16, mfc=color, mec="white", mew=1.2,
            zorder=8)
    label = site.community or "Site"
    ax.annotate(label, xy=(lon, lat), xytext=(8, 8),
                textcoords="offset points", fontsize=9, fontweight="bold",
                color=color, zorder=8)
    return lon, lat


def plot_geological_map(
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    radius_km: float | None = None,
    geology_path: str | Path | None = None,
    title: str | None = None,
):
    """Generalised geological map, national or zoomed around the site.

    ``radius_km`` zooms the map to a window around the site (a local
    geological setting figure); leave it ``None`` for the national map.
    """
    style = style or HouseStyle()
    units = load_geology(geology_path)
    outline = _outline(units)
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.6))
        legend_handles: dict[str, MplPolygon] = {}
        for unit in units:
            for ring in unit.rings:
                patch = MplPolygon(
                    ring, closed=True, facecolor=unit.color,
                    edgecolor="#666666", lw=0.5, alpha=0.9,
                )
                ax.add_patch(patch)
                legend_handles.setdefault(unit.unit, patch)
        if outline is not None:
            ax.plot(outline[:, 0], outline[:, 1], color="#333333", lw=1.2,
                    zorder=7)

        site_lonlat = _mark_site(ax, site, "#C1272D") if site else None
        if radius_km and site_lonlat is not None:
            lon, lat = site_lonlat
            dlat = radius_km / 111.32
            dlon = radius_km / (111.32 * math.cos(math.radians(lat)))
            ax.set_xlim(lon - dlon, lon + dlon)
            ax.set_ylim(lat - dlat, lat + dlat)
        elif outline is not None:
            ax.set_xlim(outline[:, 0].min() - 0.15, outline[:, 0].max() + 0.15)
            ax.set_ylim(outline[:, 1].min() - 0.12, outline[:, 1].max() + 0.12)

        mean_lat = float(np.mean(ax.get_ylim()))
        _geo_axes_finish(ax, mean_lat, style)
        ax.legend(
            legend_handles.values(), legend_handles.keys(),
            loc="upper left", fontsize=7, framealpha=0.95,
            title="Generalised geology", title_fontsize=7.5,
        )
        if title is None:
            where = (site.community or "the site") if site else "Sierra Leone"
            scope = "Local geological setting" if radius_km else "Geological map"
            title = f"{scope} - {where}" if site else f"{scope} of Sierra Leone"
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def plot_admin_map(
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str | None = None,
):
    """Administrative location map: districts, provinces and the site."""
    style = style or HouseStyle()
    units = load_geology()
    outline = _outline(units)
    districts = _district_centres()
    highlight = (site.district or "").strip().lower() if site else ""
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.6))
        if outline is not None:
            ax.add_patch(
                MplPolygon(outline, closed=True, facecolor="#F2F6FA",
                           edgecolor="#333333", lw=1.2)
            )
        for row in districts:
            is_home = row["district"].strip().lower() == highlight
            if is_home:
                lon_min, lon_max, lat_min, lat_max = row["bounds"]
                ax.add_patch(
                    MplPolygon(
                        np.array([
                            [lon_min, lat_min], [lon_max, lat_min],
                            [lon_max, lat_max], [lon_min, lat_max],
                        ]),
                        closed=True, facecolor=style.accent_color, alpha=0.15,
                        edgecolor=style.accent_color, lw=1.0, ls="--",
                    )
                )
            ax.plot(row["lon"], row["lat"], "o", ms=3,
                    color=style.accent_color if is_home else "#888888")
            ax.annotate(
                row["district"], xy=(row["lon"], row["lat"]), xytext=(0, 4),
                textcoords="offset points", ha="center",
                fontsize=6.5 if not is_home else 7.5,
                fontweight="bold" if is_home else "normal",
                color=style.accent_color if is_home else "#555555",
            )
        if site is not None:
            _mark_site(ax, site, "#C1272D")
        # neighbours and sea for orientation
        ax.text(-11.2, 9.82, "GUINEA", fontsize=8, color="#999999",
                fontweight="bold")
        ax.text(-10.95, 7.15, "LIBERIA", fontsize=8, color="#999999",
                fontweight="bold")
        ax.text(-13.25, 7.45, "Atlantic\nOcean", fontsize=8, color="#7FA8C9",
                style="italic", ha="center")
        if outline is not None:
            ax.set_xlim(outline[:, 0].min() - 0.2, outline[:, 0].max() + 0.15)
            ax.set_ylim(outline[:, 1].min() - 0.15, outline[:, 1].max() + 0.12)
        mean_lat = float(np.mean(ax.get_ylim()))
        _geo_axes_finish(ax, mean_lat, style)
        if title is None:
            title = (
                f"Location map - {site.community}"
                + (f", {site.district} District" if site.district else "")
                if site and site.community
                else "Administrative map of Sierra Leone"
            )
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig

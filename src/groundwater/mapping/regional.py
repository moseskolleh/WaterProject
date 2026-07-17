"""Regional context maps: geological setting and administrative location.

Both maps draw from real, freely licensed datasets bundled as package
data (see ``web/build_geodata.py`` for the reproducible preparation):

- ``data/sl_geology_usgs.geojson``: the USGS Geologic Map of Africa
  (geo2_7g, Open-File Report 97-470A; public domain, 1:5,000,000
  scale) clipped to the Sierra Leone window, keeping the dataset's
  own unit codes, names, eras and colours.
- ``data/sl_admin_geoboundaries.geojson``: national outline and
  district polygons from geoBoundaries (CC BY 4.0). The release
  predates the 2017 creation of Karene and Falaba districts.

Every figure carries the attribution of its sources. Both loaders
accept a replacement GeoJSON path, so newer or survey grade data can
be dropped in without code changes.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

from ..config import HouseStyle
from ..models import SiteMetadata
from ..plotting import figure_context, save_figure

GEOLOGY_CREDIT = "Geology: USGS Geologic Map of Africa (1:5M), public domain"
HYDRO_CREDIT = (
    "Hydrogeology: BGS Africa Groundwater Atlas (OR/21/063), CC BY-SA 4.0"
)
ADMIN_CREDIT = (
    "Boundaries: geoBoundaries, CC BY 4.0 (predates the 2017 "
    "Karene and Falaba districts)"
)

# Order for the geology legend, oldest last.
_ERA_ORDER = ("Cenozoic", "Mesozoic", "Paleozoic", "Precambrian", "Non-geological")


@dataclass
class GeologyUnit:
    """One polygon of the geological map."""

    glg: str  # USGS unit code, e.g. "pCm"
    unit: str  # unit name from the dataset, e.g. "Precambrian"
    era: str
    color: str
    ring: np.ndarray  # (n, 2) lon/lat outer ring


@dataclass
class AdminArea:
    level: str  # "ADM0" | "ADM2"
    name: str
    rings: list[np.ndarray] = field(default_factory=list)

    @property
    def label_point(self) -> tuple[float, float]:
        """Centroid of the largest ring (shoelace)."""
        best = max(self.rings, key=lambda r: abs(_ring_area(r)))
        return _ring_centroid(best)


def _ring_area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def _ring_centroid(ring: np.ndarray) -> tuple[float, float]:
    x, y = ring[:, 0], ring[:, 1]
    cross = x[:-1] * y[1:] - x[1:] * y[:-1]
    area = np.sum(cross) / 2.0
    if abs(area) < 1e-12:
        return float(x.mean()), float(y.mean())
    cx = np.sum((x[:-1] + x[1:]) * cross) / (6.0 * area)
    cy = np.sum((y[:-1] + y[1:]) * cross) / (6.0 * area)
    return float(cx), float(cy)


def _read_geojson(name: str, path: str | Path | None) -> dict:
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (resources.files("groundwater") / "data" / name).read_text(
            encoding="utf-8"
        )
    return json.loads(text)


def load_geology(path: str | Path | None = None) -> list[GeologyUnit]:
    """The USGS geology polygons for the Sierra Leone window."""
    data = _read_geojson("sl_geology_usgs.geojson", path)
    units: list[GeologyUnit] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        polys = (
            geom["coordinates"]
            if geom.get("type") == "MultiPolygon"
            else [geom.get("coordinates", [])]
        )
        for poly in polys:
            if not poly:
                continue
            units.append(
                GeologyUnit(
                    glg=props.get("glg", ""),
                    unit=props.get("unit", props.get("glg", "unit")),
                    era=props.get("era", ""),
                    color=props.get("color", "#CCCCCC"),
                    ring=np.asarray(poly[0], dtype=float),
                )
            )
    return units


def load_hydrogeology(path: str | Path | None = None) -> list[GeologyUnit]:
    """The BGS aquifer type and productivity polygons.

    Returned as :class:`GeologyUnit` items: ``glg`` carries the BGS
    combined code (for example ``B-L``), ``unit`` the readable label
    and ``era`` the underlying geology class.
    """
    data = _read_geojson("sl_hydrogeology_bgs.geojson", path)
    units: list[GeologyUnit] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        polys = (
            geom["coordinates"]
            if geom.get("type") == "MultiPolygon"
            else [geom.get("coordinates", [])]
        )
        for poly in polys:
            if not poly:
                continue
            units.append(
                GeologyUnit(
                    glg=props.get("code", ""),
                    unit=props.get("unit", "unit"),
                    era=props.get("geology", ""),
                    color=props.get("color", "#CCCCCC"),
                    ring=np.asarray(poly[0], dtype=float),
                )
            )
    return units


def load_admin(path: str | Path | None = None) -> tuple[AdminArea, list[AdminArea]]:
    """The national outline and the district polygons."""
    data = _read_geojson("sl_admin_geoboundaries.geojson", path)
    outline: AdminArea | None = None
    districts: list[AdminArea] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        polys = (
            geom["coordinates"]
            if geom.get("type") == "MultiPolygon"
            else [geom.get("coordinates", [])]
        )
        area = AdminArea(
            level=props.get("level", "ADM2"),
            name=props.get("name", ""),
            rings=[np.asarray(p[0], dtype=float) for p in polys if p],
        )
        if area.level == "ADM0":
            outline = area
        else:
            districts.append(area)
    if outline is None:
        raise ValueError("admin dataset has no ADM0 outline feature")
    return outline, districts


def _site_lonlat(site: SiteMetadata) -> tuple[float, float] | None:
    latlon = site.latlon
    if latlon is None:
        return None
    lat, lon = latlon
    return lon, lat


def _mask_outside_country(ax, outline: AdminArea, style: HouseStyle) -> None:
    """White out everything beyond the national boundary.

    A compound path (a large rectangle with the country rings as
    holes, even-odd filled) hides the neighbouring countries' geology
    without needing polygon clipping.
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    pad = 2.0
    rect = np.array(
        [
            [x0 - pad, y0 - pad], [x1 + pad, y0 - pad],
            [x1 + pad, y1 + pad], [x0 - pad, y1 + pad],
            [x0 - pad, y0 - pad],
        ]
    )
    vertices = [rect]  # counter-clockwise outer rectangle
    codes = [
        [MplPath.MOVETO] + [MplPath.LINETO] * (len(rect) - 2) + [MplPath.CLOSEPOLY]
    ]
    for ring in outline.rings:
        # holes must wind opposite to the outer ring or they fill solid
        hole = ring[::-1] if _ring_area(ring) > 0 else ring
        vertices.append(hole)
        codes.append(
            [MplPath.MOVETO] + [MplPath.LINETO] * (len(hole) - 2) + [MplPath.CLOSEPOLY]
        )
    compound = MplPath(
        np.concatenate(vertices), np.concatenate(codes).tolist()
    )
    ax.add_patch(
        PathPatch(compound, facecolor=style.background, edgecolor="none", zorder=4)
    )


def _geo_axes_finish(ax, mean_lat: float, credit: str) -> None:
    """Aspect, scale bar, north arrow, grid and attribution."""
    ax.set_aspect(1.0 / math.cos(math.radians(mean_lat)))
    ax.grid(True, color="#DDDDDD", lw=0.5)
    ax.tick_params(labelsize=7.5)
    ax.set_xlabel("Longitude", fontsize=8.5)
    ax.set_ylabel("Latitude", fontsize=8.5)
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
    nx = x1 - (x1 - x0) * 0.07
    ny = y1 - (y1 - y0) * 0.16
    dy = (y1 - y0) * 0.09
    ax.annotate("", xy=(nx, ny + dy), xytext=(nx, ny),
                arrowprops=dict(arrowstyle="-|>", color="#222222", lw=1.6))
    ax.text(nx, ny + dy * 1.15, "N", ha="center", fontsize=10,
            fontweight="bold")
    ax.text(0.99, 0.005, credit, transform=ax.transAxes, fontsize=6.0,
            ha="right", va="bottom", color="#888888", style="italic",
            zorder=9)


def _mark_site(ax, site: SiteMetadata, color: str) -> tuple[float, float] | None:
    lonlat = _site_lonlat(site)
    if lonlat is None:
        return None
    lon, lat = lonlat
    ax.plot(lon, lat, marker="*", ms=16, mfc=color, mec="white", mew=1.2,
            zorder=8)
    ax.annotate(site.community or "Site", xy=(lon, lat), xytext=(8, 8),
                textcoords="offset points", fontsize=9, fontweight="bold",
                color=color, zorder=8)
    return lonlat


def _plot_units_map(
    units: list[GeologyUnit],
    credit: str,
    legend_title: str,
    scope_word: str,
    site: SiteMetadata | None,
    path: str | Path | None,
    style: HouseStyle | None,
    radius_km: float | None,
    admin_path: str | Path | None,
    title: str | None,
    label_with_code: bool,
):
    """Shared renderer for the unit-coloured maps (geology, hydrogeology)."""
    style = style or HouseStyle()
    outline, _ = load_admin(admin_path)
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.6))
        legend_handles: dict[str, PathPatch] = {}
        legend_order: dict[str, tuple[int, str]] = {}
        for unit in units:
            patch = plt.Polygon(
                unit.ring, closed=True, facecolor=unit.color,
                edgecolor="#666666", lw=0.4, zorder=2,
            )
            ax.add_patch(patch)
            label = (
                f"{unit.unit} ({unit.glg})" if label_with_code and unit.glg
                else unit.unit
            )
            legend_handles.setdefault(label, patch)
            era_rank = (
                _ERA_ORDER.index(unit.era) if unit.era in _ERA_ORDER else 99
            )
            legend_order.setdefault(label, (era_rank, unit.glg))

        site_lonlat = _mark_site(ax, site, "#C1272D") if site else None
        if radius_km and site_lonlat is not None:
            lon, lat = site_lonlat
            dlat = radius_km / 111.32
            dlon = radius_km / (111.32 * math.cos(math.radians(lat)))
            ax.set_xlim(lon - dlon, lon + dlon)
            ax.set_ylim(lat - dlat, lat + dlat)
        else:
            all_pts = np.concatenate(outline.rings)
            ax.set_xlim(all_pts[:, 0].min() - 0.15, all_pts[:, 0].max() + 0.15)
            ax.set_ylim(all_pts[:, 1].min() - 0.12, all_pts[:, 1].max() + 0.12)

        _mask_outside_country(ax, outline, style)
        for ring in outline.rings:
            ax.plot(ring[:, 0], ring[:, 1], color="#333333", lw=1.1, zorder=5)

        mean_lat = float(np.mean(ax.get_ylim()))
        _geo_axes_finish(ax, mean_lat, f"{credit}. {ADMIN_CREDIT}")
        ordered = sorted(legend_handles, key=lambda k: legend_order[k])
        ax.legend(
            [legend_handles[k] for k in ordered], ordered,
            loc="upper left", fontsize=6.5, framealpha=0.95,
            title=legend_title, title_fontsize=7.5,
        )
        if title is None:
            where = (site.community or "the site") if site else "Sierra Leone"
            scope = (
                f"Local {scope_word.lower()} setting" if radius_km
                else f"{scope_word} map"
            )
            title = f"{scope} - {where}" if site else f"{scope} of Sierra Leone"
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def plot_geological_map(
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    radius_km: float | None = None,
    geology_path: str | Path | None = None,
    admin_path: str | Path | None = None,
    title: str | None = None,
):
    """Geological map from the USGS data, national or zoomed to the site.

    ``radius_km`` zooms to a window around the site (local geological
    setting); leave it ``None`` for the national map.
    """
    return _plot_units_map(
        load_geology(geology_path),
        GEOLOGY_CREDIT,
        "Geological units (USGS)",
        "Geological",
        site, path, style, radius_km, admin_path, title,
        label_with_code=True,
    )


def plot_hydrogeology_map(
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    radius_km: float | None = None,
    hydro_path: str | Path | None = None,
    admin_path: str | Path | None = None,
    title: str | None = None,
):
    """Aquifer type and productivity map from the BGS Atlas data."""
    return _plot_units_map(
        load_hydrogeology(hydro_path),
        HYDRO_CREDIT,
        "Aquifer type and productivity (BGS)",
        "Hydrogeological",
        site, path, style, radius_km, admin_path, title,
        label_with_code=False,
    )


def plot_admin_map(
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    admin_path: str | Path | None = None,
    title: str | None = None,
):
    """Administrative location map from the geoBoundaries polygons."""
    style = style or HouseStyle()
    outline, districts = load_admin(admin_path)
    highlight = (site.district or "").strip().lower() if site else ""
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.6))
        for district in districts:
            is_home = district.name.strip().lower() == highlight
            for ring in district.rings:
                ax.add_patch(
                    plt.Polygon(
                        ring, closed=True,
                        facecolor=style.accent_color if is_home else "#F2F6FA",
                        alpha=0.35 if is_home else 1.0,
                        edgecolor="#8FA6B8", lw=0.7, zorder=2,
                    )
                )
            lx, ly = district.label_point
            ax.annotate(
                district.name, xy=(lx, ly), ha="center", va="center",
                fontsize=7.5 if is_home else 6.5,
                fontweight="bold" if is_home else "normal",
                color=style.accent_color if is_home else "#555555",
                zorder=6,
            )
        for ring in outline.rings:
            ax.plot(ring[:, 0], ring[:, 1], color="#333333", lw=1.2, zorder=5)
        if site is not None:
            _mark_site(ax, site, "#C1272D")
        ax.text(-11.2, 9.82, "GUINEA", fontsize=8, color="#999999",
                fontweight="bold")
        ax.text(-10.95, 7.15, "LIBERIA", fontsize=8, color="#999999",
                fontweight="bold")
        ax.text(-13.25, 7.45, "Atlantic\nOcean", fontsize=8, color="#7FA8C9",
                style="italic", ha="center")
        all_pts = np.concatenate(outline.rings)
        ax.set_xlim(all_pts[:, 0].min() - 0.2, all_pts[:, 0].max() + 0.15)
        ax.set_ylim(all_pts[:, 1].min() - 0.15, all_pts[:, 1].max() + 0.12)
        mean_lat = float(np.mean(ax.get_ylim()))
        _geo_axes_finish(ax, mean_lat, ADMIN_CREDIT)
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

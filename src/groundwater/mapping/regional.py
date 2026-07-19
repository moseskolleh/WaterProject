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
import textwrap
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
    level: str  # "ADM0" | "ADM2" | "ADM3"
    name: str
    rings: list[np.ndarray] = field(default_factory=list)
    district: str = ""  # parent district, for ADM3 chiefdoms

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


def _point_in_ring(lon: float, lat: float, ring: np.ndarray) -> bool:
    """Ray casting point-in-polygon test."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside


def district_of(
    lat: float, lon: float, admin_path: str | Path | None = None
) -> str:
    """The district containing a point, from the boundary polygons.

    Returns an empty string when the point falls outside every
    district (offshore, across the border, or wrong coordinates).
    """
    _, districts = load_admin(admin_path)
    for district in districts:
        for ring in district.rings:
            if _point_in_ring(lon, lat, ring):
                return district.name
    return ""


def load_chiefdoms(path: str | Path | None = None) -> list[AdminArea]:
    """The chiefdom (ADM3) polygons, each carrying its parent district.

    From geoBoundaries (gbOpen, CC BY 4.0), simplified for bundling.
    """
    data = _read_geojson("sl_chiefdoms_geoboundaries.geojson", path)
    areas: list[AdminArea] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        polys = (
            geom["coordinates"]
            if geom.get("type") == "MultiPolygon"
            else [geom.get("coordinates", [])]
        )
        rings = [np.asarray(p[0], dtype=float) for p in polys if p]
        if rings:
            areas.append(
                AdminArea(
                    level="ADM3",
                    name=props.get("name", ""),
                    rings=rings,
                    district=props.get("district", ""),
                )
            )
    return areas


def chiefdom_of(
    lat: float, lon: float, path: str | Path | None = None
) -> tuple[str, str]:
    """The chiefdom and its district containing a point.

    Returns ``(chiefdom, district)`` or ``("", "")`` when the point falls
    outside every chiefdom.
    """
    for area in load_chiefdoms(path):
        for ring in area.rings:
            if _point_in_ring(lon, lat, ring):
                return area.name, area.district
    return "", ""


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
        # legend outside the axes so it never covers the map; the tight
        # bounding box at save time grows the canvas around it
        ax.legend(
            [legend_handles[k] for k in ordered],
            [textwrap.fill(k, 24) for k in ordered],
            loc="upper left", bbox_to_anchor=(1.02, 1.0),
            fontsize=6.5, framealpha=0.95, borderaxespad=0.0,
            title=textwrap.fill(legend_title, 24), title_fontsize=7.5,
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


def plot_portfolio_map(
    points: list[dict],
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    admin_path: str | Path | None = None,
    title: str = "Borehole portfolio",
):
    """National map of all boreholes coloured by status.

    ``points`` are dicts ``{label, lat, lon, status}`` as produced by
    :func:`groundwater.portfolio.portfolio_points`.
    """
    from ..portfolio import STATUS_COLORS, STATUS_LABELS

    style = style or HouseStyle()
    outline, districts = load_admin(admin_path)
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.8))
        for district in districts:
            for ring in district.rings:
                ax.add_patch(
                    plt.Polygon(ring, closed=True, facecolor="#F2F6FA",
                                edgecolor="#8FA6B8", lw=0.7, zorder=2)
                )
        for ring in outline.rings:
            ax.plot(ring[:, 0], ring[:, 1], color="#333333", lw=1.2, zorder=5)
        handles: dict[str, object] = {}
        for point in points:
            status = point.get("status", "other")
            colour = STATUS_COLORS.get(status, STATUS_COLORS["other"])
            handle, = ax.plot(
                point["lon"], point["lat"], "o", ms=8, mfc=colour,
                mec="white", mew=1.0, zorder=7,
            )
            handles.setdefault(status, handle)
        ax.text(-11.2, 9.82, "GUINEA", fontsize=8, color="#999999", fontweight="bold")
        ax.text(-10.95, 7.15, "LIBERIA", fontsize=8, color="#999999", fontweight="bold")
        ax.text(-13.25, 7.45, "Atlantic\nOcean", fontsize=8, color="#7FA8C9",
                style="italic", ha="center")
        all_pts = np.concatenate(outline.rings)
        ax.set_xlim(all_pts[:, 0].min() - 0.2, all_pts[:, 0].max() + 0.15)
        ax.set_ylim(all_pts[:, 1].min() - 0.15, all_pts[:, 1].max() + 0.12)
        _geo_axes_finish(ax, float(np.mean(ax.get_ylim())), ADMIN_CREDIT)
        if handles:
            ax.legend(
                list(handles.values()),
                [STATUS_LABELS.get(s, s) for s in handles],
                loc="lower right", fontsize=7, framealpha=0.95,
            )
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


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


def plot_coverage_choropleth(
    district_values: dict[str, float],
    chiefdom_district: dict[str, str],
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    chiefdom_path: str | Path | None = None,
    admin_path: str | Path | None = None,
    title: str = "Water coverage gap by district",
    legend_label: str = "People per functional water point",
    credit: str = ADMIN_CREDIT,
):
    """Choropleth of unmet water need, coloured by district value.

    Each chiefdom polygon is filled by the value of its district (from
    ``district_values``, keyed by district name; ``chiefdom_district`` maps
    each chiefdom to its district). Warmer = worse. A district with no
    functional source (an infinite value) is drawn in a distinct dark class;
    a district with no data is grey.
    """
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import LinearSegmentedColormap, Normalize

    style = style or HouseStyle()
    outline, _ = load_admin(admin_path)
    areas = load_chiefdoms(chiefdom_path)
    finite = [
        v for v in district_values.values() if v is not None and math.isfinite(v)
    ]
    norm = Normalize(min(finite), max(finite)) if finite else Normalize(0.0, 1.0)
    cmap = LinearSegmentedColormap.from_list(
        "unmet_need", ["#FBF1E9", style.secondary_color]
    )
    no_data = "#E9E9E9"
    no_source = "#5A1A12"  # dark laterite: no functional source mapped
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.8))
        label_pts: dict[str, list[tuple[float, float]]] = {}
        for area in areas:
            district = chiefdom_district.get(area.name)
            value = district_values.get(district) if district else None
            if value is None:
                face = no_data
            elif not math.isfinite(value):
                face = no_source
            else:
                face = cmap(norm(value))
            for ring in area.rings:
                ax.add_patch(
                    plt.Polygon(ring, closed=True, facecolor=face,
                                edgecolor="#8FA6B8", lw=0.3, zorder=2)
                )
            if district:
                label_pts.setdefault(district, []).append(area.label_point)
        for ring in outline.rings:
            ax.plot(ring[:, 0], ring[:, 1], color="#333333", lw=1.2, zorder=5)
        for district, pts in label_pts.items():
            lx = sum(p[0] for p in pts) / len(pts)
            ly = sum(p[1] for p in pts) / len(pts)
            ax.annotate(district, xy=(lx, ly), ha="center", va="center",
                        fontsize=6.0, color="#222222", fontweight="bold",
                        zorder=6)
        ax.text(-11.2, 9.82, "GUINEA", fontsize=8, color="#999999",
                fontweight="bold")
        ax.text(-10.95, 7.15, "LIBERIA", fontsize=8, color="#999999",
                fontweight="bold")
        ax.text(-13.25, 7.45, "Atlantic\nOcean", fontsize=8, color="#7FA8C9",
                style="italic", ha="center")
        all_pts = np.concatenate(outline.rings)
        ax.set_xlim(all_pts[:, 0].min() - 0.2, all_pts[:, 0].max() + 0.15)
        ax.set_ylim(all_pts[:, 1].min() - 0.15, all_pts[:, 1].max() + 0.12)
        _geo_axes_finish(ax, float(np.mean(ax.get_ylim())), credit)
        mappable = ScalarMappable(norm=norm, cmap=cmap)
        mappable.set_array([])
        fig.colorbar(mappable, ax=ax, shrink=0.6, label=legend_label)
        # legend keys for the two out-of-ramp classes, so a reader can tell the
        # dark districts are the worst case (no source), not the ramp maximum
        from matplotlib.patches import Patch

        ax.legend(
            handles=[
                Patch(facecolor=no_source, edgecolor="#8FA6B8",
                      label="No functional source"),
                Patch(facecolor=no_data, edgecolor="#8FA6B8", label="No data"),
            ],
            loc="lower right", fontsize=7, framealpha=0.95,
        )
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig

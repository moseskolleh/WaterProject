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

import csv
import functools
import io
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
from ..coverage import load_service_classes, service_class_of
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
    # interior rings per part, aligned with ``rings``. Only the point tests
    # use them: Nongowa encloses Kenema Town, and ignoring the hole labelled
    # every site in the town with the rural chiefdom around it.
    holes: list[list[np.ndarray]] = field(default_factory=list)

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


@functools.lru_cache(maxsize=8)
def _bundled_geojson(name: str) -> dict:
    """A bundled layer, parsed once per process.

    district_of and chiefdom_of re-read and re-parsed 240 KB of GeoJSON on
    every Streamlit rerun; the parsed dict is shared and never mutated by
    the loaders, which build their own arrays from it.
    """
    text = (resources.files("groundwater") / "data" / name).read_text(encoding="utf-8")
    return json.loads(text)


def _read_geojson(name: str, path: str | Path | None) -> dict:
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return _bundled_geojson(name)


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
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:], strict=True):
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside


def district_of(
    lat: float, lon: float, admin_path: str | Path | None = None
) -> str:
    """The district containing a point, as the districts are today.

    The bundled district polygons predate the 2017 creation of Karene and
    Falaba, so a point is placed in its chiefdom first and the chiefdom's
    current district read from the crosswalk; only a point inside no
    chiefdom polygon (a boundary gap in the simplified layer) falls back to
    the district polygons. Kamakwie used to come back as Bombali, and the
    app pre-filled that district and its province without a word.

    Returns an empty string when the point falls outside every district
    (offshore, across the border, or wrong coordinates).
    """
    if admin_path is None:
        _, district = chiefdom_of(lat, lon)
        if district:
            return district
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
        holes = [
            [np.asarray(r, dtype=float) for r in p[1:]] for p in polys if p
        ]
        if rings:
            areas.append(
                AdminArea(
                    level="ADM3",
                    name=props.get("name", ""),
                    rings=rings,
                    district=props.get("district", ""),
                    holes=holes,
                )
            )
    return areas


def chiefdom_of(
    lat: float, lon: float, path: str | Path | None = None
) -> tuple[str, str]:
    """The chiefdom and its district containing a point.

    Returns ``(chiefdom, district)`` or ``("", "")`` when the point falls
    outside every chiefdom. The district is the current one from the
    crosswalk (Karene and Falaba included), not the pre-2017 parent the
    boundary release carried.
    """
    current = _current_district_of_chiefdom() if path is None else {}
    for area in _cached_chiefdoms() if path is None else load_chiefdoms(path):
        for i, ring in enumerate(area.rings):
            if not _point_in_ring(lon, lat, ring):
                continue
            inner = area.holes[i] if i < len(area.holes) else []
            if any(_point_in_ring(lon, lat, hole) for hole in inner):
                continue  # inside an enclave: it belongs to the chiefdom there
            return area.name, current.get(area.name, area.district)
    return "", ""


@functools.lru_cache(maxsize=1)
def _cached_chiefdoms() -> tuple:
    """The bundled chiefdom areas, built once; callers only read them."""
    return tuple(load_chiefdoms())


def _site_lonlat(site: SiteMetadata) -> tuple[float, float] | None:
    latlon = site.latlon
    if latlon is None:
        return None
    lat, lon = latlon
    return lon, lat


@dataclass
class AreaWindow:
    """Where to centre a local map, and how wide to make it.

    A site with a GPS fix gives a point. A site with only a chiefdom or a
    district recorded still gives an area, and an area is what most of
    these maps are actually asked for: the reader wants to know where in
    the country this is and what the ground is like around it. Only a
    project with neither falls back to the national extent.
    """

    lon: float
    lat: float
    radius_km: float
    label: str
    #: True when the centre is a real GPS fix rather than an area centroid
    exact: bool = True


def _ring_span_km(rings: list[np.ndarray]) -> float:
    pts = np.concatenate(rings)
    lat = float(np.mean(pts[:, 1]))
    dlat = float(pts[:, 1].max() - pts[:, 1].min()) * 111.32
    dlon = (float(pts[:, 0].max() - pts[:, 0].min()) * 111.32
            * math.cos(math.radians(lat)))
    return max(dlat, dlon) / 2.0


@functools.lru_cache(maxsize=1)
def _bundled_crosswalk() -> dict[str, str]:
    text = (resources.files("groundwater") / "data"
            / "sl_chiefdom_district.csv").read_text(encoding="utf-8")
    return {
        row["chiefdom"].strip(): row["district"].strip()
        for row in csv.DictReader(io.StringIO(text))
    }


def _current_district_of_chiefdom(path: str | Path | None = None) -> dict[str, str]:
    """Chiefdom -> the district it is in *today*.

    The bundled boundary layer is geoBoundaries as released, which predates
    the 2017 creation of Karene and Falaba, so those two districts have no
    polygon of their own and the chiefdom polygons still name the districts
    they were split from. This crosswalk is what knows the current answer.
    """
    if path is None:
        return dict(_bundled_crosswalk())
    text = Path(path).read_text(encoding="utf-8")
    return {
        row["chiefdom"].strip(): row["district"].strip()
        for row in csv.DictReader(io.StringIO(text))
    }


def _district_from_chiefdoms(
    district: str,
    chiefdom_path: str | Path | None = None,
    crosswalk_path: str | Path | None = None,
) -> tuple[float, float, float] | None:
    """Centre and radius for a district assembled from its chiefdoms.

    The two districts created in 2017 are not in the boundary layer, and a
    site in one of them would otherwise resolve to nothing at all - telling
    a user to enter a district they had already entered, and leaving the
    reports without an area map for two of the sixteen. Their extent is
    recovered from the chiefdoms the crosswalk assigns to them.

    The centre is the middle of the combined extent rather than the
    centroid of the largest part: a district assembled from nine chiefdoms
    has no single dominant ring to sit in, and the middle of the whole is
    what frames it.
    """
    wanted = district.strip().lower()
    crosswalk = _current_district_of_chiefdom(crosswalk_path)
    rings = [
        ring
        for area in load_chiefdoms(chiefdom_path)
        if crosswalk.get(area.name, "").strip().lower() == wanted
        for ring in area.rings
    ]
    if not rings:
        return None
    pts = np.concatenate(rings)
    lon = float(pts[:, 0].min() + pts[:, 0].max()) / 2.0
    lat = float(pts[:, 1].min() + pts[:, 1].max()) / 2.0
    return lon, lat, _ring_span_km(rings)


def area_window(
    site: SiteMetadata | None,
    radius_km: float | None = None,
    admin_path: str | Path | None = None,
    chiefdom_path: str | Path | None = None,
) -> AreaWindow | None:
    """The window a local map of this site should cover, if there is one."""
    if site is None:
        return None
    lonlat = _site_lonlat(site)
    if lonlat is not None:
        return AreaWindow(lonlat[0], lonlat[1], radius_km or 40.0,
                          site.community or "the site", True)
    name = (site.chiefdom or "").strip().lower()
    if name:
        for area in load_chiefdoms(chiefdom_path):
            if area.name.strip().lower() == name:
                lon, lat = area.label_point
                return AreaWindow(lon, lat,
                                  max(_ring_span_km(area.rings) * 1.35, 12.0),
                                  f"{area.name} chiefdom", False)
    name = (site.district or "").strip().lower()
    if name:
        _, districts = load_admin(admin_path)
        for area in districts:
            if area.name.strip().lower() == name:
                lon, lat = area.label_point
                return AreaWindow(lon, lat,
                                  max(_ring_span_km(area.rings) * 1.2, 20.0),
                                  f"{area.name} district", False)
        # Karene and Falaba postdate the boundary release, so they are
        # assembled from their chiefdoms rather than looked up.
        assembled = _district_from_chiefdoms(name, chiefdom_path)
        if assembled is not None:
            lon, lat, span = assembled
            return AreaWindow(lon, lat, max(span * 1.2, 20.0),
                              f"{site.district.strip()} district", False)
    return None


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


def style_background(ax) -> str:
    """The figure's own background colour, for text plates drawn over data."""
    return ax.figure.get_facecolor()


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
    # lifted clear of however many lines the attribution wraps to; a two-source
    # credit is two lines, and the bar used to be struck through by them
    credit_lines = textwrap.fill(credit, 104).count("\n") + 1
    by = y0 + (y1 - y0) * (0.045 + 0.030 * credit_lines)
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
    # Wrapped to the frame. A two-source credit is about 140 characters and
    # runs a third of a figure-width past the left spine; the tight bounding
    # box at save time then grows the canvas to hold it, which left every
    # local geology and aquifer map sitting in the right-hand half of its own
    # figure with an empty gutter beside it.
    # On a white map the credit reads as grey italic against nothing. On a
    # filled one - an aquifer map, a hypsometric tint - it lands on top of
    # the data and neither can be read. A faint plate behind it costs the
    # white maps nothing and makes the filled ones legible.
    ax.text(0.99, 0.005, textwrap.fill(credit, 104), transform=ax.transAxes,
            fontsize=6.0, ha="right", va="bottom", color="#666666",
            style="italic", zorder=9, linespacing=1.35,
            bbox=dict(boxstyle="square,pad=0.35", fc=style_background(ax),
                      ec="none", alpha=0.82))


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
    source_scale: int | None,
    publisher_note: str = "",
):
    """Shared renderer for the unit-coloured maps (geology, hydrogeology)."""
    style = style or HouseStyle()
    outline, _ = load_admin(admin_path)
    # The window is settled before anything is drawn, because it decides
    # which units are on this map. Drawing them all first and zooming
    # afterwards built the legend from the whole country: a 10 km window
    # over the Freetown peninsula listed Ordovician, Silurian and
    # Precambrian formations alongside the two units actually under the
    # site, and a reader has no way to tell which two those were.
    window = area_window(site, radius_km, admin_path) if radius_km else None
    if window is not None:
        dlat = window.radius_km / 111.32
        dlon = window.radius_km / (111.32 * math.cos(math.radians(window.lat)))
        box = (window.lon - dlon, window.lat - dlat,
               window.lon + dlon, window.lat + dlat)
    else:
        all_pts = np.concatenate(outline.rings)
        box = (all_pts[:, 0].min() - 0.15, all_pts[:, 1].min() - 0.12,
               all_pts[:, 0].max() + 0.15, all_pts[:, 1].max() + 0.12)
    in_view = [unit for unit in units if _ring_in_box(unit.ring, box)]

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.6))
        legend_handles: dict[str, PathPatch] = {}
        legend_order: dict[str, tuple[int, str]] = {}
        for unit in in_view:
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

        _mark_site(ax, site, "#C1272D") if site else None
        ax.set_xlim(box[0], box[2])
        ax.set_ylim(box[1], box[3])

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
            if window is not None:
                scope = f"Local {scope_word.lower()} setting"
                title = f"{scope} - {window.label}"
                if not window.exact:
                    title += " (no site position recorded)"
            elif site is not None and (site.community or ""):
                title = f"{scope_word} map - {site.community}"
            else:
                title = f"{scope_word} map of Sierra Leone"
        ax.set_title(title)
        caveat = _scale_caveat(radius_km, source_scale, publisher_note)
        if caveat:
            ax.text(0.5, -0.125, textwrap.fill(caveat, 96),
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=6.5, color="#8A5A00")
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
        label_with_code=True, source_scale=_USGS_SOURCE_SCALE,
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
        label_with_code=False, source_scale=_BGS_SOURCE_SCALE,
        publisher_note=_BGS_PUBLISHER_NOTE,
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
    chiefdom_values: dict[str, float],
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    chiefdom_path: str | Path | None = None,
    admin_path: str | Path | None = None,
    title: str = "Water coverage gap by district",
    legend_label: str = "People per functional water point",
    credit: str = ADMIN_CREDIT,
    group_labels: dict[str, str] | None = None,
):
    """Choropleth of unmet water need, one colour per chiefdom polygon.

    Each chiefdom polygon is filled by ``chiefdom_values[name]``. Warmer =
    worse; ``None`` is drawn grey (no data) and an infinite value dark (no
    functional source). For the district view, pass district values expanded
    onto every chiefdom (see ``coverage.expand_district_values``) with
    ``group_labels`` mapping each chiefdom to its district, so the district
    names are annotated once at their centroid; for the chiefdom view, omit
    ``group_labels`` (166 labels would be unreadable).
    """
    style = style or HouseStyle()
    outline, _ = load_admin(admin_path)
    areas = load_chiefdoms(chiefdom_path)
    # A fixed scale, not one stretched to whatever is on this map. Rescaling
    # per figure made two maps of the same country incomparable: a chiefdom at
    # 900 people per functional point was pale beside a worst case of 40,000
    # and dark beside a worst case of 1,200, and no key said what a colour
    # meant. The bands and their colours come from the table both engines read.
    classes = load_service_classes()
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.8))
        label_pts: dict[str, list[tuple[float, float]]] = {}
        for area in areas:
            face = service_class_of(chiefdom_values.get(area.name), classes).colour
            for ring in area.rings:
                ax.add_patch(
                    plt.Polygon(ring, closed=True, facecolor=face,
                                edgecolor="#8FA6B8", lw=0.3, zorder=2)
                )
            group = group_labels.get(area.name) if group_labels else None
            if group:
                label_pts.setdefault(group, []).append(area.label_point)
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
        # Every class is a key, including the two that are not on the ramp, so
        # a reader can tell the darkest areas are the worst case rather than
        # the top of whatever range this particular map happened to span.
        from matplotlib.patches import Patch

        ax.legend(
            handles=[
                Patch(facecolor=c.colour, edgecolor="#8FA6B8", label=c.label)
                for c in classes
            ],
            loc="lower right", fontsize=7, framealpha=0.95, title=legend_label,
        )
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


# Both bundled unit datasets are published at 1:5,000,000. At that scale a
# 0.5 mm drafting line is 2.5 km wide on the ground, so a 40 km window - the
# toolkit's own default - is reading a contact to a fortieth of the frame it
# is drawn in. The zoom is still worth having: it is how a reader sees which
# unit the site sits on. What it must not do is let a crisp polygon edge
# imply a contact somebody walked, so below the threshold the figure says
# what it is made of.
_USGS_SOURCE_SCALE = 5_000_000
_BGS_SOURCE_SCALE = 5_000_000
_HONEST_WINDOW_KM = 60.0

#: The BGS Africa Groundwater Atlas user guide (OR/21/063, section 2.2) on
#: what its country maps are for. Quoted rather than paraphrased: it is the
#: publisher's own limit on its own data, and it is more use to a reader
#: deciding what to trust than any sentence this toolkit could write.
_BGS_PUBLISHER_NOTE = (
    'Its publisher states these maps are "not suitable for providing '
    'detailed information on geology and hydrogeology at a sub-national '
    '(e.g. catchment) scale".'
)


def _scale_caveat(
    radius_km: float | None,
    source_scale: int | None,
    publisher_note: str = "",
) -> str:
    """The note a small window over a small-scale dataset has earned.

    Returns an empty string for a national map, which is the scale the
    data was published at and needs no apology.
    """
    if radius_km is None or source_scale is None or radius_km > _HONEST_WINDOW_KM:
        return ""
    line_km = source_scale * 0.0005 / 1000.0  # a 0.5 mm line on the sheet
    share = line_km / (2 * radius_km) * 100
    note = (
        f"Drawn from a 1:{source_scale:,} dataset: a boundary on this map is "
        f"placed to roughly {line_km:g} km, which is {share:.0f}% of this "
        f"{2 * radius_km:g} km window. Read the contacts as regional "
        "context, not as mapped ground."
    )
    return f"{note} {publisher_note}".strip()


def _corner_occupancy(
    ax, lonlats: list[tuple[float, float]]
) -> dict[str, int]:
    """How many drawn points fall in each corner of the axes.

    The locator inset and the legend both sit on top of the map, so
    where they go has to depend on where the data is not. Fixing them to
    a corner drew a survey point underneath the inset on the first real
    site this was tried on.
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    counts = {"lower right": 0, "upper left": 0, "lower left": 0, "upper right": 0}
    for lon, lat in lonlats:
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        fx = (lon - x0) / (x1 - x0)
        fy = (lat - y0) / (y1 - y0)
        # the corner boxes the inset and legend actually occupy
        if fx > 0.62 and fy < 0.42:
            counts["lower right"] += 1
        if fx < 0.38 and fy > 0.58:
            counts["upper left"] += 1
        if fx < 0.38 and fy < 0.42:
            counts["lower left"] += 1
        if fx > 0.62 and fy > 0.58:
            counts["upper right"] += 1
    return counts


#: Where each corner's inset sits, in axes fractions.
_INSET_BOXES = {
    "lower right": (0.695, 0.02, 0.29, 0.34),
    "upper left": (0.015, 0.63, 0.29, 0.34),
    "lower left": (0.015, 0.02, 0.29, 0.34),
    "upper right": (0.695, 0.63, 0.29, 0.34),
}


def _locator_inset(ax, outline: AdminArea, window: AreaWindow,
                   districts: list[AdminArea], style: HouseStyle,
                   corner: str = "lower right") -> None:
    """A thumbnail of the country with the study area marked on it.

    A study-area map at 20 km across is unreadable as a location unless
    the reader already knows the district. The inset is what makes the
    figure answer "where is this?" as well as "what is here?", and it is
    the one piece of furniture the existing maps had no equivalent of.
    """
    inset = ax.inset_axes(_INSET_BOXES.get(corner, _INSET_BOXES["lower right"]))
    for district in districts:
        for ring in district.rings:
            inset.add_patch(
                plt.Polygon(ring, closed=True, facecolor="#EEF3F8",
                            edgecolor="#B6C6D4", lw=0.3, zorder=2)
            )
    for ring in outline.rings:
        inset.plot(ring[:, 0], ring[:, 1], color="#333333", lw=0.8, zorder=4)
    # the study area as a box where it is big enough to see, a dot where not
    dlat = window.radius_km / 111.32
    dlon = window.radius_km / (111.32 * math.cos(math.radians(window.lat)))
    if max(dlat, dlon) > 0.09:
        inset.add_patch(
            plt.Rectangle(
                (window.lon - dlon, window.lat - dlat), 2 * dlon, 2 * dlat,
                facecolor="none", edgecolor="#C1272D", lw=1.4, zorder=6,
            )
        )
    else:
        inset.plot(window.lon, window.lat, "o", ms=5, mfc="#C1272D",
                   mec="white", mew=0.9, zorder=6)
    pts = np.concatenate(outline.rings)
    inset.set_xlim(pts[:, 0].min() - 0.1, pts[:, 0].max() + 0.1)
    inset.set_ylim(pts[:, 1].min() - 0.1, pts[:, 1].max() + 0.1)
    inset.set_aspect(1.0 / math.cos(math.radians(float(np.mean(inset.get_ylim())))))
    inset.set_xticks([])
    inset.set_yticks([])
    inset.grid(False)
    for spine in inset.spines.values():
        spine.set_edgecolor("#888888")
        spine.set_linewidth(0.8)
    inset.patch.set_facecolor(style.background)
    # opaque: at 0.95 the chiefdom names underneath showed through the
    # thumbnail as ghost text across Sierra Leone
    inset.patch.set_alpha(1.0)
    inset.set_title("Sierra Leone", fontsize=6.5, pad=2.0)


def plot_study_area_map(
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    radius_km: float = 25.0,
    points: list[dict] | None = None,
    admin_path: str | Path | None = None,
    chiefdom_path: str | Path | None = None,
    title: str | None = None,
    show_geology: bool = False,
    geology_path: str | Path | None = None,
):
    """The study area at a readable scale, with a locator inset.

    This is the map a report opens on. The national location map says
    which district; this says what the study area itself contains - the
    chiefdom boundaries around it, the site, the survey points, any
    existing water points found nearby - at a scale where the distances
    between them can be read off the scale bar.

    ``points`` are dicts ``{lat, lon, label, kind}``. ``kind`` chooses
    the marker: ``VES point``, ``borehole``, ``water point`` or
    ``settlement``; anything else is drawn as a plain dot and named in
    the legend under its own word, because a map that silently reuses one
    marker for two things is a map that will be misread.

    ``show_geology`` tints the area with the geological units behind
    everything else. It is off by default: at 25 km the 1:5M units are
    large flat washes, and the study-area map's job is the local
    furniture, not the regional geology, which has its own figure.
    """
    style = style or HouseStyle()
    window = area_window(site, radius_km, admin_path, chiefdom_path)
    if window is None:
        raise ValueError(
            "a study area map needs somewhere to centre on: a GPS position, "
            "a chiefdom or a district. None of the three is recorded for this "
            "site, so there is no study area to draw."
        )
    outline, districts = load_admin(admin_path)
    chiefdoms = load_chiefdoms(chiefdom_path)
    dlat = window.radius_km / 111.32
    dlon = window.radius_km / (111.32 * math.cos(math.radians(window.lat)))
    box = (window.lon - dlon, window.lat - dlat,
           window.lon + dlon, window.lat + dlat)

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.8))
        ax.set_xlim(box[0], box[2])
        ax.set_ylim(box[1], box[3])

        credit = ADMIN_CREDIT
        if show_geology:
            for unit in load_geology(geology_path):
                if not _ring_in_box(unit.ring, box):
                    continue
                ax.add_patch(
                    plt.Polygon(unit.ring, closed=True, facecolor=unit.color,
                                edgecolor="none", alpha=0.45, zorder=1)
                )
            credit = f"{GEOLOGY_CREDIT}. {credit}"

        # chiefdoms first: they are the boundaries a community is found by
        placed_labels: list[tuple[float, float]] = []
        for area in chiefdoms:
            drawn = [r for r in area.rings if _ring_in_box(r, box)]
            for ring in drawn:
                ax.add_patch(
                    plt.Polygon(ring, closed=True, facecolor="none",
                                edgecolor="#7E93A6", lw=0.8, zorder=3)
                )
            spot = _label_spot(drawn, box)
            if spot is not None and _clear_of(spot, placed_labels, box):
                placed_labels.append(spot)
                # one label per chiefdom, on the part of it that is in view.
                # Labelling every ring wrote "Kaffu Bullom" five times across
                # the top of the first map this drew: the chiefdom reaches the
                # window as five islands, and each one asked for its own name.
                ax.annotate(area.name, xy=spot, ha="center", va="center",
                            fontsize=6.5, color="#5A6B7A", zorder=4,
                            fontstyle="italic")
        for district in districts:
            for ring in district.rings:
                if _ring_in_box(ring, box):
                    ax.plot(ring[:, 0], ring[:, 1], color="#44586B", lw=1.3,
                            zorder=5)
        for ring in outline.rings:
            if _ring_in_box(ring, box):
                ax.plot(ring[:, 0], ring[:, 1], color="#222222", lw=1.8,
                        zorder=6)

        handles = _plot_area_points(ax, points or [], style)
        if site is not None and window.exact:
            _mark_site(ax, site, "#C1272D")

        _geo_axes_finish(ax, window.lat, credit)
        # the scale bar owns the lower left and the north arrow the upper
        # right, so the inset and the legend share what is left, emptiest
        # first
        drawn_at = [
            (p.get("lon"), p.get("lat")) for p in (points or [])
            if p.get("lon") is not None and p.get("lat") is not None
        ]
        if site is not None and window.exact and site.latlon is not None:
            drawn_at.append((site.latlon[1], site.latlon[0]))
        # the chiefdom names count as occupancy too: a map with no survey
        # points on it still has a corner full of writing, and the inset
        # put itself on top of four district names on the first one drawn
        occupancy = _corner_occupancy(ax, drawn_at + placed_labels)
        free = sorted(("lower right", "upper left"), key=lambda c: occupancy[c])
        _locator_inset(ax, outline, window, districts, style, corner=free[0])
        if handles:
            # lifted clear of the attribution line, which sits on the axes
            # floor and which the legend box otherwise lands on top of
            lift = 0.035 if free[1].startswith("lower") else 0.0
            ax.legend(
                handles.values(), handles.keys(), loc=free[1],
                bbox_to_anchor=(0.0, lift, 1.0, 1.0 - lift),
                fontsize=7, framealpha=0.95,
            )
        if title is None:
            title = f"Study area - {window.label}"
            if not window.exact:
                title += " (no site position recorded)"
        ax.set_title(title)
        if show_geology:
            note = _scale_caveat(radius_km, _USGS_SOURCE_SCALE)
            if note:
                # wrapped by hand: an unwrapped line under the axes is one
                # long line, and the tight bounding box at save time grows
                # the canvas sideways to hold it, leaving the map off-centre
                # in its own figure
                ax.text(0.5, -0.125, textwrap.fill(note, 96),
                        transform=ax.transAxes, ha="center", va="top",
                        fontsize=6.5, color="#8A5A00")
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


#: Marker and colour per point kind on the study-area map.
_AREA_MARKERS = {
    "VES point": ("^", "#1F5C8B"),
    "borehole": ("o", "#0F7B3F"),
    "water point": ("s", "#7B5AA6"),
    "settlement": (".", "#555555"),
}


def _plot_area_points(ax, points: list[dict], style: HouseStyle) -> dict:
    """Draw the study-area overlays, one legend entry per kind."""
    handles: dict[str, object] = {}
    for point in points:
        lon, lat = point.get("lon"), point.get("lat")
        if lon is None or lat is None:
            continue
        kind = str(point.get("kind") or "point")
        marker, colour = _AREA_MARKERS.get(kind, ("D", style.secondary_color))
        handle, = ax.plot(
            lon, lat, marker, ms=8 if marker != "." else 10, mfc=colour,
            mec="white", mew=0.9, zorder=7,
        )
        handles.setdefault(kind, handle)
        label = point.get("label")
        if label:
            # below the marker, because the site star labels itself above
            # its own point and the two collided wherever a sounding sat on
            # the wellhead - which is most surveys
            ax.annotate(str(label), xy=(lon, lat), xytext=(7, -11),
                        textcoords="offset points", fontsize=7.5,
                        color="#222222", zorder=8)
    return handles


def _clear_of(
    spot: tuple[float, float],
    placed: list[tuple[float, float]],
    box: tuple[float, float, float, float],
    min_sep_frac: float = 0.055,
) -> bool:
    """Is there room to write another name here?

    Matplotlib will happily draw two labels through each other, and on a
    window crossing the Western Area the chiefdoms are small enough that
    three or four names landed in the same centimetre. A name that cannot
    be read is worse than no name: the reader cannot tell which polygon
    the legible one belongs to either.
    """
    gap = max(box[2] - box[0], box[3] - box[1]) * min_sep_frac
    return all(
        math.hypot(spot[0] - other[0], spot[1] - other[1]) > gap
        for other in placed
    )


def _label_spot(
    rings: list[np.ndarray], box: tuple[float, float, float, float]
) -> tuple[float, float] | None:
    """Where to write an area's name, given only the parts of it in view.

    The centroid of the largest ring is the right answer for a whole
    country and the wrong one for a chiefdom clipped by the window: it
    lands outside the frame, and the name is either not drawn or drawn
    on the edge pointing at nothing. The mean of the vertices that are
    actually inside the window is inside the window by construction.
    """
    inside = [
        v for ring in rings for v in ring
        if box[0] < v[0] < box[2] and box[1] < v[1] < box[3]
    ]
    if len(inside) < 3:
        return None
    pts = np.asarray(inside, dtype=float)
    return float(pts[:, 0].mean()), float(pts[:, 1].mean())


def _ring_in_box(ring: np.ndarray, box: tuple[float, float, float, float]) -> bool:
    """Does a ring actually reach into the window?

    The extents are tested first because they reject almost everything
    almost free - drawing all 166 chiefdoms and the whole geological map
    into a 25 km window and letting matplotlib discard them costs a
    second a figure, and the reports draw several.

    What follows the extent test is the part that matters for the legend.
    Two rectangles can overlap while the shapes inside them do not touch,
    and a legend built on the cheap test alone named a consolidated
    sedimentary aquifer on a map of the Freetown peninsula because that
    unit's bounding box reaches across the country the polygon does not.
    So: a vertex inside the window, a window corner inside the ring, or
    an edge of one crossing an edge of the other. Those three are the
    whole of it.
    """
    lon_min, lat_min, lon_max, lat_max = box
    if not (
        ring[:, 0].max() >= lon_min and ring[:, 0].min() <= lon_max
        and ring[:, 1].max() >= lat_min and ring[:, 1].min() <= lat_max
    ):
        return False
    inside = (
        (ring[:, 0] >= lon_min) & (ring[:, 0] <= lon_max)
        & (ring[:, 1] >= lat_min) & (ring[:, 1] <= lat_max)
    )
    if inside.any():
        return True
    corners = (
        (lon_min, lat_min), (lon_max, lat_min),
        (lon_max, lat_max), (lon_min, lat_max),
    )
    if any(_point_in_ring(lon, lat, ring) for lon, lat in corners):
        return True
    return _ring_crosses_box_edge(ring, box)


def _ring_crosses_box_edge(
    ring: np.ndarray, box: tuple[float, float, float, float]
) -> bool:
    """A ring that slices the window without a vertex landing in it.

    The remaining case: a long thin polygon - a dyke, a river, a coastal
    strip - passing clean through the frame. Its segments are tested
    against the four sides of the window, vectorised, because a national
    geology layer holds tens of thousands of segments and this runs once
    per unit per figure.
    """
    lon_min, lat_min, lon_max, lat_max = box
    p1 = ring[:-1]
    p2 = ring[1:]
    sides = (
        ((lon_min, lat_min), (lon_max, lat_min)),
        ((lon_max, lat_min), (lon_max, lat_max)),
        ((lon_max, lat_max), (lon_min, lat_max)),
        ((lon_min, lat_max), (lon_min, lat_min)),
    )
    for (ax_, ay), (bx, by) in sides:
        q1 = np.array([ax_, ay])
        q2 = np.array([bx, by])
        d1 = _cross_sign(q1, q2, p1)
        d2 = _cross_sign(q1, q2, p2)
        d3 = _cross_sign(p1, p2, q1)
        d4 = _cross_sign(p1, p2, q2)
        if np.any((d1 * d2 < 0) & (d3 * d4 < 0)):
            return True
    return False


def _cross_sign(a, b, c) -> np.ndarray:
    """Which side of the line a-b each point c falls on."""
    a = np.atleast_2d(np.asarray(a, dtype=float))
    b = np.atleast_2d(np.asarray(b, dtype=float))
    c = np.atleast_2d(np.asarray(c, dtype=float))
    return ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
            - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))

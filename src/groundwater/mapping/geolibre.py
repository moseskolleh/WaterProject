"""GeoLibre project files: the survey as a map somebody can open.

Every map this toolkit draws is a picture. A picture is the right thing
to put in a report and the wrong thing to hand to somebody who wants to
know what is under the next hill: it cannot be panned, the VES station
cannot be clicked, and there is nothing underneath it but graph paper.

`GeoLibre <https://geolibre.app>`_ is a free, MIT-licensed GIS that runs
in a browser, on a desktop, on a phone and inside a notebook, and reads
a documented plain-JSON project file. So the cheapest way to give this
toolkit an interactive map is not to write one. It is to write that
file.

Design
------
**Nothing new is imported.** The format is JSON, the geometry is the
GeoJSON we already emit, and the projection is the one in
:mod:`groundwater.geo`. This module needs the standard library and
nothing else - not even numpy or matplotlib, so it stays importable
where those are not. Ring coordinates arrive as numpy arrays from
:mod:`groundwater.mapping.regional` and are read row by row as plain
floats rather than by importing numpy to do it.

**Deterministic.** Re-running on the same data produces a byte-identical
file, which is the rule everywhere else in this toolkit and is the
reason layer identifiers are slugs of their names rather than the random
UUIDs the format's own examples use. A file that differs on every run
cannot be checked into a project folder or diffed against last month's.

**Per-feature colour, not a renderer.** Colours ride on the features
themselves as simplestyle properties (``fill``, ``stroke``,
``marker-color``), with a plain single-symbol style beside them as the
fallback. A categorised renderer would say the same thing in a schema
that is at version 0.1.0 and will move; simplestyle is older than this
format and will outlive this version of it.

**Attribution travels with the layer.** The bundled datasets are not all
alike - geoBoundaries is CC BY 4.0, the BGS aquifer layer is CC BY-SA
4.0, WPDx is CC BY 4.0 - so every layer carries its own credit in its
metadata and the project carries the full list. A layer whose licence
requires attribution must not be able to leave here without it.

Note on ShareAlike
------------------
:func:`site_project` inlines the geometry it is given, and inlining a
CC BY-SA layer carries ShareAlike into the resulting file. That is fine
for a project file shared under the same terms and is the reason the
credit is written next to the geometry rather than in a note somewhere
else. Where the layer can be referenced by URL instead, prefer that.

Usage
-----
>>> from groundwater.mapping import geolibre
>>> project = geolibre.site_project(site=site, survey_points=points, zone=28)
>>> geolibre.write_project(project, "rokel.geolibre.json")

The written file opens unchanged in the GeoLibre web app, the desktop
app, the Android and iOS apps, and the Jupyter widget.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable, Sequence

from ..geo import utm_to_geographic
from ..site_status import STATUS_COLORS, STATUS_LABELS, coerce_status

__all__ = [
    "GEOLIBRE_WEB_APP",
    "PROJECT_FORMAT_VERSION",
    "area_features",
    "build_project",
    "data_link",
    "features_within",
    "geojson_layer",
    "points_within_window",
    "portfolio_features",
    "portfolio_project",
    "project_link",
    "site_project",
    "suitability_features",
    "survey_point_features",
    "unit_features",
    "water_point_features",
    "window_around",
    "write_project",
]

#: The hosted web build. A self-hosted deployment passes its own base URL.
GEOLIBRE_WEB_APP = "https://web.geolibre.app/"

#: The project schema version this module writes. GeoLibre is young and
#: the format is explicitly pre-1.0, so the version is stated rather than
#: assumed, and everything that knows about the format lives in this file.
PROJECT_FORMAT_VERSION = "0.1.0"

#: A blank background rather than a basemap. Deliberate: the toolkit's
#: own maps are drawn on a plain grid, and a project that silently
#: reached for OpenStreetMap tiles would be the app's first unannounced
#: network call. The user switches a basemap on; the file does not.
BLANK_BASEMAP = ""

#: Coordinates are written to six decimal places, matching
#: :func:`groundwater.mapping.export.export_geojson`. Six places is about
#: 0.1 m at this latitude - far finer than a handheld GPS fix and finer
#: than the survey it describes.
_COORD_DP = 6

# Suitability grades, coloured red-to-green to match ``suitability_map``.
_GRADE_COLORS = {
    "Very good": "#1A9850",
    "Good": "#A6D96A",
    "Moderate": "#FDAE61",
    "Poor": "#D73027",
}

# A water point that nobody has reported on is grey, not green. The same
# rule the asset registry keeps: absence of bad news is not good news.
_FUNCTIONAL_COLORS = {True: "#2E7D5B", False: "#B23A2E", None: "#6B7785"}
_FUNCTIONAL_LABELS = {True: "Functional", False: "Non-functional", None: "Unknown"}

# Metadata keys that would be a credential leaving the machine. The rule
# elsewhere in this toolkit is that the API key never enters a saved
# project file, so sharing a project never shares the key; a GeoLibre
# project is a saved project file and the rule holds there too.
_SECRET_HINTS = ("key", "token", "secret", "password", "credential", "auth")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    """A stable identifier from a layer name.

    The format's examples use random UUIDs. This toolkit promises that
    re-running on the same raw data produces byte-identical output, and a
    random identifier breaks that promise on the first rerun, so the name
    is slugged instead. Two layers with the same name would collide;
    :func:`build_project` numbers duplicates rather than letting one
    quietly overwrite the other.
    """
    slug = _SLUG_STRIP.sub("-", str(text or "").strip().lower()).strip("-")
    return slug or "layer"


def _round(value: float) -> float:
    """Round a coordinate, and hand back a float rather than a numpy scalar."""
    return round(float(value), _COORD_DP)


def _ring(points) -> list[list[float]]:
    """A GeoJSON linear ring from a sequence of (lon, lat) pairs.

    Accepts numpy arrays without importing numpy: each row is unpacked and
    coerced. GeoJSON requires a closed ring, and the bundled boundary data
    does not always close, so it is closed here rather than trusted to be.
    """
    ring = [[_round(lon), _round(lat)] for lon, lat in points]
    if len(ring) >= 2 and ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def _feature(geometry: dict, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _point(lon: float, lat: float, properties: dict) -> dict:
    return _feature(
        {"type": "Point", "coordinates": [_round(lon), _round(lat)]}, properties
    )


def _clean(properties: dict) -> dict:
    """Drop empty values so a feature's popup is not a wall of blanks."""
    return {k: v for k, v in properties.items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Features from the objects this toolkit already has
# ---------------------------------------------------------------------------


def survey_point_features(points: Iterable, zone: int) -> list[dict]:
    """GeoJSON point features from :class:`~groundwater.mapping.maps.MapPoint`.

    ``MapPoint`` carries projected UTM metres because the printed maps are
    drawn in metres; a project file is WGS84, so each point is unprojected
    through the same transform the GeoJSON export uses.

    Duck-typed on ``label``/``easting``/``northing``/``value``/``kind``
    rather than imported, which keeps this module free of matplotlib.
    """
    features = []
    for point in points:
        lat, lon = utm_to_geographic(point.easting, point.northing, zone)
        properties = _clean(
            {
                "label": point.label,
                "kind": point.kind,
                "value": point.value,
                "easting_utm": round(float(point.easting), 1),
                "northing_utm": round(float(point.northing), 1),
                "utm_zone": f"{zone}N",
                "marker-color": "#17527E",
                "fill": "#17527E",
                "stroke": "#FFFFFF",
            }
        )
        features.append(_point(lon, lat, properties))
    return features


def suitability_features(scores: Iterable, zone: int) -> list[dict]:
    """Point features from :class:`~groundwater.siting.suitability.SitingSuitability`.

    Each point is coloured by its grade, so the drill-target ranking reads
    off the map the way it reads off the table. Scores without a position
    are skipped: a suitability with nowhere to put it is a table row, not
    a map feature.
    """
    features = []
    for score in scores:
        if score.easting is None or score.northing is None:
            continue
        lat, lon = utm_to_geographic(score.easting, score.northing, zone)
        colour = _GRADE_COLORS.get(score.grade, "#6B7785")
        properties = _clean(
            {
                "sounding": score.sounding_id,
                "suitability": round(float(score.suitability), 1),
                "grade": score.grade,
                "rank": score.rank,
                "rationale": score.rationale,
                "marker-color": colour,
                "fill": colour,
                "stroke": "#222222",
            }
        )
        features.append(_point(lon, lat, properties))
    return features


def water_point_features(points: Iterable) -> list[dict]:
    """Point features from :class:`~groundwater.waterpoints.WaterPoint`.

    Coloured by functionality, with unknown grey rather than green. The
    survey year rides along, because a point reported functional in 2016
    is evidence about 2016.
    """
    features = []
    for point in points:
        colour = _FUNCTIONAL_COLORS[point.functional]
        properties = _clean(
            {
                "status": _FUNCTIONAL_LABELS[point.functional],
                "status_raw": point.status,
                "source": point.source,
                "technology": point.technology,
                "improved": point.improved,
                "installed": point.install_year,
                "surveyed": point.report_year,
                "months_per_year": point.months_per_year,
                "distance_m": (
                    round(point.distance_m) if point.distance_m is not None else None
                ),
                "marker-color": colour,
                "fill": colour,
                "stroke": "#FFFFFF",
            }
        )
        features.append(_point(point.lon, point.lat, properties))
    return features


def portfolio_features(points: Iterable[dict]) -> list[dict]:
    """Point features from :func:`groundwater.portfolio.portfolio_points`.

    Those are already ``{label, lat, lon, status}`` dicts in WGS84, so
    this only attaches the status colour and its readable label.
    """
    features = []
    for point in points:
        status = coerce_status(point.get("status")).value
        colour = STATUS_COLORS[status]
        properties = _clean(
            {
                "label": point.get("label"),
                "status": STATUS_LABELS[status],
                "marker-color": colour,
                "fill": colour,
                "stroke": "#FFFFFF",
            }
        )
        features.append(_point(point["lon"], point["lat"], properties))
    return features


def area_features(areas: Iterable) -> list[dict]:
    """Polygon features from :class:`~groundwater.mapping.regional.AdminArea`.

    Interior rings are kept. Nongowa encloses Kenema Town, and a chiefdom
    drawn without its hole swallows the town it surrounds.
    """
    features = []
    for area in areas:
        holes = list(getattr(area, "holes", []) or [])
        polygons = []
        for index, ring in enumerate(area.rings):
            inner = holes[index] if index < len(holes) else []
            polygons.append([_ring(ring)] + [_ring(hole) for hole in inner])
        if not polygons:
            continue
        geometry = (
            {"type": "Polygon", "coordinates": polygons[0]}
            if len(polygons) == 1
            else {"type": "MultiPolygon", "coordinates": polygons}
        )
        properties = _clean(
            {
                "name": area.name,
                "level": area.level,
                "district": getattr(area, "district", ""),
                "fill": "#FFFFFF",
                "fill-opacity": 0.0,
                "stroke": "#6B7785",
                "stroke-width": 1,
            }
        )
        features.append(_feature(geometry, properties))
    return features


def unit_features(units: Iterable) -> list[dict]:
    """Polygon features from :class:`~groundwater.mapping.regional.GeologyUnit`.

    Serves both the geology and the aquifer layers: the loaders return the
    same shape, with ``glg`` carrying the USGS unit code in one and the BGS
    combined code in the other. Each polygon keeps the colour its own
    dataset assigns, so the map matches the printed one.
    """
    features = []
    for unit in units:
        properties = _clean(
            {
                "code": unit.glg,
                "unit": unit.unit,
                "class": unit.era,
                "fill": unit.color,
                "fill-opacity": 0.7,
                "stroke": "#FFFFFF",
                "stroke-width": 0.5,
            }
        )
        features.append(
            _feature(
                {"type": "Polygon", "coordinates": [_ring(unit.ring)]}, properties
            )
        )
    return features


# ---------------------------------------------------------------------------
# Layers, framing and the project itself
# ---------------------------------------------------------------------------


def geojson_layer(
    name: str,
    features: Sequence[dict],
    *,
    kind: str = "point",
    color: str = "#17527E",
    stroke: str = "#FFFFFF",
    radius: float = 7.0,
    fill_opacity: float = 0.7,
    stroke_width: float = 1.0,
    visible: bool = True,
    opacity: float = 1.0,
    attribution: str = "",
) -> dict:
    """One inline GeoJSON layer.

    ``kind`` picks the fallback single-symbol style, which is what a
    viewer that ignores the per-feature simplestyle properties will draw.
    Both are written: the features carry their own colours, and the layer
    still looks deliberate without them.
    """
    style = {
        "simpleStyleEnabled": True,
        "fillColor": color,
        "strokeColor": stroke,
        "strokeWidth": stroke_width,
        "fillOpacity": 1.0 if kind == "point" else fill_opacity,
    }
    if kind == "point":
        style["circleRadius"] = radius
    layer = {
        "id": _slug(name),
        "name": name,
        "type": "geojson",
        "source": {"type": "geojson"},
        "visible": visible,
        "opacity": opacity,
        "style": style,
        "geojson": {"type": "FeatureCollection", "features": list(features)},
        "metadata": {},
    }
    if attribution:
        layer["metadata"]["attribution"] = attribution
    return layer


def _geometry_bbox(geometry: dict) -> tuple[float, float, float, float] | None:
    """West, south, east, north of one geometry, at any nesting depth."""
    west = south = math.inf
    east = north = -math.inf

    def walk(coordinates) -> None:
        nonlocal west, south, east, north
        if (
            len(coordinates) == 2
            and isinstance(coordinates[0], (int, float))
            and isinstance(coordinates[1], (int, float))
        ):
            lon, lat = coordinates
            west, east = min(west, lon), max(east, lon)
            south, north = min(south, lat), max(north, lat)
            return
        for part in coordinates:
            walk(part)

    if not (geometry or {}).get("coordinates"):
        return None
    walk(geometry["coordinates"])
    return None if west is math.inf else (west, south, east, north)


def _layer_bbox(layer: dict) -> tuple[float, float, float, float] | None:
    """West, south, east, north over every feature in a layer."""
    return _union(
        _geometry_bbox(feature.get("geometry") or {})
        for feature in layer.get("geojson", {}).get("features", [])
    )


def window_around(lat: float, lon: float, radius_km: float):
    """A square window of ``radius_km`` about a position, in degrees.

    The same window the printed local geology and aquifer maps are drawn
    in, expressed as a bounding box so features can be selected against
    it. A degree of latitude is a fixed distance; a degree of longitude
    shrinks towards the poles, so it is scaled by the cosine.
    """
    dlat = radius_km / 111.32
    dlon = radius_km / max(111.32 * math.cos(math.radians(lat)), 1e-6)
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def points_within_window(points: Iterable, window) -> list:
    """Water points whose position falls inside ``window``.

    Applied to the records rather than to features built from them, because
    the inventory this filters can be national. The web app's coverage page
    fetches up to 200,000 points into the same place the site page reads
    them from, and building a quarter of a million features in order to
    throw almost all of them away is work nobody asked for.
    """
    if window is None:
        return list(points)
    west, south, east, north = window
    return [
        point for point in points
        if west <= point.lon <= east and south <= point.lat <= north
    ]


def features_within(features: Iterable[dict], window) -> list[dict]:
    """Features whose extent reaches into ``window``.

    A bounding-box test, not a clip. A polygon that overlaps the window is
    kept whole, so the unit the site sits in arrives with its real shape
    rather than a truncated one, and nothing is invented at the edge. It
    is there to keep a national layer from being inlined in full when only
    the ground around the site is being asked about.
    """
    if window is None:
        return list(features)
    kept = []
    for feature in features:
        bbox = _geometry_bbox(feature.get("geometry") or {})
        if bbox is not None and _overlaps(bbox, window):
            kept.append(feature)
    return kept


def _union(boxes: Iterable[tuple[float, float, float, float]]):
    """The bounding box covering every box given, or ``None`` for none."""
    boxes = [box for box in boxes if box]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _at_least(bbox, span: float):
    """Grow a bounding box about its centre until it spans at least ``span``."""
    west, south, east, north = bbox
    if east - west < span:
        mid = (west + east) / 2
        west, east = mid - span / 2, mid + span / 2
    if north - south < span:
        mid = (south + north) / 2
        south, north = mid - span / 2, mid + span / 2
    return west, south, east, north


def _ring_bbox(points):
    """West, south, east, north of a ring, without importing numpy."""
    lons = []
    lats = []
    for lon, lat in points:
        lons.append(float(lon))
        lats.append(float(lat))
    if not lons:
        return None
    return min(lons), min(lats), max(lons), max(lats)


def _overlaps(a, b) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _merc_y(lat: float) -> float:
    """Web Mercator y for a latitude, clamped short of the poles."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


#: The smallest extent a project is framed on, in degrees - about 550 m
#: at this latitude. A project holding one borehole has no extent at all,
#: and framing it literally opens at maximum zoom on a blank background
#: with the wellhead filling the screen. A survey is looked at over a few
#: hundred metres, so that is the floor.
_MIN_SPAN_DEG = 0.005


def _frame(
    bbox: tuple[float, float, float, float],
    *,
    width_px: float = 1024.0,
    height_px: float = 768.0,
    pad: float = 0.12,
) -> tuple[list[float], float]:
    """Centre and zoom that fit a bounding box, with a margin.

    The format stores a centre and a zoom rather than a bounding box, so
    the fit is computed here. It is an approximation - the viewport is
    assumed rather than known - and it is allowed to be: half a zoom
    level either way is the difference between a comfortable margin and a
    generous one, not between the right place and the wrong one.
    """
    west, south, east, north = _at_least(bbox, _MIN_SPAN_DEG)
    centre = [_round((west + east) / 2), _round((south + north) / 2)]
    lon_span = max(east - west, 1e-6)
    y_span = max(_merc_y(north) - _merc_y(south), 1e-9)
    zoom_lon = math.log2(width_px * 360.0 / (256.0 * lon_span))
    zoom_lat = math.log2(height_px * 2 * math.pi / (256.0 * y_span))
    zoom = min(zoom_lon, zoom_lat) - math.log2(1 + 2 * pad)
    return centre, round(max(0.0, min(zoom, 20.0)), 2)


def _assert_no_secrets(metadata, _where: str = "metadata") -> None:
    """Refuse metadata that looks like a credential, at any depth.

    A GeoLibre project is a file made to be handed to somebody else. The
    rule the rest of this toolkit keeps - the API key stays out of saved
    project files, so sharing a project never shares the key - is only
    kept if something checks, so this checks.

    It recurses, because a guard that reads only the top level is a guard
    that says ``{"service": {"api_key": ...}}`` is fine, and the file it
    waves through carries the key anyway. Only the metadata regions are
    scanned - the project's and each layer's - and not feature properties:
    a credential does not arrive as an attribute of a mapped water point,
    and walking a national inventory to look for one would cost more than
    it could ever find.
    """
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            lowered = str(key).lower()
            if any(hint in lowered for hint in _SECRET_HINTS):
                raise ValueError(
                    f"refusing to write {key!r} into a GeoLibre project "
                    f"({_where}): it reads as a credential, and a project "
                    "file is made to be shared"
                )
            _assert_no_secrets(value, f"{_where}.{key}")
    elif isinstance(metadata, (list, tuple)):
        for item in metadata:
            _assert_no_secrets(item, _where)


def build_project(
    name: str,
    layers: Sequence[dict],
    *,
    center: Sequence[float] | None = None,
    zoom: float | None = None,
    metadata: dict | None = None,
    legend_title: str = "Legend",
    basemap: str = BLANK_BASEMAP,
    credits: Sequence[str] = (),
    frame_on: Sequence[str] = (),
) -> dict:
    """Assemble a ``.geolibre.json`` project from prepared layers.

    Empty layers are dropped rather than written: a legend entry for a
    layer with nothing in it says there is nothing there, which is not
    the same as saying nothing was looked for.

    ``frame_on`` names the layers the camera should open on. Without it a
    site project frames every layer it holds, and since the geology layer
    covers Sierra Leone that means opening on Sierra Leone - the country,
    with the survey somewhere in it as three pixels. The context layers
    are there to be zoomed out to, not to be opened at. Named layers with
    nothing in them are ignored, so a project written before the survey
    arrived still frames on whatever it does have.
    """
    kept = [
        layer
        for layer in layers
        if layer and layer.get("geojson", {}).get("features")
    ]

    seen: dict[str, int] = {}
    for layer in kept:
        base = layer["id"]
        count = seen.get(base, 0)
        seen[base] = count + 1
        if count:
            layer["id"] = f"{base}-{count + 1}"

    wanted = {_slug(name) for name in frame_on}
    focal = [layer for layer in kept if layer["id"] in wanted]
    bbox = _union(_layer_bbox(layer) for layer in (focal or kept))

    if bbox is None:
        # Nothing to frame: the centre of Sierra Leone, whole country.
        center = center if center is not None else [-11.78, 8.46]
        zoom = zoom if zoom is not None else 7.0
    else:
        framed_center, framed_zoom = _frame(bbox)
        center = center if center is not None else framed_center
        zoom = zoom if zoom is not None else framed_zoom

    map_view = {
        "center": [_round(center[0]), _round(center[1])],
        "zoom": round(float(zoom), 2),
        "bearing": 0,
        "pitch": 0,
    }
    if bbox is not None:
        map_view["bbox"] = [_round(v) for v in _at_least(bbox, _MIN_SPAN_DEG)]

    project_metadata = dict(metadata or {})
    _assert_no_secrets(project_metadata, "project metadata")
    for layer in kept:
        _assert_no_secrets(layer.get("metadata"), f"layer {layer['name']!r}")
    project_metadata.setdefault("generator", "Groundwater Investigation Toolkit")
    layer_credits = [
        layer["metadata"]["attribution"]
        for layer in kept
        if layer.get("metadata", {}).get("attribution")
    ]
    attribution = list(dict.fromkeys(list(credits) + layer_credits))
    if attribution:
        project_metadata["attribution"] = attribution

    return {
        "version": PROJECT_FORMAT_VERSION,
        "name": name,
        "mapView": map_view,
        "basemapStyleUrl": basemap,
        "basemapVisible": bool(basemap),
        "basemapOpacity": 1,
        "layers": kept,
        "styles": {layer["id"]: layer["style"] for layer in kept},
        "legend": {"title": legend_title, "groupByLayer": True},
        "metadata": project_metadata,
    }


def write_project(project: dict, path: str | Path) -> Path:
    """Write a project to ``path``, creating parent directories.

    Two spaces of indentation and a trailing newline, so the file is
    readable in a diff and well-formed to every tool that reads the last
    line. ``ensure_ascii=False`` keeps a community name spelled the way
    it is spelled.
    """
    # Checked again here, not only in build_project: this is the point at
    # which the project stops being a dict in memory and becomes a file
    # somebody can send, and a project assembled by hand never passed
    # through the other check at all.
    _assert_no_secrets(project.get("metadata"), "project metadata")
    for layer in project.get("layers", []):
        _assert_no_secrets(layer.get("metadata"), f"layer {layer.get('name')!r}")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(project, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


# ---------------------------------------------------------------------------
# Deep links
# ---------------------------------------------------------------------------


#: Characters left alone inside a deep link's parameter value. A published
#: project URL is itself a URL, and the separators that matter - ``&``, ``=``,
#: ``?``, ``#`` - have to be encoded or the outer query swallows the inner
#: one: a signed link ending ``?sig=a&expires=1`` would otherwise hand
#: GeoLibre an ``expires`` parameter of its own and truncate the address it
#: was supposed to open. The scheme and path separators stay readable, and
#: the set matches JavaScript's ``encodeURIComponent`` exactly so the two
#: apps build the same link.
_LINK_SAFE = ":/!*'()"


def _link(app: str, params: dict) -> str:
    from urllib.parse import quote

    parts = []
    for key, value in params.items():
        # A valueless parameter is written bare, as the GeoLibre
        # documentation writes ``&maponly``, rather than as ``maponly=``.
        parts.append(key if value == "" else
                     f"{key}={quote(str(value), safe=_LINK_SAFE)}")
    query = "&".join(parts)
    separator = "" if app.endswith(("?", "&")) else "?"
    return f"{app.rstrip('?&')}{separator}{query}" if query else app


def project_link(
    url: str,
    *,
    app: str = GEOLIBRE_WEB_APP,
    maponly: bool = False,
    viewer: bool = False,
    theme: str | None = None,
) -> str:
    """A link that opens a *published* project file in GeoLibre.

    ``url`` must be reachable by the browser that follows the link. A file
    that has only been downloaded to the machine has no URL, and no query
    parameter can conjure one - that file is opened from inside GeoLibre
    instead. This is for the hosted case: a project on the Pages site, a
    programme's own server, a shared bucket.
    """
    params = {"url": url}
    if viewer:
        params["layout"] = "viewer"
    if theme:
        params["theme"] = theme
    if maponly:
        params["maponly"] = ""
    return _link(app, params)


def data_link(
    url: str, *, app: str = GEOLIBRE_WEB_APP, style_url: str | None = None
) -> str:
    """A link that opens one published data file - the GeoJSON we export.

    Lighter than a project: no styling, no legend, no framing, just the
    layer on a map. Useful for the bundled national layers, which do have
    a public URL.
    """
    params = {"data": url}
    if style_url:
        params["style"] = style_url
    return _link(app, params)


# ---------------------------------------------------------------------------
# The two projects worth writing
# ---------------------------------------------------------------------------


def site_project(
    *,
    name: str = "",
    site=None,
    zone: int | None = None,
    survey_points: Iterable | None = None,
    suitability: Iterable | None = None,
    water_points: Iterable | None = None,
    chiefdoms: Iterable | None = None,
    geology: Iterable | None = None,
    hydrogeology: Iterable | None = None,
    window_km: float | None = None,
    area=None,
    metadata: dict | None = None,
) -> dict:
    """One site, with whatever context the caller has to hand.

    Every argument is optional, because the toolkit's pages fill up in
    the order the fieldwork happens: a project written after the survey
    has soundings and no borehole, one written after handover has both.
    Layers are ordered back to front - geology and aquifers underneath,
    boundaries over them, then the survey, then the point that matters.

    ``zone`` is the UTM zone the projected inputs are in. It is taken
    from ``site`` when not given, and is only needed when there are
    projected inputs to unproject.

    ``window_km`` trims the national context layers to the ground around
    the site, the same way the printed local geology and aquifer maps are
    windowed. Without it the whole country is inlined, which is correct
    and about 400 kB.

    A site with no GPS fix still gets a project.
    :func:`~groundwater.mapping.regional.area_window` resolves it to the
    chiefdom it is in, or failing that the district, and the map opens
    there. What it does *not* do is plant a marker: a dot at a chiefdom
    centroid is indistinguishable on screen from a surveyed wellhead, and
    a reader who cannot tell the difference will measure from it. So the
    area is framed and named, the ground around it is drawn, and the
    position stays absent because it is absent. Pass ``area`` to override
    the resolution, or nothing to have it done here.
    """
    from ..waterpoints import WPDX_CREDIT
    from .regional import ADMIN_CREDIT, GEOLOGY_CREDIT, HYDRO_CREDIT

    if zone is None and site is not None and site.utm is not None:
        zone = site.utm.zone

    window = None
    center = None
    zoom = None
    has_fix = site is not None and site.latlon is not None
    if has_fix:
        if window_km:
            lat, lon = site.latlon
            window = window_around(lat, lon, window_km)
    elif site is not None:
        if area is None:
            from .regional import area_window as _resolve_area

            area = _resolve_area(site, window_km)
        if area is not None:
            window = window_around(area.lat, area.lon, area.radius_km)
            # Framed explicitly: without a fix there is no focal layer for
            # the camera to find, and the context layers alone would open
            # on the country.
            center, zoom = _frame(window)

    layers: list[dict] = []
    if hydrogeology:
        layers.append(
            geojson_layer(
                "Aquifer productivity",
                features_within(unit_features(hydrogeology), window),
                kind="polygon",
                attribution=HYDRO_CREDIT,
            )
        )
    if geology:
        layers.append(
            geojson_layer(
                "Geology",
                features_within(unit_features(geology), window),
                kind="polygon",
                visible=False,
                attribution=GEOLOGY_CREDIT,
            )
        )
    if chiefdoms:
        layers.append(
            geojson_layer(
                "Chiefdoms",
                features_within(area_features(chiefdoms), window),
                kind="polygon",
                color="#FFFFFF",
                stroke="#6B7785",
                fill_opacity=0.0,
                attribution=ADMIN_CREDIT,
            )
        )
    if water_points:
        # Windowed like the context layers, and for a sharper reason: the
        # water points are one of the layers the camera frames on, so a
        # national inventory arriving here would not merely make the file
        # large, it would open the project on Sierra Leone with the survey
        # lost inside it.
        layers.append(
            geojson_layer(
                "Existing water points",
                water_point_features(points_within_window(water_points, window)),
                radius=6.0,
                attribution=WPDX_CREDIT,
            )
        )
    if survey_points:
        if zone is None:
            raise ValueError(
                "survey_points are in projected UTM metres, so a zone is "
                "needed to unproject them; pass zone= or a site with a position"
            )
        layers.append(
            geojson_layer("Survey points", survey_point_features(survey_points, zone))
        )
    if suitability:
        if zone is None:
            raise ValueError(
                "suitability scores are in projected UTM metres, so a zone is "
                "needed to unproject them; pass zone= or a site with a position"
            )
        layers.append(
            geojson_layer(
                "Drill-target suitability",
                suitability_features(suitability, zone),
                radius=9.0,
                stroke="#222222",
            )
        )

    site_metadata = dict(metadata or {})
    if site is not None:
        site_metadata.update(
            _clean(
                {
                    "community": site.community,
                    "chiefdom": site.chiefdom,
                    "district": site.district,
                    "client": site.client,
                    "project": site.project,
                    "project_ref": site.project_ref,
                }
            )
        )
        latlon = site.latlon
        if latlon is not None:
            lat, lon = latlon
            layers.append(
                geojson_layer(
                    "Site",
                    [
                        _point(
                            lon,
                            lat,
                            _clean(
                                {
                                    "label": site.community or "Site",
                                    "district": site.district,
                                    "chiefdom": site.chiefdom,
                                    "marker-color": "#B23A2E",
                                    "fill": "#B23A2E",
                                    "stroke": "#FFFFFF",
                                }
                            ),
                        )
                    ],
                    radius=10.0,
                    color="#B23A2E",
                )
            )

    if area is not None and not area.exact:
        # Said in the file, not only in the framing: a reader opening this
        # somewhere else has no other way to know the centre is a centroid.
        site_metadata["area"] = area.label
        site_metadata["position"] = (
            f"centred on {area.label} - an area centroid, not a surveyed "
            "position; this site has no GPS fix"
        )

    if not name:
        name = (
            (site.community if site is not None and site.community else "")
            or (area.label if area is not None else "")
            or "Site"
        )

    return build_project(
        name,
        layers,
        center=center,
        zoom=zoom,
        metadata=site_metadata,
        # The survey and the site are what the project is about; the
        # geology underneath it covers Sierra Leone and is context to zoom
        # out to, never the thing to open on.
        frame_on=(
            "Site",
            "Drill-target suitability",
            "Survey points",
            "Existing water points",
        ),
    )


def portfolio_project(
    points: Iterable[dict],
    *,
    name: str = "Borehole portfolio",
    districts: Iterable | None = None,
    metadata: dict | None = None,
) -> dict:
    """Every site in the portfolio, coloured by status, over the districts."""
    from .regional import ADMIN_CREDIT

    layers = []
    if districts:
        layers.append(
            geojson_layer(
                "Districts",
                area_features(districts),
                kind="polygon",
                color="#FFFFFF",
                stroke="#6B7785",
                fill_opacity=0.0,
                attribution=ADMIN_CREDIT,
            )
        )
    layers.append(
        geojson_layer("Boreholes", portfolio_features(points), radius=8.0)
    )
    return build_project(
        name, layers, metadata=dict(metadata or {}), frame_on=("Boreholes",)
    )

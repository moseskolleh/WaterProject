"""Prepare the bundled map datasets from their public sources.

Produces two package data files from real, freely licensed datasets:

``src/groundwater/data/sl_geology_usgs.geojson``
    Geology clipped to the Sierra Leone window from the USGS Geologic
    Map of Africa (geo2_7g, Open-File Report 97-470A; public domain),
    with the dataset's own unit codes, names, eras and colours.

``src/groundwater/data/sl_admin_geoboundaries.geojson``
    The national outline (ADM0) and district polygons (ADM2) from
    geoBoundaries (www.geoboundaries.org), licensed CC BY 4.0.
    Note: the geoBoundaries release predates the 2017 creation of
    Karene and Falaba districts (14 districts, not 16).

``src/groundwater/data/sl_chiefdoms_geoboundaries.geojson``
    Chiefdom polygons (ADM3, 165 chiefdoms) from geoBoundaries
    (gbOpen, CC BY 4.0), each tagged with its parent district. Used for
    chiefdom auto-detection from GPS and finer maps.

The raw inputs are NOT committed (about 40 MB). To regenerate, first
download them into a working directory:

    Africa_Geological_Data.{shp,shx,dbf,prj} from
      https://github.com/Heed725/Africa_Geology_Data_Shapefile
      (mirror of the USGS data; also at pubs.usgs.gov OFR 97-470A)
    geoBoundaries-SLE-ADM0_simplified.geojson and
    geoBoundaries-SLE-ADM2_simplified.geojson from
      https://github.com/wmgeolab/geoBoundaries
      (releaseData/gbOpen/SLE/...; git-lfs content)

then run:

    python web/build_geodata.py --raw <working directory>

Requires ``pyshp`` (pure Python) for the shapefile only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "src" / "groundwater" / "data"

# Sierra Leone window with a margin so the country mask has clean edges.
BBOX = (-13.55, 6.70, -10.05, 10.15)  # lon_min, lat_min, lon_max, lat_max

GEOLOGY_ATTRIBUTION = (
    "Geology from the USGS Geologic Map of Africa (geo2_7g, Open-File "
    "Report 97-470A), public domain, 1:5,000,000 scale; clipped to the "
    "Sierra Leone window without modification of the unit boundaries "
    "beyond line simplification."
)
ADMIN_ATTRIBUTION = (
    "Boundaries from geoBoundaries (www.geoboundaries.org), CC BY 4.0 "
    "(Runfola et al. 2020, PLoS ONE 15(4): e0231866). The district set "
    "predates the 2017 creation of Karene and Falaba (14 districts)."
)
HYDRO_ATTRIBUTION = (
    "Hydrogeology (aquifer type and productivity) from the BGS Africa "
    "Groundwater Atlas country map for Sierra Leone (O Dochartaigh 2021, "
    "BGS Open Report OR/21/063), CC BY-SA 4.0. This derived file is "
    "likewise CC BY-SA 4.0. Source shapefile and licence in "
    "WaterProjectFiles/SierraLeone_BGS_Hydrogeology/."
)

# Display labels and colours for the BGS aquifer classes.
HYDRO_CLASSES = {
    "U-M/H": ("Unconsolidated intergranular aquifer - moderate to high productivity", "#6BAED6"),
    "CSF-L/M": ("Consolidated sedimentary aquifer, fracture flow - low to moderate productivity", "#74C476"),
    "B-L": ("Basement aquifer - low productivity", "#FDBB84"),
    "I-L": ("Igneous intrusive aquifer - low productivity", "#C994C7"),
    "n/a": ("Surface water", "#2171B5"),
}


# ---------------------------------------------------------------------------
# Geometry helpers (pure Python, degree coordinates)
# ---------------------------------------------------------------------------

def simplify_ring(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker simplification; keeps rings closed.

    A closed ring cannot go straight through DP (the anchor segment
    start == end is degenerate and the whole ring collapses), so it is
    split at the vertex farthest from the start and each half is
    simplified separately.
    """
    pts = [tuple(p) for p in points]
    closed = pts[0] == pts[-1]
    if not closed:
        return _dp(pts, tol)
    pts = pts[:-1]
    if len(pts) < 4:
        return pts + [pts[0]]
    x0, y0 = pts[0]
    split = max(
        range(1, len(pts)),
        key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2,
    )
    first = _dp(pts[: split + 1], tol)
    second = _dp(pts[split:] + [pts[0]], tol)
    out = first[:-1] + second[:-1]
    if len(out) < 3:
        return pts + [pts[0]]
    return out + [out[0]]


def _dp(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    if len(pts) < 3:
        return list(pts)
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
    index, dmax = 0, 0.0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            index, dmax = i, d
    if dmax > tol:
        left = _dp(pts[: index + 1], tol)
        right = _dp(pts[index:], tol)
        return left[:-1] + right
    return [pts[0], pts[-1]]


def clip_ring_to_bbox(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sutherland-Hodgman clip of a polygon ring against the bbox."""
    lon_min, lat_min, lon_max, lat_max = BBOX
    edges = (
        lambda p: p[0] >= lon_min,
        lambda p: p[0] <= lon_max,
        lambda p: p[1] >= lat_min,
        lambda p: p[1] <= lat_max,
    )
    intersect = (
        lambda a, b: (lon_min, a[1] + (b[1] - a[1]) * (lon_min - a[0]) / (b[0] - a[0])),
        lambda a, b: (lon_max, a[1] + (b[1] - a[1]) * (lon_max - a[0]) / (b[0] - a[0])),
        lambda a, b: (a[0] + (b[0] - a[0]) * (lat_min - a[1]) / (b[1] - a[1]), lat_min),
        lambda a, b: (a[0] + (b[0] - a[0]) * (lat_max - a[1]) / (b[1] - a[1]), lat_max),
    )
    ring = [tuple(p) for p in points]
    for inside, cross in zip(edges, intersect):
        if not ring:
            return []
        out: list[tuple[float, float]] = []
        prev = ring[-1]
        for cur in ring:
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
            prev = cur
        ring = out
    if ring and ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    return ring


def ring_area(points: list[tuple[float, float]]) -> float:
    """Absolute shoelace area in square degrees."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_geology(raw: Path, tol: float = 0.004, min_area: float = 2e-4) -> Path:
    import shapefile  # pyshp, only needed here

    sf = shapefile.Reader(str(raw / "Africa_Geological_Data"))
    fields = [f[0] for f in sf.fields[1:]]
    features = []
    for i, shape in enumerate(sf.iterShapes()):
        x0, y0, x1, y1 = shape.bbox
        if x1 < BBOX[0] or x0 > BBOX[2] or y1 < BBOX[1] or y0 > BBOX[3]:
            continue
        rec = dict(zip(fields, sf.record(i)))
        if rec["GLG"] in ("SEA",):
            continue
        parts = list(shape.parts) + [len(shape.points)]
        for start, end in zip(parts[:-1], parts[1:]):
            ring = clip_ring_to_bbox(shape.points[start:end])
            if len(ring) < 4:
                continue
            ring = simplify_ring(ring, tol)
            if len(ring) < 4 or ring_area(ring) < min_area:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "glg": rec["GLG"],
                        "unit": str(rec["long_name"]),
                        "era": str(rec["era"]),
                        "color": str(rec["color"]),
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[round(x, 4), round(y, 4)] for x, y in ring]],
                    },
                }
            )
    # biggest polygons first so small units draw on top
    features.sort(
        key=lambda f: ring_area(
            [tuple(p) for p in f["geometry"]["coordinates"][0]]
        ),
        reverse=True,
    )
    out = OUT / "sl_geology_usgs.geojson"
    payload = {
        "type": "FeatureCollection",
        "name": "sl_geology_usgs",
        "description": GEOLOGY_ATTRIBUTION,
        "features": features,
    }
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, {len(features)} polygons)")
    return out


def build_admin(raw: Path, tol: float = 0.003) -> Path:
    features = []
    for level, fname in (
        ("ADM0", "geoBoundaries-SLE-ADM0_simplified.geojson"),
        ("ADM2", "geoBoundaries-SLE-ADM2_simplified.geojson"),
    ):
        data = json.loads((raw / fname).read_text(encoding="utf-8"))
        for feature in data["features"]:
            geom = feature["geometry"]
            polys = (
                geom["coordinates"]
                if geom["type"] == "MultiPolygon"
                else [geom["coordinates"]]
            )
            rings = []
            for poly in polys:
                outer = simplify_ring([tuple(p) for p in poly[0]], tol)
                if len(outer) >= 4:
                    rings.append([[round(x, 4), round(y, 4)] for x, y in outer])
            if not rings:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "level": level,
                        "name": feature["properties"].get("shapeName", ""),
                    },
                    "geometry": {"type": "MultiPolygon",
                                 "coordinates": [[r] for r in rings]},
                }
            )
    out = OUT / "sl_admin_geoboundaries.geojson"
    payload = {
        "type": "FeatureCollection",
        "name": "sl_admin_geoboundaries",
        "description": ADMIN_ATTRIBUTION,
        "features": features,
    }
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    n0 = sum(1 for f in features if f["properties"]["level"] == "ADM0")
    n2 = sum(1 for f in features if f["properties"]["level"] == "ADM2")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, "
          f"{n0} outline + {n2} districts)")
    return out


def build_hydrogeology(tol: float = 0.002, min_area: float = 1e-4) -> Path:
    """BGS hydrogeology map from the committed source shapefile."""
    import shapefile  # pyshp, only needed here

    src = REPO / "WaterProjectFiles" / "SierraLeone_BGS_Hydrogeology"
    sf = shapefile.Reader(str(src / "SierraLeone_HG"))
    fields = [f[0] for f in sf.fields[1:]]
    features = []
    for i, shape in enumerate(sf.iterShapes()):
        rec = dict(zip(fields, sf.record(i)))
        code = str(rec.get("SLHGComb", "")).strip()
        label, color = HYDRO_CLASSES.get(
            code, (f"{rec.get('SLGLG', 'unit')} ({code})", "#CCCCCC")
        )
        parts = list(shape.parts) + [len(shape.points)]
        for start, end in zip(parts[:-1], parts[1:]):
            ring = simplify_ring([tuple(p) for p in shape.points[start:end]], tol)
            if len(ring) < 4 or ring_area(ring) < min_area:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "code": code,
                        "geology": str(rec.get("SLGLG", "")),
                        "unit": label,
                        "color": color,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[round(x, 4), round(y, 4)] for x, y in ring]],
                    },
                }
            )
    features.sort(
        key=lambda f: ring_area(
            [tuple(p) for p in f["geometry"]["coordinates"][0]]
        ),
        reverse=True,
    )
    out = OUT / "sl_hydrogeology_bgs.geojson"
    payload = {
        "type": "FeatureCollection",
        "name": "sl_hydrogeology_bgs",
        "description": HYDRO_ATTRIBUTION,
        "features": features,
    }
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, {len(features)} polygons)")
    return out


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
        if (y1 > lat) != (y2 > lat):
            xc = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < xc:
                inside = not inside
    return inside


def build_chiefdoms(raw: Path, tol: float = 0.004) -> Path:
    """Chiefdom (ADM3) polygons with their parent district.

    Reads ``geoBoundaries-SLE-ADM3_simplified.geojson`` and the ADM2
    districts from ``raw`` (both from
    https://github.com/wmgeolab/geoBoundaries, gbOpen, CC BY 4.0; the
    real content lives on git-lfs / media.githubusercontent.com),
    simplifies each ring and derives the parent district from the
    chiefdom centroid. Writes ``sl_chiefdoms_geoboundaries.geojson``.
    """
    def rings_of(geom):
        coords = geom.get("coordinates", [])
        return coords if geom.get("type") == "MultiPolygon" else [coords]

    adm2 = json.loads((raw / "geoBoundaries-SLE-ADM2_simplified.geojson").read_text())
    districts = [
        (f["properties"].get("shapeName"), poly[0])
        for f in adm2["features"]
        for poly in rings_of(f["geometry"]) if poly
    ]

    def district_of(lon, lat):
        for name, ring in districts:
            if _point_in_ring(lon, lat, ring):
                return name
        cx_cy = min(
            districts,
            key=lambda d: (sum(p[0] for p in d[1]) / len(d[1]) - lon) ** 2
            + (sum(p[1] for p in d[1]) / len(d[1]) - lat) ** 2,
        )
        return cx_cy[0]

    adm3 = json.loads((raw / "geoBoundaries-SLE-ADM3_simplified.geojson").read_text())
    features = []
    for f in adm3["features"]:
        polys = rings_of(f["geometry"])
        outer = [pt for poly in polys if poly for pt in poly[0]]
        if not outer:
            continue
        cx = sum(p[0] for p in outer) / len(outer)
        cy = sum(p[1] for p in outer) / len(outer)
        new_polys = []
        for poly in polys:
            new_rings = [
                [[round(x, 5), round(y, 5)]
                 for x, y in simplify_ring([tuple(p) for p in ring], tol)]
                for ring in poly
                if len(simplify_ring([tuple(p) for p in ring], tol)) >= 4
            ]
            if new_rings:
                new_polys.append(new_rings)
        if not new_polys:
            continue
        geom = ({"type": "Polygon", "coordinates": new_polys[0]}
                if len(new_polys) == 1
                else {"type": "MultiPolygon", "coordinates": new_polys})
        features.append({
            "type": "Feature",
            "properties": {"name": f["properties"].get("shapeName", ""),
                           "district": district_of(cx, cy)},
            "geometry": geom,
        })
    payload = {
        "type": "FeatureCollection",
        "attribution": "Chiefdoms from geoBoundaries (gbOpen, CC BY 4.0)",
        "features": features,
    }
    out = OUT / "sl_chiefdoms_geoboundaries.geojson"
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(features)} chiefdoms)")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default=None,
                        help="directory holding the downloaded raw datasets "
                        "(geology, admin and chiefdoms); omit to rebuild only "
                        "the hydrogeology layer from the committed source")
    args = parser.parse_args()
    if args.raw:
        raw = Path(args.raw)
        build_geology(raw)
        build_admin(raw)
        build_chiefdoms(raw)
    build_hydrogeology()


if __name__ == "__main__":
    main()

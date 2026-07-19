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

``src/groundwater/data/sl_population_district.csv``
    Resident population of the 16 current districts from the Statistics
    Sierra Leone 2015 Population and Housing Census (sums to the official
    national total of 7,092,113). Built from embedded published figures,
    so no raw download is needed.

``src/groundwater/data/sl_chiefdom_district.csv``
    A chiefdom -> current-district crosswalk, so a point can be placed in
    a current district (Karene/Falaba included) via the chiefdom polygons
    even though the ADM2 boundaries predate 2017. Built from the census
    chiefdom table ``SL_Doc.csv`` (Statistics Sierra Leone, via
    github.com/timothy-horton/SL_Map) placed in the raw directory.

``src/groundwater/data/sl_population_chiefdom.csv``
    The 2015 census population of all 208 chiefdoms (Statistics Sierra
    Leone, "Distribution of Total Population by Regions, Districts and
    Chiefdoms"), extracted from the census PDF. A committed source file
    (the 16 district subtotals reproduce the official district totals
    exactly), not rebuilt here.

``src/groundwater/data/sl_census_crosswalk.csv``
    Each census chiefdom mapped to the geoBoundaries chiefdom polygon that
    contains it (within the same current district), so census populations
    can be aggregated onto the 166 pre-2017 polygons. Built by
    ``build_census_crosswalk`` from the two files above; the build asserts
    that the aggregation conserves every district total exactly.

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
import csv
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
    features = split_koya_feature(features)
    payload = {
        "type": "FeatureCollection",
        "attribution": "Chiefdoms from geoBoundaries (gbOpen, CC BY 4.0)",
        "features": features,
    }
    out = OUT / "sl_chiefdoms_geoboundaries.geojson"
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(features)} chiefdoms)")
    return out


# Statistics Sierra Leone, 2015 Population and Housing Census: resident
# population of the 16 current districts. Published government statistics;
# the values sum to the official national total of 7,092,113.
DISTRICT_POPULATION_2015 = {
    "Bo": 575478, "Bombali": 422960, "Bonthe": 200781, "Falaba": 205353,
    "Kailahun": 526379, "Kambia": 345474, "Karene": 285546, "Kenema": 609891,
    "Koinadugu": 204019, "Kono": 506100, "Moyamba": 318588, "Port Loko": 530865,
    "Pujehun": 346461, "Tonkolili": 513984, "Western Area Rural": 444270,
    "Western Area Urban": 1055964,
}

# geoBoundaries chiefdom -> current district where the automatic name match is
# ambiguous or absent (each verified against the polygon centroid):
#   TMS               = Thainkatopa/Makama/Safroko, centroid in Port Loko;
#   Koya              = after split_koya_feature, only the eastern lobe (the
#                       Kenema chiefdom, centroid 7.65N/11.29W); still needs an
#                       override because "koya" collides with the Port Loko Koya
#                       and the "Koya Rural" prefix in the census table;
#   Koya (Port Loko)  = the western lobe split out below.
CHIEFDOM_DISTRICT_OVERRIDES = {
    "TMS": "Port Loko",
    "Koya": "Kenema",
    "Koya (Port Loko)": "Port Loko",
}


def split_koya_feature(features: list) -> list:
    """Split the merged geoBoundaries "Koya" feature into its two chiefdoms.

    geoBoundaries dissolves same-named ADM3 units, so the single "Koya" feature
    merges two distinct chiefdoms in two districts: the eastern lobe is Koya in
    Kenema (centroid ~11.29 W), the western lobe is Koya in Port Loko (centroid
    ~12.87 W, about three times larger). One name -> district label cannot
    represent that, so a water point in the larger western lobe would be
    mis-counted. Split by longitude: rings west of 12 W become
    "Koya (Port Loko)", the rest stay "Koya" (the Kenema chiefdom).
    """
    out: list = []
    for feature in features:
        if feature["properties"].get("name") != "Koya":
            out.append(feature)
            continue
        geom = feature["geometry"]
        polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])
        west, east = [], []
        for poly in polys:
            ring = poly[0]
            centre_lon = sum(p[0] for p in ring) / len(ring)
            (west if centre_lon < -12.0 else east).append(poly)
        for name, district, group in (
            ("Koya", "Kenema", east),
            ("Koya (Port Loko)", "Port Loko", west),
        ):
            if not group:
                continue
            geometry = (
                {"type": "Polygon", "coordinates": group[0]}
                if len(group) == 1
                else {"type": "MultiPolygon", "coordinates": group}
            )
            out.append({
                "type": "Feature",
                "properties": {"name": name, "district": district},
                "geometry": geometry,
            })
    return out


def build_population() -> Path:
    """District population table (2015 census, 16 current districts).

    Writes ``sl_population_district.csv`` from the published Statistics Sierra
    Leone figures embedded above (they are the authoritative source, so no raw
    download is needed).
    """
    assert sum(DISTRICT_POPULATION_2015.values()) == 7_092_113
    out = OUT / "sl_population_district.csv"
    lines = ["district,population"] + [
        f"{d},{DISTRICT_POPULATION_2015[d]}"
        for d in sorted(DISTRICT_POPULATION_2015)
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(DISTRICT_POPULATION_2015)} districts)")
    return out


def _norm_name(name: str) -> str:
    import re
    import unicodedata

    ascii_ = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_.lower())).strip()


def build_chiefdom_district(raw: Path) -> Path:
    """Chiefdom -> current-district crosswalk.

    Matches the committed chiefdom polygons (geoBoundaries names, truncated to
    15 chars) to the 2015 census chiefdom table ``SL_Doc.csv`` (columns REGION,
    DISTRICT, CHIEFDOM, POPULATION - Statistics Sierra Leone, via
    github.com/timothy-horton/SL_Map) by normalised name or prefix, mapping the
    census 16-district labels to canonical names, with the small verified
    override table above. Every chiefdom must resolve to exactly one district
    that exists in the population table, or the build fails loudly. Writes
    ``sl_chiefdom_district.csv``.
    """
    def to_current(label: str) -> str:
        label = label.strip().title()
        return {"Karena": "Karene", "Urban": "Western Area Urban",
                "Rural": "Western Area Rural"}.get(label, label)

    rows = list(csv.DictReader((raw / "SL_Doc.csv").read_text().splitlines()))
    index: dict[str, set] = {}
    for row in rows:
        index.setdefault(_norm_name(row["CHIEFDOM"]), set()).add(
            to_current(row["DISTRICT"])
        )
    chiefdoms = json.loads(
        (OUT / "sl_chiefdoms_geoboundaries.geojson").read_text()
    )
    crosswalk: list[tuple[str, str]] = []
    for feature in chiefdoms["features"]:
        name = feature["properties"]["name"]
        if name in CHIEFDOM_DISTRICT_OVERRIDES:
            crosswalk.append((name, CHIEFDOM_DISTRICT_OVERRIDES[name]))
            continue
        norm = _norm_name(name)
        if norm in index and len(index[norm]) == 1:
            crosswalk.append((name, next(iter(index[norm]))))
            continue
        candidates: set = set()
        for key, value in index.items():
            if key.startswith(norm) or norm.startswith(key):
                candidates |= value
        if len(candidates) != 1:
            raise ValueError(
                f"unresolved chiefdom -> district for {name!r}: {sorted(candidates)}"
            )
        crosswalk.append((name, next(iter(candidates))))
    unknown = sorted({d for _, d in crosswalk} - set(DISTRICT_POPULATION_2015))
    if unknown:
        raise ValueError(f"crosswalk districts not in population table: {unknown}")
    if len(crosswalk) != len(chiefdoms["features"]):
        raise ValueError(
            f"crosswalk has {len(crosswalk)} rows for "
            f"{len(chiefdoms['features'])} chiefdom features"
        )
    out = OUT / "sl_chiefdom_district.csv"
    lines = ["chiefdom,district"] + [
        f"{c},{d}" for c, d in sorted(crosswalk)
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(crosswalk)} chiefdoms)")
    return out


# census chiefdom -> geoBoundaries chiefdom polygon, where the automatic
# fuzzy match is wrong (each keyed by the census (district, chiefdom)). TMS =
# Thainkatopa/Makama/Safroko; its Port Loko lobe is these two census chiefdoms.
CENSUS_CROSSWALK_OVERRIDES = {
    ("Port Loko", "Thainkatopa"): "TMS",
    ("Port Loko", "Makama"): "TMS",
}


def _census_norm(name: str) -> str:
    import re
    import unicodedata

    roman = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5"}
    ascii_ = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    toks = [roman.get(t, t) for t in re.sub(r"[^a-z0-9]+", " ", ascii_.lower()).split()]
    return " ".join(t for t in toks if t not in ("city", "town")).strip()


def build_census_crosswalk() -> Path:
    """Census chiefdom -> geoBoundaries chiefdom-polygon crosswalk.

    Maps every row of the committed ``sl_population_chiefdom.csv`` (the 2015
    census chiefdom table extracted from the Statistics Sierra Leone PDF) onto
    one of the bundled chiefdom polygons, within the same current district
    (from ``sl_chiefdom_district.csv``). Matching is exact-normalised, then by
    shared name tokens, then fuzzy (``difflib``), with a small override table
    for cases the fuzzy score gets wrong. Because every census chiefdom maps to
    a polygon in its own district, aggregating the census populations by
    polygon conserves each district's authoritative total exactly - the build
    asserts this. Writes ``sl_census_crosswalk.csv``.
    """
    import difflib

    census = list(csv.DictReader(
        (OUT / "sl_population_chiefdom.csv").read_text().splitlines()))
    gb_district = dict(csv.reader(
        (OUT / "sl_chiefdom_district.csv").read_text().splitlines()[1:]))
    by_district: dict[str, list] = {}
    for chiefdom, district in gb_district.items():
        by_district.setdefault(district, []).append(chiefdom)

    def best(chiefdom: str, district: str) -> str:
        if (district, chiefdom) in CENSUS_CROSSWALK_OVERRIDES:
            return CENSUS_CROSSWALK_OVERRIDES[(district, chiefdom)]
        norm = _census_norm(chiefdom)
        tokens = set(norm.split())
        scored = []
        for candidate in by_district.get(district, []):
            cnorm = _census_norm(candidate)
            if cnorm == norm:
                return candidate
            shared = len(tokens & set(cnorm.split()))
            ratio = difflib.SequenceMatcher(None, norm, cnorm).ratio()
            prefix = 2 if (norm.startswith(cnorm) or cnorm.startswith(norm)) else 0
            scored.append((shared * 10 + ratio + prefix, candidate))
        scored.sort(reverse=True)
        return scored[0][1]

    rows = [(r["district"], r["chiefdom"], best(r["chiefdom"], r["district"]))
            for r in census]

    # conservation check: census populations aggregated by polygon must
    # reproduce every authoritative district total exactly
    pop = {r["district"] + "\0" + r["chiefdom"]: int(r["population"])
           for r in census}
    by_gb: dict[str, int] = {}
    for district, chiefdom, gb in rows:
        by_gb[gb] = by_gb.get(gb, 0) + pop[district + "\0" + chiefdom]
    district_sum: dict[str, int] = {}
    for gb, value in by_gb.items():
        district_sum[gb_district[gb]] = district_sum.get(gb_district[gb], 0) + value
    for district, total in DISTRICT_POPULATION_2015.items():
        if district_sum.get(district, 0) != total:
            raise ValueError(
                f"census crosswalk does not conserve {district}: "
                f"{district_sum.get(district, 0)} vs {total}"
            )

    out = OUT / "sl_census_crosswalk.csv"
    lines = ["district,census_chiefdom,gb_chiefdom"] + [
        f"{d},{c},{g}" for d, c, g in rows
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(rows)} census chiefdoms)")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default=None,
                        help="directory holding the downloaded raw datasets "
                        "(geology, admin, chiefdoms and the SL_Doc.csv census "
                        "table); omit to rebuild only the layers with a "
                        "committed source")
    args = parser.parse_args()
    if args.raw:
        raw = Path(args.raw)
        build_geology(raw)
        build_admin(raw)
        build_chiefdoms(raw)
        build_chiefdom_district(raw)
    build_hydrogeology()
    build_population()
    build_census_crosswalk()


if __name__ == "__main__":
    main()

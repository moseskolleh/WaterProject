"""District water-coverage gap: population per functional water point.

Ranks Sierra Leone's 16 districts by *unmet water need* - the resident
population divided by the number of functional mapped water points in the
district. The district a national programme actually allocates budget
across. It joins three bundled, verifiable inputs:

- **District population** - Statistics Sierra Leone, 2015 Population and
  Housing Census (``data/sl_population_district.csv``; the 16 districts sum
  to the official national total of 7,092,113).
- **A chiefdom -> current-district crosswalk**
  (``data/sl_chiefdom_district.csv``) so a water point is placed in a
  district via the bundled chiefdom polygons (point -> chiefdom ->
  district). This is needed because the bundled ADM2 boundaries predate the
  2017 creation of Karene and Falaba, while the census population is for the
  current 16 districts.
- **Water points** - from the Water Point Data Exchange (WPDx), passed in
  as already-parsed :class:`~groundwater.waterpoints.WaterPoint` records
  (a live national fetch or an uploaded CSV export).

Pure and matplotlib-free (only the choropleth in ``mapping.regional``
draws), so the join, the ranking and the division-by-zero handling are
fully unit-testable offline. A point that falls in the seam two
independently simplified chiefdom rings leave along one border is placed on
the chiefdom it is nearest to, within ``CHIEFDOM_EDGE_TOLERANCE_M``; a point
further out than that is returned as ``unassigned`` - counted and surfaced,
never silently dropped and never given the nearest name for want of a
better one.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Iterable

import numpy as np

from .waterpoints import WaterPoint

POPULATION_CREDIT = (
    "Population: Statistics Sierra Leone, 2015 Population and Housing Census"
)

#: How far outside every chiefdom a point may fall and still be placed on the
#: chiefdom whose ring it is nearest to, in metres.
#:
#: Each ring of the bundled layer was simplified on its own, so two rings that
#: were once one shared border no longer meet exactly, and the thin slivers
#: between them - about 37 km2 of ground nationally - are inside no chiefdom at
#: all (ROADMAP data-ingestion-7). A point in one of those seams is metres from
#: the border it belongs on, and which side of that border it fell on is below
#: the resolution of the layer, so it is resolved to the nearest ring. Nearly
#: every seam in the bundled layer is far narrower than this; the few places
#: that are wider are where three chiefdoms meet, and a point there is left
#: unplaced rather than given one of the three.
#:
#: The number is metres and not kilometres on purpose. Beyond it a point is not
#: on a border at all but in a real hole in the layer - the Maforki wedge
#: withheld pending review is 20 km2 of such ground - and there every lookup
#: answers with nothing rather than with the name of whatever lies nearest,
#: because an unplaced point is a flag on a report while a placed one is a
#: district on a document somebody signs.
CHIEFDOM_EDGE_TOLERANCE_M = 50.0

# Metres per degree of latitude, and per degree of longitude at the equator
# (shrunk by the cosine of the latitude where it is used). What they convert is
# a few tens of metres between a point and a ring it is all but touching, so
# the local flat-earth distance below is ample and a projection would be false
# precision.
_M_PER_DEG_LAT = 110_600.0
_M_PER_DEG_LON = 111_320.0


@dataclass
class ChiefdomPoly:
    """A chiefdom polygon and its parent (current) district, geometry only."""

    name: str
    rings: list[np.ndarray]
    # per-ring (min_lon, min_lat, max_lon, max_lat) bounding boxes for a fast
    # reject before the ray-casting test (national pulls have many points).
    bboxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    # interior rings per part, aligned with ``rings``. Nongowa encloses Kenema
    # Town; dropping its hole credited a city of 200,000 people's water points
    # to the rural chiefdom around it, and left the town looking unserved.
    holes: list[list[np.ndarray]] = field(default_factory=list)


def _resource_text(name: str, path: str | Path | None) -> str:
    if path is not None:
        return Path(path).read_text(encoding="utf-8")
    return (resources.files("groundwater") / "data" / name).read_text(
        encoding="utf-8"
    )


def _point_in_ring(lon: float, lat: float, ring: np.ndarray) -> bool:
    """Ray-casting point-in-polygon test (matches mapping.regional)."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:], strict=True):
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside



def _poly_contains(poly: "ChiefdomPoly", lon: float, lat: float) -> bool:
    """Point in a chiefdom, honouring enclaves cut out of it."""
    for i, (ring, (x0, y0, x1, y1)) in enumerate(
        zip(poly.rings, poly.bboxes, strict=True)
    ):
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        if not _point_in_ring(lon, lat, ring):
            continue
        inner = poly.holes[i] if i < len(poly.holes) else []
        if any(_point_in_ring(lon, lat, hole) for hole in inner):
            continue  # inside an enclave: it belongs to the chiefdom there
        return True
    return False


def _ring_distances_m(xy: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """Metres from each point of ``xy`` to the nearest segment of ``ring``.

    Distance to the ring as a line, not to its vertices: a simplified ring
    can run hundreds of metres between two vertices, and a point in the seam
    beside that stretch is metres from the border and far from either end of
    it.
    """
    lon = xy[:, 0][:, None]
    lat = xy[:, 1][:, None]
    x = (ring[None, :, 0] - lon) * _M_PER_DEG_LON * np.cos(np.radians(lat))
    y = (ring[None, :, 1] - lat) * _M_PER_DEG_LAT
    ax, ay = x[:, :-1], y[:, :-1]
    dx, dy = x[:, 1:] - ax, y[:, 1:] - ay
    length2 = dx * dx + dy * dy
    # where on each segment the perpendicular falls, clamped to its ends; a
    # segment of zero length (a vertex repeated by the simplification) would
    # divide by zero, and its own end point is the answer there.
    safe = np.where(length2 > 0.0, length2, 1.0)
    t = np.where(length2 > 0.0, np.clip(-(ax * dx + ay * dy) / safe, 0.0, 1.0), 0.0)
    px, py = ax + t * dx, ay + t * dy
    return np.sqrt(px * px + py * py).min(axis=1)


def nearest_chiefdom_index(
    lon: float,
    lat: float,
    ring_sets: Iterable[list[np.ndarray]],
    tolerance_m: float = CHIEFDOM_EDGE_TOLERANCE_M,
) -> int | None:
    """Which of the areas a point in none of them is nearest to, if any is near.

    ``ring_sets`` is each area's outer rings, in the layer's own order.
    Returns the index of the area whose ring is nearest, when that ring is
    closer than ``tolerance_m``, and ``None`` when nothing is that close -
    the point is then in no chiefdom and is left in none.

    Ties go to the earlier area, which is the rule the containment walk
    already follows. Interior rings are not candidates: a point in the seam
    between an enclave and the chiefdom around it (Kenema Town inside
    Nongowa) belongs to the enclave it is touching, not to the hole it fell
    in.

    ``mapping.regional`` resolves its own chiefdom lookups through this
    function, so the toolkit closes a seam at one distance rather than at
    two - the point of ROADMAP data-ingestion-7 is that the lookups used to
    answer the same point three different ways.
    """
    # the ring's bounding box grown by the tolerance: a point outside that box
    # is further than the tolerance from every point of the ring, so the
    # distance need not be computed at all. A national water-point pull asks
    # this of every point it could not place.
    d_lat = tolerance_m / _M_PER_DEG_LAT
    d_lon = tolerance_m / (_M_PER_DEG_LON * max(math.cos(math.radians(lat)), 1e-6))
    xy = np.array([[lon, lat]], dtype=float)
    best_index: int | None = None
    best_m = tolerance_m
    for index, rings in enumerate(ring_sets):
        for ring in rings:
            if len(ring) < 2:
                continue  # a replacement layer can carry a degenerate ring
            if (
                lon < ring[:, 0].min() - d_lon or lon > ring[:, 0].max() + d_lon
                or lat < ring[:, 1].min() - d_lat or lat > ring[:, 1].max() + d_lat
            ):
                continue
            metres = float(_ring_distances_m(xy, ring)[0])
            if metres < best_m:
                best_index, best_m = index, metres
    return best_index


def load_district_population(path: str | Path | None = None) -> dict[str, float]:
    """District -> resident population (2015 census)."""
    text = _resource_text("sl_population_district.csv", path)
    out: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(text)):
        out[row["district"].strip()] = float(row["population"])
    return out


def load_chiefdom_district(path: str | Path | None = None) -> dict[str, str]:
    """Chiefdom name -> current district (the reconciliation crosswalk)."""
    text = _resource_text("sl_chiefdom_district.csv", path)
    return {
        row["chiefdom"].strip(): row["district"].strip()
        for row in csv.DictReader(io.StringIO(text))
    }


def load_chiefdom_polys(path: str | Path | None = None) -> list[ChiefdomPoly]:
    """Chiefdom polygons from the bundled geoBoundaries layer."""
    data = json.loads(_resource_text("sl_chiefdoms_geoboundaries.geojson", path))
    polys: list[ChiefdomPoly] = []
    for feature in data.get("features", []):
        name = feature.get("properties", {}).get("name", "")
        geom = feature.get("geometry", {})
        parts = (
            geom["coordinates"]
            if geom.get("type") == "MultiPolygon"
            else [geom.get("coordinates", [])]
        )
        rings = [np.asarray(p[0], dtype=float) for p in parts if p]
        holes = [
            [np.asarray(r, dtype=float) for r in p[1:]] for p in parts if p
        ]
        if not rings:
            continue
        bboxes = [
            (r[:, 0].min(), r[:, 1].min(), r[:, 0].max(), r[:, 1].max())
            for r in rings
        ]
        polys.append(
            ChiefdomPoly(name=name, rings=rings, bboxes=bboxes, holes=holes)
        )
    return polys


def assign_chiefdoms(
    points: Iterable[WaterPoint], polys: list[ChiefdomPoly]
) -> list[str]:
    """Chiefdom name per point, "" for a point no chiefdom is near.

    The same answer as ``chiefdom_of_point`` for each point (first polygon
    in file order that contains it, enclaves honoured, then the nearest ring
    within :data:`CHIEFDOM_EDGE_TOLERANCE_M`), computed for all the points at
    once: a national pull is fifty thousand points, and the per-point ray
    cast took about ten seconds on every rerun of the coverage page. The
    bounding-box reject is kept per ring, and the points already placed drop
    out of the candidate set for the next ring.

    The seam pass is the per-point one, not a vectorised twin of it, because
    only the handful of points the containment pass could not place reach it
    and two implementations of one rule are two rules waiting to disagree.
    """
    from matplotlib.path import Path as MplPath

    points = list(points)
    names = [""] * len(points)
    if not points:
        return names
    xy = np.array([(wp.lon, wp.lat) for wp in points], dtype=float)
    pending = np.ones(len(points), dtype=bool)
    for poly in polys:
        for i, (ring, (x0, y0, x1, y1)) in enumerate(
            zip(poly.rings, poly.bboxes, strict=True)
        ):
            candidates = pending & (
                (xy[:, 0] >= x0) & (xy[:, 0] <= x1)
                & (xy[:, 1] >= y0) & (xy[:, 1] <= y1)
            )
            if not candidates.any():
                continue
            idx = np.flatnonzero(candidates)
            inside = MplPath(ring).contains_points(xy[idx])
            for hole in poly.holes[i] if i < len(poly.holes) else []:
                if inside.any():
                    inside &= ~MplPath(hole).contains_points(xy[idx])
            hit = idx[inside]
            for j in hit:
                names[j] = poly.name
            pending[hit] = False
        if not pending.any():
            break
    # Whatever is left is inside no chiefdom: either in a seam between two
    # simplified rings, which is a border and is placed on it, or genuinely
    # off the layer, which stays unplaced and is counted as unassigned.
    ring_sets = [poly.rings for poly in polys]
    for j in np.flatnonzero(pending):
        near = nearest_chiefdom_index(float(xy[j, 0]), float(xy[j, 1]), ring_sets)
        if near is not None:
            names[j] = polys[near].name
    return names


def counts_from_groups(
    grouped: dict[str, list[WaterPoint]]
) -> dict[str, dict[str, int]]:
    """Total and functional counts derived from grouped points.

    Grouping and counting are the same walk; doing both is doing it twice.
    """
    return {
        area: {
            "total": len(members),
            "functional": sum(1 for wp in members if wp.functional is True),
        }
        for area, members in grouped.items()
    }


def district_of_point(
    lat: float, lon: float, polys: list[ChiefdomPoly], chiefdom_district: dict[str, str]
) -> str:
    """District containing a point via point -> chiefdom -> district.

    The chiefdom is :func:`chiefdom_of_point`'s, seams included, so the two
    never disagree about where a point is; returns "" when no chiefdom is
    near enough to place it (offshore, across the border, a bad coordinate,
    or ground the layer does not carry at all).
    """
    chiefdom = chiefdom_of_point(lat, lon, polys)
    return chiefdom_district.get(chiefdom, "") if chiefdom else ""


def count_points_by_district(
    points: Iterable[WaterPoint],
    polys: list[ChiefdomPoly],
    chiefdom_district: dict[str, str],
) -> tuple[dict[str, dict[str, int]], list[WaterPoint]]:
    """Total and functional water-point counts per district.

    Returns ``({district: {"total": int, "functional": int}}, unassigned)``
    where ``unassigned`` holds points inside no chiefdom (never dropped).
    """
    grouped, unassigned = group_points_by_district(points, polys, chiefdom_district)
    return counts_from_groups(grouped), unassigned


def group_points_by_district(
    points: Iterable[WaterPoint],
    polys: list[ChiefdomPoly],
    chiefdom_district: dict[str, str],
) -> tuple[dict[str, list[WaterPoint]], list[WaterPoint]]:
    """The points themselves per district, not just how many there are.

    The counts are enough to divide a population by. They are not enough to
    say when the points were last surveyed or whether they last the dry
    season, which is what ``groundwater.planning`` needs, so the same walk
    keeps the records instead of tallying them away.
    """
    points = list(points)
    grouped: dict[str, list[WaterPoint]] = {}
    unassigned: list[WaterPoint] = []
    for wp, chiefdom in zip(points, assign_chiefdoms(points, polys), strict=True):
        district = chiefdom_district.get(chiefdom, "") if chiefdom else ""
        if not district:
            unassigned.append(wp)
            continue
        grouped.setdefault(district, []).append(wp)
    return grouped, unassigned


def group_points_by_chiefdom(
    points: Iterable[WaterPoint], polys: list[ChiefdomPoly]
) -> tuple[dict[str, list[WaterPoint]], list[WaterPoint]]:
    """The points themselves per chiefdom polygon."""
    points = list(points)
    grouped: dict[str, list[WaterPoint]] = {}
    unassigned: list[WaterPoint] = []
    for wp, chiefdom in zip(points, assign_chiefdoms(points, polys), strict=True):
        if not chiefdom:
            unassigned.append(wp)
            continue
        grouped.setdefault(chiefdom, []).append(wp)
    return grouped, unassigned


@dataclass
class CoverageRow:
    """One district's water-coverage picture."""

    district: str
    population: float
    water_points: int
    functional_points: int
    people_per_point: float | None  # None when there is no functional source
    rank: int = 0  # 1 = worst (highest unmet need)

    @property
    def name(self) -> str:
        return self.district

    @property
    def status(self) -> str:
        if self.functional_points == 0:
            return "No functional source mapped"
        return f"{self.people_per_point:,.0f} people per functional point"


def coverage_rows(
    population: dict[str, float], counts: dict[str, dict[str, int]]
) -> list[CoverageRow]:
    """Build one ranked :class:`CoverageRow` per district in ``population``.

    Ranking is worst-first: districts with no functional source mapped rank
    at the very top (unmet need is effectively infinite), then the rest by
    descending people-per-functional-point. Population breaks ties so a large
    district with no source outranks a small one.
    """
    rows: list[CoverageRow] = []
    for district, pop in population.items():
        bucket = counts.get(district, {"total": 0, "functional": 0})
        functional = bucket["functional"]
        ppp = (pop / functional) if functional > 0 else None
        rows.append(
            CoverageRow(
                district=district,
                population=pop,
                water_points=bucket["total"],
                functional_points=functional,
                people_per_point=ppp,
            )
        )
    rows.sort(
        key=lambda r: (
            1 if r.people_per_point is not None else 0,  # no-source first
            -(r.people_per_point or 0.0),
            -r.population,
        )
    )
    for rank, row in enumerate(rows, start=1):
        row.rank = rank
    return rows


@dataclass(frozen=True)
class ServiceClass:
    """One band of the people-per-functional-point scale."""

    kind: str  # "class" | "no_source" | "no_data"
    max_people_per_point: float | None  # None on the open-ended top class
    label: str
    basis: str
    colour: str


def load_service_classes(path: str | Path | None = None) -> list[ServiceClass]:
    """The fixed scale both engines colour the coverage map by.

    The map used to be coloured by a scale recomputed from whatever was on it:
    a continuous ramp stretched to each figure's own minimum and maximum in
    Python, five quantiles in the browser. A chiefdom at 900 people per
    functional point was therefore pale on a map whose worst area was 40,000
    and dark on one whose worst was 1,200 - same chiefdom, same data, opposite
    reading - and the two engines drew the same country two different ways.
    Nothing on either key said what a colour meant in absolute terms, so there
    was no way to tell which was right.

    A fixed scale is comparable by construction. Where the breaks fall is a
    judgement whichever way it is made, so the table says what each one rests
    on rather than leaving it to be inferred from the colours. The two lowest
    are the Sphere handbook's figures for a tapstand and a handpump; no copy
    of that standard is committed here, so the table marks them as not
    evidenced in this repository and they should be read as a stated basis
    rather than as a standard this project holds.
    """
    rows = csv.DictReader(io.StringIO(
        _resource_text("coverage_service_classes.csv", path)))
    out = []
    for row in rows:
        top = (row.get("max_people_per_point") or "").strip()
        out.append(ServiceClass(
            kind=(row.get("kind") or "class").strip(),
            max_people_per_point=float(top) if top else None,
            label=(row.get("label") or "").strip(),
            basis=(row.get("basis") or "").strip(),
            colour=(row.get("colour") or "").strip(),
        ))
    return out


def service_class_of(
    value: float | None, classes: list[ServiceClass] | None = None
) -> ServiceClass:
    """Which band a people-per-point figure falls in.

    Follows the convention :func:`choropleth_values` already uses: ``None``
    is an area nothing is known about, and infinity is an area with no
    functional mapped source at all. Those are opposite situations and the
    browser painted both the same grey, so the areas most in need - the ones
    that rank first by definition - were indistinguishable from the areas
    nobody has a figure for.
    """
    table = classes if classes is not None else load_service_classes()
    bands = [c for c in table if c.kind == "class"]
    if value is None:
        return next((c for c in table if c.kind == "no_data"), bands[-1])
    if not math.isfinite(value):
        return next((c for c in table if c.kind == "no_source"), bands[-1])
    for band in bands:
        if band.max_people_per_point is not None and value < band.max_people_per_point:
            return band
    return bands[-1]


def choropleth_values(rows: Iterable[CoverageRow]) -> dict[str, float]:
    """District -> people-per-point for the map.

    Districts with no functional source map to ``inf`` so the renderer can
    show them as a distinct "no source" class rather than a colour.
    """
    return {
        row.name: (row.people_per_point
                   if row.people_per_point is not None else math.inf)
        for row in rows
    }


def expand_district_values(
    district_values: dict[str, float], chiefdom_district: dict[str, str]
) -> dict[str, float]:
    """Spread district values onto every chiefdom, for the district choropleth."""
    return {
        chiefdom: district_values.get(district)
        for chiefdom, district in chiefdom_district.items()
    }


# --- chiefdom-level coverage -----------------------------------------------

@dataclass
class ChiefdomRow:
    """One chiefdom's water-coverage picture (finer than the district view)."""

    chiefdom: str
    district: str
    population: float
    water_points: int
    functional_points: int
    people_per_point: float | None
    rank: int = 0

    @property
    def name(self) -> str:
        return self.chiefdom

    @property
    def status(self) -> str:
        if self.functional_points == 0:
            return "No functional source mapped"
        return f"{self.people_per_point:,.0f} people per functional point"


def load_census_crosswalk(
    path: str | Path | None = None,
) -> dict[tuple[str, str], str]:
    """(district, census chiefdom) -> geoBoundaries chiefdom polygon."""
    text = _resource_text("sl_census_crosswalk.csv", path)
    # strip like the sibling loaders: the crosswalk is user-editable, so a
    # stray space in a hand edit must not break the (district, chiefdom) join.
    return {
        (row["district"].strip(), row["census_chiefdom"].strip()):
            row["gb_chiefdom"].strip()
        for row in csv.DictReader(io.StringIO(text))
    }


def chiefdom_population(
    census_path: str | Path | None = None,
    crosswalk_path: str | Path | None = None,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Population per chiefdom polygon, aggregated from the census.

    Returns ``(population, members)`` where ``population`` maps each
    geoBoundaries chiefdom polygon to the sum of the 2015 census chiefdoms
    assigned to it, and ``members`` lists those census chiefdoms (for the
    reconciliation panel - it shows how post-2017 chiefdoms fold into the
    pre-2017 polygons). District totals are conserved exactly by construction.
    """
    census_text = _resource_text("sl_population_chiefdom.csv", census_path)
    crosswalk = load_census_crosswalk(crosswalk_path)
    population: dict[str, float] = {}
    members: dict[str, list[str]] = {}
    missing: list[tuple[str, str]] = []
    for row in csv.DictReader(io.StringIO(census_text)):
        key = (row["district"].strip(), row["chiefdom"].strip())
        gb = crosswalk.get(key)
        if gb is None:  # a hand-edited crosswalk dropped or renamed this row
            missing.append(key)
            continue
        population[gb] = population.get(gb, 0.0) + float(row["population"])
        members.setdefault(gb, []).append(row["chiefdom"].strip())
    if missing:
        raise KeyError(
            f"{len(missing)} census chiefdom(s) have no crosswalk row, e.g. "
            f"{missing[0]}; check data/sl_census_crosswalk.csv"
        )
    return population, members


def chiefdom_of_point(
    lat: float, lon: float, polys: list[ChiefdomPoly]
) -> str:
    """Chiefdom polygon holding a point, or "" when no chiefdom is near it.

    A point no polygon contains is placed on the chiefdom whose ring is
    nearest, when that ring is within :data:`CHIEFDOM_EDGE_TOLERANCE_M` -
    the seams the independently simplified rings leave along their shared
    borders are that wide, and a point in one is on the border rather than
    outside the country. Further out than that it stays unplaced.
    """
    for poly in polys:
        if _poly_contains(poly, lon, lat):
            return poly.name
    near = nearest_chiefdom_index(lon, lat, (poly.rings for poly in polys))
    return polys[near].name if near is not None else ""


def count_points_by_chiefdom(
    points: Iterable[WaterPoint], polys: list[ChiefdomPoly]
) -> tuple[dict[str, dict[str, int]], list[WaterPoint]]:
    """Total and functional water-point counts per chiefdom polygon."""
    grouped, unassigned = group_points_by_chiefdom(points, polys)
    return counts_from_groups(grouped), unassigned


def chiefdom_coverage_rows(
    population: dict[str, float],
    counts: dict[str, dict[str, int]],
    chiefdom_district: dict[str, str],
) -> list[ChiefdomRow]:
    """Ranked :class:`ChiefdomRow` per chiefdom, worst (highest need) first."""
    rows: list[ChiefdomRow] = []
    for chiefdom, pop in population.items():
        bucket = counts.get(chiefdom, {"total": 0, "functional": 0})
        functional = bucket["functional"]
        ppp = (pop / functional) if functional > 0 else None
        rows.append(
            ChiefdomRow(
                chiefdom=chiefdom,
                district=chiefdom_district.get(chiefdom, ""),
                population=pop,
                water_points=bucket["total"],
                functional_points=functional,
                people_per_point=ppp,
            )
        )
    rows.sort(
        key=lambda r: (
            1 if r.people_per_point is not None else 0,
            -(r.people_per_point or 0.0),
            -r.population,
        )
    )
    for rank, row in enumerate(rows, start=1):
        row.rank = rank
    return rows


def coverage_stats(rows) -> dict:
    """Headline figures for the KPI tiles (works for district or chiefdom rows).

    ``worst_served_*`` is the highest *finite* people-per-point, i.e. the worst
    measurable coverage; it is reported separately from the ranking because
    areas with no functional source (an undefined ratio) sort to rank 1 and are
    counted by ``n_no_source`` instead.
    """
    served = [r for r in rows if r.people_per_point is not None]
    worst_served = max(served, key=lambda r: r.people_per_point, default=None)
    total_pop = sum(r.population for r in rows)
    total_functional = sum(r.functional_points for r in rows)
    return {
        "n_areas": len(rows),
        "worst_area": rows[0].name if rows else None,
        "worst_people_per_point": rows[0].people_per_point if rows else None,
        "worst_served_area": worst_served.name if worst_served else None,
        "worst_served_people_per_point": (
            worst_served.people_per_point if worst_served else None
        ),
        "n_no_source": sum(1 for r in rows if r.functional_points == 0),
        "national_people_per_point": (total_pop / total_functional)
        if total_functional else None,
    }

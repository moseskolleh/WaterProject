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
fully unit-testable offline. Border points that fall outside every chiefdom
are returned as ``unassigned`` - counted and surfaced, never silently
dropped.
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


@dataclass
class ChiefdomPoly:
    """A chiefdom polygon and its parent (current) district, geometry only."""

    name: str
    rings: list[np.ndarray]
    # per-ring (min_lon, min_lat, max_lon, max_lat) bounding boxes for a fast
    # reject before the ray-casting test (national pulls have many points).
    bboxes: list[tuple[float, float, float, float]] = field(default_factory=list)


def _resource_text(name: str, path: str | Path | None) -> str:
    if path is not None:
        return Path(path).read_text(encoding="utf-8")
    return (resources.files("groundwater") / "data" / name).read_text(
        encoding="utf-8"
    )


def _point_in_ring(lon: float, lat: float, ring: np.ndarray) -> bool:
    """Ray-casting point-in-polygon test (matches mapping.regional)."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside


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
        if not rings:
            continue
        bboxes = [
            (r[:, 0].min(), r[:, 1].min(), r[:, 0].max(), r[:, 1].max())
            for r in rings
        ]
        polys.append(ChiefdomPoly(name=name, rings=rings, bboxes=bboxes))
    return polys


def district_of_point(
    lat: float, lon: float, polys: list[ChiefdomPoly], chiefdom_district: dict[str, str]
) -> str:
    """District containing a point via point -> chiefdom -> district.

    Returns "" when the point falls outside every chiefdom (border, offshore,
    or a bad coordinate).
    """
    for poly in polys:
        for ring, (x0, y0, x1, y1) in zip(poly.rings, poly.bboxes):
            if x0 <= lon <= x1 and y0 <= lat <= y1 and _point_in_ring(lon, lat, ring):
                return chiefdom_district.get(poly.name, "")
    return ""


def count_points_by_district(
    points: Iterable[WaterPoint],
    polys: list[ChiefdomPoly],
    chiefdom_district: dict[str, str],
) -> tuple[dict[str, dict[str, int]], list[WaterPoint]]:
    """Total and functional water-point counts per district.

    Returns ``({district: {"total": int, "functional": int}}, unassigned)``
    where ``unassigned`` holds points inside no chiefdom (never dropped).
    """
    counts: dict[str, dict[str, int]] = {}
    unassigned: list[WaterPoint] = []
    for wp in points:
        district = district_of_point(wp.lat, wp.lon, polys, chiefdom_district)
        if not district:
            unassigned.append(wp)
            continue
        bucket = counts.setdefault(district, {"total": 0, "functional": 0})
        bucket["total"] += 1
        if wp.functional is True:
            bucket["functional"] += 1
    return counts, unassigned


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
    """Chiefdom polygon containing a point, or "" when outside every chiefdom."""
    for poly in polys:
        for ring, (x0, y0, x1, y1) in zip(poly.rings, poly.bboxes):
            if x0 <= lon <= x1 and y0 <= lat <= y1 and _point_in_ring(lon, lat, ring):
                return poly.name
    return ""


def count_points_by_chiefdom(
    points: Iterable[WaterPoint], polys: list[ChiefdomPoly]
) -> tuple[dict[str, dict[str, int]], list[WaterPoint]]:
    """Total and functional water-point counts per chiefdom polygon."""
    counts: dict[str, dict[str, int]] = {}
    unassigned: list[WaterPoint] = []
    for wp in points:
        chiefdom = chiefdom_of_point(wp.lat, wp.lon, polys)
        if not chiefdom:
            unassigned.append(wp)
            continue
        bucket = counts.setdefault(chiefdom, {"total": 0, "functional": 0})
        bucket["total"] += 1
        if wp.functional is True:
            bucket["functional"] += 1
    return counts, unassigned


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

"""A survey plan from the lineament candidates (PLAN.md step 4.3).

The desk study ends with a plan for the day in the field: where the crew
lays its profiling lines and where it sounds. In basement terrain a borehole
finds water where it meets a fracture zone, and a lineament candidate
(:mod:`.lineaments`) is where one may show on the surface. So the plan
crosses the candidates nearest the site at right angles, inside the ground
the site serves, and proposes a sounding where each line crosses its
candidate and one to either side.

The rules, in the order :func:`survey_plan` applies them:

* The plan is laid within the service radius of the site,
  :data:`groundwater.waterpoints.SERVICE_RADIUS_M`, the distance within
  which the water point check counts an existing source as serving the
  community: a borehole further out does not serve it.
* The candidates that come within the radius are taken nearest first, by
  the distance from the site to the nearest point of each, the longer first
  where two are as near. Each is crossed by a line at right angles to its
  strike through its point nearest the site, which, unless the candidate
  ends short of it, makes a line through the site itself. A line is
  ``survey_line_m`` long with a station every ``survey_station_m``, the
  crossing a station of it and as near its middle as the service radius
  allows; where the radius leaves less room, the line is shortened to it.
  A candidate that a line already laid crosses at right angles (their
  strikes within ``survey_cross_within_deg``) gets no line of its own, and
  no more than ``survey_lines`` lines are laid.
* Each line gets three soundings: on its candidate, and ``survey_flank_m``
  to either side along the line, because a candidate is placed from the
  terrain only to within a cell or two and the smoothing.
* A proposed sounding is a place a borehole may be drilled, so it is kept
  the separation distances of ``data/site_separation_distances.csv`` from
  what the page maps: a water point by what it is (a borehole, a dug well,
  any other water point as another well, and surface water as a stream),
  the drainage lines, which stand for the streams, and the sea. A sounding
  inside a ring is moved along its line to the nearest place clear of every
  ring, no further than ``survey_move_m``; where there is none, it is left
  out, and the plan says why. The table's other rows (latrines and
  soakaways, buildings, refuse dumps and burial grounds) are on no map
  here, and the plan says to check each peg for them on the ground.
* A water point's ring can reach a sounding from as far as the service
  radius and its separation distance (550 m for a borehole), so water
  points looked up within less than that round the site leave the plan
  blind beyond the lookup: ``searched_m`` says how far they were looked
  up, and where it is short the plan says so and tells the operator to
  look them up again, rather than saying nothing of the water points it
  could not see.
* Each sounding's AB/2 series is the VES co-pilot's own,
  :func:`groundwater.field_kit.ves_survey_plan`, for a target of
  ``survey_target_depth_m`` by the depth-of-investigation rule, its spread
  laid along its candidate's strike so that it reads the zone along its
  length rather than across it.
* Where no candidate comes within the radius, or none leaves room for a
  station, one line runs through the site across the strike of the
  10-degree band that holds the greatest length of candidates in the square
  shown, and no sounding is proposed: each goes where the profile finds a
  zone. Where the square shown holds no candidate, no line is laid.

Everything is worked out in the candidates' own frame, metres east and
north of the analysed window's first cell (:mod:`.lineaments`), with the
site and the water points placed in it between the cell centres as
:func:`.lineaments.lineament_lonlat` places a point back. Every decision is
taken with additions, multiplications, divisions, square roots, floors and
ceilings in a fixed order and the polynomial sine and cosine of
:func:`.elevation.sin_cos_deg`, so that the browser's engine in
``docs/js/gwt-core.js``, which runs the same steps in the same order, lays
the same plan to the bit.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from ..config import TerrainConfig, VESConfig
from ..text import phrase
from ..utils import and_join
from .elevation import sin_cos_deg
from .lineaments import ROSE_BANDS, LineamentAnalysis, lineament_lonlat
from .terrain_analysis import SEA, DrainagePart, TerrainCore, _json_text

__all__ = [
    "BOREHOLE",
    "COAST",
    "DUG_WELL",
    "OTHER_WELL",
    "STREAM",
    "DroppedSounding",
    "SurveyLine",
    "SurveyPlan",
    "SurveySounding",
    "line_station",
    "survey_plan",
    "survey_plan_captions",
    "survey_plan_geojson",
    "survey_plan_gpx",
    "survey_sounding_text",
    "water_point_kind",
    "water_point_reach",
]

#: The rows of the separation table the plan maps, by the structure each
#: names in ``data/site_separation_distances.csv``.
BOREHOLE = "Water supply borehole"
DUG_WELL = "Hand dug well"
OTHER_WELL = "Other existing water wells"
STREAM = "Streams and canals and irrigation ditches"
COAST = "Coastline"
_MAPPED = (BOREHOLE, DUG_WELL, OTHER_WELL, STREAM, COAST)

#: What a water point is, by its source and technology, and the row of the
#: table that keeps a sounding from it. Surface water is kept as far as a
#: stream; a spring, a tap or a tank as far as another well, the table's
#: shortest distance from a water point.
_KIND_STRUCTURE = {"borehole": BOREHOLE, "dug_well": DUG_WELL, "other": OTHER_WELL, "surface": STREAM}

#: What a sounding was moved clear of, in the catalogue's words.
_CLEARED = {
    BOREHOLE: "survey_plan.cleared_borehole",
    DUG_WELL: "survey_plan.cleared_dug_well",
    OTHER_WELL: "survey_plan.cleared_other",
    STREAM: "survey_plan.cleared_stream",
    COAST: "survey_plan.cleared_coast",
}

#: Vertices of the service radius's ring and of each water point's
#: separation ring, as :func:`.geolibre.separation_ring_features` draws its
#: own.
_RING_SEGMENTS = 64

#: Why a sounding is left out when the line ends before it.
OFF_LINE = "off_line"


@dataclass(frozen=True)
class SurveyLine:
    """One profiling line.

    ``origin`` is where it crosses its candidate, or the site for a line
    across the strike (``candidate`` None), in the candidates' frame;
    ``direction`` is the unit vector it runs along, east and north, at
    ``bearing_deg`` clockwise from grid north, from 0 to under 180. Station
    ``k``, from ``first`` to ``last``, lies ``k * station_m`` from the
    origin along it (:func:`line_station`), so the origin is station 0 and
    lies ``crossing_m`` from the line's start. ``strike_deg`` is the
    strike it crosses. ``crosses`` holds the other candidates it crosses at
    right angles, each with the distance from the start where it does;
    ``shortened`` says the service radius left less than ``survey_line_m``.
    """

    id: int
    candidate: int | None
    kind: str | None
    strike_deg: float
    bearing_deg: float
    origin: tuple[float, float]
    direction: tuple[float, float]
    first: int
    last: int
    station_m: float
    length_m: float
    crossing_m: float
    crosses: tuple[tuple[int, float], ...]
    shortened: bool


@dataclass(frozen=True)
class SurveySounding:
    """One proposed sounding: VES ``id``, on line ``line`` at ``at_m`` from
    its start, at ``point`` in the candidates' frame. ``role`` is
    ``"crossing"`` (on the candidate) or ``"flank"``; ``moved_m`` is how far
    it was moved along the line, towards the line's end where positive, to
    clear the rings of ``cleared``; ``spread_deg`` is the strike its spread
    is laid along."""

    id: int
    line: int
    role: str
    at_m: float
    point: tuple[float, float]
    moved_m: float
    cleared: tuple[str, ...]
    spread_deg: float


@dataclass(frozen=True)
class DroppedSounding:
    """A sounding left out: the ``role`` it had on ``line``, where it would
    have been (``at_m``, from the line's start), and why: the structures
    whose rings it could not be moved clear of, or ``off_line``, the line
    ending before it."""

    line: int
    role: str
    at_m: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, eq=False)
class SurveyPlan:
    """The plan for one site.

    ``site`` is the site in the candidates' frame and ``site_lonlat`` as it
    was given; ``radius_m`` the service radius. ``basis`` is
    ``"candidates"``, ``"strike"`` or ``"none"``, what the lines rest on.
    ``near`` holds the candidates within the radius, nearest first, and
    ``skipped`` each one given no line, with the line that crosses it, or 0
    where the radius left no room for a station. ``reach`` counts what each
    ring could be drawn from within reach of the radius: water points by
    kind, drainage segments (``streams``) and coastal sea cells (``sea``);
    ``rings`` holds the water points among them, ``(x, y, structure,
    distance)``, and ``water_points`` how many were given. ``distances``
    are the table's distances for the rows mapped and ``unmapped`` the rows
    no map here records, ``(structure, distance)``, in the table's order.
    ``ab2`` is :func:`~groundwater.field_kit.ves_survey_plan` for the
    target; ``covered`` says the square shown holds the whole radius.
    ``searched_m`` is how far round the site the water points given were
    looked up, or None where they were not cut to a circle round it.
    """

    site: tuple[float, float]
    site_lonlat: tuple[float, float]
    radius_m: float
    basis: str
    lines: tuple[SurveyLine, ...]
    soundings: tuple[SurveySounding, ...]
    dropped: tuple[DroppedSounding, ...]
    near: tuple[int, ...]
    skipped: tuple[tuple[int, int], ...]
    reach: dict
    rings: tuple[tuple[float, float, str, float], ...]
    water_points: int
    distances: dict
    unmapped: tuple[tuple[str, float], ...]
    ab2: dict = field(repr=False)
    covered: bool = True
    frame: tuple[float, float] = (1.0, 1.0)
    settings: TerrainConfig = field(default_factory=TerrainConfig, repr=False)
    searched_m: float | None = None


def water_point_kind(point) -> str:
    """What a water point is, for its separation distance: ``borehole``,
    ``dug_well``, ``surface`` or ``other``, read from its source and
    technology (a WPDx ``water_source_clean`` of "Borehole/Tubewell" or
    "Protected Shallow Well", say). A borehole is told first, so a tubewell
    is not taken for a dug well."""
    text = f"{point.source} {point.technology}".lower()
    if "borehole" in text or "tubewell" in text or "tube well" in text:
        return "borehole"
    if "well" in text:
        return "dug_well"
    if "surface" in text or "river" in text or "stream" in text or "lake" in text or "pond" in text:
        return "surface"
    return "other"


def _positive(name: str, value) -> float:
    value = float(value)
    if not (math.isfinite(value) and value > 0.0):
        raise ValueError(f"terrain.{name} must be a number above 0")
    return value


def _plan_settings(cfg: TerrainConfig) -> dict:
    """The plan's settings, each refused unless it is a finite number in its
    range, in the order both engines check them."""
    lines = float(cfg.survey_lines)
    if not (math.isfinite(lines) and lines == math.floor(lines) and lines >= 1.0):
        raise ValueError("terrain.survey_lines must be a whole number of 1 or more")
    out: dict[str, float] = {"survey_lines": int(lines)}
    for name in ("survey_line_m", "survey_station_m", "survey_flank_m", "survey_target_depth_m"):
        out[name] = _positive(name, getattr(cfg, name))
    move = float(cfg.survey_move_m)
    if not (math.isfinite(move) and move >= 0.0 and move < out["survey_flank_m"] / 2.0):
        raise ValueError("terrain.survey_move_m must be 0 or more and under half of terrain.survey_flank_m")
    out["survey_move_m"] = move
    within = float(cfg.survey_cross_within_deg)
    if not (math.isfinite(within) and within >= 0.0 and within < 90.0):
        raise ValueError("terrain.survey_cross_within_deg must be 0 or more and under 90 degrees")
    out["survey_cross_within_deg"] = within
    if out["survey_station_m"] > out["survey_line_m"]:
        raise ValueError("terrain.survey_station_m must be no longer than terrain.survey_line_m")
    return out


def _axis_place(axis, value: float) -> float:
    """Where ``value`` lies along the cell centres ``axis``, as a fractional
    index: the inverse of how :func:`.lineaments.lineament_lonlat` reads a
    point between two centres (or beyond the last two, at the edge)."""
    first = float(axis[0])
    i = math.floor((value - first) / (float(axis[1]) - first))
    i = min(max(i, 0), len(axis) - 2)
    lo = float(axis[i])
    return i + (value - lo) / (float(axis[i + 1]) - lo)


def _to_frame(lons, lats, frame: tuple[float, float], lon: float, lat: float) -> tuple[float, float]:
    return _axis_place(lons, float(lon)) * frame[0], _axis_place(lats, float(lat)) * frame[1]


def _distance(ax: float, ay: float, bx: float, by: float) -> float:
    ex = ax - bx
    ey = ay - by
    return math.sqrt(ex * ex + ey * ey)


def _nearest_on(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float, float]:
    """The distance from ``(px, py)`` to the segment ``a``-``b``, and the
    segment's point nearest it."""
    ex = b[0] - a[0]
    ey = b[1] - a[1]
    span = ex * ex + ey * ey
    t = ((px - a[0]) * ex + (py - a[1]) * ey) / span if span > 0.0 else 0.0
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    cx = a[0] + t * ex
    cy = a[1] + t * ey
    return _distance(px, py, cx, cy), cx, cy


# --- where along a line a ring lies: open intervals of the distance t along
# it from its origin, the points nearer the structure than its distance


def _disc_span(ox, oy, nx, ny, qx, qy, d):
    wx = ox - qx
    wy = oy - qy
    b = wx * nx + wy * ny
    c = (wx * wx + wy * wy) - d * d
    disc = b * b - c
    if not disc > 0.0:
        return None
    root = math.sqrt(disc)
    return -b - root, -b + root


def _between(v0: float, v1: float, lo: float, hi: float):
    """The t with ``lo < v0 + t * v1 < hi``."""
    if v1 == 0.0:
        return (-math.inf, math.inf) if lo < v0 < hi else None
    ta = (lo - v0) / v1
    tb = (hi - v0) / v1
    if ta > tb:
        ta, tb = tb, ta
    return (ta, tb) if ta < tb else None


def _capsule_span(ox, oy, nx, ny, ax, ay, bx, by, d):
    """The points of the line nearer than ``d`` to the segment ``a``-``b``:
    the ground nearer than ``d`` to a segment is the strip beside it and a
    disc at each end, all convex together, so the span is from the first
    start of the three to the last end."""
    spans = [s for s in (_disc_span(ox, oy, nx, ny, ax, ay, d), _disc_span(ox, oy, nx, ny, bx, by, d))
             if s is not None]
    ex = bx - ax
    ey = by - ay
    length = math.sqrt(ex * ex + ey * ey)
    if length > 0.0:
        ux = ex / length
        uy = ey / length
        px = ox - ax
        py = oy - ay
        along = _between(px * ux + py * uy, nx * ux + ny * uy, 0.0, length)
        across = _between(px * uy - py * ux, nx * uy - ny * ux, -d, d)
        if along is not None and across is not None:
            lo = along[0] if along[0] > across[0] else across[0]
            hi = along[1] if along[1] < across[1] else across[1]
            if lo < hi:
                spans.append((lo, hi))
    if not spans:
        return None
    lo, hi = spans[0]
    for s in spans[1:]:
        if s[0] < lo:
            lo = s[0]
        if s[1] > hi:
            hi = s[1]
    return lo, hi


def _zone_span(zone: tuple, ox: float, oy: float, nx: float, ny: float):
    if zone[0] == "disc":
        return _disc_span(ox, oy, nx, ny, zone[2], zone[3], zone[4])
    return _capsule_span(ox, oy, nx, ny, zone[2], zone[3], zone[4], zone[5], zone[6])


def _merged(spans: list[tuple[float, float, str]]) -> list[list[float]]:
    out: list[list[float]] = []
    for lo, hi, _ in sorted(spans, key=lambda s: (s[0], s[1])):
        if out and lo < out[-1][1]:
            if hi > out[-1][1]:
                out[-1][1] = hi
        else:
            out.append([lo, hi])
    return out


def _structures(spans) -> tuple[str, ...]:
    return tuple(name for name in _MAPPED if any(s[2] == name for s in spans))


def _crossing(p0, p1, a, b) -> float | None:
    """Where along ``p0``-``p1``, as a share of it, the segment ``a``-``b``
    crosses it, or None."""
    rx = p1[0] - p0[0]
    ry = p1[1] - p0[1]
    qx = b[0] - a[0]
    qy = b[1] - a[1]
    den = rx * qy - ry * qx
    if den == 0.0:
        return None
    wx = a[0] - p0[0]
    wy = a[1] - p0[1]
    t = (wx * qy - wy * qx) / den
    u = (wx * ry - wy * rx) / den
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t
    return None


def line_station(line: SurveyLine, k: int) -> tuple[float, float]:
    """Station ``k`` of a line, in the candidates' frame."""
    along = k * line.station_m
    return line.origin[0] + along * line.direction[0], line.origin[1] + along * line.direction[1]


def _lay(number: int, item, origin: tuple[float, float], strike: float, site: tuple[float, float],
         radius: float, s: dict, lineaments: LineamentAnalysis) -> SurveyLine | None:
    """A line at right angles to ``strike`` through ``origin``, with its
    stations inside the service radius, or None where the radius leaves no
    room for two."""
    station = s["survey_station_m"]
    bearing = strike + 90.0 if strike < 90.0 else strike - 90.0
    nx, ny = sin_cos_deg(bearing)
    wx = origin[0] - site[0]
    wy = origin[1] - site[1]
    b = wx * nx + wy * ny
    c = (wx * wx + wy * wy) - radius * radius
    disc = b * b - c
    root = math.sqrt(disc) if disc > 0.0 else 0.0
    k1 = math.ceil((-b - root) / station)
    k2 = math.floor((-b + root) / station)
    wanted = math.floor(s["survey_line_m"] / station)
    m = min(wanted, k2 - k1)
    if m < 1:
        return None
    first = -(m // 2)
    if first < k1:
        first = k1
    if first + m > k2:
        first = k2 - m
    last = first + m
    length = m * station
    line = SurveyLine(number, None if item is None else item.id, None if item is None else item.kind, strike,
                      bearing, origin, (nx, ny), first, last, station, length, (0 - first) * station, (), m < wanted)
    start = line_station(line, first)
    end = line_station(line, last)
    crosses = []
    for other in lineaments.lineaments:
        if item is not None and other.id == item.id:
            continue
        turn = abs(other.strike_deg - strike)
        if 180.0 - turn < turn:
            turn = 180.0 - turn
        if turn > s["survey_cross_within_deg"]:
            continue
        t = _crossing(start, end, other.start, other.end)
        if t is not None:
            crosses.append((other.id, t * length))
    return replace(line, crosses=tuple(crosses))


def _soundings(line: SurveyLine, zones: list[tuple], s: dict) -> tuple[list[tuple], list[DroppedSounding]]:
    """The three soundings of a line across a candidate, each moved clear of
    the rings or left out: ``(role, t, moved, cleared)`` with ``t`` along
    the line from its origin."""
    flank = s["survey_flank_m"]
    move = s["survey_move_m"]
    ox, oy = line.origin
    nx, ny = line.direction
    t_start = line.first * line.station_m
    t_end = line.last * line.station_m
    spans = []
    for zone in zones:
        span = _zone_span(zone, ox, oy, nx, ny)
        if span is not None:
            spans.append((span[0], span[1], zone[1]))
    merged = _merged(spans)
    kept: list[tuple] = []
    dropped: list[DroppedSounding] = []
    for role, t0 in (("flank", 0.0 - flank), ("crossing", 0.0), ("flank", flank)):
        if t0 < t_start or t0 > t_end:
            dropped.append(DroppedSounding(line.id, role, t0 - t_start, (OFF_LINE,)))
            continue
        inside = [span for span in spans if span[0] < t0 < span[1]]
        t = t0
        if inside:
            lo, hi = next((a, b) for a, b in merged if a < t0 < b)
            options = []
            if lo >= t0 - move and lo >= t_start:
                options.append(lo)
            if hi <= t0 + move and hi <= t_end:
                options.append(hi)
            if not options:
                dropped.append(DroppedSounding(line.id, role, t0 - t_start, _structures(inside)))
                continue
            t = options[0] if len(options) == 1 or t0 - options[0] <= options[1] - t0 else options[1]
        kept.append((role, t, t - t0, _structures(inside)))
    return kept, dropped


def survey_plan(lineaments: LineamentAnalysis, core: TerrainCore, parts: Sequence[DrainagePart],
                site: tuple[float, float], water_points: Iterable = (), cfg: TerrainConfig | None = None,
                ves: VESConfig | None = None, distances: Iterable | None = None,
                searched_m: float | None = None) -> SurveyPlan:
    """The survey plan round ``site``, ``(lon, lat)``, from the lineament
    candidates of an analysed window (the module says how it is laid out).

    ``core`` and ``parts`` are the analysis's: the sea of its classes and
    the drainage lines shown. ``water_points`` are
    :class:`~groundwater.waterpoints.WaterPoint` (or anything with ``lat``,
    ``lon``, ``source`` and ``technology``). ``cfg`` is the terrain
    settings, the candidates' own by default; ``ves`` the VES settings the
    AB/2 series is planned by; ``distances`` the separation table, the
    bundled one by default. ``searched_m`` is how far round the site the
    water points were looked up: a lookup's radius, less how far the site
    lies from where it was centred; None where they are not cut to a
    circle round the site (an export read whole, the national set).
    Settings out of range are refused with a ValueError, in the words the
    browser uses.
    """
    from ..field_kit import ves_survey_plan
    from ..supervision.checklists import load_separation_distances
    from ..waterpoints import SERVICE_RADIUS_M

    cfg = cfg or lineaments.settings
    s = _plan_settings(cfg)
    if searched_m is not None:
        searched_m = float(searched_m)
        if not (math.isfinite(searched_m) and searched_m >= 0.0):
            raise ValueError("the radius the water points were looked up within must be 0 m or more")
    if distances is None:
        distances = load_separation_distances()
    rows = list(distances)
    table: dict[str, float] = {}
    for row in rows:
        table[row.structure] = float(row.min_distance_m)
    radius = float(SERVICE_RADIUS_M)
    frame = (float(lineaments.frame[0]), float(lineaments.frame[1]))
    dx, dy = frame
    lons, lats = core.lons, core.lats
    sx, sy = _to_frame(lons, lats, frame, site[0], site[1])

    # what each ring is drawn from, within reach of the radius
    zones: list[tuple] = []
    reach = {"borehole": 0, "dug_well": 0, "other": 0, "surface": 0, "streams": 0, "sea": 0}
    rings: list[tuple[float, float, str, float]] = []
    given = 0
    for point in water_points:
        given += 1
        kind = water_point_kind(point)
        structure = _KIND_STRUCTURE[kind]
        if structure not in table:
            continue
        d = table[structure]
        qx, qy = _to_frame(lons, lats, frame, point.lon, point.lat)
        if _distance(qx, qy, sx, sy) > radius + d:
            continue
        zones.append(("disc", structure, qx, qy, d))
        rings.append((qx, qy, structure, d))
        reach[kind] += 1
    if STREAM in table:
        d = table[STREAM]
        for part in parts:
            vertices = part.vertices
            for v in range(len(vertices) - 1):
                a = (vertices[v][1] * dx, vertices[v][0] * dy)
                b = (vertices[v + 1][1] * dx, vertices[v + 1][0] * dy)
                if _nearest_on(sx, sy, a, b)[0] > radius + d:
                    continue
                zones.append(("capsule", STREAM, a[0], a[1], b[0], b[1], d))
                reach["streams"] += 1
    if COAST in table:
        # the sea nearest any point inland is a sea cell beside one that is
        # not sea, or at the edge of the window, so only those are read
        d = table[COAST]
        cls = core.cls
        n_rows, n_cols = core.rows, core.cols
        r_lo = max(0, math.floor((sy - (radius + d)) / dy))
        r_hi = min(n_rows - 1, math.ceil((sy + (radius + d)) / dy))
        c_lo = max(0, math.floor((sx - (radius + d)) / dx))
        c_hi = min(n_cols - 1, math.ceil((sx + (radius + d)) / dx))
        for r in range(r_lo, r_hi + 1):
            for c in range(c_lo, c_hi + 1):
                if cls[r, c] != SEA:
                    continue
                if not (r == 0 or c == 0 or r == n_rows - 1 or c == n_cols - 1 or cls[r - 1, c] != SEA
                        or cls[r + 1, c] != SEA or cls[r, c - 1] != SEA or cls[r, c + 1] != SEA):
                    continue
                qx = c * dx
                qy = r * dy
                if _distance(qx, qy, sx, sy) > radius + d:
                    continue
                zones.append(("disc", COAST, qx, qy, d))
                reach["sea"] += 1

    # the candidates within the radius, nearest first, and a line across each
    near = []
    for item in lineaments.lineaments:
        dist, px, py = _nearest_on(sx, sy, item.start, item.end)
        if dist <= radius:
            near.append((dist, item, (px, py)))
    near.sort(key=lambda e: (e[0], -e[1].length_m, e[1].id))
    lines: list[SurveyLine] = []
    skipped: list[tuple[int, int]] = []
    for _, item, nearest in near:
        if len(lines) >= s["survey_lines"]:
            break
        by = next((line.id for line in lines if any(c[0] == item.id for c in line.crosses)), None)
        if by is not None:
            skipped.append((item.id, by))
            continue
        line = _lay(len(lines) + 1, item, nearest, item.strike_deg, (sx, sy), radius, s, lineaments)
        if line is None:
            skipped.append((item.id, 0))
            continue
        lines.append(line)
    basis = "candidates" if lines else "none"
    if not lines and lineaments.lineaments:
        totals = [lineaments.rose_valley_m[b] + lineaments.rose_ridge_m[b] for b in range(ROSE_BANDS)]
        band = 0
        for b in range(1, ROSE_BANDS):
            if totals[b] > totals[band]:
                band = b
        line = _lay(1, None, (sx, sy), band * 10.0 + 5.0, (sx, sy), radius, s, lineaments)
        if line is not None:
            lines.append(line)
            basis = "strike"

    soundings: list[SurveySounding] = []
    dropped: list[DroppedSounding] = []
    if basis == "candidates":
        for line in lines:
            kept, lost = _soundings(line, zones, s)
            t_start = line.first * line.station_m
            for role, t, moved, cleared in kept:
                point = (line.origin[0] + t * line.direction[0], line.origin[1] + t * line.direction[1])
                soundings.append(SurveySounding(len(soundings) + 1, line.id, role, t - t_start, point, moved,
                                                cleared, line.strike_deg))
            dropped.extend(lost)

    r0, r1, c0, c1 = core.shown
    covered = (sx - radius >= (c0 - 0.5) * dx and sx + radius <= (c1 - 0.5) * dx
               and sy - radius >= (r0 - 0.5) * dy and sy + radius <= (r1 - 0.5) * dy)
    unmapped = []
    for row in rows:
        if row.structure not in _MAPPED and all(u[0] != row.structure for u in unmapped):
            unmapped.append((row.structure, float(row.min_distance_m)))
    return SurveyPlan(
        site=(sx, sy), site_lonlat=(float(site[0]), float(site[1])), radius_m=radius, basis=basis,
        lines=tuple(lines), soundings=tuple(soundings), dropped=tuple(dropped),
        near=tuple(e[1].id for e in near), skipped=tuple(skipped), reach=reach, rings=tuple(rings),
        water_points=given, distances={name: table[name] for name in _MAPPED if name in table},
        unmapped=tuple(unmapped), ab2=ves_survey_plan(s["survey_target_depth_m"], ves or VESConfig()),
        covered=covered, frame=frame, settings=cfg, searched_m=searched_m)


# --- what is said of it, and the files


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _kept(plan: SurveyPlan) -> str:
    pieces = []
    for kind, key, structure in (("borehole", "survey_plan.kept_borehole", BOREHOLE),
                                 ("dug_well", "survey_plan.kept_dug_well", DUG_WELL),
                                 ("other", "survey_plan.kept_other", OTHER_WELL),
                                 ("surface", "survey_plan.kept_surface", STREAM)):
        if plan.reach[kind]:
            pieces.append(phrase(key, distance=plan.distances[structure], count=plan.reach[kind]))
    if plan.reach["streams"]:
        pieces.append(phrase("survey_plan.kept_streams", distance=plan.distances[STREAM]))
    if plan.reach["sea"]:
        pieces.append(phrase("survey_plan.kept_coast", distance=plan.distances[COAST]))
    if not pieces:
        return phrase("survey_plan.kept_nothing_loaded" if _short_of(plan) is not None else "survey_plan.kept_nothing")
    return phrase("survey_plan.kept", kept=and_join(pieces))


def water_point_reach(plan: SurveyPlan) -> float | None:
    """How far from the site a mapped water point's separation ring can
    reach a sounding: the service radius and the table's largest distance
    from a water point, or None where the table keeps none."""
    reach = None
    for structure in (BOREHOLE, DUG_WELL, OTHER_WELL, STREAM):
        if structure in plan.distances and (reach is None or plan.distances[structure] > reach):
            reach = plan.distances[structure]
    return None if reach is None else plan.radius_m + reach


def _short_of(plan: SurveyPlan) -> tuple[float, float] | None:
    """How far the water points were looked up, to the millimetre, and the
    reach they fell short of, or None where they did not. To the
    millimetre, so that a lookup a site's round trip through UTM has put a
    hair inside its radius (299.99999998 m of 300) is neither short of a
    reach it met nor said to stop at the metre below."""
    reach = water_point_reach(plan)
    if plan.searched_m is None or reach is None:
        return None
    searched = math.floor(plan.searched_m * 1000.0 + 0.5) / 1000.0
    return None if searched >= reach else (searched, reach)


def survey_plan_captions(plan: SurveyPlan | None, where: str) -> dict[str, str]:
    """The plan figure's title (``title_plan``), its caption (``plan``), one
    paragraph saying what the lines rest on, what was proposed, moved, left
    out and kept clear of, and what to check on the ground, and the note
    the figure draws inside it (``plan_note``, named apart from the
    lineament figures' ``figure_note``, so that the captions merge). With
    no plan, for a site with no GPS fix, ``plan`` alone, saying why."""
    from ..waterpoints import SERVICE_RADIUS_M

    if plan is None:
        return {"plan": phrase("survey_plan.needs_site", radius=float(SERVICE_RADIUS_M))}
    s = _plan_settings(plan.settings)
    radius = plan.radius_m
    parts: list[str] = []
    if plan.basis == "candidates":
        parts.append(phrase("survey_plan.lines_candidates", lines=len(plan.lines), radius=radius,
                            length=s["survey_line_m"], station=s["survey_station_m"]))
        parts.append(phrase("survey_plan.near", count=len(plan.near)))
        crossed = sum(1 for _, by in plan.skipped if by > 0)
        if crossed:
            parts.append(phrase("survey_plan.crossed", count=crossed))
        ab2 = plan.ab2
        parts.append(phrase("survey_plan.soundings", count=len(plan.soundings), flank=s["survey_flank_m"],
                            ab2=float(ab2["max_ab2"]), depth=float(ab2["investigation_m"]),
                            target=float(ab2["target_m"]), spread=float(ab2["line_m"])))
        if ab2["capped"]:
            parts.append(phrase("survey_plan.capped", ab2=float(ab2["max_ab2"]), depth=float(ab2["investigation_m"]),
                                target=float(ab2["target_m"])))
        moved = [abs(x.moved_m) for x in plan.soundings if x.moved_m != 0.0]
        if moved:
            most = moved[0]
            for value in moved[1:]:
                if value > most:
                    most = value
            parts.append(phrase("survey_plan.moved", count=len(moved), most=most))
        rings = sum(1 for d in plan.dropped if d.reasons != (OFF_LINE,))
        if rings:
            parts.append(phrase("survey_plan.dropped_rings", count=rings, move=s["survey_move_m"]))
        short = sum(1 for d in plan.dropped if d.reasons == (OFF_LINE,))
        if short:
            parts.append(phrase("survey_plan.dropped_short", count=short))
        parts.append(_kept(plan))
        fell = _short_of(plan)
        if fell is not None:
            # the whole metres it reached, so that 549.6 m is not printed as
            # the 550 m it fell short of
            parts.append(phrase("survey_plan.water_points_short", searched=float(math.floor(fell[0])),
                                reach=fell[1]))
        elif plan.water_points == 0 and plan.searched_m is None:
            parts.append(phrase("survey_plan.no_water_points"))
    elif plan.basis == "strike":
        line = plan.lines[0]
        parts.append(phrase("survey_plan.lines_strike", radius=radius, strike=line.strike_deg, length=line.length_m,
                            station=line.station_m))
    else:
        parts.append(phrase("survey_plan.lines_none"))
    if plan.basis != "none" and plan.unmapped:
        items = [phrase("survey_plan.unmapped_item", structure=_lower_first(name), distance=d)
                 for name, d in plan.unmapped]
        parts.append(phrase("survey_plan.unmapped", structures=and_join(items)))
    if not plan.covered:
        parts.append(phrase("survey_plan.uncovered"))
    return {
        "title_plan": phrase("survey_plan.title_plan", where=where),
        "plan": " ".join(parts),
        "plan_note": phrase("survey_plan.figure_note"),
    }


def _g(value: float) -> str:
    return f"{float(value):g}"


def _chainage(value: float, width: int) -> str:
    """A distance along a line as a station's name has it: Python's ``g``,
    its whole metres zero-padded to ``width`` figures."""
    text = _g(value)
    head = text.split(".")[0]
    return "0" * (width - len(head)) + text


def _station_names(line: SurveyLine) -> list[str]:
    width = len(_g(line.length_m).split(".")[0])
    return [phrase("survey_plan.station_name", line=line.id, chainage=_chainage((k - line.first) * line.station_m,
                                                                                 width))
            for k in range(line.first, line.last + 1)]


def _line_text(line: SurveyLine) -> str:
    if line.candidate is None:
        return phrase("survey_plan.line_strike", length=line.length_m, bearing=line.bearing_deg,
                      station=line.station_m, strike=line.strike_deg, at=line.crossing_m)
    return phrase("survey_plan.line_candidate", length=line.length_m, bearing=line.bearing_deg,
                  station=line.station_m, kind=line.kind, candidate=line.candidate, at=line.crossing_m)


def survey_sounding_text(plan: SurveyPlan, x: SurveySounding) -> str:
    """What a proposed sounding's GPX waypoint, GeoJSON feature and table
    row say of it: where it lies, any move, and its AB/2 and spread."""
    line = plan.lines[x.line - 1]
    if x.role == "crossing":
        where = phrase("survey_plan.sounding_crossing", kind=line.kind, candidate=line.candidate, at=x.at_m,
                       line=line.id)
    else:
        where = phrase("survey_plan.sounding_flank", offset=abs(x.at_m - line.crossing_m), kind=line.kind,
                       candidate=line.candidate, at=x.at_m, line=line.id)
    out = [where]
    if x.moved_m != 0.0:
        out.append(phrase("survey_plan.sounding_moved", moved=abs(x.moved_m),
                          cleared=and_join([phrase(_CLEARED[name]) for name in x.cleared])))
    out.append(phrase("survey_plan.sounding_spread", ab2=float(plan.ab2["max_ab2"]),
                      spread=float(plan.ab2["line_m"]), strike=x.spread_deg))
    return " ".join(out)


def _xml_text(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _wpt(lon: float, lat: float, name: str, desc: str | None, kind: str) -> str:
    out = f'<wpt lat="{lat:.6f}" lon="{lon:.6f}"><name>{_xml_text(name)}</name>'
    if desc:
        out += f"<desc>{_xml_text(desc)}</desc>"
    return out + f"<type>{_xml_text(kind)}</type></wpt>\n"


def survey_plan_gpx(plan: SurveyPlan, lons, lats, meta: Mapping) -> str:
    """The plan as a GPX 1.1 file, text written by hand in a fixed order so
    that both engines write the same bytes: a waypoint at the site, at each
    proposed sounding (its name ``VES n``, its description where it lies,
    any move and its AB/2) and at each line's two ends, then each line as a
    route, a point at each station named by its distance along the line.

    ``lons`` and ``lats`` are the analysed window's cell centres; ``meta``
    holds ``where`` (the place, as the read names it), ``label`` (what the
    files are) and ``site_label`` (the site's name). Coordinates have six
    decimals, about 0.1 m, finer than a phone's fix.
    """
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n',
           '<gpx version="1.1" creator="Groundwater Investigation Toolkit" xmlns="http://www.topografix.com/GPX/1/1">\n',
           "<metadata><name>", _xml_text(phrase("survey_plan.title_plan", where=meta["where"])), "</name><desc>",
           _xml_text(phrase("survey_plan.gpx_description", where=meta["where"], label=meta["label"])),
           "</desc></metadata>\n"]
    lon, lat = plan.site_lonlat
    out.append(_wpt(lon, lat, meta["site_label"], None, "Site"))
    for x in plan.soundings:
        lon, lat = lineament_lonlat(plan, lons, lats, x.point)
        out.append(_wpt(lon, lat, phrase("survey_plan.ves_name", n=x.id), survey_sounding_text(plan, x), "VES"))
    for line in plan.lines:
        for key, k in (("survey_plan.line_start", line.first), ("survey_plan.line_end", line.last)):
            lon, lat = lineament_lonlat(plan, lons, lats, line_station(line, k))
            out.append(_wpt(lon, lat, phrase(key, line=line.id), None, "Line end"))
    for line in plan.lines:
        out.append(f"<rte><name>{_xml_text(phrase('survey_plan.line_name', line=line.id))}</name>"
                   f"<desc>{_xml_text(_line_text(line))}</desc>")
        for k, name in zip(range(line.first, line.last + 1), _station_names(line), strict=True):
            lon, lat = lineament_lonlat(plan, lons, lats, line_station(line, k))
            out.append(f'<rtept lat="{lat:.6f}" lon="{lon:.6f}"><name>{_xml_text(name)}</name></rtept>')
        out.append("</rte>\n")
    out.append("</gpx>\n")
    return "".join(out)


def _ring_text(plan: SurveyPlan, lons, lats, x: float, y: float, d: float) -> str:
    points = []
    for k in range(_RING_SEGMENTS):
        sin, cos = sin_cos_deg(360.0 * k / _RING_SEGMENTS)
        lon, lat = lineament_lonlat(plan, lons, lats, (x + d * sin, y + d * cos))
        points.append(f"[{lon:.6f},{lat:.6f}]")
    points.append(points[0])
    return '{"type":"Polygon","coordinates":[[' + ",".join(points) + "]]}"


def _point_text(plan: SurveyPlan, lons, lats, point: tuple[float, float]) -> str:
    lon, lat = lineament_lonlat(plan, lons, lats, point)
    return f'{{"type":"Point","coordinates":[{lon:.6f},{lat:.6f}]}}'


def _feature(properties: str, geometry: str) -> str:
    return '{"type":"Feature","properties":{' + properties + '},"geometry":' + geometry + "}"


def survey_plan_geojson(plan: SurveyPlan, lons, lats, meta: Mapping) -> str:
    """The plan as GeoJSON text written by hand, without whitespace, in a
    fixed key order, so that both engines write the same bytes: the service
    radius, the separation ring round each mapped water point within reach,
    the lines, their stations and the proposed soundings, each feature's
    ``layer`` naming which, as the GeoLibre project takes them apart into
    layers. ``meta`` is as :func:`survey_plan_gpx` takes it.
    Coordinates have six decimals; lengths, bearings and strikes one."""
    sx, sy = plan.site
    lon, lat = plan.site_lonlat
    out = ['{"type":"FeatureCollection","description":',
           _json_text(phrase("survey_plan.geojson_description", where=meta["where"], label=meta["label"],
                             radius=plan.radius_m)),
           f',"radius_m":{_g(plan.radius_m)},"site":[{lon:.6f},{lat:.6f}],"features":[']
    features = [_feature(f'"layer":"service_radius","radius_m":{_g(plan.radius_m)}',
                         _ring_text(plan, lons, lats, sx, sy, plan.radius_m))]
    for x, y, structure, d in plan.rings:
        features.append(_feature(f'"layer":"clearance","structure":{_json_text(structure)},"distance_m":{_g(d)}',
                                 _ring_text(plan, lons, lats, x, y, d)))
    for line in plan.lines:
        a = lineament_lonlat(plan, lons, lats, line_station(line, line.first))
        b = lineament_lonlat(plan, lons, lats, line_station(line, line.last))
        candidate = "null" if line.candidate is None else str(line.candidate)
        kind = "null" if line.kind is None else _json_text(line.kind)
        features.append(_feature(
            f'"layer":"line","line":{line.id},"name":{_json_text(phrase("survey_plan.line_name", line=line.id))},'
            f'"candidate":{candidate},"kind":{kind},"strike_deg":{line.strike_deg:.1f},'
            f'"bearing_deg":{line.bearing_deg:.1f},"length_m":{line.length_m:.1f},"station_m":{_g(line.station_m)},'
            f'"crossing_m":{line.crossing_m:.1f},"description":{_json_text(_line_text(line))}',
            f'{{"type":"LineString","coordinates":[[{a[0]:.6f},{a[1]:.6f}],[{b[0]:.6f},{b[1]:.6f}]]}}'))
    for line in plan.lines:
        for k, name in zip(range(line.first, line.last + 1), _station_names(line), strict=True):
            features.append(_feature(
                f'"layer":"station","line":{line.id},"name":{_json_text(name)},'
                f'"chainage_m":{(k - line.first) * line.station_m:.1f}',
                _point_text(plan, lons, lats, line_station(line, k))))
    for x in plan.soundings:
        features.append(_feature(
            f'"layer":"sounding","name":{_json_text(phrase("survey_plan.ves_name", n=x.id))},"line":{x.line},'
            f'"role":{_json_text(x.role)},"chainage_m":{x.at_m:.1f},"moved_m":{x.moved_m:.1f},'
            f'"ab2_max_m":{_g(plan.ab2["max_ab2"])},"spread_m":{_g(plan.ab2["line_m"])},'
            f'"spread_deg":{x.spread_deg:.1f},"description":{_json_text(survey_sounding_text(plan, x))}',
            _point_text(plan, lons, lats, x.point)))
    out.append(",".join(features))
    out.append("]}")
    return "".join(out)

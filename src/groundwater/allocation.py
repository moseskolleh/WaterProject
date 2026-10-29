"""Where to drill next, within a budget (PLAN.md step 6.1).

The coverage-gap ranking says where people are short of water. A programme
manager with a budget needs the next step: which areas to drill in, and how
many boreholes in each, to serve the most people the money buys. This
module answers that from what the toolkit already holds:

1. **The candidates** are the areas of the coverage-gap ranking
   (``coverage.coverage_rows`` or ``coverage.chiefdom_coverage_rows``),
   with the population the page shows. An area's **unserved people** are its
   population less ``allocation.people_per_borehole`` (500, the handpump
   figure of ``data/coverage_service_classes.csv``) for each functional
   mapped point, rounded down to whole people, and never fewer than none.
   The boreholes it **justifies** are that many people over the same figure,
   rounded up; each serves up to the figure, the last the remainder.
2. **The odds** are step 3.3's prior for the area's ground: the BGS aquifer
   class with a prior of its own that covers the most of the points of a
   ``allocation.ground_grid`` by ``ground_grid`` grid over the area's
   bounding box that fall inside the area, and within it the USGS unit that
   covers the most of them, a tie going to the code first in alphabetical
   order. The calibration set in force applies, as it does to every prior.
   An area none of whose points falls on such a class (only surface water,
   or off the map) has no known odds and is left out, never given the
   fallback's even chance.
3. **The cost** of a working borehole is step 3.4's: the mean completed
   borehole of the Costing page's estimate and its mean dry attempt for
   each of the ``(1 - p) / p`` dry attempts expected before a working one,
   with the depth held at the estimate's (a range of models belongs to one
   survey's point, not to a country). An access cost may be typed for an
   area, per attempt, so a working borehole there carries it ``1 / p``
   times; with none typed, the page says access is not modelled. The cost is
   worked out to the cent.
4. **The choice** aims at the most people served within the budget at those
   expected costs, and of the sets that serve as many the cheapest. Ranked
   by people served per dollar, a working borehole's people over its
   expected cost is the plan's expected people served per dollar: the chance
   times the people, over the expected cost of an attempt, is the same
   figure. With at most ``allocation.exact_max_items`` candidate boreholes
   the choice is exact, by dynamic programming over the number of people
   served (the least cost of serving each number exactly; people are whole
   numbers, so the budget is not counted out in steps of some currency
   unit, as a knapsack over the budget would count it). With more it is
   greedy: the boreholes in order of people per dollar, best first, each one
   that fits in what is left, and the linear-programming bound (the greedy
   order with the last borehole bought in part) says how far from the best
   it can be. Ties go to the area first in alphabetical order, then to its
   earlier boreholes.

Each area is then in or out with its reason (all its boreholes, some of them
and the next not affordable, not affordable, lower value per dollar than any
borehole chosen, no unserved people, odds unknown), and the marginal cost per
extra person served is the next borehole a larger budget would buy, the best
by people per dollar of those not chosen. The text says plainly that chiefdom
populations are too coarse for access distances until settlement-level
population (step 6.2) is added.

Both engines run this, and ``gwt-core.js`` is held to it by
``tests/webapp/parity.mjs``. The grid, the ray casting
(``_geometry.points_in_ring``, the browser's ``ringHolds``), the sums and the
comparisons are the same operations in the same order in both. The odds take
logarithms, which the two engines need not round alike, so the cost of a
working borehole is worked out to the cent, where they agree; with that, the
two choose the same boreholes and print the same table, and only the
expected attempts, which divide by the odds, can differ in their last bits.
"""

from __future__ import annotations

import functools
import math
import numbers
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from ._geometry import points_in_ring, ring_bbox
from .calibration_sets import in_force, set_name
from .config import Config
from .text import phrase

if TYPE_CHECKING:
    from .siting.odds import SuccessOdds

__all__ = [
    "AreaGround",
    "Allocation",
    "Candidate",
    "Marginal",
    "EXACT_MAX_CELLS",
    "LEVELS",
    "allocate",
    "allocation_basis_text",
    "allocation_csv",
    "allocation_header",
    "allocation_rows",
    "allocation_text",
    "area_ground",
    "area_grounds",
]

#: The resolutions of the coverage-gap ranking.
LEVELS = ("district", "chiefdom")

#: The most entries the exact choice's tables may hold. It keeps a mark for
#: every candidate borehole at every number of people they could serve, so
#: allocation.exact_max_items squared times allocation.people_per_borehole
#: bounds them; this keeps them to tens of megabytes in either engine, and
#: the defaults come to 800,000.
EXACT_MAX_CELLS = 50_000_000


# ------------------------------------------------------------------ the ground

@dataclass(frozen=True)
class AreaGround:
    """The ground covering most of an area, as the grid reads it."""

    area: str
    #: the grid's points that fall inside the area
    samples: int
    #: the BGS aquifer class with a prior of its own on the most of them, and
    #: the USGS unit on the most of that class's; None where there is none
    bgs_code: str | None
    glg: str | None
    #: how many of the points are on the class, and on the class and the unit
    class_samples: int
    unit_samples: int


def _has_prior(code: str) -> bool:
    """Whether the prior table has a row of its own for this aquifer class:
    any but a fallback. The surface water the BGS map marks n/a has only the
    fallback's even chance, which says nothing of the ground."""
    from .siting.odds import odds_tables

    return any(r["bgs_code"] == code and r["status"] != "fallback"
               for r in odds_tables()["prior"])


def _holds(lon: np.ndarray, lat: np.ndarray, ring: np.ndarray, holes,
           box: tuple[float, float, float, float] | None = None) -> np.ndarray:
    """Which points the ring holds and none of its holes does. A point outside
    the ring's bounding box is not tested, as the browser's twin does not
    test it."""
    x0, y0, x1, y1 = box if box is not None else ring_bbox(ring)
    out = np.zeros(lon.shape[0], dtype=bool)
    near = np.flatnonzero((lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1))
    if near.size:
        inside = points_in_ring(lon[near], lat[near], ring)
        for hole in holes:
            if inside.any():
                inside &= ~points_in_ring(lon[near], lat[near], hole)
        out[near] = inside
    return out


def _first_unit(lon: np.ndarray, lat: np.ndarray, units) -> list[str | None]:
    """Each point's code on the first unit, in the layer's order, that holds
    it, as ground_at finds it: None on no unit (and on a unit with no code)."""
    codes: list[str | None] = [None] * lon.shape[0]
    pending = np.ones(lon.shape[0], dtype=bool)
    for unit, box in units:
        if not pending.any():
            break
        hit = _holds(lon, lat, unit.ring, unit.holes, box) & pending
        for k in np.flatnonzero(hit):
            codes[k] = unit.glg or None
        pending &= ~hit
    return codes


def _most(counts: dict) -> object:
    """The key counted most, a tie going to the key first in alphabetical
    order, and None after every name."""
    return min(counts, key=lambda k: (-counts[k], k is None, k or ""))


def area_ground(name: str, polys, aquifers, units, grid: int) -> AreaGround:
    """The ground covering most of the area ``polys`` make up (chiefdom
    polygons as ``coverage.load_chiefdom_polys`` reads them), read at a
    ``grid`` by ``grid`` grid of points over their bounding box.

    ``aquifers`` and ``units`` are the BGS and USGS units in the layers'
    order, each paired with its ring's bounding box.
    """
    rings = [r for p in polys for r in p.rings if len(r)]
    if not rings:
        return AreaGround(name, 0, None, None, 0, 0)
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for ring in rings:
        bx0, by0, bx1, by1 = ring_bbox(ring)
        x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
    # cell centres, the same arithmetic as the browser's: x0 + (i + 0.5) *
    # (x1 - x0) / n, latitude by latitude
    steps = np.arange(grid, dtype=float) + 0.5
    lon = np.tile(x0 + steps * (x1 - x0) / grid, grid)
    lat = np.repeat(y0 + steps * (y1 - y0) / grid, grid)
    inside = np.zeros(lon.shape[0], dtype=bool)
    for poly in polys:
        for i, ring in enumerate(poly.rings):
            if len(ring):
                holes = poly.holes[i] if i < len(poly.holes) else []
                inside |= _holds(lon, lat, ring, holes)
    lon, lat = lon[inside], lat[inside]
    samples = int(lon.shape[0])
    codes = _first_unit(lon, lat, aquifers)
    glgs = _first_unit(lon, lat, units)
    by_class: dict = {}
    for code in codes:
        if code is not None and _has_prior(code):
            by_class[code] = by_class.get(code, 0) + 1
    if not by_class:
        return AreaGround(name, samples, None, None, 0, 0)
    code = _most(by_class)
    by_unit: dict = {}
    for c, g in zip(codes, glgs, strict=True):
        if c == code:
            by_unit[g] = by_unit.get(g, 0) + 1
    glg = _most(by_unit)
    return AreaGround(name, samples, str(code), glg if glg is None else str(glg),
                      by_class[code], by_unit[glg])


@functools.lru_cache(maxsize=4)
def _grounds(level: str, grid: int) -> dict[str, AreaGround]:
    from .coverage import load_chiefdom_district, load_chiefdom_polys
    from .siting.odds import _map_units

    polys = load_chiefdom_polys()
    aquifers, units = _map_units()
    boxed = ([(u, ring_bbox(u.ring)) for u in aquifers], [(u, ring_bbox(u.ring)) for u in units])
    groups: dict[str, list] = {}
    if level == "chiefdom":
        for poly in polys:
            if poly.name:
                groups.setdefault(poly.name, []).append(poly)
    else:
        crosswalk = load_chiefdom_district()
        for poly in polys:
            district = crosswalk.get(poly.name, "")
            if district:
                groups.setdefault(district, []).append(poly)
    return {name: area_ground(name, members, boxed[0], boxed[1], grid)
            for name, members in groups.items()}


def area_grounds(level: str, config: Config | None = None) -> dict[str, AreaGround]:
    """The ground of every district or chiefdom on the bundled layers, worked
    out once per process; a district is the chiefdoms the crosswalk puts in
    it."""
    if level not in LEVELS:
        raise ValueError(f"the resolution must be one of {LEVELS}, not {level!r}")
    config = config or Config()
    return dict(_grounds(level, _whole(config.allocation.ground_grid, "allocation.ground_grid", 1)))


# --------------------------------------------------------------- candidates

@dataclass
class Candidate:
    """One area of the ranking, as the choice weighs it, and what it got."""

    id: str
    #: the district a chiefdom is in; "" at district resolution
    district: str
    population: float
    functional_points: int
    unserved: int
    #: the boreholes the unserved people justify
    boreholes: int
    ground: AreaGround | None
    #: the prior odds for the ground, None where unknown
    odds: SuccessOdds | None
    access_usd: float
    #: the expected cost of a working borehole here, access included; None
    #: where the odds are unknown
    cost_usd: float | None
    #: the boreholes chosen, what they cost and the people they serve
    chosen: int = 0
    chosen_usd: float = 0.0
    people: int = 0
    #: all, part, budget, value, unserved or odds
    reason: str = ""

    @property
    def eligible(self) -> bool:
        return self.unserved > 0 and self.cost_usd is not None


@dataclass
class Marginal:
    """The next borehole a larger budget would buy."""

    area: str
    cost_usd: float
    people: int
    usd_per_person: float
    #: what it costs beyond the budget left
    more_usd: float


@dataclass
class Allocation:
    level: str
    budget_usd: float
    people_per_borehole: int
    exact_max_items: int
    ground_grid: int
    #: "exact" or "greedy"
    method: str
    #: the candidate boreholes chosen between: each area's, up to what its
    #: unserved people justify and the whole budget could buy
    items: int
    #: every area, the chosen first by people per dollar, then the rest
    candidates: list[Candidate]
    boreholes: int
    areas: int
    cost_usd: float
    left_usd: float
    people: int
    attempts: float
    #: the linear-programming bound on the people served, whole people
    bound: int
    marginal: Marginal | None
    #: the cost distribution's figures the costs were worked out from
    mean_usd: float
    dry_usd: float
    cost_samples: int
    cost_seed: int
    depth_m: float
    #: the calibration set in force, as the reports name it
    calibration: str
    #: the basis the coverage map's service classes give the figure, or ""
    #: where none has it
    people_basis: str = ""
    #: the least people per US$ 1,000 of any borehole chosen
    least_ratio: float | None = None
    access_areas: int = 0
    cheapest: Candidate | None = field(default=None, repr=False)


def _whole(value, name: str, least: int) -> int:
    """A whole number of at least ``least``, written as an int or a float (a
    numpy scalar too), as the browser reads any number; refused otherwise."""
    number = (float(value) if isinstance(value, numbers.Real) and not isinstance(value, bool)
              else math.nan)
    if not math.isfinite(number) or number != math.floor(number) or number < least:
        raise ValueError(f"{name} must be a whole number of at least {least}, not {value!r}")
    return int(number)


def _figure(value, name: str) -> float:
    number = (float(value) if isinstance(value, numbers.Real) and not isinstance(value, bool)
              else math.nan)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number, not {value!r}")
    return number


def _served(unserved: int, per: int, k: int) -> int:
    """The people the ``k``-th borehole of an area serves (1 for the first)."""
    return min(per, unserved - per * (k - 1))


def _row(row, name: str):
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _cost_figures(cost) -> tuple[float, float, int, int, float]:
    """The cost distribution's mean completed borehole, mean dry attempt,
    samples, seed and depth, refused where they cannot be costs."""
    mean = _figure(_row(cost, "mean"), "the mean cost of a borehole")
    dry = _figure(_row(cost, "dry_mean"), "the mean cost of a dry attempt")
    if not mean > 0.0 or dry < 0.0:
        raise ValueError("a completed borehole must cost more than nothing, and a dry attempt "
                         "nothing or more")
    return (mean, dry, _whole(_row(cost, "samples"), "the cost's samples", 1),
            _whole(_row(cost, "seed"), "the cost's seed", 0),
            _figure(_row(cost, "depth_m"), "the cost's depth"))


def _candidates(rows, level: str, mean: float, dry: float, access: dict, config: Config,
                grounds: dict) -> list[Candidate]:
    from .siting.odds import prior_odds

    per = config.allocation.people_per_borehole
    out: list[Candidate] = []
    seen: set[str] = set()
    # a few kinds of ground between them all, so each is looked up once
    priors: dict = {}
    for row in rows:
        name = _row(row, "name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"an area of the ranking has no name: {name!r}")
        if name in seen:
            raise ValueError(f"the area {name!r} is in the ranking twice")
        seen.add(name)
        population = _figure(_row(row, "population"), f"the population of {name}")
        functional = _whole(_row(row, "functional_points"), f"the functional points of {name}", 0)
        short = population - per * functional
        unserved = int(math.floor(short)) if short > 0.0 else 0
        boreholes = (unserved + per - 1) // per
        typed = access.get(name, 0.0)
        access_usd = _figure(typed, f"the access cost of {name}")
        if access_usd < 0.0:
            raise ValueError(f"the access cost of {name} must be nothing or more, not {typed!r}")
        ground = grounds.get(name)
        odds = None
        cost_usd = None
        if ground is not None and ground.bgs_code is not None:
            key = (ground.bgs_code, ground.glg)
            if key not in priors:
                priors[key] = prior_odds(ground.bgs_code, ground.glg, config)
            odds = priors[key]
            if odds.matched == "fallback":
                odds = None
        if odds is not None:
            p = odds.probability
            # to the cent: the odds take logarithms, which the two engines
            # need not round alike, and a cost they agree on to the cent is
            # the same cost in both
            cost_usd = round(mean + dry * ((1.0 - p) / p) + access_usd / p, 2)
        district = "" if level == "district" else str(_row(row, "district") or "")
        out.append(Candidate(id=name, district=district, population=population,
                             functional_points=functional, unserved=unserved, boreholes=boreholes,
                             ground=ground, odds=odds, access_usd=access_usd, cost_usd=cost_usd))
    out.sort(key=lambda c: c.id)
    return out


# ---------------------------------------------------------------- the choice

def _exact(items: list[tuple[int, int, int, float]], budget: float) -> tuple[list[int], float]:
    """The items chosen (by index) and their cost: the set serving the most
    people within ``budget``, the cheapest of those, ties to earlier items.

    ``items`` are (candidate, borehole, people, cost). The least cost of
    serving each number of people exactly is built item by item, an item
    taken only where it costs strictly less, as a 0/1 knapsack over people.
    """
    total = 0
    for _c, _k, w, _cost in items:
        total += w
    dp = np.full(total + 1, np.inf)
    dp[0] = 0.0
    takes = []
    for _c, _k, w, c in items:
        cand = dp[: total + 1 - w] + c
        better = cand < dp[w:]
        dp[w:] = np.where(better, cand, dp[w:])
        takes.append(better)
    v = int(np.flatnonzero(dp <= budget).max())
    spent = float(dp[v])
    chosen = []
    for i in range(len(items) - 1, -1, -1):
        w = items[i][2]
        if v >= w and takes[i][v - w]:
            chosen.append(i)
            v -= w
    return chosen, spent


def _ratio_order(items):
    return sorted(range(len(items)), key=lambda i: (-(items[i][2] / items[i][3]),
                                                   items[i][0], items[i][1]))


def _greedy(items, order, budget: float) -> tuple[list[int], float]:
    spent = 0.0
    chosen = []
    for i in order:
        c = items[i][3]
        if spent + c <= budget:
            spent += c
            chosen.append(i)
    return chosen, spent


def _bound(items, order, budget: float) -> float:
    """The linear-programming bound: the greedy order with the first borehole
    that does not fit bought in the part the budget left covers."""
    spent = 0.0
    people = 0.0
    for i in order:
        w, c = items[i][2], items[i][3]
        if spent + c <= budget:
            spent += c
            people += w
        else:
            people += w * ((budget - spent) / c)
            break
    return people


def allocate(rows, budget_usd, cost, *, level: str, access: dict | None = None,
             config: Config | None = None, grounds: dict | None = None) -> Allocation:
    """Choose where to drill within ``budget_usd``.

    ``rows`` are the coverage-gap ranking's rows (``coverage_rows`` or
    ``chiefdom_coverage_rows``, or mappings with their ``name``,
    ``district``, ``population`` and ``functional_points``), ``cost`` the
    cost distribution of the Costing page's borehole (``sample_cost``; its
    ``mean``, ``dry_mean``, ``samples``, ``seed`` and ``depth_m`` are read),
    ``level`` "district" or "chiefdom", and ``access`` an access cost in US$
    per attempt by area name. ``grounds`` replaces the bundled layers'
    (:func:`area_grounds`) for a test.
    """
    if level not in LEVELS:
        raise ValueError(f"the resolution must be one of {LEVELS}, not {level!r}")
    config = config or Config()
    budget = _figure(budget_usd, "the budget")
    if not budget > 0.0:
        raise ValueError(f"the budget must be more than nothing, not {budget_usd!r}")
    per = _whole(config.allocation.people_per_borehole, "allocation.people_per_borehole", 1)
    limit = _whole(config.allocation.exact_max_items, "allocation.exact_max_items", 0)
    grid = _whole(config.allocation.ground_grid, "allocation.ground_grid", 1)
    if limit * limit * per > EXACT_MAX_CELLS:
        raise ValueError(
            f"allocation.exact_max_items squared times allocation.people_per_borehole is "
            f"{limit * limit * per:,}; the exact choice keeps a table that large, and takes at "
            f"most {EXACT_MAX_CELLS:,}")
    mean, dry, samples, seed, depth = _cost_figures(cost)
    if grounds is None:
        grounds = area_grounds(level, config)
    candidates = _candidates(rows, level, mean, dry, dict(access or {}), config, grounds)

    # each area's boreholes, up to what its people justify and the whole
    # budget could buy, in alphabetical order and borehole by borehole
    items: list[tuple[int, int, int, float]] = []
    for ci, cand in enumerate(candidates):
        if not cand.eligible:
            continue
        c = float(cand.cost_usd)  # type: ignore[arg-type]
        for k in range(1, min(cand.boreholes, int(math.floor(budget / c))) + 1):
            items.append((ci, k, _served(cand.unserved, per, k), c))
    order = _ratio_order(items)
    if len(items) <= limit:
        method = "exact"
        chosen, spent = _exact(items, budget) if items else ([], 0.0)
    else:
        method = "greedy"
        chosen, spent = _greedy(items, order, budget)
    bound = _bound(items, order, budget) if items else 0.0
    for i in chosen:
        cand = candidates[items[i][0]]
        cand.chosen += 1
    left = budget - spent
    least = None
    people = 0
    boreholes = 0
    attempts = 0.0
    for cand in candidates:
        if cand.chosen:
            c = float(cand.cost_usd)  # type: ignore[arg-type]
            cand.chosen_usd = c * cand.chosen
            cand.people = min(per * cand.chosen, cand.unserved)
            ratio = 1000.0 * _served(cand.unserved, per, cand.chosen) / c
            least = ratio if least is None or ratio < least else least
            people += cand.people
            boreholes += cand.chosen
            attempts += cand.chosen / cand.odds.probability  # type: ignore[union-attr]
    for cand in candidates:
        if cand.unserved <= 0:
            cand.reason = "unserved"
        elif cand.cost_usd is None:
            cand.reason = "odds"
        elif cand.chosen == cand.boreholes:
            cand.reason = "all"
        elif cand.chosen:
            cand.reason = "part"
        elif least is not None and 1000.0 * _served(cand.unserved, per, 1) / cand.cost_usd < least:
            cand.reason = "value"
        else:
            cand.reason = "budget"

    marginal = None
    for cand in candidates:
        if cand.eligible and cand.chosen < cand.boreholes:
            c = float(cand.cost_usd)  # type: ignore[arg-type]
            w = _served(cand.unserved, per, cand.chosen + 1)
            if marginal is None or w / c > marginal.people / marginal.cost_usd:
                marginal = Marginal(cand.id, c, w, c / w, c - left)
    cheapest = None
    for cand in candidates:
        if cand.eligible and (cheapest is None or cand.cost_usd < cheapest.cost_usd):  # type: ignore[operator]
            cheapest = cand

    def first_ratio(cand: Candidate) -> float:
        return _served(cand.unserved, per, 1) / float(cand.cost_usd)  # type: ignore[arg-type]

    def group(cand: Candidate) -> tuple:
        if cand.chosen:
            return (0, -first_ratio(cand), cand.id)
        if cand.eligible:
            return (1, -first_ratio(cand), cand.id)
        return (2 if cand.reason == "odds" else 3, 0.0, cand.id)

    ordered = sorted(candidates, key=group)
    classes = _service_basis(per)
    return Allocation(
        level=level, budget_usd=budget, people_per_borehole=per, exact_max_items=limit,
        ground_grid=grid, method=method, items=len(items), candidates=ordered,
        boreholes=boreholes, areas=sum(1 for c in candidates if c.chosen), cost_usd=spent,
        left_usd=left, people=people, attempts=attempts, bound=int(math.floor(bound)),
        marginal=marginal, mean_usd=mean, dry_usd=dry, cost_samples=samples, cost_seed=seed,
        depth_m=depth,
        calibration=set_name(in_force(config)), people_basis=classes, least_ratio=least,
        access_areas=sum(1 for c in candidates if c.access_usd > 0.0), cheapest=cheapest,
    )


def _service_basis(per: int) -> str:
    """The basis the coverage map's service classes give a band whose top is
    ``per`` people per point, or "" where no band has that top."""
    from .coverage import load_service_classes

    for band in load_service_classes():
        if band.kind == "class" and band.max_people_per_point == per:
            return band.basis
    return ""


# ---------------------------------------------------------------------- prose

def _usd(value: float) -> str:
    return f"{value:,.0f}"


def _count(value: int) -> str:
    return f"{value:,}"


def allocation_text(a: Allocation) -> list[str]:
    """The choice in sentences: what the candidates are, what the budget
    buys, how it was chosen, the next borehole, and what the people served
    and the costs leave out. :func:`allocation_basis_text` is the basis."""
    out = [phrase("allocation.lead", per=a.people_per_borehole)]
    if a.cheapest is None:
        out.append(phrase("allocation.headline_no_candidates"))
    elif not a.boreholes:
        out.append(phrase("allocation.headline_none", budget=_usd(a.budget_usd),
                          area=a.cheapest.id, cheapest=_usd(float(a.cheapest.cost_usd or 0.0))))
    else:
        out.append(phrase("allocation.headline", budget=_usd(a.budget_usd), n=a.boreholes,
                          areas=a.areas, people=_count(a.people), cost=_usd(a.cost_usd),
                          attempts=a.attempts, left=_usd(a.left_usd)))
    if a.items:
        if a.method == "exact":
            out.append(phrase("allocation.method_exact", items=_count(a.items), n=a.items,
                              limit=a.exact_max_items))
        else:
            gap = a.bound - a.people
            out.append(phrase("allocation.method_greedy", items=_count(a.items),
                              limit=a.exact_max_items))
            if gap > 0:
                out.append(phrase("allocation.greedy_gap", bound=_count(a.bound), gap=_count(gap),
                                  share=_share(gap / a.bound)))
            else:
                out.append(phrase("allocation.greedy_best", bound=_count(a.bound)))
    if a.cheapest is not None:
        m = a.marginal
        if m is None:
            out.append(phrase("allocation.marginal_none"))
        else:
            out.append(phrase("allocation.marginal", area=m.area, cost=_usd(m.cost_usd),
                              people=_count(m.people), per_person=_usd(m.usd_per_person),
                              more=_usd(m.more_usd)))
    out.append(phrase("allocation.coarse"))
    if a.access_areas:
        out.append(phrase("allocation.access_some", n=a.access_areas))
    else:
        out.append(phrase("allocation.access_none"))
    return out


def allocation_basis_text(a: Allocation) -> list[str]:
    """What the people, the ground and the cost of a borehole rest on."""
    out = []
    if a.people_basis:
        out.append(phrase("allocation.basis_people", per=a.people_per_borehole,
                          basis=a.people_basis))
    else:
        out.append(phrase("allocation.basis_people_set", per=a.people_per_borehole))
    out.append(phrase("allocation.basis_ground", grid=a.ground_grid, calibration=a.calibration))
    out.append(phrase("allocation.basis_cost", mean=_usd(a.mean_usd), dry=_usd(a.dry_usd),
                      n=_count(a.cost_samples), seed=a.cost_seed, depth=a.depth_m))
    return out


def _share(fraction: float) -> str:
    from .ves.model_range import _share as share

    return share(fraction)


def allocation_header(a: Allocation) -> list[str]:
    """The table's header; the district a chiefdom is in has a column."""
    cols = ["allocation.col_area"] + (["allocation.col_district"] if a.level == "chiefdom" else []) + [
        "allocation.col_unserved", "allocation.col_ground", "allocation.col_odds", "allocation.col_cost",
        "allocation.col_chosen", "allocation.col_people", "allocation.col_ratio", "allocation.col_why"]
    return [phrase(c) for c in cols]


def _ground_cell(cand: Candidate) -> str:
    g = cand.ground
    if g is None or g.bgs_code is None:
        return phrase("allocation.ground_none")
    share = _share(g.class_samples / g.samples)
    if g.glg is None:
        return phrase("allocation.ground_cell_class", code=g.bgs_code, share=share)
    return phrase("allocation.ground_cell", code=g.bgs_code, glg=g.glg, share=share)


def _why(a: Allocation, cand: Candidate) -> str:
    per = a.people_per_borehole
    if cand.reason == "unserved":
        return phrase("allocation.why_unserved", f=cand.functional_points, per=per)
    if cand.reason == "odds":
        return phrase("allocation.why_odds")
    if cand.reason == "all":
        return phrase("allocation.why_all", k=cand.chosen)
    if cand.reason == "part":
        return phrase("allocation.why_part", k=cand.chosen, n=cand.boreholes,
                      left=_usd(a.left_usd))
    if cand.reason == "value":
        return phrase("allocation.why_value",
                      ratio=1000.0 * _served(cand.unserved, per, 1) / float(cand.cost_usd or 1.0),
                      least=float(a.least_ratio or 0.0))
    return phrase("allocation.why_budget", cost=_usd(float(cand.cost_usd or 0.0)),
                  left=_usd(a.left_usd))


def allocation_rows(a: Allocation) -> list[list[str]]:
    """The table: each area with its unserved people, its ground and odds,
    the cost of a working borehole there, the boreholes chosen of those its
    people justify, the people they serve, the people per US$ 1,000 its first
    borehole serves, and why it is in or out."""
    from .siting.odds import odds_short

    rows = []
    for cand in a.candidates:
        cost = cand.cost_usd
        eligible = cand.eligible and cost is not None
        row = [cand.id] + ([cand.district] if a.level == "chiefdom" else []) + [
            _count(cand.unserved),
            _ground_cell(cand),
            odds_short(cand.odds) if cand.odds is not None else "",
            _usd(cost) if cost is not None else "",
            phrase("allocation.chosen_cell", k=cand.chosen, n=cand.boreholes) if eligible else "",
            _count(cand.people),
            (f"{1000.0 * _served(cand.unserved, a.people_per_borehole, 1) / cost:.1f}"
             if eligible and cost is not None else ""),
            _why(a, cand),
        ]
        rows.append(row)
    return rows


def _csv_field(text: str) -> str:
    if any(ch in text for ch in ',"\n\r'):
        return '"' + text.replace('"', '""') + '"'
    return text


def allocation_csv(a: Allocation) -> str:
    """The table as CSV, then a blank line and each sentence of the text on a
    line of its own, so the caveats travel with the numbers. Both engines
    write it byte for byte."""
    lines = [",".join(_csv_field(c) for c in allocation_header(a))]
    lines += [",".join(_csv_field(c) for c in row) for row in allocation_rows(a)]
    lines.append("")
    lines += [_csv_field(t) for t in allocation_text(a) + allocation_basis_text(a)]
    return "\n".join(lines) + "\n"

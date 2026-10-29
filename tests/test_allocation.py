"""Where to drill next, within a budget (PLAN.md step 6.1).

The arithmetic of unserved people and the boreholes they justify, the ground
an area is read as, the exact choice against every set of boreholes there
is, the greedy choice against its bound and the exact one, the reasons each
area is in or out, the next borehole, the refusals, the words, and the
browser's engine held to all of it in a Node vm.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import math
import random
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from groundwater import allocation as AL
from groundwater._geometry import point_in_ring, points_in_ring
from groundwater.allocation import (
    AreaGround,
    allocate,
    allocation_basis_text,
    allocation_csv,
    allocation_rows,
    allocation_text,
)
from groundwater.config import Config
from groundwater.coverage import (
    chiefdom_population,
    load_chiefdom_district,
    load_chiefdom_polys,
    load_district_population,
    load_service_classes,
)
from groundwater.siting.odds import prior_odds

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"

#: a cost distribution as sample_cost gives its figures
COST = {"mean": 9463.416588016315, "dry_mean": 4288.96670020555, "samples": 20000, "seed": 1,
        "depth_m": 60.0}

#: grounds the prior table has a row for, and two it has not
GROUNDS = [("B-L", "pCm"), ("U-M/H", "Qe"), ("CSF-L/M", "pCm"), ("I-L", "Pi"), ("I-L", None),
           ("B-L", "H2O"), ("n/a", "H2O"), (None, None)]


def _ground(name: str, code, glg) -> AreaGround:
    return AreaGround(name, 100, code, glg, 60 if code else 0, 50 if glg else 0)


def _row(name: str, population: float, functional: int, district: str = "") -> dict:
    return {"name": name, "district": district, "population": population,
            "functional_points": functional}


def _config(**allocation) -> Config:
    config = Config()
    for key, value in allocation.items():
        setattr(config.allocation, key, value)
    return config


def _cost_of(code, glg, access=0.0, config=None) -> float:
    p = prior_odds(code, glg, config).probability
    return round(COST["mean"] + COST["dry_mean"] * ((1.0 - p) / p) + access / p, 2)


# ----------------------------------------------------------- the geometry

def test_points_in_ring_answers_as_point_in_ring_does():
    """The vectorised crossing count is the one-point one, point by point,
    on the bundled chiefdom rings and on points placed on their vertices."""
    rng = np.random.default_rng(5)
    for poly in load_chiefdom_polys()[:40]:
        ring = poly.rings[0]
        x0, y0, x1, y1 = ring[:, 0].min(), ring[:, 1].min(), ring[:, 0].max(), ring[:, 1].max()
        lon = np.concatenate([x0 + (x1 - x0) * rng.random(60), ring[:5, 0]])
        lat = np.concatenate([y0 + (y1 - y0) * rng.random(60), ring[:5, 1]])
        got = points_in_ring(lon, lat, ring)
        want = [point_in_ring(float(a), float(b), ring) for a, b in zip(lon, lat, strict=True)]
        assert got.tolist() == want
    assert points_in_ring(np.array([0.0]), np.array([0.0]), np.zeros((1, 2))).tolist() == [False]


def test_every_area_on_the_bundled_layers_has_a_ground():
    """Every chiefdom and every district is read, has points inside it, and
    lands on a class the prior table has a row for; the coastal ones on the
    unconsolidated sediments."""
    chiefdoms = AL.area_grounds("chiefdom")
    districts = AL.area_grounds("district")
    assert set(chiefdoms) == {p.name for p in load_chiefdom_polys()}
    assert set(districts) == set(load_district_population())
    for ground in list(chiefdoms.values()) + list(districts.values()):
        assert ground.samples > 0 and ground.bgs_code is not None, ground
        assert 0 < ground.unit_samples <= ground.class_samples <= ground.samples
    assert districts["Bonthe"].bgs_code == "U-M/H" and districts["Bonthe"].glg == "Qe"
    assert districts["Kono"].bgs_code == "B-L"
    # read once a process, handed out as a copy
    assert AL.area_grounds("district") is not districts
    with pytest.raises(ValueError):
        AL.area_grounds("province")


def _square(x0, y0, x1, y1):
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]], dtype=float)


def _units(*specs):
    out = []
    for glg, ring, holes in specs:
        unit = SimpleNamespace(glg=glg, ring=ring, holes=tuple(holes))
        out.append((unit, AL.ring_bbox(ring)))
    return out


def test_the_ground_is_the_class_covering_most_of_the_area():
    """Read at the grid: the class over most of the points inside the area,
    surface water and ground off the map left out, a hole in a unit not on
    it, and a tie to the code first in alphabetical order."""
    area = SimpleNamespace(rings=[_square(0, 0, 4, 4)], holes=[[_square(3, 3, 4, 4)]])
    aquifers = _units(("U-M/H", _square(0, 0, 1, 4), []),     # 4 of 16 columns
                      ("n/a", _square(1, 0, 3, 4), []),       # the most, but water
                      ("B-L", _square(3, 0, 4, 3), []))       # 3 of 4, the hole off it
    units = _units(("Qe", _square(0, 0, 2, 4), [_square(0, 0, 1, 1)]))
    g = AL.area_ground("A", [area], aquifers, units, 4)
    # 16 points less the one in the area's hole
    assert g.samples == 15
    assert (g.bgs_code, g.class_samples) == ("U-M/H", 4)
    # the unit's hole leaves one of the class's points on no unit
    assert (g.glg, g.unit_samples) == ("Qe", 3)
    tie = AL.area_ground("T", [SimpleNamespace(rings=[_square(0, 0, 2, 1)], holes=[[]])],
                         _units(("U-M/H", _square(1, 0, 2, 1), []), ("B-L", _square(0, 0, 1, 1), [])),
                         _units(), 2)
    assert (tie.bgs_code, tie.glg, tie.unit_samples) == ("B-L", None, 2)
    water = AL.area_ground("W", [area], _units(("n/a", _square(0, 0, 4, 4), [])), units, 4)
    assert water.samples == 15 and water.bgs_code is None
    assert AL.area_ground("E", [], aquifers, units, 4).samples == 0


# ----------------------------------------------------------- the candidates

def test_unserved_people_and_the_boreholes_they_justify():
    rows = [_row("A", 10_499.9, 20), _row("B", 10_000.0, 20), _row("C", 1_234.6, 0),
            _row("D", 99.0, 1)]
    grounds = {r["name"]: _ground(r["name"], "B-L", "pCm") for r in rows}
    a = allocate(rows, 1.0, COST, level="district", grounds=grounds)
    by = {c.id: c for c in a.candidates}
    assert (by["A"].unserved, by["A"].boreholes) == (499, 1)
    assert (by["B"].unserved, by["B"].boreholes, by["B"].reason) == (0, 0, "unserved")
    assert (by["C"].unserved, by["C"].boreholes) == (1234, 3)
    assert by["D"].unserved == 0
    # each borehole serves the figure, the last the remainder
    assert [AL._served(1234, 500, k) for k in (1, 2, 3)] == [500, 500, 234]
    # a district's own district is not repeated
    assert all(c.district == "" for c in a.candidates)


def test_a_working_borehole_costs_its_dry_attempts_and_access_per_attempt():
    rows = [_row("A", 5000.0, 0)]
    grounds = {"A": _ground("A", "CSF-L/M", "pCm")}
    a = allocate(rows, 1e6, COST, level="chiefdom", access={"A": 700.0}, grounds=grounds)
    cand = a.candidates[0]
    p = cand.odds.probability
    assert 0.0 < p < 1.0
    # to the cent
    assert cand.cost_usd == round(COST["mean"] + COST["dry_mean"] * ((1.0 - p) / p) + 700.0 / p, 2)
    assert a.access_areas == 1


def test_odds_are_unknown_where_the_ground_has_no_prior_of_its_own():
    """No class, surface water only, or no area on the map: left out, never
    given the fallback's even chance."""
    rows = [_row("A", 5000.0, 0), _row("B", 5000.0, 0), _row("C", 5000.0, 0)]
    grounds = {"A": _ground("A", None, None), "B": _ground("B", "n/a", "H2O")}
    a = allocate(rows, 1e6, COST, level="district", grounds=grounds)
    assert [(c.id, c.reason, c.odds, c.cost_usd) for c in a.candidates] == [
        ("A", "odds", None, None), ("B", "odds", None, None), ("C", "odds", None, None)]
    assert a.items == 0 and a.boreholes == 0 and a.cheapest is None
    text = allocation_text(a)
    assert text[1].startswith("No area has both unserved people")


# -------------------------------------------------------------- the choice

def _brute(candidates, budget, per):
    """The most people any counts of boreholes within the budget serve."""
    eligible = [c for c in candidates if c.eligible]
    ranges = [range(0, min(c.boreholes, int(budget // c.cost_usd)) + 1) for c in eligible]
    best = 0
    for counts in itertools.product(*ranges):
        cost = sum(k * c.cost_usd for k, c in zip(counts, eligible, strict=True))
        if cost <= budget * (1 + 1e-12):
            best = max(best, sum(min(per * k, c.unserved) for k, c in zip(counts, eligible, strict=True)))
    return best


def _small_case(seed: int):
    rng = random.Random(seed)
    names = rng.sample(["Bo", "Kono", "Bonthe", "Kambia", "Moyamba", "Falaba"], rng.randint(2, 5))
    rows, grounds, access = [], {}, {}
    for name in names:
        rows.append(_row(name, rng.choice([0.0, 250.0, 700.0, 1200.0, 1600.0, 2100.0]) + 37.0 * rng.random(),
                         rng.randint(0, 1)))
        grounds[name] = _ground(name, *rng.choice(GROUNDS[:6]))
        if rng.random() < 0.4:
            access[name] = rng.choice([0.0, 500.0, 2500.0])
    return rows, grounds, access, rng.choice([8000.0, 19000.0, 31000.0, 47000.0, 90000.0])


@pytest.mark.parametrize("seed", range(30))
def test_the_exact_choice_serves_the_most_people_any_choice_does(seed):
    rows, grounds, access, budget = _small_case(seed)
    a = allocate(rows, budget, COST, level="district", access=access, grounds=grounds)
    assert a.method == "exact" and a.items <= 40
    assert a.people == _brute(a.candidates, budget, 500)
    assert a.cost_usd <= budget and a.left_usd == budget - a.cost_usd
    assert a.people <= a.bound
    assert sum(c.chosen_usd for c in a.candidates) == pytest.approx(a.cost_usd, rel=1e-12)


def test_the_greedy_choice_is_held_to_its_bound_and_to_the_exact_one():
    """On one instance chosen both ways: the greedy choice serves no more
    than the exact one, which serves no more than the bound."""
    rng = random.Random(11)
    rows, grounds = [], {}
    for k in range(12):
        name = f"Area {k:02d}"
        rows.append(_row(name, 60.0 + 900.0 * rng.random(), 0))
        grounds[name] = _ground(name, *rng.choice(GROUNDS[:4]))
    budget = 160_000.0
    greedy = allocate(rows, budget, COST, level="district", grounds=grounds,
                      config=_config(people_per_borehole=50, exact_max_items=10))
    exact = allocate(rows, budget, COST, level="district", grounds=grounds,
                     config=_config(people_per_borehole=50, exact_max_items=400))
    assert greedy.method == "greedy" and exact.method == "exact" and greedy.items == exact.items > 10
    assert greedy.people <= exact.people <= greedy.bound == exact.bound
    assert greedy.cost_usd <= budget and exact.cost_usd <= budget
    text = allocation_text(greedy)
    assert any(t.startswith("No set of boreholes within the budget can serve more than") for t in text)


def test_a_tie_goes_to_the_area_first_in_alphabetical_order():
    """Two areas alike in every way and a budget for one borehole: the one
    first in alphabetical order, given in either order, both ways."""
    rows = [_row("Kono", 1000.0, 0), _row("Bo", 1000.0, 0)]
    grounds = {"Bo": _ground("Bo", "B-L", "pCm"), "Kono": _ground("Kono", "B-L", "pCm")}
    one = _cost_of("B-L", "pCm") * 1.5
    for limit in (40, 0):
        for order in (rows, rows[::-1]):
            a = allocate(order, one, COST, level="district", grounds=grounds,
                         config=_config(exact_max_items=limit))
            assert [(c.id, c.chosen) for c in a.candidates] == [("Bo", 1), ("Kono", 0)]
            assert a.method == ("exact" if limit else "greedy")


def test_each_area_is_in_or_out_with_its_reason():
    per_borehole = _cost_of("U-M/H", "Qe")
    rows = [_row("Wet", 1100.0, 0), _row("Dry", 900.0, 0), _row("Served", 400.0, 1),
            _row("Unknown", 900.0, 0), _row("Zed", 600.0, 0)]
    grounds = {"Wet": _ground("Wet", "U-M/H", "Qe"), "Dry": _ground("Dry", "B-L", "pCm"),
               "Served": _ground("Served", "B-L", "pCm"), "Unknown": _ground("Unknown", "n/a", None),
               "Zed": _ground("Zed", "U-M/H", "Qe")}
    budget = 2.5 * per_borehole
    a = allocate(rows, budget, COST, level="district", grounds=grounds)
    by = {c.id: c for c in a.candidates}
    # Wet's two full boreholes are the best per dollar (Zed's first is as
    # good, and Wet comes first in alphabetical order); its third serves 100
    assert (by["Wet"].chosen, by["Wet"].reason) == (2, "part")
    assert by["Zed"].reason == "budget" and by["Dry"].reason == "value"
    assert by["Served"].reason == "unserved" and by["Unknown"].reason == "odds"
    # the chosen first, then by people per dollar, then those left out
    assert [c.id for c in a.candidates] == ["Wet", "Zed", "Dry", "Unknown", "Served"]
    why = {row[0]: row[-1] for row in allocation_rows(a)}
    assert why["Wet"].startswith("In: 2 of the 3 boreholes")
    assert why["Zed"].startswith("Out: a working borehole here costs US$")
    assert why["Dry"].startswith("Out: lower value per dollar")
    assert why["Served"] == ("Out: no unserved people; at 500 people a point, its 1 functional mapped "
                             "point covers its population.")
    assert why["Unknown"].startswith("Out: the odds are unknown")
    # everything justified and affordable: all of them
    full = allocate(rows[:1], 10 * per_borehole, COST, level="district", grounds=grounds)
    assert full.candidates[0].reason == "all" and full.marginal is None
    assert allocation_rows(full)[0][-1] == "In: all 3 boreholes its unserved people justify."


def test_the_next_borehole_is_the_marginal_cost_per_extra_person():
    per_borehole = _cost_of("U-M/H", "Qe")
    rows = [_row("Wet", 1100.0, 0), _row("Dry", 900.0, 0)]
    grounds = {"Wet": _ground("Wet", "U-M/H", "Qe"), "Dry": _ground("Dry", "B-L", "pCm")}
    a = allocate(rows, 1.5 * per_borehole, COST, level="district", grounds=grounds)
    m = a.marginal
    # the next of Wet's (500 more people) beats Dry's first per dollar
    assert (m.area, m.people) == ("Wet", 500)
    assert m.usd_per_person == m.cost_usd / 500 and m.more_usd == m.cost_usd - a.left_usd > 0
    line = next(t for t in allocation_text(a) if t.startswith("The next borehole"))
    assert "Wet" in line and "500 more people" in line


def test_a_budget_that_buys_nothing_says_what_the_cheapest_costs():
    rows = [_row("Wet", 1100.0, 0)]
    grounds = {"Wet": _ground("Wet", "U-M/H", "Qe")}
    a = allocate(rows, 100.0, COST, level="district", grounds=grounds)
    assert a.boreholes == 0 and a.items == 0 and a.candidates[0].reason == "budget"
    text = allocation_text(a)
    assert text[1].startswith("Within US$ 100, no working borehole can be bought: the cheapest, in Wet")
    assert not any(t.startswith("The choice is") for t in text)


# --------------------------------------------------------------- refusals

@pytest.mark.parametrize("budget", [0.0, -5.0, math.nan, math.inf, "100", True])
def test_a_budget_that_is_not_an_amount_is_refused(budget):
    with pytest.raises(ValueError):
        allocate([_row("A", 900.0, 0)], budget, COST, level="district", grounds={})


@pytest.mark.parametrize("change", [
    {"rows": [_row("A", 900.0, 0), _row("A", 800.0, 0)]},
    {"rows": [_row("", 900.0, 0)]},
    {"rows": [_row("A", math.nan, 0)]},
    {"rows": [_row("A", 900.0, -1)]},
    {"rows": [_row("A", 900.0, 1.5)]},
    {"access": {"A": -1.0}},
    {"access": {"A": math.inf}},
    {"cost": dict(COST, mean=0.0)},
    {"cost": dict(COST, dry_mean=-1.0)},
    {"cost": dict(COST, samples=0)},
    {"level": "province"},
    {"config": _config(people_per_borehole=0)},
    {"config": _config(people_per_borehole=500.5)},
    {"config": _config(exact_max_items=-1)},
    {"config": _config(ground_grid=0)},
    {"config": _config(exact_max_items=400)},
])
def test_what_cannot_be_chosen_from_is_refused(change):
    args = {"rows": [_row("A", 900.0, 0)], "cost": COST, "level": "district", "access": {},
            "config": None, **change}
    with pytest.raises(ValueError):
        allocate(args["rows"], 50_000.0, args["cost"], level=args["level"], access=args["access"],
                 config=args["config"], grounds={"A": _ground("A", "B-L", "pCm")})


# ------------------------------------------------------------------ words

def test_the_text_says_what_the_people_served_leave_out():
    rows = [_row("Wet", 1100.0, 0)]
    grounds = {"Wet": _ground("Wet", "U-M/H", "Qe")}
    a = allocate(rows, 50_000.0, COST, level="chiefdom", grounds=grounds)
    text = allocation_text(a) + allocation_basis_text(a)
    assert any("too coarse for access distances" in t and "6.2" in t for t in allocation_text(a))
    assert any(t.startswith("Access is not modelled") for t in text)
    handpump = next(c for c in load_service_classes() if c.max_people_per_point == 500)
    assert any(handpump.basis in t for t in text)
    assert any("calibration: the toolkit's provisional default" in t for t in text)
    assert any("over 20,000 sampled boreholes (seed 1)" in t and "60 m" in t for t in text)
    other = allocate(rows, 50_000.0, COST, level="chiefdom", grounds=grounds,
                     config=_config(people_per_borehole=300))
    assert any("as allocation.people_per_borehole is set" in t for t in allocation_basis_text(other))


def test_the_csv_carries_the_table_and_then_the_sentences():
    rows = [_row("Wet, \"East\"", 1100.0, 0, "Bonthe"), _row("Dry", 900.0, 0, "Bo")]
    grounds = {"Wet, \"East\"": _ground("Wet, \"East\"", "U-M/H", "Qe"), "Dry": _ground("Dry", "B-L", "pCm")}
    a = allocate(rows, 50_000.0, COST, level="chiefdom", grounds=grounds)
    lines = allocation_csv(a).split("\n")
    assert lines[0].startswith("Area,District,Unserved people,Ground,")
    assert lines[1].startswith('"Wet, ""East""",Bonthe,"1,100",')
    blank = lines.index("")
    assert blank == 3
    assert lines[blank + 1:-1] == [AL._csv_field(t) for t in allocation_text(a) + allocation_basis_text(a)]
    assert lines[-1] == ""


# ------------------------------------------- the browser's engine, held to it

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js', 'support.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const input = JSON.parse(readFileSync(0, 'utf8'));
const grounds = {};
for (const level of ['district', 'chiefdom']) grounds[level] = C.areaGrounds(level);
const cases = input.map((c) => {
  try {
    const cfg = C.withConfig({ allocation: c.allocation });
    const a = C.allocate(c.rows, c.budget, c.cost, { level: c.level, access: c.access, config: cfg,
      grounds: c.grounds || undefined });
    return { ok: {
      summary: {
        method: a.method, items: a.items, boreholes: a.boreholes, areas: a.areas, cost: a.cost_usd,
        left: a.left_usd, people: a.people, attempts: a.attempts, bound: a.bound,
        least: a.least_ratio, marginal: a.marginal,
        chosen: a.candidates.map((x) => [x.id, x.unserved, x.boreholes, x.chosen, x.people, x.reason,
          x.cost_usd]),
      },
      csv: C.allocationCsv(a),
    } };
  } catch (e) {
    return { threw: String(e && e.message || e) };
  }
});
process.stdout.write(JSON.stringify({ grounds, cases }));
"""


def _summary(a) -> dict:
    return {
        "method": a.method, "items": a.items, "boreholes": a.boreholes, "areas": a.areas,
        "cost": a.cost_usd, "left": a.left_usd, "people": a.people, "attempts": a.attempts,
        "bound": a.bound, "least": a.least_ratio,
        "marginal": dataclasses.asdict(a.marginal) if a.marginal is not None else None,
        "chosen": [[c.id, c.unserved, c.boreholes, c.chosen, c.people, c.reason, c.cost_usd]
                   for c in a.candidates],
    }


def _vm_cases() -> list:
    """Small cases on given grounds (the exact choice), and the ranking's own
    areas on the bundled layers at several budgets (the greedy one)."""
    cases = []
    for seed in range(30):
        rows, grounds, access, budget = _small_case(seed)
        cases.append({"rows": rows, "budget": budget, "cost": COST, "level": "district",
                      "access": access, "allocation": {},
                      "grounds": {k: dataclasses.asdict(v) for k, v in grounds.items()}})
    districts = load_district_population()
    chiefdoms = chiefdom_population()[0]
    crosswalk = load_chiefdom_district()
    for seed in range(8):
        rng = random.Random(100 + seed)
        level = "chiefdom" if seed % 2 else "district"
        base = chiefdoms if level == "chiefdom" else districts
        rows = [_row(name, people * (1.0 + 0.2 * rng.random()), int(people / (250 + 1500 * rng.random())),
                     crosswalk.get(name, "") if level == "chiefdom" else name)
                for name, people in base.items()]
        access = {r["name"]: round(3000 * rng.random(), 2) for r in rows if rng.random() < 0.15}
        allocation = {} if seed < 6 else {"people_per_borehole": 300, "exact_max_items": 300}
        cases.append({"rows": rows, "budget": [9000.0, 61000.0, 250000.0, 1.5e6][seed % 4],
                      "cost": COST, "level": level, "access": access, "allocation": allocation,
                      "grounds": None})
    # names whose order by code point is not their order by UTF-16 code unit
    letters = [_row(name, 1000.0, 0) for name in ("\uff71 Area", "\U0001d4b5 Area", "\u00d1doye")]
    for limit in (40, 0):
        cases.append({"rows": letters, "budget": 30000.0, "cost": COST, "level": "district", "access": {},
                      "allocation": {"exact_max_items": limit},
                      "grounds": {r["name"]: dataclasses.asdict(_ground(r["name"], "U-M/H", "Qe"))
                                  for r in letters}})
    # and a few refused
    cases.append({"rows": [_row("A", 900.0, 0)], "budget": 0.0, "cost": COST, "level": "district",
                  "access": {}, "allocation": {}, "grounds": {}})
    cases.append({"rows": [_row("A", 900.0, 0)], "budget": 9e4, "cost": COST, "level": "district",
                  "access": {"A": -1.0}, "allocation": {}, "grounds": {}})
    return cases


def _python(case: dict) -> dict:
    config = Config()
    for key, value in case["allocation"].items():
        setattr(config.allocation, key, value)
    grounds = (None if case["grounds"] is None
               else {k: AreaGround(**v) for k, v in case["grounds"].items()})
    try:
        a = allocate(case["rows"], case["budget"], case["cost"], level=case["level"],
                     access=case["access"], config=config, grounds=grounds)
    except ValueError:
        return {"threw": True}
    return {"ok": {"summary": _summary(a), "csv": allocation_csv(a)}}


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path_factory.mktemp("allocation") / "allocation.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS)], input=json.dumps(_vm_cases()),
                          capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


def test_the_browser_reads_the_same_ground(browser):
    for level in AL.LEVELS:
        assert browser["grounds"][level] == {
            k: dataclasses.asdict(v) for k, v in AL.area_grounds(level).items()}


def test_the_browser_chooses_the_same_boreholes(browser):
    cases = _vm_cases()
    methods = set()
    for case, got in zip(cases, browser["cases"], strict=True):
        want = _python(case)
        if "threw" in want:
            assert "threw" in got
            continue
        assert "threw" not in got, got.get("threw")
        # the expected attempts divide by the odds, whose logarithms the
        # engines need not round alike; every cost is to the cent, so the
        # choice and everything printed are held exactly
        attempts = got["ok"]["summary"].pop("attempts")
        assert attempts == pytest.approx(want["ok"]["summary"].pop("attempts"), rel=1e-9)
        assert got["ok"] == want["ok"]
        methods.add(want["ok"]["summary"]["method"])
    assert methods == {"exact", "greedy"}

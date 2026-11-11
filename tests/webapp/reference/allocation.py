"""Where to drill next, within a budget (PLAN.md step 6.1): the "allocation"
entry of ``reference.json``.
"""

from __future__ import annotations

import dataclasses

from groundwater.config import Config
from groundwater.costing import CostingInputs

from .calibration import IN_FORCE_SET
from .common import clean


# ------------------------------------------ where to drill next (step 6.1)

#: grounds the prior table has a row of its own for, a class with no unit,
#: surface water and no class at all
ALLOCATION_GROUNDS = [("B-L", "pCm"), ("U-M/H", "Qe"), ("CSF-L/M", "pCm"), ("I-L", "Pi"),
                      ("I-L", None), ("B-L", "H2O"), ("n/a", "H2O"), (None, None)]


def _allocation_case(name: str, rows: list, budget, cost: dict, level: str, *, access=None,
                     allocation=None, grounds=None, set_=None) -> dict:
    """One choice as both engines are asked for it, and what Python made of
    it: the figures, the sentences, the table and the CSV, or the refusal."""
    from groundwater import allocation as AL
    from groundwater import calibration_sets as CS

    config = Config()
    for key, value in (allocation or {}).items():
        setattr(config.allocation, key, value)
    if set_ is not None:
        config = CS.apply_set(config, set_)
    try:
        a = AL.allocate(rows, budget, cost, level=level, access=access or {}, config=config,
                        grounds=None if grounds is None
                        else {k: AL.AreaGround(**v) for k, v in grounds.items()})
    except ValueError as exc:
        expect = {"refused": str(exc)}
    else:
        expect = {
            "summary": {
                "method": a.method, "items": a.items, "boreholes": a.boreholes, "areas": a.areas,
                "cost": a.cost_usd, "left": a.left_usd, "people": a.people, "attempts": a.attempts,
                "bound": a.bound, "least": a.least_ratio,
                "marginal": dataclasses.asdict(a.marginal) if a.marginal is not None else None,
                "candidates": [[c.id, c.district, c.unserved, c.boreholes, c.chosen, c.people,
                                c.reason, c.cost_usd, c.access_usd] for c in a.candidates],
            },
            # the CSV is the table and then the sentences, word for word
            "header": AL.allocation_header(a), "csv": AL.allocation_csv(a),
        }
    return clean({"name": name, "rows": rows, "budget": budget, "cost": cost, "level": level,
                  "access": access or {}, "allocation": allocation or {}, "grounds": grounds,
                  "set": set_, "expect": expect})


def allocation_reference() -> dict:
    """Where to drill next, within a budget (PLAN.md step 6.1): the ground
    of every district and chiefdom as the grid reads it; small choices on
    given ground, which the exact choice settles; areas alike in all but
    their names, both ways; the ranking's own areas on the bundled layers at
    budgets that buy nothing, a few boreholes and many, which the greedy
    choice settles, with access costs typed for some; the same under a
    calibration set in force and under other settings; and the refusals."""
    import random

    from groundwater import allocation as AL
    from groundwater.costing import sample_cost
    from groundwater.coverage import (
        chiefdom_coverage_rows, chiefdom_population, coverage_rows, load_chiefdom_district,
        load_district_population,
    )

    spread = sample_cost(CostingInputs(total_depth_m=60.0, mobilisation_distance_km=100.0))
    cost = {"mean": spread.mean, "dry_mean": spread.dry_mean, "samples": spread.samples,
            "seed": spread.seed, "depth_m": spread.depth_m}
    deep = sample_cost(CostingInputs(total_depth_m=85.0, mobilisation_distance_km=40.0), vat_percent=15.0)
    deep_cost = {"mean": deep.mean, "dry_mean": deep.dry_mean, "samples": deep.samples,
                 "seed": deep.seed, "depth_m": deep.depth_m}

    def ground(name, code, glg):
        return {"area": name, "samples": 100, "bgs_code": code, "glg": glg,
                "class_samples": 60 if code else 0, "unit_samples": 50 if glg else 0}

    def row(name, population, functional, district=""):
        return {"name": name, "district": district, "population": population,
                "functional_points": functional}

    cases = []
    names = ["Bo", "Kono", "Bonthe", "Kambia", "Moyamba", "Falaba", "Koya (Port Loko)", "Kaffu Bullom"]
    for seed in range(24):
        rng = random.Random(600 + seed)
        chosen = rng.sample(names, rng.randint(2, 6))
        rows, grounds, access = [], {}, {}
        for name in chosen:
            rows.append(row(name, rng.choice([0.0, 250.0, 700.0, 1200.0, 1600.0, 2100.0, 3300.0])
                            + 37.0 * rng.random(), rng.randint(0, 2), "Bonthe"))
            grounds[name] = ground(name, *rng.choice(ALLOCATION_GROUNDS))
            if rng.random() < 0.3:
                access[name] = rng.choice([0.0, 450.0, 2500.0, 0.01])
        level = "chiefdom" if seed % 3 == 0 else "district"
        cases.append(_allocation_case(f"small {seed}", rows, rng.choice([8000.0, 19000.0, 31000.0, 47000.0,
                                                                          90000.0, 150000.0]),
                                      cost if seed % 4 else deep_cost, level, access=access,
                                      grounds=grounds))
    # areas alike in all but their names: the one first in alphabetical
    # order, given in either order, exactly and greedily; and names whose
    # order by code point is not their order by UTF-16 code unit
    twins = [row("Kono", 1000.0, 0), row("Bo", 1000.0, 0), row("Bombali", 1000.0, 0)]
    letters = [row("\uff71 Area", 1000.0, 0), row("\U0001d4b5 Area", 1000.0, 0), row("\u00d1doye", 1000.0, 0)]
    letter_grounds = {r["name"]: ground(r["name"], "U-M/H", "Qe") for r in letters}
    for limit in (40, 0):
        cases.append(_allocation_case(f"letters {limit}", letters, 30000.0, cost, "district",
                                      allocation={"exact_max_items": limit}, grounds=letter_grounds))
    twin_grounds = {r["name"]: ground(r["name"], "B-L", "pCm") for r in twins}
    for limit in (40, 0):
        for order in (twins, twins[::-1]):
            for budget in (16000.0, 33000.0, 1.0e5):
                cases.append(_allocation_case(f"twins {limit} {budget:g} {order[0]['name']}", order, budget,
                                              cost, "district", allocation={"exact_max_items": limit},
                                              grounds=twin_grounds))

    # the ranking's own areas, on the bundled layers
    districts = load_district_population()
    chiefdoms = chiefdom_population()[0]
    crosswalk = load_chiefdom_district()
    for seed in range(6):
        rng = random.Random(700 + seed)
        level = "chiefdom" if seed % 2 else "district"
        base = chiefdoms if level == "chiefdom" else districts
        grown = {name: people * (1.0 + 0.25 * rng.random()) for name, people in base.items()}
        counts = {name: {"total": int(people / 400), "functional": int(people / (250 + 1500 * rng.random()))}
                  for name, people in base.items()}
        ranked = (chiefdom_coverage_rows(grown, counts, crosswalk) if level == "chiefdom"
                  else coverage_rows(grown, counts))
        rows = [row(r.name, r.population, r.functional_points, r.district if level == "chiefdom" else r.name)
                for r in ranked]
        access = {r["name"]: round(3000.0 * rng.random(), 2) for r in rows if rng.random() < 0.15}
        for budget in (61000.0, 1.5e6) if level == "chiefdom" else (9000.0, 61000.0, 1.5e6):
            cases.append(_allocation_case(f"{level} {seed} {budget:g}", rows, budget, cost, level,
                                          access=access if seed % 4 > 1 else {}))
    rows = [row(name, people, int(people / 900)) for name, people in districts.items()]
    cases.append(_allocation_case("in force", rows, 250000.0, cost, "district", set_=IN_FORCE_SET))
    cases.append(_allocation_case("settings", rows, 250000.0, deep_cost, "district",
                                  allocation={"people_per_borehole": 300, "exact_max_items": 300,
                                              "ground_grid": 9}))
    cases.append(_allocation_case("exact on the ranking", rows, 30000.0, cost, "district"))
    # refused
    one = [row("Bo", 900.0, 0)]
    for name, args in [("no budget", dict(budget=0.0)), ("negative access", dict(access={"Bo": -1.0})),
                       ("twice", dict(rows=one + one)), ("table", dict(allocation={"exact_max_items": 400})),
                       ("fraction", dict(allocation={"people_per_borehole": 500.5})),
                       ("free", dict(cost=dict(cost, mean=0.0)))]:
        spec = {"rows": one, "budget": 50000.0, "cost": cost, **args}
        cases.append(_allocation_case(f"refused: {name}", spec["rows"], spec["budget"], spec["cost"], "district",
                                      access=spec.get("access"), allocation=spec.get("allocation"),
                                      grounds={"Bo": ground("Bo", "B-L", "pCm")}))
    return {
        "grounds": {level: {k: dataclasses.asdict(v) for k, v in AL.area_grounds(level).items()}
                    for level in AL.LEVELS},
        "cases": cases,
    }

"""Calibration sets, adopted by a person (PLAN.md step 5.3).

The chance of a working borehole (siting/odds.py) starts from a prior for
the ground under the point, the interpretation (ves/interpret.py) reads its
layers by resistivity edges, and the suitability score (siting/suitability.py)
adds its four parts by weights. All three are provisional judgments. A
calibration set is the same numbers fitted to the boreholes in a pooled
ledger of predictions and outcomes (ledger.py):

- **The prior** for each row of ``success_prior.csv`` (each pairing of a
  BGS aquifer class and a geology unit, or the class on any unit): a
  beta-binomial update of the row's Beta, the provisional rate counting as
  its effective number of boreholes. Each borehole was sited on survey
  evidence that moved its odds (the likelihood ratios of step 3.3), so
  counting its success as the ground's alone would count that evidence
  twice. The count it adds is therefore the one the forecasts expect at
  the rate that, carried through each borehole's own evidence, expects as
  many successes as there were. Where no evidence moved the odds that is
  the count itself, and the update is the plain beta-binomial.
- **The resistivity edges** of each USGS geology unit: the two a drilling
  log can test. ``clay_max_rho`` parts the layers the log calls clay from
  those it calls sand, weathered rock or a fracture zone; saprolite is left
  out, since "clayey saprolite" is saprolite in the class table.
  ``fresh_basement_min_rho`` parts the weathered profile from the basement
  rock. Each layer of the best fit is read as the class of rock that fills
  at least half of it in the log, and an edge goes where it misreads the
  fewest layers. The edge between water-bearing and dry weathered rock, and
  the laterite edge, are not fitted: no class of rock in a log says whether
  weathered rock was dry.
- **The suitability weights**, once enough boreholes have succeeded and
  failed: of the 1,771 ways to weight the four parts in twentieths, the one
  that ranks the most pairs of a success and a failure the right way round.

Every fit starts from the provisional default with every borehole in the
pooled ledger, never from the set in force, so no borehole is counted twice.
A row or edge with fewer than ``ledger.fit_min_boreholes`` boreholes, and
weights without ``ledger.fit_weights_min_each`` successes and failures, are
not fitted, and the set says so. The set records the boreholes it used by
their ledger ids only, so it can be shared without the projects behind it
(step 5.5).

A fitted set changes nothing until a named person adopts it
(:func:`adopt_set`), which numbers it one after the set it replaces. Every
report names the set in force (:func:`set_name`).

Every function here has a twin of the same name in camel case in
gwt-core.js, held to it by parity. The fits use only sums, products,
quotients and square roots, so the two engines agree to the bit.
"""

from __future__ import annotations

import copy
import dataclasses
import math
import numbers
from bisect import bisect_left, bisect_right

import yaml

from .config import Config, VESConfig
from .ledger import SUITABILITY_PARTS, _name
from .text import phrase

__all__ = [
    "EDGES",
    "FORMAT",
    "FORMAT_VERSION",
    "adopt_set",
    "apply_set",
    "check_in_force",
    "clean_set",
    "config_for_sounding",
    "config_for_unit",
    "default_set",
    "evidence_rate",
    "fit_edges",
    "fit_prior",
    "fit_set",
    "fit_weights",
    "fitted_prior",
    "in_force",
    "layer_class",
    "read_set",
    "set_changes",
    "set_name",
    "set_yaml",
    "unit_edges",
]

#: What a set file says it is, and the version of its layout.
FORMAT = "groundwater calibration set"
FORMAT_VERSION = 1

#: The resistivity edges a set fits, in the order it lists them.
EDGES = ("clay_max_rho", "fresh_basement_min_rho")

#: The classes of rock (design/lithology.py) under and over each edge.
_SIDES = {
    "clay_max_rho": (("clay",), ("sand", "weathered", "fracture")),
    "fresh_basement_min_rho": (("clay", "saprolite", "sand", "weathered", "fracture"), ("basement",)),
}

#: The ledger keeps a chance to three places, so one recorded as 0 or 1 is
#: read as half a thousandth from it.
_CHANCE_BOUND = 0.0005
#: A fitted rate is written to four places, and kept that far inside (0, 1).
_RATE_BOUND = 0.0001
#: The weights are fitted in twentieths.
_STEPS = 20


def _round(value: float, digits: int) -> float:
    return round(float(value), digits)


def _uses_definition(outcome: dict, config: Config) -> bool:
    """Whether the borehole was judged at the definition of success in force."""
    judged = outcome["success_yield_m3_per_h"]
    return judged is not None and abs(judged - _round(config.odds.success_yield_m3_per_h, 3)) < 1e-9


def _judged(pooled: list[dict], config: Config) -> tuple[list[dict], dict]:
    """The drilled entries whose success is known at the definition in
    force, and how many drilled entries were left out and why."""
    kept, unknown, definition = [], 0, 0
    for entry in pooled:
        outcome = entry["outcome"]
        if outcome is None:
            continue
        if outcome["success"] is None:
            unknown += 1
        elif not _uses_definition(outcome, config):
            definition += 1
        else:
            kept.append(entry)
    return kept, {"unknown": unknown, "definition": definition}


# --------------------------------------------------------------- the prior

def _factor(odds: dict) -> float | None:
    """How far the survey evidence moved a recorded chance: its odds over
    the odds of the prior it started from."""
    p, q = odds.get("probability"), odds.get("prior")
    if p is None or q is None:
        return None
    p = min(max(p, _CHANCE_BOUND), 1.0 - _CHANCE_BOUND)
    q = min(max(q, _CHANCE_BOUND), 1.0 - _CHANCE_BOUND)
    return (p / (1.0 - p)) / (q / (1.0 - q))


def evidence_rate(factors: list[float], successes: float) -> float:
    """The rate for the ground at which boreholes whose evidence moved their
    odds by ``factors`` would expect ``successes`` successes: by a hundred
    halvings of [0, 1], since the expected count rises with the rate."""
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        expected = 0.0
        for f in factors:
            expected = expected + mid * f / (mid * f + 1.0 - mid)
        if expected < successes:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def fit_prior(pooled: list[dict], config: Config | None = None) -> tuple[list[dict], dict]:
    """The rows of the prior table the boreholes fall in, each fitted where
    it holds ``ledger.fit_min_boreholes``, and each borehole's row.

    A borehole falls in the row its point's recorded ground matches in the
    provisional table: its class and unit, else its class. One whose ground
    matches only the even-chance fallback fits nothing, since no cited rate
    is there to fit. Returns the rows in the table's order, and the ids of
    the boreholes in each fitted row by the row's position.
    """
    from .siting.odds import odds_tables, prior_for

    config = config or Config()
    rate_m3h = float(config.odds.success_yield_m3_per_h)
    judged, _ = _judged(pooled, config)
    table = odds_tables()["prior"]
    members: dict[int, list[tuple[dict, float]]] = {}
    for entry in judged:
        odds = entry["prediction"]["odds"]
        factor = _factor(odds) if odds is not None else None
        if odds is None or not odds["bgs_code"] or factor is None:
            continue
        row = prior_for(odds["bgs_code"], odds["glg"], rate_m3h)
        if row["matched"] == "fallback":
            continue
        k = next(i for i, r in enumerate(table) if r["bgs_code"] == row["bgs_code"] and r["glg"] == row["glg"])
        members.setdefault(k, []).append((entry, factor))
    rows, used = [], {}
    for k, base in enumerate(table):
        if k not in members:
            continue
        entries = [entry for entry, _ in members[k]]
        base_rate = prior_for(base["bgs_code"], base["glg"] if base["glg"] != "*" else None, rate_m3h)["rate"]
        base_n = float(base["effective_n"])
        m = len(entries)
        successes = sum(1 for e in entries if e["outcome"]["success"])
        factors = [factor for _, factor in members[k]]
        expected = m * evidence_rate(factors, successes)
        fitted = m >= int(config.ledger.fit_min_boreholes)
        rate = (base_n * base_rate + expected) / (base_n + m)
        row = {
            "bgs_code": base["bgs_code"],
            "glg": base["glg"],
            "boreholes": m,
            "successes": successes,
            "expected": _round(expected, 2),
            "base_rate": _round(base_rate, 4),
            "base_n": base_n,
            "fitted": fitted,
            "rate": min(max(_round(rate, 4), _RATE_BOUND), 1.0 - _RATE_BOUND) if fitted else None,
            "effective_n": base_n + m if fitted else None,
        }
        if fitted:
            used[len(rows)] = [e["id"] for e in entries]
        rows.append(row)
    return rows, used


# --------------------------------------------------------------- the edges

def layer_class(layer: list, prediction: dict, outcome: dict) -> str | None:
    """The class of rock the log gives a layer of the best fit: the one that
    fills at least half of it, the layer taken down to the log's total depth
    and the sounding's depth of investigation, whichever is shallower, and
    at least a metre thick there. None where no class does."""
    top, bottom, _rho = layer
    total = outcome["total_depth_m"]
    if total is None:
        return None
    end = total
    for limit in (bottom, prediction["investigation_depth_m"]):
        if limit is not None and limit < end:
            end = limit
    span = end - top
    if span < 1.0:
        return None
    overlap: dict[str, float] = {}
    for itop, ibottom, key in outcome["intervals"]:
        lo, hi = max(itop, top), min(ibottom, end)
        if hi > lo:
            overlap[key] = overlap.get(key, 0.0) + (hi - lo)
    best = None
    for key, length in overlap.items():
        if best is None or length > overlap[best]:
            best = key
    if best is None or 2.0 * overlap[best] < span:
        return None
    return best


def _misread(edge: str, value: float, below: list[float], above: list[float]) -> int:
    """How many layers an edge at ``value`` reads as the wrong side. The
    interpretation calls a layer clay at or under ``clay_max_rho`` and fresh
    basement at or over ``fresh_basement_min_rho``."""
    if edge == "clay_max_rho":
        return sum(1 for r in below if r > value) + sum(1 for r in above if r <= value)
    return sum(1 for r in below if r >= value) + sum(1 for r in above if r < value)


def _best_edge(edge: str, base: float, below: list[float], above: list[float], floor: float,
               ceiling: float | None) -> tuple[float, int]:
    """The edge that misreads the fewest layers, among the edge in force and
    the geometric midpoints (to 0.1 ohm-m) of each two resistivities next to
    each other between ``floor`` and ``ceiling``, and how many it misreads.
    A tie goes to the edge nearest the one in force, by ratio, and then to
    the lower, so the edge moves only where it misreads fewer."""
    values = sorted(set(below + above))
    best, best_miss, best_ratio = base, _misread(edge, base, below, above), 1.0
    for a, b in zip(values, values[1:], strict=False):
        c = _round(math.sqrt(a * b), 1)
        if not c > floor or (ceiling is not None and not c < ceiling):
            continue
        miss = _misread(edge, c, below, above)
        ratio = max(c / base, base / c)
        if miss < best_miss or miss == best_miss and (ratio < best_ratio or ratio == best_ratio and c < best):
            best, best_miss, best_ratio = c, miss, ratio
    return best, best_miss


def fit_edges(pooled: list[dict], config: Config | None = None) -> tuple[list[dict], dict]:
    """The resistivity edges of each geology unit the boreholes were drilled
    in, each fitted where ``ledger.fit_min_boreholes`` boreholes give it a
    layer and it has layers on both sides; and the ids of the boreholes
    behind each fitted edge, by its position.

    The unit is the one recorded with the point's odds. The edges in force
    are ``config.ves``'s, or the calibration set in force's for the unit
    where it fitted them; the clay edge stays under the top of the
    water-bearing window and the basement edge over the unit's clay edge.
    Returns the edges by unit, in code-point order, clay first.
    """
    config = config or Config()
    judged, _ = _judged(pooled, config)
    sides: dict[str, dict[str, tuple[list, list, list]]] = {}
    for entry in judged:
        prediction, outcome = entry["prediction"], entry["outcome"]
        odds = prediction["odds"]
        if odds is None or not odds["glg"]:
            continue
        unit = sides.setdefault(odds["glg"], {edge: ([], [], []) for edge in EDGES})
        for layer in prediction["layers"]:
            klass = layer_class(layer, prediction, outcome)
            if klass is None:
                continue
            for edge in EDGES:
                under, over = _SIDES[edge]
                below, above, ids = unit[edge]
                if klass in under:
                    below.append(layer[2])
                elif klass in over:
                    above.append(layer[2])
                else:
                    continue
                if entry["id"] not in ids:
                    ids.append(entry["id"])
    rows, used = [], {}
    base = {"clay_max_rho": float(config.ves.clay_max_rho),
            "fresh_basement_min_rho": float(config.ves.fresh_basement_min_rho)}
    held = in_force(config)
    for glg in sorted(sides):
        here = dict(base, **unit_edges(held, glg))
        clay = here["clay_max_rho"]
        for edge in EDGES:
            below, above, ids = sides[glg][edge]
            if not ids:
                continue
            fitted = len(ids) >= int(config.ledger.fit_min_boreholes) and bool(below) and bool(above)
            row = {"glg": glg, "edge": edge, "boreholes": len(ids), "below": len(below), "above": len(above),
                   "base": here[edge], "misread_base": _misread(edge, here[edge], below, above),
                   "fitted": fitted, "value": None, "misread": None}
            if fitted:
                if edge == "clay_max_rho":
                    value, miss = _best_edge(edge, here[edge], below, above, 0.0,
                                             float(config.ves.fractured_zone_rho[1]))
                    clay = value
                else:
                    value, miss = _best_edge(edge, here[edge], below, above, clay, None)
                row["value"], row["misread"] = value, miss
                used[len(rows)] = list(ids)
            rows.append(row)
    return rows, used


# ------------------------------------------------------------- the weights

def _pairs_right(successes: list[int], failures: list[int]) -> int:
    """Twice the pairs of a success and a failure the scores rank the right
    way round, a tie counting once: the Mann-Whitney count, in halves."""
    ordered = sorted(failures)
    total = 0
    for s in successes:
        lower = bisect_left(ordered, s)
        total += 2 * lower + (bisect_right(ordered, s) - lower)
    return total


def _in_twentieths(weights: dict) -> tuple:
    """Weights in twentieths: whole numbers where they fall on the grid, as
    every fitted set's do, so their scores stay exact."""
    out = []
    for key in SUITABILITY_PARTS:
        k = float(weights[key]) * _STEPS
        out.append(int(round(k)) if abs(k - round(k)) < 1e-9 else k)
    return tuple(out)


def _scores(parts: list[list[int]], weights: tuple) -> list:
    return [weights[0] * p[0] + weights[1] * p[1] + weights[2] * p[2] + weights[3] * p[3] for p in parts]


def fit_weights(pooled: list[dict], config: Config | None = None) -> tuple[dict, list[str]]:
    """The suitability score's weights fitted to the boreholes whose score's
    parts were recorded, and their ids where they were fitted.

    Fitted once ``ledger.fit_weights_min_each`` succeeded and as many
    failed: of the ways to weight the four parts in twentieths, the one that
    ranks the most pairs of a success and a failure the right way round, a
    tie going to the weights nearest those in force and then to the first in
    order. The parts are taken to thousandths, as the ledger keeps them, so
    the scores are whole numbers and the ranking is exact. The weights in
    force are ``config.ves.suitability_weights``: the configuration's, or
    those of the calibration set in force where it fitted them.
    """
    config = config or Config()
    judged, _ = _judged(pooled, config)
    won, lost, ids = [], [], []
    for entry in judged:
        parts = entry["prediction"]["suitability"]
        if parts is None:
            continue
        row = [int(round(parts[key] * 1000)) for key in SUITABILITY_PARTS]
        (won if entry["outcome"]["success"] else lost).append(row)
        ids.append(entry["id"])
    in_use = config.ves.suitability_weights
    base = _in_twentieths(in_use)
    pairs = len(won) * len(lost)
    out = {
        "successes": len(won),
        "failures": len(lost),
        "base": {key: float(in_use[key]) for key in SUITABILITY_PARTS},
        "right_base": _round(_pairs_right(_scores(won, base), _scores(lost, base)) / (2 * pairs), 4)
        if pairs else None,
        "fitted": len(won) >= int(config.ledger.fit_weights_min_each)
        and len(lost) >= int(config.ledger.fit_weights_min_each),
        "value": None,
        "right": None,
    }
    if not out["fitted"]:
        return out, []
    # the first weighting replaces these, since it ranks at least no pairs right
    best, best_right, best_distance = base, -1, 0
    for a in range(_STEPS + 1):
        for b in range(_STEPS + 1 - a):
            for c in range(_STEPS + 1 - a - b):
                weights = (a, b, c, _STEPS - a - b - c)
                right = _pairs_right(_scores(won, weights), _scores(lost, weights))
                distance = sum(abs(w - base[k]) for k, w in enumerate(weights))
                if right > best_right or right == best_right and distance < best_distance:
                    best, best_right, best_distance = weights, right, distance
    out["value"] = {key: best[k] / _STEPS for k, key in enumerate(SUITABILITY_PARTS)}
    out["right"] = _round(best_right / (2 * pairs), 4)
    return out, ids


# ------------------------------------------------------------------ the set

def default_set() -> dict:
    """The set the toolkit ships: step 3.3's provisional tables, step 3.1's
    edges and the suitability score's weights, adopted by no one."""
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "version": 0,
        "fitted_on": "",
        "adopted_by": "",
        "adopted_on": "",
        "replaces": None,
        "success_yield_m3_per_h": None,
        "boreholes": [],
        "left_out": {"unknown": 0, "definition": 0},
        "prior": [],
        "edges": [],
        "weights": None,
    }


def fit_set(pooled: list[dict], fitted_on: str, config: Config | None = None) -> dict:
    """A calibration set fitted to the pooled ledger's boreholes, numbered
    and adopted by no one yet.

    ``pooled`` is :func:`groundwater.ledger.pool_ledgers`'s entries, and
    ``fitted_on`` the date it was fitted, as text. Each borehole it used is
    listed by its ledger id with what it was used for; the drilled points
    whose success is not known, or was judged at another definition of
    success, are counted in ``left_out``.
    """
    config = config or Config()
    _, left_out = _judged(pooled, config)
    prior, prior_ids = fit_prior(pooled, config)
    edges, edge_ids = fit_edges(pooled, config)
    weights, weight_ids = fit_weights(pooled, config)
    uses: dict[str, list[str]] = {}
    for ids in prior_ids.values():
        for pid in ids:
            uses.setdefault(pid, []).append("prior")
    for k, ids in edge_ids.items():
        for pid in ids:
            if edges[k]["edge"] not in uses.setdefault(pid, []):
                uses[pid].append(edges[k]["edge"])
    for pid in weight_ids:
        uses.setdefault(pid, []).append("weights")
    order = {name: k for k, name in enumerate(("prior",) + EDGES + ("weights",))}
    boreholes = []
    for entry in pooled:
        if entry["id"] in uses:
            boreholes.append({"id": entry["id"], "success": entry["outcome"]["success"],
                              "forecast": entry["before_outcome"],
                              "uses": sorted(uses.pop(entry["id"]), key=order.__getitem__)})
    return dict(default_set(), version=None, fitted_on=str(fitted_on),
                success_yield_m3_per_h=_round(config.odds.success_yield_m3_per_h, 3),
                boreholes=boreholes, left_out=left_out, prior=prior, edges=edges, weights=weights)


def adopt_set(candidate: dict, adopted_by: str, adopted_on: str, in_force: dict | None = None) -> dict:
    """``candidate`` adopted by a named person on a date, numbered one after
    the set in force (the provisional default where none is given), which it
    names as the set it replaces. A blank name, or a set adopted already,
    raises ValueError with the sentence the app shows."""
    who = _name(adopted_by)
    if not who:
        raise ValueError(phrase("calibration_sets.adopt_unnamed"))
    if candidate["adopted_by"]:
        raise ValueError(phrase("calibration_sets.adopt_again", by=candidate["adopted_by"],
                                on=candidate["adopted_on"]))
    in_force = in_force or default_set()
    replaces = {"version": in_force["version"], "fitted_on": in_force["fitted_on"],
                "adopted_by": in_force["adopted_by"], "adopted_on": in_force["adopted_on"]}
    return dict(candidate, version=in_force["version"] + 1, adopted_by=who, adopted_on=str(adopted_on),
                replaces=replaces)


def set_name(s: dict) -> str:
    """The set as a report names it: the provisional default, a set numbered
    and adopted by a person, or a set nobody has adopted."""
    if s["version"] == 0:
        return phrase("calibration_sets.name_default")
    n = len(s["boreholes"])
    if s["adopted_by"]:
        return phrase("calibration_sets.name_adopted", version=s["version"], fitted_on=s["fitted_on"], n=n,
                      by=s["adopted_by"], on=s["adopted_on"])
    return phrase("calibration_sets.name_candidate", fitted_on=s["fitted_on"], n=n)


# ------------------------------------------------------------ in force

def in_force(config: Config | None) -> dict:
    """The calibration set in force: the configuration's, else the
    provisional default."""
    held = getattr(config, "calibration", None)
    return held if held is not None else default_set()


def check_in_force(s) -> dict:
    """``s`` as a set to put in force: read whole (:func:`clean_set`), and
    refused with ValueError unless it is the provisional default or a named
    person adopted it. Nothing changes until someone does."""
    s = clean_set(s)
    if s["version"] is None:
        raise ValueError(phrase("calibration_sets.not_adopted"))
    return s


def apply_set(config: Config, s) -> Config:
    """A copy of ``config`` with the set ``s`` in force.

    The copy's ``calibration`` is the set (None for the provisional
    default), and its suitability weights are the set's where it fitted
    them. A set that fits none leaves the configuration's weights, or the
    toolkit's where the set it replaces had put its own in force. The
    priors and the edges are read from ``calibration`` where they are used
    (:func:`fitted_prior`, :func:`config_for_sounding`).
    """
    s = check_in_force(s)
    out = copy.deepcopy(config)
    previous = in_force(config)["weights"]
    if s["weights"] is not None and s["weights"]["fitted"]:
        out.ves.suitability_weights = dict(s["weights"]["value"])
    elif previous is not None and previous["fitted"]:
        out.ves.suitability_weights = dict(VESConfig().suitability_weights)
    out.calibration = None if s["version"] == 0 else s
    return out


def fitted_prior(s: dict, bgs_code: str, glg: str, success_yield_m3_per_h: float) -> dict | None:
    """The set's fitted row for the prior table's row ``bgs_code`` and
    ``glg`` (``*`` for a class's row), or None. A set fitted at another
    definition of success fits nothing here, since its rates are the shares
    that reached its yield, not this one."""
    judged = s["success_yield_m3_per_h"]
    if judged is None or abs(judged - _round(success_yield_m3_per_h, 3)) >= 1e-9:
        return None
    return next((row for row in s["prior"] if row["fitted"] and row["bgs_code"] == bgs_code
                 and row["glg"] == glg), None)


def unit_edges(s: dict, glg: str | None) -> dict:
    """The resistivity edges the set fitted for a geology unit, by name."""
    return {row["edge"]: float(row["value"]) for row in s["edges"] if row["fitted"] and row["glg"] == glg}


def config_for_unit(config: Config, glg: str | None) -> Config:
    """``config`` with the set in force's edges for a geology unit in its
    VES settings, or ``config`` itself where the set fitted none there."""
    edges = unit_edges(in_force(config), glg)
    if not edges:
        return config
    return dataclasses.replace(config, ves=dataclasses.replace(config.ves, **edges))


def config_for_sounding(config: Config, sounding, zone: int | None = None, fallback=None) -> Config:
    """The configuration a sounding is interpreted with: ``config`` with the
    edges the set in force fitted for the geology unit under the sounding,
    found from its own position (in ``zone``, else its sheet's, else the
    zone its easting implies) or ``fallback``, the site's. Where the set
    fitted no edge, nothing is looked up and ``config`` comes back."""
    if not any(row["fitted"] for row in in_force(config)["edges"]):
        return config
    from types import SimpleNamespace

    from .siting.odds import ground_at, point_latlon

    site = getattr(sounding, "site", None)
    where = SimpleNamespace(site_easting=getattr(site, "easting", None),
                            site_northing=getattr(site, "northing", None))
    _, glg = ground_at(point_latlon(where, zone if zone is not None else getattr(site, "utm_zone", None),
                                    fallback))
    return config_for_unit(config, glg)


def set_changes(s: dict) -> list[str]:
    """What the set changes besides the priors, which each point's prior
    names: the edges it reads each geology unit by, and the suitability
    weights. Nothing for the provisional default or a set that fits
    neither."""
    out = []
    for glg in sorted({row["glg"] for row in s["edges"] if row["fitted"]}):
        edges = unit_edges(s, glg)
        parts = []
        if "clay_max_rho" in edges:
            parts.append(phrase("calibration_sets.edge_clay", value=edges["clay_max_rho"]))
        if "fresh_basement_min_rho" in edges:
            parts.append(phrase("calibration_sets.edge_basement", value=edges["fresh_basement_min_rho"]))
        out.append(phrase("calibration_sets.changes_edges", version=s["version"], glg=glg,
                          edges=" and ".join(parts)))
    weights = s["weights"]
    if weights is not None and weights["fitted"]:
        value = weights["value"]
        out.append(phrase("calibration_sets.changes_weights", version=s["version"],
                          thickness=value["aquifer_thickness"], fit=value["resistivity_fit"],
                          overburden=value["overburden"], fracture=value["basal_fracture"]))
    return out


# ------------------------------------------------------------- the file

def _unreadable(why: str) -> ValueError:
    return ValueError(phrase("calibration_sets.unreadable", why=why))


def _is_int(value) -> bool:
    return isinstance(value, numbers.Integral) and not isinstance(value, bool)


def _is_num(value) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _field(raw: dict, key: str, check, where: str = ""):
    """``raw[key]`` where ``check`` passes it, else the reason the file
    cannot be read, naming the field."""
    if not isinstance(raw, dict) or key not in raw or not check(raw[key]):
        raise _unreadable(phrase("calibration_sets.why_field", field=f"{where}{key}"))
    return raw[key]


def _text(value) -> bool:
    return isinstance(value, str)


def _count(value) -> bool:
    return _is_int(value) and value >= 0


def _positive(value) -> bool:
    return _is_num(value) and value > 0


def _rate(value) -> bool:
    return _is_num(value) and 0 < value < 1


def _maybe(check):
    return lambda value: value is None or check(value)


def _flag(value) -> bool:
    return isinstance(value, bool)


def clean_set(raw) -> dict:
    """A set read from a file, in the shape the functions here write, or
    ValueError with the sentence the app shows.

    A set changes what every report predicts, so a file is read whole or
    not at all: a field missing or of the wrong kind refuses the file
    rather than being left blank, and a set numbered as adopted must name
    who adopted it.
    """
    if not isinstance(raw, dict):
        raise _unreadable(phrase("calibration_sets.why_not_mapping"))
    if raw.get("format") != FORMAT or raw.get("format_version") != FORMAT_VERSION \
            or not _is_int(raw.get("format_version")):
        raise _unreadable(phrase("calibration_sets.why_format", expected=FORMAT_VERSION))
    version = _field(raw, "version", _maybe(_count))
    out = {"format": FORMAT, "format_version": FORMAT_VERSION, "version": version}
    for key in ("fitted_on", "adopted_by", "adopted_on"):
        out[key] = _field(raw, key, _text)
    out["adopted_by"] = _name(out["adopted_by"])
    if (version is not None and version > 0) != bool(out["adopted_by"]):
        raise _unreadable(phrase("calibration_sets.why_unadopted"))
    replaces = _field(raw, "replaces", lambda v: v is None or isinstance(v, dict))
    if replaces is not None:
        replaces = {"version": _field(replaces, "version", _count, "replaces."),
                    "fitted_on": _field(replaces, "fitted_on", _text, "replaces."),
                    "adopted_by": _field(replaces, "adopted_by", _text, "replaces."),
                    "adopted_on": _field(replaces, "adopted_on", _text, "replaces.")}
    out["replaces"] = replaces
    out["success_yield_m3_per_h"] = _field(raw, "success_yield_m3_per_h", _maybe(_positive))
    boreholes = []
    for item in _field(raw, "boreholes", lambda v: isinstance(v, list)):
        boreholes.append({
            "id": _field(item, "id", lambda v: isinstance(v, str) and bool(v), "boreholes."),
            "success": _field(item, "success", _flag, "boreholes."),
            "forecast": _field(item, "forecast", _flag, "boreholes."),
            "uses": list(_field(item, "uses", lambda v: isinstance(v, list) and all(
                u in ("prior",) + EDGES + ("weights",) for u in v), "boreholes.")),
        })
    out["boreholes"] = boreholes
    left = _field(raw, "left_out", lambda v: isinstance(v, dict))
    out["left_out"] = {key: _field(left, key, _count, "left_out.") for key in ("unknown", "definition")}
    prior = []
    for row in _field(raw, "prior", lambda v: isinstance(v, list)):
        fitted = _field(row, "fitted", _flag, "prior.")
        prior.append({
            "bgs_code": _field(row, "bgs_code", _text, "prior."),
            "glg": _field(row, "glg", _text, "prior."),
            "boreholes": _field(row, "boreholes", _count, "prior."),
            "successes": _field(row, "successes", _count, "prior."),
            "expected": _field(row, "expected", _is_num, "prior."),
            "base_rate": _field(row, "base_rate", _is_num, "prior."),
            "base_n": _field(row, "base_n", _positive, "prior."),
            "fitted": fitted,
            "rate": _field(row, "rate", _rate if fitted else _maybe(_rate), "prior."),
            "effective_n": _field(row, "effective_n", _positive if fitted else _maybe(_positive), "prior."),
        })
    out["prior"] = prior
    edges = []
    for row in _field(raw, "edges", lambda v: isinstance(v, list)):
        fitted = _field(row, "fitted", _flag, "edges.")
        edges.append({
            "glg": _field(row, "glg", _text, "edges."),
            "edge": _field(row, "edge", lambda v: v in EDGES, "edges."),
            "boreholes": _field(row, "boreholes", _count, "edges."),
            "below": _field(row, "below", _count, "edges."),
            "above": _field(row, "above", _count, "edges."),
            "base": _field(row, "base", _positive, "edges."),
            "misread_base": _field(row, "misread_base", _count, "edges."),
            "fitted": fitted,
            "value": _field(row, "value", _positive if fitted else _maybe(_positive), "edges."),
            "misread": _field(row, "misread", _count if fitted else _maybe(_count), "edges."),
        })
    out["edges"] = edges
    out["weights"] = _clean_weights(_field(raw, "weights", lambda v: v is None or isinstance(v, dict)))
    return out


def _weight_table(value) -> bool:
    return isinstance(value, dict) and all(_is_num(value.get(key)) and value[key] >= 0
                                           for key in SUITABILITY_PARTS)


def _clean_weights(raw: dict | None) -> dict | None:
    if raw is None:
        return None
    fitted = _field(raw, "fitted", _flag, "weights.")
    base = _field(raw, "base", _weight_table, "weights.")
    value = _field(raw, "value", _weight_table if fitted else _maybe(_weight_table), "weights.")
    if value is not None and abs(sum(value[key] for key in SUITABILITY_PARTS) - 1.0) > 1e-9:
        raise _unreadable(phrase("calibration_sets.why_weights"))
    return {
        "successes": _field(raw, "successes", _count, "weights."),
        "failures": _field(raw, "failures", _count, "weights."),
        "base": {key: base[key] for key in SUITABILITY_PARTS},
        "right_base": _field(raw, "right_base", _maybe(_is_num), "weights."),
        "fitted": fitted,
        "value": {key: value[key] for key in SUITABILITY_PARTS} if value is not None else None,
        "right": _field(raw, "right", _is_num if fitted else _maybe(_is_num), "weights."),
    }


def _scalar(value) -> str:
    """One value as the set file writes it: text in double quotes, a whole
    number without a point, any other number as the shortest text that
    reads back to it, which both engines write alike at these sizes."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, numbers.Real):
        x = float(value)
        return str(int(x)) if x.is_integer() else repr(x)
    out = []
    for ch in str(value):
        code = ord(ch)
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif code < 0x20 or 0x7F <= code <= 0x9F:
            out.append(f"\\x{code:02X}")
        elif code in (0x2028, 0x2029, 0xFEFF, 0xFFFE, 0xFFFF) or 0xD800 <= code <= 0xDFFF:
            # YAML breaks a line at the two separators, and refuses the rest
            out.append(f"\\u{code:04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _emit(value, indent: int, lines: list[str]) -> None:
    pad = " " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                _emit(item, indent + 2, lines)
            else:
                lines.append(f"{pad}{key}: " + ("{}" if item == {} else "[]" if item == [] else _scalar(item)))
        return
    for item in value:
        if isinstance(item, dict) and item:
            nested: list[str] = []
            _emit(item, indent + 2, nested)
            lines.append(f"{pad}- " + nested[0][indent + 2:])
            lines.extend(nested[1:])
        else:
            lines.append(f"{pad}- " + _scalar(item))


def set_yaml(s: dict) -> str:
    """The set as its ``calibration.yaml``: block style, the keys in the
    order the set holds them, every text quoted, so the browser writes the
    same file byte for byte and both read it back."""
    lines = ["# A calibration set of the groundwater toolkit (PLAN.md step 5.3)."]
    _emit(s, 0, lines)
    return "\n".join(lines) + "\n"


def read_set(text: str) -> dict:
    """A ``calibration.yaml`` read and checked (:func:`clean_set`)."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise _unreadable(phrase("calibration_sets.why_not_mapping")) from exc
    return clean_set(raw)

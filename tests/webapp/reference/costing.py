"""The cost as a distribution (PLAN.md step 3.4), the value of one more
measurement (3.5), and what an audit of the costing, siting and decision
arithmetic found: the "cost_range", "measurement" and "costing_siting"
entries of ``reference.json``.
"""

from __future__ import annotations

import dataclasses
import math
from types import SimpleNamespace

from groundwater.config import Config
from groundwater.costing import CostingInputs
from groundwater.models import LayeredModel
from groundwater.siting import assess_siting, ranking_tie, suitability_verdict
from groundwater.ves.interpret import interpret_model
from groundwater.ves.model_range import Stream

from .common import clean
from .odds import _odds_dict, _odds_range


# ------------------------------------------- the cost as a distribution (3.4)
#
# Every number the distribution draws is sums, products, quotients and square
# roots of the range of models' generator, so the two engines agree to the
# bit and parity.mjs compares short runs and default runs exactly. The depth
# is drawn from hand-built quantiles shaped like Rokel A's range rather than
# from the range itself: the range's own short run moves by a few parts in a
# million with the BLAS build (RANGE_RTOL), which would move a drawn depth
# across a whole metre now and then and --check with it. The range's
# quantiles are compared on their own, in the ves_range section.

COST_DEPTH = {"sounding_id": "Rokel-shaped", "step_m": 1.0, "cap_m": 41.0,
              "quantiles_m": [24.0, 25.2, 26.1, 26.9, 27.6, 28.2, 28.9, 29.5, 30.0, 30.6,
                              31.2, 31.9, 32.5, 33.2, 34.0, 34.9, 35.8, 36.9, 38.2, 40.1,
                              44.6]}

COST_CASES = {
    "manual, odds, no range": dict(
        inputs={"total_depth_m": 40.0, "mobilisation_distance_km": 100.0},
        p=0.6, sid="VES 1"),
    "design lengths, depth drawn, VAT": dict(
        inputs={"total_depth_m": 36.0, "casing_m": 27.5, "screen_m": 9.0,
                "gravel_interval_m": 24.0, "overburden_m": 18.0, "cement_bags": 6.0,
                "mobilisation_distance_km": 60.0},
        depth=True, p=0.45, sid="A (1)", pct={"vatPercent": 15.0}),
    "no gravel pack, edited rates, no odds": dict(
        inputs={"total_depth_m": 52.0, "casing_m": 43.5, "screen_m": 9.0,
                "gravel_interval_m": 0.0, "mobilisation_distance_km": 25.0,
                "handpumps": 0, "wq_samples": 2},
        depth=True, edits=[["MOB1", 3.0], ["CAS3", 0.0], ["DRL2", 22.0]],
        pct={"overheadsPercent": 10.0, "marginPercent": 0.0, "contingencyPercent": 0.0}),
    "flat catalogue": dict(
        inputs={"total_depth_m": 48.0, "mobilisation_distance_km": 120.0}, flat=True),
    "one sample": dict(inputs={"total_depth_m": 30.0}, samples=1, p=0.7, sid="B"),
    # a stainless rising main (PLAN.md step 7.2): one taken as long as the
    # hole is as long as each depth drawn, one over the intake stays put
    "stainless main as long as the hole, depth drawn": dict(
        inputs={"total_depth_m": 36.0, "mobilisation_distance_km": 60.0,
                "rising_main_material": "stainless steel"}, depth=True, p=0.5, sid="A (1)"),
    "stainless main over the intake, depth drawn": dict(
        inputs={"total_depth_m": 36.0, "mobilisation_distance_km": 60.0,
                "rising_main_material": "stainless steel", "rising_main_m": 24.0},
        depth=True),
    "long odds, few samples": dict(inputs={"total_depth_m": 30.0}, samples=5, p=0.02,
                                   sid="C"),
}

COST_PROGRAMMES = {
    "ten at 60 percent": dict(
        inputs={"total_depth_m": 40.0, "mobilisation_distance_km": 100.0}, n=10, rate=60.0),
    "21 at 35 percent, depth drawn, VAT": dict(
        inputs={"total_depth_m": 36.0, "casing_m": 27.5, "screen_m": 9.0,
                "gravel_interval_m": 24.0, "mobilisation_distance_km": 80.0},
        n=21, rate=35.0, km=22.0, depth=True, pct={"vatPercent": 15.0}),
    "one, certain, flat": dict(inputs={"total_depth_m": 45.0, "mobilisation_distance_km": 150.0},
                               n=1, rate=100.0, flat=True),
    "500 at 5 percent": dict(inputs={"total_depth_m": 40.0}, n=500, rate=5.0, samples=40),
    "ten with a stainless main, depth drawn": dict(
        inputs={"total_depth_m": 40.0, "mobilisation_distance_km": 100.0,
                "rising_main_material": "stainless steel"}, n=10, rate=60.0, depth=True),
}

COST_SHORT = 300


def _cost_rates(spec):
    from groundwater.costing import load_rates

    rates = load_rates()
    if spec.get("flat"):
        rates = [dataclasses.replace(r, min_usd=r.unit_cost_usd, max_usd=r.unit_cost_usd)
                 for r in rates]
    edits = dict(spec.get("edits", []))
    return [r.with_likely(edits[r.code]) if r.code in edits else r for r in rates]


def _cost_pct(spec) -> dict:
    names = {"overheadsPercent": "overheads_percent", "marginPercent": "margin_percent",
             "contingencyPercent": "contingency_percent", "vatPercent": "vat_percent"}
    return {names[k]: v for k, v in spec.get("pct", {}).items()}


def _cost_depth(spec):
    from groundwater.costing import DepthSpread

    return DepthSpread(**COST_DEPTH) if spec.get("depth") else None


def cost_range_reference(short_ranges) -> dict:
    from groundwater.costing import CostingInputs, depth_spread, load_rates
    from groundwater.costing.distribution import (
        cost_range_header, cost_range_rows, cost_range_text, failures_table,
        programme_range_rows, programme_range_text, sample_cost, sample_programme_cost,
        triangle_quantile,
    )

    def single(spec, samples):
        d = sample_cost(CostingInputs(**spec["inputs"]), _cost_rates(spec),
                        depth=_cost_depth(spec), success_probability=spec.get("p", 1.0),
                        odds_source=spec.get("sid"), samples=samples, **_cost_pct(spec))
        return {"dist": clean(dataclasses.asdict(d)), "text": cost_range_text(d),
                "rows": cost_range_rows(d)}

    def programme(spec, samples):
        d = sample_programme_cost(
            CostingInputs(**spec["inputs"]), spec["n"], rates=_cost_rates(spec),
            success_rate_percent=spec["rate"], inter_site_distance_km=spec.get("km", 15.0),
            depth=_cost_depth(spec), samples=samples, **_cost_pct(spec))
        return {"dist": clean(dataclasses.asdict(d)), "text": programme_range_text(d),
                "rows": programme_range_rows(d)}

    rng = Stream(5, 9)
    triangles = []
    for lo, mode, hi in ((100.0, 150.0, 300.0), (2.25, 2.5, 4.0), (0.0, 0.0, 1.0),
                         (5.0, 9.0, 9.0), (3.0, 3.0, 3.0)):
        for _ in range(4):
            u = rng.uniform()
            triangles.append([lo, mode, hi, u, triangle_quantile(lo, mode, hi, u)])
    tables = []
    for n, p in ((1, 0.4), (3, 0.3), (10, 0.75), (21, 0.35), (500, 0.05), (4, 1.0)):
        first, running = failures_table(n, p)
        tables.append([n, p, first, len(running), running[-1], running[len(running) // 2]])
    # the depth a range hands the costing, from the range's own short run
    spreads = [clean(dataclasses.asdict(depth_spread(SimpleNamespace(
        sounding_id=r["sounding_id"], investigation_depth_m=r["investigation_depth_m"],
        drilling_depth_quantiles_m=r["drilling_depth_quantiles_m"]), Config())))
        for r in short_ranges]
    edits = []
    for code, value in (["MOB1", 3.0], ["CAS3", 0.0], ["DRL2", 22.0]):
        rate = next(r for r in load_rates() if r.code == code)
        edits.append([code, value, list(rate.with_likely(value).triangle())])
    return {
        "short_samples": COST_SHORT,
        "rates": [[r.code, *r.triangle(), r.spread_group] for r in load_rates()],
        "edits": edits,
        "triangles": triangles,
        "failures": tables,
        "depth": COST_DEPTH,
        "depth_draws": [[u, _cost_depth({"depth": True}).draw(u)]
                        for u in (1e-9, 0.03, 0.25, 0.5, 0.77, 0.95, 0.999, 1 - 1e-9)],
        "spreads": spreads,
        "header": cost_range_header(),
        "cases": {name: dict(spec=spec, short=single(spec, spec.get("samples", COST_SHORT)))
                  for name, spec in COST_CASES.items()},
        "default": {name: single(COST_CASES[name], None)
                    for name in ("manual, odds, no range", "design lengths, depth drawn, VAT")},
        "programmes": {name: dict(spec=spec,
                                  short=programme(spec, spec.get("samples", COST_SHORT)))
                       for name, spec in COST_PROGRAMMES.items()},
        "programme_default": {"ten at 60 percent": programme(
            COST_PROGRAMMES["ten at 60 percent"], None)},
    }


# ------------------------------------- the value of one more measurement (3.5)
#
# Each case feeds both engines the same odds, the dicts the odds section
# (odds.py) holds, so what is compared is the preposterior analysis alone: the
# even spread's bisection, the readings, the decision and its words. The
# costs are the default cost distributions' own means. The worked example of
# tests/test_measurement.py, the extremes and the cases where nothing can
# change the decision are among them.

def _odds_object(d: dict):
    """What measurement_value reads of a SuccessOdds, from its dict."""
    return SimpleNamespace(**{**d, "evidence": [SimpleNamespace(**e) for e in d["evidence"]]})


def _measurement_dict(v) -> dict:
    from groundwater.siting.measurement import (
        measurement_basis, measurement_decision_header, measurement_decision_rows,
        measurement_reading_rows, measurement_readings_caption, measurement_summary,
        measurement_text,
    )

    out = clean(dataclasses.asdict(v))
    out["summary"] = measurement_summary(v)
    out["text"] = measurement_text(v)
    out["basis"] = measurement_basis(v)
    out["reading_rows"] = measurement_reading_rows(v)
    out["decision_header"] = measurement_decision_header(v)
    out["decision_rows"] = measurement_decision_rows(v)
    out["readings_caption"] = measurement_readings_caption(v)
    return out


def measurement_reference(odds: dict, cost_range: dict) -> dict:
    from groundwater.siting.measurement import (
        _classes, even_spread, measurement_decision_caption, measurement_reading_header,
        measurement_values, preposterior,
    )

    spreads = []
    for kind, sampled in (("sounding", True), ("profiling", False)):
        for _evidence, bands in _classes(kind, sampled):
            for weight in (1.0, 0.8, 0.6, 0.3):
                spreads.append([r ** weight for _names, r in bands])
    spreads += [[2.0, 0.5], [0.5, 2.0, 2.0, 2.0, 2.0, 2.0], [1.0, 0.9, 0.8], [1.0, 1.0],
                [1.2, 1.5], [0.01, 1.0001], [0.9999, 50.0]]
    example = [[[2.0, 2 / 3, 1 / 3], [0.5, 1 / 3, 2 / 3]]]
    prepost = [[p, q, c, d, example, preposterior(p, q, c, d, example)]
               for p, q, c, d in ((0.6, 0.5, 5000.0, 2000.0), (0.4, 0.5, 5000.0, 2000.0),
                                  (0.5, 0.5, 5000.0, 2000.0), (1e-6, 1 - 1e-6, 4000.0, 3000.0),
                                  (1 - 1e-6, 1e-6, 4000.0, 3000.0))]
    prepost.append([0.6, 0.5, 5000.0, 2000.0, [], preposterior(0.6, 0.5, 5000.0, 2000.0, [])])

    dist = cost_range["default"]["manual, odds, no range"]["dist"]
    completed, dry = dist["mean"], dist["dry_mean"]
    cases = odds["cases"]
    surveys = []
    # every tenth point of the odds section (each kind of point, range and
    # ground among them), against the next one and alone
    for i in range(0, len(cases), 10):
        pair = [cases[i]["odds"], cases[(i + 1) % len(cases)]["odds"]]
        surveys.append({"odds": pair, "ranking": [0, 1]})
        surveys.append({"odds": pair[:1], "ranking": [0]})
    # ranked the other way, and three points, the best odds not second
    surveys.append({"odds": [cases[0]["odds"], cases[3]["odds"], cases[6]["odds"]],
                    "ranking": [2, 0, 1]})
    # a prior near 1 on the coastal sands
    surveys.append({"odds": [odds["low_yield"]["odds"]], "ranking": [0]})
    for survey in surveys:
        objects = [_odds_object(o) for o in survey["odds"]]
        survey["values"] = [_measurement_dict(v) for v in
                            measurement_values(objects, survey["ranking"], completed, dry)]
    return {
        "costs": [completed, dry],
        "spreads": [[r, None if (e := even_spread(r)) is None else list(e)] for r in spreads],
        "preposterior": prepost,
        "surveys": surveys,
        "reading_header": measurement_reading_header(),
        "decision_caption": measurement_decision_caption(),
    }


# ------------------------- costing, siting and the value of a measurement
#
# What an audit of the two engines' costing, siting and decision arithmetic
# found, each held here on the input that showed it. A water zone rounded to
# whole metres took in a slice of the dry cover and the basement, and the
# suitability fit was scored on them. A gap of 2.999999999999993 between two
# weighted scores, and one of 2.96 printed as 3.0, were called within the
# 3-point margin. Equal weighted scores a last bit apart were ranked by the
# last bit, not by sounding id. Two points at the same odds, and a reading
# whose factor is exactly the threshold, were decided by costs a last bit
# apart, the second differently in each engine. A no water, no pay price
# charged every expected failure a whole completed borehole. And the
# browser's cost and programme summary tables rounded a half up where Python
# rounds it to even. Every input is a spec the browser runs through its own
# engine.

#: two points on one 150 ohm-m water layer, the first thicker, as layered
#: models both engines interpret
SITING_WATER_LAYER = [["VES-A", [1500.0, 150.0, 5000.0], [5.4, 14.6 - 5.4]],
                      ["VES-B", [1500.0, 150.0, 5000.0], [5.6, 14.4 - 5.6]]]

#: points with no water zone, scored on their overburden alone, and their
#: confidences: 19.0 x 0.8 and 16.0 x 0.95 are 15.2 a last bit apart
SITING_LAST_BIT = [["VES 2", 38.0, 0.8], ["VES 1", 47.0, 0.95], ["VES 3", None, 1.0]]

#: [first, second] weighted scores (suitability, confidence) and the margin
SITING_GAPS = [[[64.1, 1.0], [61.1, 1.0], 3.0], [[80.0, 1.0], [77.0, 1.0], 3.0],
               [[64.06, 1.0], [61.1, 1.0], 3.0], [[64.04, 1.0], [61.1, 1.0], 3.0],
               [[64.1, 1.0], [61.6, 1.0], 2.5], [[19.0, 0.8], [16.0, 0.95], 3.0],
               [[82.3, 1.0], [79.5, 1.0], 3.0], [[70.0, 0.9], [66.1, 1.0], 3.0]]

#: identical points on the ground and at the water-zone resistivity and fit
#: that sent the client to the second-ranked one, and two that did not
SAME_ODDS = [["B-L", "pCm", 500, 3.0], ["I-L", "Pi", 500, 3.0], ["CSF-L/M", "pCm", 500, 3.0],
             ["CSF-L/M", "pCm", 1500, 25.0], ["U-M/H", "Qe", 120, 15.0],
             ["U-M/H", "Qe", 1500, 7.0], ["B-L", "pCm", 30, 3.0], [None, None, 120, 3.0]]

#: the cost distribution's mean completed borehole and mean dry attempt for
#: a 60 m borehole 50 km out, 60 m on site and 45 m 20 km out
SAME_ODDS_COSTS = [[9060.953887811545, 4288.96670020555],
                   [8658.491187606725, 4288.96670020555],
                   [7891.717914862075, 3630.7302310008904]]

#: single boreholes: depth, one-way distance, VAT; 11 and 13 m have a
#: direct cost on a half
NWNP_ESTIMATES = [[60.0, 0.0, 0.0], [60.0, 40.0, 15.0], [11.0, 0.0, 0.0], [13.0, 0.0, 15.0],
                  [85.0, 120.0, 0.0]]
NWNP_RATES = [100.0, 80.0, 50.0, 35.0, 12.5]

#: programmes: depth, one-way distance, wells, success rate, VAT. Transport
#: at 2.50 USD a km lands on a half for half of all attempt counts
PROGRAMME_ROWS = [[60.0, 40.0, 2, 60.0, 0.0], [60.0, 40.0, 21, 35.0, 0.0],
                  [60.0, 40.0, 5, 60.0, 15.0], [11.0, 40.0, 2, 100.0, 0.0],
                  [13.0, 40.0, 5, 35.0, 15.0], [85.0, 40.0, 21, 60.0, 0.0]]


def _same_ground(sid, rho, err):
    def layer(top, bottom, r, wet):
        return SimpleNamespace(top_m=top, bottom_m=bottom, rho=r, water_bearing=wet)

    return SimpleNamespace(
        sounding_id=sid, water_zones=[(8.0, 30.0)], fit_error_percent=err,
        layers=[layer(0, 8, 400, False), layer(8, 30, rho, True),
                layer(30, float("inf"), 3000, False)])


def _scored_point(sid, suitability, confidence, rank):
    from groundwater.siting import SitingSuitability, SuitabilityComponents

    return SitingSuitability(
        sounding_id=sid, suitability=suitability, grade="Good",
        components=SuitabilityComponents(1.0, 1.0, 1.0, 1.0),
        rationale=f"Driven by {sid}.", rank=rank, confidence=confidence)


def _suit_rows(results) -> list:
    return [[r.sounding_id, clean(r.suitability), r.grade, clean(r.confidence), r.rank,
             clean(r.components.resistivity_fit), r.rationale] for r in results]


def costing_siting_reference() -> dict:
    from groundwater.costing import estimate_borehole_cost, estimate_programme_cost
    from groundwater.mapping import MapPoint, suitability_map_state
    from groundwater.siting import tied_leaders
    from groundwater.siting.measurement import measurement_values
    from groundwater.siting.odds import success_odds
    from groundwater.ves.interpret import rank_interpretations

    layered = []
    for sid, rho, thick in SITING_WATER_LAYER:
        model = LayeredModel(resistivities=rho, thicknesses=thick, fit_error_percent=3.0,
                             sounding_id=sid)
        layered.append(interpret_model(None, model))
    water_layer = {"zones": [[[clean(t), clean(b)] for t, b in i.water_zones] for i in layered],
                   "ranked": _suit_rows(assess_siting(layered))}

    bare = [SimpleNamespace(sounding_id=sid, water_zones=[], layers=[], aquifer_thickness_m=0.0,
                            depth_to_basement_m=dtb, confidence=c, site_easting=None,
                            site_northing=None)
            for sid, dtb, c in SITING_LAST_BIT]
    ranked = assess_siting(bare)
    last_bit = {"ranked": _suit_rows(ranked), "tie": ranking_tie(ranked),
                "preference": [i.sounding_id for i in rank_interpretations(bare)]}

    gaps = []
    for (s1, c1), (s2, c2), within in SITING_GAPS:
        pair = [_scored_point("VES-1", s1, c1, 1), _scored_point("VES-2", s2, c2, 2)]
        points = [MapPoint(label=r.sounding_id, easting=178000.0 + 50 * k, northing=1000000.0,
                           value=round(r.weighted, 1), kind="Good", rank=r.rank)
                  for k, r in enumerate(pair)]
        gaps.append({"tied": tied_leaders(pair, within) is not None,
                     "tie": ranking_tie(pair, within),
                     "verdict": suitability_verdict(pair, within),
                     "map_tie": suitability_map_state(points)["tie"]})

    def odds_pair(code, glg, rho, err):
        return [_odds_dict(success_odds(_same_ground(sid, rho, err), None, code, glg))
                for sid in ("VES-1", "VES-2")]

    same_odds = []
    for code, glg, rho, err in SAME_ODDS:
        pair = odds_pair(code, glg, rho, err)
        completed, dry = SAME_ODDS_COSTS[0]
        values = measurement_values([_odds_object(o) for o in pair], [0, 1], completed, dry)
        same_odds.append({"odds": pair, "values": [_measurement_dict(v) for v in values]})

    ranges = [_odds_range((20.0, 20.0, 20.0), 0.0), _odds_range((3.0, 3.0, 3.0), 0.5)]
    threshold_odds = [_odds_dict(success_odds(_same_ground(sid, rho, 3.0), r, "B-L", "pCm"))
                      for sid, rho, r in (("VES-1", 10, ranges[0]), ("VES-2", 30, ranges[1]))]
    threshold = [[_measurement_dict(v) for v in measurement_values(
        [_odds_object(o) for o in threshold_odds], [0, 1], completed, dry)]
        for completed, dry in SAME_ODDS_COSTS]

    def point(p, sid):
        return {"probability": p, "prior": 0.5, "sounding_id": sid, "range_sampled": False,
                "evidence": [{"key": "fit", "weight": 1.0}]}

    tied_alternatives = [point(0.6, "A"), point(0.4, "B"), point(math.nextafter(0.4, 1.0), "C")]
    alternatives = [_measurement_dict(v) for v in measurement_values(
        [_odds_object(o) for o in tied_alternatives], [0, 1, 2], 5000.0, 2000.0)]

    estimates = []
    for depth, km, vat in NWNP_ESTIMATES:
        e = estimate_borehole_cost(CostingInputs(total_depth_m=depth,
                                                 mobilisation_distance_km=km),
                                   vat_percent=vat)
        estimates.append({
            "dry_attempt_direct_usd": e.dry_attempt_direct_usd,
            "dry_attempt_price_usd": e.dry_attempt_price_usd,
            "price_with_vat_usd": e.price_with_vat_usd,
            "per_successful": [e.price_per_successful_well_usd(r) for r in NWNP_RATES],
            "per_successful_whole": [e.price_per_successful_well_usd(r, e.price_with_vat_usd)
                                     for r in NWNP_RATES],
            "summary_rows": clean(e.summary_rows()),
        })

    # a failure priced below 0, as no number or as text is refused, as is a
    # success rate of 0
    e = estimate_borehole_cost(CostingInputs(total_depth_m=60.0))
    refused = 0
    for rate, failed in ((80.0, -1.0), (80.0, float("nan")), (80.0, float("inf")),
                         (80.0, "5"), (0.0, None)):
        try:
            e.price_per_successful_well_usd(rate, failed)
        except (TypeError, ValueError):
            refused += 1

    programmes = []
    for depth, km, wells, rate, vat in PROGRAMME_ROWS:
        p = estimate_programme_cost(CostingInputs(total_depth_m=depth,
                                                  mobilisation_distance_km=km),
                                    wells, success_rate_percent=rate, vat_percent=vat)
        programmes.append({"dry_attempt_cost_usd": p.dry_attempt_cost_usd,
                           "transport_cost_usd": p.transport_cost_usd,
                           "summary_rows": clean(p.summary_rows())})

    return {
        "specs": {"water_layer": SITING_WATER_LAYER, "last_bit": SITING_LAST_BIT,
                  "gaps": SITING_GAPS, "same_odds": SAME_ODDS,
                  "same_odds_costs": SAME_ODDS_COSTS,
                  "estimates": NWNP_ESTIMATES, "rates": NWNP_RATES,
                  "programmes": PROGRAMME_ROWS},
        "water_layer": water_layer, "last_bit": last_bit, "gaps": gaps,
        "same_odds": same_odds, "threshold_odds": threshold_odds, "threshold": threshold,
        "tied_alternatives": tied_alternatives, "alternatives": alternatives,
        "estimates": estimates, "refused": refused, "programmes": programmes,
    }

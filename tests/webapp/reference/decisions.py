"""One way of reporting uncertainty (PLAN.md step 3.6): the "decisions" entry
of ``reference.json``.
"""

from __future__ import annotations

import dataclasses

from groundwater.config import Config

from .common import _ns
from .costing import COST_DEPTH


# --------------------------------------- one way of reporting uncertainty (3.6)
#
# Every decision number is built from results the other sections already
# hold the two engines to, so here both are handed the same results, as the
# dicts the browser holds and as namespaces Python reads attributes from,
# and every line is compared word for word. The depth is drawn from the
# hand-built quantiles the cost section uses, not the Rokel ranges, whose
# short runs move a few parts in a million with the BLAS build.

def _decision_dict(d) -> dict | None:
    from groundwater.decisions import decision_text

    if d is None:
        return None
    return dict(dataclasses.asdict(d), text=decision_text(d))


#: Hand-built pumping results: a band, one open at the top, a bootstrap
#: withheld, a low end with no yield, no spread at all, and no intake.
DECISION_PUMPING = {
    "banded": {"transmissivity_source": "cooper_jacob",
               "yield_recommendation": {"safe_yield_m3_per_h": 1.25,
                                        "pump_installation_depth_m": 38.4},
               "spread": {"bootstrap": {"method": "cooper_jacob", "p10": 4.1, "reason": ""},
                          "safe_yield_low_m3_per_h": 1.02, "safe_yield_high_m3_per_h": 1.61,
                          "pump_depth_low_m": 37.2, "pump_depth_high_m": 40.1}},
    "open top": {"transmissivity_source": "theis",
                 "yield_recommendation": {"safe_yield_m3_per_h": 0.391,
                                          "pump_installation_depth_m": 52.0},
                 "spread": {"bootstrap": {"method": "theis", "p10": 0.48, "reason": ""},
                            "safe_yield_low_m3_per_h": 0.354, "safe_yield_high_m3_per_h": None,
                            "pump_depth_low_m": 51.0, "pump_depth_high_m": 52.0}},
    "withheld": {"transmissivity_source": "recovery",
                 "yield_recommendation": {"safe_yield_m3_per_h": 3.0,
                                          "pump_installation_depth_m": 25.0},
                 "spread": {"bootstrap": {"method": "recovery", "p10": None,
                                          "reason": "too_few"},
                            "safe_yield_low_m3_per_h": None, "safe_yield_high_m3_per_h": None,
                            "pump_depth_low_m": None, "pump_depth_high_m": None}},
    "no low end": {"transmissivity_source": "papadopulos_cooper",
                   "yield_recommendation": {"safe_yield_m3_per_h": 0.2,
                                            "pump_installation_depth_m": 61.5},
                   "spread": {"bootstrap": {"method": "papadopulos_cooper", "p10": 0.1,
                                            "reason": ""},
                              "safe_yield_low_m3_per_h": None,
                              "safe_yield_high_m3_per_h": 0.3,
                              "pump_depth_low_m": 60.0, "pump_depth_high_m": 63.0}},
    "no spread": {"transmissivity_source": "cooper_jacob",
                  "yield_recommendation": {"safe_yield_m3_per_h": 2.0,
                                           "pump_installation_depth_m": 30.0},
                  "spread": None},
    "no intake": {"transmissivity_source": "cooper_jacob",
                  "yield_recommendation": {"safe_yield_m3_per_h": 2.0,
                                           "pump_installation_depth_m": None},
                  "spread": None},
    "pending": {"transmissivity_source": None,
                "yield_recommendation": {"safe_yield_m3_per_h": None,
                                         "pump_installation_depth_m": None},
                "spread": None},
}


def decisions_reference(odds: dict, cost_range: dict) -> dict:
    from groundwater.decisions import (
        DecisionNumber, cost_decision, decision_numbers, decision_text, depth_decision,
        odds_decision, pump_decision, yield_decision,
    )
    from groundwater.readiness import assess_readiness

    fmt = [DecisionNumber("yield", "Safe yield", "1.25 m3/h", "a band", "", "a basis"),
           DecisionNumber("odds", "Chance", "about 60 percent", None, "no reason given",
                          "a basis", "calibrated")]
    # a range shaped like Rokel A's, one cut back to its depth of
    # investigation everywhere, and none
    ranges = {
        "drawn": {"sounding_id": "P1", "n_samples": 4000, "investigation_depth_m": 41.0,
                  "drilling_depth_quantiles_m": COST_DEPTH["quantiles_m"]},
        "capped": {"sounding_id": "P2", "n_samples": 1200, "investigation_depth_m": 40.0,
                   "drilling_depth_quantiles_m": [40.0] * 21},
        # spread so that the twentieths beside the P10 and the P90 round to
        # other drilling steps: the band is read at the right ones
        "spread": {"sounding_id": "P3", "n_samples": 2000, "investigation_depth_m": 60.0,
                   "drilling_depth_quantiles_m": [10.0, 12.0, 16.0, 21.0, 23.0, 24.0, 25.0,
                                                  26.0, 27.0, 28.0, 29.0, 30.0, 31.0, 32.0,
                                                  33.0, 34.0, 36.0, 39.0, 44.0, 48.0, 52.0]},
        "none": None,
    }
    interps = {
        "P1": {"sounding_id": "P1", "max_drilling_depth_m": 33.0, "basement_not_resolved": False,
               "drilling_depth_capped": False, "rank": 2},
        "P2": {"sounding_id": "P2", "max_drilling_depth_m": 40.0, "basement_not_resolved": True,
               "drilling_depth_capped": True, "rank": 1},
    }
    depth = []
    for interp in interps.values():
        for name, r in ranges.items():
            d = depth_decision(_ns(interp), _ns(r), Config())
            depth.append({"interp": interp, "range": r, "case": name, "d": _decision_dict(d)})
    pumping = []
    for name, a in DECISION_PUMPING.items():
        for at, moved in ((None, None), (44.0, "design"), (55.0, "seasonal"), (38.4, "design")):
            pumping.append({"case": name, "analysis": a, "depth": at, "moved": moved,
                            "yield": _decision_dict(yield_decision(_ns(a))),
                            "pump": _decision_dict(pump_decision(_ns(a), at, moved))})
    odds_cases = [c["odds"] for c in odds["cases"][:6]] + [odds["wider"],
                                                           odds["low_yield"]["odds"]]
    calibrated = dict(odds_cases[0], status="calibrated")
    odds_cases.append(calibrated)
    odds_out = [{"odds": o, "d": _decision_dict(odds_decision(_ns(o)))} for o in odds_cases]
    estimate = {"price_with_vat_usd": 8643.5}
    cost = [{"dist": c["short"]["dist"], "estimate": estimate,
             "d": _decision_dict(cost_decision(_ns(c["short"]["dist"]), _ns(estimate)))}
            for c in cost_range["cases"].values()]
    cost.append({"dist": None, "estimate": estimate,
                 "d": _decision_dict(cost_decision(None, _ns(estimate)))})
    cost.append({"dist": None, "estimate": None, "d": None})

    first_cost = next(iter(cost_range["cases"].values()))["short"]["dist"]
    states = {
        "geophysical, drawn": ("geophysical", {
            "interpretations": list(interps.values()),
            "model_ranges": [ranges["drawn"], ranges["drawn"]],
            "odds": [odds_cases[0], odds_cases[1]]}),
        "geophysical, unsampled": ("geophysical", {
            "interpretations": list(interps.values()), "model_ranges": [None, None],
            "odds": [odds_cases[0], odds_cases[1]]}),
        "geophysical, no odds": ("geophysical", {
            "interpretations": list(interps.values()),
            "model_ranges": [ranges["capped"], ranges["capped"]]}),
        # two points the ranking cannot separate: the report offers both, so
        # it prints and the gate reads the numbers at both, the first-ranked
        # first; the second's range unsampled
        "geophysical, tied": ("geophysical", {
            "interpretations": list(interps.values()),
            "model_ranges": [None, ranges["capped"]],
            "odds": [odds_cases[0], odds_cases[1]], "points": [1, 0]}),
        "geophysical, nothing": ("geophysical", {}),
        "pumping, banded": ("pumping", {"pump_analysis": DECISION_PUMPING["banded"]}),
        "completion, withheld": ("completion", {"pump_analysis": DECISION_PUMPING["withheld"]}),
        "handover, no spread": ("handover", {"pump_analysis": DECISION_PUMPING["no spread"]}),
        "pumping, pending": ("pumping", {"pump_analysis": DECISION_PUMPING["pending"]}),
        "costing, sampled": ("costing", {"cost_distribution": first_cost,
                                         "cost_estimate": estimate}),
        "costing, bill alone": ("costing", {"cost_estimate": estimate}),
        "quality, banded test": ("quality", {"pump_analysis": DECISION_PUMPING["banded"]}),
    }
    numbers, gate = [], []
    for name, (report, state) in states.items():
        # the state's keys stay a dict, as the gate is handed one
        held = {k: _ns(v) for k, v in state.items()}
        numbers.append({"case": name, "report": report, "state": state,
                        "d": [_decision_dict(d)
                              for d in decision_numbers(held, report, Config())]})
        readiness = assess_readiness(held, report)
        req = [[r.state, r.detail] for r in readiness.requirements if r.key == "decision_bands"]
        gate.append({"case": name, "report": report, "state": state, "req": req})
    return {
        "format": [{"d": dataclasses.asdict(d), "text": decision_text(d)} for d in fmt],
        "depth": depth,
        "pumping": pumping,
        "odds": odds_out,
        "cost": cost,
        "numbers": numbers,
        "gate": gate,
    }

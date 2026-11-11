"""The ledger (PLAN.md step 5.1): the "ledger" entry of ``reference.json``.
"""

from __future__ import annotations

import copy

from groundwater.config import Config
from groundwater.ingestion import read_drilling_workbook

from .common import clean, DATA, _ns


# ------------------------------------- the ledger (PLAN.md step 5.1)

#: Interpretations as the ledger reads them: basement found under two
#: water-bearing zones, basement never resolved and the depth cut back to
#: the depth of investigation, and a shallow dry profile with no zone.
LEDGER_INTERPS = {
    "resolved": {"sounding_id": "VES 1", "depth_to_basement_m": 28.37, "basement_not_resolved": False,
                 "investigation_depth_m": 60.0, "water_zones": [[8.0, 20.0], [24.0, 28.0]],
                 "aquifer_thickness_m": 16.0, "max_drilling_depth_m": 35.0, "drilling_depth_capped": False,
                 "fit_error_percent": 3.456, "site_easting": 708958.4, "site_northing": 926355.5,
                 "layers": [{"top_m": 0.0, "bottom_m": 2.35, "rho": 812.449},
                            {"top_m": 2.35, "bottom_m": 28.37, "rho": 96.05},
                            {"top_m": 28.37, "bottom_m": None, "rho": 4210.0}]},
    "unresolved": {"sounding_id": "VES 2", "depth_to_basement_m": None, "basement_not_resolved": True,
                   "investigation_depth_m": 40.0, "water_zones": [[8.0, 40.0]],
                   "aquifer_thickness_m": 32.0, "max_drilling_depth_m": 40.0, "drilling_depth_capped": True,
                   "fit_error_percent": 13.35, "site_easting": 708990.0, "site_northing": 926370.0,
                   "layers": [{"top_m": 0.0, "bottom_m": 8.0, "rho": 15.25},
                              {"top_m": 8.0, "bottom_m": None, "rho": 47.0}]},
    "dry": {"sounding_id": "Kpètèma 3", "depth_to_basement_m": 6.05, "basement_not_resolved": False,
            "investigation_depth_m": 30.0, "water_zones": [], "aquifer_thickness_m": 0.0,
            "max_drilling_depth_m": 15.0, "drilling_depth_capped": False, "fit_error_percent": 2.0,
            "site_easting": None, "site_northing": None},
}

#: Ranges of models as the ledger reads them: a band quoted with the
#: drilling depths spread, basement found by too few models to quote and the
#: depths flat at the depth of investigation, and a range sampled before it
#: kept the drilling depths.
LEDGER_RANGES = {
    "none": None,
    "band": {"sounding_id": "VES 1", "basement_m": {"p10": 22.14, "p50": 28.25, "p90": 34.05},
             "basement_unresolved": 0.0, "weathered_m": {"p10": 14.0, "p50": 16.05, "p90": 19.25},
             "investigation_depth_m": 60.0,
             "drilling_depth_quantiles_m": [30.0, 31.0, 31.5, 32.0, 33.0, 34.0, 35.0, 35.5, 36.0, 37.0,
                                            38.0, 39.0, 40.0, 41.0, 42.5, 44.0, 46.0, 48.0, 50.0, 53.0,
                                            55.0]},
    "rarely": {"sounding_id": "VES 2", "basement_m": {"p10": 30.0, "p50": 35.0, "p90": 39.0},
               "basement_unresolved": 0.95, "weathered_m": {"p10": 30.6, "p50": 31.0, "p90": 33.1},
               "investigation_depth_m": 40.0, "drilling_depth_quantiles_m": [40.0] * 21},
    "old": {"sounding_id": "VES 1", "basement_m": None, "basement_unresolved": 1.0,
            "weathered_m": {"p10": 10.0, "p50": 12.0, "p90": 15.0}, "investigation_depth_m": 60.0,
            "drilling_depth_quantiles_m": []},
}

#: The suitability score's parts as the ledger reads them, and a ranked
#: siting (as assess_siting returns it) that gives the second and first
#: points theirs, in that order, and the third none.
LEDGER_PARTS = {"aquifer_thickness": 0.64, "resistivity_fit": 0.81234, "overburden": 1.0, "basal_fracture": 0.5}
LEDGER_SITING = [{"index": 1, "components": {"aquifer_thickness": 1.0, "resistivity_fit": 0.4425,
                                              "overburden": 0.5, "basal_fracture": 0.5}},
                 {"index": 0, "components": LEDGER_PARTS}, {"index": None, "components": LEDGER_PARTS}]

#: A chance of success as the ledger reads it.
LEDGER_ODDS = {
    "probability": 0.61234, "low": 0.3875, "high": 0.7805, "prior": 0.55, "effective_n": 10.0,
    "status": "provisional", "matched": "class", "bgs_code": "B-L", "glg": "pCm",
    "success_yield_m3_per_h": 1.0,
    "calibration": "the toolkit's provisional default, adopted by no named person",
}

#: Drilling logs as the ledger reads them: Dr Timbo's own, a dry hole that
#: never reached fresh rock beside VES 1, one with nothing recorded, and an
#: abandoned hole across the boundary between zones 28 and 29.
def _ledger_logs() -> dict:
    log = read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    timbo = {
        "borehole_ref": log.borehole_ref, "total_depth_m": clean(log.total_depth_m),
        "intervals": [{"top_m": clean(i.top_m), "bottom_m": clean(i.bottom_m),
                       "description": i.description} for i in log.intervals],
        "water_strikes_m": clean(log.water_strikes_m), "status": log.status,
        "completion_date": log.completion_date,
        "site": {"easting": clean(log.site.easting), "northing": clean(log.site.northing),
                 "utm_zone": log.site.utm_zone, "contractor": log.site.contractor},
    }
    return {
        "timbo": timbo,
        "dry": {"borehole_ref": "BH-7", "total_depth_m": 45.0,
                "intervals": [{"top_m": 0.0, "bottom_m": 6.0, "description": "Laterite"},
                              {"top_m": 6.0, "bottom_m": 30.0, "description": "Clayey saprolite"},
                              {"top_m": 30.0, "bottom_m": 45.0, "description": "Weathered granite"}],
                "water_strikes_m": [], "status": "Dry hole", "completion_date": "2026-11-02",
                "site": {"easting": 708962.0, "northing": 926351.0, "utm_zone": 28}},
        "bare": {"borehole_ref": "", "total_depth_m": None, "intervals": [], "water_strikes_m": [],
                 "status": "", "completion_date": "", "site": {"easting": None, "northing": None,
                                                               "utm_zone": None}},
        "abandoned": {"borehole_ref": "BH-9", "total_depth_m": 62.5,
                      "intervals": [{"top_m": 0.0, "bottom_m": 12.0, "description": "Sandy clay"},
                                    {"top_m": 12.0, "bottom_m": 40.0,
                                     "description": "Light colour granite, fracture zone 20-22 m"},
                                    {"top_m": 40.0, "bottom_m": 62.5, "description": "Fresh granite"}],
                      "water_strikes_m": [21.0, 41.5], "status": "Abandoned",
                      "completion_date": "", "site": {"easting": 169600.4, "northing": 930929.4,
                                                      "utm_zone": 29, "contractor": " Kaba \t Drilling\n"}},
    }


#: Pumping test analyses as the ledger reads them: a band and a dry-season
#: hold, a yield short of success, one exactly at it with an open band, one
#: with no spread, and a test with no yield to give.
LEDGER_ANALYSES = {
    "none": None,
    "tested": {"yield_recommendation": {"safe_yield_m3_per_h": 2.345, "confidence": "established"},
               "spread": {"bootstrap": {"p10": 1.0}, "safe_yield_low_m3_per_h": 1.875,
                          "safe_yield_high_m3_per_h": 2.995, "holds_at_dry_season": True}},
    "short": {"yield_recommendation": {"safe_yield_m3_per_h": 0.39, "confidence": "indicative"},
              "spread": {"bootstrap": {"p10": 0.2}, "safe_yield_low_m3_per_h": 0.35,
                         "safe_yield_high_m3_per_h": 0.44, "holds_at_dry_season": True}},
    "edge": {"yield_recommendation": {"safe_yield_m3_per_h": 1.0, "confidence": "indicative"},
             "spread": {"bootstrap": {"p10": 0.5}, "safe_yield_low_m3_per_h": 0.8,
                        "safe_yield_high_m3_per_h": None, "holds_at_dry_season": False}},
    "unspread": {"yield_recommendation": {"safe_yield_m3_per_h": 0.995, "confidence": "indicative"},
                 "spread": None},
    "pending": {"yield_recommendation": {"safe_yield_m3_per_h": None, "confidence": "indicative"},
                "spread": None},
}

#: Ledgers as a hand-edited file can hold them.
LEDGER_DIRTY = [
    None, "a ledger", [], {}, {"entries": "none"},
    {"drilled": "gone", "entries": [
        "an entry", {"id": 7, "point": {}, "prediction": {}}, {"id": "", "point": {}, "prediction": {}},
        {"id": "a1", "point": "here", "prediction": {}},
        {"id": "a2", "point": {"sounding_id": 3, "easting": "708958", "northing": True, "utm_zone": 28.5},
         "prediction": {"depth_to_basement_m": "28", "basement_resolved": 1, "water_zones_m": [[8, 20], [24], "x"],
                        "survey_team": 5,
                        "basement_band_m": [1, 2], "drilling_depth_band_m": [30, None],
                        "odds": {"probability": None, "low": 0.2}},
         "before_outcome": "yes", "recorded_on": 20261018,
         "outcome": {"intervals": [[0, 5, "topsoil"], [5, "x", "clay"], [5, 9]], "water_strikes_m": [12, "15"],
                     "contractor": "  WiNGiN \u00a0 Heavy  Duty ",
                     "safe_yield_band_m3_per_h": [0.5], "success": "true", "success_basis": "tested",
                     "status_class": "wet", "utm_zone": 29.0},
         "pairing": {"how": "guessed"}},
        {"id": "a3", "point": {"sounding_id": "B", "utm_zone": 29}, "prediction": {
            "odds": {"probability": 0.5, "bgs_code": 4, "glg": "pCm", "status": None}},
         "before_outcome": True, "outcome": None, "pairing": {"how": "chosen", "distance_m": 4.04}},
        {"id": "a3", "point": {}, "prediction": {}},
        {"id": "a4", "point": {}, "prediction": {}, "outcome": {"success": False,
                                                                "success_basis": "recorded_failure"},
         "pairing": {"how": "nearest", "distance_m": "far"}},
    ]},
    {"drilled": "a5", "entries": [{"id": "a5", "point": {}, "prediction": {},
                                   "outcome": {"safe_yield_band_m3_per_h": [0.5, None]}}]},
    # the ledger's identity: text is kept, anything else is none
    {"project_id": "0a1b2c3d4e5f", "entries": []}, {"project_id": 7, "entries": []},
    {"project_id": "", "entries": []}, {"project_id": ["a"], "drilled": None},
]

#: Project files' top levels, as the schema is read from them and migrated.
LEDGER_SCHEMAS = [{}, {"schema": 1}, {"schema": 2, "ledger": {"drilled": None, "entries": []}},
                  {"schema": 3}, {"schema": 4}, {"schema": 5}, {"schema": "2"}, {"schema": True}, {"version": 1},
                  {"schema": 0.5}, {"schema": 2.7}, {"schema": None},
                  # a schema 3 ledger keeps its ids and has no identity
                  {"schema": 3, "issued": [], "ledger": {"drilled": None, "entries": [
                      {"id": "a1", "point": {}, "prediction": {}, "before_outcome": True}]}}]

#: Point identifiers: a name, a position and a place, a half metre that
#: rounds to even, no position, and a name in another script; and in a
#: ledger with an identity, or an empty one, which is none.
LEDGER_IDS = [["VES 1", 708958.4, 926355.5, 28, "Rokel", "Port Loko"],
              ["VES 1", 708958.5, 926356.5, 28, "Rokel", "Port Loko"],
              ["VES 1", None, None, None, "", ""],
              ["VES 1", 708958.0, 926356.0, 28.0, "Rokel", ""],
              ["Kpètèma 3", 166030.0, 930010.0, 29, "Kpètèma", "Bo"],
              ["VES 1", None, None, None, "Rokel", "Port Loko", "0a1b2c3d4e5f"],
              ["VES 1", 708958.4, 926355.5, 28, "Rokel", "Port Loko", ""]]


def _ledger_run(ops: list) -> list:
    """Each step of a scenario applied in turn, and the ledger (and what
    else the step returns) after it. parity.mjs runs the same steps."""
    from groundwater import ledger as L

    held = L.empty_ledger()
    out = []
    for op in ops:
        config = Config()
        if op.get("within") is not None:
            config.ledger.pair_within_m = op["within"]
        if op["op"] == "record":
            held, kept = L.record_predictions(held, op["predictions"], op["on"], op["known"], "0.3.0")
            out.append({"ledger": held, "kept": kept})
        elif op["op"] == "choose":
            held = dict(held, drilled=op["id"] if op["id"] is None or isinstance(op["id"], str)
                        else held["entries"][op["id"]]["id"])
            out.append({"ledger": L.clean_ledger(held)})
        elif op["op"] == "pair":
            pid, pairing = L.pair_drilled(held, op["outcome"], config)
            out.append({"id": pid, "pairing": pairing})
        elif op["op"] == "attach":
            held = L.attach_outcome(held, op["outcome"], config)
            out.append({"ledger": held})
    return out


def ledger_reference(rokel_interps, rokel_sites, short_ranges, rokel_odds) -> dict:
    """The ledger (PLAN.md step 5.1): predictions over every kind of point
    and range, outcomes over every kind of log and test, scenarios of
    recording, pairing and attaching, cleaning hand-edited ledgers, the
    comparison's words, pooling, point identifiers, the project file's
    schema and its migration, and the real Rokel survey."""
    from groundwater import ledger as L
    from groundwater.project_io import deserialize_project, migrate_payload, payload_schema, serialize_project

    config = Config()
    wider = Config()
    wider.odds.success_yield_m3_per_h = 3.6
    predictions = []
    for iname, interp in LEDGER_INTERPS.items():
        for rname, r in LEDGER_RANGES.items():
            for with_odds in (False, True):
                odds = LEDGER_ODDS if with_odds else None
                # the score's parts with the odds, so each kind of point is
                # recorded both with and without them
                parts = LEDGER_PARTS if with_odds else None
                predictions.append({"interp": iname, "range": rname, "odds": with_odds, "parts": with_odds,
                                    "expect": L.point_prediction(_ns(interp), _ns(r), _ns(odds), config, "",
                                                                 _ns(parts))})
    logs = _ledger_logs()
    outcomes = []
    for lname, log in logs.items():
        for aname, analysis in LEDGER_ANALYSES.items():
            outcomes.append({"log": lname, "analysis": aname, "wider": False,
                             "expect": L.completion_outcome(_ns(log), _ns(analysis), config)})
    for aname in ("tested", "short"):
        outcomes.append({"log": "timbo", "analysis": aname, "wider": True,
                         "expect": L.completion_outcome(_ns(logs["timbo"]), _ns(LEDGER_ANALYSES[aname]), wider)})
    # the project's drilling contractor, which wins over the log's own
    for lname, log in logs.items():
        outcomes.append({"log": lname, "analysis": "none", "wider": False, "contractor": "  Sierra   Drilling ",
                         "expect": L.completion_outcome(_ns(log), None, config, contractor="  Sierra   Drilling ")})

    site = {"community": "Rokel", "district": "Port Loko", "utm_zone": 28}
    # each point's survey team: its own sheet's field supervisor, else the
    # project's, written as typed with its white space tidied
    surveys = []
    for teams in (None, ["  A.  Kamara\t", "", None], ["B. Sesay"]):
        for supervisor in (None, "  R.  Conteh ", 7):
            where = site if supervisor is None else dict(site, supervisor=supervisor)
            # the ranked siting with the first site only
            siting = LEDGER_SITING if supervisor is None else None
            surveys.append({"teams": teams, "site": where, "siting": siting, "expect": L.survey_predictions(
                [_ns(LEDGER_INTERPS[k]) for k in ("resolved", "unresolved", "dry")],
                [_ns(LEDGER_RANGES["band"]), None, None], [_ns(LEDGER_ODDS), _ns(LEDGER_ODDS), None],
                _ns(where), config, teams, _ns(siting))})
    survey = surveys[4]["expect"]
    resurvey = L.survey_predictions(
        [_ns(LEDGER_INTERPS[k]) for k in ("resolved", "unresolved")],
        [_ns(LEDGER_RANGES["old"]), _ns(LEDGER_RANGES["rarely"])], None, _ns(site), config)
    extra = L.survey_predictions([_ns(dict(LEDGER_INTERPS["resolved"], sounding_id="VES 4",
                                           site_easting=709300.0))], None, None, _ns(site), config)
    dry = next(o["expect"] for o in outcomes if o["log"] == "dry" and o["analysis"] == "none")
    timbo = next(o["expect"] for o in outcomes if o["log"] == "timbo" and o["analysis"] == "short")
    across = next(o["expect"] for o in outcomes if o["log"] == "abandoned" and o["analysis"] == "tested")
    scenarios = {
        "drilled": [
            {"op": "record", "predictions": survey, "on": "2026-10-01", "known": False},
            {"op": "record", "predictions": resurvey, "on": "2026-10-05", "known": False},
            {"op": "pair", "outcome": dry},
            {"op": "attach", "outcome": dry},
            {"op": "record", "predictions": survey + extra, "on": "2026-11-20", "known": True},
            {"op": "attach", "outcome": None},
            {"op": "choose", "id": 1},
            {"op": "attach", "outcome": dry},
            {"op": "choose", "id": "not an entry"},
            {"op": "attach", "outcome": dry},
            {"op": "pair", "outcome": dry, "within": 4.0},
            {"op": "attach", "outcome": timbo},
            {"op": "choose", "id": None},
            {"op": "attach", "outcome": timbo},
        ],
        "after": [
            {"op": "record", "predictions": survey[:1], "on": "2026-12-01", "known": True},
            {"op": "pair", "outcome": None},
            {"op": "pair", "outcome": timbo},
            {"op": "attach", "outcome": timbo},
            {"op": "record", "predictions": resurvey[:1], "on": "2026-12-02", "known": True},
        ],
        "no_log": [
            # a forecast with its outcome, recorded again while no log is
            # loaded (removed, or only a pumping test in): kept as it was
            # made, and a point added now is recorded after drilling
            {"op": "record", "predictions": survey, "on": "2026-10-01", "known": False},
            {"op": "attach", "outcome": dry},
            {"op": "record", "predictions": resurvey + extra, "on": "2026-10-27", "known": False},
            {"op": "attach", "outcome": None},
        ],
        "chosen": [
            # the point drilled chosen before any log or outcome: the hole is
            # drilled, so the forecasts are kept and a point added now is
            # recorded after drilling
            {"op": "record", "predictions": survey, "on": "2026-10-01", "known": False},
            {"op": "choose", "id": 1},
            {"op": "record", "predictions": resurvey + extra, "on": "2026-10-27", "known": False},
        ],
        "after_again": [
            # recorded after drilling, then again with no log loaded, before
            # and after its outcome is attached: after drilling throughout
            {"op": "record", "predictions": survey[:1], "on": "2026-12-01", "known": True},
            {"op": "record", "predictions": resurvey[:1], "on": "2026-12-05", "known": False},
            {"op": "attach", "outcome": timbo},
            {"op": "record", "predictions": survey[:1], "on": "2026-12-06", "known": False},
        ],
        "across": [
            # a point in zone 28 near its eastern edge and a log written in
            # zone 29, the same place a few metres apart
            {"op": "record", "predictions": [{"point": dict(survey[0]["point"], easting=830391.2,
                                                            northing=930924.1),
                                              "prediction": survey[0]["prediction"]},
                                             survey[1]], "on": "2026-10-01", "known": False},
            {"op": "pair", "outcome": across},
            {"op": "attach", "outcome": across},
        ],
    }
    scenario_out = {name: _ledger_run(ops) for name, ops in scenarios.items()}

    texts = []
    for i, p in enumerate(predictions):
        for j, o in enumerate([None] + [o["expect"] for o in outcomes]):
            if (i + 2 * j) % 7:
                continue
            entry = {"prediction": p["expect"], "outcome": o}
            texts.append({"prediction": i, "outcome": j - 1,
                          "check": L.basement_check(p["expect"], o),
                          "outcome_text": L.outcome_text(o), "rows": L.entry_rows(entry)})

    drilled = scenario_out["drilled"]
    pool_items = [["Rokel", drilled[-1]["ledger"]], ["Rokel copy", drilled[1]["ledger"]],
                  ["Kuntolo", scenario_out["across"][-1]["ledger"]], ["Junk", "not a ledger"],
                  ["Rokel again", drilled[3]["ledger"]]]
    pooled = L.pool_ledgers([tuple(item) for item in pool_items])
    header, rows = L.ledger_rows(pooled)

    # copies of one project and two projects alike, each pooled in both
    # orders: a save before the pumping test (the driller's word) and one
    # after it (tested short); two tested saves that rank alike; and a dry
    # hole and its replacement in one village, recorded a year apart at a
    # point with no position
    driller = next(o["expect"] for o in outcomes if o["log"] == "timbo" and o["analysis"] == "none")
    tested = next(o["expect"] for o in outcomes if o["log"] == "timbo" and o["analysis"] == "tested")
    one = L.record_predictions(L.empty_ledger(), survey[:1], "2026-01-10", False, "0.3.0")[0]
    bare = [{"point": dict(survey[0]["point"], easting=None, northing=None), "prediction": survey[0]["prediction"]}]
    village = [L.attach_outcome(L.record_predictions(L.empty_ledger(), bare, on, False, "0.3.0")[0], outcome)
               for on, outcome in (("2025-02-01", dry), ("2026-02-01", timbo))]
    # the same two holes in two projects whose predictions were first
    # recorded on the same day: one identity, so one id, and their outcomes
    # name two boreholes, so the summary does not call one an older record
    same_day = [L.attach_outcome(L.record_predictions(L.empty_ledger(), bare, "2026-02-01", False, "0.3.0")[0],
                                 outcome) for outcome in (dry, timbo)]
    # the same two holes in ledgers written before a ledger had an
    # identity: one id, so one is counted, and the summary says it may be
    # either an older record or two projects
    legacy = [{"drilled": None, "entries": [dict(e, id=L.point_id(
        e["point"]["sounding_id"], e["point"]["easting"], e["point"]["northing"], e["point"]["utm_zone"],
        e["point"]["community"], e["point"]["district"])) for e in ledger["entries"]]} for ledger in village]
    pool_pairs = {
        "copies": [["Rokel, before the test", L.attach_outcome(one, driller)],
                   ["Rokel, tested", L.attach_outcome(one, timbo)]],
        "alike": [["Rokel", L.attach_outcome(one, tested)], ["Rokel again", L.attach_outcome(one, timbo)]],
        "village": [["Rokel (Port Loko)", village[0]], ["Rokel (Port Loko)", village[1]]],
        "same_day": [["Rokel (Port Loko)", same_day[0]], ["Rokel (Port Loko)", same_day[1]]],
        "legacy": [["Rokel (Port Loko)", legacy[0]], ["Rokel (Port Loko)", legacy[1]]],
    }
    pools = []
    for name, pair in pool_pairs.items():
        for order in (pair, pair[::-1]):
            got = L.pool_ledgers([tuple(item) for item in order])
            pools.append({"name": name, "items": order, "pooled": got, "counts": L.ledger_counts(got),
                          "summary": L.ledger_summary(got)})

    on_file = copy.deepcopy(drilled[3]["ledger"])
    for entry in on_file["entries"]:
        if entry["outcome"] is not None:
            # long and with a dash PyYAML escapes, so it is folded in double quotes
            entry["outcome"]["status"] = ("Abandoned – the casing collapsed at 30 m after the second airlift, "
                                          "and the crew moved the rig to the reserve site")
    saved = serialize_project({"meta_community": "Kpètèma", "prediction_ledger": on_file}, "0.3.0")
    rokel_survey = L.survey_predictions(
        rokel_interps, [_ns(r) for r in short_ranges], [_ns(o) for o in rokel_odds],
        rokel_sites[0], config)
    return {
        "predictions": predictions,
        "interps": LEDGER_INTERPS, "ranges": LEDGER_RANGES, "odds": LEDGER_ODDS, "parts": LEDGER_PARTS,
        "logs": logs, "analyses": LEDGER_ANALYSES,
        "outcomes": outcomes,
        "site": site,
        "surveys": surveys,
        "scenarios": {name: {"ops": ops, "expect": scenario_out[name]} for name, ops in scenarios.items()},
        "texts": texts,
        "dirty": [{"raw": raw, "expect": L.clean_ledger(raw)} for raw in LEDGER_DIRTY],
        "pool": {"items": pool_items, "pooled": pooled, "counts": L.ledger_counts(pooled),
                 "header": header, "rows": rows, "none": list(L.ledger_rows([])),
                 "entry_header": L.entry_header(), "summary": L.ledger_summary(pooled),
                 "summary_none": L.ledger_summary([])},
        "pools": pools,
        # a Streamlit project file holding a ledger with an outcome, a name
        # YAML writes escaped, positions left out and a quoted calibration,
        # as the browser's YAML reader has to read it
        "file": {"yaml": saved.decode("utf-8"),
                 "expect": deserialize_project(saved)["prediction_ledger"]},
        "ids": [{"args": args, "expect": L.point_id(*args)} for args in LEDGER_IDS],
        "schemas": [{"payload": p, "schema": payload_schema(p), "migrated": migrate_payload(p)}
                    for p in LEDGER_SCHEMAS],
        "rokel": rokel_survey,
    }

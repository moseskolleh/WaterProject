"""The survey plan (PLAN.md step 4.3): the "survey_plan" entry of
``reference.json``.

``_l1_run`` analyses L1's window once for this section and the desk study
both, and keeps the answer in ``_L1_RUN``; ``tests/test_desk_study.py`` calls
it and ``_desk_terrain`` over ``PLAN_CASES`` through ``make_reference.py``.
"""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

from .geotiff import _gt_number
from .lineaments import LINEAMENT_GENERATED, lineament_heights
from .terrain import _ta_analysis, _ta_short


# ------------------------------------------------ survey plan (PLAN.md step 4.3)

#: Plans laid on L1's window (LINEAMENT_GENERATED, analysed as the
#: lineaments section analyses it) across its candidates at the defaults.
#: "at" is the site as [column, row] of the window, placed at lon0 +
#: column*step and lat0 + row*step; each water point is [column, row,
#: source, technology] placed alike; "settings" go over the window's own.
#: P1 has a spring and a tap within reach; P2's two lines each cross a
#: third candidate, given no line of its own, and its water points sit
#: where they move two soundings and leave a third out: a borehole 30 m
#: along the first line from its crossing, a dug well 12 m along the second
#: and surface water 45 m before it; at P3 the service radius shortens a
#: line; P4 has no candidate within 500 m; P5 changes every setting and asks
#: for a depth past the field schedule's longest spacing; and P6 is at the
#: square's edge. "searched" is how far round the site the water points
#: were looked up (survey_plan's searched_m), None where it is not given:
#: P7 is P2 with its water points looked up only 300 m round the site,
#: short of the 550 m a borehole's ring reaches, and P8 a lookup over
#: 1,000 m that found none.
PLAN_CASES = [
    {"case": "P1: in the middle of the window, with a spring and a tap", "at": [80.0, 80.0],
     "water": [[84.0, 77.0, "Protected Spring", ""], [79.0, 86.5, "Piped Water", "Tap stand"]], "settings": {}},
    {"case": "P2: two lines across a third candidate, with a borehole, a dug well and surface water on them",
     "at": [49.0, 42.0],
     "water": [[52.12, 40.87, "Borehole", "Hand Pump - India Mark II"], [40.465, 37.894, "Protected Shallow Well", ""],
               [38.648, 38.308, "Surface Water (River/Stream/Lake/Pond/Dam)", ""]], "settings": {}},
    {"case": "P3: a line the service radius shortens", "at": [42.0, 54.0], "water": [], "settings": {}},
    {"case": "P4: no candidate within the service radius", "at": [125.0, 125.0], "water": [], "settings": {}},
    {"case": "P5: every setting changed, and a target past the longest spacing", "at": [80.0, 80.0], "water": [],
     "settings": {"survey_lines": 3, "survey_line_m": 600.0, "survey_station_m": 25.0, "survey_flank_m": 80.0,
                  "survey_move_m": 30.0, "survey_cross_within_deg": 30.0, "survey_target_depth_m": 300.0}},
    {"case": "P6: at the edge of the square shown", "at": [20.0, 140.0], "water": [], "settings": {}},
    {"case": "P7: P2's water points looked up short of a borehole's reach", "at": [49.0, 42.0],
     "water": [[52.12, 40.87, "Borehole", "Hand Pump - India Mark II"], [40.465, 37.894, "Protected Shallow Well", ""],
               [38.648, 38.308, "Surface Water (River/Stream/Lake/Pond/Dam)", ""]], "settings": {},
     "searched": 300.0},
    {"case": "P8: a lookup over 1,000 m that found no water point", "at": [80.0, 80.0], "water": [], "settings": {},
     "searched": 1000.0},
]

#: Settings both engines refuse in the same words.
PLAN_REFUSED = [{"survey_lines": 0}, {"survey_line_m": -1.0}, {"survey_move_m": 30.0},
                  {"survey_cross_within_deg": 95.0}, {"survey_station_m": 800.0}]

#: What the GPX and the GeoJSON are told.
PLAN_META = {"where": "Kakua", "label": "Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", "site_label": "Rokel"}


def _sp_answer(a, lin, spec: dict, kase: dict) -> tuple[dict, str | None, str | None]:
    """survey_plan round the case's site on the analysed window, and what
    parity.mjs compares: the plan field by field, the AB/2 series and the
    captions word for word, and the GPX and the GeoJSON apart. A refusal is
    held word for word."""
    from groundwater.mapping.survey import survey_plan, survey_plan_captions, survey_plan_geojson, survey_plan_gpx

    def at(point):
        return [spec["lon0"] + point[0] * spec["step"], spec["lat0"] + point[1] * spec["step"]]

    water = [SimpleNamespace(lon=at(w)[0], lat=at(w)[1], source=w[2], technology=w[3]) for w in kase["water"]]
    cfg = dataclasses.replace(lin.settings, **kase["settings"])
    try:
        plan = survey_plan(lin, a.core, a.parts, at(kase["at"]), water, cfg, searched_m=kase.get("searched"))
    except ValueError as refused:
        return {"refused": str(refused)}, None, None

    def pair(p):
        return [_gt_number(v) for v in p]

    answer = {
        "basis": plan.basis, "site": pair(plan.site), "near": list(plan.near),
        "skipped": [list(s) for s in plan.skipped], "reach": plan.reach, "covered": plan.covered,
        "water_points": plan.water_points,
        "rings": [[_gt_number(g[0]), _gt_number(g[1]), g[2], _gt_number(g[3])] for g in plan.rings],
        "lines": [[line.id, line.candidate, line.kind, _gt_number(line.strike_deg), _gt_number(line.bearing_deg),
                   pair(line.origin), pair(line.direction), line.first, line.last, _gt_number(line.length_m),
                   _gt_number(line.crossing_m), [[c[0], _gt_number(c[1])] for c in line.crosses], line.shortened]
                  for line in plan.lines],
        "soundings": [[x.id, x.line, x.role, _gt_number(x.at_m), pair(x.point), _gt_number(x.moved_m),
                       list(x.cleared), _gt_number(x.spread_deg)] for x in plan.soundings],
        "dropped": [[d.line, d.role, _gt_number(d.at_m), list(d.reasons)] for d in plan.dropped],
        "ab2": plan.ab2,
        "captions": [list(item) for item in survey_plan_captions(plan, PLAN_META["where"]).items()],
    }
    lons, lats = a.core.lons, a.core.lats
    return answer, survey_plan_gpx(plan, lons, lats, PLAN_META), survey_plan_geojson(plan, lons, lats, PLAN_META)


_L1_RUN: list = []


def _l1_run():
    """L1's window analysed and its candidates found, once for the survey
    plan and the desk study both."""
    from groundwater.mapping.lineaments import lineament_candidates

    if not _L1_RUN:
        spec = LINEAMENT_GENERATED
        window = dict(spec, case="L1", settings=spec["settings"], assumed=None)
        a, _ = _ta_analysis(window, lineament_heights(spec))
        _L1_RUN.append((a, lineament_candidates(a)))
    return _L1_RUN[0]


def _desk_terrain(a, lin, spec: dict, kase: dict) -> dict:
    """What a desk study keeps of the case's plan (PLAN.md step 4.4), from
    the lineament and plan captions merged as the Site maps page merges
    them."""
    from groundwater.desk_study import desk_study_terrain
    from groundwater.mapping.lineaments import lineament_captions
    from groundwater.mapping.survey import survey_plan, survey_plan_captions

    def at(point):
        return [spec["lon0"] + point[0] * spec["step"], spec["lat0"] + point[1] * spec["step"]]

    water = [SimpleNamespace(lon=at(w)[0], lat=at(w)[1], source=w[2], technology=w[3]) for w in kase["water"]]
    plan = survey_plan(lin, a.core, a.parts, at(kase["at"]), water,
                       dataclasses.replace(lin.settings, **kase["settings"]), searched_m=kase.get("searched"))
    captions = {**lineament_captions(lin, PLAN_META["where"]), **survey_plan_captions(plan, PLAN_META["where"])}
    return desk_study_terrain(lin, plan, a.core.lons, a.core.lats, captions, PLAN_META["label"])


def survey_plan_reference() -> dict:
    """The survey plan (PLAN.md step 4.3) on L1's window: each case of
    PLAN_CASES with its GPX to the character and its GeoJSON by a short
    digest and its length, and what a desk study keeps of it (step 4.4);
    and the settings both engines refuse, on P1."""
    spec = LINEAMENT_GENERATED
    a, lin = _l1_run()
    cases = []
    for kase in PLAN_CASES:
        answer, gpx, geojson = _sp_answer(a, lin, spec, kase)
        assert "refused" not in answer, kase["case"]
        cases.append(dict(kase, expect=json.dumps(answer, separators=(",", ":")), gpx=gpx,
                          geojson=[_ta_short(geojson), len(geojson)],
                          desk=json.dumps(_desk_terrain(a, lin, spec, kase), separators=(",", ":"))))
    refused = [{"settings": settings,
                "refused": _sp_answer(a, lin, spec, dict(PLAN_CASES[0], settings=settings))[0]["refused"]}
               for settings in PLAN_REFUSED]
    # a lookup radius below 0, refused in the same words
    refused.append({"settings": {}, "searched": -1.0,
                    "refused": _sp_answer(a, lin, spec, dict(PLAN_CASES[0], searched=-1.0))[0]["refused"]})
    return {"meta": PLAN_META, "cases": cases, "refused": refused}

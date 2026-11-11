"""The desk study (PLAN.md step 4.4): the "desk_study" entry of
``reference.json``.
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

from .lineaments import LINEAMENT_GENERATED
from .survey_plan import _desk_terrain, _l1_run, PLAN_CASES


# ------------------------------------------------ desk study (PLAN.md step 4.4)

def _wpdx(lat: float, lon: float, k: int) -> list[dict]:
    """WPdx+ rows round (lat, lon), as the inventory serves them: a working
    borehole and a broken protected well inside the service radius, one of
    unknown status that names only its technology, surface water, a tap,
    and points out to and past the search radius, k of them in a ring."""
    rows = [
        {"row_id": "w1", "lat_deg": lat + 0.0012, "lon_deg": lon - 0.0005, "status_clean": "Functional",
         "water_source_clean": "Borehole", "water_tech_clean": "Hand Pump - India Mark II", "install_year": "2012"},
        {"row_id": "w2", "lat_deg": lat + 0.0030, "lon_deg": lon - 0.0010, "status_clean": "Non-Functional",
         "water_source_clean": "Protected Shallow Well", "install_year": 2008},
        {"row_id": "w3", "lat_deg": lat - 0.0040, "lon_deg": lon + 0.0035, "status_clean": "",
         "water_tech_clean": "Hand Pump"},
        {"row_id": "w4", "lat_deg": lat - 0.0021, "lon_deg": lon - 0.0002, "status_clean": "Functional",
         "water_source_clean": "Surface Water (River/Stream/Lake/Pond/Dam)"},
        {"row_id": "w5", "lat_deg": lat + 0.0065, "lon_deg": lon + 0.0040, "status_clean": "Non-Functional",
         "water_source_clean": "Piped Water", "water_tech_clean": "Tap stand", "install_year": "2016"},
        {"row_id": "w6", "lat_deg": lat + 0.0200, "lon_deg": lon, "status_clean": "Functional",
         "water_source_clean": "Borehole"},
    ]
    for i in range(k):
        angle = 2.0 * math.pi * i / max(k, 1)
        rows.append({"row_id": f"r{i}", "lat_deg": lat + 0.0055 * math.cos(angle),
                     "lon_deg": lon + 0.0055 * math.sin(angle), "status_clean": "Functional" if i % 3 else "Broken",
                     "water_source_clean": "Borehole" if i % 2 else "Protected Spring",
                     "install_year": 1995 + i})
    return rows


def _portfolio(lat: float, lon: float) -> list[dict]:
    """Earlier projects' summaries round (lat, lon): a successful borehole
    3 km off, a dry one 1 km off read from an older file, one sited with no
    depth, one 6 km off, one with no position and one zone-less."""
    from groundwater.geo import geographic_to_utm

    def placed(dlat, dlon, **fields):
        u = geographic_to_utm(lat + dlat, lon + dlon)
        return {"easting": u.easting, "northing": u.northing, "utm_zone": u.zone, **fields}

    return [
        placed(0.027, 0.0, community="Masanga", district="Tonkolili", status="Completed - successful",
               total_depth_m=48.5, safe_yield_m3_per_h=1.8, water_verdict="pass", verdict_schema=2),
        placed(-0.009, 0.0, community="Rokel", district="Port Loko", status="dry", total_depth_m="62",
               water_verdict="fail"),
        placed(0.0, 0.015, community="Lunsar", status="sited"),
        placed(0.054, 0.0, community="Far", status="Completed - successful", total_depth_m=40.0),
        {"community": "Nowhere", "status": "dry"},
        dict(placed(0.0, -0.02, community="Zoneless", status="in progress", safe_yield_m3_per_h=0.9), utm_zone=None),
    ]


#: The desk studies both engines put together: each with the site's names,
#: the place, its position (or none), the WPdx+ rows loaded (or none) and
#: the radius searched, the earlier projects (or none), and the plan of
#: PLAN_CASES whose terrain it keeps (or none). D1 has every section; D2
#: is on the Freetown Complex with nothing near; D3 has no position; D4 to
#: D6 keep L1's plans, D4 with more water points than are listed and D6
#: with the site moved off the plan; D7 is on the Bullom Group and D8 on
#: surface water, where the placeholder prior applies. D9 has an earlier
#: project with a longitude and a latitude in its UTM boxes, beside the
#: site, and water points whose install year is 0, 2009.6 and an
#: installation_year.
DESK_CASES = [
    {"case": "D1: inland, with water points and earlier projects", "site": {"community": "Rokel",
     "chiefdom": "Maforki", "district": "Port Loko"}, "where": "Rokel", "latlon": [8.6, -11.9],
     "water": _wpdx(8.6, -11.9, 3), "radius": 1000.0, "portfolio": _portfolio(8.6, -11.9), "plan": None},
    {"case": "D2: Freetown, with nothing near", "site": {"community": "Leicester", "district": "Western Area Rural"},
     "where": "Leicester", "latlon": [8.4657, -13.2317], "water": [], "radius": 500.0, "portfolio": [],
     "plan": None},
    {"case": "D3: no position", "site": {"community": "Kamakwie", "district": "Karene"}, "where": "Sella Limba",
     "latlon": None, "water": None, "radius": 1000.0, "portfolio": None, "plan": None},
    {"case": "D4: L1's two lines, and more water points than are listed", "site": {"community": "Rokel"},
     "where": "Kakua", "latlon": "plan", "water": "ring", "radius": 1000.0, "portfolio": None, "plan": 1},
    {"case": "D5: L1's line across the strike", "site": {"community": "Rokel"}, "where": "Kakua",
     "latlon": "plan", "water": None, "radius": 1000.0, "portfolio": [], "plan": 3},
    {"case": "D6: the site moved off L1's plan", "site": {"community": "Rokel"}, "where": "Kakua",
     "latlon": "moved", "water": None, "radius": 1000.0, "portfolio": None, "plan": 0},
    {"case": "D7: the Bullom Group", "site": {"community": "Lungi", "district": "Port Loko"}, "where": "Lungi",
     "latlon": [8.62, -13.2], "water": _wpdx(8.62, -13.2, 0), "radius": 750.0, "portfolio": _portfolio(8.62, -13.2),
     "plan": None},
    {"case": "D8: surface water", "site": {"community": "T"}, "where": "T", "latlon": [7.3, -11.8], "water": [],
     "radius": 1000.0, "portfolio": [], "plan": None},
    {"case": "D9: degrees in an earlier project's boxes, and install years written three ways",
     "site": {"community": "Rokel II", "district": "Western Area Rural"}, "where": "Rokel II",
     "latlon": [8.466, -13.232],
     "water": [{"row_id": "y0", "lat_deg": "8.4663", "lon_deg": "-13.232", "status_clean": "Functional",
                "water_source_clean": "Borehole", "install_year": "0"},
               {"row_id": "y1", "lat_deg": "8.4673", "lon_deg": "-13.232", "status_clean": "Functional",
                "water_source_clean": "Borehole", "install_year": "2009.6"},
               {"row_id": "y2", "lat_deg": "8.4683", "lon_deg": "-13.232", "status_clean": "Non-Functional",
                "water_source_clean": "Borehole", "installation_year": "2011"},
               {"row_id": "y3", "lat_deg": "nan", "lon_deg": "-13.232", "status_clean": "Functional"}],
     "radius": 1000.0,
     "portfolio": [{"community": "Rokel", "district": "Western Area Rural", "easting": -13.2317,
                    "northing": 8.4657, "status": "Completed - successful", "total_depth_m": 48},
                   {"community": "Kissy", "easting": "13.2", "northing": "8.47"},
                   {"community": "Nowhere", "status": "dry"}], "plan": None},
]


def _desk_case(kase: dict, terrain: dict | None) -> dict:
    """The case with its position and water points worked out from the
    plan it keeps, as both engines are given it."""
    out = dict(kase)
    if kase["latlon"] in ("plan", "moved"):
        lat, lon = terrain["site"]
        out["latlon"] = [lat, lon] if kase["latlon"] == "plan" else [lat + 0.0001, lon]
    if kase["water"] == "ring":
        out["water"] = _wpdx(out["latlon"][0], out["latlon"][1], 14)
    return out


def desk_study_reference() -> dict:
    """The desk study (PLAN.md step 4.4): each case of DESK_CASES with its
    content as desk_study_content puts it together, held whole."""
    from groundwater.desk_study import desk_study_content
    from groundwater.waterpoints import parse_wpdx_records

    spec = LINEAMENT_GENERATED
    a, lin = _l1_run()
    cases = []
    for kase in DESK_CASES:
        terrain = _desk_terrain(a, lin, spec, PLAN_CASES[kase["plan"]]) if kase["plan"] is not None else None
        given = _desk_case(kase, terrain)
        points = None if given["water"] is None else parse_wpdx_records(given["water"])
        content = desk_study_content(
            SimpleNamespace(**{"community": "", "chiefdom": "", "district": "", **given["site"]}), given["where"],
            tuple(given["latlon"]) if given["latlon"] else None, water_points=points,
            search_radius_m=given["radius"], portfolio=given["portfolio"], terrain=terrain)
        cases.append(dict(given, expect=json.dumps(content, separators=(",", ":"))))
    return {"cases": cases}

"""The desk study's content (PLAN.md step 4.4): the ground under the site,
the odds from the prior alone, the water points and earlier projects near
it, what it keeps of the terrain, and the browser's engine held to it."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from groundwater.desk_study import (
    PORTFOLIO_RADIUS_M,
    WATER_POINTS_LISTED,
    desk_study_content,
    desk_study_terrain,
    site_ground,
)
from groundwater.geo import geographic_to_utm
from groundwater.reporting.citations import CITATIONS
from groundwater.siting.odds import (
    odds_headline,
    odds_point_text,
    odds_prior_text,
    prior_odds,
    success_odds,
)
from groundwater.text import phrase
from groundwater.waterpoints import parse_wpdx_records

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "docs" / "js"
sys.path.insert(0, str(ROOT / "tests" / "webapp"))

INLAND = (8.6, -11.9)
FREETOWN = (8.4657, -13.2317)
LUNGI = (8.62, -13.2)
SITE = SimpleNamespace(community="Rokel", chiefdom="Maforki", district="Port Loko")


def _section(content: dict, key: str) -> dict:
    return next(s for s in content["sections"] if s["key"] == key)


def _strings(value) -> bool:
    """Whether every leaf of the content is text, as both writers lay it."""
    if isinstance(value, dict):
        return all(isinstance(k, str) and _strings(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_strings(v) for v in value)
    return isinstance(value, str)


def _point(lat, lon, status="Functional", source="Borehole", technology="", year=None, row="p"):
    return {"row_id": row, "lat_deg": lat, "lon_deg": lon, "status_clean": status,
            "water_source_clean": source, "water_tech_clean": technology, "install_year": year}


def _summary(lat, lon, **fields):
    u = geographic_to_utm(lat, lon)
    return {"easting": u.easting, "northing": u.northing, "utm_zone": u.zone, **fields}


# ---------------------------------------------------------------- the ground

def test_the_ground_under_a_site_on_the_freetown_complex():
    ground = site_ground(FREETOWN, "Western Area Urban")
    assert (ground["glg"], ground["bgs_code"]) == ("Pi", "I-L")
    # the formation the crosswalk names, not the USGS unit's wrong age
    assert ground["formation"] == "Freetown Layered Complex"
    assert ground["unit"] == "Paleozoic Igneous"
    assert ground["lithology"].startswith("Freetown Layered Complex")
    assert ground["aquifer"].startswith("Igneous intrusive aquifer")


def test_the_ground_inland_and_on_the_bullom_group():
    inland, coast = site_ground(INLAND), site_ground(LUNGI)
    assert (inland["glg"], inland["bgs_code"]) == ("pCm", "B-L")
    assert inland["formation"].startswith("Precambrian basement")
    assert (coast["glg"], coast["bgs_code"], coast["formation"]) == ("Qe", "U-M/H", "Bullom Group")


def test_no_position_reads_no_ground():
    assert set(site_ground(None).values()) == {""}


# ----------------------------------------------------- the odds before the survey

def test_the_prior_odds_are_the_prior_with_no_evidence():
    survey = success_odds(SimpleNamespace(sounding_id="V1", fit_error_percent=None, water_zones=[], layers=[]),
                          None, "B-L", "pCm")
    o = prior_odds("B-L", "pCm")
    assert (o.prior, o.prior_low, o.prior_high, o.matched) == (survey.prior, survey.prior_low,
                                                              survey.prior_high, survey.matched)
    assert o.evidence == [] and o.posterior_odds == o.prior_odds
    assert math.isclose(o.probability, o.prior, rel_tol=1e-12)
    assert math.isclose(o.low, o.prior_low, rel_tol=1e-12) and math.isclose(o.high, o.prior_high, rel_tol=1e-12)
    assert odds_headline(o).startswith("About 43 percent (between 23 and 63)")


def test_the_prior_sentence_is_the_survey_odds_own():
    survey = success_odds(SimpleNamespace(sounding_id="V1", fit_error_percent=2.0, water_zones=[], layers=[]),
                          None, "B-L", "pCm")
    assert odds_point_text(survey)[1] == odds_prior_text(survey)
    assert odds_prior_text(prior_odds("B-L", "pCm")) == odds_prior_text(survey)


def test_ground_the_table_does_not_list_takes_the_placeholder():
    o = prior_odds(None, None)
    assert o.matched == "fallback"
    assert odds_headline(o).startswith("About 50 percent (between 10 and 90)")


# --------------------------------------------------------------- the content

def test_every_leaf_of_the_content_is_text_and_every_section_has_its_parts():
    points = parse_wpdx_records([_point(8.601, -11.9)])
    content = desk_study_content(SITE, "Rokel", INLAND, water_points=points,
                                 portfolio=[_summary(8.61, -11.9, community="A")])
    assert _strings(content)
    assert [s["key"] for s in content["sections"]] == ["ground", "terrain", "water_points", "projects", "odds",
                                                       "plan", "checks"]
    for section in content["sections"]:
        assert set(section) == {"key", "heading", "paragraphs", "tables", "figures", "bullets"}
    assert content["stamp"]["title"] == "PRE-FIELD DOCUMENT - NOT A SURVEY RESULT"
    assert content["title"] == "Desk study - Rokel"
    assert CITATIONS["wpdx"] in content["references"]


def test_the_site_rows_give_the_names_and_the_position_both_ways():
    rows = dict(desk_study_content(SITE, "Rokel", INLAND)["site_rows"])
    assert rows["Community"] == "Rokel" and rows["District"] == "Port Loko"
    assert rows["Position"] == "8.60000 N, 11.90000 W"
    u = geographic_to_utm(*INLAND)
    assert rows["UTM"] == f"zone {u.zone}N, {u.easting:.0f} E, {u.northing:.0f} N"
    blank = dict(desk_study_content(SimpleNamespace(community="", district="Bo"), "Bo", None)["site_rows"])
    assert "Community" not in blank and blank["Position"] == "No GPS position recorded"


def test_without_a_position_every_section_says_what_it_waits_for():
    content = desk_study_content(SITE, "Rokel", None, water_points=[], portfolio=[])
    assert _section(content, "ground")["paragraphs"] == [phrase("desk_study.ground_no_position")]
    assert _section(content, "water_points")["paragraphs"] == [phrase("desk_study.water_no_position")]
    assert _section(content, "projects")["paragraphs"] == [phrase("desk_study.projects_no_position")]
    assert phrase("desk_study.odds_no_position") in _section(content, "odds")["paragraphs"]
    assert phrase("desk_study.check_position") in _section(content, "checks")["bullets"]
    # the summary has only the odds to give
    assert content["summary"] == [odds_headline(prior_odds(None, None))]


def test_the_ground_table_names_both_maps_and_the_class_yields():
    rows = _section(desk_study_content(SITE, "Rokel", INLAND), "ground")["tables"][0]["rows"]
    assert rows[0][:2] == ["USGS Geologic Map of Africa", "Precambrian (pCm)"]
    assert rows[1][:2] == ["BGS Africa Groundwater Atlas", "Basement aquifer - low productivity (B-L)"]
    assert rows[1][2] == phrase("desk_study.ground_yield", q1=0.1, q3=0.5)


def test_a_site_on_surface_water_has_no_yield_range():
    rows = _section(desk_study_content(SITE, "T", (7.3, -11.8)), "ground")["tables"][0]["rows"]
    assert rows[1][2] == phrase("desk_study.ground_no_yield")


# --------------------------------------------------------- the water points

def test_water_points_counted_and_the_service_radius_read():
    lat, lon = INLAND
    points = parse_wpdx_records([
        _point(lat + 0.001, lon, "Functional", "Borehole", "Hand Pump", 2012, "a"),            # ~110 m, serves
        _point(lat + 0.003, lon, "Non-Functional", "Protected Shallow Well", "", 2008, "b"),  # ~330 m, rehab
        _point(lat - 0.002, lon, "", "", "Hand Pump", None, "c"),                              # unknown status
        _point(lat + 0.0, lon + 0.004, "Functional", "Surface Water (River)", "", None, "d"),  # unimproved
        _point(lat + 0.02, lon, "Functional", "Borehole", "", None, "e"),                      # 2.2 km, out
    ])
    section = _section(desk_study_content(SITE, "Rokel", INLAND, water_points=points), "water_points")
    assert section["paragraphs"][0] == phrase("desk_study.water_counts", total=4, radius=1000.0, working=2,
                                              broken=1, unknown=1)
    assert section["paragraphs"][1] == phrase("desk_study.water_serving", count=1, radius=500.0)
    assert section["paragraphs"][2] == phrase("desk_study.water_rehab", count=1, radius=500.0)
    rows = section["tables"][0]["rows"]
    # nearest first; the technology stands in for a blank source, as the browser shows it
    assert [r[1] for r in rows] == ["Working", "Unknown", "Not working", "Working"]
    assert rows[1][2] == "Hand Pump" and rows[0][3] == "2012" and rows[1][3] == ""


def test_the_nearest_working_source_when_none_serves():
    lat, lon = INLAND
    points = parse_wpdx_records([_point(lat + 0.006, lon, "Functional", "Borehole")])
    section = _section(desk_study_content(SITE, "Rokel", INLAND, water_points=points), "water_points")
    assert section["paragraphs"][1] == phrase("desk_study.water_nearest", distance=points_distance(points))
    broken = parse_wpdx_records([_point(lat + 0.006, lon, "Broken", "Borehole")])
    section = _section(desk_study_content(SITE, "Rokel", INLAND, water_points=broken), "water_points")
    assert section["paragraphs"][1] == phrase("desk_study.water_no_working", radius=1000.0)


def points_distance(points) -> float:
    from groundwater.waterpoints import points_within

    return points_within(points, INLAND[0], INLAND[1], 1e9)[0].distance_m


def test_more_water_points_than_are_listed_are_counted():
    lat, lon = INLAND
    points = parse_wpdx_records([_point(lat + 0.0003 * (k + 1), lon, row=str(k)) for k in range(20)])
    section = _section(desk_study_content(SITE, "Rokel", INLAND, water_points=points), "water_points")
    assert len(section["tables"][0]["rows"]) == WATER_POINTS_LISTED
    assert section["paragraphs"][-1] == phrase("desk_study.water_more", count=20 - WATER_POINTS_LISTED,
                                               radius=1000.0)


def test_water_points_not_loaded_and_none_found_are_told_apart():
    content = desk_study_content(SITE, "Rokel", INLAND)
    assert _section(content, "water_points")["paragraphs"] == [phrase("desk_study.water_not_loaded")]
    content = desk_study_content(SITE, "Rokel", INLAND, water_points=[], search_radius_m=750)
    assert _section(content, "water_points")["paragraphs"] == [phrase("desk_study.water_none", radius=750.0)]
    assert phrase("desk_study.summary_water_none", radius=750.0) in content["summary"]


# ------------------------------------------------------- the earlier projects

def test_earlier_projects_within_5_km_nearest_first():
    lat, lon = INLAND
    portfolio = [
        _summary(lat + 0.027, lon, community="Masanga", district="Tonkolili", status="Completed - successful",
                 total_depth_m=48.5, safe_yield_m3_per_h=1.8, water_verdict="pass", verdict_schema=2),
        _summary(lat - 0.009, lon, community="Rokel", status="dry", total_depth_m="62", water_verdict="fail"),
        _summary(lat + 0.054, lon, community="Far", status="Completed - successful"),
        {"community": "Nowhere", "status": "dry"},
    ]
    section = _section(desk_study_content(SITE, "Rokel", INLAND, portfolio=portfolio), "projects")
    assert PORTFOLIO_RADIUS_M == 5000.0
    assert section["paragraphs"] == [
        phrase("desk_study.projects_found", count=2, km=5.0, drilled=2, successful=1),
        phrase("desk_study.projects_unplaced", count=1)]
    rows = section["tables"][0]["rows"]
    assert [r[0] for r in rows] == ["Rokel", "Masanga (Tonkolili)"]
    assert rows[0][1] == "1.0" and rows[1][1] == "3.0"
    # a depth typed as text is read; a verdict from an older file is marked
    assert rows[0][3] == "62.0" and rows[0][5].endswith("*")
    assert rows[1][3:5] == ["48.5", "1.80"]


def test_no_portfolio_and_no_project_near_are_told_apart():
    content = desk_study_content(SITE, "Rokel", INLAND)
    assert _section(content, "projects")["paragraphs"] == [phrase("desk_study.projects_not_loaded")]
    content = desk_study_content(SITE, "Rokel", INLAND, portfolio=[])
    assert _section(content, "projects")["paragraphs"] == [phrase("desk_study.projects_none", km=5.0)]


# -------------------------------------------------------------- the terrain

@pytest.fixture(scope="module")
def l1():
    import make_reference as mr

    a, lin = mr._l1_run()
    return mr, a, lin


def test_what_the_desk_study_keeps_of_l1s_plans(l1):
    mr, a, lin = l1
    kept = [mr._desk_terrain(a, lin, mr.LINEAMENT_GENERATED, kase) for kase in mr.PLAN_CASES]
    first = kept[0]
    assert (first["candidates"], first["valleys"], first["ridges"]) == (12, 5, 7)
    totals = [lin.rose_valley_m[b] + lin.rose_ridge_m[b] for b in range(18)]
    assert first["band_low"] == 10.0 * totals.index(max(totals)) and first["band_high"] == first["band_low"] + 10
    assert [t["basis"] for t in kept[:4]] == ["candidates", "candidates", "candidates", "strike"]
    assert len(kept[1]["lines"]) == 2 and len(kept[3]["soundings"]) == 0
    assert kept[1]["lines"][0][0] == "Line 1" and kept[1]["soundings"][0][0] == "VES 1"
    assert set(first["captions"]) == {"lineaments", "rose", "plan", "plan_note"}
    assert json.loads(json.dumps(first)) == first


def test_terrain_with_no_plan_keeps_no_site(l1):
    _, a, lin = l1
    kept = desk_study_terrain(lin, None, a.core.lons, a.core.lats, {"lineaments": "L."}, "x.tif")
    assert kept["site"] is None and kept["lines"] == [] and kept["near"] is None


def test_the_terrain_and_plan_sections_from_a_kept_terrain(l1):
    mr, a, lin = l1
    kept = mr._desk_terrain(a, lin, mr.LINEAMENT_GENERATED, mr.PLAN_CASES[1])
    content = desk_study_content(SITE, "Kakua", tuple(kept["site"]), terrain=kept)
    terrain, plan = _section(content, "terrain"), _section(content, "plan")
    assert terrain["paragraphs"][0].endswith(phrase("desk_study.terrain_near", near=3, radius=500.0))
    assert [f["key"] for f in terrain["figures"]] == ["lineaments", "rose"]
    assert plan["paragraphs"] == [kept["captions"]["plan"]]
    assert [f["key"] for f in plan["figures"]] == ["plan"]
    assert [t["caption"] for t in plan["tables"]] == ["Profiling lines", "Proposed soundings"]
    bullets = _section(content, "checks")["bullets"]
    assert phrase("desk_study.check_candidates") in bullets and phrase("desk_study.check_pegs") in bullets
    assert phrase("desk_study.summary_terrain", candidates=12, lines=2, soundings=4) in content["summary"]


def test_a_strike_line_is_said_to_propose_no_sounding(l1):
    mr, a, lin = l1
    kept = mr._desk_terrain(a, lin, mr.LINEAMENT_GENERATED, mr.PLAN_CASES[3])
    content = desk_study_content(SITE, "Kakua", tuple(kept["site"]), terrain=kept)
    assert _section(content, "terrain")["paragraphs"][0].endswith(
        phrase("desk_study.terrain_near_none", radius=500.0))
    assert phrase("desk_study.summary_terrain_strike", candidates=12, radius=500.0) in content["summary"]
    assert phrase("desk_study.check_candidates") not in _section(content, "checks")["bullets"]


def test_terrain_laid_round_another_position_is_left_out(l1):
    mr, a, lin = l1
    kept = mr._desk_terrain(a, lin, mr.LINEAMENT_GENERATED, mr.PLAN_CASES[0])
    lat, lon = kept["site"]
    # within the metre it is the same site; 11 m off it is not
    near = desk_study_content(SITE, "Kakua", (lat + 0.000005, lon), terrain=kept)
    assert _section(near, "terrain")["paragraphs"][0] != phrase("desk_study.terrain_elsewhere")
    moved = desk_study_content(SITE, "Kakua", (lat + 0.0001, lon), terrain=kept)
    assert _section(moved, "terrain")["paragraphs"] == [phrase("desk_study.terrain_elsewhere")]
    assert _section(moved, "plan")["paragraphs"] == [phrase("desk_study.plan_no_terrain")]


def test_no_terrain_asks_for_one():
    content = desk_study_content(SITE, "Rokel", INLAND)
    assert _section(content, "terrain")["paragraphs"] == [phrase("desk_study.terrain_none")]
    assert phrase("desk_study.check_terrain") in _section(content, "checks")["bullets"]


# ------------------------------------------- the browser's engine, held to it

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
for await (const line of createInterface({ input: process.stdin })) {
  const r = JSON.parse(line);
  let answer;
  try {
    const points = r.water === null ? null : C.parseWpdxRecords(r.water);
    answer = { ok: C.deskStudyContent(r.site, r.where, r.latlon ? { lat: r.latlon[0], lon: r.latlon[1] } : null,
      { waterPoints: points, searchRadiusM: r.radius, portfolio: r.portfolio, terrain: r.terrain }) };
  } catch (e) {
    answer = { threw: String(e && e.stack || e) };
  }
  process.stdout.write(JSON.stringify(answer) + '\n');
}
"""


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path_factory.mktemp("desk") / "desk.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    process = subprocess.Popen([node, str(driver), str(JS)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8")

    def ask(request: dict) -> dict:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        assert line, "the Node driver stopped; its error is above"
        answer = json.loads(line)
        assert "threw" not in answer, answer["threw"]
        return answer["ok"]

    yield ask
    assert process.stdin is not None
    process.stdin.close()
    process.wait(timeout=60)


_STATUSES = ["Functional", "Non-Functional", "Broken", "", "Functional (in use)", "Abandoned"]
_SOURCES = [("Borehole", "Hand Pump"), ("Protected Shallow Well", ""), ("", "Hand Pump"),
            ("Surface Water (River/Stream)", ""), ("Protected Spring", ""), ("Piped Water", "Tap stand"),
            ("Unprotected Well", ""), ("", "")]
_PROJECT_STATUSES = ["Completed - successful", "dry", "sited", "in progress", "drilling", "", "abandoned"]
_VERDICTS = [("pass", 2), ("health_fail", 2), ("fail", None), ("aesthetic", 1), ("", None)]


def _terrain(rng, latlon) -> dict | None:
    """A terrain as desk_study_terrain keeps it, laid round the site, a
    little off it, far off it, or with no plan, by turns."""
    if rng.random() < 0.25:
        return None
    candidates = int(rng.integers(0, 30))
    valleys = int(rng.integers(0, candidates + 1))
    basis = ["candidates", "strike", "none"][int(rng.integers(0, 3))] if candidates else "none"
    lines = int(rng.integers(1, 4)) if basis != "none" else 0
    soundings = int(rng.integers(0, 3 * lines + 1)) if basis == "candidates" else 0
    band = int(rng.integers(0, 18))
    site = None
    if latlon is not None and rng.random() < 0.9:
        shift = [0.0, 0.000004, 0.0002][int(rng.integers(0, 3))]
        site = [latlon[0] + shift, latlon[1]]
    return {
        "label": "N08W012.tif", "site": site, "candidates": candidates, "valleys": valleys,
        "ridges": candidates - valleys, "km": float(rng.uniform(0.0, 60.0)), "band_low": band * 10.0,
        "band_high": band * 10.0 + 10.0, "band_km": float(rng.uniform(0.0, 9.0)),
        "near": int(rng.integers(0, candidates + 1)) if site is not None else None,
        "basis": basis if site is not None else None,
        "captions": {key: f"The {key} caption." for key in ("relief", "lineaments", "rose", "plan", "plan_note")
                     if rng.random() < 0.85},
        "lines": [[f"Line {k + 1}", "103", "400", "8.51095 N, 11.99064 W", "8.51015 N, 11.98710 W"]
                  for k in range(lines)] if site is not None else [],
        "soundings": [[f"VES {k + 1}", "1", "150.0", "8.51160 N, 11.98620 W", "On the ridge candidate 6."]
                      for k in range(soundings)] if site is not None else [],
    }


#: Seeds whose position is pinned: on mapped surface water, where the prior
#: table has no yield range, and on the Bullom Group.
_PINNED = {7: (7.3, -11.8), 11: LUNGI}


def _case(seed: int) -> dict:
    """A seeded desk study: a position over the country (or none), WPdx+
    rows round it, earlier projects round it, a radius, and a terrain."""
    rng = np.random.default_rng(4400 + seed)
    latlon = None if rng.random() < 0.12 else [float(rng.uniform(6.95, 9.95)), float(rng.uniform(-13.25, -10.3))]
    # two kinds of ground a position drawn over the country seldom lands on
    if seed in _PINNED:
        latlon = list(_PINNED[seed])
    water = None
    if latlon is not None and rng.random() < 0.85:
        water = []
        for k in range(int(rng.integers(0, 24))):
            source, technology = _SOURCES[int(rng.integers(0, len(_SOURCES)))]
            year = [None, int(rng.integers(1980, 2024)), str(int(rng.integers(1980, 2024)))][int(rng.integers(0, 3))]
            water.append(_point(latlon[0] + float(rng.normal(0.0, 0.006)), latlon[1] + float(rng.normal(0.0, 0.006)),
                                _STATUSES[int(rng.integers(0, len(_STATUSES)))], source, technology, year, str(k)))
    portfolio = None
    if latlon is not None and rng.random() < 0.8:
        portfolio = []
        for k in range(int(rng.integers(0, 9))):
            verdict, schema = _VERDICTS[int(rng.integers(0, len(_VERDICTS)))]
            fields = {"community": ["Masanga", "", "Rokel"][k % 3], "district": ["Bo", "", "Kenema"][k % 3],
                      "status": _PROJECT_STATUSES[int(rng.integers(0, len(_PROJECT_STATUSES)))],
                      "total_depth_m": [None, float(rng.uniform(20, 90)), "55"][int(rng.integers(0, 3))],
                      "safe_yield_m3_per_h": [None, float(rng.uniform(0.2, 4.0))][int(rng.integers(0, 2))],
                      "water_verdict": verdict, "verdict_schema": schema}
            if rng.random() < 0.15:
                portfolio.append(fields)
            else:
                summary = _summary(latlon[0] + float(rng.normal(0.0, 0.03)), latlon[1] + float(rng.normal(0.0, 0.03)),
                                   **fields)
                if rng.random() < 0.2:
                    summary["utm_zone"] = None
                portfolio.append(summary)
    return {"site": {"community": ["Rokel", "", "Kamaranka"][seed % 3], "chiefdom": ["Maforki", ""][seed % 2],
                     "district": ["Port Loko", "", "Bo"][seed % 3]},
            "where": "Kakua", "latlon": latlon, "water": water, "radius": [1000.0, 500.0, 1500.0][seed % 3],
            "portfolio": portfolio, "terrain": _terrain(rng, latlon)}


def _python(case: dict) -> dict:
    points = None if case["water"] is None else parse_wpdx_records(case["water"])
    return desk_study_content(SimpleNamespace(**case["site"]), case["where"],
                              tuple(case["latlon"]) if case["latlon"] else None, water_points=points,
                              search_radius_m=case["radius"], portfolio=case["portfolio"], terrain=case["terrain"])


SEEDS = range(60)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_browser_puts_the_same_desk_study_together(browser, seed):
    case = _case(seed)
    assert browser(case) == _python(case)


def test_the_seeded_cases_reach_every_rule():
    """The cases above go down every road the content can take."""
    told = json.dumps([_python(_case(seed)) for seed in SEEDS])
    for key, values in [
        ("ground_no_position", {}), ("water_not_loaded", {}), ("water_no_position", {}),
        ("projects_not_loaded", {}), ("projects_no_position", {}), ("terrain_none", {}),
        ("terrain_elsewhere", {}), ("plan_no_terrain", {}), ("check_rehab", {}), ("check_candidates", {}),
        ("check_pegs", {}), ("water_depth", {}), ("odds_no_position", {}), ("ground_no_yield", {}),
    ]:
        assert json.dumps(phrase(f"desk_study.{key}", **values))[1:-1] in told, key
    for marker in ["recorded as not working:", "so the community may already be served",
                   "The nearest working improved source is", "No working improved source is recorded",
                   "further away than the last listed", "carries no position", "carry no position",
                   "of them come within", "None of them comes within", "proposes no sounding",
                   "no profiling line could be laid", "was analysed over the square",
                   "and no lineament candidate was found", "drilled,", "Bullom Group", "Precambrian basement"]:
        assert marker in told, marker

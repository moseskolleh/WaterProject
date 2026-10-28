"""The survey plan: profiling lines across the lineament candidates near the
site and the soundings proposed on them (PLAN.md step 4.3,
groundwater/mapping/survey.py).

The first half holds the Python module to its rules on candidates, water
points, drainage lines and sea placed for the purpose in a window's frame:
a line crosses the nearest candidate at right angles, through the site
where it can, inside the service radius; the soundings sit on the
candidate and to either side, and are moved clear of a separation ring or
left out; a candidate already crossed gets no line of its own; with no
candidate near, one line crosses the dominant strike through the site;
settings out of range are refused; and the GPX, the GeoJSON, the GeoLibre
project and the captions say what the plan is.

The second half runs the browser's engine (C.surveyPlan and the functions
beside it in docs/js/gwt-core.js) in a Node vm on seeded cases and holds it
to the Python one to the bit: every line, sounding and reason, the
captions, and the bytes of the GPX and the GeoJSON.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import math
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from groundwater.config import TerrainConfig
from groundwater.mapping import geolibre
from groundwater.mapping.lineaments import ROSE_BANDS, Lineament, LineamentAnalysis, lineament_lonlat
from groundwater.mapping.survey import (
    BOREHOLE,
    COAST,
    DUG_WELL,
    STREAM,
    line_station,
    survey_plan,
    survey_plan_captions,
    survey_plan_geojson,
    survey_plan_gpx,
    water_point_kind,
)
from groundwater.mapping.terrain_analysis import LAND, SEA
from groundwater.waterpoints import SERVICE_RADIUS_M, WaterPoint

JS = Path(__file__).resolve().parents[1] / "docs" / "js"
LON0, LAT0 = -11.5, 8.5
STEP = 1 / 3600
FRAME = (30.0, 30.0)
GPX = {"g": "http://www.topografix.com/GPX/1/1"}
META = {"where": "Kakua", "label": "a window built for the test", "site_label": "Rokel"}


# ---------------------------------------------------------------------------
# Inputs placed for the purpose, in a window's frame
# ---------------------------------------------------------------------------

def _core(rows: int = 120, cols: int = 120, shown=None, sea=None) -> SimpleNamespace:
    """What the plan reads of an analysis's core: the classes, the cell
    centres and the square shown. ``sea`` is a (rows, cols) pair of slices
    made sea."""
    cls = np.full((rows, cols), LAND, dtype=np.uint8)
    if sea is not None:
        cls[sea] = SEA
    return SimpleNamespace(rows=rows, cols=cols, shown=shown or (0, rows, 0, cols), cls=cls,
                           lons=LON0 + np.arange(cols) * STEP, lats=LAT0 + np.arange(rows) * STEP)


def _lonlat(x: float, y: float) -> tuple[float, float]:
    """A point of the frame as the plan is given one, longitude first."""
    return LON0 + x / FRAME[0] * STEP, LAT0 + y / FRAME[1] * STEP


def _candidate(id_: int, kind: str, start, end) -> Lineament:
    """A candidate from ``start`` to ``end``, its strike clockwise from
    north, from 0 to under 180, and its start the southern end."""
    if (end[1], end[0]) < (start[1], start[0]):
        start, end = end, start
    dx, dy = end[0] - start[0], end[1] - start[1]
    strike = math.degrees(math.atan2(dx, dy)) % 180.0
    return Lineament(id_, kind, tuple(map(float, start)), tuple(map(float, end)), math.hypot(dx, dy), strike, 1, 10,
                     False)


def _candidates(items, cfg: TerrainConfig | None = None) -> LineamentAnalysis:
    rose = {"valley": [0.0] * ROSE_BANDS, "ridge": [0.0] * ROSE_BANDS}
    count = {"valley": [0] * ROSE_BANDS, "ridge": [0] * ROSE_BANDS}
    for item in items:
        band = min(int(item.strike_deg // 10.0), ROSE_BANDS - 1)
        rose[item.kind][band] += item.length_m
        count[item.kind][band] += 1
    return LineamentAnalysis(tuple(items), tuple(rose["valley"]), tuple(rose["ridge"]), tuple(count["valley"]),
                             tuple(count["ridge"]), FRAME, (0, 120, 0, 120), {}, cfg or TerrainConfig())


def _water(x: float, y: float, source: str, technology: str = "") -> WaterPoint:
    lon, lat = _lonlat(x, y)
    return WaterPoint("wp", lat, lon, True, "Functional", source, technology, None, "")


def _part(*cells) -> SimpleNamespace:
    return SimpleNamespace(vertices=tuple(cells))


def _segment_distance(point, a, b) -> float:
    ex, ey = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((point[0] - a[0]) * ex + (point[1] - a[1]) * ey) / (ex * ex + ey * ey)))
    return math.hypot(point[0] - (a[0] + t * ex), point[1] - (a[1] + t * ey))


SITE = (1800.0, 1800.0)


def _plan(items, water=(), parts=(), core=None, cfg=None, site=SITE):
    return survey_plan(_candidates(items, cfg), core or _core(), parts, _lonlat(*site), water, cfg)


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

def test_a_line_crosses_the_nearest_candidate_at_right_angles_through_the_site():
    """A valley striking 30 degrees 200 m from the site is crossed by a line
    at 120 degrees through its point nearest the site, which puts the site
    on the line: 400 m long, a station every 10 m, the crossing a station of
    it at its middle. The soundings are on the valley and 50 m along the
    line either side of it, the spread laid along the valley, each inside
    the service radius; the AB/2 series reaches the 60 m target."""
    sx, sy = SITE
    ux, uy = math.sin(math.radians(30.0)), math.cos(math.radians(30.0))
    foot = (sx + 200.0 * uy, sy - 200.0 * ux)          # 200 m from the site, at right angles
    valley = _candidate(0, "valley", (foot[0] - 900 * ux, foot[1] - 900 * uy), (foot[0] + 900 * ux, foot[1] + 900 * uy))
    plan = _plan([valley])
    assert plan.basis == "candidates" and plan.near == (0,) and plan.skipped == ()
    line, = plan.lines
    assert line.candidate == 0 and line.kind == "valley"
    assert line.bearing_deg == pytest.approx(120.0)
    assert line.length_m == 400.0 and line.last - line.first == 40 and line.crossing_m == 200.0
    assert not line.shortened
    assert _segment_distance(SITE, line_station(line, line.first), line_station(line, line.last)) < 1e-6
    assert math.dist(line_station(line, 0), foot) < 1e-6
    stations = [line_station(line, k) for k in range(line.first, line.last + 1)]
    assert all(math.dist(a, b) == pytest.approx(10.0) for a, b in zip(stations, stations[1:], strict=False))
    assert all(math.dist(p, SITE) <= SERVICE_RADIUS_M for p in stations)
    assert [(x.role, x.at_m, x.moved_m) for x in plan.soundings] == [
        ("flank", 150.0, 0.0), ("crossing", 200.0, 0.0), ("flank", 250.0, 0.0)]
    assert _segment_distance(plan.soundings[1].point, valley.start, valley.end) < 1e-6
    assert [round(_segment_distance(x.point, valley.start, valley.end), 6) for x in plan.soundings] == [50, 0, 50]
    assert all(x.spread_deg == valley.strike_deg for x in plan.soundings)
    assert plan.ab2["max_ab2"] == 120 and plan.ab2["investigation_m"] >= 60.0 and not plan.ab2["capped"]
    assert plan.dropped == () and plan.covered


def test_a_line_keeps_inside_the_service_radius_and_a_short_candidate_is_crossed_at_its_end():
    """A candidate 450 m from the site leaves 50 m beyond it inside the
    radius, so its line runs from there back towards the site, the crossing
    still a station; a candidate that ends short of its point nearest the
    site is crossed at its end, by a line that no longer runs through the
    site and is shortened where the radius leaves less room."""
    sx, sy = SITE
    far = _candidate(0, "ridge", (sx + 450.0, sy - 800.0), (sx + 450.0, sy + 800.0))
    line, = _plan([far]).lines
    assert line.bearing_deg == 90.0 and line.length_m == 400.0
    assert line.last == 5 and line.first == -35 and line.crossing_m == 350.0
    assert all(math.dist(line_station(line, k), SITE) <= SERVICE_RADIUS_M for k in (line.first, line.last))
    # its end 480 m from the site, where the radius leaves a chord of 341 m
    ending = _candidate(1, "valley", (sx + 100.0, sy + 470.0), (sx + 100.0, sy + 1400.0))
    plan = _plan([ending])
    line, = plan.lines
    assert math.dist(line_station(line, 0), ending.start) < 1e-9
    assert line.shortened and line.length_m < 400.0
    assert all(math.dist(line_station(line, k), SITE) <= SERVICE_RADIUS_M + 1e-9 for k in range(line.first,
                                                                                                    line.last + 1))
    assert _segment_distance(SITE, line_station(line, line.first), line_station(line, line.last)) > 100.0


def test_candidates_are_crossed_nearest_first_and_one_crossed_already_gets_no_line():
    """Of three candidates within the radius, the nearest is crossed first;
    a second parallel to it that its line already crosses at right angles
    gets no line of its own, and says which line crosses it; the third, at
    another strike, gets the second line; a fourth beyond the radius is not
    near at all, and survey_lines caps the lines laid."""
    sx, sy = SITE
    first = _candidate(0, "valley", (sx + 60.0, sy - 900.0), (sx + 60.0, sy + 900.0))
    twin = _candidate(1, "ridge", (sx - 100.0, sy - 900.0), (sx - 100.0, sy + 900.0))
    other = _candidate(2, "valley", (sx - 900.0, sy + 250.0), (sx + 900.0, sy + 250.0))
    beyond = _candidate(3, "valley", (sx + 700.0, sy - 900.0), (sx + 700.0, sy + 900.0))
    plan = _plan([other, beyond, twin, first])
    assert plan.near == (0, 1, 2)
    assert [line.candidate for line in plan.lines] == [0, 2]
    assert plan.skipped == ((1, 1),)
    assert [c[0] for c in plan.lines[0].crosses] == [1]
    assert plan.lines[0].crosses[0][1] == pytest.approx(plan.lines[0].crossing_m - 160.0)
    assert [x.line for x in plan.soundings] == [1, 1, 1, 2, 2, 2]
    one = _plan([other, twin, first], cfg=dataclasses.replace(TerrainConfig(), survey_lines=1))
    assert [line.candidate for line in one.lines] == [0]


def test_a_sounding_is_moved_clear_of_a_ring_or_left_out_with_its_reason():
    """A borehole 30 m from the crossing puts it inside the borehole's 50 m:
    the sounding moves along its line to the ring's edge, no further than
    20 m, and says what it cleared; the flank on the borehole's side has no
    clear place within 20 m and is left out, naming the borehole. A dug
    well's ring is 20 m and another water point's 10 m."""
    sx, sy = SITE
    valley = _candidate(0, "valley", (sx + 100.0, sy - 900.0), (sx + 100.0, sy + 900.0))
    plan = _plan([valley], water=[_water(sx + 130.0, sy, "Borehole", "Hand Pump - India Mark II")])
    assert plan.reach["borehole"] == 1 and plan.rings == ((pytest.approx(sx + 130.0), pytest.approx(sy), BOREHOLE,
                                                           50.0),)
    crossing = next(x for x in plan.soundings if x.role == "crossing")
    assert crossing.cleared == (BOREHOLE,)
    assert -20.0 <= crossing.moved_m < 0.0
    assert math.dist(crossing.point, (sx + 130.0, sy)) == pytest.approx(50.0)
    assert [(d.role, d.reasons) for d in plan.dropped] == [("flank", (BOREHOLE,))]
    assert len(plan.soundings) == 2
    captions = survey_plan_captions(plan, "Kakua")["plan"]
    assert "1 sounding was moved along its line, by up to" in captions
    assert "1 sounding is left out, as no place within 20 m" in captions
    assert "at least 50 m from 1 mapped borehole" in captions
    well = _plan([valley], water=[_water(sx + 110.0, sy, "Protected Shallow Well")])
    crossing = next(x for x in well.soundings if x.role == "crossing")
    assert crossing.cleared == (DUG_WELL,) and abs(crossing.moved_m) == pytest.approx(10.0)
    tap = _plan([valley], water=[_water(sx + 105.0, sy, "Piped Water", "Tap stand")])
    crossing = next(x for x in tap.soundings if x.role == "crossing")
    assert abs(crossing.moved_m) == pytest.approx(5.0)


def test_soundings_keep_clear_of_the_drainage_lines_and_the_sea():
    """A drainage line along the valley stands for its stream, so the
    sounding on the valley moves 20 m off it; and the sea within 1000 m of
    the radius's edge keeps every sounding 1000 m from its nearest cell,
    leaving out those with no clear place."""
    sx, sy = SITE
    valley = _candidate(0, "valley", (sx + 120.0, sy - 900.0), (sx + 120.0, sy + 900.0))
    col = (sx + 120.0) / FRAME[0]
    stream = _part(*[(r, int(col)) for r in range(30, 90)])
    plan = _plan([valley], parts=[stream])
    assert plan.reach["streams"] > 0
    for x in plan.soundings:
        assert min(_segment_distance(x.point, (c * FRAME[0], r * FRAME[1]), (c2 * FRAME[0], r2 * FRAME[1]))
                   for (r, c), (r2, c2) in zip(stream.vertices, stream.vertices[1:], strict=False)) >= 20.0 - 1e-9
    crossing = next(x for x in plan.soundings if x.role == "crossing")
    assert crossing.cleared == (STREAM,) and crossing.moved_m != 0.0
    # sea in the window's eastern columns, 1100 m east of the site
    core = _core(sea=(slice(None), slice(97, None)))
    plan = _plan([valley], core=core)
    assert plan.reach["sea"] > 0
    assert all(min(math.dist(x.point, (c * FRAME[0], r * FRAME[1])) for r in range(120) for c in range(97, 120))
               >= 1000.0 - 1e-9 for x in plan.soundings)
    assert [d.reasons for d in plan.dropped] == [(COAST,)]


def test_with_no_candidate_near_one_line_crosses_the_dominant_strike_and_with_none_there_is_no_plan():
    """Candidates that all lie beyond the service radius leave one line
    through the site, at right angles to the middle of the 10-degree band
    that holds most of their length, and no sounding; a window with no
    candidate at all has no line. Each says so."""
    sx, sy = SITE
    far = [_candidate(0, "valley", (sx + 800.0, sy - 900.0), (sx + 1100.0, sy + 900.0)),
           _candidate(1, "ridge", (sx - 900.0, sy + 900.0), (sx + 900.0, sy + 950.0))]
    plan = _plan(far)
    assert plan.basis == "strike" and plan.near == () and plan.soundings == ()
    line, = plan.lines
    band = int(far[0].strike_deg // 10)
    assert line.candidate is None and line.strike_deg == band * 10.0 + 5.0
    assert line_station(line, 0) == pytest.approx(SITE)
    assert line.crossing_m == 200.0
    text = survey_plan_captions(plan, "Kakua")["plan"]
    assert text.startswith(f"No lineament candidate comes within the 500 m the site serves, so the profiling line "
                           f"runs through the site at right angles to {band * 10 + 5}°")
    none = _plan([])
    assert none.basis == "none" and none.lines == ()
    assert survey_plan_captions(none, "Kakua")["plan"].startswith("No lineament candidate is found in the square shown")


def test_the_plan_says_what_it_rests_on_what_it_kept_clear_of_and_what_to_check_on_the_ground():
    """The caption names the radius, the lines, the soundings' AB/2 and
    spread, what each sounding was kept clear of, that no water points were
    given where none were, the separation rows no map here records, and that
    the square shown did not reach the whole radius where it did not; with
    no plan at all, for a site with no fix, it says why."""
    sx, sy = SITE
    valley = _candidate(0, "valley", (sx + 100.0, sy - 900.0), (sx + 100.0, sy + 900.0))
    captions = survey_plan_captions(_plan([valley]), "Kakua")
    assert captions["title_plan"] == "Survey plan - Kakua"
    assert "not confirmed by geophysics" in captions["plan_note"]
    text = captions["plan"]
    assert "1 profiling line crosses the lineament candidate nearest the site at right angles to its strike" in text
    assert "Each is planned to AB/2 = 120 m, which by the depth-of-investigation rule sees 60 m down" in text
    assert "No water points were loaded when the terrain was analysed" in text
    assert "No water point, drainage line or sea that this page maps lies within reach" in text
    assert ("No map here records septic tank or soakaway (20 m), buildings (3 m) and solid waste dump or burial "
            "ground (1000 m)") in text
    assert "does not hold the whole service radius" not in text
    edge = _plan([valley], core=_core(shown=(0, 120, 50, 120)))
    assert not edge.covered
    assert "does not hold the whole service radius" in survey_plan_captions(edge, "Kakua")["plan"]
    assert survey_plan_captions(None, "Kakua") == {
        "plan": "A survey plan needs the site's GPS position: its lines and soundings are laid out within 500 m of "
                "the site, and without a position there is nothing to measure that from."}


def test_a_lookup_short_of_a_rings_reach_is_said_and_one_that_reaches_is_not():
    """A sounding inside the 500 m the site serves is kept 50 m from a
    borehole up to 550 m from the site, but a lookup at 500 m never loads a
    borehole 515 m off: the plan left the crossing sounding 45 m from it and
    said every sounding was kept 50 m from the one borehole it was given.
    Told how far the water points were looked up, it says the lookup fell
    short and what to do; a lookup that reached 550 m, or an inventory not
    cut to a circle, says nothing of it; a lookup that found nothing within
    its radius is not told it loaded nothing."""
    sx, sy = SITE
    valley = _candidate(0, "valley", (sx + 470.0, sy - 900.0), (sx + 470.0, sy + 900.0))
    far = _water(sx + 515.0, sy, "Borehole", "Hand Pump")
    near = _water(sx - 300.0, sy + 300.0, "Borehole", "Hand Pump")
    short = "The water points were looked up no further than 500 m round the site, short of the 550 m within which "
    lin, site = _candidates([valley]), _lonlat(*SITE)

    def caption(water, searched):
        plan = survey_plan(lin, _core(), (), site, water, None, searched_m=searched)
        crossing = next(x for x in plan.soundings if x.role == "crossing")
        return plan, crossing, survey_plan_captions(plan, "Kakua")["plan"]

    plan, crossing, text = caption([near], 500.0)
    assert plan.searched_m == 500.0 and crossing.moved_m == 0.0
    assert short + ("a mapped water point's separation distance can reach a sounding, so a peg may lie too near "
                    "one that was not loaded: look the water points up again over at least 550 m and analyse the "
                    "terrain again, or check each peg on the ground.") in text
    plan, crossing, text = caption([near, far], 1000.0)
    assert crossing.moved_m == pytest.approx(-5.0) and "looked up no further" not in text
    assert "looked up no further" not in caption([near, far], 550.0)[2]
    assert "no further than 549 m round the site, short of the 550 m" in caption([near, far], 549.9)[2]
    # to the millimetre: a hair short of 300 m is 300 m, a hair short of 550 m is no shortfall
    assert "no further than 300 m round the site" in caption([near], 299.99999998)[2]
    assert "looked up no further" not in caption([near, far], 549.99999998)[2]
    _, _, text = caption([near], None)
    assert "looked up no further" not in text and "No water points were loaded" not in text
    _, _, text = caption([], 750.0)
    assert "No water points were loaded" not in text and "looked up no further" not in text
    assert "No water point, drainage line or sea that this page maps lies within reach" in text
    _, _, text = caption([], 250.0)
    assert "No water point loaded, and no drainage line or sea that this page maps, lies within reach" in text
    assert "no further than 250 m round the site" in text
    assert "No water points were loaded when the terrain was analysed" in caption([], None)[2]
    with pytest.raises(ValueError, match="looked up within must be 0 m or more"):
        survey_plan(lin, _core(), (), site, [], None, searched_m=-1.0)


@pytest.mark.parametrize(("source", "technology", "kind"), [
    ("Borehole/Tubewell", "Hand Pump - India Mark II", "borehole"),
    ("Protected Shallow Well", "", "dug_well"),
    ("Unprotected Well", "Bucket", "dug_well"),
    ("", "Tube well", "borehole"),
    ("Surface Water (River/Stream/Lake/Pond/Dam)", "", "surface"),
    ("Protected Spring", "", "other"),
    ("Piped Water", "Tap stand", "other"),
    ("Rainwater Harvesting", "", "other"),
])
def test_a_water_point_is_kept_clear_of_by_what_it_is(source, technology, kind):
    assert water_point_kind(SimpleNamespace(source=source, technology=technology)) == kind


@pytest.mark.parametrize(("settings", "message"), [
    ({"survey_lines": 0}, "terrain.survey_lines must be a whole number of 1 or more"),
    ({"survey_lines": 1.5}, "terrain.survey_lines must be a whole number of 1 or more"),
    ({"survey_line_m": 0.0}, "terrain.survey_line_m must be a number above 0"),
    ({"survey_station_m": -10.0}, "terrain.survey_station_m must be a number above 0"),
    ({"survey_flank_m": math.inf}, "terrain.survey_flank_m must be a number above 0"),
    ({"survey_target_depth_m": math.nan}, "terrain.survey_target_depth_m must be a number above 0"),
    ({"survey_move_m": 25.0}, "terrain.survey_move_m must be 0 or more and under half of terrain.survey_flank_m"),
    ({"survey_move_m": -1.0}, "terrain.survey_move_m must be 0 or more and under half of terrain.survey_flank_m"),
    ({"survey_cross_within_deg": 90.0},
     "terrain.survey_cross_within_deg must be 0 or more and under 90 degrees"),
    ({"survey_station_m": 500.0}, "terrain.survey_station_m must be no longer than terrain.survey_line_m"),
])
def test_settings_out_of_range_are_refused(settings, message):
    with pytest.raises(ValueError) as refused:
        _plan([], cfg=dataclasses.replace(TerrainConfig(), **settings))
    assert str(refused.value) == message


def test_the_gpx_names_every_peg_and_the_geojson_takes_apart_into_the_geolibre_layers():
    """The GPX is well-formed GPX 1.1: the site, each sounding and each
    line's ends as waypoints, each line as a route with a point at each
    station named by its distance along it, zero-padded; text is escaped.
    The GeoJSON holds the service radius, the ring round each water point
    within reach, the lines, the stations and the soundings, each naming its
    layer, and the GeoLibre project takes it apart into those layers over
    the candidates and the water points near the site, and opens on the
    service radius."""
    sx, sy = SITE
    valley = _candidate(0, "valley", (sx + 100.0, sy - 900.0), (sx + 100.0, sy + 900.0))
    water = [_water(sx + 130.0, sy, "Borehole")]
    plan = _plan([valley], water=water)
    lons, lats = _core().lons, _core().lats
    gpx = ET.fromstring(survey_plan_gpx(plan, lons, lats, dict(META, site_label="Rokel & <Sons>")).encode())
    assert gpx.tag == "{http://www.topografix.com/GPX/1/1}gpx" and gpx.get("version") == "1.1"
    assert gpx.findtext("g:metadata/g:name", namespaces=GPX) == "Survey plan - Kakua"
    names = [w.findtext("g:name", namespaces=GPX) for w in gpx.findall("g:wpt", GPX)]
    assert names == ["Rokel & <Sons>", "VES 1", "VES 2", "Line 1 start", "Line 1 end"]
    route, = gpx.findall("g:rte", GPX)
    points = route.findall("g:rtept", GPX)
    assert [p.findtext("g:name", namespaces=GPX) for p in points][:3] == ["L1 000", "L1 010", "L1 020"]
    assert points[-1].findtext("g:name", namespaces=GPX) == "L1 400" and len(points) == 41
    ves = gpx.findall("g:wpt", GPX)[1]
    lon, lat = lineament_lonlat(plan, lons, lats, plan.soundings[0].point)
    assert ves.get("lat") == f"{lat:.6f}" and ves.get("lon") == f"{lon:.6f}"
    assert "AB/2 to 120 m: the 240 m spread laid along 0°." in ves.findtext("g:desc", namespaces=GPX)

    text = survey_plan_geojson(plan, lons, lats, META)
    collection = json.loads(text)
    layers = [f["properties"]["layer"] for f in collection["features"]]
    assert layers == ["service_radius", "clearance", "line"] + ["station"] * 41 + ["sounding"] * 2
    ring = collection["features"][0]["geometry"]["coordinates"][0]
    assert len(ring) == 65 and ring[0] == ring[-1]
    assert collection["radius_m"] == 500 and "not confirmed by geophysics" in collection["description"]

    candidates = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"lineament": 0, "kind": "valley"},
         "geometry": {"type": "LineString", "coordinates": [list(lineament_lonlat(plan, lons, lats, valley.start)),
                                                             list(lineament_lonlat(plan, lons, lats, valley.end))]}},
        {"type": "Feature", "properties": {"lineament": 1, "kind": "ridge"},
         "geometry": {"type": "LineString", "coordinates": [[-11.0, 9.0], [-10.9, 9.1]]}}]})
    project = geolibre.survey_plan_project(text, lineament_geojson=candidates, water_points=water)
    assert [(layer["name"], len(layer["geojson"]["features"])) for layer in project["layers"]] == [
        ("Lineament candidates", 1), ("Existing water points", 1), ("Separation rings", 1), ("Service radius", 1),
        ("Profiling lines", 1), ("Profile stations", 41), ("Proposed soundings", 2)]
    assert project["name"] == "Survey plan"
    lon, lat = collection["site"]
    west, south, east, north = project["mapView"]["bbox"]
    assert west < lon < east and south < lat < north and east - west < 0.02
    assert any("Water Point Data Exchange" in credit for credit in project["metadata"]["attribution"])
    assert project["layers"][4]["geojson"]["features"][0]["properties"]["stroke"] == "#5B2A86"


def test_the_plan_on_an_analysed_window_keeps_clear_of_its_drainage_lines(tmp_path):
    """On the window the lineament figures are tested on (a valley due north
    and a ridge at 45 degrees), the plan round a site between them crosses
    both, and no proposed sounding lies within 20 m of a drainage line; the
    figure draws it, as PNG and SVG, with its title and its note inside."""
    from test_study_area_maps import _lineament_analysis

    from groundwater.mapping import lineament_captions, plot_survey_plan, terrain_captions

    analysis, lineaments = _lineament_analysis()
    core = analysis.core
    site = (float(core.lons[70]), float(core.lats[80]))
    plan = survey_plan(lineaments, core, analysis.parts, site)
    assert [(line.candidate, line.kind) for line in plan.lines] == [(0, "valley"), (1, "ridge")]
    dx, dy = lineaments.frame
    for x in plan.soundings:
        for part in analysis.parts:
            for (r, c), (r2, c2) in zip(part.vertices, part.vertices[1:], strict=False):
                assert _segment_distance(x.point, (c * dx, r * dy), (c2 * dx, r2 * dy)) >= 20.0 - 1e-9
    captions = {**terrain_captions(analysis, None, "Kakua"), **lineament_captions(lineaments, "Kakua"),
                **survey_plan_captions(plan, "Kakua")}
    png = plot_survey_plan(analysis, captions, None, tmp_path / "plan.png", svg=True, lineaments=lineaments,
                           plan=plan)
    svg = png.with_suffix(".svg").read_text(encoding="utf-8")
    assert png.stat().st_size > 20_000
    for text in ("Survey plan - Kakua", "Profiling line", "Proposed sounding", "Separation ring", "Service radius",
                 "every peg is a proposal"):
        assert text in " ".join(svg.split()), text
    # the lines' names and the soundings' numbers, drawn with a halo, are
    # paths in the SVG, so they are read off the figure
    import matplotlib.pyplot as plt

    fig = plot_survey_plan(analysis, captions, None, lineaments=lineaments, plan=plan)
    drawn = [t.get_text().strip() for t in fig.axes[0].texts if t.get_color() == "#5B2A86"]
    plt.close(fig)
    assert drawn == ["Line 1", "Line 2"] + [str(x.id) for x in plan.soundings]


# ---------------------------------------------------------------------------
# The browser's engine, held to the Python one to the bit
# ---------------------------------------------------------------------------

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone });
for (const f of ['gwt-data.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const F64 = vm.runInContext('Float64Array', sandbox), U8 = vm.runInContext('Uint8Array', sandbox);
const f64 = (b64) => new F64(new Uint8Array(Buffer.from(b64, 'base64')).buffer);
const hex = (v) => {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, Number(v));
  let out = '';
  for (let i = 0; i < 8; i++) out += view.getUint8(i).toString(16).padStart(2, '0');
  return out;
};
const pair = (p) => p.map(hex);
const ops = {
  plan(r) {
    const cfg = C.defaultConfig();
    const terrain = Object.assign({}, cfg.terrain, r.settings);
    const lineaments = { lineaments: r.lineaments, frame: r.frame, roseValleyM: r.roseValleyM,
      roseRidgeM: r.roseRidgeM, settings: terrain };
    const core = { rows: r.rows, cols: r.cols, shown: r.shown, lons: f64(r.lons), lats: f64(r.lats),
      cls: new U8(Buffer.from(r.cls, 'base64')) };
    let plan;
    try {
      plan = C.surveyPlan(lineaments, core, r.parts, r.site, r.water, terrain, cfg.ves, undefined, r.searched);
    } catch (e) {
      return { refused: String(e && e.message) };
    }
    return {
      basis: plan.basis, site: pair(plan.site), near: plan.near, skipped: plan.skipped, reach: plan.reach,
      covered: plan.covered, water_points: plan.water_points,
      rings: plan.rings.map((g) => [hex(g[0]), hex(g[1]), g[2], hex(g[3])]),
      lines: plan.lines.map((l) => [l.id, l.candidate, l.kind, hex(l.strike_deg), hex(l.bearing_deg), pair(l.origin),
        pair(l.direction), l.first, l.last, hex(l.length_m), hex(l.crossing_m),
        l.crosses.map((c) => [c[0], hex(c[1])]), l.shortened]),
      soundings: plan.soundings.map((x) => [x.id, x.line, x.role, hex(x.at_m), pair(x.point), hex(x.moved_m), x.cleared,
        hex(x.spread_deg)]),
      dropped: plan.dropped.map((d) => [d.line, d.role, hex(d.at_m), d.reasons]),
      captions: C.surveyPlanCaptions(plan, r.where),
      gpx: C.surveyPlanGpx(plan, core.lons, core.lats, r.meta),
      geojson: C.surveyPlanGeoJson(plan, core.lons, core.lats, r.meta),
    };
  },
};
for await (const line of createInterface({ input: process.stdin })) {
  const request = JSON.parse(line);
  let answer;
  try {
    answer = { ok: ops[request.op](request) };
  } catch (e) {
    answer = { threw: String(e && e.stack || e) };
  }
  process.stdout.write(JSON.stringify(answer) + '\n');
}
"""


class _Browser:
    """The browser's engine in a Node vm, asked one question at a time."""

    def __init__(self, tmp_path: Path):
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed; run `node --version` to check")
        driver = tmp_path / "survey.mjs"
        driver.write_text(_DRIVER, encoding="utf-8")
        self._node = subprocess.Popen([node, str(driver), str(JS)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      text=True, encoding="utf-8")

    def ask(self, op: str, **request):
        assert self._node.stdin is not None and self._node.stdout is not None
        self._node.stdin.write(json.dumps({"op": op, **request}) + "\n")
        self._node.stdin.flush()
        line = self._node.stdout.readline()
        assert line, "the Node driver stopped; its error is above"
        answer = json.loads(line)
        assert "threw" not in answer, answer["threw"]
        return answer["ok"]

    def close(self) -> None:
        assert self._node.stdin is not None
        self._node.stdin.close()
        self._node.wait(timeout=60)


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    engine = _Browser(tmp_path_factory.mktemp("survey"))
    yield engine
    engine.close()


def _hex(value) -> str:
    return struct.pack(">d", float(value)).hex()


def _b64(values, dtype="<f8") -> str:
    return base64.b64encode(np.ascontiguousarray(values, dtype=dtype).tobytes()).decode("ascii")


_SOURCES = [("Borehole", "Hand Pump"), ("Protected Shallow Well", ""), ("Surface Water (River/Stream)", ""),
            ("Protected Spring", ""), ("Piped Water", "Tap stand"), ("", "Tube well")]


def _case(seed: int) -> dict:
    """A seeded case: a window of random cell sizes, candidates at random
    strikes round a site inside it, water points, drainage lines and sea by
    turns, and settings varied every few seeds."""
    rng = np.random.default_rng(4300 + seed)
    rows, cols = int(rng.integers(60, 140)), int(rng.integers(60, 140))
    frame = (float(rng.uniform(20.0, 95.0)), float(rng.uniform(20.0, 95.0)))
    margin = int(rng.integers(0, 12))
    shown = (margin, rows - margin, margin, cols - margin)
    site = (float(rng.uniform(0.3, 0.7)) * cols * frame[0], float(rng.uniform(0.3, 0.7)) * rows * frame[1])
    items = []
    for n in range(int(rng.integers(0, 6))):
        centre = (site[0] + float(rng.normal(0.0, 450.0)), site[1] + float(rng.normal(0.0, 450.0)))
        strike, half = float(rng.uniform(0.0, 180.0)), float(rng.uniform(300.0, 1400.0))
        if seed % 7 == 3 and n:
            strike = items[0].strike_deg + float(rng.uniform(-15.0, 15.0))
        ux, uy = math.sin(math.radians(strike)), math.cos(math.radians(strike))
        items.append(_candidate(n, "valley" if rng.random() < 0.5 else "ridge",
                                (centre[0] - half * ux, centre[1] - half * uy), (centre[0] + half * ux,
                                                                                 centre[1] + half * uy)))
    if seed % 9 == 4:
        # one alone, running straight away from the site from 480 m out: it
        # is crossed at its end, where the radius leaves a chord of 280 m,
        # so its line is shortened
        bearing = float(rng.uniform(0.0, 360.0))
        ux, uy = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))
        end = (site[0] + 480.0 * ux, site[1] + 480.0 * uy)
        items = [_candidate(0, "valley", end, (end[0] + 1200.0 * ux, end[1] + 1200.0 * uy))]
    water = []
    for _ in range(int(rng.integers(0, 9))):
        source, technology = _SOURCES[int(rng.integers(0, len(_SOURCES)))]
        x, y = site[0] + float(rng.normal(0.0, 300.0)), site[1] + float(rng.normal(0.0, 300.0))
        water.append({"lon": LON0 + x / frame[0] * STEP, "lat": LAT0 + y / frame[1] * STEP, "source": source,
                      "technology": technology})
    parts = []
    for _ in range(int(rng.integers(0, 4))):
        r, c = int(rng.integers(0, rows)), int(rng.integers(0, cols))
        cells = [(r, c)]
        for _ in range(int(rng.integers(3, 30))):
            r = min(max(r + int(rng.integers(-1, 2)), 0), rows - 1)
            c = min(max(c + int(rng.integers(-1, 2)), 0), cols - 1)
            cells.append((r, c))
        parts.append(cells)
    cls = np.full((rows, cols), LAND, dtype=np.uint8)
    if seed % 4 == 1:
        cls[:, : int(rng.integers(1, cols // 3))] = SEA
    if seed % 5 == 2:
        cls[int(rng.integers(0, rows - 5)):, int(rng.integers(0, cols - 5))] = 0
    settings = {}
    if seed % 6 == 5:
        settings = {"survey_lines": int(rng.integers(1, 4)), "survey_line_m": float(rng.uniform(80.0, 900.0)),
                    "survey_station_m": float(rng.choice([2.5, 5.0, 20.0, 25.0])),
                    "survey_flank_m": float(rng.uniform(20.0, 120.0)), "survey_cross_within_deg": 40.0,
                    "survey_target_depth_m": float(rng.choice([10.0, 300.0]))}
        settings["survey_move_m"] = settings["survey_flank_m"] * 0.4
    if seed == 11:
        settings = {"survey_move_m": 30.0}
    # every third case's water points looked up round the site, about half
    # of them short of the 550 m a borehole's ring reaches; one refused
    searched = float(rng.uniform(0.0, 900.0)) if seed % 3 == 0 else None
    if seed == 20:
        searched = -5.0
    return {"rows": rows, "cols": cols, "frame": frame, "shown": shown, "site_xy": site, "items": items,
            "water": water, "parts": parts, "cls": cls, "settings": settings, "searched": searched}


def _python_answer(case: dict) -> dict:
    rows, cols, frame = case["rows"], case["cols"], case["frame"]
    cfg = dataclasses.replace(TerrainConfig(), **case["settings"])
    lin = dataclasses.replace(_candidates(case["items"], cfg), frame=frame)
    core = SimpleNamespace(rows=rows, cols=cols, shown=case["shown"], cls=case["cls"],
                           lons=LON0 + np.arange(cols) * STEP, lats=LAT0 + np.arange(rows) * STEP)
    site = (LON0 + case["site_xy"][0] / frame[0] * STEP, LAT0 + case["site_xy"][1] / frame[1] * STEP)
    water = [SimpleNamespace(**w) for w in case["water"]]
    parts = [SimpleNamespace(vertices=tuple(p)) for p in case["parts"]]
    try:
        plan = survey_plan(lin, core, parts, site, water, cfg, searched_m=case["searched"])
    except ValueError as exc:
        return {"refused": str(exc)}
    pair = lambda p: [_hex(v) for v in p]  # noqa: E731
    return {
        "basis": plan.basis, "site": pair(plan.site), "near": list(plan.near),
        "skipped": [list(s) for s in plan.skipped], "reach": plan.reach, "covered": plan.covered,
        "water_points": plan.water_points,
        "rings": [[_hex(g[0]), _hex(g[1]), g[2], _hex(g[3])] for g in plan.rings],
        "lines": [[line.id, line.candidate, line.kind, _hex(line.strike_deg), _hex(line.bearing_deg), pair(line.origin),
                   pair(line.direction), line.first, line.last, _hex(line.length_m), _hex(line.crossing_m),
                   [[c[0], _hex(c[1])] for c in line.crosses], line.shortened] for line in plan.lines],
        "soundings": [[x.id, x.line, x.role, _hex(x.at_m), pair(x.point), _hex(x.moved_m), list(x.cleared),
                       _hex(x.spread_deg)] for x in plan.soundings],
        "dropped": [[d.line, d.role, _hex(d.at_m), list(d.reasons)] for d in plan.dropped],
        "captions": survey_plan_captions(plan, "Kakua"),
        "gpx": survey_plan_gpx(plan, core.lons, core.lats, META),
        "geojson": survey_plan_geojson(plan, core.lons, core.lats, META),
    }


def _browser_answer(browser, case: dict) -> dict:
    rows, cols, frame = case["rows"], case["cols"], case["frame"]
    lin = _candidates(case["items"])
    return browser.ask(
        "plan", rows=rows, cols=cols, shown=list(case["shown"]), frame=list(frame),
        lons=_b64(LON0 + np.arange(cols) * STEP), lats=_b64(LAT0 + np.arange(rows) * STEP),
        cls=base64.b64encode(case["cls"].tobytes()).decode("ascii"),
        lineaments=[{"id": i.id, "kind": i.kind, "start": list(i.start), "end": list(i.end), "length_m": i.length_m,
                     "strike_deg": i.strike_deg} for i in case["items"]],
        roseValleyM=list(lin.rose_valley_m), roseRidgeM=list(lin.rose_ridge_m),
        site=[LON0 + case["site_xy"][0] / frame[0] * STEP, LAT0 + case["site_xy"][1] / frame[1] * STEP],
        water=case["water"], parts=[{"vertices": [list(v) for v in p]} for p in case["parts"]],
        settings=case["settings"], searched=case["searched"], where="Kakua", meta=META)


@pytest.mark.parametrize("seed", range(40))
def test_the_browser_lays_the_same_plan_to_the_bit(browser, seed):
    """Forty seeded cases, every one a different mix of candidates, water
    points, drainage lines, sea, gaps, an offset square and settings: the
    browser's plan is the Python one to the bit, and its captions, GPX and
    GeoJSON the same words and bytes."""
    case = _case(seed)
    want = _python_answer(case)
    got = _browser_answer(browser, case)
    for key in want:
        assert got.get(key) == want[key], (seed, key)
    assert got == want


def test_the_cases_reach_every_rule():
    """The seeded cases are worth comparing only if they reach the rules:
    plans across candidates and across the strike and none at all, moves
    and both reasons for leaving a sounding out, every kind of ring, a line
    crossing another candidate, a skipped one, a shortened line, a square
    that does not cover the radius, and a refused setting."""
    seen: dict[str, int] = {}

    def saw(name: str, yes: bool) -> None:
        seen[name] = seen.get(name, 0) + int(bool(yes))

    for seed in range(40):
        case = _case(seed)
        answer = _python_answer(case)
        if "refused" in answer:
            saw("refused", True)
            saw("searched_refused", case["searched"] is not None and case["searched"] < 0)
            continue
        saw("short", "were looked up no further than" in answer["captions"]["plan"])
        saw("searched_far", case["searched"] is not None and answer["basis"] == "candidates"
            and "were looked up no further than" not in answer["captions"]["plan"])
        saw(answer["basis"], True)
        saw("moved", any(x[5] != _hex(0.0) for x in answer["soundings"]))
        saw("off_line", any(d[3] == ["off_line"] for d in answer["dropped"]))
        saw("rings", any(d[3] != ["off_line"] for d in answer["dropped"]))
        for kind in ("borehole", "dug_well", "other", "surface", "streams", "sea"):
            saw(kind, answer["reach"][kind])
        saw("crosses", any(line[11] for line in answer["lines"]))
        saw("skipped", answer["skipped"])
        saw("shortened", any(line[12] for line in answer["lines"]))
        saw("uncovered", not answer["covered"])
    missing = [name for name in ("candidates", "strike", "none", "moved", "off_line", "rings", "borehole", "dug_well",
                                 "other", "surface", "streams", "sea", "crosses", "skipped", "shortened", "uncovered",
                                 "refused", "short", "searched_far", "searched_refused") if not seen.get(name)]
    assert not missing, (missing, seen)

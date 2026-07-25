"""The Depth Spine view payload and the analyst screen override.

The workspace is a view: the browser draws what these functions decide. What
matters here is that the payload carries the toolkit's own numbers, and that
moving a screen re-derives everything downstream of it rather than only the
drawing.
"""

from __future__ import annotations

import json

import pytest

from groundwater.config import Config
from groundwater.depth_spine import build_view, load
from groundwater.depth_spine.projects import available
from groundwater.design import design_borehole
from groundwater.ingestion import read_drilling_workbook


@pytest.fixture(scope="module")
def dr_timbo(sample_data):
    return load("dr_timbo")


def test_sample_projects_need_a_drilling_log():
    """Only projects with a logged hole can offer a section to place screens on."""
    keys = [p.key for p in available()]
    assert "dr_timbo" in keys
    assert "rokel" not in keys  # VES survey, never drilled


def test_view_is_json_serialisable(dr_timbo):
    payload = build_view(dr_timbo)
    assert json.loads(json.dumps(payload)) == payload


def test_view_carries_the_toolkits_own_numbers(dr_timbo):
    payload = build_view(dr_timbo)

    section = payload["section"]
    assert section["totalDepth"] == 70.0
    assert section["waterStrikes"] == [12.0, 30.0]
    assert section["domain"] > section["totalDepth"]  # room for the TD line

    # The design is generated, not typed: four screens against the strikes and
    # the fractured intervals in the log.
    screens = payload["design"]["screens"]
    assert [(s["top"], s["base"]) for s in screens] == [
        (14.5, 17.0),
        (25.0, 35.0),
        (45.0, 50.0),
        (55.0, 60.0),
    ]

    # A safe yield is never a bare number when it rests on assumptions.
    block = payload["design"]["yield"]
    assert block["lowM3PerH"] < block["safeYieldM3PerH"] < block["highM3PerH"]
    assert "to" in block["rangeText"]


def test_pumping_level_is_labelled_as_unstabilised(dr_timbo):
    """The Dr. Timbo test never settled, so the line is the deepest level."""
    levels = build_view(dr_timbo)["section"]["levels"]
    assert levels["stabilised"] is False
    assert levels["pumpingLevel"] == pytest.approx(
        levels["restLevel"] + levels["maxDrawdown"], abs=0.01
    )


def test_quality_keeps_the_three_kinds_of_exceedance(dr_timbo):
    quality = build_view(dr_timbo)["quality"]
    assert quality["healthExceedances"] == ["Manganese", "Total coliforms"]
    assert set(quality["aestheticExceedances"]) == {"pH", "Iron"}
    assert "does not meet the health based guideline" in quality["verdict"]

    # Every judged row carries its ratio to the binding limit, computed here so
    # the browser never parses a limit string.
    iron = next(r for r in quality["rows"] if r["parameter"] == "Iron")
    assert iron["ratio"] == pytest.approx(0.85 / 0.3, rel=1e-3)
    assert iron["limitName"] == "WHO acceptability"

    # Corrosivity comes from the toolkit's own indices, not a reimplementation.
    assert quality["corrosivity"]["classification"] == "Strongly corrosive"
    assert quality["piper"]["percent"]["hco3"] > 0.5


def test_moving_a_screen_re_derives_the_design_and_the_boq(dr_timbo):
    before = build_view(dr_timbo)
    after = build_view(dr_timbo, screens_m=[(26.0, 40.0)])

    assert before["edited"] is False
    assert after["edited"] is True
    assert [(s["top"], s["base"]) for s in after["design"]["screens"]] == [(26.0, 40.0)]

    # The casing string follows the screens ...
    kinds = [(s["kind"], s["top"], s["base"]) for s in after["section"]["segments"]]
    assert kinds == [
        ("plain", 0.0, 26.0),
        ("screen", 26.0, 40.0),
        ("plain", 40.0, 68.0),
        ("sump", 68.0, 70.0),
    ]
    # ... the gravel pack follows the top screen, by the configured margin ...
    assert after["section"]["gravelPack"][0] == 24.0
    # ... and so does the bill of quantities.
    assert after["costing"]["quantityBasis"]["screenM"] == 14.0
    assert (
        after["costing"]["quantityBasis"]["screenM"]
        != before["costing"]["quantityBasis"]["screenM"]
    )
    assert after["costing"]["price"] != before["costing"]["price"]

    # The analyst's placement is recorded in the design basis, so a reviewer can
    # see the screens were not generated.
    assert "set by the analyst" in after["design"]["basis"][0]


def test_analyst_screens_are_clipped_loudly_not_silently(sample_data):
    log = read_drilling_workbook(
        sample_data / "dr_timbo" / "dr_timbo_drilling_log.xlsx"
    )
    design = design_borehole(
        log=log,
        static_water_level_m=9.44,
        rules=Config().design,
        screens_m=[(60.0, 90.0), (5.0, 5.2)],
    )
    codes = {f.code for f in design.flags}
    assert "screen_clipped" in codes  # 90 m is below the hole
    assert "screen_dropped" in codes  # 0.2 m is not a screen
    assert [(s.top_m, s.bottom_m) for s in design.screens] == [(60.0, 68.0)]


def test_generated_design_is_unchanged_when_no_override_is_given(sample_data):
    """The override path must not alter the automatic one."""
    log = read_drilling_workbook(
        sample_data / "dr_timbo" / "dr_timbo_drilling_log.xlsx"
    )
    rules = Config().design
    generated = design_borehole(log=log, static_water_level_m=9.44, rules=rules)
    assert [(s.top_m, s.bottom_m) for s in generated.screens] == [
        (14.5, 17.0),
        (25.0, 35.0),
        (45.0, 50.0),
        (55.0, 60.0),
    ]

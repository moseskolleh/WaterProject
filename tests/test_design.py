"""The borehole design reads the driller's own words.

Dr Timbo's log says "fracture zone 49-52 m" on the 45-50 m row and
"fracture zone 60-62 m" on the 55-60 m row, records grouting to 20 m, and
notes a seepage at 12 m in clayey laterite. The design used to screen the
five-metre rows (45-50 m covered one metre of the zone, 60-62 m sat behind
plain casing), screen the laterite at 14.5-17 m, draw a 6 m seal with a
gravel pack inside the grouted interval, and call itself as-built.
"""

from __future__ import annotations

from openpyxl import load_workbook

from groundwater.config import DesignRules
from groundwater.costing import inputs_from_design
from groundwater.design import (
    AS_BUILT_NOTE,
    DESIGN_NOTE,
    design_borehole,
    fracture_ranges,
    is_clayey,
    lithology_bands,
    lithology_class,
    logged_diameter_in,
    seal_depth_for,
)
from groundwater.ingestion import read_drilling_workbook
from groundwater.ingestion.drilling import parse_installed_screens
from groundwater.ingestion.templates import write_drilling_template
from groundwater.models import DrillingLog, LithologyInterval, SiteMetadata


def _log(intervals, strikes=(), depth=None, grout=None, installed=()):
    return DrillingLog(
        site=SiteMetadata(community="X"),
        total_depth_m=depth or max(b for _, b, _ in intervals),
        intervals=[LithologyInterval(t, b, d) for t, b, d in intervals],
        water_strikes_m=list(strikes),
        grouting_depth_m=grout,
        installed_screens_m=list(installed),
    )


def test_the_fracture_zones_the_log_names_are_screened(sample_data):
    log = read_drilling_workbook(sample_data / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    design = design_borehole(log=log, static_water_level_m=9.44)
    assert [(s.top_m, s.bottom_m) for s in design.screens] == [
        (25.0, 35.0), (48.0, 53.0), (59.0, 63.0),
    ]
    basis = " | ".join(design.design_basis)
    assert "fracture zones the log names (49-52 m, 60-62 m), with 1 m of screen" in basis
    assert "water strikes recorded in the drilling log (30 m)" in basis
    assert "the 12 m strike is not screened" in basis
    assert "clayey laterites" in basis and "20 m grouted interval" in basis
    # the recorded grout is the seal, and nothing is drawn inside it
    assert design.sanitary_seal == (0.0, 20.0)
    assert design.backfill == (20.0, 23.0)
    assert design.gravel_pack == (23.0, 70.0)
    assert "cement grout from surface to 20 m as recorded on the drilling log" in basis
    # the log's 6.5 inch hole round 5 inch casing takes no pack
    assert design.borehole_diameter_in == 6.5 and "as logged" in basis
    assert design.annular_fill == "none" and round(design.annulus_mm) == 19
    assert inputs_from_design(design).gravel_interval_m == 0.0
    assert any(f.code == "thin_annulus" and "no gravel pack is drawn or priced" in f.message
               for f in design.flags)
    assert not design.as_built and design.construction_note == DESIGN_NOTE


def test_a_seepage_in_clay_is_cased_off_not_screened():
    log = _log([(0, 6, "lateritic topsoil"), (6, 20, "clayey laterite, wet from 8 m"),
                (20, 40, "fractured granite")], strikes=[8.0, 25.0])
    design = design_borehole(log=log, static_water_level_m=2.0)
    assert all(s.top_m >= 20.0 for s in design.screens)
    assert any("the 8 m strike is not screened" in b and "seepage horizon" in b
               for b in design.design_basis)
    assert any("water strikes recorded in the drilling log (25 m)" in b
               for b in design.design_basis)
    assert is_clayey("Light yellow clayey laterites") and not is_clayey("fractured granite")


def test_the_recorded_grout_sets_the_seal():
    log = _log([(0, 10, "laterite"), (10, 40, "fractured granite")], strikes=[12.0],
               grout=15.0)
    design = design_borehole(log=log, static_water_level_m=4.0)
    assert seal_depth_for(log, DesignRules()) == 15.0
    assert design.sanitary_seal == (0.0, 15.0)
    assert design.gravel_pack[0] >= 15.0
    # the 12 m strike is inside the grout, so it is not a screen target
    assert all(s.top_m >= 15.0 for s in design.screens)
    assert any("within the 15 m grouted interval" in b for b in design.design_basis)
    # without a recorded grout the rule's minimum stands
    plain = design_borehole(log=_log([(0, 10, "laterite"), (10, 40, "fractured granite")]),
                            static_water_level_m=4.0)
    assert plain.sanitary_seal == (0.0, DesignRules().sanitary_seal_depth_m)


def test_the_annulus_decides_the_fill():
    log = _log([(0, 10, "laterite"), (10, 40, "fractured granite")], strikes=[20.0])
    none = design_borehole(log=log, static_water_level_m=4.0)
    assert none.annular_fill == "none"
    assert "no gravel pack" in dict(none.summary_rows())["Annular fill"]
    assert inputs_from_design(none).gravel_interval_m == 0.0
    stabiliser = design_borehole(log=log, static_water_level_m=4.0,
                                 rules=DesignRules(borehole_diameter_in=8.0, casing_diameter_in=4.0))
    assert stabiliser.annular_fill == "formation stabiliser"
    assert inputs_from_design(stabiliser).gravel_interval_m > 0
    pack = design_borehole(log=log, static_water_level_m=4.0,
                           rules=DesignRules(borehole_diameter_in=10.0, casing_diameter_in=4.0))
    assert pack.annular_fill == "gravel pack"
    assert "gravel pack (well sorted" in dict(pack.summary_rows())["Annular fill"]


def test_the_drilled_diameter_comes_from_the_log():
    log = _log([(0, 10, "laterite"), (10, 40, "fractured granite")], strikes=[20.0])
    for interval in log.intervals:
        interval.bit_diameter_in = 9.0
    assert logged_diameter_in(log) == 9.0
    design = design_borehole(log=log, static_water_level_m=4.0)
    assert design.borehole_diameter_in == 9.0
    assert design.annular_fill == "formation stabiliser"   # 51 mm a side round 5 inch
    assert any("9 inch hole as logged" in b for b in design.design_basis)


def test_installed_screens_make_the_drawing_as_built(tmp_path):
    assert parse_installed_screens("25-35; 48-53 m") == [(25.0, 35.0), (48.0, 53.0)]
    assert parse_installed_screens("") == []
    log = _log([(0, 10, "laterite"), (10, 40, "fractured granite")], strikes=[20.0],
               installed=[(22.0, 30.0)])
    design = design_borehole(log=log, static_water_level_m=4.0)
    assert design.as_built and design.construction_note == AS_BUILT_NOTE
    assert [(s.top_m, s.bottom_m) for s in design.screens] == [(22.0, 30.0)]
    assert design.design_basis[0].startswith("screens as installed, recorded on the drilling log")
    assert dict(design.summary_rows())["Screens (as installed)"].startswith("22-30 m")
    # and the template carries the field the crew fills in
    path = write_drilling_template(tmp_path / "log.xlsx", n_rows=3)
    wb = load_workbook(path)
    ws = wb.active
    ws["B2"] = "Somewhere"
    ws["E5"] = 40
    ws["B10"] = "22-30; 33-36"
    ws["A12"] = "0-10"
    ws["E12"] = "laterite"
    ws["A13"] = "10-40"
    ws["E13"] = "fractured granite"
    wb.save(path)
    parsed = read_drilling_workbook(path)
    assert parsed.installed_screens_m == [(22.0, 30.0), (33.0, 36.0)]
    assert design_borehole(log=parsed, static_water_level_m=4.0).as_built


def test_lithology_bands_put_a_named_zone_where_it_is(sample_data):
    log = read_drilling_workbook(sample_data / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    bands = {(t, b): c.label for t, b, c in lithology_bands(log.intervals)}
    assert bands[(45.0, 49.0)] == "Basement rock"
    assert bands[(49.0, 50.0)] == "Fracture zone"
    assert bands[(50.0, 52.0)] == "Fracture zone"
    assert bands[(52.0, 55.0)] == "Basement rock"
    # named on the 55-60 m row, drawn at 60-62 m
    assert bands[(55.0, 60.0)] == "Basement rock"
    assert bands[(60.0, 62.0)] == "Fracture zone"
    assert bands[(62.0, 65.0)] == "Basement rock"
    assert bands[(35.0, 40.0)] == "Weathered rock"      # slightly weathered, not fresh
    assert bands[(15.0, 20.0)] == "Saprolite"           # clayey saprolite is saprolite
    assert fracture_ranges("Light colour granite, fracture zone 49-52 m") == [(49.0, 52.0)]
    assert lithology_class("Weathered light colour granite, fractured").label == "Fracture zone"


def test_depth_tables_print_half_metres():
    """The table used to round 14.5 m to "14" beside a drawing that said 14.5."""
    log = _log([(0, 10, "laterite"), (10, 25, "granite"),
                (25, 40, "fractured granite, water bearing")], strikes=[13.5])
    design = design_borehole(log=log, static_water_level_m=7.0)
    rows = dict(design.summary_rows())
    assert [(s.top_m, s.bottom_m) for s in design.screens] == [(12.5, 18.5), (25.0, 38.0)]
    assert rows["Screens"].startswith("12.5-18.5 m; 25-38 m")

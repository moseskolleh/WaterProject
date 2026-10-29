"""Water quality units and bases, clock times, and the gravel pack, after an
audit of both engines.

Each test is a defect the audit reproduced in Python and in the browser's
engine alike, held here in Python; the last holds the browser's engine to the
same answers in a Node vm (parity.mjs holds the same cases in a browser).

A unit written after a measured value, or in the result column's header, is
read; nitrate and nitrite reported as nitrogen are held to the guideline for
nitrogen and read on the ion's scale by the charge balance, the hazard index
and the water quality index; calcium and magnesium as CaCO3 are put on the
element's scale; an E. coli count per 100 mL written with a space is a count;
a determinand with no guideline value no longer holds up the verdict over its
unit; a clock is a clock wherever a time is read; and a gravel pack the seal
holds down is said to be, while a screen the design places leaves room for it.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from groundwater.config import DesignRules
from groundwater.design import design_borehole
from groundwater.ingestion.waterquality import _read_cell, quality_from_grid
from groundwater.models import (
    DrillingLog,
    LithologyInterval,
    SiteMetadata,
    WaterQualityResult,
    WaterQualitySample,
)
from groundwater.quality import assess_sample
from groundwater.quality.standards import MOLAR_MASS, load_standards, normalise_parameter
from groundwater.text import phrase
from groundwater.units import parse_unit, read_quantity

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"


def _sample(*results: WaterQualityResult) -> WaterQualitySample:
    return WaterQualitySample(site=SiteMetadata(community="Test"), results=list(results))


PANEL = [
    ("pH", 7.0, "pH units"), ("E. coli", 0.0, "CFU/100 mL"),
    ("Arsenic", 0.001, "mg/L"), ("Fluoride", 0.2, "mg/L"),
]


def _with_panel(*rows) -> WaterQualitySample:
    return _sample(*[WaterQualityResult(p, v, u) for p, v, u in PANEL + list(rows)])


def _sheet(*rows, header=("Parameter", "Unit", "Result", "Detection limit")):
    return [["Laboratory", "Central Lab"], ["Sample ID", "S"], [], list(header)] + [
        list(r) for r in rows]


def _row(assessment, parameter):
    return next(r for r in assessment.rows if r.parameter == parameter)


# ------------------------------------------- a unit after a measured value

def test_a_unit_written_after_a_measured_value_is_read():
    """"0.05 mg/L" in a ug/L row was read as 0.05 ug/L, a thousandth of
    what it is, and arsenic at five times its guideline was graded Safe; the
    same unit after a "<" was read all along."""
    sample = quality_from_grid(_sheet(
        ["pH", "pH units", 7.1, ""], ["E. coli", "CFU/100 mL", 0, ""],
        ["Arsenic", "ug/L", "0.05 mg/L", ""], ["Fluoride", "mg/L", 0.2, ""],
        ["Nitrate", "mg/L", 3.1, ""], ["Manganese", "ug/L", "<0.05 mg/L", ""],
        ["Lead", "", "8 ug/L", ""],
    ), "s.xlsx")
    arsenic = next(r for r in sample.results if r.parameter == "Arsenic")
    assert (arsenic.value, arsenic.unit) == (pytest.approx(50.0), "ug/L")
    lead = next(r for r in sample.results if r.parameter == "Lead")
    assert (lead.value, lead.unit) == (8.0, "ug/L")
    a = assess_sample(sample)
    assert a.verdict_state == "health_fail"
    assert _row(a, "Arsenic").status == "exceeds_health"
    assert _row(a, "Arsenic").value_in_guideline_unit == pytest.approx(0.05)
    assert _row(a, "Lead").status == "within_limits"
    assert _row(a, "Lead").value_in_guideline_unit == pytest.approx(0.008)


@pytest.mark.parametrize("cell,number,unit", [
    ("0.05 mg/L", 0.05, "mg/l"), ("8ug/l", 8.0, "ug/l"), ("8 ug/L*", 8.0, "ug/l"),
    ("0.05mg/L (field)", 0.05, "mg/l"), ("27 oC", 27.0, "oc"),
    ("12 No./100 mL", 12.0, "no./100 ml"),
    # a number in E-notation, and a unit in a bracket or with its basis in one
    ("5.0E-02 mg/L", 0.05, "mg/l"), ("8E+00 ug/L", 8.0, "ug/l"), ("5e-3mg/l", 0.005, "mg/l"),
    ("0.05 (mg/L)", 0.05, "mg/l"), ("10 mg/L (as N)", 10.0, "mg/l as n"),
    ("0.01 mg/L (As)", 0.01, "mg/l"), ("1,250.5 mg/L", 1250.5, "mg/l"),
    ("1.234,5 mg/L", 1234.5, "mg/l"), ("(0.05 mg/L)", 0.05, "mg/l"), ("5. mg/L", 5.0, "mg/l"),
    ("450 uS/cm at 25 C", 450.0, "us/cm"), ("approx 0.05 mg/L", 0.05, "mg/l"),
    ("0.05 mg/L (DL 0.01 mg/L)", 0.05, "mg/l"),
    # a note beside the number is not a unit, and leaves it as it was read
    ("0.5 ND", 0.5, ""), ("8 (field)", 8.0, ""), ("8*", 8.0, ""), ("45 TCU", 45.0, ""),
    ("0.05 (DL 0.01)", 0.05, ""), ("7.1 at 25 C", 7.1, ""),
    # and so is a laboratory's qualifier letter, though the unit reader
    # knows D, H and S as times, M as metres and C and F as temperatures
    ("0.003 D", 0.003, ""), ("0.2 H", 0.2, ""), ("3.1 S", 3.1, ""), ("0.1 M", 0.1, ""),
    ("0.1 C", 0.1, ""), ("0.5 F", 0.5, ""), ("1 min", 1.0, ""),
])
def test_only_a_unit_the_toolkit_reads_is_taken_from_a_measured_cell(cell, number, unit):
    read = _read_cell(cell)
    assert (read["kind"], read["number"], read["unit"]) == ("number", number, unit)


@pytest.mark.parametrize("cell", [
    "0.05 mg/L As", "0.05 mg / L As", "0.05 mg/L Fe", "25 mg/L CaCO3", "25 mg/L (CaCO3)",
    "25 (CaCO3)", "10 NO3-N", "10 mg/L (NO3-N)", "10 (N)", "10 (as N)", "10 mg N/L",
    "5 E-02 mg/L", "0.05 mg/L est", "0.05 mg/L, field", "0.05 mg/L; est", "0.5 U mg/L",
    # a unit the toolkit does not read, or refuses by name, and a note that holds one
    "5 meq/L", "5eq/l", "5 ppt", "0.05 (DL 0.01 mg/L)",
])
def test_a_unit_or_basis_that_cannot_be_read_as_written_refuses_a_measured_cell(cell):
    """"0.05 mg/L As" and "5.0E-02 mg/L" dropped their unit, and arsenic at
    five times its guideline was read in its row's ug/L and graded Safe; a
    nitrogen basis without "as" was dropped as a note, and nitrate as N read
    as the ion; "5 meq/L" and "5 ppt" were read in the row's unit."""
    assert _read_cell(cell)["kind"] == "unreadable"


def test_a_lone_unit_letter_is_a_unit_only_in_its_rows_family():
    """"68 F" in a row of degrees Celsius is 20 deg C, as it was before the
    qualifier letters were read as notes; "0.1 C" in a row of mg/L is a note."""
    sample = quality_from_grid(_sheet(
        ["Temperature", "deg C", "68 F", ""], ["Temperature (field)", "deg F", "20 C", ""],
        ["Iron", "mg/L", "0.1 C", ""], ["Copper", "mg/L", "0.5 F", ""],
    ), "s.xlsx")
    assert [(r.value, r.unit) for r in sample.results] == [
        (pytest.approx(20.0), "deg C"), (pytest.approx(68.0), "deg F"),
        (0.1, "mg/L"), (0.5, "mg/L")]
    assert _read_cell("68 F", "temperature")["unit"] == "f"
    assert _read_cell("68 F")["unit"] == ""


def test_a_measured_value_in_e_notation_keeps_its_unit():
    sample = quality_from_grid(_sheet(
        ["pH", "pH units", 7.1, ""], ["E. coli", "CFU/100 mL", 0, ""],
        ["Arsenic", "ug/L", "5.0E-02 mg/L", ""], ["Fluoride", "mg/L", 0.2, ""],
        ["Nitrate", "mg/L", 3.1, ""], ["Lead", "", "8E+00 ug/L", ""],
        ["Manganese", "ug/L", "<5.0E-02 mg/L", ""], ["Iron", "ug/L", "0.05 mg/L As", ""],
    ), "s.xlsx")
    a = assess_sample(sample)
    assert a.verdict_state == "health_fail"
    assert _row(a, "Arsenic").status == "exceeds_health"
    assert _row(a, "Arsenic").value_in_guideline_unit == pytest.approx(0.05)
    assert _row(a, "Lead").value_in_guideline_unit == pytest.approx(0.008)
    manganese = next(r for r in sample.results if r.parameter == "Manganese")
    assert (manganese.below_detection, manganese.detection_limit) == (True, pytest.approx(50.0))
    iron = _row(a, "Iron")
    assert (iron.status, iron.reason) == ("indeterminate", "value_unreadable")


def test_a_qualifier_letter_after_a_measured_value_is_a_note():
    """"0.003 D" (diluted), "0.2 H" (held past its time), "3.1 S" (spike)
    and "0.1 M" (matrix) graded Safe before units after a measured value
    were read, and were then refused as a day, an hour, a second and a
    metre: the sample was "Not proven safe"."""
    a = assess_sample(quality_from_grid(_sheet(
        ["pH", "pH units", 7.1, ""], ["E. coli", "CFU/100 mL", 0, ""],
        ["Arsenic", "mg/L", "0.003 D", ""], ["Fluoride", "mg/L", "0.2 H", ""],
        ["Nitrate", "mg/L", "3.1 S", ""], ["Iron", "mg/L", "0.1 M", ""],
        ["Temperature", "deg C", "20 C", ""], ["Copper", "mg/L", "0.5 F", ""],
    ), "s.xlsx"))
    assert a.verdict_state == "pass"
    assert {r.status for r in a.rows} == {"within_limits", "no_guideline"}


def test_a_cell_unit_and_its_column_are_reconciled_or_refused():
    sample = quality_from_grid(_sheet(
        ["Iron", "mg/L", "5 NTU", ""],                       # another dimension
        ["Alkalinity", "mg/L as CaCO3", "46 mg/L", ""],      # the column's basis
        ["Nitrate", "mg/L", "10 mg/L as N", ""],             # the cell's basis
    ), "s.xlsx")
    iron, alkalinity, nitrate = sample.results
    assert iron.value is None and iron.unreadable == "5 NTU"
    assert (alkalinity.value, alkalinity.unit) == (46.0, "mg/L as CaCO3")
    assert (nitrate.value, nitrate.unit) == (10.0, "mg/L as N")


def test_a_unit_in_the_result_header_is_the_unit_of_a_row_with_none():
    """Arsenic 5 under "Result (ug/L)" was read as 5 mg/L, five hundred
    times the guideline."""
    sample = quality_from_grid(_sheet(
        ["Arsenic", "", 5], ["Lead", "mg/L", 0.003], ["Manganese", "-", 40],
        header=("Parameter", "Unit", "Result (ug/L)")), "s.xlsx")
    assert [(r.value, r.unit) for r in sample.results] == [
        (5.0, "ug/L"), (0.003, "mg/L"), (40.0, "ug/L")]
    rows = assess_sample(sample).rows
    assert [r.status for r in rows] == ["within_limits"] * 3
    assert rows[0].value_in_guideline_unit == pytest.approx(0.005)
    # a header that declares no unit the toolkit reads declares nothing
    plain = quality_from_grid(_sheet(["Arsenic", 0.004], header=("Parameter", "Result (lab)")),
                              "s.xlsx")
    assert plain.results[0].unit == ""


# --------------------------------------------- nitrate and nitrite as nitrogen

@pytest.mark.parametrize("written,key", [
    ("Nitrate (NO3-N)", "nitrate (as n)"), ("Nitrate (N)", "nitrate (as n)"),
    ("Nitrate (NO3 as N)", "nitrate (as n)"), ("Nitrate (as NO3-N)", "nitrate (as n)"),
    ("Nitrate (NO3--N)", "nitrate (as n)"), ("Nitrate (nitrogen)", "nitrate (as n)"),
    ("Nitrite (NO2-N)", "nitrite (as n)"), ("Ammonium (NH4-N)", "ammonia (as n)"),
    ("Nitrate (NO3)", "nitrate (as no3)"), ("Nitrate", "nitrate (as no3)"),
    # a qualifier naming another ion contradicts the name: resolved to nothing
    ("Nitrite (NO3-N)", "nitrite (no3-n)"),
    # the unit in the name's bracket, and a minus sign for the hyphen
    ("Nitrate (mg/L as N)", "nitrate (as n)"), ("Nitrate (mg N/L)", "nitrate (as n)"),
    ("Nitrate (mgN/L)", "nitrate (as n)"),
    ("Nitrate (ppm NO3-N)", "nitrate (as n)"), ("Nitrate (NO3−N)", "nitrate (as n)"),
    ("Nitrate−N", "nitrate (as n)"), ("Nitrite (mg/L as N)", "nitrite (as n)"),
    ("Nitrate (mg/L as NO2-N)", "nitrate (mg/l as no2-n)"),
    ("Nitrate (mg/L as NO3)", "nitrate (as no3)"), ("Nitrate (mg/L)", "nitrate (as no3)"),
])
def test_a_name_that_says_nitrogen_resolves_to_the_nitrogen_entry(written, key):
    assert normalise_parameter(written) == key


@pytest.mark.parametrize("name", [
    "Nitrate (mg/L as N)", "Nitrate (mg/l as N)", "Nitrate (mg N/L)", "Nitrate (NO3−N)"])
def test_nitrate_as_nitrogen_with_its_unit_in_the_name_is_held_to_nitrogen(name):
    """"Nitrate (mg/L as N)" at 20 mg/L, 88.5 mg/L as nitrate, was held to
    the 50 mg/L guideline for the ion and graded Safe."""
    for unit in ("mg/L", ""):
        a = assess_sample(_with_panel((name, 20.0, unit)))
        row = _row(a, name)
        assert (row.status, row.who_health) == ("exceeds_health", "11.3"), unit
        assert a.verdict_state == "health_fail"
    nitrite = _row(assess_sample(_with_panel(("Nitrite (mg/L as N)", 1.0, "mg/L"))),
                   "Nitrite (mg/L as N)")
    assert (nitrite.status, nitrite.who_health) == ("exceeds_health", "0.91")


def test_nitrate_as_nitrogen_is_held_to_the_guideline_for_nitrogen():
    """20 mg/L NO3-N is 88.5 mg/L as nitrate, 1.77 times the guideline, and
    was graded against the 50 mg/L as-ion value: suitable for drinking."""
    a = assess_sample(_with_panel(("Nitrate (NO3-N)", 20.0, "mg/L"),
                                  ("Nitrite (NO2-N)", 0.5, "mg/L")))
    assert a.verdict_state == "health_fail"
    nitrate = _row(a, "Nitrate (NO3-N)")
    assert (nitrate.status, nitrate.who_health) == ("exceeds_health", "11.3")
    assert nitrate.remark.endswith("reported as nitrogen: 20 mg/L as N is 88.5 mg/L as NO3")
    nitrite = _row(a, "Nitrite (NO2-N)")
    assert (nitrite.status, nitrite.who_health) == ("within_limits", "0.91")
    assert nitrite.remark == "reported as nitrogen: 0.5 mg/L as N is 1.64 mg/L as NO2"


def test_nitrate_in_a_unit_as_nitrogen_is_converted_unless_the_name_says_otherwise():
    a = assess_sample(_with_panel(("Nitrate", 10.0, "mg/L as N")))
    row = _row(a, "Nitrate")
    assert row.value_in_guideline_unit == pytest.approx(10.0 * 62.004 / 14.007)
    assert row.reason == "unit_basis_converted"
    assert row.remark == "(10 mg/L as N = 44.2664 mg/L as NO3)"
    assert a.verdict_state == "pass"
    flag = next(f for f in a.flags if f.code == "unit_basis_converted")
    assert flag.level == "info" and "by a factor of 4.4266" in flag.message
    # a basis the name states and the unit contradicts is still refused
    conflict = assess_sample(_with_panel(("Nitrate (as NO3)", 10.0, "mg/L as N")))
    assert _row(conflict, "Nitrate (as NO3)").reason == "unit_basis_conflict"


@pytest.mark.parametrize("parameter,value,unit", [
    # the name says nitrogen without "as", the unit says the ion
    ("Nitrate-N", 44.0, "mg/L as NO3"), ("Nitrate (NO3-N)", 44.0, "mg/L as NO3"),
    ("Nitrate (mg/L as N)", 44.0, "mg/L as NO3"), ("Nitrite-N", 1.0, "mg/L as NO2"),
    # the name says the ion inside a bracket with its unit, the unit says nitrogen
    ("Nitrate (mg/L as NO3)", 10.0, "mg/L as N"),
    # the unit names another ion's nitrogen
    ("Nitrite", 0.5, "mg/L as NO3-N"), ("Nitrate (NO3)", 5.0, "mg/L as NH4-N"),
    ("Nitrate-N", 5.0, "mg/L as NO2-N"), ("Ammonia", 1.0, "mg/L as NO3-N"),
    # the name states a basis and the unit the entry's own, another one
    ("Nitrate (mg/L as NO2)", 5.0, "mg/L as NO3"),
])
def test_a_name_and_a_unit_on_different_nitrogen_bases_are_refused(parameter, value, unit):
    """"Nitrate-N" 44 in "mg/L as NO3" was converted onto nitrogen and
    passed at 9.94 against 11.3, where the name puts it at four times the
    guideline; "Nitrite" in "mg/L as NO3-N" was converted as nitrite. The
    old code refused both, as the user guide says it does."""
    row = _row(assess_sample(_with_panel((parameter, value, unit))), parameter)
    assert (row.status, row.reason) == ("indeterminate", "unit_basis_conflict")


def test_a_name_and_a_unit_on_different_bases_are_refused_whichever_is_the_entrys():
    """"Calcium (mg/L as CaCO3)" in "mg/L as Ca" was read as calcium: the
    unit's basis is calcium's own, and the name was not read."""
    a = assess_sample(_with_panel(("Calcium (mg/L as CaCO3)", 20.0, "mg/L as Ca")))
    row = _row(a, "Calcium (mg/L as CaCO3)")
    assert (row.status, row.reason) == ("no_guideline", "unit_basis_conflict")
    assert "value_not_used" in [f.code for f in a.flags]


@pytest.mark.parametrize("parameter,unit,expected", [
    ("Nitrate", "mg/L as NO3-N", 10.0 * 62.004 / 14.007),
    ("Nitrate", "mg/L as NO3−N", 10.0 * 62.004 / 14.007),
    ("Nitrate (NO3)", "mg/L as N", 10.0 * 62.004 / 14.007),
    ("Nitrite", "mg/L as NO2-N", 10.0 * 46.005 / 14.007),
    ("Ammonia", "mg/L as NH4-N", 10.0), ("Ammonia", "mg/L as NH3-N", 10.0),
])
def test_a_unit_on_the_names_own_nitrogen_is_read(parameter, unit, expected):
    row = _row(assess_sample(_with_panel((parameter, 10.0, unit))), parameter)
    assert row.value_in_guideline_unit == pytest.approx(expected)


def test_nitrate_as_nitrogen_enters_the_indices_on_the_ions_scale():
    """The same water reported as nitrogen left the balance 10.6 percent
    short and flagged unreliable, dropped out of the hazard index (0.32 to
    0.14), and led the water quality index (13.3 to 43.7)."""
    ions = [("Calcium", 40.078, "mg/L"), ("Magnesium", 12.1525, "mg/L"),
            ("Sodium", 16.426355, "mg/L"), ("Chloride", 35.453, "mg/L"),
            ("Bicarbonate", 61.017, "mg/L"), ("Sulfate", 48.03, "mg/L")]
    as_ion = assess_sample(_with_panel(*ions, ("Nitrate", 10.0 * 62.004 / 14.007, "mg/L")))
    for nitrogen in (("Nitrate (as N)", 10.0, "mg/L"), ("Nitrate", 10.0, "mg/L as N")):
        as_n = assess_sample(_with_panel(*ions, nitrogen))
        assert as_n.ionic.error_percent == pytest.approx(as_ion.ionic.error_percent, abs=1e-6)
        assert as_n.ionic.flag is None
        assert as_n.health_risk.hazard_index == as_ion.health_risk.hazard_index == 0.37
        assert as_n.wqi.value == as_ion.wqi.value
        assert as_n.wqi.n_parameters == as_ion.wqi.n_parameters
        assert "Nitrate (as N)" not in [name for name, _ in as_n.wqi.top_contributors]
    # a certificate that reports both forms is counted once, by the ion's
    both = assess_sample(_with_panel(*ions, ("Nitrate-N", 10.0, "mg/L"),
                                     ("Nitrate", 44.2664, "mg/L")))
    assert both.ionic.anions_meq["nitrate (as no3)"] == pytest.approx(44.2664 / 62.004)
    assert both.health_risk.hazard_quotients == as_ion.health_risk.hazard_quotients


def test_the_combined_rule_reads_nitrogen_names_on_the_nitrogen_guidelines():
    a = assess_sample(_with_panel(("Nitrate (NO3-N)", 9.0, "mg/L"),
                                  ("Nitrite (NO2-N)", 0.5, "mg/L")))
    combined = _row(a, "Nitrate + nitrite (combined)")
    assert combined.status == "exceeds_health"
    assert combined.value == round(9.0 / 11.3 + 0.5 / 0.91, 2)


# ------------------------------------------------- calcium and magnesium as CaCO3

def test_calcium_and_magnesium_as_caco3_are_put_on_the_elements_scale():
    """Taken at face value, Ca as CaCO3 is 2.5 times the element and Mg 4.1
    times: a balanced analysis came out 33 percent out and unreliable, and
    the Langelier index 0.40 too high."""
    common = [("Nitrate", 4.43, "mg/L"), ("Sodium", 36.126486, "mg/L"),
              ("Chloride", 17.7265, "mg/L"), ("Alkalinity", 100.09, "mg/L as CaCO3"),
              ("Sulfate", 24.015, "mg/L"), ("TDS", 200, "mg/L"),
              ("Temperature", 27, "deg C")]
    element = assess_sample(_with_panel(*common, ("Calcium", 20.039, "mg/L"),
                                        ("Magnesium", 6.076, "mg/L")))
    caco3 = assess_sample(_with_panel(*common, ("Calcium", 50.037383, "mg/L as CaCO3"),
                                      ("Magnesium", 25.020968, "mg/L as CaCO3")))
    assert caco3.ionic.error_percent == pytest.approx(element.ionic.error_percent, abs=0.01)
    assert caco3.ionic.flag is None
    assert (caco3.corrosivity.lsi, caco3.corrosivity.rsi) == (
        element.corrosivity.lsi, element.corrosivity.rsi) == (-1.18, 9.36)
    calcium = _row(caco3, "Calcium")
    assert calcium.reason == "unit_basis_converted"
    assert calcium.value_in_guideline_unit == pytest.approx(
        50.037383 * MOLAR_MASS["Ca"] / MOLAR_MASS["CaCO3"])
    converted = [f.message for f in caco3.flags if f.code == "unit_basis_converted"]
    assert converted == [
        ("'Calcium' is reported in 'mg/L as CaCO3' and was put on the basis its guideline "
         "is written on, mg/L as Ca, by a factor of 0.4004, the ratio of their molar masses."),
        ("'Magnesium' is reported in 'mg/L as CaCO3' and was put on the basis its guideline "
         "is written on, mg/L as Mg, by a factor of 0.2428, the ratio of their molar masses.")]
    assert not [f for f in caco3.flags if f.code == "unit_basis_assumed"]
    # the element's own basis is its own scale, and bicarbonate as CaCO3 is
    # two equivalents a mole
    own = assess_sample(_with_panel(("Calcium", 20.0, "mg/L as Ca"),
                                    ("Bicarbonate", 100.087, "mg/L as CaCO3")))
    assert _row(own, "Calcium").reason == ""
    assert _row(own, "Bicarbonate").value_in_guideline_unit == pytest.approx(2 * 61.017)


def test_a_bound_or_detection_limit_put_on_another_basis_says_so():
    """A "<0.1" nitrate in "mg/L as N" read "below detection limit (0.442664
    mg/L)", with no basis and no flag; ">20" in the same unit and calcium
    ">20" as CaCO3 carried no flag either, and bounds on "Nitrate (NO3-N)"
    never said the sheet reported nitrogen."""
    def assessed(*results):
        return assess_sample(_sample(*[WaterQualityResult(p, v, u) for p, v, u in PANEL],
                                     *results))

    def converted_flags(a):
        return [f.message for f in a.flags if f.code == "unit_basis_converted"]

    factor = ("'Nitrate' is reported in 'mg/L as N' and was put on the basis its guideline "
              "is written on, mg/L as NO3, by a factor of 4.4266, the ratio of their molar "
              "masses.")
    below = assessed(WaterQualityResult("Nitrate", None, "mg/L as N", detection_limit=0.1,
                                        below_detection=True))
    row = _row(below, "Nitrate")
    assert (row.status, row.basis_reason) == ("below_detection", "unit_basis_converted")
    assert row.remark == ("below detection limit (0.1 mg/L as N = 0.442664 mg/L as NO3), "
                          "which is at or under the limit of 50 mg/L")
    assert converted_flags(below) == [factor]
    coarse = assessed(WaterQualityResult("Nitrate", None, "mg/L as N", detection_limit=15.0,
                                         below_detection=True))
    assert _row(coarse, "Nitrate").remark.startswith(
        "below a detection limit of 15 mg/L as N = 66.3997 mg/L as NO3, which is above")
    assert converted_flags(coarse) == [factor]
    bound = assessed(WaterQualityResult("Nitrate", None, "mg/L as N", greater_than=20.0))
    assert _row(bound, "Nitrate").status == "exceeds_health"
    assert converted_flags(bound) == [factor]
    calcium = assessed(WaterQualityResult("Calcium", None, "mg/L as CaCO3", greater_than=20.0))
    assert len(converted_flags(calcium)) == 1
    # a name that says nitrogen says which basis its bounds are on
    note = "; reported as nitrogen: 20 mg/L as N is 88.5 mg/L as NO3"
    over = assessed(WaterQualityResult("Nitrate (NO3-N)", None, "mg/L", greater_than=20.0))
    assert _row(over, "Nitrate (NO3-N)").remark.endswith(note)
    under = assessed(WaterQualityResult("Nitrate (NO3-N)", None, "mg/L", detection_limit=0.1,
                                        below_detection=True))
    assert _row(under, "Nitrate (NO3-N)").remark == (
        "below detection limit (0.1 mg/L), which is at or under the limit of 11.3 mg/L; "
        "reported as nitrogen: 0.1 mg/L as N is 0.443 mg/L as NO3")
    # a measured value converted the same way still says it once
    measured = assessed(WaterQualityResult("Nitrate", 10.0, "mg/L as N"))
    assert converted_flags(measured) == [factor]
    # and a basis taken as the guideline's is said to be, on a bound and a
    # detection limit as on a value: sodium "<1" in "mg/L as CaCO3" passed
    # with no word of it
    for result in (WaterQualityResult("Sodium", 30.0, "mg/L as CaCO3"),
                   WaterQualityResult("Sodium", None, "mg/L as CaCO3", greater_than=20.0),
                   WaterQualityResult("Sodium", None, "mg/L as CaCO3", detection_limit=1.0,
                                      below_detection=True)):
        a = assessed(result)
        assert [f.level for f in a.flags if f.code == "unit_basis_assumed"] == ["warning"]
        assert _row(a, "Sodium").basis_reason == "unit_basis_assumed"


# ---------------------------------------------- a count per 100 mL, with a space

@pytest.mark.parametrize("spelling", [
    "/100 mL", "No./100 mL", "per 100 mL", "CFU/100mL", "MPN/100 mL", "#/100 mL",
    "count/100 mL", "per 100 millilitres", "N\u00ba/100 mL", "N\u00b0 per 100 mL"])
def test_every_spelling_of_a_count_per_100_ml_is_one_unit(spelling):
    assert parse_unit(spelling).canonical == "CFU/100 mL"


def test_an_e_coli_count_in_a_spaced_unit_is_a_detection():
    """12 or "Present" in "No./100 mL" were unreadable units and "Not proven
    safe", while "Absent" in the same unit passed."""
    for cell in (12, "Present"):
        a = assess_sample(quality_from_grid(_sheet(
            ["pH", "pH units", 7.1, ""], ["E. coli", "No./100 mL", cell, ""],
            ["Arsenic", "mg/L", 0.001, ""], ["Fluoride", "mg/L", 0.2, ""],
            ["Nitrate", "mg/L", 3.1, ""]), "s.xlsx"))
        assert a.verdict_state == "health_fail", cell
        assert _row(a, "E. coli").status == "exceeds_health", cell


def test_a_count_seen_and_not_numbered_is_above_zero_whatever_its_unit():
    """"Present" or "TNTC" is a count above zero, and zero is zero on every
    count scale: refused on its unit, a detection was an open question."""
    a = assess_sample(_sample(
        *[WaterQualityResult(p, v, u) for p, v, u in PANEL],
        WaterQualityResult("Nitrate", 3.0, "mg/L"),
        WaterQualityResult("Total coliforms", None, "colonies", greater_than=0.0),
        WaterQualityResult("Faecal coliforms", None, "mg/L", greater_than=0.0),
    ))
    coliforms = _row(a, "Total coliforms")
    assert coliforms.status == "exceeds_national"
    assert ("in 'colonies': the reported unit could not be read; a count above zero "
            "is above zero whatever the unit") in coliforms.remark
    assert _row(a, "Faecal coliforms").status == "exceeds_health"
    # a bound that is not zero still needs its unit
    bounded = assess_sample(_sample(WaterQualityResult(
        "Total coliforms", None, "colonies", greater_than=5.0)))
    assert bounded.rows[0].status == "indeterminate"


# ------------------------------------------- a determinand with no guideline value

def test_a_unit_on_a_determinand_with_no_limit_does_not_hold_up_the_verdict():
    """"27 oC" and "mg/L Ca" made a fully graded sample "not proven safe"
    over determinands with no limit to compare them with."""
    for temperature_unit in ("oC", "ºC"):
        a = assess_sample(_with_panel(("Nitrate", 3.1, "mg/L"),
                                      ("Temperature", 29.0, temperature_unit)))
        assert _row(a, "Temperature").value_in_guideline_unit == 29.0
        assert a.verdict_state == "pass"
    a = assess_sample(_with_panel(
        ("Nitrate", 3.1, "mg/L"), ("Calcium", 8.0, "mg/L Ca"),
        ("Alkalinity", 30.0, "mg/L CaCO3"), ("Temperature", 29.0, "wibbles")))
    assert a.verdict_state == "pass", a.uncertainties
    calcium = _row(a, "Calcium")
    assert (calcium.status, calcium.reason) == ("no_guideline", "unit_unreadable")
    assert calcium.remark == phrase(
        "quality.no_guideline_unit", note=load_standards()["calcium"].note,
        unit="mg/L Ca", why="the reported unit could not be read")
    assert [f.code for f in a.flags].count("value_not_used") == 3
    # a bound on such a determinand, in a unit that is read, is no refusal
    bound = assess_sample(_sample(WaterQualityResult("Silica", None, "mg/L",
                                                     greater_than=10.0)))
    assert bound.rows[0].status == "no_guideline"
    assert "value_not_used" not in [f.code for f in bound.flags]
    assert phrase("quality.temperature_unreadable") in a.corrosivity.assumptions
    # a temperature nobody reported is still not reported
    absent = assess_sample(_with_panel(("Calcium", 8.0, "mg/L"),
                                       ("Alkalinity", 30.0, "mg/L as CaCO3")))
    assert phrase("quality.temperature_not_reported") in absent.corrosivity.assumptions
    # a determinand with a limit still refuses an unreadable unit
    iron = assess_sample(_with_panel(("Iron", 0.1, "wibbles")))
    assert _row(iron, "Iron").status == "indeterminate"


# --------------------------------------------------------- a clock is a clock

@pytest.mark.parametrize("cell,header,minutes,status", [
    ("0:30", "Time (mm:ss)", 0.5, "clock"), ("1:30", "Time (mm:ss)", 1.5, "clock"),
    ("2:00", "Time (hh:mm)", 120.0, "clock"), ("1:30", "Time (min)", 90.0, "clock"),
    ("1:60", "Time (min)", None, "unknown"), ("12 min", "Time (min)", 12.0, "ok"),
])
def test_a_clock_is_a_clock_wherever_a_time_is_read(cell, header, minutes, status):
    """read_quantity took the first number of "2:00" under "Time (hh:mm)" as
    2 minutes, and of "0:30" under "Time (mm:ss)" as none."""
    q = read_quantity(cell, header, dimension="time")
    assert (q.value, q.status) == (minutes, status)


# ------------------------------------------------------------- the gravel pack

def _log(intervals, grout=None, depth=None):
    return DrillingLog(
        site=SiteMetadata(community="X"), total_depth_m=depth or intervals[-1][1],
        intervals=[LithologyInterval(t, b, d) for t, b, d in intervals],
        grouting_depth_m=grout)


WIDE = DesignRules(borehole_diameter_in=10.0, casing_diameter_in=4.0)


def test_a_screen_the_design_places_leaves_room_for_the_pack_above_it():
    """A 20 m grout over a fracture at 20-26 m put the screen at 20 m, the
    pack clamped to the seal's foot and grout on the screen; the basis said
    the pack ran 2 m above the top screen."""
    log = _log([[0, 10, "Laterite"], [10, 20, "Granite"], [20, 26, "Granite, fractured"],
                [26, 60, "Granite"]], grout=20)
    d = design_borehole(log=log, static_water_level_m=5, rules=WIDE)
    assert [(s.top_m, s.bottom_m) for s in d.screens] == [(22.0, 26.0)]
    assert d.gravel_pack == (20.0, 60.0)
    assert ("gravel pack (well sorted siliceous gravel, 2-4 mm) from 20 m to the bottom, "
            "2 m above the top screen") in d.design_basis
    assert "gravel_pack_short" not in [f.code for f in d.flags]
    # a hole too narrow for a pack keeps the seal alone as the floor
    thin = design_borehole(log=log, static_water_level_m=5)
    assert thin.screens[0].top_m == 20.0


def test_a_zone_in_the_packs_room_is_said_to_be_there():
    log = _log([[0, 10, "Laterite"], [10, 45, "Granite, fracture zone 20-21 m"],
                [45, 60, "Granite"]], grout=20)
    d = design_borehole(log=log, static_water_level_m=5, rules=WIDE)
    assert ("the 20-21 m fracture zone is not screened: it lies within the 20 m grouted "
            "interval with the 2 m of gravel pack under it") in d.design_basis


def test_a_pack_the_seal_holds_down_is_said_to_be_and_flagged():
    """An as-built or analyst screen at 15 m in a 20 m grout has its pack
    from 20 m, 5 m below the top screen; it was "2 m above" it, with no
    flag."""
    log = _log([[0, 60, "Granite"]], grout=20)
    for top, where in ((15, "5 m below the top screen"), (20, "level with the top screen"),
                       (21, "1 m above the top screen"), (22, "2 m above the top screen")):
        d = design_borehole(log=log, static_water_level_m=5, rules=WIDE,
                            screens_m=[(top, top + 10)])
        assert (f"gravel pack (well sorted siliceous gravel, 2-4 mm) from 20 m to the "
                f"bottom, {where}") in d.design_basis, top
        short = [f for f in d.flags if f.code == "gravel_pack_short"]
        assert len(short) == (top < 22), top
        if short:
            assert short[0].level == "warning"
            assert short[0].message == phrase(
                "design.fill_short", fill="gravel pack", top=20.0, seal=20.0,
                screen=float(top), rule=2.0, need=22.0)


@pytest.mark.parametrize("grout,top", [(15.4, 17.4), (6.2, 8.2), (14.4, 16.4), (30.3, 32.3)])
def test_a_screen_exactly_the_packs_height_below_the_seal_is_not_short(grout, top):
    """17.4 - 2 is 15.399999999999999, under a 15.4 m seal, so a screen that
    leaves the full 2 m was flagged gravel_pack_short beside a basis saying
    the pack ran 2 m above it."""
    log = _log([[0, 60, "Granite"]], grout=grout)
    d = design_borehole(log=log, static_water_level_m=5, rules=WIDE, screens_m=[(top, 40)])
    assert "gravel_pack_short" not in [f.code for f in d.flags]
    assert (f"gravel pack (well sorted siliceous gravel, 2-4 mm) from {grout:g} m to the "
            "bottom, 2 m above the top screen") in d.design_basis


@pytest.mark.parametrize("grout,top", [(7.3, 8.3), (7.8, 8.8), (15.1, 16.1), (31.2, 32.2)])
def test_a_screen_a_hair_over_the_packs_height_below_the_seal_leaves_no_backfill(grout, top):
    """8.3 - 1 is 7.300000000000001, over a 7.3 m seal, so the pack started
    a few femtometres under the seal and the summary read "Backfill 7.3-7.3
    m"."""
    rules = DesignRules(borehole_diameter_in=10.0, casing_diameter_in=4.0,
                        gravel_pack_above_top_screen_m=1.0)
    d = design_borehole(log=_log([[0, 60, "Granite"]], grout=grout), static_water_level_m=5,
                        rules=rules, screens_m=[(top, 40)])
    assert d.gravel_pack[0] == d.backfill[0] == d.backfill[1] == grout
    assert ("Backfill", "none") in d.summary_rows()
    assert "gravel_pack_short" not in [f.code for f in d.flags]


# ------------------------------------------------- the browser's engine agrees

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const cases = JSON.parse(readFileSync(0, 'utf8'));
const result = (r) => Object.assign({ value: null, unit: '', detection_limit: null,
  below_detection: false, method: '', greater_than: null, greater_than_inclusive: false,
  unreadable: '' }, r);
const summary = (a) => ({
  state: a.verdict_state, statuses: a.rows.map((r) => r.status),
  reasons: a.rows.map((r) => r.reason), remarks: a.rows.map((r) => r.remark),
  converted: a.rows.map((r) => r.value_in_guideline_unit),
  flags: a.flags.map((f) => [f.level, f.code, f.message]),
  ionic: a.ionic ? a.ionic.error_percent : null,
  hi: a.health_risk ? a.health_risk.hazard_index : null,
  wqi: a.wqi ? [a.wqi.value, a.wqi.n_parameters, a.wqi.top_contributors] : null,
  corrosivity: [a.corrosivity.lsi, a.corrosivity.rsi, a.corrosivity.assumptions],
});
process.stdout.write(JSON.stringify({
  samples: cases.samples.map((rows) => summary(C.assessSample({ results: rows.map((r) =>
    result(Object.assign({ parameter: r[0], value: r[1], unit: r[2] }, r[3] || {}))),
    flags: [] }))),
  cells: cases.cells.map((c) => { const r = C.readQualityCell(c); return [r.kind, r.number, r.unit]; }),
  sheets: cases.sheets.map((g) => {
    const s = C.qualityFromGrid(g, 's.xlsx');
    return { results: s.results.map((r) => [r.parameter, r.value, r.unit, r.unreadable]),
      assessment: summary(C.assessSample(s)) };
  }),
  names: cases.names.map((n) => C.normaliseParameter(n)),
  units: cases.units.map((u) => { const p = C.parseUnit(u); return p ? p.canonical : null; }),
  quantities: cases.quantities.map((q) => {
    const r = C.readQuantity(q[0], [q[1]], 'time'); return [r.value, r.status];
  }),
  designs: cases.designs.map((spec) => {
    const d = C.designBorehole({
      log: { total_depth_m: spec.total, intervals: spec.intervals.map((r) => ({
        top_m: r[0], bottom_m: r[1], description: r[2] })), water_strikes_m: [],
        grouting_depth_m: spec.grout, installed_screens_m: [] },
      staticWaterLevelM: 5, pumpIntakeM: null, pumpIntakeFloorM: null,
      rules: Object.assign({}, C.defaultConfig().design, spec.rules),
      screensM: spec.screens || null });
    return { screens: d.screens.map((s) => [s.top_m, s.bottom_m]), basis: d.design_basis,
      flags: d.flags.map((f) => [f.level, f.code, f.message]) };
  }),
}));
"""

_IONS = [["Calcium", 40.078, "mg/L"], ["Magnesium", 12.1525, "mg/L"],
         ["Sodium", 16.426355, "mg/L"], ["Chloride", 35.453, "mg/L"],
         ["Bicarbonate", 61.017, "mg/L"], ["Sulfate", 48.03, "mg/L"]]
_CASES = {
    "samples": [
        PANEL + [["Nitrate (NO3-N)", 20.0, "mg/L"], ["Nitrite (NO2-N)", 0.5, "mg/L"]],
        PANEL + _IONS + [["Nitrate", 44.2664, "mg/L"]],
        PANEL + _IONS + [["Nitrate (as N)", 10.0, "mg/L"]],
        PANEL + _IONS + [["Nitrate", 10.0, "mg/L as N"]],
        PANEL + _IONS + [["Nitrate-N", 10.0, "mg/L"], ["Nitrate", 44.2664, "mg/L"]],
        PANEL + [["Nitrate (as NO3)", 10.0, "mg/L as N"], ["Nitrate-N", 44.0, "mg/L as NO3"]],
        PANEL + [["Calcium", 50.037383, "mg/L as CaCO3"], ["Magnesium", 25.0, "mg/L as CaCO3"],
                 ["Alkalinity", 100.09, "mg/L as CaCO3"], ["Bicarbonate", 100.0, "mg/L as CaCO3"],
                 ["Carbonate", 5.0, "mg/L as CaCO3"], ["Nitrate", 4.0, "mg/L"]],
        PANEL + [["Nitrate", 3.1, "mg/L"], ["Calcium", 8.0, "mg/L Ca"],
                 ["Alkalinity", 30.0, "mg/L CaCO3"], ["Temperature", 29.0, "wibbles"]],
        PANEL + [["Nitrate", 3.1, "mg/L"], ["Temperature", 29.0, "oC"],
                 ["Calcium", 8.0, "mg/L"], ["Alkalinity", 30.0, "mg/L as CaCO3"]],
        # a name and a unit on different nitrogen bases, or another ion's
        PANEL + [["Nitrate-N", 44.0, "mg/L as NO3"], ["Nitrate (mg/L as N)", 44.0, "mg/L as NO3"],
                 ["Nitrite", 0.5, "mg/L as NO3-N"], ["Nitrate (mg/L as NO3)", 10.0, "mg/L as N"],
                 ["Ammonia", 1.0, "mg/L as NH4-N"], ["Nitrate", 10.0, "mg/L as NO3−N"]],
        PANEL + [["Nitrate (mg/L as N)", 20.0, "mg/L"], ["Nitrite (mg N/L)", 0.5, ""]],
        # bounds and detection limits put on another basis
        PANEL + [["Nitrate", None, "mg/L as N", {"below_detection": True,
                                                 "detection_limit": 0.1}],
                 ["Nitrite", None, "mg/L as N", {"below_detection": True,
                                                 "detection_limit": 1.0}],
                 ["Calcium", None, "mg/L as CaCO3", {"greater_than": 20.0}]],
        PANEL + [["Nitrate", None, "mg/L as N", {"greater_than": 20.0}]],
        PANEL + [["Nitrate (NO3-N)", None, "mg/L", {"greater_than": 20.0}],
                 ["Nitrite-N", None, "mg/L", {"below_detection": True,
                                              "detection_limit": 0.1}]],
    ],
    "sheets": [
        _sheet(["pH", "pH units", 7.1, ""], ["E. coli", "CFU/100 mL", 0, ""],
               ["Arsenic", "ug/L", "0.05 mg/L", ""], ["Fluoride", "mg/L", 0.2, ""],
               ["Nitrate", "mg/L", 3.1, ""], ["Manganese", "ug/L", "<0.05 mg/L", ""],
               ["Lead", "", "8 ug/L", ""], ["Iron", "mg/L", "5 NTU", ""],
               ["Alkalinity", "mg/L as CaCO3", "46 mg/L", ""],
               ["Nitrite", "mg/L", "0.1 mg/L as N", ""], ["Zinc", "mg/L", "0.5 ND", ""]),
        _sheet(["Arsenic", "", 5], ["Lead", "mg/L", 0.003], ["Manganese", "-", 40],
               ["E. coli", "", 0], header=("Parameter", "Unit", "Result (ug/L)")),
        _sheet(["E. coli", "No./100 mL", 12, ""], ["Total coliforms", "per 100 mL", "Present", ""],
               ["Arsenic", "mg/L", 0.001, ""], ["Fluoride", "mg/L", 0.2, ""],
               ["Nitrate", "mg/L", 3.1, ""]),
        _sheet(["E. coli", "colonies", "TNTC", ""], ["Arsenic", "mg/L", 0.001, ""]),
        # E-notation, a symbol after the unit, and qualifier letters
        _sheet(["pH", "pH units", 7.1, ""], ["E. coli", "CFU/100 mL", 0, ""],
               ["Arsenic", "ug/L", "5.0E-02 mg/L", ""], ["Fluoride", "mg/L", "0.2 H", ""],
               ["Nitrate", "mg/L", "3.1 S", ""], ["Lead", "", "8E+00 ug/L", ""],
               ["Iron", "ug/L", "0.05 mg/L As", ""], ["Copper", "mg/L", "0.1 C", ""],
               ["Zinc", "mg/L", "0.003 D", ""], ["Nitrite", "mg/L", "0.1 (N)", ""],
               ["Electrical conductivity", "uS/cm", "450 uS/cm at 25 C", ""]),
    ],
    "cells": ["5.0E-02 mg/L", "<5.0E-02 mg/L", ">2E+01 CFU/100 mL", "0.05 mg/L As",
              "25 mg/L (CaCO3)", "10 mg/L (as N)", "10 NO3-N", "0.003 D", "20 C", "27 oC",
              "450 uS/cm @25°C", "1,250.5 mg/L", "approx 0.05 mg/L", "0.05 (DL 0.01)"],
    "names": ["Nitrate (NO3-N)", "Nitrate (N)", "Nitrate (NO3 as N)", "Nitrate (as NO3-N)",
              "Nitrite (NO2-N)", "Ammonium (NH4-N)", "Nitrite (NO3-N)", "Nitrate (NO3)",
              "Nitrate (nitrogen)", "Nitrate (NO3 – N)", "Nitrate (mg/L as N)",
              "Nitrate (mg N/L)", "Nitrate (NO3−N)", "Nitrate (mg/L as NO2-N)",
              "Nitrate (mg/L as NO3)"],
    "units": ["/100 mL", "No./100 mL", "per 100 mL", "#/100 mL", "oC", "ºC", "mg/L CaCO3"],
    "quantities": [["0:30", "Time (mm:ss)"], ["2:00", "Time (hh:mm)"], ["1:60", "Time (min)"],
                   ["1:30 pm", "Time"], ["12 min", "Time (min)"]],
    "designs": [
        {"total": 60, "grout": 20, "rules": {"borehole_diameter_in": 10, "casing_diameter_in": 4},
         "intervals": [[0, 10, "Laterite"], [10, 20, "Granite"], [20, 26, "Granite, fractured"],
                       [26, 60, "Granite"]]},
        {"total": 60, "grout": 20, "rules": {"borehole_diameter_in": 10, "casing_diameter_in": 4},
         "intervals": [[0, 10, "Laterite"], [10, 45, "Granite, fracture zone 20-21 m"],
                       [45, 60, "Granite"]]},
        {"total": 24, "grout": 20, "rules": {"borehole_diameter_in": 10, "casing_diameter_in": 4},
         "intervals": [[0, 24, "Granite"]]},
        {"total": 60, "grout": 20, "rules": {"borehole_diameter_in": 8, "casing_diameter_in": 4},
         "intervals": [[0, 60, "Granite"]], "screens": [[15, 25]]},
        {"total": 60, "grout": 20, "rules": {"borehole_diameter_in": 10, "casing_diameter_in": 4},
         "intervals": [[0, 60, "Granite"]], "screens": [[21, 30]]},
        # a screen exactly the pack's height under a seal that is not a round number
        {"total": 60, "grout": 15.4, "rules": {"borehole_diameter_in": 10,
                                               "casing_diameter_in": 4},
         "intervals": [[0, 60, "Granite"]], "screens": [[17.4, 40]]},
        {"total": 60, "grout": 30.3, "rules": {"borehole_diameter_in": 10,
                                               "casing_diameter_in": 4},
         "intervals": [[0, 60, "Granite"]], "screens": [[32.3, 50]]},
    ],
}


def _summary(a) -> dict:
    return {
        "state": a.verdict_state, "statuses": [r.status for r in a.rows],
        "reasons": [r.reason for r in a.rows], "remarks": [r.remark for r in a.rows],
        "converted": [r.value_in_guideline_unit for r in a.rows],
        "flags": [[f.level, f.code, f.message] for f in a.flags],
        "ionic": a.ionic.error_percent if a.ionic else None,
        "hi": a.health_risk.hazard_index if a.health_risk else None,
        "wqi": ([a.wqi.value, a.wqi.n_parameters, [list(c) for c in a.wqi.top_contributors]]
                if a.wqi else None),
        "corrosivity": [a.corrosivity.lsi, a.corrosivity.rsi, a.corrosivity.assumptions],
    }


def _python_answers() -> dict:
    out: dict = {"samples": [], "sheets": [], "designs": []}
    for rows in _CASES["samples"]:
        out["samples"].append(_summary(assess_sample(_sample(
            *[WaterQualityResult(r[0], r[1], r[2], **(r[3] if len(r) > 3 else {}))
              for r in rows]))))
    out["cells"] = [[c["kind"], c["number"], c["unit"]]
                    for c in (_read_cell(cell) for cell in _CASES["cells"])]
    for grid in _CASES["sheets"]:
        s = quality_from_grid(grid, "s.xlsx")
        out["sheets"].append({
            "results": [[r.parameter, r.value, r.unit, r.unreadable] for r in s.results],
            "assessment": _summary(assess_sample(s))})
    out["names"] = [normalise_parameter(n) for n in _CASES["names"]]
    out["units"] = [(lambda p: p.canonical if p else None)(parse_unit(u))
                    for u in _CASES["units"]]
    out["quantities"] = [[q.value, q.status] for q in (
        read_quantity(c, h, dimension="time") for c, h in _CASES["quantities"])]
    for spec in _CASES["designs"]:
        d = design_borehole(log=_log(spec["intervals"], spec["grout"], spec["total"]),
                            static_water_level_m=5, rules=DesignRules(**spec["rules"]),
                            screens_m=[tuple(s) for s in spec.get("screens", [])] or None)
        out["designs"].append({
            "screens": [[s.top_m, s.bottom_m] for s in d.screens], "basis": d.design_basis,
            "flags": [[f.level, f.code, f.message] for f in d.flags]})
    return out


def _part(js, py, path=""):
    """The first place two answers part: numbers to 1e-12 relative,
    everything else exactly."""
    if isinstance(py, (int, float)) and isinstance(js, (int, float)) and not isinstance(py, bool):
        return None if math.isclose(js, py, rel_tol=1e-12, abs_tol=1e-12) else f"{path}: {js} vs {py}"
    if isinstance(py, dict) and isinstance(js, dict):
        if set(py) != set(js):
            return f"{path}: keys {sorted(js)} vs {sorted(py)}"
        return next((d for d in (_part(js[k], py[k], f"{path}.{k}") for k in py) if d), None)
    if isinstance(py, (list, tuple)) and isinstance(js, list):
        if len(py) != len(js):
            return f"{path}: length {len(js)} vs {len(py)}"
        return next((d for d in (_part(a, b, f"{path}[{i}]")
                                 for i, (a, b) in enumerate(zip(js, py, strict=True))) if d), None)
    return None if js == py else f"{path}: js {js!r} vs py {py!r}"


def test_the_browser_engine_reads_and_grades_alike(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path / "quality_units.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS)], input=json.dumps(_CASES),
                          capture_output=True, text=True, encoding="utf-8", check=True)
    found = _part(json.loads(done.stdout), _python_answers())
    assert found is None, found

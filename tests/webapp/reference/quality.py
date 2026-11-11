"""Water quality: the laboratory results the quality, units and design audit
found misread, and the verdict, the sheet reader's cells, the facies and the
corrosivity sentences over samples built to reach every state - the
"quality_units", "verdicts", "quality_cells", "facies", "corrosivity_ph",
"spine_range_ratio" and "spine_quality" entries of ``reference.json``.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from groundwater.ingestion.waterquality import quality_from_grid
from groundwater.models import SiteMetadata, WaterQualityResult, WaterQualitySample
from groundwater.quality import assess_sample
from groundwater.quality.assess import unquantified_text
from groundwater.quality.corrosivity import assess_corrosivity
from groundwater.quality.diagrams import facies_of
from groundwater.reporting.quality import quality_recommendations

from .common import clean


#: Laboratory results the quality, units and design audit found misread,
#: each as [parameter, value, unit] or [parameter, None, unit, extra], where
#: extra names the other WaterQualityResult fields. The browser reads the same
#: rows from reference.json.
_QPANEL = [["pH", 7.0, "pH units"], ["E. coli", 0.0, "CFU/100 mL"],
           ["Arsenic", 0.001, "mg/L"], ["Fluoride", 0.2, "mg/L"]]
_QIONS = [["Calcium", 40.078, "mg/L"], ["Magnesium", 12.1525, "mg/L"],
          ["Sodium", 16.426355, "mg/L"], ["Chloride", 35.453, "mg/L"],
          ["Bicarbonate", 61.017, "mg/L"], ["Sulfate", 48.03, "mg/L"]]
QUALITY_CASES = {
    # nitrate and nitrite reported as nitrogen, by name and by unit
    "nitrogen_by_name": _QPANEL + [["Nitrate (NO3-N)", 20.0, "mg/L"],
                                   ["Nitrite (NO2-N)", 0.5, "mg/L"]],
    "nitrogen_spellings": _QPANEL + [["Nitrate (N)", 2.0, "mg/L"],
                                     ["Nitrite (NO2 as N)", 0.1, "mg/L"],
                                     ["Ammonium (NH4-N)", 0.2, "mg/L"]],
    "nitrogen_combined_by_name": _QPANEL + [["Nitrate (NO3-N)", 9.0, "mg/L"],
                                            ["Nitrite (NO2-N)", 0.5, "mg/L"]],
    "nitrogen_contradicted": _QPANEL + [["Nitrite (NO3-N)", 0.5, "mg/L"],
                                        ["Nitrate", 3.0, "mg/L"]],
    "nitrate_in_mg_n": _QPANEL + [["Nitrate", 10.0, "mg/L as N"]],
    "nitrate_n_in_mg_no3": _QPANEL + [["Nitrate-N", 44.0, "mg/L as NO3"]],
    "nitrate_basis_contradicted": _QPANEL + [["Nitrate (as NO3)", 10.0, "mg/L as N"]],
    # a name and a unit on different nitrogen bases, or on another ion's
    # nitrogen, are refused; a unit on the name's own nitrogen is read
    "nitrogen_name_and_unit_apart": _QPANEL + [
        ["Nitrate (NO3-N)", 44.0, "mg/L as NO3"], ["Nitrite", 0.5, "mg/L as NO3-N"],
        ["Nitrate (NO3)", 5.0, "mg/L as NH4-N"], ["Nitrate (mg/L as NO3)", 10.0, "mg/L as N"],
        ["Nitrite-N", 1.0, "mg/L as NO2"], ["Ammonia", 1.0, "mg/L as NO3-N"]],
    "basis_name_against_own_unit": _QPANEL + [
        ["Calcium (mg/L as CaCO3)", 20.0, "mg/L as Ca"],
        ["Nitrate (mg/L as NO2)", 5.0, "mg/L as NO3"]],
    "nitrogen_name_and_unit_agree": _QPANEL + [
        ["Nitrate", 2.0, "mg/L as NO3\u2212N"], ["Nitrite", 0.1, "mg/L as NO2-N"],
        ["Ammonia", 1.0, "mg/L as NH4-N"], ["Nitrate (NO3-N)", 2.0, "mg/L as NO3-N"]],
    # nitrogen named with its unit in the name's bracket
    "nitrogen_unit_in_name": _QPANEL + [
        ["Nitrate (mg/L as N)", 20.0, "mg/L"], ["Nitrite (mg N/L)", 0.5, ""]],
    "nitrogen_unit_in_name_spellings": _QPANEL + [
        ["Nitrate (mgN/L)", 2.0, "mg/L"], ["Nitrate (NO3\u2212N)", 2.0, "mg/L"],
        ["Nitrite (mg/l as N)", 0.1, "mg/L"]],
    # a bound and a detection limit put on another basis, or taken as the
    # guideline's, say so as a measured value does
    "bases_of_bounds": _QPANEL + [
        ["Nitrate", None, "mg/L as N", {"detection_limit": 0.1, "below_detection": True}],
        ["Nitrite", None, "mg/L as N", {"detection_limit": 1.0, "below_detection": True}],
        ["Calcium", None, "mg/L as CaCO3", {"greater_than": 20.0}],
        ["Sodium", None, "mg/L as CaCO3", {"detection_limit": 1.0, "below_detection": True}],
        ["Potassium", None, "mg/L as CaCO3", {"greater_than": 2.0}]],
    "nitrate_bound_as_n": _QPANEL + [["Nitrate", None, "mg/L as N", {"greater_than": 20.0}]],
    "nitrogen_named_bounds": _QPANEL + [
        ["Nitrate (NO3-N)", None, "mg/L", {"greater_than": 20.0}],
        ["Nitrite-N", None, "mg/L", {"detection_limit": 0.1, "below_detection": True}],
        ["Nitrite (NO2-N)", None, "mg/L", {"detection_limit": 2.0, "below_detection": True}]],
    # the same water, nitrate as the ion and as nitrogen, through the indices
    "ions_as_ion": _QPANEL + _QIONS + [["Nitrate", 10.0 * 62.004 / 14.007, "mg/L"]],
    "ions_as_n_by_name": _QPANEL + _QIONS + [["Nitrate (as N)", 10.0, "mg/L"]],
    "ions_as_n_by_unit": _QPANEL + _QIONS + [["Nitrate", 10.0, "mg/L as N"]],
    "ions_both_forms": _QPANEL + _QIONS + [["Nitrate-N", 10.0, "mg/L"],
                                           ["Nitrate", 10.0 * 62.004 / 14.007, "mg/L"]],
    "nitrite_as_n_indices": _QPANEL + _QIONS + [["Nitrate", 4.0, "mg/L"],
                                                ["Nitrite-N", 0.5, "mg/L"],
                                                ["Iron", 0.1, "mg/L"]],
    "nitrate_n_below_detection": _QPANEL + _QIONS + [
        ["Nitrate-N", None, "mg/L", {"detection_limit": 0.1, "below_detection": True}]],
    # calcium, magnesium, bicarbonate and carbonate as CaCO3
    "caco3_as_element": _QPANEL + [
        ["Nitrate", 4.43, "mg/L"], ["Sodium", 36.126486, "mg/L"],
        ["Chloride", 17.7265, "mg/L"], ["Alkalinity", 100.09, "mg/L as CaCO3"],
        ["Sulfate", 24.015, "mg/L"], ["TDS", 200, "mg/L"], ["Temperature", 27, "deg C"],
        ["Calcium", 20.039, "mg/L"], ["Magnesium", 6.076, "mg/L"]],
    "caco3_as_caco3": _QPANEL + [
        ["Nitrate", 4.43, "mg/L"], ["Sodium", 36.126486, "mg/L"],
        ["Chloride", 17.7265, "mg/L"], ["Alkalinity", 100.09, "mg/L as CaCO3"],
        ["Sulfate", 24.015, "mg/L"], ["TDS", 200, "mg/L"], ["Temperature", 27, "deg C"],
        ["Calcium", 50.037383, "mg/L as CaCO3"], ["Magnesium", 25.020968, "mg/L as CaCO3"]],
    "caco3_carbonates": _QPANEL + [
        ["Nitrate", 4.0, "mg/L"], ["Calcium", 20.0, "mg/L as Ca"],
        ["Magnesium", 5.0, "mg/L as Ca"], ["Bicarbonate", 100.0, "mg/L as CaCO3"],
        ["Carbonate", 5.0, "mg/L as CaCO3"], ["Sodium", 10.0, "mg/L as CaCO3"]],
    # E. coli and coliform counts in units with a space, or none readable
    "ecoli_per_100_ml_spaced": _QPANEL[:1] + [["E. coli", 12.0, "No./100 mL"],
                                              ["Arsenic", 0.001, "mg/L"],
                                              ["Fluoride", 0.2, "mg/L"],
                                              ["Nitrate", 3.0, "mg/L"]],
    "counts_in_any_unit": _QPANEL + [
        ["Nitrate", 3.0, "mg/L"],
        ["Total coliforms", None, "colonies", {"greater_than": 0.0}],
        ["Faecal coliforms", None, "mg/L", {"greater_than": 0.0}],
        ["Total coliforms", None, "per 100 mL", {"greater_than": 0.0}]],
    "count_bound_needs_unit": _QPANEL + [
        ["Nitrate", 3.0, "mg/L"],
        ["Total coliforms", None, "colonies", {"greater_than": 5.0}]],
    # a determinand with no guideline value, in a unit that cannot be read
    "no_limit_units": _QPANEL + [
        ["Nitrate", 3.1, "mg/L"], ["Calcium", 8.0, "mg/L Ca"],
        ["Alkalinity", 30.0, "mg/L CaCO3"], ["Temperature", 29.0, "wibbles"],
        ["Potassium", None, "wibbles", {"greater_than": 1.0}],
        ["Silica", None, "mg/L", {"greater_than": 10.0}],
        ["Magnesium", 5.0, "mg/L as Ca"]],
    "temperature_oc": _QPANEL + [
        ["Nitrate", 3.1, "mg/L"], ["Temperature", 29.0, "oC"], ["Calcium", 8.0, "mg/L"],
        ["Alkalinity", 30.0, "mg/L as CaCO3"]],
    "temperature_degree_ordinal": _QPANEL + [
        ["Nitrate", 3.1, "mg/L"], ["Temperature", 29.0, "\u00baC"], ["Calcium", 8.0, "mg/L"],
        ["Alkalinity", 30.0, "mg/L as CaCO3"]],
    "temperature_unreadable": _QPANEL + [
        ["Nitrate", 3.1, "mg/L"], ["Temperature", 29.0, "degrees"], ["Calcium", 8.0, "mg/L"],
        ["Alkalinity", 30.0, "mg/L as CaCO3"]],
}

#: Laboratory sheets as grids, read by both sheet readers and assessed.
_QHEAD = [["Laboratory", "Central Lab"], ["Sample ID", "S"], []]
QUALITY_SHEETS = [
    # a unit written after a measured value, against its column
    _QHEAD + [["Parameter", "Unit", "Result", "Detection limit"],
              ["pH", "pH units", 7.1, ""], ["E. coli", "CFU/100 mL", 0, ""],
              ["Arsenic", "ug/L", "0.05 mg/L", ""], ["Fluoride", "mg/L", 0.2, ""],
              ["Nitrate", "mg/L", 3.1, ""], ["Manganese", "ug/L", "<0.05 mg/L", ""],
              ["Lead", "", "8 ug/L", ""], ["Iron", "mg/L", "5 NTU", ""],
              ["Alkalinity", "mg/L as CaCO3", "46 mg/L", ""],
              ["Nitrite", "mg/L", "0.1 mg/L as N", ""], ["Zinc", "mg/L", "0.5 ND", ""],
              ["Copper", "mg/L", "0.2 (field)", ""], ["Sulfate", "mg/L", "20*", ""],
              ["Temperature", "", "27 oC", ""]],
    # a unit in the result column's header
    _QHEAD + [["Parameter", "Unit", "Result (ug/L)"],
              ["Arsenic", "", 5], ["Lead", "mg/L", 0.003], ["Manganese", "-", 40],
              ["Cadmium", "", "<1"], ["E. coli", "", 0]],
    _QHEAD + [["Parameter", "Result (lab)"], ["Arsenic", 0.004], ["Lead", "2 ug/L"]],
    # counts per 100 mL written with a space
    _QHEAD + [["Parameter", "Unit", "Result", "Detection limit"],
              ["pH", "pH units", 7.1, ""], ["E. coli", "No./100 mL", "Present", ""],
              ["Total coliforms", "per 100 mL", 12, ""], ["Arsenic", "mg/L", 0.001, ""],
              ["Fluoride", "mg/L", 0.2, ""], ["Nitrate", "mg/L", 3.1, ""]],
    _QHEAD + [["Parameter", "Unit", "Result", "Detection limit"],
              ["pH", "pH units", 7.1, ""], ["E. coli", "/100 mL", "Absent", ""],
              ["Total coliforms", "MPN/100 mL", 0, ""], ["Arsenic", "mg/L", 0.001, ""],
              ["Fluoride", "mg/L", 0.2, ""], ["Nitrate (NO3-N)", "mg/L", 2.0, ""]],
    # a number in E-notation keeps its unit, and a unit with more beside it,
    # a basis without "as" or a unit nobody reads refuses the cell
    _QHEAD + [["Parameter", "Unit", "Result", "Detection limit"],
              ["pH", "pH units", 7.1, ""], ["E. coli", "CFU/100 mL", 0, ""],
              ["Arsenic", "ug/L", "5.0E-02 mg/L", ""], ["Fluoride", "mg/L", 0.2, ""],
              ["Nitrate", "mg/L", 3.1, ""], ["Lead", "", "8E+00 ug/L", ""],
              ["Manganese", "ug/L", "<5.0E-02 mg/L", ""], ["Iron", "ug/L", "0.05 mg/L As", ""],
              ["Nitrite", "mg/L", "0.1 (N)", ""], ["Sodium", "mg/L", "5 meq/L", ""],
              ["Chloride", "mg/L", "(20 mg/L)", ""], ["Sulfate", "mg/L", "20 mg/L, est", ""],
              ["Copper", "ug/L", "0.05 (DL 0.01 mg/L)", ""]],
    # a laboratory's qualifier letter is a note, and a lone letter is a unit
    # only in its row's family
    _QHEAD + [["Parameter", "Unit", "Result", "Detection limit"],
              ["pH", "pH units", 7.1, ""], ["E. coli", "CFU/100 mL", 0, ""],
              ["Arsenic", "mg/L", "0.003 D", ""], ["Fluoride", "mg/L", "0.2 H", ""],
              ["Nitrate", "mg/L", "3.1 S", ""], ["Iron", "mg/L", "0.1 M", ""],
              ["Copper", "mg/L", "0.5 F", ""], ["Zinc", "mg/L", "0.1 C", ""],
              ["Temperature", "deg C", "68 F", ""],
              ["Electrical conductivity", "uS/cm", "450 uS/cm at 25 C", ""]],
]

#: Result cells, each with the dimension of its row's unit, read alone.
QUALITY_CELLS = [
    ["5.0E-02 mg/L", None], ["8E+00 ug/L", None], ["<5.0E-02 mg/L", None],
    [">2E+01 CFU/100 mL", None], ["5 E-02 mg/L", None], ["1,250.5 mg/L", None],
    ["1.234,5 mg/L", None], ["5. mg/L", None], ["(0.05 mg/L)", None],
    ["0.05 mg/L As", None], ["0.05 mg/L (As)", None], ["0.05 mg/L Fe", None],
    ["25 mg/L CaCO3", None], ["25 (CaCO3)", None], ["25 mg/L (as CaCO3)", None],
    ["10 NO3-N", None], ["10 (N)", None], ["10 mg N/L", None], ["10 mg/L (as N)", None],
    ["0.05 mg/L est", None], ["0.05 mg/L, field", None], ["5 meq/L", None], ["5 ppt", None],
    ["0.05 (DL 0.01)", None], ["0.05 (DL 0.01 mg/L)", None], ["0.05 mg/L (DL 0.01 mg/L)", None],
    ["0.003 D", "concentration"], ["0.2 H", None], ["0.1 M", None], ["0.1 C", "concentration"],
    ["68 F", "temperature"], ["68 F", None], ["20 C", "temperature"], ["7.1 at 25 C", "ph"],
    ["450 uS/cm @25\u00b0C", "conductivity"], ["0.5 ND", None], ["8 (field)", None],
    ["8 ug/L*", None], ["45 TCU", None],
]

#: Units the audit found unread or read apart, by spelling.
UNIT_SPELLINGS = [
    "/100 mL", "No./100 mL", "per 100 mL", "CFU/100mL", "MPN/100 mL", "#/100 mL",
    "count/100 mL", "per 100 millilitres", "cfu / 100 ml", "/100ml", "N\u00ba/100 mL",
    "N\u00b0 per 100 mL", "\u00b0N/100 mL", "oC", "\u00baC",
    "\u00b0 C", "o C", "mg/L as NO3-N", "mg/L as NO3\u2013N", "mg/l as nitrogen",
    "mg/L as NO2-N", "mg/L as N", "mg/L as Ca", "mg/L as CaCO3", "mg/L CaCO3", "mg/L Ca",
    "mg/L as NO3\u2212N", "mg/L as NH4-N",
]

#: Parameter names that say nitrogen, and some that do not.
PARAMETER_NAMES = [
    "Nitrate (NO3-N)", "Nitrate (N)", "Nitrate (NO3 as N)", "Nitrate (as NO3-N)",
    "Nitrate (NO3--N)", "Nitrate (NO3 \u2013 N)", "nitrate (no3n)", "Nitrate (nitrogen)",
    "Nitrite (NO2-N)", "Nitrite (no2 - n)", "Ammonia (NH3-N)", "Ammonium (NH4-N)",
    "Ammonium (as NH4-N)", "Nitrite (NO3-N)", "Nitrate (NO2-N)", "Nitrate (NO3)",
    "Nitrate (as NO3)", "Nitrate (as N)", "Nitrate", "NO3-N", "Nitrate-N (mg/L)",
    "Calcium (as CaCO3)", "Nitrate (mg/L as N)", "Nitrate (mg/l as N)", "Nitrate (mg N/L)",
    "Nitrate (mgN/L)", "Nitrate (ppm NO3-N)", "Nitrate (NO3\u2212N)", "Nitrate\u2212N",
    "Nitrite (mg/L as N)", "Nitrate (mg/L as NO2-N)", "Nitrate (mg/L as NO3)",
    "Nitrate (mg/L)",
]

#: Cells read in the time dimension by units.read_quantity, which took a
#: clock for its first number.
QUANTITY_CELLS = [
    ("0:30", "Time (mm:ss)"), ("1:30", "Time (mm:ss)"), ("2:00", "Time (hh:mm)"),
    ("1:30", "Time (min)"), ("00:05:30", "Time"), ("1:60", "Time (min)"),
    ("1:30 pm", "Time"), (True, "Time (min)"), ("12 pump stopped", "Time (min)"),
    ("90 s", "Time (min)"), ("1.5 hrs", "Time (min)"),
]


def _quality_result(row) -> WaterQualityResult:
    extra = row[3] if len(row) > 3 else {}
    return WaterQualityResult(row[0], row[1], row[2], **extra)


def _quality_summary(a) -> dict:
    return {
        "state": a.verdict_state,
        "statuses": [r.status for r in a.rows],
        "reasons": [r.reason for r in a.rows],
        "remarks": [r.remark for r in a.rows],
        "converted": [clean(r.value_in_guideline_unit) for r in a.rows],
        "guidelines": [r.who_health for r in a.rows],
        "uncertainties": list(a.uncertainties),
        "flags": [[f.level, f.code, f.message] for f in a.flags],
        "ionic": None if a.ionic is None else {
            "error": clean(a.ionic.error_percent),
            "cations": clean(a.ionic.cations_meq), "anions": clean(a.ionic.anions_meq)},
        "hazard": None if a.health_risk is None else {
            "index": a.health_risk.hazard_index,
            "quotients": a.health_risk.hazard_quotients},
        "wqi": None if a.wqi is None else {
            "value": a.wqi.value, "rating": a.wqi.rating, "n": a.wqi.n_parameters,
            "top": [list(c) for c in a.wqi.top_contributors]},
        "corrosivity": {
            "lsi": a.corrosivity.lsi, "rsi": a.corrosivity.rsi,
            "classification": a.corrosivity.classification,
            "assumptions": list(a.corrosivity.assumptions)},
        "verdict": a.verdict,
        "recommendations": quality_recommendations(a),
    }


def quality_units_reference() -> dict:
    """What the quality, units and design audit's cases come to in Python."""
    from groundwater.ingestion.waterquality import _read_cell
    from groundwater.quality.standards import normalise_parameter
    from groundwater.units import parse_unit, read_quantity

    def unit(text):
        u = parse_unit(text)
        return None if u is None else [u.canonical, u.dimension, u.factor, u.offset, u.basis]

    cases = {}
    for name, rows in QUALITY_CASES.items():
        sample = WaterQualitySample(site=SiteMetadata(community="Ref"),
                                    results=[_quality_result(r) for r in rows])
        cases[name] = {"rows": rows, **_quality_summary(assess_sample(sample))}
    sheets = []
    for grid in QUALITY_SHEETS:
        sample = quality_from_grid(grid, "sheet.xlsx")
        sheets.append({
            "grid": grid,
            "results": [[r.parameter, clean(r.value), r.unit, clean(r.detection_limit),
                         r.below_detection, clean(r.greater_than), r.greater_than_inclusive,
                         r.unreadable] for r in sample.results],
            **_quality_summary(assess_sample(sample)),
        })
    quantities = []
    for cell, header in QUANTITY_CELLS:
        q = read_quantity(cell, header, dimension="time")
        quantities.append({"cell": cell, "header": header, "value": clean(q.value),
                           "status": q.status, "unit": q.unit_text})
    cells = []
    for cell, dimension in QUALITY_CELLS:
        read = _read_cell(cell, dimension)
        cells.append([cell, dimension, read["kind"], clean(read["number"]), read["unit"]])
    return {
        "cases": cases, "sheets": sheets, "quantities": quantities, "cells": cells,
        "units": [[text, unit(text)] for text in UNIT_SPELLINGS],
        "names": [[name, normalise_parameter(name)] for name in PARAMETER_NAMES],
    }


def fill_quality(out: dict) -> None:
    """Fill "verdicts", "quality_cells", "facies", "corrosivity_ph",
    "spine_range_ratio" and "spine_quality": what the toolkit says of samples
    built here, which all go through the one ``_wq``.

    It fills ``out`` in place, where build() calls it: build.py says why."""
    # The verdict, over samples chosen to reach every state.
    def _wq(*results):
        return WaterQualitySample(site=SiteMetadata(community="Ref"),
                                  results=list(results))

    _panel = [
        WaterQualityResult("E. coli", 0.0, "CFU/100 mL"),
        WaterQualityResult("Arsenic", 0.001, "mg/L"),
        WaterQualityResult("Fluoride", 0.3, "mg/L"),
        WaterQualityResult("Nitrate (as NO3)", 5.0, "mg/L"),
    ]
    _cases = {
        "empty": _wq(),
        "pass": _wq(*_panel, WaterQualityResult("pH", 7.2, "pH units")),
        "aesthetic": _wq(*_panel, WaterQualityResult("Iron", 0.5, "mg/L")),
        # Aluminium used to be the national_fail case, on a WHO health value
        # of 0.9 mg/L that WHO does not set. Total coliforms above zero is
        # the real one: a national limit failure that is not a health
        # guideline failure and not faecal contamination.
        "national_fail": _wq(*_panel,
                             WaterQualityResult("Total coliforms", 5.0, "CFU/100 mL")),
        # a count the laboratory saw and did not put a number to, and a
        # ">100" inside its limit: both used to read as "not measured"
        "unquantified_count": _wq(*_panel, WaterQualityResult(
            "Total coliforms", None, "CFU/100 mL", greater_than=0.0)),
        "greater_than_inside_limit": _wq(*_panel, WaterQualityResult(
            "Sulfate", None, "mg/L", greater_than=100.0)),
        "health_fail": _wq(*_panel, WaterQualityResult("Arsenic", 0.5, "mg/L")),
        "micrograms": _wq(*_panel, WaterQualityResult("Lead", 5.0, "ug/L")),
        "bad_unit": _wq(*_panel, WaterQualityResult("Iron", 0.1, "wibbles")),
        "shallow_dl": _wq(*_panel, WaterQualityResult(
            "Cadmium", None, "mg/L", detection_limit=0.05, below_detection=True)),
        "unknown_parameter": _wq(
            *_panel, WaterQualityResult("Glyphosate", 0.4, "mg/L")),
        # the charge balance cannot be computed, and used to say nothing
        "no_ionic_balance": _wq(WaterQualityResult("Calcium", 40.0, "mg/L")),
        # a detection of a determinand the table does not know, which was
        # "not measured" and left the sample safe
        "unknown_detected": _wq(*_panel, WaterQualityResult(
            "Iron bacteria", None, "per 100 mL", greater_than=0.0)),
        # a faecal pathogen, by name: "Present" and a count fail on health,
        # nothing found is the requirement met, and a method that cannot see
        # one organism cannot show there are none; a plate count in CFU is
        # not a pathogen and stays an open question
        "pathogen_present": _wq(*_panel, WaterQualityResult(
            "Salmonella", None, "per 100 mL", greater_than=0.0)),
        "pathogen_counted": _wq(*_panel, WaterQualityResult(
            "Shigella spp.", 3.0, "CFU/100 mL")),
        "pathogen_absent": _wq(*_panel, WaterQualityResult(
            "Vibrio cholerae", None, "", below_detection=True),
            WaterQualityResult("Salmonella typhi", 0.0, "CFU/100 mL")),
        "pathogen_coarse_limit": _wq(*_panel, WaterQualityResult(
            "Cryptosporidium oocysts", None, "oocysts/10 L", detection_limit=10.0,
            below_detection=True)),
        "plate_count": _wq(*_panel, WaterQualityResult(
            "Heterotrophic plate count", 250.0, "CFU/mL")),
        # a national failure beside a result that could not be graded: the
        # verdict used to say the WHO health values were met
        "national_fail_unresolved": _wq(
            WaterQualityResult("E. coli", 0.0, "CFU/100 mL"),
            WaterQualityResult("Arsenic", None, "mg/L", detection_limit=0.05,
                               below_detection=True),
            WaterQualityResult("Total coliforms", 12.0, "CFU/100 mL")),
        # both ions reported as nitrogen, which skipped the combined rule
        "nitrogen_basis_combined": _wq(
            *_panel[:3], WaterQualityResult("Nitrate (as N)", 10.0, "mg/L"),
            WaterQualityResult("Nitrite (as N)", 0.8, "mg/L")),
        # lower bounds, on the guideline's scale and through its hierarchy
        "bound_in_micrograms": _wq(*_panel, WaterQualityResult(
            "Lead", None, "ug/L", greater_than=5.0)),
        "bound_acceptability": _wq(*_panel, WaterQualityResult(
            "Iron", None, "mg/L", greater_than=1.0)),
        "bound_stricter_open": _wq(*_panel, WaterQualityResult(
            "Copper", None, "mg/L", greater_than=1.5)),
        "bound_inclusive": _wq(*_panel[:3], WaterQualityResult(
            "Nitrate (as NO3)", None, "mg/L", greater_than=50.0,
            greater_than_inclusive=True)),
        "bound_exclusive": _wq(*_panel[:3], WaterQualityResult(
            "Nitrate (as NO3)", None, "mg/L", greater_than=50.0)),
        "unreadable": _wq(*_panel, WaterQualityResult(
            "Lead", None, "mg/L", unreadable="ND (see note)")),
        # treatment advice by table name, and pH advice by direction
        "advice_by_name": _wq(
            *_panel, WaterQualityResult("Faecal coliforms", 5.0, "CFU/100 mL"),
            WaterQualityResult("Sulphate", 400.0, "mg/L"),
            WaterQualityResult("pH", 9.2, "pH units")),
        "low_ph": _wq(*_panel, WaterQualityResult("pH", 5.9, "pH units")),
        "lead": _wq(*_panel, WaterQualityResult("Lead", 0.05, "mg/L")),
        # a table whose national iron value names its specification
        "confirmed_national": _wq(*_panel, WaterQualityResult("Iron", 1.2, "mg/L")),
    }
    # The standards table a case is assessed against, when it is not the
    # bundled one. The browser is given the same rows (parity.mjs).
    _confirmed = [
        {"parameter": "E. coli", "unit": "CFU/100 mL", "who_health_gv": "0",
         "who_aesthetic": "", "sl_standard": "0", "sl_source": "SLSB 2021",
         "category": "microbiological", "note": ""},
        {"parameter": "Arsenic", "unit": "mg/L", "who_health_gv": "0.01",
         "who_aesthetic": "", "sl_standard": "0.01", "sl_source": "SLSB 2021",
         "category": "metal", "note": ""},
        {"parameter": "Fluoride", "unit": "mg/L", "who_health_gv": "1.5",
         "who_aesthetic": "", "sl_standard": "1.5", "sl_source": "SLSB 2021",
         "category": "inorganic", "note": ""},
        {"parameter": "Nitrate (as NO3)", "unit": "mg/L", "who_health_gv": "50",
         "who_aesthetic": "", "sl_standard": "50", "sl_source": "SLSB 2021",
         "category": "inorganic", "note": ""},
        {"parameter": "Iron", "unit": "mg/L", "who_health_gv": "",
         "who_aesthetic": "0.3", "sl_standard": "0.3", "sl_source": "SLSB 2021",
         "category": "metal", "note": ""},
    ]
    _tables = {"confirmed_national": _confirmed}
    out["verdicts"] = {}
    for name, sample in _cases.items():
        standards = None
        if name in _tables:
            standards = Path(tempfile.mkdtemp()) / "standards.csv"
            with open(standards, "w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(_tables[name][0]))
                writer.writeheader()
                writer.writerows(_tables[name])
        a = assess_sample(sample, standards_path=standards)
        out["verdicts"][name] = {
            "state": a.verdict_state,
            "statuses": [r.status for r in a.rows],
            "reasons": [r.reason for r in a.rows],
            "converted": [clean(r.value_in_guideline_unit) for r in a.rows],
            "uncertainties": list(a.uncertainties),
            "missing_essential": list(a.missing_essential),
            "verdict": a.verdict,
            "flags": [[f.level, f.code, f.message] for f in a.flags],
            # the remark, the table cell a bound prints as, and whether the
            # national value was provisional, row by row; and the report's
            # recommendations, which the two engines used to word apart
            "remarks": [r.remark for r in a.rows],
            "values": [unquantified_text(r) for r in a.rows],
            "provisional": [r.sl_provisional for r in a.rows],
            "recommendations": quality_recommendations(a),
        }

    # What the laboratory sheet reader makes of a qualified result cell: a
    # unit or a label in the cell, a filled detection-limit column beside a
    # detection, a bound that is not a number.
    _cells = [
        ["E. coli", "CFU/100 mL", "Present", 1], ["E. coli", "CFU/100 mL", "TNTC", 1],
        ["Nitrate (as NO3)", "mg/L", ">50", 0.1], ["Arsenic", "mg/L", "Not analysed", 0.001],
        ["Arsenic", "mg/L", "N/A", 0.001], ["Arsenic", "mg/L", "-", 0.001],
        ["Arsenic", "mg/L", None, 0.001], ["Arsenic", "mg/L", "<0.05", 0.001],
        ["Arsenic", "mg/L", "ND (<0.05)", 0.001], ["Nitrate (as NO3)", "mg/L", ">50 mg/L", None],
        ["Nitrate (as NO3)", "mg/L", "> 50mg/l", None], ["Nitrate (as NO3)", "mg/L", "50+", None],
        ["Nitrate (as NO3)", "mg/L", "above 50", None], ["Nitrate (as NO3)", "mg/L", "≥50", None],
        ["Nitrate (as NO3)", "mg/L", ">=50", None], ["Arsenic", "mg/L", "ND (<0.05 mg/L)", None],
        ["Arsenic", "mg/L", "ND (DL 0.05)", None], ["Arsenic", "mg/L", "ND, <0.05", None],
        ["Arsenic", "mg/L", "ND at 0.05", None], ["E. coli", "CFU/100 mL", "Absent/100 mL", None],
        ["E. coli", "CFU/100 mL", "Present in 100 mL", None],
        ["Total coliforms", "CFU/100 mL", "TNTC (>300)", None],
        ["Arsenic", "mg/L", "ND (see note)", None], ["Lead", "", "<5 ug/L", None],
        ["Lead", "mg/L", "<5 ug/L", None], ["Lead", "mg/L", "<5 NTU", None],
        ["Arsenic", "mg/L", "<LOD", None], ["Arsenic", "mg/L", "<0,05", None],
        ["Arsenic", "mg/L", 0.004, None], ["Arsenic", "mg/L", "0.5 ND", None],
    ]
    _grid = ([["WATER QUALITY LABORATORY RESULTS"], ["Community", "Ref"], [], [],
              ["Parameter", "Unit", "Value", "Detection limit"]] + _cells)
    out["quality_cells"] = [
        [r.parameter, clean(r.value), r.unit, clean(r.detection_limit),
         r.below_detection, clean(r.greater_than), r.greater_than_inclusive,
         r.unreadable]
        for r in quality_from_grid(_grid, "cells.xlsx").results
    ]

    # The facies sentence over every branch it has: a mixed-cation
    # bicarbonate water was said to be one in which sodium had replaced
    # calcium, and a calcium chloride water to have no dominant ion pair.
    _ions = ("Calcium", "Magnesium", "Sodium", "Potassium", "Bicarbonate",
             "Chloride", "Sulfate")
    _mg_per_meq = (20.04, 12.15, 22.99, 39.10, 61.02, 35.45, 48.03)
    _facies_meq = {
        "ca_hco3": (3.0, 1.0, 0.5, 0.1, 3.5, 0.7, 0.4),
        "na_hco3": (0.5, 0.3, 3.0, 0.2, 3.0, 0.6, 0.4),
        "mixed_hco3": (1.6, 1.0, 1.3, 0.1, 2.5, 1.2, 0.3),
        "na_cl": (0.5, 0.5, 4.0, 0.0, 0.7, 4.0, 0.3),
        "ca_cl": (3.0, 0.5, 0.8, 0.1, 1.0, 3.0, 0.4),
        "mixed_cl": (1.5, 1.2, 1.4, 0.0, 0.8, 3.0, 0.4),
        "so4": (2.0, 1.0, 1.0, 0.0, 1.0, 0.5, 2.5),
        "ca_mixed_anion": (3.0, 0.5, 0.5, 0.0, 1.5, 1.3, 1.2),
        "mixed": (1.5, 1.2, 1.3, 0.0, 1.5, 1.3, 1.2),
    }
    out["facies"] = {
        name: facies_of(_wq(*[
            WaterQualityResult(ion, round(meq * mg, 3), "mg/L")
            for ion, meq, mg in zip(_ions, meqs, _mg_per_meq, strict=True)
        ]))["sentence"]
        for name, meqs in _facies_meq.items()
    }

    # The corrosivity sentence names the pH, to as many decimals as it needs
    # to be true: 6.46 printed as "6.5 is below the 6.5 to 8.5 range".
    out["corrosivity_ph"] = {
        str(ph): assess_corrosivity(_wq(
            WaterQualityResult("pH", ph), WaterQualityResult("Calcium", 4.0),
            WaterQualityResult("Alkalinity", 10.0), WaterQualityResult("TDS", 60.0),
        )).verdict
        for ph in (6.46, 8.54, 6.25, 6.4999, 8.46)
    }

    # The Depth Spine's guideline chart over units that are NOT the
    # guideline's own. The bundled sample reports everything in the guideline
    # unit, so a ratio computed from the raw value agrees there and the break
    # only shows on a converted one.
    from groundwater.depth_spine.view import _quality as _spine_quality

    # A pH outside its 6.5 to 8.5 range is past the limit line on either
    # side of it: below the range it used to be drawn on the compliant side.
    out["spine_range_ratio"] = {
        str(ph): next(row["ratio"] for row in _spine_quality(assess_sample(
            _wq(WaterQualityResult("pH", ph))))["rows"] if row["parameter"] == "pH")
        for ph in (5.9, 5.4, 6.5, 7.0, 8.5, 9.5, 0.0, -1.0)
    }

    out["spine_quality"] = [
        {
            "parameter": row["parameter"],
            "value": row["value"],
            "unit": row["unit"],
            "valueInGuidelineUnit": row["valueInGuidelineUnit"],
            "guidelineUnit": row["guidelineUnit"],
            "status": row["status"],
            "evaluable": row["evaluable"],
            "limitMax": row["limitMax"],
            "ratio": row["ratio"],
        }
        for row in _spine_quality(assess_sample(_wq(
            WaterQualityResult("Arsenic", 5.0, "ug/L"),
            WaterQualityResult("Electrical conductivity", 3.0, "mS/cm"),
            WaterQualityResult("Nitrate (as NO3)", 0.1, "g/L"),
            WaterQualityResult("Iron", 0.1, "wibbles"),
            WaterQualityResult("E. coli", 0.0, "CFU/100 mL"),
        )))["rows"]
    ]

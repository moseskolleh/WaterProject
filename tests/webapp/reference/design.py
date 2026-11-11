"""Designs and drilling logs the review found read or designed wrongly, and
the rising main at design time: the "design_cases", "drilling_cases",
"gate_logs" and "rising_main" entries of ``reference.json``.

The cases carry their own inputs, so ``parity.mjs`` runs each spec through
the browser's engine and the two are held to the same screens, sentences,
flags and bills.
"""

from __future__ import annotations

from groundwater.costing import inputs_from_design
from groundwater.design import design_borehole
from groundwater.models import SiteMetadata, WaterQualityResult, WaterQualitySample
from groundwater.quality import assess_sample

from .common import clean, flags


# ------------------------------------------- designs and logs the review read

# Logs the borehole-design review found read or designed wrongly: a named
# zone the fracture reader missed, a pump intake lifted above the level the
# test reached, a grout past the sump, screens clipped or trimmed out of
# their basis, and an as-built record rewritten. The browser reads each
# spec from reference.json and runs it through its own engine, so the two
# are held to the same screens, sentences and flags on the same input.
_TIMBO_ROWS = [
    [0, 10, "Lateritic topsoil"], [10, 20, "Clayey saprolite"],
    [20, 45, "Light colour granite"], [45, 50, "Light colour granite, fracture zone 49-52 m"],
    [50, 70, "Light colour granite"],
]
DESIGN_CASES = [
    # every range a fracture phrase names, in the wordings drillers use
    {"total": 60, "swl": 5, "intervals": [
        [0, 10, "Laterite"], [10, 30, "Granite"],
        [30, 35, "Granite, fractures at 30-31 m and 33-34 m"],
        [35, 45, "Granite, fracture zone between 40 and 42 m"],
        [45, 50, "Granite, fracture zone 46—48 metres"],
        [50, 55, "Granite, fractures at 51 and 53 m"], [55, 60, "Granite"]]},
    # a pump intake in a bottom screen stays below the test's floor
    {"total": 70, "grout": 20, "swl": 9.44, "pump": 52, "floor": 45.26,
     "screens": [[40, 68]], "intervals": _TIMBO_ROWS},
    {"total": 70, "grout": 20, "swl": 9.44, "pump": 52, "floor": 45.26,
     "screens": [[47, 68]], "intervals": _TIMBO_ROWS},
    {"total": 70, "grout": 20, "swl": 9.44, "pump": 52,
     "screens": [[40, 68]], "intervals": _TIMBO_ROWS},
    # a grout past the sump, and a zone the grout covers
    {"total": 60, "grout": 70, "swl": 5, "intervals": [
        [0, 10, "Laterite"], [10, 45, "Granite"],
        [45, 50, "Granite, fracture zone 49-52 m"], [50, 60, "Granite"]]},
    {"total": 60, "grout": 55, "swl": 5, "intervals": [
        [0, 10, "Laterite"], [10, 45, "Granite"],
        [45, 50, "Granite, fracture zone 49-52 m"], [50, 60, "Granite"]]},
    # zones in the grout, in the sump and below the hole
    {"total": 60, "grout": 20, "swl": 5, "intervals": [
        [0, 10, "Laterite"], [10, 20, "Granite, fracture zone 16-18 m"],
        [20, 50, "Granite"], [50, 55, "Granite, fracture zone 49-52 m"],
        [55, 60, "Granite, fracture zone 59-62 m"]]},
    {"total": 60, "swl": 5, "intervals": [
        [0, 10, "Laterite"], [10, 55, "Granite"],
        [55, 60, "Granite, fracture zone 58-62 m"]]},
    # a strike trimmed away with the shallowest screen
    {"total": 40, "swl": 2, "strikes": [9], "intervals": [
        [0, 15, "Granite"], [15, 40, "Granite, fractured"]]},
    # an as-built record that runs into the sump and inside the grout
    {"total": 60, "grout": 20, "swl": 5, "installed": [[15, 25], [48, 54], [54, 60]],
     "intervals": [[0, 10, "Laterite"], [10, 60, "Granite"]],
     "rules": {"borehole_diameter_in": 8.0, "casing_diameter_in": 4.0}},
    # the gravel pack above the top screen: a fracture at the foot of the
    # grout, a zone in the pack's room, a seal at the rule's 6 m over a
    # shallow fracture, a hole with no room for a screen below seal and pack,
    # and analyst screens the seal holds the pack below, level with and short
    # of; the 19 mm annulus of the default hole keeps the seal alone
    {"total": 60, "grout": 20, "swl": 5,
     "rules": {"borehole_diameter_in": 10.0, "casing_diameter_in": 4.0},
     "intervals": [[0, 10, "Laterite"], [10, 20, "Granite"], [20, 26, "Granite, fractured"],
                   [26, 60, "Granite"]]},
    {"total": 60, "grout": 20, "swl": 5,
     "intervals": [[0, 10, "Laterite"], [10, 20, "Granite"], [20, 26, "Granite, fractured"],
                   [26, 60, "Granite"]]},
    {"total": 60, "grout": 20, "swl": 5,
     "rules": {"borehole_diameter_in": 10.0, "casing_diameter_in": 4.0},
     "intervals": [[0, 10, "Laterite"], [10, 45, "Granite, fracture zone 20-21 m"],
                   [45, 60, "Granite"]]},
    {"total": 30, "swl": 2, "rules": {"borehole_diameter_in": 10.0, "casing_diameter_in": 4.0},
     "intervals": [[0, 7, "Laterite"], [7, 12, "Granite, fractured, water bearing"],
                   [12, 30, "Granite"]]},
    {"total": 24, "grout": 20, "swl": 5,
     "rules": {"borehole_diameter_in": 10.0, "casing_diameter_in": 4.0},
     "intervals": [[0, 24, "Granite"]]},
    {"total": 60, "grout": 20, "swl": 5, "screens": [[15, 25]],
     "rules": {"borehole_diameter_in": 10.0, "casing_diameter_in": 4.0},
     "intervals": [[0, 60, "Granite"]]},
    {"total": 60, "grout": 20, "swl": 5, "screens": [[20, 30]],
     "rules": {"borehole_diameter_in": 10.0, "casing_diameter_in": 4.0},
     "intervals": [[0, 60, "Granite"]]},
    {"total": 60, "grout": 20, "swl": 5, "screens": [[21, 30]],
     "rules": {"borehole_diameter_in": 8.0, "casing_diameter_in": 4.0},
     "intervals": [[0, 60, "Granite"]]},
    # a screen exactly the pack's height under a seal that is not a round
    # number: 17.4 - 2 is 15.399999999999999, under the 15.4 m seal, and
    # 8.3 - 1 is 7.300000000000001, over the 7.3 m one
    {"total": 60, "grout": 15.4, "swl": 5, "screens": [[17.4, 40]],
     "rules": {"borehole_diameter_in": 10.0, "casing_diameter_in": 4.0},
     "intervals": [[0, 60, "Granite"]]},
    {"total": 60, "grout": 7.3, "swl": 5, "screens": [[8.3, 40]],
     "rules": {"borehole_diameter_in": 10.0, "casing_diameter_in": 4.0,
               "gravel_pack_above_top_screen_m": 1.0},
     "intervals": [[0, 60, "Granite"]]},
]


def _case_log(spec):
    from groundwater.models import DrillingLog, LithologyInterval, SiteMetadata

    return DrillingLog(
        site=SiteMetadata(community="Case"), total_depth_m=spec["total"],
        drilling_method="DTH",
        intervals=[LithologyInterval(t, b, d) for t, b, d in spec["intervals"]],
        water_strikes_m=list(spec.get("strikes", [])),
        grouting_depth_m=spec.get("grout"),
        installed_screens_m=[tuple(s) for s in spec.get("installed", [])],
    )


def design_case(spec) -> dict:
    from groundwater.config import DesignRules
    from groundwater.reporting.handover import HandoverReportInputs, default_works

    log = _case_log(spec)
    design = design_borehole(
        log=log, static_water_level_m=spec.get("swl"), pump_intake_m=spec.get("pump"),
        pump_intake_floor_m=spec.get("floor"), rules=DesignRules(**spec.get("rules", {})),
        screens_m=[tuple(s) for s in spec["screens"]] if spec.get("screens") else None,
    )
    return {
        "spec": spec,
        "rows": [list(r) for r in design.summary_rows()],
        "basis": list(design.design_basis),
        "flags": flags(design.flags),
        "pump": clean(design.pump_intake_m),
        "works": default_works(HandoverReportInputs(site=log.site, log=log, design=design)),
    }


# Drilling log sheets as grids: the header block, the table header, rows
# and the notes under them.
def _sheet(header, rows, grout=6, notes=()):
    grid = [["BOREHOLE DRILLING LOG", None, None, None, None, None, None],
            ["Community", "Case", None, "Client", "X", None, None],
            ["Drilling method", "DTH", None, "Total depth (m)", 60, None, None],
            ["Grouting depth (m)", grout, None, "Drill rig", None, None, None],
            header]
    return grid + [list(r) for r in rows] + [[n, None, None, None, None, None, None]
                                             for n in notes]


_TABLE = ["Depth interval (m)", "From time", "To time", "Penetration rate (m/min)",
          "Sample / lithology description", "Drilling diameter (in)",
          "Water strike depth (m)"]
_ROWS = [["0-10", "", "", 1, "Topsoil and laterite", 6.5, None],
         ["10-30", "", "", 0.5, "Weathered granite", 6.5, None],
         ["30-60", "", "", 0.4, "Granite, fractured", 6.5, None]]
DRILLING_CASES = [
    # numbered strikes and a water level written beside a strike
    _sheet(_TABLE, _ROWS, notes=["Water strike 1: 18 m, water strike 2: 42 m",
                                 "Water strike at 20 m; rest water level 4.5 m"]),
    # strike cells naming a strike by number, a level and a time
    _sheet(_TABLE, [["0-10", "", "", 1, "Topsoil", 6.5, "Strike 1: 8 m"],
                    ["10-30", "", "", 0.5, "Weathered granite", 6.5, "SWL 4.5"],
                    ["30-60", "", "", 0.4, "Granite, fractured", 6.5, "14:30"]]),
    # the units a column header names, fractions of an inch, and a bare
    # millimetre size under an inch header
    _sheet(["Depth interval (m)", "From time", "To time", "Penetration rate (min/m)",
            "Sample / lithology description", "Bit diameter (mm)", "Water strike depth (m)"],
           [["0-10", "", "", 1, "Topsoil", 254, None],
            ["10-30", "", "", 2, "Weathered granite", "165", None],
            ["30-60", "", "", 4, "Granite, fractured", '8½"', 35]]),
    _sheet(_TABLE, [["0-10", "", "", 1, "Topsoil", '8-1/2"', None],
                    ["10-30", "", "", 0.5, "Weathered granite", "6½", None],
                    ["30-60", "", "", 0.4, "Granite, fractured", 165, None]]),
    # depth intervals written with their unit, and one that cannot be read
    _sheet(_TABLE, [["0m-10m", "", "", 1, "Topsoil", 6.5, None],
                    ["10 m - 30 m", "", "", 0.5, "Weathered granite, fractured", 6.5, 14],
                    ["30-60 metres", "", "", 0.4, "Granite", 6.5, None],
                    ["60 -", "", "", 0.4, "Granite", 6.5, None]]),
    # a grout written as the range it covers
    _sheet(_TABLE, _ROWS, grout="0-20"),
    # A log in feet: the headers, the cells, the total depth, a strike cell, a
    # strike note and rates per foot all say so, and are converted.
    [["Total depth (ft):", "150 ft"],
     ["Depth interval (ft)", "Sample / lithology description",
      "Penetration rate (min/ft)", "Water strike depth (ft)"],
     ["0-20 ft", "Laterite", "2", ""],
     ["20-60 ft", "Weathered granite", "4 min/ft", "45 ft"],
     ["60-150 ft", "Fresh granite", "1.5 ft/min", ""],
     ["Water strike at 90 ft", "", "", ""]],
    # every unit the sheet names is feet, so a bare depth is feet too; the
    # grout and the screens in feet, the screens with their unit on each
    [["Grouting depth:", "0-20 ft"], ["Screens installed:", "80 ft - 110 ft; 120-130 ft"],
     ["Depth interval", "Lithology description", "Penetration rate"],
     ["0-10", "Laterite", "1.5 ft/min"], ["10-140", "Granite", "4 min/ft"],
     ["Water strike at 30", "", ""], ["Water strike at 95'", "", ""]],
    # a header naming both units, and a sheet giving depths in both: a bare
    # depth there is refused, never read as metres
    [["Depth interval (m/ft)", "Lithology description"],
     ["0-10", "Laterite"], ["10-40 ft", "Granite"], ["40 ft-50 m", "Granite"]],
    [["Total depth:", "150"], ["Grouting depth:", "6"],
     ["Depth interval", "Lithology description", "Water strike"],
     ["0-20 ft", "Laterite", ""], ["20-45 m", "Granite", "12"],
     ["Water strike at 14", "", ""]],
    # a template sheet with one strike typed in feet
    _sheet(_TABLE, [["0-10", "", "", 1, "Topsoil", 6.5, None],
                    ["10-30", "", "", 0.5, "Weathered granite", 6.5, "45 ft"],
                    ["30-60", "", "", 0.4, "Granite, fractured", 6.5, "18"]]),
    # decimal commas in the interval column, and a lens inside a longer row
    _sheet(_TABLE, [["0-12,5", "", "", 1, "Topsoil", 6.5, None],
                    ["12,5-30", "", "", 0.5, "Weathered granite", 6.5, None],
                    ["30-60", "", "", 0.4, "Granite", 6.5, None]]),
    _sheet(_TABLE, [["0-30", "", "", 1, "Weathered granite", 6.5, None],
                    ["5-10", "", "", 1, "Clay lens", 6.5, None],
                    ["30-45", "", "", 0.4, "Granite", 6.5, None],
                    ["50-60", "", "", 0.4, "Granite", 6.5, None]]),
    [["Depth interval", "Lithology description"],
     ["0-12", "Laterite and saprolite"], ["12-45", "Granite, fractured at 30-32"],
     ["30-32", "Fracture zone, water"]],
]


# The two logs the readiness cases add: one in feet, and one whose rows and
# strikes the reader had to set aside. parity.mjs reads them from the
# reference, so both engines read the same cells.
GATE_FEET_LOG = DRILLING_CASES[6]
GATE_SET_ASIDE_LOG = _sheet(_TABLE, [
    ["0-10", "", "", 1, "Topsoil", 6.5, "75 m"],
    ["10 -", "", "", 0.5, "Weathered granite", 6.5, None],
    ["20-60", "", "", 0.4, "Granite, fractured", 6.5, "1/2 m"]])


def drilling_case(grid) -> dict:
    from groundwater.ingestion.drilling import drilling_from_grid

    log = drilling_from_grid(grid, "case.xlsx")
    return {
        "grid": grid,
        "strikes": clean(log.water_strikes_m),
        "grout": clean(log.grouting_depth_m),
        "total": clean(log.total_depth_m),
        "screens": [[clean(a), clean(b)] for a, b in log.installed_screens_m],
        "intervals": [[clean(iv.top_m), clean(iv.bottom_m), iv.description,
                       clean(iv.penetration_rate_m_per_min), clean(iv.bit_diameter_in)]
                      for iv in log.intervals],
        # every message in full: the gap and depth flags used to print "40.0 m"
        # here and "40 m" in the browser, and were compared by code alone
        "flags": flags(log.flags),
    }


# ------------------------------------- the rising main at design time (7.2)
#
# What the design specifies for the rising main and how often it is
# inspected, from a water quality sample, over every state the water can be
# in (aggressive by the indices, by the pH alone or by both, not aggressive,
# without the indices, no sample) and the rules that name the materials; and
# the bill of quantities that follows from a design, with the rising main
# over the pump intake, taken as long as the hole, unpriced and left out.
# The cases carry their own inputs, so parity.mjs gives the browser exactly
# these.

def _rm_sample(results, sample_id="WQ-7", when="2024-05-01"):
    return {"site": {"community": "Ref"}, "flags": [], "sample_id": sample_id,
            "sample_date": when,
            "results": [{"parameter": n, "value": v, "unit": u} for n, v, u in results]}


def _rm_object(raw):
    return WaterQualitySample(
        site=SiteMetadata(community="Ref"), sample_id=raw["sample_id"],
        sample_date=raw["sample_date"],
        results=[WaterQualityResult(**r) for r in raw["results"]])


_RM_SOFT = [("pH", 5.8, "pH units"), ("Calcium", 6.0, "mg/L"),
            ("Alkalinity", 15.0, "mg/L as CaCO3"), ("TDS", 60.0, "mg/L")]
_RM_HARD = [("pH", 7.8, "pH units"), ("Calcium", 100.0, "mg/L"),
            ("Alkalinity", 250.0, "mg/L as CaCO3"), ("TDS", 500.0, "mg/L")]

RISING_MAIN_SAMPLES = {
    "none": None,
    "soft": _rm_sample(_RM_SOFT),
    "hard": _rm_sample(_RM_HARD),
    # the indices keep it, the pH rule does not
    "acid hard": _rm_sample([("pH", 6.4, "pH units"), ("Calcium", 200.0, "mg/L"),
                             ("Alkalinity", 500.0, "mg/L as CaCO3"), ("TDS", 1500.0, "mg/L")]),
    # on the pH rule's limit, which is not below it
    "limit hard": _rm_sample([("pH", 6.5, "pH units"), ("Calcium", 200.0, "mg/L"),
                              ("Alkalinity", 500.0, "mg/L as CaCO3"),
                              ("TDS", 1500.0, "mg/L")]),
    # a Langelier index that rounds to nought, a Ryznar index on 7.0
    "nought": _rm_sample([("pH", 7.0, "pH units"), ("Calcium", 90.0, "mg/L"),
                          ("Alkalinity", 395.0, "mg/L as CaCO3"), ("TDS", 400.0, "mg/L")]),
    # moderately soft water inside the pH range
    "moderate": _rm_sample([("pH", 7.2, "pH units"), ("Calcium", 20.0, "mg/L"),
                            ("Alkalinity", 60.0, "mg/L as CaCO3"), ("TDS", 150.0, "mg/L")]),
    "scale": _rm_sample([("pH", 8.2, "pH units"), ("Calcium", 120.0, "mg/L"),
                         ("Alkalinity", 300.0, "mg/L as CaCO3"), ("TDS", 600.0, "mg/L")]),
    "ec only": _rm_sample([("pH", 6.8, "pH units"), ("Calcium", 10.0, "mg/L"),
                           ("Alkalinity", 30.0, "mg/L as CaCO3"),
                           ("Electrical conductivity", 150.0, "uS/cm")]),
    "low ph only": _rm_sample([("pH", 6.0, "pH units")]),
    "ph only": _rm_sample([("pH", 7.0, "pH units")]),
    "near the limit": _rm_sample([("pH", 6.46, "pH units")]),
    "no calcium": _rm_sample([("pH", 7.2, "pH units"), ("Calcium", 0.0, "mg/L"),
                              ("Alkalinity", 20.0, "mg/L as CaCO3")]),
    "no ph": _rm_sample([("Calcium", 10.0, "mg/L"), ("Alkalinity", 30.0, "mg/L as CaCO3")]),
    "undated": _rm_sample(_RM_SOFT, when=""),
    "unnamed": _rm_sample(_RM_HARD, sample_id="", when="20th May, 2018"),
    "anonymous": _rm_sample(_RM_SOFT, sample_id=" ", when="\ufeff"),
    "blank ends": _rm_sample(_RM_SOFT, sample_id="\ufeffWQ-7 ", when=" 2024-05-01\x1c"),
}

RISING_MAIN_RULES = {
    "default": {},
    "upvc": {"aggressive_rising_main_material": "uPVC"},
    "same": {"aggressive_rising_main_material": " Galvanised iron "},
    "intervals": {"rising_main_inspection_months": 24,
                  "aggressive_rising_main_inspection_months": 3},
}

_RM_ROWS = [[0, 10, "Laterite"], [10, 30, "Weathered granite"],
            [30, 50, "Granite, fracture zone 36-38 m"], [50, 60, "Granite"]]
RISING_MAIN_BILLS = [
    {"name": "aggressive, over the intake", "sample": "soft", "pump": 34.0},
    {"name": "aggressive, no intake", "sample": "soft"},
    {"name": "not aggressive", "sample": "hard", "pump": 34.0},
    {"name": "no sample", "sample": "none", "pump": 34.0},
    {"name": "uPVC, unpriced", "sample": "soft", "pump": 34.0, "rules": "upvc"},
    {"name": "no handpump", "sample": "soft", "pump": 34.0, "handpumps": 0},
    {"name": "two handpumps", "sample": "acid hard", "pump": 34.0, "handpumps": 2},
    {"name": "no stainless rate", "sample": "soft", "pump": 34.0, "drop": "RSM1"},
    {"name": "screens placed", "sample": "low ph only", "pump": 25.0,
     "screens": [[40, 52]]},
]


def rising_main_reference() -> dict:
    """The rising main at design time (PLAN.md step 7.2): rising_main_choice
    over every sample and rule set above, and the bill each design gives."""
    from groundwater.config import DesignRules
    from groundwater.costing import estimate_borehole_cost, load_rates
    from groundwater.design import rising_main_choice

    def quality(raw, bare):
        if raw is None:
            return None
        return _rm_object(raw) if bare else assess_sample(_rm_object(raw))

    choices = []
    for sample_name, raw in RISING_MAIN_SAMPLES.items():
        for rules_name, rules in RISING_MAIN_RULES.items():
            for bare in (False, True):
                if bare and (raw is None or rules_name != "default"):
                    continue
                choices.append({
                    "name": f"{sample_name}/{rules_name}" + ("/bare" if bare else ""),
                    "sample": raw, "rules": rules, "bare": bare,
                    "expect": rising_main_choice(quality(raw, bare), DesignRules(**rules)),
                })

    bills = []
    for spec in RISING_MAIN_BILLS:
        rules = RISING_MAIN_RULES[spec.get("rules", "default")]
        raw = RISING_MAIN_SAMPLES[spec["sample"]]
        log = _case_log({"total": 60, "intervals": _RM_ROWS})
        design = design_borehole(
            log=log, static_water_level_m=8.0, pump_intake_m=spec.get("pump"),
            rules=DesignRules(**rules),
            screens_m=[tuple(s) for s in spec["screens"]] if spec.get("screens") else None,
            quality=quality(raw, False))
        inputs = inputs_from_design(design, mobilisation_distance_km=50.0)
        inputs.handpumps = spec.get("handpumps", 1)
        rates = [r for r in load_rates() if r.code != spec.get("drop")]
        estimate = estimate_borehole_cost(inputs, rates)
        bills.append({
            "spec": dict(spec, intervals=_RM_ROWS, total=60, rules=rules, raw=raw),
            "expect": {
                "rising_main": design.rising_main,
                "material": inputs.rising_main_material,
                "length": clean(inputs.rising_main_m),
                "boq": clean(estimate.boq_rows()),
                "flags": flags(estimate.flags),
                "assumptions": list(estimate.assumptions),
                "direct": clean(estimate.direct_cost_usd),
            },
        })
    return clean({"choices": choices, "bills": bills})

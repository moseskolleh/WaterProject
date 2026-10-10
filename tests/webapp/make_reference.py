"""Produce the reference values the browser app is checked against.

Runs the Python toolkit over the bundled sample workbooks and writes
``tests/webapp/reference.json``. ``tests/webapp/parity.mjs`` then runs the
same inputs through the JavaScript engine in headless Chromium and
compares the two, so the standalone web app cannot silently drift away
from the package it was ported from.

    python tests/webapp/make_reference.py            # regenerate the file
    python tests/webapp/make_reference.py --check    # verify it, don't rewrite
    node tests/webapp/parity.mjs

The committed file is checked in so ``parity.mjs`` runs without a Python
environment, and ``--check`` is what CI uses to keep it honest.

Producing the file needs the ``extract`` extra (``pip install -e
'.[dev,extract]'``): one of the reference values is what the Python PDF
reader makes of an unruled field sheet, and that reader is pdfplumber
backed. Reading the file needs nothing.

``--check`` compares within a tolerance rather than byte for byte. The
inversion and the Theis fit go through LAPACK, which is not bit
reproducible across BLAS builds: the same input gives 1.4021310045105808
on one machine and 1.4021310045105801 on another. Those last digits carry
no information about the toolkit, so requiring them to match would make CI
fail on a runner upgrade while a genuine change of a millimetre in a
screen depth slipped through. The tolerance is tight enough that any real
change in behaviour still fails.
"""

from __future__ import annotations

import argparse
import base64
import copy
import csv
import dataclasses
import json
import math
import re
import sys
import tempfile
import zlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from groundwater.depth_spine.view import SpineInputs, build_view
from groundwater.costing import CostingInputs, inputs_from_design
from groundwater.design import design_borehole
from groundwater.hydraulics import analyse_pumping_test, test_type_text
from groundwater.ingestion import (
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.models import (
    DrillingLog,
    LayeredModel,
    SiteMetadata,
    VESSounding,
    WaterQualityResult,
    WaterQualitySample,
)
from groundwater.portfolio import (
    classify_status,
    portfolio_points,
    portfolio_rows,
    portfolio_stats,
    site_detail,
    site_one_pager,
)
from groundwater.geo import geodesic_distance_m, geographic_to_utm
from groundwater.ingestion.waterquality import quality_from_grid
from groundwater.quality import assess_sample
from groundwater.quality.assess import unquantified_text
from groundwater.quality.corrosivity import assess_corrosivity
from groundwater.quality.diagrams import facies_of
from groundwater.reporting.quality import quality_recommendations
from groundwater.units import convert as unit_convert
from groundwater.siting import assess_siting
from groundwater.siting.odds import (
    odds_basis_text,
    odds_header,
    odds_point_text,
    odds_rows,
    odds_short,
    odds_table_caption,
    odds_text,
    programme_offer,
    programme_rate,
    success_odds,
)
from groundwater.supervision.checklists import (
    legacy_item_ids,
    load_checklists,
    migrate_response_keys,
)
from groundwater.config import Config, VESConfig
from groundwater.ingestion.ves import _flag_duplicate_ids, _sounding_or_reason
from groundwater.reporting.geophysical import (
    depth_of_investigation_text,
    models_tried_text,
    poorly_resolved_text,
)
from groundwater.siting import ranking_tie, suitability_verdict
from groundwater.ves.interpret import (
    drilling_depth_text,
    drilling_preference_table,
    interpret_model,
)
from groundwater.ves.inversion import invert_sounding
from groundwater.ves.model_range import (
    Stream,
    latin_hypercube,
    model_range_caption,
    model_range_rows,
    model_range_table_caption,
    model_range_text,
    sample_model_range,
)

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "examples" / "data"
OUT = Path(__file__).resolve().parent / "reference.json"


def clean(value):
    """JSON-safe: NaN becomes null, numpy scalars become plain floats."""
    # bool before the numeric branches: bool is a subclass of int, and a
    # stabilised flag written out as 0 compares unequal to the browser's false.
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.ndarray):
        return [clean(v) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    # Dicts have to recurse too. Without this a mapping passed through here
    # came back untouched, so a tuple inside one stayed a tuple - identical
    # in the written JSON, but --check compares the fresh value against the
    # parsed file, and ("a", "b") != ["a", "b"]. That reads as 107 places
    # where the browser disagrees with the toolkit when nothing disagrees
    # at all, and a numpy scalar in the same position would survive too.
    if isinstance(value, dict):
        return {key: clean(v) for key, v in value.items()}
    return value


def site_dict(site):
    return {
        "client": site.client, "project": site.project,
        "community": site.community, "chiefdom": site.chiefdom,
        "district": site.district, "project_ref": site.project_ref,
        "easting": clean(site.easting), "northing": clean(site.northing),
        "elevation_m": clean(site.elevation_m), "supervisor": site.supervisor,
        "contractor": site.contractor,
    }


def flags(items):
    return [[f.level, f.code, f.message] for f in items]

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
]


def drilling_case(grid) -> dict:
    from groundwater.ingestion.drilling import drilling_from_grid

    log = drilling_from_grid(grid, "case.xlsx")
    return {
        "grid": grid,
        "strikes": clean(log.water_strikes_m),
        "grout": clean(log.grouting_depth_m),
        "intervals": [[clean(iv.top_m), clean(iv.bottom_m), iv.description,
                       clean(iv.penetration_rate_m_per_min), clean(iv.bit_diameter_in)]
                      for iv in log.intervals],
        # every message in full: the gap and depth flags used to print "40.0 m"
        # here and "40 m" in the browser, and were compared by code alone
        "flags": flags(log.flags),
    }


# The interpretation and report prose over cases the Rokel pair never
# reaches: a zone whose modelled base lies below the depth of investigation,
# one wholly below it, a margin cut back to it, a last reading the inversion
# dropped, poorly resolved boundaries, a near-tie, an exact tie and two
# sheets carrying one sounding number. parity.mjs builds the same cases.
VES_CASE_SPACINGS = [1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 80.0]
VES_CASES = [
    # name, rho, h, err, h_factor, ab2, rho_app
    ("zone past doi", [1000, 100, 5000], [5, 60], 8.0, None, None, None),
    ("zone below doi", [1000, 1500, 100, 5000], [10, 40, 20], 6.0, None,
     [1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 60.0], None),
    ("margin past doi", [1000, 100, 5000], [5, 33], 5.0, None, None, None),
    ("last reading dropped", [1000, 100], [8], 5.0, None, None,
     [300.0, 250.0, 200.0, 150.0, 120.0, 110.0, 0.0]),
    ("poorly resolved", [1100, 1600, 47], [1.0, 7.0], 13.3, [3.7, 1.4], None, None),
    ("two poorly resolved", [1100, 1600, 300, 47], [1.0, 2.0, 7.0], 5.0,
     [3.7, 2.5, 1.1], None, None),
    ("thin resistive at 2.5", [1000, 5000, 100], [2.5, 3], 5.0, None, None, None),
]


def _case_interp(sid, rho, h, err=None, h_factor=None, ab2=None, rho_app=None):
    ab2 = ab2 or VES_CASE_SPACINGS
    model = LayeredModel(rho, h, fit_error_percent=err, sounding_id=sid)
    if h_factor is not None:
        model.h_uncertainty_factor = np.array(h_factor, dtype=float)
    sounding = VESSounding(SiteMetadata(), sid, np.array(ab2), np.full(len(ab2), np.nan),
                           np.array(rho_app or [100.0] * len(ab2)))
    return interpret_model(sounding, model)


def _ves_sheet(number, array, header, rows):
    return ([["VES FIELD DATA", None, None, None],
             ["Client", "Ref Client", "Community", "Refville"],
             ["Project", "Geophysical Survey", "Sounding Number", number],
             ["District", "Bo", "Date", "1 Jan 2020"],
             ["Array", array, "Instrument", "ABEM"],
             [None, None, None, None],
             header]
            + [[k + 1] + list(r) for k, r in enumerate(rows)])


VES_SHEETS = [
    # a Schlumberger sheet with only its array field changed to "Wenner"
    ("W", _ves_sheet("W 1", "Wenner", ["No.", "AB/2 (m)", "MN (m)",
                                        "Apparent Resistivity (ohm-m)"],
                     [[1.5, 1.0, 300.0], [3.0, 1.0, 280.0], [6.0, 1.0, 200.0],
                      [6.0, 4.0, 190.0], [15.0, 4.0, 120.0], [30.0, 4.0, 90.0]])),
    # three readings at one AB/2, the third the one out
    ("S3", _ves_sheet("S 3", "Schlumberger", ["No.", "AB/2 (m)", "MN (m)",
                                             "Apparent Resistivity (ohm-m)"],
                      [[10.0, 1.0, 400.0], [20.0, 1.0, 250.0], [40.0, 1.0, 150.0],
                       [40.0, 4.0, 148.0], [40.0, 10.0, 78.0], [60.0, 10.0, 60.0]])),
    # a copied sheet whose Sounding Number was not changed
    ("S3 copy", _ves_sheet("S 3", "Schlumberger", ["No.", "AB/2 (m)", "MN (m)",
                                                  "Apparent Resistivity (ohm-m)"],
                           [[10.0, 1.0, 410.0], [20.0, 1.0, 260.0], [40.0, 1.0, 140.0],
                            [60.0, 10.0, 70.0]])),
]


def _trial_case(trials, chosen_rho, chosen_h, err):
    return SimpleNamespace(trials=trials, fit_error_percent=err,
                           model=LayeredModel(chosen_rho, chosen_h))


MODELS_TRIED_CASES = [
    _trial_case([(2, 4.2), (3, 0.01)], [300, 100, 150], [3, 30], 0.01),
    _trial_case([(2, 8.0), (3, 3.5), (4, 2.0)], [300, 100, 150], [3, 30], 3.5),
    _trial_case([(2, 15.4), (3, 8.0)], [300, 100, 150], [3, 30], 8.0),
    _trial_case([(2, 15.4), (3, 13.3), (4, 13.1)], [300, 100, 150], [3, 30], 13.3),
]


def ves_text(rokel_inversions, rokel_interps) -> dict:
    cases = {}
    for name, rho, h, err, h_factor, ab2, rho_app in VES_CASES:
        i = _case_interp(name, rho, h, err, h_factor, ab2, rho_app)
        suit = assess_siting([i])[0]
        cases[name] = {
            "water_zones": [[clean(t), clean(b)] for t, b in i.water_zones],
            "depth_to_basement_m": clean(i.depth_to_basement_m),
            "investigation_depth_m": clean(i.investigation_depth_m),
            "max_drilling_depth_m": clean(i.max_drilling_depth_m),
            "basement_not_resolved": i.basement_not_resolved,
            "drilling_depth_capped": i.drilling_depth_capped,
            "drilling_depth_text": drilling_depth_text(i),
            "flags": flags(i.flags),
            "narrative": i.narrative,
            "suitability": clean(suit.suitability),
            "rationale": suit.rationale,
        }

    def ranking(interps):
        suit = assess_siting(interps)
        return {
            "tie": ranking_tie(suit),
            "verdict": suitability_verdict(suit),
            "preference": [[r["VES Point"], r["Ranking"], r["Possible Water Zones (m)"]]
                           for r in drilling_preference_table(interps)],
        }

    near = [_case_interp("VES 1", [1000, 100, 5000], [5, 20], 9.0),
            _case_interp("VES 2", [1000, 100, 5000], [5, 22], 9.0)]
    equal = [_case_interp("VES 2", [1000, 100, 5000], [5, 20], 9.0),
             _case_interp("VES 1", [1000, 100, 5000], [5, 20], 9.0)]
    clear = [_case_interp("VES 1", [300, 1500], [30], 5.0),
             _case_interp("VES 2", [1000, 100, 5000], [5, 20], 5.0)]
    # the one with no water zone first, so a weight looked up by the shared
    # id would rank it with the other's score
    same_id = [_case_interp("VES 1", [300, 1500], [30], 5.0),
               _case_interp("VES 1", [1000, 100, 5000], [5, 20], 5.0)]

    grids = []
    for title, grid in VES_SHEETS:
        sounding, _ = _sounding_or_reason(grid, source="x.xlsx", sheet_name=title)
        grids.append((title, sounding))
    _flag_duplicate_ids([s for _, s in grids], [t for t, _ in grids])

    return {
        "cases": cases,
        "near_tie": ranking(near),
        "equal": ranking(equal),
        "clear": ranking(clear),
        "same_id": ranking(same_id),
        "rokel_verdict": suitability_verdict(assess_siting(rokel_interps)),
        "models_tried": [models_tried_text(inv) for inv in rokel_inversions]
        + [models_tried_text(case) for case in MODELS_TRIED_CASES],
        "poorly_resolved": [poorly_resolved_text(inv.model) for inv in rokel_inversions],
        "doi_text": [
            depth_of_investigation_text("schlumberger", 80.0, 40.0),
            depth_of_investigation_text("wenner", 60.0, 30.0),
            depth_of_investigation_text(
                "wenner", 60.0, 24.0, VESConfig(depth_of_investigation_factor=0.4)),
        ],
        "sheets": [[s.sounding_id, s.array_type, flags(s.flags)] for _, s in grids],
    }


# ------------------------------------------- the range of models (step 3.1)
#
# The generator's words, the step it draws and a Latin hypercube, which the
# two engines compute to the bit; a short run of the sampler on each Rokel
# sounding, compared closely (parity.mjs says how closely, and why not to
# the bit); and a run at the default settings, whose percentiles are
# compared within a looser tolerance, since over thousands of steps one
# accept decision taken differently on a last-bit difference would send the
# two chains different ways.

RANGE_SHORT = {"samples": 200, "burn_in": 100, "starts": 4, "chains": 2}


def _range_soundings() -> list:
    """Two soundings the Rokel pair does not cover, as readings both engines
    read: basement within reach under a weathered zone (the sentences with
    a band), and a Wenner sheet that reads one spacing twice."""
    from groundwater.models import SiteMetadata, VESSounding
    from groundwater.ves.forward import forward_schlumberger, forward_wenner

    out = []
    ab2 = np.array([1, 1.5, 2, 3, 4, 6, 8, 10, 15, 20, 30, 40, 60, 80, 100], dtype=float)
    noise = np.exp(0.03 * np.sin(1.7 * np.arange(len(ab2))))
    rho = forward_schlumberger((np.array([300.0, 60.0, 5000.0]), np.array([2.0, 15.0])), ab2)
    out.append(VESSounding(site=SiteMetadata(), sounding_id="basement in reach",
                           ab2=ab2, mn=np.full(len(ab2), np.nan), rho_app=rho * noise))
    a = np.array([1, 2, 3, 4, 6, 8, 8, 12, 16, 24, 32, 48, 64], dtype=float)
    rho = forward_wenner((np.array([200.0, 40.0, 4000.0]), np.array([2.0, 10.0])), a)
    rho = rho * np.exp(0.03 * np.sin(1.7 * np.arange(len(a))))
    rho[6] *= 1.3  # the repeat at 8 m disagrees
    out.append(VESSounding(site=SiteMetadata(), sounding_id="wenner repeat", ab2=a,
                           mn=np.full(len(a), np.nan), rho_app=rho, array_type="wenner"))
    return out


def _range_dict(r, text: bool = True, fan: bool = True) -> dict:
    out = clean(dataclasses.asdict(r))
    if text:
        out["text"] = model_range_text(r)
        out["caption"] = model_range_caption(r)
    if not fan:
        for key in ("fan", "fan_curves", "start_points"):
            out.pop(key)
    return out


def _range_text_cases() -> list:
    """Every branch of the sentences, on ranges built by hand: the plan's
    own example, basement always, rarely and never in reach, a share under
    1 percent, a dry profile, a capped depth, a better fit found, overlaps
    and widened errors, and basement in exactly the share that quotes it."""
    from groundwater.ves.model_range import Band, ModelRange

    base = dict(
        sounding_id="VES 1", n_layers=3, n_samples=4000, chains=4, starts=8, seed=1,
        base_error_percent=3.0, overlap_spacings=[], error_scale=1.0, acceptance=0.25,
        accepted=[250, 250, 250, 250], investigation_depth_m=50.0,
        basement_m=Band(22.3, 27.0, 34.2), basement_unresolved=0.3,
        weathered_m=Band(12.0, 15.0, 19.6),
        resistivity=[Band(310.4, 452.0, 1234.5), Band(41.25, 60.0, 88.88),
                     Band(2999.5, 5000.0, 12500.0)],
        interface_m=[Band(1.52, 2.0, 2.648), Band(18.05, 22.5, 30.0)],
        drilling_depth_m=35.0, drilling_depth_capped=False,
        chosen_error_percent=4.0, best_error_percent=4.0, ab2=[],
    )
    changes = [
        {}, {"basement_unresolved": 0.0}, {"basement_unresolved": 0.95},
        {"basement_m": None, "basement_unresolved": 1.0}, {"basement_unresolved": 0.002},
        {"basement_unresolved": 0.997}, {"weathered_m": Band(0.0, 0.0, 0.2)},
        {"drilling_depth_m": 50.0, "drilling_depth_capped": True},
        {"best_error_percent": 2.0, "n_layers": 4},
        {"overlap_spacings": [10.0, 40.0], "error_scale": 2.5, "chains": 1},
        {"overlap_spacings": [7.5], "base_error_percent": 2.5, "starts": 0},
        # basement in exactly a tenth of the models, as 400 of 4,000 store it:
        # the band is quoted at the threshold, not lost to a last bit
        {"basement_unresolved": 1.0 - 400 / 4000},
    ]
    out = []
    for change in changes:
        r = ModelRange(**{**base, **change})
        out.append({"range": clean(dataclasses.asdict(r)), "text": model_range_text(r),
                    "caption": model_range_caption(r), "rows": model_range_rows(r),
                    "table_caption": model_range_table_caption(r)})
    return out


# --check holds the range to the tolerances parity.mjs holds the browser to,
# not to CHECK_RTOL. Its chains start from Levenberg-Marquardt fits, which a
# different BLAS build, or OpenBLAS with more threads, rounds differently;
# on a flat equivalence valley that moves a polished start by a few parts in
# a million, and every sample of the chain started there moves with it. One
# thread against four on this machine moved the short runs by 2e-6. Only the
# sampler's runs are loosened: the generator's words, its steps, the Latin
# hypercube and the hand-built sentence cases involve no fit, so they are
# held to CHECK_RTOL like every other entry.
RANGE_RTOL = {".ves_range.default": 2e-2, ".ves_range.short": 1e-4,
              ".ves_range.synthetic": 1e-4,
              # the depth the costing reads off those short runs
              ".cost_range.spreads": 1e-4}


def range_tolerated(path: str, fresh, committed) -> bool:
    """Whether a difference --check found is inside the range's tolerance."""
    for prefix, rtol in RANGE_RTOL.items():
        if path.startswith(prefix + ".") or path.startswith(prefix + "["):
            return (isinstance(fresh, (int, float)) and isinstance(committed, (int, float))
                    and not isinstance(fresh, bool)
                    and math.isclose(fresh, committed, rel_tol=rtol, abs_tol=1e-12))
    return False


# The Papadopulos-Cooper fit's own numbers on a sheet it fits badly sit on a
# valley floor flat to within the Stehfest inversion's rounding, so another
# BLAS build or scipy stops the optimiser a few parts in a hundred thousand
# away (3e-5 relative, Python on the CI runner against this machine). --check
# holds them to the 1e-3 relative parity.mjs holds the browser to; where the
# fit is adopted it is held to CHECK_RTOL, as is everything resting on it.
PC_RTOL = 1e-3
_PC_PATH = re.compile(r"^\.pumping_spread\.cases\.([^.]+)\.pc\[\d+\]$")


def pc_tolerated(path: str, fresh, committed, reference: dict) -> bool:
    """Whether a difference --check found is a badly fitting large-diameter
    fit's own number, inside parity's tolerance for it."""
    match = _PC_PATH.match(path)
    if not match:
        return False
    case = reference.get("pumping_spread", {}).get("cases", {}).get(match.group(1)) or {}
    if case.get("source") == "papadopulos_cooper":
        return False
    return (isinstance(fresh, (int, float)) and isinstance(committed, (int, float))
            and not isinstance(fresh, bool)
            and math.isclose(fresh, committed, rel_tol=PC_RTOL, abs_tol=1e-12))


def ves_range_reference(soundings, inversions) -> dict:
    streams = {}
    for seed, stream in ((1, 0), (1, 1), (20261004, 7), (0, 0), (-1, 3)):
        rng = Stream(seed, stream)
        streams[f"{seed}/{stream}"] = [rng.next_u32() for _ in range(6)]
    rng = Stream(2, 3)
    symmetric = [rng.symmetric() for _ in range(8)]
    lhs = latin_hypercube(Stream(1, 0), 6, [0.0, -1.0, 2.0], [1.0, 3.0, 2.5])
    short = Config()
    for key, value in RANGE_SHORT.items():
        setattr(short.ves_range, key, value)
    synthetic = [{
        "id": s.sounding_id, "array": s.array_type,
        "ab2": clean(s.ab2), "rho": clean(s.rho_app),
        "range": _range_dict(sample_model_range(s, invert_sounding(s), short)),
    } for s in _range_soundings()]
    return {
        "streams": streams,
        "symmetric": symmetric,
        "lhs": lhs,
        "short_settings": RANGE_SHORT,
        "short": [_range_dict(sample_model_range(s, inv, short))
                  for s, inv in zip(soundings, inversions, strict=True)],
        "default": [_range_dict(sample_model_range(s, inv, Config()), text=False, fan=False)
                    for s, inv in zip(soundings, inversions, strict=True)],
        "synthetic": synthetic,
        "text_cases": _range_text_cases(),
    }


# ------------------------------------ the forward model at high contrast
#
# The inversion of a near-uniform sounding with one high reading can walk a
# thin top layer out to 1e5 ohm-m or more. There the forward model is the
# top layer's resistivity plus an integral that cancels nearly all of it, so
# an error in the quadrature's Bessel tables reaches the apparent
# resistivity multiplied by rho1 / rho_a. The browser's former tables, good
# to 5e-9, put the engines 0.1 percent apart there, and the fuzz suite's
# inversions met it only when a draw happened to land on such a sounding.
# This grid holds each forward model the inversion uses to 1e-6 on every
# pull request: two layers, the top 0.2 to 2 m thick at 4 to 200,000 ohm-m,
# over 3.2 to 40 ohm-m.
# The starting models are held to 1e-12 on soundings whose first spacing
# was read twice, where np.interp at the first abscissa reads the second
# reading and the browser's interp used to read the first. interp itself is
# held to np.interp exactly, at its edges and inside the range.

FORWARD_AB2 = [1.0, 1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 25.0, 40.0, 70.0, 100.0]
FORWARD_MN = [0.4] * 4 + [1.0] * 4 + [4.0] * 4
FORWARD_RHO1 = [4.0, 1e2, 1e3, 1e4, 1e5, 2e5]
FORWARD_H1 = [0.2, 0.25, 0.5, 2.0]
FORWARD_RHO2 = [3.2, 5.0, 40.0]

#: inversion_readings of regressions/ves-thin-resistive-top-layer.json and
#: ves-equivalent-models.json: sorted by spacing, a repeat in sheet order
STARTING_MODEL_CASES = [
    ([3.0, 3.0, 4.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 12.0, 15.0, 20.0, 20.0,
      25.0, 25.0, 30.0, 40.0, 50.0, 60.0, 60.0, 70.0, 80.0, 80.0],
     [40.6, 40.0, 12.0, 12.0, 7.3, 6.3, 6.1, 9.7, 6.0, 6.0, 6.1, 5.9, 5.8, 5.8,
      5.9, 5.9, 5.8, 5.9, 5.9, 5.9, 5.9, 6.0, 5.7, 6.0]),
    ([4.0, 4.0, 5.0, 6.0, 6.0, 7.0, 7.0, 8.0, 10.0, 12.0, 12.0, 15.0, 20.0, 25.0,
      30.0, 30.0, 40.0],
     [48.2, 47.9, 22.1, 42.6, 42.1, 41.7, 41.7, 41.4, 40.6, 40.5, 40.7, 40.3, 39.9,
      40.2, 39.9, 40.1, 40.2]),
]


def ves_forward_reference() -> dict:
    """Python's forward models on the contrast grid, and its starting models."""
    from groundwater.ves.forward import (
        forward_schlumberger,
        forward_schlumberger_finite_mn,
        forward_wenner,
    )
    from groundwater.ves.inversion import _starting_models

    ab2, mn = np.array(FORWARD_AB2), np.array(FORWARD_MN)
    models = []
    for rho1 in FORWARD_RHO1:
        for h1 in FORWARD_H1:
            for rho2 in FORWARD_RHO2:
                model = (np.array([rho1, rho2]), np.array([h1]))
                models.append({
                    "rho": [rho1, rho2], "h": [h1],
                    "schlumberger": clean(forward_schlumberger(model, ab2)),
                    "finite_mn": clean(forward_schlumberger_finite_mn(model, ab2, mn)),
                    "wenner": clean(forward_wenner(model, ab2)),
                })
    starts = []
    for readings, rho_app in STARTING_MODEL_CASES:
        for n in (2, 3, 4):
            starts.append({
                "ab2": readings, "rho": rho_app, "n_layers": n,
                "starts": [[clean(rho0), clean(h0)] for rho0, h0 in _starting_models(
                    np.array(readings), np.array(rho_app), n)],
            })
    return {"ab2": FORWARD_AB2, "mn": FORWARD_MN, "models": models,
            "starting_models": starts, "interp": interp_reference()}


#: (xp, fp) for np.interp at its edges: the first abscissa, the last, or one
#: inside read twice, a single point, and every point the same
INTERP_EDGES = [
    ([0.0, 0.0, 1.0], [10.0, 20.0, 30.0]), ([0.0, 1.0, 1.0], [10.0, 20.0, 30.0]),
    ([0.0, 1.0, 1.0, 2.0], [10.0, 20.0, 30.0, 40.0]), ([2.0], [7.0]), ([2.0, 2.0], [7.0, 9.0]),
]


def interp_reference() -> list:
    """np.interp at its edges, NaN included, and across the log readings of
    the starting-model soundings, where only numpy's order of operations,
    the slope first, gives numpy's last bit; parity.mjs holds interp to these
    exactly."""
    probes = [-1.0, 0.0, 0.5, 1.0, 1.5, 2.0, 3.0, math.nan]
    cases = [{"x": clean(probes), "xp": xp, "fp": fp,
              "value": clean(np.interp(probes, xp, fp))} for xp, fp in INTERP_EDGES]
    for readings, rho_app in STARTING_MODEL_CASES:
        xp, fp = np.log(readings), np.log(rho_app)
        x = np.log(np.geomspace(readings[0], readings[-1], 201))
        cases.append({"x": clean(x), "xp": clean(xp), "fp": clean(fp),
                      "value": clean(np.interp(x, xp, fp))})
    return cases


# The Bessel functions and zeros the quadrature tables are built from. The
# forward grid above would miss a zero gone astray: panels that end a little
# off the zeros integrate to nearly the same sum, and only the panel the
# quadrature stops at can move, which shows as a rare knife-edge in a
# generated inversion rather than on a pull request. So the zeros are held to
# jn_zeros, and J0 and J1 to scipy at every half unit on [0, 30], across the
# branches at 5 and 10, and on out to the largest abscissa the tables reach.

BESSEL_X = [0.5 * i for i in range(61)] + [float(x) for x in np.geomspace(31.3, 1.9e5, 25)]
#: 1-based: the first 50, every 100th of the 1200 the tables start with,
#: and on to the 60,000 they can grow to
BESSEL_ZERO_RANKS = (list(range(1, 51)) + list(range(100, 1201, 100))
                     + [2000, 5000, 10000, 20000, 40000, 60000])


def ves_bessel_reference() -> dict:
    """scipy's J0, J1 and their zeros, where the browser's tables use them."""
    from scipy.special import j0, j1, jn_zeros

    x = np.array(BESSEL_X)
    zeros = {order: jn_zeros(order, BESSEL_ZERO_RANKS[-1]) for order in (0, 1)}
    return {
        "x": BESSEL_X, "j0": clean(j0(x)), "j1": clean(j1(x)),
        "zero_ranks": BESSEL_ZERO_RANKS,
        "zeros0": clean(zeros[0][np.array(BESSEL_ZERO_RANKS) - 1]),
        "zeros1": clean(zeros[1][np.array(BESSEL_ZERO_RANKS) - 1]),
    }


# --------------------------------------------------- the chance of success
# PLAN.md step 3.3. Hand-built points cover every band, and ODDS_EDGES puts
# a point exactly on every band edge, where only the comparison decides;
# the Rokel pair is read with the short ranges above, placed by its own
# coordinates on the bundled maps.

def _odds_interp(sid, zones, layers, err):
    """A point as the odds read it: its water zones, its layers (a base of
    None is the half-space, and the last field whether the layer is
    water-bearing) and its misfit."""
    return SimpleNamespace(
        sounding_id=sid, water_zones=[tuple(z) for z in zones],
        layers=[SimpleNamespace(top_m=t, bottom_m=math.inf if b is None else b, rho=r,
                                water_bearing=wet)
                for t, b, r, wet in layers],
        fit_error_percent=err, site_easting=None, site_northing=None)


def _odds_range(basement, unresolved):
    from groundwater.ves.model_range import Band

    return SimpleNamespace(basement_m=None if basement is None else Band(*basement),
                           basement_unresolved=unresolved)


def _odds_dict(o) -> dict:
    out = clean(dataclasses.asdict(o))
    out["text"] = odds_text(o)
    out["point_text"] = odds_point_text(o)
    out["basis_text"] = odds_basis_text(o)
    out["rows"] = odds_rows(o)
    out["short"] = odds_short(o)
    out["caption"] = odds_table_caption(o)
    out["programme_rate"] = programme_rate(o)
    out["programme_offer"] = programme_offer(o)
    return out


def _three_layers(rho, err, zone=(5, 20)):
    """A water-bearing layer of ``rho`` filling ``zone``, dry above and
    basement below."""
    top, base = zone
    return ([list(zone)], [[0, top, 300.0, False], [top, base, rho, True],
                           [base, None, 5000.0, False]], err)


ODDS_POINTS = {
    # 80 ohm-m over basement at 20 m, a good fit
    "productive": _three_layers(80.0, 4.0),
    "clay": ([[3, 12]], [[0, 3, 150.0, False], [3, 12, 12.0, True],
                         [12, None, 4000.0, False]], 7.5),
    "clayey": ([[4, 30]], [[0, 4, 200.0, False], [4, 30, 35.0, True],
                           [30, None, 4000.0, False]], 12.0),
    "resistive": ([[6, 25]], [[0, 6, 900.0, False], [6, 25, 500.0, True],
                              [25, None, 6000.0, False]], 25.0),
    "fresh": ([[2, 40]], [[0, 2, 100.0, False], [2, 40, 1500.0, True]], 3.0),
    "dry": ([], [[0, 3, 900.0, False], [3, None, 8000.0, False]], 4.0),
    "unknown_fit": _three_layers(80.0, None),
    # a zone rounded to whole metres takes in 0.4 m of the basement under
    # it, which the water-zone resistivity leaves out
    "rounded": ([[6, 9]], [[0, 6, 300.0, False], [6, 8.6, 200.0, True],
                           [8.6, None, 5000.0, False]], 3.0),
}

# A point exactly on each band edge, read on B-L: the depth, the basement
# share, the misfit and the resistivity, each with nothing else moving.
ODDS_EDGES = (
    [(f"edge_depth_{d:g}", _three_layers(80.0, 4.0), ((d - 2.0, d, d + 5.0), 0.0))
     for d in (5.0, 15.0, 35.0)]
    + [("edge_share", _three_layers(80.0, 4.0), ((18.0, 22.0, 30.0), 0.1))]
    + [(f"edge_fit_{e:g}", _three_layers(80.0, e), None) for e in (5.0, 10.0, 20.0)]
    + [(f"edge_rho_{r:g}", _three_layers(r, 4.0), None) for r in (20.0, 50.0, 300.0, 800.0)]
)

ODDS_RANGES = {
    "none": None,
    "thin": ((2.0, 4.0, 6.0), 0.0),
    "shallow": ((8.0, 11.0, 16.0), 0.05),
    "favourable": ((18.0, 22.0, 30.0), 0.1 - 1e-12),
    "deep": ((30.0, 45.0, 60.0), 0.4),
    # basement found in under a tenth of the models: no band is quoted
    "not_quoted": ((30.0, 45.0, 60.0), 0.95),
    "never": (None, 1.0),
}

ODDS_GROUND = [
    ["B-L", "pCm"], ["B-L", "Qe"], ["B-L", None], ["I-L", "Pi"], ["I-L", "Mi"],
    ["CSF-L/M", "pCm"], ["U-M/H", "Qe"], ["n/a", "H2O"], ["ZZ", "pCm"],
    [None, None], [None, "pCm"],
]


def odds_reference(rokel_interps, rokel_sites, short_ranges) -> dict:
    from groundwater.siting.odds import (
        beta_quantile, lognormal_share_above, point_latlon, prior_for,
        regularised_beta,
    )

    config = Config()
    wider = Config()
    wider.odds.success_yield_m3_per_h = 3.6
    # a low success yield puts the coastal sands' prior near 1, where the
    # 90th percentile of its Beta bisects to exactly 1
    low = Config()
    low.odds.success_yield_m3_per_h = 0.3
    cases = []

    def case(name, point, spec, code, glg):
        zones, layers, err = point
        r = None if spec is None else _odds_range(*spec)
        o = success_odds(_odds_interp(name, zones, layers, err), r, code, glg, config)
        cases.append({
            "interp": {"sounding_id": name, "water_zones": zones,
                       "layers": [{"top_m": t, "bottom_m": b, "rho": rho,
                                   "water_bearing": wet}
                                  for t, b, rho, wet in layers],
                       "fit_error_percent": err},
            "range": None if r is None else {
                "basement_m": None if r.basement_m is None
                else clean(dataclasses.asdict(r.basement_m)),
                "basement_unresolved": r.basement_unresolved},
            "ground": [code, glg],
            "odds": _odds_dict(o),
        })

    for name, point in ODDS_POINTS.items():
        for rname, spec in ODDS_RANGES.items():
            for code, glg in (["B-L", "pCm"],) if rname != "favourable" else ODDS_GROUND:
                case(name, point, spec, code, glg)
    for name, point, spec in ODDS_EDGES:
        case(name, point, spec, "B-L", "pCm")
    o = success_odds(_odds_interp("wider", *ODDS_POINTS["productive"]),
                     _odds_range(*ODDS_RANGES["favourable"]), "B-L", "pCm", wider)
    low_yield = success_odds(_odds_interp("low_yield", *ODDS_POINTS["productive"]),
                             _odds_range(*ODDS_RANGES["favourable"]), "U-M/H", "Qe", low)
    from groundwater.siting.odds import ground_at

    places = [[8.3759, -13.1024], [8.6, -11.5], [8.47, -13.24], [9.5, -12.0],
              [7.6, -12.5], [5.0, -20.0]]
    # the suitability rows name their point by position: with the second
    # point copied over the first's id and listed first, the leader is the
    # one listed second
    renamed = copy.copy(rokel_interps[1])
    renamed.sounding_id = rokel_interps[0].sounding_id
    ranked_index = [s.index for s in assess_siting([renamed, rokel_interps[0]])]
    rokel = []
    for interp, site, r in zip(rokel_interps, rokel_sites, short_ranges, strict=True):
        latlon = point_latlon(interp, site.utm_zone, site.latlon)
        rokel.append({"latlon": clean(list(latlon)) if latlon else None,
                      "ground": list(ground_at(latlon)),
                      "odds": _odds_dict(success_odds(interp, r, *ground_at(latlon), config))})
    return {
        "lognormal": [[q1, q3, t, lognormal_share_above(q1, q3, t)]
                      for q1, q3, t in ((0.1, 0.5, 1 / 3.6), (0.1, 5.0, 1 / 3.6),
                                        (2.0, 20.0, 1 / 3.6), (0.1, 0.5, 0.05),
                                        (0.1, 0.5, 2.0))],
        "beta": [[a, b, x, regularised_beta(a, b, x), beta_quantile(a, b, x)]
                 for a, b in ((4.28, 5.72), (1.0, 1.0), (0.3, 9.7), (9.9, 0.1), (50.0, 50.0))
                 for x in (0.1, 0.5, 0.9)],
        "priors": [[code, glg, {k: clean(v) for k, v in prior_for(code, glg, 1.0).items()}]
                   for code, glg in ODDS_GROUND],
        "cases": cases,
        "wider": _odds_dict(o),
        "low_yield": {"rate": low.odds.success_yield_m3_per_h,
                      "odds": _odds_dict(low_yield)},
        "ranked_index": ranked_index,
        "ground": [[lat, lon, list(ground_at((lat, lon)))] for lat, lon in places],
        "rokel": rokel,
        "header": odds_header(),
    }

# ------------------------------------------- the cost as a distribution (3.4)
#
# Every number the distribution draws is sums, products, quotients and square
# roots of the range of models' generator, so the two engines agree to the
# bit and parity.mjs compares short runs and default runs exactly. The depth
# is drawn from hand-built quantiles shaped like Rokel A's range rather than
# from the range itself: the range's own short run moves by a few parts in a
# million with the BLAS build (RANGE_RTOL), which would move a drawn depth
# across a whole metre now and then and --check with it. The range's
# quantiles are compared on their own, in the ves_range section.

COST_DEPTH = {"sounding_id": "Rokel-shaped", "step_m": 1.0, "cap_m": 41.0,
              "quantiles_m": [24.0, 25.2, 26.1, 26.9, 27.6, 28.2, 28.9, 29.5, 30.0, 30.6,
                              31.2, 31.9, 32.5, 33.2, 34.0, 34.9, 35.8, 36.9, 38.2, 40.1,
                              44.6]}

COST_CASES = {
    "manual, odds, no range": dict(
        inputs={"total_depth_m": 40.0, "mobilisation_distance_km": 100.0},
        p=0.6, sid="VES 1"),
    "design lengths, depth drawn, VAT": dict(
        inputs={"total_depth_m": 36.0, "casing_m": 27.5, "screen_m": 9.0,
                "gravel_interval_m": 24.0, "overburden_m": 18.0, "cement_bags": 6.0,
                "mobilisation_distance_km": 60.0},
        depth=True, p=0.45, sid="A (1)", pct={"vatPercent": 15.0}),
    "no gravel pack, edited rates, no odds": dict(
        inputs={"total_depth_m": 52.0, "casing_m": 43.5, "screen_m": 9.0,
                "gravel_interval_m": 0.0, "mobilisation_distance_km": 25.0,
                "handpumps": 0, "wq_samples": 2},
        depth=True, edits=[["MOB1", 3.0], ["CAS3", 0.0], ["DRL2", 22.0]],
        pct={"overheadsPercent": 10.0, "marginPercent": 0.0, "contingencyPercent": 0.0}),
    "flat catalogue": dict(
        inputs={"total_depth_m": 48.0, "mobilisation_distance_km": 120.0}, flat=True),
    "one sample": dict(inputs={"total_depth_m": 30.0}, samples=1, p=0.7, sid="B"),
    "long odds, few samples": dict(inputs={"total_depth_m": 30.0}, samples=5, p=0.02,
                                   sid="C"),
}

COST_PROGRAMMES = {
    "ten at 60 percent": dict(
        inputs={"total_depth_m": 40.0, "mobilisation_distance_km": 100.0}, n=10, rate=60.0),
    "21 at 35 percent, depth drawn, VAT": dict(
        inputs={"total_depth_m": 36.0, "casing_m": 27.5, "screen_m": 9.0,
                "gravel_interval_m": 24.0, "mobilisation_distance_km": 80.0},
        n=21, rate=35.0, km=22.0, depth=True, pct={"vatPercent": 15.0}),
    "one, certain, flat": dict(inputs={"total_depth_m": 45.0, "mobilisation_distance_km": 150.0},
                               n=1, rate=100.0, flat=True),
    "500 at 5 percent": dict(inputs={"total_depth_m": 40.0}, n=500, rate=5.0, samples=40),
}

COST_SHORT = 300


def _cost_rates(spec):
    from groundwater.costing import load_rates

    rates = load_rates()
    if spec.get("flat"):
        rates = [dataclasses.replace(r, min_usd=r.unit_cost_usd, max_usd=r.unit_cost_usd)
                 for r in rates]
    edits = dict(spec.get("edits", []))
    return [r.with_likely(edits[r.code]) if r.code in edits else r for r in rates]


def _cost_pct(spec) -> dict:
    names = {"overheadsPercent": "overheads_percent", "marginPercent": "margin_percent",
             "contingencyPercent": "contingency_percent", "vatPercent": "vat_percent"}
    return {names[k]: v for k, v in spec.get("pct", {}).items()}


def _cost_depth(spec):
    from groundwater.costing import DepthSpread

    return DepthSpread(**COST_DEPTH) if spec.get("depth") else None


def cost_range_reference(short_ranges) -> dict:
    from groundwater.costing import CostingInputs, depth_spread, load_rates
    from groundwater.costing.distribution import (
        cost_range_header, cost_range_rows, cost_range_text, failures_table,
        programme_range_rows, programme_range_text, sample_cost, sample_programme_cost,
        triangle_quantile,
    )

    def single(spec, samples):
        d = sample_cost(CostingInputs(**spec["inputs"]), _cost_rates(spec),
                        depth=_cost_depth(spec), success_probability=spec.get("p", 1.0),
                        odds_source=spec.get("sid"), samples=samples, **_cost_pct(spec))
        return {"dist": clean(dataclasses.asdict(d)), "text": cost_range_text(d),
                "rows": cost_range_rows(d)}

    def programme(spec, samples):
        d = sample_programme_cost(
            CostingInputs(**spec["inputs"]), spec["n"], rates=_cost_rates(spec),
            success_rate_percent=spec["rate"], inter_site_distance_km=spec.get("km", 15.0),
            depth=_cost_depth(spec), samples=samples, **_cost_pct(spec))
        return {"dist": clean(dataclasses.asdict(d)), "text": programme_range_text(d),
                "rows": programme_range_rows(d)}

    rng = Stream(5, 9)
    triangles = []
    for lo, mode, hi in ((100.0, 150.0, 300.0), (2.25, 2.5, 4.0), (0.0, 0.0, 1.0),
                         (5.0, 9.0, 9.0), (3.0, 3.0, 3.0)):
        for _ in range(4):
            u = rng.uniform()
            triangles.append([lo, mode, hi, u, triangle_quantile(lo, mode, hi, u)])
    tables = []
    for n, p in ((1, 0.4), (3, 0.3), (10, 0.75), (21, 0.35), (500, 0.05), (4, 1.0)):
        first, running = failures_table(n, p)
        tables.append([n, p, first, len(running), running[-1], running[len(running) // 2]])
    # the depth a range hands the costing, from the range's own short run
    spreads = [clean(dataclasses.asdict(depth_spread(SimpleNamespace(
        sounding_id=r["sounding_id"], investigation_depth_m=r["investigation_depth_m"],
        drilling_depth_quantiles_m=r["drilling_depth_quantiles_m"]), Config())))
        for r in short_ranges]
    edits = []
    for code, value in (["MOB1", 3.0], ["CAS3", 0.0], ["DRL2", 22.0]):
        rate = next(r for r in load_rates() if r.code == code)
        edits.append([code, value, list(rate.with_likely(value).triangle())])
    return {
        "short_samples": COST_SHORT,
        "rates": [[r.code, *r.triangle(), r.spread_group] for r in load_rates()],
        "edits": edits,
        "triangles": triangles,
        "failures": tables,
        "depth": COST_DEPTH,
        "depth_draws": [[u, _cost_depth({"depth": True}).draw(u)]
                        for u in (1e-9, 0.03, 0.25, 0.5, 0.77, 0.95, 0.999, 1 - 1e-9)],
        "spreads": spreads,
        "header": cost_range_header(),
        "cases": {name: dict(spec=spec, short=single(spec, spec.get("samples", COST_SHORT)))
                  for name, spec in COST_CASES.items()},
        "default": {name: single(COST_CASES[name], None)
                    for name in ("manual, odds, no range", "design lengths, depth drawn, VAT")},
        "programmes": {name: dict(spec=spec,
                                  short=programme(spec, spec.get("samples", COST_SHORT)))
                       for name, spec in COST_PROGRAMMES.items()},
        "programme_default": {"ten at 60 percent": programme(
            COST_PROGRAMMES["ten at 60 percent"], None)},
    }


# ------------------------------------- the value of one more measurement (3.5)
#
# Each case feeds both engines the same odds, the dicts the odds section
# above holds, so what is compared is the preposterior analysis alone: the
# even spread's bisection, the readings, the decision and its words. The
# costs are the default cost distributions' own means. The worked example of
# tests/test_measurement.py, the extremes and the cases where nothing can
# change the decision are among them.

def _odds_object(d: dict):
    """What measurement_value reads of a SuccessOdds, from its dict."""
    return SimpleNamespace(**{**d, "evidence": [SimpleNamespace(**e) for e in d["evidence"]]})


def _measurement_dict(v) -> dict:
    from groundwater.siting.measurement import (
        measurement_basis, measurement_decision_header, measurement_decision_rows,
        measurement_reading_rows, measurement_readings_caption, measurement_summary,
        measurement_text,
    )

    out = clean(dataclasses.asdict(v))
    out["summary"] = measurement_summary(v)
    out["text"] = measurement_text(v)
    out["basis"] = measurement_basis(v)
    out["reading_rows"] = measurement_reading_rows(v)
    out["decision_header"] = measurement_decision_header(v)
    out["decision_rows"] = measurement_decision_rows(v)
    out["readings_caption"] = measurement_readings_caption(v)
    return out


def measurement_reference(odds: dict, cost_range: dict) -> dict:
    from groundwater.siting.measurement import (
        _classes, even_spread, measurement_decision_caption, measurement_reading_header,
        measurement_values, preposterior,
    )

    spreads = []
    for kind, sampled in (("sounding", True), ("profiling", False)):
        for _evidence, bands in _classes(kind, sampled):
            for weight in (1.0, 0.8, 0.6, 0.3):
                spreads.append([r ** weight for _names, r in bands])
    spreads += [[2.0, 0.5], [0.5, 2.0, 2.0, 2.0, 2.0, 2.0], [1.0, 0.9, 0.8], [1.0, 1.0],
                [1.2, 1.5], [0.01, 1.0001], [0.9999, 50.0]]
    example = [[[2.0, 2 / 3, 1 / 3], [0.5, 1 / 3, 2 / 3]]]
    prepost = [[p, q, c, d, example, preposterior(p, q, c, d, example)]
               for p, q, c, d in ((0.6, 0.5, 5000.0, 2000.0), (0.4, 0.5, 5000.0, 2000.0),
                                  (0.5, 0.5, 5000.0, 2000.0), (1e-6, 1 - 1e-6, 4000.0, 3000.0),
                                  (1 - 1e-6, 1e-6, 4000.0, 3000.0))]
    prepost.append([0.6, 0.5, 5000.0, 2000.0, [], preposterior(0.6, 0.5, 5000.0, 2000.0, [])])

    dist = cost_range["default"]["manual, odds, no range"]["dist"]
    completed, dry = dist["mean"], dist["dry_mean"]
    cases = odds["cases"]
    surveys = []
    # every tenth point of the odds section (each kind of point, range and
    # ground among them), against the next one and alone
    for i in range(0, len(cases), 10):
        pair = [cases[i]["odds"], cases[(i + 1) % len(cases)]["odds"]]
        surveys.append({"odds": pair, "ranking": [0, 1]})
        surveys.append({"odds": pair[:1], "ranking": [0]})
    # ranked the other way, and three points, the best odds not second
    surveys.append({"odds": [cases[0]["odds"], cases[3]["odds"], cases[6]["odds"]],
                    "ranking": [2, 0, 1]})
    # a prior near 1 on the coastal sands
    surveys.append({"odds": [odds["low_yield"]["odds"]], "ranking": [0]})
    for survey in surveys:
        objects = [_odds_object(o) for o in survey["odds"]]
        survey["values"] = [_measurement_dict(v) for v in
                            measurement_values(objects, survey["ranking"], completed, dry)]
    return {
        "costs": [completed, dry],
        "spreads": [[r, None if (e := even_spread(r)) is None else list(e)] for r in spreads],
        "preposterior": prepost,
        "surveys": surveys,
        "reading_header": measurement_reading_header(),
        "decision_caption": measurement_decision_caption(),
    }


def build() -> dict:
    out: dict = {}

    soundings = read_ves_workbook(DATA / "rokel" / "rokel_ves.xlsx")
    out["ves"] = [
        {
            "id": s.sounding_id, "array": s.array_type,
            "ab2": clean(s.ab2), "mn": clean(s.mn), "rho": clean(s.rho_app),
            "site": site_dict(s.site), "flags": flags(s.flags),
        }
        for s in soundings
    ]

    log = read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    out["drilling"] = {
        "ref": log.borehole_ref, "total": clean(log.total_depth_m),
        "strikes": clean(log.water_strikes_m),
        "intervals": [[clean(i.top_m), clean(i.bottom_m), i.description]
                      for i in log.intervals],
        "site": site_dict(log.site), "flags": flags(log.flags),
    }

    sample = read_quality_workbook(DATA / "dr_timbo" / "dr_timbo_water_quality.xlsx")
    out["quality"] = {
        "id": sample.sample_id, "ref": sample.borehole_ref,
        "lab": sample.laboratory,
        "results": [[r.parameter, clean(r.value), r.unit, r.below_detection,
                     clean(r.detection_limit)] for r in sample.results],
        "flags": flags(sample.flags),
    }

    test = read_pumping_workbook(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    out["pumping"] = {
        "type": test.test_type, "swl": clean(test.static_water_level_m),
        "depth": clean(test.borehole_depth_m), "pump": clean(test.pump_setting_m),
        "steps": [{"n": s.step_number, "q": clean(s.discharge_m3_per_h),
                   "t": clean(s.time_min), "wl": clean(s.water_level_m),
                   "label": s.label} for s in test.steps],
        "rec_t": clean(test.recovery_time_min),
        "rec_wl": clean(test.recovery_level_m),
        "duration": clean(test.pumping_duration_min),
        "flags": flags(test.flags),
    }

    step_test = read_pumping_workbook(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    out["step"] = {
        "type": step_test.test_type, "swl": clean(step_test.static_water_level_m),
        "nsteps": len(step_test.steps),
        "steps": [{"n": s.step_number, "q": clean(s.discharge_m3_per_h),
                   "npoints": len(s.time_min), "tmax": clean(float(s.time_min.max()))}
                  for s in step_test.steps],
        "flags": flags(step_test.flags),
    }

    analysis = analyse_pumping_test(test)
    rec = analysis.yield_recommendation
    out["analysis"] = {
        "T": clean(analysis.transmissivity_m2_per_day),
        "cj": clean(analysis.cooper_jacob.transmissivity_m2_per_day)
              if analysis.cooper_jacob else None,
        "rec": clean(analysis.recovery.transmissivity_m2_per_day)
               if analysis.recovery else None,
        "theis": clean(analysis.theis.transmissivity_m2_per_day)
                 if analysis.theis else None,
        "safe": clean(rec.safe_yield_m3_per_h),
        "low": clean(rec.safe_yield_low_m3_per_h),
        "high": clean(rec.safe_yield_high_m3_per_h),
        "pump_depth": clean(rec.pump_installation_depth_m),
        "range_text": rec.yield_range_text,
        "flags": [[f.level, f.code] for f in analysis.flags],
        # workstream 3: what the yield is worth, and why each method was or
        # was not adopted
        "source": analysis.transmissivity_source,
        "qualifies": analysis.adopted_fit()[2],
        "disqualified": sorted(analysis.disqualified),
        "casing_storage_min": clean(analysis.casing_storage_min),
        "u_check": analysis.cooper_jacob.u_check if analysis.cooper_jacob else None,
        "rec_intercept": clean(analysis.recovery.intercept_m) if analysis.recovery else None,
        "rec_intercept_fraction": clean(analysis.recovery.intercept_fraction)
                                  if analysis.recovery else None,
        "rec_pumping_time": clean(analysis.recovery.pumping_time_min)
                            if analysis.recovery else None,
        "theis_S": clean(analysis.theis.storativity) if analysis.theis else None,
        "confidence": rec.confidence,
        "confidence_reasons": list(rec.confidence_reasons),
        "confidence_text": rec.confidence_text,
        "specific_capacity": clean(rec.specific_capacity_m3hr_per_m),
        "specific_capacity_basis": rec.specific_capacity_basis,
        "pump_depth_basis": rec.pump_depth_basis,
        "deepest_level": clean(rec.deepest_pumping_level_m),
        "basis": rec.basis,
        "type_text": test_type_text(test.test_type),
    }

    # The step test with the discharges an analyst would type in: the first
    # step ends above static and gets no drawdown fit, the recovery is read
    # against an equivalent time, and the two-step Hantush-Bierschenk line
    # says it is exact by construction.
    step_q = read_pumping_workbook(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    for step, q in zip(step_q.steps, (1.5, 2.2, 3.0), strict=True):
        step.discharge_m3_per_h = q
    step_analysis = analyse_pumping_test(step_q)
    step_rec = step_analysis.yield_recommendation
    out["step_analysis"] = {
        "T": clean(step_analysis.transmissivity_m2_per_day),
        "source": step_analysis.transmissivity_source,
        "qualifies": step_analysis.adopted_fit()[2],
        "cj": clean(step_analysis.cooper_jacob.transmissivity_m2_per_day)
              if step_analysis.cooper_jacob else None,
        "theis": clean(step_analysis.theis.transmissivity_m2_per_day)
                 if step_analysis.theis else None,
        "rec": clean(step_analysis.recovery.transmissivity_m2_per_day)
               if step_analysis.recovery else None,
        "rec_pumping_time": clean(step_analysis.recovery.pumping_time_min)
                            if step_analysis.recovery else None,
        "rec_equivalent": step_analysis.recovery.equivalent_time
                          if step_analysis.recovery else None,
        "B": clean(step_analysis.step_test.aquifer_loss_B) if step_analysis.step_test else None,
        "C": clean(step_analysis.step_test.well_loss_C) if step_analysis.step_test else None,
        "two_point": step_analysis.step_test.two_point if step_analysis.step_test else None,
        "safe": clean(step_rec.safe_yield_m3_per_h),
        "pump_depth": clean(step_rec.pump_installation_depth_m),
        "confidence": step_rec.confidence,
        "confidence_reasons": list(step_rec.confidence_reasons),
        "pump_depth_basis": step_rec.pump_depth_basis,
        "specific_capacity_basis": step_rec.specific_capacity_basis,
        "flags": [[f.level, f.code] for f in step_analysis.flags],
        "type_text": test_type_text(step_q.test_type),
        # the sheet's own step numbers, not a count of the steps that fitted
        "step_numbers": [s["step"] for s in step_analysis.step_test.steps]
                        if step_analysis.step_test else None,
    }

    assessed = assess_sample(sample)
    out["assessed"] = {
        "verdict": assessed.verdict,
        "health": [r.parameter for r in assessed.health_exceedances],
        "wqi": clean(assessed.wqi.value) if assessed.wqi else None,
        "corros": assessed.corrosivity.classification,
        # The classification alone let the corrosivity sentences drift: the
        # browser went on saying the pH was "within the acceptability range"
        # for a sample flagged at 5.9 while the class it was checked on still
        # read "Strongly corrosive" on both sides.
        "corros_verdict": assessed.corrosivity.verdict,
        "corros_materials": assessed.corrosivity.materials_note,
        "national": [r.parameter for r in assessed.national_exceedances],
        "ionic": clean(assessed.ionic.error_percent) if assessed.ionic else None,
    }

    design = design_borehole(log=log, static_water_level_m=test.static_water_level_m,
                             pump_intake_m=52.0)
    from groundwater.design import lithology_bands
    out["design"] = {
        "depth": clean(design.total_depth_m),
        "screens": [[clean(s.top_m), clean(s.bottom_m)] for s in design.screens],
        "gravel": clean(list(design.gravel_pack)),
        "screen_len": clean(design.total_screen_length_m),
        # workstream 4: the log's own words decide the design
        "backfill": clean(list(design.backfill)),
        "annular_fill": design.annular_fill,
        "annulus_mm": clean(design.annulus_mm),
        "bore_in": clean(design.borehole_diameter_in),
        "as_built": design.as_built,
        "construction_note": design.construction_note,
        "pump_intake": clean(design.pump_intake_m),
        "basis": list(design.design_basis),
        "flags": [[f.level, f.code] for f in design.flags],
        "summary_rows": [list(r) for r in design.summary_rows()],
        "gravel_interval": clean(inputs_from_design(design).gravel_interval_m),
        "grout": clean(log.grouting_depth_m),
        "installed_screens": [list(map(clean, s)) for s in log.installed_screens_m],
        "bands": [[clean(t), clean(b), c.label] for t, b, c in lithology_bands(log.intervals)],
        # the seal the drawing shows is the seal the BoQ prices
        "seal": clean(list(design.sanitary_seal)),
        "cement_bags": clean(inputs_from_design(design).cement_bags),
    }

    # A manual estimate with its own seal rule: cement follows the seal given.
    _manual, _manual_notes = CostingInputs(
        total_depth_m=60.0, sanitary_seal_m=30.0).resolved()
    out["costing_manual"] = {
        "cement_bags": clean(_manual.cement_bags),
        "seal_note": next(n for n in _manual_notes if "grout seal" in n),
    }

    # The cost summary table a contract is signed on. The browser inlined its
    # own eight rows here with no VAT branch at all, so a VAT-set estimate
    # printed a contract price, then a contingency computed on a VAT-inclusive
    # budget, and no line saying where the difference went.
    from groundwater.costing import estimate_borehole_cost  # noqa: E402

    _cost_inputs, _ = CostingInputs(total_depth_m=60.0).resolved()
    # through clean(): summary_rows returns tuples, and --check compares the
    # fresh value against the parsed file, where a tuple has become a list
    out["cost_summary"] = clean({
        "no_vat": estimate_borehole_cost(_cost_inputs).summary_rows(),
        "vat": estimate_borehole_cost(
            _cost_inputs, vat_percent=15.0).summary_rows(),
    })

    # A real Streamlit project file, produced by the real serializer rather
    # than hand-written. Both apps claim they can read each other's projects,
    # and the browser could not read ANY of them: serialize_project always
    # writes rates_overrides, committee, sources, summary and asset, PyYAML
    # renders an empty one as {} or [] on one line, and the browser's parser
    # refused flow syntax outright. The hand-written fixture that was supposed
    # to guard this carried none of those five keys.
    from groundwater.project_io import deserialize_project, serialize_project  # noqa: E402

    _saved = serialize_project(
        {
            "meta_community": "Kuntoloh",
            "meta_district": "Western Area Rural",
            "project_summary": {
                "community": "Kuntoloh", "district": "Western Area Rural",
                "status": "Completed - dry", "total_depth_m": 52.0,
                "cost_per_meter_usd": 151.0,
            },
        },
        "0.2.0",
    ).decode("utf-8")
    out["streamlit_project_file"] = {
        "yaml": _saved,
        # what Python itself reads back out of those exact bytes
        "summary": deserialize_project(_saved.encode("utf-8"))["summary"],
    }

    # The supervision checklists: both engines must read the same ids out of
    # the CSV, and carry a positional answer onto the same stable id.
    _items = load_checklists()
    out["checklists"] = {
        "ids": [[i.item_id, i.legacy_id, i.checklist, i.section, i.critical,
                 i.photo_required]
                for i in _items],
        "legacy": legacy_item_ids(_items),
        "migrated": migrate_response_keys(
            {"chk_procurement-01": "yes", "rmk_drilling-03": "note",
             "chk_" + _items[10].item_id: "no", "chk_nowhere-99": "na"},
            _items),
    }

    inverted = invert_sounding(soundings[0])
    out["inversion"] = {
        "rho": clean(inverted.model.resistivities),
        "h": clean(inverted.model.thicknesses),
        "err": clean(inverted.fit_error_percent),
    }

    # The Depth Spine payload: the workspace decides nothing on its own, so
    # every figure it draws has to come back identical in the browser.
    spine = build_view(SpineInputs(
        name="Dr Timbo", log=log, analysis=analysis, assessment=assessed,
    ))
    spine_edited = build_view(
        SpineInputs(name="Dr Timbo", log=log, analysis=analysis,
                    assessment=assessed),
        screens_m=[(18.0, 30.0)],
    )
    out["spine"] = {
        "total_depth": clean(spine["section"]["totalDepth"]),
        "domain": clean(spine["section"]["domain"]),
        # the rock each row is logged as, and the bands the drawing draws
        "lithology": [[clean(u["top"]), clean(u["base"]), u["aquifer"], u["class"]]
                      for u in spine["section"]["lithology"]],
        "bands": [[clean(b["top"]), clean(b["base"]), b["class"], b["colour"]]
                  for b in spine["section"]["bands"]],
        "strikes": clean(spine["section"]["waterStrikes"]),
        "segments": [[s["kind"], clean(s["top"]), clean(s["base"])]
                     for s in spine["section"]["segments"]],
        "levels": {k: clean(v) for k, v in spine["section"]["levels"].items()},
        "screen_limits": {k: clean(v)
                          for k, v in spine["section"]["screenLimits"].items()},
        "screens": [[clean(s["top"]), clean(s["base"])]
                    for s in spine["design"]["screens"]],
        "total_screen_m": clean(spine["design"]["totalScreenM"]),
        "screen_share": clean(spine["design"]["screenShare"]),
        "yield_safe": clean(spine["design"]["yield"].get("safeYieldM3PerH")),
        "yield_range": spine["design"]["yield"].get("rangeText"),
        "yield_pump_depth": clean(spine["design"]["yield"].get("pumpDepthM")),
        "methods": [[m["label"], clean(m["transmissivity"])]
                    for m in spine["design"]["yield"].get("methods", [])],
        "design_flags": [[f["level"], f["code"]] for f in spine["design"]["flags"]],
        "cost_direct": clean(spine["costing"]["directCost"]),
        "cost_total": clean(spine["costing"]["totalCost"]),
        "cost_price": clean(spine["costing"]["price"]),
        "cost_per_metre": clean(spine["costing"]["costPerMetre"]),
        "by_stage": [[r["label"], clean(r["amount"]), clean(r["share"])]
                     for r in spine["costing"]["byStage"]],
        "quantity_basis": {k: clean(v)
                           for k, v in spine["costing"]["quantityBasis"].items()},
        "quality_verdict": spine["quality"]["verdict"],
        "quality_health": spine["quality"]["healthExceedances"],
        "quality_aesthetic": spine["quality"]["aestheticExceedances"],
        "quality_ratios": [[r["parameter"], clean(r["ratio"]), r["limitName"],
                            r["limitKind"]] for r in spine["quality"]["rows"]],
        "piper_percent": {k: clean(v)
                          for k, v in spine["quality"]["piper"]["percent"].items()},
        "edited_screens": [[clean(s["top"]), clean(s["base"])]
                           for s in spine_edited["design"]["screens"]],
        "edited_cost_direct": clean(spine_edited["costing"]["directCost"]),
        "edited": spine_edited["edited"],
    }

    # The drill-target scorecard, over the real Rokel soundings.
    rokel_inversions = [invert_sounding(s) for s in soundings]
    rokel_interps = [
        interpret_model(s, inv.model)
        for s, inv in zip(soundings, rokel_inversions, strict=True)
    ]
    out["siting"] = [
        {
            "id": r.sounding_id, "rank": r.rank,
            "suitability": clean(r.suitability), "grade": r.grade,
            "components": {
                "aquifer_thickness": clean(r.components.aquifer_thickness),
                "resistivity_fit": clean(r.components.resistivity_fit),
                "overburden": clean(r.components.overburden),
                "basal_fracture": clean(r.components.basal_fracture),
            },
            "rationale": r.rationale,
        }
        for r in assess_siting(rokel_interps)
    ]
    # The interpretation itself, and the preference table a report prints
    # from it: the zones, the depth the survey resolves, the flags and the
    # narrative are the sentences a siting decision is argued from, and
    # they used to be held to nothing.
    out["interpretations"] = [
        {
            "id": i.sounding_id,
            "water_zones": [[clean(t), clean(b)] for t, b in i.water_zones],
            "max_drilling_depth_m": clean(i.max_drilling_depth_m),
            "investigation_depth_m": clean(i.investigation_depth_m),
            "max_spacing_m": clean(i.max_spacing_m),
            "basement_not_resolved": i.basement_not_resolved,
            "confidence": clean(i.confidence),
            "fit_quality": i.fit_quality,
            "flags": [[f.level, f.code, f.message] for f in i.flags],
            "narrative": i.narrative,
        }
        for i in rokel_interps
    ]
    out["preference"] = drilling_preference_table(rokel_interps)
    out["ves_text"] = ves_text(rokel_inversions, rokel_interps)
    out["ves_range"] = ves_range_reference(soundings, rokel_inversions)
    out["odds"] = odds_reference(
        rokel_interps, [sd.site for sd in soundings],
        [_odds_range(None if r["basement_m"] is None else
                     (r["basement_m"]["p10"], r["basement_m"]["p50"], r["basement_m"]["p90"]),
                     r["basement_unresolved"]) for r in out["ves_range"]["short"]])
    out["cost_range"] = cost_range_reference(out["ves_range"]["short"])
    out["measurement"] = measurement_reference(out["odds"], out["cost_range"])

    # A siting survey with no borehole yet: the design comes from the
    # interpretation alone. The degenerate half-space used to make this an
    # 80 m hole with 48 m of screen at both Rokel points, from soundings that
    # resolve 40 m, and the browser built it from the same zone.
    ves_only = design_borehole(interpretation=rokel_interps[0])
    out["ves_only_design"] = {
        "depth": clean(ves_only.total_depth_m),
        "screens": [[clean(x.top_m), clean(x.bottom_m)] for x in ves_only.screens],
        "screen_len": clean(ves_only.total_screen_length_m),
        "basis": list(ves_only.design_basis),
    }

    # Geographic -> UTM, the direction a pasted phone position takes.
    out["geo"] = [
        {"lat": lat, "lon": lon,
         "easting": clean(geographic_to_utm(lat, lon).easting),
         "northing": clean(geographic_to_utm(lat, lon).northing),
         "zone": geographic_to_utm(lat, lon).zone}
        for lat, lon in ((8.4657, -13.2317), (8.7043, -11.4084), (7.9560, -11.7400))
    ]

    # Ground distance. Subtracting raw eastings across the 28N/29N boundary
    # put two sites 2.2 km apart 659 km apart, so both engines have to agree
    # on the same ellipsoidal answer, not merely on a close one.
    out["distance"] = [
        {"a": [8.50, -12.01], "b": [8.50, -11.99],
         "metres": clean(geodesic_distance_m(8.50, -12.01, 8.50, -11.99))},
        {"a": [8.4657, -13.2317], "b": [7.9647, -11.7383],
         "metres": clean(geodesic_distance_m(8.4657, -13.2317, 7.9647, -11.7383))},
        {"a": [8.0, -12.0], "b": [8.0, -12.0],
         "metres": clean(geodesic_distance_m(8.0, -12.0, 8.0, -12.0))},
    ]

    # Free-text borehole statuses, including the ones substring matching read
    # as successes ("incomplete" contains "complete").
    out["statuses"] = {
        raw: classify_status({"status": raw})
        for raw in ("Successful", "Completed - dry", "incomplete",
                    "not completed", "unproductive", "non-productive",
                    "low productivity", "in progress", "Sited", "visited",
                    "qwerty")
    }

    # Unit conversion, the layer both engines put every value through before
    # it is compared against a limit.
    out["units"] = [
        {"value": v, "from": f, "to": t, "result": clean(unit_convert(v, f, t))}
        for v, f, t in (
            (5.0, "ug/L", "mg/L"), (5.0, "ppb", "mg/L"), (0.5, "g/L", "mg/L"),
            (0.185, "mS/cm", "uS/cm"), (2.0, "CFU/mL", "CFU/100 mL"),
            (2.0, "L/s", "m3/h"), (120.0, "L/min", "m3/h"), (2.0, "h", "min"),
            (5.0, "gpm", "m3/h"), (5.0, "squiggles", "mg/L"),
            (5.0, "mg/L", "NTU"),
        )
    ]

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

    # The certification gate, over a project missing one thing at a time.
    from groundwater.readiness import assess_readiness

    _log = read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    _analysis = analyse_pumping_test(
        read_pumping_workbook(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx"))
    _assessment = assess_sample(
        read_quality_workbook(DATA / "dr_timbo" / "dr_timbo_water_quality.xlsx"))
    _design = design_borehole(
        log=_log, static_water_level_m=_analysis.test.static_water_level_m)
    _located = SiteMetadata(community="Dr. Timbo's", district="Western Area Rural",
                            easting=778000.0, northing=946000.0, utm_zone=28)
    _full = {"site": _located, "drilling_log": _log, "pump_analysis": _analysis,
             "wq_assessment": _assessment, "borehole_design": _design}
    _gate_cases = {
        "full": (_full, {}),
        "empty": ({}, {}),
        "no_site": (dict(_full, site=SiteMetadata(community="Nowhere")), {}),
        # a northing 500 km short: a position, but not one in the country
        "off_country": (dict(_full, site=SiteMetadata(
            community="Dr. Timbo's", district="Western Area Rural",
            easting=778000.0, northing=446000.0, utm_zone=28)), {}),
        "no_quality": (dict(_full, wq_assessment=None), {}),
        "overridden": (dict(_full, wq_assessment=None), {
            "water_quality_panel": {"reason": "lab result awaited", "by": "M. K."},
            "water_quality_evaluable": {"reason": "lab result awaited", "by": "M. K."},
        }),
        # The demonstration paths, which the two engines have to read the
        # same way: a bundled file whose readings were invented, and a
        # bundled file faithfully transcribed from a real survey. Both hold
        # the report back; only the first says nothing was measured.
        "synthetic_source": (dict(_full, sources={
            "wq": {"sample": "dr_timbo/dr_timbo_water_quality.xlsx"},
        }), {}),
        "bundled_source": (dict(_full, sources={
            "ves": {"name": "rokel_ves.xlsx", "b64": "x",
                    "sample": "rokel/rokel_ves.xlsx"},
        }), {}),
        # A bundled file whose measurements are real but whose blank columns
        # were filled in illustratively. Not blocking - it is a stated
        # assumption, which is the other half of the gate's output.
        "reconstructed_source": (dict(_full, sources={
            "log": {"sample": "dr_timbo/dr_timbo_drilling_log.xlsx"},
        }), {}),
        # The same synthetic workbook opened off disk by a script, with no
        # picker marker on it. Invented readings are invented whoever opened
        # the file, so this still fails.
        "synthetic_by_name": (dict(_full, sources={
            "wq": {"name": "dr_timbo_water_quality.xlsx"},
        }), {}),
        # But a faithfully transcribed example opened the same way is not a
        # demonstration: a script publishing the Rokel survey under the Rokel
        # name is reporting exactly what it says it is.
        "transcribed_by_name": (dict(_full, sources={
            "ves": {"name": "rokel_ves.xlsx"},
        }), {}),
        # An upload of the analyst's own file is not a demonstration, however
        # it is named - the check must not fire on everything with a source.
        "own_upload": (dict(_full, sources={
            "log": {"name": "kambia_drilling_log.xlsx", "b64": "x"},
        }), {}),
        # The one case an override is for: publishing the worked example
        # itself, with the reason on the cover.
        "demonstration_override": (dict(_full, sources={
            "wq": {"sample": "dr_timbo/dr_timbo_water_quality.xlsx"},
        }), {"field_data": {"reason": "published as a worked example",
                            "by": "M. K."}}),
    }
    out["readiness"] = {}
    for _name, (_state, _over) in _gate_cases.items():
        out["readiness"][_name] = {
            report: {
                "state": assess_readiness(_state, report, _over).state,
                "summary": assess_readiness(_state, report, _over).summary,
                "requirements": [
                    [r.key, r.state, r.detail, r.override_reason, r.override_by]
                    for r in assess_readiness(_state, report, _over).requirements
                ],
                # Stated assumptions travel onto the report beside the gate, so
                # the two engines have to state the same ones. Nothing compared
                # these, and the browser was silently stating none of them.
                "assumptions": assess_readiness(_state, report, _over).assumptions,
            }
            for report in ("completion", "handover", "quality", "pumping")
        }

    # The handover works list. Both engines build it from the same records
    # and it is what an interim payment is argued from, so the two have to
    # word it identically; nothing compared them until now.
    from groundwater.reporting.handover import (
        HandoverReportInputs, default_works,
    )

    def _works(**kw):
        return default_works(HandoverReportInputs(site=_located, **kw))

    out["handover_works"] = {
        "full": _works(log=_log, design=_design, pumping=_analysis,
                       quality=_assessment),
        "sited": _works(log=_log, design=_design, pumping=_analysis,
                        quality=_assessment, sited=True),
        "bare": _works(),
        # a sheet where nobody wrote the depth down: the bullet waits for a
        # figure rather than certifying a borehole drilled to "n/a"
        "no_depth": _works(log=DrillingLog(
            site=_located, drilling_method="Air rotary (DTH hammer)")),
    }

    # The QR encoder. Every module of every symbol, because a symbol that is
    # wrong in the data region still looks exactly like a QR symbol - and the
    # browser draws the one that gets printed and fixed to the headworks.
    from groundwater import qr

    _qr_payloads = [
        "SL-WAR-8FEEVKQ-T",
        ("BOREHOLE SL-WAR-8FEEVKQ-T\nDr. Timbo's (Western Area Rural)\n"
        "8.48310 N, 13.22940 W\n62.0 m deep, 1.85 m3/h"),
        "Kailahun - 10\u00b0 12' 03\" N",     # non-ASCII, so UTF-8 is exercised
    ]
    out["qr"] = [
        {
            "text": text, "ecc": ecc, "mask": mask,
            "version": _code.version, "size": _code.size,
            "chosen_mask": _code.mask,
            "penalty": qr._penalty(_code.modules),
            # one string per row keeps the reference file readable and diffable
            "rows": ["".join("1" if cell else "0" for cell in row)
                     for row in _code.modules],
        }
        for text in _qr_payloads
        for ecc in ("L", "M", "Q", "H")
        for mask in (None, 0, 5)
        for _code in [qr.encode(text, ecc=ecc, mask=mask)]
    ]
    out["qr_capacity"] = [
        {"version": v, "ecc": e, "bytes": qr._capacity_bytes(v, e)}
        for v in range(1, qr.MAX_VERSION + 1) for e in ("L", "M", "Q", "H")
    ]

    # The asset registry: identifiers, the merge, and what the event stream
    # says is true on a fixed day.
    from datetime import date as _date

    from groundwater import registry as _registry

    _sites = [
        SiteMetadata(district="Western Area Rural", easting=694912.0,
                     northing=938150.0, utm_zone=28),
        SiteMetadata(district="Western Area Rural", easting=694914.0,
                     northing=938147.0, utm_zone=28),
        SiteMetadata(district="Bo", easting=790500.0, northing=875300.0,
                     utm_zone=28),
        SiteMetadata(district="Kailahun", easting=280400.0, northing=925600.0,
                     utm_zone=29),
        SiteMetadata(district="Nowhere At All", easting=694912.0,
                     northing=938150.0, utm_zone=28),
    ]
    out["asset_ids"] = [
        {"district": s.district, "easting": s.easting, "northing": s.northing,
         "zone": s.utm_zone, "id": _registry.mint_asset_id(s)}
        for s in _sites
    ]
    _timbo_id = _registry.mint_asset_id(_sites[0])
    out["asset_id_parsing"] = [
        {"typed": t, "parsed": _registry.parse_asset_id(t),
         "ok": _registry.validate_asset_id(t)[0],
         "reason": _registry.validate_asset_id(t)[1]}
        for t in (_timbo_id, _timbo_id.lower(), _timbo_id.replace("0", "O"),
                  _timbo_id.replace("1", "L"), " " + _timbo_id + " ",
                  _timbo_id[:-1] + "Z", _timbo_id.replace("-", ""),
                  "SL-WAR-XXXXXXX-9", "not an identifier", "")
    ]
    _streams = [
        [{"when": "2020-01-10", "kind": "commissioned", "by": "M. Kolleh"},
         {"when": "2023-04-02", "kind": "failure", "note": "rising main parted"}],
        [{"when": "2023-04-02", "kind": "failure", "note": "rising main parted"},
         {"when": "2023-05-11", "kind": "repair", "note": "new seals",
          "by": "A. Bangura", "photo": "data:image/jpeg;base64,AAAA"},
         {"when": "not written down", "kind": "inspection"},
         {"when": "2099-01-01", "kind": "restored"}],
    ]
    out["asset_events"] = [
        e.as_dict() for e in _registry.merge_events(_timbo_id, *_streams)
    ]
    _registry_cases = {
        "silent": [],
        "commissioned": _streams[0][:1],
        "broken": _streams[0],
        "repaired": _streams[0] + [{"when": "2023-05-11", "kind": "restored"}],
        "sampled": _streams[0][:1] + [{"when": "2023-03-01", "kind": "water_sample"},
                                      {"when": "2024-05-20", "kind": "inspection"}],
        "decommissioned": _streams[0][:1] + [{"when": "2022-08-01",
                                              "kind": "decommissioned"}],
        "merged": _streams[0] + _streams[1],
    }
    _today = _date(2024, 6, 1)
    _assets = {}
    for _name, _events in _registry_cases.items():
        _assets[_name] = _registry.Asset(
            asset_id=_timbo_id, community="Dr. Timbo's",
            district="Western Area Rural", easting=694912.0, northing=938150.0,
            utm_zone=28, total_depth_m=62.0, safe_yield_m3_per_h=1.85,
            pump_type="India Mark II", installed_by="WiNGiN",
            events=[_registry.AssetEvent(**e) for e in _events],
        )
    out["asset_state"] = {
        name: _registry.asset_state(asset, _today).as_dict()
        for name, asset in _assets.items()
    }
    out["asset_placard"] = clean(_registry.placard_lines(
        _assets["commissioned"],
        _registry.asset_state(_assets["commissioned"], _today)))
    out["asset_qr_payload"] = _registry.qr_payload(_assets["commissioned"])
    out["registry_rows"] = _registry.registry_rows(list(_assets.values()), _today)
    out["registry_stats"] = clean(
        _registry.registry_stats(list(_assets.values()), _today))
    out["asset_months"] = [
        {"from": d, "months": m, "due": _registry._add_months(
            _date.fromisoformat(d), m).isoformat()}
        for d, m in (("2023-08-31", 6), ("2023-12-31", 2), ("2020-02-29", 12),
                     ("2023-01-31", 1), ("2023-03-30", 11), ("2024-02-29", 12))
    ]

    # The seasonal yield model: the month read off the sheet, and the yield
    # at each scenario's water level.
    from groundwater.seasonal import month_of as _month_of
    from groundwater.seasonal import seasonal_yield as _seasonal_yield

    out["seasonal_dates"] = [
        {"text": t, "month": _month_of(t)[0], "note": _month_of(t)[1]}
        for t in ("10/05/2018", "25/04/2018", "04/25/2018", "2018-09-14",
                  "14 Sept 2018", "September 2018", "during the rains",
                  "05/2018", "", "31/13/2018", "2018/09/14")
    ]
    out["seasonal"] = {}
    for _label, _month, _band in (("august", 8, None), ("may", 5, None),
                                  ("september", 9, None), ("unknown", None, None),
                                  ("wide", 8, 4.5), ("zero", 8, 0.0)):
        _result = _seasonal_yield(_analysis, month=_month, annual_range_m=_band)
        out["seasonal"][_label] = clean(_result.as_dict())

    # Coverage as a planning figure: projection, freshness and the
    # dry-season band.
    from groundwater import planning as _planning
    from groundwater.waterpoints import WaterPoint as _WaterPoint

    def _wp(functional, year, months):
        return _WaterPoint(
            row_id="x", lat=8.0, lon=-13.0, functional=functional,
            status="", source="Borehole", technology="Hand Pump",
            install_year=None, adm2="", report_year=year,
            months_per_year=months)

    from groundwater.waterpoints import _months_per_year, _year_of

    out["wpdx_fields"] = [
        {"date": d, "year": _year_of(d),
         "months_text": m, "months": _months_per_year(m)}
        for d, m in (("2019-04-02T00:00:00", "12"), ("02/04/2019", "yes"),
                     ("2019", "6 months"), ("", ""), ("not a date", "seasonal"),
                     ("1899-01-01", "14"), ("survey 2024 round 2", "no"))
    ]
    out["growth_rate"] = _planning.intercensal_growth_rate()
    _planning_population = {
        "Bo": 575478.0, "Kono": 506100.0, "Pujehun": 346461.0,
        "Falaba": 202566.0, "Western Area Urban": 1055964.0,
    }
    _planning_points = {
        "Bo": [_wp(True, 2024, 12), _wp(True, 2010, None), _wp(False, 2024, 12)],
        "Kono": [_wp(True, None, None), _wp(True, 2003, 6)],
        "Pujehun": [_wp(False, 2020, None)],
        "Western Area Urban": [_wp(True, 2025, 12), _wp(True, 2025, None),
                               _wp(True, 2019, 4)],
    }
    out["planning"] = {}
    for _label, _year, _rate, _rates in (
        ("census", 2015, None, None),
        ("today", 2026, None, None),
        ("slow", 2026, 0.015, None),
        ("districts", 2026, None, {"Western Area Urban": 0.06, "Pujehun": 0.01}),
    ):
        _rows, _proj = _planning.planning_rows(
            _planning_population, _planning_points,
            as_of_year=_year, rate=_rate, rates=_rates)
        out["planning"][_label] = clean({
            "projection": _proj.as_dict(),
            "stats": _planning.planning_stats(_rows, _proj),
            "rows": [r.as_dict() for r in _rows],
        })

    # Procurement: planned against actual, and what that makes payable.
    from groundwater.procurement import (
        Contract as _Contract,
    )
    from groundwater.procurement import (
        ContractLine as _ContractLine,
    )
    from groundwater.procurement import (
        Measurement as _Measurement,
    )
    from groundwater.procurement import (
        Variation as _Variation,
    )
    from groundwater.procurement import certify as _certify
    from groundwater.procurement import contract_summary as _contract_summary

    def _proc_contract(**terms):
        return _Contract(
            ref="WSD/2024/017", contractor="WiNGiN", client="District Council",
            date="2024-02-01",
            lines=[
                _ContractLine("MOB", "Mobilisation", "sum", 1, 3000.0),
                _ContractLine("DRL-OB", "Drilling, overburden", "m", 20, 45.0),
                _ContractLine("DRL-RK", "Drilling, rock", "m", 25, 80.0),
                _ContractLine("CAS", "uPVC casing", "m", 45, 22.0),
            ],
            **terms)

    _proc_cases = {
        "clean": (_proc_contract(), [_Measurement("MOB", 1.0)], [], 1, 0.0),
        "overmeasured": (_proc_contract(),
                         [_Measurement("MOB", 1.0), _Measurement("DRL-RK", 42.0)],
                         [], 1, 0.0),
        "varied": (_proc_contract(),
                   [_Measurement("MOB", 1.0), _Measurement("DRL-RK", 42.0)],
                   [_Variation("VO-1", "2024-03-04", "DRL-RK", 17.0, None,
                               "deeper water", "M. Kolleh")], 2, 1500.0),
        "unsigned": (_proc_contract(), [_Measurement("GRAVEL", 12.0)],
                     [_Variation("VO-2", "2024-03-04", "CAS", 5.0)], 1, 0.0),
        "new_item": (_proc_contract(), [_Measurement("GRAVEL", 12.0)],
                     [_Variation("VO-3", "2024-03-04", "GRAVEL", 12.0, None,
                                 "gravel pack", "M. K.", "Gravel pack", "m3")],
                     1, 0.0),
        "advance": (_proc_contract(advance_percent=20.0, retention_percent=5.0),
                    [_Measurement("MOB", 1.0), _Measurement("DRL-OB", 20.0),
                     _Measurement("DRL-RK", 25.0), _Measurement("CAS", 45.0)],
                    [], 1, 0.0),
        "overpaid": (_proc_contract(retention_percent=0.0),
                     [_Measurement("MOB", 1.0)], [], 2, 5000.0),
        "negatives": (_proc_contract(), [_Measurement("CAS", -10.0)], [], 3, -5.0),
        # a rate-only variation is a variation; an omission beyond the line
        # authorises nothing; a duplicated code is valued once and named
        "repriced": (_proc_contract(),
                     [_Measurement("MOB", 1.0), _Measurement("CAS", 45.0)],
                     [_Variation("VO-4", "2024-03-04", "CAS", 0.0, 26.0,
                                 "supplier price", "Engineer")], 1, 0.0),
        "over_omitted": (_proc_contract(), [_Measurement("CAS", 10.0)],
                         [_Variation("VO-5", "2024-03-04", "CAS", -60.0, None,
                                     "redesign", "Engineer")], 1, 0.0),
        "duplicate": (_Contract(ref="DUP", lines=[
                          _ContractLine("CAS", "uPVC casing 6 in", "m", 10, 22.0),
                          _ContractLine("CAS", "uPVC casing 4 in", "m", 10, 22.0)]),
                      [_Measurement("CAS", 10.0)], [], 1, 0.0),
    }
    out["procurement"] = {}
    for _label, (_ct, _ms, _vs, _no, _prev) in _proc_cases.items():
        _cert = _certify(_ct, _ms, number=_no, date="2024-04-01",
                         variations=_vs, previously_certified_usd=_prev)
        out["procurement"][_label] = clean({
            "certificate": _cert.as_dict(),
            "summary_rows": _contract_summary(_ct, _cert),
        })

    # Rounding and %g, which the two languages get wrong in different ways.
    out["rounding"] = [
        {"value": v, "digits": d, "rounded": clean(round(v, d))}
        for v, d in ((0.15, 1), (14.05, 1), (2.675, 2), (0.5, 0), (1.5, 0),
                     (2.5, 0), (-0.15, 1), (2.34, 2), (2.345, 2), (0.125, 2),
                     (-2.5, 0), (45.05, 1), (150.5, 0))
    ]
    out["formatting"] = [
        {"value": v, "text": f"{v:g}"}
        for v in (1e6, 1e15, 999999.6, 1e5, 1e7, 1234567, 0.0001, 0.00001,
                  2.93, 0.0, 0.005, 1e-7)
    ]

    # The portfolio view, over summaries chosen to exercise every status class
    # and the zone-inference fallback.
    summaries = [
        {"community": "Rokel", "district": "Port Loko", "easting": 235000.0,
         "northing": 963000.0, "status": "sited"},
        {"community": "Dr. Timbo", "district": "Western Area Rural",
         "easting": 778000.0, "northing": 946000.0, "utm_zone": 28,
         "status": "Completed - successful", "total_depth_m": 45.0,
         "safe_yield_m3_per_h": 2.34, "water_verdict": "pass",
         "verdict_schema": 2, "cost_per_meter_usd": 133.0},
        {"community": "Kuntoloh", "district": "Western Area Rural",
         "status": "Completed - dry", "total_depth_m": 52.0,
         "water_verdict": "aesthetic", "cost_per_meter_usd": 151.0},
    ]
    out["portfolio"] = {
        "rows": clean(portfolio_rows(summaries)),
        "points": [[p["label"], clean(p["lat"]), clean(p["lon"]), p["status"]]
                   for p in portfolio_points(summaries)],
        "stats": clean(portfolio_stats(summaries)),
        "detail": [list(row) for row in site_detail(summaries[1])],
        "one_pager": site_one_pager(summaries[1]),
    }

    out["pdf_sheet"] = pdf_sheet_reference()
    out["pumping_cases"] = pumping_cases()
    out["regional"] = regional_reference()
    out["survey_figures"] = survey_figures_reference(rokel_interps)
    out["design_cases"] = [design_case(spec) for spec in DESIGN_CASES]
    out["drilling_cases"] = [drilling_case(grid) for grid in DRILLING_CASES]
    out["photo_evidence"] = photo_evidence_reference()
    out["field_kit"] = field_kit_reference()
    out["airlift"] = airlift_reference()
    out["pumping_spread"] = pumping_spread_reference()
    out["ves_forward"] = ves_forward_reference()
    out["ves_bessel"] = ves_bessel_reference()
    return out


# ----------------------------------------------- airlift yield (step 2.3)

#: The drilling co-pilot's airlift readings: containers timed once and
#: more than once, notch heads inside, at the edges of and outside the range
#: the coefficient holds for, a reason with untidy spaces, and readings that
#: give no yield, which both engines refuse.
AIRLIFT_CASES = [
    ["bucket", {"volume_l": 20, "timings_s": [25, 24.6, 25.4]}],
    ["bucket", {"volume_l": 10, "timings_s": [7.3]}],
    ["bucket", {"volume_l": 200, "timings_s": [61.5, 59.25]}],
    ["vnotch", {"head_mm": 34}],
    ["vnotch", {"head_mm": 50}],
    ["vnotch", {"head_mm": 87.5}],
    ["vnotch", {"head_mm": 380}],
    ["vnotch", {"head_mm": 410}],
    ["none", {"reason": "  compressor\tdown,  no airlift "}],
    ["bucket", {"volume_l": 20, "timings_s": []}],
    ["bucket", {"volume_l": 0, "timings_s": [20]}],
    ["bucket", {"volume_l": 20, "timings_s": [20, 0]}],
    ["vnotch", {"head_mm": 0}],
    ["none", {"reason": " \t "}],
    ["airlift", {}],
]


def airlift_reference() -> dict:
    from groundwater.field_kit import airlift_yield

    results = []
    for method, options in AIRLIFT_CASES:
        try:
            results.append(airlift_yield(method, **options))
        except ValueError:
            results.append(None)
    return {"cases": AIRLIFT_CASES, "results": results}


# ------------------------------------- pumping spread and diagnostics (step 3.2)

def _large_diameter_grid() -> list[list]:
    """Dr Timbo's sheet rewritten as a thirty-minute test on a borehole whose
    casing holds most of what is pumped (T = 0.3 m2/day): every fit is
    disqualified and the Papadopulos-Cooper fit is adopted."""
    from groundwater.hydraulics.spread import pc_model
    from groundwater.ingestion import common

    grid, _ = common.load_grid(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    grid = json.loads(json.dumps(grid, default=str))
    for row in grid[11:]:
        for c in range(15):
            row[c] = None
    grid[4][4], grid[5][1], grid[5][4], grid[8][2] = 60, 5.0, 50, 1.0
    times = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30]
    drawdown = pc_model(24.0, 0.1, 0.0615)(
        np.array(times[1:], float) / 1440.0, math.log10(0.3), -3.0)
    levels = [5.0] + [round(5.0 + float(s), 2) for s in drawdown]
    for i, (t, level) in enumerate(zip(times, levels, strict=True)):
        grid[11 + i][0], grid[11 + i][1] = t, level
    for i, t in enumerate([0, 1, 2, 3, 4, 5, 10, 15, 20, 30]):
        grid[11 + i][12] = t
        grid[11 + i][13] = round(levels[-1] - 0.05 * math.log1p(t), 2)
    return grid


def _wide_band_grid() -> list[list]:
    """An hour's test whose readings scatter by up to three metres about a
    straight line on log time: the Theis fit is adopted, two resamples fail,
    and the band is too wide for the safety factor, so the rate is not called
    sustainable."""
    from groundwater.ingestion import common

    grid, _ = common.load_grid(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    grid = json.loads(json.dumps(grid, default=str))
    for row in grid[11:]:
        for c in range(15):
            row[c] = None
    grid[4][4], grid[5][1], grid[5][4], grid[8][2] = 60, 5.0, 50, 2.0
    times = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60]
    wobble = [0, 0.1, -0.2, 0.15, -0.1, 0.3, -0.4, 0.5, -0.3, 0.6, -0.5, 0.7, -0.6,
              0.8, -0.7, 0.9, -0.2]
    for i, t in enumerate(times):
        s = 0.0 if t == 0 else 1.2 * math.log10(t) + 2.0 + 3.5 * wobble[i]
        grid[11 + i][0], grid[11 + i][1] = t, round(5.0 + s, 2)
    return grid


def _spread_summary(analysis) -> dict:
    """What step 3.2 adds to an analysis, as parity.mjs reads it back."""
    from groundwater.hydraulics.spread import (
        diagnostic_text,
        papadopulos_cooper_text,
        spread_paragraphs,
        sustainable_sentence,
    )

    th, pc, sp, dg = (analysis.theis, analysis.papadopulos_cooper, analysis.spread,
                      analysis.diagnostic)
    boot = sp.bootstrap if sp else None
    rec = analysis.yield_recommendation
    return clean({
        "source": analysis.transmissivity_source,
        "T": analysis.transmissivity_m2_per_day,
        "theis": [th.transmissivity_m2_per_day, th.transmissivity_low_m2_per_day,
                  th.transmissivity_high_m2_per_day] if th else None,
        "pc": [pc.transmissivity_m2_per_day, pc.storativity, pc.alpha, pc.rmse_m,
               pc.transmissivity_low_m2_per_day, pc.transmissivity_high_m2_per_day]
              if pc else None,
        "pc_invalid": analysis.papadopulos_cooper_invalid,
        "boot": {k: getattr(boot, k) for k in (
            "method", "replicates", "failed", "block_length", "seed", "n_points",
            "p10", "p50", "p90", "reason")} if boot else None,
        "spread": [sp.safe_yield_low_m3_per_h, sp.safe_yield_high_m3_per_h,
                   sp.long_term_low_m3_per_h, sp.holds_at_dry_season,
                   sp.pump_depth_low_m, sp.pump_depth_high_m] if sp else None,
        "diagnostic": {
            "t": dg.derivative_time_min, "d": dg.derivative_m, "slopes": dg.slopes,
            "regimes": [[r.key, r.start_min, r.end_min, r.slope, r.n_points]
                        for r in dg.regimes],
            "plateau": dg.plateau_transmissivity_m2_per_day,
        } if dg else None,
        "safe": rec.safe_yield_m3_per_h if rec else None,
        "range_text": rec.yield_range_text if rec else None,
        "confidence": rec.confidence if rec else None,
        "text": spread_paragraphs(analysis) + [
            diagnostic_text(dg), papadopulos_cooper_text(analysis),
            sustainable_sentence(rec, sp) or ""],
    })


def _regime_curves() -> dict:
    """Synthetic drawdowns with one regime each, as minutes and metres."""
    from scipy.special import exp1

    from groundwater.hydraulics.spread import pc_model

    t = np.geomspace(0.5, 3000, 45)

    def theis(radius=0.1):
        u = radius**2 * 1e-3 / (4 * 5.0 * t / 1440)
        return 48.0 / (4 * math.pi * 5.0) * exp1(u)

    return {
        "radial": theis(),
        "storage": pc_model(48.0, 0.1, 0.0615)(t / 1440, math.log10(0.5), -3.0),
        "linear": 0.3 * np.sqrt(t),
        "recharge": theis() - theis(60.0),
        "barrier": theis() + theis(60.0),
    }, t


def pumping_spread_reference() -> dict:
    """The bands, the derivative and the large-diameter fit, in both engines.

    The generator's stream, the Bessel functions and the well function are
    compared value for value; each pumping sheet's analysis is compared
    through _spread_summary, its sentences word for word.
    """
    from types import SimpleNamespace

    from scipy.special import k0e, k1e

    from groundwater.hydraulics.spread import (
        Mulberry32,
        block_length,
        diagnose,
        pc_well_function,
        quantile,
    )
    from groundwater.ingestion.pumping import _assemble

    out: dict = {}
    streams = {}
    for seed in (1, 32, 4294967295):
        rng = Mulberry32(seed)
        streams[str(seed)] = [rng.next_float() for _ in range(50)]
    out["mulberry32"] = streams
    out["blocks"] = [[n, block_length(n)] for n in (1, 5, 8, 9, 26, 27, 28, 64, 65, 125)]
    values = [3.0, 1.0, 4.0, 1.5, 9.0, 2.6, 5.35]
    out["quantile"] = {"values": values,
                       "q": [[q, quantile(values, q)] for q in (0, 0.1, 0.25, 0.5, 0.9, 1)]}
    out["bessel"] = [[x, float(k0e(x)), float(k1e(x))]
                     for x in (1e-6, 0.01, 0.5, 1.999, 2.0, 2.001, 7.5, 40.0, 900.0)]
    out["well_function"] = [[u, a, pc_well_function(u, a)]
                            for a in (1e-1, 1e-3, 1e-5) for u in (1.0, 1e-2, 1e-4, 1e-6)]

    curves, t = _regime_curves()
    regimes = {}
    for name, s in curves.items():
        test = SimpleNamespace(static_water_level_m=0.0, steps=[SimpleNamespace(
            time_min=t, water_level_m=np.asarray(s), discharge_m3_per_h=2.0)])
        dg = diagnose(SimpleNamespace(test=test))
        regimes[name] = {
            "t": clean(t), "s": clean(np.asarray(s)),
            "regimes": clean([[r.key, r.start_min, r.end_min, r.slope, r.n_points]
                              for r in dg.regimes]),
            "plateau": clean(dg.plateau_transmissivity_m2_per_day),
        }
    out["regimes"] = regimes

    from groundwater.ingestion import common

    # the edge sheets travel in pumping_cases already; parity reads them there
    edge = _pumping_case_grids()
    timbo, _ = common.load_grid(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    own = {"dr_timbo": json.loads(json.dumps(timbo, default=str)),
           "large_diameter": _large_diameter_grid(),
           "wide_band": _wide_band_grid()}
    cases = {}
    for name, grid in list(own.items()) + list(edge.items()):
        test = _assemble(grid, f"{name}.xlsx")
        cases[name] = {"grid": json.dumps(grid) if name in own else None,
                       **_spread_summary(analyse_pumping_test(test))}
    out["cases"] = cases
    return out


# ----------------------------------------------- photo evidence (step 2.4)

def photo_evidence_reference() -> dict:
    """The provenance both engines record for the same files, and the gate.

    The files are the committed fixture, whose EXIF was written by hand, and
    variants of it from the same builder: big-endian, no metadata at all
    (so the device clock and a device fix are used), and a blank clock.
    The bytes travel in this file, so the browser reads exactly these.
    """
    import base64
    import importlib.util

    from groundwater.photos import describe_provenance, photo_provenance
    from groundwater.readiness import assess_readiness

    spec = importlib.util.spec_from_file_location(
        "make_photo_fixture", OUT.parent / "fixtures" / "make_photo_fixture.py")
    make = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make)
    attached = "2026-10-03T09:00:00Z"
    files = {
        "fixture": ((OUT.parent / "fixtures" / "photo_exif.jpg").read_bytes(), {}),
        "big_endian": (make.jpeg_with_exif(make.build_tiff(">", **make.FIXTURE_EXIF)), {}),
        "no_exif_device_fix": (make.BASE_JPEG, {
            "device_fix": {"lat": 8.4801, "lon": -13.2302, "accuracy_m": 12.5}}),
        "no_exif_refused": (make.BASE_JPEG, {"position_note": "refused",
                                             "stored": "downscaled"}),
        "blank_clock": (make.jpeg_with_exif(make.build_tiff(
            "<", taken="0000:00:00 00:00:00", lat=make.FIXTURE_EXIF["lat"],
            lon=make.FIXTURE_EXIF["lon"])), {}),
        # padded with a control byte that str.strip() takes and trim() does
        # not, and with a space both take: the two once read this differently
        "control_padding": (make.jpeg_with_exif(make.build_tiff(
            ">", taken=" 2024:03:05 14:22:10", offset="+01:00\x1c",
            lat=("N ", ((8, 1), (1, 1), (1, 1))),
            lon=("W\x1f", ((13, 1), (0, 1), (0, 1))))), {}),
    }
    cases = {}
    for name, (data, options) in files.items():
        record = photo_provenance(data, attached, **options)
        cases[name] = {
            "b64": base64.b64encode(data).decode("ascii"),
            "options": options,
            "record": record,
            "shown": describe_provenance(record),
        }
    photo = {"b64": cases["fixture"]["b64"]}
    gate = {
        "none": {},
        "one": {"supervision": {"evidence": {"des-backfill-placed-6": photo}}},
        "all": {"supervision": {"evidence": {
            key: photo for key in ("des-casing-screen-assemblage",
                                   "des-backfill-placed-6",
                                   "dev-borehole-disinfected-chlorine")}}},
        "na": {"supervision": {"responses": {
            "des-casing-screen-assemblage": {"status": "na"},
            "des-backfill-placed-6": {"status": "na"},
            "dev-borehole-disinfected-chlorine": {"status": "na"}}}},
    }
    return {
        "attached_at": attached,
        "cases": cases,
        "no_record": describe_provenance(None),
        "gate": {
            name: [[r.key, r.state, r.detail]
                   for r in assess_readiness(state, "supervision").requirements]
            for name, state in gate.items()
        },
        "gate_states": gate,
    }


# ------------------------------------------------------------- the field kit

# The kit for three projects: the plain one; one named by its reference only,
# with a wider casing, a shorter minimum test and another depth rule; and one
# with no name at all and a riser as wide as the casing, which leaves no
# casing storage to state. Every word, number and sheet code is compared.
FIELD_KIT_CASES = [
    {"site": {"project": "Rokel 2026", "project_ref": "", "community": "Kuntolo",
              "client": "Living Water International", "district": "Port Loko",
              "supervisor": "WiNGiN"},
     "boreholes": ["KTL-01", "KTL|02 %x", " KTL-01 ", "", "BH\t 3\n"],
     "config": {}},
    {"site": {"project": "Ignored", "project_ref": " LWI/2026/07 ",
              "community": "Rokel", "client": "", "district": "", "supervisor": ""},
     "boreholes": ["RK-1"],
     "config": {"pumping": {"casing_diameter_in": 6.0, "riser_diameter_in": 1.5,
                            "min_constant_test_min": 120.0,
                            "min_step_length_min": 100.0},
                "ves": {"depth_of_investigation_factor": 0.3}}},
    {"site": {"project": "", "project_ref": "", "community": "", "client": "",
              "district": "", "supervisor": ""},
     "boreholes": ["\u00d8-1 K\u0254n\u0254"],
     "config": {"pumping": {"casing_diameter_in": 1.25, "riser_diameter_in": 1.25}}},
]

# sheet codes to read: the kit's own, and texts that are not one
FIELD_KIT_CODES = [
    "GWT-FK/1|pumping|Rokel 2026|KTL-01",
    "GWT-FK/1|pumping|A%7CB%25C|%2541",
    "  GWT-FK/1|pumping||RK-1\n",
    "GWT-FK/2|pumping|Rokel 2026|KTL-01",
    "GWT-FK/1|pumping|Rokel 2026",
    "GWT-FK/1||Rokel 2026|KTL-01",
    "BOREHOLE SL-WAR-8FEEVKQ-T",
    # trimmed of the six ASCII spaces only, which str.strip() and
    # String.trim() are not: a byte-order mark and U+0085 are kept
    "\ufeffGWT-FK/1|pumping|P|B",
    "GWT-FK/1|pumping|P|B\u0085",
]

# names to make codes of, with the characters str.strip() and String.trim()
# disagree about, unicode, the escapes, and runs of spaces
FIELD_KIT_NAMES = [
    ["\ufeffRokel", "BH-1\ufeff"],
    ["x\u0085", "\u001cFS\u001f"],
    ["\u00a0K\u0254n\u0254\u00a0", "\u3000\u00d8-1 \U0001f4a7\u2028"],
    ["A|B%C%7C%25", " %7c|| "],
    ["line 1\r\nline 2", "\t\vBH\f 3 "],
]


def field_kit_reference() -> dict:
    from dataclasses import asdict

    from groundwater import field_kit as fk
    from groundwater import qr
    from groundwater.config import Config

    def config_for(overrides: dict) -> Config:
        config = Config()
        for section, values in overrides.items():
            for key, value in values.items():
                setattr(getattr(config, section), key, value)
        return config

    content = []
    for case in FIELD_KIT_CASES:
        config = config_for(case["config"])
        site = SiteMetadata(**case["site"])
        content.append(fk.field_kit_content(site, case["boreholes"], config))
    plans = [fk.ves_survey_plan(depth, config_for(case["config"]).ves)
             for depth in (0.4, 30, 62.5, 250, 400)
             for case in FIELD_KIT_CASES[:2]]
    return {
        "cases": FIELD_KIT_CASES,
        "content": content,
        "codes": FIELD_KIT_CODES,
        "parsed": [asdict(p) if (p := fk.parse_field_kit_payload(text)) else None
                   for text in FIELD_KIT_CODES],
        "names": FIELD_KIT_NAMES,
        "payloads": [fk.field_kit_payload(project, borehole)
                     for project, borehole in FIELD_KIT_NAMES],
        "minutes": {str(until): fk.reading_minutes(until)
                    for until in (0.4, 60, 120, 121, 240, 330)},
        "plans": plans,
        # every module of the first kit's printed symbols, at the level the
        # sheets print them
        "symbols": [["".join("1" if cell else "0" for cell in row)
                     for row in qr.encode(sheet["payload"], ecc="H").modules]
                    for sheet in content[0]["sheets"]],
    }


# ------------------------------------------------- pumping sheets at the edges

def _pumping_case_grids() -> dict[str, list[list]]:
    """The bundled pumping sheets with the cells rewritten that each
    hydraulics defect turned on: a recovery line that misses the origin, a
    level below the pump, a hole too shallow for the intake the test implies,
    hourly blocks read every few minutes, step times that restart, short
    steps inside the casing-storage period. Row 4 carries the borehole depth
    and row 5 the static level and pump setting in column 4 and 1; row 8 the
    step discharges; row 9 the block headings; readings start on row 11."""
    from groundwater.ingestion import common

    def grid_of(path):
        grid, _ = common.load_grid(path)
        return json.loads(json.dumps(grid, default=str))

    def copy(grid):
        return json.loads(json.dumps(grid))

    def clear_readings(grid):
        for row in grid[11:]:
            for c in range(15):
                row[c] = None

    timbo = grid_of(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    kuntolo = grid_of(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    swl = 9.44
    cases: dict[str, list[list]] = {}

    # the recovery on a clean line meeting t/t' = 1 at 20 m, beside fits that
    # are all disqualified; then with too few readings for any drawdown fit
    rejected = copy(timbo)
    for i, t_prime in enumerate([0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45,
                                 50, 55, 60]):
        rejected[11 + i][13] = (42.26 if t_prime == 0 else round(
            swl + 20.0 + 9.0 * math.log10((30 + t_prime) / t_prime), 2))
    cases["rejected_recovery"] = rejected
    alone = copy(rejected)
    for row in alone[15:]:
        row[0] = row[1] = row[2] = None
    cases["every_fit_rejected"] = alone

    # the recovery line meeting t/t' = 1 below zero
    negative = copy(timbo)
    for i, t_prime in enumerate([0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45,
                                 50, 55, 60]):
        negative[11 + i][13] = (42.26 if t_prime == 0 else round(
            swl - 8.0 + 20.0 * math.log10((30 + t_prime) / t_prime), 2))
    cases["negative_intercept"] = negative

    # the pump written at 15 m, 27 m above the deepest level recorded
    below_pump = copy(timbo)
    below_pump[5][4] = 15
    cases["level_below_pump"] = below_pump

    # a 45.5 m hole with the pump at 44 m
    shallow = copy(timbo)
    shallow[4][4] = 45.5
    shallow[5][4] = 44
    cases["shallow_hole"] = shallow

    # four hours in hourly blocks, hours two to four read every 5, 10 and 15
    # minutes and counted within the hour
    blocks = copy(timbo)
    clear_readings(blocks)
    for b, (start, times) in enumerate([
            (0, [0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 40, 50, 60]),
            (60, [5, 10, 15, 20, 25, 30, 40, 50, 60]),
            (120, [10, 20, 30, 40, 50, 60]), (180, [15, 30, 45, 60])]):
        for i, t in enumerate(times):
            blocks[11 + i][3 * b] = t
            blocks[11 + i][3 * b + 1] = round(
                swl + (0 if start + t == 0 else 3.0 * math.log10(start + t) + 5.0), 2)
    cases["blocks_by_heading"] = blocks

    # Kuntolo with its discharges, each step's time counted from its own start
    restart = copy(kuntolo)
    restart[8][2], restart[8][5], restart[8][8] = 1.5, 2.2, 3.0
    for row in restart[11:]:
        for col, offset in ((3, 60), (6, 120)):
            if isinstance(row[col], (int, float)):
                row[col] = row[col] - offset
    cases["step_restart"] = restart

    # three 50-minute steps, every one inside an 80-minute casing storage
    short = copy(kuntolo)
    short[2][4] = 50
    short[5][1] = 10.0
    short[8][2], short[8][5], short[8][8] = 1.0, 2.0, 3.0
    clear_readings(short)
    rates = [1.0, 2.0, 3.0]

    def drawdown(t):
        s = 0.0
        for i, q in enumerate(rates):
            if t > 50 * i:
                dq = q - (rates[i - 1] if i else 0.0)
                s += 2.303 * dq * 24 / (4 * math.pi * 2.5) * math.log10(
                    2.25 * 2.5 * ((t - 50 * i) / 1440) / (0.01 * 1e-3))
        q = rates[min(int((t - 1e-9) // 50), 2)]
        return s + 0.002 * (q * 24) ** 2 / 24

    for k in range(3):
        for i, t in enumerate([1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50]):
            short[11 + i][3 * k] = 50 * k + t
            short[11 + i][3 * k + 1] = round(10.0 + drawdown(50 * k + t), 2)
    cases["short_steps"] = short
    return cases


def pumping_cases() -> dict:
    """What Python makes of each edge sheet, with the sheet itself.

    The grid travels as a JSON string so the browser parses exactly the cells
    Python parsed; the rest is compared quantity by quantity, the prose word
    for word."""
    from groundwater.ingestion.pumping import _assemble
    from groundwater.models import step_offsets_min

    out = {}
    for name, grid in _pumping_case_grids().items():
        test = _assemble(grid, f"{name}.xlsx")
        analysis = analyse_pumping_test(test)
        rec = analysis.yield_recommendation
        out[name] = {
            "grid": json.dumps(grid),
            "steps": [[s.step_number, clean(s.discharge_m3_per_h), len(s.time_min),
                       clean(float(np.min(s.time_min))), clean(float(np.max(s.time_min)))]
                      for s in test.steps],
            "duration": clean(test.pumping_duration_min),
            "offsets": step_offsets_min(test.steps),
            "source": analysis.transmissivity_source,
            "qualifies": analysis.adopted_fit()[2],
            "disqualified": sorted(analysis.disqualified),
            "invalid": sorted(analysis.invalid_fits),
            "T": clean(analysis.transmissivity_m2_per_day),
            "safe": clean(rec.safe_yield_m3_per_h),
            "range_text": rec.yield_range_text,
            "pump_depth": clean(rec.pump_installation_depth_m),
            "confidence": rec.confidence,
            "confidence_reasons": list(rec.confidence_reasons),
            "pending_reason": rec.pending_reason,
            "pump_depth_basis": rec.pump_depth_basis,
            "envelope_basis": rec.envelope_basis,
            "rec_pumping_time": clean(analysis.recovery.pumping_time_min)
                                if analysis.recovery else None,
            "step_numbers": [s["step"] for s in analysis.step_test.steps]
                            if analysis.step_test else None,
            "flags": flags(analysis.flags),
        }
    return out


# ------------------------------------------------------ where a report is set

#: Positions the regional checks place a site at: the Rokel sounding on the
#: Bullom sands, the Freetown Complex under a sheet that says Port Loko, a
#: dyke the Precambrian encloses in Kono, Kamakwie in Karene, the interior,
#: and a point in the Falaba chiefdoms the boundary layer predates.
_REGIONAL_POSITIONS = [
    (8.375866051953114, -13.102371011661704, "Western Area"),
    (8.40, -13.18, "Port Loko"),
    (9.392, -10.396, "Kono"),
    (9.4967, -12.2405, "Karene"),
    (7.96, -11.74, "Bo"),
    (9.85, -11.3, "Falaba"),
    (8.35, -13.10, "Western Area"),
    (8.77, -12.79, "Port Loko District"),
]

#: District names as sheets write them: the region, a trailing "District",
#: the two districts the boundary layer predates, lower case, a name that
#: could be two districts, and one that is no district at all.
_REGIONAL_DISTRICTS = ["Karene", "Falaba", "Western Area", "Port Loko District",
                       "western area rural", "Ko", "Atlantis", ""]


def regional_reference() -> dict:
    """The area each report maps, what it is called, and the ground under it.

    Every chiefdom and district window is here, because the browser sized
    them from the largest ring alone and 41 of the 180 came out more than a
    tenth different, which the scale caveat then quoted in the client's
    copy of the report.
    """
    from groundwater.geo import parse_utm_zone
    from groundwater.mapping.regional import (
        _BGS_PUBLISHER_NOTE,
        _home_district,
        _scale_caveat,
        area_window,
        load_admin,
        load_chiefdoms,
    )
    from groundwater.reporting.context import area_map_note
    from groundwater.reporting.geophysical import _geology_for

    _, districts = load_admin()

    def window(site):
        found = area_window(site)
        if found is None:
            return None
        return clean([found.lon, found.lat, found.radius_km, found.label,
                      found.exact])

    def placed(lat, lon, district, community="T"):
        utm = geographic_to_utm(lat, lon)
        return SiteMetadata(community=community, district=district,
                            easting=utm.easting, northing=utm.northing,
                            utm_zone=utm.zone)

    cases = ([{"chiefdom": area.name, "district": ""} for area in load_chiefdoms()]
             + [{"chiefdom": "", "district": area.name} for area in districts]
             + [{"chiefdom": "", "district": name} for name in _REGIONAL_DISTRICTS]
             + [{"chiefdom": name, "district": "Port Loko"}
                for name in ("Bureh Kasseh Maconteh", "Bureh Kasseh Ma",
                             "sanda magbolontor")])
    windows = []
    for case in cases:
        site = SiteMetadata(community="T", **case)
        name, names, chiefdoms = _home_district(site, districts)
        windows.append(dict(case, window=window(site), note=area_map_note(site),
                            home=[name, sorted(names),
                                  sorted(area.name for area in chiefdoms)]))

    positions = []
    for lat, lon, district in _REGIONAL_POSITIONS:
        site = placed(lat, lon, district)
        # the position the site actually carries, after the round trip
        # through UTM, so the browser is handed the same point
        at_lat, at_lon = site.latlon
        name, names, chiefdoms = _home_district(site, districts)
        positions.append({
            "district": district, "lat": clean(at_lat), "lon": clean(at_lon),
            "window": window(site), "note": area_map_note(site),
            "home": [name, sorted(names), sorted(area.name for area in chiefdoms)],
            "geology": _geology_for(site, ""),
        })
    unplaced = [{"district": district,
                 "geology": _geology_for(SiteMetadata(district=district), "")}
                for district in ("Western Area", "Western Area Rural", "Bo", "")]

    return {
        "windows": windows,
        "positions": positions,
        "unplaced_geology": unplaced,
        "caveats": [
            {"radius_km": radius, "note": note,
             "text": _scale_caveat(radius, 5_000_000, note)}
            for radius, note in ((None, ""), (21.71465, ""), (30.0, ""),
                                 (42.5, _BGS_PUBLISHER_NOTE), (60.0, ""),
                                 (60.5, ""), (6.25, ""))
        ],
        "utm_zones": [
            {"value": value, "zone": parse_utm_zone(value)}
            for value in ("28N", "Zone 28", "29 N", "28N WGS84",
                          "WGS 84 / UTM zone 28N", "WGS-84 29N", "28.0", 28,
                          28.0, 28.5, "708958", "UTM Zone (28N or 29N)", "",
                          "zone 61", "0")
        ],
    }



# ------------------------------------------------ the survey's own figures

#: The spacings of the synthetic soundings below. Their readings are a plain
#: ramp: nothing here reads them but the pseudo-section's station order.
_SURVEY_AB2 = [1, 1.5, 2, 3, 4, 6, 8, 10, 15, 20, 25, 32, 40, 50, 65, 80, 100.0]
_E, _N = 178000.0, 1000000.0

#: Each case is a list of stations: (id, easting, northing, elevation,
#: resistivities, thicknesses). parity.mjs builds the same surveys.
SURVEY_CASES = {
    # the best point (VES 3) carries no position
    "nopos": [
        ("VES 1", _E, _N, 70.0, [320, 150, 4200], [2.5, 6]),
        ("VES 2", _E + 80, _N + 40, 72.0, [320, 160, 4200], [2.5, 5]),
        ("VES 3", None, None, None, [320, 60, 4200], [2.5, 20]),
    ],
    "noposall": [
        ("VES 1", None, None, None, [320, 150, 4200], [2.5, 6]),
        ("VES 2", None, None, None, [320, 60, 4200], [2.5, 20]),
    ],
    # 75.3 against 71.5: a tie on a five-point margin, not on three
    "margin": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 80, _N + 40, 72.0, [320, 60, 4200], [2.5, 11]),
    ],
    # 75.3 and 75.3, with a third point elsewhere
    "tie": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 80, _N + 40, 72.0, [320, 60, 4200], [2.5, 16]),
        ("VES 3", _E + 30, _N + 120, 71.0, [320, 400, 4200], [2.5, 4]),
    ],
    # levels missing at two of four stations
    "levels": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 100, _N, None, [320, 60, 4200], [2.5, 16]),
        ("VES 3", _E + 200, _N, None, [320, 60, 4200], [2.5, 16]),
        ("VES 4", _E + 300, _N, 64.0, [320, 60, 4200], [2.5, 16]),
    ],
    # a gap wider than ten depths of investigation between VES 2 and VES 3
    "gap": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 100, _N, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E + 5000, _N, 64.0, [320, 60, 4200], [2.5, 12]),
    ],
    # Rokel's two pegs, 20.7 km apart and neither reaching basement
    "far": [
        ("A (1)", 708958.0, 926355.0, 71.0, [320, 60], [2.5]),
        ("B (2)", 727012.0, 916125.0, 68.0, [320, 70], [3.0]),
    ],
    "onepoint": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E, _N, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E, _N, 72.0, [320, 60, 4200], [2.5, 12]),
    ],
    "shared": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E, _N, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E + 100, _N + 30, 72.0, [320, 60, 4200], [2.5, 12]),
    ],
    # two soundings both called VES 1
    "sameid": [
        ("VES 1", _E, _N, 70.0, [320, 150, 4200], [2.5, 5]),
        ("VES 1", _E + 100, _N, 71.0, [320, 60, 4200], [2.5, 15]),
        ("VES 2", _E + 200, _N, 72.0, [320, 160, 4200], [2.5, 5]),
    ],
    "collinear": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 16]),
        ("VES 2", _E + 100, _N, 71.0, [320, 60, 4200], [2.5, 14]),
        ("VES 3", _E + 200, _N, 72.0, [320, 60, 4200], [2.5, 12]),
    ],
    # every water zone open below the depth of investigation
    "open": [
        ("VES 1", _E, _N, 70.0, [320, 60], [2.5]),
        ("VES 2", _E + 100, _N + 30, 71.0, [320, 70], [3.0]),
        ("VES 3", _E + 40, _N + 120, 72.0, [320, 65], [2.0]),
    ],
    # one of three open
    "someopen": [
        ("VES 1", _E, _N, 70.0, [320, 60], [2.5]),
        ("VES 2", _E + 100, _N + 30, 71.0, [320, 70, 4200], [3.0, 14]),
        ("VES 3", _E + 40, _N + 120, 72.0, [320, 65, 4200], [2.0, 18]),
    ],
    # a basement at 61 m under a 50 m depth of investigation
    "deepbase": [
        ("VES 1", _E, _N, 70.0, [320, 60, 4200], [2.5, 58.5]),
        ("VES 2", _E + 100, _N + 30, 71.0, [320, 60, 4200], [2.5, 16]),
    ],
}


def _zone_straddle():
    """Three soundings either side of 12 W, each recorded in its own zone."""
    stations = []
    for k, lon in enumerate((-12.0036, -11.9964, -11.995)):
        utm = geographic_to_utm(8.9, lon)
        stations.append((f"VES {k + 1}", utm.easting, utm.northing, 30.0 + k,
                         [320, 55 + 9 * k, 4200], [2.5 + 0.4 * k, 14 + 5.5 * k]))
    return stations


def _survey(stations, array_type="schlumberger"):
    from groundwater.models import LayeredModel, VESSounding

    soundings, interps = [], []
    for sid, e, n, z, rho, h in stations:
        site = SiteMetadata(community="Kuntolo", district="Bombali",
                            easting=e, northing=n, elevation_m=z)
        ab2 = np.array(_SURVEY_AB2)
        sounding = VESSounding(
            site=site, sounding_id=sid, ab2=ab2, mn=np.full(ab2.size, 0.5),
            rho_app=100.0 + 10.0 * np.arange(ab2.size), array_type=array_type)
        model = LayeredModel(resistivities=np.array(rho, float),
                             thicknesses=np.array(h, float), sounding_id=sid,
                             fit_error_percent=0.5)
        soundings.append(sounding)
        interps.append(interpret_model(sounding, model))
    return soundings, interps


def survey_figures_reference(rokel_interps) -> dict:
    """What the survey's own figures say, case by case.

    The maps and sections are drawn by different code in each engine, but
    what they claim is decided once: which point is starred, whether two
    points tie, which figures are refused and why, the chainages, the zone
    everything is drawn in and the captions. No parity check read any of
    it, and the browser's suitability map, section and ground profile drifted
    from the package's without a failing test.
    """
    from groundwater.config import VESConfig
    from groundwater.mapping import (
        ground_profile_state,
        spacing_name,
        suitability_map_state,
        survey_zone,
        traverse_profile,
    )
    from groundwater.mapping.maps import (
        interpolated_label,
        points_enclose_an_area,
        suitability_label,
        suitability_map_note,
    )
    from groundwater.mapping.subsurface import spacing_note
    from groundwater.reporting.geophysical import (
        _SUBSURFACE_MAPS,
        _drawn_depth_text,
        _ground_profile_caption,
        _pseudosection_caption,
        _study_area_caption,
        _subsurface_caption,
        _subsurface_points,
        _suitability_caption,
    )
    from groundwater.siting import ranking_tie, suitability_map_points
    from groundwater.ves.plots import model_depth_m

    def refusal(fn):
        try:
            fn()
        except ValueError as exc:
            return str(exc)
        return None

    def suitability(interps, tie_points=3.0):
        cfg = VESConfig(ranking_tie_points=tie_points)
        suit = assess_siting(interps, cfg)
        tie = bool(ranking_tie(suit, within_points=cfg.ranking_tie_points))
        zone = survey_zone(interps)
        points = suitability_map_points(suit, zone)
        ranking = [s.sounding_id for s in suit]
        state = suitability_map_state(points, tie=tie, ranking=ranking)
        marked = [i.sounding_id for i in interps if i.site_easting is not None]
        return {
            "state": clean(state),
            "caption": _suitability_caption(state) if points else None,
            "note": suitability_map_note(state),
            "labels": [suitability_label(p, p.rank == 1 and not state["tie"])
                       for p in points],
            "compact_labels": [
                suitability_label(p, p.rank == 1 and not state["tie"], compact=True)
                for p in points],
            "eastings": [clean(p.easting) for p in points],
            "zone": zone,
            "study_area": _study_area_caption(
                "Kuntolo", marked, ranking[0], ranking[:2], tie),
        }

    def maps(interps):
        zone = survey_zone(interps) or 28
        out = {}
        for fn, key, _name, what in _SUBSURFACE_MAPS:
            reason = refusal(lambda fn=fn: plt_close(fn(interps, zone)))
            entry = {"reason": reason}
            if reason is None:
                points = _subsurface_points(key, interps, zone)
                surface = len(points) >= 3 and points_enclose_an_area(
                    [p.easting for p in points], [p.northing for p in points])
                entry["caption"] = _subsurface_caption(what, points)[0]
                entry["minimum"] = [p.minimum for p in points]
                if key != "protective_capacity":
                    entry["labels"] = [interpolated_label(p, surface) for p in points]
            out[key] = entry
        return out

    def traverse(interps):
        try:
            profile = traverse_profile(interps)
        except ValueError as exc:
            return {"reason": str(exc)}
        return {
            "reason": None,
            "labels": list(profile.labels),
            "chainage_m": clean(profile.chainage_m),
            "indices": list(profile.indices),
            "length_m": clean(profile.length_m),
            "bearing_deg": clean(profile.bearing_deg),
            # the model each station takes, by position in the list
            "layer2_rho": [clean(interps[k].model.resistivities[1])
                           for k in profile.indices],
        }

    def ground(interps):
        levelled = [i for i in interps if i.site_easting is not None
                    and i.site_northing is not None and i.site_elevation_m is not None]
        if len(levelled) < 2:
            # the report says nothing: there is no profile to be missing
            return {"reason": None, "silent": True}
        try:
            state = ground_profile_state(interps)
        except ValueError as exc:
            return {"reason": str(exc)}
        if state["reason"]:
            return {"reason": state["reason"]}
        return {
            "reason": None,
            "caption": _ground_profile_caption(state),
            "chainage_m": clean(state["chainage_m"]),
            "open_gaps": clean(state["open_gaps"]),
            "max_gap_m": clean(state["max_gap_m"]),
        }

    cases = dict(SURVEY_CASES, zones=_zone_straddle())
    # the stations travel with the answers, so the browser builds the very
    # same surveys rather than a copy of them typed out again
    out: dict = {"cases": {}, "inputs": clean(cases), "ab2": _SURVEY_AB2}
    for name, stations in cases.items():
        soundings, interps = _survey(stations)
        entry = {
            "suitability": suitability(interps),
            "traverse": traverse(interps),
            "ground": ground(interps),
            "maps": maps(interps),
            "model_depth": [clean(model_depth_m(i.model, i.investigation_depth_m))
                            for i in interps],
            "drawn_depth": [_drawn_depth_text(i.model, i) for i in interps],
        }
        if name == "margin":
            entry["suitability_margin5"] = suitability(interps, tie_points=5.0)
        out["cases"][name] = entry
    # a Wenner survey: the spacing is a, not AB/2
    wenner, interps = _survey(SURVEY_CASES["collinear"], array_type="wenner")
    profile = traverse_profile(interps)
    spacing = spacing_name(wenner)
    out["wenner"] = {
        "spacing": spacing,
        "note": spacing_note(spacing),
        "caption": _pseudosection_caption(spacing, profile),
    }
    out["rokel_drawn_depth"] = [_drawn_depth_text(i.model, i) for i in rokel_interps]
    return out


def plt_close(fig):
    """Close a figure a map function returned rather than saved."""
    import matplotlib.pyplot as plt

    plt.close(fig)


# ------------------------------------------------- the unruled PDF field sheet

#: A typed VES sheet, placed with Tm/Tj and with no ruling line anywhere on
#: the page. Both readers find its table from word positions, so this is the
#: one fixture where the two have to agree byte for byte on the same input -
#: the bytes travel in the reference file and are decoded in the browser.
_PDF_ROWS = [[1, 1.5, 0.5, 210.4], [2, 2, 0.5, 233.1], [3, 3, 0.5, 268.0],
             [4, 4, 0.5, 291.7], [5, 6, 0.5, 302.5], [6, 8, 0.5, 288.2],
             [7, 10, 0.5, 264.9], [8, 15, 0.5, 198.3]]

_PDF_HEADER = [
    (60, 760, "SCHLUMBERGER ARRAY VES FIELD DATA"),
    (60, 735, "Community: Rokel"), (300, 735, "Client: Living Water International"),
    (60, 715, "District: Port Loko"), (300, 715, "Sounding Number: VES A-1"),
    (60, 695, "Date: 2023-05-14"), (300, 695, "Field Supervisor: M. Kolleh"),
    (60, 650, "No."), (110, 650, "AB/2 (m)"), (200, 650, "MN (m)"),
    (280, 650, "Apparent Resistivity (ohm-m)"),
]


def _typed_field_sheet_pdf() -> bytes:
    placed = list(_PDF_HEADER)
    for i, row in enumerate(_PDF_ROWS):
        y = 630 - i * 18
        for x, value in zip((60, 110, 200, 280), row, strict=True):
            placed.append((x, y, str(value)))

    ops = ["BT", "/F1 10 Tf"]
    for x, y, text in placed:
        escaped = str(text).replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(f"1 0 0 1 {x} {y} Tm ({escaped}) Tj")
    ops.append("ET")
    # level 9 and no timestamp, so the same table always gives the same bytes
    content = zlib.compress("\n".join(ops).encode("latin-1"), 9)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"),
        b"<< /Length 6 0 R /Filter /FlateDecode >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        str(len(content)).encode(),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def pdf_sheet_reference() -> dict:
    """What the Python reader makes of the sheet, plus the sheet itself."""
    from groundwater.extraction.pdf_text import extract_pdf_text

    pdf = _typed_field_sheet_pdf()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ves_sheet.pdf"
        path.write_bytes(pdf)
        document = extract_pdf_text(path)

    return {
        "b64": base64.b64encode(pdf).decode("ascii"),
        "kind": document.document_kind,
        "header": [[f.name, f.value] for f in document.header],
        "tables": [{"columns": list(t.columns), "rows": [list(r) for r in t.rows]}
                   for t in document.tables],
        "uncertain": len(document.uncertain_cells),
    }


# Loose enough to absorb a different BLAS build, tight enough that a real
# change in any reported quantity fails: 1e-6 relative is a millionth of a
# metre on a screen depth and a millionth of a percent on a fit error.
CHECK_RTOL = 1e-6


def drifted(fresh, committed, path="", rtol=CHECK_RTOL, atol=1e-12):
    """Yield ``(path, fresh, committed)`` for every value that really differs.

    The defaults are for --check, the toolkit against its own committed
    values. tests/fuzz compares the two engines with the same walk at the
    tolerances parity.mjs holds each kind of quantity to.
    """
    if isinstance(fresh, dict) and isinstance(committed, dict):
        for key in sorted(set(fresh) | set(committed)):
            if key not in fresh or key not in committed:
                yield (f"{path}.{key}", fresh.get(key, "<missing>"),
                       committed.get(key, "<missing>"))
                continue
            yield from drifted(fresh[key], committed[key], f"{path}.{key}", rtol, atol)
    elif isinstance(fresh, list) and isinstance(committed, list):
        if len(fresh) != len(committed):
            yield (f"{path}[]", f"{len(fresh)} items", f"{len(committed)} items")
            return
        for i, (a, b) in enumerate(zip(fresh, committed, strict=True)):
            yield from drifted(a, b, f"{path}[{i}]", rtol, atol)
    elif isinstance(fresh, (int, float)) and isinstance(committed, (int, float)):
        if isinstance(fresh, bool) or isinstance(committed, bool):
            if fresh != committed:
                yield (path, fresh, committed)
        elif not math.isclose(fresh, committed, rel_tol=rtol, abs_tol=atol):
            yield (path, fresh, committed)
    elif fresh != committed:
        yield (path, fresh, committed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="compare the committed file against a fresh run instead of "
             "rewriting it; exit non-zero if anything really moved",
    )
    args = parser.parse_args()
    fresh = build()

    if not args.check:
        OUT.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {OUT}")
        return 0

    if not OUT.exists():
        print(f"{OUT} is missing; run this without --check to create it")
        return 1
    committed = json.loads(OUT.read_text(encoding="utf-8"))
    differences = [d for d in drifted(fresh, committed)
                   if not range_tolerated(*d) and not pc_tolerated(*d, committed)]
    if not differences:
        print(f"{OUT} agrees with this toolkit to {CHECK_RTOL:g} relative "
              "(the range of models to RANGE_RTOL, a badly fitting large-diameter "
              "fit to PC_RTOL)")
        return 0
    print(f"{OUT} disagrees with this toolkit in {len(differences)} place(s):")
    for path, a, b in differences[:20]:
        print(f"  {path.lstrip('.')}: fresh {a!r} vs committed {b!r}")
    print("\nIf the change is intended, regenerate with:\n"
          "  python tests/webapp/make_reference.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())

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
import hashlib
import json
import math
import re
import struct
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
from groundwater.geotiff import (
    GeoTiffError,
    _CodecError,
    _inflate_block,
    block_ranges,
    decode_block,
    geotiff_layout,
    read_geotiff,
)
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
    # a stainless rising main (PLAN.md step 7.2): one taken as long as the
    # hole is as long as each depth drawn, one over the intake stays put
    "stainless main as long as the hole, depth drawn": dict(
        inputs={"total_depth_m": 36.0, "mobilisation_distance_km": 60.0,
                "rising_main_material": "stainless steel"}, depth=True, p=0.5, sid="A (1)"),
    "stainless main over the intake, depth drawn": dict(
        inputs={"total_depth_m": 36.0, "mobilisation_distance_km": 60.0,
                "rising_main_material": "stainless steel", "rising_main_m": 24.0},
        depth=True),
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
    "ten with a stainless main, depth drawn": dict(
        inputs={"total_depth_m": 40.0, "mobilisation_distance_km": 100.0,
                "rising_main_material": "stainless steel"}, n=10, rate=60.0, depth=True),
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


# --------------------------------------- one way of reporting uncertainty (3.6)
#
# Every decision number is built from results the other sections already
# hold the two engines to, so here both are handed the same results, as the
# dicts the browser holds and as namespaces Python reads attributes from,
# and every line is compared word for word. The depth is drawn from the
# hand-built quantiles the cost section uses, not the Rokel ranges, whose
# short runs move a few parts in a million with the BLAS build.

def _ns(value):
    """A dict as the attributes Python's decision numbers read, all the way
    down; lists element by element."""
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_ns(v) for v in value]
    return value


def _decision_dict(d) -> dict | None:
    from groundwater.decisions import decision_text

    if d is None:
        return None
    return dict(dataclasses.asdict(d), text=decision_text(d))


#: Hand-built pumping results: a band, one open at the top, a bootstrap
#: withheld, a low end with no yield, no spread at all, and no intake.
DECISION_PUMPING = {
    "banded": {"transmissivity_source": "cooper_jacob",
               "yield_recommendation": {"safe_yield_m3_per_h": 1.25,
                                        "pump_installation_depth_m": 38.4},
               "spread": {"bootstrap": {"method": "cooper_jacob", "p10": 4.1, "reason": ""},
                          "safe_yield_low_m3_per_h": 1.02, "safe_yield_high_m3_per_h": 1.61,
                          "pump_depth_low_m": 37.2, "pump_depth_high_m": 40.1}},
    "open top": {"transmissivity_source": "theis",
                 "yield_recommendation": {"safe_yield_m3_per_h": 0.391,
                                          "pump_installation_depth_m": 52.0},
                 "spread": {"bootstrap": {"method": "theis", "p10": 0.48, "reason": ""},
                            "safe_yield_low_m3_per_h": 0.354, "safe_yield_high_m3_per_h": None,
                            "pump_depth_low_m": 51.0, "pump_depth_high_m": 52.0}},
    "withheld": {"transmissivity_source": "recovery",
                 "yield_recommendation": {"safe_yield_m3_per_h": 3.0,
                                          "pump_installation_depth_m": 25.0},
                 "spread": {"bootstrap": {"method": "recovery", "p10": None,
                                          "reason": "too_few"},
                            "safe_yield_low_m3_per_h": None, "safe_yield_high_m3_per_h": None,
                            "pump_depth_low_m": None, "pump_depth_high_m": None}},
    "no low end": {"transmissivity_source": "papadopulos_cooper",
                   "yield_recommendation": {"safe_yield_m3_per_h": 0.2,
                                            "pump_installation_depth_m": 61.5},
                   "spread": {"bootstrap": {"method": "papadopulos_cooper", "p10": 0.1,
                                            "reason": ""},
                              "safe_yield_low_m3_per_h": None,
                              "safe_yield_high_m3_per_h": 0.3,
                              "pump_depth_low_m": 60.0, "pump_depth_high_m": 63.0}},
    "no spread": {"transmissivity_source": "cooper_jacob",
                  "yield_recommendation": {"safe_yield_m3_per_h": 2.0,
                                           "pump_installation_depth_m": 30.0},
                  "spread": None},
    "no intake": {"transmissivity_source": "cooper_jacob",
                  "yield_recommendation": {"safe_yield_m3_per_h": 2.0,
                                           "pump_installation_depth_m": None},
                  "spread": None},
    "pending": {"transmissivity_source": None,
                "yield_recommendation": {"safe_yield_m3_per_h": None,
                                         "pump_installation_depth_m": None},
                "spread": None},
}


def decisions_reference(odds: dict, cost_range: dict) -> dict:
    from groundwater.decisions import (
        DecisionNumber, cost_decision, decision_numbers, decision_text, depth_decision,
        odds_decision, pump_decision, yield_decision,
    )
    from groundwater.readiness import assess_readiness

    fmt = [DecisionNumber("yield", "Safe yield", "1.25 m3/h", "a band", "", "a basis"),
           DecisionNumber("odds", "Chance", "about 60 percent", None, "no reason given",
                          "a basis", "calibrated")]
    # a range shaped like Rokel A's, one cut back to its depth of
    # investigation everywhere, and none
    ranges = {
        "drawn": {"sounding_id": "P1", "n_samples": 4000, "investigation_depth_m": 41.0,
                  "drilling_depth_quantiles_m": COST_DEPTH["quantiles_m"]},
        "capped": {"sounding_id": "P2", "n_samples": 1200, "investigation_depth_m": 40.0,
                   "drilling_depth_quantiles_m": [40.0] * 21},
        # spread so that the twentieths beside the P10 and the P90 round to
        # other drilling steps: the band is read at the right ones
        "spread": {"sounding_id": "P3", "n_samples": 2000, "investigation_depth_m": 60.0,
                   "drilling_depth_quantiles_m": [10.0, 12.0, 16.0, 21.0, 23.0, 24.0, 25.0,
                                                  26.0, 27.0, 28.0, 29.0, 30.0, 31.0, 32.0,
                                                  33.0, 34.0, 36.0, 39.0, 44.0, 48.0, 52.0]},
        "none": None,
    }
    interps = {
        "P1": {"sounding_id": "P1", "max_drilling_depth_m": 33.0, "basement_not_resolved": False,
               "drilling_depth_capped": False, "rank": 2},
        "P2": {"sounding_id": "P2", "max_drilling_depth_m": 40.0, "basement_not_resolved": True,
               "drilling_depth_capped": True, "rank": 1},
    }
    depth = []
    for interp in interps.values():
        for name, r in ranges.items():
            d = depth_decision(_ns(interp), _ns(r), Config())
            depth.append({"interp": interp, "range": r, "case": name, "d": _decision_dict(d)})
    pumping = []
    for name, a in DECISION_PUMPING.items():
        for at, moved in ((None, None), (44.0, "design"), (55.0, "seasonal"), (38.4, "design")):
            pumping.append({"case": name, "analysis": a, "depth": at, "moved": moved,
                            "yield": _decision_dict(yield_decision(_ns(a))),
                            "pump": _decision_dict(pump_decision(_ns(a), at, moved))})
    odds_cases = [c["odds"] for c in odds["cases"][:6]] + [odds["wider"],
                                                           odds["low_yield"]["odds"]]
    calibrated = dict(odds_cases[0], status="calibrated")
    odds_cases.append(calibrated)
    odds_out = [{"odds": o, "d": _decision_dict(odds_decision(_ns(o)))} for o in odds_cases]
    estimate = {"price_with_vat_usd": 8643.5}
    cost = [{"dist": c["short"]["dist"], "estimate": estimate,
             "d": _decision_dict(cost_decision(_ns(c["short"]["dist"]), _ns(estimate)))}
            for c in cost_range["cases"].values()]
    cost.append({"dist": None, "estimate": estimate,
                 "d": _decision_dict(cost_decision(None, _ns(estimate)))})
    cost.append({"dist": None, "estimate": None, "d": None})

    first_cost = next(iter(cost_range["cases"].values()))["short"]["dist"]
    states = {
        "geophysical, drawn": ("geophysical", {
            "interpretations": list(interps.values()),
            "model_ranges": [ranges["drawn"], ranges["drawn"]],
            "odds": [odds_cases[0], odds_cases[1]]}),
        "geophysical, unsampled": ("geophysical", {
            "interpretations": list(interps.values()), "model_ranges": [None, None],
            "odds": [odds_cases[0], odds_cases[1]]}),
        "geophysical, no odds": ("geophysical", {
            "interpretations": list(interps.values()),
            "model_ranges": [ranges["capped"], ranges["capped"]]}),
        # two points the ranking cannot separate: the report offers both, so
        # it prints and the gate reads the numbers at both, the first-ranked
        # first; the second's range unsampled
        "geophysical, tied": ("geophysical", {
            "interpretations": list(interps.values()),
            "model_ranges": [None, ranges["capped"]],
            "odds": [odds_cases[0], odds_cases[1]], "points": [1, 0]}),
        "geophysical, nothing": ("geophysical", {}),
        "pumping, banded": ("pumping", {"pump_analysis": DECISION_PUMPING["banded"]}),
        "completion, withheld": ("completion", {"pump_analysis": DECISION_PUMPING["withheld"]}),
        "handover, no spread": ("handover", {"pump_analysis": DECISION_PUMPING["no spread"]}),
        "pumping, pending": ("pumping", {"pump_analysis": DECISION_PUMPING["pending"]}),
        "costing, sampled": ("costing", {"cost_distribution": first_cost,
                                         "cost_estimate": estimate}),
        "costing, bill alone": ("costing", {"cost_estimate": estimate}),
        "quality, banded test": ("quality", {"pump_analysis": DECISION_PUMPING["banded"]}),
    }
    numbers, gate = [], []
    for name, (report, state) in states.items():
        # the state's keys stay a dict, as the gate is handed one
        held = {k: _ns(v) for k, v in state.items()}
        numbers.append({"case": name, "report": report, "state": state,
                        "d": [_decision_dict(d)
                              for d in decision_numbers(held, report, Config())]})
        readiness = assess_readiness(held, report)
        req = [[r.state, r.detail] for r in readiness.requirements if r.key == "decision_bands"]
        gate.append({"case": name, "report": report, "state": state, "req": req})
    return {
        "format": [{"d": dataclasses.asdict(d), "text": decision_text(d)} for d in fmt],
        "depth": depth,
        "pumping": pumping,
        "odds": odds_out,
        "cost": cost,
        "numbers": numbers,
        "gate": gate,
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
    out["decisions"] = decisions_reference(out["odds"], out["cost_range"])
    out["ledger"] = ledger_reference(rokel_interps, [sd.site for sd in soundings],
                                     out["ves_range"]["short"],
                                     [r["odds"] for r in out["odds"]["rokel"]])
    out["calibration"] = calibration_reference()
    out["calibration_sets"] = calibration_sets_reference()
    out["calibration_in_force"] = calibration_in_force_reference()
    out["sanitary"] = sanitary_reference()
    out["rising_main"] = rising_main_reference()
    out["rounds"] = rounds_reference()

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
                     ("2023-01-31", 1), ("2023-03-30", 11), ("2024-02-29", 12),
                     # a mistyped year before 1000 is written in four digits
                     ("0024-08-31", 6))
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
                  2.93, 0.0, 0.005, 1e-7,
                  # subnormals, whose shortest form can lie a decade away
                  # from their six-digit one
                  5e-324, 1e-323, 1e-321, 1e-320, 1e-319, 1e-318, 1.000004e-318, -1e-320, 3e-321)
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
    out["inflate"] = inflate_reference()
    out["geotiff"] = geotiff_reference()
    out["elevation_window"] = elevation_window_reference()
    out["terrain"] = terrain_reference()
    out["lineaments"] = lineament_reference()
    out["survey_plan"] = survey_plan_reference()
    out["desk_study"] = desk_study_reference()
    return out


# ------------------------------------------ DEFLATE blocks (PLAN.md step 4.1)

#: The DEFLATE blocks both engines inflate, each with the bytes it has to
#: give and the most it may (tests/webapp/fixtures/make_zlib_streams.py).
#: The committed file is read, never a fresh build: zlib builds differ in the
#: bytes they write, and the reference must not move with them.
ZLIB_STREAMS = OUT.parent / "fixtures" / "zlib_streams.json"


def inflate_reference() -> list:
    """What geotiff._inflate_block makes of each committed block: whether it
    reads, and the SHA-256 and length of what it gives when it does.
    parity.mjs serves the blocks themselves to the page through the
    harness's overlay, so only the answers are kept here."""
    out = []
    for stream in json.loads(ZLIB_STREAMS.read_text(encoding="utf-8")):
        try:
            block = _inflate_block(base64.b64decode(stream["b64"]), stream["expected"], stream["full"])
        except _CodecError as exc:
            out.append({"name": stream["name"], "verdict": exc.code, "sha256": None, "length": None})
            continue
        out.append({"name": stream["name"], "verdict": "accepted",
                    "sha256": hashlib.sha256(block).hexdigest(), "length": len(block)})
    return out


# ------------------------------------------- GeoTIFF reader (PLAN.md step 4.1)

#: The committed GeoTIFF fixtures (tests/webapp/fixtures/make_dem_fixture.py),
#: read where they are committed, never rebuilt: a DEFLATE file rebuilt on
#: another zlib holds other bytes, and the reference must not move with it.
#: parity.mjs serves each file to the page through the harness's overlay, so
#: only what the reader makes of it is kept here.
DEM_FIXTURES = OUT.parent / "fixtures" / "dem"

#: Files of at most this many cells are held value by value; larger ones by
#: a digest of their values and ten cells spread through them.
GEOTIFF_SMALL = 64
GEOTIFF_SPOTS = 10


def _gt_number(value):
    """A number as the geotiff section carries it: NaN as null, and the
    infinities and -0, which JSON cannot hold, as strings."""
    value = float(value)
    if value != value:
        return None
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0 and math.copysign(1.0, value) < 0:
        return "-0"
    return value


def _gt_compact(values) -> str:
    return json.dumps([_gt_number(v) for v in values], separators=(",", ":"))


def _gt_digest(values) -> str:
    """SHA-256 of float64 little-endian values, every NaN 0x7FF8000000000000
    and the signs of zeros kept, as parity.mjs computes it with C.sha256Hex."""
    a = np.array(values, dtype="<f8").ravel()
    a[np.isnan(a)] = np.nan
    return hashlib.sha256(a.tobytes()).hexdigest()


def _gt_layout(layout) -> str:
    """The layout's every field under the browser's camelCase name, as one
    line of JSON, the numbers that need not be whole by _gt_number."""
    out = {}
    for key, value in dataclasses.asdict(layout).items():
        camel = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), key)
        out[camel] = _gt_number(value) if key in ("x0", "y0", "sx", "sy", "nodata") and value is not None else value
    return json.dumps(out, separators=(",", ":"))


def geotiff_reference() -> dict:
    """What groundwater.geotiff makes of each committed fixture: the ranges
    its layout asks for given the first 16 bytes; the layout itself, or the
    refusal (id and sentence) of the layout or of the read; and the read:
    for a file of up to 8 x 8 cells every value (south row first) and the
    reasons of the per-sample rule under the elevation layer's plausibility
    bounds (north row first), for a larger one digests of both and ten
    values spread through it, and the axes by digest with their first and
    last centres and step."""
    from groundwater.config import TerrainConfig

    terrain = TerrainConfig()
    bounds = (terrain.implausible_below_m, terrain.implausible_above_m)
    files = []
    for path in sorted(DEM_FIXTURES.glob("*.tif")):
        name, data = path.name, path.read_bytes()
        entry: dict = {"name": name}
        try:
            need = geotiff_layout(name, len(data), [(0, data[:16])])
            entry["need"] = json.dumps(need, separators=(",", ":")) if isinstance(need, list) else "layout"
        except GeoTiffError as refused:
            entry["need"] = refused.ident
        try:
            layout = geotiff_layout(name, len(data), [(0, data)])
            assert not isinstance(layout, list)
            entry["layout"] = _gt_layout(layout)
            raster = read_geotiff(data, name)
        except GeoTiffError as refused:
            entry["refused"] = [refused.ident, str(refused)]
            files.append(entry)
            continue
        reasons = np.zeros((layout.height, layout.width), dtype=np.uint8)
        across = -(-layout.width // layout.block_width) if layout.tiled else 1
        for index, offset, length, rows in block_ranges(layout, 0, layout.height, 0, layout.width):
            _, why = decode_block(layout, index, data[offset:offset + length], rows, bounds)
            top, left = index // across * layout.block_height, index % across * layout.block_width
            reasons[top:top + why.shape[0], left:left + why.shape[1]] = why
        why = "".join(str(r) for r in reasons.ravel().tolist())
        z = raster.z.ravel()
        if z.size <= GEOTIFF_SMALL:
            entry["values"], entry["reasons"] = _gt_compact(z), why
        else:
            spots = [k * (z.size - 1) // (GEOTIFF_SPOTS - 1) for k in range(GEOTIFF_SPOTS)]
            entry["values"] = {"digest": _gt_digest(z), "spots": _gt_compact(z[spots])}
            entry["reasons"] = hashlib.sha256(why.encode("ascii")).hexdigest()
        entry["axes"] = {"x": _gt_digest(raster.x), "y": _gt_digest(raster.y),
                         "ends": _gt_compact([raster.x[0], raster.x[-1], layout.sx,
                                              raster.y[0], raster.y[-1], layout.sy])}
        files.append(entry)
    return {"bounds": list(bounds), "files": files}


# ---------------------------------------------- elevation layer (PLAN.md step 4.1)

_ARCSEC = 1.0 / 3600.0
_COP_W012 = "Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif"
_COP_W011 = "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif"
_OVERLAP_AT = [-12.5 + 12 * _ARCSEC, 8.75 - 19 * _ARCSEC]

#: The windows both elevation layers plan and read. A file is a committed
#: fixture (served to the page through the overlay), alone or as
#: [fixture, the name it is given], or as [fixture, name, patches], each
#: patch [offset, hex] overwriting the fixture's bytes there, so that a
#: damaged header needs no file of its own; or [[lon0, lat0, side, bump],
#: name]: an .hgt tile of heights from integer arithmetic on each cell's
#: place in the world, which the page makes itself for the ranges its plan
#: reads and no others, so that no 2.9 MB tile is committed; a bump [row,
#: column, metres] puts one cell out of step. A centre is a GPS-like point
#: [lon, lat, label]; with none the site's area window centres it, and with
#: no site the files' middle. "cap" and "blocks" set terrain.max_cells and
#: terrain.max_blocks.
ELEVATION_WINDOWS = [
    {"case": "the Copernicus pair across 11 W", "files": [_COP_W012, _COP_W011],
     "centre": [-11.0, 9.0 - 20 * _ARCSEC, "the test point"], "radius": 0.5, "margin": 0.0},
    {"case": "the pair with a margin around the square shown", "files": [_COP_W012, _COP_W011],
     "centre": [-11.0, 8.995, "the test point"], "radius": 0.3, "margin": 0.2},
    {"case": "an overlap that agrees", "files": ["overlap_north.tif", "overlap_south_agrees.tif"],
     "centre": _OVERLAP_AT + ["the test point"], "radius": 0.45, "margin": 0.0},
    {"case": "an overlap that disagrees", "files": ["overlap_north.tif", "overlap_south_disagrees.tif"],
     "centre": _OVERLAP_AT + ["the test point"], "radius": 0.45, "margin": 0.0},
    {"case": "an undeclared fill at the shared edge", "files": ["overlap_north.tif", "overlap_south_fill_edge.tif"],
     "centre": _OVERLAP_AT + ["the test point"], "radius": 0.45, "margin": 0.0},
    {"case": "half a cell out of phase", "files": ["overlap_north.tif", "phase_half_cell.tif"],
     "centre": [-12.495, 8.745, "the test point"], "radius": 0.2, "margin": 0.0},
    {"case": "another cell size", "files": ["overlap_north.tif", "spacing_mismatch.tif"],
     "centre": [-12.495, 8.745, "the test point"], "radius": 0.2, "margin": 0.0},
    {"case": "two products", "files": [_COP_W012, [_COP_W011, "n08_w011_1arc_v3.tif"]],
     "centre": [-11.0, 8.995, "the test point"], "radius": 0.3, "margin": 0.0},
    {"case": "renamed tiles", "files": ["n08w012.tif", "n08w011.tif"],
     "centre": [-11.0, 8.995, "the test point"], "radius": 0.3, "margin": 0.0},
    {"case": "a tile missing beside sea", "files": ["holes_N08W012.tif", "holes_sea_N08W013.tif",
                                                   "holes_sea_N07W012.tif"],
     "centre": [-12.0, 8.0, "the test point"], "radius": 30.0, "margin": 0.0,
     "declared": ["copernicus_glo30", ""]},
    {"case": "a tile missing beside land", "files": ["holes_N08W012.tif", "holes_land_N08W013.tif",
                                                    "holes_land_N07W012.tif"],
     "centre": [-12.0, 8.0, "the test point"], "radius": 30.0, "margin": 0.0,
     "declared": ["copernicus_glo30", ""]},
    {"case": "a tile missing beside sea seen in the window only", "files": [
        "holes_N08W012.tif", "holes_edge_N08W013.tif", "holes_sea_N07W012.tif"],
     "centre": [-12.0, 8.0, "the test point"], "radius": 15.0, "margin": 0.0,
     "declared": ["copernicus_glo30", ""]},
    {"case": "a hole beside an undeclared margin", "files": ["hole_fill_margin.tif"],
     "centre": [-12.02, 8.5, "the test point"], "radius": 8.0, "margin": 0.0,
     "declared": ["copernicus_glo30", ""]},
    {"case": "an .hgt pair across 9 N", "files": [[[-13, 9, 1201, None], "N09W013.hgt"],
                                                  [[-13, 8, 1201, None], "N08W013.hgt"]],
     "centre": [-12.5, 9.0, "the test point"], "radius": 0.2, "margin": 0.0},
    {"case": "outside the files", "files": ["n08w011.tif"], "centre": [-10.0, 8.0, "Bo"], "radius": 0.3,
     "margin": 0.0},
    {"case": "over the cap", "files": [_COP_W012, _COP_W011], "centre": [-11.0, 8.995, "the test point"],
     "radius": 1.1, "margin": 0.5, "cap": 10_000},
    {"case": "the radius the cap says fits", "files": [_COP_W012, _COP_W011],
     "centre": [-11.0, 8.995, "the test point"], "radius": 0.9, "margin": 0.5, "cap": 10_000},
    {"case": "one cell over the cap (a window of 1,225 cells)", "files": [_COP_W012, _COP_W011],
     "centre": [-11.0, 8.995, "the test point"], "radius": 0.4, "margin": 0.1, "cap": 1_224},
    {"case": "centred on a chiefdom", "files": [[[-12, 7, 1201, None], "N07W012.hgt"]],
     "site": {"community": "T", "chiefdom": "Koya", "district": "Kenema"}, "radius": 0.3, "margin": 0.0},
    {"case": "no site, centred on the files", "files": ["n08w011.tif"], "radius": 0.2, "margin": 0.0},
    {"case": "two tiles at one corner, in UTF-16 order", "files": [
        [[-13, 8, 1201, [600, 600, 1]], "N08W013\uff21.hgt"], [[-13, 8, 1201, None], "N08W013\U0001F600.hgt"]],
     "centre": [-12.5, 8.5, "the test point"], "radius": 0.3, "margin": 0.0},
    # what the 4.1a review settled: the files read, a margin alone over the
    # cap, the centre checked before the cap and a gap between tiles named,
    # shares under half a percent, the cap on blocks, and files refused as
    # they are opened (a GDAL mask, a pixel scale with one byte flipped, a
    # NaN tiepoint in the GLO-30 layout)
    {"case": "a window inside one tile of the pair", "files": [_COP_W012, _COP_W011],
     "centre": [-11.011111111111111 + 34 * _ARCSEC, 8.995, "the test point"], "radius": 0.1, "margin": 0.0},
    {"case": "a margin alone over the cap", "files": [_COP_W012, _COP_W011],
     "centre": [-11.0, 8.995, "the test point"], "radius": 1.0, "margin": 5.0, "cap": 10_000},
    {"case": "a centre far north of the tile, once refused for its radius", "files": [
        [[-12, 8, 3601, None], "N08W012.hgt"]], "centre": [-11.5, 79.7, "the test point"], "radius": 10.0,
     "margin": 5.0},
    {"case": "a centre in a gap between tiles", "files": [
        [[-12, 8, 1201, None], "N08W012.hgt"], [[-11, 8, 1201, None], "N08W011.hgt"],
        [[-12, 7, 1201, None], "N07W012.hgt"]], "centre": [-10.95, 7.97, "the test point"], "radius": 5.0,
     "margin": 0.0},
    {"case": "a centre east of the tiles", "files": [
        [[-12, 8, 1201, None], "N08W012.hgt"], [[-11, 8, 1201, None], "N08W011.hgt"],
        [[-12, 7, 1201, None], "N07W012.hgt"]], "centre": [-9.5, 8.5, "Bo"], "radius": 5.0, "margin": 0.0},
    {"case": "a gap under half a percent", "files": ["holes_N08W012.tif", "holes_land_N08W013.tif",
                                                    "holes_land_N07W012.tif"],
     "centre": [-12.0 + 9 * 0.025, 7.975 + 10 * 0.025, "the test point"], "radius": 26.0, "margin": 0.0,
     "declared": ["copernicus_glo30", ""]},
    {"case": "a sea under half a percent", "files": ["holes_N08W012.tif", "holes_sea_N08W013.tif",
                                                    "holes_sea_N07W012.tif"],
     "centre": [-12.0 + 9 * 0.025, 7.975 + 10 * 0.025, "the test point"], "radius": 26.0, "margin": 0.0,
     "declared": ["copernicus_glo30", ""]},
    {"case": "one block over the cap on blocks", "files": [_COP_W012, _COP_W011],
     "centre": [-11.0, 9.0 - 20 * _ARCSEC, "the test point"], "radius": 0.5, "margin": 0.0, "blocks": 11},
    {"case": "at the cap on blocks", "files": [_COP_W012, _COP_W011],
     "centre": [-11.0, 9.0 - 20 * _ARCSEC, "the test point"], "radius": 0.5, "margin": 0.0, "blocks": 12},
    {"case": "a file with a GDAL mask", "files": ["internal_mask.tif"], "radius": 0.2, "margin": 0.0},
    {"case": "a pixel scale with one byte flipped", "files": [
        ["holes_sea_N07W012.tif", "holes_sea_N07W012.tif", [[293, "1f"]]]], "radius": 5.0, "margin": 0.0},
    {"case": "a NaN tiepoint in the GLO-30 layout beside a good tile", "files": [
        _COP_W012, ["n08w011.tif", "n08w011.tif", [[534, "000000000000f87f"]]]],
     "centre": [-11.0, 8.995, "the test point"], "radius": 0.3, "margin": 0.0},
]


def _hgt_bytes(spec) -> bytes:
    """An .hgt tile of heights from integer arithmetic on each cell's place
    in the world, as parity.mjs makes it in the page."""
    lon0, lat0, side, bump = spec
    step = side - 1
    gj = ((90 - lat0 - 1) * step + np.arange(side, dtype=np.int64))[:, None]
    gi = ((lon0 + 180) * step + np.arange(side, dtype=np.int64))[None, :]
    z = (17 * gi + 29 * gj) % 400 + 10
    if bump:
        z[bump[0], bump[1]] += bump[2]
    return z.astype(">i2").tobytes()


def _ew_refusal(refused) -> list:
    return ["refused", refused.ident, str(refused)]


def _ew_axis(values) -> list:
    return [_gt_digest(values), _gt_number(values[0]), _gt_number(values[-1])]


def _ew_codes(values) -> str:
    """Codes a cell, as digits when there are at most 400 of them, else the
    SHA-256 of the digits."""
    digits = "".join(str(int(v)) for v in np.asarray(values).ravel().tolist())
    return digits if len(digits) <= 400 else hashlib.sha256(digits.encode("ascii")).hexdigest()


def _elevation_window(case: dict) -> dict:
    """What the Python elevation layer makes of one case, as the parity page
    writes the browser's answer: each file's source and notes (or its
    refusal), the set's label, credit, notice, surface note and sea rule,
    each file's prompts, the centre, the plan with its blocks and the reads
    that bring them in, and the read."""
    import dataclasses

    from groundwater.config import TerrainConfig
    from groundwater.mapping.elevation import (
        WindowCentre,
        elevation_label_and_credit,
        file_notes,
        open_elevation_file,
        plan_window,
        read_window,
        window_centre,
    )

    blobs, names = {}, []
    for entry in case["files"]:
        source, name, *patches = (entry, entry) if isinstance(entry, str) else entry
        blob = (DEM_FIXTURES / source).read_bytes() if isinstance(source, str) else _hgt_bytes(source)
        for offset, hexed in patches[0] if patches else []:
            patch = bytes.fromhex(hexed)
            blob = blob[:offset] + patch + blob[offset + len(patch):]
        blobs[name] = blob
        names.append(name)
    reads: list = []

    def reader(name):
        def read_at(offset: int, length: int) -> bytes:
            reads.append([name, offset, length])
            return blobs[name][offset:offset + length]
        return read_at

    readers = {name: reader(name) for name in names}
    out: dict = {"files": []}
    files = []
    for name in names:
        try:
            found = open_elevation_file(name, len(blobs[name]), readers[name])
        except GeoTiffError as refused:
            out["files"].append(_ew_refusal(refused))
            continue
        files.append(found)
        out["files"].append([found.source_id, list(found.notes)])
    if len(files) < len(names):
        return out
    declared = tuple(case.get("declared", ("detect", "")))
    label, credit, notice, surface, sea_clean = elevation_label_and_credit(files, declared)
    out["credit"] = [label, credit, notice, surface, sea_clean]
    out["prompts"] = [list(file_notes(f, declared)) for f in files]
    if case.get("centre"):
        lon, lat, where = case["centre"]
        centre = WindowCentre(lon, lat, where, True)
    else:
        site = case.get("site")
        centre = window_centre(SiteMetadata(**site) if site else None, files)
    out["centre"] = [_gt_number(centre.lon), _gt_number(centre.lat), centre.label, centre.exact, centre.note]
    cfg = TerrainConfig()
    if case.get("cap"):
        cfg = dataclasses.replace(cfg, max_cells=case["cap"])
    if case.get("blocks"):
        cfg = dataclasses.replace(cfg, max_blocks=case["blocks"])
    try:
        plan = plan_window(files, centre, case["radius"], cfg, 1, case["margin"], declared)
    except GeoTiffError as refused:
        out["plan"] = _ew_refusal(refused)
        return out
    out["plan"] = {
        "order": [f.name for f in plan.files], "sources": list(plan.sources),
        "offsets": [list(o) for o in plan.offsets],
        "at": [plan.ci, plan.cj, plan.hx, plan.hy, plan.hxs, plan.hys, plan.width, plan.height, plan.tile],
        "dx": _gt_number(plan.dx), "dy": _gt_number(plan.dy),
        "lons": _ew_axis(plan.lons), "lats": _ew_axis(plan.lats),
        "missing": [list(t) for t in plan.missing],
        "edges": [[e.missing, e.file, e.row, e.column] for e in plan.edges],
        "blocks": json.dumps([[b.file, b.index, b.offset, b.length, list(b.rows) if b.rows else None, b.window,
                               list(b.edges)] for b in plan.blocks], separators=(",", ":")),
    }
    reads.clear()
    try:
        read = read_window(plan, readers, cfg)
    except GeoTiffError as refused:
        out["read"] = _ew_refusal(refused)
    else:
        z = read.grid.z.ravel()
        spots = [k * (z.size - 1) // (GEOTIFF_SPOTS - 1) for k in range(GEOTIFF_SPOTS)]
        out["read"] = {
            "z": [_gt_digest(z), [_gt_number(v) for v in z[spots]]], "reasons": _ew_codes(read.reasons),
            "sea": _ew_codes(read.assumed_sea),
            "counts": [read.cells, read.voids, read.uncovered, read.implausible, read.assumed],
            "coverage": _gt_number(read.coverage), "shown": list(read.shown), "notes": list(read.notes),
            "prompts": list(read.prompts), "figure": read.figure_credit, "cell": read.grid.resolution_note,
            "source": read.grid.source_id,
        }
        assert (read.grid.source, read.grid.credit, read.notice, read.surface, read.grid.sea_clean) == (
            label, credit, notice, surface, sea_clean), "the read credits the set as the set is credited"
    out["reads"] = reads
    return out


def _ew_f64(values) -> str:
    """float64 values, little-endian, in base64: every bit, -0, NaN and the
    infinities included, in less room than their decimals."""
    return base64.b64encode(np.array(values, dtype="<f8").tobytes()).decode("ascii")


def elevation_window_reference() -> dict:
    """The elevation layer, case by case (ELEVATION_WINDOWS), with the
    degree sine and cosine every cell size comes from on 200 angles and the
    cell sizes of three grids, row by row. Each case's answer is one line of
    compact JSON, numbers by _gt_number, so the section stays small; the
    angles and their sines and cosines travel as float64 bits."""
    from groundwater.mapping.elevation import row_metric, sin_cos_deg

    rng = np.random.default_rng(4101)
    angles = [15.0 * k for k in range(-48, 49)]
    angles += [11.0 - int(j) * _ARCSEC for j in rng.integers(0, 4 * 3600 + 1, 40)]
    angles += [float(v) for v in rng.uniform(-720.0, 720.0, 40)]
    angles += [float(v) for v in rng.uniform(-1e6, 1e6, 6)]
    angles += [0.0, -0.0, 5e-324, -5e-324, 1e-7, 45.0, 89.99999999999999, 90.00000000000001, 1e300, -1e300,
               1.7976931348623157e308, -1.7976931348623157e308, math.inf, -math.inf, math.nan, 0.25, 7.5]
    assert len(angles) == 200
    trig = [sin_cos_deg(d) for d in angles]
    metrics = []
    for lons, lats in (
        ([-11.5 + k * _ARCSEC for k in range(5)], [8.0 + j * _ARCSEC for j in range(9)]),
        ([-13.0 + k / 1200 for k in range(4)], [9.0 - (7 - j) / 1200 for j in range(8)]),
        ([-12.0 + k / 40 for k in range(3)], [7.725 + j / 40 for j in range(6)]),
    ):
        metric = row_metric(np.array(lons), np.array(lats))
        metrics.append({"lons": _gt_compact(lons), "lats": _gt_compact(lats),
                        "rows": _gt_compact([v for r in range(len(lats)) for v in (
                            metric.dx[r], metric.dy[r], metric.dg[r], metric.au_row[r])])})
    cases = []
    for case in ELEVATION_WINDOWS:
        cases.append(dict(case, expect=json.dumps(_elevation_window(case), separators=(",", ":"))))
    return {
        "angles": _ew_f64(angles), "sin": _ew_f64([s for s, _ in trig]), "cos": _ew_f64([c for _, c in trig]),
        "metrics": metrics, "cases": cases,
    }


# --------------------------------------------- terrain analysis (PLAN.md step 4.1)

#: What the heights of every terrain window are said to be, by its read and
#: in its GeoJSON: text the captions and the description repeat word for
#: word, so it is carried once.
_TA_SURFACE = "Heights as the file gives them, of the ground and whatever stands on it."

#: The layers of whole numbers that hold one digit a cell (classes and
#: masks), written as digits; the directions, counts and areas are written
#: as numbers joined by commas.
_TA_DIGITS = ("cls", "flag", "raised", "flatRouted", "stream")


def _ta_window(case: str, z, *, assumed=None, step: float = _ARCSEC, lat0: float = 8.5, area: float = 0.0,
               settings=None, **told) -> dict:
    """One window both engines analyse, as reference.json carries it: its
    heights in metres, south row first (NaN as null, the infinities and -0
    as strings); the lattice its cell centres lie on, which both engines
    step out as lon0 + j*step; the blocks of a missing tile taken as sea
    (rows, then columns, half-open); the drainage threshold and other
    settings; and what ``told`` adds: the square shown, the source and its
    sea rule, the file's name, the place, the read the captions are given,
    and the figure credit line and notice the GeoJSON carries (a file of
    unidentified source's line unless told). parity.mjs builds the page's
    window from exactly these, so both engines analyse the same
    numbers."""
    z = np.asarray(z, dtype=np.float64)
    rows, cols = z.shape
    label = told.get("label", "test.tif")
    return {
        "case": case, "rows": rows, "cols": cols, "lon0": -12.0, "lat0": lat0, "step": step,
        "z": _gt_compact(z.ravel()), "assumed": assumed,
        "settings": {"drainage_area_km2": area, **(settings or {})}, "shown": told.get("shown"),
        "seaClean": told.get("sea_clean", False), "sourceId": told.get("source_id", "unidentified"),
        "label": label, "where": told.get("where", "the test point"), "read": told.get("read"),
            "figureCredit": told.get("figure_credit", _ta_credit(f"elevation model {label}, source not stated")),
        "notice": told.get("notice"),
    }


def _ta_credit(label: str, credit: str = "") -> str:
    """The figure credit line a read words for a set of files with this
    label and licence credit ("" for none), at the 1 arc-second cell size
    of 8.5 N: what the GeoJSON's attribution carries."""
    from groundwater.text import phrase

    if credit:
        return phrase("terrain.figure_credit", label=label, credit=credit, dx=30.6, dy=30.7)
    return phrase("terrain.figure_credit_bare", label=label, dx=30.6, dy=30.7)


def _ta_coast() -> dict:
    """T1: a coast wandering between columns 2 and 4, two valleys that
    gather the lines into confluences, a level shelf, a pit 0.5 m below
    sea level inland, a level hollow round a void (so the void is the
    outlet of what drains into the hollow), a missing tile taken as sea in
    the north-west corner, and a strip of 0 m along the east edge that
    meets the land along 16 cells in a straight line, a zero-filled gap at
    sea_straight_edge_cells = 12; the square shown leaves two cells off
    every side. The file is of unstated source, so the sea flags the lines
    that reach it and the captions say it may be a fill value, and its
    name and place need escaping in the GeoJSON."""
    rows, cols = 24, 20
    cm = np.zeros((rows, cols), dtype=np.int64)
    for r in range(rows):
        shore = 2 + (5 * r + 3) % 7 // 3
        for c in range(cols):
            cm[r, c] = (45 * (c - shore) + 6 * r + (11 * r + 7 * c) % 4 * 10 - 25
                        + 20 * min(abs(r - 8), abs(r - 16)))
    cm[9:13, 11:16] = 700        # the shelf, lower ground to its west
    cm[15, 9] = -50              # the pit
    cm[3:7, 11:16] = 200         # the hollow
    cm[2:18, 17:20] = 0          # the zero-filled strip
    z = cm / 100.0
    z[4:6, 12:15] = math.nan     # the void
    z[20:24, 0:6] = math.nan     # the missing tile, which has no height
    return _ta_window(
        "T1: a coast, a void, a shelf, a pit below sea level, a missing tile taken as sea and a zero-filled strip",
        z, assumed=[[20, 24, 0, 6]], area=0.008,
        settings={"sea_straight_edge_cells": 12, "fill_note_m": 0.25, "curvature_spacing_m": 60.0},
        shown=[2, 22, 2, 18], label='Mɔyamba "coast" – N08°.tif', where="Sɛwa \\ Mɔyamba",
        read={"surface": _TA_SURFACE, "plan": {"radiusKm": 0.3, "marginKm": 0.06}})


def _ta_plateau() -> dict:
    """T2: a level plateau 10 cells square inside a rim, drained by a notch
    on the west and one on the east, so the flats are resolved towards two
    outlets, on slopes that fall to every edge; a Copernicus tile, whose
    notice the GeoJSON carries."""
    cm = np.zeros((16, 16), dtype=np.int64)
    for r in range(16):
        for c in range(16):
            cm[r, c] = 1200 + 300 * min(r, c, 15 - r, 15 - c)
    cm[2:14, 2:14] = 3000        # the rim
    cm[3:13, 3:13] = 2000        # the plateau inside it
    cm[7, 2] = 1950              # the notches
    cm[9, 13] = 1950
    return _ta_window("T2: a plateau inside a rim, drained through two notches", cm / 100.0, area=0.01,
                      sea_clean=True, source_id="copernicus_glo30",
                      label="Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", where="Kakua",
                      figure_credit=_ta_credit("Copernicus GLO-30 tile N08 W012", "© DLR e.V. 2014-2018"),
                      notice='Produced from Copernicus data; no liability "at all".')


def _ta_ties() -> dict:
    """T3: terraces on half-metre steps, ties everywhere, folded into a
    valley, with sea along the south edge, on the 3-arc-second lattice at
    7.9 N (so the curvature spacing is one cell); the square shown cuts
    lines that leave it."""
    cm = np.zeros((30, 12), dtype=np.int64)
    for r in range(30):
        for c in range(12):
            cm[r, c] = 1000 + 50 * ((3 * r + 2 * c + (r * c) % 5) // 4) + 50 * (abs(c - 6) // 2)
    cm[0, :] = 0
    return _ta_window("T3: terraces with ties everywhere on the 3-arc-second lattice", cm / 100.0,
                      step=1 / 1200, lat0=7.9, area=0.2, shown=[3, 27, 2, 10], sea_clean=True, source_id="srtm",
                      label="n07_w012_3arc_v2.tif", where="Bo")


def _ta_degenerate() -> list:
    """T5: windows at the edges of what an analysis takes: a single row
    (refused: no step between rows to measure), three cells square, a
    window all one height, one with no height at all, one all sea, the
    infinities among heights, and the four signed-zero cases of the design
    review (a +0 or -0 seed beside a void with a pit of the other sign
    beside it, either way round). Every land cell is a stream cell."""
    nan, inf = math.nan, math.inf
    out = [
        _ta_window("T5: one row of seven cells", [[3.0, 2.0, 1.0, 2.0, 3.0, 4.0, 5.0]]),
        _ta_window("T5: three cells square round a pit", [[3.0, 2.5, 3.2], [2.6, 1.8, 2.7], [3.1, 2.4, 3.3]]),
        _ta_window("T5: six cells square all one height", np.full((6, 6), 5.0)),
        _ta_window("T5: five cells square with no height", np.full((5, 5), nan)),
        _ta_window("T5: five cells square all sea", np.full((5, 5), -2.0), sea_clean=True),
        _ta_window("T5: infinities among the heights",
                   [[4.0, 4.5, 5.0, 5.5, 6.0, 6.5], [3.5, inf, 4.5, 5.0, -inf, 6.0], [3.0, 3.5, 4.0, 4.5, 5.0, 5.5],
                    [2.5, 3.0, -inf, 4.0, 4.5, 5.0], [2.0, 2.5, 3.0, 3.5, 4.0, inf]]),
    ]
    for k, (a, b, void) in enumerate([(0.0, -0.0, 1), (-0.0, 0.0, 1), (0.0, -0.0, 4), (-0.0, 0.0, 4)]):
        z = np.full((3, 6), 9.0)
        z[1, 2], z[1, 3], z[1, void] = a, b, nan
        out.append(_ta_window(f"T5: signed zeros, case {k + 1}", z))
    return out


def _ta_worded() -> list:
    """T7: windows that reach the captions' rules for shares, margins and
    sea of unstated source, held by digests as T5 is: two cells of sea in
    480 ("less than 1%", with the count), an island of four cells in 900
    (99% sea, never 100%), a zero-filled block reaching one cell into a
    square shown with a margin of four or five cells on every side (0.1 km,
    and "1 cell"), sea of a file of unstated source in the margin alone,
    which the wetness caption and the description mention and the relief
    does not, a pit whose filling raises one cell of the 576 of land (less
    than 1% of the land, with the count), and a bowl whose filling raises
    all but one of the 400 cells shown (99% of the land, never 100%)."""
    r, c = np.arange(30)[:, None], np.arange(24)[None, :]
    corner = (2.0 + 0.3 * r[:20] + 0.2 * c) + np.zeros((20, 24))
    corner[0, 0:2] = -1.0
    island = np.full((30, 30), -1.0)
    island[14:16, 14:16] = 3.0
    block = (3.0 + 0.2 * r + 0.1 * c) + np.zeros((30, 24))
    block[0:5, 0:8] = 0.0
    block[5, 4] = 0.0
    coast = (1.0 + 0.4 * r[:16] + 0.1 * np.abs(c[:, :14] - 7)) + np.zeros((16, 14))
    coast[0:2, :] = -1.0
    pit = (2.0 + 0.3 * r[:24] + 0.2 * c) + np.zeros((24, 24))
    pit[12, 12] -= 3.0
    bowl = np.full((30, 30), 10.0)
    bowl[1:-1, 1:-1] = 1.0 + 0.01 * r[1:-1] + 0.02 * np.arange(1, 29)[None, :]
    bowl[15, 15] = 20.0
    return [
        _ta_window("T7: two cells of sea in a square of 480", np.round(corner, 2), sea_clean=True),
        _ta_window("T7: an island of four cells in 900, 99% sea", island, sea_clean=True),
        _ta_window("T7: a zero-filled block reaching one cell into the square shown", np.round(block, 2),
                   settings={"sea_straight_edge_cells": 5}, shown=[5, 26, 4, 20], sea_clean=True),
        _ta_window("T7: sea of unstated source in the margin alone", np.round(coast, 2), area=0.003,
                   shown=[3, 16, 0, 14]),
        _ta_window("T7: a pit raising one cell of land in 576", np.round(pit, 2), sea_clean=True),
        _ta_window("T7: a bowl raised but for one cell of 400 shown, 99% of the land", np.round(bowl, 2),
                   shown=[5, 25, 5, 25], sea_clean=True),
    ]


#: T4: a window generated in both engines (spec 7.5). Heights drawn from
#: one stream of the range-of-models generator (Stream / C.rangeStream),
#: row by row from the south, west to east: v = 0.5*left + 0.5*below +
#: 0.02*c + 0.03*r + 3.0*(u - 0.5), left and below the heights already
#: made beside it (0 off the grid), each rounded to 0.1 m as floor(v*10 +
#: 0.5)/10; then the columns of "strip" lowered by 30 m, a coast, and the
#: "void" block (rows, then columns, half-open) left without a height. 16
#: cells of margin are analysed round the square shown.
TERRAIN_GENERATED = {
    "case": "T4: a coast and a void on ground drawn from Stream(41, 0)", "rows": 192, "cols": 160,
    "lon0": -12.0, "lat0": 8.5, "step": _ARCSEC, "seed": 41, "stream": 0, "strip": [0, 24],
    "void": [70, 80, 90, 104], "settings": {"drainage_area_km2": 0.1}, "shown": [16, 176, 16, 144],
    "seaClean": True, "sourceId": "copernicus_glo30", "label": "Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif",
    "where": "Kakua", "read": {"surface": _TA_SURFACE, "plan": {"radiusKm": 2.0, "marginKm": 0.5}},
    "figureCredit": _ta_credit("Copernicus GLO-30 tile N08 W012", "© DLR e.V. 2014-2018"),
    "notice": "Produced from Copernicus data.",
}

#: T6: a plane tilted to its south-west corner, 256 cells square. Every
#: cell drains there, so one catchment holds all 65,536 cells, more than
#: 2^32 units of area; the page traces its lines again from a core put
#: through structuredClone, as the worker hands it over, at each of
#: "areas" (km²), from every cell a stream cell to none.
TERRAIN_PLANE = {
    "case": "T6: a plane tilted to one corner, re-traced from a cloned core", "rows": 256, "cols": 256,
    "lon0": -12.0, "lat0": 8.5, "step": _ARCSEC, "settings": {"drainage_area_km2": 0.5},
    "shown": [10, 246, 6, 250], "seaClean": True, "sourceId": "unidentified", "label": "plane.tif",
    "areas": [0.0005, 0.05, 0.5, 5.0, 61.0, 1000.0],
}


def _ta_unfold(text: str) -> np.ndarray:
    """Numbers as _gt_compact writes them, back to float64."""
    named = {"Infinity": math.inf, "-Infinity": -math.inf, "-0": -0.0}
    return np.array([math.nan if v is None else named[v] if isinstance(v, str) else v for v in json.loads(text)],
                    dtype=np.float64)


def _ta_axes(case: dict) -> tuple[list, list]:
    """A window's cell centres, lon0 + j*step and lat0 + j*step, as the
    page steps them out."""
    return ([case["lon0"] + j * case["step"] for j in range(case["cols"])],
            [case["lat0"] + j * case["step"] for j in range(case["rows"])])


def _ta_analysis(case: dict, z):
    """analyse_terrain on one window in float64, as parity.mjs runs
    C.analyseTerrain on it, and the progress it heard."""
    from groundwater.config import TerrainConfig
    from groundwater.mapping.elevation import ElevationGrid
    from groundwater.mapping.terrain_analysis import analyse_terrain

    rows, cols = case["rows"], case["cols"]
    lons, lats = _ta_axes(case)
    grid = ElevationGrid(np.asarray(lons, dtype=np.float64), np.asarray(lats, dtype=np.float64),
                         np.asarray(z, dtype=np.float64).reshape(rows, cols), source=case["label"],
                         source_id=case["sourceId"], sea_clean=case["seaClean"])
    assumed = None
    if case.get("assumed") is not None:
        assumed = np.zeros((rows, cols), dtype=bool)
        for r0, r1, c0, c1 in case["assumed"]:
            assumed[r0:r1, c0:c1] = True
    cfg = TerrainConfig(**{key: tuple(v) if isinstance(v, list) else v for key, v in case["settings"].items()})
    heard: list = []
    analysis = analyse_terrain(grid, cfg, assumed_sea=assumed, shown=case["shown"],
                               progress=lambda fraction, label: heard.append([fraction, label]),
                               precision="float64")
    return analysis, heard


def _ta_layers(a) -> tuple[dict, dict]:
    """An analysis's layers under the browser's names: those of whole
    numbers (classes, directions, masks, counts and areas), then those of
    floats, the core's cell sizes among them, in the order parity.mjs takes
    them. The core's cell centres are the window's own, which the GeoJSON
    coordinates hold to six places."""
    core = a.core
    ints = {"cls": core.cls, "code": core.code, "flag": core.flag, "raised": core.raised,
            "flatRouted": core.flat_routed, "stream": a.stream, "count": core.count, "areaUnits": core.area_units}
    floats = {"filled": a.filled, "fillDepth": a.fill_depth, "p": a.p, "q": a.q, "tanb": a.tanb}
    floats.update({f"hillshade{j}": layer for j, layer in enumerate(a.hillshades)})
    floats.update({"hillshadeMulti": a.hillshade_multi, "twiArg": a.twi_arg, "profile": a.profile,
                   "tangential": a.tangential, "dx": core.dx, "dy": core.dy, "dg": core.dg})
    return ints, floats


def _ta_whole(name: str, layer) -> str:
    """A layer of whole numbers as both engines write it: digits for a
    class or a mask, else str(int) joined by commas."""
    return ("" if name in _TA_DIGITS else ",").join(str(int(v)) for v in np.ravel(layer).tolist())


def _ta_f64(values) -> bytes:
    """float64 little-endian bytes, every NaN 0x7FF8000000000000 and the
    signs of zeros kept, as _gt_digest hashes them: T5 hashes all its
    float layers as one run of these."""
    a = np.array(values, dtype="<f8").ravel()
    a[np.isnan(a)] = np.nan
    return a.tobytes()


def _ta_spots(values, n: int = 3) -> list:
    """n cells spread through a layer, by _gt_number."""
    v = np.ravel(np.asarray(values, dtype=np.float64))
    return [_gt_number(v[k * (v.size - 1) // (n - 1)]) for k in range(n)]


def _ta_lines(lines) -> list:
    """Links or parts as JSON, each the values of its fields in their
    order (the names are carried once, in the section's "fields")."""
    return [clean(list(dataclasses.astuple(line))) for line in lines]


def _ta_lines_digest(lines) -> str:
    """SHA-256 of the links or parts as one line of JSON, every field by
    name in its order and each length by its float64 bits (16 hex digits,
    big-endian): text both engines write alike, where a length in decimals
    is not (Python writes 30.0 where JavaScript writes 30)."""
    text = json.dumps([{**dataclasses.asdict(line), "length_m": struct.pack(">d", line.length_m).hex()}
                       for line in lines], separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ta_captions(a, case: dict) -> list:
    """terrain_captions for the window's read (a surface note and a plan,
    or None) and place, as [key, sentence] pairs in Python's order."""
    from groundwater.mapping.terrain_analysis import terrain_captions

    read = case["read"]
    if read is not None:
        plan = read["plan"]
        read = SimpleNamespace(surface=read["surface"], plan=None if plan is None else SimpleNamespace(
            radius_km=plan["radiusKm"], margin_km=plan["marginKm"]))
    return [list(item) for item in terrain_captions(a, read, case["where"]).items()]


def _ta_text_digest(captions: list) -> str:
    """SHA-256 of the captions, one "key<TAB>sentence" a line."""
    return hashlib.sha256("\n".join(f"{key}\t{text}" for key, text in captions).encode("utf-8")).hexdigest()


def _ta_geojson(a, case: dict) -> str:
    """The drainage lines shown as GeoJSON. What it is told follows from
    the window, as parity.mjs makes it: the file's name, figure credit
    line and notice; the threshold; the radius and margin of the read's
    plan (0.3 and 0.05 km without one); the middle cell as the centre,
    named for the place; and the fill note, sea level, sea rule and sea
    cells of the analysed window that the analysis was run with."""
    from groundwater.mapping.elevation import WindowCentre
    from groundwater.mapping.terrain_analysis import SEA, drainage_geojson

    lons, lats = _ta_axes(case)
    plan = case["read"]["plan"] if case["read"] else None
    meta = {"label": case["label"], "figure_credit": case["figureCredit"], "notice": case["notice"],
            "surface": _TA_SURFACE, "area": case["settings"]["drainage_area_km2"],
            "radius": plan["radiusKm"] if plan else 0.3, "margin": plan["marginKm"] if plan else 0.05,
            "centre": WindowCentre(lons[case["cols"] // 2], lats[case["rows"] // 2], case["where"], True),
            "fill_note_m": a.settings.fill_note_m, "sea_clean": case["seaClean"],
            "sea_cells": int(np.count_nonzero(a.core.cls == SEA)), "sea_level_m": a.settings.sea_level_m}
    return drainage_geojson(a.core, a.parts, meta)


def _ta_told(a) -> dict:
    """What every window holds exactly beside its layers and lines: the
    summary's values in Python's key order (the keys are carried once, in
    the section's "summary"; the wetness range is held apart, to 1e-12),
    the unresolved flats, the curvature spacing in cells, the floored and
    zero-filled cells, and the square shown."""
    return {
        "summary": [_gt_number(v) if isinstance(v, float) else v
                    for key, v in a.summary.items() if key != "twi_range"],
        "scalars": [a.unresolved, a.k_cells, a.floored, a.zero_fill], "shown": list(a.core.shown),
    }


def _ta_wetness(a, n: int) -> dict:
    """The wetness index at up to n cells spread through those where it is
    defined, and its display range. The cells' indices are digits; the
    values are numbers outside the exact expectation, because each is a
    library's logarithm: parity holds them to 1e-12 and --check to
    CHECK_RTOL, so a runner whose log differs in the last bit still
    agrees."""
    twi = np.ravel(np.asarray(a.twi, dtype=np.float64))
    finite = np.flatnonzero(np.isfinite(twi))
    at = sorted({int(finite[k * (finite.size - 1) // (n - 1)]) for k in range(n)}) if finite.size else []
    return {"at": ",".join(str(i) for i in at), "values": [float(twi[i]) for i in at],
            "range": clean(list(a.summary["twi_range"]))}


def _ta_short(data) -> str:
    """The first 16 hex digits of the SHA-256 of text (as UTF-8) or bytes:
    what T5 holds each of its answers by, which tells two answers apart as
    surely as a check needs and keeps nine windows in a few kilobytes."""
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()[:16]


def _ta_held(case: dict, full: bool, words: bool = False) -> dict:
    """One window of T1-T3 (``full``) or of T5 and T7 and what Python makes
    of it, or its refusal word for word; "held" tells parity.mjs which.

    With ``full``: every layer of whole numbers as text; each float layer
    by a digest that keeps signs of zero, and three cells of it; the links
    and parts as JSON; the GeoJSON as text; and the captions, with
    ``words`` as text with the progress heard (T1), else by SHA-256, since
    most of every caption is the same sentences. Without: the layers of
    whole numbers, the float layers, the links, the parts, the GeoJSON and
    the captions each by a short digest (_ta_short), with the counts of
    links and parts and the GeoJSON's length. Then the summary and counts;
    the GeoJSON and the wetness index travel outside the exact expectation,
    the one so that its quotes are escaped once rather than twice, the
    other to be held to a tolerance."""
    held = "words" if words else "full" if full else "digests"
    try:
        a, heard = _ta_analysis(case, _ta_unfold(case["z"]))
    except ValueError as refused:
        return dict(case, held=held, expect=json.dumps({"refused": str(refused)}), geojson=None, twi=None)
    ints, floats = _ta_layers(a)
    geojson, captions = _ta_geojson(a, case), _ta_captions(a, case)
    if full:
        expect: dict = {
            "ints": {name: _ta_whole(name, v) for name, v in ints.items()},
            "floats": {name: [_gt_digest(v), _ta_spots(v)] for name, v in floats.items()},
            "links": _ta_lines(a.links), "parts": _ta_lines(a.parts),
            "captions": captions if words else _ta_text_digest(captions),
        }
        if words:
            expect["heard"] = heard
        told = geojson
    else:
        expect = {
            "ints": _ta_short("\n".join(_ta_whole(name, v) for name, v in ints.items())),
            "floats": _ta_short(b"".join(_ta_f64(v) for v in floats.values())),
            "links": [_ta_lines_digest(a.links)[:16], len(a.links)],
            "parts": [_ta_lines_digest(a.parts)[:16], len(a.parts)],
            "captions": _ta_text_digest(captions)[:16],
        }
        told = [_ta_short(geojson), len(geojson)]
    expect.update(_ta_told(a))
    return dict(case, held=held, expect=json.dumps(expect, separators=(",", ":")), geojson=told,
                twi=_ta_wetness(a, 10 if full else 4))


def _ta_generated_heights(spec: dict) -> list:
    """T4's heights, south row first (TERRAIN_GENERATED)."""
    rows, cols = spec["rows"], spec["cols"]
    draw = Stream(spec["seed"], spec["stream"])
    z = [[0.0] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            left = z[r][c - 1] if c else 0.0
            below = z[r - 1][c] if r else 0.0
            v = 0.5 * left + 0.5 * below + 0.02 * c + 0.03 * r + 3.0 * (draw.uniform() - 0.5)
            z[r][c] = math.floor(v * 10.0 + 0.5) / 10.0
    for row in z:
        for c in range(*spec["strip"]):
            row[c] = row[c] - 30.0
    r0, r1, c0, c1 = spec["void"]
    for r in range(r0, r1):
        for c in range(c0, c1):
            z[r][c] = math.nan
    return [v for row in z for v in row]


def _ta_generated(spec: dict) -> dict:
    """T4 and what Python makes of it: the heights by digest and three
    cells (so a page that drew others says so first); every layer by
    digest; the links and parts by digest and count with the first 20 of
    each in full; the GeoJSON by SHA-256 and length, its first 4,000
    characters apart; the captions by SHA-256; the summary and counts
    exact; and the wetness index at 50 cells with its count, least and
    greatest value and display range."""
    z = _ta_generated_heights(spec)
    a, _ = _ta_analysis(spec, z)
    ints, floats = _ta_layers(a)
    geojson = _ta_geojson(a, spec)
    expect = {
        "z": [_gt_digest(z), _ta_spots(z)],
        "layers": {name: _gt_digest(v) for name, v in {**ints, **floats}.items()},
        "links": [_ta_lines_digest(a.links), len(a.links), _ta_lines(a.links[:20])],
        "parts": [_ta_lines_digest(a.parts), len(a.parts), _ta_lines(a.parts[:20])],
        "geojson": [hashlib.sha256(geojson.encode("utf-8")).hexdigest(), len(geojson)],
        "captions": _ta_text_digest(_ta_captions(a, spec)), **_ta_told(a),
    }
    twi = np.ravel(np.asarray(a.twi, dtype=np.float64))
    finite = twi[np.isfinite(twi)]
    wetness = {**_ta_wetness(a, 50), "count": int(finite.size), "min": float(finite.min()),
               "max": float(finite.max())}
    return dict(spec, expect=json.dumps(expect, separators=(",", ":")), geojson=geojson[:4000], twi=wetness)


def _ta_plane(spec: dict) -> dict:
    """T6 and what Python makes of it: the area and cells draining to the
    corner, the links and parts of the analysis itself, and at each
    threshold those drainage_links traces from the core, by digest and
    count."""
    from groundwater.mapping.terrain_analysis import drainage_links

    rows, cols = spec["rows"], spec["cols"]
    a, _ = _ta_analysis(spec, [10.0 + 0.5 * (r + c) for r in range(rows) for c in range(cols)])
    core = a.core
    corner, count = int(core.area_units[0, 0]), int(core.count[0, 0])
    assert corner == int(core.area_units.max()) > 2**32 and count == rows * cols, "one catchment past 2^32"
    at = []
    for area in spec["areas"]:
        links, parts = drainage_links(core, area)
        at.append([_ta_lines_digest(links), _ta_lines_digest(parts), len(links), len(parts)])
    expect = {"corner": corner, "count": count,
              "own": [_ta_lines_digest(a.links), _ta_lines_digest(a.parts), len(a.links), len(a.parts)], "at": at}
    return dict(spec, expect=json.dumps(expect, separators=(",", ":")))


def terrain_reference() -> dict:
    """The terrain analysis (spec 7.5): T1-T3 held cell by cell and line by
    line, the degenerate windows of T5 and the caption windows of T7 by
    digests, the generated T4 by
    digests with its first lines and GeoJSON in full, and the plane T6
    re-traced from a cloned core; with what every window shares carried
    once: the surface note, the names of the links' and parts' fields, and
    the summary's keys."""
    from groundwater.mapping.terrain_analysis import DrainageLink, DrainagePart

    small = [_ta_held(_ta_coast(), full=True, words=True)]
    small += [_ta_held(w, full=True) for w in (_ta_plateau(), _ta_ties())]
    small += [_ta_held(w, full=False) for w in (*_ta_degenerate(), *_ta_worded())]
    # the summary's keys in the order analyse_terrain gives them, which is
    # the same for every window: here a small one's
    some = _ta_degenerate()[1]
    keys = [key for key in _ta_analysis(some, _ta_unfold(some["z"]))[0].summary if key != "twi_range"]
    return {
        "surface": _TA_SURFACE,
        "fields": {"links": [f.name for f in dataclasses.fields(DrainageLink)],
                   "parts": [f.name for f in dataclasses.fields(DrainagePart)]},
        "summary": keys, "cases": small, "generated": _ta_generated(TERRAIN_GENERATED),
        "plane": _ta_plane(TERRAIN_PLANE),
    }


# ----------------------------------------- lineament candidates (PLAN.md step 4.2)

#: Settings that let a window of a few dozen cells hold lineament
#: candidates: no smoothing pass, pieces and candidates two cells long, and
#: every centreline cell kept. The small windows are held with these as
#: well as with the defaults, which find nothing in them.
LINEAMENT_FINE = {
    "lineament_smoothing_m": 10.0, "lineament_contrast_km": 0.3, "lineament_share": 1.0,
    "lineament_min_curvature_per_km": 0.01, "lineament_straight_m": 30.0, "lineament_piece_m": 60.0,
    "lineament_min_length_m": 60.0, "lineament_link_gap_m": 60.0, "lineament_link_offset_m": 30.0,
}

#: Settings both engines refuse in the same words: no share, more than all
#: of it, a turn and a link angle of a right angle or more, no smoothing,
#: and a length below zero.
LINEAMENT_REFUSED = [
    {"lineament_share": 0.0}, {"lineament_share": 1.5}, {"lineament_turn_deg": 90.0},
    {"lineament_link_angle_deg": 95.0}, {"lineament_smoothing_m": 0.0}, {"lineament_min_length_m": -1.0},
    {"lineament_min_curvature_per_km": 0.0},
]

#: L1 and L2: a window generated in both engines, as T4 is. Heights drawn
#: from one stream of the range-of-models generator (Stream /
#: C.rangeStream), row by row from the south, west to east: v = 0.5*left +
#: 0.5*below + 4.0*(u - 0.5), left and below the heights already made
#: beside it (0 off the grid). Then each of "planted", [r0, c0, r1, c1,
#: depth, width] in cells and metres, cut in: every cell less than width
#: cells from the segment (r0, c0)-(r1, c1) lowered by depth*(1 - d/width),
#: a ridge where depth is below zero, the distance d worked out as
#: lineament_heights says. Then "base" added and each height rounded to
#: 0.01 m as floor(v*100 + 0.5)/100; the columns of "sea" lowered by 150 m
#: below the base, and the "void" block (rows, then columns, half-open) left
#: without a height. Two valleys of the five line up with a gap of eight
#: cells; the void cuts another. L1 finds the candidates with the defaults,
#: L2 with "settings" given to the candidates alone.
LINEAMENT_GENERATED = {
    "rows": 160, "cols": 160, "lon0": -12.0, "lat0": 8.5, "step": _ARCSEC, "seed": 43, "stream": 0, "base": 100.0,
    "planted": [[20, 40, 140, 75, 10.0, 4.0], [100, 20, 104, 140, 8.0, 3.0], [30, 130, 130, 30, -9.0, 4.0],
                [20, 100, 60, 112, 8.0, 3.0], [68, 114, 113, 127, 8.0, 3.0]],
    "sea": [0, 20], "void": [76, 84, 50, 64], "settings": {}, "shown": [16, 144, 16, 144], "seaClean": True,
    "sourceId": "copernicus_glo30", "label": "Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", "where": "Kakua",
    "read": {"surface": _TA_SURFACE, "plan": {"radiusKm": 2.0, "marginKm": 0.5}},
    "figureCredit": _ta_credit("Copernicus GLO-30 tile N08 W012", "© DLR e.V. 2014-2018"),
    "notice": "Produced from Copernicus data.",
    "cases": [
        {"case": "L1: five straight valleys and ridges planted in generated relief, the defaults", "settings": None},
        {"case": "L2: the same window with every centreline cell kept, two suns lower and shorter candidates",
         "settings": {"lineament_smoothing_m": 30.0, "lineament_contrast_km": 0.8, "lineament_share": 1.0,
                      "lineament_turn_deg": 45.0, "lineament_min_length_m": 300.0, "lineament_link_gap_m": 900.0,
                      "lineament_link_angle_deg": 20.0, "hillshade_altitude_deg": 30.0,
                      "hillshade_panel_azimuths_deg": [315.0, 45.0], "lineament_min_curvature_per_km": 0.3}},
    ],
}


def lineament_heights(spec: dict) -> list:
    """L1's heights, south row first (LINEAMENT_GENERATED). A cell's
    distance from a planted segment is from the point of the segment
    nearest it: t = ((r - r0)*er + (c - c0)*ec)/(er*er + ec*ec), er and ec
    the segment's rows and columns, t held to 0..1, and d = sqrt(pr*pr +
    pc*pc) with pr = (r0 + t*er) - r and pc = (c0 + t*ec) - c, in that
    order, so that both engines work out the same heights."""
    rows, cols = spec["rows"], spec["cols"]
    draw = Stream(spec["seed"], spec["stream"])
    z = [[0.0] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            left = z[r][c - 1] if c else 0.0
            below = z[r - 1][c] if r else 0.0
            z[r][c] = 0.5 * left + 0.5 * below + 4.0 * (draw.uniform() - 0.5)
    for r0, c0, r1, c1, depth, width in spec["planted"]:
        er, ec = float(r1 - r0), float(c1 - c0)
        span = er * er + ec * ec
        for r in range(rows):
            for c in range(cols):
                t = ((r - r0) * er + (c - c0) * ec) / span
                t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
                pr, pc = (r0 + t * er) - r, (c0 + t * ec) - c
                d = math.sqrt(pr * pr + pc * pc)
                if d < width:
                    z[r][c] = z[r][c] - depth * (1.0 - d / width)
    s0, s1 = spec["sea"]
    v0, v1, w0, w1 = spec["void"]
    out = []
    for r in range(rows):
        for c in range(cols):
            v = math.floor((z[r][c] + spec["base"]) * 100.0 + 0.5) / 100.0
            if s0 <= c < s1:
                v = v - 150.0
            if v0 <= r < v1 and w0 <= c < w1:
                v = math.nan
            out.append(v)
    return out


def _ln_answer(a, case: dict, settings) -> tuple[dict, str | None]:
    """lineament_candidates on an analysed window, with the window's own
    settings and ``settings`` over them (None for the window's own), and
    what parity.mjs compares: the candidates field by field in Python's
    order (the names are carried once, in the section's "fields"), the
    summary's values in its key order, the roses, frame and square shown,
    the progress and captions word for word; and the GeoJSON, told what
    the drainage lines' is (_ta_geojson), apart. A refusal is held word for
    word."""
    from groundwater.config import TerrainConfig
    from groundwater.mapping.elevation import WindowCentre
    from groundwater.mapping.lineaments import lineament_candidates, lineament_captions, lineament_geojson

    cfg = None
    if settings is not None:
        told = {**case["settings"], **settings}
        cfg = TerrainConfig(**{key: tuple(v) if isinstance(v, list) else v for key, v in told.items()})
    heard: list = []
    try:
        result = lineament_candidates(a, cfg, lambda fraction, label: heard.append([fraction, label]))
    except ValueError as refused:
        return {"refused": str(refused)}, None
    lons, lats = _ta_axes(case)
    plan = case["read"]["plan"] if case["read"] else None
    meta = {"label": case["label"], "figure_credit": case["figureCredit"], "notice": case["notice"],
            "surface": _TA_SURFACE, "radius": plan["radiusKm"] if plan else 0.3,
            "centre": WindowCentre(lons[case["cols"] // 2], lats[case["rows"] // 2], case["where"], True)}
    answer = {
        "lineaments": [[item.id, item.kind, [_gt_number(v) for v in item.start], [_gt_number(v) for v in item.end],
                        _gt_number(item.length_m), _gt_number(item.strike_deg), item.pieces, item.cells, item.cut]
                       for item in result.lineaments],
        "summary": [_gt_number(v) if isinstance(v, float) else v for v in result.summary.values()],
        "roses": [[_gt_number(v) for v in result.rose_valley_m], [_gt_number(v) for v in result.rose_ridge_m],
                  list(result.rose_valleys), list(result.rose_ridges)],
        "frame": [_gt_number(v) for v in result.frame], "shown": list(result.shown), "heard": heard,
        "captions": [list(item) for item in lineament_captions(result, case["where"]).items()],
    }
    return answer, lineament_geojson(result, lons, lats, meta)


def lineament_reference() -> dict:
    """The lineament candidates (PLAN.md step 4.2) of the terrain section's
    small windows (T1-T3, T5 and T7, by their index in it) with the
    defaults and LINEAMENT_FINE, each GeoJSON by a short digest and its
    length; the settings both engines refuse, on T5's window round a pit;
    and the generated L1 and L2 with every GeoJSON to the character; with
    the candidates' field names and the summary's keys carried once."""
    from groundwater.mapping.lineaments import Lineament, lineament_candidates

    windows = [_ta_coast(), _ta_plateau(), _ta_ties(), *_ta_degenerate(), *_ta_worded()]
    small = []
    for index, case in enumerate(windows):
        try:
            a, _ = _ta_analysis(case, _ta_unfold(case["z"]))
        except ValueError:
            continue
        for settings in (None, LINEAMENT_FINE):
            answer, geojson = _ln_answer(a, case, settings)
            small.append({"index": index, "settings": settings, "expect": json.dumps(answer, separators=(",", ":")),
                          "geojson": [_ta_short(geojson), len(geojson)]})
    at = 4
    pit = windows[at]
    assert pit["case"].startswith("T5: three cells square"), "the window round a pit"
    a, _ = _ta_analysis(pit, _ta_unfold(pit["z"]))
    refused = [{"index": at, "settings": settings, "refused": _ln_answer(a, pit, settings)[0]["refused"]}
               for settings in LINEAMENT_REFUSED]
    spec = LINEAMENT_GENERATED
    z = lineament_heights(spec)
    window = dict(spec, case="L1", settings=spec["settings"], assumed=None)
    a, _ = _ta_analysis(window, z)
    generated = []
    for kase in spec["cases"]:
        answer, geojson = _ln_answer(a, window, kase["settings"])
        generated.append(dict(kase, expect=json.dumps(answer, separators=(",", ":")), geojson=geojson))
    keys = list(lineament_candidates(a).summary)
    return {
        "fields": [f.name for f in dataclasses.fields(Lineament)], "summary": keys, "small": small,
        "refused": refused, "generated": {**{k: v for k, v in spec.items() if k != "cases"},
                                          "z": [_gt_digest(z), _ta_spots(z)], "cases": generated},
    }


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
#: square's edge.
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
        plan = survey_plan(lin, a.core, a.parts, at(kase["at"]), water, cfg)
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
                       dataclasses.replace(lin.settings, **kase["settings"]))
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
    return {"meta": PLAN_META, "cases": cases, "refused": refused}


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
#: surface water, where the placeholder prior applies.
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


# ------------------------------------- the ledger (PLAN.md step 5.1)

#: Interpretations as the ledger reads them: basement found under two
#: water-bearing zones, basement never resolved and the depth cut back to
#: the depth of investigation, and a shallow dry profile with no zone.
LEDGER_INTERPS = {
    "resolved": {"sounding_id": "VES 1", "depth_to_basement_m": 28.37, "basement_not_resolved": False,
                 "investigation_depth_m": 60.0, "water_zones": [[8.0, 20.0], [24.0, 28.0]],
                 "aquifer_thickness_m": 16.0, "max_drilling_depth_m": 35.0, "drilling_depth_capped": False,
                 "fit_error_percent": 3.456, "site_easting": 708958.4, "site_northing": 926355.5,
                 "layers": [{"top_m": 0.0, "bottom_m": 2.35, "rho": 812.449},
                            {"top_m": 2.35, "bottom_m": 28.37, "rho": 96.05},
                            {"top_m": 28.37, "bottom_m": None, "rho": 4210.0}]},
    "unresolved": {"sounding_id": "VES 2", "depth_to_basement_m": None, "basement_not_resolved": True,
                   "investigation_depth_m": 40.0, "water_zones": [[8.0, 40.0]],
                   "aquifer_thickness_m": 32.0, "max_drilling_depth_m": 40.0, "drilling_depth_capped": True,
                   "fit_error_percent": 13.35, "site_easting": 708990.0, "site_northing": 926370.0,
                   "layers": [{"top_m": 0.0, "bottom_m": 8.0, "rho": 15.25},
                              {"top_m": 8.0, "bottom_m": None, "rho": 47.0}]},
    "dry": {"sounding_id": "Kpètèma 3", "depth_to_basement_m": 6.05, "basement_not_resolved": False,
            "investigation_depth_m": 30.0, "water_zones": [], "aquifer_thickness_m": 0.0,
            "max_drilling_depth_m": 15.0, "drilling_depth_capped": False, "fit_error_percent": 2.0,
            "site_easting": None, "site_northing": None},
}

#: Ranges of models as the ledger reads them: a band quoted with the
#: drilling depths spread, basement found by too few models to quote and the
#: depths flat at the depth of investigation, and a range sampled before it
#: kept the drilling depths.
LEDGER_RANGES = {
    "none": None,
    "band": {"sounding_id": "VES 1", "basement_m": {"p10": 22.14, "p50": 28.25, "p90": 34.05},
             "basement_unresolved": 0.0, "weathered_m": {"p10": 14.0, "p50": 16.05, "p90": 19.25},
             "investigation_depth_m": 60.0,
             "drilling_depth_quantiles_m": [30.0, 31.0, 31.5, 32.0, 33.0, 34.0, 35.0, 35.5, 36.0, 37.0,
                                            38.0, 39.0, 40.0, 41.0, 42.5, 44.0, 46.0, 48.0, 50.0, 53.0,
                                            55.0]},
    "rarely": {"sounding_id": "VES 2", "basement_m": {"p10": 30.0, "p50": 35.0, "p90": 39.0},
               "basement_unresolved": 0.95, "weathered_m": {"p10": 30.6, "p50": 31.0, "p90": 33.1},
               "investigation_depth_m": 40.0, "drilling_depth_quantiles_m": [40.0] * 21},
    "old": {"sounding_id": "VES 1", "basement_m": None, "basement_unresolved": 1.0,
            "weathered_m": {"p10": 10.0, "p50": 12.0, "p90": 15.0}, "investigation_depth_m": 60.0,
            "drilling_depth_quantiles_m": []},
}

#: The suitability score's parts as the ledger reads them, and a ranked
#: siting (as assess_siting returns it) that gives the second and first
#: points theirs, in that order, and the third none.
LEDGER_PARTS = {"aquifer_thickness": 0.64, "resistivity_fit": 0.81234, "overburden": 1.0, "basal_fracture": 0.5}
LEDGER_SITING = [{"index": 1, "components": {"aquifer_thickness": 1.0, "resistivity_fit": 0.4425,
                                              "overburden": 0.5, "basal_fracture": 0.5}},
                 {"index": 0, "components": LEDGER_PARTS}, {"index": None, "components": LEDGER_PARTS}]

#: A chance of success as the ledger reads it.
LEDGER_ODDS = {
    "probability": 0.61234, "low": 0.3875, "high": 0.7805, "prior": 0.55, "effective_n": 10.0,
    "status": "provisional", "matched": "class", "bgs_code": "B-L", "glg": "pCm",
    "success_yield_m3_per_h": 1.0,
    "calibration": "the toolkit's provisional default, adopted by no named person",
}

#: Drilling logs as the ledger reads them: Dr Timbo's own, a dry hole that
#: never reached fresh rock beside VES 1, one with nothing recorded, and an
#: abandoned hole across the boundary between zones 28 and 29.
def _ledger_logs() -> dict:
    log = read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    timbo = {
        "borehole_ref": log.borehole_ref, "total_depth_m": clean(log.total_depth_m),
        "intervals": [{"top_m": clean(i.top_m), "bottom_m": clean(i.bottom_m),
                       "description": i.description} for i in log.intervals],
        "water_strikes_m": clean(log.water_strikes_m), "status": log.status,
        "completion_date": log.completion_date,
        "site": {"easting": clean(log.site.easting), "northing": clean(log.site.northing),
                 "utm_zone": log.site.utm_zone, "contractor": log.site.contractor},
    }
    return {
        "timbo": timbo,
        "dry": {"borehole_ref": "BH-7", "total_depth_m": 45.0,
                "intervals": [{"top_m": 0.0, "bottom_m": 6.0, "description": "Laterite"},
                              {"top_m": 6.0, "bottom_m": 30.0, "description": "Clayey saprolite"},
                              {"top_m": 30.0, "bottom_m": 45.0, "description": "Weathered granite"}],
                "water_strikes_m": [], "status": "Dry hole", "completion_date": "2026-11-02",
                "site": {"easting": 708962.0, "northing": 926351.0, "utm_zone": 28}},
        "bare": {"borehole_ref": "", "total_depth_m": None, "intervals": [], "water_strikes_m": [],
                 "status": "", "completion_date": "", "site": {"easting": None, "northing": None,
                                                               "utm_zone": None}},
        "abandoned": {"borehole_ref": "BH-9", "total_depth_m": 62.5,
                      "intervals": [{"top_m": 0.0, "bottom_m": 12.0, "description": "Sandy clay"},
                                    {"top_m": 12.0, "bottom_m": 40.0,
                                     "description": "Light colour granite, fracture zone 20-22 m"},
                                    {"top_m": 40.0, "bottom_m": 62.5, "description": "Fresh granite"}],
                      "water_strikes_m": [21.0, 41.5], "status": "Abandoned",
                      "completion_date": "", "site": {"easting": 169600.4, "northing": 930929.4,
                                                      "utm_zone": 29, "contractor": " Kaba \t Drilling\n"}},
    }


#: Pumping test analyses as the ledger reads them: a band and a dry-season
#: hold, a yield short of success, one exactly at it with an open band, one
#: with no spread, and a test with no yield to give.
LEDGER_ANALYSES = {
    "none": None,
    "tested": {"yield_recommendation": {"safe_yield_m3_per_h": 2.345, "confidence": "established"},
               "spread": {"bootstrap": {"p10": 1.0}, "safe_yield_low_m3_per_h": 1.875,
                          "safe_yield_high_m3_per_h": 2.995, "holds_at_dry_season": True}},
    "short": {"yield_recommendation": {"safe_yield_m3_per_h": 0.39, "confidence": "indicative"},
              "spread": {"bootstrap": {"p10": 0.2}, "safe_yield_low_m3_per_h": 0.35,
                         "safe_yield_high_m3_per_h": 0.44, "holds_at_dry_season": True}},
    "edge": {"yield_recommendation": {"safe_yield_m3_per_h": 1.0, "confidence": "indicative"},
             "spread": {"bootstrap": {"p10": 0.5}, "safe_yield_low_m3_per_h": 0.8,
                        "safe_yield_high_m3_per_h": None, "holds_at_dry_season": False}},
    "unspread": {"yield_recommendation": {"safe_yield_m3_per_h": 0.995, "confidence": "indicative"},
                 "spread": None},
    "pending": {"yield_recommendation": {"safe_yield_m3_per_h": None, "confidence": "indicative"},
                "spread": None},
}

#: Ledgers as a hand-edited file can hold them.
LEDGER_DIRTY = [
    None, "a ledger", [], {}, {"entries": "none"},
    {"drilled": "gone", "entries": [
        "an entry", {"id": 7, "point": {}, "prediction": {}}, {"id": "", "point": {}, "prediction": {}},
        {"id": "a1", "point": "here", "prediction": {}},
        {"id": "a2", "point": {"sounding_id": 3, "easting": "708958", "northing": True, "utm_zone": 28.5},
         "prediction": {"depth_to_basement_m": "28", "basement_resolved": 1, "water_zones_m": [[8, 20], [24], "x"],
                        "survey_team": 5,
                        "basement_band_m": [1, 2], "drilling_depth_band_m": [30, None],
                        "odds": {"probability": None, "low": 0.2}},
         "before_outcome": "yes", "recorded_on": 20261018,
         "outcome": {"intervals": [[0, 5, "topsoil"], [5, "x", "clay"], [5, 9]], "water_strikes_m": [12, "15"],
                     "contractor": "  WiNGiN \u00a0 Heavy  Duty ",
                     "safe_yield_band_m3_per_h": [0.5], "success": "true", "success_basis": "tested",
                     "status_class": "wet", "utm_zone": 29.0},
         "pairing": {"how": "guessed"}},
        {"id": "a3", "point": {"sounding_id": "B", "utm_zone": 29}, "prediction": {
            "odds": {"probability": 0.5, "bgs_code": 4, "glg": "pCm", "status": None}},
         "before_outcome": True, "outcome": None, "pairing": {"how": "chosen", "distance_m": 4.04}},
        {"id": "a3", "point": {}, "prediction": {}},
        {"id": "a4", "point": {}, "prediction": {}, "outcome": {"success": False,
                                                                "success_basis": "recorded_failure"},
         "pairing": {"how": "nearest", "distance_m": "far"}},
    ]},
    {"drilled": "a5", "entries": [{"id": "a5", "point": {}, "prediction": {},
                                   "outcome": {"safe_yield_band_m3_per_h": [0.5, None]}}]},
]

#: Project files' top levels, as the schema is read from them and migrated.
LEDGER_SCHEMAS = [{}, {"schema": 1}, {"schema": 2, "ledger": {"drilled": None, "entries": []}},
                  {"schema": 3}, {"schema": "2"}, {"schema": True}, {"version": 1}, {"schema": 0.5},
                  {"schema": 2.7}, {"schema": None}]

#: Point identifiers: a name, a position and a place, a half metre that
#: rounds to even, no position, and a name in another script.
LEDGER_IDS = [["VES 1", 708958.4, 926355.5, 28, "Rokel", "Port Loko"],
              ["VES 1", 708958.5, 926356.5, 28, "Rokel", "Port Loko"],
              ["VES 1", None, None, None, "", ""],
              ["VES 1", 708958.0, 926356.0, 28.0, "Rokel", ""],
              ["Kpètèma 3", 166030.0, 930010.0, 29, "Kpètèma", "Bo"]]


def _ledger_run(ops: list) -> list:
    """Each step of a scenario applied in turn, and the ledger (and what
    else the step returns) after it. parity.mjs runs the same steps."""
    from groundwater import ledger as L

    held = L.empty_ledger()
    out = []
    for op in ops:
        config = Config()
        if op.get("within") is not None:
            config.ledger.pair_within_m = op["within"]
        if op["op"] == "record":
            held, kept = L.record_predictions(held, op["predictions"], op["on"], op["known"], "0.3.0")
            out.append({"ledger": held, "kept": kept})
        elif op["op"] == "choose":
            held = dict(held, drilled=op["id"] if op["id"] is None or isinstance(op["id"], str)
                        else held["entries"][op["id"]]["id"])
            out.append({"ledger": L.clean_ledger(held)})
        elif op["op"] == "pair":
            pid, pairing = L.pair_drilled(held, op["outcome"], config)
            out.append({"id": pid, "pairing": pairing})
        elif op["op"] == "attach":
            held = L.attach_outcome(held, op["outcome"], config)
            out.append({"ledger": held})
    return out


def ledger_reference(rokel_interps, rokel_sites, short_ranges, rokel_odds) -> dict:
    """The ledger (PLAN.md step 5.1): predictions over every kind of point
    and range, outcomes over every kind of log and test, scenarios of
    recording, pairing and attaching, cleaning hand-edited ledgers, the
    comparison's words, pooling, point identifiers, the project file's
    schema and its migration, and the real Rokel survey."""
    from groundwater import ledger as L
    from groundwater.project_io import deserialize_project, migrate_payload, payload_schema, serialize_project

    config = Config()
    wider = Config()
    wider.odds.success_yield_m3_per_h = 3.6
    predictions = []
    for iname, interp in LEDGER_INTERPS.items():
        for rname, r in LEDGER_RANGES.items():
            for with_odds in (False, True):
                odds = LEDGER_ODDS if with_odds else None
                # the score's parts with the odds, so each kind of point is
                # recorded both with and without them
                parts = LEDGER_PARTS if with_odds else None
                predictions.append({"interp": iname, "range": rname, "odds": with_odds, "parts": with_odds,
                                    "expect": L.point_prediction(_ns(interp), _ns(r), _ns(odds), config, "",
                                                                 _ns(parts))})
    logs = _ledger_logs()
    outcomes = []
    for lname, log in logs.items():
        for aname, analysis in LEDGER_ANALYSES.items():
            outcomes.append({"log": lname, "analysis": aname, "wider": False,
                             "expect": L.completion_outcome(_ns(log), _ns(analysis), config)})
    for aname in ("tested", "short"):
        outcomes.append({"log": "timbo", "analysis": aname, "wider": True,
                         "expect": L.completion_outcome(_ns(logs["timbo"]), _ns(LEDGER_ANALYSES[aname]), wider)})
    # the project's drilling contractor, which wins over the log's own
    for lname, log in logs.items():
        outcomes.append({"log": lname, "analysis": "none", "wider": False, "contractor": "  Sierra   Drilling ",
                         "expect": L.completion_outcome(_ns(log), None, config, contractor="  Sierra   Drilling ")})

    site = {"community": "Rokel", "district": "Port Loko", "utm_zone": 28}
    # each point's survey team: its own sheet's field supervisor, else the
    # project's, written as typed with its white space tidied
    surveys = []
    for teams in (None, ["  A.  Kamara\t", "", None], ["B. Sesay"]):
        for supervisor in (None, "  R.  Conteh ", 7):
            where = site if supervisor is None else dict(site, supervisor=supervisor)
            # the ranked siting with the first site only
            siting = LEDGER_SITING if supervisor is None else None
            surveys.append({"teams": teams, "site": where, "siting": siting, "expect": L.survey_predictions(
                [_ns(LEDGER_INTERPS[k]) for k in ("resolved", "unresolved", "dry")],
                [_ns(LEDGER_RANGES["band"]), None, None], [_ns(LEDGER_ODDS), _ns(LEDGER_ODDS), None],
                _ns(where), config, teams, _ns(siting))})
    survey = surveys[4]["expect"]
    resurvey = L.survey_predictions(
        [_ns(LEDGER_INTERPS[k]) for k in ("resolved", "unresolved")],
        [_ns(LEDGER_RANGES["old"]), _ns(LEDGER_RANGES["rarely"])], None, _ns(site), config)
    extra = L.survey_predictions([_ns(dict(LEDGER_INTERPS["resolved"], sounding_id="VES 4",
                                           site_easting=709300.0))], None, None, _ns(site), config)
    dry = next(o["expect"] for o in outcomes if o["log"] == "dry" and o["analysis"] == "none")
    timbo = next(o["expect"] for o in outcomes if o["log"] == "timbo" and o["analysis"] == "short")
    across = next(o["expect"] for o in outcomes if o["log"] == "abandoned" and o["analysis"] == "tested")
    scenarios = {
        "drilled": [
            {"op": "record", "predictions": survey, "on": "2026-10-01", "known": False},
            {"op": "record", "predictions": resurvey, "on": "2026-10-05", "known": False},
            {"op": "pair", "outcome": dry},
            {"op": "attach", "outcome": dry},
            {"op": "record", "predictions": survey + extra, "on": "2026-11-20", "known": True},
            {"op": "attach", "outcome": None},
            {"op": "choose", "id": 1},
            {"op": "attach", "outcome": dry},
            {"op": "choose", "id": "not an entry"},
            {"op": "attach", "outcome": dry},
            {"op": "pair", "outcome": dry, "within": 4.0},
            {"op": "attach", "outcome": timbo},
            {"op": "choose", "id": None},
            {"op": "attach", "outcome": timbo},
        ],
        "after": [
            {"op": "record", "predictions": survey[:1], "on": "2026-12-01", "known": True},
            {"op": "pair", "outcome": None},
            {"op": "pair", "outcome": timbo},
            {"op": "attach", "outcome": timbo},
            {"op": "record", "predictions": resurvey[:1], "on": "2026-12-02", "known": True},
        ],
        "across": [
            # a point in zone 28 near its eastern edge and a log written in
            # zone 29, the same place a few metres apart
            {"op": "record", "predictions": [{"point": dict(survey[0]["point"], easting=830391.2,
                                                            northing=930924.1),
                                              "prediction": survey[0]["prediction"]},
                                             survey[1]], "on": "2026-10-01", "known": False},
            {"op": "pair", "outcome": across},
            {"op": "attach", "outcome": across},
        ],
    }
    scenario_out = {name: _ledger_run(ops) for name, ops in scenarios.items()}

    texts = []
    for i, p in enumerate(predictions):
        for j, o in enumerate([None] + [o["expect"] for o in outcomes]):
            if (i + 2 * j) % 7:
                continue
            entry = {"prediction": p["expect"], "outcome": o}
            texts.append({"prediction": i, "outcome": j - 1,
                          "check": L.basement_check(p["expect"], o),
                          "outcome_text": L.outcome_text(o), "rows": L.entry_rows(entry)})

    drilled = scenario_out["drilled"]
    pool_items = [["Rokel", drilled[-1]["ledger"]], ["Rokel copy", drilled[1]["ledger"]],
                  ["Kuntolo", scenario_out["across"][-1]["ledger"]], ["Junk", "not a ledger"],
                  ["Rokel again", drilled[3]["ledger"]]]
    pooled = L.pool_ledgers([tuple(item) for item in pool_items])
    header, rows = L.ledger_rows(pooled)

    on_file = copy.deepcopy(drilled[3]["ledger"])
    for entry in on_file["entries"]:
        if entry["outcome"] is not None:
            # long and with a dash PyYAML escapes, so it is folded in double quotes
            entry["outcome"]["status"] = ("Abandoned – the casing collapsed at 30 m after the second airlift, "
                                          "and the crew moved the rig to the reserve site")
    saved = serialize_project({"meta_community": "Kpètèma", "prediction_ledger": on_file}, "0.3.0")
    rokel_survey = L.survey_predictions(
        rokel_interps, [_ns(r) for r in short_ranges], [_ns(o) for o in rokel_odds],
        rokel_sites[0], config)
    return {
        "predictions": predictions,
        "interps": LEDGER_INTERPS, "ranges": LEDGER_RANGES, "odds": LEDGER_ODDS, "parts": LEDGER_PARTS,
        "logs": logs, "analyses": LEDGER_ANALYSES,
        "outcomes": outcomes,
        "site": site,
        "surveys": surveys,
        "scenarios": {name: {"ops": ops, "expect": scenario_out[name]} for name, ops in scenarios.items()},
        "texts": texts,
        "dirty": [{"raw": raw, "expect": L.clean_ledger(raw)} for raw in LEDGER_DIRTY],
        "pool": {"items": pool_items, "pooled": pooled, "counts": L.ledger_counts(pooled),
                 "header": header, "rows": rows, "none": list(L.ledger_rows([])),
                 "entry_header": L.entry_header(), "summary": L.ledger_summary(pooled),
                 "summary_none": L.ledger_summary([])},
        # a Streamlit project file holding a ledger with an outcome, a name
        # YAML writes escaped, positions left out and a quoted calibration,
        # as the browser's YAML reader has to read it
        "file": {"yaml": saved.decode("utf-8"),
                 "expect": deserialize_project(saved)["prediction_ledger"]},
        "ids": [{"args": args, "expect": L.point_id(*args)} for args in LEDGER_IDS],
        "schemas": [{"payload": p, "schema": payload_schema(p), "migrated": migrate_payload(p)}
                    for p in LEDGER_SCHEMAS],
        "rokel": rokel_survey,
    }


# ------------------------- the calibration report (PLAN.md step 5.2)

#: Survey teams and contractors as typed: one name in two spacings, a name
#: with an accent, letters beyond the Basic Multilingual Plane and a
#: full-width one (which JavaScript's < orders the other way round), a name
#: that is a number, one that is an object's key in JavaScript, and none.
CALIBRATION_TEAMS = ["A. Kamara", "  A.  Kamara", "B. Sesay", "", "Ñdoye", "\U0001d4b5 Team", "ｱ Team",
                     "1", "__proto__"]
CALIBRATION_CONTRACTORS = ["WiNGiN", "Kaba Drilling", "", "Kaba  Drilling ", "\U0001d4b5 Drill", "ｱ Drill"]
#: The ground under a point as its odds read it: a class and a unit, a class
#: alone, no class.
CALIBRATION_GROUND = [("B-L", "pCm"), ("B-L", None), ("CSF-L/M", "pCm"), (None, None), ("U-M/H", "Qe")]
#: Chances on the reliability bins' edges, and two a hand-edited file holds
#: outside 0 to 1.
CALIBRATION_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, -0.1]


def _pick(rng, values):
    """One of ``values``, by random() alone, whose stream every Python keeps."""
    return values[min(len(values) - 1, int(rng.random() * len(values)))]


def _calibration_entry(rng, k: int, inside_share: float, skill: str, priors: bool) -> dict:
    """A ledger entry as a file holds it: a band the depth found falls in
    ``inside_share`` of the time, a chance of success that is informative,
    contrary or the prior itself (``skill``), and the rest drawn."""
    p10 = round(8.0 + 30.0 * rng.random(), 1)
    band = [p10, round(p10 + 4.0, 1), round(p10 + 4.0 + 6.0 * rng.random(), 1)]
    has_band = rng.random() > 0.1
    best = None if rng.random() < 0.08 else round(band[1] + 3.0 * (rng.random() - 0.5), 1)
    total = round(band[2] + 20.0 * rng.random() - 8.0, 1)
    u = rng.random()
    if u < inside_share:
        found = round(band[0] + (band[2] - band[0]) * rng.random(), 1)
    elif u < inside_share + (1.0 - inside_share) / 2.0:
        found = round(max(0.5, band[0] - 1.0 - 6.0 * rng.random()), 1)
    else:
        found = round(band[2] + 1.0 + 8.0 * rng.random(), 1)
    if found > total or rng.random() < 0.1:
        found = None
    prior = 0.55 if priors else (None if rng.random() < 0.3 else 0.55)
    chance = round(rng.random(), 3) if rng.random() > 0.15 else _pick(rng, CALIBRATION_EDGES)
    succeeds = rng.random() < (min(1.0, max(0.0, chance)) if skill == "better" else
                               1.0 - min(1.0, max(0.0, chance)) if skill == "worse" else 0.55)
    if skill == "same":
        chance = prior if prior is not None else 0.55
    success = None if rng.random() < 0.08 else succeeds
    basis = None if success is None else _pick(rng, ["tested", "recorded_failure" if not success
                                                     else "recorded_success"])
    code, glg = _pick(rng, CALIBRATION_GROUND)
    drilled = rng.random() < 0.85
    return {
        "id": f"cal{k:04d}",
        "before_outcome": rng.random() < 0.85,
        "recorded_on": "2026-03-01",
        "toolkit": "0.3.0",
        "point": {"sounding_id": f"VES {k}", "community": "", "district": "", "easting": None,
                  "northing": None, "utm_zone": None},
        "prediction": {
            "depth_to_basement_m": best, "basement_resolved": best is not None,
            "investigation_depth_m": 60.0, "water_zones_m": [], "drilling_depth_m": 40.0,
            "drilling_depth_minimum": False, "basement_band_m": band if has_band else None,
            "survey_team": _pick(rng, CALIBRATION_TEAMS),
            "odds": None if rng.random() < 0.08 else {
                "probability": chance, "low": 0.1, "high": 0.9, "prior": prior, "bgs_code": code, "glg": glg,
                "status": "provisional", "matched": "class"},
        },
        "outcome": None if not drilled else {
            "basement_m": found, "total_depth_m": None if rng.random() < 0.05 else total,
            "status": "Successful" if success else "Dry", "success": success, "success_basis": basis,
            "safe_yield_m3_per_h": None, "success_yield_m3_per_h": 1.0,
            "contractor": _pick(rng, CALIBRATION_CONTRACTORS)},
        "pairing": None,
    }


def _calibration_portfolio(seed: int, n: int, inside_share: float, skill: str, priors: bool = True) -> list:
    import random

    rng = random.Random(seed)
    items, k = [], 0
    for project in ("Rokel", "Kuntolo", "Dr Timbo"):
        entries = []
        for _ in range(n // 3):
            entries.append(_calibration_entry(rng, k, inside_share, skill, priors))
            k += 1
        items.append([project, {"drilled": None, "entries": entries}])
    # a copy of the first project's file, pooled once
    items.append(["Rokel copy", copy.deepcopy(items[0][1])])
    return items


def calibration_reference() -> dict:
    """The calibration report (PLAN.md step 5.2) on pooled portfolios built
    to give each verdict: a band that holds about four in five, one too
    narrow and one too wide; odds that beat the prior, odds that lose to it
    and odds that are the prior; a portfolio too small to judge, one with
    nothing forecast, one with nothing drilled and none at all; each under
    the default settings and others. And the binomial range the band's
    count is judged by (tests/test_calibration.py holds it to scipy's)."""
    from groundwater import calibration as K
    from groundwater import ledger as L

    portfolios = {
        "calibrated": _calibration_portfolio(1, 45, 0.8, "better"),
        "narrow": _calibration_portfolio(2, 36, 0.45, "worse"),
        "wide": _calibration_portfolio(3, 45, 1.0, "same"),
        "priorless": _calibration_portfolio(4, 24, 0.8, "better", priors=False),
        "few": _calibration_portfolio(5, 9, 0.8, "better"),
        "after": [["Rokel", {"entries": [dict(e, before_outcome=False) for e in
                                         _calibration_portfolio(6, 18, 0.8, "better")[0][1]["entries"]]}]],
        "undrilled": [["Rokel", {"entries": [dict(e, outcome=None) for e in
                                             _calibration_portfolio(7, 18, 0.8, "better")[0][1]["entries"]]}]],
        "empty": [],
    }
    settings = [{}, {"min_boreholes": 3, "min_group": 2, "reliability_bins": 3},
                {"min_boreholes": 40, "min_group": 12, "reliability_bins": 10}]
    # every portfolio under the defaults, and some under each of the others
    others = {1: ("calibrated", "narrow", "few"), 2: ("wide", "priorless")}
    cases = []
    for name, items in portfolios.items():
        for k, overrides in enumerate(settings):
            if k and name not in others[k]:
                continue
            config = Config()
            for key, value in overrides.items():
                setattr(config.ledger, key, value)
            pooled = L.pool_ledgers([tuple(item) for item in items])
            cases.append({"portfolio": name, "settings": overrides, "issued": "  2026-10-19 " if k else "",
                          "expect": {
                              "depth": K.depth_scores(pooled, config),
                              "odds": K.odds_scores(pooled, config),
                              "hits": {by: K.hit_rates(pooled, by, config) for by in K.GROUPINGS},
                              "content": K.calibration_content(pooled, "  2026-10-19 " if k else "", config)}})
    ranges = [{"n": n, "p": p, "expect": list(K.binomial_range(n, p))}
              for n in (0, 1, 2, 5, 10, 11, 30, 97, 400, 2500) for p in (0.8, 0.5, 0.05)]
    return {"portfolios": portfolios, "cases": cases, "ranges": ranges}


# ----------------------------------------------- calibration sets (step 5.3)

def _set_entry(rng, k: int, unit: str, code: str, success_share: float, judged_at: float = 1.0) -> dict:
    """A ledger entry a calibration set is fitted from: a best fit of a
    clay, a weathered and a basement layer, the log that drilled through
    them, the score's parts and the chance recorded with them. Basement
    reads under 3,000 ohm-m in about half the holes, so its edge moves;
    the holes with a fracture at the contact succeed more often."""
    clay_base = round(rng.uniform(4.0, 9.0), 1)
    basement = round(rng.uniform(clay_base + 12.0, 38.0), 1)
    fracture = round(rng.uniform(0.0, 1.0), 3)
    success = rng.random() < success_share * (0.6 + 0.8 * fracture)
    chance = round(rng.uniform(0.25, 0.85), 3)
    return {
        "id": f"set{k:03d}", "before_outcome": rng.random() < 0.85, "recorded_on": "2026-04-01",
        "toolkit": "0.3.0", "point": {"sounding_id": f"VES {k}"},
        "prediction": {
            "investigation_depth_m": rng.choice([60.0, 45.0, 80.0]),
            "layers": [[0.0, 1.5, round(rng.uniform(300.0, 1500.0), 1)],
                       [1.5, clay_base, round(rng.uniform(6.0, 28.0), 1)],
                       [clay_base, basement, round(rng.uniform(22.0, 420.0), 1)],
                       [basement, None, round(rng.uniform(1100.0, 6500.0), 1)]],
            "suitability": {"aquifer_thickness": round(rng.random(), 3), "resistivity_fit": round(rng.random(), 3),
                            "overburden": round(rng.random(), 3), "basal_fracture": fracture},
            "odds": {"probability": chance, "prior": rng.choice([0.428, 0.428, 0.5, 0.966]), "bgs_code": code,
                     "glg": unit, "low": 0.2, "high": 0.9, "effective_n": 10.0, "status": "provisional",
                     "matched": "combination", "success_yield_m3_per_h": judged_at, "calibration": "x"}},
        "outcome": {"total_depth_m": round(basement + rng.uniform(4.0, 25.0), 1),
                    "intervals": [[0.0, 1.5, "laterite"], [1.5, clay_base, "clay"],
                                  [clay_base, basement, rng.choice(["weathered", "weathered", "saprolite", "sand"])],
                                  [basement, 100.0, "basement"]],
                    "success": success, "success_basis": "tested", "success_yield_m3_per_h": judged_at,
                    "safe_yield_m3_per_h": 2.0 if success else 0.4},
    }


def _set_portfolio(seed: int, n: int) -> list:
    import random

    rng = random.Random(seed)
    grounds = [("pCm", "B-L"), ("Pi", "I-L"), ("Qe", "U-M/H"), ("Mi", "B-L")]
    items, k = [], 0
    for project in ("Rokel", "Kuntolo", "Dr Timbo"):
        entries = []
        for _ in range(n // 3):
            unit, code = grounds[k % len(grounds)]
            entries.append(_set_entry(rng, k, unit, code, 0.55))
            k += 1
        items.append([project, {"drilled": None, "entries": entries}])
    items.append(["Rokel copy", copy.deepcopy(items[0][1])])
    return items


def calibration_sets_reference() -> dict:
    """Calibration sets (PLAN.md step 5.3) fitted to pooled portfolios: one
    with enough boreholes to fit every row, edge and weight, one too small to
    fit any, one whose boreholes were judged at another definition of
    success, did not say whether they succeeded, recorded no odds or no
    layers, or stand on ground with no cited rate, and none at all; each
    under the default settings and others. Each set adopted, named, written
    to its file and read back, and hand-edited files read or refused."""
    from groundwater import calibration_sets as CS
    from groundwater import ledger as L

    import random

    rng = random.Random(53)
    mixed = []
    for k, (unit, code) in enumerate([("pCm", "B-L")] * 6 + [("Pi", None)] * 2 + [(None, "n/a")] * 2):
        entry = _set_entry(rng, 500 + k, unit, code, 0.5, judged_at=3.6 if k == 1 else 1.0)
        if k == 2:
            entry["outcome"]["success"] = None
        if k == 3:
            entry["prediction"]["odds"] = None
        if k == 4:
            entry["prediction"]["layers"] = []
            entry["prediction"]["suitability"] = None
        if k == 5:
            entry["outcome"] = None
        mixed.append(entry)
    portfolios = {
        "fit": _set_portfolio(1, 36),
        "few": _set_portfolio(2, 9),
        "mixed": [["Kpètèma", {"drilled": None, "entries": mixed}]],
        "empty": [],
    }
    settings = [{}, {"ledger": {"fit_min_boreholes": 2, "fit_weights_min_each": 3}},
                {"ledger": {"fit_min_boreholes": 2, "fit_weights_min_each": 2},
                 "ves": {"clay_max_rho": 35.0, "fresh_basement_min_rho": 1500.0}},
                {"ledger": {"fit_min_boreholes": 2, "fit_weights_min_each": 2},
                 "odds": {"success_yield_m3_per_h": 3.6}}]
    earlier = CS.adopt_set(CS.fit_set([], "2026-01-01"), "Earlier Person", "2026-01-02")
    cases = []
    for name, items in portfolios.items():
        for k, overrides in enumerate(settings):
            # the mixed portfolio under every setting, the others under the
            # ones that change what they fit (another definition of success
            # leaves out all but the mixed portfolio's one borehole judged at
            # it)
            if name != "mixed" and k not in {"fit": (0, 2), "few": (0, 1), "empty": (0,)}[name]:
                continue
            config = Config()
            for section, values in overrides.items():
                for key, value in values.items():
                    setattr(getattr(config, section), key, value)
            pooled = L.pool_ledgers([tuple(item) for item in items])
            fitted = CS.fit_set(pooled, "2026-10-20", config)
            adopted = CS.adopt_set(fitted, "  A.\tKamara ", "2026-10-21", earlier if k == 2 else None)
            # the rows are the set's; the ids behind each fitted one are not
            # in it, and are held here
            # (by their positions as text, as JSON keys them)
            used = json.loads(json.dumps([CS.fit_prior(pooled, config)[1], CS.fit_edges(pooled, config)[1],
                                          CS.fit_weights(pooled, config)[1]]))
            cases.append({"portfolio": name, "settings": overrides, "in_force": k == 2, "expect": {
                "used": used, "set": fitted, "adopted": adopted,
                "names": [CS.set_name(fitted), CS.set_name(adopted)], "yaml": CS.set_yaml(adopted)}})
    # the mixed portfolio's set with every kind of row fitted, the smallest
    good = json.loads(json.dumps(next(c for c in cases if c["portfolio"] == "mixed"
                                      and c["settings"] == settings[1])["expect"]["adopted"]))

    def broken(change):
        raw = copy.deepcopy(good)
        change(raw)
        return raw

    hand = [good, None, [good], dict(good, format="a list of boreholes"), dict(good, format_version=2),
            dict(good, version=None), dict(good, adopted_by=" "), dict(good, version=-1),
            broken(lambda r: r.pop("edges")), broken(lambda r: r["prior"][0].update(rate=0.0)),
            broken(lambda r: r["prior"][0].update(fitted=False, rate=None, effective_n=None)),
            broken(lambda r: r["edges"][1].update(misread=1.5)),
            broken(lambda r: r["weights"]["value"].update(overburden=0.5)),
            broken(lambda r: r["boreholes"][0].update(uses=["prior", "laterite_min_rho"])),
            broken(lambda r: r["boreholes"][1].update(id="")),
            broken(lambda r: r["replaces"].update(version="0")),
            broken(lambda r: r.update(adopted_by="  B.   Sesay  "))]
    read = []
    for raw in hand:
        try:
            read.append({"ok": CS.clean_set(raw)})
        except ValueError as exc:
            read.append({"threw": str(exc)})
    refusals = []
    for who in ("", " \t ", None):
        try:
            CS.adopt_set(cases[0]["expect"]["set"], who, "2026-10-21")
        except ValueError as exc:
            refusals.append(str(exc))
    try:
        CS.adopt_set(cases[0]["expect"]["adopted"], "B. Sesay", "2026-10-22")
    except ValueError as exc:
        refusals.append(str(exc))
    return {"portfolios": portfolios, "earlier": earlier, "cases": cases, "hand": hand, "read": read,
            "refusals": refusals, "default": CS.default_set(), "default_name": CS.set_name(CS.default_set()),
            "default_yaml": CS.set_yaml(CS.default_set())}


# ----------------------------------------- a calibration set in force (5.3b)

#: A set adopted to be put in force: the prior of B-L on pCm and of I-L on
#: any unit fitted, CSF-L/M on pCm counted and not; both edges of pCm fitted
#: and none of Qe's; and the suitability weights.
IN_FORCE_SET = {
    "format": "groundwater calibration set", "format_version": 1, "version": 3, "fitted_on": "2027-03-01",
    "adopted_by": "A. Kamara", "adopted_on": "2027-03-02",
    "replaces": {"version": 2, "fitted_on": "2026-11-01", "adopted_by": "B. Sesay", "adopted_on": "2026-11-02"},
    "success_yield_m3_per_h": 1.0,
    "boreholes": [{"id": f"b{k}", "success": k % 2 == 0, "forecast": True, "uses": ["prior"]} for k in range(12)],
    "left_out": {"unknown": 0, "definition": 0},
    "prior": [
        {"bgs_code": "B-L", "glg": "pCm", "boreholes": 12, "successes": 9, "expected": 8.2, "base_rate": 0.4279,
         "base_n": 10.0, "fitted": True, "rate": 0.6123, "effective_n": 22.0},
        {"bgs_code": "I-L", "glg": "*", "boreholes": 6, "successes": 1, "expected": 1.0, "base_rate": 0.4279,
         "base_n": 10.0, "fitted": True, "rate": 0.3299, "effective_n": 16.0},
        {"bgs_code": "CSF-L/M", "glg": "pCm", "boreholes": 3, "successes": 3, "expected": 3.0, "base_rate": 0.7,
         "base_n": 10.0, "fitted": False, "rate": None, "effective_n": None},
    ],
    "edges": [
        {"glg": "pCm", "edge": "clay_max_rho", "boreholes": 8, "below": 8, "above": 20, "base": 20.0,
         "misread_base": 3, "fitted": True, "value": 31.5, "misread": 1},
        {"glg": "pCm", "edge": "fresh_basement_min_rho", "boreholes": 8, "below": 28, "above": 8, "base": 3000.0,
         "misread_base": 4, "fitted": True, "value": 1500.0, "misread": 0},
        {"glg": "Qe", "edge": "fresh_basement_min_rho", "boreholes": 2, "below": 3, "above": 2, "base": 3000.0,
         "misread_base": 1, "fitted": False, "value": None, "misread": None},
    ],
    "weights": {"successes": 12, "failures": 11,
                "base": {"aquifer_thickness": 0.35, "resistivity_fit": 0.25, "overburden": 0.2, "basal_fracture": 0.2},
                "right_base": 0.61, "fitted": True,
                "value": {"aquifer_thickness": 0.25, "resistivity_fit": 0.1, "overburden": 0.1, "basal_fracture": 0.55},
                "right": 0.74},
}

#: The grounds the odds are asked about, the units the edges are asked for,
#: sounding positions (Kpètèma on pCm, Rokel on Qe, none, and one whose zone
#: its easting implies) and models to interpret by each unit's edges.
IN_FORCE_GROUNDS = [["B-L", "pCm"], ["B-L", "Pi"], ["I-L", "Pi"], ["I-L", "Mi"], ["CSF-L/M", "pCm"],
                    ["U-M/H", "Qe"], ["n/a", None], [None, None], ["B-L", None]]
IN_FORCE_UNITS = ["pCm", "Qe", "Pi", None]
IN_FORCE_POSITIONS = [[166030.0, 930010.0, 29], [708958.4, 926355.5, 28], [None, None, None],
                      [250000.0, 900000.0, None]]
IN_FORCE_MODELS = [[[400.0, 90.0, 2000.0, 5000.0], [2.0, 18.0, 10.0]], [[300.0, 25.0, 140.0, 4000.0], [1.5, 6.0, 20.0]],
                   [[600.0, 120.0, 1200.0], [3.0, 30.0]], [[250.0, 12.0, 2500.0], [2.0, 10.0]]]


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


def rounds_reference() -> dict:
    """Service rounds (PLAN.md step 7.3): what is due at each borehole of a
    register on a day, by area mechanic and in the order of the walk, with
    the words and the round sheet's parts; and each record's state as the
    registry reads it, the routine inspection among its visits. Named cases
    for each rule, then registers drawn from seeds. The cases carry their
    own inputs, so parity.mjs gives the browser exactly these."""
    import random as _random
    from dataclasses import asdict as _asdict
    from datetime import date as _date

    from groundwater import rounds as RD
    from groundwater.registry import Schedule, asset_from_dict, asset_state, mint_asset_id

    def ident(easting, northing=938150.0, zone=28, district="Western Area Rural"):
        return mint_asset_id(SiteMetadata(district=district, easting=easting,
                                          northing=northing, utm_zone=zone))

    def record(easting, *events, northing=938150.0, **fields):
        return {"asset_id": ident(easting, northing), "community": "Case",
                "district": "Western Area Rural", "easting": easting, "northing": northing,
                "utm_zone": 28, "events": list(events), **fields}

    def ev(when, kind, **more):
        return {"when": when, "kind": kind, **more}

    old, late = ev("2019-01-10", "commissioned"), ev("2022-01-10", "commissioned")
    aggressive = {"material": "stainless steel", "inspection_months": 6, "chemistry": "aggressive"}
    plain = {"material": "galvanised iron", "inspection_months": 12, "chemistry": "not_aggressive"}
    named = {
        # four on a line at 0, 1, 3 and 6 km: the walk starts at the one due
        # longest and goes to the nearest each time
        "walk": [record(694000.0, late), record(695000.0, late), record(697000.0, old),
                 record(700000.0, late)],
        # equidistant either side of the start: the lower identifier first
        "tie": [record(696000.0, late), record(694000.0, late), record(695000.0, old)],
        "silent": [record(694000.0)],
        "not_due_and_gone": [record(694000.0, ev("2024-05-20", "commissioned")),
                             record(695000.0, late, ev("2022-08-01", "decommissioned")),
                             record(696000.0, late)],
        "routine_by_design": [record(694000.0, late, ev("2023-11-20", "routine_inspection"),
                                     rising_main=aggressive),
                              record(695000.0, late, ev("2023-11-20", "routine_inspection"),
                                     rising_main=plain),
                              record(696000.0, late, ev("2023-11-20", "repair"))],
        "mechanics": [record(694000.0, late, chiefdom="Koya"),
                      record(695000.0, late, chiefdom="KORI"),
                      record(696000.0, late, chiefdom="Bo Town"),
                      record(697000.0, late, chiefdom="koya", area_mechanic=" Zainab ")],
        "merged": [record(694000.0, late), {**record(694000.0, ev("2024-05-30", "routine_inspection")),
                                            "community": "", "area_mechanic": "A. Bangura",
                                            "rising_main": aggressive},
                   {"asset_id": "not one"}],
        "unplaced": [record(694000.0, late), {**record(700000.0, late), "easting": None},
                     {**record(690000.0, late), "easting": "690000"},
                     {**record(698000.0, late), "utm_zone": "28"}],
        "beyond": [record(694000.0, ev("9999-08-01", "commissioned"))],
        "zones": [record(694000.0, late), {**record(280400.0, late, northing=925600.0),
                                            "asset_id": ident(280400.0, 925600.0, 29, "Kailahun"),
                                            "utm_zone": 29}],
    }
    table = "Koya: M. Kolleh\nkori: A. Bangura\nno colon\nKOYA: Someone Else\n: blank\n"
    cases = []

    def case(name, assets, as_of="2024-06-01", mechanics=table, schedule=None, sheets=True):
        plan = Schedule(**{**_asdict(Schedule()), **(schedule or {})})
        parsed = RD.parse_area_mechanics(mechanics)
        result = RD.service_rounds(assets, as_of, plan, parsed["entries"])
        states = []
        for raw in assets:
            asset = asset_from_dict(raw)
            states.append(None if asset is None
                          else asset_state(asset, _date.fromisoformat(as_of), plan).as_dict())
        rounds = []
        for one in result["rounds"]:
            told = {"text": RD.round_text(one), "rows": RD.round_rows(one)}
            if sheets:
                told["sheets"] = [RD.stop_sheet(stop) for stop in one["stops"]]
            rounds.append(told)
        cases.append({
            "name": name, "assets": assets, "as_of": as_of, "mechanics": mechanics,
            "schedule": schedule or {}, "sheets": sheets,
            "expect": {"parsed": parsed, "result": result, "words": RD.rounds_text(result),
                       "rounds": rounds, "states": states},
        })

    # the round sheet's parts are held where they differ most: the three
    # visits' boxes and bases, and merged records with a mechanic named
    with_sheets = {"routine_by_design", "merged"}
    for name, assets in named.items():
        case(name, assets, as_of="9999-12-31" if name == "beyond" else "2024-06-01",
             sheets=name in with_sheets)
    case("empty", [])
    case("schedule", named["routine_by_design"], sheets=False,
         schedule={"water_sample_months": 3, "grace_days": 0, "routine_inspection_months": 24})
    # registers drawn from seeds: a patch of zone 28 where legs tie and stops
    # coincide, second records of one borehole, and positions, mechanics and
    # rising mains that are not what they should be. The round sheet's parts
    # are held on two named cases only, to keep this section small
    # (tests/test_rounds.py holds them on its own seeded registers)
    days = ["2019-03-01", "2020-01-10", "2022-08-01", "2023-05-20", "2023-11-20", "2023-12-01",
            "2024-01-31", "2024-05-01", "2024-06-01", "2024-07-15", "2099-01-01", "not written"]
    kinds = ["commissioned", "inspection", "routine_inspection", "water_sample", "repair",
             "failure", "restored", "decommissioned", "note"]
    for seed in range(6):
        rng = _random.Random(f"rounds {seed}")
        assets, ids = [], []
        for _ in range(rng.randint(1, 9)):
            easting = rng.choice([694000.0, 694500.0, 695000.0, 696000.0,
                                  round(rng.uniform(690000.0, 700000.0), 1)])
            northing = rng.choice([938150.0, round(rng.uniform(930000.0, 940000.0), 1)])
            if ids and rng.random() < 0.2:
                asset_id = rng.choice(ids)
            else:
                asset_id = ident(easting, northing)
                ids.append(asset_id)
            raw = {"asset_id": asset_id, "community": rng.choice(["Rokel", "", None]),
                   "district": "Western Area Rural",
                   "chiefdom": rng.choice(["Koya", "KORI", "", None, "Bumpe Ngao"]),
                   "easting": rng.choice([easting] * 9 + [None]), "northing": northing,
                   "utm_zone": rng.choice([28] * 9 + [None]),
                   "events": [ev(rng.choice(days), rng.choice(kinds))
                              for _ in range(rng.choice([0, 1, 2, 3, 5]))]}
            if rng.random() < 0.4:
                raw["area_mechanic"] = rng.choice(["A. Bangura", " M. Kolleh ", "", 7])
            if rng.random() < 0.5:
                raw["rising_main"] = rng.choice([aggressive, plain, {"inspection_months": 9},
                                                 {"inspection_months": 6.5}])
            assets.append(raw)
        case(f"seed {seed}", assets, as_of=rng.choice(["2024-06-01", "2024-02-29"]), sheets=False)
    return clean({"cases": cases})


def sanitary_reference() -> dict:
    """Sanitary inspection (PLAN.md step 7.5): forms scored and laid out as a
    table, counts graded, and the latest inspection read with the E. coli
    count of a sample into one statement, over every way each side can be
    known, partly known or unknown. The cases carry their own inputs, so
    parity.mjs gives the browser exactly these."""
    from groundwater import sanitary as SAN
    from groundwater.registry import Asset, clean_answers, iso_date, merge_events, trim_field

    asset_id = "SL-WAR-8FEEVKQ-T"
    forms = ["YNNYNNYNYN", "YNN--NYN-N", "----------", "NNNNNNNNNN", "YYYYYYYYYY",
             "yn", "YNY?nnnnnN", ""]
    counts = [0, 0.5, 1, 10, 10.5, 11, 100, 101, 1000, 1000.5, 25000]

    def form(when, answers, by="", note=""):
        return SAN.inspection_event(when, answers, by=by, note=note).as_dict()

    inspections = {
        "none": [],
        "complete": [form("2024-05-20", "NNYNNNNNNN", by="A. Bangura")],
        "intermediate": [form("2024-05-20", "YNNYNNYNYN", by=" M. Kolleh ")],
        "very_high": [form("2024-05-20", "YYYYYYYYYN")],
        "incomplete": [form("2024-05-20", "YNN--NYN-N")],
        "nearly_blank": [form("2024-05-20", "Y---------")],
        # the latest that scores, a later visit with no form after it, and a
        # form dated after today
        "later_unscored": [form("2023-11-02", "YYYYYYNNNN"), form("2024-02-01", "YNNNNNNNNN"),
                           {"when": "2024-04-11", "kind": "inspection", "note": "looked"},
                           form("2099-01-01", "YYYYYYYYYY")],
        "same_day": [form("2024-05-20", "NNNNNNNNNN", by="A"), form("2024-05-20", "YYYNNNNNNN", by="B"),
                     form("2024-05-20", "YYYNNNNNNN", by="C")],
        "blank": [form("2024-05-20", "----------")],
        "unreadable": [{"when": "2024-05-20", "kind": "inspection", "form": "tubewell_handpump",
                        "answers": "YN"},
                       {"when": "2024-05-21", "kind": "inspection", "form": "hand_dug_well",
                        "answers": "YNNYNNYNYN"}],
        "note_only": [{"when": "2024-05-20", "kind": "inspection", "note": "apron cracked"},
                      {"when": "bad date", "kind": "inspection", "form": "tubewell_handpump",
                       "answers": "YYYYYYYYYY"}],
        # dates Python 3.11 read and the browser did not: neither reads them
        "compact": [form("20240520", "YYYYYYYYYN")],
        "week": [form("2024-05-20", "NNNNNNNNNN"), form("2024-W21-1", "YYYYYYYYYN"),
                 form("2024-05-20T09:00", "YYYYYYYYYN")],
        # ends the two engines' own trims used to read apart
        "bom": [{"when": "\ufeff2024-05-20", "kind": "\ufeffinspection",
                 "form": "tubewell_handpump\ufeff", "answers": "\ufeffYNNYNNYNYN",
                 "by": "\ufeffA. Bangura\x1c"}],
        "separator": [{"when": "2024-05-20\x1c", "kind": "inspection\x85",
                       "form": "\x1ftubewell_handpump", "answers": "YNNYNNYNYN\x1c",
                       "note": "apron cracked\x1e"}],
        # a water sample the history records: named when no analysis is
        # loaded, and when it is later than the one read
        "sampled": [{"when": "2024-03-01", "kind": "water_sample",
                     "note": "E. coli 12 per 100 mL field kit"},
                    form("2024-05-20", "YNNYNNYNYN")],
        "sampled_later": [{"when": "2024-05-25", "kind": "water_sample", "by": "M. Kolleh"},
                          {"when": "2024-05-26", "kind": "water_sample"},
                          {"when": "2024-07-01", "kind": "water_sample"},
                          form("2024-05-20", "NNNNNNNNNN")],
    }
    panel = [{"parameter": "Arsenic", "value": 0.001, "unit": "mg/L"},
             {"parameter": "Fluoride", "value": 0.3, "unit": "mg/L"},
             {"parameter": "Nitrate (as NO3)", "value": 5.0, "unit": "mg/L"}]

    def sample(*ecoli, when="2024-05-21"):
        return {"site": {"community": "Ref"}, "flags": [], "sample_date": when,
                "results": [dict(r) for r in ecoli] + [dict(r) for r in panel]}

    def ecoli(value=None, unit="CFU/100 mL", parameter="E. coli", **kw):
        return {"parameter": parameter, "value": value, "unit": unit, **kw}

    samples = {
        "none": None,
        "clean": sample(ecoli(0.0)),
        "counted": sample(ecoli(40.0)),
        "heavy": sample(ecoli(2400.0)),
        "below": sample(ecoli(None, below_detection=True, detection_limit=1.0)),
        "absent": sample(ecoli(None, below_detection=True)),
        "over": sample(ecoli(None, greater_than=50.0)),
        "at_least": sample(ecoli(None, greater_than=1000.0, greater_than_inclusive=True)),
        "present": sample(ecoli(None, greater_than=0.0)),
        "coarse": sample(ecoli(None, below_detection=True, detection_limit=10.0)),
        "missing": sample(),
        "per_ml": sample(ecoli(2.0, unit="CFU/mL", parameter="Thermotolerant coliforms")),
        "two_rows": sample(ecoli(0.0), ecoli(150.0, parameter="Faecal coliforms")),
        "undated": sample(ecoli(3.0), when=""),
        "bad_unit": sample(ecoli(3.0, unit="wibbles")),
        # results the assessment could not grade, whose remarks end in a
        # full stop of their own or do not
        "slash_unit": sample(ecoli(3.0, unit="/100 mL")),
        "unreadable": sample(ecoli(None, unreadable="lots")),
        "coarse_per_ml": sample(ecoli(None, below_detection=True, detection_limit=1.0,
                                      unit="CFU/mL")),
        "chemistry": sample(ecoli(0.0), {"parameter": "Arsenic", "value": 0.05, "unit": "mg/L"}),
    }
    pairs = ([(name, "clean") for name in inspections] + [(name, "none") for name in inspections]
             + [("complete", name) for name in samples] + [("incomplete", name) for name in samples]
             + [("none", name) for name in samples])
    cases = []
    for inspection, which in pairs:
        raw = samples[which]
        assessment = None
        if raw is not None:
            assessment = assess_sample(WaterQualitySample(
                site=SiteMetadata(community="Ref"), sample_date=raw["sample_date"],
                results=[WaterQualityResult(**r) for r in raw["results"]]))
        events = inspections[inspection]
        asset = Asset(asset_id=asset_id, events=merge_events(asset_id, events))
        cases.append({
            "name": f"{inspection}/{which}", "events": events, "sample": raw,
            "today": "2024-06-01",
            "expect": {"risk": SAN.sanitary_risk(asset, "2024-06-01", assessment),
                       "merged": [e.as_dict() for e in merge_events(asset_id, events)]},
        })
    # today written as neither engine reads a day, or with blanks at its ends
    todays = []
    clean_sample = samples["clean"]
    clean_assessment = assess_sample(WaterQualitySample(
        site=SiteMetadata(community="Ref"), sample_date=clean_sample["sample_date"],
        results=[WaterQualityResult(**r) for r in clean_sample["results"]]))
    for today in ("20240601", "2024-W22-6", "2024-06-01T00:00", " 2024-06-01\n",
                  "\ufeff2024-06-01", "2024-06-01\x1c", "0024-06-01", "0000-06-01"):
        events = inspections["complete"]
        asset = Asset(asset_id=asset_id, events=merge_events(asset_id, events))
        try:
            expect = {"risk": SAN.sanitary_risk(asset, today, clean_assessment)}
        except ValueError:
            expect = {"throws": True}
        todays.append({"name": repr(today), "events": events, "sample": clean_sample,
                       "today": today, "expect": expect})
    # days as both engines read them (iso_date and isoDay), and the ends of
    # a field and of a form's answers as both trim them
    texts = ["2024-05-20", "20240520", "2024-W21-1", "2024W211", "2024-05-20T09:00",
             "2024-5-20", "+2024-05-20", "\u0968\u0966\u0968\u096a-\u0966\u096b-\u0968\u0966",
             "2023-02-29", "2024-02-29", "0000-01-01", "0001-01-01", "0050-03-01", "0099-12-31",
             "9999-12-31", " 2024-05-20 ", "\ufeff2024-05-20", "2024-05-20\x1c", "\x852024-05-20",
             "\u20002024-05-20\u3000", "\u200b2024-05-20", "", None]
    blank = ("\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2005\u200a\u2028"
             "\u2029\u202f\u205f\u3000\ufeff")
    trims = ["\ufeffYNNYNNYNYN", "YNNYNNYNYN\x1c", blank + "YnN-x" + blank,
             blank + "YNNYNNYNYN" + blank, "\u200bYNNYNNYNYN\u200b", "\x00YN\x00", blank, "",
             None]

    def day(text):
        read = iso_date(text)
        return None if read is None else read.isoformat()

    return clean({
        "asset_id": asset_id,
        "cases": cases,
        "todays": todays,
        "days": [{"text": t, "expect": {"day": day(t)}} for t in texts],
        "trims": [{"text": t, "expect": {"trim": trim_field(t), "answers": clean_answers(t),
                                         "score": SAN.score_answers(t)}} for t in trims],
        # every code point of the Basic Multilingual Plane that trim_field
        # takes off an end: the browser's trimField must take the same
        "trimmed": [c for c in range(0x10000) if trim_field(chr(c) + "x") == "x"],
        "forms": [{"answers": a, "expect": {"score": SAN.score_answers(a), "rows": SAN.form_rows(a)}}
                  for a in forms],
        "grades": [{"count": c, "expect": {
            "grade": SAN.ecoli_grade(c), "above": list(SAN.ecoli_grades_above(c, False)),
            "above_inclusive": list(SAN.ecoli_grades_above(c, True))}} for c in counts],
        "questions": SAN.form_questions(),
        "tables": SAN.sanitary_tables(),
    })


def calibration_in_force_reference() -> dict:
    """A calibration set in force (PLAN.md step 5.3, part b): the odds at
    each kind of ground with its fitted prior, or the table's where it fitted
    none, and their sentences; each unit's edges and the soundings read by
    them; the suitability weights; what the set changes; under the default,
    the set, the set without weights at another definition of success, and
    a set nobody adopted, which is refused."""
    from groundwater import calibration_sets as CS
    from groundwater.models import LayeredModel
    from groundwater.siting import assess_siting
    from groundwater.siting.odds import (
        odds_basis_text, odds_headline, odds_prior_text, odds_text, prior_odds, success_odds,
    )
    from groundwater.ves.interpret import interpret_model

    unweighed = dict(IN_FORCE_SET, weights=None, success_yield_m3_per_h=3.6)
    candidate = dict(IN_FORCE_SET, version=None, adopted_by="", adopted_on="", replaces=None)
    variants = [{"name": "default", "set": None, "settings": {}},
                {"name": "set", "set": IN_FORCE_SET, "settings": {}},
                {"name": "set at 3.6", "set": IN_FORCE_SET, "settings": {"odds": {"success_yield_m3_per_h": 3.6}}},
                {"name": "unweighed", "set": unweighed, "settings": {"odds": {"success_yield_m3_per_h": 3.6}}},
                {"name": "candidate", "set": candidate, "settings": {}}]
    cases = []
    for v in variants:
        config = Config()
        for section, values in v["settings"].items():
            for key, value in values.items():
                setattr(getattr(config, section), key, value)
        try:
            config = CS.apply_set(config, v["set"]) if v["set"] else config
        except ValueError as exc:
            cases.append(dict(v, expect={"refused": str(exc)}))
            continue
        interps = [interpret_model(None, LayeredModel(resistivities=m[0], thicknesses=m[1]),
                                   CS.config_for_unit(config, IN_FORCE_UNITS[k % len(IN_FORCE_UNITS)]).ves)
                   for k, m in enumerate(IN_FORCE_MODELS)]
        odds = []
        for code, glg in IN_FORCE_GROUNDS:
            o = prior_odds(code, glg, config)
            odds.append({"odds": dataclasses.asdict(o), "headline": odds_headline(o), "prior": odds_prior_text(o),
                         "basis": odds_basis_text(o)})
        success = []
        for k, interp in enumerate(interps):
            code, glg = IN_FORCE_GROUNDS[k % len(IN_FORCE_GROUNDS)]
            o = success_odds(interp, None, code, glg, config)
            success.append({"odds": dataclasses.asdict(o), "text": odds_text(o)})
        cases.append(dict(v, expect={
            "weights": config.ves.suitability_weights, "calibration": config.calibration, "odds": odds,
            "success": success,
            "units": [[CS.config_for_unit(config, glg).ves.clay_max_rho,
                       CS.config_for_unit(config, glg).ves.fresh_basement_min_rho] for glg in IN_FORCE_UNITS],
            "sounding": [CS.config_for_sounding(config, _ns({"site": {"easting": p[0], "northing": p[1],
                                                                      "utm_zone": p[2]}})).ves.fresh_basement_min_rho
                         for p in IN_FORCE_POSITIONS],
            "interps": [[i.depth_to_basement_m, [layer.unit for layer in i.layers]] for i in interps],
            "siting": [[r.index, r.suitability, r.rank] for r in assess_siting(interps, config.ves)],
            "changes": CS.set_changes(CS.in_force(config))}))
    return {"grounds": IN_FORCE_GROUNDS, "units": IN_FORCE_UNITS, "positions": IN_FORCE_POSITIONS,
            "models": IN_FORCE_MODELS, "cases": cases}


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

"""The soundings: the interpretation's prose over hand-built cases, the range
of models, the forward model at high contrast and the inversion's limits -
the "ves_text", "ves_range", "ves_forward", "ves_bessel" and "ves_fit"
entries of ``reference.json``.

The tolerances ``--check`` holds the range's sampler runs to are in
``common.py`` with the comparison that reads them.
"""

from __future__ import annotations

import dataclasses
import math
from types import SimpleNamespace

import numpy as np

from groundwater.config import Config, VESConfig
from groundwater.ingestion.ves import _flag_duplicate_ids, _sounding_or_reason
from groundwater.models import LayeredModel, SiteMetadata, VESSounding
from groundwater.reporting.geophysical import (
    depth_of_investigation_text,
    models_tried_text,
    poorly_resolved_text,
)
from groundwater.siting import assess_siting, ranking_tie, suitability_verdict
from groundwater.ves.interpret import (
    drilling_depth_text,
    drilling_preference_table,
    interpret_model,
)
from groundwater.ves.inversion import invert_sounding
from groundwater.ves.model_range import (
    latin_hypercube,
    model_range_caption,
    model_range_rows,
    model_range_table_caption,
    model_range_text,
    sample_model_range,
    Stream,
)

from .common import clean, flags


# The interpretation and report prose over cases the Rokel pair never
# reaches: a zone whose modelled base lies below the depth of investigation,
# one wholly below it, a margin cut back to it, a last reading the inversion
# dropped, poorly resolved boundaries, a resistive cover over conductive
# ground, a 1 m zone on half metres, a sounding too short for the vadose
# allowance, a near-tie, an exact tie, two sheets carrying one sounding
# number, a resistance sheet with rows K cannot convert, a resistivity headed
# as a resistance, and a spacing read twice with no MN recorded. parity.mjs
# builds the same cases.
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
    # a layer as resistive as basement over a water zone, over clay and over
    # a conductive half-space: a resistive cover, never the depth to bedrock
    ("cover over a water zone", [300, 5000, 60, 8000], [0.8, 2, 20], 2.0, None, None, None),
    ("cover over clay", [300, 5000, 10, 8000], [0.8, 2, 20], 2.0, None, None, None),
    ("cover over a conductive half-space", [1100, 5000, 47], [1.0, 7.0], 5.0, None, None,
     None),
    ("two covers", [300, 5000, 60, 4000, 60, 8000], [0.8, 2, 5, 2, 10], 2.0, None, None,
     None),
    ("basement over compact rock", [300, 5000, 1500, 8000], [0.8, 2, 20], 2.0, None, None,
     None),
    # a 1 m zone whose two ends round half to even onto the same metre
    ("half-metre zone", [500, 100, 5000], [3.5, 1.0], 2.0, None, None, None),
    # a sounding too short to see below the vadose allowance
    ("short sounding", [400, 90, 3000], [0.6, 8.0], 2.0, None,
     [1.0, 1.5, 2.0, 3.0, 4.0, 5.0], None),
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
    # a resistance sheet with two rows where MN/2 is not below AB/2: those
    # rows are left out and flagged, and the sheet is still read
    ("R", _ves_sheet("R 1", "Schlumberger", ["No.", "AB/2 (m)", "MN (m)", "R (ohm)"],
                     [[0.3, 1.0, 12.5], [0.5, 1.0, 9.0], [2.0, 1.0, 4.1], [3.0, 1.0, 1.9],
                      [5.0, 1.0, 0.62], [10.0, 1.0, 0.18], [15.0, 1.0, 0.09]])),
    # a resistivity headed as a resistance, but in ohm-metres
    ("R ohm-m", _ves_sheet("R 2", "Schlumberger", ["No.", "AB/2 (m)", "MN (m)",
                                                  "Apparent Resistance (Ωm)"],
                           [[1.0, 0.5, 120.0], [2.0, 0.5, 95.0], [3.0, 0.5, 80.0],
                            [5.0, 0.5, 70.0], [10.0, 2.0, 90.0]])),
    # one spacing read twice with no MN column: fitted as two readings
    ("no MN", _ves_sheet("N 1", "Schlumberger", ["No.", "AB/2 (m)",
                                                "Apparent Resistivity (ohm-m)"],
                         [[1.0, 120.0], [2.0, 95.0], [3.0, 80.0], [5.0, 70.0], [10.0, 90.0],
                          [10.0, 120.0], [15.0, 110.0], [20.0, 140.0], [30.0, 190.0]])),
]


#: (ab2, mn, rho, array) of soundings whose fitted readings and reading
#: errors both engines compare: a zero at an MN overlap beside a good
#: reading, a spacing read twice with no MN recorded, and an MN overlap
READING_CASES = [
    ([1, 2, 3, 5, 8, 10, 10, 15, 20, 30, 40, 40, 60, 80, 100],
     [0.5] * 6 + [4.0] * 5 + [10.0] * 4,
     [300, 250, 180, 120, 90, 85, 88, 80, 90, 120, 170, 0, 260, 330, 400], "schlumberger"),
    ([1, 2, 3, 5, 10, 10, 15, 20, 30, 40, 40, 60], [None] * 12,
     [120, 95, 80, 70, 90, 120, 110, 140, 190, 230, 260, 300], "schlumberger"),
    ([1, 2, 3, 5, 10, 10, 15, 20, 30, 40, 40, 60], [1.0] * 5 + [4.0] * 5 + [10.0] * 2,
     [120, 95, 80, 70, 90, 120, 110, 140, 190, 230, 260, 300], "schlumberger"),
]


def reading_cases() -> list:
    from groundwater.ves.inversion import inversion_readings
    from groundwater.ves.model_range import reading_errors

    out = []
    for ab2, mn, rho, array in READING_CASES:
        sounding = VESSounding(SiteMetadata(), "R", np.array(ab2, dtype=float),
                               np.array([np.nan if v is None else v for v in mn], dtype=float),
                               np.array(rho, dtype=float), array_type=array)
        fitted, fitted_rho, _ = inversion_readings(sounding)
        sigma, spacings = reading_errors(sounding, fitted, 3.0)
        out.append({"ab2": ab2, "mn": mn, "rho": rho, "array": array,
                    "fitted_ab2": clean(fitted), "fitted_rho": clean(fitted_rho),
                    "sigma": clean(sigma), "spacings": clean(spacings)})
    return out


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
        "sheet_readings": [[clean(s.ab2), clean(s.rho_app)] for _, s in grids],
        "readings": reading_cases(),
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
    """Three soundings the Rokel pair does not cover, as readings both
    engines read: basement within reach under a weathered zone (the
    sentences with a band), a Wenner sheet that reads one spacing twice, and
    a duricrust over a conductive weathered zone."""
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
    # a duricrust 1 m down over a conductive weathered zone: every model that
    # fits reads it as a cover, and none finds basement, where each used to
    # find it at the duricrust's top
    rho = forward_schlumberger((np.array([300.0, 5000.0, 60.0]), np.array([1.0, 3.0])), ab2)
    out.append(VESSounding(site=SiteMetadata(), sounding_id="duricrust over water",
                           ab2=ab2, mn=np.full(len(ab2), np.nan), rho_app=rho * noise))
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
# over 3.2 to 40 ohm-m, and models of three and four layers whose thinnest
# layer is not the top one, since the quadrature's cut follows the top
# layer's thickness and the contrast to the least resistivity. Two more put
# 300 and 900 m of 0.5 ohm-m on 200,000 ohm-m: there the potential (J0)
# integral's transform turns at x = 3e-9 to 8e-9 for a 1 m radius, which
# one panel on (0, 1e-6) left 1.1e-3 out in Wenner and finite MN.
# The starting models are held to 1e-12 on soundings whose first spacing
# was read twice, where np.interp at the first abscissa reads the second
# reading and the browser's interp used to read the first. interp itself is
# held to np.interp exactly, at its edges and inside the range.

FORWARD_AB2 = [1.0, 1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 25.0, 40.0, 70.0, 100.0]
FORWARD_MN = [0.4] * 4 + [1.0] * 4 + [4.0] * 4
FORWARD_RHO1 = [4.0, 1e2, 1e3, 1e4, 1e5, 2e5]
FORWARD_H1 = [0.2, 0.25, 0.5, 2.0]
FORWARD_RHO2 = [3.2, 5.0, 40.0]
#: (rho, h) of the layered models beside the grid
FORWARD_LAYERED = [
    ([300.0, 50.0, 5000.0, 2000.0], [5.0, 3.0, 0.5]),
    ([10.0, 150000.0, 10.0], [3.0, 0.5]),
    ([150000.0, 100.0, 10.0], [0.5, 15.0]),
    ([0.5, 200000.0], [0.2]),
    # thick conductive cover on the most resistive basement, where the
    # potential integral's transform falls below x = 1e-6
    ([0.5, 200000.0], [300.0]),
    ([0.5, 0.5, 0.5, 200000.0], [300.0, 300.0, 300.0]),
]

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
    for rho, h in FORWARD_LAYERED:
        model = (np.array(rho), np.array(h))
        models.append({
            "rho": rho, "h": h,
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


# ------------------------------------- the inversion's limits, held alike
#
# An audit of the VES inversion found four things parity never reached. A
# sounding of four or five readings was fitted with a parameter per reading
# and reported as fully resolved; the browser counted one iteration past the
# cap, which its own cache then refused on every reload; a reading at AB/2 =
# 0 went into the starting models' logarithms, which numpy's interp survived
# and the browser's did not; and "converged" meant only that the damped step
# search had given up. Each is held here: three short soundings' layer
# counts, trials, models and uncertainty factors, and the refusal of a model
# they cannot determine; fits run to caps of 0, 1 and 3 iterations, and why
# each stopped; a sheet with a row at AB/2 = 0, its flags and its inversion,
# and one with two such rows, whose flag the catalogue puts in the plural;
# interp over the logarithms of spacings with a 0 among them; and how the
# Rokel pair's inversions stopped and whether they converged. How many
# iterations a full inversion takes is not compared: the two engines' last
# bits send the damped steps different ways, and they agree on the model.

FIT_AB2 = [1.5, 3.0, 6.0, 10.0, 20.0, 40.0, 80.0]
FIT_NOISE = [1.02, 0.97, 1.03, 0.98, 1.01, 0.99, 1.02]
FIT_EARTH = ([800.0, 40.0, 2000.0], [3.0, 15.0])
#: the sheet with a placeholder row at AB/2 = 0 ahead of its readings
FIT_ZERO_SPACINGS = [1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 30.0, 50.0]
FIT_ZERO_EARTH = ([400.0, 60.0, 1500.0], [2.0, 10.0])


def _fit_dict(r) -> dict:
    return {
        "layers": r.model.n_layers, "trials": [n for n, _err in r.trials],
        "rho": clean(r.model.resistivities), "h": clean(r.model.thicknesses),
        "err": clean(r.fit_error_percent),
        "rho_factor": clean(r.rho_uncertainty_factor),
        "h_factor": clean(r.h_uncertainty_factor),
        "converged": r.converged, "stopped": r.stopped,
    }


def ves_fit_reference(rokel_inversions) -> dict:
    """The short soundings, the capped fits, the sheet with a zero spacing,
    interp over log 0, and how the Rokel inversions stopped."""
    from groundwater.ves.forward import forward_schlumberger
    from groundwater.ves.inversion import _starting_models, invert_model, most_layers

    earth = (np.array(FIT_EARTH[0]), np.array(FIT_EARTH[1]))
    short = []
    for n in (4, 5, 6):
        ab2 = np.array(FIT_AB2[:n])
        rho = forward_schlumberger(earth, ab2) * np.array(FIT_NOISE[:n])
        sounding = VESSounding(SiteMetadata(), "F", ab2, np.full(n, np.nan), rho)
        asked = most_layers(n) + 1
        try:
            invert_sounding(sounding, n_layers=asked)
            refused = None
        except ValueError as exc:
            refused = str(exc)
        short.append({"ab2": clean(ab2), "rho": clean(rho), "asked": asked,
                      "refused": refused, "fit": _fit_dict(invert_sounding(sounding))})

    ab2 = np.array(FIT_AB2)
    rho = forward_schlumberger(earth, ab2) * np.array(FIT_NOISE)
    rho0, h0 = _starting_models(ab2, rho, 2)[0]
    capped = []
    for cap in (0, 1, 3):
        model, _calc, err, iterations, converged, stopped = invert_model(
            ab2, rho, rho0, h0, "schlumberger", VESConfig().damping, cap)
        capped.append({"cap": cap, "iterations": iterations, "converged": converged,
                       "stopped": stopped, "err": clean(err),
                       "rho": clean(model.resistivities), "h": clean(model.thicknesses)})

    spacings = np.array(FIT_ZERO_SPACINGS)
    noise = np.resize(np.array(FIT_NOISE), spacings.size)
    readings = forward_schlumberger(
        (np.array(FIT_ZERO_EARTH[0]), np.array(FIT_ZERO_EARTH[1])), spacings) * noise
    rows = _ves_sheet("Z 1", "Schlumberger",
                      ["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"],
                      [[0.0, 0.4, 1150.0]]
                      + [[float(a), 0.4, float(r)] for a, r in zip(spacings, readings, strict=True)])
    zero, _reason = _sounding_or_reason(rows, source="x.xlsx", sheet_name="Z")
    # and with two rows not above 0, where the catalogued flag takes its plural
    rows_two = _ves_sheet("Z 2", "Schlumberger",
                          ["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"],
                          [[-1.0, 0.4, 1150.0], [0.0, 0.4, 1150.0]]
                          + [[float(a), 0.4, float(r)] for a, r in zip(spacings, readings, strict=True)])
    two, _reason = _sounding_or_reason(rows_two, source="x.xlsx", sheet_name="Z")

    xp_raw, fp = [0.0, 1.0, 2.0, 3.0], [1150.0, 1165.0, 1193.0, 1303.0]
    x = [-1.0, 0.5, 1.0, 1.5, 2.5, 5.0]
    with np.errstate(divide="ignore", invalid="ignore"):  # log 0 and log -1
        logs, probes = np.log(np.array(xp_raw)), np.log(np.array(x))
    return {
        "short": short,
        "capped_ab2": FIT_AB2, "capped_rho": clean(rho), "capped": capped,
        "zero_rows": clean(rows), "zero_flags": flags(zero.flags),
        "zero_ab2": clean(zero.ab2), "zero_fit": _fit_dict(invert_sounding(zero)),
        "zeros_rows": clean(rows_two), "zeros_flags": flags(two.flags),
        "interp": {"xp_raw": xp_raw, "fp": fp, "x": x,
                   "value": clean(np.interp(probes, logs, np.log(fp)))},
        "rokel_stops": [[inv.model.sounding_id, inv.converged, inv.stopped]
                        for inv in rokel_inversions],
    }

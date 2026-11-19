"""Lineament candidates (PLAN.md step 4.2): the "lineaments" entry of
``reference.json``. ``LINEAMENT_GENERATED`` and ``lineament_heights`` give
the window the survey plan and the desk study are laid on, and
``tests/test_desk_study.py`` reads ``LINEAMENT_GENERATED`` through
``make_reference.py``.
"""

from __future__ import annotations

import dataclasses
import json
import math

from groundwater.ves.model_range import Stream

from .elevation import _ARCSEC
from .geotiff import _gt_digest, _gt_number
from .terrain import (
    _ta_analysis,
    _ta_axes,
    _ta_coast,
    _ta_credit,
    _ta_degenerate,
    _ta_plateau,
    _ta_short,
    _ta_spots,
    _TA_SURFACE,
    _ta_ties,
    _ta_unfold,
    _ta_worded,
)


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

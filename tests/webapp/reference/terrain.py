"""The terrain analysis (PLAN.md step 4.1): the "terrain" entry of
``reference.json``. The lineament and survey plan sections analyse their
windows with ``_ta_analysis`` and the helpers beside it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import struct
from types import SimpleNamespace

import numpy as np

from groundwater.ves.model_range import Stream

from .common import clean
from .elevation import _ARCSEC
from .geotiff import _gt_compact, _gt_digest, _gt_number


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

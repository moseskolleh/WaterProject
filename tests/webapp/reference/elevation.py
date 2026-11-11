"""The elevation layer (PLAN.md step 4.1): the "elevation_window" entry of
``reference.json``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math

import numpy as np

from groundwater.geotiff import GeoTiffError
from groundwater.models import SiteMetadata

from .geotiff import DEM_FIXTURES, GEOTIFF_SPOTS, _gt_compact, _gt_digest, _gt_number


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

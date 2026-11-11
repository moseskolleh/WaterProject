"""DEFLATE blocks and the GeoTIFF reader (PLAN.md step 4.1): the "inflate" and
"geotiff" entries of ``reference.json``, over the committed fixtures in
``tests/webapp/fixtures``. ``_gt_number``, ``_gt_compact`` and ``_gt_digest``
are how the elevation, terrain, lineament and survey plan sections write
their answers too.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import math
import re

import numpy as np

from groundwater.geotiff import (
    block_ranges,
    _CodecError,
    decode_block,
    geotiff_layout,
    GeoTiffError,
    _inflate_block,
    read_geotiff,
)

from .common import OUT


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

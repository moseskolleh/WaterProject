"""Elevation models as they arrive, generated for the fuzz suite (PLAN.md
step 4.1).

Each strategy draws a *case* as ``sheets.py`` does - a kind, the input and
the options - but the input is a raster, or one compressed block of one,
rather than a workbook: ``case["raster"]`` holds it, and ``FILES`` turns a
case of each kind here into the file both engines are handed. A case is
plain JSON, so a counterexample is committed under ``tests/fuzz/regressions``
like any other, and it carries the bytes themselves where a zlib build could
write others, so it replays byte for byte on any machine.

``deflate`` draws one zlib stream of the kind a GeoTIFF's DEFLATE blocks
hold: mixed content, every level, strategy and memory level, windows from
512 bytes to 32 KB, flushes splitting it into pieces, and now and then a
flipped bit, a changed byte, a cut, a bad checksum or junk after it, read
against bounds around its true length. Both engines must give the same
verdict and, when they read it, the same bytes.

``geotiff`` draws a whole GeoTIFF as a description that
tests/webapp/fixtures/make_dem_fixture.py makes into a file
(``described_file``): a grid of 3 to 40 cells a side in any sample type,
either byte order, classic or now and then BigTIFF, strips or tiles of 16 to
48 cells, every compression the readers take with the predictors it can
carry (and now and then a predictor tag where libtiff ignores it), a no-data
text in any of its forms, Area or Point, degrees or UTM, -0, the infinities
and NaN among the samples, and now and then a file damaged or cut short.
Both readers must give the same layout, the same refusal word for word, or
the same values, reasons and axes. A case stores the description, not the
file: its DEFLATE blocks are zlib's, so on another zlib build a damaged one
is damaged in other bytes, though both readers must still agree on it.

``terrain`` draws a window of heights for the terrain analysis: 3 to 48
cells a side in whole centimetres over small ranges, so that ties are
everywhere, with plateaus, pits, voids, -0, now and then the infinities,
sea along one edge (at times a straight strip of 0 m, a zero-filled gap),
holes no file covers, a missing tile taken as sea, small drainage
thresholds, other settings and a square shown inside the window, and
lineament settings fine enough to find candidates a few cells long in it
(PLAN.md step 4.2). The window is handed to both engines as its numbers
(``_terrain_file``), and both must give every layer, drainage line, part,
lineament candidate, caption, summary value and both GeoJSON files
exactly, and the wetness index to 1e-12. A case stores the
heights as a table of centimetres, south row first, readable in a
regression file a row to a line.
"""

from __future__ import annotations

import base64
import importlib.util
import math
import random
import struct
import sys
import zlib
from functools import cache
from pathlib import Path

from hypothesis import strategies as st

_STRATEGIES = {"default": zlib.Z_DEFAULT_STRATEGY, "filtered": zlib.Z_FILTERED,
               "huffman_only": zlib.Z_HUFFMAN_ONLY, "rle": zlib.Z_RLE, "fixed": zlib.Z_FIXED}
_CONTENT = ["random", "zeros", "runs", "heights", "floats", "repeats"]


def _content(rng: random.Random, kind: str, n: int) -> bytes:
    """``n`` bytes of one kind of content a block of heights holds."""
    out = bytearray()
    if kind == "random":
        return rng.randbytes(n)
    if kind == "zeros":
        return bytes(n)
    if kind == "runs":
        while len(out) < n:
            out += bytes([rng.randrange(256)]) * rng.randrange(1, 300)
    elif kind == "heights":
        z = 120  # int16 metres in a random walk
        while len(out) < n:
            z = max(-30, min(900, z + rng.randrange(-3, 4)))
            out += struct.pack("<h", z)
    elif kind == "floats":
        z = 52.0  # float32 to a tenth of a metre, as predictor 3 leaves its bytes
        while len(out) < n:
            z = round(z + rng.randrange(-4, 5) / 10, 1)
            out += struct.pack(">f", z)
    else:  # "repeats": one passage again and again, slightly changed
        base = bytearray(rng.randbytes(rng.randrange(50, 3000)))
        while len(out) < n:
            base[rng.randrange(len(base))] = rng.randrange(256)
            out += base
    return bytes(out[:n])


@st.composite
def deflate_case(draw) -> dict:
    """One zlib stream and the bounds a reader asks it for."""
    rng = random.Random(draw(st.integers(0, 2**32 - 1)))
    pieces = draw(st.lists(st.tuples(st.sampled_from(_CONTENT), st.integers(0, 6000)),
                           min_size=1, max_size=4))
    data = b"".join(_content(rng, kind, n) for kind, n in pieces)
    level = draw(st.integers(0, 9))
    strategy = draw(st.sampled_from(sorted(_STRATEGIES)))
    mem = draw(st.integers(1, 9))
    wbits = draw(st.integers(9, 15))
    cuts = sorted(draw(st.lists(st.integers(0, len(data)), max_size=3)))
    flushes = [draw(st.sampled_from(["full", "sync"])) for _ in cuts]
    c = zlib.compressobj(level, zlib.DEFLATED, wbits, mem, _STRATEGIES[strategy])
    stream, start = b"", 0
    for cut, flush in zip(cuts, flushes, strict=True):
        stream += c.compress(data[start:cut]) + c.flush(
            zlib.Z_FULL_FLUSH if flush == "full" else zlib.Z_SYNC_FLUSH)
        start = cut
    stream += c.compress(data[start:]) + c.flush()
    made = (f"{len(data)} bytes of {', '.join(kind for kind, _ in pieces)}; level {level}, "
            f"strategy {strategy}, memLevel {mem}, window 2^{wbits}"
            + "".join(f", {flush} flush at {cut}" for cut, flush in zip(cuts, flushes, strict=True)))

    damage = draw(st.sampled_from(["none"] * 5 + ["flip", "byte", "cut", "adler", "junk"]))
    broken = bytearray(stream)
    if damage == "flip":
        at, bit = draw(st.integers(0, len(broken) - 1)), draw(st.integers(0, 7))
        broken[at] ^= 1 << bit
        made += f"; bit {bit} of byte {at} flipped"
    elif damage == "byte":
        at, value = draw(st.integers(0, len(broken) - 1)), draw(st.integers(0, 255))
        broken[at] = value
        made += f"; byte {at} set to {value}"
    elif damage == "cut":
        at = draw(st.integers(0, len(broken) - 1))
        del broken[at:]
        made += f"; cut to {at} bytes"
    elif damage == "adler":
        broken[-1] ^= 0x5A
        made += "; a bad Adler-32"
    elif damage == "junk":
        broken += bytes(draw(st.lists(st.integers(0, 255), min_size=1, max_size=16)))
        made += "; junk after the checksum"

    n = len(data)
    expected = max(0, n + draw(st.sampled_from([0, 0, 0, -1, -3, 1])))
    full = expected + draw(st.sampled_from([0, 0, 1, 7, 100]))
    return {"kind": "deflate",
            "raster": {"made": made, "b64": base64.b64encode(bytes(broken)).decode("ascii")},
            "options": {"expected": expected, "full": full}}


def _deflate_file(case: dict) -> tuple[bytes, str]:
    return base64.b64decode(case["raster"]["b64"]), ".zlib"


@cache
def _builder():
    """tests/webapp/fixtures/make_dem_fixture.py, which is a script, not a package."""
    name = "make_dem_fixture"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).resolve().parents[1] / "webapp" / "fixtures" / "make_dem_fixture.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # a dataclass looks its module up while the class is made
        spec.loader.exec_module(module)
    return sys.modules[name]


#: Where a drawn grid lies: degrees with its tiepoint at a corner or inside
#: the grid, and UTM metres, which the raw reader takes as readily
_PLACES = [{"x": -12.0, "y": 9.0, "sx": 1 / 3600, "sy": 1 / 3600, "model": 2, "epsg": 4326},
           {"x": -11.7, "y": 7.9, "sx": 1 / 1200, "sy": 1 / 1200, "model": 2, "epsg": 4326,
            "tie_col": 3, "tie_row": 2},
           {"x": 700000.0, "y": 950000.0, "sx": 30.0, "sy": 30.0, "model": 1, "epsg": 32629}]

#: GDAL_NODATA as writers give it, none most often
_NODATA = [None] * 6 + ["-9999", "nan", "-NaN", "-inf", "inf", "-0", "0", "-32768", "-32767", "65535",
                        "4294967295", "-3.40282346639e+038", "1e39", "", " 255 ", "1.5", "abc"]

_SAMPLE_KINDS = ["u8", "i8", "u16", "i16", "u32", "i32", "f32", "f64"]


@st.composite
def geotiff_case(draw) -> dict:
    """One GeoTIFF, as a description make_dem_fixture.described_file makes."""
    kind = draw(st.sampled_from(_SAMPLE_KINDS))
    width, height = draw(st.integers(3, 40)), draw(st.integers(3, 40))
    compression = draw(st.sampled_from([1, 5, 8, 32946, 32773]))
    spec = {"kind": kind, "width": width, "height": height, "seed": draw(st.integers(0, 9999)),
            "order": draw(st.sampled_from(["<", ">"])), "compression": compression}
    if compression in (5, 8, 32946):
        spec["predictor"] = draw(st.sampled_from([1, 2, 3] if kind[0] == "f" else [1, 2]))
    if draw(st.booleans()):
        spec["tile"] = [16 * draw(st.integers(1, 3)), 16 * draw(st.integers(1, 3))]
    else:
        spec["rows_per_strip"] = draw(st.integers(1, height))
    spec["georef"] = {**draw(st.sampled_from(_PLACES)), "raster": draw(st.sampled_from([1, 2, None]))}
    spec["specials"] = [[r, c, name] for r, c, name in draw(st.lists(
        st.tuples(st.integers(0, height - 1), st.integers(0, width - 1),
                  st.sampled_from(list(_builder().NAMED_SAMPLES))), max_size=4))]
    # What happens at a stated rate comes from a generator seeded by every
    # draw above: Hypothesis picks from a list nowhere near uniformly, and
    # draws the same small numbers again and again.
    coin = random.Random(f"{draw(st.integers(0, 2**32 - 1))} {sorted(spec.items())}")
    if compression not in (5, 8, 32946):  # one time in twenty a predictor tag libtiff and GDAL ignore
        spec["predictor"] = coin.choice([2, 3, 7]) if coin.random() < 0.05 else 1
    spec["bigtiff"] = coin.random() < 0.1
    spec["nodata"] = coin.choice(_NODATA)
    damage = coin.choice(["none"] * 9 + ["cut", "byte", "flip"])  # a quarter of the files damaged
    if damage == "cut":
        spec["damage"] = [["cut", coin.randrange(1000)]]
    elif damage == "byte":
        spec["damage"] = [["byte", coin.randrange(1000), coin.randrange(256)]]
    elif damage == "flip":
        spec["damage"] = [["flip", coin.randrange(1000), coin.randrange(8)]]
    return {"kind": "geotiff", "raster": spec, "options": {"bounds": list(_bounds())}}


@cache
def _bounds() -> tuple[float, float]:
    """The elevation layer's plausibility bounds (terrain.implausible_below_m
    and _above_m), which both readers judge each sample by."""
    from groundwater.config import TerrainConfig

    terrain = TerrainConfig()
    return terrain.implausible_below_m, terrain.implausible_above_m


def _geotiff_file(case: dict) -> tuple[bytes, str]:
    return _builder().described_file(case["raster"]), ".tif"


#: Where a drawn window lies: the 1-arc-second lattice at 8.5 N (GLO-30's
#: over Sierra Leone), the 3-arc-second one at 7.9 N, and cells kilometres
#: wide far north, where a row is metres wider than the next and the
#: curvature spacing rounds to one cell.
_TERRAIN_LATTICES = [(-12.0, 8.5, 1 / 3600)] * 4 + [(-12.0, 7.9, 1 / 1200), (-12.0, 55.0, 0.05)]

#: Names and places as an operator gives them: some need escaping in the
#: GeoJSON (quotes, a backslash, letters outside ASCII and outside the
#: Basic Multilingual Plane).
_TERRAIN_NAMES = ["n08w012.tif", "Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", 'Mɔyamba "coast" – N08°.tif',
                  "tile\\one 🌊.tif"]
_TERRAIN_PLACES = ["Kakua", "Sɛwa \\ Mɔyamba", 'the "middle" of the model', "Bo"]

#: A height that is not a number of centimetres, as the grid writes it.
_SPECIAL = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf, "-0": -0.0}


def _surface(coin: random.Random, rows: int, cols: int) -> list[list]:
    """Whole centimetres over a small range, so that ties are everywhere a
    real model has them: a tilt, a valley, a bowl, terraces or noise, with
    plateaus, pits and a little roughness, south row first."""
    form = coin.choice(["tilt", "valley", "bowl", "terraces", "noise"])
    a, b = coin.randint(-60, 60), coin.randint(-60, 60)
    rough, base = coin.choice([0, 0, 3, 20, 100]), coin.choice([0, 150, 800, 3000])
    mid_r, mid_c = coin.randrange(rows), coin.randrange(cols)
    step = coin.choice([10, 50, 100])
    cm = []
    for r in range(rows):
        row = []
        for c in range(cols):
            if form == "tilt":
                v = a * c + b * r
            elif form == "valley":
                v = abs(a) * abs(c - mid_c) + b * r
            elif form == "bowl":
                v = abs(a) * (abs(r - mid_r) + abs(c - mid_c))
            elif form == "terraces":
                v = step * ((a * c + b * r) // step)
            else:
                v = coin.randint(0, 400)
            row.append(base + v + (coin.randint(0, rough) if rough else 0))
        cm.append(row)
    for _ in range(coin.choice([0, 0, 1, 2])):  # plateaus: rectangles of one height
        r0, c0 = coin.randrange(rows), coin.randrange(cols)
        r1, c1 = min(rows, r0 + coin.randint(1, 8)), min(cols, c0 + coin.randint(1, 8))
        level = cm[r0][c0]
        for r in range(r0, r1):
            for c in range(c0, c1):
                cm[r][c] = level
    for _ in range(coin.choice([0, 0, 1, 3])):  # pits, now and then below sea level
        cm[coin.randrange(rows)][coin.randrange(cols)] = coin.choice([-50, 0, base - 200, base])
    return cm


@st.composite
def terrain_case(draw) -> dict:
    """One window of heights as the analysis is handed it, and how it is
    analysed: whole centimetres over small ranges (ties), plateaus and pits,
    voids, -0, now and then the infinities, sea along one edge (straight
    and zero-filled at times), holes no file covers, a missing tile taken
    as sea, small drainage thresholds, other settings, and a square shown
    inside the window."""
    rows, cols = draw(st.integers(3, 48)), draw(st.integers(3, 48))
    # What happens at a stated rate comes from a generator seeded by a draw,
    # as in geotiff_case: Hypothesis picks from a list nowhere near uniformly.
    coin = random.Random(f"{draw(st.integers(0, 2**32 - 1))} {rows} {cols}")
    cm: list[list] = _surface(coin, rows, cols)
    if coin.random() < 0.4:  # sea along one edge, low ground or a straight strip of 0 m
        width, edge, level = coin.randint(1, 4), coin.choice("SNWE"), coin.choice([0, 0, -30, -200])
        for r in range(rows):
            for c in range(cols):
                depth = {"S": r, "N": rows - 1 - r, "W": c, "E": cols - 1 - c}[edge]
                if depth < width and (level == 0 or coin.random() < 0.8):
                    cm[r][c] = level
    for _ in range(coin.choice([0, 0, 1, 4, 12])):  # voids, a cell at a time
        cm[coin.randrange(rows)][coin.randrange(cols)] = "nan"
    if coin.random() < 0.2:  # a hole no file covers, at the edge
        r0, c0 = coin.choice([0, rows - 2]), coin.randrange(cols)
        for r in range(max(0, r0), min(rows, r0 + 2)):
            for c in range(c0, min(cols, c0 + coin.randint(1, 6))):
                cm[r][c] = "nan"
    for _ in range(coin.choice([0, 1, 3])):  # -0, which must give the bits of +0
        cm[coin.randrange(rows)][coin.randrange(cols)] = "-0"
    if coin.random() < 0.08:
        for _ in range(coin.randint(1, 3)):
            cm[coin.randrange(rows)][coin.randrange(cols)] = coin.choice(["inf", "-inf"])
    assumed = []
    if coin.random() < 0.15:  # a missing tile taken as open sea, at a corner, with no height
        h, w = coin.randint(1, max(1, rows // 2)), coin.randint(1, max(1, cols // 2))
        r0, c0 = coin.choice([0, rows - h]), coin.choice([0, cols - w])
        assumed.append([r0, r0 + h, c0, c0 + w])
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                cm[r][c] = "nan"
    lon0, lat0, step = coin.choice(_TERRAIN_LATTICES)
    settings: dict = {
        "drainage_area_km2": coin.choice([0.0, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.05]),
        "sea_level_m": coin.choice([0.0] * 4 + [-1.0, 0.5]),
        "fill_note_m": coin.choice([1.0, 1.0, 0.25, 0.05, 0.0]),
        "flat_tan_slope": coin.choice([0.001, 0.001, 0.01, 0.05]),
        "curvature_spacing_m": coin.choice([90.0, 90.0, 30.0, 60.0, 250.0]),
    }
    if coin.random() < 0.3:
        settings["sea_straight_edge_cells"] = coin.choice([2, 3, 5, 8, 12])
    if coin.random() < 0.2:
        settings["hillshade_altitude_deg"] = coin.choice([30.0, 60.0])
        settings["hillshade_panel_azimuths_deg"] = coin.sample([270.0, 315.0, 0.0, 45.0, 135.0], coin.randint(1, 4))
    shown = None
    if coin.random() < 0.7:
        r0, c0 = coin.randrange(rows), coin.randrange(cols)
        shown = [r0, coin.randint(r0 + 1, rows), c0, coin.randint(c0 + 1, cols)]
    label, where = coin.choice(_TERRAIN_NAMES), coin.choice(_TERRAIN_PLACES)
    read = None
    if coin.random() < 0.5:
        read = {"surface": coin.choice(["", "Heights of the ground."]),
                "plan": None if coin.random() < 0.3 else {"radiusKm": coin.choice([0.4, 3.0]),
                                                          "marginKm": coin.choice([0.0, 0.25])}}
    meta = {"label": label,
            "figure_credit": coin.choice(["Elevation: n08w012.tif, source not stated. Cells about 31 by 31 m.",
                                          "Elevation: Copernicus GLO-30, © DLR e.V. 2014-2018."]),
            "notice": coin.choice([None, "", 'No liability "at all".']), "surface": "Heights of the ground.",
            "area": settings["drainage_area_km2"], "radius": coin.choice([10.0, 0.4]),
            "margin": coin.choice([5.0, 0.0, 0.25]),
            "centre": {"lon": lon0 + (cols // 2) * step, "lat": lat0 + (rows // 2) * step, "label": where}}
    sea_clean = coin.random() < 0.5
    source_id = coin.choice(["copernicus_glo30", "srtm", "hgt", "unidentified"])
    # what the GeoJSON's description reads besides the window: the fill
    # note and sea level it was analysed with, the sea rule, and a count of
    # sea cells that says whether the window holds any
    meta.update(fill_note_m=settings["fill_note_m"], sea_clean=sea_clean, sea_cells=coin.choice([0, 1, 250]),
                sea_level_m=settings["sea_level_m"])
    if coin.random() < 0.8:  # lineaments a few cells long; drawn last, so the draws above are as they were
        settings.update(
            lineament_smoothing_m=coin.choice([10.0, 10.0, 10.0, 25.0, 65.0]),
            lineament_contrast_km=coin.choice([0.1, 0.3, 0.6, 1.5]),
            lineament_share=coin.choice([1.0, 1.0, 0.4, 0.05]),
            lineament_min_curvature_per_km=coin.choice([1e-6, 0.01, 0.01, 0.1, 2.0]),
            lineament_turn_deg=coin.choice([10.0, 30.0, 60.0, 89.0]),
            lineament_straight_m=coin.choice([5.0, 30.0, 90.0]),
            lineament_piece_m=coin.choice([10.0, 30.0, 60.0, 120.0]),
            lineament_min_length_m=coin.choice([10.0, 30.0, 60.0, 120.0, 600.0]),
            lineament_link_angle_deg=coin.choice([5.0, 10.0, 45.0]),
            lineament_link_offset_m=coin.choice([10.0, 30.0, 90.0]),
            lineament_link_gap_m=coin.choice([1.0, 60.0, 300.0]))
    return {"kind": "terrain",
            "grid": {"rows": rows, "cols": cols, "lon0": lon0, "lat0": lat0, "step": step, "assumed": assumed,
                     "cm": cm},
            "options": {"rows": rows, "cols": cols, "settings": settings, "shown": shown, "sea_clean": sea_clean,
                        "source_id": source_id, "label": label, "where": where, "read": read, "meta": meta}}


def _terrain_file(case: dict) -> tuple[bytes, str]:
    """The window both engines analyse, as bytes: its heights (centimetres
    in metres, south row first), then the longitudes of its columns and the
    latitudes of its rows, all float64 little-endian, then one byte a cell
    marking the missing tile taken as sea. Python makes every number, so
    the browser reads the same bits rather than working them out again."""
    grid = case["grid"]
    rows, cols, step = grid["rows"], grid["cols"], grid["step"]
    z = [_SPECIAL[v] if isinstance(v, str) else v / 100.0 for row in grid["cm"] for v in row]
    lons = [grid["lon0"] + j * step for j in range(cols)]
    lats = [grid["lat0"] + j * step for j in range(rows)]
    sea = bytearray(rows * cols)
    for r0, r1, c0, c1 in grid["assumed"]:
        for r in range(r0, r1):
            sea[r * cols + c0:r * cols + c1] = b"\x01" * (c1 - c0)
    return struct.pack(f"<{len(z) + cols + rows}d", *z, *lons, *lats) + bytes(sea), ".grid"


CASES = {"deflate": deflate_case, "geotiff": geotiff_case, "terrain": terrain_case}

#: The file both engines are handed for a case of each kind here, and its
#: suffix: the block itself for ``deflate``, the file for ``geotiff``, and
#: for ``terrain`` the window's numbers (_terrain_file).
FILES = {"deflate": _deflate_file, "geotiff": _geotiff_file, "terrain": _terrain_file}

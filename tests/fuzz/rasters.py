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
"""

from __future__ import annotations

import base64
import importlib.util
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


CASES = {"deflate": deflate_case, "geotiff": geotiff_case}

#: The file both engines are handed for a case of each kind here, and its
#: suffix: the block itself for ``deflate``, the file for ``geotiff``.
FILES = {"deflate": _deflate_file, "geotiff": _geotiff_file}

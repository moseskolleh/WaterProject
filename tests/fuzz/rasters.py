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
"""

from __future__ import annotations

import base64
import random
import struct
import zlib

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


CASES = {"deflate": deflate_case}

#: The file both engines are handed for a case of each kind here, and its
#: suffix: the block itself for ``deflate``.
FILES = {"deflate": _deflate_file}

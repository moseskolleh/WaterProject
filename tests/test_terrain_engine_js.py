"""The browser's terrain engine in Node, held to the Python one.

gwt-core.js decodes the compressed blocks of an elevation model itself
(C.inflateZlib, C.lzwDecode, C.packbitsDecode): synchronously, because the
worker's tasks are, and so without DecompressionStream, which answers only
asynchronously and which a Node sandbox does not have. Everything here is
synchronous, so it runs in a Node vm - no browser - over gwt-data.js and
gwt-core.js as the page loads them, and each test hands both engines the
same blocks and requires the same verdict and, where a block is accepted,
the same bytes.

For DEFLATE the oracle is zlib itself: the Python side is zlib under the
bounded rule (geotiff._inflate_block), so a stream zlib refuses and the
browser accepts, or the reverse, fails here by name. The parity suite holds
the same on a committed set in Chromium (the ``inflate`` section of
tests/webapp/parity.mjs), where DecompressionStream checks it a third way.

The browser's GeoTIFF reader (C.geotiffLayout, C.blockRanges,
C.decodeTiffBlock, C.readGeoTiff) is held here to the committed fixtures in
tests/webapp/fixtures/dem, whose MANIFEST.json says what GDAL reads in each,
and to files made in memory by the same builder for what no fixture holds;
and, answer for answer, to the Python reader itself, on every fixture and on
several hundred files made to descriptions (make_dem_fixture.described_file)
that reach each rule the two were settled to.

The browser's elevation layer (C.elevationFile, C.windowCentre,
C.planElevationWindow, C.elevationBlockRanges, C.readElevationWindow,
C.terrainCredit and the degree trigonometry under them) is held to
groundwater/mapping/elevation.py the same way, answer for answer: every set
in the fixture manifest and every fixture alone, .hgt tiles made here, and
each refusal, run through both engines as the page runs them.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import math
import random
import shutil
import struct
import subprocess
import sys
import zlib
from functools import cache
from pathlib import Path

import pytest

from conftest import DeflateWriter, lzw_encode, lzw_pack, packbits_encode
from groundwater.geotiff import _CodecError, _inflate_block, _lzw_decode_loop, _packbits_decode

JS = Path(__file__).resolve().parents[1] / "docs" / "js"

_DRIVER = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone });
for (const f of ['gwt-data.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const Bytes = vm.runInContext('Uint8Array', sandbox);
const input = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const blocks = input.blocks.map((b64) => new Bytes(Buffer.from(b64, 'base64')));
const decode = {
  inflate: (bytes, expected, full) => C.inflateZlib(bytes, expected, full),
  lzw: (bytes, expected) => C.lzwDecode(bytes, expected),
  packbits: (bytes, expected) => C.packbitsDecode(bytes, expected),
};
writeFileSync(process.argv[4], JSON.stringify(input.runs.map(([codec, block, expected, full]) => {
  try {
    const out = decode[codec](blocks[block], expected, full);
    return ['accepted', C.sha256Hex(out), out.length];
  } catch (e) {
    return e && e.code ? [e.code, null, null] : ['threw ' + String(e && e.stack || e), null, null];
  }
})));
"""

_PYTHON = {
    "inflate": lambda data, expected, full: _inflate_block(data, expected, full),
    "lzw": lambda data, expected, full: _lzw_decode_loop(data, expected),
    "packbits": lambda data, expected, full: _packbits_decode(data, expected),
}


def _python(codec: str, data: bytes, expected: int, full: int) -> list:
    try:
        out = _PYTHON[codec](data, expected, full)
    except _CodecError as exc:
        return [exc.code, None, None]
    return ["accepted", hashlib.sha256(out).hexdigest(), len(out)]


def _browser(tmp_path: Path, blocks: list[bytes], runs: list[list]) -> list:
    """What gwt-core.js answers for each ``[codec, block, expected, full]``."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path / "codecs.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({
        "blocks": [base64.b64encode(b).decode("ascii") for b in blocks],
        "runs": runs,
    }), encoding="utf-8")
    out = tmp_path / "answers.json"
    subprocess.run([node, str(driver), str(JS), str(cases), str(out)], check=True, timeout=300)
    return json.loads(out.read_text(encoding="utf-8"))


def _both_engines_agree(tmp_path: Path, codec: str, cases: list) -> int:
    """Run every ``(name, block, bounds)`` through both engines; the number of
    runs, after failing on any that differ."""
    blocks, runs, names = [], [], []
    for name, block, bounds in cases:
        for expected, full in bounds:
            runs.append([codec, len(blocks), expected, full])
            names.append(f"{name} (expected {expected}, full {full})")
        blocks.append(block)
    browser = _browser(tmp_path, blocks, runs)
    differ = []
    for name, (_, index, expected, full), js in zip(names, runs, browser, strict=True):
        py = _python(codec, blocks[index], expected, full)
        if js != py:
            differ.append(f"{name}: browser {js}, python {py}")
    assert not differ, f"{len(differ)} of {len(runs)} differ:\n" + "\n".join(differ[:20])
    return len(runs)


# ------------------------------------------------------------------ data


def _sample(rng: random.Random, kind: str, n: int) -> bytes:
    """``n`` bytes of one kind of content a block holds."""
    out = bytearray()
    if kind == "random":
        return rng.randbytes(n)
    if kind == "zeros":
        return bytes(n)
    if kind == "text":
        words = [b"borehole ", b"aquifer ", b"laterite ", b"granite ", b"strike ", b"m\n"]
        while len(out) < n:
            out += rng.choice(words)
    elif kind == "runs":
        while len(out) < n:
            out += bytes([rng.randrange(256)]) * rng.randrange(1, 300)
    elif kind == "heights":
        # int16 heights in a random walk, as a DEM's rows hold them
        z = 120
        while len(out) < n:
            z = max(-30, min(900, z + rng.randrange(-3, 4)))
            out += struct.pack("<h", z)
    elif kind == "floats":
        # float32 heights to a tenth of a metre, most significant byte first
        z = 52.0
        while len(out) < n:
            z = round(z + rng.randrange(-4, 5) / 10, 1)
            out += struct.pack(">f", z)
    else:  # "repeats": one passage again and again, slightly changed
        base = bytearray(rng.randbytes(rng.randrange(50, 3000)))
        while len(out) < n:
            base[rng.randrange(len(base))] = rng.randrange(256)
            out += base
    return bytes(out[:n])


_KINDS = ["random", "zeros", "text", "runs", "heights", "floats", "repeats"]
_STRATEGIES = [zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED, zlib.Z_HUFFMAN_ONLY, zlib.Z_RLE, zlib.Z_FIXED]


def _bounds(n: int) -> list[tuple[int, int]]:
    """(expected, full) around a stream's true length ``n``: exact, padded,
    one short, one over and well over."""
    out = {(n, n), (n, n + 7), (0, n + 100), (n + 1, n + 9)}
    if n:
        out |= {(n - 1, n), (max(0, n - 9), n - 1)}
    return sorted(out)


def _zlib_stream(data: bytes, level=6, strategy=zlib.Z_DEFAULT_STRATEGY, mem=8, wbits=15) -> bytes:
    c = zlib.compressobj(level, zlib.DEFLATED, wbits, mem, strategy)
    return c.compress(data) + c.flush()


def _flushed(rng: random.Random, data: bytes) -> bytes:
    """``data`` in two to five pieces, each ended by a full or sync flush
    and joined into one zlib stream. Mostly each piece has a compressor of
    its own level and strategy, which puts stored and Huffman blocks side by
    side as a writer that changes level mid-stream does; now and then one
    compressor writes them all."""
    cuts = sorted(rng.randrange(len(data) + 1) for _ in range(rng.randrange(1, 5)))
    pieces = [data[a:b] for a, b in zip([0, *cuts], [*cuts, len(data)], strict=True)]
    body = b""
    shared = rng.random() < 0.3
    c = zlib.compressobj(rng.randrange(10), zlib.DEFLATED, -15, 8, rng.choice(_STRATEGIES))
    for i, piece in enumerate(pieces):
        if not shared:
            c = zlib.compressobj(rng.randrange(10), zlib.DEFLATED, -15, rng.randrange(1, 10),
                                 rng.choice(_STRATEGIES))
        last = i == len(pieces) - 1
        body += c.compress(piece) + c.flush(
            zlib.Z_FINISH if last else rng.choice([zlib.Z_FULL_FLUSH, zlib.Z_SYNC_FLUSH]))
    return b"\x78\x9c" + body + struct.pack(">I", zlib.adler32(data))


def _complete(n: int) -> list[int]:
    """Code lengths for ``n`` symbols that make a complete code: ``a`` of
    them one bit shorter than the rest, with 2a + b = 2^(L+1)."""
    for length in range(1, 15):
        a = (1 << (length + 1)) - n
        if 0 <= a <= n:
            return [length] * a + [length + 1] * (n - a)
    raise ValueError(n)


def _crafted(rng: random.Random) -> list[tuple[str, bytes, int, bool]]:
    """Streams no encoder writes, each with the length it stands for and
    whether zlib accepts it: every acceptance rule the browser copies from
    zlib, one stream each, so each is shown to be zlib's rule as well."""
    lit, dist = _complete(286), _complete(30)
    out = []

    def add(name, writer, accepted):
        out.append((name, writer.zlib(), len(writer.data), accepted))

    w = DeflateWriter()
    w.fixed([*rng.randbytes(32768), ("copy", 258, 32768)], last=True)
    add("a copy of 258 bytes from 32,768 back", w, True)
    w = DeflateWriter()
    w.fixed([1, 2, 3, ("raw", 284, 5, 31, 0, 0, 0)], last=True)
    add("length 258 spelt as code 284 with extra 31", w, True)
    w = DeflateWriter()
    w.fixed([*b"twelve bytes", ("copy", 12, 12)], last=True)
    add("a copy reaching back to the first byte", w, True)
    w = DeflateWriter()
    w.fixed([*b"twelve bytes", ("copy", 12, 13)], last=True)
    add("a copy reaching back before the first byte", w, False)
    for symbol in (286, 287):
        w = DeflateWriter()
        w.fixed([65, ("raw", symbol, 0, 0, None, 0, 0)], last=True)
        add(f"fixed literal/length {symbol}", w, False)
    for symbol in (30, 31):
        w = DeflateWriter()
        w.fixed([*b"abcdef", ("raw", 257, 0, 0, symbol, 0, 0)], last=True)
        add(f"fixed distance {symbol}", w, False)
    w = DeflateWriter()
    w.bits(1, 1)
    w.bits(3, 2)
    w.bits(0, 13)
    add("block type 3", w, False)
    w = DeflateWriter()
    w.stored(b"stored", last=True, nlen=0x1234)
    add("a stored block whose NLEN is not ~LEN", w, False)
    w = DeflateWriter()
    w.stored(b"", last=True)
    add("one empty stored block", w, True)
    w = DeflateWriter()
    w.stored(rng.randbytes(65535), last=True)
    add("a 65,535-byte stored block", w, True)
    w = DeflateWriter()
    w.stored(rng.randbytes(65535))
    w.stored(rng.randbytes(70000 - 65535), last=True)
    add("a 70,000-byte stored stream", w, True)
    w = DeflateWriter()
    w.fixed([*b"abc"])
    w.stored(b"stored")
    w.fixed([("copy", 6, 6)], last=True)
    add("a stored block straight after a fixed one that ends mid-byte", w, True)
    for i in range(12):
        # stored blocks after Huffman blocks that end mid-byte: the bits read
        # ahead have to go back before LEN and NLEN are read
        w = DeflateWriter()
        for _ in range(rng.randrange(2, 7)):
            text: list = list(_sample(rng, rng.choice(_KINDS), rng.randrange(0, 300)))
            kind = rng.choice(["fixed", "stored", "dynamic"])
            if kind == "stored":
                w.stored(bytes(text))
                continue
            if text and rng.random() < 0.5:
                text.append(("copy", rng.randrange(3, 259), rng.randrange(1, len(w.data) + len(text) + 1)))
            if kind == "fixed":
                w.fixed(text)
            else:
                w.dynamic(lit, dist, text)
        w.fixed([], last=True)
        add(f"mixed stored, fixed and dynamic blocks {i}", w, True)

    w = DeflateWriter()
    w.dynamic(lit, dist, [*b"dynamic", ("copy", 7, 7)], last=True)
    add("a dynamic block", w, True)
    w = DeflateWriter()
    w.dynamic(lit + [0, 0], dist, [65], last=True)
    add("a dynamic block declaring 288 literal/lengths", w, False)
    w = DeflateWriter()
    w.dynamic(lit, dist + [0], [65], last=True)
    add("a dynamic block declaring 31 distances", w, False)
    w = DeflateWriter()
    w.dynamic(lit, dist, [65], last=True, cl=[4] * 15 + [0, 4, 0, 0],
              sequence=[(16, 0)] + [(n, 0) for n in lit + dist][3:])
    add("a repeat with no length before it", w, False)
    w = DeflateWriter()
    w.dynamic(lit, dist, [65], last=True, cl=[4] * 15 + [0] * 4)
    add("an incomplete code-length code", w, False)
    w = DeflateWriter()
    w.dynamic(lit, dist, [65], last=True, cl=[4] * 16 + [4, 0, 0])
    add("an over-subscribed code-length code", w, False)
    w = DeflateWriter()
    w.dynamic([1, 1] + lit[2:], dist, [], last=True)
    add("an over-subscribed literal/length code", w, False)
    w = DeflateWriter()
    w.dynamic(lit[:-1] + [0], dist, [65], last=True)
    add("an incomplete literal/length code", w, False)
    w = DeflateWriter()
    w.dynamic([0] * 256 + [1] + [0] * 29, dist, [], last=True)
    add("a single one-bit code, the end of the block", w, True)
    w = DeflateWriter()
    w.dynamic([*lit[:256], 0, *lit[257:]], dist, [], last=True)
    add("no code for the end of the block", w, False)
    w = DeflateWriter()
    w.dynamic(lit, [0] * 30, [*b"literals only"], last=True)
    add("no distance codes and no copies", w, True)
    w = DeflateWriter()
    w.dynamic(lit, [0] * 30, [*b"abc", ("copy", 3, 3)], last=True)
    add("no distance codes and a copy", w, False)
    w = DeflateWriter()
    w.dynamic(lit, [1] + [0] * 29, [*b"zz", ("copy", 10, 1)], last=True)
    add("a single one-bit distance code", w, True)
    w = DeflateWriter()
    w.dynamic(lit, [2, 2, 2] + [0] * 27, [*b"zz", ("copy", 10, 1)], last=True)
    add("an incomplete distance code", w, False)
    w = DeflateWriter()
    w.dynamic(lit, [3] * 9 + [0] * 21, [*b"zz", ("copy", 10, 1)], last=True)
    add("an over-subscribed distance code", w, False)
    sequence = [(n, 0) for n in lit] + [(n, 0) for n in dist]
    w = DeflateWriter()
    w.dynamic(lit, dist, [65], last=True, cl=[4] * 15 + [0, 4, 0, 0],
              sequence=sequence[:-2] + [(16, 3)])
    add("a repeat running past the last length", w, False)
    # zeros repeated from the last literal/length into the first distances
    lit0 = [8] * 251 + [9] * 10 + [0] * 25
    dist0 = [0] * 3 + [4] * 5 + [5] * 22
    w = DeflateWriter()
    w.dynamic(lit0, dist0, [*b"abcd", ("copy", 4, 4)], last=True, cl=[4] * 15 + [0, 0, 0, 4],
              sequence=[(n, 0) for n in lit0[:261]] + [(18, 28 - 11)] + [(n, 0) for n in dist0[3:]])
    add("a run of zero lengths across the literal/length and distance sets", w, True)
    return out


def _corrupt(rng: random.Random, name: str, stream: bytes) -> list[tuple[str, bytes]]:
    """A valid stream broken each of the ways a file is damaged."""
    out = []
    for cut in sorted({1, len(stream) - 1, rng.randrange(1, len(stream))}):
        out.append((f"{name}, cut to {cut} bytes", stream[:cut]))
    for _ in range(3):
        at = rng.randrange(len(stream))
        flipped = bytearray(stream)
        flipped[at] ^= 1 << rng.randrange(8)
        out.append((f"{name}, bit flipped at byte {at}", bytes(flipped)))
    out.append((f"{name}, bad Adler-32", stream[:-1] + bytes([stream[-1] ^ 0x5A])))
    out.append((f"{name}, junk after the checksum", stream + rng.randbytes(rng.randrange(1, 40))))
    return out


def _inflate_cases() -> list:
    rng = random.Random(41)
    valid: list[tuple[str, bytes, int]] = []
    sizes = [0, 1, 37, 1000, 6000, 20000]
    for level in range(10):
        for s, strategy in enumerate(_STRATEGIES):
            kind = _KINDS[(level + s) % len(_KINDS)]
            data = _sample(rng, kind, rng.choice(sizes))
            mem, wbits = rng.choice([1, 8, 9]), rng.choice([9, 12, 15])
            name = f"{kind} at level {level}, strategy {strategy}, memLevel {mem}, window 2^{wbits}"
            valid.append((name, _zlib_stream(data, level, strategy, mem, wbits), len(data)))
    for level in (0, 1, 6, 9):
        valid.append((f"an empty stream at level {level}", zlib.compress(b"", level), 0))
    valid.append(("an empty stream, fixed codes", _zlib_stream(b"", 6, zlib.Z_FIXED), 0))
    data = rng.randbytes(70000)
    valid.append(("70,000 random bytes at level 0", zlib.compress(data, 0), len(data)))
    for i in range(30):
        data = b"".join(_sample(rng, rng.choice(_KINDS), rng.randrange(0, 9000)) for _ in range(3))
        valid.append((f"pieces flushed and joined {i}", _flushed(rng, data), len(data)))

    cases = []
    for name, stream, n, accepted in _crafted(rng):
        verdict = _python("inflate", stream, n, n)[0]
        assert verdict == ("accepted" if accepted else "damaged"), (
            f"zlib reads '{name}' otherwise than the test expects")
        cases.append((name, stream, _bounds(n)))
    for name, stream, n in valid:
        assert _inflate_block(stream, n, n) is not None, name
        cases.append((name, stream, _bounds(n)))
    for name, stream, n in valid[::2]:
        for broken, data in _corrupt(rng, name, stream):
            cases.append((broken, data, [(n, n), (0, 2 * n + 16)]))
    raw = zlib.compressobj(6, zlib.DEFLATED, -15)
    data = _sample(rng, "text", 4000)
    gz = zlib.compressobj(6, zlib.DEFLATED, 31)
    with_dict = zlib.compressobj(6, zlib.DEFLATED, 15, zdict=b"borehole aquifer")
    body = zlib.compress(data)[2:]

    def header(cmf: int) -> bytes:
        """CMF and an FLG that passes the header check, no dictionary."""
        return bytes([cmf, (31 - (cmf << 8) % 31) % 31])

    for name, stream in [
        ("raw DEFLATE with no zlib wrapper", raw.compress(data) + raw.flush()),
        ("a gzip member", gz.compress(data) + gz.flush()),
        ("a stream that needs a preset dictionary", with_dict.compress(data) + with_dict.flush()),
        ("a 64 KB window, which zlib does not have", header(0x88) + body),
        ("compression method 7", header(0x77) + body),
        ("a window of 256 bytes, read as 32 KB", header(0x08) + body),
        ("a header that fails its check", bytes([0x78, 0x9D]) + body),
        ("one byte", b"\x78"),
        ("no bytes at all", b""),
    ]:
        cases.append((name, stream, [(len(data), len(data)), (0, 10 * len(data))]))
    # a stream that inflates to 5 MB, stopped at one full block
    bomb = zlib.compressobj(9)
    stream = b"".join(bomb.compress(bytes(1 << 20)) for _ in range(5)) + bomb.flush()
    cases.append(("5 MB of zeros", stream, [(4096, 4096), (5 << 20, 5 << 20)]))
    return cases


def test_browser_inflate_gives_zlibs_verdict_and_bytes_on_every_level_strategy_and_corruption(tmp_path):
    """C.inflateZlib against zlib, under the bounded rule, on every level
    and strategy zlib has, small and declared-small windows, empty streams,
    stored blocks of the largest size, a copy from the far end of the
    window, flushed and joined pieces, mixed block types, hand-made streams
    breaking each of zlib's acceptance rules, the usual corruptions and a
    zip bomb. Prevents the browser accepting a block zlib refuses, or
    refusing one it reads: hand-written inflates are usually looser than
    zlib, and the looseness shows up as a damaged tile read as heights."""
    cases = _inflate_cases()
    assert len({stream for _, stream, _ in cases}) >= 400
    runs = _both_engines_agree(tmp_path, "inflate", cases)
    assert runs >= 1000


# ---------------------------------------------------------------- LZW


def _pillow_strips(compression: str) -> list[tuple[str, bytes, int]]:
    """Strips libtiff itself wrote, through Pillow, with the bytes each
    stands for. Little-endian only: Pillow writes II."""
    from PIL import Image, features

    if not features.check("libtiff"):
        return []
    rng = random.Random(7)
    out = []
    for mode, size, kind in [("L", (512, 300), "heights"), ("L", (64, 48), "random"),
                             ("I;16", (200, 90), "heights"), ("L", (300, 200), "runs")]:
        depth = 2 if mode == "I;16" else 1
        pixels = _sample(rng, kind, size[0] * size[1] * depth)
        buffer = io.BytesIO()
        Image.frombytes(mode, size, pixels).save(buffer, format="TIFF", compression=compression)
        image = Image.open(io.BytesIO(buffer.getvalue()))
        raw = buffer.getvalue()
        rows = image.tag_v2[278]
        for k, (offset, count) in enumerate(zip(image.tag_v2[273], image.tag_v2[279], strict=True)):
            height = min(rows, size[1] - k * rows)
            out.append((f"libtiff {compression} {mode} {size} strip {k}", raw[offset:offset + count],
                        height * size[0] * depth))
    return out


def _deferred_clear_strip(extra: int) -> bytes:
    """The strip the GDAL check used: 256 x 256 bytes from ten letters,
    which fill the table quickly, with ``extra`` codes sent after it is
    full and before the Clear."""
    rng = random.Random(3)
    image = bytes(rng.choice(b"ABCDEFGHIJ") for _ in range(256 * 256))
    return lzw_encode(image, limit=4096, defer=extra)


def _lzw_cases() -> list:
    rng = random.Random(5119)
    valid = []
    for kind in _KINDS:
        for n in (1, 300, 5000, 40000):
            data = _sample(rng, kind, n)
            valid.append((f"{kind}, {n} bytes", lzw_encode(data), n))
    data = _sample(rng, "heights", 9000)
    valid.append(("no end code", lzw_encode(data, end=False), len(data)))
    valid.append(("codes after the block", lzw_encode(data) + rng.randbytes(50), len(data)))
    valid.append(("an empty strip", lzw_encode(b""), 0))
    for extra in (1, 50, 1000, 1024, 1025, 1100):
        valid.append((f"a deferred clear after {extra} codes", _deferred_clear_strip(extra), 256 * 256))
    valid += _pillow_strips("tiff_lzw")

    cases = []
    for name, stream, n in valid:
        cases.append((name, stream, sorted({(n, n), (max(0, n - 1),) * 2, (n + 1, n + 1),
                                            (0, 0), (n // 2, n // 2)})))
    for name, stream, n in valid[::3]:
        if len(stream) < 4:
            continue
        for _ in range(3):
            at = rng.randrange(len(stream))
            flipped = bytearray(stream)
            flipped[at] ^= 1 << rng.randrange(8)
            cases.append((f"{name}, bit flipped at byte {at}", bytes(flipped), [(n, n)]))
        cut = rng.randrange(1, len(stream))
        cases.append((f"{name}, cut to {cut} bytes", stream[:cut], [(n, n), (n // 3, n // 3)]))
    hand = [
        ("a first code past the literals", lzw_pack([(256, 9), (300, 9), (257, 9)])),
        ("a code past the next entry", lzw_pack([(256, 9), (65, 9), (66, 9), (262, 9), (257, 9)])),
        ("the code that is about to be made", lzw_pack([(256, 9), (65, 9), (258, 9), (257, 9)])),
        ("Clear twice", lzw_pack([(256, 9), (256, 9), (65, 9), (257, 9)])),
        ("no Clear first", lzw_pack([(65, 9), (66, 9), (258, 9), (257, 9)])),
        ("the pre-1992 form", b"\x00\x01" + rng.randbytes(30)),
        ("a zero byte, then an even one", b"\x00\x02" + rng.randbytes(30)),
        ("one zero byte", b"\x00"),
        ("nothing", b""),
    ]
    for name, stream in hand:
        cases.append((name, stream, [(1, 1), (3, 3), (4, 4), (40, 40)]))
    return cases


def test_browser_lzw_matches_the_python_decoder_on_random_deferred_clear_and_corrupt_strips(tmp_path):
    """C.lzwDecode against the loop decoder in geotiff.py on strips of
    every kind of content, strips libtiff wrote, deferred-clear strips on
    both sides of libtiff's table limit, strips without an end code or
    with codes after the block, and broken ones. Prevents the browser and
    Python reading one strip as two different sets of heights, or one of
    them reading a strip the other refuses."""
    runs = _both_engines_agree(tmp_path, "lzw", _lzw_cases())
    assert runs >= 300


# ------------------------------------------------------------ PackBits


def _packbits_cases() -> list:
    rng = random.Random(32773)
    valid = []
    for kind in _KINDS:
        for n in (1, 200, 7000):
            data = _sample(rng, kind, n)
            valid.append((f"{kind}, {n} bytes", packbits_encode(data), n))
    valid.append(("Apple's example", bytes.fromhex("FEAA0280002AFDAA0380002A22F7AA"), 24))
    valid.append(("no-op headers between runs", b"\x80\x02abc\x80\x80\xfdz\x80", 7))
    valid += _pillow_strips("packbits")
    cases = []
    for name, stream, n in valid:
        cases.append((name, stream, sorted({(n, n), (max(0, n - 1),) * 2, (n + 1, n + 1),
                                            (0, 0), (n // 2, n // 2)})))
    for i in range(30):
        stream = rng.randbytes(rng.randrange(0, 60))
        cases.append((f"random bytes {i}", stream, [(k, k) for k in (1, 10, 100, 1000)]))
    for name, stream in [("a literal run cut short", b"\x05ab"), ("a repeat with no byte", b"\x01ab\xfe"),
                         ("only no-ops", b"\x80\x80\x80")]:
        cases.append((name, stream, [(1, 1), (2, 2), (3, 3), (6, 6)]))
    return cases


def test_browser_packbits_matches_the_python_decoder(tmp_path):
    """C.packbitsDecode against geotiff.py on PackBits of every kind of
    content, strips libtiff wrote, no-op headers, runs cut by the block
    size and runs cut by the end of the data. Prevents the two engines
    reading a QGIS "low compression" file differently."""
    runs = _both_engines_agree(tmp_path, "packbits", _packbits_cases())
    assert runs >= 100


# ------------------------------------------------------- GeoTIFF reader

DEM = Path(__file__).resolve().parent / "webapp" / "fixtures" / "dem"

# gwt-core.js kept up in one Node vm and asked one question a line, so that
# a test can drive the reader step by step - the byte-range protocol above
# all - as the page's own loop does, without starting Node for each step.
# Numbers JSON cannot carry (NaN, the infinities, -0) go as strings.
_READER = r"""
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone });
for (const f of ['gwt-data.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const Bytes = vm.runInContext('Uint8Array', sandbox);
// bytes copied into the sandbox's own Uint8Array, holding only what is given
const copy = (buffer) => { const out = new Bytes(buffer.length); out.set(buffer); return out; };
const b64 = (typed) => Buffer.from(typed.buffer, typed.byteOffset, typed.byteLength).toString('base64');
const plain = (key, v) => (typeof v !== 'number' ? v : Object.is(v, -0) ? '-0.0' :
  Number.isFinite(v) ? v : String(v));
const ops = {
  // a file on disk (path), or one made in the test (data, base64)
  read({ path, data, name }) {
    const read = C.readGeoTiff(copy(path ? readFileSync(path) : Buffer.from(data, 'base64')), name);
    return { layout: read.layout, rows: read.rows, cols: read.cols,
             z: b64(read.z), x: b64(read.x), y: b64(read.y) };
  },
  layout({ name, size, chunks }) {
    const got = C.geotiffLayout(name, size,
      chunks.map(([offset, data]) => [offset, copy(Buffer.from(data, 'base64'))]));
    return Array.isArray(got) ? { need: got } : { layout: got };
  },
  // a window read as the elevation layer reads one: the ranges blockRanges
  // lists, each decoded from only its own bytes and written where it lands
  window({ path, name, j0, j1, i0, i1, bounds }) {
    const file = readFileSync(path);
    const layout = C.geotiffLayout(name, file.length, [[0, copy(file)]]);
    const ranges = C.blockRanges(layout, j0, j1, i0, i1);
    const w = i1 - i0, values = new Float64Array((j1 - j0) * w), reasons = new Uint8Array(values.length);
    reasons.fill(9);
    const across = layout.tiled ? Math.ceil(layout.width / layout.blockWidth) : 1;
    for (const [index, offset, length, rows] of ranges) {
      const block = C.decodeTiffBlock(layout, index, copy(file.subarray(offset, offset + length)), rows, bounds);
      const top = Math.floor(index / across) * layout.blockHeight + (rows ? rows[0] : 0);
      const left = (index % across) * layout.blockWidth;
      for (let r = 0; r < block.rows; r++) {
        for (let c = 0; c < block.cols; c++) {
          const j = top + r, i = left + c;
          if (j < j0 || j >= j1 || i < i0 || i >= i1) continue;
          values[(j - j0) * w + i - i0] = block.values[r * block.cols + c];
          reasons[(j - j0) * w + i - i0] = block.reasons[r * block.cols + c];
        }
      }
    }
    return { ranges, values: b64(values), reasons: b64(reasons) };
  },
  // everything test_the_two_readers_agree_* compares, made as _agreed makes it
  agree({ data, name, bounds }) {
    const file = Buffer.from(data, 'base64');
    const answer = (ranges) => refusal(() => {
      const got = C.geotiffLayout(name, file.length,
        ranges.map(([offset, length]) => [offset, copy(file.subarray(offset, offset + length))]));
      return Array.isArray(got) ? { need: got } : { layout: layoutView(got) };
    });
    const rounds = [], ranges = [[0, 16]];
    let final;
    for (let k = 0; k < 200; k++) {
      final = answer(ranges);
      if (!final.need) break;
      rounds.push(final.need);
      ranges.push(...final.need);
    }
    const out = { rounds, final, whole: answer([[0, file.length]]) };
    if (out.whole.layout) {
      out.read = refusal(() => readAll(file, name, bounds));
      out.window = refusal(() => readWindow(file, name, bounds));
    }
    return out;
  },
};
// a refusal as [id, sentence, values]; anything else thrown is a fault
function refusal(f) {
  try {
    return f();
  } catch (e) {
    if (e && e.ident) return { refused: [e.ident, e.message, e.values] };
    throw e;
  }
}
// the layout's numbers that are not whole as their float64 bits, so -0, NaN and infinities compare
const FLOATS = new Set(['x0', 'y0', 'sx', 'sy', 'nodata']);
function hex(v) { const b = Buffer.alloc(8); b.writeDoubleBE(v); return b.toString('hex'); }
function layoutView(layout) {
  return Object.fromEntries(Object.entries(layout).map(([k, v]) => [k, FLOATS.has(k) && v !== null ? hex(v) : v]));
}
// every NaN written as the one NaN, so that values compare by their bytes
function canon(a) { for (let i = 0; i < a.length; i++) if (a[i] !== a[i]) a[i] = NaN; return a; }
// the window's blocks as blockRanges lists them, each decoded and put where it lands
function place(file, layout, j0, j1, i0, i1, judge) {
  const across = layout.tiled ? Math.ceil(layout.width / layout.blockWidth) : 1;
  const ranges = C.blockRanges(layout, j0, j1, i0, i1), w = i1 - i0;
  const values = new Float64Array((j1 - j0) * w).fill(-1), reasons = new Uint8Array(values.length).fill(9);
  for (const [index, offset, length, rows] of ranges) {
    const block = C.decodeTiffBlock(layout, index, copy(file.subarray(offset, offset + length)), rows, judge);
    const top = Math.floor(index / across) * layout.blockHeight + (rows ? rows[0] : 0);
    const left = (index % across) * layout.blockWidth;
    for (let r = 0; r < block.rows; r++) {
      for (let c = 0; c < block.cols; c++) {
        const j = top + r, i = left + c;
        if (j < j0 || j >= j1 || i < i0 || i >= i1) continue;
        values[(j - j0) * w + i - i0] = block.values[r * block.cols + c];
        reasons[(j - j0) * w + i - i0] = block.reasons[r * block.cols + c];
      }
    }
  }
  return { ranges, values: b64(canon(values)), reasons: b64(reasons) };
}
function readAll(file, name, bounds) {
  const read = C.readGeoTiff(copy(file), name), layout = read.layout, H = read.rows, W = read.cols;
  const raw = place(file, layout, 0, H, 0, W, null), judged = place(file, layout, 0, H, 0, W, bounds);
  return { rows: H, cols: W, z: b64(canon(read.z)), x: b64(read.x), y: b64(read.y), reasons: raw.reasons,
           judged: judged.values, judgedReasons: judged.reasons };
}
// a window read on its own, and its first block decoded from one byte too few
function readWindow(file, name, bounds) {
  const layout = C.geotiffLayout(name, file.length, [[0, copy(file)]]), H = layout.height, W = layout.width;
  const j0 = Math.floor(H / 3), j1 = Math.max(j0 + 1, H - Math.floor(H / 4));
  const i0 = Math.floor(W / 5), i1 = Math.max(i0 + 1, W - Math.floor(W / 3));
  const part = place(file, layout, j0, j1, i0, i1, bounds);
  const first = part.ranges.find((range) => range[2] > 0);
  const short = !first ? null : refusal(() => {
    const block = C.decodeTiffBlock(layout, first[0], copy(file.subarray(first[1], first[1] + first[2] - 1)),
      first[3], bounds);
    return { values: b64(canon(block.values)), reasons: b64(block.reasons) };
  });
  return { at: [j0, j1, i0, i1], ranges: part.ranges, values: part.values, reasons: part.reasons, short };
}
for await (const line of createInterface({ input: process.stdin })) {
  const request = JSON.parse(line);
  let answer;
  try {
    answer = { ok: ops[request.op](request) };
  } catch (e) {
    answer = e && e.ident ? { refused: e.ident, code: e.code, values: e.values, message: e.message }
      : { threw: String(e && e.stack || e) };
  }
  process.stdout.write(JSON.stringify(answer, plain) + '\n');
}
"""


class _Reader:
    """The browser's GeoTIFF reader in a Node vm (or another driver of the
    engine's), asked one question at a time."""

    def __init__(self, tmp_path: Path, script: str = _READER, filename: str = "reader.mjs"):
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed; run `node --version` to check")
        driver = tmp_path / filename
        driver.write_text(script, encoding="utf-8")
        self._node = subprocess.Popen([node, str(driver), str(JS)], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, text=True, encoding="utf-8")

    def ask(self, op: str, **request) -> dict:
        assert self._node.stdin is not None and self._node.stdout is not None
        self._node.stdin.write(json.dumps({"op": op, **request}) + "\n")
        self._node.stdin.flush()
        line = self._node.stdout.readline()
        assert line, "the Node driver stopped; its error is above"
        answer = json.loads(line)
        assert "threw" not in answer, answer["threw"]
        return answer

    def close(self) -> None:
        assert self._node.stdin is not None
        self._node.stdin.close()
        self._node.wait(timeout=60)


@pytest.fixture
def reader(tmp_path):
    browser = _Reader(tmp_path)
    yield browser
    browser.close()


_MANIFEST = json.loads((DEM / "MANIFEST.json").read_text(encoding="ascii"))
_FILES = _MANIFEST["files"]
_DTYPES = {(1, 8): "u1", (2, 8): "i1", (1, 16): "u2", (2, 16): "i2",
           (1, 32): "u4", (2, 32): "i4", (3, 32): "f4", (3, 64): "f8"}
# MANIFEST.json's layout facts and the browser's names for them
_FACTS = {"byte_order": "byteOrder", "bigtiff": "bigtiff", "width": "width", "height": "height",
          "tiled": "tiled", "block_width": "blockWidth", "block_height": "blockHeight",
          "rows_per_strip": "rowsPerStrip", "compression": "compression", "predictor": "predictor",
          "sample_format": "sampleFormat", "bits": "bits", "model_type": "modelType",
          "raster_type": "rasterType", "epsg": "epsg"}
# the words a refusal is filled with, where the file decides them (addendum A2)
_REFUSED_WITH = {
    "refuse_truncated.tif": {"part": "image directory"},
    "refuse_truncated_data.tif": {"part": "data block 4"},
    "refuse_bad_adler.tif": {"n": 1, "bytes": 96},
    "refuse_zero_rows_per_strip.tif": {"tag": "RowsPerStrip"},
    "refuse_zero_tile_width.tif": {"tag": "TileWidth"},
    "refuse_jpeg.tif": {"method": "JPEG"},
    "refuse_two_bands.tif": {"n": 2},
    "nodata_abc.tif": {"text": "abc"},
}


def _number(value) -> float:
    """A number as the driver sends it, as a float: JSON writes a whole one as
    an integer, and the driver NaN, the infinities and -0 as strings."""
    return float(value)


def _bits(value) -> bytes:
    """A number's float64 bits, so that -0, NaN and the infinities compare as they are."""
    return struct.pack("<d", float(value))


def _floats(b64: str):
    import numpy as np

    return np.frombuffer(base64.b64decode(b64), "<f8")


def _gdal_samples(entry: dict, layout: dict, z_north) -> bytes:
    """The file's samples as MANIFEST.json's digest holds them (GDAL's view),
    rebuilt from the reader's: each void back to what the file stores there - 0
    in a sparse block, as GDAL reads one without a no-data value, else the
    no-data value, else NaN - and each -0 the file stores back from the +0 the
    reader made of it."""
    import numpy as np

    native = z_north.copy()
    sparse = np.zeros(native.shape, dtype=bool)
    across = -(-layout["width"] // layout["blockWidth"]) if layout["tiled"] else 1
    for index in entry.get("sparse_blocks", []):
        ty, tx = divmod(index, across)
        sparse[ty * layout["blockHeight"]:(ty + 1) * layout["blockHeight"],
               tx * layout["blockWidth"]:(tx + 1) * layout["blockWidth"]] = True
    voids = np.isnan(native)
    native[voids & sparse] = 0.0
    if layout["nodata"] is not None:
        native[voids & ~sparse] = _number(layout["nodata"])
    for r, c in entry.get("negative_zero_cells", []):
        assert native[r, c] == 0 and not np.signbit(native[r, c]), f"-0 at ({r}, {c}) was kept"
        native[r, c] = -0.0
    dtype = _DTYPES[(layout["sampleFormat"], layout["bits"])]
    return native.astype("<" + dtype).tobytes()


def test_the_browser_reader_reads_every_committed_fixture_as_the_manifest_says(reader):
    """C.readGeoTiff on every file in tests/webapp/fixtures/dem: read or refused as
    MANIFEST.json says, a refusal with the sentence groundwater.text writes for the
    same values; the layout facts; the cell centres to the bit; every sample as
    GDAL reads the file (but for sparse blocks and -0, which the reader voids and
    canonicalises on purpose); the axes as start + index * step; and the cells the
    per-sample rule voids under the configured plausibility bounds. Prevents the
    browser reading a fixture otherwise than GDAL does - a byte-order, predictor or
    half-cell slip shows up as a wrong digest or centre - and a refusal carrying
    another sentence, or other words, than the catalogue's."""
    import numpy as np

    from groundwater.config import TerrainConfig
    from groundwater.text import phrase

    terrain = TerrainConfig()
    bounds = [terrain.implausible_below_m, terrain.implausible_above_m]
    assert len(_FILES) >= 60
    for name, entry in sorted(_FILES.items()):
        answer = reader.ask("read", path=str(DEM / name), name=name)
        if entry["raw"] != "read":
            assert answer.get("refused") == entry["raw"], f"{name}: {answer}"
            values = answer["values"]
            assert values["file"] == name, name
            assert answer["code"] == entry["raw"].removeprefix("terrain."), name
            assert answer["message"] == phrase(entry["raw"], **values), name
            for key, value in _REFUSED_WITH.get(name, {}).items():
                assert values[key] == value, f"{name}: {key} is {values[key]!r}, not {value!r}"
            continue
        assert "ok" in answer, f"{name}: {answer}"
        read = answer["ok"]
        layout = read["layout"]
        for fact, key in _FACTS.items():
            if fact in entry:
                assert layout[key] == entry[fact], f"{name}: {key} is {layout[key]!r}, not {entry[fact]!r}"
        assert layout["ifdIndex"] == entry.get("ifd_index", 0), name
        assert layout["name"] == name and layout["size"] == (DEM / name).stat().st_size, name
        assert layout["predictorApplied"] == (entry["predictor"] != 1 and entry["compression"] in (5, 8, 32946))
        assert layout["hasNodataTag"] == ("nodata" in entry), name
        assert layout["hasMask"] is entry.get("has_mask", False), name
        if "nodata" not in entry or entry["nodata_value"] in (None, "no cell"):
            assert layout["nodata"] is None, name
        else:
            assert _bits(_number(layout["nodata"])) == _bits(entry["nodata_value"]), name
        for key in ("x0", "y0", "sx", "sy"):
            assert repr(_number(layout[key])) == repr(entry[key]), (
                f"{name}: {key} is {layout[key]!r}, not {entry[key]!r}")

        rows, cols = read["rows"], read["cols"]
        assert (rows, cols) == (entry["height"], entry["width"]), name
        z_north = _floats(read["z"]).reshape(rows, cols)[::-1]
        digest = hashlib.sha256(_gdal_samples(entry, layout, z_north)).hexdigest()
        assert digest == entry["samples_sha256"], f"{name}: the samples differ from GDAL's"
        x0, y0, sx, sy = (_number(layout[k]) for k in ("x0", "y0", "sx", "sy"))
        assert _floats(read["x"]).tobytes() == np.array([x0 + i * sx for i in range(cols)]).tobytes(), name
        assert _floats(read["y"]).tobytes() == np.array(
            [y0 - (rows - 1 - r) * sy for r in range(rows)]).tobytes(), name

        window = reader.ask("window", path=str(DEM / name), name=name, j0=0, j1=rows, i0=0, i1=cols,
                            bounds=bounds)["ok"]
        why = np.frombuffer(base64.b64decode(window["reasons"]), np.uint8)
        voids = {"no_data": int((why == 1).sum()), "implausible": int((why == 2).sum())}
        assert voids == entry.get("voids", {"no_data": 0, "implausible": 0}), f"{name}: {voids}"


def _chunks(data: bytes, ranges) -> list:
    return [[offset, base64.b64encode(data[offset:offset + length]).decode("ascii")]
            for offset, length in ranges]


def _entry(data: bytes, tag: int) -> int:
    """Where the first directory's entry for ``tag`` starts, in a classic TIFF."""
    order = "<" if data[:2] == b"II" else ">"
    ifd = struct.unpack_from(order + "I", data, 4)[0]
    for k in range(struct.unpack_from(order + "H", data, ifd)[0]):
        if struct.unpack_from(order + "H", data, ifd + 2 + 12 * k)[0] == tag:
            return ifd + 2 + 12 * k
    raise KeyError(tag)


def _patched(data: bytes, at: int, raw: bytes) -> bytes:
    return data[:at] + raw + data[at + len(raw):]


@cache
def _builder():
    """tests/webapp/fixtures/make_dem_fixture.py, to make files in memory that no
    fixture holds, with the samples it meant them to hold."""
    name = "make_dem_fixture"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, DEM.parent / "make_dem_fixture.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module   # a dataclass looks its module up while the class is made
        spec.loader.exec_module(module)
    return sys.modules[name]


def _covered(ranges, offset: int, length: int) -> bool:
    return any(o <= offset and offset + length <= o + n for o, n in ranges)


def test_the_browser_layout_asks_only_for_the_bytes_it_still_needs(reader):
    """C.geotiffLayout driven as the page drives it, from nothing, a round at a
    time, given exactly the ranges it names and nothing more, on every committed
    fixture. Each round names a sorted, de-duplicated list of ranges inside the
    file that no chunk it already has covers, and never a byte of image data; the
    last round ends on exactly the layout (or the refusal) the whole file gives at
    once. The same holds when each range is read rounded out to 64 KiB, as the
    Python driver reads; and a range split across two chunks is asked for again
    whole. Prevents a reader that asks again for what it has, asks for tile data
    it does not need, never settles on a directory it cannot see, or ends on a
    layout other than the one the whole file gives."""
    for name in sorted(_FILES):
        data = (DEM / name).read_bytes()
        size = len(data)
        whole = reader.ask("layout", name=name, size=size, chunks=_chunks(data, [(0, size)]))
        assert "need" not in whole.get("ok", {}), name
        blocks = []
        if "ok" in whole:
            layout = whole["ok"]["layout"]
            blocks = [(o, n) for o, n in zip(layout["offsets"], layout["byteCounts"], strict=True) if n]
        for rounding in (1, 65536):
            have: list[tuple[int, int]] = []
            for _ in range(140):
                answer = reader.ask("layout", name=name, size=size, chunks=_chunks(data, have))
                need = answer.get("ok", {}).get("need")
                if need is None:
                    break
                if not have:
                    assert need == [[0, 16]], name
                assert need == [list(r) for r in sorted({tuple(r) for r in need})], f"{name}: {need}"
                for offset, length in need:
                    assert length > 0 and offset >= 0 and offset + length <= size, f"{name}: {need}"
                    assert not _covered(have, offset, length), f"{name}: asked again for {offset}+{length}"
                    # the 16-byte header read may run into data that starts at byte 8
                    for o, n in blocks if (offset, length) != (0, 16) else []:
                        assert offset + length <= o or o + n <= offset, (
                            f"{name}: asked for image data at {offset}+{length}")
                    start = offset - offset % rounding
                    end = min(size, -(-(offset + length) // rounding) * rounding)
                    have.append((start, end - start))
            else:
                pytest.fail(f"{name}: the layout still asks for bytes after 140 rounds")
            assert answer == whole, f"{name}: driven round by round it ends as {answer}, not {whole}"

    # a range must lie in one chunk: the first directory split in two is asked for again
    name = "be_lzw_p2_int16.tif"
    data = (DEM / name).read_bytes()
    ifd = struct.unpack_from(">I", data, 4)[0]
    halves = [(0, ifd + 20), (ifd + 20, len(data) - ifd - 20)]
    need = reader.ask("layout", name=name, size=len(data), chunks=_chunks(data, halves))["ok"]["need"]
    assert any(o < ifd + 20 < o + n for o, n in need), need

    # two tags whose values lie in the same bytes: the range is asked for once
    offsets_at, counts_at = _entry(data, 273), _entry(data, 279)
    data = _patched(data, counts_at + 8, data[offsets_at + 8:offsets_at + 12])
    entries = struct.unpack_from(">H", data, ifd)[0]
    need = reader.ask("layout", name=name, size=len(data),
                      chunks=_chunks(data, [(0, 16), (ifd, 2 + 12 * entries + 4)]))["ok"]["need"]
    shared = [struct.unpack_from(">I", data, offsets_at + 8)[0], 12]
    assert need.count(shared) == 1 and len({tuple(r) for r in need}) == len(need) >= 3, need


# fixtures read in windows: tiled and striped, compressed and not, sparse
# tiles, both byte orders and an image directory at the end of the file
_WINDOWED = ["Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", "sparse_f32.tif",
             "bigtiff_deflate_p2_f32.tif", "nodata_neg_inf.tif", "le_lzw_p3_f64.tif",
             "be_lzw_p2_int16.tif", "transform_f32.tif", "inf_f32.tif", "utm_strip.tif",
             "pred2_none.tif", "packbits_u16.tif", "nodata_empty.tif", "padded_last_strip.tif",
             "overlap_south_disagrees.tif"]


def _windows(rows: int, cols: int) -> list[tuple[int, int, int, int]]:
    """Windows (j0, j1, i0, i1) of every shape a reader is asked for: all of it,
    one cell, one row, one column, across block edges, inside one strip, the
    corners."""
    out = {(0, rows, 0, cols), (0, 1, 0, 1), (rows - 1, rows, cols - 1, cols),
           (rows // 2, rows // 2 + 1, 0, cols), (0, rows, cols // 2, cols // 2 + 1),
           (1, rows - 1, 1, cols - 1), (3, min(rows, 10), 2, min(cols, 19)),
           (rows // 3, 2 * rows // 3 + 1, cols // 4, 3 * cols // 4 + 1),
           (min(rows - 1, 15), min(rows, 17), min(cols - 1, 15), min(cols, 17))}
    return sorted(w for w in out if w[0] < w[1] and w[2] < w[3])


def test_the_browser_reader_decodes_only_the_blocks_a_window_meets(reader):
    """C.blockRanges and C.decodeTiffBlock on windows of tiled and striped
    fixtures: the blocks listed are exactly those the window meets, in the file's
    order; an uncompressed strip only part of which is wanted is read for those
    rows alone (offset and length to the byte), and every other block whole; and
    the window, put together from those bytes only, equals the whole read's slice
    to the bit, with the reasons of the per-sample rule, with and without the
    plausibility bounds. Prevents a window that decodes blocks it does not need,
    misses one it does, reads a partial strip from the wrong place, or comes out
    other than the same cells read whole."""
    import numpy as np

    from groundwater.config import TerrainConfig

    terrain = TerrainConfig()
    low, high = terrain.implausible_below_m, terrain.implausible_above_m
    partial = 0
    for name in _WINDOWED:
        whole = reader.ask("read", path=str(DEM / name), name=name)["ok"]
        layout, rows, cols = whole["layout"], whole["rows"], whole["cols"]
        z_north = _floats(whole["z"]).reshape(rows, cols)[::-1]
        bw, bh, size = layout["blockWidth"], layout["blockHeight"], layout["bits"] // 8
        across = -(-cols // bw) if layout["tiled"] else 1
        for j0, j1, i0, i1 in _windows(rows, cols):
            for bounds in (None, [low, high]):
                got = reader.ask("window", path=str(DEM / name), name=name, j0=j0, j1=j1, i0=i0, i1=i1,
                                 bounds=bounds)["ok"]
                where = f"{name} rows {j0}:{j1} columns {i0}:{i1} bounds {bounds}"
                meets = [ty * across + tx for ty in range(j0 // bh, (j1 - 1) // bh + 1)
                         for tx in range(i0 // bw, (i1 - 1) // bw + 1)]
                assert [r[0] for r in got["ranges"]] == meets, where
                for index, offset, length, part in got["ranges"]:
                    top = (index // across) * bh
                    held = min(bh, rows - top)
                    r0, r1 = max(j0 - top, 0), min(j1 - top, held)
                    sparse = layout["offsets"][index] == 0 and layout["byteCounts"][index] == 0
                    if layout["compression"] == 1 and not layout["tiled"] and (r0, r1) != (0, held):
                        partial += 1
                        assert part == [r0, r1], where
                        assert (offset, length) == ((0, 0) if sparse else (
                            layout["offsets"][index] + r0 * cols * size, (r1 - r0) * cols * size)), where
                    else:
                        assert part is None, where
                        assert (offset, length) == (layout["offsets"][index], layout["byteCounts"][index]), where
                values = _floats(got["values"]).reshape(j1 - j0, i1 - i0)
                why = np.frombuffer(base64.b64decode(got["reasons"]), np.uint8).reshape(values.shape)
                expected = z_north[j0:j1, i0:i1].copy()
                reasons = np.where(np.isnan(expected), 1, 0).astype(np.uint8)
                if bounds:
                    odd = ~np.isnan(expected) & (np.isinf(expected) | (expected < low) | (expected > high))
                    reasons[odd] = 2
                    expected[odd] = np.nan
                assert why.tobytes() == reasons.tobytes(), where
                assert values.tobytes() == expected.tobytes(), where
    assert partial >= 20


def _spread(rng: random.Random, kind: str, width: int, height: int) -> list[list]:
    """Samples of ``kind`` over its whole range, so that every carry and every
    byte of every word is exercised."""
    if kind[0] == "f":
        return [[rng.uniform(-500.0, 3000.0) for _ in range(width)] for _ in range(height)]
    bits = int(kind[1:])
    low, high = (0, (1 << bits) - 1) if kind[0] == "u" else (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
    return [[rng.randint(low, high) for _ in range(width)] for _ in range(height)]


def test_the_browser_reader_undoes_both_predictors_on_every_sample_type_byte_order_and_layout(reader):
    """C.readGeoTiff on files the fixture builder makes in memory: horizontal
    differencing on 8-, 16-, 32- and 64-bit words (float bit patterns included,
    the 64-bit ones added as two 32-bit halves with the carry taken across) and
    the floating-point predictor on float32 and float64, each in both byte
    orders, under LZW and DEFLATE, in tiles with padding and in strips, classic
    and BigTIFF; and a Predictor tag left alone without LZW or DEFLATE. Every
    sample must be the one the builder wrote. Prevents a predictor undone in the
    host's byte order instead of the file's, a carry lost between the halves of a
    64-bit word - no committed fixture differences 64-bit words - or a predictor
    applied where libtiff and GDAL ignore it."""
    import numpy as np

    make = _builder()
    rng = random.Random(4101)
    georef = make.Georef(-11.0, 8.0, 1 / 1200, 1 / 1200, raster=1)
    runs = []
    for kind in ("u8", "i8", "u16", "i16", "u32", "i32", "f32", "f64"):
        for order in "<>":
            for compression in (5, 8):
                for layout in ({"tile": (16, 16)}, {"rows_per_strip": 5}):
                    for predictor in (2, 3) if kind[0] == "f" else (2,):
                        runs.append((kind, order, compression, predictor, layout, len(runs) % 3 == 0))
            for compression in (1, 32773):
                runs.append((kind, order, compression, 2, {"rows_per_strip": 5}, False))
    for kind, order, compression, predictor, layout, bigtiff in runs:
        made = make.single("made.tif", "", _spread(rng, kind, 37, 23), kind, georef, order=order,
                           bigtiff=bigtiff, compression=compression, predictor=predictor, **layout)
        where = f"{kind} {order} compression {compression} predictor {predictor} {layout} bigtiff {bigtiff}"
        read = reader.ask("read", data=base64.b64encode(made.data).decode("ascii"), name=made.name)["ok"]
        assert read["layout"]["predictorApplied"] == (compression in (5, 8)), where
        z_north = _floats(read["z"]).reshape(23, 37)[::-1]
        dtype = _DTYPES[(read["layout"]["sampleFormat"], read["layout"]["bits"])]
        assert z_north.astype(np.dtype(dtype).newbyteorder("<")).tobytes() == made.samples, where
    assert len(runs) >= 90


def test_the_browser_reader_refuses_each_damaged_or_unsupported_header_with_its_sentence(reader):
    """C.readGeoTiff and C.geotiffLayout on files the fixture builder makes in
    memory, each broken or unusual in one way no committed fixture is: every
    header check, sample type, compression and predictor rule, each kind of
    damaged entry, the 2^53 limit, the 64-directory walk, the 64 MiB block limit,
    the georeferencing forms GDAL takes or refuses, and the no-data and GDAL
    scale texts. Each is refused with its sentence and the words addendum A2
    gives it, or read with the layout it should have. Prevents the reader
    misreading a file it should refuse, refusing one GDAL reads, or naming the
    wrong tag, method or code in the sentence the operator sees."""
    from groundwater.text import phrase

    make = _builder()
    sx = 1 / 1200
    georef = make.Georef(-12.2, 7.2, sx, sx, raster=1)
    small = make.metres(make.patch(8, 6, 41))
    whole = make.whole_metres(make.patch(8, 6, 41))
    flt_max = 3.4028234663852886e38

    def tif(rows=small, kind="f32", **options) -> bytes:
        return make.single("case.tif", "", rows, kind, georef, **options).data

    def chain(overviews: int) -> bytes:
        """``overviews`` reduced images ahead of the full one."""
        ifds = []
        for _ in range(overviews):
            reduced = make.image([[1.0, 2.0], [3.0, 4.0]], "f32", "<")
            reduced.tags[make.NEW_SUBFILE_TYPE] = (make.LONG, [1])
            ifds.append(reduced)
        full = make.image(small, "f32", "<")
        full.tags.update(georef.tags())
        return make.assemble("<", ifds + [full])

    plain, big = tif(rows_per_strip=4), tif(bigtiff=True)
    counts_at = _entry(plain, 279)
    matrix = [sx, 0.0, 0.0, -12.2, 0.0, -sx, 0.0, 7.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    keys = make.GEO_KEY_DIRECTORY

    def items(*pairs):
        return make.metadata_xml(*((role.upper(), role, text) for role, text in pairs))

    cases = [
        ("a ZIP file", b"PK\x03\x04" + bytes(60), "terrain.not_tiff", {}),
        ("TIFF version 44", _patched(plain, 2, b"\x2c\x00"), "terrain.not_tiff", {}),
        ("BigTIFF with 4-byte offsets", _patched(big, 4, b"\x04\x00"), "terrain.not_tiff", {}),
        ("a first directory at 2^53", _patched(big, 8, struct.pack("<Q", 1 << 53)), "terrain.too_large", {}),
        ("a first directory at 2^53 - 1", _patched(big, 8, struct.pack("<Q", (1 << 53) - 1)),
         "terrain.ends_early", {"part": "image directory"}),
        ("ten bytes", plain[:10], "terrain.ends_early", {"part": "file header"}),
        ("no directory at all", _patched(plain, 4, bytes(4)), "terrain.no_full_image", {}),
        ("63 overviews, then the image", chain(63), "read", {"ifdIndex": 63}),
        ("64 overviews, then the image", chain(64), "terrain.no_full_image", {}),
        ("SampleFormat 4", tif(tags={make.SAMPLE_FORMAT: (make.SHORT, [4])}),
         "terrain.sample_type", {"bits": 32, "kind": "SampleFormat 4"}),
        ("12-bit samples", tif(whole, "u16", tags={make.BITS_PER_SAMPLE: (make.SHORT, [12])}),
         "terrain.sample_type", {"bits": 12, "kind": "unsigned integer"}),
        ("signed 64-bit samples", tif(tags={make.BITS_PER_SAMPLE: (make.SHORT, [64]),
                                            make.SAMPLE_FORMAT: (make.SHORT, [2])}),
         "terrain.sample_type", {"bits": 64, "kind": "signed integer"}),
        ("Zstandard", tif(tags={make.COMPRESSION: (make.SHORT, [50000])}),
         "terrain.compression", {"method": "Zstandard"}),
        ("compression 9", tif(tags={make.COMPRESSION: (make.SHORT, [9])}),
         "terrain.compression", {"method": "TIFF method 9"}),
        ("LZW with predictor 4", tif(compression=5, tags={make.PREDICTOR: (make.SHORT, [4])}),
         "terrain.predictor", {"code": 4}),
        ("LZW integers with predictor 3", tif(whole, "i16", compression=5, tags={make.PREDICTOR: (make.SHORT, [3])}),
         "terrain.predictor", {"code": 3}),
        ("no compression with predictor 7", tif(tags={make.PREDICTOR: (make.SHORT, [7])}),
         "read", {"predictor": 7, "predictorApplied": False}),
        ("RowsPerStrip that disagrees with the strips",
         tif(rows_per_strip=4, tags={make.ROWS_PER_STRIP: (make.SHORT, [2])}),
         "terrain.bad_tag", {"tag": "StripOffsets"}),
        ("one byte count short", _patched(plain, counts_at + 4, struct.pack("<I", 1)),
         "terrain.bad_tag", {"tag": "StripByteCounts"}),
        ("ImageWidth 0", tif(tags={make.IMAGE_WIDTH: (make.SHORT, [0])}), "terrain.bad_tag", {"tag": "ImageWidth"}),
        ("TileLength 0", tif(tile=(16, 16), tags={make.TILE_LENGTH: (make.SHORT, [0])}),
         "terrain.bad_tag", {"tag": "TileLength"}),
        ("a negative RowsPerStrip", tif(tags={make.ROWS_PER_STRIP: (make.SSHORT, [-1])}),
         "terrain.bad_tag", {"tag": "RowsPerStrip"}),
        ("Compression written as text", tif(tags={make.COMPRESSION: (make.ASCII, b"1\x00")}),
         "terrain.bad_tag", {"tag": "Compression"}),
        ("PlanarConfiguration of an unknown type", tif(tags={make.PLANAR_CONFIG: (13, b"\x01\x00\x00\x00")}),
         "terrain.bad_tag", {"tag": "PlanarConfiguration"}),
        ("NewSubfileType of an unknown type", tif(tags={make.NEW_SUBFILE_TYPE: (13, b"\x01\x00\x00\x00")}),
         "read", {"ifdIndex": 0}),
        ("GeoKeyDirectory version 2", tif(tags={keys: (make.SHORT, [2, 1, 0, 0])}),
         "terrain.bad_tag", {"tag": "GeoKeyDirectory"}),
        ("GeoKeyDirectory short of its keys", tif(tags={keys: (make.SHORT, [1, 1, 0, 2, 1024, 0, 1, 2])}),
         "terrain.bad_tag", {"tag": "GeoKeyDirectory"}),
        ("a transformation of 15 values", tif(tags={make.MODEL_TRANSFORMATION: (make.DOUBLE, matrix[:15])},
                                              drop=(make.MODEL_PIXEL_SCALE, make.MODEL_TIEPOINT)),
         "terrain.bad_tag", {"tag": "ModelTransformation"}),
        ("a transformation flipped north to south",
         tif(tags={make.MODEL_TRANSFORMATION: (make.DOUBLE, matrix[:5] + [sx] + matrix[6:])},
             drop=(make.MODEL_PIXEL_SCALE, make.MODEL_TIEPOINT)), "terrain.rotated", {}),
        ("a negative pixel scale", tif(tags={make.MODEL_PIXEL_SCALE: (make.DOUBLE, [sx, -sx, 0.0])}),
         "terrain.rotated", {}),
        ("a scale and no tiepoint", tif(drop=(make.MODEL_TIEPOINT,)), "terrain.no_georeference", {}),
        ("one tiepoint and no scale", tif(drop=(make.MODEL_PIXEL_SCALE,)), "terrain.no_georeference", {}),
        ("a transformation beside several tiepoints, as GDAL reads it",
         tif(tags={make.MODEL_TRANSFORMATION: (make.DOUBLE, matrix),
                   make.MODEL_TIEPOINT: (make.DOUBLE, [0.0, 0.0, 0.0, -12.2, 7.2, 0.0,
                                                       7.0, 5.0, 0.0, -12.19, 7.19, 0.0])},
             drop=(make.MODEL_PIXEL_SCALE,)),
         "read", {"x0": (-12.2 - 0 * sx) + 0.5 * sx, "y0": (7.2 + 0 * sx) - 0.5 * sx}),
        ("blocks of 128 MiB", tif(small, "f64", tile=(16, 16), tags={make.TILE_WIDTH: (make.SHORT, [4096]),
                                                                    make.TILE_LENGTH: (make.SHORT, [4096])}),
         "terrain.block_too_large", {"mb": 128}),
        ("GDAL scale 1.0 and offset -0", tif(metadata=items(("scale", " 1.0 "), ("offset", "-0"))), "read", {}),
        ("GDAL offset 0.5", tif(metadata=items(("scale", "1"), ("offset", "0.5"))), "terrain.scaled", {}),
        ("GDAL scale nan", tif(metadata=items(("scale", "nan"),)), "terrain.scaled", {}),
        ("an empty GDAL scale", tif(metadata=items(("scale", ""),)), "terrain.scaled", {}),
    ]
    for text, kind, nodata in [
        ("1.5", "i16", None), ("70000", "i16", None), (" -32768\t", "i16", -32768.0), ("-0", "i16", 0.0),
        ("-1", "u8", None), ("1e39", "f32", math.inf), ("-1e39", "f32", -math.inf), ("Infinity", "f32", math.inf),
        ("-3.40282346639e+038", "f32", -flt_max), ("3.4028235677973362e38", "f32", flt_max),
        ("3.4028235677973366e38", "f32", math.inf),
        ("+NaN", "f32", math.nan), ("0.1", "f32", struct.unpack("<f", struct.pack("<f", 0.1))[0]),
        ("0.1", "f64", 0.1), ("1e400", "f64", math.inf), ("-0", "f64", -0.0), (" \n", "f32", None),
    ]:
        rows = whole if kind[0] != "f" else small
        if kind == "u8":
            rows = [[v % 256 for v in row] for row in whole]
        cases.append((f"no-data {text!r} on {kind}", tif(rows, kind, nodata=text), "read",
                      {"nodata": nodata, "hasNodataTag": True}))
    for text, trimmed in [("0x10", "0x10"), ("1e", "1e"), (" 5 apples\n", "5 apples"), ("--1", "--1")]:
        cases.append((f"no-data {text!r}", tif(nodata=text), "terrain.nodata_unreadable", {"text": trimmed}))

    for what, data, outcome, facts in cases:
        answer = reader.ask("read", data=base64.b64encode(data).decode("ascii"), name="case.tif")
        if outcome != "read":
            assert answer.get("refused") == outcome, f"{what}: {answer}"
            assert answer["message"] == phrase(outcome, **answer["values"]), what
            assert answer["values"] == {"file": "case.tif", **facts}, f"{what}: {answer['values']}"
            continue
        assert "ok" in answer, f"{what}: {answer}"
        layout = answer["ok"]["layout"]
        for key, value in facts.items():
            if isinstance(value, float) or key == "nodata":
                assert (layout[key] is None) == (value is None), f"{what}: {key} is {layout[key]!r}"
                if value is not None:
                    assert _bits(_number(layout[key])) == _bits(value), f"{what}: {key} is {layout[key]!r}"
            else:
                assert layout[key] == value, f"{what}: {key} is {layout[key]!r}, not {value!r}"

    # a block of exactly 64 MiB is not too large: the limit is on anything more
    data = tif(small, "f64", tile=(16, 16), tags={make.TILE_WIDTH: (make.SHORT, [2048]),
                                                 make.TILE_LENGTH: (make.SHORT, [4096])})
    answer = reader.ask("layout", name="case.tif", size=len(data), chunks=_chunks(data, [(0, len(data))]))
    assert answer["ok"]["layout"]["blockWidth"] == 2048, answer


# ------------------------------------------- the two readers, held together

def _agreed_layout(layout) -> dict:
    """A Python layout as the driver's layoutView writes the browser's: the
    keys in camelCase, and the numbers that need not be whole (the centres,
    the cell sizes and the no-data value) as their float64 bits, so that -0,
    NaN and the infinities compare as they are."""
    import dataclasses
    import re

    out = {}
    for key, value in dataclasses.asdict(layout).items():
        if key in ("x0", "y0", "sx", "sy", "nodata") and value is not None:
            value = struct.pack(">d", value).hex()
        out[re.sub(r"_([a-z])", lambda m: m.group(1).upper(), key)] = value
    return out


def _f64(values) -> str:
    """Values as float64 bytes, little-endian, every NaN the one NaN, in base64."""
    import numpy as np

    a = np.array(values, dtype="<f8")
    a[np.isnan(a)] = np.nan
    return base64.b64encode(a.tobytes()).decode("ascii")


def _u8(values) -> str:
    import numpy as np

    return base64.b64encode(np.ascontiguousarray(values, dtype=np.uint8).tobytes()).decode("ascii")


def _agreed(name: str, data: bytes, bounds: list) -> dict:
    """What the Python reader does with a file, as the driver's ``agree`` says
    what the browser's does: the ranges the layout asks for round by round
    from a 16-byte first chunk, given exactly what it asks for; where that
    ends; and what the whole file gives at once. For a file whose layout
    reads: the whole read (values south row first, and both axes) with the
    reasons of the per-sample rule without and with the plausibility bounds;
    and a window inside the image, read on its own whether or not the whole
    file reads - the blocks listed for it, what they decode to, and the
    first of them decoded from one byte too few. A refusal is its id, its
    sentence and the words it was given."""
    import numpy as np

    from groundwater.geotiff import GeoTiffError, block_ranges, decode_block, geotiff_layout, read_geotiff

    def refusal(work):
        try:
            return work()
        except GeoTiffError as refused:
            return {"refused": [refused.ident, str(refused), refused.values]}

    def answer(ranges):
        def layout():
            found = geotiff_layout(name, len(data), [(o, data[o:o + n]) for o, n in ranges])
            return {"need": [list(r) for r in found]} if isinstance(found, list) else {"layout": _agreed_layout(found)}
        return refusal(layout)

    def place(layout, j0, j1, i0, i1, judge):
        """The window's blocks as block_ranges lists them, each decoded and put where it lands."""
        ranges = block_ranges(layout, j0, j1, i0, i1)
        values = np.full((j1 - j0, i1 - i0), -1.0)
        reasons = np.full(values.shape, 9, dtype=np.uint8)
        across = -(-layout.width // layout.block_width) if layout.tiled else 1
        for index, offset, length, rows in ranges:
            block, why = decode_block(layout, index, data[offset:offset + length], rows, judge)
            top = index // across * layout.block_height + (rows[0] if rows else 0)
            left = index % across * layout.block_width
            down = (max(j0, top), min(j1, top + block.shape[0]))
            over = (max(i0, left), min(i1, left + block.shape[1]))
            at = slice(down[0] - j0, down[1] - j0), slice(over[0] - i0, over[1] - i0)
            inside = slice(down[0] - top, down[1] - top), slice(over[0] - left, over[1] - left)
            values[at], reasons[at] = block[inside], why[inside]
        listed = [[index, offset, length, list(rows) if rows else None] for index, offset, length, rows in ranges]
        return listed, _f64(values), _u8(reasons)

    def read():
        raster = read_geotiff(data, name)
        layout = raster.layout
        _, _, raw = place(layout, 0, layout.height, 0, layout.width, None)
        _, judged, judged_reasons = place(layout, 0, layout.height, 0, layout.width, tuple(bounds))
        return {"rows": layout.height, "cols": layout.width, "z": _f64(raster.z), "x": _f64(raster.x),
                "y": _f64(raster.y), "reasons": raw, "judged": judged, "judgedReasons": judged_reasons}

    def window():
        layout = geotiff_layout(name, len(data), [(0, data)])
        assert not isinstance(layout, list)
        height, width = layout.height, layout.width
        j0, i0 = height // 3, width // 5
        j1, i1 = max(j0 + 1, height - height // 4), max(i0 + 1, width - width // 3)
        ranges, values, reasons = place(layout, j0, j1, i0, i1, tuple(bounds))
        short = None
        for index, offset, length, rows in ranges:
            if length:
                def cut(index=index, offset=offset, length=length, rows=rows):
                    block, why = decode_block(layout, index, data[offset:offset + length - 1], rows, tuple(bounds))
                    return {"values": _f64(block), "reasons": _u8(why)}
                short = refusal(cut)
                break
        return {"at": [j0, j1, i0, i1], "ranges": ranges, "values": values, "reasons": reasons, "short": short}

    rounds, ranges = [], [(0, 16)]
    final: dict = {}
    for _ in range(200):
        final = answer(ranges)
        if "need" not in final:
            break
        rounds.append(final["need"])
        ranges += [tuple(r) for r in final["need"]]
    out = {"rounds": rounds, "final": final, "whole": answer([(0, len(data))])}
    if "layout" in out["whole"]:
        out["read"] = refusal(read)
        out["window"] = refusal(window)
    return json.loads(json.dumps(out))


_ARRAYS = {"z": "<f8", "x": "<f8", "y": "<f8", "judged": "<f8", "values": "<f8",
           "reasons": "u1", "judgedReasons": "u1"}


def _difference(py, js, path: str = "") -> str | None:
    """Where two answers first differ, and how; None when they are the same,
    a bool never passing for a number."""
    if isinstance(py, dict) and isinstance(js, dict):
        for key in sorted(set(py) | set(js)):
            if key not in py or key not in js:
                return f"{path}.{key}: python {py.get(key, '<missing>')!r}, browser {js.get(key, '<missing>')!r}"
            found = _difference(py[key], js[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(py, list) and isinstance(js, list) and len(py) == len(js):
        for i, (a, b) in enumerate(zip(py, js, strict=True)):
            found = _difference(a, b, f"{path}[{i}]")
            if found:
                return found
        return None
    if py == js and isinstance(py, bool) == isinstance(js, bool):
        return None
    key = path.rsplit(".", 1)[-1]
    if key in _ARRAYS and isinstance(py, str) and isinstance(js, str):
        import numpy as np

        a, b = (np.frombuffer(base64.b64decode(v), _ARRAYS[key]) for v in (py, js))
        if a.size != b.size:
            return f"{path}: python {a.size} values, browser {b.size}"
        bits = np.uint8 if a.itemsize == 1 else np.uint64
        k = int(np.flatnonzero(a.view(bits) != b.view(bits))[0])
        return f"{path}[{k}]: python {a[k]!r}, browser {b[k]!r}"
    return f"{path}: python {repr(py)[:300]}, browser {repr(js)[:300]}"


def _terrain_bounds() -> list:
    from groundwater.config import TerrainConfig

    terrain = TerrainConfig()
    return [terrain.implausible_below_m, terrain.implausible_above_m]


def _readers_agree(reader, name: str, data: bytes, bounds: list, where: str = "") -> dict:
    """Both readers on one file: the same answer to every question _agreed
    asks, or a failure saying where they part."""
    py = _agreed(name, data, bounds)
    js = reader.ask("agree", data=base64.b64encode(data).decode("ascii"), name=name, bounds=bounds)
    assert "ok" in js, f"{name} {where}: {js}"
    found = _difference(py, js["ok"])
    assert found is None, f"{name} {where}: {found}"
    return py


def _outcome(answer: dict) -> str:
    """'read', or the refusal a file met, in its layout or in its blocks."""
    refused = answer["whole"].get("refused") or answer.get("read", {}).get("refused")
    return refused[0] if refused else "read"


def test_the_two_readers_agree_on_every_committed_fixture(reader):
    """Every file in tests/webapp/fixtures/dem through both readers, compared
    whole: the layout (Python's field for field under the browser's
    camelCase names, the centres, cell sizes and no-data value to the bit);
    the ranges the layout asks for from a 16-byte first chunk and in each
    round after it; the values to the bit, signs of zero and infinities
    included, with both axes; the reasons of the per-sample rule without and
    with the plausibility bounds; the blocks a window inside the image lists
    and what they decode to; and a refusal's id, sentence and words. The
    parity suite holds the same files in Chromium against reference.json;
    this holds the two engines to each other in full, so that a rule settled
    one way in one engine and another way in the other cannot pass on the
    files both happen to read alike."""
    bounds = _terrain_bounds()
    outcomes: dict[str, int] = {}
    for name in sorted(_FILES):
        found = _outcome(_readers_agree(reader, name, (DEM / name).read_bytes(), bounds))
        assert found == _FILES[name]["raw"], f"{name}: {found}"
        outcomes[found] = outcomes.get(found, 0) + 1
    assert len(_FILES) >= 60 and outcomes["read"] >= 40 and len(outcomes) >= 15, outcomes


#: Field types for the odd-type cases: every TIFF type, and two TIFF does not define
_ODD_TYPES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18, 19]

#: Tags written with a damaged value, a count or a form each reader has to
#: settle one way, one list to a file, on files otherwise ordinary
_ODD_TAGS = [
    [[258, 3, [108]], [339, 3, [1]]],  # SampleFormat 1 with 108 bits, which 1 * 100 + 108 would read as 2, 8
    [[258, 3, [8, 8]], [277, 3, [1]]], [[258, 3, []]], [[339, 3, []]], [[259, 3, [1, 1]]], [[256, 3, []]],
    [[273, 4, []]], [[279, 4, []]], [[33550, 12, []]], [[33922, 12, []]], [[34735, 3, []]], [[34736, 12, []]],
    [[34737, 2, ""]], [[42113, 2, ""]], [[42112, 2, ""]],
    [[254, 13, "01000000"]], [[254, 4, [1, 0]]], [[254, 4, [4]]], [[255, 3, [2]]], [[255, 3, [1]]],
    [[254, 16, [0]]], [[255, 9, [1]]],
    [[266, 3, [2]]], [[266, 3, [3]]], [[266, 3, [0]]],
    [[317, 3, [0]]], [[317, 3, [4]]], [[317, 3, [7]]], [[317, 3, [3]]],
    [[278, 4, [0xFFFFFFFF]]], [[278, 4, [0]]], [[278, 3, [1000]]],
    [[34735, 3, [0, 1, 0, 0]]], [[34735, 3, [2, 1, 0, 0]]], [[34735, 3, [1, 1, 0]]],
    [[34735, 3, [1, 1, 0, 2, 1024, 0, 1, 2]]], [[34735, 3, [1, 1, 0, 2, 1024, 0, 1, 2, 1025, 0, 1, 3]]],
    [[34735, 3, [1, 1, 0, 3, 1024, 34736, 1, 0, 1024, 0, 1, 1, 3072, 0, 1, 32629]]],
    [[33550, 12, [1 / 1200]]], [[33550, 12, [1 / 1200, -1 / 1200, 0.0]]], [[33550, 12, [0.0, 1.0, 0.0]]],
    [[33922, 12, [0.0, 0.0, 0.0, -12.0]]],
    [[33922, 12, [0.0, 0.0, 0.0, -12.2, 7.2, 0.0, 7.0, 5.0, 0.0, -12.19, 7.19, 0.0]]],
    [[42112, 2, '<Item name="SCALE" role="scale"></Item>']], [[42112, 2, '<Item role="scale">nan</Item>']],
    [[42112, 2, '<Item role="offset">-0</Item><Item role="scale"> 1.0 </Item>']],
    [[42112, 2, '<Item role="offset">1e-400</Item>']], [[42113, 2, "-0\x00\x00"]],
]


def _described_specs() -> list[dict]:
    """A few hundred descriptions for make_dem_fixture.described_file: every
    sample type in both byte orders under every compression, with each
    predictor it can carry and an ignored one where it cannot, in strips and
    in tiles, classic and BigTIFF, Area and Point, in degrees and in UTM, with
    each form of no-data text, -0, the infinities, NaN and each type's
    extremes among the samples; then the same files damaged or cut short,
    with tags of other field types and counts, and with each georeferencing,
    GeoKey, no-data, scale, subfile and block-table form a reader has to
    settle one way."""
    make = _builder()
    rng = random.Random(4117)
    places = [{"x": -12.0, "y": 9.0, "sx": 1 / 3600, "sy": 1 / 3600, "model": 2, "epsg": 4326},
              {"x": 700000.0, "y": 950000.0, "sx": 30.0, "sy": 30.0, "model": 1, "epsg": 32629},
              {"x": -11.7, "y": 7.9, "sx": 1 / 1200, "sy": 1 / 1200, "model": 2, "epsg": 4326,
               "tie_col": 3, "tie_row": 2},
              {"x": -12.2, "y": 8.4, "sx": 1 / 1200, "sy": 1 / 1200, "model": 2, "epsg": 4326, "transform": True}]
    nodatas = [None, None, "", " ", "-9999", "nan", "-NaN", "-inf", "Infinity", "-0", "0", " 255 ", "65535",
               "-32768", "-32767", "4294967295", "-3.40282346639e+038", "1e39", "1.5", ".5e1", "1e400",
               "abc", "0x10", "5\x006", "--1"]
    names = list(make.NAMED_SAMPLES)

    def base(kind, order, compression, predictor) -> dict:
        width, height = rng.randint(3, 40), rng.randint(3, 40)
        spec = {"kind": kind, "width": width, "height": height, "seed": rng.randrange(1000), "order": order,
                "bigtiff": rng.random() < 0.15, "compression": compression, "predictor": predictor,
                "georef": {**rng.choice(places), "raster": rng.choice([1, 2, None])},
                "nodata": rng.choice(nodatas),
                "specials": [[rng.randrange(height), rng.randrange(width), rng.choice(names)]
                             for _ in range(rng.randint(0, 4))]}
        if rng.random() < 0.4:
            spec["tile"] = [16 * rng.randint(1, 2), 16 * rng.randint(1, 2)]
            if rng.random() < 0.2:
                spec["sparse"] = [0]
        else:
            spec["rows_per_strip"] = rng.randint(1, height)
        if rng.random() < 0.15:
            spec["ifds_first"] = False
        if rng.random() < 0.1:
            spec["overviews"] = rng.randint(1, 3)
        return spec

    plain = []
    for kind in make.KINDS:
        for order in "<>":
            for compression in (1, 5, 8, 32946, 32773):
                if compression in (5, 8, 32946):
                    predictors = [1, 2, 3] if kind[0] == "f" else [1, 2]
                else:  # the tag libtiff and GDAL ignore, written anyway
                    predictors = [1, rng.choice([2, 3, 0, 7])]
                plain += [base(kind, order, compression, predictor) for predictor in predictors]
    specs = list(plain)
    # damaged and cut short anywhere, header and directories included
    for spec in rng.sample(plain, 90):
        how = rng.choice(["cut", "byte", "flip"])
        extra = [rng.randrange(256)] if how == "byte" else [rng.randrange(8)] if how == "flip" else []
        specs.append({**spec, "damage": [[how, rng.randrange(1000), *extra]]})
    def pick(**want) -> dict:
        return dict(rng.choice([s for s in plain if all(s.get(k) == v for k, v in want.items())
                                and not s["georef"].get("transform")]))

    # each tag the readers judge, its own values written as every field type and as two TIFF does not define
    for tag in (254, 255, 256, 257, 258, 259, 266, 277, 278, 284, 317, 322, 323, 339, 33550, 33922, 34264,
                34735, 34736, 34737, 42112, 42113):
        for kind_of in _ODD_TYPES:
            spec = {**pick(), "retype": [[tag, kind_of]]}
            if tag in (322, 323):
                spec["tile"] = [16, 16]
            elif tag == 278:
                spec["tile"] = None
            if tag in (254, 255, 266, 317):
                spec["tags"] = [[tag, 3, [0 if tag in (254, 255) else 1]]]
            if tag == 34264:
                spec["georef"] = {**spec["georef"], "transform": True}
            if tag in (34736, 34737):
                spec["georef"] = {**places[0], "raster": 2, "copernicus_keys": True}
            if tag == 42112:
                spec["metadata"] = [["scale", "1"], ["offset", "0"]]
            if tag == 42113:
                spec["nodata"] = "-9999"
            specs.append(spec)
    for tags in _ODD_TAGS:
        specs += [{**pick(), "tags": tags} for _ in range(2)]
    for drop in ([33550], [33922], [33550, 33922], [34735], [258, 339], [273], [259], [256]):
        specs.append({**pick(), "drop": drop})
    # a scale of one value is a damaged entry even with no tiepoint to go with it
    specs.append({**pick(), "tags": [[33550, 12, [1 / 1200]]], "drop": [33922]})
    # dimensions BigTIFF's eight-byte fields allow, the 2^53 limit, a LONG8 value refused before any check
    # reads it, and blocks either side of 64 MiB
    for tags, strips in [([[256, 16, [1 << 53]]], False), ([[256, 16, [(1 << 53) - 1]]], False),
                         ([[257, 16, [1 << 33]], [278, 4, [0xFFFFFFFF]]], True),
                         ([[257, 16, [1 << 33]], [278, 16, [(1 << 32) + 5]]], True),
                         ([[266, 16, [1 << 53]], [259, 3, [50000]]], False),
                         ([[322, 3, [2064]], [323, 3, [32768]]], False), ([[322, 3, [2048]], [323, 3, [32768]]], False),
                         ([[322, 3, [4096]], [323, 3, [4097]]], False)]:
        spec = {**pick(), "kind": "u8", "tags": tags, "bigtiff": True, "tile": [16, 16], "predictor": 1}
        if strips:  # one strip, which a RowsPerStrip of 2^32 - 1 says
            spec["tile"], spec["rows_per_strip"] = None, None
        specs.append(spec)
    # counts: 2^53 and past the file on a tag no reader reads, 2^53 on one each reads, one more than the values
    for recount, bigtiff in [([[262, 1 << 53]], True), ([[262, (1 << 53) - 1]], True), ([[262, 1 << 31]], False),
                             ([[33550, 1 << 53]], True), ([[256, 2]], False), ([[42113, 0]], False),
                             ([[273, 1 << 40]], True), ([[34735, 3]], False)]:
        specs.append({**pick(), "recount": recount, "bigtiff": bigtiff, "nodata": "-9999"})
    # an uncompressed strip cut short past the window that reads part of it
    for kind in ("u8", "i16", "f32", "f64"):
        specs.append({**pick(kind=kind, compression=1), "tile": None, "rows_per_strip": None,
                      "damage": [["cut", 960]]})
    specs.append({**pick(), "count_type": 3})
    specs += [{**plain[0], "overviews": overviews} for overviews in (63, 64)]

    # and a file for each refusal, and each codec form, the draws above may miss
    specs += [
        {**pick(), "damage": [["byte", 0, 88]]},
        {**pick(), "overviews": 2, "tags": [[254, 4, [1]]], "loop_to": 0},
        {**pick(), "overviews": 1, "tags": [[255, 3, [2]]]},
        {**pick(), "tags": [[277, 3, [2]]]},
        {**pick(), "tags": [[259, 3, [50000]]]}, {**pick(), "tags": [[259, 3, [7]]]},
        {**pick(), "tags": [[259, 4, [99]]]},
        {**pick(kind="i16", compression=5), "encoder": {"old_lzw": True}},
        {**pick(), "drop": [33550],
         "tags": [[33922, 12, [0.0, 0.0, 0.0, -12.2, 7.2, 0.0, 7.0, 0.0, 0.0, -12.19, 7.2, 0.0]]]},
        {**pick(kind="f32", compression=5), "width": 40, "height": 40, "encoder": {"lzw_deferred": 1024}},
        {**pick(kind="f32", compression=5), "width": 40, "height": 40, "encoder": {"lzw_deferred": 1025}},
        {**pick(compression=32773), "encoder": {"packbits_noop": True}},
        {**pick(compression=8), "tile": None, "rows_per_strip": 3, "height": 10,
         "encoder": {"full_last_strip": True}},
    ]
    return specs


def test_the_two_readers_agree_on_files_made_in_memory_with_every_option(reader):
    """The comparison of test_the_two_readers_agree_on_every_committed_fixture
    on a few hundred files make_dem_fixture.described_file makes in memory
    (_described_specs): every encoding the readers take, each rule a file can
    meet one way or the other - a field type, a count, a predictor tag that
    is ignored, a GeoKey or no-data form, a sample type a folded code would
    mistake, a 2^53 value, a block either side of 64 MiB - and the same files
    damaged or cut short anywhere. Prevents the two readers settling a rule
    differently where no committed fixture looks; a failure names the first
    answer that differs and the description that made the file."""
    make = _builder()
    bounds = _terrain_bounds()
    specs = _described_specs()
    outcomes: dict[str, int] = {}
    for k, spec in enumerate(specs):
        answer = _readers_agree(reader, f"made{k}.tif", make.described_file(spec), bounds, json.dumps(spec))
        found = _outcome(answer)
        outcomes[found] = outcomes.get(found, 0) + 1
    assert len(specs) >= 300
    # the sample reaches every outcome a reader has: read, and each of its nineteen refusals
    assert outcomes["read"] >= 150 and len(outcomes) == 20, outcomes


def test_the_two_readers_agree_on_masks_block_tables_at_the_cap_and_no_data_beyond_float32(reader):
    """The rules the 4.1a review settled, through both readers and compared
    whole, round by round: a GDAL mask after the image (noted), one before
    it, of another size or reduced (not a mask of it), a mask directory past
    the end of the file or with a damaged NewSubfileType; a block table one
    entry over terrain.max_blocks (refused by its length before its values
    are read) and one at it; no-data values beyond float32, which round to
    an infinity rather than clamp to the largest float32, and those within
    half a step of it, which round to it; and damaged georeferencing, which
    the raw layer reads and the elevation layer refuses. Prevents the
    browser noting a mask, counting a table or casting a no-data value
    otherwise than Python."""
    from groundwater.config import TerrainConfig

    make = _builder()
    bounds = _terrain_bounds()
    cap = TerrainConfig().max_blocks
    sx = 1 / 1200
    rows = make.metres(make.patch(10, 6, 62))
    valid = [[c >= 3 for c in range(10)] for _ in range(6)]

    def masked(mask, after=True) -> bytes:
        full = make.image(rows, "f32", "<", compression=8)
        full.tags.update(make.Georef(-11.9, 8.4, sx, sx, raster=1).tags())
        return make.assemble("<", [full, mask] if after else [mask, full])

    def recounted(data: bytes, tag: int, count: int) -> bytes:
        return _patched(data, _entry(data, tag) + 4, struct.pack("<I", count))

    signed = make.mask_image(valid)
    signed.tags[make.NEW_SUBFILE_TYPE] = (make.SSHORT, [4])
    plain = masked(make.mask_image(valid))
    ifd = struct.unpack_from("<I", plain, 4)[0]
    count = struct.unpack_from("<H", plain, ifd)[0]
    strips = make.single("s.tif", "", rows, "f32", make.Georef(-11.9, 8.4, sx, sx, raster=1),
                         rows_per_strip=1).data
    peaks = [row[:] for row in rows]
    peaks[0][0], peaks[0][1], peaks[1][0] = 3.4028234663852886e38, math.inf, -math.inf
    files = {
        "a mask after the image": plain,
        "a mask before the image": masked(make.mask_image(valid), after=False),
        "a mask a row short": masked(make.mask_image(valid[:5])),
        "a reduced mask": masked(make.mask_image(valid, subfile=5)),
        "a mask as a page": masked(make.mask_image(valid, subfile=6)),
        "a mask past the end": _patched(plain, ifd + 2 + 12 * count, struct.pack("<I", len(plain) + 8)),
        "a mask of a signed type": masked(signed),
        "a table one over the cap": recounted(strips, make.STRIP_OFFSETS, cap + 1),
        "a table at the cap": recounted(strips, make.STRIP_BYTE_COUNTS, cap),
        "a NaN origin": make.single("n.tif", "", rows, "f32", make.Georef(math.nan, 8.4, sx, sx)).data,
        "a subnormal cell size": make.single("i.tif", "", rows, "f32",
                                             make.Georef(-11.9, 8.4, sx, 1e-320)).data,
    }
    for text in ("3.5e38", "1e39", "-1e39", "3.4028235677973366e38", "3.4028235677973362e38",
                 "-3.40282346639e+038", "inf"):
        files[f"no-data {text}"] = make.single("d.tif", "", peaks, "f32", make.Georef(-11.9, 8.4, sx, sx),
                                               nodata=text).data
    seen = {}
    for what, data in files.items():
        answer = _readers_agree(reader, "case.tif", data, bounds, what)
        layout = answer["whole"].get("layout") or {}
        seen[what] = layout.get("hasMask", _outcome(answer))
    assert seen["a mask after the image"] is True and seen["a mask as a page"] is True
    assert not any(seen[k] for k in ("a mask before the image", "a mask a row short", "a reduced mask"))
    assert seen["a mask past the end"] == "terrain.ends_early"
    assert seen["a mask of a signed type"] == "terrain.bad_tag"
    assert seen["a table one over the cap"] == "terrain.too_many_blocks"
    assert seen["a table at the cap"] == "terrain.ends_early"


# ------------------------------------------------------------ the elevation layer

_ELEVATION = r"""
import { readFileSync, openSync, readSync, fstatSync, closeSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createInterface } from 'node:readline';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const Bytes = vm.runInContext('Uint8Array', sandbox);
// the page reads a GeoTIFF's directories as Python's open_geotiff does: the
// first 64 KiB, then each range asked for rounded up to 64 KiB, 16 rounds
const UNIT = 65536, ROUNDS = 16;
const bits = (v) => { const b = Buffer.alloc(8); b.writeDoubleBE(v); return b.toString('hex'); };
const sha = (buffer) => createHash('sha256').update(buffer).digest('hex');
// float64 little-endian, every NaN the one NaN, signs of zero kept
function digest(values) {
  const out = Buffer.alloc(values.length * 8);
  for (let i = 0; i < values.length; i++) {
    if (values[i] !== values[i]) {
      out.writeUInt32LE(0, 8 * i);
      out.writeUInt32LE(0x7FF80000, 8 * i + 4);
    } else {
      out.writeDoubleLE(values[i], 8 * i);
    }
  }
  return sha(out);
}
// codes 0-9 a cell, as digits, or their digest when there are many
const codes = (u8) => (u8.length <= 2000 ? Array.from(u8).join('')
  : sha(Buffer.from(u8.buffer, u8.byteOffset, u8.byteLength)));
const valuesView = (values) => Object.fromEntries(Object.entries(values).map(
  ([k, v]) => [k, typeof v === 'number' ? bits(v) : v]));
// a refusal as {refused: [id, sentence, values]}; an Error the engine throws
// for a bad argument (Python's ValueError) as {error: true}
function guard(f) {
  try {
    return f();
  } catch (e) {
    if (e && e.ident) return { refused: [e.ident, e.message, valuesView(e.values)] };
    if (e && e.constructor && e.constructor.name === 'Error') return { error: true };
    throw e;
  }
}
const FLOATS = new Set(['x0', 'y0', 'sx', 'sy', 'nodata']);
const layoutView = (layout) => Object.fromEntries(Object.entries(layout).map(
  ([k, v]) => [k, FLOATS.has(k) && v !== null ? bits(v) : v]));
function file(path) {
  const fd = openSync(path, 'r'), size = fstatSync(fd).size;
  return {
    size,
    at(offset, length) {
      const buffer = Buffer.alloc(Math.max(0, Math.min(length, size - offset)));
      readSync(fd, buffer, 0, buffer.length, offset);
      const out = new Bytes(buffer.length);
      out.set(buffer);
      return out;
    },
    close() { closeSync(fd); },
  };
}
function open(name, source) {
  // an .hgt is laid out from its name and length, with nothing read
  let found = C.elevationFile(name, source.size, []);
  if (!Array.isArray(found)) return found;
  const chunks = [[0, source.at(0, Math.min(source.size, UNIT))]];
  for (let round = 0; round <= ROUNDS; round++) {
    found = C.elevationFile(name, source.size, chunks);
    if (!Array.isArray(found) || round === ROUNDS) break;
    for (const [offset, length] of found) {
      chunks.push([offset, source.at(offset, Math.min(Math.ceil(length / UNIT) * UNIT, source.size - offset))]);
    }
  }
  if (!Array.isArray(found)) return found;
  const values = { file: name, part: 'image directory' };
  return { refused: ['terrain.ends_early', C.phrase('terrain.ends_early', values), values] };
}
const centreView = (c) => ({ lon: bits(c.lon), lat: bits(c.lat), label: c.label, exact: c.exact, note: c.note });
const fileView = (f) => ({ name: f.name, kind: f.kind, sourceId: f.sourceId, notes: f.notes,
  layout: layoutView(f.layout) });
function planView(plan) {
  return {
    files: plan.files.map((f) => f.name), sources: plan.sources, declared: plan.declared, offsets: plan.offsets,
    x0: bits(plan.x0), y0: bits(plan.y0), sx: bits(plan.sx), sy: bits(plan.sy), centre: centreView(plan.centre),
    ci: plan.ci, cj: plan.cj, stride: plan.stride, hx: plan.hx, hy: plan.hy, hxs: plan.hxs, hys: plan.hys,
    width: plan.width, height: plan.height, cells: plan.cells, shown: plan.shown,
    radiusKm: bits(plan.radiusKm), marginKm: bits(plan.marginKm), dx: bits(plan.dx), dy: bits(plan.dy),
    lons: digest(plan.lons), lats: digest(plan.lats), tile: plan.tile, missing: plan.missing,
    edges: plan.edges.map((e) => [e.missing, e.file, e.row, e.column]),
    blocks: plan.blocks.map((b) => [b.file, b.index, b.offset, b.length, b.rows, b.window, b.edges]),
  };
}
function readView(read) {
  const g = read.grid;
  return {
    grid: { lons: digest(g.lons), lats: digest(g.lats), z: digest(g.z), rows: g.rows, cols: g.cols,
      shown: g.shown, assumedSea: codes(g.assumedSea), sourceId: g.sourceId, seaClean: g.seaClean,
      label: g.label, credit: g.credit, notice: g.notice, surface: g.surface, files: g.files,
      cellNote: g.cellNote },
    assumedSea: codes(read.assumedSea), reasons: codes(read.reasons), shown: read.shown, cells: read.cells,
    voids: read.voids, uncovered: read.uncovered, implausible: read.implausible, assumed: read.assumed,
    coverage: bits(read.coverage), centre: centreView(read.centre), notes: read.notes, prompts: read.prompts,
    surface: read.surface, notice: read.notice, figureCredit: read.figureCredit,
  };
}
const ops = {
  // the page's whole path through one set of files: open each, credit the
  // set, centre, plan, read the planned ranges and read the window
  window(request) {
    const out = { files: [] }, files = [], paths = {};
    for (const { name, path } of request.files) {
      paths[name] = path;
      const source = file(path);
      try {
        const found = guard(() => open(name, source));
        out.files.push(found.refused || found.error ? found : fileView(found));
        if (!found.refused && !found.error) files.push(found);
      } finally {
        source.close();
      }
    }
    if (files.length < request.files.length) return out;
    const declared = request.declared;
    out.credit = guard(() => {
      const c = C.terrainCredit(files, declared);
      return [c.label, c.credit, c.notice, c.surface, c.seaClean];
    });
    out.notes = guard(() => files.map((f) => C.fileNotes(f, declared)));
    const centre = request.centre ? { ...request.centre, note: null }
      : C.windowCentre(request.site, request.latlon, files);
    out.centre = centreView(centre);
    const plan = guard(() => C.planElevationWindow(files, centre, request.radius, request.config,
      request.margin, declared));
    if (plan.refused || plan.error) {
      out.plan = plan;
      return out;
    }
    out.plan = planView(plan);
    const reads = C.elevationBlockRanges(plan), blocks = new Array(plan.blocks.length);
    for (const r of reads) {
      const source = file(paths[r.name]), data = source.at(r.offset, r.length);
      source.close();
      for (const b of r.blocks) {
        const block = plan.blocks[b];
        blocks[b] = data.subarray(block.offset - r.offset, block.offset - r.offset + block.length);
      }
    }
    const progress = [];
    out.read = guard(() => readView(C.readElevationWindow(plan, blocks, request.config,
      (fraction, label) => progress.push([bits(fraction), label]))));
    out.reads = reads.map((r) => [r.name, r.offset, r.length]);
    out.progress = progress;
    return out;
  },
  // the degree sine and cosine of the float64 values in a file, as float64 pairs
  trig({ input }) {
    const raw = readFileSync(input), values = new Float64Array(raw.buffer, raw.byteOffset, raw.length / 8);
    const out = new Float64Array(2 * values.length);
    for (let i = 0; i < values.length; i++) {
      const sc = C.sinCosDeg(values[i]);
      out[2 * i] = sc[0];
      out[2 * i + 1] = sc[1];
    }
    return Buffer.from(out.buffer).toString('base64');
  },
  metric({ lons, lats }) {
    const m = C.rowMetric(lons.map(Number), lats.map(Number));
    return { dx: Array.from(m.dx, bits), dy: Array.from(m.dy, bits), dg: Array.from(m.dg, bits),
             au: Array.from(m.auRow, bits) };
  },
  cell({ cases }) {
    return cases.map(([lat, stepLon, stepLat]) => C.wgs84CellSize(lat, stepLon, stepLat).map(bits));
  },
  // the reads that bring in a plan's blocks, for a plan of [file, offset, length] blocks
  reads({ blocks, names }) {
    const plan = { files: names.map((name) => ({ name })), blocks: blocks.map(([file, offset, length], index) =>
      ({ file, index, offset, length, rows: null, window: true, edges: [] })) };
    return C.elevationBlockRanges(plan).map((r) => [r.name, r.offset, r.length, r.blocks]);
  },
};
for await (const line of createInterface({ input: process.stdin })) {
  const request = JSON.parse(line);
  let answer;
  try {
    answer = { ok: ops[request.op](request) };
  } catch (e) {
    answer = { threw: String(e && e.stack || e) };
  }
  process.stdout.write(JSON.stringify(answer) + '\n');
}
"""


@pytest.fixture
def elevation(tmp_path):
    """The browser's elevation layer in a Node vm, with the map layers its
    area window reads, asked one question at a time."""
    browser = _Reader(tmp_path, _ELEVATION, "elevation.mjs")
    yield browser
    browser.close()


def _hex(value) -> str:
    return struct.pack(">d", float(value)).hex()


def _digest(values) -> str:
    """SHA-256 of float64 little-endian values, every NaN the one NaN, signs of zero kept."""
    import numpy as np

    a = np.array(values, dtype="<f8").ravel()
    a[np.isnan(a)] = np.nan
    return hashlib.sha256(a.tobytes()).hexdigest()


def _codes(values) -> str:
    """Codes 0-9 a cell as digits, or their digest when there are many, as the driver writes them."""
    import numpy as np

    a = np.ascontiguousarray(values, dtype=np.uint8).ravel()
    return "".join(str(int(v)) for v in a) if a.size <= 2000 else hashlib.sha256(a.tobytes()).hexdigest()


def _values_view(values: dict) -> dict:
    return {k: _hex(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
            for k, v in values.items()}


@cache
def _bytes_of(path: str) -> bytes:
    return Path(path).read_bytes()


def _python_window(request: dict, site=None) -> dict:
    """What groundwater.mapping.elevation does with one request, in the shape
    the driver's ``window`` gives the browser's answer: each file opened (as
    open_elevation_file reads it) or refused; the set's label and credit and
    each file's notes under the declaration; the centre; the plan or its
    refusal; the read or its refusal; the ranges read, in order; and every
    progress report. A refusal is its id, its sentence and its words, the
    numbers as their float64 bits."""
    import dataclasses

    from groundwater.config import TerrainConfig
    from groundwater.geotiff import GeoTiffError
    from groundwater.mapping.elevation import (
        WindowCentre,
        elevation_label_and_credit,
        file_notes,
        open_elevation_file,
        plan_window,
        read_window,
        window_centre,
    )

    def guard(work):
        try:
            return work()
        except GeoTiffError as refused:
            return {"refused": [refused.ident, str(refused), _values_view(refused.values)]}
        except ValueError:
            return {"error": True}

    def centre_view(c):
        return {"lon": _hex(c.lon), "lat": _hex(c.lat), "label": c.label, "exact": c.exact, "note": c.note}

    data = {f["name"]: _bytes_of(f["path"]) for f in request["files"]}
    recorded: list = []

    def reader_of(name: str, blob: bytes):
        def read_at(offset: int, length: int) -> bytes:
            recorded.append([name, offset, length])
            return blob[offset:offset + length]
        return read_at

    readers = {name: reader_of(name, blob) for name, blob in data.items()}
    out: dict = {"files": []}
    files = []
    for f in request["files"]:
        name = f["name"]
        found = guard(lambda name=name: open_elevation_file(name, len(data[name]), readers[name]))
        if isinstance(found, dict):
            out["files"].append(found)
            continue
        files.append(found)
        out["files"].append({"name": found.name, "kind": found.kind, "sourceId": found.source_id,
                             "notes": list(found.notes), "layout": _agreed_layout(found.layout)})
    if len(files) < len(request["files"]):
        return json.loads(json.dumps(out))
    declared = tuple(request["declared"])
    out["credit"] = guard(lambda: list(elevation_label_and_credit(files, declared)))
    out["notes"] = guard(lambda: [list(file_notes(f, declared)) for f in files])
    if request["centre"]:
        c = request["centre"]
        centre = WindowCentre(c["lon"], c["lat"], c["label"], c["exact"])
    else:
        centre = window_centre(site, files)
    out["centre"] = centre_view(centre)
    caps = {key: value for key, value in ((request["config"] or {}).get("terrain") or {}).items()
            if value is not None}
    cfg = dataclasses.replace(TerrainConfig(), **caps)
    plan = guard(lambda: plan_window(files, centre, request["radius"], cfg, 1, request["margin"], declared))
    if isinstance(plan, dict):
        out["plan"] = plan
        return json.loads(json.dumps(out))
    out["plan"] = {
        "files": [f.name for f in plan.files], "sources": list(plan.sources), "declared": list(plan.declared),
        "offsets": [list(o) for o in plan.offsets], "x0": _hex(plan.x0), "y0": _hex(plan.y0),
        "sx": _hex(plan.sx), "sy": _hex(plan.sy), "centre": centre_view(plan.centre), "ci": plan.ci,
        "cj": plan.cj, "stride": plan.stride, "hx": plan.hx, "hy": plan.hy, "hxs": plan.hxs, "hys": plan.hys,
        "width": plan.width, "height": plan.height, "cells": plan.cells, "shown": list(plan.shown),
        "radiusKm": _hex(plan.radius_km), "marginKm": _hex(plan.margin_km), "dx": _hex(plan.dx),
        "dy": _hex(plan.dy), "lons": _digest(plan.lons), "lats": _digest(plan.lats), "tile": plan.tile,
        "missing": [list(t) for t in plan.missing],
        "edges": [[e.missing, e.file, e.row, e.column] for e in plan.edges],
        "blocks": [[b.file, b.index, b.offset, b.length, list(b.rows) if b.rows else None, b.window,
                    list(b.edges)] for b in plan.blocks],
    }
    recorded.clear()
    progress: list = []

    def read():
        got = read_window(plan, readers, cfg, lambda fraction, label: progress.append([_hex(fraction), label]))
        grid = got.grid
        return {
            "grid": {"lons": _digest(grid.lons), "lats": _digest(grid.lats), "z": _digest(grid.z),
                     "rows": grid.z.shape[0], "cols": grid.z.shape[1], "shown": list(got.shown),
                     "assumedSea": _codes(got.assumed_sea), "sourceId": grid.source_id,
                     "seaClean": grid.sea_clean, "label": grid.source, "credit": grid.credit,
                     "notice": got.notice, "surface": got.surface, "files": list(grid.files),
                     "cellNote": grid.resolution_note},
            "assumedSea": _codes(got.assumed_sea), "reasons": _codes(got.reasons), "shown": list(got.shown),
            "cells": got.cells, "voids": got.voids, "uncovered": got.uncovered,
            "implausible": got.implausible, "assumed": got.assumed, "coverage": _hex(got.coverage),
            "centre": centre_view(got.centre), "notes": list(got.notes), "prompts": list(got.prompts),
            "surface": got.surface, "notice": got.notice, "figureCredit": got.figure_credit,
        }

    out["read"] = guard(read)
    out["reads"] = list(recorded)
    out["progress"] = progress
    return json.loads(json.dumps(out))


def _window(files, radius, margin=0.0, centre=None, cap=None, declared=("detect", ""), site=None, latlon=None,
            blocks=None):
    """One request of the driver's ``window``: files as (name, path), the
    radius and margin in km (a margin of None is the configured one), a
    GPS-like centre or none (then the site's, or the files' middle), an
    explicit cap on cells and on blocks, and the operator's declaration."""
    terrain = {key: value for key, value in (("max_cells", cap), ("max_blocks", blocks)) if value is not None}
    return {"files": [{"name": name, "path": str(path)} for name, path in files], "centre": centre,
            "site": site, "latlon": latlon, "radius": radius, "margin": margin,
            "config": {"terrain": terrain} if terrain else None, "declared": list(declared)}


def _point(lon: float, lat: float, label: str = "the test point") -> dict:
    return {"lon": lon, "lat": lat, "label": label, "exact": True}


def _hgt_tile(side: int, lon0: int, lat0: int, sea=None, rows=None):
    """An .hgt tile's heights, north row first, from integer arithmetic on
    each cell's place in the world, so that neighbouring tiles agree where
    they overlap (tests/test_elevation.py builds them so too); ``rows``
    limits the heights to a band of rows, the rest 0, for a tile too large
    to fill."""
    import numpy as np

    step = side - 1
    band = range(side) if rows is None else rows
    gj = ((90 - lat0 - 1) * step + np.arange(band.start, band.stop, dtype=np.int64))[:, None]
    gi = ((lon0 + 180) * step + np.arange(side, dtype=np.int64))[None, :]
    heights = (17 * gi + 29 * gj) % 400 + 10
    if sea is not None:
        heights = np.where(sea(gi, gj), 0, heights)
    z = np.zeros((side, side), dtype=np.int64)
    z[band.start:band.stop] = heights
    return z


def _elevation_cases(tmp_path: Path):
    """Every request the two elevation layers are compared on, as (request,
    the Python site or None, what it is): every set in the fixture
    manifest at several centres, radii, margins and declarations; every
    fixture alone; .hgt tiles made here (a pair across 9 N, a pair across
    12 W, a set with tiles missing beside sea and beside land, a 1
    arc-second tile, names at 0 degrees and in the south and east, names
    that refuse); windows at and one cell over an explicit cap; windows
    centred on a chiefdom, a district and a GPS fix; and each refusal the
    elevation layer has."""
    import numpy as np

    from groundwater.geo import geographic_to_utm
    from groundwater.mapping.elevation import WindowCentre, open_elevation_file, plan_window
    from groundwater.mapping.regional import area_window
    from groundwater.models import SiteMetadata

    make = _builder()
    arcsec = 1 / 3600
    made_count = [0]

    def made(name: str, data: bytes):
        made_count[0] += 1
        path = tmp_path / f"made{made_count[0]}.bin"
        path.write_bytes(data)
        return name, path

    def tif(rows, georef, kind="f32", **options) -> bytes:
        return make.single("made.tif", "", rows, kind, georef, **options).data

    def hgt(z) -> bytes:
        return np.asarray(z, dtype=">i2").tobytes()

    def opened(files):
        return [open_elevation_file(name, len(_bytes_of(str(path))),
                                    lambda o, n, path=path: _bytes_of(str(path))[o:o + n]) for name, path in files]

    # every set in the manifest
    specific = {
        "copernicus_pair": [(-11.0, 9.0 - 20 * arcsec, 0.5, 0.0)],
        "renamed": [(-11.0, 8.995, 0.3, 0.0)],
        "overlap_agree": [(-12.5 + 12 * arcsec, 8.75 - 19 * arcsec, 0.45, 0.0)],
        "overlap_disagree": [(-12.5 + 12 * arcsec, 8.75 - 19 * arcsec, 0.45, 0.0)],
        "overlap_fill_edge": [(-12.5 + 12 * arcsec, 8.75 - 19 * arcsec, 0.45, 0.0)],
        "products": [(-11.0, 8.995, 0.3, 0.0)],
        "phase": [(-12.495, 8.745, 0.2, 0.0)],
        "spacing": [(-12.495, 8.745, 0.2, 0.0)],
        "holes_sea": [(-12.0, 8.0, 30.0, 0.0), (-12.0, 8.0, 15.0, 10.0)],
        "holes_land": [(-12.0, 8.0, 30.0, 0.0)],
        "holes_edge": [(-12.0, 8.0, 15.0, 0.0)],
        "hole_fill_margin": [(-12.02, 8.5, 8.0, 0.0)],
    }
    for set_name, entry in _MANIFEST["sets"].items():
        rename = entry.get("rename", {})
        files = [(rename.get(name, name), DEM / name) for name in entry["files"]]
        base = (entry.get("declare", "detect"), "")
        found = opened(files)
        sx = found[0].layout.sx
        km = sx * 111.0
        west = min(f.layout.x0 for f in found)
        east = max(f.layout.x0 + (f.layout.width - 1) * f.layout.sx for f in found)
        south = min(f.layout.y0 - (f.layout.height - 1) * f.layout.sy for f in found)
        north = max(f.layout.y0 for f in found)
        centres = [_point((west + east) / 2, (south + north) / 2), _point(west + 2.5 * sx, north - 1.5 * sx),
                   _point(east - 0.3 * sx, south + 0.7 * sx), _point(east + 10 * sx, (south + north) / 2, "Bo")]
        for centre in centres:
            for cells, margin in ((1.2, 0.0), (3.5, 2.0), (9.0, 0.0)):
                yield _window(files, cells * km, margin * km, centre, declared=base), None, f"{set_name} {centre}"
        yield _window(files, 4 * km, None, None, declared=base), None, f"{set_name} with no site"
        for lon, lat, radius, margin in specific.get(set_name, []):
            yield _window(files, radius, margin, _point(lon, lat), declared=base), None, f"{set_name} at {lon}, {lat}"
            for declared in (("copernicus_glo30", ""), ("srtm", ""), ("other", "  a mosaic\x85"),
                             ("other", " \t"), ("other", "\ufeffQGIS")):
                yield (_window(files, radius, margin, _point(lon, lat), declared=declared), None,
                       f"{set_name} declared {declared}")

    # every fixture alone, centred on its middle and near its corner
    for name in sorted(_FILES):
        sx = _FILES[name].get("sx") or 1 / 1200
        km = sx * 111.0
        yield _window([(name, DEM / name)], 2.5 * km), None, f"{name} alone"
        x0, y0 = _FILES[name].get("x0"), _FILES[name].get("y0")
        if x0 is not None and y0 is not None:
            yield (_window([(name, DEM / name)], 1.2 * km, 1.0 * km, _point(x0 + sx, y0 - sx)), None,
                   f"{name} near its corner")

    # .hgt tiles, made here: a real one is 2.9 MB
    voided = _hgt_tile(1201, -13, 8)
    voided[600, 595:600] = -32768
    voided[610, 598:601] = 9500
    voided[590, 601] = -1500
    n08w013 = made("N08W013.hgt", hgt(voided))
    n09w013 = made("N09W013.hgt", hgt(_hgt_tile(1201, -13, 9)))
    n08w012 = made("N08W012.hgt", hgt(_hgt_tile(1201, -12, 8)))
    n07w012 = made("N07W012.hgt", hgt(_hgt_tile(1201, -12, 7)))
    corner_i, corner_j = (180 - 12) * 1200, (90 - 8) * 1200

    def sea(gi, gj):
        return (gi <= corner_i + 30) & (gj >= corner_j - 30)

    sea_north = _hgt_tile(1201, -13, 8, sea)
    sea_set = [made("N08W013.hgt", hgt(sea_north)), made("N07W012.hgt", hgt(_hgt_tile(1201, -12, 7, sea)))]
    sea_north[-1, 10] = 1
    land_set = [made("N08W013.hgt", hgt(sea_north)), sea_set[1]]
    yield _window([n08w013], 2.0, 0.0, _point(-12.5, 8.5)), None, "an .hgt with voids"
    yield _window([n08w013], 0.5, 0.3, _point(-12.5, 8.5)), None, "an .hgt with a margin"
    yield _window([n08w013], 1.0, 0.0), None, "an .hgt with no site"
    yield _window([n08w013], 0.2, None, _point(-12.9, 8.9)), None, "an .hgt with the configured margin"
    yield _window([n09w013, n08w013], 0.2, 0.0, _point(-12.5, 9.0)), None, "an .hgt pair across 9 N"
    yield _window([n08w013, n09w013], 1.0, 0.3, _point(-12.5, 9.0 + 0.5 / 1200)), None, "across 9 N, a margin"
    yield _window([n08w013, n08w012], 0.5, 0.0, _point(-12.0, 8.5)), None, "an .hgt pair across 12 W"
    yield (_window([n08w013, n08w012, n07w012], 3.0, 1.0, _point(-12.01, 7.99)), None,
           "an .hgt set missing a land tile")
    for declared in (("detect", ""), ("srtm", ""), ("other", "a mosaic")):
        yield (_window(sea_set, 5.0, 0.0, _point(-12.02, 8.02), declared=declared), None,
               f"an .hgt set missing tiles beside sea, declared {declared}")
    yield _window(sea_set, 2.0, 1.0, _point(-12.02, 8.02)), None, "beside sea, a margin"
    yield _window(land_set, 5.0, 0.0, _point(-12.02, 8.02)), None, "an .hgt set missing tiles beside land"
    yield _window([("N00W000.hgt", n08w013[1])], 0.3, 0.0, _point(0.5, 0.5)), None, "an .hgt at 0 degrees"
    yield _window([("N00W000.hgt", n08w013[1])], 0.5, 0.0, _point(0.0, 0.0)), None, "the corner at 0, 0"
    yield _window([("N00W000.hgt", n08w013[1])], 0.4), None, "at 0 degrees, no site"
    yield _window([("s01e010.hgt", n08w013[1])], 0.3, 0.0, _point(10.5, -0.5)), None, "an .hgt south and east"
    fine = made("n08w012.hgt", hgt(_hgt_tile(3601, -12, 8, rows=range(1750, 1851))))
    yield _window([fine], 0.3, 0.1, _point(-11.5, 8.5)), None, "a 1 arc-second .hgt"
    yield _window([("tile.hgt", n08w013[1])], 0.3, 0.0, _point(-12.5, 8.5)), None, "an .hgt named for no corner"
    odd = made("N08W013.hgt", bytes(2 * 1000 * 1000 + 1))
    yield _window([odd], 0.3, 0.0, _point(-12.5, 8.5)), None, "an .hgt of neither size"
    yield _window([("N89W000.hgt", n08w013[1])], 0.3, 0.0, _point(0.5, 89.5)), None, "an .hgt at a pole"
    yield (_window([n08w013, ("n08w011.tif", DEM / "n08w011.tif")], 0.3, 0.0, _point(-12.5, 8.5)), None,
           "an .hgt beside a GeoTIFF")
    yield _window([n08w013, n08w013], 0.3, 0.0, _point(-12.5, 8.5)), None, "one .hgt twice"
    # two tiles at one corner: the first in UTF-16 code units (the
    # supplementary-plane name, which code points put second) is the one kept
    bumped = _hgt_tile(1201, -13, 8)
    bumped[600, 600] += 1
    plain = made("plain.hgt", hgt(_hgt_tile(1201, -13, 8)))[1]
    emoji, fullwidth = "N08W013\U0001F600.hgt", "N08W013\uff21.hgt"
    for other, what in ((n08w013[1], "one with voids"), (made("bumped.hgt", hgt(bumped))[1], "one a metre out")):
        yield (_window([(fullwidth, other), (emoji, plain)], 0.3, 0.0, _point(-12.5, 8.5)), None,
               f"two tiles at one corner, {what}")
    # by code unit "B" comes before "a", where a locale's order has it after
    yield (_window([("N08W013a.hgt", plain), ("N08W013B.hgt", made("bumped.hgt", hgt(bumped))[1])], 0.3, 0.0,
                   _point(-12.5, 8.5)), None, "two tiles at one corner named in either case")
    # three tiles at one corner: the refusal names the first cell that
    # clashes, in the first block that has one, and the file already
    # holding it, which need not be the first file
    other = _hgt_tile(1201, -13, 8)
    other[602, 598] += 2
    holed = _hgt_tile(1201, -13, 8)
    holed[600, 600] = -32768
    others = made("other.hgt", hgt(other))[1]
    for first, what in ((plain, "the first file holding the cell"), (made("holed.hgt", hgt(holed))[1],
                                                                     "the second file holding the cell")):
        yield (_window([("N08W013a.hgt", first), ("N08W013b.hgt", plain if first != plain else others),
                        ("N08W013c.hgt", made("bumped.hgt", hgt(bumped))[1])], 0.3, 0.0, _point(-12.5, 8.5)),
               None, f"three tiles at one corner, {what}")
    yield (_window([("N08W013a.hgt", plain), ("N08W013b.hgt", made("bumped.hgt", hgt(bumped))[1]),
                    ("N08W013c.hgt", others)], 0.3, 0.0, _point(-12.5, 8.5)), None,
           "three tiles at one corner, clashing in two blocks")

    # one Copernicus tile beside one of unstated source; the same tiles under
    # EarthExplorer SRTM names; an SRTM name at 3 arc-seconds
    yield (_window([(COPERNICUS_W012, DEM / COPERNICUS_W012), ("n08w011.tif", DEM / "n08w011.tif")], 0.3, 0.0,
                   _point(-11.0, 8.995)), None, "a Copernicus tile beside one of unstated source")
    yield (_window([("n08_w012_1arc_v3.tif", DEM / COPERNICUS_W012), ("N08_W011_1ARC_V3.TIF", DEM / COPERNICUS_W011)],
                   0.3, 0.0, _point(-11.0, 8.995)), None, "tiles under SRTM names")
    srtm3 = tif(make.metres(make.patch(6, 5, 7)), make.Georef(-11.9, 7.9, 1 / 1200, 1 / 1200, raster=2))
    yield (_window([made("n07_w012_3arc_v2.tif", srtm3)], 0.1, 0.0, _point(-11.9 + 2 / 1200, 7.9 - 2 / 1200)),
           None, "an SRTM name at 3 arc-seconds")
    yield (_window([made("n07_w011_3arc_v2.tif", srtm3)], 0.1, 0.0, _point(-11.9 + 2 / 1200, 7.9 - 2 / 1200)),
           None, "an SRTM name for another square")

    # a middle that is a tie at five decimals in binary, which Python's
    # "%.5f" rounds to even and toFixed rounds up
    tie = tif(make.metres(make.patch(3, 3, 9)), make.Georef(10.0, 0.03125, 0.015625, 0.015625, raster=2))
    yield _window([made("tie.tif", tie)], 2.0), None, "a middle on a binary tie"

    # the cap: over it, at the radius it says fits, exactly at it and one cell over
    pair = [(COPERNICUS_W012, DEM / COPERNICUS_W012), (COPERNICUS_W011, DEM / COPERNICUS_W011)]
    at = _point(-11.0, 8.995)
    yield _window(pair, 1.1, 0.5, at, cap=10_000), None, "over the cap"
    yield _window(pair, 0.9, 0.5, at, cap=10_000), None, "at the radius that fits"
    yield _window(pair, 0.5, 2.0, at, cap=10_000), None, "a margin wider than any window under the cap"
    plan = plan_window(opened(pair), WindowCentre(at["lon"], at["lat"], at["label"], True), 0.4, margin_km=0.1)
    yield _window(pair, 0.4, 0.1, at, cap=plan.cells), None, "a window of exactly the cap"
    yield _window(pair, 0.4, 0.1, at, cap=plan.cells - 1), None, "a window one cell over the cap"
    yield _window(pair, 0.0, 0.0, at), None, "a window of one cell"
    yield _window(pair, 0.3, 0.0, at, declared=("nonsense", "")), None, "a declaration of no kind"

    # centred on a chiefdom, a district, a GPS fix and a site with no location
    def around(lon: float, lat: float, step: float = 1 / 120, side: int = 61) -> bytes:
        x0 = math.floor(lon / step) * step - (side // 2) * step
        y0 = math.floor(lat / step) * step + (side // 2) * step
        return tif(make.metres(make.patch(side, side, 5)), make.Georef(x0, y0, step, step, raster=2))

    utm = geographic_to_utm(8.42, -12.95)
    sites = [
        (SiteMetadata(community="T", chiefdom="Koya", district="Port Loko"),
         {"community": "T", "chiefdom": "Koya", "district": "Port Loko"}, None),
        (SiteMetadata(community="T", district="Bo"), {"community": "T", "chiefdom": "", "district": "Bo"}, None),
        (SiteMetadata(community="T", district="Western Area"),
         {"community": "T", "chiefdom": "", "district": "Western Area"}, None),
        (SiteMetadata(community="Rogbere", easting=utm.easting, northing=utm.northing, utm_zone=utm.zone),
         {"community": "Rogbere", "chiefdom": "", "district": ""}, "latlon"),
    ]
    for site, js_site, fix in sites:
        area = area_window(site)
        assert area is not None
        model = made("site.tif", around(area.lon, area.lat))
        latlon = None
        if fix:
            lat, lon = site.latlon
            latlon = {"lat": lat, "lon": lon}
        yield _window([model], 2.0, 0.0, site=js_site, latlon=latlon), site, f"centred on {area.label}"
        yield _window([model], 1.0, 0.5, site=js_site, latlon=latlon), site, f"centred on {area.label}, a margin"
    nowhere = SiteMetadata(community="T")
    yield (_window([n08w013], 0.4, 0.0, site={"community": "T", "chiefdom": "", "district": ""}), nowhere,
           "a site with no location")

    # the coordinate systems refused, and what each is called
    rows = make.metres(make.patch(6, 5, 3))

    def keyed(keys, georef=None) -> bytes:
        directory = [1, 1, 0, len(keys)] + [v for key in sorted(keys) for v in key]
        return tif(rows, georef or make.Georef(-11.5, 8.5, arcsec, arcsec, raster=2),
                   tags={make.GEO_KEY_DIRECTORY: (3, directory)})

    point = _point(-11.5 + 2 * arcsec, 8.5 - 2 * arcsec)
    for label, data in (
        ("NAD83", tif(rows, make.Georef(-11.5, 8.5, arcsec, arcsec, raster=2, epsg=4269))),
        ("UTM 29N", tif(rows, make.Georef(200000.0, 900000.0, 30.0, 30.0, raster=1, model=1, epsg=32629))),
        ("UTM 28S", tif(rows, make.Georef(200000.0, 900000.0, 30.0, 30.0, raster=1, model=1, epsg=32728))),
        ("SL 1968 29N", tif(rows, make.Georef(200000.0, 900000.0, 30.0, 30.0, raster=1, model=1, epsg=2162))),
        ("user projected", tif(rows, make.Georef(200000.0, 900000.0, 30.0, 30.0, raster=1, model=1,
                                                 epsg=32767))),
        ("geocentric", keyed([(1024, 0, 1, 3)])),
        ("WGS 84 datum", keyed([(1024, 0, 1, 2), (1025, 0, 1, 2), (2048, 0, 1, 32767), (2050, 0, 1, 6326)])),
        ("another datum", keyed([(1024, 0, 1, 2), (1025, 0, 1, 2), (2048, 0, 1, 32767), (2050, 0, 1, 6267)])),
        ("no datum", keyed([(1024, 0, 1, 2), (1025, 0, 1, 2)])),
        ("grads", keyed([(1024, 0, 1, 2), (1025, 0, 1, 2), (2048, 0, 1, 4326), (2054, 0, 1, 9105)])),
        ("degrees", keyed([(1024, 0, 1, 2), (1025, 0, 1, 2), (2048, 0, 1, 4326), (2054, 0, 1, 9102)])),
        ("at 89 N", tif(rows, make.Georef(20.0, 89.0, 0.01, 0.01, raster=2))),
        ("at 88.99 N", tif(rows, make.Georef(20.0, 88.99, 0.01, 0.01, raster=2))),
        ("void", tif([[-32767.0] * 6] * 5, make.Georef(-11.5, 8.5, arcsec, arcsec, raster=2))),
    ):
        yield _window([made(f"{label}.tif", data)], 0.05, 0.0, point), None, label
    yield _window([("n08w011.tif", DEM / "n08w011.tif")], 0.3, 0.0, _point(-10.0, 8.0, "Bo")), None, "outside"
    yield _window([made("Copernicus_DSM_COG_10_N07_00_W012_00_DEM.tif", _bytes_of(str(DEM / COPERNICUS_W012)))],
                  0.2, 0.0, _point(-11.005, 8.995)), None, "a Copernicus name in the wrong square"
    yield _window([made("N08W011_FABDEM_V1-2.tif", _bytes_of(str(DEM / "n08w011.tif")))], 0.2, 0.0,
                  _point(-10.995, 8.995), declared=("copernicus_glo30", "")), None, "a FABDEM name, declared"

    # what the 4.1a review found, each through both engines. Damaged
    # georeferencing is refused as the file is opened - alone, with a site
    # centre or none, and beside a good tile - the GLO-30 fingerprint's
    # layout among them, whose degree test once raised in Python alone
    good = (COPERNICUS_W012, DEM / COPERNICUS_W012)
    square = make.metres(make.patch(12, 12, 7))
    for label, georef in (
        ("a NaN tiepoint", make.Georef(math.nan, 8.0, arcsec, arcsec, raster=2, copernicus_keys=True)),
        ("an infinite tiepoint", make.Georef(math.inf, 8.0, arcsec, arcsec, raster=2, copernicus_keys=True)),
        ("a tiepoint at minus infinity", make.Georef(-math.inf, 8.0, arcsec, arcsec, raster=2,
                                                     copernicus_keys=True)),
        ("a plain NaN tiepoint", make.Georef(math.nan, 7.99, 0.001, 0.001)),
        ("a tiepoint at 1.7e308", make.Georef(1.7e308, 8.0, 0.001, 0.001, raster=1)),
        ("a tiepoint at -1.7e308", make.Georef(-1.7e308, 8.0, 0.001, 0.001, raster=1)),
        ("a subnormal cell width", make.Georef(-12.0, 8.0, 1e-320, 0.001)),
        ("a cell just under 1e-7 degree", make.Georef(-12.0, 8.0, 0.001, 9.9e-8)),
        ("a cell of two degrees", make.Georef(-12.0, 8.0, 2.0, 0.5)),
        ("longitudes past 540", make.Georef(535.0, 8.0, 1.0, 0.5)),
        ("a NaN translation", make.Georef(math.nan, 8.0, arcsec, arcsec, transform=True)),
        ("an infinite cell height", make.Georef(-12.0, 8.0, 0.001, math.inf)),
        ("a cell of one degree", make.Georef(-12.0, 20.0, 1.0, 1.0)),
    ):
        damaged = made(f"{label}.tif", tif(square, georef))
        yield _window([damaged], 0.3, 0.0), None, label
        yield _window([damaged], 0.3, 0.0, _point(-11.995, 7.995)), None, f"{label}, a site centre"
        yield _window([good, damaged], 0.3, 0.0, _point(-11.0, 8.995)), None, f"{label}, beside a good tile"
    flat = bytearray(_bytes_of(str(DEM / "holes_sea_N07W012.tif")))
    flat[293] = 0x1F  # the high byte of ModelPixelScale's Y: a cell 1.9e-156 degree tall
    yield _window([made("holes_sea_N07W012.tif", bytes(flat))], 5.0, 0.0), None, "a corrupted pixel scale"
    yield (_window([("internal_mask.tif", DEM / "internal_mask.tif"), good], 0.2, 0.0, _point(-11.0, 8.995)),
           None, "a masked file beside a good tile")

    # a centre in a gap between tiles, one outside them all, and one far off
    # at a latitude where the cap would have been asked about first
    corner = made("N08W011.hgt", hgt(_hgt_tile(1201, -11, 8)))
    yield _window([n08w012, corner, n07w012], 5.0, 0.0, _point(-10.95, 7.97)), None, "a centre in a gap"
    yield _window([n08w012, corner, n07w012], 5.0, 0.0, _point(-9.5, 8.5)), None, "a centre east of the tiles"
    yield _window([n08w012], 10.0, None, _point(-11.5, 79.7)), None, "a centre at 79.7 N"

    # a margin alone over the cap on cells, at any radius
    yield _window(pair, 10.0, 5.0, at, cap=10_000), None, "a margin alone over the cap"
    yield _window(pair, 0.0, 5.0, at, cap=10_000), None, "a margin alone over the cap, at a radius of 0"

    # the cap on blocks: a file cut into 2 by 2 tiles at it and one over, the
    # file with the most blocks named, and an .hgt set whose edge columns
    # are a strip a row
    tiny = made("tiny.tif", tif(make.metres(make.patch(40, 40, 8)), make.Georef(-11.5, 8.5, arcsec, arcsec),
                                tile=(2, 2)))
    middle = _point(-11.5 + 20 * arcsec, 8.5 - 20 * arcsec)
    planned = len(plan_window(opened([tiny]), WindowCentre(middle["lon"], middle["lat"], "p", True), 0.3,
                              margin_km=0.0).blocks)
    yield _window([tiny], 0.3, 0.0, middle, blocks=planned), None, "tiny tiles at the cap on blocks"
    yield _window([tiny], 0.3, 0.0, middle, blocks=planned - 1), None, "tiny tiles over the cap on blocks"
    yield _window(pair, 0.5, 0.0, _point(-11.0, 9.0 - 20 * arcsec), blocks=3), None, "a pair over the cap"
    yield _window(sea_set, 5.0, 0.0, _point(-12.02, 8.02), blocks=1000), None, "edge columns over the cap"

    # the read report: the files read, the shown square counted, a gap and
    # a sea under half a percent, and a sea tile named only where it is sea
    yield (_window(pair, 0.1, 0.0, _point(-11.011111111111111 + 34 * arcsec, 8.995)), None,
           "a window inside one tile of a pair")
    yield _window([n08w012], 15.0, 0.0, _point(-11.5, 9 - 162 / 1200)), None, "a gap under half a percent"
    yield _window([n08w012], 15.0, 0.0, _point(-11.5, 9 - 161 / 1200)), None, "a gap over half a percent"
    corner_sea = sea_set + [made("N08W012.hgt", hgt(_hgt_tile(1201, -12, 8, sea)))]
    yield (_window(corner_sea, 5.0, 0.0, _point(-12 + 50 / 1200, 8 + 50 / 1200)), None,
           "a sea under half a percent")
    seam = _hgt_tile(1201, -12, 8)
    seam[-1, :] = 0
    seam[:, -1] = 0
    yield (_window([made("N08W012.hgt", hgt(seam))], 1.0, 0.0, _point(-12 + 1189 / 1200, 9 - 1195 / 1200)),
           None, "a window reaching an .hgt's shared column")


def _hold_area_centre(py: dict, js: dict, where: str) -> None:
    """A chiefdom's or district's label point to 1e-9 degrees, then taken
    as Python's for the exact comparison of the rest.

    area_window sums a ring's shoelace terms with numpy's pairwise sum and
    the browser sums them in order, so the two label points differ by some
    tens of units in the last place; the regional parity holds them to
    1e-9. The window is planned on whole cells from the centre, so the plan
    and the read are still compared exactly."""
    for answer_py, answer_js in ((py, js), (py.get("plan"), js.get("plan")), (py.get("read"), js.get("read"))):
        if not answer_py or "centre" not in answer_py:
            continue
        for key in ("lon", "lat"):
            a, b = (struct.unpack(">d", bytes.fromhex(answer["centre"][key]))[0] for answer in (answer_py, answer_js))
            assert abs(a - b) <= 1e-9, f"{where}: the centre's {key}: python {a!r}, browser {b!r}"
            answer_js["centre"][key] = answer_py["centre"][key]


def _window_outcome(answer: dict) -> str:
    """'read', or the first refusal (or error) the request met."""
    for part in answer["files"] + [answer.get("plan") or {}, answer.get("read") or {}]:
        if "refused" in part:
            return part["refused"][0]
        if "error" in part:
            return "error"
    return "read"


COPERNICUS_W012 = "Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif"
COPERNICUS_W011 = "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif"


def test_the_two_elevation_layers_agree_on_every_fixture_set_and_window(elevation, tmp_path):
    """Both elevation layers, Python's and the browser's, on several hundred
    requests (_elevation_cases), each run as the page runs it: the files
    opened, the set credited, the window centred, planned, its ranges read
    and the window read. Compared whole and exactly: each file's layout,
    source and notes or refusal; the label, credit, notice, surface note and
    sea rule of the set and each file's prompts under the declaration; the
    centre to the bit; the plan (order, offsets, half sizes, cap, shown
    square, axes by digest, missing tiles, edges, and every block with its
    bytes, edge blocks included); the reads made, in order; the grid by a
    digest that keeps signs of zero, the reasons and the assumed-sea mask
    cell by cell, the counts, coverage, notes, prompts and credit line; the
    progress reports; and every refusal's id, sentence and words. Prevents
    the two engines planning or reading a different window from the same
    files, or wording any of it differently; a failure names the request
    and the first answer that differs."""
    outcomes: dict[str, int] = {}
    assumed = missing_land = prompts = 0
    for request, site, where in _elevation_cases(tmp_path):
        py = _python_window(request, site)
        js = elevation.ask("window", **request)
        assert "ok" in js, f"{where}: {js}"
        if site is not None and py.get("centre") and not py["centre"]["exact"]:
            _hold_area_centre(py, js["ok"], where)
        found = _difference(py, js["ok"])
        assert found is None, f"{where}: {found}"
        outcome = _window_outcome(py)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        read = py.get("read") or {}
        assumed += bool(read.get("assumed"))
        missing_land += bool(py.get("plan", {}).get("missing")) and not read.get("assumed")
        prompts += bool(read.get("prompts"))
    refusals = {"terrain.projected", "terrain.no_crs", "terrain.not_wgs84", "terrain.polar", "terrain.hgt_name",
                "terrain.hgt_size", "terrain.duplicate_name", "terrain.mixed_formats", "terrain.join_spacing",
                "terrain.join_phase", "terrain.join_products", "terrain.join_disagree", "terrain.site_outside",
                "terrain.too_many_cells", "terrain.too_small", "terrain.no_elevations", "terrain.internal_mask",
                "terrain.bad_georeference", "terrain.site_gap", "terrain.margin_too_many_cells",
                "terrain.too_many_blocks"}
    assert refusals <= set(outcomes) and "error" in outcomes, sorted(refusals - set(outcomes))
    assert outcomes["read"] >= 200 and assumed >= 3 and missing_land >= 3 and prompts >= 3, (
        outcomes, assumed, missing_land, prompts)


def test_the_browser_degree_sine_cosine_and_row_metric_are_pythons_to_the_bit(elevation, tmp_path):
    """C.sinCosDeg against elevation.sin_cos_deg on 120,000 inputs, among
    them every 15 degrees from -720 to 720, every row centre from 11 N to
    7 N at 1 arc-second as a window's axis computes them, quarter degrees,
    random angles near and far, and the edge cases (signed zeros, the
    smallest and largest doubles, infinities, NaN); then C.wgs84CellSize and
    C.rowMetric against their Python twins. Every row's cell size, and so
    every slope, area and cap, comes from these; a last bit apart in one
    engine moves a window's half size or a drainage area across a
    threshold in one engine only."""
    import numpy as np

    from groundwater.mapping.elevation import row_metric, sin_cos_deg, wgs84_cell_size

    rng = random.Random(4101)
    arcsec = 1.0 / 3600.0
    inputs = [15.0 * k for k in range(-48, 49)]
    inputs += [11.0 - j * arcsec for j in range(4 * 3600 + 1)]
    inputs += [0.25 * k for k in range(-2880, 2881)]
    inputs += [rng.uniform(-720.0, 720.0) for _ in range(50_000)]
    inputs += [rng.uniform(7.0, 11.0) for _ in range(30_000)]
    inputs += [rng.uniform(-1e6, 1e6) for _ in range(10_000)]
    inputs += [90.0 * rng.randint(-40, 40) + rng.choice([-1, 1]) * rng.random() * 1e-9 for _ in range(5_000)]
    inputs += [0.0, -0.0, 5e-324, -5e-324, 1e-300, 1e-7, -1e-7, 45.0, 89.99999999999999, 90.00000000000001,
               1e300, -1e300, 1.7976931348623157e308, -1.7976931348623157e308, math.inf, -math.inf, math.nan]
    assert len(inputs) >= 100_000
    path = tmp_path / "angles.f64"
    path.write_bytes(np.array(inputs, dtype="<f8").tobytes())
    js = elevation.ask("trig", input=str(path))
    assert "ok" in js, js
    browser = np.frombuffer(base64.b64decode(js["ok"]), dtype="<f8").reshape(-1, 2)
    python = np.array([sin_cos_deg(d) for d in inputs], dtype="<f8")
    differ = np.flatnonzero((browser.view(np.uint64) != python.view(np.uint64)).any(axis=1))
    assert differ.size == 0, [(inputs[k], tuple(python[k]), tuple(browser[k])) for k in differ[:10]]

    cases = [[lat, step_lon, step_lat] for lat in (-30.0, 0.0, 7.0, 8.5, 9.75, 12.0, 60.0, 88.9)
             for step_lon, step_lat in ((arcsec, arcsec), (1 / 1200, 1 / 1200), (1 / 40, 1 / 30))]
    cases += [[rng.uniform(-88.0, 88.0), rng.uniform(1e-5, 0.1), rng.uniform(1e-5, 0.1)] for _ in range(300)]
    js = elevation.ask("cell", cases=cases)
    assert "ok" in js, js
    assert js["ok"] == [[_hex(v) for v in wgs84_cell_size(*case)] for case in cases]

    def axis(start, step, n, ascending=True):
        return [start + k * step if ascending else start - (n - 1 - k) * step for k in range(n)]

    for lons, lats in (
        (axis(-11.5, arcsec, 5), axis(8.0, arcsec, 3600)),
        (axis(-13.0, 1 / 1200, 1201), axis(9.0, 1 / 1200, 1201, ascending=False)),
        (axis(-12.0, 1 / 40, 23), axis(7.725, 1 / 40, 23)),
        ([20.0, 20.01], [60.0, 60.01]),
        ([-0.0, 1e-9], [-0.0, -1e-9]),
    ):
        metric = row_metric(np.array(lons), np.array(lats))
        js = elevation.ask("metric", lons=lons, lats=lats)
        assert "ok" in js, js
        assert js["ok"] == {"dx": [_hex(v) for v in metric.dx], "dy": [_hex(v) for v in metric.dy],
                            "dg": [_hex(v) for v in metric.dg], "au": [_hex(v) for v in metric.au_row]}


def test_the_browser_reads_a_plans_blocks_in_the_ranges_python_reads(elevation):
    """C.elevationBlockRanges against elevation._read_blocks on plans made
    up for the purpose: blocks 64 KiB less one, exactly 64 KiB and a byte
    more apart, reads reaching 16 MiB exactly and a byte past it, blocks out
    of offset order, overlapping and with nothing to read, over one to three
    files. Both engines must read the same ranges in the same order, and
    every block with bytes must lie in the one read that names it. Prevents
    the browser reading other ranges than Python, which no committed
    fixture, all of them small, can show."""
    from types import SimpleNamespace

    from groundwater.mapping.elevation import PlanBlock, _read_blocks

    rng = random.Random(4102)
    gap, cap = 65536, 16 * 1048576
    for trial in range(400):
        names = [f"f{k}.tif" for k in range(rng.randint(1, 3))]
        blocks = []
        for k in range(len(names)):
            end = rng.choice([0, 8, 1000])
            for _ in range(rng.randint(1, 25)):
                if rng.random() < 0.1:
                    blocks.append(PlanBlock(k, len(blocks), 0, 0, None, True, ()))
                    continue
                offset = max(0, end + rng.choice([0, gap - 1, gap, gap + 1, rng.randint(1, 200_000),
                                                  -rng.randint(1, 50_000)]))
                length = rng.choice([1, 2402, 7202, rng.randint(1, 300_000), 1 << 20, cap - offset % 7, cap])
                blocks.append(PlanBlock(k, len(blocks), offset, length, None, True, ()))
                end = offset + length
        if trial % 3 == 0:
            rng.shuffle(blocks)
            blocks.sort(key=lambda b: b.file)
        recorded: list = []

        def reader(name: str):
            def read_at(offset: int, length: int) -> bytes:
                recorded.append([name, offset, length])
                return b""
            return read_at

        plan = SimpleNamespace(blocks=blocks, files=[SimpleNamespace(name=name) for name in names])
        _read_blocks(plan, {name: reader(name) for name in names})
        js = elevation.ask("reads", blocks=[[b.file, b.offset, b.length] for b in blocks], names=names)
        assert "ok" in js, js
        assert [r[:3] for r in js["ok"]] == recorded, f"trial {trial}"
        for b, block in enumerate(blocks):
            holding = [r for r in js["ok"] if b in r[3]]
            if not block.length:
                assert not holding, f"trial {trial}: block {b} has nothing to read"
                continue
            assert len(holding) == 1, f"trial {trial}: block {b} is in {len(holding)} reads"
            name, offset, length, _ = holding[0]
            assert name == names[block.file] and offset <= block.offset
            assert block.offset + block.length <= offset + length, f"trial {trial}: block {b} spills out"

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
    """The browser's GeoTIFF reader in a Node vm, asked one question at a time."""

    def __init__(self, tmp_path: Path):
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed; run `node --version` to check")
        driver = tmp_path / "reader.mjs"
        driver.write_text(_READER, encoding="utf-8")
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
        ("-1", "u8", None), ("1e39", "f32", flt_max), ("-1e39", "f32", -flt_max), ("Infinity", "f32", math.inf),
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

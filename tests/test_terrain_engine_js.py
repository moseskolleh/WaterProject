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
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import random
import shutil
import struct
import subprocess
import zlib
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

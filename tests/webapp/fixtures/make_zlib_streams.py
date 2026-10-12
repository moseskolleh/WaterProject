"""Write zlib_streams.json: the DEFLATE blocks the parity suite inflates.

Both engines inflate the blocks of a DEFLATE-compressed elevation model
(geotiff._inflate_block, gwt-core.js C.inflateZlib), and both must accept
and refuse the same blocks and give the same bytes. tests/webapp/parity.mjs
serves this file to the browser engine, make_reference.py records what the
Python one makes of it, and the two are compared in Chromium, where
DecompressionStream checks each accepted block a third way.

Thirty blocks that read, one or more of each kind a writer produces -
stored, fixed codes, dynamic codes, run-length and Huffman-only strategies,
pieces flushed and joined, empty, padded to a full block, with junk after
the checksum - each with the bytes the block has to give (``expected``) and
the bytes in a full block (``full``); then six that do not.

    python tests/webapp/fixtures/make_zlib_streams.py

The committed file is what both sides read, never a fresh run: zlib builds
differ in the bytes they write for the same input, so a run on another
machine can give other streams that inflate to the same thing. Run this
only to change the set, and regenerate reference.json after it.
"""

from __future__ import annotations

import base64
import json
import random
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "zlib_streams.json"


def _heights(rng: random.Random, n: int) -> bytes:
    """int16 heights in a random walk, little-endian, as a DEM's rows hold them."""
    z, out = 120, bytearray()
    while len(out) < n:
        z = max(-30, min(900, z + rng.randrange(-3, 4)))
        out += struct.pack("<h", z)
    return bytes(out[:n])


def _floats(rng: random.Random, n: int) -> bytes:
    """float32 heights to a tenth of a metre, most significant byte first,
    as the floating-point predictor leaves them."""
    z, out = 52.0, bytearray()
    while len(out) < n:
        z = round(z + rng.randrange(-4, 5) / 10, 1)
        out += struct.pack(">f", z)
    return bytes(out[:n])


def _runs(rng: random.Random, n: int) -> bytes:
    out = bytearray()
    while len(out) < n:
        out += bytes([rng.randrange(256)]) * rng.randrange(1, 200)
    return bytes(out[:n])


def _text(rng: random.Random, n: int) -> bytes:
    words = [b"borehole ", b"aquifer ", b"laterite ", b"granite ", b"strike ", b"m\n"]
    out = bytearray()
    while len(out) < n:
        out += rng.choice(words)
    return bytes(out[:n])


def _compress(data: bytes, level=6, strategy=zlib.Z_DEFAULT_STRATEGY, mem=8, wbits=15) -> bytes:
    c = zlib.compressobj(level, zlib.DEFLATED, wbits, mem, strategy)
    return c.compress(data) + c.flush()


def _joined(pieces) -> bytes:
    """Pieces from compressors of their own, each ended by a flush, joined
    into one zlib stream: ``[(data, level, strategy, flush), ...]``."""
    body, whole = b"", b""
    for i, (data, level, strategy, flush) in enumerate(pieces):
        c = zlib.compressobj(level, zlib.DEFLATED, -15, 8, strategy)
        body += c.compress(data) + c.flush(zlib.Z_FINISH if i == len(pieces) - 1 else flush)
        whole += data
    return b"\x78\x9c" + body + struct.pack(">I", zlib.adler32(whole))


def build() -> list[dict]:
    rng = random.Random(41)
    streams: list[dict] = []

    def add(name, stream, expected, full, junk=b""):
        streams.append({"name": name, "b64": base64.b64encode(stream + junk).decode("ascii"),
                        "expected": expected, "full": full, "junk": len(junk)})

    def block(name, data, **options):
        add(name, _compress(data, **options), len(data), len(data))

    block("stored, heights", _heights(rng, 3000), level=0)
    block("stored, random bytes", rng.randbytes(1500), level=0)
    block("fixed codes, text", _text(rng, 2000), strategy=zlib.Z_FIXED)
    block("fixed codes, a short row", _heights(rng, 64), strategy=zlib.Z_FIXED)
    block("fixed codes, long runs", _runs(rng, 3000), strategy=zlib.Z_FIXED, level=9)
    block("dynamic codes, heights", _heights(rng, 6000))
    block("dynamic codes, floats at level 9", _floats(rng, 6000), level=9)
    block("dynamic codes, level 1", _heights(rng, 2000) + _runs(rng, 2000), level=1)
    block("dynamic codes, floats, filtered", _floats(rng, 4000), strategy=zlib.Z_FILTERED)
    block("dynamic codes, text and floats at level 4", _text(rng, 1500) + _floats(rng, 2500), level=4)
    block("run-length, runs", _runs(rng, 5000), strategy=zlib.Z_RLE)
    block("run-length, heights", _heights(rng, 4000), strategy=zlib.Z_RLE)
    block("Huffman only, text", _text(rng, 3000), strategy=zlib.Z_HUFFMAN_ONLY)
    block("Huffman only, floats", _floats(rng, 3000), strategy=zlib.Z_HUFFMAN_ONLY)
    block("a 512-byte window", _heights(rng, 3000), wbits=9)
    block("memLevel 1", _text(rng, 3000), mem=1)
    block("memLevel 9, level 9, repeats", (_floats(rng, 700) * 6)[:4000], mem=9, level=9)
    block("zeros", bytes(8000), level=9)
    for i, flush in enumerate((zlib.Z_FULL_FLUSH, zlib.Z_SYNC_FLUSH, zlib.Z_FULL_FLUSH)):
        pieces = [(_heights(rng, 1500), 0, zlib.Z_DEFAULT_STRATEGY, flush),
                  (_floats(rng, 1500), 6, zlib.Z_DEFAULT_STRATEGY, flush),
                  (_runs(rng, 1000), 6, zlib.Z_RLE, flush),
                  (_text(rng, 800), 9, zlib.Z_FIXED, flush)]
        rng.shuffle(pieces)
        data = b"".join(p[0] for p in pieces)
        add(f"stored and Huffman pieces, flushed and joined {i + 1}", _joined(pieces), len(data), len(data))
    c = zlib.compressobj(6)
    data = [_heights(rng, 1200) for _ in range(3)]
    stream = (c.compress(data[0]) + c.flush(zlib.Z_SYNC_FLUSH) + c.compress(data[1])
              + c.flush(zlib.Z_FULL_FLUSH) + c.compress(data[2]) + c.flush())
    add("one compressor, sync and full flushes", stream, 3600, 3600)
    add("empty, level 6", zlib.compress(b"", 6), 0, 0)
    add("empty, stored", zlib.compress(b"", 0), 0, 0)
    add("empty, asked for nothing of a full block", zlib.compress(b""), 0, 700)
    rows = _heights(rng, 300)
    add("a last strip stored exactly", zlib.compress(rows), 300, 700)
    add("a last strip padded to a full block", zlib.compress(rows + bytes(400)), 300, 700)
    add("a last strip padded part of the way", zlib.compress(rows + bytes(150)), 300, 700)
    rows = _floats(rng, 2000)
    add("junk after the checksum", zlib.compress(rows), 2000, 2000, junk=b"\x00\x00\x00")
    add("a writer's padding after the checksum", zlib.compress(rows, 1), 2000, 2000,
        junk=rng.randbytes(13))
    assert len(streams) == 30, len(streams)

    data = _heights(rng, 4000)
    stream = zlib.compress(data)
    add("cut short", stream[:len(stream) // 2], 4000, 4000)
    add("a bad Adler-32", stream[:-1] + bytes([stream[-1] ^ 0x40]), 4000, 4000)
    flipped = bytearray(stream)
    flipped[len(stream) // 3] ^= 0x08
    add("a bit flipped in a Huffman block", bytes(flipped), 4000, 4000)
    raw = zlib.compressobj(6, zlib.DEFLATED, -15)
    add("raw DEFLATE with no zlib wrapper", raw.compress(data) + raw.flush(), 4000, 4000)
    add("more than one full block", stream, 4000, 3999)
    add("fewer bytes than the block needs", stream, 4001, 8000)
    return streams


def main() -> None:
    streams = build()
    FIXTURE.write_text(json.dumps(streams, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(HERE.parents[2])}: {len(streams)} streams, "
          f"{FIXTURE.stat().st_size} bytes")


if __name__ == "__main__":
    main()

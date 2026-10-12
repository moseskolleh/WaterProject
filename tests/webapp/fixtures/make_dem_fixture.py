"""Write tests/webapp/fixtures/dem/: small GeoTIFF elevation models known to the byte.

Both engines read GeoTIFF elevation models (PLAN.md step 4.1: the raw reader in
groundwater/geotiff.py and the "TIFF and GeoTIFF" section of gwt-core.js), and
both must read the same cells from the same file. A real Copernicus tile would
do for one case, but it is 48 MB, it may not be committed, and nobody could say
what it ought to read without trusting a third reader. So the files here are
written by hand, tag by tag and block by block, around heights made by integer
arithmetic: what every cell holds is known before any reader looks at it, and
GDAL, through rasterio, is the independent check that each file says what this
script means it to (tests/test_dem_fixtures.py).

The set covers what an operator is likely to supply and what goes wrong with
it: little- and big-endian, classic and BigTIFF, strips and tiles, every
compression and predictor the reader takes, the georeferencing and no-data
forms GDAL writes, overviews and masks on either side of the image, GDAL's
block leaders and trailers, sparse blocks, a padded last strip, tiles that join
or ought not to, missing tiles beside sea and beside land, and a file for each
way the reader refuses. MANIFEST.json says, for every file, what it is for,
whether a reader must read it or refuse it (and with which sentence), and the
layout facts a reader ought to find in it.

Nothing but the standard library is needed. DEFLATE is zlib's, at one fixed
level; LZW and PackBits are encoded here, because the standard library has
neither and because the LZW cases have to be written in ways no library writes
on request (a table kept full past libtiff's Clear, the pre-1992 bit order).
The one exception is utm_strip.tif, which is this toolkit's own GeoTIFF writer
output, so that reading it back anchors the writer as well.

    python tests/webapp/fixtures/make_dem_fixture.py           # write the files and MANIFEST.json
    python tests/webapp/fixtures/make_dem_fixture.py --check   # rebuild in memory and compare
    python tests/webapp/fixtures/make_dem_fixture.py --gdal    # rewrite the GDAL-written set (dev only)

``--check`` holds LZW, PackBits and uncompressed files to the byte. A DEFLATE
file is held to its tags and to what each block decodes to instead, because
zlib and zlib-ng write different bytes for the same input at the same level.
The GDAL-written files are made by ``--gdal`` with rasterio and committed as
they came out; they are checked against GDAL, not rebuilt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEM = HERE / "dem"
MANIFEST = "MANIFEST.json"

#: The zlib level of every DEFLATE block. Fixed, so that a rebuild on the same
#: zlib writes the same bytes; another zlib build may not, which is why
#: ``--check`` compares DEFLATE files by what they decode to.
DEFLATE_LEVEL = 9

# TIFF field types
BYTE, ASCII, SHORT, LONG, RATIONAL = 1, 2, 3, 4, 5
SBYTE, UNDEFINED, SSHORT, SLONG, SRATIONAL, FLOAT, DOUBLE = 6, 7, 8, 9, 10, 11, 12
LONG8 = 16
TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
TYPE_FORMAT = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q", 17: "q", 18: "Q"}

# TIFF and GeoTIFF tags
NEW_SUBFILE_TYPE = 254
SUBFILE_TYPE = 255
IMAGE_WIDTH = 256
IMAGE_LENGTH = 257
BITS_PER_SAMPLE = 258
COMPRESSION = 259
PHOTOMETRIC = 262
FILL_ORDER = 266
STRIP_OFFSETS = 273
SAMPLES_PER_PIXEL = 277
ROWS_PER_STRIP = 278
STRIP_BYTE_COUNTS = 279
PLANAR_CONFIG = 284
PREDICTOR = 317
TILE_WIDTH = 322
TILE_LENGTH = 323
TILE_OFFSETS = 324
TILE_BYTE_COUNTS = 325
SAMPLE_FORMAT = 339
MODEL_PIXEL_SCALE = 33550
MODEL_TIEPOINT = 33922
MODEL_TRANSFORMATION = 34264
GEO_KEY_DIRECTORY = 34735
GEO_DOUBLE_PARAMS = 34736
GEO_ASCII_PARAMS = 34737
GDAL_METADATA = 42112
GDAL_NODATA = 42113

#: Sample kinds: SampleFormat (1 unsigned, 2 signed, 3 IEEE float), bits, struct code.
KINDS = {
    "u8": (1, 8, "B"), "i8": (2, 8, "b"), "u16": (1, 16, "H"), "i16": (2, 16, "h"),
    "u32": (1, 32, "I"), "i32": (2, 32, "i"), "f32": (3, 32, "f"), "f64": (3, 64, "d"),
}

FLT_MAX = 3.4028234663852886e38
#: The plausibility bounds of spec section 2.5 (terrain.implausible_below_m and
#: _above_m), used only to count the voids MANIFEST.json says a reader will find.
IMPLAUSIBLE_BELOW, IMPLAUSIBLE_ABOVE = -1000.0, 9000.0

#: GDAL's ghost header, as the real GLO-30 COGs carry it (bytes 8-191 of
#: Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif): the layout is promised, and
#: every block is preceded by its size and followed by a copy of its last four
#: bytes, none of which the tile byte counts include.
GHOST_BODY = (b"LAYOUT=IFDS_BEFORE_DATA\nBLOCK_ORDER=ROW_MAJOR\nBLOCK_LEADER=SIZE_AS_UINT4\n"
              b"BLOCK_TRAILER=LAST_4_BYTES_REPEATED\nKNOWN_INCOMPATIBLE_EDITION=NO\n ")

#: One arcsecond, the Copernicus GLO-30 spacing, as the real tiles write it.
ARCSEC = 1 / 3600


# --- heights --------------------------------------------------------------------------------

def mix(*parts: int) -> int:
    """FNV-1a over each part's four low bytes, then murmur3's finaliser: a hash any language computes alike.

    The finaliser matters: FNV-1a's low bits depend only on the low bits of
    each byte, so without it ``mix(c, seed) % 4`` is just ``c % 4`` and a
    "ragged" coastline comes out as a regular staircase.
    """
    h = 2166136261
    for part in parts:
        for shift in (0, 8, 16, 24):
            h = ((h ^ ((part >> shift) & 0xFF)) * 16777619) & 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    return h ^ (h >> 16)


def terrain_dm(gi: int, gj: int, seed: int) -> int:
    """Height in whole decimetres at lattice cell ``gi`` east, ``gj`` south.

    A slope rising to the north-east, a ridge across it on a diagonal, blocky
    plateaus and a little roughness. The surface is asymmetric, so a grid read
    transposed or mirrored cannot pass, and being whole decimetres it has the
    ties a 0.1 m-quantised model has.
    """
    slope = 3 * gi - 2 * gj
    ridge = max(0, 400 - 9 * abs(2 * gi + 3 * gj - 70 - seed % 40))
    plateau = mix(gi // 5, gj // 4, seed) % 60
    rough = mix(gi, gj, seed) % 5
    return 1500 + slope + ridge + plateau + rough


def patch(width: int, height: int, seed: int, *, gi0: int = 0, gj0: int = 0) -> list[list[int]]:
    """Decimetre heights of a ``width`` by ``height`` block, north row first."""
    return [[terrain_dm(gi0 + c, gj0 + r, seed) for c in range(width)] for r in range(height)]


def metres(rows: list[list[int]]) -> list[list[float]]:
    """Decimetres as metres, each the double nearest to ``dm / 10``."""
    return [[dm / 10 for dm in row] for row in rows]


def whole_metres(rows: list[list[int]], offset: int = 0) -> list[list[int]]:
    return [[dm // 10 + offset for dm in row] for row in rows]


# --- codecs ---------------------------------------------------------------------------------

CLEAR, EOI = 256, 257


class _Bits:
    """Codes packed into bytes: most significant bit first (TIFF LZW), or least (pre-1992 LZW)."""

    def __init__(self, msb_first: bool):
        self.msb_first = msb_first
        self.acc = 0
        self.count = 0
        self.out = bytearray()

    def put(self, code: int, width: int) -> None:
        if self.msb_first:
            self.acc = (self.acc << width) | code
            self.count += width
            while self.count >= 8:
                self.count -= 8
                self.out.append((self.acc >> self.count) & 0xFF)
            self.acc &= (1 << self.count) - 1
        else:
            self.acc |= code << self.count
            self.count += width
            while self.count >= 8:
                self.out.append(self.acc & 0xFF)
                self.acc >>= 8
                self.count -= 8

    def finish(self) -> bytes:
        if self.count:
            self.out.append((self.acc << (8 - self.count)) & 0xFF if self.msb_first else self.acc & 0xFF)
        return bytes(self.out)


@dataclass
class LzwStats:
    """What an encoding did, for MANIFEST.json: codes sent while the table was full."""

    codes: int = 0
    clears: int = 0
    codes_after_full_table: int = 0


def lzw_encode(data: bytes, *, deferred: int = 0, old_style: bool = False,
               stats: LzwStats | None = None) -> bytes:
    """TIFF LZW, as libtiff writes it, or in two forms libtiff only reads.

    The code width is whatever the decoder will be reading at, because the
    encoder tracks the decoder's table rather than its own: the decoder adds
    an entry for every code after the first following a Clear, one step
    behind the encoder. In the TIFF form it widens one code early, when its
    next free entry plus one reaches 512, 1024 or 2048 (libtiff's "Aldus"
    change); the pre-1992 form (``old_style``) widens when the entry itself
    reaches them and packs codes least significant bit first.

    libtiff's encoder sends Clear when its next free entry reaches 4094.
    ``deferred=N`` instead fills the table to 4095 and sends N more codes
    before the Clear. libtiff and GDAL read up to N = 1024, because libtiff's
    decoding table holds 5,119 entries (MAXCODE(12) + 1024), the entries past
    4095 being ones no 12-bit code can name; N = 1025 overflows it.
    """
    stats = stats if stats is not None else LzwStats()
    bits = _Bits(msb_first=not old_style)
    width, decoder_next, first = 9, 258, True

    def put(code: int) -> None:
        nonlocal width, decoder_next, first
        bits.put(code, width)
        stats.codes += 1
        if code == CLEAR:
            width, decoder_next, first = 9, 258, True
            stats.clears += 1
        elif code != EOI:
            if first:
                first = False
            else:
                decoder_next += 1
                reached = decoder_next if old_style else decoder_next + 1
                if reached >= 1 << width and width < 12:
                    width += 1

    def fresh() -> dict[bytes, int]:
        return {bytes((i,)): i for i in range(256)}

    table, encoder_next, extra = fresh(), 258, 0
    limit = 4096 if deferred else 4094
    put(CLEAR)
    w = b""
    for byte in data:
        wc = w + bytes((byte,))
        if wc in table:
            w = wc
            continue
        put(table[w])
        if encoder_next < limit:
            table[wc] = encoder_next
            encoder_next += 1
            if encoder_next == limit and not deferred:
                put(CLEAR)
                table, encoder_next = fresh(), 258
        else:
            extra += 1
            stats.codes_after_full_table += 1
            if extra >= deferred:
                put(CLEAR)
                table, encoder_next, extra = fresh(), 258, 0
        w = bytes((byte,))
    if w:
        put(table[w])
    put(EOI)
    return bits.finish()


def packbits(row: bytes, *, noop: bool = False) -> bytes:
    """PackBits for one row: runs of three or more repeated, the rest literal.

    ``noop`` starts the row with the header byte -128, which a decoder must
    skip: libtiff does, and a decoder that reads it as a run would not.
    """
    out = bytearray(b"\x80" if noop else b"")
    i, n = 0, len(row)
    while i < n:
        run = 1
        while i + run < n and run < 128 and row[i + run] == row[i]:
            run += 1
        if run >= 3:
            out += bytes(((1 - run) & 0xFF, row[i]))
            i += run
            continue
        start = i
        while i < n and i - start < 128:
            if i + 2 < n and row[i] == row[i + 1] == row[i + 2]:
                break
            i += 1
        out.append(i - start - 1)
        out += row[start:i]
    return bytes(out)


def horizontal_difference(row: bytes, order: str, size: int) -> bytes:
    """Predictor 2: each word less the one before it, modulo its width, in the file's order."""
    code = {1: "B", 2: "H", 4: "I", 8: "Q"}[size]
    words = struct.unpack(f"{order}{len(row) // size}{code}", row)
    mask = (1 << (8 * size)) - 1
    diffs = [words[0]] + [(words[i] - words[i - 1]) & mask for i in range(1, len(words))]
    return struct.pack(f"{order}{len(diffs)}{code}", *diffs)


def floating_point_difference(row: bytes, order: str, size: int) -> bytes:
    """Predictor 3 (libtiff fpDiff): bytes split into planes, most significant first, then differenced.

    The planes are most significant byte first whatever the file's byte
    order, so a big-endian file holds the same bytes as a little-endian one,
    and the differencing runs straight through the plane boundaries.
    """
    n = len(row) // size
    words = [row[k * size:(k + 1) * size] for k in range(n)]
    if order == "<":
        words = [w[::-1] for w in words]
    planes = bytes(words[x][b] for b in range(size) for x in range(n))
    out = bytearray(planes)
    for i in range(len(planes) - 1, 0, -1):
        out[i] = (planes[i] - planes[i - 1]) & 0xFF
    return bytes(out)


# --- images and files -----------------------------------------------------------------------

@dataclass
class Ifd:
    """One image file directory: its tags and the blocks its offsets point at (None: sparse)."""

    tags: dict
    blocks: list
    tiled: bool


def pack(order: str, kind: str, values) -> bytes:
    return struct.pack(f"{order}{len(values)}{KINDS[kind][2]}", *values)


def image(rows, kind: str, order: str, *, compression: int = 1, predictor: int = 1,
          tile: tuple[int, int] | None = None, rows_per_strip: int | None = None,
          samples: int = 1, pad=0, sparse=(), full_last_strip: bool = False,
          packbits_noop: bool = False, lzw_deferred: int = 0, old_lzw: bool = False,
          junk_after: dict | None = None, sample_format_tag: bool = True,
          lzw_stats: LzwStats | None = None) -> Ifd:
    """A directory holding ``rows`` (north row first) and its encoded blocks.

    ``predictor`` is written as the tag says and applied only with LZW or
    DEFLATE, as libtiff does; with no compression or PackBits the tag is
    there but the values are stored as they are (pred2_none.tif).
    """
    height = len(rows)
    width = len(rows[0]) // samples
    fmt, bits, _ = KINDS[kind]
    size = bits // 8
    blocks_rows = []
    if tile:
        tw, th = tile
        for ty in range(-(-height // th)):
            for tx in range(-(-width // tw)):
                block = []
                for r in range(ty * th, ty * th + th):
                    block.append(pack(order, kind, [
                        rows[r][c] if r < height and c < width else pad
                        for c in range(tx * tw, tx * tw + tw)]))
                blocks_rows.append(block)
    else:
        rps = rows_per_strip or height
        for k in range(-(-height // rps)):
            block = [pack(order, kind, rows[r]) for r in range(k * rps, min(height, (k + 1) * rps))]
            if full_last_strip:
                block += [pack(order, kind, [pad] * width * samples)] * (rps - len(block))
            blocks_rows.append(block)

    applied = predictor != 1 and compression in (5, 8, 32946)
    blocks = []
    for index, block in enumerate(blocks_rows):
        if index in sparse:
            blocks.append(None)
            continue
        if applied and predictor == 2:
            block = [horizontal_difference(row, order, size) for row in block]
        elif applied and predictor == 3:
            block = [floating_point_difference(row, order, size) for row in block]
        raw = b"".join(block)
        if compression == 1:
            data = raw
        elif compression == 5:
            data = lzw_encode(raw, deferred=lzw_deferred, old_style=old_lzw, stats=lzw_stats)
        elif compression in (8, 32946):
            data = zlib.compress(raw, DEFLATE_LEVEL)
        elif compression == 32773:
            data = b"".join(packbits(row, noop=packbits_noop) for row in block)
        elif compression == 7:
            data = b"\xff\xd8\xff\xd9"  # a JPEG's start and end markers: refused before decoding
        else:
            raise ValueError(f"no encoder for compression {compression}")
        if junk_after and index in junk_after:
            data += junk_after[index]
        blocks.append(data)

    tags = {
        IMAGE_WIDTH: (SHORT, [width]),
        IMAGE_LENGTH: (SHORT, [height]),
        BITS_PER_SAMPLE: (SHORT, [bits] * samples),
        COMPRESSION: (SHORT, [compression]),
        PHOTOMETRIC: (SHORT, [1]),
        SAMPLES_PER_PIXEL: (SHORT, [samples]),
        PLANAR_CONFIG: (SHORT, [1]),
    }
    if sample_format_tag:
        tags[SAMPLE_FORMAT] = (SHORT, [fmt] * samples)
    if predictor != 1:
        tags[PREDICTOR] = (SHORT, [predictor])
    if tile:
        tags[TILE_WIDTH] = (SHORT, [tile[0]])
        tags[TILE_LENGTH] = (SHORT, [tile[1]])
    else:
        tags[ROWS_PER_STRIP] = (SHORT, [rows_per_strip or height])
    return Ifd(tags, blocks, bool(tile))


def _payload(order: str, kind: int, values) -> tuple[bytes, int]:
    if isinstance(values, (bytes, bytearray)):
        return bytes(values), len(values)
    if kind in (RATIONAL, SRATIONAL):
        flat = [v for pair in values for v in pair]
        return struct.pack(f"{order}{len(flat)}{'I' if kind == RATIONAL else 'i'}", *flat), len(values)
    return struct.pack(f"{order}{len(values)}{TYPE_FORMAT[kind]}", *values), len(values)


def ghost_header() -> bytes:
    text = b"GDAL_STRUCTURAL_METADATA_SIZE=%06d bytes\n" % len(GHOST_BODY) + GHOST_BODY
    return text + b"\x00" * (len(text) % 2)


def assemble(order: str, ifds: list[Ifd], *, bigtiff: bool = False, ghost: bool = False,
             ifds_first: bool = True, data_order: list[int] | None = None,
             loop_to: int | None = None, count_type: int | None = None) -> bytes:
    """A TIFF file of ``ifds``, chained in list order.

    ``ifds_first`` puts every directory before the data, as a COG does;
    otherwise the data comes first and the directories end the file, as
    libtiff writes by default. ``ghost`` adds GDAL's ghost header and wraps
    each block in its leader and trailer. ``loop_to`` points the last
    directory back at an earlier one instead of ending the chain.
    """
    entry_size, inline, word = (20, 8, "Q") if bigtiff else (12, 4, "I")
    offset_type = LONG8 if bigtiff else LONG
    count_type = count_type or offset_type
    data_order = data_order if data_order is not None else list(range(len(ifds)))
    for ifd in ifds:
        offsets_tag, counts_tag = (TILE_OFFSETS, TILE_BYTE_COUNTS) if ifd.tiled else (STRIP_OFFSETS, STRIP_BYTE_COUNTS)
        ifd.tags[offsets_tag] = (offset_type, [0] * len(ifd.blocks))
        ifd.tags[counts_tag] = (count_type, [0 if b is None else len(b) for b in ifd.blocks])

    prelude = ghost_header() if ghost else b""
    ifd_at, value_at, block_at = {}, {}, {}

    def place_directories(pos: int) -> int:
        for k, ifd in enumerate(ifds):
            pos += pos % 2
            ifd_at[k] = pos
            pos += (8 if bigtiff else 2) + entry_size * len(ifd.tags) + (8 if bigtiff else 4)
            for tag in sorted(ifd.tags):
                payload, _ = _payload(order, *ifd.tags[tag])
                if len(payload) > inline:
                    pos += pos % 2
                    value_at[k, tag] = pos
                    pos += len(payload)
        return pos

    def place_data(pos: int) -> int:
        for k in data_order:
            for b, block in enumerate(ifds[k].blocks):
                if block is None:
                    continue
                pos += 4 if ghost else 0
                block_at[k, b] = pos
                pos += len(block) + (4 if ghost else 0)
        return pos

    start = (16 if bigtiff else 8) + len(prelude)
    end = place_data(place_directories(start)) if ifds_first else place_directories(place_data(start))
    for k, ifd in enumerate(ifds):
        offsets_tag = TILE_OFFSETS if ifd.tiled else STRIP_OFFSETS
        ifd.tags[offsets_tag] = (offset_type, [block_at.get((k, b), 0) for b in range(len(ifd.blocks))])

    out = bytearray(end)
    mark = b"II" if order == "<" else b"MM"
    if bigtiff:
        out[0:16] = mark + struct.pack(f"{order}HHHQ", 43, 8, 0, ifd_at[0])
    else:
        out[0:8] = mark + struct.pack(f"{order}HI", 42, ifd_at[0])
    out[start - len(prelude):start] = prelude
    for k, ifd in enumerate(ifds):
        pos = ifd_at[k]
        out[pos:pos + (8 if bigtiff else 2)] = struct.pack(order + ("Q" if bigtiff else "H"), len(ifd.tags))
        pos += 8 if bigtiff else 2
        for tag in sorted(ifd.tags):
            kind, values = ifd.tags[tag]
            payload, count = _payload(order, kind, values)
            head = struct.pack(order + ("HHQ" if bigtiff else "HHI"), tag, kind, count)
            if len(payload) > inline:
                field_ = struct.pack(order + word, value_at[k, tag])
                at = value_at[k, tag]
                out[at:at + len(payload)] = payload
            else:
                field_ = payload.ljust(inline, b"\x00")
            out[pos:pos + entry_size] = head + field_
            pos += entry_size
        if k + 1 < len(ifds):
            following = ifd_at[k + 1]
        else:
            following = ifd_at[loop_to] if loop_to is not None else 0
        out[pos:pos + (8 if bigtiff else 4)] = struct.pack(order + word, following)
    for (k, b), at in block_at.items():
        block = ifds[k].blocks[b]
        out[at:at + len(block)] = block
        if ghost:
            out[at - 4:at] = struct.pack("<I", len(block))
            out[at + len(block):at + len(block) + 4] = block[-4:]
    return bytes(out)


# --- georeferencing -------------------------------------------------------------------------

@dataclass
class Georef:
    """Where a grid lies, as the file states it.

    ``x``/``y`` are the tiepoint's model coordinates (or the transform's
    translation), at raster point (``tie_col``, ``tie_row``). ``raster`` is the
    GTRasterType key: 1 PixelIsArea, 2 PixelIsPoint, None for no key (which
    GDAL and the reader take as area). ``model`` None leaves out the GeoKey
    directory altogether.
    """

    x: float
    y: float
    sx: float
    sy: float
    raster: int | None = 2
    model: int | None = 2
    epsg: int | None = 4326
    tie_col: int = 0
    tie_row: int = 0
    transform: bool = False
    copernicus_keys: bool = False

    def tags(self) -> dict:
        tags = {}
        if self.transform:
            matrix = [self.sx, 0.0, 0.0, self.x, 0.0, -self.sy, 0.0, self.y,
                      0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
            tags[MODEL_TRANSFORMATION] = (DOUBLE, matrix)
        else:
            tags[MODEL_PIXEL_SCALE] = (DOUBLE, [self.sx, self.sy, 0.0])
            tags[MODEL_TIEPOINT] = (DOUBLE, [float(self.tie_col), float(self.tie_row), 0.0, self.x, self.y, 0.0])
        if self.model is None:
            return tags
        keys = [(1024, 0, 1, self.model)]
        if self.raster is not None:
            keys.append((1025, 0, 1, self.raster))
        if self.model == 2:
            keys.append((2048, 0, 1, self.epsg))
            if self.copernicus_keys:
                # exactly the keys of the real tiles: citation, degrees, and the ellipsoid
                keys += [(2049, GEO_ASCII_PARAMS, 7, 0), (2054, 0, 1, 9102),
                         (2057, GEO_DOUBLE_PARAMS, 1, 1), (2059, GEO_DOUBLE_PARAMS, 1, 0)]
                tags[GEO_DOUBLE_PARAMS] = (DOUBLE, [298.257223563, 6378137.0])
                tags[GEO_ASCII_PARAMS] = (ASCII, b"WGS 84|\x00")
        else:
            keys.append((3072, 0, 1, self.epsg))
        directory = [1, 1, 0, len(keys)] + [v for key in sorted(keys) for v in key]
        tags[GEO_KEY_DIRECTORY] = (SHORT, directory)
        return tags

    def centres(self) -> tuple[float, float]:
        """Centre of column 0 and of row 0, by the expressions of spec section 2.4."""
        area = self.raster != 2
        col, row = (0, 0) if self.transform else (self.tie_col, self.tie_row)
        x0 = (self.x - col * self.sx) + (0.5 * self.sx if area else 0.0)
        y0 = (self.y + row * self.sy) - (0.5 * self.sy if area else 0.0)
        return x0, y0


def ascii_tag(text: str) -> tuple[int, bytes]:
    return ASCII, text.encode("ascii") + b"\x00"


def metadata_xml(*items: tuple[str, str, str]) -> str:
    """GDAL_METADATA as GDAL writes it: one Item per (name, role, value)."""
    body = "".join(f'  <Item name="{name}" sample="0" role="{role}">{value}</Item>\n'
                   for name, role, value in items)
    return f"<GDALMetadata>\n{body}</GDALMetadata>\n"


# --- what a reader ought to find ------------------------------------------------------------

def nodata_value(text: str | None, kind: str):
    """GDAL_NODATA parsed and cast as spec section 2.5 says, or None, or 'unreadable'."""
    if text is None:
        return None
    s = text.strip("\x00 \t\n\r")
    low = s.lower()
    if s == "":
        return None
    if low in ("nan", "+nan", "-nan"):
        value = float("nan")
    elif low in ("inf", "+inf", "infinity", "+infinity"):
        value = float("inf")
    elif low in ("-inf", "-infinity"):
        value = float("-inf")
    else:
        if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", s):
            return "unreadable"
        value = float(s)
    fmt, bits, code = KINDS[kind]
    if fmt == 3 and bits == 32:
        if value == value and abs(value) != float("inf") and abs(value) > FLT_MAX:
            value = FLT_MAX if value > 0 else -FLT_MAX
        return struct.unpack("f", struct.pack("f", value))[0]
    if fmt == 3:
        return value
    if value != value or abs(value) == float("inf") or value != int(value):
        return "no cell"
    low_bound, high_bound = (0, (1 << bits) - 1) if fmt == 1 else (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
    return int(value) if low_bound <= value <= high_bound else "no cell"


def json_number(value):
    """A float JSON can carry: NaN and infinities as strings."""
    if isinstance(value, float) and value != value:
        return "nan"
    if isinstance(value, float) and abs(value) == float("inf"):
        return "inf" if value > 0 else "-inf"
    return value


@dataclass
class Fixture:
    """One committed file: its bytes, its MANIFEST.json entry, and its samples as GDAL reads them."""

    name: str
    data: bytes
    entry: dict
    samples: bytes = b""  # north row first, each sample little-endian in its own type


def native(rows, kind: str, sparse_cells=()) -> list[list]:
    """The values as the file stores them (rounded to float32 where it is float32)."""
    code = KINDS[kind][2]
    out = [list(struct.unpack(f"<{len(row)}{code}", struct.pack(f"<{len(row)}{code}", *row))) for row in rows]
    for r, c in sparse_cells:
        out[r][c] = 0
    return out


def describe(name: str, purpose: str, rows, kind: str, georef: Georef | None, *, order: str,
             bigtiff: bool, compression: int, predictor: int, tile, rows_per_strip, nodata,
             raw: str = "read", elevation: str | None = "read", ifd_index: int = 0,
             sparse=(), samples_per_pixel: int = 1, **extra) -> tuple[dict, bytes]:
    """The MANIFEST.json entry for a file, and its samples packed for the digest.

    Sparse blocks are counted as 0 in the digest, because that is what GDAL
    reads them as without a no-data value; the reader voids them instead,
    which ``voids`` counts.
    """
    height = len(rows)
    width = len(rows[0]) // samples_per_pixel
    fmt, bits, code = KINDS[kind]
    sparse_cells = set()
    if sparse:
        tw, th = tile
        across = -(-width // tw)
        for index in sparse:
            ty, tx = divmod(index, across)
            sparse_cells |= {(r, c) for r in range(ty * th, min(height, ty * th + th))
                             for c in range(tx * tw, min(width, tx * tw + tw))}
    values = native(rows, kind, sparse_cells)
    samples = b"".join(struct.pack(f"<{len(row)}{code}", *row) for row in values)
    entry = {"purpose": purpose, "raw": raw, "elevation": elevation, "byte_order": order,
             "bigtiff": bigtiff, "width": width, "height": height, "tiled": bool(tile)}
    if tile:
        entry["block_width"], entry["block_height"] = tile
    else:
        entry["rows_per_strip"] = rows_per_strip or height
    entry.update({"compression": compression, "predictor": predictor, "sample_format": fmt, "bits": bits})
    if samples_per_pixel != 1:
        entry["samples_per_pixel"] = samples_per_pixel
    if ifd_index:
        entry["ifd_index"] = ifd_index
    if georef is not None:
        x0, y0 = georef.centres()
        entry.update({"model_type": georef.model, "raster_type": 1 if georef.raster != 2 else 2,
                      "epsg": georef.epsg if georef.model is not None else None})
        if georef.transform:
            entry["georeference"] = "ModelTransformation"
        entry.update({"x0": x0, "y0": y0, "sx": georef.sx, "sy": georef.sy})
    parsed = nodata_value(nodata, kind)
    if nodata is not None:
        entry["nodata"] = nodata
        entry["nodata_value"] = json_number(parsed) if not isinstance(parsed, str) else parsed
    if samples_per_pixel == 1 and parsed != "unreadable":
        no_data = implausible = 0
        for r, row in enumerate(values):
            for c, v in enumerate(row):
                if (r, c) in sparse_cells or v != v or (parsed is not None and not isinstance(parsed, str)
                                                         and v == parsed):
                    no_data += 1
                elif abs(v) == float("inf") or v < IMPLAUSIBLE_BELOW or v > IMPLAUSIBLE_ABOVE:
                    implausible += 1
        if no_data or implausible:
            entry["voids"] = {"no_data": no_data, "implausible": implausible}
    if sparse:
        entry["sparse_blocks"] = sorted(sparse)
    if samples_per_pixel == 1:
        entry["samples_sha256"] = hashlib.sha256(samples).hexdigest()
    entry.update(extra)
    return entry, samples


def single(name: str, purpose: str, rows, kind: str, georef: Georef | None, *, order: str = "<",
           bigtiff: bool = False, compression: int = 1, predictor: int = 1, tile=None,
           rows_per_strip: int | None = None, nodata: str | None = None, metadata: str | None = None,
           ifds_first: bool = True, raw: str = "read", elevation: str | None = "read",
           tags: dict | None = None, drop: tuple = (), count_type: int | None = None,
           manifest: dict | None = None, **options) -> Fixture:
    """A file holding one image, in one directory, with the given encoding and georeferencing."""
    stats = LzwStats()
    ifd = image(rows, kind, order, compression=compression, predictor=predictor, tile=tile,
                rows_per_strip=rows_per_strip, lzw_stats=stats, **options)
    if georef is not None:
        ifd.tags.update(georef.tags())
    if nodata is not None:
        ifd.tags[GDAL_NODATA] = ascii_tag(nodata)
    if metadata is not None:
        ifd.tags[GDAL_METADATA] = ascii_tag(metadata)
    ifd.tags.update(tags or {})
    for tag in drop:
        ifd.tags.pop(tag, None)
    data = assemble(order, [ifd], bigtiff=bigtiff, ifds_first=ifds_first, count_type=count_type)
    extra = dict(manifest or {})
    if not ifds_first:
        extra["ifd_at_end"] = True
    if options.get("lzw_deferred"):
        extra["lzw_codes_after_full_table"] = stats.codes_after_full_table
    entry, samples = describe(
        name, purpose, rows, kind, georef, order=order, bigtiff=bigtiff, compression=compression,
        predictor=predictor, tile=tile, rows_per_strip=rows_per_strip, nodata=nodata, raw=raw,
        elevation=elevation, sparse=options.get("sparse", ()), samples_per_pixel=options.get("samples", 1),
        **extra)
    return Fixture(name, data, entry, samples)


# --- the fixtures ---------------------------------------------------------------------------

def copernicus_pair() -> list[Fixture]:
    """The 40 columns either side of 11 W and the 40 rows below 9 N, laid out as GLO-30 COGs are.

    Float32, DEFLATE with the floating-point predictor, 16 x 16 tiles (the
    real tiles are 1024), PixelIsPoint with the real tiles' GeoKeys, GDAL's
    ghost header with block leaders and trailers, the full image first and
    one overview after it, and the overview's data written before the full
    image's, as GDAL's COG driver orders them. The two abut on one lattice.

    The same bytes go out again as n08w012.tif and n08w011.tif, names
    Copernicus does not use. Spec section 7.3 asks only for n08w012.tif, to
    show the GLO-30 fingerprint prompt, but the fingerprint (section 2.10)
    wants the first centre on a whole degree, and this clip of N08 W012
    starts 40 cells west of 11 W; the W011 clip starts on 11 W and 9 N, so
    its copy is the one that prompts.
    """
    out = []
    for name, lon0, first_col in (("Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", -12.0, 3560),
                                  ("Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif", -11.0, 0)):
        gi0 = 0 if lon0 == -12.0 else 40
        dm = patch(40, 40, 8, gi0=gi0)
        rows = metres(dm)
        overview = [[(dm[2 * r][2 * c] + dm[2 * r][2 * c + 1] + dm[2 * r + 1][2 * c]
                      + dm[2 * r + 1][2 * c + 1] + 2) // 4 / 10 for c in range(20)] for r in range(20)]
        georef = Georef(lon0 + first_col * ARCSEC, 9.0, ARCSEC, ARCSEC, raster=2, copernicus_keys=True)
        full = image(rows, "f32", "<", compression=8, predictor=3, tile=(16, 16))
        full.tags.update(georef.tags())
        reduced = image(overview, "f32", "<", compression=8, predictor=3, tile=(16, 16))
        reduced.tags[NEW_SUBFILE_TYPE] = (LONG, [1])
        data = assemble("<", [full, reduced], ghost=True, data_order=[1, 0])
        entry, samples = describe(
            name, "One of two abutting GLO-30-style tiles, named as Copernicus names them: recognised "
            "as copernicus_glo30 by name and georeferencing, and joined without a seam.",
            rows, "f32", georef, order="<", bigtiff=False, compression=8, predictor=3, tile=(16, 16),
            rows_per_strip=None, nodata=None, ghost=True, overviews_after=1)
        out.append(Fixture(name, data, entry, samples))
    copies = []
    for copy_name, source, fits in (("n08w012.tif", out[0], False), ("n08w011.tif", out[1], True)):
        entry = dict(source.entry)
        entry["purpose"] = (
            f"The bytes of {source.name} under a name Copernicus does not use: unidentified, never credited. "
            + ("Its layout fits the GLO-30 fingerprint (spec section 2.10), so it prompts the operator to "
               "declare the source." if fits else
               "Its first column centre is not on a whole degree, so it does not fit the GLO-30 fingerprint "
               "of spec section 2.10; n08w011.tif is the copy that does."))
        entry["same_bytes_as"] = source.name
        entry["fits_glo30_fingerprint"] = fits
        copies.append(Fixture(copy_name, source.data, entry, source.samples))
    return out + copies


JOIN_SX = ARCSEC
JOIN_X, JOIN_Y = -12.5, 8.75


def joins() -> list[Fixture]:
    """Files on one 1-arcsecond lattice that join, or must not."""
    seed = 101

    def rows_at(gi0, gj0, width, height):
        return patch(width, height, seed, gi0=gi0, gj0=gj0)

    def at(gi0, gj0, sx=JOIN_SX, half=0.0):
        return Georef(JOIN_X + (gi0 + half) * JOIN_SX, JOIN_Y - gj0 * JOIN_SX, sx, sx, raster=2)

    north = metres(rows_at(0, 0, 24, 20))
    south = metres(rows_at(0, 19, 24, 19))
    out = [single(
        "overlap_north.tif",
        "The northern file of the overlap sets: its last row is the first row of each overlap_south file.",
        north, "f32", at(0, 0), compression=5, predictor=3, rows_per_strip=7)]
    out.append(single(
        "overlap_south_agrees.tif",
        "Shares one row with overlap_north.tif, holding the same values there: joined, one copy kept.",
        south, "f32", at(0, 19), order=">", compression=8, tile=(16, 16)))
    disagree_dm = rows_at(0, 19, 24, 19)
    for c, step in ((3, 3), (11, -5), (20, 12)):
        disagree_dm[0][c] += step
    out.append(single(
        "overlap_south_disagrees.tif",
        "Shares one row with overlap_north.tif but differs there at three cells, by up to 1.2 m: "
        "refused with terrain.join_disagree.",
        metres(disagree_dm), "f32", at(0, 19), rows_per_strip=1))
    fill = [row[:] for row in south]
    fill[0] = [-32767.0] * 24
    out.append(single(
        "overlap_south_fill_edge.tif",
        "Shares one row with overlap_north.tif, where it holds Copernicus's undeclared invalid value "
        "-32767: implausible there, so overlap_north.tif's heights are kept.",
        fill, "f32", at(0, 19), compression=5, predictor=2, rows_per_strip=7))
    out.append(single(
        "phase_half_cell.tif",
        "On overlap_north.tif's spacing but half a cell to the east: refused with terrain.join_phase.",
        metres(rows_at(20, 0, 20, 20)), "f32", at(20, 0, half=0.5), rows_per_strip=7))
    out.append(single(
        "spacing_mismatch.tif",
        "Two arcseconds a cell beside overlap_north.tif's one: refused with terrain.join_spacing.",
        metres(rows_at(24, 0, 12, 10)), "f32", at(24, 0, sx=2 * JOIN_SX), rows_per_strip=7))
    return out


TILE_P = 40
TILE_SX = 1 / TILE_P


def coast_dm(gi: int, gj: int) -> int:
    """Land rising to the north-east from a coast in the south-west, in decimetres, never below 0.1 m."""
    return 15 + 6 * gi + 5 * (79 - gj) + mix(gi // 2, gj // 2, 40) % 30


def holes() -> list[Fixture]:
    """1-degree tiles at 40 cells a degree around a missing tile, N07 W013.

    The lattice runs from 13 W and 9 N; the supplied tiles are N08 W013, N08
    W012 and N07 W012, laid out as GLO-30 COGs are (PixelIsPoint, the first
    centre on the whole degree, 40 x 40). Which way the missing tile reads
    depends only on the full edges of its supplied 4-neighbours: N08 W013's
    last row and N07 W012's first column.
    """
    def land(gi, gj):
        return False

    def sea_n(gi, gj):  # a ragged coast whose sea takes in the whole last row
        return gj >= 33 + mix(gi, 1) % 4

    def sea_e(gi, gj):  # a ragged coast whose sea takes in the whole first column
        return gi <= 45 - mix(gj, 2) % 4

    def sea_part(gi, gj):  # sea only east of 12.5 W, so the last row is half land
        return gi >= 20 and gj >= 35 + mix(gi, 3) % 3

    def tile(lon0, lat0, sea=land, kind="f32", fill=land):
        gi0, gj0 = round((lon0 + 13) * TILE_P), round((9 - (lat0 + 1)) * TILE_P)
        rows = []
        for r in range(TILE_P):
            row = []
            for c in range(TILE_P):
                gi, gj = gi0 + c, gj0 + r
                if fill(gi, gj):
                    row.append(-FLT_MAX)
                elif sea(gi, gj):
                    row.append(0 if kind == "i16" else 0.0)
                else:
                    row.append(coast_dm(gi, gj) // 10 if kind == "i16" else coast_dm(gi, gj) / 10)
            rows.append(row)
        return rows, Georef(float(lon0), float(lat0 + 1), TILE_SX, TILE_SX, raster=2)

    def margin(gi, gj):
        return gi >= 38

    cog = {"compression": 8, "predictor": 3, "tile": (16, 16)}
    out = []
    rows, g = tile(-12, 8)
    out.append(single("holes_N08W012.tif", "Land, diagonal to the missing tile N07 W013 in every holes set.",
                      rows, "f32", g, **cog))
    rows, g = tile(-13, 8, sea=sea_n)
    out.append(single("holes_sea_N08W013.tif",
                      "North of the missing tile; sea (0.0) along its whole last row.",
                      rows, "f32", g, **cog))
    rows, g = tile(-12, 7, sea=sea_e)
    out.append(single("holes_sea_N07W012.tif",
                      "East of the missing tile; sea (0.0) down its whole first column.",
                      rows, "f32", g, **cog))
    rows, g = tile(-13, 8, kind="i16")
    out.append(single("holes_land_N08W013.tif", "North of the missing tile; land along its last row.",
                      rows, "i16", g, compression=5, predictor=2, rows_per_strip=7))
    rows, g = tile(-12, 7, kind="i16")
    out.append(single("holes_land_N07W012.tif", "East of the missing tile; land down its first column.",
                      rows, "i16", g, compression=5, predictor=2, rows_per_strip=7))
    rows, g = tile(-13, 8, sea=sea_part)
    out.append(single("holes_edge_N08W013.tif",
                      "North of the missing tile; its last row is sea from 12.5 W eastwards, which is all a window "
                      "near 12 W, 8 N sees, but land west of 12.5 W.",
                      rows, "f32", g, compression=5, predictor=3, rows_per_strip=7))
    rows, g = tile(-13, 8, fill=margin)
    out.append(single("hole_fill_margin.tif",
                      "N08 W013 whose last two columns hold -3.4e38, an undeclared ArcGIS fill, beside the "
                      "missing N08 W012: the margin is implausible, so the missing tile stays a void.",
                      rows, "f32", g, compression=5, rows_per_strip=7))
    return out


def mosaic() -> Fixture:
    """A GDAL-style mosaic whose gap was filled with 0.0: a block of 'sea' with straight edges."""
    rows = []
    for r in range(40):
        row = []
        for c in range(48):
            if (c >= 30 and r <= 21) or r >= 33 + mix(c, 57) % 4:
                row.append(0.0)
            else:
                row.append((5 + 9 * (36 - r) + 2 * c + mix(c // 3, r // 3, 55) % 25 + mix(c, r, 56) % 3) / 10)
        rows.append(row)
    return single(
        "mosaic_zero_fill.tif",
        "A mosaic whose missing corner was filled with 0.0: 'sea' meeting land along a straight run of 22 "
        "cells (column 29/30) and 18 cells (row 21/22), beside a ragged coast along the south edge whose "
        "longest straight run is 4 cells.",
        rows, "f32", Georef(-13.05, 8.55, ARCSEC, ARCSEC, raster=1), compression=8, predictor=3,
        rows_per_strip=7)


def utm_strip() -> Fixture:
    """This toolkit's own writer output: UTM 29N, PixelIsArea, one uncompressed strip, NaN no-data."""
    import tempfile

    from groundwater.geotiff import write_geotiff

    height, width = 9, 12
    south_first = [[terrain_dm(c, height - 1 - r, 7) / 10 for c in range(width)] for r in range(height)]
    south_first[0][0] = float("nan")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_geotiff(Path(tmp) / "utm_strip.tif", south_first, west=196020.0, north=882030.0,
                             pixel_width=30.0, epsg=32629)
        data = path.read_bytes()
    rows = south_first[::-1]
    georef = Georef(196020.0, 882030.0, 30.0, 30.0, raster=1, model=1, epsg=32629)
    entry, samples = describe(
        "utm_strip.tif", "groundwater.geotiff.write_geotiff output: read cell for cell by the raw layer, "
        "refused by the elevation layer as projected (WGS 84 / UTM zone 29N).",
        rows, "f32", georef, order="<", bigtiff=False, compression=1, predictor=1, tile=None,
        rows_per_strip=None, nodata="nan", elevation="terrain.projected")
    entry["made_by"] = "groundwater.geotiff.write_geotiff"
    return Fixture("utm_strip.tif", data, entry, samples)


def codecs() -> list[Fixture]:
    """One file per encoding a reader must undo, each on its own patch of a 3-arcsecond lattice."""
    sx = 1 / 1200
    out = []

    rows = whole_metres(patch(19, 17, 11))
    for r, c in ((4, 5), (4, 6), (10, 0)):
        rows[r][c] = -32767
    out.append(single(
        "be_lzw_p2_int16.tif",
        "Big-endian int16, LZW with horizontal differencing, strips of 7 rows, the directory at the end of "
        "the file, GDAL_NODATA -32767 as SRTM GeoTIFFs carry it.",
        rows, "i16", Georef(-11.8, 7.98, sx, sx, raster=2), order=">", compression=5, predictor=2,
        rows_per_strip=7, nodata="-32767", ifds_first=False))

    out.append(single(
        "le_lzw_p3_f64.tif",
        "Little-endian float64, LZW with the floating-point predictor, 16 x 16 tiles, PixelIsArea, a tiepoint "
        "at raster point (3, 2) rather than the corner, and GDAL_METADATA with a unit scale and zero "
        "offset, which is read.",
        metres(patch(21, 18, 12)), "f64",
        Georef(-11.7 + 3 * sx, 7.9 - 2 * sx, sx, sx, raster=1, tie_col=3, tie_row=2),
        compression=5, predictor=3, tile=(16, 16),
        metadata=metadata_xml(("SCALE", "scale", "1"), ("OFFSET", "offset", "0"), ("", "unittype", "metre"))))

    out.append(single(
        "be_deflate_p3_f32.tif",
        "Big-endian float32, DEFLATE with the floating-point predictor, one row a strip: the planes are "
        "most significant byte first whatever the byte order, which Pillow 12.3 gets wrong.",
        metres(patch(17, 13, 13)), "f32", Georef(-11.6, 8.1, sx, sx, raster=2), order=">",
        compression=8, predictor=3, rows_per_strip=1))

    rows = whole_metres(patch(23, 15, 14), offset=150)
    rows[6][3:7] = [65535] * 4
    out.append(single(
        "packbits_u16.tif",
        "uint16 PackBits strips of 7 rows, each row opening with the no-op header byte -128, and a run of "
        "no-data cells (GDAL_NODATA '65535 ' with its trailing space).",
        rows, "u16", Georef(-11.5, 8.2, sx, sx, raster=1), compression=32773, rows_per_strip=7,
        nodata="65535 ", packbits_noop=True))

    rows = metres(patch(18, 20, 15))
    for r, c in ((0, 0), (0, 1), (19, 17)):
        rows[r][c] = -9999.0
    out.append(single(
        "bigtiff_deflate_p2_f32.tif",
        "BigTIFF float32, DEFLATE with horizontal differencing of the float bit patterns, 16 x 16 tiles, "
        "GDAL_NODATA -9999: laid out as FABDEM tiles are.",
        rows, "f32", Georef(-11.4, 8.3, sx, sx, raster=1), bigtiff=True, compression=8, predictor=2,
        tile=(16, 16), nodata="-9999"))

    out.append(single(
        "bigtiff_be_lzw_p2_i32.tif",
        "Big-endian BigTIFF int32, LZW with horizontal differencing, strips of 7 rows, offsets as LONG8 and "
        "byte counts as LONG.",
        whole_metres(patch(15, 12, 16)), "i32", Georef(-11.3, 8.4, sx, sx, raster=2), order=">",
        bigtiff=True, compression=5, predictor=2, rows_per_strip=7, count_type=LONG))

    out.append(single(
        "transform_f32.tif",
        "Placed by ModelTransformation rather than scale and tiepoint, with no RasterType key (so "
        "PixelIsArea), uncompressed strips of 7 rows.",
        metres(patch(13, 9, 17)), "f32", Georef(-11.2, 8.5, sx, sx, raster=None, transform=True),
        rows_per_strip=7))

    out.append(single(
        "sparse_f32.tif",
        "Two of six 16 x 16 tiles are sparse (offset 0, byte count 0) and there is no GDAL_NODATA: GDAL "
        "reads those cells as 0; the reader voids them.",
        metres(patch(40, 24, 18)), "f32", Georef(-11.1, 8.6, sx, sx, raster=1), compression=8,
        tile=(16, 16), sparse={1, 5}))

    out.append(single(
        "padded_last_strip.tif",
        "uint32 DEFLATE (compression 32946) with horizontal differencing, strips of 7 rows: the first "
        "strip's stream is followed by 6 bytes of junk inside its byte count, and the last strip "
        "inflates to a full 7 rows though it holds 3.",
        whole_metres(patch(11, 17, 19)), "u32", Georef(-11.0, 8.7, sx, sx, raster=2), compression=32946,
        predictor=2, rows_per_strip=7, full_last_strip=True, junk_after={0: b"GWTEND"}))

    rough = [[(1000 + mix(c, r, 20) % 20000) / 10 for c in range(58)] for r in range(42)]
    out.append(single(
        "lzw_deferred_clear.tif",
        "One LZW strip whose encoder fills the table and sends 1,024 more codes before its Clear, as "
        "libtiff allows (its table holds 5,119 entries): GDAL reads it, and so must the reader.",
        rough, "f32", Georef(-10.9, 8.8, sx, sx, raster=1), compression=5, lzw_deferred=1024))

    rows = [[(dm - 1540) / 10 for dm in row] for row in patch(12, 10, 21)]
    negative_zero = ((0, 0), (2, 5), (7, 11))
    for r in range(10):
        for c in range(12):
            if (r * 7 + c * 3) % 11 == 0:
                rows[r][c] = 0.0
    for r, c in negative_zero:
        rows[r][c] = -0.0
    out.append(single(
        "negzero_f32.tif",
        "float32 with -0.0 at three cells and +0.0 at others, LZW with the floating-point predictor: the "
        "reader canonicalises -0 to +0.",
        rows, "f32", Georef(-10.8, 8.9, sx, sx, raster=2), compression=5, predictor=3, rows_per_strip=7,
        manifest={"negative_zero_cells": [list(rc) for rc in negative_zero]}))

    rows = metres(patch(12, 10, 22))
    rows[1][2], rows[5][9] = float("inf"), float("inf")
    rows[8][0], rows[8][1] = float("-inf"), float("-inf")
    out.append(single(
        "inf_f32.tif",
        "Big-endian float32 with undeclared +inf and -inf cells and no GDAL_NODATA: implausible, so voids.",
        rows, "f32", Georef(-10.7, 9.0, sx, sx, raster=1), order=">", rows_per_strip=7))

    out.append(single(
        "pred2_none.tif",
        "Uncompressed int16 with a Predictor tag of 2, which libtiff and GDAL ignore without LZW or DEFLATE: "
        "the values are stored as they are.",
        whole_metres(patch(10, 8, 23)), "i16", Georef(-10.6, 9.1, sx, sx, raster=2), predictor=2,
        rows_per_strip=8, ifds_first=False))

    plateau = [[(10 + 3 * (c // 4) + 2 * (r // 3)) for c in range(10)] for r in range(8)]
    out.append(single(
        "pred2_packbits.tif",
        "int8 PackBits with a Predictor tag of 2, ignored as with no compression: the values are stored "
        "as they are.",
        plateau, "i8", Georef(-10.5, 9.2, sx, sx, raster=2), compression=32773, predictor=2,
        rows_per_strip=4, ifds_first=False))
    return out


def overview_mask_first() -> Fixture:
    """Reduced-resolution and mask directories before the image, and an overview after it."""
    sx = 1 / 1200
    dm = patch(24, 20, 24)
    rows = metres(dm)
    half = [[dm[2 * r][2 * c] / 10 for c in range(12)] for r in range(10)]
    reduced = image(half, "f32", "<", rows_per_strip=10)
    reduced.tags[SUBFILE_TYPE] = (SHORT, [2])  # the old tag: 2 is a reduced-resolution image
    mask = image([[255] * 24 for _ in range(20)], "u8", "<", rows_per_strip=20)
    mask.tags[NEW_SUBFILE_TYPE] = (LONG, [4])
    mask.tags[PHOTOMETRIC] = (SHORT, [4])
    georef = Georef(-10.4, 9.3, sx, sx, raster=1)
    full = image(rows, "f32", "<", compression=8, predictor=3, tile=(16, 16))
    full.tags[NEW_SUBFILE_TYPE] = (LONG, [0])
    full.tags.update(georef.tags())
    overview = image(half, "f32", "<", compression=8, predictor=3, tile=(16, 16))
    overview.tags[NEW_SUBFILE_TYPE] = (LONG, [1])
    data = assemble("<", [reduced, mask, full, overview])
    entry, samples = describe(
        "overview_mask_first.tif",
        "The full image is the third directory: before it a reduced-resolution image (old SubfileType 2) "
        "and a mask (NewSubfileType 4), after it an overview (NewSubfileType 1). GDAL opens it as "
        "GTIFF_DIR:3.",
        rows, "f32", georef, order="<", bigtiff=False, compression=8, predictor=3, tile=(16, 16),
        rows_per_strip=None, nodata=None, ifd_index=2)
    return Fixture("overview_mask_first.tif", data, entry, samples)


def nodata_variants() -> list[Fixture]:
    sx = 1 / 1200
    out = []
    rows = metres(patch(12, 9, 31))
    rows[0][0] = rows[4][7] = rows[8][11] = float("nan")
    out.append(single("nodata_nan.tif", "float32, GDAL_NODATA 'nan', three NaN cells.",
                      rows, "f32", Georef(-10.3, 7.5, sx, sx, raster=1), compression=5, rows_per_strip=7,
                      nodata="nan"))
    rows = metres(patch(12, 9, 32))
    rows[3][3] = rows[3][4] = float("-inf")
    out.append(single("nodata_neg_inf.tif",
                      "float64, GDAL_NODATA '-inf': the two -inf cells are no data, not implausible.",
                      rows, "f64", Georef(-10.2, 7.6, sx, sx, raster=2), tile=(16, 16), nodata="-inf"))
    rows = metres(patch(12, 9, 33))
    for row in rows:
        row[0] = row[1] = -FLT_MAX
    out.append(single("nodata_arcgis_float_max.tif",
                      "float32, GDAL_NODATA '-3.40282346639e+038' as ArcGIS writes it, which rounds to "
                      "-FLT_MAX once clamped, the value of its two-column fill margin.",
                      rows, "f32", Georef(-10.1, 7.7, sx, sx, raster=1), compression=8, predictor=2,
                      rows_per_strip=7, nodata="-3.40282346639e+038"))
    out.append(single("nodata_empty.tif",
                      "8-bit samples with no SampleFormat tag (so unsigned) and an empty GDAL_NODATA: no no-data "
                      "value, so the zero cells are ground at 0 m.",
                      [[max(0, v) for v in row] for row in whole_metres(patch(12, 9, 34), offset=-151)],
                      "u8", Georef(-10.0, 7.8, sx, sx, raster=1),
                      rows_per_strip=9, nodata="", sample_format_tag=False))
    out.append(single("nodata_abc.tif", "int8 with GDAL_NODATA 'abc', which is not a number.",
                      [[(r + c) % 50 for c in range(12)] for r in range(9)], "i8",
                      Georef(-9.9, 7.9, sx, sx, raster=1), rows_per_strip=9, nodata="abc",
                      raw="terrain.nodata_unreadable", elevation=None))
    return out


def refusals() -> list[Fixture]:
    """One file for each way the reader refuses (spec section 2.11), each otherwise ordinary."""
    sx = 1 / 1200
    g = Georef(-12.2, 7.2, sx, sx, raster=1)
    small = metres(patch(8, 6, 41))
    out = []

    def refuse(name, purpose, refusal, rows=small, kind="f32", georef=g, layer="raw", **options):
        raw, elevation = (refusal, None) if layer == "raw" else ("read", refusal)
        return single(name, purpose, rows, kind, georef, raw=raw, elevation=elevation, **options)

    out.append(refuse("refuse_jpeg.tif", "Compression 7 (JPEG).", "terrain.compression", compression=7))
    out.append(refuse(
        "refuse_rotated.tif", "A ModelTransformation with a shear term: not north-up.", "terrain.rotated",
        tags={MODEL_TRANSFORMATION: (DOUBLE, [sx, 1e-5, 0.0, -12.2, 0.0, -sx, 0.0, 7.2,
                                              0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])},
        drop=(MODEL_PIXEL_SCALE, MODEL_TIEPOINT)))
    out.append(refuse(
        "refuse_old_lzw.tif",
        "Genuine pre-1992 LZW (codes least significant bit first, widening late), which libtiff and GDAL "
        "still read: refused by name.", "terrain.old_lzw",
        rows=whole_metres(patch(18, 16, 42)), kind="i16", compression=5, old_lzw=True))
    two = [[v for c in range(8) for v in (terrain_dm(c, r, 43) // 10, terrain_dm(c, r, 44) // 10)]
           for r in range(6)]
    out.append(refuse("refuse_two_bands.tif", "Two samples to a cell.", "terrain.bands", rows=two, kind="i16",
                      samples=2))
    out.append(refuse("refuse_fill_order_2.tif", "FillOrder 2: bits stored in reverse order.",
                      "terrain.fill_order", tags={FILL_ORDER: (SHORT, [2])}))
    out.append(refuse("refuse_no_georeference.tif",
                      "GeoKeys but neither scale and tiepoint nor a transformation.", "terrain.no_georeference",
                      drop=(MODEL_PIXEL_SCALE, MODEL_TIEPOINT)))
    out.append(refuse(
        "refuse_control_points.tif", "Three tiepoints and no pixel scale: placed by control points.",
        "terrain.control_points",
        tags={MODEL_TIEPOINT: (DOUBLE, [0.0, 0.0, 0.0, -12.2, 7.2, 0.0, 7.0, 0.0, 0.0, -12.19, 7.2, 0.0,
                                        0.0, 5.0, 0.0, -12.2, 7.19, 0.0])},
        drop=(MODEL_PIXEL_SCALE,)))
    out.append(refuse("refuse_scaled.tif", "GDAL_METADATA with a scale of 0.1.", "terrain.scaled",
                      rows=whole_metres(patch(8, 6, 45)), kind="i16",
                      metadata=metadata_xml(("SCALE", "scale", "0.1"), ("OFFSET", "offset", "0"))))
    whole = single("refuse_truncated.tif", "", small, "f32", g, ifds_first=False)
    cut = len(whole.data) - 120
    entry = dict(whole.entry, purpose="Cut off part-way through its directory, which ends the file.",
                 raw="terrain.ends_early", elevation=None, truncated_at=cut)
    out.append(Fixture("refuse_truncated.tif", whole.data[:cut], entry, whole.samples))
    whole = single("refuse_truncated_data.tif", "", metres(patch(20, 18, 46)), "f32", g, compression=5,
                   tile=(16, 16))
    tiles = directories(whole.data)[2][0]
    cut = tiles[TILE_OFFSETS][2][-1] + tiles[TILE_BYTE_COUNTS][2][-1] // 2
    entry = dict(whole.entry, purpose="Cut off part-way through its last tile, as an interrupted download is.",
                 raw="terrain.ends_early", elevation=None, truncated_at=cut)
    out.append(Fixture("refuse_truncated_data.tif", whole.data[:cut], entry, whole.samples))
    whole = single("refuse_bad_adler.tif", "", small, "f32", g, compression=8, rows_per_strip=3)
    first = whole_strip_end(whole.data)
    corrupt = bytearray(whole.data)
    corrupt[first - 1] ^= 0x01
    entry = dict(whole.entry, purpose="DEFLATE strips whose first stream's Adler-32 has one bit flipped.",
                 raw="terrain.block_damaged", elevation=None)
    out.append(Fixture("refuse_bad_adler.tif", bytes(corrupt), entry, whole.samples))
    out.append(loop_or_overviews("refuse_ifd_loop.tif", loop=True))
    out.append(loop_or_overviews("refuse_overview_only.tif", loop=False))
    out.append(refuse("refuse_epsg_3857.tif", "Projected in EPSG 3857 (WGS 84 / Pseudo-Mercator).",
                      "terrain.projected", layer="elevation",
                      georef=Georef(-1358136.0, 803712.0, 90.0, 90.0, raster=1, model=1, epsg=3857)))
    out.append(refuse("refuse_no_crs.tif", "Georeferenced but with no GeoKey directory.", "terrain.no_crs",
                      layer="elevation", georef=Georef(-12.2, 7.2, sx, sx, raster=None, model=None)))
    out.append(refuse("refuse_zero_rows_per_strip.tif", "RowsPerStrip 0.", "terrain.bad_tag",
                      tags={ROWS_PER_STRIP: (SHORT, [0])}))
    out.append(refuse("refuse_zero_tile_width.tif", "TileWidth 0.", "terrain.bad_tag", tile=(16, 16),
                      tags={TILE_WIDTH: (SHORT, [0])}))
    out.append(refuse("refuse_polar.tif", "Geographic, with rows from 89.6 N down to 89.35 N.",
                      "terrain.polar", layer="elevation", georef=Georef(20.0, 89.6, 0.05, 0.05, raster=2)))
    return out


def whole_strip_end(data: bytes) -> int:
    """Where the first strip of a little-endian classic file ends: offset plus byte count."""
    ifd = struct.unpack_from("<I", data, 4)[0]
    count = struct.unpack_from("<H", data, ifd)[0]
    found = {}
    for k in range(count):
        tag, kind, n, value = struct.unpack_from("<HHII", data, ifd + 2 + 12 * k)
        if tag in (STRIP_OFFSETS, STRIP_BYTE_COUNTS):
            found[tag] = value if n == 1 else struct.unpack_from("<I", data, value)[0]
    return found[STRIP_OFFSETS] + found[STRIP_BYTE_COUNTS]


def loop_or_overviews(name: str, *, loop: bool) -> Fixture:
    """Overview and mask directories only; with ``loop`` the chain returns to its start."""
    sx = 1 / 1200
    dm = patch(12, 10, 47)
    overview = image(metres(dm), "f32", "<", rows_per_strip=10)
    overview.tags[NEW_SUBFILE_TYPE] = (LONG, [1])
    overview.tags.update(Georef(-12.1, 7.3, sx, sx, raster=1).tags())
    reduced = image(metres(dm), "f32", "<", rows_per_strip=10)
    reduced.tags[SUBFILE_TYPE] = (SHORT, [2])
    mask = image([[255] * 12 for _ in range(10)], "u8", "<", rows_per_strip=10)
    mask.tags[NEW_SUBFILE_TYPE] = (LONG, [4])
    mask.tags[PHOTOMETRIC] = (SHORT, [4])
    if loop:
        data = assemble("<", [overview, mask], loop_to=0)
        purpose = ("An overview and a mask whose chain points back to the overview: no full image, "
                   "and the walk must stop.")
        refusal = "terrain.directory_loop"
    else:
        data = assemble("<", [overview, reduced, mask])
        purpose = ("An overview (NewSubfileType 1), a reduced image (old SubfileType 2) and a mask "
                   "(NewSubfileType 4): no full-resolution image.")
        refusal = "terrain.no_full_image"
    entry = {"purpose": purpose, "raw": refusal, "elevation": None, "byte_order": "<", "bigtiff": False,
             "directories": 2 if loop else 3}
    return Fixture(name, data, entry)


# --- the GDAL-written set ------------------------------------------------------------------

@dataclass
class GdalSpec:
    """A file GDAL writes with ``--gdal``: what is asked of it and what it should hold."""

    name: str
    purpose: str
    kind: str
    rows: list
    order: str
    compression: int
    predictor: int
    tile: tuple | None
    rows_per_strip: int | None
    georef: Georef
    nodata: str | None
    creation: dict = field(default_factory=dict)
    driver: str = "GTiff"


def gdal_specs() -> list[GdalSpec]:
    sx = 1 / 1200
    rows = metres(patch(40, 40, 51))
    i16 = whole_metres(patch(33, 27, 53))
    i16[3][4] = i16[3][5] = -32767
    return [
        GdalSpec("gdal_cog_deflate_p3_f32.tif",
                 "GDAL's COG driver: DEFLATE with the floating-point predictor, 16 x 16 tiles, PixelIsPoint, "
                 "overviews after the image and GDAL's own ghost header.",
                 "f32", rows, "<", 8, 3, (16, 16), None,
                 Georef(-9.8, 8.0, ARCSEC, ARCSEC, raster=2), None,
                 {"COMPRESS": "DEFLATE", "PREDICTOR": "YES", "BLOCKSIZE": "16", "LEVEL": "9"}, "COG"),
        GdalSpec("gdal_lzw_p2_f32.tif",
                 "GDAL GTiff: LZW with horizontal differencing of float32 bit patterns, strips of 8 rows.",
                 "f32", metres(patch(37, 29, 52)), "<", 5, 2, None, 8,
                 Georef(-9.7, 8.1, sx, sx, raster=1), None,
                 {"COMPRESS": "LZW", "PREDICTOR": "2", "BLOCKYSIZE": "8"}),
        GdalSpec("gdal_mm_packbits_i16.tif",
                 "GDAL GTiff, big-endian: int16 PackBits strips of 5 rows, GDAL_NODATA -32767.",
                 "i16", i16, ">", 32773, 1, None, 5,
                 Georef(-9.6, 8.2, sx, sx, raster=2), "-32767",
                 {"COMPRESS": "PACKBITS", "ENDIANNESS": "BIG", "BLOCKYSIZE": "5"}),
        GdalSpec("gdal_mm_lzw_p3_tiled_f64.tif",
                 "GDAL GTiff, big-endian: float64 LZW with the floating-point predictor in 16 x 16 tiles.",
                 "f64", metres(patch(35, 22, 54)), ">", 5, 3, (16, 16), None,
                 Georef(-9.5, 8.3, sx, sx, raster=1), None,
                 {"COMPRESS": "LZW", "PREDICTOR": "3", "ENDIANNESS": "BIG", "TILED": "YES",
                  "BLOCKXSIZE": "16", "BLOCKYSIZE": "16"}),
    ]


def gdal_entry(spec: GdalSpec) -> tuple[dict, bytes]:
    entry, samples = describe(
        spec.name, spec.purpose, spec.rows, spec.kind, spec.georef, order=spec.order, bigtiff=False,
        compression=spec.compression, predictor=spec.predictor, tile=spec.tile,
        rows_per_strip=spec.rows_per_strip, nodata=spec.nodata)
    entry["made_by"] = "GDAL, through rasterio (make_dem_fixture.py --gdal)"
    entry["gdal_creation_options"] = spec.creation
    return entry, samples


def write_gdal_set(directory: Path) -> None:
    """Rewrite the GDAL-written files with rasterio. Development only: nothing else needs GDAL."""
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.shutil import copy as gdal_copy
    from rasterio.transform import Affine

    for spec in gdal_specs():
        dtype = {"f32": "float32", "f64": "float64", "i16": "int16"}[spec.kind]
        array = np.array(spec.rows, dtype=dtype)
        g = spec.georef
        # rasterio takes the corner of the first cell; GDAL writes it back as the
        # centre when the raster is PixelIsPoint
        x0, y0 = g.centres()
        transform = Affine(g.sx, 0.0, x0 - 0.5 * g.sx, 0.0, -g.sy, y0 + 0.5 * g.sy)
        profile = {"driver": "GTiff", "width": array.shape[1], "height": array.shape[0], "count": 1,
                   "dtype": dtype, "crs": f"EPSG:{g.epsg}", "transform": transform}
        if spec.nodata is not None:
            profile["nodata"] = float(spec.nodata)
        target = directory / spec.name
        if spec.driver == "COG":
            with MemoryFile() as memory:
                with memory.open(**profile) as source:
                    source.write(array, 1)
                    source.update_tags(AREA_OR_POINT="Point" if g.raster == 2 else "Area")
                with memory.open() as source:
                    gdal_copy(source, str(target), driver="COG", **spec.creation)
        else:
            with rasterio.open(target, "w", **profile, **spec.creation) as sink:
                sink.update_tags(AREA_OR_POINT="Point" if g.raster == 2 else "Area")
                sink.write(array, 1)
        print(f"wrote {target} ({target.stat().st_size} bytes)")


# --- the whole set --------------------------------------------------------------------------

SETS = {
    "copernicus_pair": {
        "files": ["Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif"],
        "expect": "Joined across 11 W without a seam or a repeated column; both recognised as copernicus_glo30."},
    "renamed": {
        "files": ["n08w012.tif", "n08w011.tif"],
        "expect": "Unidentified and never credited; n08w011.tif prompts the operator (GLO-30 fingerprint)."},
    "overlap_agree": {
        "files": ["overlap_north.tif", "overlap_south_agrees.tif"],
        "expect": "Joined; the shared row is kept once, from the first file in plan order."},
    "overlap_disagree": {
        "files": ["overlap_north.tif", "overlap_south_disagrees.tif"],
        "expect": "terrain.join_disagree at 3 shared cells, by up to 1.2 m."},
    "overlap_fill_edge": {
        "files": ["overlap_north.tif", "overlap_south_fill_edge.tif"],
        "expect": "Joined; the shared row reads overlap_north.tif's heights, the -32767 cells being implausible."},
    "products": {
        "files": ["Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif", "Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif"],
        "rename": {"Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif": "n08_w011_1arc_v3.tif"},
        "expect": "terrain.join_products: under an EarthExplorer SRTM name the second tile is identified as srtm, "
                  "and files of two products are not joined."},
    "phase": {"files": ["overlap_north.tif", "phase_half_cell.tif"], "expect": "terrain.join_phase."},
    "spacing": {"files": ["overlap_north.tif", "spacing_mismatch.tif"], "expect": "terrain.join_spacing."},
    "holes_sea": {
        "files": ["holes_N08W012.tif", "holes_sea_N08W013.tif", "holes_sea_N07W012.tif"],
        "declare": "copernicus_glo30",
        "expect": "The missing N07 W013 is assumed sea: every finite sample of its supplied neighbours' full "
                  "shared edges is 0.0."},
    "holes_land": {
        "files": ["holes_N08W012.tif", "holes_land_N08W013.tif", "holes_land_N07W012.tif"],
        "declare": "copernicus_glo30",
        "expect": "The missing N07 W013 stays a void: its neighbours' shared edges are land."},
    "holes_edge": {
        "files": ["holes_N08W012.tif", "holes_edge_N08W013.tif", "holes_sea_N07W012.tif"],
        "declare": "copernicus_glo30",
        "expect": "The missing N07 W013 stays a void: N08 W013's full last row holds land west of 12.5 W, "
                  "though a window near 12 W, 8 N (half-width under 20 cells) sees only sea on it."},
    "hole_fill_margin": {
        "files": ["hole_fill_margin.tif"],
        "declare": "copernicus_glo30",
        "expect": "The missing N08 W012 stays a void, in a window near 12 W, 8.5 N that meets only it and "
                  "N08 W013: the shared edge is all implausible fill, so it has no finite sample at all."},
    "mosaic": {
        "files": ["mosaic_zero_fill.tif"],
        "expect": "With sea_straight_edge_cells from 5 to 22, the straight-edged 0.0 block is a filled gap, not "
                  "sea, and the ragged southern coast (its longest straight run is 4 cells) stays sea."},
}


def build() -> dict[str, Fixture]:
    """Every file this script writes, by name, in memory."""
    fixtures = copernicus_pair() + joins() + holes() + [mosaic(), utm_strip()] + codecs()
    fixtures += [overview_mask_first()] + nodata_variants() + refusals()
    by_name = {f.name: f for f in fixtures}
    if len(by_name) != len(fixtures):
        raise AssertionError("two fixtures share a name")
    return by_name


def manifest(fixtures: dict[str, Fixture]) -> bytes:
    """MANIFEST.json, one line to a file so that a change to one file is a change to one line."""
    files = {name: f.entry for name, f in fixtures.items()}
    for spec in gdal_specs():
        files[spec.name] = gdal_entry(spec)[0]

    def line(value) -> str:
        return json.dumps(value, ensure_ascii=True, allow_nan=False)

    about = [
        ("Written by make_dem_fixture.py, which says how each file was made; made_by is given only for a file "
         "it did not write itself."),
        ("raw and elevation: what the raw GeoTIFF layer and the elevation layer must do with the file, 'read' "
         "or the catalogued refusal of spec section 2.11; elevation is null when the raw layer refuses."),
        ("The layout keys are GeoTiffLayout's (spec section 2.3). The predictor is applied only with "
         "compression 5, 8 or 32946. raster_type 1 is PixelIsArea (also when the key is absent), 2 PixelIsPoint. "
         "ifd_index, samples_per_pixel and georeference are given only when they are not 0, 1 and scale and "
         "tiepoint."),
        ("x0 and y0 are the centres of column 0 and row 0 (row 0 north) by the expressions of spec section 2.4; "
         "cell (i, j) is at x0 + i*sx, y0 - j*sy."),
        ("nodata is GDAL_NODATA's text without its NUL; nodata_value is that text parsed and cast to the sample "
         "type by spec section 2.5 ('no cell' when it cannot match an integer sample)."),
        ("samples_sha256: SHA-256 of every sample, north row first, each little-endian in its own type, as GDAL "
         "reads the file with masked=False; a sparse block reads as 0 there, though the reader voids it."),
        "voids: the cells the per-sample rule of spec section 2.5 voids (bounds -1000 and 9000 m), when any.",
        "sets: files meant to be read together; declare is the source the operator declares for the set.",
    ]
    out = ['{"about": ' + line(about) + ',\n "files": {\n']
    out.append(",\n".join(f"  {line(name)}: {line(entry)}" for name, entry in sorted(files.items())))
    out.append('\n },\n "sets": {\n')
    out.append(",\n".join(f"  {line(name)}: {line(entry)}" for name, entry in SETS.items()))
    out.append("\n }\n}\n")
    return "".join(out).encode("ascii")


# --- checking -------------------------------------------------------------------------------

def directories(data: bytes) -> tuple[str, bool, list[dict]]:
    """Every directory in the chain: {tag: (type, count, values)}, with its offset under None."""
    order = "<" if data[:2] == b"II" else ">"
    bigtiff = struct.unpack_from(order + "H", data, 2)[0] == 43
    at = struct.unpack_from(order + ("Q" if bigtiff else "I"), data, 8 if bigtiff else 4)[0]
    seen, out = set(), []
    while at and at not in seen and at < len(data):
        seen.add(at)
        count = struct.unpack_from(order + ("Q" if bigtiff else "H"), data, at)[0]
        pos = at + (8 if bigtiff else 2)
        tags = {None: at}
        for _ in range(count):
            if bigtiff:
                tag, kind, n = struct.unpack_from(order + "HHQ", data, pos)
                field_, inline = pos + 12, 8
            else:
                tag, kind, n = struct.unpack_from(order + "HHI", data, pos)
                field_, inline = pos + 8, 4
            size = TYPE_SIZE.get(kind, 1) * n
            where = field_ if size <= inline else struct.unpack_from(order + ("Q" if bigtiff else "I"),
                                                                     data, field_)[0]
            raw = data[where:where + size]
            if kind in (ASCII, UNDEFINED, BYTE):
                values = raw
            elif kind in (RATIONAL, SRATIONAL):
                values = struct.unpack(f"{order}{2 * n}{'I' if kind == RATIONAL else 'i'}", raw)
            else:
                values = struct.unpack(f"{order}{n}{TYPE_FORMAT[kind]}", raw)
            tags[tag] = (kind, n, values)
            pos += 20 if bigtiff else 12
        out.append(tags)
        at = struct.unpack_from(order + ("Q" if bigtiff else "I"), data, pos)[0]
    return order, bigtiff, out


def directories_first(found: list[dict]) -> bool:
    """Whether every directory comes before every block, as in a COG."""
    blocks = [o for d in found for tag in (STRIP_OFFSETS, TILE_OFFSETS) if tag in d for o in d[tag][2] if o]
    return max(d[None] for d in found) < min(blocks, default=0)


def _inflated(block: bytes):
    """What a zlib stream says, independent of how the encoder chose its bytes."""
    header_ok = len(block) >= 2 and block[0] & 0x0F == 8 and (block[0] << 8 | block[1]) % 31 == 0
    stream = zlib.decompressobj(-15)
    out = stream.decompress(block[2:])
    tail = stream.unused_data
    checksum = int.from_bytes(tail[:4], "big") ^ zlib.adler32(out) if len(tail) >= 4 else None
    return header_ok, stream.eof, out, checksum, tail[4:]


def same_deflate_file(committed: bytes, rebuilt: bytes) -> list[str]:
    """Held to tags and decoded blocks: every entry but the block offsets and counts, every block's output."""
    problems = []
    a_order, a_big, a = directories(committed)
    b_order, b_big, b = directories(rebuilt)
    if (a_order, a_big, len(a)) != (b_order, b_big, len(b)):
        return ["the byte order, the TIFF version or the number of directories differs"]
    start = 16 if a_big else 8
    ghost = ghost_header()
    has_ghost = [data[start:start + len(ghost)] == ghost for data in (committed, rebuilt)]
    if has_ghost[0] != has_ghost[1]:
        problems.append("one has GDAL's ghost header and the other has not")
    if directories_first(a) != directories_first(b):
        problems.append("one keeps its directories before its data and the other after")
    for k, (x, y) in enumerate(zip(a, b, strict=True)):
        skip = {None, STRIP_OFFSETS, STRIP_BYTE_COUNTS, TILE_OFFSETS, TILE_BYTE_COUNTS}
        if {t: v for t, v in x.items() if t not in skip} != {t: v for t, v in y.items() if t not in skip}:
            problems.append(f"directory {k}: the tags differ")
        for offsets_tag, counts_tag in ((STRIP_OFFSETS, STRIP_BYTE_COUNTS), (TILE_OFFSETS, TILE_BYTE_COUNTS)):
            if offsets_tag not in x:
                continue
            blocks = []
            for data, d, wrapped in ((committed, x, has_ghost[0]), (rebuilt, y, has_ghost[1])):
                offsets, counts = d[offsets_tag][2], d[counts_tag][2]
                listed = []
                for o, n in zip(offsets, counts, strict=True):
                    block = data[o:o + n]
                    if wrapped and n and (data[o - 4:o] != struct.pack("<I", n) or
                                          data[o + n:o + n + 4] != block[-4:]):
                        problems.append(f"directory {k}: a block's leader or trailer is wrong")
                    deflate = d[COMPRESSION][2][0] in (8, 32946)
                    listed.append(("sparse",) if o == 0 and n == 0 else
                                  _inflated(block) if deflate else block)
                blocks.append(listed)
            if blocks[0] != blocks[1]:
                problems.append(f"directory {k}: a block decodes differently")
    return problems


def check(directory: Path = DEM) -> list[str]:
    """Rebuild in memory and compare with what is committed; an empty list means they agree."""
    fixtures = build()
    problems = []
    gdal_names = {spec.name for spec in gdal_specs()}
    present = {p.name for p in directory.iterdir()} if directory.is_dir() else set()
    for name in sorted(present - set(fixtures) - gdal_names - {MANIFEST}):
        problems.append(f"{name}: committed but not written by this script")
    for name in sorted(gdal_names - present):
        problems.append(f"{name}: missing; run with --gdal")
    for name, fixture in fixtures.items():
        path = directory / name
        if not path.is_file():
            problems.append(f"{name}: missing")
            continue
        committed = path.read_bytes()
        source = fixture.entry.get("same_bytes_as")
        if source and committed != (directory / source).read_bytes():
            problems.append(f"{name}: not the same bytes as {source}")
        if fixture.entry.get("compression") not in (8, 32946):
            if committed != fixture.data:
                problems.append(f"{name}: differs from what the script writes")
        else:
            problems += [f"{name}: {p}" for p in same_deflate_file(committed, fixture.data)]
    path = directory / MANIFEST
    if not path.is_file() or path.read_bytes() != manifest(fixtures):
        problems.append(f"{MANIFEST}: differs from what the script writes")
    return problems


def write(directory: Path = DEM) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fixtures = build()
    for name, fixture in fixtures.items():
        (directory / name).write_bytes(fixture.data)
    (directory / MANIFEST).write_bytes(manifest(fixtures))
    total = sum(p.stat().st_size for p in directory.iterdir())
    print(f"wrote {len(fixtures)} files and {MANIFEST} to {directory} ({total} bytes in the directory)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="rebuild in memory and compare")
    parser.add_argument("--gdal", action="store_true", help="rewrite the GDAL-written files (needs rasterio)")
    args = parser.parse_args(argv)
    if args.check:
        problems = check()
        for problem in problems:
            print(problem)
        print("the committed fixtures are what this script writes" if not problems else
              f"{len(problems)} difference(s)")
        return 1 if problems else 0
    if args.gdal:
        write_gdal_set(DEM)
        return 0
    write()
    return 0


if __name__ == "__main__":
    sys.exit(main())

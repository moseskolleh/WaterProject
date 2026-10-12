"""A GeoTIFF writer, so an interpolated surface survives being looked at.

The survey maps in :mod:`groundwater.mapping.maps` compute a real grid -
apparent resistivity, overburden, depth to bedrock, a drill-target score -
draw it, and used to throw the grid away. The picture answers "what does
it look like"; it cannot answer "what is the value at the borehole",
"contour this at 5 m", or "show it under satellite imagery". A raster
can, in any GIS, for as long as the file is kept.

Writing one needs no dependency. A single-band float32 GeoTIFF is a TIFF
header, one image file directory, and three GeoTIFF tags saying where the
corner is and how big a pixel is - a few hundred bytes of structure
around numbers the map already has. rasterio would do it too, but it
brings GDAL, a native geospatial library, into every install of a
package whose runtime dependencies are also what the WebAssembly build
has to load in a browser. The QR encoder in this toolkit exists for the
same reason and is held to the same standard: the output is read back by
an independent reader rather than checked by inspection, because a
raster that is wrong in its georeferencing still opens perfectly
happily, in the wrong place.

What is written
---------------
Uncompressed, one strip, IEEE float32, ``PixelIsArea``, with NaN as the
nodata value so the ground outside the surveyed hull stays absent rather
than reading as zero - a zero-metre overburden is a statement, and not
one the survey made.

The projected CRS is written as an EPSG code in the GeoKey directory, so
the file lands in the right place without carrying a projection string
this toolkit would have to keep correct.

What is read
------------
The same module reads GeoTIFFs too, because an elevation model arrives as
one (PLAN.md step 4.1): Copernicus GLO-30 and FABDEM tiles, SRTM from
EarthExplorer, a clip saved from QGIS. The reader knows TIFF and GeoTIFF,
not elevation: classic and BigTIFF, either byte order, strips and tiles,
DEFLATE, LZW and PackBits, the two predictors, 8- to 32-bit integers and
32- and 64-bit floats, one band, in any coordinate system - so that what
:func:`write_geotiff` writes reads back cell for cell. What makes a file
an elevation model the toolkit takes is decided a layer up, in
:mod:`groundwater.mapping.elevation`.

``docs/js/gwt-core.js`` carries the same reader for the browser, rule for
rule, and the parity suite holds the two to the same layout, the same
cells and the same refusals. Where GDAL reads a legal file one way, both
read it that way; where a file is broken, both refuse it with the same
sentence from ``data/text/terrain.yaml`` rather than with whatever a
library happens to say. Reading is split so a window can be read without
the rest of a 48 MB tile: :func:`geotiff_layout` says which bytes it
still needs to describe the file, :func:`block_ranges` which blocks a
window meets, and :func:`decode_block` turns one block into heights.
"""

from __future__ import annotations

import functools
import re
import struct
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # numpy is imported where it is used, so the writer's import stays light
    import numpy as np

__all__ = [
    "GeoTiffError",
    "GeoTiffLayout",
    "GeoTiffRaster",
    "block_ranges",
    "decode_block",
    "geotiff_layout",
    "open_geotiff",
    "read_geotiff",
    "utm_epsg",
    "write_geotiff",
]

# TIFF field types
_ASCII = 2
_SHORT = 3
_LONG = 4
_DOUBLE = 12

# The tags a reader needs to make sense of a single-band float raster. The
# TIFF specification requires them in ascending order, which is enforced
# by sorting when the directory is assembled rather than by writing them in
# the right order by hand.
_IMAGE_WIDTH = 256
_IMAGE_LENGTH = 257
_BITS_PER_SAMPLE = 258
_COMPRESSION = 259
_PHOTOMETRIC = 262
_STRIP_OFFSETS = 273
_SAMPLES_PER_PIXEL = 277
_ROWS_PER_STRIP = 278
_STRIP_BYTE_COUNTS = 279
_PLANAR_CONFIG = 284
_SAMPLE_FORMAT = 339
_MODEL_PIXEL_SCALE = 33550
_MODEL_TIEPOINT = 33922
_GEO_KEY_DIRECTORY = 34735
_GDAL_NODATA = 42113

# GeoTIFF keys (GeoTIFF 1.0, section 6.2)
_GT_MODEL_TYPE = 1024  # 1 = projected
_GT_RASTER_TYPE = 1025  # 1 = PixelIsArea
_PROJECTED_CS_TYPE = 3072  # an EPSG projected CRS code


def utm_epsg(zone: int, hemisphere: str = "N") -> int:
    """The EPSG code for a WGS84 UTM zone.

    32601-32660 north, 32701-32760 south. Sierra Leone is 32628 and
    32629.
    """
    if not 1 <= zone <= 60:
        raise ValueError(f"UTM zone {zone} is not between 1 and 60")
    base = 32700 if hemisphere.upper().startswith("S") else 32600
    return base + zone


def _entry(tag: int, field_type: int, count: int, payload: bytes) -> bytes:
    """One 12-byte directory entry whose value already fits in four bytes."""
    return struct.pack("<HHI", tag, field_type, count) + payload.ljust(4, b"\x00")


def _short_entry(tag: int, value: int) -> bytes:
    # a SHORT is written into the first two bytes of the value field
    return _entry(tag, _SHORT, 1, struct.pack("<H", value))


def _long_entry(tag: int, value: int) -> bytes:
    return _entry(tag, _LONG, 1, struct.pack("<I", value))


def write_geotiff(
    path: str | Path,
    grid,
    *,
    west: float,
    north: float,
    pixel_width: float,
    pixel_height: float | None = None,
    epsg: int,
) -> Path:
    """Write ``grid`` as a single-band float32 GeoTIFF.

    ``grid`` is indexed ``[row][column]`` with **row 0 at the south**, the
    way :func:`numpy.meshgrid` and matplotlib produce it, and is flipped
    on the way out because TIFF rows run north to south. Getting that
    backwards produces a mirrored raster that still opens, which is why
    the tests check a corner value rather than the shape.

    ``west`` and ``north`` are the outer edge of the top-left pixel, not
    its centre: ``PixelIsArea``, as GDAL writes by default.
    """
    import numpy as np

    array = np.asarray(grid, dtype="<f4")
    if array.ndim != 2:
        raise ValueError(f"a raster needs a two-dimensional grid, got {array.ndim}")
    height, width = array.shape
    if height == 0 or width == 0:
        raise ValueError("refusing to write an empty raster")
    if pixel_height is None:
        pixel_height = pixel_width
    pixels = np.flipud(array).tobytes()

    geo_keys = [
        1, 1, 0, 3,  # version 1.1.0, three keys
        _GT_MODEL_TYPE, 0, 1, 1,
        _GT_RASTER_TYPE, 0, 1, 1,
        _PROJECTED_CS_TYPE, 0, 1, int(epsg),
    ]
    nodata = b"nan\x00"

    # Tag, type, count, payload. Whether a payload sits in its own entry or
    # after the directory is decided below by its length, not by hand: TIFF
    # requires four bytes or fewer to sit in the value field, and a reader
    # given an offset there follows it into whatever is at that address.
    # "nan" with its terminator is exactly four bytes; written as an offset
    # it read back as a nodata of 0.0, which is a number a survey could have
    # produced.
    values = [
        (_MODEL_PIXEL_SCALE, _DOUBLE, 3,
         struct.pack("<3d", float(pixel_width), float(pixel_height), 0.0)),
        (_MODEL_TIEPOINT, _DOUBLE, 6,
         struct.pack("<6d", 0.0, 0.0, 0.0, float(west), float(north), 0.0)),
        (_GEO_KEY_DIRECTORY, _SHORT, len(geo_keys),
         struct.pack(f"<{len(geo_keys)}H", *geo_keys)),
        (_GDAL_NODATA, _ASCII, len(nodata), nodata),
    ]
    out_of_line = [v for v in values if len(v[3]) > 4]
    fits_inline = [v for v in values if len(v[3]) <= 4]

    inline = [
        _long_entry(_IMAGE_WIDTH, width),
        _long_entry(_IMAGE_LENGTH, height),
        _short_entry(_BITS_PER_SAMPLE, 32),
        _short_entry(_COMPRESSION, 1),  # none
        _short_entry(_PHOTOMETRIC, 1),  # BlackIsZero
        _short_entry(_SAMPLES_PER_PIXEL, 1),
        _long_entry(_ROWS_PER_STRIP, height),  # the whole image, one strip
        _long_entry(_STRIP_BYTE_COUNTS, len(pixels)),
        _short_entry(_PLANAR_CONFIG, 1),
        _short_entry(_SAMPLE_FORMAT, 3),  # IEEE floating point
    ]

    # The directory has to be sized before the offsets into what follows it
    # can be known, and every entry counts: sizing it for one more than is
    # written pushes every offset past its data, which GDAL reports as a
    # missing CRS and a nodata of 0.0 rather than as a broken file.
    entry_count = len(inline) + len(values) + 1  # and StripOffsets
    cursor = 8 + 2 + 12 * entry_count + 4
    offsets = {}
    for tag, _, _, payload in out_of_line:
        offsets[tag] = cursor
        cursor += len(payload) + (len(payload) % 2)  # word-aligned
    strip_offset = cursor

    entries = inline + [_long_entry(_STRIP_OFFSETS, strip_offset)]
    for tag, field_type, count, payload in fits_inline:
        entries.append(_entry(tag, field_type, count, payload))
    for tag, field_type, count, _ in out_of_line:
        entries.append(_entry(tag, field_type, count,
                              struct.pack("<I", offsets[tag])))
    entries.sort(key=lambda raw: struct.unpack_from("<H", raw)[0])
    if len(entries) != entry_count:
        raise AssertionError(
            f"the directory was sized for {entry_count} entries and "
            f"{len(entries)} were written"
        )

    body = bytearray()
    body += struct.pack("<2sHI", b"II", 42, 8)
    body += struct.pack("<H", len(entries))
    for raw in entries:
        body += raw
    body += struct.pack("<I", 0)  # no second directory
    for _, _, _, payload in out_of_line:
        body += payload
        if len(payload) % 2:
            body += b"\x00"
    body += pixels

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(body))
    return path


# ------------------------------------------------------------------ codecs
#
# The three compressions an elevation model arrives in: DEFLATE (Copernicus
# GLO-30 tiles, FABDEM), LZW (what GDAL's COG driver and QGIS write by
# default) and PackBits (QGIS's "low compression"). gwt-core.js carries the
# same three as C.inflateZlib, C.lzwDecode and C.packbitsDecode, and both are
# held to one rule per codec rather than to whatever each library happens to
# do with a damaged block, so the two engines refuse the same blocks.


class _CodecError(ValueError):
    """A block that does not decode. ``code`` says why, in the reader's
    terms: ``"damaged"`` for any stream that is not what it claims to be,
    ``"old_lzw"`` for the pre-1992 form of LZW, which is refused by name
    rather than read as damage. The reader turns each into its sentence."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _inflate_block(data: bytes, expected: int, full: int) -> bytes:
    """The first ``expected`` bytes of a zlib-wrapped DEFLATE block.

    The block is accepted only when the whole stream is valid to its end,
    its Adler-32 included, and holds between ``expected`` bytes and one
    ``full`` block. That is a rule the browser's own inflate can be held to
    exactly: where zlib stops inside a stream that runs on past what was
    asked for is zlib's business, but whether the stream is valid is not.
    It also bounds the memory a block can take, so a stream that inflates
    to gigabytes stops one byte past a full block. Bytes after the
    checksum - a writer's padding to a word boundary - are ignored, as
    libtiff ignores them; output beyond ``expected`` is a padded last
    strip, and is dropped.
    """
    d = zlib.decompressobj()  # wbits 15: the zlib wrapper is required
    try:
        out = d.decompress(data, full + 1)
    except zlib.error:
        raise _CodecError("damaged") from None
    if len(out) > full or not d.eof or len(out) < expected:
        raise _CodecError("damaged")
    return out[:expected]


#: libtiff's table bound: 4,096 twelve-bit codes plus 1,023 entries no code
#: can name (MAXCODE(12) + 1024, tif_lzw.c). An encoder that defers its
#: Clear may keep adding to the table that far, and libtiff and GDAL read
#: what it wrote; a table of 4,096 would refuse files they open.
_LZW_TABLE = 5119


def _lzw_decode_loop(data: bytes, expected: int) -> bytes:
    """The first ``expected`` bytes of a TIFF LZW strip or tile, one code
    at a time.

    This is the reference the faster decoder and the browser's
    C.lzwDecode are both held to, kept as a loop because a loop can be read
    against the TIFF specification line by line. Codes are read most
    significant bit first and widen one code early, at 511, 1023 and 2047,
    as every TIFF writer since 1992 does. Decoding stops once ``expected``
    bytes are out, so whatever follows - an end code or not, padding, or
    codes no valid table could hold - is never looked at; a stream that ends
    before then, or names a code the table does not have, is damaged.
    """
    if len(data) >= 2 and data[0] == 0 and data[1] & 1:
        # the pre-1992 form, least significant bit first: libtiff's own test
        raise _CodecError("old_lzw")
    table: list[bytes] = [bytes([i]) for i in range(256)] + [b""] * (_LZW_TABLE - 256)
    bits = len(data) * 8
    padded = bytes(data) + b"\0\0\0"
    pos, width, nxt = 0, 9, 258
    prev: bytes | None = None
    out = bytearray()
    while len(out) < expected:
        if bits - pos < width:
            break  # no end code: stop where the data stops
        p = pos >> 3
        window = (padded[p] << 16) | (padded[p + 1] << 8) | padded[p + 2]
        code = (window >> (24 - (pos & 7) - width)) & ((1 << width) - 1)
        pos += width
        if code == 257:
            break
        if code == 256:
            nxt, width, prev = 258, 9, None
            continue
        if prev is None:
            if code > 255:
                raise _CodecError("damaged")
            prev = table[code]
            out += prev
            continue
        if code < nxt:
            entry = table[code]
            added = prev + entry[:1]
        elif code == nxt:
            entry = added = prev + prev[:1]
        else:
            raise _CodecError("damaged")
        if nxt == _LZW_TABLE:
            raise _CodecError("damaged")
        table[nxt] = added
        nxt += 1
        if nxt + 1 >= (1 << width) and width < 12:
            width += 1
        out += entry
        prev = entry
    if len(out) < expected:
        raise _CodecError("damaged")
    return bytes(out[:expected])


#: The codes one Clear segment can hold: the code that would add entry 5,119
#: is the 4,863rd after a Clear (index 4,862). It is still read, because a
#: Clear or an end code in that place is legal; any other code there is not.
_LZW_SEGMENT = _LZW_TABLE - 256

#: How many nine-bit codes are read at once when looking for short segments
_LZW_RUN = 1024


@functools.lru_cache(maxsize=1)
def _lzw_widths():
    """The width of the k-th code after a Clear, and where each starts.

    Every code after the first adds one table entry, so the width of a code
    depends only on how far it is from the last Clear: 9 bits up to the
    254th, then 10, 11 and 12, one code early as the loop widens.
    """
    import numpy as np

    widths, width, nxt = [9], 9, 258
    for _ in range(1, _LZW_SEGMENT):
        widths.append(width)
        nxt += 1
        if nxt + 1 >= (1 << width) and width < 12:
            width += 1
    width_of = np.array(widths, dtype=np.int64)
    return width_of, np.concatenate(([0], np.cumsum(width_of)))


def _lzw_decode(data: bytes, expected: int) -> bytes:
    """The first ``expected`` bytes of a TIFF LZW strip or tile, Clear
    segments at a time.

    The same answer as :func:`_lzw_decode_loop`, verdict and bytes, on every
    input - a test holds it there - but several times faster, because a
    Python loop per code is what makes a 48 MB tile take twenty seconds, and
    in the browser's Python (Pyodide) longer still. Between two Clears every
    code's width is known in advance, so a whole segment is read from the
    bits at once; its table is a tree whose parents are the segment's own
    codes, so each entry's first byte and length come from pointer jumping,
    and every code's string is then written backwards, all codes in step.
    Segments that end within their first 254 codes - all nine bits wide -
    are taken many at a time, so a stream that clears after every few codes
    is no slower than the loop. The loop's stopping rules are kept exactly:
    decoding stops once ``expected`` bytes are out, so nothing after that
    point is examined; a code the table cannot hold is damage only if it is
    needed; and a stream without an end code stops where its data does.
    """
    if len(data) >= 2 and data[0] == 0 and data[1] & 1:
        raise _CodecError("old_lzw")  # the pre-1992 form, as the loop tests for it
    if expected <= 0:
        return b""
    import numpy as np

    width_of, start_of = _lzw_widths()
    padded = np.frombuffer(bytes(data) + b"\0\0\0", dtype=np.uint8)
    bits = len(data) * 8
    # room for the last string to run past the block before it is cut
    out = np.empty(expected + _LZW_SEGMENT, dtype=np.uint8)
    total = pos = 0
    while total < expected:
        fits = int(np.searchsorted(start_of, bits - pos, side="right")) - 1
        count = min(fits, _LZW_SEGMENT)
        if count <= 0:
            break  # no end code: stop where the data stops
        codes = _lzw_codes(padded, pos + start_of[:count], width_of[:count])
        control = np.flatnonzero((codes == 256) | (codes == 257))
        end = int(control[0]) if control.size else count
        if end <= 253 and end < count:
            # A short segment, every code nine bits wide. So is each short
            # segment after it, wherever it starts, so all of them are read
            # from one run of nine-bit codes and decoded together.
            nine = _lzw_codes(padded, pos + 9 * np.arange(min((bits - pos) // 9, _LZW_RUN), dtype=np.int64), 9)
            begin, spans, ended = 0, [], False
            for at in np.flatnonzero((nine == 256) | (nine == 257)).tolist():
                if at - begin > 253:
                    break  # a long segment: read at its own widths next time round
                spans.append((begin, at))
                if nine[at] == 257:
                    ended = True
                    break
                begin = at + 1
            places = np.concatenate([np.arange(a, b, dtype=np.int64) for a, b in spans])
            rank = places - np.repeat(np.array([a for a, _ in spans], dtype=np.int64), [b - a for a, b in spans])
            total = _lzw_valid(nine[places], rank, out, total, expected)
            if total >= expected or ended:
                break
            pos += 9 * begin
            continue
        # A long segment, to its Clear or end code, or to the end of the data;
        # 4,863 codes with neither means the last of them is past the table
        total = _lzw_valid(codes[:end], np.arange(end, dtype=np.int64), out, total, expected)
        if total >= expected or end == count or codes[end] == 257:
            break
        pos += int(start_of[end + 1])  # past the Clear: a fresh table
    if total < expected:
        raise _CodecError("damaged")
    return out[:expected].tobytes()


def _lzw_codes(padded, starts, widths):
    """The codes of ``widths`` bits starting at bit ``starts``, most
    significant bit first. A code of up to 12 bits starting anywhere in a
    byte lies within three bytes, hence the three bytes of padding."""
    import numpy as np

    at = starts >> 3
    window = (padded[at].astype(np.int64) << 16) | (padded[at + 1].astype(np.int64) << 8) | padded[at + 2]
    return (window >> (24 - (starts & 7) - widths)) & ((1 << widths) - 1)


def _lzw_valid(codes, rank, out, total: int, expected: int) -> int:
    """Decode the codes of one or more whole segments (``rank`` is each
    code's place after its Clear) up to the first that no table could hold,
    and refuse that one if the block still needs it."""
    import numpy as np

    # a literal first, then at most the entry the code itself adds, and no
    # entry past the table's 5,119
    bound = np.where(rank == 0, 255, 257 + rank)
    invalid = np.flatnonzero((codes > bound) | (rank >= _LZW_SEGMENT - 1))
    valid = int(invalid[0]) if invalid.size else codes.size
    if valid:
        total = _lzw_strings(codes[:valid], rank[:valid], out, total, expected)
    if total < expected and valid < codes.size:
        raise _CodecError("damaged")  # the loop would read this code, and refuse it
    return total


def _lzw_strings(codes, rank, out, total: int, expected: int) -> int:
    """Write the strings of valid codes into ``out`` from ``total``, stopping
    at the code that reaches ``expected``, and return where the output now
    ends (which may be past ``expected``).

    Each code but the first after a Clear adds an entry: the string of the
    code before it plus the first byte of its own string (which, when the
    code names that very entry, is the first byte of the code before's). So
    each entry's parent is the code before it. Here the entry added by the
    k-th code is numbered 256 + k, and a code ``v`` from 258 names the entry
    added by the code ``v - 257`` places after its segment's Clear.
    """
    import numpy as np

    n = codes.size
    first = np.flatnonzero(rank == 0)  # the codes straight after a Clear add nothing
    node = np.where(codes < 256, codes, codes + (np.arange(n, dtype=np.int64) - rank) - 1)
    size = 256 + n  # literals 0-255, then 256 + k for the entry code k adds
    parent = np.full(size, -1, dtype=np.int64)
    parent[257:] = node[:-1]
    parent[256 + first] = -1
    root = parent.copy()
    root[:256] = np.arange(256)
    depth = np.ones(size, dtype=np.int64)
    depth[:257] = 0
    depth[256 + first] = 0
    live = np.flatnonzero(root >= 256)
    while live.size:  # pointer jumping: each pass halves every remaining path
        up = root[live]
        depth[live] += depth[up]
        root[live] = root[up]
        live = live[root[live] >= 256]
    suffix = np.arange(size, dtype=np.int64)  # a literal is its own last byte
    suffix[257:] = root[node[1:]]
    ends = np.cumsum((depth + 1)[node])
    reached = int(np.searchsorted(ends, expected - total))
    if reached < n:  # this code fills the block; the codes after it are never read
        node, ends = node[:reached + 1], ends[:reached + 1]
    at = total + ends - 1
    while node.size:  # every string written from its last byte back, all at once
        out[at] = suffix[node]
        node = parent[node]
        keep = node >= 0
        node, at = node[keep], at[keep] - 1
    return total + int(ends[-1])


def _packbits_decode(data: bytes, expected: int) -> bytes:
    """The first ``expected`` bytes of a PackBits strip or tile.

    Each header byte ``n``, read as signed, is followed by ``n + 1`` bytes
    to copy (0 to 127), one byte to repeat ``1 - n`` times (-127 to -1), or
    nothing (-128, a no-op). A run that reaches past ``expected`` is cut
    there and needs only the bytes it uses, as libtiff reads it; running out
    of data before ``expected`` bytes is damage.
    """
    out = bytearray()
    pos, size = 0, len(data)
    while len(out) < expected:
        if pos >= size:
            raise _CodecError("damaged")
        header = data[pos]
        pos += 1
        if header < 128:
            take = min(header + 1, expected - len(out))
            if pos + take > size:
                raise _CodecError("damaged")
            out += data[pos:pos + take]
            pos += header + 1
        elif header > 128:
            if pos >= size:
                raise _CodecError("damaged")
            out += data[pos:pos + 1] * min(257 - header, expected - len(out))
            pos += 1
    return bytes(out)


# ------------------------------------------------------------------ reader
#
# The raw layer of PLAN.md step 4.1: any GeoTIFF the codecs above can
# decode, in any coordinate system. Its twin is the "TIFF and
# GeoTIFF" section of gwt-core.js, and the two follow one set of rules, in
# one order, so that a file either reads to the same cells in both or is
# refused with the same sentence. Each refusal names its catalogue entry in
# full, as tests/test_text.py requires.

# The tags the reader looks at beyond the writer's own
_NEW_SUBFILE_TYPE = 254
_SUBFILE_TYPE = 255
_FILL_ORDER = 266
_PREDICTOR = 317
_TILE_WIDTH = 322
_TILE_LENGTH = 323
_TILE_OFFSETS = 324
_TILE_BYTE_COUNTS = 325
_MODEL_TRANSFORMATION = 34264
_GEO_DOUBLE_PARAMS = 34736
_GEO_ASCII_PARAMS = 34737
_GDAL_METADATA = 42112

# GeoTIFF keys read beyond the writer's three
_GEOGRAPHIC_TYPE = 2048
_GEOG_GEODETIC_DATUM = 2050
_GEOG_ANGULAR_UNITS = 2054

#: Each tag as a refusal names it (terrain.bad_tag, terrain.ends_early).
_TAG_NAMES = {
    _NEW_SUBFILE_TYPE: "NewSubfileType", _SUBFILE_TYPE: "SubfileType",
    _IMAGE_WIDTH: "ImageWidth", _IMAGE_LENGTH: "ImageLength", _BITS_PER_SAMPLE: "BitsPerSample",
    _COMPRESSION: "Compression", _FILL_ORDER: "FillOrder", _STRIP_OFFSETS: "StripOffsets",
    _SAMPLES_PER_PIXEL: "SamplesPerPixel", _ROWS_PER_STRIP: "RowsPerStrip",
    _STRIP_BYTE_COUNTS: "StripByteCounts", _PLANAR_CONFIG: "PlanarConfiguration",
    _PREDICTOR: "Predictor", _TILE_WIDTH: "TileWidth", _TILE_LENGTH: "TileLength",
    _TILE_OFFSETS: "TileOffsets", _TILE_BYTE_COUNTS: "TileByteCounts",
    _SAMPLE_FORMAT: "SampleFormat", _MODEL_PIXEL_SCALE: "ModelPixelScale",
    _MODEL_TIEPOINT: "ModelTiepoint", _MODEL_TRANSFORMATION: "ModelTransformation",
    _GEO_KEY_DIRECTORY: "GeoKeyDirectory", _GEO_DOUBLE_PARAMS: "GeoDoubleParams",
    _GEO_ASCII_PARAMS: "GeoAsciiParams", _GDAL_METADATA: "GDAL_METADATA", _GDAL_NODATA: "GDAL_NODATA",
}

#: Bytes per value of each TIFF field type. A type not listed is unknown:
#: an entry of that type is skipped, unless the reader needs the tag.
_TYPE_SIZE = {1: 1, 2: 1, 6: 1, 7: 1, 3: 2, 8: 2, 4: 4, 9: 4, 11: 4,
              5: 8, 10: 8, 12: 8, 16: 8, 17: 8, 18: 8}
_TYPE_FORMAT = {1: "B", 3: "H", 4: "I", 16: "Q", 12: "d"}

# The field types each tag the reader uses may have; any other is a damaged
# entry. Integers come as BYTE, SHORT, LONG or LONG8.
_INTEGER = (1, _SHORT, _LONG, 16)
_ALLOWED_TYPES = {
    **{tag: _INTEGER for tag in (
        _NEW_SUBFILE_TYPE, _SUBFILE_TYPE, _IMAGE_WIDTH, _IMAGE_LENGTH, _BITS_PER_SAMPLE, _COMPRESSION,
        _FILL_ORDER, _STRIP_OFFSETS, _SAMPLES_PER_PIXEL, _ROWS_PER_STRIP, _STRIP_BYTE_COUNTS,
        _PLANAR_CONFIG, _PREDICTOR, _TILE_WIDTH, _TILE_LENGTH, _TILE_OFFSETS, _TILE_BYTE_COUNTS,
        _SAMPLE_FORMAT)},
    **{tag: (_DOUBLE,) for tag in (
        _MODEL_PIXEL_SCALE, _MODEL_TIEPOINT, _MODEL_TRANSFORMATION, _GEO_DOUBLE_PARAMS)},
    _GEO_KEY_DIRECTORY: (_SHORT,),
    **{tag: (_ASCII,) for tag in (_GEO_ASCII_PARAMS, _GDAL_METADATA, _GDAL_NODATA)},
}
#: Tags that hold exactly one value
_SINGLE = {_NEW_SUBFILE_TYPE, _SUBFILE_TYPE, _IMAGE_WIDTH, _IMAGE_LENGTH, _COMPRESSION, _FILL_ORDER,
           _SAMPLES_PER_PIXEL, _ROWS_PER_STRIP, _PLANAR_CONFIG, _PREDICTOR, _TILE_WIDTH, _TILE_LENGTH}
#: Tags given once per sample; the first value is the one read
_PER_SAMPLE = {_BITS_PER_SAMPLE, _SAMPLE_FORMAT}
#: The tags whose values the layout reads, out of line where they do not fit
_VALUE_TAGS = sorted(set(_TAG_NAMES) - {_NEW_SUBFILE_TYPE, _SUBFILE_TYPE})

#: JavaScript reads a 64-bit offset or count as two 32-bit halves, exact
#: below 2**53, and the two engines keep one limit.
_ADDRESSABLE = 1 << 53

#: (SampleFormat, BitsPerSample) pairs the reader decodes, and how each kind is named
_SAMPLE_TYPES = {(1, 8), (2, 8), (1, 16), (2, 16), (1, 32), (2, 32), (3, 32), (3, 64)}
_SAMPLE_KINDS = {1: "unsigned integer", 2: "signed integer", 3: "floating-point"}
_COMPRESSIONS = {1, 5, 8, 32946, 32773}

#: A block decoding to more than this is refused rather than held in memory
#: whole: 64 MiB, which still takes a 3601 x 3601 float32 tile written as
#: one strip (52 MB).
_BLOCK_LIMIT = 64 << 20

#: How the layout's bytes are fetched: a first read that holds a COG's
#: every directory (a Copernicus tile keeps them in its first 1.1 KB), then
#: each missing range rounded up to 64 KiB, for at most 16 further rounds.
_READ_UNIT = 65536
_ROUNDS = 16

#: The most directories walked looking for the full-resolution image
_MAX_DIRECTORIES = 64

_FLT_MAX = 3.4028234663852886e38
_NUMBER = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?")
_SCALE_ITEM = re.compile(r'<Item[^>]*role="(scale|offset)"[^>]*>([^<]*)</Item>')


class GeoTiffError(ValueError):
    """A GeoTIFF the reader refuses, with the sentence that says why.

    ``ident`` is the full catalogue id (``"terrain.not_tiff"``), ``code``
    the same without its namespace, and ``values`` what was filled into the
    sentence. The browser's reader throws an Error carrying the same three,
    so a caller in either engine can tell refusals apart without parsing
    their words.
    """

    def __init__(self, ident: str, **values) -> None:
        from .text import phrase

        super().__init__(phrase(ident, **values))
        self.ident = ident
        self.code = ident.removeprefix("terrain.")
        self.values = values


@dataclass(frozen=True)
class GeoTiffLayout:
    """Everything about a GeoTIFF but its samples: what the blocks hold,
    where they are, and where the cells lie.

    ``x0`` and ``y0`` are the centres of column 0 and row 0, row 0 being
    the northernmost, and ``sx`` and ``sy`` the positive cell sizes, so
    cell ``(i, j)`` is centred on ``x0 + i*sx, y0 - j*sy`` in the file's
    coordinate system. A strip is a block ``block_width`` (the image width)
    by ``block_height`` (``rows_per_strip``); for tiles ``rows_per_strip``
    is None. ``nodata`` is GDAL_NODATA already cast to the sample type, or
    None when no sample can equal it. ``geo_ascii`` (the GeoAsciiParams
    text) and ``has_nodata_tag`` are kept for the elevation layer's GLO-30
    fingerprint. The browser's layout has the same fields in camelCase.
    """

    name: str
    size: int
    byte_order: str
    bigtiff: bool
    width: int
    height: int
    bits: int
    sample_format: int
    compression: int
    predictor: int
    predictor_applied: bool
    tiled: bool
    block_width: int
    block_height: int
    rows_per_strip: int | None
    offsets: list[int]
    byte_counts: list[int]
    model_type: int | None
    raster_type: int
    epsg: int | None
    datum: int | None
    angular_unit: int | None
    x0: float
    y0: float
    sx: float
    sy: float
    nodata: float | int | None
    ifd_index: int
    geo_ascii: str | None = None
    has_nodata_tag: bool = False


@dataclass(frozen=True)
class GeoTiffRaster:
    """A whole GeoTIFF read: ``z`` with row 0 at the south, as the toolkit's
    grids are (voids NaN), ``x`` the column centres ascending and ``y`` the
    row centres ascending, and the layout they came from."""

    z: np.ndarray
    x: np.ndarray
    y: np.ndarray
    layout: GeoTiffLayout


class _Missing(Exception):
    """Bytes the layout needs and was not given, as ``(offset, length)``."""

    def __init__(self, ranges: list[tuple[int, int]]) -> None:
        super().__init__(ranges)
        self.ranges = ranges


class _Chunks:
    """The bytes of a file a caller has read so far, by where they start."""

    def __init__(self, name: str, size: int, chunks: Sequence[tuple[int, bytes]]) -> None:
        self.name, self.size, self.chunks = name, size, chunks

    def at(self, offset: int, length: int, part: str) -> bytes | None:
        """The bytes at ``[offset, offset + length)`` if one chunk holds them all.

        A range past the end of the file is refused at once, whatever has
        been read: the file is shorter than its own header says.
        """
        if offset + length > self.size:
            raise GeoTiffError("terrain.ends_early", file=self.name, part=part)
        for start, data in self.chunks:
            if start <= offset and offset + length <= start + len(data):
                return bytes(data[offset - start:offset - start + length])
        return None

    def need(self, offset: int, length: int, part: str) -> bytes:
        """The bytes, or stop this round and ask for them."""
        found = self.at(offset, length, part)
        if found is None:
            raise _Missing([(offset, length)])
        return found


def geotiff_layout(name: str, size: int,
                   chunks: Sequence[tuple[int, bytes]]) -> GeoTiffLayout | list[tuple[int, int]]:
    """The layout of a GeoTIFF of ``size`` bytes, from the ``(offset, bytes)``
    chunks read so far, or the byte ranges it still needs, sorted.

    It reads nothing itself, so the one function serves a file on disk, an
    upload in the browser and a test alike: the caller reads what is asked
    for and calls again. The header and the directories are walked one
    dependent read at a time; the values of the chosen directory's tags are
    asked for together. However a file is chunked, the answer is the one the
    whole file gives, refusals included.
    """
    try:
        return _layout(_Chunks(name, size, chunks))
    except _Missing as missing:
        return sorted(set(missing.ranges))


def _addressable(value: int, name: str) -> int:
    if value >= _ADDRESSABLE:
        raise GeoTiffError("terrain.too_large", file=name)
    return value


def _bad_tag(name: str, tag: int) -> GeoTiffError:
    return GeoTiffError("terrain.bad_tag", file=name, tag=_TAG_NAMES[tag])


def _layout(src: _Chunks) -> GeoTiffLayout:
    name = src.name
    head = src.need(0, 16, "file header")
    if head[:2] == b"II":
        order = "<"
    elif head[:2] == b"MM":
        order = ">"
    else:
        raise GeoTiffError("terrain.not_tiff", file=name)
    (version,) = struct.unpack_from(order + "H", head, 2)
    if version == 42:
        big = False
        (ifd,) = struct.unpack_from(order + "I", head, 4)
    elif version == 43:
        big = True
        if struct.unpack_from(order + "HH", head, 4) != (8, 0):
            raise GeoTiffError("terrain.not_tiff", file=name)
        (ifd,) = struct.unpack_from(order + "Q", head, 8)
        _addressable(ifd, name)
    else:
        raise GeoTiffError("terrain.not_tiff", file=name)
    # classic and BigTIFF differ only in these widths
    count_size, entry_size, inline, word = (8, 20, 8, "Q") if big else (2, 12, 4, "I")

    # The directory chain, to the first full-resolution image: COGs and
    # pyramids keep overviews and masks beside it, before it as often as
    # after it.
    seen: set[int] = set()
    index = 0
    while True:
        if ifd == 0:
            raise GeoTiffError("terrain.no_full_image", file=name)
        seen.add(ifd)
        (n,) = struct.unpack(order + ("Q" if big else "H"), src.need(ifd, count_size, "image directory"))
        _addressable(n, name)
        body = src.need(ifd + count_size, n * entry_size + inline, "image directory")
        entries: dict[int, tuple[int, int, bytes]] = {}
        for k in range(n):
            tag, kind = struct.unpack_from(order + "HH", body, k * entry_size)
            if tag in entries:
                continue  # a repeated tag: the first stands, as in libtiff
            # tag, type, count and a value field, the last two 4 or 8 bytes wide
            (count,) = struct.unpack_from(order + word, body, k * entry_size + 4)
            entries[tag] = (kind, count, body[k * entry_size + 4 + inline:(k + 1) * entry_size])
        if _full_image(entries, order, inline, big, name):
            break
        (following,) = struct.unpack_from(order + word, body, n * entry_size)
        if following == 0:
            raise GeoTiffError("terrain.no_full_image", file=name)
        _addressable(following, name)
        if following in seen:
            raise GeoTiffError("terrain.directory_loop", file=name)
        index += 1
        if index == _MAX_DIRECTORIES:
            raise GeoTiffError("terrain.no_full_image", file=name)
        ifd = following

    # The chosen directory's values, out of line where they do not fit in
    # their entry. None depends on another, so every missing one is asked
    # for in the same round.
    raw: dict[int, tuple[int, int, bytes]] = {}
    missing: list[tuple[int, int]] = []
    for tag in _VALUE_TAGS:
        if tag not in entries:
            continue
        kind, count, field = entries[tag]
        length = _checked_entry(entries, tag, big, name)
        if length <= inline:
            raw[tag] = (kind, count, field[:length])
            continue
        (offset,) = struct.unpack(order + word, field)
        _addressable(offset, name)
        found = src.at(offset, length, f"values of {_TAG_NAMES[tag]}")
        if found is None:
            missing.append((offset, length))
        else:
            raw[tag] = (kind, count, found)
    if missing:
        raise _Missing(missing)
    return _describe(src, order, big, index, raw)


def _checked_entry(entries: dict, tag: int, big: bool, name: str) -> int:
    """The byte length of a tag's values, once its type and count are ones
    the reader can use."""
    kind, count, _ = entries[tag]
    if kind not in _ALLOWED_TYPES[tag]:
        raise _bad_tag(name, tag)
    if big:
        _addressable(count, name)
    if (tag in _SINGLE and count != 1) or (tag in _PER_SAMPLE and count < 1):
        raise _bad_tag(name, tag)
    return count * _TYPE_SIZE[kind]


def _full_image(entries: dict, order: str, inline: int, big: bool, name: str) -> bool:
    """Whether a directory is the full-resolution image: neither an overview
    (NewSubfileType bit 0, or the old SubfileType 2) nor a mask
    (NewSubfileType bit 2), and with a width and a height."""
    kinds: list[int | None] = []
    for tag in (_NEW_SUBFILE_TYPE, _SUBFILE_TYPE):
        if tag not in entries:
            kinds.append(None)
            continue
        length = _checked_entry(entries, tag, big, name)
        if length > inline:  # one value too long for its entry: no writer does this
            raise _bad_tag(name, tag)
        kind, _, field = entries[tag]
        (value,) = struct.unpack(order + _TYPE_FORMAT[kind], field[:length])
        kinds.append(_addressable(value, name))
    new, old = kinds
    return ((new or 0) & 0b101) == 0 and old != 2 and _IMAGE_WIDTH in entries and _IMAGE_LENGTH in entries


def _describe(src: _Chunks, order: str, big: bool, index: int, raw: dict) -> GeoTiffLayout:
    """The layout's checks, in the order both engines make them - the
    dimensions before anything divides by them, then samples, sample type,
    compression, predictor, fill order, the block table and the block size
    - then the georeferencing, the no-data value and the scale, each
    refused with its own sentence."""
    name = src.name

    def values(tag: int) -> list:
        kind, count, data = raw[tag]
        if kind == _ASCII:
            return [data]
        found = list(struct.unpack(f"{order}{count}{_TYPE_FORMAT[kind]}", data))
        if kind == 16:
            for value in found:
                _addressable(value, name)
        return found

    def first(tag: int, default):
        return values(tag)[0] if tag in raw else default

    # Dimensions, before anything divides by them
    width, height = first(_IMAGE_WIDTH, 0), first(_IMAGE_LENGTH, 0)
    if width < 1:
        raise _bad_tag(name, _IMAGE_WIDTH)
    if height < 1:
        raise _bad_tag(name, _IMAGE_LENGTH)
    tiled = _TILE_WIDTH in raw or _TILE_LENGTH in raw
    rows_per_strip = None
    if tiled:
        block_width, block_height = first(_TILE_WIDTH, 0), first(_TILE_LENGTH, 0)
        if block_width < 1:
            raise _bad_tag(name, _TILE_WIDTH)
        if block_height < 1:
            raise _bad_tag(name, _TILE_LENGTH)
    else:
        rows_per_strip = first(_ROWS_PER_STRIP, height)
        if rows_per_strip == 0xFFFFFFFF:  # libtiff's "the whole image"
            rows_per_strip = height
        rows_per_strip = min(rows_per_strip, height)
        if rows_per_strip < 1:
            raise _bad_tag(name, _ROWS_PER_STRIP)
        block_width, block_height = width, rows_per_strip

    samples = first(_SAMPLES_PER_PIXEL, 1)
    if samples != 1:
        raise GeoTiffError("terrain.bands", file=name, n=samples)

    # an absent SampleFormat is unsigned, as the TIFF rule and GDAL have it
    sample_format, bits = first(_SAMPLE_FORMAT, 1), first(_BITS_PER_SAMPLE, 1)
    if (sample_format, bits) not in _SAMPLE_TYPES:
        kind = _SAMPLE_KINDS.get(sample_format, f"SampleFormat {sample_format}")
        raise GeoTiffError("terrain.sample_type", file=name, bits=bits, kind=kind)

    compression = first(_COMPRESSION, 1)
    if compression not in _COMPRESSIONS:
        from .text import phrase_table

        method = phrase_table("terrain.compression_names").get(str(compression), f"TIFF method {compression}")
        raise GeoTiffError("terrain.compression", file=name, method=method)

    # libtiff sets a predictor up only inside its LZW and Deflate codecs, so
    # with no compression or PackBits the tag is ignored and GDAL reads the
    # values as they are stored
    predictor = first(_PREDICTOR, 1)
    applied = predictor != 1 and compression in (5, 8, 32946)
    if predictor not in (1, 2, 3) or (applied and predictor == 3 and sample_format != 3):
        raise GeoTiffError("terrain.predictor", file=name, code=predictor)

    fill_order = first(_FILL_ORDER, 1)
    if fill_order == 2:
        raise GeoTiffError("terrain.fill_order", file=name)
    if fill_order != 1:
        raise _bad_tag(name, _FILL_ORDER)

    if tiled:
        blocks = -(-width // block_width) * -(-height // block_height)
        offsets_tag, counts_tag = _TILE_OFFSETS, _TILE_BYTE_COUNTS
    else:
        blocks = -(-height // block_height)
        offsets_tag, counts_tag = _STRIP_OFFSETS, _STRIP_BYTE_COUNTS
    offsets = values(offsets_tag) if offsets_tag in raw else []
    counts = values(counts_tag) if counts_tag in raw else []
    if len(offsets) != blocks:
        raise _bad_tag(name, offsets_tag)
    if len(counts) != blocks:
        raise _bad_tag(name, counts_tag)

    block_bytes = block_width * block_height * (bits // 8)
    if block_bytes > _BLOCK_LIMIT:
        raise GeoTiffError("terrain.block_too_large", file=name, mb=block_bytes / 1048576)

    keys = _geo_keys(values(_GEO_KEY_DIRECTORY) if _GEO_KEY_DIRECTORY in raw else None, name)
    model_type = keys.get(_GT_MODEL_TYPE)
    x0, y0, sx, sy = _transform(raw, values, keys.get(_GT_RASTER_TYPE) == 2, name)

    nodata = None
    if _GDAL_NODATA in raw:
        text = values(_GDAL_NODATA)[0].decode("latin-1")
        parsed, readable = _parse_number(text)
        if not readable:
            raise GeoTiffError("terrain.nodata_unreadable", file=name, text=text.strip("\x00 \t\n\r"))
        nodata = None if parsed is None else _cast_nodata(parsed, sample_format, bits)

    if _GDAL_METADATA in raw:
        for role, text in _SCALE_ITEM.findall(values(_GDAL_METADATA)[0].decode("latin-1")):
            parsed, _ = _parse_number(text)
            if parsed is None or parsed != (1.0 if role == "scale" else 0.0):
                raise GeoTiffError("terrain.scaled", file=name)

    geo_ascii = None
    if _GEO_ASCII_PARAMS in raw:
        geo_ascii = values(_GEO_ASCII_PARAMS)[0].decode("latin-1").rstrip("\x00")
    return GeoTiffLayout(
        name=name, size=src.size, byte_order=order, bigtiff=big, width=width, height=height, bits=bits,
        sample_format=sample_format, compression=compression, predictor=predictor, predictor_applied=applied,
        tiled=tiled, block_width=block_width, block_height=block_height, rows_per_strip=rows_per_strip,
        offsets=offsets, byte_counts=counts, model_type=model_type,
        raster_type=2 if keys.get(_GT_RASTER_TYPE) == 2 else 1,
        epsg=keys.get(_PROJECTED_CS_TYPE) if model_type == 1 else keys.get(_GEOGRAPHIC_TYPE),
        datum=keys.get(_GEOG_GEODETIC_DATUM), angular_unit=keys.get(_GEOG_ANGULAR_UNITS),
        x0=x0, y0=y0, sx=sx, sy=sy, nodata=nodata, ifd_index=index, geo_ascii=geo_ascii,
        has_nodata_tag=_GDAL_NODATA in raw,
    )


def _geo_keys(directory: list | None, name: str) -> dict[int, int]:
    """The GeoKeys held in the directory itself (location 0), the first of each.

    Every key the reader uses is a SHORT; one stored elsewhere is taken as
    absent, as libgeotiff's typed lookup takes it.
    """
    if directory is None:
        return {}
    if len(directory) < 4 or len(directory) < 4 + 4 * directory[3]:
        raise _bad_tag(name, _GEO_KEY_DIRECTORY)
    keys: dict[int, int] = {}
    for k in range(directory[3]):
        key, location, _, value = directory[4 + 4 * k:8 + 4 * k]
        if location == 0 and key not in keys:
            keys[key] = value
    return keys


def _transform(raw: dict, values: Callable[[int], list], point: bool,
               name: str) -> tuple[float, float, float, float]:
    """The centres of the first column and row, and the cell sizes.

    Scale and tiepoint first, then a transformation matrix only when there
    is no scale, then several tiepoints alone (control points), which is
    the order GDAL looks for them in. PixelIsArea puts the tiepoint at a
    cell's corner and PixelIsPoint at its centre, so an area file's centres
    are half a cell in. The expressions are the browser's, operation for
    operation, so the two engines agree to the bit.
    """
    if _MODEL_PIXEL_SCALE in raw:
        scale = values(_MODEL_PIXEL_SCALE)
        if len(scale) < 2:
            raise _bad_tag(name, _MODEL_PIXEL_SCALE)
        if _MODEL_TIEPOINT not in raw:
            raise GeoTiffError("terrain.no_georeference", file=name)
        tie = values(_MODEL_TIEPOINT)
        if len(tie) < 6:
            raise _bad_tag(name, _MODEL_TIEPOINT)
        sx, sy = scale[0], scale[1]
        i, j, x, y = tie[0], tie[1], tie[3], tie[4]
        if not (sx > 0 and sy > 0):
            raise GeoTiffError("terrain.rotated", file=name)
    elif _MODEL_TRANSFORMATION in raw:
        m = values(_MODEL_TRANSFORMATION)
        if len(m) != 16:
            raise _bad_tag(name, _MODEL_TRANSFORMATION)
        if not (m[1] == 0 and m[4] == 0 and m[0] > 0 and m[5] < 0):
            raise GeoTiffError("terrain.rotated", file=name)
        sx, sy, i, j, x, y = m[0], -m[5], 0.0, 0.0, m[3], m[7]
    elif _MODEL_TIEPOINT in raw and len(values(_MODEL_TIEPOINT)) >= 12:
        raise GeoTiffError("terrain.control_points", file=name)
    else:
        raise GeoTiffError("terrain.no_georeference", file=name)
    x0 = (x - i * sx) + (0.0 if point else 0.5 * sx)
    y0 = (y + j * sy) - (0.0 if point else 0.5 * sy)
    return x0, y0, sx, sy


def _parse_number(text: str) -> tuple[float | None, bool]:
    """A no-data or scale value as GDAL writes one, as ``(value, readable)``.

    NULs and ASCII white space are trimmed first. Empty text is no value at
    all; the words for NaN and infinity are read in any case; anything else
    must be a plain decimal number, which both engines round correctly.
    """
    s = text.strip("\x00 \t\n\r")
    low = s.lower()
    if s == "":
        return None, True
    if low in ("nan", "+nan", "-nan"):
        return float("nan"), True
    if low in ("inf", "+inf", "infinity", "+infinity"):
        return float("inf"), True
    if low in ("-inf", "-infinity"):
        return float("-inf"), True
    if _NUMBER.fullmatch(s):
        return float(s), True
    return None, False


def _cast_nodata(value: float, sample_format: int, bits: int) -> float | int | None:
    """GDAL_NODATA as a sample of the file's type holds it, or None when no
    sample can equal it.

    A float32 value beyond the largest float32 is clamped to it first, as
    GDAL does: ArcGIS writes ``-3.40282346639e+038``, a hair beyond, which
    would otherwise round to -inf and match nothing in the file.
    """
    if sample_format == 3 and bits == 32:
        if value == value and abs(value) != float("inf") and abs(value) > _FLT_MAX:
            value = _FLT_MAX if value > 0 else -_FLT_MAX
        return struct.unpack("<f", struct.pack("<f", value))[0]
    if sample_format == 3:
        return value
    if value != value or abs(value) == float("inf") or value != int(value):
        return None
    low, high = (0, (1 << bits) - 1) if sample_format == 1 else (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
    return int(value) if low <= value <= high else None


def open_geotiff(name: str, size: int, read_at: Callable[[int, int], bytes]) -> GeoTiffLayout:
    """The layout of a file read through ``read_at(offset, length)``, which
    returns that many of its bytes (fewer at its end).

    The first read takes the first 64 KiB, which holds every directory of a
    cloud-optimised file; a file with its directory at the end takes one
    more. A file still asking after 16 more rounds is given up on.
    """
    chunks = [(0, read_at(0, min(size, _READ_UNIT)))]
    for _ in range(_ROUNDS):
        found = geotiff_layout(name, size, chunks)
        if isinstance(found, GeoTiffLayout):
            return found
        for offset, length in found:
            chunks.append((offset, read_at(offset, min(-(-length // _READ_UNIT) * _READ_UNIT, size - offset))))
    found = geotiff_layout(name, size, chunks)
    if isinstance(found, GeoTiffLayout):
        return found
    raise GeoTiffError("terrain.ends_early", file=name, part="image directory")


def _block_geometry(layout: GeoTiffLayout, index: int) -> tuple[int, int, int, int, int, int]:
    """Where block ``index`` starts in the image (row, column), how many of
    its rows and columns are image rather than padding, and the bytes it
    must decode to (``expected``) and may decode to (``full``)."""
    size = layout.bits // 8
    if layout.tiled:
        across = -(-layout.width // layout.block_width)
        row0 = index // across * layout.block_height
        col0 = index % across * layout.block_width
        full = layout.block_width * layout.block_height * size
        return (row0, col0, min(layout.block_height, layout.height - row0),
                min(layout.block_width, layout.width - col0), full, full)
    row0 = index * layout.block_height
    rows = min(layout.block_height, layout.height - row0)
    return (row0, 0, rows, layout.width, rows * layout.width * size,
            layout.block_height * layout.width * size)


def block_ranges(layout: GeoTiffLayout, j0: int, j1: int, i0: int,
                 i1: int) -> list[tuple[int, int, int, tuple[int, int] | None]]:
    """The blocks that rows ``[j0, j1)`` and columns ``[i0, i1)`` meet (row 0
    north), in the file's own block order, as ``(index, offset, length, rows)``.

    ``rows`` is None but for an uncompressed strip read in part: it is then
    the strip's own rows ``(r0, r1)`` that are wanted, and the offset and
    length cover only those, because uncompressed rows can be read where
    they lie. A sparse block (offset and byte count 0) needs no bytes. A
    block running past the end of the file is refused here, before
    anything is read.
    """
    j0, j1 = max(j0, 0), min(j1, layout.height)
    i0, i1 = max(i0, 0), min(i1, layout.width)
    if j0 >= j1 or i0 >= i1:
        return []
    wanted: list[tuple[int, tuple[int, int] | None]] = []
    if layout.tiled:
        across = -(-layout.width // layout.block_width)
        for down in range(j0 // layout.block_height, (j1 - 1) // layout.block_height + 1):
            for over in range(i0 // layout.block_width, (i1 - 1) // layout.block_width + 1):
                wanted.append((down * across + over, None))
    else:
        for index in range(j0 // layout.block_height, (j1 - 1) // layout.block_height + 1):
            rows = None
            if layout.compression == 1:
                row0, _, count, _, _, _ = _block_geometry(layout, index)
                r0, r1 = max(j0 - row0, 0), min(j1 - row0, count)
                if r0 > 0 or r1 < count:
                    rows = (r0, r1)
            wanted.append((index, rows))
    found = []
    for index, rows in wanted:
        offset, length = layout.offsets[index], layout.byte_counts[index]
        if offset == 0 and length == 0:
            found.append((index, 0, 0, rows))
            continue
        if offset + length > layout.size:
            raise GeoTiffError("terrain.ends_early", file=layout.name, part=f"data block {index + 1}")
        if rows is not None:
            row_bytes = layout.width * (layout.bits // 8)
            offset, length = offset + rows[0] * row_bytes, (rows[1] - rows[0]) * row_bytes
        found.append((index, offset, length, rows))
    return found


def decode_block(layout: GeoTiffLayout, index: int, data: bytes, rows: tuple[int, int] | None = None,
                 bounds: tuple[float, float] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Block ``index`` as heights, and the reason each void cell is void, row 0 north.

    ``data`` is what :func:`block_ranges` said to read. The values are
    float64 with the padding of edge tiles cropped off. ``reasons`` is 0 for
    a value, 1 for no data - the no-data value, NaN, or a sparse block,
    which GDAL reads as 0 without a no-data value though a block that holds
    no data is not ground at 0 m - and 2 for a value outside ``bounds``, the
    plausible range the elevation layer passes (an infinity included).
    Voids are NaN. Every value kept is canonicalised with ``+ 0.0``, so a
    stored -0 reads as +0 and cannot later set the two engines' choices
    between equal heights apart.
    """
    import numpy as np

    _, _, block_rows, cols, expected, full = _block_geometry(layout, index)
    if rows is not None and (layout.tiled or layout.compression != 1 or not 0 <= rows[0] < rows[1] <= block_rows):
        raise ValueError(f"rows {rows} are not rows of uncompressed strip {index}")
    out_rows = block_rows if rows is None else rows[1] - rows[0]
    if layout.offsets[index] == 0 and layout.byte_counts[index] == 0:
        return np.full((out_rows, cols), np.nan), np.ones((out_rows, cols), dtype=np.uint8)
    try:
        if layout.compression == 1:
            wanted = expected if rows is None else out_rows * layout.width * (layout.bits // 8)
            if layout.byte_counts[index] < expected or len(data) < wanted:
                raise _CodecError("damaged")
            raw = bytes(data[:wanted])
        elif layout.compression == 5:
            raw = _lzw_decode(data, expected)
        elif layout.compression == 32773:
            raw = _packbits_decode(data, expected)
        else:
            raw = _inflate_block(data, expected, full)
    except _CodecError as failure:
        if failure.code == "old_lzw":
            raise GeoTiffError("terrain.old_lzw", file=layout.name) from None
        raise GeoTiffError("terrain.block_damaged", n=index + 1, file=layout.name, bytes=expected) from None

    size = layout.bits // 8
    kind = {1: "u", 2: "i", 3: "f"}[layout.sample_format]
    across = layout.block_width
    count = len(raw) // (across * size)
    if layout.predictor_applied and layout.predictor == 2:
        # each row a running sum of words read in the file's byte order,
        # wrapping as the writer's differences did; float bit patterns too
        # (FABDEM)
        words = np.frombuffer(raw, dtype=f"{layout.byte_order}u{size}").reshape(count, across)
        native = np.cumsum(words, axis=1, dtype=f"u{size}").view(f"{kind}{size}")
    elif layout.predictor_applied:
        # predictor 3: a running sum of bytes straight along the row, then
        # each sample's bytes gathered from its planes, most significant
        # first whatever the file's byte order (libtiff's fpAcc)
        planes = np.cumsum(np.frombuffer(raw, dtype=np.uint8).reshape(count, size * across), axis=1,
                           dtype=np.uint8)
        native = np.ascontiguousarray(planes.reshape(count, size, across).transpose(0, 2, 1)).view(
            f">f{size}").reshape(count, across)
    else:
        native = np.frombuffer(raw, dtype=f"{layout.byte_order}{kind}{size}").reshape(count, across)
    values = native[:out_rows, :cols].astype(np.float64)

    reasons = np.zeros(values.shape, dtype=np.uint8)
    void = np.isnan(values)
    if layout.nodata is not None and layout.nodata == layout.nodata:
        void |= values == layout.nodata  # widening is exact, so this is the native comparison
    reasons[void] = 1
    if bounds is not None:
        low, high = bounds
        reasons[~void & (np.isinf(values) | (values < low) | (values > high))] = 2
    values = values + 0.0
    values[reasons != 0] = np.nan
    return values, reasons


def read_geotiff(source: str | Path | bytes, name: str | None = None) -> GeoTiffRaster:
    """A whole GeoTIFF, from a path or its bytes, with row 0 at the south.

    Voids are NaN: the no-data value, NaN itself and sparse blocks. Every
    other value is as stored, infinities included; which values are
    plausible heights is for the elevation layer to say, not the file
    format. ``name`` is what a refusal calls the file (by default its
    basename). Nothing caps the size here, as nothing caps ``.hgt``; the
    apps read windows.
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
        return _read_whole("the file" if name is None else name, len(data),
                           lambda offset, length: data[offset:offset + length])
    path = Path(source)
    with path.open("rb") as handle:

        def read_at(offset: int, length: int) -> bytes:
            handle.seek(offset)
            return handle.read(length)

        return _read_whole(path.name if name is None else name, path.stat().st_size, read_at)


def _read_whole(name: str, size: int, read_at: Callable[[int, int], bytes]) -> GeoTiffRaster:
    import numpy as np

    layout = open_geotiff(name, size, read_at)
    z = np.full((layout.height, layout.width), np.nan)
    for index, offset, length, rows in block_ranges(layout, 0, layout.height, 0, layout.width):
        values, _ = decode_block(layout, index, read_at(offset, length) if length else b"", rows)
        row0, col0 = _block_geometry(layout, index)[:2]
        z[row0:row0 + values.shape[0], col0:col0 + values.shape[1]] = values
    x = layout.x0 + np.arange(layout.width) * layout.sx
    y = layout.y0 - np.arange(layout.height - 1, -1, -1) * layout.sy
    return GeoTiffRaster(np.ascontiguousarray(z[::-1]), x, y, layout)

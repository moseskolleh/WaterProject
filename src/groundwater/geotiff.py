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
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

__all__ = ["utm_epsg", "write_geotiff"]

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

"""A GeoTIFF writer, so an interpolated surface survives being looked at.

``mapping.maps._interpolated_map`` computes a real 220 by 220 grid of
apparent resistivity or overburden thickness, draws it, and throws the
grid away. The picture answers "what does it look like"; it cannot answer
"what is the value at the borehole", "contour this at 5 m", or "show it
under satellite imagery". A raster can, in any GIS, for as long as the
file is kept.

Writing one needs no dependency. A single-band float32 GeoTIFF is a TIFF
header, one image file directory, and three GeoTIFF tags saying where the
corner is and how big a pixel is - a few hundred bytes of structure
around the numbers we already have. rasterio would do it too, but it
brings GDAL, and the browser build could never use it: this toolkit's own
QR encoder exists for the same reason, and is held to the same standard,
which is that the output is checked against an independent reader rather
than by inspection. A raster that is wrong in its georeferencing still
opens perfectly happily, in the wrong place.

What is written
---------------
Uncompressed, one strip, IEEE float32, ``PixelIsArea``, with NaN as the
nodata value so the masked ground outside the surveyed hull stays absent
rather than reading as zero - a zero-metre overburden is a statement, and
not one the survey made.

The projected CRS is written as an EPSG code in the GeoKey directory, so
the file lands in the right place without carrying a projection string
this toolkit would have to keep correct.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

__all__ = ["write_geotiff", "utm_epsg"]

# TIFF field types
_SHORT = 3
_LONG = 4
_DOUBLE = 12
_ASCII = 2

# The tags a reader needs to make sense of a single-band float raster,
# in ascending order, which the TIFF specification requires.
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
    """One 12-byte IFD entry whose value already fits in four bytes."""
    return struct.pack("<HHI", tag, field_type, count) + payload.ljust(4, b"\x00")


def _short_entry(tag: int, value: int) -> bytes:
    # A SHORT is written into the first two bytes of the value field.
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

    # Tag, type, count, payload. Whether a payload lives in its own entry
    # or after the directory is decided below by its length and not by
    # hand: TIFF *requires* four bytes or fewer to sit in the value field,
    # and a reader given an offset there follows it into whatever happens
    # to be at that address. "nan" is exactly four bytes with its
    # terminator, which is how that rule gets found the hard way.
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

    # Everything that fits in the four-byte value field of its own entry.
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
    # written pushes every offset past its data, which a reader reports as
    # a missing CRS and a garbage nodata rather than as a broken file.
    entry_count = len(inline) + len(values) + 1  # + StripOffsets
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
    for tag, _, _, payload in out_of_line:
        body += payload
        if len(payload) % 2:
            body += b"\x00"
    body += pixels

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(body))
    return path

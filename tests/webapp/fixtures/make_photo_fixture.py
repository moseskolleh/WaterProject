"""Write photo_exif.jpg: a small JPEG whose EXIF is known to the byte.

Both engines read the capture time and GPS position out of a photograph's
EXIF (groundwater/photos.py, gwt-core.js readExif), and both must read the
same values from the same file. A phone's photograph would do, but nobody
could say what its EXIF ought to read without trusting a third reader, so
the segment here is written by hand, tag by tag, around a 24 x 16 JPEG that
any browser decodes. The test suite holds the committed file to this
script (tests/test_photos.py), and the same builder makes the variants the
tests need: big-endian, southern and western, no GPS, a blank clock.

    python tests/webapp/fixtures/make_photo_fixture.py
"""

from __future__ import annotations

import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "photo_exif.jpg"

# A plain 24 x 16 baseline JPEG, no metadata, made once with Pillow and kept
# as bytes so that writing the fixture needs nothing but this file.
BASE_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300100b0c0e0c0a100e0d0e12"
    "11101318281a181616183123251d283a333d3c3933383740485c4e404457453738506d51"
    "575f626768673e4d71797064785c656763ffdb0043011112121815182f1a1a2f63423842"
    "636363636363636363636363636363636363636363636363636363636363636363636363"
    "6363636363636363636363636363ffc00011080010001803012200021101031101ffc400"
    "160001010100000000000000000000000000040003ffc400161001010100000000000000"
    "000000000000030061ffc4001501010100000000000000000000000000000405ffc40019"
    "1101010003010000000000000000000000030001020421ffda000c03010002110311003f"
    "001994932b532946527748dceb64659538caa3652b46be5fffd9"
)

ASCII, SHORT, LONG, RATIONAL, BYTE = 2, 3, 4, 5, 1

#: What the committed fixture carries: a time with its UTC offset, and a
#: position in Freetown with the horizontal error the camera recorded.
FIXTURE_EXIF = {
    "taken": "2024:03:05 14:22:10",
    "offset": "+00:00",
    "lat": ("N", ((8, 1), (29, 1), (3456, 100))),
    "lon": ("W", ((13, 1), (14, 1), (1234, 100))),
    "error": (5, 1),
}


def _ifd_bytes(entries, start, order):
    """One IFD laid out at offset ``start``, its long values after it.

    ``entries`` is [(tag, type, payload bytes, count)], sorted by tag as
    TIFF wants. Returns the bytes, and the offset at which each entry's
    value landed, so a pointer to a later IFD can be patched in.
    """
    head = struct.pack(order + "H", len(entries))
    body = b""
    data_at = start + 2 + 12 * len(entries) + 4
    data = b""
    for tag, kind, payload, count in entries:
        if len(payload) <= 4:
            body += struct.pack(order + "HHI", tag, kind, count) + payload.ljust(4, b"\x00")
        else:
            body += struct.pack(order + "HHII", tag, kind, count, data_at + len(data))
            data += payload
            if len(data) % 2:
                data += b"\x00"
    return head + body + struct.pack(order + "I", 0) + data


def _ascii(text):
    raw = text.encode("ascii") + b"\x00"
    return raw, len(raw)


def _rationals(order, pairs):
    return b"".join(struct.pack(order + "II", n, d) for n, d in pairs), len(pairs)


def build_tiff(order="<", taken=None, offset=None, lat=None, lon=None, error=None):
    """A TIFF block carrying the given EXIF values; None leaves a tag out."""
    o = order
    exif_entries = []
    if taken is not None:
        exif_entries.append((0x9003, ASCII) + _ascii(taken))
    if offset is not None:
        exif_entries.append((0x9011, ASCII) + _ascii(offset))
    gps_entries = []
    if lat is not None or lon is not None:
        gps_entries.append((0x0000, BYTE, bytes([2, 3, 0, 0]), 4))
    if lat is not None:
        gps_entries.append((0x0001, ASCII) + _ascii(lat[0]))
        gps_entries.append((0x0002, RATIONAL) + _rationals(o, lat[1]))
    if lon is not None:
        gps_entries.append((0x0003, ASCII) + _ascii(lon[0]))
        gps_entries.append((0x0004, RATIONAL) + _rationals(o, lon[1]))
    if error is not None:
        gps_entries.append((0x001F, RATIONAL) + _rationals(o, [error]))

    make = (0x010F, ASCII) + _ascii("GWT fixture")
    # IFD0 first, with placeholders for the two pointers, then the others
    pointers = []
    if exif_entries:
        pointers.append(0x8769)
    if gps_entries:
        pointers.append(0x8825)
    ifd0_entries = [make] + [(tag, LONG, struct.pack(o + "I", 0), 1) for tag in pointers]
    ifd0 = _ifd_bytes(ifd0_entries, 8, o)
    at = 8 + len(ifd0)
    blocks, where = [], {}
    for tag, entries in ((0x8769, exif_entries), (0x8825, gps_entries)):
        if entries:
            where[tag] = at
            block = _ifd_bytes(entries, at, o)
            blocks.append(block)
            at += len(block)
    ifd0_entries = [make] + [(tag, LONG, struct.pack(o + "I", where[tag]), 1)
                             for tag in pointers]
    ifd0 = _ifd_bytes(ifd0_entries, 8, o)
    magic = b"II" if o == "<" else b"MM"
    return magic + struct.pack(o + "HI", 42, 8) + ifd0 + b"".join(blocks)


def jpeg_with_exif(tiff):
    """BASE_JPEG with an Exif APP1 segment after its JFIF APP0."""
    body = b"Exif\x00\x00" + tiff
    segment = b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
    app0_end = 2 + 2 + struct.unpack(">H", BASE_JPEG[4:6])[0]
    return BASE_JPEG[:app0_end] + segment + BASE_JPEG[app0_end:]


def fixture_bytes():
    return jpeg_with_exif(build_tiff("<", **FIXTURE_EXIF))


if __name__ == "__main__":
    FIXTURE.write_bytes(fixture_bytes())
    print(f"wrote {FIXTURE} ({FIXTURE.stat().st_size} bytes)")

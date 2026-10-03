"""Where a photograph came from: its capture time, its position and its hash.

A supervision photograph is evidence. The grout going down the annulus, the
screen laid out on the ground before it is lowered, the chlorine going in:
each is the only record that the step happened as the checklist says, and a
photograph is worth no more as evidence than what can be said about when
and where it was taken, and whether it is the file that was attached. So
every photograph either app takes in carries a provenance record:

``sha256``
    of the bytes as they were attached, before anything else happens to
    them. The browser downscales a large photograph for storage, which
    changes its bytes; the hash stays the original's, and ``stored`` says
    whether the copy kept is the original or a downscaled one.
``taken_at`` and ``time_source``
    the EXIF DateTimeOriginal where the file carries one ("exif"), as the
    camera's own clock wrote it and with its UTC offset where the camera
    recorded that; otherwise the device clock when the photograph was
    attached, in UTC ("device"). The record says which, because a camera
    time and an upload time are very different claims.
``position`` and ``position_source``
    the EXIF GPS position where the file carries one ("exif"), with the
    horizontal error the camera recorded, if any; otherwise a fix the
    device gave when the photograph was attached ("device"), with the
    accuracy it reported; otherwise none ("none"), with ``position_note``
    saying why.

Nothing is invented. A photograph attached before this record existed has
none, and the reports say so in those words rather than filling a time or
a place in afterwards.

The EXIF reader is written out here and in ``gwt-core.js`` rather than
taken from a library: it needs four tags, both engines must read them
identically, and a dependency for that would be the larger risk. It reads
JPEG only. A phone's browser may strip the GPS tags from a photograph
before a web page sees it, which is what the device fix is for.
"""

from __future__ import annotations

import hashlib
import re
import struct
from datetime import datetime, timezone

from .text import phrase, phrase_table

__all__ = [
    "PROVENANCE_FORMAT",
    "describe_provenance",
    "photo_provenance",
    "read_exif",
    "utc_now_text",
]

#: The record's own version, so a later field can be told from a missing one.
PROVENANCE_FORMAT = 1

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_DATETIME_ORIGINAL = 0x9003
_OFFSET_TIME_ORIGINAL = 0x9011
_GPS_LAT_REF, _GPS_LAT, _GPS_LON_REF, _GPS_LON = 1, 2, 3, 4
_GPS_H_ERROR = 0x1F

# bytes per value, by TIFF type
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}

_EXIF_TIME = re.compile(r"^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$")
_EXIF_OFFSET = re.compile(r"^[+-]\d{2}:\d{2}$")


def _tiff_block(data: bytes) -> bytes | None:
    """The TIFF block of a JPEG's first Exif APP1 segment, or None."""
    if data[:2] != b"\xff\xd8":
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        # start of scan or end of image: no metadata follows
        if marker in (0xDA, 0xD9):
            return None
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if length < 2:
            return None
        body = data[pos + 4:pos + 2 + length]
        if marker == 0xE1 and body[:6] == b"Exif\x00\x00":
            return body[6:]
        pos += 2 + length
    return None


def _ifd(tiff: bytes, offset: int, order: str) -> dict[int, tuple]:
    """{tag: (type, count, value bytes)} for one IFD; {} where it is broken."""
    if offset < 8 or offset + 2 > len(tiff):
        return {}
    count = struct.unpack(order + "H", tiff[offset:offset + 2])[0]
    out: dict[int, tuple] = {}
    for i in range(count):
        at = offset + 2 + 12 * i
        if at + 12 > len(tiff):
            break
        tag, kind, n = struct.unpack(order + "HHI", tiff[at:at + 8])
        size = _TYPE_SIZE.get(kind)
        if size is None:
            continue
        total = size * n
        if total <= 4:
            raw = tiff[at + 8:at + 8 + total]
        else:
            start = struct.unpack(order + "I", tiff[at + 8:at + 12])[0]
            if start + total > len(tiff):
                continue
            raw = tiff[start:start + total]
        out[tag] = (kind, n, raw)
    return out


def _ascii(entry) -> str | None:
    if entry is None or entry[0] != 2:
        return None
    return entry[2].split(b"\x00", 1)[0].decode("ascii", "replace").strip()


def _long(entry, order: str) -> int | None:
    if entry is None or entry[1] < 1:
        return None
    if entry[0] == 4:
        return struct.unpack(order + "I", entry[2][:4])[0]
    if entry[0] == 3:
        return struct.unpack(order + "H", entry[2][:2])[0]
    return None


def _rationals(entry, order: str) -> list[float] | None:
    """An unsigned RATIONAL entry as floats; None if any denominator is 0."""
    if entry is None or entry[0] != 5:
        return None
    out = []
    for i in range(entry[1]):
        num, den = struct.unpack(order + "II", entry[2][8 * i:8 * i + 8])
        if den == 0:
            return None
        out.append(num / den)
    return out


def _degrees(entry, ref: str | None, order: str, limit: float) -> float | None:
    parts = _rationals(entry, order)
    if parts is None or len(parts) != 3 or ref not in ("N", "S", "E", "W"):
        return None
    # added in this order in both engines, so the two give the same double
    value = parts[0] + parts[1] / 60.0 + parts[2] / 3600.0
    if ref in ("S", "W"):
        value = -value
    return value if abs(value) <= limit else None


def read_exif(data: bytes) -> dict:
    """The capture time and GPS position a JPEG's EXIF carries.

    Returns ``{"taken_at": str | None, "gps": {"lat", "lon", "accuracy_m"}
    | None}``. ``taken_at`` is DateTimeOriginal as ISO 8601 local time, with
    OffsetTimeOriginal appended where the camera wrote one. A file that is
    not a JPEG, has no EXIF, or has a malformed or blank value gives None
    for that value and never raises: a photograph without metadata is
    still a photograph.
    """
    out: dict = {"taken_at": None, "gps": None}
    try:
        tiff = _tiff_block(bytes(data))
        if tiff is None or len(tiff) < 8:
            return out
        order = {b"II": "<", b"MM": ">"}.get(tiff[:2])
        if order is None or struct.unpack(order + "H", tiff[2:4])[0] != 42:
            return out
        ifd0 = _ifd(tiff, struct.unpack(order + "I", tiff[4:8])[0], order)
        exif_at = _long(ifd0.get(_EXIF_IFD), order)
        if exif_at is not None:
            exif = _ifd(tiff, exif_at, order)
            text = _ascii(exif.get(_DATETIME_ORIGINAL)) or ""
            match = _EXIF_TIME.match(text)
            # a camera with no clock set writes zeros, or spaces, which say
            # nothing about when the photograph was taken
            if match and 1 <= int(match.group(2)) <= 12 and 1 <= int(match.group(3)) <= 31:
                y, mo, d, h, mi, s = match.groups()
                taken = f"{y}-{mo}-{d}T{h}:{mi}:{s}"
                offset = _ascii(exif.get(_OFFSET_TIME_ORIGINAL)) or ""
                out["taken_at"] = taken + (offset if _EXIF_OFFSET.match(offset) else "")
        gps_at = _long(ifd0.get(_GPS_IFD), order)
        if gps_at is not None:
            gps = _ifd(tiff, gps_at, order)
            lat = _degrees(gps.get(_GPS_LAT), _ascii(gps.get(_GPS_LAT_REF)), order, 90.0)
            lon = _degrees(gps.get(_GPS_LON), _ascii(gps.get(_GPS_LON_REF)), order, 180.0)
            # 0, 0 is what a camera without a fix writes, not a place in the sea
            if lat is not None and lon is not None and not (lat == 0 and lon == 0):
                error = _rationals(gps.get(_GPS_H_ERROR), order)
                out["gps"] = {
                    "lat": lat, "lon": lon,
                    "accuracy_m": error[0] if error and len(error) == 1 else None,
                }
    except (struct.error, ValueError, IndexError):
        pass
    return out


def utc_now_text() -> str:
    """This machine's clock, in UTC, as a provenance record writes it."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def photo_provenance(
    data: bytes,
    attached_at: str,
    device_fix: dict | None = None,
    position_note: str = "not_requested",
    stored: str = "original",
) -> dict:
    """The provenance record for one photograph, from its original bytes.

    ``attached_at`` is the device clock when it was attached, in UTC
    (:func:`utc_now_text`). ``device_fix`` is ``{"lat", "lon",
    "accuracy_m"}`` from the device, used only when the file carries no
    position of its own; ``position_note`` is the code saying why there is
    no position when neither gives one (a key of
    ``evidence.position_notes``). ``stored`` is "original" or "downscaled".
    """
    data = bytes(data)
    exif = read_exif(data)
    record = {
        "format": PROVENANCE_FORMAT,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "attached_at": attached_at,
        "taken_at": exif["taken_at"] or attached_at,
        "time_source": "exif" if exif["taken_at"] else "device",
        "position": None,
        "position_source": "none",
        "position_note": position_note,
        "stored": stored,
    }
    if exif["gps"] is not None:
        record.update(position=exif["gps"], position_source="exif", position_note="")
    elif device_fix and device_fix.get("lat") is not None and device_fix.get("lon") is not None:
        accuracy = device_fix.get("accuracy_m")
        record.update(position={
            "lat": float(device_fix["lat"]), "lon": float(device_fix["lon"]),
            "accuracy_m": float(accuracy) if accuracy is not None else None,
        }, position_source="device", position_note="")
    return record


def _shown_time(text: str) -> str:
    return str(text).replace("T", " ").removesuffix("Z")


def describe_provenance(record) -> dict:
    """The record as a report prints it: ``{"time", "position", "hash"}``.

    A photograph with no record (one attached before records existed) gets
    the catalogue's "no provenance recorded" sentence as its time and empty
    position and hash, so nothing is printed that was never recorded.
    """
    if not isinstance(record, dict) or not record.get("sha256"):
        return {"time": phrase("evidence.no_provenance"), "position": "", "hash": ""}
    time_sources = phrase_table("evidence.time_sources")
    shown = phrase("evidence.time", time=_shown_time(record.get("taken_at") or ""),
                   source=time_sources.get(str(record.get("time_source") or ""), ""))
    position = record.get("position")
    if isinstance(position, dict) and position.get("lat") is not None:
        accuracy = position.get("accuracy_m")
        where = phrase(
            "evidence.position", lat=float(position["lat"]), lon=float(position["lon"]),
            accuracy=(phrase("evidence.accuracy_m", m=float(accuracy))
                      if accuracy is not None else phrase("evidence.accuracy_unknown")),
            source=phrase_table("evidence.position_sources").get(
                str(record.get("position_source") or ""), ""),
        )
    else:
        notes = phrase_table("evidence.position_notes")
        where = notes.get(record.get("position_note") or "", notes["not_requested"])
    return {
        "time": shown,
        "position": where,
        "hash": phrase("evidence.hash", short=str(record["sha256"])[:16]),
    }

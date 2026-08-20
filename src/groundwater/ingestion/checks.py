"""Metadata consistency checks.

Field sheets are often filled by copying the previous sheet, so wrong
districts, communities and coordinates slip through (the Rokel survey
report states "Port Loko" for a sounding whose coordinates fall in the
Western Area). These checks flag such conflicts before they reach a
report.

Where a point falls is decided by the bundled chiefdom polygons
(``data/sl_chiefdoms_geoboundaries.geojson``) and the chiefdom ->
current-district crosswalk, the same route
:mod:`groundwater.coverage` uses to place a water point. The bounding
boxes in ``data/sl_districts.csv`` remain as the fallback for a point
outside every chiefdom - a coastal, border or offshore position - with
a buffer so a borderline point is not flagged.

The boxes were the whole test once, and they were too coarse to do the
job this module exists for. Sierra Leone's districts interlock, so 35
of the 120 box pairs overlap, and a box big enough to hold a district
holds a good deal of its neighbours too. Measured over 166 points each
verified inside its own chiefdom, 178 of the 2,490 possible
wrong-district statements - about one in fourteen - sat inside the
stated district's box and went unflagged. The polygons miss none of
them.
"""

from __future__ import annotations

import csv
from importlib import resources
from typing import Iterable

from ..geo import infer_zone_for_sierra_leone, utm_distance_m, utm_to_geographic
from ..models import DataFlag, SiteMetadata

_BUFFER_DEG = 0.05  # about 5.5 km; used only for the bounding-box fallback

#: How far from a district's edge a point may sit and still be read as
#: possibly inside it. Set to the Douglas-Peucker tolerance the chiefdom
#: rings were simplified with in ``web/build_geodata.py``, because that is
#: what the ambiguity actually is: about 445 m of drawing error along every
#: boundary. A handheld GPS fix is good to ten metres or so and does not
#: come into it.
#:
#: It is deliberately not ``_BUFFER_DEG``. Five and a half kilometres of
#: slack is what let one wrong district statement in fourteen through the
#: box test, and restoring it here would give that back.
_BORDER_TOLERANCE_DEG = 0.004

# Sierra Leone in geographic coordinates, generous margin
_SL_BOUNDS = (-13.6, -10.0, 6.7, 10.2)  # lon_min, lon_max, lat_min, lat_max


def _fmt_latlon(lat: float, lon: float) -> str:
    """Human-readable coordinates with correct hemisphere letters.

    Sierra Leone is in the western hemisphere, so longitudes are negative and
    must read 'W', not 'E'.
    """
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.4f} {ns}, {abs(lon):.4f} {ew}"


def _load_districts() -> dict[str, dict]:
    with resources.files("groundwater.data").joinpath("sl_districts.csv").open(
        "r", encoding="utf-8"
    ) as fh:
        rows = list(csv.DictReader(fh))
    return {
        row["district"].strip().lower(): {
            "district": row["district"],
            "province": row["province"],
            "lon_min": float(row["lon_min"]),
            "lon_max": float(row["lon_max"]),
            "lat_min": float(row["lat_min"]),
            "lat_max": float(row["lat_max"]),
        }
        for row in rows
    }


_DISTRICTS = None


def districts() -> dict[str, dict]:
    global _DISTRICTS
    if _DISTRICTS is None:
        _DISTRICTS = _load_districts()
    return _DISTRICTS


def _candidate_districts(name: str) -> list[str]:
    """Every district a stated name could mean.

    Sheets do not always name a district. "Western Area" is the province
    over Western Area Urban and Western Area Rural, and a sheet that says
    only that has not said which - so both are returned and a point in
    either is consistent with what was written.

    Resolving to one of them instead, as this did while the check was
    made against bounding boxes, is a guess. The boxes overlap enough to
    hide it; polygons do not, and the guess surfaces as a conflict
    reported against a sheet that was never wrong.
    """
    key = name.strip().lower()
    if not key:
        return []
    table = districts()
    if key in table:
        return [table[key]["district"]]
    # "Western Area" without urban/rural, "Western Urban", abbreviations
    hits = [table[k]["district"] for k in table if key in k or k in key]
    if hits:
        return hits
    if "western" in key:
        return [table["western area urban"]["district"],
                table["western area rural"]["district"]]
    return []


def _normalise_district(name: str) -> str | None:
    """The lookup key for a stated district name, when it names just one."""
    candidates = _candidate_districts(name)
    if len(candidates) != 1:
        return None
    return candidates[0].strip().lower()


_CHIEFDOM_INDEX: tuple | None = None


def _chiefdom_index() -> tuple:
    """The chiefdom polygons and their crosswalk, parsed once."""
    global _CHIEFDOM_INDEX
    if _CHIEFDOM_INDEX is None:
        from ..coverage import load_chiefdom_district, load_chiefdom_polys

        _CHIEFDOM_INDEX = (load_chiefdom_polys(), load_chiefdom_district())
    return _CHIEFDOM_INDEX


def district_of_coordinates(lat: float, lon: float) -> str | None:
    """The district a point actually falls in, or ``None`` outside them all.

    Point -> chiefdom -> current district, so the answer covers Karene and
    Falaba even though the district boundary release predates them.
    ``None`` is not "nowhere": it is a point offshore, across the border,
    or in the gap simplified boundaries leave along the coast, and the
    caller falls back to the boxes rather than treating it as a conflict.
    """
    from ..coverage import district_of_point

    polys, crosswalk = _chiefdom_index()
    return district_of_point(lat, lon, polys, crosswalk) or None


def _distance_to_districts_deg(lat: float, lon: float, names: list[str]) -> float:
    """Distance from a point to the nearest edge of any of these districts.

    In degrees, with longitude scaled by the cosine of the latitude so the
    two axes are comparable. Only reached when a conflict is about to be
    reported, so the cost of walking the rings is paid once and rarely.
    """
    import math

    import numpy as np

    polys, crosswalk = _chiefdom_index()
    wanted = set(names)
    scale = math.cos(math.radians(lat))
    point = np.array([lon * scale, lat])
    best = math.inf
    for poly in polys:
        if crosswalk.get(poly.name) not in wanted:
            continue
        for ring in poly.rings:
            pts = ring.copy()
            pts[:, 0] *= scale
            a, b = pts[:-1], pts[1:]
            ab = b - a
            length2 = (ab ** 2).sum(axis=1)
            length2[length2 == 0] = 1e-18
            t = (((point - a) * ab).sum(axis=1) / length2).clip(0.0, 1.0)
            closest = a + t[:, None] * ab
            best = min(best, float(np.hypot(*(point - closest).T).min()))
    return best


def districts_containing(lat: float, lon: float, buffer_deg: float = _BUFFER_DEG) -> list[str]:
    """Districts whose (approximate) box contains the point."""
    hits = []
    for key, box in districts().items():
        if (
            box["lon_min"] - buffer_deg <= lon <= box["lon_max"] + buffer_deg
            and box["lat_min"] - buffer_deg <= lat <= box["lat_max"] + buffer_deg
        ):
            hits.append(box["district"])
    return hits


def check_site_consistency(site: SiteMetadata, context: str = "") -> list[DataFlag]:
    """Check one site record: coordinates against country, zone and district."""
    flags: list[DataFlag] = []
    ctx = context or site.community or ""

    if site.easting is None or site.northing is None:
        flags.append(
            DataFlag("info", "missing_coordinates", "No GPS coordinates recorded.", ctx)
        )
        return flags

    zone = site.utm_zone
    if zone is None:
        zone = infer_zone_for_sierra_leone(site.easting)
        flags.append(
            DataFlag(
                "info",
                "utm_zone_assumed",
                f"UTM zone not recorded; assumed {zone}N from the easting.",
                ctx,
            )
        )
    lat, lon = utm_to_geographic(site.easting, site.northing, zone)

    lon_min, lon_max, lat_min, lat_max = _SL_BOUNDS
    if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
        flags.append(
            DataFlag(
                "error",
                "coordinates_outside_country",
                f"Coordinates convert to {_fmt_latlon(lat, lon)} which is outside "
                "Sierra Leone; check easting/northing and the UTM zone.",
                ctx,
            )
        )
        return flags

    stated = _candidate_districts(site.district)
    if site.district and not stated:
        flags.append(
            DataFlag(
                "warning",
                "unknown_district",
                f"District '{site.district}' is not a recognised Sierra Leone "
                "district name.",
                ctx,
            )
        )
    elif stated:
        actual = district_of_coordinates(lat, lon)
        if actual is not None:
            likely = [actual]
            note = ""
            # A point just over the line is not a wrong district. The rings
            # are simplified, so the line itself is only drawn to about
            # 445 m, and a site on a boundary can fall either side of it
            # without anybody having written anything wrong.
            inside = actual in stated or (
                _distance_to_districts_deg(lat, lon, stated)
                <= _BORDER_TOLERANCE_DEG
            )
        else:
            # Outside every chiefdom: offshore, across the border, or in the
            # gap a simplified coastline leaves. The boxes are all there is.
            boxes = [b for b in districts().values() if b["district"] in stated]
            inside = any(
                b["lon_min"] - _BUFFER_DEG <= lon <= b["lon_max"] + _BUFFER_DEG
                and b["lat_min"] - _BUFFER_DEG <= lat <= b["lat_max"] + _BUFFER_DEG
                for b in boxes
            )
            likely = districts_containing(lat, lon)
            note = (
                " The point lies outside every mapped chiefdom, so this was "
                "judged on approximate district extents."
            )
        if not inside:
            hint = f" The point falls in {', '.join(likely)}." if likely else ""
            flags.append(
                DataFlag(
                    "warning",
                    "district_coordinate_conflict",
                    f"Stated district '{site.district}' does not contain the "
                    f"coordinates ({_fmt_latlon(lat, lon)}).{hint}{note} "
                    "Verify against the field notes.",
                    ctx,
                )
            )
    return flags


def check_group_consistency(
    sites: Iterable[tuple[str, SiteMetadata]], max_separation_km: float = 5.0
) -> list[DataFlag]:
    """Cross-record checks for one survey or project.

    Flags differing client/community/district values between sheets of
    the same project and points unexpectedly far apart.
    """
    flags: list[DataFlag] = []
    records = list(sites)
    if len(records) < 2:
        return flags

    for field in ("client", "community", "district"):
        values = {}
        for label, site in records:
            value = getattr(site, field).strip()
            if value:
                values.setdefault(value.lower(), (value, []))[1].append(label)
        if len(values) > 1:
            detail = "; ".join(
                f"'{v}' on {', '.join(labels)}" for v, labels in values.values()
            )
            flags.append(
                DataFlag(
                    "warning",
                    f"inconsistent_{field}",
                    f"Different {field} values within one project: {detail}. "
                    "This usually comes from copying the previous sheet.",
                )
            )

    # Pairwise separation, measured on the ground rather than by subtracting
    # raw eastings. Sierra Leone straddles UTM zones 28N and 29N, and each
    # zone restarts its easting at its own central meridian: two sites 2 km
    # apart either side of the 12 degrees W boundary differ by about 659 km
    # on paper. Every point is converted through its own zone first.
    points = []
    for label, site in records:
        utm = site.utm  # resolves the zone, inferring it when unrecorded
        if utm is not None:
            points.append((label, utm))
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            li, ui = points[i]
            lj, uj = points[j]
            try:
                dist_km = utm_distance_m(ui, uj) / 1000.0
            except (ValueError, ZeroDivisionError, OverflowError):
                # An unconvertible coordinate is already reported per site by
                # check_site_consistency; it must not sink the whole check.
                continue
            if dist_km > max_separation_km:
                flags.append(
                    DataFlag(
                        "warning",
                        "points_far_apart",
                        f"{li} and {lj} are {dist_km:.1f} km apart, which is "
                        "unusually far for one site; check the coordinates.",
                    )
                )
    return flags


def check_all(records: Iterable[tuple[str, SiteMetadata]]) -> list[DataFlag]:
    """Per-site and cross-site checks for a set of (label, site) records."""
    records = list(records)
    flags: list[DataFlag] = []
    for label, site in records:
        flags.extend(check_site_consistency(site, context=label))
    flags.extend(check_group_consistency(records))
    return flags

"""Metadata consistency checks.

Field sheets are often filled by copying the previous sheet, so wrong
districts, communities and coordinates slip through (the Rokel survey
report states "Port Loko" for a sounding whose coordinates fall in the
Western Area). These checks flag such conflicts before they reach a
report.

District extents are approximate bounding boxes bundled with the
package (``data/sl_districts.csv``); they are meant to catch gross
copy-over errors, not to adjudicate points near district boundaries.
A configurable buffer keeps borderline points from being flagged.
"""

from __future__ import annotations

import csv
from importlib import resources
from typing import Iterable

from ..geo import infer_zone_for_sierra_leone, utm_to_geographic
from ..models import DataFlag, SiteMetadata

_BUFFER_DEG = 0.05  # about 5.5 km; boundary points are not flagged

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


def _normalise_district(name: str) -> str | None:
    """Map a stated district name onto the lookup table."""
    key = name.strip().lower()
    if not key:
        return None
    table = districts()
    if key in table:
        return key
    # "Western Area" without urban/rural, "Western Urban", abbreviations
    candidates = [k for k in table if key in k or k in key]
    if candidates:
        return candidates[0]
    if "western" in key:
        return "western area rural"
    return None


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

    stated = _normalise_district(site.district)
    if site.district and stated is None:
        flags.append(
            DataFlag(
                "warning",
                "unknown_district",
                f"District '{site.district}' is not a recognised Sierra Leone "
                "district name.",
                ctx,
            )
        )
    elif stated is not None:
        box = districts()[stated]
        inside = (
            box["lon_min"] - _BUFFER_DEG <= lon <= box["lon_max"] + _BUFFER_DEG
            and box["lat_min"] - _BUFFER_DEG <= lat <= box["lat_max"] + _BUFFER_DEG
        )
        if not inside:
            likely = districts_containing(lat, lon)
            hint = f" The point falls in {', '.join(likely)}." if likely else ""
            flags.append(
                DataFlag(
                    "warning",
                    "district_coordinate_conflict",
                    f"Stated district '{site.district}' does not contain the "
                    f"coordinates ({_fmt_latlon(lat, lon)}).{hint} District "
                    "extents are approximate; verify against the field notes.",
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

    # pairwise separation
    points = []
    for label, site in records:
        if site.easting is not None and site.northing is not None:
            points.append((label, site.easting, site.northing))
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            li, ei, ni = points[i]
            lj, ej, nj = points[j]
            dist_km = ((ei - ej) ** 2 + (ni - nj) ** 2) ** 0.5 / 1000.0
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

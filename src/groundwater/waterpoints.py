"""Existing water points near a site: the rehabilitate-or-drill decision.

Before a programme spends money drilling a new borehole it is worth
asking what is already on the ground. A broken but *improved* handpump
200 m away is usually far cheaper to rehabilitate than a fresh borehole,
and a working improved source inside the service radius may mean the
community is already served. This module answers, for a proposed site,
"what water points already exist nearby, are they working, and does that
change the drill-new decision?" using the Water Point Data Exchange
(WPDx+), the global open dataset of rural water points.

Design
------
The network call is deliberately thin and *optional*. ``fetch_water_points``
is the only function that touches the internet; it fails soft with a typed
``WaterPointFetchError`` and takes an injectable opener so it is testable
offline. Every unit of analysis below it is a pure function over
already-fetched records, so the rehab-or-drill logic is fully unit-tested
without connectivity and the app degrades gracefully where there is none
(the common field situation in rural Sierra Leone).

Data source
-----------
Water Point Data Exchange - Plus (WPdx+), https://www.waterpointdata.org,
published under CC BY 4.0. Field names follow the WPDx data standard; the
parser accepts the documented ``lat_deg`` / ``status_clean`` style keys and
tolerant fallbacks so a schema tweak does not silently drop every point.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from typing import Callable, Iterable

WPDX_CREDIT = (
    "Water points: Water Point Data Exchange (WPdx+), CC BY 4.0, "
    "https://www.waterpointdata.org"
)

# WPdx+ is served from a Socrata endpoint; the resource id is documented but
# kept overridable so a future dataset id needs no code change.
WPDX_DOMAIN = "data.waterpointdata.org"
WPDX_RESOURCE = "eqje-vguj"

# how far around a site to look, and the radius inside which an existing
# working source is treated as already serving the site. 500 m is a common
# rural handpump service distance (RWSN / Sphere order of magnitude).
DEFAULT_SEARCH_RADIUS_M = 1000.0
SERVICE_RADIUS_M = 500.0

_EARTH_RADIUS_M = 6371000.0

# recommendation codes returned by ``rehab_vs_drill``
DRILL_NEW = "drill_new"
ASSESS_REHAB = "assess_rehab"
VERIFY_NEED = "verify_need"


class WaterPointFetchError(RuntimeError):
    """Raised when water points cannot be fetched (offline, timeout, HTTP)."""


@dataclass
class WaterPoint:
    """One water point from WPDx, reduced to the fields siting cares about."""

    row_id: str
    lat: float
    lon: float
    functional: bool | None  # True, False, or None when unknown/unreported
    status: str  # raw status text, e.g. "Functional, needs repair"
    source: str  # water source, e.g. "Borehole"
    technology: str  # water technology, e.g. "Hand Pump - India Mark II"
    install_year: int | None
    adm2: str  # district / second admin level, as recorded upstream
    distance_m: float | None = None  # filled in by ``points_within``

    @property
    def improved(self) -> bool:
        """Whether the source is an improved type worth rehabilitating.

        A borehole, tubewell, protected well or spring, or a piped supply is
        an improved source; an unprotected well/spring or surface water is
        not, so it is not a rehabilitation alternative to a new borehole.

        The unimproved check runs first because "unprotected" contains
        "protected": a "Protected Spring" is improved, an "Unprotected
        Spring" is not, and both must resolve correctly.
        """
        text = f"{self.source} {self.technology}".lower()
        unimproved = ("unprotected", "unimproved", "open well", "open dug",
                      "surface", "river", "stream", "pond", "rainwater")
        if any(word in text for word in unimproved):
            return False
        improved = ("borehole", "tubewell", "tube well", "protected",
                    "piped", "hand pump", "handpump", "mechani")
        return any(word in text for word in improved)

    def as_row(self) -> dict:
        """Compact dict for a results table."""
        state = ("Functional" if self.functional else "Non-functional"
                 if self.functional is False else "Unknown")
        return {
            "Distance (m)": round(self.distance_m) if self.distance_m is not None
            else None,
            "Status": state,
            "Source": self.source or "",
            "Technology": self.technology or "",
            "Installed": self.install_year,
        }


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two lat/lon points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2)
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _first(record: dict, *keys: str):
    """First present, non-empty value among ``keys`` (with '#'-prefixed twins)."""
    for key in keys:
        for variant in (key, "#" + key):
            if variant in record:
                value = record[variant]
                if value not in (None, ""):
                    return value
    return None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _functional_from(status_text: str, status_id) -> bool | None:
    """Map WPDx status to functional True / False / None.

    ``status_clean`` text is authoritative when present ("Functional",
    "Non-Functional", "Functional, needs repair"); ``status_id`` ("Yes"/"No")
    is the fallback. A source that is functional but needs repair still
    delivers water, so it counts as functional.
    """
    text = (status_text or "").strip().lower()
    if text:
        if "non" in text or "not functional" in text or "abandoned" in text:
            return False
        # match "functional" as a whole word, so "functionality" (used in
        # "unknown functionality") does not read as functional.
        if "functional" in re.findall(r"[a-z]+", text):
            return True
    sid = str(status_id or "").strip().lower()
    if sid in ("yes", "y", "true", "1"):
        return True
    if sid in ("no", "n", "false", "0"):
        return False
    return None


def parse_wpdx_records(records: Iterable[dict]) -> list[WaterPoint]:
    """Parse raw WPDx JSON rows into :class:`WaterPoint` objects.

    Rows without a usable latitude/longitude are skipped rather than raising,
    so one malformed record does not lose the whole response.
    """
    points: list[WaterPoint] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        lat = _to_float(_first(record, "lat_deg", "latitude", "lat"))
        lon = _to_float(_first(record, "lon_deg", "longitude", "lon"))
        if lat is None or lon is None:
            continue
        status_text = str(_first(record, "status_clean", "status") or "")
        points.append(
            WaterPoint(
                row_id=str(_first(record, "row_id", "wpdx_id", "objectid") or ""),
                lat=lat,
                lon=lon,
                functional=_functional_from(
                    status_text, _first(record, "status_id", "status")
                ),
                status=status_text,
                source=str(_first(record, "water_source_clean",
                                  "water_source", "source") or ""),
                technology=str(_first(record, "water_tech_clean",
                                      "water_tech", "technology") or ""),
                install_year=_to_int(_first(record, "install_year")),
                adm2=str(_first(record, "clean_adm2", "adm2") or ""),
            )
        )
    return points


def points_within(
    points: Iterable[WaterPoint], lat: float, lon: float, radius_m: float
) -> list[WaterPoint]:
    """Points within ``radius_m`` of (lat, lon), each stamped with its distance,
    sorted nearest first."""
    out: list[WaterPoint] = []
    for point in points:
        distance = _haversine_m(lat, lon, point.lat, point.lon)
        if distance <= radius_m:
            out.append(replace(point, distance_m=distance))
    out.sort(key=lambda p: p.distance_m)
    return out


def functionality_summary(points: Iterable[WaterPoint]) -> dict:
    """Counts and the functional rate for a set of water points."""
    points = list(points)
    functional = sum(1 for p in points if p.functional is True)
    non_functional = sum(1 for p in points if p.functional is False)
    unknown = sum(1 for p in points if p.functional is None)
    reported = functional + non_functional
    return {
        "total": len(points),
        "functional": functional,
        "non_functional": non_functional,
        "unknown": unknown,
        "functional_rate": (functional / reported * 100.0) if reported else None,
    }


def rehab_vs_drill(
    points: Iterable[WaterPoint],
    lat: float,
    lon: float,
    *,
    search_radius_m: float = DEFAULT_SEARCH_RADIUS_M,
    service_radius_m: float = SERVICE_RADIUS_M,
) -> dict:
    """Turn nearby water points into a rehabilitate-or-drill recommendation.

    Logic, in priority order:

    * a *working improved* source inside the service radius -> the community
      may already be served; verify the need before drilling;
    * otherwise a *non-functional improved* source nearby -> a rehabilitation
      candidate, usually cheaper than a new borehole;
    * otherwise -> new construction is the reasonable option, noting the
      nearest working source if one exists beyond the service radius.
    """
    nearby = points_within(points, lat, lon, search_radius_m)
    functional = [p for p in nearby if p.functional is True]
    non_functional_improved = [
        p for p in nearby if p.functional is False and p.improved
    ]
    served = [p for p in functional if p.improved
              and p.distance_m <= service_radius_m]

    summary = functionality_summary(nearby)
    common = {
        "n_nearby": len(nearby),
        "search_radius_m": search_radius_m,
        "service_radius_m": service_radius_m,
        "summary": summary,
        "rehab_candidates": [p.as_row() | {"_distance": p.distance_m}
                             for p in non_functional_improved],
    }

    if served:
        nearest = served[0]
        return {
            **common,
            "recommendation": VERIFY_NEED,
            "headline": (
                f"A working {nearest.source or 'improved source'} is already "
                f"{round(nearest.distance_m)} m away."
            ),
            "rationale": (
                "An improved, functional source sits inside the "
                f"{round(service_radius_m)} m service radius, so the site may "
                "already be served. Confirm demand (population, queue times, "
                "dry-season reliability) before committing to a new borehole."
            ),
        }

    if non_functional_improved:
        nearest = non_functional_improved[0]
        return {
            **common,
            "recommendation": ASSESS_REHAB,
            "headline": (
                f"A broken {nearest.source or 'improved source'} is "
                f"{round(nearest.distance_m)} m away - a rehabilitation "
                "candidate."
            ),
            "rationale": (
                "A non-functional improved source is nearby. Rehabilitating an "
                "existing point is usually far cheaper than a new borehole; "
                "assess it (yield, cause of failure, spare parts) before "
                "drilling."
            ),
        }

    if not nearby:
        return {
            **common,
            "recommendation": DRILL_NEW,
            "headline": (
                f"No mapped water point within {round(search_radius_m)} m."
            ),
            "rationale": (
                "No existing water point is mapped near the site, so new "
                "construction is likely justified. Field-verify, since WPDx "
                "coverage is not exhaustive."
            ),
        }

    note = ""
    if functional:
        distance = functional[0].distance_m
        if distance > service_radius_m:
            note = (
                f" The nearest working source is {round(distance)} m away, "
                f"beyond the {round(service_radius_m)} m service radius."
            )
        else:
            # inside the service radius but not an improved source, so it is
            # not a rehabilitation alternative to a borehole.
            note = (
                f" The nearest working source is {round(distance)} m away but "
                "is not an improved source suitable for rehabilitation."
            )
    return {
        **common,
        "recommendation": DRILL_NEW,
        "headline": "No rehabilitation candidate nearby." + note,
        "rationale": (
            "Nearby points are either working but beyond the service radius or "
            "not improved sources, so there is no cheaper rehabilitation "
            "alternative. New construction is reasonable." + note
        ),
    }


def fetch_water_points(
    lat: float,
    lon: float,
    radius_m: float = DEFAULT_SEARCH_RADIUS_M,
    *,
    timeout: float = 20.0,
    limit: int = 5000,
    domain: str = WPDX_DOMAIN,
    resource: str = WPDX_RESOURCE,
    urlopen: Callable | None = None,
) -> list[dict]:
    """Fetch raw WPDx rows in a bounding box around (lat, lon).

    A bounding-box query on the standard ``lat_deg``/``lon_deg`` columns is
    used (rather than a Socrata ``within_circle`` on a geo column) so the
    request does not depend on a particular geometry field name. Distance
    filtering to a true radius is done client-side by :func:`points_within`.

    Raises :class:`WaterPointFetchError` on any network, HTTP or decode
    failure; the caller (and the app) treats that as "offline / unavailable".
    """
    opener = urlopen or urllib.request.urlopen
    # metres -> degrees; guard the cosine near the poles (irrelevant for
    # Sierra Leone but keeps the maths well-defined everywhere).
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * max(math.cos(math.radians(lat)), 1e-6))
    where = (
        f"lat_deg between {lat - dlat} and {lat + dlat} "
        f"AND lon_deg between {lon - dlon} and {lon + dlon}"
    )
    # $order by the Socrata row id makes a capped result deterministic across
    # runs (a truncated slice is at least the same slice every time).
    query = urllib.parse.urlencode(
        {"$where": where, "$limit": int(limit), "$order": ":id"}
    )
    url = f"https://{domain}/resource/{resource}.json?{query}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "groundwater-toolkit/waterpoints"}
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = response.read()
        data = json.loads(payload)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise WaterPointFetchError(
            f"Could not reach the Water Point Data Exchange: {exc}"
        ) from exc
    if not isinstance(data, list):
        raise WaterPointFetchError(
            "Unexpected response from the Water Point Data Exchange "
            "(expected a list of records)."
        )
    return data


def parse_wpdx_csv(text: str) -> list[WaterPoint]:
    """Parse a WPDx CSV export into :class:`WaterPoint` records.

    A WPDx/Socrata CSV export uses the same column names as the JSON API
    (``lat_deg``, ``lon_deg``, ``status_clean``, ``water_source_clean`` ...),
    so the rows feed straight into :func:`parse_wpdx_records`. This is the
    fully offline input path - a user downloads their country's export and
    uploads it, no network required.
    """
    return parse_wpdx_records(csv.DictReader(io.StringIO(text)))


def water_points_near(
    lat: float,
    lon: float,
    radius_m: float = DEFAULT_SEARCH_RADIUS_M,
    **fetch_kwargs,
) -> list[WaterPoint]:
    """Fetch, parse and distance-filter water points near a site (one call).

    Convenience wrapper for the app; raises :class:`WaterPointFetchError` when
    the data cannot be fetched.
    """
    raw = fetch_water_points(lat, lon, radius_m, **fetch_kwargs)
    return points_within(parse_wpdx_records(raw), lat, lon, radius_m)

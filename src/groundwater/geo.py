"""Coordinate handling: WGS84 geographic and UTM zones 28N / 29N.

Implements the transverse Mercator projection with the Krueger series
(Karney 2011 formulation, terms to n**4), which is accurate to well
under a millimetre across a UTM zone. This keeps the toolkit free of
heavy GIS dependencies; if pyproj is installed the same API is used
transparently for validation.

Sierra Leone spans two UTM zones. West of 12 degrees W (Freetown
peninsula, Port Loko, Kambia, most of the coast) is zone 28N with
central meridian 15 degrees W. East of 12 degrees W is zone 29N with
central meridian 9 degrees W.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# WGS84 ellipsoid
_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)
_E = math.sqrt(_E2)
_N = _F / (2 - _F)  # third flattening

_K0 = 0.9996
_FALSE_EASTING = 500000.0

# Rectifying radius
_A1 = _A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64)

# Krueger series coefficients (Karney 2011, order n^4)
_ALPHA = (
    _N / 2 - 2 * _N**2 / 3 + 5 * _N**3 / 16 + 41 * _N**4 / 180,
    13 * _N**2 / 48 - 3 * _N**3 / 5 + 557 * _N**4 / 1440,
    61 * _N**3 / 240 - 103 * _N**4 / 140,
    49561 * _N**4 / 161280,
)
_BETA = (
    _N / 2 - 2 * _N**2 / 3 + 37 * _N**3 / 96 - _N**4 / 360,
    _N**2 / 48 + _N**3 / 15 - 437 * _N**4 / 1440,
    17 * _N**3 / 480 - 37 * _N**4 / 840,
    4397 * _N**4 / 161280,
)


@dataclass(frozen=True)
class UTMCoordinate:
    easting: float
    northing: float
    zone: int
    hemisphere: str = "N"

    def __str__(self) -> str:
        return (
            f"{self.easting:.0f} mE, {self.northing:.0f} mN "
            f"(UTM {self.zone}{self.hemisphere})"
        )


def utm_zone_from_lon(lon: float) -> int:
    """UTM zone number for a longitude in degrees."""
    return int((lon + 180) // 6) + 1


def _central_meridian(zone: int) -> float:
    return -183.0 + 6.0 * zone


def geographic_to_utm(lat: float, lon: float, zone: int | None = None) -> UTMCoordinate:
    """Convert WGS84 latitude/longitude (degrees) to UTM.

    If ``zone`` is omitted the natural zone for the longitude is used.
    Passing a zone allows forcing the survey's working zone near the
    28N/29N boundary at 12 degrees W.
    """
    if zone is None:
        zone = utm_zone_from_lon(lon)
    lam0 = math.radians(_central_meridian(zone))
    phi = math.radians(lat)
    lam = math.radians(lon) - lam0

    t = math.tan(phi)
    sigma = math.sinh(_E * math.atanh(_E * t / math.sqrt(1 + t * t)))
    tau_p = t * math.sqrt(1 + sigma * sigma) - sigma * math.sqrt(1 + t * t)

    xi_p = math.atan2(tau_p, math.cos(lam))
    eta_p = math.asinh(math.sin(lam) / math.hypot(tau_p, math.cos(lam)))

    xi = xi_p
    eta = eta_p
    for j, alpha in enumerate(_ALPHA, start=1):
        xi += alpha * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        eta += alpha * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)

    easting = _FALSE_EASTING + _K0 * _A1 * eta
    northing = _K0 * _A1 * xi
    hemisphere = "N"
    if lat < 0:
        northing += 10000000.0
        hemisphere = "S"
    return UTMCoordinate(easting, northing, zone, hemisphere)


def utm_to_geographic(
    easting: float, northing: float, zone: int, hemisphere: str = "N"
) -> tuple[float, float]:
    """Convert UTM to WGS84 latitude/longitude in degrees."""
    if hemisphere.upper().startswith("S"):
        northing = northing - 10000000.0
    xi = northing / (_K0 * _A1)
    eta = (easting - _FALSE_EASTING) / (_K0 * _A1)

    xi_p = xi
    eta_p = eta
    for j, beta in enumerate(_BETA, start=1):
        xi_p -= beta * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        eta_p -= beta * math.cos(2 * j * xi) * math.sinh(2 * j * eta)

    tau_p = math.sin(xi_p) / math.hypot(math.sinh(eta_p), math.cos(xi_p))
    lam = math.atan2(math.sinh(eta_p), math.cos(xi_p))

    # Invert tau'(tau) by Newton iteration (Karney 2011).
    tau = tau_p / math.sqrt(1 - _E2)
    for _ in range(10):
        sigma = math.sinh(_E * math.atanh(_E * tau / math.sqrt(1 + tau * tau)))
        f_tau = tau * math.sqrt(1 + sigma * sigma) - sigma * math.sqrt(1 + tau * tau)
        d_tau = (
            (math.sqrt((1 + sigma * sigma) * (1 + tau * tau)) - sigma * tau)
            * (1 - _E2)
            * math.sqrt(1 + tau * tau)
            / (1 + (1 - _E2) * tau * tau)
        )
        delta = (tau_p - f_tau) / d_tau
        tau += delta
        if abs(delta) < 1e-14:
            break

    lat = math.degrees(math.atan(tau))
    lon = math.degrees(lam) + _central_meridian(zone)
    return lat, lon


def geodesic_distance_m(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Distance in metres between two WGS84 points, along the ellipsoid.

    Vincenty's inverse formula, which is accurate to well under a millimetre
    at the distances this toolkit deals with. Vincenty does not converge for
    near-antipodal points; nothing in a country survey is antipodal, but the
    spherical (haversine) value is returned rather than raising if it ever
    happens.
    """
    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    b = _A * (1 - _F)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    l_diff = math.radians(lon2 - lon1)
    u1 = math.atan((1 - _F) * math.tan(phi1))
    u2 = math.atan((1 - _F) * math.tan(phi2))
    sin_u1, cos_u1 = math.sin(u1), math.cos(u1)
    sin_u2, cos_u2 = math.sin(u2), math.cos(u2)

    lam = l_diff
    sin_sigma = cos_sigma = sigma = cos_sq_alpha = cos_2sigma_m = 0.0
    for _ in range(200):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.hypot(
            cos_u2 * sin_lam,
            cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam,
        )
        if sin_sigma == 0:
            return 0.0  # coincident points
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sigma
        cos_sq_alpha = 1 - sin_alpha * sin_alpha
        cos_2sigma_m = (
            cos_sigma - 2 * sin_u1 * sin_u2 / cos_sq_alpha
            if cos_sq_alpha != 0
            else 0.0  # equatorial line
        )
        c = _F / 16 * cos_sq_alpha * (4 + _F * (4 - 3 * cos_sq_alpha))
        lam_prev = lam
        lam = l_diff + (1 - c) * _F * sin_alpha * (
            sigma
            + c
            * sin_sigma
            * (cos_2sigma_m + c * cos_sigma * (-1 + 2 * cos_2sigma_m**2))
        )
        if abs(lam - lam_prev) < 1e-12:
            break
    else:
        return _haversine_distance_m(lat1, lon1, lat2, lon2)

    u_sq = cos_sq_alpha * (_A * _A - b * b) / (b * b)
    big_a = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    big_b = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    delta_sigma = (
        big_b
        * sin_sigma
        * (
            cos_2sigma_m
            + big_b
            / 4
            * (
                cos_sigma * (-1 + 2 * cos_2sigma_m**2)
                - big_b
                / 6
                * cos_2sigma_m
                * (-3 + 4 * sin_sigma**2)
                * (-3 + 4 * cos_2sigma_m**2)
            )
        )
    )
    return b * big_a * (sigma - delta_sigma)


def _haversine_distance_m(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Great-circle distance on a sphere of the WGS84 mean radius."""
    radius = 6371008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lam = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def utm_distance_m(a: UTMCoordinate, b: UTMCoordinate) -> float:
    """Ground distance between two UTM points, each read in its own zone.

    Subtracting eastings from different zones is meaningless: the false
    easting restarts at every central meridian, so two sites a couple of
    kilometres apart either side of the 12 degrees W boundary between zones
    28N and 29N differ by hundreds of thousands of metres on paper. Each
    point is converted with its own zone first, then measured on the
    ellipsoid.
    """
    lat1, lon1 = utm_to_geographic(a.easting, a.northing, a.zone, a.hemisphere)
    lat2, lon2 = utm_to_geographic(b.easting, b.northing, b.zone, b.hemisphere)
    return geodesic_distance_m(lat1, lon1, lat2, lon2)


def infer_zone_for_sierra_leone(easting: float) -> int:
    """Best guess of the UTM zone for a Sierra Leone easting.

    Sierra Leone lies roughly between 13.4 W and 10.2 W. In zone 28N
    valid eastings fall around 620000 to 800000 (east of the central
    meridian); in zone 29N around 200000 to 500000 (west of it).
    Overlap is impossible in-country, so the easting alone identifies
    the zone.
    """
    return 28 if easting > 550000 else 29


_LATLON_TOKEN = re.compile(r"^([+-]?\d*\.?\d+)\s*([NSEWnsew])?$")


def parse_latlon(text: str) -> tuple[float, float] | None:
    """Parse "lat, lon" as a field crew writes it, or None if unreadable.

    Accepts a signed decimal pair (``8.4657, -13.2317``), hemisphere letters
    trailing (``8.4657 N, 13.2317 W``) or attached (``13.2317W``), letters
    leading (``N 8.4657, W 13.2317``), and comma, semicolon or whitespace
    separators.

    Every longitude in Sierra Leone is west, and a handheld GPS writes that
    as a W rather than a minus sign. Discarding the letter and taking the
    number at face value puts the site 26 degrees east of where it is -
    silently, on the wrong side of the continent - so the letter is read as
    a sign. A letter that contradicts an explicit sign (``-13.2317 E``) is
    refused rather than guessed at, and an explicit E/W on the first value
    means the pair was written longitude first.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    tokens = [t for t in re.split(r"[,;\s]+", raw) if t]

    values: list[dict] = []
    pending: str | None = None          # a leading N/S/E/W awaiting its number
    for token in tokens:
        if len(token) == 1 and token.upper() in ("N", "S", "E", "W"):
            letter = token.upper()
            if values and values[-1]["letter"] is None:
                values[-1]["letter"] = letter      # trailing "8.4657 N"
            else:
                pending = letter                   # leading "N 8.4657"
            continue
        match = _LATLON_TOKEN.match(token)
        if match is None:
            return None
        values.append({
            "value": float(match.group(1)),
            "letter": match.group(2).upper() if match.group(2) else pending,
        })
        pending = None

    if len(values) != 2:
        return None

    def signed(entry: dict) -> float | None:
        value, letter = entry["value"], entry["letter"]
        if not math.isfinite(value):
            return None
        if letter is None:
            return value
        negative = letter in ("S", "W")
        if value < 0 and not negative:
            return None                 # "-13.2317 E" contradicts itself
        if value < 0:
            return value
        return -value if negative else value

    first, second = values
    if first["letter"] in ("E", "W") or second["letter"] in ("N", "S"):
        first, second = second, first
    lat, lon = signed(first), signed(second)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    return lat, lon

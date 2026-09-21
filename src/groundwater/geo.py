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


# Sierra Leone's own extent, in degrees: about 6.9 to 10.0 north, and 10.3
# to 13.3 WEST. These bands recognise a longitude typed without its western
# sign; nothing here moves a coordinate that carries a sign or a letter.
SIERRA_LEONE_LAT_BAND = (6.9, 10.0)
SIERRA_LEONE_LON_BAND = (-13.3, -10.3)

_ZONE_NUMBER_RE = re.compile(r"\d+")


def parse_utm_zone(value) -> int | None:
    """The UTM zone a cell states, or ``None`` when it states no single zone.

    Sheets write the zone as ``28N``, ``28``, ``zone 28`` or - when the
    operator copies the label into the value cell - ``Zone 28``. Reading
    such a cell means taking the number that follows the label and nothing
    else. A value cell mistaken for a label let the neighbouring easting
    through as the zone, so a site recorded in zone 28N was carried as
    "zone 708958" and projected tens of degrees from the survey.

    A cell naming more than one number states no single zone - "28N or 29N"
    is the sheet's own instruction, not an answer - and neither does a
    number outside the 1 to 60 a UTM zone can be. Both are refused rather
    than guessed at, so the caller can say the zone is unrecorded and fall
    back to the easting.

    >>> parse_utm_zone("28N")
    28
    >>> parse_utm_zone("Zone 28")
    28
    >>> parse_utm_zone("708958") is None
    True
    >>> parse_utm_zone("UTM Zone (28N or 29N)") is None
    True
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or float(value) != int(value):
            return None
        numbers = [int(value)]
    else:
        numbers = [int(found) for found in _ZONE_NUMBER_RE.findall(str(value))]
    if len(numbers) != 1 or not 1 <= numbers[0] <= 60:
        return None
    return numbers[0]


_LATLON_TOKEN = re.compile(r"^([+-]?\d*\.?\d+)\s*([NSEWnsew])?$")
_HEMISPHERES = ("N", "S", "E", "W")

# Degree, minute and second marks as a phone, a handheld GPS or a sheet
# writes them; they separate the parts of a coordinate rather than belonging
# to any of them, so they are read as spaces.
_SEXAGESIMAL_MARKS = str.maketrans({
    "°": " ", "º": " ", "∘": " ",
    "'": " ", "’": " ", "′": " ",
    '"': " ", "”": " ", "″": " ",
})

_UNREADABLE = "Could not read those coordinates."
_AMBIGUOUS = (
    "Two numbers with nothing between them are either a decimal pair or one "
    "degrees-and-minutes value. Separate a pair with a comma "
    "(8.4657, -13.2317), or mark the hemispheres (8 27.942 N, 13 13.902 W)."
)


@dataclass(frozen=True)
class LatLonReading:
    """What :func:`read_latlon` made of a pasted coordinate.

    ``lat`` and ``lon`` are ``None`` when the text was refused, and
    ``message`` then says why, in a sentence an operator can act on. A
    reading that succeeded carries a ``code`` and a ``message`` only when
    something was assumed rather than read, so whatever shows the position
    can show the assumption with it.
    """

    lat: float | None = None
    lon: float | None = None
    code: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.lat is not None and self.lon is not None


class _CoordinateRefused(Exception):
    """A coordinate the parser will not read, carrying the reason why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _latlon_components(raw: str) -> list[dict]:
    """Split a pasted coordinate into its two components.

    Numbers accumulate into the component being read. A hemisphere letter, a
    comma or semicolon, or an explicit sign ends that component and starts
    the next, because a number of minutes or seconds is never signed and
    never carries a hemisphere of its own.
    """
    components: list[dict] = []
    current: dict | None = None

    def open_component(letter: str | None = None) -> dict:
        nonlocal current
        current = {"numbers": [], "letter": letter, "signed": False,
                   "negative": False}
        components.append(current)
        return current

    segments = re.split(r"[,;]", raw.translate(_SEXAGESIMAL_MARKS))
    for index, segment in enumerate(segments):
        if index:
            current = None
        for token in segment.split():
            if len(token) == 1 and token.upper() in _HEMISPHERES:
                letter = token.upper()
                if (current is not None and current["letter"] is None
                        and current["numbers"]):
                    current["letter"] = letter       # trailing "8.4657 N"
                    current = None
                else:
                    current = None
                    open_component(letter)           # leading "N 8.4657"
                continue
            match = _LATLON_TOKEN.match(token)
            if match is None:
                raise _CoordinateRefused("latlon_unreadable", _UNREADABLE)
            number = float(match.group(1))
            if not math.isfinite(number):
                raise _CoordinateRefused("latlon_unreadable", _UNREADABLE)
            signed = match.group(1)[0] in "+-"
            if signed and current is not None and current["numbers"]:
                current = None                       # "8 -13.2317" is a pair
            component = current if current is not None else open_component()
            if not component["numbers"]:
                component["signed"] = signed
                component["negative"] = match.group(1).startswith("-")
            component["numbers"].append(number)
            if match.group(2):
                component["letter"] = match.group(2).upper()   # "13.2317W"
                current = None

    if (len(components) == 1 and components[0]["letter"] is None
            and len(components[0]["numbers"]) == 2):
        # Nothing separates the two numbers, so they are either a decimal
        # pair or one degrees-and-minutes value. Where they could be either,
        # refusing is the only honest reading: "8 27.942" read as a pair
        # lands 2000 km from the same text read as degrees and minutes.
        only = components[0]
        degrees, rest = only["numbers"]
        if degrees == math.floor(degrees) and 0 <= rest < 60:
            raise _CoordinateRefused("latlon_unreadable", _AMBIGUOUS)
        components = [
            {"numbers": [degrees], "letter": None,
             "signed": only["signed"], "negative": only["negative"]},
            {"numbers": [rest], "letter": None,
             "signed": False, "negative": False},
        ]
    return components


def _component_degrees(component: dict, what: str) -> float:
    """One component of a pasted pair as signed decimal degrees."""
    numbers = component["numbers"]
    if not numbers or len(numbers) > 3:
        raise _CoordinateRefused("latlon_unreadable", _UNREADABLE)
    magnitude = abs(numbers[0])
    if len(numbers) > 1:
        # Degrees and decimal minutes, or degrees, minutes and seconds.
        # Read as decimal degrees, "8 27.942 N" came back as latitude 27.942
        # and longitude 8: the sheet's own numbers, in the wrong units and
        # the wrong order.
        minutes = numbers[1]
        if magnitude != math.floor(magnitude):
            raise _CoordinateRefused("latlon_unreadable", (
                f"Read the {what} as degrees and minutes, but "
                f"{numbers[0]:g} is not a whole number of degrees."))
        if not 0 <= minutes < 60:
            raise _CoordinateRefused("latlon_unreadable", (
                f"Read the {what} as degrees and minutes, but {minutes:g} "
                "is not a number of minutes (0 up to 60)."))
        magnitude += minutes / 60.0
        if len(numbers) == 3:
            seconds = numbers[2]
            if minutes != math.floor(minutes):
                raise _CoordinateRefused("latlon_unreadable", (
                    f"Read the {what} as degrees, minutes and seconds, but "
                    f"{minutes:g} is not a whole number of minutes."))
            if not 0 <= seconds < 60:
                raise _CoordinateRefused("latlon_unreadable", (
                    f"Read the {what} as degrees, minutes and seconds, but "
                    f"{seconds:g} is not a number of seconds (0 up to 60)."))
            magnitude += seconds / 3600.0
    negative = component["negative"]
    letter = component["letter"]
    if letter:
        letter_negative = letter in ("S", "W")
        if negative and not letter_negative:
            raise _CoordinateRefused("latlon_sign_contradiction", (
                f"The {what} is written both as a negative number and as "
                f"{letter}, which contradict each other."))
        negative = negative or letter_negative
    return -magnitude if negative else magnitude


def read_latlon(text: str) -> LatLonReading:
    """Read "lat, lon" as a field crew writes it, saying what was assumed.

    Accepts a signed decimal pair (``8.4657, -13.2317``), hemisphere letters
    trailing (``8.4657 N, 13.2317 W``) or attached (``13.2317W``), letters
    leading (``N 8.4657, W 13.2317``), degrees and decimal minutes
    (``8 27.942 N, 13 13.902 W``), degrees, minutes and seconds
    (``8 27 56.5 N, 13 13 54.1 W``), with or without degree marks, and
    comma, semicolon or whitespace separators.

    Every longitude in Sierra Leone is west, and a handheld GPS writes that
    as a W rather than a minus sign. Discarding the letter and taking the
    number at face value puts the site 26 degrees east of where it is -
    silently, on the wrong side of the continent - so the letter is read as
    a sign. A letter that contradicts an explicit sign (``-13.2317 E``) is
    refused rather than guessed at, and an explicit E/W on the first value
    means the pair was written longitude first.

    A positive longitude between 10.3 and 13.3 degrees, carrying neither a
    sign nor a letter and paired with a latitude inside Sierra Leone's own
    band, is a western longitude whose minus sign was never typed:
    "8.4657, 13.2317" is Freetown short of a sign, not a site 2,900 km east
    in central Africa. That reading is taken - the country is what this
    toolkit is for, and read as written the pair used to become a zone-33
    position relabelled 29N, landing 270 km inside Sierra Leone from where
    the site is - but it is the parser's reading rather than the sheet's, so
    it comes back under the ``longitude_west_assumed`` code with a sentence
    saying what was assumed. Nothing downstream may present it as read.

    Where two numbers could be either a decimal pair or one
    degrees-and-minutes value ("8 27.942"), the text is refused rather than
    read as a guess.
    """
    raw = (text or "").strip()
    if not raw:
        return LatLonReading(code="latlon_unreadable", message=_UNREADABLE)
    try:
        components = _latlon_components(raw)
        if not components:
            raise _CoordinateRefused("latlon_unreadable", _UNREADABLE)
        if len(components) < 2:
            raise _CoordinateRefused("latlon_incomplete", (
                "Read one coordinate where a latitude and a longitude are "
                "both needed."))
        if len(components) > 2:
            raise _CoordinateRefused("latlon_incomplete", (
                "Read more than two values where only a latitude and a "
                "longitude are expected."))
        first, second = components
        if first["letter"] in ("E", "W") or second["letter"] in ("N", "S"):
            first, second = second, first
        lat = _component_degrees(first, "latitude")
        lon = _component_degrees(second, "longitude")
    except _CoordinateRefused as refused:
        return LatLonReading(code=refused.code, message=refused.message)
    if abs(lat) > 90 or abs(lon) > 180:
        return LatLonReading(code="latlon_out_of_range", message=(
            "A latitude runs to 90 degrees and a longitude to 180; these "
            "do not."))
    if (lon > 0 and not second["signed"] and second["letter"] is None
            and SIERRA_LEONE_LAT_BAND[0] <= lat <= SIERRA_LEONE_LAT_BAND[1]
            and SIERRA_LEONE_LON_BAND[0] <= -lon <= SIERRA_LEONE_LON_BAND[1]):
        return LatLonReading(lat=lat, lon=-lon, code="longitude_west_assumed",
                             message=(
                                 f"Longitude {lon:g} was read as {lon:g} W: "
                                 "every longitude in Sierra Leone is west, "
                                 f"and {lon:g} east is some 2,900 km away in "
                                 f"central Africa. Type -{lon:g} or {lon:g} W "
                                 "to record the sign rather than leave it "
                                 "assumed."))
    return LatLonReading(lat=lat, lon=lon)


def parse_latlon(text: str) -> tuple[float, float] | None:
    """The pasted pair as ``(lat, lon)``, or ``None`` if it was refused.

    :func:`read_latlon` returns the same reading together with the reason a
    text was refused, or the assumption a reading rests on. Anything that
    shows a coordinate to an operator should use that instead, so a refusal
    reaches them as a sentence and an assumption is never presented as
    something the sheet said.
    """
    reading = read_latlon(text)
    return (reading.lat, reading.lon) if reading.ok else None

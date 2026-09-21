"""Metadata consistency checks.

Field sheets are often filled by copying the previous sheet, so wrong
districts, communities and coordinates slip through (the Rokel survey
report states "Port Loko" for a sounding whose coordinates fall in the
Western Area). These checks flag such conflicts before they reach a
report.

The district a point is in is read from the bundled geoBoundaries
polygons, through the mapping package's own lookups - the same answer
the maps, the coverage ranking and the browser build give. The package
also bundles a table of district bounding boxes
(``data/sl_districts.csv``) and this check used to be judged against
it; boxes drawn around districts overlap over half the country, so one
point came back as "Western Area Rural, Moyamba", and they miss ground
the districts actually cover. The table is still bundled for the
name-and-province list the apps offer, but nothing here consults it.

The polygon layer is geoBoundaries as released, which predates the 2017
creation of Karene and Falaba; the bundled chiefdom crosswalk supplies
those two, and where even that cannot place a point the check says so
rather than choosing a district for it.
"""

from __future__ import annotations

import functools
from typing import Iterable

from ..geo import infer_zone_for_sierra_leone, utm_distance_m, utm_to_geographic
from ..models import DataFlag, SiteMetadata

# Sierra Leone in geographic coordinates, generous margin
_SL_BOUNDS = (-13.6, -10.0, 6.7, 10.2)  # lon_min, lon_max, lat_min, lat_max

# "Western Area" is a region, not one of the sixteen districts: it is the
# peninsula's two districts together. Field sheets write it constantly, so
# it is read as both of them - a site anywhere in either satisfies it -
# rather than as Western Area Urban, which is what taking the first
# substring hit did, flagging every correctly labelled site on the
# southern peninsula.
_REGIONS: dict[str, tuple[str, ...]] = {
    "western area": ("Western Area Urban", "Western Area Rural"),
}

# The two districts created in 2017 and the pre-2017 district each was
# split out of. The bundled district polygons predate the split, so where
# the chiefdom layer cannot place a point and those polygons answer
# instead, "Bombali" is an answer that cannot tell Bombali from Karene.
_SPLIT_FROM = {"Karene": "Bombali", "Falaba": "Koinadugu"}


def _fmt_latlon(lat: float, lon: float) -> str:
    """Human-readable coordinates with correct hemisphere letters.

    Sierra Leone is in the western hemisphere, so longitudes are negative and
    must read 'W', not 'E'.
    """
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.4f} {ns}, {abs(lon):.4f} {ew}"


@functools.lru_cache(maxsize=1)
def district_names() -> tuple[str, ...]:
    """The sixteen districts, spelled as the boundary lookups spell them.

    Taken from the chiefdom -> current-district crosswalk rather than from
    a list written out here, so the names this check accepts are exactly
    the names the point lookup can return. Imported inside the function
    because the ingestion package is imported to read a spreadsheet and
    should not drag the boundary data in with it.
    """
    from ..coverage import load_chiefdom_district

    return tuple(sorted(set(load_chiefdom_district().values())))


def _key(name: str) -> str:
    """A stated name reduced to what can be compared: case, spacing, and a
    trailing "district" the sheet added ("Port Loko District")."""
    words = str(name or "").replace(".", " ").split()
    if len(words) > 1 and words[-1].lower().rstrip(",") in ("district", "districts"):
        words = words[:-1]
    return " ".join(words).lower()


@functools.lru_cache(maxsize=1)
def _named_areas() -> dict[str, tuple[str, ...]]:
    """Every administrative name read here -> the districts it covers."""
    areas = {_key(name): (name,) for name in district_names()}
    areas.update(_REGIONS)
    return areas


def _prefix_hit(key: str, candidate: str) -> bool:
    return candidate.startswith(key)


def _words_hit(key: str, candidate: str) -> bool:
    """True when every word of the stated name begins a word of the
    candidate, in order: "Western Urban" for Western Area Urban."""
    words = iter(candidate.split())
    return all(
        any(word.startswith(part) for word in words) for part in key.split()
    )


def match_district(name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read a district name off a sheet: ``(resolved, candidates)``.

    ``resolved`` is the districts the name can only mean - one district,
    or the two of the Western Area for a name that means the region. It is
    empty when the name matches nothing, and empty when it matches more
    than one district, in which case ``candidates`` lists what it could
    have meant. An exact name wins; then a name that prefixes exactly one
    ("Bomb" for Bombali); then one whose words begin the words of exactly
    one ("Western Urban"). Matching on the first substring hit, which is
    what this did, read "Ko" as Port Loko and "Western Area" as Western
    Area Urban; a name that could be two districts is worth refusing, and
    saying which two, rather than silently picking one of them.
    """
    key = _key(name)
    if not key:
        return (), ()
    areas = _named_areas()
    if key in areas:
        return areas[key], areas[key]
    for hit in (_prefix_hit, _words_hit):
        names = [known for known in areas if hit(key, known)]
        if not names:
            continue
        covered = {d for known in names for d in areas[known]}
        for known in names:
            # "Western" matches both halves of the Western Area and the
            # region over them, and the region is a single answer; "Ko"
            # matches Koinadugu and Kono, and there is no such answer.
            if set(areas[known]) == covered:
                return areas[known], areas[known]
        return (), tuple(sorted(covered))
    return (), ()


def districts_named(name: str) -> tuple[str, ...]:
    """The districts a district name written on a sheet can only mean."""
    return match_district(name)[0]


def district_at(lat: float, lon: float) -> tuple[str, str, bool]:
    """Where the bundled boundaries put a point.

    Returns ``(chiefdom, district, current)``. ``current`` is True when the
    district is the one the point is in today, which is what the chiefdom
    layer plus the crosswalk give; it is False when only the district
    polygons could answer, because those predate the 2017 split and so
    cannot tell Bombali from Karene or Koinadugu from Falaba. Both are
    empty when no polygon holds the point.

    The mapping package owns the point-in-polygon lookups and is imported
    here rather than at module scope because it pulls in matplotlib, and
    reading a field sheet must not depend on a plotting stack.
    """
    from ..mapping.regional import chiefdom_of, district_of

    chiefdom, district = chiefdom_of(lat, lon)
    if district:
        return chiefdom, district, True
    # No chiefdom holds the point, and none is within the seam tolerance of
    # it either. district_of is asked next, and with the bundled layer it
    # now resolves through the same chiefdom polygons, so in practice it
    # answers nothing here: a caller that supplies its own district layer is
    # the only way this returns a name, and that name may be pre-2017.
    return "", district_of(lat, lon), False


def _or_list(names: Iterable[str]) -> str:
    """A list an operator reads as a sentence: "Koinadugu or Kono"."""
    names = list(names)
    if len(names) < 2:
        return "".join(names)
    return f"{', '.join(names[:-1])} or {names[-1]}"


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

    resolved, candidates = match_district(site.district)
    if site.district and not resolved:
        if len(candidates) > 1:
            flags.append(
                DataFlag(
                    "warning",
                    "ambiguous_district",
                    f"District '{site.district}' could be "
                    f"{_or_list(candidates)}; it is not read as any of them. "
                    "Write the district out in full.",
                    ctx,
                )
            )
        else:
            flags.append(
                DataFlag(
                    "warning",
                    "unknown_district",
                    f"District '{site.district}' is not a recognised Sierra "
                    "Leone district name, so the coordinates were not checked "
                    "against it.",
                    ctx,
                )
            )
    elif resolved:
        chiefdom, found, current = district_at(lat, lon)
        if not found:
            flags.append(
                DataFlag(
                    "warning",
                    "coordinates_outside_districts",
                    f"The boundary polygons place the coordinates "
                    f"({_fmt_latlon(lat, lon)}) in no district, so district "
                    f"'{site.district}' could not be checked against them; "
                    "the point may be offshore, over the border, or in a gap "
                    "between the boundaries.",
                    ctx,
                )
            )
        elif found not in resolved:
            # A point no chiefdom polygon holds is placed by the district
            # polygons, and those predate the 2017 split: for a site stated
            # to be in Karene or Falaba they can only name the district it
            # was split from, which neither confirms nor contradicts it.
            split = next(
                (d for d in resolved if not current and _SPLIT_FROM.get(d) == found),
                "",
            )
            if split:
                flags.append(
                    DataFlag(
                        "info",
                        "district_predates_boundaries",
                        f"District '{site.district}' could not be checked "
                        f"against the coordinates ({_fmt_latlon(lat, lon)}): "
                        "no chiefdom polygon holds them, and the district "
                        f"polygons predate the 2017 creation of {split}, so "
                        f"the {found} they give is the district {split} was "
                        "split from.",
                        ctx,
                    )
                )
            elif current:
                flags.append(
                    DataFlag(
                        "warning",
                        "district_coordinate_conflict",
                        f"Stated district '{site.district}' does not contain "
                        f"the coordinates ({_fmt_latlon(lat, lon)}), which "
                        f"fall in {chiefdom} chiefdom, {found} district. "
                        "Verify against the field notes.",
                        ctx,
                    )
                )
            else:
                flags.append(
                    DataFlag(
                        "warning",
                        "district_coordinate_conflict",
                        f"Stated district '{site.district}' does not contain "
                        f"the coordinates ({_fmt_latlon(lat, lon)}). No "
                        "chiefdom polygon holds them; the district polygons, "
                        "which predate the 2017 creation of Karene and "
                        f"Falaba, place them in {found}. Verify against the "
                        "field notes.",
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
            if not value:
                continue
            # Two sheets of one project can spell the same ground two ways -
            # "Western Area" on one and "Western Area Rural" on the other -
            # and each passes its own single-sheet check. Compared as plain
            # strings they were then reported together as an inconsistency,
            # so the two checks contradicted each other. Districts are
            # grouped by what the name can mean, not by how it is typed.
            key = value.lower()
            if field == "district":
                resolved = match_district(value)[0]
                if resolved:
                    # "Western Area" can mean either half of the region and
                    # "Western Area Rural" only one of them; the two overlap,
                    # so they are one value here. Only names that can share
                    # no district at all are a disagreement.
                    key = next(
                        (
                            existing
                            for existing in values
                            if isinstance(existing, frozenset)
                            and existing & set(resolved)
                        ),
                        frozenset(resolved),
                    )
            values.setdefault(key, (value, []))[1].append(label)
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

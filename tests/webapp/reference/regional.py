"""Where a report is set: the "regional" entry of ``reference.json``.
"""

from __future__ import annotations

from groundwater.geo import geographic_to_utm
from groundwater.models import SiteMetadata

from .common import clean


# ------------------------------------------------------ where a report is set

#: Positions the regional checks place a site at: the Rokel sounding on the
#: Bullom sands, the Freetown Complex under a sheet that says Port Loko, a
#: dyke the Precambrian encloses in Kono, Kamakwie in Karene, the interior,
#: and a point in the Falaba chiefdoms the boundary layer predates.
_REGIONAL_POSITIONS = [
    (8.375866051953114, -13.102371011661704, "Western Area"),
    (8.40, -13.18, "Port Loko"),
    (9.392, -10.396, "Kono"),
    (9.4967, -12.2405, "Karene"),
    (7.96, -11.74, "Bo"),
    (9.85, -11.3, "Falaba"),
    (8.35, -13.10, "Western Area"),
    (8.77, -12.79, "Port Loko District"),
]

#: District names as sheets write them: the region, a trailing "District",
#: the two districts the boundary layer predates, lower case, a name that
#: could be two districts, and one that is no district at all.
_REGIONAL_DISTRICTS = ["Karene", "Falaba", "Western Area", "Port Loko District",
                       "western area rural", "Ko", "Atlantis", ""]


def regional_reference() -> dict:
    """The area each report maps, what it is called, and the ground under it.

    Every chiefdom and district window is here, because the browser sized
    them from the largest ring alone and 41 of the 180 came out more than a
    tenth different, which the scale caveat then quoted in the client's
    copy of the report.
    """
    from groundwater.geo import parse_utm_zone
    from groundwater.mapping.regional import (
        _BGS_PUBLISHER_NOTE,
        _home_district,
        _scale_caveat,
        area_window,
        load_admin,
        load_chiefdoms,
    )
    from groundwater.reporting.context import area_map_note
    from groundwater.reporting.geophysical import _geology_for

    _, districts = load_admin()

    def window(site):
        found = area_window(site)
        if found is None:
            return None
        return clean([found.lon, found.lat, found.radius_km, found.label,
                      found.exact])

    def placed(lat, lon, district, community="T"):
        utm = geographic_to_utm(lat, lon)
        return SiteMetadata(community=community, district=district,
                            easting=utm.easting, northing=utm.northing,
                            utm_zone=utm.zone)

    cases = ([{"chiefdom": area.name, "district": ""} for area in load_chiefdoms()]
             + [{"chiefdom": "", "district": area.name} for area in districts]
             + [{"chiefdom": "", "district": name} for name in _REGIONAL_DISTRICTS]
             + [{"chiefdom": name, "district": "Port Loko"}
                for name in ("Bureh Kasseh Maconteh", "Bureh Kasseh Ma",
                             "sanda magbolontor")])
    windows = []
    for case in cases:
        site = SiteMetadata(community="T", **case)
        name, names, chiefdoms = _home_district(site, districts)
        windows.append(dict(case, window=window(site), note=area_map_note(site),
                            home=[name, sorted(names),
                                  sorted(area.name for area in chiefdoms)]))

    positions = []
    for lat, lon, district in _REGIONAL_POSITIONS:
        site = placed(lat, lon, district)
        # the position the site actually carries, after the round trip
        # through UTM, so the browser is handed the same point
        at_lat, at_lon = site.latlon
        name, names, chiefdoms = _home_district(site, districts)
        positions.append({
            "district": district, "lat": clean(at_lat), "lon": clean(at_lon),
            "window": window(site), "note": area_map_note(site),
            "home": [name, sorted(names), sorted(area.name for area in chiefdoms)],
            "geology": _geology_for(site, ""),
        })
    unplaced = [{"district": district,
                 "geology": _geology_for(SiteMetadata(district=district), "")}
                for district in ("Western Area", "Western Area Rural", "Bo", "")]

    return {
        "windows": windows,
        "positions": positions,
        "unplaced_geology": unplaced,
        "caveats": [
            {"radius_km": radius, "note": note,
             "text": _scale_caveat(radius, 5_000_000, note)}
            for radius, note in ((None, ""), (21.71465, ""), (30.0, ""),
                                 (42.5, _BGS_PUBLISHER_NOTE), (60.0, ""),
                                 (60.5, ""), (6.25, ""))
        ],
        "utm_zones": [
            {"value": value, "zone": parse_utm_zone(value)}
            for value in ("28N", "Zone 28", "29 N", "28N WGS84",
                          "WGS 84 / UTM zone 28N", "WGS-84 29N", "28.0", 28,
                          28.0, 28.5, "708958", "UTM Zone (28N or 29N)", "",
                          "zone 61", "0")
        ],
    }

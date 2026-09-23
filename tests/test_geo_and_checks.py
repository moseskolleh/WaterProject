import math

from groundwater.geo import (
    geodesic_distance_m,
    geographic_to_utm,
    infer_zone_for_sierra_leone,
    utm_distance_m,
    utm_to_geographic,
    utm_zone_from_lon,
)
from groundwater.ingestion.checks import check_group_consistency, check_site_consistency
from groundwater.models import SiteMetadata


def test_utm_round_trip():
    for lat, lon, zone in [(8.3759, -13.1024, 28), (8.0, -11.0, 29), (9.9, -11.5, 29)]:
        utm = geographic_to_utm(lat, lon, zone)
        lat2, lon2 = utm_to_geographic(utm.easting, utm.northing, zone)
        assert math.isclose(lat, lat2, abs_tol=1e-9)
        assert math.isclose(lon, lon2, abs_tol=1e-9)


def test_rokel_coordinates_land_in_western_area():
    lat, lon = utm_to_geographic(708958, 926355, 28)
    assert 8.2 < lat < 8.6
    assert -13.4 < lon < -12.9


def test_zone_helpers():
    assert utm_zone_from_lon(-13.2) == 28
    assert utm_zone_from_lon(-10.5) == 29
    assert infer_zone_for_sierra_leone(708958) == 28
    assert infer_zone_for_sierra_leone(300000) == 29


def test_district_conflict_flagged():
    # the Rokel VES 2 header: says Port Loko, coordinates in the Western Area
    site = SiteMetadata(district="Port Loko", easting=727012, northing=916125, utm_zone=28)
    flags = check_site_consistency(site, context="B (2)")
    assert any(f.code == "district_coordinate_conflict" for f in flags)


def test_matching_district_not_flagged():
    site = SiteMetadata(district="Western Area", easting=708958, northing=926355, utm_zone=28)
    flags = check_site_consistency(site)
    assert not any(f.code == "district_coordinate_conflict" for f in flags)


def test_outside_country_flagged():
    site = SiteMetadata(district="Bo", easting=708958, northing=8926355, utm_zone=28)
    flags = check_site_consistency(site)
    assert any(f.code == "coordinates_outside_country" for f in flags)


def test_group_consistency():
    a = SiteMetadata(client="LWI", community="Rokel", district="Western Area")
    b = SiteMetadata(client="LWI", community="Rokel", district="Port Loko")
    flags = check_group_consistency([("VES 1", a), ("VES 2", b)])
    assert any(f.code == "inconsistent_district" for f in flags)
    assert not any(f.code == "inconsistent_client" for f in flags)


def test_geodesic_distance_matches_known_separations():
    """Vincenty on WGS84, checked against independently computed values."""
    # Freetown to Bo, about 174 km
    d = geodesic_distance_m(8.4657, -13.2317, 7.9647, -11.7383)
    assert abs(d - 173628.0) < 50.0
    # one degree of latitude on the meridian near the equator
    assert abs(geodesic_distance_m(8.0, -12.0, 9.0, -12.0) - 110598.0) < 50.0
    assert geodesic_distance_m(8.0, -12.0, 8.0, -12.0) == 0.0


def test_utm_distance_crosses_the_zone_boundary():
    """Raw eastings from different zones are not comparable.

    Sierra Leone straddles UTM 28N and 29N and each zone restarts its easting
    at its own central meridian, so subtracting one from the other put two
    sites 2.2 km apart 659 km apart - a QA warning on every survey that
    happens to straddle 12 degrees W.
    """
    west = geographic_to_utm(8.50, -12.01)   # zone 28N
    east = geographic_to_utm(8.50, -11.99)   # zone 29N
    assert west.zone == 28 and east.zone == 29
    naive_km = math.hypot(west.easting - east.easting,
                          west.northing - east.northing) / 1000.0
    assert naive_km > 600.0                  # what the old check computed
    assert abs(utm_distance_m(west, east) / 1000.0 - 2.20) < 0.05


def test_group_consistency_does_not_flag_neighbours_across_zones():
    west = geographic_to_utm(8.50, -12.01)
    east = geographic_to_utm(8.50, -11.99)
    a = SiteMetadata(community="Rokel", easting=west.easting,
                     northing=west.northing, utm_zone=west.zone)
    b = SiteMetadata(community="Rokel", easting=east.easting,
                     northing=east.northing, utm_zone=east.zone)
    flags = check_group_consistency([("VES 1", a), ("VES 2", b)])
    assert not any(f.code == "points_far_apart" for f in flags)


def test_group_consistency_still_flags_genuinely_distant_points():
    freetown = geographic_to_utm(8.4657, -13.2317)
    bo = geographic_to_utm(7.9647, -11.7383)
    a = SiteMetadata(community="Rokel", easting=freetown.easting,
                     northing=freetown.northing, utm_zone=freetown.zone)
    b = SiteMetadata(community="Rokel", easting=bo.easting,
                     northing=bo.northing, utm_zone=bo.zone)
    flags = check_group_consistency([("VES 1", a), ("VES 2", b)])
    far = [f for f in flags if f.code == "points_far_apart"]
    assert far and "173." in far[0].message


def test_parse_latlon_reads_hemisphere_letters_as_signs():
    """A handheld GPS writes west as a W, not a minus sign.

    Dropping the letter and taking the number at face value put every Sierra
    Leone site 26 degrees east of where it is - silently, on the wrong side
    of the continent.
    """
    from groundwater.geo import parse_latlon

    freetown = (8.4657, -13.2317)
    assert parse_latlon("8.4657, -13.2317") == freetown
    assert parse_latlon("8.4657 N, 13.2317 W") == freetown
    assert parse_latlon("8.4657N 13.2317W") == freetown
    assert parse_latlon("N 8.4657, W 13.2317") == freetown
    assert parse_latlon("8.4657;-13.2317") == freetown
    # an explicit E/W on the first value means it was written longitude first
    assert parse_latlon("13.2317 W, 8.4657 N") == freetown
    # southern hemisphere still works
    assert parse_latlon("8.4657 S, 13.2317 W") == (-8.4657, -13.2317)


def test_parse_latlon_refuses_what_it_cannot_read():
    from groundwater.geo import parse_latlon

    assert parse_latlon("") is None
    assert parse_latlon("rubbish") is None
    assert parse_latlon("8.4657") is None            # only one value
    assert parse_latlon("200, 5") is None            # out of range
    assert parse_latlon("-13.2317 E, 8.4657") is None  # sign contradicts letter


def test_parse_latlon_round_trips_through_utm():
    """The pasted pair must land on the same metre as the typed one."""
    from groundwater.geo import geographic_to_utm, parse_latlon, utm_to_geographic

    lat, lon = parse_latlon("8.4657 N, 13.2317 W")
    utm = geographic_to_utm(lat, lon)
    back = utm_to_geographic(utm.easting, utm.northing, utm.zone)
    assert abs(back[0] - lat) < 1e-9
    assert abs(back[1] - lon) < 1e-9


def test_parse_latlon_will_not_place_an_unsigned_longitude_outside_the_country():
    """A longitude typed without its minus sign is still a western longitude.

    "8.4657, 13.2317" is Freetown short of a sign. Read as written it became a
    zone-33 position, which the Streamlit page then relabelled 29N: a site
    270 km east of where it is, inside Sierra Leone and with nothing said,
    while the browser stored zone 33 for the same paste.
    """
    from groundwater.geo import geographic_to_utm, parse_latlon, read_latlon

    reading = read_latlon("8.4657, 13.2317")
    assert (reading.lat, reading.lon) == (8.4657, -13.2317)
    assert reading.code == "longitude_west_assumed"
    assert "13.2317 W" in reading.message      # it says what it assumed
    assert geographic_to_utm(reading.lat, reading.lon).zone == 28
    assert parse_latlon("8.4657, 13.2317") == (8.4657, -13.2317)

    # a sign or a letter is read, never overridden, and it is read in silence
    assert read_latlon("8.4657, -13.2317").code == ""
    east = read_latlon("8.4657, 13.2317 E")
    assert (east.lat, east.lon, east.code) == (8.4657, 13.2317, "")
    # and a longitude outside Sierra Leone's band is nothing to assume about
    far = read_latlon("8.4657, 45.0")
    assert (far.lat, far.lon, far.code) == (8.4657, 45.0, "")


def test_parse_latlon_reads_degrees_and_minutes_as_degrees_and_minutes():
    """A pair written "8 27.942 N" is degrees and minutes, not two numbers.

    The parser read the pair as decimal degrees in the order they happened to
    fall, so a handheld GPS reading of the Rokel sounding came back as
    latitude 27.942, longitude 8 - a point in the Mediterranean, 2000 km from
    the sheet it was typed off.
    """
    from groundwater.geo import parse_latlon, read_latlon

    freetown = (8.4657, -13.2317)
    for text in ("8 27.942 N, 13 13.902 W",
                 "8°27.942' N, 13°13.902' W",
                 "N 8 27.942, W 13 13.902"):
        lat, lon = parse_latlon(text)
        assert abs(lat - freetown[0]) < 1e-9
        assert abs(lon - freetown[1]) < 1e-9

    lat, lon = parse_latlon("8 27 56.5 N, 13 13 54.1 W")   # degrees, minutes, seconds
    assert abs(lat - 8.465694) < 1e-6
    assert abs(lon + 13.231694) < 1e-6

    # one coordinate is not a pair, and two bare numbers that could be either
    # a decimal pair or one degrees-and-minutes value are refused, not guessed
    assert read_latlon("8 27.942 N").code == "latlon_incomplete"
    assert parse_latlon("8 27.942") is None
    assert parse_latlon("8 61.5 N, 13 13.902 W") is None   # 61.5 is no minute


def test_every_refused_coordinate_carries_a_sentence():
    """A refusal has to reach the crew as a message, not as a blank box."""
    from groundwater.geo import read_latlon

    for text in ("", "rubbish", "8.4657", "200, 5", "-13.2317 E, 8.4657",
                 "8 27.942", "8 61.5 N, 13 13.902 W"):
        reading = read_latlon(text)
        assert not reading.ok
        assert reading.code and reading.message.endswith(".")


def test_utm_zone_reads_the_number_after_the_label():
    """A zone cell reading "Zone 28" is the zone 28, not a zone of 708958.

    A value cell that looked like a label was taken as one, and the easting
    beside it was read as the zone; a sounding in 28N was carried as zone
    708958 and projected outside the country.
    """
    from groundwater.geo import parse_utm_zone

    assert parse_utm_zone("Zone 28") == 28
    assert parse_utm_zone("28N") == 28
    assert parse_utm_zone("29 N") == 29
    assert parse_utm_zone(28) == 28
    # an easting is not a zone, and neither is the sheet's own instruction
    assert parse_utm_zone("708958") is None
    assert parse_utm_zone("UTM Zone (28N or 29N)") is None
    assert parse_utm_zone("") is None
    assert parse_utm_zone(None) is None

    rokel = dict(district="Western Area", easting=708958, northing=926355)
    assert check_site_consistency(
        SiteMetadata(utm_zone=parse_utm_zone("Zone 28"), **rokel)) == []
    # what cannot be read leaves the zone unrecorded, which the checks infer
    # from the easting and say so, rather than putting the site abroad
    unreadable = check_site_consistency(
        SiteMetadata(utm_zone=parse_utm_zone("708958"), **rokel))
    assert [f.code for f in unreadable] == ["utm_zone_assumed"]
    assert any(f.code == "coordinates_outside_country" for f in
               check_site_consistency(SiteMetadata(utm_zone=708958, **rokel)))


def test_utm_zone_is_read_past_the_datum_and_the_spreadsheet_float():
    """"28N WGS84" states zone 28, and so does a cell read back as "28.0".

    A handheld GPS writes the datum beside the zone and a GIS writes it in
    front ("WGS 84 / UTM zone 28N"); its 84 was counted as a second number,
    the zone refused, and the sheet flagged "UTM zone not recorded" when it
    had recorded one. clean_text turns a numeric cell into "28.0", which was
    refused the same way.
    """
    from groundwater.geo import parse_utm_zone

    assert parse_utm_zone("28N WGS84") == 28
    assert parse_utm_zone("WGS 84 / UTM zone 28N") == 28
    assert parse_utm_zone("29N (WGS-84)") == 29
    assert parse_utm_zone("28.0") == 28
    assert parse_utm_zone(28.0) == 28
    # still refused: a fraction, two zones, a zone no UTM grid has
    assert parse_utm_zone("28.5") is None
    assert parse_utm_zone(28.5) is None
    assert parse_utm_zone("28N or 29N WGS84") is None
    assert parse_utm_zone("zone 61") is None

    rokel = dict(district="Western Area", easting=708958, northing=926355)
    assert check_site_consistency(
        SiteMetadata(utm_zone=parse_utm_zone("28N WGS84"), **rokel)) == []


def _site_at(lat: float, lon: float, district: str) -> SiteMetadata:
    """A site record for a point, carrying the UTM fix a sheet would record."""
    utm = geographic_to_utm(lat, lon)
    return SiteMetadata(district=district, easting=utm.easting,
                        northing=utm.northing, utm_zone=utm.zone)


def test_the_district_check_is_judged_against_the_boundary_polygons():
    """A box drawn round a district is not the district.

    The check was judged against a table of hand-drawn bounding boxes, which
    overlap over half the country, so the second Rokel sounding was reported
    as falling in "Western Area Rural, Moyamba" - two districts at once, the
    second of them 80 km from the point. The bundled geoBoundaries polygons
    that every map in the toolkit already draws give one answer, and name the
    chiefdom the point is in with it.
    """
    flags = check_site_consistency(_site_at(8.2826, -12.9390, "Port Loko"),
                                   context="B (2)")
    conflict = [f for f in flags if f.code == "district_coordinate_conflict"]
    assert len(conflict) == 1
    assert "Koya Rural chiefdom, Western Area Rural district" in conflict[0].message
    assert "Moyamba" not in conflict[0].message


def test_a_correct_district_outside_its_old_bounding_box_is_not_flagged():
    """The boxes missed ground the districts hold, and blamed the sheet for it.

    Kamajei is in Moyamba but sits east of the Moyamba box, which offered Bo
    instead; Buya Romende is in Karene, which no box reached, and the boxes
    answered "Port Loko, Kambia"; Dema is in Bonthe, and for it the boxes had
    no answer at all. All three sheets were right and all three were flagged.
    """
    for lat, lon, district in [(8.2403, -11.8978, "Moyamba"),
                               (8.8199, -12.4496, "Karene"),
                               (7.5895, -12.8655, "Bonthe")]:
        flags = check_site_consistency(_site_at(lat, lon, district))
        assert flags == [], (district, [str(f) for f in flags])


def test_western_area_is_read_as_the_region_it_names():
    """"Western Area" is a region, and it is not Western Area Urban.

    The matcher took the first district name the stated one appeared in, and
    the table lists the urban half first, so "Western Area" - what field
    sheets in the peninsula almost always say - was read as Western Area
    Urban. Every correctly labelled site in Western Area Rural, which is all
    of the peninsula outside Freetown, was flagged as a district conflict.
    The region is read as both of its districts: a site in either satisfies
    it, and a site in neither still does not.
    """
    from groundwater.ingestion.checks import districts_named

    assert districts_named("Western Area") == ("Western Area Urban",
                                               "Western Area Rural")
    assert check_site_consistency(_site_at(8.3383, -13.0700,
                                           "Western Area")) == []  # Waterloo
    assert check_site_consistency(_site_at(8.4657, -13.2317,
                                           "Western Area")) == []  # Freetown
    flags = check_site_consistency(_site_at(8.1600, -12.4300, "Western Area"))
    assert [f.code for f in flags] == ["district_coordinate_conflict"]
    assert "Kaiyamba chiefdom, Moyamba district" in flags[0].message


def test_a_district_name_that_could_be_two_districts_is_refused():
    """"Ko" is not Port Loko, and saying so is better than guessing.

    The matcher accepted the first district whose name contained the stated
    one or was contained by it, so a sheet headed "Ko" was read as Port Loko
    and judged against Port Loko's ground. A name that could be two districts
    now matches neither and says which two it could be, while a name that can
    only be one - shortened, or written without the "Area" the sheet leaves
    out - is still read.
    """
    from groundwater.ingestion.checks import districts_named, match_district

    assert districts_named("Ko") == ()
    assert match_district("Ko")[1] == ("Koinadugu", "Kono")
    flags = check_site_consistency(_site_at(8.7266, -12.7423, "Ko"))
    assert [f.code for f in flags] == ["ambiguous_district"]
    assert "Koinadugu or Kono" in flags[0].message

    assert districts_named("Port Loko District") == ("Port Loko",)
    assert districts_named("Bomb") == ("Bombali",)
    assert districts_named("Western Urban") == ("Western Area Urban",)
    # and a name the country does not carry is not forced onto the nearest one
    assert districts_named("Freetown") == ()
    unknown = check_site_consistency(_site_at(8.4657, -13.2317, "Freetown"))
    assert [f.code for f in unknown] == ["unknown_district"]


def test_a_point_no_boundary_polygon_holds_is_not_given_a_district():
    """A point at sea is not in the district the boxes stretched over it.

    The boxes are rectangles round coastal districts, so a point well offshore
    sat inside two or three of them and the check either confirmed a district
    for it or named one it should have been in. The polygons hold no such
    point, and the check says it could not judge rather than judging.
    """
    flags = check_site_consistency(_site_at(8.1000, -13.4500,
                                            "Western Area Rural"))
    assert [f.code for f in flags] == ["coordinates_outside_districts"]
    assert "offshore" in flags[0].message


def test_ground_no_chiefdom_holds_is_not_judged_by_the_older_district_layer():
    """A point the chiefdoms cannot place is said to be unplaced, and no more.

    The check used to fall back to the pre-2017 district polygons for such a
    point and had a branch for when they answered with the district Karene
    or Falaba was split from. With the bundled layers that branch could not
    be reached - the district lookup resolves through the same chiefdoms -
    and its test reached it only by monkeypatching both lookups, so it held
    a behaviour production never had. The branch is gone, and this holds
    what production does: inside the withheld Maforki wedge, which the
    layer does not carry, a sheet saying Kono is neither confirmed nor
    contradicted, and no district from the older layer is named.
    """
    flags = check_site_consistency(_site_at(8.673, -10.51, "Kono"))
    assert [f.code for f in flags] == ["coordinates_outside_districts"]
    assert "Kono" in flags[0].message and "Koinadugu" not in flags[0].message
    # and a Karene sheet on Kamakwie is placed through the crosswalk
    assert check_site_consistency(_site_at(9.4967, -12.2405, "Karene")) == []
    flags = check_site_consistency(_site_at(9.4967, -12.2405, "Bo"))
    assert [f.code for f in flags] == ["district_coordinate_conflict"]
    assert "Karene district" in flags[0].message


def test_two_spellings_of_one_district_are_not_a_disagreement():
    """The single-sheet check and the cross-sheet check contradicted each other.

    "Western Area" names the region and "Western Area Rural" one of its two
    districts. Each passes its own sheet's check, and compared as plain
    strings the two were then reported together as an inconsistency, so one
    project's sheets were flagged for agreeing.
    """
    from groundwater.ingestion.checks import check_group_consistency
    from groundwater.models import SiteMetadata

    def site(district):
        return SiteMetadata(community="Kuntolo", district=district)

    overlapping = check_group_consistency([
        ("sheet 1", site("Western Area")),
        ("sheet 2", site("Western Area Rural")),
    ])
    assert [f.code for f in overlapping] == []

    # two districts that can share no ground are still a disagreement
    different = check_group_consistency([
        ("sheet 1", site("Western Area Rural")),
        ("sheet 2", site("Bo")),
    ])
    assert [f.code for f in different] == ["inconsistent_district"]

    # and a name that resolves to nothing is not quietly merged into one
    unknown = check_group_consistency([
        ("sheet 1", site("Zzz")),
        ("sheet 2", site("Bo")),
    ])
    assert [f.code for f in unknown] == ["inconsistent_district"]

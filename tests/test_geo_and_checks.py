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

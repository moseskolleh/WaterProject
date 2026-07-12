import math

from groundwater.geo import (
    geographic_to_utm,
    infer_zone_for_sierra_leone,
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

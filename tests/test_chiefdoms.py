"""Chiefdom (ADM3) boundary layer and reverse lookup."""

from groundwater.mapping import chiefdom_of, load_chiefdoms

_DISTRICTS = {
    "Bo", "Bombali", "Bonthe", "Kailahun", "Kambia", "Kenema", "Koinadugu",
    "Kono", "Moyamba", "Port Loko", "Pujehun", "Tonkolili",
    "Western Area Rural", "Western Area Urban",
}


def test_an_enclave_chiefdom_keeps_its_own_points():
    """Nongowa (Kenema district) has Kenema Town cut out of it as an interior
    ring. Keeping only exterior rings credited every water point in a city of
    200,000 to the rural chiefdom around it, and left the town itself looking
    unserved - which is exactly what the coverage-gap ranking is read for."""
    from groundwater.coverage import chiefdom_of_point, load_chiefdom_polys

    polys = load_chiefdom_polys()
    in_town = (7.8726, -11.1905)   # inside the enclave
    in_nongowa = (7.95, -11.05)    # the chiefdom around it

    assert chiefdom_of_point(*in_town, polys) == "Kenema Town"
    assert chiefdom_of_point(*in_nongowa, polys) == "Nongowa"
    assert chiefdom_of(*in_town) == ("Kenema Town", "Kenema")
    assert chiefdom_of(*in_nongowa) == ("Nongowa", "Kenema")


def test_chiefdom_layer_loads_with_parentage():
    areas = load_chiefdoms()
    # 165 geoBoundaries chiefdoms, with the merged two-district "Koya" feature
    # split back into its Kenema and Port Loko lobes
    assert len(areas) == 166
    # every chiefdom carries a valid parent district and a name and geometry
    for area in areas:
        assert area.name
        assert area.district in _DISTRICTS, area.district
        assert area.rings and area.rings[0].shape[1] == 2


def test_chiefdom_of_known_towns():
    assert chiefdom_of(8.4657, -13.2317) == ("West II", "Western Area Urban")  # Freetown
    assert chiefdom_of(8.8817, -12.0442) == ("Makeni Town", "Bombali")  # Makeni
    # Kenema city. Like Freetown and Makeni above it has its own chiefdom,
    # here as an enclave cut out of Nongowa; this used to return the rural
    # chiefdom around the city because interior rings were discarded.
    assert chiefdom_of(7.8767, -11.1875) == ("Kenema Town", "Kenema")


def test_chiefdom_of_offshore_is_empty():
    assert chiefdom_of(8.0, -14.0) == ("", "")


def test_chiefdom_district_agrees_with_district_lookup():
    from groundwater.mapping import district_of

    # for a town well inside the country, the chiefdom's parent district
    # matches the independent district lookup
    chief, district = chiefdom_of(8.8817, -12.0442)
    assert district == district_of(8.8817, -12.0442) == "Bombali"


def test_no_chiefdom_has_a_part_stranded_across_the_country():
    """A chiefdom's parts must lie near one another.

    "Maforki" (Port Loko) shipped with a twelve-point part 250 km east,
    wedged between Mafindor's two lobes in Kono - the two names are one
    letter apart. Because ``district_of_point`` returns the first polygon
    that contains the point, and Maforki is filed before Mafindor, every
    water point on that ground counted towards Port Loko instead of Kono:
    one district's coverage inflated and another's deflated, in the
    ranking that decides where to drill next.

    Sierra Leone is about 350 km across and no chiefdom is a fifth of it,
    so parts a degree apart are a filing error rather than geography.
    """
    from groundwater.coverage import load_chiefdom_polys

    stranded = []
    for poly in load_chiefdom_polys():
        if len(poly.bboxes) < 2:
            continue
        lon_span = max(b[2] for b in poly.bboxes) - min(b[0] for b in poly.bboxes)
        lat_span = max(b[3] for b in poly.bboxes) - min(b[1] for b in poly.bboxes)
        if max(lon_span, lat_span) > 1.0:
            stranded.append((poly.name, round(lon_span, 2), round(lat_span, 2)))
    assert not stranded, f"chiefdoms with parts a degree or more apart: {stranded}"


def test_the_ground_between_mafindors_lobes_is_in_kono():
    """The repair moved that part rather than deleting it.

    Nothing else in the layer covers it, so dropping it would have punched
    a hole in Kono instead of fixing the attribution.
    """
    from groundwater.coverage import (district_of_point, load_chiefdom_district,
                                      load_chiefdom_polys)

    polys = load_chiefdom_polys()
    crosswalk = load_chiefdom_district()
    assert district_of_point(8.6803, -10.5097, polys, crosswalk) == "Kono"


def test_maforki_is_only_in_port_loko():
    from groundwater.coverage import load_chiefdom_polys

    maforki = [p for p in load_chiefdom_polys() if p.name == "Maforki"]
    assert len(maforki) == 1
    for west, _, east, _ in maforki[0].bboxes:
        assert west < -12.0 and east < -12.0, "Maforki has drifted east again"

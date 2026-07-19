"""Chiefdom (ADM3) boundary layer and reverse lookup."""

from groundwater.mapping import chiefdom_of, load_chiefdoms

_DISTRICTS = {
    "Bo", "Bombali", "Bonthe", "Kailahun", "Kambia", "Kenema", "Koinadugu",
    "Kono", "Moyamba", "Port Loko", "Pujehun", "Tonkolili",
    "Western Area Rural", "Western Area Urban",
}


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
    assert chiefdom_of(7.8767, -11.1875) == ("Nongowa", "Kenema")  # Kenema


def test_chiefdom_of_offshore_is_empty():
    assert chiefdom_of(8.0, -14.0) == ("", "")


def test_chiefdom_district_agrees_with_district_lookup():
    from groundwater.mapping import district_of

    # for a town well inside the country, the chiefdom's parent district
    # matches the independent district lookup
    chief, district = chiefdom_of(8.8817, -12.0442)
    assert district == district_of(8.8817, -12.0442) == "Bombali"

"""Chiefdom (ADM3) boundary layer and reverse lookup."""

from groundwater.mapping import chiefdom_of, load_chiefdoms

_DISTRICTS = {
    "Bo", "Bombali", "Bonthe", "Falaba", "Kailahun", "Kambia", "Karene",
    "Kenema", "Koinadugu", "Kono", "Moyamba", "Port Loko", "Pujehun",
    "Tonkolili", "Western Area Rural", "Western Area Urban",
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


def test_the_lookups_return_the_districts_as_they_are_today():
    """Karene and Falaba were created in 2017; the boundary release predates
    them. Kamakwie used to come back as Bombali and Falaba town as
    Koinadugu, and the app pre-filled those districts without a word."""
    from groundwater.mapping.regional import chiefdom_of, district_of, load_chiefdoms

    assert chiefdom_of(9.4967, -12.2417) == ("Sella Limba", "Karene")   # Kamakwie
    assert district_of(9.4967, -12.2417) == "Karene"
    assert district_of(9.8586, -11.3211) == "Falaba"                    # Falaba town
    assert district_of(8.4403, -13.1716) == "Western Area Urban"        # Freetown
    assert district_of(8.7266, -12.7423) == "Port Loko"
    # the layer itself carries the current parentage
    by_name = {area.name: area.district for area in load_chiefdoms()}
    assert by_name["Sella Limba"] == "Karene" and by_name["Sulima"] == "Falaba"
    assert district_of(6.0, -13.5) == ""                                # offshore


def test_no_chiefdom_claims_ground_it_is_nowhere_near():
    """A piece of a chiefdom 250 km from the rest of it is somebody else's.

    geoBoundaries builds its ADM3 layer by dissolving same-named units, and a
    near-name collision there files real ground under the wrong chiefdom.
    "Maforki" (Port Loko) carried a 21 km2 wedge on the Guinea border in Kono,
    247 km from the rest of it, so a borehole sited there was reported - on the
    completion report, in the programme table and in the coverage ranking that
    decides where to drill next - as being in Port Loko. That is not a rounding
    error in a map; it is the wrong district on a document somebody signs.

    web/build_boundary_review.py withholds geometry like that. The real test is
    not that the wedge is gone but that nothing replaced it with another
    confident answer: a point nobody can place has to come back unplaced.
    """
    import json
    from pathlib import Path

    from groundwater.mapping.regional import _bundled_geojson

    for feature in _bundled_geojson("sl_chiefdoms_geoboundaries.geojson")["features"]:
        geometry = feature["geometry"]
        parts = (geometry["coordinates"] if geometry["type"] == "MultiPolygon"
                 else [geometry["coordinates"]])
        if len(parts) < 2:
            continue

        def centre(ring):
            return (sum(p[0] for p in ring) / len(ring),
                    sum(p[1] for p in ring) / len(ring))

        def area(ring):
            return abs(sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
                           for i in range(len(ring) - 1)) / 2)

        home = centre(max(parts, key=lambda p: area(p[0]))[0])
        for part in parts:
            here = centre(part[0])
            km = ((here[0] - home[0]) * 111.32) ** 2 + ((here[1] - home[1]) * 110.57) ** 2
            assert km ** 0.5 < 50, (
                f"{feature['properties']['name']} has a part {km ** 0.5:.0f} km from "
                "the rest of it; run web/build_boundary_review.py"
            )

    # the wedge itself, and an honest answer where it used to be
    assert chiefdom_of(8.673, -10.51) == ("", "")
    assert chiefdom_of(8.72, -12.75) == ("Maforki", "Port Loko")
    assert chiefdom_of(8.65, -10.50) == ("Mafindor", "Kono")

    review = json.loads(
        (Path(__file__).resolve().parents[1] / "src" / "groundwater" / "data"
         / "boundary_review.geojson").read_text(encoding="utf-8"))
    withheld = {f["properties"]["name"] for f in review["features"]}
    assert withheld == {"Maforki"}
    # the file has to say why, and what it is not claiming
    held = review["features"][0]["properties"]
    assert held["proposed_owner"] == "Mafindor"
    assert held["shares_boundary_with"][0]["chiefdom"] == "Mafindor"
    assert "not authority for reassigning ground" in held["decision"]


def test_the_boundary_review_survives_being_rebuilt():
    """Running the repair twice must not quietly empty the review.

    The withheld geometry is no longer in the layer, so a second run cannot
    rediscover it. If the review file were rebuilt from the layer alone it
    would come back empty, the record of what was taken out and why would be
    gone, and CI would report the emptied file as the current state.
    """
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build_boundary_review", repo / "web" / "build_boundary_review.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    chiefdoms, review, withheld = builder.build()
    assert len(withheld) == 1
    assert builder.CHIEFDOMS.read_text(encoding="utf-8") == chiefdoms, (
        "the committed chiefdom layer is stale; "
        "run: python web/build_boundary_review.py"
    )
    assert builder.REVIEW.read_text(encoding="utf-8") == review, (
        "the committed boundary review is stale; "
        "run: python web/build_boundary_review.py"
    )

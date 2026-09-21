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


def test_a_point_in_a_crack_between_two_rings_is_placed_on_the_border_it_fell_on():
    """Every chiefdom ring was simplified on its own, so two rings that were
    one shared border no longer meet exactly and thin slivers of ground - about
    37 km2 of them nationally - are inside no chiefdom at all. A point that
    landed in one used to get a different answer from every lookup that saw it.

    Take the point 21 m inside Paki Masabong on the Bombali/Tonkolili border:
    ``chiefdom_of`` said it was in no chiefdom, ``district_of`` fell through to
    the pre-2017 district polygons and said Tonkolili - the district on the
    other side of the line - and the coverage lookups said nothing at all. A
    crack is metres wide, so a point in one is on a border, not off the map,
    and every lookup now places it on the ring it is nearest to.
    """
    from groundwater.coverage import (
        assign_chiefdoms,
        chiefdom_of_point,
        district_of_point,
        load_chiefdom_district,
        load_chiefdom_polys,
    )
    from groundwater.mapping.regional import district_of
    from groundwater.waterpoints import WaterPoint

    polys = load_chiefdom_polys()
    crosswalk = load_chiefdom_district()

    # 21 m from Paki Masabong (Bombali), 42 m from Kholifa Rowala (Tonkolili)
    lat, lon = 8.8109, -11.8840
    assert chiefdom_of(lat, lon) == ("Paki Masabong", "Bombali")
    assert district_of(lat, lon) == "Bombali"          # was "Tonkolili"
    assert chiefdom_of_point(lat, lon, polys) == "Paki Masabong"
    assert district_of_point(lat, lon, polys, crosswalk) == "Bombali"

    # and the district is the one that exists today. This crack is 23 m from
    # Neya, which is in Falaba; the district polygons predate that district
    # and could only answer Koinadugu, which is what Falaba was split from.
    lat, lon = 8.9609, -10.8840
    assert chiefdom_of(lat, lon) == ("Neya", "Falaba")
    assert district_of(lat, lon) == "Falaba"           # was "Koinadugu"
    assert district_of_point(lat, lon, polys, crosswalk) == "Falaba"

    # the counting walk that places a national pull of water points agrees
    # with the one-point lookups, crack and all
    point = WaterPoint(row_id="", lat=lat, lon=lon, functional=True, status="",
                       source="Borehole", technology="", install_year=None,
                       adm2="")
    assert assign_chiefdoms([point], polys) == ["Neya"]


def test_ground_no_ring_is_near_is_left_unplaced_by_every_lookup():
    """Closing the cracks must not fill the holes.

    A crack is metres wide. The Maforki wedge is 20 km2 of Kono withheld from
    the layer pending review (see above), and the nearest ring to the point
    below is 78 m away - too far to be a seam between two rings that were
    meant to touch. ``district_of`` used to fall through to the pre-2017
    district polygons there and report the wedge as Kono, which is a district
    on a client document arrived at by having nowhere else to look.

    One tolerance governs this, and it is the width of a crack rather than of a
    chiefdom: a point outside every ring by more than that is ground this
    toolkit cannot place, and it says so.
    """
    from groundwater.coverage import (
        CHIEFDOM_EDGE_TOLERANCE_M,
        chiefdom_of_point,
        district_of_point,
        load_chiefdom_district,
        load_chiefdom_polys,
        nearest_chiefdom_index,
    )
    from groundwater.mapping import regional
    from groundwater.mapping.regional import district_of

    polys = load_chiefdom_polys()
    crosswalk = load_chiefdom_district()
    rings = [poly.rings for poly in polys]

    for lat, lon in ((8.673, -10.51),    # inside the withheld Maforki wedge
                     (8.0, -14.0),       # offshore
                     (9.4, -10.2)):      # across the Guinea border
        assert chiefdom_of(lat, lon) == ("", "")
        assert district_of(lat, lon) == ""
        assert chiefdom_of_point(lat, lon, polys) == ""
        assert district_of_point(lat, lon, polys, crosswalk) == ""
        assert nearest_chiefdom_index(lon, lat, rings) is None

    # there is a chiefdom near the wedge - 78 m from that point, and the whole
    # of Mafindor within 10 km of it. Being able to find one is not a reason
    # to answer with it.
    assert nearest_chiefdom_index(-10.51, 8.673, rings, 10_000.0) is not None
    assert CHIEFDOM_EDGE_TOLERANCE_M < 78.0
    # the number is one number: the mapping lookups use the coverage constant
    # rather than keeping a second copy of it that could drift.
    assert regional.CHIEFDOM_EDGE_TOLERANCE_M is CHIEFDOM_EDGE_TOLERANCE_M


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


def test_the_review_does_not_withhold_the_same_ground_twice():
    """A resimplified layer must not turn one fragment into two.

    The carry-forward used to test identity by exact equality of the
    encoded geometry, which holds only while the layer's vertices never
    move. Rebuilding the chiefdoms at a finer simplification moves every
    vertex, so the same Maforki fragment came back as a second, separate
    withholding - the review reported two parts where the source has one,
    and would have grown another duplicate on every rebuild.
    """
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build_boundary_review", repo / "web" / "build_boundary_review.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    name, district, part = "Maforki", "Port Loko", [[
        [-10.51, 8.68], [-10.50, 8.68], [-10.50, 8.69], [-10.51, 8.68],
    ]]
    # the same ground with every vertex nudged, as a resimplification does
    moved = [[[x + 0.0004, y - 0.0003] for x, y in part[0]]]
    assert builder._same_ground_as_any(
        (name, district, moved), [(name, district, part)]
    )
    # a different chiefdom's fragment in the same place is not the same entry
    assert not builder._same_ground_as_any(
        ("Mafindor", "Kono", moved), [(name, district, part)]
    )
    # and neither is the same chiefdom's ground somewhere else entirely
    far = [[[x + 2.0, y] for x, y in part[0]]]
    assert not builder._same_ground_as_any(
        (name, district, far), [(name, district, part)]
    )


def test_the_consistency_check_judges_sheets_against_the_layer_s_districts():
    """The names a field sheet is judged by are the layer's own sixteen.

    The ingestion check held its own table of district names and bounding
    boxes, so the districts a sheet could be judged against and the districts
    the point lookup could return were two lists that had already drifted:
    the boxes overlapped, missed ground and answered with two districts at
    once. The check now reads its names from the chiefdom crosswalk, which is
    what the lookup answers from.
    """
    from groundwater.ingestion.checks import district_names

    assert set(district_names()) == _DISTRICTS
    assert len(district_names()) == 16

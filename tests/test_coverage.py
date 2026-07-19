"""District water-coverage gap: point assignment, ranking, and the map."""

import math

import numpy as np

from groundwater.coverage import (
    ChiefdomPoly,
    CoverageRow,
    chiefdom_coverage_rows,
    chiefdom_of_point,
    chiefdom_population,
    count_points_by_chiefdom,
    count_points_by_district,
    coverage_rows,
    coverage_stats,
    choropleth_values,
    district_of_point,
    expand_district_values,
    load_census_crosswalk,
    load_chiefdom_district,
    load_chiefdom_polys,
    load_district_population,
)
from groundwater.waterpoints import WaterPoint, parse_wpdx_csv


def _square(name, x0):
    ring = np.array([[x0, 0.0], [x0, 1.0], [x0 + 1, 1.0], [x0 + 1, 0.0], [x0, 0.0]])
    return ChiefdomPoly(name=name, rings=[ring],
                        bboxes=[(x0, 0.0, x0 + 1, 1.0)])


def _wp(lat, lon, functional):
    return WaterPoint(row_id="", lat=lat, lon=lon, functional=functional,
                      status="", source="Borehole", technology="", install_year=None,
                      adm2="")


_POLYS = [_square("A", 0.0), _square("B", 1.0)]
_CROSS = {"A": "Dist1", "B": "Dist2"}
_POP = {"Dist1": 1000.0, "Dist2": 2000.0, "Dist3": 500.0}  # Dist3 has no polygon


# --- pure counting / assignment -------------------------------------------

def test_district_of_point_and_unassigned():
    assert district_of_point(0.5, 0.5, _POLYS, _CROSS) == "Dist1"
    assert district_of_point(0.5, 1.5, _POLYS, _CROSS) == "Dist2"
    assert district_of_point(9.0, 9.0, _POLYS, _CROSS) == ""  # outside every poly


def test_count_points_by_district():
    points = [
        _wp(0.5, 0.5, True), _wp(0.2, 0.2, False),   # both in A/Dist1
        _wp(0.5, 1.5, True),                          # in B/Dist2
        _wp(9.0, 9.0, True),                          # outside -> unassigned
    ]
    counts, unassigned = count_points_by_district(points, _POLYS, _CROSS)
    assert counts["Dist1"] == {"total": 2, "functional": 1}
    assert counts["Dist2"] == {"total": 1, "functional": 1}
    assert len(unassigned) == 1  # never silently dropped


# --- ranking / stats -------------------------------------------------------

def test_coverage_rows_rank_worst_first():
    counts = {"Dist1": {"total": 2, "functional": 1},
              "Dist2": {"total": 1, "functional": 1}}  # Dist3 has no points
    rows = coverage_rows(_POP, counts)
    by = {r.district: r for r in rows}
    # Dist3 has no functional source -> undefined need -> ranked worst (1)
    assert by["Dist3"].people_per_point is None
    assert by["Dist3"].rank == 1
    # then by descending people-per-point: Dist2 (2000) worse than Dist1 (1000)
    assert by["Dist2"].people_per_point == 2000.0 and by["Dist2"].rank == 2
    assert by["Dist1"].people_per_point == 1000.0 and by["Dist1"].rank == 3


def test_choropleth_values_uses_inf_for_no_source():
    rows = coverage_rows(_POP, {"Dist1": {"total": 1, "functional": 1}})
    vals = choropleth_values(rows)
    assert vals["Dist1"] == 1000.0
    assert math.isinf(vals["Dist3"])  # no functional source -> sentinel


def test_coverage_stats():
    rows = coverage_rows(_POP, {"Dist1": {"total": 2, "functional": 1},
                                "Dist2": {"total": 1, "functional": 1}})
    stats = coverage_stats(rows)
    assert stats["n_areas"] == 3
    assert stats["worst_area"] == "Dist3"  # no source, ranked first
    assert stats["n_no_source"] == 1
    # the "Highest need" KPI shows the worst *finite* ratio, not the no-source
    assert stats["worst_served_area"] == "Dist2"
    assert stats["worst_served_people_per_point"] == 2000.0
    # national = total population / total functional points = 3500 / 2
    assert stats["national_people_per_point"] == 1750.0


def test_no_source_ties_broken_by_population():
    pop = {"Big": 100000.0, "Small": 1000.0}
    rows = coverage_rows(pop, {})  # neither has functional points
    assert [r.district for r in rows] == ["Big", "Small"]  # bigger unmet need first


# --- CSV upload path (offline) --------------------------------------------

def test_parse_wpdx_csv_matches_json_shape():
    csv_text = (
        "lat_deg,lon_deg,status_clean,water_source_clean,water_tech_clean\n"
        "8.48,-13.23,Functional,Borehole,Hand Pump\n"
        "8.49,-13.24,Non-Functional,Borehole,Hand Pump\n"
    )
    points = parse_wpdx_csv(csv_text)
    assert len(points) == 2
    assert points[0].functional is True and points[1].functional is False


# --- real bundled data -----------------------------------------------------

def test_bundled_population_matches_census_total():
    pop = load_district_population()
    assert len(pop) == 16
    assert round(sum(pop.values())) == 7_092_113  # official 2015 census total


def test_bundled_crosswalk_covers_all_chiefdoms():
    cross = load_chiefdom_district()
    pop = load_district_population()
    assert len(cross) == 166  # 165 geoBoundaries chiefdoms + the split Koya lobe
    # every chiefdom maps to a district that exists in the population table
    assert set(cross.values()) <= set(pop)
    # the merged "Koya" feature is split so each lobe maps to its own district
    assert cross["Koya"] == "Kenema"
    assert cross["Koya (Port Loko)"] == "Port Loko"


def test_real_points_assign_to_expected_districts():
    polys = load_chiefdom_polys()
    cross = load_chiefdom_district()
    # Freetown, Makeni, Kenema fall in their current districts
    assert district_of_point(8.4657, -13.2317, polys, cross) == "Western Area Urban"
    assert district_of_point(8.8817, -12.0442, polys, cross) == "Bombali"
    assert district_of_point(7.8767, -11.1875, polys, cross) == "Kenema"


def test_coverage_choropleth_renders_district_and_chiefdom(tmp_path):
    from groundwater.mapping import plot_coverage_choropleth

    cross = load_chiefdom_district()
    district_values = {"Kenema": 5000.0, "Karene": math.inf, "Bo": 3000.0}
    out = plot_coverage_choropleth(
        expand_district_values(district_values, cross),
        path=tmp_path / "district.png", group_labels=cross,
    )
    assert out.exists() and out.stat().st_size > 0
    # chiefdom mode: values keyed by chiefdom, no group labels
    chiefdom_values = {"Nongowa": 6000.0, "Kakua": math.inf}
    out2 = plot_coverage_choropleth(chiefdom_values, path=tmp_path / "chiefdom.png")
    assert out2.exists() and out2.stat().st_size > 0


# --- chiefdom-level coverage ----------------------------------------------

def test_bundled_chiefdom_population_conserves_districts():
    population, members = chiefdom_population()
    pop = load_district_population()
    cross = load_chiefdom_district()
    # every polygon has a population, national total is the census total
    assert len(population) == 166
    assert all(v > 0 for v in population.values())
    assert round(sum(population.values())) == 7_092_113
    # aggregating polygon populations by district reproduces each district total
    by_district = {}
    for chiefdom, value in population.items():
        by_district[cross[chiefdom]] = by_district.get(cross[chiefdom], 0) + value
    for district, total in pop.items():
        assert round(by_district[district]) == round(total), district
    # split chiefdoms fold into a parent (e.g. Gbanti + Kamaranka)
    assert len(members["Gbanti Kamarank"]) >= 2


def test_census_crosswalk_keys_by_district_and_chiefdom():
    xwalk = load_census_crosswalk()
    # duplicate names across districts are kept distinct
    assert xwalk[("Kenema", "Koya")] != xwalk[("Port Loko", "Koya")]


def test_hand_edited_crosswalk_tolerates_whitespace(tmp_path):
    # the crosswalk is user-editable; a stray space in a hand edit must not
    # break the (district, chiefdom) join.
    from importlib import resources

    src = (resources.files("groundwater") / "data"
           / "sl_census_crosswalk.csv").read_text(encoding="utf-8")
    edited = src.replace("Kenema,Koya,Koya", "Kenema, Koya , Koya")
    path = tmp_path / "edited.csv"
    path.write_text(edited)
    population, _ = chiefdom_population(crosswalk_path=path)
    assert len(population) == 166
    assert round(sum(population.values())) == 7_092_113


def test_chiefdom_point_counts_and_ranking():
    # two chiefdoms, points placed by chiefdom
    polys = [_square("Kakua", 0.0), _square("Nongowa", 1.0)]
    cross = {"Kakua": "Bo", "Nongowa": "Kenema"}
    pop = {"Kakua": 30000.0, "Nongowa": 10000.0}
    points = [_wp(0.5, 0.5, True), _wp(0.5, 1.5, True), _wp(9, 9, True)]
    counts, unassigned = count_points_by_chiefdom(points, polys)
    assert counts["Kakua"] == {"total": 1, "functional": 1}
    assert len(unassigned) == 1
    rows = chiefdom_coverage_rows(pop, counts, cross)
    # Kakua 30000/1 worse than Nongowa 10000/1
    assert rows[0].chiefdom == "Kakua" and rows[0].district == "Bo"
    assert rows[0].rank == 1


def test_chiefdom_of_point_real_data():
    polys = load_chiefdom_polys()
    assert chiefdom_of_point(8.8817, -12.0442, polys) == "Makeni Town"
    assert chiefdom_of_point(8.0, -14.0, polys) == ""  # offshore

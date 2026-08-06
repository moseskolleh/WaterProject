"""Coverage as a planning figure.

Every test here is about a number that looks current and is not: a decade-old
population, a functional flag from a survey nobody has repeated, a source
that dries up in March. The behaviour being pinned is that each of those is
visible in the output rather than folded into a single figure.
"""

from __future__ import annotations

import pytest

from groundwater import planning
from groundwater.planning import (
    CENSUS_TOTAL,
    CENSUS_YEAR,
    DEFAULT_GROWTH_RATE,
    planning_rows,
    planning_stats,
    point_freshness,
    project_population,
    seasonal_coverage,
)
from groundwater.waterpoints import WaterPoint


def _point(functional=True, year=None, months=None, lat=8.0, lon=-13.0):
    return WaterPoint(
        row_id="x", lat=lat, lon=lon, functional=functional,
        status="Functional" if functional else "Non-Functional",
        source="Borehole", technology="Hand Pump", install_year=None, adm2="Bo",
        report_year=year, months_per_year=months,
    )


# ---------------------------------------------------------------------------
# The population
# ---------------------------------------------------------------------------

def test_the_growth_rate_is_derived_from_two_published_totals():
    """Not asserted: it can be checked against figures anyone can look up."""
    rate = planning.intercensal_growth_rate()
    years = CENSUS_YEAR - planning.PREVIOUS_CENSUS_YEAR
    assert planning.PREVIOUS_CENSUS_TOTAL * (1 + rate) ** years == \
        pytest.approx(CENSUS_TOTAL)
    assert 0.02 < rate < 0.04


def test_a_projection_says_which_year_and_which_rate():
    """A people-per-point figure without a year is a wrong number waiting."""
    projected, projection = project_population({"Bo": 100.0}, 2025)
    assert projection.base_year == CENSUS_YEAR
    assert projection.target_year == 2025
    assert projection.rate == DEFAULT_GROWTH_RATE
    assert "2015 census" in projection.note and "2025" in projection.note
    assert f"{DEFAULT_GROWTH_RATE * 100:.2f}%" in projection.note
    assert projected["Bo"] == pytest.approx(
        100.0 * (1 + DEFAULT_GROWTH_RATE) ** 10)


def test_the_census_year_itself_is_not_projected():
    projected, projection = project_population({"Bo": 100.0}, CENSUS_YEAR)
    assert projected["Bo"] == 100.0
    assert "not projected" in projection.note


def test_a_uniform_rate_cannot_change_the_ranking_and_says_so():
    """The honest limit of this feature, stated where it is read."""
    population = {"Bo": 575478.0, "Kono": 506100.0, "Pujehun": 346461.0}
    points = {name: [_point()] for name in population}
    census_rows, _ = planning_rows(population, points, as_of_year=CENSUS_YEAR)
    projected_rows, projection = planning_rows(population, points,
                                               as_of_year=2030)
    assert [r.name for r in census_rows] == [r.name for r in projected_rows]
    assert projection.uniform
    assert "ranking is unchanged" in projection.note
    # but the magnitudes really do move
    assert projected_rows[0].people_per_point > census_rows[0].people_per_point


def test_district_rates_are_what_actually_move_the_ranking():
    population = {"Western Area Urban": 100.0, "Pujehun": 110.0}
    points = {name: [_point()] for name in population}
    uniform, _ = planning_rows(population, points, as_of_year=2035)
    assert uniform[0].name == "Pujehun"

    urban, projection = planning_rows(
        population, points, as_of_year=2035,
        rates={"Western Area Urban": 0.06, "Pujehun": 0.015})
    assert urban[0].name == "Western Area Urban"
    assert not projection.uniform
    assert "ranking is unchanged" not in projection.note


def test_a_year_before_the_census_is_refused():
    """This projects forward; it does not reconstruct the past."""
    with pytest.raises(ValueError, match="before the 2015 census"):
        project_population({"Bo": 100.0}, 2010)


# ---------------------------------------------------------------------------
# How old the survey is
# ---------------------------------------------------------------------------

def test_undated_points_are_reported_as_undated_not_as_current():
    fresh = point_freshness([_point(year=None), _point(year=None)], 2026)
    assert fresh.state == "unknown"
    assert fresh.n_dated == 0
    assert "cannot be established" in fresh.detail


def test_the_freshness_label_follows_the_median_age():
    assert point_freshness([_point(year=2025), _point(year=2024)], 2026).state \
        == "fresh"
    assert point_freshness([_point(year=2020), _point(year=2021)], 2026).state \
        == "ageing"
    assert point_freshness([_point(year=2014), _point(year=2015)], 2026).state \
        == "stale"


def test_the_freshness_detail_says_how_many_carried_a_date():
    fresh = point_freshness(
        [_point(year=2025), _point(year=2016), _point(year=None)], 2026)
    assert "2 of 3 points carry a survey date" in fresh.detail
    assert "most recent is 2025" in fresh.detail


def test_coverage_over_recent_surveys_is_reported_beside_coverage_over_all():
    """The gap is the share of the supply nobody has laid eyes on in years."""
    points = {"Bo": [_point(year=2024), _point(year=2010), _point(year=2009)]}
    rows, _ = planning_rows({"Bo": 300.0}, points, as_of_year=2026)
    row = rows[0]
    assert row.functional_points == 3
    assert row.recent_functional_points == 1
    assert row.people_per_recent_point == pytest.approx(
        row.people_per_point * 3)
    assert row.staleness_gap_percent == pytest.approx(200.0)


def test_an_area_with_no_recent_survey_has_no_recent_figure_not_a_zero():
    rows, _ = planning_rows({"Bo": 300.0}, {"Bo": [_point(year=2005)]},
                            as_of_year=2026)
    assert rows[0].recent_functional_points == 0
    assert rows[0].people_per_recent_point is None
    assert rows[0].staleness_gap_percent is None


# ---------------------------------------------------------------------------
# Whether it lasts the dry season
# ---------------------------------------------------------------------------

def test_silence_about_seasonality_is_not_a_year_round_supply():
    """The whole reason this is a band and not a number."""
    result = seasonal_coverage([_point(months=None) for _ in range(4)], 400.0)
    assert result.n_unknown == 4 and result.n_year_round == 0
    assert result.people_per_point_low is None       # nothing is confirmed
    assert result.people_per_point_high == 100.0     # if all four last the year
    assert not result.is_established
    assert "Silence is not a year-round supply" in result.detail


def test_a_seasonal_source_is_not_counted_as_dry_season_service():
    points = [_point(months=12), _point(months=12), _point(months=6),
              _point(months=None)]
    result = seasonal_coverage(points, 600.0)
    assert (result.n_year_round, result.n_seasonal, result.n_unknown) == (2, 1, 1)
    assert result.people_per_point_low == 300.0      # the two confirmed
    assert result.people_per_point_high == 200.0     # plus the unasked one
    assert result.is_established
    assert "2 of 4 functional points" in result.detail


def test_a_broken_point_is_not_asked_about_the_dry_season():
    result = seasonal_coverage(
        [_point(functional=False, months=12), _point(months=12)], 100.0)
    assert result.n_year_round == 1
    assert result.people_per_point_low == 100.0


def test_a_point_with_no_functional_flag_is_not_counted_as_working():
    rows, _ = planning_rows({"Bo": 300.0}, {"Bo": [_point(functional=None)]},
                            as_of_year=2026)
    assert rows[0].functional_points == 0
    assert rows[0].people_per_point is None


# ---------------------------------------------------------------------------
# The ranking and the headlines
# ---------------------------------------------------------------------------

def test_an_area_with_no_functional_source_ranks_worst_not_best():
    """An undefined ratio is not a good one."""
    population = {"Bo": 100.0, "Kono": 900.0, "Pujehun": 50.0}
    points = {"Bo": [_point()], "Kono": [_point(functional=False)],
              "Pujehun": [_point()]}
    rows, _ = planning_rows(population, points, as_of_year=2026)
    assert rows[0].name == "Kono"
    assert rows[0].people_per_point is None
    assert [r.rank for r in rows] == [1, 2, 3]


def test_the_headlines_carry_what_they_rest_on():
    population = {"Bo": 1000.0, "Kono": 1000.0}
    points = {"Bo": [_point(year=2025), _point(year=2018)],
              "Kono": [_point(year=2004), _point(year=2003)]}
    rows, projection = planning_rows(population, points, as_of_year=2026)
    stats = planning_stats(rows, projection)
    assert stats["as_of_year"] == 2026
    assert "2015 census" in stats["projection_note"]
    assert stats["population"] > stats["census_population"]
    assert stats["n_stale_areas"] == 1 and stats["stale_areas"] == ["Kono"]
    # counting only points somebody has seen lately makes it look worse
    assert (stats["national_people_per_recent_point"]
            > stats["national_people_per_point"])
    assert stats["n_seasonality_recorded"] == 0
    assert stats["n_seasonality_unknown"] == 4


def test_the_planning_record_is_serialisable():
    import json

    import yaml

    rows, projection = planning_rows(
        {"Bo": 1000.0}, {"Bo": [_point(year=2024, months=12)]},
        as_of_year=2026)
    payload = {"rows": [r.as_dict() for r in rows],
               "projection": projection.as_dict(),
               "stats": planning_stats(rows, projection)}
    assert json.dumps(payload)
    assert yaml.safe_dump(payload)


def test_an_area_with_no_points_at_all_still_appears():
    """A district nobody has surveyed is the one most likely to need a hole."""
    rows, _ = planning_rows({"Falaba": 200_000.0}, {}, as_of_year=2026)
    assert len(rows) == 1
    assert rows[0].water_points == 0 and rows[0].people_per_point is None
    assert rows[0].freshness.state == "unknown"
    assert "no functional points here" in rows[0].seasonal.detail

"""Coverage as a planning figure rather than an archive figure.

The coverage-gap view divides a district's population by the number of
functional water points in it. Both halves of that fraction are older than
they look, and the ranking it produces is used to decide where next year's
boreholes go.

**The population is from 2015.** Sierra Leone's census is a decade old.
Dividing today's need by a decade-old population understates it everywhere,
and quoting a figure as "people per water point" without saying which year's
people is how a planning number becomes a wrong number nobody notices.
Projection does not, on its own, change the *ranking* - a single national
rate is a uniform multiplier and leaves the order untouched - so the value
here is in the magnitudes being current and in the year being stated. Where
a programme has district rates, entering them is what makes the ranking
move, and it should: Western Area Urban does not grow at the rural rate.

**The water points were surveyed on various dates.** A point reported
functional in 2016 is evidence about 2016. Treating it as a working source
today counts a supply that may have been broken for years, which is exactly
the direction that hides an unserved population. So freshness is measured
and reported, and coverage is offered over recent surveys as well as over
all of them - the gap between the two is the size of the assumption.

**A point that dries up is not a water point in the dry season.** Where the
survey recorded how many months of the year a source yields water, a
seasonal source is separated from a year-round one. Most records do not say,
and silence is not a year-round supply: the dry-season figure is therefore a
band between counting the unknowns and not counting them, never a single
number that quietly picks one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .waterpoints import WaterPoint

__all__ = [
    "CENSUS_TOTAL",
    "CENSUS_YEAR",
    "DEFAULT_GROWTH_RATE",
    "FRESHNESS_LABELS",
    "Freshness",
    "PlanningRow",
    "PopulationProjection",
    "SeasonalCoverage",
    "intercensal_growth_rate",
    "planning_rows",
    "planning_stats",
    "point_freshness",
    "project_population",
    "seasonal_coverage",
]

#: The census the bundled district populations come from.
CENSUS_YEAR = 2015
CENSUS_TOTAL = 7_092_113

#: The census before it, used only to derive a growth rate that can be
#: checked against two published totals rather than asserted.
PREVIOUS_CENSUS_YEAR = 2004
PREVIOUS_CENSUS_TOTAL = 4_976_871


def intercensal_growth_rate() -> float:
    """The annual rate implied by the two census totals.

    Derived rather than quoted, so the number can be checked against two
    figures anyone can look up. It is higher than recent international
    projections for the country - the 2004 count followed the civil war and
    the period that followed included large returnee movements - so a
    programme with its own projection should use it instead. That is what
    the ``rate`` argument is for, and every projected figure says which rate
    produced it.
    """
    years = CENSUS_YEAR - PREVIOUS_CENSUS_YEAR
    return (CENSUS_TOTAL / PREVIOUS_CENSUS_TOTAL) ** (1.0 / years) - 1.0


DEFAULT_GROWTH_RATE = intercensal_growth_rate()


@dataclass(frozen=True)
class PopulationProjection:
    """A projected population and, always with it, how it was projected."""

    base_year: int
    target_year: int
    rate: float
    uniform: bool
    factor: float

    @property
    def note(self) -> str:
        if self.target_year == self.base_year:
            return (f"Populations are the {self.base_year} census figures, "
                    "not projected.")
        text = (f"Populations are projected from the {self.base_year} census "
                f"to {self.target_year} at {self.rate * 100:.2f}% a year, a "
                f"factor of {self.factor:.3f}.")
        if self.uniform:
            text += (" The same rate is applied to every district, so the "
                     "ranking is unchanged by the projection - only the "
                     "magnitudes move. District rates would change it, and "
                     "an urban district does not grow at the rural rate.")
        return text

    def as_dict(self) -> dict:
        return {"base_year": self.base_year, "target_year": self.target_year,
                "rate": self.rate, "uniform": self.uniform,
                "factor": self.factor, "note": self.note}


def project_population(population: dict[str, float], to_year: int, *,
                       rate: float | None = None,
                       rates: dict[str, float] | None = None,
                       ) -> tuple[dict[str, float], PopulationProjection]:
    """Project census populations forward, and say how.

    ``rates`` gives per-area annual rates where a programme has them;
    anything not named falls back to ``rate``. The returned projection
    carries the wording every surface prints, so no figure appears without
    the year and rate that produced it.
    """
    national = DEFAULT_GROWTH_RATE if rate is None else float(rate)
    years = int(to_year) - CENSUS_YEAR
    if years < 0:
        raise ValueError(
            f"{to_year} is before the {CENSUS_YEAR} census; this projects "
            "forward, it does not reconstruct the past")
    per_area = {str(k).strip().lower(): float(v) for k, v in (rates or {}).items()}
    projected = {}
    for name, value in population.items():
        area_rate = per_area.get(str(name).strip().lower(), national)
        projected[name] = float(value) * (1.0 + area_rate) ** years
    return projected, PopulationProjection(
        base_year=CENSUS_YEAR, target_year=int(to_year), rate=national,
        uniform=not per_area, factor=(1.0 + national) ** years,
    )


# ---------------------------------------------------------------------------
# How old the survey is
# ---------------------------------------------------------------------------

#: How stale a survey has to be before the label changes. A borehole that
#: worked three years ago is a fair bet; one last seen eight years ago is a
#: record, not an observation.
FRESH_YEARS = 3
AGEING_YEARS = 7

FRESHNESS_LABELS = {
    "fresh": "Surveyed recently",
    "ageing": "Survey is getting old",
    "stale": "Survey is out of date",
    "unknown": "Survey dates not recorded",
}


@dataclass(frozen=True)
class Freshness:
    """When the points in an area were last actually looked at."""

    n_points: int
    n_dated: int
    latest_year: Optional[int]
    median_age_years: Optional[float]
    n_recent: int
    state: str

    @property
    def label(self) -> str:
        return FRESHNESS_LABELS.get(self.state, FRESHNESS_LABELS["unknown"])

    @property
    def detail(self) -> str:
        if self.state == "unknown":
            return ("No survey dates are recorded for these points, so how "
                    "current this coverage figure is cannot be established.")
        return (f"{self.n_dated} of {self.n_points} points carry a survey "
                f"date; the most recent is {self.latest_year} and the median "
                f"is {self.median_age_years:.0f} years old. "
                f"{self.n_recent} were surveyed in the last {FRESH_YEARS} years.")

    def as_dict(self) -> dict:
        return {"n_points": self.n_points, "n_dated": self.n_dated,
                "latest_year": self.latest_year,
                "median_age_years": self.median_age_years,
                "n_recent": self.n_recent, "state": self.state,
                "label": self.label, "detail": self.detail}


def point_freshness(points: Iterable[WaterPoint], as_of_year: int) -> Freshness:
    """Summarise how old the survey behind a set of points is."""
    points = list(points)
    years = sorted(p.report_year for p in points if p.report_year)
    if not years:
        return Freshness(len(points), 0, None, None, 0, "unknown")
    ages = [as_of_year - y for y in years]
    middle = len(ages) // 2
    median = (float(ages[middle]) if len(ages) % 2
              else (ages[middle - 1] + ages[middle]) / 2.0)
    recent = sum(1 for age in ages if age <= FRESH_YEARS)
    if median <= FRESH_YEARS:
        state = "fresh"
    elif median <= AGEING_YEARS:
        state = "ageing"
    else:
        state = "stale"
    return Freshness(len(points), len(years), max(years), median, recent, state)


# ---------------------------------------------------------------------------
# Whether the source lasts the dry season
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeasonalCoverage:
    """Year-round service, as a band rather than a number.

    ``low`` counts only the points a survey confirmed work all year; ``high``
    also counts the ones nobody asked about. The true figure is between them,
    and how far apart they are is how much of this is guesswork.
    """

    n_year_round: int
    n_seasonal: int
    n_unknown: int
    people_per_point_low: Optional[float]
    people_per_point_high: Optional[float]

    @property
    def is_established(self) -> bool:
        """Whether seasonality was recorded often enough to mean anything."""
        known = self.n_year_round + self.n_seasonal
        return known > 0 and known >= (known + self.n_unknown) * 0.5

    @property
    def people_per_point_band(self) -> str:
        """The dry-season band as a planner reads it: best case to worst.

        ``people_per_point_high`` is the kinder end - it credits the points
        nobody asked about with working all year - so it comes first.
        """
        best, worst = self.people_per_point_high, self.people_per_point_low
        if best is None and worst is None:
            return "n/a"
        if worst is None:
            return f"{best:,.0f} to no confirmed point"
        if best is None or round(best) == round(worst):
            return f"{worst:,.0f}"
        return f"{best:,.0f} to {worst:,.0f}"

    @property
    def detail(self) -> str:
        total = self.n_year_round + self.n_seasonal + self.n_unknown
        if not total:
            return "There are no functional points here to ask about."
        if self.n_year_round + self.n_seasonal == 0:
            return ("No survey recorded how many months of the year these "
                    "points yield water, so dry-season service cannot be "
                    "separated from wet-season service. Silence is not a "
                    "year-round supply.")
        text = (f"{self.n_year_round} of {total} functional points are "
                f"recorded as working all year and {self.n_seasonal} as "
                "seasonal")
        if self.n_unknown:
            text += f"; {self.n_unknown} were never asked"
        return text + "."

    def as_dict(self) -> dict:
        return {"n_year_round": self.n_year_round,
                "n_seasonal": self.n_seasonal, "n_unknown": self.n_unknown,
                "people_per_point_low": self.people_per_point_low,
                "people_per_point_high": self.people_per_point_high,
                "people_per_point_band": self.people_per_point_band,
                "is_established": self.is_established, "detail": self.detail}


def seasonal_coverage(points: Iterable[WaterPoint],
                      population: float) -> SeasonalCoverage:
    """Split the functional points by whether they last the dry season."""
    functional = [p for p in points if p.functional]
    year_round = sum(1 for p in functional if p.year_round is True)
    seasonal = sum(1 for p in functional if p.year_round is False)
    unknown = len(functional) - year_round - seasonal
    return SeasonalCoverage(
        n_year_round=year_round, n_seasonal=seasonal, n_unknown=unknown,
        people_per_point_low=(population / year_round) if year_round else None,
        people_per_point_high=(population / (year_round + unknown))
        if (year_round + unknown) else None,
    )


# ---------------------------------------------------------------------------
# The planning row
# ---------------------------------------------------------------------------

@dataclass
class PlanningRow:
    """One area, with what its coverage figure actually rests on."""

    name: str
    census_population: float
    population: float
    water_points: int
    functional_points: int
    people_per_point: Optional[float]
    recent_functional_points: int
    people_per_recent_point: Optional[float]
    freshness: Freshness
    seasonal: SeasonalCoverage
    rank: int = 0

    @property
    def staleness_gap_percent(self) -> Optional[float]:
        """How much worse coverage looks when only recent surveys count.

        A large gap is not a data-quality footnote: it is the share of this
        district's water supply that nobody has laid eyes on in years.
        """
        if not self.people_per_point or self.people_per_recent_point is None:
            return None
        return (self.people_per_recent_point / self.people_per_point - 1.0) * 100.0

    def as_dict(self) -> dict:
        return {
            "name": self.name, "rank": self.rank,
            "census_population": self.census_population,
            "population": self.population,
            "water_points": self.water_points,
            "functional_points": self.functional_points,
            "people_per_point": self.people_per_point,
            "recent_functional_points": self.recent_functional_points,
            "people_per_recent_point": self.people_per_recent_point,
            "staleness_gap_percent": self.staleness_gap_percent,
            "freshness": self.freshness.as_dict(),
            "seasonal": self.seasonal.as_dict(),
        }


def planning_rows(population: dict[str, float],
                  points_by_area: dict[str, list[WaterPoint]],
                  *, as_of_year: int, rate: float | None = None,
                  rates: dict[str, float] | None = None,
                  ) -> tuple[list[PlanningRow], PopulationProjection]:
    """Ranked planning rows for every area in ``population``.

    Ranked worst-first on the projected population per functional point, with
    areas that have no functional source at the top - an undefined ratio is
    not a good one. Population breaks ties, so a large district with no
    source outranks a small one.
    """
    projected, projection = project_population(population, as_of_year,
                                               rate=rate, rates=rates)
    rows: list[PlanningRow] = []
    for name, census in population.items():
        points = list(points_by_area.get(name, ()))
        people = projected[name]
        functional = [p for p in points if p.functional]
        recent = [p for p in functional
                  if p.report_year and as_of_year - p.report_year <= AGEING_YEARS]
        rows.append(PlanningRow(
            name=name, census_population=float(census), population=people,
            water_points=len(points), functional_points=len(functional),
            people_per_point=(people / len(functional)) if functional else None,
            recent_functional_points=len(recent),
            people_per_recent_point=(people / len(recent)) if recent else None,
            freshness=point_freshness(points, as_of_year),
            seasonal=seasonal_coverage(points, people),
        ))
    rows.sort(key=lambda r: (
        1 if r.people_per_point is not None else 0,
        -(r.people_per_point or 0.0),
        -r.population,
    ))
    for rank, row in enumerate(rows, start=1):
        row.rank = rank
    return rows, projection


def planning_stats(rows: Iterable[PlanningRow],
                   projection: PopulationProjection) -> dict:
    """Headline figures, each one carrying what it rests on."""
    rows = list(rows)
    served = [r for r in rows if r.people_per_point is not None]
    worst = max(served, key=lambda r: r.people_per_point, default=None)
    total_people = sum(r.population for r in rows)
    total_functional = sum(r.functional_points for r in rows)
    total_recent = sum(r.recent_functional_points for r in rows)
    stale_areas = [r for r in rows if r.freshness.state == "stale"]
    unknown_seasonality = sum(r.seasonal.n_unknown for r in rows)
    known_seasonality = sum(r.seasonal.n_year_round + r.seasonal.n_seasonal
                            for r in rows)
    return {
        "n_areas": len(rows),
        "as_of_year": projection.target_year,
        "projection_note": projection.note,
        "population": total_people,
        "census_population": sum(r.census_population for r in rows),
        "worst_area": rows[0].name if rows else None,
        "worst_people_per_point": rows[0].people_per_point if rows else None,
        "worst_served_area": worst.name if worst else None,
        "worst_served_people_per_point": worst.people_per_point if worst else None,
        "n_no_source": sum(1 for r in rows if r.functional_points == 0),
        "national_people_per_point": (total_people / total_functional)
        if total_functional else None,
        # the same figure counting only points somebody has seen lately: the
        # difference between the two is the size of the assumption
        "national_people_per_recent_point": (total_people / total_recent)
        if total_recent else None,
        "n_stale_areas": len(stale_areas),
        "stale_areas": [r.name for r in stale_areas],
        "n_seasonality_recorded": known_seasonality,
        "n_seasonality_unknown": unknown_seasonality,
    }


def choropleth_values(rows: Iterable[PlanningRow]) -> dict[str, float]:
    """Area -> projected people per functional point, ``inf`` where none."""
    return {r.name: (r.people_per_point if r.people_per_point is not None
                     else math.inf) for r in rows}

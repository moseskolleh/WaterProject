"""The chance of a working borehole (PLAN.md step 3.3).

The suitability score next door is a weighted sum nobody has calibrated, and
the programme estimate asks the user to type a success rate. What a manager
needs is the odds, worked out in a way anyone can follow on paper:

1. **The prior**: a success rate for the ground under the point, from
   ``data/success_prior.csv``, looked up by the BGS aquifer class and the
   USGS geology unit there. The cited figures are the yield ranges of the
   BGS productivity classes on the country maps (O Dochartaigh 2021,
   Table 3), which the guide takes as the average yields of a borehole
   sited and developed properly; it calls the ranges of the 2012
   Africa-wide map these maps develop roughly the interquartile range of
   such boreholes' yields (Table 4). Reading the country-map ranges as
   quartiles too is this toolkit's choice: read as the quartiles of a
   lognormal spread, they give the share of boreholes at or above the
   yield that counts as success. A point the table has no class for gets
   a weak, labelled fallback: an even chance.
2. **The evidence**: a likelihood ratio for each of four things the survey
   says, from ``data/success_evidence.yaml``: the depth to basement the
   range of models quotes (step 3.1), whether basement was resolved, the
   resistivity of the water-bearing zone, and the confidence of the fit.
   The fit is not evidence that the ground is wet or dry, so it brings no
   ratio of its own: it weights the other three, raising their product to
   a power below 1 for a poor fit.
3. **The answer**: prior odds times every factor. The breakdown multiplies
   back to it exactly, factor by factor.
4. **The band**: the prior is a Beta distribution with the table's rate as
   its mean and its effective sample size as its weight. Its 10th and 90th
   percentiles, carried through the same factors, are the band printed
   beside the central figure. The factors themselves are taken as given;
   the band is the prior's uncertainty, not theirs.

"Success" is a yield of at least ``config.odds.success_yield_m3_per_h`` at
the dry-season level. The prior is worked out at that rate, so changing the
definition moves it; the likelihood ratios do not depend on it.

Every number in both data files is provisional, and the reports say so.
Both engines run this, and ``gwt-core.js`` is held to it by
``tests/webapp/parity.mjs``. The numerical pieces (the normal tail, the
incomplete beta function and its inverse) are written out rather than taken
from scipy, so that both engines do the same arithmetic.
"""

from __future__ import annotations

import csv
import functools
import io
import math
from dataclasses import dataclass

import yaml

from .._resources import bundled_text
from ..config import Config
from ..text import phrase, phrase_table
from ..ves.model_range import _share, quoted_basement_band

__all__ = [
    "Evidence",
    "SuccessOdds",
    "beta_quantile",
    "ground_at",
    "lognormal_share_above",
    "odds_header",
    "odds_headline",
    "odds_rows",
    "odds_basis_text",
    "odds_point_text",
    "odds_short",
    "odds_table_caption",
    "odds_tables",
    "odds_text",
    "point_latlon",
    "programme_offer",
    "programme_rate",
    "prior_for",
    "regularised_beta",
    "success_odds",
    "survey_odds",
]

#: The quantile of the standard normal at 0.75: the quartiles of a lognormal
#: lie this many of its standard deviations either side of its median.
_Z_QUARTILE = 0.6744897501960817
_PRIOR_BAND = (0.1, 0.9)
#: How close to 0 or 1 the prior rate and its percentiles may come. A Beta
#: prior lies strictly inside (0, 1), but in doubles the 90th percentile of
#: one with a rate near 1 bisects to exactly 1.0 (a rate above about 0.993
#: at an effective n of 10 does it), and odds of p / (1 - p) are then
#: infinite.
_RATE_BOUND = 1e-6


# ------------------------------------------------------------------- tables

@functools.lru_cache(maxsize=1)
def odds_tables() -> dict:
    """``success_prior.csv`` and ``success_evidence.yaml``, parsed once.

    ``web/build_webapp_data.py`` emits this as ``GWT.data.odds``, so the
    browser reads exactly what this parses. Treat it as read-only.
    """
    def number(text: str) -> float | None:
        return float(text) if text.strip() else None

    prior = []
    for row in csv.DictReader(io.StringIO(bundled_text("success_prior.csv"))):
        prior.append({
            "bgs_code": row["bgs_code"],
            "glg": row["glg"],
            "yield_q1_l_per_s": number(row["yield_q1_l_per_s"]),
            "yield_q3_l_per_s": number(row["yield_q3_l_per_s"]),
            "rate": number(row["rate"]),
            "effective_n": float(row["effective_n"]),
            "status": row["status"],
            "basis": row["basis"],
        })
    evidence = yaml.safe_load(bundled_text("success_evidence.yaml"))
    return {"prior": prior, "evidence": evidence}


# ----------------------------------------------------------------- the maths

def _erfc(x: float) -> float:
    """The complementary error function, by Abramowitz and Stegun 7.1.26
    (absolute error under 1.5e-7, far inside a prior quoted to a percent).
    Written out rather than math.erfc because the browser has none."""
    z = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * z)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741
                + t * (-1.453152027 + t * 1.061405429))))
    tail = poly * math.exp(-z * z)
    return tail if x >= 0.0 else 2.0 - tail


def lognormal_share_above(q1: float, q3: float, threshold: float) -> float:
    """The share of a lognormal spread with quartiles ``q1`` and ``q3`` at or
    above ``threshold``: one minus its distribution function there."""
    mu = 0.5 * (math.log(q1) + math.log(q3))
    sigma = (math.log(q3) - math.log(q1)) / (2.0 * _Z_QUARTILE)
    z = (math.log(threshold) - mu) / sigma
    return 0.5 * _erfc(z / math.sqrt(2.0))


def _log_gamma(x: float) -> float:
    """ln Gamma(x) for x > 0, by Lanczos's series (g = 7, nine terms), the
    form gwt-core.js uses; good to about 1e-15 relative."""
    coefficients = (
        0.99999999999980993, 676.5203681218851, -1259.1392167224028,
        771.32342877765313, -176.61502916214059, 12.507343278686905,
        -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
    )
    if x < 0.5:
        # the reflection formula keeps the series where it converges
        return math.log(math.pi / abs(math.sin(math.pi * x))) - _log_gamma(1.0 - x)
    x -= 1.0
    a = coefficients[0]
    t = x + 7.5
    for i in range(1, 9):
        a += coefficients[i] / (x + i)
    return 0.5 * math.log(2.0 * math.pi) + (x + 0.5) * math.log(t) - t + math.log(a)


def _beta_fraction(a: float, b: float, x: float) -> float:
    """The continued fraction of the incomplete beta function, evaluated by
    the modified Lentz method (DLMF 8.17.22)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) >= tiny else tiny)
    h = d
    for m in range(1, 301):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) >= tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) >= tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) >= tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) >= tiny else tiny
        step = d * c
        h *= step
        if abs(step - 1.0) < 1e-15:
            break
    return h


def regularised_beta(a: float, b: float, x: float) -> float:
    """I_x(a, b): the distribution function of a Beta(a, b) at ``x``."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(_log_gamma(a + b) - _log_gamma(a) - _log_gamma(b)
                     + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_fraction(a, b, x) / a
    return 1.0 - front * _beta_fraction(b, a, 1.0 - x) / b


def beta_quantile(a: float, b: float, q: float) -> float:
    """The ``q`` quantile of a Beta(a, b), by bisection: a hundred halvings
    of [0, 1], which both engines take in the same order."""
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if regularised_beta(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _probability(odds: float) -> float:
    return odds / (1.0 + odds)


def _odds(p: float) -> float:
    return p / (1.0 - p)


def _inside(p: float) -> float:
    """``p`` held off 0 and 1 by :data:`_RATE_BOUND`."""
    return min(max(p, _RATE_BOUND), 1.0 - _RATE_BOUND)


# ----------------------------------------------------------------- the prior

def prior_for(bgs_code: str | None, glg: str | None,
              success_yield_m3_per_h: float) -> dict:
    """The prior table's row for this ground, and the rate it gives.

    The most specific row wins: the class and the geology unit, then the
    class on any unit, then the fallback. Returns the row's fields with
    ``matched`` ("combination", "class" or "fallback") and ``rate``, the
    prior success rate at ``success_yield_m3_per_h``.
    """
    if not success_yield_m3_per_h > 0.0:
        raise ValueError("odds.success_yield_m3_per_h must be above zero, not "
                         f"{success_yield_m3_per_h!r}")
    rows = odds_tables()["prior"]

    def find(code: str, unit: str):
        return next((r for r in rows if r["bgs_code"] == code and r["glg"] == unit), None)

    row, matched = None, "fallback"
    if bgs_code:
        if glg:
            row, matched = find(bgs_code, glg), "combination"
        if row is None:
            row, matched = find(bgs_code, "*"), "class"
    if row is None:
        row, matched = find("*", "*"), "fallback"
    if row is None:
        raise ValueError("success_prior.csv has no fallback row (bgs_code and glg '*')")
    if row["status"] == "fallback":
        matched = "fallback"
    if row["yield_q1_l_per_s"] is not None:
        rate = lognormal_share_above(row["yield_q1_l_per_s"], row["yield_q3_l_per_s"],
                                     success_yield_m3_per_h / 3.6)
    else:
        rate = row["rate"]
    # a Beta prior needs a rate strictly inside (0, 1)
    rate = _inside(rate)
    return {**row, "matched": matched, "rate": rate}


# ------------------------------------------------------------- the evidence

@dataclass
class Evidence:
    """One line of the breakdown."""

    #: "regolith", "basement", "resistivity" or "fit"
    key: str
    #: the band the evidence fell in, a key of success_evidence.yaml, or
    #: "not_sampled", "not_quoted", "unknown" where there was none
    band: str
    #: what was measured: the depth, the unresolved share, the resistivity
    #: or the fit error; None where nothing was
    value: float | None
    #: the factor the odds were multiplied by
    factor: float
    #: the chance of success after this factor and every one before it
    after: float
    #: for the fit only, the weight its band gives the survey evidence
    weight: float | None = None


def _band_of(bands: list[dict], value: float) -> dict:
    """The first band whose ``below`` is above ``value``, else the last."""
    for band in bands:
        if "below" in band and value < band["below"]:
            return band
    return bands[-1]


def _water_zone_rho(interp) -> float | None:
    """The thickness-weighted geometric mean resistivity of the water-bearing
    layers inside the water zones; None where there are none.

    Not :func:`suitability._zone_geomean_rho`, which takes every layer
    inside a zone. The zones are rounded to whole metres, so that took in
    the slice of dry layer or basement the rounding added: a zone whose only
    layer was 200 ohm-m read 307 ohm-m, "resistive", with 0.4 m of 5,000
    ohm-m basement in it, and a band edge turned that into a step in the
    odds. The logarithms are taken relative to the first such layer's
    resistivity, so a zone of one resistivity reads exactly that and not a
    rounding error either side of an edge (exp(ln 50) is 49.999...).
    """
    reference = 0.0
    acc = 0.0
    total = 0.0
    for top, bottom in interp.water_zones:
        for layer in interp.layers:
            if not layer.water_bearing:
                continue
            lo = max(layer.top_m, top)
            hi = min(layer.bottom_m if math.isfinite(layer.bottom_m) else bottom, bottom)
            if hi > lo:
                if total == 0.0:
                    reference = layer.rho
                acc += math.log(layer.rho / reference) * (hi - lo)
                total += hi - lo
    return reference * math.exp(acc / total) if total > 0 else None


def _survey_evidence(interp, model_range) -> list[tuple[str, str, float | None, float]]:
    """``(key, band, value, ratio)`` for the three survey classes."""
    table = odds_tables()["evidence"]
    out = []
    if model_range is None:
        out.append(("regolith", "not_sampled", None, 1.0))
        out.append(("basement", "not_sampled", None, 1.0))
    else:
        band = quoted_basement_band(model_range)
        if band is None:
            out.append(("regolith", "not_quoted", None, 1.0))
        else:
            hit = _band_of(table["regolith"], band.p50)
            out.append(("regolith", hit["key"], band.p50, float(hit["lr"])))
        share = model_range.basement_unresolved
        basement = table["basement"]
        if band is None:
            key = "unresolved"
        elif share <= basement["resolved_max_unresolved_share"]:
            key = "resolved"
        else:
            key = "partly"
        out.append(("basement", key, share, float(basement[key]["lr"])))
    rho = _water_zone_rho(interp)
    resistivity = table["resistivity"]
    if rho is None:
        out.append(("resistivity", "none", None, float(resistivity["none"]["lr"])))
    else:
        hit = _band_of(resistivity["bands"], rho)
        out.append(("resistivity", hit["key"], rho, float(hit["lr"])))
    return out


@dataclass
class SuccessOdds:
    sounding_id: str
    success_yield_m3_per_h: float
    #: the ground under the point, as looked up (None where there was none)
    bgs_code: str | None
    glg: str | None
    #: the prior table's row that applied, and how it was matched
    matched: str
    status: str
    basis: str
    yield_q1_l_per_s: float | None
    yield_q3_l_per_s: float | None
    effective_n: float
    #: the prior rate and the 10th and 90th percentiles of its Beta
    prior: float
    prior_low: float
    prior_high: float
    prior_odds: float
    evidence: list[Evidence]
    posterior_odds: float
    #: the chance of success, and its band from the prior's
    probability: float
    low: float
    high: float
    range_sampled: bool
    calibration: str = ""


def success_odds(interp, model_range, bgs_code: str | None, glg: str | None,
                 config: Config | None = None) -> SuccessOdds:
    """The chance that a borehole at this point succeeds, with its breakdown.

    ``interp`` is the point's interpretation, ``model_range`` its sampled
    range of models (None where none was sampled), and ``bgs_code`` and
    ``glg`` the BGS aquifer class and USGS unit under it (None where the
    point has no position or the map has nothing there).
    """
    config = config or Config()
    tables = odds_tables()
    rate_m3h = float(config.odds.success_yield_m3_per_h)
    row = prior_for(bgs_code, glg, rate_m3h)
    p0 = row["rate"]
    n = row["effective_n"]
    alpha, beta = p0 * n, (1.0 - p0) * n
    # held inside (0, 1) as the rate is: a percentile that rounded to
    # exactly 1 raised ZeroDivisionError carried through the odds below
    prior_low = _inside(beta_quantile(alpha, beta, _PRIOR_BAND[0]))
    prior_high = _inside(beta_quantile(alpha, beta, _PRIOR_BAND[1]))
    prior_odds = _odds(p0)

    survey = _survey_evidence(interp, model_range)
    err = getattr(interp, "fit_error_percent", None)
    if err is None or not math.isfinite(err):
        fit_key, weight, err = "unknown", 1.0, None
    else:
        hit = _band_of(tables["evidence"]["fit"], err)
        fit_key, weight = hit["key"], float(hit["weight"])
    product = 1.0
    for _key, _band, _value, ratio in survey:
        product *= ratio
    fit_factor = product ** (weight - 1.0)

    evidence = []
    odds = prior_odds
    for key, band, value, ratio in survey:
        odds *= ratio
        evidence.append(Evidence(key, band, value, ratio, _probability(odds)))
    odds *= fit_factor
    evidence.append(Evidence("fit", fit_key, err, fit_factor, _probability(odds),
                             weight=weight))
    total = product * fit_factor

    def carried(p):
        return _probability(_odds(p) * total)

    return SuccessOdds(
        sounding_id=interp.sounding_id,
        success_yield_m3_per_h=rate_m3h,
        bgs_code=bgs_code, glg=glg,
        matched=row["matched"], status=row["status"], basis=row["basis"],
        yield_q1_l_per_s=row["yield_q1_l_per_s"],
        yield_q3_l_per_s=row["yield_q3_l_per_s"],
        effective_n=n,
        prior=p0, prior_low=prior_low, prior_high=prior_high, prior_odds=prior_odds,
        evidence=evidence,
        posterior_odds=odds,
        probability=_probability(odds),
        low=carried(prior_low), high=carried(prior_high),
        range_sampled=model_range is not None,
        calibration=" ".join(str(tables["evidence"]["calibration"]).split()),
    )


# --------------------------------------------------------------- the ground

def point_latlon(interp, zone: int | None, fallback: tuple[float, float] | None):
    """Where the point is: its own easting and northing where it has them,
    in ``zone`` (or the zone its easting implies), else ``fallback``, the
    site's position. None where neither is known."""
    from ..geo import infer_zone_for_sierra_leone, utm_to_geographic

    e = getattr(interp, "site_easting", None)
    n = getattr(interp, "site_northing", None)
    if (isinstance(e, (int, float)) and isinstance(n, (int, float))
            and math.isfinite(e) and math.isfinite(n)):
        return utm_to_geographic(e, n, zone or infer_zone_for_sierra_leone(e))
    return fallback


@functools.lru_cache(maxsize=1)
def _map_units() -> tuple:
    """The bundled BGS and USGS polygons, parsed once: a page that redraws
    the odds on every run would otherwise read both layers each time."""
    from ..mapping.regional import load_geology, load_hydrogeology

    return tuple(load_hydrogeology()), tuple(load_geology())


def ground_at(latlon) -> tuple[str | None, str | None]:
    """The BGS aquifer class and the USGS geology unit under a position,
    as aquifer_unit_at and geology_unit_at find them on the bundled maps."""
    if latlon is None:
        return None, None
    from ..mapping.regional import _point_in_unit

    lat, lon = latlon
    aquifers, units = _map_units()
    aquifer = next((u for u in aquifers if _point_in_unit(lon, lat, u)), None)
    unit = next((u for u in units if _point_in_unit(lon, lat, u)), None)
    return (aquifer.glg if aquifer is not None else None,
            unit.glg if unit is not None else None)


def survey_odds(interpretations, ranges, zone: int | None, fallback_latlon,
                config: Config | None = None) -> list[SuccessOdds]:
    """The odds at every point of a survey, in the order given.

    ``ranges`` is in lockstep with ``interpretations`` (None, or a None in
    it, where no range was sampled); ``zone`` is the site's UTM zone, if it
    names one, and ``fallback_latlon`` the site's position, for a point
    that carries none of its own.
    """
    ranges = list(ranges or [])
    out = []
    for i, interp in enumerate(interpretations):
        model_range = ranges[i] if i < len(ranges) else None
        code, unit = ground_at(point_latlon(interp, zone, fallback_latlon))
        out.append(success_odds(interp, model_range, code, unit, config))
    return out


# -------------------------------------------------------------------- prose

def _percent(p: float) -> str:
    return _share(p)


def odds_headline(o: SuccessOdds) -> str:
    """The plan's sentence: about so many percent, between so many, that a
    borehole here yields enough for a handpump through the dry season."""
    status = phrase("odds.status_fallback" if o.matched == "fallback"
                    else "odds.status_provisional")
    return phrase("odds.headline", p=_percent(o.probability), low=_percent(o.low),
                  high=_percent(o.high), status=status)


def odds_short(o: SuccessOdds) -> str:
    """The odds in a table cell: "61 percent (39 to 78)"."""
    return phrase("odds.short", p=_percent(o.probability), low=_percent(o.low),
                  high=_percent(o.high))


def _ground_text(o: SuccessOdds) -> str:
    if o.glg:
        return phrase("odds.ground", code=o.bgs_code, glg=o.glg)
    return phrase("odds.ground_no_unit", code=o.bgs_code)


def odds_point_text(o: SuccessOdds) -> list[str]:
    """What is particular to the point: the headline, its prior, and what
    was left out. A report or page with several points prints this under
    each and :func:`odds_basis_text` once."""
    out = [odds_headline(o)]
    prior = dict(p=_percent(o.prior), low=_percent(o.prior_low),
                 high=_percent(o.prior_high), n=o.effective_n, basis=o.basis)
    if o.matched == "fallback":
        out.append(phrase("odds.prior_fallback", **prior))
    else:
        out.append(phrase(
            "odds.prior_combination" if o.matched == "combination" else "odds.prior_class",
            ground=_ground_text(o), q1=o.yield_q1_l_per_s, q3=o.yield_q3_l_per_s,
            ls=o.success_yield_m3_per_h / 3.6, **prior))
    if not o.range_sampled:
        out.append(phrase("odds.not_sampled", sid=o.sounding_id))
    return out


def odds_basis_text(o: SuccessOdds) -> list[str]:
    """What success means and what the odds rest on, the same at every
    point of a survey."""
    return [phrase("odds.definition", rate=o.success_yield_m3_per_h,
                   ls=o.success_yield_m3_per_h / 3.6),
            phrase("odds.basis", calibration=o.calibration)]


def odds_text(o: SuccessOdds) -> list[str]:
    """The odds in sentences: the headline, what success means, the prior,
    what was left out, and the basis."""
    point, basis = odds_point_text(o), odds_basis_text(o)
    return point[:1] + basis[:1] + point[1:] + basis[1:]


def _found(e: Evidence) -> str:
    """What the survey found, for the breakdown's second column."""
    missing = phrase_table("odds.found_missing")
    if f"{e.key}_{e.band}" in missing:
        return missing[f"{e.key}_{e.band}"]
    band = phrase_table("odds.bands")[e.band]
    if e.key == "regolith":
        return phrase("odds.found_regolith", depth=e.value, band=band)
    if e.key == "basement":
        return phrase("odds.found_basement", share=_share(float(e.value or 0.0)), band=band)
    if e.key == "resistivity":
        return phrase("odds.found_resistivity", rho=e.value, band=band)
    return phrase("odds.found_fit", err=e.value, band=band, weight=e.weight)


def odds_header() -> list[str]:
    return [phrase("odds.col_evidence"), phrase("odds.col_found"),
            phrase("odds.col_factor"), phrase("odds.col_after")]


def odds_rows(o: SuccessOdds) -> list[list[str]]:
    """The breakdown: the prior, then each piece of evidence with the factor
    it multiplied the odds by and the chance after it. The factors multiply
    to the posterior odds over the prior odds."""
    labels = phrase_table("odds.rows")
    rows = [[labels["prior"], _ground_text(o) if o.bgs_code
             else phrase("odds.ground_none"), "", _percent(o.prior)]]
    for e in o.evidence:
        rows.append([labels[e.key], _found(e), f"{e.factor:.2f}", _percent(e.after)])
    return rows


def odds_table_caption(o: SuccessOdds) -> str:
    return phrase("odds.table_caption", sid=o.sounding_id)


# ------------------------------------------------------- the programme rate

def programme_rate(o: SuccessOdds) -> float:
    """The odds as a programme's success rate in percent: the central figure
    to a whole percent, no lower than 1 (the least the estimate takes) and
    no higher than 99, so a rate offered from a provisional prior never
    plans a programme with no dry hole at all."""
    return float(min(max(round(100.0 * o.probability), 1), 99))


def programme_offer(o: SuccessOdds) -> str:
    """The sentence the Costing pages offer the odds with, beside the rate
    typed for a programme."""
    return phrase("odds.programme_offer", sid=o.sounding_id, p=_percent(o.probability),
                  low=_percent(o.low), high=_percent(o.high))

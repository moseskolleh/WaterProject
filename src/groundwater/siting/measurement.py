"""The value of one more measurement (PLAN.md step 3.5).

Before the rig is called, a crew can take one more sounding beside the
first-ranked point, or run a profiling line through it. Whether that is
worth doing is arithmetic, not habit: it is worth what it can save the
decision about where to drill, on average over what it might read. This
works that out as a preposterior analysis anyone can follow on paper:

1. **The decision now.** The choice is where to drill, not whether: the
   first-ranked point, or the alternative, which is the other surveyed point
   with the best odds, or, on a survey of one point, an unsurveyed site on
   the same ground at the prior. Going to the alternative is taken to cost
   its expected cost per working borehole, as the cost distribution (step
   3.4) works it out: the mean completed borehole plus the mean dry attempt
   for each of the (1 - q) / q dry attempts expected before a working one,
   at its chance q. Drilling at the point costs the completed borehole if it
   works, and the dry attempt and then the alternative if it does not. That
   is linear in the point's chance p, and it is the cheaper choice exactly
   when p is above q: it costs dry x (q - p) / q more than going to the
   alternative, so the completed borehole's cost cancels from the value, and
   a reader can check it with the dry attempt and the two chances alone.
2. **What the measurement could read.** Each class of evidence in
   ``success_evidence.yaml`` has a band for each reading and a likelihood
   ratio for each band. A sounding reads the depth to basement and whether
   basement was resolved (one class: the ratios of the two multiplied, as
   step 3.3 multiplies them) and the water-zone resistivity; a profiling
   line reads the resistivity alone. The ratios say how much more often a
   band is seen where a borehole works than where it is dry, but not how
   often either is seen. That is taken as the spread among dry boreholes
   that is as even as the ratios allow (the largest entropy whose ratios
   still average 1 over it), and the spread among working ones as that
   times the ratios. The readings of different classes are taken as
   independent of each other, and of the readings already made, given
   whether a borehole at the point would work. The ratios are raised to the
   weight of the point's own fit, as the point's own evidence was.
3. **The decision after each reading.** The chance that the measurement
   reads each combination of bands is its share among working boreholes
   times p plus its share among dry ones times (1 - p), and the chance at
   the point after it follows by Bayes's rule. The decision is taken again
   with that chance.
4. **The value.** The expected value of the sample information (EVSI) is
   the cost of the best decision now less the expected cost of the best
   decision after the measurement: what is saved, on average, in the
   readings that change the decision. It is never negative, it is zero when
   no reading changes the decision, and it is never more than the value of
   knowing for certain whether the point would work (EVPI).

The cost of the measurement itself is in ``data/field.yaml``. Both engines
run this, and ``gwt-core.js`` is held to it by ``tests/webapp/parity.mjs``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..text import phrase, phrase_table
from ..ves.model_range import _share
from .odds import SuccessOdds, odds_tables

__all__ = [
    "KINDS",
    "even_spread",
    "measurement_basis",
    "measurement_cost_usd",
    "measurement_decision_caption",
    "measurement_decision_header",
    "measurement_decision_rows",
    "measurement_reading_header",
    "measurement_reading_rows",
    "measurement_readings_caption",
    "measurement_summary",
    "measurement_text",
    "measurement_value",
    "measurement_values",
    "MeasurementValue",
    "preposterior",
    "Reading",
]

#: The measurements priced, in the order the pages and reports give them.
KINDS = ("sounding", "profiling")

#: How far the tilt of the even spread is searched either way. The spread
#: is worked out with the largest exponent taken off, so nothing overflows
#: however far it goes; a tilt this large already puts all but 1e-300 of the
#: spread on the bands nearest a ratio of 1.
_TILT = 1.0e4


@dataclass
class Reading:
    """One band a measurement could read, for the readings table."""

    #: "depth" or "resistivity"
    evidence: str
    #: the bands of success_evidence.yaml it names: (regolith, basement) for
    #: the depth, (band,) for the resistivity
    bands: tuple[str, ...]
    #: the likelihood ratio, raised to the point's fit weight
    factor: float
    #: its share among working boreholes and among dry ones
    if_success: float
    if_dry: float
    #: the chance of reading it at this point now
    chance: float


@dataclass
class MeasurementValue:
    #: "sounding" or "profiling"
    kind: str
    #: what it costs, US$, from field.yaml
    cost_usd: float
    sounding_id: str
    #: the alternative: the other point's id, or None for an unsurveyed site
    #: on the same ground at the prior
    alternative_id: str | None
    #: the chance of a working borehole at the point and at the alternative
    probability: float
    alternative_probability: float
    #: the weight of the point's fit, which the measurement's ratios are
    #: raised to
    weight: float
    #: whether the depth to basement is read (the range was sampled)
    range_sampled: bool
    #: the mean completed borehole and the mean dry attempt (step 3.4)
    completed_usd: float
    dry_usd: float
    #: going to the alternative, and drilling at the point first
    alternative_usd: float
    drill_here_usd: float
    #: "here" or "move": the cheaper choice now, and its cost
    decision_now: str
    now_usd: float
    #: the factor on the odds at which the two choices cost the same: the
    #: decision changes on readings whose factors multiply past it
    threshold: float
    #: the readings that keep the decision and those that change it: their
    #: chance, the mean chance at the point after them, and the expected
    #: cost of the decision taken on them
    keep_chance: float
    keep_probability: float
    keep_usd: float
    change_chance: float
    change_probability: float
    change_usd: float
    #: the expected cost of the best decision after the measurement, the
    #: value of the measurement (EVSI) and of perfect information (EVPI)
    after_usd: float
    value_usd: float
    perfect_usd: float
    readings: list[Reading] = field(default_factory=list)


# ----------------------------------------------------------------- the maths

def even_spread(ratios: list[float]) -> tuple[list[float], list[float]] | None:
    """How often each band is seen among dry boreholes and among working
    ones, given only the bands' likelihood ratios: ``(if_dry, if_success)``,
    or None where the ratios cannot be read so (all on one side of 1, or all
    1), so that the class carries no information.

    The spread among dry boreholes is the most even one, the largest entropy,
    whose ratios average exactly 1, and that among working ones is it times
    the ratios. The most even spread is proportional to exp(-t r) for a tilt
    t, found by a bisection that both engines take in the same order: the
    average ratio falls as t rises.
    """
    lo, hi = min(ratios), max(ratios)
    if not lo < 1.0 < hi:
        return None

    def weights(t: float) -> tuple[list[float], float, float]:
        top = -t * (lo - 1.0) if t >= 0.0 else -t * (hi - 1.0)
        w = [math.exp(-t * (r - 1.0) - top) for r in ratios]
        total = 0.0
        weighted = 0.0
        for wi, r in zip(w, ratios, strict=True):
            total += wi
            weighted += wi * r
        return w, total, weighted

    a, b = -_TILT, _TILT
    for _ in range(200):
        mid = 0.5 * (a + b)
        _w, total, weighted = weights(mid)
        if weighted > total:
            a = mid
        else:
            b = mid
    w, total, weighted = weights(0.5 * (a + b))
    return ([wi / total for wi in w],
            [wi * r / weighted for wi, r in zip(w, ratios, strict=True)])


def _alternative_usd(completed: float, dry: float, q: float) -> float:
    """The expected cost of a working borehole at a chance ``q`` an attempt,
    dry attempts and all: step 3.4's expected cost per working borehole."""
    return completed + dry * ((1.0 - q) / q)


def _drill_here_usd(p: float, completed: float, dry: float, alternative: float) -> float:
    """Drilling at the point first: the completed borehole if it works, the
    dry attempt and then the alternative if it does not."""
    return p * completed + (1.0 - p) * (dry + alternative)


def preposterior(p: float, q: float, completed_usd: float, dry_usd: float,
                 classes: list[list[tuple[float, float, float]]]) -> dict:
    """The decision before and after a measurement, from the chance ``p`` at
    the point, ``q`` at the alternative, the costs, and for each class of
    evidence the measurement reads, its bands as ``(factor, if_success,
    if_dry)``. Every combination of one band from each class is a reading.

    Returns the fields of :class:`MeasurementValue` that are numbers worked
    out here. The value is summed reading by reading as what changing the
    decision saves where it is cheaper, so it is zero, not a rounding error
    either side of it, where no reading changes the decision.
    """
    if not (0.0 < p < 1.0 and 0.0 < q < 1.0):
        raise ValueError("the chances at the point and the alternative must be in (0, 1)")
    if not (completed_usd > 0.0 and dry_usd > 0.0):
        raise ValueError("the completed borehole and the dry attempt must cost more than 0")
    move = _alternative_usd(completed_usd, dry_usd, q)
    here = _drill_here_usd(p, completed_usd, dry_usd, move)
    # a tie keeps the first-ranked point
    stay_here = here <= move
    now = here if stay_here else move

    # every combination of one band from each class, the first class
    # outermost, as (if_success, if_dry)
    combined = [(1.0, 1.0)]
    for bands in classes:
        combined = [(s0 * s, f0 * f) for s0, f0 in combined for _r, s, f in bands]

    value = 0.0
    change = [0.0, 0.0]
    for s, f in combined:
        chance = p * s + (1.0 - p) * f
        if chance <= 0.0:
            continue
        after = p * s / chance
        cost_here = _drill_here_usd(after, completed_usd, dry_usd, move)
        saving = cost_here - move if stay_here else move - cost_here
        if saving > 0.0:
            value += chance * saving
            change[0] += chance
            change[1] += chance * after

    # The readings' chances add to 1 and their chances after average back
    # to p, so the readings that keep the choice are the rest. Worked out so,
    # a choice that nothing changes is kept on a chance of exactly 1 at
    # exactly p, not on a sum of fifty-odd products that rounds a last bit
    # either side of them (and prints "over 99" for 100).
    keep_chance = max(0.0, 1.0 - change[0])
    keep_p = (min(max((p - change[1]) / keep_chance, 0.0), 1.0)
              if keep_chance > 0.0 else 0.0)
    change_p = change[1] / change[0] if change[0] > 0.0 else 0.0
    # the cost of each group's decision at its mean chance, which is the mean
    # of its cost over the group: the cost of drilling here is linear in it
    if stay_here:
        keep_usd = (_drill_here_usd(keep_p, completed_usd, dry_usd, move)
                    if keep_chance else 0.0)
        change_usd = move if change[0] else 0.0
    else:
        keep_usd = move if keep_chance else 0.0
        change_usd = (_drill_here_usd(change_p, completed_usd, dry_usd, move)
                      if change[0] else 0.0)
    perfect = now - (p * completed_usd + (1.0 - p) * move)
    return {
        "alternative_usd": move, "drill_here_usd": here,
        "decision_now": "here" if stay_here else "move", "now_usd": now,
        "threshold": (q / (1.0 - q)) / (p / (1.0 - p)),
        "keep_chance": keep_chance, "keep_probability": keep_p, "keep_usd": keep_usd,
        "change_chance": change[0], "change_probability": change_p,
        "change_usd": change_usd,
        "after_usd": now - value, "value_usd": value, "perfect_usd": perfect,
    }


# ------------------------------------------------------------- the readings

def measurement_cost_usd(kind: str) -> float:
    """What one more measurement of ``kind`` costs, from data/field.yaml."""
    from ..field_kit import field_schedules

    costs = field_schedules()["one_more_measurement"]
    if kind == "sounding":
        return float(costs["sounding_usd"])
    if kind == "profiling":
        return float(costs["profiling_line_usd"])
    raise ValueError(f"no measurement of kind {kind!r} (expected one of {KINDS})")


def _classes(kind: str, range_sampled: bool) -> list[tuple[str, list[tuple[tuple[str, ...], float]]]]:
    """The classes of evidence a measurement reads: ``(evidence, [(bands,
    ratio)])``, in the order success_evidence.yaml gives them."""
    table = odds_tables()["evidence"]
    out = []
    if kind == "sounding" and range_sampled:
        basement = table["basement"]
        depth = [((band["key"], key), float(band["lr"]) * float(basement[key]["lr"]))
                 for band in table["regolith"] for key in ("resolved", "partly")]
        # where no basement is quoted, the depth brings no ratio of its own
        depth.append((("not_quoted", "unresolved"), float(basement["unresolved"]["lr"])))
        out.append(("depth", depth))
    resistivity = table["resistivity"]
    rho = [(("none",), float(resistivity["none"]["lr"]))]
    rho += [((band["key"],), float(band["lr"])) for band in resistivity["bands"]]
    out.append(("resistivity", rho))
    return out


def _fit_weight(o: SuccessOdds) -> float:
    for e in o.evidence:
        if e.key == "fit" and e.weight is not None:
            return float(e.weight)
    return 1.0


def measurement_value(o: SuccessOdds, alternative: SuccessOdds | None,
                      completed_usd: float, dry_usd: float,
                      kind: str = "sounding") -> MeasurementValue:
    """What one more measurement of ``kind`` at the point ``o`` is worth to
    the choice between drilling there and at ``alternative`` (None for an
    unsurveyed site on the same ground, at the point's prior).

    ``completed_usd`` and ``dry_usd`` are the cost distribution's mean
    completed borehole and mean dry attempt.
    """
    cost = measurement_cost_usd(kind)
    weight = _fit_weight(o)
    p = o.probability
    q = alternative.probability if alternative is not None else o.prior
    readings: list[Reading] = []
    classes = []
    for evidence, bands in _classes(kind, o.range_sampled):
        factors = [ratio ** weight for _bands, ratio in bands]
        spread = even_spread(factors)
        if spread is None:
            # nothing it reads can move the odds: one reading, a factor of 1
            continue
        dry, wet = spread
        classes.append(list(zip(factors, wet, dry, strict=True)))
        for (names, _ratio), factor, s, f in zip(bands, factors, wet, dry, strict=True):
            readings.append(Reading(evidence, names, factor, s, f, p * s + (1.0 - p) * f))
    worked = preposterior(p, q, completed_usd, dry_usd, classes)
    return MeasurementValue(
        kind=kind, cost_usd=cost, sounding_id=o.sounding_id,
        alternative_id=alternative.sounding_id if alternative is not None else None,
        probability=p, alternative_probability=q, weight=weight,
        range_sampled=o.range_sampled,
        completed_usd=float(completed_usd), dry_usd=float(dry_usd),
        readings=readings, **worked,
    )


def measurement_values(odds: list[SuccessOdds], ranking: list[int],
                       completed_usd: float, dry_usd: float) -> list[MeasurementValue]:
    """Every measurement in :data:`KINDS` at the survey's first-ranked point.

    ``odds`` is the chance at every point, in the interpretations' order, and
    ``ranking`` the points' positions in it in the order of the ranking
    (``[s.index for s in assess_siting(...)]``). The alternative is the other
    point with the best odds, the higher-ranked of any tied; on a survey of
    one point, an unsurveyed site on the same ground. Empty where there is no
    survey.
    """
    if not odds or not ranking:
        return []
    first = odds[ranking[0]]
    alternative = None
    for i in ranking[1:]:
        if alternative is None or odds[i].probability > alternative.probability:
            alternative = odds[i]
    return [measurement_value(first, alternative, completed_usd, dry_usd, kind)
            for kind in KINDS]


# -------------------------------------------------------------------- prose

def _usd(value: float) -> str:
    return f"{value:,.0f}"


def _what(v: MeasurementValue) -> str:
    return phrase("measurement.what_sounding" if v.kind == "sounding"
                  else "measurement.what_profiling", sid=v.sounding_id)


def _alternative(v: MeasurementValue) -> str:
    if v.alternative_id is None:
        return phrase("measurement.alternative_unsurveyed")
    return phrase("measurement.alternative_point", sid=v.alternative_id)


def _decision(v: MeasurementValue, here: bool) -> str:
    """The choice, as a sentence names it."""
    if here:
        return phrase("measurement.decision_here", sid=v.sounding_id)
    return phrase("measurement.decision_move", alternative=_alternative(v))


def _cell(v: MeasurementValue, here: bool) -> str:
    """The choice, as the decision table names it."""
    if here:
        return phrase("measurement.cell_here", sid=v.sounding_id)
    return phrase("measurement.cell_move", alternative=_alternative(v))


def measurement_summary(v: MeasurementValue) -> str:
    """The plan's sentence: what the measurement is worth to this decision
    and what it costs, or that it cannot change the decision."""
    if v.change_chance == 0.0:
        return phrase("measurement.zero", what=_what(v), sid=v.sounding_id,
                      cost=_usd(v.cost_usd))
    verdict = phrase("measurement.verdict_worth" if v.value_usd > v.cost_usd
                     else "measurement.verdict_not_worth")
    return phrase("measurement.headline", what=_what(v), value=_usd(v.value_usd),
                  cost=_usd(v.cost_usd), verdict=verdict)


def measurement_text(v: MeasurementValue) -> list[str]:
    """The value in sentences: the headline, the decision now, what would
    change it, what perfect information would be worth, and what was left
    out. :func:`measurement_basis` is said once beside them."""
    out = [measurement_summary(v)]
    out.append(phrase(
        "measurement.now_here" if v.decision_now == "here" else "measurement.now_move",
        sid=v.sounding_id, p=_share(v.probability), alternative=_alternative(v),
        q=_share(v.alternative_probability), here=_usd(v.drill_here_usd),
        move=_usd(v.alternative_usd)))
    if v.change_chance > 0.0:
        out.append(phrase(
            "measurement.change_below" if v.decision_now == "here"
            else "measurement.change_above",
            threshold=v.threshold, chance=_share(v.change_chance),
            decision=_decision(v, v.decision_now != "here"),
            after=_usd(v.after_usd), now=_usd(v.now_usd)))
    out.append(phrase("measurement.perfect", sid=v.sounding_id,
                      perfect=_usd(v.perfect_usd)))
    if v.kind == "sounding" and not v.range_sampled:
        out.append(phrase("measurement.not_sampled", sid=v.sounding_id))
    return out


def measurement_basis(v: MeasurementValue) -> str:
    """What every figure rests on, the same for every measurement."""
    return phrase("measurement.basis", completed=_usd(v.completed_usd),
                  dry=_usd(v.dry_usd), weight=v.weight)


def measurement_reading_header() -> list[str]:
    return [phrase("measurement.col_evidence"), phrase("measurement.col_reading"),
            phrase("measurement.col_factor"), phrase("measurement.col_success"),
            phrase("measurement.col_dry"), phrase("measurement.col_chance")]


def _edges(bands: list[dict], key: str) -> tuple[float | None, float | None]:
    """The lower and upper edge of the band ``key`` in a banded list."""
    lower = None
    for band in bands:
        upper = band.get("below")
        if band["key"] == key:
            return lower, (float(upper) if upper is not None else None)
        lower = float(upper) if upper is not None else lower
    raise KeyError(key)


def _span(bands: list[dict], key: str, unit: str) -> str:
    lo, hi = _edges(bands, key)
    if lo is None:
        return phrase("measurement.span_under", hi=hi, unit=unit)
    if hi is None:
        return phrase("measurement.span_over", lo=lo, unit=unit)
    return phrase("measurement.span_between", lo=lo, hi=hi, unit=unit)


def _reading_label(r: Reading) -> str:
    table = odds_tables()["evidence"]
    names = phrase_table("odds.bands")
    if r.evidence == "depth":
        if r.bands[0] == "not_quoted":
            return phrase("measurement.reading_unresolved")
        return phrase("measurement.reading_depth",
                      span=_span(table["regolith"], r.bands[0], "m"),
                      band=names[r.bands[0]], basement=names[r.bands[1]])
    if r.bands[0] == "none":
        return phrase("measurement.reading_no_zone")
    return phrase("measurement.reading_resistivity",
                  span=_span(table["resistivity"]["bands"], r.bands[0], "ohm-m"),
                  band=names[r.bands[0]])


def measurement_reading_rows(v: MeasurementValue) -> list[list[str]]:
    """Every band the measurement could read: its factor on the odds, its
    share among working and dry boreholes, and the chance of reading it at
    this point now."""
    labels = phrase_table("measurement.evidence")
    return [[labels[r.evidence], _reading_label(r), f"{r.factor:.2f}",
             _share(r.if_success), _share(r.if_dry), _share(r.chance)]
            for r in v.readings]


def measurement_decision_header(v: MeasurementValue) -> list[str]:
    return ["", phrase("measurement.col_case_chance"),
            phrase("measurement.col_after", sid=v.sounding_id),
            phrase("measurement.col_decision"), phrase("measurement.col_usd")]


def measurement_decision_rows(v: MeasurementValue) -> list[list[str]]:
    """The decision without the measurement, under the readings that keep it
    and those that change it, and the value: each expected cost times its
    chance adds up to the cost after the measurement, and the value is the
    difference from the cost now."""
    labels = phrase_table("measurement.rows")
    here = v.decision_now == "here"
    rows = [[labels["now"], "", _share(v.probability), _cell(v, here), _usd(v.now_usd)]]
    if v.keep_chance > 0.0:
        rows.append([labels["keep"], _share(v.keep_chance), _share(v.keep_probability),
                     _cell(v, here), _usd(v.keep_usd)])
    if v.change_chance > 0.0:
        rows.append([labels["change"], _share(v.change_chance),
                     _share(v.change_probability), _cell(v, not here),
                     _usd(v.change_usd)])
    rows.append([labels["after"], "", "", "", _usd(v.after_usd)])
    rows.append([labels["value"], "", "", "", _usd(v.value_usd)])
    rows.append([labels["perfect"], "", "", "", _usd(v.perfect_usd)])
    return rows


def measurement_readings_caption(v: MeasurementValue) -> str:
    return phrase("measurement.readings_caption", sid=v.sounding_id)


def measurement_decision_caption() -> str:
    return phrase("measurement.decision_caption")

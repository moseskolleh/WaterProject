"""The few numbers a report asks a decision on, each with its band (PLAN.md
step 3.6).

Stage 3 gave each of them a spread: the drilling depth a range of models
(step 3.1), the yield and the pump setting a bootstrap (3.2), the chance of
a working borehole a prior carried through the survey (3.3) and the cost a
distribution (3.4). Each step printed its band in words of its own, in its
own section, and a reader of the executive summary saw the drilling depth
and the yield as single numbers. Here every one of them is printed the same
way, as its value, its band and what the band rests on:

    Safe yield: 0.391 m3/h (P10 to P90 of the transmissivity, 0.354 to
    0.443 m3/h); basis: a block bootstrap of the Cooper-Jacob fit, ...;
    provisional.

and where no band can be given yet, the line says why instead of inventing
one: "no band: the range of models has not been sampled at VES-2". The
words are in ``data/text/decision.yaml``, and ``docs/js/gwt-core.js`` (the
section headed "decision numbers") builds the same lines from the same
results, held to these by the parity suite.

The readiness gate (:mod:`groundwater.readiness`) reads the same numbers
through :func:`decision_numbers`, so a report and the gate over it cannot
disagree about which number lacks a band.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config, PumpingConfig
from .text import phrase, phrase_table

__all__ = [
    "DecisionNumber",
    "REPORT_DECISIONS",
    "cost_decision",
    "decision_numbers",
    "decision_text",
    "depth_decision",
    "odds_decision",
    "preferred_index",
    "pump_decision",
    "recommended_points",
    "yield_decision",
]


@dataclass(frozen=True)
class DecisionNumber:
    """One decision number as a report prints it."""

    #: "depth", "yield", "pump", "odds" or "cost"
    key: str
    name: str
    value: str
    #: the band in words, or None where there is none
    band: str | None
    #: why there is no band, where there is none
    reason: str
    basis: str
    #: "provisional" or "calibrated": whether what the band rests on has
    #: been checked against boreholes drilled here
    status: str = "provisional"

    @property
    def has_band(self) -> bool:
        return self.band is not None

    @property
    def text(self) -> str:
        return decision_text(self)


def decision_text(d: DecisionNumber) -> str:
    """The one line every report prints for a decision number."""
    band = d.band if d.band is not None else phrase("decision.no_band", reason=d.reason)
    return phrase("decision.line", name=d.name, value=d.value, band=band,
                  basis=d.basis, status=phrase_table("decision.status")[d.status])


# ------------------------------------------------------------- each number

def depth_decision(interp, model_range, config: Config | None = None) -> DecisionNumber:
    """The drilling depth at a point: the best fit's, as every report states
    it, with the band of the depth each sampled model would be drilled to,
    rounded and cut back as the range's own drilling depth is (whose P90 is
    the band's top)."""
    from .costing.distribution import depth_spread
    from .ves.interpret import drilling_depth_text

    sid = interp.sounding_id
    name = phrase("decision.depth_name", sid=sid)
    value = drilling_depth_text(interp)
    spread = depth_spread(model_range, config)
    if spread is None:
        return DecisionNumber("depth", name, value, None,
                              phrase("decision.depth_not_sampled", sid=sid),
                              phrase("decision.depth_basis_alone"))
    low, high = spread.draw(0.1), spread.draw(0.9)
    band = (phrase("decision.depth_band_flat", low=low) if low == high
            else phrase("decision.depth_band", low=low, high=high))
    return DecisionNumber(
        "depth", name, value, band, "",
        phrase("decision.depth_basis", samples=model_range.n_samples, step=spread.step_m,
               doi=spread.cap_m))


def yield_decision(analysis, config: PumpingConfig | None = None) -> DecisionNumber | None:
    """The safe yield with the band step 3.2's bootstrap puts on it, or None
    where there is no yield to give."""
    from .hydraulics.analysis import METHOD_LABELS

    rec = getattr(analysis, "yield_recommendation", None)
    if rec is None or rec.safe_yield_m3_per_h is None:
        return None
    config = config or PumpingConfig()
    name, value = phrase("decision.yield_name"), phrase("decision.yield_value",
                                                        x=rec.safe_yield_m3_per_h)
    # a yield rests on an adopted fit, so the method has a label; "adopted"
    # stands in for one only on an analysis built by hand
    alone = phrase("decision.yield_basis_alone",
                   method=METHOD_LABELS.get(analysis.transmissivity_source or "", "adopted"),
                   reserve=config.seasonal_allowance_m)
    spread = getattr(analysis, "spread", None)
    boot = spread.bootstrap if spread is not None else None
    if spread is None or boot is None:
        return DecisionNumber("yield", name, value, None,
                              phrase("decision.yield_no_spread"), alone)
    if boot.p10 is None:
        return DecisionNumber("yield", name, value, None,
                              phrase_table("pumping.spread_reasons")[boot.reason], alone)
    if spread.safe_yield_low_m3_per_h is None:
        return DecisionNumber("yield", name, value, None,
                              phrase("decision.yield_no_low"), alone)
    if spread.safe_yield_high_m3_per_h is None:
        band = phrase("decision.yield_band_open", low=spread.safe_yield_low_m3_per_h)
    else:
        band = phrase("decision.yield_band", low=spread.safe_yield_low_m3_per_h,
                      high=spread.safe_yield_high_m3_per_h)
    return DecisionNumber("yield", name, value, band, "", phrase(
        "decision.yield_basis", method=METHOD_LABELS[boot.method],
        reserve=config.seasonal_allowance_m))


def pump_decision(analysis, depth: float | None = None,
                  moved: str | None = None) -> DecisionNumber | None:
    """The pump intake the yield recommendation sets, with the band a
    dry-season decline moves it over, or None where it sets none.

    ``depth`` is the intake the report prints where that is not the
    recommendation's, and ``moved`` what set it there: "design" (the design
    put it in plain casing) or "seasonal" (the seasonal projection's
    drought-year low wants it deeper). The band stays the recommendation's,
    and says so.
    """
    from .hydraulics.spread import _seasonal_range

    rec = getattr(analysis, "yield_recommendation", None)
    advised = rec.pump_installation_depth_m if rec is not None else None
    if advised is None:
        return None
    if depth is None or moved is None or depth == advised:
        depth, band_key = advised, "decision.pump_band"
        basis = phrase("decision.pump_basis")
    else:
        # the band is the recommendation's, which the printed intake can lie
        # outside, so the band says whose it is
        band_key = "decision.pump_band_moved"
        basis = phrase("decision.pump_basis_moved", rec=advised,
                       where=phrase_table("decision.pump_moved")[moved])
    name, value = phrase("decision.pump_name"), phrase("decision.pump_value", x=depth)
    spread = getattr(analysis, "spread", None)
    if spread is None or spread.pump_depth_low_m is None:
        return DecisionNumber("pump", name, value, None,
                              phrase("decision.pump_no_spread"), basis)
    decline_low, decline_high = _seasonal_range()
    return DecisionNumber("pump", name, value, phrase(
        band_key, decline_low=decline_low, decline_high=decline_high,
        low=spread.pump_depth_low_m, high=spread.pump_depth_high_m), "", basis)


def odds_decision(o) -> DecisionNumber:
    """The chance of a working borehole at a point. It always has a band:
    the prior's own, carried through the survey's factors."""
    from .ves.model_range import _share

    return DecisionNumber(
        "odds", phrase("decision.odds_name", sid=o.sounding_id),
        phrase("decision.odds_value", p=_share(o.probability)),
        phrase("decision.odds_band", low=_share(o.low), high=_share(o.high)), "",
        phrase("decision.odds_basis", n=o.effective_n),
        "calibrated" if o.status == "calibrated" else "provisional")


def cost_decision(distribution=None, estimate=None) -> DecisionNumber | None:
    """The cost of a completed borehole: the distribution's P50 with its P10
    to P90 (and the P80 a budget is set at), or the bill of quantities with
    no band where no distribution was sampled; None with neither."""
    from .costing.distribution import _usd

    name = phrase("decision.cost_name")
    d = distribution
    if d is None:
        if estimate is None:
            return None
        return DecisionNumber(
            "cost", name, phrase("decision.cost_value_boq", boq=_usd(estimate.price_with_vat_usd)),
            None, phrase("decision.cost_not_sampled"), phrase("decision.cost_basis_boq"))
    if d.depth_source is None:
        depth = phrase("decision.cost_depth_fixed", depth=d.depth_m)
    else:
        depth = phrase("decision.cost_depth_drawn", sid=d.depth_source)
    # the curve is the cost at every percent, so a tenth of the way along it
    # and nine tenths are the P10 and P90 of the same sample, worked out as
    # P50 is
    tenth = (len(d.curve) - 1) // 10
    return DecisionNumber(
        "cost", name, phrase("decision.cost_value", p50=_usd(d.p50)),
        phrase("decision.cost_band", n=f"{d.samples:,}", count=d.samples,
               low=_usd(d.curve[tenth]),
               high=_usd(d.curve[len(d.curve) - 1 - tenth]), p80=_usd(d.p80)), "",
        phrase("decision.cost_basis", depth=depth, boq=_usd(d.boq_usd)))


# --------------------------------------------------------------- per report

#: The decision numbers each report asks a decision on. A geophysical report
#: recommends where and how deep to drill and how likely that is to work; a
#: pumping, completion or handover report sets the abstraction rate and the
#: pump; a cost report the budget. The others decide nothing that has a
#: spread: a water quality result is graded against a limit, and a
#: supervision record, a plate or a certificate records what was done.
REPORT_DECISIONS: dict[str, tuple[str, ...]] = {
    "geophysical": ("depth", "odds"),
    "pumping": ("yield", "pump"),
    "completion": ("yield", "pump"),
    "handover": ("yield", "pump"),
    "costing": ("cost",),
}


def preferred_index(interpretations) -> int | None:
    """The position of the point a report recommends: the first-ranked, the
    earlier of two on the same rank, the first where none is ranked."""
    if not interpretations:
        return None
    return min(range(len(interpretations)),
               key=lambda i: (getattr(interpretations[i], "rank", None) or 99, i))


def recommended_points(interpretations, config: Config | None = None) -> list[int]:
    """The positions of the points a geophysical report recommends drilling:
    the first-ranked, and with it the second where the ranking cannot
    separate them, by the test the report's tie sentence and summary use
    (:func:`groundwater.siting.tied_leaders`). The summary then offers
    either point, so the depth and the odds at both are decision numbers."""
    i = preferred_index(interpretations)
    if i is None or len(interpretations) < 2:
        return [] if i is None else [i]
    from .siting import assess_siting, tied_leaders

    ves = (config or Config()).ves
    if tied_leaders(assess_siting(interpretations, ves), ves.ranking_tie_points) is None:
        return [i]
    return sorted(range(len(interpretations)),
                  key=lambda k: (getattr(interpretations[k], "rank", None) or 99, k))[:2]


def decision_numbers(state: dict, report: str, config: Config | None = None
                     ) -> list[DecisionNumber]:
    """The decision numbers of one report, from a project keyed as the
    readiness gate reads it: ``interpretations`` with ``model_ranges`` and
    ``odds`` in lockstep, ``pump_analysis``, ``cost_distribution`` and
    ``cost_estimate``. A number with nothing to work it out from is left
    out; the gate's other requirements say what is missing.

    The survey's numbers are at ``points``, the positions
    :func:`recommended_points` gives, where the caller has them; the
    first-ranked point alone otherwise."""
    config = config or Config()
    out: list[DecisionNumber | None] = []
    wanted = REPORT_DECISIONS.get(report, ())
    interps = state.get("interpretations") or []
    points = state.get("points")
    if points is None:
        i = preferred_index(interps)
        points = [] if i is None else [i]
    ranges = list(state.get("model_ranges") or [])
    odds = list(state.get("odds") or [])
    for i in points:
        if "depth" in wanted:
            out.append(depth_decision(interps[i], ranges[i] if i < len(ranges) else None,
                                      config))
        if "odds" in wanted and i < len(odds) and odds[i] is not None:
            out.append(odds_decision(odds[i]))
    analysis = state.get("pump_analysis")
    if analysis is not None and "yield" in wanted:
        out.append(yield_decision(analysis, config.pumping))
    if analysis is not None and "pump" in wanted:
        out.append(pump_decision(analysis))
    if "cost" in wanted:
        out.append(cost_decision(state.get("cost_distribution"), state.get("cost_estimate")))
    return [d for d in out if d is not None]

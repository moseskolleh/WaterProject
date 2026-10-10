"""The cost as a distribution (PLAN.md step 3.4).

The bill of quantities prices one borehole at the likely rate of every item.
It stays the contract document: it is what a contractor prices and is paid
against. What a budget needs is different: what a borehole is likely to cost
once the things that are not known before drilling are allowed for. This
samples them:

1. **The rates**: every unit rate in ``data/borehole_cost_items.csv`` has a
   minimum and a maximum beside its likely value, each with its reason in
   ``data/borehole_cost_spread.yaml``. Each is drawn from the triangle
   between them. Rates in one group there share a cause (the pump price
   for both fuel lines, supply for the bought materials) and are drawn
   together, at one point of each of their triangles; the groups are drawn
   independently. The mobilisation lines (the journey, the rig's day
   charge, the crew and the site set-up) are drawn so too.
2. **The depth**: drawn from the range of models (step 3.1) at the survey's
   first-ranked point, read the way the range reads its drilling depth
   (rounded up to the drilling step and cut back to the depth of
   investigation). The casing and the gravel pack are lengthened or
   shortened with it, and a quantity left to a rule of thumb (the
   overburden, the crew days) is worked out again at the drawn depth. Where
   no range has been sampled the depth is held at the estimate's, and the
   text says the depth's spread is left out.
3. **Dry holes**: each sampled attempt finds water with the chance of a
   working borehole at that point (step 3.3), as a probability. A dry
   attempt pays for siting, set-up and drilling, as the programme estimate
   counts one, but not the journey from the base.

Each sampled borehole is priced as the bill of quantities is: the same
overheads, margin and VAT on its direct cost. Its P50 and P80 are the
planning figure for a completed borehole, and all the money spent over the
sampled attempts divided by the ones that found water is the expected cost
per working borehole. A programme (``programme.py``) is sampled whole: its
rates and depth drawn once, as one contract prices every borehole in it, and
its dry attempts drawn one by one until it has the boreholes it needs.

Both engines run this, and ``gwt-core.js`` is held to it by
``tests/webapp/parity.mjs``. Every number comes from the range of models'
generator (xoshiro128**), and the arithmetic is additions, products,
quotients and square roots, which IEEE doubles round the same way in both,
so the two engines' distributions agree to the bit; the sums here are
written as loops, never ``sum()``, which Python 3.12 compensates and
JavaScript does not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from ..config import Config
from ..text import phrase, phrase_table
from .model import (
    CostingInputs,
    RateItem,
    _quantity_table,
    default_casing_m,
    default_crew_days,
    default_gravel_interval_m,
    default_overburden_m,
    estimate_borehole_cost,
    load_rates,
)
from .programme import _DRY_STAGES, estimate_programme_cost

__all__ = [
    "CostDistribution",
    "DepthSpread",
    "ProgrammeDistribution",
    "cost_range_header",
    "cost_range_rows",
    "cost_range_text",
    "depth_spread",
    "failures_table",
    "programme_range_rows",
    "programme_range_text",
    "sample_cost",
    "sample_programme_cost",
    "triangle_quantile",
]


def _ves():
    """The range of models' generator, percentile and share wording. Read on
    first use: ves.model_range brings the VES readers (and openpyxl) with
    it, which importing the costing package for its arithmetic should not."""
    from ..ves import model_range

    return model_range


def percentile(sorted_values: list[float], q: float) -> float:
    return _ves().percentile(sorted_values, q)


def _share(fraction: float) -> str:
    return _ves()._share(fraction)


# One stream of the generator for each kind of draw, so the rates a borehole
# is given do not depend on whether its depth or its outcome was drawn.
_RATES, _DEPTH, _OUTCOME = 0, 1, 2

#: The cumulative curve the figures draw: the cost at every percent.
CURVE_STEPS = 100

#: A dry attempt does not pay this basis: the rig has made the journey.
_JOURNEY = "per_km_round_trip"


def triangle_quantile(lo: float, mode: float, hi: float, u: float) -> float:
    """The value of a triangular distribution with probability ``u`` at or
    below it: the triangle's inverse distribution function. A triangle with no
    width is its likely value, whatever ``u`` is."""
    if hi <= lo:
        return mode
    width = hi - lo
    if u < (mode - lo) / width:
        return lo + math.sqrt(u * width * (mode - lo))
    return hi - math.sqrt((1.0 - u) * width * (hi - mode))


# ------------------------------------------------------------------ the depth

@dataclass
class DepthSpread:
    """The drilling depth as the range of models gives it, to draw from."""

    sounding_id: str
    #: the depth at every twentieth of the way from the least to the greatest
    quantiles_m: list[float]
    step_m: float
    cap_m: float

    def draw(self, u: float) -> float:
        """The depth with probability ``u`` at or below it, between the
        quantiles, rounded up to the drilling step and cut back to the depth
        of investigation as the range's own drilling depth is."""
        q = self.quantiles_m
        pos = u * (len(q) - 1)
        k = int(math.floor(pos))
        x = q[-1] if k + 1 >= len(q) else q[k] + (q[k + 1] - q[k]) * (pos - k)
        return min(math.ceil(x / self.step_m) * self.step_m, self.cap_m)


def depth_spread(model_range, config: Config | None = None) -> DepthSpread | None:
    """The depth to draw from a sampled range of models, or None where there
    is no range (or one sampled before the range kept its depths)."""
    if model_range is None or not getattr(model_range, "drilling_depth_quantiles_m", None):
        return None
    config = config or Config()
    return DepthSpread(
        sounding_id=model_range.sounding_id,
        quantiles_m=[float(v) for v in model_range.drilling_depth_quantiles_m],
        step_m=float(config.ves.round_drilling_depth_to_m),
        cap_m=float(model_range.investigation_depth_m),
    )


def _at_depth(given: CostingInputs, base: CostingInputs, depth: float) -> CostingInputs:
    """The quantities of ``base`` (``given`` resolved) for a borehole drilled
    to ``depth`` instead: a length supplied is moved by the change in depth, a
    length left to a rule of thumb is worked out again, and a gravel pack the
    design leaves out stays out."""
    if depth == base.total_depth_m:
        return base
    shift = depth - base.total_depth_m
    over = (default_overburden_m(depth) if given.overburden_m is None
            else given.overburden_m)
    if given.casing_m is None:
        casing = default_casing_m(depth, base.screen_m or 0.0)
    else:
        casing = max(0.0, given.casing_m + shift)
    if given.gravel_interval_m is None:
        gravel = default_gravel_interval_m(depth)
    elif given.gravel_interval_m == 0.0:
        gravel = 0.0
    else:
        gravel = max(0.0, given.gravel_interval_m + shift)
    return replace(
        base, total_depth_m=depth, overburden_m=min(over, depth), casing_m=casing,
        gravel_interval_m=gravel,
        crew_days=default_crew_days(depth) if given.crew_days is None else given.crew_days,
    )


class _Quantities:
    """Each rate's quantity at a depth, or None for a basis the estimate does
    not know (which it skips, as the bill of quantities does). A depth drawn
    from the range falls on a whole drilling step, so few are worked out."""

    def __init__(self, given: CostingInputs, rates: list[RateItem]):
        self.given = given
        self.base, _ = given.resolved()
        self.bases = [r.quantity_basis for r in rates]
        self._cache: dict[float, list[float | None]] = {}

    def at(self, depth: float) -> list[float | None]:
        hit = self._cache.get(depth)
        if hit is None:
            table = _quantity_table(_at_depth(self.given, self.base, depth))
            hit = [table.get(b) for b in self.bases]
            self._cache[depth] = hit
        return hit


def _price(direct: float, overheads: float, margin: float, vat: float) -> float:
    """The contract price with any VAT on a direct cost, worked out in the
    order CostEstimate works it out, so a borehole drawn at every likely rate
    is priced to the bit as the bill of quantities prices it."""
    total = direct + direct * overheads / 100.0
    price = total + total * margin / 100.0
    return price + price * vat / 100.0


class _Rates:
    """Draws the catalogue's rates: one uniform for each spread group, in
    the order the groups first appear, and every rate in a group read from
    its own triangle at that group's uniform, so rates that share a cause
    move together and groups move apart."""

    def __init__(self, rates: list[RateItem]):
        self.triangles = [r.triangle() for r in rates]
        order: dict[str, int] = {}
        self.group = [order.setdefault(r.spread_group or "\0" + r.code, len(order))
                      for r in rates]
        self.groups = len(order)

    def draw(self, rng) -> list[float]:
        us = [rng.uniform() for _ in range(self.groups)]
        return [triangle_quantile(lo, mode, hi, us[g])
                for (lo, mode, hi), g in zip(self.triangles, self.group, strict=True)]


def _share_at_or_under(sorted_values: list[float], value: float) -> float:
    """The share of the sampled values at or under ``value``. A figure the
    sampled ones equal to the last bit counts as reached: a borehole drawn
    at every likely rate is the bill of quantities, summed in another
    order."""
    limit = value + abs(value) * 1e-12
    lo, hi = 0, len(sorted_values)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_values[mid] <= limit:
            lo = mid + 1
        else:
            hi = mid
    return lo / len(sorted_values)


def _curve(sorted_values: list[float]) -> list[float]:
    return [percentile(sorted_values, k / CURVE_STEPS) for k in range(CURVE_STEPS + 1)]


def _mean(values: list[float]) -> float:
    total = 0.0
    for v in values:
        total += v
    return total / len(values)


def _settings(config: Config | None, samples: int | None, seed: int | None):
    config = config or Config()
    n = int(config.cost_range.samples if samples is None else samples)
    if n < 1:
        raise ValueError("the cost distribution needs at least one sample")
    return config, n, int(config.cost_range.seed if seed is None else seed)


# ------------------------------------------------------------ one borehole

@dataclass
class CostDistribution:
    samples: int
    seed: int
    #: the depth the bill of quantities prices, and where the drawn one came
    #: from (None where it was held there)
    depth_m: float
    depth_source: str | None
    #: P10 and P90 of the depths drawn
    depth_p10_m: float
    depth_p90_m: float
    #: the chance each attempt found water, and the point it is the odds of
    #: (None where no odds were given and none was drawn dry)
    success_probability: float
    odds_source: str | None
    #: the contract price with any VAT of a completed borehole
    p50: float
    p80: float
    mean: float
    #: all spent over the sampled attempts, over the ones that found water;
    #: None where none did
    expected_per_working: float | None
    successes: int
    #: the bill of quantities' own figures, and the share of the sampled
    #: boreholes at or under each
    boq_usd: float
    budget_usd: float
    boq_share: float
    budget_share: float
    overheads_percent: float
    margin_percent: float
    contingency_percent: float
    vat_percent: float
    #: the share of the sampled boreholes at or under the mean
    mean_share: float = 0.0
    #: the cost at every percent from 0 to 100, for the figure
    curve: list[float] = field(default_factory=list)


def sample_cost(
    inputs: CostingInputs,
    rates: list[RateItem] | None = None,
    *,
    depth: DepthSpread | None = None,
    success_probability: float = 1.0,
    odds_source: str | None = None,
    overheads_percent: float = 15.0,
    margin_percent: float = 20.0,
    contingency_percent: float = 10.0,
    vat_percent: float = 0.0,
    config: Config | None = None,
    samples: int | None = None,
    seed: int | None = None,
) -> CostDistribution:
    """Sample the cost of one borehole, with the arguments
    :func:`estimate_borehole_cost` takes plus where the depth and the dry
    holes are drawn from.

    ``success_probability`` is the chance an attempt finds water, in
    (0, 1]; ``odds_source`` names the point it is the odds of. With 1, no
    attempt is dry and the expected cost per working borehole is the mean.
    """
    if not 0.0 < success_probability <= 1.0:
        raise ValueError("the chance of success must be in (0, 1]")
    config, n, seed = _settings(config, samples, seed)
    rates = rates if rates is not None else load_rates()
    pct = dict(overheads_percent=overheads_percent, margin_percent=margin_percent,
               contingency_percent=contingency_percent, vat_percent=vat_percent)
    boq = estimate_borehole_cost(inputs, rates, **pct)
    quantities = _Quantities(inputs, rates)
    draws = _Rates(rates)
    dry_line = [r.stage in _DRY_STAGES and r.quantity_basis != _JOURNEY for r in rates]

    rate_rng, depth_rng, outcome_rng = (_ves().Stream(seed, s)
                                        for s in (_RATES, _DEPTH, _OUTCOME))
    base_depth = quantities.base.total_depth_m
    costs: list[float] = []
    depths: list[float] = []
    spent = 0.0
    found = 0
    for _ in range(n):
        drawn = draws.draw(rate_rng)
        d = depth.draw(depth_rng.uniform()) if depth is not None else base_depth
        direct = 0.0
        dry = 0.0
        for j, q in enumerate(quantities.at(d)):
            if q is None:
                continue
            amount = q * drawn[j]
            direct += amount
            if dry_line[j]:
                dry += amount
        cost = _price(direct, overheads_percent, margin_percent, vat_percent)
        costs.append(cost)
        depths.append(d)
        if outcome_rng.uniform() < success_probability:
            found += 1
            spent += cost
        else:
            spent += _price(dry, overheads_percent, margin_percent, vat_percent)

    mean = _mean(costs)
    ordered = sorted(costs)
    depths.sort()
    return CostDistribution(
        samples=n, seed=seed,
        depth_m=float(base_depth),
        depth_source=depth.sounding_id if depth is not None else None,
        depth_p10_m=percentile(depths, 0.1), depth_p90_m=percentile(depths, 0.9),
        success_probability=float(success_probability), odds_source=odds_source,
        p50=percentile(ordered, 0.5), p80=percentile(ordered, 0.8), mean=mean,
        expected_per_working=spent / found if found else None,
        successes=found,
        boq_usd=boq.price_with_vat_usd, budget_usd=boq.budget_usd,
        boq_share=_share_at_or_under(ordered, boq.price_with_vat_usd),
        budget_share=_share_at_or_under(ordered, boq.budget_usd),
        mean_share=_share_at_or_under(ordered, mean),
        curve=_curve(ordered),
        **pct,
    )


# -------------------------------------------------------------- the programme

def failures_table(n: int, p: float) -> tuple[int, list[float]]:
    """The dry attempts a programme of ``n`` working boreholes makes at a
    chance ``p`` of success each, as a table to draw from: the least count
    kept and the running totals of the weights from it (the negative
    binomial distribution, scaled to 1 at its mode).

    The weights are worked out outwards from the mode by the ratio of one to
    the next, products and quotients only, and stop where they fall below
    1e-17 of the mode's: no logarithm, so both engines build the same table,
    and nothing underflows where p^n would.
    """
    if p >= 1.0:
        return 0, [1.0]
    q = 1.0 - p
    mode = math.floor((n - 1) * q / p) if n > 1 else 0
    below: list[float] = []
    w = 1.0
    k = mode
    while k > 0:
        w = w * k / ((n + k - 1) * q)
        if w < 1e-17:
            break
        below.append(w)
        k -= 1
    weights = below[::-1] + [1.0]
    w = 1.0
    k = mode
    while True:
        w = w * (n + k) * q / (k + 1)
        if w < 1e-17:
            break
        weights.append(w)
        k += 1
    running = []
    total = 0.0
    for v in weights:
        total += v
        running.append(total)
    return mode - len(below), running


def _draw_failures(first: int, running: list[float], u: float) -> int:
    """The count whose running weight first reaches ``u`` of the total."""
    target = u * running[-1]
    lo, hi = 0, len(running) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if running[mid] >= target:
            hi = mid
        else:
            lo = mid + 1
    return first + lo


@dataclass
class ProgrammeDistribution:
    n_boreholes: int
    samples: int
    seed: int
    success_rate_percent: float
    depth_source: str | None
    #: the programme's contract price with any VAT
    p50: float
    p80: float
    mean: float
    #: the same over the boreholes it delivers
    per_working_expected: float
    per_working_p80: float
    #: attempts at P50 and P80, rounded up to whole attempts, and the
    #: estimate's
    attempts_p50: int
    attempts_p80: int
    attempts_planned: int
    #: the programme estimate's own figures, and the share of the sampled
    #: programmes at or under each
    estimate_usd: float
    budget_usd: float
    estimate_share: float
    budget_share: float
    contingency_percent: float
    mean_share: float = 0.0
    curve: list[float] = field(default_factory=list)


def sample_programme_cost(
    per_well: CostingInputs,
    n_boreholes: int,
    *,
    rates: list[RateItem] | None = None,
    inter_site_distance_km: float = 15.0,
    success_rate_percent: float = 100.0,
    depth: DepthSpread | None = None,
    overheads_percent: float = 15.0,
    margin_percent: float = 20.0,
    contingency_percent: float = 10.0,
    vat_percent: float = 0.0,
    config: Config | None = None,
    samples: int | None = None,
    seed: int | None = None,
) -> ProgrammeDistribution:
    """Sample the cost of a programme, with the arguments
    :func:`estimate_programme_cost` takes plus where the depth is drawn from.

    Each sampled programme draws its rates and its depth once and its dry
    attempts from :func:`failures_table`, and is priced as the estimate
    prices it: one journey from the base, a move between sites for every
    attempt after the first, and each dry attempt's siting, set-up and
    drilling.
    """
    rates = rates if rates is not None else load_rates()
    estimate = estimate_programme_cost(
        per_well, n_boreholes, rates=rates, inter_site_distance_km=inter_site_distance_km,
        success_rate_percent=success_rate_percent, overheads_percent=overheads_percent,
        margin_percent=margin_percent, contingency_percent=contingency_percent,
        vat_percent=vat_percent)
    config, n, seed = _settings(config, samples, seed)
    well_inputs = CostingInputs(**{**per_well.__dict__, "mobilisation_distance_km": 0.0})
    quantities = _Quantities(well_inputs, rates)
    draws = _Rates(rates)
    dry_line = [r.stage in _DRY_STAGES for r in rates]
    journey = [r.quantity_basis == _JOURNEY for r in rates]
    first, running = failures_table(n_boreholes, success_rate_percent / 100.0)

    rate_rng, depth_rng, outcome_rng = (_ves().Stream(seed, s)
                                        for s in (_RATES, _DEPTH, _OUTCOME))
    base_depth = quantities.base.total_depth_m
    base_km = 2.0 * per_well.mobilisation_distance_km
    totals: list[float] = []
    attempts: list[float] = []
    for _ in range(n):
        drawn = draws.draw(rate_rng)
        d = depth.draw(depth_rng.uniform()) if depth is not None else base_depth
        failures = _draw_failures(first, running, outcome_rng.uniform())
        well = 0.0
        dry = 0.0
        km_rate = 0.0
        for j, q in enumerate(quantities.at(d)):
            if journey[j]:
                km_rate += drawn[j]
            if q is None:
                continue
            amount = q * drawn[j]
            well += amount
            if dry_line[j]:
                dry += amount
        tried = n_boreholes + failures
        transport = km_rate * (base_km + max(0, tried - 1) * inter_site_distance_km)
        direct = n_boreholes * well + failures * dry + transport
        total = direct * (1 + overheads_percent / 100.0)
        price = total * (1 + margin_percent / 100.0)
        totals.append(price * (1 + vat_percent / 100.0))
        attempts.append(float(tried))

    mean = _mean(totals)
    ordered = sorted(totals)
    attempts.sort()
    return ProgrammeDistribution(
        n_boreholes=n_boreholes, samples=n, seed=seed,
        success_rate_percent=float(success_rate_percent),
        depth_source=depth.sounding_id if depth is not None else None,
        p50=percentile(ordered, 0.5), p80=percentile(ordered, 0.8), mean=mean,
        per_working_expected=mean / n_boreholes,
        per_working_p80=percentile(ordered, 0.8) / n_boreholes,
        attempts_p50=math.ceil(percentile(attempts, 0.5)),
        attempts_p80=math.ceil(percentile(attempts, 0.8)),
        attempts_planned=estimate.n_attempted,
        estimate_usd=estimate.price_with_vat_usd, budget_usd=estimate.budget_usd,
        estimate_share=_share_at_or_under(ordered, estimate.price_with_vat_usd),
        budget_share=_share_at_or_under(ordered, estimate.budget_usd),
        contingency_percent=float(contingency_percent),
        mean_share=_share_at_or_under(ordered, mean),
        curve=_curve(ordered),
    )


# --------------------------------------------------------------------- prose

def _usd(value: float) -> str:
    return f"{value:,.0f}"


def cost_range_text(d: CostDistribution) -> list[str]:
    """The distribution in sentences: which figure is which, the P50 and
    P80, what they are prices of, the cost per working borehole, where the
    depth came from, and the basis."""
    out = [
        phrase("cost_range.which_is_which"),
        phrase("cost_range.headline", p50=_usd(d.p50), p80=_usd(d.p80), n=f"{d.samples:,}",
               boq=_usd(d.boq_usd), boq_share=_share(d.boq_share)),
        phrase("cost_range.price_basis", overheads=d.overheads_percent,
               margin=d.margin_percent, contingency=d.contingency_percent,
               budget=_usd(d.budget_usd), budget_share=_share(d.budget_share)),
    ]
    if d.odds_source is None:
        out.append(phrase("cost_range.working_no_odds", mean=_usd(d.mean)))
    elif d.expected_per_working is None:
        out.append(phrase("cost_range.working_none", sid=d.odds_source,
                          p=_share(d.success_probability), n=f"{d.samples:,}"))
    else:
        out.append(phrase("cost_range.working", sid=d.odds_source,
                          p=_share(d.success_probability),
                          expected=_usd(d.expected_per_working)))
    if d.depth_source is None:
        out.append(phrase("cost_range.depth_fixed", depth=d.depth_m))
    else:
        out.append(phrase("cost_range.depth_range", sid=d.depth_source, p10=d.depth_p10_m,
                          p90=d.depth_p90_m, depth=d.depth_m))
    out.append(phrase("cost_range.basis", seed=d.seed))
    return out


def cost_range_header() -> list[str]:
    return [phrase("cost_range.col_item"), phrase("cost_range.col_usd"),
            phrase("cost_range.col_share")]


def cost_range_rows(d: CostDistribution) -> list[list[str]]:
    """The planning figure beside the bill of quantities, with the share of
    sampled boreholes at or under each figure."""
    labels = phrase_table("cost_range.rows")
    rows = [[labels["p50"], _usd(d.p50), _share(0.5)],
            [labels["p80"], _usd(d.p80), _share(0.8)],
            [labels["mean"], _usd(d.mean), _share(d.mean_share)]]
    if d.expected_per_working is not None:
        rows.append([labels["expected"], _usd(d.expected_per_working), ""])
    rows.append([labels["boq"], _usd(d.boq_usd), _share(d.boq_share)])
    rows.append([labels["budget"], _usd(d.budget_usd), _share(d.budget_share)])
    return rows


def programme_range_text(d: ProgrammeDistribution) -> list[str]:
    return [
        phrase("cost_range.programme_headline", wells=d.n_boreholes, p50=_usd(d.p50),
               p80=_usd(d.p80), n=f"{d.samples:,}", estimate=_usd(d.estimate_usd),
               estimate_share=_share(d.estimate_share), contingency=d.contingency_percent,
               budget=_usd(d.budget_usd), budget_share=_share(d.budget_share)),
        phrase("cost_range.programme_working", expected=_usd(d.per_working_expected),
               p80_each=_usd(d.per_working_p80), rate=d.success_rate_percent,
               a50=d.attempts_p50, a80=d.attempts_p80, planned=d.attempts_planned),
        phrase("cost_range.programme_basis"),
    ]


def programme_range_rows(d: ProgrammeDistribution) -> list[list[str]]:
    labels = phrase_table("cost_range.programme_rows")
    return [
        [labels["p50"], _usd(d.p50), _share(0.5)],
        [labels["p80"], _usd(d.p80), _share(0.8)],
        [labels["mean"], _usd(d.mean), _share(d.mean_share)],
        [labels["expected"], _usd(d.per_working_expected), ""],
        [labels["p80_each"], _usd(d.per_working_p80), ""],
        [labels["estimate"], _usd(d.estimate_usd), _share(d.estimate_share)],
        [labels["budget"], _usd(d.budget_usd), _share(d.budget_share)],
    ]

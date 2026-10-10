"""The cost as a distribution (PLAN.md step 3.4): the spread of the rate
catalogue and its written basis, the triangle and the dry-hole draws against
their analytic answers, cases that can be checked by hand, a calibration on
a case with a closed-form answer, and the sentences and the report."""

from __future__ import annotations

import csv
import io
import math
from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

import pytest
import yaml

from groundwater._resources import bundled_text
from groundwater.config import Config
from groundwater.costing import (
    CostingInputs,
    RateItem,
    estimate_borehole_cost,
    estimate_programme_cost,
    load_rates,
)
from groundwater.costing.distribution import (
    DepthSpread,
    _at_depth,
    _Rates,
    cost_range_rows,
    cost_range_text,
    depth_spread,
    failures_table,
    programme_range_rows,
    programme_range_text,
    sample_cost,
    sample_programme_cost,
    triangle_quantile,
)
from groundwater.text import phrase
from groundwater.ves.model_range import Stream, percentile

PCT = dict(overheads_percent=15.0, margin_percent=20.0, contingency_percent=10.0)


def flat(rates: list[RateItem]) -> list[RateItem]:
    """The catalogue with every triangle collapsed onto its likely rate."""
    return [replace(r, min_usd=r.unit_cost_usd, max_usd=r.unit_cost_usd) for r in rates]


def one_line(lo: float, likely: float, hi: float, *, stage="Casing",
             basis="lump_sum") -> list[RateItem]:
    return [RateItem("X1", stage, "consumables", "one item", "lump sum", basis, likely,
                     min_usd=lo, max_usd=hi)]


def bare(depth: float = 40.0) -> CostingInputs:
    """Inputs that put nothing on a lump sum but itself."""
    return CostingInputs(total_depth_m=depth, handpumps=0, wq_samples=0)


def triangle_cdf(lo: float, mode: float, hi: float, x: float) -> float:
    if x <= mode:
        return (x - lo) ** 2 / ((hi - lo) * (mode - lo))
    return 1.0 - (hi - x) ** 2 / ((hi - lo) * (hi - mode))


def triangle_inverse(lo: float, mode: float, hi: float, q: float) -> float:
    """The analytic quantile, written the other way round from the code's:
    solved from the distribution function by bisection."""
    a, b = lo, hi
    for _ in range(200):
        m = 0.5 * (a + b)
        if triangle_cdf(lo, mode, hi, m) < q:
            a = m
        else:
            b = m
    return 0.5 * (a + b)


# ------------------------------------------------------------- the catalogue

def test_every_rate_has_a_triangle_around_its_likely_value():
    rates = load_rates()
    assert len(rates) == 23
    for r in rates:
        lo, likely, hi = r.triangle()
        assert r.min_usd is not None and r.max_usd is not None, r.code
        assert lo <= likely <= hi, r.code
        assert hi > lo, f"{r.code} has no spread"


def test_the_spread_file_gives_every_rate_its_reason_and_the_csv_its_numbers():
    """borehole_cost_spread.yaml is the written basis; the CSV's minimum and
    maximum are its shares of the likely rate, to the cent, and its group
    column names the group that gives them."""
    spread = yaml.safe_load(bundled_text("borehole_cost_spread.yaml"))
    assert spread["status"] == "provisional"
    by_code = {}
    for group in spread["groups"]:
        assert len(" ".join(group["basis"].split())) > 60, group["key"]
        assert 0.0 <= group["below"] < 1.0 and group["above"] >= 0.0
        for code in group["codes"]:
            assert code not in by_code, f"{code} is in two groups"
            by_code[code] = group
    rows = list(csv.DictReader(io.StringIO(bundled_text("borehole_cost_items.csv"))))
    assert {r["code"] for r in rows} == set(by_code)
    cent = Decimal("0.01")
    for row in rows:
        group = by_code[row["code"]]
        likely = Decimal(row["unit_cost_usd"])
        assert Decimal(row["min_usd"]) == (likely * (1 - Decimal(str(group["below"])))).quantize(
            cent, ROUND_HALF_EVEN), row["code"]
        assert Decimal(row["max_usd"]) == (likely * (1 + Decimal(str(group["above"])))).quantize(
            cent, ROUND_HALF_EVEN), row["code"]
        assert row["spread_group"] == group["key"]


def test_the_spread_is_recorded_as_provisional_with_no_source():
    record = yaml.safe_load((Path(__file__).resolve().parents[1]
                             / "data_provenance.yaml").read_text(encoding="utf-8"))
    notes = {f["path"]: " ".join(f.get("note", "").split())
             for entry in record["datasets"] for f in entry.get("files", [])}
    note = notes["src/groundwater/data/borehole_cost_spread.yaml"]
    assert "NO SOURCE IS RECORDED" in note and "provisional" in note


def test_a_catalogue_without_the_spread_still_loads(tmp_path):
    """A rate catalogue of one's own written before step 3.4 has no minimum
    or maximum: each rate is its own triangle of no width."""
    path = tmp_path / "rates.csv"
    path.write_text("code,stage,category,item,unit,quantity_basis,unit_cost_usd,note\n"
                    "A1,Siting,equipment,Survey,lump sum,lump_sum,400.00,\n", encoding="utf-8")
    (rate,) = load_rates(path)
    assert rate.triangle() == (400.0, 400.0, 400.0)
    assert rate.spread_group == ""


def test_a_minimum_above_the_likely_rate_is_refused(tmp_path):
    path = tmp_path / "rates.csv"
    path.write_text("code,stage,category,item,unit,quantity_basis,unit_cost_usd,min_usd,"
                    "max_usd,note\nA1,Siting,equipment,Survey,lump sum,lump_sum,400,450,500,\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="A1"):
        load_rates(path)


def test_an_edited_rate_keeps_its_relative_spread():
    rate = next(r for r in load_rates() if r.code == "DRL2")  # 9.35 / 11 / 15.40
    edited = rate.with_likely(22.0)
    assert edited.triangle() == pytest.approx((18.7, 22.0, 30.8))
    assert rate.with_likely(11.0).triangle() == rate.triangle()
    zero = replace(rate, unit_cost_usd=0.0, min_usd=0.0, max_usd=0.0).with_likely(5.0)
    assert zero.triangle() == (5.0, 5.0, 5.0)


# ---------------------------------------------------------------- the draws

@pytest.mark.parametrize("lo,mode,hi", [(100.0, 150.0, 300.0), (2.25, 2.5, 4.0),
                                        (0.0, 0.0, 1.0), (5.0, 9.0, 9.0)])
def test_the_triangle_has_its_analytic_mean_and_percentiles(lo, mode, hi):
    rng = Stream(7, 0)
    n = 40000
    draws = sorted(triangle_quantile(lo, mode, hi, rng.uniform()) for _ in range(n))
    mean = sum(draws) / n
    sd = math.sqrt((lo * lo + mode * mode + hi * hi - lo * mode - lo * hi - mode * hi) / 18.0)
    assert mean == pytest.approx((lo + mode + hi) / 3.0, abs=4.0 * sd / math.sqrt(n))
    for q in (0.1, 0.5, 0.8, 0.9):
        assert percentile(draws, q) == pytest.approx(triangle_inverse(lo, mode, hi, q),
                                                     abs=0.01 * (hi - lo))
        # and the inverse is exact, not merely close
        x = triangle_inverse(lo, mode, hi, q)
        assert triangle_quantile(lo, mode, hi, triangle_cdf(lo, mode, hi, x)) == pytest.approx(
            x, rel=1e-9, abs=1e-12)


def test_a_triangle_of_no_width_is_its_likely_value_whatever_the_draw():
    assert {triangle_quantile(3.0, 3.0, 3.0, u) for u in (1e-9, 0.5, 1 - 1e-9)} == {3.0}


def test_rates_in_one_group_move_together_and_groups_apart():
    """Both fuel lines sit at one point of their own triangles in every
    draw, and the fuel and the casing do not."""
    rates = load_rates()
    at = {r.code: i for i, r in enumerate(rates)}
    draws = _Rates(rates)
    rng = Stream(11, 0)

    def point(code, value):
        lo, mode, hi = rates[at[code]].triangle()
        return triangle_cdf(lo, mode, hi, value)

    apart = 0
    for _ in range(200):
        drawn = draws.draw(rng)
        fuel = point("DRL1", drawn[at["DRL1"]])
        assert point("DRL2", drawn[at["DRL2"]]) == pytest.approx(fuel, abs=1e-9)
        apart += abs(point("CAS1", drawn[at["CAS1"]]) - fuel) > 1e-6
    assert apart > 190 and draws.groups == 13


def test_the_dry_attempts_follow_the_negative_binomial():
    """The table's running weights, normalised, are the distribution function
    of C(n+k-1, k) p^n (1-p)^k, and it keeps all but a negligible tail."""
    for n, p in ((1, 0.4), (3, 0.3), (10, 0.75), (40, 0.05)):
        first, running = failures_table(n, p)
        kept = 0.0
        for i, cum in enumerate(running):
            k = first + i
            kept += math.exp(math.lgamma(n + k) - math.lgamma(k + 1) - math.lgamma(n)
                             + n * math.log(p) + k * math.log1p(-p))
            assert cum / running[-1] == pytest.approx(kept, abs=1e-12)
        assert kept == pytest.approx(1.0, abs=1e-14)
    assert failures_table(5, 1.0) == (0, [1.0])


def test_a_programme_of_hundreds_at_long_odds_does_not_underflow():
    first, running = failures_table(500, 0.01)
    mean = 500 * 0.99 / 0.01
    assert first < mean < first + len(running)
    assert all(math.isfinite(v) and v > 0 for v in running)


# ------------------------------------------------------------- by hand

def test_a_flat_catalogue_gives_the_bill_of_quantities():
    """Every triangle collapsed onto its likely rate and no dry hole: every
    sampled borehole is the bill of quantities, so P50, P80 and the mean are
    its price, and the expected cost per working borehole is the mean."""
    inputs = CostingInputs(total_depth_m=48.0, mobilisation_distance_km=120.0)
    rates = flat(load_rates())
    boq = estimate_borehole_cost(inputs, rates, vat_percent=15.0, **PCT)
    d = sample_cost(inputs, rates, vat_percent=15.0, samples=300, **PCT)
    for figure in (d.p50, d.p80, d.mean, d.expected_per_working, d.curve[0], d.curve[-1]):
        assert figure == pytest.approx(boq.price_with_vat_usd, rel=1e-12)
    assert d.boq_usd == boq.price_with_vat_usd and d.budget_usd == boq.budget_usd
    assert d.boq_share == 1.0


def test_odds_of_one_make_the_cost_per_working_borehole_the_mean():
    inputs = CostingInputs(total_depth_m=40.0, mobilisation_distance_km=80.0)
    d = sample_cost(inputs, samples=2000, success_probability=1.0, odds_source="VES 1")
    assert d.expected_per_working == d.mean and d.dry_mean > 0
    assert d.p80 > d.p50


def test_a_flat_programme_at_certain_success_is_the_programme_estimate():
    per_well = CostingInputs(total_depth_m=45.0, mobilisation_distance_km=150.0)
    rates = flat(load_rates())
    estimate = estimate_programme_cost(per_well, 6, rates=rates, vat_percent=15.0, **PCT)
    d = sample_programme_cost(per_well, 6, rates=rates, vat_percent=15.0, samples=200, **PCT)
    assert d.p50 == pytest.approx(estimate.price_with_vat_usd, rel=1e-12)
    assert d.p80 == pytest.approx(estimate.price_with_vat_usd, rel=1e-12)
    assert d.per_working_expected == pytest.approx(estimate.price_per_successful_well_usd,
                                                   rel=1e-12)
    assert d.attempts_p50 == d.attempts_p80 == d.attempts_planned == 6


def test_a_dry_attempt_pays_for_siting_set_up_and_drilling_but_not_the_journey():
    """Flat rates and a chance of a quarter: every completed borehole costs
    the bill of quantities, every dry one the siting, mobilisation and
    drilling lines less the kilometres, and the expected cost per working
    borehole is the one plus three of the other."""
    inputs = CostingInputs(total_depth_m=40.0, mobilisation_distance_km=100.0)
    rates = flat(load_rates())
    boq = estimate_borehole_cost(inputs, rates, **PCT)
    dry_direct = sum(i.amount_usd for i in boq.items
                     if i.stage in ("Siting", "Mobilisation", "Drilling")
                     and i.code != "MOB1")
    dry = dry_direct * 1.15 * 1.2
    d = sample_cost(inputs, rates, success_probability=0.25, odds_source="P", samples=40,
                    **PCT)
    assert d.dry_mean == pytest.approx(dry, rel=1e-12)
    assert d.expected_per_working == pytest.approx(boq.price_with_vat_usd + 3 * dry, rel=1e-12)


def test_the_depth_moves_the_lengths_with_it():
    """A borehole drawn 10 m deeper than the design carries 10 m more casing
    and gravel; one left to the rules has them worked out again."""
    designed = CostingInputs(total_depth_m=40.0, casing_m=31.5, screen_m=9.0,
                             gravel_interval_m=28.0, overburden_m=18.0, cement_bags=6)
    base, _ = designed.resolved()
    deeper = _at_depth(designed, base, 50.0)
    assert (deeper.casing_m, deeper.gravel_interval_m, deeper.overburden_m) == (41.5, 38.0, 18.0)
    assert deeper.crew_days == math.ceil(50 / 25) + 4 and deeper.cement_bags == 6
    assert _at_depth(designed, base, 80.0).crew_days == math.ceil(80 / 25) + 4 != base.crew_days
    shallow = _at_depth(designed, base, 12.0)
    assert (shallow.overburden_m, shallow.bedrock_m) == (12.0, 0.0)
    unpacked = replace(designed, gravel_interval_m=0.0)
    assert _at_depth(unpacked, unpacked.resolved()[0], 60.0).gravel_interval_m == 0.0
    ruled = CostingInputs(total_depth_m=40.0)
    at60 = _at_depth(ruled, ruled.resolved()[0], 60.0)
    assert (at60.overburden_m, at60.casing_m, at60.gravel_interval_m) == (30.0, 51.5, 45.0)
    assert _at_depth(ruled, ruled.resolved()[0], 40.0) == ruled.resolved()[0]


def test_a_depth_is_drawn_between_the_quantiles_and_rounded_as_the_range_rounds_it():
    spread = DepthSpread("VES 1", [20.0 + k for k in range(21)], step_m=1.0, cap_m=38.0)
    assert spread.draw(1e-9) == 21.0  # rounded up to the step
    assert spread.draw(0.5) == 30.0
    assert spread.draw(1 - 1e-9) == 38.0  # cut back to the depth of investigation
    fixed = DepthSpread("VES 1", [33.0] * 21, step_m=1.0, cap_m=50.0)
    d = sample_cost(CostingInputs(total_depth_m=33.0), depth=fixed, samples=200)
    held = sample_cost(CostingInputs(total_depth_m=33.0), samples=200)
    assert (d.p50, d.p80, d.depth_p10_m, d.depth_p90_m) == (held.p50, held.p80, 33.0, 33.0)
    assert d.depth_source == "VES 1" and held.depth_source is None


def test_the_range_keeps_the_depth_its_drilling_depth_is_read_from():
    """The range's twenty steps of drilling depth are in order, inside the
    depth of investigation, and its P90 step rounds up to the drilling depth
    the range quotes."""
    from groundwater.ingestion.ves import read_ves_workbook
    from groundwater.ves.inversion import invert_sounding
    from groundwater.ves.model_range import sample_model_range

    rokel = Path(__file__).resolve().parents[1] / "examples" / "data" / "rokel" / "rokel_ves.xlsx"
    sounding = read_ves_workbook(rokel)[0]
    config = Config()
    for key, value in dict(samples=400, burn_in=200, starts=3, chains=2).items():
        setattr(config.ves_range, key, value)
    r = sample_model_range(sounding, invert_sounding(sounding), config)
    q = r.drilling_depth_quantiles_m
    assert len(q) == 21 and q == sorted(q) and q[-1] <= r.investigation_depth_m
    step = config.ves.round_drilling_depth_to_m
    assert min(math.ceil(q[18] / step) * step, r.investigation_depth_m) == r.drilling_depth_m
    spread = depth_spread(r, config)
    assert spread is not None and spread.cap_m == r.investigation_depth_m
    assert depth_spread(None) is None


# ------------------------------------------------------------ calibration

def test_the_sampled_percentiles_match_the_analytic_ones_on_one_triangle():
    """One lump sum drawn from a triangle and nothing else priced: the
    sampled P50 and P80 are the triangle's own, within the sampling error of
    the default sample count."""
    lo, mode, hi = 100.0, 150.0, 300.0
    d = sample_cost(bare(), one_line(lo, mode, hi), overheads_percent=0.0, margin_percent=0.0,
                    contingency_percent=0.0)
    assert d.samples == Config().cost_range.samples
    assert d.p50 == pytest.approx(triangle_inverse(lo, mode, hi, 0.5), rel=0.01)
    assert d.p80 == pytest.approx(triangle_inverse(lo, mode, hi, 0.8), rel=0.01)
    assert d.mean == pytest.approx((lo + mode + hi) / 3.0, rel=0.01)


def test_the_sampled_cost_per_working_borehole_matches_its_closed_form():
    """A completed line from one triangle and a dry-hole line from another,
    at a 40 percent chance: the expected cost per working borehole is
    E[completed] + E[dry] x (1 - p) / p, within the sampling error of the
    means alone."""
    rates = (one_line(100.0, 150.0, 300.0, stage="Casing")
             + [RateItem("D1", "Drilling", "fuel", "drilling", "m", "per_m_drilled", 10.0,
                         min_usd=8.0, max_usd=16.0)])
    p = 0.4
    d = sample_cost(bare(40.0), rates, success_probability=p, odds_source="P",
                    overheads_percent=0.0, margin_percent=0.0, contingency_percent=0.0)
    completed = (100 + 150 + 300) / 3.0 + 40.0 * (8 + 10 + 16) / 3.0
    dry = 40.0 * (8 + 10 + 16) / 3.0
    assert d.mean == pytest.approx(completed, rel=0.01)
    assert d.dry_mean == pytest.approx(dry, rel=0.005)
    assert d.expected_per_working == pytest.approx(completed + dry * (1 - p) / p, rel=0.005)


def test_the_cost_per_working_borehole_holds_still_at_long_odds():
    """At a 5 percent chance the figure is nineteen dry attempts for every
    working borehole, and still moves by well under 1 percent from one seed
    to the next: dividing what the sampled attempts spent by the ones that
    found water moved it by several percent and pulled it low."""
    inputs = CostingInputs(total_depth_m=40.0, mobilisation_distance_km=100.0)
    figures = [sample_cost(inputs, success_probability=0.05, odds_source="P", seed=s,
                           samples=5000).expected_per_working for s in range(1, 6)]
    assert (max(figures) - min(figures)) / min(figures) < 0.005
    d = sample_cost(inputs, success_probability=0.05, odds_source="P", samples=5000)
    assert d.expected_per_working == d.mean + d.dry_mean * (0.95 / 0.05)


def test_the_programme_percentiles_match_the_geometric_count_of_dry_holes():
    """One working borehole wanted at a 40 percent chance, flat rates: the
    dry attempts before it are geometric, with P(F <= k) = 1 - 0.6^(k+1),
    so the programme's P50 is the one with one dry attempt and its P80 the
    one with three, and its mean has 1.5."""
    per_well = CostingInputs(total_depth_m=40.0, mobilisation_distance_km=50.0)
    rates = flat(load_rates())
    d = sample_programme_cost(per_well, 1, rates=rates, success_rate_percent=40.0,
                              inter_site_distance_km=10.0, **PCT)

    def with_dry(k: float) -> float:
        base = estimate_programme_cost(per_well, 1, rates=rates, inter_site_distance_km=10.0,
                                       **PCT)
        km_rate = sum(r.unit_cost_usd for r in rates if r.quantity_basis == "per_km_round_trip")
        dry = sum(v for s, v in base.well_estimate.by_stage()
                  if s in ("Siting", "Mobilisation", "Drilling"))
        return base.price_with_vat_usd + (k * dry + k * 10.0 * km_rate) * 1.15 * 1.2

    assert d.p50 == pytest.approx(with_dry(1), rel=1e-9)
    assert d.p80 == pytest.approx(with_dry(3), rel=1e-9)
    assert d.mean == pytest.approx(with_dry(1.5), rel=0.03)
    assert (d.attempts_p50, d.attempts_p80, d.attempts_planned) == (2, 4, 3)


# ---------------------------------------------------------- reproducible

def test_one_seed_gives_one_distribution_and_another_a_different_draw():
    inputs = CostingInputs(total_depth_m=40.0)
    a = sample_cost(inputs, samples=500, seed=3)
    b = sample_cost(inputs, samples=500, seed=3)
    c = sample_cost(inputs, samples=500, seed=4)
    assert a == b and a.p50 != c.p50


def test_impossible_settings_are_refused():
    inputs = CostingInputs(total_depth_m=40.0)
    for p in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="chance of success"):
            sample_cost(inputs, success_probability=p)
    with pytest.raises(ValueError, match="at least one sample"):
        sample_cost(inputs, samples=0)


# ------------------------------------------------------------- the words

def test_the_sentences_say_which_figure_is_which_and_what_was_left_out():
    inputs = CostingInputs(total_depth_m=40.0, mobilisation_distance_km=100.0)
    held = cost_range_text(sample_cost(inputs, samples=300))
    assert held[0] == phrase("cost_range.which_is_which")
    assert "contract document" in held[0] and "planning figure" in held[0]
    assert any("no dry hole is drawn" in t for t in held)
    assert any("held at 40 m" in t for t in held)
    spread = DepthSpread("VES 2", [30.0 + k for k in range(21)], 1.0, 60.0)
    drawn = sample_cost(inputs, depth=spread, success_probability=0.6, odds_source="VES 2",
                        samples=300)
    text = " ".join(cost_range_text(drawn))
    assert "range of models at VES 2" in text and "about 60 percent" in text
    rows = cost_range_rows(drawn)
    assert [r[2] for r in rows[:2]] == ["50", "80"] and len(rows) == 6


def test_a_long_chance_still_gives_a_cost_per_working_borehole():
    """However few the samples and long the odds, the figure is the
    completed borehole plus the dry attempts expected before it, said with
    the mean dry attempt."""
    d = sample_cost(CostingInputs(total_depth_m=40.0), samples=5,
                    success_probability=1e-3, odds_source="VES 9")
    assert d.expected_per_working == pytest.approx(d.mean + 999 * d.dry_mean, rel=1e-12)
    text = " ".join(cost_range_text(d))
    assert f"US$ {d.dry_mean:,.0f}, for each of the dry attempts" in text
    assert len(cost_range_rows(d)) == 6


def test_the_programme_sentences():
    d = sample_programme_cost(CostingInputs(total_depth_m=40.0, mobilisation_distance_km=90.0),
                              8, success_rate_percent=70.0, samples=500)
    text = programme_range_text(d)
    assert text[0].startswith("The programme of 8 working boreholes costs US$")
    assert "At 70 percent success" in text[1]
    assert len(programme_range_rows(d)) == 7


def test_the_cost_report_prints_the_planning_figure(tmp_path):
    from docx import Document

    from groundwater.reporting.costing import CostReportInputs, build_cost_report

    inputs = CostingInputs(total_depth_m=40.0, mobilisation_distance_km=100.0)
    estimate = estimate_borehole_cost(inputs)
    programme = estimate_programme_cost(inputs, 5, success_rate_percent=70.0)
    out = build_cost_report(CostReportInputs(
        estimate=estimate, programme=programme, figures_dir=tmp_path,
        distribution=sample_cost(inputs, samples=500, success_probability=0.7,
                                 odds_source="VES 1"),
        programme_distribution=sample_programme_cost(inputs, 5, success_rate_percent=70.0,
                                                     samples=500),
    ), tmp_path / "cost.docx")
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "4.1 The cost as a distribution" in text
    assert "5.1 The cost as a distribution" in text
    assert phrase("cost_range.which_is_which") in text
    assert "allows for dry holes" in text
    assert (tmp_path / "cost_distribution.png").exists()
    assert (tmp_path / "programme_distribution.png").exists()

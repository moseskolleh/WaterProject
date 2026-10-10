"""One way of reporting uncertainty (PLAN.md step 3.6).

Every report prints its decision numbers - the drilling depth, the yield,
the pump setting, the odds and the cost - as a value, a band and a basis, in
the one line groundwater.decisions writes, or says why there is no band; and
the readiness gate holds a report back where one of them has none. The
browser builds the same lines from the same results (tests/webapp/parity.mjs,
"decisions"); here are the cases by hand, the gate, and the reports.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from docx import Document

from groundwater.config import Config
from groundwater.decisions import (
    REPORT_DECISIONS,
    DecisionNumber,
    cost_decision,
    decision_numbers,
    decision_text,
    depth_decision,
    odds_decision,
    preferred_index,
    pump_decision,
    yield_decision,
)
from groundwater.readiness import REPORTS, assess_readiness
from groundwater.text import phrase

QUANTILES = [24.0, 25.2, 26.1, 26.9, 27.6, 28.2, 28.9, 29.5, 30.0, 30.6, 31.2,
             31.9, 32.5, 33.2, 34.0, 34.9, 35.8, 36.9, 38.2, 40.1, 44.6]


def interp(sid="P1", depth=33.0, rank=1, open_ended=False):
    return SimpleNamespace(sounding_id=sid, max_drilling_depth_m=depth, rank=rank,
                           basement_not_resolved=open_ended, drilling_depth_capped=False)


def model_range(sid="P1", quantiles=QUANTILES, doi=41.0):
    return SimpleNamespace(sounding_id=sid, n_samples=4000, investigation_depth_m=doi,
                           drilling_depth_quantiles_m=list(quantiles))


def analysis(spread=True, p10=4.1, low=1.02, high=1.61, pump=(37.2, 40.1), safe=1.25):
    boot = SimpleNamespace(method="cooper_jacob", p10=p10, reason="" if p10 else "too_few")
    return SimpleNamespace(
        transmissivity_source="cooper_jacob",
        yield_recommendation=SimpleNamespace(safe_yield_m3_per_h=safe,
                                             pump_installation_depth_m=38.4),
        spread=SimpleNamespace(bootstrap=boot, safe_yield_low_m3_per_h=low,
                               safe_yield_high_m3_per_h=high,
                               pump_depth_low_m=pump[0] if pump else None,
                               pump_depth_high_m=pump[1] if pump else None)
        if spread else None)


def odds(sid="P1", status="provisional"):
    return SimpleNamespace(sounding_id=sid, probability=0.61, low=0.39, high=0.78,
                           effective_n=10.0, status=status)


# ------------------------------------------------------------ the one line

def test_the_line_has_a_value_a_band_a_basis_and_a_status():
    d = DecisionNumber("yield", "Safe yield", "1.25 m3/h", "a band", "", "a basis")
    assert decision_text(d) == "Safe yield: 1.25 m3/h (a band); basis: a basis; provisional."
    assert d.text == decision_text(d) and d.has_band


def test_a_number_with_no_band_says_why_and_never_invents_one():
    d = DecisionNumber("odds", "Chance", "60 percent", None, "nothing sampled", "a basis",
                       "calibrated")
    assert not d.has_band
    assert decision_text(d) == ("Chance: 60 percent (no band: nothing sampled); "
                                "basis: a basis; calibrated.")


# ------------------------------------------------------------- each number

def test_the_drilling_depth_is_banded_by_the_models_rounded_as_the_range_rounds():
    d = depth_decision(interp(), model_range(), Config())
    # P10 is the third quantile, 26.1, and P90 the nineteenth, 38.2, each
    # rounded up to the 5 m drilling step and held to the 41 m resolved
    assert d.band == "P10 to P90 of the models that fit, 30 to 40 m"
    assert d.value == "about 33 m" and "4000 models" in d.basis
    assert d.text.startswith("Drilling depth at P1: about 33 m (P10 to P90")


def test_the_depth_band_is_read_at_the_p10_and_the_p90_and_no_other_twentieth():
    # the twentieths beside the P10 (12 and 21 m) and the P90 (39 and 48 m)
    # round to other 5 m steps than the P10's 16 m and the P90's 44 m
    spread = [10.0, 12.0, 16.0, 21.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0, 30.0,
              31.0, 32.0, 33.0, 34.0, 36.0, 39.0, 44.0, 48.0, 52.0]
    d = depth_decision(interp(), model_range(quantiles=spread, doi=60.0), Config())
    assert d.band == "P10 to P90 of the models that fit, 20 to 45 m"
    config = Config()
    config.ves.round_drilling_depth_to_m = 1.0
    d = depth_decision(interp(), model_range(quantiles=spread, doi=40.0), config)
    assert d.band == "P10 to P90 of the models that fit, 16 to 40 m"


def test_a_drilling_depth_cut_back_everywhere_is_one_depth_not_a_range():
    d = depth_decision(interp(depth=40.0, open_ended=True),
                       model_range(quantiles=[40.0] * 21, doi=40.0), Config())
    assert d.band == "P10 and P90 of the models that fit, both 40 m"
    assert d.value == "at least 40 m"


def test_an_unsampled_drilling_depth_has_no_band():
    d = depth_decision(interp(), None, Config())
    assert d.band is None
    assert d.reason == "the range of models has not been sampled at P1"
    assert "(no band: the range of models has not been sampled at P1)" in d.text


def test_the_yield_carries_the_bootstrap_band_or_says_why_not():
    assert yield_decision(analysis()).band == (
        "P10 to P90 of the transmissivity, 1.02 to 1.61 m3/h")
    assert yield_decision(analysis(high=None)).band == (
        "P10 to P90 of the transmissivity, 1.02 m3/h or more")
    withheld = yield_decision(analysis(p10=None))
    assert withheld.band is None and "fewer than five readings" in withheld.reason
    assert yield_decision(analysis(low=None)).reason == phrase("decision.yield_no_low")
    assert yield_decision(analysis(spread=False)).reason == phrase("decision.yield_no_spread")
    assert yield_decision(analysis(safe=None)) is None


def test_the_reserve_in_the_basis_is_the_configured_one():
    config = Config()
    config.pumping.seasonal_allowance_m = 3.5
    assert "the 3.5 m dry-season reserve" in yield_decision(analysis(), config.pumping).basis


def test_the_pump_intake_keeps_the_recommendations_band_where_the_report_moves_it():
    plain = pump_decision(analysis())
    assert plain.value == "38.4 m"
    assert plain.band == "over a 1 to 4 m dry-season decline, 37.2 to 40.1 m"
    moved = pump_decision(analysis(), 44.0, "design")
    # an intake outside the band it is printed with: the band says whose it is
    assert moved.value == "44 m"
    assert moved.band == ("the recommendation's setting over a 1 to 4 m dry-season decline, "
                          "37.2 to 40.1 m")
    assert "38.4 m" in moved.basis and "by the design" in moved.basis
    assert pump_decision(analysis(), 38.4, "design").basis == plain.basis
    assert pump_decision(analysis(pump=None)).band is None


def test_the_odds_always_have_a_band_and_say_when_they_are_calibrated():
    d = odds_decision(odds())
    assert d.text == ("Chance of a working borehole at P1: 61 percent (P10 to P90 of the "
                      "prior carried through the survey's factors, 39 to 78 percent); "
                      "basis: the prior from success_prior.csv, held as firmly as 10 "
                      "boreholes, and the likelihood ratios from success_evidence.yaml; "
                      "provisional.")
    assert odds_decision(odds(status="calibrated")).status == "calibrated"


def test_the_cost_is_banded_by_its_own_sample_and_the_bill_alone_is_not():
    from groundwater.costing.distribution import sample_cost
    from groundwater.costing.model import CostingInputs, estimate_borehole_cost

    inputs = CostingInputs(total_depth_m=40.0)
    spread = sample_cost(inputs, samples=500)
    d = cost_decision(spread)
    assert d.has_band and "500 sampled boreholes" in d.band
    p10, p90 = spread.curve[10], spread.curve[90]
    assert f"US$ {p10:,.0f} to {p90:,.0f}" in d.band
    assert f"US$ {spread.p80:,.0f} at P80" in d.band
    assert d.value == f"US$ {spread.p50:,.0f} at P50"
    bill = cost_decision(None, estimate_borehole_cost(inputs))
    assert bill.band is None and bill.reason == "the cost distribution has not been sampled"
    assert cost_decision(None, None) is None
    assert "1 sampled borehole," in cost_decision(sample_cost(inputs, samples=1)).band


# ------------------------------------------------------------ which numbers

def test_a_report_prints_the_numbers_it_asks_a_decision_on():
    survey = {"interpretations": [interp("P1", rank=2), interp("P2", rank=1)],
              "model_ranges": [model_range("P1"), None], "odds": [odds("P1"), odds("P2")]}
    keys = [d.key for d in decision_numbers(survey, "geophysical")]
    assert keys == ["depth", "odds"]
    # the first-ranked point, wherever it is listed
    assert decision_numbers(survey, "geophysical")[0].name == "Drilling depth at P2"
    assert [d.key for d in decision_numbers({"pump_analysis": analysis()}, "pumping")] == [
        "yield", "pump"]
    assert decision_numbers({"pump_analysis": analysis()}, "quality") == []
    assert set(REPORT_DECISIONS) <= set(REPORTS)


def test_where_two_points_are_tied_the_numbers_at_both_are_printed_and_gated():
    survey = {"interpretations": [interp("P1", rank=2), interp("P2", rank=1)],
              "model_ranges": [None, model_range("P2")], "odds": [odds("P1"), odds("P2")],
              "points": [1, 0]}
    names = [d.name for d in decision_numbers(survey, "geophysical")]
    assert names == ["Drilling depth at P2", "Chance of a working borehole at P2",
                     "Drilling depth at P1", "Chance of a working borehole at P1"]
    # the second point's range is not sampled, and the report offers it
    req = _bands(survey, "geophysical")
    assert req.state == "unmet" and req.detail == (
        "Drilling depth at P1 has no band: the range of models has not been sampled at P1.")
    assert _bands(dict(survey, points=[1]), "geophysical").state == "met"


def test_the_points_recommended_are_the_first_ranked_and_a_tied_second():
    import numpy as np

    from groundwater.decisions import recommended_points
    from groundwater.models import LayeredModel, SiteMetadata, VESSounding
    from groundwater.siting import assess_siting, tied_leaders
    from groundwater.ves import interpret_model
    from groundwater.ves.forward import forward_schlumberger
    from groundwater.ves.interpret import rank_interpretations

    # two points 2.8 weighted points apart, as test_report_text's tie, and
    # two a clear margin apart
    ab2 = np.array([1, 1.5, 2, 3, 4, 5, 7, 10, 15, 20, 30, 40, 50, 60, 70, 80.0])

    def point(sid, thickness):
        truth = LayeredModel([800, 60, 4000], [4, thickness])
        s = VESSounding(SiteMetadata(community="Testville"), sid, ab2,
                        np.full(len(ab2), 1.0), forward_schlumberger(truth, ab2))
        return interpret_model(s, truth)

    tied = [point("VES 1", 18.0), point("VES 2", 20.0)]
    rank_interpretations(tied)
    assert tied_leaders(assess_siting(tied)) is not None
    assert recommended_points(tied) == [1, 0]
    apart = [point("VES 1", 4.0), point("VES 2", 20.0)]
    rank_interpretations(apart)
    assert tied_leaders(assess_siting(apart)) is None
    assert recommended_points(apart) == [1]
    assert recommended_points(apart[:1]) == [0] and recommended_points([]) == []


def test_the_preferred_point_is_the_first_ranked_then_the_first_listed():
    assert preferred_index([]) is None
    assert preferred_index([interp(rank=None), interp(rank=None)]) == 0
    assert preferred_index([interp(rank=3), interp(rank=1), interp(rank=1)]) == 1


# --------------------------------------------------------------- the gate

def _bands(state, report):
    (req,) = [r for r in assess_readiness(state, report).requirements
              if r.key == "decision_bands"]
    return req


@pytest.mark.parametrize("report", ["geophysical", "pumping", "completion", "handover",
                                    "costing"])
def test_the_reports_that_decide_carry_the_requirement(report):
    assert "decision_bands" in REPORTS[report]


@pytest.mark.parametrize("report", ["quality", "supervision", "placard", "asset",
                                    "procurement"])
def test_the_reports_that_decide_nothing_with_a_spread_do_not(report):
    assert "decision_bands" not in REPORTS[report]


def test_the_gate_passes_a_survey_whose_numbers_are_banded_and_holds_one_that_is_not():
    banded = {"interpretations": [interp()], "model_ranges": [model_range()],
              "odds": [odds()]}
    req = _bands(banded, "geophysical")
    assert req.state == "met"
    assert req.detail == ("Each decision number carries a band: Drilling depth at P1 and "
                          "Chance of a working borehole at P1.")
    held = _bands(dict(banded, model_ranges=[None]), "geophysical")
    assert held.state == "unmet"
    assert held.detail == ("Drilling depth at P1 has no band: the range of models has not "
                           "been sampled at P1.")


def test_the_gate_holds_a_test_with_no_band_and_passes_one_with_it():
    assert _bands({"pump_analysis": analysis()}, "pumping").state == "met"
    req = _bands({"pump_analysis": analysis(spread=False)}, "handover")
    assert req.state == "unmet" and req.detail.count("has no band") == 2


def test_the_gate_counts_nothing_that_was_never_worked_out():
    # a yield that is pending is the yield requirement's to report
    pending = analysis(spread=False, safe=None)
    pending.yield_recommendation.pump_installation_depth_m = None
    assert _bands({"pump_analysis": pending}, "pumping").state == "not_applicable"
    req = _bands({}, "geophysical")
    assert req.state == "not_applicable" and req.satisfied


def test_an_override_issues_a_report_with_no_band_but_never_certifies_it():
    readiness = assess_readiness(
        {"pump_analysis": analysis(spread=False)}, "pumping",
        {"decision_bands": {"reason": "interim", "by": "A. Analyst"}})
    (req,) = [r for r in readiness.requirements if r.key == "decision_bands"]
    assert req.state == "overridden" and not readiness.is_certifiable


def test_a_banded_established_test_still_certifies(established_analysis):
    req = _bands({"pump_analysis": established_analysis}, "pumping")
    assert req.state == "met", req.detail


# ------------------------------------------------------------- the reports

def _text(path) -> str:
    return "\n".join(p.text for p in Document(str(path)).paragraphs)


def test_the_pumping_report_prints_its_numbers_in_the_one_form(tmp_path,
                                                                established_analysis):
    from groundwater.reporting.pumping import PumpingReportInputs, build_pumping_report

    path = build_pumping_report(
        PumpingReportInputs(analysis=established_analysis, figures_dir=tmp_path),
        tmp_path / "pumping.docx")
    text = _text(path)
    assert phrase("decision.heading") in text
    for d in (yield_decision(established_analysis), pump_decision(established_analysis)):
        assert d.has_band and d.text in text
    # no second, unlabelled band beside them in the key findings
    assert "Recommended safe yield:" not in text


def test_the_cost_report_prints_the_cost_in_the_one_form_with_or_without_a_band(tmp_path):
    from groundwater.costing.distribution import sample_cost
    from groundwater.costing.model import CostingInputs, estimate_borehole_cost
    from groundwater.reporting.costing import CostReportInputs, build_cost_report

    inputs = CostingInputs(total_depth_m=45.0)
    estimate = estimate_borehole_cost(inputs)
    spread = sample_cost(inputs, samples=200)
    sampled = _text(build_cost_report(
        CostReportInputs(estimate=estimate, figures_dir=tmp_path, distribution=spread),
        tmp_path / "sampled.docx"))
    assert cost_decision(spread, estimate).text in sampled
    alone = _text(build_cost_report(CostReportInputs(estimate=estimate, figures_dir=tmp_path),
                                    tmp_path / "alone.docx"))
    assert cost_decision(None, estimate).text in alone
    assert "(no band: the cost distribution has not been sampled)" in alone


def test_the_worked_examples_print_their_numbers_in_the_one_form():
    from pathlib import Path

    projects = Path(__file__).resolve().parents[1] / "examples" / "projects"
    rokel = _text(projects / "rokel" / "reports" / "Rokel_Geophysical_Survey_Report.docx")
    assert ("Drilling depth at A (1): at least 40 m (P10 and P90 of the models that fit, "
            "both 40 m); basis:") in rokel
    assert "Chance of a working borehole at A (1): 96 percent (P10 to P90" in rokel
    for name in ("Dr_Timbo_Borehole_Completion_Report.docx", "Dr_Timbo_Handover_Report.docx"):
        timbo = _text(projects / "dr_timbo" / "reports" / name)
        assert ("Safe yield: 0.391 m3/h (P10 to P90 of the transmissivity, 0.354 to "
                "0.443 m3/h); basis:") in timbo
        assert ("Pump intake below the top of the casing: 54 m (the recommendation's "
                "setting over a 1 to 4 m dry-season decline, 51 to 52 m); basis: the yield "
                "recommendation's setting at the adopted transmissivity, 52 m,") in timbo


# -------------------------------------------------------------- the figures

def test_the_model_panel_shades_the_p10_to_p90_of_the_drilling_depth():
    import matplotlib.pyplot as plt
    import numpy as np

    from groundwater.models import LayeredModel, SiteMetadata, VESSounding
    from groundwater.ves.forward import forward_schlumberger
    from groundwater.ves.model_range import drilling_depth_band
    from groundwater.ves.plots import plot_sounding_curve

    ab2 = np.array([1, 2, 5, 10, 20, 40, 80, 120.0])
    model = LayeredModel([800, 60, 4000], [4, 30])
    sounding = VESSounding(SiteMetadata(community="Testville"), "P1", ab2,
                           np.full(len(ab2), 1.0), forward_schlumberger(model, ab2))

    def shaded(quantiles):
        r = SimpleNamespace(fan=[([800, 60, 4000], [4, 30])],
                            fan_curves=[forward_schlumberger(model, ab2)], ab2=ab2,
                            drilling_depth_quantiles_m=quantiles)
        fig = plot_sounding_curve(sounding, model, depth_max=41.0, model_range=r)
        panel = fig.axes[1]
        spans = [p.get_patch_transform().transform(p.get_path().vertices)[:, 1]
                 for p in panel.patches]
        flat = [ln.get_ydata()[0] for ln in panel.lines
                if len(set(ln.get_ydata())) == 1 and ln.get_linewidth() == 2.0]
        plt.close(fig)
        return [(float(min(v)), float(max(v))) for v in spans], flat

    # unrounded, at the third and nineteenth of the twenty-one quantiles
    assert drilling_depth_band(SimpleNamespace(drilling_depth_quantiles_m=QUANTILES)) == (
        26.1, 38.2)
    spans, _ = shaded(QUANTILES)
    assert spans == [pytest.approx((26.1, 38.2))]
    # every model cut back to the same depth: a line, not a band of no height
    spans, flat = shaded([40.0] * 21)
    assert spans == [] and flat == [40.0]


def test_the_cost_curve_shades_the_p10_to_p90_the_cost_line_quotes(monkeypatch, tmp_path):
    import matplotlib.pyplot as plt

    from groundwater.costing import plots

    kept = []
    monkeypatch.setattr(plots, "save_figure", lambda fig, path, style=None: kept.append(fig))
    curve = [1000.0 + 10.0 * k + 0.5 * k * k for k in range(101)]
    plots.plot_cost_distribution(curve, [("Bill of quantities", 1500.0)], tmp_path / "c.png")
    (fig,) = kept
    (span,) = fig.axes[0].patches
    xs = span.get_patch_transform().transform(span.get_path().vertices)[:, 0]
    plt.close(fig)
    assert (min(xs), max(xs)) == pytest.approx((curve[10], curve[90]))

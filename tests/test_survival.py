"""How long boreholes keep working (PLAN.md step 7.4): Kaplan-Meier curves of
the time from commissioning to the first failure across the asset registry,
by pump type, contractor and water chemistry.

The estimate is held to the 6-MP arm of the leukaemia remission data that
Kaplan-Meier, Greenwood and the log-rank test are usually shown on, the
censoring rules one by one, and the browser's engine to this one on seeded
registers in a Node vm. The day is an input, never the clock.
"""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
from dataclasses import replace
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest

from groundwater import survival as SV
from groundwater.config import Config, SurvivalConfig
from groundwater.models import SiteMetadata
from groundwater.registry import Asset, AssetEvent, mint_asset_id
from groundwater.text import phrase, phrase_table

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"
DAY = date(2024, 6, 1)

AGGRESSIVE = {"material": "stainless steel", "inspection_months": 6, "chemistry": "aggressive"}
PLAIN = {"material": "galvanised iron", "inspection_months": 12, "chemistry": "not_aggressive"}

#: The 6-MP arm of the remission data (Freireich et al. 1963, as Gehan 1965
#: and most survival texts give it): weeks in remission, 1 relapsed, 0
#: censored. And the placebo arm, every one relapsed.
SIX_MP = [(6, 1), (6, 1), (6, 1), (6, 0), (7, 1), (9, 0), (10, 1), (10, 0), (11, 0), (13, 1),
          (16, 1), (17, 0), (19, 0), (20, 0), (22, 1), (23, 1), (25, 0), (32, 0), (32, 0),
          (34, 0), (35, 0)]
PLACEBO = [(t, 1) for t in (1, 1, 2, 2, 3, 4, 4, 5, 5, 8, 8, 8, 8, 11, 11, 12, 12, 15, 17, 22,
                            23)]


def _times(pairs):
    return [{"days": d, "failed": bool(f)} for d, f in pairs]


def _id(easting: float, northing: float = 938150.0) -> str:
    return mint_asset_id(SiteMetadata(district="Western Area Rural", easting=easting,
                                      northing=northing, utm_zone=28))


def _asset(*events, easting=694000.0, **fields) -> Asset:
    return Asset(asset_id=_id(easting), community="Case", district="Western Area Rural",
                 easting=easting, northing=938150.0, utm_zone=28,
                 events=[AssetEvent(when, kind) for when, kind in events], **fields)


# ------------------------------------------------------------- the estimate

def test_the_estimate_is_kaplan_and_meiers_product():
    """At each time a relapse happens the share still in remission is
    multiplied by the share at risk that did not relapse; a censored time
    only leaves the risk set."""
    km = SV.kaplan_meier(_times(SIX_MP), 5, (0,))
    exact, expected = Fraction(1), {}
    for day, at_risk, failed in [(6, 21, 3), (7, 17, 1), (10, 15, 1), (13, 12, 1), (16, 11, 1),
                                 (22, 7, 1), (23, 6, 1)]:
        exact *= Fraction(at_risk - failed, at_risk)
        expected[day] = round(float(exact), 4)
    steps = {s["days"]: s for s in km["steps"]}
    for day, value in expected.items():
        assert steps[day]["survival"] == value
    # the textbook's figures, as every survival text prints them
    assert [steps[d]["survival"] for d in (6, 7, 10, 13, 16, 22, 23)] == [
        0.8571, 0.8067, 0.7529, 0.6902, 0.6275, 0.5378, 0.4482]
    assert steps[9] == {**steps[9], "at_risk": 16, "failed": 0, "censored": 1,
                        "survival": 0.8067}
    assert (km["n"], km["n_failed"], km["n_censored"], km["n_no_time"]) == (21, 9, 12, 0)


def test_the_standard_error_is_greenwoods():
    km = SV.kaplan_meier(_times(SIX_MP), 5, (0,))
    se = {s["days"]: s["se"] for s in km["steps"]}
    assert [se[d] for d in (6, 7, 10, 13, 16, 22, 23)] == [
        0.0764, 0.0869, 0.0963, 0.1068, 0.1141, 0.1282, 0.1346]
    # by hand at the first relapse: S^2 * d / (n (n - d))
    s = 18 / 21
    assert se[6] == round(s * math.sqrt(3 / (21 * 18)), 4)


def test_the_band_is_on_the_log_log_scale():
    """At six weeks: S = 18/21, Greenwood's sum 3/(21 x 18), and the band
    S^exp(+-1.96 sqrt(sum) / |ln S|), 0.620 to 0.952."""
    km = SV.kaplan_meier(_times(SIX_MP), 5, (0,))
    first = km["steps"][0]
    s, total = 18 / 21, 3 / (21 * 18)
    spread = 1.959963984540054 * math.sqrt(total) / abs(math.log(s))
    assert first["lower"] == round(s ** math.exp(spread), 4) == 0.6197
    assert first["upper"] == round(s ** math.exp(-spread), 4) == 0.9516
    for step in km["steps"]:
        assert step["lower"] <= step["survival"] <= step["upper"]


def test_the_median_and_its_band():
    """The median is the first time the estimate is at or below one half
    (23 weeks); its band runs from where the band's lower edge first is (13)
    to where its upper edge first is, which it never is here."""
    km = SV.kaplan_meier(_times(SIX_MP), 5, (0,))
    assert km["median"] == {"days": 23, "lower": 13, "upper": None}
    placebo = SV.kaplan_meier(_times(PLACEBO), 5, (0,))
    # every one relapsed: the estimate and its band close on nought
    assert placebo["steps"][-1]["survival"] == 0.0
    assert placebo["steps"][-1]["lower"] == placebo["steps"][-1]["upper"] == 0.0
    assert placebo["median"]["days"] == 8
    assert placebo["median"]["lower"] <= 8 <= placebo["median"]["upper"]


def test_no_band_before_the_first_failure():
    km = SV.kaplan_meier(_times([(5, 0), (9, 0), (12, 0), (14, 1), (20, 0), (25, 0), (30, 0)]),
                         5, (0,))
    assert [(s["survival"], s["lower"], s["upper"]) for s in km["steps"][:3]] == [
        (1.0, None, None)] * 3
    assert km["steps"][3]["lower"] is not None
    # the estimate never reaches one half, but the band's lower edge does
    assert km["median"] == {"days": None, "lower": 14, "upper": None}


def test_a_failure_on_the_day_of_commissioning_counts_and_a_censoring_does_not():
    km = SV.kaplan_meier(_times([(0, 1), (0, 0), (0, 0), (30, 0), (40, 1), (50, 0), (60, 0)]),
                         5, (0,))
    assert (km["n"], km["n_no_time"], km["n_failed"]) == (5, 2, 2)
    assert km["steps"][0] == {"days": 0, "at_risk": 5, "failed": 1, "censored": 0,
                              "survival": 0.8, "se": round(0.8 * math.sqrt(1 / 20), 4),
                              **{k: km["steps"][0][k] for k in ("lower", "upper")}}


def test_numbers_at_risk_at_the_stated_years():
    days = [(400, 1), (800, 0), (1000, 1), (1200, 0), (2000, 0), (2500, 1)]
    km = SV.kaplan_meier(_times(days), 5, (0, 1, 2, 3, 5, 10))
    at = {e["years"]: e for e in km["at_times"]}
    assert [at[y]["at_risk"] for y in (0, 1, 2, 3, 5, 10)] == [6, 6, 5, 3, 2, 0]
    assert at[0]["survival"] == 1.0 and at[0]["lower"] is None
    assert at[1]["survival"] == 1.0
    # one of six failed at day 400, before two years (730.5 days)
    assert at[2]["survival"] == round(5 / 6, 4) and at[2]["lower"] is not None
    # past the longest time followed there is no estimate
    assert at[10]["survival"] is None


def test_below_the_minimum_a_group_is_counts_only():
    km = SV.kaplan_meier(_times([(100, 1), (200, 0), (300, 1), (0, 0)]), 5, (0, 1))
    assert km["judged"] is False and km["n"] == 3 and km["n_no_time"] == 1
    assert km["steps"] == [] and km["median"] is None and km["at_times"] == []
    assert SV.kaplan_meier(_times([(100, 1), (200, 0), (300, 1)]), 3, (0,))["judged"]


# ----------------------------------------------------------- the comparison

def test_the_log_rank_test_on_the_remission_data():
    """6-MP against placebo: 9 relapses observed where 19.25 were expected,
    and a chi-squared of 16.79 on one degree of freedom, as the texts give."""
    out = SV.log_rank([_times(SIX_MP), _times(PLACEBO)])
    assert out["observed"] == [9, 21] and out["expected"] == [19.2505, 10.7495]
    assert out["chi2"] == 16.7929 and out["df"] == 1 and out["reason"] is None
    assert out["p"] == round(math.erfc(math.sqrt(16.7929 / 2)), 6)
    # the order of the groups does not change the test
    swapped = SV.log_rank([_times(PLACEBO), _times(SIX_MP)])
    assert swapped["chi2"] == out["chi2"] and swapped["p"] == out["p"]


def test_three_groups_take_two_degrees_of_freedom_and_any_order():
    a = _times([(5, 1), (8, 1), (12, 0), (20, 1), (25, 0), (30, 1)])
    b = _times([(3, 1), (4, 1), (6, 1), (9, 0), (10, 1), (15, 1)])
    c = _times([(10, 0), (18, 1), (22, 0), (35, 0), (40, 1), (41, 0)])
    out = SV.log_rank([a, b, c])
    assert out["df"] == 2 and out["chi2"] > 0
    for order in ([b, c, a], [c, a, b], [c, b, a]):
        again = SV.log_rank(order)
        assert abs(again["chi2"] - out["chi2"]) < 1e-3 and again["df"] == 2
    assert out["p"] == round(SV.chi2_survival(out["chi2"], 2), 6) or abs(
        out["p"] - SV.chi2_survival(out["chi2"], 2)) < 1e-5


def test_nothing_to_compare():
    out = SV.log_rank([_times([(5, 0), (6, 0)]), _times([(7, 0)])])
    assert out["reason"] == "no_failures" and out["df"] is None and out["chi2"] is None
    # every failure falls after the other group has left the risk set
    out = SV.log_rank([_times([(1, 0), (2, 0)]), _times([(10, 1), (12, 1)])])
    assert out["reason"] == "one_at_risk" and out["not_at_risk"] == [0]
    assert (out["df"], out["chi2"], out["p"]) == (None, None, None)
    # two groups alike: nothing between them
    out = SV.log_rank([_times([(5, 1), (9, 0)]), _times([(5, 1), (9, 0)])])
    assert (out["reason"], out["df"], out["chi2"], out["p"]) == (None, 1, 0.0, 1.0)
    # at risk together only where every borehole at risk failed: no spread
    out = SV.log_rank([_times([(5, 1)]), _times([(5, 1)])])
    assert out["reason"] == "singular" and out["not_at_risk"] == [] and out["chi2"] is None
    with pytest.raises(ValueError):
        SV.log_rank([_times([(5, 1)])])


def test_a_group_never_at_risk_at_a_failure_is_left_out_of_the_test():
    """A group whose boreholes had all left the risk set before the first
    failure (or, in a register, joined it after the last) adds nothing to
    the test, so the others are compared without it on one fewer degree of
    freedom, rather than no comparison at all; R's survdiff does the same."""
    early = _times([(0.5, 0)] * 5)
    pair = SV.log_rank([_times(SIX_MP), _times(PLACEBO)])
    for groups, left in [([_times(SIX_MP), _times(PLACEBO), early], [2]),
                         ([early, _times(SIX_MP), _times(PLACEBO)], [0])]:
        out = SV.log_rank(groups)
        assert out["not_at_risk"] == left and out["reason"] is None
        assert (out["df"], out["chi2"], out["p"]) == (1, pair["chi2"], pair["p"])
        assert out["observed"][left[0]] == 0 and out["expected"][left[0]] == 0.0


@pytest.mark.parametrize("bad", [
    {"days": -1, "failed": True}, {"days": float("nan"), "failed": False},
    {"days": True, "failed": False}, {"days": "5", "failed": False},
    {"days": 5, "failed": 1}, {"days": 5}, [5, True], None,
])
def test_times_that_are_not_times_are_refused(bad):
    with pytest.raises(ValueError, match="survival:"):
        SV.kaplan_meier([{"days": 5, "failed": True}, bad], 1, (0,))
    with pytest.raises(ValueError, match="survival:"):
        SV.log_rank([_times([(5, 1)]), [bad]])


@pytest.mark.parametrize("x", [0.01, 0.5, 1.0, 3.84, 6.63, 10.0, 25.0, 60.0])
def test_the_chi_squared_tail(x):
    assert abs(SV.chi2_survival(x, 1) - math.erfc(math.sqrt(x / 2))) < 1e-13
    assert abs(SV.chi2_survival(x, 2) - math.exp(-x / 2)) < 1e-13
    assert abs(SV.chi2_survival(x, 4) - math.exp(-x / 2) * (1 + x / 2)) < 1e-13
    with pytest.raises(ValueError):
        SV.chi2_survival(x, 1.5)


# ------------------------------------------------------- one borehole's time

@pytest.mark.parametrize(("events", "ends", "days", "failed"), [
    ([("2020-01-10", "commissioned")], "commissioning", 0, False),
    ([("2020-01-10", "commissioned"), ("2021-01-10", "routine_inspection")], "report", 366,
     False),
    ([("2020-01-10", "commissioned"), ("2020-07-10", "inspection"),
      ("2021-01-10", "water_sample"), ("2023-01-01", "note")], "report", 366, False),
    ([("2020-01-10", "commissioned"), ("2020-07-10", "failure"),
      ("2020-08-01", "repair"), ("2022-01-01", "failure")], "failure", 182, True),
    ([("2020-01-10", "commissioned"), ("2021-01-10", "repair")], "repair", 366, True),
    ([("2020-01-10", "commissioned"), ("2021-01-10", "restored")], "restored", 366, True),
    ([("2020-01-10", "commissioned"), ("2020-06-01", "routine_inspection"),
      ("2021-01-10", "decommissioned"), ("2022-01-01", "failure")], "decommissioned", 366,
     False),
    # one day, several records: a failure counts before a decommissioning
    ([("2020-01-10", "commissioned"), ("2021-01-10", "decommissioned"),
      ("2021-01-10", "failure")], "failure", 366, True),
    ([("2020-01-10", "commissioned"), ("2020-01-10", "failure")], "failure", 0, True),
    # the first commissioning is time zero; a later one is a report
    ([("2020-01-10", "commissioned"), ("2021-01-10", "commissioned")], "report", 366, False),
    ([("2021-01-10", "routine_inspection")], "no_commissioning", None, False),
    # dated after the day of the analysis: not read
    ([("2020-01-10", "commissioned"), ("2024-07-01", "failure")], "commissioning", 0, False),
    ([("2024-07-01", "commissioned")], "no_commissioning", None, False),
])
def test_one_boreholes_time(events, ends, days, failed):
    out = SV.borehole_times(_asset(*events), DAY)
    assert (out["ends"], out["days"], out["failed"]) == (ends, days, failed)


def test_records_before_commissioning_and_undated_ones_are_counted_not_read():
    out = SV.borehole_times(_asset(("2019-05-01", "failure"), ("2020-01-10", "commissioned"),
                                   ("not a date", "failure"), ("2021-01-10", "inspection")),
                            "2024-06-01")
    assert (out["ends"], out["days"], out["before_start"], out["undated"]) == ("report", 366, 1, 1)
    assert out["start"] == "2020-01-10" and out["end"] == "2021-01-10"


def test_the_day_is_an_input():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        SV.borehole_times(_asset(("2020-01-10", "commissioned")), "1 June 2024")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        SV.survival_analysis([], "20240601")
    # a moment is read as its day, not compared with days and refused
    from datetime import datetime

    register = _register(6, 7)
    assert (SV.survival_analysis(register, datetime(2024, 6, 1, 15, 30))
            == SV.survival_analysis(register, "2024-06-01"))


# ------------------------------------------------------------- the groups

def test_the_groups_a_record_falls_in():
    asset = _asset(pump_type=" India Mark II ", installed_by="", rising_main=AGGRESSIVE)
    assert SV.group_value(asset, "pump_type") == ("india mark ii", "India Mark II", True)
    assert SV.group_value(asset, "contractor") == ("", phrase("survival.not_recorded"), False)
    assert SV.group_value(asset, "chemistry") == (
        "aggressive", phrase_table("survival.chemistry")["aggressive"], True)
    for rising, key in [(PLAIN, "not_aggressive"), (None, "unknown"),
                        ({**AGGRESSIVE, "chemistry": "incomplete"}, "unknown"),
                        ({**AGGRESSIVE, "chemistry": "none"}, "unknown"),
                        ({"chemistry": "aggressive"}, "unknown")]:
        assert SV.group_value(replace(asset, rising_main=rising), "chemistry")[0] == key
    with pytest.raises(ValueError):
        SV.group_value(asset, "district")


def _register(n_a: int, n_b: int, n_c: int = 0) -> list[Asset]:
    """Boreholes of two pump types (and a third), commissioned on one day,
    the first type failing early and the second late."""
    out = []
    for i in range(n_a + n_b + n_c):
        kind = "Afridev" if i < n_a else ("India Mark II" if i < n_a + n_b else "Kardia")
        fail = 200 + 40 * i if i < n_a else 1500 + 50 * i
        events = [("2018-01-10", "commissioned")]
        when = date.fromordinal(date(2018, 1, 10).toordinal() + fail)
        events.append((when.isoformat(), "failure" if i % 3 else "routine_inspection"))
        out.append(_asset(*events, easting=690000.0 + 1000 * i,
                          pump_type=kind if i != 1 else kind.upper(),
                          installed_by="Contractor A" if i % 2 else "",
                          rising_main=AGGRESSIVE if i % 2 else PLAIN))
    return out


def test_the_register_by_pump_type():
    result = SV.survival_analysis(_register(6, 7, 2), DAY)
    pump = next(g for g in result["groupings"] if g["by"] == "pump_type")
    labels = [g["label"] for g in pump["groups"]]
    # the most boreholes first, matched in either case, labelled as first spelt
    assert labels == ["India Mark II", "Afridev", "Kardia"]
    kardia = pump["groups"][2]
    assert kardia["judged"] is False and kardia["steps"] == []
    comparison = pump["comparison"]
    assert comparison["groups"] == ["India Mark II", "Afridev"]
    assert comparison["left_out"] == ["Kardia"] and comparison["df"] == 1
    assert comparison["p"] < 0.05
    text = SV.survival_text(result)
    words = next(g for g in text["groupings"] if g["by"] == "pump_type")
    assert words["heading"] == phrase("survival.by_heading", by="pump type")
    assert words["lines"][2].startswith("Kardia: too few boreholes to judge")
    assert phrase("survival.p_meaning") in words["comparison"]
    assert phrase("survival.left_out", groups="Kardia") in words["comparison"]


def test_a_new_pump_type_is_shown_and_left_out_of_the_test_not_the_others():
    """Five boreholes of a pump type commissioned this year, followed for
    weeks, were never at risk when any of the older ones failed: they are
    a group judged and drawn, but the test compares the other two without
    them, and says so."""
    new = [_asset(("2024-01-10", "commissioned"), ("2024-03-01", "routine_inspection"),
                  easting=720000.0 + 1000 * i, pump_type="Kardia") for i in range(5)]
    result = SV.survival_analysis(_register(6, 7) + new, DAY)
    pump = next(g for g in result["groupings"] if g["by"] == "pump_type")
    kardia = next(g for g in pump["groups"] if g["label"] == "Kardia")
    assert kardia["judged"] and kardia["n_failed"] == 0
    comparison = pump["comparison"]
    assert comparison["groups"] == ["India Mark II", "Afridev", "Kardia"]
    assert comparison["not_at_risk"] == ["Kardia"] and comparison["df"] == 1
    alone = next(g for g in SV.survival_analysis(_register(6, 7), DAY)["groupings"]
                 if g["by"] == "pump_type")["comparison"]
    assert (comparison["chi2"], comparison["p"]) == (alone["chi2"], alone["p"])
    words = next(g for g in SV.survival_text(result)["groupings"] if g["by"] == "pump_type")
    assert comparison["p"] < 0.001 and words["comparison"][0] == phrase(
        "survival.compared_small", groups="India Mark II and Afridev", chi2=comparison["chi2"],
        df=1)
    assert phrase("survival.not_at_risk", groups="Kardia") in words["comparison"]


def test_a_group_naming_nothing_is_shown_but_not_compared():
    result = SV.survival_analysis(_register(6, 7), DAY)
    contractor = next(g for g in result["groupings"] if g["by"] == "contractor")
    assert [g["label"] for g in contractor["groups"]] == [
        "Contractor A", phrase("survival.not_recorded")]
    assert contractor["groups"][1]["recorded"] is False and contractor["groups"][1]["judged"]
    assert contractor["comparison"]["reason"] == "fewer_than_two"
    chemistry = next(g for g in result["groupings"] if g["by"] == "chemistry")
    assert {g["key"] for g in chemistry["groups"]} == {"aggressive", "not_aggressive"}
    assert chemistry["comparison"]["reason"] is None


def test_the_counts_add_up_and_are_said():
    register = _register(6, 7) + [
        _asset(("2020-01-10", "commissioned"), easting=712000.0),
        _asset(("2020-01-10", "commissioned"), ("2021-01-10", "repair"), easting=713000.0),
        _asset(("2021-01-10", "routine_inspection"), easting=714000.0),
        _asset(("2019-01-10", "note"), ("2020-01-10", "commissioned"), ("x", "failure"),
               ("2020-02-01", "inspection"), easting=715000.0),
    ]
    result = SV.survival_analysis(register + [register[0].as_dict(), {"asset_id": "no"}], DAY)
    overall = result["overall"]
    assert result["n_boreholes"] == 17 and result["n_merged"] == 1 and result["n_unreadable"] == 1
    assert overall["n_boreholes"] == overall["n"] + overall["n_no_time"] + overall["n_no_start"]
    assert (overall["n_no_time"], overall["n_no_start"]) == (1, 1)
    assert (result["n_by_mending"], result["n_before_start"], result["n_undated"]) == (1, 1, 1)
    summary = SV.survival_text(result)["summary"]
    assert summary[0] == phrase("survival.headline", date="2024-06-01", total=17,
                                followed=overall["n"], failed=overall["n_failed"],
                                censored=overall["n_censored"])
    for key in ("no_time", "no_start", "by_mending", "before_start", "undated"):
        assert phrase(f"survival.{key}", count=1) in summary
    assert phrase("rounds.merged", count=1) in summary
    assert phrase("rounds.unreadable", count=1) in summary


def test_an_empty_register_and_one_nobody_can_follow():
    assert SV.survival_text(SV.survival_analysis([], DAY))["summary"] == [phrase("survival.empty")]
    result = SV.survival_analysis([_asset(("2021-01-10", "inspection"))], DAY)
    assert SV.survival_text(result)["summary"][0] == phrase(
        "survival.none_followed", date="2024-06-01", total=1)


def test_the_settings_are_the_configuration_and_are_refused_when_unusable():
    assert (SurvivalConfig().min_at_risk, SurvivalConfig().at_risk_years) == (5, (0, 1, 2, 3, 5, 10))
    result = SV.survival_analysis(_register(3, 3), DAY,
                                  replace(Config(), survival=SurvivalConfig(min_at_risk=3,
                                                                            at_risk_years=(0, 2))))
    assert result["min_at_risk"] == 3 and result["at_risk_years"] == [0.0, 2.0]
    assert all(g["judged"] for g in result["groupings"][0]["groups"])
    for bad in BAD_SETTINGS + [{"at_risk_years": (0, float("nan"))}]:
        config = replace(Config(), survival=replace(SurvivalConfig(), **bad))
        with pytest.raises(ValueError, match="survival:"):
            SV.survival_analysis([], DAY, config)


#: Settings both engines refuse, as JSON carries them to the browser.
BAD_SETTINGS = [{"min_at_risk": 0}, {"min_at_risk": 2.5}, {"min_at_risk": True},
                {"min_at_risk": "5"}, {"at_risk_years": [0, 2, 1]},
                {"at_risk_years": [-1, 1]}, {"at_risk_years": [0, "1"]},
                {"at_risk_years": [0, 1, 1]}, {"at_risk_years": 5},
                {"at_risk_years": "0,1"}, {"at_risk_years": {"a": 1}}]
#: Times both engines refuse.
BAD_TIMES = [{"days": -1, "failed": True}, {"days": True, "failed": False},
             {"days": "5", "failed": False}, {"days": 5, "failed": 1}, {"days": 5},
             [5, True], None]


def test_the_browser_refuses_what_python_refuses(tmp_path):
    """Settings a configuration cannot mean, and times that are not times,
    are refused by both engines rather than read as something else."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path / "refuse.mjs"
    driver.write_text(r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js', 'support.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const { settings, times } = JSON.parse(readFileSync(0, 'utf8'));
const threw = (f) => { try { f(); return null; } catch (e) { return String(e.message); } };
const base = C.withConfig(null);
process.stdout.write(JSON.stringify({
  settings: settings.map((s) => threw(() => C.survivalAnalysis([], '2024-06-01',
    Object.assign({}, base, { survival: Object.assign({}, base.survival, s) })))),
  times: times.map((t) => [threw(() => C.kaplanMeier([{ days: 5, failed: true }, t], 1, [0])),
    threw(() => C.logRank([[{ days: 5, failed: true }], [t]]))]),
}));
""", encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS)],
                          input=json.dumps({"settings": BAD_SETTINGS, "times": BAD_TIMES}),
                          capture_output=True, text=True, encoding="utf-8", check=True)
    told = json.loads(done.stdout)
    for bad, message in zip(BAD_SETTINGS, told["settings"], strict=True):
        assert message and message.startswith("survival:"), bad
        config = replace(Config(), survival=replace(SurvivalConfig(), **bad))
        with pytest.raises(ValueError, match="survival:"):
            SV.survival_analysis([], DAY, config)
    for bad, messages in zip(BAD_TIMES, told["times"], strict=True):
        assert all(m and m.startswith("survival:") for m in messages), bad


def test_the_tables():
    result = SV.survival_analysis(_register(6, 7, 2), DAY)
    pump = next(g for g in result["groupings"] if g["by"] == "pump_type")
    header = SV.survival_header()
    rows = SV.survival_rows(pump["groups"])
    assert len(header) == 7 and all(len(row) == 7 for row in rows)
    assert rows[2][5] == phrase("survival.too_few_cell") and rows[2][6] == ""
    risk = SV.at_risk_rows(pump["groups"])
    assert [row[0] for row in risk] == ["India Mark II", "Afridev"]
    assert SV.at_risk_header(result) == [phrase("survival.at_risk_group")] + [
        phrase("survival.at_risk_year", years=y) for y in (0, 1, 2, 3, 5, 10)]
    assert risk[0][1] == phrase("survival.at_risk_whole", n=7, pct=100.0)


def test_the_method_cites_its_works():
    text = SV.survival_text(SV.survival_analysis(_register(6, 7), DAY))
    citations = phrase_table("references.citations")
    assert text["references"] == [citations[k] for k in (
        "kaplan_meier", "greenwood", "kalbfleisch_prentice", "brookmeyer_crowley", "mantel")]
    assert "Kaplan and Meier 1958" in text["method"][0]
    assert phrase("survival.minimum", minimum=5) == text["method"][1]


def test_the_figure_draws(tmp_path):
    from groundwater.survival_plots import plot_survival

    result = SV.survival_analysis(_register(6, 7, 2), DAY)
    pump = next(g for g in result["groupings"] if g["by"] == "pump_type")
    path = plot_survival(pump["groups"], tmp_path / "pump.png", by="pump_type")
    assert path.stat().st_size > 1000
    again = plot_survival(pump["groups"], tmp_path / "again.png", by="pump_type")
    assert again.read_bytes() == path.read_bytes()
    # nothing judged draws axes and no curve
    plot_survival([], tmp_path / "none.png")


# ------------------------------------------- the browser's engine, held to it

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js', 'support.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const cases = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map((r) => {
  try {
    const cfg = C.withConfig({ survival: r.settings || {} });
    const result = C.survivalAnalysis(r.assets, r.as_of, cfg);
    const groups = [result.overall].concat(result.groupings.flatMap((g) => g.groups));
    return { ok: {
      result, words: C.survivalText(result), header: C.survivalHeader(),
      rows: [C.survivalRows([result.overall])].concat(result.groupings.map((g) => C.survivalRows(g.groups))),
      at_risk: [C.atRiskHeader(result), C.atRiskRows(groups)],
    } };
  } catch (e) {
    return { threw: String(e && e.message || e) };
  }
})));
"""

_DAYS = ["2015-03-01", "2016-06-15", "2017-01-10", "2018-02-28", "2018-11-30", "2019-07-04",
         "2020-01-10", "2020-12-31", "2021-05-20", "2022-08-01", "2023-03-15", "2023-11-20",
         "2024-05-31", "2024-06-01", "2024-09-01", "not written down"]
_KINDS = ["commissioned", "commissioned", "inspection", "routine_inspection", "water_sample",
          "repair", "failure", "failure", "restored", "decommissioned", "note", "something"]
_PUMPS = ["India Mark II", "india mark ii", "Afridev", "AFRIDEV ", "Kardia", "", None, 7,
          "Solar \U0001f600"]
_CONTRACTORS = ["Contractor A", "Contractor B", " contractor a", "", None]
_RISING = [AGGRESSIVE, PLAIN, {**PLAIN, "chemistry": "none"}, {"inspection_months": 9}, None,
           {"material": "x"}]


def _case(seed: int) -> dict:
    """A register, a day and settings from one seed."""
    rng = random.Random(f"survival {seed}")
    ids: list[str] = []
    assets = []
    for _ in range(rng.randint(0, 40)):
        if ids and rng.random() < 0.1:
            asset_id = rng.choice(ids)
        else:
            asset_id = _id(690000.0 + rng.randint(0, 2000) * 10.0, 930000.0 + rng.randint(0, 900) * 10.0)
            ids.append(asset_id)
        record: dict = {"asset_id": asset_id, "community": "Case",
                        "district": "Western Area Rural", "easting": 694000.0,
                        "northing": 938150.0, "utm_zone": 28,
                        "pump_type": rng.choice(_PUMPS), "installed_by": rng.choice(_CONTRACTORS)}
        rising = rng.choice(_RISING)
        if rising is not None:
            record["rising_main"] = rising
        start = rng.choice(_DAYS[:10])
        events = [{"when": start, "kind": "commissioned"}] if rng.random() < 0.9 else []
        events += [{"when": rng.choice(_DAYS), "kind": rng.choice(_KINDS),
                    "note": rng.choice(["", "seals"])}
                   for _ in range(rng.choice([0, 1, 2, 3, 5]))]
        record["events"] = events
        if rng.random() < 0.03:
            record = {"asset_id": rng.choice(["", None, "SL-WAR-XXXXXXX-9"])}
        assets.append(record)
    settings = rng.choice([{}, {}, {}, {"min_at_risk": 3}, {"min_at_risk": 1},
                           {"at_risk_years": [0, 0.5, 2.5, 7]}])
    return {"assets": assets, "as_of": rng.choice(["2024-06-01", "2022-02-28", "2019-12-31"]),
            "settings": settings}


def _python(case: dict) -> dict:
    section = {**SurvivalConfig().__dict__, **case["settings"]}
    config = replace(Config(), survival=SurvivalConfig(**section))
    result = SV.survival_analysis(case["assets"], case["as_of"], config)
    groups = [result["overall"]] + [g for grouping in result["groupings"] for g in grouping["groups"]]
    return json.loads(json.dumps({
        "result": result, "words": SV.survival_text(result), "header": SV.survival_header(),
        "rows": [SV.survival_rows([result["overall"]])]
        + [SV.survival_rows(g["groups"]) for g in result["groupings"]],
        "at_risk": [SV.at_risk_header(result), SV.at_risk_rows(groups)],
    }))


SEEDS = range(80)


@pytest.fixture(scope="module")
def browser_answers(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path_factory.mktemp("survival") / "survival.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS)],
                          input=json.dumps([_case(seed) for seed in SEEDS]),
                          capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_browser_gives_the_same_curves(browser_answers, seed):
    answer = browser_answers[seed]
    assert "threw" not in answer, answer.get("threw")
    assert answer["ok"] == _python(_case(seed))


def test_the_seeded_registers_reach_every_rule():
    told = [_python(_case(seed)) for seed in SEEDS]
    rows = [b for t in told for b in t["result"]["boreholes"]]
    assert {b["ends"] for b in rows} == set(SV.ENDS)
    groups = [g for t in told for grouping in t["result"]["groupings"] for g in grouping["groups"]]
    assert any(g["judged"] for g in groups) and any(not g["judged"] for g in groups)
    reasons = {grouping["comparison"]["reason"] for t in told
               for grouping in t["result"]["groupings"]}
    assert {None, "fewer_than_two"} <= reasons
    assert any(g["median"] and g["median"]["days"] is not None for g in groups)
    assert any(g["median"] and g["median"]["upper"] is None and g["median"]["days"] is not None
               for g in groups)
    assert any(t["result"]["n_merged"] for t in told) and any(t["result"]["n_unreadable"] for t in told)

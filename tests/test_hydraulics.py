import numpy as np
import pytest
from groundwater.config import PumpingConfig
from groundwater.hydraulics.analysis import recommend_yield
from scipy.special import exp1

from groundwater.hydraulics import (
    analyse_pumping_test,
    cooper_jacob,
    hantush_bierschenk,
    theis_fit,
    theis_recovery,
)
from groundwater.ingestion import read_pumping_workbook

T_TRUE, S_TRUE, Q, R = 120.0, 2e-4, 5.0, 0.1
T_MIN = np.array([1, 2, 3, 4, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240], float)


def synthetic_drawdown():
    u = R**2 * S_TRUE / (4 * T_TRUE * (T_MIN / 1440.0))
    return (Q * 24) / (4 * np.pi * T_TRUE) * exp1(u)


def test_cooper_jacob_recovers_transmissivity():
    result = cooper_jacob(T_MIN, synthetic_drawdown(), Q)
    assert abs(result.transmissivity_m2_per_day - T_TRUE) / T_TRUE < 0.02
    assert result.r_squared > 0.999
    assert "valid" in result.u_check


def test_theis_recovers_parameters():
    result = theis_fit(T_MIN, synthetic_drawdown(), Q, radius_m=R)
    assert abs(result.transmissivity_m2_per_day - T_TRUE) / T_TRUE < 0.02
    assert abs(np.log10(result.storativity) - np.log10(S_TRUE)) < 0.2
    assert not result.storativity_reliable  # single well


def test_recovery_method():
    tp = 240.0
    t_rec = np.array([1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120], float)
    s_rec = 2.303 * (Q * 24) / (4 * np.pi * T_TRUE) * np.log10((tp + t_rec) / t_rec)
    result = theis_recovery(t_rec, s_rec, tp, Q)
    assert abs(result.transmissivity_m2_per_day - T_TRUE) / T_TRUE < 0.02


def test_hantush_bierschenk_exact():
    B, C = 0.002, 1e-6
    q_day = np.array([48.0, 96.0, 144.0, 192.0])
    s_end = B * q_day + C * q_day**2
    result = hantush_bierschenk(list(q_day / 24.0), list(s_end))
    assert abs(result.aquifer_loss_B - B) / B < 1e-6
    assert abs(result.well_loss_C - C) / C < 1e-6
    assert result.steps[0]["efficiency_percent"] > result.steps[-1]["efficiency_percent"]


def test_full_analysis_with_discharge(sample_data):
    test = read_pumping_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    analysis = analyse_pumping_test(test)
    assert analysis.transmissivity_m2_per_day is not None
    yr = analysis.yield_recommendation
    assert yr.safe_yield_m3_per_h is not None
    assert yr.safety_factor == 1.5
    assert "safety factor" in yr.basis
    assert yr.pump_installation_depth_m is not None
    assert yr.pump_installation_depth_m <= test.borehole_depth_m - 3


def test_safe_yield_carries_an_uncertainty_band(sample_data):
    """The safe yield is not measured: it rests on an assumed storativity, an
    assumed effective radius and a regional dry-season allowance. Printing one
    number to two significant figures reads as a measurement, so the
    recommendation now carries the range those assumptions span."""
    test = read_pumping_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    yr = analyse_pumping_test(test).yield_recommendation

    low, high = yr.safe_yield_low_m3_per_h, yr.safe_yield_high_m3_per_h
    assert low is not None and high is not None
    assert low <= yr.safe_yield_m3_per_h <= high
    assert low < high, "an envelope of assumptions must produce a range"
    assert "storativity" in yr.envelope_basis
    # the text the reports and the app print
    assert "to" in yr.yield_range_text and "m3/h" in yr.yield_range_text


def test_pending_yield_has_no_band(sample_data):
    """Nothing to bracket when the yield could not be computed at all."""
    test = read_pumping_workbook(sample_data / "kuntolo" / "kuntolo_step_test.xlsx")
    yr = analyse_pumping_test(test).yield_recommendation
    assert yr.safe_yield_m3_per_h is None
    assert yr.safe_yield_low_m3_per_h is None
    assert yr.yield_range_text == "pending"


def test_pending_without_discharge(sample_data):
    test = read_pumping_workbook(sample_data / "kuntolo" / "kuntolo_step_test.xlsx")
    analysis = analyse_pumping_test(test)
    assert analysis.transmissivity_m2_per_day is None
    yr = analysis.yield_recommendation
    assert yr.safe_yield_m3_per_h is None
    assert yr.pending_reason
    # available drawdown still computed from SWL and pump setting
    assert yr.available_drawdown_m is not None and yr.available_drawdown_m > 30


def test_seasonal_decline_reduces_safe_yield(sample_data):

    from groundwater.config import PumpingConfig

    test = read_pumping_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    base = analyse_pumping_test(test, config=PumpingConfig(seasonal_allowance_m=0.0))
    dry = analyse_pumping_test(test, config=PumpingConfig(seasonal_allowance_m=8.0))
    yb = base.yield_recommendation.safe_yield_m3_per_h
    yd = dry.yield_recommendation.safe_yield_m3_per_h
    # a larger dry-season decline reserves more drawdown, so the sustainable
    # yield must fall, and the basis must disclose the reserve
    assert yb is not None and yd is not None and yd < yb
    assert "dry-season" in dry.yield_recommendation.basis


def test_step_analysis_after_supplying_discharge(sample_data):
    test = read_pumping_workbook(sample_data / "kuntolo" / "kuntolo_step_test.xlsx")
    for step, q in zip(test.steps, (1.5, 2.2, 3.0), strict=True):
        step.discharge_m3_per_h = q
    analysis = analyse_pumping_test(test)
    assert analysis.step_test is not None
    # step 1 ends above the stated static level (the sheet's datum anomaly);
    # it is dropped from the fit and named, rather than pulling B negative
    assert len(analysis.step_test.steps) == 2
    assert any(f.code == "step_negative_drawdown" for f in analysis.flags)
    assert analysis.step_test.aquifer_loss_B > 0
    # parse-time missing_discharge flag is cleared once values are supplied
    assert not any(f.code == "missing_discharge" for f in analysis.flags)


def _theis_series(T=120.0, S=1e-3, Q=5.0, r=0.1):
    from scipy.special import exp1

    t_min = np.array([1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300, 360], float)
    u = r * r * S / (4 * T * (t_min / 1440.0))
    return t_min, (Q * 24.0) / (4 * np.pi * T) * exp1(u)


def _constant_test(t_min, drawdown, swl=10.0, q=5.0, pump=40.0, depth=60.0):
    from groundwater.models import PumpingStep, PumpingTest, SiteMetadata

    step = PumpingStep(step_number=1, discharge_m3_per_h=q, time_min=t_min,
                       water_level_m=swl + drawdown)
    return PumpingTest(
        site=SiteMetadata(community="synthetic"), test_type="constant",
        static_water_level_m=swl, borehole_depth_m=depth, pump_setting_m=pump,
        steps=[step], pumping_duration_min=float(t_min[-1]),
    )


def test_a_stabilised_tail_is_refused_by_cooper_jacob_and_flagged():
    """A pumped level that stops falling after 45 minutes used to fit a
    near-flat late-time line, giving a transmissivity of thousands of m2/day
    and a 'safe yield' 25 times the tested rate."""
    t_min, s = _theis_series()
    flat = s.copy()
    held = t_min > 45
    flat[held] = s[t_min == 45][0] + 0.002 * np.log10(t_min[held] / 45)
    with pytest.raises(ValueError, match="flat"):
        cooper_jacob(t_min, flat, 5.0)
    analysis = analyse_pumping_test(_constant_test(t_min, flat))
    codes = {f.code for f in analysis.flags}
    assert {"drawdown_stabilised", "cooper_jacob_failed"} <= codes
    assert analysis.transmissivity_source == "theis"
    assert analysis.yield_recommendation.safe_yield_m3_per_h is not None
    assert analysis.yield_recommendation.safe_yield_m3_per_h < 100   # not the 133 the flat fit gave
    assert analysis.yield_recommendation.long_term_yield_m3_per_h < 199
    # a line that explains too little of the window is refused as well
    rng = np.random.default_rng(3)
    noisy = s + rng.normal(0, 0.4, len(s))
    with pytest.raises(ValueError):
        cooper_jacob(t_min, noisy, 5.0, config=PumpingConfig(cooper_jacob_min_r2=0.999))


def test_the_yield_says_why_when_the_pump_leaves_no_usable_drawdown():
    """The intake four metres below static, less submergence and the
    dry-season reserve, leaves nothing: the report used to blame a missing
    discharge that was on the sheet."""
    t_min, s = _theis_series()
    test = _constant_test(t_min, s, pump=14.0)
    analysis = analyse_pumping_test(test)
    yr = analysis.yield_recommendation
    assert yr.safe_yield_m3_per_h is None
    assert "pump intake at 14.0 m" in yr.pending_reason
    assert "no usable drawdown" in yr.pending_reason
    assert "discharge" not in yr.pending_reason
    assert "projected" not in yr.basis
    # the intake exactly at the submergence margin is an answer, not a blank
    exact = analyse_pumping_test(_constant_test(t_min, s, pump=13.0))
    assert exact.yield_recommendation.available_drawdown_m == pytest.approx(0.0)
    assert "no usable drawdown" in exact.yield_recommendation.pending_reason


def test_the_search_ceiling_is_never_reported_as_a_yield():
    """With an implausible transmissivity the bisection used to hand back
    its own 200 m3/h ceiling, and 133 m3/h went into the report."""
    t_min, s = _theis_series()
    test = _constant_test(t_min, s)
    yr = recommend_yield(test, 5000.0, None)
    assert yr.safe_yield_m3_per_h is None
    assert "does not limit the yield" in yr.pending_reason
    honest = recommend_yield(test, 120.0, None, transmissivity_source="theis")
    assert honest.safe_yield_m3_per_h is not None
    assert "from the Theis curve fit" in honest.basis


def test_a_short_test_is_flagged_with_its_extrapolation(sample_data):
    """Dr Timbo pumped for 30 minutes and the yield is projected 4.2 log
    cycles of time to 365 days; that used to pass without a word."""
    test = read_pumping_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    analysis = analyse_pumping_test(test)
    short = [f for f in analysis.flags if f.code == "short_test"]
    assert short and "30 minutes" in short[0].message and "4.2 log cycles" in short[0].message
    assert analysis.yield_recommendation.basis.startswith("Projected from a 30-minute test")
    assert analysis.transmissivity_source == "recovery"   # R squared 0.885 still qualifies
    t_min, s = _theis_series()
    long_test = analyse_pumping_test(_constant_test(t_min, s))
    assert not any(f.code == "short_test" for f in long_test.flags)


def test_a_poor_recovery_fit_does_not_override_a_good_cooper_jacob(sample_data):
    """Kuntolo with discharges: recovery R squared 0.69 used to beat a
    Cooper-Jacob at 0.99 simply by being first in the list."""
    test = read_pumping_workbook(sample_data / "kuntolo" / "kuntolo_step_test.xlsx")
    for step, q in zip(test.steps, (1.5, 2.2, 3.0), strict=True):
        step.discharge_m3_per_h = q
    analysis = analyse_pumping_test(test)
    assert analysis.recovery is not None and analysis.recovery.r_squared < 0.8
    assert analysis.cooper_jacob is not None and analysis.cooper_jacob.r_squared > 0.9
    assert analysis.transmissivity_source == "cooper_jacob"
    assert analysis.transmissivity_m2_per_day == analysis.cooper_jacob.transmissivity_m2_per_day
    assert any("recovery" in f.message for f in test.flags if f.code == "water_level_above_static")
    strict = analyse_pumping_test(test, PumpingConfig(min_fit_r_squared=0.999))
    assert any(f.code == "transmissivity_low_confidence" for f in strict.flags)


def test_a_pinned_step_fit_says_its_efficiencies_are_not_meaningful():
    result = hantush_bierschenk([1.0, 2.0, 3.0], [-0.5, 2.0, 5.0])
    assert result.aquifer_loss_B == 0.0 and result.fit_note
    clean = hantush_bierschenk([1.0, 2.0, 3.0], [1.0, 2.4, 4.2])
    assert clean.fit_note == ""

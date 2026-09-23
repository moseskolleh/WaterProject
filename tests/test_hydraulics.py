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
    # in the pumped well the u criterion is met from the first minute and
    # says nothing about the fit; the report used to read it as validation
    assert "distance criterion" in result.u_check
    assert "does not test the fit" in result.u_check
    observed = cooper_jacob(T_MIN, synthetic_drawdown(), Q, observation_radius_m=25.0)
    assert "valid" in observed.u_check


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


def _constant_test(t_min, drawdown, swl=10.0, q=5.0, pump=40.0, depth=60.0,
                   recovery=None):
    from conftest import synthetic_constant_test

    return synthetic_constant_test(t_min, drawdown, swl=swl, q=q, pump=pump,
                                   depth=depth, recovery=recovery)


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
    # the recovery's R squared of 0.885 used to make it the adopted method;
    # its 21.7 m intercept now rules it out, and nothing else qualifies
    method, _, qualifies = analysis.adopted_fit()
    assert method == "cooper_jacob" and not qualifies
    assert analysis.yield_recommendation.is_indicative
    t_min, s = _theis_series()
    long_test = analyse_pumping_test(_constant_test(t_min, s))
    assert not any(f.code == "short_test" for f in long_test.flags)


def _recovery_of(test, T=120.0):
    """The theoretical Theis recovery of the test's aquifer."""
    q = test.steps[0].discharge_m3_per_h
    t_rec = np.array([1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120], float)
    slope = 2.303 * (q * 24.0) / (4 * np.pi * T)
    return t_rec, slope * np.log10((test.pumping_duration_min + t_rec) / t_rec)


def test_a_poor_recovery_fit_does_not_override_a_good_cooper_jacob():
    """A recovery at R squared 0.47 used to beat a Cooper-Jacob at 0.99
    simply by being first in the list."""
    t_min, s = _theis_series()
    base = _constant_test(t_min, s)
    t_rec, residual = _recovery_of(base)
    wiggle = 0.12 * np.array([1, -1] * 7)[:len(t_rec)]
    analysis = analyse_pumping_test(_constant_test(t_min, s, recovery=(t_rec, residual + wiggle)))
    assert analysis.recovery is not None and analysis.recovery.r_squared < 0.8
    assert analysis.cooper_jacob is not None and analysis.cooper_jacob.r_squared > 0.9
    assert analysis.transmissivity_source == "cooper_jacob"
    assert analysis.transmissivity_m2_per_day == analysis.cooper_jacob.transmissivity_m2_per_day
    assert "R squared" in analysis.why_not_adopted("recovery")
    strict = analyse_pumping_test(
        _constant_test(t_min, s, recovery=(t_rec, residual + wiggle)),
        PumpingConfig(min_fit_r_squared=1.0),
    )
    # with both straight lines below the bar, the curve fit (which has no R
    # squared to fail) is what is left, and it is adopted as qualifying
    assert strict.transmissivity_source == "theis" and strict.adopted_fit()[2]
    assert not any(f.code == "transmissivity_low_confidence" for f in strict.flags)


def test_a_long_test_outside_casing_storage_establishes_its_yield():
    """The fixture every certificate rests on: nothing to flag."""
    t_min, s = _theis_series()
    base = _constant_test(t_min, s)
    analysis = analyse_pumping_test(_constant_test(t_min, s, recovery=_recovery_of(base)))
    yr = analysis.yield_recommendation
    assert analysis.transmissivity_source == "recovery" and analysis.adopted_fit()[2]
    assert analysis.casing_storage_min < analysis.cooper_jacob.fit_window_min[0]
    assert analysis.disqualified == {}
    assert yr.confidence == "established" and not yr.is_indicative
    assert "established" in yr.confidence_text
    assert not {"short_test", "casing_storage", "recovery_intercept"} & {f.code for f in analysis.flags}


def test_a_thirty_minute_test_inside_casing_storage_is_indicative(sample_data):
    """Dr Timbo: 5 inch casing, 0.09 m3/h per m, 30 minutes pumped. The
    casing supplies the pump for the first two hours, the recovery line
    meets t/t' = 1 at 21.7 m, and Theis returns a storativity of 0.18: the
    report used to adopt the recovery's 1.4 m2/day and call the yield
    sustainable."""
    test = read_pumping_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    analysis = analyse_pumping_test(test)
    assert 100 < analysis.casing_storage_min < 130
    assert set(analysis.disqualified) == {"recovery", "cooper_jacob", "theis"}
    codes = {f.code for f in analysis.flags}
    assert {"casing_storage", "recovery_intercept", "storativity_implausible",
            "transmissivity_low_confidence"} <= codes
    assert analysis.recovery.intercept_fraction > 0.5
    assert analysis.theis.storativity > 0.1
    # the best of the poor fits is adopted, and said to be
    assert analysis.transmissivity_source == "cooper_jacob"
    assert not analysis.adopted_fit()[2]
    assert "casing-storage period" in analysis.why_not_adopted("cooper_jacob")
    yr = analysis.yield_recommendation
    assert yr.is_indicative and len(yr.confidence_reasons) == 3
    assert "casing-storage" in yr.confidence_text and "30 minutes" in yr.confidence_text
    assert 0.3 < yr.safe_yield_m3_per_h < 0.5          # not the 0.97 the 1.4 m2/day gave
    assert "0.089" in f"{yr.specific_capacity_m3hr_per_m:.2g}"
    assert yr.specific_capacity_basis == "2.93 m3/h over 32.8 m of drawdown after 30 minutes"


def test_a_recovery_line_that_misses_the_origin_is_not_adopted():
    t_min, s = _theis_series()
    base = _constant_test(t_min, s)
    t_rec, residual = _recovery_of(base)
    analysis = analyse_pumping_test(_constant_test(t_min, s, recovery=(t_rec, residual + 0.3)))
    assert analysis.recovery.intercept_fraction > 0.25
    assert "recovery" in analysis.disqualified
    assert analysis.transmissivity_source == "cooper_jacob" and analysis.adopted_fit()[2]
    assert any(f.code == "recovery_intercept" for f in analysis.flags)
    assert not analysis.yield_recommendation.is_indicative


def test_the_pump_intake_sits_below_the_drawdown_the_yield_uses():
    """The intake used to be raised to just clear the drawdown at the safe
    rate, 3 m above the level the test itself had reached, spending the
    safety factor on lifting the pump."""
    t_min, s = _theis_series()
    analysis = analyse_pumping_test(_constant_test(t_min, s))
    yr = analysis.yield_recommendation
    cfg = PumpingConfig()
    expected = 10.0 + cfg.seasonal_allowance_m + yr.usable_drawdown_m + cfg.pump_submergence_min_m
    assert yr.pump_installation_depth_m == np.ceil(expected)
    assert yr.pump_installation_depth_m >= yr.deepest_pumping_level_m + cfg.pump_submergence_min_m
    assert "kept on the rate" in yr.pump_depth_basis
    # a test that drew the level deeper than that sets the intake itself
    deep = _constant_test(t_min, s + 30.0, pump=55.0, depth=60.0)
    yr_deep = analyse_pumping_test(deep).yield_recommendation
    assert yr_deep.pump_installation_depth_m >= yr_deep.deepest_pumping_level_m + 3
    assert "which sets the intake" in yr_deep.pump_depth_basis


def test_a_first_step_above_static_gets_no_drawdown_fit(sample_data):
    """Kuntolo with discharges: step 1 ends 4.3 m above the stated static
    level. It used to get a Cooper-Jacob line at R squared 0.99, adopted for
    the yield, while the step-test fit excluded it as a datum error."""
    from groundwater.hydraulics import equivalent_pumping_time_min

    test = read_pumping_workbook(sample_data / "kuntolo" / "kuntolo_step_test.xlsx")
    for step, q in zip(test.steps, (1.5, 2.2, 3.0), strict=True):
        step.discharge_m3_per_h = q
    analysis = analyse_pumping_test(test)
    assert analysis.cooper_jacob is None and analysis.theis is None
    codes = [f.code for f in analysis.flags]
    assert "first_step_above_static" in codes
    assert "cooper_jacob_failed" not in codes and "theis_failed" not in codes
    # the recovery after a step test is read against the equivalent time
    assert equivalent_pumping_time_min(test) == (pytest.approx(112.0), True)
    assert analysis.recovery.equivalent_time
    assert analysis.recovery.pumping_time_min == pytest.approx(112.0)
    assert "recovery_equivalent_time" in codes
    # two steps make an exact line, and the result says so
    assert analysis.step_test.two_point
    # the table carries the sheet's step numbers: step 1 was left out, and the
    # 2.2 m3/h step used to be printed as "Step 1"
    assert [s["step"] for s in analysis.step_test.steps] == [2, 3]
    assert analysis.step_test.steps[0]["discharge_m3_per_h"] == pytest.approx(2.2)
    # the sheet's levels run 18 m below the pump: a flag exists for it now
    assert any(f.code == "level_below_pump" for f in test.flags)
    yr = analysis.yield_recommendation
    # A 78.45 m reading below the 70 m hole and the 60 m pump used to set the
    # intake at 67 m ("which sets the intake"). The flagged levels no longer
    # set it, and the yield resting on them is indicative.
    assert yr.pump_installation_depth_m == 50
    assert "which sets the intake" not in yr.pump_depth_basis
    assert "78.5 m, is left out" in yr.pump_depth_basis
    assert yr.is_indicative
    assert yr.confidence_reasons[0].startswith("the recorded water levels are inconsistent")


def test_the_test_type_is_written_in_words():
    from groundwater.hydraulics import test_type_text

    assert test_type_text("constant+recovery") == "constant discharge test with recovery"
    assert test_type_text("step") == "step drawdown test"
    assert test_type_text("step+recovery") == "step drawdown test with recovery"
    assert test_type_text("") == "pumping test"


def test_one_pump_depth_per_report():
    """A report with a seasonal projection said 39 m and then 40 m."""
    from groundwater.hydraulics import pump_intake_depth
    from groundwater.seasonal import seasonal_yield

    t_min, s = _theis_series()
    analysis = analyse_pumping_test(_constant_test(t_min, s))
    seasonal = seasonal_yield(analysis, month=9)
    depth, why = pump_intake_depth(analysis, seasonal)
    assert depth == max(seasonal.pump_installation_depth_m,
                        analysis.yield_recommendation.pump_installation_depth_m)
    assert "drought" in why
    alone, why_alone = pump_intake_depth(analysis)
    assert alone == analysis.yield_recommendation.pump_installation_depth_m and why_alone == ""


def test_a_pinned_step_fit_says_its_efficiencies_are_not_meaningful():
    result = hantush_bierschenk([1.0, 2.0, 3.0], [-0.5, 2.0, 5.0])
    assert result.aquifer_loss_B == 0.0 and result.fit_note
    clean = hantush_bierschenk([1.0, 2.0, 3.0], [1.0, 2.4, 4.2])
    assert clean.fit_note == ""
    # the steps keep the numbers the sheet gave them
    kept = hantush_bierschenk([2.2, 3.0], [2.4, 4.2], step_numbers=[2, 3])
    assert [s["step"] for s in kept.steps] == [2, 3]
    assert [s["step"] for s in clean.steps] == [1, 2, 3]


def _dr_timbo(sample_data):
    return read_pumping_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")


def _dr_timbo_as(sample_data, tmp_path, **cells):
    """The Dr Timbo sheet with header cells rewritten (E5 is the borehole
    depth, E6 the pump setting), read back through the parser so its own
    checks on the levels run against the new values."""
    from openpyxl import load_workbook

    workbook = load_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    for cell, value in cells.items():
        workbook.active[cell] = value
    path = tmp_path / "dr_timbo_edited.xlsx"
    workbook.save(path)
    return read_pumping_workbook(path)


def _recovery_line(test, intercept_m, slope_m):
    """Recovery levels on a clean straight line that misses the origin."""
    t_rec = np.array([1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60], float)
    residual = intercept_m + slope_m * np.log10((test.pumping_duration_min + t_rec) / t_rec)
    test.recovery_time_min = t_rec
    test.recovery_level_m = test.static_water_level_m + residual
    return test


def test_a_rejected_recovery_is_not_adopted_over_a_casing_storage_fallback(sample_data):
    """Dr Timbo with its recovery on a clean line meeting t/t' = 1 at 20 m.
    Every fit was disqualified, and the best of the poor fits was picked by R
    squared over all of them: the rejected recovery won at 0.99, the yield
    rose to 0.99 m3/h, and the flags said in one sentence that the recovery
    was not adopted and in the next that it was."""
    analysis = analyse_pumping_test(_recovery_line(_dr_timbo(sample_data), 20.0, 9.0))
    assert analysis.recovery.r_squared > 0.99
    assert set(analysis.disqualified) == {"recovery", "cooper_jacob", "theis"}
    # the recovery line and the Theis storativity are wrong in themselves; the
    # Cooper-Jacob line is only read inside the casing-storage period
    assert set(analysis.invalid_fits) == {"recovery", "theis"}
    method, fit, qualifies = analysis.adopted_fit()
    assert method == "cooper_jacob" and not qualifies
    assert fit.transmissivity_m2_per_day == pytest.approx(0.536, abs=0.001)
    assert 0.3 < analysis.yield_recommendation.safe_yield_m3_per_h < 0.5
    low = next(f for f in analysis.flags if f.code == "transmissivity_low_confidence")
    assert "The Cooper-Jacob value of 0.54 m2/day is adopted" in low.message
    # the casing-storage flag is worded from the adoption, not against it
    casing = next(f for f in analysis.flags if f.code == "casing_storage")
    assert "the Cooper-Jacob value is adopted only as the best available" in casing.message
    assert "the Theis value is reported but not adopted" in casing.message
    assert "their transmissivity is reported but not adopted" not in casing.message


def test_when_every_fit_is_rejected_the_yield_is_pending_and_says_why(sample_data):
    """Four readings are too few for either drawdown fit, and the recovery
    line misses the origin: nothing is left that the yield could rest on."""
    test = _dr_timbo(sample_data)
    step = test.steps[0]
    step.time_min, step.water_level_m = step.time_min[:4], step.water_level_m[:4]
    test.pumping_duration_min = 3.0
    analysis = analyse_pumping_test(_recovery_line(test, 20.0, 9.0))
    assert analysis.cooper_jacob is None and analysis.theis is None
    assert "recovery" in analysis.invalid_fits
    assert analysis.adopted_fit() == (None, None, False)
    assert analysis.transmissivity_m2_per_day is None
    yr = analysis.yield_recommendation
    assert yr.safe_yield_m3_per_h is None and yr.yield_range_text == "pending"
    assert yr.pending_reason.startswith(
        "no fitted transmissivity can be adopted (Theis recovery")
    assert "where the method requires zero" in yr.pending_reason
    assert not any(f.code == "transmissivity_low_confidence" for f in analysis.flags)


def test_levels_below_the_pump_make_the_yield_indicative_and_set_no_intake(
        sample_data, tmp_path):
    """Dr Timbo written with the pump at 15 m: the level is recorded at 42.3 m,
    27 m below a pump that cannot draw it there. That reading set the intake
    at 46 m, and a sheet whose only fault was such a level was certified as
    an established yield."""
    from groundwater.models import DataFlag

    test = _dr_timbo_as(sample_data, tmp_path, E6=15)
    assert any(f.code == "level_below_pump" for f in test.flags)
    yr = analyse_pumping_test(test).yield_recommendation
    assert yr.is_indicative
    assert yr.confidence_reasons[0] == (
        "the recorded water levels are inconsistent with the stated static level, "
        "pump setting or borehole depth, so the drawdowns the yield is computed "
        "from are as recorded and not to be relied on"
    )
    # the intake comes from the usable drawdown, never from the flagged level
    assert yr.pump_installation_depth_m == 15
    assert "42.3 m, is left out" in yr.pump_depth_basis
    # the envelope's corners did not bracket this yield, and 0.0067 m3/h was
    # printed beside a range that began at 0.0068
    assert yr.safe_yield_low_m3_per_h <= yr.safe_yield_m3_per_h <= yr.safe_yield_high_m3_per_h

    # a clean long test is established; the same test with one such flag is not
    t_min, s = _theis_series()
    clean = _constant_test(t_min, s)
    assert analyse_pumping_test(clean).yield_recommendation.confidence == "established"
    clean.flags = [DataFlag("warning", "level_below_borehole", "below the bottom")]
    flagged = analyse_pumping_test(clean).yield_recommendation
    assert flagged.is_indicative and len(flagged.confidence_reasons) == 1


def test_the_intake_is_never_below_the_test_pump_or_within_3_m_of_the_bottom(
        sample_data, tmp_path):
    """Dr Timbo in a 45.5 m hole with the pump at 44 m. The deepest level plus
    submergence (45.3 m) set the intake below the pump that drew it, and
    rounding up after the 3 m cap put it at 43 m, 2.5 m above the bottom,
    beside text saying it was capped 3 m above."""
    test = _dr_timbo_as(sample_data, tmp_path, E5=45.5, E6=44)
    assert not {"level_below_pump", "level_below_borehole"} & {f.code for f in test.flags}
    yr = analyse_pumping_test(test).yield_recommendation
    assert yr.pump_installation_depth_m == 42
    assert "which sets the intake at the 44 m the test pump was set to" in yr.pump_depth_basis
    assert "capped 3 m above the 45.5 m bottom" in yr.pump_depth_basis


def test_the_yield_range_leaves_out_the_fits_the_analysis_rejected(sample_data):
    """Dr Timbo printed "0.39 m3/h (0.28 to 1.2)": the top of the range came
    from the recovery transmissivity of 1.40 m2/day that the same analysis
    refused for missing the origin."""
    analysis = analyse_pumping_test(_dr_timbo(sample_data))
    yr = analysis.yield_recommendation
    adopted = analysis.transmissivity_m2_per_day
    # only the adopted casing-storage fallback is left, so the band is the
    # one-method factor of 1.5 around it, not the spread to the recovery
    assert f"{adopted / 1.5:.1f}-{adopted * 1.5:.1f} m2/day" in yr.envelope_basis
    assert "spread between the fitted methods" not in yr.envelope_basis
    assert yr.yield_range_text == "0.39 m3/h (0.22 to 0.71)"


def _step_test(times_by_step, rates=(1.5, 2.2, 3.0), step_length=None):
    """A step test in an ideal well, each step's level rising with log time."""
    from groundwater.models import PumpingStep, PumpingTest, SiteMetadata

    swl = 10.0
    steps = [
        PumpingStep(step_number=n, discharge_m3_per_h=q,
                    time_min=np.asarray(times, float),
                    water_level_m=swl + q * (1.0 + 0.3 * np.log10(np.asarray(times, float))),
                    label=f"Step {n}")
        for n, (times, q) in enumerate(zip(times_by_step, rates, strict=True), start=1)
    ]
    t_rec = np.array([1, 2, 3, 5, 10, 20, 30, 60], float)
    return PumpingTest(
        site=SiteMetadata(community="synthetic"), test_type="step+recovery",
        static_water_level_m=swl, borehole_depth_m=70.0, pump_setting_m=60.0,
        step_length_min=step_length, steps=steps,
        pumping_duration_min=float(max(float(np.max(s.time_min)) for s in steps)),
        recovery_time_min=t_rec,
        recovery_level_m=swl + 3.0 * np.log10((158.0 + t_rec) / t_rec),
    )


def test_a_step_test_whose_times_restart_each_step_keeps_its_length():
    """Each step counted from its own start: the equivalent time for the
    recovery came out at 30 minutes where the steps had pumped 112, the flag
    said the test ran 60 minutes where it ran 158, and nothing said the
    sheet's clock restarted."""
    from groundwater.hydraulics import equivalent_pumping_time_min
    from groundwater.hydraulics.analysis import step_durations_min

    running = _step_test([np.arange(1, 61), np.arange(61, 121), np.arange(121, 159)])
    restarting = _step_test([np.arange(1, 61), np.arange(1, 61), np.arange(1, 39)])
    assert step_durations_min(running.steps) == ([60.0, 60.0, 38.0], [])
    assert step_durations_min(restarting.steps) == ([60.0, 60.0, 38.0], [2, 3])
    assert equivalent_pumping_time_min(running) == (pytest.approx(112.0), True)
    assert equivalent_pumping_time_min(restarting) == (pytest.approx(112.0), True)

    analysis = analyse_pumping_test(restarting)
    restart = next(f for f in analysis.flags if f.code == "step_time_restarted")
    assert restart.message.startswith("Steps 2 and 3 open at or before the minute")
    assert "158 minutes in all, not the 60 minutes the latest reading gives" in restart.message
    equivalent = next(f for f in analysis.flags if f.code == "recovery_equivalent_time")
    assert "equivalent pumping time of 112 minutes" in equivalent.message
    assert "not the 158 minutes the test ran" in equivalent.message
    assert not any(f.code == "step_time_restarted" for f in analyse_pumping_test(running).flags)


def test_a_step_test_is_judged_per_step_in_its_own_words():
    """A 3 x 50-minute step test inside its casing-storage period was said to
    have "pumped for 50 minutes" with "the whole test" inside the period, of
    a test that pumped for 150."""
    t = np.array([1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50], float)
    test = _step_test([t, t + 50, t + 100], rates=(1.0, 2.0, 3.0), step_length=50.0)
    test.test_type = "step"
    test.recovery_time_min = test.recovery_level_m = None
    analysis = analyse_pumping_test(test, PumpingConfig(casing_diameter_in=12.0))
    assert analysis.casing_storage_min > 50
    reasons = analysis.yield_recommendation.confidence_reasons
    assert reasons[0].startswith("each step ran for 50 minutes, below the 60 needed")
    assert reasons[1].startswith("each step lies inside the ")
    assert not any("the test pumped" in r or "the whole test" in r for r in reasons)
    casing = next(f for f in analysis.flags if f.code == "casing_storage")
    assert "; each step pumped for 50 minutes, entirely inside it" in casing.message
    assert analysis.disqualified["theis"].startswith("each 50-minute step lies inside")


def test_a_negative_recovery_intercept_is_a_share_of_a_positive_drawdown(sample_data):
    """A recovery line meeting t/t' = 1 below zero printed "37% of the -21.8 m
    the recovery started from"."""
    analysis = analyse_pumping_test(_recovery_line(_dr_timbo(sample_data), -8.0, 20.0))
    rec = analysis.recovery
    assert rec.intercept_m < 0 and "recovery" in analysis.disqualified
    flag = next(f for f in analysis.flags if f.code == "recovery_intercept")
    assert "of the -" not in flag.message
    assert f"of the {abs(rec.intercept_m) / rec.intercept_fraction:.1f} m the recovery" in flag.message

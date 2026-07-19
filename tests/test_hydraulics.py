import numpy as np
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
    from dataclasses import replace

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
    for step, q in zip(test.steps, (1.5, 2.2, 3.0)):
        step.discharge_m3_per_h = q
    analysis = analyse_pumping_test(test)
    assert analysis.step_test is not None
    assert len(analysis.step_test.steps) == 3
    # parse-time missing_discharge flag is cleared once values are supplied
    assert not any(f.code == "missing_discharge" for f in analysis.flags)

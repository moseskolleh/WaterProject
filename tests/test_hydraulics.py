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


def test_step_analysis_after_supplying_discharge(sample_data):
    test = read_pumping_workbook(sample_data / "kuntolo" / "kuntolo_step_test.xlsx")
    for step, q in zip(test.steps, (1.5, 2.2, 3.0)):
        step.discharge_m3_per_h = q
    analysis = analyse_pumping_test(test)
    assert analysis.step_test is not None
    assert len(analysis.step_test.steps) == 3
    # parse-time missing_discharge flag is cleared once values are supplied
    assert not any(f.code == "missing_discharge" for f in analysis.flags)


def test_bourdet_derivative_recovers_theis_plateau():
    """For a Theis drawdown curve the late-time log-derivative is flat
    at Q/(4 pi T); the Bourdet estimate must land on it."""
    import numpy as np
    from scipy.special import exp1

    from groundwater.hydraulics.plots import bourdet_derivative

    T = 50.0  # m2/day
    S = 1e-3
    q_day = 120.0  # m3/day
    r = 0.1
    t_min = np.geomspace(1.0, 1000.0, 60)
    t_day = t_min / 1440.0
    u = r**2 * S / (4.0 * T * t_day)
    s = q_day / (4.0 * np.pi * T) * exp1(u)

    t_out, s_out, deriv = bourdet_derivative(t_min, s)
    plateau = q_day / (4.0 * np.pi * T)
    late = deriv[np.isfinite(deriv)][-10:]
    assert np.allclose(late, plateau, rtol=0.05)


def test_diagnostic_derivative_plot(tmp_path):
    import numpy as np

    from groundwater.hydraulics.plots import plot_diagnostic_derivative

    t = np.geomspace(1.0, 600.0, 40)
    s = 0.5 * np.log(t) + 1.0
    out = tmp_path / "diag.png"
    result = plot_diagnostic_derivative(t, s, path=out)
    assert result is not None and out.exists()
    # too few points: quietly declines
    assert plot_diagnostic_derivative(t[:3], s[:3]) is None

"""The spread of a pumping test's results (PLAN.md step 3.2, hydraulics/spread.py).

The calibration tests draw synthetic tests with a known transmissivity, add
reading errors, and count how often the P10 to P90 band of the bootstrap
contains the truth. A band of the 10th to the 90th percentile should contain
it 80 percent of the time; what it actually does is printed and held here,
so a change that makes the bands wider or narrower shows up as a number.
"""

import math
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.integrate import quad
from scipy.optimize import curve_fit
from scipy.special import exp1, j0, j1, y0, y1

from groundwater.config import PumpingConfig
from groundwater.hydraulics import analyse_pumping_test
from groundwater.hydraulics.analysis import (
    PumpingTestAnalysis,
    cooper_jacob,
    theis_fit,
)
from groundwater.hydraulics.spread import (
    Mulberry32,
    _local_slopes,
    block_length,
    bootstrap_fit,
    bourdet_derivative,
    classify_regimes,
    covariance_log2,
    diagnostic_text,
    diagnostic_thresholds_text,
    papadopulos_cooper_fit,
    pc_model,
    pc_well_function,
    quantile,
    resample_blocks,
    spread_paragraphs,
    stehfest_weights,
    sustainable_sentence,
    theis_model,
)
from groundwater.ingestion import read_pumping_workbook
from groundwater.models import PumpingStep, PumpingTest, SiteMetadata

from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "examples" / "data"
TIMES = np.array([1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 75, 90,
                  105, 120, 150, 180, 210, 240], float)
Q = 2.0


# ------------------------------------------------------------- the generator

def test_mulberry32_is_32_bit_and_repeatable():
    a, b = Mulberry32(32), Mulberry32(32)
    draws = [a.next_float() for _ in range(1000)]
    assert draws == [b.next_float() for _ in range(1000)]
    assert all(0.0 <= d < 1.0 for d in draws)
    # the stream the browser's Math.imul version gives from the same seed;
    # parity.mjs compares the two engines on a longer one
    assert Mulberry32(32).next_float() == 0.3876417982392013
    assert abs(np.mean(draws) - 0.5) < 0.03


def test_quantile_is_numpys_linear_percentile():
    values = [3.0, 1.0, 4.0, 1.5, 9.0, 2.6]
    for q in (0.0, 0.1, 0.5, 0.9, 1.0):
        assert quantile(values, q) == pytest.approx(np.percentile(values, 100 * q), abs=1e-15)


def test_block_length_is_the_whole_cube_root_and_at_least_two():
    assert [block_length(n) for n in (5, 8, 9, 27, 28, 64, 65)] == [2, 2, 3, 3, 4, 4, 5]


def test_blocks_wrap_and_keep_the_length():
    residuals = [float(i) for i in range(7)]
    draw = resample_blocks(Mulberry32(1), residuals, 3)
    assert len(draw) == 7
    # every block is consecutive, wrapping from the last reading to the first
    for start in range(0, 6, 3):
        block = draw[start:start + 3]
        assert all((block[k] + 1) % 7 == block[k + 1] for k in range(len(block) - 1))


# --------------------------------------------- Papadopulos-Cooper, by Stehfest

def _pc_integral(u_w, alpha):
    """Papadopulos and Cooper's (1967) closed form for F(u_w, alpha), by quadrature."""

    def integrand(b):
        delta = (b * j0(b) - 2 * alpha * j1(b)) ** 2 + (b * y0(b) - 2 * alpha * y1(b)) ** 2
        return (1 - math.exp(-b * b / (4 * u_w))) / (b**3 * delta)

    edges = [0.0, 1e-8, 1e-4, 1e-2, 1.0, 10.0, 100.0]
    total = sum(quad(integrand, lo, hi, limit=400, epsabs=0, epsrel=1e-11)[0]
                for lo, hi in zip(edges[:-1], edges[1:], strict=True))
    total += quad(integrand, 100.0, np.inf, limit=400)[0]
    return 32 * alpha**2 / math.pi**2 * total


@pytest.mark.filterwarnings("ignore::scipy.integrate.IntegrationWarning")
@pytest.mark.parametrize("alpha", [1e-1, 1e-3, 1e-5])
@pytest.mark.parametrize("inverse_u", [1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6])
def test_stehfest_matches_the_published_solution(alpha, inverse_u):
    """Twelve Stehfest terms reproduce Papadopulos and Cooper's integral.

    The paper's tabulated values are that integral to four figures; the
    table itself could not be fetched here, so the check is against the
    integral the table was computed from, evaluated independently by
    quadrature over Bessel functions of the first and second kinds.
    """
    u_w = 1.0 / inverse_u
    published = _pc_integral(u_w, alpha)
    assert pc_well_function(u_w, alpha) == pytest.approx(published, rel=2e-5)


def test_large_diameter_limits():
    # early: the pump empties the casing, F = alpha / u_w
    assert pc_well_function(1e2, 1e-3) == pytest.approx(1e-3 / 1e2, rel=1e-3)
    # late: the casing is spent and the well is a Theis well
    assert pc_well_function(1e-6, 1e-1) == pytest.approx(exp1(1e-6), rel=2e-3)


def test_stehfest_inverts_the_simplest_transforms_exactly():
    weights = stehfest_weights(12)
    # a constant transform has no inverse away from t = 0: the weights sum to 0
    assert sum(weights) == pytest.approx(0.0, abs=1e-6)
    # 1/p is the transform of 1: (ln2/t) sum V_i t/(i ln2) = sum V_i / i
    assert sum(w / (i + 1) for i, w in enumerate(weights)) == pytest.approx(1.0, rel=1e-9)


def test_papadopulos_cooper_fit_recovers_known_t_and_s():
    true_t, true_s, rc = 1.5, 2e-4, 0.0615
    s = pc_model(Q * 24, 0.1, rc)(TIMES / 1440, math.log10(true_t), math.log10(true_s))
    result = papadopulos_cooper_fit(TIMES, s, Q, 0.1, rc)
    assert result.transmissivity_m2_per_day == pytest.approx(true_t, rel=1e-4)
    assert result.storativity == pytest.approx(true_s, rel=1e-3)
    assert result.alpha == pytest.approx(0.01 * true_s / rc**2, rel=1e-3)


# ------------------------------------------------------- the Theis covariance

def test_theis_keeps_the_covariance_curve_fit_returns():
    true_t, true_s = 5.0, 1e-3
    rng = np.random.default_rng(3)
    s = theis_model(Q * 24, 0.1)(TIMES / 1440, math.log10(true_t), math.log10(true_s))
    y = s + rng.normal(0, 0.02, len(s))
    result = theis_fit(TIMES, y, Q)
    assert result.log_covariance is not None
    p = [math.log10(result.transmissivity_m2_per_day), math.log10(result.storativity)]
    # what the browser computes from the Jacobian, which has no curve_fit
    mine = covariance_log2(theis_model(Q * 24, 0.1), TIMES / 1440, y, p)
    assert np.allclose(mine, result.log_covariance, rtol=1e-4)
    _, pcov = curve_fit(theis_model(Q * 24, 0.1), TIMES / 1440, y, p0=p)
    assert np.allclose(pcov, result.log_covariance, rtol=1e-4)
    sigma = math.sqrt(result.log_covariance[0][0])
    assert result.transmissivity_low_m2_per_day == pytest.approx(
        10 ** (p[0] - 1.2815515655446004 * sigma))
    assert result.transmissivity_low_m2_per_day < result.transmissivity_m2_per_day
    assert result.transmissivity_high_m2_per_day > result.transmissivity_m2_per_day


# ---------------------------------------------- the Bourdet derivative, regimes

DIAGNOSTIC_TIMES = np.geomspace(0.5, 3000, 45)
T5, S3 = 5.0, 1e-3


def _theis(t, radius=0.1):
    u = radius**2 * S3 / (4 * T5 * t / 1440)
    return Q * 24 / (4 * math.pi * T5) * exp1(u)


def _regimes(drawdown, config=None):
    config = config or PumpingConfig()
    t, d = bourdet_derivative(DIAGNOSTIC_TIMES, drawdown, config.diagnostic_l_log10)
    slopes = _local_slopes(t, d, config.diagnostic_window_log10)
    return [r.key for r in classify_regimes(t, d, slopes, config)]


def test_bourdet_derivative_of_a_straight_line_on_log_time():
    # s = a ln t has ds/d ln t = a exactly, whatever the spacing
    t = np.array([1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144], float)
    times, values = bourdet_derivative(t, 0.7 * np.log(t), 0.2)
    assert values == pytest.approx([0.7] * len(values))
    # no derivative at an end without a neighbour 0.2 of a cycle beyond it
    assert times[0] > t[0] and times[-1] < t[-1]


@pytest.mark.parametrize("noise", [0.0, 0.005])
def test_regimes_on_synthetic_curves(noise):
    rng = np.random.default_rng(1)

    def read(s):
        return np.round(s + rng.normal(0, noise, len(s)), 2) if noise else s

    tday = DIAGNOSTIC_TIMES / 1440
    # radial flow from the first minute in a small-diameter well
    assert _regimes(read(_theis(DIAGNOSTIC_TIMES))) == ["radial_flow"]
    # casing storage: a unit slope, the hump falling away, then radial flow
    slow = pc_model(Q * 24, 0.1, 0.0615)(tday, math.log10(0.5), math.log10(S3))
    assert _regimes(read(slow)) == ["wellbore_storage", "storage_ending", "radial_flow"]
    # linear flow along a fracture: s grows with the square root of time
    assert _regimes(read(0.3 * np.sqrt(DIAGNOSTIC_TIMES))) == ["linear_flow"]
    # a recharge boundary 30 m away (image well at 60 m) and a barrier
    recharge = _regimes(read(_theis(DIAGNOSTIC_TIMES) - _theis(DIAGNOSTIC_TIMES, 60.0)))
    assert recharge == ["radial_flow", "recharge_boundary"]
    barrier = _regimes(read(_theis(DIAGNOSTIC_TIMES) + _theis(DIAGNOSTIC_TIMES, 60.0)))
    assert barrier[:2] == ["radial_flow", "no_flow_boundary"]


def test_the_thresholds_are_settings_and_are_stated():
    text = diagnostic_thresholds_text()
    assert "0.75 to 1.25 casing storage" in text
    assert "0.35 to 0.65 linear flow" in text
    # a hydrogeologist who reads half slopes more widely moves the setting
    from dataclasses import replace
    wide = replace(PumpingConfig(), regime_half_slope_min=0.3, regime_half_slope_max=0.7)
    assert "0.3 to 0.7 linear flow" in diagnostic_thresholds_text(wide)


# ------------------------------------------------------------- the bootstrap

def _noisy(s, rng, phi=0.0, sigma=0.02):
    """Reading errors of sigma metres, correlated phi from one reading to the
    next, read to the dipper's centimetre."""
    e = np.zeros(len(s))
    for i in range(len(s)):
        e[i] = (phi * e[i - 1] if i else 0.0) + rng.normal(0, sigma)
    return np.round(s + e, 2)


def _synthetic(method, rng, phi=0.0):
    if method == "papadopulos_cooper":
        true_t = 1.0
        s = pc_model(Q * 24, 0.1, 0.0615)(TIMES / 1440, 0.0, -3.0)
    else:
        true_t = 5.0
        s = theis_model(Q * 24, 0.1)(TIMES / 1440, math.log10(true_t), -3.0)
    y = _noisy(s, rng, phi)
    test = SimpleNamespace(static_water_level_m=10.0, steps=[
        SimpleNamespace(time_min=TIMES, water_level_m=10.0 + y, discharge_m3_per_h=Q)])
    analysis = SimpleNamespace(test=test, theis=None, cooper_jacob=None,
                               papadopulos_cooper=None)
    if method == "theis":
        analysis.theis = theis_fit(TIMES, y, Q)
    elif method == "cooper_jacob":
        analysis.cooper_jacob = cooper_jacob(TIMES, y, Q)
    else:
        analysis.papadopulos_cooper = papadopulos_cooper_fit(TIMES, y, Q, 0.1, 0.0615)
    return true_t, analysis


def _coverage(method, cases, phi=0.0, seed=7):
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(cases):
        truth, analysis = _synthetic(method, rng, phi)
        band = bootstrap_fit(analysis, method)
        assert band.p10 is not None and band.p10 <= band.p50 <= band.p90
        hits += band.p10 <= truth <= band.p90
    return hits / cases


# The draws are seeded, so each rate is one exact number; the limits sit
# about two standard errors either side of it, so a change that narrows or
# widens the bands by a tenth fails here rather than passing unseen.
@pytest.mark.parametrize("method, cases, low, high", [
    ("cooper_jacob", 300, 0.69, 0.79),
    ("theis", 120, 0.56, 0.72),
])
def test_bands_contain_the_truth_at_the_stated_rate(method, cases, low, high, capsys):
    """Independent reading errors of 2 cm, read to the centimetre.

    Measured: Cooper-Jacob 0.737 (300 tests), Theis 0.642 (120 tests),
    against the 0.80 a P10 to P90 band names. The Cooper-Jacob window holds
    thirteen readings; resampled singly rather than in blocks of three they
    give 0.777. The Theis fit's own covariance band holds the truth in 0.667
    of the same tests. The band is read as a lower bound on the spread, never
    as a guarantee, and the reports say so beside it.
    """
    rate = _coverage(method, cases)
    with capsys.disabled():
        print(f"\n{method}: P10-P90 band holds the true T in {rate:.3f} of {cases} tests")
    assert low <= rate <= high


@pytest.mark.parametrize("phi, low, high", [(0.3, 0.57, 0.68), (0.6, 0.42, 0.54)])
def test_correlated_errors_narrow_the_band(phi, low, high):
    """Consecutive errors correlated (a pump rate that wanders): the blocks
    carry some of it, and the band holds the truth less often: 0.623 at 0.3
    and 0.477 at 0.6, the rates the reports print."""
    rate = _coverage("cooper_jacob", 300, phi=phi)
    assert low <= rate <= high


@pytest.mark.slow
def test_large_diameter_bands_contain_the_truth():
    """The Papadopulos-Cooper refits cost about 7 ms each in Python, so 24
    tests of 400 resamples take about a minute. Measured: 0.67."""
    rate = _coverage("papadopulos_cooper", 24)
    assert 0.5 <= rate <= 0.85


def test_too_few_readings_give_no_band():
    t = np.array([10.0, 20.0, 40.0, 80.0, 160.0, 320.0])
    s = 0.5 * np.log10(t) + 1.0
    test = SimpleNamespace(static_water_level_m=0.0, steps=[
        SimpleNamespace(time_min=t, water_level_m=s, discharge_m3_per_h=Q)])
    analysis = SimpleNamespace(test=test, cooper_jacob=cooper_jacob(t, s, Q, fit_window_min=(40, 320)))
    band = bootstrap_fit(analysis, "cooper_jacob")
    assert band.n_points == 4 and band.reason == "too_few" and band.p10 is None


# ---------------------------------------------- what the analysis now carries

def _timbo():
    return analyse_pumping_test(read_pumping_workbook(
        DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx"))


def test_central_figures_are_not_moved_and_sit_inside_their_bands():
    analysis = _timbo()
    rec, spread = analysis.yield_recommendation, analysis.spread
    # the values reference.json holds for this test since before step 3.2
    assert analysis.transmissivity_source == "cooper_jacob"
    assert rec.pump_installation_depth_m == 52
    assert spread.safe_yield_low_m3_per_h <= rec.safe_yield_m3_per_h <= spread.safe_yield_high_m3_per_h
    assert spread.pump_depth_low_m <= rec.pump_installation_depth_m <= spread.pump_depth_high_m
    boot = spread.bootstrap
    assert boot.method == "cooper_jacob" and boot.replicates == 400
    assert boot.p10 < analysis.transmissivity_m2_per_day < boot.p90
    text = spread_paragraphs(analysis)
    assert text[0].startswith("Resampling the Cooper-Jacob residuals in blocks of 2")
    assert any("dry-season reserve" in line for line in text)


def test_a_test_with_no_drawdown_fit_has_no_diagnostic():
    test = read_pumping_workbook(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    for step, q in zip(test.steps, (1.5, 2.2, 3.0), strict=True):
        step.discharge_m3_per_h = q
    analysis = analyse_pumping_test(test)
    # its first step ends above static, so nothing is fitted to it
    assert analysis.diagnostic is None
    assert diagnostic_text(analysis.diagnostic).startswith("The first step has fewer")
    assert analysis.spread.bootstrap.method == "recovery"


def _short_large_diameter_test():
    """Thirty minutes from a borehole whose casing holds most of what is
    pumped (T = 0.3 m2/day), with a recovery that misses the origin. Every
    fit is disqualified: the Theis storativity is implausible, the recovery
    misses the origin, and the Cooper-Jacob line lies inside the 269-minute
    casing-storage period. Before step 3.2 that line was adopted as the best
    available, at 0.20 m2/day."""
    times = np.array([1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30], float)
    drawdown = pc_model(1.0 * 24, 0.1, 0.0615)(times / 1440, math.log10(0.3), -3.0)
    levels = 5.0 + np.round(drawdown, 2)
    rec_t = np.array([1, 2, 3, 4, 5, 10, 15, 20, 30], float)
    rec_levels = levels[-1] - 0.05 * np.log1p(rec_t)
    return PumpingTest(
        site=SiteMetadata(), test_type="constant+recovery", static_water_level_m=5.0,
        borehole_depth_m=60.0, pump_setting_m=50.0, pumping_duration_min=30.0,
        steps=[PumpingStep(step_number=1, discharge_m3_per_h=1.0, time_min=times,
                           water_level_m=levels, label="Constant")],
        recovery_time_min=rec_t, recovery_level_m=rec_levels,
    )


def test_a_short_test_inside_casing_storage_is_no_longer_empty():
    analysis = analyse_pumping_test(_short_large_diameter_test())
    assert analysis.papadopulos_cooper is not None
    pc = analysis.papadopulos_cooper
    assert pc.transmissivity_m2_per_day == pytest.approx(0.3, rel=0.05)
    assert analysis.cooper_jacob.transmissivity_m2_per_day == pytest.approx(0.20, rel=0.05)
    assert "cooper_jacob" in analysis.disqualified
    # the readings inside casing storage are modelled rather than discarded
    assert analysis.adopted_fit() == ("papadopulos_cooper", pc, False)
    assert analysis.transmissivity_m2_per_day == pc.transmissivity_m2_per_day
    assert analysis.spread.bootstrap.method == "papadopulos_cooper"
    rec = analysis.yield_recommendation
    assert rec.safe_yield_m3_per_h is not None
    # still a short test: indicative, and never "sustainable"
    assert rec.is_indicative
    assert sustainable_sentence(rec, analysis.spread) is None


def test_the_large_diameter_fit_is_adopted_only_where_every_fit_is_disqualified():
    analysis = PumpingTestAnalysis(test=None)  # type: ignore[arg-type]
    analysis.papadopulos_cooper = SimpleNamespace(transmissivity_m2_per_day=1.0)
    analysis.recovery = SimpleNamespace(transmissivity_m2_per_day=2.0, r_squared=0.99)
    analysis.cooper_jacob = SimpleNamespace(transmissivity_m2_per_day=3.0, r_squared=0.5)
    assert analysis.adopted_fit()[0] == "recovery"
    analysis.disqualified["recovery"] = analysis.invalid_fits["recovery"] = "misses the origin"
    # a poor fit nothing disqualified is still the best of the poor fits
    assert analysis.adopted_fit()[0] == "cooper_jacob"
    analysis.disqualified["cooper_jacob"] = "inside the casing-storage period"
    assert analysis.adopted_fit() == ("papadopulos_cooper", analysis.papadopulos_cooper, False)
    # an invalid large-diameter fit leaves the casing-storage fallback
    analysis.papadopulos_cooper_invalid = "its storativity of 0.5 is above 0.1"
    assert analysis.adopted_fit()[0] == "cooper_jacob"
    analysis.invalid_fits["cooper_jacob"] = "wrong"
    assert analysis.adopted_fit() == (None, None, False)


def test_sustainable_only_where_the_band_holds_at_the_dry_season_level():
    rec = SimpleNamespace(safe_yield_m3_per_h=1.0, is_indicative=False)
    holds = SimpleNamespace(holds_at_dry_season=True)
    fails = SimpleNamespace(holds_at_dry_season=False)
    assert sustainable_sentence(rec, holds).startswith("The borehole is successful and sustainable")
    assert "not called sustainable" in sustainable_sentence(rec, fails)
    assert "not called sustainable" in sustainable_sentence(rec, None)
    rec.is_indicative = True
    assert sustainable_sentence(rec, holds) is None


# ------------------------------------------------- what the reports may claim

def test_the_band_sentence_does_not_claim_the_rate_its_percentiles_name():
    """A band that holds the truth 64 to 74 times in a hundred is not printed
    as a bare "P10 to P90": the measured rates go beside it, in the words
    both engines print."""
    text = spread_paragraphs(_timbo())
    band = text[0]
    assert "(P10 to P90)" in band
    assert "64 to 74 tests in a hundred, not 80" in band
    assert "48 when consecutive errors" in band
    assert "least the spread can be" in band
    theis = next(line for line in text if line.startswith("The Theis fit's own covariance"))
    assert "nominally P10 to P90" in theis and "67 tests in a hundred" in theis


def test_the_regime_limits_say_a_named_regime_can_be_scatter():
    text = diagnostic_thresholds_text()
    assert "one test in a hundred" in text
    assert "not a finding on its own" in text


def test_the_large_diameter_fit_rejected_on_misfit_says_no_better():
    """The rule rejects a misfit above the Theis curve's. Two RMSEs printed to
    three figures can read alike - 1.76 m against 1.76 m on the scattered
    sheet reference.json carries as wide_band, rebuilt here - so the reason
    reads "no better than", which is true of a worse fit and an equal one."""
    from groundwater.hydraulics.spread import papadopulos_cooper_text

    times = np.array([1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60], float)
    wobble = np.array([0.1, -0.2, 0.15, -0.1, 0.3, -0.4, 0.5, -0.3, 0.6, -0.5, 0.7,
                       -0.6, 0.8, -0.7, 0.9, -0.2])
    levels = 5.0 + np.round(1.2 * np.log10(times) + 2.0 + 3.5 * wobble, 2)
    test = PumpingTest(
        site=SiteMetadata(), test_type="constant", static_water_level_m=5.0,
        borehole_depth_m=60.0, pump_setting_m=50.0, pumping_duration_min=60.0,
        steps=[PumpingStep(step_number=1, discharge_m3_per_h=2.0, time_min=times,
                           water_level_m=levels, label="Constant")],
    )
    analysis = analyse_pumping_test(test)
    pc, th = analysis.papadopulos_cooper, analysis.theis
    assert f"{pc.rmse_m:.3g}" == f"{th.rmse_m:.3g}" and pc.rmse_m > th.rmse_m
    assert analysis.papadopulos_cooper_invalid.startswith(
        "it fits the readings no better than the Theis curve")
    text = papadopulos_cooper_text(analysis)
    assert "Its storativity is not given" in text and "two engines" not in text


def test_every_source_the_spread_names_is_a_pumping_reference():
    from groundwater.reporting.citations import references_for

    cited = " ".join(references_for("pumping"))
    for author in ("Kuensch", "Politis", "Hall, P.", "Davison", "Bourdet",
                   "Stehfest", "Papadopulos", "Renard, P."):
        assert author in cited

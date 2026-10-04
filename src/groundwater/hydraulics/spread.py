"""How far the pumping test results can be trusted (PLAN.md step 3.2).

A pumping test gives one transmissivity from one fit, and the yield and the
pump setting follow from it. This module puts a spread on each of them and
names the flow regime the readings show, so a report can say how wide the
answer is and which model it should have come from.

Four things live here, each mirrored rule for rule in ``docs/js/gwt-core.js``
(the section headed "pumping spread"), and held to it by the parity suite:

* **A block bootstrap of the adopted fit's residuals.** The fitted curve
  plus resampled residuals is refitted ``bootstrap_replicates`` times, and
  the 10th, 50th and 90th percentiles of the refitted transmissivity are the
  band. The residuals of a pumping test are not independent: a dipper read
  every minute sees the same wobble in the pump rate several readings
  running. Resampling single readings would treat that wobble as fresh
  information each time and give a band that is too narrow, so the residuals
  are resampled in blocks of consecutive readings (Kuensch 1989), wrapped
  from the last reading to the first (Politis and Romano's circular blocks)
  so the late readings are drawn as often as the rest. The block length is
  the smallest whole number whose cube is at least the number of readings,
  the n^(1/3) order Hall, Horowitz and Jing (1995) show is right for a
  variance or a percentile, and never less than two. The draws come from
  mulberry32, a 32-bit generator small enough to be written identically in
  both engines, from a fixed seed, so the same sheet gives the same band in
  either app on every run.

  On synthetic tests with independent 2 cm reading errors read to the
  centimetre, the P10 to P90 band holds the true transmissivity in 74
  percent of Cooper-Jacob fits, 64 of Theis fits and 67 of Papadopulos-Cooper
  fits, not the 80 the percentiles name: with eight to twenty-four readings
  the percentile bootstrap runs narrow. With errors correlated at 0.3 from one reading to
  the next it is 62 percent, and at 0.6, 48 (tests/test_pumping_spread.py).
  Read the band as the least the spread can be.
* **The Theis fit's own covariance**, which ``curve_fit`` returns and the
  analysis used to throw away. It is the band the fit gives when every
  reading's error is independent; the bootstrap does not assume that, and
  the report prints both.
* **The Bourdet derivative** (Bourdet, Ayoub and Pirard 1989), ds/d ln t by
  the weighted central difference over neighbours at least L apart in log
  time, and a reading of the flow regime from the slope of the derivative on
  log-log axes: a unit slope for casing (wellbore) storage, a plateau for
  radial flow, a half slope for linear flow along a fracture, and a fall or a
  rise after the plateau for a boundary (Renard, Glenz and Mejias 2009). The
  slope limits that decide each class are settings in ``defaults.json``,
  because they are judgements a hydrogeologist may want to move.
* **The Papadopulos-Cooper (1967) large-diameter well**, which models the
  water drawn from casing storage instead of discarding the readings taken
  while it lasts. Its Laplace-domain solution at the well face is inverted
  numerically by the Stehfest (1970) algorithm with twelve terms, the
  default of Renard's (2017) hytool; against the closed-form integral of
  Papadopulos and Cooper it agrees to better than 1e-5 relative over
  1/u_w = 1 to 1e6 and alpha = 1e-5 to 0.1 (tests/test_pumping_spread.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
from scipy.special import exp1, k0e, k1e

from ..config import PumpingConfig
from ..text import phrase, phrase_table

MIN_PER_DAY = 1440.0

#: The standard normal quantile at 0.9: a band from the 10th to the 90th
#: percentile is the central value plus and minus this many standard
#: deviations. Written out rather than computed, so both engines use the
#: same digits.
Z_P90 = 1.2815515655446004

#: The percentiles every band in this module is given at.
BAND_QUANTILES = (0.1, 0.5, 0.9)

#: Terms in the Stehfest inversion. Twelve is hytool's default, and against
#: Papadopulos and Cooper's own integral it is good to 1e-5 relative, a
#: thousand times finer than a dipper reads a typical drawdown; sixteen is
#: finer still but amplifies rounding in the Bessel functions a hundredfold.
STEHFEST_TERMS = 12

#: Iterations a Levenberg-Marquardt refit may take. A bootstrap refit starts
#: at the fitted optimum and converges in a handful; the first fit of the
#: large-diameter model starts from a straight-line estimate.
LM_MAX_ITERATIONS = 200

#: A refit stops when an iteration lowers the misfit by less than this
#: fraction of it.
LM_RELATIVE_TOLERANCE = 1e-12

#: Fewer readings than this give no band: a block bootstrap of four
#: readings in blocks of two has six distinct resamples.
BOOTSTRAP_MIN_READINGS = 5

#: The storativity floor the Theis fit refuses below (analysis.py
#: THEIS_STORATIVITY_FLOOR), repeated here so a refit is held to it too.
STORATIVITY_FLOOR = 1e-280


# ---------------------------------------------------------------------------
# A generator both engines draw the same numbers from
# ---------------------------------------------------------------------------

class Mulberry32:
    """Tommy Ettinger's mulberry32, in 32-bit integer arithmetic.

    JavaScript's ``Math.imul`` and unsigned shifts are the reference; every
    operation is masked to 32 bits here so the two produce the same stream
    from the same seed.
    """

    def __init__(self, seed: int) -> None:
        self.state = int(seed) & 0xFFFFFFFF

    def next_float(self) -> float:
        """A float in [0, 1) with 32 random bits."""
        self.state = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.state
        t = _imul(t ^ (t >> 15), t | 1)
        t ^= (t + _imul(t ^ (t >> 7), t | 61)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    def next_index(self, count: int) -> int:
        """An index in ``range(count)``."""
        return int(math.floor(self.next_float() * count))


def _imul(a: int, b: int) -> int:
    return (a * b) & 0xFFFFFFFF


def quantile(values, q: float) -> float:
    """numpy's default ("linear") percentile of ``values`` at ``q`` in [0, 1]."""
    ordered = sorted(float(v) for v in values)
    h = (len(ordered) - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (h - lo) * (ordered[hi] - ordered[lo])


def block_length(n: int) -> int:
    """The smallest whole number whose cube is at least ``n``, and at least 2.

    Counted in integers: ``27 ** (1/3)`` is 3.0000000000000004 in floating
    point, and its ceiling would make the blocks one reading longer.
    """
    length = 1
    while length**3 < n:
        length += 1
    return max(2, length)


def resample_blocks(rng: Mulberry32, residuals: list[float], length: int) -> list[float]:
    """Blocks of consecutive ``residuals`` drawn with replacement, cut to its length.

    The blocks wrap from the last reading to the first (Politis and Romano
    1992). Without the wrap the first and last readings fall in fewer blocks
    than the rest, and the late readings, which set the transmissivity, were
    resampled least: the band came out too narrow.
    """
    n = len(residuals)
    out: list[float] = []
    while len(out) < n:
        start = rng.next_index(n)
        for j in range(length):
            out.append(residuals[(start + j) % n])
    return out[:n]


# ---------------------------------------------------------------------------
# Least squares in two log parameters, the same steps in both engines
# ---------------------------------------------------------------------------

def _dot(a, b) -> float:
    """A sum of products taken left to right, as the browser's loop takes it.

    numpy sums in eight interleaved partial sums, which rounds differently;
    on the flat floor of a poorly fitted valley that difference alone moved
    where the two engines' optimisers stopped by 1e-4 in T.
    """
    total = 0.0
    for u, v in zip(np.asarray(a, dtype=float).tolist(),
                    np.asarray(b, dtype=float).tolist(), strict=True):
        total += u * v
    return total


def _cost(model, x, y, p) -> float:
    res = model(x, p[0], p[1]) - y
    return _dot(res, res)


def lm_log2(model, x, y, p0, max_iterations: int = LM_MAX_ITERATIONS):
    """``(params, cost)``: Levenberg-Marquardt on two parameters.

    The same algorithm as ``theisFit`` in the browser - a forward-difference
    Jacobian, Marquardt's scaling of the diagonal, the damping divided by ten
    on a step that helps and multiplied by ten on one that does not - with the
    2 x 2 system solved by Cramer's rule, so both engines take the same steps.
    It stops when no step helps, when a step lowers the misfit by less than
    LM_RELATIVE_TOLERANCE of it, or after ``max_iterations``.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    p = [float(p0[0]), float(p0[1])]
    lam = 1e-3
    base = model(x, p[0], p[1])
    cost = _dot(base - y, base - y)
    for _ in range(max_iterations):
        h0 = 1e-4 * max(abs(p[0]), 1.0)
        h1 = 1e-4 * max(abs(p[1]), 1.0)
        j0 = (model(x, p[0] + h0, p[1]) - base) / h0
        j1 = (model(x, p[0], p[1] + h1) - base) / h1
        res = base - y
        a00, a01, a11 = _dot(j0, j0), _dot(j0, j1), _dot(j1, j1)
        g0, g1 = _dot(j0, res), _dot(j1, res)
        stepped = False
        previous = cost
        for _attempt in range(20):
            d00 = a00 * (1.0 + lam)
            d11 = a11 * (1.0 + lam)
            det = d00 * d11 - a01 * a01
            if not (math.isfinite(det) and det != 0.0):
                lam *= 10.0
                continue
            trial = [p[0] + (-g0 * d11 + g1 * a01) / det,
                     p[1] + (-g1 * d00 + g0 * a01) / det]
            calc = model(x, trial[0], trial[1])
            ct = _dot(calc - y, calc - y)
            if math.isfinite(ct) and ct < cost:
                p, cost, base = trial, ct, calc
                lam = max(lam / 10.0, 1e-12)
                stepped = True
                break
            lam *= 10.0
            if lam > 1e12:
                break
        if not stepped or previous - cost <= LM_RELATIVE_TOLERANCE * previous:
            break
    return p, cost


def covariance_log2(model, x, y, p) -> list[list[float]] | None:
    """The 2 x 2 covariance of the parameters, as ``curve_fit`` scales it.

    ``inv(J^T J)`` times the residual variance ``cost / (n - 2)``, with the
    Jacobian by central differences. None when the system is singular or
    there are no degrees of freedom left.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    if n <= 2:
        return None
    h0 = 1e-5 * max(abs(p[0]), 1.0)
    h1 = 1e-5 * max(abs(p[1]), 1.0)
    j0 = (model(x, p[0] + h0, p[1]) - model(x, p[0] - h0, p[1])) / (2.0 * h0)
    j1 = (model(x, p[0], p[1] + h1) - model(x, p[0], p[1] - h1)) / (2.0 * h1)
    a00, a01, a11 = _dot(j0, j0), _dot(j0, j1), _dot(j1, j1)
    det = a00 * a11 - a01 * a01
    if not (math.isfinite(det) and det > 0.0):
        return None
    scale = _cost(model, x, y, p) / (n - 2)
    return [[a11 / det * scale, -a01 / det * scale],
            [-a01 / det * scale, a00 / det * scale]]


def pow10(x: float) -> float:
    """``10 ** x`` as the browser's ``Math.pow`` gives it: inf past the largest
    float, where Python's ``**`` raises. A fit can wander that far on a sheet
    no curve describes, and the analysis has to carry on and say so."""
    with np.errstate(all="ignore"):
        return float(np.power(10.0, np.float64(x)))


def log_band(log_value: float, variance: float | None) -> tuple[float | None, float | None]:
    """``10 ** (log_value -/+ Z_P90 sigma)``: P10 and P90 of a log-normal estimate."""
    if variance is None or not (math.isfinite(variance) and variance >= 0.0):
        return None, None
    sigma = math.sqrt(variance)
    return pow10(log_value - Z_P90 * sigma), pow10(log_value + Z_P90 * sigma)


# ---------------------------------------------------------------------------
# The two curves, in log10 T and log10 S
# ---------------------------------------------------------------------------

def theis_model(q_day: float, radius_m: float):
    """``s(t_day; log10 T, log10 S)`` for the Theis well function."""

    def model(t_day, log_t, log_s):
        # numpy scalars, so a step the optimiser tries far off overflows to
        # inf and is refused as it is in the browser, rather than raising
        with np.errstate(all="ignore"):
            transmissivity = np.power(10.0, np.float64(log_t))
            storativity = np.power(10.0, np.float64(log_s))
            u = radius_m**2 * storativity / (4.0 * transmissivity * t_day)
            return q_day / (4.0 * math.pi * transmissivity) * exp1(u)

    return model


def stehfest_weights(n: int = STEHFEST_TERMS) -> list[float]:
    """Stehfest's (1970) coefficients V_1 .. V_n, n even.

    Summed term by term in the order the browser sums them; every factorial
    here is an integer below 2^53, so both engines hold them exactly.
    """
    half = n // 2
    weights = []
    for i in range(1, n + 1):
        total = 0.0
        for k in range((i + 1) // 2, min(i, half) + 1):
            total += (float(k**half) * float(math.factorial(2 * k))) / (
                float(math.factorial(half - k)) * float(math.factorial(k))
                * float(math.factorial(k - 1)) * float(math.factorial(i - k))
                * float(math.factorial(2 * k - i)))
        weights.append(total if (half + i) % 2 == 0 else -total)
    return weights


STEHFEST_WEIGHTS = stehfest_weights()


def pc_dimensionless(t_d: np.ndarray, storage_cd: float) -> np.ndarray:
    """Papadopulos-Cooper drawdown in the well, ``2 pi T s / Q``, at ``t_d``.

    ``t_d = T t / (S r_w^2)`` and ``storage_cd = r_c^2 / (2 r_w^2 S)``, the
    reciprocal of twice Papadopulos and Cooper's alpha. The Laplace transform
    at the well face is ``K0(q) / (p [q K1(q) + C_D p K0(q)])`` with
    ``q = sqrt(p)``; the exponentially scaled Bessel functions keep it finite
    where K0 and K1 themselves underflow, and their common factor cancels.
    """
    t_d = np.asarray(t_d, dtype=float)
    storage_cd = np.float64(storage_cd)
    ln2 = math.log(2.0)
    total = np.zeros_like(t_d)
    for i, weight in enumerate(STEHFEST_WEIGHTS, start=1):
        p = i * ln2 / t_d
        q = np.sqrt(p)
        k0 = k0e(q)
        total = total + weight * (k0 / (p * (q * k1e(q) + storage_cd * p * k0)))
    return ln2 / t_d * total


def pc_well_function(u_w: float, alpha: float) -> float:
    """Papadopulos and Cooper's F(u_w, alpha): ``s_w = Q / (4 pi T) F``."""
    t_d = 1.0 / (4.0 * u_w)
    return float(2.0 * pc_dimensionless(np.array([t_d]), 1.0 / (2.0 * alpha))[0])


def pc_model(q_day: float, radius_m: float, casing_radius_m: float):
    """``s(t_day; log10 T, log10 S)`` in a well of large diameter."""

    def model(t_day, log_t, log_s):
        with np.errstate(all="ignore"):
            transmissivity = np.power(10.0, np.float64(log_t))
            storativity = np.power(10.0, np.float64(log_s))
            t_d = transmissivity * t_day / (storativity * radius_m**2)
            storage_cd = casing_radius_m**2 / (2.0 * radius_m**2 * storativity)
            return (q_day / (2.0 * math.pi * transmissivity)
                    * pc_dimensionless(t_d, storage_cd))

    return model


def casing_radius_m(config: PumpingConfig) -> float | None:
    """The radius of the water surface that falls in the casing, in metres.

    Water stands in the annulus between the casing and the riser, so the
    area that empties is the one Schafer's rule uses, ``dc^2 - dp^2``; the
    radius is that of a circle of the same area.
    """
    dc = config.casing_diameter_in * 0.0254
    dp = config.riser_diameter_in * 0.0254
    area = dc * dc - dp * dp
    return math.sqrt(area) / 2.0 if area > 0 else None


@dataclass
class PapadopulosCooperResult:
    transmissivity_m2_per_day: float
    storativity: float
    storativity_reliable: bool
    rmse_m: float
    discharge_m3_per_h: float
    radius_m: float
    casing_radius_m: float
    #: Papadopulos and Cooper's alpha = r_w^2 S / r_c^2
    alpha: float
    n_points: int
    #: P10 and P90 of T from the fit's covariance, and the covariance itself
    #: of (log10 T, log10 S)
    transmissivity_low_m2_per_day: float | None = None
    transmissivity_high_m2_per_day: float | None = None
    log_covariance: list[list[float]] | None = None


def papadopulos_cooper_fit(
    time_min, drawdown_m, discharge_m3_per_h: float, radius_m: float,
    casing_radius: float, start: tuple[float, float] | None = None,
) -> PapadopulosCooperResult:
    """Fit T and S of a large-diameter well to every reading, casing storage included.

    The readings and the refusals are the Theis fit's: positive times and
    drawdowns, at least five of them, a rise across them a dipper can read,
    and a storativity above the floor. ``start`` is ``(log10 T, log10 S)``;
    without one the fit starts where ``theis_fit`` does.
    """
    from .analysis import READING_RESOLUTION_M, _line_fit, _require_discharge

    _require_discharge(discharge_m3_per_h)
    t = np.asarray(time_min, dtype=float) / MIN_PER_DAY
    s = np.asarray(drawdown_m, dtype=float)
    keep = (t > 0) & (s > 0)
    t, s = t[keep], s[keep]
    if len(t) < 5:
        raise ValueError("Not enough readings for a Papadopulos-Cooper fit")
    log_t = np.log10(t)
    if _line_fit(log_t, s)[0] * float(log_t.max() - log_t.min()) < READING_RESOLUTION_M:
        raise ValueError(
            "The drawdown rises by less than a dipper reads across the readings, "
            "so the large-diameter curve cannot be fitted to it"
        )
    q_day = float(discharge_m3_per_h) * 24.0
    if start is None:
        half = len(s) // 2
        slope0 = max((s[-1] - s[half]) / max(math.log10(t[-1] / t[half]), 0.3), 0.1)
        t0 = 2.303 * q_day / (4.0 * math.pi * slope0)
        start = (math.log10(max(t0, 1e-2)), -3.0)
    model = pc_model(q_day, radius_m, casing_radius)
    p, cost = lm_log2(model, t, s, start)
    transmissivity = pow10(p[0])
    storativity = pow10(p[1])
    if not (math.isfinite(transmissivity) and storativity >= STORATIVITY_FLOOR):
        raise ValueError(
            "The Papadopulos-Cooper fit drives the storativity to the floor, "
            "so T and S cannot be fitted to it"
        )
    covariance = covariance_log2(model, t, s, p)
    low, high = log_band(p[0], covariance[0][0] if covariance else None)
    return PapadopulosCooperResult(
        transmissivity_m2_per_day=transmissivity,
        storativity=storativity,
        storativity_reliable=False,
        rmse_m=math.sqrt(cost / len(t)),
        discharge_m3_per_h=float(discharge_m3_per_h),
        radius_m=radius_m,
        casing_radius_m=casing_radius,
        alpha=radius_m**2 * storativity / casing_radius**2,
        n_points=len(t),
        transmissivity_low_m2_per_day=low,
        transmissivity_high_m2_per_day=high,
        log_covariance=covariance,
    )


# ---------------------------------------------------------------------------
# The block bootstrap of the adopted fit
# ---------------------------------------------------------------------------

@dataclass
class BootstrapResult:
    method: str
    replicates: int
    failed: int
    block_length: int
    seed: int
    n_points: int
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    #: a key of the ``pumping.spread_reasons`` table when no band is given
    reason: str = ""


def _first_step_series(analysis):
    """Times (min) and drawdowns of the first step, as the drawdown fits read them."""
    test = analysis.test
    swl = test.static_water_level_m
    if swl is None or not test.steps:
        return np.array([]), np.array([])
    step = test.steps[0]
    t = np.where(step.time_min <= 0, np.nan, step.time_min).astype(float)
    s = np.asarray(step.water_level_m, dtype=float) - swl
    keep = np.isfinite(t) & np.isfinite(s)
    return t[keep], s[keep]


def fit_series(analysis, method: str):
    """``(x, y, fitted, refit)`` for the readings ``method`` was fitted to.

    ``refit(y)`` returns the transmissivity a fit to new readings at the same
    times gives, or None where the method fails on them.
    """
    if method == "cooper_jacob":
        cj = analysis.cooper_jacob
        t, s = _first_step_series(analysis)
        window = (t >= cj.fit_window_min[0]) & (t <= cj.fit_window_min[1])
        x = np.log10(t[window])
        y = s[window]
        # the line through these readings, fitted here as the browser fits
        # it: the intercept time the result keeps underflows to zero on a
        # line that barely rises, and its logarithm is then no number
        slope, intercept = _line(x, y)
        fitted = slope * x + intercept
        q_day = cj.discharge_m3_per_h * 24.0
        return x, y, fitted, _line_refit(x, q_day)
    if method == "recovery":
        rec = analysis.recovery
        tp = np.asarray(analysis.test.recovery_time_min, dtype=float)
        sp = np.asarray(analysis.test.residual_drawdown(), dtype=float)
        keep = (tp > 0) & np.isfinite(sp)
        x = np.log10((rec.pumping_time_min + tp[keep]) / tp[keep])
        y = sp[keep]
        fitted = rec.slope_m_per_log_cycle * x + rec.intercept_m
        q_day = rec.discharge_m3_per_h * 24.0
        return x, y, fitted, _line_refit(x, q_day)
    # the two curve fits, on the first step's positive drawdowns in days
    t, s = _first_step_series(analysis)
    keep = (t > 0) & (s > 0)
    x = t[keep] / MIN_PER_DAY
    y = s[keep]
    result = analysis.theis if method == "theis" else analysis.papadopulos_cooper
    q_day = result.discharge_m3_per_h * 24.0
    if method == "theis":
        model = theis_model(q_day, result.radius_m)
    else:
        model = pc_model(q_day, result.radius_m, result.casing_radius_m)
    start = (math.log10(result.transmissivity_m2_per_day), math.log10(result.storativity))
    fitted = model(x, *start)
    return x, y, fitted, _curve_refit(model, x, start)


def _line(x, y) -> tuple[float, float]:
    """``(slope, intercept)`` by the closed form, summed left to right."""
    n = len(x)
    ones = np.ones_like(x)
    sx, sy = _dot(x, ones), _dot(y, ones)
    sxx, sxy = _dot(x, x), _dot(x, y)
    den = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / den if den != 0 else 0.0
    return slope, (sy - slope * sx) / n


def _line_refit(x, q_day):
    def refit(y):
        slope = _line(x, y)[0]
        if not slope > 0:
            return None
        return 2.303 * q_day / (4.0 * math.pi * slope)
    return refit


def _curve_refit(model, x, start):
    def refit(y):
        p, _ = lm_log2(model, x, y, start)
        transmissivity = pow10(p[0])
        if not (math.isfinite(transmissivity) and pow10(p[1]) >= STORATIVITY_FLOOR):
            return None
        return transmissivity
    return refit


def bootstrap_fit(analysis, method: str, config: PumpingConfig | None = None) -> BootstrapResult:
    """The P10, P50 and P90 of ``method``'s transmissivity under resampled residuals."""
    config = config or PumpingConfig()
    x, y, fitted, refit = fit_series(analysis, method)
    n = len(y)
    out = BootstrapResult(
        method=method, replicates=int(config.bootstrap_replicates), failed=0,
        block_length=block_length(n), seed=int(config.bootstrap_seed), n_points=n,
    )
    if n < BOOTSTRAP_MIN_READINGS:
        out.reason = "too_few"
        return out
    residuals = [float(v) for v in (y - fitted)]
    mean = sum(residuals) / n
    # Centred, and scaled up by sqrt(n / (n - 2)): a fit of two parameters
    # leaves residuals smaller than the reading errors behind them by that
    # factor on average (Davison and Hinkley 1997, section 6.2.3), and
    # resampling them unscaled gave a band too narrow on eight readings.
    inflate = math.sqrt(n / (n - 2.0))
    residuals = [(r - mean) * inflate for r in residuals]
    rng = Mulberry32(config.bootstrap_seed)
    values = []
    for _ in range(out.replicates):
        draw = resample_blocks(rng, residuals, out.block_length)
        value = refit(fitted + np.asarray(draw))
        if value is None:
            out.failed += 1
        else:
            values.append(value)
    if len(values) * 2 < out.replicates:
        out.reason = "mostly_failed"
        return out
    out.p10, out.p50, out.p90 = (quantile(values, q) for q in BAND_QUANTILES)
    return out


# ---------------------------------------------------------------------------
# The Bourdet derivative and the flow regime
# ---------------------------------------------------------------------------

@dataclass
class Regime:
    key: str  # a key of the pumping.regimes table
    start_min: float
    end_min: float
    slope: float  # median log-log slope of the derivative over the span
    n_points: int


@dataclass
class Diagnostic:
    """The Bourdet derivative of the first step and what it shows."""

    time_min: list[float]
    drawdown_m: list[float]
    derivative_time_min: list[float]
    derivative_m: list[float]  # ds / d ln t
    slopes: list[float | None]  # local log-log slope at each derivative point
    l_log10: float
    regimes: list[Regime] = field(default_factory=list)
    #: T from the radial-flow plateau, Q / (4 pi ds/d ln t), when there is one
    plateau_transmissivity_m2_per_day: float | None = None


def bourdet_derivative(time_min, drawdown_m, l_log10: float):
    """``(t, ds/d ln t)`` by Bourdet's weighted central difference.

    Each point's neighbours are the nearest readings at least ``l_log10``
    log cycles before and after it; a point without one on either side has
    no derivative, rather than a one-sided one that bends the ends of the
    curve.
    """
    t = np.asarray(time_min, dtype=float)
    s = np.asarray(drawdown_m, dtype=float)
    x = np.log(t)
    gap = l_log10 * math.log(10.0)
    out_t, out_d = [], []
    for i in range(len(t)):
        left = i - 1
        while left >= 0 and x[i] - x[left] < gap:
            left -= 1
        right = i + 1
        while right < len(t) and x[right] - x[i] < gap:
            right += 1
        if left < 0 or right >= len(t):
            continue
        dx1 = float(x[i] - x[left])
        dx2 = float(x[right] - x[i])
        d1 = float(s[i] - s[left]) / dx1
        d2 = float(s[right] - s[i]) / dx2
        out_t.append(float(t[i]))
        out_d.append((d1 * dx2 + d2 * dx1) / (dx1 + dx2))
    return out_t, out_d


def _local_slopes(times: list[float], values: list[float], window: float) -> list[float | None]:
    """The least-squares slope of log10 d against log10 t within ``window`` cycles."""
    lx = [math.log10(t) if v > 0 else None for t, v in zip(times, values, strict=True)]
    ly = [math.log10(v) if v > 0 else None for v in values]
    slopes: list[float | None] = []
    for xi in lx:
        if xi is None:
            slopes.append(None)
            continue
        xs, ys = [], []
        for j, xj in enumerate(lx):
            if xj is not None and abs(xj - xi) <= window / 2.0:
                xs.append(xj)
                ys.append(ly[j])
        if len(xs) < 3:
            slopes.append(None)
            continue
        n = len(xs)
        sx, sy = sum(xs), sum(ys)
        sxx = sum(v * v for v in xs)
        sxy = sum(a * b for a, b in zip(xs, ys, strict=True))
        den = n * sxx - sx * sx
        slopes.append((n * sxy - sx * sy) / den if den > 0 else None)
    return slopes


def _slope_class(m: float | None, config: PumpingConfig) -> str | None:
    if m is None:
        return None
    if config.regime_unit_slope_min <= m <= config.regime_unit_slope_max:
        return "unit"
    if config.regime_half_slope_min <= m <= config.regime_half_slope_max:
        return "half"
    if abs(m) <= config.regime_flat_max:
        return "flat"
    if m <= config.regime_falling_max:
        return "falling"
    if m > 0:
        return "rising"
    return None


def classify_regimes(times, values, slopes, config: PumpingConfig) -> list[Regime]:
    """Name the regimes from runs of one slope class along the derivative.

    A run counts when it has three derivative points and spans
    ``diagnostic_min_span_log10`` log cycles. Read in order: a unit slope
    before any plateau is casing storage and after one a closed boundary; a
    half slope is linear flow; a plateau is radial flow; a fall after the
    plateau is a recharge boundary or leakage, and before it the end of the
    storage hump; a rise after the plateau is a no-flow boundary.
    """
    runs: list[tuple[str, list[int]]] = []
    for i, m in enumerate(slopes):
        cls = _slope_class(m, config)
        if cls is not None and runs and runs[-1][0] == cls and runs[-1][1][-1] == i - 1:
            runs[-1][1].append(i)
        elif cls is not None:
            runs.append((cls, [i]))
    regimes: list[Regime] = []
    seen_flat = False
    for cls, members in runs:
        start, end = times[members[0]], times[members[-1]]
        if len(members) < 3 or math.log10(end / start) < config.diagnostic_min_span_log10:
            continue
        if cls == "unit":
            key = "closed_boundary" if seen_flat else "wellbore_storage"
        elif cls == "half":
            key = "linear_flow"
        elif cls == "flat":
            key = "radial_flow"
            seen_flat = True
        elif cls == "falling":
            key = "recharge_boundary" if seen_flat else "storage_ending"
        elif seen_flat:
            key = "no_flow_boundary"
        else:
            continue
        member_slopes = [float(slopes[i]) for i in members]  # type: ignore[arg-type]
        regimes.append(Regime(key=key, start_min=start, end_min=end,
                              slope=quantile(member_slopes, 0.5),
                              n_points=len(members)))
    return regimes


def diagnose(analysis, config: PumpingConfig | None = None) -> Diagnostic | None:
    """The derivative of the first step's drawdown, and the regimes it shows.

    Only the first step: it is pumped at one rate from rest, and a later
    step's derivative carries the earlier rates unless it is superposed.
    None when there are fewer than five positive drawdowns.
    """
    config = config or PumpingConfig()
    t, s = _first_step_series(analysis)
    keep = (t > 0) & (s > 0)
    t, s = t[keep], s[keep]
    order = np.argsort(t, kind="stable")
    t, s = t[order], s[order]
    # a time read twice is one point: the first reading stands
    distinct = np.concatenate([[True], np.diff(t) > 0]) if len(t) else np.array([], bool)
    t, s = t[distinct], s[distinct]
    if len(t) < 5:
        return None
    dt, dd = bourdet_derivative(t, s, config.diagnostic_l_log10)
    slopes = _local_slopes(dt, dd, config.diagnostic_window_log10)
    out = Diagnostic(
        time_min=[float(v) for v in t], drawdown_m=[float(v) for v in s],
        derivative_time_min=dt, derivative_m=dd, slopes=slopes,
        l_log10=config.diagnostic_l_log10,
        regimes=classify_regimes(dt, dd, slopes, config),
    )
    q = analysis.test.steps[0].discharge_m3_per_h
    radial = next((r for r in out.regimes if r.key == "radial_flow"), None)
    if radial is not None and q:
        plateau = [d for tt, d in zip(dt, dd, strict=True)
                   if radial.start_min <= tt <= radial.end_min and d > 0]
        if plateau:
            out.plateau_transmissivity_m2_per_day = (
                float(q) * 24.0 / (4.0 * math.pi * quantile(plateau, 0.5)))
    return out


def diagnostic_thresholds_text(config: PumpingConfig | None = None) -> str:
    """The slope limits that name each regime, for a hydrogeologist to check."""
    config = config or PumpingConfig()
    return phrase(
        "pumping.diagnostic_thresholds",
        unit_min=config.regime_unit_slope_min, unit_max=config.regime_unit_slope_max,
        half_min=config.regime_half_slope_min, half_max=config.regime_half_slope_max,
        flat=config.regime_flat_max, falling=config.regime_falling_max,
        span=config.diagnostic_min_span_log10,
    )


def diagnostic_text(diagnostic: Diagnostic | None) -> str:
    """One paragraph: the derivative's method and the regimes it names."""
    if diagnostic is None:
        return phrase("pumping.diagnostic_none")
    words = phrase_table("pumping.regimes")
    spans = [
        phrase("pumping.regime_span", what=words[r.key], start=r.start_min,
               end=r.end_min, slope=r.slope)
        for r in diagnostic.regimes
    ]
    text = phrase("pumping.diagnostic_method", l=diagnostic.l_log10)
    if not spans:
        return text + " " + phrase("pumping.diagnostic_unnamed")
    text += " " + phrase("pumping.diagnostic_shows", spans="; ".join(spans))
    if diagnostic.plateau_transmissivity_m2_per_day is not None:
        text += " " + phrase("pumping.diagnostic_plateau",
                             t=diagnostic.plateau_transmissivity_m2_per_day)
    return text


# ---------------------------------------------------------------------------
# The yield and the pump setting as bands
# ---------------------------------------------------------------------------

#: The dry-season declines the pump setting band spans: the ends of the
#: range the yield envelope already takes (analysis._ENVELOPE_SEASONAL_M).
def _seasonal_range():
    from .analysis import _ENVELOPE_SEASONAL_M
    return _ENVELOPE_SEASONAL_M


@dataclass
class PumpingSpread:
    """The bands a report prints beside the central figures."""

    bootstrap: BootstrapResult | None = None
    #: the safe yield at the P10 and P90 transmissivity, with the dry-season
    #: reserve taken, widened to include the central figure; None at an end
    #: where the projection gives no yield
    safe_yield_low_m3_per_h: float | None = None
    safe_yield_high_m3_per_h: float | None = None
    #: the long-term yield (before the safety factor) at the P10
    #: transmissivity and the dry-season level
    long_term_low_m3_per_h: float | None = None
    #: True when that long-term yield still covers the recommended rate: the
    #: safety factor absorbs the spread in the data at the dry-season level
    holds_at_dry_season: bool = False
    pump_depth_low_m: float | None = None
    pump_depth_high_m: float | None = None


def attach_spread(analysis, config: PumpingConfig | None = None) -> None:
    """Bootstrap the adopted fit and turn its band into yield and pump bands.

    The central yield and pump setting are the analysis's own and are not
    moved; each band is widened to include its central figure, as the
    yield envelope is. The yield is projected, as the central one is, with
    the static level lowered by the dry-season reserve.
    """
    from .analysis import recommend_yield

    config = config or PumpingConfig()
    spread = PumpingSpread()
    analysis.spread = spread
    method = analysis.transmissivity_source
    recommendation = analysis.yield_recommendation
    if method is None:
        return
    spread.bootstrap = bootstrap_fit(analysis, method, config)
    if recommendation is None or recommendation.safe_yield_m3_per_h is None:
        return
    central = recommendation.safe_yield_m3_per_h
    boot = spread.bootstrap
    if boot.p10 is not None and boot.p90 is not None:
        low = recommend_yield(analysis.test, boot.p10, analysis.step_test, config)
        high = recommend_yield(analysis.test, boot.p90, analysis.step_test, config)
        if low.safe_yield_m3_per_h is not None:
            spread.safe_yield_low_m3_per_h = min(low.safe_yield_m3_per_h, central)
            spread.long_term_low_m3_per_h = low.long_term_yield_m3_per_h
        if high.safe_yield_m3_per_h is not None:
            spread.safe_yield_high_m3_per_h = max(high.safe_yield_m3_per_h, central)
        spread.holds_at_dry_season = (
            spread.long_term_low_m3_per_h is not None
            and spread.long_term_low_m3_per_h >= central
        )
    depths = [recommendation.pump_installation_depth_m]
    for decline in _seasonal_range():
        variant = replace(config, seasonal_allowance_m=decline)
        trial = recommend_yield(analysis.test, analysis.transmissivity_m2_per_day,
                                analysis.step_test, variant)
        depths.append(trial.pump_installation_depth_m)
    depths = [d for d in depths if d is not None]
    if depths:
        spread.pump_depth_low_m = float(min(depths))
        spread.pump_depth_high_m = float(max(depths))


def spread_paragraphs(analysis, config: PumpingConfig | None = None) -> list[str]:
    """The sentences every report and both apps print about the bands."""
    from .analysis import METHOD_LABELS

    config = config or PumpingConfig()
    spread = getattr(analysis, "spread", None)
    if spread is None or spread.bootstrap is None:
        return []
    boot = spread.bootstrap
    out = []
    method = METHOD_LABELS[boot.method]
    if boot.p10 is None:
        reasons = phrase_table("pumping.spread_reasons")
        out.append(phrase("pumping.spread_withheld", method=method,
                          reason=reasons[boot.reason]))
    else:
        out.append(phrase(
            "pumping.spread_transmissivity", low=boot.p10, high=boot.p90,
            method=method, replicates=boot.replicates, n=boot.n_points,
            block=boot.block_length,
        ))
        if boot.failed:
            out.append(phrase("pumping.spread_failed", failed=boot.failed))
    rec = analysis.yield_recommendation
    if (rec is not None and rec.safe_yield_m3_per_h is not None
            and spread.safe_yield_low_m3_per_h is not None):
        if spread.safe_yield_high_m3_per_h is None:
            out.append(phrase("pumping.spread_yield_open",
                              low=spread.safe_yield_low_m3_per_h,
                              reserve=config.seasonal_allowance_m))
        else:
            out.append(phrase("pumping.spread_yield",
                              low=spread.safe_yield_low_m3_per_h,
                              high=spread.safe_yield_high_m3_per_h,
                              reserve=config.seasonal_allowance_m))
        out.append(phrase(
            "pumping.spread_holds" if spread.holds_at_dry_season
            else "pumping.spread_does_not_hold",
            long_term=spread.long_term_low_m3_per_h, rate=rec.safe_yield_m3_per_h))
    if spread.pump_depth_low_m is not None:
        low_decline, high_decline = _seasonal_range()
        out.append(phrase("pumping.spread_pump", low=spread.pump_depth_low_m,
                          high=spread.pump_depth_high_m,
                          decline_low=low_decline, decline_high=high_decline))
    theis = analysis.theis
    if theis is not None and theis.transmissivity_low_m2_per_day is not None:
        out.append(phrase("pumping.theis_covariance",
                          low=theis.transmissivity_low_m2_per_day,
                          high=theis.transmissivity_high_m2_per_day))
    return out


def papadopulos_cooper_text(analysis) -> str:
    """The large-diameter fit in one paragraph, or an empty string."""
    pc = getattr(analysis, "papadopulos_cooper", None)
    if pc is None:
        return ""
    text = phrase(
        "pumping.pc_fit", t=pc.transmissivity_m2_per_day, rc=pc.casing_radius_m,
        n=pc.n_points, rmse=pc.rmse_m,
    )
    if analysis.transmissivity_source == "papadopulos_cooper":
        return text + " " + phrase("pumping.pc_adopted")
    why = analysis.papadopulos_cooper_invalid
    if why:
        return text + " " + phrase("pumping.pc_invalid", why=why)
    return text + " " + phrase("pumping.pc_reported")


def sustainable_sentence(recommendation, spread) -> str | None:
    """The completion report's sentence on an established yield, or None.

    "Sustainable" is said only where the yield's band holds at the
    dry-season level: the long-term yield at the low end of the
    transmissivity band, with the dry-season reserve taken, still covers the
    recommended rate. None for an indicative or pending yield, which the
    report words as before.
    """
    if recommendation is None or not recommendation.safe_yield_m3_per_h:
        return None
    if recommendation.is_indicative:
        return None
    if spread is not None and spread.holds_at_dry_season:
        return phrase("pumping.sustainable")
    return phrase("pumping.sustainable_not_held")

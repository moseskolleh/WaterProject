"""Pumping test analysis methods.

All methods work on non-uniform time series (the sheets record 1, 2, 3
and 5 minute spacings) and true drawdown recomputed from water level
minus static water level. Internally time is converted to days and
discharge to m3/day so transmissivity comes out in m2/day.

Methods
-------
* Cooper-Jacob straight line on drawdown against log time, with the
  u < u_max validity check and automatic late time window selection.
* Theis type curve fitting of W(u) by least squares. In a single
  pumped well storativity is not resolvable (it trades off against the
  effective well radius), so S is reported with a reliability warning
  unless an observation well distance is given.
* Theis recovery: residual drawdown against log(t/t').
* Hantush-Bierschenk step test analysis: s_w/Q against Q gives the
  aquifer loss coefficient B and well loss coefficient C, well
  efficiency per step, and the drawdown-yield relationship.
* Specific capacity, safe yield with an explicit safety factor, and a
  recommended pump installation depth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import exp1

from ..config import PumpingConfig
from ..models import DataFlag, PumpingTest

MIN_PER_DAY = 1440.0


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class CooperJacobResult:
    transmissivity_m2_per_day: float
    slope_m_per_log_cycle: float
    intercept_t0_min: float  # time where the fitted line crosses s = 0
    storativity: Optional[float]  # only when an observation distance is given
    fit_window_min: tuple[float, float]
    n_points: int
    r_squared: float
    u_check: str  # narrative of the validity check
    discharge_m3_per_h: float


@dataclass
class TheisResult:
    transmissivity_m2_per_day: float
    storativity: float
    storativity_reliable: bool
    rmse_m: float
    discharge_m3_per_h: float
    radius_m: float


@dataclass
class RecoveryResult:
    transmissivity_m2_per_day: float
    slope_m_per_log_cycle: float
    n_points: int
    r_squared: float
    discharge_m3_per_h: float
    residual_at_end_m: float


@dataclass
class StepTestResult:
    aquifer_loss_B: float  # s = B Q + C Q^2 with Q in m3/day, s in m
    well_loss_C: float
    steps: list[dict]  # per step: Q, s_end, sw/Q, efficiency %
    r_squared: float

    def drawdown_at(self, q_m3_per_day: float) -> float:
        return self.aquifer_loss_B * q_m3_per_day + self.well_loss_C * q_m3_per_day**2

    def efficiency_at(self, q_m3_per_day: float) -> float:
        s_total = self.drawdown_at(q_m3_per_day)
        if s_total <= 0:
            return 100.0
        return 100.0 * self.aquifer_loss_B * q_m3_per_day / s_total


@dataclass
class YieldRecommendation:
    specific_capacity_m3hr_per_m: Optional[float]
    available_drawdown_m: Optional[float]
    usable_drawdown_m: Optional[float]
    projected_drawdown_m: Optional[float]
    long_term_yield_m3_per_h: Optional[float]
    safe_yield_m3_per_h: Optional[float]
    safety_factor: float
    design_period_days: float
    pump_installation_depth_m: Optional[float]
    basis: str  # narrative of how the recommendation was derived
    pending_reason: str = ""  # non-empty when discharge or SWL is missing


@dataclass
class PumpingTestAnalysis:
    test: PumpingTest
    cooper_jacob: Optional[CooperJacobResult] = None
    theis: Optional[TheisResult] = None
    recovery: Optional[RecoveryResult] = None
    step_test: Optional[StepTestResult] = None
    yield_recommendation: Optional[YieldRecommendation] = None
    stabilised_level_m: Optional[float] = None
    max_drawdown_m: Optional[float] = None
    flags: list[DataFlag] = field(default_factory=list)

    @property
    def transmissivity_m2_per_day(self) -> Optional[float]:
        """Preferred transmissivity: recovery is least affected by well
        losses, then Cooper-Jacob, then Theis."""
        for result in (self.recovery, self.cooper_jacob, self.theis):
            if result is not None:
                return result.transmissivity_m2_per_day
        return None


# ---------------------------------------------------------------------------
# Individual methods
# ---------------------------------------------------------------------------

def _line_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Least squares line with r^2."""
    A = np.vstack([x, np.ones_like(x)]).T
    coef, res, *_ = np.linalg.lstsq(A, y, rcond=None)
    slope, intercept = float(coef[0]), float(coef[1])
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(np.sum((y - (slope * x + intercept)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return slope, intercept, r2


def cooper_jacob(
    time_min: np.ndarray,
    drawdown_m: np.ndarray,
    discharge_m3_per_h: float,
    config: PumpingConfig | None = None,
    fit_window_min: tuple[float, float] | None = None,
    observation_radius_m: float | None = None,
    assumed_storativity: float = 1e-3,
) -> CooperJacobResult:
    """Cooper-Jacob straight line analysis.

    With no explicit window the fit uses the last full log cycle of
    data (at least 6 points), which is where u is smallest and the
    approximation holds. The u criterion is evaluated afterwards with
    the fitted T (and an assumed S for the pumped well) and reported.
    """
    config = config or PumpingConfig()
    t = np.asarray(time_min, dtype=float)
    s = np.asarray(drawdown_m, dtype=float)
    keep = (t > 0) & np.isfinite(s)
    t, s = t[keep], s[keep]
    if len(t) < 4:
        raise ValueError("Not enough readings for a Cooper-Jacob fit")

    if fit_window_min is None:
        t_end = t.max()
        t_start = max(t_end / 10.0, t.min())
        window = (t >= t_start)
        if window.sum() < 6:
            window = np.argsort(t) >= max(len(t) - 6, 0)
        fit_window_min = (float(t[window].min()), float(t[window].max()))
    else:
        window = (t >= fit_window_min[0]) & (t <= fit_window_min[1])

    slope, intercept, r2 = _line_fit(np.log10(t[window]), s[window])
    if slope <= 0:
        raise ValueError(
            "Drawdown does not increase with log time; Cooper-Jacob does not apply"
        )
    q_day = discharge_m3_per_h * 24.0
    T = 2.303 * q_day / (4.0 * math.pi * slope)
    t0_min = 10 ** (-intercept / slope)

    storativity = None
    if observation_radius_m is not None:
        t0_day = t0_min / MIN_PER_DAY
        storativity = 2.25 * T * t0_day / observation_radius_m**2

    # validity: u = r^2 S / (4 T t) at the start of the fit window
    r_eff = observation_radius_m if observation_radius_m else 0.1
    S_eff = storativity if storativity else assumed_storativity
    u_start = r_eff**2 * S_eff / (4.0 * T * (fit_window_min[0] / MIN_PER_DAY))
    if u_start < config.cooper_jacob_u_max:
        u_check = (
            f"u = {u_start:.2e} at the start of the fitted window, below the "
            f"{config.cooper_jacob_u_max} criterion; the straight line "
            "approximation is valid"
        )
    else:
        u_check = (
            f"u = {u_start:.2e} at the start of the fitted window exceeds "
            f"{config.cooper_jacob_u_max}; early data were excluded or results "
            "should be treated with caution"
        )

    return CooperJacobResult(
        transmissivity_m2_per_day=T,
        slope_m_per_log_cycle=slope,
        intercept_t0_min=t0_min,
        storativity=storativity,
        fit_window_min=fit_window_min,
        n_points=int(window.sum()),
        r_squared=r2,
        u_check=u_check,
        discharge_m3_per_h=discharge_m3_per_h,
    )


def theis_fit(
    time_min: np.ndarray,
    drawdown_m: np.ndarray,
    discharge_m3_per_h: float,
    radius_m: float = 0.1,
    observation_well: bool = False,
) -> TheisResult:
    """Least squares fit of the Theis well function.

    ``s = Q / (4 pi T) W(u)``, ``u = r^2 S / (4 T t)``. Fitting is done
    in log parameter space to keep T and S positive.
    """
    t = np.asarray(time_min, dtype=float) / MIN_PER_DAY
    s = np.asarray(drawdown_m, dtype=float)
    keep = (t > 0) & (s > 0)
    t, s = t[keep], s[keep]
    if len(t) < 5:
        raise ValueError("Not enough readings for a Theis fit")
    q_day = discharge_m3_per_h * 24.0

    def model(tt, logT, logS):
        T = 10.0**logT
        S = 10.0**logS
        u = radius_m**2 * S / (4.0 * T * tt)
        return q_day / (4.0 * math.pi * T) * exp1(u)

    # start from a Cooper-Jacob style estimate
    slope0 = max((s[-1] - s[len(s) // 2]) / max(np.log10(t[-1] / t[len(s) // 2]), 0.3), 0.1)
    T0 = 2.303 * q_day / (4.0 * math.pi * slope0)
    p0 = (math.log10(max(T0, 1e-2)), -3.0)
    popt, _ = curve_fit(model, t, s, p0=p0, maxfev=20000)
    T = 10.0 ** popt[0]
    S = 10.0 ** popt[1]
    rmse = float(np.sqrt(np.mean((model(t, *popt) - s) ** 2)))
    return TheisResult(
        transmissivity_m2_per_day=T,
        storativity=S,
        storativity_reliable=bool(observation_well),
        rmse_m=rmse,
        discharge_m3_per_h=discharge_m3_per_h,
        radius_m=radius_m,
    )


def theis_recovery(
    recovery_time_min: np.ndarray,
    residual_drawdown_m: np.ndarray,
    pumping_duration_min: float,
    discharge_m3_per_h: float,
) -> RecoveryResult:
    """Theis recovery analysis on residual drawdown against t/t'.

    ``s' = 2.303 Q / (4 pi T) log10(t/t')`` with t measured since
    pumping started and t' since it stopped.
    """
    tp = np.asarray(recovery_time_min, dtype=float)  # t'
    sp = np.asarray(residual_drawdown_m, dtype=float)
    keep = (tp > 0) & np.isfinite(sp)
    tp, sp = tp[keep], sp[keep]
    if len(tp) < 4:
        raise ValueError("Not enough recovery readings")
    ratio = (pumping_duration_min + tp) / tp
    slope, _, r2 = _line_fit(np.log10(ratio), sp)
    if slope <= 0:
        raise ValueError("Residual drawdown does not decrease; check the data")
    q_day = discharge_m3_per_h * 24.0
    T = 2.303 * q_day / (4.0 * math.pi * slope)
    return RecoveryResult(
        transmissivity_m2_per_day=T,
        slope_m_per_log_cycle=slope,
        n_points=len(tp),
        r_squared=r2,
        discharge_m3_per_h=discharge_m3_per_h,
        residual_at_end_m=float(sp[-1]),
    )


def hantush_bierschenk(
    step_discharges_m3_per_h: list[float],
    step_end_drawdowns_m: list[float],
) -> StepTestResult:
    """Hantush-Bierschenk analysis of a step drawdown test.

    Fits ``s_w = B Q + C Q^2`` through the end-of-step drawdowns by
    linear regression of s_w/Q on Q. Q is converted to m3/day, so B is
    in day/m2 and C in day2/m5.
    """
    q = np.asarray(step_discharges_m3_per_h, dtype=float) * 24.0
    s = np.asarray(step_end_drawdowns_m, dtype=float)
    if len(q) < 2:
        raise ValueError("A step test needs at least two steps with discharge")
    sq = s / q
    C, B, r2 = _line_fit(q, sq)
    if C < 0:
        # negative well loss has no physical meaning; fall back to pure
        # aquifer loss
        C = 0.0
        B = float(np.mean(sq))
    steps = []
    for i, (qi, si) in enumerate(zip(q, s), start=1):
        eff = 100.0 * B * qi / (B * qi + C * qi**2) if (B * qi + C * qi**2) > 0 else 100.0
        steps.append(
            {
                "step": i,
                "discharge_m3_per_h": qi / 24.0,
                "drawdown_end_m": float(si),
                "sw_over_q_day_per_m2": float(si / qi),
                "efficiency_percent": float(eff),
            }
        )
    return StepTestResult(aquifer_loss_B=float(B), well_loss_C=float(C), steps=steps, r_squared=r2)


# ---------------------------------------------------------------------------
# Yield recommendation
# ---------------------------------------------------------------------------

def recommend_yield(
    test: PumpingTest,
    transmissivity: Optional[float],
    step_result: Optional[StepTestResult],
    config: PumpingConfig | None = None,
    assumed_storativity: float = 1e-3,
    effective_radius_m: float = 0.1,
) -> YieldRecommendation:
    """Specific capacity, sustainable yield and pump depth.

    The long term yield solves ``s_proj(Q) = f_avail x s_available``
    where ``s_proj`` projects Cooper-Jacob drawdown to the design
    period with the fitted T (plus well losses when a step test is
    available). The stated safety factor is then applied. Every input
    is recorded in ``basis`` so the recommendation is traceable.
    """
    config = config or PumpingConfig()
    swl = test.static_water_level_m

    # observed end-of-test state
    q_last = None
    s_end = None
    if test.steps:
        last = test.steps[-1]
        q_last = last.discharge_m3_per_h
        if swl is not None:
            s_end = float(last.water_level_m[-1] - swl)

    specific_capacity = None
    if q_last and s_end and s_end > 0:
        specific_capacity = q_last / s_end

    # available drawdown: static level to pump intake less a submergence margin
    available = None
    if swl is not None and test.pump_setting_m is not None:
        available = test.pump_setting_m - swl - config.pump_submergence_min_m
    elif swl is not None and test.borehole_depth_m is not None:
        available = test.borehole_depth_m - swl - config.pump_submergence_min_m - 3.0

    # Reserve the dry-season water-table decline before taking the usable
    # fraction. A test run in the rains sits on a higher static level than
    # the borehole will see at the end of the dry season, so the raw
    # available drawdown would over-state the sustainable yield.
    # seasonal_allowance_m is the expected wet-to-dry decline (configurable
    # per district); it is already applied to the pump-setting depth below.
    usable = (
        max(available - config.seasonal_allowance_m, 0.0)
        * config.available_drawdown_fraction
        if available
        else None
    )

    if transmissivity is None or swl is None:
        reason = (
            "discharge is missing on the field sheet"
            if transmissivity is None
            else "static water level is missing"
        )
        return YieldRecommendation(
            specific_capacity_m3hr_per_m=specific_capacity,
            available_drawdown_m=available,
            usable_drawdown_m=usable,
            projected_drawdown_m=None,
            long_term_yield_m3_per_h=None,
            safe_yield_m3_per_h=None,
            safety_factor=config.safety_factor,
            design_period_days=config.design_period_days,
            pump_installation_depth_m=None,
            basis="Yield recommendation pending: " + reason + ".",
            pending_reason=reason,
        )

    t_design = config.design_period_days
    log_term = math.log10(
        2.25 * transmissivity * t_design / (effective_radius_m**2 * assumed_storativity)
    )

    def projected_drawdown(q_m3_per_h: float) -> float:
        q_day = q_m3_per_h * 24.0
        s = 2.303 * q_day / (4.0 * math.pi * transmissivity) * log_term
        if step_result is not None:
            # B Q + C Q^2 reflects drawdown at the step duration; add the
            # Cooper-Jacob time projection from step length to design period
            t_step_min = test.step_length_min or test.pumping_duration_min or 180.0
            s = step_result.drawdown_at(q_day)
            s += (
                2.303
                * q_day
                / (4.0 * math.pi * transmissivity)
                * math.log10(t_design / (t_step_min / MIN_PER_DAY))
            )
        return s

    long_term = None
    if usable and usable > 0:
        # bisect Q so projected drawdown equals the usable drawdown
        q_lo, q_hi = 0.01, 200.0
        for _ in range(80):
            q_mid = 0.5 * (q_lo + q_hi)
            if projected_drawdown(q_mid) > usable:
                q_hi = q_mid
            else:
                q_lo = q_mid
        long_term = q_lo

    safe = long_term / config.safety_factor if long_term else None

    pump_depth = None
    if safe is not None:
        s_at_safe = projected_drawdown(safe)
        pump_depth = swl + s_at_safe + config.seasonal_allowance_m + config.pump_submergence_min_m
        if test.borehole_depth_m:
            pump_depth = min(pump_depth, test.borehole_depth_m - 3.0)
        pump_depth = math.ceil(pump_depth)

    basis = (
        f"Transmissivity {transmissivity:.1f} m2/day; drawdown projected to "
        f"{t_design:.0f} days with storativity assumed {assumed_storativity:g} and "
        f"effective radius {effective_radius_m} m; usable drawdown taken as "
        f"{config.available_drawdown_fraction:.0%} of the available drawdown"
        + (
            f" {available:.1f} m (static level to pump intake less "
            f"{config.pump_submergence_min_m:.0f} m submergence), after "
            f"reserving a {config.seasonal_allowance_m:.0f} m dry-season "
            "water-table decline"
            if available
            else ""
        )
        + (
            "; well losses from the step test are included"
            if step_result is not None
            else ""
        )
        + f". A safety factor of {config.safety_factor} is applied to the long "
        "term yield."
    )
    return YieldRecommendation(
        specific_capacity_m3hr_per_m=specific_capacity,
        available_drawdown_m=available,
        usable_drawdown_m=usable,
        projected_drawdown_m=projected_drawdown(safe) if safe else None,
        long_term_yield_m3_per_h=long_term,
        safe_yield_m3_per_h=safe,
        safety_factor=config.safety_factor,
        design_period_days=t_design,
        pump_installation_depth_m=pump_depth,
        basis=basis,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def analyse_pumping_test(
    test: PumpingTest,
    config: PumpingConfig | None = None,
    observation_radius_m: float | None = None,
) -> PumpingTestAnalysis:
    """Run every applicable analysis on a parsed pumping test.

    Methods that need missing inputs (discharge, static level) are
    skipped with a flag instead of failing, so partially filled sheets
    still produce curves and a report skeleton.
    """
    config = config or PumpingConfig()
    analysis = PumpingTestAnalysis(test=test)
    # drop parse-time discharge flags that the analyst has since resolved
    flags = [
        f
        for f in test.flags
        if not (
            f.code in ("missing_discharge", "discharge_ambiguous")
            and all(s.discharge_m3_per_h is not None for s in test.steps)
        )
    ]
    swl = test.static_water_level_m

    if test.steps and swl is not None:
        last = test.steps[-1]
        analysis.max_drawdown_m = float(np.nanmax(last.water_level_m) - swl)
        tail = last.water_level_m[-3:]
        if len(tail) >= 2 and (np.max(tail) - np.min(tail)) <= 0.05:
            analysis.stabilised_level_m = float(np.mean(tail))

    # ---- Cooper-Jacob and Theis on the first step -----------------------------
    # The first step pumps at a single rate from static conditions, so the
    # single well solutions apply directly (later steps would need
    # superposition of the earlier rates).
    if swl is not None and test.steps:
        step = test.steps[0]
        q = step.discharge_m3_per_h
        if q is not None:
            t = np.where(step.time_min <= 0, np.nan, step.time_min)
            s = test.drawdown(step)
            keep = np.isfinite(t) & np.isfinite(s)
            try:
                analysis.cooper_jacob = cooper_jacob(
                    t[keep], s[keep], q, config,
                    observation_radius_m=observation_radius_m,
                )
            except ValueError as exc:
                flags.append(DataFlag("warning", "cooper_jacob_failed", str(exc)))
            try:
                analysis.theis = theis_fit(
                    t[keep], s[keep], q,
                    observation_well=observation_radius_m is not None,
                    radius_m=observation_radius_m or 0.1,
                )
            except (ValueError, RuntimeError) as exc:
                flags.append(DataFlag("warning", "theis_failed", str(exc)))

    # ---- recovery -----------------------------------------------------------
    residual = test.residual_drawdown()
    if residual is not None and test.recovery_time_min is not None:
        q_rec = None
        for step in reversed(test.steps):
            if step.discharge_m3_per_h is not None:
                q_rec = step.discharge_m3_per_h
                break
        if q_rec is not None and test.pumping_duration_min:
            try:
                analysis.recovery = theis_recovery(
                    test.recovery_time_min, residual, test.pumping_duration_min, q_rec
                )
            except ValueError as exc:
                flags.append(DataFlag("warning", "recovery_failed", str(exc)))

    # ---- step test ----------------------------------------------------------
    if test.test_type.startswith("step") and swl is not None and len(test.steps) >= 2:
        with_q = [s for s in test.steps if s.discharge_m3_per_h is not None]
        if len(with_q) >= 2:
            try:
                analysis.step_test = hantush_bierschenk(
                    [s.discharge_m3_per_h for s in with_q],
                    [float(s.water_level_m[-1] - swl) for s in with_q],
                )
            except ValueError as exc:
                flags.append(DataFlag("warning", "step_test_failed", str(exc)))
        else:
            flags.append(
                DataFlag(
                    "warning",
                    "step_test_pending",
                    "Step test analysis pending: discharge per step is missing.",
                )
            )

    # ---- yield ---------------------------------------------------------------
    analysis.yield_recommendation = recommend_yield(
        test,
        analysis.transmissivity_m2_per_day,
        analysis.step_test,
        config,
    )

    analysis.flags = flags
    return analysis

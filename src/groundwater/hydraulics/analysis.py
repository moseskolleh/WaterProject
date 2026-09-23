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
from dataclasses import dataclass, field, replace
from typing import Optional

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import exp1

from ..config import PumpingConfig
from ..models import DataFlag, PumpingTest
from ..utils import plural

MIN_PER_DAY = 1440.0

#: How each transmissivity method is named in reports, keyed by the
#: ``transmissivity_source`` an analysis adopts.
METHOD_LABELS = {
    "recovery": "Theis recovery",
    "cooper_jacob": "Cooper-Jacob",
    "theis": "Theis curve fit",
}

#: Schafer's (1978) casing-storage rule, ``t_c = 0.6 (dc^2 - dp^2) / (Q/s)``
#: minutes with the diameters in inches and Q/s in gpm/ft, restated for
#: diameters in metres and Q/s in m3/h per m: 0.6 x 39.37^2 / 1.342.
CASING_STORAGE_COEFFICIENT = 693.0

#: The words for a field sheet's test type token. The sheets say "step" or
#: "constant" and the parser appends "+recovery" when a recovery limb was
#: recorded; a report prints the phrase, never the token.
TEST_TYPE_WORDS = {
    "step": "step drawdown test",
    "constant": "constant discharge test",
}


def test_type_text(test_type: str) -> str:
    """``"constant+recovery"`` -> ``"constant discharge test with recovery"``."""
    base, _, tail = str(test_type or "").partition("+")
    words = TEST_TYPE_WORDS.get(base.strip().lower(), f"{base.strip() or 'pumping'} test")
    return words + (" with recovery" if tail else "")


#: Flags that say the recorded levels cannot all be right: a level above the
#: stated static level, below the bottom of the hole or below the pump intake.
#: A report used to certify "the drawdown and recovery curves are valid" over
#: levels 18 m below the pump intake, and the yield computed from those
#: drawdowns was called established.
LEVEL_FLAGS = ("water_level_above_static", "level_below_borehole", "level_below_pump")

#: The confidence reason a flagged set of levels gives the yield.
LEVELS_IN_DOUBT_REASON = (
    "the recorded water levels are inconsistent with the stated static level, "
    "pump setting or borehole depth, so the drawdowns the yield is computed "
    "from are as recorded and not to be relied on"
)


def levels_in_doubt(test: PumpingTest) -> bool:
    """True when the sheet's own levels contradict its static level, pump or depth."""
    return any(f.code in LEVEL_FLAGS for f in test.flags)


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
    # theory puts the line through the origin at t/t' = 1; the fitted line
    # generally does not, and the figure has to draw the line that was fitted
    intercept_m: float = 0.0
    # the pumping time t/t' was formed with: the pumped duration of a constant
    # test, or the discharge-weighted equivalent time after a step test
    pumping_time_min: float = 0.0
    equivalent_time: bool = False
    # |intercept| as a fraction of the residual drawdown the recovery started
    # from; theory says zero, and a large one says the line is not a Theis
    # recovery line
    intercept_fraction: float = 0.0


@dataclass
class StepTestResult:
    aquifer_loss_B: float  # s = B Q + C Q^2 with Q in m3/day, s in m
    well_loss_C: float
    steps: list[dict]  # per step: Q, s_end, sw/Q, efficiency %
    r_squared: float
    # set when a coefficient came out negative and the fit was redone with it
    # pinned at zero: the efficiencies are then an artefact of the refit, and
    # the report has to say so instead of printing them
    fit_note: str = ""
    # a line through two points is exact by construction: R squared is 1.000
    # whatever the data, and B, C and the efficiencies are untested
    two_point: bool = False

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
    # plausible range of the safe yield over the assumptions it rests on
    # (transmissivity, storativity, effective radius, seasonal allowance)
    safe_yield_low_m3_per_h: Optional[float] = None
    safe_yield_high_m3_per_h: Optional[float] = None
    envelope_basis: str = ""
    # "established" or "indicative", with the reasons in the reader's words:
    # a short test, a test inside its casing-storage period, a transmissivity
    # no method fitted to standard. Every report that prints the yield prints
    # this beside it, so a 30-minute test cannot become "sustainable" on the
    # handover certificate.
    confidence: str = "established"
    confidence_reasons: list[str] = field(default_factory=list)
    # the rate, drawdown and time the specific capacity was measured at
    specific_capacity_basis: str = ""
    # how the pump intake depth was arrived at, and the deepest level the test
    # itself reached
    pump_depth_basis: str = ""
    deepest_pumping_level_m: Optional[float] = None

    @property
    def is_indicative(self) -> bool:
        return self.confidence == "indicative"

    @property
    def confidence_text(self) -> str:
        """One sentence for a report: what the yield rests on."""
        if self.safe_yield_m3_per_h is None:
            return ""
        if not self.is_indicative:
            return (
                "The yield is established: the test ran long enough to show the "
                "aquifer's late-time behaviour and the adopted transmissivity "
                "fit to standard."
            )
        return (
            "The yield is indicative, not established: "
            + "; ".join(self.confidence_reasons)
            + ". Confirm it by a longer test or by monitoring the pumping level "
            "in service before it is relied on."
        )

    @property
    def yield_range_text(self) -> str:
        """"2.4 m3/h (1.8 to 3.1)" - never a bare number for an assumed one."""
        if self.safe_yield_m3_per_h is None:
            return "pending"
        text = f"{self.safe_yield_m3_per_h:.2g} m3/h"
        if (
            self.safe_yield_low_m3_per_h is not None
            and self.safe_yield_high_m3_per_h is not None
        ):
            text += (
                f" ({self.safe_yield_low_m3_per_h:.2g} to "
                f"{self.safe_yield_high_m3_per_h:.2g})"
            )
        return text


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
    # The R squared a straight-line fit has to reach before its transmissivity
    # is adopted. Copied from PumpingConfig by analyse_pumping_test, because the
    # analysis travels (session state, pickles) without its config.
    min_fit_r_squared: float = PumpingConfig.min_fit_r_squared
    # Fits that ran but cannot be adopted, keyed by method, with the reason:
    # a Cooper-Jacob window inside the casing-storage period, a recovery
    # line nowhere near the origin, a Theis storativity no aquifer has.
    disqualified: dict[str, str] = field(default_factory=dict)
    # The disqualified fits whose own result is wrong - a recovery line
    # nowhere near the origin, a storativity no aquifer has - keyed by method
    # with that reason. A fit read inside the casing-storage period is
    # disqualified as well, but its line may be sound, so it can still be
    # adopted as the best of the poor fits; a result that is wrong never can.
    invalid_fits: dict[str, str] = field(default_factory=dict)
    # How long casing storage controls the drawdown in this borehole, from
    # the casing and riser diameters and the specific capacity. None when
    # there is no specific capacity to compute it from.
    casing_storage_min: Optional[float] = None

    def fits(self) -> list[tuple[str, object]]:
        """Every method that fitted, in order of preference.

        Recovery is least affected by well losses and rate fluctuations,
        then Cooper-Jacob, then Theis.
        """
        return [
            (name, result)
            for name, result in (
                ("recovery", self.recovery),
                ("cooper_jacob", self.cooper_jacob),
                ("theis", self.theis),
            )
            if result is not None
        ]

    def adopted_fit(self) -> tuple[Optional[str], Optional[object], bool]:
        """``(method, result, qualifies)`` for the transmissivity the yield rests on.

        The first method in order of preference whose straight line reaches
        ``min_fit_r_squared`` is adopted; Theis is a curve fit with no R
        squared and is always eligible, which keeps it last. Taking recovery
        unconditionally adopted a 0.52 m2/day recovery at R squared 0.69
        over a 4.3 m2/day Cooper-Jacob at 0.99. When nothing reaches the
        threshold the best of the poor fits is still adopted, so a yield is
        produced, and ``qualifies`` is False so the caller can flag it.

        The best of the poor fits is taken from the fits nothing disqualified,
        and only when there are none from the fits disqualified for lying
        inside the casing-storage period. A fit in ``invalid_fits`` is never
        adopted: the pick used to run over every fit, so a recovery line
        meeting t/t' = 1 at 60% of its drawdown won on its R squared of 0.99
        and the yield rested on the one result the analysis had rejected.
        When nothing is left the method is None and the yield is pending.
        """
        fits = self.fits()
        for name, result in fits:
            if name in self.disqualified:
                continue
            r2 = getattr(result, "r_squared", None)
            if r2 is None or r2 >= self.min_fit_r_squared:
                return name, result, True
        pool = [item for item in fits if item[0] not in self.disqualified] or [
            item for item in fits if item[0] not in self.invalid_fits
        ]
        if not pool:
            return None, None, False
        # the best of the poor fits: the highest R squared among the straight
        # lines, and the curve fit (which has none) only when it is all there is
        name, result = max(
            pool, key=lambda item: getattr(item[1], "r_squared", None) or -1.0
        )
        return name, result, False

    def why_not_adopted(self, name: str) -> str:
        """The reason a fitted method was passed over, or an empty string."""
        if name in self.disqualified:
            return self.disqualified[name]
        result = dict(self.fits()).get(name)
        r2 = getattr(result, "r_squared", None)
        if r2 is not None and r2 < self.min_fit_r_squared:
            return f"R squared {r2:.3f} is below the {self.min_fit_r_squared:g} standard"
        return ""

    @property
    def transmissivity_source(self) -> Optional[str]:
        """``"recovery" | "cooper_jacob" | "theis"``, or None when nothing fitted."""
        return self.adopted_fit()[0]

    @property
    def transmissivity_m2_per_day(self) -> Optional[float]:
        """The transmissivity the yield recommendation rests on."""
        result = self.adopted_fit()[1]
        return result.transmissivity_m2_per_day if result is not None else None


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


def _require_discharge(discharge_m3_per_h) -> float:
    """A rate of zero is not a measurement, and T is proportional to Q.

    A blank left as 0 on the sheet used to divide by zero deep inside the
    fit; raising here puts it on the same handled path as a missing value.
    """
    if discharge_m3_per_h is None:
        raise ValueError("No discharge recorded, so transmissivity cannot be fitted")
    q = float(discharge_m3_per_h)
    if not math.isfinite(q) or q <= 0:
        raise ValueError(
            f"Discharge must be greater than zero to fit an aquifer parameter "
            f"(got {q:g} m3/h); check the discharge row on the field sheet"
        )
    return q


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
    _require_discharge(discharge_m3_per_h)
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
            # the six latest readings. argsort gives sorting indices, not
            # ranks, so comparing it against a rank picked an arbitrary six
            # whenever the sheet's times were not already in order
            window = t >= np.sort(t)[-min(6, len(t))]
        fit_window_min = (float(t[window].min()), float(t[window].max()))
    else:
        window = (t >= fit_window_min[0]) & (t <= fit_window_min[1])

    slope, intercept, r2 = _line_fit(np.log10(t[window]), s[window])
    if slope <= 0:
        raise ValueError(
            "Drawdown does not increase with log time; Cooper-Jacob does not apply"
        )
    # T is inversely proportional to the slope, so a tail that has flattened
    # to within reading resolution gave thousands of m2/day with a straight
    # face; a line that does not explain the window is no better.
    if slope < config.cooper_jacob_min_slope_m:
        raise ValueError(
            f"The fitted window {fit_window_min[0]:g}-{fit_window_min[1]:g} min "
            f"is flat ({slope:.3f} m per log cycle, under "
            f"{config.cooper_jacob_min_slope_m:g} m): the drawdown has stabilised "
            "or the slope is below reading resolution, so Cooper-Jacob does not "
            "apply"
        )
    if r2 < config.cooper_jacob_min_r2:
        raise ValueError(
            f"The straight line explains too little of the window "
            f"{fit_window_min[0]:g}-{fit_window_min[1]:g} min (R squared "
            f"{r2:.3f}, under {config.cooper_jacob_min_r2:g}), so Cooper-Jacob "
            "does not apply"
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
    if u_start < config.cooper_jacob_u_max and observation_radius_m is None:
        # In the pumped well r is the well radius, so u is tiny from the
        # first minute whatever the data look like. The criterion is a
        # distance criterion; it says the straight-line form applies, not
        # that this line is a good one, and the report used to read it as
        # a validation of the fit.
        u_check = (
            f"u = {u_start:.2e} at the start of the fitted window, below the "
            f"{config.cooper_jacob_u_max} criterion. In the pumped well "
            "itself this is a distance criterion met from the first minute; "
            "it does not test the fit"
        )
    elif u_start < config.cooper_jacob_u_max:
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
    _require_discharge(discharge_m3_per_h)
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
    equivalent_time: bool = False,
) -> RecoveryResult:
    """Theis recovery analysis on residual drawdown against t/t'.

    ``s' = 2.303 Q / (4 pi T) log10(t/t')`` with t measured since
    pumping started and t' since it stopped. ``pumping_duration_min`` is
    the time t/t' is formed with; after a step test pass the equivalent
    time from :func:`equivalent_pumping_time_min` and say so.

    The fitted line's intercept is kept and reported. Theory puts the line
    through the origin, and a line that misses it by a large fraction of
    the drawdown the recovery started from is not a Theis recovery line
    whatever its slope: the caller judges that against
    ``PumpingConfig.recovery_intercept_max_fraction``.
    """
    _require_discharge(discharge_m3_per_h)
    tp = np.asarray(recovery_time_min, dtype=float)  # t'
    sp = np.asarray(residual_drawdown_m, dtype=float)
    keep = (tp > 0) & np.isfinite(sp)
    tp, sp = tp[keep], sp[keep]
    if len(tp) < 4:
        raise ValueError("Not enough recovery readings")
    ratio = (pumping_duration_min + tp) / tp
    slope, intercept, r2 = _line_fit(np.log10(ratio), sp)
    if slope <= 0:
        raise ValueError("Residual drawdown does not decrease; check the data")
    q_day = discharge_m3_per_h * 24.0
    T = 2.303 * q_day / (4.0 * math.pi * slope)
    start = float(np.nanmax(sp))
    return RecoveryResult(
        transmissivity_m2_per_day=T,
        slope_m_per_log_cycle=slope,
        n_points=len(tp),
        r_squared=r2,
        discharge_m3_per_h=discharge_m3_per_h,
        residual_at_end_m=float(sp[-1]),
        intercept_m=float(intercept),
        pumping_time_min=float(pumping_duration_min),
        equivalent_time=equivalent_time,
        intercept_fraction=abs(float(intercept)) / start if start > 0 else 0.0,
    )


def equivalent_pumping_time_min(test: PumpingTest) -> tuple[Optional[float], bool]:
    """``(minutes, is_equivalent)``: the pumping time a recovery is read against.

    Theis recovery assumes one rate for the whole pumping time. After a step
    test the last rate was pumped for the last step only; using the last
    rate with the total time says the aquifer was stressed harder than it
    was and biases the transmissivity. The usual correction is the
    discharge-weighted equivalent time, ``sum(Q_i dt_i) / Q_last``, which
    gives the time the last rate would have had to run to pump the same
    volume. A constant test, or a step test missing a rate, uses the
    recorded duration.
    """
    steps = [s for s in test.steps if len(s.time_min)]
    if not steps:
        return test.pumping_duration_min, False
    if (
        not test.test_type.startswith("step") or len(steps) < 2
        or any(s.discharge_m3_per_h is None for s in steps)
    ):
        return test.pumping_duration_min, False
    q_last = float(steps[-1].discharge_m3_per_h)
    durations, _ = step_durations_min(steps)
    volume = sum(
        float(step.discharge_m3_per_h) * dt
        for step, dt in zip(steps, durations, strict=True)
    )
    if q_last <= 0 or volume <= 0:
        return test.pumping_duration_min, False
    return volume / q_last, True


def step_durations_min(steps) -> tuple[list[float], list[int]]:
    """``(minutes per step, restarted step numbers)``: how long each step pumped.

    A step's times normally run on from the step before (61, 62 ... after a
    step ending at 60), and its length is its last reading less that step's.
    Some sheets count each step from its own start instead, so a step opens
    at or before the minute the step before it ended; its own last reading is
    then its length, and the lengths add. Differencing those steps against
    the step before gave them no length at all: the recovery after such a
    step test was read against 30 minutes where the steps had pumped 158.
    A step with no readable time pumped for no measurable time.
    """
    durations: list[float] = []
    restarted: list[int] = []
    previous_end: Optional[float] = None
    for step in steps:
        finite = step.time_min[np.isfinite(step.time_min)]
        if not len(finite):
            durations.append(0.0)
            continue
        start, end = float(finite.min()), float(finite.max())
        if previous_end is not None and start <= previous_end:
            restarted.append(step.step_number)
            durations.append(max(end, 0.0))
        else:
            durations.append(max(end - (previous_end or 0.0), 0.0))
        previous_end = end
    return durations, restarted


def casing_storage_min(
    specific_capacity_m3h_per_m: Optional[float], config: PumpingConfig | None = None
) -> Optional[float]:
    """How long casing storage controls the drawdown, in minutes.

    Early in a test the pump takes water standing in the casing before it
    takes much from the aquifer, and a drawdown curve read inside that
    period is the borehole emptying, not the ground responding. Schafer's
    rule puts its end at ``0.6 (dc^2 - dp^2) / (Q/s)`` (inches, gpm/ft),
    here in metres and m3/h per m. A 5 inch casing with a 1.25 inch riser
    and a specific capacity of 0.09 m3/h per m gives about two hours: a
    thirty-minute test on such a borehole never leaves the casing.
    """
    config = config or PumpingConfig()
    if not specific_capacity_m3h_per_m or specific_capacity_m3h_per_m <= 0:
        return None
    dc = config.casing_diameter_in * 0.0254
    dp = config.riser_diameter_in * 0.0254
    area = dc * dc - dp * dp
    if area <= 0:
        return None
    return CASING_STORAGE_COEFFICIENT * area / specific_capacity_m3h_per_m


def deepest_pumping_level(test: PumpingTest) -> Optional[float]:
    """The deepest water level any pumping step reached, metres below datum."""
    levels = [
        float(np.nanmax(s.water_level_m))
        for s in test.steps
        if len(s.water_level_m) and np.any(np.isfinite(s.water_level_m))
    ]
    return max(levels) if levels else None


def hantush_bierschenk(
    step_discharges_m3_per_h: list[float],
    step_end_drawdowns_m: list[float],
    step_numbers: Optional[list[int]] = None,
) -> StepTestResult:
    """Hantush-Bierschenk analysis of a step drawdown test.

    Fits ``s_w = B Q + C Q^2`` through the end-of-step drawdowns by
    linear regression of s_w/Q on Q. Q is converted to m3/day, so B is
    in day/m2 and C in day2/m5.

    ``step_numbers`` are the sheet's numbers for the steps passed in. A step
    left out of the fit used to renumber the rest, so the table printed
    "Step 1 | 2.2 m3/h" beside a test details line saying step 1 ran at
    1.5 m3/h. Without them the steps are numbered from one.
    """
    q = np.asarray(step_discharges_m3_per_h, dtype=float) * 24.0
    s = np.asarray(step_end_drawdowns_m, dtype=float)
    if len(q) < 2:
        raise ValueError("A step test needs at least two steps with discharge")
    sq = s / q
    C, B, r2 = _line_fit(q, sq)
    fit_note = ""
    if C < 0:
        # negative well loss has no physical meaning; fall back to pure
        # aquifer loss
        C = 0.0
        B = float(np.mean(sq))
        fit_note = (
            "negative well loss refitted as pure aquifer loss; the efficiencies "
            "are 100% by construction and not meaningful"
        )
    if B < 0:
        # Neither has a negative aquifer loss: it made the reported well
        # efficiency negative (100 B Q / (B Q + C Q^2) with B < 0), which went
        # into the report as the borehole's efficiency. Refit through the
        # origin as pure well loss - least squares of s/Q = C Q with B = 0.
        B = 0.0
        C = float(np.sum(s) / np.sum(q**2))
        fitted = C * q
        ss_tot = float(np.sum((sq - sq.mean()) ** 2))
        r2 = 1.0 - float(np.sum((sq - fitted) ** 2)) / ss_tot if ss_tot > 0 else 1.0
        fit_note = (
            "negative aquifer loss refitted as pure well loss; efficiencies are "
            "not meaningful"
        )
    numbers = list(step_numbers) if step_numbers is not None else list(range(1, len(q) + 1))
    steps = []
    for number, qi, si in zip(numbers, q, s, strict=True):
        eff = 100.0 * B * qi / (B * qi + C * qi**2) if (B * qi + C * qi**2) > 0 else 100.0
        steps.append(
            {
                "step": int(number),
                "discharge_m3_per_h": qi / 24.0,
                "drawdown_end_m": float(si),
                "sw_over_q_day_per_m2": float(si / qi),
                "efficiency_percent": float(eff),
            }
        )
    return StepTestResult(
        aquifer_loss_B=float(B), well_loss_C=float(C), steps=steps, r_squared=r2,
        fit_note=fit_note, two_point=len(q) == 2,
    )


#: What a two-step Hantush-Bierschenk fit is worth, in the report's words.
TWO_POINT_NOTE = (
    "The line is fitted through two points, so it is exact by construction: "
    "the R squared of 1.000 tests nothing, and B, C and the efficiencies are "
    "indicative until a third step is pumped"
)


# ---------------------------------------------------------------------------
# Yield recommendation
# ---------------------------------------------------------------------------

def _no_usable_drawdown_reason(test: PumpingTest, config: PumpingConfig) -> str:
    """Why the pump setting leaves nothing to draw on, in the sheet's numbers.

    The reserves are named one by one so the fix is obvious: set the pump
    deeper, or reduce the reserve when the test was run at the annual low.
    """
    swl = test.static_water_level_m
    if test.pump_setting_m is not None:
        where = f"the pump intake at {test.pump_setting_m:.1f} m"
        gap = test.pump_setting_m - swl
        reserves = [f"the {config.pump_submergence_min_m:g} m submergence margin"]
        fix = "set the pump deeper"
    else:
        where = f"the borehole bottom at {test.borehole_depth_m:.1f} m"
        gap = test.borehole_depth_m - swl
        reserves = [
            "the 3 m clearance above the bottom",
            f"the {config.pump_submergence_min_m:g} m submergence margin",
        ]
        fix = "record the pump setting or deepen the borehole"
    if config.seasonal_allowance_m > 0:
        reserves.append(f"the {config.seasonal_allowance_m:g} m dry-season reserve")
        fix += " or reduce the reserve"
    if gap >= 0:
        position = f"is {gap:.1f} m below the static level of {swl:.1f} m"
    else:
        position = f"is {-gap:.1f} m above the static level of {swl:.1f} m"
    listed = (
        reserves[0] if len(reserves) == 1
        else ", ".join(reserves[:-1]) + " and " + reserves[-1]
    )
    return f"{where} {position}; after {listed} no usable drawdown remains - {fix}"


def recommend_yield(
    test: PumpingTest,
    transmissivity: Optional[float],
    step_result: Optional[StepTestResult],
    config: PumpingConfig | None = None,
    assumed_storativity: float = 1e-3,
    effective_radius_m: float = 0.1,
    transmissivity_source: str | None = None,
    no_transmissivity_reason: str = "",
) -> YieldRecommendation:
    """Specific capacity, sustainable yield and pump depth.

    The long term yield solves ``s_proj(Q) = f_avail x s_available``
    where ``s_proj`` projects Cooper-Jacob drawdown to the design
    period with the fitted T (plus well losses when a step test is
    available). The stated safety factor is then applied. Every input
    is recorded in ``basis`` so the recommendation is traceable;
    ``transmissivity_source`` (a key of :data:`METHOD_LABELS`) names the
    method the transmissivity came from in that narrative.
    ``no_transmissivity_reason`` is why no transmissivity was adopted when
    fits ran and every one was rejected, for the pending narrative.
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
    specific_capacity_basis = ""
    if q_last and s_end and s_end > 0:
        specific_capacity = q_last / s_end
        # a specific capacity is a rate over a drawdown at a time: 0.09 m3/h
        # per m after thirty minutes is not 0.09 after a day, and printed
        # bare to three figures it read as a property of the borehole
        minutes = None
        finite = last.time_min[np.isfinite(last.time_min)]
        if len(finite):
            minutes = float(finite.max())
        specific_capacity_basis = (
            f"{q_last:g} m3/h over {s_end:.1f} m of drawdown"
            + (f" after {minutes:g} minutes" if minutes else "")
        )
    deepest = deepest_pumping_level(test)

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
    # A zero here is an answer (the intake sits at the submergence margin),
    # not a missing value, so only None is treated as unknown.
    usable = (
        max(available - config.seasonal_allowance_m, 0.0)
        * config.available_drawdown_fraction
        if available is not None
        else None
    )

    def pending(reason: str) -> YieldRecommendation:
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
            specific_capacity_basis=specific_capacity_basis,
            deepest_pumping_level_m=deepest,
        )

    if transmissivity is None or swl is None:
        # name what is actually missing: blaming the discharge when it was
        # recorded and the fit simply failed sends the crew back to the field
        # for a number that is already on the sheet
        missing = []
        if swl is None:
            missing.append("static water level is missing")
        if transmissivity is None:
            missing.append(
                "discharge is missing on the field sheet"
                if not any(s.discharge_m3_per_h for s in test.steps)
                else no_transmissivity_reason
                or "transmissivity could not be fitted from the readings"
            )
        return pending(" and ".join(missing))

    # No drawdown to spend is a finding about the pump setting. It used to
    # come back as a blank recommendation with no reason, which every report
    # then blamed on the discharge.
    if usable is None:
        return pending(
            "neither the pump setting nor the borehole depth is recorded, so "
            "the available drawdown cannot be computed"
        )
    if usable <= 0:
        return pending(_no_usable_drawdown_reason(test, config))

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

    # bisect Q so projected drawdown equals the usable drawdown
    q_lo, q_hi = 0.01, 200.0
    if projected_drawdown(q_hi) <= usable:
        # The search would hand back its ceiling as if it were an answer.
        # Either the transmissivity is implausible or the drawdown budget is
        # enormous; in both cases this test does not limit the yield.
        return pending(
            f"the drawdown projection does not limit the yield within {q_hi:g} "
            "m3/h, so the usable drawdown is not the constraint; check the "
            "transmissivity fit before relying on this test"
        )
    for _ in range(80):
        q_mid = 0.5 * (q_lo + q_hi)
        if projected_drawdown(q_mid) > usable:
            q_hi = q_mid
        else:
            q_lo = q_mid
    long_term = q_lo
    safe = long_term / config.safety_factor

    s_at_safe = projected_drawdown(safe)
    # The intake goes where the drawdown the yield was computed on exists.
    # The long-term yield was found by spending the usable drawdown, which
    # was measured down to the test's pump setting; the intake used to be
    # raised to just clear the drawdown at the safe rate instead, which put
    # it 3 m above the level the test itself had reached and spent the
    # safety factor on lifting the pump rather than on the rate. It is now
    # set below the static level plus the dry-season reserve, the usable
    # drawdown and the submergence margin, and never above the deepest
    # level the test drew the water to, with the same submergence under it.
    # That floor is a reading, so it holds only where the readings do: a
    # level the sheet itself shows cannot be right (below the pump, below the
    # bottom of the hole) set a Kuntolo intake at 67 m from a 78.5 m reading
    # in a 70 m hole. The pump cannot have drawn the level below its own
    # setting either, so the floor never goes deeper than the test pump did.
    pump_depth = swl + config.seasonal_allowance_m + usable + config.pump_submergence_min_m
    reached = ""
    if deepest is not None and levels_in_doubt(test):
        reached = (
            f"; the deepest level recorded, {deepest:.1f} m, is left out because "
            "the recorded levels are inconsistent with the stated static level, "
            "pump setting or borehole depth"
        )
    elif deepest is not None:
        floor = deepest + config.pump_submergence_min_m
        at_pump = test.pump_setting_m is not None and floor > test.pump_setting_m
        if at_pump:
            floor = test.pump_setting_m
        reached = (
            f"; the test itself drew the level to {deepest:.1f} m"
            + (f" at {q_last:g} m3/h" if q_last else "")
        )
        if floor > pump_depth:
            pump_depth = floor
            reached += ", which sets the intake" + (
                f" at the {test.pump_setting_m:g} m the test pump was set to"
                if at_pump else ""
            )
    # Rounded to the next whole metre down the hole, except where the
    # clearance above the bottom governs: rounding down the hole after the cap
    # put a 45.5 m hole's intake at 43 m, 2.5 m above the bottom, beside text
    # saying it was capped 3 m above.
    pump_depth = math.ceil(pump_depth)
    capped = ""
    if test.borehole_depth_m and pump_depth > test.borehole_depth_m - 3.0:
        pump_depth = math.floor(test.borehole_depth_m - 3.0)
        capped = (
            f", capped 3 m above the {test.borehole_depth_m:g} m bottom of the "
            "borehole"
        )
    pump_depth_basis = (
        f"Pump intake at {pump_depth:g} m: the static level {swl:.1f} m plus the "
        f"{config.seasonal_allowance_m:g} m dry-season reserve, the {usable:.1f} m "
        "of drawdown the long-term yield is projected to use and "
        f"{config.pump_submergence_min_m:g} m of submergence{reached}{capped}. The "
        "safety factor is kept on the rate, not spent on raising the pump."
    )

    method = METHOD_LABELS.get(transmissivity_source or "", "")
    basis = (
        f"Transmissivity {transmissivity:.1f} m2/day"
        + (f" from the {method} fit" if method else "")
        + f"; drawdown projected to {t_design:.0f} days with storativity assumed "
        f"{assumed_storativity:g} and effective radius {effective_radius_m} m; "
        f"usable drawdown taken as {config.available_drawdown_fraction:.0%} of "
        f"the available drawdown {available:.1f} m (static level to pump intake "
        f"less {config.pump_submergence_min_m:.0f} m submergence), after "
        f"reserving a {config.seasonal_allowance_m:.0f} m dry-season "
        "water-table decline"
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
        projected_drawdown_m=s_at_safe,
        long_term_yield_m3_per_h=long_term,
        safe_yield_m3_per_h=safe,
        safety_factor=config.safety_factor,
        design_period_days=t_design,
        pump_installation_depth_m=pump_depth,
        basis=basis,
        specific_capacity_basis=specific_capacity_basis,
        pump_depth_basis=pump_depth_basis,
        deepest_pumping_level_m=deepest,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


# storativity is never resolvable from a single pumped well, the effective
# radius depends on the gravel pack and development, and the wet-to-dry
# decline is a regional rule of thumb. The safe yield is proportional to
# none of them individually but sensitive to all of them, so the honest
# output is a band. Ranges follow common basement-aquifer practice.
_ENVELOPE_STORATIVITY = (1e-4, 1e-2)
_ENVELOPE_RADIUS_M = (0.075, 0.15)
_ENVELOPE_SEASONAL_M = (1.0, 4.0)


def attach_yield_envelope(
    analysis: "PumpingTestAnalysis", config: PumpingConfig | None = None
) -> None:
    """Fill the safe-yield band on ``analysis.yield_recommendation``.

    Re-runs the same recommendation over the corners of the assumption
    envelope - transmissivity across whichever methods actually fitted,
    storativity, effective well radius and the seasonal allowance - and keeps
    the lowest and highest safe yields. Reported as "2.4 m3/h (1.8 to 3.1)",
    so nobody reads an assumed number as a measured one.
    """
    config = config or PumpingConfig()
    recommendation = analysis.yield_recommendation
    if recommendation is None or recommendation.safe_yield_m3_per_h is None:
        return

    # A fit the analysis rejected does not widen the band either: Dr Timbo's
    # "0.39 m3/h (0.28 to 1.2)" took its top from the recovery line it had
    # just refused for missing the origin. The adopted fit stays in even when
    # it is a casing-storage fallback, since the yield itself rests on it.
    adopted = analysis.transmissivity_source
    fitted = [
        r.transmissivity_m2_per_day
        for name, r in analysis.fits()
        if r.transmissivity_m2_per_day
        and (name not in analysis.disqualified or name == adopted)
    ]
    if not fitted:
        return
    # when only one method fitted there is no spread to measure, so allow the
    # factor of two that separates methods on a typical basement borehole
    t_range = (min(fitted), max(fitted)) if len(fitted) > 1 else (
        fitted[0] / 1.5, fitted[0] * 1.5
    )

    yields = []
    for transmissivity in t_range:
        for storativity in _ENVELOPE_STORATIVITY:
            for radius in _ENVELOPE_RADIUS_M:
                for seasonal in _ENVELOPE_SEASONAL_M:
                    variant = replace(config, seasonal_allowance_m=seasonal)
                    trial = recommend_yield(
                        analysis.test,
                        transmissivity,
                        analysis.step_test,
                        variant,
                        assumed_storativity=storativity,
                        effective_radius_m=radius,
                    )
                    if trial.safe_yield_m3_per_h:
                        yields.append(trial.safe_yield_m3_per_h)
    if not yields:
        return
    recommendation.safe_yield_low_m3_per_h = min(yields)
    recommendation.safe_yield_high_m3_per_h = max(yields)
    recommendation.envelope_basis = (
        f"Range over transmissivity {t_range[0]:.1f}-{t_range[1]:.1f} m2/day"
        f"{' (spread between the fitted methods)' if len(fitted) > 1 else ''}, "
        f"storativity {_ENVELOPE_STORATIVITY[0]:g}-{_ENVELOPE_STORATIVITY[1]:g}, "
        f"effective radius {_ENVELOPE_RADIUS_M[0]}-{_ENVELOPE_RADIUS_M[1]} m and "
        f"a dry-season decline of {_ENVELOPE_SEASONAL_M[0]:.0f}-"
        f"{_ENVELOPE_SEASONAL_M[1]:.0f} m. Design to the lower figure where the "
        "supply must not fail in a dry year."
    )


def pump_intake_depth(analysis, seasonal=None) -> tuple[Optional[float], str]:
    """The one pump intake depth a report prints, and why.

    A report with a seasonal projection used to say "install at 39 m" in
    its recommendation and "set the intake at 40 m" three paragraphs
    later: the first from the day of the test, the second from the drought
    scenario. The deeper of the two is the depth, everywhere, and the
    reason travels with it.
    """
    recommendation = getattr(analysis, "yield_recommendation", None)
    depth = getattr(recommendation, "pump_installation_depth_m", None)
    if depth is None:
        return None, ""
    seasonal_depth = None
    if seasonal is not None and getattr(seasonal, "is_established", False):
        seasonal_depth = getattr(seasonal, "pump_installation_depth_m", None)
    if seasonal_depth is not None and seasonal_depth > depth:
        return float(seasonal_depth), (
            "deep enough for the drought-year low in the seasonal projection"
        )
    if seasonal_depth is not None:
        return float(depth), (
            "which also covers the drought-year low in the seasonal projection"
        )
    return float(depth), ""


def _pumped_duration_min(test: PumpingTest) -> tuple[Optional[float], str]:
    """``(minutes, kind)``: how long the aquifer was stressed at one rate.

    A constant test is judged on the whole pumped duration; a step test on
    the length of a step, which is also the time its end-of-step drawdowns
    refer to when they are projected forward. ``kind`` is ``"step"`` or
    ``"constant"``.
    """
    if test.test_type.startswith("step"):
        length = test.step_length_min
        if not length and test.steps:
            first = test.steps[0].time_min
            finite = first[np.isfinite(first)]
            length = float(finite.max()) if len(finite) else None
        return length, "step"
    duration = test.pumping_duration_min
    if not duration and test.steps:
        times, _ = test.all_times_levels()
        finite = times[np.isfinite(times)]
        duration = float(finite.max()) if len(finite) else None
    return duration, "constant"


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
    analysis = PumpingTestAnalysis(test=test, min_fit_r_squared=config.min_fit_r_squared)
    # drop parse-time discharge flags that the analyst has since resolved
    flags = [
        f
        for f in test.flags
        if not (
            f.code in ("missing_discharge", "discharge_ambiguous")
            and all(s.discharge_m3_per_h is not None for s in test.steps)
        )
    ]
    # A zero or negative rate is a blank the crew wrote a 0 into, not a
    # measurement. Treat it as missing so the pending narrative and the
    # step-test guards below are right, rather than carrying it into a fit.
    for step in test.steps:
        q = step.discharge_m3_per_h
        if q is not None and not (float(q) > 0 and math.isfinite(float(q))):
            step.discharge_m3_per_h = None
            flags.append(
                DataFlag(
                    "warning",
                    "invalid_discharge",
                    f"Discharge recorded as {float(q):g} m3/h, which cannot be "
                    "a pumping rate; treated as not measured. Enter the "
                    "bucket-and-stopwatch value to get transmissivity and yield.",
                    context=step.label or f"step {step.step_number}",
                )
            )

    swl = test.static_water_level_m

    if test.steps and swl is not None:
        last = test.steps[-1]
        analysis.max_drawdown_m = float(np.nanmax(last.water_level_m) - swl)
        tail = last.water_level_m[-3:]
        if len(tail) >= 2 and (np.max(tail) - np.min(tail)) <= 0.05:
            analysis.stabilised_level_m = float(np.mean(tail))
            # Theis assumes an infinite aquifer whose drawdown never stops
            # growing with log time; a level that has held still is being
            # fed by something, and projecting it to 365 days is the wrong
            # question.
            flags.append(
                DataFlag(
                    "warning",
                    "drawdown_stabilised",
                    f"The pumped water level held at about "
                    f"{analysis.stabilised_level_m:.2f} m over the last readings: "
                    "a recharge boundary or leakage is indicated, so the "
                    "Theis/Cooper-Jacob projection to the design period is not "
                    "the governing check; the stabilised level is.",
                )
            )

    # ---- test length ------------------------------------------------------
    # The yield is projected to the design period on log time, so a short
    # test is extrapolated over several decades of time from a curve that
    # has not yet shown its late-time behaviour. Say how far.
    duration, kind = _pumped_duration_min(test)
    threshold = (
        config.min_step_length_min if kind == "step" else config.min_constant_test_min
    )
    short_prefix = ""
    if duration is not None and 0 < duration < threshold:
        cycles = math.log10(config.design_period_days * MIN_PER_DAY / duration)
        if kind == "step":
            what = f"Each step ran for {duration:g} minutes"
            short_prefix = f"Projected from {duration:g}-minute steps"
        else:
            what = f"The test pumped for {duration:g} minutes"
            short_prefix = f"Projected from a {duration:g}-minute test"
        short_prefix += (
            f" ({cycles:.1f} log cycles to {config.design_period_days:g} days); "
            "treat as indicative. "
        )
        flags.append(
            DataFlag(
                "warning",
                "short_test",
                f"{what}, below the {threshold:g} minutes needed to see late-time "
                f"behaviour; the yield is extrapolated {cycles:.1f} log cycles of "
                f"time to the {config.design_period_days:g}-day design period and "
                "should be treated as indicative.",
            )
        )

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
            # A step that ends above the stated static level has no drawdown
            # to fit. It used to get a Cooper-Jacob line through negative
            # drawdowns, adopted for the yield at R squared 0.99, while the
            # step-test fit two lines below excluded the same step as a
            # datum error.
            s_end = float(s[keep][-1]) if keep.any() else float("nan")
            label = step.label or f"step {step.step_number}"
            if not s_end > 0:
                flags.append(
                    DataFlag(
                        "warning",
                        "first_step_above_static",
                        f"{label} ends at {s_end:.2f} m drawdown, at or above the "
                        f"stated static level of {swl:.2f} m, so no drawdown "
                        "fit is made on it; check the static level and the "
                        "datum for that step.",
                        context=label,
                    )
                )
                keep &= False
            try:
                analysis.cooper_jacob = cooper_jacob(
                    t[keep], s[keep], q, config,
                    observation_radius_m=observation_radius_m,
                )
            except ValueError as exc:
                if keep.any():
                    flags.append(DataFlag("warning", "cooper_jacob_failed", str(exc)))
            try:
                analysis.theis = theis_fit(
                    t[keep], s[keep], q,
                    observation_well=observation_radius_m is not None,
                    radius_m=observation_radius_m or 0.1,
                )
            except (ValueError, RuntimeError) as exc:
                if keep.any():
                    flags.append(DataFlag("warning", "theis_failed", str(exc)))

    # ---- step clocks ----------------------------------------------------------
    # A step test whose times restart each step is read with each step's own
    # last reading as its length. The reading is the toolkit's, not the
    # sheet's, and the overview and the recorded duration still show the
    # step clocks, so it is said.
    step_durations: list[float] = []
    if test.test_type.startswith("step"):
        timed = [s for s in test.steps if len(s.time_min)]
        step_durations, restarted = step_durations_min(timed)
        if restarted:
            one = len(restarted) == 1
            names = (
                f"Step {restarted[0]}" if one
                else "Steps " + ", ".join(str(n) for n in restarted[:-1])
                + f" and {restarted[-1]}"
            )
            recorded = (
                f", not the {test.pumping_duration_min:g} minutes the latest "
                "reading gives" if test.pumping_duration_min else ""
            )
            flags.append(
                DataFlag(
                    "warning",
                    "step_time_restarted",
                    f"{names} {'opens' if one else 'open'} at or before the minute "
                    f"the step before {'it' if one else 'each'} ended, so "
                    f"{'its' if one else 'their'} times are read as counted from "
                    f"the start of {'the' if one else 'each'} step rather than from "
                    "the start of the test: each step's own last reading is taken "
                    f"as its length, and the steps pumped for {sum(step_durations):g} "
                    f"minutes in all{recorded}. Check the times on the sheet.",
                )
            )

    # ---- recovery -----------------------------------------------------------
    residual = test.residual_drawdown()
    if residual is not None and test.recovery_time_min is not None:
        q_rec = None
        for step in reversed(test.steps):
            if step.discharge_m3_per_h is not None:
                q_rec = step.discharge_m3_per_h
                break
        t_pump, equivalent = equivalent_pumping_time_min(test)
        if q_rec is not None and t_pump:
            try:
                analysis.recovery = theis_recovery(
                    test.recovery_time_min, residual, t_pump, q_rec,
                    equivalent_time=equivalent,
                )
            except ValueError as exc:
                flags.append(DataFlag("warning", "recovery_failed", str(exc)))
        rec = analysis.recovery
        if rec is not None and equivalent:
            # the steps' own lengths added up: a sheet whose step times
            # restart has a latest reading that is one step, not the test
            flags.append(
                DataFlag(
                    "info",
                    "recovery_equivalent_time",
                    f"The recovery is read against an equivalent pumping time of "
                    f"{t_pump:.0f} minutes at the last rate of {q_rec:g} m3/h "
                    f"(the volume pumped over all the steps at that rate), not "
                    f"the {sum(step_durations):g} minutes the test ran.",
                )
            )
        if rec is not None and rec.intercept_fraction > config.recovery_intercept_max_fraction:
            analysis.disqualified["recovery"] = (
                f"the recovery line meets t/t' = 1 at {rec.intercept_m:.1f} m of "
                f"residual drawdown, {rec.intercept_fraction:.0%} of the drawdown "
                "the recovery started from, where the method requires zero"
            )
            analysis.invalid_fits["recovery"] = analysis.disqualified["recovery"]
            # the fraction is of the magnitude the recovery started from; a
            # line meeting the axis below zero printed "37% of the -21.8 m"
            flags.append(
                DataFlag(
                    "warning",
                    "recovery_intercept",
                    f"The recovery line does not pass through the origin: it "
                    f"meets t/t' = 1 at {rec.intercept_m:.1f} m of residual "
                    f"drawdown ({rec.intercept_fraction:.0%} of the "
                    f"{abs(rec.intercept_m) / max(rec.intercept_fraction, 1e-9):.1f} m "
                    "the recovery started from), where Theis recovery requires "
                    "zero. The residual drawdown is dominated by something the "
                    "method does not model (casing storage, a changing static "
                    "level or a wrong pumping time), so its transmissivity of "
                    f"{rec.transmissivity_m2_per_day:.2f} m2/day is reported but "
                    "not adopted.",
                )
            )

    # ---- step test ----------------------------------------------------------
    if test.test_type.startswith("step") and swl is not None and len(test.steps) >= 2:
        with_q = [s for s in test.steps if s.discharge_m3_per_h is not None]
        if len(with_q) >= 2:
            # A step that ends at or above the static level has no drawdown
            # to divide by: its s/Q is zero or negative, the intercept of the
            # fit goes negative and the refit reports a borehole with no
            # aquifer loss and 0% efficiency. A first step ending 4 m above
            # static (a datum anomaly) is what the sheets actually hold.
            positive = []
            for s in with_q:
                s_end = float(s.water_level_m[-1] - swl)
                label = s.label or f"step {s.step_number}"
                if not s_end > 0:
                    flags.append(
                        DataFlag(
                            "warning",
                            "step_negative_drawdown",
                            f"{label} ends at {s_end:.2f} m drawdown, at or above "
                            "the static level, so it is left out of the "
                            "Hantush-Bierschenk fit; check the static level and "
                            "the datum for that step.",
                            context=label,
                        )
                    )
                else:
                    positive.append((s.discharge_m3_per_h, s_end, s.step_number))
            if len(positive) >= 2:
                try:
                    analysis.step_test = hantush_bierschenk(
                        [q for q, _, _ in positive], [s_end for _, s_end, _ in positive],
                        step_numbers=[n for _, _, n in positive],
                    )
                except ValueError as exc:
                    flags.append(DataFlag("warning", "step_test_failed", str(exc)))
            else:
                flags.append(
                    DataFlag(
                        "warning",
                        "step_test_pending",
                        f"Step test analysis pending: only {plural(len(positive), 'step')} "
                        "with discharge show positive drawdown, and the fit "
                        "needs at least two.",
                    )
                )
        else:
            flags.append(
                DataFlag(
                    "warning",
                    "step_test_pending",
                    "Step test analysis pending: discharge per step is missing.",
                )
            )

    # ---- casing storage -------------------------------------------------------------
    # The drawdown fits are on the first step, so the specific capacity that
    # sets the casing-storage period is that step's end-of-step value.
    if swl is not None and test.steps:
        first = test.steps[0]
        q_first = first.discharge_m3_per_h
        levels = first.water_level_m[np.isfinite(first.water_level_m)]
        s_first = float(levels[-1] - swl) if len(levels) else None
        if q_first and s_first and s_first > 0:
            analysis.casing_storage_min = casing_storage_min(q_first / s_first, config)
    t_c = analysis.casing_storage_min
    # A step test is judged on the length of a step, so its sentences are
    # worded per step: a 3 x 50-minute test used to be "the test pumped for
    # 50 minutes" and "the whole test lies inside" the casing-storage period.
    per_step = kind == "step"
    inside: list[str] = []
    casing_flag: Optional[DataFlag] = None
    if t_c:
        cj = analysis.cooper_jacob
        if cj is not None and cj.fit_window_min[1] <= t_c:
            analysis.disqualified["cooper_jacob"] = (
                f"its fitted window {cj.fit_window_min[0]:g}-{cj.fit_window_min[1]:g} "
                f"minutes lies inside the {t_c:.0f}-minute casing-storage period"
            )
            inside.append("cooper_jacob")
        elif cj is not None and cj.fit_window_min[0] < t_c:
            flags.append(
                DataFlag(
                    "warning",
                    "casing_storage_window",
                    f"The Cooper-Jacob window starts at {cj.fit_window_min[0]:g} "
                    f"minutes, inside the {t_c:.0f}-minute casing-storage period; "
                    "the early part of the line is the borehole emptying.",
                )
            )
        th = analysis.theis
        if th is not None and duration is not None and duration <= t_c:
            analysis.disqualified["theis"] = (
                (f"each {duration:g}-minute step lies inside" if per_step
                 else f"the whole {duration:g}-minute test lies inside")
                + f" the {t_c:.0f}-minute casing-storage period"
            )
            inside.append("theis")
        if inside:
            # Worded below, once the adoption is known: the flag said every fit
            # inside the period was "reported but not adopted" while the
            # transmissivity note adopted one of them as the best available.
            casing_flag = DataFlag("warning", "casing_storage", "")
            flags.append(casing_flag)
    th = analysis.theis
    if th is not None and th.storativity > config.max_plausible_storativity:
        storativity_reason = (
            f"its storativity of {th.storativity:.2g} is above "
            f"{config.max_plausible_storativity:g}, which no aquifer has"
        )
        analysis.disqualified.setdefault("theis", storativity_reason)
        analysis.invalid_fits["theis"] = storativity_reason
        flags.append(
            DataFlag(
                "warning",
                "storativity_implausible",
                f"The Theis fit returns a storativity of {th.storativity:.2g}; no "
                f"aquifer stores more than about {config.max_plausible_storativity:g} "
                "of its volume, and a value this size is the casing being emptied, "
                "not the aquifer draining. The fit is not adopted.",
            )
        )

    # ---- transmissivity ---------------------------------------------------------
    method, fit, qualifies = analysis.adopted_fit()
    if casing_flag is not None:
        words = {"cooper_jacob": "Cooper-Jacob", "theis": "Theis"}
        several = len(inside) > 1
        text = (
            f"With a {config.casing_diameter_in:g} inch casing and a "
            f"specific capacity of {q_first / s_first:.2g} m3/h per m, "
            "casing storage controls the drawdown for the first "
            f"{t_c:.0f} minutes (Schafer's rule)"
            + ((f"; each step pumped for {duration:g} minutes" if per_step
                else f"; this test pumped for {duration:g} minutes")
               + ", entirely inside it" if duration is not None and duration <= t_c
               else "")
            + f". The {' and '.join(words[k] for k in inside)} fit"
            + ("s see" if several else " sees")
            + " the borehole emptying rather than the aquifer"
        )
        if method in inside:
            others = [words[k] for k in inside if k != method]
            text += (
                ". No fit outside that period can be adopted, so the "
                f"{words[method]} value is adopted only as the best available"
                + (f" and the {' and '.join(others)} value is reported but not "
                   "adopted" if others else "")
                + "."
            )
        else:
            text += (", so " + ("their" if several else "its")
                     + " transmissivity is reported but not adopted.")
        casing_flag.message = text
    # Every fit ran and every one was rejected on its own result: the yield
    # is pending, and says why, rather than resting on a rejected line.
    rejected = ""
    if fit is None and analysis.fits():
        rejected = "no fitted transmissivity can be adopted (" + "; ".join(
            f"{METHOD_LABELS[name]} {result.transmissivity_m2_per_day:.2f} m2/day, "
            + (analysis.invalid_fits.get(name) or analysis.why_not_adopted(name))
            for name, result in analysis.fits()
        ) + ")"
    if fit is not None and not qualifies:
        scored = "; ".join(
            f"{METHOD_LABELS[name]} {result.transmissivity_m2_per_day:.2f} m2/day, "
            + (analysis.why_not_adopted(name) or "usable")
            for name, result in analysis.fits()
        )
        flags.append(
            DataFlag(
                "warning",
                "transmissivity_low_confidence",
                f"No method fitted to standard ({scored}). The "
                f"{METHOD_LABELS[method]} value of "
                f"{fit.transmissivity_m2_per_day:.2f} m2/day is adopted as the "
                "best available, so the yield rests on a fit that does not "
                "meet it.",
            )
        )

    # ---- yield ---------------------------------------------------------------
    analysis.yield_recommendation = recommend_yield(
        test,
        analysis.transmissivity_m2_per_day,
        analysis.step_test,
        config,
        transmissivity_source=method,
        no_transmissivity_reason=rejected,
    )
    attach_yield_envelope(analysis, config)
    recommendation = analysis.yield_recommendation
    if short_prefix and recommendation.safe_yield_m3_per_h is not None:
        recommendation.basis = short_prefix + recommendation.basis

    # ---- what the yield is worth ---------------------------------------------------
    # One judgement, made here and printed by every report beside the yield.
    # The pumping report used to carry these warnings in its data notes while
    # the completion and handover reports printed the same yield as
    # "successful and sustainable" without them. Levels the sheet itself
    # shows cannot be right come first: a yield computed from them was called
    # established, and the readiness gate certified it.
    reasons: list[str] = []
    if levels_in_doubt(test):
        reasons.append(LEVELS_IN_DOUBT_REASON)
    if duration is not None and 0 < duration < threshold:
        reasons.append(
            (f"each step ran for {duration:g} minutes" if per_step
             else f"the test pumped for {duration:g} minutes")
            + f", below the {threshold:g} "
            "needed to see late-time behaviour, so the yield is extrapolated "
            f"{math.log10(config.design_period_days * MIN_PER_DAY / duration):.1f} "
            "log cycles of time"
        )
    if t_c and duration is not None and duration <= t_c:
        reasons.append(
            ("each step lies inside" if per_step else "the whole test lies inside")
            + f" the {t_c:.0f}-minute casing-storage "
            "period, so its drawdown is the borehole emptying rather than the "
            "aquifer responding"
        )
    if fit is not None and not qualifies:
        reasons.append(
            f"no transmissivity method fitted to standard and the "
            f"{METHOD_LABELS[method]} value is adopted as the best available"
        )
    if recommendation.safe_yield_m3_per_h is not None and reasons:
        recommendation.confidence = "indicative"
        recommendation.confidence_reasons = reasons

    analysis.flags = flags
    return analysis

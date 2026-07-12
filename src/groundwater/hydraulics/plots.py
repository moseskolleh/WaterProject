"""Pumping test diagnostic plots.

All plots work from the parsed test (true drawdown recomputed from
static water level) and accept the analysis results for fitted line
overlays. Missing discharge does not block the water level and
drawdown curves.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ..config import HouseStyle
from ..models import PumpingTest
from ..plotting import figure_context, save_figure
from .analysis import (
    CooperJacobResult,
    RecoveryResult,
    StepTestResult,
    TheisResult,
)

__all__ = [
    "plot_test_overview",
    "plot_cooper_jacob",
    "plot_theis",
    "plot_recovery",
    "plot_step_test",
]


def plot_test_overview(
    test: PumpingTest,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
):
    """Water level against time for the whole test including recovery."""
    style = style or HouseStyle()
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 3.2))
        t_end = 0.0
        for step in test.steps:
            label = step.label if len(test.steps) > 1 else "pumping phase"
            ax.plot(step.time_min, step.water_level_m, "-o", ms=3,
                    color=style.accent_color, lw=1.2,
                    label=label if step.step_number in (1,) else None)
            t_end = max(t_end, float(step.time_min.max()))
        if test.recovery_time_min is not None:
            ax.plot(test.recovery_time_min + t_end, test.recovery_level_m, "-s",
                    ms=3, color=style.secondary_color, lw=1.2, label="recovery")
        if test.static_water_level_m is not None:
            ax.axhline(test.static_water_level_m, color="#666666", lw=1.0, ls="--",
                       label=f"static water level {test.static_water_level_m:.2f} m")
        if test.pump_setting_m:
            ax.axhline(test.pump_setting_m, color="#999999", lw=1.0, ls=":",
                       label=f"pump setting {test.pump_setting_m:.0f} m")
        ax.invert_yaxis()
        ax.set_xlabel("Time since pumping started (min)")
        ax.set_ylabel("Water level (m below datum)")
        title = "Pumping test overview"
        if test.site.community:
            title += f" - {test.site.community}"
        ax.set_title(title)
        ax.legend(loc="best")
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def plot_cooper_jacob(
    time_min: np.ndarray,
    drawdown_m: np.ndarray,
    result: CooperJacobResult | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Cooper-Jacob straight line analysis",
):
    """Semi-log drawdown against time with the fitted straight line."""
    style = style or HouseStyle()
    t = np.asarray(time_min, dtype=float)
    s = np.asarray(drawdown_m, dtype=float)
    keep = t > 0
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in * 0.85, 3.2))
        ax.semilogx(t[keep], s[keep], "o", ms=4, mfc="white",
                    mec=style.accent_color, mew=1.2, label="drawdown")
        if result is not None:
            t_line = np.geomspace(max(result.intercept_t0_min, t[keep].min() / 3), t[keep].max() * 1.3, 50)
            s_line = result.slope_m_per_log_cycle * np.log10(t_line / result.intercept_t0_min)
            ax.semilogx(t_line, s_line, "-", color=style.secondary_color, lw=1.8,
                        label=(
                            f"fit: {result.slope_m_per_log_cycle:.2f} m/log cycle, "
                            f"T = {result.transmissivity_m2_per_day:.1f} m2/day"
                        ))
            ax.axvspan(*result.fit_window_min, color=style.accent_color, alpha=0.08,
                       label="fitted window")
        ax.set_xlabel("Time (min)")
        ax.set_ylabel("Drawdown (m)")
        ax.invert_yaxis()
        ax.set_title(title)
        ax.legend(loc="best")
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def plot_theis(
    time_min: np.ndarray,
    drawdown_m: np.ndarray,
    result: TheisResult | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Theis curve fit",
):
    """Log-log drawdown against time with the fitted Theis curve."""
    from scipy.special import exp1

    style = style or HouseStyle()
    t = np.asarray(time_min, dtype=float)
    s = np.asarray(drawdown_m, dtype=float)
    keep = (t > 0) & (s > 0)
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in * 0.85, 3.2))
        ax.loglog(t[keep], s[keep], "o", ms=4, mfc="white",
                  mec=style.accent_color, mew=1.2, label="drawdown")
        if result is not None:
            t_line = np.geomspace(t[keep].min(), t[keep].max(), 80)
            t_day = t_line / 1440.0
            q_day = result.discharge_m3_per_h * 24.0
            u = result.radius_m**2 * result.storativity / (
                4.0 * result.transmissivity_m2_per_day * t_day
            )
            s_line = q_day / (4.0 * np.pi * result.transmissivity_m2_per_day) * exp1(u)
            label = (
                f"Theis fit: T = {result.transmissivity_m2_per_day:.1f} m2/day, "
                f"S = {result.storativity:.1e}"
            )
            if not result.storativity_reliable:
                label += " (S indicative)"
            ax.loglog(t_line, s_line, "-", color=style.secondary_color, lw=1.8, label=label)
        ax.set_xlabel("Time (min)")
        ax.set_ylabel("Drawdown (m)")
        ax.set_title(title)
        ax.legend(loc="best")
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def plot_recovery(
    recovery_time_min: np.ndarray,
    residual_drawdown_m: np.ndarray,
    pumping_duration_min: float,
    result: RecoveryResult | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Theis recovery analysis",
):
    """Residual drawdown against t/t' on a semi-log axis."""
    style = style or HouseStyle()
    tp = np.asarray(recovery_time_min, dtype=float)
    sp = np.asarray(residual_drawdown_m, dtype=float)
    keep = tp > 0
    ratio = (pumping_duration_min + tp[keep]) / tp[keep]
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in * 0.85, 3.2))
        ax.semilogx(ratio, sp[keep], "o", ms=4, mfc="white",
                    mec=style.accent_color, mew=1.2, label="residual drawdown")
        if result is not None:
            r_line = np.geomspace(1.001, ratio.max() * 1.2, 50)
            s_line = result.slope_m_per_log_cycle * np.log10(r_line)
            ax.semilogx(r_line, s_line, "-", color=style.secondary_color, lw=1.8,
                        label=(
                            f"fit: {result.slope_m_per_log_cycle:.2f} m/log cycle, "
                            f"T = {result.transmissivity_m2_per_day:.1f} m2/day"
                        ))
        ax.set_xlabel("t / t'")
        ax.set_ylabel("Residual drawdown (m)")
        ax.set_title(title)
        ax.legend(loc="best")
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def plot_step_test(
    test: PumpingTest,
    result: StepTestResult | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
):
    """Step test figure: drawdown per step, plus the Hantush-Bierschenk
    sw/Q against Q fit when discharges are available."""
    style = style or HouseStyle()
    swl = test.static_water_level_m
    with figure_context(style):
        if result is not None:
            fig, (ax, ax2) = plt.subplots(1, 2, figsize=(style.figure_width_in, 3.2))
        else:
            fig, ax = plt.subplots(figsize=(style.figure_width_in * 0.85, 3.2))
            ax2 = None
        for step in test.steps:
            s = step.water_level_m - swl if swl is not None else step.water_level_m
            q_note = (
                f", Q = {step.discharge_m3_per_h:.1f} m3/h"
                if step.discharge_m3_per_h is not None
                else ", Q pending"
            )
            ax.plot(step.time_min, s, "-o", ms=3, lw=1.2, label=f"{step.label}{q_note}")
        ax.invert_yaxis()
        ax.set_xlabel("Time since test start (min)")
        ax.set_ylabel("Drawdown below static (m)" if swl is not None else "Water level (m)")
        ax.set_title("Step drawdown test")
        ax.legend(loc="best", fontsize=8)

        if ax2 is not None and result is not None:
            q = np.array([s["discharge_m3_per_h"] for s in result.steps]) * 24.0
            sq = np.array([s["sw_over_q_day_per_m2"] for s in result.steps])
            ax2.plot(q, sq, "o", ms=5, mfc="white", mec=style.accent_color, mew=1.4,
                     label="observed")
            q_line = np.linspace(0, q.max() * 1.15, 40)
            ax2.plot(q_line, result.aquifer_loss_B + result.well_loss_C * q_line, "-",
                     color=style.secondary_color, lw=1.8,
                     label=(
                         f"B = {result.aquifer_loss_B:.2e} day/m2\n"
                         f"C = {result.well_loss_C:.2e} day2/m5"
                     ))
            ax2.set_xlabel("Discharge Q (m3/day)")
            ax2.set_ylabel("s_w / Q (day/m2)")
            ax2.set_title("Hantush-Bierschenk")
            ax2.legend(loc="best", fontsize=8)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig

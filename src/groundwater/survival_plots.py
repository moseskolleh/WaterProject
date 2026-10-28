"""The time-to-failure figure (PLAN.md step 7.4), in the house style.

One figure a grouping: for each group judged, the share still working as a
step from 100 percent at commissioning, its 95 percent band shaded behind
it, and a tick where a borehole was censored at the last report of it
working. It draws what :func:`groundwater.survival.survival_analysis`
returns, as ``charts.survivalCurves`` draws it in the browser.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from .config import HouseStyle
from .hydraulics.plots import STEP_COLOURS
from .plotting import figure_context, save_figure
from .survival import DAYS_PER_YEAR
from .text import phrase, phrase_table

__all__ = ["plot_survival", "survival_figure_title"]

#: The colours after the house accent and secondary, for a third group and
#: on: the step test's, less its first, which is the default accent.
_MORE = STEP_COLOURS[1:]


def survival_figure_title(by: str | None) -> str:
    """The figure's title: over all boreholes (``by`` None) or by a grouping."""
    if by is None:
        return phrase("survival.figure_all")
    return phrase("survival.figure_by", by=phrase_table("survival.by")[by])


def _path(steps: list[dict], key: str) -> tuple[list[float], list[float]]:
    """A step function from day nought, in years and percent, of ``key``
    (the estimate or an edge of its band): flat to each time, then down."""
    xs, ys = [0.0], [100.0]
    for step in steps:
        x = step["days"] / DAYS_PER_YEAR
        xs += [x, x]
        ys += [ys[-1], 100.0 * step[key]]
    return xs, ys


def _band(steps: list[dict]) -> tuple[list[float], list[float], list[float]]:
    """The band as steps, from the first time it has a width: x, lower and
    upper, each held flat to the next time."""
    xs: list[float] = []
    lows: list[float] = []
    highs: list[float] = []
    for i, step in enumerate(steps):
        if step["lower"] is None:
            continue
        x = step["days"] / DAYS_PER_YEAR
        end = (steps[i + 1]["days"] / DAYS_PER_YEAR) if i + 1 < len(steps) else x
        xs += [x, end]
        lows += [100.0 * step["lower"]] * 2
        highs += [100.0 * step["upper"]] * 2
    return xs, lows, highs


def plot_survival(groups: list[dict], path: str | Path, by: str | None = None,
                  style: HouseStyle | None = None) -> Path:
    """The share still working against years since commissioning, for the
    judged groups among ``groups`` (a grouping's, or the overall estimate
    alone), titled for ``by``."""
    style = style or HouseStyle()
    shown = [g for g in groups if g["judged"]]
    colours = (style.accent_color, style.secondary_color) + _MORE
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, style.figure_width_in * 0.6))
        right = 1.0
        for i, group in enumerate(shown):
            colour = colours[i % len(colours)]
            steps = group["steps"]
            xs, lows, highs = _band(steps)
            if xs:
                ax.fill_between(xs, lows, highs, color=colour, alpha=0.15, linewidth=0)
            line_x, line_y = _path(steps, "survival")
            ax.plot(line_x, line_y, color=colour, linewidth=1.6,
                    label=phrase("survival.legend", label=group["label"], n=group["n"]))
            ticks = [(s["days"] / DAYS_PER_YEAR, 100.0 * s["survival"])
                     for s in steps if s["censored"]]
            if ticks:
                ax.plot([t[0] for t in ticks], [t[1] for t in ticks], linestyle="none",
                        marker="|", markersize=7, markeredgewidth=1.2, color=colour)
            right = max(right, group["last_days"] / DAYS_PER_YEAR)
        if shown:
            ax.plot([], [], linestyle="none", marker="|", markersize=7, markeredgewidth=1.2,
                    color=style.neutral_color, label=phrase("survival.legend_censored"))
            ax.legend(loc="best")
        ax.set_xlim(0.0, right * 1.04)
        ax.set_ylim(0.0, 102.0)
        ax.set_xlabel(phrase("survival.axis_x"))
        ax.set_ylabel(phrase("survival.axis_y"))
        ax.set_title(survival_figure_title(by))
        fig.tight_layout()
    return save_figure(fig, path, style)

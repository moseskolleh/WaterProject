"""The calibration report's two figures (PLAN.md step 5.2), in the house
style.

- The depth to basement found against the depth the best fit gave, at
  every forecast point drilled: the P10 to P90 band drawn across each, the
  line where the two agree, and a hole that stopped short of basement drawn
  at its total depth, pointing down, since basement lies deeper still. A
  point whose best fit resolved no basement is drawn hollow at its band's
  P50, so it is never read as a best fit's depth.
- The reliability diagram: in each band of forecast chance, the share of
  boreholes that succeeded against the band's mean forecast, with the
  number of forecasts beside each point. Calibrated forecasts lie on the
  diagonal.

Both draw what :func:`groundwater.calibration.depth_scores` and
:func:`~groundwater.calibration.odds_scores` return, as ``charts.depthCalibration``
and ``charts.reliabilityDiagram`` draw it in the browser.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from .config import HouseStyle
from .plotting import figure_context, save_figure

__all__ = ["plot_depth_calibration", "plot_reliability"]

#: How each check is drawn: judged inside, judged outside, or not judged.
_INSIDE = ("inside",)
_OUTSIDE = ("shallower", "deeper")


def _where(point: dict) -> tuple[float | None, float | None, bool, bool]:
    """A point's place on the figure: the depth predicted (the best fit's,
    else the band's P50), the depth found or, short of basement, the total
    depth, whether it stopped short, and whether the depth predicted is the
    band's P50 for want of a best fit's."""
    band = point["band"]
    fallback = point["predicted"] is None
    x = point["predicted"] if not fallback else (band[1] if band else None)
    if point["found"] is not None:
        return x, point["found"], False, fallback
    return x, point["total_depth_m"], True, fallback


def plot_depth_calibration(depth: dict, path: str | Path, style: HouseStyle | None = None) -> Path:
    """The depth to basement found against the depth predicted, from
    :func:`~groundwater.calibration.depth_scores`."""
    style = style or HouseStyle()
    drawn = []
    for point in depth["points"]:
        x, y, short, fallback = _where(point)
        if x is not None and y is not None:
            drawn.append((point, x, y, short, fallback))
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, style.figure_width_in * 0.72))
        values = [1.0]
        for point, x, y, _short, _fallback in drawn:
            values += [x, y] + ([point["band"][0], point["band"][2]] if point["band"] else [])
        top = max(values) * 1.08
        ax.plot([0, top], [0, top], color=style.neutral_color, linewidth=0.9, linestyle="--",
                label="Found where predicted")
        kinds = {"inside": (style.accent_color, "Inside the band"),
                 "outside": (style.secondary_color, "Outside the band"),
                 "unjudged": (style.neutral_color, "Not judged")}
        present = set()
        for point, x, y, short, fallback in drawn:
            kind = ("inside" if point["check"] in _INSIDE else
                    "outside" if point["check"] in _OUTSIDE else "unjudged")
            present.add(kind)
            colour = kinds[kind][0]
            if point["band"]:
                ax.plot([point["band"][0], point["band"][2]], [y, y], color=colour, linewidth=1.2,
                        alpha=0.7)
            # hollow where the depth predicted is the band's P50, not a best fit's
            ax.plot([x], [y], marker="v" if short else "o", markersize=6.5 if short else 6,
                    color=colour, markerfacecolor="white" if fallback else colour,
                    markeredgecolor=colour if fallback else "white",
                    markeredgewidth=1.4 if fallback else 0.8, linestyle="none")
        # the legend names each colour by a circle, and the downward mark once
        for kind in ("inside", "outside", "unjudged"):
            if kind in present:
                ax.plot([], [], marker="o", color=kinds[kind][0], linestyle="none", label=kinds[kind][1])
        if any(entry[3] for entry in drawn):
            ax.plot([], [], marker="v", color=style.neutral_color, linestyle="none",
                    label="Stopped short of basement, at its total depth")
        if any(entry[4] for entry in drawn):
            ax.plot([], [], marker="o", color=style.neutral_color, markerfacecolor="white",
                    markeredgewidth=1.4, linestyle="none", label="No best fit: at the band's P50")
        ax.set_xlim(0, top)
        ax.set_ylim(top, 0)
        ax.set_xlabel("Depth to basement predicted by the best fit (m)")
        ax.set_ylabel("Depth to basement found (m)")
        ax.set_title("Depth to basement, predicted and found")
        ax.legend(loc="best")
        fig.tight_layout()
    return save_figure(fig, path, style)


def plot_reliability(odds: dict, path: str | Path, style: HouseStyle | None = None) -> Path:
    """The reliability diagram, from :func:`~groundwater.calibration.odds_scores`."""
    style = style or HouseStyle()
    shown = [b for b in odds["bins"] if b["n"]]
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, style.figure_width_in * 0.72))
        ax.plot([0, 100], [0, 100], color=style.neutral_color, linewidth=0.9, linestyle="--",
                label="Calibrated")
        xs = [100.0 * b["mean_p"] for b in shown]
        ys = [100.0 * b["observed"] for b in shown]
        ax.plot(xs, ys, color=style.accent_color, linewidth=1.4, marker="o", markersize=6,
                markeredgecolor="white", markeredgewidth=0.8, label="Forecasts, by band of chance")
        for b, x, y in zip(shown, xs, ys, strict=True):
            ax.annotate(f"{b['n']}", (x, y), xytext=(6, -12 if y > 88 else 5), textcoords="offset points",
                        fontsize=8, color=style.neutral_color)
        for b in odds["bins"][1:]:
            ax.axvline(100.0 * b["low"], color="#D9D9D9", linewidth=0.6, zorder=0)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_xlabel("Mean chance forecast (%)")
        ax.set_ylabel("Boreholes that succeeded (%)")
        ax.set_title("Reliability of the chance of success")
        ax.legend(loc="upper left")
        fig.tight_layout()
    return save_figure(fig, path, style)

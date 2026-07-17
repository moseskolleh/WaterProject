"""Cost breakdown and programme figures in the house style."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt

from ..config import HouseStyle
from ..plotting import figure_context, save_figure
from .model import CostEstimate


def plot_cost_breakdown(
    estimate: CostEstimate,
    path: str | Path,
    style: HouseStyle | None = None,
) -> Path:
    """Two-panel breakdown: cost by stage and by resource category.

    The same two roll-ups the RWSN costing model reports, drawn as
    horizontal bars so long stage names stay readable.
    """
    style = style or HouseStyle()
    with figure_context(style):
        fig, (ax1, ax2) = plt.subplots(
            1, 2, figsize=(style.figure_width_in * 1.35, 3.4)
        )
        for ax, pairs, title in (
            (ax1, estimate.by_stage(), "By construction stage"),
            (ax2, estimate.by_category(), "By resource category"),
        ):
            labels = [p[0].capitalize() for p in pairs][::-1]
            values = [p[1] for p in pairs][::-1]
            bars = ax.barh(labels, values, color=style.accent_color, height=0.62)
            ax.bar_label(
                bars,
                labels=[f"{v:,.0f}" for v in values],
                padding=3,
                fontsize=8,
                color=style.neutral_color,
            )
            ax.set_xlabel("USD")
            ax.set_title(title)
            ax.set_xlim(0, max(values) * 1.22 if values else 1)
            ax.grid(axis="y", visible=False)
        fig.suptitle(
            f"Direct works cost {estimate.direct_cost_usd:,.0f} USD",
            fontweight="bold",
            fontsize=11,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.94))
    return save_figure(fig, path, style)


def plot_programme_gantt(
    programme,
    path: str | Path,
    style: HouseStyle | None = None,
) -> Path:
    """Indicative programme of works for a borehole package.

    Single rig schedule in the layout of the RWSN supervision guide's
    example programme: mobilisation, siting, a drilling front moving
    through the communities, then testing, platforms, pump
    installation and demobilisation.
    """
    style = style or HouseStyle()
    days_per_well = programme.well_estimate.inputs.crew_days or 6.0
    drilling_weeks = max(1, math.ceil(programme.n_attempted * days_per_well / 6.0))
    siting_weeks = max(1, math.ceil(programme.n_attempted / 10.0))
    # (activity, start week, duration weeks) with week numbers from 1
    drill_start = 1 + siting_weeks
    rows = [
        ("Mobilisation", 1, 1),
        ("Borehole siting", 2, siting_weeks),
        ("Drilling, lining and development", drill_start, drilling_weeks),
        ("Pumping tests and water quality", drill_start + 1, drilling_weeks),
        ("Platform casting", drill_start + 2, drilling_weeks),
        ("Pump installation", drill_start + drilling_weeks, 2),
        ("Demobilisation", drill_start + drilling_weeks + 1, 1),
    ]
    total_weeks = max(start + dur - 1 for _, start, dur in rows)
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 2.9))
        for i, (label, start, dur) in enumerate(rows):
            ax.barh(
                len(rows) - 1 - i, dur, left=start - 0.5, height=0.55,
                color=style.accent_color if "Drilling" not in label
                else style.secondary_color,
                edgecolor="white",
            )
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in rows[::-1]], fontsize=8)
        ax.set_xticks(range(1, total_weeks + 1))
        ax.set_xlim(0.5, total_weeks + 0.5)
        ax.set_xlabel("Week")
        ax.grid(axis="y", visible=False)
        ax.set_title(
            f"Indicative programme: {programme.n_attempted} borehole(s), "
            f"one rig, about {total_weeks} weeks"
        )
        fig.tight_layout()
    return save_figure(fig, path, style)

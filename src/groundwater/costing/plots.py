"""Cost breakdown figures in the house style."""

from __future__ import annotations

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

"""Shared matplotlib styling: one accent colour, clean grids, no clutter.

Every figure in the toolkit goes through :func:`figure_context` so
reports look uniform. The style follows the house rules: white
background, a single accent colour with one secondary colour for
overlays, no unnecessary ornamentation.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from .config import HouseStyle

_DEFAULT = HouseStyle()


@contextmanager
def figure_context(style: HouseStyle | None = None):
    """rcParams context applying the house style."""
    style = style or _DEFAULT
    rc = {
        "figure.facecolor": style.background,
        "axes.facecolor": style.background,
        "savefig.facecolor": style.background,
        "axes.edgecolor": "#666666",
        "axes.labelcolor": "#222222",
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.grid": True,
        "grid.color": "#D9D9D9",
        "grid.linewidth": 0.6,
        "grid.linestyle": "-",
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "xtick.color": "#444444",
        "ytick.color": "#444444",
        "legend.fontsize": 9,
        "legend.framealpha": 0.95,
        "legend.edgecolor": "#CCCCCC",
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "lines.linewidth": 1.6,
        "figure.dpi": 110,
    }
    with plt.rc_context(rc):
        yield


def save_figure(fig, path: str | Path, style: HouseStyle | None = None) -> Path:
    """Save with consistent DPI and tight layout; return the path."""
    style = style or _DEFAULT
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=style.figure_dpi, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)
    return path


RESISTIVITY_CMAP = "viridis"

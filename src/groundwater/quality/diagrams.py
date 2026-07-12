"""Hydrochemical facies diagrams: Piper and Stiff.

Both work from the meq/L values produced by the ionic balance module,
so they need the major ions to be present in the sample. Multiple
samples can be plotted on one Piper diagram for comparison.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ..config import HouseStyle
from ..models import WaterQualitySample
from ..plotting import figure_context, save_figure
from .ionic import ionic_balance

_SQ3 = np.sqrt(3.0)


def _ternary_xy(a: float, b: float, c: float, origin=(0.0, 0.0), size=1.0):
    """Barycentric (a bottom-left, b bottom-right, c top) to xy."""
    total = a + b + c
    if total <= 0:
        return None
    a, b, c = a / total, b / total, c / total
    x = origin[0] + (b + 0.5 * c) * size
    y = origin[1] + (_SQ3 / 2.0) * c * size
    return x, y


def _triangle(ax, origin, size, labels, ticks=True):
    x0, y0 = origin
    verts = np.array(
        [[x0, y0], [x0 + size, y0], [x0 + 0.5 * size, y0 + _SQ3 / 2 * size], [x0, y0]]
    )
    ax.plot(verts[:, 0], verts[:, 1], color="#444444", lw=1.2)
    for frac in (0.2, 0.4, 0.6, 0.8):
        # grid lines parallel to each side
        ax.plot(
            [x0 + frac * size, x0 + 0.5 * size + 0.5 * frac * size],
            [y0, y0 + _SQ3 / 2 * size * (1 - frac)],
            color="#DDDDDD", lw=0.6, zorder=0,
        )
        ax.plot(
            [x0 + (1 - frac) * size, x0 + 0.5 * size - 0.5 * frac * size],
            [y0, y0 + _SQ3 / 2 * size * (1 - frac)],
            color="#DDDDDD", lw=0.6, zorder=0,
        )
        ax.plot(
            [x0 + 0.5 * frac * size, x0 + size - 0.5 * frac * size],
            [y0 + _SQ3 / 2 * size * frac, y0 + _SQ3 / 2 * size * frac],
            color="#DDDDDD", lw=0.6, zorder=0,
        )
    la, lb, lc = labels
    ax.text(x0 - 0.03, y0 - 0.05, la, ha="right", va="top", fontsize=9)
    ax.text(x0 + size + 0.03, y0 - 0.05, lb, ha="left", va="top", fontsize=9)
    ax.text(x0 + 0.5 * size, y0 + _SQ3 / 2 * size + 0.04, lc, ha="center", fontsize=9)


def plot_piper(
    samples: list[WaterQualitySample],
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Piper diagram",
):
    """Piper trilinear diagram for one or more samples.

    The diamond point is the classical construction: the intersection
    of the +60 degree line through the cation point and the -60 degree
    line through the anion point. Samples without a complete major ion
    analysis are skipped.
    """
    style = style or HouseStyle()
    size = 1.0
    gap = 0.18
    cat_origin = (0.0, 0.0)
    an_origin = (size + gap, 0.0)

    # diamond vertices from the projection geometry
    x_mid = size + gap / 2.0
    y_bot = _SQ3 / 2.0 * gap
    diamond = np.array(
        [
            [x_mid, y_bot],  # bottom: Ca+Mg with HCO3
            [x_mid + size / 2.0, y_bot + _SQ3 / 2.0 * size],  # right: Na+K with SO4+Cl
            [x_mid, y_bot + _SQ3 * size],  # top: Ca+Mg with SO4+Cl
            [x_mid - size / 2.0, y_bot + _SQ3 / 2.0 * size],  # left
            [x_mid, y_bot],
        ]
    )

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in * 0.9, 5.6))
        ax.set_aspect("equal")
        ax.axis("off")
        _triangle(ax, cat_origin, size, ("Ca", "Na+K", "Mg"))
        _triangle(ax, an_origin, size, ("HCO3", "Cl", "SO4"))
        ax.plot(diamond[:, 0], diamond[:, 1], color="#444444", lw=1.2)
        ax.annotate(
            "SO4 + Cl increases upward; Na + K increases to the right",
            xy=(x_mid, y_bot + _SQ3 * size + 0.06),
            ha="center", fontsize=7.5, color="#555555",
        )

        markers = ["o", "s", "^", "D", "v", "P", "X"]
        plotted = []
        for i, sample in enumerate(samples):
            ionic = ionic_balance(sample)
            if ionic is None:
                continue
            cat = ionic.cations_meq
            an = ionic.anions_meq
            ca, mg = cat.get("calcium", 0), cat.get("magnesium", 0)
            nak = cat.get("sodium", 0) + cat.get("potassium", 0)
            cl = an.get("chloride", 0)
            so4 = an.get("sulfate", 0)
            hco3 = an.get("bicarbonate", 0) + an.get("carbonate", 0)

            p_cat = _ternary_xy(ca, nak, mg, cat_origin, size)
            p_an = _ternary_xy(hco3, cl, so4, an_origin, size)
            if p_cat is None or p_an is None:
                continue
            # intersection of +60 deg line through the cation point and
            # -60 deg line through the anion point
            xc, yc = p_cat
            xa, ya = p_an
            xd = 0.5 * (xc + xa) + (ya - yc) / (2.0 * _SQ3)
            yd = yc + _SQ3 * (xd - xc)
            marker = markers[i % len(markers)]
            label = sample.sample_id or sample.site.community or f"sample {i + 1}"
            color = style.accent_color if i % 2 == 0 else style.secondary_color
            first = True
            for px, py in ((xc, yc), (xa, ya), (xd, yd)):
                ax.plot(px, py, marker, ms=6, mfc=color, mec="white", mew=0.8,
                        label=label if first else None)
                first = False
            plotted.append(label)
        if plotted:
            ax.legend(loc="upper left", fontsize=8, frameon=True)
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def plot_stiff(
    sample: WaterQualitySample,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str | None = None,
):
    """Stiff diagram: Na+K / Ca / Mg on the left, Cl / HCO3 / SO4 right."""
    style = style or HouseStyle()
    ionic = ionic_balance(sample)
    if ionic is None:
        raise ValueError("Stiff diagram needs the major ions (Ca, Mg, Na, Cl, HCO3)")
    cat = ionic.cations_meq
    an = ionic.anions_meq
    rows = [
        (cat.get("sodium", 0) + cat.get("potassium", 0), an.get("chloride", 0), "Na+K", "Cl"),
        (cat.get("calcium", 0), an.get("bicarbonate", 0) + an.get("carbonate", 0), "Ca", "HCO3"),
        (cat.get("magnesium", 0), an.get("sulfate", 0), "Mg", "SO4"),
    ]
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in * 0.7, 2.8))
        ys = [2, 1, 0]
        xs_left = [-r[0] for r in rows]
        xs_right = [r[1] for r in rows]
        poly_x = xs_left + xs_right[::-1]
        poly_y = ys + ys[::-1]
        ax.fill(poly_x, poly_y, color=style.accent_color, alpha=0.25, lw=0)
        ax.plot(poly_x + [poly_x[0]], poly_y + [poly_y[0]], color=style.accent_color, lw=1.6)
        ax.axvline(0, color="#555555", lw=1.0)
        for y, (c_meq, a_meq, c_label, a_label) in zip(ys, rows):
            ax.plot([-c_meq], [y], "o", ms=4, color=style.accent_color)
            ax.plot([a_meq], [y], "o", ms=4, color=style.accent_color)
            ax.text(ax.get_xlim()[0], y, "", fontsize=8)
        span = max(max(map(abs, xs_left)), max(xs_right), 0.5) * 1.3
        ax.set_xlim(-span, span)
        ax.set_ylim(-0.6, 2.6)
        for y, (c, a, c_label, a_label) in zip(ys, rows):
            ax.text(-span * 0.98, y, c_label, ha="left", va="center", fontsize=9)
            ax.text(span * 0.98, y, a_label, ha="right", va="center", fontsize=9)
        ax.set_yticks([])
        ax.set_xlabel("meq/L (cations left, anions right)")
        ax.set_title(title or f"Stiff diagram - {sample.sample_id or sample.site.community}")
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig

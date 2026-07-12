"""VES figures: sounding curves with models, layer pseudo-sections and
multi-sounding geoelectric cross-sections."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colors as mcolors
from matplotlib import cm

from ..config import HouseStyle
from ..models import LayeredModel, VESSounding
from ..plotting import figure_context, save_figure
from ..utils import fmt_num
from .forward import forward_schlumberger
from .splice import splice_segments

__all__ = [
    "plot_sounding_curve",
    "plot_model_pseudosection",
    "plot_geoelectric_section",
]

_RHO_NORM = mcolors.LogNorm(vmin=10, vmax=5000)


def _model_step(model: LayeredModel, depth_max: float) -> tuple[np.ndarray, np.ndarray]:
    """Stepwise rho(z) profile for plotting."""
    tops = model.depths_top
    rho = model.resistivities
    z = [0.0]
    r = [rho[0]]
    for i in range(1, len(rho)):
        z.extend([tops[i], tops[i]])
        r.extend([rho[i - 1], rho[i]])
    z.append(depth_max)
    r.append(rho[-1])
    return np.array(z), np.array(r)


def plot_sounding_curve(
    sounding: VESSounding,
    model: LayeredModel | None = None,
    rho_calc: np.ndarray | None = None,
    ab2_calc: np.ndarray | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    show_splice: bool = True,
):
    """Log-log sounding curve with optional fitted model panel.

    Left: apparent resistivity against AB/2 with the field segments,
    the spliced curve and the model response. Right: the layered model
    as a resistivity-depth step plot, annotated with the fit error.
    """
    style = style or HouseStyle()
    with figure_context(style):
        if model is not None:
            fig, (ax, axm) = plt.subplots(
                1, 2, figsize=(style.figure_width_in, 3.4), width_ratios=[1.6, 1]
            )
        else:
            fig, ax = plt.subplots(figsize=(style.figure_width_in * 0.75, 3.4))
            axm = None

        # field segments
        markers = ["o", "s", "^", "D", "v", "P"]
        for k, idx in enumerate(sounding.segments()):
            mn = sounding.mn[idx][0] if len(idx) else float("nan")
            label = f"MN = {fmt_num(mn)} m" if np.isfinite(mn) else "field data"
            ax.loglog(
                sounding.ab2[idx],
                sounding.rho_app[idx],
                markers[k % len(markers)],
                ms=4.5,
                mfc="white",
                mec=style.accent_color,
                mew=1.2,
                ls="none",
                label=label,
            )
        if show_splice and len(sounding.segments()) > 1:
            ab2_s, rho_s, _ = splice_segments(sounding)
            ax.loglog(
                ab2_s, rho_s, "-", color=style.accent_color, lw=1.0, alpha=0.8,
                label="spliced curve",
            )
        if model is not None:
            if rho_calc is None or ab2_calc is None:
                ab2_calc = np.geomspace(sounding.ab2.min(), sounding.ab2.max(), 60)
                rho_calc = forward_schlumberger(model, ab2_calc)
            ax.loglog(
                ab2_calc, rho_calc, "-", color=style.secondary_color, lw=1.8,
                label="model response",
            )
        ax.set_xlabel("AB/2 (m)")
        ax.set_ylabel("Apparent resistivity (ohm-m)")
        ax.set_title(f"{sounding.label} sounding curve")
        ax.legend(loc="best")
        ax.grid(True, which="both")

        if axm is not None and model is not None:
            depth_max = max(float(np.max(sounding.ab2)), model.depths_top[-1] * 1.5 + 5)
            z, r = _model_step(model, depth_max)
            axm.plot(r, z, color=style.secondary_color, lw=2.0)
            axm.set_xscale("log")
            axm.set_ylim(depth_max, 0)
            axm.set_xlabel("Layer resistivity (ohm-m)")
            axm.set_ylabel("Depth (m)")
            err = model.fit_error_percent
            title = "Layered model"
            if err is not None:
                title += f" (ERR = {err:.1f}%)"
            axm.set_title(title)
            tops = model.depths_top
            for i, row in enumerate(model.as_table()):
                top = tops[i]
                bottom = tops[i + 1] if i + 1 < len(tops) else depth_max
                z_label = 0.5 * (top + min(bottom, depth_max))
                axm.annotate(
                    f"{fmt_num(row['rho_ohm_m'], 4)}",
                    xy=(row["rho_ohm_m"], z_label),
                    xytext=(3, 0), textcoords="offset points",
                    fontsize=7.5, va="center", color="#333333",
                )
            axm.grid(True, which="both")
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def plot_model_pseudosection(
    model: LayeredModel,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    depth_max: float | None = None,
    title: str | None = None,
):
    """Single sounding layer column coloured by resistivity.

    The 'pseudo-section showing apparent resistivity and layer
    thicknesses' figure of the survey reports: horizontal bands to
    scale with a logarithmic resistivity colour bar.
    """
    style = style or HouseStyle()
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in * 0.72, 3.6))
        tops = model.depths_top
        if depth_max is None:
            depth_max = (tops[-1] if len(tops) > 1 else 10) * 1.35 + 3
        cmap = plt.get_cmap("viridis")
        for i, rho in enumerate(model.resistivities):
            top = tops[i]
            bottom = tops[i + 1] if i + 1 < len(tops) else depth_max
            ax.axhspan(top, bottom, color=cmap(_RHO_NORM(max(rho, _RHO_NORM.vmin))))
            z_text = (top + min(bottom, depth_max)) / 2
            ax.text(
                0.5, z_text, f"{fmt_num(rho, 4)} ohm-m",
                ha="center", va="center", fontsize=9,
                color="white", transform=ax.get_yaxis_transform(),
                path_effects=None,
                bbox=dict(boxstyle="round,pad=0.25", fc="#00000055", ec="none"),
            )
        for z in tops[1:]:
            ax.axhline(z, color="white", lw=1.0)
        ax.set_ylim(depth_max, 0)
        ax.set_xlim(0, 1)
        ax.set_xticks([])
        ax.set_ylabel("Depth (m)")
        ax.set_title(title or f"{model.sounding_id or 'VES'} layer section")
        sm = cm.ScalarMappable(norm=_RHO_NORM, cmap=cmap)
        cbar = fig.colorbar(sm, ax=ax, pad=0.04)
        cbar.set_label("Resistivity (ohm-m)")
        ax.grid(False)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def plot_geoelectric_section(
    models: list[LayeredModel],
    positions: list[float] | None = None,
    labels: list[str] | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    depth_max: float | None = None,
    title: str = "Interpreted geoelectric cross-section",
):
    """Cross-section through several soundings along a profile.

    Each sounding is drawn as a column at its chainage; layer
    boundaries are connected between adjacent soundings.
    """
    style = style or HouseStyle()
    if positions is None:
        positions = list(np.arange(len(models), dtype=float) * 100.0)
    if labels is None:
        labels = [m.sounding_id or f"VES {i + 1}" for i, m in enumerate(models)]
    if depth_max is None:
        depth_max = max(
            (m.depths_top[-1] if m.n_layers > 1 else 10) * 1.35 + 5 for m in models
        )
    span = max(positions) - min(positions) or 100.0
    half_w = span / (len(models) * 2.6)
    cmap = plt.get_cmap("viridis")

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 3.6))
        for x, model in zip(positions, models):
            tops = model.depths_top
            for i, rho in enumerate(model.resistivities):
                top = tops[i]
                bottom = tops[i + 1] if i + 1 < len(tops) else depth_max
                ax.fill_between(
                    [x - half_w, x + half_w], top, bottom,
                    color=cmap(_RHO_NORM(max(rho, _RHO_NORM.vmin))), lw=0,
                )
            for z in tops[1:]:
                ax.plot([x - half_w, x + half_w], [z, z], color="white", lw=1.0)
        # connect boundaries between neighbouring soundings
        for a in range(len(models) - 1):
            m1, m2 = models[a], models[a + 1]
            n_shared = min(m1.n_layers, m2.n_layers) - 1
            for k in range(1, n_shared + 1):
                z1 = m1.depths_top[k] if k < m1.n_layers else None
                z2 = m2.depths_top[k] if k < m2.n_layers else None
                if z1 is None or z2 is None:
                    continue
                ax.plot(
                    [positions[a] + half_w, positions[a + 1] - half_w],
                    [z1, z2],
                    color="#777777", lw=1.0, ls="--",
                )
        for x, label in zip(positions, labels):
            ax.text(
                x, depth_max * 0.035, label, ha="center", va="top", fontsize=9,
                fontweight="bold", color=style.accent_color,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85),
            )
        ax.set_ylim(depth_max, 0)
        ax.set_xlabel("Distance along profile (m)")
        ax.set_ylabel("Depth (m)")
        ax.set_title(title)
        sm = cm.ScalarMappable(norm=_RHO_NORM, cmap=cmap)
        cbar = fig.colorbar(sm, ax=ax, pad=0.03)
        cbar.set_label("Resistivity (ohm-m)")
        ax.grid(False)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig

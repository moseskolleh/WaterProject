"""VES figures: sounding curves with models, layer pseudo-sections and
multi-sounding geoelectric cross-sections."""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colors as mcolors
from matplotlib import cm

from ..config import HouseStyle
from ..models import LayeredModel, VESSounding
from ..plotting import figure_context, save_figure
from ..utils import fmt_num
from .forward import forward_schlumberger, forward_wenner
from .splice import splice_segments

__all__ = [
    "plot_sounding_curve",
    "plot_model_pseudosection",
    "plot_geoelectric_section",
]

#: The house colour scale for layer resistivity when nothing better is
#: known. A figure fits its own scale to the models it draws (see
#: :func:`_rho_norm`): a fixed 10-5,000 ohm-m ramp coloured 3 ohm-m saline
#: clay the same as 10 ohm-m fresh-water clay and 20,000 ohm-m basement
#: the same as 5,000, with nothing on the bar to say it had clipped.
_RHO_NORM = mcolors.LogNorm(vmin=10, vmax=5000)


def _rho_norm(models: list[LayeredModel]) -> mcolors.LogNorm:
    """A log colour scale spanning the decades the drawn models occupy."""
    rho = np.concatenate([np.asarray(m.resistivities, float) for m in models]) \
        if models else np.array([])
    rho = rho[np.isfinite(rho) & (rho > 0)]
    if not rho.size:
        return _RHO_NORM
    lo = 10 ** np.floor(np.log10(rho.min()))
    hi = 10 ** np.ceil(np.log10(rho.max()))
    if hi <= lo:
        hi = lo * 10
    return mcolors.LogNorm(vmin=float(lo), vmax=float(hi))


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
    depth_max: float | None = None,
    reference_model: LayeredModel | None = None,
    reference_label: str = "reference model",
):
    """Log-log sounding curve with optional fitted model panel.

    Left: apparent resistivity against AB/2 with the field segments,
    the spliced curve and the model response. Right: the layered model
    as a resistivity-depth step plot, annotated with the fit error.

    ``depth_max`` is the depth of investigation the panel is drawn to;
    left unset it is the toolkit's default fraction of the largest AB/2,
    the same rule the interpretation uses, so the panel no longer runs to
    the electrode spacing while the layer column beside it stops at half
    of it. ``reference_model`` (an imported IPI2Win model, say) is drawn
    dashed on both panels so the two interpretations can be read together.
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
                # the array decides the kernel: drawing a Schlumberger
                # response over Wenner readings shows a model that misses
                # its own data by tens of percent
                rho_calc = (
                    forward_wenner(model, ab2_calc)
                    if sounding.array_type.startswith("wenner")
                    else forward_schlumberger(model, ab2_calc)
                )
            ax.loglog(
                ab2_calc, rho_calc, "-", color=style.secondary_color, lw=1.8,
                label="model response",
            )
        if reference_model is not None:
            ab2_ref = np.geomspace(sounding.ab2.min(), sounding.ab2.max(), 60)
            rho_ref = (
                forward_wenner(reference_model, ab2_ref)
                if sounding.array_type.startswith("wenner")
                else forward_schlumberger(reference_model, ab2_ref)
            )
            ax.loglog(ab2_ref, rho_ref, "--", color="#777777", lw=1.2,
                      label=reference_label)
        # a Wenner sounding's x axis is the spacing a, not half AB
        ax.set_xlabel(
            "a (m)" if sounding.array_type.startswith("wenner") else "AB/2 (m)"
        )
        ax.set_ylabel("Apparent resistivity (ohm-m)")
        ax.set_title(f"{sounding.label} sounding curve")
        # the curve runs from top left to bottom right, so the lower left is
        # the one corner the legend cannot cover data in
        ax.legend(loc="lower left", fontsize=7)
        ax.grid(True, which="both")

        if axm is not None and model is not None:
            from .interpret import depth_of_investigation

            if depth_max is None:
                depth_max = depth_of_investigation(float(np.max(sounding.ab2)))
            # the deepest interface must stay on the panel, or the model
            # shown is not the model fitted
            depth_max = max(float(depth_max), model.depths_top[-1] * 1.2 + 2.0)
            z, r = _model_step(model, depth_max)
            axm.plot(r, z, color=style.secondary_color, lw=2.0, label="fitted model")
            if reference_model is not None:
                z_ref, r_ref = _model_step(reference_model, depth_max)
                axm.plot(r_ref, z_ref, "--", color="#777777", lw=1.2,
                         label=reference_label)
                axm.legend(loc="lower right", fontsize=7)
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
            n = model.n_layers
            for i, row in enumerate(model.as_table()):
                top = tops[i]
                bottom = tops[i + 1] if i + 1 < len(tops) else depth_max
                # a label sits in the middle of its layer, but a thin top
                # layer's middle is under the frame and the half-space has
                # no middle: it is labelled just under its top, and said to
                # be the half-space rather than a layer ending at the axis
                if i == n - 1:
                    z_label = top + 0.08 * depth_max
                    text = f"{fmt_num(row['rho_ohm_m'], 4)} (half-space)"
                else:
                    z_label = max(0.5 * (top + min(bottom, depth_max)), 0.035 * depth_max)
                    text = fmt_num(row["rho_ohm_m"], 4)
                axm.annotate(
                    text,
                    xy=(row["rho_ohm_m"], z_label),
                    xytext=(4, 0), textcoords="offset points",
                    fontsize=7.5, va="center", color="#333333",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85),
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
        norm = _rho_norm([model])
        for i, rho in enumerate(model.resistivities):
            top = tops[i]
            bottom = tops[i + 1] if i + 1 < len(tops) else depth_max
            ax.axhspan(top, bottom, color=cmap(norm(max(rho, norm.vmin))))
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
        sm = cm.ScalarMappable(norm=norm, cmap=cmap)
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
    half_width_m: float | None = None,
    note: str = "",
    correlate: list[bool] | None = None,
):
    """Cross-section through several soundings along a profile.

    Each sounding is drawn as a column at its chainage; layer
    boundaries are connected between adjacent soundings where
    ``correlate`` (one flag per adjacent pair, all True by default) allows
    it - a caller that knows two stations are too far apart to share a
    horizon passes False for that gap and the columns stand alone.

    ``half_width_m`` is how much ground either side of the peg a column
    stands for. The default divides the profile between the soundings,
    which is fine for the evenly spaced default positions and wrong for
    real ones: two soundings 20 km apart came out as two columns 8 km
    wide, which says the sounding measured 8 km of ground. Pass the
    sounding's own lateral reach - its largest electrode half-spacing is
    the defensible number - and the column stands for what it sampled.

    ``note`` is printed under the axes. Use it to say what the figure
    cannot: chiefly that a correlation drawn across a gap much larger
    than the depth of investigation is a line between two points, not a
    horizon anybody traced.
    """
    style = style or HouseStyle()
    if not models:
        raise ValueError("a geoelectric section needs at least one sounding model")
    if positions is None:
        positions = list(np.arange(len(models), dtype=float) * 100.0)
    if labels is None:
        labels = [m.sounding_id or f"VES {i + 1}" for i, m in enumerate(models)]
    # The three lists are read as one column per sounding, so they have to
    # agree. A caller that derives them separately can desynchronise them: the
    # workbook reader skips a sheet whose resistivity column was never
    # labelled, which leaves the models one short of a chainage list typed by
    # hand. Zipped, that draws the section with a sounding silently dropped or
    # the labels off by one - neither of which is visible in the finished
    # figure, and both of which reach a signed survey report.
    if len(positions) != len(models) or len(labels) != len(models):
        raise ValueError(
            f"{len(models)} soundings need {len(models)} positions and "
            f"{len(models)} labels; got {len(positions)} and {len(labels)}"
        )
    if depth_max is None:
        depth_max = max(
            (m.depths_top[-1] if m.n_layers > 1 else 10) * 1.35 + 5 for m in models
        )
    span = max(positions) - min(positions) or 100.0
    if half_width_m is not None:
        # never wider than the ground to the next peg, or the columns
        # overlap and the section reads as one continuous exposure
        ordered_x = sorted(positions)
        gaps = [b - a for a, b in zip(ordered_x, ordered_x[1:], strict=False)]
        limit = min(gaps) / 2.2 if gaps else span
        half_w = max(min(float(half_width_m), limit), span * 0.004)
    else:
        half_w = span / (len(models) * 2.6)
    cmap = plt.get_cmap("viridis")
    norm = _rho_norm(models)
    if correlate is None:
        correlate = [True] * max(len(models) - 1, 0)
    if len(correlate) != max(len(models) - 1, 0):
        raise ValueError(
            f"{len(models)} soundings have {max(len(models) - 1, 0)} gaps between "
            f"them; got {len(correlate)} correlation flags"
        )

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 3.6))
        for x, model in zip(positions, models, strict=True):
            tops = model.depths_top
            for i, rho in enumerate(model.resistivities):
                top = tops[i]
                bottom = tops[i + 1] if i + 1 < len(tops) else depth_max
                ax.fill_between(
                    [x - half_w, x + half_w], top, bottom,
                    color=cmap(norm(max(rho, norm.vmin))), lw=0,
                )
            for z in tops[1:]:
                ax.plot([x - half_w, x + half_w], [z, z], color="white", lw=1.0)
        # connect boundaries between neighbouring soundings
        for a in range(len(models) - 1):
            if not correlate[a]:
                continue
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
        for x, label in zip(positions, labels, strict=True):
            ax.text(
                x, depth_max * 0.035, label, ha="center", va="top", fontsize=9,
                fontweight="bold", color=style.accent_color,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85),
            )
        ax.set_ylim(depth_max, 0)
        ax.set_xlabel("Distance along profile (m)")
        ax.set_ylabel("Depth (m)")
        if note:
            ax.text(0.5, -0.30, textwrap.fill(note, 104),
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=7, color="#B00020")
        ax.set_title(title)
        sm = cm.ScalarMappable(norm=norm, cmap=cmap)
        cbar = fig.colorbar(sm, ax=ax, pad=0.03)
        cbar.set_label("Resistivity (ohm-m)")
        ax.grid(False)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig

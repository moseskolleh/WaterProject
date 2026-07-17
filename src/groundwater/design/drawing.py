"""To-scale borehole design schematic.

Draws the lithology column beside the construction column with a
shared depth axis, in the layout of the contractor borehole record
sheets: header block, formation profile on the left, borehole diagram
with annotated construction elements on the right, water strikes and
static water level marked, and a legend.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from ..config import HouseStyle
from ..models import DrillingLog
from ..plotting import figure_context, save_figure
from .designer import BoreholeDesign

# lithology keyword -> (colour, hatch)
_LITHO_STYLES = [
    (("topsoil", "lateritic topsoil"), ("#8B5A2B", "")),
    (("laterite", "clayey laterites"), ("#C4703E", "")),
    (("clay",), ("#B8860B", "--")),
    (("saprolite", "weathered granite fragments"), ("#D2B48C", "..")),
    (("sand", "gravel"), ("#E8D8A0", "..")),
    (("fracture", "fractured"), ("#9FB6CD", "xx")),
    (("granite", "gneiss", "basement", "bedrock", "rock"), ("#A9A9A9", "++")),
]
_DEFAULT_LITHO = ("#CCCCCC", "")


def _litho_style(description: str) -> tuple[str, str]:
    text = description.lower()
    for keywords, style in _LITHO_STYLES:
        if any(k in text for k in keywords):
            return style
    return _DEFAULT_LITHO


def _stack_labels(
    entries: list[tuple[float, ...]], min_gap: float, y_min: float, y_max: float
) -> list[tuple[float, tuple]]:
    """Place labels without overlap and inside the axis.

    Labels are sorted by their anchor depth, pushed down until they no
    longer collide, then pulled back up from the bottom so nothing
    ends up outside ``y_max``. Returns ``(label_y, entry)`` pairs.
    """
    placed: list[tuple[float, tuple]] = []
    level = y_min
    for entry in sorted(entries, key=lambda e: e[0]):
        y = max(entry[0], level)
        placed.append((y, entry))
        level = y + min_gap
    limit = y_max
    for i in range(len(placed) - 1, -1, -1):
        y, entry = placed[i]
        if y > limit:
            y = limit
            placed[i] = (y, entry)
        limit = y - min_gap
    return placed


def draw_borehole_design(
    design: BoreholeDesign,
    log: DrillingLog | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str | None = None,
    header_pairs: list[tuple[str, str]] | None = None,
):
    """Draw the design; returns the saved path (or the figure)."""
    style = style or HouseStyle()
    depth = design.total_depth_m
    stick = design.stickup_m
    y_top = -stick - 1.2  # air above ground

    with figure_context(style):
        fig, (ax_l, ax_c) = plt.subplots(
            1, 2, figsize=(style.figure_width_in, 8.2), sharey=True,
            width_ratios=[1.0, 1.35],
        )
        for ax in (ax_l, ax_c):
            ax.set_ylim(depth + depth * 0.04, y_top)
            ax.grid(False)
            # no frame box: the old right/bottom spines ran through the
            # depth labels; the drawing carries its own outlines
            for side in ("top", "right", "bottom"):
                ax.spines[side].set_visible(False)
        ax_c.spines["left"].set_visible(False)
        ax_c.tick_params(left=False, labelleft=False)

        # ------------------------------------------------------------------
        # left: lithology column
        # ------------------------------------------------------------------
        ax_l.set_xlim(0, 1.02)
        ax_l.set_xticks([])
        ax_l.set_ylabel("Depth (m)")
        ax_l.set_title("Formation / profile", fontsize=10)
        if log is not None and log.intervals:
            litho_entries = []
            for interval in log.intervals:
                color, hatch = _litho_style(interval.description)
                ax_l.add_patch(
                    Rectangle(
                        (0.08, interval.top_m), 0.36, interval.thickness_m,
                        facecolor=color, hatch=hatch, edgecolor="#555555", lw=0.6,
                    )
                )
                wrapped = textwrap.fill(interval.description, 30)
                mid = (interval.top_m + interval.bottom_m) / 2
                litho_entries.append((mid, wrapped))
            gap = depth / 26.0
            for label_y, (mid, wrapped) in _stack_labels(
                litho_entries, gap, y_top + gap, depth + depth * 0.02
            ):
                ax_l.text(0.50, label_y, wrapped, fontsize=6.5, va="center",
                          linespacing=1.1)
        else:
            ax_l.text(0.5, depth / 2, "no drilling log", ha="center", fontsize=9,
                      color="#888888")
        ax_l.axhline(0, color="#333333", lw=1.2)
        ax_l.text(0.02, -0.6, "GL", fontsize=7, color="#333333")

        # ------------------------------------------------------------------
        # right: construction column
        # ------------------------------------------------------------------
        ax_c.set_xlim(0, 1.16)
        ax_c.set_xticks([])
        ax_c.set_title(
            f'Borehole diagram ({design.borehole_diameter_in:g}" hole, '
            f'{design.casing_diameter_in:g}" {design.casing_material})',
            fontsize=10,
        )
        x_hole, w_hole = 0.30, 0.26
        x_case = x_hole + w_hole / 2 - 0.055
        w_case = 0.11

        # annulus fills
        seal_top, seal_bot = design.sanitary_seal
        back_top, back_bot = design.backfill
        grav_top, grav_bot = design.gravel_pack
        for (top, bot), (color, hatch, label) in (
            ((seal_top, seal_bot), ("#B0B0B0", "//", "cement sanitary seal")),
            ((back_top, back_bot), ("#E0D5C0", "", "backfill")),
            ((grav_top, grav_bot), ("#F0E3B2", "..", "gravel pack")),
        ):
            ax_c.add_patch(
                Rectangle((x_hole, top), w_hole, bot - top, facecolor=color,
                          hatch=hatch, edgecolor="#777777", lw=0.5)
            )
        # borehole wall
        ax_c.plot([x_hole, x_hole], [0, depth], color="#333333", lw=1.4)
        ax_c.plot([x_hole + w_hole, x_hole + w_hole], [0, depth], color="#333333", lw=1.4)
        ax_c.plot([x_hole, x_hole + w_hole], [depth, depth], color="#333333", lw=1.6)

        # casing string
        for segment in design.segments:
            if segment.kind == "screen":
                face, hatch = "white", "---"
                edge = style.accent_color
            elif segment.kind == "sump":
                face, hatch = "#D8D8D8", ""
                edge = "#333333"
            else:
                face, hatch = "white", ""
                edge = "#333333"
            ax_c.add_patch(
                Rectangle((x_case, segment.top_m), w_case,
                          segment.bottom_m - segment.top_m,
                          facecolor=face, hatch=hatch, edgecolor=edge, lw=1.0,
                          zorder=5)
            )
        # stick-up and cap
        ax_c.add_patch(
            Rectangle((x_case, -stick), w_case, stick, facecolor="white",
                      edgecolor="#333333", lw=1.0, zorder=5)
        )
        ax_c.plot([x_case - 0.02, x_case + w_case + 0.02], [-stick, -stick],
                  color="#333333", lw=2.0, zorder=6)
        # bottom plug
        ax_c.add_patch(
            Rectangle((x_case, depth - 0.6), w_case, 0.6, facecolor="#555555",
                      edgecolor="#333333", zorder=6)
        )
        # ground line
        ax_c.axhline(0, color="#333333", lw=1.2)

        # water level marker and strikes (labels join the right-hand
        # column below so nothing is written across the annulus)
        neutral = "#999999"
        annos: list[tuple[float, str, str]] = []  # (anchor depth, text, colour)
        if design.static_water_level_m is not None:
            swl = design.static_water_level_m
            ax_c.plot([x_case + w_case / 2], [swl], marker="v", ms=8,
                      color=style.accent_color, zorder=7)
            annos.append((swl, f"SWL {swl:.2f} m", style.accent_color))
        for strike in design.water_strikes_m:
            ax_c.annotate(
                "", xy=(x_hole, strike), xytext=(x_hole - 0.09, strike),
                arrowprops=dict(arrowstyle="->", color="#2A6EBB", lw=1.4),
            )
            ax_c.text(x_hole - 0.10, strike, f"{strike:g} m", fontsize=7,
                      ha="right", va="center", color="#2A6EBB")
        if design.pump_intake_m is not None:
            y = design.pump_intake_m
            ax_c.add_patch(Rectangle((x_case + 0.015, y - 1.2), w_case - 0.03, 1.2,
                                     facecolor=style.secondary_color, zorder=8))
            annos.append((y - 0.6, f"pump intake {y:.0f} m",
                          style.secondary_color))

        # right-hand annotations with depths
        screens = design.screens
        annos += [
            (seal_bot / 2 if seal_bot else 1.5,
             f"sanitary seal 0-{seal_bot:g} m", neutral),
            ((back_top + back_bot) / 2,
             f"backfill {back_top:g}-{back_bot:g} m", neutral),
            ((grav_top + min(grav_bot, depth)) / 2,
             f"gravel pack {grav_top:g}-{grav_bot:g} m", neutral),
        ]
        for s in screens:
            annos.append(((s.top_m + s.bottom_m) / 2,
                          f"screen {s.top_m:g}-{s.bottom_m:g} m", neutral))
        sump = [s for s in design.segments if s.kind == "sump"]
        if sump:
            annos.append(((sump[0].top_m + sump[0].bottom_m) / 2,
                          f"sump (sediment trap) "
                          f"{sump[0].top_m:g}-{sump[0].bottom_m:g} m",
                          neutral))
        annos.append((depth - 0.3, "bottom plug", neutral))
        x_text = x_hole + w_hole + 0.06
        min_gap = depth / 28.0
        for label_y, (anchor_y, text, color) in _stack_labels(
            annos, min_gap, y_top + min_gap, depth + depth * 0.02
        ):
            text_color = "#444444" if color == neutral else color
            ax_c.annotate(
                text, xy=(x_hole + w_hole, min(anchor_y, depth)),
                xytext=(x_text, label_y), fontsize=7.0, va="center",
                color=text_color,
                arrowprops=dict(arrowstyle="-", color=color, lw=0.7,
                                shrinkA=2, shrinkB=1),
            )

        # scale ticks every 5 m on both axes
        ticks = np.arange(0, depth + 1, 5)
        for ax in (ax_l, ax_c):
            ax.set_yticks(ticks)

        # ------------------------------------------------------------------
        # title and header block
        # ------------------------------------------------------------------
        fig.suptitle(title or "Borehole design", fontsize=12, fontweight="bold",
                     color=style.accent_color)
        if header_pairs:
            header_text = "    ".join(f"{k}: {v}" for k, v in header_pairs)
            fig.text(0.5, 0.945, header_text, ha="center", fontsize=8,
                     color="#444444")
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        if path is not None:
            return save_figure(fig, path, style)
        return fig

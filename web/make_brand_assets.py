"""Generate the toolkit brand assets (favicon icon and sidebar logo).

Draws a water droplet over a stylised water table with matplotlib (a
core dependency), so the assets can be regenerated deterministically
without any design software:

    python web/make_brand_assets.py

Outputs into ``src/groundwater/data/brand/``:

    icon.png   512x512 favicon / page icon (transparent background)
    icon.svg   hand-written vector twin, inlined as the web demo favicon
    logo.png   icon plus wordmark for the app sidebar

The PNGs ship as package data, so the Streamlit app can reference them
both in a normal installation and in the browser (stlite) demo, where
the whole package is mounted into the virtual filesystem.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "src" / "groundwater" / "data" / "brand"

ACCENT = "#1F5C8B"  # house accent (config.HouseStyle.accent_color)
ACCENT_LIGHT = "#4C9BD6"
INK = "#173B54"  # wordmark colour

# Circle-to-bezier constant for quarter arcs.
K = 0.552284749831

# The SVG twin of the matplotlib drawing below (y grows downward).
ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{light}"/>
      <stop offset="1" stop-color="{accent}"/>
    </linearGradient>
  </defs>
  <path fill="url(#g)" d="M32 4 C28 16 12 26 12 41 C12 32.95 12 41 12 41
    C12 52.05 20.95 61 32 61 C43.05 61 52 52.05 52 41 C52 26 36 16 32 4 Z"/>
  <path fill="none" stroke="#FFFFFF" stroke-width="3.6" stroke-linecap="round"
    d="M17.5 42.5 C21 38.5 25 38.5 28.5 42.5 C32 46.5 36 46.5 39.5 42.5
       C42 39.7 44.5 39.2 46.5 41"/>
  <path fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round"
    opacity="0.55"
    d="M20.5 50 C23.5 47 26.5 47 29.5 50 C32.5 53 35.5 53 38.5 50"/>
</svg>
"""


def droplet_path() -> MplPath:
    """The droplet outline in a 64x64 box, y growing upward."""
    cx, cy, r = 32.0, 23.0, 20.0  # bowl circle (y-up)
    tip = (32.0, 60.0)
    verts = [tip]
    codes = [MplPath.MOVETO]
    # right flank: tip down to the right edge of the bowl
    verts += [(36.0, 48.0), (cx + r, cy + 15.0), (cx + r, cy)]
    codes += [MplPath.CURVE4] * 3
    # bottom half circle, right edge -> bottom -> left edge
    verts += [(cx + r, cy - K * r), (cx + K * r, cy - r), (cx, cy - r)]
    codes += [MplPath.CURVE4] * 3
    verts += [(cx - K * r, cy - r), (cx - r, cy - K * r), (cx - r, cy)]
    codes += [MplPath.CURVE4] * 3
    # left flank: mirror of the right
    verts += [(cx - r, cy + 15.0), (28.0, 48.0), tip]
    codes += [MplPath.CURVE4] * 3
    verts.append(tip)
    codes.append(MplPath.CLOSEPOLY)
    return MplPath(verts, codes)


def draw_droplet(ax) -> None:
    """Gradient-filled droplet with white water table waves."""
    path = droplet_path()
    patch = PathPatch(path, facecolor="none", edgecolor="none")
    ax.add_patch(patch)

    # vertical gradient clipped to the droplet
    grad = np.linspace(0.0, 1.0, 256).reshape(-1, 1)
    img = ax.imshow(
        grad,
        extent=(0, 64, 0, 64),
        origin="lower",
        cmap=matplotlib.colors.LinearSegmentedColormap.from_list(
            "drop", [ACCENT, ACCENT_LIGHT]
        ),
        interpolation="bilinear",
        zorder=1,
    )
    img.set_clip_path(patch)

    # water table: a bold wave and a fainter one below (y-up coordinates)
    x = np.linspace(17.5, 46.5, 200)
    y = 21.5 + 2.6 * np.sin((x - 17.5) / 29.0 * 2.0 * np.pi * 1.25)
    line1 = ax.plot(x, y, color="white", lw=9.5, solid_capstyle="round", zorder=2)[0]
    x2 = np.linspace(20.5, 38.5, 150)
    y2 = 13.5 + 1.9 * np.sin((x2 - 20.5) / 18.0 * 2.0 * np.pi * 0.75 + np.pi)
    line2 = ax.plot(
        x2, y2, color="white", lw=6.5, alpha=0.55, solid_capstyle="round", zorder=2
    )[0]
    line1.set_clip_path(patch)
    line2.set_clip_path(patch)

    ax.set_xlim(0, 64)
    ax.set_ylim(0, 64)
    ax.set_aspect("equal")
    ax.axis("off")


def make_icon(out_path: Path) -> None:
    fig = plt.figure(figsize=(5.12, 5.12), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    draw_droplet(ax)
    fig.savefig(out_path, transparent=True, dpi=100)
    plt.close(fig)


def make_logo(out_path: Path) -> None:
    """Droplet icon plus wordmark, for the app sidebar."""
    fig = plt.figure(figsize=(11.2, 2.4), dpi=100)
    ax_icon = fig.add_axes([0.005, 0.06, 0.19, 0.88])
    draw_droplet(ax_icon)
    ax_text = fig.add_axes([0.20, 0, 0.80, 1])
    ax_text.axis("off")
    ax_text.text(
        0.01, 0.60, "Groundwater Toolkit",
        fontsize=46, fontweight="bold", color=INK,
        ha="left", va="center", family="DejaVu Sans",
    )
    ax_text.text(
        0.012, 0.20, "Siting - Drilling - Testing - Quality - Reporting",
        fontsize=17, color=ACCENT,
        ha="left", va="center", family="DejaVu Sans",
    )
    fig.savefig(out_path, transparent=True, dpi=100)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.svg").write_text(
        ICON_SVG.format(light=ACCENT_LIGHT, accent=ACCENT), encoding="utf-8"
    )
    make_icon(OUT / "icon.png")
    make_logo(OUT / "logo.png")
    for name in ("icon.svg", "icon.png", "logo.png"):
        size = (OUT / name).stat().st_size
        print(f"wrote {OUT / name} ({size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()

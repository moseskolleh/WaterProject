"""Generate the app theme from the house style.

The website used a palette that matched nothing else in the project: the
report figures, the logo and the favicon are all drawn in the house accent
(:class:`groundwater.config.HouseStyle`), so a visitor met a blue droplet on a
green page. The colours the client sees in a .docx and the colours they see on
the website should be the same colours.

Writes two files, both derived from the same accent:

* ``.streamlit/config.toml`` - the app theme. ``web/build_demo.py`` reads it,
  so the browser demo follows automatically.
* ``ui/depth-spine/src/tokens.css`` - the Depth Spine workspace, which draws on
  a dark canvas and so needs the accent lightened rather than used neat.

    python web/make_theme.py

Every derived colour is checked against WCAG AA contrast before it is written,
so a change to the house accent cannot quietly produce unreadable text.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from groundwater.config import HouseStyle  # noqa: E402

# The wordmark ink from web/make_brand_assets.py: darker than the accent, and
# already the colour of the logo's lettering.
INK = "#173B54"


def _rgb(colour: str) -> tuple[float, float, float]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _luminance(colour: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    la, lb = sorted((_luminance(a), _luminance(b)))
    return (lb + 0.05) / (la + 0.05)


def _mix(colour: str, other: str, amount: float) -> str:
    """Blend two hex colours; ``amount`` is how much of ``other`` to take."""
    mixed = (
        round(255 * (c1 + (c2 - c1) * amount))
        for c1, c2 in zip(_rgb(colour), _rgb(other))
    )
    return "#" + "".join(f"{value:02X}" for value in mixed)


def palette(style: HouseStyle | None = None) -> dict[str, str]:
    """The UI palette, derived from the house accent."""
    style = style or HouseStyle()
    accent = style.accent_color
    white = "#FFFFFF"
    return {
        "base": "light",
        # The accent carries buttons, focus rings and the active nav item.
        "primaryColor": accent,
        "backgroundColor": white,
        # Surfaces are the accent at low strength, so panels read as part of
        # the same family rather than as grey boxes.
        "secondaryBackgroundColor": _mix(white, accent, 0.06),
        "textColor": INK,
        "linkColor": accent,
        "borderColor": _mix(white, accent, 0.22),
        "baseRadius": "0.6rem",
        "sidebarBackgroundColor": _mix(white, accent, 0.10),
        "sidebarSecondaryBackgroundColor": white,
    }


def check(colours: dict[str, str]) -> list[str]:
    """WCAG AA checks on the pairs a reader actually has to read."""
    problems = []
    pairs = [
        ("body text on the page", colours["textColor"], colours["backgroundColor"], 4.5),
        ("body text on panels", colours["textColor"], colours["secondaryBackgroundColor"], 4.5),
        ("body text in the sidebar", colours["textColor"], colours["sidebarBackgroundColor"], 4.5),
        ("links on the page", colours["linkColor"], colours["backgroundColor"], 4.5),
        ("button label on the accent", "#FFFFFF", colours["primaryColor"], 4.5),
    ]
    for label, fg, bg, minimum in pairs:
        ratio = contrast(fg, bg)
        if ratio < minimum:
            problems.append(f"{label}: {fg} on {bg} is {ratio:.2f}:1, needs {minimum}")
    return problems



# ----------------------------------------------------------- oklch ------- #
# The workspace draws on a near-black canvas, where the accent used neat is far
# too dark to read. Lightening it in sRGB would wash the hue out, so the dark
# variants are built in Oklab, which keeps the hue and moves only lightness.


def _to_oklch(colour: str) -> tuple[float, float, float]:
    """Hex to Oklch (L, chroma, hue in degrees)."""

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in _rgb(colour))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (v ** (1 / 3) for v in (l, m, s))
    lightness = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b2 = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return lightness, math.hypot(a, b2), math.degrees(math.atan2(b2, a)) % 360


def _from_oklch(lightness: float, chroma: float, hue: float) -> str:
    """Oklch back to a hex colour, clipped into sRGB."""
    h = math.radians(hue)
    a, b = chroma * math.cos(h), chroma * math.sin(h)
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3
    channels = (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )

    def encode(c: float) -> int:
        c = max(0.0, min(1.0, c))
        c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(255 * c)

    return "#" + "".join(f"{encode(c):02X}" for c in channels)


# The canvas the section is drawn on, from the study. Dark on purpose: a
# borehole section is a drawing, and the coloured lithology, casing and water
# lines read better against it than against paper white.
CANVAS = "#12181A"
RAIL = "#0D1315"

# Water is drawn cyan rather than blue. The accent is the house blue now, and a
# water line the same hue as the buttons would stop reading as water.
WATER_HUE = 200.0


def workspace_palette(style: HouseStyle | None = None) -> dict[str, str]:
    """The Depth Spine tokens: the house accent, lightened for a dark canvas."""
    style = style or HouseStyle()
    _, _, hue = _to_oklch(style.accent_color)
    chroma = 0.12
    return {
        "canvas": CANVAS,
        "rail": RAIL,
        # Three steps: fills, emphasis, and text on the canvas.
        "accent": _from_oklch(0.66, chroma, hue),
        "accentBright": _from_oklch(0.74, chroma, hue),
        "accentText": _from_oklch(0.83, 0.09, hue),
        "onAccent": "#0B1214",
        "water": _from_oklch(0.78, 0.13, WATER_HUE),
        "waterText": _from_oklch(0.85, 0.11, WATER_HUE),
        # The surround the workspace floats on, when it is not embedded.
        "surround": palette(style)["secondaryBackgroundColor"],
        "surroundText": INK,
        "accentHue": f"{hue:.1f}",
        "waterHue": f"{WATER_HUE:.1f}",
    }


def check_workspace(colours: dict[str, str]) -> list[str]:
    """The workspace pairs, checked against the same AA thresholds."""
    problems = []
    pairs = [
        ("accent text on the canvas", colours["accentText"], colours["canvas"], 4.5),
        ("accent on the canvas", colours["accent"], colours["canvas"], 3.0),
        ("label on the accent", colours["onAccent"], colours["accent"], 4.5),
        ("water line on the canvas", colours["water"], colours["canvas"], 3.0),
        ("water label on the canvas", colours["waterText"], colours["canvas"], 4.5),
        ("page text on the surround", colours["surroundText"], colours["surround"], 4.5),
    ]
    for label, fg, bg, minimum in pairs:
        ratio = contrast(fg, bg)
        if ratio < minimum:
            problems.append(f"{label}: {fg} on {bg} is {ratio:.2f}:1, needs {minimum}")
    return problems


TOKENS_TEMPLATE = """/* Generated by web/make_theme.py from groundwater.config.HouseStyle.
   Do not edit: run `python web/make_theme.py` and rebuild the frontend.

   The workspace is a drawing surface, so it keeps the study's dark canvas -
   but the accent is the house blue, lightened here for legibility on it, and
   water moves to cyan so the two never read as the same thing. */
:root {{
  --ink: {canvas};
  --rail: {rail};
  --accent: {accent};
  --accent-bright: {accentBright};
  --accent-text: {accentText};
  --on-accent: {onAccent};
  --water: {water};
  --water-text: {waterText};

  /* Bare hues, for the places that need the family at some other lightness or
     with an alpha - a swatch wash, a gradient, a dashed guide. */
  --accent-h: {accentHue};
  --water-h: {waterHue};
  --surround: {surround};
  --surround-text: {surroundText};
}}
"""


def render_tokens(colours: dict[str, str] | None = None) -> str:
    return TOKENS_TEMPLATE.format(**(colours or workspace_palette()))


TEMPLATE = """# Generated by web/make_theme.py from groundwater.config.HouseStyle.
# Edit the house style (or this generator) and re-run, rather than editing here:
# web/build_demo.py reads this file, so the browser demo follows automatically.
[theme]
base = "{base}"
primaryColor = "{primaryColor}"
backgroundColor = "{backgroundColor}"
secondaryBackgroundColor = "{secondaryBackgroundColor}"
textColor = "{textColor}"
linkColor = "{linkColor}"
borderColor = "{borderColor}"
baseRadius = "{baseRadius}"

[theme.sidebar]
backgroundColor = "{sidebarBackgroundColor}"
secondaryBackgroundColor = "{sidebarSecondaryBackgroundColor}"

[browser]
gatherUsageStats = false
"""


def render(colours: dict[str, str] | None = None) -> str:
    return TEMPLATE.format(**(colours or palette()))


TOKENS_PATH = REPO / "ui" / "depth-spine" / "src" / "tokens.css"
CONFIG_PATH = REPO / ".streamlit" / "config.toml"


def main() -> None:
    colours = palette()
    workspace = workspace_palette()
    problems = check(colours) + check_workspace(workspace)
    for problem in problems:
        print(f"contrast: {problem}")
    if problems:
        raise SystemExit("nothing written: fix the contrast failures above")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(render(colours), encoding="utf-8")
    print(f"wrote {CONFIG_PATH}")
    for name, value in colours.items():
        print(f"  {name:32s} {value}")

    TOKENS_PATH.write_text(render_tokens(workspace), encoding="utf-8")
    print(f"wrote {TOKENS_PATH}")
    for name, value in workspace.items():
        print(f"  {name:32s} {value}")
    print("\nrebuild the workspace so the change reaches the app and the demo:")
    print("  cd ui/depth-spine && npm run build:all && python web/build_demo.py")


if __name__ == "__main__":
    main()

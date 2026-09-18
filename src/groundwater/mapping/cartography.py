"""The furniture and the palette every map in this toolkit is drawn with.

A map is not a chart with coastlines on it. It has a frame, a graticule
that says where on Earth it is, a scale bar someone can measure with, a
north arrow, a key, and a line saying where the data came from - and the
weight and colour of every one of those says how much attention it wants.
Before this module those pieces were open-coded in three files with three
sets of numbers, so the same site came out looking like three different
maps depending on which function drew it.

Two rules run through it.

**Hierarchy is the whole job.** The eye should find the coastline first,
then the site, then the boundaries, then the graticule - and never the
graticule first. That is set by weight and contrast, not by adding more
ink: the graticule here is a hairline at 12% grey, and it disappears
until you look for it.

**Nothing may look more certain than it is.** The boundaries this draws
are simplified, and the geological contacts come from a map published at
1:5,000,000. So the lines are drawn honestly at the resolution the data
has, and the figure says what that resolution is. What this module will
not do is smooth a contact into a confident curve it was never surveyed
to: a prettier line that implies a surveyor walked it is a worse map, not
a better one. Where the jaggedness is an artefact of simplification
rather than a property of the data, the fix is finer data, and
``web/build_geodata.py`` is where that is decided.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import matplotlib.patheffects as path_effects
import numpy as np
from matplotlib.patches import Polygon as MplPolygon

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

#: Sea, and the land beyond the border. A coastal map with no sea on it
#: reads as a country floating in paper - and on the Freetown peninsula,
#: which is most of what this toolkit maps, half the frame is ocean.
SEA = "#D9E6EF"
SEA_LINE = "#A8C4D6"
FOREIGN_LAND = "#F2F0EC"
FOREIGN_LINE = "#D8D4CC"

#: Ink, in four weights. Everything textual comes from here.
INK = "#1A1A1A"
INK_MUTED = "#5A5A5A"
INK_FAINT = "#8C8C8C"
GRATICULE = "#00000020"

#: Boundaries, heaviest first. A national outline is a fact; a chiefdom
#: boundary in a simplified layer is a guide to roughly where you are.
COAST = "#33414D"
DISTRICT = "#6B7A88"
CHIEFDOM = "#A3B1BC"

#: The neutral fill under everything on an administrative map.
LAND = "#FBFAF8"
LAND_HIGHLIGHT = "#E8EFF5"

SITE = "#B3261E"

#: Where the source layer has no polygon at all. Drawn, and keyed, because
#: a gap left the colour of the page reads as "nothing here" rather than
#: as "this map does not say".
NOT_MAPPED = "#EDEBE7"

#: A muted geological palette, keyed by the bundled USGS unit code.
#:
#: The colours carried in the data are the USGS sheet's own and they are
#: brutal on a report page - #0052CC pure blue for water, #F7437C magenta
#: for the Precambrian that covers 85% of the country, #CB372D for the
#: Freetown gabbro. Three fully saturated hues fighting each other is what
#: made these figures look like a school atlas.
#:
#: These keep the conventional sense of geological colour - warm for
#: igneous, cool for sedimentary, grey-pink for old basement - at a
#: lightness that a site marker and a black contact line can be read over,
#: and that survives a greyscale photocopy, which is how most of these
#: reports are actually read in the field. The source colours stay in the
#: GeoJSON and ``prefer_source_colours`` puts them back.
# Each tint is at least 0.05 of relative luminance from every other and
# from the sea, the paper and the not-mapped tone, so the units stay
# apart in greyscale. The Bullom Group was 0.77 against a sea of 0.78 and
# vanished into the Atlantic on a photocopy; tests/test_study_area_maps.py
# holds the separation.
GEOLOGY_COLOURS = {
    "pCm": "#CDBAC6",   # Precambrian basement - the ground state
    "Pi": "#B7715C",    # the Freetown layered gabbro: basic igneous, warm, dark
    "Mi": "#CC9A86",    # dolerite, the same family a shade lighter
    "O": "#9DB9A3",     # Rokel River Group metasediments
    "S": "#BCCDB6",
    "Qe": "#E6D5A6",    # Bullom Group sands and clays
    "H2O": "#6F9BBF",   # surface water: a deep blue, well apart from the sea
}


def relative_luminance(colour: str) -> float:
    """sRGB relative luminance, 0 (black) to 1 (white): what a photocopy keeps."""
    rgb = [int(colour.lstrip("#")[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def geology_colour(code: str, source_colour: str, prefer_source: bool = False) -> str:
    """The fill for one geological unit."""
    if prefer_source:
        return source_colour
    return GEOLOGY_COLOURS.get(code, source_colour)


@dataclass(frozen=True)
class LineStyle:
    color: str
    width: float
    zorder: float


#: One place to change how heavy each class of boundary is drawn.
LINES = {
    "coast": LineStyle(COAST, 1.5, 6.0),
    "district": LineStyle(DISTRICT, 0.9, 5.0),
    "chiefdom": LineStyle(CHIEFDOM, 0.5, 4.0),
    "contact": LineStyle("#8A8A8A", 0.35, 3.0),
}


# ---------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------

def halo(size: float = 2.2, color: str = "#FFFFFF"):
    """A cut-out behind a label so it reads over any fill.

    Every place name on these maps sits on top of something - a
    geological unit, a hypsometric tint, a choropleth class. Without a
    halo the name takes the colour of whatever it landed on and a third
    of the labels become unreadable, which is the single thing that most
    made these figures look homemade.
    """
    return [path_effects.withStroke(linewidth=size, foreground=color)]


def place_label(ax, lon, lat, text, *, size=7.0, color=INK_MUTED,
                weight="normal", style="normal", zorder=8.0, ha="center",
                va="center", halo_color="#FFFFFF", halo_size=2.2):
    """Draw a place name with a halo, in the house type scale."""
    return ax.annotate(
        text, xy=(lon, lat), ha=ha, va=va, fontsize=size, color=color,
        fontweight=weight, fontstyle=style, zorder=zorder,
        path_effects=halo(halo_size, halo_color),
    )


def declutter(
    candidates: list[tuple[float, float, str]],
    extent: tuple[float, float, float, float],
    min_sep_frac: float = 0.052,
    priority: list[float] | None = None,
    reserved: list[tuple[float, float, float, float]] | None = None,
) -> list[tuple[float, float, str]]:
    """Keep the labels that fit, drop the ones that would overlap.

    Matplotlib will happily draw two names through each other. On a
    window crossing the Western Area the chiefdoms are small enough that
    four names landed in the same centimetre, and a name nobody can read
    is worse than no name: the reader cannot tell which polygon the
    legible one belongs to either.

    Greedy, largest-first, over estimated text boxes rather than points.
    ``priority`` (bigger is more important, the polygon's area is the
    obvious choice) decides who wins a collision, so the chiefdom filling
    the frame keeps its name and the sliver clipped by the corner loses
    it. A label whose text would run off the frame is dropped too: a name
    half outside the neatline points at nothing.
    """
    if not candidates:
        return []
    order = (
        np.argsort(priority)[::-1] if priority is not None
        else np.arange(len(candidates))
    )
    width = extent[2] - extent[0]
    height = extent[3] - extent[1]
    # A label is a box, not a dot. Testing centre-to-centre distance kept
    # "Western Area Urban" and "Western Area Rural" because their centroids
    # are far enough apart - while the words themselves, fifteen characters
    # wide, ran straight through each other. Character width is estimated
    # rather than measured because the renderer has not laid the text out
    # yet, and an estimate that is roughly right for DejaVu Sans at these
    # sizes is enough to separate the cases that actually collide.
    char_w = width * min_sep_frac * 0.30
    line_h = height * min_sep_frac * 0.62
    kept: list[tuple[float, float, str]] = []
    # boxes nothing may be written over: the site marker, the inset, a
    # legend. The site star used to be drawn through the district's name.
    boxes: list[tuple[float, float, float, float]] = list(reserved or [])
    for i in order:
        lon, lat, text = candidates[int(i)]
        half_w = len(text) * char_w / 2.0
        half_h = line_h / 2.0
        box = (lon - half_w, lat - half_h, lon + half_w, lat + half_h)
        # a name whose word runs off the frame, sideways or vertically,
        # points at nothing
        if not (extent[0] < lon < extent[2] and extent[1] < lat < extent[3]):
            continue
        if box[0] < extent[0] or box[2] > extent[2]:
            continue
        if box[1] < extent[1] or box[3] > extent[3]:
            continue
        if any(
            box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1]
            for b in boxes
        ):
            continue
        kept.append((lon, lat, text))
        boxes.append(box)
    return kept


# ---------------------------------------------------------------------------
# Graticule
# ---------------------------------------------------------------------------

def _nice_interval(span_deg: float) -> float:
    """A round graticule interval giving three to six lines across.

    Five was the target and the steps are coarse, so a 1.2 degree window
    fell to a 0.1 degree step and thirteen labels ran into each other
    along the bottom edge. A degree-and-minute label is about a tenth of
    the frame wide at this size; six across is the most that stay apart.
    """
    target = span_deg / 3.5
    for step in (5.0, 2.0, 1.0, 0.5, 0.25, 0.2, 0.1, 0.05, 0.025, 0.02,
                 0.01, 0.005, 0.002, 0.001):
        if step <= target:
            return step
    return 0.001


def _dms(value: float, axis: str) -> str:
    """A coordinate as degrees and minutes, the way a map writes them.

    ``-13.5`` is how a spreadsheet writes a longitude. A map writes
    13 degrees 30 minutes West, and a hydrogeologist reading a GPS in
    the field is reading degrees and minutes.
    """
    hemi = ("N" if value >= 0 else "S") if axis == "lat" else ("E" if value >= 0 else "W")
    value = abs(value)
    deg = int(value)
    minutes = (value - deg) * 60.0
    # 12.99999 is sixty minutes past twelve, which is thirteen degrees, not
    # "12 deg 60'". Floating point put a tick just short of 13 W and the
    # graticule on every map of the Western Area was labelled 12 deg 60' W.
    if minutes >= 59.95:
        deg += 1
        minutes = 0.0
    if minutes < 0.05:
        return f"{deg}°{hemi}"
    if abs(minutes - round(minutes)) < 0.05:
        return f"{deg}°{round(minutes):02d}′{hemi}"
    return f"{deg}°{minutes:04.1f}′{hemi}"


def graticule(ax, *, interval: float | None = None, label_size: float = 7.0):
    """A hairline graticule with degree-and-minute labels.

    Replaces the full grey grid, which was the heaviest thing on most of
    these maps and drew the eye before the data did.
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    step = interval or _nice_interval(max(x1 - x0, y1 - y0))
    # only ticks inside the frame: a tick placed past the limit made
    # matplotlib grow the axes to include it, which put a white strip on
    # the national maps and moved every local window off its site
    eps = step * 1e-6
    xs = np.array([x for x in np.arange(math.ceil(x0 / step) * step, x1 + step / 2, step)
                   if x0 - eps <= x <= x1 + eps])
    ys = np.array([y for y in np.arange(math.ceil(y0 / step) * step, y1 + step / 2, step)
                   if y0 - eps <= y <= y1 + eps])
    for x in xs:
        ax.axvline(x, color=GRATICULE, lw=0.5, zorder=2.5)
    for y in ys:
        ax.axhline(y, color=GRATICULE, lw=0.5, zorder=2.5)
    ax.set_xticks(xs)
    ax.set_yticks(ys)
    ax.set_xticklabels([_dms(x, "lon") for x in xs], fontsize=label_size,
                       color=INK_MUTED)
    ax.set_yticklabels([_dms(y, "lat") for y in ys], fontsize=label_size,
                       color=INK_MUTED)
    ax.tick_params(length=3, width=0.6, color=INK_FAINT, pad=2)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_edgecolor(COAST)
        spine.set_linewidth(0.9)


# ---------------------------------------------------------------------------
# Scale bar
# ---------------------------------------------------------------------------

def _nice_scale_length(span_km: float) -> float:
    """A round bar length at roughly a quarter of the frame."""
    target = span_km / 4.0
    if target <= 0:
        return 1.0
    power = 10 ** math.floor(math.log10(target))
    for mult in (5, 4, 2, 1):
        if power * mult <= target:
            return power * mult
    return power


def scale_bar(ax, mean_lat: float, *, segments: int = 4, frac_x: float = 0.055,
              frac_y: float = 0.055, height_frac: float = 0.011):
    """An alternating-segment scale bar with ticked divisions.

    The old bar was a black line with a white half drawn over it and one
    label at the middle, which tells a reader the total and nothing else.
    This is the bar on a published sheet: a zero at the left, divisions
    that can actually be counted off against a distance on the map, and
    the unit stated once at the right.
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    km_per_deg = 111.32 * math.cos(math.radians(mean_lat))
    total_km = _nice_scale_length((x1 - x0) * km_per_deg)
    bar_deg = total_km / km_per_deg
    seg_deg = bar_deg / segments

    bx = x0 + (x1 - x0) * frac_x
    by = y0 + (y1 - y0) * frac_y
    bh = (y1 - y0) * height_frac

    for i in range(segments):
        ax.add_patch(
            MplPolygon(
                [(bx + i * seg_deg, by), (bx + (i + 1) * seg_deg, by),
                 (bx + (i + 1) * seg_deg, by + bh), (bx + i * seg_deg, by + bh)],
                closed=True, facecolor=INK if i % 2 == 0 else "#FFFFFF",
                edgecolor=INK, lw=0.6, zorder=10.0,
            )
        )
    # a zero, the midpoint and the total with its unit: enough to measure
    # against. The unit used to be a separate "km" beside the bar, which
    # the total overprinted whenever it had two digits.
    ticks = {0: "0", segments // 2: f"{total_km / 2:g}", segments: f"{total_km:g} km"}
    for i, text in ticks.items():
        ax.annotate(
            text, xy=(bx + i * seg_deg, by + bh * 1.25),
            ha="center" if i < segments else "left",
            xytext=(0, 0) if i < segments else (-4, 0), textcoords="offset points",
            va="bottom", fontsize=6.5, color=INK, zorder=10.0,
            path_effects=halo(2.0),
        )


# ---------------------------------------------------------------------------
# North arrow
# ---------------------------------------------------------------------------

def north_arrow(ax, *, frac_x: float = 0.945, frac_y: float = 0.9,
                size_frac: float = 0.055):
    """A filled compass needle rather than a line with a letter over it.

    Two triangles about a common axis: the east half solid, the west half
    open. It reads as a needle at a centimetre high, which an annotate
    arrow does not.
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    cx = x0 + (x1 - x0) * frac_x
    cy = y0 + (y1 - y0) * frac_y
    h = (y1 - y0) * size_frac
    w = h * 0.32 * ((x1 - x0) / (y1 - y0)) * 0.55

    ax.add_patch(MplPolygon([(cx, cy + h), (cx + w, cy - h * 0.45), (cx, cy - h * 0.12)],
                            closed=True, facecolor=INK, edgecolor=INK,
                            lw=0.5, zorder=10.0))
    ax.add_patch(MplPolygon([(cx, cy + h), (cx - w, cy - h * 0.45), (cx, cy - h * 0.12)],
                            closed=True, facecolor="#FFFFFF", edgecolor=INK,
                            lw=0.5, zorder=10.0))
    ax.annotate("N", xy=(cx, cy + h * 1.18), ha="center", va="bottom",
                fontsize=8.0, fontweight="bold", color=INK, zorder=10.0,
                path_effects=halo(2.2))


# ---------------------------------------------------------------------------
# Sea, and the land across the border
# ---------------------------------------------------------------------------

def sea_and_neighbours(ax, outline_rings: list[np.ndarray], background: str,
                       foreign_rings: list[np.ndarray] | None = None):
    """Fill the frame as sea, then lay the country on top of it.

    Sierra Leone has 400 km of coast and this toolkit's busiest site is
    on the Freetown peninsula, where half of every window is Atlantic.
    Drawn as white it read as blank paper, so the coastline looked like
    the edge of the data rather than the edge of the land - the single
    thing that most made these look unfinished.

    Everything outside the national outline is filled: across the land
    border that is Guinea or Liberia, not ocean, so it is drawn in a
    neutral paper tone and the sea proper is only claimed where the
    caller knows it is sea. The two are told apart by the caller, not
    guessed here.
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    ax.add_patch(
        MplPolygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], closed=True,
                   facecolor=SEA, edgecolor="none", zorder=0.4)
    )
    # Guinea and Liberia, in the paper tone, laid over the sea and under
    # the country. They were painted the same blue as the Atlantic on every
    # map, so a site near the border looked like a site on the coast. The
    # caller passes what it knows is land across the border; without it,
    # everything outside the outline stays sea.
    for ring in foreign_rings or []:
        ax.add_patch(
            MplPolygon(ring, closed=True, facecolor=FOREIGN_LAND,
                       edgecolor="none", zorder=0.5)
        )
    for ring in outline_rings:
        ax.add_patch(
            MplPolygon(ring, closed=True, facecolor=background,
                       edgecolor="none", zorder=0.6)
        )


def neatline(ax):
    """The frame. A map has an edge; a chart has axes."""
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_edgecolor(COAST)
        spine.set_linewidth(0.9)
        spine.set_zorder(11.0)


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def attribution(ax, text: str, *, width: int = 104, size: float = 5.8) -> float:
    """The sources, set small, at the foot, on a plate that keeps it legible.

    It is small because it is not the map; it is present because a
    figure without its sources cannot be checked. Returns the axes-fraction
    y a caller should put the next block of small print at, because a
    three-source credit wraps to three lines and anything written at a
    fixed offset below it lands on top of it.
    """
    import textwrap

    # Under the frame, not inside it. Inside, a three-source credit wrapped
    # to three lines across the bottom-left corner and buried the scale bar,
    # which is the one piece of furniture a reader actually measures with.
    wrapped = textwrap.fill(text, width)
    ax.text(
        1.0, -0.055, wrapped, transform=ax.transAxes,
        ha="right", va="top", fontsize=size, color=INK_FAINT,
        style="italic", linespacing=1.4,
    )
    # how far down the next block has to start to clear this one
    return -0.055 - (wrapped.count("\n") + 1) * 0.026


def title_block(ax, title: str, subtitle: str = ""):
    """Title above the frame, subtitle under it in the muted weight."""
    ax.set_title(title, fontsize=11.5, fontweight="600", color=INK, pad=9)
    if subtitle:
        ax.text(0.0, 1.012, subtitle, transform=ax.transAxes, ha="left",
                va="bottom", fontsize=7.5, color=INK_MUTED)

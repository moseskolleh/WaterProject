"""The community handover sheet as a Word document (PLAN.md step 9.1).

Lays out :func:`groundwater.community_sheet.community_sheet_content` on one
page: the title, how much water, whether it is safe to drink, who to call,
how to report a fault, and what to keep away, with its picture. The words
and the numbers are all in the content; this module only places them, as
``GWT.docx.communitySheet`` places the same content in the browser.

It has to stay one page, so each part's sentences are set as one paragraph,
the margins are narrower than the reports', and there is one picture: the
rings, their key, and beside them the square a phone scans where the sheet
carries one.

The rings are drawn at equal steps, not to scale: the table's distances run
from 3 m to a kilometre, and to scale the inner rings would be a dot. Each
ring carries its distance and the key says what is to be kept beyond it.

Nothing in the picture is assumed to be as long as the English; every word
drawn is measured first. A row of the key too long for the room beside the
rings is broken at its spaces, the rows start after the widest distance, and
a key too tall, a distance or a word too wide, a label too long for the room
under the square and a word at the centre wider than the rings are each set
smaller or broken. Translated words must not run under the square a phone
scans, or off the picture's edge. The English is drawn where it always was.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..community_sheet import community_sheet_content
from ..config import Config
from ..models import SiteMetadata
from ..verification import Issue
from docx.shared import Cm

from .docx_utils import ReportBuilder

__all__ = ["build_community_sheet", "fit_words", "key_layout", "label_layout", "sheet_picture",
           "wrap_words"]

#: The page's margins. The other documents keep 2.5 cm; this one has to hold
#: on one page what they would run on to a second.
MARGIN_CM = 1.5
#: The picture's size as printed, with and without the square to scan.
PICTURE_HEIGHT_CM = 5.0
PICTURE_WIDTH_CM = 12.6
PICTURE_WIDTH_SCAN_CM = 16.0
#: Where the picture's three parts sit, in centimetres from its left edge:
#: the rings' centre and outer radius, the key, and the square.
RINGS_AT_CM, RINGS_RADIUS_CM = 2.5, 2.2
KEY_AT_CM, KEY_TEXT_AT_CM = 6.0, 7.3
SCAN_AT_CM, SCAN_SIZE_CM = 12.8, 2.9
#: How many characters of the square's label go on a line.
SCAN_LABEL_WIDTH = 24
#: The key's type in points, the room a line of it takes, and the white kept
#: between the key and whatever is to its right.
KEY_LABEL_PT, KEY_TEXT_PT, KEY_PITCH_CM, KEY_CLEAR_CM = 8.0, 7.5, 0.42, 0.25
#: The white kept between a distance and its rows, and the widest a distance
#: is set before it is set smaller: the rows keep four centimetres at least.
KEY_GAP_CM, KEY_LABEL_MAX_CM = 0.1, 2.2
#: The type of the distances on the rings, of the word at the centre and of
#: the square's label, and the room the label's lines have under the square.
RING_LABEL_PT, CENTRE_PT, SCAN_LABEL_PT, SCAN_LABEL_ROOM_CM = 7.0, 6.5, 6.5, 3.3


def wrap_words(text: str, width: int) -> list[str]:
    """``text`` broken at spaces into lines of at most ``width`` characters
    (a longer word has a line to itself), as the browser breaks it."""
    lines: list[str] = []
    for word in text.split(" "):
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def fit_words(text: str, limit: float, measure) -> list[str]:
    """``text`` broken at spaces into lines no wider than ``limit`` as
    ``measure`` measures a line (a word wider than that has a line to
    itself), as the browser breaks it."""
    lines: list[str] = []
    for word in text.split(" "):
        if lines and measure(lines[-1] + " " + word) <= limit:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def key_layout(rings: list[dict], right: float, height: float, measure) -> dict:
    """Where the key's words go: ``text_at``, where the rows start, after the
    widest distance; ``label_scale``, how much smaller a distance too wide
    for its column is set; ``rows``, for each ring the lines of each thing it
    names; ``pitch``, the room a line takes; and ``scale``, how much smaller
    than its usual size the whole key is set. ``right`` is how far right a
    row may reach and ``measure(text, points, bold)`` a width in
    centimetres. The browser lays the key out by the same steps
    (communitySheetPicture).

    The English is where it was before the key was measured, in the font
    the picture is drawn in here and in matplotlib's own: the rows start at
    ``KEY_TEXT_AT_CM`` and none is broken."""
    widest = max((measure(ring["label"], KEY_LABEL_PT, True) for ring in rings), default=0.0)
    # a distance with a long word for its unit is set smaller rather than
    # left to push the rows off the picture
    label_scale = min(1.0, KEY_LABEL_MAX_CM / widest) if widest else 1.0
    text_at = max(KEY_TEXT_AT_CM, KEY_AT_CM + widest * label_scale + KEY_GAP_CM)
    limit = right - text_at
    rows = [[fit_words(what, limit, lambda line: measure(line, KEY_TEXT_PT, False))
             for what in ring["what"]] for ring in rings]
    lines = sum(len(broken) for ring in rows for broken in ring) + max(len(rings) - 1, 0) * 0.5
    # a key too tall for the picture is set closer and smaller, and so is
    # one with a word no line can hold
    longest = max((measure(line, KEY_TEXT_PT, False) for ring in rows for broken in ring
                   for line in broken), default=0.0)
    scale = min(1.0, (height - 0.4) / (lines * KEY_PITCH_CM) if lines else 1.0,
                limit / longest if longest else 1.0)
    return {"text_at": text_at, "label_scale": label_scale, "rows": rows, "lines": lines,
            "pitch": KEY_PITCH_CM * scale, "scale": scale}


def label_layout(caption: str, measure) -> dict:
    """The lines of the label under the square a phone scans, and how much
    smaller than its usual size it is set. Broken as the English always was,
    at ``SCAN_LABEL_WIDTH`` characters; then a line still wider than the room
    under the square is broken again by its measure, and a word no line can
    hold sets the whole label smaller."""
    def wide(line: str) -> float:
        return measure(line, SCAN_LABEL_PT, False)

    lines = [part for line in wrap_words(caption, SCAN_LABEL_WIDTH)
             for part in (fit_words(line, SCAN_LABEL_ROOM_CM, wide)
                          if wide(line) > SCAN_LABEL_ROOM_CM else [line])]
    longest = max((wide(line) for line in lines), default=0.0)
    return {"lines": lines,
            "scale": min(1.0, SCAN_LABEL_ROOM_CM / longest) if longest else 1.0}


def sheet_picture(content: dict, out_path: str | Path) -> tuple[Path, float]:
    """Draw the sheet's picture as a PNG, and return it with its printed
    width in centimetres.

    On the left the rings, each with its distance; beside them the key: what
    is to be kept beyond each ring. Where the sheet carries a link to the
    report page, the square to scan is on the right with its label.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Rectangle

    keep, report = content["keep_away"], content["report"]
    rings = keep["rings"]
    width = PICTURE_WIDTH_SCAN_CM if report["payload"] else PICTURE_WIDTH_CM
    height = PICTURE_HEIGHT_CM
    ink, ground, accent = "#161a17", "#f1f3f0", "#1b7a2e"
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(width / 2.54, height / 2.54), dpi=220)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.set_aspect("equal")
    ax.axis("off")

    centre = (RINGS_AT_CM, height / 2)
    step = RINGS_RADIUS_CM / max(len(rings), 1)
    # outermost first, so that each ring is drawn over the one beyond it
    for k in range(len(rings), 0, -1):
        ax.add_patch(Circle(centre, k * step, facecolor=ground if k % 2 else "#ffffff",
                                edgecolor=ink, linewidth=0.9))
    # Nothing in the picture is assumed to be as long as the English: every
    # word drawn is measured first.
    def measure(text: str, points: float, bold: bool) -> float:
        probe = ax.text(0, 0, text, fontsize=points, fontweight="bold" if bold else "normal")
        wide = probe.get_window_extent().width / fig.dpi * 2.54
        probe.remove()
        return wide

    # a distance wider than the picture has room for left of the rings'
    # centre is set smaller, all of them alike
    on_ring = max((measure(ring["label"], RING_LABEL_PT, True) for ring in rings), default=0.0)
    ring_scale = min(1.0, 2 * (RINGS_AT_CM - 0.1) / on_ring) if on_ring else 1.0
    for k, ring in enumerate(rings, start=1):
        # the distance sits on its ring, at the foot, on a patch of white
        ax.text(centre[0], centre[1] - k * step, ring["label"], ha="center", va="center",
                fontsize=RING_LABEL_PT * ring_scale, fontweight="bold", color=ink,
                bbox={"facecolor": "#ffffff", "edgecolor": "none", "pad": 1.0})
    ax.add_patch(Circle(centre, 0.13, facecolor=accent, edgecolor=ink, linewidth=0.6))
    # the word at the centre: one wider than the innermost ring would be
    # struck through by it, so it is given a patch of white, and one wider
    # than the rings is set smaller
    named = measure(keep["centre"], CENTRE_PT, True)
    ax.text(centre[0], centre[1] + 0.22, keep["centre"], ha="center", va="bottom",
            fontsize=CENTRE_PT * min(1.0, (2 * RINGS_RADIUS_CM - 0.2) / named if named else 1.0),
            fontweight="bold", color=ink,
            bbox=({"facecolor": "#ffffff", "edgecolor": "none", "pad": 1.0}
                  if named > 2 * step else None))

    # the key: one entry a ring, nearest first, each thing on a line of its
    # own, and on more than one where it is too long for the room there is
    right = (SCAN_AT_CM if report["payload"] else width) - KEY_CLEAR_CM
    key = key_layout(rings, right, height, measure)
    pitch, scale = key["pitch"], key["scale"]
    y = height / 2 + key["lines"] * pitch / 2 - 0.2 * scale
    for ring, things in zip(rings, key["rows"], strict=True):
        ax.text(KEY_AT_CM, y, ring["label"], ha="left", va="center",
                fontsize=KEY_LABEL_PT * key["label_scale"] * scale, fontweight="bold", color=ink)
        for broken in things:
            for line in broken:
                ax.text(key["text_at"], y, line, ha="left", va="center",
                        fontsize=KEY_TEXT_PT * scale, color=ink)
                y -= pitch
        y -= pitch / 2

    if report["payload"]:
        from .. import qr

        modules = qr.encode(report["payload"], ecc="H").modules
        size = len(modules)
        cell = SCAN_SIZE_CM / (size + 2)   # a module of white all round
        top = height - 0.35
        for r, row in enumerate(modules):
            for c, dark in enumerate(row):
                if dark:
                    ax.add_patch(Rectangle(
                        (SCAN_AT_CM + (c + 1) * cell, top - (r + 2) * cell), cell, cell,
                        facecolor="#000000", edgecolor="none", linewidth=0))
        label = label_layout(report["caption"], measure)
        # the label's lines keep to the room under the square: more of them
        # than the English has are set closer
        foot = top - SCAN_SIZE_CM - 0.25
        gap = min(0.33, (foot - 0.15) / max(len(label["lines"]) - 1, 1))
        for n, line in enumerate(label["lines"]):
            ax.text(SCAN_AT_CM + SCAN_SIZE_CM / 2, foot - n * gap, line,
                    ha="center", va="center", color=ink,
                    fontsize=SCAN_LABEL_PT * min(1.0, gap / 0.33 + 0.15) * label["scale"])
    fig.savefig(path, facecolor="#ffffff")
    plt.close(fig)
    return path, width


def build_community_sheet(site: SiteMetadata, out_path: str | Path, figures_dir: str | Path, *,
                          analysis: Any = None, quality: Any = None, committee: Any = None,
                          asset_id: str = "", hours_per_day: float | None = None,
                          example: bool = False, config: Config | None = None,
                          issue: Issue | None = None, language: str = "",
                          translations: dict | None = None) -> Path:
    """Write the community handover sheet to ``out_path``.

    ``language`` is the code of the translation to print it in, and nothing
    for English (PLAN.md step 9.2); what the translation has no words for is
    printed in English. The page's furniture is the same in every language:
    the word "Figure" before the picture's caption and the line at the foot
    that carries the document's code are the reports' own, and English.

    Raises ValueError for a report address the registry would not print on
    a plate, and for a language that is not on offer, as
    :func:`community_sheet_content` does.
    """
    config = config or Config()
    content = community_sheet_content(
        site, analysis=analysis, quality=quality, committee=committee, asset_id=asset_id,
        hours_per_day=hours_per_day, example=example, config=config, language=language,
        translations=translations)
    figures = Path(figures_dir)
    rb = ReportBuilder(config.style, title=content["title"], kind="community_sheet",
                       issue=issue, config=config)
    for side in ("top", "bottom", "left", "right"):
        setattr(rb.doc.sections[0], f"{side}_margin", Cm(MARGIN_CM))

    if content["example"]:
        rb.paragraph(content["example"], bold=True, align="center")
    rb.paragraph(content["title"], bold=True, size_pt=18, align="center")

    for part in (content["water"], content["quality"]):
        rb.paragraph(part["heading"], bold=True, size_pt=12)
        rb.paragraph(part["headline"], bold=True, size_pt=14)
        if part["lines"]:
            rb.paragraph(" ".join(part["lines"]))

    contacts = content["contacts"]
    rb.paragraph(contacts["heading"], bold=True, size_pt=12)
    rb.table(contacts["rows"], header=contacts["header"], col_widths_cm=[5.0, 6.0, 5.0],
             font_size_pt=10.0)

    report = content["report"]
    rb.paragraph(report["heading"], bold=True, size_pt=12)
    rb.paragraph(" ".join(report["lines"]))

    # what to keep away is the picture: its key says, ring by ring, what the
    # content's lines say, and the square to scan sits beside it
    keep = content["keep_away"]
    rb.paragraph(keep["heading"], bold=True, size_pt=12)
    picture, width = sheet_picture(content, figures / "community_sheet_picture.png")
    rb.figure(picture, keep["caption"], width_cm=width)
    return rb.save(out_path)

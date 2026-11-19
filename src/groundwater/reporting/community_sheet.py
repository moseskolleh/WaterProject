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
ring carries its distance and the key says what is to be kept beyond it, so
the picture says all that the content's ``keep_away`` lines say.
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

__all__ = ["build_community_sheet", "sheet_picture", "wrap_words"]

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
    for k, ring in enumerate(rings, start=1):
        # the distance sits on its ring, at the foot, on a patch of white
        ax.text(centre[0], centre[1] - k * step, ring["label"], ha="center", va="center",
                fontsize=7, fontweight="bold", color=ink,
                bbox={"facecolor": "#ffffff", "edgecolor": "none", "pad": 1.0})
    ax.add_patch(Circle(centre, 0.13, facecolor=accent, edgecolor=ink, linewidth=0.6))
    ax.text(centre[0], centre[1] + 0.22, keep["centre"], ha="center", va="bottom",
            fontsize=6.5, fontweight="bold", color=ink)

    # the key: one entry a ring, nearest first, each thing on a line of its own
    lines = sum(len(ring["what"]) for ring in rings) + max(len(rings) - 1, 0) * 0.5
    y = height / 2 + lines * 0.42 / 2 - 0.2
    for ring in rings:
        ax.text(KEY_AT_CM, y, ring["label"], ha="left", va="center", fontsize=8,
                fontweight="bold", color=ink)
        for what in ring["what"]:
            ax.text(KEY_TEXT_AT_CM, y, what, ha="left", va="center", fontsize=7.5, color=ink)
            y -= 0.42
        y -= 0.21

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
        for n, line in enumerate(wrap_words(report["caption"], SCAN_LABEL_WIDTH)):
            ax.text(SCAN_AT_CM + SCAN_SIZE_CM / 2, top - SCAN_SIZE_CM - 0.25 - n * 0.33, line,
                    ha="center", va="center", fontsize=6.5, color=ink)
    fig.savefig(path, facecolor="#ffffff")
    plt.close(fig)
    return path, width


def build_community_sheet(site: SiteMetadata, out_path: str | Path, figures_dir: str | Path, *,
                          analysis: Any = None, quality: Any = None, committee: Any = None,
                          asset_id: str = "", hours_per_day: float | None = None,
                          example: bool = False, config: Config | None = None,
                          issue: Issue | None = None) -> Path:
    """Write the community handover sheet to ``out_path``.

    Raises ValueError for a report address the registry would not print on
    a plate, as :func:`community_sheet_content` does.
    """
    config = config or Config()
    content = community_sheet_content(
        site, analysis=analysis, quality=quality, committee=committee, asset_id=asset_id,
        hours_per_day=hours_per_day, example=example, config=config)
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

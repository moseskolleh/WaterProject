"""The field kit as a Word document (PLAN.md step 2.5).

Lays out :func:`groundwater.field_kit.field_kit_content`: one pumping test
sheet for each borehole, each on pages of its own with its QR code at the
top, then the three quick cards, one to a page, for laminating. The words
and the numbers are all in the content; this module only places them, as
``GWT.docx.fieldKit`` places the same content in the browser.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..field_kit import field_kit_content
from ..models import SiteMetadata
from .docx_utils import ReportBuilder
from .registry import write_qr_png

__all__ = ["build_field_kit"]

#: The printed width of a sheet's QR code. A phone held over an A4 sheet
#: reads a symbol this size from the whole page's photograph.
QR_WIDTH_CM = 4.0


def _table(rb: ReportBuilder, table: dict, widths: list[float] | None = None) -> None:
    rb.table(table["rows"], header=table["header"] or None, caption=table["caption"],
             col_widths_cm=widths, font_size_pt=10.0)


def build_field_kit(site: SiteMetadata, boreholes: list[str], out_path: str | Path,
                    figures_dir: str | Path, config: Config | None = None) -> Path:
    """Write the field kit for ``boreholes`` to ``out_path``.

    Raises ValueError when no borehole is named, since a kit with no sheet
    is only the cards, and when a sheet code is too long for its symbol.
    """
    config = config or Config()
    content = field_kit_content(site, boreholes, config)
    if not content["sheets"]:
        raise ValueError("Name at least one borehole for the field kit.")
    rb = ReportBuilder(config.style, title=content["title"])

    for k, sheet in enumerate(content["sheets"]):
        if k:
            rb.page_break()
        rb.paragraph(sheet["title"], bold=True, size_pt=14)
        image = write_qr_png(sheet["payload"],
                             Path(figures_dir) / f"field_kit_qr_{k + 1}.png")
        rb.figure(image, sheet["code"], width_cm=QR_WIDTH_CM)
        if sheet["warning"]:
            rb.paragraph(sheet["warning"], bold=True)
        rb.header_block_table([(label, value) for label, value in sheet["header"]])
        for note in sheet["notes"]:
            rb.paragraph(note)
        rb.paragraph(sheet["discharge_note"])
        _table(rb, sheet["discharge"])
        _table(rb, sheet["bucket"])
        rb.paragraph(sheet["transcribe"], italic=True)
        for block in sheet["blocks"]:
            _table(rb, block, [3.0, 4.5, 4.5])
        _table(rb, sheet["recovery"], [3.0, 4.5, 4.5])

    for card in content["cards"]:
        rb.page_break()
        rb.paragraph(card["title"], bold=True, size_pt=14)
        for line in card["lines"]:
            rb.paragraph(line)
        for table in card["tables"]:
            _table(rb, table)
        for note in card["notes"]:
            rb.paragraph(note, italic=card["key"] == "disinfection")
    rb.references(content["references"])
    return rb.save(out_path)

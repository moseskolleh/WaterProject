"""The contractor scorecards as a Word document (PLAN.md step 6.3).

Lays out :func:`groundwater.scorecards.scorecard_content` over the project
files on the Portfolio page as the calibration report is laid out: the cover
with what the files hold, the summary, then each section with its
paragraphs, tables and bullets, and the references. The words and the
numbers are all in the content; this module only places them, as
``GWT.docx.scorecardReport`` does in the browser.
"""

from __future__ import annotations

from ..config import Config
from ..scorecards import scorecard_content
from ..verification import Issue
from .docx_utils import ReportBuilder

__all__ = ["build_scorecard_report"]

#: Each section's tables, by its key, with the widths their columns are
#: printed at (the page holds 16 cm between its margins).
_WIDTHS = {
    "cards": [[2.4, 1.3, 2.4, 2.0, 2.1, 2.0, 2.6, 1.2]],
    "checks": [[3.0, 2.6, 8.4, 2.0]],
    "dry": [[3.2, 1.6, 1.2, 1.6, 2.0, 1.8, 1.8, 2.8]],
}


def build_scorecard_report(files, out_path, issued_on: str = "", config: Config | None = None,
                           issue: Issue | None = None):
    """Write the contractor scorecards over ``files`` ((project label, works
    record, ledger) for each project file) to ``out_path`` and return its
    path. ``issue`` names the evidence (the project files on the page, PLAN.md
    step 8.1); its day is ``issued_on`` where it gives none."""
    config = config or Config()
    content = scorecard_content(files, issued_on, config)
    issue = issue or Issue()
    if not issue.issued_on:
        issue = Issue(issued_on=issued_on, evidence=issue.evidence)
    rb = ReportBuilder(config.style, title=content["title"], kind="scorecards", issue=issue, config=config)
    rb.cover([content["title"]], [content["subtitle"]], [(label, value) for label, value in content["rows"]])
    rb.table_of_contents()
    rb.executive_summary(content["summary"])
    for section in content["sections"]:
        rb.heading(section["heading"], 1)
        for text in section["paragraphs"]:
            rb.paragraph(text, align="justify")
        widths = _WIDTHS.get(section["key"], [])
        for k, table in enumerate(section["tables"]):
            rb.table(table["rows"], header=table["header"], caption=table["caption"],
                     col_widths_cm=widths[k] if k < len(widths) else None, font_size_pt=8.0)
        if section["bullets"]:
            rb.bullets(section["bullets"])
    rb.references(content["references"])
    return rb.save(out_path)

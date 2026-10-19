"""The calibration report as a Word document (PLAN.md step 5.2).

Lays out :func:`groundwater.calibration.calibration_content` over a pooled
ledger: the cover with what the ledgers hold, the summary, then each
section with its paragraphs, figures, tables and bullets, and the
references. The words and the numbers are all in the content; this module
only places them, and draws the two figures the content names
(:mod:`groundwater.calibration_plots`), as ``GWT.docx.calibrationReport``
does in the browser.
"""

from __future__ import annotations

from pathlib import Path

from ..calibration import calibration_content, depth_scores, odds_scores
from ..calibration_plots import plot_depth_calibration, plot_reliability
from ..config import Config
from .context import _figures_dir
from .docx_utils import ReportBuilder

__all__ = ["build_calibration_report", "calibration_figures", "figure_keys"]

#: Each section's tables, by its key, with the widths their columns are
#: printed at (the page holds 16 cm between its margins).
_WIDTHS = {
    "depth": [[3.0, 2.0, 5.0, 3.0, 3.0]],
    "odds": [[4.0, 2.6, 3.4, 6.0]],
    "hits": [[4.2, 1.6, 1.9, 1.9, 1.6, 2.2, 2.6]] * 3,
}


def calibration_figures(pooled: list[dict], keys, figures_dir: str | Path, config: Config | None = None) -> dict:
    """The figures named by ``keys`` (``depth``, ``reliability``), drawn into
    ``figures_dir``, as their PNG paths by key."""
    config = config or Config()
    folder = Path(figures_dir)
    out = {}
    if "depth" in keys:
        out["depth"] = plot_depth_calibration(depth_scores(pooled, config), folder / "calibration_depth.png",
                                              config.style)
    if "reliability" in keys:
        out["reliability"] = plot_reliability(odds_scores(pooled, config), folder / "calibration_reliability.png",
                                              config.style)
    return out


def figure_keys(content: dict) -> list[str]:
    """The keys of the figures a report's content names, in its order."""
    return [figure["key"] for section in content["sections"] for figure in section["figures"]]


def build_calibration_report(pooled: list[dict], out_path, issued_on: str = "", config: Config | None = None,
                             figures_dir: Path | None = None) -> Path:
    """Write the calibration report over ``pooled`` (the entries of
    :func:`groundwater.ledger.pool_ledgers`) to ``out_path`` and return its
    path. The figures the content names are drawn beside the document,
    unless a directory is named."""
    config = config or Config()
    content = calibration_content(pooled, issued_on, config)
    keys = figure_keys(content)
    figures = calibration_figures(pooled, keys, _figures_dir(figures_dir, out_path), config) if keys else {}
    rb = ReportBuilder(config.style, title=content["title"])
    rb.cover([content["title"]], [content["subtitle"]], [(label, value) for label, value in content["rows"]])
    rb.table_of_contents()
    rb.executive_summary(content["summary"])
    for section in content["sections"]:
        rb.heading(section["heading"], 1)
        for text in section["paragraphs"]:
            rb.paragraph(text, align="justify")
        for figure in section["figures"]:
            rb.figure(figures[figure["key"]], figure["caption"], width_cm=15.0)
        widths = _WIDTHS.get(section["key"], [])
        for k, table in enumerate(section["tables"]):
            rb.table(table["rows"], header=table["header"], caption=table["caption"],
                     col_widths_cm=widths[k] if k < len(widths) else None, font_size_pt=9.0)
        if section["bullets"]:
            rb.bullets(section["bullets"])
    rb.references(content["references"])
    return rb.save(out_path)

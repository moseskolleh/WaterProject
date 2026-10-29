"""The round sheet: what an area mechanic takes out on a service round.

One document for every round on a day (PLAN.md step 7.3), each round from a
new page: whose round it is, the day it was drawn up, how its stops were put
in order and how often each visit is due, then each stop in order with the
borehole's identifier and the line a scan of its plate begins with, where it
is, what is due and why, and blank boxes for the readings and for the visit.
It is a
working sheet, printed and written on at the borehole, so it makes no claim
about the water and carries no readiness stamp. The words are in
``data/text/rounds.yaml``; ``roundSheet`` in gwt-docx.js is the browser's
twin, printing the same parts in the same order.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..verification import Issue
from ..rounds import round_text, rounds_text, stop_sheet
from ..text import phrase
from .docx_utils import ReportBuilder

__all__ = ["build_round_sheet"]


def build_round_sheet(rounds: dict, out_path: str | Path,
                      config: Config | None = None, issue: Issue | None = None) -> Path:
    """Write the round sheet of ``rounds`` (what
    :func:`~groundwater.rounds.service_rounds` returns) to ``out_path``."""
    rb = ReportBuilder(config.style if config else None,
                       title=f"Service rounds - {rounds['as_of']}", kind="rounds", issue=issue,
                       config=config)
    words = rounds_text(rounds)
    if not rounds["rounds"]:
        rb.paragraph(phrase("rounds.sheet_title"), bold=True, align="center", size_pt=16)
        rb.paragraph(phrase("rounds.sheet_drawn", date=rounds["as_of"]), align="center")
        for line in words["summary"]:
            rb.paragraph(line)
        return rb.save(out_path)
    for index, one in enumerate(rounds["rounds"]):
        if index:
            rb.page_break()
        rb.paragraph(phrase("rounds.sheet_title"), bold=True, align="center", size_pt=16)
        rb.paragraph(phrase("rounds.sheet_mechanic",
                            mechanic=one["mechanic"] or phrase("rounds.unassigned")),
                     bold=True, align="center", size_pt=13)
        rb.paragraph(phrase("rounds.sheet_drawn", date=rounds["as_of"]), align="center")
        for line in round_text(one):
            rb.paragraph(line)
        rb.paragraph(words["method"], italic=True)
        rb.paragraph(words["intervals"], italic=True)
        rb.paragraph(phrase("rounds.sheet_check"), bold=True)
        for stop in one["stops"]:
            sheet = stop_sheet(stop)
            rb.heading(sheet["heading"], level=2, numbered=False)
            rb.table(sheet["details"], col_widths_cm=[5.0, 11.0])
            for visit in sheet["visits"]:
                rb.paragraph(visit["text"])
                widths = [1.2, 11.0, 3.8] if len(visit["header"]) == 3 else [7.0, 9.0]
                rb.table(visit["rows"], header=visit["header"], col_widths_cm=widths)
            rb.table(sheet["visit"]["rows"], header=sheet["visit"]["header"],
                     col_widths_cm=[7.0, 9.0])
        rb.paragraph(phrase("rounds.sheet_after"), italic=True)
    return rb.save(out_path)

"""Rule based extraction from PDFs that carry a text layer.

Uses pdfplumber (``pip install groundwater-toolkit[extract]``) to pull
words and tables, then matches header labels with the same canonical
patterns the template parsers use. Clean numeric parses get full
confidence; anything ambiguous is flagged for review. Image-only scans
yield no text here and should go through the AI extractor instead.

Two things a field sheet does that a naive reader gets wrong, and which
this module handles from word positions rather than from the page's
line art:

* **Header pairs run together.** ``extract_text()`` collapses the wide
  gap between two columns to a single space, so ``Community: Rokel``
  beside ``Client: Living Water International`` reads as one label with
  the other's text glued onto its value. Lines are rebuilt here from
  word coordinates, and a gap wide enough to be a column break is
  written as one, so the two are read as two fields.

* **Tables without ruling lines are invisible.** ``extract_tables()``
  finds a table by the rules drawn around it. A typed sheet very often
  has none - the columns are held by whitespace alone. Where that
  happens the table is found from the layout instead: a run of
  consecutive lines sharing a column structure. Ruled tables still go
  through pdfplumber, which is better at them.

The browser reader in ``docs/js/gwt-core.js`` does the same job with the
same algorithm, so a sheet read in either place gives the same tables.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Optional

from ..ingestion.common import match_label, split_inline_value
from ..utils import clean_text, parse_number
from .models import (
    ExtractedDocument,
    ExtractedField,
    ExtractedTable,
    UncertainCell,
)

_KIND_MARKERS = {
    "ves": ("ves", "schlumberger", "apparent resistivity", "sounding"),
    "pumping_test": ("pumping test", "step test", "constant discharge", "drawdown"),
    "drilling_log": ("drilling", "borehole log", "penetration"),
    "water_quality": ("water quality", "laboratory", "parameter", "guideline"),
}

#: Horizontal gap, in points, that reads as a column break rather than a
#: word space. About three characters at 10 pt.
_COLUMN_GAP_PT = 14.0

#: How far apart two word starts can be and still be the same column.
_COLUMN_TOLERANCE_PT = 8.0


def _guess_kind(text: str) -> str:
    text = text.lower()
    scores = {
        kind: sum(1 for marker in markers if marker in text)
        for kind, markers in _KIND_MARKERS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def extract_pdf_text(path: str | Path) -> ExtractedDocument:
    """Extract header fields and tables from a text-layer PDF."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise ImportError(
            "PDF extraction needs pdfplumber; install with "
            "'pip install groundwater-toolkit[extract]'"
        ) from exc

    path = Path(path)
    header: list[ExtractedField] = []
    tables: list[ExtractedTable] = []
    uncertain: list[UncertainCell] = []
    all_text: list[str] = []
    seen_fields: set[str] = set()

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines = _page_lines(page)
            all_text.append("\n".join(_line_text(line) for line in lines))

            # header labels from text lines ("Community: Rokel   Date: ...")
            header_lines: list[int] = []
            for position, line in enumerate(lines):
                matched = False
                for part in _split_line(_line_text(line)):
                    label, value = split_inline_value(part)
                    key = match_label(label)
                    if not key or not value:
                        continue
                    matched = True
                    if key in seen_fields:
                        continue
                    seen_fields.add(key)
                    header.append(ExtractedField(key, clean_text(value), 0.95))
                if matched:
                    header_lines.append(position)

            # Ruled tables are pdfplumber's job; it is better at them than a
            # column-clustering pass, which cannot see a merged cell.
            found = [_clean_table(raw) for raw in page.extract_tables() or []]
            candidates = [t for t in found if t is not None]
            if not candidates:
                candidates = _tables_from_lines(lines, set(header_lines))

            for columns, rows in candidates:
                index = len(tables)
                confidences = []
                for r, row in enumerate(rows):
                    row_conf = 1.0
                    for c, cell in enumerate(row):
                        conf, reason = _cell_confidence(
                            cell, columns[c] if c < len(columns) else ""
                        )
                        if conf < 1.0:
                            uncertain.append(UncertainCell(index, r, c, reason))
                            row_conf = min(row_conf, conf)
                    confidences.append(row_conf)
                tables.append(
                    ExtractedTable(
                        title=f"Table {index + 1}",
                        columns=columns,
                        rows=rows,
                        row_confidence=confidences,
                    )
                )

    text_blob = "\n".join(all_text)
    return ExtractedDocument(
        source=str(path),
        document_kind=_guess_kind(text_blob),
        header=header,
        tables=tables,
        uncertain_cells=uncertain,
        extractor="pdf-text",
        notes="Rule based extraction from the PDF text layer.",
    )


# --------------------------------------------------------------- page layout

#: A word as this module needs it: the text and where it starts and ends.
_Word = dict[str, Any]
_Line = list[_Word]


def _page_lines(page) -> list[_Line]:
    """Words grouped into lines, in reading order.

    ``extract_words`` returns words with coordinates but no line
    structure. Words are grouped by their vertical position, with a
    tolerance drawn from the word's own height so a large heading and
    small body text are each grouped at their own scale.
    """
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:  # noqa: BLE001  # pragma: no cover
        # Not a page with no text layer - that one raises nothing and
        # simply yields no words. What reaches here is a content stream
        # pdfplumber could not parse, and returning [] leaves it looking
        # blank. One unreadable page must not cost the other nine, so it
        # stays a skip until the reader has a flag channel to say so.
        return []

    lines: list[dict[str, Any]] = []
    for word in words:
        text = clean_text(word.get("text", ""))
        if not text:
            continue
        top = float(word.get("top", 0.0))
        height = max(float(word.get("bottom", top)) - top, 1.0)
        tolerance = max(height * 0.5, 2.0)
        for line in lines:
            if abs(line["top"] - top) <= tolerance:
                line["words"].append(
                    {"text": text, "x0": float(word.get("x0", 0.0)),
                     "x1": float(word.get("x1", 0.0))}
                )
                break
        else:
            lines.append({
                "top": top,
                "words": [{"text": text, "x0": float(word.get("x0", 0.0)),
                           "x1": float(word.get("x1", 0.0))}],
            })

    lines.sort(key=lambda line: line["top"])
    out: list[_Line] = []
    for line in lines:
        line["words"].sort(key=lambda w: w["x0"])
        out.append(line["words"])
    return out


def _line_text(line: _Line) -> str:
    """A line as text, with column breaks written as three spaces.

    That is the shape ``_split_line`` reads, and it is the piece
    ``extract_text()`` throws away.
    """
    parts: list[str] = []
    for i, word in enumerate(line):
        if i == 0:
            parts.append(word["text"])
            continue
        gap = word["x0"] - line[i - 1]["x1"]
        parts.append(("   " if gap > _COLUMN_GAP_PT else " ") + word["text"])
    return "".join(parts)


def _tables_from_lines(
    lines: list[_Line], header_lines: set[int]
) -> list[tuple[list[str], list[list[str]]]]:
    """Tables from the layout, for sheets with no ruling lines.

    A run of consecutive multi-word lines that share a column structure
    is a table. The first line of the run is its header row.
    """
    tables: list[tuple[list[str], list[list[str]]]] = []
    run: list[_Line] = []

    def flush() -> None:
        nonlocal run
        if len(run) >= 3:
            columns = _column_positions(run)
            if len(columns) >= 2:
                grid = [_to_cells(line, columns) for line in run]
                header, rows = grid[0], grid[1:]
                if rows:
                    tables.append((header, rows))
        run = []

    for position, line in enumerate(lines):
        # The header block is a two-column layout too, but its lines are
        # label/value pairs already read as header fields; folding them into
        # the reading table would put "Community: Rokel" where an AB/2
        # spacing belongs.
        if len(line) >= 2 and position not in header_lines:
            run.append(line)
        else:
            flush()
    flush()
    return tables


def _column_positions(lines: list[_Line]) -> list[float]:
    """Column edges: word start positions that recur down the block."""
    starts = sorted(word["x0"] for line in lines for word in line)
    clusters: list[dict[str, float]] = []
    for x in starts:
        if clusters and x - clusters[-1]["at"] <= _COLUMN_TOLERANCE_PT:
            clusters[-1]["n"] += 1
            clusters[-1]["at"] = (clusters[-1]["at"] + x) / 2
            continue
        clusters.append({"at": x, "n": 1})
    threshold = max(2, len(lines) // 2)
    return [c["at"] for c in clusters if c["n"] >= threshold]


def _to_cells(line: _Line, columns: list[float]) -> list[str]:
    cells = [""] * len(columns)
    for word in line:
        index = 0
        for i, edge in enumerate(columns):
            if word["x0"] >= edge - _COLUMN_TOLERANCE_PT:
                index = i
        cells[index] = f'{cells[index]} {word["text"]}' if cells[index] else word["text"]
    return cells


# ------------------------------------------------------------------ grading


def _split_line(line: str) -> list[str]:
    return [p for p in re.split(r"\t+|\s{3,}", line) if p.strip()]


def _clean_table(raw: Iterable[Iterable]) -> Optional[tuple[list[str], list[list[str]]]]:
    rows = [[clean_text(c) for c in row] for row in raw if any(clean_text(c) for c in row)]
    if len(rows) < 2:
        return None
    return rows[0], rows[1:]


def _cell_confidence(cell: str, column: str) -> tuple[float, str]:
    """Numeric columns should parse as numbers; empty cells in numeric
    columns and non-numeric junk are review items."""
    numeric_column = any(
        marker in column.lower()
        for marker in ("(m)", "m)", "ohm", "rate", "level", "depth", "time", "value", "ab/2", "mn")
    )
    if not numeric_column:
        return 1.0, ""
    if cell == "":
        return 0.6, "empty cell in a numeric column"
    if parse_number(cell) is None:
        return 0.4, "does not parse as a number"
    return 1.0, ""

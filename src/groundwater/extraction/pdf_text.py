"""Rule based extraction from PDFs that carry a text layer.

Uses pdfplumber (``pip install groundwater-toolkit[extract]``) to pull
words and tables, then matches header labels with the same canonical
patterns the template parsers use. Clean numeric parses get full
confidence; anything ambiguous is flagged for review. Image-only scans
yield no text here and should go through the AI extractor instead.
"""

from __future__ import annotations

from pathlib import Path

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
            text = page.extract_text() or ""
            all_text.append(text)
            # header labels from text lines ("Community: Rokel   Date: ...")
            for line in text.splitlines():
                for part in _split_line(line):
                    label, value = split_inline_value(part)
                    key = match_label(label)
                    if key and value and key not in seen_fields:
                        seen_fields.add(key)
                        header.append(ExtractedField(key, clean_text(value), 0.95))

            for raw_table in page.extract_tables() or []:
                table = _clean_table(raw_table)
                if table is None:
                    continue
                columns, rows = table
                index = len(tables)
                confidences = []
                for r, row in enumerate(rows):
                    row_conf = 1.0
                    for c, cell in enumerate(row):
                        conf, reason = _cell_confidence(cell, columns[c] if c < len(columns) else "")
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


def _split_line(line: str) -> list[str]:
    import re

    return [p for p in re.split(r"\t+|\s{3,}", line) if p.strip()]


def _clean_table(raw: list[list]) -> tuple[list[str], list[list[str]]] | None:
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

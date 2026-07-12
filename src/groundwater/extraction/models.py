"""Common structure for extracted field sheet content.

Whatever the source (text PDF, photographed sheet, AI extraction),
the result is header fields plus data tables, each value carrying a
confidence in [0, 1]. Values below the review threshold are flagged
and highlighted in the review workbook rather than silently accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REVIEW_THRESHOLD = 0.85


@dataclass
class ExtractedField:
    name: str
    value: str
    confidence: float = 1.0

    @property
    def needs_review(self) -> bool:
        return self.confidence < REVIEW_THRESHOLD


@dataclass
class UncertainCell:
    table_index: int
    row: int  # 0-based data row
    column: int  # 0-based column
    reason: str = ""


@dataclass
class ExtractedTable:
    title: str
    columns: list[str]
    rows: list[list[str]]
    row_confidence: list[float] = field(default_factory=list)

    def confidence_for_row(self, index: int) -> float:
        if index < len(self.row_confidence):
            return self.row_confidence[index]
        return 1.0


@dataclass
class ExtractedDocument:
    source: str
    document_kind: str = "unknown"  # ves | pumping_test | drilling_log | water_quality | unknown
    header: list[ExtractedField] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    uncertain_cells: list[UncertainCell] = field(default_factory=list)
    notes: str = ""
    extractor: str = ""  # "pdf-text" | "claude"

    def get(self, name: str) -> str:
        key = name.strip().lower()
        for f in self.header:
            if f.name.strip().lower() == key:
                return f.value
        return ""

    @property
    def review_items(self) -> list[str]:
        items = [
            f"header field '{f.name}' = '{f.value}' (confidence {f.confidence:.2f})"
            for f in self.header
            if f.needs_review
        ]
        for cell in self.uncertain_cells:
            if cell.table_index < len(self.tables):
                table = self.tables[cell.table_index]
                value = ""
                if cell.row < len(table.rows) and cell.column < len(table.rows[cell.row]):
                    value = table.rows[cell.row][cell.column]
                items.append(
                    f"table '{table.title}' row {cell.row + 1}, column "
                    f"'{table.columns[cell.column] if cell.column < len(table.columns) else cell.column + 1}'"
                    f" = '{value}'" + (f" ({cell.reason})" if cell.reason else "")
                )
        return items

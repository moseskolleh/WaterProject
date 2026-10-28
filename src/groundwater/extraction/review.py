"""Review workbook generation for extracted documents.

Every extraction produces a review workbook: the header fields and
every table, with uncertain values highlighted amber and a Review
sheet listing everything that needs checking. For recognised VES
sheets the standard template can also be filled directly so the normal
parsers pick the data up after review.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from ..ingestion.common import match_label
from ..ingestion.ves import reading_columns
from ..text import phrase, phrase_table
from .models import REVIEW_THRESHOLD, ExtractedDocument, ExtractedTable

_AMBER = PatternFill("solid", fgColor="FFE08A")
_HEADER_FONT = Font(bold=True)


def ves_template_columns(table: ExtractedTable) -> tuple[dict[str, int], list[str]]:
    """The columns of an extracted VES table the template takes, and what
    it lacks.

    Returns ``(placed, missing)``: ``placed`` maps "ab2", "mn" or
    "mn_half", "rho" or "resistance", and "k" to the table's columns;
    ``missing`` holds the ``extraction.ves_missing`` keys that keep the
    readings out of the template, empty when they can go in.

    The columns are read by the VES reader's own rules
    (``ingestion.ves.reading_columns``), which are the rules that read the
    filled template back. Picked by substring instead, a sheet headed AB/2,
    MN/2, K, Resistance (ohm), App. Resistivity (ohm-m) had its resistances
    written into the template's apparent-resistivity column, a factor K too
    small, and its half-spacings into the full MN column; every cell parsed,
    so nothing was flagged. As the reader does, an apparent resistivity is
    taken ahead of a resistance, and MN ahead of MN/2.
    """
    cols = reading_columns(list(table.columns))
    placed: dict[str, int] = {}
    missing: list[str] = []
    if "ab2" in cols:
        placed["ab2"] = cols["ab2"]
    else:
        missing.append("wenner" if "a" in cols else "spacing")
    if "mn" in cols:
        placed["mn"] = cols["mn"]
    elif "mn_half" in cols:
        placed["mn_half"] = cols["mn_half"]
    if "rho" in cols:
        placed["rho"] = cols["rho"]
    elif "resistance" in cols:
        placed["resistance"] = cols["resistance"]
        if "k" in cols:
            placed["k"] = cols["k"]
        elif "mn" not in placed and "mn_half" not in placed:
            # the reader works K out from AB/2 and MN; with neither K nor MN
            # every row would be dropped
            missing.append("factor")
    else:
        missing.append("value")
    return placed, missing


def _ves_unplaced(table: ExtractedTable, missing: list[str]) -> str:
    reasons = phrase_table("extraction.ves_missing")
    return phrase(
        "extraction.ves_unplaced",
        table=table.title,
        missing="; ".join(reasons[key] for key in missing),
        headings=", ".join(f"'{c}'" for c in table.columns) or "none",
    )


def sheet_review_items(document: ExtractedDocument) -> list[str]:
    """What needs checking about the sheet as a whole, before any one value.

    A sheet whose table was not found, or a VES sheet whose readings the
    template cannot take, has lost every reading; its review used to say
    "None: all values extracted with high confidence".
    """
    if not document.tables:
        return [phrase("extraction.no_table")]
    if document.document_kind == "ves":
        _placed, missing = ves_template_columns(document.tables[0])
        if missing:
            return [_ves_unplaced(document.tables[0], missing)]
    return []


def write_review_workbook(document: ExtractedDocument, path: str | Path) -> Path:
    """Write the extraction to an Excel review workbook.

    Sheet 1 (Header): field, value, confidence; low confidence rows
    highlighted. One sheet per table with uncertain cells highlighted.
    Final Review sheet lists every flagged item with its reason.
    """
    path = Path(path)
    wb = Workbook()

    ws = wb.active
    ws.title = "Header"
    ws.append(["Field", "Value", "Confidence"])
    for cell in ws[1]:
        cell.font = _HEADER_FONT
    for field in document.header:
        ws.append([field.name, field.value, round(field.confidence, 2)])
        if field.needs_review:
            for cell in ws[ws.max_row]:
                cell.fill = _AMBER
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 32

    flagged = {(c.table_index, c.row, c.column): c.reason for c in document.uncertain_cells}
    for index, table in enumerate(document.tables):
        sheet = wb.create_sheet(f"Table {index + 1}"[:31])
        sheet.append([table.title])
        sheet["A1"].font = _HEADER_FONT
        sheet.append(table.columns)
        for cell in sheet[2]:
            cell.font = _HEADER_FONT
        for r, row in enumerate(table.rows):
            sheet.append(row)
            for c in range(len(row)):
                if (index, r, c) in flagged:
                    sheet.cell(row=sheet.max_row, column=c + 1).fill = _AMBER
            if table.confidence_for_row(r) < REVIEW_THRESHOLD:
                for c in range(len(row)):
                    sheet.cell(row=sheet.max_row, column=c + 1).fill = _AMBER

    review = wb.create_sheet("Review")
    review.append(["Items needing manual review"])
    review["A1"].font = _HEADER_FONT
    items = document.review_items
    if items:
        for item in items:
            review.append([item])
    else:
        review.append(["None: all values extracted with high confidence."])
    review.append([])
    review.append([f"Source: {document.source}"])
    review.append([f"Extractor: {document.extractor}"])
    review.append([f"Document kind: {document.document_kind}"])
    if document.notes:
        review.append([f"Notes: {document.notes}"])
    review.column_dimensions["A"].width = 100

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def fill_ves_template(document: ExtractedDocument, path: str | Path) -> Path:
    """Fill the standard VES template from an extracted VES sheet.

    Header fields are mapped through the same label patterns the
    parsers use; the first table supplies the readings. Values that
    need review keep their amber highlight in the filled template.

    The readings go in as the sheet has them, under headings the VES
    reader reads the way the sheet meant them: a half-spacing column is
    headed "MN/2 (m)", so the reader doubles it, and a sheet that records
    resistances has them headed "Resistance (ohm)", with its K column
    beside them where it has one, so the reader works the apparent
    resistivity out as it does for any such sheet. A table whose readings
    cannot be placed that way is refused, with the reason, rather than
    written as a template that reads back with no readings.
    """
    from ..ingestion.templates import _table_header, write_ves_template

    if document.document_kind != "ves":
        raise ValueError("fill_ves_template needs a document of kind 'ves'")
    if not document.tables:
        raise ValueError("No data table was extracted")

    table = document.tables[0]
    placed, missing = ves_template_columns(table)
    if missing:
        reason = _ves_unplaced(table, missing)
        raise ValueError(reason[0].upper() + reason[1:] + ".")
    path = Path(path)
    write_ves_template(path, n_soundings=1, n_rows=max(len(table.rows), 18))
    wb = load_workbook(path)
    ws = wb.active
    # The blank template's own sounding number and instrument are not the
    # sheet's: left in, they were read back as if the sheet had given them.
    ws["D3"] = None
    ws["D8"] = None

    # header mapping: canonical key -> template value cell
    cell_map = {
        "client": "B2", "community": "D2",
        "project": "B3", "sounding_id": "D3",
        "district": "B4", "easting": "D4",
        "date": "B5", "northing": "D5",
        "supervisor": "B6", "elevation_m": "D6",
        "chiefdom": "B7", "utm_zone": "D7",
        "array_type": "B8", "instrument": "D8",
    }
    for field in document.header:
        # The AI extractor names a field the way the sheet does ("Sounding
        # Number"), which the label patterns resolve. The text-layer extractor
        # has already resolved it, so its name is the canonical key itself -
        # and a canonical key does not match its own pattern ("sounding_id" is
        # not "sounding number"). Accept either, or the field silently fails
        # to land in the template.
        key = field.name if field.name in cell_map else match_label(field.name)
        target = cell_map.get(key or "")
        if target:
            ws[target] = field.value
            if field.needs_review:
                ws[target].fill = _AMBER

    flagged = {
        (c.row, c.column): c.reason
        for c in document.uncertain_cells
        if c.table_index == 0
    }
    # template column (1-based) <- the extracted table's column
    targets = [(placed["ab2"], 2)]
    # the blank template's own headings, changed where the sheet's columns
    # are not what they say
    headings = [ws.cell(row=10, column=c).value for c in range(1, 5)]
    if "mn" in placed:
        targets.append((placed["mn"], 3))
    elif "mn_half" in placed:
        targets.append((placed["mn_half"], 3))
        headings[2] = "MN/2 (m)"
    if "rho" in placed:
        targets.append((placed["rho"], 4))
    else:
        targets.append((placed["resistance"], 4))
        headings[3] = "Resistance (ohm)"
        if "k" in placed:
            targets.append((placed["k"], 5))
            headings.append("K")
    _table_header(ws, 10, headings)
    for r, row in enumerate(table.rows):
        target_row = 11 + r
        ws.cell(row=target_row, column=1, value=r + 1)
        for source_col, target_col in targets:
            if source_col >= len(row):
                continue
            cell = ws.cell(row=target_row, column=target_col, value=row[source_col])
            if (r, source_col) in flagged:
                cell.fill = _AMBER
    wb.save(path)
    return path

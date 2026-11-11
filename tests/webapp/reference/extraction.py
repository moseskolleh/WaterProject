"""Reading field sheets: the unruled PDF field sheet and the cases the two
engines each got wrong - the "pdf_sheet" and "extraction" entries of
``reference.json``. Producing these is what needs the ``extract`` extra.
"""

from __future__ import annotations

import base64
import tempfile
import zlib
from pathlib import Path
from types import SimpleNamespace

from .common import clean


# ------------------------------------------------- the unruled PDF field sheet

#: A typed VES sheet, placed with Tm/Tj and with no ruling line anywhere on
#: the page. Both readers find its table from word positions, so this is the
#: one fixture where the two have to agree byte for byte on the same input -
#: the bytes travel in the reference file and are decoded in the browser.
_PDF_ROWS = [[1, 1.5, 0.5, 210.4], [2, 2, 0.5, 233.1], [3, 3, 0.5, 268.0],
             [4, 4, 0.5, 291.7], [5, 6, 0.5, 302.5], [6, 8, 0.5, 288.2],
             [7, 10, 0.5, 264.9], [8, 15, 0.5, 198.3]]

_PDF_HEADER = [
    (60, 760, "SCHLUMBERGER ARRAY VES FIELD DATA"),
    (60, 735, "Community: Rokel"), (300, 735, "Client: Living Water International"),
    (60, 715, "District: Port Loko"), (300, 715, "Sounding Number: VES A-1"),
    (60, 695, "Date: 2023-05-14"), (300, 695, "Field Supervisor: M. Kolleh"),
    (60, 650, "No."), (110, 650, "AB/2 (m)"), (200, 650, "MN (m)"),
    (280, 650, "Apparent Resistivity (ohm-m)"),
]


def _typed_field_sheet_pdf() -> bytes:
    placed = list(_PDF_HEADER)
    for i, row in enumerate(_PDF_ROWS):
        y = 630 - i * 18
        for x, value in zip((60, 110, 200, 280), row, strict=True):
            placed.append((x, y, str(value)))
    return _placed_sheet_pdf(placed)


def _placed_sheet_pdf(placed) -> bytes:
    """A one-page PDF with each (x, y, text) placed by Tm/Tj in Helvetica.
    An empty list draws a line and no text at all, as a scanner's page
    carries none."""
    ops = ["BT", "/F1 10 Tf"]
    for x, y, text in placed:
        escaped = str(text).replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(f"1 0 0 1 {x} {y} Tm ({escaped}) Tj")
    ops.append("ET")
    if not placed:
        ops = ["0.5 w", "60 600 m", "400 600 l", "S"]
    # level 9 and no timestamp, so the same table always gives the same bytes
    content = zlib.compress("\n".join(ops).encode("latin-1"), 9)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"),
        b"<< /Length 6 0 R /Filter /FlateDecode >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        str(len(content)).encode(),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def pdf_sheet_reference() -> dict:
    """What the Python reader makes of the sheet, plus the sheet itself."""
    from groundwater.extraction.pdf_text import extract_pdf_text

    pdf = _typed_field_sheet_pdf()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ves_sheet.pdf"
        path.write_bytes(pdf)
        document = extract_pdf_text(path)

    return {
        "b64": base64.b64encode(pdf).decode("ascii"),
        "kind": document.document_kind,
        "header": [[f.name, f.value] for f in document.header],
        "tables": [{"columns": list(t.columns), "rows": [list(r) for r in t.rows]}
                   for t in document.tables],
        "uncertain": len(document.uncertain_cells),
    }


# ------------------------------------------------------- reading field sheets

#: Cells the text-layer grader is given, under a numeric heading. parse_number
#: takes the first number in a cell, so the grader asks whether that number
#: is all there is: a scanner's letter O for a zero ("12O.4") is a misread.
EXTRACTION_CELLS = [
    "120.4", "078,7", "2,933", "1.234,5", "80m", "80 m", "120.4 ohm-m",
    "120.4ohm.m", "120.4 \u03a9m", "120.4 \u2126m", "120.4 \u03c9\u00b7m", "1e3", ".5",
    "-3", "5 min", "2.5 m3/h", "0.8 l/s", "4 m/min",
    "12O.4", "9B.1", "8O.2", "12O", "1l", "1 234", "1/2", "12.", "45 ft",
    "<0.01", "08:30", "1,2,3", "m", "", "--",
]

#: AI replies with a VES table, headed the ways field sheets head one: the
#: template takes what the VES reader reads back, and refuses the rest.
_RK_ROWS = [["1", "1.5", "0.25", "13.74", "8.76", "120.4"],
            ["2", "2", "0.25", "24.74", "3.97", "98.1"],
            ["3", "3", "0.25", "56.16", "1.43", "80.2"],
            ["4", "4", "0.25", "100.14", "0.659", "66.0"],
            ["5", "6", "0.25", "225.8", "0.227", "51.3"]]
_RK_COLUMNS = ["No.", "AB/2 (m)", "MN/2 (m)", "K", "Resistance (ohm)",
               "App. Resistivity (ohm-m)"]
EXTRACTION_TABLES = {
    "all_six": [0, 1, 2, 3, 4, 5],
    "resistance_and_k": [0, 1, 2, 3, 4],
    "resistance_only": [0, 1, 2, 4],
    "resistance_no_mn": [0, 1, 4],
    "no_mn": [0, 1, 5],
}


def _extraction_payload(columns, rows, header=True):
    return {
        "document_kind": "ves",
        "header": [{"name": "Community", "value": "Rokel", "confidence": 0.95},
                   {"name": "Sounding Number", "value": "VES 3", "confidence": 0.95}]
        if header else [],
        "tables": [{"title": "Readings", "columns": columns, "rows": rows}],
        "uncertain_cells": [{"table_index": 0, "row": 1, "column": 1,
                             "reason": "smudged"}],
        "notes": "",
    }


def extraction_payloads() -> dict:
    out = {}
    for name, keep in EXTRACTION_TABLES.items():
        out[name] = _extraction_payload(
            [_RK_COLUMNS[i] for i in keep], [[row[i] for i in keep] for row in _RK_ROWS])
    out["wenner"] = _extraction_payload(
        ["No.", "a (m)", "Apparent Resistivity (ohm-m)"],
        [["1", "1", "120.4"], ["2", "2", "98.1"]])
    out["unheaded"] = _extraction_payload(
        ["Field readings", "(Schlumberger", "array)", ""],
        [["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"],
         ["1", "1.5", "0.5", "120.4"]], header=False)
    # a table the transcription left untitled is named "Table 1" in both
    out["untitled"] = _extraction_payload(
        ["No.", "a (m)", "Apparent Resistivity (ohm-m)"], [["1", "1", "120.4"]])
    out["untitled"]["tables"][0]["title"] = ""
    out["no_table"] = dict(_extraction_payload([], []), tables=[], uncertain_cells=[])
    out["no_table_pumping"] = dict(out["no_table"], document_kind="pumping_test")
    return out


#: The replies an extraction can come back with: (stop reason, content).
EXTRACTION_REPLIES = {
    "cut_off": ("max_tokens", [{"type": "thinking", "thinking": "..."},
                               {"type": "text", "text": '{"document_kind": "ves", "hea'}]),
    "cut_off_thinking": ("max_tokens", [{"type": "thinking", "thinking": "..."}]),
    "refusal": ("refusal", []),
    "no_text": ("end_turn", [{"type": "thinking", "thinking": "..."}]),
    "not_json": ("end_turn", [{"type": "text", "text": "Here is the sheet: {"}]),
    "not_an_object": ("end_turn", [{"type": "text", "text": "[1, 2]"}]),
    "no_reason": (None, [{"type": "text", "text": "null"}]),
    "complete": ("end_turn", [{"type": "text", "text": '{"document_kind": "ves"}'}]),
}


def captioned_sheet_placed() -> list:
    """The typed VES sheet with a caption above its headings, a note under its
    readings and three cells a scanner misread: the caption used to become the
    Python reader's header and the note a reading, and "12O.4" passed as 12."""
    placed = list(_PDF_HEADER)
    placed.append((60, 668, "Field readings (Schlumberger array)"))
    rows = [list(r) for r in _PDF_ROWS[:5]]
    rows[0][3], rows[1][3], rows[2][3] = "21O.4", "2B3.1", "268.O"
    for i, row in enumerate(rows):
        y = 630 - i * 18
        for x, value in zip((60, 110, 200, 280), row, strict=True):
            placed.append((x, y, str(value)))
    placed.append((60, 630 - 5 * 18, "Notes: MN is the full potential electrode spacing."))
    return placed


def extraction_reference() -> dict:
    """What reading a field sheet gives, in the cases the two engines each got
    wrong: the grader, the filled template read back, the replies an AI
    transcription can end with, and two PDFs - a captioned sheet with misread
    cells, and one with no text layer at all."""
    from groundwater.extraction.claude import ClaudeExtractor, _reply_payload
    from groundwater.extraction.pdf_text import _cell_confidence, extract_pdf_text
    from groundwater.extraction.review import fill_ves_template
    from groundwater.ingestion import read_ves_workbook
    from groundwater.utils import is_whole_number

    out: dict = {
        "cells": [[cell, *_cell_confidence(cell, "Apparent Resistivity (ohm-m)"),
                   is_whole_number(cell)] for cell in EXTRACTION_CELLS],
        "payloads": extraction_payloads(),
        "fills": {},
        "replies_in": {name: [stop, content]
                       for name, (stop, content) in EXTRACTION_REPLIES.items()},
        "replies": {},
    }
    with tempfile.TemporaryDirectory() as tmp:
        for name, payload in out["payloads"].items():
            document = ClaudeExtractor._to_document(payload, "scan.jpg")
            entry: dict = {"review": document.review_items}
            if not document.tables:
                # both apps offer the template only for a VES table
                out["fills"][name] = entry
                continue
            try:
                path = fill_ves_template(document, Path(tmp) / f"{name}.xlsx")
            except ValueError as exc:
                entry["refused"] = str(exc)
            else:
                s = read_ves_workbook(path)[0]
                entry.update({
                    "ab2": clean(s.ab2), "mn": clean(s.mn), "rho": clean(s.rho_app),
                    "flags": [f.code for f in s.flags], "id": s.sounding_id,
                    "community": s.site.community, "instrument": s.instrument,
                    "array": s.array_type,
                })
            out["fills"][name] = entry

        for name, (stop, content) in EXTRACTION_REPLIES.items():
            reply = SimpleNamespace(stop_reason=stop,
                                    content=[SimpleNamespace(**b) for b in content])
            try:
                out["replies"][name] = {"kind": _reply_payload(reply)["document_kind"]}
            except RuntimeError as exc:
                out["replies"][name] = {"error": str(exc)}

        pdfs = {"captioned": _placed_sheet_pdf(captioned_sheet_placed()),
                "no_text": _placed_sheet_pdf([])}
        out["pdfs"] = {}
        for name, pdf in pdfs.items():
            path = Path(tmp) / f"{name}.pdf"
            path.write_bytes(pdf)
            entry = {"b64": base64.b64encode(pdf).decode("ascii")}
            try:
                document = extract_pdf_text(path)
            except ValueError as exc:
                entry["error"] = str(exc)
            else:
                entry.update({
                    "tables": [{"columns": list(t.columns), "rows": [list(r) for r in t.rows]}
                               for t in document.tables],
                    "uncertain": [[c.table_index, c.row, c.column, c.reason]
                                  for c in document.uncertain_cells],
                    "review": document.review_items,
                })
            out["pdfs"][name] = entry
    return out

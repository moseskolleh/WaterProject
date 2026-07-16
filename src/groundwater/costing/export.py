"""Bill of quantities Excel export.

Writes the estimate as a working BoQ workbook the contractor or client
can edit: quantities and rates stay as numbers with an amount formula
per line, so adjusting a rate updates the totals in Excel.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .model import CostEstimate

ACCENT = "1F5C8B"
LIGHT = "DCE6F1"

_thin = Side(style="thin", color="9BB3C8")
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def write_boq_workbook(estimate: CostEstimate, path: str | Path) -> Path:
    """Write the bill of quantities with live amount formulas."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Bill of quantities"

    ws["A1"] = "BILL OF QUANTITIES - BOREHOLE CONSTRUCTION"
    ws["A1"].font = Font(bold=True, size=13, color=ACCENT)
    ws.merge_cells("A1:G1")
    ws["A2"] = (
        "Amounts are formulas (quantity x rate); edit quantities or "
        "rates and the totals update. All values in USD."
    )
    ws["A2"].font = Font(italic=True, size=9)
    ws.merge_cells("A2:G2")

    headers = ["Code", "Stage", "Item", "Unit", "Quantity", "Rate (USD)", "Amount (USD)"]
    header_row = 4
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = Font(bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=ACCENT)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = BORDER

    row = header_row + 1
    first_item_row = row
    current_stage = None
    for item in sorted(
        estimate.items,
        key=lambda i: (
            [s for s, _ in estimate.by_stage()].index(i.stage)
            if i.stage in dict(estimate.by_stage())
            else 99,
            i.code,
        ),
    ):
        if item.stage != current_stage:
            current_stage = item.stage
            cell = ws.cell(row=row, column=1, value=current_stage.upper())
            cell.font = Font(bold=True, size=10, color=ACCENT)
            cell.fill = PatternFill("solid", fgColor=LIGHT)
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
            row += 1
        values = [
            item.code,
            item.stage,
            item.item,
            item.unit,
            round(item.quantity, 2),
            round(item.unit_cost_usd, 2),
            f"=E{row}*F{row}",
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = BORDER
            if col in (5, 6, 7):
                cell.number_format = "#,##0.00"
        row += 1
    last_item_row = row - 1

    def _summary(label: str, formula: str, bold: bool = False) -> None:
        nonlocal row
        cell = ws.cell(row=row, column=3, value=label)
        cell.font = Font(bold=True, size=10)
        amount = ws.cell(row=row, column=7, value=formula)
        amount.number_format = "#,##0.00"
        amount.font = Font(bold=bold, size=10)
        amount.border = BORDER
        row += 1

    row += 1
    direct_cell = f"G{row}"
    _summary(
        "Direct works cost",
        f"=SUMPRODUCT(E{first_item_row}:E{last_item_row},F{first_item_row}:F{last_item_row})",
        bold=True,
    )
    _summary(
        f"Overheads ({estimate.overheads_percent:g}%)",
        f"={direct_cell}*{estimate.overheads_percent / 100.0}",
    )
    total_cell = f"G{row}"
    _summary("Total cost", f"={direct_cell}*{1 + estimate.overheads_percent / 100.0}", bold=True)
    _summary(
        f"Margin ({estimate.margin_percent:g}%)",
        f"={total_cell}*{estimate.margin_percent / 100.0}",
    )
    _summary(
        "Contract price",
        f"={total_cell}*{1 + estimate.margin_percent / 100.0}",
        bold=True,
    )

    widths = (8, 14, 52, 10, 10, 12, 14)
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width

    wb.save(path)
    return path

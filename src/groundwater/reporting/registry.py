"""The asset record: what stays with the borehole after the project ends.

Two documents in one file, because they are two halves of the same job.

The **placard** is a single page meant to be printed, laminated and fixed
to the headworks. It carries the identifier in large type, the QR symbol
that encodes it, and the handful of facts a technician needs before opening
anything: where it is, how deep, what pump. Nothing on it goes out of date,
which is why the maintenance history is deliberately not on it.

The **asset record** is the history: what has happened, what condition that
leaves the borehole in, and what is now overdue. It is the document a
district water office reads when deciding where to send a repair team, and
it says plainly when the answer is that nobody knows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from docx.shared import Pt

from .. import qr
from ..config import Config
from ..registry import (
    Asset,
    AssetState,
    Schedule,
    asset_state,
    placard_lines,
    qr_payload,
)
from .docx_utils import ReportBuilder

__all__ = [
    "AssetReportInputs",
    "build_asset_placard",
    "build_asset_record",
    "write_qr_png",
]

#: Level H, so the symbol still reads after a season of mud and sunlight.
PLACARD_ECC = "H"


def write_qr_png(text: str, out_path: str | Path, *, scale: int = 10,
                 ecc: str = PLACARD_ECC) -> Path:
    """Render ``text`` as a QR symbol on disk, and return where it went."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(qr.to_png(qr.encode(text, ecc=ecc), scale=scale))
    return path


@dataclass
class AssetReportInputs:
    asset: Asset
    figures_dir: str | Path
    today: date | None = None
    schedule: Schedule | None = None
    prepared_by: str = ""
    readiness: Any = None


def _state(inputs: AssetReportInputs) -> AssetState:
    return asset_state(inputs.asset, inputs.today or date.today(),
                       inputs.schedule)


def build_asset_placard(inputs: AssetReportInputs, out_path: str | Path,
                        config: Config | None = None) -> Path:
    """The page that gets fixed to the borehole."""
    asset = inputs.asset
    rb = ReportBuilder(config.style if config else None,
                       title=f"Borehole {asset.asset_id}")

    rb.paragraph("BOREHOLE IDENTIFICATION PLATE", bold=True, align="center")
    rb.paragraph(asset.asset_id, bold=True, size_pt=26, align="center")
    rb.paragraph(asset.label, size_pt=13, align="center")

    image = write_qr_png(qr_payload(asset),
                         Path(inputs.figures_dir) / f"qr_{asset.asset_id}.png")
    rb.figure(image, "Scan for this borehole's identifier and position. The "
                     "symbol carries the details themselves, so it reads with "
                     "no network and no application installed.", width_cm=7.0)

    rb.table([[label, value] for label, value in placard_lines(asset,
                                                               _state(inputs))],
             header=["", ""], caption="Borehole details",
             col_widths_cm=[5.0, 10.0])
    rb.paragraph(
        "Report a breakdown or a change to this borehole against the "
        "identifier above. Quote it in full, including the last character - "
        "it is a check character, and it is what stops a repair being "
        "recorded against a different village's borehole.",
        italic=True)
    return rb.save(out_path)


def build_asset_record(inputs: AssetReportInputs, out_path: str | Path,
                       config: Config | None = None) -> Path:
    """The maintenance history and what it means today."""
    asset = inputs.asset
    state = _state(inputs)
    today = inputs.today or date.today()
    rb = ReportBuilder(config.style if config else None,
                       title=f"Asset record - {asset.label}")

    rb.cover(
        ["Borehole Asset Record"],
        [asset.label, asset.asset_id],
        [("Status", state.label), ("As at", today.isoformat())]
        + ([("Prepared by", inputs.prepared_by)] if inputs.prepared_by else []),
    )
    rb.provisional_stamp(inputs.readiness)

    rb.heading("Condition")
    rb.paragraph(f"{state.label}. {state.detail}")
    if state.days_out_of_service is not None:
        rb.paragraph(
            f"This borehole has been out of service for "
            f"{state.days_out_of_service} days. Every day counted here is a "
            "day the community went back to whatever they used before.",
            bold=True)
    if state.undated_events:
        rb.paragraph(
            f"{state.undated_events} record(s) carry a date that could not be "
            "read. They are listed below with the date as written, but they "
            "establish nothing about when anything last happened.")

    rb.heading("Details")
    rb.table([[label, value] for label, value in placard_lines(asset, state)],
             header=["", ""], col_widths_cm=[5.0, 10.0])

    rb.heading("Outstanding")
    overdue = state.overdue
    unknown = [item for item in state.due if item.state == "unknown"]
    if overdue or unknown:
        rb.bullets([item.detail for item in overdue]
                   + [item.detail for item in unknown])
    else:
        scheduled = [item for item in state.due
                     if item.state in ("scheduled", "due")]
        if scheduled:
            rb.bullets([item.detail for item in scheduled])
        else:
            rb.paragraph("Nothing is outstanding.")

    rb.heading("History")
    if asset.events:
        rows = []
        for event in sorted(asset.events, key=lambda e: (e.when or "9999",
                                                         e.kind)):
            rows.append([event.when or "(no date)", event.label,
                         event.note or "", event.by or "",
                         "yes" if event.photo else ""])
        rb.table(rows, header=["Date", "Event", "Note", "Recorded by", "Photo"],
                 caption="Everything recorded against this borehole",
                 col_widths_cm=[2.4, 3.2, 6.0, 2.4, 1.5])
        rb.paragraph(
            "This history is append-only: a mistake is corrected by recording "
            "the correction, so both entries stay visible. Nothing here has "
            "been edited or removed.", italic=True)
    else:
        rb.paragraph(
            "Nothing has ever been recorded against this borehole. That is "
            "not the same as nothing having happened to it.", bold=True)
    return rb.save(out_path)

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

from ..utils import plural

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


from .. import qr
from ..config import Config
from ..registry import (
    Asset,
    AssetState,
    Schedule,
    asset_state,
    placard_lines,
    qr_payload,
    report_link,
)
from ..models import SiteMetadata
from ..sanitary import form_rows, sanitary_risk
from ..text import phrase
from .citations import references_for
from .context import add_area_section
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
    #: The water quality assessment of the borehole's latest sample, whose
    #: E. coli count the sanitary risk reads (PLAN.md step 7.5); None when
    #: the project holds none.
    quality: Any = None


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

    # the report address the programme set (PLAN.md step 7.1): with one,
    # the symbol is a link to the borehole's report page; one the registry
    # refuses stops the plate rather than being printed on it
    report_url = (config or Config()).service.report_url
    image = write_qr_png(qr_payload(asset, report_url),
                         Path(inputs.figures_dir) / f"qr_{asset.asset_id}.png")
    rb.figure(image, phrase("fault_reports.placard_caption_link"
                            if report_link(asset.asset_id, report_url)
                            else "fault_reports.placard_caption_text"), width_cm=7.0)

    rb.table([[label, value] for label, value in placard_lines(asset,
                                                               _state(inputs))],
             header=["", ""], caption="Borehole details",
             col_widths_cm=[5.0, 10.0])
    rb.paragraph(phrase("fault_reports.placard_quote"), italic=True)
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
            f"{plural(state.undated_events, 'record')} "
            f"{'carries' if state.undated_events == 1 else 'carry'} a date that could not be "
            "read. They are listed below with the date as written, but they "
            "establish nothing about when anything last happened.")

    add_area_section(
        rb,
        SiteMetadata(community=asset.community, chiefdom=asset.chiefdom,
                     district=asset.district, easting=asset.easting,
                     northing=asset.northing, utm_zone=asset.utm_zone),
        inputs.figures_dir, config.style if config else None,
        heading="Where it is",
    )

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

    _sanitary_section(rb, asset, today, inputs.quality)

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
    rb.references(references_for("asset"))
    return rb.save(out_path)


def _sanitary_section(rb: ReportBuilder, asset: Asset, today: date, quality) -> None:
    """The sanitary risk statement, and the form it rests on as recorded."""
    risk = sanitary_risk(asset, today, quality)
    rb.heading(phrase("sanitary.heading"))
    rb.paragraph(risk["statement"])
    inspection = risk["inspection"]
    if inspection is not None:
        rb.table(form_rows(inspection["answers"], inspection["form"]),
                 header=[phrase("sanitary.col_number"), phrase("sanitary.col_question"),
                         phrase("sanitary.col_answer")],
                 caption=phrase("sanitary.form_caption", when=inspection["label"]),
                 col_widths_cm=[1.2, 11.0, 3.0])
    rb.paragraph(phrase("sanitary.basis"), italic=True)

"""Drilling supervision checklist report generator.

Turns the supervisor's checklist responses into a signed record: stage
by stage tables with each item's status and remark, the critical
failures up front, and the three party sign off block (supervisor,
driller, community representative) that RWSN supervision practice
expects.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config
from ..models import SiteMetadata
from ..photos import describe_provenance
from ..supervision.checklists import (
    ChecklistAssessment,
    ChecklistItem,
    ChecklistResponse,
    stage_title,
)
from ..supervision.field_checks import FieldCheck
from .citations import GLOSSARY, references_for
from .context import _figures_dir
from .docx_utils import ReportBuilder
from ..text import phrase
from .context import add_area_section

_STATUS_LABEL = {
    "yes": "Yes",
    "no": "NO",
    "na": "N/A",
    "pending": "-",
}


@dataclass
class SupervisionReportInputs:
    site: SiteMetadata
    items: list[ChecklistItem]
    responses: dict[str, ChecklistResponse]
    assessment: ChecklistAssessment
    supervisor: str = ""
    driller: str = ""
    community_rep: str = ""
    notes: list[str] = field(default_factory=list)
    #: Sand content, verticality, screen open area, specific capacity and the
    #: rest of :mod:`groundwater.supervision.field_checks`. A checklist says
    #: what was inspected; these say what was measured, and they are what the
    #: works are accepted or rejected against.
    field_checks: list[FieldCheck] = field(default_factory=list)
    #: Where the location map is written. A supervision record is a record
    #: of a place as much as of a checklist, so it carries one. Left unset,
    #: the figures go beside the document rather than into whatever
    #: directory the process happens to be running in.
    figures_dir: Path | None = None
    #: :class:`~groundwater.readiness.Readiness` for this report, from
    #: :func:`groundwater.readiness.assess_readiness`. When it is not
    #: certifiable the cover carries a PROVISIONAL stamp listing why.
    readiness: Any = None
    #: Photographs attached to checklist items, keyed by item id:
    #: ``{"name", "mime", "b64" or "bytes", "provenance"}``. Each is printed
    #: with where its time and position came from and its hash, and a
    #: photograph attached before provenance was recorded says so.
    evidence: dict = field(default_factory=dict)


def _photo_bytes(photo: dict) -> bytes | None:
    if photo.get("bytes") is not None:
        return bytes(photo["bytes"])
    try:
        return base64.b64decode(photo.get("b64") or "", validate=True) or None
    except (ValueError, TypeError):
        return None


def _evidence_section(rb: ReportBuilder, inputs: SupervisionReportInputs,
                      figures: Path, number: str) -> None:
    """The photographs attached to checklist items, with their provenance."""
    attached = [(item, inputs.evidence[item.item_id]) for item in inputs.items
                if isinstance(inputs.evidence.get(item.item_id), dict)]
    if not attached:
        return
    rb.heading(f"{number} Photographic Evidence", 2)
    rows = []
    for item, photo in attached:
        shown = describe_provenance(photo.get("provenance"))
        rows.append([item.text, str(photo.get("name") or ""), shown["time"],
                     shown["position"], shown["hash"]])
    rb.table(rows, header=["Item", "Photograph", "Taken", "Position", "Hash"],
             caption="Photographs attached to checklist items, with where "
                     "each time and position came from.",
             font_size_pt=8.0)
    if any((photo.get("provenance") or {}).get("stored") == "downscaled"
           for _, photo in attached):
        rb.paragraph(phrase("evidence.hash_downscaled"))
    rb.paragraph(phrase("evidence.presence_only"))
    for item, photo in attached:
        data = _photo_bytes(photo)
        if not data:
            continue
        suffix = ".png" if "png" in str(photo.get("mime") or "").lower() else ".jpg"
        path = figures / f"evidence_{item.item_id}{suffix}"
        path.write_bytes(data)
        try:
            rb.figure(path, item.text, width_cm=12)
        except Exception:  # noqa: BLE001 - an image Word cannot take is still listed above
            continue


def build_supervision_report(
    inputs: SupervisionReportInputs,
    out_path: str | Path,
    config: Config | None = None,
) -> Path:
    config = config or Config()
    site = inputs.site
    assessment = inputs.assessment

    rb = ReportBuilder(
        config.style,
        title=f"Supervision Checklist - {site.community or 'Borehole'}",
    )
    rb.cover(
        title_lines=["DRILLING SUPERVISION", "CHECKLIST RECORD"],
        subtitle_lines=[
            f"at {site.community}" + (f", {site.district} District" if site.district else "")
            if site.community
            else "Borehole Construction Supervision",
        ],
        details=[
            ("Client", site.client),
            ("Project", site.project),
            ("Contractor", site.contractor),
            ("Supervisor", inputs.supervisor or site.supervisor),
            ("Date", site.date),
        ],
    )
    rb.provisional_stamp(inputs.readiness)
    rb.table_of_contents()

    # ---- 1 summary -------------------------------------------------------
    rb.heading("1. Summary", 1)
    rb.paragraph(assessment.verdict, bold=True)
    rb.table(
        [
            [
                progress.title,
                f"{progress.answered}/{progress.total}",
                str(progress.failed),
                str(progress.critical_failed),
            ]
            for progress in assessment.stages
        ],
        header=["Stage", "Answered", "Failed", "Critical failed"],
        caption="Checklist progress by supervision stage.",
    )
    critical = [f for f in assessment.flags if f.code == "critical_item_failed"]
    if critical:
        rb.paragraph("Critical items that failed:", bold=True)
        rb.bullets([f"{f.context}: {f.message}" for f in critical])

    add_area_section(rb, site, _figures_dir(inputs.figures_dir, out_path),
                     config.style, heading="1.1 Location and setting")

    # ---- 2 checklists -----------------------------------------------------
    rb.heading("2. Checklist Record", 1)
    rb.paragraph(
        "The checklists follow the RWSN/UNICEF guidance for supervising "
        "water well drilling. Critical items are marked with an asterisk; "
        "a failed critical item stops acceptance of the works."
    )
    stage_keys: list[str] = []
    for item in inputs.items:
        if item.checklist not in stage_keys:
            stage_keys.append(item.checklist)
    for number, key in enumerate(stage_keys, start=1):
        stage_items = [i for i in inputs.items if i.checklist == key]
        rb.heading(f"2.{number} {stage_title(key)}", 2)
        rows = []
        for item in stage_items:
            response = inputs.responses.get(item.item_id)
            status = _STATUS_LABEL.get(
                response.status if response else "pending", "-"
            )
            remark = response.remark if response else ""
            marker = "*" if item.critical else ""
            rows.append([f"{item.text}{marker}", status, remark])
        rb.table(
            rows,
            header=["Item", "Status", "Remark"],
            caption=f"{stage_title(key)} checklist.",
        )

    # ---- 3 notes ----------------------------------------------------------
    has_evidence = any(isinstance(inputs.evidence.get(i.item_id), dict)
                       for i in inputs.items)
    if inputs.notes or inputs.field_checks or has_evidence:
        rb.heading("3. Site Record", 1)
    # numbered as they are printed, so a record with only photographs has a
    # 3.1 and not a 3.3 under a section with nothing before it
    subsection = iter(range(1, 4))
    if inputs.notes:
        rb.heading(f"3.{next(subsection)} Site Notes and Instructions", 2)
        rb.paragraph(
            "Site instructions are issued in writing and signed in "
            "duplicate by the supervisor and the driller."
        )
        rb.bullets(inputs.notes)

    # ---- field acceptance checks -------------------------------------------
    if inputs.field_checks:
        rb.heading(f"3.{next(subsection)} Field Acceptance Checks", 2)
        rb.paragraph(
            "Measured against the acceptance limits in the RWSN and UNICEF "
            "supervision guidance. A failed check is a defect the contractor "
            "is required to make good before the works are accepted.",
            align="justify",
        )
        rb.table(
            [[c.name, c.measured, c.limit, c.status.upper(), c.message]
             for c in inputs.field_checks],
            header=["Check", "Measured", "Acceptance limit", "Result", "Note"],
            caption="Field acceptance checks.",
        )

    # ---- photographic evidence ---------------------------------------------
    _evidence_section(rb, inputs, _figures_dir(inputs.figures_dir, out_path),
                      f"3.{next(subsection)}")

    # ---- signatures --------------------------------------------------------
    rb.heading("4. Sign Off", 1)
    rb.paragraph(
        "The undersigned confirm that the checklist record above reflects "
        "the works as inspected."
    )
    for role, name in (
        ("Supervisor", inputs.supervisor or site.supervisor),
        ("For the driller", inputs.driller or site.contractor),
        ("For the community", inputs.community_rep),
    ):
        rb.paragraph("")
        rb.paragraph("." * 30)
        rb.paragraph(f"{role}: {name}", bold=True)
        rb.paragraph("Date: ........................")

    rb.references(references_for("supervision"))
    rb.glossary(GLOSSARY)

    return rb.save(out_path)

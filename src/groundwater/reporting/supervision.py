"""Drilling supervision checklist report generator.

Turns the supervisor's checklist responses into a signed record: stage
by stage tables with each item's status and remark, the critical
failures up front, and the three party sign off block (supervisor,
driller, community representative) that RWSN supervision practice
expects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..models import SiteMetadata
from ..supervision.checklists import (
    ChecklistAssessment,
    ChecklistItem,
    ChecklistResponse,
    stage_title,
)
from .docx_utils import ReportBuilder

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
    if inputs.notes:
        rb.heading("3. Site Notes and Instructions", 1)
        rb.paragraph(
            "Site instructions are issued in writing and signed in "
            "duplicate by the supervisor and the driller."
        )
        rb.bullets(inputs.notes)

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

    return rb.save(out_path)

"""Project handover report generator.

The closing deliverable for the client, NGO or government partner: a
project summary, the works completed, the borehole data sheet with all
key results, the as-built design drawing, the water quality verdict,
operation and maintenance guidance, the community/WASH committee
details, recommendations and the handover signature blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..design.designer import BoreholeDesign
from ..design.drawing import draw_borehole_design
from ..hydraulics.analysis import PumpingTestAnalysis
from ..models import DrillingLog, SiteMetadata
from ..quality.assess import WaterQualityAssessment
from ..utils import fmt_num
from .docx_utils import ReportBuilder

_OM_GUIDANCE = [
    (
        "Daily",
        [
            "Keep the apron and surroundings clean; no washing or animal "
            "watering on the apron.",
            "Check for leaks, unusual pump noise and discoloured water.",
            "Keep the drainage channel and soakaway free flowing.",
        ],
    ),
    (
        "Weekly",
        [
            "Tighten loose bolts on the pump head and inspect the apron for cracks.",
            "Record the approximate hours of use or strokes per day.",
        ],
    ),
    (
        "Monthly",
        [
            "Measure and record the water level where a dip access exists.",
            "Collect the agreed user fees and update the cash book.",
            "Inspect the fence and the sanitary protection zone (no pit "
            "latrine, refuse pit or animal pen within 30 m).",
        ],
    ),
    (
        "Yearly",
        [
            "Service the pump according to the manufacturer schedule and "
            "replace fast wearing parts.",
            "Repeat the physico-chemical and bacteriological water tests.",
            "Review the tariff against the cost of spare parts.",
        ],
    ),
]


@dataclass
class CommitteeMember:
    role: str
    name: str
    phone: str = ""


@dataclass
class HandoverReportInputs:
    site: SiteMetadata
    log: DrillingLog | None = None
    design: BoreholeDesign | None = None
    pumping: PumpingTestAnalysis | None = None
    quality: WaterQualityAssessment | None = None
    figures_dir: Path = Path(".")
    works_completed: list[str] = field(default_factory=list)
    committee: list[CommitteeMember] = field(default_factory=list)
    committee_notes: str = ""
    tariff_note: str = ""
    pump_type: str = ""
    extra_recommendations: list[str] = field(default_factory=list)
    contractor_rep: str = ""
    client_rep: str = ""
    community_rep: str = ""


def build_handover_report(
    inputs: HandoverReportInputs,
    out_path: str | Path,
    config: Config | None = None,
) -> Path:
    config = config or Config()
    site = inputs.site
    figures = Path(inputs.figures_dir)
    figures.mkdir(parents=True, exist_ok=True)

    rb = ReportBuilder(config.style, title=f"Handover Report - {site.community}")
    rb.cover(
        title_lines=["PROJECT HANDOVER REPORT"],
        subtitle_lines=[
            "Borehole Water Supply",
            f"at {site.community}" + (f", {site.district} District" if site.district else ""),
        ],
        details=[
            ("Client", site.client),
            ("Project", site.project),
            ("Contractor", site.contractor),
            ("Date", site.date),
        ],
    )
    rb.table_of_contents()

    # ---- 1 project summary ----------------------------------------------------
    rb.heading("1. Project Summary", 1)
    lat_lon = site.latlon
    rb.header_block_table(
        [
            ("Community", site.community), ("Chiefdom", site.chiefdom),
            ("District", site.district), ("Client", site.client),
            ("Contractor", site.contractor), ("Project reference", site.project_ref),
            ("GPS East", fmt_num(site.easting, 7) if site.easting else ""),
            ("GPS North", fmt_num(site.northing, 7) if site.northing else ""),
            ("Latitude / Longitude",
             f"{lat_lon[0]:.5f} N, {abs(lat_lon[1]):.5f} W" if lat_lon else ""),
            ("Elevation", fmt_num(site.elevation_m) + " m" if site.elevation_m else ""),
        ]
    )

    # ---- 2 works completed ---------------------------------------------------------
    rb.heading("2. Works Completed", 1)
    works = inputs.works_completed or _default_works(inputs)
    rb.bullets(works)

    # ---- 3 borehole data sheet ---------------------------------------------------
    rb.heading("3. Borehole Data Sheet", 1)
    rows: list[list[str]] = []
    log = inputs.log
    if log is not None:
        rows += [
            ["Borehole reference", log.borehole_ref],
            ["Total depth", fmt_num(log.total_depth_m) + " m"],
            ["Drilling method", log.drilling_method],
            ["Water strikes", ", ".join(f"{w:g} m" for w in log.water_strikes_m) or "n/a"],
            ["Completion date", log.completion_date],
            ["Status", log.status],
        ]
    if inputs.design is not None:
        rows += [[k, v] for k, v in inputs.design.summary_rows()]
    analysis = inputs.pumping
    if analysis is not None:
        if analysis.transmissivity_m2_per_day:
            rows.append(["Transmissivity", fmt_num(analysis.transmissivity_m2_per_day) + " m2/day"])
        yr = analysis.yield_recommendation
        if yr is not None:
            if yr.safe_yield_m3_per_h:
                rows.append([
                    f"Safe yield (safety factor {yr.safety_factor:g})",
                    fmt_num(yr.safe_yield_m3_per_h) + " m3/h",
                ])
            if yr.pump_installation_depth_m:
                rows.append(["Pump installation depth", fmt_num(yr.pump_installation_depth_m) + " m"])
    if inputs.pump_type:
        rows.append(["Pump type", inputs.pump_type])
    rb.table(rows, header=["Item", "Value"], caption="Key borehole data.")

    if inputs.design is not None:
        design_fig = figures / "borehole_design.png"
        if not design_fig.exists():
            draw_borehole_design(
                inputs.design, log, path=design_fig, style=config.style,
                title=f"Borehole design - {site.community}",
            )
        rb.figure(design_fig, "As-built borehole diagram.", width_cm=13.0)

    # ---- 4 water quality ------------------------------------------------------------
    rb.heading("4. Water Quality", 1)
    if inputs.quality is not None:
        rb.paragraph(inputs.quality.verdict, align="justify")
        exceed = inputs.quality.health_exceedances + inputs.quality.aesthetic_exceedances
        if exceed:
            rb.table(
                [[r.parameter, fmt_num(r.value), r.unit, r.remark] for r in exceed],
                header=["Parameter", "Value", "Unit", "Remark"],
                caption="Parameters above guideline or standard limits.",
            )
    else:
        rb.paragraph("Water quality results are reported separately.")

    # ---- 5 O&M -------------------------------------------------------------------------
    rb.heading("5. Operation and Maintenance Guidance", 1)
    rb.paragraph(
        "The lifetime of the borehole depends on routine care. The tasks "
        "below follow standard rural water supply practice; the community "
        "should keep a logbook of all maintenance, breakdowns and payments.",
        align="justify",
    )
    for period, tasks in _OM_GUIDANCE:
        rb.paragraph(period, bold=True)
        rb.bullets(tasks)
    yr = analysis.yield_recommendation if analysis else None
    if yr is not None and yr.safe_yield_m3_per_h:
        rb.paragraph(
            f"Operate the pump at no more than {fmt_num(yr.safe_yield_m3_per_h)} "
            "m3/h and allow the recommended rest periods. If the water level "
            "reaches the pump intake, stop pumping and let the borehole recover.",
            bold=True,
        )
    if inputs.tariff_note:
        rb.paragraph(f"Tariff arrangement: {inputs.tariff_note}")

    # ---- 6 committee -----------------------------------------------------------------
    rb.heading("6. Community / WASH Committee", 1)
    if inputs.committee:
        rb.table(
            [[m.role, m.name, m.phone] for m in inputs.committee],
            header=["Role", "Name", "Phone"],
            caption="WASH committee members responsible for the water point.",
        )
    else:
        rb.paragraph(
            "The WASH committee membership should be recorded here (chair, "
            "secretary, treasurer, caretakers) with contact numbers."
        )
    if inputs.committee_notes:
        rb.paragraph(inputs.committee_notes, align="justify")

    # ---- 7 recommendations -----------------------------------------------------------
    rb.heading("7. Recommendations", 1)
    recs = [
        "Protect the wellhead: keep the 30 m sanitary zone free of latrines, "
        "refuse pits and animal pens.",
        "Keep this report and the borehole data sheet with the committee "
        "records; any future contractor will need them.",
        "Report persistent taste, odour or discolouration to the district "
        "water office and arrange a water quality test.",
    ]
    if inputs.quality is not None and inputs.quality.health_exceedances:
        recs.insert(
            0,
            "Implement the treatment measures in the water quality report "
            "before the water is used for drinking.",
        )
    recs.extend(inputs.extra_recommendations)
    rb.bullets(recs)

    # ---- signatures ----------------------------------------------------------------------
    rb.heading("8. Handover Signatures", 1)
    rb.paragraph(
        "The works described above are handed over to the client and the "
        "community in working condition."
    )
    for role, name in (
        ("For the contractor", inputs.contractor_rep or site.contractor),
        ("For the client", inputs.client_rep or site.client),
        ("For the community / WASH committee", inputs.community_rep),
    ):
        rb.paragraph("")
        rb.paragraph("." * 30)
        rb.paragraph(f"{role}: {name}", bold=True)
        rb.paragraph("Date: ........................")

    return rb.save(out_path)


def _default_works(inputs: HandoverReportInputs) -> list[str]:
    works = ["Geophysical siting survey and borehole location selection."]
    if inputs.log is not None:
        works.append(
            f"Drilling of the borehole to {fmt_num(inputs.log.total_depth_m)} m"
            + (f" by {inputs.log.drilling_method}" if inputs.log.drilling_method else "")
            + "."
        )
    if inputs.design is not None:
        works.append(
            "Construction with "
            f"{inputs.design.casing_diameter_in:g} inch {inputs.design.casing_material} "
            "casing and screens, gravel pack and sanitary seal."
        )
    works += [
        "Development of the borehole by air lifting until clear.",
        "Pumping test and yield assessment.",
        "Water quality sampling and laboratory analysis.",
        "Wellhead completion with apron and drainage.",
    ]
    return works

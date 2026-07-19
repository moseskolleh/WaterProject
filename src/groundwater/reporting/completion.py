"""Borehole completion report generator.

Follows the structure of the contractor completion report example:
introduction, methodology, drilling works, borehole log data with the
drilling record table, borehole construction and design drawing,
development record, pumping test summary, borehole characteristics and
installation block, recommendations and conclusions, and the preparer
signature block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..design.designer import BoreholeDesign
from ..design.drawing import draw_borehole_design
from ..hydraulics.analysis import PumpingTestAnalysis
from ..hydraulics.plots import plot_test_overview
from ..models import DrillingLog
from ..quality.assess import WaterQualityAssessment
from ..utils import fmt_num
from .citations import GLOSSARY, references_for
from .docx_utils import ReportBuilder


@dataclass
class CompletionReportInputs:
    log: DrillingLog
    design: BoreholeDesign | None = None
    pumping: PumpingTestAnalysis | None = None
    quality: WaterQualityAssessment | None = None
    figures_dir: Path = Path(".")
    development_record: list[tuple[str, str, str, str]] = field(default_factory=list)
    # rows of (from time, to time, estimated yield, observation)
    development_note: str = ""
    pump_type: str = ""
    preparer_name: str = ""
    preparer_role: str = "Technical Manager"
    preparer_phone: str = ""


def _executive_summary(inputs: CompletionReportInputs) -> tuple[list[str], list[str]]:
    """Compose the completion executive summary from the drilling and test data."""
    log = inputs.log
    community = log.site.community or "the site"
    analysis = inputs.pumping
    yr = analysis.yield_recommendation if analysis else None
    quality = inputs.quality
    status = (log.status or "").strip()

    bits = [
        "This report documents the drilling, construction and testing of the "
        f"borehole at {community}."
    ]
    if log.total_depth_m:
        s = f"The borehole was drilled to {fmt_num(log.total_depth_m)} m"
        if log.drilling_method:
            s += f" by {log.drilling_method}"
        if status:
            s += f" and is recorded as {status.lower()}"
        bits.append(s + ".")
    if yr is not None and yr.safe_yield_m3_per_h:
        bits.append(
            f"The recommended safe yield is {fmt_num(yr.safe_yield_m3_per_h)} m3/h "
            f"at a pump setting of {fmt_num(yr.pump_installation_depth_m)} m."
        )
    elif analysis is not None and not analysis.test.has_discharge:
        bits.append(
            "The pumping test discharge is pending, so the yield figures are not "
            "yet final."
        )
    if quality is not None:
        bits.append(
            "The water requires treatment before drinking."
            if quality.health_exceedances
            else "The water is suitable for drinking on the parameters tested."
        )

    key: list[str] = []
    if log.total_depth_m:
        key.append(
            f"Borehole depth: {fmt_num(log.total_depth_m)} m"
            + (f", {status}." if status else ".")
        )
    if yr is not None and yr.safe_yield_m3_per_h:
        key.append(f"Safe yield: {fmt_num(yr.safe_yield_m3_per_h)} m3/h.")
    if quality is not None:
        key.append(
            "Water safety: "
            + (
                "treatment required before drinking."
                if quality.health_exceedances
                else "suitable on the parameters tested."
            )
        )
    return [" ".join(bits)], key


def build_completion_report(
    inputs: CompletionReportInputs,
    out_path: str | Path,
    config: Config | None = None,
) -> Path:
    config = config or Config()
    log = inputs.log
    site = log.site
    figures = Path(inputs.figures_dir)
    figures.mkdir(parents=True, exist_ok=True)

    rb = ReportBuilder(
        config.style, title=f"Borehole Completion Report - {site.community}"
    )
    rb.cover(
        title_lines=["BOREHOLE DRILLING AND", "PUMP TEST REPORT"],
        subtitle_lines=[f"for {site.community}"],
        details=[
            ("Submitted to", site.client),
            ("Contractor", site.contractor or ""),
            ("Borehole Ref. No.", log.borehole_ref or ""),
            ("Completion date", log.completion_date or ""),
            ("Status", log.status or ""),
        ],
    )
    rb.table_of_contents()

    # ---- executive summary ---------------------------------------------------
    exec_paras, exec_key = _executive_summary(inputs)
    rb.executive_summary(exec_paras, exec_key)

    # ---- introduction --------------------------------------------------------
    rb.heading("1. Introduction", 1)
    rb.paragraph(
        "Groundwater can be abstracted from the ground in different ways, and "
        "the choice of abstraction method depends on the resources available "
        "and the local conditions. Borehole drilling was the recommended "
        f"abstraction method for this project at {site.community}, and the "
        "work was executed as per the specifications. Details of the "
        "activities are presented in this report.",
        align="justify",
    )

    # ---- methodology -----------------------------------------------------------
    rb.heading("2. Methodology", 1)
    rb.paragraph(
        "The methodology adopted included reconnaissance, observation of the "
        "geological and hydrogeological conditions, assessment of existing "
        "boreholes and hand dug wells, drilling, construction, development "
        "and test pumping of the borehole.",
        align="justify",
    )

    # ---- drilling ---------------------------------------------------------------
    rb.heading("3. Drilling", 1)
    rb.paragraph("The drilling work included the following:")
    rb.bullets(
        [
            "Mobilisation of the drill rig and all necessary equipment.",
            "Drilling through all formations for completion of the borehole"
            + (f" using the {log.drilling_method} method." if log.drilling_method else "."),
            "Supply and installation of casings (plain and screen).",
            "Gravel packing of the annulus.",
            "Development of the borehole by surging with compressed air and airlifting.",
            "Demobilisation.",
        ]
    )
    rb.header_block_table(
        [
            ("Contractor", site.contractor or ""), ("Client", site.client),
            ("Location", site.community), ("Depth of borehole", fmt_num(log.total_depth_m) + " m"),
            ("Start date", log.start_date), ("Completion date", log.completion_date),
            ("Drilling method", log.drilling_method), ("BH status", log.status),
        ]
    )

    # ---- borehole log -------------------------------------------------------------
    rb.heading("4. Borehole Log Data", 1)
    rows = []
    for iv in log.intervals:
        rows.append(
            [
                f"{iv.top_m:g}-{iv.bottom_m:g}",
                fmt_num(iv.thickness_m),
                iv.from_time,
                iv.to_time,
                fmt_num(iv.penetration_rate_m_per_min) if iv.penetration_rate_m_per_min else "",
                iv.description,
                f'{iv.bit_diameter_in:g}"' if iv.bit_diameter_in else "",
            ]
        )
    rb.table(
        rows,
        header=["Depth (m)", "Interval (m)", "From", "To",
                "Penetration rate (m/min)", "Sample description", "Diameter"],
        caption="Drilling record and formation log.",
        font_size_pt=8.5,
    )
    strikes = log.water_strikes_m
    if strikes:
        for i, strike in enumerate(strikes, start=1):
            label = ["First", "Second", "Third", "Fourth"][i - 1] if i <= 4 else f"{i}th"
            rb.paragraph(f"{label} water strike: {strike:g} m", bold=True)
    if log.grouting_depth_m:
        rb.paragraph(f"Grouting: {log.grouting_depth_m:g} m", bold=True)

    # ---- construction / design ---------------------------------------------------
    if inputs.design is not None:
        rb.heading("5. Borehole Construction", 1)
        design_fig = figures / "borehole_design.png"
        if not design_fig.exists():
            draw_borehole_design(
                inputs.design, log, path=design_fig, style=config.style,
                title=f"Borehole design - {site.community} ({log.borehole_ref})",
                header_pairs=[
                    ("Client", site.client), ("Contractor", site.contractor or ""),
                    ("Method", log.drilling_method), ("Status", log.status),
                ],
            )
        rb.table(
            [[k, v] for k, v in inputs.design.summary_rows()],
            header=["Item", "Detail"],
            caption="Construction summary.",
        )
        rb.figure(design_fig, "As-built borehole design with lithology and construction columns.", width_cm=13.5)
        if inputs.design.design_basis:
            rb.paragraph("Design basis:", bold=True)
            rb.bullets(inputs.design.design_basis)

    # ---- development ---------------------------------------------------------------
    section = 6 if inputs.design is not None else 5
    if inputs.development_record or inputs.development_note:
        rb.heading(f"{section}. Borehole Development Record", 1)
        if inputs.development_note:
            rb.paragraph(inputs.development_note)
        if inputs.development_record:
            rb.table(
                [list(r) for r in inputs.development_record],
                header=["From", "To", "Estimated yield (m3/h)", "Observation"],
                caption="Borehole development by air lifting.",
            )
        section += 1

    # ---- pumping test ---------------------------------------------------------------
    if inputs.pumping is not None:
        analysis = inputs.pumping
        test = analysis.test
        rb.heading(f"{section}. Pumping Test", 1)
        overview = figures / "test_overview.png"
        if not overview.exists():
            plot_test_overview(test, path=overview, style=config.style)
        rb.figure(overview, "Constant discharge test and recovery record.")
        q = test.steps[0].discharge_m3_per_h if test.steps else None
        rows = [
            ["Test type", test.test_type],
            ["Duration", fmt_num(test.pumping_duration_min) + " min" if test.pumping_duration_min else ""],
            ["Discharge", fmt_num(q) + " m3/h" if q else "pending"],
            ["Static water level", fmt_num(test.static_water_level_m) + " m"],
            ["Maximum drawdown", fmt_num(analysis.max_drawdown_m) + " m" if analysis.max_drawdown_m else ""],
        ]
        if analysis.transmissivity_m2_per_day:
            rows.append(["Transmissivity", fmt_num(analysis.transmissivity_m2_per_day) + " m2/day"])
        yr = analysis.yield_recommendation
        if yr and yr.specific_capacity_m3hr_per_m:
            rows.append(["Specific capacity", fmt_num(yr.specific_capacity_m3hr_per_m) + " m3/h per m"])
        rb.table(rows, header=["Item", "Value"], caption="Pumping test summary.")
        section += 1

    # ---- characteristics and installation ------------------------------------------
    rb.heading(f"{section}. Borehole Characteristics and Installation", 1)
    swl = inputs.pumping.test.static_water_level_m if inputs.pumping else None
    dwl = None
    if inputs.pumping and inputs.pumping.test.steps and swl is not None:
        dwl = float(inputs.pumping.test.steps[-1].water_level_m[-1])
    q = None
    if inputs.pumping and inputs.pumping.test.steps:
        q = inputs.pumping.test.steps[0].discharge_m3_per_h
    yr = inputs.pumping.yield_recommendation if inputs.pumping else None
    pairs = [
        ("Borehole depth", fmt_num(log.total_depth_m) + " m"),
        ("Borehole diameter", f'{inputs.design.borehole_diameter_in:g}"' if inputs.design else ""),
        ("Static water level", fmt_num(swl) + " m" if swl is not None else ""),
        ("Dynamic water level", fmt_num(dwl) + " m" if dwl is not None else ""),
        ("Drawdown", fmt_num(dwl - swl) + " m" if (dwl is not None and swl is not None) else ""),
        ("Flow rate", fmt_num(q * 1000) + " L/h" if q else "pending"),
        ("Pump type", inputs.pump_type),
        ("Installation depth", fmt_num(yr.pump_installation_depth_m) + " m" if yr and yr.pump_installation_depth_m else
         (fmt_num(inputs.pumping.test.pump_setting_m) + " m" if inputs.pumping and inputs.pumping.test.pump_setting_m else "")),
    ]
    rb.header_block_table(pairs)
    section += 1

    # ---- water quality (optional) ---------------------------------------------------
    if inputs.quality is not None:
        rb.heading(f"{section}. Water Quality Summary", 1)
        rb.paragraph(inputs.quality.verdict, align="justify")
        exceed = inputs.quality.health_exceedances + inputs.quality.aesthetic_exceedances
        if exceed:
            rb.table(
                [[r.parameter, fmt_num(r.value), r.unit, r.who_health or r.who_aesthetic or r.sl_standard, r.remark]
                 for r in exceed],
                header=["Parameter", "Value", "Unit", "Limit", "Remark"],
                caption="Parameters above guideline or standard limits.",
            )
        section += 1

    # ---- recommendations ----------------------------------------------------------
    rb.heading(f"{section}. Recommendations and Conclusions", 1)
    bullets = []
    if (log.status or "").lower().startswith("success") or (
        inputs.pumping and inputs.pumping.yield_recommendation
        and inputs.pumping.yield_recommendation.safe_yield_m3_per_h
    ):
        bullets.append("The borehole is successful and sustainable when operated as recommended.")
    yr = inputs.pumping.yield_recommendation if inputs.pumping else None
    if yr and yr.safe_yield_m3_per_h:
        bullets.append(
            f"The recommended abstraction rate is {fmt_num(yr.safe_yield_m3_per_h)} m3/h "
            f"(safety factor {yr.safety_factor:g} applied to the long term yield)."
        )
        if yr.pump_installation_depth_m:
            bullets.append(
                f"The pump installation depth is {fmt_num(yr.pump_installation_depth_m)} m."
            )
        bullets.append(
            "The pump should rest for at least one hour in every pumping "
            "cycle and the pumping water level should be checked routinely."
        )
    elif inputs.pumping is not None and not inputs.pumping.test.has_discharge:
        bullets.append(
            "The pumping test discharge must be supplied so the yield "
            "recommendation can be completed; abstraction figures remain pending."
        )
    if inputs.quality is not None and inputs.quality.health_exceedances:
        bullets.append(
            "Water treatment is required before drinking; see the water "
            "quality assessment."
        )
    else:
        bullets.append(
            "Physico-chemical and bacteriological testing should be repeated "
            "at least once a year."
        )
    rb.bullets(bullets)

    # ---- references and glossary -----------------------------------------------
    rb.references(references_for("completion"))
    rb.glossary(GLOSSARY)

    rb.signature_block(
        name=inputs.preparer_name or site.supervisor,
        role=inputs.preparer_role,
        phone=inputs.preparer_phone,
        organisation=site.contractor or config.style.organisation,
    )
    return rb.save(out_path)

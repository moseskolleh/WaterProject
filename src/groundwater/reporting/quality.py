"""Water quality report generator.

Presents the laboratory results against WHO guideline values and the
national standard, flags every exceedance clearly (bold red status),
reports the ionic balance check and, where the major ions are
available, the Piper and Stiff diagrams, and closes with treatment
recommendations matched to the exceedances found.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx.shared import Pt, RGBColor

from ..config import Config
from ..quality.assess import WaterQualityAssessment
from ..quality.diagrams import plot_piper, plot_stiff
from ..utils import fmt_num
from .docx_utils import ReportBuilder

_STATUS_LABEL = {
    "within_limits": "Complies",
    "exceeds_health": "EXCEEDS HEALTH GUIDELINE",
    "exceeds_national": "Exceeds national/adopted limit",
    "exceeds_aesthetic": "Exceeds acceptability value",
    "below_detection": "Below detection",
    "no_guideline": "No guideline value",
    "not_measured": "Not measured",
}

_TREATMENT_ADVICE = {
    "iron": "Iron above the acceptability value causes staining and metallic "
    "taste; aeration followed by sand filtration or a simple oxidation "
    "filter normally resolves it.",
    "manganese": "Manganese requires oxidation and filtration (aeration or "
    "chlorination followed by filtration); monitor infant exposure in the "
    "meantime.",
    "e. coli": "Any E. coli detection calls for shock chlorination of the "
    "borehole, verification of the sanitary seal and apron, and re-sampling "
    "before use.",
    "total coliforms": "Coliform detection calls for disinfection of the "
    "borehole and pump, a sanitary inspection of the wellhead, and re-sampling.",
    "nitrate (as no3)": "Elevated nitrate usually indicates pollution from "
    "sanitation or agriculture; investigate the sanitary protection zone. Do "
    "not give the water to bottle fed infants until resolved.",
    "fluoride": "Fluoride above 1.5 mg/L requires an alternative source or "
    "defluoridation (bone char or activated alumina).",
    "arsenic": "Arsenic above 0.01 mg/L requires an alternative source or "
    "specialised removal; re-test to confirm before any use for drinking.",
    "ph": "Low pH water is corrosive to metal fittings; a limestone contactor "
    "or careful choice of corrosion resistant materials is advised.",
    "turbidity": "High turbidity interferes with disinfection; extend "
    "development of the borehole and re-sample.",
}


@dataclass
class QualityReportInputs:
    assessment: WaterQualityAssessment
    figures_dir: Path
    analyst_name: str = ""
    analyst_role: str = "Water Quality Analyst"
    analyst_phone: str = ""
    include_diagrams: bool = True


def build_quality_report(
    inputs: QualityReportInputs,
    out_path: str | Path,
    config: Config | None = None,
) -> Path:
    config = config or Config()
    assessment = inputs.assessment
    sample = assessment.sample
    site = sample.site
    figures = Path(inputs.figures_dir)
    figures.mkdir(parents=True, exist_ok=True)

    rb = ReportBuilder(config.style, title=f"Water Quality Report - {site.community}")
    rb.cover(
        title_lines=["WATER QUALITY REPORT"],
        subtitle_lines=[
            f"Borehole water assessment at {site.community}"
            + (f", {site.district} District" if site.district else ""),
        ],
        details=[
            ("Client", site.client),
            ("Sample ID", sample.sample_id),
            ("Borehole", sample.borehole_ref),
            ("Sample date", sample.sample_date),
            ("Laboratory", sample.laboratory),
        ],
    )

    # ---- 1 sample details -------------------------------------------------
    rb.heading("1. Sample Details", 1)
    rb.header_block_table(
        [
            ("Community", site.community), ("Client", site.client),
            ("Sample ID", sample.sample_id), ("Borehole Ref. No.", sample.borehole_ref),
            ("Sample date", sample.sample_date), ("Laboratory", sample.laboratory),
            ("District", site.district), ("Project", site.project),
        ]
    )
    rb.paragraph(
        "Results are compared against the WHO Guidelines for Drinking-water "
        "Quality (fourth edition with addenda) and the national standard "
        "limits configured for this project. Where a confirmed national "
        "value is not available, the WHO or regional figure is adopted for "
        "that parameter and the status column reads national/adopted limit. "
        "Values reported by the laboratory as below the detection limit are "
        "shown as such.",
        align="justify",
    )

    # ---- 2 results table ------------------------------------------------------
    rb.heading("2. Results Against Guideline Values", 1)
    table_no = rb.next_table_number
    rb.paragraph(
        f"Table {table_no} lists every parameter tested. Exceedances are "
        "highlighted in the status column."
    )
    header = ["Parameter", "Value", "Unit", "WHO health", "WHO acceptability",
              "National", "Status"]
    rows = []
    highlight = []
    for r in assessment.rows:
        value = "< DL" if (r.below_detection and r.value is None) else fmt_num(r.value)
        rows.append([
            r.parameter, value, r.unit, r.who_health, r.who_aesthetic,
            r.sl_standard, _STATUS_LABEL.get(r.status, r.status),
        ])
        highlight.append(r.status in ("exceeds_health", "exceeds_national", "exceeds_aesthetic"))
    rb.table(rows, header=header, caption="Laboratory results against guideline values.",
             font_size_pt=8.5)
    # bold red status text on exceedance rows
    table = rb.doc.tables[-1]
    for i, is_exceed in enumerate(highlight):
        if not is_exceed:
            continue
        cell = table.rows[i + 1].cells[len(header) - 1]
        for para in cell.paragraphs:
            for run in para.runs:
                run.font.bold = True
                run.font.color.rgb = RGBColor(0xB0, 0x00, 0x00)

    rb.paragraph(assessment.verdict, bold=True, align="justify")

    # ---- 3 ionic balance ---------------------------------------------------------
    rb.heading("3. Ionic Balance Check", 1)
    ionic = assessment.ionic
    if ionic is None:
        rb.paragraph(
            "The major ion analysis is incomplete, so no ionic balance check "
            "is possible for this sample."
        )
    else:
        note = (
            " Bicarbonate was estimated from total alkalinity."
            if ionic.used_alkalinity_for_bicarbonate
            else ""
        )
        rb.paragraph(
            f"Sum of cations {fmt_num(ionic.sum_cations_meq, 3)} meq/L, sum of "
            f"anions {fmt_num(ionic.sum_anions_meq, 3)} meq/L, charge balance "
            f"error {ionic.error_percent:+.1f} percent.{note} "
            + (
                "The analysis balances within the normal 5 percent tolerance."
                if abs(ionic.error_percent) <= 5
                else "The balance error exceeds 5 percent; the laboratory "
                "analysis should be reviewed."
            ),
            align="justify",
        )

    # ---- 4 diagrams ----------------------------------------------------------------
    if inputs.include_diagrams and ionic is not None:
        rb.heading("4. Hydrochemical Facies", 1)
        piper_path = figures / "piper.png"
        stiff_path = figures / "stiff.png"
        if not piper_path.exists():
            plot_piper([sample], path=piper_path, style=config.style)
        if not stiff_path.exists():
            plot_stiff(sample, path=stiff_path, style=config.style)
        rb.figure(piper_path, "Piper diagram.", width_cm=13.0)
        rb.figure(stiff_path, "Stiff diagram.", width_cm=11.0)

    # ---- 5 recommendations -----------------------------------------------------------
    rb.heading("5. Recommendations", 1)
    advice = []
    for r in assessment.health_exceedances + assessment.aesthetic_exceedances:
        key = r.parameter.strip().lower()
        for match, text in _TREATMENT_ADVICE.items():
            if match in key:
                advice.append(text)
                break
    if not advice:
        advice.append(
            "No treatment is required on the basis of the parameters tested. "
            "Maintain the sanitary seal and apron in good condition."
        )
    advice.append(
        "Repeat physico-chemical and bacteriological testing at least once a "
        "year, and after any flooding or repair work on the wellhead."
    )
    rb.bullets(advice)

    rb.signature_block(
        name=inputs.analyst_name,
        role=inputs.analyst_role,
        phone=inputs.analyst_phone,
        organisation=config.style.organisation,
    )
    return rb.save(out_path)

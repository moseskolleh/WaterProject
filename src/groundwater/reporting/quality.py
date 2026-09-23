"""Water quality report generator.

Presents the laboratory results against WHO guideline values and the
national standard, flags every exceedance clearly (bold red status),
reports the ionic balance check and, where the major ions are
available, the Piper and Stiff diagrams, and closes with treatment
recommendations matched to the exceedances found.
"""

from __future__ import annotations

from typing import Any

from dataclasses import dataclass
from pathlib import Path

from docx.shared import RGBColor

from ..config import Config
from ..quality.assess import STATUS_LABELS, WaterQualityAssessment, unquantified_text
from ..quality.diagrams import facies_of, plot_piper, plot_stiff
from ..quality.standards import (
    PROVISIONAL_NATIONAL_NOTE,
    faecal_pathogen,
    normalise_parameter,
)
from ..utils import fmt_num, safe_slug, plural_noun
from .citations import GLOSSARY, references_for
from .docx_utils import ReportBuilder
from .context import add_area_section

#: The wording lives with the assessment so every surface prints the same
#: label and a new status can never leak out as a raw code.
_STATUS_LABEL = STATUS_LABELS

def _sentence(text: str) -> str:
    """Upper-case the first letter only.

    str.capitalize() lower-cases everything after it, which turns "E. coli"
    into "e. coli" and "Total petroleum hydrocarbons" into a lower-case
    determinand halfway through a client-facing sentence.
    """
    return text[:1].upper() + text[1:] if text else text


#: Advice for a parameter over its limit, keyed by the standards-table name.
#: It used to be matched by substring on the name as written, so "Sulphate"
#: got the pH advice for containing "ph", and "Faecal coliforms" and lead got
#: nothing, which left "No treatment is required" under a verdict of
#: "Treat before use". The browser's recommendations are the same list
#: (gwt-docx.js qualityRecommendations).
_NITRATE_ADVICE = (
    "Elevated nitrate usually indicates pollution from sanitation or "
    "agriculture; investigate the sanitary protection zone. Do not give the "
    "water to bottle fed infants until resolved."
)
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
    "nitrate (as no3)": _NITRATE_ADVICE,
    "nitrate (as n)": _NITRATE_ADVICE,
    "nitrate + nitrite": _NITRATE_ADVICE,
    "fluoride": "Fluoride above 1.5 mg/L requires an alternative source or "
    "defluoridation (bone char or activated alumina).",
    "arsenic": "Arsenic above 0.01 mg/L requires an alternative source or "
    "specialised removal; re-test to confirm before any use for drinking.",
    "turbidity": "High turbidity interferes with disinfection; extend "
    "development of the borehole and re-sample.",
}

#: For a faecal pathogen found in the water, which has no table entry to key
#: advice by and used to get none under "Treat before use".
_PATHOGEN_ADVICE = (
    "A faecal pathogen in the water calls for shock chlorination of the "
    "borehole, a sanitary inspection to find where the contamination enters, "
    "and re-sampling for the pathogen and for E. coli before the supply is "
    "used for drinking."
)

#: pH is out of range in one of two directions, and the advice for each is
#: different: the low-pH advice used to be given for a pH of 9.2.
_PH_ADVICE_LOW = (
    "Low pH water is corrosive to metal fittings; a limestone contactor or "
    "careful choice of corrosion resistant materials is advised."
)
_PH_ADVICE_HIGH = (
    "A pH above the acceptability range reduces the effectiveness of chlorine "
    "disinfection and can give the water a bitter taste and deposit scale; "
    "confirm the reading and set any chlorine dose to suit."
)


def quality_recommendations(assessment: WaterQualityAssessment) -> list[str]:
    """The recommendations a water quality report closes with.

    Every health or national exceedance gets a treatment line whether or not
    there is advice written for its parameter, and the list is the one the
    browser writes, word for word.
    """
    advice: list[str] = []
    corr = assessment.corrosivity
    if corr is not None and corr.is_aggressive:
        advice.append(corr.materials_note)

    def names(rows) -> str:
        return ", ".join(r.parameter for r in rows)

    if assessment.health_exceedances:
        advice.append(
            "Treat or replace the source before it is used for drinking: "
            "health based limits are exceeded for "
            + names(assessment.health_exceedances) + "."
        )
    if assessment.national_exceedances:
        advice.append(
            "Treat before the supply is accepted against the national "
            "standard: national limits are exceeded for "
            + names(assessment.national_exceedances) + "."
        )
    for r in assessment.all_exceedances:
        key = normalise_parameter(r.parameter)
        if key == "ph":
            low = (r.value_in_guideline_unit is not None
                   and r.value_in_guideline_unit < 7.0)
            text = _PH_ADVICE_LOW if low else _PH_ADVICE_HIGH
        elif faecal_pathogen(r.parameter):
            text = _PATHOGEN_ADVICE
        else:
            text = _TREATMENT_ADVICE.get(key)
        if text and text not in advice:
            advice.append(text)
    if assessment.aesthetic_exceedances:
        advice.append(
            "Acceptability limits are exceeded for "
            + names(assessment.aesthetic_exceedances) + ": simple treatment "
            "is advisable if users complain of taste, odour or staining."
        )
    state = assessment.verdict_state
    if state == "indeterminate":
        # "No treatment is required" is a clearance, and this report has not
        # established one. Say what is outstanding instead.
        advice.append(
            "Do not treat this supply as safe to drink on these results. "
            + _sentence("; ".join(assessment.uncertainties))
            + ". Resolve these and re-issue the assessment before any "
            "treatment decision is taken."
        )
    elif state == "pass" and not advice:
        advice.append(
            "No treatment is required on the basis of the parameters tested. "
            "Maintain the sanitary seal and apron in good condition."
        )
    advice.append(
        "Disinfect the borehole after any maintenance and re-test "
        "microbiological quality before the source is returned to use."
    )
    advice.append(
        "Repeat physico-chemical and bacteriological testing at least once a "
        "year, and after any flooding, repair work on the wellhead or change "
        "in taste, colour or odour."
    )
    return advice


@dataclass
class QualityReportInputs:
    assessment: WaterQualityAssessment
    figures_dir: Path
    analyst_name: str = ""
    analyst_role: str = "Water Quality Analyst"
    analyst_phone: str = ""
    include_diagrams: bool = True
    #: The certification gate for this report, from
    #: :func:`groundwater.readiness.assess_readiness`. When it is not
    #: certifiable the cover says so; when it is absent nothing is
    #: stamped, so an existing caller is unaffected.
    readiness: Any = None


def _executive_summary(assessment: WaterQualityAssessment) -> tuple[list[str], list[str]]:
    """Compose the water-quality executive summary from the assessment."""
    community = assessment.sample.site.community or "the site"
    health = assessment.health_exceedances
    national = assessment.national_exceedances
    aesthetic = assessment.aesthetic_exceedances
    state = assessment.verdict_state
    if state == "national_fail":
        names = ", ".join(r.parameter for r in national)
        limits = plural_noun(len(national), "limit")
        if assessment.uncertainties:
            # The national failure outranks the open questions without
            # answering them, so the WHO values are not called met.
            para = (
                f"Laboratory results for the borehole water at {community} do "
                f"not comply with the national standard {limits} for {names}, "
                "and they have not been shown to meet the WHO health based "
                "guideline values: " + "; ".join(assessment.uncertainties) + "."
            )
            who_key = [
                "The WHO health based guideline values have not been shown to be met."
            ] + [_sentence(u) + "." for u in assessment.uncertainties]
        else:
            para = (
                f"Laboratory results for the borehole water at {community} meet "
                "the WHO health based guideline values but do not comply with "
                f"the national standard {limits} for {names}."
            )
            who_key = ["All WHO health based guideline values are met."]
        if any(r.sl_provisional for r in national):
            # The note in section 1 says a provisional limit is to be confirmed
            # before an exceedance of it is treated as a compliance finding;
            # calling it a legal requirement here contradicted it.
            para += (
                f" The national {limits} applied {'are' if len(national) > 1 else 'is'} "
                "provisional, so confirm the figures against the Sierra Leone "
                "Standards Bureau specification before treating the exceedance "
                "as a compliance finding; treatment is required before the "
                "supply can be accepted."
            )
        else:
            para += (
                " A national limit is a legal requirement, not a matter of "
                "taste: treatment is required before the supply can be accepted."
            )
        key = who_key + [
            f"National standard {plural_noun(len(national), 'exceedance')}: {names}.",
            "Treatment is required before the supply is accepted.",
        ]
    elif state == "indeterminate":
        para = (
            f"Laboratory results for the borehole water at {community} do not "
            "establish that the water is suitable for drinking. "
            + _sentence("; ".join(assessment.uncertainties))
            + ". No suitability verdict can be given until these are resolved."
        )
        key = [
            "The water has NOT been shown to be safe to drink.",
        ] + [_sentence(u) + "." for u in assessment.uncertainties]
    elif health:
        names = ", ".join(r.parameter for r in health)
        para = (
            f"Laboratory results for the borehole water at {community} were "
            "assessed against the WHO Guidelines for Drinking-water Quality and "
            "the national/adopted limits. The water does not meet the health "
            f"based guideline {plural_noun(len(health), 'value')} for {names}, so treatment or an "
            "alternative source is required before it is used for drinking."
        )
        key = [
            f"Health based {plural_noun(len(health), 'exceedance')}: {names}.",
            "Treatment or an alternative source is required before drinking.",
        ]
        if national:
            # a national-limit failure beside a health one used to vanish
            # from the summary; the indicator that put it there is named
            also = ", ".join(r.parameter for r in national)
            para += (
                f" The water also fails the national standard "
                f"{plural_noun(len(national), 'limit')} for {also}."
            )
            key.insert(1, f"National standard {plural_noun(len(national), 'exceedance')}: {also}.")
    elif aesthetic:
        names = ", ".join(r.parameter for r in aesthetic)
        para = (
            f"Laboratory results for the borehole water at {community} meet all "
            "health based guideline values. Acceptability (aesthetic) limits are "
            f"exceeded for {names}; the water is usable for drinking, although "
            "taste, odour or staining complaints may arise."
        )
        key = [
            "All health based guideline values are met.",
            f"Aesthetic {plural_noun(len(aesthetic), 'exceedance')}: {names}.",
        ]
    else:
        para = (
            f"Laboratory results for the borehole water at {community} comply "
            "with the WHO guideline values and the national/adopted limits "
            "applied. The water is suitable for drinking on the basis of the "
            "parameters tested."
        )
        key = [
            "All measured parameters comply with the limits applied.",
            "The water is suitable for drinking on the parameters tested.",
        ]
    return [para], key


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
    # Qualify figure filenames with the site: several reports share one
    # figures directory in an app session and generation is guarded by an
    # existence check, so fixed names made the second report silently reuse
    # the first site's figures.
    slug = safe_slug(sample.borehole_ref or site.community, "site")

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
    rb.provisional_stamp(inputs.readiness)

    # ---- executive summary ------------------------------------------------
    exec_paras, exec_key = _executive_summary(assessment)
    rb.executive_summary(exec_paras, exec_key)

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
    # A national exceedance reads as a compliance failure, so the report must
    # say plainly when the limit it was judged against is not yet confirmed.
    # Said when a national value in the table the assessment used is
    # provisional, not whenever the bundled table carries one.
    if any(r.sl_provisional for r in assessment.rows):
        rb.paragraph(PROVISIONAL_NATIONAL_NOTE, align="justify")

    add_area_section(rb, site, figures, config.style,
                     heading="1.1 Location and setting")

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
        value = unquantified_text(r) or (
            "< DL" if (r.below_detection and r.value is None) else fmt_num(r.value))
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

    # headline aggregate scores for quick ranking of the source
    wqi = assessment.wqi
    if wqi is not None:
        rb.paragraph(
            f"Water Quality Index: {wqi.value:.0f} ({wqi.rating}), over "
            f"{wqi.n_parameters} physico-chemical parameters.",
            bold=True,
        )
    hr = assessment.health_risk
    if hr is not None:
        line = f"Health Hazard Index: {hr.hazard_index:.2f} ({hr.rating})."
        if hr.cancer_risk is not None:
            line += (
                f" Estimated lifetime arsenic cancer risk {hr.cancer_risk:.1e}."
            )
        rb.paragraph(line, bold=True)

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

    # ---- 4 corrosivity and materials ---------------------------------------------
    rb.heading("4. Corrosivity and Materials", 1)
    corr = assessment.corrosivity
    if corr is None or corr.classification == "Insufficient data":
        rb.paragraph(
            corr.verdict if corr is not None else
            "Corrosivity was not assessed; pH, calcium and alkalinity are "
            "required to compute the saturation indices."
        )
    else:
        rb.paragraph(corr.verdict, align="justify")
        idx_rows: list[list[str]] = []
        if corr.lsi is not None:
            idx_rows.append(["Langelier Saturation Index (LSI)", f"{corr.lsi:+.2f}"])
        if corr.rsi is not None:
            idx_rows.append(["Ryznar Stability Index (RSI)", f"{corr.rsi:.2f}"])
        if corr.aggressive_index is not None:
            idx_rows.append(["Aggressive Index (AI)", f"{corr.aggressive_index:.2f}"])
        if corr.larson_skold is not None:
            idx_rows.append(["Larson-Skold ratio", f"{corr.larson_skold:.2f}"])
        idx_rows.append(["Classification", corr.classification])
        rb.table(idx_rows, header=["Index", "Value"],
                 caption="Corrosivity and scaling indices.")
        rb.paragraph(corr.materials_note, align="justify", bold=corr.is_aggressive)
        if corr.assumptions:
            rb.paragraph("Assumptions: " + " ".join(corr.assumptions))

    # ---- 5 diagrams ----------------------------------------------------------------
    if inputs.include_diagrams and ionic is not None:
        rb.heading("5. Hydrochemical Facies", 1)
        piper_path = figures / f"piper_{slug}.png"
        stiff_path = figures / f"stiff_{slug}.png"
        plot_piper([sample], path=piper_path, style=config.style)
        plot_stiff(sample, path=stiff_path, style=config.style)
        # the section used to be two figures and no words
        facies = facies_of(sample)
        if facies is not None:
            rb.paragraph(facies["sentence"], align="justify")
        rb.figure(
            piper_path,
            "Piper diagram: the sample's major-ion composition, with the "
            "cations on the left triangle, the anions on the right and the "
            "combined point in the diamond.",
            width_cm=13.0,
        )
        rb.figure(
            stiff_path,
            "Stiff diagram: the same composition as a shape, cations to the "
            "left and anions to the right of the axis.",
            width_cm=11.0,
        )

    # ---- 6 recommendations -----------------------------------------------------------
    rb.heading("6. Recommendations", 1)
    rb.bullets(quality_recommendations(assessment))

    # ---- 7 limitations ---------------------------------------------------------
    rb.heading("7. Limitations and Uncertainty", 1)
    rb.bullets(
        [
            ("The results describe a single sample at one point in time. Water "
            "quality varies with the season, rainfall and the condition of the "
            "wellhead, so periodic re-testing is needed to confirm the "
            "verdict."),
            ("Parameters reported below the laboratory detection limit are shown "
            "as such; a non-detection does not prove complete absence."),
            ("The corrosivity and index calculations use the parameters "
            "supplied. Missing pH, calcium or alkalinity limit what can be "
            "assessed, and any assumptions made are stated where they are "
            "used."),
        ]
    )

    # ---- references and glossary -----------------------------------------------
    rb.references(references_for("quality"))
    rb.glossary(GLOSSARY)

    rb.signature_block(
        name=inputs.analyst_name,
        role=inputs.analyst_role,
        phone=inputs.analyst_phone,
        organisation=config.style.organisation,
    )
    return rb.save(out_path)

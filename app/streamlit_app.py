"""Groundwater toolkit web interface.

Lets the field team upload data files in the standard templates and
produces the analysis figures and client-ready reports without
touching code.

Run from the repository root:

    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import streamlit as st

from groundwater.config import Config
from groundwater.design import design_borehole, draw_borehole_design
from groundwater.hydraulics import analyse_pumping_test
from groundwater.hydraulics.plots import (
    plot_cooper_jacob,
    plot_recovery,
    plot_step_test,
    plot_test_overview,
)
from groundwater.ingestion import (
    check_all,
    read_drilling_workbook,
    read_pumping_docx,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.ingestion.templates import write_all_templates
from groundwater.quality import assess_sample, plot_piper, plot_stiff
from groundwater.reporting.geophysical import (
    GeophysicalReportInputs,
    build_geophysical_report,
)
from groundwater.reporting.pumping import PumpingReportInputs, build_pumping_report
from groundwater.reporting.quality import QualityReportInputs, build_quality_report
from groundwater.utils import fmt_num
from groundwater.ves import interpret_model, invert_sounding
from groundwater.ves.interpret import drilling_preference_table
from groundwater.ves.plots import plot_sounding_curve

st.set_page_config(page_title="Groundwater Toolkit", page_icon=":droplet:", layout="wide")

CONFIG = Config()
IN_BROWSER = sys.platform == "emscripten"  # running under Pyodide (GitHub Pages demo)


def workdir() -> Path:
    if "workdir" not in st.session_state:
        st.session_state.workdir = Path(tempfile.mkdtemp(prefix="gw_"))
    return st.session_state.workdir


def save_upload(uploaded) -> Path:
    path = workdir() / uploaded.name
    path.write_bytes(uploaded.getbuffer())
    return path


def sample_data_dir() -> Path | None:
    """Bundled sample datasets, when present (repo checkout or web demo)."""
    here = Path(__file__).resolve().parent
    for candidate in (
        here.parent / "examples" / "data",
        here / "examples" / "data",
        Path("examples/data"),
    ):
        if candidate.is_dir():
            return candidate
    return None


def choose_input(label: str, key: str, types: list[str], samples: list[str]) -> Path | None:
    """File uploader with an optional bundled-sample fallback.

    Returns the path of the uploaded file, the chosen sample, or None.
    """
    upload = st.file_uploader(label, type=types, key=f"upload_{key}")
    if upload is not None:
        return save_upload(upload)
    root = sample_data_dir()
    if root is not None:
        available = [s for s in samples if (root / s).exists()]
        if available:
            none_option = "(or pick a bundled sample to try)"
            pick = st.selectbox(
                "No file uploaded yet", [none_option] + available, key=f"sample_{key}"
            )
            if pick != none_option:
                return root / pick
    return None


def show_flags(flags) -> None:
    for flag in flags:
        text = str(flag)
        if flag.level == "error":
            st.error(text)
        elif flag.level == "warning":
            st.warning(text)
        else:
            st.info(text)


def offer_download(path: Path, label: str) -> None:
    with open(path, "rb") as fh:
        st.download_button(label, fh.read(), file_name=path.name)


st.title("Groundwater Investigation Toolkit")
st.caption(
    "Vertical electrical soundings, pumping tests, water quality and "
    "borehole design for rural water supply projects in Sierra Leone."
)
if IN_BROWSER:
    st.info(
        "This demo runs entirely in your browser; nothing is uploaded to any "
        "server. Heavy steps such as the VES inversion take noticeably longer "
        "here than in the full installation. Every tab has bundled sample "
        "data so you can try it without your own files."
    )

tab_ves, tab_pump, tab_quality, tab_design, tab_extract, tab_templates = st.tabs(
    ["VES survey", "Pumping test", "Water quality", "Borehole design",
     "Scanned sheets", "Templates"]
)

# ---------------------------------------------------------------------------
# VES
# ---------------------------------------------------------------------------
with tab_ves:
    st.header("VES survey analysis")
    path = choose_input(
        "VES workbook (standard template)", "ves", ["xlsx"],
        ["rokel/rokel_ves.xlsx"],
    )
    if path is not None:
        soundings = read_ves_workbook(path)
        if not soundings:
            st.error("No soundings found in the workbook.")
        else:
            st.success(f"Parsed {len(soundings)} sounding(s).")
            for s in soundings:
                show_flags(s.flags)
            show_flags(check_all([(s.sounding_id, s.site) for s in soundings]))

            if st.button("Run inversion and interpretation", key="run_ves"):
                results = []
                interps = []
                progress = st.progress(0.0)
                for i, sounding in enumerate(soundings):
                    result = invert_sounding(sounding, CONFIG.ves)
                    interp = interpret_model(sounding, result.model, CONFIG.ves)
                    results.append(result)
                    interps.append(interp)
                    progress.progress((i + 1) / len(soundings))
                st.session_state.ves_results = (soundings, results, interps)

    if "ves_results" in st.session_state:
        soundings, results, interps = st.session_state.ves_results
        for sounding, result, interp in zip(soundings, results, interps):
            st.subheader(f"{sounding.sounding_id}")
            fig_path = workdir() / f"curve_{sounding.sounding_id.replace(' ', '_')}.png"
            plot_sounding_curve(sounding, result.model, result.rho_calc, result.ab2, path=fig_path)
            st.image(str(fig_path))
            st.write(
                f"ERR = {result.fit_error_percent:.1f}%, water zones: "
                + (", ".join(f"{int(t)}-{int(b)} m" for t, b in interp.water_zones) or "none"),
            )
            st.write(interp.narrative)
        st.subheader("Drilling preference")
        st.table(drilling_preference_table(interps))

        if st.button("Build geophysical survey report", key="build_geo_report"):
            report_path = build_geophysical_report(
                GeophysicalReportInputs(
                    soundings=soundings,
                    inversions=results,
                    interpretations=interps,
                    figures_dir=workdir(),
                    flags=check_all([(s.sounding_id, s.site) for s in soundings]),
                    include_qa_annex=True,
                ),
                workdir() / "Geophysical_Survey_Report.docx",
                CONFIG,
            )
            offer_download(report_path, "Download geophysical survey report (.docx)")

# ---------------------------------------------------------------------------
# Pumping test
# ---------------------------------------------------------------------------
with tab_pump:
    st.header("Pumping test analysis")
    path = choose_input(
        "Pumping test sheet (template .xlsx or field .docx)", "pump", ["xlsx", "docx"],
        ["dr_timbo/dr_timbo_constant_test.xlsx", "kuntolo/kuntolo_step_test.xlsx"],
    )
    if path is not None:
        test = (
            read_pumping_docx(path) if path.suffix == ".docx" else read_pumping_workbook(path)
        )
        st.success(
            f"Parsed {test.test_type} test with {len(test.steps)} pumping series "
            f"and {'a' if test.recovery_time_min is not None else 'no'} recovery record."
        )
        show_flags(test.flags)

        missing = [s for s in test.steps if s.discharge_m3_per_h is None]
        if missing:
            st.info("Enter discharge rates to complete the analysis (m3/h).")
            cols = st.columns(len(test.steps))
            for col, step in zip(cols, test.steps):
                with col:
                    q = st.number_input(
                        f"{step.label} Q", min_value=0.0, value=0.0, step=0.1,
                        key=f"q_{step.step_number}",
                    )
                    if q > 0:
                        step.discharge_m3_per_h = q

        analysis = analyse_pumping_test(test, CONFIG.pumping)
        st.session_state.pump_analysis = analysis

        overview = workdir() / "overview.png"
        plot_test_overview(test, path=overview)
        st.image(str(overview))

        col1, col2 = st.columns(2)
        with col1:
            if analysis.cooper_jacob is not None:
                cj_path = workdir() / "cj.png"
                swl = test.static_water_level_m
                step = test.steps[0]
                plot_cooper_jacob(step.time_min, step.water_level_m - swl,
                                  analysis.cooper_jacob, path=cj_path)
                st.image(str(cj_path))
        with col2:
            if analysis.recovery is not None:
                rec_path = workdir() / "rec.png"
                plot_recovery(test.recovery_time_min, test.residual_drawdown(),
                              test.pumping_duration_min, analysis.recovery, path=rec_path)
                st.image(str(rec_path))
        if test.test_type.startswith("step"):
            st_path = workdir() / "steps.png"
            plot_step_test(test, analysis.step_test, path=st_path)
            st.image(str(st_path))

        st.subheader("Results")
        if analysis.transmissivity_m2_per_day:
            st.metric("Transmissivity", f"{analysis.transmissivity_m2_per_day:.1f} m2/day")
        yr = analysis.yield_recommendation
        if yr is not None:
            cols = st.columns(3)
            cols[0].metric("Available drawdown",
                           f"{fmt_num(yr.available_drawdown_m)} m" if yr.available_drawdown_m else "n/a")
            cols[1].metric("Safe yield",
                           f"{fmt_num(yr.safe_yield_m3_per_h)} m3/h" if yr.safe_yield_m3_per_h else "pending")
            cols[2].metric("Pump depth",
                           f"{fmt_num(yr.pump_installation_depth_m)} m" if yr.pump_installation_depth_m else "pending")
            st.caption(yr.basis)

        if st.button("Build pumping test report", key="build_pump_report"):
            report_path = build_pumping_report(
                PumpingReportInputs(analysis=analysis, figures_dir=workdir()),
                workdir() / "Pumping_Test_Report.docx",
                CONFIG,
            )
            offer_download(report_path, "Download pumping test report (.docx)")

# ---------------------------------------------------------------------------
# Water quality
# ---------------------------------------------------------------------------
with tab_quality:
    st.header("Water quality assessment")
    path = choose_input(
        "Laboratory results (standard template)", "wq", ["xlsx"],
        ["dr_timbo/dr_timbo_water_quality.xlsx"],
    )
    if path is not None:
        sample = read_quality_workbook(path)
        assessment = assess_sample(sample)
        show_flags(assessment.flags)
        st.subheader("Verdict")
        if assessment.health_exceedances:
            st.error(assessment.verdict)
        elif assessment.aesthetic_exceedances:
            st.warning(assessment.verdict)
        else:
            st.success(assessment.verdict)

        rows = [
            {
                "Parameter": r.parameter,
                "Value": "< DL" if (r.below_detection and r.value is None) else r.value,
                "Unit": r.unit,
                "WHO health": r.who_health,
                "National": r.sl_standard,
                "Status": r.status,
            }
            for r in assessment.rows
        ]
        st.dataframe(rows, use_container_width=True)

        if assessment.ionic is not None:
            st.write(
                f"Ionic balance: cations {assessment.ionic.sum_cations_meq:.2f} meq/L, "
                f"anions {assessment.ionic.sum_anions_meq:.2f} meq/L, "
                f"error {assessment.ionic.error_percent:+.1f}%"
            )
            col1, col2 = st.columns(2)
            piper = workdir() / "piper.png"
            stiff = workdir() / "stiff.png"
            plot_piper([sample], path=piper)
            plot_stiff(sample, path=stiff)
            col1.image(str(piper))
            col2.image(str(stiff))

        if st.button("Build water quality report", key="build_wq_report"):
            report_path = build_quality_report(
                QualityReportInputs(assessment=assessment, figures_dir=workdir()),
                workdir() / "Water_Quality_Report.docx",
                CONFIG,
            )
            offer_download(report_path, "Download water quality report (.docx)")

# ---------------------------------------------------------------------------
# Borehole design
# ---------------------------------------------------------------------------
with tab_design:
    st.header("Borehole design")
    path = choose_input(
        "Drilling log (standard template)", "log", ["xlsx"],
        ["dr_timbo/dr_timbo_drilling_log.xlsx"],
    )
    swl_input = st.number_input("Static water level (m)", min_value=0.0, value=0.0, step=0.1)
    if path is not None:
        log = read_drilling_workbook(path)
        show_flags(log.flags)
        design = design_borehole(
            log=log,
            static_water_level_m=swl_input or None,
            rules=CONFIG.design,
        )
        st.table(design.summary_rows())
        drawing = workdir() / "design.png"
        draw_borehole_design(
            design, log, path=drawing,
            title=f"Borehole design - {log.site.community or 'site'}",
        )
        st.image(str(drawing))
        offer_download(drawing, "Download design drawing (.png)")

# ---------------------------------------------------------------------------
# Scanned sheets
# ---------------------------------------------------------------------------
with tab_extract:
    st.header("Scanned field sheet extraction")
    st.write(
        "Upload a scanned sheet or PDF. Text PDFs are extracted directly; "
        "photos and image scans use the AI assisted extractor when an "
        "Anthropic API key is configured. Uncertain values are highlighted "
        "in the review workbook, never silently accepted."
    )
    import importlib.util

    # probe availability without importing (imports happen on Extract click)
    extraction_available = importlib.util.find_spec("pdfplumber") is not None
    if not extraction_available:
        st.info(
            "Extraction is not available in this installation. It needs the "
            "optional dependencies: pip install groundwater-toolkit[extract] "
            "for text PDFs and [ai] for photographed sheets."
        )
    upload = st.file_uploader("Scan or PDF", type=["pdf", "png", "jpg", "jpeg"], key="scan")
    use_ai = st.checkbox("Use AI assisted extraction (needs ANTHROPIC_API_KEY)")
    if upload is not None and st.button("Extract", key="run_extract"):
        path = save_upload(upload)
        try:
            if use_ai or path.suffix.lower() != ".pdf":
                from groundwater.extraction import ClaudeExtractor

                document = ClaudeExtractor().extract(path)
            else:
                from groundwater.extraction import extract_pdf_text

                document = extract_pdf_text(path)
        except Exception as exc:  # surfaced to the operator
            st.error(str(exc))
        else:
            st.success(
                f"Extracted a {document.document_kind} sheet: "
                f"{len(document.header)} header fields, {len(document.tables)} table(s), "
                f"{len(document.review_items)} item(s) to review."
            )
            from groundwater.extraction import write_review_workbook

            review_path = workdir() / (path.stem + "_review.xlsx")
            write_review_workbook(document, review_path)
            offer_download(review_path, "Download review workbook (.xlsx)")
            if document.document_kind == "ves" and document.tables:
                from groundwater.extraction import fill_ves_template

                template_path = workdir() / (path.stem + "_ves_template.xlsx")
                fill_ves_template(document, template_path)
                offer_download(template_path, "Download filled VES template (.xlsx)")

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
with tab_templates:
    st.header("Blank field data templates")
    st.write("Download the standard templates for the field team.")
    template_dir = workdir() / "templates"
    if st.button("Generate templates", key="gen_templates"):
        for template in write_all_templates(template_dir):
            offer_download(template, f"Download {template.name}")

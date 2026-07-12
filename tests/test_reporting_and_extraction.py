import hashlib
import re

import docx
import pytest

from groundwater.config import Config
from groundwater.design import design_borehole
from groundwater.hydraulics import analyse_pumping_test
from groundwater.ingestion import (
    check_all,
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.quality import assess_sample
from groundwater.reporting import build_geophysical_report
from groundwater.reporting.completion import CompletionReportInputs, build_completion_report
from groundwater.reporting.docx_utils import lint_text
from groundwater.reporting.geophysical import GeophysicalReportInputs
from groundwater.reporting.handover import HandoverReportInputs, build_handover_report
from groundwater.reporting.pumping import PumpingReportInputs, build_pumping_report
from groundwater.reporting.quality import QualityReportInputs, build_quality_report
from groundwater.ves import interpret_model, invert_sounding


def _document_text(path) -> str:
    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


@pytest.fixture(scope="module")
def geophysical_report(sample_data, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("geo")
    soundings = read_ves_workbook(sample_data / "rokel" / "rokel_ves.xlsx")
    inversions = [invert_sounding(s) for s in soundings]
    interps = [interpret_model(s, r.model) for s, r in zip(soundings, inversions)]
    inputs = GeophysicalReportInputs(
        soundings=soundings,
        inversions=inversions,
        interpretations=interps,
        figures_dir=tmp,
        geologist_name="Test Geologist",
        flags=check_all([(s.sounding_id, s.site) for s in soundings]),
        include_qa_annex=True,
    )
    path = build_geophysical_report(inputs, tmp / "geo.docx")
    return path, inputs, tmp


def test_geophysical_report_structure(geophysical_report):
    path, _, _ = geophysical_report
    text = _document_text(path)
    for expected in (
        "Table of Contents",
        "1. Introduction",
        "2. Background and Geology of the Project Area",
        "3.1 Reconnaissance Survey",
        "3.2.1 Resistivity Profiling",
        "3.2.2 Selection of VES Points",
        "3.2.3 Vertical Electrical Sounding (VES)",
        "4. Data Analysis and Interpretation",
        "order of preference for drilling",
        "5. Conclusions and Recommendations",
        "REPORT SUBMITTED BY:",
    ):
        assert expected in text, f"missing section: {expected}"
    # every figure caption is numbered and referenced in the body
    figures = re.findall(r"Figure (\d+)\.", text)
    assert figures and figures == sorted(figures, key=int)
    assert "Figure 1" in text


def test_geophysical_report_reproducible(geophysical_report):
    path, inputs, tmp = geophysical_report
    first = hashlib.sha256(path.read_bytes()).hexdigest()
    again = build_geophysical_report(inputs, tmp / "geo2.docx")
    assert hashlib.sha256(again.read_bytes()).hexdigest() == first


def test_house_style_no_dashes_or_contractions(geophysical_report):
    path, _, _ = geophysical_report
    text = _document_text(path)
    assert "—" not in text  # em dash
    assert "–" not in text  # en dash
    assert not lint_text(text), lint_text(text)


def test_all_other_reports_build(sample_data, tmp_path):
    log = read_drilling_workbook(sample_data / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    test = read_pumping_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    sample = read_quality_workbook(sample_data / "dr_timbo" / "dr_timbo_water_quality.xlsx")
    analysis = analyse_pumping_test(test)
    assessment = assess_sample(sample)
    design = design_borehole(log=log, static_water_level_m=test.static_water_level_m)

    pumping = build_pumping_report(
        PumpingReportInputs(analysis=analysis, figures_dir=tmp_path),
        tmp_path / "pumping.docx",
    )
    completion = build_completion_report(
        CompletionReportInputs(
            log=log, design=design, pumping=analysis, quality=assessment,
            figures_dir=tmp_path,
        ),
        tmp_path / "completion.docx",
    )
    handover = build_handover_report(
        HandoverReportInputs(
            site=log.site, log=log, design=design, pumping=analysis,
            quality=assessment, figures_dir=tmp_path,
        ),
        tmp_path / "handover.docx",
    )
    quality = build_quality_report(
        QualityReportInputs(assessment=assessment, figures_dir=tmp_path),
        tmp_path / "quality.docx",
    )
    for path, must_contain in (
        (pumping, "Cooper-Jacob"),
        (completion, "Borehole Log Data"),
        (handover, "Operation and Maintenance"),
        (quality, "Ionic Balance"),
    ):
        text = _document_text(path)
        assert must_contain in text
        assert "—" not in text
        assert not lint_text(text)
    # traceability: the safety factor is stated explicitly
    assert "safety factor" in _document_text(pumping).lower()


def test_pending_pumping_report(sample_data, tmp_path):
    test = read_pumping_workbook(sample_data / "kuntolo" / "kuntolo_step_test.xlsx")
    analysis = analyse_pumping_test(test)
    path = build_pumping_report(
        PumpingReportInputs(analysis=analysis, figures_dir=tmp_path),
        tmp_path / "kuntolo.docx",
    )
    text = _document_text(path)
    assert "pending" in text.lower()
    assert "discharge" in text.lower()


def test_extraction_review_workbook(tmp_path):
    from groundwater.extraction import (
        ExtractedDocument,
        ExtractedField,
        ExtractedTable,
        UncertainCell,
        fill_ves_template,
        write_review_workbook,
    )
    from openpyxl import load_workbook

    document = ExtractedDocument(
        source="scan.jpg",
        document_kind="ves",
        header=[
            ExtractedField("Community", "Rokel", 0.97),
            ExtractedField("GPS Coordinate East", "0708958", 0.6),
        ],
        tables=[
            ExtractedTable(
                title="Schlumberger Array VES Field Data",
                columns=["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"],
                rows=[["1", "1", "0.4", "1165"], ["2", "2", "0.4", "1193"]],
            )
        ],
        uncertain_cells=[UncertainCell(0, 1, 3, "smudged digits")],
        extractor="claude",
    )
    review = write_review_workbook(document, tmp_path / "review.xlsx")
    wb = load_workbook(review)
    assert set(wb.sheetnames) == {"Header", "Table 1", "Review"}
    review_texts = [row[0].value for row in wb["Review"].iter_rows() if row[0].value]
    assert any("GPS Coordinate East" in t for t in review_texts)

    template = fill_ves_template(document, tmp_path / "ves.xlsx")
    filled = load_workbook(template)
    ws = filled.active
    assert ws["D2"].value == "Rokel"
    assert ws["D4"].value == "0708958"
    assert ws.cell(row=12, column=4).value == "1193"
    # then the standard parser reads the filled template
    from groundwater.ingestion import read_ves_workbook

    soundings = read_ves_workbook(template)
    assert len(soundings) == 1 and soundings[0].n_readings == 2


def test_pdf_kind_guess():
    from groundwater.extraction.pdf_text import _guess_kind

    assert _guess_kind("Schlumberger array VES data, apparent resistivity") == "ves"
    assert _guess_kind("constant discharge pumping test, drawdown") == "pumping_test"
    assert _guess_kind("nothing recognisable") == "unknown"

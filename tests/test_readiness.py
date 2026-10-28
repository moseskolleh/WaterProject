"""The certification gate.

A completion report is what a borehole is handed over on. The toolkit will
write one from whatever it has - an interim report is a real need - but a
document resting on missing evidence must not be indistinguishable from one
that is not. These tests pin the two halves of that: what counts as
established, and what the document says when it is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from groundwater.design import design_borehole
from groundwater.hydraulics import analyse_pumping_test
from groundwater.ingestion import (
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.models import SiteMetadata, WaterQualityResult
from groundwater.quality import assess_sample
from groundwater.readiness import REPORTS, REQUIREMENTS, assess_readiness


@pytest.fixture(scope="module")
def project(sample_data) -> dict:
    """A complete Dr Timbo project, with a position the sheets do not carry."""
    from conftest import synthetic_constant_test

    d = Path(sample_data) / "dr_timbo"
    log = read_drilling_workbook(d / "dr_timbo_drilling_log.xlsx")
    # Dr Timbo's own test pumped for thirty minutes inside its casing
    # storage, so its yield is indicative and no certificate can rest on
    # it; the complete project gets a six-hour test with recovery instead
    analysis = analyse_pumping_test(synthetic_constant_test(recovery=True))
    sample = read_quality_workbook(d / "dr_timbo_water_quality.xlsx")
    return {
        "site": SiteMetadata(
            community="Dr. Timbo's", district="Western Area Rural",
            easting=778000.0, northing=946000.0, utm_zone=28,
        ),
        "drilling_log": log,
        "pump_analysis": analysis,
        "wq_assessment": assess_sample(sample),
        "borehole_design": design_borehole(
            log=log, static_water_level_m=analysis.test.static_water_level_m),
    }


def test_a_complete_project_is_ready(project):
    readiness = assess_readiness(project, "completion")
    assert readiness.state == "ready"
    assert readiness.is_certifiable
    assert readiness.unmet == []


def test_an_empty_project_is_not_ready():
    """Fail closed: nothing loaded is not the same as nothing wrong.

    Two of the checks are negative ones - no unreadable unit, no fatal flag -
    and they are vacuously true when nothing has been loaded. That is
    harmless: every substantive requirement beside them is unmet, so the
    project is not certifiable and the report says exactly which pieces of
    evidence are missing.
    """
    readiness = assess_readiness({}, "completion")
    assert readiness.state == "not_ready"
    assert not readiness.is_certifiable
    outstanding = {r.key for r in readiness.unmet}
    assert outstanding == {
        "site_located", "borehole_logged", "pumping_measured",
        "yield_established", "water_quality_panel", "water_quality_evaluable",
        "design_derived",
    }


def test_the_gate_judges_evidence_not_the_answer(project, sample_data):
    """A borehole that fails a health guideline is still certifiable.

    The finding is the point of the report. A gate that held back bad news
    would teach people to leave the bad news out.
    """
    assessment = project["wq_assessment"]
    assert assessment.verdict_state == "health_fail"     # the sample really does
    assert assess_readiness(project, "completion").state == "ready"


def test_an_ungraded_determinand_holds_the_report_back(project, sample_data):
    """Even when the verdict is already a failure.

    A health exceedance outranks uncertainty in the verdict, and rightly, but
    it does not make an unreadable result readable - so the row is checked,
    not the headline.
    """
    d = Path(sample_data) / "dr_timbo"
    sample = read_quality_workbook(d / "dr_timbo_water_quality.xlsx")
    sample.results.append(WaterQualityResult("Iron", 0.1, "wibbles"))
    state = dict(project, wq_assessment=assess_sample(sample))

    readiness = assess_readiness(state, "completion")
    assert readiness.state == "not_ready"
    outstanding = {r.key for r in readiness.unmet}
    assert "water_quality_evaluable" in outstanding
    assert "Iron" in dict((r.key, r.detail) for r in readiness.unmet)[
        "water_quality_evaluable"]


def test_a_missing_position_holds_every_report_back(project):
    state = dict(project, site=SiteMetadata(community="Nowhere"))
    # the sheets carry no coordinates either, so nothing can supply one
    for report in ("completion", "handover", "quality", "pumping"):
        readiness = assess_readiness(state, report)
        assert "site_located" in {r.key for r in readiness.unmet}, report


def test_a_position_on_any_sheet_locates_the_project(project):
    """Crews write the GPS on one sheet and not the others."""
    log = project["drilling_log"]
    log.site.easting, log.site.northing, log.site.utm_zone = 778000.0, 946000.0, 28
    try:
        state = dict(project, site=SiteMetadata(community="Dr. Timbo's"))
        readiness = assess_readiness(state, "completion")
        assert "site_located" not in {r.key for r in readiness.unmet}
    finally:
        log.site.easting = log.site.northing = None


def test_an_indicative_yield_is_not_established(project, sample_data):
    """Dr Timbo's 30-minute test: the gate used to certify the number."""
    d = Path(sample_data) / "dr_timbo"
    analysis = analyse_pumping_test(read_pumping_workbook(d / "dr_timbo_constant_test.xlsx"))
    assert analysis.yield_recommendation.is_indicative
    state = dict(project, pump_analysis=analysis)
    for report in ("completion", "handover", "pumping"):
        readiness = assess_readiness(state, report)
        unmet = {r.key: r.detail for r in readiness.unmet}
        assert "yield_established" in unmet, report
        assert "indicative, not established" in unmet["yield_established"]
        assert "casing-storage" in unmet["yield_established"]


def test_a_pumping_report_does_not_need_the_water_quality(project):
    """Each report is judged on what it actually claims."""
    state = dict(project, wq_assessment=None)
    assert assess_readiness(state, "pumping").state == "ready"
    assert assess_readiness(state, "completion").state == "not_ready"


def test_an_override_issues_the_report_without_certifying_it(project):
    state = dict(project, wq_assessment=None)
    readiness = assess_readiness(
        state, "completion",
        overrides={
            "water_quality_panel": {"reason": "interim; lab result awaited",
                                    "by": "M. Kolleh"},
            "water_quality_evaluable": "interim; lab result awaited",
        },
    )
    assert readiness.state == "ready_with_overrides"
    # issuable, but never certifiable - those are different claims
    assert not readiness.is_certifiable
    assert {r.key for r in readiness.overridden} == {
        "water_quality_panel", "water_quality_evaluable"}
    assert "M. Kolleh" in [r.override_by for r in readiness.overridden]
    assert "Issued on override" in readiness.summary


def test_an_override_cannot_invent_a_requirement_that_was_met(project):
    """Overriding something already established must not change its record."""
    readiness = assess_readiness(
        project, "completion", overrides={"borehole_logged": "not needed"})
    logged = [r for r in readiness.requirements if r.key == "borehole_logged"][0]
    assert logged.state == "met" and not logged.override_reason


def test_a_check_that_raises_is_not_a_pass():
    """A broken check must never read as an established requirement."""
    class Exploding:
        flags = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))

    readiness = assess_readiness({"pump_analysis": Exploding()}, "pumping")
    assert readiness.state == "not_ready"
    assert any("could not run" in r.detail for r in readiness.unmet)


def test_the_readiness_record_is_serialisable(project):
    import json

    import yaml

    payload = assess_readiness(project, "completion").as_dict()
    assert json.dumps(payload)
    assert yaml.safe_dump(payload)


def test_every_report_names_only_requirements_that_exist():
    for report, keys in REPORTS.items():
        assert keys, report
        for key in keys:
            assert key in REQUIREMENTS, f"{report} names an unknown requirement {key}"


def test_a_provisional_report_says_so_on_its_cover(project, tmp_path):
    """The stamp is the whole point: it travels with the document."""
    from docx import Document

    from groundwater.reporting.quality import QualityReportInputs, build_quality_report

    state = dict(project, site=SiteMetadata(community="Nowhere"))
    readiness = assess_readiness(state, "quality")
    assert not readiness.is_certifiable

    out = build_quality_report(
        QualityReportInputs(
            assessment=project["wq_assessment"], figures_dir=tmp_path,
            include_diagrams=False, readiness=readiness,
        ),
        tmp_path / "quality.docx",
    )
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "PROVISIONAL - NOT FOR CERTIFICATION" in text
    assert "Site position" in text


def test_a_ready_report_carries_no_stamp(project, tmp_path):
    from docx import Document

    from groundwater.reporting.quality import QualityReportInputs, build_quality_report

    readiness = assess_readiness(project, "quality")
    assert readiness.is_certifiable
    out = build_quality_report(
        QualityReportInputs(
            assessment=project["wq_assessment"], figures_dir=tmp_path,
            include_diagrams=False, readiness=readiness,
        ),
        tmp_path / "quality_ready.docx",
    )
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "PROVISIONAL" not in text
    assert "NOT A CERTIFICATION" not in text


@pytest.mark.slow
def test_the_geophysical_report_is_stamped_when_the_site_is_unlocated(
        sample_data, tmp_path):
    """The gate declares a rule for this report, so the report must carry it.

    A survey whose points have no position cannot be found again on the
    ground, which is the whole of what the geophysical requirement asks.
    """
    from docx import Document

    from groundwater.reporting.geophysical import (
        GeophysicalReportInputs,
        build_geophysical_report,
    )
    from groundwater.ves import interpret_model, invert_sounding

    soundings = read_ves_workbook(sample_data / "rokel" / "rokel_ves.xlsx")
    inversions = [invert_sounding(s) for s in soundings]
    interps = [interpret_model(s, r.model)
               for s, r in zip(soundings, inversions, strict=True)]
    readiness = assess_readiness({"site": SiteMetadata(community="Nowhere")},
                                 "geophysical")
    assert not readiness.is_certifiable

    out = build_geophysical_report(
        GeophysicalReportInputs(
            soundings=soundings, inversions=inversions,
            interpretations=interps, figures_dir=tmp_path,
            readiness=readiness),
        tmp_path / "geophysical.docx",
    )
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "PROVISIONAL - NOT FOR CERTIFICATION" in text
    assert "Site position" in text


def test_the_costing_and_supervision_reports_are_stamped_too(tmp_path):
    from docx import Document

    from groundwater.costing.model import CostingInputs, estimate_borehole_cost
    from groundwater.reporting.costing import CostReportInputs, build_cost_report
    from groundwater.reporting.supervision import (
        SupervisionReportInputs,
        build_supervision_report,
    )
    from groundwater.supervision.checklists import (
        ChecklistResponse,
        evaluate_checklist,
        load_checklists,
    )

    site = SiteMetadata(community="Nowhere")
    estimate = estimate_borehole_cost(CostingInputs(total_depth_m=45.0))
    cost_readiness = assess_readiness({"site": site}, "costing")
    assert not cost_readiness.is_certifiable
    cost_doc = build_cost_report(
        CostReportInputs(
            estimate=estimate, site=site, figures_dir=tmp_path,
            readiness=cost_readiness),
        tmp_path / "cost.docx",
    )
    cost_text = "\n".join(p.text for p in Document(str(cost_doc)).paragraphs)
    assert "PROVISIONAL - NOT FOR CERTIFICATION" in cost_text
    # an estimate is a pre-construction document: it is not held to a drilling
    # log or an as-built design, only to a position and its own basis
    assert "Cost estimate" in cost_text and "Drilling log" not in cost_text
    located = SiteMetadata(community="Nowhere", easting=778000.0, northing=946000.0, utm_zone=28)
    # the cost is a decision number, so the estimate alone, with no
    # distribution to band it, is not enough (PLAN.md step 3.6)
    unbanded = assess_readiness({"site": located, "cost_estimate": estimate}, "costing")
    assert [r.key for r in unbanded.unmet] == ["decision_bands"]
    from groundwater.costing.distribution import sample_cost

    spread = sample_cost(CostingInputs(total_depth_m=45.0), samples=200)
    assert assess_readiness({"site": located, "cost_estimate": estimate,
                             "cost_distribution": spread}, "costing").is_certifiable
    assert not assess_readiness({"site": located}, "costing").is_certifiable

    items = load_checklists()
    responses = {i.item_id: ChecklistResponse(i.item_id, "yes")
                 for i in items[:20]}
    sup_readiness = assess_readiness({"site": site}, "supervision")
    sup_doc = build_supervision_report(
        SupervisionReportInputs(
            site=site, items=items, responses=responses,
            assessment=evaluate_checklist(items, responses),
            readiness=sup_readiness),
        tmp_path / "supervision.docx",
    )
    sup_text = "\n".join(p.text for p in Document(str(sup_doc)).paragraphs)
    assert "PROVISIONAL - NOT FOR CERTIFICATION" in sup_text
    assert "Site position" in sup_text


def test_an_overridden_report_names_who_issued_it(project, tmp_path):
    from docx import Document

    from groundwater.reporting.quality import QualityReportInputs, build_quality_report

    state = dict(project, site=SiteMetadata(community="Nowhere"))
    readiness = assess_readiness(
        state, "quality",
        overrides={"site_located": {"reason": "GPS unit failed; position to "
                                              "follow", "by": "M. Kolleh"}},
    )
    assert readiness.state == "ready_with_overrides"
    out = build_quality_report(
        QualityReportInputs(
            assessment=project["wq_assessment"], figures_dir=tmp_path,
            include_diagrams=False, readiness=readiness,
        ),
        tmp_path / "quality_override.docx",
    )
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "ISSUED ON OVERRIDE" in text
    assert "M. Kolleh" in text
    assert "GPS unit failed" in text


# ---------------------------------------------------------------------------
# The supervision record and the drilling log reader
# ---------------------------------------------------------------------------

def _critical_items():
    from groundwater.supervision import load_checklists

    return [i for i in load_checklists() if i.critical]


def test_a_critical_item_never_answered_keeps_the_supervision_record_provisional():
    """Three photographed items answered and 35 critical ones blank was a
    certified record whose own summary said 35 critical items were open."""
    photo = {"b64": "AAAA"}
    photographed = ("des-casing-screen-assemblage", "des-backfill-placed-6",
                    "dev-borehole-disinfected-chlorine")
    state = {"supervision": {
        "evidence": {key: photo for key in photographed},
        "responses": {key: {"status": "yes"} for key in photographed}}}
    readiness = assess_readiness(state, "supervision")
    assert not readiness.is_certifiable
    (req,) = [r for r in readiness.requirements if r.key == "checklist_answered"]
    assert req.state == "unmet"
    assert req.detail.startswith("No answer is recorded for 35 critical checklist items "
                                 "(4 in Procurement and contract, 5 in Pre-contract")
    # an answer of No is an answer: the record states the failure, and is
    # complete; N/A is an answer too, in either app's shape
    answers = {i.item_id: ("No" if n % 3 == 0 else {"status": "na"} if n % 3 == 1
                           else "yes") for n, i in enumerate(_critical_items())}
    state["supervision"]["responses"] = answers
    readiness = assess_readiness(state, "supervision")
    (req,) = [r for r in readiness.requirements if r.key == "checklist_answered"]
    assert (req.state, req.detail) == ("met", (
        "Each of the 38 critical checklist items has an answer. This asks only "
        "that each was answered: an answer of No stays in the record as a failure."))
    # an answer that is none of the four is read as pending
    answers[_critical_items()[0].item_id] = "maybe"
    (req,) = [r for r in assess_readiness(state, "supervision").requirements
              if r.key == "checklist_answered"]
    assert req.state == "unmet" and "1 critical checklist item (1 in" in req.detail
    assert REPORTS["supervision"] == ("field_data", "site_located", "checklist_answered",
                                      "photo_evidence")


def test_a_log_the_reader_set_part_of_aside_is_not_called_complete():
    """A dropped row and a refused strike used to pass "Drilling log" and
    "Every reading carried a unit the toolkit could read"."""
    import datetime

    from groundwater.ingestion.drilling import REFUSAL_CODES, drilling_from_grid

    grid = [
        ["Total depth (m)", 45],
        ["Depth interval (m)", "Sample / lithology description", "Water strike depth (m)"],
        ["0-5", "Laterite", None],
        [datetime.datetime(2026, 10, 5), "Clay", None],
        ["10-30", "Weathered granite", "18/22"],
        ["30-45", "Granite", None],
    ]
    log = drilling_from_grid(grid)
    assert {f.code for f in log.flags} >= {"interval_read_as_date", "water_strike_unreadable"}
    readiness = assess_readiness({"drilling_log": log}, "completion")
    states = {r.key: (r.state, r.detail) for r in readiness.requirements}
    assert states["borehole_logged"][0] == "unmet"
    assert states["borehole_logged"][1].startswith(
        "The drilling log reader set part of the sheet aside, so the log is not "
        "complete: Depth interval cell holds the date 05 Oct 2026")
    assert states["readings_usable"][0] == "unmet"
    assert "18/22" in states["readings_usable"][1]
    assert set(REFUSAL_CODES) >= {"interval_read_as_date", "interval_unreadable",
                                  "water_strike_unreadable", "diameter_implausible",
                                  "depth_unit_ambiguous"}

    # A strike below the bottom of the hole carried its unit and was read,
    # then refused: the log is not complete, but every reading was readable.
    deep = drilling_from_grid([
        ["Total depth (m)", 45],
        ["Depth interval (m)", "Sample / lithology description", "Water strike depth (m)"],
        ["0-45", "Granite", "165 m"]])
    assert [f.code for f in deep.flags] == ["water_strike_below_total_depth"]
    states = {r.key: (r.state, r.detail) for r in assess_readiness(
        {"drilling_log": deep}, "completion").requirements}
    assert states["borehole_logged"][0] == "unmet"
    assert "165 m below the recorded total depth of 45 m" in states["borehole_logged"][1]
    assert states["readings_usable"] == (
        "met", "Every reading carried a unit the toolkit could read.")


def test_a_log_converted_from_feet_is_complete_and_says_it_was_converted():
    from groundwater.ingestion.drilling import drilling_from_grid

    log = drilling_from_grid([
        ["Total depth (ft):", "150 ft"],
        ["Depth interval (ft)", "Sample / lithology description"],
        ["0-20", "Laterite"], ["20-150", "Granite"]])
    readiness = assess_readiness({"drilling_log": log}, "completion")
    states = {r.key: (r.state, r.detail) for r in readiness.requirements}
    assert states["borehole_logged"] == ("met", "Logged to 46 m with 2 lithological intervals.")
    assert states["readings_usable"][0] == "met"
    assert readiness.assumptions == [(
        "The drilling log gives 5 depths in feet; they were converted to metres "
        "at 0.3048 m to the foot and kept to the centimetre (the deepest, 150 ft, "
        "is 45.72 m). Check the converted log against the sheet.")]

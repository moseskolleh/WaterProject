"""Supervision module: checklist data, scoring and the field
acceptance checks from the RWSN supervision guidance."""

from __future__ import annotations

from pathlib import Path

import pytest

from groundwater.models import SiteMetadata
from groundwater.reporting.supervision import (
    SupervisionReportInputs,
    build_supervision_report,
)
from groundwater.supervision import (
    STAGE_ORDER,
    ChecklistResponse,
    annular_space_check,
    disinfection_dose,
    evaluate_checklist,
    handpump_corrosion_check,
    load_checklists,
    load_separation_distances,
    pack_aquifer_ratio_check,
    sand_content_check,
    screen_open_area_check,
    specific_capacity_check,
    stage_title,
    verticality_check,
)


def test_checklists_load_in_stage_order():
    items = load_checklists()
    assert len(items) >= 70
    stages_seen: list[str] = []
    for item in items:
        if item.checklist not in stages_seen:
            stages_seen.append(item.checklist)
    assert tuple(stages_seen) == STAGE_ORDER, "CSV order must match STAGE_TITLES"
    assert any(i.critical for i in items)
    ids = [i.item_id for i in items]
    assert len(ids) == len(set(ids))
    assert stage_title("drilling") == "Drilling"


def test_evaluate_counts_and_critical_failures():
    items = load_checklists()
    critical = next(i for i in items if i.critical)
    routine = next(i for i in items if not i.critical)
    responses = {
        critical.item_id: ChecklistResponse(critical.item_id, "no", "failed"),
        routine.item_id: ChecklistResponse(routine.item_id, "yes"),
    }
    a = evaluate_checklist(items, responses)
    assert a.total == len(items)
    assert a.answered == 2
    assert a.critical_failures == 1
    assert "critical" in a.verdict
    assert any(f.code == "critical_item_failed" for f in a.flags)

    # not-applicable counts as answered and passed, unknown states as pending
    responses[critical.item_id] = ChecklistResponse(critical.item_id, "na")
    responses[routine.item_id] = ChecklistResponse(routine.item_id, "bogus")
    a2 = evaluate_checklist(items, responses)
    assert a2.critical_failures == 0
    assert a2.answered == 1


def test_evaluate_accepts_response_list():
    items = load_checklists()
    a = evaluate_checklist(items, [ChecklistResponse(items[0].item_id, "yes")])
    assert a.answered == 1


def test_separation_distances():
    distances = load_separation_distances()
    by_structure = {d.structure: d.min_distance_m for d in distances}
    assert by_structure["Water supply borehole"] == 50
    assert by_structure["Septic tank or soakaway"] == 20


def test_sand_content_limits():
    ok = sand_content_check([0.1, 0.15, 0.2])
    assert ok.passed is True
    bad = sand_content_check([0.1, 0.25, 0.1])
    assert bad.passed is False
    assert sand_content_check([]).passed is None


def test_verticality_rule():
    # two thirds of a 100 mm ID over 30 m allows 66.7 mm
    check = verticality_check(60, 30, 100)
    assert check.passed is True
    assert verticality_check(70, 30, 100).passed is False


def test_screen_open_area_rule():
    # Q = 3 L/s needs at least 0.1 m2
    assert screen_open_area_check(3.0, 0.11).passed is True
    assert screen_open_area_check(3.0, 0.09).passed is False


def test_specific_capacity_rule():
    assert specific_capacity_check(3.6, 2.0).passed is True
    assert specific_capacity_check(0.9, 2.0).passed is False
    assert specific_capacity_check(1.0, 0.0).passed is None


def test_pack_aquifer_ratio():
    assert pack_aquifer_ratio_check(2.0, 0.4).passed is True  # ratio 5
    assert pack_aquifer_ratio_check(4.0, 0.4).passed is False  # ratio 10


def test_annular_space_rule():
    # 6.5 inch hole (165 mm) with 125 mm OD casing leaves only 20 mm
    assert annular_space_check(6.5, 125).passed is False
    # 10 inch hole with 113 mm casing leaves 70+ mm: a true gravel pack
    wide = annular_space_check(10, 113)
    assert wide.passed is True and "gravel pack" in wide.message.lower()


def test_corrosion_rule_boundary():
    assert handpump_corrosion_check(6.5).passed is True
    assert handpump_corrosion_check(6.4).passed is False


def test_disinfection_dose_example():
    """40 m water column in 103 mm ID casing holds about 333 L, needing
    about 3.3 L of 0.2 percent solution (WHO 20 mg/L shock dose)."""
    dose = disinfection_dose(40, 103)
    assert dose.well_volume_l == pytest.approx(333, rel=0.02)
    assert dose.solution_02pct_l == pytest.approx(dose.well_volume_l / 100)
    assert dose.hth_grams == pytest.approx(dose.solution_02pct_l * 2 / 0.65)
    assert "4 hours" in dose.summary()


def test_supervision_report_builds_and_reproducible(tmp_path: Path):
    items = load_checklists()
    responses = {
        i.item_id: ChecklistResponse(i.item_id, "yes") for i in items[:20]
    }
    failed = next(i for i in items if i.critical)
    responses[failed.item_id] = ChecklistResponse(failed.item_id, "no", "not done")
    assessment = evaluate_checklist(items, responses)
    inputs = SupervisionReportInputs(
        site=SiteMetadata(community="Kuntolo", district="Bombali",
                          client="Client", contractor="Driller Ltd"),
        items=items,
        responses=responses,
        assessment=assessment,
        supervisor="A. Supervisor",
        notes=["Site instruction 1 issued in duplicate."],
    )
    a = build_supervision_report(inputs, tmp_path / "a.docx")
    b = build_supervision_report(inputs, tmp_path / "b.docx")
    assert a.stat().st_size > 20_000
    assert a.read_bytes() == b.read_bytes()

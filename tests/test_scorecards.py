"""Contractor scorecards (PLAN.md step 6.3)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from groundwater import ledger as L
from groundwater import scorecards as SC
from groundwater.calibration import binomial_range
from groundwater.config import Config
from groundwater.ingestion import read_drilling_workbook
from groundwater.project_io import (
    PERSIST_PREFIXES,
    deserialize_project,
    serialize_project,
    stale_on_load,
)
from groundwater.supervision import load_checklists
from groundwater.text import phrase, phrase_table
from groundwater.utils import sum_in_order

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"
DATA = REPO / "examples" / "data"


def ns(value):
    """A dict as the attributes the engine reads, all the way down."""
    if isinstance(value, dict):
        return SimpleNamespace(**{k: ns(v) for k, v in value.items()})
    if isinstance(value, list):
        return [ns(v) for v in value]
    return value


@pytest.fixture(scope="module")
def timbo():
    return read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")


CONTRACT = {"lines": [{"code": "DRL", "item": "Drilling", "unit": "m", "quantity": 60.0, "rate_usd": 40.0},
                      {"code": "CAS", "item": "Casing", "unit": "m", "quantity": 60.0, "rate_usd": 12.5}],
            "variations": [{"ref": "VO-1", "date": "2018-05-12", "code": "DRL", "quantity_delta": 10.0,
                            "rate_usd": None, "reason": "Water deeper", "authorised_by": "  A.  Kamara "},
                           {"ref": "VO-2", "date": "2018-05-12", "code": "CAS", "quantity_delta": 5.0,
                            "rate_usd": None, "reason": "", "authorised_by": " \t"},
                           {"ref": "VO-3", "date": "", "code": "", "quantity_delta": 99.0}],
            "due": " 2018-05-10 "}


def _site(contractor="", community="Dr Timbo", district="Port Loko"):
    return SimpleNamespace(contractor=contractor, community=community, district=district)


# ------------------------------------------------------------------- dates

@pytest.mark.parametrize("text, day", [
    ("13th May, 2018", "2018-05-13"), ("13 May 2018", "2018-05-13"), ("13th of May 2018", "2018-05-13"),
    ("May 13, 2018", "2018-05-13"), ("May. 13th, 2018", "2018-05-13"), ("13-May-2018", "2018-05-13"),
    ("3 Sept 2019", "2019-09-03"), ("13TH MAY 2018", "2018-05-13"), ("2018-05-13", "2018-05-13"),
    ("2018-05-13 08:30", "2018-05-13"), ("2018-05-13T08:30:00", "2018-05-13"), ("29 Feb 2020", "2020-02-29"),
    # figures alone can be read two ways round, and are not read
    ("05/06/2018", None), ("25/04/2018", None), ("13.05.2018", None),
    # a day the month does not have, a month nobody has, a year of nought
    ("29 Feb 2019", None), ("31 April 2018", None), ("13 Mayo 2018", None), ("0000-01-01", None),
    ("2018-13-01", None), ("", None), (None, None), ("13 May", None), ("Kelvin 13 Kay 2018", None),
])
def test_a_written_date_is_read_only_where_it_names_one_day(text, day):
    assert SC.written_day(text) == day


# ------------------------------------------------------------- the record

def test_the_record_holds_what_the_project_records_of_its_contractors_work(timbo):
    answers = {"drl-daily-drilling-log": "no", "drl-depth-measured-marked": "yes", "dev-plumb-test-passed": "na",
               "prc-contractor-registered-country": "no", "not-an-item": "no", "drl-strata-log-prepared": "pending"}
    record = SC.works_record(_site(), timbo, None, L.empty_ledger(), answers,
                             {"logged_m": 70.0, "claimed_m": 75.456}, CONTRACT)
    assert record["drilled"] is True
    # the project names none, so the log's contractor
    assert record["contractor"] == "WiNGiN Heavy Duty Machines Co. Ltd"
    assert (record["borehole_ref"], record["completion_date"]) == ("BH-1", "13th May, 2018")
    assert (record["success"], record["success_basis"]) == (True, "recorded_success")
    # paired with no surveyed point, so no forecast, and its own identifier
    assert record["forecast"] is None
    assert record["id"] == L.point_id("borehole BH-1", timbo.site.easting, timbo.site.northing,
                                      timbo.site.utm_zone, "Dr Timbo", "Port Loko")
    # every stage answered, Yes or No; N/A and pending are not answers
    assert record["checklist"] == {"drilling": {"answered": 2, "failed": ["drl-daily-drilling-log"]},
                                   "procurement": {"answered": 1, "failed": ["prc-contractor-registered-country"]}}
    assert (record["logged_m"], record["claimed_m"]) == (70.0, 75.46)
    # VO-2's signature is white space, so it is a request; VO-3 names no line
    assert (record["contract"], record["variations_signed"], record["variations_unsigned"]) == (True, 1, 1)
    assert record["variation_usd"] == 400.0
    assert record["completion_due"] == "2018-05-10"
    # the file holds exactly what clean_works reads back
    assert SC.clean_works(record) == record
    assert list(record) == sorted(record)


def test_the_project_contractor_wins_over_the_logs(timbo):
    record = SC.works_record(_site("  Kaba   Drilling "), timbo, None, None)
    assert record["contractor"] == "Kaba Drilling"


def test_nothing_recorded_is_no_record():
    assert SC.works_record(_site("Kaba"), None, None, L.empty_ledger(), {"drl-daily-drilling-log": "pending"},
                           {"logged_m": None, "claimed_m": None}, None) is None
    # a contract with no lines is not a contract
    assert SC.works_record(_site(), None, None, None, None, None, {"lines": [], "variations": []}) is None


def test_a_metre_count_is_a_number_not_below_nought(timbo):
    for logged, claimed in ((-1.0, 70.0), ("70", 70.0), (float("nan"), 70.0), (True, 70.0)):
        record = SC.works_record(_site(), timbo, None, None, None, {"logged_m": logged, "claimed_m": claimed})
        assert record["logged_m"] is None and record["claimed_m"] == 70.0


def _survey_point(before: bool, p: float = 0.62):
    interp = SimpleNamespace(sounding_id="VES 1", depth_to_basement_m=20.0, basement_not_resolved=False,
                             investigation_depth_m=60.0, water_zones=[(8.0, 20.0)], aquifer_thickness_m=12.0,
                             max_drilling_depth_m=35.0, drilling_depth_capped=False, fit_error_percent=3.0,
                             site_easting=None, site_northing=None, layers=[])
    odds = SimpleNamespace(probability=p, low=0.3, high=0.8, prior=0.5, effective_n=10.0, status="provisional",
                           matched="class", bgs_code="B-L", glg="pCm", success_yield_m3_per_h=1.0, calibration="")
    survey = L.survey_predictions([interp], None, [odds], SimpleNamespace(community="Dr Timbo",
                                                                           district="Port Loko", utm_zone=28))
    held, _ = L.record_predictions(L.empty_ledger(), survey, "2018-04-01", not before, "0.3.0")
    return held


def test_the_forecast_is_the_chance_recorded_before_drilling_at_the_point_drilled(timbo):
    held = _survey_point(before=True)
    record = SC.works_record(_site(), timbo, None, held)
    # the survey's only point, so the log pairs with it
    assert record["id"] == held["entries"][0]["id"]
    assert record["forecast"] == 0.62
    # a prediction recorded after drilling is not a forecast
    assert SC.works_record(_site(), timbo, None, _survey_point(before=False))["forecast"] is None


def test_a_file_whose_log_was_not_carried_keeps_the_outcome_its_ledger_recorded(timbo):
    held = L.attach_outcome(_survey_point(before=True), L.completion_outcome(timbo, None, Config()))
    record = SC.works_record(_site(), None, None, held)
    assert record["drilled"] and record["success"] is True and record["forecast"] == 0.62
    assert record["contractor"] == "WiNGiN Heavy Duty Machines Co. Ltd"


def test_a_hand_edited_record_is_cleaned_not_raised(timbo):
    good = SC.works_record(_site(), timbo, None, None, {"drl-daily-drilling-log": "no"}, None, CONTRACT)
    assert SC.clean_works(None) is None and SC.clean_works("works") is None
    assert SC.clean_works(dict(good, id="")) is None and SC.clean_works(dict(good, id=7)) is None
    edited = SC.clean_works(dict(
        good, checklist={"drilling": {"answered": 1, "failed": ["a", "b"]},  # more failed than answered
                         "design": {"answered": 2, "failed": ["x", "x", 3, ""]},
                         "Design": {"answered": 1, "failed": []}, "10": {"answered": 1, "failed": []},
                         "development": {"answered": 0, "failed": []}, "demobilisation": {"answered": True}},
        forecast=1.5, success="yes", success_basis="tested", logged_m=-3, contractor=" A \t B "))
    assert edited["checklist"] == {"design": {"answered": 2, "failed": ["x"]}}
    assert (edited["forecast"], edited["success"], edited["success_basis"]) == (None, None, None)
    assert (edited["logged_m"], edited["contractor"]) == (None, "A B")
    # a completion date due is text: a number would be written out one way
    # here and another in the browser
    assert SC.clean_works(dict(good, completion_due=20180510.0))["completion_due"] == ""
    assert SC.works_record(_site(), timbo, None, None, None, None, dict(CONTRACT, due=20180510))[
        "completion_due"] == ""
    # counts that do not go with a contract are dropped with it
    for broken in ({"contract": False}, {"variations_signed": -1}, {"variations_unsigned": 1.5},
                   {"variation_usd": "400"}, {"variations_signed": True}):
        cleaned = SC.clean_works(dict(good, **broken))
        assert (cleaned["contract"], cleaned["variations_signed"], cleaned["variation_usd"],
                cleaned["completion_due"]) == (False, None, None, "")


# ----------------------------------------------------------------- pooling

def _row(k: int, contractor: str, project: str = "x", **fields) -> dict:
    """A drilled borehole as a works record holds it, pooled from ``project``."""
    record = SC.clean_works(dict({"id": f"bh{k:03d}", "drilled": True, "contractor": contractor,
                                  "borehole_ref": f"BH-{k}"}, **fields))
    return dict(record, project=project, source="works")


def test_a_borehole_is_counted_once_from_its_richest_copy(timbo):
    rich = SC.works_record(_site(), timbo, None, _survey_point(True), {"drl-daily-drilling-log": "no"},
                           {"logged_m": 70.0, "claimed_m": 70.0}, CONTRACT)
    poor = SC.works_record(_site(), timbo, None, _survey_point(True))
    older = L.attach_outcome(_survey_point(True), L.completion_outcome(timbo, None, Config()))
    undrilled = SC.works_record(_site("Kaba"), None, None, None, {"drl-daily-drilling-log": "no"})
    files = [("old copy", None, older), ("poor", poor, None), ("rich", rich, None), ("Kaba", undrilled, None),
             ("not a record", "junk", L.empty_ledger())]
    boreholes = SC.scorecard_boreholes(files)
    assert len(boreholes) == 1
    assert (boreholes[0]["project"], boreholes[0]["source"]) == ("rich", "works")
    # on its own, the file saved before the works record gives its dry holes
    alone = SC.scorecard_boreholes([("old copy", None, older)])
    assert [(b["source"], b["forecast"], b["success"], b["logged_m"]) for b in alone] == [
        ("ledger", 0.62, True, None)]


# -------------------------------------------------------------- scorecards

def test_a_measure_nobody_recorded_reads_not_recorded_and_a_recorded_none_reads_none():
    boreholes = [_row(1, "Kaba", "A", contract=True, variations_signed=0, variations_unsigned=0, variation_usd=0.0,
                      checklist={"drilling": {"answered": 3, "failed": []}}),
                 _row(2, "Kaba", "B")]
    card = SC.contractor_scorecards(boreholes)[0]
    assert card["metres"] == {"n": 0, "logged_m": None, "claimed_m": None, "over_m": None, "beyond": 0}
    assert card["variations"] == {"n": 1, "signed": 0, "unsigned": 0, "value_usd": 0.0}
    assert card["checks"]["n"] == 1 and card["checks"]["failed"] == 0
    assert card["time"]["n"] == 0 and card["time"]["days_late"] is None
    assert card["dry"]["known"] == 0 and card["dry"]["expected"] is None
    row = SC.scorecard_content([("A", boreholes[0], None), ("B", boreholes[1], None)])["sections"][0]["tables"][0]
    cells = dict(zip(row["header"], row["rows"][0], strict=True))
    nothing = phrase("scorecards.not_recorded")
    assert cells[phrase("scorecards.col_metres")] == nothing
    assert cells[phrase("scorecards.col_time")] == nothing
    assert cells[phrase("scorecards.col_variations")] == "None signed on 1 contract"
    assert cells[phrase("scorecards.col_checks")] == "None failed on 1 borehole checked"
    assert cells[phrase("scorecards.col_dry")] == phrase("scorecards.dry_cell_unknown")


def _forecasts(contractor: str, start: int, chances, dry: int) -> list[dict]:
    """Boreholes forecast at ``chances``, the first ``dry`` of them dry."""
    return [_row(start + k, contractor, contractor, forecast=p, success=k >= dry, success_basis="tested")
            for k, p in enumerate(chances)]


def test_a_contractor_is_ranked_only_on_five_forecast_boreholes():
    boreholes = (_forecasts("Kaba", 0, [0.8] * 6, dry=0) + _forecasts("WiNGiN", 10, [0.5] * 5, dry=4)
                 + _forecasts("Sesay", 20, [0.8] * 4, dry=0) + _forecasts("", 30, [0.6] * 6, dry=1)
                 + _forecasts("Conteh", 40, [0.8] * 5, dry=0) + [_row(50, "Sesay")])
    cards = SC.contractor_scorecards(boreholes)
    assert [(c["contractor"], c["rank"], c["unranked"]) for c in cards] == [
        ("Conteh", 1, None), ("Kaba", 1, None), ("WiNGiN", 3, None),
        ("Sesay", None, "too_few"), (phrase("scorecards.no_contractor"), None, "no_contractor")]
    kaba = next(c for c in cards if c["contractor"] == "Kaba")
    # 0 dry where 6 x 0.2 were expected
    assert kaba["dry"]["expected"] == 1.2 and kaba["measure"] == round(-1.2 / 6, 3)
    sesay = next(c for c in cards if c["contractor"] == "Sesay")
    assert (sesay["boreholes"], sesay["dry"]["forecast"], sesay["measure"]) == (5, 4, None)
    rows = SC.scorecard_content([(b["project"], b, None) for b in boreholes])["sections"][0]["tables"][0]["rows"]
    assert [r[-1] for r in rows] == ["1", "1", "3", "Not ranked: 4 forecast, 5 needed",
                                     "Not ranked: no contractor named"]
    # the minimum is a setting
    config = Config()
    config.ledger.scorecard_min_boreholes = 4
    assert next(c for c in SC.contractor_scorecards(boreholes, config) if c["contractor"] == "Sesay")["rank"] == 1
    # and a contractor with no forecast is never ranked, whatever it says
    config.ledger.scorecard_min_boreholes = 0
    plain = SC.contractor_scorecards([_row(60, "Turay", success=True, success_basis="tested")], config)
    assert (plain[0]["rank"], plain[0]["unranked"], plain[0]["measure"]) == (None, "too_few", None)
    rows = SC.scorecard_content([("x", _row(60, "Turay"), None)], config=config)["sections"][0]["tables"][0]["rows"]
    assert rows[0][-1] == "Not ranked: 0 forecast, 1 needed"


def test_dry_holes_are_judged_against_the_binomial_range_at_the_mean_chance():
    chances = [0.9, 0.7, 0.8, 0.6, 0.9, 0.8, 0.7, 0.9]
    expected = sum_in_order(1.0 - p for p in chances)
    low, high = binomial_range(len(chances), expected / len(chances))
    for dry, verdict in ((high + 1, "more"), (high, "within"), (low, "within")):
        card = SC.contractor_scorecards(_forecasts("Kaba", 0, chances, dry=dry))[0]
        assert card["dry"]["range"] == [low, high]
        assert (card["dry"]["forecast_dry"], card["dry"]["verdict"]) == (dry, verdict)
    if low > 0:
        assert SC.contractor_scorecards(_forecasts("Kaba", 0, chances, dry=low - 1))[0]["dry"]["verdict"] == "fewer"
    # holes with no forecast count as dry holes but not against the forecast
    plain = [_row(90, "Kaba", success=False)]
    card = SC.contractor_scorecards(_forecasts("Kaba", 0, chances, dry=1) + plain)[0]
    assert (card["dry"]["known"], card["dry"]["dry"], card["dry"]["forecast"], card["dry"]["forecast_dry"]) == (
        9, 2, 8, 1)


def test_the_failed_checks_are_those_of_the_stages_the_contractor_works_in():
    items = load_checklists()
    first = {stage: next(i.item_id for i in items if i.checklist == stage)
             for stage in ("procurement", "drilling", "design", "handover")}
    stages = {stage: {"answered": 2, "failed": [first[stage]]} for stage in first}
    boreholes = [_row(1, "Kaba", "A", checklist=stages),
                 _row(2, "Kaba", "B", checklist={"handover": {"answered": 1, "failed": []}})]
    checks = SC.contractor_scorecards(boreholes)[0]["checks"]
    # only the drilling and design stages are the contractor's of the four;
    # the second borehole answered only a handover item, so it was not checked
    assert checks == {"n": 1, "with_failures": 1, "failed": 2,
                      "items": [["drilling", first["drilling"], 1], ["design", first["design"], 1]]}
    config = Config()
    for named in (("handover",), ("handover", "handover")):
        # a stage named twice counts its failures once
        config.ledger.scorecard_stages = named
        assert SC.contractor_scorecards(boreholes, config)[0]["checks"] == {
            "n": 2, "with_failures": 1, "failed": 1, "items": [["handover", first["handover"], 1]]}
    content = SC.scorecard_content([("A", boreholes[0], None), ("B", boreholes[1], None)])
    failed = next(s for s in content["sections"] if s["key"] == "checks")["tables"][0]["rows"]
    texts = {i.item_id: i.text for i in items}
    assert failed == [["Kaba", "Drilling", texts[first["drilling"]], "1"],
                      ["Kaba", "Design and installation", texts[first["design"]], "1"]]
    intro = next(s for s in content["sections"] if s["key"] == "checks")["paragraphs"][0]
    stages_named = ("in a stage the contractor works in: mobilisation, drilling, design and installation, "
                    "development and completion, and demobilisation.")
    assert stages_named in intro
    # with no stage set, the report says none is counted rather than listing none
    config.ledger.scorecard_stages = ()
    content = SC.scorecard_content([("A", boreholes[0], None)], config=config)
    section = next(s for s in content["sections"] if s["key"] == "checks")
    assert (section["paragraphs"], section["tables"]) == ([phrase("scorecards.checks_no_stages")], [])
    assert phrase("scorecards.checks_no_stages") in content["sections"][-1]["bullets"]


def test_time_is_the_logs_completion_date_against_the_contracts():
    rows = [_row(k, "Kaba", contract=True, variations_signed=0, variations_unsigned=0, variation_usd=0.0,
                 completion_due=due, completion_date=done)
            for k, (due, done) in enumerate([("2018-05-10", "13th May, 2018"), ("2018-05-10", "2018-05-20"),
                                             ("2018-05-10", "May 1, 2018"), ("2018-05-10", "05/06/2018"),
                                             ("10 May 2018", "2018-05-20"), ("", "2018-05-20")])]
    time = SC.contractor_scorecards(rows)[0]["time"]
    # 3 and 10 days late, 9 early; two dates not read, one row with no due date
    assert time == {"n": 3, "late": 2, "days_late": 13, "most_days": 10, "unread": 2}
    cell = SC.scorecard_content([("x", r, None) for r in rows])["sections"][0]["tables"][0]["rows"][0][5]
    assert cell == "2 of 3 finished late, 13 days in all, at most 10; 2 dates not read"


def test_metres_claimed_beyond_the_reconciliation_limit_are_counted():
    rows = [_row(k, "Kaba", logged_m=lm, claimed_m=cm)
            for k, (lm, cm) in enumerate([(60.0, 64.0), (60.0, 63.0), (60.0, 52.5), (None, 70.0)])]
    metres = SC.contractor_scorecards(rows)[0]["metres"]
    assert metres == {"n": 3, "logged_m": 180.0, "claimed_m": 179.5, "over_m": -0.5, "beyond": 1}
    cell = SC.scorecard_content([("x", r, None) for r in rows])["sections"][0]["tables"][0]["rows"][0][2]
    assert cell == ("-0.5 m on 3 boreholes (179.5 m claimed, 180 m logged); 1 claimed more than 3 m over the "
                    "logs")


def test_the_report_says_there_is_nothing_where_nothing_was_drilled():
    content = SC.scorecard_content([("A", None, L.empty_ledger())], "2026-10-29")
    assert content["summary"] == [phrase("scorecards.summary_none")]
    assert [s["key"] for s in content["sections"]] == ["method"]
    assert content["rows"][-1] == [phrase("scorecards.row_issued"), "2026-10-29"]
    assert content["references"] and "Supervising Water Well Drilling" in content["references"][0]


def test_the_summary_names_the_boreholes_with_no_contractor_and_the_older_files(timbo):
    older = L.attach_outcome(_survey_point(True), L.completion_outcome(timbo, None, Config(), contractor=""))
    unnamed = _row(1, "")
    content = SC.scorecard_content([("old", None, older), ("x", unnamed, None)])
    assert content["summary"][:3] == [
        "2 boreholes drilled by 1 contractor, from 2 project files.",
        phrase("scorecards.summary_unnamed", n=1), phrase("scorecards.summary_ledger_only", n=1)]
    assert phrase_table("scorecards.dry_verdict")["too_few"] in content["sections"][2]["tables"][0]["rows"][0]
    # where no borehole names one, the summary counts no contractors
    alone = SC.scorecard_content([("x", unnamed, None)])["summary"]
    assert alone[:2] == ["1 borehole drilled, from 1 project file.",
                         ("1 borehole names no contractor in the site details or on the drilling log, so it is set "
                          "out apart and not ranked.")]


def test_the_report_is_written_as_a_word_document(tmp_path, timbo):
    docx = pytest.importorskip("docx")
    from groundwater.reporting.scorecards import build_scorecard_report

    record = SC.works_record(_site(), timbo, None, None, {"drl-daily-drilling-log": "no"},
                             {"logged_m": 70.0, "claimed_m": 75.0}, CONTRACT)
    path = build_scorecard_report([("Dr Timbo", record, None)], tmp_path / "Contractor_Scorecards.docx",
                                  "2026-10-29")
    text = "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    cells = [c.text for t in docx.Document(str(path)).tables for row in t.rows for c in row.cells]
    assert phrase("scorecards.title") in text and phrase("scorecards.method_heading") in text
    assert "WiNGiN Heavy Duty Machines Co. Ltd" in cells
    assert "+5 m on 1 borehole (75 m claimed, 70 m logged); 1 claimed more than 3 m over the logs" in cells
    # byte for byte on a second build
    again = build_scorecard_report([("Dr Timbo", record, None)], tmp_path / "again.docx", "2026-10-29")
    assert Path(path).read_bytes() == Path(again).read_bytes()


# ----------------------------------------------------- the project file

def test_the_works_record_and_the_contract_ride_in_the_project_file(timbo):
    record = SC.works_record(_site(), timbo, None, None, {"drl-daily-drilling-log": "no"}, None, CONTRACT)
    lines = [{"code": "DRL", "item": "Drilling", "unit": "m", "quantity": np.float64(60.0), "rate_usd": 40.0,
              "stage": "", "category": ""}]
    measured = [{"Code": "DRL", "Item": "Drilling", "Unit": "m", "Contract": 60.0,
                 "Measured to date": np.float64(float("nan"))}]
    variations = [{"Ref": "VO-1", "Date": "", "Code": "DRL", "Quantity change": np.int64(10),
                   "New rate (USD)": None, "Reason": "", "Authorised by": "A. Kamara"}]
    session = {"meta_community": "Dr Timbo", "proc_ref": "WSD/2018/1", "proc_due": "2018-05-10",
               "proc_contract_lines": lines, "proc_measured": measured, "proc_variations": variations,
               "works_record": record, "proc_measure_editor": {"edited_rows": {}}}
    saved = serialize_project(session, "0.3.0")
    payload = yaml.safe_load(saved)
    assert payload["works"] == record
    assert payload["procurement"] == {
        "lines": [dict(lines[0], quantity=60.0)],
        "measured": [dict(measured[0], **{"Measured to date": None})],
        "variations": [dict(variations[0], **{"Quantity change": 10})]}
    # the scalars ride in the state; the editors' working copies do not
    assert payload["state"]["proc_ref"] == "WSD/2018/1" and payload["state"]["proc_due"] == "2018-05-10"
    assert "proc_measure_editor" not in payload["state"]
    back = deserialize_project(saved)
    assert back["works"] == record and back["procurement"] == payload["procurement"]
    assert back["proc_ref"] == "WSD/2018/1"
    # the browser's file carries the record at the same place, as JSON
    browser = json.dumps({"format": "groundwater-toolkit-project", "schema": 2, "summary": {},
                          "ledger": {"drilled": None, "entries": []}, "works": record, "state": {}})
    assert deserialize_project(browser.encode("utf-8"))["works"] == record


def test_a_file_without_them_loads_as_it_did_and_a_load_drops_the_outgoing_contract():
    saved = serialize_project({"meta_community": "Rokel"}, "0.3.0")
    payload = yaml.safe_load(saved)
    assert "works" not in payload and "procurement" not in payload
    back = deserialize_project(saved)
    assert "works" not in back and "procurement" not in back
    hand = yaml.safe_load(saved)
    hand.update(works={"id": ""}, procurement={"lines": "none"})
    back = deserialize_project(yaml.safe_dump(hand).encode("utf-8"))
    assert "works" not in back and "procurement" not in back
    outgoing = {"proc_contract_lines": [{}], "proc_measured": [], "proc_variations": [], "proc_ref": "X",
                "proc_due": "2018-05-10", "proc_measure_editor": {}, "meta_community": "Rokel"}
    assert set(stale_on_load(outgoing)) == set(outgoing) - {"meta_community"}
    assert "proc_due".startswith(PERSIST_PREFIXES)


def test_the_scorecard_settings_are_in_the_defaults():
    config = Config()
    assert config.ledger.scorecard_min_boreholes == 5
    assert config.ledger.scorecard_stages == ("mobilisation", "drilling", "design", "development",
                                              "demobilisation")
    stages = {item.checklist for item in load_checklists()}
    assert set(config.ledger.scorecard_stages) <= stages


# ------------------------------------------- the browser's engine, held to it

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
for await (const line of createInterface({ input: process.stdin })) {
  const r = JSON.parse(line);
  let answer;
  try {
    const cfg = C.withConfig({ ledger: r.settings });
    const records = r.projects.map((p) => C.worksRecord(p.site, p.log, p.analysis, p.ledger, p.answers, p.metres,
      p.procurement, cfg));
    const files = r.projects.map((p, i) => [p.label, p.on_file ? records[i] : null, p.ledger_file]);
    const boreholes = C.scorecardBoreholes(files);
    answer = { ok: { records, clean: records.map((w) => C.cleanWorks(w)), boreholes,
      cards: C.contractorScorecards(boreholes, cfg), content: C.scorecardContent(files, r.issued, cfg),
      days: r.days.map((d) => C.writtenDay(d)) } };
  } catch (e) {
    answer = { threw: String(e && e.stack || e) };
  }
  process.stdout.write(JSON.stringify(answer) + '\n');
}
"""


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path_factory.mktemp("scorecards") / "scorecards.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    process = subprocess.Popen([node, str(driver), str(JS)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8")

    def ask(request: dict) -> dict:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        assert line, "the Node driver stopped; its error is above"
        answer = json.loads(line)
        assert "threw" not in answer, answer["threw"]
        return answer["ok"]

    yield ask
    assert process.stdin is not None
    process.stdin.close()
    process.wait(timeout=60)


_CONTRACTORS = ["WiNGiN Heavy Duty", "", " Kaba\tDrilling ", "Kaba Drilling", "Ñdoye", "\U0001d4b5 Drill", "ｱ Drill",
                "__proto__", "constructor"]
_STATUSES = ["Successful", "Dry", "Dry hole", "", "Abandoned", "In progress"]
_DATES = ["13th May, 2018", "2018-05-20", "May 9, 2018", "05/06/2018", "", "2018-05-13 08:00", "31 Feb 2018",
          "2018-06-02"]
_DUES = ["2018-05-10", "", " 2018-05-25 ", "10/05/2018", "2018-02-30", 20180510.0, None]


def _project(rng, k: int, items: list, skew: str = "") -> dict:
    """One project as an app holds it, drawn: its site details, log, test,
    ledger, checklist answers, metres and contract. ``skew`` "dry" draws
    holes forecast to succeed that the driller recorded dry, "wet" holes
    forecast to fail that he recorded successful, each a forecast of its
    own drilled by one contractor."""
    ok = rng.random() < 0.85
    log = None if rng.random() < 0.15 else {
        "borehole_ref": f"BH-{k % 7}", "total_depth_m": float(rng.choice([30.0, 45.0, 60.0])),
        "intervals": [{"top_m": 0.0, "bottom_m": 10.0, "description": "Laterite"},
                      {"top_m": 10.0, "bottom_m": 30.0, "description": "Weathered granite"},
                      {"top_m": 30.0, "bottom_m": 45.0, "description": "Fresh granite"}],
        "water_strikes_m": [], "status": {"dry": "Dry", "wet": "Successful"}.get(
            skew, _STATUSES[int(rng.integers(0, len(_STATUSES)))]),
        "completion_date": _DATES[int(rng.integers(0, len(_DATES)))],
        "site": {"easting": None if rng.random() < 0.2 else round(float(rng.uniform(708900, 709100)), 1),
                 "northing": round(float(rng.uniform(926300, 926450)), 1), "utm_zone": 28,
                 "contractor": "Kaba Drilling" if skew else _CONTRACTORS[int(rng.integers(0, len(_CONTRACTORS)))]}}
    analysis = None if skew or rng.random() < 0.5 else {
        "yield_recommendation": {"safe_yield_m3_per_h": round(float(rng.uniform(0.1, 4.0)), 4),
                                 "confidence": "indicative"}, "spread": None}
    chance = round(float(rng.uniform(*{"dry": (0.8, 0.95), "wet": (0.05, 0.2)}.get(skew, (0.05, 0.95)))), 3)
    ledger = {"drilled": None, "entries": []}
    if skew or rng.random() < 0.7:
        ledger["entries"].append({
            # the same point in several files, but for the skewed ones
            "id": f"sk{k:03d}" if skew else f"pt{k % 11:03d}",
            "before_outcome": bool(skew) or bool(rng.random() < 0.8), "recorded_on": "2018-04-01",
            "toolkit": "0.3.0",
            "point": {"sounding_id": "VES 1", "community": "C", "district": "D", "easting": None, "northing": None,
                      "utm_zone": None},
            "prediction": {"odds": None if not skew and rng.random() < 0.15
                           else {"probability": chance, "low": 0.2, "high": 0.9}},
            "outcome": None if log is not None or rng.random() < 0.5 else {
                "success": bool(rng.random() < 0.6), "success_basis": "tested", "contractor": "Kept Drilling",
                "borehole_ref": "BH-kept", "completion_date": "2018-05-01"}})
    answers = {item.item_id: ["yes", "no", "na", "pending", "yes"][int(rng.integers(0, 5))]
               for item in items if rng.random() < 0.25}
    metres = {"logged_m": None if rng.random() < 0.3 else round(float(rng.uniform(40, 80)), 3),
              "claimed_m": None if rng.random() < 0.3 else round(float(rng.uniform(40, 85)), 3)}
    procurement = None if rng.random() < 0.3 else {
        "lines": [{"code": "DRL", "item": "Drilling", "unit": "m", "quantity": 60.0, "rate_usd": 40.0},
                  {"code": "CAS", "item": "Casing", "unit": "m", "quantity": 60.0, "rate_usd": 12.5}],
        "variations": [{"ref": f"VO-{j}", "code": rng.choice(["DRL", "CAS", "NEW", ""]),
                        "quantity_delta": round(float(rng.uniform(-10, 20)), 1),
                        "rate_usd": None if rng.random() < 0.7 else round(float(rng.uniform(10, 50)), 2),
                        "authorised_by": rng.choice(["A. Kamara", "", " \t", "B.  Sesay"])}
                       for j in range(int(rng.integers(0, 4)))],
        "due": _DUES[int(rng.integers(0, len(_DUES)))]}
    site = {"contractor": "" if skew else rng.choice(["", "", "  Sierra   Drilling "]),
            "community": "C" if ok else "", "district": "D"}
    return {"label": f"P{k}", "site": site, "log": log, "analysis": analysis, "ledger": ledger, "answers": answers,
            "metres": metres, "procurement": procurement, "on_file": bool(rng.random() < 0.85),
            "ledger_file": ledger if rng.random() < 0.9 else None}


def _case(seed: int, items: list) -> dict:
    rng = np.random.default_rng(seed)
    skew = {3: "dry", 4: "wet"}.get(seed % 5, "")
    projects = [_project(rng, k, items, skew if k % 3 else "") for k in range(int(rng.integers(1, 30)))]
    if seed % 3 == 0:
        # a project that records nothing a scorecard reads
        projects.append({"label": "empty", "site": {"contractor": "Kaba"}, "log": None, "analysis": None,
                         "ledger": {"drilled": None, "entries": []}, "answers": {"drl-daily-drilling-log": "na"},
                         "metres": {"logged_m": None, "claimed_m": 61.0 if seed % 2 else None},
                         "procurement": None, "on_file": True, "ledger_file": None})
    settings = [{}, {"scorecard_min_boreholes": 2},
                {"scorecard_min_boreholes": 1, "scorecard_stages": ["drilling", "procurement", "handover", "drilling"]},
                {"scorecard_stages": []}, {"scorecard_min_boreholes": 0}][seed % 5]
    return {"projects": projects, "settings": settings, "issued": ["", " 2026-10-29 "][seed % 2],
            "days": _DATES + _DUES}


def _python(case: dict) -> dict:
    config = Config()
    for key, value in case["settings"].items():
        setattr(config.ledger, key, tuple(value) if isinstance(value, list) else value)
    records = [SC.works_record(ns(p["site"]), ns(p["log"]), ns(p["analysis"]), p["ledger"], p["answers"],
                               p["metres"], p["procurement"], config) for p in case["projects"]]
    files = [(p["label"], records[i] if p["on_file"] else None, p["ledger_file"])
             for i, p in enumerate(case["projects"])]
    boreholes = SC.scorecard_boreholes(files)
    return {"records": records, "clean": [SC.clean_works(w) for w in records], "boreholes": boreholes,
            "cards": SC.contractor_scorecards(boreholes, config),
            "content": SC.scorecard_content(files, case["issued"], config),
            "days": [SC.written_day(d) for d in case["days"]]}


def _plain(value):
    """Tuples as the lists JSON brings back."""
    return json.loads(json.dumps(value))


SEEDS = range(40)


@pytest.fixture(scope="module")
def items():
    return load_checklists()


@pytest.mark.parametrize("seed", SEEDS)
def test_the_browser_keeps_the_same_scorecards(browser, items, seed):
    case = _case(seed, items)
    assert browser(case) == _plain(_python(case))


def test_the_seeded_cases_reach_every_rule(items):
    told = [_python(_case(seed, items)) for seed in SEEDS]
    cards = [c for t in told for c in t["cards"]]
    assert {c["dry"]["verdict"] for c in cards} == {"too_few", "within", "more", "fewer"}
    assert {c["unranked"] for c in cards} == {None, "too_few", "no_contractor"}
    assert any(c["rank"] and c["rank"] > 1 for c in cards)
    assert any(c["time"]["late"] for c in cards) and any(c["time"]["unread"] for c in cards)
    assert any(c["metres"]["beyond"] for c in cards) and any(c["variations"]["unsigned"] for c in cards)
    assert any(c["checks"]["items"] for c in cards)
    sources = {b["source"] for t in told for b in t["boreholes"]}
    assert sources == {"works", "ledger"}
    assert any(r is None for t in told for r in t["records"])
    assert any(r and r["forecast"] is not None for t in told for r in t["records"])

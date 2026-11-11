"""Contractor scorecards (PLAN.md step 6.3): the "scorecards" entry of
``reference.json``.
"""

from __future__ import annotations

from groundwater.config import Config
from groundwater.ingestion import read_drilling_workbook

from .calibration import _pick
from .common import _ns, REPO


# ----------------------------------------- contractor scorecards (step 6.3)

#: Contractors as a log or the site details name them: one name in two
#: spellings, an accent, letters beyond the Basic Multilingual Plane and a
#: full-width one, names that are an object's keys in JavaScript, and none.
SCORECARD_CONTRACTORS = ["WiNGiN Heavy Duty", "", " Kaba\tDrilling ", "Kaba Drilling", "Ñdoye Drilling",
                         "\U0001d4b5 Drill", "ｱ Drill", "__proto__", "constructor"]
SCORECARD_STATUSES = ["Successful", "Dry", "Dry hole", "", "Abandoned", "In progress"]
#: Completion dates as logs write them, read and not.
SCORECARD_DATES = ["13th May, 2018", "2018-05-20", "May 9, 2018", "05/06/2018", "", "2018-05-13 08:00",
                   "31 Feb 2018", "2018-06-02", "3 Sept 2018", "13TH of MAY 2018"]
#: Contract completion dates as typed, read and not; a number in a
#: hand-edited file is not read.
SCORECARD_DUES = ["2018-05-10", "", " 2018-05-25 ", "10/05/2018", "2018-02-30", 20180510.0, None]


def _scorecard_project(rng, k: int, items: list, skew: str) -> dict:
    """One project as an app holds it, drawn by random() alone: its site
    details, log, test, ledger, checklist answers, the drilled metres
    reconciliation and the contract. ``skew`` draws holes forecast to
    succeed that the driller recorded dry ("dry"), or forecast to fail that
    he recorded successful ("wet"), each a forecast of its own drilled by
    one contractor."""
    log = None if rng.random() < 0.15 else {
        "borehole_ref": f"BH-{k % 7}", "total_depth_m": _pick(rng, [30.0, 45.0, 60.0]),
        "intervals": [{"top_m": 0.0, "bottom_m": 10.0, "description": "Laterite"},
                      {"top_m": 10.0, "bottom_m": 30.0, "description": "Weathered granite"},
                      {"top_m": 30.0, "bottom_m": 45.0, "description": "Fresh granite"}],
        "water_strikes_m": [], "status": {"dry": "Dry", "wet": "Successful"}.get(
            skew, _pick(rng, SCORECARD_STATUSES)),
        "completion_date": _pick(rng, SCORECARD_DATES),
        "site": {"easting": None if rng.random() < 0.2 else round(708900.0 + 200.0 * rng.random(), 1),
                 "northing": round(926300.0 + 150.0 * rng.random(), 1), "utm_zone": 28,
                 "contractor": "Kaba Drilling" if skew else _pick(rng, SCORECARD_CONTRACTORS)}}
    analysis = None if skew or rng.random() < 0.5 else {
        "yield_recommendation": {"safe_yield_m3_per_h": round(0.1 + 3.9 * rng.random(), 4),
                                 "confidence": "indicative"}, "spread": None}
    low, high = {"dry": (0.8, 0.95), "wet": (0.05, 0.2)}.get(skew, (0.05, 0.95))
    chance = round(low + (high - low) * rng.random(), 3)
    ledger = {"drilled": None, "entries": []}
    if skew or rng.random() < 0.7:
        ledger["entries"].append({
            # the same point in several files, but for the skewed ones
            "id": f"sk{k:03d}" if skew else f"pt{k % 11:03d}",
            "before_outcome": bool(skew) or rng.random() < 0.8, "recorded_on": "2018-04-01", "toolkit": "0.3.0",
            "point": {"sounding_id": "VES 1", "community": "Rokel", "district": "Port Loko", "easting": None,
                      "northing": None, "utm_zone": None},
            "prediction": {"odds": None if not skew and rng.random() < 0.15
                           else {"probability": chance, "low": 0.2, "high": 0.9}},
            # a file whose log was not carried with it keeps its outcome
            "outcome": None if log is not None or rng.random() < 0.5 else {
                "success": rng.random() < 0.6, "success_basis": "tested", "contractor": "Kept Drilling",
                "borehole_ref": "BH-kept", "completion_date": "2018-05-01"}})
    answers = {item.item_id: _pick(rng, ["yes", "no", "na", "pending", "yes"]) for item in items
               if rng.random() < 0.08}
    metres = {"logged_m": None if rng.random() < 0.3 else round(40.0 + 40.0 * rng.random(), 3),
              "claimed_m": None if rng.random() < 0.3 else round(40.0 + 45.0 * rng.random(), 3)}
    procurement = None if rng.random() < 0.3 else {
        "lines": [{"code": "DRL", "item": "Drilling", "unit": "m", "quantity": 60.0, "rate_usd": 40.0},
                  {"code": "CAS", "item": "Casing", "unit": "m", "quantity": 60.0, "rate_usd": 12.5}],
        "variations": [{"ref": f"VO-{j}", "code": _pick(rng, ["DRL", "CAS", "NEW", ""]),
                        "quantity_delta": round(-10.0 + 30.0 * rng.random(), 1),
                        "rate_usd": None if rng.random() < 0.7 else round(10.0 + 40.0 * rng.random(), 2),
                        "authorised_by": _pick(rng, ["A. Kamara", "", " \t", "B.  Sesay"])}
                       for j in range(int(rng.random() * 4))],
        "due": _pick(rng, SCORECARD_DUES)}
    site = {"contractor": "" if skew else _pick(rng, ["", "", "  Sierra   Drilling "]),
            "community": "Rokel" if rng.random() < 0.85 else "", "district": "Port Loko"}
    return {"label": f"Project {k}", "site": site, "log": log, "analysis": analysis, "ledger": ledger,
            "answers": answers, "metres": metres, "procurement": procurement,
            "on_file": rng.random() < 0.85, "ledger_file": ledger if rng.random() < 0.9 else None}


def _scorecard_portfolio(seed: int, items: list) -> list:
    import random

    rng = random.Random(seed)
    # two portfolios of skewed holes, under the settings with the smaller minimums
    skew = {5: "dry", 6: "wet"}.get(seed, "")
    count = 12 if skew else 1 + int(rng.random() * 12)
    projects = [_scorecard_project(rng, k, items, skew if k % 3 else "") for k in range(count)]
    if seed % 3 == 0:
        # a project that records nothing a scorecard reads
        projects.append({"label": "Empty", "site": {"contractor": "Kaba"}, "log": None, "analysis": None,
                         "ledger": {"drilled": None, "entries": []}, "answers": {"drl-daily-drilling-log": "na"},
                         "metres": {"logged_m": None, "claimed_m": None}, "procurement": None, "on_file": True,
                         "ledger_file": None})
    return projects


def _scorecard_files(projects: list, records: list) -> list:
    return [[p["label"], records[i] if p["on_file"] else None, p["ledger_file"]] for i, p in enumerate(projects)]


#: Works records as a hand might edit them.
SCORECARD_HAND = [
    None, "works", {"id": ""}, {"id": 7},
    {"id": "a", "drilled": "yes", "success": 1, "success_basis": "tested", "forecast": 1.5, "logged_m": -3,
     "claimed_m": "70", "contractor": " A \t B ", "checklist": {
         "drilling": {"answered": 1, "failed": ["x", "y"]}, "design": {"answered": 2, "failed": ["x", "x", 3, ""]},
         "Design": {"answered": 1, "failed": []}, "10": {"answered": 1, "failed": []},
         "development": {"answered": 0, "failed": []}, "demobilisation": {"answered": True},
         "mobilisation": {"answered": 2.0, "failed": "x"}, "handover": []}},
    {"id": "b", "drilled": True, "success": False, "success_basis": "made up", "contract": True,
     "variations_signed": 2, "variations_unsigned": 0, "variation_usd": 120.456, "completion_due": " 2018-05-01 "},
    {"id": "c", "contract": True, "variations_signed": -1, "variations_unsigned": 0, "variation_usd": 1.0,
     "completion_due": "2018-05-01"},
    {"id": "d", "contract": False, "variations_signed": 1, "variations_unsigned": 1, "variation_usd": 1.0,
     "completion_due": "2018-05-01"},
    {"id": "e", "contract": True, "variations_signed": 1.0, "variations_unsigned": 0.5, "variation_usd": 1.0},
    {"id": "f", "contract": True, "variations_signed": True, "variations_unsigned": 0, "variation_usd": 1.0},
    {"id": "g", "forecast": 0.0, "success": True, "success_basis": "recorded_success", "drilled": True,
     "checklist": "none", "logged_m": 0, "claimed_m": 1e3},
    {"id": "h", "contract": True, "variations_signed": 0, "variations_unsigned": 0, "variation_usd": 0.0,
     "completion_due": 20180510.0, "completion_date": 43233.0},
]

#: Dates as logs write them, beyond the ones the cases draw.
SCORECARD_DAYS = SCORECARD_DATES + SCORECARD_DUES + [
    "13 May 2018", "13th of May 2018", "May. 13th, 2018", "13-May-2018", "3 Sept 2019", "Sep 3, 2019",
    "29 Feb 2019", "29 Feb 2020", "31 April 2018", "13 Mayo 2018", "0000-01-01", "2018-13-01", "13 May",
    "25/04/2018", "13.05.2018", "2018-05-13T08:30:00", "2018-05-13 08:30:00", "2018-05-13 8:30",
    " 13 May 2018 ", "13 Kay 2018", "13 ſt May 2018", "Mayday 13 2018", 43233.0, 20180513]


def scorecards_reference() -> dict:
    """Contractor scorecards (PLAN.md step 6.3): works records made from
    drawn projects of every kind (logs, tests, ledgers kept and paired,
    checklist answers, metres, contracts with signed and unsigned variation
    orders) and read back clean; pooled with the ledgers of files saved
    before the record, the scorecards and the report's content, under the
    default settings and others; hand-edited records; dates as logs write
    them; Dr Timbo's own log, as each engine reads the workbook; and a
    Streamlit project file carrying a record, as the browser's YAML reader
    reads it."""
    from groundwater import scorecards as SC
    from groundwater.project_io import deserialize_project, serialize_project
    from groundwater.supervision import load_checklists

    items = load_checklists()
    settings = [{}, {"scorecard_min_boreholes": 2},
                {"scorecard_min_boreholes": 1, "scorecard_stages": ["drilling", "procurement", "handover", "drilling"]},
                {"scorecard_stages": []}]
    cases = []
    for seed in range(9):
        projects = _scorecard_portfolio(seed, items)
        if seed == 8:
            # a portfolio whose boreholes name no contractor anywhere
            for p in projects:
                p["site"]["contractor"] = ""
                if p["log"] is not None:
                    p["log"]["site"]["contractor"] = ""
                for entry in p["ledger"]["entries"]:
                    if entry["outcome"] is not None:
                        entry["outcome"]["contractor"] = ""
        # and a minimum of none, which is taken as one
        over = {"scorecard_min_boreholes": 0} if seed == 4 else settings[seed % 4]
        config = Config()
        for key, value in over.items():
            setattr(config.ledger, key, tuple(value) if isinstance(value, list) else value)
        records = [SC.works_record(_ns(p["site"]), _ns(p["log"]), _ns(p["analysis"]), p["ledger"], p["answers"],
                                   p["metres"], p["procurement"], config) for p in projects]
        files = _scorecard_files(projects, records)
        boreholes = SC.scorecard_boreholes([tuple(f) for f in files])
        issued = "  2026-10-29 " if seed % 2 else ""
        # each record reads back as it was made, which parity holds the
        # browser's to, so the cleaned copies are not written out again
        assert [SC.clean_works(w) for w in records] == records
        cases.append({"projects": projects, "settings": over, "issued": issued, "expect": {
            "records": records, "boreholes": boreholes, "cards": SC.contractor_scorecards(boreholes, config),
            "content": SC.scorecard_content([tuple(f) for f in files], issued, config)}})

    timbo_log = read_drilling_workbook(REPO / "examples" / "data" / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    timbo_inputs = {
        "site": {"contractor": "", "community": "Dr Timbo", "district": "Port Loko"},
        "answers": {"drl-daily-drilling-log": "no", "dev-plumb-test-passed": "yes", "dem-cleared-waste-removed": "no"},
        "metres": {"logged_m": 70.0, "claimed_m": 74.5},
        "procurement": {"lines": [{"code": "DRL", "item": "Drilling", "unit": "m", "quantity": 60.0,
                                   "rate_usd": 40.0}],
                        "variations": [{"ref": "VO-1", "code": "DRL", "quantity_delta": 10.0,
                                        "authorised_by": "A. Kamara"}], "due": "2018-05-10"}}
    timbo = SC.works_record(_ns(timbo_inputs["site"]), timbo_log, None, None, timbo_inputs["answers"],
                            timbo_inputs["metres"], timbo_inputs["procurement"])
    timbo_files = [("Dr Timbo", timbo, None)]
    # Dr Timbo's borehole saved before any prediction was recorded, and again
    # once predictions at two points with no position leave it paired with
    # no point: one identifier, with no ledger identity in it, so one borehole
    from groundwater import ledger as L

    unpaired_survey = L.survey_predictions(
        [_ns({"sounding_id": name, "depth_to_basement_m": 20.0, "basement_not_resolved": False,
              "investigation_depth_m": 60.0, "water_zones": [[8.0, 20.0]], "aquifer_thickness_m": 12.0,
              "max_drilling_depth_m": 35.0, "drilling_depth_capped": False, "fit_error_percent": 3.0,
              "site_easting": None, "site_northing": None, "layers": []}) for name in ("VES 1", "VES 2")],
        None, None, _ns({"community": "Dr Timbo", "district": "Port Loko", "utm_zone": 28}))
    unpaired_ledgers = [L.empty_ledger(),
                        L.record_predictions(L.empty_ledger(), unpaired_survey, "2018-06-01", True, "0.3.0")[0]]
    unpaired_records = [SC.works_record(_ns(timbo_inputs["site"]), timbo_log, None, ledger)
                        for ledger in unpaired_ledgers]
    unpaired_files = [(f"save {k + 1}", record, ledger)
                      for k, (record, ledger) in enumerate(zip(unpaired_records, unpaired_ledgers, strict=True))]

    saved = serialize_project({"meta_community": "Dr Timbo", "works_record": timbo,
                               "proc_contract_lines": timbo_inputs["procurement"]["lines"]}, "0.3.0")
    return {
        "cases": cases,
        "hand": [{"raw": raw, "expect": SC.clean_works(raw)} for raw in SCORECARD_HAND],
        "days": [{"text": text, "expect": SC.written_day(text)} for text in SCORECARD_DAYS],
        "timbo": {"inputs": timbo_inputs, "record": timbo,
                  "content": SC.scorecard_content(timbo_files, "2026-10-29")},
        "unpaired": {"ledgers": unpaired_ledgers, "records": unpaired_records,
                     "boreholes": SC.scorecard_boreholes(unpaired_files)},
        "file": {"yaml": saved.decode("utf-8"), "expect": deserialize_project(saved)["works"]},
    }

"""The ledger of predictions and outcomes (PLAN.md step 5.1)."""

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
from groundwater.config import Config
from groundwater.ingestion import read_drilling_workbook
from groundwater.project_io import (
    PROJECT_SCHEMA,
    RESET_ON_LOAD_KEYS,
    deserialize_project,
    migrate_payload,
    payload_schema,
    serialize_project,
)
from groundwater.text import phrase, phrase_table

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


def _interp(**fields):
    base = {"sounding_id": "VES 1", "depth_to_basement_m": 28.37, "basement_not_resolved": False,
            "investigation_depth_m": 60.0, "water_zones": [(8.0, 20.0), (24.0, 28.0)],
            "aquifer_thickness_m": 16.0, "max_drilling_depth_m": 35.0, "drilling_depth_capped": False,
            "fit_error_percent": 3.456, "site_easting": 708958.4, "site_northing": 926355.5}
    base.update(fields)
    return ns(base)


def _range(**fields):
    base = {"sounding_id": "VES 1", "n_samples": 4000,
            "basement_m": {"p10": 22.14, "p50": 28.25, "p90": 34.05},
            "basement_unresolved": 0.0, "weathered_m": {"p10": 14.0, "p50": 16.05, "p90": 19.25},
            "investigation_depth_m": 60.0,
            "drilling_depth_quantiles_m": [30.0 + k for k in range(21)]}
    base.update(fields)
    return ns(base)


ODDS = ns({"probability": 0.61234, "low": 0.3875, "high": 0.7805, "prior": 0.55, "effective_n": 10.0,
           "status": "provisional", "matched": "class", "bgs_code": "B-L", "glg": "pCm",
           "success_yield_m3_per_h": 1.0, "calibration": "provisional, adopted by no named person"})

SITE = ns({"community": "Rokel", "district": "Port Loko", "utm_zone": 28})


def _log(**fields):
    base = {"borehole_ref": "BH-7", "total_depth_m": 45.0,
            "intervals": [{"top_m": 0.0, "bottom_m": 6.0, "description": "Laterite"},
                          {"top_m": 6.0, "bottom_m": 30.0, "description": "Saprolite"},
                          {"top_m": 30.0, "bottom_m": 45.0, "description": "Fresh granite"}],
            "water_strikes_m": [12.0, 26.0], "status": "Successful", "completion_date": "2026-11-02",
            "site": {"easting": 708962.0, "northing": 926351.0, "utm_zone": 28}}
    base.update(fields)
    return ns(base)


def _analysis(safe, low=None, high=None, holds=True, boot=True):
    spread = None
    if low is not None:
        spread = {"bootstrap": {"p10": 1.0} if boot else None, "safe_yield_low_m3_per_h": low,
                  "safe_yield_high_m3_per_h": high, "holds_at_dry_season": holds}
    return ns({"yield_recommendation": {"safe_yield_m3_per_h": safe, "confidence": "established"},
               "spread": spread})


def _survey(*interps):
    return L.survey_predictions(list(interps), None, None, SITE)


# --------------------------------------------------------------- prediction

def test_a_prediction_is_the_points_numbers_with_its_bands_and_odds():
    p = L.point_prediction(_interp(), _range(), ODDS)
    assert p["depth_to_basement_m"] == 28.4 and p["basement_resolved"]
    assert p["basement_band_m"] == [22.1, 28.2, 34.0] and p["weathered_band_m"] == [14.0, 16.1, 19.2]
    assert p["water_zones_m"] == [[8.0, 20.0], [24.0, 28.0]] and p["water_bearing_m"] == 16.0
    assert p["drilling_depth_m"] == 35.0 and not p["drilling_depth_minimum"]
    assert p["range_sampled"] and p["basement_unresolved_share"] == 0.0
    assert p["odds"]["probability"] == 0.612 and p["odds"]["calibration"].startswith("provisional")
    assert p["fit_error_percent"] == 3.46


def test_the_drilling_depth_band_is_the_one_the_reports_print():
    from groundwater.decisions import depth_decision

    r = _range()
    p = L.point_prediction(_interp(), r, None)
    printed = depth_decision(_interp(), r, Config()).band
    assert p["drilling_depth_band_m"] == [35.0, 50.0]
    assert "35" in printed and "50" in printed


def test_without_a_range_there_is_no_band_and_the_minimum_is_marked():
    p = L.point_prediction(_interp(depth_to_basement_m=None, basement_not_resolved=True,
                                   drilling_depth_capped=True), None, None)
    assert not p["range_sampled"] and p["odds"] is None
    assert p["basement_band_m"] is p["weathered_band_m"] is p["drilling_depth_band_m"] is None
    assert p["drilling_depth_minimum"] and not p["basement_resolved"]


def test_a_band_found_by_too_few_models_is_not_quoted():
    p = L.point_prediction(_interp(), _range(basement_unresolved=0.95), None)
    assert p["basement_band_m"] is None and p["basement_unresolved_share"] == 0.95


def test_the_survey_names_each_point_by_its_place_and_position():
    out = L.survey_predictions([_interp(), _interp(sounding_id="VES 2", site_easting=None)],
                               [_range()], [ODDS], SITE)
    assert [o["point"]["sounding_id"] for o in out] == ["VES 1", "VES 2"]
    assert out[0]["point"] == {"sounding_id": "VES 1", "easting": 708958.4, "northing": 926355.5,
                               "utm_zone": 28, "community": "Rokel", "district": "Port Loko"}
    # the lists go with the points by position; a short list leaves the rest bare
    assert out[0]["prediction"]["range_sampled"] and not out[1]["prediction"]["range_sampled"]
    assert out[1]["point"]["easting"] is None


def test_a_point_id_holds_to_the_metre_and_to_the_place():
    a = L.point_id("VES 1", 708958.4, 926355.5, 28, "Rokel", "Port Loko")
    assert a == L.point_id("VES 1", 708958.0, 926356.0, 28, "Rokel", "Port Loko")
    assert a != L.point_id("VES 1", 708958.4, 926355.5, 28, "Kuntolo", "Port Loko")
    # two surveys whose soundings share a name and carry no position differ by place
    assert L.point_id("VES 1", None, None, None, "Rokel", "") != L.point_id("VES 1", None, None, None, "Bo", "")
    assert len(a) == 12 and int(a, 16) >= 0


# ------------------------------------------------------------------ outcome

def test_dr_timbos_log_found_basement_at_40_m_and_tested_short():
    log = read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    out = L.completion_outcome(log, _analysis(0.39, 0.35, 0.44))
    assert out["basement_m"] == 40.0 and out["total_depth_m"] == 70.0
    assert out["water_strikes_m"] == [12.0, 30.0]
    assert out["intervals"][0] == [0.0, 5.0, "topsoil"]
    # a fracture zone named inside a row of granite is a band of its own
    assert [49.0, 50.0, "fracture"] in out["intervals"]
    assert out["status_class"] == "successful"
    assert (out["success"], out["success_basis"]) == (False, "tested")
    assert out["safe_yield_band_m3_per_h"] == [0.35, 0.44] and out["holds_at_dry_season"] is True


def test_success_follows_the_test_then_the_drillers_word():
    assert L.completion_outcome(_log(), _analysis(2.3))["success_basis"] == "tested"
    untested = L.completion_outcome(_log(), None)
    assert (untested["success"], untested["success_basis"]) == (True, "recorded_success")
    for status in ("Dry hole", "Abandoned", "Collapsed", "Low yield"):
        failed = L.completion_outcome(_log(status=status), None)
        assert (failed["success"], failed["success_basis"]) == (False, "recorded_failure"), status
        # in the driller's own word, not called dry when it collapsed
        assert status in L.outcome_text(failed)
    for status in ("Drilled", "Awaiting pumping test", ""):
        unknown = L.completion_outcome(_log(status=status), None)
        assert (unknown["success"], unknown["success_basis"]) == (None, None), status
    pending = L.completion_outcome(_log(status=""), _analysis(None))
    assert pending["success"] is None and pending["safe_yield_m3_per_h"] is None


def test_success_is_decided_on_the_yield_as_worked_out_not_as_rounded():
    out = L.completion_outcome(_log(), _analysis(0.9996))
    assert out["safe_yield_m3_per_h"] == 1.0 and out["success"] is False
    assert L.completion_outcome(_log(), _analysis(1.0))["success"] is True
    wider = Config()
    wider.odds.success_yield_m3_per_h = 3.6
    out = L.completion_outcome(_log(), _analysis(2.3), wider)
    assert out["success"] is False and out["success_yield_m3_per_h"] == 3.6


def test_a_hole_that_never_reached_fresh_rock_and_an_open_yield_band():
    out = L.completion_outcome(_log(intervals=[{"top_m": 0.0, "bottom_m": 45.0, "description": "Weathered granite"}]),
                               _analysis(1.4, 0.8, None))
    assert out["basement_m"] is None
    assert out["safe_yield_band_m3_per_h"] == [0.8, None]
    # a spread with no bootstrap gives neither the band nor the season's hold
    out = L.completion_outcome(_log(), _analysis(1.4, 0.8, 2.0, boot=False))
    assert out["safe_yield_band_m3_per_h"] is None and out["holds_at_dry_season"] is None


def test_no_log_is_no_outcome():
    assert L.completion_outcome(None, _analysis(2.0)) is None


# --------------------------------------------------------------- recording

def test_predictions_recorded_before_drilling_are_replaced_until_it_is_drilled():
    first = _survey(_interp(), _interp(sounding_id="VES 2", site_easting=709100.0))
    ledger, kept = L.record_predictions(L.empty_ledger(), first, "2026-10-01", False, "0.3.0")
    assert kept == [] and [e["before_outcome"] for e in ledger["entries"]] == [True, True]
    again = _survey(_interp(depth_to_basement_m=30.0))
    ledger, kept = L.record_predictions(ledger, again, "2026-10-05", False, "0.3.0")
    assert ledger["entries"][0]["prediction"]["depth_to_basement_m"] == 30.0
    assert ledger["entries"][0]["recorded_on"] == "2026-10-05"
    assert len(ledger["entries"]) == 2, "a point no longer surveyed keeps its entry"

    # once the borehole is drilled, a forecast is kept as it was made
    later = _survey(_interp(depth_to_basement_m=40.0), _interp(sounding_id="VES 9", site_easting=709500.0))
    ledger, kept = L.record_predictions(ledger, later, "2026-11-20", True, "0.3.0")
    assert kept == [ledger["entries"][0]["id"]]
    assert ledger["entries"][0]["prediction"]["depth_to_basement_m"] == 30.0
    assert ledger["entries"][2]["before_outcome"] is False, "recorded after drilling, and marked so"


def test_an_entry_keeps_its_outcome_through_a_new_recording():
    ledger, _ = L.record_predictions(L.empty_ledger(), _survey(_interp()), "2026-12-01", True, "0.3.0")
    ledger = L.attach_outcome(ledger, L.completion_outcome(_log(), None))
    assert ledger["entries"][0]["outcome"] is not None
    ledger, kept = L.record_predictions(ledger, _survey(_interp(depth_to_basement_m=12.0)), "2026-12-02", True,
                                        "0.3.0")
    assert kept == [] and ledger["entries"][0]["prediction"]["depth_to_basement_m"] == 12.0
    assert ledger["entries"][0]["outcome"] is not None and ledger["entries"][0]["pairing"] is not None


# ----------------------------------------------------------------- pairing

def _two_points():
    survey = _survey(_interp(), _interp(sounding_id="VES 2", site_easting=709100.0))
    return L.record_predictions(L.empty_ledger(), survey, "2026-10-01", False, "0.3.0")[0]


def test_the_nearest_point_within_the_distance_is_the_one_drilled():
    ledger = _two_points()
    outcome = L.completion_outcome(_log(), None)
    pid, pairing = L.pair_drilled(ledger, outcome)
    assert pid == ledger["entries"][0]["id"]
    assert pairing == {"how": "nearest", "distance_m": pytest.approx(5.8, abs=0.1)}
    close = Config()
    close.ledger.pair_within_m = 4.0
    assert L.pair_drilled(ledger, outcome, close) == (None, None)


def test_a_person_s_choice_comes_first_and_the_only_point_last():
    ledger = _two_points()
    outcome = L.completion_outcome(_log(), None)
    chosen = dict(ledger, drilled=ledger["entries"][1]["id"])
    assert L.pair_drilled(chosen, outcome)[1]["how"] == "chosen"
    unplaced = L.completion_outcome(_log(site={"easting": None, "northing": None, "utm_zone": None}), None)
    assert L.pair_drilled(ledger, unplaced) == (None, None), "never the recommended point by default"
    one = L.record_predictions(L.empty_ledger(), _survey(_interp()), "2026-10-01", False, "0.3.0")[0]
    assert L.pair_drilled(one, unplaced) == (one["entries"][0]["id"], {"how": "only", "distance_m": None})
    assert L.pair_drilled(one, None) == (None, None)


def test_a_point_and_a_log_either_side_of_the_zone_boundary_pair():
    from groundwater.geo import geographic_to_utm

    a, b = geographic_to_utm(8.4103, -12.00012, 28), geographic_to_utm(8.41035, -11.99996, 29)
    survey = L.survey_predictions([_interp(site_easting=a.easting, site_northing=a.northing)], None, None, SITE)
    ledger = L.record_predictions(L.empty_ledger(), survey + _survey(_interp(sounding_id="far", site_easting=700000.0)),
                                  "2026-10-01", False, "0.3.0")[0]
    outcome = L.completion_outcome(_log(site={"easting": b.easting, "northing": b.northing, "utm_zone": 29}), None)
    pid, pairing = L.pair_drilled(ledger, outcome)
    assert pid == ledger["entries"][0]["id"] and pairing["distance_m"] < 25.0


def test_attaching_moves_the_outcome_and_none_keeps_it():
    ledger = _two_points()
    outcome = L.completion_outcome(_log(), None)
    ledger = L.attach_outcome(ledger, outcome)
    assert [e["outcome"] is not None for e in ledger["entries"]] == [True, False]
    ledger = L.attach_outcome(dict(ledger, drilled=ledger["entries"][1]["id"]), outcome)
    assert [e["outcome"] is not None for e in ledger["entries"]] == [False, True]
    assert ledger["entries"][1]["pairing"]["how"] == "chosen"
    kept = L.attach_outcome(ledger, None)
    assert kept == L.clean_ledger(ledger), "a file whose log was not carried keeps what it recorded"
    unplaced = L.completion_outcome(_log(site={"easting": None, "northing": None, "utm_zone": None}), None)
    loose = L.attach_outcome(dict(ledger, drilled=None), unplaced)
    assert all(e["outcome"] is None for e in loose["entries"])


# ---------------------------------------------------------------- cleaning

def test_a_hand_edited_ledger_is_cleaned_not_raised():
    assert L.clean_ledger(None) == L.empty_ledger() == L.clean_ledger("a ledger")
    raw = {"drilled": "gone", "entries": [
        "junk", {"id": 7}, {"id": "a", "point": {}, "prediction": {"depth_to_basement_m": "28",
                                                                  "water_zones_m": [[8, 20], [24]],
                                                                  "basement_band_m": [1, 2]}},
        {"id": "a", "point": {}, "prediction": {"depth_to_basement_m": 3.0}},
        {"id": "b", "point": {"easting": True}, "prediction": {}, "before_outcome": "yes",
         "outcome": {"success": "true", "success_basis": "tested", "status_class": "wet"},
         "pairing": {"how": "guessed"}},
    ]}
    clean = L.clean_ledger(raw)
    assert [e["id"] for e in clean["entries"]] == ["a", "b"] and clean["drilled"] is None
    a, b = clean["entries"]
    assert a["prediction"]["depth_to_basement_m"] is None, "a number written as text is not read"
    assert a["prediction"]["water_zones_m"] == [[8.0, 20.0]] and a["prediction"]["basement_band_m"] is None
    assert b["before_outcome"] is False, "untold timing is taken as after drilling"
    assert b["point"]["easting"] is None and b["pairing"] is None
    assert b["outcome"]["success"] is None and b["outcome"]["success_basis"] is None
    assert b["outcome"]["status_class"] is None
    assert L.clean_ledger(clean) == clean


# ------------------------------------------------------------- comparison

def _entry(prediction, outcome):
    return {"prediction": prediction, "outcome": outcome}


@pytest.mark.parametrize(("found", "total", "want"), [
    (30.0, 45.0, "inside"), (22.1, 45.0, "inside"), (34.0, 45.0, "inside"), (40.0, 45.0, "deeper"),
    (12.0, 45.0, "shallower"), (None, 45.0, "deeper"), (None, 30.0, "unreached_allowed"),
    (None, None, "unreached_allowed"),
])
def test_the_basement_found_against_the_band(found, total, want):
    p = L.point_prediction(_interp(), _range(), None)
    outcome = dict(L.completion_outcome(_log(), None), basement_m=found, total_depth_m=total)
    assert L.basement_check(p, outcome) == want


def test_no_band_and_no_hole_are_said_so():
    p = L.point_prediction(_interp(), None, None)
    assert L.basement_check(p, L.completion_outcome(_log(), None)) == "no_band"
    assert L.basement_check(p, None) is None


def test_the_comparison_rows_before_and_after_drilling():
    p = L.point_prediction(_interp(), _range(), ODDS)
    rows = L.entry_rows(_entry(p, None))
    assert L.entry_header() == ["Quantity", "Predicted", "Found", "How they compare"]
    assert [r[0] for r in rows] == [phrase("ledger.row_basement"), phrase("ledger.row_zones"),
                                    phrase("ledger.row_depth"), phrase("ledger.row_odds")]
    assert {r[2] for r in rows} == {phrase("ledger.not_drilled")} and {r[3] for r in rows} == {""}
    assert rows[0][1] == "28.4 m (22.1 to 34 m over the models that fit)"
    assert rows[1][1] == "Water-bearing at 8-20, 24-28 m"
    assert rows[2][1] == "About 35 m (35 to 50 m over the models that fit)"
    assert rows[3][1] == "61 percent (39 to 78)"
    rows = L.entry_rows(_entry(p, L.completion_outcome(_log(), _analysis(2.3))))
    assert rows[0][2:] == ["30 m", phrase_table("ledger.basement_check")["inside"]]
    assert rows[1][2:] == ["Water struck at 12, 26 m", "2 of 2 strikes in a predicted zone"]
    assert rows[2][2] == "Drilled to 45 m" and rows[3][2] == "Successful: 2.3 m3/h tested"


def test_an_open_zone_and_a_flat_band():
    p = L.point_prediction(_interp(depth_to_basement_m=None, basement_not_resolved=True, water_zones=[(8.0, 40.0)],
                                   max_drilling_depth_m=40.0, drilling_depth_capped=True, investigation_depth_m=40.0),
                           _range(basement_unresolved=1.0, basement_m=None, drilling_depth_quantiles_m=[40.0] * 21,
                                  investigation_depth_m=40.0), None)
    rows = L.entry_rows(_entry(p, None))
    assert rows[0][1] == "Not resolved within 40 m"
    assert rows[1][1] == "Water-bearing at 8-40+ m"
    assert rows[2][1] == "At least 40 m (40 m over every model that fits)"
    assert rows[3][1] == phrase("ledger.odds_none")


# ----------------------------------------------------------------- pooling

def test_a_portfolio_pools_each_entry_once_keeping_the_fullest_copy():
    ledger = _two_points()
    drilled = L.attach_outcome(ledger, L.completion_outcome(_log(), _analysis(0.4)))
    other = L.record_predictions(L.empty_ledger(), L.survey_predictions(
        [_interp(sounding_id="A")], None, None, ns({"community": "Kuntolo", "district": "Bo", "utm_zone": 29})),
        "2026-09-01", False, "0.3.0")[0]
    pooled = L.pool_ledgers([("Rokel", ledger), ("Rokel, drilled", drilled), ("Kuntolo", other),
                             ("Junk", "not a ledger")])
    assert [(e["project"], e["point"]["sounding_id"]) for e in pooled] == [
        ("Rokel, drilled", "VES 1"), ("Rokel", "VES 2"), ("Kuntolo", "A")]
    counts = L.ledger_counts(pooled)
    assert counts == {"points": 3, "projects": 3, "drilled": 1, "forecast": 1, "success": 0, "failure": 1,
                      "unknown": 0}
    header, rows = L.ledger_rows(pooled)
    assert len(header) == 8 and len(rows) == 1
    assert rows[0][:3] == ["Rokel, drilled", "VES 1", phrase("ledger.recorded_before")]
    assert rows[0][-1] == "0.4 m3/h tested, short of the 1 m3/h counted as success"
    assert L.ledger_summary(pooled) == ("3 survey points predicted in 3 projects, 1 of them drilled; 1 of the "
                                        "drilled points had their prediction recorded before drilling.")
    assert L.ledger_summary([]) == phrase("ledger.pool_none")


# ------------------------------------------------------------ project file

def test_the_project_file_carries_the_ledger():
    ledger = L.attach_outcome(_two_points(), L.completion_outcome(_log(), None))
    saved = serialize_project({"meta_community": "Rokel", "prediction_ledger": ledger}, "0.3.0")
    payload = yaml.safe_load(saved)
    # 2 from step 5.1, which brought the ledger; 3 from step 8.1
    assert payload["schema"] == PROJECT_SCHEMA == 3
    assert payload["ledger"] == L.clean_ledger(ledger)
    back = deserialize_project(saved)
    assert back["prediction_ledger"] == L.clean_ledger(ledger)
    # and a project with none still writes the empty one its schema has
    assert yaml.safe_load(serialize_project({}, "0.3.0"))["ledger"] == L.empty_ledger()


def test_a_schema_1_file_migrates_to_an_empty_ledger():
    old = {"groundwater_toolkit_project": "0.2.0", "format": "groundwater-toolkit-project", "schema": 1,
           "state": {"meta_community": "Rokel"}}
    assert payload_schema(old) == 1
    migrated = migrate_payload(old)
    assert migrated["schema"] == 3 and migrated["ledger"] == L.empty_ledger() and migrated["issued"] == []
    assert old["schema"] == 1 and "ledger" not in old, "the file read is not changed"
    back = deserialize_project(yaml.safe_dump(old).encode())
    assert back["prediction_ledger"] == L.empty_ledger() and "warnings" not in back


@pytest.mark.parametrize(("schema", "read"), [(None, 1), (1, 1), (2, 2), (3, 3), ("2", 1), (True, 1),
                                              (0.5, 1), (2.7, 2), (float("inf"), 1)])
def test_the_schema_a_file_was_saved_in(schema, read):
    payload = {} if schema is None else {"schema": schema}
    assert payload_schema(payload) == read


def test_a_file_of_a_later_schema_warns_and_an_unreadable_one_loads():
    later = deserialize_project(b"schema: 4\nledger: {entries: []}\nstate: {meta_community: X}\n")
    assert later["meta_community"] == "X" and "format 4" in later["warnings"][0]
    odd = deserialize_project(b"schema: .inf\nstate: {meta_community: X}\n")
    assert odd["meta_community"] == "X" and "warnings" not in odd


def test_a_browser_file_s_ledger_is_read_by_python():
    ledger = L.attach_outcome(_two_points(), L.completion_outcome(_log(), None))
    payload = {"format": "groundwater-toolkit-project", "schema": 2, "saved": "2026-10-18T00:00:00Z",
               "summary": {"community": "Rokel"}, "ledger": ledger, "state": {"site": {"community": "Rokel"}}}
    assert deserialize_project(json.dumps(payload).encode())["prediction_ledger"] == L.clean_ledger(ledger)
    # one written before schema 2, with its version: 1, has none
    payload = {"format": "groundwater-toolkit-project", "version": 1, "state": {}}
    assert deserialize_project(json.dumps(payload).encode())["prediction_ledger"] == L.empty_ledger()


def test_a_load_drops_the_outgoing_projects_ledger():
    assert "prediction_ledger" in RESET_ON_LOAD_KEYS


def test_the_pairing_distance_is_a_setting(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("ledger:\n  pair_within_m: 20\n", encoding="utf-8")
    assert Config.load(path).ledger.pair_within_m == 20.0
    assert Config().ledger.pair_within_m == 50.0


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
    const cfg = C.withConfig({ odds: { success_yield_m3_per_h: r.success }, ledger: { pair_within_m: r.within } });
    const survey = C.surveyPredictions(r.interps, r.ranges, r.odds, r.site, cfg, r.teams);
    const outcome = C.completionOutcome(r.log, r.analysis, cfg, r.contractor);
    let held = C.recordPredictions(r.held, survey, '2026-10-01', r.known, '0.3.0');
    const kept = held.kept;
    held = C.attachOutcome(Object.assign({}, held.ledger, { drilled: r.drilled }), outcome, cfg);
    const pooled = C.poolLedgers([['A', held], ['B', r.held]]);
    const table = C.ledgerRows(pooled);
    answer = { ok: { survey, outcome, kept, held, rows: held.entries.map((e) => C.entryRows(e)),
      pooled, counts: C.ledgerCounts(pooled), table: [table.header, table.rows],
      clean: C.cleanLedger(r.dirty) } };
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
    driver = tmp_path_factory.mktemp("ledger") / "ledger.mjs"
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


_DESCRIPTIONS = ["Topsoil", "Laterite", "Clayey saprolite", "Sand and gravel", "Weathered granite",
                 "Fresh granite", "Light colour granite, fracture zone 20-22 m", "Gneiss", "Quartz vein",
                 "Fractured rock"]
_STATUSES = ["Successful", "Dry", "Dry hole", "", "Abandoned", "In progress", "Sited", "successful (low yield)"]


def _round(rng, low, high, digits=2):
    return round(float(rng.uniform(low, high)), digits)


def _case(seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(1, 4))
    interps, ranges, odds = [], [], []
    for _ in range(n):
        resolved = bool(rng.random() < 0.6)
        doi = float(rng.choice([30.0, 40.0, 60.0, 80.0]))
        top = _round(rng, 2.0, 10.0, 0)
        zones = [] if rng.random() < 0.15 else [[top, min(doi, top + _round(rng, 3.0, 30.0, 0))]]
        interps.append({
            "sounding_id": ["VES 1", "VES 2", "A (1)", "Kpètèma"][int(rng.integers(0, 4))],
            "depth_to_basement_m": _round(rng, 5.0, doi) if resolved else None,
            "basement_not_resolved": not resolved, "investigation_depth_m": doi,
            "water_zones": zones, "aquifer_thickness_m": sum(b - t for t, b in zones),
            "max_drilling_depth_m": _round(rng, 10.0, doi, 0), "drilling_depth_capped": bool(rng.random() < 0.3),
            "fit_error_percent": _round(rng, 0.5, 25.0, 4),
            "site_easting": None if rng.random() < 0.15 else _round(rng, 708900.0, 709100.0, 1),
            "site_northing": None if rng.random() < 0.15 else _round(rng, 926300.0, 926450.0, 1),
        })
        if rng.random() < 0.5:
            ranges.append(None)
        else:
            lo = _round(rng, 5.0, doi * 0.6)
            q = sorted(_round(rng, 10.0, doi, 1) for _ in range(21))
            ranges.append({"sounding_id": "x", "basement_m": None if rng.random() < 0.2 else
                           {"p10": lo, "p50": lo + 3.0, "p90": lo + _round(rng, 3.0, 12.0)},
                           "basement_unresolved": float(rng.choice([0.0, 0.0, 0.05, 0.5, 0.9, 0.95, 1.0])),
                           "weathered_m": {"p10": 5.0, "p50": _round(rng, 5.0, 20.0), "p90": 25.0},
                           "investigation_depth_m": doi,
                           "drilling_depth_quantiles_m": [] if rng.random() < 0.1 else q})
        odds.append(None if rng.random() < 0.3 else {
            "probability": _round(rng, 0.0, 1.0, 5), "low": _round(rng, 0.0, 0.5, 5), "high": _round(rng, 0.5, 1.0, 5),
            "prior": 0.55, "effective_n": float(rng.choice([2.0, 10.0])), "status": "provisional",
            "matched": "class", "bgs_code": "B-L", "glg": None if rng.random() < 0.3 else "pCm",
            "success_yield_m3_per_h": 1.0, "calibration": "provisional"})
    rows = []
    depth = 0.0
    for _ in range(int(rng.integers(0, 7))):
        step = _round(rng, 2.0, 15.0, 1)
        rows.append({"top_m": depth, "bottom_m": round(depth + step, 1),
                     "description": _DESCRIPTIONS[int(rng.integers(0, len(_DESCRIPTIONS)))]})
        depth = round(depth + step, 1)
    log = None if rng.random() < 0.15 else {
        "borehole_ref": "BH-1", "total_depth_m": None if rng.random() < 0.1 else (depth or 30.0),
        "intervals": rows, "water_strikes_m": sorted(_round(rng, 3.0, 50.0, 1) for _ in range(int(rng.integers(0, 3)))),
        "status": _STATUSES[int(rng.integers(0, len(_STATUSES)))], "completion_date": "2026-11-02",
        "site": {"easting": None if rng.random() < 0.2 else _round(rng, 708900.0, 709100.0, 1),
                 "northing": _round(rng, 926300.0, 926450.0, 1), "utm_zone": 28}}
    safe = None if rng.random() < 0.3 else _round(rng, 0.1, 4.0, 4)
    analysis = None if rng.random() < 0.3 else {
        "yield_recommendation": {"safe_yield_m3_per_h": safe, "confidence": "indicative"},
        "spread": None if rng.random() < 0.4 else {
            "bootstrap": None if rng.random() < 0.2 else {"p10": 1.0},
            "safe_yield_low_m3_per_h": None if rng.random() < 0.2 else _round(rng, 0.1, 1.0),
            "safe_yield_high_m3_per_h": None if rng.random() < 0.3 else _round(rng, 1.0, 5.0),
            "holds_at_dry_season": bool(rng.random() < 0.5)}}
    site = {"community": ["Rokel", "", "Kpètèma"][seed % 3], "district": ["Port Loko", ""][seed % 2], "utm_zone": 28,
            "supervisor": ["", "  R.  Conteh ", None][seed % 3]}
    if log is not None:
        log["site"]["contractor"] = ["WiNGiN Heavy Duty", "", " Kaba\tDrilling "][seed % 3]
    teams = [None, ["  A.  Kamara", ""], ["B. Sesay"] * n][seed % 3]
    contractor = ["", "  Sierra   Drilling ", ""][(seed // 3) % 3]
    earlier = {"drilled": None, "entries": []}
    if seed % 4 == 1:
        # an earlier recording of the same survey, made before drilling
        earlier = {"drilled": None, "entries": [
            {"id": L.point_id(i["sounding_id"], i["site_easting"], i["site_northing"], 28, site["community"],
                              site["district"]),
             "point": {"sounding_id": i["sounding_id"]}, "prediction": {"depth_to_basement_m": 1.0},
             "before_outcome": True, "recorded_on": "2026-09-01", "toolkit": "0.2.0"} for i in interps]}
    return {"interps": interps, "ranges": ranges, "odds": odds, "site": site, "log": log, "analysis": analysis,
            "teams": teams, "contractor": contractor,
            "held": earlier, "known": log is not None and seed % 3 == 0,
            "drilled": None, "success": [1.0, 3.6][seed % 2], "within": [50.0, 400.0, 5.0][seed % 3],
            "dirty": [None, "x", earlier,
                      {"entries": [{"id": "z", "point": {}, "prediction": {"odds": {"probability": 1}}}],
                       "drilled": "z"}][seed % 4]}


def _python(case: dict) -> dict:
    config = Config()
    config.odds.success_yield_m3_per_h = case["success"]
    config.ledger.pair_within_m = case["within"]
    survey = L.survey_predictions(ns(case["interps"]), ns(case["ranges"]), ns(case["odds"]), ns(case["site"]), config,
                                  case["teams"])
    outcome = L.completion_outcome(ns(case["log"]), ns(case["analysis"]), config, case["contractor"])
    held, kept = L.record_predictions(case["held"], survey, "2026-10-01", case["known"], "0.3.0")
    held = L.attach_outcome(dict(held, drilled=case["drilled"]), outcome, config)
    pooled = L.pool_ledgers([("A", held), ("B", case["held"])])
    header, rows = L.ledger_rows(pooled)
    return {"survey": survey, "outcome": outcome, "kept": kept, "held": held,
            "rows": [L.entry_rows(e) for e in held["entries"]], "pooled": pooled, "counts": L.ledger_counts(pooled),
            "table": [header, rows], "clean": L.clean_ledger(case["dirty"])}


def _plain(value):
    """Tuples as the lists JSON brings back."""
    return json.loads(json.dumps(value))


SEEDS = range(60)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_browser_keeps_the_same_ledger(browser, seed):
    case = _case(seed)
    assert browser(case) == _plain(_python(case))


def test_the_seeded_cases_reach_every_rule():
    """The cases above go down every road the ledger can take."""
    told = [_python(_case(seed)) for seed in SEEDS]
    bases = {t["outcome"]["success_basis"] for t in told if t["outcome"]}
    assert bases == {"tested", "recorded_failure", "recorded_success", None}
    pairings = {e["pairing"]["how"] for t in told for e in t["held"]["entries"] if e["pairing"]}
    assert pairings == {"nearest", "only"}
    assert any(t["kept"] for t in told), "a forecast kept once the borehole is drilled"
    assert any(not e["before_outcome"] for t in told for e in t["held"]["entries"])
    checks = {L.basement_check(e["prediction"], e["outcome"]) for t in told for e in t["held"]["entries"]}
    assert {"inside", "deeper", "shallower", "unreached_allowed", "no_band", None} <= checks
    assert any(t["outcome"] and t["outcome"]["safe_yield_band_m3_per_h"] for t in told)
    assert any(t["outcome"] and t["outcome"]["basement_m"] is None for t in told)
    teams = {s["prediction"]["survey_team"] for t in told for s in t["survey"]}
    assert {"A. Kamara", "R. Conteh", "B. Sesay", ""} <= teams
    contractors = {t["outcome"]["contractor"] for t in told if t["outcome"]}
    assert {"WiNGiN Heavy Duty", "Kaba Drilling", "Sierra Drilling", ""} <= contractors

"""Calibration sets (PLAN.md step 5.3): the priors, resistivity edges and
suitability weights fitted to a pooled ledger, and adopted by a person."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from groundwater import calibration_sets as CS
from groundwater import ledger as L
from groundwater.config import Config
from groundwater.siting.odds import prior_for
from groundwater.siting.suitability import SuitabilityComponents, assess_siting
from groundwater.text import phrase

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"

#: A borehole's bands of rock as the log gives them: laterite, clay,
#: weathered rock and basement from 22 m.
_LOG = [[0.0, 2.0, "laterite"], [2.0, 8.0, "clay"], [8.0, 22.0, "weathered"], [22.0, 50.0, "basement"]]
_LAYERS = [[0.0, 2.0, 900.0], [2.0, 8.0, 12.0], [8.0, 22.0, 140.0], [22.0, None, 2400.0]]
_PARTS = {"aquifer_thickness": 0.5, "resistivity_fit": 0.5, "overburden": 0.5, "basal_fracture": 0.5}


def _entry(k, *, success=True, p=0.6, prior=0.55, code="B-L", glg="pCm", odds=True, drilled=True, judged_at=1.0,
           layers=None, intervals=None, total=50.0, doi=60.0, parts=None, before=True):
    """A pooled entry, as pool_ledgers returns it."""
    raw = {
        "id": f"e{k:03d}", "before_outcome": before, "recorded_on": "2026-03-01", "toolkit": "0.3.0",
        "point": {"sounding_id": f"VES {k}"},
        "prediction": {"investigation_depth_m": doi, "layers": layers if layers is not None else _LAYERS,
                       "suitability": parts,
                       "odds": {"probability": p, "prior": prior, "bgs_code": code, "glg": glg} if odds else None},
        "outcome": {"total_depth_m": total, "success": success, "success_yield_m3_per_h": judged_at,
                    "success_basis": "tested" if success is not None else None,
                    "intervals": intervals if intervals is not None else _LOG} if drilled else None,
    }
    return L.pool_ledgers([("Rokel", {"entries": [raw]})])[0]


def _ledger(**ledger) -> Config:
    config = Config()
    for key, value in ledger.items():
        setattr(config.ledger, key, value)
    return config


# ------------------------------------------------------------ the ledger

def test_a_prediction_keeps_the_layers_and_the_suitability_parts():
    layers = [SimpleNamespace(top_m=0.0, bottom_m=2.04, rho=880.06),
              SimpleNamespace(top_m=2.04, bottom_m=float("inf"), rho=140.0)]
    interp = SimpleNamespace(sounding_id="VES 1", depth_to_basement_m=None, basement_not_resolved=True,
                             investigation_depth_m=40.0, water_zones=[], aquifer_thickness_m=0.0,
                             max_drilling_depth_m=40.0, drilling_depth_capped=False, fit_error_percent=3.0,
                             layers=layers)
    parts = SuitabilityComponents(0.12345, 1.0, 0.15, 0.0)
    p = L.point_prediction(interp, None, None, suitability=parts)
    assert p["layers"] == [[0.0, 2.0, 880.1], [2.0, None, 140.0]]
    assert p["suitability"] == {"aquifer_thickness": 0.123, "resistivity_fit": 1.0, "overburden": 0.15,
                                "basal_fracture": 0.0}
    assert L.point_prediction(interp, None, None)["suitability"] is None


def test_a_survey_gives_each_point_its_own_parts_though_the_siting_comes_back_ranked():
    from groundwater.ves.interpret import interpret_model
    from groundwater.models import LayeredModel

    thin = interpret_model(None, LayeredModel(resistivities=[300.0, 5000.0], thicknesses=[3.0],
                                              sounding_id="thin"))
    thick = interpret_model(None, LayeredModel(resistivities=[300.0, 120.0, 5000.0], thicknesses=[3.0, 25.0],
                                               sounding_id="thick"))
    siting = assess_siting([thin, thick])
    assert siting[0].sounding_id == "thick"
    out = L.survey_predictions([thin, thick], None, None, SimpleNamespace(), siting=siting)
    by_id = {s.sounding_id: s.components for s in siting}
    for item, sid in zip(out, ("thin", "thick"), strict=True):
        assert item["prediction"]["suitability"]["aquifer_thickness"] == round(by_id[sid].aquifer_thickness, 3)
    assert [len(item["prediction"]["layers"]) for item in out] == [2, 3]


def test_a_ledger_written_before_the_layers_reads_them_blank():
    clean = L.clean_ledger({"entries": [{"id": "x", "point": {}, "prediction": {}}]})
    prediction = clean["entries"][0]["prediction"]
    assert prediction["layers"] == [] and prediction["suitability"] is None


def test_a_hand_edited_layer_or_part_of_the_wrong_kind_is_left_out():
    clean = L.clean_ledger({"entries": [{"id": "x", "point": {}, "prediction": {
        "layers": [[0, 2, 900], [2, None, 140], [2, "8", 12], [None, 8, 12], "x", [1, 2]],
        "suitability": {"aquifer_thickness": 0.5, "resistivity_fit": 0.5, "overburden": 0.5}}}]})
    prediction = clean["entries"][0]["prediction"]
    assert prediction["layers"] == [[0.0, 2.0, 900.0], [2.0, None, 140.0]]
    assert prediction["suitability"] is None


# ------------------------------------------------------------- the prior

def test_without_evidence_the_prior_is_the_plain_beta_binomial():
    pooled = [_entry(k, p=0.55, prior=0.55, success=k < 4) for k in range(7)]
    rows, used = CS.fit_prior(pooled)
    (row,) = rows
    base = prior_for("B-L", "pCm", 1.0)["rate"]
    assert (row["bgs_code"], row["glg"], row["boreholes"], row["successes"]) == ("B-L", "pCm", 7, 4)
    assert row["expected"] == 4.0
    assert row["rate"] == round((10 * base + 4) / 17, 4) and row["effective_n"] == 17.0
    assert used == {0: [e["id"] for e in pooled]}


def test_evidence_that_raised_the_odds_counts_its_successes_for_less():
    """Boreholes sited where the survey doubled the odds: the ground's rate
    that explains their successes is lower than the share that succeeded."""
    pooled = [_entry(k, p=0.8, prior=2 / 3, success=k < 6) for k in range(8)]
    (row,), _ = CS.fit_prior(pooled)
    assert row["successes"] == 6 and row["expected"] < 6
    factor = (0.8 / 0.2) / (0.667 / 0.333)
    theta = row["expected"] / 8
    assert sum(theta * factor / (theta * factor + 1 - theta) for _ in range(8)) == pytest.approx(6, abs=0.01)


def test_the_expected_count_matches_the_successes_at_the_fitted_rate():
    factors = [0.5, 1.0, 2.0, 4.0, 0.25]
    theta = CS.evidence_rate(factors, 3)
    assert sum(theta * f / (theta * f + 1 - theta) for f in factors) == pytest.approx(3, abs=1e-12)
    assert CS.evidence_rate(factors, 0) < 1e-20 and CS.evidence_rate(factors, 5) > 1 - 1e-12


def test_a_row_with_too_few_boreholes_is_counted_and_not_fitted():
    rows, used = CS.fit_prior([_entry(k) for k in range(4)])
    assert rows[0]["boreholes"] == 4 and not rows[0]["fitted"] and rows[0]["rate"] is None
    assert rows[0]["effective_n"] is None and used == {}
    rows, _ = CS.fit_prior([_entry(k) for k in range(4)], _ledger(fit_min_boreholes=4))
    assert rows[0]["fitted"]


def test_each_borehole_falls_in_the_row_its_ground_matches():
    pooled = ([_entry(k, glg="pCm") for k in range(5)] + [_entry(10 + k, glg="Pi") for k in range(5)]
              + [_entry(20 + k, code="n/a", glg=None) for k in range(5)]
              + [_entry(30 + k, code=None, glg="pCm") for k in range(5)])
    rows, _ = CS.fit_prior(pooled)
    # B-L on pCm has its own row; B-L on Pi falls in the class's; the
    # surface-water fallback and a point with no class fit nothing
    assert [(r["bgs_code"], r["glg"], r["boreholes"]) for r in rows] == [("B-L", "pCm", 5), ("B-L", "*", 5)]


def test_only_boreholes_judged_at_the_definition_in_force_are_fitted():
    pooled = ([_entry(k) for k in range(5)] + [_entry(10 + k, judged_at=3.6) for k in range(3)]
              + [_entry(20 + k, success=None) for k in range(2)] + [_entry(30, drilled=False)])
    rows, _ = CS.fit_prior(pooled)
    assert rows[0]["boreholes"] == 5
    assert CS.fit_set(pooled, "2026-10-20")["left_out"] == {"unknown": 2, "definition": 3}


def test_a_borehole_certain_to_succeed_moves_the_rate_without_reaching_one():
    pooled = [_entry(k, code="U-M/H", glg="Qe", p=1.0, prior=1.0) for k in range(30)]
    (row,), _ = CS.fit_prior(pooled)
    assert 0 < row["rate"] < 1 and row["rate"] <= 0.9999


# ------------------------------------------------------------- the edges

def test_a_layer_is_read_as_the_class_that_fills_half_of_it():
    outcome = {"total_depth_m": 50.0, "intervals": _LOG}
    prediction = {"investigation_depth_m": 60.0}
    assert CS.layer_class([2.0, 8.0, 12.0], prediction, outcome) == "clay"
    assert CS.layer_class([5.0, 13.0, 30.0], prediction, outcome) == "weathered"  # 5 of 8 m
    assert CS.layer_class([4.0, 12.0, 30.0], prediction, outcome) == "clay"  # 4 and 4: the first met
    assert CS.layer_class([0.0, 20.0, 30.0], {"investigation_depth_m": 60.0},
                          {"total_depth_m": 50.0, "intervals": [[0.0, 6.0, "clay"], [6.0, 12.0, "sand"],
                                                                [12.0, 20.0, "weathered"]]}) is None
    # the half-space down to the log's total depth, and to the depth of
    # investigation where that is shallower
    assert CS.layer_class([22.0, None, 2400.0], prediction, outcome) == "basement"
    assert CS.layer_class([22.0, None, 2400.0], {"investigation_depth_m": 22.5}, outcome) is None
    assert CS.layer_class([49.5, None, 2400.0], prediction, outcome) is None
    assert CS.layer_class([2.0, 8.0, 12.0], prediction, {"total_depth_m": None, "intervals": _LOG}) is None
    assert CS.layer_class([2.0, 8.0, 12.0], prediction, {"total_depth_m": 50.0, "intervals": []}) is None


def test_the_basement_edge_moves_where_it_misreads_fewer_layers():
    # basement read at 2,400 ohm-m in every hole: the 3,000 edge misreads it
    pooled = [_entry(k) for k in range(5)]
    edges, used = CS.fit_edges(pooled)
    assert [(e["glg"], e["edge"]) for e in edges] == [("pCm", "clay_max_rho"), ("pCm", "fresh_basement_min_rho")]
    clay, basement = edges
    assert (clay["below"], clay["above"], clay["misread_base"], clay["value"]) == (5, 5, 0, 20.0)
    assert (basement["below"], basement["above"], basement["misread_base"]) == (10, 5, 5)
    assert basement["value"] == round((140.0 * 2400.0) ** 0.5, 1) and basement["misread"] == 0
    assert used == {0: [e["id"] for e in pooled], 1: [e["id"] for e in pooled]}


def test_an_edge_that_misreads_nothing_stays_where_it_is():
    layers = [[0.0, 2.0, 900.0], [2.0, 8.0, 12.0], [8.0, 22.0, 140.0], [22.0, None, 4000.0]]
    edges, _ = CS.fit_edges([_entry(k, layers=layers) for k in range(5)])
    assert [e["value"] for e in edges] == [20.0, 3000.0]


def test_a_tie_goes_to_the_edge_nearest_the_one_in_force():
    # clay read at 10 and 30 ohm-m, weathered rock at 25: two midpoints each
    # misread one layer, as the edge in force does; it stays
    layers = [[2.0, 4.0, 10.0], [4.0, 6.0, 30.0], [8.0, 22.0, 25.0], [22.0, None, 4000.0]]
    intervals = [[0.0, 6.0, "clay"], [6.0, 22.0, "weathered"], [22.0, 50.0, "basement"]]
    edges, _ = CS.fit_edges([_entry(k, layers=layers, intervals=intervals) for k in range(5)])
    clay = edges[0]
    assert (clay["misread_base"], clay["value"], clay["misread"]) == (5, 20.0, 5)


def test_saprolite_does_not_move_the_clay_edge():
    intervals = [[0.0, 8.0, "saprolite"], [8.0, 22.0, "weathered"], [22.0, 50.0, "basement"]]
    edges, _ = CS.fit_edges([_entry(k, intervals=intervals) for k in range(5)])
    clay = next(e for e in edges if e["edge"] == "clay_max_rho")
    basement = next(e for e in edges if e["edge"] == "fresh_basement_min_rho")
    assert clay["below"] == 0 and not clay["fitted"]
    # both saprolite layers, and the weathered rock, under basement
    assert basement["below"] == 15


def test_the_clay_edge_stays_under_the_water_bearing_window_and_basement_over_clay():
    # clay read up to 1,500 ohm-m: the edge between it and weathered rock at
    # 2,000 would sit over the window's 800 ohm-m top, so it stops short
    layers = [[2.0, 8.0, 1500.0], [8.0, 22.0, 2000.0], [22.0, None, 6000.0]]
    edges, _ = CS.fit_edges([_entry(k, layers=layers) for k in range(5)])
    clay, basement = edges
    assert clay["value"] < 800.0
    assert basement["value"] > clay["value"]


def test_edges_are_fitted_unit_by_unit_and_only_on_enough_boreholes():
    pooled = [_entry(k, glg="Pi") for k in range(5)] + [_entry(10 + k, glg="pCm") for k in range(4)] \
        + [_entry(20 + k, glg=None) for k in range(5)]
    edges, _ = CS.fit_edges(pooled)
    assert [(e["glg"], e["fitted"]) for e in edges] == [("Pi", True), ("Pi", True), ("pCm", False), ("pCm", False)]


# ----------------------------------------------------------- the weights

def _parts(a, b, c, d) -> dict:
    return {"aquifer_thickness": a, "resistivity_fit": b, "overburden": c, "basal_fracture": d}


def test_the_weights_are_fitted_only_on_enough_successes_and_failures():
    pooled = [_entry(k, parts=_PARTS, success=k < 12) for k in range(21)]
    weights, used = CS.fit_weights(pooled)
    assert (weights["successes"], weights["failures"], weights["fitted"]) == (12, 9, False)
    assert weights["value"] is None and used == []
    assert weights["right_base"] == 0.5  # every pair tied
    weights, used = CS.fit_weights(pooled, _ledger(fit_weights_min_each=9))
    assert weights["fitted"] and len(used) == 21
    # nothing told the boreholes apart, so the weights in force stay
    assert weights["value"] == weights["base"] == {"aquifer_thickness": 0.35, "resistivity_fit": 0.25,
                                                    "overburden": 0.2, "basal_fracture": 0.2}


def test_the_weights_go_to_the_part_that_ranks_the_successes_first():
    rng = random.Random(1)
    pooled = []
    for k in range(30):
        success = k < 15
        fracture = round(rng.uniform(0.6, 1.0) if success else rng.uniform(0.0, 0.4), 3)
        pooled.append(_entry(k, success=success, parts=_parts(round(rng.random(), 3), round(rng.random(), 3),
                                                              round(rng.random(), 3), fracture)))
    weights, _ = CS.fit_weights(pooled)
    assert weights["right"] == 1.0 and weights["right"] > weights["right_base"]
    assert weights["value"]["basal_fracture"] > 0.2
    assert sum(weights["value"].values()) == pytest.approx(1.0)


def test_a_borehole_without_the_parts_is_not_weighed():
    pooled = [_entry(k, success=k % 2 == 0, parts=_PARTS if k < 20 else None) for k in range(30)]
    weights, _ = CS.fit_weights(pooled)
    assert weights["successes"] + weights["failures"] == 20


# ---------------------------------------------------------------- the set

def _fitted() -> dict:
    pooled = [_entry(k, success=k % 3 != 0, parts=_parts(0.5, 0.5, 0.5, 0.9 if k % 3 else 0.1))
              for k in range(30)] + [_entry(99, success=None)]
    return CS.fit_set(pooled, "2026-10-20")


def test_a_fitted_set_counts_the_boreholes_it_used_and_names_none():
    s = _fitted()
    assert s["version"] is None and s["adopted_by"] == "" and s["fitted_on"] == "2026-10-20"
    assert s["success_yield_m3_per_h"] == 1.0
    assert s["boreholes"] == 30 and s["left_out"] == {"unknown": 1, "definition": 0}
    # issued, once adopted, under the licence in the settings, by nobody yet
    assert (s["licence"], s["organisation"], s["contact"], s["sources"]) == ("CC BY 4.0", "", "", [])
    # no ledger id, project, place or borehole name in the file
    text = CS.set_yaml(CS.adopt_set(s, "A. Kamara", "2026-10-21"))
    assert not any(word in text for word in ("e000", "e029", "Rokel", "VES"))


def test_a_set_used_for_the_weights_alone_counts_its_boreholes_once():
    pooled = [_entry(k, success=k % 2 == 0, parts=_PARTS, odds=False, layers=[]) for k in range(20)] \
        + [_entry(100 + k, parts=_PARTS) for k in range(5)]
    s = CS.fit_set(pooled, "2026-10-20", _ledger(fit_weights_min_each=10))
    # 20 for the weights alone, and 5 for the prior, the edges and the weights
    assert s["weights"]["fitted"] and s["boreholes"] == 25
    # 15 succeeded and 10 failed: with the weights not fitted, only the 5
    assert CS.fit_set(pooled, "2026-10-20", _ledger(fit_weights_min_each=11))["boreholes"] == 5


def test_adopting_issues_the_set_in_the_name_of_an_organisation():
    s = CS.adopt_set(_fitted(), "A. Kamara", "2026-10-21", organisation="  Rural\tWater  Trust ",
                     contact=" wells@example.org\n")
    assert (s["organisation"], s["contact"], s["licence"]) == ("Rural Water Trust", "wells@example.org",
                                                               "CC BY 4.0")
    # the file declares them before anything else it holds
    assert CS.set_yaml(s).splitlines()[3:6] == ['licence: "CC BY 4.0"', 'organisation: "Rural Water Trust"',
                                                'contact: "wells@example.org"']
    assert CS.adopt_set(_fitted(), "A. Kamara", "2026-10-21")["organisation"] == ""
    # another licence in the settings, and none
    other = CS.fit_set([], "2026-10-20", _ledger(set_licence=" CC  BY-SA 4.0 "))
    assert other["licence"] == "CC BY-SA 4.0"
    assert CS.fit_set([], "2026-10-20", _ledger(set_licence=""))["licence"] == ""


def test_adopting_numbers_the_set_after_the_one_in_force():
    s = CS.adopt_set(_fitted(), "  A.\tKamara ", "2026-10-21")
    assert (s["version"], s["adopted_by"], s["adopted_on"]) == (1, "A. Kamara", "2026-10-21")
    assert s["replaces"] == {"version": 0, "fitted_on": "", "adopted_by": "", "adopted_on": ""}
    again = CS.adopt_set(_fitted(), "B. Sesay", "2026-11-02", in_force=s)
    assert again["version"] == 2 and again["replaces"] == {"version": 1, "fitted_on": "2026-10-20",
                                                           "adopted_by": "A. Kamara", "adopted_on": "2026-10-21"}


def test_a_set_is_adopted_by_a_named_person_once():
    with pytest.raises(ValueError, match="named person"):
        CS.adopt_set(_fitted(), " \t ", "2026-10-21")
    adopted = CS.adopt_set(_fitted(), "A. Kamara", "2026-10-21")
    with pytest.raises(ValueError, match="adopted by A. Kamara on 2026-10-21 already"):
        CS.adopt_set(adopted, "B. Sesay", "2026-10-22")


def test_every_report_can_name_the_set():
    assert CS.set_name(CS.default_set()) == phrase("calibration_sets.name_default")
    assert CS.set_name(_fitted()) == ("a calibration set fitted on 2026-10-20 to 30 boreholes, "
                                      "not adopted by anyone")
    assert CS.set_name(CS.adopt_set(_fitted(), "A. Kamara", "2026-10-21")) == (
        "calibration set 1, fitted on 2026-10-20 to 30 boreholes and adopted by A. Kamara on 2026-10-21")


def test_the_default_names_the_provisional_calibration_as_the_odds_named_it():
    assert CS.set_name(CS.default_set()) == (
        "the toolkit's provisional default from PLAN.md step 3.3, adopted by no named person and not "
        "calibrated against drilled outcomes")


# ------------------------------------------------------------- the review

def test_a_fitted_set_is_reviewed_beside_the_set_in_force_before_anyone_adopts_it():
    review = CS.set_review(_fitted())
    assert review["title"] == "Calibration set fitted on 2026-10-20" and review["adoptable"]
    lead, left, fits, weights, now, adopt, licence = review["summary"]
    assert lead.startswith("It uses 30 boreholes from the pooled ledgers") and "1 m3/h" in lead
    assert left == ("Left out: 1 drilled point whose success is not known, and 0 judged at another "
                    "definition of success.")
    assert fits == ("It fits 1 of the 1 prior row its boreholes fall in and 2 of 2 resistivity edges; a row or "
                    "an edge needs 5 boreholes.")
    assert "200 pairs" in weights
    assert now == "In force now: " + CS.set_name(CS.default_set()) + "."
    assert adopt.startswith("Nothing changes until a named person adopts it.")
    assert licence.startswith("Adopted, it is issued under CC BY 4.0, in the name of the organisation")
    prior, edges, parts = review["tables"]
    assert [prior["key"], edges["key"], parts["key"]] == ["prior", "edges", "weights"]
    assert prior["rows"] == [["B-L on pCm", "30", "20", "43 percent", "43 percent",
                              "57 percent, worth 40 boreholes"]]
    assert edges["rows"][1] == ["pCm", "Fresh basement, from", "60 and 30", "3,000 ohm-m, 30 misread",
                                "580 ohm-m, 0 misread"]
    assert [row[0] for row in parts["rows"]] == ["Aquifer thickness", "Resistivity fit", "Overburden",
                                                 "Basal fracture"]
    assert all(len(row) == len(table["header"]) for table in review["tables"] for row in table["rows"])


def test_the_review_reads_the_set_in_force_it_was_fitted_under():
    config = CS.apply_set(Config(), CS.adopt_set(_fitted(), "A. Kamara", "2026-10-21"))
    pooled = [_entry(k, success=k % 3 != 0, parts=_parts(0.5, 0.5, 0.5, 0.9 if k % 3 else 0.1)) for k in range(30)]
    review = CS.set_review(CS.fit_set(pooled, "2026-11-02", config), config)
    assert review["summary"][-3].startswith("In force now: calibration set 1, fitted on 2026-10-20")
    prior, edges, _ = review["tables"]
    # the table's 43 percent, set 1's 57 in force, and the fit from the table again
    assert prior["rows"][0][3:] == ["43 percent", "57 percent", "57 percent, worth 40 boreholes"]
    assert edges["rows"][1][3] == "580 ohm-m, 0 misread"


def test_a_set_that_fits_nothing_has_nothing_to_adopt():
    pooled = [_entry(k, success=k != 0, parts=_PARTS) for k in range(3)]
    review = CS.set_review(CS.fit_set(pooled, "2026-11-02"))
    assert not review["adoptable"]
    assert review["summary"][0].startswith("It uses 0 boreholes")
    assert "need 10 of each" in review["summary"][2]
    assert review["summary"][-1].startswith("It fits nothing yet, so there is nothing to adopt")
    prior, edges, parts = review["tables"]
    assert prior["rows"][0][5] == "too few (3 of 5)"
    assert edges["rows"][0][4] == "too few (3 of 5), or no layer on one side"
    assert {row[2] for row in parts["rows"]} == {"not fitted"}


# --------------------------------------------------------------- the file

def test_a_set_file_reads_back_as_it_was_written():
    for s in (CS.default_set(), _fitted(), CS.adopt_set(_fitted(), "A. Kamara", "2026-10-21")):
        text = CS.set_yaml(s)
        assert CS.read_set(text) == s
        assert yaml.safe_load(text) == s


def test_names_with_quotes_breaks_and_separators_survive_the_file():
    name = 'Ö "Q" \\ back\x07slash line\x85﻿end 😀'
    s = CS.adopt_set(_fitted(), "A. Kamara", name)
    assert CS.read_set(CS.set_yaml(s))["adopted_on"] == name


def test_the_file_writes_whole_numbers_without_a_point():
    text = CS.set_yaml(_fitted())
    assert "\n    base_n: 10\n" in text and "\n    effective_n: 40\n" in text
    assert "\nversion: null\n" in text and "\nreplaces: null\n" in text


@pytest.mark.parametrize("change, why", [
    (lambda s: s.update(format="something else"), r"reads \(1 to 2\)"),
    (lambda s: s.update(format_version=3), r"reads \(1 to 2\)"),
    (lambda s: s.update(format_version=True), r"reads \(1 to 2\)"),
    (lambda s: s.update(format_version=2.0), r"reads \(1 to 2\)"),
    (lambda s: s.pop("prior"), 'field "prior" is missing'),
    (lambda s: s.pop("licence"), 'field "licence" is missing'),
    (lambda s: s.update(contact=None), '"contact"'),
    (lambda s: s["prior"][0].update(rate=1.0), '"prior.rate"'),
    (lambda s: s["prior"][0].update(boreholes=-1), '"prior.boreholes"'),
    (lambda s: s["prior"][0].update(boreholes=0, successes=0, expected=0), "holds no borehole"),
    (lambda s: s["prior"][0].update(successes=31), "counts more successes, or expects more"),
    (lambda s: s["prior"][0].update(expected=30.5), "counts more successes, or expects more"),
    (lambda s: s["prior"].append(dict(s["prior"][0])), "gives the prior of B-L on pCm twice"),
    (lambda s: s["edges"][0].update(edge="laterite_min_rho"), '"edges.edge"'),
    (lambda s: s["edges"][1].update(edge="clay_max_rho"), "gives the clay_max_rho edge of pCm twice"),
    (lambda s: s["edges"][0].update(boreholes=0), "holds no borehole"),
    (lambda s: s.update(boreholes=[]), '"boreholes"'),
    (lambda s: s.update(boreholes=None), "not whole as a pooled set"),
    (lambda s: s.update(sources={}), '"sources"'),
    (lambda s: s.update(adopted_by="  "), "who adopted it disagree"),
    (lambda s: s.update(version=None), "who adopted it disagree"),
    (lambda s: s["weights"]["value"].update(overburden=0.9), "do not add up to 1"),
    (lambda s: s["weights"].update(value=None), '"weights.value"'),
    (lambda s: s.update(left_out=[]), '"left_out"'),
    # whole numbers too large for a float, which YAML reads from 400 digits
    # and the browser as Infinity: refused, where Python raised OverflowError
    # on a number and read a count
    (lambda s: s["prior"][0].update(expected=int("9" * 400)), '"prior.expected"'),
    (lambda s: s["weights"].update(right_base=-int("9" * 400)), '"weights.right_base"'),
    (lambda s: s.update(boreholes=int("9" * 400)), '"boreholes"'),
])
def test_a_set_file_is_read_whole_or_refused(change, why):
    s = json.loads(json.dumps(CS.adopt_set(_fitted(), "A. Kamara", "2026-10-21")))
    change(s)
    with pytest.raises(ValueError, match=why):
        CS.clean_set(s)


def test_a_file_that_is_not_a_set_is_refused_in_a_sentence():
    for text in ("", "- a\n- b\n", "key: [unclosed\n"):
        with pytest.raises(ValueError, match="not a calibration set the toolkit can read"):
            CS.read_set(text)


def _format_one(s: dict) -> dict:
    """``s`` as a file of format 1 (PLAN.md step 5.3) held it: its
    boreholes listed by their ledger ids, and no licence, organisation,
    contact or sources."""
    old = {key: value for key, value in s.items() if key not in ("licence", "organisation", "contact", "sources")}
    old["format_version"] = 1
    old["boreholes"] = [{"id": f"3f2a{k:08x}", "success": k % 3 != 0, "forecast": k != 4,
                         "uses": ["prior", "clay_max_rho", "fresh_basement_min_rho", "weights"]}
                        for k in range(s["boreholes"])]
    return old


def test_a_file_of_format_1_is_read_with_its_ledger_ids_counted_and_dropped():
    s = CS.adopt_set(_fitted(), "A. Kamara", "2026-10-21")
    raw = _format_one(s)
    text = CS.set_yaml(raw)
    assert "format_version: 1" in text and "3f2a00000000" in text
    read = CS.read_set(text)
    assert read == dict(s, licence="") and read["format_version"] == 2 and read["boreholes"] == 30
    assert "3f2a" not in CS.set_yaml(read)
    assert CS.set_name(read) == CS.set_name(s)
    # put in force as it was
    assert CS.apply_set(Config(), raw).calibration == read
    # and still checked as format 1 was
    raw["boreholes"][3]["uses"] = ["everything"]
    with pytest.raises(ValueError, match='"boreholes.uses"'):
        CS.clean_set(raw)
    with pytest.raises(ValueError, match='"boreholes"'):
        CS.clean_set(dict(raw, boreholes=30))


# ------------------------------------------- the browser's engine, held to it

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js', 'support.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core, S = sandbox.GWT.support;
const cases = JSON.parse(readFileSync(0, 'utf8'));
function attempt(f) {
  try { return { ok: f() }; } catch (e) { return { threw: String(e && e.message || e) }; }
}
process.stdout.write(JSON.stringify(cases.map((r) => {
  try {
    const cfg = C.withConfig(r.settings);
    const pooled = C.poolLedgers(r.items);
    const prior = C.fitPrior(pooled, cfg), edges = C.fitEdges(pooled, cfg), weights = C.fitWeights(pooled, cfg);
    const fitted = C.fitSet(pooled, r.on, cfg);
    const adopted = attempt(() => C.adoptSet(fitted, r.by, r.on, r.inForce ? C.cleanSet(r.inForce) : null,
      r.organisation, r.contact));
    const shown = adopted.ok || fitted;
    const text = C.setYaml(shown);
    return { ok: {
      prior: [prior.rows, prior.used], edges: [edges.rows, edges.used], weights: [weights.weights, weights.used],
      set: fitted, adopted: adopted, name: C.setName(shown), yaml: text,
      read: attempt(() => C.cleanSet(S.parseYaml(text))),
      hand: r.hand.map((raw) => attempt(() => C.cleanSet(raw))),
      classes: r.layers.map((q) => C.layerClass(q[0], q[1], q[2])),
      rates: r.rates.map((q) => C.evidenceRate(q[0], q[1])),
      review: C.setReview(fitted, cfg),
      review_adopted: adopted.ok ? C.setReview(fitted, C.applySet(cfg, adopted.ok)) : null,
    } };
  } catch (e) {
    return { threw: String(e && e.stack || e) };
  }
})));
"""

_CODES = [("B-L", "pCm"), ("B-L", "Pi"), ("I-L", "Pi"), ("I-L", "Mi"), ("CSF-L/M", "pCm"), ("U-M/H", "Qe"),
          ("n/a", None), (None, None), ("B-L", None), ("I-L", "\U0001d4b5"), ("CSF-L/M", "Pi")]
_CLASSES = ["topsoil", "laterite", "clay", "saprolite", "sand", "weathered", "fracture", "basement", "other"]
_NAMES = ["A. Kamara", " A.\t Kamara ", "", "  ", "Ñdoye \"Q\" \\", "line break", "\U0001d4b5"]


def _layers(rng: random.Random) -> list:
    tops = sorted({round(rng.uniform(0.0, 40.0), 1) for _ in range(rng.randint(1, 5))} | {0.0})
    out = []
    for k, top in enumerate(tops):
        bottom = tops[k + 1] if k + 1 < len(tops) else rng.choice([None, round(top + rng.uniform(0.5, 30.0), 1)])
        out.append([top, bottom, rng.choice([round(rng.uniform(1.0, 9000.0), 1), round(rng.uniform(5.0, 60.0), 1),
                                             20.0, 3000.0, 140.0])])
    return out


def _intervals(rng: random.Random) -> list:
    edges = sorted({round(rng.uniform(0.0, 60.0), 1) for _ in range(rng.randint(1, 6))} | {0.0})
    return [[edges[k], edges[k + 1], rng.choice(_CLASSES)] for k in range(len(edges) - 1)]


def _raw(rng: random.Random, k: int) -> dict:
    code, glg = rng.choice(_CODES)
    p = rng.choice([round(rng.random(), 3), 0.0, 1.0, 0.5, None])
    success = rng.choice([True, False, True, None])
    return {
        "id": f"r{k}", "before_outcome": rng.random() < 0.8, "recorded_on": "2026-03-01", "toolkit": "x",
        "point": {"sounding_id": f"VES {k}"},
        "prediction": {
            "investigation_depth_m": rng.choice([None, 60.0, round(rng.uniform(10.0, 80.0), 1)]),
            "layers": _layers(rng) if rng.random() < 0.85 else [],
            "suitability": None if rng.random() < 0.2 else _parts(*(round(rng.random(), 3) for _ in range(4))),
            "odds": None if p is None else {"probability": p, "prior": rng.choice([0.428, 0.5, None, 0.966, 0.0]),
                                            "bgs_code": code, "glg": glg}},
        "outcome": None if rng.random() < 0.1 else {
            "total_depth_m": rng.choice([None, round(rng.uniform(15.0, 70.0), 1), 50.0]),
            "intervals": _intervals(rng), "success": success,
            "success_basis": None if success is None else "tested",
            "success_yield_m3_per_h": rng.choice([1.0, 1.0, 1.0, 3.6, None])},
    }


def _hand(rng: random.Random, good: dict) -> list:
    """Hand-edited set files: the good one, and copies with one field
    broken."""
    out = [good]
    for _ in range(6):
        bad = json.loads(json.dumps(good))
        target = rng.choice(["top", "prior", "edges", "weights"])
        if target == "top":
            bad[rng.choice(list(bad))] = rng.choice([None, "x", -1, 1.5, True, [], {}])
        elif target == "weights" and bad["weights"]:
            bad["weights"][rng.choice(list(bad["weights"]))] = rng.choice([None, "x", -1, 2, {}])
        elif bad[target]:
            row = rng.choice(bad[target])
            row[rng.choice(list(row))] = rng.choice([None, "x", -1, 1.5, True, [], "laterite_min_rho"])
        out.append(bad)
    out.append([good])
    if isinstance(good.get("boreholes"), int):
        # the same set as a file of format 1 held it
        out.append(_format_one(good))
    return out


def _case(seed: int) -> dict:
    rng = random.Random(seed)
    items = [[f"P{j}", {"entries": [_raw(rng, 100 * j + k, ) for k in range(rng.randint(0, 40))]}]
             for j in range(rng.randint(1, 3))]
    settings = {"ledger": {"fit_min_boreholes": rng.choice([5, 1, 2, 40]),
                           "fit_weights_min_each": rng.choice([10, 1, 3, 100]),
                           "set_licence": rng.choice(["CC BY 4.0", "", " CC  BY-SA 4.0 "])},
                "odds": {"success_yield_m3_per_h": rng.choice([1.0, 1.0, 3.6])},
                "ves": rng.choice([{}, {"clay_max_rho": 35.0, "fresh_basement_min_rho": 1200.0}])}
    in_force = None
    if seed % 3 == 0:
        in_force = CS.set_yaml(CS.adopt_set(CS.fit_set([], "2026-01-01"), "Earlier Person", "2026-01-02"))
        in_force = yaml.safe_load(in_force)
    layers = [[_layers(rng)[0], {"investigation_depth_m": rng.choice([None, 30.0])},
               {"total_depth_m": rng.choice([None, 40.0]), "intervals": _intervals(rng)}] for _ in range(20)]
    rates = [[[round(rng.uniform(0.05, 20.0), 3) for _ in range(rng.randint(0, 8))], rng.randint(0, 8)]
             for _ in range(10)]
    return {"items": items, "settings": settings, "on": rng.choice(["2026-10-20", "", "20 Oct 2026"]),
            "by": rng.choice(_NAMES), "organisation": rng.choice(_NAMES), "contact": rng.choice(["", " x@y.z "]),
            "inForce": in_force, "layers": layers, "rates": rates, "seed": seed}


def _settings(settings: dict) -> Config:
    config = Config()
    for section, values in settings.items():
        for key, value in values.items():
            setattr(getattr(config, section), key, value)
    return config


def _attempt(f):
    try:
        return {"ok": f()}
    except ValueError as exc:
        return {"threw": str(exc)}


def _python(case: dict) -> dict:
    config = _settings(case["settings"])
    pooled = L.pool_ledgers([tuple(item) for item in case["items"]])
    fitted = CS.fit_set(pooled, case["on"], config)
    in_force = CS.clean_set(case["inForce"]) if case["inForce"] else None
    adopted = _attempt(lambda: CS.adopt_set(fitted, case["by"], case["on"], in_force,
                                            organisation=case["organisation"], contact=case["contact"]))
    shown = adopted.get("ok") or fitted
    text = CS.set_yaml(shown)
    good = json.loads(json.dumps(shown))
    return json.loads(json.dumps({
        "prior": list(CS.fit_prior(pooled, config)), "edges": list(CS.fit_edges(pooled, config)),
        "weights": list(CS.fit_weights(pooled, config)), "set": fitted, "adopted": adopted,
        "name": CS.set_name(shown), "yaml": text, "read": _attempt(lambda: CS.read_set(text)),
        "hand": [_attempt(lambda raw=raw: CS.clean_set(raw)) for raw in _hand(random.Random(case["seed"]), good)],
        "classes": [CS.layer_class(*q) for q in case["layers"]],
        "rates": [CS.evidence_rate(*q) for q in case["rates"]], "review": CS.set_review(fitted, config),
        "review_adopted": CS.set_review(fitted, CS.apply_set(config, adopted["ok"])) if "ok" in adopted else None}))


SEEDS = range(24)


@pytest.fixture(scope="module")
def browser_answers(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    cases = []
    for seed in SEEDS:
        case = _case(seed)
        good = json.loads(json.dumps(_python(case)["read"].get("ok") or {}))
        case["hand"] = _hand(random.Random(seed), good)
        cases.append(case)
    driver = tmp_path_factory.mktemp("sets") / "sets.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS)], input=json.dumps(cases), capture_output=True, text=True,
                          encoding="utf-8", check=True)
    return json.loads(done.stdout)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_browser_fits_the_same_set_and_writes_the_same_file(browser_answers, seed):
    answer = browser_answers[seed]
    assert "threw" not in answer, answer.get("threw")
    assert answer["ok"] == _python(_case(seed))


def test_the_seeded_cases_reach_every_rule():
    told = [_python(_case(seed)) for seed in SEEDS]
    rows = [row for t in told for row in t["prior"][0]]
    edges = [row for t in told for row in t["edges"][0]]
    assert {row["fitted"] for row in rows} == {True, False}
    assert any(row["fitted"] and row["value"] != row["base"] for row in edges)
    assert any(row["fitted"] and row["value"] == row["base"] for row in edges)
    assert {row["edge"] for row in edges if row["fitted"]} == set(CS.EDGES)
    assert {t["weights"][0]["fitted"] for t in told} == {True, False}
    assert any(t["weights"][0]["value"] not in (None, t["weights"][0]["base"]) for t in told)
    assert {"ok", "threw"} <= {key for t in told for key in t["adopted"]}
    assert {"ok", "threw"} <= {key for t in told for result in t["hand"] for key in result}
    assert {c for t in told for c in t["classes"]} >= {None, "clay", "basement"}

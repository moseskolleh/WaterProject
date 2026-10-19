"""The calibration report (PLAN.md step 5.2): the ledger's forecasts scored
against what was drilled."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from groundwater import calibration as K
from groundwater import ledger as L
from groundwater.config import Config
from groundwater.text import phrase

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"


def _entry(k, *, band=(20.0, 25.0, 30.0), best=25.0, found=None, total=40.0, before=True, drilled=True,
           p=0.6, prior=0.55, success=True, basis="tested", team="", contractor="", code="B-L", glg="pCm",
           odds=True, project="Rokel"):
    """A pooled entry, as pool_ledgers returns it."""
    raw = {
        "id": f"e{k}", "before_outcome": before, "recorded_on": "2026-03-01", "toolkit": "0.3.0",
        "point": {"sounding_id": f"VES {k}"},
        "prediction": {"depth_to_basement_m": best, "basement_band_m": list(band) if band else None,
                       "survey_team": team,
                       "odds": {"probability": p, "prior": prior, "bgs_code": code, "glg": glg} if odds else None},
        "outcome": {"basement_m": found, "total_depth_m": total, "success": success,
                    "success_basis": basis if success is not None else None, "contractor": contractor}
        if drilled else None,
    }
    return L.pool_ledgers([(project, {"entries": [raw]})])[0]


def _depths(inside, above, below, n_extra=()):
    entries = [_entry(k, found=25.0) for k in range(inside)]
    entries += [_entry(100 + k, found=15.0) for k in range(above)]
    entries += [_entry(200 + k, found=35.0) for k in range(below)]
    return entries + list(n_extra)


# -------------------------------------------------------------- the band

@pytest.mark.parametrize("n", [1, 2, 5, 9, 10, 11, 30, 97, 400, 1000])
@pytest.mark.parametrize("p", [0.8, 0.5, 0.05, 0.95])
def test_the_expected_range_is_the_binomials_5th_and_95th_percentiles(n, p):
    stats = pytest.importorskip("scipy.stats")
    assert K.binomial_range(n, p) == (int(stats.binom.ppf(0.05, n, p)), int(stats.binom.ppf(0.95, n, p)))


def test_a_large_sample_does_not_underflow():
    low, high = K.binomial_range(20000, 0.8)
    assert 15800 < low < 16000 < high < 16200


def test_a_band_holding_four_in_five_reads_as_calibrated():
    d = K.depth_scores(_depths(8, 1, 1))
    assert (d["judged"], d["inside"], d["shallower"], d["deeper"]) == (10, 8, 1, 1)
    assert d["expected"] == [6, 10] and d["verdict"] == "calibrated"


def test_a_band_that_misses_too_often_is_too_narrow_and_one_that_never_does_too_wide():
    assert K.depth_scores(_depths(5, 2, 3))["verdict"] == "narrow"
    wide = K.depth_scores(_depths(30, 0, 0))
    assert wide["expected"] == [20, 27] and wide["verdict"] == "wide"


def test_below_the_minimum_it_is_too_few_to_judge_and_says_the_counts():
    d = K.depth_scores(_depths(7, 1, 1))
    assert d["judged"] == 9 and d["verdict"] == "too_few"
    section = K.calibration_content(_depths(7, 1, 1))["sections"][0]
    assert phrase("calibration.depth_too_few", judged=9, minimum=10) in section["paragraphs"]
    assert any("7 found basement inside the band, 1 above it and 1 below it" in t for t in section["paragraphs"])
    config = Config()
    config.ledger.min_boreholes = 9
    assert K.depth_scores(_depths(7, 1, 1), config)["verdict"] == "calibrated"


def test_a_hole_short_of_basement_is_judged_only_once_it_passed_the_band():
    short = _entry(1, found=None, total=28.0)
    past = _entry(2, found=None, total=31.0)
    unbanded = _entry(3, band=None, found=26.0)
    d = K.depth_scores([short, past, unbanded])
    assert [p["check"] for p in d["points"]] == ["unreached_allowed", "deeper", "no_band"]
    assert (d["judged"], d["deeper"], d["unreached"], d["no_band"]) == (1, 1, 1, 1)


def test_the_bias_is_the_depth_found_less_the_best_fit():
    d = K.depth_scores([_entry(1, best=20.0, found=24.0), _entry(2, best=30.0, found=28.0),
                        _entry(3, best=None, found=25.0), _entry(4, best=22.0, found=None, total=28.0)])
    assert (d["errors"], d["bias_m"], d["mean_abs_m"]) == (2, 1.0, 3.0)


def test_only_forecasts_are_scored():
    after = [_entry(k, found=25.0, before=False) for k in range(12)]
    undrilled = [_entry(100 + k, drilled=False) for k in range(12)]
    assert K.depth_scores(after + undrilled)["drilled"] == 0
    assert K.odds_scores(after + undrilled)["n"] == 0
    assert sum(g["drilled"] for g in K.hit_rates(after + undrilled, "team")) == 12


# --------------------------------------------------------------- the odds

def test_the_brier_score_beside_the_priors():
    entries = [_entry(1, p=0.9, success=True), _entry(2, p=0.2, success=False), _entry(3, p=0.6, success=False)]
    o = K.odds_scores(entries)
    assert o["brier"] == round((0.01 + 0.04 + 0.36) / 3, 4)
    assert o["brier_prior"] == round((0.45 ** 2 + 0.55 ** 2 + 0.55 ** 2) / 3, 4)
    assert o["skill"] == round(1 - ((0.01 + 0.04 + 0.36) / 3) / ((0.45 ** 2 + 2 * 0.55 ** 2) / 3), 3)
    assert (o["n"], o["successes"], o["failures"], o["mean_p"]) == (3, 1, 2, round(1.7 / 3, 3))


def test_a_forecast_that_is_the_prior_has_no_skill_and_a_missing_prior_gives_no_reference():
    assert K.odds_scores([_entry(k, p=0.55, success=k % 2 == 0) for k in range(4)])["skill"] == 0.0
    o = K.odds_scores([_entry(1, prior=None), _entry(2)])
    assert o["brier"] is not None and o["brier_prior"] is None and o["skill"] is None


def test_the_reliability_bins_take_each_chance_on_its_lower_edge():
    entries = [_entry(k, p=p, success=bool(k % 2)) for k, p in enumerate([0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 0.19])]
    bins = K.odds_scores(entries)["bins"]
    assert [b["n"] for b in bins] == [2, 1, 1, 1, 2]
    assert [(b["low"], b["high"]) for b in bins] == [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    assert bins[0]["mean_p"] == 0.095 and bins[4]["observed"] == 0.5


def test_a_chance_outside_0_to_1_or_an_unknown_outcome_is_not_scored():
    o = K.odds_scores([_entry(1, p=1.5), _entry(2, p=-0.1), _entry(3, odds=False), _entry(4, success=None),
                       _entry(5)])
    assert (o["n"], o["no_odds"], o["unknown"]) == (1, 3, 1)


def test_the_outcomes_are_counted_by_what_decided_them():
    entries = [_entry(1, basis="tested"), _entry(2, success=False, basis="recorded_failure"),
               _entry(3, basis="recorded_success"), _entry(4, basis="recorded_success")]
    assert K.odds_scores(entries)["bases"] == {"tested": 1, "recorded_failure": 1, "recorded_success": 2}


def test_too_few_forecasts_are_too_few_to_judge():
    content = K.calibration_content([_entry(k) for k in range(4)])
    odds = content["sections"][1]
    assert odds["figures"] == [] and odds["tables"] == []
    assert phrase("calibration.odds_too_few", n=4, success=4, failure=0, minimum=10) in odds["paragraphs"]


# ------------------------------------------------------------ hit rates

def test_hit_rates_group_by_name_as_written_once_tidied():
    entries = [_entry(k, team="A. Kamara", success=k < 3) for k in range(5)]
    entries += [_entry(10, team="  A.  Kamara\t"), _entry(11, team=""), _entry(12, team="B. Sesay", success=None)]
    groups = K.hit_rates(entries, "team")
    assert [(g["label"], g["drilled"], g["success"], g["failure"], g["unknown"]) for g in groups] == [
        ("A. Kamara", 6, 4, 2, 0), ("B. Sesay", 1, 0, 0, 1), (phrase("calibration.not_recorded"), 1, 1, 0, 0)]
    assert groups[0]["rate"] == round(4 / 6, 3) and groups[1]["rate"] is None


def test_hit_rates_by_geology_name_the_class_and_unit():
    entries = [_entry(1), _entry(2, glg=None), _entry(3, code=None), _entry(4, odds=False)]
    labels = [g["label"] for g in K.hit_rates(entries, "geology")]
    assert labels == ["B-L on pCm", "B-L, with no USGS unit", "No BGS class at the point", "Not recorded"]


def test_groups_sort_by_boreholes_then_by_letter_as_python_orders_them():
    names = ["ｱ Drill", "\U0001d4b5 Drill", "Kaba", "Kaba", "WiNGiN"]
    groups = K.hit_rates([_entry(k, contractor=n) for k, n in enumerate(names)], "contractor")
    # the letter beyond the Basic Multilingual Plane after the full-width one
    assert [g["label"] for g in groups] == ["Kaba", "WiNGiN", "ｱ Drill", "\U0001d4b5 Drill"]


def test_the_forecast_beside_the_rate_counts_only_forecasts_with_an_outcome():
    entries = [_entry(1, p=0.8), _entry(2, p=0.4), _entry(3, p=0.9, before=False), _entry(4, p=0.1, success=None)]
    group = K.hit_rates(entries, "contractor")[0]
    assert (group["forecast_n"], group["forecast_mean"]) == (2, 0.6)


def test_a_grouping_the_report_does_not_give_is_refused():
    with pytest.raises(ValueError):
        K.hit_rates([], "district")


# ------------------------------------------------------------- the report

def test_the_report_says_what_it_scored_and_what_it_left_out():
    entries = _depths(8, 1, 1) + [_entry(50, before=False), _entry(51, drilled=False)]
    content = K.calibration_content(entries, " 2026-10-19 ")
    assert content["rows"][-1] == [phrase("calibration.row_issued"), "2026-10-19"]
    assert content["summary"][1] == phrase("calibration.summary_scored", forecast=10)
    assert phrase("calibration.limit_after", after=1) in content["sections"][-1]["bullets"]
    assert [s["key"] for s in content["sections"]] == ["depth", "odds", "hits", "limits"]
    assert content["sections"][0]["figures"][0]["key"] == "depth"
    assert content["sections"][1]["figures"][0]["key"] == "reliability"
    assert len(content["sections"][2]["tables"]) == 3
    assert content["references"][0].startswith("Brier, G. W. (1950)")


def test_an_empty_portfolio_has_nothing_to_score():
    content = K.calibration_content([])
    assert content["summary"] == [phrase("ledger.pool_none")]
    assert content["sections"][2]["paragraphs"] == [phrase("calibration.hits_none")]
    assert all(not s["tables"] for s in content["sections"])
    assert [row[1] for row in content["rows"]] == ["0", "0", "0", "0"]


# ------------------------------------- the ledger's team and contractor

def test_a_points_team_is_its_sheets_field_supervisor_else_the_projects():
    from types import SimpleNamespace

    interp = SimpleNamespace(sounding_id="VES 1", depth_to_basement_m=20.0, basement_not_resolved=False,
                             investigation_depth_m=60.0, water_zones=[], aquifer_thickness_m=0.0,
                             max_drilling_depth_m=30.0, drilling_depth_capped=False, fit_error_percent=2.0,
                             site_easting=None, site_northing=None)
    site = SimpleNamespace(community="Rokel", district="Port Loko", utm_zone=28, supervisor=" R.  Conteh ")
    survey = L.survey_predictions([interp, interp], None, None, site, teams=["  A.  Kamara", ""])
    assert [s["prediction"]["survey_team"] for s in survey] == ["A. Kamara", "R. Conteh"]
    # the team is not part of the point's identity
    assert L.point_id("VES 1", None, None, 28, "Rokel", "Port Loko") == L.record_predictions(
        L.empty_ledger(), survey[:1], "2026-03-01", False, "0.3.0")[0]["entries"][0]["id"]


def test_the_projects_contractor_wins_over_the_logs():
    from types import SimpleNamespace

    log = SimpleNamespace(borehole_ref="BH-1", total_depth_m=40.0, intervals=[], water_strikes_m=[],
                          status="Successful", completion_date="",
                          site=SimpleNamespace(easting=None, northing=None, utm_zone=None, contractor="WiNGiN"))
    assert L.completion_outcome(log)["contractor"] == "WiNGiN"
    assert L.completion_outcome(log, contractor=" Kaba   Drilling ")["contractor"] == "Kaba Drilling"


def test_a_ledger_written_before_the_team_and_contractor_reads_them_blank():
    clean = L.clean_ledger({"entries": [{"id": "x", "point": {}, "prediction": {}, "outcome": {"success": True}}]})
    entry = clean["entries"][0]
    assert entry["prediction"]["survey_team"] == "" and entry["outcome"]["contractor"] == ""


# ------------------------------------------- the browser's engine, held to it

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const cases = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map((r) => {
  try {
    const cfg = C.withConfig({ ledger: r.settings });
    const pooled = C.poolLedgers(r.items);
    return { ok: { depth: C.depthScores(pooled, cfg), odds: C.oddsScores(pooled, cfg),
      hits: ['geology', 'team', 'contractor'].map((by) => C.hitRates(pooled, by, cfg)),
      content: C.calibrationContent(pooled, r.issued, cfg), range: C.binomialRange(r.n, r.p) } };
  } catch (e) {
    return { threw: String(e && e.stack || e) };
  }
})));
"""

_NAMES = ["A. Kamara", " A.  Kamara", "B. Sesay", "", "Ñdoye", "\U0001d4b5", "ｱ", "1", "__proto__", "constructor"]


def _raw(rng: random.Random, k: int, inside: float) -> dict:
    """A ledger entry as a file holds it, its basement found inside its band
    ``inside`` of the time."""
    band = sorted(round(rng.uniform(5.0, 45.0), 1) for _ in range(3))
    found = (round(rng.uniform(band[0], band[2]), 1) if rng.random() < inside
             else rng.choice([None, round(rng.uniform(2.0, 50.0), 1)]))
    chance = rng.choice([round(rng.random(), 3), 0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, None])
    success = rng.choice([True, False, None])
    return {
        "id": f"r{k}", "before_outcome": rng.random() < 0.8, "recorded_on": "2026-03-01", "toolkit": "x",
        "point": {"sounding_id": f"VES {k}"},
        "prediction": {"depth_to_basement_m": rng.choice([None, round(rng.uniform(5.0, 45.0), 1)]),
                       "basement_band_m": rng.choice([None, band, band]),
                       "survey_team": rng.choice(_NAMES),
                       "odds": None if chance is None else {
                           "probability": chance, "prior": rng.choice([0.55, 0.3, None, 0.55]),
                           "bgs_code": rng.choice(["B-L", None, "CSF-L/M"]), "glg": rng.choice(["pCm", None])}},
        "outcome": None if rng.random() < 0.15 else {
            "basement_m": found,
            "total_depth_m": rng.choice([None, round(rng.uniform(20.0, 60.0), 1)]),
            "success": success, "success_basis": None if success is None else rng.choice(
                ["tested", "recorded_failure", "recorded_success"]),
            "contractor": rng.choice(_NAMES)},
    }


def _case(seed: int) -> dict:
    rng = random.Random(seed)
    # most bands miss often; one case in four holds nearly every depth found
    inside = 1.0 if seed % 4 == 3 else 0.3
    items = [[f"P{j}", {"entries": [_raw(rng, 100 * j + k, inside) for k in range(rng.randint(0, 30))]}]
             for j in range(rng.randint(1, 4))]
    if seed % 5 == 0 and items:
        items.append(["copy", json.loads(json.dumps(items[0][1]))])
    return {"items": items, "issued": rng.choice(["", " 2026-10-19 "]),
            "settings": {"min_boreholes": rng.choice([10, 3, 25]), "min_group": rng.choice([5, 2, 1]),
                         "reliability_bins": rng.choice([5, 3, 10, 1])},
            "n": rng.randint(0, 300), "p": rng.choice([0.8, 0.5, 0.05])}


def _python(case: dict) -> dict:
    config = Config()
    for key, value in case["settings"].items():
        setattr(config.ledger, key, value)
    pooled = L.pool_ledgers([tuple(item) for item in case["items"]])
    return json.loads(json.dumps({
        "depth": K.depth_scores(pooled, config), "odds": K.odds_scores(pooled, config),
        "hits": [K.hit_rates(pooled, by, config) for by in K.GROUPINGS],
        "content": K.calibration_content(pooled, case["issued"], config),
        "range": list(K.binomial_range(case["n"], case["p"]))}))


SEEDS = range(40)


@pytest.fixture(scope="module")
def browser_answers(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path_factory.mktemp("calibration") / "calibration.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS)], input=json.dumps([_case(s) for s in SEEDS]),
                          capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_browser_scores_the_same(browser_answers, seed):
    answer = browser_answers[seed]
    assert "threw" not in answer, answer.get("threw")
    assert answer["ok"] == _python(_case(seed))


def test_the_seeded_cases_reach_every_rule():
    told = [_python(_case(seed)) for seed in SEEDS]
    assert {t["depth"]["verdict"] for t in told} == {"too_few", "calibrated", "narrow", "wide"}
    assert {t["odds"]["verdict"] for t in told} == {"too_few", "scored"}
    skills = [t["odds"]["skill"] for t in told if t["odds"]["skill"] is not None]
    assert any(s > 0 for s in skills) and any(s < 0 for s in skills)
    assert any(t["odds"]["brier"] is not None and t["odds"]["brier_prior"] is None for t in told)
    rates = [g["rate"] for t in told for groups in t["hits"] for g in groups]
    assert None in rates and any(r is not None for r in rates)


# ------------------------------------------------- the document and its figures

def _portfolio(n: int = 12) -> list[dict]:
    """Forecasts with bands and chances: some inside the band, some outside,
    one short of basement, one with no band."""
    entries = []
    for k in range(n):
        found = None if k == 3 else 19.0 + k + (9.0 if k % 4 == 0 else 0.0)
        entries.append(_entry(k, band=None if k == 5 else (16.0 + k, 20.0 + k, 26.0 + k), best=20.0 + k,
                              found=found, total=30.0 + k, p=(k + 0.5) / n, success=k % 3 != 0,
                              team="A. Kamara", contractor="Kaba Drilling"))
    return entries


def test_the_report_lays_out_its_content_with_the_figures_it_names(tmp_path):
    from docx import Document

    from groundwater.reporting.calibration import build_calibration_report, figure_keys

    pooled = _portfolio()
    content = K.calibration_content(pooled, "2026-10-19")
    assert figure_keys(content) == ["depth", "reliability"]
    path = build_calibration_report(pooled, tmp_path / "Calibration_Report.docx", "2026-10-19",
                                    figures_dir=tmp_path / "figures")
    doc = Document(str(path))
    text = "\n".join(para.text for para in doc.paragraphs)
    for section in content["sections"]:
        assert section["heading"] in text
    assert len(doc.inline_shapes) == 2
    assert sorted(p.name for p in (tmp_path / "figures").glob("*.png")) == [
        "calibration_depth.png", "calibration_reliability.png"]
    # the depth points, the bins and the three groupings of hit rates
    assert len(doc.tables) >= 1 + 1 + 3
    assert content["references"][0] in text


def test_a_portfolio_with_nothing_drilled_builds_a_report_without_figures(tmp_path):
    from docx import Document

    from groundwater.reporting.calibration import build_calibration_report

    path = build_calibration_report([_entry(1, drilled=False)], tmp_path / "r.docx")
    doc = Document(str(path))
    assert len(doc.inline_shapes) == 0
    assert phrase("calibration.hits_none") in "\n".join(para.text for para in doc.paragraphs)
    assert not list(tmp_path.glob("*.png"))


def test_the_figures_draw_every_kind_of_point_and_an_empty_bin(tmp_path):
    from groundwater.calibration_plots import plot_depth_calibration, plot_reliability

    pooled = _portfolio() + [_entry(50, best=None, found=30.0), _entry(51, best=None, band=None, found=30.0),
                             _entry(52, found=12.0), _entry(53, found=None, total=27.0)]
    depth = K.depth_scores(pooled)
    assert {p["check"] for p in depth["points"]} == {"inside", "shallower", "deeper", "unreached_allowed",
                                                     "no_band"}
    assert plot_depth_calibration(depth, tmp_path / "depth.png").stat().st_size > 0
    odds = K.odds_scores([_entry(1, p=0.1), _entry(2, p=0.9, success=False)])
    assert [b["n"] for b in odds["bins"]] == [1, 0, 0, 0, 1]
    assert plot_reliability(odds, tmp_path / "reliability.png").stat().st_size > 0

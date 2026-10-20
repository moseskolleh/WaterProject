"""A calibration set in force (PLAN.md step 5.3, part b): its priors in the
odds, its resistivity edges in the interpretation of each geology unit, its
suitability weights in the ranking, and its name in every report."""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import random
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from groundwater import calibration_sets as CS
from groundwater import ledger as L
from groundwater.config import Config, VESConfig
from groundwater.models import LayeredModel
from groundwater.siting import assess_siting
from groundwater.siting.odds import (
    odds_basis_text,
    odds_headline,
    odds_prior_text,
    prior_for,
    prior_odds,
    success_odds,
)
from groundwater.ves.cache import inversion_key
from groundwater.ves.interpret import interpret_model

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"

_WEIGHTS = {"aquifer_thickness": 0.25, "resistivity_fit": 0.1, "overburden": 0.1, "basal_fracture": 0.55}

#: Positions on the bundled maps: Kpètèma, on the Precambrian (pCm) of the
#: BGS class B-L, and Rokel, on the Holocene (Qe) of U-M/H.
_PCM = (166030.0, 930010.0, 29)
_QE = (708958.4, 926355.5, 28)


def _set(**changes) -> dict:
    """An adopted set: the prior of B-L on pCm and of I-L on any unit fitted,
    CSF-L/M on pCm counted and not fitted; both edges of pCm fitted and
    none of Qe's; and the weights."""
    s = {
        "format": CS.FORMAT, "format_version": CS.FORMAT_VERSION, "version": 3, "fitted_on": "2027-03-01",
        "adopted_by": "A. Kamara", "adopted_on": "2027-03-02",
        "replaces": {"version": 2, "fitted_on": "2026-11-01", "adopted_by": "B. Sesay", "adopted_on": "2026-11-02"},
        "success_yield_m3_per_h": 1.0,
        "boreholes": [{"id": f"b{k}", "success": k % 2 == 0, "forecast": True, "uses": ["prior"]} for k in range(12)],
        "left_out": {"unknown": 0, "definition": 0},
        "prior": [
            {"bgs_code": "B-L", "glg": "pCm", "boreholes": 12, "successes": 9, "expected": 8.2, "base_rate": 0.4279,
             "base_n": 10.0, "fitted": True, "rate": 0.6123, "effective_n": 22.0},
            {"bgs_code": "I-L", "glg": "*", "boreholes": 6, "successes": 1, "expected": 1.0, "base_rate": 0.4279,
             "base_n": 10.0, "fitted": True, "rate": 0.3299, "effective_n": 16.0},
            {"bgs_code": "CSF-L/M", "glg": "pCm", "boreholes": 3, "successes": 3, "expected": 3.0,
             "base_rate": 0.7, "base_n": 10.0, "fitted": False, "rate": None, "effective_n": None},
        ],
        "edges": [
            {"glg": "pCm", "edge": "clay_max_rho", "boreholes": 8, "below": 8, "above": 20, "base": 20.0,
             "misread_base": 3, "fitted": True, "value": 31.5, "misread": 1},
            {"glg": "pCm", "edge": "fresh_basement_min_rho", "boreholes": 8, "below": 28, "above": 8,
             "base": 3000.0, "misread_base": 4, "fitted": True, "value": 1500.0, "misread": 0},
            {"glg": "Qe", "edge": "fresh_basement_min_rho", "boreholes": 2, "below": 3, "above": 2,
             "base": 3000.0, "misread_base": 1, "fitted": False, "value": None, "misread": None},
        ],
        "weights": {"successes": 12, "failures": 11, "base": dict(VESConfig().suitability_weights),
                    "right_base": 0.61, "fitted": True, "value": dict(_WEIGHTS), "right": 0.74},
    }
    s.update(changes)
    return s


def _in_force(**changes) -> Config:
    return CS.apply_set(Config(), _set(**changes))


def _sounding(e, n, zone):
    return SimpleNamespace(site=SimpleNamespace(easting=e, northing=n, utm_zone=zone))


# ------------------------------------------------------------- in force

def test_only_an_adopted_set_or_the_default_goes_in_force():
    candidate = _set(version=None, adopted_by="", adopted_on="", replaces=None)
    with pytest.raises(ValueError, match="not been adopted by anyone"):
        CS.apply_set(Config(), candidate)
    assert CS.apply_set(Config(), CS.default_set()).calibration is None
    config = _in_force()
    assert config.calibration["version"] == 3 and CS.in_force(config)["adopted_by"] == "A. Kamara"
    assert CS.in_force(Config()) == CS.default_set()


def test_putting_a_set_in_force_leaves_the_configuration_given_alone():
    config = Config()
    held = CS.apply_set(config, _set())
    assert config.calibration is None and config.ves.suitability_weights == VESConfig().suitability_weights
    assert held.ves.suitability_weights == _WEIGHTS


def test_a_set_without_weights_leaves_the_configurations_or_puts_the_toolkits_back():
    config = Config()
    config.ves.suitability_weights = dict(_WEIGHTS, aquifer_thickness=0.3, basal_fracture=0.5)
    assert CS.apply_set(config, _set(weights=None)).ves.suitability_weights == config.ves.suitability_weights
    replaced = CS.apply_set(_in_force(), _set(weights=None, version=4))
    assert replaced.ves.suitability_weights == VESConfig().suitability_weights
    assert CS.apply_set(_in_force(), CS.default_set()).ves.suitability_weights == VESConfig().suitability_weights


def test_a_config_file_names_the_set_to_put_in_force(tmp_path):
    (tmp_path / "calibration.yaml").write_text(CS.set_yaml(_set()), encoding="utf-8")
    (tmp_path / "config.yaml").write_text("odds:\n  success_yield_m3_per_h: 1.0\ncalibration: calibration.yaml\n",
                                          encoding="utf-8")
    config = Config.load(tmp_path / "config.yaml")
    assert config.calibration == CS.clean_set(_set()) and config.ves.suitability_weights == _WEIGHTS
    # dumped with the set in it, and read back the same
    config.dump(tmp_path / "again.yaml")
    assert Config.load(tmp_path / "again.yaml").calibration == config.calibration


def test_a_config_file_cannot_put_an_unadopted_set_in_force(tmp_path):
    (tmp_path / "calibration.yaml").write_text(
        CS.set_yaml(_set(version=None, adopted_by="", adopted_on="", replaces=None)), encoding="utf-8")
    (tmp_path / "config.yaml").write_text("calibration: calibration.yaml\n", encoding="utf-8")
    with pytest.raises(ValueError, match="nothing changes until a named person adopts it"):
        Config.load(tmp_path / "config.yaml")


# --------------------------------------------------------------- the prior

def test_a_fitted_row_gives_the_prior_and_says_so():
    config = _in_force()
    o = prior_odds("B-L", "pCm", config)
    assert (o.prior, o.effective_n, o.status, o.matched) == (0.6123, 22.0, "calibrated", "combination")
    assert (o.base_rate, o.fitted_boreholes, o.fitted_successes, o.set_version) == (
        prior_for("B-L", "pCm", 1.0)["rate"], 12, 9, 3)
    assert odds_headline(o).endswith("Prior fitted in calibration set 3.")
    text = odds_prior_text(o)
    assert text.startswith("The prior is 61 percent") and "the table's 43 percent" in text
    assert "fitted to 12 boreholes drilled there, 9 of which succeeded, in calibration set 3" in text
    assert "held as firmly as 22 boreholes" in text


def test_a_fitted_class_row_gives_the_prior_of_a_unit_it_does_not_list():
    o = prior_odds("I-L", "Kc", _in_force())
    assert (o.prior, o.matched, o.status) == (0.3299, "class", "calibrated")
    assert "the class's row applies" in odds_prior_text(o) and "drilled on the class" in odds_prior_text(o)


def test_a_row_the_set_did_not_fit_keeps_the_tables_prior():
    for code, glg in (("CSF-L/M", "pCm"), ("U-M/H", "Qe"), ("n/a", None), (None, None)):
        held, plain = prior_odds(code, glg, _in_force()), prior_odds(code, glg, Config())
        assert (held.prior, held.status, held.effective_n) == (plain.prior, plain.status, plain.effective_n)
        assert held.calibration != plain.calibration


def test_a_set_fitted_at_another_definition_of_success_fits_no_prior_here():
    config = _in_force()
    config.odds.success_yield_m3_per_h = 3.6
    o = prior_odds("B-L", "pCm", config)
    assert o.status == "provisional" and o.prior == pytest.approx(prior_for("B-L", "pCm", 3.6)["rate"])


def test_the_survey_evidence_moves_a_fitted_prior_as_it_moves_the_tables():
    interp = interpret_model(None, LayeredModel(resistivities=[300.0, 120.0, 5000.0], thicknesses=[3.0, 25.0],
                                                sounding_id="VES 1"))
    held, plain = success_odds(interp, None, "B-L", "pCm", _in_force()), success_odds(interp, None, "B-L", "pCm")
    ratio = lambda o: (o.posterior_odds / o.prior_odds)  # noqa: E731
    assert ratio(held) == pytest.approx(ratio(plain), rel=1e-12)
    assert held.probability > plain.probability


def test_every_report_names_the_set_and_what_else_it_changes():
    o = prior_odds("U-M/H", "Qe", _in_force())
    assert o.calibration == ("calibration set 3, fitted on 2027-03-01 to 12 boreholes and adopted by A. Kamara "
                             "on 2027-03-02")
    basis = odds_basis_text(o)[1]
    assert "calibration: calibration set 3, fitted on 2027-03-01" in basis
    assert basis.endswith("Calibration set 3 reads the USGS unit pCm with clay up to 31.5 ohm-m and fresh "
                          "basement from 1,500 ohm-m. Calibration set 3 weights the suitability score's parts "
                          "0.25 (aquifer thickness), 0.1 (resistivity fit), 0.1 (overburden) and 0.55 (basal "
                          "fracture).")
    assert odds_basis_text(prior_odds("U-M/H", "Qe"))[1].endswith("not calibrated against drilled outcomes. "
                                                                  "The band is the 10th to 90th percentile of a "
                                                                  "Beta prior with the table's effective sample "
                                                                  "size, carried through the same factors; the "
                                                                  "factors themselves are provisional choices. The "
                                                                  "suitability score is kept beside these odds for "
                                                                  "comparison.")
    assert CS.set_changes(CS.default_set()) == [] and CS.set_changes(_set(edges=[], weights=None)) == []


def test_the_ledger_records_the_set_a_forecast_was_made_with():
    o = prior_odds("B-L", "pCm", _in_force())
    held = L._odds(o)
    assert held["status"] == "calibrated" and held["calibration"].startswith("calibration set 3")


# --------------------------------------------------------------- the edges

def test_a_unit_is_read_by_its_fitted_edges_and_others_by_the_configurations():
    config = _in_force()
    assert CS.unit_edges(config.calibration, "pCm") == {"clay_max_rho": 31.5, "fresh_basement_min_rho": 1500.0}
    pcm = CS.config_for_unit(config, "pCm")
    assert (pcm.ves.clay_max_rho, pcm.ves.fresh_basement_min_rho) == (31.5, 1500.0)
    assert pcm.ves.fractured_zone_rho == config.ves.fractured_zone_rho and pcm.calibration == config.calibration
    for glg in ("Qe", None, "Kc"):
        assert CS.config_for_unit(config, glg) is config


def test_a_sounding_is_read_by_the_edges_of_the_unit_under_it():
    config = _in_force()
    assert CS.config_for_sounding(config, _sounding(*_PCM)).ves.fresh_basement_min_rho == 1500.0
    assert CS.config_for_sounding(config, _sounding(*_QE)) is config
    # no position of its own: the site's, else nothing to look up
    nowhere = _sounding(None, None, None)
    assert CS.config_for_sounding(config, nowhere) is config
    from groundwater.siting.odds import point_latlon

    site = point_latlon(SimpleNamespace(site_easting=_PCM[0], site_northing=_PCM[1]), _PCM[2], None)
    assert CS.config_for_sounding(config, nowhere, fallback=site).ves.clay_max_rho == 31.5
    # with no edge fitted nothing is looked up at all
    plain, unedged = Config(), _in_force(edges=[])
    assert CS.config_for_sounding(plain, _sounding(*_PCM)) is plain
    assert CS.config_for_sounding(unedged, _sounding(*_PCM)) is unedged


def test_a_fitted_basement_edge_moves_the_depth_to_basement():
    # 2,000 ohm-m under 20 m of weathered rock: compact rock by the edge in
    # force, fresh basement by pCm's
    model = LayeredModel(resistivities=[400.0, 90.0, 2000.0, 5000.0], thicknesses=[2.0, 18.0, 10.0],
                         sounding_id="VES 1")
    plain = interpret_model(None, model, Config().ves)
    held = interpret_model(None, model, CS.config_for_unit(_in_force(), "pCm").ves)
    assert plain.layers[2].unit != "fresh basement" and held.layers[2].unit == "fresh basement"
    assert (plain.depth_to_basement_m, held.depth_to_basement_m) == (30.0, 20.0)


def test_fitting_against_a_set_in_force_starts_from_its_edges_and_weights():
    from test_calibration_sets import _entry

    pooled = [_entry(k, glg="pCm") for k in range(5)]
    edges, _ = CS.fit_edges(pooled, _in_force())
    assert [row["base"] for row in edges] == [31.5, 1500.0]
    weights, _ = CS.fit_weights(pooled, _in_force())
    assert weights["base"] == _WEIGHTS


# ------------------------------------------------------------- the weights

def test_the_set_in_force_weights_the_suitability_score():
    interps = [interpret_model(None, LayeredModel(resistivities=[300.0, 120.0, 5000.0], thicknesses=[3.0, h],
                                                  sounding_id=f"VES {k}"))
               for k, h in enumerate((8.0, 25.0, 40.0))]
    plain, held = assess_siting(interps, Config().ves), assess_siting(interps, _in_force().ves)
    for p, h in zip(sorted(plain, key=lambda r: r.index), sorted(held, key=lambda r: r.index), strict=True):
        c = h.components
        assert h.suitability == round(100 * (0.25 * c.aquifer_thickness + 0.1 * c.resistivity_fit
                                             + 0.1 * c.overburden + 0.55 * c.basal_fracture), 1)
        assert p.components == h.components


def test_the_weights_in_force_do_not_invert_a_survey_again():
    sounding = SimpleNamespace(sounding_id="VES 1", array_type="schlumberger", ab2=[1.0, 2.0, 4.0],
                               mn=[0.5, 0.5, 0.5], rho_app=[100.0, 80.0, 60.0])
    assert inversion_key(sounding, _in_force().ves) == inversion_key(sounding, Config().ves)


# ------------------------------------------- the browser's engine, held to it

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const cases = JSON.parse(readFileSync(0, 'utf8'));
function attempt(f) {
  try { return { ok: f() }; } catch (e) { return { threw: String(e && e.message || e) }; }
}
process.stdout.write(JSON.stringify(cases.map((r) => {
  try {
    const applied = attempt(() => C.withConfig(Object.assign({}, r.settings, r.set ? { calibration: r.set } : {})));
    if (applied.threw) return { ok: { refused: applied.threw } };
    const cfg = applied.ok;
    const interps = r.models.map((m, k) => C.interpretModel(null, C.layeredModel(m[0], m[1]),
      C.configForUnit(cfg, r.units[k % r.units.length])));
    return { ok: {
      weights: cfg.ves.suitability_weights,
      calibration: cfg.calibration || null,
      odds: r.grounds.map((g) => {
        const o = C.priorOdds(g[0], g[1], cfg);
        return { odds: o, headline: C.oddsHeadline(o), prior: C.oddsPriorText(o), basis: C.oddsBasisText(o) };
      }),
      success: interps.map((interp, k) => {
        const g = r.grounds[k % r.grounds.length];
        const o = C.successOdds(interp, null, g[0], g[1], cfg);
        return { odds: o, text: C.oddsText(o) };
      }),
      units: r.units.map((glg) => { const v = C.configForUnit(cfg, glg).ves;
        return [v.clay_max_rho, v.fresh_basement_min_rho]; }),
      sounding: r.positions.map((p) => C.configForSounding(cfg, { site: { easting: p[0], northing: p[1],
        utm_zone: p[2] } }).ves.fresh_basement_min_rho),
      interps: interps.map((i) => [i.depth_to_basement_m, i.layers.map((l) => l.unit)]),
      siting: C.assessSiting(interps, cfg.ves).map((s) => [s.index, s.suitability, s.rank]),
      changes: C.setChanges(C.inForce(cfg)),
    } };
  } catch (e) {
    return { threw: String(e && e.stack || e) };
  }
})));
"""

_GROUNDS = [["B-L", "pCm"], ["B-L", "Pi"], ["I-L", "Pi"], ["I-L", "Mi"], ["CSF-L/M", "pCm"], ["U-M/H", "Qe"],
            ["n/a", None], [None, None], ["B-L", None]]
_UNITS = ["pCm", "Qe", "Pi", None]
_POSITIONS = [list(_PCM), list(_QE), [None, None, None], [250000.0, 900000.0, None]]


def _case(seed: int) -> dict:
    rng = random.Random(seed)
    choice = seed % 6
    if choice == 0:
        s = None
    elif choice == 1:
        s = _set()
    elif choice == 2:
        s = _set(weights=None, success_yield_m3_per_h=3.6)
    elif choice == 3:
        s = _set(version=None, adopted_by="", adopted_on="", replaces=None)
    elif choice == 4:
        s = CS.default_set()
    else:
        from test_calibration_sets import _case as portfolio

        items = portfolio(seed)["items"]
        config = Config()
        config.ledger.fit_min_boreholes = 2
        config.ledger.fit_weights_min_each = 2
        fitted = CS.fit_set(L.pool_ledgers([tuple(i) for i in items]), "2027-01-01", config)
        s = json.loads(json.dumps(CS.adopt_set(fitted, "Seeded Person", "2027-01-02")))
    models = [[[round(rng.uniform(100, 900), 1), round(rng.uniform(10, 400), 1), round(rng.uniform(800, 6000), 1)],
               [round(rng.uniform(1, 4), 1), round(rng.uniform(4, 40), 1)]] for _ in range(4)]
    settings = {"odds": {"success_yield_m3_per_h": rng.choice([1.0, 1.0, 3.6])}}
    return {"set": s, "settings": settings, "grounds": _GROUNDS, "units": _UNITS, "positions": _POSITIONS,
            "models": models}


def _config(case: dict) -> Config:
    config = Config()
    for section, values in case["settings"].items():
        for key, value in values.items():
            setattr(getattr(config, section), key, value)
    return CS.apply_set(config, case["set"]) if case["set"] else config


def _python(case: dict) -> dict:
    try:
        config = _config(case)
    except ValueError as exc:
        return {"refused": str(exc)}
    from groundwater.siting.odds import odds_text

    interps = [interpret_model(None, LayeredModel(resistivities=m[0], thicknesses=m[1]),
                               CS.config_for_unit(config, case["units"][k % len(case["units"])]).ves)
               for k, m in enumerate(case["models"])]
    out = {"weights": config.ves.suitability_weights, "calibration": config.calibration, "odds": [], "success": []}
    for code, glg in case["grounds"]:
        o = prior_odds(code, glg, config)
        out["odds"].append({"odds": dataclasses.asdict(o), "headline": odds_headline(o),
                            "prior": odds_prior_text(o), "basis": odds_basis_text(o)})
    for k, interp in enumerate(interps):
        code, glg = case["grounds"][k % len(case["grounds"])]
        o = success_odds(interp, None, code, glg, config)
        out["success"].append({"odds": dataclasses.asdict(o), "text": odds_text(o)})
    out["units"] = [[CS.config_for_unit(config, glg).ves.clay_max_rho,
                     CS.config_for_unit(config, glg).ves.fresh_basement_min_rho] for glg in case["units"]]
    out["sounding"] = [CS.config_for_sounding(config, _sounding(*p)).ves.fresh_basement_min_rho
                       for p in case["positions"]]
    out["interps"] = [[i.depth_to_basement_m, [layer.unit for layer in i.layers]] for i in interps]
    out["siting"] = [[s.index, s.suitability, s.rank] for s in assess_siting(interps, config.ves)]
    out["changes"] = CS.set_changes(CS.in_force(config))
    return json.loads(json.dumps(out, default=lambda v: None if isinstance(v, float) and not math.isfinite(v)
                                 else v))


def _close(js, py, path=""):
    """The first place two answers part: numbers to 1e-9 relative (the
    odds' lognormal and Beta percentiles take logarithms, which the two
    engines need not round alike), everything else exactly."""
    numbers = isinstance(js, (int, float)) and isinstance(py, (int, float)) and not isinstance(js, bool)
    if (isinstance(py, float) or isinstance(js, float)) and numbers:
        return None if math.isclose(js, py, rel_tol=1e-9, abs_tol=1e-12) else f"{path}: js {js} vs py {py}"
    if isinstance(py, dict) and isinstance(js, dict):
        if set(py) != set(js):
            return f"{path}: keys js {sorted(js)} vs py {sorted(py)}"
        return next((d for d in (_close(js[k], py[k], f"{path}.{k}") for k in py) if d), None)
    if isinstance(py, list) and isinstance(js, list):
        if len(py) != len(js):
            return f"{path}: length js {len(js)} vs py {len(py)}"
        return next((d for d in (_close(a, b, f"{path}[{i}]")
                                 for i, (a, b) in enumerate(zip(js, py, strict=True))) if d), None)
    return None if js == py else f"{path}: js {js!r} vs py {py!r}"


SEEDS = range(18)


@pytest.fixture(scope="module")
def browser_answers(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path_factory.mktemp("in_force") / "in_force.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS)], input=json.dumps([_case(s) for s in SEEDS]),
                          capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_browser_puts_the_same_set_in_force(browser_answers, seed):
    answer = browser_answers[seed]
    assert "threw" not in answer, answer.get("threw")
    found = _close(answer["ok"], _python(_case(seed)))
    assert found is None, found


def test_the_seeded_cases_reach_every_rule():
    told = [_python(_case(seed)) for seed in SEEDS]
    assert any("refused" in t for t in told)
    statuses = {o["odds"]["status"] for t in told if "odds" in t for o in t["odds"]}
    assert {"calibrated", "provisional", "fallback"} <= statuses
    assert any(t.get("changes") for t in told) and any(t.get("changes") == [] for t in told)
    assert {tuple(u) for t in told if "units" in t for u in t["units"]} >= {(31.5, 1500.0), (20.0, 3000.0)}
    assert len({json.dumps(t["siting"]) for t in told if "siting" in t}) > 1
    assert copy.deepcopy(told) == told

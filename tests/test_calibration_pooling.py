"""Pooled evidence without pooled data (PLAN.md step 5.5): calibration sets
from several organisations pooled into one, and the set file that makes it
possible, holding counts and not projects."""

from __future__ import annotations

import copy
import json
import math
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from groundwater import calibration_sets as CS
from groundwater import ledger as L
from groundwater.config import Config
from groundwater.siting.odds import prior_for

from test_calibration_sets import _case, _entry, _format_one, _ledger, _parts, _settings

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"

#: Logs and best fits that fit a clay edge between 12 and 140 ohm-m and a
#: basement edge between 140 and the basement's resistivity.
_LOG = [[0.0, 2.0, "laterite"], [2.0, 8.0, "clay"], [8.0, 22.0, "weathered"], [22.0, 50.0, "basement"]]


def _layers(clay: float, weathered: float, basement: float) -> list:
    return [[0.0, 2.0, 900.0], [2.0, 8.0, clay], [8.0, 22.0, weathered], [22.0, None, basement]]


def _issued(entries: list, organisation: str, on: str = "2026-10-20", config: Config | None = None,
            **adopt) -> dict:
    """A set fitted to ``entries`` and adopted for ``organisation``."""
    s = CS.fit_set(entries, on, config)
    return CS.adopt_set(s, adopt.pop("by", "A. Kamara"), adopt.pop("adopted_on", on), organisation=organisation,
                        **adopt)


def _plain(start: int, n: int, successes: int, **entry) -> list:
    """Boreholes sited without evidence that moved their odds: each one's
    chance is its prior, so the count each set adds is its successes."""
    return [_entry(start + k, p=0.55, prior=0.55, success=k < successes, **entry) for k in range(n)]


# ---------------------------------------------------------------- the prior

def test_each_grounds_counts_are_summed_over_one_provisional_prior():
    a = _issued(_plain(0, 7, 4), "Rural Water Trust")
    b = _issued(_plain(100, 9, 7), "Kono Wells")
    pooled = CS.pool_sets([a, b], "2026-10-28")
    (row,) = pooled["prior"]
    base = prior_for("B-L", "pCm", 1.0)["rate"]
    assert (row["boreholes"], row["successes"], row["expected"]) == (16, 11, 11.0)
    # the provisional prior's ten boreholes counted once, not once a set
    assert row["effective_n"] == 26.0
    assert row["rate"] == round((10 * base + 11) / 26, 4)
    # which is the set the two ledgers give fitted together, where no
    # evidence moved the odds
    together = CS.fit_set(_plain(0, 7, 4) + _plain(100, 9, 7), "2026-10-28")["prior"]
    assert pooled["prior"] == together


def test_the_evidence_adjusted_counts_are_summed_as_each_set_worked_them_out():
    a = _issued([_entry(k, p=0.8, prior=0.6, success=k < 5) for k in range(6)], "Rural Water Trust")
    b = _issued([_entry(100 + k, p=0.4, prior=0.6, success=k < 2) for k in range(5)], "Kono Wells")
    (row,) = CS.pool_sets([a, b], "2026-10-28")["prior"]
    assert row["expected"] == round(a["prior"][0]["expected"] + b["prior"][0]["expected"], 2)
    assert row["successes"] == 7 and row["expected"] != 7


def test_a_row_too_small_to_fit_in_each_set_is_fitted_in_the_sum():
    a = _issued(_plain(0, 3, 2, code="I-L", glg="Pi") + _plain(10, 6, 3), "Rural Water Trust")
    b = _issued(_plain(100, 4, 1, code="I-L", glg="Pi"), "Kono Wells", config=_ledger(fit_min_boreholes=4))
    assert [r["fitted"] for r in a["prior"]] == [True, False] and b["prior"][0]["fitted"]
    pooled = CS.pool_sets([a, b], "2026-10-28")
    assert [(r["bgs_code"], r["glg"], r["boreholes"], r["fitted"]) for r in pooled["prior"]] == [
        ("B-L", "pCm", 6, True), ("I-L", "Pi", 7, True)]
    # the minimum is the one in force where the sets are pooled
    assert not CS.pool_sets([a, b], "2026-10-28", _ledger(fit_min_boreholes=8))["prior"][1]["fitted"]


def test_a_set_with_no_row_for_a_ground_leaves_its_rate_as_the_other_set_fitted_it():
    a = _issued([_entry(k, p=0.7, prior=0.55, success=k % 3 != 0) for k in range(11)], "Rural Water Trust")
    b = _issued(_plain(100, 6, 3, code="I-L", glg="Pi"), "Kono Wells")
    pooled = CS.pool_sets([a, b], "2026-10-28")
    assert pooled["prior"][0] == a["prior"][0]
    assert pooled["prior"][1] == b["prior"][0]


def test_the_counts_left_out_are_summed():
    a = _issued(_plain(0, 6, 3) + [_entry(50, success=None)], "Rural Water Trust")
    b = _issued(_plain(100, 6, 3) + [_entry(150 + k, judged_at=3.6) for k in range(2)], "Kono Wells")
    assert CS.pool_sets([a, b], "2026-10-28")["left_out"] == {"unknown": 1, "definition": 2}


# ---------------------------------------------------------------- the edges

def test_an_edge_is_the_mean_of_the_sets_edges_in_logarithms_weighted_by_their_boreholes():
    a = _issued([_entry(k, layers=_layers(12.0, 140.0, 2400.0)) for k in range(6)], "Rural Water Trust")
    b = _issued([_entry(100 + k, layers=_layers(30.0, 260.0, 1600.0)) for k in range(9)], "Kono Wells")
    clay_a, basement_a = a["edges"]
    clay_b, basement_b = b["edges"]
    pooled = CS.pool_sets([a, b], "2026-10-28")
    clay, basement = pooled["edges"]
    for edge, one, two in ((clay, clay_a, clay_b), (basement, basement_a, basement_b)):
        mean = math.exp((6 * math.log(one["value"]) + 9 * math.log(two["value"])) / 15)
        assert edge["value"] == round(mean, 1) and edge["fitted"] and edge["sets"] == 2
        assert (edge["boreholes"], edge["below"], edge["above"]) == (
            15, one["below"] + two["below"], one["above"] + two["above"])
        # no set carried its layers, so nothing says how many it misreads
        assert edge["misread"] is None and edge["misread_base"] is None
    low, high = sorted([basement_a["value"], basement_b["value"]])
    assert low < basement["value"] < high


def test_an_edge_no_set_fitted_is_counted_and_not_fitted():
    a = _issued([_entry(k, layers=_layers(12.0, 140.0, 2400.0)) for k in range(3)] + _plain(10, 5, 3, glg="Pi"),
                "Rural Water Trust")
    b = _issued([_entry(100 + k, layers=_layers(30.0, 260.0, 1600.0)) for k in range(4)], "Kono Wells")
    pooled = CS.pool_sets([a, b], "2026-10-28")
    pcm = [e for e in pooled["edges"] if e["glg"] == "pCm"]
    assert [(e["fitted"], e["sets"], e["boreholes"], e["value"]) for e in pcm] == [(False, 0, 7, None),
                                                                                    (False, 0, 7, None)]


def _hand_set(edges: list, organisation: str, by: str = "A. Kamara") -> dict:
    """An adopted set holding only these edge rows, as a file may."""
    rows = [{"glg": glg, "edge": edge, "boreholes": n, "below": n, "above": n, "base": 20.0 if edge == "clay_max_rho"
             else 3000.0, "misread_base": 0, "fitted": value is not None, "value": value,
             "misread": 0 if value is not None else None} for glg, edge, n, value in edges]
    s = dict(CS.default_set(), licence="CC BY 4.0", organisation=organisation, version=1, fitted_on="2026-10-01",
             adopted_by=by, adopted_on="2026-10-02", success_yield_m3_per_h=1.0, boreholes=10, edges=rows)
    return CS.clean_set(s)


def test_a_pooled_clay_edge_stays_under_the_water_bearing_window():
    a = _hand_set([("pCm", "clay_max_rho", 5, 700.0)], "Rural Water Trust")
    b = _hand_set([("pCm", "clay_max_rho", 5, 1000.0)], "Kono Wells")
    (clay,) = CS.pool_sets([a, b], "2026-10-28")["edges"]
    assert (clay["fitted"], clay["value"], clay["sets"]) == (False, None, 2)
    review = CS.set_review(CS.pool_sets([a, b], "2026-10-28"))
    assert review["tables"][-1]["rows"][0][4] == ("not fitted: pooled, it would not stay under the top of the "
                                                  "water-bearing window")
    # under a window that starts higher it is fitted
    config = Config()
    config.ves.fractured_zone_rho = (config.ves.fractured_zone_rho[0], 1000.0)
    (clay,) = CS.pool_sets([a, b], "2026-10-28", config)["edges"]
    assert clay["fitted"] and clay["value"] == round(math.sqrt(700.0 * 1000.0), 1)


def test_a_pooled_basement_edge_stays_over_the_clay_edge_it_is_read_with():
    # one set fitted pCm's clay edge at 150, the other its basement at 120
    a = _hand_set([("pCm", "clay_max_rho", 5, 150.0)], "Rural Water Trust")
    b = _hand_set([("pCm", "fresh_basement_min_rho", 5, 120.0)], "Kono Wells")
    clay, basement = CS.pool_sets([a, b], "2026-10-28")["edges"]
    assert clay["fitted"] and clay["value"] == 150.0
    assert (basement["fitted"], basement["value"], basement["sets"]) == (False, None, 1)
    review = CS.set_review(CS.pool_sets([a, b], "2026-10-28"))
    assert review["tables"][-1]["rows"][1][4] == "not fitted: pooled, it would not stay over the clay edge"
    # without a pooled clay edge for the unit, it is read with the
    # configuration's 20 ohm-m, and clears it
    c = _hand_set([("Pi", "clay_max_rho", 5, 150.0)], "Rural Water Trust")
    (basement,) = [e for e in CS.pool_sets([c, b], "2026-10-28")["edges"] if e["glg"] == "pCm"]
    assert basement["fitted"] and basement["value"] == 120.0


def test_the_edges_in_force_are_shown_beside_the_pooled_ones():
    a = _issued([_entry(k, layers=_layers(12.0, 140.0, 2400.0)) for k in range(6)], "Rural Water Trust")
    b = _issued([_entry(100 + k, layers=_layers(30.0, 260.0, 1600.0)) for k in range(9)], "Kono Wells")
    config = CS.apply_set(Config(), a)
    pooled = CS.pool_sets([a, b], "2026-10-28", config)
    assert [e["base"] for e in pooled["edges"]] == [a["edges"][0]["value"], a["edges"][1]["value"]]
    assert [e["base"] for e in CS.pool_sets([a, b], "2026-10-28")["edges"]] == [20.0, 3000.0]


# ------------------------------------------------------------ the pooled set

def _three() -> tuple[dict, dict, dict]:
    a = _issued([_entry(k, success=k % 3 != 0, parts=_parts(0.5, 0.5, 0.5, 0.9 if k % 3 else 0.1))
                 for k in range(30)], "Rural Water Trust", contact="wells@example.org")
    b = _issued([_entry(100 + k, layers=_layers(30.0, 260.0, 1600.0), success=k % 2 == 0) for k in range(9)],
                "Kono Wells", on="2026-09-01", by="B. Sesay")
    c = _issued(_plain(200, 6, 2, code="I-L", glg="Pi"), "Bo District Council", on="2026-08-15", by="F. Koroma")
    return a, b, c


def test_a_pooled_set_lists_its_sources_and_holds_no_borehole_count_or_weights():
    a, b, c = _three()
    pooled = CS.pool_sets([a, b, c], "2026-10-28")
    assert (pooled["version"], pooled["adopted_by"], pooled["fitted_on"]) == (None, "", "2026-10-28")
    assert pooled["licence"] == "CC BY 4.0" and pooled["boreholes"] is None and pooled["weights"] is None
    assert sorted(s["organisation"] for s in pooled["sources"]) == ["Bo District Council", "Kono Wells",
                                                                   "Rural Water Trust"]
    trust = next(s for s in pooled["sources"] if s["organisation"] == "Rural Water Trust")
    assert trust == {"organisation": "Rural Water Trust", "contact": "wells@example.org", "licence": "CC BY 4.0",
                     "version": 1, "fitted_on": "2026-10-20", "adopted_by": "A. Kamara",
                     "adopted_on": "2026-10-20", "boreholes": 30, "sets": 0,
                     "fingerprint": CS.set_fingerprint(a), "pools": []}
    assert CS.set_name(pooled) == "a calibration set pooled on 2026-10-28 from 3 sets, not adopted by anyone"
    adopted = CS.adopt_set(pooled, "C. Conteh", "2026-10-29", organisation="Salone Water Forum")
    assert CS.set_name(adopted) == ("calibration set 1, pooled on 2026-10-28 from 3 sets and adopted by "
                                    "C. Conteh on 2026-10-29")
    assert CS.read_set(CS.set_yaml(adopted)) == adopted


def test_the_order_of_the_sets_makes_no_difference():
    a, b, c = _three()
    once = CS.set_yaml(CS.pool_sets([a, b, c], "2026-10-28"))
    for order in ([c, a, b], [b, c, a], [c, b, a]):
        assert CS.set_yaml(CS.pool_sets(order, "2026-10-28")) == once


def test_a_pooled_set_can_be_pooled_again_and_names_every_set_it_holds():
    a, b, c = _three()
    first = CS.adopt_set(CS.pool_sets([a, b], "2026-10-28"), "C. Conteh", "2026-10-29",
                         organisation="Salone Water Forum")
    again = CS.pool_sets([first, c], "2026-11-02")
    held = next(s for s in again["sources"] if s["organisation"] == "Salone Water Forum")
    assert held["sets"] == 2 and held["boreholes"] is None
    assert held["pools"] == sorted([CS.set_fingerprint(a), CS.set_fingerprint(b)])
    # the counts are those of the three sets pooled at once
    assert again["prior"] == CS.pool_sets([a, b, c], "2026-11-02")["prior"]


def test_a_pooled_set_in_force_gives_its_priors_and_edges_and_the_toolkits_weights():
    a, b, _ = _three()
    weighted = CS.apply_set(Config(), a)
    assert weighted.ves.suitability_weights == a["weights"]["value"]
    pooled = CS.adopt_set(CS.pool_sets([a, b], "2026-10-28"), "C. Conteh", "2026-10-29", in_force=a)
    config = CS.apply_set(weighted, pooled)
    assert config.calibration == pooled
    fitted = prior_for("B-L", "pCm", 1.0, config.calibration)
    assert fitted["status"] == "calibrated" and fitted["fitted_boreholes"] == 39
    assert CS.config_for_unit(config, "pCm").ves.fresh_basement_min_rho == pooled["edges"][1]["value"]
    # it fits no weights, so the toolkit's are put back
    assert config.ves.suitability_weights == Config().ves.suitability_weights


def test_the_fingerprint_is_of_what_a_set_counts_not_of_who_issued_it():
    a, b, _ = _three()
    print_a = CS.set_fingerprint(a)
    assert len(print_a) == 64
    assert CS.set_fingerprint(dict(a, organisation="Someone Else", contact="", licence="CC0")) == print_a
    assert CS.set_fingerprint(dict(a, version=7, adopted_by="B. Sesay", adopted_on="2027-01-01")) == print_a
    assert CS.set_fingerprint(dict(a, fitted_on="2027-01-01")) == print_a
    changed = copy.deepcopy(a)
    changed["prior"][0]["successes"] -= 1
    assert CS.set_fingerprint(changed) != print_a
    # a file of format 1 is the same set as the file of format 2 it became,
    # and a file that is not a set has no fingerprint
    assert CS.set_fingerprint(_format_one(a)) == print_a
    with pytest.raises(ValueError, match="not a calibration set the toolkit can read"):
        CS.set_fingerprint(dict(a, prior="none"))


# --------------------------------------------------------------- refusals

def test_pooling_needs_two_sets():
    a, _, _ = _three()
    for sets in ([], [a]):
        with pytest.raises(ValueError, match="needs at least two calibration sets"):
            CS.pool_sets(sets, "2026-10-28")


@pytest.mark.parametrize("change, why", [
    (lambda a, b: [a, None], "b.yaml: This is not a calibration set the toolkit can read: the file does not hold"),
    (lambda a, b: [a, dict(b, format_version=7)], "b.yaml: This is not a calibration set"),
    (lambda a, b: [a, CS.default_set()], "b.yaml is the toolkit's provisional default, which holds nothing"),
    (lambda a, b: [dict(a, version=None, adopted_by="", adopted_on="", replaces=None), b],
     "a.yaml has not been adopted by anyone"),
    (lambda a, b: [a, dict(b, licence="")], "b.yaml declares no licence"),
    (lambda a, b: [a, _format_one(b)], "b.yaml declares no licence, so it cannot be pooled. A set saved before"),
    (lambda a, b: [a, dict(b, success_yield_m3_per_h=None)], "b.yaml does not say at what yield"),
    (lambda a, b: [a, dict(b, success_yield_m3_per_h=3.6)],
     "b.yaml judged its boreholes a success at 3.6 m3/h and a.yaml at 1 m3/h"),
    (lambda a, b: [a, dict(a, organisation="Kono Wells", adopted_by="B. Sesay")],
     "b.yaml and a.yaml are the same set"),
    (lambda a, b: [a, dict(b, licence="CC BY-SA 4.0")],
     "b.yaml is issued under CC BY-SA 4.0, and a pooled set is issued under CC BY 4.0 (ledger.set_licence)"),
])
def test_a_set_that_cannot_be_pooled_is_refused_by_its_file(change, why):
    a, b, _ = _three()
    with pytest.raises(ValueError, match="^" + why.replace(".", r"\.").replace("(", r"\(").replace(")", r"\)")):
        CS.pool_sets(json.loads(json.dumps(change(a, b))), "2026-10-28", labels=["a.yaml", "b.yaml"])


def test_sets_are_pooled_only_under_the_licence_a_pooled_set_is_issued_under():
    a, b, _ = _three()
    with pytest.raises(ValueError, match=r"^No licence is set for the sets this toolkit issues"):
        CS.pool_sets([a, b], "2026-10-28", _ledger(set_licence=" "))
    share = _ledger(set_licence="CC BY-SA 4.0")
    with pytest.raises(ValueError, match=r"^Set 1 is issued under CC BY 4\.0, and a pooled set is issued under "
                                         r"CC BY-SA 4\.0"):
        CS.pool_sets([a, b], "2026-10-28", share)
    alike = [dict(s, licence="CC BY-SA 4.0") for s in (a, b)]
    assert CS.pool_sets(alike, "2026-10-28", share)["licence"] == "CC BY-SA 4.0"


def test_without_file_names_a_set_is_named_by_its_place():
    a, _, _ = _three()
    with pytest.raises(ValueError, match="^Set 2 and Set 1 are the same set"):
        CS.pool_sets([a, a], "2026-10-28")


def test_a_set_and_a_pooled_set_that_holds_it_are_refused():
    a, b, c = _three()
    first = CS.adopt_set(CS.pool_sets([a, b], "2026-10-28"), "C. Conteh", "2026-10-29")
    other = CS.adopt_set(CS.pool_sets([a, c], "2026-10-28"), "D. Turay", "2026-10-29")
    for sets in ([first, a], [b, first], [first, other]):
        with pytest.raises(ValueError, match="hold the counts of one same set"):
            CS.pool_sets(sets, "2026-11-02")
    # deeper down too
    deeper = CS.adopt_set(CS.pool_sets([first, c], "2026-11-02"), "E. Bangura", "2026-11-03")
    with pytest.raises(ValueError, match="hold the counts of one same set"):
        CS.pool_sets([deeper, b], "2026-11-04")


def test_a_set_fitted_from_another_provisional_prior_is_refused():
    a, b, _ = _three()
    other = copy.deepcopy(b)
    other["prior"][0]["base_rate"] = 0.5
    with pytest.raises(ValueError, match="b.yaml fitted the prior of B-L on pCm from another provisional rate"):
        CS.pool_sets([a, other], "2026-10-28", labels=["a.yaml", "b.yaml"])
    unknown = copy.deepcopy(b)
    unknown["prior"][0].update(bgs_code="n/a", glg="*")
    with pytest.raises(ValueError, match="fitted the prior of n/a on any unit"):
        CS.pool_sets([a, unknown], "2026-10-28")


@pytest.mark.parametrize("change, why", [
    (lambda p, a: p.update(boreholes=12), "not whole as a pooled set"),
    (lambda p, a: p.update(weights=a["weights"]), "not whole as a pooled set"),
    (lambda p, a: p["edges"][0].update(misread=1), '"edges.misread"'),
    (lambda p, a: p["edges"][0].update(misread_base=0), '"edges.misread_base"'),
    (lambda p, a: p["edges"][0].pop("sets"), '"edges.sets"'),
    (lambda p, a: p["edges"][0].update(sets=0), '"edges.sets"'),
    (lambda p, a: p["sources"][0].update(fingerprint="ABC"), '"sources.fingerprint"'),
    (lambda p, a: p["sources"][0].update(pools=["x"]), '"sources.pools"'),
    (lambda p, a: p["sources"][0].update(adopted_by=" "), '"sources.adopted_by"'),
    (lambda p, a: p["sources"][0].update(version=0), '"sources.version"'),
    (lambda p, a: p["sources"][0].update(boreholes=None), "not whole as a pooled set"),
    # a set that lists no sources is not a pooled set, so counts boreholes
    (lambda p, a: p.update(sources=[]), "not whole as a pooled set"),
])
def test_a_pooled_set_file_is_read_whole_or_refused(change, why):
    a, b, _ = _three()
    pooled = json.loads(json.dumps(CS.adopt_set(CS.pool_sets([a, b], "2026-10-28"), "C. Conteh", "2026-10-29")))
    CS.clean_set(pooled)
    change(pooled, a)
    with pytest.raises(ValueError, match=why):
        CS.clean_set(pooled)


# ---------------------------------------------------------------- the review

def test_a_pooled_set_is_reviewed_with_its_sources_beside_the_set_in_force():
    a, b, c = _three()
    again = _issued(_plain(300, 5, 3), "Rural Water Trust", on="2026-10-25", by="G. Sesay")
    review = CS.set_review(CS.pool_sets([a, b, c, again], "2026-10-28"))
    assert review["title"] == "Calibration set pooled on 2026-10-28" and review["adoptable"]
    summary = review["summary"]
    assert summary[0].startswith("It pools the 4 calibration sets below, judged at a yield of 1 m3/h.")
    assert any(s.startswith("A pooled set fits no suitability weights") for s in summary)
    assert any(s.startswith("Rural Water Trust issued 2 of these sets.") for s in summary)
    sources, prior, edges = review["tables"]
    assert [t["key"] for t in review["tables"]] == ["sources", "prior", "edges"]
    assert sources["header"] == ["Organisation", "Set", "Licence", "Contact"]
    kono = ("calibration set 1, fitted on 2026-09-01 to 9 boreholes and adopted by B. Sesay on "
            "2026-09-01")
    assert ["Kono Wells", kono, "CC BY 4.0", "not given"] in sources["rows"]
    clay = next(row for row in edges["rows"] if row[:2] == ["pCm", "Clay, up to"])
    assert clay[3] == "20 ohm-m" and clay[4].endswith(" ohm-m, from 3 sets")
    assert prior["rows"][0][0] == "B-L on pCm" and prior["rows"][0][1] == "44"
    assert all(len(row) == len(t["header"]) for t in review["tables"] for row in t["rows"])


# --------------------------------------------- the browser's engine, held to it

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js', 'support.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core, S = sandbox.GWT.support;
const cases = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map((r) => {
  try {
    const cfg = C.withConfig(r.settings);
    const pooled = C.poolSets(r.sets, r.on, cfg, r.labels);
    const adopted = C.adoptSet(pooled, 'C. Conteh', '2026-10-29', null, r.organisation, '');
    const text = C.setYaml(adopted);
    return { ok: { set: pooled, review: C.setReview(pooled, cfg), name: C.setName(adopted), yaml: text,
      read: C.cleanSet(S.parseYaml(text)), prints: r.sets.map((s) => {
        try { return C.setFingerprint(s); } catch (e) { return null; }
      }) } };
  } catch (e) {
    return { threw: String(e && e.message || e) };
  }
})));
"""


#: What each seeded pool does besides pooling sets that can be pooled: the
#: same set twice, a pooled set with a set it holds, a set without a
#: licence, a file of format 1, a pooled set pooled again, a set under
#: another licence, and no licence set to issue a pooled set under.
_TWISTS = ["none", "twice", "none", "chain", "none", "unlicensed", "old", "deeper", "licence", "unset", "none",
           "deeper"]


def _pool_case(seed: int) -> dict:
    """Sets fitted to seeded portfolios under seeded settings and adopted
    for seeded organisations, pooled in a seeded order; some cases pool a
    set twice, a pooled set with one it holds, or a set that cannot be."""
    rng = random.Random(1000 + seed)
    twist = _TWISTS[seed % len(_TWISTS)]
    sets = []
    for k in range(rng.randint(2, 4)):
        case = _case(rng.randint(0, 10 ** 6))
        config = _settings(case["settings"])
        config.odds.success_yield_m3_per_h = 1.0
        config.ledger.set_licence = "CC BY-SA 4.0" if twist == "licence" and k == 0 else " CC  BY 4.0 "
        pooled = L.pool_ledgers([tuple(item) for item in case["items"]])
        fitted = CS.fit_set(pooled, rng.choice(["2026-10-20", "2026-09-01"]), config)
        sets.append(json.loads(json.dumps(CS.adopt_set(fitted, f"Adopter {k}", "2026-10-21", organisation=rng.choice(
            ["Rural Water Trust", "Kono Wells", "", "Ñdoye \"Q\""]), contact=rng.choice(["", "x@y.z"])))))

    def pool_of(two):
        try:
            return json.loads(json.dumps(CS.adopt_set(CS.pool_sets(two, "2026-10-25"), "P", "2026-10-26")))
        except ValueError:
            # the two cannot be pooled (both empty, say): a set of its own
            return json.loads(json.dumps(_issued(_plain(900 + seed, 6, 4), "Late Org")))

    if twist == "twice":
        sets.append(dict(sets[0], organisation="Renamed"))
    elif twist == "chain":
        sets.append(pool_of(sets[:2]))
    elif twist == "unlicensed":
        sets[-1]["licence"] = ""
    elif twist == "old":
        sets.append(_format_one(sets[0]))
    elif twist == "deeper":
        sets = [pool_of(sets[:2])] + sets[2:]
        if len(sets) < 2:
            sets.append(json.loads(json.dumps(_issued(_plain(800 + seed, 6, 4), "Late Org"))))
    rng.shuffle(sets)
    settings = {"ledger": {"fit_min_boreholes": rng.choice([5, 2, 20]),
                           "set_licence": "" if twist == "unset" else "CC BY 4.0"},
                "ves": rng.choice([{}, {"clay_max_rho": 35.0, "fresh_basement_min_rho": 1200.0},
                                   {"fractured_zone_rho": [80.0, 60.0]}])}
    labels = [f"set-{k}.yaml" for k in range(len(sets))] if rng.random() < 0.5 else None
    return {"sets": sets, "settings": settings, "on": rng.choice(["2026-10-28", ""]), "labels": labels,
            "organisation": rng.choice(["", "Salone Water Forum"]), "twist": twist}


def _python(case: dict) -> dict:
    config = _settings(case["settings"])
    try:
        pooled = CS.pool_sets(case["sets"], case["on"], config, case["labels"])
    except ValueError as exc:
        return {"threw": str(exc)}
    adopted = CS.adopt_set(pooled, "C. Conteh", "2026-10-29", organisation=case["organisation"])
    text = CS.set_yaml(adopted)

    def fingerprint(s):
        try:
            return CS.set_fingerprint(s)
        except ValueError:
            return None

    return json.loads(json.dumps({"ok": {
        "set": pooled, "review": CS.set_review(pooled, config), "name": CS.set_name(adopted), "yaml": text,
        "read": CS.read_set(text), "prints": [fingerprint(s) for s in case["sets"]]}}))


SEEDS = range(40)


@pytest.fixture(scope="module")
def browser_answers(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path_factory.mktemp("pool") / "pool.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    cases = [_pool_case(seed) for seed in SEEDS]
    done = subprocess.run([node, str(driver), str(JS)], input=json.dumps(cases), capture_output=True, text=True,
                          encoding="utf-8", check=True)
    return json.loads(done.stdout)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_browser_pools_the_same_set_and_refuses_the_same_sets(browser_answers, seed):
    assert browser_answers[seed] == _python(_pool_case(seed))


def test_the_seeded_pools_reach_every_rule():
    told = [(_pool_case(seed), _python(_pool_case(seed))) for seed in SEEDS]
    made = [t["ok"]["set"] for _, t in told if "ok" in t]
    refused = [t["threw"] for _, t in told if "threw" in t]
    assert len(made) >= 8 and refused
    assert any("are the same set" in r for r in refused) and any("one same set" in r for r in refused)
    assert any("declares no licence" in r for r in refused)
    assert any("a pooled set is issued under" in r for r in refused)
    edges = [e for s in made for e in s["edges"]]
    assert {(e["fitted"], e["sets"] > 0) for e in edges} == {(True, True), (False, False), (False, True)}
    assert any(e["sets"] > 1 for e in edges if e["fitted"])
    rows = [r for s in made for r in s["prior"]]
    assert {r["fitted"] for r in rows} == {True, False}
    assert any(s["sets"] > 0 for p in made for s in p["sources"])

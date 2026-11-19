"""The calibration report (PLAN.md step 5.2), calibration sets (5.3), pooling
them (5.5) and a set in force (5.3b): the "calibration", "calibration_sets",
"calibration_pooling" and "calibration_in_force" entries of
``reference.json``. ``_pick`` draws for the scorecards' projects too, and
``IN_FORCE_SET`` is the set the allocation cases put in force.
"""

from __future__ import annotations

import copy
import dataclasses
import json

from groundwater.config import Config

from .common import _ns


# ------------------------- the calibration report (PLAN.md step 5.2)

#: Survey teams and contractors as typed: one name in two spacings, a name
#: with an accent, letters beyond the Basic Multilingual Plane and a
#: full-width one (which JavaScript's < orders the other way round), a name
#: that is a number, one that is an object's key in JavaScript, and none.
CALIBRATION_TEAMS = ["A. Kamara", "  A.  Kamara", "B. Sesay", "", "Ñdoye", "\U0001d4b5 Team", "ｱ Team",
                     "1", "__proto__"]
CALIBRATION_CONTRACTORS = ["WiNGiN", "Kaba Drilling", "", "Kaba  Drilling ", "\U0001d4b5 Drill", "ｱ Drill"]
#: The ground under a point as its odds read it: a class and a unit, a class
#: alone, no class.
CALIBRATION_GROUND = [("B-L", "pCm"), ("B-L", None), ("CSF-L/M", "pCm"), (None, None), ("U-M/H", "Qe")]
#: Chances on the reliability bins' edges, and two a hand-edited file holds
#: outside 0 to 1.
CALIBRATION_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, -0.1]


def _pick(rng, values):
    """One of ``values``, by random() alone, whose stream every Python keeps."""
    return values[min(len(values) - 1, int(rng.random() * len(values)))]


def _calibration_entry(rng, k: int, inside_share: float, skill: str, priors: bool) -> dict:
    """A ledger entry as a file holds it: a band the depth found falls in
    ``inside_share`` of the time, a chance of success that is informative,
    contrary or the prior itself (``skill``), and the rest drawn."""
    p10 = round(8.0 + 30.0 * rng.random(), 1)
    band = [p10, round(p10 + 4.0, 1), round(p10 + 4.0 + 6.0 * rng.random(), 1)]
    has_band = rng.random() > 0.1
    best = None if rng.random() < 0.08 else round(band[1] + 3.0 * (rng.random() - 0.5), 1)
    total = round(band[2] + 20.0 * rng.random() - 8.0, 1)
    u = rng.random()
    if u < inside_share:
        found = round(band[0] + (band[2] - band[0]) * rng.random(), 1)
    elif u < inside_share + (1.0 - inside_share) / 2.0:
        found = round(max(0.5, band[0] - 1.0 - 6.0 * rng.random()), 1)
    else:
        found = round(band[2] + 1.0 + 8.0 * rng.random(), 1)
    if found > total or rng.random() < 0.1:
        found = None
    prior = 0.55 if priors else (None if rng.random() < 0.3 else 0.55)
    chance = round(rng.random(), 3) if rng.random() > 0.15 else _pick(rng, CALIBRATION_EDGES)
    succeeds = rng.random() < (min(1.0, max(0.0, chance)) if skill == "better" else
                               1.0 - min(1.0, max(0.0, chance)) if skill == "worse" else 0.55)
    if skill == "same":
        chance = prior if prior is not None else 0.55
    success = None if rng.random() < 0.08 else succeeds
    basis = None if success is None else _pick(rng, ["tested", "recorded_failure" if not success
                                                     else "recorded_success"])
    code, glg = _pick(rng, CALIBRATION_GROUND)
    drilled = rng.random() < 0.85
    return {
        "id": f"cal{k:04d}",
        "before_outcome": rng.random() < 0.85,
        "recorded_on": "2026-03-01",
        "toolkit": "0.3.0",
        "point": {"sounding_id": f"VES {k}", "community": "", "district": "", "easting": None,
                  "northing": None, "utm_zone": None},
        "prediction": {
            "depth_to_basement_m": best, "basement_resolved": best is not None,
            "investigation_depth_m": 60.0, "water_zones_m": [], "drilling_depth_m": 40.0,
            "drilling_depth_minimum": False, "basement_band_m": band if has_band else None,
            "survey_team": _pick(rng, CALIBRATION_TEAMS),
            "odds": None if rng.random() < 0.08 else {
                "probability": chance, "low": 0.1, "high": 0.9, "prior": prior, "bgs_code": code, "glg": glg,
                "status": "provisional", "matched": "class"},
        },
        "outcome": None if not drilled else {
            "basement_m": found, "total_depth_m": None if rng.random() < 0.05 else total,
            "status": "Successful" if success else "Dry", "success": success, "success_basis": basis,
            "safe_yield_m3_per_h": None, "success_yield_m3_per_h": 1.0,
            "contractor": _pick(rng, CALIBRATION_CONTRACTORS)},
        "pairing": None,
    }


def _calibration_portfolio(seed: int, n: int, inside_share: float, skill: str, priors: bool = True) -> list:
    import random

    rng = random.Random(seed)
    items, k = [], 0
    for project in ("Rokel", "Kuntolo", "Dr Timbo"):
        entries = []
        for _ in range(n // 3):
            entries.append(_calibration_entry(rng, k, inside_share, skill, priors))
            k += 1
        items.append([project, {"drilled": None, "entries": entries}])
    # a copy of the first project's file, pooled once
    items.append(["Rokel copy", copy.deepcopy(items[0][1])])
    return items


def calibration_reference() -> dict:
    """The calibration report (PLAN.md step 5.2) on pooled portfolios built
    to give each verdict: a band that holds about four in five, one too
    narrow and one too wide; odds that beat the prior, odds that lose to it
    and odds that are the prior; a portfolio too small to judge, one with
    nothing forecast, one with nothing drilled and none at all; each under
    the default settings and others. And the binomial range the band's
    count is judged by (tests/test_calibration.py holds it to scipy's)."""
    from groundwater import calibration as K
    from groundwater import ledger as L

    portfolios = {
        "calibrated": _calibration_portfolio(1, 45, 0.8, "better"),
        "narrow": _calibration_portfolio(2, 36, 0.45, "worse"),
        "wide": _calibration_portfolio(3, 45, 1.0, "same"),
        "priorless": _calibration_portfolio(4, 24, 0.8, "better", priors=False),
        "few": _calibration_portfolio(5, 9, 0.8, "better"),
        "after": [["Rokel", {"entries": [dict(e, before_outcome=False) for e in
                                         _calibration_portfolio(6, 18, 0.8, "better")[0][1]["entries"]]}]],
        "undrilled": [["Rokel", {"entries": [dict(e, outcome=None) for e in
                                             _calibration_portfolio(7, 18, 0.8, "better")[0][1]["entries"]]}]],
        # one borehole in three judged at another definition of success,
        # which the odds and the hit rates count and leave out
        "definition": [
            [name, dict(ledger, entries=[
                dict(e, outcome=dict(e["outcome"], success_yield_m3_per_h=3.0)) if e["outcome"] and k % 3 == 0 else e
                for k, e in enumerate(ledger["entries"])])]
            for name, ledger in _calibration_portfolio(8, 36, 0.8, "better")],
        "empty": [],
    }
    settings = [{}, {"min_boreholes": 3, "min_group": 2, "reliability_bins": 3},
                {"min_boreholes": 40, "min_group": 12, "reliability_bins": 10}]
    # every portfolio under the defaults, and some under each of the others
    others = {1: ("calibrated", "narrow", "few", "definition"), 2: ("wide", "priorless")}
    cases = []
    for name, items in portfolios.items():
        for k, overrides in enumerate(settings):
            if k and name not in others[k]:
                continue
            config = Config()
            for key, value in overrides.items():
                setattr(config.ledger, key, value)
            pooled = L.pool_ledgers([tuple(item) for item in items])
            cases.append({"portfolio": name, "settings": overrides, "issued": "  2026-10-19 " if k else "",
                          "expect": {
                              "depth": K.depth_scores(pooled, config),
                              "odds": K.odds_scores(pooled, config),
                              "hits": {by: K.hit_rates(pooled, by, config) for by in K.GROUPINGS},
                              "content": K.calibration_content(pooled, "  2026-10-19 " if k else "", config)}})
    ranges = [{"n": n, "p": p, "expect": list(K.binomial_range(n, p))}
              for n in (0, 1, 2, 5, 10, 11, 30, 97, 400, 2500) for p in (0.8, 0.5, 0.05)]
    return {"portfolios": portfolios, "cases": cases, "ranges": ranges}


# ----------------------------------------------- calibration sets (step 5.3)

def _set_entry(rng, k: int, unit: str, code: str, success_share: float, judged_at: float = 1.0) -> dict:
    """A ledger entry a calibration set is fitted from: a best fit of a
    clay, a weathered and a basement layer, the log that drilled through
    them, the score's parts and the chance recorded with them. Basement
    reads under 3,000 ohm-m in about half the holes, so its edge moves;
    the holes with a fracture at the contact succeed more often."""
    clay_base = round(rng.uniform(4.0, 9.0), 1)
    basement = round(rng.uniform(clay_base + 12.0, 38.0), 1)
    fracture = round(rng.uniform(0.0, 1.0), 3)
    success = rng.random() < success_share * (0.6 + 0.8 * fracture)
    chance = round(rng.uniform(0.25, 0.85), 3)
    return {
        "id": f"set{k:03d}", "before_outcome": rng.random() < 0.85, "recorded_on": "2026-04-01",
        "toolkit": "0.3.0", "point": {"sounding_id": f"VES {k}"},
        "prediction": {
            "investigation_depth_m": rng.choice([60.0, 45.0, 80.0]),
            "layers": [[0.0, 1.5, round(rng.uniform(300.0, 1500.0), 1)],
                       [1.5, clay_base, round(rng.uniform(6.0, 28.0), 1)],
                       [clay_base, basement, round(rng.uniform(22.0, 420.0), 1)],
                       [basement, None, round(rng.uniform(1100.0, 6500.0), 1)]],
            "suitability": {"aquifer_thickness": round(rng.random(), 3), "resistivity_fit": round(rng.random(), 3),
                            "overburden": round(rng.random(), 3), "basal_fracture": fracture},
            "odds": {"probability": chance, "prior": rng.choice([0.428, 0.428, 0.5, 0.966]), "bgs_code": code,
                     "glg": unit, "low": 0.2, "high": 0.9, "effective_n": 10.0, "status": "provisional",
                     "matched": "combination", "success_yield_m3_per_h": judged_at, "calibration": "x"}},
        "outcome": {"total_depth_m": round(basement + rng.uniform(4.0, 25.0), 1),
                    "intervals": [[0.0, 1.5, "laterite"], [1.5, clay_base, "clay"],
                                  [clay_base, basement, rng.choice(["weathered", "weathered", "saprolite", "sand"])],
                                  [basement, 100.0, "basement"]],
                    "success": success, "success_basis": "tested", "success_yield_m3_per_h": judged_at,
                    "safe_yield_m3_per_h": 2.0 if success else 0.4},
    }


def _set_portfolio(seed: int, n: int) -> list:
    import random

    rng = random.Random(seed)
    grounds = [("pCm", "B-L"), ("Pi", "I-L"), ("Qe", "U-M/H"), ("Mi", "B-L")]
    items, k = [], 0
    for project in ("Rokel", "Kuntolo", "Dr Timbo"):
        entries = []
        for _ in range(n // 3):
            unit, code = grounds[k % len(grounds)]
            entries.append(_set_entry(rng, k, unit, code, 0.55))
            k += 1
        items.append([project, {"drilled": None, "entries": entries}])
    items.append(["Rokel copy", copy.deepcopy(items[0][1])])
    return items


def calibration_sets_reference() -> dict:
    """Calibration sets (PLAN.md step 5.3) fitted to pooled portfolios: one
    with enough boreholes to fit every row, edge and weight, one too small to
    fit any, one whose boreholes were judged at another definition of
    success, did not say whether they succeeded, recorded no odds or no
    layers, or stand on ground with no cited rate, and none at all; each
    under the default settings and others. Each set adopted, named, written
    to its file and read back, and hand-edited files read or refused."""
    from groundwater import calibration_sets as CS
    from groundwater import ledger as L

    import random

    rng = random.Random(53)
    mixed = []
    for k, (unit, code) in enumerate([("pCm", "B-L")] * 6 + [("Pi", None)] * 2 + [(None, "n/a")] * 2):
        entry = _set_entry(rng, 500 + k, unit, code, 0.5, judged_at=3.6 if k == 1 else 1.0)
        if k == 2:
            entry["outcome"]["success"] = None
        if k == 3:
            entry["prediction"]["odds"] = None
        if k == 4:
            entry["prediction"]["layers"] = []
            entry["prediction"]["suitability"] = None
        if k == 5:
            entry["outcome"] = None
        mixed.append(entry)
    portfolios = {
        "fit": _set_portfolio(1, 36),
        "few": _set_portfolio(2, 9),
        "mixed": [["Kpètèma", {"drilled": None, "entries": mixed}]],
        "empty": [],
    }
    settings = [{}, {"ledger": {"fit_min_boreholes": 2, "fit_weights_min_each": 3}},
                {"ledger": {"fit_min_boreholes": 2, "fit_weights_min_each": 2},
                 "ves": {"clay_max_rho": 35.0, "fresh_basement_min_rho": 1500.0}},
                {"ledger": {"fit_min_boreholes": 2, "fit_weights_min_each": 2},
                 "odds": {"success_yield_m3_per_h": 3.6}}]
    earlier = CS.adopt_set(CS.fit_set([], "2026-01-01"), "Earlier Person", "2026-01-02")
    cases = []
    for name, items in portfolios.items():
        for k, overrides in enumerate(settings):
            # the mixed portfolio under every setting, the others under the
            # ones that change what they fit (another definition of success
            # leaves out all but the mixed portfolio's one borehole judged at
            # it)
            if name != "mixed" and k not in {"fit": (0, 2), "few": (0, 1), "empty": (0,)}[name]:
                continue
            config = Config()
            for section, values in overrides.items():
                for key, value in values.items():
                    setattr(getattr(config, section), key, value)
            pooled = L.pool_ledgers([tuple(item) for item in items])
            fitted = CS.fit_set(pooled, "2026-10-20", config)
            adopted = CS.adopt_set(fitted, "  A.\tKamara ", "2026-10-21", earlier if k == 2 else None)
            # the rows are the set's; the ids behind each fitted one are not
            # in it, and are held here
            # (by their positions as text, as JSON keys them)
            used = json.loads(json.dumps([CS.fit_prior(pooled, config)[1], CS.fit_edges(pooled, config)[1],
                                          CS.fit_weights(pooled, config)[1]]))
            cases.append({"portfolio": name, "settings": overrides, "in_force": k == 2, "expect": {
                "used": used, "set": fitted, "adopted": adopted,
                "names": [CS.set_name(fitted), CS.set_name(adopted)], "yaml": CS.set_yaml(adopted)}})
    # the mixed portfolio's set with every kind of row fitted, the smallest
    good = json.loads(json.dumps(next(c for c in cases if c["portfolio"] == "mixed"
                                      and c["settings"] == settings[1])["expect"]["adopted"]))

    def broken(change, base=None):
        raw = copy.deepcopy(good if base is None else base)
        change(raw)
        return raw

    # the same set as a file of format 1 (step 5.3) held it: its boreholes
    # listed by ledger id, and no licence, organisation, contact or sources
    old = {key: value for key, value in good.items() if key not in ("licence", "organisation", "contact",
                                                                   "sources")}
    old.update(format_version=1, boreholes=[{"id": f"set{k:03d}", "success": k % 2 == 0, "forecast": True,
                                             "uses": ["prior", "clay_max_rho"]} for k in range(good["boreholes"])])
    hand = [good, None, [good], dict(good, format="a list of boreholes"), dict(good, format_version=3),
            dict(good, version=None), dict(good, adopted_by=" "), dict(good, version=-1),
            broken(lambda r: r.pop("edges")), broken(lambda r: r["prior"][0].update(rate=0.0)),
            broken(lambda r: r["prior"][0].update(fitted=False, rate=None, effective_n=None)),
            broken(lambda r: r["edges"][1].update(misread=1.5)),
            broken(lambda r: r["weights"]["value"].update(overburden=0.5)),
            broken(lambda r: r["replaces"].update(version="0")),
            broken(lambda r: r.update(adopted_by="  B.   Sesay  ")),
            # format 2's own fields, and the rows' counts
            broken(lambda r: r.pop("licence")), broken(lambda r: r.update(boreholes=None)),
            broken(lambda r: r.update(boreholes=[])), broken(lambda r: r.update(sources={})),
            broken(lambda r: r.update(organisation="  Rural \t Water  ", contact=" x@y.z\n")),
            broken(lambda r: r["prior"][0].update(successes=r["prior"][0]["boreholes"] + 1)),
            broken(lambda r: r["prior"].append(dict(r["prior"][0]))),
            broken(lambda r: r["edges"].append(dict(r["edges"][0]))),
            broken(lambda r: r["edges"][0].update(boreholes=0)),
            # format 1, read with its ids counted and dropped, or refused as
            # it was
            old, broken(lambda r: r["boreholes"][0].update(uses=["prior", "laterite_min_rho"]), old),
            broken(lambda r: r["boreholes"][1].update(id=""), old), broken(lambda r: r.update(boreholes=3), old)]
    read = []
    for raw in hand:
        try:
            read.append({"ok": CS.clean_set(raw)})
        except ValueError as exc:
            read.append({"threw": str(exc)})
    refusals = []
    for who in ("", " \t ", None):
        try:
            CS.adopt_set(cases[0]["expect"]["set"], who, "2026-10-21")
        except ValueError as exc:
            refusals.append(str(exc))
    try:
        CS.adopt_set(cases[0]["expect"]["adopted"], "B. Sesay", "2026-10-22")
    except ValueError as exc:
        refusals.append(str(exc))
    return {"portfolios": portfolios, "earlier": earlier, "cases": cases, "hand": hand, "read": read,
            "refusals": refusals, "default": CS.default_set(), "default_name": CS.set_name(CS.default_set()),
            "default_yaml": CS.set_yaml(CS.default_set())}


# ---------------------------------------- pooling calibration sets (5.5)

def calibration_pooling_reference() -> dict:
    """Calibration sets of several organisations (PLAN.md step 5.5), each
    fitted to a portfolio of its own and adopted, pooled: two, three in
    another order, a pooled set pooled again with a third, under the default
    settings and others (a smaller minimum, the edges of another set in
    force, a water-bearing window whose top the pooled clay edge reaches);
    and every refusal: one set, a file that is not a set, the provisional
    default, a set nobody adopted, a set of format 1 that declares no
    licence, a set without a definition of success or with another, the
    same set twice, a set and a pooled set that holds it, a prior fitted
    from another provisional rate, a set under another licence than the
    one a pooled set is issued under, and no licence set to issue it under. Each pooled set's review, its name
    and file once adopted, and each set's fingerprint."""
    from groundwater import calibration_sets as CS
    from groundwater import ledger as L

    def issued(seed, n, organisation, by, on, contact="", **settings):
        config = Config()
        for key, value in settings.items():
            setattr(config.ledger, key, value)
        fitted = CS.fit_set(L.pool_ledgers([tuple(item) for item in _set_portfolio(seed, n)]), on, config)
        return json.loads(json.dumps(CS.adopt_set(fitted, by, on, organisation=organisation, contact=contact)))

    trust = issued(11, 36, "Rural Water Trust", "A. Kamara", "2026-10-20", contact="wells@example.org")
    kono = issued(12, 24, "Kono Wells", "B. Sesay", "2026-09-01")
    bo = issued(13, 12, "", "F. Koroma", "2026-08-15", fit_min_boreholes=2)
    late = issued(14, 9, "Rural Water Trust", "G. Sesay", "2026-10-25")
    forum = json.loads(json.dumps(CS.adopt_set(CS.pool_sets([trust, kono], "2026-10-28"), "C. Conteh",
                                               "2026-10-29", organisation="Salone Water Forum")))
    old = {key: value for key, value in kono.items() if key not in ("licence", "organisation", "contact",
                                                                   "sources")}
    old.update(format_version=1, boreholes=[{"id": f"k{k}", "success": True, "forecast": True, "uses": ["prior"]}
                                            for k in range(kono["boreholes"])])
    other_table = copy.deepcopy(kono)
    other_table["prior"][0]["base_rate"] = 0.5
    window = {"ves": {"fractured_zone_rho": [20.0, 60.0]}}
    groups = [
        ([trust, kono], ["trust.yaml", "kono.yaml"], {}),
        ([bo, kono, trust], None, {}),
        ([trust, kono, bo, late], None, {"ledger": {"fit_min_boreholes": 2}}),
        ([trust, kono], ["trust.yaml", "kono.yaml"], {"calibration": trust}),
        ([kono, bo], None, window),
        ([forum, bo], ["forum.yaml", "bo.yaml"], {}),
        ([trust], ["trust.yaml"], {}),
        ([trust, None], ["trust.yaml", "notes.yaml"], {}),
        ([CS.default_set(), trust], None, {}),
        ([trust, dict(kono, version=None, adopted_by="", adopted_on="", replaces=None)], None, {}),
        ([trust, old], ["trust.yaml", "kono-2025.yaml"], {}),
        ([trust, dict(kono, success_yield_m3_per_h=None)], None, {}),
        ([trust, dict(kono, success_yield_m3_per_h=3.6)], ["trust.yaml", "kono.yaml"], {}),
        ([trust, dict(trust, organisation="Renamed", adopted_by="H. Turay")], None, {}),
        ([forum, kono], ["forum.yaml", "kono.yaml"], {}),
        ([trust, other_table], None, {}),
        ([trust, dict(kono, licence="CC BY-SA 4.0")], ["trust.yaml", "kono.yaml"], {}),
        ([trust, kono], None, {"ledger": {"set_licence": " "}}),
    ]
    cases = []
    for sets, labels, settings in groups:
        config = Config()
        for section, values in settings.items():
            if section == "calibration":
                config = CS.apply_set(config, values)
                continue
            for key, value in values.items():
                setattr(getattr(config, section), key, value)
        expect: dict
        try:
            pooled = CS.pool_sets(sets, "2026-10-28", config, labels)
        except ValueError as exc:
            expect = {"threw": str(exc)}
        else:
            adopted = CS.adopt_set(pooled, " C.\tConteh ", "2026-10-29", in_force=CS.in_force(config),
                                   organisation="Salone Water Forum", contact="forum@example.org")
            expect = {"set": pooled, "review": CS.set_review(pooled, config), "name": CS.set_name(adopted),
                      "yaml": CS.set_yaml(adopted)}
        cases.append({"sets": sets, "labels": labels, "settings": settings, "expect": json.loads(json.dumps(expect))})
    prints = [{"set": s, "fingerprint": CS.set_fingerprint(s)}
              for s in (trust, kono, bo, late, forum, old, dict(trust, organisation="Renamed"))]
    return {"cases": cases, "fingerprints": prints}


# ----------------------------------------- a calibration set in force (5.3b)

#: A set adopted to be put in force: the prior of B-L on pCm and of I-L on
#: any unit fitted, CSF-L/M on pCm counted and not; both edges of pCm fitted
#: and none of Qe's; and the suitability weights.
IN_FORCE_SET = {
    "format": "groundwater calibration set", "format_version": 1, "version": 3, "fitted_on": "2027-03-01",
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
        {"bgs_code": "CSF-L/M", "glg": "pCm", "boreholes": 3, "successes": 3, "expected": 3.0, "base_rate": 0.7,
         "base_n": 10.0, "fitted": False, "rate": None, "effective_n": None},
    ],
    "edges": [
        {"glg": "pCm", "edge": "clay_max_rho", "boreholes": 8, "below": 8, "above": 20, "base": 20.0,
         "misread_base": 3, "fitted": True, "value": 31.5, "misread": 1},
        {"glg": "pCm", "edge": "fresh_basement_min_rho", "boreholes": 8, "below": 28, "above": 8, "base": 3000.0,
         "misread_base": 4, "fitted": True, "value": 1500.0, "misread": 0},
        {"glg": "Qe", "edge": "fresh_basement_min_rho", "boreholes": 2, "below": 3, "above": 2, "base": 3000.0,
         "misread_base": 1, "fitted": False, "value": None, "misread": None},
    ],
    "weights": {"successes": 12, "failures": 11,
                "base": {"aquifer_thickness": 0.35, "resistivity_fit": 0.25, "overburden": 0.2, "basal_fracture": 0.2},
                "right_base": 0.61, "fitted": True,
                "value": {"aquifer_thickness": 0.25, "resistivity_fit": 0.1, "overburden": 0.1, "basal_fracture": 0.55},
                "right": 0.74},
}

#: The grounds the odds are asked about, the units the edges are asked for,
#: sounding positions (Kpètèma on pCm, Rokel on Qe, none, and one whose zone
#: its easting implies) and models to interpret by each unit's edges.
IN_FORCE_GROUNDS = [["B-L", "pCm"], ["B-L", "Pi"], ["I-L", "Pi"], ["I-L", "Mi"], ["CSF-L/M", "pCm"],
                    ["U-M/H", "Qe"], ["n/a", None], [None, None], ["B-L", None]]
IN_FORCE_UNITS = ["pCm", "Qe", "Pi", None]
IN_FORCE_POSITIONS = [[166030.0, 930010.0, 29], [708958.4, 926355.5, 28], [None, None, None],
                      [250000.0, 900000.0, None]]
IN_FORCE_MODELS = [[[400.0, 90.0, 2000.0, 5000.0], [2.0, 18.0, 10.0]], [[300.0, 25.0, 140.0, 4000.0], [1.5, 6.0, 20.0]],
                   [[600.0, 120.0, 1200.0], [3.0, 30.0]], [[250.0, 12.0, 2500.0], [2.0, 10.0]]]


def calibration_in_force_reference() -> dict:
    """A calibration set in force (PLAN.md step 5.3, part b): the odds at
    each kind of ground with its fitted prior, or the table's where it fitted
    none, and their sentences; each unit's edges and the soundings read by
    them; the suitability weights; what the set changes; under the default,
    the set, the set without weights at another definition of success, and
    a set nobody adopted, which is refused."""
    from groundwater import calibration_sets as CS
    from groundwater.models import LayeredModel
    from groundwater.siting import assess_siting
    from groundwater.siting.odds import (
        odds_basis_text, odds_headline, odds_prior_text, odds_text, prior_odds, success_odds,
    )
    from groundwater.ves.interpret import interpret_model

    unweighed = dict(IN_FORCE_SET, weights=None, success_yield_m3_per_h=3.6)
    candidate = dict(IN_FORCE_SET, version=None, adopted_by="", adopted_on="", replaces=None)
    variants = [{"name": "default", "set": None, "settings": {}},
                {"name": "set", "set": IN_FORCE_SET, "settings": {}},
                {"name": "set at 3.6", "set": IN_FORCE_SET, "settings": {"odds": {"success_yield_m3_per_h": 3.6}}},
                {"name": "unweighed", "set": unweighed, "settings": {"odds": {"success_yield_m3_per_h": 3.6}}},
                {"name": "candidate", "set": candidate, "settings": {}}]
    cases = []
    for v in variants:
        config = Config()
        for section, values in v["settings"].items():
            for key, value in values.items():
                setattr(getattr(config, section), key, value)
        try:
            config = CS.apply_set(config, v["set"]) if v["set"] else config
        except ValueError as exc:
            cases.append(dict(v, expect={"refused": str(exc)}))
            continue
        interps = [interpret_model(None, LayeredModel(resistivities=m[0], thicknesses=m[1]),
                                   CS.config_for_unit(config, IN_FORCE_UNITS[k % len(IN_FORCE_UNITS)]).ves)
                   for k, m in enumerate(IN_FORCE_MODELS)]
        odds = []
        for code, glg in IN_FORCE_GROUNDS:
            o = prior_odds(code, glg, config)
            odds.append({"odds": dataclasses.asdict(o), "headline": odds_headline(o), "prior": odds_prior_text(o),
                         "basis": odds_basis_text(o)})
        success = []
        for k, interp in enumerate(interps):
            code, glg = IN_FORCE_GROUNDS[k % len(IN_FORCE_GROUNDS)]
            o = success_odds(interp, None, code, glg, config)
            success.append({"odds": dataclasses.asdict(o), "text": odds_text(o)})
        cases.append(dict(v, expect={
            "weights": config.ves.suitability_weights, "calibration": config.calibration, "odds": odds,
            "success": success,
            "units": [[CS.config_for_unit(config, glg).ves.clay_max_rho,
                       CS.config_for_unit(config, glg).ves.fresh_basement_min_rho] for glg in IN_FORCE_UNITS],
            "sounding": [CS.config_for_sounding(config, _ns({"site": {"easting": p[0], "northing": p[1],
                                                                      "utm_zone": p[2]}})).ves.fresh_basement_min_rho
                         for p in IN_FORCE_POSITIONS],
            "interps": [[i.depth_to_basement_m, [layer.unit for layer in i.layers]] for i in interps],
            "siting": [[r.index, r.suitability, r.rank] for r in assess_siting(interps, config.ves)],
            "changes": CS.set_changes(CS.in_force(config))}))
    return {"grounds": IN_FORCE_GROUNDS, "units": IN_FORCE_UNITS, "positions": IN_FORCE_POSITIONS,
            "models": IN_FORCE_MODELS, "cases": cases}

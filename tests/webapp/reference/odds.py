"""The chance of success (PLAN.md step 3.3): the "odds" entry of
``reference.json``. ``_odds_dict`` and ``_odds_range`` are also what the
measurement cases and ``build()`` shape their odds with.
"""

from __future__ import annotations

import copy
import dataclasses
import math
from types import SimpleNamespace

from groundwater.config import Config
from groundwater.siting import assess_siting
from groundwater.siting.odds import (
    odds_basis_text,
    odds_header,
    odds_point_text,
    odds_rows,
    odds_short,
    odds_table_caption,
    odds_text,
    programme_offer,
    programme_rate,
    success_odds,
)

from .common import clean


# --------------------------------------------------- the chance of success
# PLAN.md step 3.3. Hand-built points cover every band, and ODDS_EDGES puts
# a point exactly on every band edge, where only the comparison decides;
# the Rokel pair is read with the short ranges (RANGE_SHORT in ves.py), placed by its own
# coordinates on the bundled maps.

def _odds_interp(sid, zones, layers, err):
    """A point as the odds read it: its water zones, its layers (a base of
    None is the half-space, and the last field whether the layer is
    water-bearing) and its misfit."""
    return SimpleNamespace(
        sounding_id=sid, water_zones=[tuple(z) for z in zones],
        layers=[SimpleNamespace(top_m=t, bottom_m=math.inf if b is None else b, rho=r,
                                water_bearing=wet)
                for t, b, r, wet in layers],
        fit_error_percent=err, site_easting=None, site_northing=None)


def _odds_range(basement, unresolved):
    from groundwater.ves.model_range import Band

    return SimpleNamespace(basement_m=None if basement is None else Band(*basement),
                           basement_unresolved=unresolved)


def _odds_dict(o) -> dict:
    out = clean(dataclasses.asdict(o))
    out["text"] = odds_text(o)
    out["point_text"] = odds_point_text(o)
    out["basis_text"] = odds_basis_text(o)
    out["rows"] = odds_rows(o)
    out["short"] = odds_short(o)
    out["caption"] = odds_table_caption(o)
    out["programme_rate"] = programme_rate(o)
    out["programme_offer"] = programme_offer(o)
    return out


def _three_layers(rho, err, zone=(5, 20)):
    """A water-bearing layer of ``rho`` filling ``zone``, dry above and
    basement below."""
    top, base = zone
    return ([list(zone)], [[0, top, 300.0, False], [top, base, rho, True],
                           [base, None, 5000.0, False]], err)


ODDS_POINTS = {
    # 80 ohm-m over basement at 20 m, a good fit
    "productive": _three_layers(80.0, 4.0),
    "clay": ([[3, 12]], [[0, 3, 150.0, False], [3, 12, 12.0, True],
                         [12, None, 4000.0, False]], 7.5),
    "clayey": ([[4, 30]], [[0, 4, 200.0, False], [4, 30, 35.0, True],
                           [30, None, 4000.0, False]], 12.0),
    "resistive": ([[6, 25]], [[0, 6, 900.0, False], [6, 25, 500.0, True],
                              [25, None, 6000.0, False]], 25.0),
    "fresh": ([[2, 40]], [[0, 2, 100.0, False], [2, 40, 1500.0, True]], 3.0),
    "dry": ([], [[0, 3, 900.0, False], [3, None, 8000.0, False]], 4.0),
    "unknown_fit": _three_layers(80.0, None),
    # a zone rounded to whole metres takes in 0.4 m of the basement under
    # it, which the water-zone resistivity leaves out
    "rounded": ([[6, 9]], [[0, 6, 300.0, False], [6, 8.6, 200.0, True],
                           [8.6, None, 5000.0, False]], 3.0),
}

# A point exactly on each band edge, read on B-L: the depth, the basement
# share, the misfit and the resistivity, each with nothing else moving.
ODDS_EDGES = (
    [(f"edge_depth_{d:g}", _three_layers(80.0, 4.0), ((d - 2.0, d, d + 5.0), 0.0))
     for d in (5.0, 15.0, 35.0)]
    + [("edge_share", _three_layers(80.0, 4.0), ((18.0, 22.0, 30.0), 0.1))]
    + [(f"edge_fit_{e:g}", _three_layers(80.0, e), None) for e in (5.0, 10.0, 20.0)]
    + [(f"edge_rho_{r:g}", _three_layers(r, 4.0), None) for r in (20.0, 50.0, 300.0, 800.0)]
)

ODDS_RANGES = {
    "none": None,
    "thin": ((2.0, 4.0, 6.0), 0.0),
    "shallow": ((8.0, 11.0, 16.0), 0.05),
    "favourable": ((18.0, 22.0, 30.0), 0.1 - 1e-12),
    "deep": ((30.0, 45.0, 60.0), 0.4),
    # basement found in under a tenth of the models: no band is quoted
    "not_quoted": ((30.0, 45.0, 60.0), 0.95),
    "never": (None, 1.0),
}

ODDS_GROUND = [
    ["B-L", "pCm"], ["B-L", "Qe"], ["B-L", None], ["I-L", "Pi"], ["I-L", "Mi"],
    ["CSF-L/M", "pCm"], ["U-M/H", "Qe"], ["n/a", "H2O"], ["ZZ", "pCm"],
    [None, None], [None, "pCm"],
]


def odds_reference(rokel_interps, rokel_sites, short_ranges) -> dict:
    from groundwater.siting.odds import (
        beta_quantile, lognormal_share_above, point_latlon, prior_for,
        regularised_beta,
    )

    config = Config()
    wider = Config()
    wider.odds.success_yield_m3_per_h = 3.6
    # a low success yield puts the coastal sands' prior near 1, where the
    # 90th percentile of its Beta bisects to exactly 1
    low = Config()
    low.odds.success_yield_m3_per_h = 0.3
    cases = []

    def case(name, point, spec, code, glg):
        zones, layers, err = point
        r = None if spec is None else _odds_range(*spec)
        o = success_odds(_odds_interp(name, zones, layers, err), r, code, glg, config)
        cases.append({
            "interp": {"sounding_id": name, "water_zones": zones,
                       "layers": [{"top_m": t, "bottom_m": b, "rho": rho,
                                   "water_bearing": wet}
                                  for t, b, rho, wet in layers],
                       "fit_error_percent": err},
            "range": None if r is None else {
                "basement_m": None if r.basement_m is None
                else clean(dataclasses.asdict(r.basement_m)),
                "basement_unresolved": r.basement_unresolved},
            "ground": [code, glg],
            "odds": _odds_dict(o),
        })

    for name, point in ODDS_POINTS.items():
        for rname, spec in ODDS_RANGES.items():
            for code, glg in (["B-L", "pCm"],) if rname != "favourable" else ODDS_GROUND:
                case(name, point, spec, code, glg)
    for name, point, spec in ODDS_EDGES:
        case(name, point, spec, "B-L", "pCm")
    o = success_odds(_odds_interp("wider", *ODDS_POINTS["productive"]),
                     _odds_range(*ODDS_RANGES["favourable"]), "B-L", "pCm", wider)
    low_yield = success_odds(_odds_interp("low_yield", *ODDS_POINTS["productive"]),
                             _odds_range(*ODDS_RANGES["favourable"]), "U-M/H", "Qe", low)
    from groundwater.siting.odds import ground_at

    places = [[8.3759, -13.1024], [8.6, -11.5], [8.47, -13.24], [9.5, -12.0],
              [7.6, -12.5], [5.0, -20.0]]
    # the suitability rows name their point by position: with the second
    # point copied over the first's id and listed first, the leader is the
    # one listed second
    renamed = copy.copy(rokel_interps[1])
    renamed.sounding_id = rokel_interps[0].sounding_id
    ranked_index = [s.index for s in assess_siting([renamed, rokel_interps[0]])]
    rokel = []
    for interp, site, r in zip(rokel_interps, rokel_sites, short_ranges, strict=True):
        latlon = point_latlon(interp, site.utm_zone, site.latlon)
        rokel.append({"latlon": clean(list(latlon)) if latlon else None,
                      "ground": list(ground_at(latlon)),
                      "odds": _odds_dict(success_odds(interp, r, *ground_at(latlon), config))})
    return {
        "lognormal": [[q1, q3, t, lognormal_share_above(q1, q3, t)]
                      for q1, q3, t in ((0.1, 0.5, 1 / 3.6), (0.1, 5.0, 1 / 3.6),
                                        (2.0, 20.0, 1 / 3.6), (0.1, 0.5, 0.05),
                                        (0.1, 0.5, 2.0))],
        "beta": [[a, b, x, regularised_beta(a, b, x), beta_quantile(a, b, x)]
                 for a, b in ((4.28, 5.72), (1.0, 1.0), (0.3, 9.7), (9.9, 0.1), (50.0, 50.0))
                 for x in (0.1, 0.5, 0.9)],
        "priors": [[code, glg, {k: clean(v) for k, v in prior_for(code, glg, 1.0).items()}]
                   for code, glg in ODDS_GROUND],
        "cases": cases,
        "wider": _odds_dict(o),
        "low_yield": {"rate": low.odds.success_yield_m3_per_h,
                      "odds": _odds_dict(low_yield)},
        "ranked_index": ranked_index,
        "ground": [[lat, lon, list(ground_at((lat, lon)))] for lat, lon in places],
        "rokel": rokel,
        "header": odds_header(),
    }

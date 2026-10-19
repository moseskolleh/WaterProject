"""A calibration report: the ledger's forecasts against what was drilled
(PLAN.md step 5.2).

The ledger of predictions and outcomes (ledger.py) keeps what the survey
predicted at each point beside what the borehole drilled there found. This
module scores the predictions over a pooled ledger, many projects at once:

- the depth to basement found against the predicted P10 to P90 band. A
  calibrated band holds the depth found four times in five, and the report
  gives the range a calibrated band's count would fall in nine times in ten
  on as many boreholes, so a shortfall can be told from bad luck;
- the chance of success, by its Brier score (Brier, 1950) beside the score
  the prior alone would have had, and by a reliability diagram (Murphy and
  Winkler, 1977);
- the hit rate, the share of boreholes that succeeded, by geology unit,
  survey team and contractor.

Only forecasts are scored: predictions recorded before their borehole was
drilled. One recorded afterwards may have been made knowing what the
borehole found, so it is counted and left out. The hit rates count every
drilled point, since a rate does not rest on when the prediction was
written. Below ``ledger.min_boreholes`` (``ledger.min_group`` for a hit
rate) the report says there are too few boreholes to judge and gives the
counts. It changes nothing the toolkit predicts.

Every function here takes the entries of :func:`groundwater.ledger.pool_ledgers`
and has a twin of the same name in camel case in gwt-core.js, held to it by
parity.
"""

from __future__ import annotations

import math

from .config import Config
from .ledger import (
    _basement_found,
    _basement_predicted,
    _name,
    _share,
    basement_check,
    ledger_counts,
    ledger_summary,
)
from .reporting.citations import references_for
from .text import phrase, phrase_table
from .utils import sum_in_order

__all__ = [
    "BAND_COVERAGE",
    "binomial_range",
    "calibration_content",
    "depth_scores",
    "forecast_entries",
    "hit_rates",
    "odds_scores",
]

#: The share of depths found that a calibrated P10 to P90 band holds.
BAND_COVERAGE = 0.8

#: The percentiles of the count inside that bound the range a calibrated
#: band falls in: at least nine times in ten.
_EXPECTED = (0.05, 0.95)

#: The groupings the hit rates are given by, in the report's order.
GROUPINGS = ("geology", "team", "contractor")

_BASES = ("tested", "recorded_failure", "recorded_success")


def _num(value: float, digits: int) -> float:
    return round(float(value), digits)


def forecast_entries(pooled: list[dict]) -> list[dict]:
    """The drilled entries whose prediction was recorded before drilling:
    the only ones the band and the odds are scored on."""
    return [entry for entry in pooled if entry["outcome"] is not None and entry["before_outcome"]]


def binomial_range(n: int, p: float, low: float = _EXPECTED[0], high: float = _EXPECTED[1]) -> tuple[int, int]:
    """The counts out of ``n`` that bound a binomial at ``p``: the smallest
    count whose cumulative probability reaches ``low``, and the smallest that
    reaches ``high``.

    The probabilities are worked out from the most likely count outward,
    each from its neighbour by a product and a quotient, so no power of ``p``
    underflows on a large ``n`` and the two engines agree to the bit.
    """
    if n <= 0:
        return 0, 0
    q = 1.0 - p
    mode = min(n, math.floor((n + 1) * p))
    weights = [0.0] * (n + 1)
    weights[mode] = 1.0
    for k in range(mode, n):
        weights[k + 1] = weights[k] * (n - k) * p / ((k + 1) * q)
    for k in range(mode, 0, -1):
        weights[k - 1] = weights[k] * k * q / ((n - k + 1) * p)
    total = sum_in_order(weights)
    lo = hi = n
    found_lo = found_hi = False
    cumulative = 0.0
    for k in range(n + 1):
        cumulative = cumulative + weights[k] / total
        if not found_lo and cumulative >= low:
            lo, found_lo = k, True
        if not found_hi and cumulative >= high:
            hi, found_hi = k, True
    return lo, hi


# ------------------------------------------------------------------- depth

def depth_scores(pooled: list[dict], config: Config | None = None) -> dict:
    """The depth to basement found against the predicted band, over the
    forecasts.

    ``points`` are the forecast points drilled, each with the depth the best
    fit gave (``predicted``), its band (P10, P50 and P90, or None), the depth
    to basement found (None where the hole stopped short) and the hole's
    total depth, and how the two compare (``check``, as
    :func:`groundwater.ledger.basement_check` has it). A hole is judged
    against the band when basement was found, or when it stopped below the
    band's P90 without finding it. ``expected`` is the range of the count
    inside that a calibrated band would hold at least nine times in ten on
    as many judged, and ``verdict`` is ``too_few`` below
    ``ledger.min_boreholes`` judged, else ``calibrated``, ``narrow`` (fewer
    inside than that) or ``wide`` (more). ``bias_m`` is the mean of the depth
    found less the best fit's, and ``mean_abs_m`` the mean distance between
    them, over the holes that found basement where the best fit had one.
    """
    config = config or Config()
    counts = {"inside": 0, "shallower": 0, "deeper": 0, "unreached_allowed": 0, "no_band": 0}
    points, errors = [], []
    for entry in forecast_entries(pooled):
        prediction, outcome = entry["prediction"], entry["outcome"]
        check = basement_check(prediction, outcome) or "no_band"
        counts[check] += 1
        best, found = prediction["depth_to_basement_m"], outcome["basement_m"]
        points.append({
            "project": entry["project"],
            "sounding_id": entry["point"]["sounding_id"],
            "predicted": best,
            "band": prediction["basement_band_m"],
            "found": found,
            "total_depth_m": outcome["total_depth_m"],
            "check": check,
        })
        if best is not None and found is not None:
            errors.append(found - best)
    judged = counts["inside"] + counts["shallower"] + counts["deeper"]
    minimum = int(config.ledger.min_boreholes)
    expected = list(binomial_range(judged, BAND_COVERAGE)) if judged else None
    if judged < minimum or expected is None:
        verdict = "too_few"
    elif counts["inside"] < expected[0]:
        verdict = "narrow"
    elif counts["inside"] > expected[1]:
        verdict = "wide"
    else:
        verdict = "calibrated"
    return {
        "points": points,
        "drilled": len(points),
        "judged": judged,
        "inside": counts["inside"],
        "shallower": counts["shallower"],
        "deeper": counts["deeper"],
        "unreached": counts["unreached_allowed"],
        "no_band": counts["no_band"],
        "minimum": minimum,
        "expected": expected,
        "verdict": verdict,
        "errors": len(errors),
        "bias_m": _num(sum_in_order(errors) / len(errors), 2) if errors else None,
        "mean_abs_m": _num(sum_in_order(abs(x) for x in errors) / len(errors), 2) if errors else None,
    }


# -------------------------------------------------------------------- odds

def _chance(prediction: dict) -> float | None:
    """The forecast chance of success, or None where none was worked out
    or a hand-edited file holds one outside 0 to 1."""
    odds = prediction["odds"]
    p = odds["probability"] if odds is not None else None
    return p if p is not None and 0.0 <= p <= 1.0 else None


def _squared(p: float, success: bool) -> float:
    """The squared difference between a chance and its outcome, 1 or 0."""
    d = p - (1.0 if success else 0.0)
    return d * d


def odds_scores(pooled: list[dict], config: Config | None = None) -> dict:
    """The forecast chances of success against the outcomes.

    ``scored`` are the forecasts with a chance and a known outcome. Over
    them: ``brier``, the mean squared difference between chance and outcome
    (1 or 0); ``brier_prior``, the same for the prior each forecast started
    from (None where a forecast lacks one); ``skill``, one less their ratio,
    above zero where the survey's evidence improved on the prior; and
    ``bins``, the reliability diagram's ``ledger.reliability_bins`` equal
    bands of chance, each with its forecasts, their mean chance and the
    share that succeeded. ``bases`` counts the outcomes by what decided them.
    ``verdict`` is ``too_few`` below ``ledger.min_boreholes`` scored, else
    ``scored``.
    """
    config = config or Config()
    scored, no_odds, unknown = [], 0, 0
    for entry in forecast_entries(pooled):
        p = _chance(entry["prediction"])
        success = entry["outcome"]["success"]
        if p is None:
            no_odds += 1
            continue
        if success is None:
            unknown += 1
            continue
        prior = entry["prediction"]["odds"]["prior"]
        scored.append({
            "project": entry["project"],
            "sounding_id": entry["point"]["sounding_id"],
            "p": p,
            "prior": prior if prior is not None and 0.0 <= prior <= 1.0 else None,
            "success": success,
            "basis": entry["outcome"]["success_basis"],
        })
    n = len(scored)
    minimum = int(config.ledger.min_boreholes)
    nbins = max(1, int(config.ledger.reliability_bins))
    members: list[list[dict]] = [[] for _ in range(nbins)]
    for s in scored:
        members[min(nbins - 1, math.floor(s["p"] * nbins))].append(s)
    bins = []
    for k, inside in enumerate(members):
        m = len(inside)
        hits = sum(1 for s in inside if s["success"])
        bins.append({
            "low": _num(k / nbins, 3),
            "high": _num((k + 1) / nbins, 3),
            "n": m,
            "successes": hits,
            "mean_p": _num(sum_in_order(s["p"] for s in inside) / m, 3) if m else None,
            "observed": _num(hits / m, 3) if m else None,
        })
    brier = brier_prior = skill = mean_p = None
    if n:
        brier = sum_in_order(_squared(s["p"], s["success"]) for s in scored) / n
        mean_p = _num(sum_in_order(s["p"] for s in scored) / n, 3)
        if all(s["prior"] is not None for s in scored):
            brier_prior = sum_in_order(_squared(s["prior"], s["success"]) for s in scored) / n
            if brier_prior > 0.0:
                skill = _num(1.0 - brier / brier_prior, 3)
            brier_prior = _num(brier_prior, 4)
        brier = _num(brier, 4)
    successes = sum(1 for s in scored if s["success"])
    return {
        "scored": scored,
        "n": n,
        "successes": successes,
        "failures": n - successes,
        "no_odds": no_odds,
        "unknown": unknown,
        "bases": {basis: sum(1 for s in scored if s["basis"] == basis) for basis in _BASES},
        "minimum": minimum,
        "verdict": "too_few" if n < minimum else "scored",
        "mean_p": mean_p,
        "brier": brier,
        "brier_prior": brier_prior,
        "skill": skill,
        "bins": bins,
    }


# --------------------------------------------------------------- hit rates

def _group(entry: dict, by: str) -> tuple[str, bool]:
    """The group an entry falls in, and whether it names one."""
    if by == "geology":
        odds = entry["prediction"]["odds"]
        if odds is None:
            return phrase("calibration.not_recorded"), False
        if not odds["bgs_code"]:
            return phrase("calibration.geology_no_class"), False
        if odds["glg"]:
            return phrase("calibration.geology", code=odds["bgs_code"], glg=odds["glg"]), True
        return phrase("calibration.geology_class", code=odds["bgs_code"]), True
    name = entry["prediction"]["survey_team"] if by == "team" else entry["outcome"]["contractor"]
    if name:
        return name, True
    return phrase("calibration.not_recorded"), False


def _code_points(text: str) -> list[int]:
    return [ord(c) for c in text]


def hit_rates(pooled: list[dict], by: str, config: Config | None = None) -> list[dict]:
    """The drilled points by geology unit, survey team or contractor
    (``by``), each group with its boreholes drilled, successful, not
    successful and not known yet, its hit rate (the share successful of
    those known, None below ``ledger.min_group`` known), and the mean chance
    forecast over its forecasts with a known outcome (None where it has
    none) with their number. The groups that name one come first, the most
    drilled first and then by name, letter by letter; those whose point
    records none come last.
    """
    if by not in GROUPINGS:
        raise ValueError(f"calibration: no hit rate by {by!r}")
    config = config or Config()
    minimum = int(config.ledger.min_group)
    groups: dict[str, dict] = {}
    chances: dict[str, list[float]] = {}
    for entry in pooled:
        outcome = entry["outcome"]
        if outcome is None:
            continue
        label, recorded = _group(entry, by)
        group = groups.setdefault(label, {"label": label, "recorded": recorded, "drilled": 0, "success": 0,
                                          "failure": 0, "unknown": 0})
        chances.setdefault(label, [])
        group["drilled"] += 1
        if outcome["success"] is True:
            group["success"] += 1
        elif outcome["success"] is False:
            group["failure"] += 1
        else:
            group["unknown"] += 1
        p = _chance(entry["prediction"])
        if entry["before_outcome"] and outcome["success"] is not None and p is not None:
            chances[label].append(p)
    out = []
    for label, group in groups.items():
        known = group["success"] + group["failure"]
        ps = chances[label]
        out.append(dict(group, known=known,
                        rate=_num(group["success"] / known, 3) if known >= minimum and known else None,
                        forecast_n=len(ps),
                        forecast_mean=_num(sum_in_order(ps) / len(ps), 3) if ps else None))
    out.sort(key=lambda g: (not g["recorded"], -g["drilled"], _code_points(g["label"])))
    return out


# ------------------------------------------------------------------ report

def _section(key: str, heading: str) -> dict:
    return {"key": key, "heading": heading, "paragraphs": [], "tables": [], "figures": [], "bullets": []}


def _depth_section(depth: dict, pooled: list[dict]) -> dict:
    section = _section("depth", phrase("calibration.depth_heading"))
    paragraphs = section["paragraphs"]
    paragraphs.append(phrase("calibration.depth_intro"))
    if not depth["drilled"]:
        return section
    paragraphs.append(phrase("calibration.depth_counts", drilled=depth["drilled"], inside=depth["inside"],
                             shallower=depth["shallower"], deeper=depth["deeper"], unreached=depth["unreached"],
                             no_band=depth["no_band"]))
    if depth["verdict"] == "too_few":
        paragraphs.append(phrase("calibration.depth_too_few", judged=depth["judged"], minimum=depth["minimum"]))
    else:
        low, high = depth["expected"]
        paragraphs.append(phrase("calibration.depth_judged", inside=depth["inside"], judged=depth["judged"],
                                 share=_share(depth["inside"] / depth["judged"]), low=low, high=high))
        if depth["verdict"] == "calibrated":
            paragraphs.append(phrase("calibration.depth_calibrated"))
        elif depth["verdict"] == "narrow":
            paragraphs.append(phrase("calibration.depth_narrow", shallower=depth["shallower"],
                                     deeper=depth["deeper"]))
        else:
            paragraphs.append(phrase("calibration.depth_wide"))
    if depth["errors"]:
        bias, values = depth["bias_m"], {"mae": depth["mean_abs_m"], "n": depth["errors"]}
        if bias > 0.0:
            paragraphs.append(phrase("calibration.depth_bias_deeper", bias=bias, **values))
        elif bias < 0.0:
            paragraphs.append(phrase("calibration.depth_bias_shallower", bias=-bias, **values))
        else:
            paragraphs.append(phrase("calibration.depth_bias_none", **values))
    if any((p["predicted"] is not None or p["band"] is not None)
           and (p["found"] is not None or p["total_depth_m"] is not None) for p in depth["points"]):
        section["figures"].append({"key": "depth", "caption": phrase("calibration.depth_figure")})
    checks = phrase_table("ledger.basement_check")
    section["tables"].append({
        "header": [phrase("ledger.pool_col_project"), phrase("ledger.pool_col_point"),
                   phrase("ledger.pool_col_basement"), phrase("ledger.pool_col_found"),
                   phrase("ledger.pool_col_check")],
        "rows": [[entry["project"], entry["point"]["sounding_id"], _basement_predicted(entry["prediction"]),
                  _basement_found(entry["outcome"]), checks[point["check"]]]
                 for entry, point in zip(forecast_entries(pooled), depth["points"], strict=True)],
        "caption": phrase("calibration.depth_table"),
    })
    return section


def _percent(fraction: float) -> str:
    return phrase("calibration.percent", p=_share(fraction))


def _odds_section(odds: dict, config: Config) -> dict:
    section = _section("odds", phrase("calibration.odds_heading"))
    paragraphs = section["paragraphs"]
    paragraphs.append(phrase("calibration.odds_intro", rate=float(config.odds.success_yield_m3_per_h)))
    if not (odds["n"] or odds["no_odds"] or odds["unknown"]):
        return section
    if odds["no_odds"] or odds["unknown"]:
        paragraphs.append(phrase("calibration.odds_left_out", no_odds=odds["no_odds"], unknown=odds["unknown"]))
    if odds["verdict"] == "too_few":
        paragraphs.append(phrase("calibration.odds_too_few", n=odds["n"], success=odds["successes"],
                                 failure=odds["failures"], minimum=odds["minimum"]))
        return section
    n, bases = odds["n"], odds["bases"]
    paragraphs.append(phrase("calibration.odds_bases", n=n, tested=bases["tested"],
                             failure=bases["recorded_failure"], success=bases["recorded_success"]))
    paragraphs.append(phrase("calibration.odds_mean", p=_share(odds["mean_p"]), k=odds["successes"], n=n,
                             share=_share(odds["successes"] / n)))
    paragraphs.append(phrase("calibration.odds_brier", bs=odds["brier"]))
    if odds["brier_prior"] is not None:
        skill = odds["skill"]
        if skill is not None and skill > 0.0:
            paragraphs.append(phrase("calibration.odds_skill_better", bs0=odds["brier_prior"], skill=_share(skill)))
        elif skill is not None and skill < 0.0:
            paragraphs.append(phrase("calibration.odds_skill_worse", bs0=odds["brier_prior"], skill=_share(-skill)))
        else:
            paragraphs.append(phrase("calibration.odds_skill_same", bs0=odds["brier_prior"]))
    paragraphs.append(phrase("calibration.odds_reliability"))
    width = _share(1.0 / len(odds["bins"]))
    section["figures"].append({"key": "reliability", "caption": phrase("calibration.odds_figure", width=width)})
    none = phrase("calibration.none")
    section["tables"].append({
        "header": [phrase("calibration.odds_col_band"), phrase("calibration.odds_col_n"),
                   phrase("calibration.odds_col_mean"), phrase("calibration.odds_col_found")],
        "rows": [[phrase("calibration.odds_band", low=_share(b["low"]), high=_share(b["high"])), str(b["n"]),
                  _percent(b["mean_p"]) if b["n"] else none,
                  phrase("calibration.odds_found", k=b["successes"], n=b["n"], share=_share(b["observed"]))
                  if b["n"] else none]
                 for b in odds["bins"]],
        "caption": phrase("calibration.odds_table"),
    })
    return section


_HIT_TABLES = {
    "geology": ("calibration.hits_col_geology", "calibration.hits_geology"),
    "team": ("calibration.hits_col_team", "calibration.hits_team"),
    "contractor": ("calibration.hits_col_contractor", "calibration.hits_contractor"),
}


def _hits_section(pooled: list[dict], config: Config) -> dict:
    section = _section("hits", phrase("calibration.hits_heading"))
    if not any(entry["outcome"] is not None for entry in pooled):
        section["paragraphs"].append(phrase("calibration.hits_none"))
        return section
    section["paragraphs"].append(phrase("calibration.hits_intro", minimum=int(config.ledger.min_group)))
    too_few, not_forecast = phrase("calibration.hits_too_few"), phrase("calibration.hits_not_forecast")
    for by in GROUPINGS:
        column, caption = _HIT_TABLES[by]
        section["tables"].append({
            "header": [phrase(column), phrase("calibration.hits_col_drilled"), phrase("calibration.hits_col_success"),
                       phrase("calibration.hits_col_failure"), phrase("calibration.hits_col_unknown"),
                       phrase("calibration.hits_col_rate"), phrase("calibration.hits_col_forecast")],
            "rows": [[g["label"], str(g["drilled"]), str(g["success"]), str(g["failure"]), str(g["unknown"]),
                      _percent(g["rate"]) if g["rate"] is not None else too_few,
                      phrase("calibration.hits_forecast", p=_share(g["forecast_mean"]), n=g["forecast_n"])
                      if g["forecast_mean"] is not None else not_forecast]
                     for g in hit_rates(pooled, by, config)],
            "caption": phrase(caption),
        })
    return section


def _depth_summary(depth: dict) -> str:
    if depth["verdict"] == "too_few":
        return phrase("calibration.summary_depth_too_few", judged=depth["judged"], minimum=depth["minimum"])
    low, high = depth["expected"]
    values = dict(inside=depth["inside"], judged=depth["judged"], share=_share(depth["inside"] / depth["judged"]),
                  low=low, high=high)
    if depth["verdict"] == "calibrated":
        return phrase("calibration.summary_depth_calibrated", **values)
    if depth["verdict"] == "narrow":
        return phrase("calibration.summary_depth_narrow", **values)
    return phrase("calibration.summary_depth_wide", **values)


def _odds_summary(odds: dict) -> str:
    if odds["verdict"] == "too_few":
        return phrase("calibration.summary_odds_too_few", n=odds["n"], minimum=odds["minimum"])
    if odds["brier_prior"] is None:
        return phrase("calibration.summary_odds_no_prior", bs=odds["brier"], n=odds["n"])
    return phrase("calibration.summary_odds", bs=odds["brier"], n=odds["n"], bs0=odds["brier_prior"])


def calibration_content(pooled: list[dict], issued_on: str = "", config: Config | None = None) -> dict:
    """Everything the calibration report says, as plain data.

    ``pooled`` are the entries of the pooled ledgers
    (:func:`groundwater.ledger.pool_ledgers`) and ``issued_on`` the date the
    report is issued, as the app writes it ("" to leave it off). Both
    engines return the same structure, which the two document writers lay
    out: a title and subtitle, the cover's rows, the summary, and the
    sections, each with its paragraphs, tables, figures (a key the writer
    draws, from :func:`depth_scores` or :func:`odds_scores`, and a caption)
    and bullets, then the references.
    """
    config = config or Config()
    counts = ledger_counts(pooled)
    after = counts["drilled"] - counts["forecast"]
    depth = depth_scores(pooled, config)
    odds = odds_scores(pooled, config)
    rows = [[phrase("calibration.row_projects"), str(counts["projects"])],
            [phrase("calibration.row_points"), str(counts["points"])],
            [phrase("calibration.row_drilled"), str(counts["drilled"])],
            [phrase("calibration.row_forecasts"), str(counts["forecast"])]]
    issued = _name(issued_on)
    if issued:
        rows.append([phrase("calibration.row_issued"), issued])

    summary = [ledger_summary(pooled)]
    if counts["forecast"]:
        summary.append(phrase("calibration.summary_scored", forecast=counts["forecast"]))
    elif counts["drilled"]:
        summary.append(phrase("calibration.summary_nothing"))
    if counts["forecast"]:
        summary += [_depth_summary(depth), _odds_summary(odds)]
    if counts["drilled"]:
        summary.append(phrase("calibration.summary_hits", minimum=int(config.ledger.min_group)))

    limits = _section("limits", phrase("calibration.limits_heading"))
    limits["bullets"].append(phrase("calibration.limit_files"))
    if after:
        limits["bullets"].append(phrase("calibration.limit_after", after=after))
    limits["bullets"] += [phrase("calibration.limit_driller"), phrase("calibration.limit_names"),
                          phrase("calibration.limit_minimum", minimum=int(config.ledger.min_boreholes),
                                 group=int(config.ledger.min_group)),
                          phrase("calibration.limit_changes")]
    return {
        "title": phrase("calibration.title"),
        "subtitle": phrase("calibration.subtitle"),
        "rows": rows,
        "summary": summary,
        "sections": [_depth_section(depth, pooled), _odds_section(odds, config), _hits_section(pooled, config),
                     limits],
        "references": references_for("calibration"),
    }

"""A ledger of predictions and outcomes (PLAN.md step 5.1).

A siting method that never compares what it predicted with what was drilled
cannot improve. The ledger keeps the two side by side, in the project file,
so that a portfolio of projects can pool them for the calibration of step
5.2. It is not the Depth Spine's sign-off ledger, which records who certified
each value of one borehole.

There is one entry for each survey point. Its prediction is what the survey
said there, written down as plain numbers when the predictions are recorded:
the depth to basement and its band over the models that fit, the
water-bearing zones and their thickness, the drilling depth and its band,
and the chance of a working borehole with what that chance rests on. A
prediction is kept as it was recorded. It is replaced only while the project
holds no completion, and ``before_outcome`` says whether it was recorded
before the borehole was drilled, so a prediction written down afterwards is
never read as a forecast.

Each prediction names the survey team that made it, and each outcome the
contractor who drilled, so the calibration of step 5.2 can give hit rates for
each.

The outcome is what the borehole drilled at the point found: the depth to
basement in the log, its bands of rock, the water strikes, the total depth,
the tested yield, and whether it succeeded as the odds define success. It is
worked out again from the project's completion whenever the project is
saved, so a corrected log corrects it, and it is attached to the entry for
the point the borehole was drilled at: the one a person chose, else the
nearest within ``ledger.pair_within_m`` of the log's position, else the
survey's only point. Nothing else is guessed: the survey's recommended point
is not taken to be the one drilled, since a wrong pairing would mislead the
calibration.

Every function here has a twin of the same name in camel case in
gwt-core.js, and parity holds them to one another.
"""

from __future__ import annotations

import hashlib
import math
import numbers
import re
from collections.abc import Iterable

from .config import Config
from .text import phrase, phrase_table

__all__ = [
    "attach_outcome",
    "clean_ledger",
    "completion_outcome",
    "empty_ledger",
    "entry_header",
    "entry_rows",
    "ledger_counts",
    "ledger_rows",
    "ledger_summary",
    "pair_drilled",
    "point_id",
    "point_prediction",
    "pool_ledgers",
    "record_predictions",
    "survey_predictions",
]


def empty_ledger() -> dict:
    """A ledger with no entry: the one every project starts with."""
    return {"drilled": None, "entries": []}


# ------------------------------------------------------------ plain numbers

def _num(value, digits: int | None) -> float | None:
    """A finite number rounded as Python rounds (not at all for ``digits``
    None), or None. Only a number is one: a number written as text in a
    hand-edited file is not read, as the browser's twin would read it
    differently."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    x = float(value)
    if not math.isfinite(x):
        return None
    return x if digits is None else round(x, digits)


def _band(band, digits: int = 1) -> list[float | None] | None:
    if band is None:
        return None
    return [_num(band.p10, digits), _num(band.p50, digits), _num(band.p90, digits)]


#: The white space a name is collapsed over and trimmed of: ASCII only, as
#: the field kit's codes are, so the two engines write the same name.
_SPACE = re.compile(r"[ \t\n\r\f\v]+")


def _name(value) -> str:
    """A person's or firm's name as typed, with its runs of white space made
    one space and its ends trimmed; "" for anything but text."""
    return _SPACE.sub(" ", value).strip(" ") if isinstance(value, str) else ""


def _zone(value) -> int | None:
    """A UTM zone number, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def point_id(sounding_id: str, easting, northing, utm_zone, community: str = "",
             district: str = "") -> str:
    """The entry's identifier: a hash of the point's name, place and position.

    Two copies of one project's file give their points the same identifier,
    so a portfolio pools them once; two projects whose soundings share a name
    ("VES 1") differ by their place or their position. The position is taken
    to the metre, so a re-read of the same coordinates does not move it.
    """
    e = "" if _num(easting, 1) is None else f"{float(easting):.0f}"
    n = "" if _num(northing, 1) is None else f"{float(northing):.0f}"
    zone = _zone(utm_zone)
    text = "\n".join([str(sounding_id or ""), e, n, "" if zone is None else str(zone),
                      str(community or ""), str(district or "")])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------- prediction

def _odds(odds) -> dict | None:
    if odds is None:
        return None
    return {
        "probability": _num(odds.probability, 3),
        "low": _num(odds.low, 3),
        "high": _num(odds.high, 3),
        "prior": _num(odds.prior, 3),
        "effective_n": _num(odds.effective_n, 3),
        "status": str(odds.status or ""),
        "matched": str(odds.matched or ""),
        "bgs_code": odds.bgs_code or None,
        "glg": odds.glg or None,
        "success_yield_m3_per_h": _num(odds.success_yield_m3_per_h, 3),
        "calibration": str(odds.calibration or ""),
    }


#: The four parts of the suitability score (siting/suitability.py), in the
#: order the score adds them.
SUITABILITY_PARTS = ("aquifer_thickness", "resistivity_fit", "overburden", "basal_fracture")


def _layers(interp) -> list[list[float | None]]:
    """The best fit's layers as [top, bottom, resistivity], the half-space's
    bottom None: what step 5.3 pairs with the log's bands of rock to fit the
    resistivity edges of each geology unit."""
    out = []
    for layer in getattr(interp, "layers", None) or []:
        bottom = _num(layer.bottom_m, 1)
        out.append([_num(layer.top_m, 1), bottom, _num(layer.rho, 1)])
    return out


def _suitability(components) -> dict | None:
    """The suitability score's four parts, each 0 to 1, or None."""
    if components is None:
        return None
    out = {key: _num(getattr(components, key, None), 3) for key in SUITABILITY_PARTS}
    return None if None in out.values() else out


def point_prediction(interp, model_range, odds, config: Config | None = None, team: str = "",
                     suitability=None) -> dict:
    """What the survey predicts at one point, as plain numbers.

    ``interp`` is the point's interpretation, ``model_range`` its sampled
    range of models (None where none was sampled) and ``odds`` its chance of
    a working borehole (None where it was not worked out); ``team`` is the
    survey team that made it, "" where none is recorded, and ``suitability``
    the parts of its suitability score (the ``components`` of
    siting.assess_siting), None where none was worked out. The drilling
    depth's band is the one the reports print (decisions.depth_decision).
    The layers and the score's parts are what a calibration set (PLAN.md
    step 5.3) is fitted from.
    """
    from .costing.distribution import depth_spread
    from .ves.model_range import quoted_basement_band

    config = config or Config()
    basement_band = weathered_band = depth_band = None
    unresolved = None
    if model_range is not None:
        basement_band = _band(quoted_basement_band(model_range))
        weathered_band = _band(model_range.weathered_m)
        unresolved = _num(model_range.basement_unresolved, 3)
        spread = depth_spread(model_range, config)
        if spread is not None:
            depth_band = [_num(spread.draw(0.1), 1), _num(spread.draw(0.9), 1)]
    return {
        "depth_to_basement_m": _num(interp.depth_to_basement_m, 1),
        "basement_resolved": not interp.basement_not_resolved,
        "investigation_depth_m": _num(interp.investigation_depth_m, 1),
        "water_zones_m": [[_num(top, 1), _num(bottom, 1)] for top, bottom in interp.water_zones],
        "water_bearing_m": _num(interp.aquifer_thickness_m, 1),
        "drilling_depth_m": _num(interp.max_drilling_depth_m, 1),
        "drilling_depth_minimum": bool(interp.basement_not_resolved or interp.drilling_depth_capped),
        "fit_error_percent": _num(interp.fit_error_percent, 2),
        "range_sampled": model_range is not None,
        "basement_band_m": basement_band,
        "basement_unresolved_share": unresolved,
        "weathered_band_m": weathered_band,
        "drilling_depth_band_m": depth_band,
        "odds": _odds(odds),
        "survey_team": _name(team),
        "layers": _layers(interp),
        "suitability": _suitability(suitability),
    }


def survey_predictions(interps, ranges, odds, site, config: Config | None = None,
                       teams: list[str] | None = None, siting=None) -> list[dict]:
    """Each point's place and prediction, in the survey's order.

    ``ranges`` and ``odds`` go with ``interps`` by position (two points can
    share an id), None where a point has none; ``site`` is the project's
    site, for its zone, its place and its field supervisor. ``teams`` go by
    position too: the field supervisor each point's own sheet names. A
    point's survey team is its sheet's, as the geophysical report prints it
    over the sounding, else the project's field supervisor. ``siting`` is
    what siting.assess_siting returned for ``interps``, each result found
    by the ``index`` it carries, since it comes back ranked.
    """
    zone = _zone(getattr(site, "utm_zone", None))
    community = str(getattr(site, "community", "") or "")
    district = str(getattr(site, "district", "") or "")
    supervisor = _name(getattr(site, "supervisor", ""))
    parts = {r.index: r.components for r in siting or [] if getattr(r, "index", None) is not None}
    out = []
    for k, interp in enumerate(interps):
        point = {
            "sounding_id": str(interp.sounding_id or ""),
            "easting": _num(interp.site_easting, 1),
            "northing": _num(interp.site_northing, 1),
            "utm_zone": zone,
            "community": community,
            "district": district,
        }
        model_range = ranges[k] if ranges is not None and k < len(ranges) else None
        chance = odds[k] if odds is not None and k < len(odds) else None
        team = (_name(teams[k]) if teams is not None and k < len(teams) else "") or supervisor
        out.append({"point": point, "prediction": point_prediction(interp, model_range, chance, config, team,
                                                                   parts.get(k))})
    return out


# ------------------------------------------------------------------ outcome

def completion_outcome(log, analysis=None, config: Config | None = None, contractor: str = "") -> dict | None:
    """What the borehole found, or None where the project holds no log.

    ``contractor`` is the project's drilling contractor, from its site
    details; it wins over the log's own, as the project's details win over
    every sheet's in the reports' headers, and the log's is taken where the
    details leave it blank.

    The depth to basement is the top of the log's first band of basement
    rock, in the one class table every drawing uses; none in the log means
    it was not reached. Success is as the odds define it where a pumping
    test says: a tested safe yield of at least ``odds.success_yield_m3_per_h``.
    Without a test, a hole whose recorded status reads as unsuccessful (dry,
    abandoned, collapsed or low-yielding, as the portfolio classes it) is a
    failure and one recorded as successful is kept as the driller's word;
    anything else is not known yet. ``success_basis`` says which of these it
    was: ``tested``, ``recorded_failure`` or ``recorded_success``.
    """
    if log is None:
        return None
    from .design.lithology import lithology_bands
    from .site_status import classify_text

    config = config or Config()
    bands = lithology_bands(list(log.intervals))
    basement = next((top for top, _, klass in bands if klass.key == "basement"), None)
    status = classify_text(log.status or "")
    status_class = status.value if status is not None else None
    rec = getattr(analysis, "yield_recommendation", None) if analysis is not None else None
    raw = _num(rec.safe_yield_m3_per_h, None) if rec is not None else None
    safe = _num(raw, 2)
    band = None
    holds = None
    spread = getattr(analysis, "spread", None) if analysis is not None else None
    if safe is not None and spread is not None and spread.bootstrap is not None:
        holds = bool(spread.holds_at_dry_season)
        if spread.bootstrap.p10 is not None and spread.safe_yield_low_m3_per_h is not None:
            # the top is None where the projection gives no upper yield
            band = [_num(spread.safe_yield_low_m3_per_h, 2), _num(spread.safe_yield_high_m3_per_h, 2)]
    threshold = float(config.odds.success_yield_m3_per_h)
    if raw is not None:
        # on the yield as worked out, not as rounded for the file
        success, basis = raw >= threshold, "tested"
    elif status_class == "dry":
        success, basis = False, "recorded_failure"
    elif status_class == "successful":
        success, basis = True, "recorded_success"
    else:
        success, basis = None, None
    site = log.site
    return {
        "borehole_ref": str(log.borehole_ref or ""),
        "contractor": _name(contractor) or _name(getattr(site, "contractor", "")),
        "easting": _num(site.easting, 1),
        "northing": _num(site.northing, 1),
        "utm_zone": _zone(site.utm_zone),
        "completion_date": str(log.completion_date or ""),
        "total_depth_m": _num(log.total_depth_m, 1),
        "status": str(log.status or ""),
        "status_class": status_class,
        "basement_m": _num(basement, 1),
        "intervals": [[_num(top, 1), _num(bottom, 1), klass.key] for top, bottom, klass in bands],
        "water_strikes_m": [_num(depth, 1) for depth in log.water_strikes_m],
        "safe_yield_m3_per_h": safe,
        "safe_yield_band_m3_per_h": band,
        "yield_confidence": str(rec.confidence) if rec is not None and safe is not None else None,
        "holds_at_dry_season": holds,
        "success_yield_m3_per_h": _num(threshold, 3),
        "success": success,
        "success_basis": basis,
    }


# --------------------------------------------------------------- recording

def record_predictions(ledger: dict, predictions: list[dict], recorded_on: str,
                       outcome_known: bool, toolkit: str) -> tuple[dict, list[str]]:
    """The ledger with the survey's predictions written in, and the ids of
    the entries that kept the prediction they had.

    A point's entry is replaced unless its prediction was recorded before
    drilling and the project now holds a completion: that prediction is a
    forecast, and a forecast is kept as it was made. ``outcome_known`` says
    whether the project holds a completion now; an entry recorded while it
    does is marked as recorded after drilling. An entry keeps its outcome
    through a new recording, and a point no longer in the survey keeps its
    entry: the ledger is a record, not the survey's current state.
    """
    ledger = clean_ledger(ledger)
    entries = list(ledger["entries"])
    where = {entry["id"]: k for k, entry in enumerate(entries)}
    kept: list[str] = []
    for item in predictions:
        point = item["point"]
        pid = point_id(point["sounding_id"], point["easting"], point["northing"], point["utm_zone"],
                       point["community"], point["district"])
        k = where.get(pid)
        old = entries[k] if k is not None else None
        if old is not None and old["before_outcome"] and outcome_known:
            kept.append(pid)
            continue
        entry = {
            "id": pid,
            "point": dict(point),
            "prediction": item["prediction"],
            "recorded_on": str(recorded_on),
            "before_outcome": not outcome_known,
            "toolkit": str(toolkit),
            "outcome": old["outcome"] if old is not None else None,
            "pairing": old["pairing"] if old is not None else None,
        }
        if k is None:
            where[pid] = len(entries)
            entries.append(entry)
        else:
            entries[k] = entry
    return {"drilled": ledger["drilled"], "entries": entries}, kept


def _distance(point: dict, outcome: dict) -> float | None:
    """Ground distance from a survey point to the logged borehole, each
    position read in its own zone (the zone inferred from the easting where
    none is recorded), or None where either has no position."""
    from .geo import UTMCoordinate, infer_zone_for_sierra_leone, utm_distance_m

    if None in (point.get("easting"), point.get("northing"), outcome.get("easting"),
                outcome.get("northing")):
        return None
    a_zone = point.get("utm_zone") or infer_zone_for_sierra_leone(point["easting"])
    b_zone = outcome.get("utm_zone") or infer_zone_for_sierra_leone(outcome["easting"])
    return utm_distance_m(UTMCoordinate(point["easting"], point["northing"], a_zone),
                          UTMCoordinate(outcome["easting"], outcome["northing"], b_zone))


def pair_drilled(ledger: dict, outcome: dict | None,
                 config: Config | None = None) -> tuple[str | None, dict | None]:
    """The id of the entry the borehole was drilled at, and how that was
    decided: chosen by a person, the nearest point within
    ``ledger.pair_within_m`` of the log's position, or the survey's only
    point. (None, None) where none of these says, or there is no outcome."""
    config = config or Config()
    entries = clean_ledger(ledger)["entries"]
    if outcome is None or not entries:
        return None, None
    chosen = ledger.get("drilled") if isinstance(ledger, dict) else None
    for entry in entries:
        if entry["id"] == chosen:
            return chosen, {"how": "chosen", "distance_m": _num(_distance(entry["point"], outcome), 1)}
    best, best_d = None, None
    for entry in entries:
        d = _distance(entry["point"], outcome)
        if d is not None and d <= float(config.ledger.pair_within_m) and (best_d is None or d < best_d):
            best, best_d = entry, d
    if best is not None:
        return best["id"], {"how": "nearest", "distance_m": _num(best_d, 1)}
    if len(entries) == 1:
        only = entries[0]
        return only["id"], {"how": "only", "distance_m": _num(_distance(only["point"], outcome), 1)}
    return None, None


def attach_outcome(ledger: dict, outcome: dict | None, config: Config | None = None) -> dict:
    """The ledger with the project's completion attached to the point it was
    drilled at, and taken off every other.

    ``outcome`` is :func:`completion_outcome` of the project as it stands.
    Where the project holds no completion (``outcome`` None) the outcomes the
    ledger already has are kept: a file whose log was not carried with it
    keeps what it recorded. Where a completion cannot be paired, no entry
    holds it, and the app asks which point was drilled.
    """
    ledger = clean_ledger(ledger)
    if outcome is None:
        return ledger
    pid, pairing = pair_drilled(ledger, outcome, config)
    entries = []
    for entry in ledger["entries"]:
        drilled = entry["id"] == pid
        entries.append(dict(entry, outcome=outcome if drilled else None,
                            pairing=pairing if drilled else None))
    return {"drilled": ledger["drilled"], "entries": entries}


# ---------------------------------------------------------------- cleaning

_PREDICTION_NUMBERS = (("depth_to_basement_m", 1), ("investigation_depth_m", 1), ("water_bearing_m", 1),
                       ("drilling_depth_m", 1), ("fit_error_percent", 2),
                       ("basement_unresolved_share", 3))
_PREDICTION_FLAGS = ("basement_resolved", "drilling_depth_minimum", "range_sampled")
_PREDICTION_BANDS = (("basement_band_m", 3), ("weathered_band_m", 3), ("drilling_depth_band_m", 2))
_ODDS_NUMBERS = ("probability", "low", "high", "prior", "effective_n", "success_yield_m3_per_h")
_ODDS_TEXTS = ("status", "matched", "calibration")
_OUTCOME_NUMBERS = (("easting", 1), ("northing", 1), ("total_depth_m", 1), ("basement_m", 1),
                    ("safe_yield_m3_per_h", 2), ("success_yield_m3_per_h", 3))
_OUTCOME_TEXTS = ("borehole_ref", "completion_date", "status")
_OUTCOME_KEYS = {"status_class": ("successful", "dry", "sited", "in_progress", "other"),
                 "success_basis": ("tested", "recorded_failure", "recorded_success"),
                 "yield_confidence": ("established", "indicative")}
_PAIRINGS = ("chosen", "nearest", "only")


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _flag(value) -> bool | None:
    return value if isinstance(value, bool) else None


def _numbers(value, length: int | None, digits: int) -> list | None:
    """A list of numbers (of ``length``, where one is given), or None."""
    if not isinstance(value, list) or (length is not None and len(value) != length):
        return None
    out = [_num(v, digits) for v in value]
    return None if None in out else out


def _clean_prediction(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out: dict = {key: _num(raw.get(key), digits) for key, digits in _PREDICTION_NUMBERS}
    for key in _PREDICTION_FLAGS:
        out[key] = raw.get(key) is True
    out["survey_team"] = _name(raw.get("survey_team"))
    zones = raw.get("water_zones_m")
    out["water_zones_m"] = [pair for pair in (_numbers(z, 2, 1) for z in zones) if pair is not None] \
        if isinstance(zones, list) else []
    for key, length in _PREDICTION_BANDS:
        out[key] = _numbers(raw.get(key), length, 1)
    layers = raw.get("layers")
    out["layers"] = [
        [_num(layer[0], 1), _num(layer[1], 1), _num(layer[2], 1)] for layer in layers
        if isinstance(layer, list) and len(layer) == 3 and _num(layer[0], 1) is not None
        and _num(layer[2], 1) is not None and (layer[1] is None or _num(layer[1], 1) is not None)
    ] if isinstance(layers, list) else []
    parts = raw.get("suitability")
    clean_parts = {key: _num(parts.get(key), 3) for key in SUITABILITY_PARTS} if isinstance(parts, dict) else None
    out["suitability"] = clean_parts if clean_parts is not None and None not in clean_parts.values() else None
    odds = raw.get("odds")
    if isinstance(odds, dict):
        clean: dict = {key: _num(odds.get(key), 3) for key in _ODDS_NUMBERS}
        clean.update({key: _text(odds.get(key)) for key in _ODDS_TEXTS})
        clean["bgs_code"] = odds.get("bgs_code") if isinstance(odds.get("bgs_code"), str) else None
        clean["glg"] = odds.get("glg") if isinstance(odds.get("glg"), str) else None
        out["odds"] = clean if clean["probability"] is not None else None
    else:
        out["odds"] = None
    return dict(sorted(out.items()))


def _clean_outcome(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out: dict = {key: _num(raw.get(key), digits) for key, digits in _OUTCOME_NUMBERS}
    out.update({key: _text(raw.get(key)) for key in _OUTCOME_TEXTS})
    out["contractor"] = _name(raw.get("contractor"))
    for key, allowed in _OUTCOME_KEYS.items():
        out[key] = raw.get(key) if raw.get(key) in allowed else None
    out["utm_zone"] = _zone(raw.get("utm_zone"))
    intervals = raw.get("intervals")
    out["intervals"] = [
        [_num(iv[0], 1), _num(iv[1], 1), iv[2]] for iv in intervals
        if isinstance(iv, list) and len(iv) == 3 and isinstance(iv[2], str)
        and _num(iv[0], 1) is not None and _num(iv[1], 1) is not None
    ] if isinstance(intervals, list) else []
    strikes = raw.get("water_strikes_m")
    out["water_strikes_m"] = [s for s in (_num(v, 1) for v in strikes) if s is not None] \
        if isinstance(strikes, list) else []
    band = raw.get("safe_yield_band_m3_per_h")
    out["safe_yield_band_m3_per_h"] = (
        [_num(band[0], 2), _num(band[1], 2)]
        if isinstance(band, list) and len(band) == 2 and _num(band[0], 2) is not None else None)
    out["holds_at_dry_season"] = _flag(raw.get("holds_at_dry_season"))
    out["success"] = _flag(raw.get("success"))
    if out["success"] is None:
        out["success_basis"] = None
    return dict(sorted(out.items()))


def _clean_point(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    return {
        "community": _text(raw.get("community")),
        "district": _text(raw.get("district")),
        "easting": _num(raw.get("easting"), 1),
        "northing": _num(raw.get("northing"), 1),
        "sounding_id": _text(raw.get("sounding_id")),
        "utm_zone": _zone(raw.get("utm_zone")),
    }


def clean_ledger(raw) -> dict:
    """A ledger as read from a file, in the shape the functions here write.

    A hand-edited file is a message, not a traceback: an entry that is not a
    mapping, or has no id, point or prediction, is left out, and a field of
    the wrong kind is blank rather than an error. A prediction whose timing
    is not recorded is taken as recorded after drilling, the cautious
    reading. An entry whose id appears twice is kept once, the first time.
    """
    if not isinstance(raw, dict):
        return empty_ledger()
    entries, seen = [], set()
    listed = raw.get("entries")
    for item in listed if isinstance(listed, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        point, prediction = _clean_point(item.get("point")), _clean_prediction(item.get("prediction"))
        if point is None or prediction is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        outcome = _clean_outcome(item.get("outcome"))
        pairing = item.get("pairing")
        if (outcome is None or not isinstance(pairing, dict) or pairing.get("how") not in _PAIRINGS):
            pairing = None
        else:
            pairing = {"distance_m": _num(pairing.get("distance_m"), 1), "how": pairing["how"]}
        entries.append({
            "before_outcome": item.get("before_outcome") is True,
            "id": item["id"],
            "outcome": outcome,
            "pairing": pairing,
            "point": point,
            "prediction": prediction,
            "recorded_on": _text(item.get("recorded_on")),
            "toolkit": _text(item.get("toolkit")),
        })
    drilled = raw.get("drilled")
    return {"drilled": drilled if isinstance(drilled, str) and drilled in seen else None,
            "entries": entries}


# ------------------------------------------------------------- comparison

def _share(fraction: float) -> str:
    from .ves.model_range import _share as share

    return share(fraction)


def basement_check(prediction: dict, outcome: dict | None) -> str | None:
    """How the depth to basement found compares with the predicted band:
    ``inside``, ``deeper``, ``shallower``, ``unreached_allowed`` (not reached
    yet and the band reaches below the hole), ``no_band``, or None where the
    point was not drilled."""
    if outcome is None:
        return None
    band = prediction.get("basement_band_m")
    if band is None:
        return "no_band"
    low, high = band[0], band[2]
    found = outcome.get("basement_m")
    if found is None:
        total = outcome.get("total_depth_m")
        if total is not None and total > high:
            return "deeper"
        return "unreached_allowed"
    if found < low:
        return "shallower"
    if found > high:
        return "deeper"
    return "inside"


def _depth_list(values: Iterable[float]) -> str:
    from .utils import fmt_num

    return ", ".join(fmt_num(v) for v in values)


def _zones_text(prediction: dict) -> str:
    from .ves.interpret import zone_cell

    zones = prediction["water_zones_m"]
    if not zones:
        return phrase("ledger.zones_none")
    open_last = not prediction["basement_resolved"]
    cells = [zone_cell(top, bottom, open_ended=open_last and k == len(zones) - 1)
             for k, (top, bottom) in enumerate(zones)]
    return phrase("ledger.zones", zones=", ".join(cells))


def _basement_predicted(prediction: dict) -> str:
    band = prediction["basement_band_m"]
    d = prediction["depth_to_basement_m"]
    if d is None:
        if band is not None:
            return phrase("ledger.basement_none_band", low=band[0], high=band[2])
        return phrase("ledger.basement_none", doi=prediction["investigation_depth_m"] or 0.0)
    if band is not None:
        return phrase("ledger.basement_band", d=d, low=band[0], high=band[2])
    return phrase("ledger.basement_best", d=d)


def _basement_found(outcome: dict) -> str:
    if outcome["basement_m"] is not None:
        return phrase("ledger.found_basement", d=outcome["basement_m"])
    if outcome["total_depth_m"] is not None:
        return phrase("ledger.found_basement_unreached", td=outcome["total_depth_m"])
    return phrase("ledger.found_basement_no_depth")


def _depth_predicted(prediction: dict) -> str:
    d = prediction["drilling_depth_m"] or 0.0
    depth = phrase("ledger.depth_least" if prediction["drilling_depth_minimum"] else "ledger.depth_about",
                   d=d)
    band = prediction["drilling_depth_band_m"]
    if band is None:
        return depth
    if band[0] == band[1]:
        return phrase("ledger.depth_band_flat", depth=depth, low=band[0])
    return phrase("ledger.depth_band", depth=depth, low=band[0], high=band[1])


def _odds_text(prediction: dict) -> str:
    odds = prediction["odds"]
    if odds is None:
        return phrase("ledger.odds_none")
    return phrase("ledger.odds_short", p=_share(odds["probability"]), low=_share(odds["low"] or 0.0),
                  high=_share(odds["high"] or 0.0))


def outcome_text(outcome: dict | None) -> str:
    """How the borehole turned out, in a few words, by what says so."""
    if outcome is None:
        return phrase("ledger.not_drilled")
    basis = outcome["success_basis"]
    if basis == "tested":
        if outcome["success"]:
            return phrase("ledger.outcome_success_tested", y=outcome["safe_yield_m3_per_h"])
        return phrase("ledger.outcome_short_tested", y=outcome["safe_yield_m3_per_h"],
                      t=outcome["success_yield_m3_per_h"] or 0.0)
    if basis == "recorded_failure":
        return phrase("ledger.outcome_failure_recorded", status=outcome["status"])
    if basis == "recorded_success":
        return phrase("ledger.outcome_success_recorded", status=outcome["status"])
    return phrase("ledger.outcome_unknown")


def _strikes_check(prediction: dict, outcome: dict) -> str:
    strikes = outcome["water_strikes_m"]
    if not strikes or not prediction["water_zones_m"]:
        return ""
    inside = sum(1 for s in strikes if any(top <= s <= bottom for top, bottom in prediction["water_zones_m"]))
    return phrase("ledger.strikes_in_zones", k=inside, n=len(strikes))


def entry_header() -> list[str]:
    """The four columns of :func:`entry_rows`."""
    return [phrase("ledger.col_quantity"), phrase("ledger.col_predicted"), phrase("ledger.col_found"),
            phrase("ledger.col_check")]


def entry_rows(entry: dict) -> list[list[str]]:
    """One point's prediction beside what was found, as rows of four cells:
    the quantity, what was predicted, what was found, and how they compare."""
    prediction, outcome = entry["prediction"], entry["outcome"]
    not_drilled = phrase("ledger.not_drilled")
    if outcome is None:
        found = [not_drilled] * 4
        checks = ["", "", "", ""]
    else:
        strikes = outcome["water_strikes_m"]
        found = [
            _basement_found(outcome),
            phrase("ledger.strikes", strikes=_depth_list(strikes)) if strikes
            else phrase("ledger.strikes_none"),
            phrase("ledger.drilled_to", td=outcome["total_depth_m"]) if outcome["total_depth_m"] is not None
            else phrase("ledger.drilled_no_depth"),
            outcome_text(outcome),
        ]
        checks = [phrase_table("ledger.basement_check")[basement_check(prediction, outcome) or "no_band"],
                  _strikes_check(prediction, outcome), "", ""]
    labels = [phrase("ledger.row_basement"), phrase("ledger.row_zones"), phrase("ledger.row_depth"),
              phrase("ledger.row_odds")]
    predicted = [_basement_predicted(prediction), _zones_text(prediction), _depth_predicted(prediction),
                 _odds_text(prediction)]
    return [[labels[k], predicted[k], found[k], checks[k]] for k in range(4)]


# ----------------------------------------------------------------- pooling

def _rank(entry: dict) -> tuple:
    """Which of two copies of one entry a pool keeps: the one with an
    outcome, then one recorded before drilling, then the later recording."""
    return (entry["outcome"] is not None, entry["before_outcome"], entry["recorded_on"])


def pool_ledgers(items: Iterable[tuple[str, dict]]) -> list[dict]:
    """The entries of many projects' ledgers, each once.

    ``items`` are (project label, ledger) pairs, as the portfolio reads them
    from its files. An entry found in two files (two copies of one project)
    is kept once, the copy with the most in it; each kept entry carries the
    label of the project it came from as ``project``. The order is the order
    the entries were first met.
    """
    kept: dict[str, dict] = {}
    for label, ledger in items:
        for entry in clean_ledger(ledger)["entries"]:
            have = kept.get(entry["id"])
            if have is None or _rank(entry) > _rank(have):
                kept[entry["id"]] = dict(entry, project=str(label or ""))
    return list(kept.values())


def ledger_counts(pooled: list[dict]) -> dict:
    """How much a pooled ledger holds: the points predicted, the projects
    they are in, those drilled, and those drilled whose prediction was
    recorded before drilling."""
    drilled = [entry for entry in pooled if entry["outcome"] is not None]
    return {
        "points": len(pooled),
        "projects": len({entry["project"] for entry in pooled}),
        "drilled": len(drilled),
        "forecast": sum(1 for entry in drilled if entry["before_outcome"]),
        "success": sum(1 for entry in drilled if entry["outcome"]["success"] is True),
        "failure": sum(1 for entry in drilled if entry["outcome"]["success"] is False),
        "unknown": sum(1 for entry in drilled if entry["outcome"]["success"] is None),
    }


def ledger_summary(pooled: list[dict]) -> str:
    """What a pooled ledger holds, in a sentence."""
    if not pooled:
        return phrase("ledger.pool_none")
    counts = ledger_counts(pooled)
    return phrase("ledger.pool_counts", points=counts["points"], projects=counts["projects"],
                  drilled=counts["drilled"], forecast=counts["forecast"])


def ledger_rows(pooled: list[dict]) -> tuple[list[str], list[list[str]]]:
    """The drilled points of a pooled ledger as a table: its header and rows.
    The points not drilled are counted (:func:`ledger_counts`), not listed."""
    header = [phrase("ledger.pool_col_project"), phrase("ledger.pool_col_point"),
              phrase("ledger.pool_col_recorded"), phrase("ledger.pool_col_basement"),
              phrase("ledger.pool_col_found"), phrase("ledger.pool_col_check"),
              phrase("ledger.pool_col_odds"), phrase("ledger.pool_col_outcome")]
    rows = []
    for entry in pooled:
        outcome = entry["outcome"]
        if outcome is None:
            continue
        prediction = entry["prediction"]
        rows.append([
            entry["project"],
            entry["point"]["sounding_id"],
            phrase("ledger.recorded_before" if entry["before_outcome"] else "ledger.recorded_after"),
            _basement_predicted(prediction),
            _basement_found(outcome),
            phrase_table("ledger.basement_check")[basement_check(prediction, outcome) or "no_band"],
            _odds_text(prediction),
            outcome_text(outcome),
        ])
    return header, rows

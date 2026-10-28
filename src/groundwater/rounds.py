"""Service rounds: what is due, by area mechanic, in an order (PLAN.md step 7.3).

The asset registry says, for one borehole, what is due and when
(:func:`~groundwater.registry.asset_state`). A district water office does
not send a mechanic to one borehole: it sends each area mechanic out on a
round. So this module takes the register of many boreholes and a day, and
works out which boreholes have a visit due on that day, whose round each is
on, and in what order to make them.

* **What is due.** The registry's three visits: the sanitary inspection,
  the routine inspection of the pump and rising main, and the water quality
  sample, each due at an interval from ``data/defaults.json`` counted from
  the last one recorded, or from commissioning. The routine inspection's
  interval is the one the borehole's design sets for its rising main (PLAN.md
  step 7.2), which the record carries. A visit due or overdue on the day is
  on the round, and so is one with nothing to count from: a borehole with no
  record of a visit is due now, and its condition is "not known", never
  working. A decommissioned borehole is not visited.
* **Whose round.** The area mechanic named on the borehole's record, else
  the mechanic named for its chiefdom in a table the programme keeps (one
  line a chiefdom: the chiefdom, a colon and the name), else none, and the
  stops with no mechanic are a group of their own, last.
* **In what order.** A nearest-neighbour walk, stated as such: from the
  stop due the longest to the nearest stop not yet visited, each time,
  in a straight line on the ellipsoid to the metre, a tie going to the lower
  identifier. It is an order, not an optimal route. Stops with no position
  come last, by identifier.

The day is an input, never the clock. Several records of one borehole (two
project files of the same borehole, from two phones) are one stop, their
histories merged as the registry merges them. Every function here has a twin
of the same name in camel case in gwt-core.js, and parity holds them to one
another.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TypeGuard

from .geo import geodesic_distance_m, infer_zone_for_sierra_leone, utm_to_geographic
from .registry import (
    Asset,
    Schedule,
    asset_from_dict,
    asset_state,
    iso_date,
    merge_events,
    trim_field,
)
from .sanitary import form_questions
from .text import phrase, phrase_table

__all__ = [
    "ROUND_STATES",
    "mechanic_for",
    "parse_area_mechanics",
    "round_header",
    "round_rows",
    "round_text",
    "rounds_text",
    "service_rounds",
    "stop_sheet",
]

#: The states of a registry visit that put it on a round: overdue, due, and
#: due now with nothing to count from.
ROUND_STATES = ("overdue", "due", "unknown")

#: The fields of a record taken from the first record of a borehole that has
#: one, when several records name it; the events are merged instead. A text
#: field counts as had when it is text that is not blank once trimmed, any
#: other field when it is not missing.
_MERGED_TEXT = ("community", "district", "chiefdom", "pump_type", "installed_by",
                "area_mechanic")
_MERGED_VALUES = ("easting", "northing", "utm_zone", "total_depth_m",
                  "safe_yield_m3_per_h", "rising_main")


def _day(as_of) -> date:
    """The day the round is drawn up: a date, or one written YYYY-MM-DD and
    nothing else, read as ``isoDay`` reads it in the browser."""
    day = as_of if isinstance(as_of, date) else iso_date(as_of)
    if day is None:
        raise ValueError("a service round needs the day it is drawn up, as YYYY-MM-DD")
    return day


def _text(value) -> str:
    return trim_field(value) if isinstance(value, str) else ""


def _fold(text: str) -> str:
    """A chiefdom's name for matching: A to Z as a to z, nothing else
    changed, so both engines match exactly the same names."""
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in text)


def _number(value: object) -> TypeGuard[int | float]:
    """A finite number, as ``typeof value === 'number'`` and ``isFinite``
    read it in the browser: not a bool, and not text that reads as one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an int past a double, which the browser reads as Infinity
        return False


# ------------------------------------------------------------ the mechanics

def parse_area_mechanics(text) -> dict:
    """The area mechanics by chiefdom, from one line a chiefdom.

    A line is the chiefdom, a colon and the mechanic's name; blank lines are
    passed over. A line that cannot be read is not guessed at: it is left
    out, and ``skipped`` says why, line by line. Of two lines naming one
    chiefdom (matched with A to Z read as a to z) the first is used.
    """
    entries: list[dict] = []
    skipped: list[str] = []
    seen: set[str] = set()
    raw = text if isinstance(text, str) else ""
    for number, line in enumerate(raw.split("\n"), start=1):
        line = trim_field(line)
        if not line:
            continue
        chiefdom, colon, mechanic = line.partition(":")
        if not colon:
            skipped.append(phrase("rounds.mechanics_no_colon", line=number))
            continue
        chiefdom, mechanic = trim_field(chiefdom), trim_field(mechanic)
        if not chiefdom or not mechanic:
            skipped.append(phrase("rounds.mechanics_blank", line=number))
            continue
        if _fold(chiefdom) in seen:
            skipped.append(phrase("rounds.mechanics_repeated", line=number, chiefdom=chiefdom))
            continue
        seen.add(_fold(chiefdom))
        entries.append({"chiefdom": chiefdom, "mechanic": mechanic})
    return {"entries": entries, "skipped": skipped}


def mechanic_for(asset, mechanics=None) -> tuple[str, str]:
    """The area mechanic whose round ``asset`` is on, and how that was found:
    ``asset`` (named on its record), ``chiefdom`` (named for its chiefdom in
    ``mechanics``, the entries :func:`parse_area_mechanics` returns) or
    ``none``."""
    named = _text(getattr(asset, "area_mechanic", ""))
    if named:
        return named, "asset"
    chiefdom = _fold(_text(getattr(asset, "chiefdom", "")))
    if chiefdom:
        for entry in mechanics or []:
            if not isinstance(entry, dict):
                continue
            mechanic = _text(entry.get("mechanic"))
            if mechanic and _fold(_text(entry.get("chiefdom"))) == chiefdom:
                return mechanic, "chiefdom"
    return "", "none"


# ---------------------------------------------------------------- the stops

def _position(asset: Asset) -> tuple[float, float] | None:
    """Latitude and longitude, from an easting and northing that are both
    finite numbers, each in its own zone (inferred from the easting where the
    record names no zone from 1 to 60), or None."""
    easting, northing, given = asset.easting, asset.northing, asset.utm_zone
    if not (_number(easting) and _number(northing)):
        return None
    zone = (int(given) if _number(given) and given == int(given) and 1 <= given <= 60
            else infer_zone_for_sierra_leone(float(easting)))
    try:
        lat, lon = utm_to_geographic(float(easting), float(northing), zone)
    except (ArithmeticError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    return lat, lon


def _position_text(lat: float, lon: float) -> str:
    """As the headworks plate's symbol writes a position."""
    return (f"{abs(lat):.5f} {'N' if lat >= 0 else 'S'}, "
            f"{abs(lon):.5f} {'E' if lon >= 0 else 'W'}")


def _records(assets) -> tuple[list[Asset], int, int]:
    """The records read as assets, those of one borehole as one; with how
    many records named a borehole already named, and how many could not be
    read."""
    merged: dict[str, Asset] = {}
    repeated = unreadable = 0
    for raw in assets or []:
        asset = asset_from_dict(raw.as_dict() if isinstance(raw, Asset) else raw)
        if asset is None:
            unreadable += 1
            continue
        first = merged.get(asset.asset_id)
        if first is None:
            merged[asset.asset_id] = asset
            continue
        repeated += 1
        for name in _MERGED_TEXT:
            if not _text(getattr(first, name)) and _text(getattr(asset, name)):
                setattr(first, name, getattr(asset, name))
        for name in _MERGED_VALUES:
            if getattr(first, name) in (None, "") and getattr(asset, name) not in (None, ""):
                setattr(first, name, getattr(asset, name))
        first.events = merge_events(first.asset_id, first.events, asset.events)
    return list(merged.values()), repeated, unreadable


def _walk(stops: list[dict]) -> list[dict]:
    """The stops in the order of a nearest-neighbour walk, each with the
    straight-line distance from the one before it, in whole metres."""
    placed = [s for s in stops if s["placed"]]
    unplaced = sorted((s for s in stops if not s["placed"]), key=lambda s: s["asset_id"])
    order: list[dict] = []
    if placed:
        here = min(placed, key=lambda s: (s["_first"], s["asset_id"]))
        here["leg_m"] = None
        order.append(here)
        left = [s for s in placed if s is not here]
        while left:
            for stop in left:
                stop["_leg"] = round(geodesic_distance_m(*here["_where"], *stop["_where"]))
            here = min(left, key=lambda s: (s["_leg"], s["asset_id"]))
            here["leg_m"] = here["_leg"]
            order.append(here)
            left = [s for s in left if s is not here]
    for stop in unplaced:
        stop["leg_m"] = None
        order.append(stop)
    for number, stop in enumerate(order, start=1):
        stop["order"] = number
        # the working values are not part of the answer: a latitude computed
        # by two engines' trigonometry need not agree to the last bit, and
        # the stop's position is given as the plate writes it instead
        for working in ("_leg", "_first", "_where"):
            stop.pop(working, None)
    return order


def service_rounds(assets, as_of, schedule: Schedule | None = None,
                   mechanics=None) -> dict:
    """The service rounds of a register of boreholes on the day ``as_of``.

    ``assets`` are registry assets (or their saved records); ``as_of`` is a
    date or a day written YYYY-MM-DD, never read off the clock; ``schedule``
    the intervals (:meth:`Schedule.from_config`), and ``mechanics`` the area
    mechanics by chiefdom (the ``entries`` of :func:`parse_area_mechanics`).

    Each round is a mechanic's (``mechanic``, blank for the stops no
    mechanic is named for, which come last) with its ``stops`` in order and
    the sum of the legs between them (``distance_m``). Each stop carries the
    borehole's identifier and the line a scan of its plate begins with
    (``plate``), where it is, its condition on record and the visits due
    (the registry's due items, with the interval and its basis), and the
    distance from the stop before.
    """
    day = _day(as_of)
    schedule = schedule or Schedule()
    records, repeated, unreadable = _records(assets)
    groups: dict[str, list[dict]] = {}
    nothing_due = decommissioned = 0
    for asset in records:
        state = asset_state(asset, day, schedule)
        if state.function == "decommissioned":
            decommissioned += 1
            continue
        due = [item for item in state.due if item.state in ROUND_STATES]
        if not due:
            nothing_due += 1
            continue
        mechanic, how = mechanic_for(asset, mechanics)
        where = _position(asset)
        community, district = _text(asset.community), _text(asset.district)
        place = community or "(unnamed site)"
        groups.setdefault(mechanic, []).append({
            "order": 0,
            "asset_id": asset.asset_id,
            "plate": f"BOREHOLE {asset.asset_id}",
            # as the registry labels a borehole, from the fields as read here
            "label": f"{place} ({district})" if district else place,
            "community": community,
            "chiefdom": _text(asset.chiefdom),
            "district": district,
            "placed": where is not None,
            "position": _position_text(*where) if where else "",
            "mechanic": mechanic,
            "mechanic_from": how,
            "function": state.function,
            "condition": state.label,
            "condition_detail": state.detail,
            "due": [item.as_dict() for item in due],
            "first_due": min(item.due_on or day for item in due).isoformat(),
            "leg_m": None,
            "_first": min(item.due_on or day for item in due),
            "_where": where,
        })
    names = sorted(name for name in groups if name)
    if "" in groups:
        names.append("")
    rounds = []
    for name in names:
        stops = _walk(groups[name])
        rounds.append({
            "mechanic": name,
            "stops": stops,
            "distance_m": sum(s["leg_m"] for s in stops if s["leg_m"] is not None),
            "placed": sum(1 for s in stops if s["placed"]),
            "unplaced": sum(1 for s in stops if not s["placed"]),
        })
    return {
        "as_of": day.isoformat(),
        "rounds": rounds,
        "n_boreholes": len(records),
        "n_stops": sum(len(r["stops"]) for r in rounds),
        "n_nothing_due": nothing_due,
        "n_decommissioned": decommissioned,
        "n_merged": repeated,
        "n_unreadable": unreadable,
        "schedule": {"sanitary_inspection_months": schedule.sanitary_inspection_months,
                     "water_sample_months": schedule.water_sample_months,
                     "grace_days": schedule.grace_days,
                     "routine_inspection_months": schedule.routine_inspection_months},
    }


# -------------------------------------------------------------- the words

def rounds_text(result: dict) -> dict:
    """What the rounds say as a whole: ``summary`` (the headline and the
    counts beside it), ``method`` (how a round is put in order) and
    ``intervals`` (what is due when, and that the intervals are choices)."""
    summary: list[str] = []
    total, stops = result["n_boreholes"], result["n_stops"]
    if not total:
        summary.append(phrase("rounds.empty"))
    elif stops:
        summary.append(phrase("rounds.headline", date=result["as_of"], total=total,
                              due=stops, rounds=len(result["rounds"])))
    else:
        summary.append(phrase("rounds.headline_none", date=result["as_of"], total=total))
    if stops and result["n_nothing_due"]:
        summary.append(phrase("rounds.nothing_due", count=result["n_nothing_due"]))
    if result["n_decommissioned"]:
        summary.append(phrase("rounds.decommissioned", count=result["n_decommissioned"]))
    if result["n_merged"]:
        summary.append(phrase("rounds.merged", count=result["n_merged"]))
    if result["n_unreadable"]:
        summary.append(phrase("rounds.unreadable", count=result["n_unreadable"]))
    plan = result["schedule"]
    return {
        "summary": summary,
        "method": phrase("rounds.method"),
        "intervals": phrase("rounds.intervals", sanitary=plan["sanitary_inspection_months"],
                            sample=plan["water_sample_months"],
                            routine=plan["routine_inspection_months"],
                            grace=plan["grace_days"]),
    }


def round_text(one: dict) -> list[str]:
    """What one round says of itself: whose it is and how many stops, how far
    from the first to the last, the stops with no position, and for the
    stops no mechanic is named for, how to name one."""
    name = one["mechanic"] or phrase("rounds.unassigned")
    out = [phrase("rounds.round_stops", mechanic=name, stops=len(one["stops"]))]
    if one["placed"] > 1:
        out.append(phrase("rounds.round_distance", km=one["distance_m"] / 1000))
    if one["unplaced"]:
        out.append(phrase("rounds.unplaced", count=one["unplaced"]))
    if not one["mechanic"]:
        out.append(phrase("rounds.round_unassigned"))
    return out


def round_header() -> list[str]:
    """The labels of a round's table, in order."""
    return list(phrase_table("rounds.columns").values())


def _due_short(item: dict) -> str:
    return phrase("rounds.due_short", title=item["title"],
                  state=phrase_table("rounds.state")[item["state"]])


def round_rows(one: dict) -> list[list[str]]:
    """A round's stops as the rows of its table."""
    return [[str(stop["order"]), stop["asset_id"], stop["community"], stop["chiefdom"],
             stop["condition"], "; ".join(_due_short(item) for item in stop["due"]),
             "" if stop["leg_m"] is None else phrase("rounds.leg_km", km=stop["leg_m"] / 1000)]
            for stop in one["stops"]]


def stop_sheet(stop: dict) -> dict:
    """What the round sheet prints for one stop: its ``heading``, the
    ``details`` (label and value rows: the identifier and what the plate's
    symbol begins with, where it is, its condition and how far from the stop
    before), and for each visit due the sentence saying what is due and why
    with the boxes for its readings (``visits``), then the boxes for the
    visit itself (``visit``). A box is a row whose last cell is blank."""
    words = phrase_table("rounds.sheet_details")
    if stop["leg_m"] is not None:
        leg = phrase("rounds.sheet_leg", km=stop["leg_m"] / 1000)
    elif not stop["placed"]:
        leg = phrase("rounds.sheet_no_position")
    else:
        leg = phrase("rounds.sheet_first")
    mechanic = (f"{stop['mechanic']} ({phrase_table('rounds.mechanic_from')[stop['mechanic_from']]})"
                if stop["mechanic"] else phrase("rounds.unassigned"))
    details = [
        [words["identifier"], stop["asset_id"]],
        [words["plate"], stop["plate"]],
        [words["community"], stop["community"] or "-"],
        [words["chiefdom"], stop["chiefdom"] or "-"],
        [words["district"], stop["district"] or "-"],
        [words["position"], stop["position"] or phrase("rounds.sheet_no_position")],
        [words["condition"], f"{stop['condition']}. {stop['condition_detail']}"],
        [words["leg"], leg],
        [words["mechanic"], mechanic],
    ]
    states = phrase_table("rounds.state")
    value = phrase("rounds.sheet_value")
    visits = []
    for item in stop["due"]:
        text = phrase("rounds.sheet_due", title=item["title"], state=states[item["state"]],
                      detail=item["detail"], basis=item["basis"])
        if item["key"] == "inspection":
            header = [phrase("sanitary.col_number"), phrase("sanitary.col_question"),
                      phrase("rounds.sheet_yes_no")]
            rows = [[str(number), question, ""]
                    for number, question in enumerate(form_questions(), start=1)]
        else:
            boxes = phrase_table("rounds.readings_routine" if item["key"] == "routine_inspection"
                                 else "rounds.readings_sample")
            header = [item["title"], value]
            rows = [[label, ""] for label in boxes.values()]
        visits.append({"text": text, "header": header, "rows": rows})
    return {
        "heading": phrase("rounds.sheet_stop", order=stop["order"], place=stop["label"]),
        "details": details,
        "visits": visits,
        "visit": {"header": [phrase("rounds.sheet_visit"), value],
                  "rows": [[label, ""] for label in phrase_table("rounds.readings_visit").values()]},
    }

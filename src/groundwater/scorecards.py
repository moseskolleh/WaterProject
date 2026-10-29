"""Contractor scorecards (PLAN.md step 6.3).

A programme that lets drilling contracts again and again should know how
each contractor has done. The records to tell it are already kept, one
project at a time: the supervision checklist answered on site, the drilled
metres reconciliation (the metres invoiced against the signed daily logs),
the contract and its variation orders on the Procurement page, the drilling
log's completion date and outcome, and the forecast the survey recorded at
the point before it was drilled. This module reads them across a portfolio
of project files and sets them out by contractor.

Each project file carries a **works record** at its top level, written by
:func:`works_record` when the project is saved and read back whole or
blanked by :func:`clean_works`, as the ledger of predictions and outcomes
is: both apps write the same record, so either app's Portfolio page can pool
the other's files. A project file saved before the record existed carries
none, and its ledger's drilled points give only their outcome and their
forecast.

A scorecard gives, for each contractor:

- its boreholes, those the files record as drilled;
- the metres invoiced against the metres in the signed logs, over the
  boreholes where both are typed, and how many claimed more than the
  reconciliation check allows;
- the supervision checklist's items answered No, in the stages the
  contractor works in (``ledger.scorecard_stages``), over the boreholes
  with any of them answered, and which;
- the variation orders signed against its contracts and their value as the
  payment certificate gives it, over the boreholes with a contract;
- the days its boreholes finished after the contract's completion date, over
  those where both dates can be read;
- its dry holes, and on the boreholes forecast before drilling, the number
  the forecasts expected with the binomial range of step 5.2.

A figure no record holds is ``None`` and reads "not recorded", never nought.
A contractor is ranked, by dry holes against the forecast per forecast
borehole, only on at least ``ledger.scorecard_min_boreholes`` forecast
boreholes whose outcome is known, and never on none; below that it is
listed unranked with the reason.

Every public function has a twin of the same name in camel case in
gwt-core.js, and parity holds them to one another.
"""

from __future__ import annotations

import math
import numbers
import re
from datetime import date

from .calibration import _code_points, binomial_range
from .config import Config
from .ledger import _name, _num, attach_outcome, completion_outcome, point_id, pool_ledgers
from .registry import iso_date, trim_field
from .reporting.citations import references_for
from .supervision.checklists import load_checklists, stage_title
from .supervision.field_checks import METRES_TOLERANCE_M, metres_reconciliation_check
from .text import phrase, phrase_table
from .utils import sum_in_order

__all__ = [
    "clean_works",
    "contractor_scorecards",
    "scorecard_boreholes",
    "scorecard_content",
    "works_record",
    "written_day",
]

_BASES = ("tested", "recorded_failure", "recorded_success")

#: A checklist stage's key, as the checklist writes them.
_STAGE_KEY = re.compile(r"[a-z][a-z0-9_]*")


# ------------------------------------------------------------------- dates

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december")

#: An ISO day, with the time of day a date cell can carry after it.
_ISO_WRITTEN = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[ T][0-9]{2}:[0-9]{2}(?::[0-9]{2})?)?")
#: The separators a date written with its month by name is split by.
_SEP = r"[ \t,./-]+"
_DAY_FIRST = re.compile(r"([0-9]{1,2})(?:st|nd|rd|th)?(?:[ \t]+of)?" + _SEP + r"([A-Za-z]+)\.?" + _SEP
                        + r"([0-9]{4})", re.IGNORECASE | re.ASCII)
_MONTH_FIRST = re.compile(r"([A-Za-z]+)\.?" + _SEP + r"([0-9]{1,2})(?:st|nd|rd|th)?" + _SEP + r"([0-9]{4})",
                          re.IGNORECASE | re.ASCII)


def _month(word: str) -> int | None:
    """The month a word names in full or by its first three letters ("Sept"
    too), or None."""
    w = word.lower()
    for k, name in enumerate(_MONTHS, start=1):
        if w == name or w == name[:3] or (k == 9 and w == "sept"):
            return k
    return None


def written_day(text) -> str | None:
    """The day a date as written on a drilling log names, as YYYY-MM-DD, or
    None where it cannot be read without a guess.

    Read: an ISO day (with the time of day a date cell can carry), and a day
    with its month by name, either way round ("13th May, 2018", "May 13
    2018", "13-May-2018"). Not read: a date in figures alone, which can be
    read two ways round, a day the month does not have, and anything else.
    """
    raw = trim_field(text)
    iso = _ISO_WRITTEN.fullmatch(raw)
    if iso:
        day = iso_date(iso.group(1))
        return day.isoformat() if day is not None else None
    for pattern, day_at, month_at in ((_DAY_FIRST, 1, 2), (_MONTH_FIRST, 2, 1)):
        found = pattern.fullmatch(raw)
        if not found:
            continue
        month = _month(found.group(month_at))
        if month is None:
            return None
        try:
            return date(int(found.group(3)), month, int(found.group(day_at))).isoformat()
        except ValueError:
            return None
    return None


def _days_late(due: str, done: str) -> int | None:
    """Days ``done`` (as the log writes it) fell after ``due`` (YYYY-MM-DD),
    negative where it was early, or None where either cannot be read."""
    due_day = iso_date(due)
    done_text = written_day(done)
    done_day = iso_date(done_text) if done_text is not None else None
    if due_day is None or done_day is None:
        return None
    return (done_day - due_day).days


# ------------------------------------------------------------- the record

def _metres(value) -> float | None:
    """Drilled metres as typed: a number not below nought, to the
    centimetre, or None."""
    x = _num(value, 2)
    return x if x is not None and x >= 0.0 else None


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _due(value) -> str:
    """A contract's completion date as typed, trimmed; "" for anything but
    text, which the browser's twin would write out differently."""
    return trim_field(value) if isinstance(value, str) else ""


def _variation(raw: dict):
    from .procurement import Variation

    rate = _num(raw.get("rate_usd"), None)
    return Variation(ref=_text(raw.get("ref")), date=_text(raw.get("date")), code=trim_field(raw.get("code")),
                     quantity_delta=_num(raw.get("quantity_delta"), None) or 0.0, rate_usd=rate,
                     reason=_text(raw.get("reason")), authorised_by=_name(raw.get("authorised_by")),
                     item=_text(raw.get("item")), unit=_text(raw.get("unit")))


def _variation_figures(procurement) -> tuple[int, int, float] | None:
    """The signed and unsigned variation orders on a contract and the value
    the signed ones add to its sum, as the payment certificate values them,
    or None where no contract is recorded."""
    from .procurement import Contract, ContractLine, certify

    if not isinstance(procurement, dict):
        return None
    lines = procurement.get("lines")
    if not isinstance(lines, list) or not lines:
        return None
    contract = Contract(ref="", lines=[
        ContractLine(code=trim_field(line.get("code")), item=_text(line.get("item")), unit=_text(line.get("unit")),
                     quantity=_num(line.get("quantity"), None) or 0.0,
                     rate_usd=_num(line.get("rate_usd"), None) or 0.0)
        for line in lines if isinstance(line, dict)])
    raws = procurement.get("variations")
    variations = [_variation(v) for v in raws if isinstance(v, dict) and trim_field(v.get("code"))] \
        if isinstance(raws, list) else []
    certificate = certify(contract, [], number=1, date="", variations=variations)
    signed = sum(1 for v in variations if v.authorised_by)
    return signed, len(variations) - signed, certificate.variation_usd


def works_record(site, log, analysis, ledger, answers=None, metres=None, procurement=None,
                 config: Config | None = None, items=None) -> dict | None:
    """What one project records of its contractor's work, or None where it
    records nothing a scorecard reads.

    ``site`` is the project's site details (its contractor, community and
    district), ``log`` its drilling log and ``analysis`` its pumping test
    (each None where it has none), and ``ledger`` its ledger of predictions
    and outcomes. ``answers`` are the supervision checklist's answers by item
    id (``yes``, ``no``, ``na`` or ``pending``), ``metres`` the drilled
    metres reconciliation's ``logged_m`` and ``claimed_m`` as typed, and
    ``procurement`` the contract on the Procurement page: its ``lines`` (code,
    item, unit, quantity, rate_usd), its ``variations`` (ref, date, code,
    quantity_delta, rate_usd, reason, authorised_by) and its completion date
    ``due``, or None where none was awarded. ``items`` are the checklist's
    items, the bundled checklist where None.

    The borehole is the project's completion, the outcome
    :func:`groundwater.ledger.completion_outcome` works out from the log, or
    where the project holds no log, the outcome its ledger kept. Its
    forecast is the chance of success recorded at the point it was drilled
    at, where that was recorded before drilling. Its identifier is that
    point's, so a file saved before this record and a later copy of it count
    the borehole once; a borehole paired with no point is identified by its
    reference, position and place, and by the identity of the project's
    ledger where it has one, as a ledger's points are.
    """
    config = config or Config()
    contractor = _name(getattr(site, "contractor", ""))
    outcome = completion_outcome(log, analysis, config, contractor=contractor)
    held = attach_outcome(ledger, outcome, config)
    drilled = next((entry for entry in held["entries"] if entry["outcome"] is not None), None)
    if outcome is None and drilled is not None:
        # a file whose log was not carried with it keeps what its ledger recorded
        outcome = drilled["outcome"]
    forecast = None
    if drilled is not None and drilled["before_outcome"] and drilled["prediction"]["odds"] is not None:
        p = drilled["prediction"]["odds"]["probability"]
        forecast = p if p is not None and 0.0 <= p <= 1.0 else None

    answers = answers if isinstance(answers, dict) else {}
    checklist: dict[str, dict] = {}
    for item in load_checklists() if items is None else items:
        status = answers.get(item.item_id)
        if status not in ("yes", "no"):
            continue
        stage = checklist.setdefault(item.checklist, {"answered": 0, "failed": []})
        stage["answered"] += 1
        if status == "no":
            stage["failed"].append(item.item_id)

    logged = _metres(metres.get("logged_m")) if isinstance(metres, dict) else None
    claimed = _metres(metres.get("claimed_m")) if isinstance(metres, dict) else None
    figures = _variation_figures(procurement)
    if outcome is None and not checklist and logged is None and claimed is None and figures is None:
        return None
    community = str(getattr(site, "community", "") or "")
    district = str(getattr(site, "district", "") or "")
    ref = outcome["borehole_ref"] if outcome is not None else ""
    if drilled is not None:
        rid = drilled["id"]
    else:
        at = outcome or {}
        rid = point_id("borehole " + ref, at.get("easting"), at.get("northing"), at.get("utm_zone"),
                       community, district, held["project_id"] or "")
    return {
        "borehole_ref": ref,
        "checklist": dict(sorted(checklist.items())),
        "claimed_m": claimed,
        "community": community,
        "completion_date": outcome["completion_date"] if outcome is not None else "",
        "completion_due": _due(procurement.get("due")) if isinstance(procurement, dict) and figures is not None
        else "",
        "contract": figures is not None,
        "contractor": outcome["contractor"] if outcome is not None else contractor,
        "district": district,
        "drilled": outcome is not None,
        "forecast": forecast,
        "id": rid,
        "logged_m": logged,
        "success": outcome["success"] if outcome is not None else None,
        "success_basis": outcome["success_basis"] if outcome is not None else None,
        "variation_usd": _num(figures[2], 2) if figures is not None else None,
        "variations_signed": figures[0] if figures is not None else None,
        "variations_unsigned": figures[1] if figures is not None else None,
    }


def _count(value) -> int | None:
    """A whole count not below nought, or None."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    x = float(value)
    return int(x) if math.isfinite(x) and x.is_integer() and x >= 0 else None


def clean_works(raw) -> dict | None:
    """A works record as read from a file, in the shape :func:`works_record`
    writes, or None where it is not one (not a mapping, or no identifier).

    A hand-edited record is cleaned rather than refused: a field of the wrong
    kind is blank, a checklist stage that fails more items than it answered
    is left out, and counts that do not go with a contract are dropped.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        return None
    checklist: dict[str, dict] = {}
    stages = raw.get("checklist")
    for stage, held in (stages.items() if isinstance(stages, dict) else ()):
        if not isinstance(stage, str) or not _STAGE_KEY.fullmatch(stage) or not isinstance(held, dict):
            continue
        answered = _count(held.get("answered"))
        listed = held.get("failed")
        failed = list(dict.fromkeys(f for f in listed if isinstance(f, str) and f)) \
            if isinstance(listed, list) else []
        if answered is None or answered == 0 or len(failed) > answered:
            continue
        checklist[stage] = {"answered": answered, "failed": failed}
    contract = raw.get("contract") is True
    success = raw.get("success") if isinstance(raw.get("success"), bool) else None
    basis = raw.get("success_basis") if success is not None and raw.get("success_basis") in _BASES else None
    forecast = _num(raw.get("forecast"), 3)
    signed, unsigned = _count(raw.get("variations_signed")), _count(raw.get("variations_unsigned"))
    value = _num(raw.get("variation_usd"), 2)
    if not contract or None in (signed, unsigned, value):
        contract, signed, unsigned, value = False, None, None, None
    return {
        "borehole_ref": _text(raw.get("borehole_ref")),
        "checklist": dict(sorted(checklist.items())),
        "claimed_m": _metres(raw.get("claimed_m")),
        "community": _text(raw.get("community")),
        "completion_date": _text(raw.get("completion_date")),
        "completion_due": _due(raw.get("completion_due")) if contract else "",
        "contract": contract,
        "contractor": _name(raw.get("contractor")),
        "district": _text(raw.get("district")),
        "drilled": raw.get("drilled") is True,
        "forecast": forecast if forecast is not None and 0.0 <= forecast <= 1.0 else None,
        "id": raw["id"],
        "logged_m": _metres(raw.get("logged_m")),
        "success": success,
        "success_basis": basis,
        "variation_usd": value,
        "variations_signed": signed,
        "variations_unsigned": unsigned,
    }


# ----------------------------------------------------------------- pooling

def _ledger_row(entry: dict) -> dict:
    """A borehole a file saved before the works record holds in its ledger
    alone: its contractor, outcome and forecast, and nothing else recorded."""
    outcome = entry["outcome"]
    odds = entry["prediction"]["odds"]
    p = odds["probability"] if odds is not None and entry["before_outcome"] else None
    return {
        "borehole_ref": outcome["borehole_ref"], "checklist": {}, "claimed_m": None,
        "community": entry["point"]["community"], "completion_date": outcome["completion_date"],
        "completion_due": "", "contract": False, "contractor": outcome["contractor"],
        "district": entry["point"]["district"], "drilled": True,
        "forecast": p if p is not None and 0.0 <= p <= 1.0 else None, "id": entry["id"], "logged_m": None,
        "success": outcome["success"], "success_basis": outcome["success_basis"] if outcome["success"] is not None
        else None, "variation_usd": None, "variations_signed": None, "variations_unsigned": None,
        "project": entry["project"], "source": "ledger",
    }


def _recorded(row: dict) -> int:
    """How many of the scorecard's measures a borehole's record holds."""
    return sum((row["logged_m"] is not None and row["claimed_m"] is not None, bool(row["checklist"]),
                row["contract"], bool(row["completion_due"]), row["success"] is not None,
                row["forecast"] is not None))


def _richer(row: dict, have: dict) -> bool:
    return (row["source"] == "works", _recorded(row)) > (have["source"] == "works", _recorded(have))


def scorecard_boreholes(files) -> list[dict]:
    """The boreholes drilled across a portfolio's project files, each once.

    ``files`` are (project label, works record, ledger) for each file, as the
    Portfolio page reads them. A file with a works record gives the borehole
    it records as drilled; a file without one (saved before the record
    existed) gives the drilled points of its ledger, pooled as the ledger
    pools them. A borehole met twice (two copies of one file) is kept once,
    the copy from a works record that records the most. Each carries the
    label of its file as ``project`` and where it came from as ``source``
    (``works`` or ``ledger``), in the order first met.
    """
    kept: dict[str, dict] = {}
    older = []

    def keep(row: dict) -> None:
        have = kept.get(row["id"])
        if have is None or _richer(row, have):
            kept[row["id"]] = row

    for label, works, ledger in files:
        record = clean_works(works)
        if record is None:
            older.append((label, ledger))
        elif record["drilled"]:
            keep(dict(record, project=str(label or ""), source="works"))
    for entry in pool_ledgers(older):
        if entry["outcome"] is not None:
            keep(_ledger_row(entry))
    return list(kept.values())


# -------------------------------------------------------------- scorecards

def _round(value: float, digits: int) -> float:
    return round(float(value), digits)


def _minimum(config: Config) -> int:
    """The fewest forecast boreholes a contractor is judged and ranked on:
    ``ledger.scorecard_min_boreholes``, and never fewer than one, since a
    contractor with no forecast has nothing to be ranked by."""
    return max(1, int(config.ledger.scorecard_min_boreholes))


def _stages(config: Config) -> list[str]:
    """The checklist stages whose items are the contractor's acceptance
    checks (``ledger.scorecard_stages``), each once, so a stage named twice
    does not count its failures twice."""
    return list(dict.fromkeys(str(stage) for stage in config.ledger.scorecard_stages or ()))


def _check_order(items) -> dict[str, int]:
    return {item.item_id: k for k, item in enumerate(items)}


def _card(name: str, rows: list[dict], stages: list[str], minimum: int, order: dict[str, int]) -> dict:
    """One contractor's scorecard over its boreholes."""
    pairs = [(r["logged_m"], r["claimed_m"]) for r in rows if r["logged_m"] is not None and r["claimed_m"] is not None]
    logged, claimed = sum_in_order(p[0] for p in pairs), sum_in_order(p[1] for p in pairs)
    metres = {
        "n": len(pairs),
        "logged_m": _round(logged, 2) if pairs else None,
        "claimed_m": _round(claimed, 2) if pairs else None,
        "over_m": _round(claimed - logged, 2) if pairs else None,
        "beyond": sum(1 for lm, cm in pairs if not metres_reconciliation_check(lm, cm).passed),
    }

    checked = [r for r in rows if any(stage in r["checklist"] for stage in stages)]
    failures: dict[tuple[str, str], int] = {}
    failed_total = with_failures = 0
    for r in checked:
        failed = [(stage, item) for stage in stages if stage in r["checklist"]
                  for item in r["checklist"][stage]["failed"]]
        failed_total += len(failed)
        with_failures += 1 if failed else 0
        for key in failed:
            failures[key] = failures.get(key, 0) + 1
    listed = sorted(failures, key=lambda key: (stages.index(key[0]), order.get(key[1], len(order)),
                                               _code_points(key[1])))
    checks = {"n": len(checked), "with_failures": with_failures, "failed": failed_total,
              "items": [[stage, item, failures[(stage, item)]] for stage, item in listed]}

    contracts = [r for r in rows if r["contract"]]
    variations = {
        "n": len(contracts),
        "signed": sum(r["variations_signed"] for r in contracts) if contracts else None,
        "unsigned": sum(r["variations_unsigned"] for r in contracts) if contracts else None,
        "value_usd": _round(sum_in_order(r["variation_usd"] for r in contracts), 2) if contracts else None,
    }

    timed, unread = [], 0
    for r in rows:
        if not r["completion_due"]:
            continue
        days = _days_late(r["completion_due"], r["completion_date"])
        if days is None:
            unread += 1
        else:
            timed.append(days)
    late = [d for d in timed if d > 0]
    time = {"n": len(timed), "late": len(late), "days_late": sum(late) if timed else None,
            "most_days": max(late) if late else None, "unread": unread}

    known = [r for r in rows if r["success"] is not None]
    forecast = [r for r in known if r["forecast"] is not None]
    expected = sum_in_order(1.0 - r["forecast"] for r in forecast)
    found = sum(1 for r in forecast if r["success"] is False)
    span = list(binomial_range(len(forecast), expected / len(forecast))) if forecast else None
    if len(forecast) < minimum or span is None:
        verdict = "too_few"
    elif found > span[1]:
        verdict = "more"
    elif found < span[0]:
        verdict = "fewer"
    else:
        verdict = "within"
    dry = {"known": len(known), "dry": sum(1 for r in known if r["success"] is False),
           "forecast": len(forecast), "forecast_dry": found,
           "expected": _round(expected, 2) if forecast else None, "range": span, "verdict": verdict}
    ranked = bool(name) and len(forecast) >= minimum
    return {
        "contractor": name or phrase("scorecards.no_contractor"),
        "recorded": bool(name),
        "boreholes": len(rows),
        "from_ledger": sum(1 for r in rows if r["source"] == "ledger"),
        "metres": metres,
        "checks": checks,
        "variations": variations,
        "time": time,
        "dry": dry,
        "measure": _round((found - expected) / len(forecast), 3) if ranked else None,
        "rank": None,
        "unranked": None if ranked else ("too_few" if name else "no_contractor"),
    }


def contractor_scorecards(boreholes: list[dict], config: Config | None = None, items=None) -> list[dict]:
    """A scorecard for each contractor of :func:`scorecard_boreholes`.

    Each holds the contractor's name (``recorded`` False for the boreholes
    that name none, listed together), its boreholes, and its ``metres``,
    ``checks``, ``variations``, ``time`` and ``dry`` figures, each with the
    number of boreholes it rests on (``n``, or ``known`` and ``forecast``
    for the dry holes) and None where none records it. ``measure`` is the
    ranking measure, the dry holes found on the forecast boreholes less the
    number expected, for each of them, given only on at least
    ``ledger.scorecard_min_boreholes`` of them; ``rank`` is 1 for the
    fewest, a tie sharing a rank, and ``unranked`` says why a contractor has
    none (``too_few`` or ``no_contractor``). The ranked come first, by rank
    and then by name letter by letter; then the rest, the most boreholes
    first; and the boreholes naming no contractor last.
    """
    config = config or Config()
    minimum = _minimum(config)
    stages = _stages(config)
    order = _check_order(load_checklists() if items is None else items)
    groups: dict[str, list[dict]] = {}
    for row in boreholes:
        groups.setdefault(_name(row["contractor"]), []).append(row)
    cards = [_card(name, rows, stages, minimum, order) for name, rows in groups.items()]
    measures = [card["measure"] for card in cards if card["measure"] is not None]
    for card in cards:
        if card["measure"] is not None:
            card["rank"] = 1 + sum(1 for m in measures if m < card["measure"])
    cards.sort(key=lambda c: (c["rank"] is None, not c["recorded"], c["rank"] or 0,
                              0 if c["rank"] is not None else -c["boreholes"], _code_points(c["contractor"])))
    return cards


# ------------------------------------------------------------------ report

def _section(key: str, heading: str) -> dict:
    return {"key": key, "heading": heading, "paragraphs": [], "tables": [], "figures": [], "bullets": []}


def _signed_g(value: float) -> str:
    """A difference in metres with its sign: "+4", "-2.5", "0"."""
    if value == 0:
        return "0"
    return ("+" if value > 0 else "") + format(value, "g")


def _signed_money(value: float) -> str:
    """A sum of money with its sign outside the currency, as the payment
    certificate writes it: "+$1,360", "-$200"."""
    return ("+" if value >= 0 else "-") + f"${abs(value):,.0f}"


def _metres_cell(m: dict) -> str:
    if not m["n"]:
        return phrase("scorecards.not_recorded")
    text = phrase("scorecards.metres_cell", over=_signed_g(m["over_m"]), n=m["n"], claimed=m["claimed_m"],
                  logged=m["logged_m"])
    if m["beyond"]:
        text += "; " + phrase("scorecards.metres_beyond", k=m["beyond"], tolerance=METRES_TOLERANCE_M)
    return text


def _checks_cell(c: dict) -> str:
    if not c["n"]:
        return phrase("scorecards.not_recorded")
    if not c["failed"]:
        return phrase("scorecards.checks_cell_none", n=c["n"])
    return phrase("scorecards.checks_cell", failed=c["failed"], k=c["with_failures"], n=c["n"])


def _variations_cell(v: dict) -> str:
    if not v["n"]:
        return phrase("scorecards.not_recorded")
    if v["signed"]:
        text = phrase("scorecards.variations_cell", signed=v["signed"], value=_signed_money(v["value_usd"]),
                      n=v["n"])
    else:
        text = phrase("scorecards.variations_cell_none", n=v["n"])
    if v["unsigned"]:
        text += "; " + phrase("scorecards.variations_unsigned", k=v["unsigned"])
    return text


def _time_cell(t: dict) -> str:
    parts = []
    if t["n"]:
        parts.append(phrase("scorecards.time_cell", late=t["late"], n=t["n"], days=t["days_late"],
                            most=t["most_days"]) if t["late"]
                     else phrase("scorecards.time_cell_none", n=t["n"]))
    if t["unread"]:
        parts.append(phrase("scorecards.time_unread", k=t["unread"]))
    return "; ".join(parts) if parts else phrase("scorecards.not_recorded")


def _dry_cell(d: dict) -> str:
    if not d["known"]:
        return phrase("scorecards.dry_cell_unknown")
    text = phrase("scorecards.dry_cell", dry=d["dry"], known=d["known"])
    if d["forecast"]:
        text += "; " + phrase("scorecards.dry_forecast", fdry=d["forecast_dry"], f=d["forecast"],
                              expected=d["expected"], low=d["range"][0], high=d["range"][1])
    return text


def _rank_cell(card: dict, minimum: int) -> str:
    if card["rank"] is not None:
        return str(card["rank"])
    if card["unranked"] == "no_contractor":
        return phrase("scorecards.rank_no_contractor")
    return phrase("scorecards.rank_too_few", f=card["dry"]["forecast"], minimum=minimum)


def _stages_text(stages: list[str]) -> str:
    """The stages' titles in a sentence, in lower case: "mobilisation,
    drilling, and design and installation"."""
    titles = [stage_title(stage).lower() for stage in stages]
    if len(titles) < 2:
        return "".join(titles)
    if len(titles) == 2:
        return titles[0] + " and " + titles[1]
    # the last after a comma, as a title can hold an "and" of its own
    return ", ".join(titles[:-1]) + ", and " + titles[-1]


def scorecard_content(files, issued_on: str = "", config: Config | None = None) -> dict:
    """Everything the contractor scorecards say, as plain data.

    ``files`` are (project label, works record, ledger) for each project
    file on the Portfolio page and ``issued_on`` the date the report is
    issued, as the app writes it ("" to leave it off). Both engines return
    the same structure, which the two document writers lay out as the
    calibration report is laid out: a title and subtitle, the cover's rows,
    the summary, and the sections, each with its paragraphs, tables and
    bullets, then the references. The section keyed ``cards`` holds the
    scorecards' table and ``checks`` the checks that failed; both apps show
    them on the page.
    """
    config = config or Config()
    files = list(files)
    minimum = _minimum(config)
    stages = _stages(config)
    items = load_checklists()
    boreholes = scorecard_boreholes(files)
    cards = contractor_scorecards(boreholes, config, items)
    named = [card for card in cards if card["recorded"]]
    rows = [[phrase("scorecards.row_projects"), str(len(files))],
            [phrase("scorecards.row_boreholes"), str(len(boreholes))],
            [phrase("scorecards.row_contractors"), str(len(named))]]
    issued = _name(issued_on)
    if issued:
        rows.append([phrase("scorecards.row_issued"), issued])

    summary = []
    if not boreholes:
        summary.append(phrase("scorecards.summary_none"))
    else:
        if named:
            summary.append(phrase("scorecards.summary_counts", boreholes=len(boreholes), contractors=len(named),
                                  projects=len(files)))
        else:
            summary.append(phrase("scorecards.summary_counts_unnamed", boreholes=len(boreholes),
                                  projects=len(files)))
        unnamed = sum(card["boreholes"] for card in cards if not card["recorded"])
        if unnamed:
            summary.append(phrase("scorecards.summary_unnamed", n=unnamed))
        older = sum(card["from_ledger"] for card in cards)
        if older:
            summary.append(phrase("scorecards.summary_ledger_only", n=older))
        ranked = sum(1 for card in cards if card["rank"] is not None)
        summary.append(phrase("scorecards.summary_ranked", ranked=ranked, minimum=minimum) if ranked
                       else phrase("scorecards.summary_unranked", minimum=minimum))
        summary.append(phrase("scorecards.summary_n"))

    sections = []
    if boreholes:
        table = _section("cards", phrase("scorecards.cards_heading"))
        table["paragraphs"].append(phrase("scorecards.cards_intro"))
        table["tables"].append({
            "header": [phrase("scorecards.col_contractor"), phrase("scorecards.col_boreholes"),
                       phrase("scorecards.col_metres"), phrase("scorecards.col_checks"),
                       phrase("scorecards.col_variations"), phrase("scorecards.col_time"),
                       phrase("scorecards.col_dry"), phrase("scorecards.col_rank")],
            "rows": [[card["contractor"], str(card["boreholes"]), _metres_cell(card["metres"]),
                      _checks_cell(card["checks"]), _variations_cell(card["variations"]), _time_cell(card["time"]),
                      _dry_cell(card["dry"]), _rank_cell(card, minimum)] for card in cards],
            "caption": phrase("scorecards.cards_table"),
        })
        sections.append(table)

        checks = _section("checks", phrase("scorecards.checks_heading"))
        checks["paragraphs"].append(phrase("scorecards.checks_intro", stages=_stages_text(stages)) if stages
                                    else phrase("scorecards.checks_no_stages"))
        texts = {item.item_id: item.text for item in items}
        failed = [[card["contractor"], stage_title(stage), texts.get(item, item), str(count)]
                  for card in cards for stage, item, count in card["checks"]["items"]]
        if failed:
            checks["tables"].append({
                "header": [phrase("scorecards.col_contractor"), phrase("scorecards.col_stage"),
                           phrase("scorecards.col_check"), phrase("scorecards.col_failed_on")],
                "rows": failed,
                "caption": phrase("scorecards.checks_table"),
            })
        elif any(card["checks"]["n"] for card in cards):
            checks["paragraphs"].append(phrase("scorecards.checks_none"))
        elif stages:
            checks["paragraphs"].append(phrase("scorecards.checks_unchecked"))
        sections.append(checks)

        dry = _section("dry", phrase("scorecards.dry_heading"))
        dry["paragraphs"] += [phrase("scorecards.dry_intro", rate=float(config.odds.success_yield_m3_per_h)),
                              phrase("scorecards.dry_range", minimum=minimum),
                              phrase("scorecards.dry_rank", minimum=minimum)]
        verdicts = phrase_table("scorecards.dry_verdict")
        none = phrase("scorecards.not_recorded")
        dry["tables"].append({
            "header": [phrase("scorecards.col_contractor"), phrase("scorecards.col_known"),
                       phrase("scorecards.col_dry_found"), phrase("scorecards.col_forecast"),
                       phrase("scorecards.col_dry_forecast"), phrase("scorecards.col_expected"),
                       phrase("scorecards.col_range"), phrase("scorecards.col_verdict")],
            "rows": [[card["contractor"], str(d["known"]), str(d["dry"]), str(d["forecast"]),
                      str(d["forecast_dry"]) if d["forecast"] else none,
                      format(d["expected"], "g") if d["forecast"] else none,
                      phrase("scorecards.dry_range_cell", low=d["range"][0], high=d["range"][1])
                      if d["forecast"] else none,
                      verdicts[d["verdict"]]]
                     for card in cards for d in [card["dry"]]],
            "caption": phrase("scorecards.dry_table"),
        })
        sections.append(dry)

    method = _section("method", phrase("scorecards.method_heading"))
    method["bullets"] += [
        phrase("scorecards.method_boreholes"),
        phrase("scorecards.method_metres", tolerance=METRES_TOLERANCE_M),
        phrase("scorecards.method_checks", stages=_stages_text(stages)) if stages
        else phrase("scorecards.checks_no_stages"),
        phrase("scorecards.method_variations"),
        phrase("scorecards.method_time"),
        phrase("scorecards.method_dry"),
        phrase("scorecards.method_names"),
        phrase("scorecards.method_minimum", minimum=minimum),
        phrase("scorecards.method_report"),
    ]
    sections.append(method)
    return {
        "title": phrase("scorecards.title"),
        "subtitle": phrase("scorecards.subtitle"),
        "rows": rows,
        "summary": summary,
        "sections": sections,
        "references": references_for("scorecards"),
    }

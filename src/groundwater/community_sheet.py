"""The community handover sheet: what one page tells the people who keep the
borehole (PLAN.md step 9.1).

The handover report is written for the client and the district water office.
This is the page for the community: how much water the borehole gives, whether
it is safe to drink, who to call, how to report a fault, and what has to be
kept away from it. :func:`community_sheet_content` works out everything the
page says, as plain data, in a form both engines build the same way
(``communitySheet`` in ``docs/js/gwt-core.js`` is its port, held to it by the
parity suite); ``reporting/community_sheet.py`` and ``GWT.docx.communitySheet``
lay it out.

Nothing here is new hydrogeology. Every figure is one the toolkit already
holds, put in words a person who was not at the pumping test can use:

- **How much water.** The lower end of the yield recommendation's range
  (:class:`~groundwater.hydraulics.analysis.YieldRecommendation`), or its
  safe yield where it gives no range, as litres in an hour and as jerrycans
  of 20 litres. With the hours the pump is used each day, which whoever
  builds the sheet enters, the same as an amount for a day. Every rounding
  is downward: an amount a community plans by is better a little low than a
  little high. An indicative yield is called a first estimate, and no yield
  at all is said as "not measured yet" rather than left off.
- **Safe to drink.** The verdict of the water quality assessment
  (:attr:`~groundwater.quality.assess.WaterQualityAssessment.verdict_state`),
  which fails closed. Only a pass, or a pass with aesthetic findings, is told
  as safe; no assessment is told as not known, and to treat the water.
- **Who to call.** The committee entered on the Handover page, then lines to
  write on.
- **Reporting a fault.** The borehole's identifier, as on its plate, and the
  plate's own link where the programme has set a report address
  (:func:`~groundwater.registry.report_link`). No telephone number is
  printed for reports by SMS, because none is known here (QUESTIONS.md).
- **What to keep away.** The rows of ``data/site_separation_distances.csv``
  a community can act on, in its own words, nearest first.

What the sheet could not say, and why, comes back in ``notes`` for whoever is
building it. Those are shown beside the button and never printed.
"""

from __future__ import annotations

import math
from typing import Any

from .config import Config
from .models import SiteMetadata
from .registry import report_link, trim_field
from .supervision.checklists import load_separation_distances
from .text import phrase, phrase_table

__all__ = ["JERRYCAN_L", "community_sheet_content", "round_down"]

#: The jerrycan water is carried in, in litres.
JERRYCAN_L = 20

#: How many lines the sheet leaves to write a name and a number on when no
#: committee member was entered.
BLANK_CONTACTS = 3


def round_down(value: float) -> int:
    """``value`` as a whole number rounded down to two significant figures.

    Down, never to nearest: 1,790 litres is printed as 1,700. The small
    allowance is for arithmetic that lands a hair under a whole number
    (0.57 x 1000 is 569.9999999999999), which is that number.
    """
    whole = math.floor(value + 1e-9)
    if whole < 100:
        return max(whole, 0)
    step = 10 ** (len(str(whole)) - 2)
    return whole // step * step


def _hours(hours_per_day: Any) -> float | None:
    """The hours of use in a day, where they are a time of day's worth."""
    if isinstance(hours_per_day, bool) or not isinstance(hours_per_day, (int, float)):
        return None
    hours = float(hours_per_day)
    return hours if math.isfinite(hours) and 0 < hours <= 24 else None


def _water(analysis: Any, hours: float | None, notes: list[str]) -> dict:
    table = phrase_table("community_sheet.builder_notes")
    water: dict[str, Any] = {
        "heading": phrase("community_sheet.water_heading"), "state": "none",
        "litres_per_hour": None, "jerrycans_per_hour": None, "hours_per_day": None,
        "litres_per_day": None, "jerrycans_per_day": None,
        "headline": phrase("community_sheet.water_none"), "lines": [],
    }
    rec = getattr(analysis, "yield_recommendation", None)
    if rec is None or rec.safe_yield_m3_per_h is None:
        notes.append(table["no_test" if analysis is None else "pending"])
        return water
    low = getattr(rec, "safe_yield_low_m3_per_h", None)
    rate = low if low is not None else rec.safe_yield_m3_per_h
    # the recommendation's own word for a short test, or one inside its
    # casing-storage time, or one no method fitted to standard
    indicative = getattr(rec, "confidence", "established") == "indicative"
    per_hour = round_down(rate * 1000.0)
    water["state"] = "first_estimate" if indicative else "measured"
    water["litres_per_hour"] = per_hour
    water["jerrycans_per_hour"] = per_hour // JERRYCAN_L
    if per_hour <= 0:
        water["headline"] = phrase("community_sheet.water_very_little")
    elif hours is None:
        notes.append(table["no_hours"])
        if water["jerrycans_per_hour"] >= 1:
            water["headline"] = phrase("community_sheet.water_hour",
                                       cans=water["jerrycans_per_hour"])
            water["lines"].append(phrase("community_sheet.water_hour_detail",
                                         litres=per_hour, can=JERRYCAN_L))
        else:
            water["headline"] = phrase("community_sheet.water_litres_hour", litres=per_hour)
    else:
        per_day = round_down(per_hour * hours)
        unit = phrase_table("community_sheet.hour_words")["one" if hours == 1 else "other"]
        water["hours_per_day"] = hours
        water["litres_per_day"] = per_day
        water["jerrycans_per_day"] = per_day // JERRYCAN_L
        if water["jerrycans_per_day"] >= 1:
            water["headline"] = phrase("community_sheet.water_day",
                                       cans=water["jerrycans_per_day"])
            water["lines"].append(phrase("community_sheet.water_day_detail", litres=per_day,
                                         hours=hours, unit=unit, can=JERRYCAN_L))
        else:
            water["headline"] = phrase("community_sheet.water_litres_day", litres=per_day,
                                       hours=hours, unit=unit)
    if indicative:
        notes.append(table["first_estimate"])
        water["lines"].append(phrase("community_sheet.water_first_estimate"))
    else:
        water["lines"].append(phrase("community_sheet.water_tested"))
    if per_hour > 0:
        water["lines"].append(phrase("community_sheet.water_shortage"))
    return water


def _quality(quality: Any, notes: list[str]) -> dict:
    answers = phrase_table("community_sheet.quality")
    state = getattr(quality, "verdict_state", None) if quality is not None else None
    if state not in answers or state == "none":
        if quality is None:
            notes.append(phrase_table("community_sheet.builder_notes")["no_quality"])
            state = "none"
        else:
            # a verdict this sheet has no words for is not told as safe
            state = "indeterminate"
    lines: list[str] = []
    if state == "health_fail":
        names = [row.parameter for row in quality.health_exceedances]
        if names:
            lines.append(phrase("community_sheet.quality_found", names=", ".join(names)))
        lines.append(phrase("community_sheet.quality_ask"))
    return {"heading": phrase("community_sheet.quality_heading"), "state": state,
            "headline": answers[state], "lines": lines}


def _contacts(committee: Any, notes: list[str]) -> dict:
    columns = phrase_table("community_sheet.contacts_columns")
    rows: list[list[str]] = []
    for member in committee or []:
        get = member.get if isinstance(member, dict) else lambda key, m=member: getattr(m, key, "")
        role, name = trim_field(get("role") or ""), trim_field(get("name") or "")
        phone = trim_field(get("phone") or get("contact") or "")
        if name or phone:
            rows.append([role, name, phone])
    if not rows:
        notes.append(phrase_table("community_sheet.builder_notes")["no_committee"])
        rows = [["", "", ""] for _ in range(BLANK_CONTACTS)]
    rows += [[role, "", ""] for role in phrase_table("community_sheet.contacts_write_in").values()]
    return {"heading": phrase("community_sheet.contacts_heading"),
            "header": [columns["role"], columns["name"], columns["phone"]], "rows": rows}


def _report(asset_id: str, report_url: str, notes: list[str]) -> dict:
    table = phrase_table("community_sheet.builder_notes")
    lines = [phrase("community_sheet.report_tell")]
    payload = caption = ""
    if not asset_id:
        notes.append(table["no_identifier"])
    else:
        lines.append(phrase("community_sheet.report_number", id=asset_id))
        # an address the registry refuses stops the sheet, as it stops the
        # plate, rather than being printed
        payload = report_link(asset_id, report_url)
        if payload:
            lines.append(phrase("community_sheet.report_scan"))
            caption = phrase("community_sheet.report_caption", id=asset_id)
        else:
            notes.append(table["no_address"])
    return {"heading": phrase("community_sheet.report_heading"), "identifier": asset_id,
            "lines": lines, "payload": payload, "caption": caption}


def _keep_away() -> dict:
    words = phrase_table("community_sheet.keep_structures")
    kept = [(row.min_distance_m, words[row.structure]) for row in load_separation_distances()
            if row.structure in words]
    # nearest first; the table's own order among things at one distance
    kept.sort(key=lambda item: item[0])
    rings: list[dict] = []
    for distance, what in kept:
        if rings and rings[-1]["distance_m"] == distance:
            rings[-1]["what"].append(what)
        else:
            rings.append({"distance_m": distance, "what": [what],
                          "label": phrase("community_sheet.keep_metres", distance=distance)})
    return {
        "heading": phrase("community_sheet.keep_heading"),
        "lines": [phrase("community_sheet.keep_line", what=what, distance=distance)
                  for distance, what in kept],
        "rings": rings,
        "centre": phrase("community_sheet.keep_centre"),
        "caption": phrase("community_sheet.keep_caption"),
    }


def community_sheet_content(site: SiteMetadata, *, analysis: Any = None, quality: Any = None,
                            committee: Any = None, asset_id: str = "",
                            hours_per_day: float | None = None,
                            config: Config | None = None) -> dict:
    """Everything the community handover sheet says, as plain data.

    ``analysis`` is the pumping test analysis and ``quality`` the water
    quality assessment, either of which may be absent; ``committee`` the
    members entered at handover (objects or mappings with a role, a name and
    a phone or contact); ``asset_id`` the borehole's identifier as its plate
    carries it; ``hours_per_day`` the hours the pump is used each day. The
    report address is the programme's (``config.service.report_url``).

    Raises ValueError for a report address the registry would not print on a
    plate, with the registry's reason.
    """
    config = config or Config()
    notes: list[str] = []
    place = trim_field(site.community or "")
    identifier = trim_field(asset_id or "")
    content = {
        "title": (phrase("community_sheet.title", place=place) if place
                  else phrase("community_sheet.title_unnamed")),
        "water": _water(analysis, _hours(hours_per_day), notes),
        "quality": _quality(quality, notes),
        "contacts": _contacts(committee, notes),
        "report": _report(identifier, config.service.report_url, notes),
        "keep_away": _keep_away(),
    }
    notes.append(phrase_table("community_sheet.builder_notes")["english_only"])
    content["notes"] = notes
    return content

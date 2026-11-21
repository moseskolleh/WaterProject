"""The community handover sheet (PLAN.md step 9.1): the "community_sheet"
entry of ``reference.json``.
"""

from __future__ import annotations

from groundwater.config import Config
from groundwater.models import SiteMetadata

from .common import _ns


# Everything the sheet says is built from results the other sections already
# hold the two engines to (the yield recommendation, the water quality
# verdict), so here both are handed the same results, as the dicts the
# browser holds and as namespaces Python reads attributes from, and every
# word and number of the content is compared.

def _yield(safe, low=None, confidence="established") -> dict:
    return {"yield_recommendation": {"safe_yield_m3_per_h": safe,
                                     "safe_yield_low_m3_per_h": low,
                                     "confidence": confidence}}


def _verdict(state, *parameters, national=()) -> dict:
    return {"verdict_state": state,
            "health_exceedances": [{"parameter": name} for name in parameters],
            "national_exceedances": [{"parameter": name} for name in national]}


COMMITTEE = [
    {"role": "Chairperson", "name": "  Aminata   Kamara ", "contact": "076 000 000"},
    {"role": "Caretaker", "name": "Sorie Conteh", "phone": ""},
    # a role nobody was named for is a line nobody can call
    {"role": "Treasurer", "name": " ", "contact": ""},
    {"role": "", "name": "", "contact": "+232 77 111 222"},
]

#: Translations of the sheet made up for the purpose (PLAN.md step 9.2; none
#: is bundled, and every word here is invented): a whole one, one that has a
#: sentence and part of a table, one with nothing in it, and one that may
#: not be offered.
TRANSLATIONS = {
    "zz": {
        "language": {"name": "Zedish", "translated_by": "A. Translator",
                     "checked_by": "B. Checker"},
        # Nonsense syllables throughout, from one small stock (zub, glorp,
        # wug, frim, blop, tiv, kwem, sarn, dru, plim, vosh), with the two
        # letters a real translation would bring. No word is taken from, or
        # made to look like, a word of any language.
        "text": {"community_sheet": {
            "title": "Zɛdo glorp {place}",
            "title_unnamed": "Zɛdo glorp",
            "example": "Frimo wug zub blop. Tiv glorp kwem zub.",
            "water_heading": "Wug zub frim",
            "water_day": "Zub {cans:num} {cans:plural:glorp|glorpɔz} frim wug sarn.",
            "water_day_detail": "Frimo {litres:num} dru, zub plim wug {hours:g} "
                                "{unit} wug sarn. Glorp zub {can:g} dru.",
            "water_hour": "Zub {cans:num} {cans:plural:glorp|glorpɔz} frim wug ɔmba.",
            "water_hour_detail": "Frimo {litres:num} dru wug ɔmba. Glorp zub {can:g} dru.",
            "water_litres_hour": "Zub {litres:num} dru frim wug ɔmba.",
            "water_litres_day": "Zub {litres:num} dru frim wug sarn, zub {hours:g} {unit}.",
            "hour_words": {"one": "ɔmba", "other": "ɔmbaɔz"},
            "water_very_little": "Frimo vosh wug zub frim tiv.",
            "water_tested": "Frimo zub plim vosh.",
            "water_first_estimate": "Frimo zub kwem. Frim wug tiv zub.",
            "water_shortage": "Frim tiv zub, wug blopɔz.",
            "water_none": "Frim tiv vosh wug.",
            "quality_heading": "Frim zub glorp wug?",
            "quality": {"pass": "Zɛ.", "aesthetic": "Zɛ, wug frimo vosh.",
                        "health_fail": "Tiv.", "national_fail": "Tiv wug.",
                        "indeterminate": "Wug tiv zub.", "none": "Frim tiv vosh sarn."},
            "quality_found": "Frimo vosh zub: {names}.",
            "quality_ask": "Wug blopɔz.",
            "contacts_heading": "Zub wug kwem",
            "contacts_columns": {"role": "Zub", "name": "Plimo", "phone": "Druvo"},
            "contacts_write_in": {"mechanic": "Plim sarno", "office": "Frim vosho"},
            "report_heading": "Plim wug tiv",
            "report_tell": "Wug blopo zub sarn.",
            "report_number": "Glorp zub kwemo: {id}.",
            "report_scan": "ɔ druvo zub plimo.",
            "report_caption": "Druvo zub kwemo {id}",
            "keep_heading": "Zub frimo wug vosho",
            "keep_structures": {"Septic tank or soakaway": "Sarnɔz",
                                "Buildings": "Blopɔz", "Hand dug well": "Kwemɔz",
                                "Solid waste dump or burial ground": "Tiv plimo"},
            "keep_centre": "Glorp",
            "keep_metres": "{distance:g} druɔ",
            "keep_caption": "Vosho tiv sarno.",
        }},
    },
    "zy": {
        "language": {"name": "Ypsilonian", "translated_by": "C. Translator",
                     "checked_by": "D. Checker"},
        "text": {"community_sheet": {
            "title": "{place}: zɛdo \\u2014 glorp",
            "quality": {"none": "Wug  tiv zub."},
            "keep_structures": {"Buildings": "Blopɔz"},
            "water_first_estimate": None,
        }},
    },
    # nothing translated yet: English throughout, and every part counted
    "zx": {"language": {"name": "Alphan", "translated_by": "A. Translator",
                        "checked_by": "B. Checker"}, "text": {}},
    # no checker is named: it is not offered, a sheet asked for in it is
    # refused, and whoever builds any sheet is told it is there
    "yy": {"language": {"name": "Unchecked", "translated_by": "E. Translator"},
           "text": {"community_sheet": {"title": "X {place}"}}},
}

#: The sheet for: nothing at all; the whole of it; and then each thing that
#: changes what it says, one at a time. ``hours_per_day`` is given as JSON
#: gives it, so a text or a true where a number belongs is in the list.
COMMUNITY_SHEET_CASES = [
    # nothing loaded and nothing entered
    {"site": {"community": "Rokel"}},
    # everything: a range, hours, a committee, a plate and a report address
    {"site": {"community": " Dr. Timbo's  Residence "}, "analysis": _yield(0.39, 0.22),
     "quality": _verdict("pass"), "committee": COMMITTEE,
     "asset_id": " SL-WAR-8FEEVKQ-T ", "hours_per_day": 8,
     "report_url": "https://water.example.org/app/"},
    # a first estimate with no range and no hours, a plate typed in lower
    # case with spaces in it, which the registry reads, and no address
    {"site": {"community": "Kuntoloh"}, "analysis": _yield(1.25, None, "indicative"),
     "quality": _verdict("health_fail", "Manganese", "E. coli"),
     "asset_id": " sl-war-8feevkq -t "},
    # identifiers the registry does not give: a wrong check character, free
    # text, and both with a report address set, which is then never read
    {"site": {"community": "A"}, "asset_id": "SL-WAR-8FEEVKQ-X"},
    {"site": {"community": "A"}, "asset_id": "the borehole by the school",
     "report_url": "https://water.example.org/app/"},
    # long and short dashes, doubled spaces and no-break spaces in what was
    # typed: one way of writing them, for both writers
    {"site": {"community": " Bo \u2013 Kenema  Road \u2014 East "},
     "committee": [{"role": "Chair \u2013 acting", "name": "Aminata\t\u00a0Kamara\u202f",
                    "contact": "076  000\u2014000"}],
     "asset_id": "SL\u2013WAR\u20138FEEVKQ\u2013T",
     "report_url": "https://water.example.org/app/"},
    # more members than one page holds, and members that are not members
    {"site": {"community": "A"}, "committee": [
        {"role": "Member", "name": f"Person {n}", "contact": ""} for n in range(1, 11)]},
    {"site": {"community": "A"}, "committee": [
        None, "Aminata", 7, {"role": "Chair", "name": 12, "contact": 76000000},
        {"role": "Caretaker", "name": "Sorie Conteh", "phone": "", "contact": "077 1"},
        {"name": "Fatmata Sesay"}]},
    # a link too long for the square stops the sheet in both engines
    {"site": {"community": "A"}, "asset_id": "SL-WAR-8FEEVKQ-T",
     "report_url": "https://water.example.org/" + "a-long-path-of-the-programme/" * 3},
    # no place, and a test with no yield yet
    {"site": {"community": ""}, "analysis": {"yield_recommendation": {
        "safe_yield_m3_per_h": None, "safe_yield_low_m3_per_h": None,
        "confidence": "established"}}},
    {"site": {"community": "A"}, "analysis": {"yield_recommendation": None}},
    # rounding, always downward: a hair under a whole number, three figures,
    # five figures, and amounts under one jerrycan
    {"site": {"community": "A"}, "analysis": _yield(0.57), "hours_per_day": 6.5},
    {"site": {"community": "A"}, "analysis": _yield(1.999, 1.794), "hours_per_day": 10},
    {"site": {"community": "A"}, "analysis": _yield(12.48), "hours_per_day": 24},
    {"site": {"community": "A"}, "analysis": _yield(0.019), "hours_per_day": 1},
    {"site": {"community": "A"}, "analysis": _yield(0.019)},
    # litres that are not a whole number of jerrycans: the two figures the
    # sheet gives agree all the same
    {"site": {"community": "A"}, "analysis": _yield(0.391, 0.2198)},
    {"site": {"community": "A"}, "analysis": _yield(0.391, 0.2198), "hours_per_day": 3},
    # an amount in an hour that is nothing in the part of an hour it is used
    {"site": {"community": "A"}, "analysis": _yield(0.0015), "hours_per_day": 0.5},
    {"site": {"community": "A"}, "analysis": _yield(0.012), "hours_per_day": 1.5},
    {"site": {"community": "A"}, "analysis": _yield(0.0004), "hours_per_day": 8},
    {"site": {"community": "A"}, "analysis": _yield(0.02, None, "indicative"),
     "hours_per_day": 1},
    # hours that are not a time of day's worth are not used
    {"site": {"community": "A"}, "analysis": _yield(0.8), "hours_per_day": 0},
    {"site": {"community": "A"}, "analysis": _yield(0.8), "hours_per_day": 25},
    {"site": {"community": "A"}, "analysis": _yield(0.8), "hours_per_day": -3},
    {"site": {"community": "A"}, "analysis": _yield(0.8), "hours_per_day": "8"},
    {"site": {"community": "A"}, "analysis": _yield(0.8), "hours_per_day": True},
    # each answer on safety, and a verdict the sheet has no words for
    {"site": {"community": "A"}, "quality": _verdict("aesthetic")},
    {"site": {"community": "A"}, "quality": _verdict("health_fail")},
    {"site": {"community": "A"}, "quality": _verdict("national_fail")},
    {"site": {"community": "A"},
     "quality": _verdict("national_fail", national=("Total coliforms",))},
    {"site": {"community": "A"}, "quality": _verdict("indeterminate")},
    {"site": {"community": "A"}, "quality": _verdict("not a verdict")},
    {"site": {"community": "A"}, "quality": _verdict("none")},
    # a bundled example loaded: said across the top, and to the builder
    {"site": {"community": "Rokel"}, "analysis": _yield(0.39, 0.22), "example": True},
    # an address the registry will not print stops the sheet in both engines
    {"site": {"community": "A"}, "asset_id": "SL-WAR-8FEEVKQ-T",
     "report_url": "http://water.example.org/app/"},
    # and one with no plate to name does not come to it
    {"site": {"community": "A"}, "report_url": "https://water.example.org/app/"},
    # --- in another language (PLAN.md step 9.2) ---
    # the whole of it: every sentence a full sheet prints, and what a failed
    # water test, an example and a first estimate add
    {"site": {"community": "Rokel"}, "analysis": _yield(0.39, 0.22),
     "quality": _verdict("pass"), "committee": COMMITTEE, "asset_id": "SL-WAR-8FEEVKQ-T",
     "hours_per_day": 8, "report_url": "https://water.example.org/app/",
     "language": "zz", "translations": TRANSLATIONS},
    {"site": {"community": ""}, "analysis": _yield(1.25, None, "indicative"),
     "quality": _verdict("health_fail", "Manganese"), "example": True, "hours_per_day": 1,
     "language": "zz", "translations": TRANSLATIONS},
    {"site": {"community": "A"}, "analysis": _yield(0.019), "hours_per_day": 6.5,
     "quality": _verdict("aesthetic"), "language": "zz", "translations": TRANSLATIONS},
    {"site": {"community": "A"}, "language": "zz", "translations": TRANSLATIONS},
    # each way the amount of water is told: in an hour, in litres in an
    # hour, in litres in a day, and as very little
    {"site": {"community": "A"}, "analysis": _yield(0.39, 0.22),
     "quality": _verdict("national_fail"), "language": "zz", "translations": TRANSLATIONS},
    {"site": {"community": "A"}, "analysis": _yield(0.019),
     "quality": _verdict("indeterminate"), "language": "zz", "translations": TRANSLATIONS},
    {"site": {"community": "A"}, "analysis": _yield(0.012), "hours_per_day": 1.5,
     "language": "zz", "translations": TRANSLATIONS},
    {"site": {"community": "A"}, "analysis": _yield(0.0004), "language": "zz",
     "translations": TRANSLATIONS},
    # a part of it: the rest is English, and the builder is told how much.
    # Its dash and its doubled space are written as typed text is
    {"site": {"community": "Rokel"}, "analysis": _yield(0.39, 0.22, "indicative"),
     "committee": COMMITTEE, "asset_id": "SL-WAR-8FEEVKQ-T", "hours_per_day": 8,
     "language": "zy", "translations": TRANSLATIONS},
    # a translation with nothing in it yet: the same sheets, every part of
    # each counted as English, so that both engines ask the speaker for the
    # same parts on every path
    {"site": {"community": "Rokel"}, "analysis": _yield(0.39, 0.22),
     "quality": _verdict("pass"), "committee": COMMITTEE, "asset_id": "SL-WAR-8FEEVKQ-T",
     "hours_per_day": 8, "report_url": "https://water.example.org/app/",
     "language": "zx", "translations": TRANSLATIONS},
    {"site": {"community": ""}, "analysis": _yield(1.25, None, "indicative"),
     "quality": _verdict("health_fail", "Manganese"), "example": True,
     "language": "zx", "translations": TRANSLATIONS},
    {"site": {"community": "A"}, "analysis": _yield(0.019), "language": "zx",
     "translations": TRANSLATIONS},
    {"site": {"community": "A"}, "analysis": _yield(0.012), "hours_per_day": 1.5,
     "language": "zx", "translations": TRANSLATIONS},
    {"site": {"community": "A"}, "analysis": _yield(0.0004), "language": "zx",
     "translations": TRANSLATIONS},
    # hours entered and an amount for the day that rounds to nothing: the
    # sheet says "very little" and prints no word for hours, so none is
    # counted as English
    {"site": {"community": "A"}, "analysis": _yield(0.001), "hours_per_day": 0.5,
     "language": "zx", "translations": TRANSLATIONS},
    {"site": {"community": "A"}, "analysis": _yield(0.001), "hours_per_day": 0.5,
     "language": "zz", "translations": TRANSLATIONS},
    # English where a translation is on offer: nobody is told that none exists
    {"site": {"community": "Rokel"}, "translations": TRANSLATIONS},
    # English where nothing is installed, whatever the package bundles
    {"site": {"community": "Rokel"}, "translations": {}},
    # a language that is not offered, and one that is not there, stop the
    # sheet in both engines
    {"site": {"community": "Rokel"}, "language": "yy", "translations": TRANSLATIONS},
    {"site": {"community": "Rokel"}, "language": "qq", "translations": TRANSLATIONS},
    # and with none installed, any language is one that is not there
    {"site": {"community": "Rokel"}, "language": "kri", "translations": {}},
]


def community_sheet_reference() -> dict:
    from groundwater.community_sheet import community_sheet_content, round_down

    results = []
    for case in COMMUNITY_SHEET_CASES:
        config = Config()
        config.service.report_url = case.get("report_url", "")
        try:
            results.append(community_sheet_content(
                SiteMetadata(**case["site"]),
                analysis=_ns(case["analysis"]) if case.get("analysis") else None,
                quality=_ns(case["quality"]) if case.get("quality") else None,
                committee=case.get("committee"), asset_id=case.get("asset_id", ""),
                hours_per_day=case.get("hours_per_day"),
                example=case.get("example", False), config=config,
                language=case.get("language", ""), translations=case.get("translations")))
        except ValueError as error:
            results.append({"error": str(error)})
    amounts = [0, 0.4, 19.99, 99, 100, 101, 219.99999, 569.9999999999999, 999.5, 1000,
               1790, 12480, 123456.7, 999999]
    return {"cases": COMMUNITY_SHEET_CASES, "results": results,
            "amounts": amounts, "rounded": [round_down(x) for x in amounts]}

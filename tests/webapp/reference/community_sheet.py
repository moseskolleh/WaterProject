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
#: is bundled): a whole one for the parts a full sheet prints, one that has a
#: sentence and part of a table, and one that may not be offered.
TRANSLATIONS = {
    "zz": {
        "language": {"name": "Zedish", "translated_by": "A. Translator",
                     "checked_by": "B. Checker"},
        "text": {"community_sheet": {
            "title": "Una b\u0254r\u0254l na {place}",
            "title_unnamed": "Una b\u0254r\u0254l",
            "example": "D\u025bn mek dis pepa wit \u025bgzampul. N\u0254 gi am to p\u0254sin.",
            "water_heading": "Us k\u0254l wata",
            "water_day": "L\u025bk {cans:num} {cans:plural:j\u025briken|j\u025briken d\u025bm} wata insay wan de.",
            "water_day_detail": "Dat na {litres:num} lita, w\u025bn di p\u0254mp wok f\u0254 {hours:g} "
                                "{unit} insay wan de. Wan j\u025briken na {can:g} lita.",
            "water_hour": "L\u025bk {cans:num} {cans:plural:j\u025briken|j\u025briken d\u025bm} insay wan awa.",
            "water_hour_detail": "Dat na {litres:num} lita insay wan awa. Wan j\u025briken na {can:g} lita.",
            "water_litres_hour": "L\u025bk {litres:num} lita insay wan awa.",
            "water_litres_day": "L\u025bk {litres:num} lita insay wan de, f\u0254 {hours:g} {unit}.",
            "hour_words": {"one": "awa", "other": "awa d\u025bm"},
            "water_very_little": "Di t\u025bst si smol wata n\u0254m\u0254.",
            "water_tested": "Dis k\u0254m\u0254t na di p\u0254mp t\u025bst.",
            "water_first_estimate": "Dis na f\u0254s g\u025bs. Di wata kin smol pas dis.",
            "water_shortage": "If di wata smol pas dis, t\u025bl di k\u0254miti.",
            "water_none": "D\u025bn n\u0254 m\u025bzh\u0254 di wata yet.",
            "quality_heading": "Di wata fayn f\u0254 drink?",
            "quality": {"pass": "Y\u025bs.", "aesthetic": "Y\u025bs, b\u0254t i kin get test.",
                        "health_fail": "N\u0254.", "national_fail": "N\u0254 yet.",
                        "indeterminate": "Wi n\u0254 no yet.", "none": "D\u025bn n\u0254 t\u025bst am yet."},
            "quality_found": "Di t\u025bst si dis tumos: {names}.",
            "quality_ask": "Aks di k\u0254miti.",
            "contacts_heading": "Udat f\u0254 k\u0254l",
            "contacts_columns": {"role": "Udat", "name": "Nem", "phone": "Fon"},
            "contacts_write_in": {"mechanic": "P\u0254mp mekanik", "office": "Di wata \u0254fis"},
            "report_heading": "If di p\u0254mp pwel",
            "report_tell": "T\u025bl di kiateka di sem de.",
            "report_number": "Gi d\u025bn dis n\u0254mba: {id}.",
            "report_scan": "\u0254 skan di skw\u025by.",
            "report_caption": "Skan f\u0254 rip\u0254t {id}",
            "keep_heading": "L\u025bf d\u025bn tin ya fawe",
            "keep_structures": {"Septic tank or soakaway": "Latrin d\u025bm",
                                "Buildings": "Os d\u025bm", "Hand dug well": "W\u025bl d\u025bm",
                                "Solid waste dump or burial ground": "D\u0254ti ples"},
            "keep_line": "{what}: {distance:g} mita.",
            "keep_centre": "B\u0254r\u0254l",
            "keep_metres": "{distance:g} m",
            "keep_caption": "Di pikch\u0254 n\u0254 to skel.",
        }},
    },
    "zy": {
        "language": {"name": "Ypsilonian", "translated_by": "C. Translator",
                     "checked_by": "D. Checker"},
        "text": {"community_sheet": {
            "title": "{place}: una b\u0254r\u0254l",
            "quality": {"none": "Wi n\u0254 no yet."},
            "keep_structures": {"Buildings": "Os d\u025bm"},
            "water_first_estimate": None,
        }},
    },
    # no checker is named: it is not offered, and a sheet asked for in it is
    # refused
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
    # long and short dashes and doubled spaces in what was typed: one way of
    # writing them, for both writers
    {"site": {"community": " Bo \u2013 Kenema  Road \u2014 East "},
     "committee": [{"role": "Chair \u2013 acting", "name": "Aminata\t Kamara",
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
    # a part of it: the rest is English, and the builder is told how much
    {"site": {"community": "Rokel"}, "analysis": _yield(0.39, 0.22, "indicative"),
     "committee": COMMITTEE, "asset_id": "SL-WAR-8FEEVKQ-T", "hours_per_day": 8,
     "language": "zy", "translations": TRANSLATIONS},
    # English where a translation is on offer: nobody is told that none exists
    {"site": {"community": "Rokel"}, "translations": TRANSLATIONS},
    # a language that is not offered, and one that is not there, stop the
    # sheet in both engines
    {"site": {"community": "Rokel"}, "language": "yy", "translations": TRANSLATIONS},
    {"site": {"community": "Rokel"}, "language": "qq", "translations": TRANSLATIONS},
    # and with none bundled, any language is one that is not there
    {"site": {"community": "Rokel"}, "language": "kri"},
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

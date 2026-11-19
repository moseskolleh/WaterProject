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


def _verdict(state, *parameters) -> dict:
    return {"verdict_state": state,
            "health_exceedances": [{"parameter": name} for name in parameters]}


COMMITTEE = [
    {"role": "Chairperson", "name": "  Aminata   Kamara ", "contact": "076 000 000"},
    {"role": "Caretaker", "name": "Sorie Conteh", "phone": ""},
    # a role nobody was named for is a line nobody can call
    {"role": "Treasurer", "name": " ", "contact": ""},
    {"role": "", "name": "", "contact": "+232 77 111 222"},
]

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
    # a first estimate with no range and no hours, a plate and no address
    {"site": {"community": "Kuntoloh"}, "analysis": _yield(1.25, None, "indicative"),
     "quality": _verdict("health_fail", "Manganese", "E. coli"),
     "asset_id": "SL-PLK-7QX2M4A-K"},
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
    {"site": {"community": "A"}, "quality": _verdict("indeterminate")},
    {"site": {"community": "A"}, "quality": _verdict("not a verdict")},
    {"site": {"community": "A"}, "quality": _verdict("none")},
    # an address the registry will not print stops the sheet in both engines
    {"site": {"community": "A"}, "asset_id": "SL-WAR-8FEEVKQ-T",
     "report_url": "http://water.example.org/app/"},
    # and one with no plate to name does not come to it
    {"site": {"community": "A"}, "report_url": "https://water.example.org/app/"},
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
                hours_per_day=case.get("hours_per_day"), config=config))
        except ValueError as error:
            results.append({"error": str(error)})
    amounts = [0, 0.4, 19.99, 99, 100, 101, 219.99999, 569.9999999999999, 999.5, 1000,
               1790, 12480, 123456.7, 999999]
    return {"cases": COMMUNITY_SHEET_CASES, "results": results,
            "amounts": amounts, "rounded": [round_down(x) for x in amounts]}

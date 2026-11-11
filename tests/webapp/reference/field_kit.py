"""Airlift yield (PLAN.md step 2.3) and the field kit: the "airlift" and
"field_kit" entries of ``reference.json``.
"""

from __future__ import annotations

from groundwater.config import Config
from groundwater.models import SiteMetadata


# ----------------------------------------------- airlift yield (step 2.3)

#: The drilling co-pilot's airlift readings: containers timed once and
#: more than once, notch heads inside, at the edges of and outside the range
#: the coefficient holds for, a reason with untidy spaces, and readings that
#: give no yield, which both engines refuse.
AIRLIFT_CASES = [
    ["bucket", {"volume_l": 20, "timings_s": [25, 24.6, 25.4]}],
    ["bucket", {"volume_l": 10, "timings_s": [7.3]}],
    ["bucket", {"volume_l": 200, "timings_s": [61.5, 59.25]}],
    ["vnotch", {"head_mm": 34}],
    ["vnotch", {"head_mm": 50}],
    ["vnotch", {"head_mm": 87.5}],
    ["vnotch", {"head_mm": 380}],
    ["vnotch", {"head_mm": 410}],
    ["none", {"reason": "  compressor\tdown,  no airlift "}],
    ["bucket", {"volume_l": 20, "timings_s": []}],
    ["bucket", {"volume_l": 0, "timings_s": [20]}],
    ["bucket", {"volume_l": 20, "timings_s": [20, 0]}],
    ["vnotch", {"head_mm": 0}],
    ["none", {"reason": " \t "}],
    ["airlift", {}],
]


def airlift_reference() -> dict:
    from groundwater.field_kit import airlift_yield

    results = []
    for method, options in AIRLIFT_CASES:
        try:
            results.append(airlift_yield(method, **options))
        except ValueError:
            results.append(None)
    return {"cases": AIRLIFT_CASES, "results": results}


# ------------------------------------------------------------- the field kit

# The kit for three projects: the plain one; one named by its reference only,
# with a wider casing, a shorter minimum test and another depth rule; and one
# with no name at all and a riser as wide as the casing, which leaves no
# casing storage to state. Every word, number and sheet code is compared.
FIELD_KIT_CASES = [
    {"site": {"project": "Rokel 2026", "project_ref": "", "community": "Kuntolo",
              "client": "Living Water International", "district": "Port Loko",
              "supervisor": "WiNGiN"},
     "boreholes": ["KTL-01", "KTL|02 %x", " KTL-01 ", "", "BH\t 3\n"],
     "config": {}},
    {"site": {"project": "Ignored", "project_ref": " LWI/2026/07 ",
              "community": "Rokel", "client": "", "district": "", "supervisor": ""},
     "boreholes": ["RK-1"],
     "config": {"pumping": {"casing_diameter_in": 6.0, "riser_diameter_in": 1.5,
                            "min_constant_test_min": 120.0,
                            "min_step_length_min": 100.0},
                "ves": {"depth_of_investigation_factor": 0.3}}},
    {"site": {"project": "", "project_ref": "", "community": "", "client": "",
              "district": "", "supervisor": ""},
     "boreholes": ["\u00d8-1 K\u0254n\u0254"],
     "config": {"pumping": {"casing_diameter_in": 1.25, "riser_diameter_in": 1.25}}},
]

# sheet codes to read: the kit's own, and texts that are not one
FIELD_KIT_CODES = [
    "GWT-FK/1|pumping|Rokel 2026|KTL-01",
    "GWT-FK/1|pumping|A%7CB%25C|%2541",
    "  GWT-FK/1|pumping||RK-1\n",
    "GWT-FK/2|pumping|Rokel 2026|KTL-01",
    "GWT-FK/1|pumping|Rokel 2026",
    "GWT-FK/1||Rokel 2026|KTL-01",
    "BOREHOLE SL-WAR-8FEEVKQ-T",
    # trimmed of the six ASCII spaces only, which str.strip() and
    # String.trim() are not: a byte-order mark and U+0085 are kept
    "\ufeffGWT-FK/1|pumping|P|B",
    "GWT-FK/1|pumping|P|B\u0085",
]

# names to make codes of, with the characters str.strip() and String.trim()
# disagree about, unicode, the escapes, and runs of spaces
FIELD_KIT_NAMES = [
    ["\ufeffRokel", "BH-1\ufeff"],
    ["x\u0085", "\u001cFS\u001f"],
    ["\u00a0K\u0254n\u0254\u00a0", "\u3000\u00d8-1 \U0001f4a7\u2028"],
    ["A|B%C%7C%25", " %7c|| "],
    ["line 1\r\nline 2", "\t\vBH\f 3 "],
]


def field_kit_reference() -> dict:
    from dataclasses import asdict

    from groundwater import field_kit as fk
    from groundwater import qr
    from groundwater.config import Config

    def config_for(overrides: dict) -> Config:
        config = Config()
        for section, values in overrides.items():
            for key, value in values.items():
                setattr(getattr(config, section), key, value)
        return config

    content = []
    for case in FIELD_KIT_CASES:
        config = config_for(case["config"])
        site = SiteMetadata(**case["site"])
        content.append(fk.field_kit_content(site, case["boreholes"], config))
    plans = [fk.ves_survey_plan(depth, config_for(case["config"]).ves)
             for depth in (0.4, 30, 62.5, 250, 400)
             for case in FIELD_KIT_CASES[:2]]
    return {
        "cases": FIELD_KIT_CASES,
        "content": content,
        "codes": FIELD_KIT_CODES,
        "parsed": [asdict(p) if (p := fk.parse_field_kit_payload(text)) else None
                   for text in FIELD_KIT_CODES],
        "names": FIELD_KIT_NAMES,
        "payloads": [fk.field_kit_payload(project, borehole)
                     for project, borehole in FIELD_KIT_NAMES],
        "minutes": {str(until): fk.reading_minutes(until)
                    for until in (0.4, 60, 120, 121, 240, 330)},
        "plans": plans,
        # every module of the first kit's printed symbols, at the level the
        # sheets print them
        "symbols": [["".join("1" if cell else "0" for cell in row)
                     for row in qr.encode(sheet["payload"], ecc="H").modules]
                    for sheet in content[0]["sheets"]],
    }

"""Sanitary inspection (PLAN.md step 7.5): the "sanitary" entry of
``reference.json``.
"""

from __future__ import annotations

from groundwater.models import SiteMetadata, WaterQualityResult, WaterQualitySample
from groundwater.quality import assess_sample

from .common import clean


def sanitary_reference() -> dict:
    """Sanitary inspection (PLAN.md step 7.5): forms scored and laid out as a
    table, counts graded, and the latest inspection read with the E. coli
    count of a sample into one statement, over every way each side can be
    known, partly known or unknown. The cases carry their own inputs, so
    parity.mjs gives the browser exactly these."""
    from groundwater import sanitary as SAN
    from groundwater.registry import Asset, clean_answers, iso_date, merge_events, trim_field

    asset_id = "SL-WAR-8FEEVKQ-T"
    forms = ["YNNYNNYNYN", "YNN--NYN-N", "----------", "NNNNNNNNNN", "YYYYYYYYYY",
             "yn", "YNY?nnnnnN", ""]
    counts = [0, 0.5, 1, 10, 10.5, 11, 100, 101, 1000, 1000.5, 25000]

    def form(when, answers, by="", note=""):
        return SAN.inspection_event(when, answers, by=by, note=note).as_dict()

    inspections = {
        "none": [],
        "complete": [form("2024-05-20", "NNYNNNNNNN", by="A. Bangura")],
        "intermediate": [form("2024-05-20", "YNNYNNYNYN", by=" M. Kolleh ")],
        "very_high": [form("2024-05-20", "YYYYYYYYYN")],
        "incomplete": [form("2024-05-20", "YNN--NYN-N")],
        "nearly_blank": [form("2024-05-20", "Y---------")],
        # the latest that scores, a later visit with no form after it, and a
        # form dated after today
        "later_unscored": [form("2023-11-02", "YYYYYYNNNN"), form("2024-02-01", "YNNNNNNNNN"),
                           {"when": "2024-04-11", "kind": "inspection", "note": "looked"},
                           form("2099-01-01", "YYYYYYYYYY")],
        "same_day": [form("2024-05-20", "NNNNNNNNNN", by="A"), form("2024-05-20", "YYYNNNNNNN", by="B"),
                     form("2024-05-20", "YYYNNNNNNN", by="C")],
        "blank": [form("2024-05-20", "----------")],
        "unreadable": [{"when": "2024-05-20", "kind": "inspection", "form": "tubewell_handpump",
                        "answers": "YN"},
                       {"when": "2024-05-21", "kind": "inspection", "form": "hand_dug_well",
                        "answers": "YNNYNNYNYN"}],
        "note_only": [{"when": "2024-05-20", "kind": "inspection", "note": "apron cracked"},
                      {"when": "bad date", "kind": "inspection", "form": "tubewell_handpump",
                       "answers": "YYYYYYYYYY"}],
        # dates Python 3.11 read and the browser did not: neither reads them
        "compact": [form("20240520", "YYYYYYYYYN")],
        "week": [form("2024-05-20", "NNNNNNNNNN"), form("2024-W21-1", "YYYYYYYYYN"),
                 form("2024-05-20T09:00", "YYYYYYYYYN")],
        # ends the two engines' own trims used to read apart
        "bom": [{"when": "\ufeff2024-05-20", "kind": "\ufeffinspection",
                 "form": "tubewell_handpump\ufeff", "answers": "\ufeffYNNYNNYNYN",
                 "by": "\ufeffA. Bangura\x1c"}],
        "separator": [{"when": "2024-05-20\x1c", "kind": "inspection\x85",
                       "form": "\x1ftubewell_handpump", "answers": "YNNYNNYNYN\x1c",
                       "note": "apron cracked\x1e"}],
        # a water sample the history records: named when no analysis is
        # loaded, and when it is later than the one read
        "sampled": [{"when": "2024-03-01", "kind": "water_sample",
                     "note": "E. coli 12 per 100 mL field kit"},
                    form("2024-05-20", "YNNYNNYNYN")],
        "sampled_later": [{"when": "2024-05-25", "kind": "water_sample", "by": "M. Kolleh"},
                          {"when": "2024-05-26", "kind": "water_sample"},
                          {"when": "2024-07-01", "kind": "water_sample"},
                          form("2024-05-20", "NNNNNNNNNN")],
    }
    panel = [{"parameter": "Arsenic", "value": 0.001, "unit": "mg/L"},
             {"parameter": "Fluoride", "value": 0.3, "unit": "mg/L"},
             {"parameter": "Nitrate (as NO3)", "value": 5.0, "unit": "mg/L"}]

    def sample(*ecoli, when="2024-05-21"):
        return {"site": {"community": "Ref"}, "flags": [], "sample_date": when,
                "results": [dict(r) for r in ecoli] + [dict(r) for r in panel]}

    def ecoli(value=None, unit="CFU/100 mL", parameter="E. coli", **kw):
        return {"parameter": parameter, "value": value, "unit": unit, **kw}

    samples = {
        "none": None,
        "clean": sample(ecoli(0.0)),
        "counted": sample(ecoli(40.0)),
        "heavy": sample(ecoli(2400.0)),
        "below": sample(ecoli(None, below_detection=True, detection_limit=1.0)),
        "absent": sample(ecoli(None, below_detection=True)),
        "over": sample(ecoli(None, greater_than=50.0)),
        "at_least": sample(ecoli(None, greater_than=1000.0, greater_than_inclusive=True)),
        "present": sample(ecoli(None, greater_than=0.0)),
        "coarse": sample(ecoli(None, below_detection=True, detection_limit=10.0)),
        "missing": sample(),
        "per_ml": sample(ecoli(2.0, unit="CFU/mL", parameter="Thermotolerant coliforms")),
        "two_rows": sample(ecoli(0.0), ecoli(150.0, parameter="Faecal coliforms")),
        "undated": sample(ecoli(3.0), when=""),
        "bad_unit": sample(ecoli(3.0, unit="wibbles")),
        # results the assessment could not grade, whose remarks end in a
        # full stop of their own or do not ("/100 mL" was one until the
        # water quality audit read it as a count per 100 mL)
        "unread_unit": sample(ecoli(3.0, unit="colonies")),
        "unreadable": sample(ecoli(None, unreadable="lots")),
        "coarse_per_ml": sample(ecoli(None, below_detection=True, detection_limit=1.0,
                                      unit="CFU/mL")),
        "chemistry": sample(ecoli(0.0), {"parameter": "Arsenic", "value": 0.05, "unit": "mg/L"}),
    }
    pairs = ([(name, "clean") for name in inspections] + [(name, "none") for name in inspections]
             + [("complete", name) for name in samples] + [("incomplete", name) for name in samples]
             + [("none", name) for name in samples])
    cases = []
    for inspection, which in pairs:
        raw = samples[which]
        assessment = None
        if raw is not None:
            assessment = assess_sample(WaterQualitySample(
                site=SiteMetadata(community="Ref"), sample_date=raw["sample_date"],
                results=[WaterQualityResult(**r) for r in raw["results"]]))
        events = inspections[inspection]
        asset = Asset(asset_id=asset_id, events=merge_events(asset_id, events))
        cases.append({
            "name": f"{inspection}/{which}", "events": events, "sample": raw,
            "today": "2024-06-01",
            "expect": {"risk": SAN.sanitary_risk(asset, "2024-06-01", assessment),
                       "merged": [e.as_dict() for e in merge_events(asset_id, events)]},
        })
    # today written as neither engine reads a day, or with blanks at its ends
    todays = []
    clean_sample = samples["clean"]
    clean_assessment = assess_sample(WaterQualitySample(
        site=SiteMetadata(community="Ref"), sample_date=clean_sample["sample_date"],
        results=[WaterQualityResult(**r) for r in clean_sample["results"]]))
    for today in ("20240601", "2024-W22-6", "2024-06-01T00:00", " 2024-06-01\n",
                  "\ufeff2024-06-01", "2024-06-01\x1c", "0024-06-01", "0000-06-01"):
        events = inspections["complete"]
        asset = Asset(asset_id=asset_id, events=merge_events(asset_id, events))
        try:
            expect = {"risk": SAN.sanitary_risk(asset, today, clean_assessment)}
        except ValueError:
            expect = {"throws": True}
        todays.append({"name": repr(today), "events": events, "sample": clean_sample,
                       "today": today, "expect": expect})
    # days as both engines read them (iso_date and isoDay), and the ends of
    # a field and of a form's answers as both trim them
    texts = ["2024-05-20", "20240520", "2024-W21-1", "2024W211", "2024-05-20T09:00",
             "2024-5-20", "+2024-05-20", "\u0968\u0966\u0968\u096a-\u0966\u096b-\u0968\u0966",
             "2023-02-29", "2024-02-29", "0000-01-01", "0001-01-01", "0050-03-01", "0099-12-31",
             "9999-12-31", " 2024-05-20 ", "\ufeff2024-05-20", "2024-05-20\x1c", "\x852024-05-20",
             "\u20002024-05-20\u3000", "\u200b2024-05-20", "", None]
    blank = ("\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2005\u200a\u2028"
             "\u2029\u202f\u205f\u3000\ufeff")
    trims = ["\ufeffYNNYNNYNYN", "YNNYNNYNYN\x1c", blank + "YnN-x" + blank,
             blank + "YNNYNNYNYN" + blank, "\u200bYNNYNNYNYN\u200b", "\x00YN\x00", blank, "",
             None]

    def day(text):
        read = iso_date(text)
        return None if read is None else read.isoformat()

    return clean({
        "asset_id": asset_id,
        "cases": cases,
        "todays": todays,
        "days": [{"text": t, "expect": {"day": day(t)}} for t in texts],
        "trims": [{"text": t, "expect": {"trim": trim_field(t), "answers": clean_answers(t),
                                         "score": SAN.score_answers(t)}} for t in trims],
        # every code point of the Basic Multilingual Plane that trim_field
        # takes off an end: the browser's trimField must take the same
        "trimmed": [c for c in range(0x10000) if trim_field(chr(c) + "x") == "x"],
        "forms": [{"answers": a, "expect": {"score": SAN.score_answers(a), "rows": SAN.form_rows(a)}}
                  for a in forms],
        "grades": [{"count": c, "expect": {
            "grade": SAN.ecoli_grade(c), "above": list(SAN.ecoli_grades_above(c, False)),
            "above_inclusive": list(SAN.ecoli_grades_above(c, True))}} for c in counts],
        "questions": SAN.form_questions(),
        "tables": SAN.sanitary_tables(),
    })

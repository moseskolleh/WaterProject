"""Sanitary inspection, read with the E. coli count (PLAN.md step 7.5).

A water sample says what was in the water on the day it was taken. A
sanitary inspection says what could get into it: a latrine uphill, a
cracked apron, a pump loose on its base. WHO's approach to a community
supply reads the two together, because each covers what the other cannot
see: a clean sample from a borehole with every hazard around it is luck,
and a contaminated one from a well-kept borehole points at the aquifer or
the pump rather than the apron.

So this module does three things, from data both engines read:

* **Scores the form.** The inspection is WHO's ten-question form for a
  tubewell with a handpump (``data/sanitary_inspection.csv``), and its score
  is the number of questions answered yes, a risk present, banded as the
  form bands it (``data/sanitary_risk.yaml``). A question left unanswered is
  not a no: an incomplete form gives the range of scores its answers allow
  and says that it is incomplete.
* **Grades the count.** The E. coli (or thermotolerant coliform) result of
  the project's water quality assessment is graded A to E as WHO grades a
  count per 100 mL, with the sample's date. A count the laboratory did not
  put a number to gives the range of grades it allows; a result the
  assessment could not grade gives none, and says why.
* **Reads the two together** in a risk-to-health matrix, the cells of which
  are a choice made here and say so (``sanitary_risk.yaml``), into one
  statement with the action priority, naming the inspection and the sample
  by their dates. A side that is unknown is said to be unknown, and no
  priority is read from the matrix until it is known; a side known only as
  a range is taken at its worse end. A water sample the borehole's history
  records but whose analysis is not the one read here is named by its date,
  so the statement never contradicts the history beside it.

An inspection is an event in the asset registry (``registry.AssetEvent``
with ``kind="inspection"``), carrying its form and answers, so it merges by
content like every other record of the borehole. Every function here has a
twin of the same name in camel case in gwt-core.js, and parity holds them to
one another.
"""

from __future__ import annotations

import csv
import functools
import io
from datetime import date

import yaml

from ._resources import bundled_text
from .quality.assess import VERDICT_LONG
from .quality.standards import StandardEntry, normalise_parameter, to_standard_unit
from .registry import AssetEvent, clean_answers, iso_date, merge_events, trim_field
from .text import phrase, phrase_table

__all__ = [
    "DEFAULT_FORM",
    "PRIORITIES",
    "ecoli_grade",
    "ecoli_grades_above",
    "form_questions",
    "form_rows",
    "inspection_event",
    "latest_inspection",
    "microbiology",
    "sanitary_risk",
    "sanitary_tables",
    "score_answers",
    "score_band",
]

#: The form the apps offer: a tubewell, a drilled borehole, with a handpump.
DEFAULT_FORM = "tubewell_handpump"

#: The action priorities a cell of the matrix may hold, least first.
PRIORITIES = ("low", "higher", "urgent")

#: The scale the grades are written on. Built here rather than read from the
#: standards table, so a table that writes E. coli in another unit still
#: grades a count per 100 mL.
_PER_100_ML = StandardEntry(parameter="E. coli", unit="CFU/100 mL", who_health=None,
                            who_aesthetic=None, sl_standard=None,
                            category="microbiological", note="")


@functools.lru_cache(maxsize=1)
def sanitary_tables() -> dict:
    """``sanitary_inspection.csv`` and ``sanitary_risk.yaml``, parsed once.

    ``web/build_webapp_data.py`` emits this as ``GWT.data.sanitary``, so the
    browser reads exactly what this parses. A table that does not hold
    together - a band missing a score, a matrix row of the wrong length, a
    priority nobody defined - is refused here rather than read half right.
    Treat the result as read-only.
    """
    body = "".join(line for line in bundled_text("sanitary_inspection.csv").splitlines(True)
                   if not line.lstrip().startswith("#"))
    forms: dict[str, list[str]] = {}
    for row in csv.DictReader(io.StringIO(body)):
        questions = forms.setdefault(row["form"].strip(), [])
        if int(row["number"]) != len(questions) + 1:
            raise ValueError(f"sanitary_inspection.csv: question {row['number']} of "
                             f"{row['form']} is out of order")
        questions.append(row["question"].strip())
    risk = yaml.safe_load(bundled_text("sanitary_risk.yaml"))
    grades = [{"grade": str(g["grade"]), "max": None if g["max"] is None else float(g["max"])}
              for g in risk["grades"]]
    if not grades or grades[-1]["max"] is not None or any(
            g["max"] is None for g in grades[:-1]):
        raise ValueError("sanitary_risk.yaml: only the last grade is open above")
    out: dict = {"forms": {}, "grades": grades}
    for form, questions in forms.items():
        n = len(questions)
        bands = [{"key": str(b["key"]), "min": int(b["min"]), "max": int(b["max"])}
                 for b in risk["bands"][form]]
        if [b["min"] for b in bands] != [0] + [b["max"] + 1 for b in bands[:-1]] or \
                bands[-1]["max"] != n:
            raise ValueError(f"sanitary_risk.yaml: the bands of {form} do not cover 0 to {n}")
        matrix = risk["matrix"][form]
        if sorted(matrix) != sorted(g["grade"] for g in grades):
            raise ValueError(f"sanitary_risk.yaml: the matrix of {form} needs a row per grade")
        cells = {}
        for grade in (g["grade"] for g in grades):
            row = [str(cell) for cell in matrix[grade]]
            if len(row) != n + 1 or any(cell not in PRIORITIES for cell in row):
                raise ValueError(f"sanitary_risk.yaml: row {grade} of {form} needs "
                                 f"{n + 1} cells, each one of {', '.join(PRIORITIES)}")
            cells[grade] = row
        out["forms"][form] = {"questions": questions, "bands": bands, "matrix": cells}
    return out


def _form(form: str) -> dict | None:
    return sanitary_tables()["forms"].get(form)


def form_questions(form: str = DEFAULT_FORM) -> list[str]:
    """The form's questions, in order."""
    spec = _form(form)
    return list(spec["questions"]) if spec else []


def score_band(score: int, form: str = DEFAULT_FORM) -> str:
    """The key of the band ``score`` falls in."""
    spec = _form(form)
    if spec is None:
        raise KeyError(f"no sanitary inspection form {form!r}")
    for band in spec["bands"]:
        if band["min"] <= score <= band["max"]:
            return band["key"]
    raise ValueError(f"{score} is not a score of the {form} form")


def score_answers(answers, form: str = DEFAULT_FORM) -> dict | None:
    """What a form's answers score, or ``None`` when they do not fit it.

    The score is the number of yes answers. A question not answered may be
    a yes, so an incomplete form scores a range, from its yes answers to
    those plus every question left open, and ``complete`` says which.
    """
    spec = _form(form)
    text = clean_answers(answers)
    if spec is None or len(text) != len(spec["questions"]):
        return None
    n = len(text)
    yes = text.count("Y")
    answered = n - text.count("-")
    low, high = yes, yes + (n - answered)
    return {"form": form, "n": n, "answered": answered, "yes": yes,
            "low": low, "high": high, "band_low": score_band(low, form),
            "band_high": score_band(high, form), "complete": answered == n}


def form_rows(answers, form: str = DEFAULT_FORM) -> list[list[str]]:
    """Number, question and answer for each question, for a table."""
    words = phrase_table("sanitary.answer")
    text = clean_answers(answers)
    return [[str(i + 1), question, words[text[i] if i < len(text) else "-"]]
            for i, question in enumerate(form_questions(form))]


def inspection_event(when: str, answers, by: str = "", note: str = "",
                     form: str = DEFAULT_FORM) -> AssetEvent:
    """A sanitary inspection, as the registry records it."""
    return AssetEvent(when=trim_field(when), kind="inspection", note=note, by=by,
                      form=form, answers=clean_answers(answers))


# ------------------------------------------------------------------ E. coli

def ecoli_grade(count: float) -> str:
    """The grade of a count per 100 mL: A for none, then B to E."""
    for grade in sanitary_tables()["grades"]:
        if grade["max"] is None or count <= grade["max"]:
            return grade["grade"]
    raise AssertionError("the last grade is open above")  # pragma: no cover


def ecoli_grades_above(bound: float, inclusive: bool = False) -> tuple[str, str]:
    """The grades a count of more than ``bound`` (or at least it) may be in."""
    grades = sanitary_tables()["grades"]
    for grade in grades:
        top = grade["max"]
        if top is None or bound < top or (inclusive and bound <= top):
            return grade["grade"], grades[-1]["grade"]
    raise AssertionError("the last grade is open above")  # pragma: no cover


def _per_100_ml(value: float, unit: str) -> float | None:
    converted, _ = to_standard_unit(float(value), unit, _PER_100_ML)
    return converted


def _reason(remark) -> str:
    """An assessment's remark, made to close a sentence the statement ends.

    A remark may or may not end in a full stop of its own; the statement
    adds one, so the remark's is taken off (with any blanks after it), the
    same characters in both engines.
    """
    return str(remark or "").rstrip(" \t\n\r\f\v.")


def _graded(row) -> dict:
    """What one E. coli row of an assessment says, on the grades' scale."""
    out = {"parameter": row.parameter, "kind": "ungraded", "count": None,
           "bound": None, "inclusive": False, "grade_low": None,
           "grade_high": None, "reason": _reason(row.remark), "unit": row.unit}
    if not row.evaluable or row.status == "indeterminate":
        return out
    if row.status == "below_detection":
        return {**out, "kind": "none_found", "count": 0.0, "grade_low": "A",
                "grade_high": "A", "reason": ""}
    if row.value is not None:
        count = _per_100_ml(row.value, row.unit)
        if count is None:
            return {**out, "kind": "unit", "reason": ""}
        grade = ecoli_grade(count)
        return {**out, "kind": "counted", "count": count, "grade_low": grade,
                "grade_high": grade, "reason": ""}
    if row.greater_than is not None:
        bound = _per_100_ml(row.greater_than, row.unit)
        if bound is None:
            return {**out, "kind": "unit", "reason": ""}
        inclusive = bool(row.greater_than_inclusive)
        low, high = ecoli_grades_above(bound, inclusive)
        kind = "detected" if bound == 0 and not inclusive else "bound"
        return {**out, "kind": kind, "bound": bound, "inclusive": inclusive,
                "grade_low": low, "grade_high": high, "reason": ""}
    return out


def microbiology(assessment) -> dict | None:
    """The E. coli side of the risk, from a water quality assessment.

    ``None`` when there is no assessment at all. Otherwise the sample's date
    as written and the graded result: of the rows naming E. coli or an
    alias of it (thermotolerant or faecal coliforms), the worst one graded;
    a row not measured is passed over, and with nothing graded the first
    row the assessment could not grade is reported with its reason.
    """
    if assessment is None:
        return None
    sample = getattr(assessment, "sample", None)
    when = trim_field(getattr(sample, "sample_date", "") or "")
    graded, ungraded = [], []
    order = [g["grade"] for g in sanitary_tables()["grades"]]
    for row in assessment.rows:
        if normalise_parameter(row.parameter) != "e. coli" or row.status == "not_measured":
            continue
        result = _graded(row)
        (graded if result["grade_low"] is not None else ungraded).append(result)
    if graded:
        # max keeps the first of equals, so the order the laboratory
        # reported them in settles a tie
        best = max(graded, key=lambda r: (order.index(r["grade_high"]),
                                          order.index(r["grade_low"])))
    elif ungraded:
        best = ungraded[0]
    else:
        best = {"parameter": "", "kind": "missing", "count": None, "bound": None,
                "inclusive": False, "grade_low": None, "grade_high": None,
                "reason": "", "unit": ""}
    return {"date": when, **best}


# --------------------------------------------------------------- inspections

def _today(today) -> date:
    """``today`` as a date: a date, or a day written YYYY-MM-DD and nothing
    else, read as ``isoDay`` reads it in the browser."""
    day = today if isinstance(today, date) else iso_date(today)
    if day is None:
        raise ValueError("the risk statement needs today's date, as YYYY-MM-DD")
    return day


def _latest_sample(events, today: date) -> tuple[AssetEvent, date] | None:
    """The latest water sample the history records, dated no later than
    ``today``, with its day; of several that day, the first in the
    registry's order."""
    pick: tuple[AssetEvent, date] | None = None
    for event in events or []:
        when = event.date if event.kind == "water_sample" else None
        if when is not None and when <= today and (pick is None or when > pick[1]):
            pick = (event, when)
    return pick


def latest_inspection(events, today) -> dict:
    """The inspection the risk statement rests on, from an event stream.

    The latest inspection whose form scores (at least one question
    answered), dated no later than ``today``; of several on that day, the
    one showing the most risk. ``later`` is the latest inspection after it
    that gives no score (a visit with no form, or a form left blank), which
    the statement mentions; with no inspection that scores, ``unscored`` is
    the latest form recorded that does not (blank, or not fitting any form).
    ``undated`` counts the forms whose date cannot be read as YYYY-MM-DD,
    which are not read and which the statement says are not.
    """
    today = _today(today)
    inspections = []
    undated = 0
    for event in events or []:
        if event.kind != "inspection":
            continue
        when = event.date
        if when is None:
            undated += 1 if (event.form or event.answers) else 0
            continue
        if when > today:
            continue
        score = score_answers(event.answers, event.form) if (event.form or event.answers) else None
        inspections.append((when, event, score))
    scored = [(w, e, s) for w, e, s in inspections if s is not None and s["answered"]]
    pick = same_day = None
    if scored:
        last = max(w for w, _, _ in scored)
        same_day = [(e, s) for w, e, s in scored if w == last]
        # the most risk: the highest the score may be, then the highest it is
        pick = max(same_day, key=lambda pair: (pair[1]["high"], pair[1]["low"]))
    unscored = [(w, e, s) for w, e, s in inspections if s is None or not s["answered"]]
    later = None
    if pick is not None:
        after = [(w, e) for w, e, _ in unscored if w > pick[0].date]
        if after:
            later = max(after, key=lambda pair: pair[0])[1]
    blank = None
    if pick is None:
        forms = [(w, e, s) for w, e, s in unscored if e.form or e.answers]
        if forms:
            blank = max(forms, key=lambda triple: triple[0])
    return {
        "event": pick[0] if pick else None,
        "score": pick[1] if pick else None,
        "same_day": len(same_day) if same_day else 0,
        "later": later,
        "unscored": blank[1] if blank else None,
        "unscored_fits": blank[2] is not None if blank else False,
        "undated": undated,
    }


# -------------------------------------------------------------- the statement

def _rank(priority: str) -> int:
    return PRIORITIES.index(priority)


def _when(event: AssetEvent) -> str:
    by = trim_field(event.by)
    return phrase("sanitary.dated_by", date=event.when, by=by) if by else event.when


def _span(low: str, high: str, table: dict) -> str:
    return table[low] if low == high else phrase("sanitary.span", low=table[low],
                                                 high=table[high])


def sanitary_risk(asset, today, assessment=None) -> dict:
    """The borehole's sanitary risk on ``today``, as one statement.

    ``asset`` is a registry asset (its events are read), ``today`` an ISO
    day or a date (records dated after it are not read), and ``assessment``
    the water quality assessment of the borehole's latest sample, or
    ``None`` when none is loaded. The result carries the parts and the
    ``statement`` that says them, with ``action``, the action priority to
    act on: ``None`` until both sides are known well enough to read one.
    ``sample_event`` is the latest water sample the history records, which
    the statement names when no analysis is loaded or when it is later than
    the sample the analysis is of.
    """
    events = merge_events(getattr(asset, "asset_id", ""), getattr(asset, "events", None) or [])
    found = latest_inspection(events, today)
    sampled = _latest_sample(events, _today(today))
    micro = microbiology(assessment)
    grades = [g["grade"] for g in sanitary_tables()["grades"]]
    band_words = phrase_table("sanitary.band")
    sentences: list[str] = []

    event, score = found["event"], found["score"]
    form = event.form if event is not None else DEFAULT_FORM
    if score is not None and event is not None:
        if score["complete"]:
            sentences.append(phrase("sanitary.inspection_complete", when=_when(event),
                                    yes=score["yes"], n=score["n"],
                                    band=band_words[score["band_low"]]))
        else:
            sentences.append(phrase(
                "sanitary.inspection_incomplete", when=_when(event),
                answered=score["answered"], n=score["n"], yes=score["yes"],
                low=score["low"], high=score["high"],
                band=_span(score["band_low"], score["band_high"], band_words)))
        if found["same_day"] > 1:
            sentences.append(phrase("sanitary.inspection_several",
                                    count=found["same_day"], date=event.when))
        if found["later"] is not None:
            sentences.append(phrase("sanitary.inspection_later",
                                    when=_when(found["later"])))
    elif found["unscored"] is not None:
        key = ("sanitary.inspection_blank" if found["unscored_fits"]
               else "sanitary.inspection_unreadable")
        sentences.append(phrase(key, when=_when(found["unscored"])))
    elif found["undated"]:
        sentences.append(phrase("sanitary.inspection_undated_only", count=found["undated"]))
    else:
        sentences.append(phrase("sanitary.inspection_none"))
    if found["undated"] and (score is not None or found["unscored"] is not None):
        sentences.append(phrase("sanitary.inspection_undated", count=found["undated"]))

    grade_words = phrase_table("sanitary.grade")
    if micro is None:
        if sampled is not None:
            sentences.append(phrase("sanitary.sample_not_loaded", when=_when(sampled[0])))
        else:
            sentences.append(phrase("sanitary.no_sample"))
    else:
        dated = micro["date"] or phrase("sanitary.undated")
        kind = micro["kind"]
        if kind == "missing":
            sentences.append(phrase("sanitary.ecoli_missing", date=dated))
        elif kind == "counted":
            sentences.append(phrase("sanitary.ecoli_counted", parameter=micro["parameter"],
                                    date=dated, count=micro["count"],
                                    grade=micro["grade_low"],
                                    words=grade_words[micro["grade_low"]]))
        elif kind == "none_found":
            sentences.append(phrase("sanitary.ecoli_none_found",
                                    parameter=micro["parameter"], date=dated,
                                    words=grade_words["A"]))
        elif kind in ("bound", "detected"):
            span = _span(micro["grade_low"], micro["grade_high"],
                         {g: g for g in grades})
            if kind == "detected":
                sentences.append(phrase("sanitary.ecoli_detected",
                                        parameter=micro["parameter"], date=dated,
                                        grades=span))
            else:
                key = ("sanitary.ecoli_at_least" if micro["inclusive"]
                       else "sanitary.ecoli_over")
                sentences.append(phrase(key, parameter=micro["parameter"],
                                        date=dated, bound=micro["bound"], grades=span))
        elif kind == "unit":
            sentences.append(phrase("sanitary.ecoli_unit", parameter=micro["parameter"],
                                    date=dated, unit=micro["unit"]))
        elif micro["reason"]:
            sentences.append(phrase("sanitary.ecoli_ungraded",
                                    parameter=micro["parameter"], date=dated,
                                    reason=micro["reason"]))
        else:
            sentences.append(phrase("sanitary.ecoli_ungraded_bare",
                                    parameter=micro["parameter"], date=dated))
        # a later sample on record is named, so the statement does not pass
        # off an older analysis as the borehole's latest word
        read_on = iso_date(micro["date"])
        if sampled is not None and read_on is not None and sampled[1] > read_on:
            sentences.append(phrase("sanitary.sample_later", when=_when(sampled[0])))

    # the cells the two sides allow: a side not known allows every one
    spec = _form(form) or _form(DEFAULT_FORM)
    assert spec is not None  # the default form is bundled
    n = len(spec["questions"])
    scores = (range(score["low"], score["high"] + 1) if score is not None
              else range(0, n + 1))
    known_grade = micro is not None and micro["grade_low"] is not None
    rows = (grades[grades.index(micro["grade_low"]):grades.index(micro["grade_high"]) + 1]
            if known_grade and micro is not None else grades)
    cells = [spec["matrix"][g][s] for g in rows for s in scores]
    low = min(cells, key=_rank)
    high = max(cells, key=_rank)
    priority_words = phrase_table("sanitary.priority")
    both_known = score is not None and known_grade
    if low == high:
        action = low
        sentences.append(phrase("sanitary.together", priority=priority_words[low]))
    elif both_known:
        action = high
        level = phrase_table("sanitary.priority_level")
        sentences.append(phrase("sanitary.together_range", low=level[low],
                                high=level[high], priority=priority_words[high]))
    else:
        action = None
        if low == PRIORITIES[0]:
            sentences.append(phrase("sanitary.together_unknown"))
        else:
            sentences.append(phrase("sanitary.together_floor",
                                    priority=priority_words[low]))

    verdict = getattr(assessment, "verdict_state", None) if assessment is not None else None
    if verdict:
        sentences.append(phrase("sanitary.verdict", verdict=VERDICT_LONG[verdict]))

    return {
        "inspection": None if event is None else {
            "when": event.when, "by": event.by, "form": event.form,
            "answers": event.answers, "event_id": event.event_id,
            "label": _when(event),
        },
        "score": score,
        "microbiology": micro,
        "sample_event": None if sampled is None else {
            "when": sampled[0].when, "by": sampled[0].by,
            "event_id": sampled[0].event_id, "label": _when(sampled[0]),
        },
        "priority_low": low,
        "priority_high": high,
        "action": action,
        "settled": low == high,
        "statement": " ".join(sentences),
    }

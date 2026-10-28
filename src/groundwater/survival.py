"""How long boreholes keep working (PLAN.md step 7.4).

The asset registry records, for each borehole, an append-only history of
what happened to it. Read across the register, those histories say how long
boreholes keep working after they are commissioned, and whether one kind of
pump, one contractor or one kind of water does better than another. This
module reads them as a time-to-failure analysis.

* **Time zero** is the commissioning date, the first ``commissioned`` record.
  A borehole with none dated on or before the day of the analysis has no time
  to count from and is left out, and the result says how many.
* **The event** is the first failure: the first ``failure`` record, or a
  ``repair`` or ``restored`` record with no failure recorded before it,
  which says the borehole had broken down by that day; such a breakdown is
  dated by the record that mends it, the latest it can have happened. Of
  several records on one day, a failure counts before a mending, a mending
  before a decommissioning, and a decommissioning before a report.
* **Censoring** is the registry's "unknown is not functional" rule written as
  a method. A borehole that has not failed is counted as working up to the
  last report of it working and not after: its commissioning, or a visit
  that would have recorded a failure had it found one (a sanitary or
  routine inspection, or a water sample). A note says nothing either way.
  Not reported since is not taken as working. A borehole decommissioned
  without a failure is censored on that day; one with no report since its
  commissioning is censored at commissioning, and contributes no time.
  Which records count as a failure and which as a report of working are
  choices (QUESTIONS.md item 14).
* **The estimate** is Kaplan and Meier's (1958) of the share still working,
  with Greenwood's (1926) variance and a 95 percent pointwise band on the
  log-log scale (Kalbfleisch and Prentice 1980). There is no band before the
  first failure, where the estimate is 1 and the log-log scale has no width,
  and where the last boreholes at risk all fail the estimate and its band
  close on nought. The median is the first time the estimate falls to one
  half or below, and its band runs from where the band's lower edge does so
  to where its upper edge does (after Brookmeyer and Crowley 1982). A year
  is 365.25 days.
* **Groups** are the pump type and the contractor named on the record, and
  the water's corrosivity the record carries from its design's rising main
  (PLAN.md step 7.2). A group is judged only on at least
  ``survival.min_at_risk`` boreholes followed (``data/defaults.json``);
  below that it says there are too few to judge and gives its counts, never
  a curve. Groups whose records name a value, and have that many, are
  compared by the log-rank test (Mantel 1966); a group whose records name
  none is shown but not compared, since it is not one kind of borehole, and
  a group none of whose boreholes was at risk when any failed adds nothing
  to the test and is left out of it, with one fewer degree of freedom.

The day is an input, never the clock. Several records of one borehole are
read as one, as the service rounds read them. Every public function here has
a twin of the same name in camel case in gwt-core.js, and parity holds them
to one another; the numbers are rounded where they are reported (the share
to four decimals, the chi-squared to four, the p-value to six), so the two
engines' logarithms need not agree to the last bit.
"""

from __future__ import annotations

import math
from datetime import date

from .config import Config, SurvivalConfig
from .registry import Asset, _whole, clean_rising_main, iso_date, merge_events, trim_field
from .reporting.citations import references_for
from .rounds import _fold, _number, _records
from .siting.odds import _log_gamma
from .text import phrase, phrase_table

__all__ = [
    "DAYS_PER_YEAR",
    "ENDS",
    "GROUPINGS",
    "Z_95",
    "at_risk_header",
    "at_risk_rows",
    "borehole_times",
    "chi2_survival",
    "group_value",
    "kaplan_meier",
    "log_rank",
    "survival_analysis",
    "survival_header",
    "survival_rows",
    "survival_text",
]

#: The groupings, in the order the pages show them.
GROUPINGS = ("pump_type", "contractor", "chemistry")

#: The length of a year, in days: the Julian year.
DAYS_PER_YEAR = 365.25

#: The two-sided 95 percent point of the standard normal distribution.
Z_95 = 1.959963984540054

#: The record that is a failure.
_FAILURE = "failure"
#: Records that mend a breakdown: with no failure before them, one had
#: happened by their day.
_MENDING = ("repair", "restored")
#: Records of a visit that found the borehole working, or of its
#: commissioning: a report of working.
_WORKING = ("commissioned", "inspection", "routine_inspection", "water_sample")

#: How a borehole's time ends: by a failure (the first three) or censored.
ENDS = ("failure", "repair", "restored", "decommissioned", "report", "commissioning",
        "no_commissioning")


def _day(as_of) -> date:
    """The day of the analysis: a date (of a datetime, its day), or one
    written YYYY-MM-DD and nothing else, read as ``isoDay`` reads it in the
    browser."""
    day = (date(as_of.year, as_of.month, as_of.day) if isinstance(as_of, date)
           else iso_date(as_of))
    if day is None:
        raise ValueError("survival: the analysis needs the day it is made, as YYYY-MM-DD")
    return day


def _settings(config: Config | None) -> tuple[int, list[float]]:
    """The minimum followed and the times at risk a configuration sets,
    refused, as ``survivalSettings`` refuses them in the browser, unless the
    minimum is a whole number, 1 or more, and the times are a list of
    numbers of years, 0 or more, each larger than the one before."""
    survival = config.survival if config is not None else SurvivalConfig()
    minimum = survival.min_at_risk
    if not _whole(minimum) or minimum < 1:
        raise ValueError("survival: min_at_risk must be a whole number, 1 or more")
    stated = survival.at_risk_years
    years = list(stated) if isinstance(stated, (list, tuple)) else None
    if years is None or any(not _number(value) or value < 0 or (i and value <= years[i - 1])
                            for i, value in enumerate(years)):
        raise ValueError("survival: at_risk_years must be a list of numbers of years, 0 or "
                         "more, each larger than the one before")
    return int(minimum), [float(y) for y in years]


def _text(value) -> str:
    return trim_field(value) if isinstance(value, str) else ""


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


# ------------------------------------------------------------- one borehole

def borehole_times(asset: Asset, as_of) -> dict:
    """One borehole's time from commissioning to its first failure, or to
    the day it is censored, read from its history as of ``as_of``.

    ``start`` and ``end`` are the days (YYYY-MM-DD), ``days`` the time
    between them, ``failed`` whether it ends in a failure, and ``ends`` how
    it ends (:data:`ENDS`). ``before_start`` counts the records dated before
    the commissioning, which are not read, and ``undated`` those whose date
    cannot be read. Records dated after ``as_of`` are not read.
    """
    day = _day(as_of)
    events = merge_events(asset.asset_id, asset.events)
    by_day: dict[date, set[str]] = {}
    undated = 0
    for event in events:
        when = event.date
        if when is None:
            undated += 1
        elif when <= day:
            by_day.setdefault(when, set()).add(event.kind)
    commissioned = [when for when, kinds in by_day.items() if "commissioned" in kinds]
    out = {"asset_id": asset.asset_id, "start": None, "end": None, "days": None,
           "failed": False, "ends": "no_commissioning", "before_start": 0, "undated": undated}
    if not commissioned:
        return out
    start = min(commissioned)
    out["start"] = start.isoformat()
    out["before_start"] = sum(1 for e in events if e.date is not None and e.date < start)
    last, ends, failed = start, "commissioning", False
    for when in sorted(w for w in by_day if w >= start):
        kinds = by_day[when]
        if _FAILURE in kinds:
            last, ends, failed = when, "failure", True
            break
        mended = next((kind for kind in _MENDING if kind in kinds), None)
        if mended is not None:
            last, ends, failed = when, mended, True
            break
        if "decommissioned" in kinds:
            last, ends = when, "decommissioned"
            break
        if when > start and any(kind in kinds for kind in _WORKING):
            last, ends = when, "report"
    out.update(end=last.isoformat(), days=(last - start).days, failed=failed, ends=ends)
    return out


def group_value(asset: Asset, by: str) -> tuple[str, str, bool]:
    """The group ``asset`` falls in by ``by`` (one of :data:`GROUPINGS`): its
    key, its label and whether its record names one. Pump types and
    contractors are matched with A to Z read as a to z and nothing else
    folded, and labelled as the first record of the group spells them."""
    if by == "chemistry":
        rising = clean_rising_main(getattr(asset, "rising_main", None))
        state = rising["chemistry"] if rising is not None else ""
        key = state if state in ("aggressive", "not_aggressive") else "unknown"
        return key, phrase_table("survival.chemistry")[key], key != "unknown"
    if by not in GROUPINGS:
        raise ValueError(f"survival: no grouping by {by!r}")
    name = _text(getattr(asset, "pump_type" if by == "pump_type" else "installed_by", ""))
    if not name:
        return "", phrase("survival.not_recorded"), False
    return _fold(name), name, True


# --------------------------------------------------------------- the maths

def _band(survival: float, total: float) -> tuple[float | None, float | None]:
    """The 95 percent pointwise band on the log-log scale, from the share
    still working and Greenwood's sum: none where the share is 1, nought
    where it is nought."""
    if survival <= 0.0:
        return 0.0, 0.0
    if survival >= 1.0:
        return None, None
    spread = Z_95 * math.sqrt(total) / abs(math.log(survival))
    return survival ** math.exp(spread), survival ** math.exp(-spread)


def _checked(times, where: str) -> list[tuple]:
    """``times`` as (days, failed) pairs; refused, as ``survivalTimes``
    refuses them in the browser, unless each is a mapping whose ``days`` is
    a number, 0 or more, and whose ``failed`` is true or false."""
    out = []
    for t in times:
        days, failed = (t.get("days"), t.get("failed")) if isinstance(t, dict) else (None, None)
        if not _number(days) or days < 0 or not isinstance(failed, bool):
            raise ValueError(f"survival: {where} takes times of days, 0 or more, each with "
                             "whether it failed, true or false")
        out.append((days, failed))
    return out


def _sweep(pairs: list[tuple]) -> list[tuple]:
    """The distinct times of (days, failed) ``pairs`` in order, each with
    the number at risk there (those whose time is that or later), the number
    failed and the number censored."""
    by_day: dict = {}
    for days, failed in pairs:
        counts = by_day.setdefault(days, [0, 0])
        counts[0 if failed else 1] += 1
    out, at_risk = [], len(pairs)
    for day in sorted(by_day):
        failed, censored = by_day[day]
        out.append((day, at_risk, failed, censored))
        at_risk -= failed + censored
    return out


def kaplan_meier(times: list[dict], minimum: int | None = None, years=None) -> dict:
    """The Kaplan-Meier estimate over ``times``, each a ``days`` (0 or more)
    and whether it ``failed`` (true or false).

    A time of nought that is censored contributes nothing and is counted in
    ``n_no_time``; the rest are ``n`` followed, ``n_failed`` and
    ``n_censored``. Only with at least ``minimum`` followed (``judged``)
    are the ``steps`` (one a distinct time: the number at risk, failed and
    censored there, the share still working, Greenwood's standard error and
    the band), the ``median`` (its days and its band's, each None where not
    reached) and ``at_times`` (at each of ``years``: the number at risk and
    the share still working with its band, the share None past the last
    time followed) given; below it they are empty and None. ``minimum`` and
    ``years`` default to the ``survival`` section of ``data/defaults.json``.
    """
    if minimum is None or years is None:
        least, stated = _settings(None)
        minimum = least if minimum is None else minimum
        years = stated if years is None else years
    followed = [(days, failed) for days, failed in _checked(times, "kaplan_meier")
                if failed or days > 0]
    n_failed = sum(1 for _, failed in followed if failed)
    out = {
        "n": len(followed),
        "n_failed": n_failed,
        "n_censored": len(followed) - n_failed,
        "n_no_time": len(times) - len(followed),
        "judged": len(followed) >= minimum,
        "last_days": max((days for days, _ in followed), default=None),
        "steps": [],
        "median": None,
        "at_times": [],
    }
    if not out["judged"]:
        return out
    survival, total = 1.0, 0.0
    raw = []
    for day, at_risk, failed, censored in _sweep(followed):
        if failed:
            if failed < at_risk:
                survival *= (at_risk - failed) / at_risk
                total += failed / (at_risk * (at_risk - failed))
            else:
                survival = 0.0
        lower, upper = _band(survival, total)
        raw.append({"days": day, "at_risk": at_risk, "failed": failed, "censored": censored,
                    "survival": survival, "se": survival * math.sqrt(total),
                    "lower": lower, "upper": upper})
    out["steps"] = [{**step, "survival": round(step["survival"], 4), "se": round(step["se"], 4),
                     "lower": _round(step["lower"], 4), "upper": _round(step["upper"], 4)}
                    for step in raw]

    def first(key: str):
        return next((s["days"] for s in raw if s[key] is not None and s[key] <= 0.5), None)

    out["median"] = {"days": first("survival"), "lower": first("lower"), "upper": first("upper")}
    for year in years:
        threshold = year * DAYS_PER_YEAR
        at_risk = sum(1 for days, _ in followed if days >= threshold)
        entry = {"years": year, "at_risk": at_risk, "survival": None, "lower": None,
                 "upper": None}
        if threshold <= out["last_days"]:
            before = [s for s in raw if s["days"] <= threshold]
            step = before[-1] if before else None
            entry.update(survival=round(step["survival"], 4) if step else 1.0,
                         lower=_round(step["lower"], 4) if step else None,
                         upper=_round(step["upper"], 4) if step else None)
        out["at_times"].append(entry)
    return out


def _gamma_q(a: float, x: float) -> float:
    """The regularised upper incomplete gamma function Q(a, x): by its series
    below a + 1 and its continued fraction (by the modified Lentz method)
    above, as gammaQ evaluates it in the browser."""
    if x <= 0.0:
        return 1.0
    front = math.exp(-x + a * math.log(x) - _log_gamma(a))
    if x < a + 1.0:
        term = total = 1.0 / a
        ap = a
        for _ in range(1000):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return max(0.0, 1.0 - total * front)
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        d = 1.0 / (d if abs(d) >= tiny else tiny)
        c = b + an / c
        c = c if abs(c) >= tiny else tiny
        step = d * c
        h *= step
        if abs(step - 1.0) < 1e-15:
            break
    return front * h


def chi2_survival(x: float, df: int) -> float:
    """The chance a chi-squared on ``df`` degrees of freedom is at least
    ``x``."""
    if not _whole(df) or df < 1:
        raise ValueError("survival: a chi-squared needs a whole number of degrees of freedom")
    return _gamma_q(df / 2.0, x / 2.0)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """``matrix`` x = ``vector`` by Gaussian elimination with partial pivoting
    (the first of equal pivots), or None where a pivot is under 1e-10 of the
    largest diagonal entry."""
    m = len(vector)
    rows = [list(matrix[i][:m]) + [vector[i]] for i in range(m)]
    scale = max(abs(rows[i][i]) for i in range(m))
    if not scale > 0.0:
        return None
    for col in range(m):
        pivot = col
        for r in range(col + 1, m):
            if abs(rows[r][col]) > abs(rows[pivot][col]):
                pivot = r
        if abs(rows[pivot][col]) <= 1e-10 * scale:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(col + 1, m):
            factor = rows[r][col] / rows[col][col]
            for c in range(col, m + 1):
                rows[r][c] -= factor * rows[col][c]
    x = [0.0] * m
    for r in range(m - 1, -1, -1):
        total = rows[r][m]
        for c in range(r + 1, m):
            total -= rows[r][c] * x[c]
        x[r] = total / rows[r][r]
    return x


def log_rank(groups: list[list[dict]]) -> dict:
    """The log-rank test across ``groups``, each a list of ``days`` (0 or
    more) and whether it ``failed`` (true or false): followed boreholes only.

    Gives the failures ``observed`` in each group and those ``expected``
    were they all failing at the same rate. A group none of whose members
    was at risk when any failed adds nothing to the test (its observed and
    expected are both nought) and is left out of it: its index is in
    ``not_at_risk``, and the ``chi2`` is on ``df``, one fewer than the
    groups left in, with its ``p``. Where there is nothing to compare the
    three are None and the ``reason`` says why: ``no_failures``,
    ``one_at_risk`` (whenever one failed, all at risk were of one group) or
    ``singular`` (the groups left in were not at risk together at enough of
    the failures for the test to be computed).
    """
    k = len(groups)
    if k < 2:
        raise ValueError("survival: a log-rank test needs two groups or more")
    pairs = [_checked(g, "log_rank") for g in groups]
    observed = [sum(1 for _, failed in g if failed) for g in pairs]
    out: dict = {"observed": observed, "expected": None, "not_at_risk": [], "df": None,
                 "chi2": None, "p": None, "reason": None}
    if not sum(observed):
        out["reason"] = "no_failures"
        return out
    # every group's times together, swept in order: at each time, the number
    # still at risk in each group, then those that leave the risk set there
    by_day: dict = {}
    for i, g in enumerate(pairs):
        for days, failed in g:
            counts = by_day.setdefault(days, [[0, 0] for _ in range(k)])
            counts[i][0 if failed else 1] += 1
    at_risk = [len(g) for g in pairs]
    expected = [0.0] * k
    var = [[0.0] * k for _ in range(k)]
    seen = [False] * k
    for day in sorted(by_day):
        counts = by_day[day]
        d = sum(c[0] for c in counts)
        if d:
            n = sum(at_risk)
            for i in range(k):
                expected[i] += d * at_risk[i] / n
                seen[i] = seen[i] or at_risk[i] > 0
            if n > 1:
                factor = d * (n - d) / (n - 1)
                for i in range(k):
                    for j in range(k):
                        delta = n if i == j else 0
                        var[i][j] += factor * at_risk[i] * (delta - at_risk[j]) / (n * n)
        for i in range(k):
            at_risk[i] -= counts[i][0] + counts[i][1]
    out["expected"] = [round(e, 4) for e in expected]
    kept = [i for i in range(k) if seen[i]]
    out["not_at_risk"] = [i for i in range(k) if not seen[i]]
    if len(kept) < 2:
        out["reason"] = "one_at_risk"
        return out
    m = len(kept) - 1
    diff = [observed[kept[i]] - expected[kept[i]] for i in range(m)]
    solved = _solve([[var[kept[i]][kept[j]] for j in range(m)] for i in range(m)], diff)
    if solved is None:
        out["reason"] = "singular"
        return out
    chi2 = 0.0
    for i in range(m):
        chi2 += diff[i] * solved[i]
    chi2 = max(chi2, 0.0)
    out.update(df=m, chi2=round(chi2, 4), p=round(chi2_survival(chi2, m), 6))
    return out


# ------------------------------------------------------------ the register

def _code_points(text: str) -> list[int]:
    return [ord(c) for c in text]


def _analysis(key: str, label: str, recorded: bool, rows: list[dict], minimum: int,
              years: list[float]) -> dict:
    """One group's estimate, with its counts."""
    started = [r for r in rows if r["days"] is not None]
    km = kaplan_meier([{"days": r["days"], "failed": r["failed"]} for r in started],
                      minimum, years)
    return {"key": key, "label": label, "recorded": recorded, "n_boreholes": len(rows),
            "n_no_start": len(rows) - len(started), **km}


def survival_analysis(assets, as_of, config: Config | None = None) -> dict:
    """How long the boreholes of a register keep working, as of ``as_of``.

    ``assets`` are registry assets (or their saved records), several records
    of one borehole read as one; ``as_of`` is a date or a day written
    YYYY-MM-DD, never read off the clock; ``config`` gives the minimum
    followed and the times at risk (its ``survival`` section).

    The result carries each borehole's time (``boreholes``, as
    :func:`borehole_times` gives it, with its groups), the estimate over
    them all (``overall``), and for each of :data:`GROUPINGS` the groups
    (those that name a value first, the most boreholes first and then by
    label letter by letter, then the one that names none), each as
    :func:`kaplan_meier` gives it with its key, label and counts, and the
    ``comparison`` across the groups that name a value and are judged.
    """
    day = _day(as_of)
    minimum, years = _settings(config)
    records, repeated, unreadable = _records(assets)
    rows = []
    for asset in records:
        row = borehole_times(asset, day)
        row["groups"] = {}
        for by in GROUPINGS:
            key, label, recorded = group_value(asset, by)
            row["groups"][by] = {"key": key, "label": label, "recorded": recorded}
        rows.append(row)
    groupings = []
    for by in GROUPINGS:
        members: dict[tuple[bool, str], list[dict]] = {}
        labels: dict[tuple[bool, str], str] = {}
        for row in rows:
            group = row["groups"][by]
            ident = (group["recorded"], group["key"])
            members.setdefault(ident, []).append(row)
            labels.setdefault(ident, group["label"])
        groups = [_analysis(ident[1], labels[ident], ident[0], members[ident], minimum, years)
                  for ident in members]
        groups.sort(key=lambda g: (not g["recorded"], -g["n_boreholes"], _code_points(g["label"])))
        compared = [g for g in groups if g["recorded"] and g["judged"]]
        comparison: dict = {"groups": [g["label"] for g in compared],
                            "left_out": [g["label"] for g in groups
                                         if not (g["recorded"] and g["judged"])]}
        if len(compared) < 2:
            comparison.update(observed=None, expected=None, not_at_risk=[], df=None, chi2=None,
                              p=None, reason="fewer_than_two")
        else:
            comparison.update(log_rank([
                [{"days": r["days"], "failed": r["failed"]}
                 for r in members[(True, g["key"])]
                 if r["days"] is not None and (r["failed"] or r["days"] > 0)]
                for g in compared]))
            comparison["not_at_risk"] = [compared[i]["label"]
                                         for i in comparison["not_at_risk"]]
        groupings.append({"by": by, "groups": groups, "comparison": comparison})
    overall = _analysis("all", phrase("survival.all"), True, rows, minimum, years)
    return {
        "as_of": day.isoformat(),
        "min_at_risk": minimum,
        "at_risk_years": years,
        "n_boreholes": len(rows),
        "n_merged": repeated,
        "n_unreadable": unreadable,
        "n_by_mending": sum(1 for r in rows if r["ends"] in _MENDING),
        "n_before_start": sum(1 for r in rows if r["before_start"]),
        "n_undated": sum(1 for r in rows if r["undated"]),
        "boreholes": rows,
        "overall": overall,
        "groupings": groupings,
    }


# -------------------------------------------------------------- the words

def _years(days: int) -> float:
    return days / DAYS_PER_YEAR


def _list(labels: list[str]) -> str:
    """Labels as a list in words: "A", "A and B", "A, B and C"."""
    if len(labels) == 1:
        return labels[0]
    return phrase("survival.list_and", first=", ".join(labels[:-1]), last=labels[-1])


def _median_text(group: dict) -> str:
    median = group["median"]
    if median["days"] is None:
        return phrase("survival.median_none", years=_years(group["last_days"]))
    if median["upper"] is None:
        return phrase("survival.median_open", years=_years(median["days"]),
                      lower=_years(median["lower"]))
    return phrase("survival.median", years=_years(median["days"]),
                  lower=_years(median["lower"]), upper=_years(median["upper"]))


def _group_line(group: dict, minimum: int) -> str:
    if not group["judged"]:
        return phrase("survival.too_few", label=group["label"], n=group["n"], minimum=minimum,
                      failed=group["n_failed"], censored=group["n_censored"])
    return phrase("survival.group_line", label=group["label"], n=group["n"],
                  failed=group["n_failed"], censored=group["n_censored"],
                  median=_median_text(group))


def _comparison_text(comparison: dict, minimum: int) -> list[str]:
    out = []
    reason = comparison["reason"]
    if reason == "fewer_than_two":
        out.append(phrase("survival.compare_few", minimum=minimum))
    elif reason == "no_failures":
        out.append(phrase("survival.compare_no_failures"))
    elif reason == "one_at_risk":
        out.append(phrase("survival.compare_one_at_risk"))
    elif reason == "singular":
        out.append(phrase("survival.compare_singular"))
    else:
        named = _list([label for label in comparison["groups"]
                       if label not in comparison["not_at_risk"]])
        if comparison["p"] < 0.001:
            out.append(phrase("survival.compared_small", groups=named, chi2=comparison["chi2"],
                              df=comparison["df"]))
        else:
            out.append(phrase("survival.compared", groups=named, chi2=comparison["chi2"],
                              df=comparison["df"], p=comparison["p"]))
        out.append(phrase("survival.p_meaning"))
        if comparison["not_at_risk"]:
            out.append(phrase("survival.not_at_risk",
                              groups=_list(comparison["not_at_risk"])))
    if comparison["left_out"] and reason != "fewer_than_two":
        out.append(phrase("survival.left_out", groups=_list(comparison["left_out"])))
    return out


def survival_text(result: dict) -> dict:
    """What the analysis says: ``summary`` (the headline and the counts
    beside it), ``method`` (how the estimate, its band, the median and the
    comparison are made, and the minimum as a choice), ``overall`` and, for
    each grouping, its ``heading``, ``intro``, a line a group and the
    ``comparison``; and the works the method cites (``references``)."""
    minimum = result["min_at_risk"]
    overall = result["overall"]
    summary: list[str] = []
    total = result["n_boreholes"]
    if not total:
        summary.append(phrase("survival.empty"))
    elif overall["n"]:
        summary.append(phrase("survival.headline", date=result["as_of"], total=total,
                              followed=overall["n"], failed=overall["n_failed"],
                              censored=overall["n_censored"]))
    else:
        summary.append(phrase("survival.none_followed", date=result["as_of"], total=total))
    if overall["n_no_time"]:
        summary.append(phrase("survival.no_time", count=overall["n_no_time"]))
    if overall["n_no_start"]:
        summary.append(phrase("survival.no_start", count=overall["n_no_start"]))
    if result["n_by_mending"]:
        summary.append(phrase("survival.by_mending", count=result["n_by_mending"]))
    if result["n_before_start"]:
        summary.append(phrase("survival.before_start", count=result["n_before_start"]))
    if result["n_undated"]:
        summary.append(phrase("survival.undated", count=result["n_undated"]))
    if result["n_merged"]:
        summary.append(phrase("rounds.merged", count=result["n_merged"]))
    if result["n_unreadable"]:
        summary.append(phrase("rounds.unreadable", count=result["n_unreadable"]))
    by_words = phrase_table("survival.by")
    intros = phrase_table("survival.by_intro")
    return {
        "summary": summary,
        "method": [phrase("survival.method"), phrase("survival.minimum", minimum=minimum),
                   phrase("survival.comparison_method")],
        "overall": {"heading": phrase("survival.all"), "lines": [_group_line(overall, minimum)]},
        "groupings": [{"by": g["by"],
                       "heading": phrase("survival.by_heading", by=by_words[g["by"]]),
                       "intro": intros[g["by"]],
                       "lines": [_group_line(group, minimum) for group in g["groups"]],
                       "comparison": _comparison_text(g["comparison"], minimum)}
                      for g in result["groupings"]],
        "references": references_for("survival"),
    }


def survival_header() -> list[str]:
    """The labels of a grouping's table, in order."""
    return list(phrase_table("survival.columns").values())


def survival_rows(groups: list[dict]) -> list[list[str]]:
    """Groups (a grouping's, or ``[overall]``) as the rows of its table: the
    counts, and the median and its band in years, or, below the minimum,
    that there are too few to judge."""
    out = []
    for group in groups:
        counts = [group["label"], str(group["n_boreholes"]), str(group["n"]),
                  str(group["n_failed"]), str(group["n_censored"])]
        if not group["judged"]:
            out.append(counts + [phrase("survival.too_few_cell"), ""])
            continue
        median = group["median"]
        if median["days"] is None:
            out.append(counts + [phrase("survival.not_reached"), ""])
            continue
        upper = (phrase("survival.not_reached") if median["upper"] is None
                 else phrase("survival.years_cell", years=_years(median["upper"])))
        out.append(counts + [phrase("survival.years_cell", years=_years(median["days"])),
                             phrase("survival.band_cell",
                                    lower=phrase("survival.years_cell",
                                                 years=_years(median["lower"])),
                                    upper=upper)])
    return out


def at_risk_header(result: dict) -> list[str]:
    """The labels of the table of numbers at risk: the group, then each
    stated time."""
    return [phrase("survival.at_risk_group")] + [
        phrase("survival.at_risk_year", years=year) for year in result["at_risk_years"]]


def at_risk_rows(groups: list[dict]) -> list[list[str]]:
    """The judged groups' numbers at risk and shares still working at each
    stated time, a row a group."""
    out = []
    for group in groups:
        if not group["judged"]:
            continue
        cells = [group["label"]]
        for entry in group["at_times"]:
            if entry["survival"] is None:
                cells.append(phrase("survival.at_risk_beyond", n=entry["at_risk"]))
            elif entry["lower"] is None:
                cells.append(phrase("survival.at_risk_whole", n=entry["at_risk"],
                                    pct=100.0 * entry["survival"]))
            else:
                cells.append(phrase("survival.at_risk_cell", n=entry["at_risk"],
                                    pct=100.0 * entry["survival"],
                                    lower=100.0 * entry["lower"],
                                    upper=100.0 * entry["upper"]))
        out.append(cells)
    return out

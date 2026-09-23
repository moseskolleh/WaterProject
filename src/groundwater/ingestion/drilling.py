"""Parser for drilling log sheets (Excel template and WiNGiN style tables)."""

from __future__ import annotations

import datetime
from pathlib import Path

import re

from ..models import DataFlag, DrillingLog, LithologyInterval
from ..utils import clean_text, parse_depth_interval, parse_number, plural
from . import common

_SCREEN_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)")

# A clock time carries a colon or an "h" between the hour and the minutes
# ("14:30", "14h30"). A decimal point is deliberately not a clock separator
# here: "8.50" in a strike note is a depth far more often than it is ten to
# nine, and reading it as a time would lose the strike.
#
# A driller also writes the hour with no separator at all and the word after
# it instead ("1430 hrs"), and that form reached the depth reader untouched:
# a 30 m borehole was handed over recording a water strike at 1430 m
# (ROADMAP data-ingestion-9, the same clock read as a depth as "14:30" was).
# Three or four digits carrying "hrs" or "hours" are a time of day and never
# a depth in metres, so they are removed with the other clock forms; a bare
# "2 hrs" is an elapsed time and too short to be a clock, so it is left
# alone, and no number that carries a metre unit is touched either way.
#
# A clock time is written with no space inside it. "Water strike 1: 12 m,
# water strike 2: 30 m" numbers its strikes with a colon and a space, and a
# pattern that allowed the space took "1: 12" and "2: 30" for times and
# recorded no strike at all, without a flag.
_CLOCK_TIME_RE = re.compile(
    r"\b\d{1,2}[:h]\d{2}\b(?:\s*(?:am|pm|hrs?))?"
    r"|\b\d{3,4}\s*(?:hrs?|hours?)\b",
    re.IGNORECASE,
)

# A water level written beside a strike ("Water strike at 18 m; rest water
# level 4.5 m") is not a strike. Its number was read as one, so the log
# recorded strikes at 4.5 m and 18 m and the design basis explained why the
# 4.5 m strike was not screened.
_WATER_LEVEL_RE = re.compile(
    r"\b(?:s\.?w\.?l|r\.?w\.?l|(?:rest(?:ing)?|static|standing)\s+(?:water\s+)?level"
    r"|water\s+level)\b\.?[^\d;,.]*?\d+(?:[.,]\d+)?\s*(?:met(?:re|er)s?\b|m\b)?",
    re.IGNORECASE,
)

# One depth, or a list of them sharing the unit written after the last
# ("12, 18 and 30 m"), in metres. The lookahead keeps the "m" of a rate
# ("0.5 m/min") from reading as a depth in metres.
_DEPTH_LIST_RE = re.compile(
    # A slash is not a list separator here. "1/2 m" is half a metre and
    # "12/30" is as likely a date as a pair, and both used to come out as
    # two strikes - which is the invention this parser exists to stop.
    r"(?:\d+(?:[.,]\d+)?\s*(?:,|&|\+|and\b)\s*)*"
    r"\d+(?:[.,]\d+)?\s*(?:met(?:re|er)s?|m)\b(?!\s*/)",
    re.IGNORECASE,
)

_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)?")

# The unit a diameter cell carries, if it carries one at all. Bit sizes are
# quoted in halves and eighths of an inch, so the number may be a whole and a
# fraction ("6 1/2 in"); the lookbehind keeps the denominator of that fraction
# from being read as the diameter on its own.
_DIAMETER_UNIT_RE = re.compile(
    r"(?<![\d./,])(?P<number>\d+(?:[.,]\d+)?)"
    r"(?:\s*(?P<numerator>\d+)\s*/\s*(?P<denominator>\d+))?\s*"
    # The abbreviations take a plural on a field sheet as readily as the
    # spelled-out words do. "165 mms" fell past an "mm" that could not end in
    # an s, and a metric bit was recorded as a 165 inch hole exactly as
    # "165 mm" was before this parser existed (ROADMAP data-ingestion-15) -
    # and that diameter is what sizes the casing and the gravel pack.
    r"(?P<unit>millimet(?:re|er)s?|mms?|centimet(?:re|er)s?|cms?"
    r"|inch(?:es)?|in|''|\"|”|″)(?![a-z])",
    re.IGNORECASE,
)

# The unit a penetration rate cell carries: metres per minute or hour, or the
# time per metre a driller times with a stopwatch and writes the other way up.
# The metre is written out as often as it is abbreviated, and the hour takes
# a plural: "30 metres/hour" and "30 m/hrs" carry their unit as plainly as
# "30 m/hr" does, but neither was matched, so both fell through to the bare
# number and were recorded as thirty metres a minute - sixty times too fast,
# which is the defect this parser was written to close (ROADMAP
# data-ingestion-15). The longer spelling is listed before the shorter one in
# each pair so "metres" is not read as an "m" followed by rubbish.
_METRE = r"(?:met(?:re|er)s?|m)"
_RATE_UNITS = (
    _METRE + r"\s*(?:/|per)\s*min(?:ute)?s?"
    r"|" + _METRE + r"\s*(?:/|per)\s*(?:hrs?|hours?|h)"
    r"|min(?:ute)?s?\s*(?:/|per)\s*" + _METRE +
    r"|sec(?:ond)?s?\s*(?:/|per)\s*" + _METRE +
    r"|s\s*(?:/|per)\s*" + _METRE
)
_RATE_UNIT_RE = re.compile(
    r"(?<![\d./,])(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>" + _RATE_UNITS + r")(?![a-z])",
    re.IGNORECASE,
)

# The unit a column header gives its cells: "Penetration rate (min/m)", "Bit
# diameter (mm)". A bare number in the cell is in that unit. The column was
# read in the template's units whatever its header said, so 165 under "Bit
# diameter (mm)" was a 165 inch hole (a 2 m annulus and 1654 bags of cement
# in the bill of quantities) and 4 under "(min/m)" was 4 m/min.
_RATE_HEADER_RE = re.compile(r"(?:" + _RATE_UNITS + r")(?![a-z])", re.IGNORECASE)
_METRIC_HEADER_RE = re.compile(
    r"\b(millimet(?:re|er)s?|mms?|centimet(?:re|er)s?|cms?)\b", re.IGNORECASE,
)

# A whole number and a fraction of an inch with no unit ("6 1/2"), which is
# how a bit is quoted.
_MIXED_NUMBER_RE = re.compile(
    r"(?<![\d./,])(?P<number>\d+(?:[.,]\d+)?)\s+(?P<numerator>\d+)\s*/\s*(?P<denominator>\d+)"
)

# "8½" and "8-1/2" are how a bit size is stamped and typed; both used to
# be read as 8 inches. The fraction is written out and the hyphen dropped, so
# they reach the patterns above as "8 1/2".
_VULGAR_FRACTIONS = {"\u00bd": "1/2", "\u00bc": "1/4", "\u00be": "3/4", "\u215b": "1/8",
                     "\u215c": "3/8", "\u215d": "5/8", "\u215e": "7/8"}
_VULGAR_RE = re.compile("[" + "".join(_VULGAR_FRACTIONS) + "]")
_HYPHENATED_FRACTION_RE = re.compile(r"(\d)\s*-\s*(?=\d+\s*/\s*\d)")

#: No water well is drilled wider than this, in inches: a larger reading is a
#: bit size in millimetres with its unit left off.
MAX_BIT_DIAMETER_IN = 36.0


#: Two numbers with a slash between them: a fraction, a date, or a run
#: number, none of which is a depth.
_FRACTION_RE = re.compile(r"\d\s*/\s*\d")


def parse_water_strike_depths(value) -> tuple[list[float], str]:
    """Read the strike depths a cell names, in metres.

    Returns ``(depths, reason)``: the depths the cell can be read to name,
    or an empty list and the reason it cannot be read confidently, which the
    caller raises as a flag. Recording nothing and saying so is the right
    answer here, because a strike depth places the screens.

    A strike cell used to be read as the last number after the last colon,
    so "Water strike: 8 m at 14:30" recorded a 30 m strike - the minutes of
    the clock time - "at 12 m and 30 m" recorded only 12 m, and a 0 typed in
    the strike column to mean "no water on this row" recorded a strike at the
    surface, which then seeded a 0-5 m screen against the topsoil (ROADMAP
    data-ingestion-9). Clock times are removed before any number is read, a
    number that carries a metre unit is a depth, and a zero is an empty cell.

    >>> parse_water_strike_depths("Water strike: 8 m at 14:30")
    ([8.0], '')
    >>> parse_water_strike_depths("Water strikes at 12 m and 30 m")
    ([12.0, 30.0], '')
    >>> parse_water_strike_depths(0)
    ([], '')
    """
    if value is None:
        return [], ""
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        # Excel hands a cell typed as a time back as a datetime, and reading
        # it as a number recorded the year as a strike depth. A cell typed
        # as a time of day alone comes back as a time, which was read as
        # "14:30:00" and dropped without the flag the browser raises.
        return [], "the cell holds a date or a time rather than a depth"
    if isinstance(value, bool):
        return [], ""
    if isinstance(value, (int, float)):
        return ([float(value)] if value > 0 else []), ""

    # A water level and a clock time are taken out before any number is
    # read, and counted: a cell whose only numbers were those names no
    # strike, and says so rather than recording nothing in silence.
    text, levels = _WATER_LEVEL_RE.subn(" ", clean_text(value))
    text, clocks = _CLOCK_TIME_RE.subn(" ", text)
    # A fraction between two digits is half a metre, or a date, or a run
    # number; it is not two depths and it is not its own denominator.
    # "Water strike 1/2 m" read as a strike at 2 m, which would place a
    # screen. Refusing it and saying so is the only honest answer.
    if _FRACTION_RE.search(text):
        return [], "it writes a fraction or a date, which names no single depth"
    depths: list[float] = []
    for match in _DEPTH_LIST_RE.finditer(text):
        for token in _NUMBER_TOKEN_RE.findall(match.group(0)):
            depth = parse_number(token)
            if depth is not None and depth > 0:
                depths.append(depth)
    if depths:
        return depths, ""

    # No number carries a unit. A single number is the depth the note is
    # about ("First water strike: 12"); several are a sentence this parser
    # cannot take apart, and guessing one of them is worse than refusing.
    numbers = _NUMBER_TOKEN_RE.findall(text)
    if not numbers:
        named = [what for what, count in (("a water level", levels), ("a clock time", clocks))
                 if count]
        if named:
            return [], "it names " + " and ".join(named) + " but no strike depth"
        return [], ""
    if len(numbers) > 1:
        return [], "it names several numbers and none of them carries a unit"
    depth = parse_number(numbers[0])
    if depth is None or depth <= 0:
        return [], ""
    return [depth], ""


def _unreadable_strike_flag(text: str, reason: str) -> DataFlag:
    """The flag raised for a strike cell that cannot be read as a depth.

    Refusing the cell costs the log a strike, so the flag names the cell it
    refused, why it refused it, and the wording that would have read.
    """
    return DataFlag(
        "warning",
        "water_strike_unreadable",
        f'Water strike cell "{text}" was not read as a depth: {reason}. '
        "No strike was recorded from it; write each depth with its unit, as "
        '"water strike at 12 m and 30 m".',
    )


def _fractions_written_out(text: str) -> str:
    text = _VULGAR_RE.sub(lambda m: " " + _VULGAR_FRACTIONS[m.group(0)], text)
    return _HYPHENATED_FRACTION_RE.sub(r"\1 ", text)


def _inches(number: float | None, unit: str | None) -> float | None:
    """A diameter in ``unit`` (the cell's or the header's) in inches."""
    if number is None or not unit:
        return number
    unit = unit.lower()
    if unit.startswith(("mm", "millim")):
        return round(number / 25.4, 2)
    if unit.startswith(("cm", "centim")):
        return round(number / 2.54, 2)
    return number


def header_diameter_unit(header) -> str | None:
    """The metric unit a diameter column header names, or ``None`` for inches."""
    match = _METRIC_HEADER_RE.search(clean_text(header))
    return match.group(1).lower() if match else None


def header_rate_unit(header) -> str | None:
    """The penetration rate unit a column header names, if it names one."""
    match = _RATE_HEADER_RE.search(clean_text(header))
    return match.group(0) if match else None


def parse_bit_diameter_in(value, unit: str | None = None) -> float | None:
    """The drilled diameter in inches, converting the unit the cell carries.

    Crews quote a bit in millimetres as often as in inches, and the column
    was read as a bare number, so "165 mm" was recorded as a 165 inch hole
    (ROADMAP data-ingestion-15) - a metre and a half of annulus in the bill
    of quantities and in the completion drawing. A cell with no unit is in
    ``unit``, the unit its column header names; with none, inches, which is
    the unit the template column asks for ("Drilling diameter (in)") and the
    unit the design rules are written in.

    A converted diameter is kept to two decimals: 165 mm is the metric name
    of a 6.5 in bit, and 6.5 in is what the completion log should print.

    >>> parse_bit_diameter_in("165 mm")
    6.5
    >>> parse_bit_diameter_in('6 1/2"')
    6.5
    >>> parse_bit_diameter_in(6.5)
    6.5
    >>> parse_bit_diameter_in("8½")
    8.5
    >>> parse_bit_diameter_in(165, unit="mm")
    6.5
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _inches(float(value), unit)
    text = _fractions_written_out(clean_text(value))
    match = _DIAMETER_UNIT_RE.search(text)
    if match is None:
        mixed = _MIXED_NUMBER_RE.search(text)
        if mixed is None:
            return _inches(parse_number(text), unit)
        number = parse_number(mixed.group("number"))
        if number is not None and float(mixed.group("denominator")) != 0:
            number += float(mixed.group("numerator")) / float(mixed.group("denominator"))
        return _inches(number, unit)
    number = parse_number(match.group("number"))
    if number is None:
        return None
    if match.group("numerator") and float(match.group("denominator")) != 0:
        # "6 1/2 in" is six and a half inches, which is how a bit is quoted.
        number += float(match.group("numerator")) / float(match.group("denominator"))
    return _inches(number, match.group("unit"))


def _rate_in_m_per_min(number: float | None, unit: str | None) -> float | None:
    """A penetration rate in ``unit`` (the cell's or the header's) in m/min."""
    if number is None or not unit:
        return number
    unit = re.sub(r"\s+", "", unit).lower().replace("per", "/")
    if unit.startswith("min"):
        # minutes per metre: the reciprocal, and a zero is not a rate at all
        return 1.0 / number if number > 0 else None
    if unit.startswith("s"):
        # seconds per metre
        return 60.0 / number if number > 0 else None
    if "/h" in unit:
        return number / 60.0
    return number


def parse_penetration_rate_m_per_min(value, unit: str | None = None) -> float | None:
    """The penetration rate in metres per minute, whichever way up it is written.

    A driller times a rod with a stopwatch and writes what the watch says, so
    the cell carries "5 min/m" as readily as "0.2 m/min" and a rig sheet
    quotes metres per hour. The column was read as a bare number, so a hole
    advancing at five minutes to the metre was recorded as five metres a
    minute (ROADMAP data-ingestion-15), twenty-five times too fast. A cell
    with no unit is in ``unit``, the unit its column header names; with
    none, metres per minute, which is the unit the template column asks for
    ("Penetration rate (m/min)").

    >>> parse_penetration_rate_m_per_min("5 min/m")
    0.2
    >>> parse_penetration_rate_m_per_min(0.33)
    0.33
    >>> parse_penetration_rate_m_per_min(4, unit="min/m")
    0.25
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _rate_in_m_per_min(float(value), unit)
    text = clean_text(value)
    match = _RATE_UNIT_RE.search(text)
    if match is None:
        return _rate_in_m_per_min(parse_number(text), unit)
    number = parse_number(match.group("number"))
    if number is None:
        return None
    return _rate_in_m_per_min(number, match.group("unit"))


def parse_installed_screens(value) -> list[tuple[float, float]]:
    """``"25-35; 48-53 m"`` -> ``[(25.0, 35.0), (48.0, 53.0)]``.

    The as-built screens a crew writes on the sheet, as ranges separated by
    anything. A cell with no range in it records no screens. The dashes are
    normalised first so a range typed with an en or em dash is read as the
    range it is rather than dropped (ROADMAP data-ingestion-8).
    """
    text = common.normalise_dashes(clean_text(value))
    out = []
    for match in _SCREEN_RANGE_RE.finditer(text):
        top, bottom = float(match.group(1)), float(match.group(2))
        if bottom < top:
            top, bottom = bottom, top
        if bottom > top:
            out.append((top, bottom))
    return sorted(out)


def _reads_as_interval(value) -> bool:
    """Whether a cell in the interval column was meant as a depth interval.

    A cell of numbers and separators with nothing else in it ("30 -", "30
    40") is a row the crew logged and this parser could not read, and it is
    flagged. A note under the table ("Water strike 1: 18 m") has words in it
    and is not a row at all.
    """
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    text = common.strip_metre_units(common.normalise_dashes(clean_text(value)))
    text = re.sub(r"\b(?:to|from)\b", " ", text, flags=re.IGNORECASE)
    return bool(re.search(r"\d", text)) and not re.search(r"[a-z]", text, re.IGNORECASE)


def _find_log_header(grid: list[list]) -> tuple[int, dict] | None:
    """Locate the drilling table header row and map its columns."""
    for r, row in enumerate(grid):
        texts = common.row_text(row)
        cols: dict[str, int] = {}
        for c, t in enumerate(texts):
            if not t:
                continue
            if ("depth" in t and "interval" in t) or t.startswith("depth /"):
                cols["interval"] = c
            elif t.startswith("depth") and "interval" not in cols:
                cols.setdefault("interval", c)
            elif t.startswith("from"):
                cols.setdefault("from_time", c)
            elif t.startswith("to"):
                cols.setdefault("to_time", c)
            elif "penetration" in t:
                cols["rate"] = c
            elif "sample" in t or "litholog" in t or "description" in t:
                cols.setdefault("description", c)
            elif "diameter" in t or "bit" in t:
                cols.setdefault("diameter", c)
            elif "strike" in t:
                cols["strike"] = c
        if "interval" in cols:
            return r, cols
    return None


def read_drilling_workbook(path: str | Path) -> DrillingLog:
    grid, _ = common.load_grid(path)
    return drilling_from_grid(grid, source=str(path))


def drilling_from_grid(grid: list[list], source: str = "") -> DrillingLog:
    fields = common.extract_header_fields(grid, max_rows=len(grid))
    site = common.site_from_fields(fields, source=source)
    flags: list[DataFlag] = []

    located = _find_log_header(grid)
    intervals: list[LithologyInterval] = []
    strikes: list[float] = []
    zero_strike_rows = 0
    too_wide: list[str] = []
    if located is not None:
        header_row, cols = located

        def header(key):
            c = cols.get(key)
            row = grid[header_row]
            return row[c] if c is not None and c < len(row) else None

        # the unit the column header names is the unit of a bare number
        rate_unit = header_rate_unit(header("rate"))
        diameter_unit = header_diameter_unit(header("diameter"))
        for row in grid[header_row + 1 :]:
            def cell(key):
                c = cols.get(key)
                return row[c] if c is not None and c < len(row) else None

            raw_interval = cell("interval")
            if clean_text(raw_interval).lower().startswith("note"):
                continue
            if isinstance(raw_interval, (datetime.date, datetime.datetime)):
                # Excel turns "5-10" typed into a General cell into 10 May.
                # Losing the row is better than a 5 to 2026 m interval, but
                # the crew has to know a row went missing.
                flags.append(
                    DataFlag(
                        "warning",
                        "interval_read_as_date",
                        f"Depth interval cell holds the date "
                        f"{raw_interval:%d %b %Y} - Excel converts entries like "
                        '"5-10" into dates. Format the depth column as Text '
                        "and retype the interval; this row was skipped.",
                    )
                )
                continue
            # Word turns "5-10" into "5–10" as the crew types the sheet and
            # the en dash survives the copy into Excel, but the interval
            # pattern lists only the plain hyphen, so the row was dropped
            # without a word and the gap it left was reported as a gap in the
            # crew's log (ROADMAP data-ingestion-8). Normalising the dashes
            # reads the interval as it was written, whichever dash was typed.
            # A metre unit against each depth ("30 m - 40 m", "5m-10m") is
            # dropped first for the same reason: the row used to be skipped
            # with its description and its strike.
            interval = parse_depth_interval(
                common.strip_metre_units(common.normalise_dashes(raw_interval))
            )
            if interval is None:
                if _reads_as_interval(raw_interval):
                    flags.append(
                        DataFlag(
                            "warning",
                            "interval_unreadable",
                            f'Depth interval cell "{clean_text(raw_interval)}" was not '
                            "read as a depth interval, so this row was skipped; write "
                            'it as the depths from and to, as "30-40".',
                        )
                    )
                continue
            top, bottom = interval
            description = clean_text(cell("description"))
            diameter = parse_bit_diameter_in(cell("diameter"), diameter_unit)
            if diameter is not None and diameter > MAX_BIT_DIAMETER_IN:
                # a bit size in millimetres with its unit left off: sized as
                # inches it made a two-metre annulus and a thousand bags of
                # cement
                too_wide.append(clean_text(cell("diameter")))
                diameter = None
            intervals.append(
                LithologyInterval(
                    top_m=top,
                    bottom_m=bottom,
                    description=description,
                    from_time=clean_text(cell("from_time")),
                    to_time=clean_text(cell("to_time")),
                    penetration_rate_m_per_min=parse_penetration_rate_m_per_min(
                        cell("rate"), rate_unit
                    ),
                    bit_diameter_in=diameter,
                )
            )
            raw_strike = cell("strike")
            depths, reason = parse_water_strike_depths(raw_strike)
            strikes.extend(depths)
            if reason:
                flags.append(
                    _unreadable_strike_flag(clean_text(raw_strike), reason)
                )
            elif not depths and parse_number(raw_strike) == 0:
                # A crew fills the strike column with 0 to mean "no water on
                # this row". Read as a number it was a strike at 0 m, which
                # seeded a screen against the topsoil (ROADMAP
                # data-ingestion-9); it is counted here so the refusal is
                # visible rather than silent.
                zero_strike_rows += 1

        if zero_strike_rows:
            flags.append(
                DataFlag(
                    "info",
                    "water_strike_zero_ignored",
                    f"The water strike column holds 0 on {zero_strike_rows} "
                    "row(s); a zero there is read as no strike on that row, "
                    "not as a strike at 0 m.",
                )
            )
        if too_wide:
            values = ", ".join(dict.fromkeys(too_wide))
            flags.append(
                DataFlag(
                    "warning",
                    "diameter_implausible",
                    f"Drilled diameter {values} reads as more than "
                    f"{MAX_BIT_DIAMETER_IN:g} inches, wider than any water well "
                    "bit, so it was not recorded; write the unit in the cell or "
                    'the column header, as "165 mm".',
                )
            )

    # Water strikes noted as text lines ("First water strike: 12m"). The note
    # used to be read as the last number after the last colon, so
    # "Water strike: 8 m at 14:30" recorded a 30 m strike and a note naming
    # two strikes recorded only the first (ROADMAP data-ingestion-9).
    for row in grid:
        for c in row:
            raw = clean_text(c)
            text = raw.lower()
            if "water strike" in text and not text.startswith("note"):
                depths, reason = parse_water_strike_depths(raw)
                for value in depths:
                    if value not in strikes:
                        strikes.append(value)
                if reason:
                    # A cell in the strike column that is also a note has
                    # already been refused once by the loop above, and one
                    # refusal of one cell is one flag.
                    flag = _unreadable_strike_flag(raw, reason)
                    if all(f.message != flag.message for f in flags):
                        flags.append(flag)

    total = fields.get("borehole_depth_m")
    if total is None and intervals:
        total = max(iv.bottom_m for iv in intervals)

    # A strike below the bottom of the hole is a number the drilling never
    # reached. It survives only as a figure printed to the client - the
    # handover report lists the strikes - because the screen designer clips
    # it out, so nothing else in the toolkit ever contradicts it.
    if total is not None:
        too_deep = [v for v in strikes if v > float(total)]
        if too_deep:
            strikes = [v for v in strikes if v <= float(total)]
            flags.append(
                DataFlag(
                    "warning",
                    "water_strike_below_total_depth",
                    "Water "
                    + plural(len(too_deep), "strike")
                    + " at "
                    + ", ".join(f"{v:g} m" for v in sorted(too_deep))
                    + f" below the recorded total depth of {float(total):g} m, "
                    "so it was not recorded; check the cell it came from.",
                )
            )

    log = DrillingLog(
        site=site,
        borehole_ref=str(fields.get("borehole_ref", "") or ""),
        total_depth_m=total,
        drilling_method=fields.get("drilling_method", ""),
        intervals=sorted(intervals, key=lambda iv: iv.top_m),
        water_strikes_m=sorted(strikes),
        grouting_depth_m=fields.get("grouting_depth_m"),
        installed_screens_m=parse_installed_screens(fields.get("installed_screens", "")),
        start_date=str(fields.get("start_date", "")),
        completion_date=str(fields.get("completion_date", "")),
        status=fields.get("status", ""),
        source=str(source),
    )

    # consistency of the interval column
    # intervals[1:] is one shorter by design: n intervals give n-1 boundaries.
    for a, b in zip(log.intervals, log.intervals[1:], strict=False):
        if b.top_m < a.bottom_m - 1e-9:
            flags.append(
                DataFlag(
                    "warning",
                    "interval_overlap",
                    f"Depth intervals overlap at {b.top_m} m.",
                )
            )
        elif b.top_m > a.bottom_m + 1e-9:
            flags.append(
                DataFlag(
                    "warning",
                    "interval_gap",
                    f"Gap in the drilling log between {a.bottom_m} m and {b.top_m} m.",
                )
            )
    if total and log.intervals and abs(log.intervals[-1].bottom_m - total) > 1e-6:
        flags.append(
            DataFlag(
                "warning",
                "depth_mismatch",
                f"Stated total depth {total} m differs from the deepest logged "
                f"interval {log.intervals[-1].bottom_m} m.",
            )
        )
    if not log.intervals:
        flags.append(
            DataFlag("error", "no_intervals", "No depth intervals found in the log.")
        )
    missing_desc = sum(1 for iv in log.intervals if not iv.description)
    if log.intervals and missing_desc:
        flags.append(
            DataFlag(
                "info",
                "missing_lithology",
                f"{missing_desc} interval(s) have no lithology description.",
            )
        )
    log.flags = flags
    return log

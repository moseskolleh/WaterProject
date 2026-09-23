"""Parsers for pumping test field sheets (Excel template and Word sheets).

The paper layout (WiNGiN step test sheet) records readings in side by
side hourly column groups, each with Time (min), Water Level (m) and
Drawdown (m), followed by a Recovery block. Two rules from the sheets
drive the parsing:

* The recorded drawdown column is the increment between successive
  readings, not drawdown below static. Only time and water level are
  read; true drawdown is always recomputed as water level minus static
  water level.
* Discharge is often missing. The test still parses and produces water
  level and drawdown series, but a ``missing_discharge`` flag marks all
  transmissivity and yield results as pending.
* Units are read, not assumed. The sheet's own headings say what the
  numbers mean - "Time (min)", "Discharge per step (m3/h)" - and a crew
  that heads the column L/s or records the times in hours means exactly
  that. Both are converted to the canonical m3/h and minutes. A unit the
  toolkit cannot read is refused rather than guessed at: a discharge in an
  unreadable unit leaves the step pending, and a time column in one is
  dropped, because there is no pending state for time and every consumer
  would otherwise fit a curve to the wrong axis.

Times within each group are irregular (1, 2, 3 and 5 minute spacing);
nothing assumes uniform sampling.

Two recovery layouts occur on real sheets and both are handled:

* A dedicated recovery block with its own Time and Water Level columns,
  followed by a Recovery column and sometimes by a Drawdown column as
  well (Time / Level / Drawdown / Recovery, Kuntolo sheet). The water
  level column is read; the Drawdown and Recovery columns are increments
  between readings and are ignored, exactly as on a pumping block.
* A single shared time column with a Recovery column that says it holds
  water levels ("Recovery water level"). That column is read against the
  shared times, interpreted as minutes since the pump stopped.

A recovery column the sheet never explains - one sitting apart from the
block's own columns and headed only "Recovery" - is refused with a flag
rather than read as a curve: read as levels, an increment column makes a
recovery that climbs a few centimetres out of a borehole tens of metres
deep.

A constant discharge test is written in hourly blocks side by side and
each block's elapsed time is often counted within its own hour, restarting
at 1. The blocks are joined into one series that runs forwards, each
block's start taken from its own heading ("Constant discharge 61-120 min")
or, failing that, from the last reading of the block before it. Read as
one column those restarts interleave into a sawtooth.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..models import DataFlag, PumpingStep, PumpingTest
from ..units import Quantity, convert, read_quantity, unit_from_label
from ..utils import clean_text, parse_number
from . import common

# Free-text discharge notes: "Constant Discharge of 2.93m3/h", "Q = 0.81 L/s".
# The unit is captured rather than assumed - the old pattern only matched an
# m3/h tail, so a rate written in L/s was silently dropped instead of read.
_DISCHARGE_TEXT_RE = re.compile(
    r"discharge\s*(?:of|0f)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*"
    r"([a-zµμ]{1,3}\s*3?\s*/\s*[a-z]{1,4}|lps|lpm|lph)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Locating the column groups
# ---------------------------------------------------------------------------

# The heading a sheet prints over a column group - "Constant discharge
# 61-120 min", "Recovery" - is the sheet's own statement of what the block
# holds and which minutes of the test it covers, so both readings below take
# the block's place in the test from it rather than from an assumption.
_BLOCK_SPAN_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*([a-z]{1,8})?",
    re.IGNORECASE,
)


def _column_role(text: str) -> str:
    """What a column's own header says the column holds.

    "Recovery" is tested before "water level" so a column headed "Recovery
    water level" is read as the recovery column it says it is, and "drawdown"
    before "level" so an increment column is never taken for a level.
    """
    if not text:
        return ""
    if "reco" in text:
        return "recovery"
    if "drawdown" in text or "draw down" in text:
        return "drawdown"
    if "water" in text or text.startswith("level"):
        return "level"
    return ""


def _block_span_min(heading: str) -> tuple[float, float] | None:
    """The minutes a block heading says the block covers, e.g. ``(61.0, 120.0)``.

    ``None`` when the heading names no span, or names one in a unit that
    cannot be read: an offset applied to every reading in a block has to come
    from the sheet, never from a guess at what "1-2" might mean.
    """
    match = _BLOCK_SPAN_RE.search(common.normalise_dashes(heading or ""))
    if match is None:
        return None
    first: float | None = float(match.group(1))
    last: float | None = float(match.group(2))
    written = (match.group(3) or "").strip()
    if written:
        first = convert(first, written, "min", dimension="time")
        last = convert(last, written, "min", dimension="time")
    if first is None or last is None or last <= first:
        return None
    return first, last


def _block_heading(grid: list[list], header_row: int, start: int, end: int) -> str:
    """The heading the sheet prints above a column group ("" when there is none).

    Only the two rows immediately above the column headers are read - on the
    template the block headings sit directly over the group's own first column -
    and only a heading the reader can act on is returned: one naming the
    recovery block, or the minutes the block covers. Anything else standing
    above the table belongs to the sheet's header block ("Discharge per step
    (m3/h)" sits there on the template), and carrying that into a flag as if
    the crew had written it over the readings would say more than the sheet
    does.
    """
    for r in range(header_row - 1, max(header_row - 3, -1), -1):
        row = grid[r] if r < len(grid) else []
        for cc in range(start, min(end, len(row))):
            text = clean_text(row[cc])
            if not text:
                continue
            if "recover" in text.lower() or _block_span_min(text) is not None:
                return text
    return ""


def _group(base: dict, level: int, kind: str, **extra) -> dict:
    """One column group: the base fields the whole block shares, plus its own."""
    return {**base, "level": level, "kind": kind, **extra}


def _find_groups(grid: list[list]) -> tuple[int, list[dict]] | None:
    """Find the header row of Time / Water Level / ... column groups.

    Returns ``(row_index, groups)``. Each group carries its column indices, the
    header its time column declares, the heading printed above the block, and a
    ``kind``:

    ``"pumping"``
        time and water level while the pump ran.
    ``"recovery"``
        time and water level after it stopped. A recovery block's Drawdown and
        Recovery columns are increments between readings, so the water level
        column is the one read: a block laid out Time / Level / Drawdown /
        Recovery used to have its fourth column read as the levels, which made
        the recovery curve the increment rather than the water level (ROADMAP
        data-ingestion-10).
    ``"recovery_unreadable"``
        a recovery column the sheet never explains. ``_assemble`` flags it and
        reads no curve from it.

    A block is a recovery block when its heading or its time column says
    "recovery", or when its columns run Time, Water Level[, Drawdown], Recovery
    with nothing else between them. A recovery column that says it holds water
    levels ("Recovery water level") is instead read as a second series against
    the shared time column, which is the other layout the sheets use.
    """
    best: tuple[int, list[dict]] | None = None
    for r, row in enumerate(grid):
        texts = common.row_text(row)
        time_cols = [c for c, t in enumerate(texts) if t.startswith("time")]
        if not time_cols:
            continue
        groups: list[dict] = []
        for gi, c in enumerate(time_cols):
            end = time_cols[gi + 1] if gi + 1 < len(time_cols) else len(texts)
            roles: dict[str, int] = {}
            for cc in range(c + 1, end):
                role = _column_role(texts[cc])
                if role and role not in roles:
                    roles[role] = cc
            level_col = roles.get("level")
            draw_col = roles.get("drawdown")
            reco_col = roles.get("recovery")
            if level_col is None and reco_col is None:
                continue
            # The header text travels with the group so the time unit it
            # declares - "Time (min)", "Time (h)" - is read rather than assumed,
            # and the block heading travels with it so a constant test's hourly
            # blocks can be put back in the order the sheet gives them.
            header = texts[c]
            heading = _block_heading(grid, r, c, end)
            base = {"time": c, "time_header": header, "block_heading": heading}
            says_recovery = "recover" in heading.lower() or "recover" in header
            reco_says_level = reco_col is not None and (
                "level" in texts[reco_col] or "water" in texts[reco_col]
            )

            if reco_col is None:
                groups.append(_group(base, level_col,
                                     "recovery" if says_recovery else "pumping"))
            elif says_recovery:
                # The sheet names the block, so its level column is the level
                # and its recovery column is an increment, as the drawdown
                # column is on a pumping block.
                groups.append(_group(
                    base, level_col if level_col is not None else reco_col,
                    "recovery"))
            elif level_col is None:
                # Nothing else in the block can be a water level, so the
                # recovery column is read as one.
                groups.append(_group(base, reco_col, "recovery"))
            elif reco_says_level and (
                len(time_cols) == 1 or max(level_col, reco_col) - c > 2
            ):
                # A shared time column with a recovery column that says it
                # holds levels: two series read against the same times. A
                # block with its own time column and the recovery column
                # beside it is a recovery block, not a pumping block with a
                # second series; read the other way, its water levels were
                # joined onto the drawdown curve as the next hour.
                groups.append(_group(base, level_col, "pumping"))
                groups.append(_group(base, reco_col, "recovery"))
            elif max(level_col, reco_col) - c <= 2:
                # Time, Water Level, Recovery: the recovery block the bundled
                # template prints.
                groups.append(_group(base, level_col, "recovery"))
            elif (level_col == c + 1 and draw_col == c + 2 and reco_col == c + 3
                  and len(time_cols) > 1):
                # Time, Level, Drawdown, Recovery: a recovery block written
                # with both increment columns. Reading its fourth column as the
                # levels made the recovery curve the rise between readings
                # rather than the water level (ROADMAP data-ingestion-10). It
                # is read this way only when another group holds the pumping
                # readings; alone on a sheet the same four columns could be a
                # whole test against one time column, which is refused below.
                groups.append(_group(base, level_col, "recovery"))
            else:
                # A recovery column standing apart from the block's own
                # columns: it may hold levels or increments and the sheet does
                # not say which, so the pumping pair is read and the recovery
                # column is refused by name.
                groups.append(_group(base, level_col, "pumping"))
                groups.append(_group(base, reco_col, "recovery_unreadable",
                                     recovery_header=clean_text(row[reco_col])))
        if groups and (best is None or len(groups) > len(best[1])):
            best = (r, groups)
    return best


def _read_series(
    grid: list[list], header_row: int, group: dict
) -> tuple[np.ndarray, np.ndarray, str, list[str]]:
    """Read one Time / Water Level pair, with the times put into minutes.

    Returns ``(times_min, levels, time_unit, skipped)``. ``time_unit`` is the
    unit the column declared; it is empty when nothing was declared (minutes
    assumed) and ``"?<text>"`` when the *header* declared one that could not
    be read - in which case the caller must drop the group rather than treat
    unknown units as minutes. Unlike discharge, there is no "pending" state
    for time: every consumer would silently produce wrong transmissivities.

    ``skipped`` lists individual cells whose own text could not be read; they
    cost one reading each rather than the column, and the caller reports
    them.
    """
    header = group.get("time_header", "")
    # A unit the header declares applies to the whole column, so an
    # unreadable one there costs the group. A unit written into one cell
    # applies to that cell, so an unreadable one there costs one reading -
    # otherwise a single annotated entry ("5 (approx)") threw away the test.
    declared, header_unit = unit_from_label(header, dimension="time")
    if declared and header_unit is None:
        return (np.array([], dtype=float), np.array([], dtype=float),
                f"?{declared}", [])

    times, levels, skipped = [], [], []
    unit_text = declared
    for row in grid[header_row + 1 :]:
        cell = row[group["time"]] if group["time"] < len(row) else None
        wl = parse_number(row[group["level"]]) if group["level"] < len(row) else None
        quantity = read_quantity(cell, header, dimension="time")
        if quantity.status == "absent" or wl is None:
            continue
        if quantity.status == "unknown":
            # one unreadable reading, not a broken column - but never silent
            skipped.append(str(cell))
            continue
        if quantity.unit_text:
            unit_text = quantity.unit_text
        times.append(quantity.value)
        levels.append(wl)
    return (np.array(times, dtype=float), np.array(levels, dtype=float),
            unit_text, skipped)


_STEP_LABEL_RE = re.compile(r"^\s*step\s*\d*\s*q\b", re.IGNORECASE)


def _row_unit_hint(row: list) -> str:
    """The row's own leading label, e.g. 'Discharge per step (m3/h)'."""
    for cell in row:
        text = clean_text(cell)
        if text and "discharge" in text.lower():
            return text
    return ""


def _find_step_discharges(grid: list[list]) -> dict[int, "Quantity"]:
    """Read per step discharge from 'Step n Q' labelled cells.

    Two hazards on a real sheet, both handled here:

    * The rate is written in whatever unit the crew used. The unit is taken
      from the value cell, then the label, then the row's discharge caption,
      and the value is converted to m3/h. A unit that cannot be read is
      refused, which routes the step into the existing "discharge missing,
      results pending" path rather than producing a wrong transmissivity.
    * The neighbouring cell may be the *next* step's label rather than a
      value. Scanning it blindly read "Step 2 Q (m3/h)" as a discharge of
      2 m3/h whenever the first step's box was left empty, and fitted a
      transmissivity to it. Label-shaped cells are skipped.
    """
    discharges: dict[int, Quantity] = {}
    for row in grid:
        row_hint = _row_unit_hint(row)
        for c, cell in enumerate(row):
            label = clean_text(cell)
            if not _STEP_LABEL_RE.match(label):
                continue
            num = parse_number(label.lower().split("q")[0])
            if num is None:
                continue
            for cc in range(c + 1, min(c + 3, len(row))):
                neighbour = row[cc]
                if _STEP_LABEL_RE.match(clean_text(neighbour)):
                    break  # the next step's label, not this step's value
                quantity = read_quantity(
                    neighbour, label, row_hint, dimension="flow"
                )
                if quantity.status == "absent":
                    continue
                discharges[int(num)] = quantity
                break
    return discharges


def _discharge_candidates_from_text(grid: list[list]) -> tuple[list[float], list[str]]:
    """Discharge values mentioned in free text such as
    'Constant Discharge of 2.93m3/h'.

    Returns ``(values_in_m3_per_h, unreadable_unit_texts)``. A note whose
    unit cannot be read is reported rather than converted, so it can be
    raised as a flag instead of quietly becoming a number in m3/h.
    """
    found: list[float] = []
    unreadable: list[str] = []
    for row in grid:
        for cell in row:
            if cell is None or isinstance(cell, (int, float)):
                continue
            for m in _DISCHARGE_TEXT_RE.finditer(str(cell)):
                written = m.group(2).strip()
                value = convert(float(m.group(1)), written, "m3/h", dimension="flow")
                if value is None:
                    if written not in unreadable:
                        unreadable.append(written)
                    continue
                if value not in found:
                    found.append(value)
    return found, unreadable


# Pre-printed text that names a test kind without recording which test was
# run: the template's own title mentions both, and its constant-discharge
# column labels ("Constant discharge 61-120 min") sit on every sheet whatever
# was pumped. Reading either as an answer turned step tests into constant ones.
_CONSTANT_COLUMN_LABEL_RE = re.compile(r"constant\s+discharge\s*\d")


def _sheet_test_type(grid: list[list]) -> str:
    """Look for 'STEP TEST' or 'CONSTANT DISCHARGE' banners in the sheet.

    Only decisive text counts. A cell naming both kinds is a form title
    ("PUMPING TEST FIELD SHEET (STEP / CONSTANT DISCHARGE)"), and a
    constant-discharge column label is a heading for one of the hourly
    groups - neither says which test the crew actually ran.
    """
    for row in grid:
        for cell in row:
            text = clean_text(cell).lower()
            if not text:
                continue
            step_words = "step test" in text or "step drawdown" in text
            constant_words = (
                "constant discharge" in text or "constant rate" in text
            )
            # "(STEP / CONSTANT DISCHARGE)" offers both; any mention of a step
            # alongside constant wording makes the cell a title, not an answer
            if constant_words and "step" in text:
                continue
            if step_words:
                return "step"
            if constant_words and not _CONSTANT_COLUMN_LABEL_RE.search(text):
                return "constant"
    return ""


# ---------------------------------------------------------------------------
# Assembling the PumpingTest
# ---------------------------------------------------------------------------

def _join_constant_blocks(
    blocks: list[tuple[np.ndarray, np.ndarray, dict]],
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """Join the hourly blocks of a constant discharge test into one series.

    A constant discharge sheet is written in hourly column groups side by side
    and each group's elapsed time is often counted within its own hour: 1, 2, 3
    in the first block and 1, 2, 3 again in the second. Concatenating the
    groups and sorting the result interleaved them into a sawtooth - minute 1
    of every hour, then minute 2 of every hour - and every drawdown curve and
    every transmissivity fitted to it was wrong (ROADMAP data-ingestion-10).

    Each block's place in the test is read off the sheet: the minutes its own
    heading names ("Constant discharge 61-120 min"), or, when the heading names
    none, the last reading of the block before it, which is what a block whose
    times go backwards continues from. A block that is neither - one starting
    inside the readings already taken and running past them - is left out and
    named, because a block placed at a minute nobody can check produces a curve
    nobody can trust.

    Returns ``(times_min, levels, joined, dropped)``. ``joined`` and ``dropped``
    are sentences naming what was done, for the caller to raise as flags.
    """
    times: list[np.ndarray] = []
    levels: list[np.ndarray] = []
    joined: list[str] = []
    dropped: list[str] = []
    end: float | None = None
    for number, (t, wl, group) in enumerate(blocks, start=1):
        heading = str(group.get("block_heading", "") or "")
        span = _block_span_min(heading)
        first = float(t[0])
        offset = 0.0
        # The sentence describing the shift is held back until the block has
        # actually been kept. Appended where the offset is worked out, a block
        # that the backwards check below then drops was named in both flags at
        # once, and the report said in one sentence that the block had been
        # joined with so many minutes added and in the next that it had been
        # left out (ROADMAP data-ingestion-10).
        note = ""
        if span is not None and first < span[0]:
            # The block is placed by its heading alone. The template numbers
            # the minutes of each block on from the block before ("0-60 min",
            # "61-120 min"), so the block's own clock reads zero one minute
            # before its heading starts. Aligning its first reading with the
            # heading instead put a block read every five minutes, 5 to 60,
            # at 61 to 116, and a four-hour test ended at 226 minutes.
            offset = max(span[0] - 1.0, 0.0)
            if offset:
                note = (
                    f"block {number} counts its time within its own hour and its "
                    f"heading '{heading}' covers {span[0]:g} to {span[1]:g} min, "
                    f"so {offset:g} min were added to it and its first reading, "
                    f"at {first:g} min, is minute {first + offset:g} of the test"
                )
        elif span is not None or end is None or first > end:
            offset = 0.0
        elif float(t.max()) <= end:
            offset = end
            note = (
                f"block {number} restarts its time at {first:g} min, inside the "
                f"{end:g} min already read, and its heading names no minutes, so "
                f"it was read as continuing from the last reading before it and "
                f"{offset:g} min were added to it"
            )
        else:
            dropped.append(
                f"Block {number} of the constant discharge readings starts at "
                f"{first:g} min, inside the {end:g} min already read, and runs "
                f"past them to {float(t.max()):g} min, so the sheet does not say "
                "whether its times count from the start of the test or from the "
                "start of the block."
            )
            continue
        shifted = t + offset
        if end is not None and float(shifted[0]) < end:
            dropped.append(
                f"Block {number} of the constant discharge readings still starts "
                f"at {float(shifted[0]):g} min once placed, before the {end:g} "
                "min already read, so its readings would run backwards into the "
                "block before it."
            )
            continue
        if note:
            joined.append(note)
        times.append(shifted)
        levels.append(wl)
        end = float(shifted.max())
    if not times:
        empty = np.array([], dtype=float)
        return empty, empty, joined, dropped
    all_t = np.concatenate(times)
    all_wl = np.concatenate(levels)
    order = np.argsort(all_t, kind="stable")
    return all_t[order], all_wl[order], joined, dropped


def _assemble(grid: list[list], source: str) -> PumpingTest:
    fields = common.extract_header_fields(grid, max_rows=len(grid))
    site = common.site_from_fields(fields, source=source)
    flags: list[DataFlag] = []

    located = _find_groups(grid)
    if located is None:
        raise ValueError(f"No Time/Water Level column groups found in {source}")
    header_row, groups = located

    for group in groups:
        if group["kind"] != "recovery_unreadable":
            continue
        # The sheet carries a recovery column but never says what is in it, and
        # a recovery curve drawn from increments is wrong by the whole depth to
        # water. Refusing it and naming it is the only honest answer (ROADMAP
        # data-ingestion-10).
        where = (f" in the '{group['block_heading']}' block"
                 if group["block_heading"] else "")
        flags.append(
            DataFlag(
                "warning",
                "recovery_layout_unreadable",
                f"A column headed '{group.get('recovery_header', '')}' stands "
                f"apart from the water level column{where}, and nothing on the "
                "sheet says whether it holds water levels or the rise between "
                "readings, so no recovery curve was read from it. Head the "
                "recovery block 'Recovery', or the column 'Recovery water "
                "level (m)'.",
            )
        )

    def _series(kind: str) -> list[tuple[np.ndarray, np.ndarray, dict]]:
        """Read every column group of one kind, dropping unreadable-unit ones.

        A time column whose unit cannot be read is dropped rather than taken
        as minutes: reading hours as minutes would rescale every drawdown
        curve and every transmissivity fitted to it, silently.

        Each block is handed back with the group it came from, because a
        constant test's blocks are placed by the heading the sheet prints over
        them before they are joined into one series.
        """
        out = []
        for group in groups:
            if group["kind"] != kind:
                continue
            t, wl, unit_text, skipped = _read_series(grid, header_row, group)
            if unit_text.startswith("?"):
                flags.append(
                    DataFlag(
                        "error",
                        "time_unit_unknown",
                        f"The {kind} time column is headed "
                        f"'{group.get('time_header', '')}' and its unit "
                        f"'{unit_text[1:]}' could not be read, so the readings "
                        "were not used. Head the column in minutes, hours or "
                        "seconds.",
                    )
                )
                continue
            if unit_text and unit_text.lower() not in ("min", "mins", "minute",
                                                       "minutes"):
                flags.append(
                    DataFlag(
                        "info",
                        "time_unit_converted",
                        f"The {kind} times are recorded in '{unit_text}' and "
                        "have been converted to minutes for the analysis.",
                    )
                )
            if skipped:
                flags.append(
                    DataFlag(
                        "warning",
                        "time_reading_unreadable",
                        f"{len(skipped)} {kind} reading(s) carried text this "
                        "toolkit could not read as a time and were left out ("
                        + ", ".join(repr(x) for x in skipped[:3])
                        + "). Put notes outside the reading columns.",
                    )
                )
            if len(t):
                out.append((t, wl, group))
        return out

    pumping_blocks = _series("pumping")
    recovery_blocks = _series("recovery")
    pumping_series = [(t, wl) for t, wl, _ in pumping_blocks]
    recovery_series = [(t, wl) for t, wl, _ in recovery_blocks]

    test_type = str(fields.get("test_type", "")).strip().lower()
    stated = bool(test_type)
    if not test_type:
        test_type = _sheet_test_type(grid)
    inferred_from_shape = not test_type
    if not test_type:
        test_type = "step" if len(pumping_series) > 1 else "constant"
    if inferred_from_shape and not stated and len(pumping_series) > 1:
        flags.append(
            DataFlag(
                "info",
                "test_type_inferred",
                f"The test type cell is blank; the {len(pumping_series)} filled "
                "column groups have been read as the steps of a step test. If "
                'this was a constant discharge test, write "constant" in the '
                "test type cell so the readings are analysed as one series.",
            )
        )

    if test_type.startswith("constant") and len(pumping_blocks) > 1:
        # The hourly column groups are one continuous series on a constant
        # test, but each block's times are often counted within its own hour,
        # so every block is put back in its place before they are joined.
        t, wl, joined, dropped = _join_constant_blocks(pumping_blocks)
        for note in dropped:
            flags.append(
                DataFlag(
                    "warning",
                    "constant_block_unreadable",
                    note + " The block was left out of the series rather than "
                    "joined at a minute nobody can check. Head each block with "
                    "the minutes it covers, as in 'Constant discharge 121-180 "
                    "min'.",
                )
            )
        if joined and len(t):
            flags.append(
                DataFlag(
                    "info",
                    "constant_blocks_joined",
                    f"The constant discharge readings are written in "
                    f"{len(pumping_blocks)} blocks: " + "; ".join(joined)
                    + f". The blocks have been joined into one series running "
                    f"{t.min():g} to {t.max():g} min.",
                )
            )
        pumping_series = [(t, wl)] if len(t) else []

    step_length = fields.get("step_length_min")
    discharges = _find_step_discharges(grid)

    steps: list[PumpingStep] = []
    for i, (t, wl) in enumerate(pumping_series, start=1):
        quantity = discharges.get(i)
        steps.append(
            PumpingStep(
                step_number=i,
                time_min=t,
                water_level_m=wl,
                # A refused unit leaves this None, which is the existing
                # "results pending until discharge is supplied" path - the
                # right answer, and far better than a number in the wrong unit.
                discharge_m3_per_h=quantity.value if quantity is not None else None,
                label=f"Step {i}" if len(pumping_series) > 1 else "Pumping phase",
            )
        )
        if quantity is None:
            continue
        if quantity.status == "unknown":
            flags.append(
                DataFlag(
                    "warning",
                    "discharge_unit_unknown",
                    f"Step {i} discharge is written as "
                    f"{quantity.raw_value:g} '{quantity.unit_text}', a unit "
                    "this toolkit does not recognise, so it was not used. "
                    "Record the rate in m3/h, L/s or L/min.",
                )
            )
        elif quantity.status == "converted":
            flags.append(
                DataFlag(
                    "info",
                    "discharge_unit_converted",
                    f"Step {i} discharge {quantity.raw_value:g} "
                    f"{quantity.unit_text} read as {quantity.value:.3g} m3/h.",
                )
            )
        elif quantity.status == "assumed":
            flags.append(
                DataFlag(
                    "info",
                    "discharge_unit_assumed",
                    f"Step {i} discharge {quantity.raw_value:g} carries no "
                    "unit on the sheet and was read as m3/h. Head the "
                    "discharge row with its unit to remove the assumption.",
                )
            )

    # Free-text discharge: use it only when unambiguous (one candidate, one step)
    candidates, unreadable_units = _discharge_candidates_from_text(grid)
    missing = [s for s in steps if s.discharge_m3_per_h is None]
    for written in unreadable_units:
        flags.append(
            DataFlag(
                "warning",
                "discharge_unit_unknown",
                f"A discharge note on the sheet is written in '{written}', a "
                "unit this toolkit does not recognise, so it was not used.",
            )
        )
    if candidates and missing:
        if len(candidates) == 1 and len(steps) == 1:
            steps[0].discharge_m3_per_h = candidates[0]
            flags.append(
                DataFlag(
                    "info",
                    "discharge_from_text",
                    f"Discharge {candidates[0]:g} m3/h taken from a text note on "
                    "the sheet; confirm against the measured value.",
                )
            )
        else:
            flags.append(
                DataFlag(
                    "warning",
                    "discharge_ambiguous",
                    "Discharge mentioned in sheet text ("
                    + ", ".join(f"{c:g} m3/h" for c in candidates)
                    + ") but not assigned per step; enter values in the template.",
                )
            )

    recovery_time = recovery_level = None
    if recovery_series:
        recovery_time, recovery_level = recovery_series[0]

    if recovery_time is not None:
        test_type += "+recovery"

    swl = fields.get("static_water_level_m")
    pumping_duration = None
    if steps:
        pumping_duration = float(max(s.time_min.max() for s in steps))

    test = PumpingTest(
        site=site,
        borehole_ref=str(fields.get("borehole_ref", "") or ""),
        test_type=test_type,
        static_water_level_m=swl,
        borehole_depth_m=fields.get("borehole_depth_m"),
        pump_setting_m=fields.get("pump_setting_m"),
        step_length_min=step_length,
        steps=steps,
        recovery_time_min=recovery_time,
        recovery_level_m=recovery_level,
        pumping_duration_min=pumping_duration,
        source=str(source),
    )

    # ---- data quality flags ------------------------------------------------
    if swl is None:
        flags.append(
            DataFlag(
                "error",
                "missing_static_water_level",
                "Static water level is missing; drawdown cannot be computed.",
            )
        )
    missing_q = [s.step_number for s in steps if s.discharge_m3_per_h is None]
    if missing_q:
        flags.append(
            DataFlag(
                "warning",
                "missing_discharge",
                "Discharge not recorded for step(s) "
                + ", ".join(str(n) for n in missing_q)
                + ". Drawdown and recovery curves are produced, but transmissivity "
                "and yield results are pending until discharge values are supplied.",
            )
        )
    if swl is not None:
        # The recovery limb is checked too: a recovery that overshoots the
        # static level gives negative residual drawdown, and the recovery
        # transmissivity - the one the yield prefers - is fitted through it.
        above = []
        if steps and any(np.any(s.water_level_m < swl - 0.01) for s in steps):
            above.append("pumping")
        if recovery_level is not None and np.any(recovery_level < swl - 0.01):
            above.append("recovery")
        if above:
            flags.append(
                DataFlag(
                    "warning",
                    "water_level_above_static",
                    f"Some {' and '.join(above)} water levels are above the "
                    "stated static water level, giving negative drawdown. Check "
                    "the static level and the measuring datum on the sheet.",
                )
            )
    for s in steps:
        if np.any(np.diff(s.time_min) <= 0):
            flags.append(
                DataFlag(
                    "warning",
                    "time_not_increasing",
                    f"Times are not strictly increasing in {s.label}.",
                    s.label,
                )
            )
    if test.borehole_depth_m and test.pump_setting_m:
        if test.pump_setting_m > test.borehole_depth_m:
            flags.append(
                DataFlag(
                    "warning",
                    "pump_below_borehole",
                    "Pump setting is deeper than the borehole depth.",
                )
            )
    if test.borehole_depth_m and steps:
        max_wl = max(float(np.nanmax(s.water_level_m)) for s in steps)
        if max_wl > test.borehole_depth_m:
            flags.append(
                DataFlag(
                    "warning",
                    "level_below_borehole",
                    f"Recorded water level {max_wl:.2f} m exceeds the stated "
                    f"borehole depth {test.borehole_depth_m:.0f} m; check the sheet.",
                )
            )
    if test.pump_setting_m and steps:
        # A pump cannot draw the water below its own intake. Levels 18 m
        # under the pump went into a report as 59 m of drawdown and 38 m of
        # available drawdown, with nothing to say the sheet could not be
        # right.
        max_wl = max(float(np.nanmax(s.water_level_m)) for s in steps)
        if max_wl > test.pump_setting_m:
            flags.append(
                DataFlag(
                    "warning",
                    "level_below_pump",
                    f"Recorded water level {max_wl:.2f} m is below the pump "
                    f"intake at {test.pump_setting_m:.0f} m. A pump cannot draw "
                    "the level below its own intake, so the pump setting, the "
                    "levels or the datum on the sheet is wrong; the drawdown "
                    "figures are as recorded and not to be relied on.",
                )
            )
    test.flags = flags
    return test


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def read_pumping_workbook(path: str | Path) -> PumpingTest:
    """Read a pumping test from the Excel template layout."""
    grid, _ = common.load_grid(path)
    return _assemble(grid, source=str(path))


def read_pumping_docx(path: str | Path) -> PumpingTest:
    """Read a pumping test from a Word field sheet (Kuntolo style).

    Paragraph text supplies the header block; the table whose header
    contains Time / Water Level column groups supplies the readings.
    """
    import docx  # python-docx

    path = Path(path)
    document = docx.Document(str(path))

    header_grid: list[list] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        parts = [p for p in re.split(r"\t+|\s{3,}", text) if p.strip()]
        header_grid.append(parts)

    best_table: list[list] | None = None
    best_count = 0
    for table in document.tables:
        grid = [[cell.text for cell in row.cells] for row in table.rows]
        located = _find_groups(grid)
        if located and len(located[1]) > best_count:
            best_table = grid
            best_count = len(located[1])
    if best_table is None:
        raise ValueError(f"No pumping test table found in {path}")

    return _assemble(header_grid + best_table, source=str(path))

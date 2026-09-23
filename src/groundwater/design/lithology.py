"""One reading of the driller's words, shared by every drawing.

The borehole drawing, the browser drawing and the Depth Spine each kept
their own table of lithology keywords, so the same log was "clay" on one
figure, "clay and saprolite" on another and "fresh basement" on a third
for an interval the driller had called slightly weathered granite. This
module is the one table. A description is matched against the classes in
order and the first match wins, except that a fracture zone named with a
depth range inside a longer interval ("Light colour granite, fracture zone
49-52 m") is a band of its own: the range is the fracture zone, the rest
of the interval is the rock it is in, and the drawing used to hatch the
whole five metres.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..ingestion.common import normalise_dashes
from ..models import LithologyInterval

_RANGE = r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*m\b"

#: "fracture zone", "fractured", "fractures": the words that name a fracture.
#: The depths they name are read from the rest of the clause.
FRACTURE_PHRASE_RE = re.compile(r"\bfracture[ds]?\b(?:\s+zones?\b)?", re.IGNORECASE)

#: Any depth range written into a description.
ANY_RANGE_RE = re.compile(_RANGE, re.IGNORECASE)

# One depth range in a fracture clause: "49-52 m", "49 m to 52 m", "between
# 49 and 52 m", "49-52 metres", or "49-52" with the unit left off. A range
# followed by another unit ("2-3 mm", "1-2 per metre") is an aperture or a
# count, not depths, and is not read.
_NUMBER = r"(\d+(?:\.\d+)?)"
_METRES = r"(?:metres?|meters?|mtrs?|m)\b"
_DEPTH_RANGE_RE = re.compile(
    r"(?:between\s+" + _NUMBER + r"\s*(?:" + _METRES + r")?\s*(?:and|-|to)\s*" + _NUMBER
    + r"|" + _NUMBER + r"\s*(?:" + _METRES + r")?\s*(?:-|to)\s*" + _NUMBER + r")"
    + r"(?:\s*" + _METRES + r")?"
    + r"(?!\s*(?:mm|cm|%|in\b|inch|\"|ft\b|feet|per\b|/|x\b|\d|m\s*/))",
    re.IGNORECASE,
)

# Where a fracture clause ends: a semicolon, a bracket, a line break, a full
# stop that is not a decimal point, or a comma that does not lead straight on
# to another range ("fractured zones 49-52 m, 55-56 m" is one clause,
# "fractured, quartz vein at 52-53 m" is two).
_CLAUSE_END_RE = re.compile(r"[;()\n]|\.(?!\d)|,(?!\s*(?:and\s+|&\s*)?\d)")

# "at" or "from" before the first range belongs to the fracture phrase, so it
# goes with it when the zone is taken out of the description.
_RANGE_LEAD_RE = re.compile(r"\s*\b(?:at|from)\s*$", re.IGNORECASE)

#: How far outside the row it is written on a named zone may lie and still be
#: read as a depth. The driller logs "fracture zone 60-62 m" against the
#: 55-60 m row he was drilling when he saw it; a "range" tens of metres from
#: its row is something else (a count, a date), and the row is screened
#: instead.
NAMED_ZONE_REACH_M = 5.0


@dataclass(frozen=True)
class LithologyClass:
    key: str
    label: str
    colour: str
    hatch: str


#: In matching order. The regexes are applied to the lowercased description.
LITHOLOGY_CLASSES: tuple[tuple[LithologyClass, re.Pattern], ...] = tuple(
    (LithologyClass(key, label, colour, hatch), re.compile(pattern))
    for key, label, colour, hatch, pattern in (
        ("fracture", "Fracture zone", "#9FB6CD", "xx", r"fracture|fissure"),
        ("topsoil", "Topsoil", "#8B5A2B", "", r"topsoil|top soil"),
        ("laterite", "Laterite", "#C4703E", "", r"laterit|duricrust"),
        ("saprolite", "Saprolite", "#D2B48C", "..", r"saprolit|regolith"),
        ("clay", "Clay", "#B8860B", "--", r"\bclay"),
        ("sand", "Sand and gravel", "#E8D8A0", "..", r"\bsand|gravel"),
        ("weathered", "Weathered rock", "#A98F63", "//", r"weather"),
        ("basement", "Basement rock", "#A9A9A9", "++",
         r"granite|gneiss|schist|basement|bedrock|\brock\b|fresh"),
    )
)

OTHER = LithologyClass("other", "Other material", "#CCCCCC", "")

#: Words that make an interval clayey ground: a seepage in it is cased and
#: grouted off, not screened, whatever the strike column says.
CLAYEY_RE = re.compile(r"\bclay|laterit|topsoil|top soil")


def lithology_class(description: str) -> LithologyClass:
    """The class of a description as a whole."""
    text = (description or "").lower()
    for klass, pattern in LITHOLOGY_CLASSES:
        if pattern.search(text):
            return klass
    return OTHER


def is_clayey(description: str) -> bool:
    return bool(CLAYEY_RE.search((description or "").lower()))


@dataclass(frozen=True)
class FractureReading:
    """What a description says about named fracture zones.

    ``ranges`` are the zones read, in metres. ``unread`` is true when a
    fracture phrase names depths that could not be read as a zone near the
    row ("fractures at 49 and 52 m"), so the caller treats the whole logged
    interval as the target as well. ``cuts`` are the spans of the
    (dash-normalised) text that name the zones read, for taking them out.
    """

    ranges: list[tuple[float, float]]
    unread: bool
    cuts: list[tuple[int, int]]
    text: str


def read_fractures(
    description: str, top_m: float | None = None, bottom_m: float | None = None,
) -> FractureReading:
    """Read every depth range a fracture phrase names, to the end of its clause.

    Only the first range right after the phrase used to be read, so
    "fractures at 30-31 m and 33-34 m" left 33-34 m behind plain casing,
    and "between 49 and 52 m", "49 m to 52 m", "49-52 metres", "49-52" and
    an em dash all read as nothing, which screened the whole logged row.
    Given the row (``top_m``, ``bottom_m``), a range further than
    :data:`NAMED_ZONE_REACH_M` from it is not taken as a depth.
    """
    text = normalise_dashes(description or "")
    ranges: list[tuple[float, float]] = []
    cuts: list[tuple[int, int]] = []
    unread = False
    phrases = list(FRACTURE_PHRASE_RE.finditer(text))
    for i, phrase in enumerate(phrases):
        limit = phrases[i + 1].start() if i + 1 < len(phrases) else len(text)
        end = _CLAUSE_END_RE.search(text, phrase.end(), limit)
        clause_end = end.start() if end else limit
        clause = text[phrase.end():clause_end]
        read: list[tuple[int, int]] = []
        for match in _DEPTH_RANGE_RE.finditer(clause):
            numbers = [float(g) for g in match.groups() if g is not None]
            top, bottom = min(numbers), max(numbers)
            near = top_m is None or bottom_m is None or (
                top >= top_m - NAMED_ZONE_REACH_M
                and bottom <= bottom_m + NAMED_ZONE_REACH_M
            )
            if bottom > top and near:
                ranges.append((top, bottom))
                read.append(match.span())
        # whatever digits are left in the clause name something that was
        # not read as a zone
        left = "".join(
            clause[a:b] for a, b in zip(
                [0] + [e for _, e in read], [s for s, _ in read] + [len(clause)],
                strict=True,
            )
        )
        if re.search(r"\d", left):
            unread = True
        elif read:
            start = read[0][0]
            lead = _RANGE_LEAD_RE.search(clause[:start])
            if lead:
                start = lead.start()
            cuts.append((phrase.start(), phrase.end()))
            cuts.append((phrase.end() + start, phrase.end() + read[-1][1]))
    return FractureReading(ranges=ranges, unread=unread, cuts=cuts, text=text)


def fracture_ranges(
    description: str, top_m: float | None = None, bottom_m: float | None = None,
) -> list[tuple[float, float]]:
    """Depth ranges a description names as fractured, in metres."""
    return read_fractures(description, top_m, bottom_m).ranges


def host_description(
    description: str, top_m: float | None = None, bottom_m: float | None = None,
) -> str:
    """The description with its named fracture ranges taken out.

    "Light colour granite, fracture zone 49-52 m" -> "Light colour granite",
    so the rock around a named zone is classed as what it is. A fracture
    phrase whose depths could not all be read is left in, so the row it is
    written on is still classed as fractured.
    """
    reading = read_fractures(description, top_m, bottom_m)
    text, kept, cursor = reading.text, [], 0
    for start, end in reading.cuts:
        kept.append(text[cursor:start])
        cursor = end
    kept.append(text[cursor:])
    return re.sub(r"\s+", " ", "".join(kept)).strip(" ,;.")


def host_class(
    description: str, top_m: float | None = None, bottom_m: float | None = None,
) -> LithologyClass:
    """The class of the rock a row is logged as, once any zone it names is out.

    "Light colour granite, fracture zone 49-52 m" is basement rock with a
    fracture zone drawn in it as a band of its own; the class of the whole
    description would call the row a fracture zone.
    """
    if fracture_ranges(description, top_m, bottom_m):
        return lithology_class(host_description(description, top_m, bottom_m))
    return lithology_class(description)


def lithology_bands(
    intervals: list[LithologyInterval] | LithologyInterval,
) -> list[tuple[float, float, LithologyClass]]:
    """The log split into bands, each with its class.

    A fracture zone named with its depths is a band of its own wherever
    those depths fall, which is not always the row it was written on: the
    driller logs "fracture zone 60-62 m" against the 55-60 m interval he was
    drilling when he saw it. The rest of every interval is the rock the
    description names once the zone is taken out of it. Pass one interval
    to band it alone (the named zones of the others are then unknown).
    """
    if isinstance(intervals, LithologyInterval):
        intervals = [intervals]
    named = sorted(
        zone for interval in intervals
        for zone in fracture_ranges(interval.description, interval.top_m, interval.bottom_m)
    )
    fracture = lithology_class("fracture")
    bands: list[tuple[float, float, LithologyClass]] = []
    for interval in sorted(intervals, key=lambda iv: iv.top_m):
        top, bottom = float(interval.top_m), float(interval.bottom_m)
        # the host rock: the description without the zone it names, so
        # "Light colour granite, fracture zone 49-52 m" is granite here
        host = host_class(interval.description, top, bottom)
        cursor = top
        for t, b in named:
            t, b = max(t, top), min(b, bottom)
            if b <= max(t, cursor):
                continue
            if t > cursor:
                bands.append((cursor, t, host))
            bands.append((max(t, cursor), b, fracture))
            cursor = b
        if cursor < bottom:
            bands.append((cursor, bottom, host))
    return bands

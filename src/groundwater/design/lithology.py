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

from ..models import LithologyInterval

_RANGE = r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*m\b"

#: "fracture zone 49-52 m", "fractured 60-62 m", "fractures at 30-31 m":
#: a depth range named against a fracture phrase.
FRACTURE_RANGE_RE = re.compile(
    r"fracture[ds]?\s*(?:zones?)?\s*(?:at|from|between)?\s*" + _RANGE,
    re.IGNORECASE,
)

#: Any depth range written into a description.
ANY_RANGE_RE = re.compile(_RANGE, re.IGNORECASE)


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


def fracture_ranges(description: str) -> list[tuple[float, float]]:
    """Depth ranges a description names as fractured, in metres."""
    out = []
    for match in FRACTURE_RANGE_RE.finditer(description or ""):
        top, bottom = float(match.group(1)), float(match.group(2))
        if bottom < top:
            top, bottom = bottom, top
        if bottom > top:
            out.append((top, bottom))
    return out


def host_description(description: str) -> str:
    """The description with its named fracture ranges taken out.

    "Light colour granite, fracture zone 49-52 m" -> "Light colour granite",
    so the rock around a named zone is classed as what it is.
    """
    text = FRACTURE_RANGE_RE.sub("", description or "")
    return re.sub(r"[\s,;]+$", "", text).strip(" ,;")


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
        zone for interval in intervals for zone in fracture_ranges(interval.description)
    )
    fracture = lithology_class("fracture")
    bands: list[tuple[float, float, LithologyClass]] = []
    for interval in sorted(intervals, key=lambda iv: iv.top_m):
        top, bottom = float(interval.top_m), float(interval.bottom_m)
        # the host rock: the description without the zone it names, so
        # "Light colour granite, fracture zone 49-52 m" is granite here
        host = lithology_class(
            host_description(interval.description)
            if fracture_ranges(interval.description) else interval.description
        )
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

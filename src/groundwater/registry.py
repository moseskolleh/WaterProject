"""The borehole as an asset, not as a project.

A drilling project ends. The borehole does not: it is pumped every day for
twenty years by people who were not there when it was drilled, and the
question that matters after handover is not "what did the pumping test say"
but "is it working, when was it last looked at, and when was the water last
tested". The completion report cannot answer that, because it was written
once and never touched again.

So this module holds the other half. An asset has a stable identifier that
survives the project file, a position, and an append-only stream of events -
commissioned, inspected, sampled, broken down, repaired, abandoned. From
that stream it derives what is true today: whether the point is working,
how long it has been out, and what is now overdue.

Three things shape the design.

**Offline first.** Field updates are recorded on a phone at the wellhead
with no signal, often by two people who each write the visit down. Events
are therefore identified by their content rather than by a counter, so the
same visit recorded twice merges into one, and a merge is a set union that
needs no server to arbitrate it.

**Append-only.** A maintenance record that can be edited is a maintenance
record nobody can rely on. A mistake is corrected by recording the
correction, which leaves both in the history where an auditor can see them.

**Nothing is assumed working.** An asset with no events is ``unknown``, not
``functional``. A failure with no recorded repair stays a failure. The
common way an asset register becomes useless is that absence of bad news
gets read as good news, and after two years everything is green.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date

from .config import Config, DesignRules, ServiceConfig
from .geo import degrees_in_utm_boxes, infer_zone_for_sierra_leone, utm_to_geographic
from .text import phrase, phrase_table
from .utils import and_join

__all__ = [
    "Asset",
    "AssetEvent",
    "AssetState",
    "DISTRICT_CODES",
    "EVENT_KINDS",
    "FUNCTION_LABELS",
    "Schedule",
    "asset_from_project",
    "asset_state",
    "asset_with_rising_main",
    "check_character",
    "clean_answers",
    "clean_rising_main",
    "event_id",
    "format_asset_id",
    "is_legacy_asset_id",
    "iso_date",
    "legacy_check_character",
    "merge_events",
    "mint_asset_id",
    "parse_asset_id",
    "placard_lines",
    "qr_payload",
    "registry_rows",
    "registry_stats",
    "trim_field",
    "validate_asset_id",
]


# ---------------------------------------------------------------------------
# The identifier
# ---------------------------------------------------------------------------

#: Crockford's base 32: no I, L, O or U, so nothing in a code can be confused
#: with 1, 0 or V when it is read off a plate or repeated over a radio.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: What a reader who writes I, L, O or U anyway almost certainly meant.
_FOLD = {"I": "1", "L": "1", "O": "0", "U": "V"}

#: The check character is ISO 7064 MOD 37,36, whose alphabet is the full 36.
_CHECK_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: District codes. Written out rather than derived, for the same reason the
#: site statuses are: a rule that produces "BO" for Bo and "BOM" for Bombali
#: today produces a collision the first time a district is renamed, and a
#: collision here means two boreholes with one identifier.
DISTRICT_CODES = {
    "western area urban": "WAU",
    "western area rural": "WAR",
    "port loko": "PL",
    "kambia": "KAM",
    "karene": "KAR",
    "bombali": "BOM",
    "falaba": "FAL",
    "koinadugu": "KOI",
    "tonkolili": "TON",
    "kono": "KON",
    "kenema": "KEN",
    "kailahun": "KAI",
    "bo": "BO",
    "bonthe": "BON",
    "moyamba": "MOY",
    "pujehun": "PUJ",
}

#: A district nobody could match. Deliberately not a guess: an identifier
#: that says XX is one somebody can fix, and it still locates the borehole.
UNKNOWN_DISTRICT = "XX"

#: Positions are quantised to this before they go into the identifier.
POSITION_STEP_M = 10

_ID_RE = re.compile(r"^SL-([A-Z]{2,4})-([0-9A-Z]{7})-([0-9A-Z])$")


#: ISO 7064's hybrid system for M = 36: the running sum is reduced modulo M
#: (36, with 0 written as 36) and doubled modulo M + 1 (37).
_M = 36


def _check_with(body: str, modulus: int) -> str:
    product = _M
    for char in body.upper():
        value = _CHECK_ALPHABET.find(char)
        if value < 0:
            continue  # separators and spaces carry no value
        total = (product % (_M + 1)) + value
        product = 2 * (total % modulus or modulus)
    return _CHECK_ALPHABET[(_M + 1 - product % (_M + 1)) % _M]


def check_character(body: str) -> str:
    """ISO 7064 MOD 37,36 over ``body``, ignoring separators.

    The running sum is reduced modulo 36 and doubled modulo 37, as the
    standard's hybrid system has it. It used to be reduced modulo 37, which
    left 37 final states for 36 check characters, so two of them shared
    one: about one single mistyped character in 680 still validated, and
    the identifier did not match the standard's own worked examples.

    Done as the standard has it, every single wrong character is caught.
    Most transpositions of two adjacent characters are caught too, but not
    all: of the 45,360 ways two different characters can meet in one of
    the calculation's 36 states, 72 leave the state unchanged (one in 630),
    which is the hybrid system's own limit rather than a slip here.

    >>> check_character("00000000D07A0090")
    'Q'
    """
    return _check_with(body, _M)


def legacy_check_character(body: str) -> str:
    """The check character identifiers were minted with before the correction.

    Reduced modulo 37 rather than 36 (see :func:`check_character`). Kept so
    an identifier already painted on a plate, or already holding a history
    in a project file, still reads; never used to mint.
    """
    return _check_with(body, _M + 1)


def _position_code(easting: float, northing: float, zone: int) -> str:
    """Seven characters holding the position to the nearest ten metres.

    Derived rather than allocated, because there is no server to allocate
    from: two teams standing at the same wellhead with no connection between
    them have to arrive at the same identifier.
    """
    east = int(round(float(easting) / POSITION_STEP_M))
    north = int(round(float(northing) / POSITION_STEP_M))
    if not 0 <= east < 1 << 17 or not 0 <= north < 1 << 17:
        raise ValueError(
            f"({easting}, {northing}) is not a position inside Sierra Leone; "
            "an identifier minted from it would not be findable"
        )
    value = ((1 if int(zone) == 29 else 0) << 34) | (east << 17) | north
    return "".join(_ALPHABET[(value >> shift) & 31]
                   for shift in range(30, -1, -5))


def _district_code(district: str) -> str:
    return DISTRICT_CODES.get(str(district or "").strip().lower(),
                              UNKNOWN_DISTRICT)


def format_asset_id(district_code: str, position_code: str) -> str:
    body = f"SL-{district_code}-{position_code}"
    return f"{body}-{check_character(body)}"


def mint_asset_id(site) -> str:
    """The identifier for a borehole at ``site``.

    Minted once, at commissioning, and carried from then on. A later GPS fix
    a few metres off the first one produces a different code, which is why
    the registry matches on the recorded identifier first and on proximity
    only as a fallback - the derivation is how the first identifier is made
    and how a lost one is reconstructed, not something to re-run each visit.
    """
    easting = getattr(site, "easting", None)
    northing = getattr(site, "northing", None)
    if easting is None or northing is None:
        raise ValueError(
            "a borehole with no recorded position cannot be given an "
            "identifier: there would be nothing to find it by"
        )
    # Degrees typed into the two boxes are not a position in metres. The
    # browser's readiness gate read them as degrees and passed the plate,
    # while this refused them as a point near the equator, so a plate was
    # certified for an identifier nobody could mint. Both engines now refuse
    # them, in the same words.
    degrees = degrees_in_utm_boxes(easting, northing)
    if degrees:
        raise ValueError(degrees)
    zone = getattr(site, "utm_zone", None) or infer_zone_for_sierra_leone(
        float(easting))
    return format_asset_id(_district_code(getattr(site, "district", "")),
                           _position_code(easting, northing, zone))


def parse_asset_id(text: str) -> str | None:
    """Normalise a hand-entered identifier, or ``None`` if it is not one.

    Case, spacing and the four Crockford confusions (I and L for 1, O for 0,
    U for V) are forgiven in the position code, because they are reading
    mistakes rather than different codes. A failing check character is not
    forgiven: that is a wrong identifier, and a wrong identifier attaches a
    maintenance history to somebody else's borehole.
    """
    raw = re.sub(r"[\s_]+", "", str(text or "")).upper().replace("–", "-")
    if not raw:
        return None
    if not raw.startswith("SL-"):
        raw = "SL-" + raw
    parts = raw.split("-")
    if len(parts) != 4:
        return None
    _, district, code, given = parts
    # The position code is written in the 32-character Crockford alphabet,
    # which has no I, L, O or U, so folding them there is unambiguous. The
    # check character is drawn from the full 36, where those four mean
    # themselves - folding it rejected one identifier in nine that mint()
    # had just produced.
    code = "".join(_FOLD.get(c, c) for c in code)
    candidate = f"SL-{district}-{code}-{given}"
    if not _ID_RE.match(candidate):
        return None
    body = f"SL-{district}-{code}"
    # An identifier minted before the check character followed ISO 7064
    # exactly is still the identifier on its plate and in its project file,
    # so it is read as it is rather than refused or renamed:
    # validate_asset_id says that it carries the older character.
    if given not in (check_character(body), legacy_check_character(body)):
        return None
    return candidate


def is_legacy_asset_id(asset_id: str) -> bool:
    """Whether ``asset_id`` checks only against the legacy check character."""
    parsed = parse_asset_id(asset_id)
    if not parsed:
        return False
    body, given = parsed.rsplit("-", 1)
    return check_character(body) != given


def validate_asset_id(text: str) -> tuple[bool, str]:
    """``(ok, reason)`` - the reason is written to be shown to the person typing.

    An identifier carrying the legacy check character is accepted, and its
    reason is the note saying so rather than an empty string.
    """
    raw = str(text or "").strip()
    if not raw:
        return False, "No identifier was entered."
    parsed = parse_asset_id(raw)
    if parsed:
        if is_legacy_asset_id(parsed):
            # read, and said: while the older character is read, about one
            # single mistyped character in 36 matches it, so the person
            # typing is told to compare the identifier with the plate
            body = parsed.rsplit("-", 1)[0]
            return True, phrase("registry.legacy_check_character", asset_id=parsed,
                                expected=check_character(body))
        return True, ""
    tidy = re.sub(r"[\s_]+", "", raw.upper())
    if not tidy.startswith("SL-"):
        tidy = "SL-" + tidy
    parts = tidy.split("-")
    if len(parts) != 4:
        return False, ("An identifier looks like SL-WAR-8T4KQ2A-7: country, "
                       "district, position, check character.")
    _, district, code, given = parts
    code = "".join(_FOLD.get(c, c) for c in code)
    if not re.fullmatch(r"[0-9A-Z]{7}", code):
        return False, "The position part should be seven letters or digits."
    expected = check_character(f"SL-{district}-{code}")
    return False, (
        f"The check character does not match: this identifier should end in "
        f"{expected}, not {given}. Something in it has been mistyped.")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

#: kind -> (label, what it establishes about function, is it a service visit).
#: A routine inspection is the area mechanic's visit to the pump and the
#: rising main (PLAN.md step 7.3), at the interval the design sets for the
#: rising main; an ``inspection`` is the sanitary inspection, as it always
#: was. A repair is not counted as a routine inspection: it records what was
#: mended, not that the rest was looked at.
EVENT_KINDS = {
    "commissioned": ("Commissioned", "functional", False),
    "inspection": ("Sanitary inspection", None, True),
    "routine_inspection": ("Routine inspection", None, True),
    "water_sample": ("Water sampled", None, False),
    "repair": ("Repair", "functional", True),
    "failure": ("Failure", "non_functional", True),
    "restored": ("Returned to service", "functional", True),
    "decommissioned": ("Decommissioned", "decommissioned", False),
    "note": ("Note", None, False),
}

#: The order events recorded on one day are read in. Sorting them by kind
#: name put "decommissioned" before "failure", "repair" and "restored", so a
#: hole recorded as collapsed and decommissioned on one visit read "Not
#: working" and stayed due an inspection, and a pump pulled for reuse on the
#: decommissioning day read "Working". This order is a choice, stated: on a
#: day the borehole is commissioned first, then visited, found broken,
#: mended, and only then decommissioned, which is the last thing that can
#: happen to it. Kinds of the same rank keep their name order.
SAME_DAY_ORDER = {
    "commissioned": 0, "inspection": 1, "water_sample": 1, "note": 1,
    "failure": 2, "repair": 3, "restored": 3, "decommissioned": 4,
}


def _day_rank(kind: str) -> int:
    return SAME_DAY_ORDER.get(kind, 1)


FUNCTION_LABELS = {
    "functional": "Working",
    "non_functional": "Not working",
    "decommissioned": "Decommissioned",
    "unknown": "Not known",
}


def _hash32(text: str) -> int:
    """FNV-1a. Small, deterministic, and the same four lines in any language.

    The bytes hashed are the low byte of each UTF-16 code unit, because that
    is what the browser app's ``charCodeAt(i) & 0xFF`` sees. Iterating code
    points instead agrees for everything on the Basic Multilingual Plane and
    diverges on an emoji, and a note with a thumbs-up then carried a
    different identifier on the phone and in the office copy, so the same
    visit no longer merged into one.
    """
    value = 0x811C9DC5
    for low in text.encode("utf-16-le")[::2]:
        value = ((value ^ low) * 0x01000193) & 0xFFFFFFFF
    return value


#: What :func:`trim_field` takes off the ends of a registry field: every
#: character either engine's own trim would take, written out. Python's
#: ``str.strip`` and JavaScript's ``String.trim`` disagree on a handful -
#: Python strips U+001C to U+001F and U+0085, JavaScript the byte order mark
#: U+FEFF - so the same stored answers scored in one engine and not the
#: other. The union, rather than the ASCII blanks the field kit's codes are
#: trimmed of, because event identifiers were already derived from trimmed
#: notes: the union changes no identifier the two engines agreed on.
#: ``TRIMMED`` in gwt-core.js is the twin.
_TRIMMED = ("\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0\u1680"
            + "".join(chr(c) for c in range(0x2000, 0x200B))  # U+2000 to U+200A
            + "\u2028\u2029\u202f\u205f\u3000\ufeff")

#: An ISO day as both engines read one: four digits, two, two, nothing else.
_ISO_DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def trim_field(text) -> str:
    """``text`` with the blanks at its ends taken off, as both engines take them.

    The twin of ``trimField`` in gwt-core.js; see ``_TRIMMED`` for why it
    is not ``str.strip``.
    """
    return str("" if text is None else text).strip(_TRIMMED)


def iso_date(text) -> date | None:
    """The day ``text`` writes as YYYY-MM-DD, or ``None`` when it is not one.

    Strict on purpose, and the same rule as ``isoDay`` in gwt-core.js. From
    Python 3.11 ``date.fromisoformat`` also reads ``20240520`` and
    ``2024-W21-1``, which the browser does not and Python 3.10 does not, so
    one record would have dated a visit in one engine and not the other.
    """
    raw = trim_field(text)
    if not _ISO_DAY_RE.fullmatch(raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def event_id(asset_id: str, when: str, kind: str, note: str = "",
             by: str = "", form: str = "", answers: str = "") -> str:
    """A content-derived identifier, so recording a visit twice merges to one.

    Two people at the same wellhead writing down the same repair on the same
    day produce the same event, and a union of their phones has one entry
    rather than two. The cost is that two genuinely separate events with
    identical wording on the same day also collapse - which is the right way
    round: a duplicated record is a lie about how much maintenance happened.

    A sanitary inspection's form and answers (PLAN.md step 7.5) are part of
    its content, so two forms filled in differently on one day stay two
    records. An event without them hashes as it always did, so no event
    recorded before the form existed changes its identifier.
    """
    content = f"{asset_id}|{when}|{kind}|{trim_field(note)}|{trim_field(by)}"
    if form or answers:
        content += f"|{form}|{answers}"
    digest = _hash32(content)
    tail = "".join(_ALPHABET[(digest >> shift) & 31] for shift in (15, 10, 5, 0))
    return f"{when}/{kind}/{tail}"


@dataclass
class AssetEvent:
    """One thing that happened to a borehole."""

    when: str                # ISO date; kept as written so a bad one is visible
    kind: str
    note: str = ""
    by: str = ""
    photo: str = ""          # a data URL or a path; opaque here
    event_id: str = ""
    #: A sanitary inspection's form (a form id of sanitary_inspection.csv)
    #: and its answers, one letter a question: Y where the risk is present,
    #: N where it is not, - where the question was not answered. Blank on
    #: every other event (PLAN.md step 7.5).
    form: str = ""
    answers: str = ""

    def identified_for(self, asset_id: str) -> AssetEvent:
        """A copy carrying its content-derived id."""
        return AssetEvent(
            when=self.when, kind=self.kind, note=self.note, by=self.by,
            photo=self.photo,
            event_id=self.event_id or event_id(asset_id, self.when, self.kind,
                                               self.note, self.by, self.form,
                                               self.answers),
            form=self.form, answers=self.answers,
        )

    @property
    def label(self) -> str:
        return EVENT_KINDS.get(self.kind, ("Other", None, False))[0]

    @property
    def date(self) -> date | None:
        """The date, or ``None`` when it cannot be read.

        An event whose date is unreadable is kept - throwing away a
        maintenance record because of a typo is worse - but it can never
        establish when anything last happened.
        """
        return iso_date(self.when)

    def as_dict(self) -> dict:
        out = {"when": self.when, "kind": self.kind, "note": self.note,
               "by": self.by, "photo": self.photo}
        # only an event that has them carries them, so a project file with
        # no sanitary inspection in it is written as it was before
        if self.form or self.answers:
            out["form"] = self.form
            out["answers"] = self.answers
        out["event_id"] = self.event_id
        return out


def clean_answers(raw) -> str:
    """A form's answers as stored: Y, N or - for each question, in order.

    Y and N are read in either case; anything else, a blank included, is a
    question not answered, because an answer nobody can read is not a no.
    The ends are trimmed as :func:`trim_field` trims them.
    """
    return "".join("Y" if c in "Yy" else "N" if c in "Nn" else "-"
                   for c in trim_field(raw or ""))


def _coerce_event(raw) -> AssetEvent | None:
    if isinstance(raw, AssetEvent):
        return raw
    if not isinstance(raw, dict):
        return None
    kind = trim_field(raw.get("kind") or "")
    if kind not in EVENT_KINDS:
        kind = "note"
    return AssetEvent(
        when=trim_field(raw.get("when") or ""), kind=kind,
        note=str(raw.get("note") or ""), by=str(raw.get("by") or ""),
        photo=str(raw.get("photo") or ""),
        event_id=str(raw.get("event_id") or ""),
        form=trim_field(raw.get("form") or ""),
        answers=clean_answers(raw.get("answers")),
    )


def merge_events(asset_id: str, *streams) -> list[AssetEvent]:
    """Union of several event streams, in date order.

    This is the whole offline story. Two phones that have been out of touch
    for a fortnight each hold part of the history; merging them is a set
    union over content-derived identifiers, so it needs no clock agreement,
    no server and no conflict resolution. Merging is commutative and
    idempotent: order does not matter and doing it twice changes nothing.
    """
    merged: dict[str, AssetEvent] = {}
    for stream in streams:
        for raw in stream or []:
            event = _coerce_event(raw)
            if event is None:
                continue
            event = event.identified_for(asset_id)
            existing = merged.get(event.event_id)
            if existing is None:
                merged[event.event_id] = event
            elif not existing.photo and event.photo:
                # the only asymmetry: a phone that has the photograph wins,
                # because the alternative is losing it
                merged[event.event_id] = event
    return sorted(merged.values(),
                  key=lambda e: (e.when or "9999", _day_rank(e.kind), e.kind,
                                 e.event_id))


# ---------------------------------------------------------------------------
# The asset
# ---------------------------------------------------------------------------

@dataclass
class Asset:
    """A borehole, as the people who maintain it see it."""

    asset_id: str
    community: str = ""
    district: str = ""
    chiefdom: str = ""
    easting: float | None = None
    northing: float | None = None
    utm_zone: int | None = None
    total_depth_m: float | None = None
    safe_yield_m3_per_h: float | None = None
    pump_type: str = ""
    installed_by: str = ""
    events: list[AssetEvent] = field(default_factory=list)
    #: The area mechanic whose service round the borehole is on (PLAN.md
    #: step 7.3); blank where none is named on the record, and then the
    #: rounds look the chiefdom up instead.
    area_mechanic: str = ""
    #: What the borehole's design specifies for the rising main (PLAN.md
    #: step 7.2), as :func:`clean_rising_main` keeps it: ``material``,
    #: ``inspection_months`` (the routine inspection's interval) and
    #: ``chemistry``. None where the record carries none, and then the
    #: routine inspection is due at the schedule's shorter interval.
    rising_main: dict | None = None
    #: The issue records of the documents issued about this borehole
    #: (PLAN.md step 8.1), as :func:`groundwater.verification.
    #: clean_issue_records` keeps them, so a copy of one can be checked
    #: against the register.
    documents: list[dict] = field(default_factory=list)

    @property
    def latlon(self) -> tuple[float, float] | None:
        if self.easting is None or self.northing is None:
            return None
        zone = self.utm_zone or infer_zone_for_sierra_leone(float(self.easting))
        try:
            return utm_to_geographic(float(self.easting), float(self.northing),
                                     int(zone))
        except Exception:  # noqa: BLE001 - a bad coordinate simply has no fix
            return None

    @property
    def label(self) -> str:
        place = self.community or "(unnamed site)"
        return f"{place} ({self.district})" if self.district else place

    def with_events(self, *streams) -> Asset:
        """A copy carrying the merged union of this asset's events and more."""
        return Asset(**{**self.__dict__,
                        "events": merge_events(self.asset_id, self.events,
                                               *streams)})

    def as_dict(self) -> dict:
        payload = {k: v for k, v in self.__dict__.items()
                   if k not in ("events", "area_mechanic", "rising_main", "documents")}
        # only a record that has them carries them, so a project file with
        # no mechanic named, no rising main and no document issued is
        # written as it was before
        if self.area_mechanic:
            payload["area_mechanic"] = self.area_mechanic
        if self.rising_main is not None:
            payload["rising_main"] = dict(self.rising_main)
        if self.documents:
            payload["documents"] = [dict(record) for record in self.documents]
        payload["events"] = [e.identified_for(self.asset_id).as_dict()
                             for e in self.events]
        return payload


#: The longest interval a record may set, in months: a hundred years. A
#: longer one is not an interval anybody meant, and its due date would pass
#: the year 9999 the calendar ends at.
_MAX_MONTHS = 1200


def _whole(value) -> bool:
    """Whether ``value`` is a whole number, as JavaScript and Python both
    read one: 5.0 is 5, true is not a number, and an int past a double
    (which the browser reads as Infinity) is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value == int(value)
    except OverflowError:
        return False


def _whole_months(value) -> int | None:
    """``value`` as a number of months from 1 to 1200, or None when it is not
    a whole number in that range."""
    if not _whole(value) or not 1 <= value <= _MAX_MONTHS:
        return None
    return int(value)


def _text_field(value) -> str:
    """A text field of a record, trimmed, or blank when it is not text."""
    return trim_field(value) if isinstance(value, str) else ""


def clean_rising_main(raw) -> dict | None:
    """The rising main a record carries, as both engines keep it, or None.

    ``raw`` is a design's rising main (``rising_main_choice``) or a stored
    record's. The interval has to be a whole number of months from 1 to
    1200, or the record carries no rising main at all, since the interval is
    what the routine inspection is due by; the material is trimmed, and the
    chemistry is kept only when it is one of the states the design names.
    """
    if not isinstance(raw, dict):
        return None
    months = _whole_months(raw.get("inspection_months"))
    if months is None:
        return None
    chemistry = _text_field(raw.get("chemistry"))
    return {"material": _text_field(raw.get("material")),
            "inspection_months": months,
            "chemistry": chemistry if chemistry in phrase_table("rounds.water") else ""}


def asset_with_rising_main(asset: Asset, rising_main) -> Asset:
    """A copy of ``asset`` carrying the rising main of its project's design.

    The design is the latest word on the borehole's rising main, so the apps
    pass the current project's record through this before showing or saving
    it. A design with no rising main (or none) leaves the record as it is.
    """
    clean = clean_rising_main(rising_main)
    if clean is None:
        return asset
    return Asset(**{**asset.__dict__, "rising_main": clean})


def asset_from_dict(payload: dict) -> Asset | None:
    """Rebuild an asset from a saved project file, or ``None`` if it is not one."""
    if not isinstance(payload, dict):
        return None
    asset_id = parse_asset_id(payload.get("asset_id"))
    if not asset_id:
        return None
    from .verification import clean_issue_records

    known = {f for f in Asset.__dataclass_fields__
             if f not in ("events", "area_mechanic", "rising_main", "documents")}
    fields = {k: v for k, v in payload.items() if k in known}
    fields["asset_id"] = asset_id
    asset = Asset(**fields)
    asset.area_mechanic = _text_field(payload.get("area_mechanic"))
    asset.rising_main = clean_rising_main(payload.get("rising_main"))
    asset.events = merge_events(asset_id, payload.get("events") or [])
    asset.documents = clean_issue_records(payload.get("documents"))
    return asset


def asset_from_project(state: dict) -> Asset | None:
    """Draft an asset from an assembled project, or ``None`` without a position.

    Nothing is invented: the commissioning event is not written here, because
    a borehole is commissioned by somebody deciding it is, on a day, and that
    decision is a record with a name on it rather than a side effect of
    opening a page. The draft carries the issue records of the documents
    issued about the borehole from the project (its ``issued``), so a record
    first stored after they were issued holds them (PLAN.md step 8.1).
    """
    from .verification import borehole_records

    site = _project_site(state)
    if site is None:
        return None
    try:
        asset_id = mint_asset_id(site)
    except ValueError:
        return None
    log = state.get("drilling_log")
    analysis = state.get("pump_analysis")
    depth = getattr(log, "total_depth_m", None) if log is not None else None
    recommendation = getattr(analysis, "yield_recommendation", None)
    design = state.get("borehole_design")
    return Asset(
        rising_main=clean_rising_main(getattr(design, "rising_main", None)),
        asset_id=asset_id,
        community=getattr(site, "community", "") or "",
        district=getattr(site, "district", "") or "",
        chiefdom=getattr(site, "chiefdom", "") or "",
        easting=getattr(site, "easting", None),
        northing=getattr(site, "northing", None),
        utm_zone=getattr(site, "utm_zone", None),
        total_depth_m=depth,
        safe_yield_m3_per_h=getattr(recommendation, "safe_yield_m3_per_h", None),
        installed_by=getattr(site, "contractor", "") or "",
        documents=borehole_records(state.get("issued")),
    )


def _project_site(state: dict):
    """The site metadata, merged across the sheets that carry any of it."""
    candidates = [state.get("site")]
    log = state.get("drilling_log")
    if log is not None:
        candidates.append(getattr(log, "site", None))
    analysis = state.get("pump_analysis")
    if analysis is not None:
        candidates.append(getattr(getattr(analysis, "test", None), "site", None))
    assessment = state.get("wq_assessment")
    if assessment is not None:
        candidates.append(getattr(getattr(assessment, "sample", None), "site",
                                  None))
    merged = None
    for site in candidates:
        if site is None:
            continue
        if merged is None:
            merged = site
            continue
        try:
            merged = merged.merged_with(site)
        except AttributeError:  # noqa: PERF203 - a plain object is fine as-is
            continue
    if merged is None:
        return None
    return merged if getattr(merged, "easting", None) is not None else None


# ---------------------------------------------------------------------------
# What is true today
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Schedule:
    """How often a point should be visited.

    These are a programme's choices, not a standard (``config.ServiceConfig``
    says why each value is what it is): the defaults are the ``service``
    section of ``data/defaults.json``, and :meth:`from_config` reads them
    from a configuration. Change them there and every due date in the
    registry moves with them.

    The routine inspection of the pump and rising main is due at the interval
    the borehole's record carries from its design (``Asset.rising_main``,
    PLAN.md step 7.2); ``routine_inspection_months`` is the interval for a
    record that carries none, the design rules' interval for water whose
    corrosivity is not known.
    """

    sanitary_inspection_months: int = ServiceConfig().sanitary_inspection_months
    water_sample_months: int = ServiceConfig().water_sample_months
    #: How long past due before an item stops being "due" and starts being
    #: "overdue". A visit is a journey, not a diary entry.
    grace_days: int = ServiceConfig().grace_days
    routine_inspection_months: int = DesignRules().aggressive_rising_main_inspection_months

    def __post_init__(self) -> None:
        """Refuse an interval no due date can be counted with, as
        ``checkSchedule`` refuses it in the browser: a configuration that
        set one would otherwise give a due date in one engine and an error
        or nonsense in the other."""
        for name in ("sanitary_inspection_months", "water_sample_months",
                     "routine_inspection_months"):
            months = _whole_months(getattr(self, name))
            if months is None:
                raise ValueError(f"schedule: {name} must be a whole number of months "
                                 f"from 1 to {_MAX_MONTHS}")
            object.__setattr__(self, name, months)
        grace = self.grace_days
        if not _whole(grace) or grace < 0:
            raise ValueError("schedule: grace_days must be a whole number of days, 0 or more")
        object.__setattr__(self, "grace_days", int(grace))

    @classmethod
    def from_config(cls, config: Config | None = None) -> Schedule:
        """The schedule a configuration sets: its ``service`` section, and
        its design rules' interval for a rising main in water whose
        corrosivity is not known."""
        config = config or Config()
        return cls(sanitary_inspection_months=config.service.sanitary_inspection_months,
                   water_sample_months=config.service.water_sample_months,
                   grace_days=config.service.grace_days,
                   routine_inspection_months=config.design.aggressive_rising_main_inspection_months)


@dataclass(frozen=True)
class DueItem:
    key: str
    title: str
    due_on: date | None
    state: str          # "scheduled" | "due" | "overdue" | "unknown"
    detail: str
    #: The interval it is due by, in months, and where that comes from.
    months: int = 0
    basis: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "state": self.state,
                "due_on": self.due_on.isoformat() if self.due_on else None,
                "detail": self.detail, "months": self.months, "basis": self.basis}


@dataclass(frozen=True)
class AssetState:
    """What the event stream says about the borehole now."""

    function: str
    since: date | None
    detail: str
    last_inspection: date | None
    last_sample: date | None
    commissioned: date | None
    days_out_of_service: int | None
    due: tuple[DueItem, ...]
    undated_events: int
    last_routine_inspection: date | None = None

    @property
    def label(self) -> str:
        return FUNCTION_LABELS.get(self.function, "Not known")

    @property
    def is_working(self) -> bool:
        """True only when something says so. ``unknown`` is not a yes."""
        return self.function == "functional"

    @property
    def overdue(self) -> tuple[DueItem, ...]:
        return tuple(item for item in self.due if item.state == "overdue")

    def as_dict(self) -> dict:
        return {
            "function": self.function, "label": self.label,
            "since": self.since.isoformat() if self.since else None,
            "detail": self.detail,
            "last_inspection": self.last_inspection.isoformat()
            if self.last_inspection else None,
            "last_sample": self.last_sample.isoformat()
            if self.last_sample else None,
            "last_routine_inspection": self.last_routine_inspection.isoformat()
            if self.last_routine_inspection else None,
            "commissioned": self.commissioned.isoformat()
            if self.commissioned else None,
            "days_out_of_service": self.days_out_of_service,
            "due": [item.as_dict() for item in self.due],
            "undated_events": self.undated_events,
        }


def _add_months(start: date, months: int) -> date | None:
    """``months`` after ``start``, or None when that is past the year 9999,
    the last a date can hold in either engine."""
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    if year > 9999:
        return None
    # clamp rather than roll over: six months from 31 August is 28 February,
    # not 3 March, and a due date that drifts forward is one that gets missed
    day = min(start.day, [31, 29 if year % 4 == 0 and (year % 100 or not
                                                       year % 400) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def asset_state(asset: Asset, today: date | None = None,
                schedule: Schedule | None = None) -> AssetState:
    """Reduce the event stream to the borehole's condition on ``today``."""
    today = today or date.today()
    schedule = schedule or Schedule()
    events = merge_events(asset.asset_id, asset.events)
    dated = [(e.date, e) for e in events if e.date is not None]
    dated.sort(key=lambda pair: (pair[0], _day_rank(pair[1].kind), pair[1].kind,
                                 pair[1].event_id))
    undated = sum(1 for e in events if e.date is None)

    function, since, detail = "unknown", None, (
        "Nothing has been recorded against this borehole, so whether it is "
        "working is not known.")
    commissioned = last_inspection = last_sample = last_routine = None
    after_decommissioning: list[AssetEvent] = []
    for when, event in dated:
        if when > today:
            continue  # a record dated in the future settles nothing yet
        establishes = EVENT_KINDS.get(event.kind, ("", None, False))[1]
        if (establishes and function == "decommissioned"
                and event.kind != "commissioned"):
            # Decommissioning is terminal: a repair or a failure logged after
            # it stays in the history but does not bring the borehole back.
            # Only a new commissioning record does. A second decommissioning
            # record changes nothing, as a second failure report does not.
            if establishes != "decommissioned":
                after_decommissioning.append(event)
        elif establishes and establishes != function:
            # Only a change moves "since". A villager reporting a broken pump
            # again in May, as the plate reports of PLAN.md step 7.1 will,
            # restarted the count from May, so a borehole out since January
            # showed 12 days out of service rather than 143.
            function, since = establishes, when
            detail = f"{event.label} recorded on {when.isoformat()}"
            if event.by:
                detail += f" by {event.by}"
            after_decommissioning = []
        if event.kind == "commissioned" and commissioned is None:
            commissioned = when
        if event.kind == "inspection":
            last_inspection = when
        if event.kind == "routine_inspection":
            last_routine = when
        if event.kind == "water_sample":
            last_sample = when

    if function == "decommissioned" and after_decommissioning:
        detail += ". " + phrase(
            "registry.after_decommissioning", n=len(after_decommissioning),
            events=and_join([phrase("registry.event_on", event=e.label.lower(),
                                    when=e.when) for e in after_decommissioning]))
    out_for = ((today - since).days
               if function == "non_functional" and since else None)
    if undated and function == "unknown":
        detail = (f"{undated} record(s) carry a date nobody can read, so "
                  "nothing can be established from them.")

    due: list[DueItem] = []
    if function != "decommissioned":
        months = schedule.sanitary_inspection_months
        due.append(_due_item(
            "inspection", "Sanitary inspection", last_inspection, commissioned,
            months, schedule.grace_days, today,
            "A sanitary inspection is what catches a cracked apron or a "
            "latrine dug uphill before the water shows it.",
            phrase("rounds.basis_sanitary", months=months)))
        months, basis = _routine_interval(asset, schedule)
        due.append(_due_item(
            "routine_inspection", EVENT_KINDS["routine_inspection"][0], last_routine,
            commissioned, months, schedule.grace_days, today,
            phrase("rounds.routine_why"), basis))
        months = schedule.water_sample_months
        due.append(_due_item(
            "water_sample", "Water quality sample", last_sample, commissioned,
            months, schedule.grace_days, today,
            "Water that was safe at handover is not evidence that it is safe "
            "now: the aquifer, the headworks and the catchment all change.",
            phrase("rounds.basis_sample", months=months)))
    return AssetState(
        function=function, since=since, detail=detail,
        last_inspection=last_inspection, last_sample=last_sample,
        commissioned=commissioned, days_out_of_service=out_for,
        due=tuple(item for item in due if item is not None),
        undated_events=undated, last_routine_inspection=last_routine,
    )


def _routine_interval(asset: Asset, schedule: Schedule) -> tuple[int, str]:
    """The routine inspection's interval in months, and where it comes from:
    the rising main the record carries from the design, else the schedule's
    interval for a record that carries none."""
    rising = clean_rising_main(getattr(asset, "rising_main", None))
    if rising is None:
        months = schedule.routine_inspection_months
        return months, phrase("rounds.basis_default", months=months)
    months = rising["inspection_months"]
    if rising["material"] and rising["chemistry"]:
        return months, phrase("rounds.basis_design", months=months,
                              material=rising["material"],
                              water=phrase_table("rounds.water")[rising["chemistry"]])
    return months, phrase("rounds.basis_record", months=months)


def _due_item(key: str, title: str, last: date | None, commissioned: date | None,
              months: int, grace_days: int, today: date, why: str,
              basis: str) -> DueItem:
    anchor = last or commissioned
    if anchor is None:
        return DueItem(key, title, None, "unknown",
                       f"No {title.lower()} has been recorded, and there is no "
                       f"commissioning date to count from. {why}", months, basis)
    due_on = _add_months(anchor, months)
    if due_on is None:
        return DueItem(key, title, None, "scheduled",
                       phrase("rounds.beyond", title=title.lower()), months, basis)
    late = (today - due_on).days
    if late > grace_days:
        never = "" if last else "has never been done; it "
        return DueItem(key, title, due_on, "overdue",
                       f"{title} {never}has been due since "
                       f"{due_on.isoformat()}, {late} days ago. {why}", months, basis)
    if late > 0:
        return DueItem(key, title, due_on, "due",
                       f"{title} fell due on {due_on.isoformat()}.", months, basis)
    return DueItem(key, title, due_on, "scheduled",
                   f"Next {title.lower()} due {due_on.isoformat()}.", months, basis)


# ---------------------------------------------------------------------------
# What goes on the borehole itself
# ---------------------------------------------------------------------------

def qr_payload(asset: Asset) -> str:
    """The text the QR code carries.

    Plain text rather than a link. A link is only useful where there is a
    network, and the whole reason this symbol is on the headworks is that
    there is not one - a technician who scans it should see the identifier,
    the place and the position on the screen immediately, with nothing to
    load and nothing to install.
    """
    lines = [f"BOREHOLE {asset.asset_id}", asset.label]
    latlon = asset.latlon
    if latlon is not None:
        lat, lon = latlon
        lines.append(f"{abs(lat):.5f} {'N' if lat >= 0 else 'S'}, "
                     f"{abs(lon):.5f} {'E' if lon >= 0 else 'W'}")
    facts = []
    if asset.total_depth_m:
        facts.append(f"{float(asset.total_depth_m):.1f} m deep")
    if asset.safe_yield_m3_per_h:
        facts.append(f"{float(asset.safe_yield_m3_per_h):.2f} m3/h")
    if asset.pump_type:
        facts.append(asset.pump_type)
    if facts:
        lines.append(", ".join(facts))
    return "\n".join(lines)


def placard_lines(asset: Asset, state: AssetState | None = None) -> list[tuple[str, str]]:
    """Field-value rows for the plate that gets fixed to the headworks."""
    rows = [("Identifier", asset.asset_id), ("Community", asset.community or "-")]
    if asset.district:
        rows.append(("District", asset.district))
    latlon = asset.latlon
    if latlon is not None:
        rows.append(("Position", f"{latlon[0]:.5f} N, {abs(latlon[1]):.5f} W"))
    if asset.total_depth_m:
        rows.append(("Depth", f"{float(asset.total_depth_m):.1f} m"))
    if asset.safe_yield_m3_per_h:
        rows.append(("Safe yield", f"{float(asset.safe_yield_m3_per_h):.2f} m3/h"))
    if asset.pump_type:
        rows.append(("Pump", asset.pump_type))
    if asset.installed_by:
        rows.append(("Installed by", asset.installed_by))
    if state is not None:
        if state.commissioned:
            rows.append(("Commissioned", state.commissioned.isoformat()))
        rows.append(("Status", state.label))
    return rows


# ---------------------------------------------------------------------------
# Many of them
# ---------------------------------------------------------------------------

def registry_rows(assets, today: date | None = None,
                  schedule: Schedule | None = None) -> list[dict]:
    """One formatted row per asset, for the registry table."""
    today = today or date.today()
    rows = []
    for asset in assets:
        state = asset_state(asset, today, schedule)
        overdue = state.overdue
        rows.append({
            "Identifier": asset.asset_id,
            "Community": asset.community or "(unnamed)",
            "District": asset.district or "",
            "Status": state.label,
            "Since": state.since.isoformat() if state.since else "",
            "Last inspected": state.last_inspection.isoformat()
            if state.last_inspection else "",
            "Last sampled": state.last_sample.isoformat()
            if state.last_sample else "",
            "Overdue": ", ".join(item.title for item in overdue),
            "Events": len(asset.events),
        })
    return rows


def registry_stats(assets, today: date | None = None,
                   schedule: Schedule | None = None) -> dict:
    """Headline counts.

    ``n_unknown`` is reported beside the working and broken counts and never
    folded into either. A register where most points are unknown looks very
    like one where most points are working, unless the number is on the
    page next to them.
    """
    today = today or date.today()
    assets = list(assets)
    counts = {key: 0 for key in FUNCTION_LABELS}
    overdue_by_key: dict[str, int] = {}
    out_days = []
    for asset in assets:
        state = asset_state(asset, today, schedule)
        counts[state.function] = counts.get(state.function, 0) + 1
        if state.days_out_of_service is not None:
            out_days.append(state.days_out_of_service)
        for item in state.overdue:
            overdue_by_key[item.key] = overdue_by_key.get(item.key, 0) + 1
    known = counts["functional"] + counts["non_functional"]
    return {
        "n_assets": len(assets),
        "n_functional": counts["functional"],
        "n_non_functional": counts["non_functional"],
        "n_decommissioned": counts["decommissioned"],
        "n_unknown": counts["unknown"],
        # over the points whose condition is actually known, and None when
        # none of them are - a functionality rate computed over silence is
        # the number that makes these registers untrustworthy
        "functionality_rate": (counts["functional"] / known * 100.0)
        if known else None,
        "n_overdue_inspection": overdue_by_key.get("inspection", 0),
        "n_overdue_routine": overdue_by_key.get("routine_inspection", 0),
        "n_overdue_sample": overdue_by_key.get("water_sample", 0),
        "mean_days_out_of_service": (sum(out_days) / len(out_days))
        if out_days else None,
    }

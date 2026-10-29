"""Reports on a borehole from its plate and by SMS (PLAN.md step 7.1).

The registry knows a borehole only as well as somebody tells it, and the
people who know first are the ones who pump it. This module turns what they
say into registry records, from three ways of saying it:

**The report page.** A plate's QR code, once the programme sets the browser
app's address (``service.report_url``), is a link to ``#/report/<identifier>``
in that app, which offers four choices - working, broken, slow, or bad taste
or colour - with a date, a name, a note and a photograph, all but the choice
and the date optional. :func:`report_record` makes the report.

**SMS.** A phone with no browser sends ``BH <identifier> <WORD> [note]``, the
word one of WORKING, BROKEN, SLOW, or TASTE, COLOUR, COLOR or BAD (A to Z
read in either case; the table is ``fault_reports.sms_words`` in the
catalogue). No gateway
is built and none is needed: a programme that runs one hands what it
receives to :func:`receive_messages`, the adapter's whole interface, a list
of messages each with its ``text`` and, where the gateway gives them, the
time it was ``received`` (written YYYY-MM-DD first) and the ``sender``.
Without one, a plain-text file of the messages, one a line with the time
received and the sender before ``BH`` where the copy has them, is read by
:func:`read_sms_lines`. Both apps import such a file.

**A file of reports.** The browser keeps the reports made on a phone in a
queue until the registry they belong to is opened there, and can write them
to a small file for whoever holds it (:func:`reports_file`), which either app
reads back (:func:`read_reports_file`).

Every report is a record: ``accepted``, ``held`` or ``refused``, with the
``reason`` when it is not accepted. The identifier is checked by the
registry's own :func:`registry.validate_asset_id`, so a mistyped one is
refused with what it should have ended in, and anything that function reads
with a note rather than plainly (an identifier minted with an older check
character) is held for a person to confirm when it comes by SMS, since an
SMS has nobody reading the note as it is typed; on the report page the app
shows the note to the person at the plate. An accepted report becomes an
event (:func:`report_event`): broken is a ``failure``, working a
``reported_working``, slow a ``reported_slow`` and bad taste or colour a
``quality_complaint`` (``registry.EVENT_KINDS`` says what each establishes).
:func:`merge_reports` adds them to the boreholes they name by the registry's
own rule, a union over content-derived identifiers, so the same report
imported twice, or sent twice in a day by one sender in the same words, is
one record.

Nothing here reads the clock. A report's day is the day the person gave, or
the day the gateway or the file says it was received, or a day the person
importing gives for lines that carry none; a line with no day at all is
refused rather than dated on the day it happened to be imported.

Every function here has a twin in ``gwt-core.js``.
"""

from __future__ import annotations

import re

from . import registry as _registry
from .registry import (
    _TRIMMED,
    Asset,
    AssetEvent,
    _coerce_event,
    asset_from_dict,
    clean_photo_provenance,
    iso_date,
    merge_events,
    parse_asset_id,
    trim_field,
)
from .text import phrase, phrase_table

__all__ = [
    "CHOICES",
    "KINDS",
    "REPORTS_FORMAT",
    "REPORTS_VERSION",
    "confirm_report",
    "import_summary",
    "merge_reports",
    "parse_sms",
    "read_reports_file",
    "read_sms_lines",
    "receive_messages",
    "report_event",
    "report_header",
    "report_record",
    "report_rows",
    "reports_file",
    "sms_format",
]

#: What a report can say, in the order the report page offers it.
CHOICES = ("working", "broken", "slow", "taste")

#: The registry event each choice is recorded as.
KINDS = {"working": "reported_working", "broken": "failure",
         "slow": "reported_slow", "taste": "quality_complaint"}

#: The file of reports a phone exports: its ``format`` and ``version``.
REPORTS_FORMAT = "gwt-borehole-reports"
REPORTS_VERSION = 1

#: A run of the blanks :func:`registry.trim_field` takes off a field's ends,
#: which is what separates the words of a message, the same in both engines.
_BLANKS = re.compile("[" + re.escape(_TRIMMED) + "]+")
#: The same, with the commas and semicolons a copied list puts between the
#: time received, the sender and the message.
_FIELD_BREAKS = re.compile("[" + re.escape(_TRIMMED) + ",;]+")
#: The word that starts a report, as a word of its own.
_BH = re.compile("(?:^|[" + re.escape(_TRIMMED) + ",;])(BH)(?=[" + re.escape(_TRIMMED)
                 + "]|$)", re.IGNORECASE)
#: A day written year, month and day, alone or as the start of a time.
_ISO_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
                       r"(?:T[0-9]{1,2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?"
                       r"(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?")
#: A time of day written alone.
_CLOCK = re.compile(r"[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?")
#: Anything else that looks like a day: 01/05/2026, 1.5.26, 2026/05/01.
_OTHER_DAY = re.compile(r"[0-9]{1,4}[/.-][0-9]{1,2}[/.-][0-9]{1,4}")
#: The day at the start of a time received as a gateway writes it.
_DAY_FIRST = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[T ]|$)")

_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _text(value) -> str:
    """A field of a report, trimmed, or blank when it is not text."""
    return trim_field(value) if isinstance(value, str) else ""


def _words() -> str:
    """The SMS words, "WORKING, BROKEN, ... or BAD"."""
    words = list(phrase_table("fault_reports.sms_words"))
    return ", ".join(words[:-1]) + " or " + words[-1]


def _record(**fields) -> dict:
    """A report with every field, in the order both engines write them."""
    out = {"status": "refused", "reason": "", "asset_id": "", "typed": "",
           "choice": "", "kind": "", "when": "", "note": "", "by": "",
           "photo": "", "photo_provenance": None,
           "line": None, "text": "", "received": "", "sender": ""}
    out.update(fields)
    return out


def report_record(asset_id, choice, when, note: object = "", by: object = "",
                  photo: object = "", photo_provenance: object = None) -> dict:
    """A report as the report page makes it: on the borehole ``asset_id``,
    one of :data:`CHOICES`, on the day ``when`` (YYYY-MM-DD, the page's
    input), with an optional note, name and photograph (a data URL) with its
    provenance record.

    Refused, with the reason, when the identifier does not check (the
    registry's own words), when the choice is not one of the four or when
    the day is not one. Otherwise accepted: an identifier the registry reads
    with a note is accepted here, since the page shows the note to the
    person at the plate.
    """
    typed = _text(asset_id)
    ok, reason = _registry.validate_asset_id(typed)
    if not ok:
        return _record(reason=reason, typed=typed)
    parsed = parse_asset_id(typed) or ""
    if choice not in CHOICES:
        return _record(reason=phrase("fault_reports.no_choice"), asset_id=parsed,
                       typed=typed)
    day = _text(when)
    if iso_date(day) is None:
        reason = (phrase("fault_reports.bad_day", when=day) if day
                  else phrase("fault_reports.no_day"))
        return _record(reason=reason, asset_id=parsed, typed=typed, choice=choice)
    picture = photo if isinstance(photo, str) else ""
    return _record(status="accepted", asset_id=parsed, typed=typed, choice=choice,
                   kind=KINDS[choice], when=day, note=_text(note), by=_text(by),
                   photo=picture,
                   photo_provenance=clean_photo_provenance(photo_provenance)
                   if picture else None)


def _sms(message, day: str, received: str, sender: str, line, text: str) -> dict:
    """An SMS report from ``message`` received on ``day`` (blank when there
    is none), with what to show of the line it came from."""
    shown = {"line": line, "text": text, "received": received, "sender": sender}
    words = [w for w in _BLANKS.split(_text(message)) if w]
    if not words or words[0].translate(_UPPER) != "BH":
        return _record(reason=phrase("fault_reports.no_bh", words=_words()), **shown)
    if len(words) < 2:
        return _record(reason=phrase("fault_reports.no_identifier", words=_words()), **shown)
    typed = words[1]
    if len(words) < 3:
        return _record(reason=phrase("fault_reports.no_word", words=_words()), typed=typed,
                       **shown)
    ok, reason = _registry.validate_asset_id(typed)
    if not ok:
        return _record(reason=reason, typed=typed, **shown)
    parsed = parse_asset_id(typed) or ""
    choice = phrase_table("fault_reports.sms_words").get(words[2].translate(_UPPER))
    if choice is None:
        return _record(reason=phrase("fault_reports.unknown_word", word=words[2],
                                     words=_words()),
                       asset_id=parsed, typed=typed, **shown)
    found = {"asset_id": parsed, "typed": typed, "choice": choice}
    if not day:
        return _record(reason=phrase("fault_reports.no_date"), **found, **shown)
    if iso_date(day) is None:
        return _record(reason=phrase("fault_reports.bad_date", date=day), **found, **shown)
    by = (phrase("fault_reports.sms_by", sender=sender) if sender
          else phrase("fault_reports.sms_by_unknown"))
    fields = {**found, "kind": KINDS[choice], "when": day, "note": " ".join(words[3:]),
              "by": by, **shown}
    if reason:
        # read, but with a note the registry shows to whoever types the
        # identifier; an SMS has nobody to show it to as it is typed
        return _record(status="held", reason=phrase("fault_reports.held", note=reason),
                       **fields)
    return _record(status="accepted", **fields)


def _day_of(received: str, received_on) -> str:
    """The day a report was received on: the day the time received begins
    with, else the day given for messages that carry none. The time
    received as written when it does not begin with a day, so the refusal
    names it."""
    if received:
        match = _DAY_FIRST.match(received)
        return match.group(1) if match else received
    return _text(received_on)


def parse_sms(text, received="", sender="", received_on="") -> dict:
    """One SMS, ``BH <identifier> <WORD> [note]``, as a report.

    ``received`` is the time it was received as the gateway writes it, read
    only when it begins with a day written YYYY-MM-DD; ``sender`` is who sent
    it, kept as the report's "by" ("SMS from ..."); ``received_on`` is the
    day for a message that carries no time received, an input of whoever
    imports it, and with neither the report is refused. A word after the
    identifier other than the catalogue's is refused, and anything after the
    word is kept as the note.
    """
    stamp, who = _text(received), _text(sender)
    return _sms(text, _day_of(stamp, received_on), stamp, who, None, _text(text))


def receive_messages(messages, received_on="") -> list[dict]:
    """The interface of an SMS gateway adapter, which is optional.

    ``messages`` are what a gateway received, in order, each a mapping with
    the message's ``text`` and, where the gateway gives them, the time it
    was ``received`` and the ``sender`` (or the message's text alone). Each
    becomes a report, as :func:`parse_sms` reads it, numbered from 1 in
    ``line``. Nothing is sent back to the sender and nothing is merged: the
    reports go where the apps' imports put them.
    """
    out = []
    for number, message in enumerate(messages if isinstance(messages, list) else [], start=1):
        if isinstance(message, str):
            message = {"text": message}
        if not isinstance(message, dict):
            message = {}
        stamp, who = _text(message.get("received")), _text(message.get("sender"))
        text = _text(message.get("text"))
        out.append(_sms(text, _day_of(stamp, received_on), stamp, who, number, text))
    return out


def read_sms_lines(text, received_on="") -> list[dict]:
    """A plain-text file of SMS messages, one a line, as reports.

    Before ``BH`` a line may carry the time received - a day written
    YYYY-MM-DD, alone or with a time after a T, then perhaps a time of day -
    and the sender, separated by blanks, commas or semicolons; whatever else
    is there is the sender. A day written any other way (01/05/2026) is
    refused, not guessed, and so is a line with two days. ``received_on`` is
    the day for lines that carry none. Blank lines are skipped; ``line`` is
    the line's number in the file.
    """
    out = []
    raw = text if isinstance(text, str) else ""
    for number, line in enumerate(re.split(r"\r\n|\r|\n", raw), start=1):
        shown = trim_field(line)
        if not shown:
            continue
        found = _BH.search(shown)
        if found is None:
            out.append(_record(reason=phrase("fault_reports.no_bh", words=_words()),
                               line=number, text=shown))
            continue
        days, clock, sender = [], [], []
        for token in _FIELD_BREAKS.split(shown[:found.start(1)]):
            if not token:
                continue
            if _ISO_TIME.fullmatch(token):
                days.append(token)
            elif _CLOCK.fullmatch(token):
                clock.append(token)
            elif _OTHER_DAY.fullmatch(token):
                out.append(_record(reason=phrase("fault_reports.bad_date", date=token),
                                   line=number, text=shown))
                break
            else:
                sender.append(token)
        else:
            stamp = " ".join(days + clock)
            who = " ".join(sender)
            if len(days) > 1:
                out.append(_record(reason=phrase("fault_reports.two_dates", first=days[0],
                                                 second=days[1]),
                                   line=number, text=shown, received=stamp, sender=who))
                continue
            day = days[0][:10] if days else _text(received_on)
            out.append(_sms(shown[found.start(1):], day, stamp, who, number, shown))
    return out


def confirm_report(record: dict) -> dict:
    """A held report, confirmed by a person: the same report, accepted.

    Only a held report can be confirmed; anything else is returned as it is.
    """
    if not isinstance(record, dict) or record.get("status") != "held":
        return record
    return {**record, "status": "accepted", "reason": ""}


def report_event(record: dict) -> AssetEvent:
    """The registry event an accepted report is recorded as, read as the
    registry reads any saved event, so a record from a hand-edited queue
    or file becomes the same event in both engines."""
    event = _coerce_event({key: record.get(key) for key in
                           ("when", "kind", "note", "by", "photo", "photo_provenance")})
    assert event is not None  # a mapping always reads as an event
    return event


def merge_reports(assets, records) -> dict:
    """The accepted ``records`` merged into the boreholes they name.

    ``assets`` are registry assets (or their saved records); each comes back
    with the reports that name its identifier merged into its history by the
    registry's rule, and the others as they were. ``added`` counts the
    records new to a history and ``already`` those it already held (the same
    report imported twice, or sent twice in a day by one sender);
    ``unmatched`` are the accepted reports that name none of the boreholes.
    Held and refused reports are not merged.
    """
    accepted = [r for r in (records if isinstance(records, list) else [])
                if isinstance(r, dict) and r.get("status") == "accepted"]
    matched: set[int] = set()
    out, added, already = [], 0, 0
    for raw in assets if isinstance(assets, list) else []:
        asset = raw if isinstance(raw, Asset) else asset_from_dict(raw)
        if asset is None:
            continue
        mine = [(i, r) for i, r in enumerate(accepted) if r.get("asset_id") == asset.asset_id]
        if not mine:
            out.append(asset)
            continue
        known = {e.event_id for e in merge_events(asset.asset_id, asset.events)}
        events = [report_event(r) for _, r in mine]
        ids = {e.identified_for(asset.asset_id).event_id for e in events}
        added += len(ids - known)
        already += len(ids & known)
        matched.update(i for i, _ in mine)
        out.append(asset.with_events(events))
    return {"assets": out, "added": added, "already": already,
            "unmatched": [r for i, r in enumerate(accepted) if i not in matched]}


def reports_file(records) -> dict:
    """The accepted ``records`` as the file a phone exports: what each says
    of which borehole on which day, with its note, name and photograph."""
    out = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict) or record.get("status") != "accepted":
            continue
        # each field as text, so a hand-edited record is written the same by
        # both engines; read back, every report is checked again anyway
        entry: dict[str, object] = {key: _text(record.get(key))
                                    for key in ("asset_id", "choice", "when", "note", "by")}
        photo = record.get("photo")
        if isinstance(photo, str) and photo:
            entry["photo"] = photo
            provenance = clean_photo_provenance(record.get("photo_provenance"))
            if provenance is not None:
                entry["photo_provenance"] = provenance
        out.append(entry)
    return {"format": REPORTS_FORMAT, "version": REPORTS_VERSION, "reports": out}


def read_reports_file(payload) -> list[dict]:
    """The reports in a file :func:`reports_file` wrote, each checked again
    as the report page checks one, and numbered from 1 in ``line``.

    A file that is not one of this format and version is refused whole
    (ValueError, in the catalogue's words).
    """
    if (not isinstance(payload, dict) or payload.get("format") != REPORTS_FORMAT
            or not _registry._whole(payload.get("version"))
            or payload.get("version") != REPORTS_VERSION
            or not isinstance(payload.get("reports"), list)):
        raise ValueError(phrase("fault_reports.file_refused"))
    out = []
    for number, entry in enumerate(payload["reports"], start=1):
        entry = entry if isinstance(entry, dict) else {}
        record = report_record(_text(entry.get("asset_id")), entry.get("choice"),
                               entry.get("when"), entry.get("note"), entry.get("by"),
                               entry.get("photo"), entry.get("photo_provenance"))
        out.append({**record, "line": number})
    return out


def report_header() -> list[str]:
    """The header of the table of an import, in both apps."""
    return list(phrase_table("fault_reports.columns").values())


def report_rows(records) -> list[list[str]]:
    """One row of the table of an import a report: its line, when it was
    received, who sent it, the borehole as given, what it says, what became
    of it and why."""
    says = phrase_table("fault_reports.choices")
    outcome = phrase_table("fault_reports.outcome")
    rows = []
    for r in records if isinstance(records, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("status"), str) \
                or r["status"] not in outcome:
            continue
        choice = r.get("choice")
        rows.append(["" if r.get("line") is None else str(r["line"]),
                     r.get("received") or r.get("when") or "", r.get("sender") or "",
                     r.get("asset_id") or r.get("typed") or "",
                     says.get(choice, "") if isinstance(choice, str) else "",
                     outcome[r["status"]], r.get("reason") or ""])
    return rows


def sms_format() -> str:
    """What a report by SMS and a file of them look like, as both apps' imports
    say it."""
    return phrase("fault_reports.sms_format", words=_words())


def import_summary(records) -> str:
    """How many reports an import read and what became of them."""
    records = [r for r in (records if isinstance(records, list) else [])
               if isinstance(r, dict)]
    count = {s: sum(1 for r in records if r.get("status") == s)
             for s in ("accepted", "held", "refused")}
    return phrase("fault_reports.import_summary", n=len(records), **count)

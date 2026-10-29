"""Documents that can be verified (PLAN.md step 8.1).

In donor-funded drilling a completion report is money, and a .docx is easy
to change. So every document the toolkit writes carries a manifest: a
custom XML part, ``customXml/groundwater-manifest.xml``, in a namespace of
its own, linked from the document, that records

* what the document is: its kind, its title and the day it was issued (an
  input, never the clock);
* the engine that wrote it and its version;
* the calibration set in force, by name and by the SHA-256 of its
  ``calibration.yaml``;
* its readiness: certifiable, issued on override, provisional, or no
  certification gate run, with what was outstanding or overridden;
* the SHA-256 of every evidence file it was issued from (the workbooks, the
  photographs);
* the SHA-256 of every other part of the package (``word/document.xml``,
  each image, the styles ...), so a check can name the part that changed.

The SHA-256 of the manifest itself is the document's hash. It covers every
part through theirs, and it is what an issue record holds: the apps write
one into the project file (``issued``) and, where the borehole has an
identifier, into its asset record (``documents``).

The cover carries a short code and a QR symbol of it, and every page's
footer the code. The code cannot be a short form of the document's hash,
because the parts that print it are in the document: the hash would have to
cover itself. So the code is a short form of the *code digest*, the SHA-256
of the manifest written without the code and without the parts that carry
it (the footers and the QR symbol, listed apart as ``carriers``): of what
the document says, who wrote it, with which calibration, how ready, from
which evidence. A copy whose text is changed and whose manifest is brought
into line no longer gives its own code. That is a choice, and this is why
it was made.

:func:`verify_document` answers four things about a .docx: whether the
toolkit issued it (its hash matches an issue record given to it), whether
it has changed since (every part against the manifest), whether it was
certifiable or provisional (as the manifest records), and which evidence it
was issued from. Without a signature (PLAN.md step 8.2) a forger who
rewrites a part, the manifest, the code and the parts that print it passes
the second check; the issue record is what catches that, which is why the
answer to the first question says so when no record is given.

The package is read here byte by byte rather than through ``zipfile``, and
by the same rules as ``readPackage`` in gwt-core.js, so the two engines
refuse exactly the same files.
"""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass

from .readiness import REPORTS
from .registry import _ALPHABET, _FOLD, _TRIMMED, check_character, iso_date, trim_field
from .text import phrase, phrase_table

__all__ = [
    "BOREHOLE_KINDS",
    "ENGINE",
    "Issue",
    "MANIFEST_PART",
    "READINESS_STATES",
    "VERDICTS",
    "borehole_records",
    "calibration_facts",
    "clean_issue_records",
    "code_digest",
    "document_code",
    "document_record",
    "evidence_entry",
    "issue_records_of",
    "lookup_code",
    "manifest_facts",
    "manifest_xml",
    "parse_document_code",
    "read_manifest",
    "read_package",
    "readiness_facts",
    "seal_package",
    "verify_document",
]

#: Where the manifest sits in the package. Not ``customXml/item1.xml``:
#: python-docx's own template already has one.
MANIFEST_PART = "customXml/groundwater-manifest.xml"
MANIFEST_NS = "urn:groundwater-toolkit:manifest"
MANIFEST_FORMAT = 1
_REL_ID = "rIdGroundwaterManifest"
_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml"
_DOCUMENT_RELS = "word/_rels/document.xml.rels"
_CONTENT_TYPES = "[Content_Types].xml"
_XML_DEFAULT = '<Default Extension="xml" ContentType="application/xml"/>'

#: The engine a manifest names, as the inversion cache names it
#: (``ves/cache.py``), with the package's version; the browser's is
#: ``gwt-core``. The version only, not numpy's or a digest of the code: a
#: document re-issued on another machine from the same inputs is the same
#: document.
ENGINE = "groundwater-python"

#: What the manifest records of a document's readiness: the three states of
#: :class:`groundwater.readiness.Readiness`, and ``not_assessed`` for a
#: document no gate was run for (the desk study, the field kit, the
#: calibration report, a round sheet, or a report built without one).
READINESS_STATES = ("ready", "ready_with_overrides", "not_ready", "not_assessed")

#: The kinds of document that are about the borehole itself, whose issue
#: records the apps keep in its asset record as well as in the project
#: file: the ones with a certification gate.
BOREHOLE_KINDS = tuple(REPORTS)

#: Every verdict :func:`verify_document` gives, best first.
VERDICTS = ("verified", "unconfirmed", "changed", "not_issued", "altered_manifest",
            "damaged_manifest", "no_manifest", "unreadable")

#: A part larger than this, or a package larger in all, is not read: a few
#: hundred bytes can claim gigabytes, and a .docx the toolkit wrote is
#: nowhere near either.
MAX_PART_BYTES = 128 * 1024 * 1024
MAX_PACKAGE_BYTES = 512 * 1024 * 1024

_HEX64 = re.compile(r"[0-9a-f]{64}")
_CODE_RE = re.compile(r"[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]")
#: What a code typed or scanned may carry between its characters: the blanks
#: both engines trim (``CODE_BLANKS_RE`` in gwt-core.js), underscores and
#: hyphens.
_CODE_BLANKS = re.compile("[" + "".join(re.escape(c) for c in _TRIMMED) + "_-]+")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Issue:
    """What the caller knows of an issue that a document's writer does not:
    the day it is issued on (an ISO day, or blank where none is given) and
    the evidence files it is issued from (:func:`evidence_entry`)."""

    issued_on: str = ""
    evidence: tuple = ()


# ---------------------------------------------------------------------------
# The code
# ---------------------------------------------------------------------------

def document_code(digest: str) -> str:
    """The short code of a code digest: its first 40 bits as eight Crockford
    base-32 characters in two groups, and an ISO 7064 MOD 37,36 check
    character, as the asset identifier has (``0A1B-2C3D-5``).

    Forty bits is a code a person can read off a page and type; it names an
    issue among the few a programme makes, and the hash behind it is what
    is checked.
    """
    body = ""
    for start in (0, 5):
        value = int(digest[start:start + 5], 16)
        body += "".join(_ALPHABET[(value >> shift) & 31] for shift in (15, 10, 5, 0))
    return f"{body[:4]}-{body[4:]}-{check_character(body)}"


def parse_document_code(text) -> str | None:
    """A typed or scanned code as the toolkit writes it, or None.

    Case, blanks (the ones :func:`~groundwater.registry.trim_field` trims),
    underscores, missing hyphens, the word DOCUMENT the QR symbol leads
    with, and the four Crockford confusions in the body (I and L for 1, O for
    0, U for V) are forgiven; a wrong check character, and anything but
    printable ASCII, is not.
    """
    raw = _CODE_BLANKS.sub("", str("" if text is None else text))
    if any(not " " <= c <= "~" for c in raw):
        return None
    raw = raw.upper()
    if raw.startswith("DOCUMENT"):
        raw = raw[len("DOCUMENT"):]
    if len(raw) != 9:
        return None
    body = "".join(_FOLD.get(c, c) for c in raw[:8])
    if any(c not in _ALPHABET for c in body) or check_character(body) != raw[8]:
        return None
    return f"{body[:4]}-{body[4:]}-{raw[8]}"


# ---------------------------------------------------------------------------
# The facts
# ---------------------------------------------------------------------------

#: What XML 1.0 cannot carry at all, dropped from a value rather than
#: written as a document no reader can open.
_UNWRITABLE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def _text(value) -> str:
    """A field of the manifest: text, with what XML cannot carry dropped and
    trimmed as both engines trim; anything but text is blank."""
    return trim_field(_UNWRITABLE.sub("", value)) if isinstance(value, str) else ""


def readiness_facts(readiness) -> dict:
    """What the manifest records of a readiness: its state, and each
    requirement that held the document back - outstanding, or overridden by
    a named person for a reason - in the order the gate lists them.

    ``readiness`` is a :class:`~groundwater.readiness.Readiness`, its
    ``as_dict()``, the browser's equivalent, or None for a document no gate
    was run for.
    """
    if readiness is None:
        return {"state": "not_assessed", "items": []}
    requirements = (readiness.get("requirements") if isinstance(readiness, dict)
                    else getattr(readiness, "requirements", None)) or []
    items = []
    for req in requirements:
        def get(key, req=req):
            return req.get(key) if isinstance(req, dict) else getattr(req, key, "")
        state = get("state")
        if state == "unmet":
            items.append({"state": "unmet", "title": _text(get("title")), "by": "", "reason": ""})
        elif state == "overridden":
            items.append({"state": "overridden", "title": _text(get("title")),
                          "by": _text(get("override_by")), "reason": _text(get("override_reason"))})
    return {"state": _readiness_state(items), "items": items}


def _readiness_state(items: list[dict]) -> str:
    if any(item["state"] == "unmet" for item in items):
        return "not_ready"
    return "ready_with_overrides" if items else "ready"


def evidence_entry(what: str, name: str, data: bytes) -> dict:
    """One evidence file as the manifest lists it: what it is, its name,
    and the SHA-256 of its bytes."""
    return {"what": _text(what), "name": _text(name), "sha256": _sha256(bytes(data))}


def calibration_facts(calibration) -> dict:
    """The calibration set in force as the manifest names it: its name as a
    report gives it, and the SHA-256 of its ``calibration.yaml``. None is
    the provisional default, which is what is in force when no set is."""
    from .calibration_sets import clean_set, default_set, set_name, set_yaml

    s = clean_set(calibration if calibration is not None else default_set())
    return {"name": set_name(s), "sha256": _sha256(set_yaml(s).encode("utf-8"))}


def _sort_key(entry: dict) -> tuple:
    return (entry["what"], entry["name"], entry["sha256"])


def manifest_facts(kind: str, title: str, issued_on: str = "", engine=("", ""),
                   calibration=None, readiness=None, evidence=()) -> dict:
    """The facts a manifest records about a document, cleaned and in order.

    ``engine`` is ``(name, version)``; ``calibration`` is
    :func:`calibration_facts`'s mapping, or None where the issue does not
    say, which the manifest records as not stated; ``readiness`` as
    :func:`readiness_facts` takes it, or its result; ``evidence`` a list of
    :func:`evidence_entry` mappings, listed once each and in order.

    An issue date that is not a day, an evidence file with no SHA-256 and a
    calibration with a name and no hash raise ValueError: a manifest that
    records any of them is worse than none.
    """
    issued = _text(issued_on)
    if issued and iso_date(issued) is None:
        raise ValueError(phrase("verification.bad_date", date=issued))
    files = []
    for entry in evidence or ():
        digest = _text(entry.get("sha256"))
        if not _HEX64.fullmatch(digest):
            raise ValueError(phrase("verification.bad_hash", name=_text(entry.get("name"))))
        item = {"what": _text(entry.get("what")), "name": _text(entry.get("name")), "sha256": digest}
        if item not in files:
            files.append(item)
    files.sort(key=_sort_key)
    cal = {"name": "", "sha256": ""}
    if calibration is not None:
        cal = {"name": _text(calibration.get("name")), "sha256": _text(calibration.get("sha256"))}
        if not cal["name"] or not _HEX64.fullmatch(cal["sha256"]):
            raise ValueError(phrase("verification.bad_calibration"))
    if isinstance(readiness, dict) and set(readiness) == {"state", "items"}:
        # already the manifest's shape, as read back from one: cleaned as
        # it would have been written, so a manifest holding a field it
        # could not have been written with is not read
        ready = {"state": _text(readiness["state"]),
                 "items": [{key: _text(item.get(key)) for key in ("state", "title", "by", "reason")}
                           for item in readiness["items"]]}
    else:
        ready = readiness_facts(readiness)
    return {
        "document": {"kind": _text(kind), "title": _text(title), "issued_on": issued},
        "engine": {"name": _text(engine[0]), "version": _text(engine[1])},
        "calibration": cal,
        "readiness": ready,
        "evidence": files,
    }


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------

_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
            "\t": "&#9;", "\n": "&#10;", "\r": "&#13;"}
_UNESCAPES = {v: k for k, v in _ESCAPES.items()}
_TO_ESCAPE = re.compile('[&<>"\t\n\r]')


def _attr(value: str) -> str:
    return _TO_ESCAPE.sub(lambda m: _ESCAPES[m.group(0)], value)


def _element(name: str, attrs: list[tuple[str, str]], close: bool = True) -> str:
    body = "".join(f' {key}="{_attr(value)}"' for key, value in attrs)
    return f"<{name}{body}{'/' if close else ''}>"


_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_OPEN = f'<manifest xmlns="{MANIFEST_NS}" format="{MANIFEST_FORMAT}">'


def manifest_xml(facts: dict, code: str = "", parts=(), carriers=()) -> str:
    """The manifest as the toolkit writes it: one element to a line, every
    attribute always present and in one order, so the two engines write the
    same bytes and the check can insist on them. ``parts`` and ``carriers``
    are ``(name, sha256)`` pairs, in order."""
    d, e, c, r = facts["document"], facts["engine"], facts["calibration"], facts["readiness"]
    lines = [
        _HEAD, _OPEN,
        _element("document", [("kind", d["kind"]), ("title", d["title"]),
                              ("issued", d["issued_on"]), ("code", code)]),
        _element("engine", [("name", e["name"]), ("version", e["version"])]),
        _element("calibration", [("name", c["name"]), ("sha256", c["sha256"])]),
        _element("readiness", [("state", r["state"])], close=False),
    ]
    lines += [_element("item", [("state", i["state"]), ("title", i["title"]),
                                ("by", i["by"]), ("reason", i["reason"])]) for i in r["items"]]
    lines += ["</readiness>", "<evidence>"]
    lines += [_element("file", [("what", f["what"]), ("name", f["name"]), ("sha256", f["sha256"])])
              for f in facts["evidence"]]
    lines += ["</evidence>", "<parts>"]
    lines += [_element("part", [("name", name), ("sha256", digest)]) for name, digest in parts]
    lines += ["</parts>", "<carriers>"]
    lines += [_element("part", [("name", name), ("sha256", digest)]) for name, digest in carriers]
    lines += ["</carriers>", "</manifest>"]
    return "\n".join(lines) + "\n"


def code_digest(facts: dict, parts) -> str:
    """The SHA-256 of the manifest written with no code and no carriers:
    what the cover's code is a short form of."""
    return _sha256(manifest_xml(facts, "", parts).encode("utf-8"))


_V = '([^"<>]*)'
_LINES = {
    "document": re.compile(f'<document kind="{_V}" title="{_V}" issued="{_V}" code="{_V}"/>'),
    "engine": re.compile(f'<engine name="{_V}" version="{_V}"/>'),
    "calibration": re.compile(f'<calibration name="{_V}" sha256="{_V}"/>'),
    "readiness": re.compile(f'<readiness state="{_V}">'),
    "item": re.compile(f'<item state="{_V}" title="{_V}" by="{_V}" reason="{_V}"/>'),
    "file": re.compile(f'<file what="{_V}" name="{_V}" sha256="{_V}"/>'),
    "part": re.compile(f'<part name="{_V}" sha256="{_V}"/>'),
}
_ENTITY = re.compile(r"&[^;&]*;|&")


def _unescape(value: str) -> str:
    def one(match):
        if match.group(0) not in _UNESCAPES:
            raise ValueError("entity")
        return _UNESCAPES[match.group(0)]

    return _ENTITY.sub(one, value)


def _parsed(kind: str, line: str) -> list[str]:
    match = _LINES[kind].fullmatch(line)
    if match is None:
        raise ValueError(kind)
    return [_unescape(value) for value in match.groups()]


def _listed(lines: list[str], at: int, kind: str, end: str) -> tuple[list[list[str]], int]:
    out = []
    while at < len(lines) and lines[at] != end:
        out.append(_parsed(kind, lines[at]))
        at += 1
    if at >= len(lines):
        raise ValueError(end)
    return out, at + 1


def _names_ok(pairs: list[tuple[str, str]]) -> bool:
    names = [name for name, _ in pairs]
    return (len(set(names)) == len(names) and names == sorted(names)
            and all(name and name != MANIFEST_PART and _HEX64.fullmatch(digest) for name, digest in pairs))


def read_manifest(text: str) -> dict | None:
    """``{"facts", "code", "parts", "carriers"}`` from a manifest's text, or
    None.

    None unless the text is exactly what :func:`manifest_xml` writes for
    what it holds, and what it holds is sound: a manifest edited by hand,
    or written by anything else, is not read at all.
    """
    if not isinstance(text, str) or not text.endswith("\n"):
        return None
    lines = text[:-1].split("\n")
    try:
        if lines[:2] != [_HEAD, _OPEN] or lines[-1] != "</manifest>":
            raise ValueError("frame")
        kind, title, issued, code = _parsed("document", lines[2])
        engine = _parsed("engine", lines[3])
        cal_name, cal_sha = _parsed("calibration", lines[4])
        (state,) = _parsed("readiness", lines[5])
        items, at = _listed(lines, 6, "item", "</readiness>")
        if lines[at] != "<evidence>":
            raise ValueError("evidence")
        files, at = _listed(lines, at + 1, "file", "</evidence>")
        if lines[at] != "<parts>":
            raise ValueError("parts")
        parts, at = _listed(lines, at + 1, "part", "</parts>")
        if lines[at] != "<carriers>":
            raise ValueError("carriers")
        carriers, at = _listed(lines, at + 1, "part", "</carriers>")
        if at != len(lines) - 1:
            raise ValueError("trailing")
        readiness = {"state": state, "items": [{"state": i[0], "title": i[1], "by": i[2], "reason": i[3]}
                                               for i in items]}
        if (state not in READINESS_STATES
                or any(i["state"] not in ("unmet", "overridden") for i in readiness["items"])
                or any(i["state"] == "unmet" and (i["by"] or i["reason"]) for i in readiness["items"])
                or (state == "not_assessed" and items)
                or (state != "not_assessed" and state != _readiness_state(readiness["items"]))):
            raise ValueError("readiness")
        calibration = {"name": cal_name, "sha256": cal_sha} if cal_name or cal_sha else None
        facts = manifest_facts(kind, title, issued, tuple(engine), calibration, readiness,
                               [{"what": f[0], "name": f[1], "sha256": f[2]} for f in files])
        part_pairs = [(p[0], p[1]) for p in parts]
        carrier_pairs = [(p[0], p[1]) for p in carriers]
        if (not _names_ok(part_pairs) or not _names_ok(carrier_pairs)
                or {n for n, _ in part_pairs} & {n for n, _ in carrier_pairs}):
            raise ValueError("parts")
        if not _CODE_RE.fullmatch(code) or parse_document_code(code) != code:
            raise ValueError("code")
    except (IndexError, ValueError):
        return None
    if manifest_xml(facts, code, part_pairs, carrier_pairs) != text:
        return None
    return {"facts": facts, "code": code, "parts": part_pairs, "carriers": carrier_pairs}


# ---------------------------------------------------------------------------
# Sealing a package
# ---------------------------------------------------------------------------

def _record(facts: dict, code: str, digest: str) -> dict:
    d = facts["document"]
    return {"code": code, "sha256": digest, "kind": d["kind"], "title": d["title"],
            "issued_on": d["issued_on"], "readiness": facts["readiness"]["state"]}


def seal_package(entries: dict, facts: dict,
                 make_carriers: Callable[[str], dict] | None = None) -> dict:
    """A document's parts with its manifest added, and what it records.

    ``entries`` maps each part's name to its bytes, as the writer is about
    to zip them, without the parts that carry the code. The manifest is
    linked from ``word/document.xml``'s relationships, and the package is
    given a content type for ``.xml`` where it has none; every part is then
    hashed, the code worked out from them, and ``make_carriers(code)`` asked
    for the parts that print it, which are hashed into the manifest apart.
    Returns ``{"entries", "manifest", "code", "sha256", "record"}``; the
    record is what the project file and the asset record keep.
    """
    if MANIFEST_PART in entries:
        raise ValueError(f"the package already has a part named {MANIFEST_PART}")
    out = {name: bytes(data) for name, data in entries.items()}
    rels = out[_DOCUMENT_RELS].decode("utf-8")
    if rels.count("</Relationships>") != 1:
        raise ValueError("the document's relationships are not one list")
    link = (f'<Relationship Id="{_REL_ID}" Type="{_REL_TYPE}" '
            f'Target="../{MANIFEST_PART}"/>')
    out[_DOCUMENT_RELS] = rels.replace("</Relationships>", link + "</Relationships>").encode("utf-8")
    types = out[_CONTENT_TYPES].decode("utf-8")
    if 'Extension="xml"' not in types:
        start = types.index("<Types")
        end = types.index(">", start) + 1
        out[_CONTENT_TYPES] = (types[:end] + _XML_DEFAULT + types[end:]).encode("utf-8")
    parts = [(name, _sha256(out[name])) for name in sorted(out)]
    code = document_code(code_digest(facts, parts))
    made = {name: bytes(data) for name, data in (make_carriers(code) if make_carriers else {}).items()}
    if any(name in out or name == MANIFEST_PART for name in made):
        raise ValueError("a part that carries the code is named twice")
    out.update(made)
    carriers = [(name, _sha256(made[name])) for name in sorted(made)]
    manifest = manifest_xml(facts, code, parts, carriers)
    out[MANIFEST_PART] = manifest.encode("utf-8")
    digest = _sha256(out[MANIFEST_PART])
    return {"entries": out, "manifest": manifest, "code": code, "sha256": digest,
            "record": _record(facts, code, digest)}


# ---------------------------------------------------------------------------
# Issue records
# ---------------------------------------------------------------------------

_RECORD_KEYS = ("code", "sha256", "kind", "title", "issued_on", "readiness")


def clean_issue_records(raw) -> list[dict]:
    """Issue records as both engines keep them: each well formed, one per
    document hash, in the order they were issued (by date, then code, then
    hash, by code point). A record that is not one is dropped, as a
    hand-edited ledger entry is."""
    seen: dict[str, dict] = {}
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        if not all(isinstance(entry.get(key), str) for key in _RECORD_KEYS):
            continue
        record = {key: _text(entry[key]) for key in _RECORD_KEYS}
        if (parse_document_code(record["code"]) != record["code"]
                or not _HEX64.fullmatch(record["sha256"])
                or (record["issued_on"] and iso_date(record["issued_on"]) is None)
                or record["readiness"] not in READINESS_STATES):
            continue
        seen.setdefault(record["sha256"], record)
    return sorted(seen.values(), key=lambda r: (r["issued_on"], r["code"], r["sha256"]))


def borehole_records(raw) -> list[dict]:
    """The issue records among ``raw`` of documents about the borehole
    itself (:data:`BOREHOLE_KINDS`), which its asset record keeps."""
    return [r for r in clean_issue_records(raw) if r["kind"] in BOREHOLE_KINDS]


def issue_records_of(payload) -> list[dict]:
    """Every issue record a saved project file carries, as either app wrote
    it: the project's own (``issued``) and its asset record's
    (``documents``, at the top of a Python app's file and in the state of a
    browser app's)."""
    if not isinstance(payload, dict):
        return []
    raw: list = []
    held = payload.get("state")
    state: dict = held if isinstance(held, dict) else {}
    for asset in (payload.get("asset"), state.get("asset")):
        if isinstance(asset, dict) and isinstance(asset.get("documents"), list):
            raw += asset["documents"]
    for issued in (payload.get("issued"), state.get("issued")):
        if isinstance(issued, list):
            raw += issued
    return clean_issue_records(raw)


def lookup_code(text, records) -> dict:
    """What the issue records say of a code typed in or read off a cover:
    ``{"code", "records", "lines"}``, the records issued under it and the
    sentences the page shows, one to a record."""
    held = clean_issue_records(records)
    code = parse_document_code(text)
    if code is None:
        return {"code": None, "records": [],
                "lines": [phrase("verification.code_unreadable", code=_text(str(text or "")))]}
    found = [r for r in held if r["code"] == code]
    if not found:
        return {"code": code, "records": [],
                "lines": [phrase("verification.code_not_found", n=len(held), code=code)]}
    words = phrase_table("verification.readiness_words")
    lines = [phrase("verification.code_found", code=code, title=r["title"],
                    when=_issued_words(r["issued_on"]), readiness=words[r["readiness"]],
                    sha256=r["sha256"]) for r in found]
    return {"code": code, "records": found, "lines": lines}


def _issued_words(day: str) -> str:
    return (phrase("verification.on_day", date=day) if day
            else phrase("verification.on_no_day"))


# ---------------------------------------------------------------------------
# Reading a package
# ---------------------------------------------------------------------------

def read_package(data: bytes) -> dict | None:
    """The parts of a ZIP package by name, or None when it is not one this
    toolkit reads.

    Read from the central directory, as ``readPackage`` in gwt-core.js reads
    it, rule for rule: one end-of-directory record, at the end of the file
    with nothing after its comment, on one disk and not ZIP64, its
    directory running up to it with nothing over; no entry encrypted or
    compressed by anything but DEFLATE, named twice, or named in other than
    ASCII without the UTF-8 flag; each entry's local header naming it and
    its method as the directory does, its data before the directory, and
    its size and CRC-32 as the directory says, with nothing after the end
    of its DEFLATE stream.
    """
    data = bytes(data)
    n = len(data)
    eocd = -1
    for at in range(n - 22, max(-1, n - 22 - 65535 - 1), -1):
        if data[at:at + 4] == b"PK\x05\x06":
            eocd = at
            break
    if eocd < 0:
        return None
    disk, cd_disk, here, count, size, start, comment = struct.unpack_from("<HHHHIIH", data, eocd + 4)
    if (disk or cd_disk or here != count or eocd + 22 + comment != n
            or start + size != eocd or count == 0xFFFF or start == 0xFFFFFFFF):
        return None
    parts: dict[str, bytes] = {}
    total = 0
    at = start
    for _ in range(count):
        if at + 46 > eocd or data[at:at + 4] != b"PK\x01\x02":
            return None
        flags, method = struct.unpack_from("<HH", data, at + 8)
        crc, csize, usize, name_len, extra_len, comment_len = struct.unpack_from("<IIIHHH", data, at + 16)
        local = struct.unpack_from("<I", data, at + 42)[0]
        raw_name = data[at + 46:at + 46 + name_len]
        at += 46 + name_len + extra_len + comment_len
        if at > eocd or flags & 0x2041 or method not in (0, 8):
            return None
        if flags & 0x800:
            try:
                name = raw_name.decode("utf-8")
            except UnicodeDecodeError:
                return None
        elif all(b < 0x80 for b in raw_name):
            name = raw_name.decode("ascii")
        else:
            return None
        if local + 30 > start or data[local:local + 4] != b"PK\x03\x04":
            return None
        lmethod = struct.unpack_from("<H", data, local + 8)[0]
        lname_len, lextra_len = struct.unpack_from("<HH", data, local + 26)
        if lmethod != method or data[local + 30:local + 30 + lname_len] != raw_name:
            return None
        begin = local + 30 + lname_len + lextra_len
        if begin + csize > start:
            return None
        if name.endswith("/"):
            continue
        if name in parts or usize > MAX_PART_BYTES:
            return None
        total += usize
        if total > MAX_PACKAGE_BYTES:
            return None
        stored = data[begin:begin + csize]
        if method == 0:
            body = stored
        else:
            inflater = zlib.decompressobj(-15)
            try:
                body = inflater.decompress(stored, usize + 1)
            except zlib.error:
                return None
            if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
                return None
        if len(body) != usize or (zlib.crc32(body) & 0xFFFFFFFF) != crc:
            return None
        parts[name] = body
    if at != eocd:
        return None
    return parts


def _manifest_of(parts: dict) -> dict | None:
    raw = parts.get(MANIFEST_PART)
    if raw is None:
        return None
    try:
        return read_manifest(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def document_record(data: bytes) -> dict | None:
    """The issue record of a document the toolkit has just written, from
    its own bytes, or None when it carries no manifest that can be relied
    on."""
    parts = read_package(data)
    if parts is None:
        return None
    manifest = _manifest_of(parts)
    if manifest is None or _code_of(manifest) != manifest["code"]:
        return None
    return _record(manifest["facts"], manifest["code"], _sha256(parts[MANIFEST_PART]))


def _code_of(manifest: dict) -> str:
    return document_code(code_digest(manifest["facts"], manifest["parts"]))


# ---------------------------------------------------------------------------
# Verifying a document
# ---------------------------------------------------------------------------

def _part_label(name: str) -> str:
    names = phrase_table("verification.part_names")
    if name in names:
        return phrase("verification.part_label", name=name, what=names[name])
    if name.startswith("word/media/"):
        return phrase("verification.part_label", name=name, what=names["word/media"])
    return name


def _readiness_line(readiness: dict) -> str:
    state = readiness["state"]
    if state == "ready":
        return phrase("verification.readiness_ready")
    if state == "not_assessed":
        return phrase("verification.readiness_not_assessed")
    overridden = "; ".join(phrase("verification.overridden_by", title=i["title"], by=i["by"])
                           if i["by"] else i["title"]
                           for i in readiness["items"] if i["state"] == "overridden")
    if state == "ready_with_overrides":
        return phrase("verification.readiness_overrides", titles=overridden)
    line = phrase("verification.readiness_not_ready",
                  titles="; ".join(i["title"] for i in readiness["items"] if i["state"] == "unmet"))
    if overridden:
        line += " " + phrase("verification.readiness_also_overridden", titles=overridden)
    return line


def _evidence_line(evidence: list[dict]) -> str:
    if not evidence:
        return phrase("verification.evidence_none")
    files = "; ".join(phrase("verification.evidence_file", name=f["name"], what=f["what"],
                             short=f["sha256"][:16]) if f["what"]
                      else phrase("verification.evidence_file_bare", name=f["name"], short=f["sha256"][:16])
                      for f in evidence)
    return phrase("verification.evidence_some", n=len(evidence), files=files)


def _engine_line(facts: dict) -> str:
    calibration = facts["calibration"]["name"] or phrase("verification.calibration_unstated")
    return phrase("verification.engine_line", engine=facts["engine"]["name"],
                  version=facts["engine"]["version"], calibration=calibration,
                  when=_issued_words(facts["document"]["issued_on"]))


def verify_document(data: bytes, records=None) -> dict:
    """What can be said of a .docx: whether the toolkit issued it, whether it
    has changed since, whether it was certifiable or provisional, and which
    evidence it was issued from.

    ``records`` are the issue records to check it against - a project
    file's and an asset record's (:func:`clean_issue_records` takes them as
    they come) - or None when none were given, which the first answer says.
    Returns the verdict (one of :data:`VERDICTS`), how the first answer
    came out (``issued``), the four answers as the page shows them
    (``answers``, keyed ``issued``, ``changed``, ``readiness`` and
    ``evidence``, blank where the manifest cannot be relied on), the lines
    the page and the command line print, and what they rest on: the code,
    the document's hash, the manifest's facts, the parts that changed, went
    missing or were added, and the record matched.
    """
    report: dict = {
        "verdict": "unreadable", "issued": "unreadable", "code": "", "sha256": "", "facts": None,
        "changed": [], "missing": [], "added": [], "record": None, "answers": {}, "lines": [],
    }
    parts = read_package(data)
    if parts is None:
        return _answered(report, phrase("verification.issued_unreadable"), "", "", "")
    if MANIFEST_PART not in parts:
        report["verdict"] = report["issued"] = "no_manifest"
        return _answered(report, phrase("verification.issued_no_manifest"),
                         phrase("verification.changed_unknown"), "", "")
    manifest = _manifest_of(parts)
    if manifest is None:
        report["verdict"] = report["issued"] = "damaged_manifest"
        return _answered(report, phrase("verification.issued_damaged"),
                         phrase("verification.changed_unknown"), "", "")
    digest = _sha256(parts[MANIFEST_PART])
    report.update(code=manifest["code"], sha256=digest)
    if _code_of(manifest) != manifest["code"]:
        report["verdict"] = report["issued"] = "altered_manifest"
        return _answered(report, phrase("verification.issued_altered", code=manifest["code"]),
                         phrase("verification.changed_unknown"), "", "")

    facts, code = manifest["facts"], manifest["code"]
    report["facts"] = facts
    listed = dict(manifest["parts"] + manifest["carriers"])
    report["changed"] = sorted(name for name, held in listed.items()
                               if name in parts and _sha256(parts[name]) != held)
    report["missing"] = sorted(name for name in listed if name not in parts)
    report["added"] = sorted(name for name in parts if name not in listed and name != MANIFEST_PART)
    altered = bool(report["changed"] or report["missing"] or report["added"])

    if records is None:
        report["issued"] = "not_checked"
        issued = phrase("verification.issued_not_checked")
    else:
        held = clean_issue_records(records)
        match = next((r for r in held if r["sha256"] == digest), None)
        same_code = [r for r in held if r["code"] == code]
        if match is not None:
            report["issued"], report["record"] = "matched", match
            issued = phrase("verification.issued_matched", code=code)
        elif same_code:
            report["issued"], report["record"] = "record_differs", same_code[0]
            issued = phrase("verification.issued_record_differs", code=code)
        else:
            report["issued"] = "no_record"
            issued = phrase("verification.issued_no_record", n=len(held), code=code)

    if altered:
        pieces = []
        if report["changed"]:
            pieces.append(phrase("verification.changed_parts", n=len(report["changed"]),
                                 parts="; ".join(_part_label(n) for n in report["changed"])))
        if report["missing"]:
            pieces.append(phrase("verification.missing_parts",
                                 parts="; ".join(_part_label(n) for n in report["missing"])))
        if report["added"]:
            pieces.append(phrase("verification.added_parts",
                                 parts="; ".join(_part_label(n) for n in report["added"])))
        changed = " ".join(pieces)
    else:
        changed = phrase("verification.unchanged")
    if altered or report["issued"] == "record_differs":
        report["verdict"] = "changed"
    else:
        report["verdict"] = {"matched": "verified", "not_checked": "unconfirmed"}.get(
            report["issued"], "not_issued")
    return _answered(report, issued, changed, _readiness_line(facts["readiness"]),
                     _evidence_line(facts["evidence"]), _engine_line(facts))


def _answered(report: dict, issued: str, changed: str, readiness: str, evidence: str,
              engine: str = "") -> dict:
    report["answers"] = {"issued": issued, "changed": changed, "readiness": readiness,
                         "evidence": evidence}
    headline = phrase_table("verification.verdicts")[report["verdict"]]
    report["lines"] = [line for line in (headline, issued, changed, readiness, evidence, engine) if line]
    return report

"""One evidence bundle for each borehole (PLAN.md step 8.3).

An auditor of a donor-funded borehole asks for the same things every time:
the field sheets as they came off site, what was worked out from them, the
documents issued and something that shows none of it was changed
afterwards. :func:`build_evidence_bundle` puts them in one ZIP archive:

* ``raw/``: the source files as they were uploaded (the field sheets);
* ``tables/``: processed tables (CSV);
* ``figures/``: figures, which the apps take out of the documents that
  embed them, byte for byte;
* ``reports/``: the documents issued, each carrying its own manifest
  (:mod:`groundwater.verification`, step 8.1);
* ``signatures/``: signatures over sign-offs (step 8.2), where there are
  any;
* ``manifest.json``: the size and SHA-256 of every other file, the engine
  and its version, the calibration set in force, each document's code, hash
  and readiness, the readiness of the documents taken together, and the
  issue records the project held;
* ``README.txt``: what the bundle is and how to check it.

A folder that holds nothing carries a note saying so (``README.txt`` in it),
so that an empty ``signatures/`` reads as "nothing is signed yet" rather
than as something lost on the way.

The archive is written byte by byte, entries sorted by name, every entry
stored (the documents and figures in it are compressed already) with one
fixed timestamp, so the same files give the same bytes in both engines and
on every machine, and no zlib build moves a byte. The SHA-256 of
``manifest.json`` is the bundle's hash.

:func:`verify_evidence_bundle` checks a bundle: every file against
``manifest.json``, every document against its own manifest and against the
issue records given, and every other file against the documents, which
list the SHA-256 of each field sheet they were issued from and of each
figure they embed. A bundle rewritten throughout agrees with itself, so
only what is outside it confirms it: an issue record confirms a document,
and a confirmed document confirms the files it lists. Without issue records
a bundle is at best "unconfirmed", as a document checked with none is.

Both engines write the same bundle for the same files and say the same of
it: ``buildEvidenceBundle`` and ``verifyEvidenceBundle`` in gwt-core.js are
the twins, held to these by the parity suite.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib

from .registry import _TRIMMED, iso_date
from .text import phrase, phrase_table
from .verification import (
    ENGINE,
    MAX_PACKAGE_BYTES,
    MAX_PART_BYTES,
    READINESS_STATES,
    _manifest_of,
    _readiness_state,
    _text,
    clean_issue_records,
    parse_document_code,
    read_package,
    verify_document,
)

__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_MANIFEST",
    "BUNDLE_README",
    "BUNDLE_VERDICTS",
    "BUNDLE_VERSION",
    "FOLDERS",
    "PROGRAMME_KINDS",
    "build_evidence_bundle",
    "bundle_manifest",
    "bundle_name",
    "bundle_note",
    "bundle_readiness",
    "bundle_readme",
    "document_figures",
    "read_bundle_manifest",
    "verify_evidence_bundle",
]

#: What ``manifest.json`` says it is, and the version of its layout.
BUNDLE_FORMAT = "groundwater-toolkit evidence bundle"
BUNDLE_VERSION = 1
BUNDLE_MANIFEST = "manifest.json"
BUNDLE_README = "README.txt"

#: The folders a bundle has, in the order its README lists them. A folder
#: that holds nothing carries a note of this name.
FOLDERS = ("raw", "tables", "figures", "reports", "signatures")
NOTE = "README.txt"

#: The kinds of document about many boreholes rather than one: the
#: calibration report pools projects and a round sheet covers the register.
#: The apps leave them out of a borehole's bundle unless they are added by
#: hand.
PROGRAMME_KINDS = ("calibration", "rounds")

#: Every verdict :func:`verify_evidence_bundle` gives, best first.
BUNDLE_VERDICTS = ("verified", "unconfirmed", "changed", "not_issued", "damaged_manifest",
                   "no_manifest", "unreadable")

#: An archive the reader reads has fewer entries than this
#: (``read_package`` refuses a count of 0xFFFF), manifest.json included.
MAX_ENTRIES = 0xFFFF - 1

#: A document's own check that leaves it sound: unchanged since it was
#: written, whatever the issue records say.
_SOUND = ("verified", "unconfirmed", "not_issued")

_HEX64 = re.compile(r"[0-9a-f]{64}")
#: What a file name in a bundle may not hold: what Windows and the ZIP
#: format refuse, and the control characters XML does carry.
_NAME_BAD = re.compile('[\x00-\x1f\x7f<>:"|?*]')
_NAME_EDGES = _TRIMMED + "."
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lower(name: str) -> str:
    """``name`` with A to Z folded, and nothing else: two names that differ
    only so would be one file where a folder ignores case."""
    return name.translate(_ASCII_LOWER)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def bundle_name(name) -> str:
    """A file's name as a bundle holds it: the last part of a path, with
    what XML cannot carry dropped, what a folder cannot hold (control
    characters and ``<>:"|?*``) made an underscore, and blanks and dots
    taken off its ends; ``file`` where nothing is left."""
    text = re.split(r"[/\\]", _text(name))[-1]
    text = _NAME_BAD.sub("_", text).strip(_NAME_EDGES)
    return text or "file"


def _placed(items: list[dict]) -> list[dict]:
    """One folder's files named as the bundle holds them, in order: sorted
    by name and hash, a file listed twice (the same name, but for case, and
    the same bytes) once, and a different file under a name already taken
    numbered, as ``sheet (2).xlsx``."""
    out = []
    taken: set[str] = set()
    seen: dict[str, set[str]] = {}
    for item in sorted(items, key=lambda i: (i["name"], i["sha256"])):
        low = _lower(item["name"])
        if item["sha256"] in seen.get(low, set()):
            continue
        seen.setdefault(low, set()).add(item["sha256"])
        name = item["name"]
        if _lower(name) in taken:
            dot = name.rfind(".")
            stem, ext = (name[:dot], name[dot:]) if dot > 0 else (name, "")
            k = 2
            while _lower(f"{stem} ({k}){ext}") in taken:
                k += 1
            name = f"{stem} ({k}){ext}"
        taken.add(_lower(name))
        out.append(dict(item, name=name))
    return out


# ---------------------------------------------------------------------------
# What the bundle writes for itself
# ---------------------------------------------------------------------------

def _made_line(facts: dict) -> str:
    made_on = facts["made_on"]
    when = phrase("bundle.on_day", date=made_on) if made_on else phrase("bundle.on_no_day")
    calibration = facts["calibration"]["name"] or phrase("verification.calibration_unstated")
    return phrase("bundle.made", engine=facts["engine"]["name"], version=facts["engine"]["version"],
                  when=when, calibration=calibration)


def bundle_readme(facts: dict) -> str:
    """README.txt: what the bundle is and how to check it, from the facts
    ``manifest.json`` records, so a check can write it again and compare."""
    title = facts["title"]
    folders = phrase_table("bundle.folders")
    lines = [phrase("bundle.readme_title", title=title) if title else phrase("bundle.readme_title_bare"),
             _made_line(facts), "", phrase("bundle.readme_lead"), ""]
    lines += [phrase("bundle.readme_entry", name=f"{folder}/", what=folders[folder]) for folder in FOLDERS]
    lines += [phrase("bundle.readme_entry", name=BUNDLE_MANIFEST, what=folders["manifest"]), "",
              phrase("bundle.readme_check"), phrase("bundle.readme_check_toolkit"),
              phrase("bundle.readme_check_hand"), phrase("bundle.readme_check_outside")]
    return "\n".join(lines) + "\n"


def bundle_note(folder: str) -> str:
    """The note a folder that holds nothing carries."""
    return phrase_table("bundle.empty_notes")[folder] + "\n"


def bundle_readiness(states) -> str:
    """The readiness of a bundle's documents taken together: the least
    ready of those a certification gate was run for, and ``not_assessed``
    where none was. A bundle holding one provisional document is not a
    certification, however ready the rest are. That is a choice."""
    gated = [state for state in states if state != "not_assessed"]
    if not gated:
        return "not_assessed"
    for state in ("not_ready", "ready_with_overrides"):
        if state in gated:
            return state
    return "ready"


def bundle_manifest(facts: dict) -> str:
    """``manifest.json`` as both engines write it: two-space indents, keys
    in one order, text as it is (UTF-8, not escaped) and a newline at the
    end, which ``JSON.stringify(facts, null, 2)`` writes byte for byte."""
    return json.dumps(facts, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# A document in a bundle
# ---------------------------------------------------------------------------

def _document_of(data: bytes, checked: dict | None = None) -> dict | None:
    """A sealed document's manifest, its hash and its parts, or None where
    it carries none that can be relied on or has changed since it was
    written. ``checked`` is what :func:`verify_document` already said of
    it, against any issue records."""
    checked = checked if checked is not None else verify_document(data, None)
    if checked["verdict"] not in _SOUND:
        return None
    parts = read_package(data)
    manifest = _manifest_of(parts or {})
    if parts is None or manifest is None:  # pragma: no cover - verify_document said it was sound
        return None
    return {"manifest": manifest, "sha256": checked["sha256"], "parts": parts}


def _document_entry(path: str, held: dict) -> dict:
    """What ``manifest.json`` lists of a document: where it is, its code and
    hash, and what its own manifest records of it."""
    facts, readiness = held["manifest"]["facts"], held["manifest"]["facts"]["readiness"]
    return {"path": path, "code": held["manifest"]["code"], "sha256": held["sha256"],
            "kind": facts["document"]["kind"], "title": facts["document"]["title"],
            "issued_on": facts["document"]["issued_on"], "readiness": readiness["state"],
            "items": [dict(item) for item in readiness["items"]]}


def document_figures(name, data: bytes) -> list[dict]:
    """The figures a document embeds, taken out of it as it embeds them:
    each image its manifest lists among its parts (not the cover's code,
    which is a carrier), named after the document, ready for
    :func:`build_evidence_bundle`'s ``figures`` folder. None from a document
    with no manifest that can be relied on."""
    held = _document_of(data)
    if held is None:
        return []
    stem = bundle_name(name)
    if _lower(stem).endswith(".docx") and len(stem) > len(".docx"):
        stem = stem[:-len(".docx")]
    out = []
    for part, _ in held["manifest"]["parts"]:
        if part.startswith("word/media/"):
            image = part[len("word/media/"):].replace("/", "_")
            out.append({"folder": "figures", "name": f"{stem} - {image}", "data": held["parts"][part],
                        "what": ""})
    return out


# ---------------------------------------------------------------------------
# Building a bundle
# ---------------------------------------------------------------------------

def _stored_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """A ZIP archive of ``entries`` as given, each stored, dated 1980-01-01
    00:00, a name in ASCII as it is and any other flagged UTF-8, with no
    extra fields, comments or attributes: the same bytes in both engines."""
    chunks: list[bytes] = []
    central: list[bytes] = []
    offset = 0
    for name, body in entries:
        raw = name.encode("utf-8")
        flags = 0 if name.isascii() else 0x800
        crc = zlib.crc32(body) & 0xFFFFFFFF
        head = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, 0, 0, 0x21, crc, len(body), len(body),
                           len(raw), 0) + raw
        central.append(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, flags, 0, 0, 0x21, crc,
                                   len(body), len(body), len(raw), 0, 0, 0, 0, 0, offset) + raw)
        chunks += [head, body]
        offset += len(head) + len(body)
    directory = b"".join(central)
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), len(directory), offset, 0)
    return b"".join(chunks) + directory + end


def build_evidence_bundle(title, files, *, borehole="", made_on="", engine=None, calibration=None,
                          records=None) -> dict:
    """An evidence bundle of ``files``: ``{"bytes", "manifest", "sha256",
    "facts"}``, the archive, its ``manifest.json``, that file's SHA-256 (the
    bundle's hash) and what it records.

    ``files`` are ``{"folder", "name", "data", "what"}`` mappings: the folder
    one of :data:`FOLDERS`, the name as the file was called (cleaned by
    :func:`bundle_name`), its bytes, and what it is (a source file's kind of
    sheet; blank for the folder's own word). ``title`` and ``borehole`` say
    what the bundle is about, ``made_on`` is the day it is made (an input,
    never the clock; blank where none is given), ``engine`` is ``(name,
    version)`` (this engine's by default), ``calibration`` the set in force
    as :func:`~groundwater.verification.calibration_facts` names it (None:
    not stated), and ``records`` the project's issue records.

    A document that does not pass its own check (one with no manifest, or
    changed since it was written), a folder that is not one of the five, a
    file too large to be read back and nothing at all raise ValueError: a
    bundle that carries any of them is worse than none.
    """
    from . import __version__

    when = _text(made_on)
    if when and iso_date(when) is None:
        raise ValueError(phrase("verification.bad_date", date=when))
    name_version = engine if engine is not None else (ENGINE, __version__)
    cal = {"name": "", "sha256": ""}
    if calibration is not None:
        cal = {"name": _text(calibration.get("name")), "sha256": _text(calibration.get("sha256"))}
        if not cal["name"] or not _HEX64.fullmatch(cal["sha256"]):
            raise ValueError(phrase("verification.bad_calibration"))
    words = phrase_table("bundle.what")
    by_folder: dict[str, list[dict]] = {folder: [] for folder in FOLDERS}
    documents: dict[str, dict] = {}
    for item in files or ():
        folder = _text(item.get("folder"))
        if folder not in by_folder:
            raise ValueError(phrase("bundle.bad_folder", folder=folder))
        data = bytes(item.get("data") or b"")
        name = bundle_name(item.get("name"))
        if len(data) > MAX_PART_BYTES:
            raise ValueError(phrase("bundle.file_too_big", name=name))
        digest = _sha256(data)
        if folder == "reports":
            held = _document_of(data)
            if held is None:
                why = verify_document(data, None)["lines"][0]
                raise ValueError(phrase("bundle.bad_document", name=name, why=why))
            documents[digest] = held
        by_folder[folder].append({"name": name, "sha256": digest, "data": data,
                                  "what": _text(item.get("what")) or words[folder]})
    if not any(by_folder.values()):
        raise ValueError(phrase("bundle.nothing"))

    entries: list[dict] = []
    doc_entries = []
    for folder in FOLDERS:
        placed = _placed(by_folder[folder])
        if not placed:
            entries.append({"path": f"{folder}/{NOTE}", "what": words["note"],
                            "data": bundle_note(folder).encode("utf-8")})
        for item in placed:
            path = f"{folder}/{item['name']}"
            entries.append({"path": path, "what": item["what"], "data": item["data"]})
            if folder == "reports":
                doc_entries.append(_document_entry(path, documents[item["sha256"]]))
    doc_entries.sort(key=lambda d: d["path"])
    facts = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "title": _text(title),
        "borehole": _text(borehole),
        "made_on": when,
        "engine": {"name": _text(name_version[0]), "version": _text(name_version[1])},
        "calibration": cal,
        "readiness": bundle_readiness(d["readiness"] for d in doc_entries),
        "documents": doc_entries,
        "issued": clean_issue_records(list(records or [])),
        "files": [],
    }
    entries.append({"path": BUNDLE_README, "what": words["readme"],
                    "data": bundle_readme(facts).encode("utf-8")})
    entries.sort(key=lambda e: e["path"])
    if len(entries) + 1 > MAX_ENTRIES:
        raise ValueError(phrase("bundle.bundle_too_big"))
    facts["files"] = [{"path": e["path"], "what": e["what"], "bytes": len(e["data"]),
                       "sha256": _sha256(e["data"])} for e in entries]
    manifest = bundle_manifest(facts)
    raw_manifest = manifest.encode("utf-8")
    if sum(len(e["data"]) for e in entries) + len(raw_manifest) > MAX_PACKAGE_BYTES:
        raise ValueError(phrase("bundle.bundle_too_big"))
    pairs = sorted([(e["path"], e["data"]) for e in entries] + [(BUNDLE_MANIFEST, raw_manifest)])
    return {"bytes": _stored_zip(pairs), "manifest": manifest, "sha256": _sha256(raw_manifest),
            "facts": facts}


# ---------------------------------------------------------------------------
# Reading manifest.json back
# ---------------------------------------------------------------------------

def _refuse_constant(token: str):
    raise ValueError(token)


def _str(value) -> str:
    if not isinstance(value, str):
        raise ValueError("text")
    return _text(value)


def _int(value, top: int) -> int:
    if type(value) is not int or not 0 <= value <= top:
        raise ValueError("count")
    return value


def _dict(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("object")
    return value


def _list(value) -> list:
    if not isinstance(value, list):
        raise ValueError("list")
    return value


def _day(value) -> str:
    day = _str(value)
    if day and iso_date(day) is None:
        raise ValueError("day")
    return day


def _items(raw, state: str) -> list[dict]:
    items = []
    for value in _list(raw):
        item = _dict(value)
        items.append({key: _str(item.get(key)) for key in ("state", "title", "by", "reason")})
    if (state not in READINESS_STATES
            or any(i["state"] not in ("unmet", "overridden") for i in items)
            or any(i["state"] == "unmet" and (i["by"] or i["reason"]) for i in items)
            or (state == "not_assessed" and items)
            or (state != "not_assessed" and state != _readiness_state(items))):
        raise ValueError("readiness")
    return items


def _path_ok(path: str) -> bool:
    if path == BUNDLE_README:
        return True
    folder, _, name = path.partition("/")
    return folder in FOLDERS and bool(name) and bundle_name(name) == name


def _facts_from(obj) -> dict:
    """What a parsed manifest.json records, cleaned as it would have been
    written; ValueError where it could not have been written so."""
    obj = _dict(obj)
    if obj.get("format") != BUNDLE_FORMAT or _int(obj.get("version"), 1 << 30) != BUNDLE_VERSION:
        raise ValueError("format")
    engine, cal = _dict(obj.get("engine")), _dict(obj.get("calibration"))
    calibration = {"name": _str(cal.get("name")), "sha256": _str(cal.get("sha256"))}
    if (calibration["name"] or calibration["sha256"]) and not (
            calibration["name"] and _HEX64.fullmatch(calibration["sha256"])):
        raise ValueError("calibration")
    documents = []
    for value in _list(obj.get("documents")):
        d = _dict(value)
        entry: dict = {"path": _str(d.get("path")), "code": _str(d.get("code")),
                       "sha256": _str(d.get("sha256")), "kind": _str(d.get("kind")),
                       "title": _str(d.get("title")), "issued_on": _day(d.get("issued_on")),
                       "readiness": _str(d.get("readiness"))}
        entry["items"] = _items(d.get("items"), entry["readiness"])
        if parse_document_code(entry["code"]) != entry["code"] or not _HEX64.fullmatch(entry["sha256"]):
            raise ValueError("document")
        documents.append(entry)
    files = []
    for value in _list(obj.get("files")):
        f = _dict(value)
        entry = {"path": _str(f.get("path")), "what": _str(f.get("what")),
                 "bytes": _int(f.get("bytes"), MAX_PART_BYTES), "sha256": _str(f.get("sha256"))}
        if not _path_ok(entry["path"]) or not _HEX64.fullmatch(entry["sha256"]):
            raise ValueError("file")
        files.append(entry)
    facts = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "title": _str(obj.get("title")),
        "borehole": _str(obj.get("borehole")),
        "made_on": _day(obj.get("made_on")),
        "engine": {"name": _str(engine.get("name")), "version": _str(engine.get("version"))},
        "calibration": calibration,
        "readiness": _str(obj.get("readiness")),
        "documents": documents,
        "issued": clean_issue_records(_list(obj.get("issued"))),
        "files": files,
    }
    paths = [f["path"] for f in files]
    lowered = [_lower(p) for p in paths]
    if (paths != sorted(paths) or len(set(lowered)) != len(lowered) or BUNDLE_README not in paths
            or any(not any(p.startswith(f"{folder}/") for p in paths) for folder in FOLDERS)):
        raise ValueError("files")
    doc_paths = [d["path"] for d in documents]
    reports = [p for p in paths if p.startswith("reports/")]
    if doc_paths != sorted(set(doc_paths)) or reports != (doc_paths or [f"reports/{NOTE}"]):
        raise ValueError("documents")
    if facts["readiness"] != bundle_readiness(d["readiness"] for d in documents):
        raise ValueError("readiness")
    return facts


def read_bundle_manifest(text) -> dict | None:
    """What a ``manifest.json`` records, or None unless it is exactly what
    :func:`bundle_manifest` writes for what it holds and what it holds is
    sound: one edited by hand, or written by anything else, is not read at
    all."""
    if not isinstance(text, str):
        return None
    try:
        facts = _facts_from(json.loads(text, parse_constant=_refuse_constant))
    except (ValueError, RecursionError):
        return None
    return facts if bundle_manifest(facts) == text else None


# ---------------------------------------------------------------------------
# Verifying a bundle
# ---------------------------------------------------------------------------

def _own_text(path: str, facts: dict) -> bytes | None:
    """What the toolkit writes at ``path`` for these facts: the README, or
    a folder's note; None for any other file."""
    if path == BUNDLE_README:
        return bundle_readme(facts).encode("utf-8")
    folder, _, name = path.partition("/")
    if name == NOTE and folder in FOLDERS:
        return bundle_note(folder).encode("utf-8")
    return None


def _evidence_words(entry: dict) -> str:
    short = entry["sha256"][:16]
    if entry["what"]:
        return phrase("verification.evidence_file", name=entry["name"], what=entry["what"], short=short)
    return phrase("verification.evidence_file_bare", name=entry["name"], short=short)


def verify_evidence_bundle(data: bytes, records=None) -> dict:
    """What can be said of an evidence bundle: whether every file is as it
    was made, whether each document in it passes its own check and was
    issued, and what confirms each file from outside the bundle.

    ``records`` are the issue records to check its documents against (a
    project file's and an asset record's, as
    :func:`~groundwater.verification.clean_issue_records` takes them), or
    None when none were given, which the answer says. Returns the verdict
    (one of :data:`BUNDLE_VERDICTS`), the bundle's hash, what its
    manifest.json records (``facts``), each file (``files``: its path, what
    it is, its size and listed hash, the hash found, its ``state`` - ``ok``,
    ``changed``, ``missing`` or ``added`` - what ``confirmed`` it -
    ``issue_record``, ``document``, ``toolkit`` or ``none`` - and the
    documents that list it), each document (``documents``: its own verdict,
    code and hash, whether manifest.json lists it as it is, and whether the
    bundle's own issue records hold it) and the lines the pages and the
    command line print.
    """
    report: dict = {"verdict": "unreadable", "sha256": "", "facts": None, "files": [], "documents": [],
                    "lines": []}
    parts = read_package(data)
    if parts is None:
        return _bundle_answered(report, [phrase("bundle.unreadable")])
    if BUNDLE_MANIFEST not in parts:
        report["verdict"] = "no_manifest"
        return _bundle_answered(report, [phrase("bundle.no_manifest")])
    try:
        facts = read_bundle_manifest(parts[BUNDLE_MANIFEST].decode("utf-8"))
    except UnicodeDecodeError:
        facts = None
    if facts is None:
        report["verdict"] = "damaged_manifest"
        return _bundle_answered(report, [phrase("bundle.damaged")])
    report["sha256"] = _sha256(parts[BUNDLE_MANIFEST])
    report["facts"] = facts
    outside = None if records is None else clean_issue_records(records)
    own = {r["sha256"] for r in facts["issued"]}

    documents = []
    listing: dict[str, set[str]] = {}      # a hash -> the sound documents that list it
    confirming: set[str] = set()           # the hashes verified documents list
    evidence: list[dict] = []
    for entry in facts["documents"]:
        body = parts.get(entry["path"])
        doc = {"path": entry["path"], "present": body is not None, "verdict": "", "issued": "",
               "code": "", "sha256": "", "agrees": False, "held": False, "headline": ""}
        if body is not None:
            checked = verify_document(body, outside)
            doc.update(verdict=checked["verdict"], issued=checked["issued"], code=checked["code"],
                       sha256=checked["sha256"], headline=checked["lines"][0],
                       held=checked["sha256"] in own)
            held = _document_of(body, checked)
            if held is not None:
                doc["agrees"] = _document_entry(entry["path"], held) == entry
                manifest = held["manifest"]
                hashes = {digest for _, digest in manifest["parts"]}
                hashes |= {f["sha256"] for f in manifest["facts"]["evidence"]}
                for digest in hashes:
                    listing.setdefault(digest, set()).add(entry["path"])
                if checked["verdict"] == "verified":
                    confirming |= hashes
                for f in manifest["facts"]["evidence"]:
                    if f not in evidence:
                        evidence.append(f)
        documents.append(doc)
    by_path = {d["path"]: d for d in documents}

    files = []
    found_hashes = set()
    for entry in facts["files"]:
        path = entry["path"]
        body = parts.get(path)
        found = "" if body is None else _sha256(body)
        if found:
            found_hashes.add(found)
        if body is None:
            state = "missing"
        elif found == entry["sha256"] and len(body) == entry["bytes"]:
            state = "ok"
        else:
            state = "changed"
        confirmed = "none"
        if state == "ok":
            if path in by_path:
                confirmed = "issue_record" if by_path[path]["verdict"] == "verified" else "none"
            elif body == _own_text(path, facts):
                confirmed = "toolkit"
            elif found in confirming:
                confirmed = "document"
        files.append({"path": path, "what": entry["what"], "bytes": entry["bytes"], "sha256": entry["sha256"],
                      "found": found, "state": state, "confirmed": confirmed,
                      "listed_by": sorted(p for p in listing.get(found, ()) if p != path)})
    listed = {f["path"] for f in facts["files"]}
    for path in sorted(p for p in parts if p not in listed and p != BUNDLE_MANIFEST):
        found = _sha256(parts[path])
        found_hashes.add(found)
        files.append({"path": path, "what": "", "bytes": len(parts[path]), "sha256": "", "found": found,
                      "state": "added", "confirmed": "none", "listed_by": []})
    report["files"], report["documents"] = files, documents

    broken = (any(f["state"] != "ok" for f in files)
              or any(d["present"] and not (d["verdict"] in _SOUND and d["agrees"]) for d in documents))
    if broken:
        verdict = "changed"
    elif outside is None:
        verdict = "unconfirmed"
    elif any(d["verdict"] == "not_issued" for d in documents):
        verdict = "not_issued"
    elif documents and all(f["confirmed"] != "none" for f in files):
        verdict = "verified"
    else:
        verdict = "unconfirmed"
    report["verdict"] = verdict

    lines = []
    if not any(f["state"] != "ok" for f in files):
        lines.append(phrase("bundle.files_match", n=len(files)))
    for state, key in (("changed", "bundle.files_changed"), ("missing", "bundle.files_missing"),
                       ("added", "bundle.files_added")):
        paths = [f["path"] for f in files if f["state"] == state]
        if paths:
            lines.append(phrase(key, paths="; ".join(paths)))
    for entry, doc in zip(facts["documents"], documents, strict=True):
        if not doc["present"]:
            continue
        lines.append(phrase("bundle.document_line", path=doc["path"], code=entry["code"],
                            verdict=doc["headline"]))
        if doc["verdict"] in _SOUND and not doc["agrees"]:
            lines.append(phrase("bundle.document_disagrees", path=doc["path"], code=entry["code"]))
    if outside is None:
        lines.append(phrase("bundle.confirm_no_records"))
    else:
        resting = [f["path"] for f in files if f["confirmed"] == "none"]
        if resting:
            lines.append(phrase("bundle.confirm_some", k=len(files) - len(resting), n=len(files),
                                paths="; ".join(resting)))
        else:
            lines.append(phrase("bundle.confirm_all", n=len(files)))
    missing = [f for f in evidence if f["sha256"] not in found_hashes]
    if missing:
        missing.sort(key=lambda f: (f["what"], f["name"], f["sha256"]))
        lines.append(phrase("bundle.not_carried", n=len(missing),
                            files="; ".join(_evidence_words(f) for f in missing)))
    lines.append(phrase("bundle.readiness", words=phrase_table("bundle.readiness_words")[facts["readiness"]]))
    lines.append(_made_line(facts))
    return _bundle_answered(report, lines)


def _bundle_answered(report: dict, lines: list[str]) -> dict:
    report["lines"] = [phrase_table("bundle.verdicts")[report["verdict"]], *lines]
    return report

"""Documents that can be verified (PLAN.md step 8.1).

Every document either engine writes carries a manifest of what it is and of
every part's hash, and a code printed in its footers and on its cover. These
hold the code, the manifest, the package reader, the four answers and the
issue records to what groundwater/verification.py says of them, and the
step's own test of done: one digit changed in a downloaded report fails the
check, which names the part.
"""

from __future__ import annotations

import base64
import io
import json
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
import yaml

from groundwater import verification as V
from groundwater.cli import main
from groundwater.config import Config
from groundwater.registry import Asset, asset_from_dict, asset_from_project, check_character
from groundwater.reporting.docx_utils import ReportBuilder
from groundwater.text import phrase

from conftest import DeflateWriter

REPO = Path(__file__).resolve().parents[1]
ENGINE = ("groundwater-python", "0.3.0")


def _facts(**more):
    base = dict(kind="pumping", title="Pumping Test Report - Kuntoloh", issued_on="2024-05-01",
                engine=ENGINE, calibration=V.calibration_facts(None), readiness=None,
                evidence=[V.evidence_entry("pumping test sheet", "kuntolo.xlsx", b"readings")])
    base.update(more)
    return V.manifest_facts(**base)


def _zip(entries: dict, *, stored=()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name in stored else zipfile.ZIP_DEFLATED
            z.writestr(info, entries[name])
    return buffer.getvalue()


_CONTENT = {
    "[Content_Types].xml": b'<?xml version="1.0"?><Types xmlns="t"><Default Extension="rels" ContentType="r"/></Types>',
    "word/_rels/document.xml.rels": b'<Relationships xmlns="r"></Relationships>',
    "word/document.xml": b"<w:document>The safe yield is 1.25 m3/h.</w:document>",
}


def _sealed(**more):
    return V.seal_package(dict(_CONTENT), _facts(**more),
                          lambda code: {"word/footer1.xml": f"Document {code} - page".encode()})


def _rezip(sealed, change=None, drop=(), add=None) -> bytes:
    entries = {n: d for n, d in sealed["entries"].items() if n not in drop}
    for name, (old, new) in (change or {}).items():
        assert entries[name].count(old) == 1
        entries[name] = entries[name].replace(old, new)
    entries.update(add or {})
    return _zip(entries)


# ------------------------------------------------------------------ the code

def test_the_code_is_forty_bits_in_crockford_base_32_with_a_check_character():
    digest = "0123456789" + "f" * 54
    code = V.document_code(digest)
    body = code[:4] + code[5:9]
    assert len(code) == 11 and code[4] == code[9] == "-"
    assert int("".join(f"{'0123456789ABCDEFGHJKMNPQRSTVWXYZ'.index(c):05b}" for c in body), 2) == 0x0123456789
    assert code[10] == check_character(body)
    assert V.parse_document_code(code) == code


@pytest.mark.parametrize("typed", ["document 0a1b-2c3d", "0A1B2C3D", " 0a1b 2c3d ", "0A1B_2C3D",
                                   "DOCUMENT\t0A1B-2C3D", "OA1B-2C3D", "0A1B-2C3D﻿"])
def test_a_typed_or_scanned_code_is_read_as_the_toolkit_writes_it(typed):
    body = "0A1B2C3D"
    code = f"{body[:4]}-{body[4:]}-{check_character(body)}"
    assert V.parse_document_code(typed + check_character(body).lower()) == code


@pytest.mark.parametrize("typed", ["", "0A1B-2C3D", "0A1B-2C3D-EE", "0A1B-2C3Ü-E", None, 7,
                                   "0A1B-2C3D-İ"])
def test_what_is_not_a_code_is_refused(typed):
    assert V.parse_document_code(typed) is None


def test_a_wrong_check_character_is_refused():
    body = "0A1B2C3D"
    good = check_character(body)
    for wrong in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if wrong != good:
            assert V.parse_document_code(body + wrong) is None


# -------------------------------------------------------------- the manifest

def test_the_manifest_is_one_element_a_line_and_reads_back_whole():
    sealed = _sealed()
    text = sealed["manifest"]
    assert text.startswith('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                           '<manifest xmlns="urn:groundwater-toolkit:manifest" format="1">\n')
    held = V.read_manifest(text)
    assert held["code"] == sealed["code"]
    assert held["facts"] == _facts()
    assert [name for name, _ in held["carriers"]] == ["word/footer1.xml"]
    assert "word/document.xml" in dict(held["parts"])
    assert V.MANIFEST_PART not in dict(held["parts"])


@pytest.mark.parametrize(("old", "new"), [
    ('format="1"', 'format="2"'),
    ('<engine name=', '<engine  name='),
    ('kind="pumping" title=', 'title="x" kind="pumping" x='),
    ("</evidence>", "</evidence>\n"),
    # a state its items do not give (not_ready with nothing outstanding)
    ('state="not_assessed"', 'state="not_ready"'),
    ("Kuntoloh", "Kuntoloh&#x41;"),
    ("Kuntoloh", "Kuntoloh&apos;"),
    ("Kuntoloh", "Kuntoloh "),
    ("Kuntoloh", "Kuntoloh\t"),
    ('<carriers>\n<part name="word/footer1.xml"', '<carriers>\n<part name="word/document.xml"'),
])
def test_a_manifest_not_exactly_as_the_toolkit_writes_one_is_not_read(old, new):
    text = _sealed()["manifest"]
    assert text.count(old) >= 1
    assert V.read_manifest(text.replace(old, new, 1)) is None


def test_a_manifest_with_parts_out_of_order_or_twice_is_not_read():
    text = _sealed()["manifest"]
    lines = text.split("\n")
    parts = [k for k, line in enumerate(lines) if line.startswith("<part ")]
    swapped = list(lines)
    swapped[parts[0]], swapped[parts[1]] = swapped[parts[1]], swapped[parts[0]]
    assert V.read_manifest("\n".join(swapped)) is None
    doubled = list(lines)
    doubled.insert(parts[0], lines[parts[0]])
    assert V.read_manifest("\n".join(doubled)) is None
    assert V.read_manifest("﻿" + text) is None
    assert V.read_manifest(text.rstrip("\n")) is None


def test_what_cannot_be_written_is_refused_or_dropped():
    with pytest.raises(ValueError, match="2024-02-30"):
        _facts(issued_on="2024-02-30")
    with pytest.raises(ValueError, match="kuntolo"):
        _facts(evidence=[{"what": "x", "name": "kuntolo.xlsx", "sha256": "abc"}])
    with pytest.raises(ValueError):
        _facts(calibration={"name": "a set", "sha256": ""})
    facts = _facts(title=" A\x00 title\ud800 ", kind=7)
    assert facts["document"]["title"] == "A title" and facts["document"]["kind"] == ""
    # one evidence file listed twice is listed once
    twice = [V.evidence_entry("photograph", "p.jpg", b"1")] * 2
    assert len(_facts(evidence=twice)["evidence"]) == 1


def test_the_readiness_a_manifest_records_is_the_gates():
    from groundwater.readiness import assess_readiness

    gate = assess_readiness({}, "pumping", {"site_located": {"reason": "plate only", "by": "A. Kamara"}})
    facts = V.readiness_facts(gate)
    assert facts["state"] == gate.state == "not_ready"
    assert [i["title"] for i in facts["items"]] == [r.title for r in gate.requirements
                                                     if r.state in ("unmet", "overridden")]
    overridden = [i for i in facts["items"] if i["state"] == "overridden"]
    assert overridden and overridden[0]["by"] == "A. Kamara" and overridden[0]["reason"] == "plate only"
    assert V.readiness_facts(None) == {"state": "not_assessed", "items": []}


# ------------------------------------------------------- verifying a package

def test_a_document_as_written_is_unchanged_and_needs_a_record_to_be_verified():
    sealed = _sealed()
    data = _rezip(sealed)
    report = V.verify_document(data)
    assert report["verdict"] == "unconfirmed" and report["issued"] == "not_checked"
    assert report["code"] == sealed["code"] and report["sha256"] == sealed["sha256"]
    assert V.verify_document(data, [sealed["record"]])["verdict"] == "verified"
    assert V.document_record(data) == sealed["record"]
    other = _sealed(issued_on="2024-05-02")
    assert other["code"] != sealed["code"]
    no_record = V.verify_document(data, [other["record"]])
    assert no_record["verdict"] == "not_issued" and no_record["issued"] == "no_record"
    assert no_record["answers"]["issued"] == phrase("verification.issued_no_record", n=1, code=sealed["code"])


def test_one_digit_changed_fails_the_check_and_names_the_part():
    """PLAN.md step 8.1's test of done, on a package."""
    sealed = _sealed()
    data = _rezip(sealed, change={"word/document.xml": (b"1.25", b"1.35")})
    report = V.verify_document(data, [sealed["record"]])
    assert report["verdict"] == "changed"
    assert report["changed"] == ["word/document.xml"] and not report["missing"] and not report["added"]
    assert "word/document.xml (the text of the document)" in report["answers"]["changed"]
    # the manifest itself is as issued, and the first answer says so
    assert report["issued"] == "matched"


def test_a_part_removed_or_added_is_named():
    sealed = _sealed()
    removed = V.verify_document(_rezip(sealed, drop=["word/footer1.xml"]))
    assert removed["verdict"] == "changed" and removed["missing"] == ["word/footer1.xml"]
    added = V.verify_document(_rezip(sealed, add={"word/media/image9.png": b"png"}))
    assert added["verdict"] == "changed" and added["added"] == ["word/media/image9.png"]
    assert "an image" in added["answers"]["changed"]


def test_a_manifest_brought_into_line_with_a_changed_part_no_longer_gives_its_code():
    sealed = _sealed()
    entries = dict(sealed["entries"])
    entries["word/document.xml"] = entries["word/document.xml"].replace(b"1.25", b"9.25")
    old = V.read_manifest(sealed["manifest"])
    parts = [(n, V._sha256(entries[n]) if n == "word/document.xml" else d) for n, d in old["parts"]]
    entries[V.MANIFEST_PART] = V.manifest_xml(old["facts"], old["code"], parts, old["carriers"]).encode()
    report = V.verify_document(_zip(entries))
    assert report["verdict"] == "altered_manifest" and report["facts"] is None
    assert report["answers"]["readiness"] == "" and report["answers"]["evidence"] == ""


def test_a_readiness_rewritten_in_the_manifest_no_longer_gives_its_code():
    sealed = _sealed(readiness={"state": "not_ready", "items": [
        {"state": "unmet", "title": "Site position", "by": "", "reason": ""}]})
    text = sealed["manifest"].replace('<readiness state="not_ready">\n<item state="unmet" '
                                      'title="Site position" by="" reason=""/>', '<readiness state="ready">')
    assert text != sealed["manifest"] and V.read_manifest(text) is not None
    entries = dict(sealed["entries"], **{V.MANIFEST_PART: text.encode()})
    assert V.verify_document(_zip(entries))["verdict"] == "altered_manifest"


def test_a_copy_that_differs_only_where_the_code_is_printed_is_not_as_issued():
    sealed = _sealed()
    entries = dict(sealed["entries"])
    entries["word/footer1.xml"] = entries["word/footer1.xml"].replace(b"page", b"PAGE")
    old = V.read_manifest(sealed["manifest"])
    carriers = [("word/footer1.xml", V._sha256(entries["word/footer1.xml"]))]
    entries[V.MANIFEST_PART] = V.manifest_xml(old["facts"], old["code"], old["parts"], carriers).encode()
    report = V.verify_document(_zip(entries), [sealed["record"]])
    assert report["issued"] == "record_differs" and report["verdict"] == "changed"
    assert not report["changed"]


@pytest.mark.parametrize("damage", ["no zip", "no manifest", "not utf-8", "empty manifest"])
def test_what_cannot_be_read_says_so(damage):
    sealed = _sealed()
    if damage == "no zip":
        data, verdict = b"PK\x03\x04 not a package", "unreadable"
    elif damage == "no manifest":
        data, verdict = _rezip(sealed, drop=[V.MANIFEST_PART]), "no_manifest"
    else:
        body = b"\xff\xfe" if damage == "not utf-8" else b""
        data, verdict = _zip(dict(sealed["entries"], **{V.MANIFEST_PART: body})), "damaged_manifest"
    report = V.verify_document(data)
    assert report["verdict"] == verdict and report["lines"][0] == phrase_table_verdict(verdict)
    assert V.document_record(data) is None


def phrase_table_verdict(verdict: str) -> str:
    from groundwater.text import phrase_table

    return phrase_table("verification.verdicts")[verdict]


# ----------------------------------------------------------- the ZIP reader

def test_the_package_reader_reads_what_zipfile_reads():
    data = _rezip(_sealed())
    parts = V.read_package(data)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert parts == {name: z.read(name) for name in z.namelist()}
    stored = _zip(dict(_CONTENT), stored=set(_CONTENT))
    assert V.read_package(stored) == _CONTENT


def _entry(name: bytes, body: bytes, *, method=0, flags=0, crc=None, usize=None, payload=None):
    payload = body if payload is None else payload
    crc = (__import__("zlib").crc32(body) & 0xFFFFFFFF) if crc is None else crc
    usize = len(body) if usize is None else usize
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, method, 0, 0x21, crc, len(payload), usize,
                        len(name), 0) + name + payload
    return local, (flags, method, crc, len(payload), usize, name)


def _package(entries, *, comment=b"", junk=b"") -> bytes:
    out, central = b"", b""
    for local, (flags, method, crc, csize, usize, name) in entries:
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, flags, method, 0, 0x21, crc, csize,
                               usize, len(name), 0, 0, 0, 0, 0, len(out)) + name
        out += local
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), len(central), len(out),
                      len(comment)) + comment
    return out + central + end + junk


def test_the_package_reader_refuses_what_it_cannot_vouch_for():
    good = _package([_entry(b"a.xml", b"<a/>")])
    assert V.read_package(good) == {"a.xml": b"<a/>"}
    assert V.read_package(_package([_entry(b"a.xml", b"<a/>")], comment=b"note")) == {"a.xml": b"<a/>"}
    raw = DeflateWriter()
    raw.fixed(list(b"<a/>"), last=True)
    raw._align()
    deflated = bytes(raw.body)
    assert V.read_package(_package([_entry(b"a.xml", b"<a/>", method=8, payload=deflated)])) == {"a.xml": b"<a/>"}
    refused = {
        "after the end": _package([_entry(b"a.xml", b"<a/>")], junk=b"x"),
        "named twice": _package([_entry(b"a.xml", b"<a/>"), _entry(b"a.xml", b"<b/>")]),
        "a bad CRC": _package([_entry(b"a.xml", b"<a/>", crc=1)]),
        "a size that lies": _package([_entry(b"a.xml", b"<a/>", usize=5)]),
        "encrypted": _package([_entry(b"a.xml", b"<a/>", flags=1)]),
        "another method": _package([_entry(b"a.xml", b"<a/>", method=12)]),
        "a name not ASCII": _package([_entry("é.xml".encode(), b"<a/>")]),
        "a name not UTF-8": _package([_entry(b"\xff.xml", b"<a/>", flags=0x800)]),
        "bytes after the stream": _package([_entry(b"a.xml", b"<a/>", method=8, payload=deflated + b"\0")]),
        "a stream cut short": _package([_entry(b"a.xml", b"<a/>", method=8, payload=deflated[:-1])]),
        "nothing": b"",
    }
    for why, data in refused.items():
        assert V.read_package(data) is None, why
    assert V.read_package(_package([_entry("é.xml".encode(), b"<a/>", flags=0x800)])) == {"é.xml": b"<a/>"}


# -------------------------------------------------------------- the writers

@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """A document with a cover and a gate, and one without either."""
    folder = tmp_path_factory.mktemp("sealed")
    from groundwater.readiness import assess_readiness

    def write(name, cover=True, issue=None):
        rb = ReportBuilder(title="A sealed document", kind="pumping", issue=issue, config=Config())
        if cover:
            rb.cover(["A SEALED DOCUMENT"], ["for a test"], [("Client", "Nobody")])
            rb.provisional_stamp(assess_readiness({}, "pumping"))
        rb.heading("1. Results")
        rb.paragraph("The safe yield is 1.25 m3/h.")
        return rb.save(folder / name), rb.record

    issue = V.Issue(issued_on="2026-10-29",
                    evidence=(V.evidence_entry("pumping test sheet", "test.xlsx", b"readings"),))
    return {"cover": write("cover.docx", issue=issue), "again": write("again.docx", issue=issue),
            "plain": write("plain.docx", cover=False)}


def test_a_document_carries_its_code_in_every_footer_and_a_symbol_on_its_cover(built):
    path, record = built["cover"]
    data = path.read_bytes()
    assert record == V.document_record(data)
    parts = V.read_package(data)
    manifest = V.read_manifest(parts[V.MANIFEST_PART].decode())
    carriers = [name for name, _ in manifest["carriers"]]
    assert carriers[:2] == ["word/footer1.xml", "word/footer2.xml"] and carriers[2].startswith("word/media/")
    assert phrase("verification.footer", code=record["code"]).encode() in parts["word/footer1.xml"]
    assert phrase("verification.cover_code", code=record["code"]).encode() in parts["word/footer2.xml"]
    assert b'Target="../customXml/groundwater-manifest.xml"' in parts["word/_rels/document.xml.rels"]
    assert b"<w:titlePg/>" in parts["word/document.xml"]
    cv2 = pytest.importorskip("cv2", reason="no decoder installed")
    image = cv2.imdecode(np.frombuffer(parts[carriers[2]], dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert cv2.QRCodeDetector().detectAndDecode(image)[0] == phrase("verification.qr", code=record["code"])
    report = V.verify_document(data, [record])
    assert report["verdict"] == "verified"
    assert report["facts"]["readiness"]["state"] == "not_ready"
    assert report["facts"]["engine"]["name"] == V.ENGINE
    assert [f["name"] for f in report["facts"]["evidence"]] == ["test.xlsx"]
    assert report["facts"]["document"]["issued_on"] == "2026-10-29"


def test_a_document_issued_again_from_the_same_inputs_is_the_same_bytes(built):
    assert built["cover"][0].read_bytes() == built["again"][0].read_bytes()
    assert built["cover"][1] == built["again"][1]


def test_a_document_with_no_cover_has_its_code_in_the_footer_and_no_symbol(built):
    path, record = built["plain"]
    parts = V.read_package(path.read_bytes())
    manifest = V.read_manifest(parts[V.MANIFEST_PART].decode())
    assert [name for name, _ in manifest["carriers"]] == ["word/footer1.xml"]
    assert not [n for n in parts if n.startswith("word/media/")]
    assert manifest["facts"]["readiness"] == {"state": "not_assessed", "items": []}
    assert manifest["facts"]["document"]["issued_on"] == "" and manifest["facts"]["evidence"] == []
    report = V.verify_document(path.read_bytes())
    assert report["answers"]["readiness"] == phrase("verification.readiness_not_assessed")
    assert report["answers"]["evidence"] == phrase("verification.evidence_none")


def test_one_digit_changed_in_a_written_report_fails_and_names_the_part(built):
    """PLAN.md step 8.1's test of done, on a report as written and saved."""
    path, record = built["cover"]
    with zipfile.ZipFile(path) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    assert entries["word/document.xml"].count(b"1.25") == 1
    entries["word/document.xml"] = entries["word/document.xml"].replace(b"1.25", b"1.26")
    report = V.verify_document(_zip(entries), [record])
    assert report["verdict"] == "changed" and report["changed"] == ["word/document.xml"]
    assert report["lines"][0] == phrase_table_verdict("changed")


def test_a_document_the_browser_wrote_is_read_and_answered_here():
    """The field kit tests/webapp/fieldkit.mjs had Chromium write, deflated
    by its own CompressionStream: this engine reads it, and says of it what
    the browser says (parity.mjs holds the browser to this answer)."""
    data = (REPO / "tests" / "webapp" / "fixtures" / "fieldkit_browser.docx").read_bytes()
    report = V.verify_document(data)
    assert report["verdict"] == "unconfirmed"
    facts = report["facts"]
    assert facts["engine"]["name"] == "gwt-core" and facts["document"]["kind"] == "field_kit"
    assert [name for name, _ in V.read_manifest(V.read_package(data)[V.MANIFEST_PART].decode())["carriers"]] == [
        "word/footer1.xml"]
    record = V.document_record(data)
    assert V.verify_document(data, [record])["verdict"] == "verified"


def test_the_committed_python_document_is_what_the_builder_writes(tmp_path):
    """fixtures/sealed_python.docx, which parity.mjs has the browser read, is
    read here as issued; and what the builder writes from the same inputs
    today has the same parts, the same carriers and the same facts (the
    engine's version apart). Only the bytes python-docx and zlib choose may
    differ, which is why the reference reads the committed file."""
    import importlib.util
    import sys

    fixtures = REPO / "tests" / "webapp" / "fixtures"
    spec = importlib.util.spec_from_file_location("make_sealed_docx", fixtures / "make_sealed_docx.py")
    make = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = make
    spec.loader.exec_module(make)
    data = make.FIXTURE.read_bytes()
    record = V.document_record(data)
    assert record is not None and V.verify_document(data, [record])["verdict"] == "verified"
    fresh = make.build(tmp_path / "fresh.docx").read_bytes()
    held, now = (V.read_manifest(V.read_package(d)[V.MANIFEST_PART].decode()) for d in (data, fresh))
    assert [n for n, _ in now["parts"]] == [n for n, _ in held["parts"]], "run fixtures/make_sealed_docx.py"
    assert [n for n, _ in now["carriers"]] == [n for n, _ in held["carriers"]]
    assert dict(now["facts"], engine=held["facts"]["engine"]) == held["facts"]


def test_the_calibration_set_in_force_is_named(built):
    from groundwater.calibration_sets import default_set, set_name

    path, _ = built["plain"]
    facts = V.read_manifest(V.read_package(path.read_bytes())[V.MANIFEST_PART].decode())["facts"]
    assert facts["calibration"]["name"] == set_name(default_set())


# ---------------------------------------------------------- issue records

def test_issue_records_are_kept_once_each_in_the_order_issued():
    a, b = _sealed()["record"], _sealed(issued_on="2023-01-01")["record"]
    junk = [{"code": "x"}, "a", None, dict(a, readiness="maybe"), dict(a, sha256="ABC"),
            dict(a, issued_on="yesterday")]
    assert V.clean_issue_records([a, b, a, *junk]) == [b, a]
    assert V.clean_issue_records("not a list") == []


def test_a_project_file_and_an_asset_record_carry_their_issue_records():
    from groundwater.project_io import deserialize_project, serialize_project

    record = _sealed()["record"]
    other = dict(_sealed(issued_on="2023-01-01")["record"], kind="desk_study")
    saved = serialize_project({"meta_community": "K", "issued_documents": [record, other, {"bad": 1}]}, "0.3.0")
    payload = yaml.safe_load(saved)
    assert payload["issued"] == [other, record]
    assert deserialize_project(saved)["issued_documents"] == [other, record]
    asset = Asset(asset_id="SL-WAR-8FEEVKQ-E", documents=[record])
    back = asset_from_dict(asset.as_dict())
    assert back is not None and back.documents == [record]
    assert "documents" not in Asset(asset_id="SL-WAR-8FEEVKQ-E").as_dict()
    # either app's file, read for its records: the browser's keeps its asset in its state
    browser = {"issued": [other], "state": {"asset": {"documents": [record]}}}
    assert V.issue_records_of(browser) == [other, record]
    assert V.issue_records_of({"asset": {"documents": [record]}}) == [record]
    assert V.issue_records_of([record]) == []


def test_a_draft_asset_record_carries_the_documents_issued_about_its_borehole():
    from groundwater.models import SiteMetadata

    record = _sealed()["record"]
    desk = dict(_sealed(issued_on="2023-01-01")["record"], kind="desk_study")
    site = SiteMetadata(district="Western Area Rural", easting=694000.0, northing=938150.0, utm_zone=28)
    draft = asset_from_project({"site": site, "issued": [record, desk]})
    assert draft is not None and draft.documents == [record]


def test_a_code_is_looked_up_in_the_records():
    record = _sealed()["record"]
    found = V.lookup_code(record["code"].lower().replace("-", " "), [record])
    assert found["records"] == [record]
    assert found["lines"] == [phrase("verification.code_found", code=record["code"], title=record["title"],
                                     when=phrase("verification.on_day", date="2024-05-01"),
                                     readiness="with no certification gate run", sha256=record["sha256"])]
    assert V.lookup_code("nonsense", [record])["code"] is None
    assert V.lookup_code(record["code"], [])["lines"] == [
        phrase("verification.code_not_found", n=0, code=record["code"])]


# --------------------------------------------------------- the command line

def test_groundwater_verify_says_the_four_things_and_exits_by_the_verdict(tmp_path, capsys, built):
    from groundwater.project_io import serialize_project

    path, record = built["cover"]
    assert main(["verify", str(path)]) == 2
    printed = capsys.readouterr().out
    assert phrase_table_verdict("unconfirmed") in printed and f"code: {record['code']}" in printed
    project = tmp_path / "p.yaml"
    project.write_bytes(serialize_project({"issued_documents": [record]}, "0.3.0"))
    assert main(["verify", str(path), "--project", str(project)]) == 0
    assert phrase_table_verdict("verified") in capsys.readouterr().out
    browser = tmp_path / "p.gwt.json"
    browser.write_text(json.dumps({"schema": 3, "issued": [record], "state": {}}))
    assert main(["verify", str(path), "--project", str(browser)]) == 0
    capsys.readouterr()
    with zipfile.ZipFile(path) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    entries["word/document.xml"] = entries["word/document.xml"].replace(b"1.25", b"7.25")
    changed = tmp_path / "changed.docx"
    changed.write_bytes(_zip(entries))
    assert main(["verify", str(changed), "--project", str(project)]) == 1
    assert "part: word/document.xml" in capsys.readouterr().out
    assert main(["verify", "--code", record["code"], "--project", str(project)]) == 0
    assert record["title"] in capsys.readouterr().out
    assert main(["verify", str(tmp_path / "missing.docx")]) == 1


def test_a_photograph_is_listed_by_the_hash_of_the_file_as_it_arrived():
    """The browser and the Streamlit app list a photograph by its provenance
    record's hash; the bytes stand in only where it has none."""
    import importlib.util
    import sys

    sys.path.insert(0, str(REPO / "app"))
    try:
        spec = importlib.util.find_spec("shared")
        assert spec is not None
        from shared import photo_evidence
    finally:
        sys.path.remove(str(REPO / "app"))
    held = "a" * 64
    assert photo_evidence({"name": "seal.jpg", "provenance": {"sha256": held}, "b64": "AA=="})["sha256"] == held
    raw = base64.b64encode(b"jpeg").decode()
    assert photo_evidence({"name": "seal.jpg", "b64": raw}) == V.evidence_entry("photograph", "seal.jpg", b"jpeg")


def test_the_example_code_the_pages_show_is_a_code():
    """The sentence for a code that cannot be read, and the placeholder of
    the box a code is typed into in each app, give an example: it has to be
    one the check accepts, or the example itself is refused."""
    import re

    code_re = r"[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]"
    shown = re.findall(code_re, phrase("verification.code_unreadable", code="x"))
    for page in (REPO / "app" / "views" / "verify.py", REPO / "docs" / "js" / "gwt-app.js"):
        shown += re.findall(rf"placeholder(?:=\"|: ')({code_re})['\"]", page.read_text(encoding="utf-8"))
    assert len(shown) == 3 and all(V.parse_document_code(code) == code for code in shown), shown

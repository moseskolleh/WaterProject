"""One evidence bundle for each borehole (PLAN.md step 8.3).

A borehole's sheets, tables, figures, documents and signatures in one ZIP
archive with a manifest.json of every file's SHA-256 and a README saying how
to check it, written the same byte for byte by both engines; and the check
that says, file by file, whether a bundle is as it was made and what outside
it confirms each file. These hold groundwater/bundle.py to that, the browser
engine's twin to it in a Node vm, and ``groundwater bundle`` and
``groundwater verify`` to what they print and how they exit.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

from groundwater import bundle as B
from groundwater import verification as V
from groundwater.cli import main
from groundwater.text import phrase, phrase_table

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"
ENGINE = ("groundwater-python", "0.3.0")
SHEET = b"time_min,level_m\n0,12.50\n10,13.25\n"


def _document(text="The safe yield is 1.25 m3/h.", kind="completion", evidence=None, media=None,
              readiness=None, issued_on="2026-10-29") -> bytes:
    """A sealed document, stored: a figure, the cover's code as a carrier
    image, and the sheet it was issued from."""
    content = {"[Content_Types].xml": b'<Types xmlns="t"><Default Extension="rels" ContentType="r"/></Types>',
               "word/_rels/document.xml.rels": b'<Relationships xmlns="r"></Relationships>',
               "word/document.xml": f"<w:document>{text}</w:document>".encode()}
    content.update({"word/media/image1.png": b"\x89PNG figure"} if media is None else media)
    if evidence is None:
        evidence = [V.evidence_entry("pumping test sheet", "case_pumping.xlsx", SHEET)]
    facts = V.manifest_facts(kind, f"{kind} report", issued_on, ENGINE, V.calibration_facts(None),
                             readiness, evidence)
    sealed = V.seal_package(content, facts, lambda code: {
        "word/footer1.xml": f"Document {code} - page".encode(), "word/media/code.png": code.encode()})
    return B._stored_zip(sorted(sealed["entries"].items()))


DOC = _document()
RECORD = V.document_record(DOC)


def _files(doc=DOC, table=True):
    files = [{"folder": "raw", "name": "case_pumping.xlsx", "data": SHEET, "what": "pumping test sheet"},
             {"folder": "reports", "name": "Completion.docx", "data": doc}]
    if table:
        files.append({"folder": "tables", "name": "layered_models.csv", "data": b"sounding,N\nA,1\n"})
    return files + B.document_figures("Completion.docx", doc)


def _bundle(files=None, **options):
    options.setdefault("made_on", "2026-10-31")
    options.setdefault("engine", ENGINE)
    options.setdefault("calibration", V.calibration_facts(None))
    options.setdefault("records", [RECORD])
    return B.build_evidence_bundle("Case borehole", _files() if files is None else files, **options)


def _changed(data: bytes, set_parts=None, drop=(), manifest=None) -> bytes:
    """``data`` with parts replaced or dropped, and manifest.json brought
    into line with the parts named in ``manifest`` (a list) where given."""
    parts = V.read_package(data)
    for name in drop:
        del parts[name]
    parts.update(set_parts or {})
    if manifest is not None:
        facts = B.read_bundle_manifest(V.read_package(data)[B.BUNDLE_MANIFEST].decode())
        for entry in facts["files"]:
            if entry["path"] in manifest:
                entry["sha256"] = hashlib.sha256(parts[entry["path"]]).hexdigest()
                entry["bytes"] = len(parts[entry["path"]])
        parts[B.BUNDLE_MANIFEST] = B.bundle_manifest(facts).encode()
    return B._stored_zip(sorted(parts.items()))


# ------------------------------------------------------------ the archive

def test_a_bundle_is_the_same_bytes_each_time_and_any_zip_reader_reads_it():
    first, second = _bundle(), _bundle()
    assert first["bytes"] == second["bytes"]
    with zipfile.ZipFile(io.BytesIO(first["bytes"])) as z:
        assert z.testzip() is None
        infos = z.infolist()
        names = [i.filename for i in infos]
        assert names == sorted(names)
        # stored, one fixed timestamp, no attributes: nothing a zlib build or
        # a clock chooses
        assert {i.compress_type for i in infos} == {zipfile.ZIP_STORED}
        assert {i.date_time for i in infos} == {(1980, 1, 1, 0, 0, 0)}
        assert {i.external_attr for i in infos} == {0}
        assert z.read(B.BUNDLE_MANIFEST).decode() == first["manifest"]
    assert first["sha256"] == hashlib.sha256(first["manifest"].encode()).hexdigest()
    assert set(names) == {"README.txt", "manifest.json", "raw/case_pumping.xlsx", "reports/Completion.docx",
                          "tables/layered_models.csv", "figures/Completion - image1.png",
                          "signatures/README.txt"}


def test_the_manifest_lists_every_other_file_and_what_it_records():
    built = _bundle()
    facts = built["facts"]
    parts = V.read_package(built["bytes"])
    assert [f["path"] for f in facts["files"]] == sorted(p for p in parts if p != B.BUNDLE_MANIFEST)
    for entry in facts["files"]:
        assert entry["sha256"] == hashlib.sha256(parts[entry["path"]]).hexdigest()
        assert entry["bytes"] == len(parts[entry["path"]])
    assert facts["engine"] == {"name": ENGINE[0], "version": ENGINE[1]}
    assert facts["calibration"] == V.calibration_facts(None)
    assert facts["made_on"] == "2026-10-31" and facts["issued"] == [RECORD]
    (doc,) = facts["documents"]
    assert doc["path"] == "reports/Completion.docx"
    assert {k: doc[k] for k in ("code", "sha256", "kind", "title", "issued_on", "readiness")} == RECORD
    assert facts["readiness"] == "not_assessed"
    assert json.loads(built["manifest"]) == facts
    assert B.read_bundle_manifest(built["manifest"]) == facts


def test_an_empty_folder_carries_a_note_and_the_readme_says_how_to_check_it():
    parts = V.read_package(_bundle(_files(table=False))["bytes"])
    assert parts["tables/README.txt"].decode() == phrase_table("bundle.empty_notes")["tables"] + "\n"
    assert parts["signatures/README.txt"].decode().startswith("This bundle carries no signatures.")
    readme = parts["README.txt"].decode()
    assert readme.splitlines()[0] == "Evidence bundle: Case borehole"
    assert phrase("bundle.readme_check_hand") in readme and "groundwater verify" in readme
    assert "Made by groundwater-python 0.3.0, on 2026-10-31." in readme


def test_the_documents_taken_together_are_as_ready_as_the_least_ready():
    assert B.bundle_readiness([]) == "not_assessed"
    assert B.bundle_readiness(["not_assessed", "ready"]) == "ready"
    assert B.bundle_readiness(["ready", "ready_with_overrides"]) == "ready_with_overrides"
    assert B.bundle_readiness(["ready", "not_ready", "ready_with_overrides"]) == "not_ready"
    gate = {"requirements": [{"state": "unmet", "title": "Site position", "override_by": "",
                              "override_reason": ""}]}
    provisional = _document(kind="pumping", readiness=gate)
    built = _bundle(_files() + [{"folder": "reports", "name": "Pumping.docx", "data": provisional}])
    assert built["facts"]["readiness"] == "not_ready"


# ------------------------------------------------------------ the names

@pytest.mark.parametrize(("name", "held"), [
    ("sheet.xlsx", "sheet.xlsx"), (" a/b\\c.xlsx ", "c.xlsx"), ("..", "file"), (None, "file"),
    ('CON:x?"<1>|*.csv', "CON_x___1___.csv"), ("tab\there.xlsx", "tab_here.xlsx"),
    ("C:\\Users\\field\\Kpètèma BH-1.xlsx", "Kpètèma BH-1.xlsx"), (". .hidden. .", "hidden"),
    ("a\x00b.xlsx", "ab.xlsx")])
def test_a_name_is_what_a_folder_can_hold(name, held):
    assert B.bundle_name(name) == held


def test_a_file_named_twice_is_numbered_and_one_listed_twice_is_kept_once():
    files = [{"folder": "raw", "name": n, "data": d} for n, d in (
        ("a.xlsx", b"1"), ("A.xlsx", b"2"), ("a.xlsx", b"1"), ("a.xlsx", b"3"), ("a (2).xlsx", b"4"),
        ("noext", b"6"), ("NOEXT", b"7"))]
    paths = [f["path"] for f in _bundle(files, records=[])["facts"]["files"] if f["path"].startswith("raw/")]
    # sorted by name and hash first, so "a (2).xlsx" keeps its own name and
    # the two other files called a.xlsx come after it
    assert paths == ["raw/A.xlsx", "raw/NOEXT", "raw/a (2).xlsx", "raw/a (3).xlsx", "raw/a (4).xlsx",
                     "raw/noext (2)"]


# ------------------------------------------------------------ refused

@pytest.mark.parametrize(("change", "words"), [
    ({"files": [{"folder": "photos", "name": "x", "data": b"1"}]}, 'no folder called "photos"'),
    ({"made_on": "2026-02-30"}, "is not a day"),
    ({"calibration": {"name": "a set", "sha256": ""}}, "has to be named with the SHA-256"),
    ({"files": [{"folder": "reports", "name": "u.docx", "data": b"not a document"}]},
     "u.docx cannot go into an evidence bundle: Not a Word document the toolkit can read."),
    ({"files": []}, "There is nothing to put into an evidence bundle"),
])
def test_what_cannot_go_into_a_bundle_is_refused(change, words):
    options = dict(change)
    files = options.pop("files", None)
    with pytest.raises(ValueError, match=re.escape(words)):
        _bundle(files, **options)


def test_a_document_changed_since_it_was_written_is_refused():
    parts = V.read_package(DOC)
    parts["word/document.xml"] = parts["word/document.xml"].replace(b"1.25", b"1.35")
    changed = B._stored_zip(sorted(parts.items()))
    with pytest.raises(ValueError, match="Changed since it was issued"):
        _bundle([{"folder": "reports", "name": "c.docx", "data": changed}])


def test_a_file_too_large_to_read_back_is_refused(monkeypatch):
    monkeypatch.setattr(B, "MAX_PART_BYTES", 4)
    with pytest.raises(ValueError, match="too large for an evidence bundle"):
        _bundle([{"folder": "raw", "name": "big.xlsx", "data": b"12345"}])


# ------------------------------------------------------------ figures

def test_the_figures_are_taken_out_of_a_document_and_not_its_code():
    figures = B.document_figures("Completion Report.docx", _document(media={
        "word/media/image1.png": b"one", "word/media/charts/two.png": b"two"}))
    assert [(f["folder"], f["name"], f["data"]) for f in figures] == [
        ("figures", "Completion Report - charts_two.png", b"two"),
        ("figures", "Completion Report - image1.png", b"one")]
    assert B.document_figures("x.docx", b"not a document") == []


# ------------------------------------------------------------ manifest.json

@pytest.mark.parametrize("edit", [
    lambda t: t.replace('"title": ', '"title":  ', 1), lambda t: t.replace('"version": 1,', '"version": 1.0,'),
    lambda t: t.rstrip("\n"), lambda t: "\ufeff" + t, lambda t: t.replace("\n", "\r\n"),
    lambda t: t.replace('"bytes": ', '"bytes": -', 1), lambda t: t.replace('"made_on": "2026-10-31"',
                                                                           '"made_on": "2026-13-01"'),
    lambda t: t.replace('"readiness": "not_assessed"', '"readiness": "ready"', 1),
])
def test_a_manifest_not_exactly_as_the_toolkit_writes_one_is_not_read(edit):
    text = _bundle()["manifest"]
    assert B.read_bundle_manifest(text) is not None
    assert B.read_bundle_manifest(edit(text)) is None


def test_a_manifest_that_lists_a_file_outside_its_folders_is_not_read():
    facts = _bundle()["facts"]
    for path in ("raw/../x", "raw/a/b.xlsx", "other/x", "manifest.json", "RAW/case_pumping.xlsx"):
        changed = copy.deepcopy(facts)
        changed["files"].append({"path": path, "what": "", "bytes": 1, "sha256": "0" * 64})
        changed["files"].sort(key=lambda f: f["path"])
        assert B.read_bundle_manifest(B.bundle_manifest(changed)) is None, path


# ------------------------------------------------------------ the check

def _verdict(data, records=None):
    return B.verify_evidence_bundle(data, records)


def test_a_bundle_as_made_is_unconfirmed_with_no_record_and_says_why():
    report = _verdict(_bundle()["bytes"])
    assert report["verdict"] == "unconfirmed"
    assert report["lines"][0] == phrase_table("bundle.verdicts")["unconfirmed"]
    assert phrase("bundle.confirm_no_records") in report["lines"]
    assert all(f["state"] == "ok" for f in report["files"])
    sheet = next(f for f in report["files"] if f["path"] == "raw/case_pumping.xlsx")
    assert sheet["listed_by"] == ["reports/Completion.docx"] and sheet["confirmed"] == "none"


def test_a_bundle_whose_every_file_is_confirmed_from_outside_it_is_verified():
    report = _verdict(_bundle(_files(table=False))["bytes"], [RECORD])
    assert report["verdict"] == "verified", report["lines"]
    confirmed = {f["path"]: f["confirmed"] for f in report["files"]}
    assert confirmed == {"README.txt": "toolkit", "figures/Completion - image1.png": "document",
                         "raw/case_pumping.xlsx": "document", "reports/Completion.docx": "issue_record",
                         "signatures/README.txt": "toolkit", "tables/README.txt": "toolkit"}
    assert phrase("bundle.confirm_all", n=6) in report["lines"]


def test_a_table_rests_on_the_manifest_alone_so_the_bundle_is_not_verified():
    report = _verdict(_bundle()["bytes"], [RECORD])
    assert report["verdict"] == "unconfirmed"
    assert phrase("bundle.confirm_some", k=5, n=6, paths="tables/layered_models.csv") in report["lines"]


def test_one_byte_changed_in_a_sheet_fails_the_check_and_names_the_file():
    data = _bundle()["bytes"]
    changed = _changed(data, {"raw/case_pumping.xlsx": SHEET.replace(b"13.25", b"13.75")})
    report = _verdict(changed, [RECORD])
    assert report["verdict"] == "changed"
    assert phrase("bundle.files_changed", paths="raw/case_pumping.xlsx") in report["lines"]


def test_a_sheet_rewritten_with_the_manifest_is_caught_by_the_document_that_lists_it():
    data = _bundle(_files(table=False))["bytes"]
    sheet = "raw/case_pumping.xlsx"
    changed = _changed(data, {sheet: SHEET + b"20,14.00\n"}, manifest=[sheet])
    report = _verdict(changed, [RECORD])
    assert report["verdict"] == "unconfirmed"
    entry = next(f for f in report["files"] if f["path"] == sheet)
    assert entry["state"] == "ok" and entry["confirmed"] == "none" and entry["listed_by"] == []
    # and the sheet the document does list is named as not carried
    assert any(line.startswith("Its documents list 1 evidence file the bundle does not carry: "
                               "case_pumping.xlsx") for line in report["lines"])


def test_a_document_swapped_with_the_manifest_matches_no_issue_record():
    data = _bundle()["bytes"]
    other = _document(text="The safe yield is 9.25 m3/h.")
    path = "reports/Completion.docx"
    parts = V.read_package(data)
    parts[path] = other
    facts = B.read_bundle_manifest(parts[B.BUNDLE_MANIFEST].decode())
    rec = V.document_record(other)
    facts["documents"][0].update(code=rec["code"], sha256=rec["sha256"])
    entry = next(f for f in facts["files"] if f["path"] == path)
    entry.update(sha256=hashlib.sha256(other).hexdigest(), bytes=len(other))
    parts[B.BUNDLE_MANIFEST] = B.bundle_manifest(facts).encode()
    swapped = B._stored_zip(sorted(parts.items()))
    assert _verdict(swapped)["verdict"] == "unconfirmed"
    report = _verdict(swapped, [RECORD])
    assert report["verdict"] == "not_issued"
    assert report["documents"][0]["verdict"] == "not_issued" and report["documents"][0]["agrees"]


def test_a_readiness_misstated_in_the_manifest_is_caught_by_the_document_itself():
    gate = {"requirements": [{"state": "unmet", "title": "Site position", "override_by": "",
                              "override_reason": ""}]}
    provisional = _document(kind="pumping", readiness=gate)
    data = _bundle([{"folder": "reports", "name": "P.docx", "data": provisional}],
                   records=[V.document_record(provisional)])["bytes"]
    parts = V.read_package(data)
    facts = B.read_bundle_manifest(parts[B.BUNDLE_MANIFEST].decode())
    facts["documents"][0].update(readiness="ready", items=[])
    facts["readiness"] = "ready"
    parts[B.BUNDLE_MANIFEST] = B.bundle_manifest(facts).encode()
    report = _verdict(B._stored_zip(sorted(parts.items())), [V.document_record(provisional)])
    assert report["verdict"] == "changed"
    assert not report["documents"][0]["agrees"]
    assert phrase("bundle.document_disagrees", path="reports/P.docx",
                  code=facts["documents"][0]["code"]) in report["lines"]


def test_a_file_removed_or_added_is_named():
    data = _bundle()["bytes"]
    removed = _verdict(_changed(data, drop=["tables/layered_models.csv"]))
    assert removed["verdict"] == "changed"
    assert phrase("bundle.files_missing", paths="tables/layered_models.csv") in removed["lines"]
    added = _verdict(_changed(data, {"raw/extra.xlsx": b"extra"}))
    assert added["verdict"] == "changed"
    assert phrase("bundle.files_added", paths="raw/extra.xlsx") in added["lines"]


def test_the_readme_rewritten_with_the_manifest_is_no_longer_the_toolkits_own():
    data = _bundle(_files(table=False))["bytes"]
    readme = V.read_package(data)["README.txt"] + b"Checked by nobody.\n"
    report = _verdict(_changed(data, {"README.txt": readme}, manifest=["README.txt"]), [RECORD])
    assert report["verdict"] == "unconfirmed"
    assert next(f for f in report["files"] if f["path"] == "README.txt")["confirmed"] == "none"


@pytest.mark.parametrize(("damage", "verdict"), [
    (lambda d: b"PK\x03\x04 not a zip", "unreadable"),
    (lambda d: _changed(d, drop=[B.BUNDLE_MANIFEST]), "no_manifest"),
    (lambda d: _changed(d, {B.BUNDLE_MANIFEST: b"\xff\xfe{"}), "damaged_manifest"),
    (lambda d: _changed(d, {B.BUNDLE_MANIFEST: V.read_package(d)[B.BUNDLE_MANIFEST] + b"\n"}),
     "damaged_manifest"),
    (lambda d: DOC, "no_manifest"),
])
def test_what_cannot_be_read_as_a_bundle_says_so(damage, verdict):
    report = _verdict(damage(_bundle()["bytes"]), [RECORD])
    assert report["verdict"] == verdict
    assert report["lines"][0] == phrase_table("bundle.verdicts")[verdict]
    assert report["files"] == [] and report["facts"] is None


# ------------------------------------------------------------ the browser's twin

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const input = JSON.parse(readFileSync(0, 'utf8'));
const bytes = (b64) => Uint8Array.from(Buffer.from(b64, 'base64'));
const files = input.files.map((f) => ({ folder: f.folder, name: f.name, data: bytes(f.b64), what: f.what }));
const doc = files.find((f) => f.folder === 'reports');
const built = C.buildEvidenceBundle(input.title, files.concat(C.documentFigures(doc.name, doc.data)),
  { madeOn: input.made_on, engine: input.engine, calibration: C.calibrationFacts(null), records: input.records });
const report = C.verifyEvidenceBundle(built.bytes, input.records);
process.stdout.write(JSON.stringify({ b64: Buffer.from(built.bytes).toString('base64'), verdict: report.verdict,
  lines: report.lines }));
"""


def test_the_browser_engine_writes_the_same_bundle_and_says_the_same_of_it(tmp_path):
    import base64

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path / "bundle.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    files = [f for f in _files() if f["folder"] != "figures"]
    payload = {"title": "Case borehole", "made_on": "2026-10-31", "engine": list(ENGINE), "records": [RECORD],
               "files": [{"folder": f["folder"], "name": f["name"], "what": f.get("what", ""),
                          "b64": base64.b64encode(f["data"]).decode()} for f in files]}
    done = subprocess.run([node, str(driver), str(JS)], input=json.dumps(payload), capture_output=True,
                          text=True, encoding="utf-8", check=True)
    js = json.loads(done.stdout)
    built = _bundle()
    assert base64.b64decode(js["b64"]) == built["bytes"]
    report = _verdict(built["bytes"], [RECORD])
    assert (js["verdict"], js["lines"]) == (report["verdict"], report["lines"])


# ------------------------------------------------------------ the command line

def test_groundwater_bundle_packs_a_project_folder_and_verify_checks_it(tmp_path, capsys):
    out = tmp_path / "dr_timbo.zip"
    data = REPO / "examples" / "data" / "dr_timbo"
    folder = tmp_path / "dr_timbo"
    shutil.copytree(REPO / "examples" / "projects" / "dr_timbo", folder)
    assert main(["bundle", str(out), "--folder", str(folder), "--raw", "drilling",
                 str(data / "dr_timbo_drilling_log.xlsx"), "--date", "2026-10-31"]) == 0
    printed = capsys.readouterr().out
    manifest = V.read_package(out.read_bytes())[B.BUNDLE_MANIFEST]
    facts = B.read_bundle_manifest(manifest.decode())
    assert facts["title"] == "Dr. Timbo's Residence" and facts["made_on"] == "2026-10-31"
    assert len(facts["documents"]) == 3
    assert f"sha256: {hashlib.sha256(manifest).hexdigest()}" in printed
    assert {"path": "raw/dr_timbo_drilling_log.xlsx", "what": "drilling log",
            "bytes": (data / "dr_timbo_drilling_log.xlsx").stat().st_size,
            "sha256": hashlib.sha256((data / "dr_timbo_drilling_log.xlsx").read_bytes()).hexdigest()} \
        in facts["files"]
    assert any(f["path"].startswith("figures/") for f in facts["files"])

    # not issued, so unchanged but not confirmed: exit 2
    assert main(["verify", str(out)]) == 2
    printed = capsys.readouterr().out
    assert printed.splitlines()[0] == phrase_table("bundle.verdicts")["unconfirmed"]
    assert "  raw/dr_timbo_drilling_log.xlsx: as made, rests on manifest.json alone" in printed

    # one byte changed: exit 1, and the file is named
    parts = V.read_package(out.read_bytes())
    sheet = "raw/dr_timbo_drilling_log.xlsx"
    parts[sheet] = bytes([parts[sheet][0] ^ 1]) + parts[sheet][1:]
    changed = tmp_path / "changed.zip"
    changed.write_bytes(B._stored_zip(sorted(parts.items())))
    assert main(["verify", str(changed)]) == 1
    assert phrase("bundle.files_changed", paths=sheet) in capsys.readouterr().out


def test_groundwater_bundle_takes_the_figures_out_of_the_documents_and_keeps_the_records(tmp_path, capsys):
    report = tmp_path / "Completion.docx"
    report.write_bytes(DOC)
    sheet = tmp_path / "case_pumping.xlsx"
    sheet.write_bytes(SHEET)
    project = tmp_path / "project.gwt.json"
    project.write_text(json.dumps({"issued": [RECORD]}), encoding="utf-8")
    out = tmp_path / "b.zip"
    assert main(["bundle", str(out), "--report", str(report), "--raw", "pumping", str(sheet),
                 "--project", str(project), "--title", "Case"]) == 0
    capsys.readouterr()
    # every file confirmed from outside it: exit 0
    assert main(["verify", str(out), "--project", str(project)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == phrase_table("bundle.verdicts")["verified"]


def test_groundwater_bundle_refuses_what_cannot_go_in(tmp_path, capsys):
    bad = tmp_path / "notes.docx"
    bad.write_bytes(b"not a document")
    assert main(["bundle", str(tmp_path / "b.zip"), "--report", str(bad)]) == 1
    assert "notes.docx cannot go into an evidence bundle" in capsys.readouterr().err
    assert main(["bundle", str(tmp_path / "b.zip"), "--raw", "sheet", str(bad)]) == 1
    assert "--raw sheet: the role is one of" in capsys.readouterr().err
    assert not (tmp_path / "b.zip").exists()


def test_struct_layout_of_an_entry_is_what_the_reader_checks():
    """Every local header agrees with the directory, as read_package insists."""
    data = _bundle()["bytes"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            signature, version, flags, method = struct.unpack_from("<IHHH", data, info.header_offset)
            assert (signature, version, method) == (0x04034B50, 20, 0)
            assert flags == (0 if info.filename.isascii() else 0x800)

"""One evidence bundle for each borehole (PLAN.md step 8.3): the "bundle"
entry of ``reference.json``.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json

from .common import clean
from .verification import BROWSER_DOCUMENT, PYTHON_DOCUMENT, _vr_rezip, _vr_zip


def _bd_b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _bd_edited(facts: dict, edits) -> dict:
    """``facts`` with each edit made: ``["set", path, value]``, ``["append",
    path, value]``, ``["insert", path, index, value]``, ``["reverse",
    path]`` or ``["drop", path, prefix]`` (the entries of a list whose path
    starts so), a path being keys and indexes from the top. parity.mjs makes
    the same edits."""
    out = copy.deepcopy(facts)
    for edit in edits:
        op, path = edit[0], edit[1]
        holder = out
        for key in path[:-1]:
            holder = holder[key]
        last = path[-1]
        if op == "set":
            holder[last] = copy.deepcopy(edit[2])
        elif op == "append":
            holder[last].append(copy.deepcopy(edit[2]))
        elif op == "insert":
            holder[last].insert(edit[2], copy.deepcopy(edit[3]))
        elif op == "reverse":
            holder[last].reverse()
        elif op == "drop":
            holder[last] = [x for x in holder[last] if not x["path"].startswith(edit[2])]
        else:  # pragma: no cover - a recipe typed wrong
            raise ValueError(op)
    return out


def _bd_manifest_text(text, facts: dict, recipe: dict):
    """A manifest.json written otherwise, as ``recipe`` says: literally
    (``text``, or ``nest`` brackets deep), with its facts edited and dumped
    (``edits``, then ``dump`` with an ``indent``, ``ascii`` escapes or a key
    ``order``), or its text changed (the first ``replace``, ``cut`` off the
    end, ``wrap``ped, ``crlf`` line ends). parity.mjs writes the same."""
    if "text" in recipe:
        return recipe["text"]
    if "nest" in recipe:
        return "[" * recipe["nest"] + "]" * recipe["nest"]
    if "edits" in recipe or "dump" in recipe:
        edited = _bd_edited(facts, recipe.get("edits", []))
        dump = recipe.get("dump", {})
        if "order" in dump:
            edited = {key: edited[key] for key in dump["order"]}
        text = json.dumps(edited, indent=dump.get("indent", 2), ensure_ascii=dump.get("ascii", False)) + "\n"
    if "replace" in recipe:
        old, new = recipe["replace"]
        assert old in text, old
        text = text.replace(old, new, 1)
    if "cut" in recipe:
        text = text[:-recipe["cut"]]
    if "wrap" in recipe:
        text = recipe["wrap"][0] + text + recipe["wrap"][1]
    if recipe.get("crlf"):
        text = text.replace("\n", "\r\n")
    return text


def _bd_apply(base: bytes, recipe: dict, docs: dict) -> bytes:
    """A bundle's parts changed as ``recipe`` says - parts replaced (by
    bytes, or by one of the documents), dropped or added, manifest.json
    rewritten (brought into line with the parts named, and edited, or its
    text changed) - and stored afresh, as parity.mjs changes them with
    C.storedZip; or the bytes it gives outright."""
    from groundwater import verification as V
    from groundwater.bundle import BUNDLE_MANIFEST, _stored_zip, read_bundle_manifest

    if recipe.get("raw") is not None:
        return base64.b64decode(recipe["raw"])
    parts = dict(V.read_package(base))
    text = parts[BUNDLE_MANIFEST].decode("utf-8")
    facts = read_bundle_manifest(text)
    for path in recipe.get("drop", []):
        parts.pop(path, None)
    for path, value in recipe.get("set", {}).items():
        parts[path] = docs[value["doc"]] if isinstance(value, dict) else base64.b64decode(value)
    manifest = recipe.get("manifest")
    if manifest is not None:
        if "in_line" in manifest:
            changed = copy.deepcopy(facts)
            for entry in changed["files"]:
                if entry["path"] in manifest["in_line"]:
                    entry["sha256"] = hashlib.sha256(parts[entry["path"]]).hexdigest()
                    entry["bytes"] = len(parts[entry["path"]])
            text = _bd_manifest_text(text, changed, {"edits": manifest["edits"]})
        else:
            text = _bd_manifest_text(text, facts, manifest)
        parts[BUNDLE_MANIFEST] = text.encode("utf-8")
    return _stored_zip(sorted(parts.items()))


def bundle_reference() -> dict:
    """One evidence bundle for each borehole (PLAN.md step 8.3): names as a
    bundle holds them, the readiness of documents taken together, the README
    and the folders' notes; bundles built from small documents sealed here
    and from the two committed ones, and refused; the figures taken out of a
    document; manifest.json read back, or refused; and a bundle changed in
    each way that matters, checked with and without issue records. The
    documents here are written field by field, so no zlib build moves a
    byte, and a changed bundle is given as what changed, which parity.mjs
    applies with C.storedZip."""
    from groundwater import bundle as B
    from groundwater import verification as V
    from groundwater.readiness import assess_readiness
    from groundwater.text import phrase_table

    out: dict = {}
    names = ["sheet.xlsx", " a/b\\c.xlsx ", "..", "", None, 7, 'CON:x?"<1>|*.csv', "tab\there.xlsx",
             "é sheet.xlsx", "😀.csv", "\ufeff x \u3000", ". .hidden. .", "a\x00b\x1f.xlsx", "a\ud800b.csv",
             "line\nbreak\r.csv", "del\x7f.csv", "dir/", "C:\\Users\\field\\Kpètèma BH-1.xlsx"]
    out["names"] = [[n, B.bundle_name(n)] for n in names]
    combos = [[], ["not_assessed"], ["ready"], ["ready", "not_assessed"], ["ready", "ready_with_overrides"],
              ["ready_with_overrides", "not_ready", "ready"], ["not_assessed", "not_ready"]]
    out["readiness"] = [[c, B.bundle_readiness(c)] for c in combos]
    out["notes"] = {folder: B.bundle_note(folder) for folder in B.FOLDERS}

    # small documents, sealed as the writers seal them and zipped field by
    # field: one with figures, a carrier image and evidence, a desk study
    # with no gate, a certifiable one
    kinds = phrase_table("verification.evidence_kinds")
    sheet = b"time_min,level_m\n0,12.50\n10,13.25\n"
    photo = b"\xff\xd8\xff jpeg bytes"
    calibration = V.calibration_facts(None)

    def gate(kind, overrides=None):
        g = assess_readiness({}, kind, overrides or {})
        return {"requirements": [{"state": r.state, "title": r.title, "override_by": r.override_by,
                                  "override_reason": r.override_reason} for r in g.requirements]}

    def document(kind, title, issued_on, readiness, evidence, text, media=None):
        content = {"[Content_Types].xml": b'<Types xmlns="t"><Default Extension="rels" ContentType="r"/></Types>',
                   "word/_rels/document.xml.rels": b'<Relationships xmlns="r"></Relationships>',
                   "word/document.xml": f"<w:document>{text}</w:document>".encode()}
        content.update(media or {})
        facts = V.manifest_facts(kind, title, issued_on, ("groundwater-python", "0.3.0"), calibration,
                                 readiness, evidence)
        sealed = V.seal_package(content, facts, lambda code: {
            "word/footer1.xml": f"Document {code} - page".encode(),
            "word/media/code.png": f"QR DOCUMENT {code}".encode()})
        return _vr_zip(sealed["entries"]), sealed["record"]

    evidence = [V.evidence_entry(kinds["pumping"], "case_pumping.xlsx", sheet),
                V.evidence_entry(kinds["photo"], "seal.jpg", photo)]
    media = {"word/media/image1.png": b"\x89PNG figure one", "word/media/charts/two.png": b"\x89PNG figure two"}
    doc_a, rec_a = document("completion", "Completion report - Case", "2026-10-29", gate("quality"),
                            evidence, "The safe yield is 1.25 m3/h.", media)
    doc_b, rec_b = document("desk_study", "Desk study - Case", "", None, [], "A desk study.")
    doc_c, rec_c = document("quality", "Water quality - Case", "2026-10-30", {"requirements": []},
                            evidence[:1], "Certifiable.")
    doc_o, rec_o = document("placard", "Plate - Case", "2026-10-29",
                            gate("placard", {"site_located": {"reason": "plate", "by": "A. K"}}), [], "Plate.")
    doc_a2, _ = document("completion", "Completion report - Case", "2026-10-29", gate("quality"),
                         evidence, "The safe yield is 9.25 m3/h.", media)
    unsealed = _vr_zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document/>"})
    changed_doc = _vr_rezip(doc_a, {"word/document.xml": V.read_package(doc_a)["word/document.xml"]
                                    .replace(b"1.25", b"1.35")})
    python_docx, browser_docx = PYTHON_DOCUMENT.read_bytes(), BROWSER_DOCUMENT.read_bytes()
    fixtures = {"python-docx": python_docx, "the browser's": browser_docx}
    docs = {"a": doc_a, "b": doc_b, "c": doc_c, "o": doc_o, "a2": doc_a2, "unsealed": unsealed,
            "changed": changed_doc}
    out["documents"] = {key: _bd_b64(data) for key, data in docs.items()}
    out["records"] = {"a": rec_a, "b": rec_b, "c": rec_c, "o": rec_o}

    def resolve(spec):
        """A file of a case: its bytes inline, a document above, or one of
        the committed documents parity.mjs reads out of the verification
        section."""
        if "doc" in spec:
            return docs[spec["doc"]]
        if "fixture" in spec:
            return fixtures[spec["fixture"]]
        return base64.b64decode(spec["b64"])

    out["figures"] = []
    for name, spec in (("Completion Report.docx", {"doc": "a"}), ("desk.DOCX", {"doc": "b"}),
                       ("Field kit.docx", {"fixture": "the browser's"}), ("a.docx", {"fixture": "python-docx"}),
                       (".docx", {"doc": "a"}), ("x", {"doc": "unsealed"}), ("y", {"doc": "changed"}),
                       ("z", {"b64": _bd_b64(b"not a package")})):
        figs = B.document_figures(name, resolve(spec))
        out["figures"].append({"name": name, "spec": spec, "figures": [
            {"folder": f["folder"], "name": f["name"], "sha256": hashlib.sha256(f["data"]).hexdigest(),
             "what": f["what"]} for f in figs]})

    def figure_files(name, spec):
        """The figures of a document, taken out of it by each engine's own
        document_figures when the case is built."""
        return [{"figures_of": dict(spec, name=name)}]

    raw ={"folder": "raw", "name": "case_pumping.xlsx", "b64": _bd_b64(sheet), "what": kinds["pumping"]}
    table = {"folder": "tables", "name": "layered_models.csv", "b64": _bd_b64(b"sounding,N\nA,1\n"), "what": ""}
    junk = {"code": "not a code"}
    builds = [
        {"name": "a borehole", "title": "Case borehole", "options": {
            "borehole": "SL-WAR-8FEEVKQ-E", "made_on": "2026-10-31", "engine": ["groundwater-python", "0.3.0"],
            "calibration": calibration, "records": [rec_b, rec_a, junk, rec_o]},
         "files": [raw, table, {"folder": "reports", "name": "Completion Report.docx", "doc": "a"},
                   {"folder": "reports", "name": "Desk study.docx", "doc": "b"}]
         + figure_files("Completion Report.docx", {"doc": "a"})},
        {"name": "names that collide", "title": ' Kpètèma & <Bo> "1"\t', "options": {
            "made_on": "", "engine": ["gwt-core", "0.3.0"], "calibration": None, "records": []},
         "files": [{"folder": "raw", "name": n, "b64": _bd_b64(d), "what": w}
                   for n, d, w in (("a.xlsx", b"1", ""), ("A.xlsx", b"2", "VES field sheet"),
                                   ("a.xlsx", b"1", "again"), ("a.xlsx", b"3", ""), ("a (2).xlsx", b"4", ""),
                                   (".xlsx", b"5", ""), ("noext", b"6", ""), ("NOEXT", b"7", ""),
                                   ("dir/sub/a.xlsx", b"8", ""), ("é.xlsx", b"9", ""), ("É.xlsx", b"10", ""))]
         + [{"folder": " signatures ", "name": "keys.json", "b64": _bd_b64(b"{}"), "what": "public keys"}]},
        {"name": "one certifiable document", "title": "", "options": {
            "made_on": "2026-11-01", "engine": ["gwt-core", "0.3.0"], "calibration": calibration,
            "records": [rec_c]},
         "files": [{"folder": "reports", "name": "Quality.docx", "doc": "c"},
                   {"folder": "reports", "name": "quality.docx", "doc": "c"}]},
        {"name": "on override", "title": "Override", "options": {
            "made_on": "", "engine": ["groundwater-python", "0.3.0"], "calibration": None, "records": None},
         "files": [{"folder": "reports", "name": "Plate.docx", "doc": "o"},
                   {"folder": "reports", "name": "Quality.docx", "doc": "c"}]},
        {"name": "raw only", "title": "Raw", "options": {
            "made_on": "", "engine": ["groundwater-python", "0.3.0"], "calibration": None, "records": None},
         "files": [raw]},
        {"name": "the committed documents", "title": "Fixtures", "options": {
            "made_on": "2026-10-29", "engine": ["gwt-core", "0.3.0"], "calibration": calibration,
            "records": [V.document_record(python_docx), V.document_record(browser_docx)]},
         "files": [{"folder": "reports", "name": "Report.docx", "fixture": "python-docx"},
                   {"folder": "reports", "name": "Field kit.docx", "fixture": "the browser's"}]
         + figure_files("Field kit.docx", {"fixture": "the browser's"})},
    ]

    def build(case):
        files = []
        for f in case["files"]:
            if "figures_of" in f:
                files += B.document_figures(f["figures_of"]["name"], resolve(f["figures_of"]))
            else:
                files.append(dict(folder=f["folder"], name=f["name"], data=resolve(f), what=f.get("what", "")))
        o = case["options"]
        return B.build_evidence_bundle(case["title"], files, borehole=o.get("borehole", ""),
                                       made_on=o["made_on"], engine=tuple(o["engine"]),
                                       calibration=o["calibration"], records=o["records"])

    built = []
    for case in builds:
        result = build(case)
        built.append(dict(case, result={"sha256": result["sha256"], "manifest": result["manifest"],
                                        "bytes_sha256": hashlib.sha256(result["bytes"]).hexdigest(),
                                        "size": len(result["bytes"])}))
    out["builds"] = built

    plain = {"name": "", "title": "Refused", "files": [raw], "options": {
        "made_on": "2026-10-31", "engine": ["groundwater-python", "0.3.0"], "calibration": None, "records": []}}
    refusals = [
        dict(plain, name="a folder that is not one", files=[dict(raw, folder="photos")]),
        dict(plain, name="a day that is not one", options=dict(plain["options"], made_on="2026-02-30")),
        dict(plain, name="a calibration with no hash", options=dict(plain["options"],
                                                                    calibration={"name": "x", "sha256": ""})),
        dict(plain, name="a document with no manifest", files=[{"folder": "reports", "name": "u.docx",
                                                               "doc": "unsealed"}]),
        dict(plain, name="a document changed since", files=[raw, {"folder": "reports", "name": "c.docx",
                                                                 "doc": "changed"}]),
        dict(plain, name="not a document", files=[{"folder": "reports", "name": "sheet.xlsx", "b64": raw["b64"]}]),
        dict(plain, name="nothing", files=[]),
    ]
    out["refusals"] = []
    for case in refusals:
        try:
            build(case)
        except ValueError as exc:
            out["refusals"].append(dict(case, error=str(exc)))
        else:
            raise AssertionError(f"build_evidence_bundle took {case['name']}")

    # manifest.json read back, and the ones not exactly as written, from a
    # small bundle so that the texts stay short
    small = build({"title": "Small Kpètèma 😀",
                   "files": [raw, {"folder": "reports", "name": "Plate.docx", "doc": "o"}],
                   "options": {"made_on": "2026-10-31", "engine": ["gwt-core", "0.3.0"],
                               "calibration": None, "records": [rec_o]}})
    out["read_base"] = small["manifest"]
    # the README, with a title and with none
    out["readmes"] = [B.bundle_readme(small["facts"]), B.bundle_readme(build(builds[2])["facts"])]
    zero = "0" * 64
    first = small["facts"]["files"][0]
    keys = list(small["facts"])
    edits = [
        {}, {"dump": {"indent": 1}}, {"dump": {"ascii": True}},
        {"dump": {"order": ["borehole", "title"] + [k for k in keys if k not in ("title", "borehole")]}},
        {"edits": [["set", ["extra"], 1]]},
        {"replace": ['"version": 1,', '"version": 1.0,']}, {"replace": ['"version": 1,', '"version": true,']},
        {"replace": [f'"bytes": {first["bytes"]}', '"bytes": NaN']},
        {"replace": [f'"bytes": {first["bytes"]}', '"bytes": 2e1']},
        {"replace": [f'"bytes": {first["bytes"]}', '"bytes": -0']},
        {"replace": ['"title": "Small Kp', '"title": "Sm\\u0061ll Kp']},
        {"edits": [["set", ["title"], " Small "]]},
        {"edits": [["reverse", ["files"]]]},
        {"edits": [["set", ["files", 1, "path"], "FIGURES/README.txt"]]},
        {"edits": [["append", ["files"], {"path": "raw/../x", "what": "", "bytes": 1, "sha256": zero}]]},
        {"edits": [["append", ["files"], {"path": "raw/a/b.xlsx", "what": "", "bytes": 1, "sha256": zero}]]},
        {"edits": [["insert", ["files"], 0, {"path": "manifest.json", "what": "", "bytes": 1, "sha256": zero}]]},
        {"edits": [["drop", ["files"], "signatures/"]]}, {"edits": [["drop", ["files"], "README.txt"]]},
        {"edits": [["set", ["readiness"], "ready"]]},
        {"edits": [["set", ["documents", 0, "items", 0, "state"], "unmet"]]},
        {"edits": [["set", ["documents", 0, "items", 0, "by"], ""]]},
        {"edits": [["set", ["documents", 0, "path"], "reports/elsewhere.docx"]]},
        {"edits": [["append", ["documents"], small["facts"]["documents"][0]]]},
        {"edits": [["append", ["issued"], junk]]},
        {"edits": [["append", ["issued"], dict(rec_a, title=" padded ")]]},
        {"edits": [["set", ["calibration"], {"name": "a set", "sha256": ""}]]},
        {"edits": [["set", ["calibration"], {"name": "a set", "sha256": zero}]]},
        {"edits": [["set", ["made_on"], "2026-13-01"]]},
        {"edits": [["set", ["files", 0, "sha256"], first["sha256"].upper()]]},
        {"edits": [["set", ["files", 0, "bytes"], V.MAX_PART_BYTES + 1]]},
        {"edits": [["set", ["documents", 0, "code"], "0A1B-2C3D-E"]]},
        {"edits": [["set", ["engine"], ["gwt-core", "0.3.0"]]]},
        {"cut": 1}, {"wrap": ["", "\n"]}, {"crlf": True}, {"wrap": ["\ufeff", ""]},
        {"text": ""}, {"text": "[]"}, {"text": "{}"}, {"nest": 5000}, {"text": 7}, {"text": None},
    ]
    out["read"] = [[edit, B.read_bundle_manifest(_bd_manifest_text(small["manifest"], small["facts"], edit))]
                   for edit in edits]

    # a bundle changed in each way that matters, checked with and without
    # issue records: the first one built above, which parity.mjs builds too
    base = build(builds[0])
    data, facts = base["bytes"], base["facts"]
    parts = V.read_package(data)

    sheet2 = sheet.replace(b"13.25", b"13.75")
    readme2 = parts["README.txt"] + b"Checked by nobody.\n"
    figure_path = next(p for p in parts if p.startswith("figures/"))
    figure2 = parts[figure_path] + b"x"
    table2 = b"sounding,N\nA,2\n"
    rec_a2 = V.document_record(doc_a2)
    completion = next(i for i, d in enumerate(facts["documents"])
                      if d["path"] == "reports/Completion Report.docx")

    def in_line(paths, edits=()):
        """manifest.json brought into line with the parts named, which
        the recipe's set changes, and then edited."""
        return {"in_line": list(paths), "edits": list(edits)}

    recipes = [
        {"name": "as made"},
        {"name": "a field sheet changed", "set": {"raw/case_pumping.xlsx": _bd_b64(sheet2)}},
        {"name": "a field sheet changed, manifest.json in line", "set": {"raw/case_pumping.xlsx": _bd_b64(sheet2)},
         "manifest": in_line(["raw/case_pumping.xlsx"])},
        {"name": "a table changed, manifest.json in line", "set": {"tables/layered_models.csv": _bd_b64(table2)},
         "manifest": in_line(["tables/layered_models.csv"])},
        {"name": "a figure changed, manifest.json in line", "set": {figure_path: _bd_b64(figure2)},
         "manifest": in_line([figure_path])},
        {"name": "the README changed, manifest.json in line", "set": {"README.txt": _bd_b64(readme2)},
         "manifest": in_line(["README.txt"])},
        {"name": "a document removed", "drop": ["reports/Desk study.docx"]},
        {"name": "a file added", "set": {"raw/extra.xlsx": _bd_b64(b"extra")}},
        {"name": "a document swapped, manifest.json in line", "set_doc": {"reports/Completion Report.docx": "a2"},
         "manifest": in_line(["reports/Completion Report.docx"], [
             ["set", ["documents", completion, "code"], rec_a2["code"]],
             ["set", ["documents", completion, "sha256"], rec_a2["sha256"]]])},
        {"name": "a document changed inside, manifest.json in line",
         "set_doc": {"reports/Completion Report.docx": "changed"},
         "manifest": in_line(["reports/Completion Report.docx"])},
        {"name": "a document's readiness misstated", "manifest": in_line([], [
            ["set", ["documents", completion, "readiness"], "ready"],
            ["set", ["documents", completion, "items"], []],
            ["set", ["readiness"], "ready"]])},
        {"name": "manifest.json removed", "drop": ["manifest.json"]},
        {"name": "manifest.json edited by hand", "manifest": {"replace": ['"title": ', '"title":  ']}},
        {"name": "manifest.json not utf-8", "set": {"manifest.json": _bd_b64(b"\xff\xfe{")}},
        {"name": "not a zip", "raw": _bd_b64(b"PK\x03\x04 not a zip")},
        {"name": "a document, not a bundle", "doc": "a"},
    ]
    for recipe in recipes:
        for path, key in recipe.pop("set_doc", {}).items():
            recipe.setdefault("set", {})[path] = {"doc": key}
    record_sets = {"none": None, "empty": [], "a": [rec_a], "a, b and o": [rec_o, rec_b, rec_a, junk]}
    every = ("as made", "a field sheet changed, manifest.json in line", "a document swapped, manifest.json in line")
    out["checks"] = []
    for recipe in recipes:
        changed = docs[recipe["doc"]] if "doc" in recipe else _bd_apply(data, recipe, docs)
        reports = {}
        for key, records in record_sets.items():
            if key == "a, b and o" or recipe["name"] in every:
                report = B.verify_evidence_bundle(changed, records)
                reports[key] = {"records": records, "facts": report["facts"] is not None,
                                "report": {k: v for k, v in report.items() if k != "facts"}}
        out["checks"].append({"recipe": recipe, "sha256": hashlib.sha256(changed).hexdigest(),
                              "reports": reports})
    # the bundle of the committed documents, checked against their records
    fixture = build(builds[-1])["bytes"]
    out["fixture_check"] = {key: {k: v for k, v in B.verify_evidence_bundle(fixture, records).items()
                                  if k != "facts"}
                            for key, records in (("none", None),
                                                 ("theirs", builds[-1]["options"]["records"]))}
    return clean(out)

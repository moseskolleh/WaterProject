"""Documents that can be verified (PLAN.md step 8.1): the "verification"
entry of ``reference.json``. The two committed documents and the zip helpers
are also what the evidence bundles in ``bundle.py`` are built from.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import zlib

from groundwater.models import SiteMetadata

from .common import clean, OUT


#: The document a browser wrote, committed (tests/webapp/fieldkit.mjs
#: --write-fixtures): what the Python engine says of it is what the browser
#: has to say.
BROWSER_DOCUMENT = OUT.parent / "fixtures" / "fieldkit_browser.docx"
#: And one python-docx wrote, committed likewise
#: (fixtures/make_sealed_docx.py): python-docx writes other parts in another
#: version and zlib builds other bytes, so a fresh one is another document.
PYTHON_DOCUMENT = OUT.parent / "fixtures" / "sealed_python.docx"


def _fixed_deflate(data: bytes) -> bytes:
    """``data`` as one final DEFLATE block of fixed Huffman codes, literals
    only (RFC 1951, 3.2.6): bytes the format fixes, where a compressor's are
    its build's own."""
    bits = [1, 1, 0]  # BFINAL, then BTYPE 01, least significant bit first

    def code(value: int, length: int) -> None:
        bits.extend((value >> (length - 1 - k)) & 1 for k in range(length))

    for byte in data:
        code(0x30 + byte, 8) if byte < 144 else code(0x190 + byte - 144, 9)
    code(0, 7)  # the end of the block
    out = bytearray((len(bits) + 7) // 8)
    for k, bit in enumerate(bits):
        out[k // 8] |= bit << (k % 8)
    assert zlib.decompress(bytes(out), -15) == data
    return bytes(out)


def _vr_zip(entries: dict, deflate: bool = False) -> bytes:
    """A package, entries sorted, each stored or (``deflate``) in a block of
    fixed codes: written here field by field, so the bytes are the same on
    every machine."""
    return _vr_package([
        _vr_entry(name.encode("utf-8"), body, flags=0 if name.isascii() else 0x800,
                  method=8 if deflate else 0, payload=_fixed_deflate(body) if deflate else None)
        for name, body in sorted(entries.items())])


def _vr_rezip(data: bytes, changed: dict) -> bytes:
    """``data``'s entries with their compressed bytes as they are, and those
    named in ``changed`` stored afresh: a copy with one part edited, no
    larger than it needs to be and with no byte a zlib build chose here."""
    import io
    import zipfile

    entries = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = info.filename.encode("utf-8")
            if info.filename in changed:
                entries.append(_vr_entry(name, changed[info.filename]))
                continue
            name_len, extra_len = struct.unpack_from("<HH", data, info.header_offset + 26)
            begin = info.header_offset + 30 + name_len + extra_len
            entries.append(_vr_entry(name, z.read(info), method=info.compress_type,
                                     payload=data[begin:begin + info.compress_size]))
    return _vr_package(entries)


def _vr_entry(name: bytes, body: bytes, *, method=0, flags=0, crc=None, usize=None, payload=None,
              local_name=None):
    payload = body if payload is None else payload
    crc = (zlib.crc32(body) & 0xFFFFFFFF) if crc is None else crc
    usize = len(body) if usize is None else usize
    lname = name if local_name is None else local_name
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, method, 0, 0x21, crc, len(payload), usize,
                        len(lname), 0) + lname + payload
    return local, (flags, method, crc, len(payload), usize, name)


def _vr_package(entries, *, comment=b"", junk=b"", count=None) -> bytes:
    """A package written field by field: the ones no writer makes, and the
    rest with bytes no zlib build chooses."""
    out, central = b"", b""
    for local, (flags, method, crc, csize, usize, name) in entries:
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, flags, method, 0, 0x21, crc, csize,
                               usize, len(name), 0, 0, 0, 0, 0, len(out)) + name
        out += local
    n = len(entries) if count is None else count
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, n, n, len(central), len(out), len(comment)) + comment
    return out + central + end + junk


def verification_reference() -> dict:
    """Documents that can be verified (PLAN.md step 8.1): codes from digests
    and read back from what is typed; the facts a manifest records, the
    manifest written and read, the package sealed; packages read rule by
    rule, the four answers given of each with and without issue records;
    issue records kept, read out of either app's project file and looked up
    by code; and the documents an asset record keeps. The cases carry their
    own inputs, so parity.mjs gives the browser exactly these."""
    import random as _random

    from groundwater import verification as V
    from groundwater.readiness import assess_readiness
    from groundwater import qr
    from groundwater.registry import asset_from_dict, asset_from_project
    from groundwater.text import phrase

    rng = _random.Random("verification")
    out: dict = {}
    digests = ["0" * 64, "f" * 64, "0123456789abcdef" * 4] + [
        hashlib.sha256(f"document {k}".encode()).hexdigest() for k in range(40)]
    out["codes"] = [[d, V.document_code(d)] for d in digests]
    typed = [None, "", 7, "0A1B-2C3D", "document 0a1b-2c3d-x", "OA1B 2C3D", "0a1b_2c3d", "0A1B-2C3D-EE",
             "0A1B-2C3Ü-E", "0A1B\t2C3D", "﻿0A1B2C3D", "DOCUMENT", "0A1B-2C3D-İ"]
    for _, code in out["codes"][:12]:
        body = code.replace("-", "")
        typed += [code, code.lower(), f"DOCUMENT {code}", body, body[:4] + " " + body[4:],
                  body.replace("1", "L").replace("0", "O"), body[:-1] + rng.choice("0123456789ABCDEFGHIJ")]
    out["parse"] = [[t, V.parse_document_code(t)] for t in typed]
    # the cover's symbol, as the two writers draw it: the same bytes, since
    # its hash is one of the parts the manifest lists (held by that hash)
    out["qr_png"] = [[text, hashlib.sha256(qr.to_png(qr.encode(text, ecc="H"), scale=8,
                                                     stored=True)).hexdigest()]
                     for text in [phrase("verification.qr", code=c) for _, c in out["codes"][:3]] + ["x" * 60]]

    # the readiness a manifest records, from the shape each engine's gate has
    gates = []
    for kind, overrides in (("pumping", {}), ("completion", {"site_located": {"reason": "plate", "by": "A. K"}}),
                            ("placard", {"site_located": "a reason, no name"}), ("costing", {})):
        gate = assess_readiness({}, kind, overrides)
        gates.append({"requirements": [{"state": r.state, "title": r.title, "override_by": r.override_by,
                                        "override_reason": r.override_reason} for r in gate.requirements]})
    gates += [None, {"requirements": []},
              {"requirements": [{"state": "overridden", "title": " T\x01 ", "override_by": 5,
                                 "override_reason": "r\ud800"}, {"state": "met", "title": "M"}]}]
    out["readiness"] = [[g, V.readiness_facts(g)] for g in gates]

    calibration = V.calibration_facts(None)
    out["calibration"] = calibration
    files = [{"what": "pumping test sheet", "name": "kuntolo.xlsx", "sha256": "1" * 64},
             {"what": "photograph", "name": "seal & cap <1>.jpg", "sha256": "2" * 64},
             {"what": "photograph", "name": "seal & cap <1>.jpg", "sha256": "2" * 64},
             {"what": "", "name": "Kpètèma \"3\"\n\ttab.xlsx", "sha256": "0" * 64},
             {"what": "VES field sheet", "name": "😀 sheet.xlsx", "sha256": "3" * 64},
             {"what": "VES field sheet", "name": "０ sheet.xlsx", "sha256": "4" * 64}]
    arg_cases = [
        {"kind": "pumping", "title": "Pumping Test Report - Kuntoloh", "issued_on": "2024-05-01",
         "engine": ["groundwater-python", "0.3.0"], "calibration": calibration, "readiness": gates[0],
         "evidence": files[:1]},
        {"kind": "completion", "title": " Kpètèma & <Bo> \"BH-1\"\r\n", "issued_on": "",
         "engine": ["gwt-core", "0.3.0"], "calibration": None, "readiness": gates[1], "evidence": files},
        {"kind": "placard", "title": "Borehole SL-WAR-8FEEVKQ-E", "issued_on": " 2026-10-29 ",
         "engine": ["", ""], "calibration": calibration, "readiness": gates[2], "evidence": []},
        {"kind": 7, "title": None, "issued_on": "", "engine": [None, 3], "calibration": None,
         "readiness": {"state": "not_ready", "items": [{"state": "unmet", "title": "Site position",
                                                       "by": "", "reason": ""}]}, "evidence": []},
    ]
    refusals = [dict(arg_cases[0], issued_on="2024-02-30"), dict(arg_cases[0], issued_on="20240501"),
                dict(arg_cases[0], evidence=[{"what": "x", "name": "a", "sha256": "ABC"}]),
                dict(arg_cases[0], evidence=[{"what": "x", "name": "a", "sha256": "A" * 64}]),
                dict(arg_cases[0], calibration={"name": "a set", "sha256": ""}),
                dict(arg_cases[0], calibration={"name": "", "sha256": "1" * 64})]
    parts = [["[Content_Types].xml", "a" * 64], ["word/document.xml", "b" * 64],
             ["word/media/é.png", "c" * 64]]
    carriers = [["word/footer1.xml", "d" * 64]]
    manifests = []
    for args in arg_cases:
        facts = V.manifest_facts(args["kind"], args["title"], args["issued_on"], tuple(args["engine"]),
                                 args["calibration"], args["readiness"], args["evidence"])
        digest = V.code_digest(facts, parts)
        code = V.document_code(digest)
        manifests.append({"args": args, "facts": facts, "digest": digest, "code": code,
                          "xml": V.manifest_xml(facts, code, parts, carriers)})
    errors = []
    for args in refusals:
        try:
            V.manifest_facts(args["kind"], args["title"], args["issued_on"], tuple(args["engine"]),
                             args["calibration"], args["readiness"], args["evidence"])
        except ValueError as exc:
            errors.append({"args": args, "error": str(exc)})
        else:
            raise AssertionError(f"manifest_facts took {args}")
    out["manifests"], out["refusals"], out["parts"], out["carriers"] = manifests, errors, parts, carriers

    # manifests read back, and the ones that are not exactly as written
    good = manifests[1]["xml"]
    texts = [m["xml"] for m in manifests] + [
        good.replace('format="1"', 'format="2"'), good.replace("<engine name=", "<engine  name="),
        good.replace("</evidence>", "</evidence>\n", 1), good.replace("&amp;", "&#38;", 1),
        good.replace("&amp;", "&apos;", 1), good.replace('state="ready_with_overrides"', 'state="ready"', 1),
        "﻿" + good, good.rstrip("\n"), good + "\n", good.replace("\n", "\r\n"),
        good.replace(f'code="{manifests[1]["code"]}"', 'code="0A1B-2C3D-E"'),
        good.replace(f'code="{manifests[1]["code"]}"', 'code="0A1B-2C3D-5"'),
        good.replace(f'code="{manifests[1]["code"]}"', 'code=""'),
        good.replace('<carriers>\n<part name="word/footer1.xml"', '<carriers>\n<part name="word/document.xml"'),
        good.replace('name="word/media/é.png"', 'name="a.png"'),
        good.replace("d" * 64, "D" * 64), "", "<manifest/>", 7]
    out["read"] = [[t, V.read_manifest(t)] for t in texts]

    # a package sealed, as the writers seal one
    content = {"[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="t"><Default Extension="rels" '
                                      'ContentType="r"/></Types>',
               "word/_rels/document.xml.rels": '<Relationships xmlns="r"></Relationships>',
               "word/document.xml": "<w:document>The safe yield is 1.25 m3/h.</w:document>"}
    seal_facts = manifests[0]["facts"]
    sealed = V.seal_package({k: v.encode() for k, v in content.items()}, seal_facts,
                            lambda code: {"word/footer1.xml": f"Document {code} - page".encode()})
    out["seal"] = {"entries": content, "facts": seal_facts, "code": sealed["code"], "sha256": sealed["sha256"],
                   "manifest": sealed["manifest"], "record": sealed["record"],
                   "parts": {name: data.decode("utf-8") for name, data in sealed["entries"].items()}}
    with_xml = dict(content, **{"[Content_Types].xml": '<Types xmlns="t"><Default Extension="xml" '
                                                       'ContentType="application/xml"/></Types>'})
    out["seal_xml"] = V.seal_package({k: v.encode() for k, v in with_xml.items()}, seal_facts)["manifest"]

    # packages, and what each engine says of each
    record = sealed["record"]
    other = V.seal_package({k: v.encode() for k, v in content.items()}, manifests[2]["facts"],
                           lambda code: {"word/footer1.xml": code.encode()})["record"]
    entries = sealed["entries"]

    def changed(name, old, new, manifest=False):
        out_entries = dict(entries)
        out_entries[name] = out_entries[name].replace(old, new)
        if manifest:
            held = V.read_manifest(entries[V.MANIFEST_PART].decode())
            listed = [(n, V._sha256(out_entries[n]) if n == name else d) for n, d in held["parts"]]
            carried = [(n, V._sha256(out_entries[n]) if n == name else d) for n, d in held["carriers"]]
            out_entries[V.MANIFEST_PART] = V.manifest_xml(held["facts"], held["code"], listed,
                                                          carried).encode()
        return out_entries

    deflated = _fixed_deflate(b"<a/>")
    written = PYTHON_DOCUMENT.read_bytes()
    written_entries = V.read_package(written)
    written_changed = {"word/document.xml": written_entries["word/document.xml"].replace(b"1.25", b"1.35")}
    browser = BROWSER_DOCUMENT.read_bytes()
    browser_record = V.document_record(browser)
    packages = {
        "sealed": _vr_zip(entries), "deflated": _vr_zip(entries, deflate=True),
        "one digit": _vr_zip(changed("word/document.xml", b"1.25", b"1.35")),
        "part removed": _vr_zip({n: d for n, d in entries.items() if n != "word/footer1.xml"}),
        "part added": _vr_zip(dict(entries, **{"word/media/image9.png": b"png", "z/extra.bin": b"x"})),
        "manifest brought into line": _vr_zip(changed("word/document.xml", b"1.25", b"9.25", manifest=True)),
        "carrier changed": _vr_zip(changed("word/footer1.xml", b"page", b"PAGE", manifest=True)),
        "no manifest": _vr_zip({n: d for n, d in entries.items() if n != V.MANIFEST_PART}),
        "manifest not utf-8": _vr_zip(dict(entries, **{V.MANIFEST_PART: b"\xff\xfe<"})),
        "manifest with a bom": _vr_zip(dict(entries, **{V.MANIFEST_PART: b"\xef\xbb\xbf" + entries[V.MANIFEST_PART]})),
        "not a package": b"PK\x03\x04 not a package",
        "nothing": b"",
        "python-docx": written,
        "python-docx, one digit": _vr_rezip(written, written_changed),
        "the browser's": browser,
        "crafted": _vr_package([_vr_entry(b"a.xml", b"<a/>"), _vr_entry(b"dir/", b"")]),
        "crafted, deflated": _vr_package([_vr_entry(b"a.xml", b"<a/>", method=8, payload=deflated)]),
        "crafted, a comment": _vr_package([_vr_entry(b"a.xml", b"<a/>")], comment=b"a note"),
        "crafted, utf-8 name": _vr_package([_vr_entry("é.xml".encode(), b"<a/>", flags=0x800)]),
        "crafted, a descriptor flag": _vr_package([_vr_entry(b"a.xml", b"<a/>", flags=8)]),
        "after the end": _vr_package([_vr_entry(b"a.xml", b"<a/>")], junk=b"x"),
        "named twice": _vr_package([_vr_entry(b"a.xml", b"<a/>"), _vr_entry(b"a.xml", b"<b/>")]),
        "a bad crc": _vr_package([_vr_entry(b"a.xml", b"<a/>", crc=1)]),
        "a size that lies": _vr_package([_vr_entry(b"a.xml", b"<a/>", usize=5)]),
        "encrypted": _vr_package([_vr_entry(b"a.xml", b"<a/>", flags=1)]),
        "another method": _vr_package([_vr_entry(b"a.xml", b"<a/>", method=12)]),
        "a name not ascii": _vr_package([_vr_entry("é.xml".encode(), b"<a/>")]),
        "a name not utf-8": _vr_package([_vr_entry(b"\xff.xml", b"<a/>", flags=0x800)]),
        "a local name that differs": _vr_package([_vr_entry(b"a.xml", b"<a/>", local_name=b"b.xml")]),
        "bytes after the stream": _vr_package([_vr_entry(b"a.xml", b"<a/>", method=8, payload=deflated + b"\0")]),
        "a stream cut short": _vr_package([_vr_entry(b"a.xml", b"<a/>", method=8, payload=deflated[:-1])]),
        "a stream that runs on": _vr_package([_vr_entry(b"a.xml", b"<a/", method=8, payload=deflated)]),
        "zip64": _vr_package([_vr_entry(b"a.xml", b"<a/>")], count=0xFFFF),
    }
    record_sets = {"none": None, "empty": [], "this": [record], "another": [other],
                   "this and another": [other, record, {"junk": 1}]}
    cases = []
    for name, data in packages.items():
        parts_read = V.read_package(data)
        case = {"name": name, "b64": base64.b64encode(data).decode("ascii"),
                "parts": None if parts_read is None else {n: V._sha256(b) for n, b in parts_read.items()},
                "record": V.document_record(data), "reports": {}}
        for key, records in record_sets.items():
            if key == "none" or name in ("sealed", "one digit", "carrier changed", "python-docx"):
                case["reports"][key] = {"records": records, "report": V.verify_document(data, records)}
        if name == "the browser's":
            case["reports"]["its own"] = {"records": [browser_record],
                                          "report": V.verify_document(data, [browser_record])}
        cases.append(case)
    out["packages"] = cases

    # issue records kept, read from project files, looked up
    desk = dict(other, kind="desk_study")
    raw_records = [record, other, record, desk, {"code": record["code"]}, "a", None,
                   dict(record, readiness="maybe"), dict(record, sha256="AB"), dict(record, issued_on="today"),
                   dict(record, code=record["code"].lower()), dict(record, title=" padded\x00 ", sha256="9" * 64),
                   dict(other, issued_on="", sha256="8" * 64), dict(record, kind=7)]
    out["records"] = {"raw": raw_records, "clean": V.clean_issue_records(raw_records),
                      "borehole": V.borehole_records(raw_records), "not_a_list": V.clean_issue_records({"a": 1})}
    payloads = [{"issued": [record], "asset": {"documents": [other, desk]}},
                {"issued": [desk], "state": {"asset": {"documents": [record]}, "issued": [other]}},
                {"asset": [record], "state": [record], "issued": "x"}, [record], None, {}]
    out["payloads"] = [[p, V.issue_records_of(p)] for p in payloads]
    lookups = [record["code"], record["code"].lower().replace("-", " "), f"DOCUMENT {other['code']}",
               "0A1B-2C3D", "not a code", desk["code"]]
    out["lookups"] = [{"text": t, "records": raw_records, "result": V.lookup_code(t, raw_records)}
                      for t in lookups] + [{"text": record["code"], "records": [],
                                            "result": V.lookup_code(record["code"], [])}]

    # the documents an asset record keeps, and those a draft carries
    site = {"district": "Western Area Rural", "easting": 694000.0, "northing": 938150.0, "utm_zone": 28,
            "community": "Case"}
    asset_id = asset_from_project({"site": SiteMetadata(**site)}).asset_id
    stored = [{"asset_id": asset_id, "documents": raw_records}, {"asset_id": asset_id, "documents": "x"},
              {"asset_id": asset_id}]
    out["assets"] = {
        "stored": [[s, asset_from_dict(s).documents] for s in stored],
        "draft": {"site": site, "issued": raw_records,
                  "documents": asset_from_project({"site": SiteMetadata(**site), "issued": raw_records}).documents},
    }
    return clean(out)

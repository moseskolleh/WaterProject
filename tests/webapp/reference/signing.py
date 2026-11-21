"""Signed statements (PLAN.md step 8.2): the "signing" entry of
``reference.json``.

The signature check is arithmetic written out by hand in each engine, and
the readers of a statement and of a members' file refuse whatever is not
exactly what the toolkit writes. Both are held here on: the standard's own
test signatures and every way a key or a signature can be malformed; texts a
strict reader must and must not read; statements signed by Web Crypto in a
browser and committed (``fixtures/signing_webcrypto.json``); and members'
files that place a signer, or must not be read at all.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "signing_webcrypto.json"

# RFC 6979, appendix A.2.5: ECDSA over P-256 with SHA-256, the key and the
# signatures of the messages "sample" and "test".
RFC_KEY = ("0460fed4ba255a9d31c961eb74c6356d68c049b8923b61fa6ce669622e60f29fb6"
           "7903fe1008b8bc99a41ae9e95628bc64f2f1b20c2d7e9f5177a3c294d4462299")
RFC_SAMPLE = ("efd48b2aacb6a8fd1140dd9cd45e81d69d2c877b56aaf991c34d0ea84eaf3716"
              "f7cb1c942d657c41d436c7a1b6e29f65f3e900dbb9aff4064dc4ab2f843acda8")
RFC_TEST = ("f1abb023518351cd71d881567b1ea663ed3efcf6c5132b354f28d3b0b7d38367"
            "019f4113742a2b14bd25926b49c649155f267e60d3814b4c0cc84250e46f0083")
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF


def _other_s(signature: str) -> str:
    """The same signature with n - s for s: also a signature of the message,
    as the standard has it. Both engines take it, and say so the same."""
    return signature[:64] + f"{_N - int(signature[64:], 16):064x}"


#: [key, message, signature]: the standard's two, then each thing that makes
#: a key not a key, a signature not one, or either not this message's.
VERIFY_CASES = [
    [RFC_KEY, "sample", RFC_SAMPLE],
    [RFC_KEY, "test", RFC_TEST],
    [RFC_KEY, "sample", _other_s(RFC_SAMPLE)],
    [RFC_KEY, "sample", RFC_TEST],
    [RFC_KEY, "Sample", RFC_SAMPLE],
    [RFC_KEY, "", RFC_SAMPLE],
    [RFC_KEY, "sample ɛɔ", RFC_SAMPLE],
    # one digit of the signature, one of the key
    [RFC_KEY, "sample", RFC_SAMPLE[:-1] + "9"],
    [RFC_KEY[:-1] + "8", "sample", RFC_SAMPLE],
    # r and s out of range: nought, the order of the group, past it
    [RFC_KEY, "sample", "0" * 64 + RFC_SAMPLE[64:]],
    [RFC_KEY, "sample", RFC_SAMPLE[:64] + "0" * 64],
    [RFC_KEY, "sample", f"{_N:064x}" + RFC_SAMPLE[64:]],
    [RFC_KEY, "sample", RFC_SAMPLE[:64] + f"{_N:064x}"],
    [RFC_KEY, "sample", "f" * 128],
    # a point that is not on the curve, one past the field, nought, a
    # compressed key, a key in capitals, text that is not hexadecimal
    ["04" + RFC_KEY[2:66] + f"{int(RFC_KEY[66:], 16) ^ 1:064x}", "sample", RFC_SAMPLE],
    ["04" + f"{_P:064x}" + RFC_KEY[66:], "sample", RFC_SAMPLE],
    ["04" + "0" * 128, "sample", RFC_SAMPLE],
    ["02" + RFC_KEY[2:66], "sample", RFC_SAMPLE],
    ["03" + RFC_KEY[2:], "sample", RFC_SAMPLE],
    [RFC_KEY.upper(), "sample", RFC_SAMPLE],
    [RFC_KEY, "sample", RFC_SAMPLE.upper()],
    [RFC_KEY[:-2], "sample", RFC_SAMPLE],
    [RFC_KEY, "sample", RFC_SAMPLE + "00"],
    ["04" + "g" * 128, "sample", RFC_SAMPLE],
    ["", "sample", ""],
    [None, "sample", None],
    [12, "sample", 34],
]

#: Things that are, and are not, a statement: what statement_text writes or
#: refuses to write.
STATEMENT_VALUES = [
    {"says": "sign-off", "stage": "design", "value": "0.39 m³/h", "count": 3,
     "figures": {"yield": "0.39 m³/h", "depth": "62 m"}, "sheets": ["ab", "cd"]},
    {"says": "x"},
    {"says": "x", "empty": "", "none": [], "nothing": {}, "nought": 0, "most": 999999999},
    {"says": "x", "text": "a \"quoted\" word, a back\\slash, a tab\there\nand a line"},
    {"says": "x", "text": "ɛɔ —   \U0001f4a7  inside"},
    # --- not statements
    {"says": ""},
    {"stage": "design", "says": "x"},
    {"says": "x", "Stage": "design"},
    {"says": "x", "1st": "design"},
    {"says": "x", "_x": "design"},
    {"says": "x", "a-b": "design"},
    {"says": "x", "a" * 41: "design"},
    {"says": "x", "n": 1000000000},
    {"says": "x", "n": -1},
    {"says": "x", "n": 1.5},
    {"says": "x", "n": True},
    {"says": "x", "n": None},
    {"says": "x", "text": " leading"},
    {"says": "x", "text": "trailing "},
    {"says": "x", "text": "a\u0001b"},
    {"says": "x", "list": ["a", 1]},
    {"says": "x", "list": [["a"]]},
    {"says": "x", "list": [" a"]},
    {"says": "x", "named": {"a": 1}},
    {"says": "x", "named": {"A": "b"}},
    {"says": "x", "named": {"a": {"b": "c"}}},
    {"says": 1},
    {},
    [],
    "says",
    None,
    7,
]

_GOOD = '{\n  "says": "x",\n  "n": 3\n}\n'
#: Texts a strict reader is handed: the first is read, the rest are not, each
#: for one reason.
STATEMENT_TEXTS = [
    _GOOD,
    '{\n  "says": "x",\n  "list": [],\n  "named": {}\n}\n',
    '{\n  "says": "x",\n  "list": [\n    "a"\n  ],\n  "named": {\n    "a": "b"\n  }\n}\n',
    # the same things, not written as the toolkit writes them
    _GOOD.rstrip("\n"),
    _GOOD + "\n",
    " " + _GOOD,
    "﻿" + _GOOD,
    _GOOD.replace("\n", "\r\n"),
    '{"says": "x", "n": 3}\n',
    '{\n    "says": "x",\n    "n": 3\n}\n',
    '{\n  "says": "x",\n  "n": 3,\n  "n": 3\n}\n',
    '{\n  "says": "x",\n  "says": "x",\n  "n": 3\n}\n',
    # numbers that are not whole numbers in range, however written
    _GOOD.replace("3", "3.0"),
    _GOOD.replace("3", "3e0"),
    _GOOD.replace("3", "-0"),
    _GOOD.replace("3", "03"),
    _GOOD.replace("3", "1000000000"),
    _GOOD.replace("3", "9007199254740993"),
    _GOOD.replace("3", "1" + "0" * 400),
    _GOOD.replace("3", "NaN"),
    _GOOD.replace("3", "Infinity"),
    _GOOD.replace("3", "true"),
    _GOOD.replace("3", "null"),
    # text that is not clean, or cannot be text at all
    _GOOD.replace('"x"', '"x "'),
    _GOOD.replace('"x"', '"\\u0001"'),
    _GOOD.replace('"x"', '"\\ud800"'),
    _GOOD.replace('"x"', '"\\ud83d\\udca7"'),
    _GOOD.replace('"x"', '"\\u0078"'),
    _GOOD.replace('"x"', "'x'"),
    # names
    _GOOD.replace('"n"', '"N"'),
    _GOOD.replace('"n"', '"__proto__"'),
    _GOOD.replace('"n"', '"constructor"'),
    _GOOD.replace('"n"', '"1"'),
    _GOOD.replace('"n"', '""'),
    # not an object, or nothing at all
    '[\n  "says"\n]\n',
    '"says"\n',
    "3\n",
    "null\n",
    "",
    "{",
    "[" * 5000,
    '{\n  "says": "x",\n  "n": ' + "[" * 3000 + "]" * 3000 + "\n}\n",
]

#: How long a padded statement is, in characters of padding: under the
#: longest text read, and over it. Built in each engine, not kept here.
PADDED = [1000, 199900, 200000, 400000]

_KEY_B = "04" + "6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296" + \
    "4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5"


def _members(**change) -> dict:
    members = {
        "format": "groundwater-toolkit members' keys", "version": 1,
        "organisation": "Example Water Programme", "issued_on": "2026-11-21",
        "members": [
            {"name": "A. Example", "role": "hydrogeologist", "key": RFC_KEY,
             "valid_from": "2026-01-01", "valid_to": "2026-12-31", "withdrawn": ""},
            {"name": "B. Sample", "role": "", "key": _KEY_B,
             "valid_from": "", "valid_to": "", "withdrawn": ""},
        ],
    }
    members.update(change)
    return members


def _member(index: int, **change) -> dict:
    members = _members()
    members["members"][index] = {**members["members"][index], **change}
    return members


def _without(index: int, field: str) -> dict:
    members = _members()
    del members["members"][index][field]
    return members


def _reordered() -> dict:
    members = _members()
    first = members["members"][0]
    members["members"][0] = {"role": first["role"], "name": first["name"],
                             **{k: v for k, v in first.items() if k not in ("name", "role")}}
    return members


#: Members' files as values: the first few are read, the rest refused.
MEMBERS_VALUES = [
    _members(),
    _members(members=[]),
    _member(1, withdrawn="2026-12-01"),
    _member(0, valid_from="", valid_to=""),
    _members(organisation="Example — Water (Zɛdo)"),
    # --- refused: nobody's list, no day, a day that is not one
    _members(organisation=""),
    _members(organisation=" Example"),
    _members(issued_on=""),
    _members(issued_on="21/11/2026"),
    _members(issued_on="2026-02-30"),
    _members(issued_on=" 2026-11-21"),
    _members(issued_on="2026-11-21T00:00"),
    _member(0, valid_from="2026-13-01"),
    _member(0, valid_to="tomorrow"),
    _member(1, withdrawn="yes"),
    _member(1, withdrawn=True),
    _member(1, withdrawn=None),
    # a member with no name, a key that is not one, one key twice
    _member(0, name=""),
    _member(0, name=" A. Example"),
    _member(0, role=7),
    _member(0, key=RFC_KEY.upper()),
    _member(0, key=RFC_KEY[:-2]),
    _member(1, key=RFC_KEY),
    # the wrong shape
    _without(0, "role"),
    _member(0, note="extra"),
    _reordered(),
    _members(version=2),
    _members(version=True),
    _members(format="members"),
    _members(members={"a": 1}),
    _members(members=[None]),
    {k: v for k, v in _members().items() if k != "issued_on"},
    {**_members(), "note": "extra"},
    [],
    None,
]

#: Where a key stands, by the day a statement gives: [members value, key,
#: day]. The first member's key is valid for 2026 only.
STANDING_CASES = [
    [_members(), RFC_KEY, "2026-06-01"],
    [_members(), RFC_KEY, "2026-01-01"],
    [_members(), RFC_KEY, "2026-12-31"],
    [_members(), RFC_KEY, "2025-12-31"],
    [_members(), RFC_KEY, "2027-01-01"],
    [_members(), RFC_KEY, ""],
    [_members(), RFC_KEY, "June"],
    [_members(), RFC_KEY, None],
    [_member(0, valid_to=""), RFC_KEY, "2031-01-01"],
    [_member(0, valid_from=""), RFC_KEY, "1999-01-01"],
    [_members(), _KEY_B, ""],
    [_members(), _KEY_B, "2026-06-01"],
    # withdrawn, whatever day the statement gives
    [_member(1, withdrawn="2026-12-01"), _KEY_B, "2026-06-01"],
    [_member(0, withdrawn="2026-12-01"), RFC_KEY, "2026-06-01"],
    # a key nobody is listed with; a file that is not one
    [_members(members=[]), RFC_KEY, "2026-06-01"],
    [_members(organisation=""), RFC_KEY, "2026-06-01"],
    [None, RFC_KEY, "2026-06-01"],
]


def _told(checked: dict) -> dict:
    """What a check said, as both engines say it."""
    return {"verdict": checked["verdict"], "statement": checked["statement"],
            "key": checked["key"], "code": checked["code"], "standing": checked["standing"],
            "member": checked["member"], "file_code": checked["file_code"],
            "lines": checked["lines"]}


def signing_reference() -> dict:
    from groundwater import signing as S

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    members_file = fixture["members"]
    signed = fixture["signed"]

    def written(value):
        try:
            return S.statement_text(value)
        except ValueError:
            return None

    def members_written(value):
        try:
            return S.members_text(value)
        except ValueError:
            return None

    def padded(n: int):
        text = S.statement_text({"says": "x", "pad": "a" * n})
        return S.read_statement(text) is not None

    # the committed statements, as they are and spoiled each way a file can be
    held = json.loads(signed[0])
    spoiled = {
        "one_letter": signed[0].replace("EX-01", "EX-02"),
        "misnamed": fixture["misnamed"],
        "signature_digit": signed[0].replace(
            held["signature"], held["signature"][:-1] + ("0" if held["signature"][-1] != "0"
                                                         else "1")),
        "another_key": signed[0].replace(held["key"], json.loads(signed[1])["key"]),
        "version_2": signed[0].replace('"version": 1', '"version": 2'),
        "format": signed[0].replace("signed statement", "statement"),
        "reordered": S._written({"version": 1, "format": S.SIGNED_FORMAT,
                                 "statement": held["statement"], "key": held["key"],
                                 "signature": held["signature"]}),
        "extra": S._written({**held, "note": "extra"}),
        "capitals": signed[0].replace(held["signature"], held["signature"].upper()),
        "no_newline": signed[0].rstrip("\n"),
        "statement_only": S.statement_text(held["statement"]),
        "nothing": "",
        "not_text": None,
    }
    members_spoiled = members_file.replace("Example Water Programme", "Another Programme")
    checks = [[text, None] for text in signed]
    checks += [[text, members_file] for text in signed]
    # a members' file that is another organisation's list, and one that is not a file
    checks += [[signed[0], members_spoiled], [signed[0], "not a members' file"],
               [signed[0], ""], [signed[0], 7]]
    checks += [[text, members_file] for text in spoiled.values()]

    return {
        "verify": {"cases": VERIFY_CASES,
                   "results": [S.verify_p256(key, message.encode("utf-8"), signature)
                               for key, message, signature in VERIFY_CASES]},
        "keys": {"cases": [RFC_KEY, _KEY_B, RFC_KEY.upper(), RFC_KEY[:-2], "", None],
                 "ids": [S.key_id(key) for key in
                         [RFC_KEY, _KEY_B, RFC_KEY.upper(), RFC_KEY[:-2], "", None]],
                 "codes": [S.key_code(value) for value in
                           [S.key_id(RFC_KEY), S.key_id(_KEY_B), S.key_id(RFC_KEY).upper(),
                            "abc", "", None]],
                 "code_cases": [S.key_id(RFC_KEY), S.key_id(_KEY_B), S.key_id(RFC_KEY).upper(),
                                "abc", "", None]},
        "statements": {"values": STATEMENT_VALUES,
                       "written": [written(value) for value in STATEMENT_VALUES],
                       "texts": STATEMENT_TEXTS,
                       "read": [S.read_statement(text) for text in STATEMENT_TEXTS],
                       "padded": PADDED, "padded_read": [padded(n) for n in PADDED]},
        "members": {"values": MEMBERS_VALUES,
                    "written": [members_written(value) for value in MEMBERS_VALUES],
                    "codes": [S.members_code(members_written(value)) for value in MEMBERS_VALUES],
                    "standing_cases": STANDING_CASES,
                    "standing": [S.signer_standing(members, S.key_id(key), day)
                                 for members, key, day in STANDING_CASES]},
        "checks": {"cases": checks,
                   "names": [*["alone"] * len(signed), *["with members"] * len(signed),
                             "another list", "not a file", "an empty file", "a number",
                             *spoiled],
                   "results": [_told(S.check_signed(text, members)) for text, members in checks],
                   "read": [S.read_signed(text) for text, _ in checks]},
    }

"""Signed statements (PLAN.md step 8.2): the half that needs no browser.

A sign-off or an override that carries a signature is only worth more than a
typed name if the check behind it is right, and if nothing that is not a
signed statement can pass for one. So what is held here is the signature
check itself, against the standard's own test signatures, against a library
that makes real keys (cryptography, test-only, as segno is for the QR
encoder), and against statements a browser signed with Web Crypto
(tests/webapp/fixtures/signing_webcrypto.json, written by
tests/webapp/signing.mjs); and the readers, which read nothing the toolkit
did not write. The browser's port is held to the same by the parity suite
(tests/webapp/reference/signing.py).

Every name here is made up.
"""

import json
from pathlib import Path

import pytest

from groundwater import signing as S

REPO = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (REPO / "tests" / "webapp" / "fixtures" / "signing_webcrypto.json").read_text(encoding="utf-8"))

# RFC 6979, appendix A.2.5: P-256 with SHA-256
KEY = ("0460fed4ba255a9d31c961eb74c6356d68c049b8923b61fa6ce669622e60f29fb6"
       "7903fe1008b8bc99a41ae9e95628bc64f2f1b20c2d7e9f5177a3c294d4462299")
SAMPLE = ("efd48b2aacb6a8fd1140dd9cd45e81d69d2c877b56aaf991c34d0ea84eaf3716"
          "f7cb1c942d657c41d436c7a1b6e29f65f3e900dbb9aff4064dc4ab2f843acda8")
TEST = ("f1abb023518351cd71d881567b1ea663ed3efcf6c5132b354f28d3b0b7d38367"
        "019f4113742a2b14bd25926b49c649155f267e60d3814b4c0cc84250e46f0083")
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


# ------------------------------------------------------------------ the check


def test_the_standards_own_signatures_are_accepted_and_nothing_near_them():
    assert S.verify_p256(KEY, b"sample", SAMPLE)
    assert S.verify_p256(KEY, b"test", TEST)
    assert not S.verify_p256(KEY, b"sample", TEST)
    assert not S.verify_p256(KEY, b"Sample", SAMPLE)
    assert not S.verify_p256(KEY, b"", SAMPLE)
    # any one digit of the signature, or of the key
    for at in (0, 31, 63, 64, 100, 127):
        other = SAMPLE[:at] + ("0" if SAMPLE[at] != "0" else "1") + SAMPLE[at + 1:]
        assert not S.verify_p256(KEY, b"sample", other), at
    for at in (2, 40, 65, 66, 129):
        other = KEY[:at] + ("0" if KEY[at] != "0" else "1") + KEY[at + 1:]
        assert not S.verify_p256(other, b"sample", SAMPLE), at


def test_what_is_not_a_key_or_not_a_signature_is_refused_not_raised():
    zero, order = "0" * 64, f"{N:064x}"
    for signature in (zero + SAMPLE[64:], SAMPLE[:64] + zero, order + SAMPLE[64:],
                      SAMPLE[:64] + order, "f" * 128, SAMPLE.upper(), SAMPLE[:-2], SAMPLE + "00",
                      "", None, 12, b"bytes"):
        assert S.verify_p256(KEY, b"sample", signature) is False, signature
    # a point that is not on the curve is not a key, whatever signature it is
    # given: without the check one can be chosen to pass
    off_curve = "04" + KEY[2:66] + f"{int(KEY[66:], 16) ^ 1:064x}"
    for key in (off_curve, "04" + "0" * 128, "04" + "f" * 128, "02" + KEY[2:66],
                "03" + KEY[2:], KEY.upper(), KEY[:-2], "", None, 7):
        assert S.verify_p256(key, b"sample", SAMPLE) is False, key
    assert S.verify_p256(KEY, "sample", SAMPLE) is False     # text is not bytes


def test_a_key_is_known_by_the_hash_of_its_point_and_read_out_in_five_groups():
    import hashlib

    identifier = S.key_id(KEY)
    assert identifier == hashlib.sha256(bytes.fromhex(KEY)).hexdigest()
    assert S.key_code(identifier) == "-".join(
        identifier[i:i + 4].upper() for i in range(0, 20, 4))
    assert len(S.key_code(identifier)) == 24
    for wrong in (KEY.upper(), KEY[:-2], "", None, 7):
        assert S.key_id(wrong) == ""
    for wrong in (identifier.upper(), identifier[:-1], "", None):
        assert S.key_code(wrong) == ""


def _oracle():
    crypto = pytest.importorskip("cryptography", reason="the signature oracle is not installed")
    assert crypto
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    def make():
        private = ec.generate_private_key(ec.SECP256R1())
        numbers = private.public_key().public_numbers()
        return private, f"04{numbers.x:064x}{numbers.y:064x}"

    def sign(private, message: bytes) -> str:
        r, s = decode_dss_signature(private.sign(message, ec.ECDSA(hashes.SHA256())))
        return f"{r:064x}{s:064x}"

    return make, sign


def test_signatures_made_by_an_independent_library_are_accepted_and_no_others():
    import os

    make, sign = _oracle()
    for length in (0, 1, 31, 32, 33, 55, 56, 64, 119, 120, 500, 4096):
        private, key = make()
        _, stranger = make()
        message = os.urandom(length)
        signature = sign(private, message)
        assert S.verify_p256(key, message, signature), length
        assert not S.verify_p256(key, message + b"\x00", signature)
        assert not S.verify_p256(stranger, message, signature)
        # the other s of the same signature is also one, as the standard has
        # it: the check takes it and says so the same in both engines
        other = signature[:64] + f"{N - int(signature[64:], 16):064x}"
        assert S.verify_p256(key, message, other)


# ------------------------------------------------------------ a statement's text


STATEMENT = {"says": "sign-off", "stage": "design", "value": "0.39 m³/h", "count": 3,
             "figures": {"yield": "0.39 m³/h", "depth": "62 m"}, "sheets": ["ab", "cd"]}


def test_a_statement_is_written_one_way_and_read_back_only_as_written():
    text = S.statement_text(STATEMENT)
    assert text == json.dumps(STATEMENT, indent=2, ensure_ascii=False) + "\n"
    assert text.startswith('{\n  "says": "sign-off",\n') and "m³/h" in text
    assert S.read_statement(text) == STATEMENT
    # the order of its parts is part of what is signed
    assert list(S.read_statement(text)) == list(STATEMENT)
    for other in (text.rstrip("\n"), text + "\n", " " + text, text.replace("\n", "\r\n"),
                  json.dumps(STATEMENT) + "\n", json.dumps(STATEMENT, indent=4) + "\n",
                  json.dumps(STATEMENT, indent=2) + "\n", "﻿" + text):
        assert S.read_statement(other) is None, other[:40]


@pytest.mark.parametrize("value", [
    {"says": ""}, {"stage": "design", "says": "x"}, {"says": "x", "Stage": "y"},
    {"says": "x", "1st": "y"}, {"says": "x", "_x": "y"}, {"says": "x", "a" * 41: "y"},
    {"says": "x", "n": 1000000000}, {"says": "x", "n": -1}, {"says": "x", "n": 1.5},
    {"says": "x", "n": True}, {"says": "x", "n": None}, {"says": "x", "t": " leading"},
    {"says": "x", "t": "trailing "}, {"says": "x", "t": "a\x01b"}, {"says": "x", "t": "\ud800"},
    {"says": "x", "l": ["a", 1]}, {"says": "x", "l": [["a"]]}, {"says": "x", "d": {"a": 1}},
    {"says": "x", "d": {"A": "b"}}, {"says": "x", "d": {"a": {"b": "c"}}}, {"says": 1},
    {}, [], "says", None, 7,
])
def test_what_is_not_a_statement_is_not_written(value):
    assert S.clean_statement(value) is None
    with pytest.raises(ValueError):
        S.statement_text(value)


@pytest.mark.parametrize("number", ["3.0", "3e0", "-0", "03", "1000000000", "9007199254740993",
                                    "1" + "0" * 400, "NaN", "Infinity", "true", "null"])
def test_a_number_that_is_not_a_whole_one_in_range_is_not_read(number):
    # decimal numbers are where the two engines' writers differ, and past
    # 2**53 the browser's are no longer exact: neither is in a statement
    assert S.read_statement('{\n  "says": "x",\n  "n": 3\n}\n') == {"says": "x", "n": 3}
    assert S.read_statement('{\n  "says": "x",\n  "n": ' + number + "\n}\n") is None


def test_a_text_far_past_what_the_toolkit_writes_is_not_read():
    def padded(n):
        return S.statement_text({"says": "x", "pad": "a" * n})

    assert S.read_statement(padded(199_900)) is not None
    assert S.read_statement(padded(S.MAX_BYTES)) is None
    # counted in bytes, so the same text is the same length in both engines
    assert S.read_statement(padded(0).replace('""', '"' + "ɛ" * 100_001 + '"')) is None
    assert S.read_statement("[" * 100_000) is None
    assert S.read_statement(None) is None and S.read_statement(b"{}") is None


# -------------------------------------------------------------- signed statements


def test_statements_signed_by_web_crypto_in_a_browser_hold():
    assert len(FIXTURE["signed"]) == 3
    for text, expect in zip(FIXTURE["signed"], FIXTURE["expect"], strict=True):
        alone = S.check_signed(text)
        assert alone["verdict"] == "holds" and alone["standing"] == "not_checked"
        assert alone["statement"]["key"] == alone["key"] and len(alone["code"]) == 24
        placed = S.check_signed(text, FIXTURE["members"])
        assert (placed["verdict"], placed["standing"]) == (expect["verdict"], expect["standing"])
        assert placed["member"]["name"] == expect["name"] == placed["statement"]["name"]
        assert placed["file_code"] == S.members_code(FIXTURE["members"])


def test_a_statement_changed_after_it_was_signed_does_not_hold():
    for text in FIXTURE["signed"]:
        held = json.loads(text)
        for changed in (text.replace("EX-01", "EX-02"),
                        text.replace("P-7Q2M", "P-7Q2N"),
                        text.replace("Example Village", "Another Village")):
            assert changed != text
            said = S.check_signed(changed, FIXTURE["members"])
            assert said["verdict"] == "does_not_hold", changed[:60]
            # and the signer of something that does not hold is not looked up
            assert said["standing"] == "not_checked" and said["member"] is None
        signature = held["signature"]
        flipped = signature[:-1] + ("0" if signature[-1] != "0" else "1")
        assert S.check_signed(text.replace(signature, flipped))["verdict"] == "does_not_hold"


def test_a_statement_is_bound_to_the_key_it_names():
    first, second = (json.loads(text) for text in FIXTURE["signed"][:2])
    # another person's key put beside a good statement and its signature
    swapped = S.signed_text(first["statement"], second["key"], first["signature"])
    assert S.check_signed(swapped)["verdict"] == "does_not_hold"
    # a statement naming somebody else's key, under a signature that is good
    # for its text: the key it names did not sign it
    assert S.check_signed(FIXTURE["misnamed"])["verdict"] == "does_not_hold"
    assert S.read_signed(FIXTURE["misnamed"]) is not None
    # a statement that names no key at all, well signed, is not relied on
    make, sign = _oracle()
    private, key = make()
    nameless = {"says": "sign-off", "stage": "design"}
    signed = S.signed_text(nameless, key, sign(private, S.statement_text(nameless).encode()))
    assert S.check_signed(signed)["verdict"] == "does_not_hold"
    named = {**nameless, "key": S.key_id(key)}
    signed = S.signed_text(named, key, sign(private, S.statement_text(named).encode()))
    assert S.check_signed(signed)["verdict"] == "holds"


def test_only_the_file_the_toolkit_writes_is_read_as_a_signed_statement():
    text = FIXTURE["signed"][0]
    held = json.loads(text)
    assert S.read_signed(text) == {"statement": held["statement"], "key": held["key"],
                                   "signature": held["signature"]}
    assert S.signed_text(held["statement"], held["key"], held["signature"]) == text
    reordered = {"version": 1, "format": held["format"], "statement": held["statement"],
                 "key": held["key"], "signature": held["signature"]}
    for other in (text.replace('"version": 1', '"version": 2'),
                  text.replace('"version": 1', '"version": true'),
                  text.replace("signed statement", "statement"),
                  json.dumps(reordered, indent=2, ensure_ascii=False) + "\n",
                  json.dumps({**held, "note": "extra"}, indent=2, ensure_ascii=False) + "\n",
                  text.replace(held["signature"], held["signature"].upper()),
                  text.replace(held["key"], held["key"][:-2]),
                  text.rstrip("\n"), S.statement_text(held["statement"]), "", None, 7):
        assert S.read_signed(other) is None
        said = S.check_signed(other, FIXTURE["members"])
        assert said["verdict"] == "not_a_statement" and said["statement"] is None
        not_one = "This is not a signed statement the toolkit wrote. Nothing in it is taken as said."
        assert said["lines"] == [not_one]
    for statement, key, signature in ((None, held["key"], held["signature"]),
                                      (held["statement"], "04", held["signature"]),
                                      (held["statement"], held["key"], "ab")):
        with pytest.raises(ValueError):
            S.signed_text(statement, key, signature)


# ------------------------------------------------------------ the members' file


def members(**change) -> dict:
    out = {"format": S.MEMBERS_FORMAT, "version": 1, "organisation": "Example Water Programme",
           "issued_on": "2026-11-21",
           "members": [{"name": "A. Example", "role": "hydrogeologist", "key": KEY,
                        "valid_from": "2026-01-01", "valid_to": "2026-12-31", "withdrawn": ""}]}
    out.update(change)
    return out


def member(**change) -> dict:
    out = members()
    out["members"][0].update(change)
    return out


def test_a_members_file_is_read_only_as_written_and_names_its_organisation():
    text = S.members_text(members())
    assert S.read_members(text) == members()
    code = S.members_code(text)
    assert len(code) == 24 and code == code.upper()
    # another organisation's name on the same list is another file
    other = text.replace("Example Water Programme", "Another Programme")
    assert S.read_members(other) is not None and S.members_code(other) != code
    assert S.read_members(text.rstrip("\n")) is None and S.members_code(text.rstrip("\n")) == ""
    assert S.read_members(json.dumps(members()) + "\n") is None


@pytest.mark.parametrize("value", [
    members(organisation=""), members(organisation=" Example"), members(issued_on=""),
    members(issued_on="21/11/2026"), members(issued_on="2026-02-30"),
    members(issued_on=" 2026-11-21"), members(version=2), members(version=True),
    members(format="members"), members(members={"a": 1}), members(members=[None]),
    member(valid_from="2026-13-01"), member(valid_to="tomorrow"), member(withdrawn="yes"),
    member(withdrawn=True), member(withdrawn=None), member(name=""), member(name=" A"),
    member(role=7), member(key=KEY.upper()), member(key=KEY[:-2]), member(note="extra"),
    {**members(), "note": "extra"}, [], None,
])
def test_a_members_file_with_a_fault_is_refused_whole(value):
    # a date that is not one is not read as "no date", and a withdrawal that
    # cannot be read is not read as "not withdrawn": the file is not read
    with pytest.raises(ValueError):
        S.members_text(value)
    assert S.signer_standing(value, S.key_id(KEY), "2026-06-01")["standing"] == "not_checked"


def test_one_key_is_one_member():
    twice = members()
    twice["members"].append({**twice["members"][0], "name": "B. Sample"})
    with pytest.raises(ValueError):
        S.members_text(twice)


def test_where_a_signer_stands():
    identifier = S.key_id(KEY)

    def standing(value, day):
        return S.signer_standing(value, identifier, day)["standing"]

    assert [standing(members(), day) for day in
            ("2026-01-01", "2026-06-01", "2026-12-31")] == ["listed"] * 3
    # dated outside the days the key is valid for, or not dated at all
    assert [standing(members(), day) for day in
            ("2025-12-31", "2027-01-01", "", "June", None, 20260601)] == ["out_of_dates"] * 6
    # no days, no question of dates
    undated = member(valid_from="", valid_to="")
    assert standing(undated, "") == "listed" and standing(undated, "1999-01-01") == "listed"
    assert standing(member(valid_to=""), "2031-01-01") == "listed"
    assert standing(member(valid_from=""), "1999-01-01") == "listed"
    # withdrawn, whatever day the statement gives: the day is the signer's clock
    for day in ("2026-06-01", "2020-01-01", ""):
        assert standing(member(withdrawn="2026-12-01"), day) == "withdrawn"
    assert S.signer_standing(members(), "0" * 64, "2026-06-01") == {
        "standing": "not_listed", "member": None}
    assert S.signer_standing(None, identifier, "2026-06-01")["standing"] == "not_checked"
    assert S.signer_standing(members(), identifier, "2026-06-01")["member"]["name"] == "A. Example"


def test_the_words_a_checker_is_given_say_what_was_and_was_not_shown():
    listed, withdrawn, dated = (S.check_signed(text, FIXTURE["members"])
                                for text in FIXTURE["signed"])
    file_code = S.members_code(FIXTURE["members"])
    claim = ("The time in it, 2026-11-21 09:30, is the clock of the signer's own device. It is a "
             "claim, not a proof.")
    whose = ("The key is listed in the members' file you gave (Example Water Programme, file code "
             f"{file_code}) as A. Example, hydrogeologist.")
    assert listed["lines"] == [
        f"The signature holds. This statement was signed with the key {listed['code']}.",
        claim, whose,
    ]
    assert "has withdrawn it" in withdrawn["lines"][-1] and "(no role given)" in withdrawn[
        "lines"][-1]
    assert "whatever date it gives" in withdrawn["lines"][-1]
    assert "dated outside the days the key is valid for" in dated["lines"][-1]
    alone = S.check_signed(FIXTURE["signed"][0])
    assert alone["lines"][-1] == "Whose key that is was not checked: no members' file was given."
    # a file that is not a members' file is said to be one, not passed over
    for not_a_file in ("not a members' file", "", 7):
        said = S.check_signed(FIXTURE["signed"][0], not_a_file)
        assert said["verdict"] == "holds" and said["standing"] == "not_checked"
        assert said["lines"][-1].startswith("The members' file given is not one the toolkit wrote")
    # a key the list does not have
    empty = S.members_text(members(members=[]))
    said = S.check_signed(FIXTURE["signed"][0], empty)
    assert said["standing"] == "not_listed" and said["lines"][-1].startswith(
        "The key is not in the members' file you gave (Example Water Programme, file code ")


# -------------------------------------------------------------- the command line


def test_the_command_line_checks_a_signed_statement(tmp_path, capsys):
    from groundwater.cli import main

    files = []
    for n, text in enumerate(FIXTURE["signed"]):
        files.append(tmp_path / f"statement{n}.json")
        files[-1].write_text(text, encoding="utf-8")
    listed, withdrawn, dated = (str(path) for path in files)
    members_file = tmp_path / "members.json"
    members_file.write_text(FIXTURE["members"], encoding="utf-8")
    changed = tmp_path / "changed.json"
    changed.write_text(FIXTURE["signed"][0].replace("EX-01", "EX-02"), encoding="utf-8")

    # it holds and the signer is listed
    assert main(["signature", listed, "--members", str(members_file)]) == 0
    said = capsys.readouterr().out
    assert "The signature holds." in said and "as A. Example, hydrogeologist" in said
    # and what was signed is shown as it stands in the text
    assert "value: US$ 9,500" in said and "  yield: 0.39 m³/h" in said
    # it holds, and nobody has said whose key it is
    assert main(["signature", listed]) == 2
    assert "no members' file was given" in capsys.readouterr().out
    assert main(["signature", dated, "--members", str(members_file)]) == 2
    capsys.readouterr()
    # a withdrawn key, a changed statement, a file that is not one
    assert main(["signature", withdrawn, "--members", str(members_file)]) == 1
    assert "has withdrawn it" in capsys.readouterr().out
    assert main(["signature", str(changed), "--members", str(members_file)]) == 1
    said = capsys.readouterr().out
    assert "does not hold" in said and "value:" not in said
    assert main(["signature", str(members_file)]) == 1
    assert "not a signed statement" in capsys.readouterr().out
    assert main(["signature", str(tmp_path / "nowhere.json")]) == 1
    assert main(["signature", listed, "--members", str(tmp_path / "nowhere.json")]) == 1

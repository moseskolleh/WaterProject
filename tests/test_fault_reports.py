"""Reports on a borehole from its plate and by SMS (PLAN.md step 7.1).

What the people who pump a borehole say about it becomes a registry record
only through the registry's own check of the identifier, so a mistyped one
is refused, and a report by SMS that the check reads only with a note is
held for a person rather than merged. Nothing is dated from the clock: a
message with no day is refused unless the person importing it gives one.
Accepted reports merge by the registry's rule, so a report imported twice is
one record. The browser's engine is held to this one on seeded inputs.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from groundwater import fault_reports as F
from groundwater import registry
from groundwater.config import Config, ServiceConfig
from groundwater.models import SiteMetadata
from groundwater.registry import Asset, AssetEvent, asset_from_dict, asset_state, mint_asset_id
from groundwater.text import phrase

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"

TIMBO = SiteMetadata(community="Dr. Timbo's", district="Western Area Rural",
                     easting=694912.0, northing=938150.0, utm_zone=28)
ID = mint_asset_id(TIMBO)
OTHER = mint_asset_id(SiteMetadata(district="Bo", easting=790500.0, northing=875300.0,
                                   utm_zone=28))


def _mistyped(asset_id: str) -> str:
    """``asset_id`` with its check character mistyped: one that is neither
    its own nor, where the registry still reads one (the character minted
    before the check followed ISO 7064 exactly), its older one."""
    body, given = asset_id.rsplit("-", 1)
    older = getattr(registry, "legacy_check_character", None)
    taken = {given, older(body) if older else given}
    return f"{body}-" + next(c for c in "ZYXW" if c not in taken)


MISTYPED = _mistyped(ID)
DAY = date(2026, 6, 1)


def _asset(*events) -> Asset:
    return Asset(asset_id=ID, community="Dr. Timbo's", district="Western Area Rural",
                 easting=694912.0, northing=938150.0, utm_zone=28, events=list(events))


# ---------------------------------------------------------------------------
# An SMS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("word", "choice", "kind"), [
    ("WORKING", "working", "reported_working"),
    ("broken", "broken", "failure"),
    ("Slow", "slow", "reported_slow"),
    ("TASTE", "taste", "quality_complaint"),
    ("colour", "taste", "quality_complaint"),
    ("COLOR", "taste", "quality_complaint"),
    ("bad", "taste", "quality_complaint"),
])
def test_each_word_is_read_in_any_case_as_its_choice(word, choice, kind):
    r = F.parse_sms(f"BH {ID} {word}", received="2026-05-01T08:14:00Z", sender="+23276123456")
    assert r["status"] == "accepted" and r["reason"] == ""
    assert (r["choice"], r["kind"], r["when"]) == (choice, kind, "2026-05-01")
    assert r["by"] == "SMS from +23276123456"
    assert r["asset_id"] == ID


def test_the_identifier_is_read_as_the_registry_reads_it_and_the_rest_is_the_note():
    r = F.parse_sms(f"  bh  {ID.lower()}   broken  handle   snapped ", received="2026-05-01")
    assert r["status"] == "accepted" and r["asset_id"] == ID and r["typed"] == ID.lower()
    assert r["note"] == "handle snapped"
    # with no sender the record says only that it came by SMS
    assert r["by"] == phrase("fault_reports.sms_by_unknown") == "SMS"


def test_a_mistyped_identifier_is_refused_in_the_registrys_own_words():
    r = F.parse_sms(f"BH {MISTYPED} BROKEN", received="2026-05-01")
    assert r["status"] == "refused"
    assert r["reason"] == registry.validate_asset_id(MISTYPED)[1]
    assert "should end in " + ID[-1] in r["reason"]


@pytest.mark.parametrize(("text", "key"), [
    ("", "no_bh"),
    ("BROKEN " + ID, "no_bh"),
    ("BHX " + ID + " BROKEN", "no_bh"),
    ("BH", "no_identifier"),
    ("BH " + ID, "no_word"),
])
def test_a_message_that_is_not_a_report_says_what_a_report_is(text, key):
    r = F.parse_sms(text, received="2026-05-01")
    assert r["status"] == "refused"
    words = "WORKING, BROKEN, SLOW, TASTE, COLOUR, COLOR or BAD"
    assert r["reason"] == phrase(f"fault_reports.{key}", words=words)


def test_a_word_that_is_not_one_of_the_reports_is_refused_not_guessed():
    r = F.parse_sms(f"BH {ID} FIXED", received="2026-05-01")
    assert r["status"] == "refused" and r["asset_id"] == ID
    assert r["reason"].startswith("FIXED is not one of the report's words")


def test_the_day_comes_from_the_message_or_the_person_never_the_clock():
    # no day received and none given: refused, not dated today
    r = F.parse_sms(f"BH {ID} BROKEN")
    assert r["status"] == "refused" and r["reason"] == phrase("fault_reports.no_date")
    # the person importing gives the day for messages that carry none
    r = F.parse_sms(f"BH {ID} BROKEN", received_on="2026-05-03")
    assert r["status"] == "accepted" and r["when"] == "2026-05-03"
    # but a day the gateway gave is the message's own, and wins
    r = F.parse_sms(f"BH {ID} BROKEN", received="2026-05-01 23:59", received_on="2026-05-03")
    assert r["when"] == "2026-05-01"
    # a time received that does not begin with a day is not read as one
    for stamp in ("08:14", "01/05/2026", "2026-02-30T10:00"):
        r = F.parse_sms(f"BH {ID} BROKEN", received=stamp, received_on="2026-05-03")
        assert r["status"] == "refused", stamp
        assert r["reason"] == phrase("fault_reports.bad_date",
                                     date=stamp[:10] if stamp[0] == "2" else stamp)


def test_a_report_the_registry_reads_only_with_a_note_is_held_for_a_person(monkeypatch):
    """An identifier read with a note (one minted with an older check
    character, where the registry accepts it) has nobody to read the note
    when it comes by SMS, so the report is held, not merged."""
    real = registry.validate_asset_id

    def noted(text):
        ok, reason = real(text)
        return (True, "Compare it with the plate.") if ok else (ok, reason)

    monkeypatch.setattr(registry, "validate_asset_id", noted)
    r = F.parse_sms(f"BH {ID} BROKEN gone", received="2026-05-01", sender="+232")
    assert r["status"] == "held"
    assert r["reason"] == phrase("fault_reports.held", note="Compare it with the plate.")
    # it carries everything it needs once a person confirms it
    assert (r["asset_id"], r["kind"], r["when"], r["note"]) == (ID, "failure", "2026-05-01", "gone")
    merged = F.merge_reports([_asset()], [r])
    assert merged["added"] == 0 and merged["assets"][0].events == []
    confirmed = F.confirm_report(r)
    assert confirmed["status"] == "accepted" and confirmed["reason"] == ""
    assert F.merge_reports([_asset()], [confirmed])["added"] == 1
    # the same identifier is refused before it is held when anything else is wrong
    assert F.parse_sms(f"BH {ID} FIXED", received="2026-05-01")["status"] == "refused"
    assert F.parse_sms(f"BH {ID} BROKEN")["status"] == "refused"
    # and on the report page the note is shown to the person at the plate,
    # so a report made there is accepted
    assert F.report_record(ID, "broken", "2026-05-01")["status"] == "accepted"


_LEGACY_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js', 'support.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const typed = process.argv[3];
process.stdout.write(JSON.stringify({
  verdict: C.validateAssetId(typed),
  sms: C.parseSms('BH ' + typed + ' BROKEN', '2026-05-01', '+232'),
  page: C.reportRecord(typed, 'broken', '2026-05-01'),
}));
"""


def test_an_sms_naming_a_borehole_by_its_older_check_character_is_held(tmp_path):
    """The registry's own check decides, so the ISO 7064 correction of the
    check character reaches SMS reports with no change here: an identifier
    the registry reads only by the character it was minted with before the
    correction is held for a person, in both engines, and one typed on the
    report page is taken, the page showing the registry's note."""
    older = getattr(registry, "legacy_check_character", None)
    if older is None:
        pytest.skip("this registry reads one check character; the older one is read "
                    "once the ISO 7064 MOD 37,36 correction is merged")
    body = next(b for b in (i.rsplit("-", 1)[0] for i in (ID, OTHER, *_IDS))
                if older(b) != registry.check_character(b))
    typed = f"{body}-{older(body)}"
    ok, note = registry.validate_asset_id(typed)
    assert ok and note
    sms = F.parse_sms(f"BH {typed} BROKEN", received="2026-05-01", sender="+232")
    assert sms["status"] == "held"
    assert sms["reason"] == phrase("fault_reports.held", note=note)
    assert F.report_record(typed, "broken", "2026-05-01")["status"] == "accepted"
    node = shutil.which("node")
    if node is None:
        return
    driver = tmp_path / "legacy.mjs"
    driver.write_text(_LEGACY_DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS), typed], capture_output=True,
                          text=True, encoding="utf-8", check=True)
    told = json.loads(done.stdout)
    assert told["verdict"]["ok"] and told["verdict"]["reason"] == note
    assert told["sms"] == json.loads(json.dumps(sms))
    assert told["page"]["status"] == "accepted"


def test_only_a_held_report_can_be_confirmed():
    refused = F.parse_sms(f"BH {MISTYPED} BROKEN", received="2026-05-01")
    assert F.confirm_report(refused) is refused
    accepted = F.parse_sms(f"BH {ID} BROKEN", received="2026-05-01")
    assert F.confirm_report(accepted) is accepted


# ---------------------------------------------------------------------------
# A file of messages, and the gateway's interface
# ---------------------------------------------------------------------------

def test_a_file_of_messages_reads_the_day_time_and_sender_before_bh():
    text = "\r\n".join([
        f"2026-05-01 08:14 +23276123456 BH {ID} BROKEN handle snapped",
        "",
        f"2026-05-02T09:00:00Z,Fatmata Kamara,BH {ID} taste brown water",
        f"2026-05-02;+232;bh {ID} working",
        f"08:30 BH {ID} SLOW",
        f"BH {ID} SLOW",
    ])
    rows = F.read_sms_lines(text, received_on="2026-05-03")
    assert [r["line"] for r in rows] == [1, 3, 4, 5, 6]
    assert [r["status"] for r in rows] == ["accepted"] * 5
    assert [(r["when"], r["sender"], r["received"]) for r in rows] == [
        ("2026-05-01", "+23276123456", "2026-05-01 08:14"),
        ("2026-05-02", "Fatmata Kamara", "2026-05-02T09:00:00Z"),
        ("2026-05-02", "+232", "2026-05-02"),
        ("2026-05-03", "", "08:30"),
        ("2026-05-03", "", ""),
    ]
    assert rows[0]["by"] == "SMS from +23276123456" and rows[0]["note"] == "handle snapped"
    assert rows[1]["choice"] == "taste" and rows[1]["note"] == "brown water"


def test_a_line_whose_day_cannot_be_told_is_refused():
    text = "\n".join([
        f"01/05/2026 BH {ID} SLOW",
        f"2026-05-01 2026-05-02 BH {ID} SLOW",
        f"2026-13-01 BH {ID} SLOW",
        "hello there",
        f"BH {MISTYPED} BROKEN",
    ])
    rows = F.read_sms_lines(text, received_on="2026-05-03")
    assert [r["status"] for r in rows] == ["refused"] * 5
    assert rows[0]["reason"] == phrase("fault_reports.bad_date", date="01/05/2026")
    assert rows[1]["reason"] == phrase("fault_reports.two_dates", first="2026-05-01",
                                       second="2026-05-02")
    assert rows[2]["reason"] == phrase("fault_reports.bad_date", date="2026-13-01")
    assert rows[3]["reason"].startswith("Not a report")
    assert "check character" in rows[4]["reason"]
    assert F.read_sms_lines(None) == [] and F.read_sms_lines("\n \n") == []


def test_the_gateway_adapter_takes_received_messages_and_merges_nothing():
    """An SMS gateway is optional: whatever runs one hands this the messages."""
    out = F.receive_messages([
        {"text": f"BH {ID} BROKEN", "received": "2026-05-01T07:00:00+00:00", "sender": "+232"},
        f"BH {ID} WORKING",
        {"text": f"BH {ID} SLOW", "received": "yesterday"},
        7,
    ], received_on="2026-05-04")
    assert [r["line"] for r in out] == [1, 2, 3, 4]
    assert [r["status"] for r in out] == ["accepted", "accepted", "refused", "refused"]
    assert out[0]["when"] == "2026-05-01" and out[1]["when"] == "2026-05-04"
    assert F.receive_messages(None) == [] and F.receive_messages({"text": "x"}) == []


# ---------------------------------------------------------------------------
# The report page
# ---------------------------------------------------------------------------

def test_a_report_from_the_page_is_checked_as_an_sms_is():
    r = F.report_record(ID.lower(), "slow", " 2026-05-01 ", " slow since Monday ", " Aminata ")
    assert r["status"] == "accepted"
    assert (r["asset_id"], r["kind"], r["when"], r["note"], r["by"]) == (
        ID, "reported_slow", "2026-05-01", "slow since Monday", "Aminata")
    assert F.report_record(MISTYPED, "slow", "2026-05-01")["status"] == "refused"
    assert F.report_record(ID, "fixed", "2026-05-01")["reason"] == phrase("fault_reports.no_choice")
    assert F.report_record(ID, "slow", "2026-02-30")["reason"] == phrase(
        "fault_reports.bad_day", when="2026-02-30")
    # a day left blank is asked for, not quoted back as a blank
    for blank in ("", " ", None, 20260501):
        assert F.report_record(ID, "slow", blank)["reason"] == phrase("fault_reports.no_day")
    assert F.report_record("", "slow", "2026-05-01")["reason"] == "No identifier was entered."


def test_a_photograph_keeps_its_provenance_and_nothing_else_does():
    provenance = {"format": 1, "sha256": "ab" * 32, "stored": "original"}
    r = F.report_record(ID, "broken", "2026-05-01", photo="data:image/jpeg;base64,AAAA",
                        photo_provenance=provenance)
    assert r["photo"] and r["photo_provenance"] == provenance
    # no photograph, no provenance; a record with no hash is evidence of nothing
    assert F.report_record(ID, "broken", "2026-05-01",
                           photo_provenance=provenance)["photo_provenance"] is None
    assert F.report_record(ID, "broken", "2026-05-01", photo="data:x",
                           photo_provenance={"sha256": ""})["photo_provenance"] is None
    # nor is a hash that is not a SHA-256 as both engines write one
    for sha in ("ab", "AB" * 32, "ab" * 31 + "a", "ab" * 32 + "\n", "gh" * 32):
        assert F.report_record(ID, "broken", "2026-05-01", photo="data:x",
                               photo_provenance={"sha256": sha})["photo_provenance"] is None


# ---------------------------------------------------------------------------
# Into the registry
# ---------------------------------------------------------------------------

def test_reports_merge_into_the_boreholes_they_name_by_the_registrys_rule():
    reports = F.read_sms_lines("\n".join([
        f"2026-05-01 +232 BH {ID} BROKEN handle snapped",
        f"2026-05-01 +232 BH {ID} BROKEN handle snapped",    # sent twice: one record
        f"2026-05-01 +999 BH {ID} BROKEN handle snapped",    # another sender: another
        f"2026-05-02 BH {OTHER} WORKING",
        f"2026-05-02 BH {MISTYPED} WORKING",
    ]))
    merged = F.merge_reports([_asset(AssetEvent("2020-01-10", "commissioned"))], reports)
    assert (merged["added"], merged["already"]) == (2, 0)
    assert [r["asset_id"] for r in merged["unmatched"]] == [OTHER]
    asset = merged["assets"][0]
    # two records of one kind on one day are in the order of their
    # identifiers, which follow the borehole's identifier: compared as a set
    assert sorted((e.when, e.kind, e.by) for e in asset.events) == [
        ("2020-01-10", "commissioned", ""),
        ("2026-05-01", "failure", "SMS from +232"),
        ("2026-05-01", "failure", "SMS from +999")]
    state = asset_state(asset, DAY)
    assert state.function == "non_functional" and state.days_out_of_service == 31
    # imported again, it adds nothing
    again = F.merge_reports([asset], reports)
    assert (again["added"], again["already"]) == (0, 2)
    assert again["assets"][0].events == asset.events
    # a saved record merges the same as the asset it came from
    from_dict = F.merge_reports([asset.as_dict()], reports)
    assert from_dict["assets"][0].as_dict() == again["assets"][0].as_dict()


def test_what_each_report_establishes():
    def state_after(*kinds):
        events = [AssetEvent("2020-01-10", "commissioned"), AssetEvent("2026-03-01", "failure")]
        events += [AssetEvent("2026-05-01", k) for k in kinds]
        return asset_state(_asset(*events), DAY)

    # a report that it works says so, as a failure report says the opposite
    assert state_after("reported_working").function == "functional"
    assert state_after("reported_working").detail.startswith("Reported working recorded on")
    # slow, and water that tastes or looks wrong, say something is the
    # matter without saying whether water comes: the failure stands
    assert state_after("reported_slow").function == "non_functional"
    assert state_after("quality_complaint").function == "non_functional"
    assert registry.EVENT_KINDS["quality_complaint"][0] == "Water quality complaint"
    # and nothing assumed: a slow report alone leaves the borehole unknown
    assert asset_state(_asset(AssetEvent("2026-05-01", "reported_slow")), DAY).function == "unknown"


def test_a_photographs_provenance_travels_with_it_and_is_not_part_of_the_identifier():
    provenance = {"format": 1, "sha256": "cd" * 32}
    plain = AssetEvent("2026-05-01", "failure", note="x", by="SMS")
    pictured = AssetEvent("2026-05-01", "failure", note="x", by="SMS",
                          photo="data:image/jpeg;base64,AAAA", photo_provenance=provenance)
    assert plain.identified_for(ID).event_id == pictured.identified_for(ID).event_id
    merged = registry.merge_events(ID, [plain], [pictured])
    assert len(merged) == 1 and merged[0].photo_provenance == provenance
    saved = _asset(pictured).as_dict()
    assert saved["events"][0]["photo_provenance"] == provenance
    assert asset_from_dict(saved).events[0].photo_provenance == provenance
    # an event with none is written as it was before
    assert "photo_provenance" not in _asset(plain).as_dict()["events"][0]
    assert registry.clean_photo_provenance({"sha256": 5}) is None
    assert registry.clean_photo_provenance([provenance]) is None


def test_a_working_report_is_a_report_of_working_to_the_survival_analysis():
    from groundwater.survival import borehole_times

    working = _asset(AssetEvent("2020-01-10", "commissioned"),
                     AssetEvent("2022-01-10", "reported_working"),
                     AssetEvent("2023-01-10", "reported_slow"),
                     AssetEvent("2023-06-10", "quality_complaint"))
    times = borehole_times(working, DAY)
    assert (times["end"], times["ends"], times["failed"]) == ("2022-01-10", "report", False)


# ---------------------------------------------------------------------------
# The file a phone exports
# ---------------------------------------------------------------------------

def test_the_file_of_reports_round_trips_and_is_checked_again_on_the_way_in():
    provenance = {"format": 1, "sha256": "ef" * 32}
    reports = [
        F.report_record(ID, "broken", "2026-05-01", "handle", "Aminata",
                        "data:image/jpeg;base64,AAAA", provenance),
        F.parse_sms(f"BH {OTHER} WORKING", received="2026-05-02", sender="+232"),
        F.parse_sms(f"BH {MISTYPED} WORKING", received="2026-05-02"),
    ]
    payload = F.reports_file(reports)
    assert payload["format"] == F.REPORTS_FORMAT and payload["version"] == F.REPORTS_VERSION
    assert len(payload["reports"]) == 2       # only what was accepted goes out
    assert payload["reports"][0]["photo_provenance"] == provenance
    assert "photo" not in payload["reports"][1]
    back = F.read_reports_file(json.loads(json.dumps(payload)))
    assert [r["status"] for r in back] == ["accepted", "accepted"]
    assert [r["line"] for r in back] == [1, 2]
    for got, sent in zip(back, reports[:2], strict=True):
        for key in ("asset_id", "choice", "kind", "when", "note", "by", "photo",
                    "photo_provenance"):
            assert got[key] == sent[key], key
    # an entry that does not check is refused on the way in, not trusted
    payload["reports"].append({"asset_id": MISTYPED, "choice": "broken", "when": "2026-05-01"})
    payload["reports"].append("not a report")
    back = F.read_reports_file(payload)
    assert [r["status"] for r in back] == ["accepted", "accepted", "refused", "refused"]


@pytest.mark.parametrize("payload", [
    None, [], {"format": "something else", "version": 1, "reports": []},
    {"format": F.REPORTS_FORMAT, "version": 2, "reports": []},
    {"format": F.REPORTS_FORMAT, "version": True, "reports": []},
    {"format": F.REPORTS_FORMAT, "version": 1, "reports": {}},
])
def test_a_file_that_is_not_one_is_refused_whole(payload):
    with pytest.raises(ValueError, match="not a file of borehole reports"):
        F.read_reports_file(payload)


def test_the_table_of_an_import_says_what_became_of_each_line():
    rows = F.read_sms_lines(f"2026-05-01 +232 BH {ID} BROKEN\nhello\nBH {ID} SLOW",
                            received_on="")
    assert F.report_header() == ["Line", "Received", "Sender", "Borehole", "Says",
                                 "Outcome", "Why"]
    table = F.report_rows(rows)
    assert table[0] == ["1", "2026-05-01", "+232", ID, "Broken", "Accepted", ""]
    assert table[1][:6] == ["2", "", "", "", "", "Refused"]
    assert table[2][:6] == ["3", "", "", ID, "Slow", "Refused"]
    assert F.import_summary(rows) == (
        "3 read: 1 accepted, 0 held for a person to confirm, 2 refused.")
    assert F.report_rows(None) == [] and F.report_rows([{"status": ["x"]}]) == []


# ---------------------------------------------------------------------------
# The plate
# ---------------------------------------------------------------------------

def test_the_report_address_is_blank_until_the_programme_sets_one():
    assert ServiceConfig().report_url == ""
    assert Config().service.report_url == ""
    asset = _asset()
    assert registry.qr_payload(asset).startswith(f"BOREHOLE {ID}\n")
    assert registry.scan_start(ID) == f"BOREHOLE {ID}"


def test_with_an_address_the_symbol_is_a_link_to_the_boreholes_report_page():
    asset = _asset()
    link = "https://water.example.org/toolkit/#/report/" + ID
    assert registry.qr_payload(asset, "https://water.example.org/toolkit/") == link
    assert registry.qr_payload(asset, "  https://water.example.org/toolkit/ ") == link
    assert registry.report_link(ID, "HTTPS://example.org/a?b=c") == (
        "HTTPS://example.org/a?b=c#/report/" + ID)
    assert registry.scan_start(ID, "https://water.example.org/toolkit/") == link


@pytest.mark.parametrize("url", [
    "http://water.example.org/", "water.example.org", "https://", "https:///x",
    "https://example.org/#/report", "https://example .org/", "ftp://example.org",
    "https://example.org/a\u00a0b",
    # printable ASCII only: Python's re.IGNORECASE read a long s as an s and
    # passed this one where the browser refused it
    "http\u017f://example.org/", "https://w\u00e1ter.example.org/", "https://example.org/\x01",
    "https://example.org/\x7f",
])
def test_an_address_a_phone_could_not_keep_offline_is_refused(url):
    reason = registry.check_report_url(url)
    assert reason == phrase("fault_reports.url_refused", url=registry.trim_field(url))
    with pytest.raises(ValueError, match="cannot go on a plate"):
        registry.qr_payload(_asset(), url)


def test_the_rounds_say_what_a_scan_of_the_plate_begins_with():
    from groundwater.rounds import service_rounds

    assets = [_asset(AssetEvent("2020-01-10", "commissioned"))]
    plain = service_rounds(assets, DAY)["rounds"][0]["stops"][0]["plate"]
    linked = service_rounds(assets, DAY, report_url="https://example.org/")["rounds"][0]
    assert plain == f"BOREHOLE {ID}"
    assert linked["stops"][0]["plate"] == "https://example.org/#/report/" + ID
    with pytest.raises(ValueError, match="cannot go on a plate"):
        service_rounds(assets, DAY, report_url="http://example.org/")


def test_the_plate_says_what_its_symbol_is(tmp_path):
    from docx import Document

    from groundwater.reporting.registry import AssetReportInputs, build_asset_placard

    asset = _asset(AssetEvent("2020-01-10", "commissioned"))

    def text(config):
        out = build_asset_placard(AssetReportInputs(asset=asset, figures_dir=tmp_path,
                                                    today=DAY), tmp_path / "p.docx", config)
        return "\n".join(p.text for p in Document(str(out)).paragraphs)

    plain = text(None)
    assert phrase("fault_reports.placard_caption_text") in plain
    assert phrase("fault_reports.placard_quote") in plain
    linked = text(replace(Config(), service=ServiceConfig(report_url="https://example.org/")))
    assert phrase("fault_reports.placard_caption_link") in linked
    assert phrase("fault_reports.placard_caption_text") not in linked
    with pytest.raises(ValueError, match="cannot go on a plate"):
        text(replace(Config(), service=ServiceConfig(report_url="http://example.org/")))


def test_the_linked_symbol_reads_back(tmp_path):
    cv2 = pytest.importorskip("cv2", reason="no decoder installed")
    import numpy as np

    from groundwater.reporting.registry import write_qr_png

    payload = registry.qr_payload(_asset(), "https://water.example.org/toolkit/")
    png = write_qr_png(payload, tmp_path / "qr.png")
    image = cv2.imdecode(np.frombuffer(png.read_bytes(), dtype=np.uint8),
                         cv2.IMREAD_GRAYSCALE)
    assert cv2.QRCodeDetector().detectAndDecode(image)[0] == payload


# ---------------------------------------------------------------------------
# The browser's engine, held to this one
# ---------------------------------------------------------------------------

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, structuredClone, TextEncoder, TextDecoder });
for (const f of ['gwt-data.js', 'gwt-geo.js', 'gwt-core.js', 'support.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox, { filename: f });
}
const C = sandbox.GWT.core;
const cases = JSON.parse(readFileSync(0, 'utf8'));
const answer = (c) => {
  try {
    const lines = C.readSmsLines(c.text, c.received_on);
    const messages = C.receiveMessages(c.messages, c.received_on);
    const page = c.page.map((a) => C.reportRecord(...a));
    const all = lines.concat(messages, page, c.odd);
    const merged = C.mergeReports(c.assets, all);
    const file = C.reportsFile(all);
    return { ok: { lines, messages, page, merged, file,
      back: C.readReportsFile(JSON.parse(JSON.stringify(file))),
      rows: C.reportRows(all), summary: C.importSummary(all), header: C.reportHeader(),
      links: c.urls.map((u) => C.checkReportUrl(u)) } };
  } catch (e) {
    return { threw: String(e && e.stack || e) };
  }
};
const out = cases.map(answer);
// the held path: a check that reads an identifier with a note, standing in
// for one minted with an older check character
const real = C.validateAssetId;
C.validateAssetId = (t) => {
  const v = real(t);
  return v.ok ? Object.assign({}, v, { reason: 'Compare it with the plate.' }) : v;
};
out.push(answer(cases[0]));
C.validateAssetId = real;
process.stdout.write(JSON.stringify(out));
"""

_IDS = [ID, OTHER, mint_asset_id(SiteMetadata(district="Kailahun", easting=280400.0,
                                              northing=925600.0, utm_zone=29))]
_WORDS = ["WORKING", "broken", "Slow", "taste", "COLOUR", "color", "BAD", "FIXED", "", "bh"]
_PREFIXES = ["", "2026-05-01 ", "2026-05-01 08:14 ", "2026-05-01T08:14:00Z,", "+23276123456 ",
             "2026-05-01;Fatmata Kamara;", "01/05/2026 ", "2026-13-01 ", "08:14 ",
             "2026-05-01 2026-05-02 ", "x ", "\u00a0", "2026-05-01\t+232 ", "1.5.26 ",
             "2026-05-01T08:14+0100 ", "2026-05-01 +23276123456 "]
_NOTES = ["", " handle snapped", "  brown  water ", " \u3000noted", " 2026-05-09", " \U0001f600"]
_URLS = ["", "https://example.org/", "http://example.org/", "https://", "https://a#b",
         " https://a.org/x?y=1 ", "https://a .org", "https://a.org/\ufeff", 7, None,
         "http\u017f://a.org", "HTTPS://A.ORG/x", "https://\u00e9.org", "https://a.org/~\x7f",
         "https://xn--wter-6qa.example.org/a?b=c&d=%20"]


def _identifier(rng: random.Random) -> str:
    chosen, pick = rng.choice(_IDS), rng.random()
    if pick < 0.15:
        return chosen[:-1] + rng.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    if pick < 0.25:
        return chosen.lower()
    if pick < 0.3:
        return chosen.replace("-", "")
    if pick < 0.35:
        return ""
    if pick < 0.4:
        return chosen[3:]
    return chosen


def _odd(rng: random.Random) -> list:
    """Records marked accepted that no reader here wrote: a queue or a file
    edited by hand, its fields missing, of the wrong type or untrimmed. Both
    engines read each as the registry reads a saved event."""
    pool = [
        {"status": "accepted"},
        {"status": "accepted", "asset_id": rng.choice(_IDS), "kind": "bogus",
         "when": " 2026-05-07 ", "note": 5, "by": None, "photo": 7,
         "photo_provenance": {"sha256": "ab" * 32}},
        {"status": "accepted", "asset_id": rng.choice(_IDS), "choice": ["x"], "when": None,
         "kind": "failure", "note": " kept as written ", "photo": "data:image/jpeg;base64,AAAA",
         "photo_provenance": {"sha256": "AB" * 32}},
        {"status": "accepted", "asset_id": 7, "kind": "reported_working", "when": "2026-05-08"},
    ]
    return rng.sample(pool, rng.randint(0, len(pool)))


def _case(seed: int) -> dict:
    rng = random.Random(f"fault reports {seed}")
    lines = [rng.choice(_PREFIXES) + rng.choice(["BH", "bh", "Bh", "BH:", "B H"]) + " "
             + _identifier(rng) + (" " + w if (w := rng.choice(_WORDS)) else "")
             + rng.choice(_NOTES) for _ in range(rng.randint(5, 60))]
    # the report a stored record came from, sent again
    lines.insert(rng.randint(0, len(lines)),
                 f"2026-05-01 +23276123456 BH {_IDS[rng.randint(0, 2)]} BROKEN handle snapped")
    stamps =["", "2026-05-02T10:00:00Z", "08:00", "2026-02-30", "2026-05-02 10:00"]
    messages = [{"text": rng.choice(lines), "received": rng.choice(stamps),
                 "sender": rng.choice(["", "+23276", 5])}
                for _ in range(rng.randint(0, 10))] + [rng.choice(lines), 3, None]
    page = [[rng.choice([_IDS[0], _IDS[0][:-1] + "Q", "", 5]),
             rng.choice(["working", "broken", "slow", "taste", "x", None]),
             rng.choice(["2026-05-01", "2026-02-30", "", " 2026-05-04 "]),
             rng.choice(["", " n ", 4]), rng.choice(["", "Me"]),
             rng.choice(["", "data:image/jpeg;base64,AAAA", 7]),
             rng.choice([None, {"sha256": "ab"}, {"sha256": ""}, [], {"sha256": 3}])]
            for _ in range(rng.randint(0, 12))]
    # and one with a photograph and its provenance
    page.insert(rng.randint(0, len(page)), [
        rng.choice(_IDS), rng.choice(["working", "broken"]), "2026-05-01", "seen", "",
        "data:image/jpeg;base64,AAAA", {"format": 1, "sha256": "ab" * 32}])
    assets = [{"asset_id": i, "community": "Case", "district": "Western Area Rural",
               "easting": 694912.0, "northing": 938150.0, "utm_zone": 28,
               "events": [{"when": "2026-05-01", "kind": "failure", "note": "handle snapped",
                           "by": "SMS from +23276123456"}]}
              for i in _IDS[:rng.randint(0, 3)]]
    return {"text": rng.choice(["\n", "\r\n", "\r"]).join(lines),
            "received_on": rng.choice(["", "2026-05-03", "not a day"]),
            "messages": messages, "page": page, "assets": assets, "urls": _URLS,
            "odd": _odd(rng)}


def _python(case: dict) -> dict:
    lines = F.read_sms_lines(case["text"], case["received_on"])
    messages = F.receive_messages(case["messages"], case["received_on"])
    page = [F.report_record(*a) for a in case["page"]]
    every = lines + messages + page + case["odd"]
    merged = F.merge_reports(case["assets"], every)
    file = F.reports_file(every)
    return json.loads(json.dumps({
        "lines": lines, "messages": messages, "page": page,
        "merged": {"assets": [a.as_dict() for a in merged["assets"]],
                   "added": merged["added"], "already": merged["already"],
                   "unmatched": merged["unmatched"]},
        "file": file, "back": F.read_reports_file(json.loads(json.dumps(file))),
        "rows": F.report_rows(every), "summary": F.import_summary(every),
        "header": F.report_header(),
        "links": [registry.check_report_url(u) for u in case["urls"]],
    }))


SEEDS = range(40)


@pytest.fixture(scope="module")
def browser_answers(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path_factory.mktemp("fault_reports") / "reports.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS)],
                          input=json.dumps([_case(seed) for seed in SEEDS]),
                          capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_browser_reads_the_same_reports(browser_answers, seed):
    answer = browser_answers[seed]
    assert "threw" not in answer, answer.get("threw")
    assert answer["ok"] == _python(_case(seed))


def test_the_browser_holds_what_the_registry_reads_with_a_note(browser_answers, monkeypatch):
    real = registry.validate_asset_id

    def noted(text):
        ok, reason = real(text)
        return (True, "Compare it with the plate.") if ok else (ok, reason)

    monkeypatch.setattr(registry, "validate_asset_id", noted)
    want = _python(_case(0))
    answer = browser_answers[len(SEEDS)]
    assert "threw" not in answer, answer.get("threw")
    assert answer["ok"] == want
    assert any(r["status"] == "held" for r in want["lines"])


def test_the_seeded_cases_reach_every_outcome():
    told = [_python(_case(seed)) for seed in SEEDS]
    reasons = {r["reason"].split(" ")[0] for t in told for r in t["lines"] + t["messages"]
               if r["status"] == "refused"}
    assert {"Not", "There", "The", "FIXED"} <= reasons
    statuses = {r["status"] for t in told for r in t["lines"] + t["messages"] + t["page"]}
    # held only where a mistyped character happens to be an identifier's
    # older one, which this registry does not read
    assert {"accepted", "refused"} <= statuses
    assert any(t["merged"]["added"] for t in told) and any(t["merged"]["already"] for t in told)
    assert any(t["merged"]["unmatched"] for t in told)
    assert any(r["photo_provenance"] for t in told for r in t["page"])
    assert any(r["when"] == "2026-05-03" for t in told for r in t["lines"])

"""The asset registry.

Two things are being pinned here. The identifier has to be wrong loudly
rather than quietly, because a mistyped one silently attaches a repair
history to a different village's borehole. And the state derived from the
event stream has to fail closed: an asset register earns its reputation by
going green everywhere as soon as people stop filing reports.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from groundwater import registry
from groundwater.models import SiteMetadata
from groundwater.registry import (
    Asset,
    AssetEvent,
    Schedule,
    asset_state,
    check_character,
    merge_events,
    mint_asset_id,
    parse_asset_id,
    registry_stats,
    validate_asset_id,
)

# Dr. Timbo's Residence, Western Area Rural: 8.48310 N, 13.22940 W.
TIMBO = SiteMetadata(community="Dr. Timbo's", district="Western Area Rural",
                     easting=694912.0, northing=938150.0, utm_zone=28)


# ---------------------------------------------------------------------------
# The identifier
# ---------------------------------------------------------------------------

def test_the_same_borehole_gets_the_same_identifier_from_either_phone():
    """There is no server to allocate from, so it has to be derivable."""
    other = SiteMetadata(community="different name entirely",
                         district="Western Area Rural",
                         easting=694914.0, northing=938147.0, utm_zone=28)
    assert mint_asset_id(TIMBO) == mint_asset_id(other)


def test_two_boreholes_a_village_apart_get_different_identifiers():
    far = SiteMetadata(district="Western Area Rural", easting=695512.0,
                       northing=938150.0, utm_zone=28)
    assert mint_asset_id(TIMBO) != mint_asset_id(far)


def test_the_identifier_says_where_it_is_before_you_decode_it():
    assert mint_asset_id(TIMBO).startswith("SL-WAR-")


def test_a_district_nobody_recognises_is_marked_not_guessed():
    odd = SiteMetadata(district="Freetown City", easting=694912.0,
                       northing=938150.0, utm_zone=28)
    assert mint_asset_id(odd).startswith("SL-XX-")


def test_a_borehole_with_no_position_cannot_be_given_an_identifier():
    with pytest.raises(ValueError, match="nothing to find it by"):
        mint_asset_id(SiteMetadata(community="Nowhere"))


def test_every_district_in_the_data_has_a_code_and_no_two_share_one():
    """The codes are written out, so nothing checks them but this."""
    path = Path(registry.__file__).parent / "data" / "sl_districts.csv"
    with path.open(encoding="utf-8") as handle:
        districts = [row["district"] for row in csv.DictReader(handle)]
    for district in districts:
        assert district.lower() in registry.DISTRICT_CODES, district
    codes = list(registry.DISTRICT_CODES.values())
    assert len(set(codes)) == len(codes), "two districts share a code"
    assert registry.UNKNOWN_DISTRICT not in codes


_ISO_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _iso_7064_mod_37_36(body: str) -> str:
    """ISO/IEC 7064's hybrid system with M = 36, written out as the
    standard defines it, independently of the module: P1 = M; for each
    character, S = (P mod (M + 1)) + a, P = 2 x ||S||M (S mod M, with 0
    read as M); the check character a1 makes (P + a1) mod M equal 1."""
    m = 36
    p = m
    for char in body:
        a = _ISO_ALPHABET.find(char)
        if a < 0:
            continue
        s = (p % (m + 1)) + a
        p = 2 * (s % m if s % m else m)
    return _ISO_ALPHABET[(m + 1 - p % (m + 1)) % m]


def test_the_check_character_is_iso_7064_mod_37_36():
    """The published examples, and the standard written out on 20,000 bodies.

    The sum used to be reduced modulo 37 rather than 36. The ISAN examples
    are ISO 15706 identifiers, which carry MOD 37,36 check characters (as
    python-stdnum's ISAN module writes them: 0000-0000-D07A-0090-Q-0000-
    0000-X and 1881-66C7-3420-6541-Y-9F3A-0245-O), and A12425GABC1234002 M
    is the MOD 37,36 example in python-stdnum's iso7064 module.
    """
    import random

    assert check_character("00000000D07A0090") == "Q"
    assert check_character("00000000D07A009000000000") == "X"
    assert check_character("188166C734206541") == "Y"
    assert check_character("188166C7342065419F3A0245") == "O"
    assert check_character("A12425GABC1234002") == "M"
    rng = random.Random(3)
    for _ in range(20000):
        body = "".join(rng.choice(_ISO_ALPHABET) for _ in range(rng.randint(1, 20)))
        assert check_character(body) == _iso_7064_mod_37_36(body), body


def test_every_single_wrong_character_changes_the_check_character():
    """The point of the check character. All of them, not most of them.

    Exhaustive over the states the calculation can be in: from any state,
    two different characters lead to two different states, and two different
    final states give two different check characters, so no string with one
    character changed keeps its check character. The reduction modulo 37 it
    used to make let two final states share "1": SL-BO-C4817SW and
    SL-BO-P4817SW, one character apart, both ended in 1.
    """
    import random

    from groundwater.registry import legacy_check_character

    def step(p, a, modulus):
        s = (p % 37) + a
        return 2 * (s % modulus or modulus)

    def final(p):
        return (37 - p % 37) % 36

    states = {36} | {2 * k for k in range(1, 37)}
    for p in states:
        assert len({step(p, a, 36) % 37 for a in range(36)}) == 36
    assert len({final(p) for p in states}) == 36
    # the legacy calculation's final states are 37, onto 36 characters
    legacy_states = {36} | {2 * k for k in range(1, 38)}
    assert len({final(p) for p in legacy_states}) == 36 < len(legacy_states)

    # and through the module, over identifiers of the shape minted, every
    # position and every character
    rng = random.Random(7)
    crockford = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    bodies = [mint_asset_id(TIMBO).rsplit("-", 1)[0], "SL-BO-C4817SW"] + [
        f"SL-{rng.choice(['WAR', 'BO', 'KEN', 'PL'])}-"
        + "".join(rng.choice(crockford) for _ in range(7)) for _ in range(300)]
    for body in bodies:
        held_check = check_character(body)
        for position, held in enumerate(body):
            if held == "-":
                continue
            for char in _ISO_ALPHABET:
                if char != held:
                    broken = body[:position] + char + body[position + 1:]
                    assert check_character(broken) != held_check, broken
    assert legacy_check_character("SL-BO-C4817SW") == legacy_check_character(
        "SL-BO-P4817SW") == "1"
    assert check_character("SL-BO-C4817SW") != check_character("SL-BO-P4817SW")


def test_a_mistyped_new_identifier_is_never_accepted_in_silence():
    """Read with the legacy character, a mistyped one says so.

    Identifiers minted before the correction stay readable, and about one
    single mistyped character in 36 of a new identifier happens to match the
    legacy character. Those are accepted with the legacy note, which tells
    the person typing to compare the identifier with the plate; none is
    accepted as a plain valid identifier.
    """
    identifier = mint_asset_id(TIMBO)
    body = identifier.replace("-", "")
    noted = 0
    for position in range(len(body)):
        for char in _ISO_ALPHABET:
            if char == body[position]:
                continue
            broken = body[:position] + char + body[position + 1:]
            candidate = f"SL-{broken[2:5]}-{broken[5:12]}-{broken[12:]}"
            parsed = parse_asset_id(candidate)
            if parsed is None or parsed == identifier:
                continue  # refused, or a forgiven Crockford confusion
            ok, reason = validate_asset_id(candidate)
            assert ok and reason.startswith(
                f"{parsed} ends in the check character identifiers were given "
                "before"), candidate
            assert "a mistyped identifier can pass as an older one" in reason
            assert registry.is_legacy_asset_id(parsed), candidate
            noted += 1
    # of the 455 single mistypings of this identifier, 10 (1 in 45)
    assert noted == 10


def test_most_transpositions_of_two_adjacent_characters_are_caught():
    """All but one in 630: the hybrid system's own limit.

    The module claimed every transposition; ISO 7064 MOD 37,36 does not
    give that. Pinned exactly at the state level: of the 45,360 ways two
    different adjacent characters can meet one of the 36 states the
    calculation can be in, 72 leave the state where it was, and the module
    is the standard (test_the_check_character_is_iso_7064_mod_37_36).
    """
    def step(p, a):
        s = (p % 37) + a
        return 2 * (s % 36 or 36)

    states = sorted({36} | {2 * k for k in range(1, 37)})
    missed = sum(1 for p in states for a in range(36) for b in range(36)
                 if a != b and step(step(p, a), b) == step(step(p, b), a))
    assert missed == 72
    # the identifier the tests use is not one of them, and a swap that the
    # legacy character happens to let through is read only with its note
    identifier = mint_asset_id(TIMBO)
    body = identifier.replace("-", "")
    for i in range(len(body) - 1):
        if body[i] == body[i + 1]:
            continue
        swapped = body[:i] + body[i + 1] + body[i] + body[i + 2:]
        candidate = f"SL-{swapped[2:5]}-{swapped[5:12]}-{swapped[12:]}"
        assert check_character(candidate.rsplit("-", 1)[0]) != candidate[-1] or \
            parse_asset_id(candidate) == identifier, candidate
        parsed = parse_asset_id(candidate)
        if parsed not in (None, identifier):
            assert registry.is_legacy_asset_id(parsed), candidate


def test_a_new_identifier_is_minted_with_the_iso_character():
    identifier = mint_asset_id(TIMBO)
    assert identifier == "SL-WAR-8FEEVKQ-E"
    assert validate_asset_id(identifier) == (True, "")
    assert not registry.is_legacy_asset_id(identifier)


def test_an_identifier_minted_before_the_correction_still_reads():
    """Plates are already fixed to headworks, and histories filed under them.

    SL-WAR-8FEEVKQ-T is the identifier the toolkit minted for Dr. Timbo's
    before the correction. It still parses as itself, is never renamed, and
    a stored asset carrying it still opens with its history; validating it
    says it carries the legacy character and what the standard would give.
    """
    legacy = "SL-WAR-8FEEVKQ-T"
    assert registry.legacy_check_character("SL-WAR-8FEEVKQ") == "T"
    assert parse_asset_id(legacy) == legacy
    assert parse_asset_id(legacy.lower()) == legacy
    assert registry.is_legacy_asset_id(legacy)
    ok, note = validate_asset_id(legacy)
    assert ok
    assert note.startswith("SL-WAR-8FEEVKQ-T ends in the check character identifiers "
                           "were given before the toolkit followed ISO 7064 MOD 37,36")
    assert "it would end in E." in note
    stored = Asset(asset_id=legacy, events=[AssetEvent("2020-01-10", "commissioned")])
    restored = registry.asset_from_dict(stored.as_dict())
    assert restored is not None and restored.asset_id == legacy
    assert [e.kind for e in restored.events] == ["commissioned"]
    # a character neither calculation gives is refused
    assert parse_asset_id("SL-WAR-8FEEVKQ-Z") is None
    ok, reason = validate_asset_id("SL-WAR-8FEEVKQ-Z")
    assert not ok and "should end in E, not Z" in reason


def test_the_reading_confusions_are_forgiven_but_wrong_codes_are_not():
    """I and L for 1, O for 0, U for V - read off a plate, not different codes."""
    identifier = mint_asset_id(TIMBO)
    typed = identifier.replace("1", "I").replace("0", "O").lower()
    assert parse_asset_id(typed) == identifier
    assert parse_asset_id(" " + identifier.replace("SL-", "") + " ") == identifier
    assert parse_asset_id("SL-WAR-8T4KQ2A-7") is None or \
        parse_asset_id("SL-WAR-8T4KQ2A-7").startswith("SL-WAR-")


def test_a_wrong_identifier_is_refused_with_something_a_person_can_act_on():
    identifier = mint_asset_id(TIMBO)
    wrong = identifier[:-1] + ("Z" if identifier[-1] != "Z" else "Y")
    ok, reason = validate_asset_id(wrong)
    assert not ok
    assert "check character" in reason and "mistyped" in reason
    assert identifier[-1] in reason        # it says what it should have been

    ok, reason = validate_asset_id("")
    assert not ok and "No identifier" in reason
    ok, reason = validate_asset_id("just some words")
    assert not ok and "SL-WAR" in reason


def test_the_check_character_ignores_separators():
    assert check_character("SL-WAR-8T4KQ2A") == check_character("SLWAR8T4KQ2A")


# ---------------------------------------------------------------------------
# The event stream
# ---------------------------------------------------------------------------

def _asset(*events) -> Asset:
    return Asset(asset_id=mint_asset_id(TIMBO), community="Dr. Timbo's",
                 district="Western Area Rural", easting=694912.0,
                 northing=938150.0, utm_zone=28, events=list(events))


def test_a_borehole_nobody_has_reported_on_is_not_working_it_is_unknown():
    """The failure mode of every asset register: silence read as success."""
    state = asset_state(_asset(), date(2024, 6, 1))
    assert state.function == "unknown"
    assert not state.is_working
    assert state.label == "Not known"


def test_a_failure_with_no_repair_stays_a_failure():
    state = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2023-04-02", "failure", "rising main parted"),
    ), date(2024, 6, 1))
    assert state.function == "non_functional"
    assert state.days_out_of_service == 426
    assert not state.is_working


def test_a_repair_puts_it_back_in_service():
    state = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2023-04-02", "failure", "rising main parted"),
        AssetEvent("2023-05-11", "restored", "new rising main", by="A. Bangura"),
    ), date(2024, 6, 1))
    assert state.function == "functional"
    assert state.days_out_of_service is None
    assert "A. Bangura" in state.detail


def test_the_order_events_arrive_in_does_not_change_the_answer():
    """They arrive from two phones, in whatever order the merge happens."""
    events = [
        AssetEvent("2023-05-11", "restored"),
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2023-04-02", "failure"),
    ]
    forwards = asset_state(_asset(*events), date(2024, 6, 1))
    backwards = asset_state(_asset(*reversed(events)), date(2024, 6, 1))
    assert forwards.as_dict() == backwards.as_dict()


def test_a_record_dated_in_the_future_settles_nothing_yet():
    state = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2023-04-02", "failure"),
        AssetEvent("2099-01-01", "restored"),
    ), date(2024, 6, 1))
    assert state.function == "non_functional"


def test_an_unreadable_date_is_kept_but_establishes_nothing():
    """Losing a maintenance record to a typo is worse than not counting it."""
    asset = _asset(AssetEvent("last rains", "repair", "changed the seals"))
    state = asset_state(asset, date(2024, 6, 1))
    assert state.function == "unknown"
    assert state.undated_events == 1
    assert "nobody can read" in state.detail
    assert len(merge_events(asset.asset_id, asset.events)) == 1


def test_the_same_visit_written_down_twice_merges_into_one():
    """Two people at one wellhead, two phones, one repair."""
    mine = [AssetEvent("2023-05-11", "repair", "new seals", by="A. Bangura")]
    theirs = [AssetEvent("2023-05-11", "repair", "new seals", by="A. Bangura")]
    merged = merge_events("SL-WAR-8T4KQ2A-7", mine, theirs)
    assert len(merged) == 1


def test_merging_is_a_union_that_does_not_care_about_order_or_repetition():
    a = [AssetEvent("2023-05-11", "repair", "new seals")]
    b = [AssetEvent("2023-04-02", "failure", "rising main parted")]
    once = [e.event_id for e in merge_events("X", a, b)]
    again = [e.event_id for e in merge_events("X", b, a, a, b)]
    assert once == again


def test_a_merge_keeps_the_copy_that_has_the_photograph():
    without = [AssetEvent("2023-05-11", "repair", "new seals")]
    with_photo = [AssetEvent("2023-05-11", "repair", "new seals",
                             photo="data:image/jpeg;base64,AAAA")]
    for order in ((without, with_photo), (with_photo, without)):
        merged = merge_events("X", *order)
        assert len(merged) == 1 and merged[0].photo


# ---------------------------------------------------------------------------
# What is due
# ---------------------------------------------------------------------------

def test_an_annual_sample_falls_due_a_year_after_the_last_one():
    state = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2023-03-01", "water_sample"),
    ), date(2024, 6, 1))
    sample = [i for i in state.due if i.key == "water_sample"][0]
    assert sample.due_on == date(2024, 3, 1)
    assert sample.state == "overdue"
    assert "2024-03-01" in sample.detail


def test_a_borehole_that_has_never_been_sampled_counts_from_commissioning():
    """Otherwise a point nobody ever sampled is never overdue for sampling."""
    state = asset_state(_asset(AssetEvent("2020-01-10", "commissioned")),
                        date(2024, 6, 1))
    sample = [i for i in state.due if i.key == "water_sample"][0]
    assert sample.state == "overdue"
    assert "has never been done" in sample.detail


def test_with_no_dates_at_all_the_schedule_is_unknown_rather_than_satisfied():
    state = asset_state(_asset(), date(2024, 6, 1))
    assert {i.state for i in state.due} == {"unknown"}
    assert state.overdue == ()


def test_the_grace_period_separates_due_from_overdue():
    events = [AssetEvent("2020-01-10", "commissioned"),
              AssetEvent("2023-06-01", "inspection")]
    due = asset_state(_asset(*events), date(2023, 12, 15))
    overdue = asset_state(_asset(*events), date(2024, 2, 1))
    assert [i.state for i in due.due if i.key == "inspection"] == ["due"]
    assert [i.state for i in overdue.due if i.key == "inspection"] == ["overdue"]


def test_a_due_date_never_drifts_forward_over_a_short_month():
    state = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2023-08-31", "inspection"),
    ), date(2023, 9, 1))
    inspection = [i for i in state.due if i.key == "inspection"][0]
    assert inspection.due_on == date(2024, 2, 29)


def test_the_programme_sets_its_own_intervals():
    events = [AssetEvent("2020-01-10", "commissioned"),
              AssetEvent("2023-06-01", "water_sample")]
    quarterly = Schedule(water_sample_months=3, grace_days=0)
    state = asset_state(_asset(*events), date(2023, 10, 1), quarterly)
    sample = [i for i in state.due if i.key == "water_sample"][0]
    assert sample.due_on == date(2023, 9, 1) and sample.state == "overdue"


def test_a_decommissioned_borehole_is_not_chased_for_inspections():
    state = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2022-08-01", "decommissioned", "collapsed, backfilled"),
    ), date(2024, 6, 1))
    assert state.function == "decommissioned"
    assert state.due == ()


def test_a_second_report_of_a_broken_pump_does_not_restart_the_count():
    """Out since January, reported again in May: 143 days, not 12."""
    state = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2024-01-10", "failure", "handle broken", by="M. Kolleh"),
        AssetEvent("2024-05-20", "failure", "still broken, reported at the plate"),
    ), date(2024, 6, 1))
    assert state.function == "non_functional"
    assert state.since == date(2024, 1, 10)
    assert state.days_out_of_service == 143
    assert state.detail == "Failure recorded on 2024-01-10 by M. Kolleh"
    stats = registry_stats([_asset(
        AssetEvent("2024-01-10", "failure"), AssetEvent("2024-05-20", "failure"))],
        date(2024, 6, 1))
    assert stats["mean_days_out_of_service"] == 143
    # a repair still ends it, and the next failure starts a new count
    later = asset_state(_asset(
        AssetEvent("2024-01-10", "failure"), AssetEvent("2024-02-01", "repair"),
        AssetEvent("2024-02-15", "repair"), AssetEvent("2024-05-20", "failure"),
    ), date(2024, 6, 1))
    assert later.since == date(2024, 5, 20) and later.days_out_of_service == 12


def test_decommissioning_is_the_last_thing_that_happens_on_its_day():
    """Same-day records are read commissioned, visits, failure, repair,
    decommissioned, whatever their kind names sort to."""
    collapsed = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2023-03-01", "failure", "hole collapsed"),
        AssetEvent("2023-03-01", "decommissioned", "backfilled"),
    ), date(2024, 6, 1))
    assert collapsed.function == "decommissioned"
    assert collapsed.due == () and collapsed.days_out_of_service is None
    pulled = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2023-03-01", "decommissioned", "dry"),
        AssetEvent("2023-03-01", "repair", "pump pulled for reuse"),
    ), date(2024, 6, 1))
    assert pulled.function == "decommissioned" and pulled.due == ()
    assert registry.SAME_DAY_ORDER["decommissioned"] == max(registry.SAME_DAY_ORDER.values())
    # the history lists them in the same order
    merged = merge_events("X", [AssetEvent("2023-03-01", "decommissioned"),
                                AssetEvent("2023-03-01", "repair"),
                                AssetEvent("2023-03-01", "failure"),
                                AssetEvent("2023-03-01", "commissioned"),
                                AssetEvent("2023-03-01", "inspection")])
    assert [e.kind for e in merged] == ["commissioned", "inspection", "failure",
                                        "repair", "decommissioned"]


def test_a_decommissioned_borehole_returns_only_through_a_commissioning():
    """A repair logged after it is kept, said, and changes nothing."""
    state = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2022-08-01", "decommissioned", "collapsed"),
        AssetEvent("2023-01-05", "repair", "new seals"),
        AssetEvent("2023-02-01", "failure"),
    ), date(2024, 6, 1))
    assert state.function == "decommissioned"
    assert state.since == date(2022, 8, 1)
    assert state.detail == (
        "Decommissioned recorded on 2022-08-01. Records dated after the "
        "decommissioning (repair on 2023-01-05 and failure on 2023-02-01) are "
        "kept in the history but do not bring the borehole back into service: "
        "a decommissioned borehole returns only through a new commissioning record.")
    back = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2022-08-01", "decommissioned", "collapsed"),
        AssetEvent("2023-01-05", "repair", "new seals"),
        AssetEvent("2023-06-01", "commissioned", "redrilled beside the old hole"),
    ), date(2024, 6, 1))
    assert back.function == "functional" and back.since == date(2023, 6, 1)
    assert back.detail == "Commissioned recorded on 2023-06-01"
    # a second decommissioning record is no return to service to explain
    again = asset_state(_asset(
        AssetEvent("2020-01-10", "commissioned"),
        AssetEvent("2022-08-01", "decommissioned", "collapsed"),
        AssetEvent("2023-01-05", "decommissioned", "backfilled"),
    ), date(2024, 6, 1))
    assert again.function == "decommissioned" and again.since == date(2022, 8, 1)
    assert again.detail == "Decommissioned recorded on 2022-08-01"


# ---------------------------------------------------------------------------
# Many of them
# ---------------------------------------------------------------------------

def test_a_functionality_rate_is_never_computed_over_silence():
    """The number that makes these registers untrustworthy."""
    silent = [_asset() for _ in range(9)]
    working = _asset(AssetEvent("2023-01-01", "commissioned"))
    stats = registry_stats(silent + [working], date(2024, 6, 1))
    assert stats["n_assets"] == 10
    assert stats["n_unknown"] == 9
    assert stats["functionality_rate"] == 100.0   # over the one that is known
    assert stats["n_functional"] == 1

    assert registry_stats([], date(2024, 6, 1))["functionality_rate"] is None


def test_the_headline_counts_add_up():
    assets = [
        _asset(AssetEvent("2023-01-01", "commissioned")),
        _asset(AssetEvent("2023-01-01", "commissioned"),
               AssetEvent("2023-09-01", "failure")),
        _asset(AssetEvent("2023-01-01", "commissioned"),
               AssetEvent("2023-09-01", "decommissioned")),
        _asset(),
    ]
    stats = registry_stats(assets, date(2024, 6, 1))
    assert (stats["n_functional"], stats["n_non_functional"],
            stats["n_decommissioned"], stats["n_unknown"]) == (1, 1, 1, 1)
    assert stats["functionality_rate"] == 50.0
    assert stats["mean_days_out_of_service"] == 274


def test_the_registry_record_is_serialisable():
    import json

    import yaml

    asset = _asset(AssetEvent("2023-05-11", "repair", "new seals",
                              by="A. Bangura"))
    payload = {"asset": asset.as_dict(),
               "state": asset_state(asset, date(2024, 6, 1)).as_dict()}
    assert json.dumps(payload)
    assert yaml.safe_dump(payload)
    restored = registry.asset_from_dict(payload["asset"])
    assert restored is not None
    assert restored.asset_id == asset.asset_id
    assert [e.as_dict() for e in restored.events] == \
        [e.identified_for(asset.asset_id).as_dict() for e in asset.events]


def test_a_saved_record_with_a_broken_identifier_is_not_loaded():
    """It would attach somebody else's history to this borehole."""
    assert registry.asset_from_dict({"asset_id": "SL-WAR-XXXXXXX-9"}) is None
    assert registry.asset_from_dict({"community": "no id at all"}) is None
    assert registry.asset_from_dict("not a record") is None


# ---------------------------------------------------------------------------
# What goes on the borehole
# ---------------------------------------------------------------------------

def test_the_symbol_carries_the_facts_and_not_a_link():
    """A link needs a network. The whole reason it is here is that there isn't one."""
    from groundwater import qr

    asset = _asset()
    asset.total_depth_m, asset.safe_yield_m3_per_h = 62.0, 1.85
    payload = registry.qr_payload(asset)
    assert "http" not in payload
    assert asset.asset_id in payload
    assert "Dr. Timbo's" in payload
    assert "8.48310 N, 13.22940 W" in payload
    assert "62.0 m deep" in payload and "1.85 m3/h" in payload
    qr.encode(payload, ecc="H")           # and it fits in a printable symbol


def test_the_placard_shows_the_condition_when_it_is_known():
    asset = _asset(AssetEvent("2020-01-10", "commissioned"))
    rows = dict(registry.placard_lines(asset, asset_state(asset, date(2024, 6, 1))))
    assert rows["Identifier"] == asset.asset_id
    assert rows["Status"] == "Working"
    assert rows["Commissioned"] == "2020-01-10"


def test_an_asset_is_drafted_from_a_project_but_never_commissioned_by_one():
    """Somebody commissions a borehole. Opening a page does not."""
    asset = registry.asset_from_project({"site": TIMBO})
    assert asset is not None and asset.asset_id == mint_asset_id(TIMBO)
    assert asset.events == []
    assert asset_state(asset, date(2024, 6, 1)).function == "unknown"

    assert registry.asset_from_project({}) is None
    assert registry.asset_from_project(
        {"site": SiteMetadata(community="Nowhere")}) is None


def test_degrees_in_the_utm_boxes_are_refused_in_the_gates_words():
    """The browser read them as degrees and certified the plate, while no
    identifier could be minted; Python read them as metres near the equator.
    Both refuse them, and the identifier says why in the gate's words."""
    from groundwater.readiness import assess_readiness

    site = SiteMetadata(easting=-13.2294, northing=8.4831,
                        district="Western Area Rural")
    with pytest.raises(ValueError) as refused:
        mint_asset_id(site)
    message = str(refused.value)
    assert message.startswith("The easting and northing hold -13.2294 and 8.4831, "
                              "which are a longitude and a latitude in degrees "
                              "(8.48310° N, 13.22940° W), not UTM metres")
    gate = assess_readiness({"site": site, "sources": {}}, "placard")
    located = [r for r in gate.requirements if r.key == "site_located"][0]
    assert gate.state == "not_ready" and located.detail == message
    assert registry.asset_from_project({"site": site}) is None
    assert site.utm is None and site.latlon is None
    # an unsigned longitude is read as west, and the sentence says so
    unsigned = SiteMetadata(easting=13.2294, northing=8.4831)
    with pytest.raises(ValueError, match="13.2294 was read as 13.2294 W"):
        mint_asset_id(unsigned)
    # converted, the same place mints and passes
    from groundwater.geo import geographic_to_utm

    utm = geographic_to_utm(8.4831, -13.2294)
    placed = SiteMetadata(easting=round(utm.easting), northing=round(utm.northing),
                          utm_zone=utm.zone, district="Western Area Rural")
    assert mint_asset_id(placed).startswith("SL-WAR-")
    assert [r.state for r in assess_readiness(
        {"site": placed, "sources": {}}, "placard").requirements] == ["met", "met"]


# ---------------------------------------------------------------------------
# The documents
# ---------------------------------------------------------------------------

def test_the_placard_carries_a_symbol_that_reads_back(tmp_path):
    """The plate on the headworks is the whole delivery mechanism."""
    cv2 = pytest.importorskip("cv2", reason="no decoder installed")
    import numpy as np

    from groundwater.reporting.registry import AssetReportInputs, build_asset_placard

    asset = _asset(AssetEvent("2020-01-10", "commissioned"))
    asset.total_depth_m, asset.pump_type = 62.0, "India Mark II"
    out = build_asset_placard(
        AssetReportInputs(asset=asset, figures_dir=tmp_path,
                          today=date(2024, 6, 1)),
        tmp_path / "placard.docx")
    assert out.is_file()

    png = tmp_path / f"qr_{asset.asset_id}.png"
    image = cv2.imdecode(np.frombuffer(png.read_bytes(), dtype=np.uint8),
                         cv2.IMREAD_GRAYSCALE)
    text, *_ = cv2.QRCodeDetector().detectAndDecode(image)
    assert text == registry.qr_payload(asset)
    assert asset.asset_id in text


def test_the_record_says_when_nothing_is_known(tmp_path):
    from docx import Document

    from groundwater.reporting.registry import AssetReportInputs, build_asset_record

    out = build_asset_record(
        AssetReportInputs(asset=_asset(), figures_dir=tmp_path,
                          today=date(2024, 6, 1)),
        tmp_path / "record.docx")
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "Not known" in text
    assert "not the same as nothing having happened" in text


def test_the_record_counts_the_days_the_community_went_without(tmp_path):
    from docx import Document

    from groundwater.reporting.registry import AssetReportInputs, build_asset_record

    asset = _asset(AssetEvent("2020-01-10", "commissioned"),
                   AssetEvent("2023-04-02", "failure", "rising main parted"))
    out = build_asset_record(
        AssetReportInputs(asset=asset, figures_dir=tmp_path,
                          today=date(2024, 6, 1)),
        tmp_path / "record.docx")
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "Not working" in text
    assert "426 days" in text
    assert "has never been done" in text          # and what is overdue with it
    tables = Document(str(out)).tables
    body = "\n".join(cell.text for t in tables for row in t.rows
                     for cell in row.cells)
    assert "rising main parted" in body


def test_an_asset_record_is_gated_like_every_other_report(tmp_path):
    """A record of a borehole nobody located is not a certification either."""
    from docx import Document

    from groundwater.readiness import assess_readiness
    from groundwater.reporting.registry import AssetReportInputs, build_asset_record

    readiness = assess_readiness({}, "completion")
    out = build_asset_record(
        AssetReportInputs(asset=_asset(), figures_dir=tmp_path,
                          today=date(2024, 6, 1), readiness=readiness),
        tmp_path / "record.docx")
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "PROVISIONAL - NOT FOR CERTIFICATION" in text


def test_a_minted_identifier_is_always_accepted_by_the_parser():
    """Round trip every identifier a stretch of the country mints.

    The check character comes from the full 36-character alphabet, in which
    I, L, O and U mean themselves. Folding them the way the position code
    folds them - where the alphabet has no such letters, so folding is
    unambiguous - rejected one identifier in nine that this same module had
    just minted, and with it the whole maintenance history filed under it.
    """
    from groundwater.models import SiteMetadata
    from groundwater.registry import mint_asset_id, parse_asset_id

    minted = 0
    for easting in range(700000, 700400, 7):
        for northing in range(900000, 900400, 11):
            site = SiteMetadata(district="Port Loko", easting=easting,
                                northing=northing, utm_zone=28)
            asset_id = mint_asset_id(site)
            minted += 1
            assert parse_asset_id(asset_id) == asset_id, asset_id
    assert minted > 2000


def test_a_mistyped_check_character_is_still_refused():
    """Forgiving the four Crockford confusions must not forgive a wrong code."""
    from groundwater.registry import parse_asset_id

    # SL-PL-8HE2QWG-G is well formed, and SL-PL-8HE2QWG-3 is the same body
    # with the legacy check character; every other check character is not
    assert parse_asset_id("SL-PL-8HE2QWG-G") == "SL-PL-8HE2QWG-G"
    assert parse_asset_id("SL-PL-8HE2QWG-3") == "SL-PL-8HE2QWG-3"
    for wrong in "012456789ABCDEFHIJKLMNOPQRSTUVWXYZ":
        assert parse_asset_id(f"SL-PL-8HE2QWG-{wrong}") is None


def test_an_emoji_in_a_note_hashes_the_same_as_the_browser():
    """The browser hashes UTF-16 code units; Python used to hash code points.

    They agree on everything in the Basic Multilingual Plane and diverged on
    an emoji, so the same repair noted with a thumbs-up on a phone and typed
    in the office never merged. The literals are the browser engine's own
    answers (docs/js/gwt-core.js eventId)."""
    from groundwater.registry import event_id

    asset = "SL-WAR-8T4KQ2A-7"
    assert event_id(asset, "2024-01-01", "failure", "pump seized", "M") == "2024-01-01/failure/8Z6E"
    assert event_id(asset, "2024-01-01", "failure", "café", "M") == "2024-01-01/failure/GTTD"
    assert event_id(asset, "2024-01-01", "failure", "pump seized 😀", "M") == "2024-01-01/failure/1QW1"

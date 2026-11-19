"""The community handover sheet (PLAN.md step 9.1).

The sheet is a page a community keeps and plans by, so what is held here is
mostly what it must not do: promise more water than the test established,
call water safe that was not shown to be, or leave something out without a
word. The browser's port is held to the same content by the parity suite
(tests/webapp/reference/community_sheet.py); these are the rules themselves.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from groundwater.community_sheet import JERRYCAN_L, community_sheet_content, round_down
from groundwater.config import Config
from groundwater.models import SiteMetadata
from groundwater.text import phrase_table

REPO = Path(__file__).resolve().parents[1]
SITE = SiteMetadata(community="Rokel")


def analysis(safe, low=None, confidence="established"):
    return SimpleNamespace(yield_recommendation=SimpleNamespace(
        safe_yield_m3_per_h=safe, safe_yield_low_m3_per_h=low, confidence=confidence))


def verdict(state, *parameters):
    return SimpleNamespace(verdict_state=state, health_exceedances=[
        SimpleNamespace(parameter=name) for name in parameters])


def sheet(**given):
    return community_sheet_content(SITE, **given)


NOTES = phrase_table("community_sheet.builder_notes")


# ----------------------------------------------------------------- how much water


@pytest.mark.parametrize("value, rounded", [
    (0, 0), (0.4, 0), (19.99, 19), (99, 99), (100, 100), (101, 100), (1790, 1700),
    (12480, 12000), (999999, 990000),
    # arithmetic a hair under a whole number is that number: 0.57 x 1000
    (0.57 * 1000, 570), (219.99999, 210),
])
def test_an_amount_is_rounded_down_to_two_figures_and_never_up(value, rounded):
    assert round_down(value) == rounded
    assert round_down(value) <= value + 1e-9


def test_the_amount_is_the_low_end_of_the_range_not_its_middle():
    water = sheet(analysis=analysis(0.39, 0.22), hours_per_day=8)["water"]
    # 0.22 m3/h is 220 litres an hour, 1,760 a day, told as 1,700: 85 jerrycans
    assert (water["litres_per_hour"], water["litres_per_day"]) == (220, 1700)
    assert water["jerrycans_per_day"] == 85 == 1700 // JERRYCAN_L
    assert water["headline"] == "About 85 jerrycans of water a day."
    assert "1,700 litres" in water["lines"][0] and "8 hours a day" in water["lines"][0]
    # and never more than the safe yield itself would give
    assert water["litres_per_day"] <= 0.39 * 1000 * 8


def test_with_no_range_the_amount_is_the_safe_yield():
    water = sheet(analysis=analysis(1.25), hours_per_day=10)["water"]
    assert (water["litres_per_hour"], water["litres_per_day"]) == (1200, 12000)


def test_without_the_hours_the_sheet_gives_an_hour_and_says_what_is_missing():
    content = sheet(analysis=analysis(0.8))
    water = content["water"]
    assert water["headline"] == "About 40 jerrycans of water in an hour."
    assert water["litres_per_day"] is None and water["hours_per_day"] is None
    assert NOTES["no_hours"] in content["notes"]
    assert "a day" not in " ".join([water["headline"], *water["lines"]])


@pytest.mark.parametrize("hours", [0, -3, 25, float("nan"), float("inf"), "8", True, None])
def test_hours_that_are_not_a_time_of_days_worth_are_not_used(hours):
    water = sheet(analysis=analysis(0.8), hours_per_day=hours)["water"]
    assert water["litres_per_day"] is None
    assert water["headline"] == "About 40 jerrycans of water in an hour."


def test_one_hour_is_an_hour_and_half_hours_are_taken():
    one = sheet(analysis=analysis(0.8), hours_per_day=1)["water"]
    assert "for 1 hour a day" in one["lines"][0]
    half = sheet(analysis=analysis(0.8), hours_per_day=6.5)["water"]
    assert half["litres_per_day"] == 5200 and "for 6.5 hours a day" in half["lines"][0]


def test_an_indicative_yield_is_called_a_first_estimate_in_plain_words():
    content = sheet(analysis=analysis(0.39, 0.22, "indicative"), hours_per_day=8)
    water = content["water"]
    assert water["state"] == "first_estimate"
    said = " ".join(water["lines"])
    assert "first estimate" in said and "may give less" in said
    assert "indicative" not in said and "yield" not in said
    assert NOTES["first_estimate"] in content["notes"]
    # an established one says where the figure came from and no more
    established = sheet(analysis=analysis(0.39, 0.22), hours_per_day=8)["water"]
    assert established["state"] == "measured"
    assert "first estimate" not in " ".join(established["lines"])


def test_less_than_a_jerrycan_is_told_in_litres_and_almost_nothing_as_very_little():
    small = sheet(analysis=analysis(0.019))["water"]
    assert small["jerrycans_per_hour"] == 0
    assert small["headline"] == "About 19 litres of water in an hour."
    none = sheet(analysis=analysis(0.0004), hours_per_day=8)["water"]
    assert none["litres_per_hour"] == 0
    assert none["headline"] == "The pumping test found very little water in this borehole."
    # nothing to fall short of, so no line about telling the committee
    assert not any("much less" in line for line in none["lines"])


def test_no_test_and_a_test_with_no_yield_are_said_not_left_out():
    for given, note in (({}, "no_test"),
                        ({"analysis": analysis(None)}, "pending"),
                        ({"analysis": SimpleNamespace(yield_recommendation=None)}, "pending")):
        content = sheet(**given)
        assert content["water"]["state"] == "none"
        assert content["water"]["headline"] == (
            "How much water this borehole gives has not been measured yet.")
        assert NOTES[note] in content["notes"]


# ------------------------------------------------------------------ safe to drink


@pytest.mark.parametrize("state, begins", [
    ("pass", "Yes."), ("aesthetic", "Yes."), ("health_fail", "No,"),
    ("national_fail", "Not yet."), ("indeterminate", "Not known yet."),
])
def test_each_verdict_has_its_answer(state, begins):
    quality = sheet(quality=verdict(state))["quality"]
    assert quality["state"] == state and quality["headline"].startswith(begins)


def test_only_a_pass_is_told_as_safe():
    for state in ("health_fail", "national_fail", "indeterminate", "not a verdict", "none"):
        said = sheet(quality=verdict(state))["quality"]["headline"]
        assert "safe to drink" not in said or "until" in said, state
        assert not said.startswith("Yes"), state
    # no assessment at all is not safe either, and the builder is told
    content = sheet()
    assert content["quality"]["state"] == "none"
    assert content["quality"]["headline"].startswith("Not known yet.")
    assert "Treat it before you drink it" in content["quality"]["headline"]
    assert NOTES["no_quality"] in content["notes"]


def test_a_verdict_the_sheet_has_no_words_for_is_not_known():
    assert sheet(quality=verdict("something new"))["quality"]["state"] == "indeterminate"


def test_what_was_found_is_named_and_the_committee_is_who_to_ask():
    quality = sheet(quality=verdict("health_fail", "Manganese", "E. coli"))["quality"]
    assert quality["lines"] == [
        "The test found too much of this in the water: Manganese, E. coli.",
        "Ask the committee how the water is to be treated.",
    ]


# ------------------------------------------------------------ who to call, reporting


def test_the_committee_is_listed_and_lines_are_left_to_write_on():
    contacts = sheet(committee=[
        {"role": "Chairperson", "name": "  Aminata   Kamara ", "contact": "076 000 000"},
        SimpleNamespace(role="Caretaker", name="Sorie Conteh", phone="077 1"),
        {"role": "Treasurer", "name": " ", "contact": ""},
    ])["contacts"]
    assert contacts["header"] == ["Who", "Name", "Phone"]
    assert contacts["rows"][:2] == [["Chairperson", "Aminata   Kamara", "076 000 000"],
                                    ["Caretaker", "Sorie Conteh", "077 1"]]
    assert contacts["rows"][2:] == [["Pump mechanic", "", ""], ["The district water office", "", ""]]


def test_no_committee_leaves_blank_lines_and_tells_the_builder():
    content = sheet()
    assert content["contacts"]["rows"][:3] == [["", "", ""]] * 3
    assert NOTES["no_committee"] in content["notes"]


def test_the_plate_is_named_and_linked_only_where_there_is_an_address():
    config = Config()
    plain = sheet(asset_id=" SL-WAR-8FEEVKQ-T ", config=config)
    assert plain["report"]["identifier"] == "SL-WAR-8FEEVKQ-T"
    assert "SL-WAR-8FEEVKQ-T" in plain["report"]["lines"][1]
    assert plain["report"]["payload"] == "" and plain["report"]["caption"] == ""
    assert NOTES["no_address"] in plain["notes"]
    config.service.report_url = "https://water.example.org/app/"
    linked = sheet(asset_id="SL-WAR-8FEEVKQ-T", config=config)["report"]
    assert linked["payload"] == "https://water.example.org/app/#/report/SL-WAR-8FEEVKQ-T"
    assert linked["lines"][-1] == "Or scan the square below with a phone to send a report."
    assert linked["caption"] == "Scan to report a fault at borehole SL-WAR-8FEEVKQ-T"


def test_no_identifier_names_no_plate_and_no_telephone_number_is_printed():
    content = sheet()
    assert content["report"]["lines"] == ["Tell the caretaker or a committee member the same day."]
    assert NOTES["no_identifier"] in content["notes"]
    # no number is known for reports by SMS (QUESTIONS.md), so none is invented
    everything = repr(content)
    assert "SMS" not in everything and "text " not in everything.lower().replace("plain text", "")


def test_an_address_the_registry_refuses_stops_the_sheet():
    config = Config()
    config.service.report_url = "http://water.example.org/app/"
    with pytest.raises(ValueError, match="cannot go on a plate"):
        sheet(asset_id="SL-WAR-8FEEVKQ-T", config=config)
    # with no plate to name, the address is never read
    assert sheet(config=config)["report"]["payload"] == ""


# ------------------------------------------------------------------ what to keep away


def test_the_distances_are_the_separation_tables_own():
    from groundwater.supervision.checklists import load_separation_distances

    table = {row.structure: row.min_distance_m for row in load_separation_distances()}
    words = phrase_table("community_sheet.keep_structures")
    # every structure the sheet words is a row of the table, by its name
    assert set(words) <= set(table)
    keep = sheet()["keep_away"]
    assert keep["lines"] == [
        "Houses and other buildings: at least 3 metres away.",
        "Hand dug wells: at least 20 metres away.",
        "Latrines, septic tanks and soakaways: at least 20 metres away.",
        "Rubbish dumps and burial grounds: at least 1000 metres away.",
    ]
    for structure, what in words.items():
        ring = next(r for r in keep["rings"] if what in r["what"])
        assert ring["distance_m"] == table[structure]


def test_the_rings_are_nearest_first_with_one_ring_for_each_distance():
    rings = sheet()["keep_away"]["rings"]
    distances = [ring["distance_m"] for ring in rings]
    assert distances == sorted(set(distances)) == [3.0, 20.0, 1000.0]
    assert [ring["label"] for ring in rings] == ["3 m", "20 m", "1000 m"]
    assert rings[1]["what"] == ["Hand dug wells", "Latrines, septic tanks and soakaways"]


# ------------------------------------------------------------------------ the whole


def test_the_sheet_is_in_plain_words():
    content = community_sheet_content(
        SiteMetadata(community="Dr. Timbo's Residence"),
        analysis=analysis(0.39, 0.22, "indicative"), quality=verdict("health_fail", "Manganese"),
        asset_id="SL-WAR-8FEEVKQ-T", hours_per_day=8)
    printed = [content["title"]]
    for part in ("water", "quality", "report", "keep_away"):
        printed += [content[part]["heading"], *content[part].get("lines", [])]
        printed.append(content[part].get("headline", ""))
    said = " ".join(printed).lower()
    for jargon in ("yield", "indicative", "transmissivity", "drawdown", "m3", "m³",
                   "aquifer", "verdict", "exceed", "guideline", "parameter"):
        assert jargon not in said, jargon
    assert content["title"] == "Your borehole at Dr. Timbo's Residence"
    assert community_sheet_content(SiteMetadata())["title"] == "Your borehole"


def test_the_builder_is_always_told_the_sheet_is_in_english_only():
    for given in ({}, {"analysis": analysis(1.0), "quality": verdict("pass")}):
        assert sheet(**given)["notes"][-1] == NOTES["english_only"]
    # and nothing meant for the builder is in what the sheet prints
    content = sheet()
    printed = repr({k: v for k, v in content.items() if k != "notes"})
    assert not any(note in printed for note in NOTES.values())


def test_no_krio_is_in_the_catalogue():
    # PLAN.md step 9.1: a Krio version is translated and checked by native
    # speakers, and nothing is machine translated. Until there is one, the
    # catalogue holds the English alone.
    folder = REPO / "src" / "groundwater" / "data" / "text"
    assert not list(folder.glob("community_sheet*krio*"))
    assert not list(folder.glob("community_sheet.*.yaml"))


def test_the_worked_example_that_needs_most_care(sample_data):
    """Dr. Timbo's Residence: a 30-minute test and manganese over the limit."""
    from groundwater.hydraulics import analyse_pumping_test
    from groundwater.ingestion import read_pumping_workbook, read_quality_workbook
    from groundwater.quality import assess_sample

    folder = REPO / "examples" / "data" / "dr_timbo"
    test = read_pumping_workbook(folder / "dr_timbo_constant_test.xlsx")
    result = analyse_pumping_test(test)
    quality = assess_sample(read_quality_workbook(folder / "dr_timbo_water_quality.xlsx"))
    content = community_sheet_content(test.site, analysis=result, quality=quality,
                                      hours_per_day=8)
    rec = result.yield_recommendation
    assert content["water"]["state"] == "first_estimate"
    assert content["water"]["litres_per_day"] <= rec.safe_yield_low_m3_per_h * 1000 * 8
    assert content["quality"]["state"] == "health_fail"
    assert "Manganese" in content["quality"]["lines"][0]

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


def verdict(state, *parameters, national=()):
    return SimpleNamespace(
        verdict_state=state,
        health_exceedances=[SimpleNamespace(parameter=name) for name in parameters],
        national_exceedances=[SimpleNamespace(parameter=name) for name in national])


def sheet(**given):
    # with no translation installed, whatever the package comes to bundle:
    # these are the rules of the English sheet (tests/test_text_languages.py
    # holds the translated one)
    given.setdefault("translations", {})
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
    # an amount in an hour that comes to nothing in half an hour of use is
    # very little too, not "about 0 litres a day"
    part = sheet(analysis=analysis(0.0015), hours_per_day=0.5)["water"]
    assert part["litres_per_hour"] == 1 and part["litres_per_day"] == 0
    assert part["headline"] == "The pumping test found very little water in this borehole."
    assert not any("much less" in line for line in part["lines"])
    none = sheet(analysis=analysis(0.0004), hours_per_day=8)["water"]
    assert none["litres_per_hour"] == 0
    assert none["headline"] == "The pumping test found very little water in this borehole."
    # nothing to fall short of, so no line about telling the committee
    assert not any("much less" in line for line in none["lines"])


def test_the_litres_and_the_jerrycans_agree_by_the_readers_own_arithmetic():
    # 0.2198 m3/h is 210 litres an hour to two figures, which is ten
    # jerrycans and ten litres: the sheet gives the ten jerrycans and the
    # 200 litres they make
    hour = sheet(analysis=analysis(0.391, 0.2198))["water"]
    assert hour["litres_per_hour"] == 210 and hour["jerrycans_per_hour"] == 10
    assert hour["headline"] == "About 10 jerrycans of water in an hour."
    assert hour["lines"][0] == "That is 200 litres in an hour. A jerrycan holds 20 litres."
    day = sheet(analysis=analysis(0.391, 0.2198), hours_per_day=3)["water"]
    assert day["jerrycans_per_day"] == 31 and "That is 620 litres" in day["lines"][0]
    for water in (hour, day):
        printed = water["lines"][0].split(" litres")[0].split()[-1].replace(",", "")
        cans = water["jerrycans_per_day"] or water["jerrycans_per_hour"]
        assert int(printed) == cans * JERRYCAN_L


def test_a_first_estimate_gives_no_cause_it_cannot_know():
    # a yield is indicative for a short test, for one inside its
    # casing-storage time, for readings that contradict the header: the
    # sheet does not say "the test was short" of all of them
    said = " ".join(sheet(analysis=analysis(1.0, None, "indicative"))["water"]["lines"])
    assert "first estimate" in said and "short" not in said


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
        part = sheet(quality=verdict(state, "Arsenic", national=("Total coliforms",)))["quality"]
        assert "safe to drink" not in " ".join([part["headline"], *part["lines"]]), state
        assert not part["headline"].startswith("Yes"), state
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
    # a failure of the national standard names what failed it as well, and
    # is told to treat the water, as untested water is
    national = sheet(quality=verdict("national_fail", national=("Total coliforms",)))["quality"]
    assert "Treat it before you drink it" in national["headline"]
    assert national["lines"][0] == (
        "The test found too much of this in the water: Total coliforms.")


def test_failed_water_is_not_told_that_treating_it_makes_it_safe():
    # what failed may be arsenic or fluoride, which boiling and chlorine do
    # not take out: the sheet says treatment or another source, as the
    # engine's own verdict does, and names no treatment
    quality = sheet(quality=verdict("health_fail", "Arsenic"))["quality"]
    said = " ".join([quality["headline"], *quality["lines"]])
    assert "or drinking water taken from another source" in quality["headline"]
    for method in ("boil", "chlorin", "filter"):
        assert method not in said.lower()


# ------------------------------------------------------------ who to call, reporting


def test_the_committee_is_listed_and_lines_are_left_to_write_on():
    contacts = sheet(committee=[
        {"role": "Chairperson", "name": "  Aminata   Kamara ", "contact": "076 000 000"},
        SimpleNamespace(role="Caretaker", name="Sorie Conteh", phone="077 1"),
        {"role": "Treasurer", "name": " ", "contact": ""},
    ])["contacts"]
    assert contacts["header"] == ["Who", "Name", "Phone"]
    assert contacts["rows"][:2] == [["Chairperson", "Aminata Kamara", "076 000 000"],
                                    ["Caretaker", "Sorie Conteh", "077 1"]]
    assert contacts["rows"][2:] == [["Pump mechanic", "", ""], ["The district water office", "", ""]]


def test_six_members_are_printed_and_the_builder_is_told_of_the_rest():
    from groundwater.community_sheet import MAX_CONTACTS

    members = [{"role": "Member", "name": f"Person {n}", "contact": ""} for n in range(1, 11)]
    content = sheet(committee=members)
    rows = content["contacts"]["rows"]
    assert [row[1] for row in rows[:MAX_CONTACTS]] == [f"Person {n}" for n in range(1, 7)]
    assert len(rows) == MAX_CONTACTS + 2 and rows[MAX_CONTACTS][0] == "Pump mechanic"
    assert ("The sheet prints the first 6 committee members so that it stays one page; "
            "4 more were entered and are left off.") in content["notes"]
    seven = sheet(committee=members[:7])
    assert any("1 more was entered and is left off." in note for note in seven["notes"])
    assert not any("left off" in note for note in sheet(committee=members[:6])["notes"])


def test_typed_text_is_written_one_way_for_both_writers():
    from groundwater.community_sheet import sheet_text

    assert sheet_text(" Bo \u2013 Kenema  Road \u2014 East ") == "Bo - Kenema Road - East"
    assert sheet_text("Aminata\t Kamara\n") == "Aminata Kamara"
    assert sheet_text(None) == "" and sheet_text(76000000) == "" and sheet_text(float("nan")) == ""
    content = community_sheet_content(SiteMetadata(community=" Bo \u2013 Kenema  Road "),
                                      committee=[None, "Aminata", {"name": 12, "contact": 7},
                                                 {"role": "Chair \u2013 acting", "name": "A  B"}])
    assert content["title"] == "Your borehole at Bo - Kenema Road"
    assert content["contacts"]["rows"][0] == ["Chair - acting", "A B", ""]
    assert content["contacts"]["rows"][1][0] == "Pump mechanic"


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


def test_the_identifier_is_read_as_the_registry_reads_it_or_not_printed():
    config = Config()
    config.service.report_url = "https://water.example.org/app/"
    # case, spaces and a short dash are forgiven, and the plate's own
    # spelling is what is printed and what the square carries
    for typed in (" sl-war-8feevkq -t ", "SL\u2013WAR\u20138FEEVKQ\u2013T", "WAR-8FEEVKQ-T"):
        report = sheet(asset_id=typed, config=config)["report"]
        assert report["identifier"] == "SL-WAR-8FEEVKQ-T", typed
        assert report["payload"].endswith("#/report/SL-WAR-8FEEVKQ-T"), typed
    # a wrong check character, or words, is nobody's borehole: no number,
    # no square, and the builder is told
    for typed in ("SL-WAR-8FEEVKQ-X", "the borehole by the school"):
        content = sheet(asset_id=typed, config=config)
        assert content["report"]["identifier"] == "" and content["report"]["payload"] == ""
        assert content["report"]["lines"] == [
            "Tell the caretaker or a committee member the same day."]
        assert NOTES["bad_identifier"] in content["notes"]
        assert NOTES["no_identifier"] not in content["notes"]
        assert typed not in repr({k: v for k, v in content.items() if k != "notes"})


def test_a_link_too_long_for_the_square_stops_the_sheet_before_it_is_built():
    config = Config()
    config.service.report_url = "https://water.example.org/" + "a-long-path-of-the-programme/" * 3
    with pytest.raises(ValueError, match="will not fit"):
        sheet(asset_id="SL-WAR-8FEEVKQ-T", config=config)


def test_no_identifier_names_no_plate_and_no_telephone_number_is_printed():
    import re

    content = sheet()
    assert content["report"]["lines"] == ["Tell the caretaker or a committee member the same day."]
    assert NOTES["no_identifier"] in content["notes"]
    # no number is known for reports by SMS (QUESTIONS.md), so none is
    # invented: nothing the sheet prints of its own has a run of digits long
    # enough to dial, with nothing loaded or with everything
    full = community_sheet_content(
        SiteMetadata(community="Rokel"), analysis=analysis(0.39, 0.22, "indicative"),
        quality=verdict("health_fail", "Manganese"), hours_per_day=8)
    for built in (content, full):
        own = repr({k: v for k, v in built.items() if k not in ("contacts", "notes")})
        assert "SMS" not in own and not re.search(r"\d(?:[ -]?\d){6,}", own), own


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
    # what is to be kept away is said by the picture's key, ring by ring
    assert [(ring["label"], ring["what"]) for ring in keep["rings"]] == [
        ("3 m", ["Houses and other buildings"]),
        ("20 m", ["Hand dug wells", "Latrines, septic tanks and soakaways"]),
        ("1000 m", ["Rubbish dumps and burial grounds"]),
    ]
    assert "lines" not in keep
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


def test_a_sheet_from_a_bundled_example_says_so_across_its_top():
    content = sheet(analysis=analysis(0.39, 0.22), example=True)
    assert content["example"].startswith("This sheet was made from example data.")
    assert "must not be handed out" in content["example"]
    assert NOTES["example"] in content["notes"]
    assert sheet(analysis=analysis(0.39, 0.22))["example"] == ""


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


def test_another_projects_hours_and_identifier_do_not_carry_into_this_one():
    # the Streamlit app's two boxes are cleared when a project is opened, as
    # the asset record is: left behind, they would print the last borehole's
    # number on this one's sheet
    from groundwater.project_io import stale_on_load

    state = {"ho_sheet_hours": 8.0, "ho_sheet_asset": "SL-WAR-8FEEVKQ-T", "ho_tariff": "5 SLE",
             "ho_sheet_language": "zz"}
    # and its language, which is that community's (PLAN.md step 9.2)
    assert set(stale_on_load(state)) == {"ho_sheet_hours", "ho_sheet_asset",
                                         "ho_sheet_language"}
    # the file's own values come back after the clearing: all three are kept
    # with the project
    from groundwater.project_io import deserialize_project, serialize_project

    saved = deserialize_project(serialize_project({**state, "meta_community": "Rokel"}, "0.3.0"))
    assert {key: saved.get(key) for key in state} == state


# -------------------------------------------------------------------- the document


def _expected(content: dict) -> list[str]:
    """What the document says for a content, in the order it is set (the
    browser suite, tests/webapp/community_sheet.mjs, holds its writer to the
    same list)."""
    out = [content["example"]] if content["example"] else []
    out.append(content["title"])
    for part in (content["water"], content["quality"]):
        out += [part["heading"], part["headline"]]
        if part["lines"]:
            out.append(" ".join(part["lines"]))
    out += [content["contacts"]["heading"], *content["contacts"]["header"]]
    out += [cell for row in content["contacts"]["rows"] for cell in row if cell]
    out += [content["report"]["heading"], " ".join(content["report"]["lines"])]
    out += [content["keep_away"]["heading"], "Figure 1. " + content["keep_away"]["caption"]]
    return out


def _read(path) -> dict:
    import re
    import struct
    import zipfile
    from html import unescape

    with zipfile.ZipFile(path) as package:
        xml = package.read("word/document.xml").decode("utf-8")
        media = [name for name in package.namelist() if name.startswith("word/media/")]
        picture = package.read(media[0]) if media else b""
        everything = b"".join(package.read(name) for name in package.namelist())
    # a paragraph's runs joined, as a reader has them
    paragraphs = ["".join(unescape(t) for t in re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
                  for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)]
    margins = re.search(
        r'<w:pgMar w:top="(\d+)" w:right="(\d+)" w:bottom="(\d+)" w:left="(\d+)"', xml)
    return {"paragraphs": [p for p in paragraphs if p.strip()], "pictures": len(media),
            "size": struct.unpack(">II", picture[16:24]) if picture else (0, 0),
            "margins": [int(m) for m in margins.groups()] if margins else [],
            "everything": everything}


def _full(tmp_path, **more):
    from groundwater.reporting.community_sheet import build_community_sheet

    given = dict(
        analysis=analysis(0.39, 0.22, "indicative"), quality=verdict("health_fail", "Manganese"),
        committee=[{"role": "Chairperson", "name": "Aminata Kamara", "contact": "076 000 000"},
                   {"role": "Caretaker", "name": "Sorie Conteh", "contact": "077 111 222"}],
        asset_id="SL-WAR-8FEEVKQ-T", hours_per_day=8, example=True, translations={})
    given.update(more)
    site = SiteMetadata(community="Dr. Timbo's Residence")
    path = build_community_sheet(site, tmp_path / "sheet.docx", tmp_path, **given)
    return path, community_sheet_content(site, **given)


def test_the_document_says_the_content_whole_and_in_order(tmp_path):
    path, content = _full(tmp_path)
    read = _read(path)
    want = _expected(content)
    from groundwater.verification import document_record

    # the content and nothing after it
    assert read["paragraphs"] == want
    assert read["paragraphs"][0].startswith("This sheet was made from example data.")
    # nothing meant for the builder is printed
    assert not any(note in " ".join(read["paragraphs"]) for note in NOTES.values())
    # and it is issued as its own kind of document, kept with the borehole's
    assert document_record(path.read_bytes())["kind"] == "community_sheet"
    from groundwater.verification import BOREHOLE_KINDS

    assert "community_sheet" in BOREHOLE_KINDS


def test_the_document_has_one_picture_and_narrow_margins(tmp_path):
    from groundwater.reporting import community_sheet as writer

    read = _read(_full(tmp_path)[0])
    assert read["pictures"] == 1
    # 1.5 cm in twentieths of a point, where the reports keep 2.5 cm
    assert len(read["margins"]) == 4 and all(840 <= margin <= 860 for margin in read["margins"])
    width, height = read["size"]
    assert abs(width / height - writer.PICTURE_WIDTH_CM / writer.PICTURE_HEIGHT_CM) < 0.02


def test_the_picture_carries_the_square_only_where_there_is_a_link(tmp_path):
    from groundwater.reporting import community_sheet as writer

    config = Config()
    config.service.report_url = "https://water.example.org/app/"
    path, content = _full(tmp_path, config=config)
    read = _read(path)
    width, height = read["size"]
    assert read["pictures"] == 1 and content["report"]["payload"]
    assert abs(width / height - writer.PICTURE_WIDTH_SCAN_CM / writer.PICTURE_HEIGHT_CM) < 0.02
    assert "Or scan the square below" in " ".join(read["paragraphs"])
    # the square is where the sheet says it is: black modules on the right
    from PIL import Image

    with Image.open(tmp_path / "community_sheet_picture.png") as picture:
        grey = picture.convert("L")
        right = grey.crop((int(grey.width * 0.8), 0, grey.width, int(grey.height * 0.6)))
        left = grey.crop((int(grey.width * 0.4), 0, int(grey.width * 0.75), grey.height))

    def black(image) -> float:
        return sum(image.histogram()[:40]) / (image.width * image.height)

    assert black(right) > 0.15 > black(left)


def test_words_are_wrapped_at_spaces_as_the_browser_wraps_them():
    from groundwater.reporting.community_sheet import wrap_words

    assert wrap_words("Scan to report a fault at borehole SL-WAR-8FEEVKQ-T", 24) == [
        "Scan to report a fault", "at borehole", "SL-WAR-8FEEVKQ-T"]
    assert wrap_words("averyveryverylongwordindeed x", 10) == ["averyveryverylongwordindeed", "x"]
    assert wrap_words("", 10) == [""]


def test_the_fullest_sheet_is_one_page(tmp_path):
    """Counted by LibreOffice where it is installed, which lays a page out
    much as Word does; CI has none, and there the layout is held by the
    margins, the single picture and its size above."""
    import shutil
    import subprocess

    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office or not shutil.which("pdfinfo"):
        pytest.skip("no LibreOffice to count pages with")
    config = Config()
    config.service.report_url = "https://water.example.org/app/"
    # ten members entered: the sheet prints six, which is what keeps it a page
    committee = [{"role": "Committee member", "name": f"Aminata Kamara the {n}th",
                  "contact": "076 000 000"} for n in range(1, 11)]
    path, _ = _full(tmp_path, committee=committee, config=config,
                    quality=verdict("health_fail", "Manganese", "Iron", "E. coli"))
    subprocess.run([office, "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path),
                    str(path)], capture_output=True, timeout=300, check=True)
    info = subprocess.run(["pdfinfo", str(tmp_path / "sheet.pdf")], capture_output=True,
                          text=True, check=True).stdout
    assert "Pages:           1" in info, info

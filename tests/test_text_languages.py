"""Strings that can be translated (PLAN.md step 9.2).

English is the working language. What a community reads (today the
community handover sheet) can be said in another language once a translation
of it is put beside the English, and the plan is exact about what kind of
translation that is: made and checked by native speakers, never by machine.
So what is held here is mostly what the mechanism must refuse: a translation
nobody checked, one that drops or changes a number, one that translates what
is not there. No translation is bundled, and none is written here: the tests
make one up, out of the English with a mark in front of each sentence.

The browser's port is held to the same rules by the parity suite
(tests/webapp/reference/text_languages.py and community_sheet.py).
"""

import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from groundwater.community_sheet import (
    BUILDER_ENTRIES,
    community_sheet_content,
    sheet_entries,
)
from groundwater.config import Config
from groundwater.models import SiteMetadata
from groundwater.text import (
    Speaker,
    languages,
    phrase,
    phrase_table,
    read_translations,
    text_catalogue,
    translation_problems,
    translations,
    untranslated,
)

REPO = Path(__file__).resolve().parents[1]
TEXT = REPO / "src" / "groundwater" / "data" / "text"
SITE = SiteMetadata(community="Rokel")

#: Put in front of every made-up sentence: two letters Krio is written with
#: and English is not, so that a sentence left in English is seen at once.
MARK = "ɛɔ "

WHO = {"name": "Zedish", "translated_by": "A. Translator", "checked_by": "B. Checker"}

ENGLISH = {"sheet": {
    "title": "Your borehole at {place}",
    "amount": "About {cans:num} {cans:plural:jerrycan|jerrycans}, {hours:g} hours.",
    "plain": "Tell the caretaker.",
    "answers": {"yes": "Yes.", "no": "No."},
}}


def held(text=None, code="zz", **facts):
    return {code: {"language": {**WHO, **facts}, "text": {"sheet": text or {}}}}


def marked(only=None) -> dict:
    """A translation of the community sheet made of its own English with the
    mark in front: every entry the sheet prints, or only those named."""
    english = text_catalogue()["community_sheet"]
    text = {}
    for ident in sheet_entries():
        key = ident.split(".", 1)[1]
        if only is not None and key not in only:
            continue
        source = english[key]
        text[key] = ({row: MARK + words for row, words in source.items()}
                     if isinstance(source, dict) else MARK + source)
    return {"zz": {"language": dict(WHO), "text": {"community_sheet": text}}}


def analysis(safe, low=None, confidence="established"):
    return SimpleNamespace(yield_recommendation=SimpleNamespace(
        safe_yield_m3_per_h=safe, safe_yield_low_m3_per_h=low, confidence=confidence))


def verdict(state, *parameters):
    return SimpleNamespace(
        verdict_state=state, national_exceedances=[],
        health_exceedances=[SimpleNamespace(parameter=name) for name in parameters])


COMMITTEE = [{"role": "Chairperson", "name": "Aminata Kamara", "contact": "076 000 000"}]


def linked() -> Config:
    config = Config()
    config.service.report_url = "https://water.example.org/app/"
    return config


def printed(content: dict) -> list[str]:
    """Every string of a content that is printed on the sheet and comes from
    the catalogue (so not a committee member's row, which is as typed)."""
    out = [content["title"], content["example"]]
    for part in (content["water"], content["quality"], content["report"], content["keep_away"]):
        out += [part["heading"], *part["lines"]]
    out += [content["water"]["headline"], content["quality"]["headline"]]
    out += [content["contacts"]["heading"], *content["contacts"]["header"]]
    # the roles left to be written in beside, after the committee's rows
    out += [row[0] for row in content["contacts"]["rows"][-2:]]
    out += [content["report"]["caption"], content["keep_away"]["centre"],
            content["keep_away"]["caption"]]
    for ring in content["keep_away"]["rings"]:
        out += [ring["label"], *ring["what"]]
    return [text for text in out if text]


# ------------------------------------------------- what is refused, and why


def test_a_translation_nobody_checked_is_not_offered():
    # PLAN.md: translated and checked by native speakers. A folder that does
    # not name both is not offered, whatever it holds.
    good = {"plain": "Tɛl di kiateka."}
    assert [language["code"] for language in languages(held(good), ENGLISH)] == ["zz"]
    for missing in ("name", "translated_by", "checked_by"):
        for value in (None, "", "   ", 7):
            facts = {missing: value}
            assert translation_problems("zz", held(good, **facts), ENGLISH) == [
                f"language.yaml does not say {missing}"], (missing, value)
            assert languages(held(good, **facts), ENGLISH) == []
    nothing = {"zz": {"text": {"sheet": good}}}
    assert len(translation_problems("zz", nothing, ENGLISH)) == 3
    with pytest.raises(ValueError, match="cannot be used: language.yaml does not say checked_by"):
        Speaker("zz", held(good, checked_by=""), ENGLISH)


def test_a_sentence_keeps_every_value_the_english_has():
    # a translation that drops the number of jerrycans, or prints it another
    # way, would hand a community a sheet that says something else
    def problems(amount):
        return translation_problems("zz", held({"amount": amount}), ENGLISH)

    reason = ("sheet.amount does not take the values the English takes (cans, hours), "
              "each in a format it uses")
    wrong = [reason]
    assert problems("{cans:num} {cans:plural:jɛriken|jɛriken dɛm} {hours:g}") == []
    # the order is the translation's own, a value may be said twice, and of
    # the two ways English writes the count either may be used alone
    assert problems("{hours:g} awa, {cans:num}, {cans:num}") == []
    assert problems("{cans:plural:wan|bok} {hours:g}") == []
    assert problems("{cans:num} jɛriken") == wrong           # the hours are gone
    assert problems("{cans:num} {hours:g} {days:g}") == wrong     # a value English lacks
    assert problems("{cans:g} {hours:g}") == wrong                # 1,200 printed as 1200
    assert problems("{cans:num} {hours:.1f}") == wrong
    assert problems("{cans:num} {hours:plural:awa|awa dɛm}") == wrong
    assert problems("{cans:num} {hours}") == wrong
    assert problems("{cans:num} { hours") == ["sheet.amount has a lone brace"]
    # a sentence with no values takes none
    assert translation_problems("zz", held({"plain": "Tɛl {who}."}), ENGLISH) == [
        "sheet.plain does not take the values the English takes (none), each in a format it uses"]


def test_a_translation_translates_only_what_is_there():
    def problems(text):
        return translation_problems("zz", held(text), ENGLISH)

    assert problems({"extra": "x"}) == ["sheet.extra is not an entry of the English"]
    assert problems({"answers": "Yes or no."}) == [
        "sheet.answers is a table in English and a sentence here"]
    assert problems({"plain": {"a": "b"}}) == [
        "sheet.plain is a sentence in English and not one here"]
    assert problems({"plain": 12}) == ["sheet.plain is a sentence in English and not one here"]
    assert problems({"answers": {"maybe": "x"}}) == [
        "sheet.answers[maybe] is not a row of the English table"]
    # a table row is plain text: it is printed as it stands, braces and all
    assert problems({"answers": {"yes": "{x}"}}) == ["sheet.answers[yes] is not plain text"]
    assert problems({"plain": " ", "answers": {"no": ""}}) == [
        "sheet.answers[no] is blank", "sheet.plain is blank"]
    other = {"zz": {"language": dict(WHO), "text": {"elsewhere": {"plain": "x"}, "sheet": ["x"]}}}
    assert translation_problems("zz", other, ENGLISH) == [
        "elsewhere.yaml translates a file English does not have",
        "sheet.yaml is not a list of entries"]


def test_a_folder_is_named_as_a_language_is():
    for code in ("Kri", "k", "kri2", "krio-sl", "toolongcode"):
        problems = translation_problems(code, held({}, code=code), ENGLISH)
        assert problems == [f"'{code}' is not a language's code (two to eight small letters)"]
        assert languages(held({}, code=code), ENGLISH) == []
    assert translation_problems("kri", held({}, code="kri"), ENGLISH) == []
    assert translation_problems("qq", held({}), ENGLISH) == ["there is no translation 'qq'"]


def test_what_is_not_translated_yet_is_no_fault():
    # left out, or named and left empty as a translator's working copy has it
    for text in ({}, {"title": None, "answers": None}, {"answers": {"yes": None}}):
        assert translation_problems("zz", held(text), ENGLISH) == []
    empty_file = {"zz": {"language": dict(WHO), "text": {"sheet": None}}}
    assert translation_problems("zz", empty_file, ENGLISH) == []
    assert Speaker("zz", empty_file, ENGLISH).phrase("sheet.plain") == "Tell the caretaker."


def test_languages_are_offered_by_name():
    several = {**held({}, code="zc", name="Mende"), **held({}, code="za", name=" Temne "),
               **held({}, code="zb", name="Krio"), **held({}, code="zd", name="Krio"),
               **held({"extra": "x"}, code="ze", name="Faulty")}
    assert [(language["code"], language["name"]) for language in languages(several, ENGLISH)] == [
        ("zb", "Krio"), ("zd", "Krio"), ("zc", "Mende"), ("za", "Temne")]
    assert languages({}, ENGLISH) == []


# ----------------------------------------------------------- what is spoken


def test_a_speaker_says_what_it_has_and_english_for_the_rest():
    say = Speaker("zz", held({"plain": "Tɛl di kiateka.", "answers": {"no": "Nɔ."}}),
                  ENGLISH)
    assert say.language == {"code": "zz", **WHO}
    assert say.phrase("sheet.plain") == "Tɛl di kiateka."
    assert say.fell_back == []
    assert say.phrase("sheet.title", place="Rokel") == "Your borehole at Rokel"
    assert say.phrase_table("sheet.answers") == {"yes": "Yes.", "no": "Nɔ."}
    # each entry it had to say in English, once, in the order it was asked
    say.phrase("sheet.title", place="Kuntolo")
    assert say.fell_back == ["sheet.title", "sheet.answers"]


def test_a_speaker_fills_a_translated_sentence_as_english_is_filled():
    text = {"amount": "{hours:g} awa: {cans:num} {cans:plural:jɛriken|jɛriken dɛm}."}
    say = Speaker("zz", held(text), ENGLISH)
    assert say.phrase("sheet.amount", cans=1, hours=6.5) == "6.5 awa: 1 jɛriken."
    assert say.phrase("sheet.amount", cans=1200, hours=8) == "8 awa: 1,200 jɛriken dɛm."
    with pytest.raises(KeyError):
        say.phrase("sheet.amount", cans=1)
    with pytest.raises(KeyError):
        say.phrase("sheet.nothing")
    with pytest.raises(TypeError):
        say.phrase("sheet.answers")
    with pytest.raises(TypeError):
        say.phrase_table("sheet.plain")


def test_english_is_spoken_with_no_language_and_keeps_no_count():
    say = Speaker("", held({"plain": "Tɛl di kiateka."}), ENGLISH)
    assert say.code == "" and say.language == {}
    assert say.phrase("sheet.plain") == "Tell the caretaker."
    assert say.fell_back == []
    # and over the catalogue itself it is phrase() and phrase_table()
    real = Speaker()
    assert real.phrase("community_sheet.title", place="Rokel") == phrase(
        "community_sheet.title", place="Rokel")
    assert real.phrase_table("community_sheet.quality") == phrase_table("community_sheet.quality")


def test_what_is_left_to_translate_is_told_entry_by_entry():
    text = {"plain": "x", "title": None, "answers": {"no": "Nɔ."}}
    assert untranslated("zz", ["sheet.title", "sheet.plain", "sheet.answers", "sheet.amount"],
                        held(text), ENGLISH) == ["sheet.title", "sheet.answers[yes]", "sheet.amount"]
    assert untranslated("qq", ["sheet.plain"], held(text), ENGLISH) == ["sheet.plain"]


# ------------------------------------------------- the files a translator writes


def write_translation(folder: Path, code: str, facts: dict | None, **files) -> None:
    (folder / code).mkdir(parents=True)
    if facts is not None:
        (folder / code / "language.yaml").write_text(
            yaml.safe_dump(facts, allow_unicode=True), encoding="utf-8")
    for name, entries in files.items():
        (folder / code / f"{name}.yaml").write_text(
            entries if isinstance(entries, str) else yaml.safe_dump(entries, allow_unicode=True),
            encoding="utf-8")


def test_a_translation_is_a_folder_beside_the_english(tmp_path):
    write_translation(tmp_path, "zz", WHO,
                      community_sheet={"title": "Una bɔrɔl na {place}"}, verification="")
    write_translation(tmp_path, "zy", None, community_sheet="# nothing yet\n")
    (tmp_path / "zz" / "notes.txt").write_text("not a catalogue file", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "community_sheet.yaml").write_text("title: English\n", encoding="utf-8")
    read = read_translations(tmp_path)
    assert read == {
        "zy": {"language": {}, "text": {"community_sheet": None}},
        "zz": {"language": WHO,
               "text": {"community_sheet": {"title": "Una bɔrɔl na {place}"},
                        "verification": None}},
    }
    assert [language["code"] for language in languages(read)] == ["zz"]
    content = community_sheet_content(SITE, language="zz", translations=read)
    assert content["title"] == "Una bɔrɔl na Rokel"


def test_every_bundled_translation_can_be_offered():
    # the rule for whatever is put in data/text from here on: a translation
    # in the package names who made it and who checked it, and has no fault.
    # A folder that fails this is not offered by either app; it should not
    # be in the package at all.
    folders = sorted(p.name for p in TEXT.iterdir()
                     if p.is_dir() and not p.name.startswith(("_", ".")))
    assert sorted(translations()) == folders
    for code in folders:
        assert translation_problems(code) == [], code
    assert [language["code"] for language in languages()] == sorted(
        folders, key=lambda code: (translations()[code]["language"]["name"].strip(), code))


def test_the_command_line_says_what_a_translation_lacks(tmp_path, capsys):
    from groundwater.cli import main

    assert main(["translation"]) == (0 if all(
        not translation_problems(code) for code in translations()) else 1)
    capsys.readouterr()

    assert main(["translation", "--folder", str(tmp_path)]) == 0
    assert "English only" in capsys.readouterr().out

    whole = marked()["zz"]["text"]["community_sheet"]
    write_translation(tmp_path, "zz", WHO, community_sheet=whole)
    write_translation(tmp_path, "zy", {**WHO, "name": "Ypsilonian"},
                      community_sheet={"title": "{place}", "quality": {"pass": "Yɛs."}})
    write_translation(tmp_path, "zx", {"name": "Unchecked", "translated_by": "A"},
                      community_sheet={"title": "No place"})
    assert main(["translation", "zz", "--folder", str(tmp_path)]) == 0
    said = capsys.readouterr().out
    assert "zz: Zedish, translated by A. Translator, checked by B. Checker" in said
    assert "translated in full" in said

    assert main(["translation", "zy", "--folder", str(tmp_path)]) == 0
    said = capsys.readouterr().out
    left = len(sheet_entries()) - 2 + len(phrase_table("community_sheet.quality")) - 1
    assert f"prints {left} of its parts in English" in said
    assert "- community_sheet.quality[health_fail]" in said
    assert "- community_sheet.water_heading" in said
    assert "community_sheet.title\n" not in said and "quality[pass]" not in said
    # nothing for the builder is asked of a translator
    assert "builder_notes" not in said and "community_sheet.about" not in said

    assert main(["translation", "zx", "--folder", str(tmp_path)]) == 1
    said = capsys.readouterr().out
    assert "zx: cannot be offered" in said and "does not say checked_by" in said
    assert "community_sheet.title does not take the values" in said

    # every one is told, and one that cannot be offered fails the lot
    assert main(["translation", "--folder", str(tmp_path)]) == 1
    said = capsys.readouterr().out
    assert said.index("zx:") < said.index("zy:") < said.index("zz:")
    assert main(["translation", "qq", "--folder", str(tmp_path)]) == 1
    assert main(["translation", "--folder", str(tmp_path / "nowhere")]) == 1


# ------------------------------------------------------- the sheet, translated


FULL = dict(analysis=analysis(0.39, 0.22), quality=verdict("pass"), committee=COMMITTEE,
            asset_id="SL-WAR-8FEEVKQ-T", hours_per_day=8)

#: Sheets that between them print every entry the sheet has.
EVERY_SHEET = [
    {},
    dict(FULL, config=linked()),
    dict(FULL, hours_per_day=None, example=True),
    dict(analysis=analysis(1.25, None, "indicative"), quality=verdict("health_fail", "Manganese"),
         hours_per_day=1),
    dict(analysis=analysis(0.019), hours_per_day=6.5, quality=verdict("aesthetic")),
    dict(analysis=analysis(0.019), quality=verdict("national_fail")),
    dict(analysis=analysis(0.0004), quality=verdict("indeterminate")),
    # less than a jerrycan in a day
    dict(analysis=analysis(0.012), hours_per_day=1.5),
]


def test_a_translated_sheet_has_no_english_left_in_it():
    for given in EVERY_SHEET:
        site = SiteMetadata(community="" if given.get("example") else "Rokel")
        content = community_sheet_content(site, language="zz", translations=marked(), **given)
        english = community_sheet_content(site, translations=marked(), **given)
        assert content["fell_back"] == [], given
        strings = printed(content)
        assert all(text.startswith(MARK) for text in strings), [
            text for text in strings if not text.startswith(MARK)]
        # the same sheet, sentence for sentence: every figure is where it was
        # (a line of what to keep away is made of two translated parts, and
        # carries the mark of each)
        assert [text.replace(MARK, "") for text in strings] == printed(english)
        for key in ("litres_per_hour", "jerrycans_per_hour", "litres_per_day",
                    "jerrycans_per_day", "state"):
            assert content["water"][key] == english["water"][key]
        assert content["quality"]["state"] == english["quality"]["state"]
        assert content["report"]["payload"] == english["report"]["payload"]
        # what was typed is printed as typed
        assert content["contacts"]["rows"][:-2] == english["contacts"]["rows"][:-2]


def test_the_entries_a_translator_is_asked_for_are_the_ones_the_sheet_prints():
    # asked of an empty translation, every entry the sheet prints falls back:
    # between them the sheets above ask for each entry sheet_entries() names
    # and for nothing else, so the list a translator works from is the sheet
    nothing = {"zz": {"language": dict(WHO), "text": {}}}
    asked = set()
    for given in EVERY_SHEET:
        site = SiteMetadata(community="" if given.get("example") else "Rokel")
        asked |= set(community_sheet_content(
            site, language="zz", translations=nothing, **given)["fell_back"])
    assert asked == set(sheet_entries())
    catalogue = text_catalogue()["community_sheet"]
    assert set(BUILDER_ENTRIES) <= set(catalogue)
    assert len(sheet_entries()) == len(catalogue) - len(BUILDER_ENTRIES)


def test_the_builder_is_told_whose_translation_it_is_in_english():
    notes = phrase_table("community_sheet.builder_notes")
    content = community_sheet_content(SITE, language="zz", translations=marked())
    assert content["language"] == {"code": "zz", **WHO}
    assert content["notes"][-1] == (
        "The sheet is in Zedish: translated by A. Translator, checked by B. Checker.")
    # the notes are the builder's, and stay in English
    assert notes["no_test"] in content["notes"] and notes["no_quality"] in content["notes"]
    assert not any(MARK in note for note in content["notes"])
    assert notes["english_only"] not in content["notes"]
    too_many = community_sheet_content(
        SITE, language="zz", translations=marked(),
        committee=[{"role": "Member", "name": f"Person {n}"} for n in range(9)])
    assert any(note.startswith("The sheet prints the first 6") for note in too_many["notes"])


def test_a_part_translated_sheet_says_how_much_is_english():
    part = marked(only={"title", "water_none"})
    content = community_sheet_content(SITE, language="zz", translations=part)
    assert content["title"] == MARK + "Your borehole at Rokel"
    assert content["water"]["headline"].startswith(MARK)
    assert content["quality"]["headline"].startswith("Not known yet.")
    count = len(content["fell_back"])
    assert count > 5 and "community_sheet.title" not in content["fell_back"]
    assert content["notes"][-1] == (
        f"{count} parts of this sheet are not fully in Zedish yet. What the translation "
        "has no words for is printed in English.")
    one = marked()
    del one["zz"]["text"]["community_sheet"]["keep_caption"]
    content = community_sheet_content(SITE, language="zz", translations=one)
    assert content["fell_back"] == ["community_sheet.keep_caption"]
    assert content["notes"][-1].startswith("1 part of this sheet is not fully in Zedish yet.")


def test_english_is_the_sheet_unless_a_language_is_asked_for():
    notes = phrase_table("community_sheet.builder_notes")
    plain = community_sheet_content(SITE)
    offered = community_sheet_content(SITE, translations=marked())
    assert offered["language"] == {} and offered["fell_back"] == []
    assert not any(MARK in text for text in printed(offered))
    # with a translation on offer the builder chose English, and is not told
    # that none exists; with none, they are
    assert notes["english_only"] not in offered["notes"]
    assert plain["notes"][-1] == notes["english_only"]
    assert {**offered, "notes": None} == {**plain, "notes": None}


def test_a_language_that_is_not_offered_stops_the_sheet():
    unchecked = marked()
    unchecked["zz"]["language"].pop("checked_by")
    with pytest.raises(ValueError, match="'zz' cannot be used: language.yaml does not say"):
        community_sheet_content(SITE, language="zz", translations=unchecked)
    with pytest.raises(ValueError, match="there is no translation 'kri'"):
        community_sheet_content(SITE, language="kri", translations=marked())
    faulty = marked()
    faulty["zz"]["text"]["community_sheet"]["water_day"] = "Plenty of water."
    with pytest.raises(ValueError, match="water_day does not take the values"):
        community_sheet_content(SITE, language="zz", translations=faulty)


# ---------------------------------------------------------------- the document


def test_the_document_is_written_in_the_language(tmp_path):
    from test_community_sheet import _expected, _read

    from groundwater.reporting.community_sheet import build_community_sheet

    given = dict(FULL, config=linked(), language="zz", translations=marked())
    with warnings.catch_warnings():
        # a letter the picture's font has no shape for is drawn as a box,
        # and matplotlib says so in a warning: none is wanted here
        warnings.simplefilter("error")
        path = build_community_sheet(SITE, tmp_path / "sheet.docx", tmp_path, **given)
    content = community_sheet_content(SITE, **given)
    read = _read(path)
    assert read["paragraphs"] == _expected(content)
    typed = {cell for row in content["contacts"]["rows"][:-2] for cell in row}
    for paragraph in read["paragraphs"]:
        if paragraph in typed:
            continue
        # the word before the caption is the reports' own, in every language
        assert paragraph.removeprefix("Figure 1. ").startswith(MARK), paragraph
    assert read["pictures"] == 1
    # and the same borehole's English sheet is the same sheet otherwise
    english = _read(build_community_sheet(SITE, tmp_path / "english.docx", tmp_path,
                                          **{**given, "language": ""}))
    assert len(english["paragraphs"]) == len(read["paragraphs"])
    assert english["margins"] == read["margins"] and english["size"] == read["size"]

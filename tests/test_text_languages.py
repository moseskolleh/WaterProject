"""Strings that can be translated (PLAN.md step 9.2).

English is the working language. What a community reads (today the
community handover sheet) can be said in another language once a translation
of it is put beside the English, and the plan is exact about what kind of
translation that is: made and checked by native speakers, never by machine.
So what is held here is mostly what the mechanism must refuse: a translation
nobody checked, one that drops or changes a number, one that translates what
is not there. No translation is bundled, and none is written here: where a
whole translated sheet is wanted it is the English with a mark in front of
each sentence, and every other word of a "translation" below is invented.

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
    same_as_english,
    text_catalogue,
    translation_problems,
    translations,
    untranslated,
)

REPO = Path(__file__).resolve().parents[1]
TEXT = REPO / "src" / "groundwater" / "data" / "text"
SITE = SiteMetadata(community="Rokel")

#: Put in front of every sentence of the made-up sheet: two letters that
#: languages of Sierra Leone are written with and English is not, so that a
#: sentence left in English is seen at once.
MARK = "ɛɔ "

WHO = {"name": "Zedish", "translated_by": "A. Translator", "checked_by": "B. Checker"}

ENGLISH = {"sheet": {
    "title": "Your borehole at {place}",
    "amount": "About {cans:num} {cans:plural:jerrycan|jerrycans}, {hours:g} hours.",
    "plain": "Tell the caretaker.",
    "answers": {"yes": "Yes.", "no": "No."},
}}

WRONG = "does not take the values the English takes ({}), each written as the English writes it"


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
    for part in (content["water"], content["quality"], content["report"]):
        out += [part["heading"], *part["lines"]]
    out += [content["water"]["headline"], content["quality"]["headline"]]
    out += [content["contacts"]["heading"], *content["contacts"]["header"]]
    # the roles left to be written in beside, after the committee's rows
    out += [row[0] for row in content["contacts"]["rows"][-2:]]
    out += [content["report"]["caption"], content["keep_away"]["heading"],
            content["keep_away"]["centre"], content["keep_away"]["caption"]]
    for ring in content["keep_away"]["rings"]:
        out += [ring["label"], *ring["what"]]
    return [text for text in out if text]


# ------------------------------------------------- what is refused, and why


def test_a_translation_nobody_checked_is_not_offered():
    # PLAN.md: translated and checked by native speakers. A folder that does
    # not name both is not offered, whatever it holds.
    good = {"plain": "Wug zub frimo."}
    assert [language["code"] for language in languages(held(good), ENGLISH)] == ["zz"]
    for missing in ("name", "translated_by", "checked_by"):
        # nothing, blank, white space of any kind, not text
        for value in (None, "", "   ", 7, "\x85", "﻿", " \x1f"):
            facts = {missing: value}
            assert translation_problems("zz", held(good, **facts), ENGLISH) == [
                f"language.yaml does not say {missing}"], (missing, value)
            assert languages(held(good, **facts), ENGLISH) == []
    nothing = {"zz": {"text": {"sheet": good}}}
    assert len(translation_problems("zz", nothing, ENGLISH)) == 3
    with pytest.raises(ValueError, match="cannot be used: language.yaml does not say checked_by"):
        Speaker("zz", held(good, checked_by=""), ENGLISH)


def test_a_sentence_keeps_every_number_the_english_has():
    # a translation that drops the number of jerrycans, or prints it another
    # way, would hand a community a sheet that says something else
    def problems(amount):
        return translation_problems("zz", held({"amount": amount}), ENGLISH)

    wrong = ["sheet.amount " + WRONG.format("cans, hours")]
    assert problems("{cans:num} {cans:plural:glorp|glorps} {hours:g}") == []
    # the order is the translation's own and a value may be said twice
    assert problems("{hours:g} wug, {cans:num}, {cans:num} {cans:plural:a|b}") == []
    # the word that agrees with the count may be left out, by a language
    # that has no need of it ...
    assert problems("{cans:num} glorp, {hours:g} wug") == []
    # ... the count itself may not: "about jerrycans a day"
    assert problems("{cans:plural:glorp|glorps} {hours:g}") == wrong
    assert problems("{cans:num} glorps") == wrong                 # the hours are gone
    assert problems("{cans:num} {hours:g} {days:g}") == wrong     # a value English lacks
    assert problems("{cans:g} {hours:g}") == wrong                # 1,200 printed as 1200
    assert problems("{cans:num} {cans:g} {hours:g}") == wrong     # and both ways
    assert problems("{cans:num} {hours:.1f}") == wrong
    assert problems("{cans:num} {hours:g} {hours:plural:wug|wugs}") == wrong
    assert problems("{cans:num} {hours}") == wrong
    assert problems("{cans:num} {hours:g} {__proto__}") == wrong
    assert problems("{cans:num} { hours") == ["sheet.amount has a lone brace"]
    # a figure of another script is not a format
    assert problems("{cans:num} {hours:.١f}") == ["sheet.amount has a lone brace"]
    # a sentence with no values takes none
    assert translation_problems("zz", held({"plain": "Wug {who}."}), ENGLISH) == [
        "sheet.plain " + WRONG.format("none")]


def test_the_headline_of_the_real_sheet_cannot_lose_its_number():
    # the two sentences a community plans by, on the catalogue itself
    for key in ("water_day", "water_hour"):
        text = {"community_sheet": {key: "Zub {cans:plural:glorp|glorps} frim."}}
        faulty = {"zz": {"language": dict(WHO), "text": text}}
        assert translation_problems("zz", faulty) == [f"community_sheet.{key} " + WRONG.format("cans")]
        assert languages(faulty) == []
        with pytest.raises(ValueError, match="does not take the values"):
            community_sheet_content(SITE, analysis=analysis(1.5), hours_per_day=8,
                                    language="zz", translations=faulty)


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
    assert problems({"answers": {"yes": "}"}}) == ["sheet.answers[yes] is not plain text"]
    assert problems({"plain": " ", "answers": {"no": ""}}) == [
        "sheet.answers[no] is blank", "sheet.plain is blank"]
    # blank is blank whichever white space it is made of
    assert problems({"plain": "﻿", "answers": {"no": "\x85\x1c"}}) == [
        "sheet.answers[no] is blank", "sheet.plain is blank"]
    other = {"zz": {"language": dict(WHO), "text": {"elsewhere": {"plain": "x"}, "sheet": ["x"]}}}
    assert translation_problems("zz", other, ENGLISH) == [
        "elsewhere.yaml translates a file English does not have",
        "sheet.yaml is not a list of entries"]


def test_a_folder_is_named_as_a_language_is():
    for code in ("Kri", "k", "kri2", "krio-sl", "ninechars"):
        problems = translation_problems(code, held({}, code=code), ENGLISH)
        assert problems == [f"'{code}' is not a language's code (two to eight small letters)"]
        assert languages(held({}, code=code), ENGLISH) == []
    for code in ("kr", "kri", "eightchr"):
        assert translation_problems(code, held({}, code=code), ENGLISH) == []
    assert translation_problems("qq", held({}), ENGLISH) == ["there is no translation 'qq'"]


def test_what_is_not_translated_yet_is_no_fault():
    # left out, or named with nothing after it as a translator's working
    # copy has it
    for text in ({}, {"title": None, "answers": None}, {"answers": {"yes": None}}):
        assert translation_problems("zz", held(text), ENGLISH) == []
    empty_file = {"zz": {"language": dict(WHO), "text": {"sheet": None}}}
    assert translation_problems("zz", empty_file, ENGLISH) == []
    assert Speaker("zz", empty_file, ENGLISH).phrase("sheet.plain") == "Tell the caretaker."


def test_languages_are_offered_by_name():
    several = {**held({}, code="zc", name="Mende"), **held({}, code="za", name=" Temne "),
               **held({}, code="zb", name="Krio"), **held({}, code="zd", name="﻿Krio\x85"),
               **held({"extra": "x"}, code="ze", name="Faulty")}
    assert [(language["code"], language["name"]) for language in languages(several, ENGLISH)] == [
        ("zb", "Krio"), ("zd", "Krio"), ("zc", "Mende"), ("za", "Temne")]
    assert languages({}, ENGLISH) == []


# ----------------------------------------------------------- what is spoken


def test_a_speaker_says_what_it_has_and_english_for_the_rest():
    say = Speaker("zz", held({"plain": "Wug zub frimo.", "answers": {"no": "Nɔb."}}),
                  ENGLISH)
    assert say.language == {"code": "zz", **WHO}
    assert say.phrase("sheet.plain") == "Wug zub frimo."
    assert say.fell_back == []
    assert say.phrase("sheet.title", place="Rokel") == "Your borehole at Rokel"
    assert say.phrase_table("sheet.answers") == {"yes": "Yes.", "no": "Nɔb."}
    # each entry it had to say in English, once, in the order it was asked
    say.phrase("sheet.title", place="Kuntolo")
    assert say.fell_back == ["sheet.title", "sheet.answers"]


def test_one_row_asked_for_is_counted_by_itself():
    # a table one row of which is printed (an answer, a unit) is asked for
    # row by row, so that a row this sheet does not print is not counted
    say = Speaker("zz", held({"answers": {"no": "Nɔb."}}), ENGLISH)
    assert say.row("sheet.answers", "no") == "Nɔb."
    assert say.fell_back == []
    assert say.row("sheet.answers", "yes") == "Yes."
    assert say.row("sheet.answers", "yes") == "Yes."
    assert say.fell_back == ["sheet.answers[yes]"]
    with pytest.raises(KeyError):
        say.row("sheet.answers", "maybe")
    with pytest.raises(TypeError):
        say.row("sheet.plain", "yes")
    assert Speaker("", {}, ENGLISH).row("sheet.answers", "no") == "No."


def test_a_speaker_fills_a_translated_sentence_as_english_is_filled():
    text = {"amount": "{hours:g} wug: {cans:num} {cans:plural:glorp|glorps}."}
    say = Speaker("zz", held(text), ENGLISH)
    assert say.phrase("sheet.amount", cans=1, hours=6.5) == "6.5 wug: 1 glorp."
    assert say.phrase("sheet.amount", cans=1200, hours=8) == "8 wug: 1,200 glorps."
    with pytest.raises(KeyError):
        say.phrase("sheet.amount", cans=1)
    with pytest.raises(KeyError):
        say.phrase("sheet.nothing")
    with pytest.raises(TypeError):
        say.phrase("sheet.answers")
    with pytest.raises(TypeError):
        say.phrase_table("sheet.plain")


def test_translated_text_is_written_one_way_for_both_writers():
    # the two document writers tidy text differently (one turns a long dash
    # into a hyphen, the other closes up spaces): translated text is handed
    # to both already tidied, as typed text is
    text = {"plain": "  Wug — zub  – frimo.\t", "title": "Glorp—{place}  wug",
            "answers": {"yes": " Zɛ – zub ", "no": "Nɔb—wug"}}
    say = Speaker("zz", held(text), ENGLISH)
    assert say.phrase("sheet.plain") == "Wug - zub - frimo."
    assert say.phrase("sheet.title", place="Bo") == "Glorp - Bo wug"
    assert say.phrase_table("sheet.answers") == {"yes": "Zɛ - zub", "no": "Nɔb - wug"}
    assert say.row("sheet.answers", "no") == "Nɔb - wug"


def test_english_is_spoken_with_no_language_and_keeps_no_count():
    say = Speaker("", held({"plain": "Wug zub frimo."}), ENGLISH)
    assert say.code == "" and say.language == {}
    assert say.phrase("sheet.plain") == "Tell the caretaker."
    assert say.row("sheet.answers", "yes") == "Yes."
    assert say.fell_back == []
    # and over the catalogue itself it is phrase() and phrase_table()
    real = Speaker()
    assert real.phrase("community_sheet.title", place="Rokel") == phrase(
        "community_sheet.title", place="Rokel")
    assert real.phrase_table("community_sheet.quality") == phrase_table("community_sheet.quality")


def test_what_is_left_to_translate_is_told_entry_by_entry():
    text = {"plain": "x", "title": None, "answers": {"no": "Nɔb."}}
    assert untranslated("zz", ["sheet.title", "sheet.plain", "sheet.answers", "sheet.amount"],
                        held(text), ENGLISH) == ["sheet.title", "sheet.answers[yes]", "sheet.amount"]
    assert untranslated("qq", ["sheet.plain"], held(text), ENGLISH) == ["sheet.plain"]


def test_a_copy_of_the_english_is_pointed_out():
    # a rule cannot tell a sentence copied from the English file from one
    # that reads the same in both languages; what is the same is listed, for
    # a person to say which it is
    text = {"plain": "Tell the caretaker.", "title": " Your  borehole at {place} ",
            "amount": "{cans:num} glorps {hours:g}", "answers": {"yes": "Yes.", "no": "Nɔb."}}
    idents = ["sheet.title", "sheet.amount", "sheet.plain", "sheet.answers"]
    assert same_as_english("zz", idents, held(text), ENGLISH) == [
        "sheet.title", "sheet.plain", "sheet.answers[yes]"]
    assert same_as_english("zz", idents, held({}), ENGLISH) == []


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
                      community_sheet={"title": "Zɛdo glorp {place}"}, verification="")
    write_translation(tmp_path, "zy", None, community_sheet="# nothing yet\n")
    (tmp_path / "zz" / "notes.txt").write_text("not a catalogue file", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "community_sheet.yaml").write_text("title: English\n", encoding="utf-8")
    read = read_translations(tmp_path)
    assert read == {
        "zy": {"language": {}, "text": {"community_sheet": None}},
        "zz": {"language": WHO,
               "text": {"community_sheet": {"title": "Zɛdo glorp {place}"},
                        "verification": None}},
    }
    assert [language["code"] for language in languages(read)] == ["zz"]
    content = community_sheet_content(SITE, language="zz", translations=read)
    assert content["title"] == "Zɛdo glorp Rokel"


def test_the_english_file_itself_reads_as_a_translation(tmp_path):
    # a translator starts from the English file: its comments, its folded
    # sentences, its quoted ones and its rows keyed by words with spaces in
    # them all read as they are written
    english = (TEXT / "community_sheet.yaml").read_text(encoding="utf-8")
    write_translation(tmp_path, "zz", WHO, community_sheet=english)
    read = read_translations(tmp_path)
    assert read["zz"]["text"]["community_sheet"] == text_catalogue()["community_sheet"]
    # the builder's entries are in it, which are English's own and no fault
    assert translation_problems("zz", read) == []
    # and every part of it is still the English, which is pointed out
    assert untranslated("zz", sheet_entries(), read) == []
    assert len(same_as_english("zz", sheet_entries(), read)) > len(sheet_entries())


def test_a_file_that_cannot_be_read_refuses_its_language_and_no_other(tmp_path):
    # the slips a translator makes when a sentence is turned round: one that
    # now begins with its value, one with a colon in it, a file saved by an
    # editor in another encoding. Each is a reason, in words, against that
    # language; the others, and the English sheet, are untouched
    write_translation(tmp_path, "za", WHO, community_sheet="keep_metres: {distance:g} zm\n")
    write_translation(tmp_path, "zb", WHO, community_sheet="water_heading: Zub: glorp\n")
    write_translation(tmp_path, "zc", WHO)
    (tmp_path / "zc" / "community_sheet.yaml").write_bytes("title: Zub {place}\n".encode("utf-16"))
    write_translation(tmp_path, "zd", None, community_sheet={"title": "Zub {place}"})
    (tmp_path / "zd" / "language.yaml").write_text("name: [Zedish\n", encoding="utf-8")
    write_translation(tmp_path, "zz", WHO, community_sheet={"title": "Zub {place}"})
    read = read_translations(tmp_path)

    problems = {code: translation_problems(code, read) for code in read}
    assert problems["zz"] == []
    assert len(problems["za"]) == 1 and problems["za"][0].startswith(
        "community_sheet.yaml cannot be read: line 1, column ")
    colon = ("community_sheet.yaml cannot be read: line 1, column 19: mapping values are not "
             "allowed here")
    assert problems["zb"] == [colon]
    assert problems["zc"] == ["community_sheet.yaml cannot be read: it is not saved as UTF-8 text"]
    assert len(problems["zd"]) == 1 and problems["zd"][0].startswith(
        "language.yaml cannot be read: line ")
    assert [language["code"] for language in languages(read)] == ["zz"]

    # the English sheet is built, and says that something installed is not
    # on offer; the sound translation is built too
    plain = community_sheet_content(SITE, translations=read)
    assert plain["title"] == "Your borehole at Rokel"
    assert plain["notes"][-1] == phrase("community_sheet.translation_refused",
                                        codes="za, zb, zc, zd")
    assert community_sheet_content(SITE, language="zz", translations=read)["title"] == "Zub Rokel"


def test_both_engines_are_handed_the_same_data(tmp_path):
    # the browser's copy of a translation goes through JSON, where a row
    # keyed 2 is keyed "2" and a date is its text; Python judges that same
    # data, so that one app does not offer what the other refuses
    import json

    write_translation(tmp_path, "zz", None,
                      terrain="compression_names:\n  2: Zub\n",
                      community_sheet="title: 2026-03-01\n")
    (tmp_path / "zz" / "language.yaml").write_text(
        "name: Zedish\ntranslated_by: A. Translator\nchecked_by: B. Checker\n"
        "checked_on: 2026-03-01\n", encoding="utf-8")
    read = read_translations(tmp_path)
    assert json.loads(json.dumps(read)) == read
    assert read["zz"]["language"]["checked_on"] == "2026-03-01"
    assert read["zz"]["text"]["terrain"] == {"compression_names": {"2": "Zub"}}
    assert translation_problems("zz", read) == [
        "community_sheet.title " + WRONG.format("place")]


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
                      community_sheet={"title": "{place}", "quality": {"pass": "Zɛ."},
                                       "keep_centre": "Borehole"})
    write_translation(tmp_path, "zx", {"name": "Unchecked", "translated_by": "A"},
                      community_sheet={"title": "No place"})
    write_translation(tmp_path, "zw", WHO, community_sheet="title: {place} zub\n")
    assert main(["translation", "zz", "--folder", str(tmp_path)]) == 0
    said = capsys.readouterr().out
    assert "zz: Zedish, translated by A. Translator, checked by B. Checker" in said
    assert "has words for every part" in said and "read exactly as the English" not in said

    assert main(["translation", "zy", "--folder", str(tmp_path)]) == 0
    said = capsys.readouterr().out
    left = len(sheet_entries()) - 3 + len(phrase_table("community_sheet.quality")) - 1
    assert f"prints {left} of its parts in English" in said
    assert "- community_sheet.quality[health_fail]" in said
    assert "- community_sheet.water_heading" in said
    assert "community_sheet.title\n" not in said and "quality[pass]" not in said
    # what it words as the English does is pointed out, for a person to judge
    assert "1 of its parts read exactly as the English does" in said
    assert said.rstrip().endswith("- community_sheet.keep_centre")
    # nothing for the builder is asked of a translator
    assert "builder_notes" not in said and "community_sheet.about" not in said

    assert main(["translation", "zx", "--folder", str(tmp_path)]) == 1
    said = capsys.readouterr().out
    assert "zx: cannot be offered" in said and "does not say checked_by" in said
    assert "community_sheet.title does not take the values" in said

    # a file that does not parse is a reason, with its place, not a traceback
    assert main(["translation", "zw", "--folder", str(tmp_path)]) == 1
    assert "community_sheet.yaml cannot be read: line 1" in capsys.readouterr().out
    # and a sound language beside it is still answered for
    assert main(["translation", "zz", "--folder", str(tmp_path)]) == 0
    capsys.readouterr()

    # every one is told, and one that cannot be offered fails the lot
    assert main(["translation", "--folder", str(tmp_path)]) == 1
    said = capsys.readouterr().out
    assert said.index("zw:") < said.index("zx:") < said.index("zy:") < said.index("zz:")
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
    hours = {MARK + words for words in phrase_table("community_sheet.hour_words").values()}
    for given in EVERY_SHEET:
        site = SiteMetadata(community="" if given.get("example") else "Rokel")
        content = community_sheet_content(site, language="zz", translations=marked(), **given)
        english = community_sheet_content(site, translations=marked(), **given)
        assert content["fell_back"] == [], given
        strings = printed(content)
        for text, source in zip(strings, printed(english), strict=True):
            # the mark at its head, and the same sentence: every figure is
            # where it was
            assert text.startswith(MARK) and text.replace(MARK, "") == source, text
            # a sentence that carries the word for hours carries the
            # translated word, so two marks; every other sentence, one
            inner = sum(text.count(" " + word + " ") for word in hours)
            assert text.count(MARK) == 1 + inner, text
        days = [line for line in content["water"]["lines"] + [content["water"]["headline"]]
                if "with the pump used for" in line]
        assert all(line.count(MARK) == 2 for line in days), days
        for key in ("litres_per_hour", "jerrycans_per_hour", "litres_per_day",
                    "jerrycans_per_day", "state"):
            assert content["water"][key] == english["water"][key]
        assert content["quality"]["state"] == english["quality"]["state"]
        assert content["report"]["payload"] == english["report"]["payload"]
        # what was typed is printed as typed
        assert content["contacts"]["rows"][:-2] == english["contacts"]["rows"][:-2]
    # at least one of the sheets above says the hours, so the count of two
    # marks was put to the test
    assert any(given.get("hours_per_day") for given in EVERY_SHEET)


def test_the_entries_a_translator_is_asked_for_are_the_ones_the_sheet_prints():
    # asked of an empty translation, everything a sheet prints falls back:
    # between them the sheets above ask for each entry sheet_entries() names
    # and for nothing else, so the list a translator works from is the sheet
    nothing = {"zz": {"language": dict(WHO), "text": {}}}
    asked = set()
    for given in EVERY_SHEET:
        site = SiteMetadata(community="" if given.get("example") else "Rokel")
        content = community_sheet_content(site, language="zz", translations=nothing, **given)
        # and each sheet asks only for what it prints: as many parts fell
        # back as it has strings from the catalogue (a table every row of
        # which is printed is one part)
        tables = {"community_sheet.contacts_columns": 3, "community_sheet.contacts_write_in": 2,
                  "community_sheet.keep_structures": 4}
        strings = len(printed(content))
        strings -= sum(tables[name] - 1 for name in tables if name in content["fell_back"])
        # the rings' labels are one sentence printed three times, and the
        # hour word is inside its sentence
        strings -= len(content["keep_away"]["rings"]) - 1
        strings += sum(1 for name in content["fell_back"] if "hour_words" in name)
        assert len(content["fell_back"]) == strings, (given, content["fell_back"])
        asked |= {name.split("[")[0] for name in content["fell_back"]}
    assert asked == set(sheet_entries())
    catalogue = text_catalogue()["community_sheet"]
    assert set(BUILDER_ENTRIES) <= set(catalogue)
    assert len(sheet_entries()) == len(catalogue) - len(BUILDER_ENTRIES)


def test_only_what_this_sheet_prints_is_counted_as_english():
    # a translation with one answer on safety missing is whole for every
    # sheet that does not print that answer
    one = marked()
    one["zz"]["text"]["community_sheet"]["quality"]["national_fail"] = None
    one["zz"]["text"]["community_sheet"]["hour_words"]["one"] = None
    passed = community_sheet_content(SITE, language="zz", translations=one,
                                     analysis=analysis(0.39), hours_per_day=8,
                                     quality=verdict("pass"))
    assert passed["fell_back"] == []
    assert not any("printed in English" in note for note in passed["notes"])
    failed = community_sheet_content(SITE, language="zz", translations=one,
                                     analysis=analysis(0.39), hours_per_day=1,
                                     quality=verdict("national_fail"))
    assert failed["fell_back"] == ["community_sheet.hour_words[one]",
                                   "community_sheet.quality[national_fail]"]
    assert failed["quality"]["headline"].startswith("Not yet.")
    assert failed["notes"][-1].startswith("2 parts of this sheet have no Zedish wording yet")


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
        f"{count} parts of this sheet have no Zedish wording yet and are printed in English.")
    one = marked()
    del one["zz"]["text"]["community_sheet"]["keep_caption"]
    content = community_sheet_content(SITE, language="zz", translations=one)
    assert content["fell_back"] == ["community_sheet.keep_caption"]
    assert content["notes"][-1] == (
        "1 part of this sheet has no Zedish wording yet and is printed in English.")


def test_english_is_the_sheet_unless_a_language_is_asked_for():
    notes = phrase_table("community_sheet.builder_notes")
    plain = community_sheet_content(SITE, translations={})
    offered = community_sheet_content(SITE, translations=marked())
    assert offered["language"] == {} and offered["fell_back"] == []
    assert not any(MARK in text for text in printed(offered))
    # with a translation on offer the builder chose English, and is not told
    # that none exists; with none, they are
    assert notes["english_only"] not in offered["notes"]
    assert plain["notes"][-1] == notes["english_only"]
    assert {**offered, "notes": None} == {**plain, "notes": None}


def test_a_language_that_is_not_offered_stops_the_sheet_and_is_said():
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
    # whoever installed it is told, on the English sheet, that it is there
    # and not offered, rather than left looking for it in the list
    both = {**marked(), "yy": unchecked["zz"], "yx": faulty["zz"]}
    refused = phrase("community_sheet.translation_refused", codes="yx, yy")
    assert community_sheet_content(SITE, translations=both)["notes"][-1] == refused
    assert community_sheet_content(SITE, language="zz", translations=both)["notes"][-1] == refused
    assert not any("cannot be offered" in note
                   for note in community_sheet_content(SITE, translations=marked())["notes"])


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


def test_both_writers_are_handed_the_same_translated_words(tmp_path):
    from test_community_sheet import _read

    from groundwater.reporting.community_sheet import build_community_sheet

    untidy = marked()
    text = untidy["zz"]["text"]["community_sheet"]
    text["report_tell"] = "Zub  wug — frimo – glorp."
    text["water_none"] = " Frim nɔb zub. "
    content = community_sheet_content(SITE, language="zz", translations=untidy)
    assert content["report"]["lines"][0] == "Zub wug - frimo - glorp."
    assert content["water"]["headline"] == "Frim nɔb zub."
    path = build_community_sheet(SITE, tmp_path / "sheet.docx", tmp_path, language="zz",
                                 translations=untidy)
    paragraphs = _read(path)["paragraphs"]
    # as the content has them, with nothing left for a writer to change
    assert "Frim nɔb zub." in paragraphs and "Zub wug - frimo - glorp." in paragraphs


# ----------------------------------------------------------------- the picture


def long_rows(times: float) -> dict:
    """A translation whose rows of the key are the English ones made longer
    with invented words, and whose distances carry a word, not a letter."""
    english = phrase_table("community_sheet.keep_structures")
    filler = " zɛdo glorp frimo wug zub ɔmba"
    rows = {key: words + (filler * 4)[: int(len(words) * (times - 1))].rstrip()
            for key, words in english.items()}
    return {"zz": {"language": dict(WHO), "text": {"community_sheet": {
        "keep_structures": rows, "keep_metres": "{distance:g} mitazɔ"}}}}


def test_the_key_is_laid_out_by_measure_and_english_is_where_it_was():
    from groundwater.reporting.community_sheet import fit_words, key_layout

    def measure(text, points, bold):          # every letter a fifth of a centimetre
        return 0.2 * len(text)

    assert fit_words("aa bb cc dd", 1.0, lambda line: 0.2 * len(line)) == ["aa bb", "cc dd"]
    assert fit_words("abcdefgh ij", 1.0, lambda line: 0.2 * len(line)) == ["abcdefgh", "ij"]
    assert fit_words("", 1.0, len) == [""]
    rings = [{"label": "3 m", "what": ["aaaa bbbb"]}, {"label": "20 m", "what": ["cc", "dddd eeee ffff"]}]
    roomy = key_layout(rings, 12.55, 5.0, measure)
    # room for all of it: nothing is broken, nothing is smaller, and the rows
    # start where the English ones do
    assert roomy["text_at"] == 7.3 and roomy["scale"] == 1.0
    assert roomy["rows"] == [[["aaaa bbbb"]], [["cc"], ["dddd eeee ffff"]]]
    tight = key_layout(rings, 9.5, 5.0, measure)
    assert tight["rows"] == [[["aaaa bbbb"]], [["cc"], ["dddd eeee", "ffff"]]]
    # a distance wider than the room the English one has moves the rows right
    wide = key_layout([{"label": "1000 mitazozo", "what": ["aa"]}], 12.55, 5.0, measure)
    assert wide["text_at"] == pytest.approx(6.0 + 2.6 + 0.25)
    # a word no line can hold, and a key too tall, are set smaller
    assert key_layout([{"label": "3 m", "what": ["a" * 40]}], 12.55, 5.0, measure)["scale"] < 1
    tall = key_layout([{"label": "3 m", "what": ["aa"] * 20}], 12.55, 5.0, measure)
    assert tall["scale"] < 1 and tall["lines"] * tall["pitch"] <= 5.0 - 0.4 + 1e-9


@pytest.mark.parametrize("times", [1.3, 2.0, 3.5])
def test_a_longer_translation_does_not_run_into_the_square_or_off_the_picture(tmp_path, times):
    from PIL import Image, ImageChops

    from groundwater.reporting import community_sheet as writer

    def picture(name, **given):
        content = community_sheet_content(SITE, **given)
        path, width = writer.sheet_picture(content, tmp_path / name)
        with Image.open(path) as image:
            return image.convert("L"), width

    def cm(image, width, x0, x1):
        return image.crop((int(image.width * x0 / width), 0, int(image.width * x1 / width),
                           image.height))

    def black(image) -> int:
        return sum(image.histogram()[:128])

    scan = dict(asset_id="SL-WAR-8FEEVKQ-T", config=linked())
    english, width = picture("english.png", translations={}, **scan)
    long, _ = picture("long.png", language="zz", translations=long_rows(times), **scan)
    # the square a phone scans is the same square, pixel for pixel, with its
    # white margin: nothing of the key is printed over it
    box = (writer.SCAN_AT_CM, writer.SCAN_AT_CM + writer.SCAN_SIZE_CM)
    assert english.size == long.size
    assert ImageChops.difference(cm(english, width, *box),
                                 cm(long, width, *box)).getbbox() is None
    assert black(cm(english, width, *box)) > 0
    # and the key is there, longer than the English one
    key = (writer.KEY_AT_CM, writer.SCAN_AT_CM - 0.05)
    assert black(cm(long, width, *key)) > black(cm(english, width, *key))

    # with no square, nothing reaches the picture's right edge
    plain, width = picture("plain.png", language="zz", translations=long_rows(times))
    assert black(cm(plain, width, width - 0.12, width)) == 0
    assert black(cm(plain, width, writer.KEY_AT_CM, width)) > 0

"""Other languages (PLAN.md step 9.2): the "text_languages" entry of
``reference.json``.

No translation is bundled: PLAN.md asks for one made and checked by native
speakers. So the two engines are held to each other on a catalogue and on
translations made up for the purpose, which are handed to both: every reason
a translation is refused, which are offered and in what order, and what a
speaker says, sentence by sentence, with what it had to say in English.
"""

from __future__ import annotations

#: A catalogue small enough to read whole: a sentence for each format the
#: grammar has, a sentence with no values, one with a written brace, and a
#: table.
ENGLISH = {
    "sheet": {
        "title": "Your borehole at {place}",
        "amount": "About {cans:num} {cans:plural:jerrycan|jerrycans}, {litres:.1f} litres "
                  "in {hours:g} hours.",
        "plain": "Tell the caretaker.",
        "braces": "Write {{name}} for {name}.",
        "answers": {"yes": "Yes.", "no": "No.", "unknown": "Not known yet."},
    },
    "notes": {
        "kept": "Kept {n:g} {n:plural:row|rows}.",
    },
}

_WHO = {"name": "Zedish", "translated_by": "A. Translator", "checked_by": "B. Checker"}


def _language(text: dict, **facts) -> dict:
    return {"language": {**_WHO, **facts}, "text": text}


#: Translations, by code: the ones that can be offered first, then one for
#: each reason a translation is refused. Letters outside ASCII are in them
#: because Krio is written with them.
HELD = {
    # the whole of it, with the plural's two words its own, a value used
    # twice, and the order of the values changed
    "zz": _language({
        "sheet": {
            "title": "Una bɔrɔl na {place}",
            "amount": "{litres:.1f} lita insay {hours:g} awa: lɛk {cans:num} "
                      "{cans:plural:jɛriken|jɛriken dɛm} ({cans:num}).",
            "plain": "Tɛl di kiateka.",
            "braces": "Rayt {{name}} fɔ {name}.",
            "answers": {"yes": "Yɛs.", "no": "Nɔ.", "unknown": "Wi nɔ no yet."},
        },
        "notes": {"kept": "{n:g} {n:plural:ro|ro dɛm}."},
    }),
    # a part of it: one sentence, and two rows of the table
    "zy": _language({"sheet": {"plain": "Tɛl am.", "answers": {"no": "Nɔ.", "yes": "Yɛs."}}},
                    name="  Ypsilonian ", translated_by=" C. Translator ", checked_by="D. Checker\n"),
    # nothing translated yet, which is English throughout and no fault; and
    # a file with nothing in it
    "zx": _language({}, name="Alphan"),
    "zw": _language({"sheet": {}}, name="Alphan"),
    # entries named and left empty are not translated yet, which is no fault
    "zu": _language({"sheet": {"title": None, "plain": "T\u025bl am.",
                               "answers": {"yes": None, "no": "N\u0254."}},
                     "notes": {"kept": None}}, name="Gamman"),
    "zt": _language({"sheet": {"answers": None}, "notes": None}, name="Gamman"),
    # of a plural and a number English writes for one value, either alone
    "zv": _language({"sheet": {"amount": "{cans:num} / {litres:.1f} / {hours:g}"},
                     "notes": {"kept": "{n:plural:wan|bok}"}}, name="Betan"),
    # --- refused: it does not say what it is, who made it or who checked it
    "ya": {"language": {"name": "Nameless", "translated_by": "A. Translator"}, "text": {}},
    "yb": {"language": {"name": " ", "translated_by": "", "checked_by": "B. Checker"}, "text": {}},
    "yc": {"language": {"name": "Numbered", "translated_by": 7, "checked_by": None}, "text": {}},
    "yd": {"language": ["Listed", "A", "B"], "text": {}},
    "ye": {"text": {"sheet": {"plain": "No facts at all."}}},
    # --- refused: it translates what English does not have
    "yf": _language({"sheet": {"plain": "Ok.", "extra": "Not in English."},
                     "other": {"plain": "A file English lacks."}}),
    "yg": _language({"sheet": ["plain", "title"]}),
    # --- refused: a sentence for a table, a table for a sentence, a row
    # English lacks, a row that is not plain text
    "yh": _language({"sheet": {"answers": "Yes or no.", "plain": {"a": "b"}}}),
    "yi": _language({"sheet": {"answers": {"yes": "Yɛs.", "maybe": "Maybe.", "no": 0,
                                           "unknown": "A {value}."}}}),
    "yj": _language({"sheet": {"title": 12, "plain": None, "braces": ["a"]}}),
    # --- refused: a sentence that does not take the values the English does
    "yk": _language({"sheet": {"title": "No place named."}}),
    "yl": _language({"sheet": {"title": "{place} of {district}"}}),
    "ym": _language({"sheet": {"plain": "Tell {who}."}}),
    "yn": _language({"sheet": {"amount": "{cans:g} {litres:.1f} {hours:g}"}}),
    "yo": _language({"sheet": {"amount": "{cans:num} {litres:.2f} {hours:g}"}}),
    "yp": _language({"sheet": {"amount": "{cans:num} {litres:.1f} {hours:plural:awa|awa dɛm}"}}),
    "yq": _language({"sheet": {"title": "A lone { brace at {place}"}}),
    "yr": _language({"sheet": {"title": "{place"}}),
    "ys": _language({"sheet": {"braces": "{{name}} only"}}),
    "yt": _language({"sheet": {"title": "{place:g}"}}),
    # --- refused: a blank sentence, a blank row
    "yv": _language({"sheet": {"plain": "", "title": "  \n", "answers": {"yes": " ", "no": ""}}}),
    # several at once, to hold the order they are told in
    "yu": {"language": {"name": "Many"}, "text": {
        "sheet": {"title": "none", "zeta": "x", "answers": {"zeta": "x", "alpha": "y"},
                  "amount": "{cans:num}"},
        "alpha": {}, "notes": "kept"}},
    # --- refused: a folder that is not named as a language is
    "Zz": _language({}, name="Capital"),
    "z": _language({}, name="Short"),
    "toolongcode": _language({}, name="Long"),
    "z1": _language({}, name="Digit"),
}

#: What each speaker is asked, in order: a sentence with its values, or a
#: table. Some are asked twice, some do not exist, and some are asked for as
#: the wrong kind or with the wrong values.
SCRIPT = [
    ["phrase", "sheet.title", {"place": "Rokel"}],
    ["phrase", "sheet.amount", {"cans": 1, "litres": 20, "hours": 6.5}],
    ["phrase", "sheet.amount", {"cans": 1200, "litres": 24000.04, "hours": 8}],
    ["phrase", "sheet.plain", {}],
    ["table", "sheet.answers", None],
    ["phrase", "sheet.braces", {"name": "Aminata"}],
    ["phrase", "notes.kept", {"n": 1}],
    ["phrase", "sheet.title", {"place": "Kuntolo"}],
    ["table", "sheet.answers", None],
    ["phrase", "sheet.missing", {}],
    ["phrase", "missing.title", {}],
    ["phrase", "nodot", {}],
    ["phrase", "sheet.answers", {}],
    ["table", "sheet.title", None],
    ["phrase", "sheet.title", {}],
    ["phrase", "sheet.title", {"place": "Rokel", "more": "x"}],
    ["phrase", "sheet.title", {"place": 7}],
]


def _spoken(code: str) -> dict:
    from groundwater.text import Speaker

    try:
        say = Speaker(code, held=HELD, english=ENGLISH)
    except ValueError as error:
        return {"refused": str(error)}
    said = []
    for kind, ident, values in SCRIPT:
        try:
            said.append(say.phrase(ident, **values) if kind == "phrase"
                        else say.phrase_table(ident))
        except (KeyError, TypeError, ValueError):
            # that it is refused is compared; each engine words it its own way
            said.append({"error": True})
    return {"language": say.language, "said": said, "fell_back": say.fell_back}


def text_languages_reference() -> dict:
    from groundwater.text import languages, translation_problems

    codes = [*HELD, "qq", ""]
    return {
        "english": ENGLISH, "held": HELD, "script": SCRIPT, "codes": codes,
        "problems": [translation_problems(code, HELD, ENGLISH) for code in codes],
        "languages": languages(HELD, ENGLISH),
        "spoken": [_spoken(code) for code in codes],
        # with nothing held there is nothing to offer, and English is spoken
        "none": {"languages": languages({}, ENGLISH),
                 "problems": translation_problems("zz", {}, ENGLISH)},
        # the translations the package itself bundles and offers, which the
        # browser's build has to offer too
        "bundled": [language["code"] for language in languages()],
    }

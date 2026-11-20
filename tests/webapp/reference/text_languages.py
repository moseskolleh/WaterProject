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
        # a count English writes only as the word that agrees with it
        "rows": "Kept {n:plural:a row|rows}.",
        # and one it prints two ways
        "both": "{n:g} of {n:num}, {m:.1f}.",
    },
}

_WHO = {"name": "Zedish", "translated_by": "A. Translator", "checked_by": "B. Checker"}


def _language(text: dict, **facts) -> dict:
    return {"language": {**_WHO, **facts}, "text": text}


#: Translations, by code: the ones that can be offered first, then one for
#: each reason a translation is refused. Every word in them is invented (no
#: language is written here, PLAN.md forbids it); the letters outside ASCII
#: are there because the languages this is for are written with them.
HELD = {
    # the whole of it, with the plural's two words its own, a value used
    # twice, and the order of the values changed
    "zz": _language({
        "sheet": {
            "title": "Zɛdo glorp {place}",
            "amount": "{litres:.1f} frim wug {hours:g} ɔmba: zub {cans:num} "
                      "{cans:plural:glorp|glorpɔz} ({cans:num}).",
            "plain": "Wug zub frimo.",
            "braces": "Zub {{name}} frim {name}.",
            "answers": {"yes": "Zɛ.", "no": "Nɔb.", "unknown": "Wug nɔb zub."},
        },
        "notes": {"kept": "{n:g} {n:plural:frim|frimɔz}."},
    }),
    # a part of it: one sentence, and two rows of the table
    "zy": _language({"sheet": {"plain": "Wug zub.", "answers": {"no": "Nɔb.", "yes": "Zɛ."}}},
                    name="  Ypsilonian ", translated_by=" C. Translator ", checked_by="D. Checker\n"),
    # nothing translated yet, which is English throughout and no fault; and
    # a file with nothing in it
    "zx": _language({}, name="Alphan"),
    "zw": _language({"sheet": {}}, name="Alphan"),
    # entries named with nothing after them are not translated yet, which is
    # no fault
    "zu": _language({"sheet": {"title": None, "plain": "Wug zub.",
                               "answers": {"yes": None, "no": "Nɔb."}},
                     "notes": {"kept": None}}, name="Gamman"),
    "zt": _language({"sheet": {"answers": None}, "notes": None}, name="Gamman"),
    # the word that agrees with a count may be left out, by a language with
    # no need of it; the number may not (see "yw")
    "zv": _language({"sheet": {"amount": "{cans:num} / {litres:.1f} / {hours:g}"},
                     "notes": {"kept": "{n:g} frim"}}, name="Betan"),
    # dashes and doubled spaces are written one way, as typed text is, and
    # the white space either engine would take off the ends of a name is
    # taken off by both
    "zs": _language({"sheet": {"plain": "  Wug \u2014 zub  \u2013 frimo.\t",
                               # tidied once it is filled: a plural with no word
                               # for one leaves two spaces, and a no-break space
                               # is a space
                               "amount": "{cans:num} glorp {cans:plural:|frimɔz} wug\u00a0"
                                         "{litres:.1f}\u202f{hours:g}",
                               "title": "Glorp\u2014{place}  wug",
                               "answers": {"yes": " Zɛ \u2013 zub ", "no": "Nɔb\u2014wug"}}},
                    name="\ufeff Deltan \x85", translated_by="\x1cE. Translator\u2028",
                    checked_by="\u00a0F. Checker\ufeff"),
    # a code may be eight letters
    "zzzzzzzz": _language({"notes": {"rows": "Zub {n:plural:frim|frimɔz}.",
                                     # both ways English prints it, turned round
                                     "both": "{m:.1f}: {n:num} wug {n:g}."}}, name="Eightish"),
    # --- refused: it does not say what it is, who made it or who checked it
    "ya": {"language": {"name": "Nameless", "translated_by": "A. Translator"}, "text": {}},
    "yb": {"language": {"name": " ", "translated_by": "", "checked_by": "B. Checker"}, "text": {}},
    "yc": {"language": {"name": "Numbered", "translated_by": 7, "checked_by": None}, "text": {}},
    "yd": {"language": ["Listed", "A", "B"], "text": {}},
    "ye": {"text": {"sheet": {"plain": "No facts at all."}}},
    # ... nor with white space only one of the engines' own trims would take
    "xa": _language({}, checked_by="\x85"),
    "xb": _language({}, checked_by="\ufeff"),
    "xc": _language({}, name="\x1f", translated_by="\u2028\u3000"),
    # --- refused: it translates what English does not have
    "yf": _language({"sheet": {"plain": "Ok.", "extra": "Not in English."},
                     "other": {"plain": "A file English lacks."}}),
    "yg": _language({"sheet": ["plain", "title"]}),
    # --- refused: a sentence for a table, a table for a sentence, a row
    # English lacks, a row that is not plain text
    "yh": _language({"sheet": {"answers": "Yes or no.", "plain": {"a": "b"}}}),
    "yi": _language({"sheet": {"answers": {"yes": "Zɛ.", "maybe": "Maybe.", "no": 0,
                                           "unknown": "A {value}."}}}),
    "yj": _language({"sheet": {"title": 12, "braces": ["a"]}}),
    "xd": _language({"sheet": {"answers": {"yes": "}", "no": "{"}}}),
    # --- refused: a sentence that does not take the values the English does
    "yk": _language({"sheet": {"title": "No place named."}}),
    "yl": _language({"sheet": {"title": "{place} of {district}"}}),
    "ym": _language({"sheet": {"plain": "Tell {who}."}}),
    "yn": _language({"sheet": {"amount": "{cans:g} {litres:.1f} {hours:g}"}}),
    "yo": _language({"sheet": {"amount": "{cans:num} {litres:.2f} {hours:g}"}}),
    "yp": _language({"sheet": {"amount": "{cans:num} {litres:.1f} {hours:plural:wug|wugɔz}"}}),
    "yq": _language({"sheet": {"title": "A lone { brace at {place}"}}),
    "yr": _language({"sheet": {"title": "{place"}}),
    "ys": _language({"sheet": {"braces": "{{name}} only"}}),
    "yt": _language({"sheet": {"title": "{place:g}"}}),
    # the number is dropped and only the word that agreed with it is kept:
    # the headline of the sheet with no figure in it
    "yw": _language({"sheet": {"amount": "Zub {cans:plural:glorp|glorpɔz} {litres:.1f} {hours:g}"}}),
    "yx": _language({"notes": {"kept": "{n:plural:frim|frimɔz}"}}),
    # where English writes a count only as a word, a translation may not
    # print the number: plainly, or beside the word
    "xk": _language({"notes": {"rows": "Zub {n}."}}),
    "xl": _language({"notes": {"rows": "Zub {n} {n:plural:frim|frimɔz}."}}),
    "xm": _language({"notes": {"rows": "Zub {n:g} {n:plural:frim|frimɔz}."}}),
    # a word that agrees with a count is added where English has none, the
    # number kept: the word is not the translation's to add
    "xn": _language({"sheet": {"amount": "{cans:num} {litres:.1f} {hours:g} "
                                         "{hours:plural:wug|wugɔz}"}}),
    # of the two ways English prints a number, one is dropped
    "xo": _language({"notes": {"both": "{n:g} wug {m:.1f}."}}),
    "xp": _language({"notes": {"both": "{n:num} wug {m:.1f}."}}),
    # a number written both ways English writes it and one more
    "xe": _language({"notes": {"kept": "{n:g} {n:num} {n:plural:frim|frimɔz}"}}),
    # a value named as an object's own furniture is named, and is one more
    # value than English has
    "xf": _language({"sheet": {"title": "Zub {place} {__proto__}", "plain": "Wug {constructor}."}}),
    # a figure of another script in a format is not a format
    "xg": _language({"sheet": {"amount": "{cans:num} {litres:.\u0661f} {hours:g}"}}),
    # --- refused: a blank sentence, a blank row, whichever white space
    "yv": _language({"sheet": {"plain": "", "title": "  \n", "answers": {"yes": " ", "no": ""}}}),
    "xh": _language({"sheet": {"plain": "\ufeff", "title": "\x85\x1c",
                               "answers": {"yes": "\u2029", "no": "\ufeff\u00a0"}}}),
    # --- refused: a file that could not be read, kept as the reason; a file
    # that is one line of text is not a list of entries
    "xi": _language({"sheet": "cannot be read: line 1, column 27: expected <block end>, "
                              "but found '<scalar>'",
                     "notes": "kept: but not as a list"}),
    "xj": {"language": "cannot be read: it is not saved as UTF-8 text",
           "text": {"sheet": {"plain": "Wug zub."}}},
    # several at once, to hold the order they are told in
    "yu": {"language": {"name": "Many"}, "text": {
        "sheet": {"title": "none", "zeta": "x", "answers": {"zeta": "x", "alpha": "y"},
                  "amount": "{cans:num}"},
        "alpha": {}, "notes": "kept"}},
    # --- refused: a folder that is not named as a language is
    "Zz": _language({}, name="Capital"),
    "z": _language({}, name="Short"),
    "zzzzzzzzz": _language({}, name="Nine letters"),
    "z1": _language({}, name="Digit"),
}

#: What each speaker is asked, in order: a sentence with its values, a whole
#: table, or one row of a table. Some are asked twice, some do not exist,
#: and some are asked for as the wrong kind or with the wrong values.
SCRIPT = [
    ["phrase", "sheet.title", {"place": "Rokel"}],
    ["phrase", "sheet.amount", {"cans": 1, "litres": 20, "hours": 6.5}],
    ["phrase", "sheet.amount", {"cans": 1200, "litres": 24000.04, "hours": 8}],
    ["phrase", "sheet.plain", {}],
    ["row", "sheet.answers", "no"],
    ["row", "sheet.answers", "unknown"],
    ["row", "sheet.answers", "no"],
    ["phrase", "sheet.braces", {"name": "Aminata"}],
    ["phrase", "notes.kept", {"n": 1}],
    ["phrase", "notes.rows", {"n": 3}],
    ["phrase", "notes.both", {"n": 1200, "m": 2}],
    ["phrase", "sheet.title", {"place": "Kuntolo"}],
    ["table", "sheet.answers", None],
    ["table", "sheet.answers", None],
    ["row", "sheet.answers", "maybe"],
    ["row", "sheet.title", "yes"],
    ["row", "sheet.missing", "yes"],
    ["phrase", "sheet.missing", {}],
    ["phrase", "missing.title", {}],
    ["phrase", "nodot", {}],
    ["phrase", "sheet.answers", {}],
    ["table", "sheet.title", None],
    ["phrase", "sheet.title", {}],
    ["phrase", "sheet.title", {"place": "Rokel", "more": "x"}],
    ["phrase", "sheet.title", {"place": 7}],
    # a value the sentence does not use is refused whatever it is named
    ["phrase", "sheet.title", {"place": "Rokel", "constructor": "x"}],
    ["phrase", "sheet.title", {"place": "Rokel", "toString": "x"}],
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
                        else say.row(ident, values) if kind == "row"
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

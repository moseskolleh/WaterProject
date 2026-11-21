"""The words both engines write, read from ``data/text/*.yaml``.

A sentence the Python reports and the browser's reports both print used to
be typed out twice, once here and once in ``docs/js``, and the parity suite
then compared the two word for word. It is now written once, in a catalogue
file, and both engines read it: this module here, and the browser through
``GWT.data.text``, which ``web/build_webapp_data.py`` emits from the same
files. ``renderText`` in ``docs/js/gwt-core.js`` is the same renderer as
:func:`render_text`, rule for rule.

Each file under ``data/text`` is a namespace, and an entry is named by the
file and its key: ``quality.treat_health`` is the key ``treat_health`` in
``quality.yaml``. An entry is either a sentence template (a string) or a
table (a mapping of strings looked up by a value from the data, such as a
parameter name or a citation key). Only the top-level files are read, so a
translation can later sit beside them in a folder of its own.

A template names its values in braces, and a number always says how it is
written, because the two engines print a bare number differently (Python
writes 5.0 where JavaScript writes 5):

    {name}                 a string, inserted as it is
    {name:num}             fmt_num: three significant figures, thousands
                           separated ("1,250", "0.75", "n/a")
    {name:g}               Python's "g" format ("5", "1.25")
    {name:.0f}             fixed decimals, rounded as Python rounds
    {name:plural:one|other}  "one" when the count is 1, "other" otherwise
    {{ and }}              literal braces

A missing value, a value the template does not use, a number given to a
plain ``{name}`` and a stray brace are all errors rather than a sentence
with a hole in it.

Other languages (PLAN.md step 9.2)
----------------------------------

English is the working language and the catalogue above is the English. A
translation is a folder beside it named for the language, ``data/text/kri``
for Krio, holding:

- ``language.yaml``: the language's ``name``, who it was ``translated_by``
  and who it was ``checked_by``. PLAN.md asks that community-facing text be
  translated and checked by native speakers, and forbids a machine
  translation, so a folder that does not name both is not offered by
  :func:`languages`, whatever else it holds;
- files named as the English ones are, each with as many of that file's
  entries as have been translated. An entry not there is said in English
  (:class:`Speaker` keeps count, so that whoever builds a document is told),
  and a table may translate some of its rows.

A translated sentence has to take the same values as the English one, each
written as the English writes it; only the word of a plural may be left out,
never the number. :func:`translation_problems` lists every place a
translation does not hold to this (an entry English does not have, a
sentence where English has a table, a placeholder missing, added or
reformatted, a file that cannot be read), and a translation with a problem
is not offered either. The same rules are
``translationProblems`` in ``docs/js/gwt-core.js``, which reads the same
folders as ``GWT.data.translations``.

Only what a community reads is said through a :class:`Speaker` (today the
community handover sheet). The reports, and every note to whoever builds a
document, stay in English.
"""

from __future__ import annotations

import functools
import json
import math
import numbers
import re
from importlib import resources

import yaml

from .utils import fmt_num

__all__ = ["render_text", "phrase", "phrase_table", "text_catalogue",
           "Speaker", "languages", "read_translations", "same_as_english",
           "translation_problems", "translations", "untranslated"]

# The one grammar, held to the same pattern in gwt-core.js. The alternation
# matches an escape, a placeholder or a lone brace, in that order, so a lone
# brace can be reported instead of passed through.
_TOKEN = re.compile(
    r"\{\{|\}\}"
    r"|\{([a-z_][a-z0-9_]*)(?::(num|g|\.[0-9]+f|plural:[^{}|]*\|[^{}|]*))?\}"
    r"|[{}]"
)


def _format(name: str, spec: str | None, value) -> str:
    if spec is None:
        if not isinstance(value, str):
            raise TypeError(
                f"text: {{{name}}} takes a string; a number names its format, "
                f"as {{{name}:num}}"
            )
        return value
    if spec.startswith("plural:"):
        # a whole number, whatever its type: JavaScript cannot tell 2.0 from
        # 2, so a count of 2.0 is refused by neither engine
        if (isinstance(value, bool) or not isinstance(value, numbers.Real)
                or not math.isfinite(value) or value != int(value)):
            raise TypeError(f"text: {{{name}:plural:...}} takes a whole count")
        one, other = spec[len("plural:"):].split("|")
        return one if value == 1 else other
    # numbers.Real rather than int and float, so a numpy scalar out of a
    # fitted array is a number here too
    if ((isinstance(value, bool) or not isinstance(value, numbers.Real))
            and not (spec == "num" and value is None)):
        raise TypeError(f"text: {{{name}:{spec}}} takes a number, not {value!r}")
    if spec == "num":
        return fmt_num(value)
    return format(value, spec)


def render_text(template: str, values: dict | None = None) -> str:
    """``template`` with its placeholders filled from ``values``."""
    values = values or {}
    used: set[str] = set()

    def fill(match: re.Match) -> str:
        token = match.group(0)
        if token in ("{{", "}}"):
            return token[0]
        name = match.group(1)
        if name is None:
            raise ValueError(f"text: a lone {token!r} in {template!r}; write {token * 2}")
        if name not in values:
            raise KeyError(f"text: no value for {{{name}}} in {template!r}")
        used.add(name)
        return _format(name, match.group(2), values[name])

    text = _TOKEN.sub(fill, template)
    unused = set(values) - used
    if unused:
        raise KeyError(f"text: {sorted(unused)} are not in {template!r}")
    return text


@functools.lru_cache(maxsize=1)
def text_catalogue() -> dict[str, dict]:
    """Every catalogue file, by namespace. Shared: treat it as read-only."""
    folder = resources.files("groundwater") / "data" / "text"
    catalogue = {}
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".yaml") and entry.is_file():
            catalogue[entry.name[: -len(".yaml")]] = yaml.safe_load(
                entry.read_text(encoding="utf-8")
            )
    return catalogue


def _entry(ident: str):
    namespace, _, key = ident.partition(".")
    try:
        return text_catalogue()[namespace][key]
    except KeyError:
        raise KeyError(f"text: no entry {ident!r} in data/text") from None


def phrase(ident: str, **values) -> str:
    """The sentence ``ident`` names, with ``values`` filled in."""
    template = _entry(ident)
    if not isinstance(template, str):
        raise TypeError(f"text: {ident!r} is a table; read it with phrase_table")
    return render_text(template, values)


def phrase_table(ident: str) -> dict[str, str]:
    """The table ``ident`` names: literal text, keyed by a value from the data."""
    table = _entry(ident)
    if not isinstance(table, dict):
        raise TypeError(f"text: {ident!r} is a sentence; read it with phrase")
    return table


# ----------------------------------------------------------- other languages

#: What ``language.yaml`` has to say before a translation is offered.
LANGUAGE_FACTS = ("name", "translated_by", "checked_by")

_LANGUAGE_CODE = re.compile(r"^[a-z]{2,8}\Z")

#: How what :func:`read_translations` keeps for a file it could not read
#: begins. Both engines tell such a file by it.
UNREADABLE = "cannot be read"

# The white space taken off the ends of a sentence, a row and a fact, and
# what makes one blank. Written out, and the same list in gwt-core.js:
# Python's str.strip() and JavaScript's trim() do not take the same
# characters (a byte-order mark is space to one and the file separators to
# the other), and a translation one app offered and the other refused would
# follow. This is every character either takes.
_EDGE = ("\t\n\v\f\r \x1c\x1d\x1e\x1f\x85\xa0        "
         "        　﻿")

# Every run of white space, of whatever kind, is printed as one space. The
# browser's document writer closes up all of it and the Python one none of
# it, so a no-break space a translator typed would otherwise be printed two
# ways. Written out (the list above) rather than \s, which the two engines
# read differently.
_SPACES = re.compile("[" + re.escape(_EDGE) + "]+")


def _trimmed(value: str) -> str:
    return value.strip(_EDGE)


def _tidy(text: str) -> str:
    """Translated text as it is printed: a long dash as a hyphen with spaces
    and a short one as a hyphen, each run of white space one space, the ends
    trimmed. The two document writers tidy text differently; done here, to
    the sentence once its values are in it, both are handed text neither has
    cause to change, as typed text is (``community_sheet.sheet_text``)."""
    return _trimmed(_SPACES.sub(" ", text.replace("—", " - ").replace("–", "-")))


def _read_file(item):
    """One file of a translation as both engines hold it: what YAML makes of
    it, carried through JSON as the browser's copy is (a row keyed 2 is keyed
    "2", a date is its text). A file that cannot be read is kept as the
    reason, in words, so that only its language is refused."""
    try:
        text = item.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"{UNREADABLE}: it is not saved as UTF-8 text"
    try:
        loaded = yaml.safe_load(text)
        return json.loads(json.dumps(loaded, default=str, allow_nan=False))
    except yaml.reader.ReaderError as error:
        # a character YAML does not allow (a soft line break pasted from a
        # word processor, a letter left by a wrong re-encoding): told by its
        # place in the text, since it has no mark
        before = text[: error.position]
        return (f"{UNREADABLE}: line {before.count(chr(10)) + 1}, column "
                f"{len(before) - (before.rfind(chr(10)) + 1) + 1}: a character that cannot be "
                f"in the file (U+{error.character:04X})")
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark is not None else ""
        return f"{UNREADABLE}: {where}{getattr(error, 'problem', None) or 'it is not YAML'}"
    except (TypeError, ValueError):
        return f"{UNREADABLE}: it holds something that is not text, a number or a list"


def read_translations(folder) -> dict[str, dict]:
    """The translations in ``folder``, one to a subfolder, by the subfolder's
    name: ``{"language": the facts of language.yaml, "text": {namespace:
    entries}}``. Whether each can be offered is :func:`translation_problems`'
    to say; nothing is refused here, so that it can be told why, and a file
    that cannot be read (a sentence that needed quotes, a file saved in
    another encoding) is kept as the reason rather than raised: one
    language's slip does not stop the others, or the English."""
    found: dict[str, dict] = {}
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        # not a translation: Python's own folders, and anything hidden
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        facts, text = {}, {}
        for item in sorted(entry.iterdir(), key=lambda e: e.name):
            if not (item.name.endswith(".yaml") and item.is_file()):
                continue
            if item.name == "language.yaml":
                facts = _read_file(item)
            else:
                text[item.name[: -len(".yaml")]] = _read_file(item)
        found[entry.name] = {"language": facts, "text": text}
    return found


@functools.lru_cache(maxsize=1)
def translations() -> dict[str, dict]:
    """Every translation the package bundles, by language code
    (:func:`read_translations` of ``data/text``). Shared: treat it as
    read-only."""
    return read_translations(resources.files("groundwater") / "data" / "text")


def _placeholders(template: str) -> dict[str, set[str]] | None:
    """Each value a template takes, with the formats it writes it in; None
    where the template does not parse (a lone brace)."""
    taken: dict[str, set[str]] = {}
    for match in _TOKEN.finditer(template):
        if match.group(0) in ("{{", "}}"):
            continue
        if match.group(1) is None:
            return None
        spec = match.group(2) or ""
        # the two words of a plural are the translation's own to choose
        taken.setdefault(match.group(1), set()).add("plural" if spec.startswith("plural:")
                                                    else spec)
    return taken


def _same_values(mine: dict[str, set[str]], theirs: dict[str, set[str]]) -> bool:
    """Whether a translated sentence takes the values the English one takes,
    each written as the English writes it. The value itself is printed every
    way the English prints it and no other: a sentence that kept the word
    "jerrycans" and lost their number would pass a looser rule. Only the
    word that agrees with a count may be left out, by a language that has no
    need of it, and it may not be added where English has none."""
    if set(mine) != set(theirs):
        return False
    return all(mine[name] - {"plural"} == theirs[name] - {"plural"}
               and ("plural" not in mine[name] or "plural" in theirs[name])
               for name in theirs)


def _unreadable(value) -> bool:
    return isinstance(value, str) and value.startswith(UNREADABLE)


def translation_problems(code: str, held: dict | None = None,
                         english: dict | None = None) -> list[str]:
    """Every reason the translation ``code`` cannot be offered, in words; an
    empty list where it can. ``held`` is the translations to read (the
    bundled ones by default) and ``english`` the catalogue they translate.

    An entry that is not translated, whether left out or named with nothing
    after it, is not a problem: it is said in English. These are: a code
    that is not two to eight small letters; a file that could not be read; a
    language that does not say what it is, who translated it and who checked
    it; a file or an entry English does not have; a sentence where English
    has a table, or the other way round; a table row English does not have;
    a sentence or a row that is blank; and a sentence that does not take the
    values the English one takes, each written as the English writes it.
    """
    held = translations() if held is None else held
    english = text_catalogue() if english is None else english
    if code not in held:
        return [f"there is no translation {code!r}"]
    entry = held[code]
    facts = entry.get("language") or {}
    problems = [] if _LANGUAGE_CODE.match(code) else [
        f"{code!r} is not a language's code (two to eight small letters)"]
    if _unreadable(facts):
        problems.append(f"language.yaml {facts}")
    else:
        problems += [f"language.yaml does not say {fact}" for fact in LANGUAGE_FACTS
                     if not (isinstance(facts, dict) and isinstance(facts.get(fact), str)
                             and _trimmed(facts[fact]))]
    for namespace in sorted(entry.get("text") or {}):
        entries = entry["text"][namespace]
        if namespace not in english:
            problems.append(f"{namespace}.yaml translates a file English does not have")
            continue
        if entries is None:
            # a file with nothing in it yet
            continue
        if _unreadable(entries):
            problems.append(f"{namespace}.yaml {entries}")
            continue
        if not isinstance(entries, dict):
            problems.append(f"{namespace}.yaml is not a list of entries")
            continue
        for key in sorted(entries, key=str):
            ident, value, source = f"{namespace}.{key}", entries[key], english[namespace].get(key)
            if source is None:
                problems.append(f"{ident} is not an entry of the English")
            elif value is None:
                # named and left empty: not translated yet
                continue
            elif isinstance(source, dict):
                if not isinstance(value, dict):
                    problems.append(f"{ident} is a table in English and a sentence here")
                    continue
                for row in sorted(value, key=str):
                    if row not in source:
                        problems.append(f"{ident}[{row}] is not a row of the English table")
                    elif value[row] is None:
                        continue
                    elif not isinstance(value[row], str) or "{" in value[row] or "}" in value[row]:
                        problems.append(f"{ident}[{row}] is not plain text")
                    elif not _trimmed(value[row]):
                        problems.append(f"{ident}[{row}] is blank")
            elif not isinstance(value, str):
                problems.append(f"{ident} is a sentence in English and not one here")
            elif not _trimmed(value):
                problems.append(f"{ident} is blank")
            else:
                mine, theirs = _placeholders(value), _placeholders(source)
                if mine is None:
                    problems.append(f"{ident} has a lone brace")
                elif theirs is not None and not _same_values(mine, theirs):
                    problems.append(
                        f"{ident} does not take the values the English takes "
                        f"({', '.join(sorted(theirs)) or 'none'}), each written as the English "
                        "writes it")
    return problems


def _facts(held: dict, code: str) -> dict:
    return {"code": code, **{fact: _trimmed(held[code]["language"][fact])
                             for fact in LANGUAGE_FACTS}}


def languages(held: dict | None = None, english: dict | None = None) -> list[dict]:
    """The translations that can be offered, as ``{"code", "name",
    "translated_by", "checked_by"}``, by name: those with no problem."""
    held = translations() if held is None else held
    offered = [_facts(held, code) for code in sorted(held)
               if not translation_problems(code, held, english)]
    return sorted(offered, key=lambda language: (language["name"], language["code"]))


def _each(code: str, idents, held: dict | None, english: dict | None):
    """Each entry ``idents`` names, a table row by row, as ``(what it is
    called, the English, the translation's words or None)``."""
    held = translations() if held is None else held
    english = text_catalogue() if english is None else english
    text = (held.get(code) or {}).get("text") or {}
    for ident in idents:
        namespace, _, key = ident.partition(".")
        source = english[namespace][key]
        file = text.get(namespace)
        mine = file.get(key) if isinstance(file, dict) else None
        if isinstance(source, dict):
            if not isinstance(mine, dict):
                yield ident, None, None
                continue
            for row in source:
                yield f"{ident}[{row}]", source[row], mine.get(row)
        else:
            yield ident, source, mine


def untranslated(code: str, idents, held: dict | None = None,
                 english: dict | None = None) -> list[str]:
    """Of the entries ``idents`` names, those the translation ``code`` has no
    words for yet, in the order given; a table that has some of its rows is
    told row by row, as ``ident[row]``. What a :class:`Speaker` of it would
    say in English."""
    return [name for name, _, mine in _each(code, idents, held, english) if mine is None]


def same_as_english(code: str, idents, held: dict | None = None,
                    english: dict | None = None) -> list[str]:
    """Of the entries ``idents`` names, those the translation ``code`` words
    exactly as the English does. Some should be (a unit, a name); the rest
    are a copy of the English file that was not yet translated, which the
    rules cannot tell from a translation and a person can."""
    return [name for name, source, mine in _each(code, idents, held, english)
            if isinstance(mine, str) and isinstance(source, str)
            and _tidy(mine) == _tidy(source)]


class Speaker:
    """The catalogue in one language, with English where it has no words.

    ``Speaker("")`` is English. ``Speaker("kri")`` says each sentence in
    Krio where the translation has it and in English where it does not, and
    keeps in ``fell_back`` what it had to say in English, each once, in the
    order it was first asked for: a sentence or a whole table by its name, a
    single row asked for with :meth:`row` as ``name[row]``. A language that
    cannot be offered (:func:`translation_problems`) is refused with its
    reasons. Translated text is tidied as typed text is (:func:`_tidy`).
    """

    def __init__(self, code: str = "", held: dict | None = None, english: dict | None = None):
        self.code = code or ""
        self.fell_back: list[str] = []
        self.language: dict = {}
        self._english = text_catalogue() if english is None else english
        self._text: dict = {}
        if self.code:
            held = translations() if held is None else held
            problems = translation_problems(self.code, held, self._english)
            if problems:
                raise ValueError(f"text: the translation {self.code!r} cannot be used: "
                                 + "; ".join(problems))
            self._text = held[self.code].get("text") or {}
            self.language = _facts(held, self.code)

    def _source(self, ident: str):
        namespace, _, key = ident.partition(".")
        try:
            return namespace, key, self._english[namespace][key]
        except KeyError:
            raise KeyError(f"text: no entry {ident!r} in data/text") from None

    def _missed(self, ident: str) -> None:
        if self.code and ident not in self.fell_back:
            self.fell_back.append(ident)

    def _mine(self, namespace: str, key: str):
        return (self._text.get(namespace) or {}).get(key)

    def phrase(self, ident: str, **values) -> str:
        """The sentence ``ident`` names, in this language or in English."""
        namespace, key, source = self._source(ident)
        if not isinstance(source, str):
            raise TypeError(f"text: {ident!r} is a table; read it with phrase_table")
        mine = self._mine(namespace, key)
        if mine is None:
            self._missed(ident)
            return render_text(source, values)
        # tidied once it is filled: a plural with no word for one leaves
        # two spaces where the word would have been
        return _tidy(render_text(mine, values))

    def phrase_table(self, ident: str) -> dict[str, str]:
        """The whole table ``ident`` names, each row in this language or in
        English. For a table every row of which is printed; where one row is
        chosen, :meth:`row` keeps a truer count of what fell back."""
        namespace, key, source = self._source(ident)
        if not isinstance(source, dict):
            raise TypeError(f"text: {ident!r} is a sentence; read it with phrase")
        mine = self._mine(namespace, key) or {}
        if any(mine.get(row) is None for row in source):
            self._missed(ident)
        return {row: text if mine.get(row) is None else _tidy(mine[row])
                for row, text in source.items()}

    def row(self, ident: str, row: str) -> str:
        """One row of the table ``ident`` names, in this language or in
        English."""
        namespace, key, source = self._source(ident)
        if not isinstance(source, dict):
            raise TypeError(f"text: {ident!r} is a sentence; read it with phrase")
        if row not in source:
            raise KeyError(f"text: no row {row!r} in {ident!r}")
        mine = (self._mine(namespace, key) or {}).get(row)
        if mine is None:
            self._missed(f"{ident}[{row}]")
            return source[row]
        return _tidy(mine)

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
in a format the English allows it: :func:`translation_problems` lists every
place a translation does not (an entry English does not have, a sentence
where English has a table, a placeholder missing, added or reformatted),
and a translation with a problem is not offered either. The same rules are
``translationProblems`` in ``docs/js/gwt-core.js``, which reads the same
folders as ``GWT.data.translations``.

Only what a community reads is said through a :class:`Speaker` (today the
community handover sheet). The reports, and every note to whoever builds a
document, stay in English.
"""

from __future__ import annotations

import functools
import math
import numbers
import re
from importlib import resources

import yaml

from .utils import fmt_num

__all__ = ["render_text", "phrase", "phrase_table", "text_catalogue",
           "Speaker", "languages", "read_translations", "translation_problems",
           "translations", "untranslated"]

# The one grammar, held to the same pattern in gwt-core.js. The alternation
# matches an escape, a placeholder or a lone brace, in that order, so a lone
# brace can be reported instead of passed through.
_TOKEN = re.compile(
    r"\{\{|\}\}"
    r"|\{([a-z_][a-z0-9_]*)(?::(num|g|\.\d+f|plural:[^{}|]*\|[^{}|]*))?\}"
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


def read_translations(folder) -> dict[str, dict]:
    """The translations in ``folder``, one to a subfolder, by the subfolder's
    name: ``{"language": the facts of language.yaml, "text": {namespace:
    entries}}``. Whether each can be offered is :func:`translation_problems`'
    to say; nothing is refused here, so that it can be told why."""
    found: dict[str, dict] = {}
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        # not a translation: Python's own folders, and anything hidden
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        facts, text = {}, {}
        for item in sorted(entry.iterdir(), key=lambda e: e.name):
            if not (item.name.endswith(".yaml") and item.is_file()):
                continue
            loaded = yaml.safe_load(item.read_text(encoding="utf-8"))
            if item.name == "language.yaml":
                facts = loaded
            else:
                text[item.name[: -len(".yaml")]] = loaded
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


def translation_problems(code: str, held: dict | None = None,
                         english: dict | None = None) -> list[str]:
    """Every reason the translation ``code`` cannot be offered, in words; an
    empty list where it can. ``held`` is the translations to read (the
    bundled ones by default) and ``english`` the catalogue they translate.

    An entry that is not translated, whether left out or named and left
    empty, is not a problem: it is said in English. These are: a code that
    is not two to eight small letters; a language that does not say what it
    is, who translated it and who checked it; a file or an entry English
    does not have; a sentence where English has a table, or the other way
    round; a table row English does not have; a sentence or a row that is
    blank; and a sentence that does not take the values the English one
    takes, each in a format the English uses.
    """
    held = translations() if held is None else held
    english = text_catalogue() if english is None else english
    if code not in held:
        return [f"there is no translation {code!r}"]
    entry = held[code]
    facts = entry.get("language") or {}
    problems = [] if _LANGUAGE_CODE.match(code) else [
        f"{code!r} is not a language's code (two to eight small letters)"]
    problems += [f"language.yaml does not say {fact}" for fact in LANGUAGE_FACTS
                 if not (isinstance(facts, dict) and isinstance(facts.get(fact), str)
                         and facts[fact].strip())]
    for namespace in sorted(entry.get("text") or {}):
        entries = entry["text"][namespace]
        if namespace not in english:
            problems.append(f"{namespace}.yaml translates a file English does not have")
            continue
        if entries is None:
            # a file with nothing in it yet
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
                    elif not value[row].strip():
                        problems.append(f"{ident}[{row}] is blank")
            elif not isinstance(value, str):
                problems.append(f"{ident} is a sentence in English and not one here")
            elif not value.strip():
                problems.append(f"{ident} is blank")
            else:
                mine, theirs = _placeholders(value), _placeholders(source)
                if mine is None:
                    problems.append(f"{ident} has a lone brace")
                elif theirs is not None and (set(mine) != set(theirs) or any(
                        not mine[name] <= theirs[name] for name in mine)):
                    problems.append(
                        f"{ident} does not take the values the English takes "
                        f"({', '.join(sorted(theirs)) or 'none'}), each in a format it uses")
    return problems


def languages(held: dict | None = None, english: dict | None = None) -> list[dict]:
    """The translations that can be offered, as ``{"code", "name",
    "translated_by", "checked_by"}``, by name: those with no problem."""
    held = translations() if held is None else held
    offered = []
    for code in sorted(held):
        if not translation_problems(code, held, english):
            facts = held[code]["language"]
            offered.append({"code": code, **{fact: facts[fact].strip() for fact in LANGUAGE_FACTS}})
    return sorted(offered, key=lambda language: (language["name"], language["code"]))


def untranslated(code: str, idents, held: dict | None = None,
                 english: dict | None = None) -> list[str]:
    """Of the entries ``idents`` names, those the translation ``code`` has no
    words for yet, in the order given; a table that has some of its rows is
    told row by row, as ``ident[row]``. What a :class:`Speaker` of it would
    say in English."""
    held = translations() if held is None else held
    english = text_catalogue() if english is None else english
    text = (held.get(code) or {}).get("text") or {}
    missing: list[str] = []
    for ident in idents:
        namespace, _, key = ident.partition(".")
        source = english[namespace][key]
        mine = (text.get(namespace) or {}).get(key)
        if mine is None:
            missing.append(ident)
        elif isinstance(source, dict) and isinstance(mine, dict):
            missing += [f"{ident}[{row}]" for row in source if mine.get(row) is None]
    return missing


class Speaker:
    """The catalogue in one language, with English where it has no words.

    ``Speaker("")`` is English. ``Speaker("kri")`` says each sentence in
    Krio where the translation has it and in English where it does not, and
    keeps in ``fell_back`` the entries it had to say in English, each once,
    in the order they were first asked for. A language that cannot be
    offered (:func:`translation_problems`) is refused with its reasons.
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
            self.language = {"code": self.code, **{
                fact: held[self.code]["language"][fact].strip() for fact in LANGUAGE_FACTS}}

    def _source(self, ident: str):
        namespace, _, key = ident.partition(".")
        try:
            return namespace, key, self._english[namespace][key]
        except KeyError:
            raise KeyError(f"text: no entry {ident!r} in data/text") from None

    def _missed(self, ident: str) -> None:
        if self.code and ident not in self.fell_back:
            self.fell_back.append(ident)

    def phrase(self, ident: str, **values) -> str:
        """The sentence ``ident`` names, in this language or in English."""
        namespace, key, source = self._source(ident)
        if not isinstance(source, str):
            raise TypeError(f"text: {ident!r} is a table; read it with phrase_table")
        mine = (self._text.get(namespace) or {}).get(key)
        if mine is None:
            self._missed(ident)
        return render_text(source if mine is None else mine, values)

    def phrase_table(self, ident: str) -> dict[str, str]:
        """The table ``ident`` names, each row in this language or English."""
        namespace, key, source = self._source(ident)
        if not isinstance(source, dict):
            raise TypeError(f"text: {ident!r} is a sentence; read it with phrase")
        mine = (self._text.get(namespace) or {}).get(key) or {}
        if any(mine.get(row) is None for row in source):
            self._missed(ident)
        return {row: text if mine.get(row) is None else mine[row]
                for row, text in source.items()}


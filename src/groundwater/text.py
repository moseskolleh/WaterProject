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
"""

from __future__ import annotations

import functools
import re
from importlib import resources

import yaml

from .utils import fmt_num

__all__ = ["render_text", "phrase", "phrase_table", "text_catalogue"]

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
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"text: {{{name}:plural:...}} takes a whole count")
        one, other = spec[len("plural:"):].split("|")
        return one if value == 1 else other
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if not (spec == "num" and value is None):
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

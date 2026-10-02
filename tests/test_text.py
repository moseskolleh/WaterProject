"""The shared words: data/text/*.yaml, and the one renderer both engines run.

A sentence both engines write is kept once, in the catalogue, and these
tests hold the catalogue to that: every file is well formed, every entry is
read by both engines, none of the catalogued sentences is still typed out in
either engine's source, and the browser's renderer gives the same text as
groundwater.text for the same template and values.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from groundwater.text import phrase, phrase_table, render_text, text_catalogue

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"
# generated from the catalogue, so of course they carry its words
GENERATED_JS = {"gwt-data.js", "gwt-geo.js", "gwt-samples.js"}

_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_PLACEHOLDER = re.compile(
    r"\{\{|\}\}"
    r"|\{([a-z_][a-z0-9_]*)(?::(num|g|\.\d+f|plural:[^{}|]*\|[^{}|]*))?\}"
    r"|[{}]"
)


def _python_source() -> str:
    paths = sorted((REPO / "src" / "groundwater").rglob("*.py"))
    paths += sorted((REPO / "app").rglob("*.py"))
    return "\n".join(p.read_text(encoding="utf-8") for p in paths)


def _js_source() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(JS.glob("*.js"))
        if p.name not in GENERATED_JS
    )


def _joined(source: str) -> str:
    """Source with string literals that are split across lines joined up.

    Both engines wrap a long sentence over several literals - adjacent ones
    in Python, ``' +`` in JavaScript - so a sentence that is still typed out
    does not appear in the file as one run of text until they are joined.
    """
    return re.sub(r"""(['"])[\s+]*[fFrRbB]{0,2}\1""", "", source)


def _entries():
    """(id, text) for every sentence, and for every row of every table."""
    for namespace, entries in text_catalogue().items():
        for key, value in entries.items():
            if isinstance(value, dict):
                for row, text in value.items():
                    yield f"{namespace}.{key}[{row}]", text
            else:
                yield f"{namespace}.{key}", value


def test_the_catalogue_is_well_formed():
    """Every entry is a sentence or a table of sentences, named so the code
    can quote it, and every template parses."""
    catalogue = text_catalogue()
    names = sorted(p.stem for p in (REPO / "src" / "groundwater" / "data" / "text")
                   .glob("*.yaml"))
    assert names and sorted(catalogue) == names
    for namespace, entries in catalogue.items():
        assert _ID.match(namespace), namespace
        assert isinstance(entries, dict) and entries, namespace
        for key, value in entries.items():
            assert _ID.match(key), f"{namespace}.{key}"
            if isinstance(value, dict):
                assert value, f"{namespace}.{key} is an empty table"
                for row, text in value.items():
                    assert isinstance(row, str) and isinstance(text, str), (
                        f"{namespace}.{key}[{row!r}]")
                    # a table row is printed as it stands, never rendered
                    assert "{" not in text and "}" not in text, (
                        f"{namespace}.{key}[{row!r}]")
            else:
                assert isinstance(value, str), (
                    f"{namespace}.{key} is {type(value).__name__}; quote it")
                for match in _PLACEHOLDER.finditer(value):
                    assert match.group(0) in ("{{", "}}") or match.group(1), (
                        f"{namespace}.{key}: a lone brace")
    for ident, text in _entries():
        # a folded YAML scalar is one line; a stray newline or a doubled
        # space is a typing slip a reader of the report would see
        assert text == text.strip() and "\n" not in text and "  " not in text, ident


def test_every_entry_is_read_by_both_engines():
    """An entry is named, quoted, in the Python package and in the browser.

    The point of the catalogue is a sentence both engines write. One that
    only one engine reads is either dead or a sentence the other engine
    still types out for itself.
    """
    python, js = _python_source(), _js_source()
    for namespace, entries in text_catalogue().items():
        for key in entries:
            ident = re.escape(f"{namespace}.{key}")
            quoted = re.compile(rf"""['"]{ident}['"]""")
            assert quoted.search(python), f"the Python package never reads {namespace}.{key}"
            assert quoted.search(js), f"the browser never reads {namespace}.{key}"


def _typed_out(text: str, source: str) -> list[str]:
    """The pieces of ``text`` that ``source`` still spells out as literals.

    A piece is a run of literal text between placeholders, long enough to be
    a phrase rather than a word. It is looked for as a string literal would
    hold it: opened by a quote (or, in an f-string, by the end of a
    placeholder) and closed by one (or by the start of the next), so a
    different sentence that happens to begin with the same words - the
    verdict's "Acceptability limits are exceeded for: ..." - is not
    mistaken for a copy.
    """
    found = []
    for piece in _PLACEHOLDER.sub("\0", text).split("\0"):
        if len(piece.strip()) >= 20:
            if re.search(r"""['"}]""" + re.escape(piece) + r"""['"{]""", source):
                found.append(piece)
    return found


def test_no_catalogued_sentence_is_still_typed_out():
    """No engine carries its own copy of a catalogued sentence.

    Both engines' source is searched with wrapped string literals joined
    up. A copy left behind is how the two engines came to word one list two
    ways, and it is the copy a later edit would forget.
    """
    python, js = _joined(_python_source()), _joined(_js_source())
    for ident, text in _entries():
        assert not _typed_out(text, python), f"{ident} is still typed out in src/ or app/"
        assert not _typed_out(text, js), f"{ident} is still typed out in docs/js"


def test_the_treatment_advice_is_keyed_by_standards_table_names():
    """A key the standards table does not have is advice nobody can be given."""
    from groundwater.quality.standards import load_standards

    # and the WHO combined rule's own row, "Nitrate + nitrite (combined)",
    # which normalises to "nitrate + nitrite"
    names = set(load_standards()) | {"nitrate + nitrite"}
    advice = phrase_table("quality.treatment_advice")
    assert set(advice) <= names, sorted(set(advice) - names)


# --------------------------------------------------------------- the renderer

# (template, values) pairs both renderers are given; an expected text of
# None means both must refuse.
RENDER_CASES = [
    ("plain words", {}, "plain words"),
    ("{a} and {b}", {"a": "x", "b": "y"}, "x and y"),
    ("{d:num} m", {"d": 62.0}, "62 m"),
    ("{d:num} m", {"d": 1250}, "1,250 m"),
    ("{d:num} m", {"d": 0.7512}, "0.751 m"),
    ("{d:num} m", {"d": None}, "n/a m"),
    ("{d:g} inch", {"d": 5.0}, "5 inch"),
    ("{d:g} inch", {"d": 1.25}, "1.25 inch"),
    ("{d:g} inch", {"d": 4}, "4 inch"),
    ("{d:.0f} mm", {"d": 19.4}, "19 mm"),
    ("{d:.0f} mm", {"d": 18.5}, "18 mm"),
    ("{d:.1f} mm", {"d": 14.05}, "14.1 mm"),
    ("{d:.2f}", {"d": 2.675}, "2.67"),
    ("{n:num} {n:plural:limit|limits}", {"n": 1}, "1 limit"),
    ("{n:num} {n:plural:limit|limits}", {"n": 3}, "3 limits"),
    ("{n:plural:series|series}", {"n": 0}, "series"),
    ("{{literal}} {a}", {"a": "x"}, "{literal} x"),
    # refused: a hole, a spare value, a bare number, a lone brace
    ("{a}", {}, None),
    ("words", {"a": "x"}, None),
    ("{a}", {"a": 5.0}, None),
    ("{a:num}", {"a": "5"}, None),
    ("{n:plural:one|many}", {"n": 1.5}, None),
    ("a { b", {}, None),
    ("{A}", {"A": "x"}, None),
]


@pytest.mark.parametrize("template,values,expected", RENDER_CASES)
def test_render_text(template, values, expected):
    if expected is None:
        with pytest.raises((KeyError, TypeError, ValueError)):
            render_text(template, values)
    else:
        assert render_text(template, values) == expected


def test_phrase_reads_the_catalogue():
    assert phrase("quality.treat_health", parameters="Arsenic").endswith(
        "exceeded for Arsenic.")
    with pytest.raises(KeyError):
        phrase("quality.no_such_entry")
    with pytest.raises(TypeError):
        phrase("quality.treatment_advice")
    with pytest.raises(TypeError):
        phrase_table("quality.treat_health")


_JS_RENDER = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
for (const f of ['support.js', 'gwt-data.js', 'gwt-core.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox,
    { filename: f });
}
const C = sandbox.GWT.core;
const cases = JSON.parse(readFileSync(process.argv[3], 'utf8'));
writeFileSync(process.argv[4], JSON.stringify({
  rendered: cases.map(([template, values]) => {
    try { return C.renderText(template, values); } catch (e) { return null; }
  }),
  catalogue: sandbox.GWT.data.text,
}));
"""


def test_the_browser_renders_the_same_text(tmp_path):
    """renderText in gwt-core.js gives what render_text gives, refusals
    included, and the bundle carries the catalogue as Python reads it."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    script = tmp_path / "render.mjs"
    script.write_text(_JS_RENDER, encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([[t, v] for t, v, _ in RENDER_CASES]), encoding="utf-8")
    out = tmp_path / "out.json"
    subprocess.run([node, str(script), str(JS), str(cases), str(out)],
                   check=True, timeout=120)
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["rendered"] == [expected for _, _, expected in RENDER_CASES]
    assert result["catalogue"] == text_catalogue(), (
        "docs/js/gwt-data.js carries another catalogue; "
        "run: python web/build_webapp_data.py")

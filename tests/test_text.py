"""The shared words and constants: data/text/*.yaml, the one renderer both
engines run, and data/defaults.json.

A sentence both engines write is kept once, in the catalogue, and these
tests hold the catalogue to that: every file is well formed, every entry is
read by both engines, none of the catalogued sentences is still typed out in
either engine's source, and the browser's renderer gives the same text as
groundwater.text for the same template and values. The configuration
defaults are held the same way: one file, the shape of Config, and no copy
of it left in either engine.
"""

from __future__ import annotations

import json
import math
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from groundwater.text import _TOKEN as _PLACEHOLDER
from groundwater.text import phrase, phrase_table, render_text, text_catalogue

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"
# generated from the catalogue, so of course they carry its words
GENERATED_JS = {"gwt-data.js", "gwt-geo.js", "gwt-samples.js"}

_ID = re.compile(r"^[a-z][a-z0-9_]*$")


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
        if len(piece.strip()) >= 20 and re.search(
                r"""['"}]""" + re.escape(piece) + r"""['"{]""", source):
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
        if ident.endswith(f"[{text}]"):
            # a table row that prints its own key ("gravel pack") is the
            # data's vocabulary, which the code compares against, not a copy
            continue
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


def test_every_citation_closes_some_report_and_every_cited_one_exists():
    """The reference table holds what the reports cite and nothing else.

    citations.py drops a key it cannot find, and the browser would print
    "undefined" under References, so a misspelt key is caught here.
    """
    from groundwater.reporting.citations import _REFERENCES_FOR

    table = set(phrase_table("references.citations"))
    python = {key for keys in _REFERENCES_FOR.values() for key in keys}
    js = set(re.findall(r"\bREFERENCES\.(\w+)",
                        (JS / "gwt-docx.js").read_text(encoding="utf-8")))
    assert python <= table, sorted(python - table)
    assert js <= table, sorted(js - table)
    assert table <= python | js, f"cited by no report: {sorted(table - python - js)}"


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


def test_a_numpy_scalar_is_a_number():
    """Values often come out of a fitted array; fmt_num always took them."""
    import numpy as np

    assert render_text("{d:num} m, {n:plural:step|steps}",
                       {"d": np.int64(62), "n": np.int64(3)}) == "62 m, steps"
    assert render_text("{d:.1f}", {"d": np.float32(2.25)}) == "2.2"


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
// JSON has no NaN or infinity, so the cases spell them {"$float": "nan"}
const SPECIAL = { nan: NaN, inf: Infinity, '-inf': -Infinity };
const cases = JSON.parse(readFileSync(process.argv[3], 'utf8'), (key, value) =>
  (value && typeof value === 'object' && '$float' in value) ? SPECIAL[value.$float] : value);
writeFileSync(process.argv[4], JSON.stringify({
  rendered: cases.map(([template, values]) => {
    try { return C.renderText(template, values); } catch (e) { return null; }
  }),
  catalogue: sandbox.GWT.data.text,
  defaults: C.defaultConfig(),
}));
"""


def _encode(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"$float": repr(value)}
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    return value


def _browser(tmp_path, cases) -> dict:
    """What gwt-core.js renders for each (template, values), None for a
    refusal, with the catalogue and defaults the bundle carries."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    script = tmp_path / "render.mjs"
    script.write_text(_JS_RENDER, encoding="utf-8")
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([[t, _encode(v)] for t, v in cases]), encoding="utf-8")
    out = tmp_path / "out.json"
    subprocess.run([node, str(script), str(JS), str(path), str(out)],
                   check=True, timeout=300)
    return json.loads(out.read_text(encoding="utf-8"))


def test_the_browser_renders_the_same_text(tmp_path):
    """renderText in gwt-core.js gives what render_text gives, refusals
    included, and the bundle carries the catalogue and the configuration
    defaults as Python reads them."""
    result = _browser(tmp_path, [(t, v) for t, v, _ in RENDER_CASES])
    assert result["rendered"] == [expected for _, _, expected in RENDER_CASES]
    assert result["catalogue"] == text_catalogue(), (
        "docs/js/gwt-data.js carries another catalogue; "
        "run: python web/build_webapp_data.py")
    assert result["defaults"] == _defaults_json(), (
        "docs/js/gwt-data.js carries other configuration defaults; "
        "run: python web/build_webapp_data.py")


def _generated_numbers():
    """Numbers chosen to find where two ways of writing a number part:
    halves and near-halves at every scale, values whose stored binary sits
    just either side of the decimal they were typed as (1.05, 0.155), zero
    of either sign, negatives that round to nothing, the edges of the
    fixed and exponential forms of %g, powers of ten and their neighbours,
    numbers past 1e21 where toFixed changes form, subnormals, NaN and the
    infinities, and a spread of random values."""
    rng = random.Random(17)
    values = [0.0, -0.0, 0.5, -0.5, 1.5, 2.5, -2.5, -0.4, -0.004, 0.125, 2.675,
              14.05, 1.05, 0.155, 0.0005, 1e-4, 9.99995e-5, 1e-5, 999.5, 999999.5,
              123456.5, 1e15, 1e16, 1e17, 1e21, 1e22, 7.1e23, 1.5e300, 5e-324,
              2.2e-308, math.nan, math.inf, -math.inf]
    for e in range(-12, 22):
        p = 10.0 ** e
        values += [p, -p, math.nextafter(p, 0), math.nextafter(p, math.inf),
                   p * 0.99995, p * 0.9995]
    for _ in range(600):
        # a short decimal ending in 5, typed as a report would carry it
        values.append(float(f"{rng.randint(1, 99999)}5e{rng.randint(-8, 6)}")
                      * rng.choice((1, -1)))
        values.append(rng.uniform(-1000, 1000))
        values.append(10 ** rng.uniform(-12, 24) * rng.choice((1, -1)))
        values.append(float(rng.randint(-10**7, 10**7)))
    return values


def test_the_two_renderers_agree_on_generated_numbers(tmp_path):
    """Every number format, both engines, the same text for a few thousand
    numbers each.

    The hand-picked cases above say what the grammar means; these find
    where the two implementations of it part. They did: to seventeen
    digits 1.05 reads as a tie, so {d:.1f} wrote 1.0 here and 1.1 in
    Python, and fmt_num gave 0.001 for 0.001005 against Python's 0.00101.
    """
    cases = []
    for value in _generated_numbers():
        for spec in ("num", "g", ".0f", ".1f", ".2f", ".3f", ".6f", ".12f"):
            cases.append((f"{{x:{spec}}}", {"x": value}))
    for count in (0, 1, 2, -1, 1.0, 2.0, 1.5, -0.0, math.nan, math.inf, 10**6):
        cases.append(("{n:plural:one|other}", {"n": count}))

    def python(template, values):
        try:
            return render_text(template, values)
        except (KeyError, TypeError, ValueError):
            return None

    browser = _browser(tmp_path, cases)["rendered"]
    parted = [(t, v, py, js) for (t, v), js in zip(cases, browser, strict=True)
              if (py := python(t, v)) != js]
    assert not parted, f"{len(parted)} of {len(cases)} differ, e.g. {parted[:8]}"


# ----------------------------------------------------- the configuration defaults

def _defaults_json() -> dict:
    return json.loads((REPO / "src" / "groundwater" / "data" / "defaults.json")
                      .read_text(encoding="utf-8"))


def test_the_defaults_file_is_the_configuration():
    """defaults.json has exactly the fields config.py declares, each of the
    type its field declares, and Config() is built from it.

    The type is held exactly: an int written as 10.0 would change the text
    of the VES configuration, and with it every inversion cache key.
    """
    import dataclasses

    from groundwater.config import Config

    defaults = _defaults_json()
    config = Config()
    assert list(defaults) == [f.name for f in dataclasses.fields(Config)]
    kinds = {"int": int, "float": float, "str": str, "tuple": list}
    for section, values in defaults.items():
        fields = dataclasses.fields(getattr(config, section))
        assert list(values) == [f.name for f in fields], section
        for f in fields:
            assert type(values[f.name]) is kinds[f.type], f"{section}.{f.name}"
    assert json.loads(json.dumps(dataclasses.asdict(config))) == defaults


def test_no_engine_types_out_a_configuration_default():
    """config.py reads every default from the file, and no browser script
    carries a copy of the old DEFAULT_CONFIG literal.

    A default typed out next to its key (``safety_factor: 1.5``) is what a
    copy looks like. The costing inputs carry drilled and casing diameters
    of their own, in both engines (costing/model.py CostingInputs and
    gwt-core.js costingInputs); they are the costing's defaults, not this
    file's, and are named here so that any other match fails.
    """
    source = (REPO / "src" / "groundwater" / "config.py").read_text(encoding="utf-8")
    fields = re.findall(r"^    (\w+): (\w+) = (.*)$", source, re.MULTILINE)
    assert fields
    for name, _kind, default in fields:
        if name in {"style", "ves", "pumping", "design", "ves_range", "odds",
                    "cost_range"}:
            continue
        assert re.match(r"(tuple\()?_[A-Z]+\[\"" + name + r"\"\]", default), (
            f"config.py types out the default of {name}: {default}")

    allowed = {"borehole_diameter_in", "casing_diameter_in"}
    js = _js_source()
    for section, values in _defaults_json().items():
        for key, value in values.items():
            if isinstance(value, list) or value == "":
                continue
            if isinstance(value, str):
                literal = "['\"]" + re.escape(value) + "['\"]"
            else:
                literal = re.escape(f"{value:g}") + r"(?:\.0+)?(?![.\d])"
            found = re.findall(r"\b" + key + r"\s*:\s*" + literal, js)
            if key in allowed:
                assert len(found) <= 1, f"{section}.{key} is typed out in docs/js"
            else:
                assert not found, f"{section}.{key} is typed out in docs/js: {found}"

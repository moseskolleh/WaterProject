"""The browser's YAML reader against PyYAML, on the files PyYAML writes.

The browser reads a Streamlit project file with its own small YAML reader
(``parseYaml`` in docs/js/support.js): the Portfolio page pools them and the
ledger of predictions and outcomes rides in them. These documents are dumped
by PyYAML as serialize_project dumps a project, and the browser has to read
back what PyYAML reads: lists in lists, names written with escapes, long
strings folded over lines in either kind of quote, keys with a colon in
them, and text that looks like a number to anyone but YAML 1.1.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

JS = Path(__file__).resolve().parents[1] / "docs" / "js"

_DRIVER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = vm.createContext({ console, TextEncoder, TextDecoder });
vm.runInContext(readFileSync(process.argv[2] + '/support.js', 'utf8'), sandbox, { filename: 'support.js' });
const S = sandbox.GWT.support;
const texts = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(texts.map((text) => {
  try { return { ok: S.parseYaml(text) }; } catch (e) { return { threw: String(e.message) }; }
})));
"""

_CHARACTERS = list("abc XYZ 019:#-'\"\\,.{}[]&*!|>%@`") + ["è", "–", "\t", "😀", "\x85", "\n", "  ", " "]


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_CHARACTERS) for _ in range(rng.choice([0, 1, 3, 12, 85, 160])))


def _leaf(rng: random.Random):
    r = rng.random()
    if r < 0.15:
        return None
    if r < 0.25:
        return rng.choice([True, False])
    if r < 0.4:
        return round(rng.uniform(-1e4, 1e4), rng.choice([0, 1, 3]))
    if r < 0.47:
        return rng.choice(["12", "true", "null", "~", "1e3", "1.5", "-", "- x", "a: b", "#x", "", "yes", ".inf"])
    return _word(rng)


def _tree(rng: random.Random, depth: int = 0):
    r = rng.random()
    if depth > 3 or r < 0.35:
        return _leaf(rng)
    if r < 0.65:
        return [_tree(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    keys = ["id", "a b", "x:y", "é", "1", "true", "meta_community"]
    return {rng.choice(keys) + str(k): _tree(rng, depth + 1) for k in range(rng.randint(0, 4))}


def _read(texts: list[str], tmp_path: Path) -> list[dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path / "yaml.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    done = subprocess.run([node, str(driver), str(JS)], input=json.dumps(texts), capture_output=True,
                          text=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


def test_the_browser_reads_what_pyyaml_writes(tmp_path):
    rng = random.Random(20261018)
    docs = [{"root": _tree(rng), "list": [_tree(rng, 1) for _ in range(3)], "text": _word(rng)}
            for _ in range(400)]
    texts = [yaml.safe_dump(doc, sort_keys=True) for doc in docs]
    answers = _read(texts, tmp_path)
    for text, answer in zip(texts, answers, strict=True):
        assert "threw" not in answer, (answer, text)
        assert answer["ok"] == yaml.safe_load(text), text


def test_the_ledgers_shapes_read_back(tmp_path):
    """The ledger's own shapes: a list of pairs, a list of [top, bottom,
    class] bands, a name with an accent and a status in other script."""
    doc = {"ledger": {"drilled": None, "entries": [{
        "id": "e3804c25dbb1", "before_outcome": True,
        "point": {"sounding_id": "Kpètèma 3", "easting": None, "utm_zone": 28},
        "prediction": {"water_zones_m": [[8.0, 20.0], [24.0, 28.0]], "basement_band_m": [22.1, 28.2, 34.0]},
        "outcome": {"intervals": [[0.0, 6.0, "laterite"], [6.0, 30.0, "saprolite"]],
                    "status": "Abandoned – the casing collapsed at 30 m after the second airlift, and the "
                              "crew moved the rig to the reserve site"}}]}}
    answer = _read([yaml.safe_dump(doc, sort_keys=True)], tmp_path)[0]
    assert answer == {"ok": doc}


def test_what_the_reader_cannot_read_it_says(tmp_path):
    answers = _read(["a: [1, 2]\n", "a: &x 1\n", 'a: "unclosed\n', "a: 1\n  b: 2\n"], tmp_path)
    assert all("threw" in answer for answer in answers), answers

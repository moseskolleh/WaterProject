"""Checks that the browser demo build stays in sync with the code."""

import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_demo", REPO / "web" / "build_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_build(tmp_path, sample_data):
    builder = _load_builder()
    out = builder.build(tmp_path, builder.DEFAULT_STLITE_BASE, None)
    html = out.read_text(encoding="utf-8")
    assert "@stlite/browser@1.8.1/build/stlite.js" in html
    match = re.search(r"const FILES = (\{.*?\});\n", html, re.DOTALL)
    assert match, "FILES blob not found"
    files = json.loads(match.group(1))
    assert "streamlit_app.py" in files
    assert "gw_app/common.py" in files
    assert "groundwater/__init__.py" in files
    assert "groundwater/data/who_guidelines.csv" in files
    for sample in builder.SAMPLE_FILES:
        assert f"examples/data/{sample}" in files
        assert files[f"examples/data/{sample}"]["t"] == "b64"
    # the inlined package matches the source tree exactly
    for rel in ("models.py", "ves/forward.py", "hydraulics/analysis.py"):
        source = (REPO / "src" / "groundwater" / rel).read_text(encoding="utf-8")
        assert files[f"groundwater/{rel}"]["d"] == source
    assert (tmp_path / ".nojekyll").exists()


def test_committed_demo_is_current(sample_data):
    """docs/index.html must be regenerated when app/package/samples change."""
    builder = _load_builder()
    committed = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    match = re.search(r"const FILES = (\{.*?\});\n", committed, re.DOTALL)
    assert match, "FILES blob not found in docs/index.html"
    files = json.loads(match.group(1))
    fresh = builder.collect_files()
    assert set(files) == set(fresh), (
        "docs/index.html file set differs from the source tree; "
        "run: python web/build_demo.py"
    )
    stale = [path for path in fresh if files[path] != fresh[path]]
    assert not stale, (
        f"docs/index.html is stale for {stale[:5]}; run: python web/build_demo.py"
    )

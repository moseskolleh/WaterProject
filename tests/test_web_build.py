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


def test_inlined_files_cannot_end_the_script_block(tmp_path, sample_data):
    """A file mentioning </script> must not truncate the demo.

    An HTML parser ends a script at the first literal closing tag, even inside
    a JavaScript string. Before this was escaped, one Python comment containing
    "</script>" cut the bundle in half: mount() never ran, and the remainder of
    the JSON was parsed as markup.
    """
    builder = _load_builder()
    out = builder.build(tmp_path, builder.DEFAULT_STLITE_BASE, None)
    html = out.read_text(encoding="utf-8")

    # Exactly one script element: opening and closing tag, nothing in between.
    assert html.count("<script") == 1
    assert html.count("</script>") == 1

    # And the escape survives a round trip, so the files still arrive intact.
    match = re.search(r"const FILES = (\{.*?\});\n", html, re.DOTALL)
    assert match
    files = json.loads(match.group(1))
    source = (REPO / "src" / "groundwater" / "depth_spine" / "inline.py").read_text(
        encoding="utf-8"
    )
    assert "</script>" in source, "this test needs a file that mentions the tag"
    assert files["groundwater/depth_spine/inline.py"]["d"] == source


def test_demo_theme_comes_from_the_app_config(tmp_path, sample_data):
    """One palette: the demo reads .streamlit/config.toml rather than copying it."""
    import tomllib

    builder = _load_builder()
    with open(REPO / ".streamlit" / "config.toml", "rb") as fh:
        expected = tomllib.load(fh)["theme"]

    theme = builder.app_theme()
    assert theme["theme.primaryColor"] == expected["primaryColor"]
    assert theme["theme.backgroundColor"] == expected["backgroundColor"]
    assert theme["theme.sidebar.backgroundColor"] == expected["sidebar"]["backgroundColor"]

    # And those colours reach the page the visitor sees while it loads.
    html = builder.build(tmp_path, builder.DEFAULT_STLITE_BASE, None).read_text(
        encoding="utf-8"
    )
    shell = html[: html.index("const FILES")]
    assert expected["backgroundColor"] in shell
    assert expected["primaryColor"] in shell
    assert "__" not in shell.replace("__FILES_JSON__", ""), "unsubstituted placeholder"

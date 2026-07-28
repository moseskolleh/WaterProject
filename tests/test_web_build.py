"""Checks that the published site stays in sync with the code.

``docs/`` carries two builds: the standalone JavaScript app at the
site root and the stlite/Pyodide build under ``docs/wasm/``. Both are
partly generated, and a generated file that has drifted from its
source is worse than one that was never built, so the drift is a test
failure rather than something to notice later.
"""

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
    """docs/wasm/index.html must be regenerated when app/package/samples change.

    The site root is the standalone JavaScript app; the stlite build lives
    beside it under ``docs/wasm/``.
    """
    builder = _load_builder()
    committed = (REPO / "docs" / "wasm" / "index.html").read_text(encoding="utf-8")
    match = re.search(r"const FILES = (\{.*?\});\n", committed, re.DOTALL)
    assert match, "FILES blob not found in docs/wasm/index.html"
    files = json.loads(match.group(1))
    fresh = builder.collect_files()
    assert set(files) == set(fresh), (
        "docs/wasm/index.html file set differs from the source tree; "
        "run: python web/build_demo.py"
    )
    stale = [path for path in fresh if files[path] != fresh[path]]
    assert not stale, (
        f"docs/wasm/index.html is stale for {stale[:5]}; "
        "run: python web/build_demo.py"
    )


def _load_webapp_builder():
    spec = importlib.util.spec_from_file_location(
        "build_webapp_data", REPO / "web" / "build_webapp_data.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_webapp_data_is_current(sample_data):
    """docs/js/gwt-data.js must match the CSV, GeoJSON and sample workbooks.

    The standalone app carries its own copy of the guideline table, the rate
    catalogue, the checklists, the map layers and the sample workbooks. They
    are re-emitted mechanically from ``src/groundwater/data`` and
    ``examples/data``, so a stale copy means the browser is scoring water
    against different limits from the package.
    """
    builder = _load_webapp_builder()
    committed = builder.OUT.read_text(encoding="utf-8")
    payload = json.loads(
        committed[committed.index("GWT.data = ") + len("GWT.data = "):]
        .rsplit(";", 2)[0]
    )

    for key, name in builder.CSV_TABLES.items():
        assert payload[key] == builder.read_csv_rows(name), (
            f"docs/js/gwt-data.js is stale for {name}; "
            "run: python web/build_webapp_data.py"
        )
    for key, name in builder.GEOJSON_LAYERS.items():
        assert payload["geo"][key] == builder.read_geojson(name), (
            f"docs/js/gwt-data.js is stale for {name}; "
            "run: python web/build_webapp_data.py"
        )
    for key, spec in builder.SAMPLE_PROJECTS.items():
        for role, rel in spec["files"].items():
            source = REPO / "examples" / "data" / rel
            assert payload["samples"][key]["files"][role]["b64"] == \
                builder.encode_file(source), (
                    f"docs/js/gwt-data.js is stale for {rel}; "
                    "run: python web/build_webapp_data.py"
                )


def test_webapp_scripts_are_wired_up():
    """Every script index.html loads must exist, and in dependency order."""
    html = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"></script>', html)
    assert scripts, "index.html loads no scripts"
    # support.js defines the helpers the rest use at load time, and gwt-data.js
    # must be in place before gwt-core.js reads the standards table.
    assert scripts[0].endswith("support.js")
    assert scripts.index("js/gwt-data.js") < scripts.index("js/gwt-core.js")
    for src in scripts:
        assert (REPO / "docs" / src).exists(), f"{src} is referenced but missing"
    for href in re.findall(r'<link rel="stylesheet" href="([^"]+)"', html):
        assert (REPO / "docs" / href).exists(), f"{href} is referenced but missing"


def test_root_redirect_points_at_the_site():
    """The repo-root index.html must send visitors to docs/.

    GitHub Pages can be pointed at the repository root or at /docs. Served
    from the root there is otherwise no index, so Pages renders README.md and
    the advertised link shows the readme instead of the application. This file
    is what makes one URL work under both settings; served from /docs it is
    never published.
    """
    root = REPO / "index.html"
    assert root.exists(), "index.html at the repository root is missing"
    html = root.read_text(encoding="utf-8")
    # both paths matter: the meta refresh covers a browser with JavaScript
    # disabled, the script covers the rest and preserves any fragment
    assert re.search(r'http-equiv="refresh"[^>]*url=docs/', html), \
        "the meta refresh does not point at docs/"
    assert "location.replace('docs/'" in html, \
        "the scripted redirect does not point at docs/"
    assert '<a href="docs/">' in html, \
        "no visible fallback link for a browser that honours neither"
    # and the target has to exist, or the redirect is a loop into a 404
    assert (REPO / "docs" / "index.html").exists()

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


def test_the_service_worker_precaches_every_script_the_page_loads():
    """A script the worker does not know about is a page that breaks offline.

    The app is used where the network is a luxury, and the failure is a
    quiet one: everything works on the machine that added the script,
    because it is in the browser's own cache, and the feature is simply
    missing on a device that installed the app before it existed.
    """
    docs = REPO / "docs"
    html = (docs / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"></script>', html)
    worker = (docs / "sw.js").read_text(encoding="utf-8")
    precache = re.search(r"var PRECACHE = \[(.*?)\];", worker, re.DOTALL)
    assert precache, "PRECACHE list not found in sw.js"
    cached = set(re.findall(r"'([^']+)'", precache.group(1)))
    missing = [src for src in scripts if src not in cached]
    assert not missing, (
        f"{missing} loaded by index.html but not precached by sw.js; add them "
        "to PRECACHE and bump VERSION"
    )


def _load_offline_builder():
    spec = importlib.util.spec_from_file_location(
        "build_offline", REPO / "web" / "build_offline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_worker_is_current():
    """docs/sw.js must be what web/build_offline.py produces from the shell.

    The worker is generated from the app shell precisely so nobody has to
    remember it: a script added to index.html is precached by the next
    build. A committed worker that has drifted from the shell is the
    failure that was being designed out - the device that installed the
    app yesterday quietly missing a page today.
    """
    builder = _load_offline_builder()
    fresh = builder.render(builder.shell_assets())
    assert builder.OUT.read_text(encoding="utf-8") == fresh, (
        "docs/sw.js is stale; run: python web/build_offline.py"
    )


def test_the_release_identifier_follows_the_shell():
    """Change a precached byte and the release has to change with it.

    A release identifier that stays put is a device that keeps serving the
    previous app with nothing to show for it: the browser compares the
    worker byte for byte, and an identical worker is never replaced.
    """
    builder = _load_offline_builder()
    paths = builder.shell_assets()
    before = builder.release_id(paths)
    assert before.startswith("gwt-v"), (
        "the activate handler sweeps caches by the 'gwt-v' prefix"
    )

    engine = REPO / "docs" / "js" / "gwt-core.js"
    original = engine.read_bytes()
    try:
        engine.write_bytes(original + b"\n/* a deployed change */\n")
        assert builder.release_id(paths) != before
    finally:
        engine.write_bytes(original)
    assert builder.release_id(paths) == before


def test_the_precache_list_is_the_shell_the_page_loads():
    """Everything the page loads is precached, and nothing precached is absent.

    Both directions matter. A script that is loaded but not cached is a
    feature missing offline; a path that is cached but not on disk fails
    the install outright, and with an all-or-nothing precache that means no
    offline app at all.
    """
    builder = _load_offline_builder()
    paths = builder.shell_assets()
    docs = REPO / "docs"
    html = (docs / "index.html").read_text(encoding="utf-8")

    loaded = re.findall(r'<script src="([^"]+)"></script>', html)
    loaded += re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    missing = [src for src in loaded if src not in paths]
    assert not missing, f"{missing} is loaded by index.html but not precached"

    absent = [p for p in paths if p != "./" and not (docs / p).exists()]
    assert not absent, f"{absent} is precached but not in docs/"

    # The stlite build is a 60 MB Python runtime from a CDN. Putting it on
    # someone's phone unasked is a decision for the user, not the worker.
    assert not [p for p in paths if p.startswith("wasm/")]


def test_the_worker_is_written_in_one_step(tmp_path):
    """A worker truncated half way through a write shadows the one that worked."""
    builder = _load_offline_builder()
    target = tmp_path / "sw.js"
    target.write_text("previous release", encoding="utf-8")
    builder.write_atomically(target, "next release")
    assert target.read_text(encoding="utf-8") == "next release"
    assert not list(tmp_path.glob("*.tmp")), "the staging file was left behind"


def test_the_build_groups_a_shape_s_rings_into_one_polygon_with_its_holes():
    """Every ring used to be a filled polygon carrying the parent's code.

    A shapefile writes an outer ring clockwise and the holes that cut it the
    other way. Split into separate features, thirteen holes were drawn on
    top of the unit they should have exposed.
    """
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "build_geodata", Path(__file__).resolve().parents[1] / "web" / "build_geodata.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # clockwise outer square, counter-clockwise window inside it
    outer = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0), (0.0, 0.0)]
    hole = [(3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0), (3.0, 3.0)]
    assert module.signed_ring_area(outer) < 0, "an outer ring winds clockwise"
    assert module.signed_ring_area(hole) > 0, "a hole winds the other way"

    polygons = module.rings_to_polygons([outer, hole])
    assert len(polygons) == 1
    assert polygons[0][0] == outer and polygons[0][1] == hole

    # two separate bodies each keep their own hole
    far_outer = [(20.0, 0.0), (20.0, 10.0), (30.0, 10.0), (30.0, 0.0), (20.0, 0.0)]
    far_hole = [(23.0, 3.0), (27.0, 3.0), (27.0, 7.0), (23.0, 7.0), (23.0, 3.0)]
    grouped = module.rings_to_polygons([outer, far_outer, hole, far_hole])
    assert len(grouped) == 2
    assert all(len(poly) == 2 for poly in grouped)

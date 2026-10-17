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
    # the pages, their helpers and the state schema the script imports from
    # beside it (PLAN.md step 1.1), mounted where the imports look for them
    app_modules = sorted(p for p in (REPO / "app").rglob("*.py")
                         if "__pycache__" not in p.parts)
    assert {"state.py", "shared.py", "views/__init__.py",
            "views/costing.py"} <= {p.relative_to(REPO / "app").as_posix()
                                    for p in app_modules}
    for path in app_modules:
        mount = path.relative_to(REPO / "app").as_posix()
        assert files[mount]["d"] == path.read_text(encoding="utf-8"), mount
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
    """docs/js/gwt-data.js and its bundles must match the CSV, GeoJSON and
    sample workbooks.

    The standalone app carries its own copy of the guideline table, the rate
    catalogue, the checklists, the map layers and the sample workbooks. They
    are re-emitted mechanically from ``src/groundwater/data`` and
    ``examples/data``, so a stale copy means the browser is scoring water
    against different limits from the package. The map layers and the sample
    workbooks are written to bundles of their own, loaded on demand, and are
    held to their sources the same way.
    """
    builder = _load_webapp_builder()
    fresh = builder.bundle_texts()
    assert set(fresh) == {builder.OUT, *builder.BUNDLE_OUT.values()}
    for path, text in fresh.items():
        assert path.exists(), (
            f"{path.name} is missing; run: python web/build_webapp_data.py"
        )
        assert path.read_text(encoding="utf-8") == text, (
            f"docs/js/{path.name} is stale; run: python web/build_webapp_data.py"
        )

    committed = builder.OUT.read_text(encoding="utf-8")
    payload = json.loads(
        committed[committed.index("GWT.data = ") + len("GWT.data = "):]
        .split(";\n", 1)[0]
    )
    for key, name in builder.CSV_TABLES.items():
        assert payload[key] == builder.read_csv_rows(name), (
            f"docs/js/gwt-data.js is stale for {name}; "
            "run: python web/build_webapp_data.py"
        )
    # the first screen's script carries no layer and no workbook: they are
    # what the split takes off the critical path
    assert "geo" not in payload
    for sample in payload["samples"].values():
        for entry in sample["files"].values():
            assert "b64" not in entry and entry["name"] and entry["path"]

    geo_text = builder.BUNDLE_OUT["geo"].read_text(encoding="utf-8")
    geo = json.loads(
        geo_text[geo_text.index("GWT.data.geo = ") + len("GWT.data.geo = "):]
        .split(";\n", 1)[0]
    )
    for key, name in builder.GEOJSON_LAYERS.items():
        assert geo[key] == builder.read_geojson(name), (
            f"docs/js/gwt-geo.js is stale for {name}; "
            "run: python web/build_webapp_data.py"
        )
    samples_text = builder.BUNDLE_OUT["samples"].read_text(encoding="utf-8")
    sample_bytes = json.loads(
        samples_text[samples_text.index("var bytes = ") + len("var bytes = "):]
        .split(";\n", 1)[0]
    )
    for key, spec in builder.SAMPLE_PROJECTS.items():
        for role, rel in spec["files"].items():
            source = REPO / "examples" / "data" / rel
            assert sample_bytes[key][role] == builder.encode_file(source), (
                f"docs/js/gwt-samples.js is stale for {rel}; "
                "run: python web/build_webapp_data.py"
            )
            assert payload["samples"][key]["files"][role]["name"] == source.name
    # the loader fetches each bundle by the name the build gave it
    assert json.dumps(builder.BUNDLES) in committed
    # the About page names this release, so it has to be the one the package is
    import groundwater

    assert payload["version"] == builder.toolkit_version(), (
        "docs/js/gwt-data.js names another version; run: python web/build_webapp_data.py"
    )
    assert groundwater.__version__ == builder.toolkit_version(), (
        "the installed package is another version; reinstall with pip install -e ."
    )
    # the browser's inversion cache names its engine by this digest, so a
    # stale one would hand back results the edited engine never computed
    assert payload["engineDigest"] == builder.engine_digest(), (
        "docs/js/gwt-data.js carries the digest of another gwt-core.js; "
        "run: python web/build_webapp_data.py"
    )


def _scripts(html: str) -> list[str]:
    """The scripts a page loads, in order, whatever attributes they carry."""
    return re.findall(r'<script\b[^>]*\bsrc="([^"]+)"[^>]*></script>', html)


def test_webapp_scripts_are_wired_up():
    """Every script index.html loads must exist, and in dependency order."""
    html = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    scripts = _scripts(html)
    assert scripts, "index.html loads no scripts"
    # support.js defines the helpers the rest use at load time, and gwt-data.js
    # must be in place before gwt-core.js reads the standards table.
    assert scripts[0].endswith("support.js")
    assert scripts.index("js/gwt-data.js") < scripts.index("js/gwt-core.js")
    # gwt-worker.js is GWT.engine on the page, which gwt-app.js takes at load
    # time; its tasks call gwt-core.js when the page has to run them itself.
    assert (scripts.index("js/gwt-core.js") < scripts.index("js/gwt-worker.js")
            < scripts.index("js/gwt-app.js"))
    # gwt-store.js is where the session is kept, which gwt-app.js opens at
    # load time to restore it.
    assert scripts.index("js/gwt-store.js") < scripts.index("js/gwt-app.js")
    # gwt-app.js is last: it runs the app, and it is where the bundles the
    # first screen does without are named.
    assert scripts[-1] == "js/gwt-app.js"
    # Deferred, every one, so the browser draws the shell without waiting on
    # them; deferred scripts still run in document order, so the order above
    # holds. One left parser-blocking between deferred ones would run first.
    tags = re.findall(r"<script\b[^>]*\bsrc=[^>]*>", html)
    assert all(re.search(r"\sdefer[\s>]", tag) for tag in tags), tags
    for src in scripts:
        assert (REPO / "docs" / src).exists(), f"{src} is referenced but missing"
    for href in re.findall(r'<link rel="stylesheet" href="([^"]+)"', html):
        assert (REPO / "docs" / href).exists(), f"{href} is referenced but missing"


def _bundles() -> dict[str, str]:
    """Every bundle a script of the app's names for GWT.load, by name, as a
    path under docs/."""
    found: dict[str, str] = {}
    for script in (REPO / "docs" / "js").glob("*.js"):
        text = script.read_text(encoding="utf-8")
        for statement in re.findall(r"GWT\.bundles\s*=[^;]*;", text):
            for name, url in re.findall(
                    r"""["']?(\w+)["']?\s*:\s*["']([^"']+\.js)["']""", statement):
                found[name] = "js/" + url
    return found


def test_the_engine_prints_fixed_decimals_as_python_does():
    """gwt-core.js writes a fixed number of decimals with pyFixed only.

    toFixed rounds an exact binary tie (1.25, 6.5) away from zero and
    Python's "%.1f" to the even digit, so every toFixed in report prose was
    a divergence waiting for a sheet with that number on it: the fuzz suite
    found them one at a time (a borehole depth of 6.5 m, a static level of
    1.25 m). The two inside pyFixed and formatG are the only ones left.
    """
    source = (REPO / "docs" / "js" / "gwt-core.js").read_text(encoding="utf-8")
    calls = [line.strip() for line in source.splitlines()
             if ".toFixed(" in line and not line.lstrip().startswith(("*", "/*", "//"))]
    assert calls == [
        "return sign + Math.abs(pyRound(v, d)).toFixed(d);",
        "var out = rounded.toFixed(Math.max(0, p - 1 - exp));",
    ]


def test_every_bundle_loaded_on_demand_exists_and_is_precached():
    """A bundle is fetched the first time a page needs it, not with the shell.

    It is still part of the release: a device that installed the app and was
    only ever shown the Overview has to be able to open a map at a borehole
    with no network, so the service worker precaches every bundle the app
    can ask for, and none of them may be missing.
    """
    bundles = _bundles()
    # the map layers and the samples, from gwt-data.js; the figures, the map
    # export, the photo slots and the document writer, from gwt-app.js
    assert {"geo", "samples", "charts", "geolibre", "imageSlot", "docx"} <= set(bundles)
    builder = _load_offline_builder()
    paths = builder.shell_assets()
    for name, path in bundles.items():
        assert (REPO / "docs" / path).exists(), f"bundle {name}: {path} is missing"
        assert path in paths, f"bundle {name}: {path} is not precached"
    # and none of them is loaded by the page up front, which would undo the
    # point of loading it on demand
    html = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    assert not set(bundles.values()) & set(_scripts(html))


def test_the_web_app_icon_is_the_brand_icon():
    """docs/icon.svg was a hand-made copy of the package's brand icon with
    nothing keeping the two the same. make_brand_assets.py writes both from
    one drawing; this fails when either has been edited on its own."""
    spec = importlib.util.spec_from_file_location(
        "make_brand_assets", REPO / "web" / "make_brand_assets.py"
    )
    brand = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(brand)
    drawn = brand.icon_svg().encode("utf-8")
    package = REPO / "src" / "groundwater" / "data" / "brand" / "icon.svg"
    assert package.read_bytes() == drawn, (
        "brand/icon.svg is not what web/make_brand_assets.py draws; run it"
    )
    assert brand.WEB_ICON.read_bytes() == drawn, (
        "docs/icon.svg differs from the brand icon; run web/make_brand_assets.py"
    )


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
    scripts = _scripts(html)
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

    loaded = _scripts(html)
    loaded += re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)
    missing = [src for src in loaded if src not in paths]
    assert not missing, f"{missing} is loaded by index.html but not precached"

    absent = [p for p in paths if p != "./" and not (docs / p).exists()]
    assert not absent, f"{absent} is precached but not in docs/"

    # The stlite build is a 60 MB Python runtime from a CDN. Putting it on
    # someone's phone unasked is a decision for the user, not the worker.
    assert not [p for p in paths if p.startswith("wasm/")]


def test_what_the_engine_worker_imports_is_precached():
    """A Web Worker fetches its imports itself, where no <script> tag names them.

    gwt-worker.js imports the engine and its tables when it starts. Offline,
    an import that is not in the release fails the worker, and the page is
    left doing every inversion on its own thread again, with nothing to say
    why.
    """
    builder = _load_offline_builder()
    paths = builder.shell_assets()
    worker = REPO / "docs" / "js" / "gwt-worker.js"
    calls = re.findall(r"importScripts\(([^)]*)\)", worker.read_text(encoding="utf-8"))
    imported = [
        "js/" + url for call in calls for url in re.findall(r"'([^']+)'", call)
    ]
    assert "js/gwt-core.js" in imported and "js/gwt-data.js" in imported
    assert "js/gwt-worker.js" in paths
    missing = [path for path in imported if path not in paths]
    assert not missing, f"the engine worker imports {missing}, which is not precached"


def test_the_shell_follows_a_worker_s_imports(tmp_path, monkeypatch):
    """An import only a worker makes is still part of the shell.

    The engine worker's imports happen to be scripts the page loads too, so
    the check above would pass without following them at all. This is the
    case it exists for: a script nothing but a worker asks for.
    """
    builder = _load_offline_builder()
    (tmp_path / "js").mkdir()
    (tmp_path / "index.html").write_text(
        '<!doctype html><script src="js/entry.js"></script>', encoding="utf-8")
    (tmp_path / "js" / "entry.js").write_text(
        "if (self.importScripts) self.importScripts('tables.js', \"engine.js\");\n",
        encoding="utf-8")
    (tmp_path / "js" / "tables.js").write_text("", encoding="utf-8")
    (tmp_path / "js" / "engine.js").write_text("", encoding="utf-8")
    for extra in builder.EXTRA:
        (tmp_path / extra).write_text("", encoding="utf-8")
    monkeypatch.setattr(builder, "DOCS", tmp_path)

    paths = builder.shell_assets()
    assert paths.index("js/entry.js") < paths.index("js/tables.js")
    assert "js/engine.js" in paths

    # and one that is not there fails the build like any missing script
    (tmp_path / "js" / "engine.js").unlink()
    try:
        builder.shell_assets()
    except builder.ShellError as exc:
        assert "js/engine.js" in str(exc)
    else:
        raise AssertionError("a missing worker import was not reported")


def test_the_shell_follows_the_bundles_a_script_names(tmp_path, monkeypatch):
    """A script fetched on demand is still part of the shell.

    Nothing on the first screen asks for it, so reading the page the way a
    browser does would never meet it; the GWT.bundles assignment that names
    it is what the build follows instead.
    """
    builder = _load_offline_builder()
    (tmp_path / "js").mkdir()
    (tmp_path / "index.html").write_text(
        '<!doctype html><script src="js/entry.js" defer></script>', encoding="utf-8")
    (tmp_path / "js" / "entry.js").write_text(
        "GWT.bundles = Object.assign(GWT.bundles || {}, {\n"
        "  maps: 'maps.js', \"figures\": \"figures.js\",\n});\n",
        encoding="utf-8")
    (tmp_path / "js" / "maps.js").write_text("", encoding="utf-8")
    (tmp_path / "js" / "figures.js").write_text("", encoding="utf-8")
    for extra in builder.EXTRA:
        (tmp_path / extra).write_text("", encoding="utf-8")
    monkeypatch.setattr(builder, "DOCS", tmp_path)

    paths = builder.shell_assets()
    assert paths.index("js/entry.js") < paths.index("js/maps.js")
    assert "js/figures.js" in paths

    (tmp_path / "js" / "maps.js").unlink()
    try:
        builder.shell_assets()
    except builder.ShellError as exc:
        assert "js/maps.js" in str(exc)
    else:
        raise AssertionError("a missing bundle was not reported")


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

    # a hole clipped at the window's edge starts on the edge it shares with
    # its clipped outer ring; it was dropped because that one vertex was
    # tested and a ray cast from a boundary point reads as outside
    edge_hole = [(10.0, 3.0), (10.0, 7.0), (7.0, 7.0), (7.0, 3.0), (10.0, 3.0)]
    assert module.signed_ring_area(edge_hole) > 0
    assert not module.point_in_ring(edge_hole[0], outer)
    polygons = module.rings_to_polygons([outer, edge_hole])
    assert polygons == [[outer, edge_hole]]

    # a hole in an island in a hole is cut from the island, not the continent
    island = [(4.0, 4.0), (4.0, 6.0), (6.0, 6.0), (6.0, 4.0), (4.0, 4.0)]
    island_hole = [(4.5, 4.5), (5.5, 4.5), (5.5, 5.5), (4.5, 5.5), (4.5, 4.5)]
    nested = module.rings_to_polygons([outer, island, hole, island_hole])
    assert [outer, hole] in nested and [island, island_hole] in nested


# The engine worker, started in Node: importScripts reads docs/js, and the
# names it was asked for are written out, with what the engine answered.
_JS_WORKER = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import vm from 'node:vm';
const dir = process.argv[2];
const imported = [];
const sandbox = { console, URL, postMessage() {},
  location: { href: 'http://localhost/js/gwt-worker.js' } };
sandbox.self = sandbox;
sandbox.importScripts = (...urls) => urls.forEach((url) => {
  const name = new URL(url, sandbox.location.href).pathname.split('/').pop();
  imported.push(name);
  vm.runInContext(readFileSync(dir + '/' + name, 'utf8'), sandbox, { filename: name });
});
vm.createContext(sandbox);
vm.runInContext('var globalThis = this;', sandbox);
sandbox.importScripts('gwt-worker.js');
const started = imported.slice();
const district = sandbox.GWT.core.districtOfPoint(8.484, -13.234);
writeFileSync(process.argv[3], JSON.stringify({ started, imported, district }));
"""


def test_the_engine_worker_imports_the_map_layers_when_a_task_reads_them(tmp_path):
    """The map layers left gwt-data.js; the worker still has them when asked.

    The page loads gwt-geo.js before it draws a page that reads it. A worker
    cannot be handed it that way, so the engine imports it, synchronously,
    the first time anything reads the layers; a worker that answered from an
    empty layer would put every point in no district and say nothing.
    """
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path / "worker.mjs"
    driver.write_text(_JS_WORKER, encoding="utf-8")
    out = tmp_path / "out.json"
    result = subprocess.run(
        [node, str(driver), str(REPO / "docs" / "js"), str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    found = json.loads(out.read_text(encoding="utf-8"))
    # starting takes the engine and its tables, not the layers
    assert found["started"] == ["gwt-worker.js", "gwt-data.js", "gwt-core.js"]
    # reading a district from a position fetches them, once
    assert found["imported"].count("gwt-geo.js") == 1
    assert found["district"] == "Western Area Urban"


def _node(tmp_path, script: str, *args: str) -> dict:
    """Run a Node script, written to tmp_path, with these arguments and then
    the path of the JSON file it writes; return what it wrote."""
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    driver = tmp_path / "driver.mjs"
    driver.write_text(script, encoding="utf-8")
    out = tmp_path / "out.json"
    result = subprocess.run([node, str(driver), *args, str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(out.read_text(encoding="utf-8"))


# The engine worker in Node again, running the two terrain tasks as the
# browser would: each request reaches it as a copy, and each answer is
# posted through structuredClone with the transfer list the worker gives,
# which moves the listed buffers as postMessage does (and, as postMessage
# does, refuses a list that names one buffer twice). The window is the
# holes_sea set: three Copernicus-style tiles beside a missing one taken as
# sea, read 15 km round its corner with a 10 km margin.
_JS_TRANSFER = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import vm from 'node:vm';
const [dir, dem, out] = process.argv.slice(2);
const posted = [];
const sandbox = { console, URL, performance, location: { href: 'http://localhost/js/gwt-worker.js' } };
sandbox.self = sandbox;
sandbox.postMessage = (message, transfer) => {
  const list = transfer || [];
  posted.push({ message, list, received: structuredClone(message, { transfer: list }) });
};
sandbox.importScripts = (...urls) => urls.forEach((url) => {
  const name = new URL(url, sandbox.location.href).pathname.split('/').pop();
  vm.runInContext(readFileSync(dir + '/' + name, 'utf8'), sandbox, { filename: name });
});
vm.createContext(sandbox);
vm.runInContext('var globalThis = this;', sandbox);
sandbox.importScripts('gwt-worker.js');
const C = sandbox.GWT.core;

// what the worker asks of the engine, which it reads off GWT.core when a
// task runs: the precision an analysis is made in, what the analysis
// holds its drawn layers in, and the most cells a side of the display
const engineAnalyse = C.analyseTerrain, engineDisplay = C.terrainDisplayLayers;
const spied = { precision: [], twi: [], edge: [] };
C.analyseTerrain = (grid, cfg, progress, precision, shown) => {
  const analysis = engineAnalyse(grid, cfg, progress, precision, shown);
  spied.precision.push(precision);
  spied.twi.push(analysis.twi.constructor.name);
  return analysis;
};
C.terrainDisplayLayers = (analysis, grid, maxEdge) => {
  spied.edge.push(maxEdge);
  return engineDisplay(analysis, grid, maxEdge);
};

// the page's part: open the files, plan the window, cut out its blocks
const names = ['holes_N08W012.tif', 'holes_sea_N08W013.tif', 'holes_sea_N07W012.tif'];
const bytes = Object.fromEntries(names.map((name) => [name, new Uint8Array(readFileSync(dem + '/' + name))]));
const files = names.map((name) => C.elevationFile(name, bytes[name].length, [[0, bytes[name]]]));
const centre = { lon: -12.0, lat: 8.0, label: 'the test point', exact: true, note: null };
const plan = C.planElevationWindow(files, centre, 15.0, null, 10.0, ['copernicus_glo30', '']);
const blocks = new Array(plan.blocks.length);
for (const r of C.elevationBlockRanges(plan)) {
  const merged = bytes[r.name].slice(r.offset, r.offset + r.length);
  for (const b of r.blocks) {
    const at = plan.blocks[b].offset - r.offset;
    blocks[b] = merged.slice(at, at + plan.blocks[b].length);
  }
}

// one request as the page sends it, a copy, and what the worker posted
function ask(id, type, payload) {
  sandbox.onmessage({ data: structuredClone({ id, type, payload }) });
  return posted[posted.length - 1];
}
// an answer that did not come back ends the run with what came instead
function answered(post) {
  if (post.message.result !== undefined) return post;
  writeFileSync(out, JSON.stringify({ failed: post.message }));
  process.exit(0);
}
// for each array named: whether its buffer is in the transfer list,
// whether the worker's own array is now empty (a buffer handed over has
// no bytes left), and how many values the page received
function moved(post, sent, got) {
  const fates = {};
  for (const [name, array] of Object.entries(sent)) {
    fates[name] = { listed: post.list.includes(array.buffer), detached: array.buffer.byteLength === 0,
      length: got[name].length };
  }
  return fates;
}
function named(object, prefix, keys) {
  return Object.fromEntries(keys.map((key) => [prefix + key, object[key]]));
}
const same = (a, b) => a.length === b.length && Array.from(a).every((v, i) => Object.is(v, b[i]));

const read = answered(ask(1, 'readElevation', { plan, blocks, cfg: null }));
const r = read.message.result, got = read.received.result;
const GRID = ['z', 'lons', 'lats', 'assumedSea'];
const onPage = C.readElevationWindow(plan, blocks, null, null);

const grid = got.grid, where = 'the test point';
const analysed = answered(ask(2, 'analyseTerrain', { grid, cfg: null, read: { ...got, grid: null },
  where }));
const a = analysed.message.result, b = analysed.received.result;
const DISPLAY = ['lons', 'lats', 'z', 'hillshadeMulti', 'twi', 'profile', 'tangential', 'cls', 'assumedSea',
  'raised', 'stream', 'flag'];
const CORE = ['lons', 'lats', 'dx', 'dy', 'dg', 'count', 'areaUnits', 'cls', 'code', 'flag', 'raised',
  'flatRouted'];
const sentLayers = { ...named(a.display, 'display.', DISPLAY), ...named(a.core, 'core.', CORE) };
const gotLayers = { ...named(b.display, 'display.', DISPLAY), ...named(b.core, 'core.', CORE) };
a.display.hillshades.forEach((layer, k) => {
  sentLayers['display.hillshades.' + k] = layer;
  gotLayers['display.hillshades.' + k] = b.display.hillshades[k];
});
const direct = engineAnalyse(onPage.grid, null, null, 'float32', onPage.grid.shown);
const directCore = C.terrainCore(direct);

// a refusal is an error, with nothing to hand over, and another task's
// answer hands nothing over either
const descending = { ...grid, lats: Float64Array.from(grid.lats).reverse() };
const refused = ask(3, 'analyseTerrain', { grid: descending, cfg: null, read: null, where });
const other = ask(4, 'recompute', { sources: {} });

// a square shown 1,100 cells a side, wider than the display's 1,024: a
// plane rising to the north-east, with a margin of 4 cells
const side = 1108, step = 1 / 3600;
const plane = {
  lons: Float64Array.from({ length: side }, (_, i) => -12.0 + i * step),
  lats: Float64Array.from({ length: side }, (_, j) => 8.0 + j * step),
  z: Float64Array.from({ length: side * side }, (_, k) => 100.0 + 0.01 * (k % side) + 0.02 * Math.floor(k / side)),
  rows: side, cols: side, shown: [4, 1104, 4, 1104], assumedSea: null, sourceId: 'unidentified', seaClean: false,
  label: 'a plane',
};
const thinned = answered(ask(5, 'analyseTerrain', { grid: plane, cfg: null, read: null, where })).received.result;

writeFileSync(out, JSON.stringify({
  ready: posted[0].message.ready === true,
  read: {
    moved: moved(read, { ...named(r.grid, 'grid.', GRID), reasons: r.reasons },
      { ...named(got.grid, 'grid.', GRID), reasons: got.reasons }),
    listed: read.list.length,
    rows: got.grid.rows, cols: got.grid.cols, assumed: got.assumed,
    same: same(got.grid.z, onPage.grid.z) && same(got.reasons, onPage.reasons) &&
      same(got.grid.assumedSea, onPage.grid.assumedSea),
  },
  analyse: {
    moved: moved(analysed, sentLayers, gotLayers), listed: analysed.list.length,
    display: [b.display.rows, b.display.cols], core: [b.core.rows, b.core.cols],
    keys: Object.keys(b).sort(),
    same: same(b.core.areaUnits, directCore.areaUnits) && same(b.core.code, directCore.code) &&
      JSON.stringify(b.summary) === JSON.stringify(direct.summary) &&
      JSON.stringify(b.captions) === JSON.stringify(C.terrainCaptions(direct, onPage, where)),
  },
  refused: { error: refused.message.error, listed: refused.list.length },
  descend: C.phrase('terrain.axes_descend'),
  other: { error: other.message.error || null, listed: other.list.length },
  spied,
  thinned: {
    at: [thinned.display.stride, thinned.display.rows, thinned.display.cols],
    lengths: Object.entries(thinned.display).flatMap(([key, v]) => (ArrayBuffer.isView(v) ? [[key, v.length]]
      : key === 'hillshades' ? v.map((layer) => [key, layer.length]) : [])),
  },
}));
"""


def test_the_worker_hands_terrain_layers_back_by_transfer(tmp_path):
    """A terrain answer is handed to the page, not copied, and only the answer.

    At the cap on cells the grid read and the layers of the analysis run to
    tens of megabytes, and a copy holds each of them twice while it is made,
    on a device that may be short of memory already. Each terrain answer
    names every buffer under its arrays in the transfer list, and each one
    once: a buffer named twice makes the whole answer fail to clone, and
    one left out is copied. An error or another task's answer hands nothing
    over. The worker analyses in float32, so that the layers only drawn
    take half the memory, and thins the display to 1,024 cells a side,
    which a square shown at the cap is wider than.
    """
    found = _node(tmp_path, _JS_TRANSFER, str(REPO / "docs" / "js"),
                  str(REPO / "tests" / "webapp" / "fixtures" / "dem"))
    # an answer that would not clone comes back as an error, uncloneable
    assert "failed" not in found, found.get("failed")
    assert found["ready"]

    read = found["read"]
    rows, cols = read["rows"], read["cols"]
    assert read["assumed"] > 0, "the window holds no missing tile taken as sea"
    assert read["moved"] == {
        "grid.z": {"listed": True, "detached": True, "length": rows * cols},
        "grid.lons": {"listed": True, "detached": True, "length": cols},
        "grid.lats": {"listed": True, "detached": True, "length": rows},
        "grid.assumedSea": {"listed": True, "detached": True, "length": rows * cols},
        "reasons": {"listed": True, "detached": True, "length": rows * cols},
    }
    assert read["listed"] == 5, "the list names a buffer the answer does not hold"
    assert read["same"], "the read the page receives is not the read the engine gives"

    analyse = found["analyse"]
    # the lineament candidates (PLAN.md step 4.2) are plain objects and
    # numbers, copied: no buffer of theirs is handed over
    assert analyse["keys"] == ["captions", "core", "display", "kCells", "lineamentCaptions", "lineaments", "links",
                               "parts", "summary"]
    (high, wide), (rows, cols) = analyse["display"], analyse["core"]
    lengths = {"display.lons": wide, "display.lats": high, "core.lons": cols, "core.lats": rows,
               "core.dx": rows, "core.dy": rows, "core.dg": rows}
    moved = analyse["moved"]
    assert "display.hillshades.0" in moved
    for name, fate in moved.items():
        length = lengths.get(name, high * wide if name.startswith("display.") else rows * cols)
        assert fate == {"listed": True, "detached": True, "length": length}, name
    assert analyse["listed"] == len(moved), "the list names a buffer the answer does not hold"
    assert analyse["same"], "the analysis the page receives is not the one the engine gives"

    assert found["refused"] == {"error": {"name": "Error", "message": found["descend"]}, "listed": 0}
    assert found["other"] == {"error": None, "listed": 0}

    # every analysis the worker made (the descending grid was refused before
    # it had one) was in float32 and thinned to 1,024 cells a side
    assert found["spied"] == {"precision": ["float32", "float32"], "twi": ["Float32Array", "Float32Array"],
                              "edge": [1024, 1024]}
    # 1,100 cells a side are drawn from every other one
    thinned = found["thinned"]
    assert thinned["at"] == [2, 550, 550]
    assert thinned["lengths"] and all(
        length == (550 if key in ("lons", "lats") else 550 * 550) for key, length in thinned["lengths"]
    ), thinned["lengths"]


# GWT.engine on a page, in Node, with a Worker the script drives by hand: it
# says it is ready, or not, then fails in one of the ways a real one does
# (an error event, a message that cannot be read, an answer it could not
# send). Each case runs in a context of its own, since a worker that fails
# before it is ready sends every later request to the page. The grid is a
# small tilted surface, enough for the analysis to run when the page has to
# run it.
_JS_ENGINE_STOPS = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import vm from 'node:vm';
const [dir, out] = process.argv.slice(2);
const SCRIPTS = ['gwt-data.js', 'gwt-core.js', 'gwt-worker.js'].map((name) =>
  [name, readFileSync(dir + '/' + name, 'utf8')]);

function page() {
  const workers = [], warnings = [];
  class Worker {
    constructor(url) {
      this.url = url;
      this.sent = [];
      this.terminated = false;
      workers.push(this);
    }
    // what reaches the worker is a copy, as postMessage makes one, with
    // the buffers listed handed over
    postMessage(message, transfer) {
      this.sent.push({ message: structuredClone(message, { transfer: transfer || [] }),
        transfer: transfer === undefined ? null : transfer });
    }
    terminate() { this.terminated = true; }
  }
  const sandbox = { URL, structuredClone, performance, setTimeout, clearTimeout, Worker,
    console: { log: console.log, error: console.error, warn: (text) => warnings.push(text) },
    location: { protocol: 'http:', href: 'http://localhost/' } };
  vm.createContext(sandbox);
  for (const [name, text] of SCRIPTS) vm.runInContext(text, sandbox, { filename: name });
  return { engine: sandbox.GWT.engine, workers, warnings };
}

const rows = 24, cols = 24, step = 1 / 3600;
const grid = {
  lons: Float64Array.from({ length: cols }, (_, i) => -12.0 + i * step),
  lats: Float64Array.from({ length: rows }, (_, j) => 8.0 + j * step),
  z: Float64Array.from({ length: rows * cols }, (_, k) => 40.0 + 0.5 * (k % cols) + 0.25 * Math.floor(k / cols) +
    0.1 * ((k * 7919) % 13)),
  rows, cols, shown: [4, 20, 4, 20], assumedSea: null, sourceId: 'unidentified', seaClean: false,
  label: 'a test surface', credit: null, notice: null, surface: null, files: ['test.tif'],
  cellNote: 'about 31 by 31 m',
};
const plan = { blocks: [] }, blocks = [new Uint8Array([1, 2, 3, 4])];
const terrain = {
  readElevation: (engine) => engine.readElevation(plan, blocks, null),
  analyseTerrain: (engine) => engine.analyseTerrain(grid, null, null, 'the test point'),
};

// how the worker fails, after or before it said it was ready
const FAILS = {
  crashed: (worker) => worker.onerror({ message: 'out of memory', preventDefault() {} }),
  unreadable: (worker) => worker.onmessageerror({}),
  uncloneable: (worker) => worker.onmessage({ data: { id: worker.sent[0].message.id,
    error: { name: 'DataCloneError', message: 'the answer would not clone' }, uncloneable: true } }),
};
// the error a task threw, which the worker answers with and goes on: an
// array Chromium or Firefox found no memory for, or the engine's refusal
const THROWN = {
  chromium: { name: 'RangeError', message: 'Array buffer allocation failed' },
  firefox: { name: 'Error', message: 'out of memory' },
  refused: { name: 'Error', message: 'The window holds no elevations.' },
};

async function settled(promise) {
  try {
    const result = await promise;
    return { resolved: Object.keys(result).sort() };
  } catch (e) {
    return { rejected: [e.name, e.message] };
  }
}
function report(engine, workers, warnings, outcome) {
  return {
    ...outcome,
    history: engine.history().map((h) => [h.type, h.mode, h.outcome]),
    sent: workers.flatMap((w) => w.sent.map((s) => [s.message.type, s.transfer])),
    workers: workers.length, terminated: workers.map((w) => w.terminated),
    mode: engine.mode(), unavailable: engine.unavailable(), warnings,
  };
}
// one request on a page of its own: the worker says it is ready (or not)
// and then fails as asked
async function run(start, fail, ready) {
  const { engine, workers, warnings } = page();
  const promise = start(engine);
  if (ready) workers[0].onmessage({ data: { ready: true } });
  fail(workers[0]);
  const outcome = await settled(promise);
  return report(engine, workers, warnings, outcome);
}

const found = { stopped: {}, rerun: {}, thrown: {} };
for (const fail of Object.keys(FAILS)) {
  for (const [task, start] of Object.entries(terrain)) {
    found.stopped[fail + ' ' + task] = await run(start, FAILS[fail], true);
  }
  found.rerun[fail] = await run((engine) => engine.recompute({ sources: {} }), FAILS[fail], true);
}
for (const [kind, error] of Object.entries(THROWN)) {
  const fail = (worker) => worker.onmessage({ data: { id: worker.sent[0].message.id, error } });
  for (const [task, start] of Object.entries(terrain)) found.thrown[kind + ' ' + task] = await run(start, fail, true);
  found.thrown[kind + ' recompute'] = await run((engine) => engine.recompute({ sources: {} }), fail, true);
}
found.beforeReady = await run(terrain.analyseTerrain, FAILS.crashed, false);
{
  const { engine, workers, warnings } = page();
  engine.forcePage(true);
  found.pageOnly = report(engine, workers, warnings, await settled(terrain.analyseTerrain(engine)));
}
{
  const { engine, workers, warnings } = page();
  const promise = terrain.analyseTerrain(engine);
  workers[0].onmessage({ data: { ready: true } });
  const stopped = engine.cancel(['readElevation', 'analyseTerrain']);
  found.cancelled = { stopped, ...report(engine, workers, warnings, await settled(promise)) };
}
{
  // a read answered, then an analysis, then another request: the worker
  // that answered the analysis is stopped, and the request after it starts
  // a fresh one
  const { engine, workers, warnings } = page();
  const answer = (worker) => worker.onmessage({ data: { id: worker.sent[worker.sent.length - 1].message.id,
    result: { answered: true } } });
  const read = terrain.readElevation(engine);
  workers[0].onmessage({ data: { ready: true } });
  answer(workers[0]);
  const afterRead = { ...await settled(read), terminated: workers.map((w) => w.terminated) };
  const analysis = terrain.analyseTerrain(engine);
  answer(workers[0]);
  const outcome = await settled(analysis);
  engine.recompute({ sources: {} });
  found.answered = { afterRead, ...report(engine, workers, warnings, outcome) };
}
// a buffer handed over has no bytes left
found.blocksKept = blocks[0].length === 4 && blocks[0].buffer.byteLength > 0 && grid.z.buffer.byteLength > 0;
writeFileSync(out, JSON.stringify(found));
"""


def test_a_terrain_job_is_not_rerun_on_the_page_after_the_started_worker_stops(tmp_path):
    """A terrain job the started worker loses fails with a sentence.

    Any other job the worker loses is run again on the page. A terrain job
    that stops the worker has most likely run it out of memory, and the
    same job run again on the page would then take the tab down with it.
    So once the worker has said it is ready, a crash, an answer that cannot
    be read and an answer that could not be sent each fail a terrain job
    with an error named WorkerStopped, which says to try a smaller radius.
    So does an array the browser found no memory for: the task throws, and
    the worker answers with the error and goes on, which is how most
    terrain jobs short of memory end; that worker is stopped. The engine's
    own refusal still comes through in its words. A worker that fails
    before it is ready never ran the job, so the job still runs on the
    page, as every later one does; and where the page is the engine from
    the start, a terrain job runs there as any other.
    """
    found = _node(tmp_path, _JS_ENGINE_STOPS, str(REPO / "docs" / "js"))
    stopped = ["WorkerStopped", ("The background engine stopped while working out the terrain, most "
                                 "likely for lack of memory; try a smaller radius.")]
    for case, got in found["stopped"].items():
        task, failure = case.split()[1], case.split()[0]
        assert got.get("rejected") == stopped, (case, got)
        # the worker had it, and nothing ran on the page
        assert got["history"] == [[task, "worker", "failed"]], case
        # the request went as a copy, with nothing handed over
        assert got["sent"] == [[task, None]], case
        # the worker stays the engine, and only a crashed one is stopped, or
        # one that had an analysis
        assert got["mode"] == "worker" and got["unavailable"] == "", case
        assert got["terminated"] == [failure == "crashed" or task == "analyseTerrain"], case
        if failure == "uncloneable":
            assert got["warnings"] == [(f"The engine worker could not send back its answer to {task} "
                                        "(the answer would not clone).")], case

    for failure, got in found["rerun"].items():
        assert "resolved" in got, (failure, got)
        assert got["history"] == [["recompute", "page", "done"]], failure
        assert got["mode"] == "worker", failure
    assert found["rerun"]["uncloneable"]["warnings"] == [
        ("The engine worker could not send back its answer to recompute (the answer would not clone); "
         "working it out on the page.")]

    errors = {"chromium": ["RangeError", "Array buffer allocation failed"], "firefox": ["Error", "out of memory"],
              "refused": ["Error", "The window holds no elevations."]}
    for case, got in found["thrown"].items():
        kind, task = case.split()
        assert got["history"] == [[task, "worker", "failed"]] and got["sent"] == [[task, None]], case
        assert got["mode"] == "worker", case
        if kind != "refused" and task != "recompute":
            # a terrain job short of memory: the sentence, and its worker stopped
            assert got.get("rejected") == stopped and got["terminated"] == [True], case
        else:
            # the task's own error in its own words, from a worker that is
            # kept unless it had an analysis
            assert got.get("rejected") == errors[kind], case
            assert got["terminated"] == [task == "analyseTerrain"], case

    before = found["beforeReady"]
    assert before.get("resolved") == ["captions", "core", "display", "kCells", "lineamentCaptions", "lineaments",
                                      "links", "parts", "summary"], before
    assert before["history"] == [["analyseTerrain", "page", "done"]]
    assert before["mode"] == "page" and before["unavailable"].startswith("it did not start")

    page_only = found["pageOnly"]
    assert page_only["resolved"] == before["resolved"]
    assert page_only["history"] == [["analyseTerrain", "page", "done"]] and page_only["workers"] == 0

    cancelled = found["cancelled"]
    assert cancelled["stopped"] == 1 and cancelled["rejected"][0] == "Cancelled"
    assert cancelled["history"] == [["analyseTerrain", "worker", "cancelled"]] and cancelled["terminated"] == [True]

    assert found["blocksKept"], "the page's blocks or grid went with a request"


def test_the_worker_that_analysed_the_terrain_is_stopped_once_it_has_answered(tmp_path):
    """An idle worker would keep the analysis it answered from.

    The answer's layers are handed over, but the rest of the analysis is
    garbage the idle worker may hold for minutes, a hundred megabytes and
    more at the default window, while the page draws the figures on top of
    it. So the worker is stopped once an analysis is answered, and the next
    request starts a fresh one; a read answered keeps its worker for the
    analysis that follows it.
    """
    found = _node(tmp_path, _JS_ENGINE_STOPS, str(REPO / "docs" / "js"))
    answered = found["answered"]
    assert answered["afterRead"] == {"resolved": ["answered"], "terminated": [False]}
    assert answered["resolved"] == ["answered"]
    assert answered["history"] == [["readElevation", "worker", "done"], ["analyseTerrain", "worker", "done"]]
    # the read and the analysis went to the first worker, the request after
    # them to a second
    assert answered["sent"] == [["readElevation", None], ["analyseTerrain", None], ["recompute", None]]
    assert answered["workers"] == 2 and answered["terminated"] == [True, False]

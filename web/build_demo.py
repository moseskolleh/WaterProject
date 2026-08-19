"""Build the browser-only demo site (GitHub Pages) with stlite.

Generates ``docs/index.html``: a self-contained page that runs the
Streamlit app entirely in the visitor's browser via stlite (Streamlit
compiled to WebAssembly with Pyodide). No server is involved; uploads
never leave the browser. The page inlines the whole ``groundwater``
package, the app script and the bundled sample datasets, so the only
external fetches are the stlite runtime and the Pyodide/scientific
wheels from the jsDelivr CDN, plus the app's display fonts from
Google Fonts (optional: system fallbacks are used when that fetch
fails, e.g. offline).

Run from the repository root:

    python web/build_demo.py                # production build into docs/
    python web/build_demo.py --stlite-base ./vendor/stlite/build \
        --pyodide-url ./vendor/pyodide/pyodide.mjs --out docs_local
                                            # self-hosted assets (testing)

Pinned runtime: @stlite/browser 1.8.1, which bundles Streamlit 1.57.0
and defaults to Pyodide v0.29.3 (Python 3.13, numpy 2.2.5,
scipy 1.14.1, matplotlib 3.8.4). The test suite is run against these
exact package versions in CI-style verification.
"""

from __future__ import annotations

import argparse
import base64
import json
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

STLITE_VERSION = "1.8.1"
DEFAULT_STLITE_BASE = f"https://cdn.jsdelivr.net/npm/@stlite/browser@{STLITE_VERSION}/build"

# Installed by micropip in the browser. numpy/scipy/matplotlib/PyYAML/lxml
# resolve to Pyodide-built wasm wheels; python-docx/openpyxl/et-xmlfile are
# pure-Python wheels fetched from PyPI.
REQUIREMENTS = [
    "numpy",
    "scipy",
    "matplotlib",
    "openpyxl",
    "python-docx",
    "PyYAML",
]

SAMPLE_FILES = [
    "rokel/rokel_ves.xlsx",
    "rokel/rokel_ipi2win_models.xlsx",
    "kuntolo/kuntolo_step_test.xlsx",
    "dr_timbo/dr_timbo_drilling_log.xlsx",
    "dr_timbo/dr_timbo_constant_test.xlsx",
    "dr_timbo/dr_timbo_water_quality.xlsx",
]

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
<title>Groundwater Toolkit - Browser Demo</title>
<link rel="icon" type="image/svg+xml" href="__FAVICON_SVG__" />
<link rel="stylesheet" href="__STLITE_CSS__" />
<style>
  /* The first visit downloads about 60 MB, so this screen is on show for a
     while. It uses the app's own palette, injected from .streamlit/config.toml,
     so the demo looks like the toolkit before the toolkit has finished loading
     rather than like a broken page. */
  html, body, #root { height: 100%; margin: 0; padding: 0; }
  body {
    background: __BG__;
    color: __TEXT__;
    font-family: "Source Sans 3", "Source Sans Pro", -apple-system, system-ui, sans-serif;
  }
  #boot {
    min-height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem;
    box-sizing: border-box;
  }
  #boot-card {
    max-width: 30rem;
    text-align: center;
  }
  #boot-mark { width: 72px; height: 72px; margin: 0 auto 1.25rem; display: block; }
  #boot-title {
    margin: 0 0 .5rem;
    font-size: 1.4rem;
    font-weight: 600;
    color: __PRIMARY__;
    letter-spacing: -0.01em;
  }
  #boot-note { margin: 0; line-height: 1.6; opacity: .75; font-size: .95rem; }
  #boot-bar {
    margin: 1.5rem auto 0;
    width: 12rem;
    height: 4px;
    border-radius: 999px;
    background: __BORDER__;
    overflow: hidden;
  }
  #boot-bar::after {
    content: "";
    display: block;
    width: 40%;
    height: 100%;
    border-radius: 999px;
    background: __PRIMARY__;
    animation: boot-slide 1.4s ease-in-out infinite;
  }
  @keyframes boot-slide {
    0%   { transform: translateX(-100%); }
    100% { transform: translateX(350%); }
  }
  @media (prefers-reduced-motion: reduce) {
    #boot-bar::after { animation: none; width: 100%; opacity: .5; }
  }
</style>
</head>
<body>
<div id="root"><div id="boot"><div id="boot-card">
<img id="boot-mark" src="__FAVICON_SVG__" alt="" />
<h1 id="boot-title">Groundwater Investigation Toolkit</h1>
<p id="boot-note">Starting the browser demo. The Python runtime and scientific
libraries (about 60 MB) are downloaded on first visit and cached by the browser
afterwards.</p>
<div id="boot-bar"></div>
</div></div></div>
<script type="module">
import { mount } from "__STLITE_JS__";

const FILES = __FILES_JSON__;

const files = {};
for (const [path, spec] of Object.entries(FILES)) {
  files[path] =
    spec.t === "b64" ? Uint8Array.from(atob(spec.d), (c) => c.charCodeAt(0)) : spec.d;
}

mount(
  {
    entrypoint: "streamlit_app.py",
    files,
    requirements: __REQUIREMENTS_JSON__,
__PYODIDE_LINE__
    streamlitConfig: __THEME_JSON__,
  },
  document.getElementById("root"),
);
</script>
</body>
</html>
"""


def collect_files() -> dict:
    """Gather every file the app needs, keyed by its mount path."""
    files: dict[str, dict] = {}

    app_source = (REPO / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    files["streamlit_app.py"] = {"t": "text", "d": app_source}

    # The whole package ships, including depth_spine: importing it no longer
    # needs the component build, and it carries a self-contained static
    # workspace (.html) that st.components.v1.html can show here, where a
    # custom component cannot run.
    package_root = REPO / "src" / "groundwater"
    for path in sorted(package_root.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        mount_path = "groundwater/" + path.relative_to(package_root).as_posix()
        if path.suffix in (".py", ".csv", ".yaml", ".txt", ".md", ".html"):
            files[mount_path] = {"t": "text", "d": path.read_text(encoding="utf-8")}
        else:
            files[mount_path] = {
                "t": "b64",
                "d": base64.b64encode(path.read_bytes()).decode("ascii"),
            }

    for rel in SAMPLE_FILES:
        source = REPO / "examples" / "data" / rel
        if not source.exists():
            raise FileNotFoundError(
                f"{source} is missing; run examples/build_sample_data.py first"
            )
        files[f"examples/data/{rel}"] = {
            "t": "b64",
            "d": base64.b64encode(source.read_bytes()).decode("ascii"),
        }
    return files


def _script_safe_json(value) -> str:
    """JSON that can live inside a <script> block.

    An HTML parser ends a script at the first literal ``</script>``, wherever
    it appears - including inside a JavaScript string. Any inlined file that
    mentions one would truncate the whole bundle, and everything after it would
    be parsed as markup. Escaping ``<`` keeps the JSON valid and the tag
    unrecognisable to the parser.
    """
    return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c")


def app_theme() -> dict[str, str]:
    """The app's own theme, read from .streamlit/config.toml.

    The demo used to carry a second copy of these values, which is one edit
    away from the browser demo and the hosted app being different colours.
    Read the app's config instead, so there is only ever one palette.
    """
    config = REPO / ".streamlit" / "config.toml"
    with open(config, "rb") as fh:
        data = tomllib.load(fh)

    theme = data.get("theme", {}) or {}
    sidebar = theme.pop("sidebar", {}) or {}
    flat = {f"theme.{key}": value for key, value in theme.items()}
    flat.update({f"theme.sidebar.{key}": value for key, value in sidebar.items()})
    # The demo is a read-only shop window: no "deploy" or "edit" affordances.
    flat["client.toolbarMode"] = "viewer"
    return flat


def _favicon_data_uri() -> str:
    """The brand droplet SVG inlined as the page favicon."""
    svg_path = REPO / "src" / "groundwater" / "data" / "brand" / "icon.svg"
    if not svg_path.exists():
        return ""
    encoded = base64.b64encode(svg_path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def build(out_dir: Path, stlite_base: str, pyodide_url: str | None) -> Path:
    files = collect_files()
    pyodide_line = (
        f'    pyodideUrl: {json.dumps(pyodide_url)},' if pyodide_url else "    // pyodideUrl: default (jsDelivr)"
    )
    theme = app_theme()
    html = (
        TEMPLATE
        .replace("__FAVICON_SVG__", _favicon_data_uri())
        # json.dumps closes the object at column 0; nudge it back so the
        # generated script stays readable when someone views source.
        .replace("__THEME_JSON__", json.dumps(theme, indent=6)[:-1] + "    }")
        # The boot screen borrows the app's own colours, so there is still only
        # one palette to change.
        .replace("__BG__", theme.get("theme.backgroundColor", "#FFFFFF"))
        .replace("__TEXT__", theme.get("theme.textColor", "#222222"))
        .replace("__PRIMARY__", theme.get("theme.primaryColor", "#2B6850"))
        .replace("__BORDER__", theme.get("theme.borderColor", "#DDDDDD"))
        .replace("__STLITE_CSS__", f"{stlite_base}/stlite.css")
        .replace("__STLITE_JS__", f"{stlite_base}/stlite.js")
        .replace("__FILES_JSON__", _script_safe_json(files))
        .replace("__REQUIREMENTS_JSON__", _script_safe_json(REQUIREMENTS))
        .replace("__PYODIDE_LINE__", pyodide_line)
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("")
    size_kb = out.stat().st_size / 1024
    print(f"wrote {out} ({size_kb:.0f} KB, {len(files)} files inlined)")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO / "docs"), help="output directory")
    parser.add_argument("--stlite-base", default=DEFAULT_STLITE_BASE,
                        help="base URL of the stlite build directory")
    parser.add_argument("--pyodide-url", default=None,
                        help="override the Pyodide runtime URL (self-hosting)")
    args = parser.parse_args()
    build(Path(args.out), args.stlite_base.rstrip("/"), args.pyodide_url)


if __name__ == "__main__":
    main()

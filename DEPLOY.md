# Hosting the toolkit online

Two ready-to-use options. Option A gives you a URL on GitHub Pages in
about two minutes with no accounts beyond GitHub. Option B runs the
full server version on Streamlit Community Cloud (free, needs one
login).

## Option A: GitHub Pages (browser-only demo)

The repository contains a pre-built browser version of the app in
`docs/` (`docs/index.html`). It runs the complete toolkit inside the
visitor's browser through WebAssembly (stlite/Pyodide): no server, and
uploaded files never leave the visitor's machine. All bundled sample
datasets are included, so anyone can try every tab with one click.

Enable it once:

1. Open the repository on GitHub: `https://github.com/moseskolleh/WaterProject`
2. Go to **Settings -> Pages** (left sidebar, "Code and automation").
3. Under **Build and deployment**, set Source to **Deploy from a
   branch**. If it currently shows "GitHub Actions", change it: that
   mode publishes nothing until a workflow hands GitHub a site.
4. Two dropdowns appear. Pick Branch: **main**, folder: **/docs**,
   then click **Save**.
5. After about a minute the site is live at:

   `https://moseskolleh.github.io/WaterProject/`

Notes:

- First visit downloads the Python runtime and scientific libraries
  (about 60 MB, from the jsDelivr CDN); the browser caches them, so
  later visits start quickly.
- Heavy steps (the VES inversion) take roughly 5 to 10 times longer
  than the server version. A note in the app tells visitors this.
- The AI scan extraction is not available in the browser build; the
  tab explains that. Everything else works: parsing, checks, VES
  inversion, pumping tests, water quality, borehole design, and
  downloading the .docx reports.
- The demo is rebuilt with `python web/build_demo.py` (commit the
  regenerated `docs/index.html` afterwards). Rebuild whenever the app,
  the package or the sample data changes.

If the repository is private: GitHub Pages on private repositories
requires GitHub Pro/Team; either make the repository public or use
Option B.

## Option B: Streamlit Community Cloud (full version)

Runs the real server app, including PDF text extraction and (with an
API key) the AI-assisted scan extraction. The app is deployed at
`https://waterproject.streamlit.app/`.

1. Go to `https://share.streamlit.io` and sign in with GitHub.
2. Click **Create app** -> **Deploy a public app from GitHub** (private
   repositories are also supported after granting access).
3. Fill in:
   - Repository: `moseskolleh/WaterProject`
   - Branch: `main`
   - Main file path: `app/streamlit_app.py`

   If the form asks for a GitHub URL to a .py file instead, paste:
   `https://github.com/moseskolleh/WaterProject/blob/main/app/streamlit_app.py`
4. Click **Deploy**. The build installs `requirements.txt` (which also
   installs this package via the `.` line) and starts the app at
   `https://<your-app-name>.streamlit.app`.

Optional, for AI scan extraction: in the app's **Settings -> Secrets**
add

```
ANTHROPIC_API_KEY = "sk-ant-..."
```

and add a line `anthropic` to `requirements.txt`.

## What was verified

- Full test suite (64 tests: parsers, numerics, reports, and
  Streamlit UI flows driven through AppTest) passes in a clean venv
  installed exactly the way Streamlit Cloud installs it.
- The same suite passes against the exact package versions the
  browser build ships (Python 3.13; numpy 2.2.5, scipy 1.14.1,
  matplotlib 3.8.4, pandas 2.3.3, streamlit 1.57.0 from the pinned
  stlite 1.8.1 / Pyodide 0.29.3 runtime).
- The built `docs/index.html` was booted in a real Chromium browser:
  the stlite runtime loads, the Python (WASM) interpreter starts and
  all 59 inlined files (package, app, sample data) mount correctly.
  The scientific wheels come from the public CDN at visit time, which
  is standard Pyodide infrastructure.
- pyarrow is pinned below 25 in `requirements.txt`; 25.0.0 was
  observed to crash streamlit's table serialization in sandboxed
  Linux environments.

# Hosting the toolkit online

Two ready-to-use options. Option A gives you a URL on GitHub Pages in
about two minutes with no accounts beyond GitHub. Option B runs the
full server version on Streamlit Community Cloud (free, needs one
login).

## Option A: GitHub Pages (no server, nothing to install)

`docs/` is the published site. It holds two things:

- **`docs/index.html` — the standalone web app.** Plain HTML, CSS and
  JavaScript: no Python runtime, no build step, no dependencies fetched
  at visit time. It starts in well under a second, works offline once
  loaded, and does the whole job — reading the field workbooks,
  inverting the soundings, analysing the pumping tests, assessing the
  water quality, designing the borehole, costing the works, running the
  supervision checklists and writing the .docx reports — entirely in
  the visitor's browser.
- **`docs/wasm/index.html` — the WebAssembly build.** The real Python
  package running through stlite/Pyodide, for anyone who wants the
  server app's exact behaviour in a browser. It costs a 60 MB first
  load; the standalone app is linked from its own About page.

Enable Pages once:

1. Open the repository on GitHub: `https://github.com/moseskolleh/WaterProject`
2. Go to **Settings -> Pages** (left sidebar, "Code and automation").
3. Under **Build and deployment**, set Source to **Deploy from a
   branch**. If it currently shows "GitHub Actions", change it: that
   mode publishes nothing until a workflow hands GitHub a site.
4. Two dropdowns appear. Pick Branch: **main**, folder: **/docs**,
   then click **Save**.
5. After about a minute the site is live at:

   `https://moseskolleh.github.io/WaterProject/`

   and the WebAssembly build at
   `https://moseskolleh.github.io/WaterProject/wasm/`.

### Rebuilding what `docs/` contains

The standalone app is hand-written source, not generated — edit
`docs/index.html`, `docs/css/gwt.css` and `docs/js/*.js` directly. Two
parts of it are generated and must be regenerated when their sources
change:

```bash
python web/build_webapp_data.py   # docs/js/gwt-data.js: the guideline
                                  # table, rate catalogue, checklists,
                                  # map layers and sample workbooks
python web/build_demo.py          # docs/wasm/index.html: the stlite build
```

CI fails if `docs/js/gwt-data.js` is out of date with the CSVs it is
built from, so the two can never drift apart.

### Checking it before you publish

```bash
npm install --no-save playwright && npx playwright install chromium
python tests/webapp/make_reference.py   # reference values from the Python package
node tests/webapp/parity.mjs            # browser engine vs those values
node tests/webapp/smoke.mjs             # every page, every report, in Chromium
```

`parity.mjs` runs the real sample workbooks through the browser
readers and analyses and compares the result against the Python
toolkit's own output, so the port cannot drift from the package it
came from. `smoke.mjs` loads each sample, visits every page, builds
every report and fails on any console error.

Notes:

- If the repository is private, GitHub Pages needs GitHub Pro/Team;
  either make the repository public or use Option B.
- No analytics, no CDN, no external fetches: everything the standalone
  app needs is served from `docs/`, which is also why it keeps working
  on a field laptop that has lost its connection.

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

- The standalone web app's engine is checked against the Python
  package on the bundled sample workbooks: the XLSX reader, all four
  field-sheet parsers, the VES forward model and inversion, the
  Cooper-Jacob/Theis/recovery/step analyses, the yield recommendation,
  the water quality assessment and the borehole design all agree, and
  the generated report prose matches character for character.
- The six .docx reports the app writes were opened with `python-docx`
  (a strict OOXML reader): headings, tables and embedded figures all
  parse, and the BoQ workbook reads back through `openpyxl`.
- Every page of the standalone app was driven in headless Chromium
  with an empty project and with each sample loaded, with no console
  errors.
- The full test suite (parsers, numerics, reports, and
  Streamlit UI flows driven through AppTest) passes in a clean venv
  installed exactly the way Streamlit Cloud installs it.
- The same suite passes against the exact package versions the
  browser build ships (Python 3.13; numpy 2.2.5, scipy 1.14.1,
  matplotlib 3.8.4, pandas 2.3.3, streamlit 1.57.0 from the pinned
  stlite 1.8.1 / Pyodide 0.29.3 runtime).
- The built `docs/wasm/index.html` was booted in a real Chromium browser:
  the stlite runtime loads, the Python (WASM) interpreter starts and
  all 59 inlined files (package, app, sample data) mount correctly.
  The scientific wheels come from the public CDN at visit time, which
  is standard Pyodide infrastructure.
- pyarrow is pinned below 25 in `requirements.txt`; 25.0.0 was
  observed to crash streamlit's table serialization in sandboxed
  Linux environments.

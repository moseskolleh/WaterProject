# Groundwater Investigation Toolkit

Analysis and reporting system for rural water supply borehole projects
in Sierra Leone. Covers the full project lifecycle: geophysical siting
surveys (vertical electrical sounding), borehole design, drilling
records, pumping tests, water quality assessment and handover to the
client. Raw field data goes in; client-ready figures, drawings and
.docx reports come out.

Built for crystalline basement terrain (weathered/fractured zone
aquifers above fresh basement) with the coastal sedimentary west in
mind, following RWSN professional drilling guidance and WHO drinking
water quality guidelines.

## What it produces

1. VES sounding curves, layered earth models and drilling preference tables
2. Survey maps (site location, iso-resistivity, overburden thickness) and GIS layers
3. To-scale borehole design drawings with lithology and construction columns
4. Pumping test analysis (Cooper-Jacob, Theis, recovery, step tests) with a
   recommended safe yield and pump setting depth
5. Water quality assessment against WHO and national standards, with
   ionic balance checks and Piper/Stiff diagrams
6. Borehole cost estimates and bills of quantities following the RWSN
   Cost-Effective Boreholes methodology (editable unit rates, cost and
   price kept apart, stage and resource breakdowns)
7. Drilling supervision checklists (procurement to post-construction)
   with field acceptance checks: sand content, verticality, screen
   open area, disinfection dose, handpump corrosion risk, drilled
   metres reconciliation against the signed daily logs
8. Multi-borehole programme estimates (shared mobilisation, expected
   dry attempts, indicative programme of works)
9. Location, geology and aquifer maps from real open datasets
   (geoBoundaries districts CC BY 4.0, USGS Geologic Map of Africa,
   BGS Africa Groundwater Atlas aquifer productivity CC BY-SA 4.0),
   embedded automatically into the survey and handover reports
10. Seven report types: geophysical survey, borehole completion,
    pumping test, water quality, project handover, cost estimate and
    supervision checklist record; the web app saves and reloads the
    whole working state as a project file
11. A rehabilitate-or-drill check: existing water points near the site
    from the Water Point Data Exchange (WPdx+, CC BY 4.0), turned into a
    recommendation - a broken improved source nearby is a rehabilitation
    candidate, a working one inside the service radius may already serve
    the community, otherwise new construction is justified
12. A water coverage-gap view at district or chiefdom resolution: areas
    ranked by population per functional water point, joining the 2015
    census populations (Statistics Sierra Leone) with WPDx points, as a
    choropleth and a ranked table to steer where to drill next. Chiefdom
    populations aggregate the census onto the boundary polygons with
    district totals conserved exactly and the reconciliation shown

## Try it online

- **Standalone web app (GitHub Pages, no server, no install):**
  <https://moseskolleh.github.io/WaterProject/>
- **Full app (Streamlit Community Cloud):**
  <https://waterproject.streamlit.app/>
- **WebAssembly build of the Streamlit app:** linked from the standalone
  app's *About & method* page (it sits beside it, under `wasm/`).

The published site is the `docs/` folder. GitHub Pages can be pointed
either at the repository root or at `/docs`, and the link above works
either way: a root-level `index.html` redirects to `docs/` when the
site is served from the root, and is simply not published when it is
served from `/docs`. Without that redirect a root-served site has no
index at all and renders this readme instead of the app.

The **standalone web app** is the toolkit rewritten to run entirely in
the browser as plain HTML, CSS and JavaScript. It starts instantly,
needs no Python runtime and does the whole job: reading the field
workbooks (and a pumping test written on a Word field sheet), inverting
the soundings, scoring the drill targets, analysing the pumping tests,
assessing the water quality, designing the borehole on the Depth Spine,
costing the works, running the supervision checklists, comparing a
whole portfolio of boreholes, reading a scanned field sheet and writing
the seven .docx reports. Uploaded sheets are parsed in the page and
never leave the machine. Its engine is held to the Python package's own
numbers by a parity check in CI, on the real sample workbooks. Source
lives in `docs/`.

Every page the Streamlit app has, the standalone app has. One works
differently rather than less: the AI-assisted reading of a photographed
sheet needs an Anthropic API key, which the server holds in its secrets
and the browser asks the operator for on the Settings page. It is kept
out of saved project files, so sharing a project never shares the key.

Two features reach the network, and both are a button rather than
something a page does on its own: the live Water Point Data Exchange
lookup (which always has an offline CSV path beside it) and the AI
extraction. Everything else works with the cable pulled out.

That is meant literally. The standalone app registers a service worker
that keeps the whole app — page, stylesheet, engine, sample projects
and data tables — on the device after one visit, and ships a web app
manifest, so it installs from the browser and opens full screen with no
network at all. The Water Point Data Exchange and the Anthropic API are
never intercepted and never cached: a water point inventory read back
off disk would be indistinguishable from a live one, and a request
carrying an API key does not belong in a cache. Both apps are also
honest about when the local copy stops being written: if the browser's
storage fills up, autosave says so and asks for a project file rather
than failing quietly.

The Streamlit app is the complete server version. The WebAssembly build
is that same Python app compiled to run in the browser through
stlite/Pyodide — behaviourally identical to the server version, at the
cost of a 60 MB first load.

All three bundle every sample dataset, so every page works with one
click. Hosting setup lives in `DEPLOY.md`; the Pages site goes live
after the one-time Pages setting described there (Source: deploy from a
branch, `main`, folder `/docs`).

## Installation

```bash
pip install -e .            # core toolkit
pip install -e .[gis]       # + GeoPackage export (geopandas)
pip install -e .[app]       # + Streamlit web interface
pip install -e .[extract]   # + PDF text extraction (pdfplumber)
pip install -e .[ai]        # + AI-assisted scan extraction (anthropic)
pip install -e .[dev]       # + pytest
```

## Quick start

Build the bundled sample datasets (transcribed from real survey and
completion reports) and run the end to end examples:

```bash
python examples/build_sample_data.py
python examples/run_rokel_geophysics.py      # VES survey -> geophysical report
python examples/run_kuntolo_step_test.py     # step test with pending discharge
python examples/run_dr_timbo_completion.py   # drilling -> design, completion,
                                             # water quality, handover reports
```

Each example writes into `examples/projects/<name>/` using the fixed
project layout:

```
<project>/
    project.yaml     site metadata and configuration overrides
    raw/             field data exactly as received
    processed/       parsed and derived tables (CSV)
    figures/         all generated figures (PNG)
    reports/         generated .docx reports
```

Re-running on the same raw data produces byte-identical outputs.

## Web interface

```bash
pip install -e .[app]
streamlit run app/streamlit_app.py
```

The field team can upload template files, review the automatic data
checks, supply missing values (for example step discharges), and
download figures and reports without touching code.

## Package layout

```
groundwater/
    ingestion/    Excel/CSV templates, parsers, metadata consistency checks
    ves/          geometric factors, 1D forward model + inversion, IPI2Win
                  import, curve classification, hydrogeological interpretation
    hydraulics/   Cooper-Jacob, Theis, recovery, Hantush-Bierschenk,
                  specific capacity, safe yield, pump setting depth
    quality/      WHO/national standards comparison, ionic balance,
                  Piper and Stiff diagrams
    design/       construction design rules and to-scale schematics
    costing/      RWSN cost model: rate catalogue, BoQ, enterprise
                  calculators (depreciation, wear, loans), Excel export
    supervision/  stage checklists, separation distances and numeric
                  field acceptance checks
    mapping/      site maps, iso-resistivity and overburden maps, GIS export
    reporting/    house-styled .docx builders for the seven report types
    extraction/   scanned sheet extraction with review flagging
```

## Reference library

The methods for costing and supervision are grounded in the RWSN,
Skat and UNICEF publications collected in `WaterProjectFiles/`:
the Borehole Costing Model and quick start guide, "Costing and
Pricing: a Guide for Water Well Drilling Enterprises", "Procurement
and Contract Management of Drilled Well Construction", "Professional
Water Well Drilling", "Supervising Water Well Drilling", the UNICEF
"Borehole Drilling - Planning, Contracting and Management" toolkit
and the WASH Funders infrastructure checklists, plus the Geology of
Sierra Leone map (Ministry of Water Resources/SALWACO 2017) and the
BGS Africa Groundwater Atlas hydrogeology shapefile (CC BY-SA 4.0)
that grounds the aquifer maps. Checklist items, separation distances
and unit rates live in editable CSVs under `src/groundwater/data/`,
so field practice can be adapted without code changes;
`web/build_geodata.py` documents how the bundled map layers are
derived from their sources, and `web/build_webapp_data.py` re-emits
those same tables into the standalone web app so the two can never
disagree. `web/build_icons.mjs` rasterises `docs/icon.svg` into the
sizes the web app manifest needs, using the same headless Chromium the
browser tests run in.

Key behaviours built in from the real field sheets:

- numbers with leading zeros (`078.7`, GPS `0708958`) parse cleanly
- duplicate AB/2 readings at Schlumberger MN segment changes are kept,
  with optional curve splicing
- the recorded drawdown column (increment between readings) is never
  used; true drawdown is recomputed as water level minus static level
- missing discharge does not block parsing: curves, stabilised level
  and available drawdown are produced and yield results are marked
  pending until the discharge is supplied
- metadata consistency checks flag copy-over errors (district that
  does not contain the GPS coordinates, differing client or community
  between sheets of one project)

## Configuration

House style (colours, fonts, organisation, logo), VES interpretation
thresholds, pumping test safety factors and borehole design rules live
in `groundwater/config.py` and can be overridden per project by a
`config.yaml` in the project folder. The WHO/national standards table
is an editable CSV (`groundwater/data/who_guidelines.csv`).

Its `sl_source` column records where each national value came from.
Every one of them currently reads `provisional`: they are WHO guideline
figures carried across, or limits taken from regional practice, and
have not been checked against the Sierra Leone Standards Bureau
drinking water specification. Both apps and the water quality report
say so wherever a national verdict is shown, because failing an
unconfirmed limit is a prompt to check the specification, not a
compliance finding to put in front of a regulator. Confirm a figure,
set `sl_source` to the issuing specification, and the warning drops
away for that parameter — no code change needed.

## Tests and docs

```bash
python -m pytest             # parsers, numerics, reports

# the standalone web app, in a real browser
npm install --no-save playwright && npx playwright install chromium
node tests/webapp/parity.mjs                    # browser engine vs this package
node tests/webapp/smoke.mjs                     # every page and every report
python tests/webapp/make_reference.py --check   # the reference values are current
```

The VES forward model is validated against analytic two-layer image
series solutions (agreement better than 0.5 percent); the pumping test
methods recover synthetic aquifer parameters exactly. See
`docs/user_guide.md` for the field team guide and
`QUESTIONS.md` for open items that need project data or decisions.

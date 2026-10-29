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
2. Maps of the study area at four scales, and a section through the
   ground beneath it: the study area itself with a national locator
   inset; the regional geological and aquifer settings; the terrain,
   worked out from an elevation model the operator supplies because none
   is bundled and none is downloaded - both apps read GeoTIFF and `.hgt`
   tiles such as Copernicus GLO-30 and SRTM, several joined into one
   model and read a window at a time without GDAL, and analyse the
   ground around the site into drainage lines with Strahler order, a
   wetness index, curvature and the relief lit from four directions,
   every figure carrying inside the image the reminder that these are
   candidates to check on the ground, and the drainage lines
   downloadable as GeoJSON (the Python app also reads one ESRI ASCII or
   XYZ grid, and draws a topographic map with hillshade and contours
   over the wider map window); and the survey's own subsurface - depth
   to bedrock, aquifer thickness, bedrock surface elevation, aquifer
   protective capacity, iso-resistivity at a measured electrode spacing,
   the interpreted geoelectric section at the soundings' surveyed
   spacing and the apparent-resistivity pseudo-section, which is the
   readings themselves before any inversion has been believed. Plus GIS
   layers, and each continuous surface and the drill-target score
   written as a georeferenced GeoTIFF beside its picture, so it can be
   sampled, contoured or laid under imagery in any GIS rather than only
   looked at (the Python app; the browser app draws the surfaces only as
   pictures). A surface gets a raster only where the soundings enclose
   ground to clip it to and none of them is a lower bound; otherwise it
   stays a picture, as the protective-capacity map, drawn in classes,
   always does
3. To-scale borehole design drawings with lithology and construction columns,
   and a rising main chosen from the water: where the sample's corrosivity
   indices or its pH say the water is aggressive, the design specifies a
   stainless steel rising main in place of galvanised iron, inspected every
   6 months rather than 12, says why from the sample's index values, and the
   bill of quantities prices it (at a placeholder rate). With no sample the
   design says the choice rests on no chemistry. The intervals and the rate
   are choices waiting on `QUESTIONS.md` item 13
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
   embedded automatically into the survey and handover reports. The
   geological key names the rock rather than its age: the USGS layer
   carries seven classes for the whole country, one of which dates the
   Freetown peninsula wrong, so a bundled crosswalk gives each the
   formation and lithology the Geology of Sierra Leone map (MoWR/SALWACO
   2017, 1:600,000) maps there - the Freetown Layered Complex, the Bullom
   Group - and what that rock means for a borehole. It annotates rather
   than reclassifies: the polygon is still the 1:5,000,000 one, and where
   the two sources disagree the figure says both
10. Thirteen documents: geophysical survey, borehole completion, pumping
    test, water quality, project handover, cost estimate, supervision
    checklist record, interim payment certificate, borehole asset record,
    the laminated identification plate for the headworks, the desk
    study, put together before anyone travels to the site and stamped as a
    pre-field document, the calibration report, which scores a
    portfolio's recorded forecasts against what was drilled, and the
    contractor scorecards, which set each drilling contractor's boreholes
    out across a portfolio: metres claimed against the signed logs, failed
    acceptance checks, variation orders, time against the contract and dry
    holes against the forecast, each with the number of boreholes it rests
    on, and a ranking only on five forecast boreholes or more. Every one of
    the site's reports opens on a map of the area; the plate is a single
    laminated sheet and carries the asset QR code instead, and the
    calibration report and the scorecards, which cover many sites, carry
    neither. The web app saves and reloads the whole working state as a
    project file
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
13. A certification-readiness gate on every document that has a cover to
    stamp (all but the identification plate, which is a single laminated
    sheet): each is judged
    on the evidence it actually claims, and one built on missing evidence
    is stamped PROVISIONAL - NOT FOR CERTIFICATION on its own cover with
    the outstanding items listed. It judges completeness, not outcome - a
    borehole whose water fails a health guideline is perfectly certifiable;
    one whose result could not be read is not. An interim document can be
    issued on a recorded override naming who issued it and why, which makes
    it issuable and never certifiable
14. A planning view over the coverage gap, because both halves of "people
    per functional water point" are older than the phrase suggests: the
    2015 census is projected to a year the user picks at a rate they can
    set (defaulting to the rate implied by the 2004 and 2015 census totals,
    and saying plainly that a uniform rate cannot reorder the ranking - only
    district rates do that); the age of the survey behind each point is
    measured, with coverage over recent surveys reported beside coverage
    over all of them so the gap between them is the size of the assumption
    (a survey dated after the year planned for says nothing about it, and
    is left out of both the age and the recent count);
    and dry-season service is a band rather than a number, because most
    surveys never recorded how many months of the year a source yields water
    and silence is not a year-round supply
15. A seasonal sustainable-yield model: a pumping test measures one day,
    so the tested water level is placed in the annual cycle and the yield
    reported at three levels - as tested, at the normal end-of-dry-season
    low, and in a drought year - with the pump intake set deep enough for
    the worst of them. A date that could be read either way round (10/05 is
    10 May or 5 October, opposite ends of the year) is treated as no date:
    the whole annual range is reserved and the report says why
16. Procurement tracking over the bill of quantities: the estimate is
    frozen into a contract when it is awarded, work measured is kept
    separate from work authorised so only the lower one is paid, variation
    orders record who authorised the difference and why - an order nobody
    signed is left out of the valuation rather than valued with a warning
    beside it - and the interim payment certificate shows every deduction
    between the value of the work and the figure at the bottom. Work done
    but not authorised is named and withheld rather than quietly paid or
    quietly dropped, a later
    certificate that forgets what earlier ones paid is challenged, and a
    certificate that would pay less than nothing pays nothing and says by
    how much the job is overpaid
17. A borehole asset registry for the second twenty years: an identifier
    derived from the position (so two teams at the same wellhead with no
    connection between them arrive at the same one) and closed by an ISO
    7064 MOD 37,36 check character (identifiers minted before that
    character was corrected are still read, with a note saying so), a
    printable headworks plate carrying a QR symbol generated offline, an
    append-only maintenance history that merges by content when two phones
    meet, and
    derived condition and overdue dates. Nothing is assumed working - a
    borehole nobody has reported on is unknown, not functional, and the
    functionality rate is only ever computed over the points whose
    condition is actually known. A sanitary inspection is recorded there
    on WHO's ten-question form for a borehole with a handpump and read
    with the E. coli count of the latest water sample into one risk
    statement with its action priority, naming both dates. A question left
    unanswered is not a no, so an incomplete form gives a range; a side
    that is not known is said to be unknown and gives no priority. The
    form's wording and the matrix's cells, which are a choice made here,
    are listed in `QUESTIONS.md` for checking. The registry schedules three
    visits: the sanitary inspection, a routine inspection of the pump and
    rising main at the interval the design sets for the rising main, and
    the water quality sample, every interval a setting in
    `data/defaults.json`. Service rounds group what is due on a day across
    the register by area mechanic (named on the borehole's record, else for
    its chiefdom), order each round by a stated nearest-neighbour walk that
    is not an optimal route, and print a round sheet with boxes for the
    readings. Across the register, the time from commissioning to the
    first failure is estimated by Kaplan and Meier's method, overall and
    by pump type, contractor and water corrosivity, as a step curve with
    its 95 percent band and a table of the median and the numbers at risk
    on a day that is an input. A borehole that has not failed counts as
    working only up to the last report of it working; a group of fewer
    than five boreholes followed says it is too few to judge and shows no
    curve; and groups are compared by the log-rank test, with its p-value
    said to be what it is. A plate printed with the programme's report
    address carries a link to the browser app's report page for its
    borehole, which works with no network on a phone that has opened the
    app: working, broken, slow, or bad taste or colour, with an optional
    photograph, kept on the phone until the borehole's record is opened
    there or carried to it as a small file. A feature phone reports by
    SMS (`BH <identifier> BROKEN`), and both apps import a file of
    messages, refusing a mistyped identifier by its check character and a
    message whose day cannot be told, and holding for a person one that
    the registry reads only with a note. No SMS gateway is needed; a
    programme that runs one hands its messages to
    `fault_reports.receive_messages`
18. The survey as an interactive map, not only as a picture: both apps
    write a [GeoLibre](https://geolibre.app) project file - an open,
    plain-JSON map format - carrying the site, the scored drill targets,
    any water points found nearby and the geology, aquifer and chiefdom
    layers around it, styled, framed and with each layer's attribution
    inside it. It opens in GeoLibre's web, desktop and phone apps and in
    a Jupyter notebook, where it can be panned, clicked and put over
    satellite imagery. Building it needs nothing new: the format is JSON,
    the geometry is the GeoJSON already exported, and the file is
    assembled offline. It opens on a blank background rather than a
    basemap, because switching one on is a request to the network and
    that is the operator's decision to make

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
the .docx documents. Uploaded sheets are parsed in the page and
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
pip install -e .[dev]       # + pytest, ruff, nox and the test-only oracles
```

A tagged release (from 0.3.0 on) attaches the wheel, the sdist and the
example packs to its GitHub Release, so a version can be installed
without a checkout:

```bash
pip install groundwater-toolkit==0.3.0 --find-links \
  https://github.com/moseskolleh/WaterProject/releases/expanded_assets/v0.3.0
```

`nox -s check` runs everything CI runs; see `CONTRIBUTING.md`.

## Quick start

Build the bundled sample datasets (transcribed from real survey and
completion reports) and run the end to end examples:

```bash
python examples/build_sample_data.py
python examples/run_rokel_geophysics.py      # VES survey -> geophysical report
python examples/run_kuntolo_step_test.py     # step test with pending discharge
python examples/run_dr_timbo_completion.py   # drilling -> design, completion,
                                             # water quality, handover reports
python examples/build_catalogue.py           # index them, and pack each case up
```

`examples/CATALOGUE.md` is what that last command writes: what went into
each case, counted by the readers themselves, and what each report says
on its own cover. Two of the three cases publish stamped reports, because
their sheets are missing something real - a GPS fix, the discharges - and
an example that papered over that would be advertising something the
toolkit does not do.

Each example writes into `examples/projects/<name>/` using the fixed
project layout:

```
<project>/
    project.yaml     site metadata
    config.yaml      optional configuration overrides
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

## Command line

For batch work without either app - forty saved projects to re-run after
a standards-table update, a programme table to build, templates to hand
out - the same library calls are on the command line:

```bash
groundwater recompute project.yaml --json summary.json   # rebuild a saved project's analyses
groundwater portfolio *.yaml --csv programme.csv --map programme.png
groundwater templates ./templates                        # the five field templates
groundwater extract field_sheet.pdf --out ./review       # a text-layer PDF into a review workbook
```

`recompute` prints one line per saved source and exits non-zero when one
could not be rebuilt, so a shell loop over a folder of project files
stops on the file that needs attention. `extract` writes the review
workbook, and the filled VES template when the sheet's reading table can
go into one (it says why when it cannot), and prints how many items the
review lists; a scanned PDF with no text layer is refused with a pointer
to the AI extraction. `python -m groundwater` is the same thing.

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
    mapping/      site maps, iso-resistivity and overburden maps, GIS export,
                  GeoLibre project files, elevation models read a window
                  at a time (elevation.py) and the terrain analysis
                  worked out from them (terrain_analysis.py)
    reporting/    house-styled .docx builders, one per document
    extraction/   scanned sheet extraction with review flagging
    readiness.py  the certification gate: per-report requirements, overrides
    seasonal.py   the tested day placed in the year: dry-season and drought
                  yields, and the pump depth the worst of them needs
    planning.py   coverage as a planning figure: population projection,
                  survey freshness, dry-season service as a band
    procurement.py  contract, variation orders, measurement and the interim
                  payment certificate
    registry.py   asset identifiers, maintenance events, derived condition
    rounds.py     service rounds: what is due on a day, by area mechanic,
                  in the order of a nearest-neighbour walk
    sanitary.py   the sanitary inspection form, scored and read with the
                  E. coli count into one risk statement
    fault_reports.py  reports from the plate's report page and by SMS,
                  each accepted, held for a person or refused, and merged
                  into the registry by content
    qr.py         a dependency-free QR encoder for the headworks plate
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
- elapsed times written as clocks (`1:30`, or a cell Excel shows as a
  time) are read as the hours and minutes they show; a recovery written
  in blocks is joined, and one written on the test's own clock is moved
  back to the stop; a time of day is refused rather than guessed at
- the length of each step is read in its unit (`1 hr`), and the casing
  and riser diameters a sheet records set its casing-storage period
- a unit written in a laboratory result cell (`0.05 mg/L`) or in the
  result column's header (`Result (ug/L)`) is read; nitrate and nitrite
  reported as nitrogen (`Nitrate (NO3-N)`) are held to the guideline for
  nitrogen, and calcium or magnesium `as CaCO3` is put on the element's
  scale before the charge balance and the corrosivity indices use it
- metadata consistency checks flag copy-over errors (district that
  does not contain the GPS coordinates, differing client or community
  between sheets of one project)

## Configuration

House style (colours, fonts, organisation, logo), VES interpretation
thresholds, pumping test safety factors and borehole design rules live
in `groundwater/config.py` and can be overridden per project by a
`config.yaml` in the project folder. The WHO/national standards table
is an editable CSV (`groundwater/data/who_guidelines.csv`).

A calibration set (PLAN.md step 5.3) fitted to a programme's drilled
boreholes and adopted by a named person is put in force on either app's
Portfolio page, which fits it to the pooled project files, sets it
beside the set in force for review and saves it as `calibration.yaml`.
Outside the apps it is put in force by naming its file in the same
`config.yaml`, as `calibration: calibration.yaml` beside it. It replaces
the prior of each ground it fitted, the resistivity edges of each
geology unit and the suitability weights, and every report that prints
the odds names it. A set nobody adopted is refused.

A set file holds counts, not projects (PLAN.md step 5.5): how many
boreholes on each ground and how many succeeded, each geology unit's
edges, who adopted it, and the licence (CC BY 4.0, `ledger.set_licence`),
organisation and contact it was issued under; no project, client, place,
position or borehole name. So organisations can pass their sets to each
other, and the Portfolio page's *Pool sets from other organisations*
pools several into one (`calibration_sets.pool_sets`): each ground's
counts summed over the provisional prior counted once, each edge the
borehole-weighted geometric mean of the sets' edges, the sources
listed, and the same set, or a set and a pooled set holding it,
refused. The pooled set is adopted by a named person like any other.
The user guide says what a set file does and does not reveal.

The standards table's `sl_source` column records where each national
value came from. Every one of them currently reads `provisional`: they
are WHO guideline figures carried across, or limits taken from regional
practice, and have not been checked against the Sierra Leone Standards Bureau
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
node tests/webapp/copilot.mjs                   # the pumping test co-pilot, played back
python tests/webapp/make_reference.py --check   # the reference values are current
```

The VES forward model is validated against analytic two-layer image
series solutions (agreement better than 0.5 percent); the pumping test
methods recover synthetic aquifer parameters exactly. See
`docs/user_guide.md` for the field team guide and
`QUESTIONS.md` for open items that need project data or decisions.
`ROADMAP.md` lists the defects an audit of the worked examples found in
the maps, the designs, the interpretations and the reports, in the order
they are being fixed.

## Licence and attribution

The toolkit's source code is MIT licensed — see [`LICENSE`](LICENSE).

The bundled data is not all MIT, and one dataset is copyleft: the BGS Africa
Groundwater Atlas hydrogeology layer is CC BY-SA 4.0, and ShareAlike
propagates into `docs/js/gwt-geo.js` and `docs/wasm/index.html`, which embed
it. [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) lists every dataset and
document with its source, its licence and the attribution that licence
requires; [`data_provenance.yaml`](data_provenance.yaml) is the same record in
machine-readable form, with a SHA-256 per file so a silent substitution is
detectable.

Where a licence could not be evidenced from the material itself, both files
say **unverified — needs confirmation** rather than assuming a permissive one.
That applies to the reference documents under `WaterProjectFiles/`: they are
the sources the methods are grounded in, which is provenance, not permission
to republish.

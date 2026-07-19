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

## Try it online

- **Full app (Streamlit Community Cloud):**
  <https://waterproject.streamlit.app/>
- **Browser demo (GitHub Pages, no server):**
  <https://moseskolleh.github.io/WaterProject/>

The Streamlit app is the complete server version. The GitHub Pages
demo runs the toolkit inside the visitor's browser via WebAssembly:
uploaded files never leave the machine, the first visit downloads the
Python runtime (about 60 MB, cached afterwards), and the AI scan
extraction tab is not available there. Both bundle every sample
dataset, so every tab works with one click. Hosting setup lives in
`DEPLOY.md`; the Pages demo goes live after the one-time Pages setting
described there (Source: deploy from a branch, `main`, folder `/docs`).

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
derived from their sources.

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

## Tests and docs

```bash
python -m pytest             # parsers, numerics, reports
```

The VES forward model is validated against analytic two-layer image
series solutions (agreement better than 0.5 percent); the pumping test
methods recover synthetic aquifer parameters exactly. See
`docs/user_guide.md` for the field team guide and
`QUESTIONS.md` for open items that need project data or decisions.

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
6. Five report types: geophysical survey, borehole completion, pumping
   test, water quality and project handover

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
    mapping/      site maps, iso-resistivity and overburden maps, GIS export
    reporting/    house-styled .docx builders for the five report types
    extraction/   scanned sheet extraction with review flagging
```

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

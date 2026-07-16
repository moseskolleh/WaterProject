# Field Team User Guide

This guide covers how to record data in the standard templates, what
the automatic checks look for, and how to run the analysis through the
web interface. No programming is needed.

## 1. Getting the templates

Ask the analyst for the current template pack, or generate it from the
Templates tab of the web interface. There are four templates:

| Template | Used for |
|---|---|
| `template_ves.xlsx` | Vertical electrical sounding field data |
| `template_pumping_test.xlsx` | Step and constant discharge tests |
| `template_drilling_log.xlsx` | Drilling record and formation log |
| `template_water_quality.xlsx` | Laboratory results |

General rules for all templates:

- Work in metres, minutes and mg/L unless the column heading says otherwise.
- Type numbers as they appear on the instrument. Leading zeros such as
  `078.7` are fine.
- Never leave the header block empty. Community, district, GPS
  coordinates (UTM), date and the responsible person matter as much as
  the readings; the checks compare them across sheets.
- Record the UTM zone (28N in the west including Freetown and Port
  Loko, 29N in the east). The system flags coordinates that do not
  match the stated district.

## 2. VES sheet

One worksheet per sounding. Fill the header block, then the readings:
reading number, AB/2 in metres, MN in metres (the full distance
between the potential electrodes, not half of it), and the apparent
resistivity from the instrument.

At every segment change (for example AB/2 = 3, 10, 40 and 70 m),
repeat the same AB/2 with the old MN and again with the new MN. Both
readings are used; do not delete either one.

## 3. Pumping test sheet

Fill the header block including the static water level measured before
the pump started, the pump setting depth and the borehole depth. Write
`step` or `constant` in the test type cell.

- Record depth to water in metres below the measuring point at each
  time. The `Drawdown` column is the change since the previous reading,
  exactly as on the paper sheets; the analysis does not use it and
  recomputes drawdown from the static level, so small arithmetic slips
  there do not matter.
- Reading times do not need to be evenly spaced. Record the actual
  minute of each reading.
- The four column groups cover hours one to four. For a step test each
  group is one step; for a constant test they continue one series.
- The recovery block has its own time column: minutes since the pump
  stopped.
- **Record the discharge of every step** in the discharge row (bucket
  and stopwatch: litres divided by seconds, times 3.6 gives m3/h).
  Without discharge the system still draws the curves but reports
  transmissivity and yield as pending.

## 4. Drilling log

One row per drilled interval (`0-5`, `5-10`, ...). Describe the sample
from the cuttings in plain words (colour, grain, weathering, clay
content); note fracture zones and write the depth of every water
strike in the water strike column. The design module places screens
against these depths, so accuracy here directly shapes the borehole
design.

## 5. Water quality sheet

Enter the laboratory certificate values against the pre-printed
parameter list. For results below the detection limit write `<` and
the limit (for example `<0.01`) in the value column. Add extra
parameters on new rows with their units.

## 6. Running the analysis (web interface)

1. Open the toolkit in the browser (the analyst provides the address,
   or run `streamlit run app/streamlit_app.py`).
2. Pick the tab for your data type and upload the filled template.
3. Read the messages: green is parsed, blue is information, amber
   needs review, red blocks the analysis. Typical amber messages are a
   missing discharge, a water level above the stated static level, or
   a district that does not match the GPS coordinates. Fix what you
   can in the template and upload again.
4. Supply anything the sheet was missing (the pumping tab asks for
   step discharges).
5. Download the figures and the report.

## 7. Costing tab

Enter the planned depth, the overburden thickness if known and the
one way distance from the contractor's base to the site, then press
"Estimate cost". The estimate follows the RWSN Cost-Effective
Boreholes method: line items roll up by construction stage and by
resource category, the contractor's cost is kept apart from the
contract price, and every rule of thumb applied is listed under
"Assumptions applied".

- The bundled unit rates are indicative. Open "Unit rate catalogue"
  and type the current local prices before using an estimate for real
  budgeting or contracting.
- If a design was produced in the Borehole design tab, switch on "Use
  the design" and the casing, screen and gravel quantities carry over
  automatically.
- Download the bill of quantities (`.xlsx`, with live formulas the
  contractor can edit) or the full cost estimate report (`.docx`).

## 8. Supervision tab

The checklists follow the RWSN/UNICEF supervision guidance, stage by
stage from procurement to post-construction monitoring. Answer each
item Yes, No or N/A as the works proceed; items marked *critical*
stop acceptance while they are open or failed. The tab also carries
the field acceptance calculators (chlorine disinfection dose, sand
content, verticality, specific capacity) and the minimum separation
distances from pollution sources. When a stage is complete, download
the signed checklist record from "Checklist record and sign off".

## 9. Scanned sheets

Photograph or scan the paper sheet squarely under good light and
upload it in the Scanned sheets tab. The extractor transcribes the
header and the tables and highlights every value it is not sure about
in amber in the review workbook. Check each highlighted cell against
the paper before the data is used; nothing is accepted silently.

## 10. Where results go

Each project has one folder with a fixed layout: `raw` (your files,
never modified), `processed` (parsed tables), `figures` and
`reports`. Keep the raw files; re-running the analysis on them always
gives the same outputs.

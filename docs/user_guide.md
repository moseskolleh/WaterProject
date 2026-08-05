# Field Team User Guide

This guide covers how to record data in the standard templates, what
the automatic checks look for, and how to run the analysis through the
web interface. No programming is needed.

## 1. Getting the templates

Ask the analyst for the current template pack, or generate it from the
**Templates** page of the web interface (sidebar, under *Delivery*).
There are four templates:

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

## 5a. Finding your way around

The web interface is one workspace with a sidebar. The sidebar holds
the **site details** (community, area, GPS - filled in once, used by
every page and every report), the **project file** panel for saving
and loading, and the page list grouped by where you are in the job:

| Group | Pages |
|---|---|
| Project | Overview, Guided start, Site maps |
| Investigation | Geophysics (VES), Borehole design, Depth Spine, Scanned sheets |
| Testing | Pumping test, Water quality |
| Delivery | Costing & BoQ, Supervision, Handover, Templates |
| Area analysis | Water points, Coverage gap, Portfolio |

The same pages are in the standalone browser app, which needs no
install and no Python; it keeps the project in the browser and saves it
as a `.gwt.json` file rather than a `.yaml` one. Either app can read
the other's saved projects on the Portfolio page.

**Overview** opens first and is the project dashboard: the lifecycle
strip across the top shows how far the borehole has got (Sited →
Drilled → Tested → Assessed → Handover), and the cards below summarise
whatever has been produced so far.

## 5b. Guided start (new projects)

**Guided start** walks a new project through the core sequence in
three steps: fill the site details (the wizard checks them off as the
sidebar panel is completed), run the siting analysis on the VES
workbook (the best ranked sounding sets the drilling depth, or a
planned depth can be entered directly), and produce the first cost
estimate from that depth. Every result carries over to the full pages
for fine tuning, and the final step lists what to do during and after
drilling.

## 6. Running the analysis (web interface)

1. Open the toolkit in the browser (the analyst provides the address,
   or run `streamlit run app/streamlit_app.py`).
2. Pick the page for your data type from the sidebar and upload the
   filled template. Every page also offers the bundled sample files,
   so you can try a step before your own data arrives.
3. Read the messages: green is parsed, blue is information, amber
   needs review, red blocks the analysis. Typical amber messages are a
   missing discharge, a water level above the stated static level, or
   a district that does not match the GPS coordinates. Fix what you
   can in the template and upload again.
4. Supply anything the sheet was missing (the pumping test page asks
   for step discharges).
5. Download the figures and the report.

## 7. Costing & BoQ

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
- If a design was produced in the Borehole design page, switch on "Use
  the design" and the casing, screen and gravel quantities carry over
  automatically.
- Download the bill of quantities (`.xlsx`, with live formulas the
  contractor can edit) or the full cost estimate report (`.docx`).

## 8. Supervision

The checklists follow the RWSN/UNICEF supervision guidance, stage by
stage from procurement to post-construction monitoring. Answer each
item Yes, No or N/A as the works proceed; items marked *critical*
stop acceptance while they are open or failed. The page also carries
the field acceptance calculators (chlorine disinfection dose, sand
content, verticality, specific capacity) and the minimum separation
distances from pollution sources. When a stage is complete, download
the signed checklist record from "Checklist record and sign off".

## 8a. Depth Spine

The whole borehole on one depth axis: the cuttings log, the casing
string and the water levels drawn against the same ruler, so the
alignment between them is true rather than eyeballed. It opens once a
drilling log is loaded.

The screened intervals are the only editable thing on the section.
Drag a screen or one of its handles - or focus a handle and use the
arrow keys, 0.1 m a press and 1 m with Shift - and the toolkit re-runs
the design around it: the casing string, the annulus, the acceptance
checks and the bill of quantities all come back recomputed. A screen
moved here is a screen moved everywhere, including on the Borehole
design page and in the completion report.

Three stages carry one professional opinion each - the design, the
water quality verdict and the price to the client. Accepting is one
press; overriding costs a value and a written reason, because the
override is what ends up in front of the client with a name on it.
Moving a screen clears the design and costing signatures, since a
signature has to belong to the numbers that were in front of the
person at the time.

## 9. Handover

The closing report for the client and the community. Fill the site
details in the sidebar once (they feed every page), then answer the
handover questions: the pump installed, the tariff agreed, the WASH
committee members (add rows as needed), any extra works or
recommendations, and the three signatories. Results already produced
on the other pages - the borehole design, the pumping test and the
water quality verdict - attach to the report automatically; the page
shows what is attached before you build it.

## 10. Site maps

Generates report-ready context maps from the sidebar site details:
an administrative location map (districts, with yours highlighted),
the geological setting (USGS Geologic Map of Africa) and the aquifer
type and productivity map (BGS Africa Groundwater Atlas), nationally
or zoomed to the site. Enter the UTM coordinates in the sidebar to
place the site star. Every figure carries its data attribution, and
the same maps embed automatically into the geophysical survey and
handover reports when the site has coordinates.

## 10a. Area analysis: where to drill, and whether to drill at all

Three pages answer the questions that come *before* a borehole is
sited, using open national datasets rather than your own files.

**Water points** - before drilling at a site, check what is already
there. Set the GPS, choose a search radius, and press *Look up water
points*: the page queries the Water Point Data Exchange (WPdx+) for
mapped sources around the site. It returns one of three
recommendations: a broken improved source nearby is a **rehabilitation
candidate** (usually far cheaper than a new borehole), a working source
inside the service radius means the community **may already be served**
and the need should be verified, and otherwise **new construction is
justified**. The lookup needs a connection; if there is none, download
your country's WPdx export once and upload the CSV instead - the
analysis is identical and runs offline.

**Coverage gap** - where are the underserved people? Ranks districts,
or chiefdoms for finer targeting, by population per functional water
point (2015 census populations joined to WPDx points), as a choropleth
map and a ranked table. Higher means more people per working source
means higher priority.

**Portfolio** - upload several saved project files at once for the
programme view: a status map, headline figures (success rate, mean cost
per metre), a comparison table and a one-page brief for any single
site. Files saved by either app are accepted, so a programme run across
both still pools into one view.

## 11. Saving your work

Everything you enter (site details, checklist answers, costing
inputs, edited unit rates) lives only in the browser session and is
lost on refresh. Use the sidebar's "Project file" panel to save the
whole working state as a small `.yaml` file, and load it back later
or on another machine to continue where you stopped.

## 12. Scanned sheets

There are two paths, and which one you need depends on the file.

A **PDF that was typed** - printed from a computer rather than
photographed - carries a text layer, and *Read a text PDF* pulls the
header and the reading table straight out of it. Nothing is uploaded
anywhere.

A **photograph or an image-only scan** has no text to read, and goes
to the AI extractor instead. Photograph or scan the paper sheet
squarely under good light. In the browser app this needs an Anthropic
API key, set once on the Settings page; in the Streamlit app the
analyst configures it in the app's secrets.

Either way the extractor transcribes the header and the tables and
highlights every value it is not sure about in amber in the review
workbook. Check each highlighted cell against the paper before the
data is used; nothing is accepted silently, and extraction never
writes into the project on its own - correct the workbook, then upload
the corrected sheet on the page that needs it.

## 13. Where results go

Each project has one folder with a fixed layout: `raw` (your files,
never modified), `processed` (parsed tables), `figures` and
`reports`. Keep the raw files; re-running the analysis on them always
gives the same outputs.

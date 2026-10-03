# Field Team User Guide

This guide covers how to record data in the standard templates, what
the automatic checks look for, and how to run the analysis through the
web interface. No programming is needed.

## 1. Getting the templates

Ask the analyst for the current template pack, or generate it from the
**Templates** page of the web interface (sidebar, under *Delivery*;
in the browser app its address is [`#/templates`](index.html#/templates)).
There are five templates:

| Template | Used for |
|---|---|
| `template_ves.xlsx` | Vertical electrical sounding field data |
| `template_pumping_test.xlsx` | Step and constant discharge tests |
| `template_drilling_log.xlsx` | Drilling record and formation log |
| `template_daily_drilling_report.xlsx` | The driller's daily report, one row per interval |
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

## 2a. VES co-pilot (browser app, at the peg)

The browser app has a page that checks a Schlumberger sounding as it is
taken: **VES co-pilot**, under *Investigation*, at
[`#/vescopilot`](index.html#/vescopilot). It is in the browser app only;
the Streamlit app's Geophysics page says so, and reads the workbook the
co-pilot writes like any other. It works with no network once the app is
installed.

**Before the survey.** Enter the target depth and press *Propose the
spacings*. A Schlumberger sounding resolves to about half of its largest
AB/2, the same rule the interpretation and the drilling depth use, so a
50 m target needs AB/2 = 100 m: 200 m of straight, open ground centred
on the peg. Check that the ground is there before anyone unrolls a
cable. The proposal runs 1, 1.5, 2, 3, 4, 5, 6, 8, 10 m and on, with MN
never more than a fifth of AB, and changes MN when AB passes twenty
times it; at each change the plan lists the same AB/2 twice, once with
each MN. The plan is a text box, one `AB/2 MN` pair a line: edit it to
suit the ground (or to match a paper sheet already in use) and press
*Use this plan*.

**At each reading.** The form is filled in with the next spacing on the
plan. Enter the potential V in millivolts and the current I in
milliamps, or the apparent resistivity if the instrument shows it, and
press *Add the reading*. The resistivity is worked out with the exact
Schlumberger geometric factor the parsers use, and the point goes on the
log-log curve at once. Four things are checked at the peg:

- **A rise steeper than 45 degrees.** Over layered ground the curve can
  climb no faster than one decade of resistivity per decade of AB/2.
  Over a resistive basement it climbs at very nearly that, so a reading
  is called out only when it sits more than 10 percent above the
  45-degree line from the reading before it at the same MN: room for the
  finite MN and a good reading's scatter. Steeper than that is a misread
  potential, a peg in the wrong place, a current electrode with no
  contact, or ground that is not layered.
- **An MN change whose two readings disagree by more than 20 percent**,
  the same test and threshold the Geophysics page applies to an uploaded
  sheet. Re-read both before the current electrodes move.
- **A potential too small to read reliably.** The default is 1 mV; set
  your instrument's figure under *Instrument*. Raise the current (water
  the current electrodes), or widen MN and read the spacing at both MN.
- **A spacing skipped or read twice**, against the plan.

The first three say **Re-measure now**; press *Re-measure this reading*
and the new reading takes the old one's place. The table keeps what each
reading raised.

**Preview inversion.** From the eighth reading the app fits a layered
model to the readings so far, in the background, and draws it on the
curve. It says whether basement is in view within the depth the line
resolves so far, so the team can extend the line while it is still
laid out. It is a preview, refitted after each reading; *Stop the
preview* stops it, and so does leaving the page. A copy of the app
opened straight from a file (`file://`) has no background worker, and
the fit would hold the page for some seconds after every reading, so
there it runs only when *Run the preview now* is pressed. The finished
workbook is interpreted on the Geophysics page.

**The workbook.** *Take the GPS position* (at the centre peg; the
browser asks permission the first time) and *Download the workbook*. It
is the standard VES template, with the site details from the Site page,
the device clock and GPS fix in the header, the position also written as
UTM, and V, I and the time of each reading beside the resistivity.
Upload it on the Geophysics page. The readings are saved in the browser
with the project a moment after each one is added, so a reload or a
closed tab does not lose them, and opening another project or a sample
keeps them. *Start a new sounding* clears them, and so does *Reset
everything* on the Settings page, so download the workbook first.

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
the limit (for example `<0.01`) in the value column; the words a
certificate uses for the same thing (`Absent`, `ND`, `Not detected`)
are read too. For E. coli and total coliforms, `<1` or `Absent` means
not detected in the 100 mL sample, which is the guideline being met.
Add extra parameters on new rows with their units: the common
certificate spellings (`Iron (Fe)`, `Total alkalinity`, `Nitrate-N`,
`Colour`, `Thermotolerant coliforms`) are recognised.

Results are judged against two columns: the WHO guideline value and a
national one. **The national column is provisional.** Its values are
WHO figures carried across or limits taken from regional practice, and
have not been confirmed against the Sierra Leone Standards Bureau
drinking water specification. The apps and the water quality report say
so wherever a national verdict appears. Treat a national exceedance as
a reason to check the specification, not as a compliance finding to put
in front of a regulator. The table is an editable CSV
(`groundwater/data/who_guidelines.csv`): confirm a figure, put the
issuing specification in its `sl_source` column, and the warning drops
away for that parameter.

## 5a. Finding your way around

The web interface is one workspace with a sidebar. The sidebar holds
the **site details** (community, area, GPS - filled in once, used by
every page and every report), the **project file** panel for saving
and loading, and the page list grouped by where you are in the job:

| Group | Pages |
|---|---|
| Project | Overview, Guided start, Site maps |
| Investigation | Geophysics (VES), VES co-pilot (browser app only), Borehole design, Depth Spine, Scanned sheets |
| Testing | Pumping test, Water quality |
| Delivery | Costing & BoQ, Supervision, Handover, Templates |
| Area analysis | Water points, Coverage gap, Portfolio |

The same pages are in the standalone browser app, which needs no
install and no Python; it keeps the project in the browser and saves it
as a `.gwt.json` file rather than a `.yaml` one. Either app can read
the other's saved projects on the Portfolio page.

In the browser app every page has an address of its own: the app's
address followed by `#/` and the page, so the Geophysics page is
[`index.html#/ves`](index.html#/ves) and the pumping test page is
[`index.html#/pumping`](index.html#/pumping). The browser's back and
forward buttons move between the pages you have visited, a bookmark
opens the page it was made on, and an address can be written into a
report, an email or a QR code on a field sheet. Some pages go one step
further and name one thing on them:

| Address | Opens |
|---|---|
| [`#/overview`](index.html#/overview) | Overview |
| [`#/site`](index.html#/site) | Site & maps |
| [`#/ves`](index.html#/ves), `#/ves/VES-3` | Geophysics, at sounding VES-3 |
| [`#/vescopilot`](index.html#/vescopilot) | VES co-pilot |
| [`#/design`](index.html#/design) | Borehole design |
| [`#/pumping`](index.html#/pumping), `#/pumping/KTL-01` | Pumping test, for borehole KTL-01 |
| [`#/quality`](index.html#/quality) | Water quality |
| [`#/costing`](index.html#/costing) | Costing & BoQ |
| [`#/supervision`](index.html#/supervision) | Supervision |
| [`#/handover`](index.html#/handover) | Handover |
| [`#/registry`](index.html#/registry), `#/registry/<asset id>` | Asset registry, for that borehole |
| [`#/templates`](index.html#/templates) | Templates |

The other pages follow the same pattern (`#/guided`, `#/spine`,
`#/extract`, `#/procurement`, `#/waterpoints`, `#/coverage`,
`#/portfolio`, `#/settings`, `#/about`). An address opens the page in
whatever project the browser has open; it does not carry the project
with it. If it names a sounding or a borehole the open project does not
hold, the page says so across the top rather than showing another one
in its place. An address the app does not know opens the Overview.

The browser app installs. Open it once with a connection and it keeps
itself on the device; the Overview page then offers an **Install**
button, after which it opens full screen like any other application and
works with no network at all. Only the live water point lookup and the
AI-assisted scan reading need a connection - everything else, including
every sample project and the standards tables, is already on the
device.

The browser app also keeps a running copy of the session in the
browser's own storage (IndexedDB), so a refresh never loses fieldwork.
Each workbook and photograph is kept there once, as a file of its own,
and a change writes only the part of the session it touched, so typing
does not stutter however many photos the project holds. The Settings
page shows how much room it takes, and whether the browser has agreed
to keep it rather than clear it when the device runs short of space.
That storage is still finite. If a write fails, the app says so across
the top of the page and asks for a project file: from that point the
file you save is the only record, so save one. A browser that will not
give the app any storage at all gets the same warning as soon as the
app opens.

Only one tab saves the session. Open the app in a second tab of the
same browser and that tab opens the saved copy, says across the top
that another tab is saving the project, and saves nothing itself.
**Continue here** moves the saving to it: it opens what the other tab
saved, and the other tab stops saving and says so. A session kept by an
earlier version of the app, in the browser's older local storage, is
moved across the first time the new version opens; if you go back to an
earlier version for a while, what it saved is the copy the new version
opens when you return.

The VES inversion takes a few seconds per sounding on a laptop, and
longer on an older one; a pumping test analysis is usually quicker. In
the browser app both run in the background. A bar across the top of the
page says what is running and how far it has got, and the rest of the
app can be used meanwhile. **Cancel** on the bar stops the work at once
and keeps nothing from it: a stopped inversion leaves the Geophysics
page as it was, with a button to run it again, and a stopped pumping
analysis leaves the test loaded with an **Analyse now** button. Opened
as a file (a copy on a USB stick, say) rather than from its web
address, the app cannot run work in the background: it gives the same
results, but the page is busy while each sounding is inverted, and a
Cancel press is only read between soundings.

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

In the browser app: [`#/costing`](index.html#/costing).

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

In the browser app: [`#/supervision`](index.html#/supervision).

The checklists follow the RWSN/UNICEF supervision guidance, stage by
stage from procurement to post-construction monitoring. Answer each
item Yes, No or N/A as the works proceed; items marked *critical*
stop acceptance while they are open or failed. The page also carries
the field acceptance calculators (chlorine disinfection dose, sand
content, verticality, specific capacity) and the minimum separation
distances from pollution sources. When a stage is complete, download
the signed checklist record from "Checklist record and sign off".

## 8a. Depth Spine

In the browser app: [`#/spine`](index.html#/spine).

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

In the browser app: [`#/handover`](index.html#/handover).

The closing report for the client and the community. Fill the site
details in the sidebar once (they feed every page), then answer the
handover questions: the pump installed, the tariff agreed, the WASH
committee members (add rows as needed), any extra works or
recommendations, and the three signatories. Results already produced
on the other pages - the borehole design, the pumping test and the
water quality verdict - attach to the report automatically; the page
shows what is attached before you build it.

## 10. Site maps

In the browser app: [`#/site`](index.html#/site).

Four tabs, from the country down to the rock under the borehole.
Enter the UTM coordinates in the sidebar to place the site star; the
window slider sets how much ground the local maps cover. Every figure
carries its data attribution, and the study area, geological and
aquifer maps embed automatically into the geophysical survey and
handover reports.

**Study area & setting** - the study area at a scale where the
distances can be read off the scale bar, with the chiefdom boundaries
around the site, the survey points, any water points already looked
up, and a thumbnail of the country showing where in it this is. Beside
it, the administrative location map, the geological setting (USGS
Geologic Map of Africa) and the aquifer type and productivity map (BGS
Africa Groundwater Atlas). Both of those datasets are published at
1:5,000,000, so on a window smaller than 120 km across the figure says
on its own face how far a boundary on it can be trusted - the BGS user
guide's own words are that its maps are "not suitable for providing
detailed information on geology and hydrogeology at a sub-national
(e.g. catchment) scale". Zoom them for context, not for a contact.

The geological key names the rock, not its age. The USGS layer carries
seven classes for the whole country and they are ages - "Paleozoic
Igneous", "Precambrian", "Holocene" - which tell a driller nothing about
whether the ground stores water. A bundled crosswalk gives each class the
formation and lithology the *Geology of Sierra Leone* map (MoWR/SALWACO
2017, 1:600,000, 28 formations) maps there, so the key reads "Freetown
Layered Complex (Jf; USGS Pi)" and "Bullom Group (Q, Tb; USGS Qe)", and
the crosswalk says what each rock means for a borehole: the Freetown
gabbro stores nothing and yields only from fractures, the Bullom sands
yield well and are the easiest ground in the country to contaminate.

Four things about that are worth knowing before you rely on it.

It **annotates, it does not reclassify**. The polygon and its boundary
are still the 1:5,000,000 ones and are no more accurate for being better
named - which is why the key keeps the USGS code beside the formation.

Where the two sources **disagree**, the figure says so rather than
quietly picking one. The USGS layer dates the Freetown peninsula as
Paleozoic; it is the Freetown Layered Complex, Jurassic, about 193
million years old. The map states both.

Two classes are deliberately **left unnamed**, and never appear in the
key at all. "Ordovician" and "Silurian" have no vertices inside Sierra
Leone - they are the Bove Basin in Guinea, inside the bundled window only
because the clip box reaches 10.15 N - so putting a Sierra Leonean
formation on them would be naming another country's ground, and because
they are masked away when the map is drawn they are dropped from the key
rather than sending you hunting for a colour that is not there. And
"Precambrian", which covers most of the country, is named as what it
mostly is (Leonean granite) with its own row saying plainly that it is
not one rock: cross-tabbed against the BGS layer, 12 per cent of it is
the Rokel River Group, a belt through Port Loko, Kambia, Moyamba and
Tonkolili where the aquifer is fracture flow in indurated beds rather
than a weathered zone. Where that matters, read the aquifer map beside
it: the BGS layer separates the two where the USGS one does not.

**Not everything is mapped.** Two and a half per cent of the country's
land area falls in no USGS polygon at all, all of it coastal: at
1:5,000,000 the coastal units stop short of the shore, across the Bullom
shore and the Sherbro estuaries. That ground is drawn in its own tint and
the key calls it "Not mapped at this scale" - it is not sea, and it is
not a unit whose colour you have misread. The entry appears only when
unmapped ground is actually in the window, so its absence means there is
none, not that nobody checked.

**Topography** - no elevation model is bundled with this toolkit and
none is downloaded, so the topographic map is drawn from a file you
supply and names its source on the figure. Three formats are read
without GDAL: an SRTM tile (`.hgt`, free from NASA Earthdata; keep the
filename, because the file carries no header saying where on Earth it
is), an ESRI ASCII grid (`.asc`, what any GIS exports) or
longitude/latitude/elevation columns (`.xyz`, `.csv`). A GeoTIFF
converts with `gdal_translate -of AAIGrid`. You get a hypsometric
tint, hillshade, labelled contours at an interval chosen for the
relief, and your soundings as spot heights over it. Below that, the
ground profile along the traverse, which needs no elevation model at
all: it is the elevation recorded at each sounding, in order along the
line, measured at the pegs and straight between them.

**Subsurface** - maps of this site rather than of the country, every
one drawn from the soundings themselves: depth to bedrock, interpreted
aquifer thickness, the bedrock surface as a landform (a low in it is a
buried valley, which basement groundwater drains towards), aquifer
protective capacity in its standard longitudinal-conductance classes,
transverse resistance, and an iso-resistivity map at whichever
electrode spacing every sounding measured. Then two sections along the
traverse: the interpreted geoelectric section, drawn at the soundings'
surveyed spacing rather than evenly spaced, and the
apparent-resistivity pseudo-section, which involves no inversion at
all - each point is a reading at the station and spacing it was taken
with, so it is still right if the inversion is wrong. Its vertical
axis is AB/2, the electrode half-spacing, and is labelled as such
rather than converted to a depth.

Every interpolated surface is blanked outside the ground the soundings
enclose. A contour past the last peg is the interpolator continuing a
trend, and somebody will site a borehole on it. Where the soundings
sit too far off the best-fit line to read as one section, the page and
the figure both say so rather than letting the picture imply a
traverse nobody walked.

**Interactive** - the GeoLibre project file (see below).

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
inputs, edited unit rates) lives in the session you are working in.
Use the "Project file" panel to save the whole working state and load
it back later or on another machine to continue where you stopped.

The two apps differ in what survives on their own. The Streamlit app
holds its session in memory, so a refresh loses it; it saves a
`.yaml` project file. The standalone browser app mirrors the session
to the browser's IndexedDB storage as you go, so a refresh or a closed
tab comes back where you left it, and it warns you in red if that
mirror ever stops being written; it saves a `.gwt.json` project file,
the same file as before the mirror moved to IndexedDB. Either
app reads the other's file, so a project started in the field on a
phone can be finished at a desk.

A project file saved after the soundings were inverted carries their
inversions, so reopening it shows the models at once instead of
inverting the survey again. Each one is stored under a fingerprint of
the readings, the VES settings and the version of the app that computed
it: change a reading or a setting, or open the file in a newer version,
and that sounding is inverted afresh. Each app uses only the inversions
it computed itself, so a file moved from one app to the other is
inverted once on arrival.

## 12. Scanned sheets

In the browser app: [`#/extract`](index.html#/extract).

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

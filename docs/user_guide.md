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

## 1a. The field kit (for teams without a device)

A crew with no phone or tablet to run the co-pilots on takes the field
kit instead: **Field kit** on the Templates page, or on the Pumping
test page, in either app (in the browser app,
[`#/templates`](index.html#/templates)). Type the borehole identifiers,
one a line, as the sheets should print them; the boxes start with the
ones the project's sheets already name. The kit is one Word document
to print:

- **A pumping test sheet for each borehole**, pre-filled with the
  community, client, district and borehole number. It states the
  casing-storage time for the project's casing and riser at a cautious
  transmissivity of 1 m2/day, and so how long the pump must run. Its
  Time column holds the reading schedule the pumping co-pilot uses,
  for the pumping and again for the recovery. Its tables have the
  columns of `template_pumping_test.xlsx`, so a filled sheet is typed
  into the template cell for cell.
- **Three quick cards to laminate**: the pumping schedule, the VES
  spacings (AB/2, MN and the depth each reaches, as the VES co-pilot
  proposes them), and the chlorine doses for disinfecting a borehole,
  by casing diameter and water column.

Each sheet carries a QR code, and the same code printed under it, so
that a photographed sheet can be matched to its project and borehole
when it is read back. The code is one line of four fields separated by
`|`:

```
GWT-FK/1|pumping|<project>|<borehole>
```

`GWT-FK/1` is the format and its version; `pumping` is the sheet;
`<project>` is the project reference, or the project name where there
is no reference (the Streamlit app has no reference field, so there it
is the name), and is empty when neither is set; `<borehole>` is the
identifier as printed. In the last two fields each run of spaces, tabs
and line breaks becomes one space, the ends are trimmed, `%` is written
`%25` and `|` is written `%7C`. A code longer than the symbol can hold
(122 bytes at error-correction level H) is refused rather than cut
short; `groundwater/field_kit.py` has the full definition.

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

What the pumping test page and report make of the sheet, besides the
straight-line fits:

- **A diagnostic plot.** Drawdown and its derivative on log-log axes.
  The slope of the derivative names the flow regime: about 1 while the
  pump empties the casing, flat for radial flow through the aquifer,
  about 1/2 for flow along a single fracture, and a fall or a rise
  after the flat part for a recharge or a no-flow boundary. The slope
  limits are settings, printed under the plot.
- **A band on every figure that matters.** The transmissivity the yield
  rests on is given from the 10th to the 90th percentile of refits to
  the readings' own scatter, and the safe yield and the pump intake are
  given as bands too. Read the band as the least the spread can be: on
  test data it held the true value about seven times in ten, not eight.
  A yield is called sustainable only where the bottom of its band still
  covers the recommended rate at the dry-season level.
- **The early readings are used.** A test that never got past casing
  storage is fitted with the Papadopulos-Cooper solution for a
  large-diameter well, which models the water drawn from the casing.
  Its result is still marked indicative: run the test longer.

## 3a. Pumping test co-pilot (browser app, on a phone or tablet)

The browser app can sit with the crew while the test runs and fill in
the pumping test sheet for them. Open **Pumping co-pilot** (sidebar,
under *Testing*; address [`#/pumpcopilot`](index.html#/pumpcopilot)).
It exists only in the browser app; the Streamlit app says so on its
Pumping test page. Install the app on the phone and open the page once
with a network: after that it works with none.

**Before pumping.** Enter the casing and riser diameters, the hole
depth, the pump setting, the static level (read it before the pump
starts) and the planned rate. The page works out how long the water
standing in the casing controls the drawdown (Schafer's casing-storage
rule), for a cautious transmissivity range of 1 to 10 m2/day that you
can change. Until that period is over, the level tells you about the
casing, not the aquifer. The page then says when the test can stop at
the earliest: "If the pump starts now, do not stop before 13:07." A
30-minute test on a 5-inch casing in weathered basement is usually all
casing storage, which is what happened at Dr Timbo's. Press **Record GPS
position** to put the phone's position in the sheet; the phone asks for
permission first.

**While pumping.** Press **Start the pump** at the moment it starts. If
the pump was started before you opened the page, enter how many minutes
it has already run before you press it, so the readings are timed from
the real start.
The page counts down to each reading and beeps when one is due, on this
schedule: 0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40,
50, 60, 75, 90 and 120 minutes, then every 30 minutes. Type the depth
to water and press **Record level**. A reading typed from 6 seconds
before its time to a fiftieth of the time after it (6 seconds early in
the test, 2.4 minutes at two hours) is written at the scheduled minute,
as you would write it on paper; any other is written at the minute it
was actually taken. Drawdown is plotted against log time as you go, with
the casing-storage period shaded and the pump intake drawn across.

The page warns you:

- when the level reaches the pump intake (and earlier, when it is
  within 3 m of it): reduce the rate, because a pump cannot draw water
  below itself and the readings would be worthless;
- when a discharge measurement differs by more than 5 percent from the
  first one of the same step: set the valve back and measure again;
- while the test is still inside casing storage, and until the time it
  may stop. **Stop the pump** asks again if you press it early. Once
  levels are being read, the drawdown gives its own casing-storage
  period, but that period keeps growing while the level is falling, so
  the cautious figure from before pumping stands until the readings have
  passed the measured one;
- when the phone's clock is set back during the test, since every
  minute is worked out from it.

Each warning starts with how urgent it is in words (*Act now*,
*Warning* or *Note*), not only in its colour.

Once the readings are past casing storage, the page fits the same
Cooper-Jacob line the analysis will, and says how much the
transmissivity has moved over the last log cycle. "T has changed less
than 10 percent over the last log cycle. The test can stop at the
planned time" means the test has done its job. If the planned time is
earlier than the shortest test the analysis can give a yield from, the
page says so and gives the later time instead.

**Discharge.** Use the bucket and stopwatch: enter the bucket volume,
time three fillings (with the watch on the page, or type the seconds)
and press **Record this rate**; the three timings are averaged. Measure
again every hour or so, and after any change at the valve. A meter
reading can be entered instead. A step with no discharge cannot be
saved: if it really was not measured, record it as not measured and say
why. The reason is written on the sheet.

**Step tests.** Choose *Step drawdown*, give the number of steps (up to
four) and the step length, and press **Start step 2** (and so on) at the
moment the rate changes. The schedule starts again for each step.

**Recovery.** Press **Stop the pump** at the moment it stops. The
schedule starts again from that moment, and recovery readings are
minutes since the pump stopped.

**If the phone sleeps or the page is reloaded,** nothing is lost: every
reading is saved on the phone as it is taken, and the clock is the
phone's own clock, so the page reopens at the right minute and lists
any readings that fell due while it was asleep. Do not invent a missed
reading; take the next one.

**At the end,** press **Write the workbook (.xlsx)**. It is the
standard pumping test sheet (section 3), with the phone's clock at the
start and stop of pumping and the GPS position in the header, and a
second sheet logging every reading, timing and event. Upload it like
any other sheet, or press **Use it as this project's pumping test** to
analyse it at once; that also sets the project's casing and riser
diameters to the ones entered here, which the readers do not take from
the sheet. Save the project file as well (section 11).

## 4. Drilling log

One row per drilled interval (`0-5`, `5-10`, ...). Describe the sample
from the cuttings in plain words (colour, grain, weathering, clay
content); note fracture zones and write the depth of every water
strike in the water strike column. The design module places screens
against these depths, so accuracy here directly shapes the borehole
design.

## 4a. Drilling log co-pilot (browser app, at the rig)

The browser app keeps the drilling log as the hole is drilled: **Drilling
co-pilot**, under *Investigation*, at
[`#/drillcopilot`](index.html#/drillcopilot). It is in the browser app
only; the Streamlit app's Borehole design page says so, and reads the
drilling log it writes like any other. It works with no network once the
app is installed.

**Each interval.** Press *Start drilling* when the bit touches the top of
the interval. When it reaches the bottom, enter the depth, choose the
formation from the list and add a note (colour, grain, hardness), then
press *Log it and drill on*, or *Log it and stop* for a rod change of any
length, the end of the shift or a breakdown. The list is the toolkit's
own lithology classes, the ones the design and the Depth Spine read a log
by, so the formation is never a word the design reads as something else.
The note goes after the class, and a note that would make the row read as
another class is refused: "Weathered rock, sandy" would read as sand and
gravel, and saprolite logged as "Clay, soft saprolite" would read as
saprolite. A fracture zone is logged as an interval of its own: a depth
range in the note ("Fracture zone, 27-28 m") is read as a zone inside the
row, with the rest of the row as other material, and is refused. A water
strike is never written in the note: it has its own box.

**The penetration rate** is the time from *Start drilling* to the log of
the interval, on the device clock, over its length, in minutes per metre.
Rod changes inside an interval count in it; press *Log it and stop* and
*Start drilling* again to keep a long stop out. An interval cannot start
before the last one ended: if the device clock has been set back, it is
refused until the clock is right.

**A water strike** is recorded on the interval it was struck in, with its
airlift yield: a container timed filling (up to three timings; the yield
is the volume over the mean time), or the head over a 90-degree V-notch
plate, read by the Kindsvater-Shen equation. A notch head under 50 mm or
over 380 mm is outside the range the notch's coefficient holds for, and
the page says so; time a container as well. If the yield could not be
measured, say why, without naming the strike: the reason is written in
the log, where the readers would take a number in it for another strike.
It is an estimate while drilling, not a pumping test.

**Cuttings.** Each interval takes a photograph of its cuttings, laid out
beside the metre mark. It keeps the capture time, the position and the
SHA-256 of the file, as every photograph in the app does, and the depths
of its interval.

**Each day** the supervisor types their name and presses *Countersign*.
The name, the device time and a SHA-256 digest of the day's entries are
kept. A change to a day after it is signed needs a reason, and the day
then shows as *amended after signing* until it is countersigned again
(or changed back to exactly what was signed). Each interval keeps the day
it was logged on, so a log opened on a device set to another time zone
keeps its days and their countersigns.
This is a record, not a cryptographic signature: it shows a change, but
anyone with the file could change a day and its digest together.

**The sheets.** *Download the drilling log* writes the standard drilling
log template, with the rate headed in min/m, the airlift yield, the
device-clock times and each photograph's hash after its seven columns,
and sheets for the photographs and the countersigns. *Download the daily
reports* writes the driller's daily report template, a sheet a day, with
the countersign in the supervisor's signature cell; the rig operator's
cell is left for a pen. No page reads the daily report back. *Use it as
this project's drilling log* hands the log to the Borehole design page.

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

### The rising main the design specifies

Galvanised iron rising mains and rods corrode quickly in aggressive
water, and a corroded main is a common reason a handpump fails early. So
the **Rising main** card on the Borehole design page (both apps) reads
the sample on the Water quality page:

- **Aggressive water** - the corrosivity classification on the Water
  quality page counts it aggressive (a Ryznar index above 7.0, a
  Langelier index below -0.5 or an aggressive index below 10), or its pH
  is below 6.5, the limit of the supervision page's handpump corrosion
  check. The design specifies a stainless steel rising main in place of
  galvanised iron, inspected every 6 months. The card quotes the index
  values or the pH and names the sample by its identifier and date.
- **Water that is not aggressive** - galvanised iron, inspected every
  12 months, with the index values that say so.
- **No sample, or one that lacks pH, calcium or alkalinity** (and whose
  pH, if it has one, is not below 6.5) - the card says the choice rests
  on no chemistry, or on no corrosivity index. The design keeps
  galvanised iron and the 6 month interval until a sample with all three
  is analysed. Analyse one before the pump is ordered.

The choice follows the sample: load or replace the water quality sheet
and the design changes with it. The materials and both intervals are
settings (`groundwater/data/defaults.json`), and the intervals are a
choice made in this toolkit, not a standard; `QUESTIONS.md` item 12 asks
for them to be confirmed. The card reads only the one sample the project
holds, so a sample from another borehole, or from another season, is
read as this borehole's water. The completion and handover reports do
not name the rising main yet.

## 5a. Finding your way around

The web interface is one workspace with a sidebar. The sidebar holds
the **site details** (community, area, GPS - filled in once, used by
every page and every report), the **project file** panel for saving
and loading, and the page list grouped by where you are in the job:

| Group | Pages |
|---|---|
| Project | Overview, Guided start, Site maps |
| Investigation | Geophysics (VES), VES co-pilot (browser app only), Borehole design, Drilling co-pilot (browser app only), Depth Spine, Scanned sheets |
| Testing | Pumping test, Pumping co-pilot (browser app only), Water quality |
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
| [`#/site`](index.html#/site), [`#/site/terrain`](index.html#/site/terrain) | Site & maps, at its topography and terrain card |
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

Once the soundings are inverted, **Sample the range of models** on the
Geophysics page (the Streamlit app has the same button) samples the
models that fit each sounding about as well as its best fit, and says
what they agree on: "Basement between 22 and 34 m (P10 to P90); not
resolved in 30 percent of the models that fit", the thickness of the
water-bearing weathered zone, and a drilling depth read from the 90th
percentile and still cut back to the depth the sounding resolves. A grey
fan of the sampled models is drawn over the curve, and the report prints
the same sentences under each sounding's best fit, which is left as it
was. It takes a few seconds a sounding, with its own bar and Cancel; the
settings are under `ves_range` in the project's configuration, and the
error each reading is given (3 percent, plus the measured disagreement
at each MN overlap) is provisional.

Beside the drill-target suitability score, both apps' Geophysics pages
and both geophysical reports give each point **the chance of a working
borehole**: "About 61 percent (between 39 and 78) that a borehole here
yields enough for a handpump through the dry season. Provisional prior."
It is worked out in a way that can be checked on paper:

- **The prior** is a success rate for the ground under the point: the
  BGS aquifer class and the USGS geology unit there, looked up on the
  bundled maps at the point's own coordinates, or the site's if the
  point has none. The table, `success_prior.csv`, gives each class's
  yields from the BGS atlas user guide (O Dochartaigh 2021); read as
  the quartiles of a lognormal spread, they say what share of boreholes
  reach the yield that counts as success. A point with no class (no
  position, or open water on the map) gets an even chance, labelled a
  placeholder.
- **"Success"** is a yield of at least 1 m3/h at the dry-season level,
  the handpump design rate. It is `odds.success_yield_m3_per_h` in the
  project's configuration, and changing it changes the prior.
- **The evidence** multiplies the odds: a factor for the depth to
  basement and for whether basement was resolved (both from the range
  of models, so both are left out, at a factor of 1, until the range is
  sampled), and one for the resistivity of the water-bearing zone. A
  poor fit does not make the ground drier; it draws those three factors
  back towards 1. The factors and their reasons are in
  `success_evidence.yaml`.
- **The band** is the prior's own uncertainty, a Beta distribution as
  firm as 10 boreholes for a cited class and 2 for the placeholder,
  carried through the same factors.

A table under each point shows what each piece of evidence was, the
factor it multiplied the odds by and the chance after it, so the factors
multiply back to the answer. Every number in both files is provisional
until a hydrogeologist confirms it and drilled outcomes calibrate it, and
the reports say so. The suitability score stays beside the odds for
comparison.

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
- Where the design specifies a stainless steel rising main (see "The
  rising main the design specifies"), the bill carries line RSM1, the
  extra over the handpump line per metre of rising main, over the pump
  intake depth; with no intake known it is taken as long as the hole, and
  the assumptions say so. Its rate is a placeholder with no quotation
  behind it: type a current price in the catalogue. A material the
  catalogue has no rate for (uPVC) is not priced, and the estimate says
  so in a warning. An estimate typed in without a design takes the
  rising main from the water quality sample in the same way.
- Download the bill of quantities (`.xlsx`, with live formulas the
  contractor can edit) or the full cost estimate report (`.docx`).
- The programme estimate uses the siting success rate typed for it.
  Once soundings are inverted, the page offers the chance of a working
  borehole at the survey's first-ranked point beside it, with a **Use
  N percent** button; the estimate changes only when that is pressed.
  The odds are one point on one survey's ground, and a programme across
  other ground has other odds.

### The cost as a distribution

Under the summary, "The cost as a distribution" gives the planning
figure beside the bill of quantities. The bill of quantities stays the
contract document: it prices every item at its likely rate and is what
a contractor is paid against. The distribution samples 20,000 boreholes
(`cost_range.samples` in the configuration), each with every rate drawn
between the minimum and maximum the rate catalogue gives it, and
reports:

- **P50 and P80** of the cost of a completed borehole: half of the
  sampled boreholes cost less than the P50 and four in five less than
  the P80. Each is the contract price with any VAT, before contingency.
  Budget from these.
- **The expected cost per working borehole**: the mean completed
  borehole, plus the mean dry attempt for each of the dry attempts
  expected before a working one ((1 - p) / p of them at a chance p of
  water). The chance of water is the survey's at its first-ranked point;
  with no survey, no dry hole is allowed for.
- Where the bill of quantities and the planning budget (with its
  contingency) fall among the sampled boreholes.

The depth is drawn from the range of models at the first-ranked point
once the range has been sampled on the Geophysics page; until then it
is held at the depth typed or designed, and the page says so. The
programme estimate is sampled the same way, at its own success rate,
with each sampled programme's rates and depth drawn once for the whole
package. Both appear in the cost estimate report, section 4.1 and the
programme section. The minimum and maximum of each rate are
provisional choices, with their reasons in
`src/groundwater/data/borehole_cost_spread.yaml`; an edited rate keeps
its spread in proportion. The same seed gives the same figures in both
apps.

### The value of one more measurement

Under the distribution, "The value of one more measurement" says what
a second sounding beside the survey's first-ranked point, or a
profiling line through it, is worth to the choice of where to drill,
and what it costs, in the form "A second sounding beside *point* is
worth up to US$ *value* to this decision and costs about US$ *cost*."
The Geophysics page
and the geophysical report print it under the chance of a working
borehole once the cost has been estimated, and the cost estimate
report in section 4.2.

The choice is between drilling at the first-ranked point and going to
the alternative: the other surveyed point with the best odds or, on a
survey of one point, an unsurveyed site on the same ground at the prior.
Going to the alternative is taken to cost its expected cost per working
borehole, from the distribution's mean completed borehole and mean dry
attempt; drilling at the point first costs the completed borehole if
it works, and the dry attempt and then the alternative if it does not.
The cheaper choice is the one with the better odds.

The measurement could read any band of the evidence the odds use (the
depth to basement and whether basement was resolved, for a sounding
whose range has been sampled, and the water-zone resistivity), each
with the factor on the odds `success_evidence.yaml` gives it, weighted
by the point's own fit. The factors do not say how often each band is
seen, so the bands are spread among dry boreholes as evenly as the
factors allow, and among working ones by the factors. That spread is a
choice, not a bound: another the factors allow can put the value higher
or lower, so the page says so. A table under
the sentences gives every band, its two shares and the chance of
reading it now. For each combination of bands the chance at the point
is worked out again and the choice taken again; the value is the
expected cost of the best choice now less the expected cost of the best
choice after the reading. It is never negative, it is zero when no
reading can change the choice, and the page says so, and it is never
more than the value of knowing for certain whether the point would
work, which is printed beside it. The new reading is taken as
independent of the ones already made, given whether a borehole at the
point would work; a sounding beside the first reads much of the same
ground, so on that count the value overstates what it adds. The costs of a sounding
(US$ 100) and a profiling line (US$ 150) are provisional figures in
`src/groundwater/data/field.yaml` with no recorded source.

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

## 9a. Sanitary inspection

In the browser app: [`#/registry`](index.html#/registry). In the
Streamlit app: the Asset registry page.

Once the borehole has an identifier (it needs a recorded position), the
Asset registry page carries the **sanitary inspection** form: WHO's ten
questions for a tubewell (a drilled borehole) with a handpump, such as
whether a latrine is within 10 m, whether the apron is cracked and whether
the pump is loose on its base. Answer each question as you find it at the
wellhead: *Yes* where the risk is present, *No* where it is not. Leave a
question *Not answered* if you could not see; it is not counted as a no.
Enter the date and who inspected, then press *Record the inspection*. The
inspection goes into the borehole's history like any other visit, so it is
saved with the project, and the same form recorded on two phones merges
into one record.

The score is the number of risks present: 0 to 2 is low, 3 to 5
intermediate, 6 to 8 high and 9 or 10 very high. A form with questions
left open gives a range ("between 3 and 5 of 10") and says it is
incomplete.

Under the form, one statement reads the latest inspection with the
E. coli (or thermotolerant coliform) count of the water quality sample
loaded on the Water quality page, and names the date of each. The count
is graded A (none in 100 mL), B (1 to 10), C (11 to 100), D (101 to 1000)
or E (over 1000). The two are then read together in a risk-to-health
matrix to give an action priority: low, higher or urgent. Four things
to know when you read it:

- **A side that is not known gives no priority.** With no sample loaded,
  or no E. coli result in it, the statement says the microbiological side
  is not known. If the borehole's history records a water sample, the
  statement names its date and says its results are not loaded; load that
  sample's sheet on the Water quality page to bring it in. If the history
  records a sample later than the one loaded, the statement names that
  one too. With no inspection on the form, it says the sanitary side is
  not known. The priority is given only where every possible answer on
  the unknown side would give the same one (a count over 1000 is urgent
  whatever the inspection says).
- **Dates are read as YYYY-MM-DD and nothing else**, in both apps. A form
  in a project file whose date is written another way (`20240520`,
  `20/05/2024`) is kept in the history but not used, and the statement
  says how many such forms there are.
- **A range is taken at its worse end.** An incomplete form, or a count
  the laboratory did not put a number to ("TNTC", ">50"), can fall in
  more than one cell; the statement says so and takes the worse until the
  form is finished or the count is known.
- **The matrix reads faecal contamination only.** The statement ends
  with the sample's verdict on everything it tested, so an arsenic or
  manganese failure is not hidden behind a low sanitary priority.

The form's wording was written from WHO's 1997 surveillance volume as field
manuals reproduce it, not checked against the volume. The cells of the
matrix are a choice made in this toolkit (each is the worse of the two
sides' own WHO risk words), not a copy of WHO's figure. Both are listed in
`QUESTIONS.md` for someone with the documents to check. The asset record
(.docx) carries the statement, the latest form as recorded and the
reference.

## 10. Site maps

In the browser app: [`#/site`](index.html#/site), and the terrain
at [`#/site/terrain`](index.html#/site/terrain).

From the country down to the rock under the borehole. The Python app
lays the page out in four tabs: Study area & setting, Topography,
Subsurface and Interactive. The browser app's Site & maps page is one
page of cards instead: the project and its location, where the site
sits, the study area, geology and aquifers, topography and terrain, and
the interactive map.
The subsurface maps outside the reports are in the Python app for now.
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
none is downloaded, so the terrain is worked out from files you supply,
and every figure names their source. Both apps read GeoTIFF and `.hgt`
tiles and analyse the ground around the site: the Python app on its
Topography tab, the browser app on the *Topography and terrain* card
([`#/site/terrain`](index.html#/site/terrain)).
None of it needs GDAL.

- **GeoTIFF tiles** (`.tif`) in longitude and latitude (WGS 84), as
  Copernicus GLO-30 and USGS EarthExplorer SRTM tiles are published and
  as QGIS saves a clip: uncompressed or compressed with DEFLATE (with or
  without a predictor, as the published GLO-30 tiles are), LZW (what
  GDAL's COG driver and QGIS write by default) or PackBits, in strips or
  tiles, BigTIFF included. LZW reads more slowly than DEFLATE in the
  Python app (`bench/README.md` has the figures). A reprojected copy (UTM,
  for example) is refused rather than resampled, because it has already
  been resampled once: supply the tile as you downloaded it. JPEG, LERC,
  Zstandard and the other lossy or newer codecs are refused by name, and
  so are old-style LZW, a rotated grid or one placed by control points,
  scaled values, a GDAL mask of invalid cells, and a file cut into more
  blocks than `terrain.max_blocks`. Each refusal is a sentence that
  names the file and says why, and what to do where there is something
  to do.
- **SRTM-format tiles** (`.hgt`, from NASA Earthdata). Keep the
  filename: the file carries no header saying where on Earth it is, so
  `N08W013.hgt` is placed by its name alone.
- **One grid** (Python app only): `.asc`, what any GIS exports, or
  longitude/latitude/elevation columns in `.xyz` or `.csv`. It is read
  whole and on its own, never joined to other files.

**Where to get the tiles.** Download them by hand; neither app links
to them or fetches them. Copernicus GLO-30 tiles are in the
copernicus-dem-30m bucket of the Registry of Open Data on AWS, and NASA
SRTM and NASADEM tiles on NASA Earthdata and USGS EarthExplorer. The
tiles on viewfinderpanoramas are void-filled compilations of several
sources: declare them as *Another source* (see Credit, below).

**Several tiles, and why.** GeoTIFF and `.hgt` tiles are read a window
at a time, only the blocks the window meets, and several tiles are
joined into one model. The terrain analysis reads the square shown and
5 km beyond it on every side, 30 km across at the defaults, so a site
within 15 km of the edge of a 1-degree tile needs the tile beside it as
well, and a site near a corner all four tiles that meet there. The
Python app's wider topographic map (below), 40 km each way by default,
needs two to four tiles around most sites. Supply every tile the window
touches. Copernicus tiles abut; SRTM tiles share an edge row, which must
agree to the bit. Tiles that do not sit on one grid, or that come from
different products, are refused rather than resampled.

**Supply tiles, not a mosaic.** A mosaic or clip of tiles saved
without a no-data value fills its gaps with 0 m, and 0 m is what
Copernicus writes for the sea. So a 0 m area that meets the land along
a straight line of grid cells 150 long or more
(`terrain.sea_straight_edge_cells`) is taken for such a fill and treated
as a gap rather than sea, and the caption says how much of the square
that was; a smaller fill can still pass for sea. And unless the files
are Copernicus or SRTM-format tiles, recognised or declared, a drainage
line that ends in ground at or below 0 m is dashed, because that ground
may be a fill value rather than the sea. Supply the tiles as you
downloaded them and neither question arises.

**Gaps, missing tiles and the sea.** Ground no file covers is a gap,
and the read says how much of the window that is. The one exception is
the sea: Copernicus and SRTM publish no tiles for open sea, so a missing
tile is taken as sea, with no height, when the full shared edge of every
tile beside it is at or below 0 m; a missing tile with any land on that
edge stays a gap. The figures hatch it. The sea itself is ground at or
below 0 m (`terrain.sea_level_m`) joined to the edge of the analysed
square, so a tidal estuary counts as sea and the drainage lines end at
its head; ground at or below 0 m inland that is not joined to the edge
stays land. Heights below -1000 m or above 9000 m, and infinite values, are
read as no data and counted.

**Credit.** The source is recognised from the tiles' names together
with their georeferencing, so a renamed tile is credited as a file of
unstated source; a file laid out exactly like a GLO-30 tile but not
named like one asks you to say what it is. A file that looks like a
FABDEM tile is flagged: its makers license it for non-commercial use
only, the Copernicus notices may apply to it too, and the credit is
yours to add. The *Source of the elevation model* choice (detect it from
the file names, Copernicus GLO-30, SRTM, or another source in your own
words) lets you state the source, and what you state wins.
Copernicus tiles carry their licence's "produced using Copernicus
WorldDEM-30 ..." notice inside every figure, and its liability sentence
under the downloads, in the drainage lines' GeoJSON and, in the browser
app, in small print on the card (see `THIRD_PARTY_NOTICES.md`).
A `.hgt` tile is credited as an SRTM-format tile of unstated source
unless you say it is SRTM, because NASADEM and void-filled compilations
such as the viewfinderpanoramas tiles use the same format; declare those
as another source.

**The window, the margin and the cap.** The square shown runs 10 km
each way from the site by default (`terrain.analysis_radius_km`). It is
centred on the GPS fix; without one, on the chiefdom or district, and
with no location at all, on the middle of the files, and the read says
which. The analysis also works over 5 km beyond the square on every side
(`terrain.analysis_buffer_km`), so that the edge of the analysis does
not bend the drainage lines: the lines are traced over the whole and cut
where the map ends. Checked against an 11 km margin on three 10 km
windows of a real Copernicus tile, no undashed line cell in the square
shown appeared or disappeared, and 0 to 100 of them kept a changed
upslope area. At the defaults the analysed square is about 983 by 979
cells at 1 arc-second. It may hold at most 1,500,000 cells, margin
included (`terrain.max_cells`), in both apps alike, so that whether a
window is refused does not depend on which app ran it. A radius whose
window would hold more is refused, and the refusal names a radius that
fits: at 1 arc-second and the default margin, 13.7 km south of about 8.3
degrees north and 13.6 km north of it. That radius is worked out from
the largest square window the cap holds, 1,223 cells each way, sized by
a cell's shorter side, less the margin and rounded down to a tenth of a
kilometre, so a radius a little wider, up to about 13.7 km, may still
fit. Coarser tiles fit a wider radius.

**Analysing the terrain.** Add the tiles: in the Python app with the
uploader on the Topography tab, in the browser app by dropping them on
the card or picking them (any file can be picked; the card reads each
one to see what it is). Each GeoTIFF and `.hgt` file is read for its
layout as soon as it is added, so a refusal, or a question about its
source, shows beside its name before anything is analysed; the browser
card also lists each file's size and the source detected. Set the
radius of the square shown (1 to 50 km) and the drainage threshold
(0.05 to 100 km²; 0.5 km² unless `terrain.drainage_area_km2` says
otherwise): a drainage line starts where more than that drains to a
cell. Then press **Analyse the terrain**. The progress names each stage
as it runs, from reading the elevation model to working out curvature
and wetness and looking for lineament candidates, and in the Python app
then each figure as it is drawn. In
the browser app the analysis runs in the background, with the bar
across the top of the page and its **Cancel**, which stops it and keeps
nothing. What the read found comes first: the files read, the cells and
their size, how much of the window is a gap or taken as sea, and any
heights read as no data. Then the four terrain figures, the two of the
lineament candidates and the survey plan laid across them, each with the
same captions under it in both apps.

In the browser app a new drainage threshold redraws the lines without
analysing the ground again: the card traces them afresh on the page
from the analysis it holds, and redraws the relief figure and the
GeoJSON with them, and lays the survey plan again, which keeps clear of
the lines. The lineament candidates do not depend on the threshold, and
stay as they are. The Python app keeps the figures but not the
analysis, so a new threshold there needs another press of the button.
The lines come out the same either way. A new radius, other files or
another declared source need a new analysis in both apps, and the
figures drawn from the old files or the old source are taken away.

**The figures.** Everything on them is worked out from the
elevation model alone, so it is a candidate to check on the ground, not
a mapped stream, spring, wet patch or fracture. The heights are of a
surface, not always of the ground: Copernicus GLO-30 is a surface model
whose heights include tree canopy and buildings, SRTM-format heights
come from radar and include part of them, and the heights of any other
file should be taken to include them. Each figure draws its credit line
and that caveat inside the image, so both go with a downloaded PNG or
SVG; the captions under it say the rest. On every map the sea is pale
blue, a missing tile taken as sea the same blue hatched, and gaps grey.

- **Shaded relief and drainage lines.** The land coloured by height
  under a hillshade lit from four directions (GDAL's multidirectional
  composite), with contours at an interval chosen for the relief, and
  the drainage lines, drawn wider as their Strahler order rises. Water
  is routed over a surface whose closed hollows are filled to their
  spill level, and across flat ground by its distance from higher and
  lower ground rather than by slope. Land the fill raised by 1 m or more
  (`terrain.fill_note_m`) is tinted purple, and a stretch of line routed
  across a filled hollow or a flat is drawn paler. Those are the least
  certain stretches, because a hollow or a flat may be real or made by
  canopy, buildings or an embankment that the model records as ground,
  and they are most of the lines: in three 10 km windows of a real
  Copernicus tile, 79 to 87 percent of the drainage-line cells were
  routed that way. A dashed line may take in water from beyond the
  analysed square or from behind a gap in the model (and, for files
  other than Copernicus or SRTM-format tiles, from behind ground at or
  below 0 m, which may be a fill rather than the sea), so its upslope
  area and order may be larger or smaller than shown. The captions give
  the share of the square taken as sea or as a 0 m fill, the share of
  the line cells drawn paler and of the land tinted, and any cells on
  flats left without a direction.
- **Topographic wetness index**, ln(a / tan β), with water routed to a
  single neighbour (D8): high values mark ground where water gathers
  and lingers. Slopes gentler than 0.001 (`terrain.flat_tan_slope`) are
  taken as 0.001, so a swamp floor still shows. Lightened cells receive
  water from beyond the analysed square or from behind a gap, so their
  values are uncertain.
- **Curvature**, worked out over about 90 m
  (`terrain.curvature_spacing_m`), per km, in two panels. Down the slope
  (profile), positive is convex, where flow speeds up, and negative
  concave; across it (tangential), negative is converging flow, the
  hollows, and positive diverging, the spurs. Ground flatter than 0.001
  is not drawn.
- **Shaded relief from four directions**: four panels, lit from the
  west, north-west, north and north-east (270, 315, 0 and 45 degrees) at
  45 degrees above the horizon, so that none is lit from the bottom of
  the map, where light makes valleys read as ridges. A straight feature
  shows most strongly under light across it and fades under light along
  it; anything seen here is inferred from the terrain, not confirmed by
  geophysics.
- **Lineament candidates**: straight valleys (blue) and straight ridges
  (orange) at least 600 m long, drawn over the relief in grey. In
  crystalline basement a borehole finds water where it meets a fracture
  zone, and a fracture zone often shows on the surface as a straight
  valley, a straight ridge or valleys that line up. The candidates are
  found in the relief smoothed over about 65 m and lit from the four
  directions of the panels above: where the shading changes sharply
  along a line, compared with the ground within 1.5 km of it, and the
  ground bends across the line, a valley where it bends up and a ridge
  where it bends down. Pieces that line up across a gap of up to 300 m
  are drawn as one. They are inferred from terrain, not confirmed by
  geophysics, and the figure says so inside it: a fracture zone, a
  geological contact, a dyke, a road or a field boundary can each draw
  one, and on a surface model a line of trees can too. The method favours
  no direction (tested on terrain that has none), but it draws candidates
  wherever the relief has straight stretches, fractured or not, so they
  are where to look first, not where to drill.
- **Strike of the lineament candidates**: two roses, valleys and ridges,
  of the length of the candidates in each 10° band of strike, measured
  clockwise from grid north. A strike has no way along it, so each band
  is drawn twice, opposite itself; each petal's area, not its reach, goes
  with the length, and both roses are on one scale, the rings naming the
  lengths. A band that stands out is a direction many straight features
  share, which is worth comparing with the structural trends of the
  geological map. The rose is drawn only where there is a candidate.
- **Survey plan**, round the site where it has a GPS position: profiling
  lines across the lineament candidates nearest the site, at right angles
  to their strike, and soundings proposed on them, all inside the 500 m
  within which the water point check counts a source as serving the
  community. Each line runs through its candidate's point nearest the
  site, and so through the site itself unless the candidate ends short
  of it: 400 m long, or as long as the service radius leaves room for,
  with a station every 10 m, the crossing one of them. A candidate that
  a line already crosses at right angles (their strikes within 20°) gets
  no line of its own, and at most two lines are laid. Each line has three
  soundings: on its candidate, and 50 m along the line to either side,
  because a candidate is placed from the terrain only to within a cell
  or two. A sounding is a place a borehole may go, so it is kept the
  distances of the site separation table from what the page maps: 50 m
  from a mapped borehole, 20 m from a dug well, 10 m from any other water
  point, 20 m from surface water and from the drainage lines, which stand
  for the streams, and 1,000 m from the sea. One inside such a ring moves
  along its line to the nearest clear place, no further than 20 m; where
  there is none, it is left out, and the caption says how many and why.
  The water points are those loaded on the Water points page when the
  terrain was analysed. Latrines and soakaways, buildings, refuse dumps
  and burial grounds are on no map here: check each peg for them on the
  ground. Each sounding is planned with the VES co-pilot's AB/2 series
  to the spacing at which the depth-of-investigation rule reaches 60 m
  (AB/2 = 120 m, a 240 m spread), the spread laid along its candidate's
  strike so that it reads the zone along its length. With no candidate
  within the service radius, one line runs through the site across the
  strike of the 10° band holding most of the candidates' length, and no
  sounding is proposed: each goes where the profile finds a zone to
  sound. With no candidate in the square shown, or a site with no GPS
  position, the caption says why there is no plan. A table under the
  figure lists each proposed sounding's position, its line and its
  distance along it, and what it was moved clear of.

**Downloads.** Each figure downloads as PNG and SVG, and the drainage
lines and the lineament candidates as GeoJSON (*Drainage lines
(GeoJSON)* and *Lineament candidates (GeoJSON)* on the browser card).
Each GeoJSON feature is one piece of a line inside the square shown,
with its link number and part, its Strahler order, where it ends, its
upslope area in km² and its length in metres, `edge_contaminated` where
it is dashed on the figure, and `flat_routed_cells` and `filled_cells`:
its cells routed across flats or filled hollows, and those of them the
fill raised by 1 m or more. The file's `description` says what the lines
are and are not, and the file carries the figures' credit line. Each
feature of `lineament_candidates.geojson` is one candidate as a straight
line, with its `kind` (valley or ridge), its `length_m`, its `strike_deg`
from grid north (0 to 180), the straight `pieces` linked into it, and
`cut` where the square shown cuts it; its `description` says that the
candidates are inferred from terrain, not confirmed by geophysics. The
layers themselves are not offered as GeoTIFF yet.

The survey plan downloads as GPX (`survey_plan.gpx`, *Survey plan (GPX)*
on the browser card) and as a GeoLibre project
(`survey_plan.geolibre.json`, *Survey plan (GeoLibre)*). The GPX holds a
waypoint at the site, at the centre of each proposed sounding (`VES 1`,
`VES 2` and on) and at each line's two ends, and each line as a route
with a point at each station, named by its line and its distance along
it (`L1 000`, `L1 010` and on), so that a phone's GPS app that imports
GPX can walk the team to each peg. Each sounding's description says
where it lies, any move, and its AB/2 and spread. The GeoLibre project
draws the service radius, the separation ring round each mapped water
point within reach, the lines, their stations and the soundings, over
the candidates and the water points near the site, and opens on the
service radius.

**Nothing is saved with the project.** The tiles, the radius and
threshold chosen on the page, the figures and the drainage lines belong
to the session: loading a project drops them in both apps, as opening a
sample project or *Reset everything* on the Settings page does in the
browser app, so add the tiles again to work the terrain out afresh; the
same files and settings give the same figures. The relief, the lineament
candidates, their rose and the survey plan go into the desk study, below;
the topographic map and the terrain figures are not carried into the
other reports yet, and both apps say so on the page.

**The desk study.** *Build the desk study (.docx)*, at the foot of the
page in both apps (under the four tabs in the Python app, the last card
on the browser's Site page), writes the eleventh document: what is known
of the site before anyone travels to it. Every copy carries the stamp
*PRE-FIELD DOCUMENT - NOT A SURVEY RESULT* on the page after its cover,
whatever the project holds, since nothing in it was measured on the
ground. It holds:

- the site's names and its position, in degrees and in UTM, on the cover;
- the area maps every report opens on, with the aquifer and geology maps;
- the geology and the aquifer class under the site, the formation the
  crosswalk names and what that rock means for a borehole, and the
  class's published yield range;
- the terrain and its lineament candidates, from the last *Analyse the
  terrain* press: how many, how long, the 10° band of strike that holds
  the most of them, how many come within the 500 m the site serves, and
  the relief, the candidates and their rose as the press drew them;
- the water points the Water points page holds, within the radius it
  searched: how many are working, whether a working improved source lies
  within the 500 m the site serves, the broken ones there to assess for
  rehabilitation, and the nearest 15 in a table. The WPdx+ inventory as
  read here records no depth or yield, and the document says so;
- the earlier projects the Portfolio page holds within 5 km, nearest
  first, with their status, depth, safe yield and water quality;
- the odds of a working borehole from the ground alone, before any
  survey, in the words of the geophysical report's odds;
- the survey plan's lines and soundings, with its figure;
- what the field visit is to check.

Each part says what it waits for where the page holds nothing for it: no
GPS position, no water points loaded, no portfolio loaded, or no
elevation model analysed. A desk study built after the site has moved
more than a metre from where the terrain was analysed leaves the terrain
and the plan out, and says to analyse the terrain again.

**On a phone, and from a copy opened as a file.** If the browser app's
background engine stops partway through the terrain, most likely for
lack of memory, the card says so and suggests a smaller radius, rather
than running the analysis again on the page, where it could take the
tab down with it. A device that reports 2 GB of memory or less asks
before it analyses a window of more than 1,000,000 cells; the default
window at 1 arc-second is just under that.
A copy opened as a file has no background engine: the card says before
a run that the page will be held until the analysis finishes, and
Cancel is read only between reading the files and analysing them.

**Settings.** The radius and the threshold are set on the page; the
rest are under `terrain` in the project's configuration. Most of these
defaults are provisional choices that want a hydrogeologist's or the
owner's confirmation; the changelog lists which, and why.

| Setting | Default | What it sets |
|---|---|---|
| `terrain.analysis_radius_km` | 10 | the radius the page starts at |
| `terrain.analysis_buffer_km` | 5 | the margin analysed beyond the square shown |
| `terrain.max_cells` | 1,500,000 | the cap on the cells analysed, margin included, and on the cells the wider map draws before it thins them |
| `terrain.max_blocks` | 100,000 | the most blocks a file may be cut into, or a window may need decoded |
| `terrain.sea_level_m` | 0 | ground at or below this, joined to the edge, is sea |
| `terrain.sea_straight_edge_cells` | 150 | a 0 m area meeting land along a straight line this many cells long is a fill, not sea |
| `terrain.implausible_below_m`, `terrain.implausible_above_m` | -1000, 9000 | heights outside these are read as no data |
| `terrain.drainage_area_km2` | 0.5 | the drainage threshold the page starts at, in km² |
| `terrain.fill_note_m` | 1 | the raise at which filled land is tinted |
| `terrain.flat_tan_slope` | 0.001 | the least slope (as a tangent) the wetness index takes, and the slope below which curvature is not drawn |
| `terrain.curvature_spacing_m` | 90 | the distance curvature is worked out over |
| `terrain.hillshade_azimuths_deg` | 225, 270, 315, 360 | the suns of the composite hillshade |
| `terrain.hillshade_panel_azimuths_deg` | 270, 315, 0, 45 | the suns of the four panels |
| `terrain.hillshade_altitude_deg` | 45 | the height of the sun above the horizon |
| `terrain.hillshade_z_factor` | 1 | the vertical exaggeration: none |
| `terrain.lineament_smoothing_m` | 65 | how far the heights are smoothed before lineaments are sought |
| `terrain.lineament_contrast_km` | 1.5 | the side of the square a centreline cell is compared with |
| `terrain.lineament_share` | 0.4 | the share of centreline cells kept, the strongest against their surroundings |
| `terrain.lineament_min_curvature_per_km` | 0.1 | the least bend across a line, per km |
| `terrain.lineament_turn_deg` | 30 | the most two neighbouring cells of one line may turn |
| `terrain.lineament_straight_m` | 90 | how far a cell may lie from the straight piece it is on |
| `terrain.lineament_piece_m` | 300 | the shortest straight piece |
| `terrain.lineament_min_length_m` | 600 | the shortest candidate drawn |
| `terrain.lineament_link_angle_deg`, `terrain.lineament_link_offset_m`, `terrain.lineament_link_gap_m` | 10, 90, 300 | how closely pieces must line up, and across how long a gap, to be linked |
| `terrain.survey_lines` | 2 | the most profiling lines the survey plan lays |
| `terrain.survey_line_m` | 400 | the length of a line, where the service radius leaves room for it |
| `terrain.survey_station_m` | 10 | the spacing of a line's stations |
| `terrain.survey_flank_m` | 50 | how far along the line the flank soundings are from the crossing |
| `terrain.survey_move_m` | 20 | the furthest a sounding moves along its line to clear a separation ring; under half of `survey_flank_m` |
| `terrain.survey_cross_within_deg` | 20 | how far from parallel two candidates may be for one line to cross both at right angles |
| `terrain.survey_target_depth_m` | 60 | the depth each sounding is planned to see to, by the depth-of-investigation rule |

**The topographic map and the ground profile** (Python app only). The
Topography tab also draws a topographic map over the wider window the
slider at the top of the page sets: a hypsometric tint, hillshade,
labelled contours at an interval chosen for the relief, and your
soundings as spot heights over it, from tiles or from one `.asc` or
`.xyz` grid. The map is framed on the whole square asked for, with a
sentence saying how much of it the files cover. When the window holds
more cells than `terrain.max_cells`, the map draws one cell in every few
each way, without averaging, and says so. Below that, the ground
profile along the traverse, which needs no elevation model at all: it
is the elevation recorded at each sounding, in order along the line,
measured at the pegs and straight between them. Both apps' geophysical
survey reports carry the profile. The Python app also analyses one
`.asc` or `.xyz` grid, cut to the same window and held to the same cap
as tiles; where the grid ends before the window does, the square shown
stops with it, and the read report gives the radius it reached.

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
both still pools into one view. At its foot, **Predictions and
outcomes** pools the files' ledgers (section 11): how many survey
points were predicted and how many drilled, a table of the drilled ones
with the depth to basement predicted and found and the chance predicted
beside the outcome, and the whole pooled ledger as a `.json` file. A
point found in two files (two copies of one project) counts once.

Under it, **Calibration** scores the pooled forecasts against what was
drilled (PLAN.md step 5.2), and *Build the calibration report (.docx)*
writes them up as a Word document. Only predictions recorded before
their borehole was drilled are scored.

- **The depth to basement.** A calibrated P10 to P90 band holds the
  depth found about four times in five. The report counts how many
  boreholes found basement inside the band, above it and below it, and
  says whether that count is within what a calibrated band would give
  nine times in ten on as many boreholes (6 to 10 of 10), or shows a
  band too narrow or too wide. A borehole that stopped short of basement
  is judged only once it has passed the band's P90. The figure sets each
  depth found against the depth the best fit predicted, with its band; a
  point whose best fit resolved no basement is drawn hollow at the
  middle of its band (P50) instead.
- **The chance of success.** The Brier score of the forecasts (0 is
  perfect; an even chance every time scores 0.25) beside the score of
  the prior alone, and a reliability diagram: in each band of forecast
  chance, the share that succeeded. On calibrated forecasts the points
  lie on the diagonal.
- **Hit rates** by geology unit, survey team and contractor: the share
  of drilled boreholes that succeeded, with the mean chance forecast
  beside it.
- **Too few to judge.** Under 10 boreholes for the band or the odds,
  and under 5 known outcomes for a hit rate, the report says there are
  too few boreholes to judge and gives the counts. Both numbers are
  settings (`ledger.min_boreholes`, `ledger.min_group`).

The report changes nothing the toolkit predicts. In the Streamlit app
the download is offered for the files on the page when it was built;
change the files and build it again.

Last on the page, **Calibration sets** (PLAN.md step 5.3) is where the
pooled ledgers start to change what the toolkit predicts, and only once a
named person says so. It is shown even with no files on the page.

- **The set in force.** Every report reads its priors (the chance of a
  working borehole before the survey is counted), its resistivity edges
  (the clay and fresh basement cut-offs, for each geology unit) and its
  suitability weights from the calibration set in force. Until someone
  adopts one, that is the toolkit's provisional default, adopted by no
  one and not calibrated against drilled outcomes. The card names the
  set in force and lists what it changes besides the priors.
- **Fit a set to the pooled ledgers** fits all three to the drilled
  points whose success is known, judged at the success yield in force.
  Every fit starts from the provisional default, so a borehole is never
  counted twice. A prior row, or an edge of a geology unit, needs 5
  boreholes (`ledger.fit_min_boreholes`), and the weights need 10
  boreholes that succeeded and 10 that failed
  (`ledger.fit_weights_min_each`); the rest stay as they are.
- **The review** sets the fitted set beside the set in force: how many
  boreholes it used and left out, what it fits, and a table each of the
  priors (the provisional table's rate, the rate in force and the
  fitted one, with the number of boreholes it is worth), the edges (the
  layers under and over each, and how many layers each edge misreads
  against the drilling logs) and the weights. A set that fits nothing
  has nothing to adopt.
- **Adopt it.** Type the name of the person adopting it and press
  *Adopt the set and put it in force*. It is numbered after the set in
  force, names the set it replaces, and is in force from then on: every
  page reads by it, and a survey already inverted is read by it again,
  each sounding by the edges fitted for the geology unit under it. The
  range of models of a sounding read by other edges is sampled again
  when asked for. Without a name nothing is adopted.
- **Keep it.** *Download the set in force (calibration.yaml)* saves it,
  with the boreholes it used (by their ledger ids only), the date it was
  fitted and who adopted it. *Put it in force* reads a calibration.yaml
  back; a file that is not a set, or a set nobody adopted, is refused
  and the set in force stays. *Return to the provisional default* drops
  it. The same file, named in a `config.yaml` as `calibration:
  calibration.yaml`, puts it in force for the Python package.
- **Whose it is.** The set in force belongs to the session (the
  Streamlit app) or to the browser (the standalone app), not to a
  project: no project file carries one, and opening a project or a
  sample leaves it in force. In the browser app it outlives a refresh,
  and *Reset everything* returns it to the default; the Streamlit app
  forgets it with the session, so download it to keep it.

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
inverted once on arrival. The range of models is not saved: an
inversion is checked on the way back in by fitting its model to the
readings again, and a range could only be taken on trust, so it is
sampled again when it is asked for.

A project file also carries a **ledger of predictions and outcomes**
(PLAN.md step 5.1): what the survey predicted at each point, written
down when it was predicted, beside what the borehole drilled there
found. It is how the toolkit will learn from the holes drilled with it.

- **Recording.** On the VES page (*Geophysics (VES)* in the Streamlit
  app), *Predictions and outcomes*, below the drill-target suitability,
  has *Record the survey's predictions*, and
  building the geophysical report records them too. Each point's depth
  to basement, water-bearing zones, drilling depth and chance of success
  are written down, with their bands where the range of models was
  sampled first: sample it before recording if you want the bands kept.
  So are the best fit's layers and the four parts of its suitability
  score, which a calibration set (PLAN.md step 5.3) is fitted from: the
  layers against the bands of rock in the drilling log, the parts
  against whether the borehole succeeded.
- **Before and after drilling.** A prediction recorded before a
  drilling log is loaded is a forecast, and once a log is loaded it is
  kept as it was made, whatever is recorded later. One recorded after a
  log is loaded is marked "after drilling", so it is never counted as a
  forecast.
- **The point drilled.** The borehole's outcome goes to the point it
  was drilled at: the one chosen under *Point drilled*, else the nearest
  point within 50 m of the drilling log's GPS position, else the
  survey's only point. Where none of these says, the page asks you to
  choose; the survey's recommended point is never assumed.
- **The outcome** is what the log and the pumping test say, worked out
  again whenever the project is saved, so a corrected log corrects it:
  the depth to fresh rock, the water strikes, the total depth, the
  tested yield and whether it succeeded (a tested safe yield of at least
  1 m3/h, or the driller's recorded status where there is no test).
  The page sets it beside the prediction, row by row.
- **Who.** Each prediction records the survey team that made it: the
  *Field Supervisor* on that point's VES sheet, else the field
  supervisor in the site details. Each outcome records the contractor
  who drilled: the drilling contractor in the site details, else the
  one on the drilling log. Fill them in where you can: the calibration
  report on the Portfolio page (section 10a) gives hit rates by survey
  team and by contractor, and counts a borehole without them as "Not
  recorded".

The file format went to schema 2 to carry the ledger. Either app opens
a file saved before that with an empty ledger, and a file of a later
schema than the app knows still opens, with a warning that what the app
does not recognise is not restored. Loading another project replaces
the ledger with that project's own.

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

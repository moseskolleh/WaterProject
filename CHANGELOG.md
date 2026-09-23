# Changes pending release

## Corrections to the previous entry

The entry that stood here described a body of work that was never
uploaded: the pull request carrying it said so in its own description
and was merged anyway. Most of what it announced is not in this
repository, and some of it contradicted what the code does. It has been
replaced rather than annotated, because a release note nobody can check
is worse than none. What it claimed, and what is true:

- "Twelve reproducible example cases" - there are three
  (`examples/CATALOGUE.md` counts them from the files).
- "PDF previews" - none are produced or committed;
  `examples/build_catalogue.py --previews` renders them where the machine
  has LibreOffice and says so plainly where it does not.
- "Demonstration evidence cannot pass the technical readiness gate" -
  the Dr Timbo example supplied its own GPS position so that it would.
  That has been removed; see below.
- "Versioned inventory snapshots" and "IndexedDB persistence" - neither
  exists anywhere in the toolkit. The browser app mirrors a session to
  `localStorage` and saves a project file; that is all.
- "Population-weighted straight-line accessibility" and "closure and
  monitoring decision reports" - no such code exists. The census
  populations the toolkit does carry are chiefdom totals, which is the
  wrong resolution to weight a distance by: that needs settlement points
  or a population surface, and neither is here.
- "Sixteen derived display districts" - see the boundary note below. The
  sixteen current districts are carried by the crosswalk and the
  population tables, and a point is placed in one through the chiefdom
  polygons; there is no sixteen-district polygon layer, and this
  repository does not hold the data to derive one honestly.

## What changed

A sounding is read to the depth it resolves, not to the length of its
array. A Schlumberger sounding resolves the ground to about half of its
largest AB/2; the interpretation used to take the spacing itself, so a
conductive half-space below 8 m became a "water bearing zone 8 m to
80 m", an aquifer 72 m thick and a recommendation to drill to 80 m, at
both Rokel points, from data that had seen 40. One rule
(`VESConfig.depth_of_investigation_factor`) now sets how deep the
interpretation, the model panel, the layer column, the section and the
drilling-depth cap reach. A water-bearing half-space is an open-ended
zone: "8 m to at least 40 m", flagged `basement_not_resolved`, with the
thickness a minimum and the drilling depth a minimum, and it is called
what it is - a weathered zone whose base the sounding never reached -
rather than "fractured bedrock with groundwater in fractures", which
fresh gabbro at 47 ohm-m is not.

The ranking can now see how well a model fits. Neither Rokel model
reaches the 10 percent misfit target; the report preferred B (2), fitted
to 26.8 percent, over A (1) at 13.3, on 2.7 ohm-m of half-space
resistivity, and said nothing about either fit. A model above the target
now carries a `poor_fit` flag and a sentence in its narrative, the
points are ranked on their suitability discounted by a confidence that
the misfit and an unresolved basement lower, the suitability table
prints that confidence, and two points whose weighted scores are within
three points are said to be indistinguishable rather than 1st and 2nd.
The one ranking is assigned once and read everywhere, so the summary,
the preference table and the scorecard cannot name different points.
The sounding block lists the models tried, names a boundary the
uncertainty factor shows to be unresolved, and, where an earlier
interpretation is supplied, tables it beside the toolkit's with its
reported misfit and the misfit this toolkit computes for it on the same
readings (35.8 percent against the 21.5 reported for Rokel A (1)). Two
readings at one AB/2 that disagree by more than a fifth at an MN change
are a warning naming the pair, not an information note. The preference
table's resistivity column is named for what it holds, the layer
resistivities, and the layer column figure is captioned as one rather
than as a pseudo-section. The browser engine mirrors all of it, and the
parity suite now holds the two engines to the interpretation's zones,
flags, confidence and narrative and to the preference table word for
word.

The survey-scale figures now show what was measured and refuse what was
not. Three soundings on a straight line, the standard field layout,
used to crash the geophysical report and the Streamlit maps page with a
Qhull "initial simplex is flat" error that no handler caught; a survey
that encloses no area now gets its values drawn at the points under a
note saying why there is no surface, and the report catches the error
class Qhull actually raises. The Rokel example hard-coded its two
soundings 60 m apart on the geoelectric section when their own
coordinates put them 20.7 km apart; the section is now drawn from the
recorded positions, no boundary is correlated across a gap wider than
ten times the depth of investigation, and a survey with no closer pair
gets no section and a sentence saying so ("20,751 m apart, about 519
times the 40 m they resolve"). The apparent-resistivity pseudo-section,
the one figure that shows the readings rather than an interpretation of
them, is drawn from two placed soundings, paints no colour across a gap
the correlation rule excludes, and keeps its station labels off the
readings; the protective-capacity map is drawn from the same two. The
report lists, under "Not drawn from this survey, and why", every figure
it could not draw. The drill-target map can be walked to: the
recommended point is a star with its grid coordinates printed beside
it, every point is labelled by rank and score, a tie within three points
is written on the map, the caption describes what was drawn rather than
a surface that was not, and the study-area map stars the recommended
sounding instead of hiding it under a marker for the runner-up. Maps of
an elongated survey keep their proportions and at most five round
grid labels an axis, the resistivity colour scale is fitted to the
models on the figure rather than clipped at fixed limits, and both
Streamlit pages infer the UTM zone from the easting instead of assuming
two different zones.

A pumping test is now worth what it measured. Dr Timbo's constant test
pumped for thirty minutes at 2.93 m3/h from a 5 inch casing and drew the
level down 32.8 m; by Schafer's rule the water standing in the casing
supplies such a pump for the first two hours, so the whole test was the
borehole emptying rather than the aquifer responding, and the Theis fit
duly returned a storativity of 0.18. The report adopted a transmissivity
of 1.4 m2/day from a recovery line that met t/t' = 1 at 21.7 m of
residual drawdown, where the method requires zero, and the completion
and handover reports printed a safe yield of 0.97 m3/h and "successful
and sustainable" without the pumping report's own "treat as indicative".
The analysis now computes the casing-storage period from the casing and
riser diameters, checks the recovery intercept, refuses a storativity no
aquifer has, fits no drawdown line to a first step that ends above the
stated static level, and reads the recovery after a step test against
the discharge-weighted equivalent pumping time. A method that fails any
of these is reported with its reason and not adopted; when nothing
fits to standard the best of the poor fits is adopted and said to be.
Every yield carries a confidence, established or indicative with its
reasons, and every report that prints the yield prints that beside it:
the completion report reserves "successful and sustainable" for an
established yield, and the readiness gate holds "Yield established"
unmet for an indicative one. Dr Timbo's yield is 0.39 m3/h, indicative,
on a 0.54 m2/day Cooper-Jacob line adopted as the best available.

The pump goes where the drawdown the yield was computed on exists. The
intake used to be raised to just clear the drawdown at the safe rate,
which put Dr Timbo's pump at 39 m, three metres above the 42.3 m the
test itself had reached, and spent the safety factor on lifting the
pump; it is now set below the static level plus the dry-season reserve,
the usable drawdown and the submergence margin, never above the deepest
level the test reached, so Dr Timbo's goes to 52 m and the basis says
why. A report prints one pump depth, the deeper of the yield's and the
drought scenario's, instead of 39 m in one paragraph and 40 m in the
next; the test's own pump setting is stated beside it; every depth is
below the top of the casing, the datum the sheet records levels from,
rather than a ground level nobody measured the stick-up to. The
parser flags a level recorded below the pump intake, and a report whose
levels are flagged says they are inconsistent rather than that the
curves are valid. The overview figure labels every step in its own
colour with the legend under the axes, the step figure draws the intake
and the hole bottom, a two-step Hantush-Bierschenk line says it is
exact by construction instead of printing R squared 1.000, the specific
capacity carries its rate, drawdown and time, the test type is written
in words, and the browser engine mirrors all of it with the parity suite
holding both engines to the same confidence, reasons and pump depth.

The borehole design reads the driller's own words. Dr Timbo's log says
"fracture zone 49-52 m" on the 45-50 m row and "fracture zone 60-62 m"
on the 55-60 m row; the screens were set on the five-metre rows, so one
covered a metre of the first zone and the second sat behind plain
casing. A depth range named against a fracture phrase is now the
target, with a metre of screen either side, and the lithology column
draws the zone at those depths with the rock around it classed as what
the driller called it, from one class table shared with the Depth Spine
rather than three. The log records grouting to 20 m; the drawing showed
a 6 m seal with a screen and a gravel pack inside the grouted interval.
The recorded grout is now the seal, nothing is screened inside it, and
the 12 m seepage in clayey laterite is cased off rather than screened,
with the basis saying so. The drilled diameter comes from the log's
diameter column, and the annular fill follows the annulus it leaves: a
5 inch casing in a 6.5 inch hole leaves 19 mm a side, into which no
gravel can be poured, so the drawing, the summary and the bill of
quantities carry no pack instead of the 2-4 mm one the design's own
flag said could not be placed, and the completion and handover reports
print the design's warnings. A pump intake that the yield puts inside a
screen is moved into plain casing beside it, and the reports print that
depth. The drilling template gains a "Screens installed" field; a
drawing built from it is captioned as built, and every other drawing
is captioned as the design it is. Dr Timbo's screens are 25-35, 48-53
and 59-63 m under a 20 m grout, with the pump at 54 m.

The reports say what their inputs support. The geology paragraph was
chosen by the substring "western" in the district name and said
"Freetown Basic Complex" of a site the report's own maps placed on the
Bullom Group; it is now written from the USGS and BGS polygons under
the site, through the crosswalk the map legend uses, and the Western
Area text is chosen by region. The field-work section asserted a
reconnaissance dated the survey day, a geomorphological survey,
traverse selection, pegs and a profiling method for every survey; it
now prints the recorded reconnaissance date and notes when there are
any and says there are none when there are not, states the array and
the count of positioned soundings, says that no elevation model was
supplied, and draws the ground profile the recorded levels support.
Total coliforms were reported as a WHO health-guideline failure and
"faecal contamination" with E. coli at zero: WHO sets no health
guideline for them, so they are a national-limit failure that calls
for disinfection and a sanitary inspection, and the remark, the
verdict and the summary say so. The corrosivity paragraph stated the pH
was within the acceptability range beside a value of 5.9; it now states
the pH and which side of the range it is on. The table of contents
carries the headings themselves rather than "right-click and choose
Update Field", captions carry Word's Caption style, an empty table no
longer crashes a build, the Piper diagram's base labels no longer meet
as "HNO3+K" and the facies section says what the water is, a
provisional report qualifies its own executive summary, the national
standard is cited as unverified, every "(s)" is a noun that agrees with
its count, grid coordinates print as coordinates, the model table
writes "half-space" rather than "0/0", and the placeholder signatories
and phone number are out of the worked examples.

The regional maps show where things are at the scale they are drawn.
The scale caveat quoted an 80 km window on maps drawn at 52 km and
135 km; it now describes the window that was drawn. The same USGS
polygon was named for the site's district rather than its own, so the
Freetown Complex was "Paleozoic Igneous", the age the crosswalk itself
calls wrong, on a Kuntolo map; each polygon is now placed by its own
position. The bundled chiefdom layer truncates names to fifteen
characters and those went onto client maps; the full names are carried
beside them, printed, and accepted from an operator. Guinea and Liberia
were painted the same blue as the Atlantic; the land across the border
is now in the paper tone, told from the sea by the geology layer's own
polygons. Graticule ticks placed past the frame grew every map and
thirteen labels at a tenth of a degree collided; the ticks stay inside
the frame at three to six per axis. The location map highlights the
district the position resolves to, lights both halves of the Western
Area and the chiefdoms of Karene and Falaba, and keeps the site star
clear of the names; the geology tints are separated in greyscale; the
study-area map is drawn at the scale its points need, so Rokel's shows
both soundings 20.7 km apart on one sheet; a unit map over the coastal
plain says that the Precambrian polygon spans the Rokel River Group belt
the aquifer map shows as fracture flow; the Streamlit maps page draws
the maps the reports embed; the national legends sit in the Atlantic
corner and the scale bar's total carries its unit.

An audit of the three worked examples, reading every figure and every
report as a client or a ministry reviewer would, found real defects in
the maps, the borehole design, the VES interpretation, the pumping-test
recommendations and the report text. `ROADMAP.md` lists them by
consequence in the order they are being fixed, with the files, the
browser-engine mirrors and the tests each touches. The first step is
done here: the example folders held twenty-nine figures that no script
had written for months - maps keyed to a district centroid the boundary
layer had since moved, drawings under file names a builder had stopped
using - beside the current ones, with nothing in either name to say which
a committed report embeds. Every example now clears its output folders
before it runs, a map of an area with no GPS fix is named for the area
(`study_area_map_port_loko_district.png`) rather than for a centroid
that moves with every rebuild of the layer, and a test runs each example
into a temporary folder and holds the committed set of files to it.

Offline releases are now built rather than maintained by hand.
`web/build_offline.py` reads the app shell the way a browser does and
emits `docs/sw.js` with exactly the files the page loads; the release
identifier is a hash of those bytes, so a shell change cannot ship
without one. A release is all of its files or none of them: a precache
that cannot complete fails the install, leaves no cache behind and
leaves the device on the release it already had. An open tab finishes on
the release it started with, which is what the app already told the
user.

A handover report no longer claims work nobody recorded. The browser
engine asserted, of every project, that the borehole had been developed
and test pumped, that headworks had been built with an apron, drainage
channel and soakaway, and that a handpump had been installed and
commissioned - whether or not the project held a pumping test, a design,
or anything at all about a pump. Each bullet is now conditioned on the
record that evidences it, as the Python engine has always done.

The Dr Timbo example no longer invents a GPS position to get past the
readiness gate. Its sheets carry none, so its three reports now publish
with the provisional stamp and the position listed as outstanding, which
is what that data supports and a better demonstration of the gate than a
clean cover.

Chiefdom geometry that cannot place a borehole is withheld rather than
trusted. `Maforki` (Port Loko) carried a 21 km² wedge on the Guinea
border in Kono, 247 km from the rest of it, so a borehole sited there
was reported in Port Loko - on the completion report, in the programme
table, and in the coverage ranking that decides where to drill next.
`web/build_boundary_review.py` takes geometry like that out of the
lookup layer and writes it to `boundary_review.geojson` with the
measurements the decision rests on and the chiefdom it probably belongs
to. Nothing is reassigned: a shared boundary is evidence of origin, not
authority over ground. A point there now comes back unplaced, which is
the honest answer.

`examples/build_catalogue.py` indexes the worked examples into
`examples/CATALOGUE.md` and packs each case - inputs, reports, figures
and derived tables - into one zip. Every count comes back out of the
workbook by the reader the toolkit uses, and every verdict is read off
the report's own cover, so a report stamped provisional is listed as
provisional with the requirement it is missing.

Two browser checks now run in CI beside the existing ones.
`tests/webapp/offline.mjs` covers the edges a field device actually
falls off: a file the page loads that nobody precached, a deploy that
half arrived, an update swapped in under a tab mid-recompute, and real
work - loading a survey and recomputing it - with no network at all.
`tests/webapp/review.mjs` holds the documents to what the project holds
a record of: that a demonstration project cannot pass the gate for any
report kind, that the stamp and the outstanding requirement reach the
document the user downloads, that a health failure is still a readable
result while a reading nobody can grade is named, and that an interim
issue says who issued it and why without becoming a certification.

A report drawn from the bundled example data now says so on its own
cover. The samples are offered from a picker so that nobody needs a
borehole to see what the toolkit does, but the documents they produce
carry the same letterhead and signature block as real ones and leave as
`.docx` files that get forwarded and filed. `src/groundwater/data/sample_provenance.csv`
records what each bundled file actually holds - transcribed verbatim,
part illustrative reconstruction, or synthetic - and the certification
gate reads it. Two things fail it, and they are
not equally serious: a source whose readings were invented, which is
true of the file however it was opened, and a source picked from the
sample list, which is a fact about the session and so turns on the
picker's own marker. The Dr Timbo water quality workbook is the first
case - no sample was ever taken - so the completion, quality and
handover reports that example publishes now list it as outstanding. The
Rokel survey is the second: a verbatim transcription of a real 2015
survey, so the example that publishes it under the Rokel name is still
certifiable, while the same file pulled into somebody else's project is
not. The marker is saved with the project, so reopening one does not
launder it, and a role's marker clears when real data is dropped on that
role. `examples/build_catalogue.py` reads the difference straight off
the covers.

The handover works list is now worded identically by the two engines,
and `tests/webapp/parity.mjs` holds them there. Four of its seven
bullets differed, so one borehole got two different certificates: a
quantity surveyor reading the browser's got the screen run, one reading
Python's got the casing size, and neither got the sanitary seal. The
merged bullet carries all three. The drilling bullet also now waits for
a depth figure instead of certifying a borehole drilled to "n/a m" off a
sheet where nobody wrote one down.

The coverage ranking in the browser says how many water points it could
not place. A point inside no chiefdom - the Guinea and Liberia fringe
the search box overhangs, offshore points from bad coordinates, and the
geometry the boundary review now holds back - is left out of every
area's ratio, so the areas it belonged to rank worse than the data
supports. The Streamlit app has always said how many went; this page
ranked the country without them and said nothing.

Autosave tells the truth about what it is holding. A failed write no
longer deletes the copy that already succeeded - the whole state goes in
one `setItem`, which either replaces the old value or throws and leaves
it intact, so there was never a half-written mirror to clear up, and
what the removal actually did was delete this morning's drilling log the
first time a photograph filled the quota. The banner now distinguishes
the two failures, because they call for different urgency: a browser
that has stored something and stopped is losing the last few minutes, and
a browser that has never managed a write at all - a private window, or a
tablet whose storage was full before the app opened - is losing the whole
day, and must not be told a copy is waiting for it.

A release really is all of its files or none of them now. The install
handler has always refused half a release, but that was worth little
while an ordinary page load could rewrite the release it was running:
the fetch handler revalidated in the background and put each answer
back into the *versioned* cache, so a deploy that was still uploading
became the app one file at a time, under the old release's identifier,
without any install ever succeeding. The release cache is now written
only by `install`. Anything in scope that the release does not carry
gets ordinary revalidation in a separate runtime cache, which is
swept with the release it belongs to. `tests/webapp/offline.mjs`
changes a file on the server, loads the page and requires the bytes on
disk to be unchanged; with the old behaviour restored that check sees
the shipped engine replaced by a 39-byte placeholder.

A project saved in the Streamlit app can now be opened in the browser
app. It never could: `serialize_project` always writes five container
keys, PyYAML renders an empty one as `{}` or `[]`, and the browser's
YAML reader refused flow syntax outright - so every Streamlit project
failed to parse, and the portfolio and asset-registry pickers reported
it only as a count of skipped files. Two places in the app and the
user guide said the opposite. The reader now accepts the two empty
collections and still refuses a non-empty flow collection, which it
genuinely cannot read. The smoke fixture that was supposed to guard
this was hand-written and carried none of the five keys, so it passed
against a file no save has ever produced; parity now round-trips the
real bytes of a real `serialize_project` call.

Reports no longer assert equipment and works nobody recorded. The
handover works list ended with an unconditional wellhead bullet, so a
project holding nothing but a site certified an apron and a drainage
channel - in the same function whose docstring says every bullet is
conditioned on the record that evidences it; there is no headworks
record in the toolkit for it to be conditioned on, so the bullet is
gone and `works_completed` remains the supervisor's way to assert it.
The browser's completion report printed "Handpump" as the pump type on
every borehole, from a field nothing in that app ever writes.

The browser's costing report prints the VAT lines again. Its cost
summary table was eight hand-inlined rows with no VAT branch at all,
while the app offers a VAT input and the engine computes the figures,
so a VAT-set estimate showed a contract price, then a contingency
computed on a VAT-inclusive budget, and no line saying where the
difference went. The table now comes from a shared
`costSummaryRows`, compared against Python's `summary_rows` with and
without VAT.

The Streamlit app now reports the inventory rows its reader could not
use. The `skipped` out-parameter added last release was wired only
into the browser, so the two apps disagreed about the same export. And
in the browser, the note that carries those discards sat behind a
"did we load any points?" guard, so it was suppressed in exactly the
case it exists for - a BOM'd export whose first column arrives as
`\ufefflat_deg` loses every coordinate, and the page said "no water
points near this site", the opposite of what the export says.

Stated assumptions are now compared across the two engines, and the
browser states the ones it was silently dropping. A bundled file whose
blank columns were filled in illustratively is recorded as an
assumption on the Python gate and was recorded nowhere on the
browser's; nothing compared the two, because parity checked a gate's
requirements and not its assumptions.

Several documented claims were not true and have been corrected:
`DEPLOY.md` listed two generated parts of `docs/` when there are three
(a deploy following it shipped a stale service worker) and counted six
`.docx` reports when there are ten; `README.md` said every one of the
ten documents opens on a map and that the gate stamps every report,
both of which exclude the laminated identification plate;
`docs/user_guide.md` described the browser app's persistence with the
Streamlit app's words and named a template file the toolkit does not
write; `docs/geolibre_integration.md` still counted seven reports; and
`THIRD_PARTY_NOTICES.md` did not record that chiefdom geometry is
withheld from the CC BY layer.

One test that claimed to catch a defect did not. `review.mjs`'s
"the same figure is the same colour whatever else is on the map"
compared two maps to each other over rank-identical fixtures, and
quantile breaks are rank-based - so the per-map scale it was written
to prevent satisfied every clause in it. It now pins each fill to the
colour the shared class table gives that value, over a third fixture
that is deliberately not rank-equivalent.

The mapping section now answers the question a report opens with. It
had three maps - a national administrative locator and the geological
and aquifer settings - and nothing between the country and the survey
point. There is now a study area map: the chiefdom boundaries around
the site at a scale where the distances can be read off the scale bar,
the survey points and any water points already found on it, and a
thumbnail of the country with the window boxed on it, so the figure
answers "where is this?" as well as "what is here?". Every report that
carries a map of the area carries this one first.

Three of the survey-scale maps the package has always had were
reachable from nothing. `site_location_map`, `iso_resistivity_map` and
`overburden_thickness_map` were called by the test suite and by no
application, report or example; the Maps page drew the three national
context maps and stopped. They are on the Maps page now, alongside the
subsurface maps built from the same interpretations: depth to bedrock,
interpreted aquifer thickness, the bedrock surface as a landform,
aquifer protective capacity in its standard longitudinal-conductance
classes, and transverse resistance. The iso-resistivity map offers only
the electrode spacings every sounding actually measured, because a map
at a spacing two of five curves skipped is interpolated from three
points and captioned as five.

Two sections along the traverse, where there was one. The geoelectric
section existed but had to be told where the soundings were, and its
default was to space them 100 m apart in the order they were handed
over - so a survey that walked 40 m between two pegs and 300 m to the
next came out evenly spaced, which reads as a uniformly thickening
weathered zone when what the ground did was thicken over 40 m and hold
for 300. It is now drawn at the surveyed chainages, from the soundings'
own positions projected onto the best-fit line through them. Beside it
is an apparent-resistivity pseudo-section, which involves no inversion
at all: each point is a reading at the station and electrode spacing it
was taken with, so it is still right if the inversion is wrong. Its
vertical axis is AB/2 and is labelled AB/2, not a depth - current does
spread deeper as the electrodes spread, but the pseudo-depth
conversions vary with the very layering the section is drawn to reveal,
and calling a measurement geometry a depth is how a pseudo-section
starts being read as a cross-section. Where the soundings sit too far
off the line to read as one section, both figures say so on their own
face.

There are topographic maps, and there is no elevation model. None is
bundled and none is downloaded: the map is drawn from a file the
operator supplies and names that file's source on the figure. An SRTM
`.hgt` tile, an ESRI ASCII `.asc` grid and plain
longitude/latitude/elevation columns are all read with numpy alone,
because a drilling supervisor with a laptop in Makeni can obtain any of
them and cannot install GDAL. A void in any of them stays a void rather
than becoming a hollow in the ground, and a scatter of heights is
refused rather than gridded - an elevation surface interpolated from
the spot heights a survey happens to record is a guess about the ground
between the pegs, not a measurement of the landscape. What a survey can
always draw is the ground profile along its own traverse, and that is
drawn separately: measured at the pegs, straight between them, and
saying which stations recorded no elevation.

A caption stopped claiming what its figure did not show. The
geophysical survey report captioned its site figure "Topographic map of
the project area" over a scatter of survey pegs with no elevation,
contour or relief anywhere in it. It is captioned as the survey point
location map it is, and there is a slot beside it for a real
topographic map when the operator supplies an elevation model. The
figure it mis-captioned was, in the event, never drawn at all: nothing
in the toolkit ever set the field it came from.

Two defects in the existing maps, both visible in every report that
carries one. A local geological or aquifer map legended every unit in
the national dataset rather than the units on the map, so a 10 km
window over the Freetown peninsula listed Ordovician, Silurian and
Precambrian formations beside the two under the site, with nothing to
say which two. The legend is now built from what the window actually
holds, tested against the three ways a polygon can reach into a window
- a vertex inside it, the window inside the polygon, or an edge
slicing through. And a two-source attribution line ran a third of a
figure-width past the left spine, which the tight bounding box then
grew the canvas to hold: every local geology and aquifer map has been
sitting in the right-hand half of its own figure with an empty gutter
beside it. The credit wraps to the frame, and the scale bar is lifted
clear of however many lines it wraps to.

A cross-section stopped implying a traverse nobody walked. The
geoelectric section divided the profile equally between its columns, so
two Rokel soundings 20.7 km apart came out as two columns 8 km wide -
each claiming to have measured 8 km of ground. A column is now as wide
as the sounding's own lateral reach, and where the gap between adjacent
soundings dwarfs that reach the figure says in red how many times over:
at Rokel the widest gap is 259 times the 80 m the soundings reached, so
the dashed correlations across it join two measurements with nothing
between them, and the figure now says to read them as a proposal rather
than as a traced horizon.

Both zoomable unit maps now say what scale they were drawn at. The USGS
and BGS layers are published at 1:5,000,000, where a 0.5 mm drafting
line is 2.5 km on the ground, and the toolkit's own default window is
40 km - so a reader is being shown a contact placed to a sixteenth of
the frame it is drawn in. Below 120 km across, the figure says so, and
for the aquifer map it says it in the publisher's words: the BGS Africa
Groundwater Atlas user guide states its country maps are "not suitable
for providing detailed information on geology and hydrogeology at a
sub-national (e.g. catchment) scale".

The maps were redrawn. They had no sea on them, which on the Freetown
peninsula - where most of what this toolkit maps actually is - meant half
of every window was blank paper and the coastline read as the edge of the
data rather than the edge of the land. The mask that stops a geological
unit running on across the Atlantic was painted the page colour, so it
painted out anything drawn underneath it. There is now sea under every
map, a hairline graticule labelled in degrees and minutes instead of a
grey grid heavier than the data, an alternating-segment scale bar with a
zero and divisions somebody can measure against, a compass needle instead
of a line with a letter over it, halos behind every place name, and line
weights that rank coastline over district over chiefdom over geological
contact. All of it lives in one module, `mapping/cartography.py`, because
it had been open-coded in three files with three sets of numbers and the
same site came out looking like three different maps depending on which
function drew it.

The boundaries are the real ones now. They were the geoBoundaries
_simplified_ release put through Douglas-Peucker again at 0.003 degrees
and rounded to four decimal places - about 330 m of simplification on top
of somebody else's, quantised to 11 m steps. On a 25 km study-area map
that is more than a percent of the frame per step, which is why every
coastline looked hand-traced. They are rebuilt from the full-resolution
releases at 45 m for the national outline and districts and 90 m for the
chiefdoms, which is finer than the eye can find at any window this toolkit
draws. This is a real cost and worth stating plainly: the offline app's
precache grows from 1,662 KB to 2,143 KB, on an app installed on phones in
places where that is somebody's data allowance. (The last 12 KB of that is
the lithology crosswalk, bundled so the browser's key can name the rock;
its comment block, which is most of the file, is stripped on the way in.)
It buys a coastline, an estuary and a river boundary that are where they
actually are.

What was NOT done, and deliberately: no curve smoothing at render time.
Running a spline through a simplified boundary produces a confident line
that no survey drew, and this toolkit does not draw confidence it does not
have. The jaggedness was an artefact of simplification, so the fix was
finer data, not a prettier curve over the same coarse data.

The geology stopped being wrong. The bundled layer is the USGS Geologic
Map of Africa at 1:5,000,000 and carries seven classes for the whole
country, which are ages rather than rocks - and one of the ages is
incorrect. The single polygon it calls "Paleozoic Igneous" is the Freetown
peninsula, where the rock is the Freetown Layered Complex: Jurassic
layered gabbro, norite and anorthosite, about 193 million years old. A
driller told "Paleozoic Igneous" has been handed a wrong age and no rock
at all, and the Western Area is exactly where this toolkit is used most.

`sl_lithology_usgs_crosswalk.csv` now says what each class is made of,
from the Geology of Sierra Leone map (Fileccia, Teatini, Walther and
Mastrocola 2017, Hydro Nova for SALWACO and the Ministry of Water
Resources, 1:600,000, 28 formations) - which this repository has committed
all along and the geophysical report already cited in its prose while the
figures beside it said "Precambrian". The key now reads "Freetown Layered
Complex (Jf)" and "Bullom Group (Q, Tb)", and each row carries what it
means for drilling: gabbro stores nothing and yields only from fractures;
the Bullom sands yield well and are the easiest ground in the country to
contaminate.

It annotates rather than reclassifies. The polygon is still the 1:5M one
and is no more accurate for being better named, every row records whether
it is quoted from the committed 2017 map or taken from the wider
literature, a class annotated for one region is not applied to another,
and where the two sources disagree on age the figure states both rather
than quietly correcting somebody else's dataset.

Two of the seven classes are deliberately left unnamed, and that is the
finding rather than an omission. "Ordovician" and "Silurian" have zero
vertices inside Sierra Leone - all 94 and 28 of them are in the Bove
Basin in Guinea, inside the bundled window only because the clip box
reaches 10.15 N. Naming them for a Sierra Leonean formation would put a
name on another country's ground. The 2017 sheet does map Ordovician
inside Sierra Leone; the USGS layer simply does not draw it, because at
1:5,000,000 it is swallowed by "Precambrian".

And "Precambrian", which covers most of the country, is not one rock.
Cross-tabbed against the bundled BGS hydrogeology on a 1.4 km national
grid, 87 per cent of it is basement aquifer and 12 per cent is
consolidated sedimentary with fracture flow - a belt from 7.6 to 9.7
degrees North through Port Loko, Kambia, Moyamba and Tonkolili, which is
the Rokel River Group. That is a different drilling target inside one
colour: fracture flow in indurated beds with shales acting as
aquicludes, rather than a weathered-zone aquifer. Its row says so, and
the BGS aquifer map beside it does separate the two.

The proportions quoted in that row and in this note come from the two
bundled layers and nothing else, so anyone with a checkout can rerun
them; `tests/test_study_area_maps.py` pins them. That matters because an
earlier pass at the crosswalk proposed qualifying the Holocene class as
"85 per cent Bullom Group, 15 per cent metasediment" on the strength of
a nearest-label sample of the 2017 map's PDF text layer. A Voronoi over
label positions is not an overlay of mapped contacts, and it drags a
band of genuinely Bullom ground onto the Magbele and Tapr labels that
sit along the inland edge of the coastal plain. Checked against the BGS
layer - independent, different scale, different publisher - the Holocene
class is 99.4 per cent unconsolidated intergranular aquifer, which is
the Bullom Group and nothing else. The qualification was wrong and was
not made; the header of the crosswalk records why, so nobody
reintroduces it from the same artefact.

The layer also has holes, and the maps now admit it. Two and a half per
cent of Sierra Leone's land area falls in no USGS polygon at all, every
point of it in a coastal district - Bonthe, Port Loko, Moyamba, the
Western Area, Kambia and Pujehun - because at 1:5,000,000 the coastal
units stop short of the shore. That ground used to be painted the same
colour as the ocean, so the Bullom shore and the Sherbro estuaries read
as sea on maps of the country whose coastal aquifer is its most
productive ground. It now carries its own tint and a key entry, "Not
mapped at this scale", on both engines - and the key only carries the
entry when unmapped ground is actually in the window.

Two more things the key used to get wrong. It listed "Ordovician" and
"Silurian", which are masked away when the map is drawn because they are
wholly across the Guinea border: entries for colours that are not on the
map, sending a reader hunting for them. Units that cover no ground inside
the country are now dropped before the key is built. And the national
geological map, which passes no district, refused the crosswalk and fell
back to the source's own wording - so the one polygon in the layer whose
age is demonstrably wrong was captioned "Paleozoic Igneous" on the map
most likely to be read by somebody who does not know better. With no
district there is no region to choose by, but where every row for a
class agrees on the formation there is only one answer to give, and the
lookup now gives it. A named district that has no row still gets
nothing: the Freetown gabbro is not under Kono.

The browser draws the same key. The crosswalk is bundled into
`gwt-data.js` and `gwt-charts.js` mirrors the lookup, its two refusals
and the wrong-age footnote, so the figure on screen and the figure in
the report name the same rock. It also paints sea and unmapped ground
apart, which it did not: the whole map frame was one tint, so a coverage
gap and the Atlantic were indistinguishable. `data_provenance.yaml` had
claimed the crosswalk was embedded in the browser bundle since it was
written; it was not, and now is.

Two defects the rebuild exposed. The boundary review tested whether it had
already withheld a piece of ground by comparing the encoded geometry byte
for byte, which holds only while the layer's vertices never move -
rebuilding at a finer tolerance moved every vertex, so the same Maforki
fragment came back as a second, separate withholding and the file would
have grown another duplicate on every rebuild. Identity is now the same
chiefdom, the same district and centres within five kilometres. And the
graticule labelled the tick just short of 13 degrees West as "12 deg 60'
W", on every map of the Western Area.

The Streamlit design page now designs against the pumping test. It asked
for a static water level with nothing in the box and passed no pump intake
at all, so the intake checks never ran on the design that page hands to the
drawing, the bill of quantities and the completion report: two pages of the
same app disagreed about the same borehole. It prefills the level from the
project's test, says where the figure came from, and passes the intake that
test recommends into the designer.

Every bundled table is now in the provenance record. Six were outside it,
two of them with no stated source at all, so nothing told a reader which
bundled numbers are somebody's published dataset and which are the
toolkit's own working assumptions. The costing and supervision tables are
recorded against the practice guides they were built from, the coverage
classes against the Sphere figures they quote, and the rest as authored
here - with the district boxes marked as a coarse plausibility check and
not a survey product, and the separation distances marked as having no
recorded source at all, which is the honest thing to say about them.
`THIRD_PARTY_NOTICES.md` says the same in prose, and a test now fails if a
bundled table is ever added outside the record.

The parity suite compares what it had only been collecting. Eight groups
were read out of the browser, written into the reference and then held to
nothing: the drilling log's site fields, the pumping test's duration and
recovery levels, the Depth Spine's levels, Piper percentages and quantity
basis, the portfolio statistics and the census statistics. A disagreement
in any of them passed every run, which is how a 12 m against 13 m
divergence once passed 528 of 528 checks. They are compared on the shape
the Python states: a field the browser adds of its own is not a divergence,
and a field Python states has to match.

The browser writes the same reports as the package. It had no figure
derived from the survey at all - no section, no pseudo-section, no
subsurface map, not even the study-area map the report opens on - so a
reader holding the two reports for one survey saw two different documents.
It now draws all of them, the drill-target suitability map with its four
caption states, and the ground surface along the traverse, each with the
caption the Python gives it, and it lists what it could not draw and why.
The refusals are the part that matters: no correlation across a gap too
wide for one horizon to span, no subsurface section where fewer than two
soundings carry a position, and the ground profile omitted in silence where
fewer than two carry an elevation, exactly as the package omits it.

Figures bound for a report are painted for paper. Every chart took its
colours from the live CSS tokens as it was built, and the app's default
theme is dark, so clients opening a report got maps and borehole drawings
rasterised white on black.

The parsers read a field sheet the way a driller fills one in. A non-detect
written with its limit - "ND (<0.05)" - was read as a measured
concentration, so the arsenic a laboratory reported as absent was graded
the worst reading on the sheet. A count nobody quantified - "TNTC",
"Present" - read as "not measured", so a sample with E. coli 0 and total
coliforms too numerous to count was graded Safe, and ">50" was read as
exactly 50, which passes a limit of 50. A longitude typed without its
western sign was taken at face value and the page then relabelled the zone,
moving the site 250 km to fit it inside the country. An interval written
with an en dash was dropped without a word. A water strike was read as the
last number after the last colon, so "8 m at 14:30" recorded a strike 30 m
down. A diameter read without its unit made "165 mm" a 165 inch hole - and
that diameter is what sizes the casing and decides whether a gravel pack
will fit. A Wenner sounding had no ingestion path and was inverted as a
Schlumberger one, wrong by tens of percent with nothing downstream to
notice.

The guideline table no longer carries values WHO does not set. Aluminium
had a health guideline of 0.9 mg/L, which WHO derives and declines to
adopt; hardness and turbidity had WHO acceptability values WHO does not
set; and the nitrogen-basis limits were the floor of their conversions, so
a sample complying as nitrate was failed as nitrogen. A national limit is
reported as provisional, with the WHO figure it was carried across from
named beside it.

The district consistency check reads the boundary polygons. It was judged
against hand-drawn boxes that overlap on half the country and miss a tenth
of it, while the polygons every other part of the toolkit uses sat in the
same package; the boxes are deleted. A seam between two independently
simplified chiefdom rings no longer swallows a point: one named tolerance
closes it, and beyond that the lookup answers nothing rather than placing
the withheld Maforki wedge confidently in Kono.

A hole in a map unit is cut out of it rather than painted over it. Every
interior ring became a filled polygon carrying its parent's code, and
thirteen of them were drawn on top of the unit they should have exposed:
the dolerite dykes in Kono, Koinadugu and Falaba, and the igneous aquifer
around Kamakwie, disappeared behind the ground meant to reveal them. Both
bundled layers are rebuilt with their holes: 34 in the geology and 10 in
the hydrogeology. An earlier note here said the rebuild had to wait for the
raw downloads, but the BGS source had been committed all along, and the
USGS mirror is reachable. The rebuild found that three Precambrian holes
clipped at the window's edge had been dropped, because only a hole's first
vertex was tested and it lay on the edge its outer ring shares. On the
national geology map the lake near 11°35′W, 7°35′N is now water rather
than an outline over granite.

The worked examples' reports are what the code writes today. Report text
changed after they were last regenerated, so the committed reports still
quoted WHO turbidity and hardness values WHO does not set, judged
districts by the deleted boxes and blamed handpumps for a corroded
submersible. Nothing caught it, because the examples test compared file
names; it now compares the text of every report as well.

## A note on the sixteen districts

The shipped district polygons are the pre-2017 fourteen, from
geoBoundaries; Karene and Falaba have no polygon of their own. A point
is still placed in one of the sixteen current districts, because the
lookup goes through the chiefdom polygons and the crosswalk, which is
more accurate than a dissolved district layer would be.

Deriving sixteen district polygons by dissolving the chiefdoms was
tried and does not work on this data, and the reason is worth recording
so it is not tried again: `web/build_geodata.py` simplifies each
chiefdom ring independently, so neighbouring chiefdoms no longer share
vertices and their common boundary does not cancel. Measured on the
committed layer, the boundary left after cancelling shared edges is
760 km for Bo against a true district perimeter of 470 km, and 772 km
for Kono against 374 km - roughly half of it internal seams. A correct
dissolve needs a real geometric union over unsimplified source geometry,
which means the raw geoBoundaries download this repository does not
carry.

Confirmed national standards, current supplier quotations, client report
formats, local calibration outcomes and authoritative boundary ownership
still require source material from the programme. Existing provisional
inputs retain their labels.

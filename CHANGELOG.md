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

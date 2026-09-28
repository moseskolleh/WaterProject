# Changelog

One section per version, newest first. PLAN.md step 0.4 closed the long
"changes pending release" entry as 0.3.0; everything below the Stage 0 notes is
that entry, kept as it was written.

## Unreleased

### Links that go to a page, and less before the first paint (PLAN.md steps 1.4 and 1.5)

Every page of the browser app now has an address, `#/<page>`. The Geophysics, Pumping test and Asset registry pages can also name one item, as in `#/ves/VES-3`, `#/pumping/KTL-01` and `#/registry/<asset id>`. The back and forward buttons move between pages, the user guide links to them, and a QR code on a field sheet can open one. An address wins over the page a saved session was left on. An address the app doesn't know opens the Overview, and an item the open project doesn't hold is flagged across the top of the page. The Streamlit app has no such addresses; step 1.1 is where its pages get their own.

The first screen now loads less. The map layers and the sample workbooks moved out of `gwt-data.js`, now 86 KB, into `gwt-geo.js` (760 KB) and `gwt-samples.js` (50 KB). Those two, and the figures, the map export, the photo slots and the document writer, are fetched the first time a page, a report or a sample needs them. The five scripts left in `index.html` are deferred, and the service worker still precaches every bundle, so the app works offline as before. Time to interactive on the throttled profile (4x CPU, Slow 4G, cold, median of 5 runs) fell from 16.25 s to 9.08 s, 44 percent lower, against the plan's 40. `bench/web.mjs` now follows Lighthouse in never placing time to interactive before the end of DOMContentLoaded; without that floor a page with deferred scripts reads as interactive at first paint, and the floor does not move the figure on 0.3.0. The cost has moved rather than gone: on a cold, uninstalled visit, the first page that draws maps fetches about 1.07 MB before it draws, several seconds on Slow 4G. Once the service worker has installed, that is instant, offline included. What remains on the critical path is `gwt-core.js` and `gwt-app.js`, uncompressed; minifying them is left for later.

### A saved survey reopens without inverting it again (PLAN.md step 1.6)

Reopening a saved survey no longer inverts it again (PLAN.md step 1.6). Each engine saves its inversions in the project file under the SHA-256 of the sounding's id, array type, AB/2, MN and apparent resistivities, the whole VES configuration, a format number and the engine's name. For Python the engine name is the package version, the numpy and scipy versions and a digest of ves/inversion.py, forward.py, splice.py and models.py. For the browser it is the release and a SHA-256 of gwt-core.js written into gwt-data.js. Only the chosen model, its iteration count, whether it converged and the layer-count trials are stored. `restore_inversion`/`restoreInversion` rebuild the rest, and the result is identical to a fresh one on the same machine and build. A file from another machine gives that machine's answer, which can differ in the last digits, as fresh inversions on two BLAS builds do. An entry is ignored and the sounding inverted afresh when its key does not match, when a field is malformed, or when its model does not reproduce the misfit the search recorded. The entry's digest catches accidental damage, not deliberate editing. project.yaml gains an optional `inversion_cache` (schema stays 1), and `.gwt.json` gains `state.inversionCache`. The cache is mirrored to localStorage but dropped from the mirror rather than letting it stop autosave. In the browser, a recompute such as typing a discharge no longer drops the inversions or cancels a run for the same soundings, which used to leave the Geophysics page showing "not yet inverted". Opening another project stops a running inversion before the new project replaces the session. Measured on a shared 4-CPU machine: reopening the saved Rokel project in Python went from 3.10 s to 34.6 ms (median of 5), and in the browser at 4x CPU slowdown from 4.87 s to 0.38 s (median of 3).

### What is still open from these steps

- A page with no service worker yet (a first visit, or `file://`) fetches its bundles on demand, so a deploy landing between first paint and a later bundle could mix two releases in one tab. A release query on the bundle URLs would close it; the service worker already matches with `ignoreSearch`.
- The Python cache key names the numpy and scipy versions but not the BLAS build, and the browser's names the release and the engine's digest but not the JavaScript engine, so a project file from another machine or browser returns that machine's inversion.
- Any change to `gwt-core.js`, or to the hashed Python modules, invalidates every saved inversion, even a change that does not touch the inversion. That is conservative by design.
- The Streamlit "Run inversion" button still always inverts; only loading a project uses the saved inversions.

## 0.3.0

### The release

This is the first tagged release. The version is 0.3.0 in pyproject.toml, and the browser app's About page now names it: `build_webapp_data.py` writes the version into the bundle, and a test holds the bundle, the package and pyproject.toml to one number. A tag `v0.3.0` pushed on main runs `.github/workflows/release.yml`. The workflow refuses a tag that does not match pyproject.toml or a changelog with no section for the version. It checks that the committed service worker is current, builds the wheel, the sdist and the example packs with `nox -s release`, and publishes them as a GitHub Release. The release notes are this section, and `release.json` records the commit, the SHA-256 of every asset and the web app's release identifier from `docs/sw.js`. From this release on, the changelog has one section per version.

### The browser engine runs in a worker (PLAN.md step 1.2)

The VES inversion and the pumping test fits now run in a Web Worker, docs/js/gwt-worker.js. It imports gwt-data.js and gwt-core.js and answers three requests: invert (one sounding), analysePumping and recompute (what the app derives from the sheets once the page has read them, since reading a workbook needs DOMParser). Before, inverting the two Rokel soundings held the page in a single task of 2.7 s on this machine (11-12 s with the CPU throttled four times), and there was nothing to press to stop it. The page calls the worker through GWT.engine, a promise per request. A work bar in the house style shows what is running, how far it has got and a Cancel button. Cancel terminates the worker, which is the one way to stop it in the middle of a fit, and the next request starts a fresh one. The newest recompute or inversion run wins, and a stopped run leaves the results it would have replaced. Opened from file://, or wherever the worker fails to start, the same tasks run on the page, on a structured clone of the request, and give the same answers, compared in smoke.mjs as whole object graphs. There the bar goes up before the page stops drawing, so Cancel is read between soundings. The step test result's drawdown_at and efficiency_at methods became C.stepDrawdownAt and C.stepEfficiencyAt, because a structured clone cannot carry a method. The progress hooks read nothing back: parity.mjs passes 1377/1377 with reference.json untouched. build_offline.py now follows importScripts in the shell's scripts, so the worker's imports are precached, and offline.mjs checks that the worker starts with no network. Measured with Playwright on the Rokel sample, headless Chromium, 3 runs each: at 1x, no main-thread task over 50 ms appears from the click to the result, where before the longest was 2.67-2.76 s. Inversion wall time is about the same, 4.6-4.8 s before and 4.8-5.2 s after on a machine shared with other work. At 4x the page's own tasks during the run are 53-98 ms rather than 11 s. What remains is drawing the loaded sample and the first, cold interpretation of a model on the page between soundings. Chromium does not throttle a worker, so throttled wall times do not compare. smoke.mjs now collects Long Tasks and holds the page to none over 50 ms while the Rokel soundings invert and a pumping test is analysed, at 1x. It also checks that timers and scrolling keep going, that Cancel works in the worker and from file://, and that the readings do see an inversion run on the page.

### PR #52's performance work, carried onto main (step 0.1)

PR #52's performance work is on `main` now. It was carried over by hand rather than replayed: `main` had moved about 98 commits since the PR branched, and had already solved part of the same problem its own way.

- **Forward model and inversion.** The VES forward model evaluates a sounding's spacings in one pass over the quadrature. The inversion takes its Jacobian's five nudged models in one pass too. The arithmetic is unchanged: 300 random models (Schlumberger, finite-MN and Wenner, thin layers included) and 24 synthetic inversions, uncertainty factors included, hash identically to `main`'s. That needed one correction to #52. Its vectorised finite-MN step moved 18 of 951 readings by one unit in the last place, because a scalar `L**2` goes through `pow()` and an array's goes through `x * x`. So that step still combines one reading at a time. The quadrature tables are now built on first use rather than at import.
- **Imports.** The subpackages bind their plotting, workbook and report modules when first used. Importing `groundwater.hydraulics` for an analysis no longer imports pyplot, and importing `groundwater.reporting` no longer imports python-docx.
- **Boundary lookups.** The two copies of the ray cast behind `district_of`, `chiefdom_of` and the coverage lookups are now one, in `groundwater._geometry`. It takes the crossing count over a whole ring at once and holds every ring's bounding box in one array, so a lookup no longer walks all 256 chiefdom rings in Python.
- **Bundled data.** Every bundled data table and map layer, the app's district table included, is read through `groundwater._resources`. Coverage and mapping share one parse of the chiefdom layer.
- **Figures.** `figure_context` now closes any figure a plot function leaves open when it raises.

Two parts of #52 are not replayed, because `main` already does the job. Placing a national pull of water points is done by `coverage.assign_chiefdoms`. Caching the tables is already done where it is repeated: an `lru_cache` holds the WHO table, the provenance record, the crosswalks and the map layers, and the app caches the unit rates and checklists. Those parse in under half a millisecond in any case.

Measured on one 4-CPU machine shared with another job (load average about 3), alternating `main` and this branch, three rounds of small timing scripts:
- One `district_of` lookup goes from 25 ms to 0.03 ms.
- The forward model on Rokel A goes from 0.90 ms to 0.55 ms, and the Jacobian from 4.6 ms to 2.2 ms.
- Inverting both Rokel soundings goes from 4.8-7.8 s to 1.9-4.1 s (noisy).
- Placing 20,000 in-country water points by district goes from 0.13 s to 0.065 s. Points off the chiefdom layer still take the per-point seam pass, and it is unchanged.
- In a fresh interpreter, median of five: importing `groundwater.reporting` goes from 1.1 s to 0.13 s, `groundwater.mapping` from 0.88 s to 0.13 s, and `groundwater.hydraulics` from 0.81 s to 0.53 s.

Answers, reports and the worked examples are unchanged.

### PR #54, landed as three parts (step 0.1)

The district check no longer reports a site just over a drawn border as being in the wrong district. The chiefdom rings it judges by are simplified to within about 89 m of the geoBoundaries line, so a stated district is now accepted when the point is inside it as drawn or within 90 m of its edge. Both engines do this. Measured over one verified interior point per chiefdom, stated as each of the fifteen districts it is not in, the tolerance lets none of the 2,490 wrong statements through. In random samples of placed points, just under one percent lie close enough to another district's edge for it to apply. PR #54's move of the detached Maforki fragment was not taken: that ring stays withheld for review until someone with a source moves it.

The GeoLibre project from both apps now draws the separation distances in site_separation_distances.csv as rings round the wellhead, so a latrine 20 m away or a burial ground 1 km away can be seen over imagery rather than read from a table. The rings are true to the ground to within 0.08 m and are drawn only round a GPS fix. Each says it is ground that has to stay clear, and that the table has no recorded source. They add about 61 KB to a site project.

The continuous survey surfaces (iso-resistivity, depth to bedrock, aquifer thickness, bedrock elevation, transverse resistance) and the drill-target score are now also written as a GeoTIFF beside each picture, so they can be sampled, contoured or laid under imagery in a GIS. A raster is written only for a surface clipped to the surveyed ground and with no lower-bound point. It holds NaN outside the ground and ohm-m rather than log10. A line of soundings, or a map with an "at least" beside a point, stays a picture. The protective-capacity map, drawn in classes, never gets a raster, because a raster would give back the precision the classes withhold. The Streamlit app offers each raster it keeps for download under its map; the browser app draws the surfaces only as pictures, and both say so. The writer needs no dependency. rasterio is a test-only dev dependency that reads each file back, so a raster in the wrong place cannot pass as correct. A 220 by 220 surface is 193,898 bytes and takes well under a millisecond to write, and drawing a five-sounding map took the same time, within noise, with the raster as without it.

### PR #17's wizard fix, ported (step 0.1)

A sounding that will not invert no longer crashes the Streamlit app or costs a loaded project its costing values. Before, the siting step dropped the wizard's load grace before inverting anything and had no guard around the inversion. A workbook whose readings parsed but would not invert therefore ended the run with a stack trace and stored no result. The loaded project's adjusted costing depth was then reset on the next visit to the costing step: in the test case, 85 m came back as the 72 m prefill. Now the failure appears as an error naming the sounding, and the run's progress bar is cleared. Nothing from the failed run is stored. The last successful siting result stays in place, and when there is one the error says that the results shown come from it. The grace is dropped only once a new result has been stored. This is the fix from pull request #17, ported by hand because that branch shares no history with main. The browser app already limited a failure to its own sounding and needed no change. It keeps the other soundings and names the one that failed, whereas the Streamlit app rejects the whole run.

### One command for the checks, and a CI that checks more (steps 0.2 and 0.6)

`nox -s check` now runs the whole check sequence in one command: ruff at the version the dev extra pins, the pytest suite, the bundle freshness checks, `make_reference.py --check`, the four browser suites, and a rebuild of the Depth Spine. CI calls the same nox sessions step by step, so a command changed in one place changes in both. The one thing CI adds is the Python version matrix: a local check covers only the interpreter it runs on. `nox -s build` regenerates the generated files in the order each depends on the last. The Depth Spine goes first, because the demo inlines the package that carries it, and `build_offline.py` goes last. `nox -s examples` reruns the worked examples and their index. `nox -s release` puts the wheel, the sdist and the example packs in `dist/`. The sessions run in the current environment rather than in virtualenvs, because that is the environment CONTRIBUTING.md installs into and the browser suites need Playwright from `node_modules`.

CI now also builds and lints the Depth Spine workspace (`tsc`, `oxlint`, both Vite builds). It fails if the committed build under `src/groundwater/depth_spine/` is not what the source beside it produces, and it counts a new untracked asset as a difference, because Vite names assets by content hash. Here, with Node 22.22.2 and npm 10.9.7, a fresh build is byte-identical to the committed one.

The 59 tests that drive the app through AppTest, regenerate the examples, or took ten seconds or more are marked `slow`. On pull requests they run on Python 3.12 only, in a job of their own that runs beside the fast suite on all four versions. A new nightly run takes the whole suite on every version. Measured one after the other on a shared 4-CPU machine, the full suite took 930 s, the fast part 269 s and the slow part 540 s. On the run for pull request #72, the last before this change, the Python 3.12 test job took 11 min 28 s and the whole run 11 min 29 s. This split should bring a pull request run to roughly 7 minutes; that is an estimate, and no CI run with the new workflow exists yet.

The Playwright browser download and the npm downloads are cached, the pip cache follows `pyproject.toml`, every action is pinned by commit SHA, and the workflow can only read the repository. CI's lint job reads the ruff pin from `pyproject.toml` rather than repeating it. Dependabot proposes grouped weekly updates for the actions, the Python requirements and the Depth Spine's npm packages.

### A performance baseline (step 0.3)

There is now a performance baseline to quote against. `bench/run.py` times the Python package on the bundled examples: importing each subsystem in a fresh interpreter, one forward-model call, inverting each sample sounding, analysing each sample pumping test, building each of the ten reports, recomputing each example saved as a project, and one run of the Streamlit app's script through AppTest. It takes one warm-up and five samples and reports the median with the interquartile range. It holds numpy to one BLAS thread: on this shared 4-CPU machine, OpenBLAS's thread per CPU made the Rokel A inversion 2.3 times slower and about ten times noisier (3.5 s against 1.5 s), which would have made two commits impossible to compare. `--compare bench/baseline.json` prints each measure beside the baseline with the ratio. `bench/web.mjs` loads the browser app cold with the CPU slowed 4x and DevTools' "Slow 4G" network (562.5 ms, 180,000 B/s down). It records first paint, time to interactive by Lighthouse's definition, the bytes sent before first paint, and the wall time and longest main-thread task of a Rokel re-inversion, started from the Geophysics page and judged finished by what the page shows. Time to interactive counts requests still downloading, taken from the DevTools protocol, because Resource Timing lists a request only once it has finished. In the committed baseline (provisional, taken while the machine was shared) the app first paints at 2.5 s after 65 kB and becomes interactive at 16.2 s. A report takes 3 to 6 s to build, most of it drawing the area maps; the asset placard takes 0.17 s. Importing `groundwater.reporting` costs 1.4 s. A Streamlit rerun with every sample loaded takes 3.9 s. With the inversion in the worker, the longest main-thread task during a re-inversion is 175 ms. On c3cb529, where the inversion ran on the main thread, it was 8.9 s (one run). Chromium will not throttle a worker, so the inversion is also timed unthrottled: 3.6 s in the worker against 3.8 s on the main thread (one run). The worker changed where the work runs, not how long it takes. `bench/baseline.json` is committed with each release. The one committed now is provisional, because it was taken while the machine was shared.

### The small untruths (step 0.5)

The Depth Spine workspace no longer asks Google for its fonts. It was the one page in the toolkit that did: both of its builds linked the Google Fonts stylesheet for IBM Plex Sans, IBM Plex Mono and Space Grotesk. Offline it therefore drew in fallback faces, and online every render told a third party that a borehole was being looked at. The faces now come from the package's brand folder, where the main app already keeps its own. IBM Plex Sans 400 to 700 and IBM Plex Mono 600 were added there, copied unmodified from @fontsource/ibm-plex-sans and @fontsource/ibm-plex-mono 5.3.0 (SIL OFL 1.1), and IBM's Plex Sans copyright line was added to the licence. The component build ships the files beside its script. The single-file page the browser demo shows inlines them, because it is handed to the browser as a string and cannot fetch a relative file. The licence header had pointed to a manifest.json that was not in the repository. It is there now, recording the source and SHA-256 of every font file, and the test suite checks the hashes. offline.mjs loads both builds with every request off the machine refused, and requires that none was made and that all three families actually loaded. Against the previous build the same checks fail on the Google request. A build from a clean `npm ci` is byte-identical to what is committed. The static workspace grows from 257,329 to 469,250 bytes, and the WebAssembly demo, which inlines the package, grows from 3,694,714 to 4,277,166 bytes.

DEPLOY.md no longer tells the reader to add `anthropic` to requirements.txt, which already installs it. It pins Playwright 1.56.1 as CONTRIBUTING.md and CI do, and lists the offline and review checks CI runs. It had claimed the standalone app made no external fetches; it now says plainly that two of its buttons go online. It also says that docs/icon.svg is generated. QUESTIONS.md item 7 had still described district bounding boxes. It now says what the checker does: it places a point through the chiefdom polygons and the chiefdom-to-district crosswalk. It names the two limits that remain. First, seams between chiefdoms, left because the layer's build simplifies each ring on its own, which a 50 m tolerance bridges. Second, the withheld Maforki fragment. It also names the boundary data and gazetteer that would help. docs/icon.svg was a hand-made copy of the brand icon. make_brand_assets.py now writes both from one drawing, and a test fails if either is edited on its own.

### What this release leaves open

- Editing a discharge on the Pumping test page while an inversion runs stops the inversion, and nothing re-runs it. Every recompute has always dropped the inversions; the worker only makes this reachable, because the page now stays usable while one runs.
- With the CPU throttled four times, the page still has tasks of 53-98 ms during an inversion. One is drawing the loaded sample. The other is the first, cold interpretation of a model, which could move into the worker's invert reply.
- `bench/` does not yet time the test suite, or the placement of water points outside the chiefdom layer. That placement still takes the per-point seam pass, 5.5-6 s for 20,000 points spread over sea and neighbouring countries.
- The separation-distance rings are drawn in the GeoLibre export of both apps, not on the matplotlib site map. The loader's docstring cites FGN/NWRI 2010, and data_provenance.yaml records no source; the two should agree.
- `web/make_brand_assets.py`, which the icon test names as the remedy, also rewrites icon.png and logo.png, and those do not reproduce byte for byte under matplotlib 3.11.
- The WebAssembly demo inlines the Depth Spine component build, which cannot run under stlite, and grows by 0.58 MB with the fonts.
- On a failed sounding the two apps differ: the browser keeps the other soundings and names the failed one, and Streamlit keeps the previous run. Neither behaviour is documented.

### The repair roadmap

What stood here as "Changes pending release" before PLAN.md, the work of
the repair roadmap (ROADMAP.md), follows unchanged.

#### Corrections to the previous entry

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

#### What changed

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

#### The fixes, reviewed

With every roadmap item ticked, the commits that ticked them were reviewed
area by area, each finding reproduced in both engines and each fix written
against a test that failed on the code as it was. Sixty-nine were found.
The parity suite that holds the browser to the package grew from 623
checks to 1,298 on the way. The five things the fixes deliberately left
open are closed in the next section.

A pumping test no longer rests its yield on a result it refused. When every
fit was disqualified the fallback picked the best R squared over all of
them, so a recovery line meeting t/t' = 1 at 60 percent of its drawdown
could carry a yield of 0.99 m3/h; a fit whose own result is wrong is now
never adopted, and with nothing left the yield is pending and says why.
The yield range left out nothing either, so Dr Timbo's "0.39 m3/h (0.28 to
1.2)" took its top from that refused line; it is 0.22 to 0.71, and a range
now always contains the yield it qualifies. A level the sheet itself shows
cannot be right - below the pump, below the hole - makes the yield
indicative and no longer sets the pump intake, which had put Kuntolo's at
67 m from a reading below the bottom of a 70 m hole. An hourly block is
placed by its heading, so a four-hour test read every few minutes no longer
ends at 226 minutes and gets called short; a step test whose clock
restarts keeps its length; the step table keeps the sheet's step numbers.
Both apps now give the design the one intake the pumping report prints.

A drill-target map no longer passes its star to the runner-up when the
best point has no position, and a survey either side of 12 degrees W is
drawn in one UTM zone instead of on a 660 km map. The tie between the top
two points is decided once, on the project's own margin, and read by the
text, the map and the study-area overlay, so a report can no longer call
two points indistinguishable over a map that stars one; the summary,
conclusions, recommendations and preference table ("=1st") carry it too,
and "listed first by name only" is said only of equal scores. Minimum
aquifer thicknesses are labelled as minima rather than contoured, the
ground profile follows the section's rules (Rokel's straight slope across
20.7 km of unlevelled ground is refused), captions describe what was
drawn, and a refused map names what is actually missing. Nothing below a
sounding's depth of investigation is reported as resolved, and a drilling
depth cut back to it reads as a minimum; the sheets' own warnings, such as
overlap readings that disagree by a factor of two, reach Annex A; a Wenner
survey is described in its own terms.

A laboratory sheet is read as the laboratory wrote it. A filled
detection-limit column had turned "Present", "TNTC" and ">50" into "not
detected", so a sample with E. coli present was graded safe to drink;
bounds and non-detects written with a unit or a label (">50 mg/L", "ND (DL
0.05)", "Absent/100 mL") were read as measured numbers. Both are read as
what they are, bounds are graded through the same limit hierarchy as
measured values, and the combined nitrate and nitrite rule reads either
basis. A national-limit failure no longer claims the WHO health values are
met when something could not be graded, treatment advice follows the
parameter and the direction of the exceedance ("Sulphate" no longer gets
the low-pH advice), and the facies sentence no longer says sodium replaced
calcium in a water whose calcium and magnesium are two thirds of the
cations.

A design document says what the design is. The completion and handover
reports promised a gravel pack in a 19 mm annulus the design had left
empty and listed a generated casing string as completed work; they now
describe the fill the design places and call the construction designed
unless the log records it installed. Every fracture zone a description
names is read, in the usual wordings, so "fractures at 30-31 m and 33-34 m"
screens both; a pump intake inside a screen is no longer lifted above the
level the pumping test reached; a grout written "0-20" is 20 m; "Water
strike 1: 12 m" is a strike and a rest water level is not; the basis
describes only the screens that are built; an as-built record keeps its
screens as recorded. The Depth Spine draws the drawing's lithology bands.

The browser's geophysical report described every site as crystalline
basement, the Bullom sands included, because nothing gave it a geology
paragraph; it is now worked out from the map under the site, word for word
as the package writes it. Two report builds started together no longer put
dark-theme figures into a client document. The browser places and frames a
report's area as the package does, so Karene and Falaba get their maps and
captions carry full chiefdom names, and in both engines a sheet saying
"Western Area" or "Port Loko District" gets its map. A longitude typed in
degrees without its sign is read as west, with a note, instead of placing
the site in central Africa. The study-area tint and the GeoLibre export
keep the holes the rebuilt layers now carry.

#### What the review left open

A laboratory that names a pathogen is read as having named one.
"Salmonella: Present" had become an unknown determinand: not evaluable, so
it kept the sample from "suitable", but not a failure either, so the
verdict asked for the units and detection limits to be confirmed while the
laboratory had reported Salmonella in the water. The only thing that
could have told the code it was microbiological was its unit, and a
heterotrophic plate count in CFU/mL - which WHO does not treat as a health
parameter - would have failed on the same rule. Both engines now recognise
the faecal-oral pathogens by name: any count, "Present" or lower bound is a
health failure with its own treatment line (shock chlorination, a sanitary
inspection, re-sampling for the pathogen and for E. coli); none counted,
"Absent" or "<1" is the requirement met; a coarser detection limit cannot
show that the organism is absent. WHO sets no guideline value for a
pathogen, and the row says that rather than quoting one. A plate count
names no organism and stays an open question.

The short water-quality sentence in the completion and handover summaries
said the WHO values had "not been shown to be met", or that the results
were incomplete, and named nothing; it now says what is unresolved, as the
verdict in the quality section does.

A step test whose clock restarts at each step is recorded as lasting as
long as its steps together: the Kuntolo sheet read that way pumped for 158
minutes, and the test details row said 60. The overview and the step
drawdown figure put each step where it was pumped instead of stacking all
three on the first hour.

The labels on a drill-target map are placed apart. Each used to be written
to the right of its peg, so a dense survey printed its labels through each
other and through the neighbouring pegs; both engines now place the target
first and the rest by rank, each at the nearest place round its peg that
covers nothing, then further out on a leader line. When the full labels do
not all fit, the grade line, which the table carries for every point, gives
way everywhere but at the target, and the caption says the grade is
printed where the map has room. On the Rokel map this moves B (2)'s label
back inside the right-hand neatline, where the browser already had it.

The browser's readiness gate refuses a position outside Sierra Leone, as
the Python's does: the site page flagged such a position and the report
went out unstamped. A latitude and longitude typed into the site boxes is
recorded on the gate as degrees, where it read "-13 mE, 8 mN".

#### A note on the sixteen districts

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

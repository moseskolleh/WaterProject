# The plan after the repairs

`ROADMAP.md` was a repair list, and every item on it is closed. The
toolkit now reads its field sheets faithfully, refuses what it cannot
defend, stamps what it cannot certify, and gives the same answer in
Python and in the browser. That makes it correct. It does not yet make
it exceptional.

This plan is about what comes next. It is written to be implemented
step by step: each numbered step is one pull request (or a short
series), says why it matters, what to build, where the code goes, and
when it counts as done. The stages are ordered so that each one
unlocks the next, but most steps inside a stage are independent.

## The idea

Most borehole software records what happened. This toolkit should
change what happens. Three things, taken together, would make it
unlike anything else used on rural water supply in West Africa:

1. **It stops bad field data while the team is still standing there.**
   Both worked examples lost most of their value in the field: a
   30-minute pumping test that never left casing storage, and a step
   test with no discharges recorded. A phone that knows the rules can
   say "do not stop yet" or "re-measure this reading" at the moment
   it is still cheap to do so.
2. **It states decisions as odds and prices them.** Instead of a
   score of 68, it says something like "about a 65 percent chance of
   a handpump borehole here, basement between 22 and 34 m, expected
   cost per working borehole USD 9,800, and one more sounding is worth
   about USD 400 of that decision". (The figures here are made up to
   show the form; none of them is a result.)
3. **It learns from every hole it predicts, and anyone can check
   what it issued.** Every drilled borehole is a test of the survey
   that sited it. Keep the prediction next to the outcome, and the
   toolkit's advice for Sierra Leone becomes calibrated to Sierra
   Leone, openly and with sign-off. Every issued document carries a
   fingerprint that anyone can verify offline.

Everything else in this plan either makes room for those three (speed,
one source of truth, a worker thread, storage that holds a project) or
carries them out to the people who need them (programme managers,
mechanics, communities).

## Where the project stands

Measured on the current `main` (commit `5ee2277`) unless noted.

| | |
|---|---|
| Python engine | `src/groundwater/`, about 20k lines, 847 test functions in 43 files |
| Browser engine | `docs/js/`, about 2.5 MB of unminified JavaScript; `gwt-core.js` alone is 17,936 lines and 443 exports |
| Streamlit app | `app/streamlit_app.py`, one 5,124-line file; every page runs on every rerun (`_page`, line 1316) |
| Parity | `tests/webapp/parity.mjs` (133 check sites) against `reference.json` (683 KB), built from three sample projects |
| Bundled data before first paint | `gwt-data.js`, 913 KB, of which 714 KB is boundary GeoJSON |
| VES inversion, two Rokel soundings | about 4 s in Python (PR #52 measured 4.62 s); in the browser it runs on the main thread |
| Test suite | 322 s before PR #52's caching, 215 s after (PR #52's own measurement); the slowest tests are the Streamlit AppTests (31 s for the guided wizard alone), which pay for every page on every rerun |
| Releases | none tagged; version 0.2.0; one 927-line "pending release" changelog |
| Stranded work | PR #52 (performance), PR #54 (district accuracy, protection rings, GeoTIFF), PR #17 (wizard fix), open since August |

What is already strong, and must not be lost on the way: fail-closed
verdicts, the readiness gate, provenance with checksums, byte-identical
outputs, offline by default with the network behind a button, and a
house voice in the reports that says exactly what the evidence
supports.

What is in the way:

- Every engine change is written twice and held together by a test
  built on three sample projects. That doubles the cost of every
  feature below unless it is dealt with first.
- The browser does its heaviest work on the main thread. The header
  of `gwt-core.js` says the inversion runs in a Web Worker, but no
  worker exists.
- The browser autosaves the whole project, uploaded workbooks and
  photos included, as base64 in `localStorage` on every change.
- Nothing numerical carries a spread. There is no Monte Carlo,
  bootstrap or quantile anywhere in the package. The suitability
  weights in `siting/suitability.py` are hard-coded, and their own
  docstring says the intended upgrade is "to fit them against real
  drilling outcomes".
- The Depth Spine workspace loads Google Fonts, so it is the one page
  that is not fully offline.

## Rules this plan keeps

These come from `CONTRIBUTING.md` and the roadmap's cross-cutting
rules, plus four new ones for the new kinds of work.

1. Engine changes land in both engines in one commit with parity, until
   step 1.10 decides otherwise. A feature that exists in only one app
   says so in both apps.
2. Network access stays behind a button. No step here needs a server,
   and none makes one mandatory.
3. **A probability always carries its basis and its sample size.** A
   prior that nobody has calibrated is labelled provisional, just as
   the national water standards are today.
4. **Nothing learns silently.** A calibration is a file that a named
   person adopts, and every report names the calibration it used.
5. **Efficiency claims are measured.** Every speed-up quotes a before
   and an after from `bench/` (step 0.3).
6. **Field tools write the templates the parsers already read.** A
   phone is just another way to fill in `template_pumping_test.xlsx`,
   not a new ingestion path.

## The stages at a glance

Sizes are relative: **S** is a single focused pull request, **M** is a
few pull requests, and **L** is a workstream of several weeks.

| Stage | Theme | Size | Release | Needs |
|---|---|---|---|---|
| 0 | Clear the runway | M | 0.3 | none |
| 1 | Speed, and one source of truth | L | 0.4 | 0 |
| 2 | Field co-pilots | L | 0.5 | 1.2, 1.3 |
| 3 | Decisions under uncertainty | L | 0.6 | 1.10 |
| 4 | Siting before the survey | M | 0.6 | 3.3 |
| 5 | The learning loop | M | 0.7 | 3.1, 3.3 |
| 6 | Programme scale | M | 0.8 | 3.4, 5.1 |
| 7 | Twenty years of service | M | 0.9 | 1.3 |
| 8 | Trust that anyone can check | M | 0.9 | 1.3 |
| 9 | People, language and learning | M | 1.0 | 1.7 |
| 10 | AI as reviewer and archivist | M | 0.7 | 1.7 |

Critical path: **0.1 → 1.2 → 1.10 → 2.1 → 3.1 / 3.3 → 5.1 → 5.3.**
Stages 7, 8, 9 and step 10.1 can run alongside it at any time.

---

## Stage 0 — Clear the runway

Housekeeping that makes every later step cheaper to do and easier to
trust.

**0.1 Land or retire the stranded pull requests.** (M, both engines)
- *Why:* PR #52 cut the test suite from 322 s to 215 s, the forward
  model from 739 ms to 130 ms, and the assignment of 20,000 water
  points to districts from 3.31 s to 0.40 s. PR #54 replaced
  bounding boxes that got 1 check in 14 wrong with the chiefdom
  polygons. Both were cut before roadmap PRs #67 to #70 and conflict
  with them now. Carrying them further only makes the merge harder.
- *Build:* rebase #52 onto `main` and re-measure. Split #54 into its
  three parts: the district and Maforki repair, the protection rings,
  and the GeoTIFF writer. Land each one separately. Check whether
  #17's failure still reproduces in the current wizard; port it or
  close it with a note.
- *Done when:* no pull request older than 30 days is open, and
  `bench/` (step 0.3) records the #52 gains on `main`.

**0.2 One command for the whole check sequence.** (S)
- *Why:* the 14-command sequence in `CONTRIBUTING.md` exists only as
  prose, and its order matters (`build_offline.py` must run last).
- *Build:* a `noxfile.py` (or a `Makefile`) with `check`, `build`,
  `parity`, `examples` and `release` sessions that run exactly what CI
  runs, in CI's order. Point `CONTRIBUTING.md` at it.
- *Done when:* `nox -s check` passing locally means CI passes.

**0.3 A performance baseline.** (S)
- *Build:* `bench/run.py`, which times the import of each subsystem,
  the forward model, the inversion of each sample sounding, the
  pumping analysis, each report build and the recompute of a saved
  project. `bench/web.mjs` drives Playwright on a throttled profile
  (4x CPU slowdown, "Slow 4G") and records first paint, time to
  interactive, the longest main-thread task and the inversion wall
  time. Commit `bench/baseline.json` with each release.
- *Done when:* every later efficiency step can quote a before and an
  after from these numbers.

**0.4 Cut the first real release.** (S)
- *Build:* close the pending changelog as `0.3.0`, tag it, and add a
  `release.yml` workflow that builds the wheel and the example packs,
  attaches them to a GitHub Release, and records the service worker
  release identifier. From then on the changelog gets one section per
  version.
- *Done when:* `pip install groundwater-toolkit==0.3.0` works from the
  release assets, and the web app's About page shows the version.

**0.5 Fix the small untruths.** (S)
- The header of `gwt-core.js` claims the inversion runs in a worker.
  Either make it true (step 1.2) or change the comment now.
- The Depth Spine loads IBM Plex Sans and Space Grotesk from Google
  Fonts. Self-host them from `data/brand/fonts/` as the main app
  does, adding IBM Plex Sans under its OFL licence.
- `DEPLOY.md` says to add `anthropic` to the requirements, which is
  already done, and installs an unpinned Playwright. `QUESTIONS.md`
  item 7 still describes bounding boxes. `docs/icon.svg` is a
  hand-made copy of `brand/icon.svg` with no check keeping them the
  same.
- *Done when:* `offline.mjs` loads the Depth Spine with the network
  blocked.

**0.6 CI that is quicker and checks more.** (S)
- Cache the Playwright browsers and npm. Key the pip cache on
  `pyproject.toml`. Run the heavy AppTest and example-regeneration
  tests on one Python version, and the fast suite on all four.
- Pin actions by commit SHA, and add Dependabot for Actions, pip and
  npm.
- Build and lint `ui/depth-spine` in CI (`tsc`, `oxlint`,
  `vite build`), and fail if the committed `frontend/` and
  `static/workspace.html` differ from a fresh build.
- Add a nightly scheduled run, which step 1.8 uses.
- *Done when:* the median CI time on a pull request is lower than
  before and nothing that is built is left unchecked.

---

## Stage 1 — Speed, and one source of truth

The efficiency stage. It pays for everything after it.

**1.1 Streamlit runs only the page you are looking at.** (M, Streamlit)
- *Why:* every page executes on every rerun and is then hidden with
  CSS. One click on the costing page re-parses four workbooks, refits
  Theis and redraws a dozen matplotlib figures.
- *Build:* move each `with tab_x:` block into its own function under
  `app/pages/`, and use `st.navigation` / `st.Page`. Cache parsed
  workbooks and rendered figures by the content hash of their inputs
  (`st.cache_data` keyed on bytes, not on filenames). Put interactive
  widgets inside `st.fragment` so they rerun alone. Stop
  `_cov_join`, a cross-session `cache_resource`, from reading and
  writing `session_state`. The AppTests keep working because shared
  state moves to one `session_state` schema documented in
  `app/state.py`.
- *Done when:* a rerun on any page takes less than a quarter of
  today's time (measured in `bench/`), no page's code runs while
  another page is showing, and the AppTests get faster with it.

**1.2 The browser engine moves into a Web Worker.** (M, browser)
- *Why:* the Levenberg-Marquardt inversion (up to 3 layer counts ×
  2 starting models × 60 iterations with a numerical Jacobian) and the
  Theis fits (up to 200 iterations × 20 attempts) freeze the page on a
  field laptop. `gwt-core.js` already touches no DOM, so it can move
  as it is.
- *Build:* `docs/js/gwt-worker.js` loads `gwt-core.js` with
  `importScripts` and exposes a small message API
  (`invert`, `analysePumping`, `recompute`, `cancel`) that reports
  progress. The app calls it through a promise wrapper, shows a
  progress bar and offers a cancel button. Keep a synchronous
  fallback for `file://`, where workers are restricted.
- *Done when:* during an inversion no main-thread task longer than
  50 ms appears in the Long Tasks API readings `smoke.mjs` collects,
  and the page keeps scrolling.

**1.3 Projects are stored in IndexedDB, not `localStorage`.** (M, browser)
- *Why:* the whole state, including workbooks as base64 and photos,
  is stringified into one `localStorage` key 400 ms after every
  change. It hits the quota on a real project and makes typing
  stutter. Step 2 adds photos and live logs, which makes it worse.
- *Build:* a small storage module that keeps each source file as a
  `Blob` in IndexedDB and the state as structured records, writes only
  what changed, calls `navigator.storage.persist()`, and shows
  `navigator.storage.estimate()` on the Settings page. On first run it
  migrates the `gwt.project.v1` key. The `.gwt.json` file format stays
  the same.
- *Done when:* a project with 50 photos and 10 workbooks autosaves in
  under 50 ms, and survives a reload.

**1.4 Links that go to a page.** (S, browser)
- *Build:* hash routes (`#/ves`, `#/pumping/KTL-01`) driven from
  `store.nav`, so the back button works, the user guide can link to a
  page, and a QR code on a field sheet can open the right one.
- *Done when:* back and forward move between pages, and `smoke.mjs`
  opens every page by its URL.

**1.5 Load less before the first paint.** (S, browser)
- *Build:* split the boundary GeoJSON (714 KB) and the sample
  workbooks out of `gwt-data.js` and load them the first time a map or
  sample is needed. They stay precached by the service worker, so
  offline behaviour does not change. Mark the scripts that are not
  needed first as `defer`. Optionally minify in `build_offline.py`,
  keeping source maps so errors stay readable.
- *Done when:* time to interactive on the throttled profile is at least
  40 percent lower than the 0.3 baseline.

**1.6 Never invert the same sounding twice.** (S, both engines)
- *Why:* `recompute.py` inverts every sounding each time a project
  loads, and so does the browser. The result is fully determined by
  the readings, the configuration and the engine version.
- *Build:* key each inversion result by the SHA-256 of the readings,
  the `VESConfig` and the engine version. Store it in the project file
  as a cache the loader may use and may discard, never as a source of
  truth. A version change invalidates it.
- *Done when:* reopening a saved survey does not run the inversion,
  and a test proves that a changed reading or configuration does.

**1.7 One source for the words and constants both engines use.** (M, both engines)
- *Why:* `qualityRecommendations`, `handoverWorks`, `REFERENCES` and
  `DEFAULT_CONFIG` are written out by hand twice, and parity then
  checks them word for word. Generating both from one file removes
  the whole class of failure rather than testing for it.
- *Build:* `src/groundwater/data/text/*.yaml` holds sentence templates
  with named placeholders and plural forms, and
  `src/groundwater/data/defaults.json` holds the configuration
  defaults. Python reads them directly; `build_webapp_data.py` emits
  them into the bundle. Migrate one list per pull request, starting
  with the three the parity docs already name.
- *Done when:* no report sentence written by both engines is typed
  out twice. This is also the string catalogue that step 9.2 needs.

**1.8 Test the two engines against each other on thousands of cases.** (M)
- *Why:* parity is held on three sample projects. A disagreement that
  only appears on a fourth kind of sheet reaches a client before a
  test finds it.
- *Build:* Hypothesis strategies that generate plausible soundings,
  pumping tests (steps, recoveries, gaps, clock restarts), lab sheets
  (with non-detects, "TNTC" and unit variants) and drilling logs,
  written as workbooks and passed through the real parsers. A Node
  runner puts the same bytes through `gwt-core.js`. The two outputs
  are compared with the tolerances `make_reference.py` already uses.
  Pull requests run a few hundred cases; the nightly job runs tens of
  thousands. Every counterexample is shrunk and saved as a named
  regression case.
- *Done when:* the nightly job has run clean for two weeks, and at
  least one real divergence it found has been fixed. It will find one.

**1.9 Type and lint checks for the code that has none.** (S)
- *Build:* add `// @ts-check` and JSDoc types to the public functions
  of `gwt-core.js`, and run `tsc --noEmit --allowJs --checkJs` and
  `oxlint` over `docs/js` in CI. Run Pyright in basic mode on
  `src/groundwater`, starting with `models.py`, `units.py` and
  `config.py`. Report `pytest-cov` coverage with no threshold at
  first. Clear the deferred Ruff `UP` and `SIM` findings in one
  mechanical pull request.
- *Done when:* about 35k lines of browser JavaScript are no longer
  unchecked.

**1.10 Decide: one engine or two.** (M, decision)
- *Why:* stage 3 adds sampling methods that are expensive to write
  twice. Before that, measure whether the Python engine can be the
  browser's engine too.
- *Build:* a time-boxed spike. Run the VES page's computation through
  Pyodide inside the step 1.2 worker, with only numpy and scipy
  loaded; charts and `.docx` stay in JavaScript. Measure the
  download, the cold start and the warm start on a low-end Android
  phone and on a field laptop, once the files are precached.
- *Decide by numbers written down beforehand.* For example: at most
  25 MB precached once, a warm start under 4 s, and inversion no more
  than twice as slow as today's JS. If the spike meets them, retire
  the science functions in `gwt-core.js` page by page, keep
  JavaScript for the interface, charts and documents, and let parity
  become a test of the interface. If it does not, keep two engines
  with 1.7 and 1.8 as the safety net, and write the stage 3 samplers
  as small, parity-tested cores.
- *Done when:* `docs/decisions/0001-engine.md` records the numbers
  and the decision.

---

## Stage 2 — Field co-pilots

The field half of the idea. These run in the browser app, installed on
a phone or tablet and working offline. They exist in the browser app
only, and the Streamlit app says so. Each one writes the standard
template, so everything downstream stays the same.

**2.1 Pumping test co-pilot.** (L, browser; highest value in the plan)
- *Why:* the roadmap's worst hydraulics findings all began in the
  field. The Dr Timbo test pumped for 30 minutes, all of it inside
  casing storage. The Kuntolo sheet recorded no discharges. Its levels
  sat below the pump intake. None of that can be repaired afterwards.
- *Before pumping:* the operator enters the casing and riser
  diameters, the pump setting, the hole depth, the static level and
  the planned rate. The co-pilot works out Schafer's casing-storage
  time for a conservative transmissivity range (`casing_storage_min`
  already exists in both engines) and states the shortest test that
  can give a transmissivity: "Do not stop before 14:20."
- *While pumping:*
  - a log-spaced reading schedule with a countdown and a sound
    (0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50,
    60, 75, 90 and 120 minutes, then every 30 minutes);
  - drawdown against log time, plotted live;
  - warnings for a level at or below the pump intake, a discharge
    drifting more than 5 percent, and "still inside casing storage";
  - after storage, a live Cooper-Jacob estimate and a note on how
    stable it is: "T has changed less than 10 percent over the last
    log cycle. The test can stop at the planned time."
- *Discharge helper:* a bucket-and-stopwatch timer that asks for the
  bucket volume, takes three timings and averages them into the rate.
  A step test with no discharge becomes impossible to save without an
  explicit "not measured" and a reason.
- *Recovery:* the schedule restarts at the moment the pump stops.
- *Output:* the standard pumping-test workbook, with the device clock
  and GPS in the header.
- *Done when:* played back at speed, the Dr Timbo readings produce a
  "do not stop" warning at 30 minutes, and the Kuntolo sheet cannot be
  saved without discharges or an explicit reason.

**2.2 VES co-pilot.** (M, browser)
- *Before the survey:* the operator enters the target depth. The
  co-pilot proposes the AB/2 series and MN changes using the one
  depth-of-investigation rule (0.5 of the maximum AB/2), so the array
  is long enough before anyone unrolls a cable.
- *At each reading:* enter V and I (or the apparent resistivity), and
  the point appears on the log-log curve. It checks four things:
  - a rise steeper than 45 degrees, which no layered earth can
    produce, so it points to a reading or electrode error;
  - overlapping readings at an MN change that disagree by more than
    20 percent (the existing warning, moved to the peg);
  - a potential too small for the instrument to read reliably;
  - a skipped or repeated spacing.
- A preview inversion runs in the worker once eight readings are in,
  so the team can see whether basement has been reached while they
  can still extend the line.
- *Done when:* the Rokel overlaps that disagree by 45 to 98 percent
  would each have raised "re-measure now" at the peg.

**2.3 Drilling log co-pilot.** (M, browser)
- Intervals are entered against the one lithology class table, so
  saprolite is never logged as "clay" by a free-text slip.
- The penetration rate comes from timestamps, and water strikes carry
  an airlift estimate.
- Each interval can take a cuttings photo tagged with its depth.
- The supervisor countersigns each day.
- The output is the drilling-log and daily-report templates.

**2.4 Photo evidence with provenance.** (S, both engines)
- Every photo carries its capture time, its GPS position (with
  permission) and its SHA-256. Critical supervision items (grout
  placement, screen make-up, disinfection) can require a photo. The
  readiness gate checks that evidence is present, and says it does
  not judge whether the evidence is good.

**2.5 A field kit for teams without a device.** (S, both engines)
- Printable, pre-filled sheets for each borehole (site, identifier,
  reading schedule, casing-storage time) and laminated quick cards
  (VES schedule, pumping schedule, disinfection doses).
- Each sheet carries a QR code with the project and borehole
  identifier, so a photographed sheet matches itself to its project
  when it is extracted (step 10.1).

---

## Stage 3 — Decisions under uncertainty

The decision half of the idea. Every number that feeds a decision gets
a spread, and the decision gets a price.

**3.1 VES: a range of models, not one.** (L, both engines, or one per 1.10)
- *Why:* one Levenberg-Marquardt fit from two starting models is one
  member of a family of models that fit equally well. On Rokel B the
  four-layer fit (24.9 percent) was worse than the three-layer fit
  (23.7 percent), which is a symptom of local minima. The linearised
  covariance is kept only as a thickness factor capped at 10x.
- *Build:*
  - more starting models, drawn by Latin hypercube, each polished by
    Levenberg-Marquardt;
  - a per-reading error model: a base percentage, plus the measured
    discrepancy at each MN overlap;
  - a Metropolis-Hastings sampler over log-parameters, started from
    the best fits, giving P10, P50 and P90 for depth to basement,
    weathered-zone thickness and the resistivity of each unit;
  - the drilling-depth cap uses P90, and still stops at the depth of
    investigation.
  - A forward call on a Rokel sounding takes about 0.85 ms in
    Python today, so 5,000 samples cost about 4 s and 20,000 about
    17 s. That is acceptable in a worker with a progress bar, and
    `bench/` sets the default sample count.
- *Report, in this form:* "Basement between 22 and 34 m (P10 to
  P90); not resolved in 30 percent of the models that fit", with a
  fan of the fitting models drawn over the curve.
- *Done when:* the synthetic tests recover known layer depths inside
  the P10 to P90 band at close to the stated rate.

**3.2 Pumping tests: the right model and its spread.** (M, both engines)
- Keep the Theis covariance that `curve_fit` returns (it is discarded
  at `hydraulics/analysis.py:513`), and add a block bootstrap of the
  residuals for every adopted fit.
- A Bourdet derivative diagnostic plot identifies the flow regime:
  - a unit slope for wellbore storage;
  - a plateau for radial flow;
  - a half slope for linear flow along a fracture, which is common in
    basement rock;
  - the signs of a boundary.
- The Papadopulos-Cooper large-diameter solution models early data
  inside casing storage instead of throwing it away. A short test is
  still marked indicative, but it may no longer be empty.
- The yield and the pump setting become bands, and the "sustainable"
  wording is kept for a band that holds at the dry-season level.

**3.3 The chance of a working borehole.** (M, both engines)
- *Why:* the programme estimate asks the user to type a success rate
  (default 100 percent) and the suitability score is a weighted sum
  nobody has calibrated. What a manager needs is the odds.
- *Build:* a transparent Bayesian model that anyone can follow on
  paper:
  - *Prior:* a success rate for each combination of BGS aquifer
    productivity class and geology unit. The initial values come from
    published regional rates, cited and marked provisional.
  - *Evidence:* likelihood ratios for evidence classes from the
    survey: the regolith-thickness band (from 3.1), whether basement
    was resolved, the resistivity band of the weathered zone, and the
    confidence of the fit.
  - *"Success"* is defined in configuration: a yield of at least the
    handpump design rate at the dry-season level.
- *Output, in this form:* "About 65 percent (between 50 and 78) that
  a borehole here yields enough for a handpump through the dry
  season. Provisional prior." It comes with a breakdown of how much each piece of
  evidence moved the number. The existing score stays in the reports
  beside it until step 5.3 retires it.

**3.4 Cost as a distribution.** (M, both engines)
- Add min / likely / max columns to `borehole_cost_items.csv`. A
  Monte Carlo draws depth from 3.1, rates from those triangles, dry
  holes from 3.3 and mobilisation.
- It reports the P50 and P80 cost per borehole, the expected cost per
  working borehole, and the same for a programme in `programme.py`.
- The deterministic bill of quantities stays the contract document;
  the distribution is the planning figure, and the page says which is
  which.

**3.5 The value of one more measurement.** (S, both engines)
- A small decision calculation: the expected cost of drilling now,
  against the cost of one more sounding or a profiling line plus the
  expected improvement in the odds (from 3.3's likelihood ratios).
- In this form: "A second sounding 40 m east is worth up to USD 420
  to this decision and costs about USD 180." Nothing like this exists in field
  practice today, and it turns survey design from habit into
  arithmetic.

**3.6 One way of reporting uncertainty.** (S, both engines)
- Every report prints the few decision numbers (drilling depth,
  yield, pump setting, odds of success, cost) as a band with its
  basis. Figures show bands as fans.
- The readiness gate treats a decision number with no band as
  incomplete, just as it treats a missing GPS fix.

---

## Stage 4 — Siting before the survey

A desk study the day before anyone travels.

**4.1 Terrain analysis on an elevation model the operator supplies.** (M, both engines)
- The rule that no DEM is bundled stays.
- Read compressed GeoTIFF (DEFLATE and LZW, as in Copernicus GLO-30
  tiles) with a dependency-free reader that mirrors PR #54's writer.
  Today `terrain.py` asks the user to run `gdal_translate` first.
- Add D8 flow direction and accumulation, drainage lines, the
  topographic wetness index, curvature and multi-azimuth hillshade.

**4.2 Lineament candidates.** (M, both engines)
- Straight edges in multi-azimuth hillshade and aligned valleys,
  drawn with an orientation rose. They are captioned "inferred from
  terrain, not confirmed by geophysics", because that is what they
  are.

**4.3 A survey plan.** (M, both engines)
- Proposed VES points and a profiling line that crosses the candidate
  lineaments at right angles.
- They stay inside the community's service radius and outside the
  separation-distance rings (PR #54).
- Each point gets an AB/2 series sized by the depth-of-investigation
  rule.
- Exported to GeoLibre and as GPX, so a phone's GPS walks the team to
  each peg.

**4.4 A desk study report, the eleventh document.** (M, both engines)
- It covers the geology and aquifer class, terrain and lineaments,
  nearby water points with their status and any recorded depth or
  yield, and earlier projects in the portfolio within 5 km.
- It gives the provisional odds of success from the prior alone, and
  the survey plan. It is stamped as a pre-field document.

---

## Stage 5 — The learning loop

The learning half of the idea. A siting method that never compares
its predictions with what was drilled cannot improve.

**5.1 A ledger of predictions and outcomes.** (M, both engines)
- When a completion is recorded at a site that had a survey, pair
  what was predicted (the basement band, weathered-zone thickness,
  water-bearing zone, odds of success, recommended depth) with what
  was found (the logged lithology depths, water strikes, tested
  yield, dry or successful).
- The ledger lives in the project file (a schema bump with a proper
  migration in `project_io.py`) and pools across a portfolio.

**5.2 A calibration report.** (M, both engines)
- Predicted against observed depth, with the share of outcomes inside
  the P10 to P90 band (it should be near 80 percent).
- A reliability diagram and Brier score for the odds of success.
- Hit rates by geology unit, survey team and contractor.
- Below a minimum sample size it says "too few boreholes to judge"
  and shows the counts.

**5.3 Calibration sets, adopted by a person.** (M, both engines)
- Fit the 3.3 priors (a beta-binomial for each class) and the
  resistivity-to-lithology bands for each geology unit from the
  ledger.
- Write them to a versioned `calibration.yaml` that records the
  boreholes it used, its date and who adopted it.
- Reports name the calibration set in force. Nothing changes until a
  named person adopts a new set.
- Once enough holes are in, this replaces the hard-coded `_WEIGHTS` in
  `siting/suitability.py`. That is the upgrade path its docstring has
  asked for since it was written.

**5.4 Historic records.** (M, needs 10.2)
- Decades of paper completion reports hold hundreds of outcomes.
- Digitised in batch (10.2) and checked by a person, they enter the
  ledger marked "historic, extracted", with a lower weight than
  records the toolkit itself produced.

**5.5 Pooled evidence without pooled data.** (S)
- A calibration set is a small open file (CC BY), so organisations
  across Sierra Leone can pool what they have learnt about the ground
  without sharing clients' project files.

---

## Stage 6 — Programme scale

**6.1 Where to drill next, within a budget.** (M, both engines)
- *Candidates:* the areas in the coverage-gap ranking.
- *Value:* expected people served = unserved population × the odds of
  success (3.3).
- *Cost:* the cost distribution from 3.4, with access added.
- *Choice:* ranked by expected people served per dollar. Exact
  selection is used for small lists and a stated greedy method for
  large ones.
- *Output:* the chosen set, why each candidate is in or out, and the
  marginal cost per extra person served. It says plainly that the
  chiefdom populations are too coarse for access distances until
  step 6.2 is done.

**6.2 Settlement-level population.** (S, data)
- GRID3 settlement extents or WorldPop, subject to a licence check
  recorded in `data_provenance.yaml`.
- If the licence does not allow bundling, the operator supplies the
  layer, as with the DEM.

**6.3 Contractor scorecards.** (S, both engines)
- Built from the supervision and procurement records: metres drilled
  against the signed logs, failed acceptance checks, variation
  orders, time overruns, and the dry-hole rate against the predicted
  odds.
- Shown with sample sizes, and never ranked on fewer than five
  boreholes.

**6.4 A programme dashboard.** (M, both apps)
- A map of sites by stage: desk study, surveyed, drilled, tested,
  handed over, in service.
- Spend against certified value over time.
- The outstanding readiness items at each site.
- The same view as `groundwater programme` on the command line.

**6.5 The sixteen districts.** (S, data, needs a networked machine)
- Build them from OCHA COD-AB, as `QUESTIONS.md` item 9(a) and PR #54
  describe, then delete both crosswalk fallbacks.

---

## Stage 7 — Twenty years of service

The registry already has check-summed identifiers, merge by content
and no assumption that anything works. This stage uses those
foundations.

**7.1 From plate to fault report.** (M, browser)
- The QR code on the headworks plate opens a report page that works
  offline, with four choices: working, broken, slow, or bad
  taste/colour. A photo is optional.
- Reports queue on the phone and merge into the registry by content
  hash (the existing rule).
- For feature phones, a short SMS format
  (`BH SL-PL-XXXXXXX-C BROKEN`). The MOD 37,36 check character already
  in the identifier catches a mistyped code.
- An SMS gateway adapter is optional, configured by the programme, and
  never required.

**7.2 Material choice at design time.** (S, both engines)
- The Langelier and Ryznar indices are already computed. When the
  water is aggressive, the design recommends a stainless or uPVC
  rising main and shorter inspection intervals, and the bill of
  quantities follows.

**7.3 Service rounds.** (S, both engines)
- Inspections and samples that are due, grouped by area mechanic,
  with a printable round sheet.

**7.4 How long boreholes keep working.** (M, both engines)
- Kaplan-Meier time-to-failure curves by pump type, contractor and
  water chemistry.
- Survival analysis treats "not reported since" as censored, which is
  the registry's "unknown is not functional" rule written as a method.

**7.5 Sanitary inspection.** (S, both engines)
- WHO sanitary inspection forms for a borehole with a handpump, scored
  and combined with the latest water quality verdict into one risk
  statement.

---

## Stage 8 — Trust that anyone can check

**8.1 Documents that can be verified.** (M, both engines)
- *Why:* in donor-funded drilling, a completion report is money. The
  toolkit's outputs are already byte-identical on re-run, which makes
  this possible.
- *Build:* each issued document embeds a manifest (a custom XML part)
  holding:
  - the SHA-256 of every evidence file;
  - the engine version;
  - the calibration set;
  - the readiness state.

  Its own hash goes into the project file and the registry. A short
  code and a QR code go on the cover. A *Verify a document* page,
  which works offline, reports four things: whether the toolkit
  issued the document, whether it has changed since, whether it was
  certifiable or provisional, and which evidence it rests on.
- *Done when:* changing one digit in a downloaded report makes the
  check fail and name the part that changed.

**8.2 Signed sign-offs.** (M, browser first)
- Each professional has an ECDSA P-256 key pair made with Web Crypto,
  kept in IndexedDB and backed up to a file.
- Sign-offs in the Depth Spine ledger and readiness overrides are
  signed with it.
- The organisation publishes its members' public keys in a small file,
  so a signature can be checked offline.

**8.3 One evidence bundle for each borehole.** (S, both engines)
- `examples/packs/` generalised: raw data, processed tables, figures,
  reports, the manifest and the signatures in one archive.
- It is what an auditor asks for, and it re-verifies itself.

---

## Stage 9 — People, language and learning

**9.1 A community handover sheet.** (M, both engines)
- One page with pictures. It shows how much water the borehole can
  give each day, who to call, how to report a fault (the plate code),
  and what must stay away from the borehole (the separation rings as
  a picture).
- It is written in plain English with a Krio version translated and
  checked by native speakers. Nothing is machine translated.

**9.2 Strings that can be translated.** (M, both apps; builds on 1.7)
- One string catalogue for both apps. English stays the working
  language; community-facing text goes into Krio first.

**9.3 Training mode: find the fault.** (M, browser)
- The roadmap's findings become exercises on the three worked
  examples:
  - the 30-minute test inside casing storage;
  - the half-space reported as an aquifer 80 m deep;
  - the unsigned longitude that put a site 250 km away.
- The trainee has to find the problem before the app shows the
  finding and the fix. Few toolkits can teach from a documented
  record of their own failures.

**9.4 Accessibility.** (S, browser)
- `role="dialog"`, a focus trap and focus return for modals; a live
  region for toasts; `aria-expanded` on the navigation toggle.
- Keyboard walkthroughs in `smoke.mjs`, and an axe-core check on every
  page in CI.

**9.5 A user guide that stays current.** (S)
- Screenshots generated by Playwright on every release, so they never
  go stale.
- Troubleshooting, a glossary and printable quick cards.
- The guide served as HTML, not raw Markdown.

---

## Stage 10 — AI as reviewer and archivist, never the calculator

The rule from the Depth Spine holds for AI too: it computes no
hydrogeology. It reads and it questions.

**10.1 Harden the extraction that exists.** (S, both engines)
- The model (`claude-opus-5`, today in `extraction/claude.py` and
  again in `gwt-core.js`) is named once, in the shared defaults of
  step 1.7.
- Cache the fixed instructions and schema with prompt caching, stream
  large PDFs, and handle a refusal with the API's server-side
  fallback.
- Fill the templates for all four sheet types, not only VES
  (`review.py` fills VES only).
- The QR code from step 2.5 matches a photographed sheet to its
  project.

**10.2 Digitise archives in batch.** (M, Python)
- `groundwater extract --ai --batch <folder>` sends a folder of
  scanned reports through the Message Batches API, which costs half
  the price and runs asynchronously. It writes one review workbook per
  document. Today the command line cannot call Claude at all.
- Rows a person accepts feed the ledger in step 5.4.

**10.3 A second-opinion review.** (M, both apps, opt-in)
- Claude reads the project's structured summary (inputs, flags,
  derived numbers, readiness) and writes the questions a senior
  hydrogeologist would ask. Each question cites the project field it
  is about.
- Every cited field must exist, and every number it quotes must match
  the project, or the memo is rejected.
- The memo is an appendix labelled as an AI review. It cannot change a
  number, pass a gate or sign.

**10.4 Measure before trusting.** (S)
- A small evaluation set of about 30 real field sheets with
  hand-checked transcriptions.
- Measure accuracy cell by cell, and re-run it before any model or
  prompt change ships.

---

## What this plan deliberately leaves out

- **Machine-learning yield prediction from a few dozen boreholes.** It
  would overfit and could not explain itself. The 3.3 model can be
  followed on paper, and step 5.3 calibrates it in the open.
- **A blockchain.** A hash, a signature and a public key file (stage 8)
  give the same assurance without a network.
- **Anything that makes the toolkit depend on a server.** Sync,
  gateways and AI stay optional.
- **Bundling data whose licence cannot be shown.** It stays operator
  supplied, as the DEM is today.
- **Machine-translated Krio.**

## How to tell it is working

Record these at each release in `bench/baseline.json` and the
changelog:

| Measure | Why it matters | Direction |
|---|---|---|
| Field defects caught at capture ÷ all field defects | Stage 2 working | up |
| Reports issued certifiable ÷ all reports | better data, not looser gates | up |
| Share of outcomes inside P10 to P90 | honest bands | near 80% |
| Brier score of the odds of success | the odds mean something | down |
| Predicted ÷ actual cost per working borehole | costing is honest | near 1 |
| Time to interactive, throttled | usable on a field laptop | down |
| Longest main-thread task during inversion | the page stays usable | < 50 ms |
| Streamlit rerun time | the server app is usable | down |
| Nightly fuzz cases without divergence | the two engines agree | up |
| Test suite and CI duration | the cost of every change | down |

## Where to start: the first two weeks

1. Step 0.1: rebase PR #52 and re-measure; split PR #54 into three.
2. Steps 0.2 and 0.3: `nox -s check` and `bench/` with the first
   `baseline.json`.
3. Step 0.5: self-host the Depth Spine fonts and correct the
   worker comment.
4. Step 0.4: tag `0.3.0`.
5. Begin step 1.2 (the worker), because the co-pilots, the samplers
   and the engine decision all stand on it.

# Performance baseline

A change that claims to make the toolkit faster quotes a before and an
after from here (PLAN.md, "Efficiency claims are measured"). Two scripts
take the numbers, both on the bundled examples so that two commits are
timed on the same work, and `baseline.json` holds the last set taken on
the machine named inside it.

## Running it

```bash
python bench/run.py                                  # the Python package, ~8 min
python bench/run.py --quick --only inversion         # one group, 2 samples
python bench/run.py --compare bench/baseline.json    # now, beside the baseline

node bench/web.mjs                                   # the browser app, ~2.5 min
node bench/web.mjs --quick --out web.json
python bench/run.py --from web.json --compare bench/baseline.json
```

`run.py` imports the package from this checkout's `src/`, whatever is
installed, so it times the code beside it. `web.mjs` serves `docs/` with
`tests/webapp/harness.mjs` and needs Playwright as the web tests do.
Both write the same JSON layout (`--out FILE`), and `run.py --from`
reads one or more such files instead of running anything, so one
command merges the two into a baseline and the same `--compare` prints
either against it:

```bash
python bench/run.py --out py.json
node bench/web.mjs --out web.json
python bench/run.py --from py.json --from web.json --out bench/baseline.json \
    --notes "quiet machine, nothing else running"
```

`--only GROUP` (repeatable) is one of `import`, `forward`,
`inversion`, `pumping`, `reports`, `recompute`, `streamlit`. `--quick` takes 2
samples per measure instead of 5 (`web.mjs --quick`: 1 run instead of
3), which is enough to see that something moved and not enough to
quote.

## Comparing two commits

Run both on the same machine, back to back, with nothing else busy -
`load_average` in each run's `machine` block says how busy it was. The
comparison prints the median of each, `now/baseline`, and both
interquartile ranges. A ratio below 1 is faster or smaller. A
difference smaller than the spread either side is noise, not a result;
quote it as no change. Each run also records the commit and whether the
tree was dirty, so a number cannot be quoted against the wrong code.

## What each number means

**`run.py`**, every value in seconds. Each in-process measure makes one
warm-up call that is thrown away, then takes 5 samples; a call under
0.2 s is repeated until one sample lasts that long and averaged. The
reported number is the median, the spread is the interquartile range,
and the method is written beside every measure in the JSON. So these
are steady-state times: bytecode compiled, lookup tables and caches
built by the warm-up.

numpy is held to one BLAS thread (`OPENBLAS_NUM_THREADS=1`,
`OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, unless the environment already
sets them; each run's `machine` block records what they were). The
inversion's matrices are small, and OpenBLAS's default of one thread per
CPU made Rokel A 2.3x slower and ten times noisier on this 4-CPU machine
while another process was running: 1.5 s (IQR 0.04 s) with one thread
against 3.5 s (IQR 0.45 to 0.67 s) with four, in alternating runs of
`--repeats 3 --only inversion`.

- `import/*` - the cost of importing each subsystem in a fresh
  interpreter: the wall time of `python -c "import groundwater.X"`
  minus that of `python -c pass` run just before it. `import/bare
  interpreter start` is that subtracted start, for reference. Importing
  a subpackage runs `groundwater/__init__.py` first, so each figure
  includes it.
- `forward/*` - one forward-model call on the Rokel A sounding's own
  fitted model, at that sounding's electrode spacings.
- `inversion/*` - `invert_sounding` on each sounding in each
  `examples/data/*/*_ves.xlsx`, with the default configuration: the
  layer-count search included.
- `pumping/*` - `analyse_pumping_test` on each sample test: Kuntolo as
  recorded (no discharges, so no transmissivity), Kuntolo with the
  illustrative discharges `run_kuntolo_step_test.py` carries in its
  comments (which reaches the Hantush-Bierschenk analysis), and the Dr
  Timbo constant-rate test with its recovery.
- `reports/*` - each document the package builds, from inputs made
  beforehand, written with its figures into a temporary folder: the
  geophysical, pumping, completion, water quality, handover, cost
  estimate, payment certificate, supervision, asset placard and asset
  record reports. Analyses are not in these times; drawing the figures
  and maps is.
- `recompute/*` - `groundwater recompute` on each example saved as the
  apps save a project (`src_*` entries pointing at the bundled
  samples), reading of the project file included. The Rokel one inverts
  both soundings, so it is roughly their sum. `rokel saved project,
  inversions saved` is the same project saved once it has been inverted,
  with the inversions in the file (PLAN.md step 1.6): reopening a survey
  rather than opening it for the first time.
- `streamlit/*` - one run of `app/streamlit_app.py` through Streamlit's
  `AppTest`, in this process, which is what the app does on every click:
  the first run of a new session, a rerun of that session, and a rerun
  once every sample is loaded and the inversion and cost estimate have
  run (the rerun changes nothing, so it is the cost every later click
  pays before its own work). That loaded rerun is timed on the Overview
  (`rerun, every sample loaded and analysed`, the name the measure had
  when it was the only one) and again on seven other pages (`rerun on
  PAGE, every sample loaded`), each sample picked on its own page and the
  page chosen as the sidebar navigation chooses it. Before PLAN.md step
  1.1 every page ran on every rerun, so these were all one number. Left
  out, with a message, when Streamlit is not installed.

**`web.mjs`**, times in milliseconds and sizes in bytes, the median of
3 cold runs. Each run is a fresh browser with an empty cache on a
throttled profile: the CPU slowed 4x (`Emulation.setCPUThrottlingRate`,
rate 4) and DevTools' "Slow 4G" network (`Network.emulateNetworkConditions`:
562.5 ms latency, 180,000 bytes/s down, 84,375 bytes/s up), at a
1440 x 900 viewport.

- `first paint`, `first contentful paint` - from the Paint Timing
  entries.
- `time to interactive` - Lighthouse's definition: find the first 5 s
  window after first contentful paint in which no long task (over 50 ms
  on the main thread) runs and no more than two requests are in flight;
  TTI is the end of the last long task before that window, or first
  contentful paint if there was none, and never earlier than the end of
  DOMContentLoaded, which Lighthouse takes as a floor too. Without the
  floor a page whose scripts are deferred reads as interactive when it
  first paints: two large scripts still downloading are "no more than two
  requests", and nothing of the app runs until both have arrived. The
  bundled baseline was taken before the floor was added; the app's
  scripts were not deferred then, and DOMContentLoaded came before the
  window it found, so the floor would not have moved it. The requests are the page's own,
  taken from the DevTools protocol's Network events, so a download
  still under way counts from the moment it was sent (Resource Timing
  lists a request only once it has finished). The service worker's
  precache is not counted.
- `bytes before first paint` - the transfer size of the document and of
  every response that had finished by first paint.
- `rokel inversion wall time` - load the Rokel sample from the
  Overview, open Geophysics (VES), press "Re-run inversion", and time
  from the click to the last change the page makes to show the models.
  Completion is read off the page (the busy overlay or work bar gone,
  the curves drawn, nothing changing for 2 s), not from the app's
  internals, so the same script times the inversion on the main thread
  and in a worker.
- `rokel inversion wall time, CPU unthrottled` - the same, pressed again
  with the CPU slowdown off. Chromium throttles only the page's main
  thread; it refuses to throttle a worker ("Operation is only supported
  for pages, not workers"). An inversion in the worker runs at full
  speed while one on the main thread runs at a quarter of it, so across
  that change the throttled wall time is not like for like and this one
  is.
- `rokel inversion longest main-thread task` and `... blocking time` -
  the longest Long Task overlapping the throttled re-inversion, and the
  sum of each one's excess over 50 ms. A Long Task is only reported over
  50 ms, so 0 means none.
- `rokel saved project reopen wall time` and `... longest main-thread
  task` - the Rokel project saved with the Save project button and opened
  again with Open project, with the CPU slowed 4x again, timed from the
  file being chosen to the last change the page makes to show the models.
  Before PLAN.md step 1.6 this inverted both soundings again; since, the
  file carries their inversions and it inverts nothing.
- `autosave of 50 photos and 10 workbooks, main-thread time` (at 4x, and
  `..., CPU unthrottled` at 1x) - PLAN.md step 1.3's project, built by
  `tests/webapp/heavy.mjs` in a browser of its own: 50 canvas-drawn
  JPEGs at the size the photo slots keep and 10 workbooks, about 20.6 MB
  as JSON. Each of five autosaves follows one typed field; the number is
  the median of their main-thread time, taken from a Chromium trace as
  every main-thread task between the write being asked for and it being
  stored or refused, clipped to that interval and summed. `..., first
  write` is the write that stores the whole session. Before step 1.3
  every one of these was the whole session stringified into
  localStorage, and localStorage refused it for quota;
  `options.autosave_stored` in the run says whether the writes went in.

## The committed baseline

`bench/baseline.json` is committed with each release (PLAN.md step
0.3: "Commit `bench/baseline.json` with each release"), taken on a
quiet machine at the release commit, so that the next release's
efficiency work has a before to quote. Its `notes` field says under
what conditions it was taken; a baseline marked provisional was taken
on a busy machine and is for orientation, not for quoting.

# Performance baseline

A change that claims to make the toolkit faster quotes a before and an
after from here (PLAN.md, "Efficiency claims are measured"). Two scripts
take the numbers, both on the bundled examples (except the terrain
group, which reads a seeded synthetic tile, because no elevation model
is bundled) so that two commits are timed on the same work, and
`baseline.json` holds the last set taken on the machine named inside it.

## Running it

```bash
python bench/run.py                                  # the Python package, ~8 min
python bench/run.py --quick --only inversion         # one group, 2 samples
python bench/run.py --compare bench/baseline.json    # now, beside the baseline
python bench/terrain_memory.py                       # the terrain analysis's memory, ~15 s

node bench/web.mjs                                   # the browser app, ~5.5 min
node bench/web.mjs --quick --out web.json
node bench/web.mjs --only terrain                    # the terrain card alone, ~3 min
python bench/run.py --from web.json --compare bench/baseline.json
```

`run.py` imports the package from this checkout's `src/`, whatever is
installed, so it times the code beside it. `web.mjs` serves `docs/` with
`tests/webapp/harness.mjs` and needs Playwright as the web tests do, and
for its terrain measures the package's own dependencies as well: it has
`bench/terrain_memory.py --write-tile` write the tile `run.py` reads
(with `python`, or the interpreter `PYTHON` names).
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
`inversion`, `range`, `cost`, `pumping`, `terrain`, `reports`,
`recompute`, `streamlit`; for `web.mjs`, `--only PART` is one of
`load` (the cold load, the Rokel re-inversion and the reopening),
`autosave` and `terrain`.
`--quick` takes 2 samples per measure instead of 5 (`web.mjs --quick`:
1 run instead of 3), which is enough to see that something moved and
not enough to quote.

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
- `range/*` - `sample_model_range` (PLAN.md step 3.1) on each Rokel
  sounding at the default settings, around its own inversion, which is
  made beforehand: 8 Latin hypercube starts polished by the inversion's
  fit, then 4 chains of 500 burn-in steps and 4,000 kept samples between
  them, each step one forward call.
- `cost/*` - `sample_cost` and `sample_programme_cost` (PLAN.md step
  3.4) at the default sample count, on the Dr Timbo design's bill of
  quantities 100 km from the base, the depth drawn from Rokel A's range
  at the default settings (sampled beforehand) and dry holes at a 60
  percent chance; the programme is ten boreholes at 60 percent.
- `pumping/*` - `analyse_pumping_test` on each sample test: Kuntolo as
  recorded (no discharges, so no transmissivity), Kuntolo with the
  illustrative discharges `run_kuntolo_step_test.py` carries in its
  comments (which reaches the Hantush-Bierschenk analysis), and the Dr
  Timbo constant-rate test with its recovery.
- `terrain/*` - reading an operator's elevation model and analysing it
  (PLAN.md step 4.1). No elevation model is bundled, so the setup writes
  a synthetic 3600 by 3600 float32 tile (a seeded fractal surface with a
  tilt and centimetre steps) laid out as the Copernicus GLO-30 tile N08 W012 is:
  PixelIsPoint, EPSG 4326, 1/3600 degree. `read a window, DEFLATE GLO-30
  layout` reads the window the terrain analysis takes by default (the
  radius shown, 10 km, plus the 5 km margin analysed around it, centred
  on the middle of the tile) from 1024 square tiles compressed with
  DEFLATE and the floating-point predictor, as the published tiles are;
  the window meets four of the sixteen. `read a window, LZW 512 tiles`
  reads the same window from 512 square LZW tiles with no predictor, as
  GDAL's COG driver writes by default; the file holds only the nine tiles
  the window meets, because the pure-Python encoder that writes it takes
  about a second a tile. `... loop decoder` is the same read with the
  reader's LZW decoder swapped for the 40-line loop it is tested against,
  which is the measure behind decoding a Clear segment at a time. `read a
  whole DEFLATE tile` is `read_geotiff` on the whole file, as the command
  line and the tests read it. `analyse the default window` is
  `analyse_terrain` on the DEFLATE window, 983 by 979 cells at 1
  arc-second, with the layers that are only drawn kept in float32 as the
  Streamlit app keeps them. `analyse at the cap` is the same on a window
  near the cap on cells (`terrain.max_cells`) with the default margin: its
  radius is the one the planner's refusal offers when asked for more, so
  the measure follows the cap if the cap moves (16.5 km at 2,000,000
  cells, 1407 by 1401 cells, 1,971,207). `trace drainage lines
  from the core` is `drainage_links` at the default threshold (0.5 km²)
  on the default window's core: the drainage lines alone, which the
  browser traces again on the page each time the threshold is moved.
  Writing the file, reading the window and, for the drainage lines, the
  analysis they are traced from, are setup and are not timed.

  The memory the analysis takes is not in `run.py`'s output, whose layout
  has no field for it. `python bench/terrain_memory.py` writes the same
  tile, then reads the window at the cap and analyses it once in a fresh
  interpreter, after a warm-up analysis of a 1 km window, and prints JSON:
  `increase_mb` is the peak resident set size after the analysis
  (`ru_maxrss`) less the resident set size just before it, the window
  already read; `read_mb` and `first_use_mb` are what the read and the
  warm-up (the modules the analysis imports on first use) added before
  that; and it gives the analysis's wall time, the window, the commit, the
  date and the same `machine` block as `run.py`. MB there are 2^20 bytes,
  `ps -o rss` divided by 1024. It reads `/proc`, so it runs on Linux only.
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
- `terrain default window wall time, worker` and `terrain window at
  the cap wall time, worker` - PLAN.md step 4.1's Topography and
  terrain card on Site & maps, as an operator meets it: the synthetic
  tile `run.py`'s terrain group reads (below) picked on the card, and
  *Analyse the terrain* pressed, timed from the click to the last change
  the page makes to show the four figures. That is all of it: the page
  reading the blocks the window needs out of the file, the engine
  worker reading the window and analysing it, and the page drawing the
  figures. No site is entered, so the window is centred on the middle of
  the tile, as `run.py`'s is: the default (983 by 979 cells analysed),
  and one near the cap on cells, at the radius the card offers when
  asked for 50 km (16.5 km, 1407 by 1401). Each press is made in a
  fresh browser, so the worker starts with it. These are not cold
  loads: the app is loaded first, unthrottled, and the network plays no
  part. The CPU is at full speed, because Chromium slows the page and
  not the worker: at 4x only the page's share would slow.
  `... longest main-thread task, worker` is the longest Long Task in the
  same interval, which is the figures being drawn; the page answers
  while the worker works. `... memory added, worker` (Linux only) is how
  far the renderer process, which holds the page and its worker, rose
  above its resident set at the click: its high-water mark once the
  figures are shown (`VmHWM` in `/proc/PID/status`, reset to the
  resident set just before the click by writing 5 to
  `/proc/PID/clear_refs`), less that resident set.
- `terrain default window wall time, on the page` and `terrain window
  at the cap wall time, on the page` - the same presses with the
  analysis on the page's own thread, as a copy of the app opened as a
  file runs it, having no worker (`GWT.engine.forcePage`, the engine's
  switch for tests), and the CPU slowed 4x, so the page is held from
  the read to the figures.

## The range of models: why 4,000 samples

PLAN.md step 3.1 asks for the default sample count to be set from a
measurement here. On 4 October 2026, on this repository's 4-CPU
machine (load average 1.4 from another agent's work), `run.py --only
forward --only range` timed one forward call on Rokel A at 366 us (IQR
25 us), against the 0.85 ms the plan estimated from the older baseline
(967 us there), and the default range at 4.95 s on Rokel A (three
layers) and 1.30 s on Rokel B (two). The same ranges took 7.7 to 7.9 s
and 0.63 to 0.70 s in the browser app's engine worker, three runs in
headless Chromium: the browser's forward model is slower on the thin
layers the chains visit.

The number was then chosen by what more samples buy. Rokel A sampled
with five seeds at each of three counts, the P10 and P90 of the base of
its second layer and of the weathered zone moved across the seeds by up
to 1.0 m at 2,000 samples, 0.7 m at 4,000 and 0.9 m at 8,000, and the
P90 of the half-space resistivity (about 60 ohm-m) by 12.3, 8.6 and 8.5
ohm-m. Past 4,000 the spread is the chains settling in different
equivalent models, not too few samples in each, and doubling the count
doubles the wait without narrowing it. So the default is 4,000, with
500 burn-in steps a chain: about 5 s a sounding here, and a few times
that on a field laptop, which the worker and its progress bar carry.

## The cost distribution: why 20,000 samples

PLAN.md step 3.4 asks for the default sample count to be set from a
measured timing. On 10 October 2026, on this repository's 4-CPU machine
(load average 0.6), a 40 m borehole 100 km from the base with its depth
drawn from the Rokel-shaped quantiles the parity reference uses (24 to
41 m) and a 60 percent chance of water was sampled with ten seeds at
each count, one numpy thread. The spread of each figure across the
seeds (greatest less least, as a share of their mean), and the median
of three runs:

| samples | one borehole | programme of ten | P50 | P80 | per working borehole | programme P80 |
|---|---|---|---|---|---|---|
| 2,000 | 39 ms | 42 ms | 0.41% | 0.53% | 0.38% | 1.31% |
| 5,000 | 100 ms | 108 ms | 0.20% | 0.24% | 0.21% | 0.64% |
| 10,000 | 222 ms | 211 ms | 0.21% | 0.17% | 0.15% | 0.70% |
| 20,000 | 405 ms | 442 ms | 0.11% | 0.11% | 0.07% | 0.41% |
| 40,000 | 845 ms | 905 ms | 0.07% | 0.04% | 0.06% | 0.24% |

P50 and P80 settle by a few thousand samples. The expected cost per
working borehole is worked out from the mean completed borehole and the
mean dry attempt, so it is as steady as they are. It was first taken as
all that the sampled attempts spent over the ones that found water,
which moved by 0.9 percent from seed to seed here at 20,000 samples,
1.5 percent at a 30 percent chance and 6.7 percent at 5 percent, where
it also came out 1.7 percent low. The noisy figure is the programme's
P80, which turns on how many dry attempts were drawn. At 20,000 every
figure moves by under half a percent from one seed to the next, for
about 0.4 s in Python each time an estimate is made; doubling it buys a
few hundredths of a percent for twice the wait. In the browser engine,
headless Chromium, the same 20,000 took 33 ms and 25 ms (median of
five), and 90 to 103 ms and 113 to 119 ms with the CPU slowed four
times, over two runs. `run.py --only cost` times the default on the Dr
Timbo design (`cost/*` above).

## Reading an elevation model: what a window costs

PLAN.md step 4.1 reads an operator's GeoTIFF a window at a time. On 12
October 2026, on this repository's 4-CPU machine (Xeon at 2.1 GHz, load
average 1.3 to 1.5, numpy 2.4.6), `run.py --only terrain` gave, median
of five:

| measure | median | IQR |
|---|---|---|
| read a window, DEFLATE GLO-30 layout | 202 ms | 21 ms |
| read a window, LZW 512 tiles | 403 ms | 62 ms |
| read a window, LZW 512 tiles, loop decoder | 2.22 s | 91 ms |
| read a whole DEFLATE tile | 672 ms | 34 ms |

The window is the default the terrain analysis reads: a 10 km radius
shown and the 5 km margin around it, 983 by 979 cells at 1 arc-second.
The DEFLATE window decodes four 1024-square tiles (4.2 million samples)
and the LZW window nine 512-square tiles (2.4 million), so the two do
not decode the same number of cells: per sample, LZW costs about three
and a half times what DEFLATE with the floating-point predictor does,
because zlib inflates in C and the LZW decoder is numpy. Decoding LZW a
Clear segment at a time, rather than one code at a time as the 40-line
loop it is tested against does, makes the LZW read 5.5 times quicker.
The browser engine's reads are not timed on their own: `web.mjs` drives
the app, and times a press of *Analyse the terrain* whole, the read
included (below).

On the same day `web.mjs` measured what the reader costs the browser
app before anyone uses it: `gwt-core.js` grew from 1.06 MB to 1.18 MB
with the codecs, the GeoTIFF reader and the elevation layer, and time to
interactive on the throttled profile went from 11.11 s to 11.84 s
(median of three cold loads each, the commit before the step and the
step's last commit), first contentful paint staying at 2.4 s.

## The terrain analysis: why 2,000,000 cells

PLAN.md step 4.1 caps the cells the terrain analysis takes, the margin
included, at `terrain.max_cells`: one limit in every runtime, so that
whether a window is refused does not depend on where the engine ran. At
2,000,000 cells, asked for more, the planner offers 16.5 km on the
bench's tile: with the 5 km margin, 1407 by 1401 cells at 1 arc-second,
1,971,207. The value was committed as provisional, to be confirmed here
by this rule, on the bench machine:

- `terrain/analyse at the cap` (`run.py --only terrain`) has a median of
  at most 6.0 s;
- a whole press of *Analyse the terrain* at that radius in the running
  Streamlit app, the read, the analysis and the four figures with their
  downloads, raises the server process to at most 690 MB, the least
  memory Streamlit Community Cloud gives an app: a first press in a
  server just started, and a second press, from another session, in the
  same server.

If either fails, `max_cells` comes down in steps of 250,000 until both
hold, and the changelog says so. Only `defaults.json`, `gwt-data.js` and
the reason beside `max_cells` in `config.py` change: every parity case
and test of the cap passes its own `max_cells`, so nothing in
`reference.json` moves.

Until 13 October 2026 the second rule counted the analysis alone: the
peak increase `bench/terrain_memory.py` gives, plus the app's idle
resident set. That left out the figures, which the Topography tab draws
while it holds the analysis, and what the server keeps from one press to
the next, so the press is now measured whole, in the server. Start the
app with `streamlit run app/streamlit_app.py`, open Site maps and its
Topography tab, upload the tile `python bench/terrain_memory.py
--write-tile PATH` writes, and set the radius. Just before pressing
*Analyse the terrain*, write 5 to `/proc/PID/clear_refs` for the
Streamlit process, which resets its high-water mark to its resident set;
once the figures and the GeoJSON download are shown, `VmHWM` in
`/proc/PID/status` is the press's peak. For the second press, open the
app in another browser, a new session, on the same server, and do the
same. MB in these Streamlit figures are 10^6 bytes, so 690 MB is 658
MiB; `/proc` counts in units of 1024 bytes.

Taken on 12 October 2026 on this repository's 4-CPU machine (Xeon at
2.1 GHz, Python 3.13.16, numpy 2.4.6, scipy 1.17.1, load average 0.7 to
0.9), `run.py --only terrain`, median of five:

| measure | median | IQR |
|---|---|---|
| analyse the default window | 1.39 s | 44 ms |
| analyse at the cap | 2.79 s | 540 ms |
| trace drainage lines from the core | 53 ms | 3 ms |

The spread at the cap comes from two slower samples (3.84 and 3.33 s);
the other three lie between 2.60 and 2.79 s. The time holds.

The analysis alone, as the rule counted it then: `terrain_memory.py` at
the cap, three runs, gave `increase_mb` 279, 270 and 272, with `read_mb`
14 to 33 and `first_use_mb` 52 to 70 beside it (MB of 2^20 bytes, as
that script counts them), and the app's idle resident set with Site
maps loaded was 159 MB (163,276 kB by `/proc`'s VmRSS) the same day:
279 + 159 = 438 MB, and 523 MB with the modules the analysis loads on
first use and the read's bytes counted too. On those figures 2,000,000
cells was kept on 12 October.

The whole press was measured on 13 October 2026 on the same machine
(Streamlit 1.64.0, load average 0.4 to 1.6), driven headless by
Playwright, a scratch script that is not committed, with a fresh server
for each case and each press in a fresh browser. The server idled at
167 to 168 MB with Site maps loaded (20 servers), and stood at about 225
MB just before a first press, the tile uploaded. Each press's peak:

| radius (cells analysed) | first press | second press, after one at the same radius | second press, after one at 10 km |
|---|---|---|---|
| 10 km (962,357) | 409 to 416 MB (8 servers) | 494, 532 MB | the column before |
| 13.6 km (1,478,647) | 535 to 543 MB (4) | 630 to 669 MB (4) | 600, 660 MB |
| 15.1 km (1,726,587) | 610, 643 MB | 677, 678 MB | 706, 751 MB |
| 16.5 km (1,971,207) | 679 to 729 MB (6) | 747 to 772 MB (3) | 748, 779 MB |

A first press took about 7 s at 10 km and 13 to 18 s at the cap, from
the click to the GeoJSON download. **So the rule fails at 2,000,000
cells.** A first press at the cap stayed under 690 MB in three of six
fresh servers (679, 688 and 688 MB) and went over it in the other three
(716, 728 and 729 MB), and every second press at the cap went over it.
The analysis is not all of it: the figures are drawn while it is held,
and the server ends a press 30 to 90 MB above where it began, which it
keeps. A second session's upload adds about 55 MB to that, so a second
press starts from 312 to 368 MB rather than 225. Two presses at 13.6 km
left the idle server at 372 to 387 MB for the next three and a half
minutes, and each further press in the same server started higher: four
at the cap peaked at 729, 755, 831 and 914 MB, and four at 13.6 km at
535, 630, 680 and 694 MB.

By the rule's own steps, the planner offers 15.1 km at 1,750,000 cells,
where a second press after one at 10 km reached 706 and 751 MB, and
13.6 km at 1,500,000, where every first press (535 to 543 MB) and second
press (600 to 669 MB) measured stayed under 690 MB. **A whole press, the
second included, fits at 1,500,000 cells, 13.6 km.** Read as 690 MiB,
the verdict is the same: 690 MiB is 724 MB, and two of the six first
presses at the cap, every second press there, and a second press at
15.1 km after one at 10 km (751 MB) went over it. `max_cells` is not
changed here; it stays provisional, for the owner to decide.

The synthetic tile looks like ground, which is the easy case. Surfaces
built to be hard, each 1414 by 1414 cells (1,999,396, just under the cap),
were measured on 12 October with the analysis alone, as `terrain_memory.py`
does (a warm-up first, the peak increase over the window held), with the
code as part b merged it, while another test run shared the machine: a
channel winding through the whole window behind walls took 2.99 s and
+304 MB; a plane tilted evenly to the south, nearly every cell of which
is on a drainage line, 1.88 s and +308 MB; a channel in lanes that turns
at every cell, 2.51 s and +435 MB; and ground dead flat, 4.27 s and +320
MB (MB of 2^20 bytes). Before the part b review the first two took 27.2
s and 5.6 s, and raised the peak by 731 MB and 692 MB. Those surfaces
were not pressed in the app; their analysis alone takes up to 156 MB
more than the synthetic tile's 279 MB, so a whole press on them would
take more than the table above. The time is well under 6.0 s on every
one.

The cap is one number for every runtime, so a slower runtime makes a
long wait, not a different answer. The browser app was timed with the
page part c adds on 13 October 2026, on the same machine (Chromium 141,
load average 0.2 to 1.7 while the runs went on): `web.mjs --only
terrain` three times, three presses at each size in each, each press in
a fresh browser, on the synthetic tile, and the median of the nine. MB
from here on are 10^6 bytes, as `web.mjs` and `run.py` print them.

| measure | median | IQR |
|---|---|---|
| terrain default window wall time, worker | 2.97 s | 0.44 s |
| terrain default window longest main-thread task, worker | 0.57 s | 0.18 s |
| terrain default window memory added, worker | 232 MB | 10 MB |
| terrain window at the cap wall time, worker | 5.12 s | 0.68 s |
| terrain window at the cap longest main-thread task, worker | 0.50 s | 0.04 s |
| terrain window at the cap memory added, worker | 432 MB | 9 MB |
| terrain default window wall time, on the page (CPU 4x) | 12.17 s | 0.83 s |
| terrain window at the cap wall time, on the page (CPU 4x) | 19.63 s | 1.68 s |

A press is timed whole. Where its time goes was read once from the
engine's own record of its requests (a scratch run, two presses at each
size, not part of `web.mjs`): the page planned the window and read the
blocks out of the file in about 0.13 s from the click, the worker read
the window in 0.44 to 0.57 s and analysed it in 1.21 to 1.27 s at the
default window and 3.20 s at the cap, and the figures were drawn in
about half a second after its answer: that drawing is the longest
main-thread task above. So the browser's analysis at the cap takes a
little longer than CPython's 2.79 s, and a press there 5.1 s from click
to figures, with the bar and its Cancel on the page throughout. On the
page, at a quarter of the speed, the press holds the page for 12.2 s at
the default and 19.6 s at the cap.

The memory is the page and its worker together, and is more than the
design's estimate (80 to 90 MB in the worker at the default window, 150
to 250 MB at the cap), which was scaled from the routing alone. Where it
goes was read against the engine's record of its requests, with the
renderer's resident set sampled every 4 ms (a scratch run, three presses
at each size with the worker stopped and three with it kept, not part
of `web.mjs`). The worker holds the grid and the analysis's layers while
it works (those only drawn in float32, as in Python, the rest in
float64), and the peak comes as it finishes: at the default window as
its answer reaches the page, at the cap a little before. The worker is
then stopped, and the next press starts a fresh one. The page draws the figures at 95 to 165 MB above where the press
began, keeps 90 to 140 MB for the next twenty seconds, and 40 to 55 MB
once its own garbage is collected, about thirty seconds on: the blocks
read, the layers handed back for drawing, the full-size core it traces
new thresholds from, and the figures.

Before the worker was stopped, it kept its finished analysis as garbage
it had no reason to collect while idle. The peak then came after the
answer, while the page drew the figures, and the tab held 250 to 275 MB
at the default window and 405 to 455 MB at the cap for twenty seconds,
still 185 to 380 MB at thirty, until a collection forced in the worker
alone brought it to 50 to 75 MB. Timed beside the branch on the same day
with the stop taken out, alternated with it, three runs of `web.mjs`
each, that version's memory added was 314 MB at the default window and
482 MB at the cap (median of nine; IQR 15 and 33 MB). Stopping the
worker takes 82 MB, a quarter, off the default window's peak and 50 MB
off the cap's, and changes no time beyond its spread. A device that
reports 2 GB of memory or less is asked before it analyses more than
1,000,000 cells, so above the default window; the default window itself
adds about 230 MB to the tab at its peak, and the tab keeps about 100 MB
of that until its garbage is collected.

An ad hoc Pyodide run, labelled as such: not part of `web.mjs`, run once
by hand on the pattern of `spikes/pyodide-engine/measure.mjs`, its
scripts not committed. Pyodide 0.29.3 (Python 3.13.2, numpy 2.2.5, scipy
1.14.1, what the Streamlit demo ships), in a Web Worker in the same
headless Chromium, with the package's terrain modules and the synthetic
tile on its file system, read the window and ran `analyse_terrain` on it
as `run.py` does (float32), three times after a 1 km warm-up, in a
fresh browser for each window, twice. The analysis took 1.90 s at the
default window (median of six, 1.76 to 2.34 s) and 4.09 s at the cap
(3.90 to 5.49 s, the first of each three the slowest), and the read 0.24
to 0.37 s. Its WebAssembly memory, which only grows, went from 201 MB
with the window at the cap read to 417 MB after the analyses (168 to
290 MB at the default). So Pyodide analyses the window at the cap in
about one and a half times CPython's time, under the 6.0 s CPython is
held to.

On the same day `web.mjs` measured what part c's page costs the app
before anyone uses it. Its scripts grew by 67 KB: `gwt-app.js` from 353
to 381 KB, `gwt-charts.js` from 263 to 292 KB and `gwt-worker.js` from
21 to 28 KB, `gwt-core.js` by 1,855 bytes, the catalogue in `gwt-data.js`
by 748 and `gwt-docx.js` by 37. Time to interactive on the throttled
profile went from 12.40 s to 12.58 s, first contentful paint stayed at
2.5 s (2.46 s before, 2.46 and 2.48 s after), and the bytes before first paint from 98,610 to
105,486 (the larger worker script; median of three cold loads each, the
commit before part c, `plan/4.1c-base`, once, and part c's last twice,
back to back). The 11.84 s above was taken on another day, before part
b's analysis joined `gwt-core.js`, and is not to be compared with these.

## The committed baseline

`bench/baseline.json` is committed with each release (PLAN.md step
0.3: "Commit `bench/baseline.json` with each release"), taken on a
quiet machine at the release commit, so that the next release's
efficiency work has a before to quote. Its `notes` field says under
what conditions it was taken; a baseline marked provisional was taken
on a busy machine and is for orientation, not for quoting.

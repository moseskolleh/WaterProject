# 0001: One engine or two

- **Status:** decided, 3 October 2026 (PLAN.md step 1.10).
- **Decision:** keep two engines. The browser app keeps `docs/js/gwt-core.js`;
  steps 1.7 and 1.8 stay the safety net, and the stage 3 samplers are written
  as small, parity-tested cores in both engines.
- **Final or provisional:** final for the question the plan asked, with the
  runtime it asked about (Pyodide with numpy and scipy, as shipped). It does
  not wait on the phone measurement. The start threshold fails on a
  server-class CPU, and a low-end phone will not start Pyodide faster than
  that. The section "What would reopen it" names the result that would.
- **Evidence:** `spikes/pyodide-engine/` (the spike, its README and
  `results.json`, the raw run quoted below).

## The question

Stage 3 adds sampling methods (a range of VES models, the spread of a
pumping test's answer, the chance of a working borehole) that are expensive
to write twice, once in
`src/groundwater` and once in `gwt-core.js`. Before writing them, PLAN.md
step 1.10 asks whether the Python package can be the browser's engine too:
Pyodide inside the step 1.2 worker, numpy and scipy loaded, charts and
`.docx` left in JavaScript.

## The thresholds, as the plan fixed them beforehand

1. At most **25 MB** precached, once.
2. A warm start under **4 s**.
3. Inversion no more than **twice as slow** as today's JavaScript.

If all three were met, the science functions in `gwt-core.js` would be
retired page by page; if not, two engines stay.

## Method

The spike runs the VES page's computation: `invert_sounding` and
`interpret_model` on the two soundings of the Rokel sample (`A (1)` and
`B (2)`, 18 readings each), with the default configuration. The page reads
the workbook with the app's own reader, as the app does, and sends each
sounding to a worker. `spikes/pyodide-engine/pyodide-worker.js` is a variant
of `gwt-worker.js` with the same message protocol. It loads Pyodide 0.29.3
(Python 3.13.2, numpy 2.2.5, scipy 1.14.1), which is what the stlite pin in
`web/build_demo.py` defaults to, and the 17 files of the package that the
computation touches, found with an audit hook. It has to load PyYAML as well
as numpy and scipy (117 KB), because `import groundwater` imports
`project.py`, which imports `yaml`. No matplotlib, openpyxl or python-docx
is loaded: step 0.1's lazy imports keep them out.

`spikes/pyodide-engine/measure.mjs` drives headless Chromium 141 through
Playwright on this machine: 4 CPUs (Intel Xeon, 2.80 GHz), nothing else
running (load average 0.58 before the run, 1.04 after, from the run itself).
There were five repetitions, each in a fresh browser profile. A service
worker precaches every file the Pyodide worker fetches. Then the local
server drops every connection, and Chromium cannot resolve any other host,
so every start below reads its files from Cache Storage, as an installed app
with no signal would. The JavaScript engine (`gwt-worker.js`) is timed in
the same pages. Figures are medians of the five, with the range.

- **Bytes to precache** is the sum of the files the Pyodide worker fetched,
  checked against what the service worker then held. Compressed sizes are
  gzip -9 and brotli 11 of the same files, computed in the driver.
- **Start** is the time from `new Worker()` to the worker's ready message, on
  the page's clock. In the **cold** run, the profile has just precached and
  has never started Pyodide. **Reload** reloads the page in the same browser.
  **Restart** closes the browser and reopens it on the same profile, offline,
  which is a field device's first start of the day.
- **Inversion** is the task's own time in the worker (for Pyodide,
  `invert_sounding` timed inside Python; with `interpret_model` and the JSON
  both ways it is 1 to 3 ms more). Each engine inverts both soundings twice
  in each run, so the second call is a warm inversion with Pyodide already up.
- **4x CPU** applies DevTools' `Emulation.setCPUThrottlingRate`, rate 4.
  Chromium does not apply it to a worker. The run checks this: the JavaScript
  worker took 2,087 ms on `A (1)` with its page throttled 4x and 2,068 ms
  without. So the throttled figures run both engines on the page's own
  thread.
- **Memory** is the largest peak resident set (`VmHWM`) of any Chromium
  renderer, with one engine alone in a fresh browser, plus Pyodide's
  WebAssembly heap size.
  `performance.measureUserAgentSpecificMemory` refused to run in this
  headless Chromium although the page was cross-origin isolated.
- **Native** is `spikes/pyodide-engine/engine.py` under CPython 3.11 (numpy
  2.4.6, scipy 1.17.1), with one BLAS thread as `bench/run.py` holds it.

## The numbers

| Measure | Threshold | JavaScript today | Pyodide | Verdict |
|---|---|---|---|---|
| Precached, as stored | 25 MB | 2.9 MB, the whole app | **30.9 MB** (29.5 MiB) | fails |
| Precached, as sent with brotli 11 (gzip -9) | | | 23.2 MB (24.0 MB) | passes, only if the host compresses |
| Warm start, restart offline | 4 s | 40 ms (38-44) | **6.41 s** (6.34-6.90) | fails |
| Warm start, reload | 4 s | 44 ms (38-67) | **6.49 s** (6.17-6.89) | fails |
| Cold start, first after precache | | 39 ms (37-43) | 6.83 s (6.75-7.06) | |
| Inversion `A (1)`, first call | 2x | 2,076 ms | 3,195 ms | 1.54x, passes |
| Inversion `B (2)`, first call | 2x | 1,496 ms | 2,498 ms | 1.67x, passes |
| Inversion `A (1)`, again | 2x | 2,045 ms | 2,988 ms | 1.46x, passes |
| Inversion `B (2)`, again | 2x | 1,481 ms | 2,426 ms | 1.64x, passes |
| Inversion on the page, 4x CPU, `A (1)` / `B (2)` | 2x | 9,775 / 7,376 ms | 16,727 / 13,729 ms | 1.71x / 1.86x, passes |
| Start on the page, 4x CPU, warm / cold | | | 35.2 s / 35.1 s | |
| Renderer peak resident memory | | 127 MB (123-127) | 476 MB (470-482) | |
| WebAssembly heap | | | 97 MB (97-109) | |

The precache is ten files. The scipy wheel is 13.3 MB, `pyodide.asm.wasm`
8.6 MB (2.1 MB with brotli), the numpy wheel 3.1 MB, the standard library
2.4 MB, libopenblas 2.1 MB and `pyodide.asm.js` 1.1 MB. The rest, the
package archive included (59 KB), is under 0.3 MB. The wheels and zips are
already compressed, so 21 MB of the 23.2 MB sent is incompressible. The app
fetches nothing else on top of its current 2.9 MB precache. The archive is
15 bytes larger as committed (58,821) than as measured (58,806), because
`engine.py`'s command-line reader was changed for lint after the run; the
code the worker runs is the same.

Where a Pyodide start goes, as the median over all fifteen worker starts:

| Phase | ms |
|---|---|
| the runtime (`loadPyodide`) | 1,874 |
| loading the numpy, scipy, libopenblas and PyYAML wheels, their shared libraries included | 2,593 |
| `import numpy` | 510 |
| `import scipy.special` | 1,308 |
| unpacking and importing the package | 218 |

A start with numpy alone, which cannot invert, took 2.85 s (2.83-2.93).
The other 3.6 s of the 6.4 s is scipy, PyYAML and the package, and the
package's own share is 0.2 s. The package uses scipy for three Bessel
functions, `j0`, `j1` and `jn_zeros`, in `ves/forward.py`.

The native package inverts `A (1)` in 925 ms and `B (2)` in 846 ms. On
this machine Pyodide is 3.0x to 3.5x slower than CPython, and `gwt-core.js`
1.8x to 2.2x slower.

**Agreement.** All 100 Pyodide answers (5 runs x 2 soundings x 2 calls, in
three worker starts and on the page at two speeds) agree with native CPython
and with `tests/webapp/reference.json`, at the tolerances `parity.mjs` uses:
model resistivities and thicknesses to 1e-3 relative, misfit to 1e-4,
confidence to 1e-6, and zones, depths, flags, fit quality and narrative word
for word. The largest relative difference from CPython anywhere in a model
is 9.2e-9, and every Pyodide run gave bit-identical models. The 100
`gwt-core.js` answers agree as well, to within 3.3e-7. As expected, the
package gives the package's answer under Pyodide.

## What could not be measured here

- **A low-end Android phone and a field laptop.** The plan asks for both, and
  neither was available. Every number above is from one 4-CPU server-class
  machine with fast storage and plenty of memory.
- **What the 4x proxy tells, and what it does not.** It runs both engines on
  a page thread that DevTools slows fourfold. It shows that the inversion
  ratio holds up when every instruction costs more: 1.7x to 1.9x, against
  1.5x to 1.7x unthrottled. It shows that a start dominated by interpreter
  work grows with the CPU: 6.5 s became 35 s. It leaves out the WebAssembly
  compilation Chromium does on background threads, storage speed, memory
  bandwidth and memory pressure. A phone is also not this laptop at a quarter
  of the speed: on a 2 GB or 3 GB device, a tab that peaks at 476 MB, against
  127 MB today, may be killed in the background. That is a risk the proxy
  cannot see.
- **Other browsers.** Only Chromium was run, not Firefox or Safari (iOS
  WebKit is the browser on every iPhone).
- **A cold download over a field network.** The plan asks for the starts
  "once the files are precached", and that is what was measured. Filling the
  precache once means 23 to 31 MB over the network, against 2.9 MB today.

## The decision

Two engines. On the numbers measured, the spike meets the inversion
threshold with room to spare (1.46x to 1.67x in the worker) and fails the
other two. It fails the warm start by 60 percent (6.4 s against 4 s) and
fails the precache by 24 percent as stored (30.9 MB against 25 MB). It meets
the precache only as compressed bytes on the wire, by 1.8 MB, and only from a
host that compresses WebAssembly. Each failure on its own decides it, under
the rule the plan wrote down beforehand.

So nothing is retired. `gwt-core.js` stays the browser's engine, parity and
the step 1.8 fuzzing stay the guarantee that the two agree, and the stage 3
samplers are written as small cores in both engines with parity tests, as
the plan's fallback says. This step changes no code in either app.

## Why the phone measurement would not change it

A low-end Android phone will start Pyodide more slowly than this machine,
not faster. The start that fails here took 6.4 s on a CPU that runs the
JavaScript inversion in 2 s, and the 4x proxy put it at 35 s. No phone result
can bring that under 4 s, so the decision does not wait on one. To pass, a
field laptop would need to run a single thread more than 1.6 times as fast
as this 2.8 GHz server core. A recent high-end laptop might do that; the
laptops the toolkit is used on are not those, and a decision that holds only
on the best machine in the programme does not serve the rest. The phone and
field-laptop measurement is still worth taking: it would show how slow
today's JavaScript engine is there, which is the number the stage 3
samplers' budget needs. The spike's driver and README say how to re-run it
against a real device.

## What would reopen it

A change to the runtime rather than to the device. That would need a warm
start under about 1 s on this machine, so that a device four times slower
stays near the 4 s threshold, and a precache under 25 MB as stored. Three
routes were not tried, because the spike was time-boxed:

- a forward model that does not need scipy. A numpy-only start took 2.85 s
  here, and dropping scipy also drops 15.4 MB of the precache;
- Pyodide's experimental memory snapshots, which restore an interpreter with
  its imports already done;
- a scipy built with `scipy.special` alone.

None of them reaches 1 s on the numbers above without the snapshots. If a
later Pyodide makes that possible, re-run `spikes/pyodide-engine/` against
the same thresholds, on a phone as well as here.

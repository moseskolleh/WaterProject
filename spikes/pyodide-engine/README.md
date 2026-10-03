# Spike: the Python package as the browser's engine (PLAN.md step 1.10)

A time-boxed spike, not part of either app. It runs the VES page's
computation - `invert_sounding` and `interpret_model` on the two Rokel
soundings - through Pyodide in a Web Worker, and times it against the
JavaScript engine the browser app ships (`docs/js/gwt-worker.js` and
`gwt-core.js`). The numbers and the decision taken from them are in
[`docs/decisions/0001-engine.md`](../../docs/decisions/0001-engine.md).

It lives here, not under `docs/`, so that nothing in it is published with
the app, precached by its service worker, or checked by `nox -s js` as app
code, and not under `src/` or `web/`, so that it never reaches the wheel
or the stlite demo. `bench/` is for numbers the project re-takes at each
release; this is a one-off measurement, kept so that it can be re-run on a
phone or a field laptop.

## Running it

```bash
python spikes/pyodide-engine/build.py           # fetches the 392 MB tarball
python spikes/pyodide-engine/build.py --tarball ~/Downloads/pyodide-0.29.3.tar.bz2
node spikes/pyodide-engine/measure.mjs --reps 5   # about 40 minutes here
python spikes/pyodide-engine/summarize.py         # the numbers, from results.json
```

`build.py` writes `vendor/` (ignored by git): the Pyodide 0.29.3 runtime
and the four packages the computation loads (numpy, scipy, libopenblas and
PyYAML), taken from the release tarball on GitHub and checked against the SHA-256 it was measured with, and
`groundwater-ves.zip`, the 17 files of the package the computation touches.
Those are found by running it under CPython with an audit hook, not listed
by hand. Pyodide 0.29.3 is the version `web/build_demo.py`'s stlite pin
defaults to, so this measures the Python 3.13, numpy 2.2.5 and scipy 1.14.1
the Streamlit demo already ships. The tarball comes from GitHub releases
because `cdn.jsdelivr.net` was blocked on the machine this was measured on.

`measure.mjs` serves `docs/` at `/app/` and this folder at `/spike/` from
one local server and drives `bench.html` in headless Chromium (Playwright,
as the web tests use). `results.json` is the run quoted in the decision
record.

## The files

- `engine.py` - the whole interface: a sounding as the browser engine holds
  it in, `VESSounding` built from it, `invert_sounding`, `interpret_model`,
  JSON out with the fields `tests/webapp/parity.mjs` compares. The same
  file runs under CPython for the native times.
- `pyodide-worker.js` - a variant of `gwt-worker.js`: the same
  `{id, type, payload}` protocol, an `invert` task that answers with the
  model and its interpretation. Loaded on a page instead, it defines
  `PyEngine`, the same steps on the page's thread, for the throttled runs.
  It sends no progress; the JavaScript engine reports each iteration.
- `sw.js` - a precache like the app's: `addAll` at install, cache first.
- `bench.html` - reads the Rokel workbook with the app's own reader and
  offers the driver its calls; draws nothing.
- `measure.mjs`, `summarize.py` - the driver and the report.

## What it measures, and how

Each repetition starts from a fresh browser profile. The spike's service
worker precaches every file the Pyodide worker fetches; then the server
drops every connection, and Chromium cannot resolve any other host
(`--host-resolver-rules`), so what follows reads only from Cache Storage:

- **cold**: the first Pyodide start this profile has seen, precached,
  nothing compiled;
- **reload**: the page reloaded in the same browser;
- **restart**: the browser closed and reopened on the same profile,
  offline, which is a field device's first start of the day;
- each engine inverts both soundings twice in each, so the second call
  is the warm inversion with Pyodide already up;
- **page 1x / page 4x**: the same work on the page's own thread, with
  DevTools' CPU throttling off and at 4x.

The start is `new Worker()` to the worker's ready message, on the page's
clock; the worker also reports where the time went. Inversion time is the
task's own time in the worker (and `invert_sounding` alone, timed inside
Python). Each run's answers are compared with CPython's, and with
`tests/webapp/reference.json`, at parity's tolerances.

**The 4x figures are a proxy, and a weak one.** Chromium refuses to throttle
a worker, and the run checks this: the JavaScript worker takes the same
time with its page throttled 4x as without. So the throttled numbers come
from running both engines on the page's own thread. That slows the
JavaScript and the Python interpreter alike, but not the WebAssembly
compilation Chromium does on background threads, nor memory bandwidth,
nor the file reads, and a phone is not a laptop at a quarter of the speed:
it has less memory, slower storage and a different CPU. They say how the
two engines compare when every instruction costs four times as much; they
do not say what a phone does.

**Memory** is the largest peak resident set (`VmHWM`) of any Chromium
renderer, with one engine alone in a fresh browser, and for Pyodide the size
of its WebAssembly heap, which only grows. `measureUserAgentSpecificMemory`
refused to run ("not available") in the headless Chromium Playwright drives
here, although the page is cross-origin isolated; the reason was not
chased, and the driver records the refusal.

## What it does not do

It does not change either app, retire any JavaScript, or try to make
Pyodide start faster (Pyodide's experimental memory snapshots, a scipy built
with only `scipy.special`, or the package without scipy). It does not
measure a phone or a field laptop; the decision record says what that
leaves open.

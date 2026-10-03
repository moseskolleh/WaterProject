/* pyodide-worker.js - the VES computation in Python, in the browser (spike).
 *
 * A variant of docs/js/gwt-worker.js for PLAN.md step 1.10. It answers the
 * same message protocol - {id, type, payload} in, {id, result | error, ran}
 * out, and {ready: true} once it can take work - but its invert task runs the
 * package's own invert_sounding and interpret_model under Pyodide, with only
 * numpy, scipy and PyYAML loaded. Charts, documents and the workbook reader
 * stay in JavaScript; the page reads the sheet and sends the sounding.
 *
 * Like gwt-worker.js it is loaded two ways:
 *
 *   - as a Web Worker, it starts Pyodide at once and answers requests;
 *   - on a page, it defines PyEngine (start, invert), which runs the same
 *     steps on the page's own thread. The driver uses that to time the
 *     engine under DevTools' CPU throttling, which Chromium applies to a
 *     page and refuses to apply to a worker.
 *
 * It is not part of the app and nothing in docs/ loads it.
 */
(function (global) {
  'use strict';

  var IN_WORKER = typeof document === 'undefined' &&
    typeof global.importScripts === 'function';

  /* Where the runtime and the package archive are served from, relative to
   * this script: spikes/pyodide-engine/vendor/, which build.py writes. */
  var BASE = new URL('vendor/', (IN_WORKER ? global.location.href
    : (document.currentScript && document.currentScript.src) || global.location.href)).href;

  /* A worker named 'numpy-only' starts the runtime with numpy and nothing else, and
   * cannot invert: the driver times it to show what a start would cost if
   * the package did not need scipy (it needs it for three Bessel functions,
   * j0, j1 and jn_zeros, in ves/forward.py). The name, not the URL: a
   * response from Cache Storage carries the URL it was stored under, so a
   * fragment or query on the worker's URL does not reach it. */
  var NUMPY_ONLY = IN_WORKER && global.name === 'numpy-only';
  var PACKAGES = NUMPY_ONLY ? ['numpy'] : ['numpy', 'scipy', 'pyyaml'];
  var SITE = '/home/pyodide/gw';

  function now() { return global.performance.now(); }

  /* Start Pyodide, load the wheels, unpack the package and import the
   * modules the computation needs. Each phase is timed on this thread's
   * clock, so the driver can say where a start's time went. */
  async function start() {
    var phases = {};
    var t = now();
    if (typeof global.loadPyodide !== 'function') {
      if (IN_WORKER) {
        global.importScripts(BASE + 'pyodide/pyodide.js');
      } else {
        await new Promise(function (resolve, reject) {
          var s = document.createElement('script');
          s.src = BASE + 'pyodide/pyodide.js';
          s.onload = resolve;
          s.onerror = function () { reject(new Error('pyodide.js did not load')); };
          document.head.appendChild(s);
        });
      }
    }
    phases.script = now() - t;

    t = now();
    /* indexURL is where the lock file and every wheel are fetched from too,
     * so nothing reaches for a CDN */
    var pyodide = await global.loadPyodide({ indexURL: BASE + 'pyodide/' });
    phases.runtime = now() - t;

    t = now();
    await pyodide.loadPackage(PACKAGES, { messageCallback: function () {} });
    phases.packages = now() - t;

    /* The first imports are where numpy and scipy.special initialise, so
     * they are timed apart from the package's own. */
    t = now();
    pyodide.runPython('import numpy');
    phases.import_numpy = now() - t;

    if (NUMPY_ONLY) {
      return { phases: phases, versions: null,
        invert: function () { throw new Error('started with numpy only'); },
        heapBytes: function () { return pyodide._module.HEAPU8.buffer.byteLength; } };
    }

    t = now();
    pyodide.runPython('import scipy.special');
    phases.import_scipy_special = now() - t;

    t = now();
    var zip = await (await global.fetch(BASE + 'groundwater-ves.zip')).arrayBuffer();
    pyodide.unpackArchive(zip, 'zip', { extractDir: SITE });
    pyodide.runPython('import sys\nsys.path.insert(0, ' + JSON.stringify(SITE) + ')\n' +
      'import engine');
    phases.import_groundwater = now() - t;

    var run = pyodide.globals.get('engine').run_json;
    return {
      pyodide: pyodide,
      phases: phases,
      versions: JSON.parse(pyodide.runPython(
        'import json, sys, numpy, scipy, yaml\n' +
        'json.dumps({"python": sys.version.split()[0], "numpy": numpy.__version__,' +
        ' "scipy": scipy.__version__, "pyyaml": yaml.__version__})')),
      /* one sounding: the inversion and its interpretation */
      invert: function (payload) {
        return JSON.parse(run(JSON.stringify({ sounding: payload.sounding,
          config: payload.config || null })));
      },
      /* the size of the WebAssembly heap, which only ever grows, so it is
       * the most the interpreter has held at once */
      heapBytes: function () {
        var m = pyodide._module;
        return (m.HEAPU8 || m.HEAP8).buffer.byteLength;
      },
    };
  }

  if (!IN_WORKER) {
    global.PyEngine = { start: start };
    return;
  }

  /* A time any thread of this page can read the same way, as gwt-worker.js
   * has it: a worker's own clock starts when the worker does. */
  function wallClock() {
    return global.performance.timeOrigin + global.performance.now();
  }

  var began = wallClock();
  var engine = null;
  var pending = [];

  function answer(request) {
    var t0 = wallClock(), reply;
    try {
      if (request.type !== 'invert') {
        throw new Error('The engine has no task called ' + request.type);
      }
      reply = { id: request.id, result: engine.invert(request.payload) };
    } catch (e) {
      reply = { id: request.id,
        error: { name: (e && e.name) || 'Error', message: String(e && e.message) } };
    }
    reply.ran = [t0, wallClock()];
    reply.heapBytes = engine.heapBytes();
    global.postMessage(reply);
  }

  global.onmessage = function (event) {
    if (engine) answer(event.data || {});
    else pending.push(event.data || {});
  };

  start().then(function (e) {
    engine = e;
    global.postMessage({ ready: true, began: began, at: wallClock(), phases: e.phases,
      versions: e.versions, heapBytes: e.heapBytes() });
    pending.splice(0).forEach(answer);
  }, function (e) {
    global.postMessage({ failed: String(e && (e.stack || e.message) || e) });
  });
}(typeof window !== 'undefined' ? window : globalThis));

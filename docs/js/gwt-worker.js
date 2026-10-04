/* gwt-worker.js - the engine's long computations, off the page's own thread.
 *
 * The VES inversion (up to three layer counts, two starting models each and
 * sixty iterations with a numerical Jacobian) and the pumping test fits used
 * to run on the page. On a field laptop the Rokel sample held the page for
 * seconds at a time: nothing drew, nothing scrolled, and there was nothing to
 * press to stop it. gwt-core.js touches no DOM, so it runs in a Web Worker as
 * it is.
 *
 * This one file is loaded twice and does a different job each time:
 *
 *   - started as a Web Worker, it imports the engine and its tables and
 *     answers its requests - invert (and the VES co-pilot's previewInvert),
 *     sampleRange, analysePumping, recompute and the pumping test co-pilot's
 *     cooperJacob - reporting progress on the way;
 *   - loaded by the page, it is GWT.engine: a promise per request, the
 *     progress passed on, cancel, and the same tasks run on the page
 *     itself where no worker can start - a copy opened from file://, which
 *     browsers refuse a worker, or a browser that fails to load one.
 *
 * Both run TASKS below on a structured clone of the request, so the answer
 * does not depend on which of them ran it.
 */
(function (global) {
  'use strict';

  /** @type {GWTNamespace} */
  var GWT = global.GWT || (global.GWT = {});
  var IN_WORKER = typeof document === 'undefined' &&
    typeof global.importScripts === 'function';

  /* Only what the tasks read: the engine, and the tables it takes from
   * GWT.data - the standards the assessment is made against, the lithology
   * crosswalk the drilling log is read with. The map layers are a bundle of
   * their own, gwt-geo.js, which the engine imports here itself the first
   * time a task reads them (GWT.loadNow). support.js belongs to the page
   * (building the DOM, and reading workbooks, which needs DOMParser) and is
   * not loaded here. */
  if (IN_WORKER) global.importScripts('gwt-data.js', 'gwt-core.js');

  function own(map, key) {
    return Object.prototype.hasOwnProperty.call(map, key);
  }

  /* The crew often writes discharge nowhere on the sheet; the value entered on
   * the Pumping test page belongs to the project, not to the file. */
  function applyManualDischarges(test, manual) {
    (test.steps || []).forEach(function (step) {
      var value = manual[step.step_number];
      if (value !== undefined && value !== null && value !== '') {
        step.discharge_m3_per_h = Number(value);
      }
    });
  }

  var TASKS = {
    /* One sounding, as C.invertSounding returns it. The page interprets the
     * model itself: the interpretation is cheap, and it keeps the model it
     * was made from as the same object the inversion result holds. */
    invert: function (payload, progress) {
      return GWT.core.invertSounding(payload.sounding,
        { config: payload.config, onProgress: progress });
    },

    /* The same inversion, for the VES co-pilot's preview. It is a task of
     * its own because cancelling works by task: the co-pilot stops its
     * preview each time a reading comes in, and the Geophysics page stops
     * its run whenever the project changes, and neither may stop the
     * other's. */
    previewInvert: function (payload, progress) {
      return GWT.core.invertSounding(payload.sounding,
        { config: payload.config, onProgress: progress });
    },

    /* The range of models that fit one sounding (PLAN.md step 3.1): a few
     * thousand forward calls and a handful of fits, seconds of work, so it
     * runs here with its progress in the work bar. A task of its own, so
     * stopping it does not stop an inversion, nor an inversion it. */
    sampleRange: function (payload, progress) {
      return GWT.core.sampleModelRange(payload.sounding, payload.inversion,
        payload.config, progress);
    },

    /* The analysis holds the test it was made from as analysis.test, and
     * clears a rate on that test it cannot use, so the caller takes the test
     * back from the analysis: the one it sent was a copy. */
    analysePumping: function (payload, progress) {
      return GWT.core.analysePumpingTest(payload.test, payload.config,
        { onProgress: progress });
    },

    /* What recompute derives from the sheets once the page has read them:
     * the soundings, the drilling log, the pumping test with the discharges
     * entered by hand, and the water quality sample with its assessment. A
     * sheet that fails is a notice and a null, as it always was, and the rest
     * still come back. They come back in one message, so an object two of
     * them share - the sample the assessment was made from - is still one
     * object at the other end. Notices are [role, message, tone]. */
    recompute: function (payload) {
      var C = GWT.core, sources = payload.sources;
      var out = { soundings: null, log: null, test: null, sample: null,
        assessment: null, notices: [] };
      if (sources.ves) {
        try {
          var skipped = [];
          out.soundings = C.readVesSheets(sources.ves.sheets, sources.ves.name, skipped);
          /* a sheet the reader could not use is named with the reason */
          out.skippedVesSheets = skipped;
          skipped.forEach(function (flag) { out.notices.push(['ves', flag.message, 'warn']); });
        } catch (e) {
          out.notices.push(['ves', 'VES sheet: ' + e.message, 'error']);
        }
      }
      if (sources.drilling) {
        try {
          out.log = C.drillingFromGrid(sources.drilling.sheets[0].rows, sources.drilling.name);
        } catch (e2) {
          out.notices.push(['drilling', 'Drilling log: ' + e2.message, 'error']);
        }
      }
      if (sources.pumping) {
        try {
          /* a Word field sheet arrives already read, since reading it needs
           * the page */
          out.test = sources.pumping.test ||
            C.pumpingFromGrid(sources.pumping.sheets[0].rows, sources.pumping.name);
          applyManualDischarges(out.test, payload.manualDischarges || {});
        } catch (e3) {
          out.notices.push(['pumping', 'Pumping sheet: ' + e3.message, 'error']);
        }
      }
      if (sources.quality) {
        try {
          out.sample = C.qualityFromGrid(sources.quality.sheets[0].rows, sources.quality.name);
          out.assessment = C.assessSample(out.sample);
        } catch (e4) {
          out.notices.push(['quality', 'Water quality sheet: ' + e4.message, 'error']);
        }
      }
      return out;
    },

    /* Cooper-Jacob lines on readings still coming in: the pumping test
     * co-pilot's live estimate, and the estimate one log cycle earlier that
     * it is judged against. Each fit is the engine's own, with its default
     * window: the same line the analysis fits to the first step once the
     * sheet is read. A fit the engine refuses comes back as its reason, not
     * as an error for the whole request. */
    cooperJacob: function (payload) {
      return payload.fits.map(function (fit) {
        try {
          return { fit: GWT.core.cooperJacob(fit.time, fit.drawdown, fit.discharge,
            payload.config) };
        } catch (e) {
          return { refused: e && e.message !== undefined ? e.message : String(e) };
        }
      });
    },
  };

  /* A time any thread of this page can read the same way: a worker's clock
   * starts when the worker does, so its own performance.now() means nothing
   * to the page. */
  function wallClock() {
    return global.performance.timeOrigin + global.performance.now();
  }

  /* An error as it can cross a postMessage: its name and its message, which
   * is what the page reads off it. */
  function errorOf(e) {
    return {
      name: (e && e.name) || 'Error',
      message: e && e.message !== undefined ? e.message : String(e),
    };
  }

  /* ================================================================ worker */

  if (IN_WORKER) {
    /* An inversion reports every iteration, and a message per iteration is
     * work for the page to read, so progress goes out at most this often. */
    var PROGRESS_MS = 80;

    var progressFor = function (id) {
      var last = -Infinity;
      return function (fraction, label) {
        var now = Date.now();
        if (now - last < PROGRESS_MS) return;
        last = now;
        global.postMessage({ id: id, progress: [fraction, label] });
      };
    };

    global.onmessage = function (event) {
      var request = event.data || {};
      var began = wallClock(), reply;
      try {
        if (!own(TASKS, request.type)) {
          throw new Error('The engine has no task called ' + request.type);
        }
        reply = { id: request.id,
          result: TASKS[request.type](request.payload, progressFor(request.id)) };
      } catch (e) {
        reply = { id: request.id, error: errorOf(e) };
      }
      /* when the task itself ran, for the page's history */
      /** @type {Record<string, any>} */ (reply).ran = [began, wallClock()];
      try {
        global.postMessage(reply);
      } catch (e2) {
        /* An answer that will not clone. Say so rather than lose it: the page
         * runs the request itself and has the answer that way. */
        global.postMessage({ id: request.id, error: errorOf(e2), uncloneable: true });
      }
    };
    global.postMessage({ ready: true });
    return;
  }

  /* ================================================================== page */

  /* The worker is this file, started from the URL the page loaded it from,
   * which is right wherever the app is served from. */
  var SCRIPT_URL = (typeof document !== 'undefined' && document.currentScript &&
    /** @type {HTMLScriptElement} */ (document.currentScript).src) || 'js/gwt-worker.js';

  /* How many finished requests history() keeps. */
  var HISTORY = 40;

  var engine = {
    worker: null,     // started with the first request, and after a cancel
    ready: false,     // it has loaded the engine and said so
    unavailable: '',  // why every request runs on the page, once one has to
    pageOnly: false,  // forcePage(true): for tests, and for debugging
    queue: [],        // requests waiting for the worker, oldest first
    running: null,    // the request the worker has
    waiting: [],      // requests waiting for a frame before running on the page
    nextId: 1,
  };
  var history = [];

  function now() {
    return global.performance ? global.performance.now() : Date.now();
  }

  function cancelled() {
    var e = new Error('Cancelled');
    e.name = 'Cancelled';
    return e;
  }

  function isCancelled(e) {
    return !!e && e.name === 'Cancelled';
  }

  /* The error a task threw, rebuilt on this side with the same name and
   * message; the page shows the message, as it did when the task ran here. */
  function rebuilt(error) {
    var e = new Error(error.message);
    e.name = error.name;
    return e;
  }

  /* Why no worker will be started, or '' if one can be. */
  function workerUnavailable() {
    if (engine.unavailable) return engine.unavailable;
    if (typeof global.Worker !== 'function') return 'this browser has no Web Workers';
    /* Chrome refuses a file:// page a worker outright and other browsers
     * treat every file as an origin of its own, so asking only logs an error */
    if (global.location && global.location.protocol === 'file:') return 'opened from file://';
    return '';
  }

  /* 'worker' or 'page': where the next request will run. */
  function mode() {
    return engine.pageOnly || workerUnavailable() ? 'page' : 'worker';
  }

  function giveUp(reason) {
    engine.unavailable = reason;
    console.warn('The engine worker is unavailable (' + reason + '); ' +
      'the page will do its own computing.');
  }

  function settle(job, outcome, error, result) {
    history.push({ id: job.id, type: job.type, mode: job.mode, start: job.start,
      end: now(), ran: job.ran || null, outcome: outcome });
    if (history.length > HISTORY) history.shift();
    if (error) job.reject(error);
    else job.resolve(result);
  }

  function request(type, payload, options) {
    var opts = options || {};
    return new Promise(function (resolve, reject) {
      var job = { id: engine.nextId++, type: type, payload: payload,
        onProgress: opts.onProgress || null, resolve: resolve, reject: reject,
        mode: '', start: now() };
      if (mode() === 'page') {
        runOnPage(job);
      } else {
        engine.queue.push(job);
        next();
      }
    });
  }

  function startWorker() {
    if (engine.worker) return engine.worker;
    if (workerUnavailable()) return null;
    var worker;
    try {
      worker = new global.Worker(SCRIPT_URL);
    } catch (e) {
      giveUp('it could not be started: ' + e.message);
      return null;
    }
    /* A worker that has been stopped can still have a message on its way;
     * only the current worker is listened to. */
    worker.onmessage = function (event) {
      if (worker === engine.worker) receive(event.data || {});
    };
    worker.onerror = function (event) {
      if (worker === engine.worker) crashed(event);
    };
    worker.onmessageerror = function () {
      if (worker === engine.worker) unreadable();
    };
    engine.worker = worker;
    engine.ready = false;
    return worker;
  }

  function stopWorker() {
    if (!engine.worker) return;
    engine.worker.terminate();
    engine.worker = null;
    engine.ready = false;
  }

  /* One request in the worker at a time. The queue is kept here rather than
   * posted ahead into the worker's own, so a request cancelled before it
   * starts is simply dropped, and stopping the one that is running loses
   * nothing that was waiting behind it. */
  function next() {
    while (!engine.running && engine.queue.length) {
      var job = engine.queue.shift();
      var worker = engine.pageOnly ? null : startWorker();
      if (!worker) {
        runOnPage(job);
        continue;
      }
      job.mode = 'worker';
      engine.running = job;
      try {
        worker.postMessage({ id: job.id, type: job.type, payload: job.payload });
      } catch (e) {
        /* a request that will not clone is run here instead */
        engine.running = null;
        runOnPage(job);
      }
    }
  }

  function receive(data) {
    if (data.ready) {
      engine.ready = true;
      return;
    }
    var job = engine.running;
    if (!job || data.id !== job.id) return;
    if (data.progress) {
      if (job.onProgress) job.onProgress(data.progress[0], data.progress[1]);
      return;
    }
    engine.running = null;
    if (data.ran) {
      var origin = global.performance.timeOrigin;
      job.ran = [data.ran[0] - origin, data.ran[1] - origin];
    }
    if (data.uncloneable) {
      console.warn('The engine worker could not send back its answer to ' +
        job.type + ' (' + data.error.message + '); working it out on the page.');
      runOnPage(job);
    } else if (data.error) {
      settle(job, 'failed', rebuilt(data.error));
    } else {
      settle(job, 'done', null, data.result);
    }
    next();
  }

  /* The worker's own failure rather than a task's: a task's errors come back
   * as answers. Before the worker has said it is ready, this is the script or
   * what it imports failing to load, and nothing will ever run there, so
   * every request from now on runs on the page. After, it is one request lost
   * with a broken worker; that one is run on the page, and the next request
   * gets a fresh worker. */
  function crashed(event) {
    if (event && event.preventDefault) event.preventDefault();
    var job = engine.running;
    var loaded = engine.ready;
    engine.running = null;
    stopWorker();
    if (!loaded) giveUp('it did not start: ' + ((event && event.message) || 'it failed to load'));
    if (job) runOnPage(job);
    next();
  }

  /* An answer that arrived and could not be read: run the request here. */
  function unreadable() {
    var job = engine.running;
    engine.running = null;
    if (job) runOnPage(job);
    next();
  }

  /* A copy of what the task is given. The worker only ever sees a copy of
   * what it is sent, so the page's run gets one too: a task that alters its
   * argument - the pumping analysis does - then alters it the same way on
   * both sides, and never the caller's own object. */
  function copy(value) {
    return typeof global.structuredClone === 'function'
      ? global.structuredClone(value) : value;
  }

  /* After the next frame, so whatever the page drew to say it is busy is on
   * screen before a task on the page stops it drawing. A hidden tab draws no
   * frames, and its work still has to get done. */
  function afterPaint(fn) {
    var done = false;
    function go() {
      if (done) return;
      done = true;
      setTimeout(fn, 0);
    }
    if (typeof global.requestAnimationFrame === 'function') {
      global.requestAnimationFrame(go);
    }
    setTimeout(go, 100);
  }

  function runOnPage(job) {
    job.mode = 'page';
    engine.waiting.push(job);
    afterPaint(function () {
      var at = engine.waiting.indexOf(job);
      if (at < 0) return;  // cancelled while it waited
      engine.waiting.splice(at, 1);
      var result, began = now();
      try {
        result = TASKS[job.type](copy(job.payload), job.onProgress);
      } catch (e) {
        job.ran = [began, now()];
        settle(job, 'failed', e);
        return;
      }
      job.ran = [began, now()];
      settle(job, 'done', null, result);
    });
  }

  /* Stop the requests of these types, running or waiting; each rejects with
   * an error named 'Cancelled'. Returns how many were stopped.
   *
   * A worker in the middle of a fit reads no messages until the fit is done,
   * so a request to stop would only be read after the answer. Stopping the
   * worker is the one cancel that works mid-iteration, and the next request
   * starts a fresh one. A task running on the page has the page to itself,
   * so a press of Cancel is read only once it returns; it stops what would
   * have come after it. */
  function cancel(types) {
    var kinds = types ? [].concat(types) : Object.keys(TASKS);
    var stopped = [];
    function keep(job) {
      if (kinds.indexOf(job.type) < 0) return true;
      stopped.push(job);
      return false;
    }
    engine.queue = engine.queue.filter(keep);
    engine.waiting = engine.waiting.filter(keep);
    if (engine.running && kinds.indexOf(engine.running.type) >= 0) {
      stopped.push(engine.running);
      engine.running = null;
      stopWorker();
    }
    stopped.forEach(function (job) { settle(job, 'cancelled', cancelled()); });
    next();
    return stopped.length;
  }

  /* Run every request on the page from now on, or go back to the worker.
   * The smoke test holds the two to the same answers with this. */
  function forcePage(on) {
    engine.pageOnly = !!on;
  }

  GWT.engine = {
    /* invertSounding for one sounding */
    invert: function (sounding, config, options) {
      return request('invert', { sounding: sounding, config: config }, options);
    },
    /* invertSounding for the VES co-pilot's preview, cancelled on its own */
    previewInvert: function (sounding, config, options) {
      return request('previewInvert', { sounding: sounding, config: config }, options);
    },
    /* sampleModelRange for one sounding and the inversion of it */
    sampleRange: function (sounding, inversion, config, options) {
      return request('sampleRange', { sounding: sounding, inversion: inversion,
        config: config }, options);
    },
    /* analysePumpingTest; the test to keep is the analysis's own .test */
    analysePumping: function (test, config, options) {
      return request('analysePumping', { test: test, config: config }, options);
    },
    /* input: { sources: {role: {name, sheets} | {name, test}},
     *          manualDischarges, config } */
    recompute: function (input, options) {
      return request('recompute', input, options);
    },
    /* fits: [{time, drawdown, discharge}]; each answer is {fit} or {refused} */
    cooperJacob: function (fits, config, options) {
      return request('cooperJacob', { fits: fits, config: config }, options);
    },
    cancel: cancel,
    isCancelled: isCancelled,
    mode: mode,
    forcePage: forcePage,
    /* Why requests run on the page, or '' while a worker can take them. */
    unavailable: function () { return engine.pageOnly ? 'forced' : workerUnavailable(); },
    /* The last requests to finish, oldest first: {id, type, mode, start, end,
     * ran, outcome}. start and end are when the page asked and had its
     * answer; ran is [from, to], when the task itself was computing, or null
     * if it never ran. All on the page's performance clock. The smoke test
     * reads its Long Tasks against the ran windows. */
    history: function () { return history.slice(); },
    TASKS: TASKS,
  };
}(typeof window !== 'undefined' ? window : globalThis));

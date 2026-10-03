/* gwt-pump-copilot.js - the pumping test co-pilot (PLAN.md step 2.1).
 *
 * The worst hydraulics findings in the roadmap all began at the well. The
 * Dr Timbo test pumped for 30 minutes, all of it inside casing storage. The
 * Kuntolo sheet recorded no discharge, and its levels sat below the pump
 * intake. None of that can be put right in the office afterwards, so this
 * page sits with the crew while the test runs:
 *
 *   - before pumping, it works out Schafer's casing-storage period for a
 *     cautious range of transmissivity and says how long the test must run;
 *   - while pumping, it keeps the log-spaced reading schedule with a
 *     countdown and a sound, plots drawdown against log time, and warns of a
 *     level at the pump intake, a discharge that drifts, and readings still
 *     inside casing storage; once out of it, it shows the engine's own
 *     Cooper-Jacob estimate and how much it is still moving;
 *   - it times the bucket, and will not write a sheet with a pumping step
 *     that has neither a discharge nor a stated reason for having none;
 *   - when the pump stops, the schedule starts again for the recovery;
 *   - at the end it writes the standard pumping test workbook, the layout
 *     src/groundwater/ingestion/templates.py writes and both engines read,
 *     so everything downstream is unchanged (PLAN.md rule 6).
 *
 * The test lives in the session under `pumpCopilot`, which gwt-store.js
 * keeps in IndexedDB, and every reading is written as soon as it is taken.
 * Nothing here counts time with a running timer: the pump's start and stop
 * are device-clock times, and every elapsed time is worked out from them
 * afresh, so a page reloaded, or a phone that slept through three readings,
 * comes back to the right minute and says which readings were missed.
 *
 * The co-pilot exists in the browser app only; the Streamlit app says so in
 * the same words (text catalogue, pumping_copilot.browser_only).
 */
(function (global) {
  'use strict';

  /** @type {GWTNamespace} */
  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support, C = GWT.core;
  var el = S.el, card = S.card, field = S.field;

  /* S.button, with the data- attributes the browser checks find it by */
  function button(label, onClick, options) {
    var node = S.button(label, onClick, options);
    Object.keys(options || {}).forEach(function (k) {
      if (k.indexOf('data-') === 0) node.setAttribute(k, options[k]);
    });
    return node;
  }

  var KEY = 'pumpCopilot';
  var FORMAT = 1;

  /* PLAN.md's schedule: log-spaced to two hours, then every 30 minutes.
   * Equal spacing in log time is what the Cooper-Jacob line is fitted in, so
   * the early minutes, where the curve bends fastest, are not left with two
   * points and the late hours with forty. */
  var SCHEDULE_MIN = [0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30,
    40, 50, 60, 75, 90, 120];
  var LATE_EVERY_MIN = 30;

  /* A rate that has moved this much since the step's first measurement is a
   * different test: the drawdown is then answering two rates at once. */
  var DRIFT_LIMIT = 0.05;
  /* The estimate is stable when it has moved less than this over the last
   * log cycle of the test. */
  var STABLE_LIMIT = 0.10;
  /* Logan (1964): T is about 1.22 Q/s, with Q/s in m3/day per metre. It turns
   * a transmissivity into the specific capacity Schafer's rule needs before
   * any drawdown has been read. */
  var LOGAN = 1.22;
  /* the cautious range offered before pumping, m2/day: the low end is what
   * sets the time, and weathered basement is often no better */
  var T_LOW = 1, T_HIGH = 10;
  /* the template has four step groups */
  var MAX_STEPS = 4;

  /* ---------------------------------------------------------------- clock */

  /* The device clock, in milliseconds. A test can put its own clock here
   * (GWT.pumpCopilotClock) to play a test back at speed: the page never
   * counts time any other way, so a played-back test is the same code path
   * as a real one. */
  function now() {
    return typeof GWT.pumpCopilotClock === 'function'
      ? Number(GWT.pumpCopilotClock()) : Date.now();
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  /* "14:20", on the device's own clock and time zone, which is what the
   * crew's watch says */
  function clockText(ms) {
    var d = new Date(ms);
    return pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function dateText(ms) {
    var d = new Date(ms);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  /* The device clock with its offset from UTC, so whoever reads the sheet
   * can tell local time from a clock that was simply wrong. */
  function deviceClockText(ms) {
    var d = new Date(ms);
    var offset = -d.getTimezoneOffset();
    var sign = offset < 0 ? '-' : '+';
    var abs = Math.abs(offset);
    return dateText(ms) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) +
      ':' + pad(d.getSeconds()) + sign + pad(Math.floor(abs / 60)) + ':' + pad(abs % 60);
  }

  function round(value, places) {
    var f = Math.pow(10, places);
    return Math.round(value * f) / f;
  }

  function isNum(v) { return typeof v === 'number' && isFinite(v); }

  function minutesText(min) {
    if (min < 90) return String(round(min, min < 10 ? 2 : 1)) + ' min';
    var h = Math.floor(min / 60), m = Math.round(min - 60 * h);
    if (m === 60) { h += 1; m = 0; }
    return h + ' h ' + pad(m) + ' min';
  }

  /* a minute on the schedule or the sheet as the crew writes it: 0.5, 10, 75 */
  function minuteText(min) {
    return String(round(min, 2));
  }

  function countdownText(seconds) {
    var s = Math.max(0, Math.ceil(seconds));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return (h ? h + ':' + pad(m) : String(m)) + ':' + pad(r);
  }

  /* ------------------------------------------------------------- schedule */

  /* The first scheduled minute after `afterMin`, on a phase's own clock. */
  function nextSlot(afterMin) {
    for (var i = 0; i < SCHEDULE_MIN.length; i++) {
      if (SCHEDULE_MIN[i] > afterMin + 1e-9) return SCHEDULE_MIN[i];
    }
    var last = SCHEDULE_MIN[SCHEDULE_MIN.length - 1];
    return last + LATE_EVERY_MIN *
      (Math.floor((afterMin - last) / LATE_EVERY_MIN + 1e-9) + 1);
  }

  function isSlot(min) {
    return min > 0 && Math.abs(nextSlot(min - 1e-6) - min) < 1e-6;
  }

  /* Every scheduled minute in (from, to]. */
  function slotsBetween(from, to) {
    var out = [];
    for (var s = nextSlot(from); s <= to + 1e-9; s = nextSlot(s)) out.push(s);
    return out;
  }

  /* How far from a scheduled minute a reading may be and still be written
   * as that minute, as the crew writes it on a paper sheet: 6 seconds early
   * on, a tenth of the time later. A reading further off is written at the
   * minute it was actually taken. */
  function slotTolerance(slot) {
    return Math.max(0.1, 0.1 * slot);
  }

  /* -------------------------------------------------------------- session */

  function app() { return GWT.app; }

  function session() {
    var s = app().store.get(KEY);
    return s && typeof s === 'object' ? s : null;
  }

  function pumpingConfig(setup) {
    var cfg = app().config().pumping;
    var out = Object.assign({}, cfg);
    if (setup && isNum(setup.casingIn)) out.casing_diameter_in = setup.casingIn;
    if (setup && isNum(setup.riserIn)) out.riser_diameter_in = setup.riserIn;
    return out;
  }

  /* What the setup form starts from: the project's own site, and the
   * casing the engine assumes. */
  function blankSession() {
    var site = app().store.get('site') || {};
    var cfg = app().config().pumping;
    return {
      format: FORMAT,
      phase: 'setup',
      setup: {
        community: site.community || '', client: site.client || '',
        district: site.district || '', operator: site.supervisor || '',
        boreholeRef: '', testType: 'constant',
        casingIn: cfg.casing_diameter_in, riserIn: cfg.riser_diameter_in,
        pumpSettingM: null, depthM: null, staticM: null, plannedRate: null,
        plannedMin: cfg.min_constant_test_min, stepLengthMin: cfg.min_step_length_min,
        steps: 3, tLow: T_LOW, tHigh: T_HIGH,
      },
      startedAt: null, stoppedAt: null,
      steps: [], readings: [], gps: null, events: [], savedAt: null,
    };
  }

  /* Change the session and write it at once: a reading is the one thing
   * here that cannot be taken again. */
  function update(fn) {
    var current = session() || blankSession();
    var next = JSON.parse(JSON.stringify(current));
    var result = fn(next);
    app().store.set(KEY, next);
    app().store.flush();
    return result;
  }

  function logEvent(s, text, at) {
    s.events.push({ at: at === undefined ? now() : at, text: text });
  }

  /* ------------------------------------------------------------ the clock
   * of the test, always worked out from the device-clock times it stores */

  function pumpingMinutes(s, t) {
    if (!s.startedAt) return 0;
    var end = s.stoppedAt && s.stoppedAt < t ? s.stoppedAt : t;
    return Math.max(0, (end - s.startedAt) / 60000);
  }

  function recoveryMinutes(s, t) {
    return s.stoppedAt ? Math.max(0, (t - s.stoppedAt) / 60000) : 0;
  }

  function currentStep(s) {
    return s.steps.length ? s.steps.length - 1 : 0;
  }

  /* The phase now running, its clock in minutes, the minute its schedule
   * counts from on the sheet's clock, and the readings already in it. */
  function phaseClock(s, t) {
    if (s.phase === 'recovery') {
      return {
        phase: 'recovery', step: null, elapsed: recoveryMinutes(s, t), origin: 0,
        readings: s.readings.filter(function (r) { return r.phase === 'recovery'; }),
      };
    }
    var k = currentStep(s);
    var origin = s.steps.length ? s.steps[k].startMin : 0;
    return {
      phase: 'pumping', step: k, elapsed: pumpingMinutes(s, t) - origin, origin: origin,
      readings: s.readings.filter(function (r) {
        return r.phase === 'pumping' && r.step === k;
      }),
    };
  }

  /* Where the schedule stands at time t: the reading due (the latest
   * scheduled minute already passed and not yet read), the ones missed
   * before it, and the next one with the seconds left to it. */
  function scheduleAt(s, t) {
    var clock = phaseClock(s, t);
    var last = clock.readings.length
      ? clock.readings[clock.readings.length - 1].min - clock.origin : 0;
    var passed = slotsBetween(last, clock.elapsed);
    var due = passed.length ? passed[passed.length - 1] : null;
    var next = nextSlot(Math.max(clock.elapsed, last));
    var originMs = clock.phase === 'recovery' ? s.stoppedAt
      : s.startedAt + clock.origin * 60000;
    return {
      phase: clock.phase, step: clock.step, elapsed: clock.elapsed,
      origin: clock.origin, last: last,
      due: due, missed: passed.slice(0, -1),
      next: next, nextAt: originMs + next * 60000,
      seconds: (next - clock.elapsed) * 60,
    };
  }

  /* The minute a reading taken now is written at, on the phase's clock:
   * the scheduled minute when it is close enough to one, else the minute it
   * was actually taken. */
  function readingMinute(s, t) {
    var sched = scheduleAt(s, t);
    var e = sched.elapsed;
    var candidates = [sched.due, sched.next].filter(function (v) {
      return v !== null && v > sched.last + 1e-9;
    });
    for (var i = 0; i < candidates.length; i++) {
      if (Math.abs(e - candidates[i]) <= slotTolerance(candidates[i])) {
        return { min: candidates[i], scheduled: true };
      }
    }
    return { min: round(e, 2), scheduled: false };
  }

  /* ------------------------------------------------------------- discharge */

  function meanRate(step) {
    var values = (step.discharges || []).map(function (d) { return d.rate; })
      .filter(isNum);
    if (!values.length) return null;
    return values.reduce(function (a, b) { return a + b; }, 0) / values.length;
  }

  /* Bucket and stopwatch: litres over the mean of the timings, in m3/h. */
  function bucketRate(litres, seconds) {
    var t = seconds.filter(function (v) { return isNum(v) && v > 0; });
    if (!(litres > 0) || t.length < 3) return null;
    var mean = t.reduce(function (a, b) { return a + b; }, 0) / t.length;
    return { rate: litres / mean * 3.6, meanSeconds: mean };
  }

  /* Why the sheet cannot be written yet; an empty list when it can. A step
   * with no discharge gives a drawdown curve and no transmissivity, and the
   * sheet that went to the office from Kuntolo said nothing about why. */
  function saveProblems(s) {
    var problems = [];
    if (!s || !s.startedAt) return ['The test has not started.'];
    /* the sheet records when the pump stopped, and the recovery after it */
    if (!s.stoppedAt) problems.push('The pump has not been stopped yet.');
    if (!s.readings.some(function (r) { return r.phase === 'pumping'; })) {
      problems.push('No water level has been read while pumping.');
    }
    s.steps.forEach(function (step, i) {
      var measured = (step.discharges || []).length > 0;
      var reason = String(step.notMeasured || '').trim();
      if (!measured && !reason) {
        problems.push('Step ' + (i + 1) + ' has no discharge. Measure it, or ' +
          'record it as not measured and say why.');
      }
    });
    return problems;
  }

  /* ------------------------------------------------------- casing storage */

  /* Schafer's casing-storage period for a transmissivity, through Logan's
   * specific capacity, in minutes. */
  function storageForT(T, cfg) {
    if (!(T > 0)) return null;
    return C.casingStorageMin(T / (LOGAN * 24), cfg);
  }

  /* The pumping readings of the first step as drawdowns; the casing period
   * and the Cooper-Jacob line are both read from the first step, as the
   * analysis reads them. */
  function firstStepSeries(s) {
    var swl = s.setup.staticM, t = [], d = [];
    s.readings.forEach(function (r) {
      if (r.phase === 'pumping' && r.step === 0 && r.min > 0 && isNum(r.level)) {
        t.push(r.min); d.push(r.level - swl);
      }
    });
    return { time: t, drawdown: d };
  }

  /* The casing-storage period from what has been measured: the step's rate
   * over its latest drawdown, as analysePumpingTest will work it out from
   * the sheet. Null until both are known. The rate is the measured one; the
   * planned rate stands in, and says so, until the bucket has been timed. */
  function liveStorage(s, cfg) {
    var series = firstStepSeries(s);
    if (!series.time.length || !s.steps.length) return null;
    var sLast = series.drawdown[series.drawdown.length - 1];
    var measured = meanRate(s.steps[0]);
    var q = isNum(measured) ? measured : s.steps[0].plannedRate;
    if (!(sLast > 0) || !(q > 0)) return null;
    var tc = C.casingStorageMin(q / sLast, cfg);
    return tc === null ? null : { min: tc, rate: q, measured: isNum(measured),
      drawdown: sLast };
  }

  /* The shortest test that can give a transmissivity, in minutes of
   * pumping, and what sets it: a constant test runs past both the casing
   * period and the engine's minimum test length; a step test's first step
   * runs past the casing period, since that is the step the drawdown fits
   * are made on, and every step lasts at least the minimum step length. */
  function shortestPlan(setup, tc, cfg) {
    var storage = isNum(tc) ? tc : 0;
    if (setup.testType === 'step') {
      var stepMin = Math.max(cfg.min_step_length_min, setup.stepLengthMin || 0);
      var first = Math.max(stepMin, storage);
      var n = Math.max(1, Math.min(MAX_STEPS, setup.steps || 1));
      return { total: first + (n - 1) * stepMin, firstStep: first,
        storageBinds: storage > stepMin };
    }
    return { total: Math.max(cfg.min_constant_test_min, storage), firstStep: null,
      storageBinds: storage > cfg.min_constant_test_min };
  }

  /* How long the crew means to pump, in minutes. */
  function plannedLength(setup) {
    if (setup.testType === 'step') {
      return Math.max(1, Math.min(MAX_STEPS, setup.steps || 1)) * (setup.stepLengthMin || 0);
    }
    return setup.plannedMin || 0;
  }

  /* --------------------------------------------------------- the warnings */

  /* What the page says at time t: the clock, the schedule, the casing
   * period and every warning. Pure: the same session and time give the same
   * answer, which is what lets a test be played back at speed. */
  function evaluate(s, t) {
    var setup = s.setup, cfg = pumpingConfig(setup);
    var out = {
      cfg: cfg, warnings: [],
      storageRange: [storageForT(setup.tHigh, cfg), storageForT(setup.tLow, cfg)],
      live: null, plan: null, stopBefore: null, firstStepBefore: null,
      schedule: null, pumpingMin: pumpingMinutes(s, t),
    };
    function warn(level, code, message) {
      out.warnings.push({ level: level, code: code, message: message });
    }
    out.live = s.startedAt ? liveStorage(s, cfg) : null;
    var tc = out.live ? out.live.min : out.storageRange[1];
    out.tc = tc;
    out.plan = shortestPlan(setup, tc, cfg);
    var startMs = s.startedAt || t;
    out.stopBefore = startMs + out.plan.total * 60000;
    if (out.plan.firstStep !== null) {
      out.firstStepBefore = startMs + out.plan.firstStep * 60000;
    }
    out.planned = plannedLength(setup);
    out.plannedStop = startMs + out.planned * 60000;
    if (s.phase === 'setup' || !s.startedAt) return out;

    var sched = out.schedule = scheduleAt(s, t);
    var swl = setup.staticM;
    /* the latest level of all, whichever phase it was read in */
    var latest = s.readings.length ? s.readings[s.readings.length - 1] : null;

    if (s.phase === 'pumping') {
      var elapsed = out.pumpingMin;
      if (elapsed < out.plan.total) {
        warn('warning', 'do_not_stop', 'Do not stop before ' + clockText(out.stopBefore) +
          '. The shortest test that can give a transmissivity here runs ' +
          minutesText(out.plan.total) + (out.plan.storageBinds
            ? ', set by the casing-storage period'
            : ', the minimum ' + (setup.testType === 'step' ? 'step length' : 'test length') +
              ' the analysis asks for') +
          '; stopping now leaves ' + minutesText(out.plan.total - elapsed) + ' short.');
      }
      if (setup.testType === 'step' && sched.step === 0 && out.firstStepBefore &&
          t < out.firstStepBefore) {
        warn('warning', 'first_step', 'Do not change to step 2 before ' +
          clockText(out.firstStepBefore) + ': the drawdown fits are made on step 1, ' +
          'and it has to run past casing storage first.');
      }
      if (isNum(tc) && elapsed < tc && (sched.step === 0 || sched.step === null)) {
        warn('warning', 'casing_storage', 'Still inside casing storage until about ' +
          clockText(startMs + tc * 60000) + ' (' + minutesText(tc) + ' of pumping' +
          (out.live ? (out.live.measured ? '' : ', at the planned rate until the ' +
            'discharge is measured') : ', for ' + S.sig(setup.tLow, 2) +
            ' m2/day until drawdown is read') + '). The level is still mostly the ' +
          'casing emptying, not the aquifer answering, so no transmissivity can be ' +
          'read from it yet.');
      }
      var step = s.steps[sched.step];
      var rates = (step.discharges || []).map(function (d) { return d.rate; });
      if (rates.length > 1) {
        var drift = (rates[rates.length - 1] - rates[0]) / rates[0];
        if (Math.abs(drift) > DRIFT_LIMIT) {
          warn('bad', 'discharge_drift', 'The discharge has drifted ' +
            S.sig(Math.abs(drift) * 100, 2) + ' percent since this step\'s first ' +
            'measurement (' + S.sig(rates[0], 3) + ' to ' +
            S.sig(rates[rates.length - 1], 3) + ' m3/h), more than the ' +
            Math.round(DRIFT_LIMIT * 100) + ' percent a constant rate allows. Set ' +
            'the valve back to ' + S.sig(rates[0], 3) + ' m3/h and time the bucket again.');
        }
      }
      if (!rates.length && !String(step.notMeasured || '').trim() && sched.elapsed >= 2) {
        warn('warning', 'discharge_missing', 'No discharge measured for step ' +
          (sched.step + 1) + ' yet. Time the bucket now: without a rate the sheet ' +
          'gives a drawdown curve and no transmissivity.');
      }
    }
    if (s.phase === 'pumping' && latest && isNum(setup.pumpSettingM)) {
      if (latest.level >= setup.pumpSettingM) {
        warn('bad', 'level_at_intake', 'The water level, ' + S.sig(latest.level, 4) +
          ' m, is at or below the pump intake at ' + S.sig(setup.pumpSettingM, 3) +
          ' m. A pump cannot draw the water below its own intake: check the dipper ' +
          'and the datum now, and reduce the rate before the pump runs dry.');
      } else if (latest.level >= setup.pumpSettingM - cfg.pump_submergence_min_m) {
        warn('warning', 'level_near_intake', 'The water level is within ' +
          S.sig(setup.pumpSettingM - latest.level, 2) + ' m of the pump intake (' +
          S.sig(setup.pumpSettingM, 3) + ' m). Reduce the rate if it is still falling.');
      }
    }
    if (latest && isNum(setup.depthM) && latest.level > setup.depthM) {
      warn('bad', 'level_below_hole', 'The water level, ' + S.sig(latest.level, 4) +
        ' m, is deeper than the hole (' + S.sig(setup.depthM, 3) + ' m). Check the ' +
        'reading and the datum.');
    }
    if (latest && isNum(swl) && latest.level < swl - 0.01) {
      warn('warning', 'level_above_static', 'The last level is above the static ' +
        'level of ' + S.sig(swl, 4) + ' m. Check the reading and the measuring point.');
    }
    if (sched.missed.length) {
      warn('info', 'readings_missed', 'Missed: the ' + sched.missed.map(function (m) {
        return minuteText(m);
      }).join(', ') + '-minute ' + (sched.missed.length > 1 ? 'readings' : 'reading') +
        '. Take the next one as soon as it is due; a missed reading is not made up ' +
        'by guessing it.');
    }
    if (s.phase === 'recovery') {
      warn('info', 'recovery', 'Recovery: the pump stopped at ' + clockText(s.stoppedAt) +
        ' and the schedule started again from that moment.');
    }
    return out;
  }

  /* ------------------------------------------------- the live Cooper-Jacob */

  /* The engine's Cooper-Jacob line through the first step as it stands, and
   * the one through the readings of a log cycle earlier, worked out in the
   * engine worker. While the test is still inside casing storage it resolves
   * to that state and fits nothing, since a line through the casing emptying
   * is not an aquifer's. */
  function liveEstimate(s, t) {
    if (!s || !s.startedAt || !s.steps.length) return Promise.resolve(null);
    var ev = evaluate(s, t);
    var series = firstStepSeries(s);
    var q = meanRate(s.steps[0]);
    var tEnd = series.time.length ? series.time[series.time.length - 1] : 0;
    var base = { tc: ev.tc, tEnd: tEnd, rate: q };
    if (!isNum(ev.tc) || tEnd <= ev.tc) {
      return Promise.resolve(Object.assign(base, { state: 'storage' }));
    }
    if (!isNum(q)) return Promise.resolve(Object.assign(base, { state: 'no_rate' }));
    var fits = [{ time: series.time, drawdown: series.drawdown, discharge: q }];
    var earlier = series.time.filter(function (v) { return v <= tEnd / 10 + 1e-9; });
    if (earlier.length) {
      fits.push({ time: earlier, drawdown: series.drawdown.slice(0, earlier.length),
        discharge: q });
    }
    return GWT.engine.cooperJacob(fits, ev.cfg).then(function (answers) {
      var nowFit = answers[0], then = answers[1] || null;
      if (!nowFit.fit) return Object.assign(base, { state: 'refused', reason: nowFit.refused });
      var out = Object.assign(base, { state: 'fit', fit: nowFit.fit });
      /* a log cycle back is still the casing emptying until the test has run
       * ten times the casing period */
      if (tEnd / 10 <= ev.tc) {
        out.stability = 'early';
        out.stableFrom = s.startedAt + ev.tc * 10 * 60000;
      } else if (!then || !then.fit) {
        out.stability = 'unknown';
      } else {
        var T = nowFit.fit.transmissivity_m2_per_day;
        var T0 = then.fit.transmissivity_m2_per_day;
        out.change = Math.abs(T - T0) / T;
        out.previous = then.fit;
        out.stability = out.change < STABLE_LIMIT ? 'stable' : 'moving';
      }
      return out;
    });
  }

  function estimateNote(est) {
    if (!est) return '';
    if (est.state === 'storage') {
      return 'No estimate yet: every reading so far is inside casing storage' +
        (isNum(est.tc) ? ' (until minute ' + Math.round(est.tc) + ')' : '') + '.';
    }
    if (est.state === 'no_rate') {
      return 'No estimate: the discharge of step 1 has not been measured.';
    }
    if (est.state === 'refused') return 'No estimate: ' + est.reason + '.';
    var T = est.fit.transmissivity_m2_per_day;
    var head = 'Cooper-Jacob: T = ' + S.sig(T, 3) + ' m2/day from ' +
      minuteText(est.fit.fit_window_min[0]) + ' to ' + minuteText(est.fit.fit_window_min[1]) +
      ' min (' + S.sig(est.fit.slope_m_per_log_cycle, 3) + ' m per log cycle, R squared ' +
      est.fit.r_squared.toFixed(3) + ').';
    if (est.stability === 'stable') {
      return head + ' T has changed less than 10 percent over the last log cycle. ' +
        'The test can stop at the planned time.';
    }
    if (est.stability === 'moving') {
      return head + ' T has changed ' + S.sig(est.change * 100, 2) + ' percent over ' +
        'the last log cycle (from ' + S.sig(est.previous.transmissivity_m2_per_day, 3) +
        ' m2/day). Keep pumping.';
    }
    if (est.stability === 'early') {
      return head + ' The test is not yet a full log cycle clear of casing storage ' +
        '(that comes at ' + clockText(est.stableFrom) + '), so how steady T is cannot ' +
        'be judged yet.';
    }
    return head + ' The line a log cycle earlier could not be fitted, so how steady T ' +
      'is cannot be judged yet.';
  }

  /* -------------------------------------------------------------- actions */

  function setSetup(name, value) {
    update(function (s) { s.setup[name] = value; });
  }

  /* A figure from before the pump started, put right during the test, with
   * the change in the log the sheet carries. */
  function correctSetup(name, label, value) {
    if (!isNum(value)) throw new Error('Enter a number.');
    update(function (s) {
      var was = s.setup[name];
      if (was === value) return;
      s.setup[name] = value;
      logEvent(s, label + ' corrected from ' + was + ' to ' + value);
    });
  }

  /* Why the test cannot start yet; empty when it can. */
  function startProblems(setup) {
    var problems = [];
    if (!isNum(setup.staticM)) problems.push('Enter the static water level.');
    if (!isNum(setup.pumpSettingM)) problems.push('Enter the pump setting.');
    if (!(setup.plannedRate > 0)) problems.push('Enter the planned rate.');
    if (!(setup.casingIn > setup.riserIn)) {
      problems.push('The casing must be wider than the riser.');
    }
    if (isNum(setup.staticM) && isNum(setup.pumpSettingM) &&
        setup.pumpSettingM <= setup.staticM) {
      problems.push('The pump is set above the static level.');
    }
    if (isNum(setup.depthM) && isNum(setup.pumpSettingM) &&
        setup.pumpSettingM > setup.depthM) {
      problems.push('The pump is set deeper than the hole.');
    }
    return problems;
  }

  function start() {
    var t = now();
    primeSound();
    update(function (s) {
      var problems = startProblems(s.setup);
      if (problems.length) throw new Error(problems.join(' '));
      s.phase = 'pumping';
      s.startedAt = t;
      s.stoppedAt = null;
      s.steps = [{ startMin: 0, plannedRate: s.setup.plannedRate, discharges: [],
        notMeasured: '' }];
      s.readings = [];
      s.savedAt = null;
      logEvent(s, 'Pump started at ' + S.sig(s.setup.plannedRate, 3) +
        ' m3/h planned', t);
    });
  }

  /* A level read now, or at `opts.min` on the sheet's clock when it is given
   * (a reading typed in late, or a test played back). Returns the reading. */
  function record(level, opts) {
    var o = opts || {};
    var t = isNum(o.at) ? o.at : now();
    if (!isNum(level) || level < 0) throw new Error('Enter the water level in metres.');
    return update(function (s) {
      if (s.phase !== 'pumping' && s.phase !== 'recovery') {
        throw new Error('Start the pump first.');
      }
      var sched = scheduleAt(s, t);
      var min, scheduled;
      if (isNum(o.min)) {
        min = o.min;
        scheduled = isSlot(min - sched.origin);
      } else {
        var at = readingMinute(s, t);
        min = at.min + sched.origin;
        scheduled = at.scheduled;
      }
      if (min <= sched.origin + 1e-9) {
        throw new Error('A reading has to come after minute ' + minuteText(sched.origin) +
          (sched.phase === 'recovery' ? ', when the pump stopped.' : ', when this step started.'));
      }
      var previous = sched.last + sched.origin;
      var phaseReadings = s.readings.filter(function (r) {
        return r.phase === sched.phase && (sched.phase === 'recovery' || r.step === sched.step);
      });
      if (phaseReadings.length && min <= previous + 1e-9) {
        throw new Error('A reading at minute ' + minuteText(min) + ' is not after the last one (' +
          minuteText(previous) + ').');
      }
      var reading = { phase: sched.phase, step: sched.step, min: round(min, 2),
        level: level, at: t, scheduled: scheduled };
      s.readings.push(reading);
      return reading;
    });
  }

  function undoReading() {
    update(function (s) {
      var gone = s.readings.pop();
      if (gone) {
        logEvent(s, 'Reading at minute ' + gone.min + ' (' + gone.level +
          ' m) removed');
      }
    });
  }

  function addDischarge(rate, method, extra, stepIndex) {
    if (!(rate > 0)) throw new Error('Enter a discharge greater than zero.');
    var t = now();
    update(function (s) {
      if (!s.steps.length) throw new Error('Start the pump first.');
      var k = isNum(stepIndex) ? stepIndex : currentStep(s);
      var step = s.steps[k];
      step.discharges.push(Object.assign({
        rate: round(rate, 4), method: method, at: t,
        min: round(pumpingMinutes(s, t), 2),
      }, extra || {}));
      step.notMeasured = '';
    });
  }

  function setNotMeasured(stepIndex, reason) {
    var text = String(reason || '').trim();
    if (!text) throw new Error('Say why the discharge was not measured.');
    update(function (s) {
      var step = s.steps[stepIndex];
      if (!step) throw new Error('There is no step ' + (stepIndex + 1) + '.');
      if (step.discharges.length) {
        throw new Error('Step ' + (stepIndex + 1) + ' has a measured discharge.');
      }
      step.notMeasured = text;
      logEvent(s, 'Step ' + (stepIndex + 1) + ' discharge recorded as not measured: ' + text);
    });
  }

  function nextStep(rate) {
    var t = now();
    update(function (s) {
      if (s.phase !== 'pumping') throw new Error('The pump is not running.');
      if (s.steps.length >= MAX_STEPS) {
        throw new Error('The workbook holds ' + MAX_STEPS + ' steps.');
      }
      var at = round(pumpingMinutes(s, t), 2);
      s.steps.push({ startMin: at, plannedRate: isNum(rate) ? rate : null,
        discharges: [], notMeasured: '' });
      logEvent(s, 'Step ' + s.steps.length + ' started at minute ' + at +
        (isNum(rate) ? ', ' + S.sig(rate, 3) + ' m3/h planned' : ''), t);
    });
  }

  function stopPump() {
    var t = now();
    update(function (s) {
      if (s.phase !== 'pumping') throw new Error('The pump is not running.');
      s.phase = 'recovery';
      s.stoppedAt = t;
      logEvent(s, 'Pump stopped after ' + round(pumpingMinutes(s, t), 2) + ' min', t);
    });
  }

  function setGps(position) {
    update(function (s) {
      s.gps = position;
      logEvent(s, 'GPS position taken (' + position.lat.toFixed(6) + ', ' +
        position.lon.toFixed(6) + ', within ' + Math.round(position.accuracy || 0) + ' m)');
    });
  }

  /* With the user's permission, from the press of a button: the position
   * goes in the sheet's header as UTM, and as latitude and longitude beside
   * it, with the accuracy the device reported. */
  function takeGps() {
    if (!global.navigator || !global.navigator.geolocation) {
      S.toast('This device has no location service.', 'error');
      return;
    }
    S.toast('Asking the device for its position…');
    global.navigator.geolocation.getCurrentPosition(function (pos) {
      var c = pos.coords;
      setGps({ lat: c.latitude, lon: c.longitude, accuracy: c.accuracy,
        altitude: isNum(c.altitude) ? c.altitude : null, at: now() });
      S.toast('Position recorded.', 'ok');
      rerender();
    }, function (e) {
      S.toast('No position: ' + e.message, 'error');
    }, { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 });
  }

  function discard() {
    app().store.remove(KEY);
    app().store.flush();
  }

  /* ------------------------------------------------------------ workbook */

  /* The rows of the standard pumping test sheet, cell for cell where
   * src/groundwater/ingestion/templates.py puts them, with the co-pilot's
   * own header lines (the device clock, the GPS fix, the casing) in columns
   * Q and R, beyond the reach of the readers' label-to-value search, and a
   * second worksheet holding the log. The readers take the first sheet. */
  function workbookSheets(s, writtenAt) {
    var setup = s.setup;
    var rows = [];
    function put(r, c, v) {
      while (rows.length <= r) rows.push([]);
      var row = rows[r];
      while (row.length < c) row.push('');
      row[c] = v === null || v === undefined ? '' : v;
    }
    var step = setup.testType === 'step';
    put(0, 0, 'PUMPING TEST FIELD SHEET (STEP / CONSTANT DISCHARGE)');
    var start = s.startedAt;
    var utm = null;
    if (s.gps) {
      utm = C.geographicToUtm(s.gps.lat, s.gps.lon);
    }
    var header = [
      [1, 0, 'Community', setup.community], [1, 3, 'Date', start ? dateText(start) : ''],
      [2, 0, 'Client', setup.client],
      [2, 3, 'Length of each step (min)', step ? setup.stepLengthMin : ''],
      [3, 0, 'Test conducted by', setup.operator],
      [3, 3, 'Start time', start ? clockText(start) : ''],
      [4, 0, 'Borehole Ref. No.', setup.boreholeRef],
      [4, 3, 'Depth of Borehole (m)', setup.depthM],
      [5, 0, 'Static water level (m)', setup.staticM],
      [5, 3, 'Pump setting (m)', setup.pumpSettingM],
      [6, 0, 'Test type (step or constant)', step ? 'step' : 'constant'],
      [6, 3, 'District', setup.district],
      [1, 6, 'GPS Coordinate East', utm ? Math.round(utm.easting) : ''],
      [2, 6, 'GPS Coordinate North', utm ? Math.round(utm.northing) : ''],
      [3, 6, 'UTM Zone (28N or 29N)', utm ? utm.zone + utm.hemisphere : ''],
      [4, 6, 'Elevation (m)', ''],
    ];
    header.forEach(function (h) { put(h[0], h[1], h[2]); put(h[0], h[1] + 1, h[3]); });

    var extras = [
      ['Written by', 'Groundwater Toolkit pumping test co-pilot ' +
        ((GWT.data && GWT.data.version) || '')],
      ['Device clock, pump started', start ? deviceClockText(start) : ''],
      ['Device clock, pump stopped', s.stoppedAt ? deviceClockText(s.stoppedAt) : ''],
      ['Device clock, sheet written', deviceClockText(writtenAt)],
      ['GPS latitude (WGS84)', s.gps ? round(s.gps.lat, 6) : ''],
      ['GPS longitude (WGS84)', s.gps ? round(s.gps.lon, 6) : ''],
      ['GPS accuracy (m)', s.gps && isNum(s.gps.accuracy) ? Math.round(s.gps.accuracy) : ''],
      ['GPS fix, device clock', s.gps ? deviceClockText(s.gps.at) : ''],
      ['Casing diameter (in)', setup.casingIn],
      ['Riser diameter (in)', setup.riserIn],
      ['Planned rate (m3/h)', setup.plannedRate],
    ];
    /* two columns of pairs, so none of them reaches down into the rows the
     * readers take the column headings and the readings from */
    extras.forEach(function (pair, i) {
      var r = 1 + (i % 6), c = 16 + 3 * Math.floor(i / 6);
      put(r, c, pair[0]);
      put(r, c + 1, pair[1]);
    });

    /* why a step has no discharge, said on the sheet itself; worded so no
     * reader takes it for a label or a rate */
    var unmeasured = [];
    s.steps.forEach(function (st, i) {
      if (!st.discharges.length && String(st.notMeasured || '').trim()) {
        unmeasured.push('step ' + (i + 1) + ': ' + String(st.notMeasured).trim());
      }
    });
    if (unmeasured.length) {
      put(7, 0, 'Discharge note');
      put(7, 1, 'Not measured (' + unmeasured.join('; ') + ')');
    }

    put(8, 0, 'Discharge per step (m3/h)');
    [1, 4, 7, 10].forEach(function (col, i) {
      put(8, col, 'Step ' + (i + 1) + ' Q');
      var st = s.steps[i];
      var q = st ? meanRate(st) : null;
      put(8, col + 1, isNum(q) ? round(q, 3) : '');
    });

    /* the column groups: a constant test in hourly blocks, each read on the
     * test's own clock under a heading that names its minutes, so the
     * readers place each block by its heading; a step test one step to a
     * group, on the same clock */
    var pumping = s.readings.filter(function (r) { return r.phase === 'pumping'; });
    var groups = [[], [], [], []], headings;
    var lastMin = pumping.length ? pumping[pumping.length - 1].min : 0;
    if (step) {
      pumping.forEach(function (r) { groups[Math.min(r.step, 3)].push(r); });
      headings = groups.map(function (g, i) {
        var st = s.steps[i];
        if (!st) return 'Step ' + (i + 1);
        var end = i + 1 < s.steps.length ? s.steps[i + 1].startMin
          : (g.length ? g[g.length - 1].min : st.startMin);
        return 'Step ' + (i + 1) + ', ' + minuteText(st.startMin) + '-' + minuteText(end) + ' min';
      });
    } else {
      /* a reading belongs to the block whose heading starts at or before
       * it: the readers shift a block whose first reading comes before its
       * heading's first minute, so a reading at 60.5 min stays in the first
       * block rather than being moved an hour on */
      pumping.forEach(function (r) {
        var block = r.min < 61 ? 0 : r.min < 121 ? 1 : r.min < 181 ? 2 : 3;
        groups[block].push(r);
      });
      headings = ['Constant discharge 0-60 min', 'Constant discharge 61-120 min',
        'Constant discharge 121-180 min',
        'Constant discharge 181-' + Math.max(240, Math.ceil(lastMin)) + ' min'];
    }
    var recovery = s.readings.filter(function (r) { return r.phase === 'recovery'; });
    var head = 10;
    [0, 3, 6, 9].forEach(function (col, i) {
      put(head - 1, col, headings[i]);
      put(head, col, 'Time (min)');
      put(head, col + 1, 'Water Level (m)');
      put(head, col + 2, 'Drawdown (m)');
      var prev = null;
      groups[i].forEach(function (r, j) {
        put(head + 1 + j, col, r.min);
        put(head + 1 + j, col + 1, r.level);
        put(head + 1 + j, col + 2, prev === null ? 0 : round(r.level - prev, 2));
        prev = r.level;
      });
    });
    put(head - 1, 12, 'Recovery');
    put(head, 12, 'Time (min)');
    put(head, 13, 'Water Level (m)');
    put(head, 14, 'Recovery (m)');
    var before = null;
    recovery.forEach(function (r, j) {
      put(head + 1 + j, 12, r.min);
      put(head + 1 + j, 13, r.level);
      put(head + 1 + j, 14, before === null ? 0 : round(before - r.level, 2));
      before = r.level;
    });
    var longest = Math.max(40, recovery.length,
      Math.max.apply(null, groups.map(function (g) { return g.length; })));
    put(head + longest + 2, 0, 'Notes: record depth to water in metres below the ' +
      'measuring point. The Drawdown and Recovery columns are the change between ' +
      'successive readings; the analysis recomputes true drawdown from the static ' +
      'water level. Recovery time is minutes since the pump stopped. Record the ' +
      'discharge of every step; results stay provisional until discharge is supplied.');

    var log = [['PUMPING TEST CO-PILOT LOG'], [],
      ['Device clock', 'Event']];
    s.events.forEach(function (e) { log.push([deviceClockText(e.at), e.text]); });
    log.push([], ['Readings'],
      ['Phase', 'Step', 'Time (min)', 'Water level (m)', 'Device clock', 'Timing']);
    s.readings.forEach(function (r) {
      log.push([r.phase, r.phase === 'pumping' ? r.step + 1 : '', r.min, r.level,
        deviceClockText(r.at), r.scheduled ? 'scheduled minute' : 'time taken']);
    });
    log.push([], ['Discharge measurements'],
      ['Step', 'Time (min)', 'Rate (m3/h)', 'Method', 'Bucket (L)', 'Timings (s)',
        'Device clock']);
    s.steps.forEach(function (st, i) {
      st.discharges.forEach(function (d) {
        log.push([i + 1, d.min, d.rate, d.method, isNum(d.bucketL) ? d.bucketL : '',
          (d.timingsS || []).join(', '), deviceClockText(d.at)]);
      });
      if (!st.discharges.length && st.notMeasured) {
        log.push([i + 1, '', '', 'not measured', '', '', st.notMeasured]);
      }
    });
    return [
      { name: 'Pumping Test', rows: rows, widths: [13, 13, 13, 13, 13, 13, 13, 13, 13,
        13, 13, 13, 13, 13, 13, 4, 26, 30, 4, 22, 14] },
      { name: 'Co-pilot log', rows: log, widths: [26, 10, 12, 16, 26, 22, 26] },
    ];
  }

  function fileName(s) {
    var stem = S.slug(s.setup.boreholeRef || s.setup.community || 'pumping_test');
    return stem + '_pumping_test_' + (s.startedAt ? dateText(s.startedAt) : 'draft') + '.xlsx';
  }

  /* The workbook's bytes, or an error naming what is missing. */
  async function workbook(s) {
    var problems = saveProblems(s);
    if (problems.length) throw new Error(problems.join(' '));
    return S.writeXlsx(workbookSheets(s, now()));
  }

  async function save() {
    var s = session();
    var bytes = await workbook(s);
    S.download(fileName(s), new Blob([bytes]));
    update(function (next) {
      next.savedAt = now();
      logEvent(next, 'Workbook written');
    });
    return bytes;
  }

  /* The sheet the co-pilot wrote, as the project's pumping test, read by
   * the same reader as an uploaded one. */
  async function useInProject() {
    var s = session();
    var bytes = new Uint8Array(await workbook(s));
    var store = app().store;
    store.set('sources.pumping', { name: fileName(s), b64: S.bytesToBase64(bytes) });
    /* rates typed on the Pumping test page belonged to the sheet before
     * this one; this sheet carries its own, or its reasons for having none */
    store.set('pumping.manualDischarges', {});
    await app().recompute();
    app().goto('pumping');
  }

  /* Over a pumping test the project already holds, only when asked. */
  function offerToProject() {
    var held = (app().store.get('sources') || {}).pumping;
    if (!held) return act(useInProject)();
    S.modal('Replace the pumping test sheet?', el('p', 'This project already holds ' +
      held.name + '. The co-pilot\'s sheet takes its place; the other file is not ' +
      'changed.'), [
      button('Replace it', function () {
        document.querySelectorAll('.modal-overlay').forEach(function (n) {
          n.parentNode.removeChild(n);
        });
        act(useInProject)();
      }, { variant: 'danger' }),
    ]);
    return null;
  }

  /* ---------------------------------------------------------------- sound */

  var audio = null;
  var beepCount = 0;

  /* A browser plays sound only after the user has pressed something, so the
   * audio is opened on the press that starts the pump. */
  function primeSound() {
    try {
      var Ctor = global.AudioContext || /** @type {any} */ (global).webkitAudioContext;
      if (!audio && Ctor) audio = new Ctor();
      if (audio && audio.state === 'suspended') audio.resume();
    } catch (e) { audio = null; }
  }

  function beep() {
    beepCount += 1;
    try {
      if (global.navigator && global.navigator.vibrate) global.navigator.vibrate([250, 120, 250]);
    } catch (e) { /* not every device vibrates */ }
    if (!audio) return;
    try {
      [0, 0.35].forEach(function (offset) {
        var osc = audio.createOscillator(), gain = audio.createGain();
        osc.frequency.value = 880;
        gain.gain.value = 0.25;
        osc.connect(gain);
        gain.connect(audio.destination);
        osc.start(audio.currentTime + offset);
        osc.stop(audio.currentTime + offset + 0.22);
      });
    } catch (e) { /* a sound that fails leaves the countdown on screen */ }
  }

  /* --------------------------------------------------------------- ticker */

  /* Once a second while a test runs: the countdown, the clock, and a sound
   * when a reading falls due. It only ever reads the device clock, so a
   * second it misses - a hidden tab, a phone asleep - costs nothing but that
   * second's drawing. A reading that fell due while nobody was looking is
   * not sounded late; the page lists it as missed. */
  var ticker = null;
  var sounded = '';
  var warningsShown = '';

  function tick() {
    var s = session();
    if (!s || (s.phase !== 'pumping' && s.phase !== 'recovery')) return null;
    var t = now();
    var ev = evaluate(s, t);
    var sched = ev.schedule;
    if (sched.due !== null) {
      var key = sched.phase + ':' + sched.step + ':' + sched.due;
      var dueAt = (sched.phase === 'recovery' ? s.stoppedAt
        : s.startedAt + sched.origin * 60000) + sched.due * 60000;
      if (key !== sounded) {
        sounded = key;
        if (t - dueAt < 60000) beep();
      }
    }
    var doc = global.document;
    if (!doc) return ev;
    var countdown = doc.querySelector('[data-cp="countdown"]');
    if (countdown) {
      countdown.textContent = sched.due !== null
        ? 'Read now: the ' + minuteText(sched.due) + '-minute reading'
        : countdownText(sched.seconds);
    }
    var elapsed = doc.querySelector('[data-cp="elapsed"]');
    if (elapsed) elapsed.textContent = elapsedText(s, sched);
    var next = doc.querySelector('[data-cp="next"]');
    if (next) next.textContent = nextText(sched);
    var host = doc.querySelector('[data-cp="warnings"]');
    var shown = JSON.stringify(ev.warnings);
    if (host && shown !== warningsShown) {
      warningsShown = shown;
      S.clear(host);
      S.append(host, warningsView(ev.warnings));
    }
    return ev;
  }

  function ensureTicker() {
    if (ticker || typeof global.setInterval !== 'function') return;
    ticker = global.setInterval(tick, 1000);
  }

  /* ----------------------------------------------------------------- page */

  /* Drawn again once the event that asked for it has finished. An input's
   * change event also fires when the page removing it takes its focus, and
   * a redraw started from inside that removal pulls the page out from under
   * itself. */
  var redrawPending = false;

  function rerender() {
    if (redrawPending) return;
    redrawPending = true;
    global.setTimeout(function () {
      redrawPending = false;
      warningsShown = '';
      app().render();
    }, 0);
  }

  function act(fn) {
    return async function () {
      try {
        await fn.apply(null, arguments);
        rerender();
      } catch (e) {
        S.toast(e.message, 'error', 8000);
      }
    };
  }

  function elapsedText(s, sched) {
    if (sched.phase === 'recovery') {
      return 'Recovery ' + minutesText(sched.elapsed) + ' since the pump stopped at ' +
        clockText(s.stoppedAt);
    }
    return 'Pumping ' + minutesText(sched.elapsed + sched.origin) + ' since ' +
      clockText(s.startedAt) + (s.setup.testType === 'step'
        ? ', step ' + (sched.step + 1) + ' for ' + minutesText(sched.elapsed) : '');
  }

  function nextText(sched) {
    return 'Next reading: ' + minuteText(sched.next) + ' min' +
      (sched.phase === 'recovery' ? ' after the stop' : sched.origin ? ' into the step' : '') +
      ', at ' + clockText(sched.nextAt);
  }

  function warningsView(warnings) {
    if (!warnings.length) return el('p.muted', 'No warnings.');
    var tone = { bad: 'callout-bad', warning: 'callout-warn', info: 'callout-info' };
    return warnings.map(function (w) {
      return el('div.callout.' + (tone[w.level] || 'callout-info'),
        { 'data-warning': w.code }, el('p', w.message));
    });
  }

  function num(value, onChange, attrs) {
    return S.numberInput(value, onChange, Object.assign({ step: 'any', inputmode: 'decimal' },
      attrs || {}));
  }

  function setupView(s) {
    var setup = s.setup;
    var ev = evaluate(s, now());
    function n(name, label, hint) {
      return field(label, num(setup[name], act(function (v) { setSetup(name, v); }),
        { 'data-setup': name }), hint);
    }
    function txt(name, label) {
      return field(label, S.textInput(setup[name], function (v) { setSetup(name, v); },
        { 'data-setup': name }));
    }
    var problems = startProblems(setup);
    var range = ev.storageRange;
    var step = setup.testType === 'step';
    return [
      card('The borehole', [
        el('div.grid.grid-3', [
          txt('community', 'Community'), txt('boreholeRef', 'Borehole ref.'),
          txt('client', 'Client'), txt('district', 'District'),
          txt('operator', 'Test conducted by'),
          field('Test type', S.selectInput(setup.testType, [
            { value: 'constant', label: 'Constant discharge' },
            { value: 'step', label: 'Step drawdown' },
          ], act(function (v) { setSetup('testType', v); }), { 'data-setup': 'testType' })),
          n('casingIn', 'Casing diameter (in)'), n('riserIn', 'Riser diameter (in)'),
          n('depthM', 'Hole depth (m)'), n('pumpSettingM', 'Pump setting (m)'),
          n('staticM', 'Static water level (m)', 'Read it before the pump starts'),
          n('plannedRate', step ? 'Step 1 rate (m3/h)' : 'Planned rate (m3/h)'),
          step ? null : n('plannedMin', 'Planned length (min)'),
          step ? n('steps', 'Number of steps (up to 4)') : null,
          step ? n('stepLengthMin', 'Step length (min)') : null,
          n('tLow', 'Transmissivity, low end (m2/day)'),
          n('tHigh', 'Transmissivity, high end (m2/day)'),
        ].filter(Boolean)),
      ]),
      card('Before pumping', [
        el('p', 'Schafer\'s rule puts the end of casing storage at 0.6 (dc² − dp²) ' +
          'divided by the specific capacity. Before any drawdown is read, the ' +
          'specific capacity comes from the transmissivity range above through ' +
          'Logan\'s T ≈ 1.22 Q/s. Over that range, storage lasts ' +
          (isNum(range[0]) && isNum(range[1])
            ? minutesText(range[0]) + ' to ' + minutesText(range[1]) : '—') +
          '. The low end sets the time; once the level is being read, the measured ' +
          'drawdown takes its place.'),
        el('div.callout.callout-warn', { 'data-cp': 'plan' }, [
          el('p', el('strong', 'If the pump starts now, do not stop before ' +
            clockText(ev.stopBefore) + '.')),
          el('p', 'The shortest test that can give a transmissivity here is ' +
            minutesText(ev.plan.total) + (ev.plan.storageBinds
              ? ', set by the casing-storage period.'
              : ', the minimum ' + (step ? 'step length' : 'test length') +
                ' the analysis asks for, which is longer than casing storage.') +
            (step && ev.firstStepBefore ? ' Step 1 must run until ' +
              clockText(ev.firstStepBefore) + '.' : '')),
          ev.planned < ev.plan.total
            ? el('p', { 'data-cp': 'plan-short' }, 'The test as planned, ' +
              minutesText(ev.planned) + ', is shorter than that. Plan to pump until ' +
              clockText(ev.stopBefore) + ' at least.')
            : el('p', 'As planned, the pump stops at ' + clockText(ev.plannedStop) + '.'),
        ]),
        el('div.btn-row', [
          button(s.gps ? 'Take the GPS position again' : 'Record GPS position', takeGps,
            { variant: 'ghost' }),
          s.gps ? el('span.muted', S.sig(s.gps.lat, 7) + ', ' + S.sig(s.gps.lon, 7) +
            ' (within ' + Math.round(s.gps.accuracy || 0) + ' m)') : null,
        ]),
        problems.length ? el('ul', problems.map(function (p) { return el('li', p); })) : null,
        el('div.btn-row', [
          button('Start the pump', act(start), { disabled: problems.length > 0 }),
        ]),
      ]),
    ];
  }

  /* drawdown against log time as it comes in, with the casing period
   * shaded and the depth of the pump intake drawn across */
  function chartView(s, ev) {
    var charts = GWT.charts;
    var swl = s.setup.staticM;
    var pumping = s.readings.filter(function (r) { return r.phase === 'pumping' && r.min > 0; });
    var recovery = s.readings.filter(function (r) { return r.phase === 'recovery' && r.min > 0; });
    if (!charts || (!pumping.length && !recovery.length)) {
      return el('p.muted', 'The plot starts with the first reading.');
    }
    var times = pumping.concat(recovery).map(function (r) { return r.min; });
    var draws = pumping.concat(recovery).map(function (r) { return r.level - swl; });
    var intake = isNum(s.setup.pumpSettingM) ? s.setup.pumpSettingM - swl : null;
    var f = charts.frame({
      width: 720, height: 380, title: 'Drawdown as read',
      xLabel: 'Minutes since the pump started, or stopped (log scale)',
      yLabel: 'Drawdown (m)', xLog: true, yDown: true,
      xDomain: charts.padDomain(times.concat([nextSlot(Math.max.apply(null, times))]), true),
      yDomain: charts.padDomain([0].concat(draws, intake === null ? [] : [intake]), false, 0.08),
    });
    var p = f.palette;
    var NS = 'http://www.w3.org/2000/svg';
    if (isNum(ev.tc)) {
      var rect = global.document.createElementNS(NS, 'rect');
      var x0 = f.margin.left, x1 = Math.min(f.fx(ev.tc), f.margin.left + f.plotW);
      if (x1 > x0) {
        rect.setAttribute('x', String(x0));
        rect.setAttribute('y', String(f.margin.top));
        rect.setAttribute('width', String(x1 - x0));
        rect.setAttribute('height', String(f.plotH));
        rect.setAttribute('fill', p.warning);
        rect.setAttribute('fill-opacity', '0.12');
        f.plot.appendChild(rect);
      }
    }
    if (intake !== null) {
      f.plot.appendChild(charts.polyline([[f.margin.left, f.fy(intake)],
        [f.margin.left + f.plotW, f.fy(intake)]],
      { stroke: p.critical, 'stroke-width': 1.5, 'stroke-dasharray': '6 4' }));
    }
    pumping.forEach(function (r) {
      f.plot.appendChild(charts.marker(f.fx(r.min), f.fy(r.level - swl), 'circle',
        p.accent, p.surface, 4));
    });
    recovery.forEach(function (r) {
      f.plot.appendChild(charts.marker(f.fx(r.min), f.fy(r.level - swl), 'square',
        p.secondary, p.surface, 3.6));
    });
    var entries = [{ label: 'Pumping', kind: 'circle', colour: p.accent }];
    if (recovery.length) entries.push({ label: 'Recovery', kind: 'square', colour: p.secondary });
    if (intake !== null) entries.push({ label: 'Pump intake', kind: 'line', colour: p.critical });
    if (isNum(ev.tc)) entries.push({ label: 'Casing storage', kind: 'square', colour: p.warning });
    charts.legend(f, entries, {});
    return el('div.figure', f.svg);
  }

  /* The bucket timer keeps its timings on the page until they are used; a
   * half-timed bucket is not worth keeping across a reload. */
  var bucket = { litres: 20, timings: [], startedAt: null };

  function dischargeView(s, k) {
    var step = s.steps[k];
    var result = bucketRate(bucket.litres, bucket.timings);
    var stopwatch = bucket.startedAt
      ? button('Stop the watch', act(function () {
        bucket.timings.push(round((now() - bucket.startedAt) / 1000, 2));
        bucket.startedAt = null;
      }), { variant: 'primary' })
      : button(bucket.timings.length >= 3 ? 'Time it again' : 'Start the watch (timing ' +
        (bucket.timings.length + 1) + ' of 3)', act(function () {
        if (bucket.timings.length >= 3) bucket.timings = [];
        bucket.startedAt = now();
      }), { variant: 'ghost' });
    var typed = { rate: null, method: 'flow meter' };
    var reason = { text: step.notMeasured || '' };
    var measuredList = step.discharges.map(function (d) {
      return el('li', S.sig(d.rate, 4) + ' m3/h at minute ' + minuteText(d.min) + ' (' +
        d.method + (isNum(d.bucketL) ? ', ' + d.bucketL + ' L in ' +
          (d.timingsS || []).join(', ') + ' s' : '') + ')');
    });
    return card('Discharge, step ' + (k + 1), [
      measuredList.length ? el('ul', measuredList)
        : step.notMeasured ? el('p', 'Recorded as not measured: ' + step.notMeasured)
          : el('p.muted', 'Not measured yet.'),
      el('h4', 'Bucket and stopwatch'),
      el('div.grid.grid-3', [
        field('Bucket volume (L)', num(bucket.litres, function (v) { bucket.litres = v; },
          { 'data-cp': 'bucket-litres' })),
        field('Timings (s)', S.textInput(bucket.timings.join(', '), function (v) {
          bucket.timings = String(v).split(/[ ,;]+/).map(Number).filter(function (x) {
            return x > 0;
          });
          rerender();
        }, { 'data-cp': 'bucket-timings', placeholder: 'three timings, or use the watch' })),
      ]),
      el('div.btn-row', [
        stopwatch,
        result ? el('span', S.sig(result.rate, 3) + ' m3/h (mean ' +
          S.sig(result.meanSeconds, 3) + ' s)') : el('span.muted', 'Three timings give the rate.'),
        result ? button('Record this rate', act(function () {
          addDischarge(result.rate, 'bucket', { bucketL: bucket.litres,
            timingsS: bucket.timings.slice() }, k);
          bucket.timings = [];
        }), { 'data-cp': 'record-bucket' }) : null,
      ]),
      el('h4', 'Or a meter reading'),
      el('div.btn-row', [
        num(null, function (v) { typed.rate = v; }, { 'data-cp': 'typed-rate',
          placeholder: 'm3/h' }),
        button('Record', act(function () {
          addDischarge(/** @type {number} */ (typed.rate), typed.method, {}, k);
        }), { variant: 'ghost' }),
      ]),
      step.discharges.length ? null : el('div', [
        el('h4', 'Not measured'),
        field('Why the discharge of step ' + (k + 1) + ' was not measured',
          S.textInput(reason.text, function (v) { reason.text = v; },
            { 'data-cp': 'not-measured-reason' })),
        button('Record as not measured', act(function () {
          setNotMeasured(k, reason.text);
        }), { variant: 'ghost' }),
      ]),
    ]);
  }

  function readingsTable(s) {
    var rows = s.readings.slice().reverse().map(function (r) {
      return [r.phase === 'recovery' ? 'Recovery' : 'Step ' + (r.step + 1),
        minuteText(r.min), String(r.level), clockText(r.at),
        r.scheduled ? 'on schedule' : 'as taken'];
    });
    return S.table(['', 'Minute', 'Level (m)', 'Clock', 'Timed'], rows);
  }

  var estimateSeq = 0;

  function estimateView(s) {
    var host = el('div', { 'data-cp': 'estimate' }, el('p.muted', 'Working it out…'));
    var seq = ++estimateSeq;
    liveEstimate(s, now()).then(function (est) {
      if (seq !== estimateSeq) return;
      S.clear(host);
      host.setAttribute('data-state', est ? est.state + (est.stability ? ':' + est.stability : '') : '');
      S.append(host, el('p', est ? estimateNote(est) : 'No readings yet.'));
    }, function (e) {
      if (seq !== estimateSeq) return;
      S.clear(host);
      S.append(host, el('p', 'No estimate: ' + e.message));
    });
    return host;
  }

  function liveView(s) {
    var t = now();
    var ev = evaluate(s, t);
    var sched = ev.schedule;
    var k = currentStep(s);
    var level = { value: null };
    var input = num(null, function (v) { level.value = v; },
      { 'data-cp': 'level', placeholder: 'Depth to water (m)' });
    var problems = saveProblems(s);
    var pumping = s.phase === 'pumping';
    ensureTicker();
    warningsShown = JSON.stringify(ev.warnings);
    return [
      card(pumping ? 'Pumping' : 'Recovery', [
        el('p', { 'data-cp': 'elapsed' }, elapsedText(s, sched)),
        el('p', { style: { fontSize: '2.2rem', fontWeight: '600', margin: '0.2rem 0' },
          'data-cp': 'countdown', 'aria-live': 'polite' },
          sched.due !== null ? 'Read now: the ' + minuteText(sched.due) + '-minute reading'
            : countdownText(sched.seconds)),
        el('p.muted', { 'data-cp': 'next' }, nextText(sched)),
        el('div.btn-row', [
          input,
          button('Record level', act(function () {
            record(/** @type {number} */ (level.value));
          }), { 'data-cp': 'record' }),
          s.readings.length ? button('Undo last reading', act(undoReading),
            { variant: 'ghost' }) : null,
        ]),
        el('div', { 'data-cp': 'warnings' }, warningsView(ev.warnings)),
        pumping ? el('p.muted', 'Planned stop ' + clockText(ev.plannedStop) +
          '; do not stop before ' + clockText(ev.stopBefore) + '.') : null,
      ]),
      card('Drawdown against log time', [chartView(s, ev), estimateView(s)]),
      dischargeView(s, pumping ? k : Math.max(0, Math.min(stepPick, s.steps.length - 1))),
      !pumping && s.steps.length > 1 ? card('Steps', [
        field('Discharge for step', S.selectInput(stepPick, s.steps.map(function (st, i) {
          return { value: i, label: 'Step ' + (i + 1) };
        }), function (v) { stepPick = Number(v); rerender(); })),
      ]) : null,
      card(pumping ? 'The pump' : 'The sheet', [
        pumping && s.setup.testType === 'step' && s.steps.length < MAX_STEPS
          ? el('div.btn-row', [
            num(null, function (v) { stepRate.value = v; },
              { 'data-cp': 'step-rate', placeholder: 'Next step rate (m3/h)' }),
            button('Start step ' + (s.steps.length + 1), act(function () {
              nextStep(stepRate.value);
            }), { variant: 'ghost' }),
          ]) : null,
        pumping ? button('Stop the pump', function () {
          if (now() < ev.stopBefore) {
            S.modal('Stop before ' + clockText(ev.stopBefore) + '?', el('p',
              'Stopping now gives a test too short to read a transmissivity from. ' +
              'Stop only if the pump has to.'), [
              button('Stop anyway', function () {
                document.querySelectorAll('.modal-overlay').forEach(function (n) {
                  n.parentNode.removeChild(n);
                });
                act(stopPump)();
              }, { variant: 'danger' }),
            ]);
            return;
          }
          act(stopPump)();
        }, { 'data-cp': 'stop' }) : null,
        !pumping && problems.length ? el('div.callout.callout-bad', { 'data-cp': 'save-blocked' },
          [el('p', el('strong', 'The workbook cannot be written yet'))].concat(
            problems.map(function (p) { return el('p', p); }))) : null,
        !pumping ? el('div.btn-row', [
          button('Write the workbook (.xlsx)', act(save),
            { disabled: problems.length > 0, 'data-cp': 'save' }),
          button('Use it as this project\'s pumping test', offerToProject,
            { disabled: problems.length > 0, variant: 'ghost' }),
        ]) : null,
        !pumping && s.savedAt ? el('p.muted', 'Written at ' + clockText(s.savedAt) + '.') : null,
      ]),
      card('Readings', [readingsTable(s)]),
      card('The test details', [
        el('details', [
          el('summary', 'Correct a figure entered before the pump started'),
          el('p.muted', 'A change here is logged, and every warning is worked out ' +
            'again from it.'),
          el('div.grid.grid-3', [['staticM', 'Static water level (m)'],
            ['pumpSettingM', 'Pump setting (m)'], ['depthM', 'Hole depth (m)'],
            ['casingIn', 'Casing diameter (in)'], ['riserIn', 'Riser diameter (in)'],
          ].map(function (pair) {
            return field(pair[1], num(s.setup[pair[0]], act(function (v) {
              correctSetup(pair[0], pair[1], v);
            }), { 'data-setup': pair[0] }));
          })),
        ]),
      ]),
      card('', [
        el('div.btn-row', [
          button(s.gps ? 'Take the GPS position again' : 'Record GPS position', takeGps,
            { variant: 'ghost' }),
          button('Discard this test', function () {
            S.modal('Discard this test?', el('p', 'Every reading and discharge of this ' +
              'test is removed from this device. Write the workbook first to keep them.'), [
              button('Discard', function () {
                document.querySelectorAll('.modal-overlay').forEach(function (n) {
                  n.parentNode.removeChild(n);
                });
                discard();
                rerender();
              }, { variant: 'danger' }),
            ]);
          }, { variant: 'ghost' }),
        ]),
      ]),
    ];
  }

  var stepPick = 0;
  var stepRate = { value: null };

  function page() {
    var s = session() || blankSession();
    var live = s.phase === 'pumping' || s.phase === 'recovery';
    return [
      el('div.page-head', [
        el('h1', 'Pumping test co-pilot'),
        el('p.lead', 'Plans the test before the pump starts, keeps the reading ' +
          'schedule, warns while the test can still be put right, and writes ' +
          'the standard pumping test workbook.'),
      ]),
      el('p.muted', C.phrase('pumping_copilot.browser_only')),
    ].concat(live ? liveView(s) : setupView(s));
  }

  /* A live test reopened, by a reload or a phone waking, picks its sound
   * and countdown up again as soon as this module is back. */
  if (global.document) {
    var reopened = GWT.app && GWT.app.store && GWT.app.store.get(KEY);
    if (reopened && (reopened.phase === 'pumping' || reopened.phase === 'recovery')) {
      ensureTicker();
    }
  }

  GWT.pumpCopilot = {
    page: page, session: session, evaluate: evaluate, tick: tick,
    start: start, record: record, undoReading: undoReading,
    addDischarge: addDischarge, setNotMeasured: setNotMeasured,
    nextStep: nextStep, stopPump: stopPump, setGps: setGps, discard: discard,
    setSetup: setSetup, correctSetup: correctSetup, saveProblems: saveProblems,
    workbook: workbook,
    workbookSheets: workbookSheets, save: save, useInProject: useInProject,
    liveEstimate: liveEstimate, estimateNote: estimateNote,
    bucketRate: bucketRate, nextSlot: nextSlot, scheduleAt: scheduleAt,
    SCHEDULE_MIN: SCHEDULE_MIN,
    beeps: function () { return beepCount; },
  };
  (GWT.loadedBundles || (GWT.loadedBundles = {})).pumpCopilot = true;
}(typeof window !== 'undefined' ? window : globalThis));

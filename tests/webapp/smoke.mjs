/* Drive the whole app in headless Chromium: load each sample, visit every
 * page, build every report, and fail on any console error or missing output.
 */
import { readFile } from 'node:fs/promises';
import { withPage } from './harness.mjs';
import { timeAutosaves } from './heavy.mjs';

/* the app as a copy on disk, opened without a server */
const FROM_DISK = new URL('../../docs/index.html', import.meta.url).href;

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

const PAGES = ['overview', 'guided', 'site', 'ves', 'vescopilot', 'design', 'drillcopilot', 'spine',
  'pumping', 'pumpcopilot', 'quality', 'costing', 'procurement', 'supervision', 'handover',
  'templates', 'extract',
  'waterpoints', 'coverage', 'portfolio', 'registry', 'settings', 'about'];

await withPage(async (page, base, consoleErrors) => {
  const downloads = [];
  page.on('download', (d) => downloads.push(d.suggestedFilename()));

  await page.goto(base + '/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app);
  check('app boots', true);

  // Long Tasks from here on. The inversion and the pumping analysis run in
  // the engine worker, and the checks below hold the page's own thread to it:
  // a task over 50 ms here, while either is computing, is a page that has
  // stopped answering.
  await page.evaluate(() => {
    window.__longTasks = [];
    new PerformanceObserver((list) => {
      list.getEntries().forEach((e) => window.__longTasks.push(
        { start: e.startTime, duration: e.duration }));
    }).observe({ type: 'longtask', buffered: true });
    /* the long tasks that overlap any of these [from, to] windows */
    window.__longDuring = (windows) => window.__longTasks.filter((t) =>
      windows.some((w) => t.start < w[1] && t.start + t.duration > w[0]));
    /* JSON that keeps a model's Infinity and a NaN, so two results can be
     * compared across pages */
    window.__serialise = (value) => JSON.stringify(value, (k, x) =>
      (typeof x === 'number' && !Number.isFinite(x) ? String(x) : x));
  });

  // The About page names the release, from the bundle build_webapp_data.py
  // wrote out of pyproject.toml; test_web_build.py holds that to the package.
  const version = await page.evaluate(() => {
    window.GWT.app.goto('about');
    const shown = document.querySelector('#page-host .about-version');
    return { bundled: window.GWT.data.version, shown: shown ? shown.textContent : '' };
  });
  check('about: the page names the release it is',
    /^\d+\.\d+\.\d+/.test(version.bundled || '') &&
    version.shown.includes('Version ' + version.bundled), JSON.stringify(version));

  // every page renders with an empty project
  for (const key of PAGES) {
    await page.evaluate((k) => window.GWT.app.goto(k), key);
    await page.waitForTimeout(60);
    const info = await page.evaluate(() => ({
      html: document.querySelector('#page-host').innerHTML.length,
      bad: !!document.querySelector('.callout-bad p strong'),
      badText: document.querySelector('.callout-bad p strong')?.textContent || '',
    }));
    check(`empty project: ${key} renders`, info.html > 200 &&
      info.badText !== 'Something went wrong drawing this page.',
      `${info.html} chars, ${info.badText}`);
  }

  // load the full sample and check the analyses appear
  await page.evaluate(() => window.GWT.app.goto('overview'));
  await page.evaluate(async () => {
    const btns = Array.from(document.querySelectorAll('button'));
    const btn = btns.find((b) => b.textContent.includes('Load Dr Timbo'));
    btn.click();
  });
  await page.waitForFunction(
    () => window.GWT.app.recomputeState.generation > 0 &&
          window.GWT.app.recomputeState.running === 0 &&
          window.GWT.app.derived.analysis !== null,
    { timeout: 60000 });
  check('dr_timbo sample loads', true);

  const pumpingRun = await page.evaluate(() => {
    const runs = window.GWT.engine.history()
      .filter((h) => h.type === 'analysePumping' && h.outcome === 'done');
    return {
      modes: runs.map((h) => h.mode),
      long: window.__longDuring(runs.map((h) => h.ran)),
    };
  });
  check('engine: the pumping test was analysed in the worker',
    pumpingRun.modes.length > 0 && pumpingRun.modes.every((m) => m === 'worker'),
    JSON.stringify(pumpingRun.modes));
  check('engine: no main-thread task over 50 ms while the pumping test was analysed',
    pumpingRun.long.length === 0, JSON.stringify(pumpingRun.long));

  const state = await page.evaluate(() => {
    const d = window.GWT.app.derived;
    return {
      log: !!d.log, test: !!d.test, analysis: !!d.analysis,
      sample: !!d.sample, assessment: !!d.assessment, design: !!d.design,
      estimate: !!d.estimate,
      T: d.analysis && d.analysis.transmissivity_m2_per_day,
      safe: d.analysis && d.analysis.yield_recommendation.safe_yield_m3_per_h,
      screens: d.design && d.design.screens.length,
      cost: d.estimate && d.estimate.total_cost_usd,
    };
  });
  check('drilling log parsed', state.log);
  check('pumping test analysed', state.analysis && state.T > 0, `T=${state.T}`);
  check('yield computed', state.safe > 0, `safe=${state.safe}`);
  check('water quality assessed', state.assessment);
  check('design assembled', state.design && state.screens > 0, `screens=${state.screens}`);
  check('cost estimated', state.estimate && state.cost > 0, `cost=${state.cost}`);

  // every page renders with a full project, and figures actually draw
  for (const key of PAGES) {
    await page.evaluate((k) => window.GWT.app.goto(k), key);
    await page.waitForTimeout(120);
    const info = await page.evaluate(() => ({
      html: document.querySelector('#page-host').innerHTML.length,
      svgs: document.querySelectorAll('#page-host svg').length,
      badText: document.querySelector('.callout-bad p strong')?.textContent || '',
      tables: document.querySelectorAll('#page-host table.data').length,
    }));
    check(`loaded project: ${key} renders`,
      info.html > 200 && info.badText !== 'Something went wrong drawing this page.',
      `${info.html} chars, ${info.svgs} svg, ${info.tables} tables, ${info.badText}`);
  }

  // figures present where they must be
  for (const [key, minSvg] of [['pumping', 2], ['quality', 2], ['design', 1], ['costing', 2]]) {
    await page.evaluate((k) => window.GWT.app.goto(k), key);
    await page.waitForTimeout(150);
    const n = await page.evaluate(() => document.querySelectorAll('#page-host svg').length);
    check(`${key}: ${minSvg}+ figures drawn`, n >= minSvg, `found ${n}`);
  }

  // rokel sample: the VES chain. A timer is sampled while it inverts, and the
  // main pane is scrolled with the mouse wheel as it does, the way a hand on a
  // trackpad would: a page frozen by the inversion shows as a gap in both.
  await page.evaluate(() => window.GWT.app.goto('overview'));
  const beforeRokel = await page.evaluate(() => {
    const probe = window.__probe = { ticks: [], scrolls: [] };
    probe.timer = setInterval(() => probe.ticks.push(performance.now()), 20);
    document.querySelector('#main').addEventListener('scroll',
      () => probe.scrolls.push(performance.now()), { passive: true });
    const last = Math.max(0, ...window.GWT.engine.history().map((h) => h.id));
    Array.from(document.querySelectorAll('button'))
      .find((b) => b.textContent.includes('Load Rokel')).click();
    return last;
  });
  await page.waitForFunction(() => window.GWT.app.working('invert'), { timeout: 60000 });
  await page.mouse.move(900, 500);
  for (let i = 0; i < 6; i += 1) {
    await page.mouse.wheel(0, i % 2 ? -400 : 400);
    await page.waitForTimeout(200);
  }
  await page.waitForFunction(() => {
    const d = window.GWT.app.derived;
    return d.interpretations && d.interpretations.length > 0;
  }, { timeout: 120000 });
  const ves = await page.evaluate(() => ({
    n: window.GWT.app.derived.interpretations.length,
    errs: window.GWT.app.derived.inversions.map((r) => r.fit_error_percent),
    ranked: window.GWT.app.derived.interpretations.map((i) => i.rank),
  }));
  check('rokel: soundings inverted', ves.n > 0, `${ves.n} soundings`);
  check('rokel: fits converged', ves.errs.every((e) => e < 60),
    `errors ${ves.errs.map((e) => e.toFixed(1)).join(', ')}`);
  check('rokel: ranked', ves.ranked.every((r) => r >= 1), JSON.stringify(ves.ranked));

  await page.evaluate(() => window.GWT.app.goto('ves'));
  await page.waitForTimeout(200);
  const vesSvgs = await page.evaluate(() => document.querySelectorAll('#page-host svg').length);
  check('ves page draws curves', vesSvgs >= 2, `found ${vesSvgs}`);

  // The chance of a working borehole (PLAN.md step 3.3) sits beside the
  // suitability score: a column of the table, and each point's sentences and
  // breakdown, the engine's words. With no range sampled yet the page says
  // the depth and basement evidence are left out.
  const oddsPage = await page.evaluate(() => {
    const app = window.GWT.app, C = window.GWT.core;
    const host = document.querySelector('#page-host');
    const heads = Array.from(host.querySelectorAll('th')).map((th) => th.textContent);
    const points = Array.from(host.querySelectorAll('.odds-point')).map((p) => p.textContent);
    const odds = app.surveyOdds();
    return { heads, points, words: odds.map((o) => C.oddsPointText(o).join(' ')),
      basis: C.oddsBasisText(odds[0]).join(' '),
      shorts: odds.map((o) => C.oddsShort(o)), cells: host.textContent,
      n: app.derived.interpretations.length };
  });
  check('odds: the VES page shows the chance beside the suitability score',
    oddsPage.heads.includes('Chance of a working borehole') &&
    oddsPage.shorts.every((t) => oddsPage.cells.includes(t)), JSON.stringify(oddsPage.shorts));
  check('odds: each point\'s sentences and breakdown, in the engine\'s words',
    oddsPage.points.length === oddsPage.n &&
    oddsPage.words.every((w) => oddsPage.points.some((p) => p.includes(w))) &&
    oddsPage.points.every((p) => p.includes('has not been sampled') &&
      p.includes('Chance after (percent)')) && oddsPage.cells.includes(oddsPage.basis),
    JSON.stringify(oddsPage.points).slice(0, 800));

  // The programme estimate keeps the rate typed for it; the survey's odds at
  // its first-ranked point are offered beside it and used only on a click.
  const programmeOdds = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core;
    const before = app.store.get('costing.success_rate');
    await app.goto('costing');
    const button = Array.from(document.querySelectorAll('#page-host button'))
      .find((b) => /^Use \d+ percent$/.test(b.textContent));
    const offered = document.querySelector('#page-host .callout').textContent;
    const first = C.assessSiting(app.derived.interpretations, app.config().ves)[0];
    const odds = app.surveyOdds().find((o) => o.sounding_id === first.sounding_id);
    const untouched = app.store.get('costing.success_rate');
    const attemptsBefore = app.derived.programme ? app.derived.programme.n_attempted : null;
    button.click();
    await new Promise((r) => setTimeout(r, 100));
    const used = app.store.get('costing.success_rate');
    const programme = app.derived.programme;
    app.store.set('costing.success_rate', before);
    await app.goto('ves');
    return { before, untouched, used, rate: C.programmeRate(odds), label: button.textContent,
      offered, sentence: C.programmeOffer(odds), attemptsBefore,
      percent: programme ? programme.success_rate_percent : null };
  });
  check('odds: the programme estimate keeps its typed rate until the odds are chosen',
    programmeOdds.untouched === programmeOdds.before &&
    programmeOdds.offered.includes(programmeOdds.sentence) &&
    programmeOdds.label === `Use ${programmeOdds.rate} percent`,
    JSON.stringify(programmeOdds));
  check('odds: choosing them sets the programme\'s success rate',
    programmeOdds.used === programmeOdds.rate &&
    (programmeOdds.percent === null || programmeOdds.percent === programmeOdds.rate),
    JSON.stringify(programmeOdds));

  // --- the engine worker ----------------------------------------------------
  // PLAN.md step 1.2: during an inversion no main-thread task longer than
  // 50 ms, and the page keeps scrolling. The windows are the engine's own
  // record of when each sounding was being inverted.
  const inverting = await page.evaluate((after) => {
    const probe = window.__probe;
    clearInterval(probe.timer);
    const runs = window.GWT.engine.history()
      .filter((h) => h.id > after && h.type === 'invert' && h.outcome === 'done');
    const windows = runs.map((h) => h.ran);
    const from = Math.min(...windows.map((w) => w[0]));
    const to = Math.max(...windows.map((w) => w[1]));
    const ticks = [from].concat(probe.ticks.filter((t) => t > from && t < to), [to]);
    let gap = 0;
    for (let i = 1; i < ticks.length; i += 1) gap = Math.max(gap, ticks[i] - ticks[i - 1]);
    return {
      modes: runs.map((h) => h.mode),
      ms: Math.round(to - from),
      long: window.__longDuring(windows),
      ticks: ticks.length - 2,
      gap: Math.round(gap),
      scrolls: probe.scrolls.filter((t) => t > from && t < to).length,
    };
  }, beforeRokel);
  check('engine: the Rokel soundings were inverted in the worker',
    inverting.modes.length === ves.n && inverting.modes.every((m) => m === 'worker'),
    JSON.stringify(inverting.modes));
  check('engine: no main-thread task over 50 ms while the Rokel soundings inverted',
    inverting.long.length === 0, JSON.stringify(inverting.long));
  check('engine: timers kept firing and the page kept scrolling while it inverted',
    inverting.ticks >= inverting.ms / 100 && inverting.gap < 250 && inverting.scrolls > 0,
    JSON.stringify(inverting));

  // Cancel has to stop an inversion part way through a fit, not after it. A
  // worker busy in a fit reads no messages, so this is the worker being
  // stopped. What was there before is kept, and the next run starts in a
  // fresh worker and gives the same answer.
  const cancelled = await page.evaluate(async () => {
    const app = window.GWT.app, engine = window.GWT.engine;
    const before = window.__serialise(app.derived.inversions);
    app.goto('ves');
    Array.from(document.querySelectorAll('#page-host button'))
      .find((b) => b.textContent === 'Re-run inversion').click();
    let bar = null, fill = 0;
    for (let i = 0; i < 400; i += 1) {
      await new Promise((r) => setTimeout(r, 25));
      bar = document.querySelector('#work-status .work-bar[data-work="invert"]');
      fill = bar ? parseFloat(bar.querySelector('.progress-fill').style.width) : 0;
      if (bar && fill > 0 && fill < 100) break;
    }
    const shown = bar ? bar.textContent : '';
    const pressed = performance.now();
    bar.querySelector('button').click();
    while (app.working('invert') && performance.now() - pressed < 5000) {
      await new Promise((r) => setTimeout(r, 10));
    }
    const stoppedIn = Math.round(performance.now() - pressed);
    await new Promise((r) => setTimeout(r, 100));
    const last = engine.history().filter((h) => h.type === 'invert').pop();
    const after = {
      kept: window.__serialise(app.derived.inversions) === before,
      barGone: !document.querySelector('#work-status .work-bar'),
      page: document.querySelector('#page-host').textContent.includes('Re-run inversion'),
    };
    await app.runInversions();
    return {
      fill, shown, stoppedIn, outcome: last.outcome, after,
      again: window.__serialise(app.derived.inversions) === before,
      rerun: engine.history().filter((h) => h.type === 'invert').slice(-2)
        .map((h) => h.mode + ':' + h.outcome),
    };
  });
  check('cancel: the work bar shows the inversion part way, with a Cancel button',
    cancelled.fill > 0 && cancelled.fill < 100 &&
    cancelled.shown.includes('Inverting 2 soundings') && cancelled.shown.includes('Cancel'),
    JSON.stringify(cancelled));
  check('cancel: Cancel stops the inversion mid-fit, at once',
    cancelled.outcome === 'cancelled' && cancelled.stoppedIn < 1000 &&
    cancelled.after.barGone, JSON.stringify(cancelled));
  check('cancel: a stopped run leaves the results it would have replaced',
    cancelled.after.kept && cancelled.after.page, JSON.stringify(cancelled.after));
  check('cancel: the next run goes to the end in a fresh worker, with the same answer',
    cancelled.again && cancelled.rerun.every((r) => r === 'worker:done'),
    JSON.stringify(cancelled.rerun));

  // The range of models (PLAN.md step 3.1) is sampled in the engine worker,
  // a sounding at a time, with its progress in the work bar, and it is shown
  // beside the best fit: the sentences the engine writes, and a fan of the
  // models that fit drawn over the curve. A short run here; the default
  // settings are timed in bench/ and compared with Python in parity.mjs.
  const ranged = await page.evaluate(async () => {
    const app = window.GWT.app, engine = window.GWT.engine, C = window.GWT.core;
    const saved = app.store.get('config');
    app.store.set('config', Object.assign({}, saved || {}, {
      ves_range: { samples: 1200, burn_in: 200, starts: 3, chains: 2 } }));
    app.goto('ves');
    const mark = Math.max(0, ...engine.history().map((h) => h.id));
    const inversions = app.derived.inversions.slice();
    Array.from(document.querySelectorAll('#page-host button'))
      .find((b) => b.textContent === 'Sample the range of models').click();
    let fill = 0, shown = '';
    for (let i = 0; i < 800 && !(fill > 0 && fill < 100); i += 1) {
      await new Promise((r) => setTimeout(r, 25));
      const bar = document.querySelector('#work-status .work-bar[data-work="range"]');
      if (bar) {
        fill = parseFloat(bar.querySelector('.progress-fill').style.width) || 0;
        shown = bar.textContent;
      }
    }
    const began = performance.now();
    while (app.working('range') && performance.now() - began < 60000) {
      await new Promise((r) => setTimeout(r, 25));
    }
    await new Promise((r) => setTimeout(r, 200));
    const runs = engine.history().filter((h) => h.id > mark && h.type === 'sampleRange');
    const callouts = Array.from(document.querySelectorAll('#page-host .callout-info'))
      .map((c) => c.textContent).filter((t) => t.includes('Range of models that fit'));
    const legends = Array.from(document.querySelectorAll('#page-host svg'))
      .filter((svg) => svg.textContent.includes('Models that fit')).length;
    /* the same sounding, inversion and settings, straight to the engine */
    const id = app.derived.interpretations[1].sounding_id;
    const sounding = app.derived.soundings.find((s) => s.sounding_id === id);
    const direct = C.modelRangeText(C.sampleModelRange(sounding, inversions[1],
      app.config())).join(' ');
    /* the odds read the sampled ranges: the depth and basement evidence */
    const oddsSampled = Array.from(document.querySelectorAll('#page-host .odds-point'))
      .map((p) => p.textContent);
    const oddsWords = app.surveyOdds().map((o) => C.oddsPointText(o).join(' '));
    app.store.set('config', saved);
    app.render();
    const after = Array.from(document.querySelectorAll('#page-host .callout-info'))
      .filter((c) => c.textContent.includes('Range of models that fit')).length;
    return { fill, shown, modes: runs.map((h) => h.mode + ':' + h.outcome), callouts,
      legends, direct, after, n: inversions.length, oddsSampled, oddsWords };
  });
  check('odds: a sampled range brings in the depth and basement evidence',
    ranged.oddsSampled.length === ranged.n &&
    ranged.oddsSampled.every((p) => !p.includes('has not been sampled') &&
      !p.includes('range not sampled')) &&
    ranged.oddsWords.every((w) => ranged.oddsSampled.some((p) => p.includes(w))),
    JSON.stringify(ranged.oddsSampled).slice(0, 800));
  check('range: sampled in the worker, a sounding at a time',
    ranged.modes.length === ranged.n && ranged.modes.every((m) => m === 'worker:done'),
    JSON.stringify(ranged.modes));
  check('range: the work bar shows it part way, with a Cancel button',
    ranged.fill > 0 && ranged.fill < 100 &&
    ranged.shown.includes('Sampling the range of models') && ranged.shown.includes('Cancel'),
    JSON.stringify([ranged.fill, ranged.shown]));
  check('range: each sounding shows the sentences beside its best fit, and its fan',
    ranged.callouts.length === ranged.n && ranged.legends === ranged.n &&
    ranged.callouts.every((t) => /Basement (between|not resolved)/.test(t)),
    JSON.stringify(ranged.callouts));
  check('range: the worker\'s range is the engine\'s, word for word',
    ranged.callouts[1] && ranged.callouts[1].includes(ranged.direct),
    `page ${ranged.callouts[1]}\n     direct ${ranged.direct}`);
  check('range: a range sampled with other settings is not shown as this one',
    ranged.after === 0, String(ranged.after));

  // Cancel stops the sounding being sampled (the worker is stopped with it)
  // and the ones after it; and a recompute that replaces the inversions
  // while a range runs stops it rather than sampling around inversions no
  // longer on show, which used to read the cleared interpretations and throw.
  const stopped = await page.evaluate(async () => {
    const app = window.GWT.app, engine = window.GWT.engine;
    const saved = app.store.get('config');
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    app.store.set('config', Object.assign({}, saved || {}, {
      ves_range: { samples: 40000, burn_in: 200, starts: 3, chains: 2 } }));
    let mark = Math.max(0, ...engine.history().map((h) => h.id));
    const run = app.sampleRanges();
    for (let i = 0; i < 400 && !app.working('range'); i += 1) await wait(10);
    await wait(300);
    const began = performance.now();
    app.cancelWork('range');
    await run;
    const cancelMs = performance.now() - began;
    await wait(300);
    const cancelled = engine.history().filter((h) => h.id > mark && h.type === 'sampleRange')
      .map((h) => h.mode + ':' + h.outcome);
    const kept = app.derived.inversions.map((inv) => !!app.rangeFor(inv));

    app.store.set('config', Object.assign({}, saved || {}, {
      ves_range: { samples: 400, burn_in: 100, starts: 2, chains: 2 } }));
    mark = Math.max(0, ...engine.history().map((h) => h.id));
    const inversions = app.derived.inversions, interpretations = app.derived.interpretations;
    let error = null;
    const raced = app.sampleRanges();
    /* what a recompute does while it inverts afresh */
    app.derived.inversions = null;
    app.derived.interpretations = null;
    try { await raced; } catch (e) { error = String(e); }
    const racedRuns = engine.history().filter((h) => h.id > mark && h.type === 'sampleRange')
      .length;
    app.derived.inversions = inversions;
    app.derived.interpretations = interpretations;
    app.store.set('config', saved);
    app.render();
    return { cancelled, cancelMs, kept, working: app.working('range'), error, racedRuns };
  });
  check('range: Cancel stops the sampling in the worker, and nothing after it starts',
    stopped.cancelled.length === 1 && stopped.cancelled[0] === 'worker:cancelled' &&
    stopped.kept.every((k) => !k) && !stopped.working && stopped.cancelMs < 2000,
    JSON.stringify(stopped));
  check('range: a recompute mid-run stops the range rather than throwing',
    stopped.error === null && stopped.racedRuns === 1, JSON.stringify(stopped));

  // Opened from file:// a browser will not start a worker, and a worker can
  // fail to load; the page then runs the same tasks itself. Worker, page and
  // a direct call to the engine have to agree on everything: the numbers, the
  // Infinity at the foot of a model, the type of every value, and which
  // objects are one object - an analysis and the test it holds. Structured
  // clone is what carries a result out of the worker, and it drops functions
  // and prototypes and copies what it keeps, so the whole graph is compared.
  const agree = await page.evaluate(async () => {
    const app = window.GWT.app, engine = window.GWT.engine;
    const C = window.GWT.core, S = window.GWT.support;
    function differ(a, b, path, seen) {
      if (typeof a !== typeof b) return path + ': ' + typeof a + ' against ' + typeof b;
      if (typeof a === 'function') return path + ': a function';
      if (a === null || b === null || typeof a !== 'object') {
        return Object.is(a, b) ? null : path + ': ' + String(a) + ' against ' + String(b);
      }
      if (seen.a.has(a) || seen.b.has(b)) {
        return seen.a.get(a) === b && seen.b.get(b) === a ? null
          : path + ': one object in one result and two in the other';
      }
      seen.a.set(a, b);
      seen.b.set(b, a);
      const ta = Object.prototype.toString.call(a), tb = Object.prototype.toString.call(b);
      if (ta !== tb || Object.getPrototypeOf(a) !== Object.getPrototypeOf(b)) {
        return path + ': ' + ta + ' against ' + tb;
      }
      if (Array.isArray(a) && a.length !== b.length) {
        return path + ': ' + a.length + ' items against ' + b.length;
      }
      const ka = Object.keys(a), kb = Object.keys(b);
      if (ka.join('|') !== kb.join('|')) return path + ': keys ' + ka + ' against ' + kb;
      for (const k of ka) {
        const d = differ(a[k], b[k], path + '.' + k, seen);
        if (d) return d;
      }
      return null;
    }
    const same = (a, b) => differ(a, b, 'result', { a: new Map(), b: new Map() });
    window.__same = same;

    const cfg = app.config();
    const soundings = app.derived.soundings;
    const short = structuredClone(soundings[0]);
    short.rho_app = short.rho_app.map((v, i) => (i < 3 ? v : 0));
    /* the two pumping samples, and Kuntolo with its discharges entered by
     * hand, which makes it a step test with fits to make */
    const inputs = [];
    for (const [key, manual] of [['dr_timbo', {}], ['kuntolo', {}],
      ['kuntolo', { 1: 1.5, 2: 2.2, 3: '3.0' }]]) {
      const files = window.GWT.data.samples[key].files, sources = {};
      for (const role of Object.keys(files)) {
        sources[role] = { name: files[role].name,
          sheets: await S.readXlsx(S.base64ToBytes(files[role].b64)) };
      }
      inputs.push({ config: cfg, sources, manualDischarges: manual });
    }

    /* the engine called directly, as the page used to */
    const direct = { invert: soundings.map((s) => C.invertSounding(s, { config: cfg })),
      recompute: [], analyse: [] };
    inputs.forEach((input) => {
      const src = structuredClone(input.sources), out = {};
      if (src.drilling) out.log = C.drillingFromGrid(src.drilling.sheets[0].rows, src.drilling.name);
      if (src.pumping) {
        out.test = C.pumpingFromGrid(src.pumping.sheets[0].rows, src.pumping.name);
        out.test.steps.forEach((step) => {
          const q = input.manualDischarges[step.step_number];
          if (q !== undefined) step.discharge_m3_per_h = Number(q);
        });
      }
      if (src.quality) {
        out.sample = C.qualityFromGrid(src.quality.sheets[0].rows, src.quality.name);
        out.assessment = C.assessSample(out.sample);
      }
      direct.recompute.push(out);
      direct.analyse.push(C.analysePumpingTest(structuredClone(out.test), cfg));
    });
    try { C.invertSounding(short, { config: cfg }); direct.error = 'no error'; }
    catch (e) { direct.error = e.name + ': ' + e.message; }

    /* every request, and where each one actually ran: an answer the worker
     * could not send back is worked out on the page instead, quietly */
    async function through(onPage) {
      engine.forcePage(onPage);
      const first = Math.max(0, ...engine.history().map((h) => h.id));
      try {
        const r = { invert: [], recompute: [], analyse: [] };
        for (const s of soundings) r.invert.push(await engine.invert(s, cfg));
        for (const input of inputs) {
          const derived = await engine.recompute(input);
          r.recompute.push(derived);
          r.analyse.push(await engine.analysePumping(derived.test, cfg));
        }
        r.error = await engine.invert(short, cfg)
          .then(() => 'no error', (e) => e.name + ': ' + e.message);
        r.ran = engine.history().filter((h) => h.id > first).map((h) => h.mode);
        return r;
      } finally {
        engine.forcePage(false);
      }
    }
    const worker = await through(false), onPage = await through(true);
    /* the Long Tasks readings have to be able to see an inversion at all, or
     * finding none while the worker inverts proves nothing: the same
     * soundings inverted on the page must show up in them */
    await new Promise((r) => setTimeout(r, 200));
    const pageInversions = engine.history().filter((h) =>
      h.type === 'invert' && h.mode === 'page' && h.outcome === 'done').slice(-soundings.length);
    const seen = window.__longDuring(pageInversions.map((h) => h.ran));
    const parsed = (r) => r.recompute.map((d) => {
      const out = {};
      ['log', 'test', 'sample', 'assessment'].forEach((k) => { if (d[k]) out[k] = d[k]; });
      return out;
    });
    return {
      ran: [worker.ran, onPage.ran],
      requests: soundings.length + 2 * inputs.length + 1,
      app: same(direct.invert, app.derived.inversions),
      worker: [same(direct.invert, worker.invert), same(direct.recompute, parsed(worker)),
        same(direct.analyse, worker.analyse)],
      page: [same(direct.invert, onPage.invert), same(direct.recompute, parsed(onPage)),
        same(direct.analyse, onPage.analyse)],
      both: same(worker.recompute, onPage.recompute),
      /* flags an analysis holds that are the very objects on its test */
      shared: worker.analyse.map((a, i) => [
        direct.analyse[i].flags.filter((f) => direct.analyse[i].test.flags.includes(f)).length,
        a.flags.filter((f) => a.test.flags.includes(f)).length]),
      fitted: worker.analyse.map((a) => [a.transmissivity_m2_per_day, !!a.step_test]),
      errors: [direct.error, worker.error, onPage.error],
      pageLong: { inversions: pageInversions.length,
        longest: Math.round(Math.max(0, ...seen.map((t) => t.duration))) },
    };
  });
  check('engine: the Long Tasks readings see an inversion run on the page',
    agree.pageLong.inversions === ves.n &&
    agree.pageLong.longest > 50, JSON.stringify(agree.pageLong));
  check('engine: the worker returns what a direct call to the engine returns',
    agree.ran[0].length === agree.requests && agree.ran[0].every((m) => m === 'worker') &&
    agree.app === null &&
    agree.worker.every((d) => d === null), JSON.stringify(agree));
  check('engine: the page\'s own path returns the same, to the last bit',
    agree.ran[1].length === agree.requests && agree.ran[1].every((m) => m === 'page') &&
    agree.page.every((d) => d === null) &&
    agree.both === null, JSON.stringify(agree));
  check('engine: a fitted step test is among the analyses compared',
    agree.fitted[0][0] > 0 && agree.fitted[2][1] === true, JSON.stringify(agree.fitted));
  check('engine: an analysis still holds its flags as the ones on its test',
    agree.shared.some((n) => n[0] > 0) && agree.shared.every((n) => n[0] === n[1]),
    JSON.stringify(agree.shared));
  check('engine: an engine error comes back with its own message, either way',
    agree.errors[0] === 'Error: Not enough readings to invert' &&
    agree.errors.every((e) => e === agree.errors[0]), JSON.stringify(agree.errors));

  // PLAN.md step 1.6: a saved survey reopens without inverting anything, and
  // the models it shows are the ones the inversion gave, to the last bit and
  // as the same object graph. A changed reading, a changed setting, another
  // engine or a damaged entry inverts again - only what it has to - and a
  // recompute keeps what is still good. engine.invert is watched rather than
  // the history, which forgets and records only what finished.
  const reused = await page.evaluate(async () => {
    const app = window.GWT.app, engine = window.GWT.engine;
    const C = window.GWT.core, S = window.GWT.support, same = window.__same;
    const realInvert = engine.invert;
    const calls = [];
    engine.invert = function (sounding) {
      calls.push(sounding.sounding_id);
      return realInvert.apply(this, arguments);
    };
    const since = () => calls.splice(0).length;
    const until = async (test) => {
      for (let i = 0; i < 2400 && !test(); i += 1) await new Promise((r) => setTimeout(r, 25));
      return test();
    };
    const out = {};
    try {
      const before = app.derived.inversions;
      const ranks = JSON.stringify(app.derived.interpretations.map((i) => [i.sounding_id, i.rank]));
      const saved = JSON.stringify(app.projectPayload());
      const file = JSON.parse(saved);
      out.entries = Object.keys(file.state.inversionCache || {}).length;

      // reopening: nothing inverted, the same results
      await app.loadProject(saved);
      out.reopen = { calls: since(), same: same(before, app.derived.inversions),
        ranks: JSON.stringify(app.derived.interpretations
          .map((i) => [i.sounding_id, i.rank])) === ranks,
        working: app.working('invert') };

      // a discharge typed on the Pumping test page, the way a user types it
      const kuntolo = window.GWT.data.samples.kuntolo.files.pumping;
      app.store.set('sources.pumping', { name: kuntolo.name, b64: kuntolo.b64,
        sample: kuntolo.path });
      await app.recompute();
      out.addSheet = { calls: since(), n: (app.derived.inversions || []).length };
      async function typeDischarge(value) {
        app.goto('pumping');
        const generation = app.recomputeState.generation;
        const input = document.querySelector('#page-host input.cell');
        input.value = String(value);
        input.dispatchEvent(new Event('change'));
        await until(() => app.recomputeState.generation > generation);
      }
      await typeDischarge(1.5);
      out.discharge = { calls: since(), n: (app.derived.inversions || []).length,
        q: app.derived.test.steps[0].discharge_m3_per_h, same: same(before, app.derived.inversions) };

      // ...and typed while the survey is still inverting: the run carries on
      const mark = Math.max(0, ...engine.history().map((h) => h.id));
      const running = app.runInversions();
      await until(() => calls.length > 0 && app.working('invert'));
      out.whileRunning = { typedWhileRunning: app.working('invert') };
      await typeDischarge(2.2);
      await running;
      out.whileRunning.calls = since();
      out.whileRunning.n = (app.derived.inversions || []).length;
      out.whileRunning.q = app.derived.test.steps[0].discharge_m3_per_h;
      out.whileRunning.cancelled = engine.history().filter((h) =>
        h.id > mark && h.type === 'invert' && h.outcome === 'cancelled').length;
      app.goto('ves');
      await new Promise((r) => setTimeout(r, 100));
      out.whileRunning.page = !document.querySelector('#page-host').textContent
        .includes('not yet inverted');

      // a changed reading: that sounding alone is inverted again
      await app.loadProject(saved);
      since();
      const sheets = await S.readXlsx(S.base64ToBytes(app.store.get('sources.ves').b64));
      const row = sheets[1].rows.find((r) => r[0] === 1 && r[3] !== undefined && r[3] !== null);
      row[3] = String(Number(row[3]) * 1.05);
      app.store.set('sources.ves', Object.assign({}, app.store.get('sources.ves'),
        { b64: S.bytesToBase64(await S.writeXlsx(sheets)) }));
      await app.recompute();
      await app.inversionsSettled();
      out.reading = { calls: calls.slice(), n: app.derived.inversions.length,
        firstSame: same(before[0], app.derived.inversions[0]),
        entries: Object.keys(app.store.get('inversionCache')).length };
      since();

      // a changed setting: every sounding again
      await app.loadProject(saved);
      since();
      app.store.set('config.ves.damping', 0.021);
      await app.recompute();
      await app.inversionsSettled();
      out.config = { calls: since(), n: app.derived.inversions.length };

      // another engine: the same file, and nothing in it is found
      const digest = window.GWT.data.engineDigest;
      window.GWT.data.engineDigest = digest.replace(/^./, (c) => (c === '0' ? '1' : '0'));
      try {
        await app.loadProject(saved);
        out.engine = { calls: since(), same: same(before, app.derived.inversions) };
      } finally {
        window.GWT.data.engineDigest = digest;
      }

      // a damaged entry and a hand-edited one, signed again to look sound:
      // both inverted afresh, and nothing thrown
      const damaged = JSON.parse(saved);
      const keys = Object.keys(damaged.state.inversionCache);
      damaged.state.inversionCache[keys[0]].result = 'junk';
      const edited = damaged.state.inversionCache[keys[1]];
      edited.result.resistivities[0] *= 1.5;
      edited.digest = C.sha256Hex(keys[1] + '\n' + C.canonicalText(edited.result));
      await app.loadProject(JSON.stringify(damaged));
      out.damaged = { calls: since(), same: same(before, app.derived.inversions) };
      const probe = app.derived.soundings[0], key = C.inversionCacheKey(probe, app.config());
      out.garbage = [null, 'x', 7, [], {}, { result: {}, digest: 'x' },
        { result: { resistivities: 'x' }, digest: C.sha256Hex(key + '\n' +
          C.canonicalText({ resistivities: 'x' })) }]
        .map((entry) => C.inversionFromCache(entry, key, probe, app.config()));

      // another project opened while a run is going: the outgoing run is
      // stopped there and then, so nothing it finishes is written into the
      // incoming project's cache or put on show over its soundings, and the
      // incoming project's own inversions are all it uses
      await app.loadProject(saved);
      app.store.set('config.ves.damping', 0.021);
      await app.recompute();
      await until(() => calls.length > 0 && app.working('invert'));
      since();
      await app.loadProject(saved);
      out.loadMidRun = { calls: since(), same: same(before, app.derived.inversions),
        keys: Object.keys(app.store.get('inversionCache')).sort().join() ===
          Object.keys(file.state.inversionCache).sort().join() };

      // a mirror that has no room for the cache is kept without it, rather
      // than not kept at all: the whole session written afresh, with the
      // cache's store refusing every entry
      await app.store.forget();
      const original = IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put = function (value, key) {
        if (this.name === 'cache') {
          const err = new Error('quota');
          err.name = 'QuotaExceededError';
          throw err;
        }
        return original.call(this, value, key);
      };
      let wrote;
      try {
        wrote = await app.store.persist();
      } finally {
        IDBObjectStore.prototype.put = original;
      }
      const mirrored = await app.storage.readBack();
      out.lighter = { wrote, ok: app.store.autosaveOk(),
        cache: Object.keys(mirrored.inversionCache || {}).length,
        sources: !!(mirrored.sources && mirrored.sources.ves),
        live: Object.keys(app.store.get('inversionCache')).length };
      // and offered again by the next write, which has room for it
      await app.store.persist();
      out.lighter.later = Object.keys((await app.storage.readBack()).inversionCache).length;

      // back to the survey as saved
      await app.loadProject(saved);
      since();
    } finally {
      engine.invert = realInvert;
    }
    return out;
  });
  check('cache: a saved survey carries an inversion per sounding',
    reused.entries === ves.n, JSON.stringify(reused.entries));
  check('cache: reopening a saved survey inverts nothing, and shows the same results',
    reused.reopen.calls === 0 && reused.reopen.same === null && reused.reopen.ranks &&
    !reused.reopen.working, JSON.stringify(reused.reopen));
  check('cache: loading a pumping sheet and typing a discharge keep the inversions',
    reused.addSheet.calls === 0 && reused.addSheet.n === ves.n &&
    reused.discharge.calls === 0 && reused.discharge.n === ves.n &&
    reused.discharge.q === 1.5 && reused.discharge.same === null,
    JSON.stringify([reused.addSheet, reused.discharge]));
  check('cache: a discharge typed while the survey inverts leaves the run going to the end',
    reused.whileRunning.typedWhileRunning && reused.whileRunning.calls === ves.n &&
    reused.whileRunning.cancelled === 0 && reused.whileRunning.n === ves.n &&
    reused.whileRunning.q === 2.2 && reused.whileRunning.page,
    JSON.stringify(reused.whileRunning));
  check('cache: a changed reading inverts that sounding and no other',
    reused.reading.calls.length === 1 && reused.reading.calls[0] === 'B (2)' &&
    reused.reading.n === ves.n && reused.reading.firstSame === null &&
    reused.reading.entries === ves.n, JSON.stringify(reused.reading));
  check('cache: a changed setting inverts every sounding',
    reused.config.calls === ves.n && reused.config.n === ves.n, JSON.stringify(reused.config));
  check('cache: another engine finds nothing in the file, and gets the same answer',
    reused.engine.calls === ves.n && reused.engine.same === null, JSON.stringify(reused.engine));
  check('cache: opening another project mid-run keeps the run out of it',
    reused.loadMidRun.calls === 0 && reused.loadMidRun.same === null &&
    reused.loadMidRun.keys, JSON.stringify(reused.loadMidRun));
  check('cache: an autosave too big with the cache in it is kept without it',
    reused.lighter.wrote === true && reused.lighter.ok === true &&
    reused.lighter.cache === 0 && reused.lighter.sources &&
    reused.lighter.live === ves.n && reused.lighter.later === ves.n,
    JSON.stringify(reused.lighter));
  check('cache: a damaged or hand-edited entry is not used',
    reused.damaged.calls === ves.n && reused.damaged.same === null &&
    reused.garbage.every((g) => g === null), JSON.stringify([reused.damaged, reused.garbage]));

  // The same app as a copy on disk. No worker is asked for, the page does its
  // own computing and says why, and the Rokel inversion is the worker's.
  const fromDisk = await (async () => {
    const tab = await page.context().newPage();
    const errors = [];
    tab.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    tab.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
    try {
      await tab.goto(FROM_DISK, { waitUntil: 'load' });
      await tab.waitForFunction(() => window.GWT && window.GWT.app, { timeout: 30000 });
      const found = await tab.evaluate(async () => {
        const app = window.GWT.app, engine = window.GWT.engine;
        await app.loadSample('rokel');
        const out = {
          mode: engine.mode(), why: engine.unavailable(),
          ran: engine.history().map((h) => h.type + ':' + h.mode + ':' + h.outcome),
          inversions: JSON.stringify(app.derived.inversions, (k, x) =>
            (typeof x === 'number' && !Number.isFinite(x) ? String(x) : x)),
        };
        /* Here the page stops drawing while a sounding inverts, so the work
         * bar has to be on screen in the frame before the first one starts,
         * or there is no Cancel to press. A press read then stops the run. */
        const kept = out.inversions;
        const run = app.runInversions();
        await new Promise((r) => requestAnimationFrame(r));
        const bar = document.querySelector('#work-status .work-bar[data-work="invert"]');
        if (bar) bar.querySelector('button').click();
        await run;
        out.cancel = { bar: !!bar,
          outcome: engine.history().filter((h) => h.type === 'invert').pop().outcome,
          kept: JSON.stringify(app.derived.inversions, (k, x) =>
            (typeof x === 'number' && !Number.isFinite(x) ? String(x) : x)) === kept };
        return out;
      });
      return Object.assign(found, { errors });
    } finally {
      await tab.close();
    }
  })();
  const inWorker = await page.evaluate(() => window.__serialise(window.GWT.app.derived.inversions));
  check('file://: no worker is asked for, and the page says why it computes itself',
    fromDisk.mode === 'page' && fromDisk.why === 'opened from file://' &&
    fromDisk.ran.length > 0 && fromDisk.ran.every((r) => r.endsWith(':page:done')),
    JSON.stringify(fromDisk.ran));
  check('file://: the Rokel inversion comes out exactly as it does in the worker',
    fromDisk.inversions === inWorker, `${fromDisk.inversions.length} against ${inWorker.length} chars`);
  check('file://: the work bar is up before the page stops drawing, and Cancel works',
    fromDisk.cancel.bar && fromDisk.cancel.outcome === 'cancelled' && fromDisk.cancel.kept,
    JSON.stringify(fromDisk.cancel));
  check('file://: no console errors', fromDisk.errors.length === 0,
    fromDisk.errors.slice(0, 5).join('\n     '));

  // A worker that is asked for and fails to load - a deploy missing the file,
  // a proxy that mangles it. The request it had is not lost: it and every
  // one after it runs on the page, with the same answer.
  const noWorker = await (async () => {
    const tab = await page.context().newPage();
    try {
      await tab.addInitScript(() => {
        const Real = window.Worker;
        window.Worker = function () { return new Real('js/not-in-this-deploy.js'); };
      });
      await tab.goto(base + '/index.html', { waitUntil: 'load' });
      await tab.waitForFunction(() => window.GWT && window.GWT.app);
      return await tab.evaluate(async () => {
        const app = window.GWT.app, engine = window.GWT.engine;
        /* The tab shares this origin's storage, so it restores this page's
         * session first. Fetching the sample workbooks gives that work time
         * to finish rather than be cancelled, so it is let finish, and only
         * what the sample asks for is counted. */
        await window.GWT.load('samples');
        await new Promise((resolve) => {
          const idle = setInterval(() => {
            if (app.recomputeState.running || app.working('invert') ||
                app.working('pumping')) return;
            clearInterval(idle);
            resolve();
          }, 50);
        });
        const before = engine.history().length;
        await app.loadSample('dr_timbo');
        return {
          why: engine.unavailable(),
          ran: engine.history().slice(before)
            .map((h) => h.type + ':' + h.mode + ':' + h.outcome),
          analysis: JSON.stringify(app.derived.analysis,
            (k, x) => (typeof x === 'number' && !Number.isFinite(x) ? String(x) : x)),
        };
      });
    } finally {
      await tab.close();
    }
  })();
  const timboHere = await page.evaluate(() => {
    const C = window.GWT.core, app = window.GWT.app, S = window.GWT.support;
    return S.readXlsx(S.base64ToBytes(window.GWT.data.samples.dr_timbo.files.pumping.b64))
      .then((sheets) => window.__serialise(C.analysePumpingTest(C.pumpingFromGrid(
        sheets[0].rows, window.GWT.data.samples.dr_timbo.files.pumping.name), app.config())));
  });
  const finished = noWorker.ran.filter((r) => !r.endsWith(':cancelled'));
  check('a worker that fails to load: its request and every later one run on the page',
    noWorker.why.startsWith('it did not start') &&
    finished.join() === 'recompute:page:done,analysePumping:page:done',
    JSON.stringify(noWorker.ran));
  check('a worker that fails to load: the answer is the same',
    noWorker.analysis === timboHere, `${(noWorker.analysis || '').length} against ${timboHere.length} chars`);

  // The GeoLibre project the site page saves, through the page's own button:
  // with a fix it carries the separation distances as rings round the
  // wellhead, and they do not take over the camera.
  const geolibre = await page.evaluate(() => {
    const app = window.GWT.app;
    let saved = '';
    const original = window.GWT.support.download;
    window.GWT.support.download = (name, body) => { saved = String(body); };
    try {
      app.goto('site');
      app.render();
      Array.from(document.querySelectorAll('button'))
        .find((b) => b.textContent === 'Save GeoLibre project').click();
    } finally {
      window.GWT.support.download = original;
    }
    const project = JSON.parse(saved || '{}');
    const byName = {};
    (project.layers || []).forEach((l) => { byName[l.name] = l; });
    const rings = byName['Separation distances'];
    const features = rings ? rings.geojson.features : [];
    /* the Rokel survey spans kilometres and would hide a ring taking over the
     * camera, so that is asked of the site on its own: framed on the point,
     * not on the 2 km across the widest ring */
    const site = byName.Site ? byName.Site.geojson.features[0].geometry.coordinates : null;
    const alone = site ? window.GWT.geolibre.siteProject(
      { community: 'Rokel', lon: site[0], lat: site[1], zone: 28 }) : null;
    return {
      layers: Object.keys(byName),
      hasSite: !!site,
      rings: features.length,
      widths: features.map((f) => f.properties.min_distance_m),
      explained: features.every((f) => /stay clear/.test(f.properties.meaning) &&
        /not a cited standard/.test(f.properties.basis)),
      aloneLayers: alone ? alone.layers.map((l) => l.name) : [],
      aloneZoom: alone ? alone.mapView.zoom : null,
      tableRows: window.GWT.core.loadSeparationDistances().length,
    };
  });
  check('geolibre: a site with a fix carries its separation rings',
    geolibre.hasSite && geolibre.rings === geolibre.tableRows && geolibre.rings > 0 &&
    geolibre.explained, JSON.stringify(geolibre));
  check('geolibre: the rings are widest first and do not frame the map',
    geolibre.widths[0] === Math.max.apply(null, geolibre.widths) &&
    geolibre.aloneLayers.indexOf('Separation distances') >= 0 &&
    geolibre.aloneZoom > 16,
    JSON.stringify({ widths: geolibre.widths, zoom: geolibre.aloneZoom }));

  // The visible text of a .docx, in reading order. A report that is a valid
  // ZIP with all the right OOXML parts can still be empty of the numbers it
  // was built to carry, so the checks below read what a client would read.
  await page.evaluate(() => {
    window.__docText = async function (bytes) {
      const files = await window.GWT.support.unzip(bytes);
      const parts = ['word/document.xml', 'word/footer1.xml']
        .filter((n) => files[n]);
      return parts.map((name) => {
        const xml = new DOMParser().parseFromString(
          new TextDecoder().decode(files[name]), 'application/xml');
        /* w:t carries the run text; w:tab and paragraph ends become spaces so
         * adjacent cells never run two words together */
        return Array.from(xml.getElementsByTagName('w:p')).map((p) =>
          Array.from(p.getElementsByTagName('w:t'))
            .map((t) => t.textContent).join('')).join('\n');
      }).join('\n');
    };
  });

  // build every report from the dr_timbo project
  await page.evaluate(() => window.GWT.app.goto('overview'));
  await page.evaluate(() => {
    Array.from(document.querySelectorAll('button'))
      .find((b) => b.textContent.includes('Load Dr Timbo')).click();
  });
  await page.waitForFunction(
    () => window.GWT.app.recomputeState.running === 0 &&
          window.GWT.app.derived.analysis !== null,
    { timeout: 60000 });

  // A pumping analysis stopped part way. The test stays loaded, the page says
  // the analysis was stopped rather than failing to draw, and Analyse now
  // brings back the same analysis and the same design.
  const pumpingStop = await page.evaluate(async () => {
    const app = window.GWT.app, d = app.derived;
    const before = { analysis: window.__serialise(d.analysis),
      design: window.__serialise(d.design) };
    app.goto('pumping');
    const analysing = app.reanalyseTest();
    app.cancelWork('pumping');
    await analysing;
    app.render();
    const text = document.querySelector('#page-host').textContent;
    const stopped = { analysis: d.analysis, note: d.analysisNote, test: !!d.test,
      says: text.includes('This test has not been analysed: the analysis was stopped'),
      discharges: text.includes('Discharge per step') };
    const again = Array.from(document.querySelectorAll('#page-host button'))
      .find((b) => b.textContent === 'Analyse now');
    if (again) again.click();
    for (let i = 0; i < 500 && !d.analysis; i += 1) {
      await new Promise((r) => setTimeout(r, 20));
    }
    await new Promise((r) => setTimeout(r, 200));
    return {
      stopped: Object.assign(stopped, { analysis: stopped.analysis === null }),
      button: !!again,
      same: window.__serialise(d.analysis) === before.analysis,
      design: window.__serialise(d.design) === before.design,
      figures: document.querySelectorAll('#page-host svg').length,
      last: window.GWT.engine.history().filter((h) => h.type === 'analysePumping')
        .slice(-2).map((h) => h.outcome),
    };
  });
  check('cancel: a stopped pumping analysis leaves the test loaded and says so',
    pumpingStop.stopped.analysis && pumpingStop.stopped.test &&
    pumpingStop.stopped.says && pumpingStop.stopped.discharges &&
    JSON.stringify(pumpingStop.last) === JSON.stringify(['cancelled', 'done']),
    JSON.stringify(pumpingStop));
  check('cancel: Analyse now brings back the same analysis and design',
    pumpingStop.button && pumpingStop.same && pumpingStop.design &&
    pumpingStop.figures >= 2, JSON.stringify(pumpingStop));

  for (const kind of ['completion', 'pumping', 'quality', 'costing', 'supervision', 'handover']) {
    const outcome = await page.evaluate(async (k) => {
      try {
        const before = window.__docx_bytes;
        // build without downloading: call the builder directly
        const cfg = window.GWT.app.config();
        const C = window.GWT.core, charts = window.GWT.charts, docx = window.GWT.docx;
        const d = window.GWT.app.derived;
        const context = { style: cfg.style, site: window.GWT.app.store.get('site') };
        let builder;
        if (k === 'completion') { context.log = d.log; context.design = d.design; context.figures = []; builder = await docx.completionReport(context); }
        else if (k === 'pumping') { context.analysis = d.analysis; context.figures = []; builder = await docx.pumpingReport(context); }
        else if (k === 'quality') { context.assessment = d.assessment; context.figures = []; builder = await docx.qualityReport(context); }
        else if (k === 'costing') { context.estimate = d.estimate; context.figures = []; builder = await docx.costingReport(context); }
        else if (k === 'supervision') {
          const items = C.loadChecklists();
          context.items = items; context.responses = {};
          context.evaluation = C.evaluateChecklist(items, {});
          builder = await docx.supervisionReport(context);
        } else {
          context.log = d.log; context.design = d.design; context.analysis = d.analysis;
          context.assessment = d.assessment; context.committee = []; context.figures = [];
          builder = await docx.handoverReport(context);
        }
        const bytes = await builder.build();
        window.__lastDocx = bytes;
        return { ok: true, size: bytes.length, images: builder.images.length };
      } catch (e) { return { ok: false, error: e.message + '\n' + e.stack }; }
    }, kind);
    check(`report: ${kind} builds`, outcome.ok && outcome.size > 4000,
      outcome.ok ? `${outcome.size} bytes` : outcome.error);

    if (outcome.ok) {
      // the archive must be a readable ZIP with the required OOXML parts
      const parts = await page.evaluate(async () => {
        const files = await window.GWT.support.unzip(window.__lastDocx);
        const doc = new TextDecoder().decode(files['word/document.xml'] || new Uint8Array());
        return { names: Object.keys(files), docLen: doc.length,
          wellFormed: !!new DOMParser().parseFromString(doc, 'application/xml')
            .querySelector('body') === false };
      });
      const required = ['[Content_Types].xml', '_rels/.rels', 'word/document.xml',
        'word/styles.xml', 'word/_rels/document.xml.rels', 'word/footer1.xml'];
      check(`report: ${kind} zip complete`,
        required.every((r) => parts.names.includes(r)) && parts.docLen > 1000,
        parts.names.join(', '));

      // and the headline figures actually reached the page. Structure alone
      // proves nothing: a report can be a perfect ZIP full of dashes.
      const content = await page.evaluate(async (k) => {
        const text = await window.__docText(window.__lastDocx);
        const d = window.GWT.app.derived, C = window.GWT.core;
        const site = window.GWT.app.store.get('site');
        const has = (s) => (s !== null && s !== undefined && s !== '')
          && text.includes(String(s));
        /* [description, expected value] - each is read back out of the same
         * derived result the page shows, so the report cannot drift from it */
        const wants = { completion: [], pumping: [], quality: [], costing: [],
          supervision: [], handover: [] };

        wants.completion = [
          ['community', has(site.community)],
          ['borehole reference', has(d.log.borehole_ref)],
          ['total depth', has(C.fmtNum(d.design.total_depth_m))],
          ['screen length', has(C.fmtNum(d.design.total_screen_length_m))],
        ];
        wants.pumping = [
          ['transmissivity', has(window.GWT.support.sig(
            d.analysis.transmissivity_m2_per_day, 3))],
          ['safe yield', has(C.fmtNum(
            d.analysis.yield_recommendation.safe_yield_m3_per_h))],
          // the report prints the test type in words ("constant discharge
          // test with recovery"), never the sheet's token
          ['test type', has(C.testTypeText(d.test.test_type))],
        ];
        wants.quality = [
          ['the verdict', has(d.assessment.verdict)],
          ['a determinand name', has(d.assessment.rows[0].parameter)],
          ['the sample identifier',
            has(d.sample.sample_id) || has(d.sample.borehole_ref)],
        ];
        wants.costing = [
          ['a bill line', has(d.estimate.items[0].item)],
          ['the total cost', has(window.GWT.support.money(
            d.estimate.total_cost_usd, 0).replace(/^\$/, ''))],
        ];
        wants.supervision = [
          ['a checklist item', has(C.loadChecklists()[0].text)],
          ['the section name', has(C.loadChecklists()[0].section)],
        ];
        wants.handover = [
          ['community', has(site.community)],
          ['total depth', has(C.fmtNum(d.design.total_depth_m))],
          ['the water quality verdict', has(d.assessment.verdict)],
        ];
        return { len: text.length, wants: wants[k] };
      }, kind);
      const missing = (content.wants || []).filter(([, ok]) => !ok)
        .map(([what]) => what);
      check(`report: ${kind} carries its headline figures`,
        content.wants.length > 0 && missing.length === 0,
        `missing: ${missing.join(', ')} (${content.len} chars of text)`);
    }
  }

  // a report with a real rasterised figure, to exercise the image path
  const withFigure = await page.evaluate(async () => {
    try {
      const charts = window.GWT.charts, docx = window.GWT.docx, d = window.GWT.app.derived;
      const png = await charts.toPng(charts.testOverview(d.test, d.analysis, { hover: false }));
      const b = new docx.ReportBuilder({ title: 'fig test' });
      b.heading('Figure', 1);
      b.figure(png, 'A rasterised chart');
      const bytes = await b.build();
      const files = await window.GWT.support.unzip(bytes);
      return { ok: true, media: Object.keys(files).filter((n) => n.startsWith('word/media/')),
        size: bytes.length, pngBytes: png.dataUrl.length };
    } catch (e) { return { ok: false, error: e.message }; }
  });
  check('report: embeds a rasterised figure',
    withFigure.ok && withFigure.media.length === 1,
    withFigure.ok ? withFigure.media.join(',') : withFigure.error);

  // project save/load round trip
  const roundTrip = await page.evaluate(async () => {
    const store = window.GWT.app.store;
    const before = JSON.stringify(store.state);
    const payload = { state: JSON.parse(before) };
    store.replace(window.GWT.app.blankState());
    store.replace(payload.state);
    await window.GWT.app.recompute();
    return {
      same: JSON.stringify(store.state) === before,
      analysis: !!window.GWT.app.derived.analysis,
    };
  });
  check('project round trip', roundTrip.same && roundTrip.analysis,
    JSON.stringify(roundTrip));

  // --- photo evidence (PLAN.md step 2.4) ---
  // A checklist item that needs a photograph holds the supervision record
  // back, in the catalogue's words, until one is attached through the page;
  // the photograph attached carries the record Python makes of the same
  // file; a device fix is recorded as one; and a project whose photographs
  // predate provenance opens and says they have none.
  const photoRef = JSON.parse(await readFile(
    new URL('reference.json', import.meta.url), 'utf8')).photo_evidence;
  const fixtureJpeg = await readFile(new URL('fixtures/photo_exif.jpg', import.meta.url));
  const savedState = await page.evaluate(() => {
    const store = window.GWT.app.store;
    const saved = JSON.stringify(store.state);
    store.set('supervision.evidence', {});
    store.set('supervision.responses', {});
    store.set('photoPosition', false);
    window.GWT.app.goto('supervision');
    return saved;
  });
  await page.waitForTimeout(150);
  const photoItems = ['des-casing-screen-assemblage', 'des-backfill-placed-6',
    'dev-borehole-disinfected-chlorine'];
  const gateText = () => page.evaluate((ids) => {
    const C = window.GWT.core;
    const items = C.loadChecklists().filter((i) => ids.indexOf(i.item_id) >= 0);
    const text = document.querySelector('#page-host').textContent;
    return {
      held: text.includes('Photo evidence — '),
      says: items.map((i) => text.includes(C.phrase('evidence.photo_missing',
        { stage: C.stageTitle(i.checklist), item: i.text }))),
      caveat: text.includes(C.phrase('evidence.presence_only')),
    };
  }, photoItems);
  const attach = async (key, file) => {
    const [chooser] = await Promise.all([page.waitForEvent('filechooser'),
      page.click(`.img-slot[data-key="${key}"] .img-slot-drop`)]);
    await chooser.setFiles(file);
    await page.waitForFunction((k) =>
      !!(window.GWT.app.store.get('supervision.evidence') || {})[k], key);
    await page.waitForTimeout(150);
  };
  const before = await gateText();
  check('photo evidence: each missing photograph holds the supervision record, in the catalogue\'s words',
    before.held && before.says.every(Boolean) && before.caveat, JSON.stringify(before));

  await attach('des-backfill-placed-6', { name: 'seal.jpg', mimeType: 'image/jpeg',
    buffer: fixtureJpeg });
  const attached = await page.evaluate(() =>
    window.GWT.app.store.get('supervision.evidence')['des-backfill-placed-6'].provenance);
  const expected = Object.assign({}, photoRef.cases.fixture.record);
  const sorted = (x) => JSON.stringify(Object.fromEntries(Object.keys(x).sort()
    .filter((k) => k !== 'attached_at').map((k) => [k, x[k]])));
  check('photo evidence: a photograph attached in the page carries the record Python makes of it',
    sorted(attached) === sorted(expected) && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(attached.attached_at),
    `js ${JSON.stringify(attached)}\n     py ${JSON.stringify(expected)}`);
  const one = await gateText();
  check('photo evidence: an attached photograph lifts only its own item',
    one.held && JSON.stringify(one.says) === '[true,false,true]', JSON.stringify(one));

  // a file with no EXIF, attached with the device's position allowed
  const app1 = fixtureJpeg.indexOf(Buffer.from([0xff, 0xe1]));
  const bare = Buffer.concat([fixtureJpeg.subarray(0, app1),
    fixtureJpeg.subarray(app1 + 2 + fixtureJpeg.readUInt16BE(app1 + 2))]);
  await page.context().grantPermissions(['geolocation']);
  await page.context().setGeolocation({ latitude: 8.4801, longitude: -13.2302, accuracy: 20 });
  await page.evaluate(() => window.GWT.app.store.set('photoPosition', true));
  await attach('des-casing-screen-assemblage', { name: 'screen.jpg',
    mimeType: 'image/jpeg', buffer: bare });
  const fixed = await page.evaluate(() =>
    window.GWT.app.store.get('supervision.evidence')['des-casing-screen-assemblage'].provenance);
  check('photo evidence: without EXIF, the device clock and an allowed fix, each said to be',
    fixed.time_source === 'device' && fixed.taken_at === fixed.attached_at &&
    fixed.position_source === 'device' && fixed.position.accuracy_m === 20 &&
    Math.abs(fixed.position.lat - 8.4801) < 1e-9 && fixed.bytes === bare.length,
    JSON.stringify(fixed));
  await page.evaluate(() => window.GWT.app.store.set('photoPosition', false));
  await attach('dev-borehole-disinfected-chlorine', { name: 'chlorine.jpg',
    mimeType: 'image/jpeg', buffer: bare });
  const unasked = await page.evaluate(() =>
    window.GWT.app.store.get('supervision.evidence')['dev-borehole-disinfected-chlorine'].provenance);
  const all = await gateText();
  check('photo evidence: with every photograph present the gate no longer holds the record',
    !all.held && unasked.position_source === 'none' &&
    unasked.position_note === 'not_requested', JSON.stringify({ all, unasked }));

  // asked, and refused; then asked of a device that never answers, which
  // once held the photograph for as long as the permission prompt stayed
  // open, because the geolocation timeout starts only after permission.
  // The device's answers are stood in for: Chromium went on serving the
  // emulated fix after the permission was cleared.
  const reattach = async (device) => {
    await page.evaluate((mode) => {
      window.GWT.app.store.remove('supervision.evidence.dev-borehole-disinfected-chlorine');
      window.GWT.app.store.set('photoPosition', true);
      navigator.geolocation.getCurrentPosition = mode === 'refuse'
        ? function (ok, fail) { fail({ code: 1, message: 'User denied Geolocation' }); }
        : function () {};
      window.GWT.imageSlot.positionWaitMs = 400;
      window.GWT.app.goto('supervision');
    }, device);
    await page.waitForTimeout(150);
    const started = Date.now();
    await attach('dev-borehole-disinfected-chlorine', { name: 'chlorine.jpg',
      mimeType: 'image/jpeg', buffer: bare });
    const provenance = await page.evaluate(() => window.GWT.app.store.get(
      'supervision.evidence')['dev-borehole-disinfected-chlorine'].provenance);
    return { ms: Date.now() - started, provenance };
  };
  const refused = await reattach('refuse');
  check('photo evidence: a refused position is recorded as refused',
    refused.provenance.position_source === 'none' &&
    refused.provenance.position_note === 'refused', JSON.stringify(refused));
  const silent = await reattach('silent');
  check('photo evidence: a device that never answers does not hold the photograph',
    silent.provenance.position_source === 'none' &&
    silent.provenance.position_note === 'unavailable' && silent.ms < 10000,
    JSON.stringify(silent));
  await page.evaluate(() => {
    delete navigator.geolocation.getCurrentPosition;
    window.GWT.imageSlot.positionWaitMs = 30000;
    window.GWT.app.store.set('photoPosition', false);
  });

  // a photograph large enough to be downscaled for storage keeps the hash
  // of the file as attached, not of the copy the project holds
  const largeJpeg = Buffer.from(await page.evaluate(async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 2400; canvas.height = 1600;
    const ctx = canvas.getContext('2d');
    for (let i = 0; i < 400; i++) {
      ctx.fillStyle = `hsl(${(i * 37) % 360}, 60%, ${30 + (i % 40)}%)`;
      ctx.fillRect((i * 97) % 2400, (i * 53) % 1600, 120, 90);
    }
    const blob = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', 0.9));
    return window.GWT.support.bytesToBase64(new Uint8Array(await blob.arrayBuffer()));
  }), 'base64');
  await page.evaluate(() => {
    window.GWT.app.store.remove('supervision.evidence.dev-borehole-disinfected-chlorine');
    window.GWT.app.goto('supervision');
  });
  await page.waitForTimeout(150);
  await attach('dev-borehole-disinfected-chlorine', { name: 'large.jpg',
    mimeType: 'image/jpeg', buffer: largeJpeg });
  const large = await page.evaluate(() => {
    const kept = window.GWT.app.store.get(
      'supervision.evidence')['dev-borehole-disinfected-chlorine'];
    const S = window.GWT.support;
    return { provenance: kept.provenance, width: kept.width,
      keptHash: window.GWT.core.photoProvenance(
        S.base64ToBytes(kept.dataUrl.split(',')[1]), { attached_at: 'x' }).sha256 };
  });
  const { createHash } = await import('node:crypto');
  const originalHash = createHash('sha256').update(largeJpeg).digest('hex');
  check('photo evidence: a downscaled photograph keeps the hash of the file as attached',
    large.provenance.stored === 'downscaled' && large.width <= 1600 &&
    large.provenance.sha256 === originalHash && large.keptHash !== originalHash &&
    large.provenance.bytes === largeJpeg.length,
    JSON.stringify({ large, originalHash }));

  // a project saved before provenance existed: a supervision photo slot
  // holding a photograph with no record, and no evidence field at all
  const old = await page.evaluate(async (b64) => {
    const app = window.GWT.app, C = window.GWT.core, docx = window.GWT.docx;
    const state = JSON.parse(JSON.stringify(app.blankState()));
    delete state.supervision.evidence;
    delete state.photoPosition;
    state.photos = { supervision: { materials: { dataUrl: 'data:image/jpeg;base64,' + b64,
      width: 24, height: 16, mime: 'image/jpeg', caption: 'Casing as delivered' } } };
    await app.loadProject(JSON.stringify({ format: 'groundwater-toolkit-project',
      version: 1, state: state }));
    app.goto('supervision');
    await new Promise((r) => setTimeout(r, 150));
    const text = document.querySelector('#page-host').textContent;
    const items = C.loadChecklists();
    const kept = { item: items.find((i) => i.item_id === 'des-backfill-placed-6'),
      photo: { provenance: null } };
    const builder = await docx.supervisionReport({ style: app.config().style,
      site: app.store.get('site'), items: items, responses: {},
      evaluation: C.evaluateChecklist(items, {}),
      evidence: window.GWT.imageSlot.collect(app.store.get('photos.supervision'), 'supervision')
        .map((photo) => ({ item: null, photo: photo })).concat([kept]),
      figures: [] });
    const doc = await window.__docText(await builder.build());
    return {
      shows: text.includes(C.phrase('evidence.no_provenance')),
      held: text.includes('Photo evidence — '),
      report: doc.includes(C.phrase('evidence.no_provenance')),
      invented: /SHA-256 [0-9a-f]{16}/.test(doc),
    };
  }, fixtureJpeg.toString('base64'));
  check('photo evidence: an older project opens and says its photographs have no recorded provenance',
    old.shows && old.held && old.report && !old.invented, JSON.stringify(old));
  await page.evaluate(async (saved) => {
    window.GWT.app.store.replace(JSON.parse(saved));
    await window.GWT.app.recompute();
  }, savedState);

  // templates actually generate valid workbooks
  const tmpl = await page.evaluate(async () => {
    const out = {};
    for (const key of ['ves', 'drilling', 'pumping', 'quality']) {
      const spec = window.GWT.app.templates[key];
      const bytes = await window.GWT.support.writeXlsx(spec.sheets());
      const sheets = await window.GWT.support.readXlsx(bytes);
      out[key] = { rows: sheets[0].rows.length, name: sheets[0].name };
    }
    return out;
  }).catch(() => null);
  if (tmpl) {
    check('templates round trip through the reader',
      Object.values(tmpl).every((t) => t.rows > 5), JSON.stringify(tmpl));
  }

  // --- Depth Spine: an edited screen has to move everything downstream ---
  const spine = await page.evaluate(async () => {
    const app = window.GWT.app;
    app.goto('spine');
    const before = {
      screens: app.derived.design.screens.map((s) => [s.top_m, s.bottom_m]),
      screenM: app.derived.design.total_screen_length_m,
      cost: app.derived.estimate.direct_cost_usd,
    };
    app.commitSpineScreens([{ top: 18, base: 30 }]);
    const after = {
      screens: app.derived.design.screens.map((s) => [s.top_m, s.bottom_m]),
      screenM: app.derived.design.total_screen_length_m,
      cost: app.derived.estimate.direct_cost_usd,
      stored: app.store.get('design.screens'),
    };
    app.commitSpineScreens(null);
    const reset = app.derived.design.screens.map((s) => [s.top_m, s.bottom_m]);
    return { before, after, reset };
  });
  check('spine: an edited screen re-derives the design',
    JSON.stringify(spine.after.screens) === JSON.stringify([[18, 30]]),
    JSON.stringify(spine.after.screens));
  check('spine: the bill of quantities follows the screen',
    spine.after.cost !== spine.before.cost,
    `${spine.before.cost} -> ${spine.after.cost}`);
  check('spine: reset returns the generated design',
    JSON.stringify(spine.reset) === JSON.stringify(spine.before.screens),
    JSON.stringify(spine.reset));

  const ledger = await page.evaluate(() => {
    const app = window.GWT.app;
    app.store.set('spine.signatory', 'M. Kolleh · hydrogeologist');
    app.spineDecide('design', {
      stage: 'design', status: 'accepted', value: '2.3 m³/h',
      recommended: '2.3 m³/h', signatory: 'M. Kolleh · hydrogeologist',
      at: '2024-01-01 09:00', clean: true,
    });
    const signed = JSON.parse(JSON.stringify(app.store.get('spine.ledger')));
    // moving a screen has to invalidate a signature that belonged to the old numbers
    app.commitSpineScreens([{ top: 20, base: 28 }]);
    const after = JSON.parse(JSON.stringify(app.store.get('spine.ledger')));
    app.commitSpineScreens(null);
    return { signed: !!signed.design, cleared: !after.design };
  });
  check('spine: a decision is recorded', ledger.signed);
  check('spine: moving a screen invalidates the signature', ledger.cleared);

  // --- Portfolio: project files from either application ---
  const portfolio = await page.evaluate(() => {
    const app = window.GWT.app, C = window.GWT.core;
    const own = JSON.stringify(app.projectPayload());
    /* The shape serialize_project really emits: five container keys it always
     * writes, any of which comes out as {} or [] when empty. The fixture that
     * stood here carried none of them, so it passed against a file no
     * Streamlit save has ever produced. parity.mjs now checks the real bytes;
     * this keeps the portfolio path honest too. */
    const streamlit = [
      'asset: {}',
      'committee: []',
      'format: groundwater-toolkit-project',
      'rates_overrides: {}',
      'schema: 1',
      'sources: {}',
      'groundwater_toolkit_project: 0.2.0',
      'summary:',
      '  community: Kuntoloh',
      '  district: Western Area Rural',
      '  status: Completed - dry',
      '  total_depth_m: 52.0',
      '  cost_per_meter_usd: 151.0',
      'state:',
      '  meta_community: Kuntoloh',
      '',
    ].join('\n');
    const summaries = [
      app.summaryFromProjectFile('dr_timbo.gwt.json', own),
      app.summaryFromProjectFile('kuntoloh_project.yaml', streamlit),
    ];
    let rejected = false;
    try { app.summaryFromProjectFile('junk.json', '{"nope": 1}'); }
    catch (e) { rejected = true; }
    return {
      communities: summaries.map((s) => s.community),
      stats: C.portfolioStats(summaries),
      rows: C.portfolioRows(summaries).length,
      brief: C.portfolioOnePager(summaries[1]).split('\n')[0],
      rejected,
    };
  });
  check('portfolio: reads this app\'s own project file',
    portfolio.communities[0] === "Dr. Timbo's Residence", portfolio.communities[0]);
  check('portfolio: reads a Streamlit .yaml project file',
    portfolio.communities[1] === 'Kuntoloh', portfolio.communities[1]);
  check('portfolio: aggregates the programme',
    portfolio.stats.n_projects === 2 && portfolio.rows === 2,
    JSON.stringify(portfolio.stats));
  check('portfolio: a brief is written for a site',
    portfolio.brief === 'SITE BRIEF - Kuntoloh (Western Area Rural)', portfolio.brief);
  check('portfolio: a file that is not a project is rejected', portfolio.rejected);

  // --- Water points: the live lookup, against a stubbed endpoint ---
  const waterPoints = await page.evaluate(async () => {
    const C = window.GWT.core;
    const url = C.wpdxUrl(8.4657, -13.2317, 1000);
    const real = window.fetch;
    let requested = null;
    window.fetch = async (u) => {
      if (requested === null) requested = String(u);   // the site lookup
      return new Response(JSON.stringify([
        { row_id: '1', lat_deg: '8.4660', lon_deg: '-13.2318',
          status_clean: 'Non-Functional', water_source_clean: 'Borehole',
          water_tech_clean: 'Hand Pump - India Mark II', install_year: '2011' },
        { row_id: '2', lat_deg: '8.4690', lon_deg: '-13.2350',
          status_clean: 'Functional', water_source_clean: 'Unprotected Spring',
          water_tech_clean: '' },
        // inside the query's bounding box, outside the 1000 m circle: the
        // corner case the distance filter exists for
        { row_id: '3', lat_deg: '8.4741', lon_deg: '-13.2398',
          status_clean: 'Functional', water_source_clean: 'Borehole',
          water_tech_clean: 'Hand Pump' },
      ]), { status: 200, headers: { 'content-type': 'application/json' } });
    };
    let points, raw, national, failure = null;
    try {
      raw = await C.fetchWaterPoints(8.4657, -13.2317, 1000);
      // the site lookup clips to the circle; the national pull must not, or
      // the coverage join loses everything outside a 300 km radius
      points = await C.waterPointsNear(8.4657, -13.2317, 1000);
      national = C.parseWpdxRecords(await C.fetchWaterPoints(8.46, -11.79, 300000)).length;
    } finally { window.fetch = real; }

    // and the failure path, which must stay a message rather than a crash
    window.fetch = async () => { throw new TypeError('offline'); };
    try { await C.waterPointsNear(8.4657, -13.2317, 1000); }
    catch (e) { failure = e.name + ': ' + e.message; }
    window.fetch = real;

    const decision = C.rehabVsDrill(points, 8.4657, -13.2317, { searchRadiusM: 1000 });
    return {
      url, requested, n: points.length, rawCount: raw.length, national,
      improved: C.parseWpdxRecords(raw).map((p) => p.improved),
      functional: C.parseWpdxRecords(raw).map((p) => p.functional),
      nearby: decision.nearby.length,
      recommendation: decision.recommendation,
      candidates: decision.rehab_candidates.length,
      failure,
    };
  });
  check('water points: the query is a WPdx bounding box',
    waterPoints.url.includes('data.waterpointdata.org/resource/eqje-vguj.json') &&
    waterPoints.url.includes('lat_deg%20between') &&
    waterPoints.url.includes('lon_deg%20between') &&
    waterPoints.url.includes('$order=%3Aid') &&
    waterPoints.requested === waterPoints.url, waterPoints.url);
  check('water points: the lookup parses the response', waterPoints.rawCount === 3,
    `${waterPoints.rawCount} rows`);
  check('water points: an unprotected spring is not an improved source',
    JSON.stringify(waterPoints.improved) === JSON.stringify([true, false, true]),
    JSON.stringify(waterPoints.improved));
  check('water points: status maps to functionality',
    JSON.stringify(waterPoints.functional) === JSON.stringify([false, true, true]),
    JSON.stringify(waterPoints.functional));
  check('water points: the corner of the bounding box is not in the circle',
    waterPoints.n === 2 && waterPoints.rawCount === 3,
    `${waterPoints.n} kept of ${waterPoints.rawCount} returned`);
  check('water points: only the ones in range are judged',
    waterPoints.nearby === 2, `${waterPoints.nearby} within 1000 m`);
  check('water points: the national pull is not distance-filtered',
    waterPoints.national === 3, `${waterPoints.national} of 3 kept`);
  check('water points: a broken borehole nearby is a rehabilitation candidate',
    waterPoints.recommendation === 'assess_rehab' && waterPoints.candidates === 1,
    `${waterPoints.recommendation}, ${waterPoints.candidates} candidates`);
  check('water points: being offline is a message, not a crash',
    /^WaterPointFetchError: /.test(waterPoints.failure || ''), waterPoints.failure);

  // --- coverage as a planning figure ---------------------------------------
  // The census is a decade old and the survey behind each point is older than
  // it looks. The page has to show both rather than one figure that reads as
  // current, and the year and rate have to be the analyst's to set.
  const planning = await page.evaluate(() => {
    const C = window.GWT.core, app = window.GWT.app;
    const wp = (functional, year, months) => C.parseWpdxRecords([{
      lat_deg: 8, lon_deg: -13,
      status_clean: functional ? 'Functional' : 'Non-Functional',
      status_id: functional ? 'Yes' : 'No',
      water_source_clean: 'Borehole', water_tech_clean: 'Hand Pump',
      report_date: year === null ? '' : String(year),
      months_year: months === null ? '' : String(months),
    }])[0];
    const population = { Bo: 1000, Kono: 1000 };
    const points = {
      Bo: [wp(true, 2025, 12), wp(true, 2005, null)],
      Kono: [wp(true, 2004, null), wp(true, 2003, null)],
    };
    const atCensus = C.planningRows(population, points, { asOfYear: 2015 });
    const projected = C.planningRows(population, points, { asOfYear: 2026 });
    const stats = C.planningStats(projected.rows, projected.projection);

    app.store.set('coverage.year', 2030);
    app.store.set('coverage.rate', 1.5);
    const slow = C.planningRows(population, points,
      { asOfYear: 2030, rate: 0.015 });
    app.store.set('coverage.year', null);
    app.store.set('coverage.rate', null);
    return {
      censusPeople: atCensus.rows[0].population,
      projectedPeople: projected.rows[0].population,
      order: projected.rows.map((r) => r.name),
      note: projected.projection.note,
      stats,
      slowPeople: slow.rows[0].population,
      freshness: projected.rows.map((r) => [r.name, r.freshness.state]),
      seasonal: projected.rows[0].seasonal,
    };
  });
  check('planning: the population is projected and says so',
    planning.projectedPeople > planning.censusPeople &&
    planning.note.includes('2015 census') && planning.note.includes('2026'),
    planning.note);
  check('planning: a uniform rate does not reorder the ranking, and says so',
    planning.note.includes('ranking is unchanged'), planning.note);
  check('planning: the rate is the analyst\'s to set',
    planning.slowPeople < planning.projectedPeople,
    `${planning.slowPeople} vs ${planning.projectedPeople}`);
  check('planning: an area surveyed twenty years ago is flagged stale',
    JSON.stringify(planning.freshness) ===
      JSON.stringify([['Kono', 'stale'], ['Bo', 'stale']]) ||
    planning.stats.n_stale_areas >= 1,
    JSON.stringify(planning.freshness));
  check('planning: counting only recent surveys makes coverage look worse',
    planning.stats.national_people_per_recent_point >
      planning.stats.national_people_per_point,
    JSON.stringify([planning.stats.national_people_per_point,
      planning.stats.national_people_per_recent_point]));
  check('planning: unrecorded seasonality is a band, not a year-round supply',
    planning.seasonal.people_per_point_low !== planning.seasonal.people_per_point_high &&
    planning.seasonal.n_unknown > 0,
    JSON.stringify(planning.seasonal));

  // --- Pasted GPS coordinates ---
  // Every longitude in Sierra Leone is west, and a handheld GPS writes that
  // as a letter rather than a minus sign. Reading "13.2317 W" as +13.2317
  // puts the site on the far side of the continent, silently.
  const coords = await page.evaluate(() => {
    const parse = window.GWT.app.parseLatLon;
    return [
      '8.4657, -13.2317', '8.4657 N, 13.2317 W', '8.4657N 13.2317W',
      'N 8.4657, W 13.2317', '13.2317 W, 8.4657 N', '8.4657;-13.2317',
      '8.4657 S, 13.2317 W', '-13.2317 E, 8.4657', '8.4657', '200, 5', 'rubbish', '',
    ].map((text) => [text, parse(text)]);
  });
  const expectedCoords = [
    ['8.4657, -13.2317', { lat: 8.4657, lon: -13.2317 }],
    ['8.4657 N, 13.2317 W', { lat: 8.4657, lon: -13.2317 }],
    ['8.4657N 13.2317W', { lat: 8.4657, lon: -13.2317 }],
    ['N 8.4657, W 13.2317', { lat: 8.4657, lon: -13.2317 }],
    ['13.2317 W, 8.4657 N', { lat: 8.4657, lon: -13.2317 }],
    ['8.4657;-13.2317', { lat: 8.4657, lon: -13.2317 }],
    ['8.4657 S, 13.2317 W', { lat: -8.4657, lon: -13.2317 }],
    ['-13.2317 E, 8.4657', null], ['8.4657', null], ['200, 5', null],
    ['rubbish', null], ['', null],
  ];
  check('coordinates: hemisphere letters are read as signs',
    JSON.stringify(coords) === JSON.stringify(expectedCoords),
    JSON.stringify(coords));

  // --- Scanned sheets: a text PDF, read in the page ---
  // The fixture is written here rather than committed as a binary: a typed
  // field sheet is Helvetica text placed with Tm/Tj in one FlateDecode
  // content stream, and building it in the test says so out loud.
  await page.evaluate(async () => {
    const rows = [[1, 1.5, 0.5, 210.4], [2, 2, 0.5, 233.1], [3, 3, 0.5, 268.0],
      [4, 4, 0.5, 291.7], [5, 6, 0.5, 302.5], [6, 8, 0.5, 288.2],
      [7, 10, 0.5, 264.9], [8, 15, 0.5, 198.3]];
    const placed = [
      [60, 760, 'SCHLUMBERGER ARRAY VES FIELD DATA'],
      [60, 735, 'Community: Rokel'], [300, 735, 'Client: Living Water International'],
      [60, 715, 'District: Port Loko'], [300, 715, 'Sounding Number: VES A-1'],
      [60, 695, 'Date: 2023-05-14'], [300, 695, 'Field Supervisor: M. Kolleh'],
      [60, 650, 'No.'], [110, 650, 'AB/2 (m)'], [200, 650, 'MN (m)'],
      [280, 650, 'Apparent Resistivity (ohm-m)'],
    ];
    rows.forEach((row, i) => {
      const y = 630 - i * 18;
      [[60, row[0]], [110, row[1]], [200, row[2]], [280, row[3]]]
        .forEach(([x, value]) => placed.push([x, y, String(value)]));
    });
    let content = 'BT /F1 10 Tf\n';
    placed.forEach(([x, y, text]) => {
      const escaped = text.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)');
      content += `1 0 0 1 ${x} ${y} Tm (${escaped}) Tj\n`;
    });
    content += 'ET\n';

    const raw = new Uint8Array(content.length);
    for (let i = 0; i < content.length; i++) raw[i] = content.charCodeAt(i);
    const compressed = new Uint8Array(await new Response(
      new Blob([raw]).stream().pipeThrough(new CompressionStream('deflate'))
    ).arrayBuffer());

    const parts = [];
    function push(text) {
      for (let i = 0; i < text.length; i++) parts.push(text.charCodeAt(i));
    }
    push('%PDF-1.4\n');
    const bodies = [
      '<< /Type /Catalog /Pages 2 0 R >>',
      '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
      '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] ' +
        '/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
      null,
      '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
      String(compressed.length),   // object 6: the indirect /Length
    ];
    const offsets = [];
    bodies.forEach((body, i) => {
      offsets.push(parts.length);
      push(`${i + 1} 0 obj\n`);
      if (body === null) {
        // /Length as an indirect reference — the shape that made a greedy
        // \d+ backtrack to "1" and truncate the stream to a single byte
        push('<< /Length 6 0 R /Filter /FlateDecode >>\nstream\n');
        compressed.forEach((b) => parts.push(b));
        push('\nendstream');
      } else {
        push(body);
      }
      push('\nendobj\n');
    });
    const xrefAt = parts.length;
    push(`xref\n0 ${bodies.length + 1}\n0000000000 65535 f \n`);
    offsets.forEach((offset) => push(String(offset).padStart(10, '0') + ' 00000 n \n'));
    push(`trailer\n<< /Size ${bodies.length + 1} /Root 1 0 R >>\n` +
      `startxref\n${xrefAt}\n%%EOF\n`);
    window.__pdfFixture = window.GWT.support.bytesToBase64(new Uint8Array(parts));
  });

  const scan = await page.evaluate(async () => {
    const C = window.GWT.core, S = window.GWT.support;
    const bytes = S.base64ToBytes(window.__pdfFixture);
    const doc = await C.extractPdfText(bytes, 'ves_sheet.pdf');
    const workbook = await S.writeXlsx(C.reviewWorkbookSheets(doc));
    const sheets = await S.readXlsx(workbook);
    const filled = await S.writeXlsx([{
      name: 'VES 1',
      rows: C.fillVesTemplateSheets(doc, window.GWT.app.templates.ves.sheets()[0].rows),
    }]);
    const vesSheets = await S.readXlsx(filled);
    const sounding = C.readVesSheets(vesSheets, 'filled.xlsx')[0];
    return {
      kind: doc.document_kind,
      header: doc.header.map((f) => [f.name, f.value]),
      columns: doc.tables[0] ? doc.tables[0].columns : [],
      rows: doc.tables[0] ? doc.tables[0].rows.length : 0,
      sheetNames: sheets.map((s) => s.name),
      soundingId: sounding.sounding_id,
      community: sounding.site.community,
      ab2: sounding.ab2, rho: sounding.rho_app,
    };
  });
  check('scan: the sheet type is recognised', scan.kind === 'ves', scan.kind);
  check('scan: header fields are read',
    JSON.stringify(scan.header) === JSON.stringify([
      ['community', 'Rokel'], ['client', 'Living Water International'],
      ['district', 'Port Loko'], ['sounding_id', 'VES A-1'],
      ['date', '2023-05-14'], ['supervisor', 'M. Kolleh']]),
    JSON.stringify(scan.header));
  check('scan: the reading table is found',
    JSON.stringify(scan.columns) ===
      JSON.stringify(['No.', 'AB/2 (m)', 'MN (m)', 'Apparent Resistivity (ohm-m)']) &&
    scan.rows === 8, `${scan.rows} rows, ${JSON.stringify(scan.columns)}`);
  check('scan: the review workbook has a sheet per table plus a Review sheet',
    JSON.stringify(scan.sheetNames) === JSON.stringify(['Header', 'Table 1', 'Review']),
    JSON.stringify(scan.sheetNames));
  check('scan: the filled VES template reads back through the normal reader',
    scan.soundingId === 'VES A-1' && scan.community === 'Rokel' &&
    scan.ab2.length === 8 && Math.abs(scan.rho[0] - 210.4) < 1e-9,
    `${scan.soundingId} / ${scan.community} / ${scan.ab2.length} readings`);

  // --- A pumping test written on a Word field sheet ---
  // Built here from the sample workbook so the two readers are compared on
  // the same readings: a .docx that carries the workbook's own numbers must
  // come back as the same PumpingTest.
  const docxTest = await page.evaluate(async () => {
    const S = window.GWT.support, C = window.GWT.core;
    const grids = await S.readXlsx(S.base64ToBytes(GWT.data.samples.kuntolo.files.pumping.b64));
    const rows = grids[0].rows;
    const fromXlsx = C.pumpingFromGrid(rows, 'kuntolo_step_test.xlsx');

    const esc = (text) => String(text === null || text === undefined ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    // the header block becomes paragraphs (tab separated), the readings a table
    const split = rows.findIndex((r) => (r || []).some(
      (c) => /time\s*\(min\)/i.test(String(c || ''))));
    const paragraphs = rows.slice(0, split).map((row) =>
      `<w:p><w:r><w:t xml:space="preserve">${
        esc((row || []).filter((c) => c !== null && c !== undefined && c !== '')
          .join('\t'))}</w:t></w:r></w:p>`).join('');
    const width = Math.max(...rows.slice(split).map((r) => (r || []).length));
    const table = '<w:tbl>' + rows.slice(split).map((row) => '<w:tr>' +
      Array.from({ length: width }, (_, i) =>
        `<w:tc><w:p><w:r><w:t xml:space="preserve">${esc((row || [])[i])}` +
        '</w:t></w:r></w:p></w:tc>').join('') + '</w:tr>').join('') + '</w:tbl>';
    const document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
      `<w:body>${paragraphs}${table}</w:body></w:document>`;
    const bytes = await S.zip([
      { name: '[Content_Types].xml', store: true, data:
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
        '</Types>' },
      { name: '_rels/.rels', data:
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
        '</Relationships>' },
      { name: 'word/document.xml', data: document },
    ]);
    const fromDocx = await C.readPumpingDocx(bytes, 'kuntolo_step_test.docx');
    return {
      type: [fromXlsx.test_type, fromDocx.test_type],
      swl: [fromXlsx.static_water_level_m, fromDocx.static_water_level_m],
      steps: [fromXlsx.steps.length, fromDocx.steps.length],
      points: [fromXlsx.steps.map((s) => s.time_min.length),
        fromDocx.steps.map((s) => s.time_min.length)],
      levels: [fromXlsx.steps[0].water_level_m, fromDocx.steps[0].water_level_m],
      community: [fromXlsx.site.community, fromDocx.site.community],
    };
  });
  check('docx: a Word field sheet reads as the same test',
    docxTest.type[0] === docxTest.type[1] &&
    docxTest.swl[0] === docxTest.swl[1] &&
    docxTest.steps[0] === docxTest.steps[1] &&
    docxTest.community[0] === docxTest.community[1],
    JSON.stringify(docxTest));
  check('docx: every reading survives the round trip',
    JSON.stringify(docxTest.points[0]) === JSON.stringify(docxTest.points[1]) &&
    JSON.stringify(docxTest.levels[0]) === JSON.stringify(docxTest.levels[1]),
    JSON.stringify(docxTest.points));

  // --- provisional national standards -------------------------------------
  // The national column is carried WHO/regional figures, not a confirmed
  // Sierra Leone Standards Bureau specification. A national exceedance that
  // did not say so would read as a compliance finding.
  const provisional = await page.evaluate(() => {
    const params = window.GWT.core.provisionalNationalParameters();
    const table = window.GWT.core.loadStandards();
    return {
      count: params.length,
      arsenic: table.arsenic && table.arsenic.sl_provisional,
      hasNote: (window.GWT.core.PROVISIONAL_NATIONAL_NOTE || '').length > 100,
      /* an entry with no national value at all is not "provisional" */
      noNationalIsNotProvisional: Object.keys(table)
        .filter((k) => !table[k].sl_standard)
        .every((k) => table[k].sl_provisional === false),
    };
  });
  check('standards: the national column is flagged provisional',
    provisional.count > 0 && provisional.arsenic === true && provisional.hasNote,
    JSON.stringify(provisional));
  check('standards: a missing national value is not called provisional',
    provisional.noNationalIsNotProvisional === true);

  await page.evaluate(() => window.GWT.app.goto('quality'));
  await page.waitForTimeout(120);
  const qualityNote = await page.evaluate(() => {
    const text = document.querySelector('#page-host').textContent;
    return {
      onPage: text.includes('National limits are provisional'),
      lists: /Unconfirmed: .*Arsenic/.test(text),
    };
  });
  check('standards: the quality page says the national limits are unconfirmed',
    qualityNote.onPage && qualityNote.lists, JSON.stringify(qualityNote));

  const qualityDoc = await page.evaluate(async () => {
    const docx = window.GWT.docx, d = window.GWT.app.derived;
    const builder = await docx.qualityReport({
      site: window.GWT.app.store.get('site'),
      assessment: d.assessment, figures: [],
    });
    const text = await window.__docText(await builder.build());
    return {
      len: text.length,
      saysProvisional: text.includes('The national column in the standards ' +
        'table is provisional'),
    };
  });
  check('standards: the quality report says the national column is provisional',
    qualityDoc.len > 1000 && qualityDoc.saysProvisional, JSON.stringify(qualityDoc));

  // --- procurement ----------------------------------------------------------
  // A bill of quantities is an estimate until somebody signs it. The three
  // ways money leaks afterwards all have to survive the wiring: work measured
  // that nobody authorised, work paid for twice, and retention forgotten.
  const procurement = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core, d = app.derived;
    app.store.set('procurement', { contract: null, measured: {},
      variations: [], number: 1, date: '', previous: 0 });
    app.store.set('procurement.ref', 'WSD/2024/017');
    app.goto('procurement');
    app.render();
    const before = document.querySelector('#page-host').textContent;

    const press = (label) => {
      const btn = Array.from(document.querySelectorAll('#page-host button'))
        .find((b) => b.textContent === label);
      if (btn) btn.click();
      return !!btn;
    };
    const awarded = press('Award this estimate as the contract');
    const contract = (app.store.get('procurement') || {}).contract;

    // measure a drilling line well past what was priced
    const drilling = contract.lines.find((l) => /drill/i.test(l.item)) ||
      contract.lines[0];
    const measured = {};
    measured[drilling.code] = drilling.quantity * 2;
    app.store.set('procurement', Object.assign(app.store.get('procurement'),
      { measured }));
    app.render();
    const over = C.certify(contract,
      [{ code: drilling.code, quantity: drilling.quantity * 2 }],
      { number: 1, date: '2024-04-01' });

    // then authorise it, and the same work becomes payable
    const authorised = C.certify(contract,
      [{ code: drilling.code, quantity: drilling.quantity * 2 }],
      { number: 1, date: '2024-04-01', variations: [{
        ref: 'VO-1', date: '2024-03-04', code: drilling.code,
        quantity_delta: drilling.quantity, rate_usd: null,
        reason: 'water deeper than priced', authorised_by: 'M. Kolleh' }] });

    // a second certificate that forgets what the first one paid
    const forgetful = C.certify(contract,
      [{ code: drilling.code, quantity: drilling.quantity }],
      { number: 2, date: '2024-05-01' });

    const page_text = document.querySelector('#page-host').textContent;
    const doc = await window.__docText(await (await window.GWT.docx
      .paymentCertificate({ style: app.config().style, contract,
        certificate: over })).build());

    app.store.set('procurement', { contract: null, measured: {},
      variations: [], number: 1, date: '', previous: 0 });
    app.render();
    return { before, awarded, lines: contract.lines.length,
      code: drilling.code, over, authorised, forgetful, page_text, doc };
  });
  check('procurement: an estimate is not a contract until it is awarded',
    procurement.before.includes('not a contract until it is awarded') &&
    procurement.awarded === true && procurement.lines > 0,
    `${procurement.lines} lines`);
  check('procurement: work nobody authorised is withheld, not paid',
    procurement.over.overmeasure_usd > 0 &&
    procurement.over.gross_usd < procurement.over.revised_sum_usd &&
    procurement.over.problems.some((p) => p.includes('not payable until a variation')),
    JSON.stringify(procurement.over.problems));
  check('procurement: the page says so where the analyst is looking',
    procurement.page_text.includes('measured but not authorised'),
    procurement.page_text.slice(0, 160));
  check('procurement: a variation makes the same work payable',
    procurement.authorised.overmeasure_usd === 0 &&
    procurement.authorised.gross_usd > procurement.over.gross_usd,
    JSON.stringify([procurement.over.gross_usd,
      procurement.authorised.gross_usd]));
  check('procurement: a later certificate with nothing certified is challenged',
    procurement.forgetful.problems.some((p) =>
      p.includes('paid for that work twice')),
    JSON.stringify(procurement.forgetful.problems));
  check('procurement: retention is withheld from the payment',
    procurement.over.retention_usd > 0 &&
    procurement.over.due_now_usd < procurement.over.gross_usd,
    JSON.stringify([procurement.over.gross_usd, procurement.over.retention_usd,
      procurement.over.due_now_usd]));
  check('procurement: the certificate shows the problems before the money',
    procurement.doc.includes('Before the figures') &&
    // before the valuation, not before the cover's headline figure
    procurement.doc.indexOf('Before the figures') <
      procurement.doc.indexOf('Summary') &&
    procurement.doc.includes('Measured beyond what was authorised') &&
    procurement.doc.includes('not payable until a variation'),
    procurement.doc.length + ' chars');

  // --- the yield through the year ------------------------------------------
  // The sample sheet's date is 10/05/2018, which is 10 May or 5 October -
  // opposite ends of the year. The page has to say so rather than pick one,
  // and the month the analyst picks has to reach the report.
  const seasonal = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core, d = app.derived;
    app.store.set('seasonal', {});
    app.goto('pumping');
    app.render();
    const asRead = {
      text: document.querySelector('#page-host').textContent,
      month: C.monthOf(d.analysis.test.site.date).month,
    };

    const pick = (month) => {
      const select = Array.from(document.querySelectorAll('#page-host select'))
        .find((s2) => Array.from(s2.options).some((o) => o.label === 'September'));
      if (!select) return false;
      select.value = String(month);
      select.dispatchEvent(new Event('change'));
      return true;
    };
    const picked = pick(9);
    const september = {
      text: document.querySelector('#page-host').textContent,
      result: C.seasonalYield(d.analysis, app.config().pumping, { month: 9 }),
    };
    pick(5);
    const may = C.seasonalYield(d.analysis, app.config().pumping, { month: 5 });

    pick(9);
    const doc = await window.__docText(await (await window.GWT.docx.pumpingReport({
      style: app.config().style, site: app.store.get('site'),
      analysis: d.analysis, figures: [],
      seasonal: C.seasonalYield(d.analysis, app.config().pumping, { month: 9 }),
    })).build());

    app.store.set('seasonal', {});
    app.render();
    return { asRead, picked, september, may, doc };
  });
  check('seasonal: an ambiguous sheet date is explained, not resolved',
    seasonal.asRead.month === null &&
    seasonal.asRead.text.includes('could be read either way round'),
    `month ${seasonal.asRead.month}`);
  check('seasonal: picking the month changes what the test proves',
    seasonal.picked === true &&
    seasonal.may.design_yield_m3_per_h > seasonal.september.result.design_yield_m3_per_h,
    JSON.stringify({ may: seasonal.may.design_yield_m3_per_h,
      september: seasonal.september.result.design_yield_m3_per_h }));
  check('seasonal: the page names the three scenarios',
    ['As tested', 'End of dry season', 'Drought year']
      .every((title) => seasonal.september.text.includes(title)),
    seasonal.september.text.slice(0, 200));
  check('seasonal: the pump is set for the drought case',
    seasonal.september.result.pump_installation_depth_m ===
      Math.max(...seasonal.september.result.scenarios
        .map((s) => s.pump_installation_depth_m)),
    JSON.stringify(seasonal.september.result.scenarios.map((s) =>
      [s.key, s.pump_installation_depth_m])));
  check('seasonal: the report carries the projection',
    seasonal.doc.includes('Through the year') &&
    seasonal.doc.includes('September') &&
    seasonal.doc.includes('the pump is fitted once'),
    seasonal.doc.length + ' chars');

  // --- the asset registry --------------------------------------------------
  // The identifier is derived from the position, the history is append-only
  // and merges by content, and nothing counts as working until something
  // says so. All three have to survive the wiring, not just the engine.
  const registry = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core, d = app.derived;
    const site = app.store.get('site');
    const saved = [site.easting, site.northing, site.utm_zone];
    app.store.set('asset', null);
    d.registry = [];
    app.goto('registry');
    app.render();
    const unlocated = document.querySelector('#page-host').textContent;

    site.easting = 694912; site.northing = 938150; site.utm_zone = 28;
    app.render();
    const located = {
      text: document.querySelector('#page-host').textContent,
      id: document.querySelector('#page-host .asset-id')?.textContent || '',
      minted: C.mintAssetId(site),
      hasSymbol: !!document.querySelector('#page-host .qr-preview svg'),
    };

    // record a visit through the form the way a field team would
    const fill = (placeholder, value) => {
      const input = document.querySelector(
        '#page-host input[placeholder="' + placeholder + '"]');
      if (!input) return false;
      input.value = value;
      input.dispatchEvent(new Event('change'));
      return true;
    };
    const press = (label) => {
      const btn = Array.from(document.querySelectorAll('#page-host button'))
        .find((b) => b.textContent === label);
      if (btn) btn.click();
      return !!btn;
    };
    fill('YYYY-MM-DD', 'not a date');
    const refusedBadDate = press('Add to the history') &&
      ((app.store.get('asset') || {}).events || []).length === 0;

    // re-queried each time: the page re-renders after every submit, so a
    // node captured before it is detached and setting it changes nothing
    const recordFailure = () => {
      fill('YYYY-MM-DD', '2023-04-02');
      fill('Name', 'A. Bangura');
      fill('What was found or done', 'rising main parted');
      const kind = Array.from(document.querySelectorAll('#page-host select'))
        .find((s2) => Array.from(s2.options).some((o) => o.value === 'failure'));
      if (kind) { kind.value = 'failure'; kind.dispatchEvent(new Event('change')); }
      return press('Add to the history');
    };
    recordFailure();
    const recorded = app.store.get('asset') || {};
    const afterOne = C.assetState(C.assetFromDict(recorded), '2024-06-01');

    // the same visit again: content-derived ids mean it merges, not doubles
    recordFailure();
    const afterTwice = (app.store.get('asset') || {}).events.length;

    // a wrong identifier is refused with something a person can act on
    app.store.set('registry.lookup', C.mintAssetId(site).slice(0, -1) + 'Z');
    app.render();
    // by content, not by tone: the status callout on a broken borehole is
    // also a .callout-bad and sits above this one
    const lookup = Array.from(document.querySelectorAll('#page-host .callout p'))
      .map((n) => n.textContent).find((t) => t.includes('check character')) || '';

    const doc = await window.__docText(await (await window.GWT.docx.assetRecordReport({
      asset: C.assetFromDict(app.store.get('asset')),
      today: '2024-06-01',
    })).build());

    app.store.set('registry.lookup', '');
    app.store.set('asset', null);
    site.easting = saved[0]; site.northing = saved[1]; site.utm_zone = saved[2];
    app.render();
    return { unlocated, located, refusedBadDate, afterOne, afterTwice, lookup, doc };
  });
  check('registry: a borehole with no position gets no identifier',
    registry.unlocated.includes('nothing to find the borehole by'));
  check('registry: the identifier is derived from the position',
    registry.located.id === registry.located.minted &&
    registry.located.id.startsWith('SL-WAR-'),
    JSON.stringify({ shown: registry.located.id, minted: registry.located.minted }));
  check('registry: the page draws the symbol that goes on the headworks',
    registry.located.hasSymbol === true);
  check('registry: a date nobody can read is refused, not stored',
    registry.refusedBadDate === true);
  check('registry: a recorded failure leaves the borehole not working',
    registry.afterOne.function === 'non_functional' &&
    registry.afterOne.days_out_of_service === 426,
    JSON.stringify(registry.afterOne));
  check('registry: the same visit recorded twice merges into one',
    registry.afterTwice === 1, `${registry.afterTwice} events`);
  check('registry: a mistyped identifier says what it should have ended in',
    registry.lookup.includes('check character') &&
    registry.lookup.includes('mistyped'), registry.lookup);
  check('registry: the record names the days the community went without',
    registry.doc.includes('Not working') && registry.doc.includes('426 days') &&
    registry.doc.includes('rising main parted'));

  // --- the certification gate ---------------------------------------------
  // The gate never blocks a build: an interim report is a real need, and an
  // analyst who is refused one will produce the document some other way. So
  // the only thing between missing evidence and a page that reads as certified
  // is the panel and the stamp, and both of them live in the wiring rather
  // than in the engine the parity suite already pins.
  const gate = await page.evaluate(async () => {
    const app = window.GWT.app, docx = window.GWT.docx, d = app.derived;
    const buildQuality = async () => window.__docText(await (await docx.qualityReport({
      site: app.store.get('site'), assessment: d.assessment, figures: [],
      readiness: app.reportReadiness('quality'),
    })).build());
    const panelText = () => document.querySelector('#page-host').textContent;

    app.store.set('overrides', {});
    app.goto('quality');

    // The bundled sheets carry no coordinates - the crew never wrote one down -
    // so the demo project really is short of this, and an analyst supplies it
    // on the site page before the report goes out.
    const sites = [app.store.get('site'), d.log && d.log.site,
      d.analysis && d.analysis.test && d.analysis.test.site,
      d.assessment && d.assessment.sample && d.assessment.sample.site]
      .filter(Boolean);
    const saved = sites.map((s) => [s.easting, s.northing, s.utm_zone]);
    const site = app.store.get('site');
    site.easting = 778000; site.northing = 946000; site.utm_zone = 28;
    /* ...and the data is the analyst's own by this point. Loading a bundled
     * sample marks the project a demonstration, which no amount of GPS
     * clears - rightly, since Dr Timbo's water quality workbook is synthetic
     * - so a fixture that is testing the evidence gate has to stop being one
     * first. This is what an analyst does: look at the sample, then put their
     * own sheets in. */
    const savedSources = JSON.parse(JSON.stringify(app.store.get('sources')));
    Object.keys(savedSources).forEach((role) => {
      app.store.set('sources.' + role, {
        name: 'kambia_' + role + '.xlsx', b64: savedSources[role].b64,
      });
    });
    app.render();
    const complete = {
      state: app.reportReadiness('quality').state,
      ok: !!document.querySelector('#page-host .callout-ok'),
      doc: await buildQuality(),
    };

    // take the position off every sheet: a borehole nobody can find again
    sites.forEach((s) => { s.easting = null; s.northing = null; });
    app.render();
    const missing = {
      state: app.reportReadiness('quality').state,
      bad: !!document.querySelector('#page-host .callout-bad'),
      names: panelText(),
      doc: await buildQuality(),
    };

    // an override with no reason is not an override
    const fill = (placeholder, value) => {
      const input = document.querySelector(
        '#page-host input[placeholder="' + placeholder + '"]');
      if (!input) return false;
      input.value = value;
      input.dispatchEvent(new Event('change'));
      return true;
    };
    const press = (label) => {
      const btn = Array.from(document.querySelectorAll('#page-host button'))
        .find((b) => b.textContent === label);
      if (btn) btn.click();
      return !!btn;
    };
    const typedName = fill('Name', 'M. Kolleh');
    press('Record override');
    const refused = {
      state: app.reportReadiness('quality').state,
      recorded: Object.keys((app.store.get('overrides') || {}).quality || {}).length,
    };

    // ...and a reason with nobody's name against it is not one either: an
    // override is somebody's authority standing in for missing evidence
    fill('Name', '');
    fill('Why this is being issued now', 'GPS unit failed; position to follow');
    press('Record override');
    const unsigned = {
      state: app.reportReadiness('quality').state,
      recorded: Object.keys((app.store.get('overrides') || {}).quality || {}).length,
    };

    fill('Name', 'M. Kolleh');
    fill('Why this is being issued now', 'GPS unit failed; position to follow');
    const pressed = press('Record override');
    const issued = {
      state: app.reportReadiness('quality').state,
      warn: !!document.querySelector('#page-host .callout-warn'),
      doc: await buildQuality(),
    };

    press('Clear overrides');
    const cleared = app.reportReadiness('quality').state;
    site.easting = 778000; site.northing = 946000;
    const restored = app.reportReadiness('quality').state;

    sites.forEach((s, i) => {
      s.easting = saved[i][0]; s.northing = saved[i][1]; s.utm_zone = saved[i][2];
    });
    app.store.set('sources', savedSources);
    app.store.set('overrides', {});
    app.render();
    return { complete, missing, refused, unsigned, issued, cleared, typedName,
      pressed, restored };
  });
  check('gate: a complete project reports as ready and carries no stamp',
    gate.complete.state === 'ready' && gate.complete.ok === true &&
    !gate.complete.doc.includes('PROVISIONAL'),
    JSON.stringify({ state: gate.complete.state, ok: gate.complete.ok }));
  check('gate: missing evidence is named on the page, not just counted',
    gate.missing.state === 'not_ready' && gate.missing.bad === true &&
    gate.missing.names.includes('Site position'),
    JSON.stringify({ state: gate.missing.state, bad: gate.missing.bad }));
  check('gate: the report is still produced, stamped provisional',
    gate.missing.doc.includes('PROVISIONAL - NOT FOR CERTIFICATION') &&
    gate.missing.doc.includes('Site position'));
  check('gate: an override without a reason is refused',
    gate.typedName === true && gate.refused.state === 'not_ready' &&
    gate.refused.recorded === 0, JSON.stringify(gate.refused));
  check('gate: an override nobody has put their name to is refused',
    gate.unsigned.state === 'not_ready' && gate.unsigned.recorded === 0,
    JSON.stringify(gate.unsigned));
  check('gate: an override issues the report and names who issued it',
    gate.pressed === true && gate.issued.state === 'ready_with_overrides' &&
    gate.issued.warn === true &&
    gate.issued.doc.includes('ISSUED ON OVERRIDE - NOT A CERTIFICATION') &&
    gate.issued.doc.includes('M. Kolleh') &&
    gate.issued.doc.includes('GPS unit failed'),
    JSON.stringify({ state: gate.issued.state, warn: gate.issued.warn }));
  check('gate: clearing the override puts the requirement back',
    gate.cleared === 'not_ready' && gate.restored === 'ready',
    JSON.stringify({ cleared: gate.cleared, restored: gate.restored }));

  // --- the API key never reaches long-term storage ------------------------
  // It used to be a field of the persisted state, so the store mirrored it
  // into localStorage on every change: unencrypted, surviving a browser
  // restart, readable by anything with script access to this origin. The
  // session is in IndexedDB now; the key is in neither.
  const credential = await page.evaluate(async () => {
    const app = window.GWT.app;
    const stored = async () => (localStorage.getItem('gwt.project.v1') || '')
      .includes('sk-ant-smoke-test-key') ||
      JSON.stringify(await app.storage.readBack() || {}).includes('sk-ant-smoke-test-key');
    app.setApiKey('sk-ant-smoke-test-key', false);
    const inMemory = {
      readable: app.getApiKey(),
      inSession: sessionStorage.getItem('gwt.credential.v1'),
      inLocal: await stored(),
      inState: JSON.stringify(app.store.state).includes('sk-ant-smoke-test-key'),
    };
    app.store.set('site.community', 'typed with a key held');
    inMemory.persisted = await app.store.persist();
    inMemory.inLocalAfterPersist = await stored();

    // opting in puts it in sessionStorage, which the browser drops with the tab
    app.setApiKey('sk-ant-smoke-test-key', true);
    const remembered = sessionStorage.getItem('gwt.credential.v1');
    app.store.set('site.community', 'typed with a key remembered');
    await app.store.persist();
    const stillNotInLocal = !(await stored());

    app.forgetApiKey();
    return Object.assign(inMemory, {
      remembered,
      stillNotInLocal,
      forgotten: app.getApiKey(),
      sessionCleared: sessionStorage.getItem('gwt.credential.v1'),
    });
  });
  check('credentials: the key is usable in this tab',
    credential.readable === 'sk-ant-smoke-test-key', JSON.stringify(credential));
  check('credentials: it is not in the session state',
    credential.inState === false, JSON.stringify(credential));
  check('credentials: it is never written to long-term storage',
    credential.inLocal === false && credential.inLocalAfterPersist === false &&
    credential.persisted === true && credential.stillNotInLocal === true,
    JSON.stringify(credential));
  check('credentials: memory-only by default, session storage on opt-in',
    credential.inSession === null &&
    credential.remembered === 'sk-ant-smoke-test-key',
    JSON.stringify(credential));
  check('credentials: forgetting it is a real sweep',
    credential.forgotten === '' && credential.sessionCleared === null,
    JSON.stringify(credential));

  // a project file is meant to be mailed to a colleague
  const shared = await page.evaluate(async () => {
    const app = window.GWT.app;
    app.setApiKey('sk-ant-shared-file-key', true);
    /* an older build could also leave a stale field in the store itself */
    app.store.set('extraction.apiKey', 'sk-ant-stale-store-key');
    let captured = '';
    const original = window.GWT.support.download;
    window.GWT.support.download = (name, body) => { captured = String(body); };
    app.goto('settings');
    app.render();
    document.querySelectorAll('button').forEach((b) => {
      if (b.textContent === 'Save project file') b.click();
    });
    window.GWT.support.download = original;
    app.forgetApiKey();
    app.store.remove('extraction.apiKey');
    return {
      length: captured.length,
      carriesKey: captured.includes('sk-ant-shared-file-key'),
      carriesStale: captured.includes('sk-ant-stale-store-key'),
    };
  });
  check('credentials: a saved project file never carries the key',
    shared.length > 100 && !shared.carriesKey && !shared.carriesStale,
    JSON.stringify(shared));

  // --- autosave failure is announced --------------------------------------
  // Storage quota is finite and photographs are large. Autosave dropping out
  // silently is the worst thing this app can do to a day of fieldwork. Quota
  // is simulated by an IndexedDB put that throws QuotaExceededError, which
  // abandons the write's whole transaction, as a real one does.
  await page.evaluate(() => {
    const original = IDBObjectStore.prototype.put;
    window.__quota = {
      fill() {
        IDBObjectStore.prototype.put = function () {
          const err = new Error('quota');
          err.name = 'QuotaExceededError';
          throw err;
        };
      },
      free() { IDBObjectStore.prototype.put = original; },
    };
  });
  const autosave = await page.evaluate(async () => {
    const store = window.GWT.app.store;
    window.__quota.fill();
    store.set('site.community', 'typed as the quota filled');
    const okDuringFailure = await store.persist();
    const failingState = store.autosaveOk();
    const bannerShown = !!document.querySelector('#autosave-banner .callout-bad');
    window.__quota.free();
    const okAfterRecovery = await store.persist();
    const stored = await window.GWT.app.storage.readBack();
    return {
      okDuringFailure, failingState, bannerShown, okAfterRecovery,
      recovered: store.autosaveOk(),
      bannerCleared: !document.querySelector('#autosave-banner .callout-bad'),
      bannerText: document.querySelector('#autosave-banner')?.textContent || '',
      caughtUp: stored.site.community === 'typed as the quota filled',
    };
  });
  check('autosave: a failed mirror write is reported, not swallowed',
    autosave.okDuringFailure === false && autosave.failingState === false &&
    autosave.bannerShown === true, JSON.stringify(autosave));
  check('autosave: the warning clears once writing works again, and the change is kept',
    autosave.okAfterRecovery === true && autosave.recovered === true &&
    autosave.bannerCleared === true && autosave.caughtUp === true, JSON.stringify(autosave));

  // A failed write used to delete the copy that had already succeeded, so the
  // first photograph that filled the quota took this morning's drilling log
  // with it and the next load opened a blank app. An hour-old copy is worth
  // having; nothing is not.
  const mirror = await page.evaluate(async () => {
    const store = window.GWT.app.store, storage = window.GWT.app.storage;
    await store.persist();
    const before = JSON.stringify(await storage.readBack());

    window.__quota.fill();
    store.set('site.community', 'typed after the quota filled');
    const failed = await store.persist();
    window.__quota.free();

    /* and the copy still reads back into a project, unchanged */
    const restored = await storage.readBack();
    const after = JSON.stringify(restored);
    /* read the banner before restoring: a successful write clears it */
    const banner = document.querySelector('#autosave-banner')?.textContent || '';
    await store.persist();
    return {
      failed,
      banner,
      survived: after === before,
      restorable: !!(restored && typeof restored === 'object' && restored.site),
    };
  });
  check('autosave: a failed write leaves the copy that already succeeded',
    mirror.failed === false && mirror.survived === true &&
    mirror.restorable === true, JSON.stringify(mirror));
  // ...and the banner says so. The two failures need opposite warnings, so
  // each has to be pinned against the other's wording: a banner that always
  // said "nothing was stored" would be just as wrong as one that always
  // promised a copy, and either passes a test that only checks one case.
  check('autosave: a surviving copy is what the banner reports',
    /copy it already had is still there/.test(mirror.banner) &&
    !/has not managed to store the session even once/.test(mirror.banner),
    JSON.stringify(mirror.banner));

  // But on a browser that has never managed a single write - a private
  // window, or a tablet whose storage was full before the app opened - there
  // is no copy, and the banner must not say there is. That is the case where
  // the whole day is at stake rather than the last few minutes, so it is the
  // case where a promised backup does the most damage.
  const nothingKept = await page.evaluate(async () => {
    const store = window.GWT.app.store;
    /* return the store to the healthy state first, so the stub below causes
     * the transition that fires onPersistError; without this the block
     * depends on whatever the previous one left behind */
    await store.persist();
    await store.forget();

    window.__quota.fill();
    store.set('site.community', 'typed in a private window');
    await store.persist();
    window.__quota.free();

    /* read the banner before restoring the store: a successful write fires
     * onPersistRecovered, which clears the host */
    const text = document.querySelector('#autosave-banner')?.textContent || '';
    const shown = !!document.querySelector('#autosave-banner .callout-bad');
    await store.persist();
    return { shown, text };
  });
  check('autosave: a browser that never stored anything is not promised a copy',
    nothingKept.shown === true &&
    /has not managed to store the session even once/.test(nothingKept.text) &&
    !/copy it already had is still there/.test(nothingKept.text),
    JSON.stringify(nothingKept));

  // --- where the session is kept (PLAN.md step 1.3) -----------------------
  // Each of these opens the app in a browser context of its own, so its
  // storage starts empty and nothing here reaches the page above.
  const browser = page.context().browser();
  const freshTab = async (init) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    if (init) await context.addInitScript(init.fn, init.arg);
    const errors = [];
    const open = async () => {
      const tab = await context.newPage();
      tab.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
      tab.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
      await tab.goto(base + '/index.html', { waitUntil: 'load' });
      await tab.waitForFunction(() => window.GWT && window.GWT.app &&
        document.querySelector('#page-host .page-head'));
      return tab;
    };
    return { context, errors, open };
  };
  const settled = (tab) => tab.waitForFunction(() =>
    !window.GWT.app.recomputeState.running && !window.GWT.app.working('invert') &&
    !window.GWT.app.working('pumping'), null, { timeout: 120000 });
  /* the session as a digest, leaving out the page it is on */
  const digest = (tab) => tab.evaluate(async () => {
    const state = Object.assign({}, window.GWT.app.store.state, { nav: null });
    const bytes = new TextEncoder().encode(JSON.stringify(state));
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('');
  });

  // A project with 50 photos and 10 workbooks autosaves in under 50 ms of
  // main-thread time, and survives a reload. Before this step the same
  // autosave stringified 20.6 MB into localStorage in about 90 ms, and was
  // refused for quota every time.
  const heavy = await (async () => {
    const { context, errors, open } = await freshTab();
    try {
      const tab = await open();
      const timed = await timeAutosaves(tab, { samples: 5 });
      const built = timed.built, first = timed.first;
      const times = timed.edits.map((t) => t.main);
      const writes = timed.edits.map((t) => t.value);
      /* a caption is one record; a replaced photo is that record, one file
       * written and the one it replaced deleted */
      const photoEdits = await tab.evaluate(async () => {
        const app = window.GWT.app, S = window.GWT.support;
        const set = JSON.parse(JSON.stringify(app.store.get('photos.completion')));
        const keep = (p) => Object.assign({}, p);
        const next = Object.assign({}, app.store.get('photos.completion'));
        next.site = Object.assign(keep(next.site), { caption: 'A new caption' });
        app.store.set('photos.completion', next);
        await app.store.persist();
        const caption = app.storage.stats.last;
        const bytes = S.base64ToBytes(set.drilling.dataUrl);
        bytes[bytes.length - 3] ^= 0xff;
        const replaced = Object.assign({}, app.store.get('photos.completion'));
        replaced.drilling = Object.assign(keep(replaced.drilling),
          { dataUrl: 'data:image/jpeg;base64,' + S.bytesToBase64(bytes) });
        app.store.set('photos.completion', replaced);
        await app.store.persist();
        return { caption, replaced: app.storage.stats.last };
      });
      await settled(tab);
      const before = await digest(tab);
      await tab.reload({ waitUntil: 'load' });
      await tab.waitForFunction(() => window.GWT && window.GWT.app &&
        document.querySelector('#page-host .page-head'));
      await settled(tab);
      const after = await digest(tab);
      const reloaded = await tab.evaluate(() => {
        const photos = window.GWT.app.store.get('photos');
        return {
          photos: Object.values(photos).reduce((n, set) => n +
            Object.keys(set).filter((k) => k !== '__extra' && set[k]).length +
            (set.__extra || []).filter((e) => e.image).length, 0),
          workbooks: Object.keys(window.GWT.app.store.get('sources')).length,
          caption: photos.completion.site.caption,
        };
      });
      /* the first write after a reload stores only what changed after it */
      const afterReload = await tab.evaluate(async () => {
        /* what went to IndexedDB, counted at IndexedDB rather than taken
         * from the storage module's own account of it */
        const original = IDBObjectStore.prototype.put;
        const puts = [];
        IDBObjectStore.prototype.put = function (value, key) {
          puts.push(this.name + ':' + key);
          return original.call(this, value, key);
        };
        try {
          window.GWT.app.store.set('site.community', 'typed after the reload');
          await window.GWT.app.store.persist();
        } finally {
          IDBObjectStore.prototype.put = original;
        }
        return Object.assign({ puts: puts.sort().join() }, window.GWT.app.storage.stats.last);
      });
      /* the Settings page says where it is kept and how much room it takes */
      await tab.evaluate(() => window.GWT.app.goto('settings'));
      await tab.waitForFunction(() =>
        /In use: [\d.]+ [MG]B of about/.test(document.querySelector('#page-host').textContent),
      null, { timeout: 10000 });
      const settings = await tab.evaluate(() =>
        document.querySelector('#page-host').textContent.includes('IndexedDB'));
      return { built, first, times, writes, photoEdits, before, after, reloaded,
        afterReload, settings, errors };
    } finally {
      await context.close();
    }
  })();
  const heavyMedian = [...heavy.times].sort((a, b) => a - b)[2];
  check('storage: a project with 50 photos and 10 workbooks autosaves in under 50 ms',
    heavy.built.photos === 50 && heavy.built.workbooks === 10 && heavy.first.value.ok &&
    heavy.writes.every((w) => w.ok) && heavyMedian < 50,
    JSON.stringify({ built: heavy.built, mainMs: heavy.times, firstWriteMs: heavy.first.main,
      first: heavy.first.value }));
  check('storage: a changed field writes its record and nothing else',
    heavy.writes.every((w) => w.last.records.join() === 'site' && w.last.blobs === 0 &&
      w.last.orphans === 0 && w.last.removed.length === 0 && w.last.cache === 0) &&
    heavy.afterReload.records.join() === 'site' && heavy.afterReload.blobs === 0 &&
    heavy.afterReload.puts === 'meta:saved,records:site',
    JSON.stringify([heavy.writes[0], heavy.afterReload]));
  check('storage: a caption writes the photo record, a replaced photo one file',
    heavy.photoEdits.caption.records.join() === 'photos' &&
    heavy.photoEdits.caption.blobs === 0 && heavy.photoEdits.caption.orphans === 0 &&
    heavy.photoEdits.replaced.records.join() === 'photos' &&
    heavy.photoEdits.replaced.blobs === 1 && heavy.photoEdits.replaced.orphans === 1,
    JSON.stringify(heavy.photoEdits));
  check('storage: the heavy project survives a reload exactly',
    heavy.before === heavy.after && heavy.reloaded.photos === 50 &&
    heavy.reloaded.workbooks === 10 && heavy.reloaded.caption === 'A new caption',
    JSON.stringify({ before: heavy.before, after: heavy.after, reloaded: heavy.reloaded }));
  check('storage: the Settings page shows where the session is kept, and how much room',
    heavy.settings === true, JSON.stringify(heavy.settings));
  check('storage: no console errors with the heavy project', heavy.errors.length === 0,
    heavy.errors.slice(0, 5).join('\n     '));

  // A session an earlier build left in localStorage is moved into IndexedDB
  // on the first visit, and the old key goes only once the new copy reads
  // back as the same session. A key the old build stored with it stays out.
  const legacyPhoto = 'data:image/jpeg;base64,' +
    Buffer.from(Array.from({ length: 30000 }, (_, i) => (i * 7919) % 251)).toString('base64');
  const legacy = JSON.stringify({
    nav: 'site', theme: 'dark',
    site: { project: 'Moved from localStorage', community: 'Kuntolo' },
    photos: { completion: { site: { dataUrl: legacyPhoto, width: 10, height: 10,
      mime: 'image/jpeg', caption: 'Old photo' }, __extra: [] } },
    extraction: { model: '', apiKey: 'sk-ant-left-by-an-old-build' },
    inversionCache: {},
  });
  const seedLegacy = {
    fn: (text) => {
      if (sessionStorage.getItem('seeded')) return;
      sessionStorage.setItem('seeded', '1');
      localStorage.setItem('gwt.project.v1', text);
    },
    arg: legacy,
  };
  const migrated = await (async () => {
    const { context, errors, open } = await freshTab(seedLegacy);
    try {
      const tab = await open();
      await tab.waitForFunction(() => localStorage.getItem('gwt.project.v1') === null,
        null, { timeout: 10000 }).catch(() => {});
      const first = await tab.evaluate(async (photo) => {
        const app = window.GWT.app;
        const stored = await app.storage.readBack();
        return {
          project: app.store.get('site.project'),
          photo: app.store.get('photos.completion.site.dataUrl') === photo,
          legacyKey: localStorage.getItem('gwt.project.v1'),
          storedProject: stored && stored.site.project,
          storedPhoto: !!stored && stored.photos.completion.site.dataUrl === photo,
          key: JSON.stringify(stored).includes('sk-ant-left-by-an-old-build') ||
            JSON.stringify(app.store.state).includes('sk-ant-left-by-an-old-build'),
        };
      }, legacyPhoto);
      await tab.reload({ waitUntil: 'load' });
      await tab.waitForFunction(() => window.GWT && window.GWT.app &&
        document.querySelector('#page-host .page-head'));
      const reloaded = await tab.evaluate((photo) => ({
        project: window.GWT.app.store.get('site.project'),
        photo: window.GWT.app.store.get('photos.completion.site.dataUrl') === photo,
      }), legacyPhoto);
      return { first, reloaded, errors };
    } finally {
      await context.close();
    }
  })();
  check('storage: an earlier build\'s localStorage session is moved into IndexedDB',
    migrated.first.project === 'Moved from localStorage' && migrated.first.photo &&
    migrated.first.storedProject === 'Moved from localStorage' && migrated.first.storedPhoto &&
    migrated.reloaded.project === 'Moved from localStorage' && migrated.reloaded.photo,
    JSON.stringify(migrated));
  check('storage: the old key goes once moved, and the API key in it goes nowhere',
    migrated.first.legacyKey === null && migrated.first.key === false,
    JSON.stringify(migrated.first));

  // A move that IndexedDB refuses leaves the old copy where it was, and the
  // banner says it is no longer being updated rather than that it is gone.
  const stuck = await (async () => {
    const { context, open } = await freshTab({
      fn: (text) => {
        if (!sessionStorage.getItem('seeded')) {
          sessionStorage.setItem('seeded', '1');
          localStorage.setItem('gwt.project.v1', text);
        }
        IDBObjectStore.prototype.put = function () {
          const err = new Error('quota');
          err.name = 'QuotaExceededError';
          throw err;
        };
      },
      arg: legacy,
    });
    try {
      const tab = await open();
      await tab.waitForFunction(() => !!document.querySelector('#autosave-banner .callout-bad'),
        null, { timeout: 10000 }).catch(() => {});
      return await tab.evaluate(() => ({
        project: window.GWT.app.store.get('site.project'),
        legacyKept: !!localStorage.getItem('gwt.project.v1'),
        banner: document.querySelector('#autosave-banner')?.textContent || '',
      }));
    } finally {
      await context.close();
    }
  })();
  check('storage: a move that is refused keeps the old copy, and says so',
    stuck.project === 'Moved from localStorage' && stuck.legacyKept &&
    /copy it already had is still there/.test(stuck.banner), JSON.stringify(stuck));

  // Where IndexedDB is missing or throws - some private windows, some
  // browsers on file:// - the app still runs, and says at once, in the
  // autosave banner's words, that it is saving nothing.
  const fallback = await (async () => {
    const { context, errors, open } = await freshTab({
      fn: () => {
        Object.defineProperty(window, 'indexedDB', {
          configurable: true,
          get() { throw new DOMException('The user denied permission.', 'SecurityError'); },
        });
      },
    });
    try {
      const tab = await open();
      await tab.waitForFunction(() => !!document.querySelector('#autosave-banner .callout-bad'),
        null, { timeout: 10000 }).catch(() => {});
      const banner = await tab.evaluate(() =>
        document.querySelector('#autosave-banner')?.textContent || '');
      const works = await tab.evaluate(async () => {
        const app = window.GWT.app;
        await app.loadSample('dr_timbo');
        app.store.set('site.community', 'typed with nowhere to keep it');
        return { ok: await app.store.persist(), analysis: !!app.derived.analysis,
          mode: app.storage.mode };
      });
      await tab.evaluate(() => window.GWT.app.goto('settings'));
      await tab.waitForFunction(() => document.querySelector('#page-host').textContent
        .includes('will not keep the session'), null, { timeout: 10000 }).catch(() => {});
      const settings = await tab.evaluate(() =>
        document.querySelector('#page-host').textContent.includes('will not keep the session'));
      return { banner, works, settings, errors };
    } finally {
      await context.close();
    }
  })();
  check('storage: with no IndexedDB the app runs, and says it is saving nothing',
    /Nothing is being autosaved/.test(fallback.banner) &&
    /has not managed to store the session even once/.test(fallback.banner) &&
    fallback.works.analysis && fallback.works.ok === false && fallback.works.mode === 'none' &&
    fallback.settings, JSON.stringify(fallback));
  check('storage: no console errors with no IndexedDB', fallback.errors.length === 0,
    fallback.errors.slice(0, 5).join('\n     '));

  // Two tabs on one browser. Only one saves; the other says so and saves
  // nothing, so the copy on disk is never records of two sessions mixed.
  // "Continue here" moves the saving, and the tab that had it says so.
  const tabs = await (async () => {
    const { context, errors, open } = await freshTab();
    try {
      const first = await open();
      await first.evaluate(async () => {
        window.GWT.app.store.set('site.community', 'typed in the first tab');
        await window.GWT.app.store.persist();
      });
      const second = await open();
      await second.waitForFunction(() =>
        /Another tab is saving this project/.test(
          document.querySelector('#autosave-banner')?.textContent || ''),
      null, { timeout: 10000 }).catch(() => {});
      const readerView = await second.evaluate(async () => {
        const app = window.GWT.app;
        const opened = app.store.get('site.community');
        app.store.set('site.community', 'typed in the second tab');
        return { opened, role: app.storage.role, ok: await app.store.persist(),
          banner: document.querySelector('#autosave-banner')?.textContent || '' };
      });
      const firstStill = await first.evaluate(async () => {
        const app = window.GWT.app;
        app.store.set('site.client', 'still the first tab');
        const ok = await app.store.persist();
        const stored = await app.storage.readBack();
        return { ok, community: stored.site.community, client: stored.site.client,
          banner: !!document.querySelector('#autosave-banner .callout-bad') };
      });
      await second.getByRole('button', { name: 'Continue here' }).click();
      await second.waitForFunction(() => window.GWT.app.storage.role === 'writer' &&
        !document.querySelector('#autosave-banner .callout-bad'), null, { timeout: 10000 })
        .catch(() => {});
      await first.waitForFunction(() => /Another tab is saving this project/.test(
        document.querySelector('#autosave-banner')?.textContent || ''), null, { timeout: 10000 })
        .catch(() => {});
      const moved = await second.evaluate(async () => {
        const app = window.GWT.app;
        const opened = { community: app.store.get('site.community'),
          client: app.store.get('site.client') };
        app.store.set('site.community', 'typed after continuing here');
        return { opened, role: app.storage.role, ok: await app.store.persist() };
      });
      const firstAfter = await first.evaluate(async () => {
        const app = window.GWT.app;
        app.store.set('site.community', 'typed in the first tab after it lost the saving');
        const ok = await app.store.persist();
        const stored = await app.storage.readBack();
        return { ok, role: app.storage.role, community: stored.site.community,
          banner: document.querySelector('#autosave-banner')?.textContent || '' };
      });
      return { readerView, firstStill, moved, firstAfter, errors };
    } finally {
      await context.close();
    }
  })();
  check('tabs: a second tab opens the saved copy and saves nothing, and says so',
    tabs.readerView.opened === 'typed in the first tab' && tabs.readerView.role === 'reader' &&
    tabs.readerView.ok === false && /Another tab is saving this project/.test(tabs.readerView.banner) &&
    tabs.firstStill.ok && tabs.firstStill.community === 'typed in the first tab' &&
    tabs.firstStill.client === 'still the first tab' && !tabs.firstStill.banner,
    JSON.stringify([tabs.readerView, tabs.firstStill]));
  check('tabs: "Continue here" moves the saving, with what the other tab had saved',
    tabs.moved.role === 'writer' && tabs.moved.ok &&
    tabs.moved.opened.community === 'typed in the first tab' &&
    tabs.moved.opened.client === 'still the first tab' &&
    tabs.firstAfter.ok === false && tabs.firstAfter.role === 'reader' &&
    tabs.firstAfter.community === 'typed after continuing here' &&
    /Another tab is saving this project/.test(tabs.firstAfter.banner),
    JSON.stringify([tabs.moved, tabs.firstAfter]));
  check('tabs: no console errors', tabs.errors.length === 0,
    tabs.errors.slice(0, 5).join('\n     '));

  // An autosave that falls due while "Continue here" is taking the saving
  // over holds this tab's own session, which is older than what the other
  // tab saved. It must not be written over that before this tab reads it.
  const takeover = await (async () => {
    const { context, errors, open } = await freshTab();
    try {
      const first = await open();
      await first.evaluate(async () => {
        window.GWT.app.store.set('site.community', 'typed in the first tab');
        await window.GWT.app.store.persist();
      });
      const second = await open();
      await second.evaluate(() => window.GWT.app.storage.ready);
      await first.evaluate(async () => {
        window.GWT.app.store.set('site.client', 'typed in the first tab after');
        await window.GWT.app.store.persist();
      });
      const out = await second.evaluate(async () => {
        const app = window.GWT.app;
        app.store.set('site.community', 'typed in the second tab');
        const moving = app.continueHere();
        app.store.persist();
        await moving;
        const stored = await app.storage.readBack();
        return { role: app.storage.role, client: app.store.get('site.client'),
          storedClient: stored.site.client };
      });
      /* and the change made just before the tab is put away - switched
       * from, or the phone locked, after which it may be frozen and never
       * run its 400 ms autosave - is written as it is hidden */
      out.hidden = await second.evaluate(async () => {
        const app = window.GWT.app;
        app.store.set('site.client', 'typed as it was hidden');
        Object.defineProperty(document, 'visibilityState',
          { configurable: true, get() { return 'hidden'; } });
        document.dispatchEvent(new Event('visibilitychange'));
        await new Promise((resolve) => setTimeout(resolve, 100));
        return (await app.storage.readBack()).site.client;
      });
      return Object.assign(out, { errors });
    } finally {
      await context.close();
    }
  })();
  check('tabs: an autosave during "Continue here" does not overwrite the other tab\'s copy',
    takeover.role === 'writer' && takeover.client === 'typed in the first tab after' &&
    takeover.storedClient === 'typed in the first tab after', JSON.stringify(takeover));
  check('storage: the last change is written as the tab is hidden, not 400 ms later',
    takeover.hidden === 'typed as it was hidden' && takeover.errors.length === 0,
    JSON.stringify(takeover));

  // Without Web Locks (an older browser) the newest tab takes the saving
  // over when it opens, and the one that had it is refused and says so.
  const unlocked = await (async () => {
    const { context, errors, open } = await freshTab({
      fn: () => {
        Object.defineProperty(Navigator.prototype, 'locks',
          { configurable: true, get() { return undefined; } });
      },
    });
    try {
      const first = await open();
      await first.evaluate(async () => {
        window.GWT.app.store.set('site.community', 'typed in the first tab');
        await window.GWT.app.store.persist();
      });
      const second = await open();
      const newest = await second.evaluate(async () => {
        await window.GWT.app.storage.ready;
        return { role: window.GWT.app.storage.role,
          community: window.GWT.app.store.get('site.community') };
      });
      const older = await first.evaluate(async () => {
        const app = window.GWT.app;
        app.store.set('site.community', 'typed in the older tab');
        const ok = await app.store.persist();
        const stored = await app.storage.readBack();
        return { ok, role: app.storage.role, stored: stored.site.community,
          banner: document.querySelector('#autosave-banner')?.textContent || '' };
      });
      return { newest, older, errors };
    } finally {
      await context.close();
    }
  })();
  check('tabs: without Web Locks the newest tab saves, and the older one says it does not',
    unlocked.newest.role === 'writer' && unlocked.newest.community === 'typed in the first tab' &&
    unlocked.older.ok === false && unlocked.older.role === 'reader' &&
    unlocked.older.stored === 'typed in the first tab' &&
    /Another tab is saving this project/.test(unlocked.older.banner) &&
    unlocked.errors.length === 0, JSON.stringify(unlocked));

  // A session an earlier build wrote to localStorage after the move - the
  // user went back to an older copy of the app for a while - is the newer
  // one, and is opened rather than deleted. The old key kept because its
  // move did not read back is not: the copy here has moved on from it.
  const older = await (async () => {
    const { context, errors, open } = await freshTab();
    const reopen = async (tab) => {
      await tab.reload({ waitUntil: 'load' });
      await tab.waitForFunction(() => window.GWT && window.GWT.app &&
        document.querySelector('#page-host .page-head'));
      await tab.evaluate(() => window.GWT.app.storage.ready);
    };
    const oldSession = JSON.stringify({ nav: 'site',
      site: { project: 'Older build', community: 'typed in an older build' } });
    try {
      const tab = await open();
      await tab.evaluate(async () => {
        window.GWT.app.store.set('site.community', 'typed in this build');
        await window.GWT.app.store.persist();
      });
      await tab.evaluate((text) => localStorage.setItem('gwt.project.v1', text), oldSession);
      await reopen(tab);
      const taken = await tab.evaluate(async () => {
        const app = window.GWT.app;
        await new Promise((resolve) => setTimeout(resolve, 200));
        return { community: app.store.get('site.community'),
          stored: (await app.storage.readBack()).site.community,
          legacyKey: localStorage.getItem('gwt.project.v1') !== null };
      });
      await tab.evaluate(async () => {
        window.GWT.app.store.set('site.community', 'typed after the move');
        await window.GWT.app.store.persist();
      });
      await tab.evaluate((text) => localStorage.setItem('gwt.project.v1', text), oldSession);
      await reopen(tab);
      const kept = await tab.evaluate(() => ({
        community: window.GWT.app.store.get('site.community'),
        legacyKey: localStorage.getItem('gwt.project.v1') !== null }));
      return { taken, kept, errors };
    } finally {
      await context.close();
    }
  })();
  check('storage: an older build\'s later session is opened, not deleted',
    older.taken.community === 'typed in an older build' &&
    older.taken.stored === 'typed in an older build' && older.taken.legacyKey === false,
    JSON.stringify(older));
  check('storage: the old key already moved does not come back over newer work',
    older.kept.community === 'typed after the move' && older.kept.legacyKey === false &&
    older.errors.length === 0, JSON.stringify(older));

  // --- addresses: every page has one ---------------------------------------
  // Each page opened cold, in a tab of its own, by nothing but its URL: the
  // way a link in the user guide or a QR code on a field sheet opens it.
  const TITLES = await page.evaluate(() => Object.fromEntries(
    Array.from(document.querySelectorAll('#app-nav .nav-item')).map((b) => [b.textContent, 1])));
  const byUrl = await (async () => {
    const tab = await page.context().newPage();
    const errors = [];
    tab.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    tab.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
    const opened = {};
    try {
      for (const key of PAGES) {
        await tab.goto('about:blank');
        await tab.goto(base + '/index.html#/' + key, { waitUntil: 'load' });
        await tab.waitForFunction((k) => {
          const app = window.GWT && window.GWT.app;
          const host = document.querySelector('#page-host');
          return app && app.store.get('nav') === k && host &&
            !host.textContent.includes('Loading the maps and figures');
        }, key, { timeout: 60000 });
        opened[key] = await tab.evaluate(() => ({
          hash: location.hash,
          active: document.querySelector('#app-nav .nav-item.active')?.textContent || '',
          title: document.querySelector('#page-host .page-head h1')?.textContent || '',
          broken: Array.from(document.querySelectorAll('#page-host .callout-bad strong'))
            .some((n) => /^(Something went wrong|This page could not be loaded)/
              .test(n.textContent)),
        }));
      }
    } finally {
      await tab.close();
    }
    return { opened, errors };
  })();
  const wrongPage = PAGES.filter((key) => {
    const o = byUrl.opened[key];
    return !o || o.hash !== '#/' + key || !o.active || !TITLES[o.active] || o.broken ||
      !o.title;
  });
  check('addresses: every page opens by its URL, in a fresh tab',
    wrongPage.length === 0,
    JSON.stringify(wrongPage.map((k) => [k, byUrl.opened[k]])));
  check('addresses: no console errors opening pages by URL', byUrl.errors.length === 0,
    byUrl.errors.slice(0, 5).join('\n     '));

  // Back and forward move between pages, as the address records them.
  const history = await (async () => {
    const tab = await page.context().newPage();
    try {
      await tab.goto(base + '/index.html', { waitUntil: 'load' });
      await tab.waitForFunction(() => window.GWT && window.GWT.app);
      const at = () => tab.evaluate(() => [window.GWT.app.store.get('nav'), location.hash]);
      const seen = { start: await at() };
      await tab.locator('#app-nav').getByRole('button', { name: 'Geophysics (VES)' }).click();
      await tab.locator('#app-nav').getByRole('button', { name: 'Pumping test' }).click();
      seen.clicked = await at();
      await tab.goBack();
      await tab.waitForFunction(() => window.GWT.app.store.get('nav') === 'ves');
      seen.back = await at();
      await tab.goBack();
      await tab.waitForFunction((k) => window.GWT.app.store.get('nav') === k, seen.start[0]);
      seen.backAgain = await at();
      await tab.goForward();
      await tab.waitForFunction(() => window.GWT.app.store.get('nav') === 'ves');
      seen.forward = await at();
      // a mistyped or out-of-date address is the Overview, and says so in
      // the address bar, rather than an error
      await tab.evaluate(() => { location.hash = '#/no-such-page/at-all'; });
      await tab.waitForFunction(() => location.hash === '#/overview');
      seen.unknown = await at();
      seen.broken = await tab.evaluate(() => !!document.querySelector('#page-host .callout-bad'));
      seen.title = await tab.evaluate(() =>
        document.querySelector('#page-host .page-head h1')?.textContent || '');
      return seen;
    } finally {
      await tab.close();
    }
  })();
  check('addresses: the page a session opens on has an address of its own',
    history.start[1] === '#/' + history.start[0], JSON.stringify(history));
  check('addresses: back and forward move between pages',
    history.clicked.join() === 'pumping,#/pumping' && history.back.join() === 'ves,#/ves' &&
    history.backAgain.join() === history.start.join() &&
    history.forward.join() === 'ves,#/ves', JSON.stringify(history));
  check('addresses: an unknown address falls back to the Overview',
    history.unknown.join() === 'overview,#/overview' && !history.broken &&
    history.title === 'Overview',
    JSON.stringify(history));

  // An item on a page has an address too: a sounding, a borehole.
  await page.evaluate(() => window.GWT.app.loadSample('rokel'));
  await page.waitForFunction(() => {
    const app = window.GWT.app;
    return !app.working('invert') && app.derived.interpretations &&
      app.derived.interpretations.length > 1;
  }, null, { timeout: 120000 });
  const items = await page.evaluate(async () => {
    const app = window.GWT.app;
    const wanted = app.derived.interpretations[1].sounding_id;
    location.hash = app.hashFor('ves', wanted);
    /* the main pane scrolls smoothly, so the card is given time to arrive */
    const arrived = () => {
      const node = document.querySelector('#page-host .item-target');
      const top = node ? node.getBoundingClientRect().top : Infinity;
      return top >= 0 && top < window.innerHeight / 2;
    };
    for (let waited = 0; waited < 5000 && !arrived(); waited += 100) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    const target = document.querySelector('#page-host .item-target');
    const out = {
      wanted, hash: location.hash, nav: app.store.get('nav'),
      marked: target ? target.getAttribute('data-item') : null,
      title: target ? target.querySelector('.card-title').textContent : '',
      inView: arrived(),
    };
    await app.goto('ves', 'VES-that-was-never-shot');
    out.missing = document.querySelector('#page-host .item-missing')?.textContent || '';
    /* the pumping test page's item is the borehole the test was run on */
    await app.loadSample('dr_timbo');
    out.borehole = app.derived.test.borehole_ref;
    await app.goto('pumping', out.borehole);
    out.boreholeMarked = document.querySelector('#page-host .item-target')
      ?.getAttribute('data-item') || null;
    out.boreholeHash = location.hash;
    await app.goto('overview');
    return out;
  });
  check('addresses: #/ves/<sounding> opens on that sounding',
    items.nav === 'ves' && items.marked === items.wanted &&
    items.title.startsWith(items.wanted) && items.inView, JSON.stringify(items));
  check('addresses: a sounding the project does not hold is said to be missing',
    items.missing.includes('VES-that-was-never-shot'), JSON.stringify(items.missing));
  check('addresses: #/pumping/<borehole> opens on that borehole\'s test',
    !!items.borehole && items.boreholeMarked === items.borehole &&
    items.boreholeHash === '#/pumping/' + encodeURIComponent(items.borehole),
    JSON.stringify(items));

  // Every page opened by URL above restored whatever this page had open, and
  // that project carried no water sample. The water quality page names each
  // result's status in the document writer's words, so opened cold on a
  // project with a sample, before anything else has fetched the writer, it
  // drew "Something went wrong" instead of its table.
  await page.waitForFunction(() => !window.GWT.app.recomputeState.running &&
    !!window.GWT.app.derived.assessment, null, { timeout: 120000 });
  /* the mirror is written 400 ms after a change; the tab restores from it */
  await page.evaluate(() => window.GWT.app.store.persist());
  const qualityCold = await (async () => {
    const tab = await page.context().newPage();
    const errors = [];
    tab.on('pageerror', (e) => errors.push(e.message));
    tab.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    try {
      await tab.goto(base + '/index.html#/quality', { waitUntil: 'load' });
      await tab.waitForFunction(() => {
        const app = window.GWT && window.GWT.app;
        const host = document.querySelector('#page-host');
        return app && !app.recomputeState.running && app.derived.assessment && host &&
          !host.textContent.includes('Loading the maps and figures');
      }, null, { timeout: 120000 });
      const drawn = await tab.evaluate(() => ({
        broken: /Something went wrong/.test(document.querySelector('#page-host').textContent),
        badges: document.querySelectorAll('#page-host table .badge').length,
      }));
      return Object.assign(drawn, { errors });
    } finally {
      await tab.close();
    }
  })();
  check('addresses: the water quality page opens by its URL on a project with a sample',
    !qualityCold.broken && qualityCold.badges > 0 && qualityCold.errors.length === 0,
    JSON.stringify(qualityCold));

  // --- offline: the app installs itself ------------------------------------
  // 127.0.0.1 is a secure context, so the real worker registers here.
  const worker = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready;
    return { scope: reg.scope, controlled: !!navigator.serviceWorker.controller };
  }).catch((e) => ({ error: String(e) }));
  check('offline: the service worker registers and takes control',
    !!worker.scope && worker.controlled === true, JSON.stringify(worker));

  const cached = await page.evaluate(async () => {
    const names = await caches.keys();
    const cache = await caches.open(names.find((n) => n.startsWith('gwt-v')));
    const keys = await cache.keys();
    const paths = keys.map((r) => new URL(r.url).pathname).sort();
    return {
      names,
      paths,
      /* the app itself is on disk ... */
      hasShell: paths.some((p) => p.endsWith('/index.html')),
      hasEngine: paths.some((p) => p.endsWith('/js/gwt-core.js')),
      hasData: paths.some((p) => p.endsWith('/js/gwt-data.js')),
      hasManifest: paths.some((p) => p.endsWith('/manifest.webmanifest')),
      /* ... and nothing that belongs to somebody else's server is */
      noForeign: keys.every((r) => new URL(r.url).origin === location.origin),
      noWasm: !paths.some((p) => p.includes('/wasm/')),
    };
  });
  check('offline: the whole app shell is precached',
    cached.hasShell && cached.hasEngine && cached.hasData && cached.hasManifest,
    JSON.stringify(cached.paths));
  check('offline: nothing cross-origin is cached',
    cached.noForeign === true && cached.noWasm === true,
    JSON.stringify(cached.paths));

  // The WPdx and Anthropic endpoints must never be answered from disk: a
  // stale water point inventory read back from cache is indistinguishable
  // from a live one, and an API key does not belong in a cache.
  const passthrough = await page.evaluate(async () => {
    const names = await caches.keys();
    const cache = await caches.open(names.find((n) => n.startsWith('gwt-v')));
    const probes = ['https://data.waterpointdata.org/resource/eqje-vguj.json?x=1',
      'https://api.anthropic.com/v1/messages'];
    const hits = [];
    for (const url of probes) {
      hits.push(!!(await cache.match(url, { ignoreSearch: true })));
    }
    return hits;
  });
  check('offline: external APIs are never served from the cache',
    passthrough.every((hit) => hit === false), JSON.stringify(passthrough));

  // With the network gone the app still opens: this is the whole point.
  const offlineLoad = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready;
    if (!reg.active) return { error: 'no active worker' };
    return { ok: true };
  });
  if (offlineLoad.ok) {
    await page.context().setOffline(true);
    await page.goto(base + '/index.html', { waitUntil: 'load' });
    const bootedOffline = await page.evaluate(() =>
      !!(window.GWT && window.GWT.app && window.GWT.data &&
         Object.keys(window.GWT.data.samples || {}).length > 0));
    // The bundles the first screen does without are fetched on demand, so
    // the precache is the only place they can come from with no network.
    const bundlesOffline = await page.evaluate(async () => {
      const names = Object.keys(window.GWT.bundles);
      const failed = [];
      for (const name of names) {
        await window.GWT.load(name).catch((e) => failed.push(name + ': ' + e.message));
      }
      return { names, failed, geo: !!window.GWT.data.geo,
        sample: !!window.GWT.data.samples.rokel.files.ves.b64 };
    });
    await page.context().setOffline(false);
    check('offline: the app boots with the network switched off', bootedOffline);
    check('offline: every bundle loaded on demand comes from the precache',
      bundlesOffline.failed.length === 0 && bundlesOffline.names.length >= 6 &&
      bundlesOffline.geo && bundlesOffline.sample, JSON.stringify(bundlesOffline));
  } else {
    check('offline: the app boots with the network switched off', false,
      JSON.stringify(offlineLoad));
  }

  // The VES co-pilot (PLAN.md step 2.2), played back with the Rokel readings
  // through the page itself: the form, the peg's checks, the curve, the
  // preview inversion, a reload, and the workbook it writes, read back by
  // the browser's own parser. tests/test_ves_copilot.py reads the same kind
  // of workbook with the Python one.
  await page.context().grantPermissions(['geolocation'], { origin: base });
  await page.context().setGeolocation({ latitude: 8.6, longitude: -12.9, accuracy: 5 });
  await page.evaluate(() => window.GWT.app.goto('vescopilot'));
  await page.waitForFunction(() => !!window.GWT.vesCopilot &&
    !!document.querySelector('#page-host [data-vc="target"]'));
  /* the page's controls, driven as a hand would: a value typed, the change
   * it fires on leaving the box, then the button; put back after a reload */
  const driveCopilot = () => page.evaluate(() => {
    window.__vc = {
      set(name, value) {
        const input = document.querySelector('#page-host [data-vc="' + name + '"]');
        input.value = value === null || value === undefined ? '' : String(value);
        input.dispatchEvent(new Event('change'));
      },
      press(label) {
        const btn = Array.from(document.querySelectorAll('#page-host button'))
          .find((b) => b.textContent.trim() === label);
        if (!btn) throw new Error('no button ' + label);
        btn.click();
      },
      has(label) {
        return Array.from(document.querySelectorAll('#page-host button'))
          .some((b) => b.textContent.trim() === label);
      },
      peg() {
        const node = document.querySelector('#page-host [data-vc="peg"]');
        return node ? Array.from(node.querySelectorAll('[data-check]'))
          .map((li) => [li.getAttribute('data-check'), li.textContent]) : null;
      },
      fresh() {
        window.GWT.vesCopilot.cancelPreview('idle');
        window.GWT.app.store.set('vesCopilot', window.GWT.vesCopilot.blankSession());
        return window.GWT.app.render();
      },
      /* one reading through the form; the checks the peg then shows */
      read(r) {
        this.set('ab2', r.ab2); this.set('mn', r.mn);
        this.set('v', r.v); this.set('i', r.i); this.set('rho', r.rho);
        this.press(this.has('Replace the reading') ? 'Replace the reading' : 'Add the reading');
        return this.peg();
      },
    };
  });
  await driveCopilot();
  await page.evaluate(() => window.__vc.fresh());

  // Before the survey: the target depth sets the line by the engines' one
  // depth-of-investigation rule, 0.5 of the largest AB/2.
  const proposal = await page.evaluate(() => {
    window.__vc.set('target', 50);
    window.__vc.press('Propose the spacings');
    const V = window.GWT.vesCopilot;
    const plan = window.GWT.app.store.get('vesCopilot').plan;
    const depths = [10, 20, 35, 60, 120].map((d) => {
      const p = V.propose(d);
      return { d, max: p.max_ab2, doi: p.investigation_m, line: p.line_m,
        mnChanges: p.steps.filter((s, i) => i && s.ab2 === p.steps[i - 1].ab2).length,
        fifth: p.steps.every((s) => s.mn * 5 <= 2 * s.ab2) };
    });
    return { plan, depths,
      text: document.querySelector('#page-host [data-vc="proposal"]')?.textContent || '',
      next: document.querySelector('#page-host [data-vc="next"]')?.textContent || '' };
  });
  check('ves co-pilot: a 50 m target proposes AB/2 to 100 m, resolving 50 m',
    proposal.plan.length > 0 && proposal.plan[proposal.plan.length - 1].ab2 === 100 &&
    proposal.text.includes('AB/2 = 100 m') && proposal.text.includes('200 m of straight') &&
    proposal.next.startsWith('Next: AB/2 1 m, MN 0.4 m'), JSON.stringify(proposal));
  check('ves co-pilot: each target gets the shortest series that reaches it',
    JSON.stringify(proposal.depths.map((p) => [p.d, p.max, p.doi])) ===
      JSON.stringify([[10, 20, 10], [20, 40, 20], [35, 80, 40], [60, 120, 60],
        [120, 250, 125]]) &&
    proposal.depths.every((p) => p.fifth && p.mnChanges >= 1),
    JSON.stringify(proposal.depths));

  // At the peg, each of the four checks, one at a time, against the plan the
  // 50 m target proposed.
  const four = await page.evaluate(() => {
    const vc = window.__vc, C = window.GWT.core;
    const out = {};
    // a potential under the instrument's setting (1 mV by default); the
    // resistivity is K V / I with the engine's own Schlumberger K
    out.low = vc.read({ ab2: 1, mn: 0.4, v: 0.5, i: 100 });
    const first = window.GWT.app.store.get('vesCopilot').readings[0];
    out.rho = [first.rho, C.apparentResistivity('schlumberger', 0.5 / 100, { ab2: 1, mn: 0.4 })];
    out.minSaid = window.GWT.vesCopilot.DEFAULT_MIN_POTENTIAL_MV;
    // the same spacing read again: a repeat, not a second reading
    out.repeat = vc.read({ ab2: 1, mn: 0.4, v: 40, i: 100 });
    // 1.5 m skipped on the way to 2 m
    out.skip = vc.read({ ab2: 2, mn: 0.4, rho: 3.2 });
    // 2 m to 3 m at slope ln(9.6/3.2)/ln(1.5) = 2.71: no layered earth does that
    out.steep = vc.read({ ab2: 3, mn: 0.4, rho: 9.6 });
    // 3 m to 4 m at slope 0.9: steep, but a layered earth can
    const at4 = 9.6 * Math.pow(4 / 3, 0.9);
    out.gentle = vc.read({ ab2: 4, mn: 0.4, rho: at4 });
    // the MN change at 4 m: 30 percent apart, over the engine's 20
    out.overlap = vc.read({ ab2: 4, mn: 1, rho: at4 * 1.3 });
    out.ratio = C.OVERLAP_DISCREPANCY_RATIO;
    // re-measured in its place, now within 5 percent
    vc.press('Re-measure this reading');
    out.remeasured = vc.read({ ab2: 4, mn: 1, rho: at4 * 1.05 });
    out.count = window.GWT.app.store.get('vesCopilot').readings.length;
    out.curveMarks = document.querySelectorAll('#page-host .vc-curve svg [data-reading]').length;
    return out;
  });
  const codes = (peg) => (peg || []).map((c) => c[0]).join(',');
  check('ves co-pilot: a potential under the instrument setting says re-measure',
    codes(four.low) === 'low_potential' && four.low[0][1].startsWith('Re-measure now') &&
    four.minSaid === 1 && Math.abs(four.rho[0] - four.rho[1]) < 1e-3,
    JSON.stringify([four.low, four.rho]));
  check('ves co-pilot: a spacing read twice is called a repeat',
    codes(four.repeat) === 'repeated', JSON.stringify(four.repeat));
  check('ves co-pilot: a skipped spacing is named',
    codes(four.skip) === 'skipped' && four.skip[0][1].includes('AB/2 1.5 m'),
    JSON.stringify(four.skip));
  check('ves co-pilot: a rise steeper than 45 degrees says re-measure, a slope of 0.9 does not',
    codes(four.steep) === 'steep_rise' && four.steep[0][1].includes('slope of 2.71') &&
    codes(four.gentle) === '', JSON.stringify([four.steep, four.gentle]));
  check('ves co-pilot: an overlap 30 percent apart says re-measure, by the engine\'s 20',
    codes(four.overlap) === 'overlap_discrepancy' && four.ratio === 1.2 &&
    four.overlap[0][1].includes('(ratio 1.30)'), JSON.stringify(four.overlap));
  check('ves co-pilot: a re-measured reading takes the place of the one it repeats',
    codes(four.remeasured) === '' && four.count === 6 && four.curveMarks === 6,
    JSON.stringify(four));

  // PLAN.md step 2.2's done-when: played back reading by reading, each Rokel
  // overlap that disagrees by 45 to 98 percent says "re-measure now" at the
  // peg, and the overlaps that agree say nothing.
  const rokel = await page.evaluate(async () => {
    await window.GWT.load('samples');
    const S = window.GWT.support, C = window.GWT.core, vc = window.__vc;
    const sheets = await S.readXlsx(S.base64ToBytes(window.GWT.data.samples.rokel.files.ves.b64));
    const soundings = C.readVesSheets(sheets, 'rokel_ves.xlsx');
    const out = { raised: [], quiet: [], played: [], atEight: [] };
    for (const s of soundings) {
      await vc.fresh();
      const box = document.querySelector('#page-host textarea');
      box.value = s.ab2.map((a, i) => a + ' ' + s.mn[i]).join('\n');
      vc.press('Use this plan');
      vc.set('sounding-id', s.sounding_id);
      vc.set('instrument', 'Syscal Junior');
      for (let i = 0; i < s.ab2.length; i++) {
        const peg = vc.read({ ab2: s.ab2[i], mn: s.mn[i], rho: s.rho_app[i] });
        const said = peg.filter((c) => c[0] === 'overlap_discrepancy');
        if (said.length) {
          out.raised.push([s.sounding_id, s.ab2[i],
            said[0][1].startsWith('Re-measure now'), said[0][1].match(/ratio [\d.]+/)[0]]);
        } else if (s.ab2.indexOf(s.ab2[i]) !== i) {
          out.quiet.push([s.sounding_id, s.ab2[i]]);
        }
        /* before the eighth reading nothing is fitted; at it, a fit waits */
        if (i === 6 || i === 7) out.atEight.push(window.GWT.vesCopilot.preview().status);
      }
      out.played.push({ id: s.sounding_id, ab2: s.ab2, mn: s.mn, rho: s.rho_app });
    }
    return out;
  });
  check('ves co-pilot: every Rokel overlap off by 45 to 98 percent said re-measure now at the peg',
    JSON.stringify(rokel.raised) === JSON.stringify([
      ['A (1)', 10, true, 'ratio 1.45'], ['A (1)', 40, true, 'ratio 1.98'],
      ['B (2)', 10, true, 'ratio 1.47'], ['B (2)', 40, true, 'ratio 1.54'],
      ['B (2)', 70, true, 'ratio 1.64']]) &&
    JSON.stringify(rokel.quiet) === JSON.stringify([['A (1)', 3], ['A (1)', 70], ['B (2)', 3]]),
    JSON.stringify(rokel));

  // The preview: started by the eighth reading, in the worker, and it can be
  // stopped. The page now holds sounding B (2), all eighteen readings.
  const previewRun = await page.evaluate(async () => {
    const V = window.GWT.vesCopilot;
    const until = async (fn, ms) => {
      const end = Date.now() + ms;
      while (!fn()) {
        if (Date.now() > end) return false;
        await new Promise((r) => setTimeout(r, 20));
      }
      return true;
    };
    const out = {};
    out.running = await until(() => V.preview().status === 'running', 10000);
    window.__vc.press('Stop the preview');
    out.stopped = V.preview().status;
    out.stoppedText = document.querySelector('#page-host [data-vc="preview-status"]')?.textContent;
    out.cancelled = window.GWT.engine.history()
      .filter((h) => h.type === 'previewInvert' && h.outcome === 'cancelled').length;
    window.__vc.press('Run the preview now');
    out.done = await until(() => V.preview().status === 'done', 60000);
    const node = document.querySelector('#page-host [data-vc="preview"]');
    out.text = node ? node.textContent : '';
    out.said = document.querySelector('#page-host .vc-preview')?.textContent || '';
    out.modes = window.GWT.engine.history()
      .filter((h) => h.type === 'previewInvert' && h.outcome === 'done').map((h) => h.mode);
    out.modelLine = !!document.querySelector(
      '#page-host .vc-curve svg path[stroke-dasharray="6 4"]');
    return out;
  });
  check('ves co-pilot: the preview waits for eight readings, then starts',
    JSON.stringify(rokel.atEight) === JSON.stringify(['idle', 'waiting', 'idle', 'waiting']),
    JSON.stringify(rokel.atEight));
  check('ves co-pilot: the preview inversion can be stopped',
    previewRun.running && previewRun.stopped === 'stopped' && previewRun.cancelled >= 1 &&
    /Preview stopped/.test(previewRun.stoppedText || ''), JSON.stringify(previewRun));
  check('ves co-pilot: the preview runs in the worker and says it is a preview',
    previewRun.done && previewRun.modes.length >= 1 &&
    previewRun.modes.every((m) => m === 'worker') && previewRun.text.startsWith('Preview:') &&
    previewRun.said.includes('A preview, not the survey\'s result') && previewRun.modelLine,
    JSON.stringify(previewRun));

  // The position, with permission, then a reload: the session is in
  // IndexedDB with the rest of the project and comes back as it was.
  const beforeReload = await page.evaluate(async () => {
    window.__vc.press('Take the GPS position');
    const end = Date.now() + 10000;
    while (!window.GWT.app.store.get('vesCopilot').gps && Date.now() < end) {
      await new Promise((r) => setTimeout(r, 20));
    }
    /* the autosave, as it goes in 400 ms after a change */
    await new Promise((r) => setTimeout(r, 1000));
    return window.GWT.app.store.get('vesCopilot');
  });
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app && window.GWT.vesCopilot &&
    !!document.querySelector('#page-host [data-vc="target"]'), null, { timeout: 30000 });
  await driveCopilot();
  const afterReload = await page.evaluate(() => ({
    session: window.GWT.app.store.get('vesCopilot'),
    rows: document.querySelectorAll('#page-host table.data tbody tr').length,
    status: window.GWT.vesCopilot.preview().status,
  }));
  check('ves co-pilot: the session survives a reload',
    JSON.stringify(afterReload.session) === JSON.stringify(beforeReload) &&
    beforeReload.readings.length === 18 && !!beforeReload.gps &&
    beforeReload.gps.lat === 8.6 && afterReload.rows === 18 &&
    ['waiting', 'running'].includes(afterReload.status),
    JSON.stringify({ before: beforeReload && beforeReload.readings.length,
      gps: beforeReload && beforeReload.gps, after: afterReload.rows,
      status: afterReload.status }));

  // Leaving the page stops a preview that is waiting or running, so the
  // engine's one queue is free for the Geophysics page; coming back starts
  // it again. Opening a sample project keeps the sounding: readings taken at
  // the peg cannot be taken again (FIELD_SESSIONS in gwt-app.js).
  const leaving = await page.evaluate(async () => {
    const V = window.GWT.vesCopilot, app = window.GWT.app;
    const until = async (fn, ms) => {
      const end = Date.now() + ms;
      while (!fn()) {
        if (Date.now() > end) return false;
        await new Promise((r) => setTimeout(r, 20));
      }
      return true;
    };
    const fits = () => window.GWT.engine.history()
      .filter((h) => h.type === 'previewInvert').length;
    const out = { before: V.preview().status };
    await app.goto('design');
    out.left = V.preview().status;
    const settled = fits();
    /* longer than the debounce: a fit left waiting would have started */
    await new Promise((r) => setTimeout(r, 2000));
    out.stillStopped = V.preview().status === 'stopped' && fits() === settled;
    await app.goto('vescopilot');
    out.back = V.preview().status;
    await app.loadSample('rokel');
    out.kept = (app.store.get('vesCopilot').readings || []).length;
    out.site = app.store.get('site').community || '';
    /* the readings table's rows, each with its own Delete */
    out.rows = Array.from(document.querySelectorAll('#page-host table.data tbody tr'))
      .filter((tr) => Array.from(tr.querySelectorAll('button'))
        .some((btn) => btn.textContent.trim() === 'Delete')).length;
    out.refit = await until(() => V.preview().status === 'done', 60000);
    return out;
  });
  await driveCopilot();
  check('ves co-pilot: leaving the page stops the preview, coming back starts it again',
    ['waiting', 'running'].includes(leaving.before) && leaving.left === 'stopped' &&
    leaving.stillStopped && ['waiting', 'running'].includes(leaving.back) && leaving.refit,
    JSON.stringify(leaving));
  check('ves co-pilot: opening a sample project keeps the sounding being taken',
    leaving.kept === 18 && leaving.rows === 18 && leaving.site !== '', JSON.stringify(leaving));

  // With no worker the fit would hold the page after every reading, so it
  // waits to be asked; with the worker back it starts by itself again.
  const onPage = await page.evaluate(async () => {
    const V = window.GWT.vesCopilot, app = window.GWT.app, E = window.GWT.engine;
    E.forcePage(true);
    try {
      await app.goto('design');
      /* the preview of these readings is done; forget it, as a new reading would */
      V.cancelPreview('idle');
      await app.goto('vescopilot');
      return { status: V.preview().status, fits: E.history().length,
        text: document.querySelector('#page-host [data-vc="preview-status"]')?.textContent || '',
        button: Array.from(document.querySelectorAll('#page-host button'))
          .some((b) => b.textContent.trim() === 'Run the preview now') };
    } finally {
      E.forcePage(false);
      await app.goto('design');
      await app.goto('vescopilot');
    }
  });
  await driveCopilot();
  check('ves co-pilot: with no worker the preview waits to be asked',
    onPage.status === 'manual' && onPage.button && /no background worker/.test(onPage.text),
    JSON.stringify(onPage));

  // The workbook, from the download button, read by the browser's parser.
  const written = await page.evaluate(async (played) => {
    const S = window.GWT.support, C = window.GWT.core;
    window.GWT.vesCopilot.cancelPreview('stopped');
    const kept = S.download;
    let saved = null;
    S.download = (name, blob) => { saved = { name, blob }; };
    try {
      window.__vc.press('Download the workbook');
      const end = Date.now() + 10000;
      while (!saved && Date.now() < end) await new Promise((r) => setTimeout(r, 20));
    } finally {
      S.download = kept;
    }
    const bytes = new Uint8Array(await saved.blob.arrayBuffer());
    const skipped = [];
    const soundings = C.readVesSheets(await S.readXlsx(bytes), saved.name, skipped);
    const s = soundings[0];
    const want = played[played.length - 1];
    const utm = C.geographicToUtm(8.6, -12.9);
    return { name: saved.name, n: soundings.length, skipped: skipped.length,
      id: s.sounding_id, same: JSON.stringify([s.ab2, s.mn, s.rho_app]) ===
        JSON.stringify([want.ab2, want.mn, want.rho]),
      easting: s.site.easting, wantEasting: Math.round(utm.easting * 10) / 10,
      zone: s.site.utm_zone, instrument: s.instrument,
      codes: s.flags.map((f) => f.code) };
  }, rokel.played);
  check('ves co-pilot: the workbook reads back through the browser\'s parser',
    written.n === 1 && written.skipped === 0 && written.id === 'B (2)' && written.same &&
    written.easting === written.wantEasting && written.zone === 28 &&
    written.instrument === 'Syscal Junior' &&
    written.codes.includes('segment_overlap_discrepancy') &&
    written.name === 'b_2_ves_copilot.xlsx', JSON.stringify(written));
  await page.evaluate(() => window.__vc.fresh());
  await page.context().clearPermissions();

  // A dense survey's drill-target map. Every label was written to the right
  // of its peg, so twelve pegs 60 m apart - or sixteen 50 m apart in two
  // rows - printed their labels through each other and the map named none
  // of them. Each label is now placed where it covers nothing.
  const dense = await page.evaluate(async () => {
    await window.GWT.load('charts');
    const C = window.GWT.core, charts = window.GWT.charts;
    function survey(nx, ny, spacing) {
      const points = [];
      for (let j = 0; j < ny; j++) {
        for (let i = 0; i < nx; i++) {
          const k = j * nx + i;
          const value = 80 - 4 * ((k * 7) % (nx * ny));
          points.push({ label: 'VES ' + (k + 1), easting: 710000 + spacing * i,
            northing: 950000 + spacing * j, value: value,
            kind: value >= 55 ? 'Good' : 'Moderate' });
        }
      }
      points.slice().sort((a, b) => b.value - a.value)
        .forEach((p, r) => { p.rank = r + 1; });
      points.forEach((p) => {
        p.recommended = p.rank === 1;
        p.text = C.suitabilityLabel(p, p.recommended, false);
        p.compact_text = C.suitabilityLabel(p, p.recommended, true);
      });
      return points;
    }
    function layout(points) {
      const svg = charts.suitabilityMap({ title: 'Drill-target suitability',
        cmap: 'RdYlGn', points: points, grid: null, surface: false, note: '',
        tie_note: '', levels: C.linspace(0, 100, 11), extent: C.mapExtent(points),
        zone: 28, legend: [{ label: 'recommended drill target', kind: 'star', value: 80 },
          { label: 'surveyed point', kind: 'circle', value: 40 }] }, { width: 680 });
      document.body.appendChild(svg);
      const boxes = {};
      svg.querySelectorAll('text[data-peg]').forEach((t) => {
        const b = t.getBBox(), key = t.getAttribute('data-peg');
        const o = boxes[key] || { x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9, text: [] };
        o.x0 = Math.min(o.x0, b.x); o.y0 = Math.min(o.y0, b.y);
        o.x1 = Math.max(o.x1, b.x + b.width); o.y1 = Math.max(o.y1, b.y + b.height);
        o.text.push(t.textContent);
        boxes[key] = o;
      });
      const leaders = svg.querySelectorAll('line[data-leader]').length;
      svg.remove();
      const list = Object.keys(boxes).map((k) => Object.assign({ key: k }, boxes[k]));
      const clashes = [];
      list.forEach((a, i) => list.slice(i + 1).forEach((b) => {
        if (Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0) > 0.5 &&
            Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0) > 0.5) clashes.push([a.key, b.key]);
      }));
      return { labels: list.length, clashes: clashes, leaders: leaders,
        full: list.every((b) => b.text.some((line) => line.endsWith('suitability'))) };
    }
    return { grid: layout(survey(4, 3, 60)), strip: layout(survey(8, 2, 50)) };
  });
  check('a dense survey map writes every label clear of every other',
    dense.grid.labels === 12 && dense.grid.clashes.length === 0 &&
    dense.strip.labels === 16 && dense.strip.clashes.length === 0,
    JSON.stringify(dense));
  check('a dense survey map ties a moved label to its peg, and keeps it in full',
    dense.grid.leaders > 0 && dense.grid.full, JSON.stringify(dense.grid));

  check('no console errors', consoleErrors.length === 0,
    consoleErrors.slice(0, 10).join('\n     '));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

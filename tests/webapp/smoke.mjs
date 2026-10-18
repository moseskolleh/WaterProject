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

  // Part of the terrain work is in the Python app alone, and neither app's
  // reports carry the terrain yet: the Topography and terrain card on Site &
  // maps says both in the catalogue's words, once, above its drop zone, and
  // About says them too, rather than leaving "every page" to imply otherwise.
  const elevationNotice = await page.evaluate(() => {
    const app = window.GWT.app, C = window.GWT.core;
    const notices = [C.phrase('terrain.python_only'), C.phrase('terrain.not_in_reports')];
    const saying = (selector) => notices.map((notice) => Array.from(
      document.querySelectorAll('#page-host ' + selector)).filter((p) => p.textContent === notice).length);
    app.goto('site');
    const callout = document.querySelector('[data-item="terrain"] .callout.callout-info');
    const zone = document.querySelector('[data-item="terrain"] .upload-zone');
    const site = { card: saying('[data-item="terrain"] .callout.callout-info p'), page: saying('p'),
      aboveDrop: !!callout && !!zone &&
        !!(callout.compareDocumentPosition(zone) & Node.DOCUMENT_POSITION_FOLLOWING) };
    app.goto('about');
    return { site, about: saying('p') };
  });
  check('site and about: the terrain card, above its drop zone, and About say what of the terrain is in the ' +
    'Python app alone and not in reports',
    elevationNotice.site.card.join() === '1,1' && elevationNotice.site.page.join() === '1,1' &&
    elevationNotice.site.aboveDrop && elevationNotice.about.every((n) => n > 0), JSON.stringify(elevationNotice));

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
    // the callout the button sits in: the page has others, the cost
    // distribution's among them
    const offered = button.closest('.callout').textContent;
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

  // A sheet copied without renumbering gives two points one id. The pages
  // looked the odds up by id, so both rows showed the last point's and the
  // Costing page offered the first point carrying the leader's id; they are
  // paired by position. Here the second Rokel point takes the first's id and
  // is listed first, so the leader is the one listed second.
  const sharedId = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core;
    const kept = { interps: app.derived.interpretations, invs: app.derived.inversions,
      soundings: app.derived.soundings };
    const renamed = Object.assign({}, kept.interps[1],
      { sounding_id: kept.interps[0].sounding_id });
    try {
      app.derived.interpretations = [renamed, kept.interps[0]];
      app.derived.inversions = [kept.invs[1], kept.invs[0]];
      app.derived.soundings = [kept.soundings[1], kept.soundings[0]];
      const odds = app.surveyOdds();
      const weighted = app.derived.interpretations.map((i) => {
        const s = C.assessSiting([i], app.config().ves)[0];
        return s.suitability * s.confidence;
      });
      const lead = weighted[1] > weighted[0] ? 1 : 0;
      await app.goto('ves');
      const host = document.querySelector('#page-host');
      const table = Array.from(host.querySelectorAll('table')).find((t) =>
        Array.from(t.querySelectorAll('th')).some((th) =>
          th.textContent === 'Chance of a working borehole'));
      const column = Array.from(table.querySelectorAll('th'))
        .findIndex((th) => th.textContent === 'Chance of a working borehole');
      const cells = Array.from(table.querySelectorAll('tbody tr'))
        .map((tr) => tr.children[column].textContent);
      const points = Array.from(host.querySelectorAll('.odds-point')).map((p) => p.textContent);
      await app.goto('costing');
      const offered = Array.from(document.querySelectorAll('#page-host .callout'))
        .find((c) => /Use \d+ percent/.test(c.textContent)).textContent;
      return { lead, cells, shorts: odds.map((o) => C.oddsShort(o)),
        words: odds.map((o) => C.oddsPointText(o).join(' ')), points, offered,
        sentence: C.programmeOffer(odds[lead]) };
    } finally {
      app.derived.interpretations = kept.interps;
      app.derived.inversions = kept.invs;
      app.derived.soundings = kept.soundings;
      await app.goto('ves');
    }
  });
  check('odds: two points with one id each show their own odds, in rank order',
    sharedId.lead === 1 && sharedId.shorts[0] !== sharedId.shorts[1] &&
    JSON.stringify(sharedId.cells) ===
      JSON.stringify([sharedId.shorts[1], sharedId.shorts[0]]) &&
    sharedId.words.every((w) => sharedId.points.some((p) => p.includes(w))),
    JSON.stringify(sharedId).slice(0, 800));
  check('odds: the Costing page offers the leader\'s odds, not the first with its id',
    sharedId.offered.includes(sharedId.sentence), JSON.stringify(sharedId).slice(0, 800));

  // The value of one more measurement (PLAN.md step 3.5): beside the odds
  // and the costs on the Costing page, under the odds on the VES page, and
  // in the cost and geophysical reports, priced from the same distribution
  // at the survey's first-ranked point against the other point.
  const valuePage = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core, docx = window.GWT.docx;
    await app.goto('costing');
    const spreads = app.costSpreads();
    if (!spreads) return { spreads: null };
    const values = app.surveyMeasurements(spreads.single);
    const cards = Array.from(document.querySelectorAll('#page-host .card'));
    const card = cards.find((c) => (c.querySelector('h2, h3') || {}).textContent ===
      C.phrase('measurement.heading'));
    const words = values.map((v) => C.measurementText(v).join(' '));
    const costing = card ? card.textContent : '';
    const context = { style: app.config().style, site: app.store.get('site'),
      estimate: app.derived.estimate, figures: [], distribution: spreads.single,
      measurements: values };
    // read once the reader of a document's text is set up, further down
    window.__valueReport = { bytes: await (await docx.costingReport(context)).build(),
      words, heading: '4.2 ' + C.phrase('measurement.heading') };
    await app.goto('ves');
    const ves = document.querySelector('#page-host').textContent;
    const first = C.assessSiting(app.derived.interpretations, app.config().ves)[0];
    return {
      card: !!card, n: values.length, first: first.sounding_id,
      ids: values.map((v) => v.sounding_id), alternatives: values.map((v) => v.alternative_id),
      summaries: values.map((v) => C.measurementSummary(v)),
      costing: values.every((v) => costing.includes(C.measurementSummary(v))) &&
        costing.includes(C.measurementBasis(values[0])) &&
        costing.includes(C.measurementReadingsCaption(values[0])),
      ves: values.every((v) => ves.includes(C.measurementSummary(v))),
    };
  });
  check('measurement: the Costing page prices a sounding and a profiling line at the ' +
    'first-ranked point', valuePage.card && valuePage.n === 2 &&
    valuePage.ids.every((id) => id === valuePage.first) &&
    valuePage.alternatives.every((id) => id !== null && id !== valuePage.first),
  JSON.stringify(valuePage).slice(0, 600));
  check('measurement: the Costing page prints the engine\'s sentences and tables',
    valuePage.costing, JSON.stringify(valuePage.summaries));
  check('measurement: the VES page prints it under the odds once the cost is estimated',
    valuePage.ves, JSON.stringify(valuePage.summaries));

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
          // the yield and the intake as decision numbers, in the one form
          // with their bands (PLAN.md step 3.6)
          ['the decision numbers', [C.yieldDecision(d.analysis), C.pumpDecision(d.analysis)]
            .every((n) => n && n.band !== null && has(C.decisionText(n)))],
          // and the summary gives the yield's value alone, as the Python
          // report does, not the assumption envelope as a second band
          ['the yield in the summary without the envelope',
            has('The recommended safe yield is ' + C.fmtNum(
              d.analysis.yield_recommendation.safe_yield_m3_per_h) + ' m3/h') &&
            !text.includes('The recommended safe yield is ' +
              C.yieldRangeText(d.analysis.yield_recommendation))],
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
          // built with no distribution, the cost says why it has no band
          ['the cost as a decision number with no band',
            has(C.decisionText(C.costDecision(null, d.estimate))) &&
            text.includes('no band: ' + C.phrase('decision.cost_not_sampled'))],
        ];
        wants.supervision = [
          ['a checklist item', has(C.loadChecklists()[0].text)],
          ['the section name', has(C.loadChecklists()[0].section)],
        ];
        wants.handover = [
          ['community', has(site.community)],
          ['total depth', has(C.fmtNum(d.design.total_depth_m))],
          ['the water quality verdict', has(d.assessment.verdict)],
          ['the decision numbers, the intake where the design sets it',
            has(C.decisionText(C.yieldDecision(d.analysis))) &&
            has(C.decisionText(C.pumpDecision(d.analysis, d.design.pump_intake_m || null,
              'design')))],
          ['the yield in the summary without the envelope',
            has('rated at a safe yield of ' + C.fmtNum(
              d.analysis.yield_recommendation.safe_yield_m3_per_h) + ' m3/h') &&
            !text.includes('rated at a safe yield of ' +
              C.yieldRangeText(d.analysis.yield_recommendation))],
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

  // The cost as a distribution (PLAN.md step 3.4): the Costing page shows
  // the planning figure beside the bill of quantities, says which is the
  // contract document, draws the curve, and does the same for a programme;
  // the cost report prints it, from the same sampled distribution.
  const spreadPage = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core, docx = window.GWT.docx;
    const before = app.store.get('costing.programme_n');
    await app.goto('costing');
    // typed into the page, as a user sets it: the estimate is rebuilt
    const setWells = async (n) => {
      const input = Array.from(document.querySelectorAll('#page-host label.field'))
        .find((f) => f.querySelector('.field-label').textContent ===
          'Successful boreholes required').querySelector('input');
      input.value = String(n);
      input.dispatchEvent(new Event('change'));
      await new Promise((r) => setTimeout(r, 50));
    };
    await setWells(4);
    try {
      const spreads = app.costSpreads();
      const cards = Array.from(document.querySelectorAll('#page-host .card'));
      const card = cards.find((c) => (c.querySelector('h2, h3') || {}).textContent ===
        C.phrase('cost_range.heading'));
      const host = document.querySelector('#page-host').textContent;
      const context = { style: app.config().style, site: app.store.get('site'),
        estimate: app.derived.estimate, programme: app.derived.programme, figures: [],
        distribution: spreads.single, programmeDistribution: spreads.programme };
      const text = await window.__docText(await (await docx.costingReport(context)).build());
      return {
        card: !!card, svg: card ? card.querySelectorAll('svg').length : 0,
        first: card ? card.querySelector('.callout').textContent : '',
        which: C.phrase('cost_range.which_is_which'),
        single: C.costRangeText(spreads.single).every((t) => host.includes(t)),
        programme: !!spreads.programme &&
          C.programmeRangeText(spreads.programme).every((t) => host.includes(t)),
        again: app.costSpreads() === spreads,
        boq: spreads.single.boq_usd === app.derived.estimate.price_with_vat_usd,
        report: C.costRangeText(spreads.single).every((t) => text.includes(t)) &&
          text.includes(C.decisionText(C.costDecision(spreads.single,
            app.derived.estimate))) &&
          C.programmeRangeText(spreads.programme).every((t) => text.includes(t)) &&
          text.includes('4.1 ' + C.phrase('cost_range.heading')),
      };
    } finally {
      await setWells(before);
    }
  });
  check('cost range: the Costing page says which figure is the contract document',
    spreadPage.card && spreadPage.first === spreadPage.which && spreadPage.svg === 1,
    JSON.stringify(spreadPage).slice(0, 600));
  check('cost range: the page prints the engine\'s sentences for a borehole and a programme',
    spreadPage.single && spreadPage.programme && spreadPage.boq,
    JSON.stringify(spreadPage).slice(0, 600));
  check('cost range: a page drawn again does not sample again', spreadPage.again,
    JSON.stringify(spreadPage).slice(0, 600));
  check('cost range: the cost report prints the same distribution', spreadPage.report,
    JSON.stringify(spreadPage).slice(0, 600));
  // the cost report built beside the Rokel survey, further up, prints what
  // one more measurement is worth in its section 4.2 (PLAN.md step 3.5)
  const valueReport = await page.evaluate(async () => {
    const kept = window.__valueReport;
    if (!kept) return { built: false };
    const text = await window.__docText(kept.bytes);
    return { built: true, heading: text.includes(kept.heading),
      words: kept.words.every((w) => text.includes(w)) };
  });
  check('measurement: the cost report prints it in section 4.2',
    valueReport.built && valueReport.heading && valueReport.words, JSON.stringify(valueReport));

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

  // the ledger of predictions and outcomes (PLAN.md step 5.1): saved at the
  // top of the project file, where the Python app writes it, under schema 2;
  // opened again into the session; empty from a file of schema 1; and a
  // file of a later schema says so as it opens
  const ledgerTrip = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core, S = window.GWT.support;
    const interp = { sounding_id: 'VES 1', depth_to_basement_m: 28.4, basement_not_resolved: false,
      investigation_depth_m: 60, water_zones: [[8, 20]], aquifer_thickness_m: 12,
      max_drilling_depth_m: 35, drilling_depth_capped: false, fit_error_percent: 3.2,
      site_easting: 708958, site_northing: 926355 };
    const survey = C.surveyPredictions([interp], null, null,
      { community: 'Rokel', district: 'Port Loko', utm_zone: 28 });
    const recorded = C.recordPredictions(C.emptyLedger(), survey, '2026-10-01', false, '0.3.0').ledger;
    app.store.set('ledger', recorded);
    const payload = JSON.parse(JSON.stringify(app.projectPayload()));
    const toasts = [];
    const toast = S.toast;
    S.toast = (message, tone) => { toasts.push([message, tone]); };
    try {
      app.store.set('ledger', C.emptyLedger());
      await app.loadProject(JSON.stringify(payload));
      const back = app.store.get('ledger');
      await app.loadProject(JSON.stringify({ format: 'groundwater-toolkit-project', version: 1,
        state: Object.assign({}, payload.state, { ledger: recorded }) }));
      const old = app.store.get('ledger');
      await app.loadProject(JSON.stringify(Object.assign({}, payload, { schema: C.PROJECT_SCHEMA + 1 })));
      const same = (a) => JSON.stringify(C.cleanLedger(a)) === JSON.stringify(C.cleanLedger(recorded));
      return { schema: payload.schema, version: payload.version, top: same(payload.ledger),
        inState: 'ledger' in payload.state, back: same(back), entries: recorded.entries.length,
        old: old, later: toasts[toasts.length - 1] };
    } finally {
      S.toast = toast;
    }
  });
  check('ledger: the project file carries it at its top level, at schema 2, and opens with it',
    ledgerTrip.schema === 2 && ledgerTrip.version === undefined && !ledgerTrip.inState &&
    ledgerTrip.top && ledgerTrip.back && ledgerTrip.entries === 1, JSON.stringify(ledgerTrip).slice(0, 600));
  check('ledger: a file of schema 1 opens with an empty one, and a later schema says so',
    ledgerTrip.old.entries.length === 0 && ledgerTrip.later[1] === 'warn' &&
    /format 3; this app reads format 2/.test(ledgerTrip.later[0]), JSON.stringify(ledgerTrip.later));
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

  // The four terrain figures of PLAN.md step 4.1, drawn before the card that
  // will show them exists. An analysis is made here, in the page, on a
  // generated window with a coast, a missing tile taken as sea, a gap, a
  // flat shelf and a closed hollow, and each figure is drawn from what the
  // worker will hand the page: C.terrainDisplayLayers, the parts and the
  // captions. Each has to paint the layers it names and the furniture of a
  // map, carry the credit and the caveat inside the SVG, where a downloaded
  // copy keeps them, and rasterise through toPng to a PNG whose maps are
  // painted rather than left blank: the layers are embedded as PNG images,
  // and an image the rasteriser dropped would leave only the furniture.
  const terrain = await page.evaluate(async () => {
    await window.GWT.load('charts');
    const C = window.GWT.core, charts = window.GWT.charts;
    const rows = 90, cols = 90, step = 1 / 3600, n = rows * cols;
    const lons = new Float64Array(cols), lats = new Float64Array(rows);
    for (let c = 0; c < cols; c++) lons[c] = -12.0 + c * step;
    for (let r = 0; r < rows; r++) lats[r] = 8.4 + r * step;
    /* a hill with spurs, falling west to the sea */
    const z = new Float64Array(n), assumedSea = new Uint8Array(n);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const dr = r - 45, dc = c - 60, d = Math.sqrt(dr * dr + dc * dc);
        z[r * cols + c] = 55 * Math.exp(-(d * d) / 800) + 0.45 * (c - 26) + 2 * Math.sin(r / 7) +
          3 * Math.cos(6 * Math.atan2(dr, dc)) * Math.min(d / 20, 1);
      }
    }
    const block = (r0, r1, c0, c1, fn) => {
      for (let r = r0; r < r1; r++) for (let c = c0; c < c1; c++) fn(r * cols + c);
    };
    block(0, 25, 0, 20, (k) => { assumedSea[k] = 1; z[k] = NaN; });     // a missing tile taken as sea
    block(52, 58, 40, 46, (k) => { z[k] = NaN; });                        // a gap
    let shelf = Infinity;
    block(30, 39, 36, 47, (k) => { shelf = Math.min(shelf, z[k]); });
    block(30, 39, 36, 47, (k) => { z[k] = shelf; });                      // a flat shelf
    block(60, 63, 30, 33, (k) => { z[k] -= 4; });                         // a closed hollow
    const grid = { lons, lats, z, rows, cols, shown: [15, 75, 15, 75], assumedSea,
      sourceId: 'copernicus_glo30', seaClean: true, label: 'a generated window' };
    const cfg = { terrain: { drainage_area_km2: 0.05 } };
    const analysis = C.analyseTerrain(grid, cfg, null, 'float32', grid.shown);
    const display = C.terrainDisplayLayers(analysis, grid, 1024);
    const captions = C.terrainCaptions(analysis, null, 'Testville');
    const credit = 'Elevation: a generated window. Cells about 30 by 31 m.';
    const settings = C.withConfig(cfg).terrain;
    const opts = { parts: analysis.parts, summary: analysis.summary, captions, figureCredit: credit,
      site: { lon: lons[50], lat: lats[45], label: 'Testville' }, cfg: settings };
    const flat = (s) => String(s).replace(/\s+/g, ' ').trim();
    const decode = async (src) => {
      const img = new Image();
      img.src = src;
      await img.decode();
      const canvas = document.createElement('canvas');
      canvas.width = img.width;
      canvas.height = img.height;
      const g = canvas.getContext('2d');
      g.drawImage(img, 0, 0);
      return { w: img.width, h: img.height, at: (x, y) => Array.from(g.getImageData(x, y, 1, 1).data),
        region: (x, y, w, h) => g.getImageData(x, y, w, h).data };
    };
    const builders = {
      terrainRelief: { title: 'title_relief', layers: ['relief'] },
      wetnessMap: { title: 'title_wetness', layers: ['wetness'] },
      curvatureMaps: { title: 'title_curvature', layers: ['profile', 'tangential'] },
      hillshadeDirections: { title: 'title_directions',
        layers: settings.hillshade_panel_azimuths_deg.map((a) => 'hillshade-' + a) },
    };
    const out = { summary: analysis.summary, display: [display.rows, display.cols, display.stride], figures: {} };
    const svgs = {};
    for (const [name, want] of Object.entries(builders)) {
      const svg = charts[name](display, opts);
      svgs[name] = svg;
      const texts = Array.from(svg.querySelectorAll('text')).map((t) => t.textContent);
      const note = (kind) => Array.from(svg.querySelectorAll(`text[data-note="${kind}"]`))
        .map((t) => t.textContent).join(' ');
      const images = Array.from(svg.querySelectorAll('image'));
      const sizes = [];
      for (const image of images) {
        const raster = await decode(image.getAttribute('href'));
        sizes.push([raster.w, raster.h]);
      }
      /* the rasterised figure: in each map, the share of pixels not of the
       * figure's own ground, which is what a dropped image would leave */
      const png = await charts.toPng(svg, { scale: 2 });
      const picture = await decode(png.dataUrl);
      const ground = picture.at(4, 4);
      const painted = images.map((image) => {
        const x = Math.round(Number(image.getAttribute('x')) * 2) + 2;
        const y = Math.round(Number(image.getAttribute('y')) * 2) + 2;
        const data = picture.region(x, y, Math.round(Number(image.getAttribute('width')) * 2) - 4,
          Math.round(Number(image.getAttribute('height')) * 2) - 4);
        let count = 0;
        for (let i = 0; i < data.length; i += 4) {
          if (Math.abs(data[i] - ground[0]) + Math.abs(data[i + 1] - ground[1]) +
              Math.abs(data[i + 2] - ground[2]) > 24) count++;
        }
        return Math.round(1000 * count / (data.length / 4)) / 1000;
      });
      const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
      out.figures[name] = {
        layers: images.map((image) => image.getAttribute('data-layer')), want: want.layers,
        sizes: sizes, title: flat(texts.join(' ')).includes(flat(captions[want.title])),
        panelTitles: name !== 'hillshadeDirections' ||
          settings.hillshade_panel_azimuths_deg.every((a, t) => texts.includes(captions['panel_' + t])),
        credit: note('credit') === credit, caveat: note('caveat') === flat(captions.figure_caveat),
        stars: svg.querySelectorAll('[data-site]').length,
        north: texts.filter((t) => t === 'N').length,
        scale: texts.filter((t) => /^\d+(\.\d+)? k?m$/.test(t)).length,
        png: [png.width, png.height, viewBox[2] * 2, viewBox[3] * 2], painted: painted,
      };
    }

    /* the relief, read cell by cell off its own raster: assumed sea hatched
     * where ((x + y) mod 6) < 2, sea and gaps in their fills, and on the
     * wetness map land with no index left transparent */
    const pixel = async (svg, find) => {
      const raster = await decode(svg.querySelector('image').getAttribute('href'));
      for (let k = 0; k < display.cls.length; k++) {
        const x = k % display.cols, y = display.rows - 1 - Math.floor(k / display.cols);
        if (find(k, x, y)) return raster.at(x, y);
      }
      return null;
    };
    const cls = display.cls, sea = display.assumedSea;
    out.cells = {
      hatched: await pixel(svgs.terrainRelief, (k, x, y) => cls[k] === 2 && sea[k] && (x + y) % 6 < 2),
      assumed: await pixel(svgs.terrainRelief, (k, x, y) => cls[k] === 2 && sea[k] && (x + y) % 6 >= 2),
      sea: await pixel(svgs.terrainRelief, (k) => cls[k] === 2 && !sea[k]),
      gap: await pixel(svgs.terrainRelief, (k) => cls[k] === 0),
      blank: await pixel(svgs.wetnessMap, (k) => cls[k] === 1 && Number.isNaN(display.twi[k])),
    };

    /* the drainage lines: one path per run of stretches routed alike, each
     * as wide as its Strahler order makes it, the flat-routed runs paler
     * and every run of a line flagged as draining beyond the square dashed */
    const runs = [];
    analysis.parts.forEach((part) => {
      let start = 0;
      const flats = part.stretch_flat;
      for (let s = 1; s <= flats.length; s++) {
        if (s < flats.length && flats[s] === flats[start]) continue;
        runs.push({ id: part.id, width: 0.6 + 0.5 * (part.strahler - 1), flat: flats[start],
          dashed: part.edge_contaminated, first: start === 0 });
        start = s;
      }
    });
    const drawn = Array.from(svgs.terrainRelief.querySelectorAll('path[data-link]'));
    const paths = drawn.map((p) => ({
      id: Number(p.getAttribute('data-link')), width: Number(p.getAttribute('stroke-width')),
      flat: p.getAttribute('stroke-opacity') === '0.45', dashed: p.hasAttribute('stroke-dasharray') }));
    /* each run of a dashed line takes the pattern up as far along the line
     * as the runs before it were drawn, so a run shorter than a dash is not
     * drawn solid by starting the pattern again */
    let along = 0;
    const offsets = drawn.map((p, i) => {
      if (runs[i] && runs[i].first) along = 0;
      const at = { id: runs[i] && runs[i].id, dashed: runs[i] && runs[i].dashed, along,
        offset: Number(p.getAttribute('stroke-dashoffset')) };
      along += p.getTotalLength();
      return at;
    }).filter((at) => at.dashed);
    out.dashes = { runs: offsets.length, later: offsets.filter((at) => at.along > 0).length,
      off: offsets.filter((at) => !(Math.abs(at.offset - at.along) < 0.1)) };
    out.lines = {
      parts: analysis.parts.length, runs: runs.length, paths: paths.length,
      same: JSON.stringify(paths) === JSON.stringify(runs.map((r) => ({ id: r.id, width: r.width,
        flat: r.flat, dashed: r.dashed }))),
      flat: paths.filter((p) => p.flat).length, dashed: paths.filter((p) => p.dashed).length,
      solid: paths.filter((p) => !p.dashed).length,
      contours: svgs.terrainRelief.querySelectorAll('path[data-contour]').length,
      elsewhere: ['wetnessMap', 'curvatureMaps', 'hillshadeDirections']
        .map((name) => svgs[name].querySelectorAll('path[data-link], path[data-contour]').length),
    };

    /* a line of order 5, 2.6 units wide, on a relief 218 units wide, whose
     * map is 60 units across for the 60 cells shown, so a cell is drawn one
     * unit across, as a window's cells are at the cap: two stretches routed
     * by slope, one across a flat and two more by slope. The map alone,
     * without the graticule, scale bar and north arrow drawn over it, and
     * rasterised at 8 times: the flat stretch keeps its 45% at its middle,
     * which round ends on the stretches beside it would cover, and those
     * stretches are drawn in the line's full colour. */
    const line = { id: 1, part: 0, strahler: 5, edge_contaminated: false, outlet: 'edge',
      vertices: [30, 31, 32, 33, 34, 35].map((c) => [45, c]), stretch_flat: [false, false, true, false, false] };
    const narrow = (parts) => {
      const svg = charts.terrainRelief(display, Object.assign({}, opts,
        { parts, summary: {}, site: null, width: 218 }));
      Array.from(svg.children).forEach((node) => {
        if (node.tagName !== 'defs' && !node.querySelector('[data-layer]')) node.setAttribute('data-export', 'skip');
      });
      return svg;
    };
    const lined = narrow([line]);
    const runsOf = Array.from(lined.querySelectorAll('path[data-link]'));
    const [withLine, ground] = await Promise.all([lined, narrow([])].map(async (svg) =>
      decode((await charts.toPng(svg, { scale: 8 })).dataUrl)));
    const middle = (p) => {
      const at = p.getPointAtLength(p.getTotalLength() / 2);
      return [Math.floor(at.x * 8), Math.floor(at.y * 8)];
    };
    out.caps = runsOf.length !== 3 ? { runs: runsOf.length } : {
      runs: runsOf.length, unit: Number(runsOf[1].getTotalLength().toFixed(2)),
      flat: withLine.at(...middle(runsOf[1])).slice(0, 3),
      pale: ground.at(...middle(runsOf[1])).slice(0, 3)
        .map((g, i) => Math.round(0.45 * [31, 92, 153][i] + 0.55 * g)),
      solid: [runsOf[0], runsOf[2]].map((p) => withLine.at(...middle(p)).slice(0, 3)),
    };
    return out;
  });
  const terrainFigures = Object.entries(terrain.figures);
  check('terrain figures: an analysis made in the page has a coast, assumed sea, a gap and a flat',
    terrain.summary.sea > 0 && terrain.summary.assumed_sea > 0 && terrain.summary.voids > 0 &&
    terrain.summary.flat_routed_stream > 0 && terrain.summary.raised > 0 &&
    terrain.display.join() === '60,60,1', JSON.stringify({ summary: terrain.summary, display: terrain.display }));
  check('terrain figures: each paints its layers at the size of the square shown',
    terrainFigures.every(([, f]) => f.layers.join() === f.want.join() &&
      f.sizes.every((s) => s.join() === '60,60')),
    JSON.stringify(terrainFigures.map(([name, f]) => [name, f.layers, f.sizes])));
  check('terrain figures: each carries its title, the credit and the caveat inside the SVG',
    terrainFigures.every(([, f]) => f.title && f.panelTitles && f.credit && f.caveat),
    JSON.stringify(terrainFigures.map(([name, f]) => [name, f.title, f.panelTitles, f.credit, f.caveat])));
  check('terrain figures: every map has the site star, a scale bar and a north arrow',
    terrainFigures.every(([, f]) => f.stars === f.want.length && f.north === f.want.length &&
      f.scale === f.want.length),
    JSON.stringify(terrainFigures.map(([name, f]) => [name, f.stars, f.north, f.scale])));
  check('terrain figures: the relief hatches assumed sea and fills sea and gaps; no index is left blank',
    JSON.stringify(terrain.cells) === JSON.stringify({ hatched: [157, 189, 216, 255],
      assumed: [207, 227, 242, 255], sea: [207, 227, 242, 255], gap: [230, 230, 230, 255],
      blank: [0, 0, 0, 0] }), JSON.stringify(terrain.cells));
  check('terrain figures: the drainage lines are drawn by order, paler where flat-routed, dashed where flagged',
    terrain.lines.same && terrain.lines.paths > 0 && terrain.lines.flat > 0 && terrain.lines.dashed > 0 &&
    terrain.lines.solid > 0 && terrain.lines.contours > 0 && terrain.lines.elsewhere.every((count) => count === 0),
    JSON.stringify(terrain.lines));
  check('terrain figures: a dashed line\'s pattern runs on from one run to the next, not starting again',
    terrain.dashes.later > 0 && terrain.dashes.off.length === 0, JSON.stringify(terrain.dashes));
  const apart = (a, b) => a.reduce((sum, v, i) => sum + Math.abs(v - b[i]), 0);
  check('terrain figures: a flat-routed stretch shorter than the line is wide is still drawn paler',
    terrain.caps.runs === 3 && terrain.caps.unit < 2 && apart(terrain.caps.flat, terrain.caps.pale) <= 9 &&
    terrain.caps.solid.every((c) => apart(c, [31, 92, 153]) <= 6), JSON.stringify(terrain.caps));
  check('terrain figures: toPng of each gives a PNG whose maps are painted',
    terrainFigures.every(([, f]) => f.png[0] === f.png[2] && f.png[1] === f.png[3] &&
      f.painted.length === f.want.length && f.painted.every((share) => share > 0.6)),
    JSON.stringify(terrainFigures.map(([name, f]) => [name, f.png, f.painted])));

  // The lineament candidates' two figures (PLAN.md step 4.2), drawn from an
  // analysis made here of the window test_study_area_maps.py draws them
  // from: gentle relief with a valley cut due north and a ridge raised
  // north-east, one candidate of each. The map draws each candidate from
  // end to end in its kind's colour over the grey relief of the square
  // shown, keyed, with the site, a scale bar and a north arrow; the rose
  // draws each band twice, opposite itself, reaching the square root of its
  // share of the longest band, with its rings named; both carry the title,
  // the credit, and the note that the candidates are inferred from terrain
  // with the caveat, inside the SVG; a rose with no candidate is not drawn;
  // and both rasterise through toPng.
  const lineamentFigures = await page.evaluate(async () => {
    const C = window.GWT.core, charts = window.GWT.charts;
    const n = 160, step = 1 / 3600;
    const lons = new Float64Array(n), lats = new Float64Array(n), z = new Float64Array(n * n);
    for (let k = 0; k < n; k++) {
      lons[k] = -12.0 + k * step;
      lats[k] = 8.5 + k * step;
    }
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        const along = (r + c) / Math.SQRT2, across = (r - c) / Math.SQRT2;
        let v = 100 + 0.02 * c + 1.5 * Math.sin(r / 9) * Math.cos(c / 11);
        if (r > 20 && r < 140) v -= 8 * Math.exp(-(((c - 60) / 3) ** 2));
        if (along > 60 && along < 170) v += 8 * Math.exp(-(((across - 20) / 3) ** 2));
        z[r * n + c] = v;
      }
    }
    const grid = { lons, lats, z, rows: n, cols: n, shown: [10, 150, 10, 150], assumedSea: null,
      sourceId: 'copernicus_glo30', seaClean: true, label: 'a generated window' };
    const analysis = C.analyseTerrain(grid, null, null, 'float64', grid.shown);
    const lin = C.lineamentCandidates(analysis, null, null);
    const display = C.terrainDisplayLayers(analysis, grid, 1024);
    const captions = Object.assign({}, C.terrainCaptions(analysis, null, 'Testville'),
      C.lineamentCaptions(lin, 'Testville'));
    const credit = 'Elevation: a generated window. Cells about 31 by 31 m.';
    const opts = { captions, figureCredit: credit, lineaments: lin, axes: { lons, lats },
      site: { lon: lons[80], lat: lats[80], label: 'Testville' } };
    const flat = (text) => String(text).replace(/\s+/g, ' ').trim();
    const map = charts.lineamentMap(display, opts), rose = charts.lineamentRose(lin, opts);
    const notes = (svg, kind) => flat(Array.from(svg.querySelectorAll(`text[data-note="${kind}"]`))
      .map((t) => t.textContent).join(' '));
    const texts = (svg) => Array.from(svg.querySelectorAll('text')).map((t) => t.textContent);
    const lines = Array.from(map.querySelectorAll('line[data-lineament]')).map((line) => {
      const [x1, y1, x2, y2] = ['x1', 'y1', 'x2', 'y2'].map((key) => Number(line.getAttribute(key)));
      return { kind: line.getAttribute('data-kind'), colour: line.getAttribute('stroke'),
        across: Math.round(100 * Math.abs(x2 - x1) / Math.abs(y2 - y1)) / 100 };
    });
    const longest = Math.max(...lin.roseValleyM, ...lin.roseRidgeM);
    const petals = Array.from(rose.querySelectorAll('path[data-petal]')).map((path) => {
      const kind = path.getAttribute('data-petal'), band = Number(path.getAttribute('data-band'));
      const length = (kind === 'valley' ? lin.roseValleyM : lin.roseRidgeM)[band];
      return [kind, band, Number(path.getAttribute('data-from')),
        Math.abs(Number(path.getAttribute('data-reach')) - Math.sqrt(length / longest)) < 1e-6];
    });
    const zeros = new Array(18).fill(0);
    const painted = async (svg) => {
      const png = await charts.toPng(svg, { scale: 2 });
      const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
      return [png.width, png.height].join() === [viewBox[2] * 2, viewBox[3] * 2].join();
    };
    return {
      candidates: lin.lineaments.map((l) => [l.kind, Math.round(l.strike_deg)]), lines,
      layer: Array.from(map.querySelectorAll('image')).map((i) => i.getAttribute('data-layer')).join(),
      key: ['Straight valley', 'Straight ridge'].every((label) => texts(map).includes(label)),
      furniture: [map.querySelectorAll('[data-site]').length, texts(map).filter((t) => t === 'N').length,
        texts(map).filter((t) => /^\d+(\.\d+)? k?m$/.test(t)).length].join(),
      inside: [map, rose].map((svg) => [flat(texts(svg).join(' ')).includes(flat(captions['title_' +
        (svg === map ? 'lineaments' : 'rose')])), notes(svg, 'credit') === credit,
      notes(svg, 'caveat') === flat(captions.figure_note + ' ' + captions.figure_caveat)].join()),
      petals, headings: [captions.rose_valleys, captions.rose_ridges].every((h) => texts(rose).includes(h)),
      rings: rose.querySelectorAll('text[data-ring]').length,
      none: charts.lineamentRose(Object.assign({}, lin, { lineaments: [], roseValleyM: zeros, roseRidgeM: zeros }),
        opts) === null,
      png: [await painted(map), await painted(rose)].join(),
    };
  });
  check('lineament figures: the planted valley and ridge are found, one candidate each',
    JSON.stringify(lineamentFigures.candidates) === '[["valley",0],["ridge",45]]',
    JSON.stringify(lineamentFigures.candidates));
  check('lineament figures: the map draws each candidate end to end in its kind\'s colour over the grey relief, ' +
    'keyed, with the site, a scale bar and a north arrow',
    JSON.stringify(lineamentFigures.lines.map((l) => [l.kind, l.colour])) ===
      '[["valley","#1D4E89"],["ridge","#C15A2A"]]' && lineamentFigures.lines[0].across < 0.05 &&
    Math.abs(lineamentFigures.lines[1].across - 1) < 0.1 && lineamentFigures.layer === 'lineaments' &&
    lineamentFigures.key && lineamentFigures.furniture === '1,1,1', JSON.stringify(lineamentFigures));
  check('lineament figures: the rose draws each band twice, opposite itself, its area going with its length, ' +
    'the rings named and each rose headed with its count and length',
    JSON.stringify(lineamentFigures.petals) ===
      '[["valley",0,0,true],["valley",0,180,true],["ridge",4,40,true],["ridge",4,220,true]]' &&
    lineamentFigures.headings && lineamentFigures.rings === 8 && lineamentFigures.none,
    JSON.stringify([lineamentFigures.petals, lineamentFigures.headings, lineamentFigures.rings, lineamentFigures.none]));
  check('lineament figures: both carry the title, the credit, and the note with the caveat inside the SVG, and ' +
    'rasterise whole', lineamentFigures.inside.every((row) => row === 'true,true,true') &&
    lineamentFigures.png === 'true,true', JSON.stringify([lineamentFigures.inside, lineamentFigures.png]));

  // The Topography and terrain card on Site & maps (PLAN.md step 4.1), at
  // #/site/terrain. Files dropped on it or picked are opened for their
  // layout at once, so a refusal or a question about a file's source shows
  // beside its name in the engine's words. "Analyse the terrain" plans the
  // window on the page, reads the blocks it meets in the reads
  // C.elevationBlockRanges gives, the edge blocks of a missing tile
  // included, each block cut out with a buffer of its own, and has the
  // worker read the window: the read report on the card is the one the
  // engine writes for the same files read whole with the same settings. The
  // site is put on the shared edge of the committed Copernicus pair, 8.995 N,
  // 11.0 W, and then on the corner of the holes_sea tiles, 8 N, 12 W, where
  // the fourth tile is missing and taken as sea.
  const dem = async (name) => ({ name, mimeType: 'image/tiff',
    buffer: await readFile(new URL('./fixtures/dem/' + name, import.meta.url)) });
  const demSet = (names) => Promise.all(names.map(dem));
  const pair = await demSet(['Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif',
    'Copernicus_DSM_COG_10_N08_00_W011_00_DEM.tif']);
  const odd = await demSet(['refuse_jpeg.tif', 'n08w011.tif']);
  const holes = await demSet(['holes_N08W012.tif', 'holes_sea_N08W013.tif', 'holes_sea_N07W012.tif']);
  const overlap = await demSet(['overlap_north.tif', 'overlap_south_disagrees.tif']);
  /* the files as page.evaluate can carry them */
  const carried = (files) => files.map((f) => ({ name: f.name, bytes: Array.from(f.buffer) }));
  const keptSite = await page.evaluate(() => {
    const store = window.GWT.app.store;
    const kept = { easting: store.get('site.easting'), northing: store.get('site.northing'),
      utm_zone: store.get('site.utm_zone') };
    store.set('site.easting', 280126.0);
    store.set('site.northing', 994900.0);
    store.set('site.utm_zone', 29);
    /* what the page reads of the files, and the blocks it hands the worker */
    window.__slices = [];
    window.__slice = Blob.prototype.slice;
    Blob.prototype.slice = function (start, end, type) {
      if (this instanceof File) window.__slices.push([this.name, start, end]);
      return window.__slice.call(this, start, end, type);
    };
    const engine = window.GWT.engine;
    window.__readElevation = engine.readElevation;
    engine.readElevation = function (plan, blocks, cfg, options) {
      window.__sent = blocks.map((b) => (b ? [b.byteOffset, b.byteLength, b.buffer.byteLength] : null));
      return window.__readElevation.call(this, plan, blocks, cfg, options);
    };
    location.hash = '#/site/terrain';
    return kept;
  });
  await page.waitForFunction(() => {
    const node = document.querySelector('#page-host .item-target');
    return node && node.getAttribute('data-item') === 'terrain';
  });
  const terrainCard = await page.evaluate(async () => {
    const arrived = () => {
      const node = document.querySelector('#page-host .item-target');
      const top = node ? node.getBoundingClientRect().top : Infinity;
      return top >= 0 && top < window.innerHeight / 2;
    };
    for (let waited = 0; waited < 5000 && !arrived(); waited += 100) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    const titles = Array.from(document.querySelectorAll('#page-host .card-title'))
      .map((t) => t.textContent);
    const at = titles.indexOf('Topography and terrain');
    return { nav: window.GWT.app.store.get('nav'), hash: location.hash, inView: arrived(),
      title: document.querySelector('#page-host .item-target .card-title').textContent,
      before: titles[at - 1], after: titles[at + 1] };
  });
  check('terrain card: #/site/terrain opens Site & maps on the Topography and terrain card',
    terrainCard.nav === 'site' && terrainCard.hash === '#/site/terrain' &&
    terrainCard.title === 'Topography and terrain' && terrainCard.inView, JSON.stringify(terrainCard));
  check('terrain card: it sits between Geology and aquifers and the Interactive map',
    terrainCard.before === 'Geology and aquifers' && terrainCard.after === 'Interactive map',
    JSON.stringify(terrainCard));

  /* the card's list as it stands: each file's details and its callouts */
  const listed = () => page.evaluate(() => Array.from(
    document.querySelectorAll('[data-item="terrain"] .terrain-file')).map((node) => ({
    name: node.getAttribute('data-file'),
    details: node.querySelector('.muted').textContent,
    refusals: Array.from(node.querySelectorAll('.callout-bad p')).map((p) => p.textContent),
    prompts: Array.from(node.querySelectorAll('.callout-warn p')).map((p) => p.textContent),
  })));
  const opened = (n) => page.waitForFunction((count) => {
    const files = document.querySelectorAll('[data-item="terrain"] .terrain-file');
    return files.length === count && Array.from(files).every((f) => !f.textContent.includes('opening…'));
  }, n);
  /* files dropped on the card, as a drag from the desktop delivers them */
  const drop = (files, extra) => page.evaluate(([list, hgt]) => {
    const transfer = new DataTransfer();
    list.forEach((f) => transfer.items.add(new File([new Uint8Array(f.bytes)], f.name)));
    /* an SRTM-format tile, placed by its name and sized by its length */
    if (hgt) transfer.items.add(new File([new Uint8Array(2 * 1201 * 1201)], hgt));
    document.querySelector('[data-item="terrain"] .upload-zone').dispatchEvent(
      new DragEvent('drop', { dataTransfer: transfer, bubbles: true, cancelable: true }));
  }, [carried(files), extra || null]);
  /* a field of the card by its label */
  const setField = (label, value) => page.evaluate(([text, v]) => {
    const host = Array.from(document.querySelectorAll('[data-item="terrain"] label.field'))
      .find((f) => f.querySelector('.field-label').textContent === text);
    const input = host.querySelector('input, select');
    input.value = v;
    input.dispatchEvent(new Event('change'));
  }, [label, value]);
  /* the Analyse button: pressed, or whether it can be */
  const analyse = (press) => page.evaluate((click) => {
    const node = Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain');
    if (click) node.click();
    return node.disabled;
  }, press);
  const removeAll = () => page.evaluate(() => {
    const names = Array.from(document.querySelectorAll('[data-item="terrain"] .terrain-file'))
      .map((node) => node.getAttribute('data-file'));
    for (const name of names) {
      Array.from(document.querySelectorAll(`[data-item="terrain"] .terrain-file[data-file="${name}"] button`))
        .find((b) => b.textContent === 'Remove').click();
    }
  });
  /* "Analyse the terrain" pressed, what the page read and handed the
   * worker, and the read the engine makes of the same files read whole,
   * at the radius and with the source the card was given */
  const readOnCard = async (files, radius, declared) => {
    await page.evaluate(() => { window.__slices = []; window.__sent = null; });
    await analyse(true);
    await page.waitForFunction(() => document.querySelector('[data-item="terrain"] .terrain-read'),
      null, { timeout: 60000 });
    return page.evaluate(([list, r, d]) => {
      const C = window.GWT.core, app = window.GWT.app, cfg = app.config();
      const whole = {};
      list.forEach((f) => { whole[f.name] = new Uint8Array(f.bytes); });
      const found = list.map((f) => C.elevationFile(f.name, whole[f.name].length, [[0, whole[f.name]]]));
      const centre = C.windowCentre(app.store.get('site'), app.siteLatLon(), found);
      const plan = C.planElevationWindow(found, centre, r, cfg, null, d);
      const blocks = plan.blocks.map((b) => (b.length
        ? whole[plan.files[b.file].name].slice(b.offset, b.offset + b.length) : null));
      const read = C.readElevationWindow(plan, blocks, cfg, null);
      const shown = document.querySelector('[data-item="terrain"] .terrain-read');
      const last = window.GWT.engine.history().filter((h) => h.type === 'readElevation').pop();
      return {
        notes: Array.from(shown.querySelectorAll(':scope > p')).map((p) => p.textContent),
        /* under the read report, or under the downloads once the analysis
         * that follows the read has drawn its figures */
        notice: document.querySelector('[data-item="terrain"] .terrain-notice small')?.textContent || null,
        want: { notes: read.notes, notice: read.notice },
        liability: C.phrase('terrain.copernicus_liability'),
        slices: window.__slices.splice(0),
        reads: C.elevationBlockRanges(plan).map((x) => [x.name, x.offset, x.offset + x.length]),
        blocks: plan.blocks.filter((b) => b.length).length,
        edgeOnly: plan.blocks.filter((b) => !b.window).length,
        sent: window.__sent,
        lengths: plan.blocks.map((b) => (b.length ? b.length : null)),
        ran: last ? [last.mode, last.outcome] : null,
      };
    }, [carried(files), radius, declared]);
  };
  /* the blocks went to the worker each with a buffer of its own, and the
   * worker read them */
  const ownBuffers = (read) => read.sent.length === read.lengths.length &&
    read.sent.every((b, i) => (b === null ? read.lengths[i] === null
      : b[0] === 0 && b[1] === read.lengths[i] && b[2] === b[1])) &&
    JSON.stringify(read.ran) === '["worker","done"]';

  await drop(odd, 'N08W012.hgt');
  await opened(3);
  const dropped = {
    list: await listed(),
    read: await page.evaluate(() => window.__slices.splice(0)),
    engine: await page.evaluate((files) => files.map((f) => {
      const C = window.GWT.core, bytes = new Uint8Array(f.bytes);
      try {
        const found = C.elevationFile(f.name, bytes.length, [[0, bytes]]);
        return { refusals: [], prompts: C.fileNotes(found, ['detect', '']) };
      } catch (e) {
        return { refusals: [e.message], prompts: [] };
      }
    }), carried(odd)),
    disabled: await analyse(false),
  };
  await setField('Source of the elevation model', 'copernicus_glo30');
  dropped.declared = await listed();
  await setField('Source of the elevation model', 'detect');
  check('terrain card: a dropped file\'s refusal and a question about its source show at once, in the ' +
    'engine\'s words',
    dropped.list.map((f) => f.name).join() === 'refuse_jpeg.tif,n08w011.tif,N08W012.hgt' &&
    dropped.list.slice(0, 2).every((f, i) => JSON.stringify([f.refusals, f.prompts]) ===
      JSON.stringify([dropped.engine[i].refusals, dropped.engine[i].prompts])) &&
    dropped.list[0].refusals.length === 1 && dropped.list[1].prompts.length === 1 &&
    dropped.list[1].details === '5.4 kB · source not recognised' && dropped.disabled,
    JSON.stringify(dropped));
  /* a cloud-optimised file's directories are all in its first 64 KiB */
  check('terrain card: a GeoTIFF is opened from its first 64 KiB alone and an .hgt tile from its name, ' +
    'as the Python app opens them',
    JSON.stringify(dropped.read) === JSON.stringify(odd.map((f) => [f.name, 0, f.buffer.length])) &&
    JSON.stringify(dropped.list[2]) === JSON.stringify({ name: 'N08W012.hgt',
      details: '2.9 MB · SRTM format, source not stated', refusals: [], prompts: [] }),
    JSON.stringify([dropped.read, dropped.list[2]]));
  check('terrain card: declaring the source answers the question about it',
    dropped.declared[1].prompts.length === 0 && dropped.declared[0].refusals.length === 1,
    JSON.stringify(dropped.declared));
  await removeAll();
  const removed = await listed();
  check('terrain card: Remove takes a file off the list', removed.length === 0, JSON.stringify(removed));

  const [chooser] = await Promise.all([page.waitForEvent('filechooser'),
    page.click('[data-item="terrain"] .upload-zone')]);
  await chooser.setFiles(pair);
  await opened(2);
  const picked = await listed();
  const opening = await page.evaluate(() => window.__slices.splice(0));
  check('terrain card: the Copernicus pair picked is listed with its sizes and recognised',
    JSON.stringify(picked.map((f) => [f.name, f.details, f.refusals, f.prompts])) === JSON.stringify([
      [pair[0].name, '5.5 kB · recognised as Copernicus GLO-30', [], []],
      [pair[1].name, '5.4 kB · recognised as Copernicus GLO-30', [], []]]), JSON.stringify(picked));
  check('terrain card: the pair picked is opened from its first 64 KiB, as a dropped file is',
    JSON.stringify(opening) === JSON.stringify(pair.map((f) => [f.name, 0, f.buffer.length])),
    JSON.stringify(opening));

  /* the widest radius asked for is over the cap on cells at 1 arc-second */
  await setField('Radius of the square shown (km)', '50');
  await analyse(true);
  await page.waitForFunction(() => document.querySelector('[data-item="terrain"] .btn-row ~ .callout-bad'));
  const overCap = await page.evaluate((files) => {
    const C = window.GWT.core, app = window.GWT.app;
    const found = files.map((f) => C.elevationFile(f.name, f.bytes.length, [[0, new Uint8Array(f.bytes)]]));
    let want = '';
    try {
      C.planElevationWindow(found, C.windowCentre(app.store.get('site'), app.siteLatLon(), found), 50,
        app.config(), null, ['detect', '']);
    } catch (e) {
      want = e.message;
    }
    return { shown: document.querySelector('[data-item="terrain"] .btn-row ~ .callout-bad').textContent,
      want, read: !!document.querySelector('[data-item="terrain"] .terrain-read'),
      reads: window.__slices.splice(0) };
  }, carried(pair));
  check('terrain card: a window over the cap is refused on the card in the engine\'s words, with the ' +
    'radius that fits, and nothing is read',
    overCap.shown === overCap.want && overCap.want.includes('km fits') && !overCap.read &&
    overCap.reads.length === 0, JSON.stringify(overCap));

  await setField('Radius of the square shown (km)', '1');
  const pairRead = await readOnCard(pair, 1, ['detect', '']);
  check('terrain card: the read report is the engine\'s for the same files read whole, with the ' +
    'Copernicus notice in small print',
    pairRead.notes.length > 1 && JSON.stringify(pairRead.notes) === JSON.stringify(pairRead.want.notes) &&
    pairRead.notes[0].startsWith('Read 2 files (') && pairRead.notes[0].includes(', 1 km each way.') &&
    pairRead.notice === pairRead.want.notice && pairRead.notice === pairRead.liability,
    JSON.stringify(pairRead));
  check('terrain card: the blocks are read in merged reads, one a file here, and nothing else is read',
    JSON.stringify(pairRead.slices) === JSON.stringify(pairRead.reads) &&
    pairRead.reads.length === 2 && pairRead.blocks > pairRead.reads.length,
    JSON.stringify([pairRead.slices, pairRead.reads, pairRead.blocks]));
  check('terrain card: each block goes to the worker with a buffer of its own, and the worker reads them',
    ownBuffers(pairRead), JSON.stringify([pairRead.sent, pairRead.ran]));

  /* three tiles around a missing fourth, declared Copernicus GLO-30 since
   * their names are not Copernicus's */
  await removeAll();
  await page.evaluate(() => {
    const store = window.GWT.app.store;
    store.set('site.easting', -12.0);
    store.set('site.northing', 8.0);
    store.set('site.utm_zone', null);
  });
  await drop(holes);
  await opened(3);
  await setField('Source of the elevation model', 'copernicus_glo30');
  await setField('Radius of the square shown (km)', '15');
  const holesRead = await readOnCard(holes, 15, ['copernicus_glo30', '']);
  await page.evaluate((kept) => {
    Blob.prototype.slice = window.__slice;
    window.GWT.engine.readElevation = window.__readElevation;
    const store = window.GWT.app.store;
    Object.keys(kept).forEach((key) => store.set('site.' + key, kept[key]));
  }, keptSite);
  check('terrain card: a missing tile beside sea-level edges is read as sea, as the engine reads it under ' +
    'the source declared',
    JSON.stringify(holesRead.notes) === JSON.stringify(holesRead.want.notes) &&
    holesRead.notes.some((note) => note.includes('a tile not supplied (N07 W013)')) &&
    holesRead.notice === holesRead.liability, JSON.stringify(holesRead));
  check('terrain card: the edge blocks beside the missing tile are read too, outside the window',
    JSON.stringify(holesRead.slices) === JSON.stringify(holesRead.reads) && holesRead.edgeOnly > 0 &&
    ownBuffers(holesRead), JSON.stringify([holesRead.slices, holesRead.reads, holesRead.edgeOnly,
      holesRead.sent, holesRead.ran]));

  // "Analyse the terrain" goes on from the read to the analysis, in the
  // engine worker, with each stage the engine names shown in the work bar
  // and its Cancel there, which stops the worker and keeps nothing. The
  // answer is the engine's at the card's drainage threshold. A new
  // threshold is worked out on the page from the core the worker handed
  // over, with no request to the engine: the lines, the captions, the
  // summary and the GeoJSON are those of an analysis at that threshold, and
  // of the figures only the relief is drawn again, with the new lines. An
  // answer to a run since dropped is not shown. With no worker the card
  // says, before a run, that the page will be held, and a Cancel read
  // between the read and the analysis stops it there. A device that says it
  // has 2 GB of memory or less is asked before a window of more than a
  // million cells. The tile is an SRTM-format .hgt made here: ridges and
  // hollows falling to the south-west, at 3 arc-seconds, around a site at
  // 8.5 N, 11.5 W, with a straight valley 15 m deep running due north
  // through it, a lineament candidate on every window the card reads.
  await removeAll();
  const keptTerrain = await page.evaluate(() => {
    const app = window.GWT.app, engine = window.GWT.engine, store = app.store;
    const kept = { easting: store.get('site.easting'), northing: store.get('site.northing'),
      utm_zone: store.get('site.utm_zone') };
    store.set('site.easting', -11.5);
    store.set('site.northing', 8.5);
    store.set('site.utm_zone', null);
    const n = 1201, view = new DataView(new ArrayBuffer(2 * n * n));
    for (let row = 0; row < n; row++) {
      for (let col = 0; col < n; col++) {
        const x = col, y = n - 1 - row;
        const z = 300 - 0.1 * (x + y) + 35 * Math.sin(x / 31) * Math.sin(y / 23) + 20 * Math.cos((x - y) / 47) -
          15 * Math.exp(-(((x - 603) / 4) ** 2));
        view.setInt16(2 * (row * n + col), Math.round(z), false);
      }
    }
    window.__hgt = new File([view.buffer], 'N08W012.hgt');
    /* what the page reads of the tile */
    window.__slices = [];
    window.__slice = Blob.prototype.slice;
    Blob.prototype.slice = function (start, end, type) {
      if (this instanceof File) window.__slices.push([this.name, start, end]);
      return window.__slice.call(this, start, end, type);
    };
    /* what the card asks the engine to analyse, the stages it hears, and,
     * when the test says so, the request held back until released, or a
     * Cancel pressed the moment the analysis is asked for */
    window.__analyseTerrain = engine.analyseTerrain;
    engine.analyseTerrain = function (grid, cfg, read, where, options) {
      const heard = window.__heard = [];
      /* the grid as the card hands it over: the card lets go of its cells
       * once the analysis has answered */
      window.__grid = Object.assign({}, grid);
      window.__asked = { area: cfg.terrain.drainage_area_km2, where, label: read.centre.label,
        stripped: [read.grid, read.assumedSea, read.reasons].every((v) => v === null),
        captions: [!!read.plan, !!read.surface], grid: grid.rows * grid.cols };
      const opts = Object.assign({}, options, { onProgress: (fraction, label) => {
        heard.push([fraction, label]);
        options.onProgress(fraction, label);
      } });
      const go = () => window.__analyseTerrain.call(engine, grid, cfg, read, where, opts);
      if (window.__hold) return new Promise((resolve) => { window.__release = resolve; }).then(go);
      const answer = go();
      if (window.__cancelNow) app.cancelWork('terrain');
      return answer;
    };
    /* the session's answer, and the engine's own analysis of the grid the
     * card read and handed over, at a threshold, with the GeoJSON the
     * Python app writes; and the lineament candidates found in it, with
     * their captions and GeoJSON, which no threshold moves */
    window.__terrainGot = () => {
      const r = app.terrainSession().result;
      return JSON.stringify({ links: r.links, parts: r.parts, summary: r.summary, captions: r.captions,
        geojson: r.geojson, lineaments: Object.assign({}, r.lineaments, { settings: null }),
        lineamentCaptions: r.lineamentCaptions, lineamentGeojson: r.lineamentGeojson,
        plan: r.plan ? Object.assign({}, r.plan, { settings: null }) : null, planCaptions: r.planCaptions,
        planGpx: r.planGpx, planGeoJson: r.planGeoJson });
    };
    window.__terrainWant = (areaKm2) => {
      const C = window.GWT.core, read = app.terrainSession().read, grid = window.__grid, cfg = app.config();
      cfg.terrain.drainage_area_km2 = areaKm2;
      const a = C.analyseTerrain(grid, cfg, null, 'float32', grid.shown);
      let sea = 0;
      for (const v of a.core.cls) sea += v === 2 ? 1 : 0;
      const geojson = C.drainageGeoJson(a.core, a.parts, { label: read.grid.label,
        figure_credit: read.figureCredit, notice: read.notice, surface: read.surface, area: areaKm2,
        radius: read.plan.radiusKm, margin: read.plan.marginKm, centre: read.centre,
        fill_note_m: a.settings.fill_note_m, sea_clean: read.grid.seaClean, sea_cells: sea,
        sea_level_m: a.settings.sea_level_m });
      const lineaments = C.lineamentCandidates(a, null, null);
      const lineamentGeojson = C.lineamentGeoJson(lineaments, read.grid.lons, read.grid.lats, {
        label: read.grid.label, figure_credit: read.figureCredit, notice: read.notice, surface: read.surface,
        radius: read.plan.radiusKm, centre: read.centre });
      /* the survey plan laid across them round the site (PLAN.md step
       * 4.3), keeping clear of the drainage lines at this threshold; no
       * water points are loaded */
      const result = app.terrainSession().result, site = result ? result.site : null;
      const plan = site ? C.surveyPlan(lineaments, a.core, a.parts, [site.lon, site.lat], null, cfg.terrain, cfg.ves)
        : null;
      const laid = !!plan && plan.basis !== 'none';
      const told = { where: read.centre.label, label: read.grid.label,
        site_label: app.store.get('site.community') || 'Site' };
      return JSON.stringify({ links: a.links, parts: a.parts, summary: a.summary,
        captions: C.terrainCaptions(a, read, read.centre.label), geojson,
        /* the settings the candidates carry name the threshold, which no
         * candidate depends on */
        lineaments: Object.assign({}, lineaments, { settings: null }),
        lineamentCaptions: C.lineamentCaptions(lineaments, read.centre.label), lineamentGeojson,
        plan: plan ? Object.assign({}, plan, { settings: null }) : null,
        planCaptions: C.surveyPlanCaptions(plan, read.centre.label),
        planGpx: laid ? C.surveyPlanGpx(plan, a.core.lons, a.core.lats, told) : null,
        planGeoJson: laid ? C.surveyPlanGeoJson(plan, a.core.lons, a.core.lats, told) : null });
    };
    window.__until = async (test, ms) => {
      const began = performance.now();
      while (!test()) {
        if (performance.now() - began > (ms || 60000)) return false;
        await new Promise((resolve) => setTimeout(resolve, 20));
      }
      return true;
    };
    window.__settled = () => !app.terrainSession().running && !app.working('terrain');
    window.__lastTerrain = () => engine.history().filter((h) => h.type === 'readElevation' ||
      h.type === 'analyseTerrain').slice(-2).map((h) => [h.type, h.mode, h.outcome, !!h.ran]);
    window.__card = () => {
      const host = document.querySelector('[data-item="terrain"]');
      const button = Array.from(host.querySelectorAll('button'))
        .find((b) => b.textContent === 'Analyse the terrain');
      return { read: !!host.querySelector('.terrain-read'),
        refusals: Array.from(host.querySelectorAll('.btn-row ~ .callout-bad')).map((c) => c.textContent),
        pageOnly: host.querySelector('.terrain-page-only')?.textContent || null,
        running: Array.from(host.querySelectorAll('p.muted'))
          .some((p) => p.textContent.startsWith('Analysing the terrain.')),
        disabled: button.disabled, bar: !!document.querySelector('#work-status .work-bar') };
    };
    window.__toasts = () => Array.from(document.querySelectorAll('.toast')).map((t) => t.textContent);
    const transfer = new DataTransfer();
    transfer.items.add(window.__hgt);
    document.querySelector('[data-item="terrain"] .upload-zone').dispatchEvent(
      new DragEvent('drop', { dataTransfer: transfer, bubbles: true, cancelable: true }));
    return kept;
  });
  await opened(1);
  /* the tile as found, whatever was declared for the files before it */
  await setField('Source of the elevation model', 'detect');
  const stages = await page.evaluate(() => ['classes', 'fill', 'flow', 'flats', 'accumulate', 'drainage',
    'shading', 'curvature', 'lineaments'].map((s) => window.GWT.core.phrase('terrain.stage_' + s)));
  /* labels in the order the engine names its stages, none twice */
  const inOrder = (labels) => labels.every((label, i) => stages.indexOf(label) >= 0 &&
    (i === 0 || stages.indexOf(label) > stages.indexOf(labels[i - 1])));

  /* a run to the end in the worker, the work bar watched as it goes */
  await setField('Radius of the square shown (km)', '30');
  await setField('Drainage threshold (km²)', '0.25');
  const worked = await page.evaluate(async () => {
    const seen = [];
    const watch = new MutationObserver(() => {
      const bar = document.querySelector('#work-status .work-bar[data-work="terrain"]');
      if (bar) {
        seen.push([bar.querySelector('.work-label').textContent,
          bar.querySelector('.work-detail').textContent,
          parseFloat(bar.querySelector('.progress-fill').style.width) || 0, bar.textContent.includes('Cancel')]);
      }
    });
    watch.observe(document.querySelector('#work-status'), { subtree: true, childList: true,
      characterData: true, attributes: true });
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    const during = window.__card();
    const done = await window.__until(window.__settled);
    watch.disconnect();
    const s = window.GWT.app.terrainSession();
    return { during, done, seen, after: window.__card(), ran: window.__lastTerrain(), asked: window.__asked,
      heard: window.__heard, centre: s.read.centre.label, cells: s.read.grid.rows * s.read.grid.cols,
      areaKm2: s.result.areaKm2, lines: s.result.parts.length, got: window.__terrainGot(),
      want: window.__terrainWant(0.25), stage: window.GWT.core.phrase('terrain.stage_read'),
      kept: { z: s.read.grid.z, assumedSea: s.read.grid.assumedSea, readSea: s.read.assumedSea,
        reasons: s.read.reasons, lons: s.read.grid.lons.length, notes: s.read.notes.length } };
  });
  const barDetails = worked.seen.map((b) => b[1]).filter((d, i, all) => d !== all[i - 1]);
  check('terrain analysis: the read goes on to the analysis in the worker, the grid sent once and the read ' +
    'without its cells',
    worked.done && JSON.stringify(worked.ran) ===
      '[["readElevation","worker","done",true],["analyseTerrain","worker","done",true]]' &&
    worked.asked.stripped && worked.asked.captions.every(Boolean) && worked.asked.where === worked.centre &&
    worked.asked.grid === worked.cells && worked.cells > 500000 && worked.cells < 1000000,
    JSON.stringify([worked.done, worked.ran, worked.asked, worked.cells]));
  check('terrain analysis: the work bar names each stage as the engine does, and holds Cancel while it runs',
    worked.during.running && worked.during.disabled && worked.seen.length > 0 &&
    worked.seen.every((b) => b[0] === 'Analysing the terrain' && b[3]) &&
    worked.seen.every((b, i) => i === 0 || b[2] >= worked.seen[i - 1][2]) &&
    inOrder(barDetails.filter((d) => d !== worked.stage)) && barDetails.some((d) => d !== worked.stage) &&
    worked.heard.length > 0 && worked.heard[0][1] === stages[0] &&
    inOrder(worked.heard.map((h) => h[1]).filter((label, i, all) => label !== all[i - 1])) &&
    !worked.after.bar && !worked.after.running && !worked.after.disabled,
    JSON.stringify([worked.during, barDetails, worked.seen.slice(0, 3), worked.heard, worked.after]));
  check('terrain analysis: the lines, summary, captions and GeoJSON are the engine\'s at the card\'s threshold',
    worked.asked.area === 0.25 && worked.areaKm2 === 0.25 && worked.lines > 10 && worked.got === worked.want,
    JSON.stringify([worked.asked.area, worked.areaKm2, worked.lines, worked.got.slice(0, 300),
      worked.want.slice(0, 300)]));
  check('terrain analysis: once it has answered, the page keeps none of the read\'s layers of a value a cell',
    worked.kept.z === null && worked.kept.assumedSea === null && worked.kept.readSea === null &&
    worked.kept.reasons === null && worked.kept.lons > 0 && worked.kept.notes > 0,
    JSON.stringify(Object.fromEntries(Object.entries(worked.kept).map(([key, v]) =>
      [key, v === null || typeof v === 'number' ? v : 'kept']))));

  /* a new threshold, and back */
  const retraced = { first: worked.got };
  await page.evaluate(() => {
    const s = window.GWT.app.terrainSession();
    window.__mark = window.GWT.engine.history().length;
    /* the figures the card drew from the first answer */
    window.__figures = Object.assign({}, s.figures);
  });
  await setField('Drainage threshold (km²)', '2');
  Object.assign(retraced, await page.evaluate(() => {
    const s = window.GWT.app.terrainSession(), was = window.__figures || {}, now = s.figures || {};
    const figures = Object.keys(was).filter((key) => was[key] && now[key] === was[key]);
    /* the lines a relief draws, by link, and those of the parts it was given */
    const links = (svg) => (svg ? Array.from(new Set(Array.from(svg.querySelectorAll('path[data-link]'))
      .map((p) => Number(p.getAttribute('data-link'))))).sort((a, b) => a - b).join() : null);
    const shown = Array.from(document.querySelectorAll('[data-item="terrain"] figure.figure'));
    /* the four, the lineament map and, where there is a candidate, the
     * rose, and the survey plan where it lays a line */
    const all = ['relief', 'wetness', 'curvature', 'directions', 'lineaments']
      .concat(s.result.lineaments.lineaments.length ? ['rose'] : []).concat(s.result.planGpx ? ['plan'] : []);
    return { asked: window.GWT.engine.history().length - window.__mark, areaKm2: s.result.areaKm2,
      figures, drawn: Object.keys(was).filter((key) => was[key]), all,
      relief: !!now.relief && now.relief !== was.relief && links(now.relief) === Array.from(new Set(
        s.result.parts.filter((p) => p.vertices.length > 1).map((p) => p.id))).sort((a, b) => a - b).join() &&
        links(now.relief) !== links(was.relief),
      plan: !!now.plan && now.plan !== was.plan,
      shown: shown.map((f) => Object.keys(now).find((key) => now[key] === f.querySelector('svg'))),
      shownCaption: shown.length ? (shown[0].querySelector('figcaption span') || {}).textContent : null,
      got: window.__terrainGot(), want: window.__terrainWant(2), caption: s.result.captions.relief };
  }));
  await setField('Drainage threshold (km²)', '0.25');
  Object.assign(retraced, await page.evaluate(() => ({ back: window.__terrainGot(),
    askedBack: window.GWT.engine.history().length - window.__mark })));
  check('terrain threshold: a new one traces the lines again on the page, with no request to the engine',
    retraced.asked === 0 && retraced.askedBack === 0 && retraced.areaKm2 === 2 &&
    retraced.got !== retraced.first && JSON.parse(retraced.got).parts.length <
      JSON.parse(retraced.first).parts.length,
    JSON.stringify([retraced.asked, retraced.askedBack, retraced.areaKm2]));
  check('terrain threshold: the lines, summary, captions and GeoJSON are those of an analysis at the new ' +
    'threshold, and back again those of the first',
    retraced.got === retraced.want && retraced.back === retraced.first &&
    retraced.caption.includes('where more than 2 km² drains'),
    JSON.stringify([retraced.caption, retraced.got.slice(0, 300), retraced.want.slice(0, 300)]));
  check('terrain threshold: of the figures, only the relief and the survey plan, which keeps clear of the ' +
    'lines, are drawn again, the relief with the lines and the caption at the new threshold',
    retraced.all.length === 7 && retraced.drawn.join() === retraced.all.join() && retraced.relief &&
    retraced.plan && retraced.figures.join() === retraced.all.slice(1, -1).join() &&
    retraced.shown.join() === retraced.all.join() && retraced.shownCaption === retraced.caption,
    JSON.stringify([retraced.all, retraced.drawn, retraced.relief, retraced.plan, retraced.figures,
      retraced.shown]));

  /* a threshold changed while the analysis runs is traced from its answer */
  await setField('Radius of the square shown (km)', '3');
  await page.evaluate(() => {
    window.__hold = true;
    window.__release = null;
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    return window.__until(() => window.__release);
  });
  /* the engine's workers, which the page started from gwt-worker.js, the
   * one that read the window now waiting for the analysis */
  const engineWorkers = () => page.workers().filter((w) => w.url().endsWith('/gwt-worker.js'));
  const waitingWorkers = engineWorkers().length;
  await setField('Drainage threshold (km²)', '1');
  const during = await page.evaluate(async () => {
    window.__hold = false;
    window.__release();
    const done = await window.__until(window.__settled);
    const s = window.GWT.app.terrainSession();
    return { done, asked: window.__asked.area, areaKm2: s.result.areaKm2, got: window.__terrainGot(),
      want: window.__terrainWant(1), ran: window.__lastTerrain() };
  });
  check('terrain threshold: one changed while the analysis runs is traced again from its answer',
    during.done && during.asked === 0.25 && during.areaKm2 === 1 && during.got === during.want &&
    JSON.stringify(during.ran) ===
      '[["readElevation","worker","done",true],["analyseTerrain","worker","done",true]]',
    JSON.stringify([during.done, during.asked, during.areaKm2, during.ran]));
  /* the worker that answered the analysis is stopped, and with it the
   * rest of the analysis, which an idle worker would keep */
  let answeredWorkers = engineWorkers().length;
  for (let waited = 0; waited < 3000 && answeredWorkers; waited += 50) {
    await new Promise((resolve) => setTimeout(resolve, 50));
    answeredWorkers = engineWorkers().length;
  }
  check('terrain analysis: the worker that read and analysed the window is stopped once it has answered',
    waitingWorkers === 1 && answeredWorkers === 0, JSON.stringify({ waitingWorkers, answeredWorkers }));

  /* an answer to a run dropped while it was out is not shown */
  const heldBack = await page.evaluate(async () => {
    window.__hold = true;
    window.__release = null;
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    await window.__until(() => window.__release);
    return true;
  });
  await setField('Source of the elevation model', 'srtm');
  const stale = await page.evaluate(async () => {
    window.__hold = false;
    const mark = window.GWT.engine.history().length;
    window.__release();
    await window.__until(() => window.GWT.engine.history().length > mark);
    await new Promise((resolve) => setTimeout(resolve, 100));
    const s = window.GWT.app.terrainSession();
    return { ran: window.__lastTerrain(), read: s.read, result: s.result, card: window.__card() };
  });
  check('terrain analysis: an answer to a run dropped since, by another source declared, is not shown',
    heldBack && stale.ran[1].join() === 'analyseTerrain,worker,done,true' && stale.read === null &&
    stale.result === null && !stale.card.read && !stale.card.running && !stale.card.bar &&
    !stale.card.disabled, JSON.stringify(stale));
  await setField('Source of the elevation model', 'detect');

  /* Cancel in the work bar, part way through a large window's analysis */
  await setField('Radius of the square shown (km)', '40');
  const halted = await page.evaluate(async () => {
    const app = window.GWT.app, stages = ['classes', 'fill', 'flow', 'flats', 'accumulate', 'drainage',
      'shading', 'curvature'].map((s) => window.GWT.core.phrase('terrain.stage_' + s));
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    let bar = null;
    await window.__until(() => {
      bar = document.querySelector('#work-status .work-bar[data-work="terrain"]');
      return bar && stages.indexOf(bar.querySelector('.work-detail').textContent) >= 0;
    });
    const shown = bar ? bar.querySelector('.work-detail').textContent : '';
    const pressed = performance.now();
    bar.querySelector('button').click();
    await window.__until(window.__settled, 5000);
    const stoppedIn = Math.round(performance.now() - pressed);
    await new Promise((resolve) => setTimeout(resolve, 100));
    const s = app.terrainSession();
    return { shown, stoppedIn, ran: window.__lastTerrain(), read: s.read, result: s.result,
      card: window.__card(), toasts: window.__toasts() };
  });
  check('terrain cancel: Cancel stops the analysis in the worker at once, and nothing of the run is kept',
    halted.shown !== '' && halted.stoppedIn < 1000 &&
    JSON.stringify(halted.ran) ===
      '[["readElevation","worker","done",true],["analyseTerrain","worker","cancelled",false]]' &&
    halted.read === null && halted.result === null && !halted.card.read && !halted.card.running &&
    !halted.card.bar && !halted.card.disabled && halted.card.refusals.length === 0 &&
    halted.toasts.some((t) => t.startsWith('The terrain analysis was stopped, and nothing of it is kept.')),
    JSON.stringify(halted));

  /* with no worker: the line before a run, the same answer from the page,
   * and a Cancel read between the read and the analysis */
  await setField('Radius of the square shown (km)', '3');
  const pageRun = await page.evaluate(async () => {
    const app = window.GWT.app, engine = window.GWT.engine;
    const inWorker = { card: window.__card(), mode: engine.mode() };
    engine.forcePage(true);
    app.render();
    const before = window.__card();
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    const running = window.__card();
    const done = await window.__until(window.__settled);
    const answer = { ran: window.__lastTerrain(), got: window.__terrainGot(), want: window.__terrainWant(1) };
    window.__cancelNow = true;
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    const cancelled = await window.__until(window.__settled);
    window.__cancelNow = false;
    await new Promise((resolve) => setTimeout(resolve, 300));
    const s = app.terrainSession();
    const after = { ran: window.__lastTerrain(), read: s.read, result: s.result, card: window.__card(),
      toasts: window.__toasts() };
    engine.forcePage(false);
    app.render();
    return { inWorker, before, reason: engine.unavailable(), running, done, answer, cancelled, after,
      back: window.__card() };
  });
  check('terrain page-only: with no worker the card says, before a run, that the page will be held',
    pageRun.inWorker.mode === 'worker' && pageRun.inWorker.card.pageOnly === null &&
    pageRun.before.pageOnly === 'This copy of the app has no background worker (forced), so the analysis ' +
      'will hold the page until it finishes.' && pageRun.running.pageOnly === null &&
    pageRun.back.pageOnly === null,
    JSON.stringify([pageRun.inWorker, pageRun.before, pageRun.running, pageRun.back]));
  check('terrain page-only: the page reads and analyses the window itself, to the same answer',
    pageRun.done && JSON.stringify(pageRun.answer.ran) ===
      '[["readElevation","page","done",true],["analyseTerrain","page","done",true]]' &&
    pageRun.answer.got === pageRun.answer.want && pageRun.answer.got === during.got,
    JSON.stringify([pageRun.answer.ran, pageRun.answer.got === pageRun.answer.want,
      pageRun.answer.got === during.got]));
  check('terrain page-only: a Cancel read between the read and the analysis stops it there, keeping nothing',
    pageRun.cancelled && JSON.stringify(pageRun.after.ran) ===
      '[["readElevation","page","done",true],["analyseTerrain","page","cancelled",false]]' &&
    pageRun.after.read === null && pageRun.after.result === null && !pageRun.after.card.read &&
    !pageRun.after.card.bar &&
    pageRun.after.toasts.some((t) => t.startsWith('The terrain analysis was stopped')),
    JSON.stringify(pageRun.after));

  /* a device that says it has little memory, asked before a large window */
  const memory = await page.evaluate(async () => {
    const app = window.GWT.app;
    const press = () => Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    const modal = () => {
      const box = document.querySelector('.modal-overlay .modal');
      return box ? { title: box.querySelector('h3').textContent,
        text: box.querySelector('.modal-body').textContent,
        buttons: Array.from(box.querySelectorAll('button')).map((b) => b.textContent) } : null;
    };
    const tap = (label) => Array.from(document.querySelectorAll('.modal-overlay button'))
      .find((b) => b.textContent === label).click();
    const setRadius = (km) => {
      const host = Array.from(document.querySelectorAll('[data-item="terrain"] label.field'))
        .find((f) => f.querySelector('.field-label').textContent === 'Radius of the square shown (km)');
      const input = host.querySelector('input');
      input.value = String(km);
      input.dispatchEvent(new Event('change'));
    };
    const marks = () => window.GWT.engine.history().length;
    const out = {};
    Object.defineProperty(navigator, 'deviceMemory', { value: 2, configurable: true });
    setRadius(45);
    const mark = marks();
    window.__slices = [];
    press();
    out.asked = modal();
    out.asking = { card: window.__card(), working: app.working('terrain'), slices: window.__slices.length };
    tap('Close');
    await new Promise((resolve) => setTimeout(resolve, 200));
    out.closed = { modal: modal(), card: window.__card(), requests: marks() - mark,
      slices: window.__slices.length };
    press();
    tap('Run it anyway');
    out.anyway = { modal: modal(), running: app.terrainSession().running };
    await window.__until(() => window.GWT.engine.history().length > mark || window.__settled());
    out.anyway.cells = app.terrainSession().read ? app.terrainSession().read.grid.rows *
      app.terrainSession().read.grid.cols : null;
    app.cancelWork('terrain');
    await window.__until(window.__settled);
    setRadius(3);
    press();
    out.small = { modal: modal(), running: app.terrainSession().running };
    await window.__until(window.__settled);
    out.small.result = !!app.terrainSession().result;
    Object.defineProperty(navigator, 'deviceMemory', { value: 4, configurable: true });
    setRadius(45);
    press();
    out.ample = { modal: modal(), running: app.terrainSession().running };
    app.cancelWork('terrain');
    await window.__until(window.__settled);
    delete navigator.deviceMemory;
    return out;
  });
  check('terrain memory: a device that says it has 2 GB or less is asked before a window of over a ' +
    'million cells, and nothing is read until it says to go on',
    JSON.stringify(memory.asked) === JSON.stringify({ title: 'This device may run short of memory',
      text: 'This device reports 2 GB of memory or less; a window this size may close the tab. Run it anyway?',
      buttons: ['×', 'Run it anyway', 'Close'] }) &&
    !memory.asking.working && !memory.asking.card.running && memory.asking.slices === 0 &&
    memory.closed.modal === null && memory.closed.requests === 0 && memory.closed.slices === 0 &&
    !memory.closed.card.read && !memory.closed.card.disabled,
    JSON.stringify([memory.asked, memory.asking, memory.closed]));
  check('terrain memory: told to go on it runs; a smaller window, or a device with more memory, is not asked',
    memory.anyway.modal === null && memory.anyway.running && memory.anyway.cells > 1000000 &&
    memory.small.modal === null && memory.small.running && memory.small.result &&
    memory.ample.modal === null && memory.ample.running,
    JSON.stringify([memory.anyway, memory.small, memory.ample]));

  // The figures on the card: each of the four drawn from the worker's
  // display layers by its builder in gwt-charts.js, and the lineament
  // candidates' map and rose (PLAN.md step 4.2), with the engine's captions
  // under each, and PNG and SVG buttons that save it under the name the
  // Python app gives its files; and the drainage lines and the candidates
  // saved as the GeoJSON the engine writes, told what the Python app tells
  // it. The
  // Copernicus licence's liability sentence is in small print under the
  // downloads when the files hold a Copernicus tile, and only then. Loading
  // a project, with a run still going, opening a sample and resetting the
  // workspace each drop the tiles, the card's settings and all made of
  // them, as loading a project drops them in the Python app.
  await setField('Radius of the square shown (km)', '3');
  await setField('Drainage threshold (km²)', '0.5');
  const drawn = await page.evaluate(async () => {
    const app = window.GWT.app;
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    const done = await window.__until(window.__settled);
    const s = app.terrainSession(), want = JSON.parse(window.__terrainWant(0.5));
    const layers = { relief: ['relief'], wetness: ['wetness'], curvature: ['profile', 'tangential'],
      directions: s.result.cfg.terrain.hillshade_panel_azimuths_deg.map((a) => 'hillshade-' + a),
      lineaments: ['lineaments'], rose: [], plan: ['plan'] };
    /* the lineament figures' captions, and the note they carry with the
     * caveat; the plan's, and its own note */
    const lineament = (name) => name === 'lineaments' || name === 'rose';
    const captions = Object.assign({}, want.captions, want.lineamentCaptions, want.planCaptions);
    const flat = (text) => String(text).replace(/\s+/g, ' ').trim();
    const label = app.store.get('site.community') || 'Site';
    const figures = Array.from(document.querySelectorAll('[data-item="terrain"] figure.figure')).map((node) => {
      const svg = node.querySelector('svg');
      const name = Object.keys(s.figures || {}).find((key) => s.figures[key] === svg) || null;
      const texts = Array.from(svg.querySelectorAll('text')).map((t) => t.textContent);
      const note = (kind) => flat(Array.from(svg.querySelectorAll(`text[data-note="${kind}"]`))
        .map((t) => t.textContent).join(' '));
      return { name, caption: (node.querySelector('figcaption span') || {}).textContent,
        want: (name === 'plan' ? want.planCaptions : lineament(name) ? want.lineamentCaptions : want.captions)[name],
        layers: Array.from(svg.querySelectorAll('image'))
          .map((image) => image.getAttribute('data-layer')).join() === (layers[name] || []).join(),
        title: flat(texts.join(' ')).includes(flat(captions['title_' + name])),
        credit: note('credit') === flat(s.read.figureCredit),
        caveat: note('caveat') === flat(lineament(name) ? captions.figure_note + ' ' + captions.figure_caveat
          : name === 'plan' ? captions.plan_note + ' ' + captions.figure_caveat : captions.figure_caveat),
        stars: svg.querySelectorAll('[data-site]').length === (layers[name] || []).length &&
          (name === 'rose' || texts.includes(label)),
        buttons: Array.from(node.querySelectorAll('.figure-actions button')).map((b) => b.textContent).join() };
    });
    const count = (text) => Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .filter((b) => b.textContent === text).length;
    const rows = Array.from(document.querySelectorAll('[data-item="terrain"] table.data tbody tr'))
      .map((tr) => tr.querySelector('td').textContent);
    return { done, figures, ran: window.__lastTerrain(), readNotice: s.read.notice,
      candidates: s.result.lineaments.lineaments.length,
      plan: [s.result.plan.basis, s.result.plan.lines.length, s.result.plan.soundings.length],
      table: rows.join() === s.result.plan.soundings.map((x) => 'VES ' + x.id).join(),
      notices: document.querySelectorAll('[data-item="terrain"] .terrain-notice').length,
      geojson: [count('Drainage lines (GeoJSON)'), count('Lineament candidates (GeoJSON)'),
        count('Survey plan (GPX)'), count('Survey plan (GeoLibre)')].join() };
  });
  check('terrain figures on the card: the four, the lineament candidates\' map and rose and the survey plan, ' +
    'each drawn from the worker\'s answer with its layers, title, credit, caveat and the site starred on every ' +
    'map, and the engine\'s captions under it',
    drawn.done && JSON.stringify(drawn.ran) ===
      '[["readElevation","worker","done",true],["analyseTerrain","worker","done",true]]' &&
    drawn.candidates > 0 &&
    drawn.figures.map((f) => f.name).join() === 'relief,wetness,curvature,directions,lineaments,rose,plan' &&
    drawn.figures.every((f) => f.caption === f.want && f.layers && f.title && f.credit && f.caveat && f.stars),
    JSON.stringify([drawn.done, drawn.ran, drawn.candidates, drawn.figures]));
  check('terrain figures on the card: each with its PNG and SVG buttons, the lines\' and the candidates\' ' +
    'GeoJSON and the plan\'s GPX and GeoLibre project after them, and no liability sentence for a set holding ' +
    'no Copernicus tile',
    drawn.figures.every((f) => f.buttons === 'PNG,SVG') && drawn.geojson === '1,1,1,1' &&
    drawn.readNotice === null && drawn.notices === 0, JSON.stringify([drawn.figures.map((f) => f.buttons),
      drawn.geojson, drawn.readNotice, drawn.notices]));
  check('terrain figures on the card: the valley is found only 1.8 km south of the site, beyond the 500 m it ' +
    'serves, so the survey plan crosses the strike through the site and proposes no sounding',
    drawn.plan.join() === 'strike,1,0' && drawn.table, JSON.stringify([drawn.plan, drawn.table]));

  /* the theme changed to light and back: the figures are drawn again in
   * the page's new colours each time, as every other figure is */
  const themed = await page.evaluate(() => {
    const app = window.GWT.app, s = app.terrainSession(), was = app.store.get('theme', 'dark');
    const svgs = () => Array.from(document.querySelectorAll('[data-item="terrain"] figure.figure > svg'));
    const grounds = () => svgs().map((svg) => svg.querySelector('rect').getAttribute('fill')).join();
    const toggle = (to) => {
      for (let n = 0; n < 3 && app.store.get('theme') !== to; n++) {
        document.querySelector('button[title="Switch theme"]').click();
      }
    };
    const dark = { svgs: svgs(), grounds: grounds() };
    toggle('light');
    const light = { svgs: svgs(), grounds: grounds(), surface: window.GWT.charts.palette().surface };
    toggle(was);
    const back = { svgs: svgs(), grounds: grounds() };
    const kept = (shown) => shown.map((svg) => Object.keys(s.figures || {}).find((key) => s.figures[key] === svg))
      .join();
    return { was, light: light.grounds, dark: dark.grounds, back: back.grounds,
      redrawn: [light.svgs.length, light.svgs.filter((svg, i) => svg !== dark.svgs[i]).length,
        back.svgs.filter((svg, i) => svg !== light.svgs[i]).length].join(), kept: kept(back.svgs),
      painted: light.grounds === Array(7).fill(light.surface).join() && light.grounds !== dark.grounds &&
        back.grounds === dark.grounds };
  });
  check('terrain figures on the card: a new theme draws them again in its colours',
    themed.was === 'dark' && themed.redrawn === '7,7,7' &&
    themed.kept === 'relief,wetness,curvature,directions,lineaments,rose,plan' && themed.painted,
    JSON.stringify(themed));

  /* what each button saves, kept instead of handed to the browser */
  const saved = await page.evaluate(async () => {
    const support = window.GWT.support, s = window.GWT.app.terrainSession();
    const want = JSON.parse(window.__terrainWant(0.5));
    const got = [];
    window.__download = support.download;
    support.download = (name, data, mime) => { got.push({ name, data, mime }); };
    const host = document.querySelector('[data-item="terrain"]');
    const figures = Array.from(host.querySelectorAll('figure.figure'));
    for (const node of figures) {
      for (const label of ['PNG', 'SVG']) {
        const count = got.length;
        Array.from(node.querySelectorAll('.figure-actions button')).find((b) => b.textContent === label).click();
        await window.__until(() => got.length > count, 20000);
      }
    }
    for (const text of ['Drainage lines (GeoJSON)', 'Lineament candidates (GeoJSON)', 'Survey plan (GPX)',
      'Survey plan (GeoLibre)']) {
      const lineButton = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === text);
      if (lineButton) lineButton.click();
    }
    support.download = window.__download;
    const out = { names: got.map((g) => g.name), figures: [] };
    for (let i = 0; i < figures.length; i++) {
      const svg = figures[i].querySelector('svg'), png = got[2 * i].data, text = got[2 * i + 1].data;
      /* the PNG at twice the figure's size, its maps painted, not the
       * figure's ground alone */
      const bitmap = await createImageBitmap(png);
      const canvas = document.createElement('canvas');
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const g = canvas.getContext('2d');
      g.drawImage(bitmap, 0, 0);
      const ground = Array.from(g.getImageData(4, 4, 1, 1).data);
      const painted = Array.from(svg.querySelectorAll('image')).map((image) => {
        const box = ['x', 'y', 'width', 'height'].map((key) => Number(image.getAttribute(key)) * 2);
        const data = g.getImageData(Math.round(box[0]) + 2, Math.round(box[1]) + 2,
          Math.round(box[2]) - 4, Math.round(box[3]) - 4).data;
        let count = 0;
        for (let k = 0; k < data.length; k += 4) {
          if (Math.abs(data[k] - ground[0]) + Math.abs(data[k + 1] - ground[1]) +
              Math.abs(data[k + 2] - ground[2]) > 24) count++;
        }
        return Math.round(1000 * count / (data.length / 4)) / 1000;
      });
      const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
      /* the SVG as the page draws it: the same rasters and the same words */
      const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
      const hrefs = (root) => Array.from(root.querySelectorAll('image')).map((image) => image.getAttribute('href'));
      const words = (root) => Array.from(root.querySelectorAll('text')).map((t) => t.textContent).join('|');
      /* the rose is drawn, not painted from a raster: its petals are what
       * it shows */
      const rose = svg.querySelectorAll('path[data-petal]').length;
      out.figures.push({
        png: [png.type, bitmap.width, bitmap.height, viewBox[2] * 2, viewBox[3] * 2], painted, rose,
        svg: [got[2 * i + 1].mime, doc.documentElement.nodeName, !doc.querySelector('parsererror'),
          (hrefs(doc).length > 0 || rose > 0) && hrefs(doc).join() === hrefs(svg).join(), words(doc) === words(svg)],
      });
    }
    const lines = got.slice(2 * figures.length)[0] || {}, parsed = JSON.parse(lines.data || '{"features":[]}');
    out.geojson = { mime: lines.mime, same: lines.data === s.result.geojson && lines.data === want.geojson,
      features: parsed.features.length === s.result.parts.length && parsed.features.length > 0,
      attribution: parsed.attribution === s.read.figureCredit, notice: 'notice' in parsed,
      description: parsed.description === want.captions.geojson_description };
    const candidates = got.slice(2 * figures.length)[1] || {};
    const found = JSON.parse(candidates.data || '{"features":[]}');
    out.lineaments = { mime: candidates.mime,
      same: candidates.data === s.result.lineamentGeojson && candidates.data === want.lineamentGeojson,
      features: found.features.length === s.result.lineaments.lineaments.length && found.features.length > 0,
      attribution: found.attribution === s.read.figureCredit, notice: 'notice' in found,
      described: found.description.includes('not confirmed by geophysics') };
    /* the survey plan's GPX, as the engine writes it, and its GeoLibre
     * project, opening on the service radius */
    const gpx = got.slice(2 * figures.length)[2] || {}, plan = s.result.plan;
    const doc = new DOMParser().parseFromString(gpx.data || '', 'application/xml');
    const ns = 'http://www.topografix.com/GPX/1/1';
    out.gpx = { name: gpx.name, mime: gpx.mime, same: gpx.data === s.result.planGpx && gpx.data === want.planGpx,
      parsed: !doc.querySelector('parsererror') && doc.documentElement.namespaceURI === ns,
      waypoints: doc.getElementsByTagNameNS(ns, 'wpt').length === 1 + plan.soundings.length + 2 * plan.lines.length,
      stations: doc.getElementsByTagNameNS(ns, 'rtept').length ===
        plan.lines.reduce((n, line) => n + line.last - line.first + 1, 0) };
    const project = got.slice(2 * figures.length)[3] || {};
    const layers = JSON.parse(project.data || '{"layers":[]}').layers.map((layer) => layer.name);
    out.geolibre = { name: project.name, layers: layers.join(), plan: s.result.planGeoJson === want.planGeoJson };
    return out;
  });
  check('terrain downloads: each figure saves as a PNG with its maps painted and an SVG of what the page ' +
    'draws, under the Python app\'s names',
    saved.names.join() === ['relief', 'wetness', 'curvature', 'directions', 'lineaments', 'rose', 'plan']
      .map((n) => `terrain_${n}.png,terrain_${n}.svg`).join() + ',drainage_lines.geojson,lineament_candidates.geojson' +
      ',survey_plan.gpx,survey_plan.geolibre.json' &&
    saved.figures.every((f) => f.png[0] === 'image/png' && f.png[1] === f.png[3] && f.png[2] === f.png[4] &&
      (f.painted.length > 0 || f.rose > 0) && f.painted.every((share) => share > 0.6) &&
      JSON.stringify(f.svg) === '["image/svg+xml;charset=utf-8","svg",true,true,true]'),
    JSON.stringify([saved.names, saved.figures]));
  check('terrain downloads: the drainage lines save as the GeoJSON the engine writes, credited and described ' +
    'as the Python app has it',
    JSON.stringify(saved.geojson) === JSON.stringify({ mime: 'application/geo+json', same: true, features: true,
      attribution: true, notice: false, description: true }), JSON.stringify(saved.geojson));
  check('terrain downloads: the lineament candidates save as the GeoJSON the engine writes, credited and ' +
    'described as not confirmed by geophysics',
    JSON.stringify(saved.lineaments) === JSON.stringify({ mime: 'application/geo+json', same: true, features: true,
      attribution: true, notice: false, described: true }), JSON.stringify(saved.lineaments));
  check('terrain downloads: the survey plan saves as the GPX the engine writes, a waypoint at the site, each ' +
    'sounding and each line\'s ends and a route point at each station, and as a GeoLibre project of its layers',
    JSON.stringify(saved.gpx) === JSON.stringify({ name: 'survey_plan.gpx', mime: 'application/gpx+xml',
      same: true, parsed: true, waypoints: true, stations: true }) &&
    JSON.stringify(saved.geolibre) === JSON.stringify({ name: 'survey_plan.geolibre.json',
      layers: 'Service radius,Profiling lines,Profile stations,Site', plan: true }),
    JSON.stringify([saved.gpx, saved.geolibre]));

  /* the site moved 2.8 km south, beside the stretch of the valley the
   * candidates hold: the plan crosses it, with three soundings listed
   * under the figure and saved as the engine writes them */
  const beside = await page.evaluate(async () => {
    const app = window.GWT.app, store = app.store, support = window.GWT.support;
    store.set('site.northing', 8.475);
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    const done = await window.__until(window.__settled);
    const s = app.terrainSession(), plan = s.result.plan, want = JSON.parse(window.__terrainWant(0.5));
    const host = document.querySelector('[data-item="terrain"]');
    const figure = s.figures && s.figures.plan;
    const rows = Array.from(host.querySelectorAll('table.data tbody tr')).map((tr) =>
      Array.from(tr.querySelectorAll('td')).map((td) => td.textContent));
    const got = [];
    const download = support.download;
    support.download = (name, data, mime) => { got.push({ name, data, mime }); };
    for (const text of ['Survey plan (GPX)', 'Survey plan (GeoLibre)']) {
      Array.from(host.querySelectorAll('button')).find((b) => b.textContent === text).click();
    }
    support.download = download;
    const ns = 'http://www.topografix.com/GPX/1/1';
    const doc = new DOMParser().parseFromString(got[0].data, 'application/xml');
    const names = Array.from(doc.getElementsByTagNameNS(ns, 'wpt')).map((w) =>
      w.getElementsByTagNameNS(ns, 'name')[0].textContent);
    const project = JSON.parse(got[1].data);
    store.set('site.northing', 8.5);
    return { done, plan: [plan.basis, plan.lines.length, plan.soundings.length].join(),
      same: s.result.planGpx === want.planGpx && s.result.planGeoJson === want.planGeoJson &&
        JSON.stringify(s.result.planCaptions) === JSON.stringify(want.planCaptions),
      figure: figure ? [figure.querySelectorAll('[data-plan-line]').length,
        figure.querySelectorAll('circle[data-sounding]').length, figure.querySelectorAll('[data-radius]').length,
        figure.querySelectorAll('circle[data-station]').length].join() : null,
      stations: plan.lines[0].last - plan.lines[0].first + 1,
      rows: rows.map((row) => row[0]).join(), described: rows.every((row) => row[5].includes('AB/2 to 120 m')),
      names: names.join(), label: store.get('site.community') || 'Site',
      layers: project.layers.map((layer) => layer.name).join() };
  });
  check('terrain survey plan: beside the valley the plan crosses it with a line and three soundings, as the ' +
    'engine lays it, drawn, listed under the figure and saved as GPX and a GeoLibre project',
    beside.done && beside.plan === 'candidates,1,3' && beside.same &&
    beside.figure === `1,3,1,${beside.stations}` && beside.rows === 'VES 1,VES 2,VES 3' && beside.described &&
    beside.names === `${beside.label},VES 1,VES 2,VES 3,Line 1 start,Line 1 end` &&
    beside.layers === 'Lineament candidates,Service radius,Profiling lines,Profile stations,Proposed soundings,Site',
    JSON.stringify(beside));

  /* the desk study (PLAN.md step 4.4) beside the valley: the eleventh
   * document carries the pre-field stamp after its cover, the terrain the
   * card found and its plan's soundings, and the figures the card names,
   * drawn again for paper; with the site moved off the plan it leaves the
   * terrain out and says so */
  const desk = await page.evaluate(async () => {
    const app = window.GWT.app, store = app.store, support = window.GWT.support, C = window.GWT.core;
    const host = Array.from(document.querySelectorAll('.card')).find((card) =>
      (card.querySelector('h2, h3') || {}).textContent === 'Desk study');
    const button = host && Array.from(host.querySelectorAll('button'))
      .find((b) => b.textContent === 'Build the desk study (.docx)');
    const build = async () => {
      const got = [];
      const download = support.download;
      support.download = (name, data) => { got.push({ name, data }); };
      try {
        await app.buildDeskStudy(button);
      } finally {
        support.download = download;
      }
      if (!got.length) return null;
      const bytes = new Uint8Array(await got[0].data.arrayBuffer());
      const files = await support.unzip(bytes);
      const xml = new DOMParser().parseFromString(new TextDecoder().decode(files['word/document.xml']),
        'application/xml');
      const text = Array.from(xml.getElementsByTagName('w:p')).map((para) =>
        Array.from(para.getElementsByTagName('w:t')).map((t) => t.textContent).join('')).join('\n');
      return { name: got[0].name, text: text,
        media: Object.keys(files).filter((n) => n.startsWith('word/media/')).length };
    };
    store.set('site.northing', 8.475);
    const here = await build();
    store.set('site.northing', 8.5);
    const moved = await build();
    const s = app.terrainSession();
    return { card: !!button, here: here && { name: here.name, media: here.media,
      stamp: here.text.includes(C.phrase('desk_study.stamp_title')),
      order: here.text.indexOf(C.phrase('desk_study.stamp_title')) < here.text.indexOf('Executive Summary'),
      terrain: here.text.includes(C.phrase('desk_study.terrain_heading')) &&
        !here.text.includes(C.phrase('desk_study.terrain_elsewhere')),
      soundings: s.result.desk.soundings.every((row) => here.text.includes(row[4])),
      sounded: s.result.desk.soundings.length, rose: s.result.lineaments.lineaments.length > 0 },
      moved: moved && moved.text.includes(C.phrase('desk_study.terrain_elsewhere')) };
  });
  /* the area maps (the locator, the aquifer and the geology maps), then the
   * relief, the candidates, their rose and the plan */
  check('desk study: beside the valley it saves Desk_Study.docx, stamped pre-field after the cover, with the ' +
    'terrain, the plan\'s soundings and the figures the card names; with the site moved off the plan it leaves ' +
    'the terrain out and says so',
    desk.card && !!desk.here && desk.here.name === 'Desk_Study.docx' && desk.here.stamp && desk.here.order &&
    desk.here.terrain && desk.here.sounded === 3 && desk.here.soundings &&
    desk.here.media === 3 + 2 + (desk.here.rose ? 1 : 0) + 1 && desk.moved,
    JSON.stringify(desk));

  /* a Copernicus set: the three tiles around a missing fourth, declared
   * Copernicus GLO-30, at 8 N, 12 W */
  const holesSite = () => page.evaluate(() => {
    const store = window.GWT.app.store;
    store.set('site.easting', -12.0);
    store.set('site.northing', 8.0);
    store.set('site.utm_zone', null);
  });
  const holesOnCard = async () => {
    await holesSite();
    await drop(holes);
    await opened(3);
    await setField('Source of the elevation model', 'copernicus_glo30');
    await setField('Radius of the square shown (km)', '15');
  };
  /* the card's state, and whether the session is a fresh one */
  const cleared = () => page.evaluate(() => {
    const app = window.GWT.app, s = app.terrainSession(), cfg = app.config().terrain;
    const host = document.querySelector('[data-item="terrain"]');
    const value = (label) => Array.from(host.querySelectorAll('label.field'))
      .find((f) => f.querySelector('.field-label').textContent === label).querySelector('input, select').value;
    return {
      session: s.files.length === 0 && s.opened.size === 0 && s.read === null && s.result === null &&
        s.figures === null && s.radiusKm === null && s.areaKm2 === null && s.declared === 'detect' &&
        !s.running && s.refusal === '',
      card: [host.querySelectorAll('.terrain-file').length, host.querySelectorAll('figure.figure').length,
        !!host.querySelector('.terrain-read'), !!host.querySelector('.terrain-notice'),
        !!document.querySelector('#work-status .work-bar[data-work="terrain"]')].join(),
      fields: [value('Radius of the square shown (km)') === String(cfg.analysis_radius_km),
        value('Drainage threshold (km²)') === String(cfg.drainage_area_km2),
        value('Source of the elevation model') === 'detect'].join(),
    };
  });
  const runToEnd = () => page.evaluate(async () => {
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    await window.__until(window.__settled);
    return !!window.GWT.app.terrainSession().result;
  });
  await removeAll();
  await holesOnCard();
  const licensed = await page.evaluate(async () => {
    const C = window.GWT.core, s = () => window.GWT.app.terrainSession();
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    await window.__until(window.__settled);
    const host = document.querySelector('[data-item="terrain"]');
    const notices = Array.from(host.querySelectorAll('.terrain-notice'));
    const lines = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === 'Drainage lines (GeoJSON)');
    const figures = Array.from(host.querySelectorAll('figure.figure'));
    const flat = (text) => String(text).replace(/\s+/g, ' ').trim();
    return {
      figures: figures.length, liability: C.phrase('terrain.copernicus_liability'),
      notices: notices.map((n) => (n.querySelector('small') || {}).textContent || null),
      underDownloads: !!lines && notices.length === 1 &&
        !!(lines.compareDocumentPosition(notices[0]) & Node.DOCUMENT_POSITION_FOLLOWING) &&
        figures.every((f) => !!(f.compareDocumentPosition(notices[0]) & Node.DOCUMENT_POSITION_FOLLOWING)),
      credit: s().read.figureCredit.includes(C.phrase('terrain.credit_copernicus_modified')) &&
        figures.every((f) => flat(Array.from(f.querySelectorAll('text[data-note="credit"]'))
          .map((t) => t.textContent).join(' ')) === flat(s().read.figureCredit)),
      geojson: JSON.parse(s().result.geojson).notice, lineaments: JSON.parse(s().result.lineamentGeojson).notice,
      drawn: 5 + (s().result.lineaments.lineaments.length ? 1 : 0),
    };
  });
  check('terrain figures on the card: a Copernicus set\'s liability sentence is in small print under the ' +
    'downloads, once, and its credit inside every figure and in both GeoJSON files',
    licensed.figures === licensed.drawn && JSON.stringify(licensed.notices) === JSON.stringify([licensed.liability]) &&
    licensed.underDownloads && licensed.credit && licensed.geojson === licensed.liability &&
    licensed.lineaments === licensed.liability, JSON.stringify(licensed));

  /* A file removed or added, or the source put in other words, after a
   * run: what was read and drawn from the files as they were is taken
   * away at once, before anything is pressed again. */
  const takenAway = () => page.evaluate(() => {
    const s = window.GWT.app.terrainSession(), host = document.querySelector('[data-item="terrain"]');
    return [s.read === null, s.result === null, s.figures === null, !host.querySelector('.terrain-read'),
      host.querySelectorAll('figure.figure').length === 0, !host.querySelector('.terrain-notice'),
      !document.querySelector('#work-status .work-bar[data-work="terrain"]')].join();
  });
  const removeOne = (name) => page.evaluate((file) => Array.from(document.querySelectorAll(
    `[data-item="terrain"] .terrain-file[data-file="${file}"] button`)).find((b) => b.textContent === 'Remove')
    .click(), name);
  const changed = {};
  await removeOne(holes[2].name);
  changed.removed = { files: (await listed()).length, card: await takenAway() };
  await drop([holes[2]]);
  await opened(3);
  changed.ranBeforeAdding = await runToEnd();
  await drop([holes[2]]);
  changed.added = await takenAway();
  await opened(3);
  await setField('Source of the elevation model', 'other');
  await setField('The source, in your own words', 'a survey of our own');
  changed.ranBeforeWords = await runToEnd();
  await setField('The source, in your own words', 'a survey of the district');
  changed.words = await takenAway();
  const gone = 'true,true,true,true,true,true,true';
  check('terrain clearing: a file removed, a file added, or the source put in other words takes the read ' +
    'and the figures away at once',
    changed.removed.files === 2 && changed.removed.card === gone && changed.ranBeforeAdding &&
    changed.added === gone && changed.ranBeforeWords && changed.words === gone, JSON.stringify(changed));

  /* the same tiles left undeclared: some of the window is sea in a file of
   * unstated source, which the GeoJSON's description says, as the engine
   * writes it with the sea it counts itself */
  await setField('Source of the elevation model', 'detect');
  const undeclared = await page.evaluate(async () => {
    const C = window.GWT.core, s = () => window.GWT.app.terrainSession();
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    const done = await window.__until(window.__settled);
    const result = s().result, want = JSON.parse(window.__terrainWant(result.areaKm2)).geojson;
    return { done, seaClean: s().read.grid.seaClean, seaCells: result.seaCells, same: result.geojson === want,
      unstated: JSON.parse(result.geojson).description.endsWith(C.phrase('terrain.geojson_sea_unstated',
        { level: result.cfg.terrain.sea_level_m })) };
  });
  check('terrain downloads: the GeoJSON of a set of unstated source with sea in its window says so, as the ' +
    'engine writes it',
    undeclared.done && undeclared.seaClean === false && undeclared.seaCells > 0 && undeclared.same &&
    undeclared.unstated, JSON.stringify(undeclared));

  /* Cancel while the page is still reading the blocks out of the files,
   * each read made slow: the card says at once that nothing is running,
   * and no read is started after the one under way */
  const midRead = await page.evaluate(async () => {
    const C = window.GWT.core, app = window.GWT.app, s = app.terrainSession();
    const found = s.files.map((file) => s.opened.get(file).found);
    const plan = C.planElevationWindow(found, C.windowCentre(app.store.get('site'), app.siteLatLon(), found),
      15, app.config(), null, ['detect', '']);
    const reads = [], arrayBuffer = Blob.prototype.arrayBuffer;
    Blob.prototype.arrayBuffer = function () {
      reads.push(performance.now());
      const bytes = arrayBuffer.call(this);
      return new Promise((resolve) => setTimeout(resolve, 1500)).then(() => bytes);
    };
    try {
      Array.from(document.querySelectorAll('[data-item="terrain"] button'))
        .find((b) => b.textContent === 'Analyse the terrain').click();
      let bar = null;
      await window.__until(() => (bar = document.querySelector('#work-status .work-bar[data-work="terrain"]')));
      const pressed = reads.length;
      bar.querySelector('button').click();
      await new Promise((resolve) => setTimeout(resolve, 100));
      const card = window.__card(), started = reads.length;
      await new Promise((resolve) => setTimeout(resolve, 2000));
      return { reads: C.elevationBlockRanges(plan).length, pressed, started, after: reads.length, card,
        later: window.__card(), read: s.read, result: s.result, running: s.running,
        toasts: window.__toasts().filter((t) => t.startsWith('The terrain analysis was stopped')).length };
    } finally {
      Blob.prototype.arrayBuffer = arrayBuffer;
    }
  });
  check('terrain cancel: Cancel while the page reads the files clears the card at once, and no further read ' +
    'is made',
    midRead.reads > 1 && midRead.pressed === 1 && midRead.started === 1 && midRead.after === 1 &&
    !midRead.card.running && !midRead.card.disabled && !midRead.card.bar && !midRead.card.read &&
    !midRead.later.running && !midRead.later.disabled && midRead.read === null && midRead.result === null &&
    !midRead.running && midRead.toasts > 0, JSON.stringify(midRead));

  /* the worker finds no memory for the analysis: the error Chromium
   * throws then, thrown in the real worker as the analysis starts, is
   * taken as the worker stopping, which the card says in its sentence
   * under the read report, and the worker is let go */
  await page.evaluate(() => {
    window.__hold = true;
    window.__release = null;
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    return window.__until(() => window.__release);
  });
  await engineWorkers().pop().evaluate(() => {
    self.GWT.core.analyseTerrain = () => {
      throw new RangeError('Array buffer allocation failed');
    };
  });
  const starved = await page.evaluate(async () => {
    window.__hold = false;
    window.__release();
    const done = await window.__until(window.__settled);
    /* the bar goes at the next frame */
    await new Promise((resolve) => setTimeout(resolve, 100));
    const s = window.GWT.app.terrainSession();
    return { done, card: window.__card(), ran: window.__lastTerrain(), read: !!s.read, result: s.result };
  });
  let starvedWorkers = engineWorkers().length;
  for (let waited = 0; waited < 3000 && starvedWorkers; waited += 50) {
    await new Promise((resolve) => setTimeout(resolve, 50));
    starvedWorkers = engineWorkers().length;
  }
  check('terrain analysis: a worker short of memory for it is stopped, and the card says so in its sentence, ' +
    'under the read report',
    starved.done && JSON.stringify(starved.card.refusals) === JSON.stringify(['The background engine stopped ' +
      'while working out the terrain, most likely for lack of memory; try a smaller radius.']) &&
    starved.card.read && starved.read && starved.result === null && !starved.card.bar && !starved.card.running &&
    !starved.card.disabled && JSON.stringify(starved.ran) ===
      '[["readElevation","worker","done",true],["analyseTerrain","worker","failed",true]]' &&
    starvedWorkers === 0, JSON.stringify({ ...starved, starvedWorkers }));

  /* two tiles that disagree where they overlap: the worker's read refuses
   * them, in the engine's words for the same files read whole */
  await removeAll();
  await page.evaluate(() => {
    const store = window.GWT.app.store;
    store.set('site.easting', -12.4967);
    store.set('site.northing', 8.7447);
    store.set('site.utm_zone', null);
  });
  await drop(overlap);
  await opened(2);
  await setField('Radius of the square shown (km)', '1');
  const disagree = await page.evaluate(async (list) => {
    const C = window.GWT.core, app = window.GWT.app, cfg = app.config();
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    const done = await window.__until(window.__settled);
    await new Promise((resolve) => setTimeout(resolve, 100));
    const whole = {};
    list.forEach((f) => { whole[f.name] = new Uint8Array(f.bytes); });
    const found = list.map((f) => C.elevationFile(f.name, whole[f.name].length, [[0, whole[f.name]]]));
    const plan = C.planElevationWindow(found, C.windowCentre(app.store.get('site'), app.siteLatLon(), found), 1,
      cfg, null, ['detect', '']);
    const blocks = plan.blocks.map((b) => (b.length
      ? whole[plan.files[b.file].name].slice(b.offset, b.offset + b.length) : null));
    let want = '';
    try {
      C.readElevationWindow(plan, blocks, cfg, null);
    } catch (e) {
      want = e.message;
    }
    return { done, want, card: window.__card(), ran: window.__lastTerrain().pop() };
  }, carried(overlap));
  check('terrain card: a read the worker refuses is said on the card in the engine\'s words',
    disagree.done && disagree.want.includes('at 3 shared cells, by up to 1.20 m') &&
    JSON.stringify(disagree.card.refusals) === JSON.stringify([disagree.want]) && !disagree.card.read &&
    !disagree.card.bar && !disagree.card.running && !disagree.card.disabled &&
    disagree.ran.join() === 'readElevation,worker,failed,true', JSON.stringify(disagree));
  await removeAll();
  await holesOnCard();

  /* a project loaded while a run is out: the run is stopped and its answer
   * dropped; then a sample opened, and the workspace reset, each with an
   * analysis on show */
  const onLoad = await page.evaluate(async () => {
    const app = window.GWT.app, engine = window.GWT.engine, before = app.terrainSession();
    window.__hold = true;
    window.__release = null;
    Array.from(document.querySelectorAll('[data-item="terrain"] button'))
      .find((b) => b.textContent === 'Analyse the terrain').click();
    await window.__until(() => window.__release);
    const running = before.running && app.working('terrain');
    await app.loadProject(JSON.stringify(app.projectPayload()));
    window.__hold = false;
    const mark = engine.history().length;
    window.__release();
    await window.__until(() => engine.history().length > mark);
    await new Promise((resolve) => setTimeout(resolve, 200));
    return { running, replaced: app.terrainSession() !== before, stopped: !before.running,
      ran: window.__lastTerrain()[1], nav: app.store.get('nav') };
  });
  const afterLoad = await cleared();
  await holesOnCard();
  const sampled = { ran: await runToEnd() };
  await page.evaluate(() => window.GWT.app.loadSample('dr_timbo'));
  const afterSample = await cleared();
  await holesOnCard();
  const continued = { ran: await runToEnd() };
  Object.assign(continued, await page.evaluate(async () => {
    const app = window.GWT.app, before = app.terrainSession();
    await app.continueHere();
    if (app.store.get('nav') !== 'site') app.goto('site');
    return { replaced: app.terrainSession() !== before };
  }));
  const afterContinue = await cleared();
  await holesOnCard();
  await setField('Drainage threshold (km²)', '2');
  const reset = { ran: await runToEnd() };
  Object.assign(reset, await page.evaluate(async () => {
    const app = window.GWT.app, before = app.terrainSession();
    app.goto('settings');
    Array.from(document.querySelectorAll('#page-host button')).find((b) => b.textContent === 'Reset everything')
      .click();
    Array.from(document.querySelectorAll('.modal-overlay button')).find((b) => b.textContent === 'Reset').click();
    const replaced = await window.__until(() => app.terrainSession() !== before, 10000);
    app.goto('site');
    return { replaced, nav: app.store.get('nav') };
  }));
  const afterReset = await cleared();
  check('terrain clearing: loading a project drops the tiles, the card\'s settings and the analysis, and ' +
    'stops a run going, whose answer is not shown',
    onLoad.running && onLoad.replaced && onLoad.stopped && onLoad.nav === 'site' &&
    JSON.stringify(onLoad.ran) === '["analyseTerrain","worker","done",true]' && afterLoad.session &&
    afterLoad.card === '0,0,false,false,false' && afterLoad.fields === 'true,true,true',
    JSON.stringify([onLoad, afterLoad]));
  check('terrain clearing: opening a sample, and resetting the workspace, drop the tiles, the settings and the ' +
    'analysis on show',
    sampled.ran && afterSample.session && afterSample.card === '0,0,false,false,false' &&
    afterSample.fields === 'true,true,true' && reset.ran && reset.replaced && afterReset.session &&
    afterReset.card === '0,0,false,false,false' && afterReset.fields === 'true,true,true',
    JSON.stringify([sampled, afterSample, reset, afterReset]));
  check('terrain clearing: taking the saving over from another tab drops the tiles, the settings and the ' +
    'analysis on show, as opening another project does',
    continued.ran && continued.replaced && afterContinue.session &&
    afterContinue.card === '0,0,false,false,false' && afterContinue.fields === 'true,true,true',
    JSON.stringify([continued, afterContinue]));

  await removeAll();
  await page.evaluate((kept) => {
    Blob.prototype.slice = window.__slice;
    window.GWT.engine.analyseTerrain = window.__analyseTerrain;
    const store = window.GWT.app.store;
    Object.keys(kept).forEach((key) => store.set('site.' + key, kept[key]));
  }, keptTerrain);

  check('no console errors', consoleErrors.length === 0,
    consoleErrors.slice(0, 10).join('\n     '));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

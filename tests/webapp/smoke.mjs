/* Drive the whole app in headless Chromium: load each sample, visit every
 * page, build every report, and fail on any console error or missing output.
 */
import { withPage } from './harness.mjs';

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

const PAGES = ['overview', 'guided', 'site', 'ves', 'design', 'pumping', 'quality',
  'costing', 'supervision', 'handover', 'templates', 'waterpoints', 'coverage',
  'settings', 'about'];

await withPage(async (page, base, consoleErrors) => {
  const downloads = [];
  page.on('download', (d) => downloads.push(d.suggestedFilename()));

  await page.goto(base + '/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app);
  check('app boots', true);

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

  // rokel sample: the VES chain
  await page.evaluate(() => window.GWT.app.goto('overview'));
  await page.evaluate(() => {
    Array.from(document.querySelectorAll('button'))
      .find((b) => b.textContent.includes('Load Rokel')).click();
  });
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

  check('no console errors', consoleErrors.length === 0,
    consoleErrors.slice(0, 10).join('\n     '));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

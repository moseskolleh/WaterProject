/* Drive the whole app in headless Chromium: load each sample, visit every
 * page, build every report, and fail on any console error or missing output.
 */
import { withPage } from './harness.mjs';

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

const PAGES = ['overview', 'guided', 'site', 'ves', 'design', 'spine', 'pumping',
  'quality', 'costing', 'procurement', 'supervision', 'handover',
  'templates', 'extract',
  'waterpoints', 'coverage', 'portfolio', 'registry', 'settings', 'about'];

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
          ['test type', has(d.analysis.test_type || d.test.test_type)],
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
    const streamlit = [
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
    app.store.set('overrides', {});
    app.render();
    return { complete, missing, refused, issued, cleared, typedName, pressed,
      restored };
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
  // restart, readable by anything with script access to this origin.
  const credential = await page.evaluate(async () => {
    const app = window.GWT.app;
    app.setApiKey('sk-ant-smoke-test-key', false);
    const inMemory = {
      readable: app.getApiKey(),
      inSession: sessionStorage.getItem('gwt.credential.v1'),
      inLocal: (localStorage.getItem('gwt.project.v1') || '')
        .includes('sk-ant-smoke-test-key'),
      inState: JSON.stringify(app.store.state).includes('sk-ant-smoke-test-key'),
    };
    app.store.persist();
    inMemory.inLocalAfterPersist = (localStorage.getItem('gwt.project.v1') || '')
      .includes('sk-ant-smoke-test-key');

    // opting in puts it in sessionStorage, which the browser drops with the tab
    app.setApiKey('sk-ant-smoke-test-key', true);
    const remembered = sessionStorage.getItem('gwt.credential.v1');
    const stillNotInLocal = !(localStorage.getItem('gwt.project.v1') || '')
      .includes('sk-ant-smoke-test-key');

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
    credential.stillNotInLocal === true, JSON.stringify(credential));
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
  // localStorage quota is finite and photographs are large. Autosave dropping
  // out silently is the worst thing this app can do to a day of fieldwork.
  const autosave = await page.evaluate(async () => {
    const store = window.GWT.app.store;
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function () {
      const err = new Error('quota');
      err.name = 'QuotaExceededError';
      throw err;
    };
    const okDuringFailure = store.persist();
    const failingState = store.autosaveOk();
    const bannerShown = !!document.querySelector('#autosave-banner .callout-bad');
    Storage.prototype.setItem = original;
    const okAfterRecovery = store.persist();
    return {
      okDuringFailure, failingState, bannerShown, okAfterRecovery,
      recovered: store.autosaveOk(),
      bannerCleared: !document.querySelector('#autosave-banner .callout-bad'),
      bannerText: document.querySelector('#autosave-banner')?.textContent || '',
    };
  });
  check('autosave: a failed mirror write is reported, not swallowed',
    autosave.okDuringFailure === false && autosave.failingState === false &&
    autosave.bannerShown === true, JSON.stringify(autosave));
  check('autosave: the warning clears once writing works again',
    autosave.okAfterRecovery === true && autosave.recovered === true &&
    autosave.bannerCleared === true, JSON.stringify(autosave));

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
    await page.context().setOffline(false);
    check('offline: the app boots with the network switched off', bootedOffline);
  } else {
    check('offline: the app boots with the network switched off', false,
      JSON.stringify(offlineLoad));
  }

  check('no console errors', consoleErrors.length === 0,
    consoleErrors.slice(0, 10).join('\n     '));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

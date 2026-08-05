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
  'quality', 'costing', 'supervision', 'handover', 'templates', 'extract',
  'waterpoints', 'coverage', 'portfolio', 'settings', 'about'];

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
      requested = String(u);
      return new Response(JSON.stringify([
        { row_id: '1', lat_deg: '8.4660', lon_deg: '-13.2318',
          status_clean: 'Non-Functional', water_source_clean: 'Borehole',
          water_tech_clean: 'Hand Pump - India Mark II', install_year: '2011' },
        { row_id: '2', lat_deg: '8.4690', lon_deg: '-13.2350',
          status_clean: 'Functional', water_source_clean: 'Unprotected Spring',
          water_tech_clean: '' },
        { row_id: '3', lat_deg: '9.9', lon_deg: '-13.9',
          status_clean: 'Functional', water_source_clean: 'Borehole',
          water_tech_clean: 'Hand Pump' },
      ]), { status: 200, headers: { 'content-type': 'application/json' } });
    };
    let points, failure = null;
    try {
      points = await C.waterPointsNear(8.4657, -13.2317, 1000);
    } finally { window.fetch = real; }

    // and the failure path, which must stay a message rather than a crash
    window.fetch = async () => { throw new TypeError('offline'); };
    try { await C.waterPointsNear(8.4657, -13.2317, 1000); }
    catch (e) { failure = e.name + ': ' + e.message; }
    window.fetch = real;

    const decision = C.rehabVsDrill(points, 8.4657, -13.2317, { searchRadiusM: 1000 });
    return {
      url, requested, n: points.length,
      improved: points.map((p) => p.improved),
      functional: points.map((p) => p.functional),
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
  check('water points: the lookup parses the response', waterPoints.n === 3,
    `${waterPoints.n} points`);
  check('water points: an unprotected spring is not an improved source',
    JSON.stringify(waterPoints.improved) === JSON.stringify([true, false, true]),
    JSON.stringify(waterPoints.improved));
  check('water points: status maps to functionality',
    JSON.stringify(waterPoints.functional) === JSON.stringify([false, true, true]),
    JSON.stringify(waterPoints.functional));
  check('water points: only the ones in range are judged',
    waterPoints.nearby === 2, `${waterPoints.nearby} within 1000 m`);
  check('water points: a broken borehole nearby is a rehabilitation candidate',
    waterPoints.recommendation === 'assess_rehab' && waterPoints.candidates === 1,
    `${waterPoints.recommendation}, ${waterPoints.candidates} candidates`);
  check('water points: being offline is a message, not a crash',
    /^WaterPointFetchError: /.test(waterPoints.failure || ''), waterPoints.failure);

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
    ];
    const offsets = [];
    bodies.forEach((body, i) => {
      offsets.push(parts.length);
      push(`${i + 1} 0 obj\n`);
      if (body === null) {
        push(`<< /Length ${compressed.length} /Filter /FlateDecode >>\nstream\n`);
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

  check('no console errors', consoleErrors.length === 0,
    consoleErrors.slice(0, 10).join('\n     '));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

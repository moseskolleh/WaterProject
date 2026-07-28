/* Write real .docx/.xlsx/PNG artifacts and screenshots to a directory, so the
 * outputs can be opened and checked by a person or by python-docx.
 */
import { withPage } from './harness.mjs';
import { writeFile, mkdir } from 'node:fs/promises';

const OUT = process.argv[2] || '/tmp/gwt-artifacts';
await mkdir(OUT, { recursive: true });

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app);
  await page.evaluate(() => window.GWT.app.loadSample('dr_timbo'));
  await page.waitForFunction(() => window.GWT.app.recomputeState.running === 0 &&
    window.GWT.app.derived.estimate !== null, { timeout: 60000 });

  const kinds = ['completion', 'pumping', 'quality', 'costing', 'supervision', 'handover'];
  for (const kind of kinds) {
    const b64 = await page.evaluate(async (k) => {
      const cfg = window.GWT.app.config(), C = window.GWT.core;
      const charts = window.GWT.charts, docx = window.GWT.docx, d = window.GWT.app.derived;
      const ctx = { style: cfg.style, site: window.GWT.app.store.get('site'), figures: [] };
      let builder;
      if (k === 'completion') {
        ctx.log = d.log; ctx.design = d.design;
        ctx.figures = [{ image: await charts.toPng(charts.boreholeDesign(d.design, d.log)),
          caption: 'Borehole construction design', widthCm: 12 }];
        builder = await docx.completionReport(ctx);
      } else if (k === 'pumping') {
        ctx.analysis = d.analysis;
        ctx.figures = [
          { image: await charts.toPng(charts.testOverview(d.test, d.analysis, { hover: false })),
            caption: 'Water level through the pumping and recovery phases' },
          { image: await charts.toPng(charts.cooperJacob(d.analysis, { hover: false })),
            caption: 'Cooper-Jacob straight line fit' },
        ];
        builder = await docx.pumpingReport(ctx);
      } else if (k === 'quality') {
        ctx.assessment = d.assessment;
        ctx.figures = [
          { image: await charts.toPng(charts.piper([d.sample])), caption: 'Piper diagram', widthCm: 13 },
          { image: await charts.toPng(charts.stiff(d.sample)), caption: 'Stiff diagram', widthCm: 11 },
        ];
        builder = await docx.qualityReport(ctx);
      } else if (k === 'costing') {
        ctx.estimate = d.estimate;
        ctx.figures = [{ image: await charts.toPng(charts.costBreakdown(d.estimate, { mode: 'stage' })),
          caption: 'Direct cost by construction stage' }];
        builder = await docx.costingReport(ctx);
      } else if (k === 'supervision') {
        const items = C.loadChecklists();
        const responses = {};
        items.forEach((it, i) => { responses[it.item_id] = { item_id: it.item_id, status: ['yes','no','na','pending'][i % 4], remark: '' }; });
        ctx.items = items; ctx.responses = responses;
        ctx.evaluation = C.evaluateChecklist(items, responses);
        ctx.fieldChecks = [C.sandContentCheck([0.1, 0.15, 0.12]), C.handpumpCorrosionCheck(6.2)];
        builder = await docx.supervisionReport(ctx);
      } else {
        ctx.log = d.log; ctx.design = d.design; ctx.analysis = d.analysis;
        ctx.assessment = d.assessment;
        ctx.committee = [{ name: 'A. Kamara', role: 'Chair', contact: '076 000 000' }];
        builder = await docx.handoverReport(ctx);
      }
      const bytes = await builder.build();
      let s = '';
      for (let i = 0; i < bytes.length; i += 0x8000) {
        s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      }
      return btoa(s);
    }, kind);
    await writeFile(`${OUT}/${kind}_report.docx`, Buffer.from(b64, 'base64'));
  }

  // a BoQ workbook
  const xlsx = await page.evaluate(async () => {
    const d = window.GWT.app.derived, S = window.GWT.support;
    const rows = d.estimate.boq_rows(); const header = Object.keys(rows[0]);
    const bytes = await S.writeXlsx([{ name: 'BoQ',
      rows: [header].concat(rows.map((r) => header.map((h) => r[h]))) }]);
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(s);
  });
  await writeFile(`${OUT}/boq.xlsx`, Buffer.from(xlsx, 'base64'));

  // screenshots of the main pages, both themes
  for (const theme of ['light', 'dark']) {
    await page.evaluate((t) => {
      window.GWT.app.store.set('theme', t);
      document.documentElement.setAttribute('data-theme', t);
      window.GWT.app.render();
    }, theme);
    for (const key of ['overview', 'pumping', 'quality', 'design', 'costing', 'ves']) {
      await page.evaluate((k) => window.GWT.app.goto(k), key);
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${OUT}/${theme}-${key}.png`, fullPage: false });
    }
  }
  // one full-page shot of the richest page
  await page.evaluate(() => {
    window.GWT.app.store.set('theme', 'light');
    document.documentElement.setAttribute('data-theme', 'light');
    window.GWT.app.goto('pumping');
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/pumping-full.png`, fullPage: true });

  console.log('console errors:', consoleErrors.length ? consoleErrors.join('\n') : 'none');
});
console.log('artifacts written to ' + OUT);

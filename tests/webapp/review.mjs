/* What a signed document is allowed to say.
 *
 * These reports are not summaries. A handover report is signed by the
 * contractor, the client and the community; a payment certificate is argued
 * from the works list; an asset record is what somebody comes back to in five
 * years to find the borehole again. So the standing rule across the toolkit
 * is that a document may assert only what the project actually holds a record
 * of, and must say plainly where a record is missing rather than quietly
 * reading well.
 *
 * That rule is easy to break by accident and almost impossible to notice: the
 * document still builds, still has every heading, and reads better for the
 * missing hedge. parity.mjs holds the browser engine to the Python numbers and
 * smoke.mjs proves every page and report renders; neither of them reads what
 * the document ends up claiming. This file does.
 *
 * The demonstration projects are the fixture on purpose. They are transcribed
 * from real survey and completion reports and they are incomplete in exactly
 * the way field data is - no GPS fix on any sheet, a step test with no
 * discharge recorded - so the honest answer for all of them is "not
 * certifiable", and a change that makes a demonstration project certifiable
 * is the change this file exists to catch.
 */
import { withPage } from './harness.mjs';
import { readFile } from 'node:fs/promises';

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app);

  // The visible text of a .docx, in reading order: a report can be a valid
  // ZIP with every OOXML part in place and still claim something nobody
  // recorded, so these checks read what the client would read.
  await page.evaluate(() => {
    window.__docText = async function (bytes) {
      const files = await window.GWT.support.unzip(bytes);
      return ['word/document.xml', 'word/footer1.xml']
        .filter((n) => files[n])
        .map((name) => {
          const xml = new DOMParser().parseFromString(
            new TextDecoder().decode(files[name]), 'application/xml');
          return Array.from(xml.getElementsByTagName('w:p')).map((p) =>
            Array.from(p.getElementsByTagName('w:t'))
              .map((t) => t.textContent).join('')).join('\n');
        }).join('\n');
    };
    window.__handover = async function (over) {
      const cfg = window.GWT.app.config();
      const d = window.GWT.app.derived;
      const context = Object.assign({
        style: cfg.style, site: window.GWT.app.store.get('site'),
        log: d.log, design: d.design, analysis: d.analysis,
        assessment: d.assessment, interpretations: d.interpretations,
        committee: [], figures: [],
        readiness: window.GWT.app.reportReadiness('handover'),
      }, over || {});
      const builder = await window.GWT.docx.handoverReport(context);
      return window.__docText(await builder.build());
    };
  });

  /* The document the user actually gets: built through the app's own
   * buildReport, which is what assembles the maps, the locator note and the
   * readiness the report is stamped from. The hand-built context above is
   * only for the variants that need a record withheld. */
  async function issued(kind) {
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.evaluate((k) => window.GWT.app.buildReport(k), kind),
    ]);
    const bytes = await readFile(await download.path());
    return page.evaluate((b64) => window.__docText(
      Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))), bytes.toString('base64'));
  }

  await page.evaluate(() => window.GWT.app.loadSample('dr_timbo'));
  await page.waitForFunction(
    () => window.GWT.app.recomputeState.running === 0 &&
          window.GWT.app.derived.analysis !== null, { timeout: 60000 });

  // --- a demonstration project is not a certifiable one ---------------------
  // Every one of the sample sheets is missing its GPS fix, which is true of
  // the originals. Nothing in the load path may quietly supply one to make
  // the demonstration look finished.
  const gate = await page.evaluate(() => {
    const kinds = Object.keys(window.GWT.core.READINESS_REPORTS);
    const out = {};
    for (const kind of kinds) {
      const r = window.GWT.app.reportReadiness(kind);
      out[kind] = {
        certifiable: r.is_certifiable,
        unmet: r.unmet.map((u) => u.key),
        state: r.state,
      };
    }
    return { kinds, out, site: window.GWT.app.store.get('site') };
  });
  const everyKind = gate.kinds.every((k) => gate.out[k].certifiable === false &&
    gate.out[k].unmet.includes('site_located'));
  check('demonstration evidence cannot pass the gate, for any report',
    gate.kinds.length >= 10 && everyKind, JSON.stringify(gate.out));
  check('nothing in the load path invents a position',
    (gate.site.easting === null || gate.site.easting === undefined) &&
    (gate.site.northing === null || gate.site.northing === undefined),
    JSON.stringify(gate.site));

  // --- the gate judges evidence, not outcome --------------------------------
  // Water that fails a health guideline is a finding, not a missing record.
  // A borehole with bad water is perfectly certifiable; one whose result
  // could not be read is not.
  const verdict = await page.evaluate(() => {
    const r = window.GWT.app.reportReadiness('quality');
    const byKey = Object.fromEntries(r.requirements.map((q) => [q.key, q.state]));
    return {
      verdict: window.GWT.app.derived.assessment.verdict_state,
      panel: byKey.water_quality_panel,
      evaluable: byKey.water_quality_evaluable,
    };
  });
  check('water that fails a health guideline is still a readable result',
    verdict.verdict === 'health_fail' && verdict.panel === 'met' &&
    verdict.evaluable === 'met', JSON.stringify(verdict));

  // But a value nobody can grade is a missing result, and is named.
  const ungraded = await page.evaluate(() => {
    /* graded by the engine's own reader, not by hand-built rows: a unit the
     * reader cannot convert has to survive as an ungraded row all the way to
     * the gate rather than being dropped on the way */
    const state = window.GWT.app.projectState();
    const sample = JSON.parse(JSON.stringify(window.GWT.app.derived.sample));
    sample.results.push({ parameter: 'Iron', value: 0.1, unit: 'wibbles' });
    const wq = window.GWT.core.assessSample(sample);
    const r = window.GWT.core.assessReadiness(
      Object.assign({}, state, { wq_assessment: wq }), 'quality', {});
    const found = r.unmet.find((u) => u.key === 'water_quality_evaluable');
    return { unmet: r.unmet.map((u) => u.key), detail: found ? found.detail : '' };
  });
  check('a reading nobody can grade is named, not dropped',
    ungraded.unmet.includes('water_quality_evaluable') &&
    ungraded.detail.includes('Iron'), JSON.stringify(ungraded));

  // --- the document says what the gate says ---------------------------------
  const stamped = await issued('handover');
  check('the report is still produced, and carries the stamp',
    stamped.includes('PROVISIONAL - NOT FOR CERTIFICATION'),
    stamped.slice(0, 300));
  check('the stamp names the outstanding requirement, not just a count',
    stamped.includes('This report rests on incomplete results.') &&
    stamped.includes('Site position') &&
    stamped.includes('No GPS position is recorded on any sheet in this project.'),
    stamped.slice(0, 600));

  // --- handover works require a record --------------------------------------
  // The works list is the part of a handover report that money and liability
  // hang off. Every bullet has to be backed by the record that evidences it:
  // a project with no pumping test may not be handed over claiming one.
  const works = await page.evaluate(async () => {
    function worksOf(text) {
      const start = text.indexOf('2. Works Completed');
      const end = text.indexOf('3. Borehole Data Sheet');
      return text.slice(start, end).split('\n').map((s) => s.trim())
        .filter((s) => s && !s.startsWith('2. Works Completed'));
    }
    const full = worksOf(await window.__handover());
    /* the same project with each record withheld in turn */
    const noPumping = worksOf(await window.__handover({ analysis: null }));
    const noQuality = worksOf(await window.__handover({ assessment: null }));
    const noDesign = worksOf(await window.__handover({ design: null }));
    const sited = worksOf(await window.__handover({
      interpretations: [{ sounding_id: 'VES 1' }] }));
    return { full, noPumping, noQuality, noDesign, sited };
  });
  const said = (list, fragment) => list.some((line) => line.includes(fragment));
  check('a handover with no pumping test does not claim one',
    said(works.full, 'Pumping test') && !said(works.noPumping, 'Pumping test'),
    JSON.stringify(works.noPumping));
  check('a handover with no laboratory analysis does not claim one',
    said(works.full, 'Water quality sampled') &&
    !said(works.noQuality, 'Water quality sampled'),
    JSON.stringify(works.noQuality));
  check('a handover with no design claims neither construction nor development',
    !said(works.noDesign, 'Cased and screened') &&
    !said(works.noDesign, 'developed by air lifting'),
    JSON.stringify(works.noDesign));
  check('a siting survey is listed only where one was interpreted',
    !said(works.full, 'Geophysical siting survey') &&
    said(works.sited, 'Geophysical siting survey'),
    JSON.stringify(works.full));
  check('nothing is asserted about a handpump nobody recorded installing',
    !said(works.full, 'Handpump') && !said(works.full, 'soakaway'),
    JSON.stringify(works.full));

  // --- missing GPS stays missing, everywhere it shows ------------------------
  check('the report says the maps cover the area, not the borehole',
    stamped.includes('No GPS position is recorded for it'), '');

  await page.evaluate(() => window.GWT.app.goto('registry'));
  await page.waitForTimeout(120);
  const registry = await page.evaluate(() => ({
    warned: Array.from(document.querySelectorAll('#page-host .callout-warn p'))
      .map((n) => n.textContent).join(' '),
    identifier: !!document.querySelector('#page-host p.asset-id'),
  }));
  check('an unlocated borehole is given no asset identifier',
    registry.identifier === false &&
    registry.warned.includes('no recorded position yet'),
    JSON.stringify(registry));

  // --- and a recorded position clears it ------------------------------------
  // The stamp has to track the evidence rather than a flag somebody set:
  // supply the one missing record and the document stops hedging.
  await page.evaluate(() => {
    window.GWT.app.store.set('site.easting', 778000);
    window.GWT.app.store.set('site.northing', 946000);
  });
  const locatedText = await issued('handover');
  const located = await page.evaluate((text) => {
    const r = window.GWT.app.reportReadiness('handover');
    return {
      state: r.state,
      certifiable: r.is_certifiable,
      summary: r.summary,
      stamped: text.includes('PROVISIONAL'),
      hedged: text.includes('No GPS position is recorded for it'),
    };
  }, locatedText);
  check('recording the position is what clears the stamp',
    located.certifiable === true && located.state === 'ready' &&
    located.stamped === false && located.hedged === false,
    JSON.stringify(located));

  // --- an interim document says who issued it and why ------------------------
  await page.evaluate(() => {
    window.GWT.app.store.set('site.easting', null);
    window.GWT.app.store.set('site.northing', null);
    window.GWT.app.store.set('overrides', {
      handover: { site_located: { reason: 'GPS unit failed on the day',
        by: 'M. Kolleh' } },
    });
  });
  const overrideText = await issued('handover');
  const override = await page.evaluate((text) => {
    const r = window.GWT.app.reportReadiness('handover');
    return {
      state: r.state,
      certifiable: r.is_certifiable,
      titled: text.includes('ISSUED ON OVERRIDE - NOT A CERTIFICATION'),
      named: text.includes('M. Kolleh') && text.includes('GPS unit failed on the day'),
      provisional: text.includes('PROVISIONAL - NOT FOR CERTIFICATION'),
    };
  }, overrideText);
  check('an interim document names who issued it and why',
    override.titled === true && override.named === true &&
    override.provisional === false, JSON.stringify(override));
  check('an override is an interim issue, never a certification',
    override.state === 'ready_with_overrides' && override.certifiable === false,
    JSON.stringify(override));

  // --- a result that is pending says why -------------------------------------
  // The step test has no discharge on the sheet, so there is no yield. The
  // gate has to carry that reason through rather than report an empty result.
  await page.evaluate(() => window.GWT.app.store.set('overrides', {}));
  await page.evaluate(() => window.GWT.app.loadSample('kuntolo'));
  await page.waitForFunction(
    () => window.GWT.app.recomputeState.running === 0 &&
          window.GWT.app.derived.analysis !== null, { timeout: 60000 });
  const pending = await page.evaluate(() => {
    const r = window.GWT.app.reportReadiness('pumping');
    const rec = window.GWT.app.derived.analysis.yield_recommendation;
    const found = r.unmet.find((u) => u.key === 'yield_established');
    return {
      reason: rec.pending_reason,
      detail: found ? found.detail : '',
      unmet: r.unmet.map((u) => u.key),
    };
  });
  check('a yield that is pending says why, in the words the analysis used',
    !!pending.reason && pending.detail === pending.reason &&
    pending.unmet.includes('yield_established'), JSON.stringify(pending));

  check('no console errors', consoleErrors.length === 0,
    consoleErrors.slice(0, 10).join('\n     '));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

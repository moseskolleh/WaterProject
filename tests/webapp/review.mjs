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
  // recorded, so these checks read what the client would read. The table of
  // contents repeats every heading, so it is left out unless asked for: the
  // checks find a section by its heading, and would otherwise find its line
  // in the contents.
  await page.evaluate(() => {
    window.__docText = async function (bytes, withContents) {
      const files = await window.GWT.support.unzip(bytes);
      return ['word/document.xml', 'word/footer1.xml']
        .filter((n) => files[n])
        .map((name) => {
          const xml = new DOMParser().parseFromString(
            new TextDecoder().decode(files[name]), 'application/xml');
          return Array.from(xml.getElementsByTagName('w:p')).filter((p) =>
            withContents || !Array.from(p.getElementsByTagName('w:instrText'))
              .some((i) => /^\s*TOC\b/.test(i.textContent)))
            .map((p) => Array.from(p.getElementsByTagName('w:t'))
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

  // A position is not a position in Sierra Leone just because it was typed.
  // The site page flagged a fix outside the country and the gate passed it,
  // where the Python holds the report back; the site page also takes a
  // latitude and longitude in the two boxes, which only the browser does.
  const placed = await page.evaluate(() => {
    const state = window.GWT.app.projectState();
    const detail = (site) => window.GWT.core.assessReadiness(
      Object.assign({}, state, { site: Object.assign({}, state.site, site) }),
      'completion', {}).requirements.find((q) => q.key === 'site_located');
    return {
      utm: detail({ easting: 778000, northing: 446000, utm_zone: 28 }),
      degrees: detail({ easting: -13.2317, northing: 8.4657, utm_zone: null }),
      unsigned: detail({ easting: 13.2317, northing: 8.4657, utm_zone: null }),
      abroad: detail({ easting: -13.2317, northing: 4.0, utm_zone: null }),
    };
  });
  check('a UTM fix outside the country does not pass the gate',
    placed.utm.state === 'unmet' &&
    placed.utm.detail.includes('which is outside Sierra Leone'), JSON.stringify(placed.utm));
  check('a degree fix outside the country does not pass the gate',
    placed.abroad.state === 'unmet' &&
    placed.abroad.detail.startsWith('Coordinates convert to 4.0000 N, 13.2317 W'),
    JSON.stringify(placed.abroad));
  check('a degree fix is recorded as degrees, not as metres',
    placed.degrees.state === 'met' &&
    placed.degrees.detail === 'Position recorded: 8.46570° N, 13.23170° W.' &&
    placed.unsigned.state === 'met' &&
    placed.unsigned.detail === placed.degrees.detail,
    JSON.stringify([placed.degrees, placed.unsigned]));

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
    said(works.full, 'laboratory analysis') &&
    !said(works.noQuality, 'laboratory analysis'),
    JSON.stringify(works.noQuality));
  check('a handover with no design claims neither construction nor development',
    !said(works.noDesign, 'Construction with') &&
    !said(works.noDesign, 'air lifting'),
    JSON.stringify(works.noDesign));
  // The bullets a payment is argued from carry the quantities a surveyor
  // checks. They used to carry the casing size in one engine and the screen
  // run in the other, and the seal in neither.
  // It words the fill from the design and says "designed" unless the log
  // records the screens as installed: it used to certify a gravel pack in a
  // 19 mm annulus the design had left empty, and 19 m of screen as completed
  // work above a drawing captioned "not an as-built record".
  check('the construction bullet carries the casing, the screen run and the seal',
    said(works.full, 'Construction designed with 5 inch uPVC casing, 19 m of screen, ' +
      'no gravel pack (the 19 mm annulus is too thin to place one) and sanitary seal ' +
      'to 20 m; the drilling log records no casing string as installed.'),
    JSON.stringify(works.full));
  // The pumping report promised that "the borehole design sets it just below
  // that screen", while the design lifted an intake in a bottom screen above
  // the level the test had reached. The sentence now says what the design does.
  const pumpingText = await issued('pumping');
  check('the pumping report says what the design does with an intake in a screen',
    pumpingText.includes('or above it where that is no shallower than the deepest ' +
      'level the test reached plus the submergence margin; otherwise it keeps this ' +
      'depth and says so in its design notes.') &&
    !pumpingText.includes('sets it just below that screen'),
    pumpingText.slice(pumpingText.indexOf('Install the pump intake'),
      pumpingText.indexOf('Install the pump intake') + 400));
  check('a siting survey is listed only where one was interpreted',
    !said(works.full, 'Geophysical siting survey') &&
    said(works.sited, 'Geophysical siting survey'),
    JSON.stringify(works.full));
  check('nothing is asserted about a handpump nobody recorded installing',
    !said(works.full, 'Handpump') && !said(works.full, 'soakaway'),
    JSON.stringify(works.full));

  // --- the care instructions follow the pump that is there ------------------
  // Section 5 is the part of the handover a caretaker actually uses, and it
  // used to be handpump boilerplate whatever the project recorded: bolts on
  // the pump head, strokes to count per day, rods to inspect. A submersible
  // has none of those and has a control box, a starter and a running current
  // that nothing told anyone to check.
  const om = await page.evaluate(async () => {
    const section = (text) => text.slice(
      text.indexOf('5. Operation and Maintenance Guidance'),
      text.indexOf('6. Community / WASH Committee'));
    return {
      unrecorded: section(await window.__handover()),
      submersible: section(await window.__handover({
        pumpType: 'Grundfos SQFlex submersible' })),
      solar: section(await window.__handover({ pumpType: 'Solar pump, 1.2 kW array' })),
    };
  });
  check('maintenance guidance follows the pump that was installed',
    om.unrecorded.includes('strokes per day') &&
    !om.submersible.includes('strokes per day') &&
    !om.submersible.includes('pump rods') &&
    !om.submersible.includes('bolts on the pump head') &&
    om.submersible.includes('Check the running current against the commissioning value.') &&
    om.solar.includes('the array for damage, loose connections and shading'),
    om.submersible);

  // --- the data sheet states a thing once -----------------------------------
  // The log and the construction record both carry a depth, a static level
  // and the strikes. Printed twice a metre apart they are two claims for a
  // reader to reconcile, and a pump nobody recorded is not a row at all.
  const sheet = await page.evaluate(async () => {
    const text = await window.__handover();
    return text.slice(text.indexOf('3. Borehole Data Sheet'),
      text.indexOf('4. Water Quality'))
      .split('\n').map((s) => s.trim()).filter(Boolean);
  });
  const rows = (label) => sheet.filter((line) => line === label).length;
  check('the borehole data sheet states each item once, and invents no pump',
    rows('Total depth') === 1 && rows('Water strikes') === 1 &&
    rows('Static water level') <= 1 && rows('Pump type') === 0,
    JSON.stringify(sheet));

  // --- the cover is filled in or silent -------------------------------------
  // A label with nothing after it is a blank line on the first page of a
  // signed document. The handover cover carried two.
  const cover = stamped.slice(0, stamped.indexOf('PROVISIONAL - NOT FOR CERTIFICATION'));
  check('no cover line is a label with nothing after it',
    cover.includes('Borehole reference') && !cover.includes('Handover date') &&
    !cover.includes('—'), cover);

  // --- the summary is qualified the way the cover is ------------------------
  // A stamp on page one and an unhedged verdict on page three is a
  // contradiction the reader who starts at the summary never sees resolved.
  const qualified = 'This report is provisional and not a certification (outstanding: ';
  check('a provisional report says so where its verdict is given',
    stamped.includes(qualified) &&
    stamped.includes('). The findings below are those the supplied records ' +
      'support; the cover says what is missing.') &&
    stamped.indexOf(qualified) > stamped.indexOf('Executive Summary') &&
    stamped.indexOf(qualified) < stamped.indexOf('Key findings:'),
    stamped.slice(stamped.indexOf('Executive Summary'),
      stamped.indexOf('Executive Summary') + 400));

  // --- what the water result is called --------------------------------------
  // WHO sets no health based guideline for total coliforms and E. coli is 0
  // here, so a coliform count is a national-limit failure and an indicator of
  // wellhead ingress. Three documents called it a health guideline breach and
  // faecal contamination, which is a different finding with a different
  // remedy.
  //
  // Each table cell is its own paragraph in the extracted text, so a row is
  // the parameter's line and the three that follow it: value, unit, remark.
  const lines = stamped.split('\n').map((line) => line.trim());
  const coliformAt = lines.indexOf('Total coliforms');
  const coliformRow = lines.slice(coliformAt, coliformAt + 4).join(' | ');
  const healthSentence = lines.find(
    (line) => line.includes('health based guideline value for:')) || '';
  check('total coliforms are reported as a national-limit failure, not a health one',
    coliformAt > 0 && !/coliform/i.test(healthSentence) &&
    /national limit/i.test(coliformRow) &&
    !/exceeds the WHO health based guideline/i.test(coliformRow),
    JSON.stringify([healthSentence, coliformRow]));

  // --- a provisional limit is called provisional wherever it is printed -----
  // The national column has not been confirmed against the Standards Bureau
  // specification, and a national exceedance reads as a compliance failure.
  // The quality report said so; the completion and handover tables printed
  // the same judgement bare.
  const provisional = 'The national column in the standards table is provisional';
  const completionDoc = await issued('completion');
  check('a national limit in a report table carries the provisional note',
    stamped.includes('Total coliforms') && stamped.includes(provisional) &&
    completionDoc.includes('Total coliforms') && completionDoc.includes(provisional),
    JSON.stringify([stamped.includes(provisional), completionDoc.includes(provisional)]));

  // --- the facies section says what its diagram shows ------------------------
  // It used to be two figures under a heading naming something neither of
  // them spelled out, which tells a reader who cannot read a Piper diagram
  // nothing whatever.
  const qualityDoc = await issued('quality');
  const faciesAt = qualityDoc.indexOf('5. Hydrochemical Facies');
  const piperAt = qualityDoc.indexOf('Piper trilinear diagram');
  check('the facies section names the water type above the diagram',
    faciesAt >= 0 && piperAt > faciesAt &&
    /The water is a [-\w+]+ type \(/.test(qualityDoc.slice(faciesAt, piperAt)),
    qualityDoc.slice(faciesAt, faciesAt + 400));

  // --- the table of contents reads before Word has updated it ----------------
  // Its cached result was the sentence "Right-click and choose Update Field",
  // which is what every viewer other than Word shows; it is now the headings,
  // and settings.xml asks Word to add the page numbers on opening, as the
  // Python builder does.
  const parts = await page.evaluate(async () => {
    const d = window.GWT.app.derived;
    const builder = await window.GWT.docx.qualityReport({
      assessment: d.assessment, style: window.GWT.app.config().style, figures: [],
    });
    const bytes = await builder.build();
    const files = await window.GWT.support.unzip(bytes);
    const text = (name) => (files[name] ? new TextDecoder().decode(files[name]) : '');
    return {
      body: await window.__docText(bytes, true),
      settings: text('word/settings.xml'),
      types: text('[Content_Types].xml'),
      rels: text('word/_rels/document.xml.rels'),
    };
  });
  const tocAt = parts.body.indexOf('Table of Contents');
  const contents = parts.body.slice(tocAt, parts.body.indexOf('Executive Summary'));
  check('the table of contents lists the headings and asks Word to number them',
    tocAt >= 0 && !parts.body.includes('Right-click') &&
    contents.includes('1. Sample Details') && contents.includes('6. Recommendations') &&
    parts.settings.includes('<w:updateFields w:val="true"/>') &&
    parts.types.includes('/word/settings.xml') && parts.rels.includes('settings.xml'),
    JSON.stringify({ contents: contents.slice(0, 300), settings: parts.settings }));

  // --- a result the laboratory did not quantify prints as it was reported ---
  // TNTC and ">50" reached the results table as a dash. The one engine that
  // writes this table has to print the bound, or "detected".
  const unquantified = await page.evaluate(async () => {
    const C = window.GWT.core;
    const assessment = C.assessSample({ site: { community: 'Ref' }, flags: [], results: [
      { parameter: 'E. coli', value: 0, unit: 'CFU/100 mL' },
      { parameter: 'Arsenic', value: 0.001, unit: 'mg/L' },
      { parameter: 'Fluoride', value: 0.3, unit: 'mg/L' },
      { parameter: 'Nitrate (as NO3)', value: null, unit: 'mg/L', greater_than: 50 },
      { parameter: 'Total coliforms', value: null, unit: 'CFU/100 mL', greater_than: 0 },
    ] });
    const builder = await window.GWT.docx.qualityReport({
      assessment, style: window.GWT.app.config().style, figures: [],
    });
    return (await window.__docText(await builder.build())).split('\n');
  });
  const cellAfter = (name) => unquantified[unquantified.indexOf(name) + 1];
  check('a result the laboratory did not quantify prints as it was reported',
    cellAfter('Nitrate (as NO3)') === '>50' && cellAfter('Total coliforms') === 'detected',
    JSON.stringify([cellAfter('Nitrate (as NO3)'), cellAfter('Total coliforms')]));

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

  // --- a demonstration says so, and keeps saying it -------------------------
  // The sample files are offered from a picker so nobody has to have drilled
  // a borehole to see what the toolkit does. The documents they produce are
  // indistinguishable from real ones - same letterhead, same signature block
  // - and they leave as .docx files that get forwarded and filed, so the fact
  // has to travel with the document rather than live in the session that made
  // it. Dr Timbo's water quality workbook is the sharp case: no sample was
  // ever taken, and the determinand values exist to exercise the assessment.
  const demo = await page.evaluate(() => {
    const out = {};
    for (const kind of Object.keys(window.GWT.core.READINESS_REPORTS)) {
      const r = window.GWT.app.reportReadiness(kind);
      const q = r.requirements.filter((x) => x.key === 'field_data')[0];
      out[kind] = q ? [q.state, q.detail] : null;
    }
    return out;
  });
  const demoKinds = Object.keys(demo);
  check('every report kind knows it is describing a worked example',
    demoKinds.length >= 10 && demoKinds.every((k) => demo[k] && demo[k][0] === 'unmet'),
    JSON.stringify(demo));
  check('it says the readings were never measured, not merely that they are samples',
    demoKinds.every((k) => /never measured/.test(demo[k][1]) &&
      /dr_timbo_water_quality\.xlsx/.test(demo[k][1])),
    JSON.stringify(demo.completion));

  // The document, not the screen. This is the whole point: the stamp and the
  // reason have to be inside the file somebody forwards.
  const demoDoc = await issued('quality');
  check('the reason a demonstration cannot be certified is in the document',
    demoDoc.includes('PROVISIONAL - NOT FOR CERTIFICATION') &&
    demoDoc.includes('Field data') &&
    demoDoc.includes('Readings that were never measured are in this project'),
    demoDoc.slice(0, 800));

  // Saving and reopening must not launder it. The marker rides in the project
  // file with the source it belongs to; this runs the same two steps that
  // openProject() runs on a picked file, without the picker.
  const reopened = await page.evaluate(() => {
    const saved = JSON.stringify(window.GWT.app.projectPayload());
    const state = JSON.parse(saved).state;
    window.GWT.app.store.replace(Object.assign(window.GWT.app.blankState(), state));
    const r = window.GWT.app.reportReadiness('quality');
    const q = r.requirements.filter((x) => x.key === 'field_data')[0];
    return { written: /dr_timbo\/dr_timbo_water_quality\.xlsx/.test(saved),
      state: q.state, certifiable: r.is_certifiable };
  });
  check('saving and reopening a demonstration leaves it a demonstration',
    reopened.written === true && reopened.state === 'unmet' &&
    reopened.certifiable === false, JSON.stringify(reopened));

  // And it has to clear, per role, when real data arrives - otherwise it is a
  // label nobody can remove and everybody learns to ignore. Dropping a file on
  // a role replaces that whole source, which is what clears its marker.
  const replaced = await page.evaluate(() => {
    const before = window.GWT.app.store.get('sources');
    const b64 = before.quality.b64;
    window.GWT.app.store.set('sources.quality',
      { name: 'kambia_lab_results.xlsx', b64: b64 });
    const one = window.GWT.app.reportReadiness('quality').requirements
      .filter((x) => x.key === 'field_data')[0];
    ['drilling', 'pumping'].forEach(function (role) {
      window.GWT.app.store.set('sources.' + role,
        { name: 'kambia_' + role + '.xlsx', b64: before[role].b64 });
    });
    const all = window.GWT.app.reportReadiness('quality').requirements
      .filter((x) => x.key === 'field_data')[0];
    return { one: [one.state, one.detail], all: [all.state, all.detail] };
  });
  check('replacing one demonstration file drops that file, and only that file',
    replaced.one[0] === 'unmet' && !/never measured/.test(replaced.one[1]) &&
    /dr_timbo_drilling_log\.xlsx/.test(replaced.one[1]),
    JSON.stringify(replaced.one));
  check('replacing the data with the analyst\'s own clears the marker',
    replaced.all[0] === 'met', JSON.stringify(replaced.all));

  // --- and a recorded position clears the rest ------------------------------
  // The stamp has to track the evidence rather than a flag somebody set. The
  // data is the analyst's own now; supply the one record still missing and
  // the document stops hedging. Both were needed, which is the point: the
  // stamp comes off when the evidence is there, and not before.
  //
  // The sample's pumping test is 30 minutes inside its casing storage, so
  // its yield is indicative and the handover keeps "Yield established"
  // outstanding whatever the position says (the Python gate does the same,
  // and tests/webapp/reference.json records it). Recording the position
  // therefore clears the position gate and the hedge on the handover, and
  // clears the stamp itself on the water quality report, whose gate has no
  // yield requirement.
  await page.evaluate(() => {
    window.GWT.app.store.set('site.easting', 778000);
    window.GWT.app.store.set('site.northing', 946000);
  });
  const locatedText = await issued('handover');
  const qualityText = await issued('quality');
  const located = await page.evaluate(([text, qtext]) => {
    const r = window.GWT.app.reportReadiness('handover');
    const q = window.GWT.app.reportReadiness('quality');
    const position = r.requirements.find((x) => x.key === 'site_located');
    return {
      state: r.state,
      position: position ? position.state : null,
      outstanding: r.unmet.map((u) => u.key),
      summary: r.summary,
      hedged: text.includes('No GPS position is recorded for it'),
      quality_state: q.state,
      quality_certifiable: q.is_certifiable,
      quality_stamped: qtext.includes('PROVISIONAL'),
      quality_hedged: qtext.includes('No GPS position is recorded for it'),
    };
  }, [locatedText, qualityText]);
  check('recording the position is what clears the stamp',
    located.position === 'met' && located.hedged === false &&
    located.state === 'not_ready' &&
    JSON.stringify(located.outstanding) === JSON.stringify(['yield_established']) &&
    located.summary === 'Not ready to certify - outstanding: Yield established.' &&
    located.quality_state === 'ready' && located.quality_certifiable === true &&
    located.quality_stamped === false && located.quality_hedged === false,
    JSON.stringify(located));

  // A grid reference is a position somebody has to type into a GPS to stand
  // where the borehole is. Printed with a thousands separator and no zone it
  // is a quantity instead, and in a country straddling zones 28N and 29N it
  // does not even say which grid it belongs to.
  check('a grid coordinate prints with its zone and no thousands separator',
    locatedText.includes('778000 m E (UTM zone 28N)') &&
    locatedText.includes('946000 m N') && !locatedText.includes('778,000'),
    locatedText.slice(0, 600));

  // --- an interim document says who issued it and why ------------------------
  // Both outstanding requirements are overridden, each with its reason: an
  // override on the position alone would leave the indicative yield unmet
  // and the document provisional rather than an override issue.
  await page.evaluate(() => {
    window.GWT.app.store.set('site.easting', null);
    window.GWT.app.store.set('site.northing', null);
    window.GWT.app.store.set('overrides', {
      handover: {
        site_located: { reason: 'GPS unit failed on the day', by: 'M. Kolleh' },
        yield_established: { reason: 'yield to be confirmed by a longer test',
          by: 'M. Kolleh' },
      },
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

  // --- the pumping report says what the sheet cannot support -----------------
  // The browser's pumping report printed none of the analysis's notes, so
  // Kuntolo's levels 18 m below the pump reached the client with nothing to
  // say so; its cover printed the parser's "step+recovery" token; its step
  // table renumbered the steps after one was left out; and the completion
  // report asked for a discharge the sheet recorded. The Python report, and
  // the hydraulics-8 wording, are what it is held to.
  const kuntoloDocs = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core, d = app.derived;
    const base = { style: app.config().style, site: app.store.get('site'), figures: [] };
    const log = { borehole_ref: 'KTL-01', total_depth_m: 70, status: 'Successful',
      intervals: [], water_strikes_m: [] };
    const text = async (builder) => window.__docText(await (await builder).build());
    const withQ = (pump) => {
      const test = JSON.parse(JSON.stringify(d.analysis.test));
      [1.5, 2.2, 3.0].forEach((q, i) => { test.steps[i].discharge_m3_per_h = q; });
      if (pump) test.pump_setting_m = pump;
      return C.analysePumpingTest(test);
    };
    return {
      pumping: await text(window.GWT.docx.pumpingReport(
        Object.assign({ analysis: d.analysis }, base))),
      stepped: await text(window.GWT.docx.pumpingReport(
        Object.assign({ analysis: withQ() }, base))),
      noDischarge: await text(window.GWT.docx.completionReport(
        Object.assign({ analysis: d.analysis, log }, base))),
      // rates on the sheet, and a pump set too shallow to leave any drawdown
      shallowPump: await text(window.GWT.docx.completionReport(
        Object.assign({ analysis: withQ(20), log }, base))),
    };
  });
  check('pumping report: the test type is in words on the cover, never the token',
    kuntoloDocs.pumping.includes('step drawdown test with recovery') &&
    !kuntoloDocs.pumping.includes('step+recovery'), kuntoloDocs.pumping.slice(0, 400));
  check('pumping report: the analysis\'s own notes are printed',
    kuntoloDocs.pumping.includes('Data verification notes:') &&
    kuntoloDocs.pumping.includes('[WARNING] level_below_pump: Recorded water level 78.45 m'),
    kuntoloDocs.pumping.slice(0, 400));
  check('pumping report: levels that cannot be right are never presented as sound curves',
    kuntoloDocs.pumping.includes('The recorded water levels are inconsistent with ' +
      'the stated static level, pump setting or borehole depth (see the data ' +
      'verification notes), so the curves are shown as recorded and their drawdowns ' +
      'are not to be relied on; the transmissivity and safe yield are pending ' +
      'because discharge is missing on the field sheet.') &&
    kuntoloDocs.pumping.includes('as recorded; the notes below say why the recorded ' +
      'levels cannot all be right'), kuntoloDocs.pumping.slice(0, 1200));
  check('pumping report: a step left out of the fit keeps the sheet\'s number',
    /Well efficiency\n2\n2\.20\n[^\n]*\n[^\n]*\n[^\n]*\n3\n3\.00\n/.test(kuntoloDocs.stepped),
    (kuntoloDocs.stepped.match(/Well efficiency(\n[^\n]*){12}/) || [''])[0]);
  check('completion: a discharge is asked for only when the sheet has none',
    kuntoloDocs.noDischarge.includes('The pumping test discharge must be supplied') &&
    !kuntoloDocs.shallowPump.includes('The pumping test discharge must be supplied'),
    JSON.stringify([kuntoloDocs.noDischarge.length, kuntoloDocs.shallowPump.length]));

  // --- the casing paragraph follows the adoption, and the intake is one depth
  // Dr Timbo's Cooper-Jacob line lies inside the casing-storage period and is
  // adopted as the best available; the report said a page earlier that no
  // line is read from that period. With an 8 m annual swing the drought case
  // sets the intake at 55 m where the day of the test sets 52 m; the design
  // was fed 52 m (and moved it to 54 m, below a screen) while the pumping
  // report printed 55 m.
  await page.evaluate(() => window.GWT.app.loadSample('dr_timbo'));
  await page.waitForFunction(
    () => window.GWT.app.recomputeState.running === 0 &&
          window.GWT.app.derived.analysis !== null, { timeout: 60000 });
  const timbo = await page.evaluate(async () => {
    const app = window.GWT.app, C = window.GWT.core, d = app.derived;
    app.store.set('seasonal', { rangeM: 8 });
    await app.recompute();
    const seasonal = C.seasonalYield(d.analysis, app.config().pumping, { annualRangeM: 8 });
    const intake = C.pumpIntakeDepth(d.analysis, seasonal);
    const pumping = await window.__docText(await (await window.GWT.docx.pumpingReport({
      style: app.config().style, site: app.store.get('site'), figures: [],
      analysis: d.analysis, seasonal,
    })).build());
    const moved = (d.design.flags || []).find((f) => f.code === 'pump_intake_moved');
    const out = {
      pumping, intake: intake[0],
      yieldDepth: d.analysis.yield_recommendation.pump_installation_depth_m,
      designIntake: d.design.pump_intake_m,
      requested: moved ? moved.message : null,
    };
    app.store.set('seasonal', {});
    await app.recompute();
    return out;
  });
  check('pumping report: the casing paragraph is worded from the adoption',
    timbo.pumping.includes('No fit outside it can be adopted, so the Cooper-Jacob ' +
      'value read inside it is used only as the best available.') &&
    !timbo.pumping.includes('no straight line is read from it') &&
    timbo.pumping.includes('the Cooper-Jacob value is adopted only as the best available'),
    timbo.pumping.slice(0, 400));
  check('the design is given the intake the pumping report prints',
    timbo.intake > timbo.yieldDepth &&
    timbo.pumping.includes('Install the pump intake at ' + timbo.intake + ' m') &&
    (timbo.designIntake === timbo.intake ||
      (timbo.requested || '').includes('The pump intake of ' + timbo.intake + ' m')),
    JSON.stringify({ intake: timbo.intake, yieldDepth: timbo.yieldDepth,
      design: timbo.designIntake, moved: timbo.requested }));

  // --- a sounding that will not invert takes only itself out -----------------
  // The inversion is the one computation here that can fail on real readings,
  // and it fails one sounding at a time. What must never happen is the survey
  // closing ranks over the gap: the geophysical report argues where to drill
  // from a named sounding's curve, so a figure captioned with one sounding's
  // name carrying another's data sends a rig to the wrong place. Silence is
  // the second failure - a survey reported on four soundings when five were
  // shot is a different survey, and the reader cannot tell from the figures.
  await page.evaluate(() => window.GWT.app.loadSample('rokel'));
  await page.waitForFunction(
    () => window.GWT.app.recomputeState.running === 0 &&
          (window.GWT.app.derived.interpretations || []).length > 0,
    { timeout: 120000 });

  const soundings = await page.evaluate(
    () => window.GWT.app.derived.soundings.map((s) => s.sounding_id));
  check('ves: the sample has more than one sounding to confuse',
    soundings.length > 1, JSON.stringify(soundings));

  // The whole Rokel survey through the app's own report build: two pegs
  // 20.7 km apart, both levelled, neither reaching basement. The ground
  // profile follows the rule the section follows and is refused, with its
  // reason in the list of what was not drawn; it used to draw a straight
  // 71 to 68 m slope across the 20.7 km the section refused to cross.
  const rokelReport = await issued('geophysical');
  const notDrawn = rokelReport.slice(rokelReport.indexOf('Not drawn from this survey'));
  check('geophysical: the ground profile is refused across 20.7 km, and says why',
    !rokelReport.includes('Ground surface along the survey traverse, from the ' +
      'elevation recorded') &&
    notDrawn.includes('Ground profile: the levelled stations are 20,751 m apart'),
    notDrawn.slice(0, 900));
  check('geophysical: the depth-to-bedrock refusal names the missing basement',
    notDrawn.includes('did not reach basement within the depth they resolve, so ' +
      'they have no depth to bedrock') &&
    !/Depth to bedrock map:[^\n]*Record the GPS position/.test(notDrawn),
    notDrawn.slice(0, 900));

  const broken = await page.evaluate(async () => {
    const C = window.GWT.core;
    const real = C.invertSounding;
    let seen = 0;
    /* the FIRST sounding fails, so every later index is shifted by one - the
     * arrangement that used to rename them */
    C.invertSounding = function (s, o) {
      seen += 1;
      if (seen === 1) throw new Error('this sounding will not invert');
      return real.call(C, s, o);
    };
    try {
      await window.GWT.app.runInversions({ quiet: true });
    } finally {
      C.invertSounding = real;
    }
    window.GWT.app.goto('ves');
    await new Promise((r) => setTimeout(r, 200));
    const d = window.GWT.app.derived;
    return {
      soundings: d.soundings.map((s) => s.sounding_id),
      interpreted: d.interpretations.map((interp) => interp.sounding_id),
      /* what the page actually captions each figure with */
      captions: Array.from(document.querySelectorAll('#page-host figure figcaption'))
        .map((n) => n.textContent),
      warned: Array.from(document.querySelectorAll('#page-host .callout-warn'))
        .map((n) => n.textContent).join(' '),
    };
  });

  const failed = broken.soundings[0];
  const survived = broken.soundings.slice(1);
  check('ves: the sounding that failed is not interpreted',
    !broken.interpreted.includes(failed), JSON.stringify(broken.interpreted));
  check('ves: every sounding that did invert keeps its own name',
    survived.every((id) => broken.interpreted.includes(id)) &&
    broken.interpreted.length === survived.length,
    JSON.stringify({ survived, interpreted: broken.interpreted }));
  check('ves: no figure is captioned with the failed sounding',
    broken.captions.length > 0 &&
    !broken.captions.some((c) => c.includes(failed)),
    JSON.stringify(broken.captions));
  check('ves: the page names the sounding it could not interpret',
    broken.warned.includes(failed) &&
    broken.warned.includes('could not be interpreted'), broken.warned);

  // The .docx pairs a figure to a sounding's block by identity, not by order
  // (gwt-docx.js: f.soundingId === interp.sounding_id). A figure stamped with
  // the wrong name therefore matched no block at all, so a surviving sounding
  // got a heading, a narrative and a layer table with no curve and no model
  // under it, while its own figures sat in the package under the failed
  // sounding's name. This goes through the app's own report build - the one
  // that stamps the names - and reads the document it downloads.
  const geophysical = await issued('geophysical');
  check('ves: every surviving sounding keeps its figures in its own block',
    survived.every((id) =>
      geophysical.includes('Sounding curve and fitted model for ' + id)) &&
    !geophysical.includes('Sounding curve and fitted model for ' + failed) &&
    !geophysical.includes('Layered earth model for ' + failed),
    JSON.stringify({ survived, failed }));
  check('ves: the report does not head a block for a sounding it could not interpret',
    !new RegExp('^' + failed.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$', 'm')
      .test(geophysical), failed);

  // The geology section is the ground under the site. Nothing in the page set
  // it, so the document fell back to a fixed "crystalline basement complex"
  // paragraph on every site - Rokel's included, which is on the Bullom sands,
  // beside the report's own maps showing the Bullom Group and an
  // intergranular aquifer. The paragraph's wording is held to the Python's in
  // parity.mjs; what is held here is that the report the user gets carries it.
  const geologyNote = await page.evaluate(() => window.GWT.core.geologyParagraph(
    window.GWT.app.store.get('site'), window.GWT.app.siteLatLon()));
  check('geophysical: the geology section describes the ground the site is on',
    /Bullom Group/.test(geologyNote) && geophysical.includes(geologyNote) &&
    !geophysical.includes('crystalline basement complex'),
    geologyNote.slice(0, 240));

  // --- the browser report says what the Python report says ------------------
  // The sounding blocks, the scorecard, the annex and the array are written
  // only by gwt-docx.js; the sentences are worded in the core and held to the
  // package by parity.mjs, and this holds that the report prints them. The
  // browser report had no "Models tried", no poorly resolved boundary, no
  // suitability table, an annex nothing filled, and "a Schlumberger array"
  // whatever the sheets said.
  await page.evaluate(() => window.GWT.app.runInversions({ quiet: true }));
  const rokelDoc = await issued('geophysical');
  check('ves: every sounding block says what else was tried',
    (rokelDoc.match(/Models tried: /g) || []).length === soundings.length,
    (rokelDoc.match(/Models tried: [^\n]*/g) || []).join(' | '));
  check('ves: a poorly resolved boundary is named, and the narrative does not claim it',
    rokelDoc.includes('is poorly resolved: within its uncertainty the model collapses') &&
    rokelDoc.includes('are fitted with a 3 layer model') &&
    !rokelDoc.includes('The data at A (1) resolves a 3 layer subsurface'),
    (rokelDoc.match(/[^\n]*poorly resolved[^\n]*/g) || []).join(' | ').slice(0, 600));
  check('ves: the scorecard the ranking is decided on is printed',
    rokelDoc.includes('Suitability (0 to 100)') && rokelDoc.includes('Confidence') &&
    /Point \S+ \(\d\) ranks first \(suitability \d+ out of 100/.test(rokelDoc),
    (rokelDoc.match(/[^\n]*ranks first[^\n]*/g) || []).join(' | ').slice(0, 400));
  check('ves: the warnings the sheets raised reach the annex',
    rokelDoc.includes('Annex A. Data Verification Notes') &&
    rokelDoc.includes('[WARNING] segment_overlap_discrepancy (A (1)): ') &&
    rokelDoc.includes('156.1 and 78.7 ohm-m (ratio 1.98)'),
    rokelDoc.slice(rokelDoc.indexOf('Annex A'), rokelDoc.indexOf('Annex A') + 400));
  check('ves: the array and its reach are the sheets\', in the sheets\' terms',
    rokelDoc.includes('recorded with the Schlumberger electrode configuration') &&
    rokelDoc.includes('with AB/2 expanded to 80 m the depth of investigation here is ' +
      'about 40 m'),
    (rokelDoc.match(/[^\n]*(array\. |expanded to)[^\n]*/g) || []).join(' | ').slice(0, 600));

  /* Two points the ranking cannot separate, and a Wenner survey: built
   * straight from interpretations, since no bundled survey is either. */
  const [tieDoc, wennerDoc] = await page.evaluate(async () => {
    const C = window.GWT.core, app = window.GWT.app;
    const ab2 = [1, 2, 5, 10, 20, 40, 80];
    const survey = (array, models) => {
      const soundings = [], inversions = [], interpretations = [];
      models.forEach(([sid, rho, h]) => {
        const sounding = { site: { community: 'Testville' }, sounding_id: sid, ab2,
          mn: ab2.map(() => NaN), rho_app: ab2.map(() => 100), array_type: array,
          flags: [] };
        const model = C.layeredModel(rho, h, { fit_error_percent: 9.0, sounding_id: sid });
        soundings.push(sounding);
        inversions.push({ array_type: array, model, fit_error_percent: 9.0,
          trials: [[2, 20.0], [3, 9.0]] });
        interpretations.push(C.interpretModel(sounding, model));
      });
      return { style: app.config().style, site: { community: 'Testville' },
        interpretations, inversions, soundings, figures: [], ves: app.config().ves };
    };
    const tie = survey('schlumberger', [['VES 1', [1000, 100, 5000], [5, 20]],
      ['VES 2', [1000, 100, 5000], [5, 22]]]);
    const wenner = survey('wenner', [['W 1', [1000, 100, 5000], [5, 20]]]);
    return Promise.all([tie, wenner].map(async (context) =>
      window.__docText(await (await window.GWT.docx.geophysicalReport(context)).build())));
  });
  check('ves: a pair the ranking cannot separate is not a winner and a runner-up',
    !tieDoc.includes('(ranked 1st)') && !tieDoc.includes('Recommended VES point') &&
    tieDoc.includes('Drill at VES 2 or VES 1, which the survey cannot separate') &&
    tieDoc.includes('Points VES 2 and VES 1 cannot be told apart on geophysical grounds') &&
    tieDoc.includes('VES 2 is ahead by 2.8 points, within the 3-point margin') &&
    (tieDoc.match(/^=1st$/gm) || []).length === 2 && !tieDoc.includes('by name only') &&
    tieDoc.includes('Of these the 3-layer model is the simplest that reaches the 10 ' +
      'percent target.'),
    tieDoc.slice(tieDoc.indexOf('5. Conclusions'), tieDoc.indexOf('5. Conclusions') + 400));
  check('ves: a Wenner survey is described as one',
    wennerDoc.includes('recorded with the Wenner electrode configuration') &&
    wennerDoc.includes('with a expanded to 80 m (AB/2 of 120 m)') &&
    wennerDoc.includes('a Wenner sounding resolves the ground to roughly half of its ' +
      'largest electrode spacing a') &&
    !wennerDoc.includes('Schlumberger array') &&
    !wennerDoc.includes('Schlumberger sounding resolves'),
    wennerDoc.slice(wennerDoc.indexOf('3.2 Geophysical'), wennerDoc.indexOf('3.2 Geophysical') + 600));

  // The field-work section says what the inputs evidence and nothing else, as
  // reporting/geophysical.py's has since reports-6. The browser's still said
  // the site "was walked with the community", that the points were agreed
  // with it, and that resistivity profiling was run with a Schlumberger
  // array, for every survey: a day of field work nobody recorded.
  check('geophysical: the field work claims no walk, no agreement and no profiling',
    !geophysical.includes('walked with the community') &&
    !geophysical.includes('agreed with the community') &&
    !geophysical.includes('Resistivity Profiling') &&
    geophysical.includes('No reconnaissance record (date or field observations) ' +
      'was supplied with the sounding data') &&
    geophysical.includes('No resistivity profiling record was supplied.') &&
    /\d+ soundings? of \d+ carr(y|ies) a recorded GPS position/.test(geophysical) &&
    /electrode configuration, to determine the formation resistivities/.test(geophysical),
    geophysical.slice(geophysical.indexOf('3. Field Work'),
      geophysical.indexOf('4. Data Analysis')).slice(0, 1500));

  // --- a ranking that is cut short says so -----------------------------------
  // The coverage table is read to decide where to drill next, and it is sorted
  // worst first, so the rows that fall off the end are the ones already doing
  // worst. Showing 60 of 166 without a word looks like the whole country. The
  // same goes for the inventory it is built from: a record with no coordinates
  // is rightly dropped, but an export half full of them and a complete one
  // otherwise produce the same page.
  const coverage = await page.evaluate(async () => {
    const C = window.GWT.core, app = window.GWT.app;
    const rows = [];
    for (let i = 0; i < 400; i += 1) {
      rows.push({
        lat_deg: 7.2 + (i % 40) * 0.06,
        lon_deg: -13.1 + Math.floor(i / 40) * 0.28,
        status_clean: i % 3 ? 'Functional' : 'Non-Functional',
        report_date: '2019-01-01',
      });
    }
    /* two readable points that land inside no chiefdom - the offshore and
     * across-the-border cases the 300 km search box deliberately overhangs */
    const offshore = [
      { lat_deg: 7.0, lon_deg: -14.0, status_clean: 'Functional',
        report_date: '2019-01-01' },
      { lat_deg: 6.9, lon_deg: -14.2, status_clean: 'Functional',
        report_date: '2019-01-01' },
    ];
    /* one row with no position and one that is not a record at all */
    const skipped = [];
    app.derived.waterPoints = C.parseWpdxRecords(
      rows.concat(offshore).concat([{ lat_deg: '', lon_deg: 1 }, 'not a record']),
      skipped);
    app.derived.waterPointsSkipped = skipped;
    app.derived.waterPointsSource = 'a synthetic inventory';
    app.store.set('coverage.level', 'chiefdom');
    app.goto('coverage');
    await new Promise((r) => setTimeout(r, 400));

    const host = document.querySelector('#page-host');
    const shown = host.querySelectorAll('table.data tbody tr').length;
    let exported = null;
    const realDownload = window.GWT.support.download;
    window.GWT.support.download = function (name, data) {
      exported = { name, rows: String(data).trim().split('\r\n').length - 1 };
    };
    const buttons = Array.from(host.querySelectorAll('button'))
      .filter((b) => b.textContent.includes('Download table'));
    if (buttons.length) buttons[0].click();
    window.GWT.support.download = realDownload;

    return {
      text: host.textContent,
      shown,
      buttons: buttons.length,
      exported,
      skippedCodes: skipped.map((f) => f.code),
    };
  });

  const showing = coverage.text.match(/Showing (\d+) of ([\d,]+)/);
  check('coverage: a truncated ranking says how many it is not showing',
    !!showing && Number(showing[1]) < Number(showing[2].replace(/,/g, '')),
    showing ? showing[0] : coverage.text.slice(0, 200));
  check('coverage: the whole ranking is downloadable, not just the rows shown',
    coverage.buttons >= 1 && coverage.exported !== null &&
    coverage.exported.rows === Number(showing[2].replace(/,/g, '')),
    JSON.stringify(coverage.exported));
  // A point inside no chiefdom is left out of every area's ratio, so the
  // ranking is computed as though it were not there and the areas it belonged
  // to rank worse than the data supports. Streamlit has always said how many
  // went; this page ranked the country without them and said nothing.
  check('coverage: the ranking says how many points it left out of every area',
    /fell outside every chiefdom polygon/.test(coverage.text) &&
    /not counted in any area above/.test(coverage.text),
    coverage.text.slice(0, 400));

  check('coverage: the inventory says what it could not place',
    coverage.skippedCodes.includes('water_point_unplaced') &&
    coverage.skippedCodes.includes('water_point_unreadable') &&
    coverage.text.includes('no usable latitude'),
    JSON.stringify(coverage.skippedCodes));

  // --- one page, one population ----------------------------------------------
  // The map and the ranking were built on the 2015 census while the planning
  // view a card below projected it forward, so the same area appeared twice on
  // one screen with two different numbers of people in it and nothing saying
  // which was which. The growth rate is uniform, so the ranking does not move
  // - only the magnitudes, which are the figures anybody quotes.
  const population = await page.evaluate(async () => {
    const app = window.GWT.app;
    app.store.set('coverage.level', 'district');
    app.store.set('coverage.year', 2030);
    app.goto('coverage');
    await new Promise((r) => setTimeout(r, 400));
    const host = document.querySelector('#page-host');
    const tables = Array.from(host.querySelectorAll('table.data'));
    /* the population column of each table, keyed by area name, so the two are
     * compared on the same area rather than on row order */
    const byName = tables.map((table) => {
      const heads = Array.from(table.querySelectorAll('th')).map((n) => n.textContent);
      const nameAt = heads.findIndex((h) => h === 'District');
      const popAt = heads.findIndex((h) => h.startsWith('Population'));
      const out = {};
      if (nameAt < 0 || popAt < 0) return { label: null, values: out };
      Array.from(table.querySelectorAll('tbody tr')).forEach((tr) => {
        const cells = tr.querySelectorAll('td');
        out[cells[nameAt].textContent] = cells[popAt].textContent;
      });
      return { label: heads[popAt], values: out };
    }).filter((t) => t.label);
    return {
      tables: byName,
      title: (host.textContent.match(
        /People per functional water point, by district \((\d+)\)/) || [])[0],
      note: host.textContent.includes('Populations are projected from the 2015 census to 2030'),
    };
  });

  check('coverage: the map says which year its populations are for',
    population.title === 'People per functional water point, by district (2030)' &&
    population.note === true, JSON.stringify(population.title));
  check('coverage: every population column on the page names the same year',
    population.tables.length >= 2 &&
    population.tables.every((t) => t.label === 'Population 2030'),
    JSON.stringify(population.tables.map((t) => t.label)));

  const first = population.tables[0];
  const rest = population.tables.slice(1);
  const shared = Object.keys(first.values).filter(
    (name) => rest.every((t) => t.values[name] !== undefined));
  check('coverage: the same area has the same population in every table',
    shared.length > 0 &&
    shared.every((name) => rest.every((t) => t.values[name] === first.values[name])),
    JSON.stringify(shared.slice(0, 3).map(
      (name) => [name, first.values[name]].concat(rest.map((t) => t.values[name])))));

  // --- the same number is the same colour on every map -----------------------
  // The coverage map is the figure a district officer argues from, and it used
  // to be coloured by a scale recomputed from whatever was on it. A chiefdom at
  // 900 people per functional point was pale beside a worst case of 40,000 and
  // dark beside a worst case of 1,200 - same chiefdom, same data, opposite
  // reading - and nothing on the key said what a colour meant.
  const scale = await page.evaluate(() => {
    const C = window.GWT.core, charts = window.GWT.charts;
    const classes = C.loadServiceClasses();
    const square = (i) => ({
      type: 'Feature',
      properties: { name: 'A' + i },
      geometry: { type: 'Polygon', coordinates: [[[i, 0], [i + 1, 0],
        [i + 1, 1], [i, 1], [i, 0]]] },
    });
    function fillsFor(values) {
      const features = values.map((_, i) => square(i));
      const svg = charts.choropleth({
        features: features,
        value: (f) => values[Number(f.properties.name.slice(1))],
        name: (f) => f.properties.name,
        classes: classes, width: 200, height: 200, title: 't',
      });
      const out = {};
      svg.querySelectorAll('path[aria-label]').forEach((p) => {
        out[p.getAttribute('aria-label').split(':')[0]] = p.getAttribute('fill');
      });
      return out;
    }
    /* 900 sits in the same band on all three; only the company it keeps
     * differs. The third map is deliberately NOT rank-equivalent to the other
     * two - under a per-map quantile scale 900 is the middle value on the
     * first two and the lowest on the wide one, which is what tells a fixed
     * scale apart from a recomputed one. */
    const mild = fillsFor([900, 1200, 100]);
    const severe = fillsFor([900, 40000, 100]);
    const wide = fillsFor([900, 40000, 30000, 25000, 20000, 100]);
    const sentinels = fillsFor([900, Infinity, null]);
    /* what the shared class table says 900 and 100 should be, independent of
     * any map: the band whose ceiling first covers the value */
    const bandOf = (v) => classes.filter((c) => c.kind === 'class').find(
      (c) => c.max_people_per_point === null ||
        c.max_people_per_point === undefined || v <= Number(c.max_people_per_point));
    return {
      mild900: mild.A0, severe900: severe.A0, wide900: wide.A0,
      mild100: mild.A2, severe100: severe.A2, wide100: wide.A5,
      band900: bandOf(900).colour, band100: bandOf(100).colour,
      noSource: sentinels.A1, noData: sentinels.A2,
      table: classes.map((c) => [c.kind, c.colour]),
    };
  });

  // Pinned to the class table, not just to each other. Comparing two maps
  // proves nothing when the fixtures are rank-identical: quantile breaks are
  // rank-based, so the per-map scale this replaced satisfied every relative
  // clause while colouring 900 differently on a wider map.
  check('coverage map: the same figure is the same colour whatever else is on the map',
    scale.mild900 === scale.band900 && scale.severe900 === scale.band900 &&
    scale.wide900 === scale.band900 &&
    scale.mild100 === scale.band100 && scale.severe100 === scale.band100 &&
    scale.wide100 === scale.band100 &&
    scale.band900 !== scale.band100,
    JSON.stringify(scale));
  check('coverage map: no functional source is not the same as no data',
    scale.noSource !== scale.noData &&
    scale.noSource === scale.table.find((c) => c[0] === 'no_source')[1] &&
    scale.noData === scale.table.find((c) => c[0] === 'no_data')[1],
    JSON.stringify({ noSource: scale.noSource, noData: scale.noData }));

  // The hardest case for the note to get right is the one where the count and
  // the discards disagree completely: a BOM'd export whose first column
  // arrives as "\ufefflat_deg" loses every coordinate, so there is nothing to
  // count and everything to explain. Reporting only the count leaves "no water
  // points near this site" - the opposite of what the export says.
  const allBad = await page.evaluate(async () => {
    const C = window.GWT.core, app = window.GWT.app;
    const rows = [];
    for (let i = 0; i < 500; i += 1) {
      rows.push({ lat_deg: '', lon_deg: '', status_clean: 'Functional' });
    }
    const skipped = [];
    app.derived.waterPoints = C.parseWpdxRecords(rows, skipped);
    app.derived.waterPointsSkipped = skipped;
    app.derived.waterPointsSource = 'an export whose header did not survive';
    app.goto('waterpoints');
    await new Promise((r) => setTimeout(r, 300));
    return {
      loaded: app.derived.waterPoints.length,
      codes: skipped.map((f) => f.code),
      text: document.querySelector('#page-host').textContent,
    };
  });
  check('an inventory that parsed to nothing says why, not "none near this site"',
    allBad.loaded === 0 && allBad.codes.includes('water_point_unplaced') &&
    /no usable latitude and longitude/i.test(allBad.text),
    JSON.stringify({ loaded: allBad.loaded, codes: allBad.codes,
      text: allBad.text.slice(0, 260) }));

  // --- where the site is, as the page and its locator show it ---------------
  // The locator lit a district only when its name was typed exactly as the
  // boundary layer spells it, while the legend named whatever the sheet said:
  // "Karene" at Kamakwie, "Falaba", "Western Area" and "Port Loko District"
  // all got a key entry in a colour that was nowhere on the map.
  const locators = await page.evaluate(async () => {
    const app = window.GWT.app, charts = window.GWT.charts, docx = window.GWT.docx;
    const C = window.GWT.core;
    const saved = JSON.parse(JSON.stringify(app.store.get('site')));
    const out = [];
    const cases = [
      { district: 'Karene', lat: 9.4967, lon: -12.2405, name: 'Karene district' },
      { district: 'Falaba', lat: 9.85, lon: -11.3, name: 'Falaba district' },
      { district: 'Western Area', lat: 8.35, lon: -13.1, name: 'Western Area Rural district' },
      { district: 'Port Loko District', lat: 8.77, lon: -12.79, name: 'Port Loko district' },
      { district: 'Karene', lat: null, lon: null, name: 'Karene district' },
      { district: 'Western Area', lat: null, lon: null, name: 'Western Area' },
    ];
    const realMap = charts.siteMap, realDoc = docx.supervisionReport;
    try {
      for (const c of cases) {
        const utm = c.lat === null ? null : C.geographicToUtm(c.lat, c.lon);
        app.store.set('site', Object.assign({}, saved, {
          community: 'T', chiefdom: '', district: c.district,
          easting: utm ? utm.easting : null, northing: utm ? utm.northing : null,
          utm_zone: utm ? utm.zone : null }));
        let svg = null;
        charts.siteMap = function (spec) { svg = realMap(spec); return svg; };
        docx.supervisionReport = async () => ({ save: async () => {} });
        await app.buildReport('supervision');
        const fills = svg ? [...svg.querySelectorAll('path')]
          .map((p) => (p.getAttribute('fill') || '').toUpperCase()) : [];
        const texts = svg ? [...svg.querySelectorAll('text')].map((t) => t.textContent) : [];
        out.push({ case: c.district + (c.lat === null ? ' (no position)' : ''),
          expected: c.name, lit: fills.filter((f) => f === '#CFE0D6').length,
          legend: texts.filter((t) => / district$|^Western Area$/.test(t)) });
      }
    } finally {
      charts.siteMap = realMap;
      docx.supervisionReport = realDoc;
      app.store.set('site', saved);
    }
    return out;
  });
  check('locator: the district the key names is lit on the map',
    locators.every((l) => l.lit > 0 && l.legend.includes(l.expected)),
    JSON.stringify(locators));

  // A pair of degrees in the site's easting and northing fields was taken at
  // face value, so a longitude typed without its western sign put the site in
  // central Africa - no marker, "13.23170 E" in every report, and nothing on
  // the page to say so - while a correct western fix printed "-13.23170°E".
  const degrees = await page.evaluate(async () => {
    const app = window.GWT.app;
    const saved = JSON.parse(JSON.stringify(app.store.get('site')));
    const out = {};
    try {
      for (const [key, e, n] of [['unsigned', 13.2317, 8.4657],
        ['signed', -13.2317, 8.4657], ['abroad', 20.5, 5.25]]) {
        app.store.set('site', Object.assign({}, saved, { community: 'T', chiefdom: '',
          district: '', easting: e, northing: n, utm_zone: null }));
        app.goto('site');
        await new Promise((r) => setTimeout(r, 200));
        const latlon = app.siteLatLon();
        out[key] = { lat: latlon && latlon.lat, lon: latlon && latlon.lon,
          text: document.querySelector('#page-host').textContent };
      }
    } finally {
      app.store.set('site', saved);
    }
    return out;
  });
  check('site: an unsigned longitude in the degree fields is read as west, and says so',
    degrees.unsigned.lon === -13.2317 &&
    degrees.unsigned.text.includes('8.46570° N, 13.23170° W') &&
    degrees.unsigned.text.includes('Longitude 13.2317 was read as 13.2317 W'),
    JSON.stringify([degrees.unsigned.lat, degrees.unsigned.lon]));
  check('site: a western position is printed as west, not as a negative east',
    degrees.signed.text.includes('8.46570° N, 13.23170° W') &&
    !degrees.signed.text.includes('°E') && !degrees.signed.text.includes('was read as'),
    degrees.signed.text.slice(0, 200));
  check('site: a position outside Sierra Leone is flagged, as the Python check flags it',
    degrees.abroad.text.includes('Coordinates convert to 5.2500 N, 20.5000 E which ' +
      'is outside Sierra Leone'),
    degrees.abroad.text.slice(0, 200));

  /* A report figure is painted for paper, not for the screen it was built
   * on. The app's default theme is dark and every chart reads the live CSS
   * tokens as it is constructed, so clients were sent maps, sections and
   * borehole drawings rasterised white on black.
   *
   * Two builds run at once whenever two report cards are clicked one after
   * the other, and each turns the print palette off when it finishes. While
   * that was a switch, the first to finish turned it off under the other,
   * whose remaining figures went into its document on the dark ground. So
   * this runs two real builds together, on the dark theme, and reads the
   * background of every figure the documents were handed. */
  const printed = await page.evaluate(async () => {
    const app = window.GWT.app, charts = window.GWT.charts, docx = window.GWT.docx;
    document.documentElement.setAttribute('data-theme', 'dark');
    const onScreen = charts.palette().surface;
    const captured = [];
    const real = { geophysicalReport: docx.geophysicalReport,
      supervisionReport: docx.supervisionReport };
    Object.keys(real).forEach((name) => {
      docx[name] = async (ctx) => { captured.push(ctx); return { save: async () => {} }; };
    });
    try {
      await Promise.all([app.buildReport('geophysical'), app.buildReport('supervision')]);
    } finally {
      Object.assign(docx, real);
    }
    const images = [];
    captured.forEach((ctx) => {
      [].concat(ctx.areaMaps || [], ctx.figures || [], ctx.subsurface || [],
        [ctx.groundProfile, ctx.suitabilityMap])
        .forEach((f) => { if (f && f.image && f.image.dataUrl) images.push(f); });
    });
    const corners = [];
    for (const f of images) {
      const img = new Image();
      img.src = f.image.dataUrl;
      await img.decode();
      const canvas = document.createElement('canvas');
      canvas.width = img.width; canvas.height = img.height;
      const g = canvas.getContext('2d');
      g.drawImage(img, 0, 0);
      const px = g.getImageData(4, 4, 1, 1).data;
      corners.push({ caption: String(f.caption || '').slice(0, 48),
        rgb: [px[0], px[1], px[2]] });
    }
    return { onScreen, documents: captured.length, corners,
      backOnScreen: charts.palette().surface };
  });
  const light = (hex) => {
    const v = String(hex || '').trim().replace('#', '');
    if (v.length !== 6) return false;
    const n = [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255);
    return (0.2126 * n[0] + 0.7152 * n[1] + 0.0722 * n[2]) > 0.8;
  };
  const darkFigures = printed.corners.filter((c) =>
    (0.2126 * c.rgb[0] + 0.7152 * c.rgb[1] + 0.0722 * c.rgb[2]) / 255 <= 0.8);
  check('two reports built at once are both rasterised for paper, whatever theme the app is in',
    printed.documents === 2 && printed.corners.length >= 6 && darkFigures.length === 0 &&
    !light(printed.onScreen) && printed.backOnScreen === printed.onScreen,
    JSON.stringify({ documents: printed.documents, figures: printed.corners.length,
      dark: darkFigures, onScreen: printed.onScreen, back: printed.backOnScreen }));

  check('no console errors', consoleErrors.length === 0,
    consoleErrors.slice(0, 10).join('\n     '));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

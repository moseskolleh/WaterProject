/* The community handover sheet in the browser app (PLAN.md step 9.1).
 *
 * What the sheet says is C.communitySheetContent, which parity.mjs holds to
 * the Python engine case by case. This drives what is around it on the
 * Handover page: the card that says what the sheet will say before it is
 * built, the two things it asks for, the picture, and the document, which is
 * opened again here and read: every word of the content in its order, one
 * picture, one page's worth of margins.
 */
import { withPage } from './harness.mjs';

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

const card = (page) => page.locator('#page-host .card', { hasText: 'Community handover sheet' }).first();
const cardWords = (page) => card(page).evaluate((node) => node.textContent.replace(/\s+/g, ' '));
const toasts = (page) => page.evaluate(() => {
  const said = Array.from(document.querySelectorAll('.toast')).map((t) => t.textContent);
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  return said.join(' | ');
});

/* Build the sheet with the card's button and read the document back: its
 * words in order, its picture's size in pixels, and its margins. */
async function build(page) {
  await toasts(page);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    card(page).getByRole('button', { name: 'Community sheet (.docx)' }).click(),
  ]);
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const bytes = Array.from(Buffer.concat(chunks));
  await page.waitForFunction(() => document.querySelector('.toast'));
  const read = await page.evaluate(async (raw) => {
    const parts = await window.GWT.support.unzip(new Uint8Array(raw).buffer);
    const xml = new TextDecoder().decode(parts['word/document.xml']);
    const words = Array.from(xml.matchAll(/<w:t[^>]*>([^<]*)<\/w:t>/g)).map((m) => m[1]
      .replace(/&amp;/g, '&').replace(/&apos;/g, "'").replace(/&quot;/g, '"')
      .replace(/&lt;/g, '<').replace(/&gt;/g, '>')).filter((t) => t.trim());
    const media = Object.keys(parts).filter((name) => name.startsWith('word/media/'));
    const png = media.length ? new DataView(parts[media[0]].buffer, parts[media[0]].byteOffset) : null;
    const margin = /<w:pgMar w:top="(\d+)" w:right="(\d+)" w:bottom="(\d+)" w:left="(\d+)"/.exec(xml);
    return {
      words, pictures: media.length,
      width: png ? png.getUint32(16) : 0, height: png ? png.getUint32(20) : 0,
      margins: margin ? margin.slice(1).map(Number) : [],
    };
  }, bytes);
  return { name: download.suggestedFilename(), said: await toasts(page), ...read };
}

/* what the document must say for a content, in the order it is set */
function expected(content) {
  const out = [];
  if (content.example) out.push(content.example);
  out.push(content.title);
  for (const part of [content.water, content.quality]) {
    out.push(part.heading, part.headline);
    if (part.lines.length) out.push(part.lines.join(' '));
  }
  out.push(content.contacts.heading, ...content.contacts.header);
  content.contacts.rows.forEach((row) => row.forEach((cell) => { if (cell) out.push(cell); }));
  out.push(content.report.heading, content.report.lines.join(' '));
  out.push(content.keep_away.heading, 'Figure 1. ' + content.keep_away.caption);
  return out;
}

const contentNow = (page) => page.evaluate(() => {
  const app = window.GWT.app, handover = app.store.get('handover');
  return window.GWT.core.communitySheetContent(app.store.get('site'), {
    analysis: app.derived.analysis || null, quality: app.derived.assessment || null,
    committee: handover.committee, assetId: handover.assetId,
    hoursPerDay: handover.hoursPerDay,
    example: (app.reportReadiness('handover').requirements || []).some((r) =>
      r.key === 'field_data' && r.state !== 'met' && r.state !== 'not_applicable'),
    config: app.config(),
  });
});

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/index.html#/handover', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app &&
    document.querySelector('#page-host .page-head'));
  const notes = await page.evaluate(() => window.GWT.core.phraseTable('community_sheet.builder_notes'));

  /* --- nothing loaded ---------------------------------------------------- */
  const empty = await cardWords(page);
  check('community sheet: the Handover page has its card, in the catalogue\'s words',
    empty.includes(await page.evaluate(() => window.GWT.core.phrase('community_sheet.about'))));
  check('community sheet: with nothing loaded the card says what the sheet will say of that',
    empty.includes('How much water this borehole gives has not been measured yet.') &&
    empty.includes('Not known yet. The water has not been tested.') &&
    ['no_test', 'no_quality', 'no_committee', 'no_identifier', 'english_only']
      .every((key) => empty.includes(notes[key])) && !empty.includes(notes.example), empty);
  const labelled = await card(page).evaluate((node) => Array.from(node.querySelectorAll('input'))
    .map((input) => !!(input.labels && input.labels.length) || !!input.getAttribute('aria-label')));
  check('community sheet: its two boxes are labelled', labelled.length === 2 && labelled.every(Boolean),
    JSON.stringify(labelled));

  const blank = await build(page);
  const blankContent = await contentNow(page);
  check('community sheet: it is built with nothing loaded, and says so plainly',
    blank.said.includes('Community sheet ready.') && blank.said.includes('Document code') &&
    /^community_sheet_.*\.docx$/.test(blank.name) &&
    JSON.stringify(blank.words.slice(0, expected(blankContent).length)) ===
      JSON.stringify(expected(blankContent)),
    JSON.stringify({ said: blank.said, name: blank.name, words: blank.words.slice(0, 8) }));
  check('community sheet: one picture, the rings and their key, and margins that keep it to a page',
    blank.pictures === 1 && blank.width === 1008 && blank.height === 448 &&
    blank.margins.every((m) => m > 800 && m < 900), JSON.stringify(blank));

  /* --- the worked example that needs most care --------------------------- */
  await page.evaluate(() => window.GWT.app.loadSample('dr_timbo'));
  await page.evaluate(() => {
    window.GWT.app.store.set('handover.committee', [
      { role: 'Chairperson', name: 'Aminata Kamara', contact: '076 000 000' },
      { role: 'Caretaker', name: 'Sorie Conteh', contact: '' },
      { role: 'Treasurer', name: '', contact: '' },
    ]);
    window.GWT.app.goto('handover');
  });
  /* typed and left, as a person does: leaving the box is what tells the
   * page, and the page is drawn again with the box gone */
  const type = async (selector, text) => {
    const box = card(page).locator(selector);
    await box.fill(text);
    await box.blur();
  };
  await type('input[type="number"]', '8');
  await type('input:not([type="number"])', '  SL-WAR-8FEEVKQ-T ');
  const loaded = await cardWords(page);
  const held = await page.evaluate(() => window.GWT.app.store.get('handover'));
  check('community sheet: the hours and the identifier are kept with the project',
    held.hoursPerDay === 8 && held.assetId === 'SL-WAR-8FEEVKQ-T', JSON.stringify(held));
  check('community sheet: a short test is a first estimate from the low end, and unsafe water is not softened',
    loaded.includes('About 80 jerrycans of water a day.') &&
    loaded.includes('No, not as it is. Treat this water before you drink it.') &&
    loaded.includes(notes.first_estimate) && !loaded.includes(notes.no_hours) &&
    !loaded.includes(notes.no_identifier) && loaded.includes(notes.no_address), loaded);
  check('community sheet: a bundled example is said on the card before it is said on the sheet',
    loaded.includes('This sheet was made from example data.') && loaded.includes(notes.example), loaded);

  const sample = await build(page);
  const sampleContent = await contentNow(page);
  const want = expected(sampleContent);
  check('community sheet: the document says the content, whole and in order',
    JSON.stringify(sample.words.slice(0, want.length)) === JSON.stringify(want) &&
    sample.words[0].startsWith('This sheet was made from example data.') &&
    sample.words.some((w) => w.includes('This is a first estimate.')) &&
    sample.words.some((w) => w.includes('Manganese')) &&
    sample.words.includes('Aminata Kamara') && !sample.words.includes('Treasurer'),
    JSON.stringify({ got: sample.words.slice(0, want.length), want }));
  check('community sheet: with no report address the picture has no square to scan',
    sample.pictures === 1 && sample.width === 1008 && !sample.words.join(' ').includes('scan the square'),
    JSON.stringify({ width: sample.width }));

  /* --- a report address -------------------------------------------------- */
  await page.evaluate(() => {
    window.GWT.app.store.set('config.service.report_url', 'https://water.example.org/app/');
    window.GWT.app.render();
  });
  const linkedCard = await cardWords(page);
  const linked = await build(page);
  const dark = await page.evaluate(() => {
    /* the square is drawn where the sheet says it is: sample the picture */
    const handover = window.GWT.app.store.get('handover');
    return { payload: window.GWT.core.reportLink(handover.assetId, window.GWT.app.config().service.report_url) };
  });
  check('community sheet: with an address the sheet carries the plate\'s own link, as a square to scan',
    !linkedCard.includes(notes.no_address) && linked.pictures === 1 && linked.width === 1280 &&
    linked.height === 448 && linked.words.join(' ').includes('Or scan the square below with a phone') &&
    dark.payload === 'https://water.example.org/app/#/report/SL-WAR-8FEEVKQ-T',
    JSON.stringify({ width: linked.width, payload: dark.payload }));

  /* --- an address the registry refuses ----------------------------------- */
  await page.evaluate(() => {
    window.GWT.app.store.set('config.service.report_url', 'http://water.example.org/app/');
    window.GWT.app.render();
  });
  const refused = await cardWords(page);
  await toasts(page);
  await card(page).getByRole('button', { name: 'Community sheet (.docx)' }).click();
  await page.waitForFunction(() => document.querySelector('.toast'));
  const refusal = await toasts(page);
  check('community sheet: an address the registry will not print stops the sheet, with the reason',
    refused.includes('cannot go on a plate') && !refused.includes('What the sheet will say') &&
    refusal.includes('Could not build the community sheet') && refusal.includes('cannot go on a plate'),
    JSON.stringify({ refused: refused.slice(0, 200), refusal }));
  await page.evaluate(() => {
    window.GWT.app.store.set('config.service.report_url', '');
    window.GWT.app.render();
  });

  /* --- half hours, and the hours taken away ------------------------------ */
  await type('input[type="number"]', '6.5');
  const half = await cardWords(page);
  await type('input[type="number"]', '');
  const none = await cardWords(page);
  check('community sheet: half hours are taken, and with no hours the sheet gives an hour',
    half.includes('About 65 jerrycans of water a day.') &&
    none.includes('About 10 jerrycans of water in an hour.') && none.includes(notes.no_hours),
    JSON.stringify({ half: half.slice(300, 420), none: none.slice(300, 420) }));

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n'));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} community sheet checks passed`);
process.exit(failed.length ? 1 : 0);

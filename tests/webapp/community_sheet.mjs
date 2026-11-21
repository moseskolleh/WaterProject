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
    /* the picture itself, drawn back onto a canvas so that it can be read */
    let pixels = null;
    if (media.length) {
      const blob = new Blob([parts[media[0]]], { type: 'image/png' });
      const bitmap = await createImageBitmap(blob);
      const canvas = document.createElement('canvas');
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      canvas.getContext('2d').drawImage(bitmap, 0, 0);
      window.__sheetPicture = canvas;
      const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      /* the share of dark pixels in a part of it, in centimetres from its
       * left edge and its top, at 80 pixels to the centimetre */
      const dark = (x0, y0, x1, y1) => {
        let n = 0, all = 0;
        for (let y = Math.round(y0 * 80); y < Math.round(y1 * 80); y += 1) {
          for (let x = Math.round(x0 * 80); x < Math.round(x1 * 80); x += 1) {
            all += 1;
            if (data[(y * canvas.width + x) * 4] < 110) n += 1;
          }
        }
        return n / all;
      };
      pixels = { rings: dark(0.2, 0.2, 4.8, 4.8), key: dark(6.0, 1.2, 12.0, 3.8),
        /* the whole of the key's column, whatever height the key takes */
        column: dark(6.0, 0, canvas.width > 1100 ? 12.55 : 12.45, 5.0),
        right: canvas.width > 1100 ? dark(12.8, 0.35, 15.7, 3.25) : null,
        /* the white kept between the key and the square, beside the square */
        gap: canvas.width > 1100 ? dark(12.58, 0, 12.8, 3.3) : null,
        /* and the picture's own two edges, left and right */
        edges: dark(0, 0, 0.06, 5.0) + dark(canvas.width / 80 - 0.06, 0, canvas.width / 80, 5.0) };
    }
    return {
      words, pictures: media.length, pixels,
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
    committee: handover.committee,
    /* typed on the card, else the one the Asset registry holds */
    assetId: handover.assetId || (app.store.get('asset') || {}).asset_id || '',
    hoursPerDay: handover.hoursPerDay,
    example: (app.reportReadiness('handover').requirements || []).some((r) =>
      r.key === 'field_data' && r.state !== 'met' && r.state !== 'not_applicable'),
    config: app.config(),
    /* the language chosen on the card, while it is still on offer */
    language: window.GWT.core.textLanguages().some((l) => l.code === handover.language)
      ? handover.language : '',
  });
});

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/index.html#/handover', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app &&
    document.querySelector('#page-host .page-head'));
  /* With no translation installed, whatever this build comes to bundle: what
   * follows is the English sheet, and "none installed" is what it tests.
   * What the build does bundle is kept for the check below. */
  const bundled = await page.evaluate(() => {
    const held = window.GWT.data.translations;
    window.GWT.data.translations = {};
    window.GWT.app.render();
    return { codes: Object.keys(held),
      faulty: Object.keys(held).filter((code) => window.GWT.core.translationProblems(code, held).length) };
  });
  check('community sheet: every translation this build bundles is one it can offer',
    bundled.faulty.length === 0, JSON.stringify(bundled));
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
  /* PLAN.md step 9.2: with no translation installed nothing offers a choice
   * of language */
  const choice = await card(page).locator('select').count();
  check('community sheet: with no translation installed, no language is offered', choice === 0,
    String(choice));

  const blank = await build(page);
  const blankContent = await contentNow(page);
  check('community sheet: it is built with nothing loaded, and says so plainly',
    blank.said.includes('Community sheet ready.') && blank.said.includes('Document code') &&
    /^community_sheet_.*\.docx$/.test(blank.name) &&
    JSON.stringify(blank.words) === JSON.stringify(expected(blankContent)),
    JSON.stringify({ said: blank.said, name: blank.name, words: blank.words.slice(0, 8) }));
  check('community sheet: one picture, with rings and a key drawn in it, and margins that keep it to a page',
    blank.pictures === 1 && blank.width === 1008 && blank.height === 400 &&
    blank.pixels.rings > 0.01 && blank.pixels.rings < 0.2 &&
    blank.pixels.key > 0.005 && blank.pixels.key < 0.2 &&
    blank.margins.length === 4 && blank.margins.every((m) => m > 800 && m < 900),
    JSON.stringify({ ...blank, words: undefined }));

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
    loaded.includes('No, not as it is. This water must be treated before you drink it, or ' +
      'drinking water taken from another source.') &&
    loaded.includes(notes.first_estimate) && !loaded.includes(notes.no_hours) &&
    !loaded.includes(notes.no_identifier) && loaded.includes(notes.no_address), loaded);
  check('community sheet: a bundled example is said on the card before it is said on the sheet',
    loaded.includes('This sheet was made from example data.') && loaded.includes(notes.example), loaded);

  const sample = await build(page);
  const sampleContent = await contentNow(page);
  const want = expected(sampleContent);
  check('community sheet: the document says the content, whole and in order',
    JSON.stringify(sample.words) === JSON.stringify(want) &&
    sample.words[0].startsWith('This sheet was made from example data.') &&
    sample.words.some((w) => w.includes('This is a first estimate.')) &&
    sample.words.some((w) => w.includes('Manganese')) &&
    sample.words.includes('Aminata Kamara') && !sample.words.includes('Treasurer'),
    JSON.stringify({ got: sample.words, want }));
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
  check('community sheet: with an address the sheet says to scan the square, and the picture is wider for it',
    !linkedCard.includes(notes.no_address) && linked.pictures === 1 && linked.width === 1280 &&
    linked.height === 400 && linked.words.join(' ').includes('Or scan the square below with a phone') &&
    linked.pixels.right > 0.2 && linked.pixels.right < 0.6 && linked.pixels.rings > 0.01,
    JSON.stringify({ width: linked.width, pixels: linked.pixels }));

  /* The square is the plate's own link, module for module. Each module of
   * the symbol is looked for at its centre in the picture, dark or light,
   * for the short address above and for a long one, whose modules are
   * under four pixels wide: drawn a pixel too wide, as they once were,
   * the light ones between two dark ones are lost and no phone reads it. */
  const readSquare = () => page.evaluate(() => {
    const C = window.GWT.core, app = window.GWT.app;
    /* the identifier typed on the card, else the one the registry holds */
    const id = app.store.get('handover').assetId || (app.store.get('asset') || {}).asset_id;
    const payload = C.reportLink(C.parseAssetId(id), app.config().service.report_url);
    const code = C.qrEncode(payload, { ecc: 'H' });
    const canvas = window.__sheetPicture, ctx = canvas.getContext('2d');
    const PX = 80, side = 2.9, left = 12.8, top = 0.35, cell = side / (code.size + 2);
    let wrong = 0;
    for (let r = 0; r < code.size; r += 1) {
      for (let c = 0; c < code.size; c += 1) {
        const x = Math.round((left + (c + 1.5) * cell) * PX), y = Math.round((top + (r + 1.5) * cell) * PX);
        const dark = ctx.getImageData(x, y, 1, 1).data[0] < 128;
        if (dark !== !!code.modules[r][c]) wrong += 1;
      }
    }
    /* and the white round it, a module wide, is white */
    const edge = ctx.getImageData(Math.round((left + 0.5 * cell) * PX),
      Math.round((top + 0.5 * cell) * PX), 1, 1).data[0];
    return { payload, size: code.size, wrong, edge };
  });
  const short = await readSquare();
  await page.evaluate(() => {
    window.GWT.app.store.set('config.service.report_url',
      'https://water.programme.example.org/sierra-leone/boreholes/app/');
    window.GWT.app.render();
  });
  await build(page);
  const long = await readSquare();
  check('community sheet: every module of the square is drawn where the plate\'s link puts it',
    short.payload === 'https://water.example.org/app/#/report/SL-WAR-8FEEVKQ-T' &&
    short.wrong === 0 && short.edge > 200 && long.size > short.size && long.wrong === 0 &&
    long.edge > 200, JSON.stringify({ short, long }));

  /* --- an identifier that is not one ------------------------------------- */
  await type('input:not([type="number"])', 'SL-WAR-8FEEVKQ-X');
  const wrongId = await cardWords(page);
  await type('input:not([type="number"])', 'sl-war-8feevkq-t');
  const forgiven = await contentNow(page);
  check('community sheet: an identifier with a wrong check character is not printed, and one mistyped in case is read',
    wrongId.includes(notes.bad_identifier) && !wrongId.includes(notes.no_identifier) &&
    forgiven.report.identifier === 'SL-WAR-8FEEVKQ-T' &&
    forgiven.report.payload.endsWith('#/report/SL-WAR-8FEEVKQ-T'),
    JSON.stringify({ wrongId: wrongId.slice(-400), report: forgiven.report }));
  await type('input:not([type="number"])', 'SL-WAR-8FEEVKQ-T');

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

  /* --- one box straight after the other ---------------------------------- */
  /* Typed as a person types: the hours, then a click into the identifier
   * with no pause between. The page used to be drawn again when the first
   * box changed, which took the second out from under the click. */
  await type('input:not([type="number"])', '');
  await card(page).locator('input[type="number"]').click();
  await page.keyboard.type('7');
  await card(page).locator('input:not([type="number"])').click();
  await page.keyboard.type('SL-WAR-8FEEVKQ-T');
  await page.keyboard.press('Tab');
  const both = await page.evaluate(() => ({
    held: window.GWT.app.store.get('handover'),
    shown: Array.from(document.querySelectorAll('#page-host .card')).find((c) =>
      c.textContent.includes('Community handover sheet')).querySelector('input:not([type="number"])').value,
    focusLost: document.activeElement === document.body ||
      (document.activeElement.classList && document.activeElement.classList.contains('skip-link')),
  }));
  const after = await cardWords(page);
  check('community sheet: a box typed into straight after the other keeps what was typed, and the keyboard',
    both.held.hoursPerDay === 7 && both.held.assetId === 'SL-WAR-8FEEVKQ-T' &&
    both.shown === 'SL-WAR-8FEEVKQ-T' && !both.focusLost &&
    after.includes('About 70 jerrycans of water a day.') && !after.includes(notes.no_identifier),
    JSON.stringify(both));

  /* --- the registry's own identifier ------------------------------------- */
  await page.evaluate(() => {
    const app = window.GWT.app;
    app.store.set('handover.assetId', '');
    app.store.set('asset', { asset_id: 'SL-WAR-8FEEVKQ-T', community: 'Dr. Timbo\'s Residence' });
    app.render();
  });
  const offered = await page.evaluate(() => Array.from(document.querySelectorAll('#page-host .card'))
    .find((c) => c.textContent.includes('Community handover sheet'))
    .querySelector('input:not([type="number"])').value);
  const fromRegistry = await cardWords(page);
  check('community sheet: with nothing typed the box starts from the identifier the Asset registry holds',
    offered === 'SL-WAR-8FEEVKQ-T' && !fromRegistry.includes(notes.no_identifier),
    JSON.stringify({ offered }));

  /* --- another language (PLAN.md step 9.2) ------------------------------- */
  /* None is bundled, so one is made up here: every entry the sheet prints,
   * as its own English with two letters in front that Krio is written with
   * and English is not, so that a sentence left in English is seen at once.
   * Beside it, one with a single sentence, and one nobody checked. */
  const MARK = '\u025b\u0254 ';
  await page.evaluate((mark) => {
    const app = window.GWT.app, english = window.GWT.data.text.community_sheet;
    const builders = ['about', 'too_many_contacts', 'in_language', 'not_translated',
      'translation_refused', 'builder_notes'];
    const whole = {};
    Object.keys(english).forEach((key) => {
      if (builders.includes(key)) return;
      if (typeof english[key] === 'string') { whole[key] = mark + english[key]; return; }
      whole[key] = {};
      Object.keys(english[key]).forEach((row) => { whole[key][row] = mark + english[key][row]; });
    });
    /* the rows of the key half as long again, a long word for the unit, a
     * name for the centre wider than the innermost ring and a label for the
     * square with a word no line holds: the picture has to make room for
     * every one of them */
    const long = Object.assign({}, whole, { keep_structures: {},
      keep_metres: mark + '{distance:g} druvazoglorpfrimowugzubombazedo',
      keep_centre: mark + 'Zedoglorp frimo wug',
      report_caption: mark + 'Wumma mombo wamma mummo womma mammowummamombowammamummowommamammo {id}' });
    Object.keys(whole.keep_structures).forEach((row) => {
      long.keep_structures[row] = whole.keep_structures[row] + ' zedo glorp frimo wug zub';
    });
    window.GWT.data.translations = {
      zw: { language: { name: 'Longish', translated_by: 'G. Translator', checked_by: 'H. Checker' },
        text: { community_sheet: long } },
      zz: { language: { name: 'Zedish', translated_by: 'A. Translator', checked_by: 'B. Checker' },
        text: { community_sheet: whole } },
      /* a second translation of the same name, as two dialects might be */
      zu: { language: { name: 'Zedish', translated_by: 'I. Translator', checked_by: 'J. Checker' },
        text: { community_sheet: { title: mark + '{place}' } } },
      zy: { language: { name: 'Ypsilonian', translated_by: 'C. Translator', checked_by: 'D. Checker' },
        text: { community_sheet: { title: mark + '{place}',
          /* a doubled space, two kinds of dash and a no-break space */
          report_tell: mark + 'Zub  wug \u2014 frimo \u2013\u00a0glorp.' } } },
      yy: { language: { name: 'Unchecked', translated_by: 'E. Translator' },
        text: { community_sheet: whole } },
    };
    app.store.set('config.service.report_url', 'https://water.example.org/app/');
    app.render();
  }, MARK);
  const select = card(page).locator('select');
  const options = await select.evaluate((node) => ({
    labelled: !!(node.labels && node.labels.length),
    label: node.labels && node.labels[0] ? node.labels[0].textContent : '',
    choices: Array.from(node.options).map((o) => [o.value, o.textContent]),
    chosen: node.value,
  }));
  check('community sheet: a translation that names who checked it is offered, by name; one that does not is not',
    options.labelled && options.label.includes('Language of the sheet') && options.chosen === '' &&
    /* two of one name are told apart by their codes */
    JSON.stringify(options.choices) === JSON.stringify([['', 'English'], ['zw', 'Longish'],
      ['zy', 'Ypsilonian'], ['zu', 'Zedish (zu)'], ['zz', 'Zedish (zz)']]),
    JSON.stringify(options));
  const stillEnglish = await cardWords(page);
  check('community sheet: with a translation on offer the sheet is English until one is chosen, and nobody is told none exists',
    stillEnglish.includes('About 70 jerrycans of water a day.') && !stillEnglish.includes(MARK) &&
    !stillEnglish.includes(notes.english_only), stillEnglish.slice(0, 600));
  check('community sheet: a translation that is installed and cannot be offered is said, not passed over',
    stillEnglish.includes('A translation is installed that cannot be offered (yy)'),
    stillEnglish.slice(-400));

  await select.selectOption('zz');
  const inZedish = await cardWords(page);
  const zedish = await build(page);
  const zedishContent = await contentNow(page);
  const typed = ['Chairperson', 'Aminata Kamara', '076 000 000', 'Caretaker', 'Sorie Conteh'];
  check('community sheet: the card says what the sheet will say in the language chosen, and whose translation it is',
    inZedish.includes(MARK + 'About 70 jerrycans of water a day.') &&
    inZedish.includes('The sheet is in Zedish: translated by A. Translator, checked by B. Checker.') &&
    /* a whole translation: the card does not say that any part is English */
    !/wording yet/.test(inZedish) && inZedish.includes(notes.first_estimate) &&
    (await page.evaluate(() => window.GWT.app.store.get('handover').language)) === 'zz',
    inZedish.slice(0, 900));
  check('community sheet: the document is written in the language, every sentence of it, as a file of its own',
    /^community_sheet_.*_zz\.docx$/.test(zedish.name) && zedishContent.language.code === 'zz' &&
    zedishContent.fell_back.length === 0 &&
    JSON.stringify(zedish.words) === JSON.stringify(expected(zedishContent)) &&
    zedish.words.every((w) => typed.includes(w) || w.replace(/^Figure 1\. /, '').startsWith(MARK)) &&
    zedish.pictures === 1 && zedish.width === 1280 && zedish.pixels.right > 0.2,
    JSON.stringify({ name: zedish.name, fell: zedishContent.fell_back, got: zedish.words,
      want: expected(zedishContent) }));

  await select.selectOption('zy');
  const inPart = await cardWords(page);
  const part = await build(page);
  check('community sheet: what a translation has no words for is printed in English, and the builder is told how much',
    /parts of this sheet have no Ypsilonian wording yet and are printed in English/.test(inPart) &&
    inPart.includes('About 70 jerrycans of water a day.') && /_zy\.docx$/.test(part.name) &&
    part.words[0].startsWith('This sheet was made from example data.') &&
    part.words[1].startsWith(MARK), JSON.stringify({ card: inPart.slice(0, 500), words: part.words.slice(0, 3) }));
  /* the two document writers tidy text differently; a translated sentence
   * reaches this one as it reaches the other, dashes and spaces settled */
  check('community sheet: translated words are written one way, as typed words are',
    part.words.some((w) => w.startsWith(MARK + 'Zub wug - frimo - glorp.')),
    JSON.stringify(part.words.filter((w) => w.includes('Zub'))));

  /* a translation longer than the English: the key makes room, and the
   * square is still the plate's link, module for module */
  await select.selectOption('zw');
  const longer = await build(page);
  const longSquare = await readSquare();
  /* How the key is broken into lines is the fonts' doing and differs from
   * one machine to the next; what does not is that the key is drawn, that
   * nothing of it reaches the white beside the square, and that the square
   * is whole. */
  check('community sheet: a longer translation does not run into the square a phone scans',
    longer.width === 1280 && longSquare.wrong === 0 && longSquare.edge > 200 &&
    longer.pixels.gap === 0 && zedish.pixels.gap === 0 && longer.pixels.column > 0.005 &&
    longer.pixels.edges === 0 && zedish.pixels.edges === 0,
    JSON.stringify({ longSquare, long: longer.pixels, english: zedish.pixels }));
  /* and it is by breaking the rows and setting the distance smaller that
   * it fits, not by chance: the layout itself, for the English sheet and
   * for the longer one */
  const laid = await page.evaluate(() => {
    const app = window.GWT.app, C = window.GWT.core, handover = app.store.get('handover');
    const key = (language) => app.communitySheetPicture(C.communitySheetContent(
      app.store.get('site'), { assetId: (app.store.get('asset') || {}).asset_id,
        committee: handover.committee, config: app.config(), language })).key;
    return { english: key(''), long: key('zw') };
  });
  const lines = (key) => key.rows.flat().map((broken) => broken.length);
  check('community sheet: the English key is where it always was, and the longer one is broken and moved to fit',
    laid.english.textAt === 7.3 && laid.english.scale === 1 && laid.english.labelScale === 1 &&
    lines(laid.english).every((n) => n === 1) &&
    /* the long unit: the distance set smaller, the rows started after it */
    laid.long.labelScale < 1 && laid.long.labelWidth <= 2.2 + 1e-9 &&
    Math.abs(laid.long.textAt - (6.0 + laid.long.labelWidth + 0.1)) < 1e-9 &&
    laid.long.textAt > 7.3 && lines(laid.long).some((n) => n > 1) &&
    /* and no line of any row wider, as it is drawn, than the room it has */
    laid.long.widths.flat(2).every((w) => w <= laid.long.limit + 1e-9),
    JSON.stringify({ english: { ...laid.english, widths: undefined },
      long: { ...laid.long, widths: undefined } }));
  await page.evaluate(() => {
    window.GWT.app.store.set('config.service.report_url', '');
    window.GWT.app.render();
  });
  const noSquare = await build(page);
  const edge = await page.evaluate(() => {
    const canvas = window.__sheetPicture, ctx = canvas.getContext('2d');
    const data = ctx.getImageData(canvas.width - 10, 0, 10, canvas.height).data;
    let dark = 0;
    for (let i = 0; i < data.length; i += 4) if (data[i] < 128) dark += 1;
    return { dark, width: canvas.width };
  });
  check('community sheet: nor off the edge of the picture where there is no square',
    noSquare.width === 1008 && edge.dark === 0 && noSquare.pixels.column > 0.005 &&
    noSquare.pixels.edges === 0,
    JSON.stringify({ edge, pixels: noSquare.pixels }));

  /* a project saved where a translation was installed, opened where it is not */
  await page.evaluate(() => {
    window.GWT.data.translations = {};
    window.GWT.app.render();
  });
  const without = await cardWords(page);
  const plain = await build(page);
  check('community sheet: a language this build does not have is English again, not an error',
    (await card(page).locator('select').count()) === 0 && !without.includes(MARK) &&
    without.includes('About 70 jerrycans of water a day.') && without.includes(notes.english_only) &&
    !/_z[yz]\.docx$/.test(plain.name) && !plain.words.some((w) => w.includes(MARK)),
    JSON.stringify({ card: without.slice(0, 400), name: plain.name }));

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n'));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} community sheet checks passed`);
process.exit(failed.length ? 1 : 0);

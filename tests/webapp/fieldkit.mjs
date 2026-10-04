/* The field kit (PLAN.md step 2.5), built through the browser app's button.
 *
 * What is checked:
 *   - the Field kit card is on the Templates page and on the Pumping test
 *     page, with a test loaded and without one, and offers the boreholes the
 *     project's sheets name;
 *   - the button writes a .docx holding every word and number of the
 *     engine's content (C.fieldKitContent, which parity holds to the Python
 *     engine's), in order;
 *   - each sheet's QR image, read back pixel by pixel, is the symbol of that
 *     sheet's code, module for module;
 *   - the document is the same as the copy committed in fixtures/, whose QR
 *     images tests/test_field_kit.py decodes with OpenCV.
 *
 *     node tests/webapp/fieldkit.mjs                    # check
 *     node tests/webapp/fieldkit.mjs --write-fixtures   # rewrite fixtures/
 */
import { chromium } from 'playwright';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { serveDocs } from './harness.mjs';

const WRITE = process.argv.includes('--write-fixtures');
const FIXTURES = new URL('./fixtures/', import.meta.url);
const FIXTURE = new URL('fieldkit_browser.docx', FIXTURES);

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

/* the site tests/test_field_kit.py builds its kit for, field for field */
const SITE = {
  project: 'Rokel 2026', project_ref: '', community: 'Kuntolo',
  client: 'Living Water International', district: 'Port Loko', supervisor: 'WiNGiN',
};
const BOREHOLES = 'KTL-01\nKTL|02 %x';

const { server, base } = await serveDocs();
const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));

try {
  await page.goto(base + '/index.html#/templates', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app && window.GWT.core,
    null, { timeout: 30000 });
  await page.evaluate((site) => {
    /* the downloads land here instead of on disk */
    window.__downloads = [];
    window.GWT.support.download = async (name, data) => {
      const bytes = new Uint8Array(await new Response(data).arrayBuffer());
      window.__downloads.push({ name, bytes: Array.from(bytes) });
    };
    Object.keys(site).forEach((k) => window.GWT.app.store.set('site.' + k, site[k]));
    window.GWT.app.goto('templates');
  }, SITE);
  await page.waitForSelector('[data-fieldkit=boreholes]');
  check('the Templates page has the Field kit card',
    await page.locator('[data-fieldkit=build]').count() === 1);

  await page.fill('[data-fieldkit=boreholes]', BOREHOLES);
  await page.click('[data-fieldkit=build]');
  await page.waitForFunction(() => window.__downloads.length > 0, null, { timeout: 30000 });

  const built = await page.evaluate(async (boreholes) => {
    const S = window.GWT.support, C = window.GWT.core, app = window.GWT.app;
    const file = window.__downloads[0];
    const parts = await S.unzip(new Uint8Array(file.bytes).buffer);
    const text = (name) => new TextDecoder().decode(parts[name]);
    const xml = text('word/document.xml');
    const runs = Array.from(xml.matchAll(/<w:t[^>]*>([^<]*)<\/w:t>/g))
      .map((m) => m[1].replace(/&lt;/g, '<').replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&'));
    const content = C.fieldKitContent(app.store.get('site'), boreholes.split('\n'),
      app.config());

    /* every string the content holds, in the order the document prints it */
    const expected = [];
    const tbl = (t) => {
      if (t.caption) expected.push(t.caption);
      t.header.forEach((h) => expected.push(h));
      t.rows.forEach((r) => r.forEach((c) => { if (c !== '') expected.push(c); }));
    };
    content.sheets.forEach((s) => {
      expected.push(s.title, s.code);
      if (s.warning) expected.push(s.warning);
      s.header.forEach((p) => p.forEach((c) => { if (c !== '') expected.push(c); }));
      s.notes.forEach((n) => expected.push(n));
      expected.push(s.discharge_note);
      tbl(s.discharge); tbl(s.bucket);
      expected.push(s.transcribe);
      s.blocks.forEach(tbl); tbl(s.recovery);
    });
    content.cards.forEach((card) => {
      expected.push(card.title);
      card.lines.forEach((l) => expected.push(l));
      card.tables.forEach(tbl);
      card.notes.forEach((n) => expected.push(n));
    });
    content.references.forEach((r) => expected.push(r));
    let at = 0;
    const missing = [];
    expected.forEach((want) => {
      /* a caption is printed with its number before it */
      const i = runs.findIndex((r, k) => k >= at && (r === want || r.endsWith('. ' + want)));
      if (i < 0) missing.push(want); else at = i + 1;
    });

    /* each QR image, read back module by module */
    async function modulesOf(bytes, size) {
      const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
      const canvas = document.createElement('canvas');
      canvas.width = bitmap.width; canvas.height = bitmap.height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(bitmap, 0, 0);
      const scale = bitmap.width / (size + 8);
      const px = ctx.getImageData(0, 0, bitmap.width, bitmap.height).data;
      const out = [];
      for (let r = 0; r < size; r++) {
        const row = [];
        for (let c = 0; c < size; c++) {
          const x = Math.floor((c + 4.5) * scale), y = Math.floor((r + 4.5) * scale);
          row.push(px[4 * (y * bitmap.width + x)] < 128);
        }
        out.push(row);
      }
      return out;
    }
    async function symbols(zipParts) {
      const media = Object.keys(zipParts).filter((n) => /^word\/media\//.test(n)).sort();
      const out = [];
      for (let k = 0; k < content.sheets.length; k++) {
        const code = C.qrEncode(content.sheets[k].payload, { ecc: 'H' });
        const read = await modulesOf(zipParts[media[k]], code.size);
        out.push(JSON.stringify(read) === JSON.stringify(code.modules));
      }
      return { count: media.length, match: out };
    }
    const mine = await symbols(parts);
    return {
      name: file.name, bytes: file.bytes, missing, xml,
      payloads: content.sheets.map((s) => s.payload), mine,
      decoded: content.sheets.map((s) => C.parseFieldKitPayload(s.payload)),
    };
  }, BOREHOLES);

  check('the button writes field_kit_rokel_2026.docx', built.name === 'field_kit_rokel_2026.docx',
    built.name);
  check('the document prints every word and number of the content, in order',
    built.missing.length === 0, JSON.stringify(built.missing.slice(0, 5)));
  check('one QR image for each sheet', built.mine.count === 2, String(built.mine.count));
  check('each QR image is its sheet code\'s symbol, module for module',
    built.mine.match.length === 2 && built.mine.match.every(Boolean), JSON.stringify(built.mine));
  check('the codes are the documented format',
    JSON.stringify(built.payloads) === JSON.stringify(['GWT-FK/1|pumping|Rokel 2026|KTL-01',
      'GWT-FK/1|pumping|Rokel 2026|KTL%7C02 %25x']), JSON.stringify(built.payloads));
  check('a code reads back to its project and borehole',
    built.decoded[1].project === 'Rokel 2026' && built.decoded[1].borehole === 'KTL|02 %x',
    JSON.stringify(built.decoded));

  if (WRITE) {
    await mkdir(FIXTURES, { recursive: true });
    await writeFile(FIXTURE, Buffer.from(built.bytes));
    console.log('wrote ' + FIXTURE.pathname);
  } else {
    const fixture = Array.from(await readFile(FIXTURE));
    const same = await page.evaluate(async ({ bytes, xml }) => {
      const parts = await window.GWT.support.unzip(new Uint8Array(bytes).buffer);
      return new TextDecoder().decode(parts['word/document.xml']) === xml;
    }, { bytes: fixture, xml: built.xml });
    check('the document is the one committed in fixtures/fieldkit_browser.docx', same,
      'run: node tests/webapp/fieldkit.mjs --write-fixtures');
  }

  /* the box keeps what was typed into it while the session lasts */
  await page.evaluate(() => window.GWT.app.goto('pumping'));
  await page.waitForSelector('[data-fieldkit=boreholes]');
  check('the Pumping test page has the Field kit card with no test loaded',
    await page.locator('[data-fieldkit=build]').count() === 1);
  check('the box keeps the boreholes typed into it on another page',
    await page.inputValue('[data-fieldkit=boreholes]') === BOREHOLES);

  /* a fresh session offers the boreholes the project's sheets name */
  const fresh = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  fresh.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));
  await fresh.goto(base + '/index.html#/pumping', { waitUntil: 'load' });
  await fresh.waitForFunction(() => window.GWT && window.GWT.app, null, { timeout: 30000 });
  await fresh.evaluate(async () => {
    await window.GWT.app.loadSample('dr_timbo');
    window.GWT.app.goto('pumping');
  });
  await fresh.waitForFunction(() => window.GWT.app.derived.test, null, { timeout: 30000 });
  await fresh.evaluate(() => window.GWT.app.render());
  await fresh.waitForSelector('[data-fieldkit=boreholes]');
  const offered = await fresh.evaluate(() => {
    const d = window.GWT.app.derived;
    const refs = [d.log && d.log.borehole_ref, d.test.borehole_ref].filter(Boolean);
    return {
      box: document.querySelector('[data-fieldkit=boreholes]').value,
      want: refs.filter((r, i) => refs.indexOf(r) === i).join('\n'),
    };
  });
  check('with a test loaded, the card offers the boreholes its sheets name',
    offered.want !== '' && offered.box === offered.want, JSON.stringify(offered));
  await fresh.close();

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n'));
} finally {
  await browser.close();
  server.close();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} field kit checks passed`);
process.exit(failed.length ? 1 : 0);

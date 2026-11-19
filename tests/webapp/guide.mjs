/* The user guide as a page (PLAN.md step 9.5): docs/user_guide.html, built
 * from docs/user_guide.md by web/build_guide.py.
 *
 * tests/test_guide_build.py holds the page to the guide without a browser.
 * This opens it in one, as a reader would: on a laptop and on a phone, in
 * the light and in the dark, with a network and then with none. Whether the
 * screenshots in it still show the app as it is, is not asked here; that is
 * `node web/guide_shots.mjs --check`, which `nox -s browser` runs next.
 */
import { createRequire } from 'node:module';
import { chromium } from 'playwright';
import { serveDocs } from './harness.mjs';

const require = createRequire(import.meta.url);
let AXE;
try {
  AXE = require.resolve('axe-core/axe.min.js');
} catch {
  console.error('axe-core is not installed beside the checkout. Run:\n' +
    '  npm install --no-save playwright@1.56.1 axe-core@4.10.3');
  process.exit(1);
}

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

const LAPTOP = { viewport: { width: 1200, height: 800 } };
const PHONE = { viewport: { width: 390, height: 780 }, isMobile: true, hasTouch: true };

const network = { down: false };
const { server, base } = await serveDocs({ network });
const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const errors = [];

async function open(options, address = '/user_guide.html') {
  const context = await browser.newContext(options);
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  await page.goto(base + address, { waitUntil: 'load' });
  return page;
}

/* every picture scrolled past, so that the lazy ones load, then counted */
async function pictures(page) {
  return page.evaluate(async () => {
    const all = Array.from(document.querySelectorAll('main img'));
    for (const img of all) {
      img.loading = 'eager';
      if (!img.complete) await new Promise((r) => { img.onload = r; img.onerror = r; });
    }
    return {
      count: all.length,
      broken: all.filter((i) => !i.naturalWidth).map((i) => i.getAttribute('src')),
      unnamed: all.filter((i) => !i.alt.trim()).map((i) => i.getAttribute('src')),
      uncaptioned: all.filter((i) => !i.closest('figure') ||
        !i.closest('figure').querySelector('figcaption')).map((i) => i.getAttribute('src')),
      /* the size the page declares is the file's own, so nothing moves as
       * a picture arrives */
      missized: all.filter((i) => Number(i.getAttribute('width')) !== i.naturalWidth ||
        Number(i.getAttribute('height')) !== i.naturalHeight).map((i) => i.getAttribute('src')),
    };
  });
}

async function axe(page) {
  await page.addScriptTag({ path: AXE });
  return page.evaluate(async () => {
    const run = await window.axe.run(document, { resultTypes: ['violations'] });
    return run.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target).join(' | ')}`);
  });
}

try {
  /* --- a laptop ---------------------------------------------------------- */
  const laptop = await open(LAPTOP);
  const shown = await pictures(laptop);
  check('guide: every picture loads, has its words for a screen reader and its caption',
    shown.count >= 10 && !shown.broken.length && !shown.unnamed.length && !shown.uncaptioned.length,
    JSON.stringify(shown));
  check('guide: each picture is given the size of its file, so the page does not jump as it loads',
    !shown.missized.length, JSON.stringify(shown.missized));

  const links = await laptop.evaluate(() => {
    const ids = new Set(Array.from(document.querySelectorAll('[id]')).map((n) => n.id));
    const inPage = Array.from(document.querySelectorAll('a[href^="#"]'));
    const contents = Array.from(document.querySelectorAll('.contents a'));
    const sections = Array.from(document.querySelectorAll('main h2'));
    return {
      dead: inPage.filter((a) => !ids.has(a.getAttribute('href').slice(1))).map((a) => a.getAttribute('href')),
      contents: contents.length, sections: sections.length,
      sameOrder: contents.every((a, i) => sections[i] && a.getAttribute('href') === '#' + sections[i].id),
      doubled: Array.from(document.querySelectorAll('[id]')).map((n) => n.id)
        .filter((id, i, all) => all.indexOf(id) !== i),
    };
  });
  check('guide: the contents list every section, in order, and no link within the page is dead',
    links.contents === links.sections && links.contents >= 20 && links.sameOrder &&
    !links.dead.length && !links.doubled.length, JSON.stringify(links));

  const beside = await laptop.evaluate(() => {
    const nav = document.querySelector('.contents').getBoundingClientRect();
    const main = document.querySelector('main').getBoundingClientRect();
    return { beside: nav.right <= main.left + 1, open: document.querySelector('.contents details').open,
      wide: document.documentElement.scrollWidth > document.documentElement.clientWidth };
  });
  check('guide, laptop: the contents stand open beside the guide and the page is no wider than the window',
    beside.beside && beside.open && !beside.wide, JSON.stringify(beside));

  /* a section reached from the contents stops below the bar, not under it */
  await laptop.click('.contents a[href="#14-troubleshooting"]');
  await laptop.waitForTimeout(150);
  const landed = await laptop.evaluate(() => {
    const bar = document.querySelector('.top').getBoundingClientRect();
    const head = document.getElementById('14-troubleshooting').getBoundingClientRect();
    return { bar: Math.round(bar.bottom), head: Math.round(head.top) };
  });
  check('guide, laptop: a section opened from the contents is shown below the bar',
    landed.head >= landed.bar && landed.head < 400, JSON.stringify(landed));

  /* The guide names pages of the app by address. Each has to be one. */
  const routes = await laptop.evaluate(() => Array.from(new Set(
    Array.from(document.querySelectorAll('a[href^="index.html#/"]'))
      .map((a) => a.getAttribute('href').slice('index.html#/'.length).split('/')[0]))));
  const app = await open(LAPTOP, '/index.html');
  await app.waitForFunction(() => window.GWT && window.GWT.app);
  const known = await app.evaluate(() => Object.keys(window.GWT.app.PAGES));
  const unknown = routes.filter((r) => !known.includes(r));
  check('guide: every address of the app it gives is a page the app has',
    routes.length >= 10 && !unknown.length, JSON.stringify({ routes: routes.length, unknown }));

  /* and the app leads to the guide: About & method links it */
  await app.evaluate(() => window.GWT.app.goto('about'));
  await app.click('#page-host a[href="user_guide.html"]');
  await app.waitForURL(/user_guide\.html$/);
  const back = await app.evaluate(() => ({
    title: document.title, home: document.querySelector('.open-app').getAttribute('href'),
  }));
  check('guide: About & method opens it, and its bar leads back to the app',
    /User Guide/.test(back.title) && back.home === 'index.html', JSON.stringify(back));
  await app.context().close();

  const lightAxe = await axe(laptop);
  check('guide, light: axe-core finds nothing serious', !lightAxe.length, lightAxe.join('\n     '));
  await laptop.context().close();

  const dark = await open({ ...LAPTOP, colorScheme: 'dark' });
  const darkness = await dark.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const darkAxe = await axe(dark);
  check('guide, dark: the page follows the device, and axe-core finds nothing serious',
    darkness === 'rgb(13, 15, 14)' && !darkAxe.length, darkness + ' ' + darkAxe.join('\n     '));
  await dark.context().close();

  /* --- a phone ----------------------------------------------------------- */
  const phone = await open(PHONE);
  await pictures(phone);
  const narrow = await phone.evaluate(() => {
    const doc = document.documentElement;
    const tables = Array.from(document.querySelectorAll('.table-wrap'));
    return {
      wide: doc.scrollWidth > doc.clientWidth,
      closed: !document.querySelector('.contents details').open,
      /* a wide table scrolls in its own box */
      boxed: tables.every((t) => t.getBoundingClientRect().width <= doc.clientWidth),
      scrolling: tables.filter((t) => t.scrollWidth > t.clientWidth).length,
      pictures: Array.from(document.querySelectorAll('main img'))
        .every((i) => i.getBoundingClientRect().width <= doc.clientWidth),
    };
  });
  check('guide, phone: nothing is wider than the screen; a wide table scrolls inside its own box',
    !narrow.wide && narrow.boxed && narrow.pictures, JSON.stringify(narrow));
  check('guide, phone: the contents start closed, so the guide is on the first screen',
    narrow.closed, JSON.stringify(narrow));
  await phone.click('.contents summary');
  await phone.click('.contents a[href="#15-glossary"]');
  await phone.waitForTimeout(150);
  const chosen = await phone.evaluate(() => ({
    closed: !document.querySelector('.contents details').open,
    head: Math.round(document.getElementById('15-glossary').getBoundingClientRect().top),
  }));
  check('guide, phone: choosing a section closes the contents and shows the section',
    chosen.closed && chosen.head >= 0 && chosen.head < 400, JSON.stringify(chosen));
  /* the narrowest phones still in use: the bar's name and its way back
   * have to fit on one line, or the whole page scrolls sideways */
  const small = await open({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true });
  const fits = await small.evaluate(() => ({
    scroll: document.documentElement.scrollWidth, screen: document.documentElement.clientWidth,
    button: Math.round(document.querySelector('.open-app').getBoundingClientRect().right),
  }));
  check('guide, a 320 px phone: the bar fits and the page does not scroll sideways',
    fits.scroll <= fits.screen && fits.button <= fits.screen, JSON.stringify(fits));
  await small.context().close();
  const phoneAxe = await axe(phone);
  check('guide, phone: axe-core finds nothing serious', !phoneAxe.length, phoneAxe.join('\n     '));
  await phone.context().close();

  /* --- paper ------------------------------------------------------------- */
  const paper = await open(LAPTOP);
  await paper.emulateMedia({ media: 'print' });
  const printed = await paper.evaluate(() => ({
    bar: getComputedStyle(document.querySelector('.top')).display,
    contents: getComputedStyle(document.querySelector('.contents')).display,
    ground: getComputedStyle(document.body).backgroundColor,
  }));
  check('guide, printed: the bar and the contents are left off, and the paper is white',
    printed.bar === 'none' && printed.contents === 'none' && printed.ground === 'rgb(255, 255, 255)',
    JSON.stringify(printed));
  await paper.context().close();

  /* --- no network -------------------------------------------------------- */
  /* The guide and its pictures are in the release the service worker puts
   * on the device, so a device that has opened the app once reads the guide
   * with nothing to fetch it from. */
  const context = await browser.newContext(LAPTOP);
  const first = await context.newPage();
  await first.goto(base + '/index.html', { waitUntil: 'load' });
  await first.evaluate(async () => {
    await navigator.serviceWorker.ready;
    for (let i = 0; i < 100 && !navigator.serviceWorker.controller; i += 1) {
      await new Promise((r) => setTimeout(r, 100));
    }
  });
  network.down = true;
  const offline = await context.newPage();
  let opened = true;
  try {
    await offline.goto(base + '/user_guide.html', { waitUntil: 'load' });
  } catch {
    opened = false;
  }
  const kept = opened ? await pictures(offline) : { count: 0, broken: ['the page itself'] };
  const styled = opened && await offline.evaluate(() =>
    getComputedStyle(document.querySelector('.top')).position === 'sticky');
  check('guide, no network: the page, its stylesheet and every picture come from the device',
    opened && styled && kept.count >= 10 && !kept.broken.length, JSON.stringify(kept));
  network.down = false;
  await context.close();

  check('no console errors', errors.length === 0, errors.join('\n'));
} finally {
  await browser.close();
  server.close();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} guide checks passed`);
process.exit(failed.length ? 1 : 0);

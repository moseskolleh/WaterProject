/* The user guide's screenshots (PLAN.md step 9.5).
 *
 * docs/user_guide.md shows the browser app as it is, and a picture of an app
 * goes stale the day a page is reworded. So no screenshot is taken by hand:
 * each is a line in SHOTS below, taken here from the app in docs/ with one of
 * the bundled worked examples loaded, at a fixed size, a fixed clock and the
 * light theme.
 *
 *     node web/guide_shots.mjs            retake the shots whose page changed
 *     node web/guide_shots.mjs --all      retake every shot (before a release)
 *     node web/guide_shots.mjs --check    fail if a shot shows a page that has
 *                                         since changed (CI, nox -s browser)
 *     node web/guide_shots.mjs --release  fail if the app changed at all since
 *                                         the last --all (the release workflow)
 *
 * What "changed" means. Two machines do not draw the same pixels, so the
 * pictures are not compared. Beside each picture is kept the text of the
 * page it shows, in web/guide/<name>.txt, and --check opens every page again
 * and compares the words: a heading renamed, a button added or a sentence
 * reworded fails it and names the shot and the first words that differ.
 *
 * The words, and not the numbers among them. The first run of this check in
 * CI failed on a page that had not changed: the Geophysics page said an
 * inversion took 16 iterations on the machine that took the picture and 18
 * on CI's, whose browser is another version, and a fitted value can differ
 * in its last printed digit the same way. So every number is read as "a
 * number here": one that moved fails nothing, one that appeared or went
 * does. The record keeps the numbers as they were seen, so that it reads as
 * the page did.
 *
 * A number that moved, like a change only to how a page looks, is what
 * --release is for: web/guide/shots.json records a hash of the app's files
 * when every shot was last retaken, and a release whose app is not that app
 * is refused until they are retaken. --release reads files and starts no
 * browser.
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const REPO = fileURLToPath(new URL('../', import.meta.url));
const DOCS = REPO + 'docs/';
/* the pictures, published beside the guide that shows them */
const PICTURES = DOCS + 'guide/';
/* the words each picture was taken of, and the hash of the app */
const RECORD = REPO + 'web/guide/';
const LOCK = RECORD + 'shots.json';

/* One clock for every run: a page that prints today's date prints this one.
 * Mid-morning in Freetown, in the dry season when the drilling is done. */
const NOW = '2026-02-12T10:30:00Z';

const DEVICES = {
  /* a small laptop: the navigation beside the page, and a picture that is
   * still legible when the guide is read on a phone */
  laptop: { viewport: { width: 1120, height: 760 }, deviceScaleFactor: 1 },
  /* a phone held upright, at the two device pixels to one that phones have */
  phone: { viewport: { width: 390, height: 760 }, deviceScaleFactor: 2,
    isMobile: true, hasTouch: true },
};

/* The shots, in the order the guide uses them.
 *
 *   name    the picture is docs/guide/<name>.png
 *   device  a key of DEVICES
 *   sample  the worked example loaded (a key of GWT.data.samples), or none
 *   route   the page, as the address after #/
 *   at      the heading of a card on the page: the window is scrolled to it.
 *           Without it the picture is of the top of the page.
 *   before  what to do on the page before the picture is taken
 *
 * Each picture is of the window, not of the whole page: a page here runs to
 * several screens, and a picture that long is unreadable in a guide.
 */
const SHOTS = [
  { name: 'overview', device: 'laptop', sample: 'rokel', route: 'overview' },
  { name: 'navigation-phone', device: 'phone', sample: 'rokel', route: 'overview',
    before: async (page) => { await page.click('#nav-toggle'); } },
  { name: 'templates', device: 'laptop', sample: null, route: 'templates' },
  { name: 'ves', device: 'laptop', sample: 'rokel', route: 'ves' },
  { name: 'ves-sounding', device: 'laptop', sample: 'rokel', route: 'ves', at: 'A (1)' },
  { name: 'ves-copilot', device: 'phone', sample: null, route: 'vescopilot' },
  { name: 'design', device: 'laptop', sample: 'dr_timbo', route: 'design', at: 'Construction' },
  { name: 'pumping', device: 'laptop', sample: 'kuntolo', route: 'pumping' },
  { name: 'pumping-analysis', device: 'laptop', sample: 'dr_timbo', route: 'pumping', at: 'Analysis' },
  { name: 'pumping-copilot', device: 'phone', sample: null, route: 'pumpcopilot' },
  { name: 'drilling-copilot', device: 'phone', sample: null, route: 'drillcopilot' },
  { name: 'quality', device: 'laptop', sample: 'dr_timbo', route: 'quality' },
  { name: 'guided', device: 'laptop', sample: null, route: 'guided' },
  { name: 'training', device: 'laptop', sample: null, route: 'training' },
  { name: 'costing', device: 'laptop', sample: 'dr_timbo', route: 'costing' },
  { name: 'supervision', device: 'laptop', sample: 'dr_timbo', route: 'supervision' },
  { name: 'handover', device: 'laptop', sample: 'dr_timbo', route: 'handover' },
  { name: 'site', device: 'laptop', sample: 'rokel', route: 'site' },
  { name: 'site-map', device: 'laptop', sample: 'rokel', route: 'site', at: 'Where the site sits' },
];

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

/* The app, as one hash: the page, its stylesheet and every script. The
 * guide's own files are not in it, so retaking the pictures does not move it. */
async function appDigest() {
  const files = ['index.html', 'css/gwt.css'];
  for (const name of (await readdir(DOCS + 'js')).sort()) {
    if (name.endsWith('.js')) files.push('js/' + name);
  }
  const whole = createHash('sha256');
  for (const file of files) {
    whole.update(file + '\0' + sha256(await readFile(DOCS + file)) + '\n');
  }
  return whole.digest('hex');
}

async function readLock() {
  try {
    return JSON.parse(await readFile(LOCK, 'utf8'));
  } catch {
    return { app: '', shots: [] };
  }
}

async function readText(path) {
  try {
    return await readFile(path, 'utf8');
  } catch {
    return null;
  }
}

/* The page's words as lines of a text file: every run of white space one
 * space, then broken at about a hundred characters so that a reworded
 * sentence is a short diff. */
function asLines(words) {
  const lines = [];
  let line = '';
  for (const word of words.replace(/\s+/g, ' ').trim().split(' ')) {
    if (line && line.length + 1 + word.length > 100) {
      lines.push(line);
      line = word;
    } else {
      line = line ? line + ' ' + word : word;
    }
  }
  if (line) lines.push(line);
  return lines.join('\n') + '\n';
}

/* A page's words with every number read as "a number here" (the header
 * says why), and the line breaks of the record, which fall where the
 * lengths of the numbers put them, read as spaces. */
function wordsOf(text) {
  return text.replace(/\d[\d.,]*\d|\d/g, '#').replace(/\s+/g, ' ').trim();
}

/* whether a page reads as it did when its picture was taken */
function sameWords(was, now) {
  return was !== null && wordsOf(was) === wordsOf(now);
}

/* where two texts first differ in their words, with a few either side,
 * quoted with their numbers as each was seen */
function firstDifference(was, now) {
  const a = was.trim().split(/\s+/), b = now.trim().split(/\s+/);
  let i = 0;
  while (i < a.length && i < b.length && wordsOf(a[i]) === wordsOf(b[i])) i += 1;
  const from = Math.max(0, i - 6);
  return {
    was: a.slice(from, i + 8).join(' ') || '(nothing)',
    now: b.slice(from, i + 8).join(' ') || '(nothing)',
  };
}

async function settle(page) {
  await page.waitForFunction(() => {
    const host = document.querySelector('#page-host');
    return !!(window.GWT && window.GWT.app && host && host.querySelector('.page-head')) &&
      !host.textContent.includes('Loading the maps and figures');
  });
  await page.evaluate(() => document.fonts.ready);
  /* the charts are drawn after the page is; give a drawing frame its turn */
  await page.waitForTimeout(350);
}

/* Open the app on one device and take (or only read) that device's shots. */
async function visit(browser, base, device, shots, take) {
  const context = await browser.newContext({
    ...DEVICES[device], colorScheme: 'light', locale: 'en-GB',
    timezoneId: 'Africa/Freetown', reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.clock.setFixedTime(new Date(NOW));
  /* Two things the Overview says depend on the moment and the browser, and
   * the words of a page have to be the same on every machine. Whether a
   * browser offers to install the app is its own decision, taken differently
   * from one version to the next, so the offer is kept from the app: the
   * pictures are of the app with none made. */
  await page.addInitScript(() => {
    window.addEventListener('beforeinstallprompt', (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
    }, true);
  });
  await page.goto(base + '/index.html');
  await page.waitForFunction(() => window.GWT && window.GWT.app);
  /* And "This app is saved on the device" appears once the service worker
   * has the page, a moment after it loads: waited for, so that every
   * picture is of the app as it is once that has happened. */
  const kept = await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    for (let i = 0; i < 150 && !navigator.serviceWorker.controller; i += 1) {
      await new Promise((r) => setTimeout(r, 100));
    }
    return !!navigator.serviceWorker.controller;
  });
  if (!kept) throw new Error('the service worker did not take the page; the Overview would not say what it says on a device');
  const seen = {};
  let loaded = null;
  /* the pages shown with nothing loaded go first, while nothing is */
  const ordered = shots.filter((s) => !s.sample).concat(shots.filter((s) => s.sample));
  for (const shot of ordered) {
    if (shot.sample && loaded !== shot.sample) {
      await page.evaluate((key) => window.GWT.app.loadSample(key), shot.sample);
      loaded = shot.sample;
    }
    await page.evaluate((route) => window.GWT.app.goto(route), shot.route);
    await settle(page);
    /* the toasts a sample raises as it loads are not part of any page */
    await page.evaluate(() => document.querySelectorAll('.toast').forEach((t) => t.remove()));
    if (shot.before) {
      await shot.before(page);
      await page.waitForTimeout(250);
    }
    if (shot.at) {
      const found = await page.evaluate((heading) => {
        const card = Array.from(document.querySelectorAll('#page-host .card')).find((c) => {
          const head = c.querySelector('h2, h3, .card-head');
          return head && head.textContent.trim().startsWith(heading);
        });
        if (!card) return false;
        /* whichever of the card's ancestors scrolls: the page's own column
         * on a laptop, the document on a phone */
        let scroller = card.parentElement;
        while (scroller && scroller !== document.body) {
          const flow = getComputedStyle(scroller).overflowY;
          if ((flow === 'auto' || flow === 'scroll') && scroller.scrollHeight > scroller.clientHeight) break;
          scroller = scroller.parentElement;
        }
        const whole = !scroller || scroller === document.body;
        const bar = document.querySelector('.app-top');
        const top = whole ? (bar ? bar.getBoundingClientRect().bottom : 0)
          : scroller.getBoundingClientRect().top;
        (whole ? window : scroller).scrollBy(0, card.getBoundingClientRect().top - top - 16);
        return true;
      }, shot.at);
      if (!found) throw new Error(`${shot.name}: no card headed "${shot.at}" on #/${shot.route}`);
      await page.waitForTimeout(250);
    }
    /* The words are the whole page's, though the picture is of one window
     * of it: which words fall inside the window depends on how each machine
     * breaks its lines, and the words of the page do not. */
    const words = await page.evaluate(() => {
      const copy = document.body.cloneNode(true);
      copy.querySelectorAll('script, style, noscript, template').forEach((n) => n.remove());
      return copy.textContent;
    });
    seen[shot.name] = asLines(words);
    if (take(shot, seen[shot.name])) await page.screenshot({ path: PICTURES + shot.name + '.png' });
  }
  await context.close();
  if (errors.length) throw new Error('the app raised an error while it was photographed: ' + errors[0]);
  return seen;
}

async function main() {
  const mode = process.argv[2] || '';
  if (!['', '--all', '--check', '--release'].includes(mode)) {
    console.error('usage: node web/guide_shots.mjs [--all | --check | --release]');
    process.exit(2);
  }
  const lock = await readLock();
  const names = SHOTS.map((s) => s.name);

  if (mode === '--release') {
    const app = await appDigest();
    if (lock.app !== app) {
      console.error('The app has changed since the user guide\'s screenshots were last all\n' +
        'retaken, so some of them may show a page as it no longer looks. Retake them:\n' +
        '  nox -s guide -- --all\nand commit docs/guide and web/guide before the release is tagged.');
      process.exit(1);
    }
    console.log(`The guide's ${names.length} screenshots were all taken of this app.`);
    return;
  }

  /* imported here, so that --release needs no Playwright */
  const { chromium } = await import('playwright');
  const { serveDocs } = await import('../tests/webapp/harness.mjs');
  const { server, base } = await serveDocs();
  const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  await mkdir(PICTURES, { recursive: true });
  await mkdir(RECORD, { recursive: true });
  const stale = [];
  const taken = [];
  try {
    for (const device of Object.keys(DEVICES)) {
      const shots = SHOTS.filter((s) => s.device === device);
      const was = {};
      for (const shot of shots) was[shot.name] = await readText(RECORD + shot.name + '.txt');
      const have = {};
      for (const shot of shots) have[shot.name] = (await readText(PICTURES + shot.name + '.png')) !== null;
      const seen = await visit(browser, base, device, shots, (shot, words) => {
        const changed = !sameWords(was[shot.name], words) || !have[shot.name];
        if (mode === '--check') {
          if (changed) stale.push({ name: shot.name, was: was[shot.name], now: words, have: have[shot.name] });
          return false;
        }
        if (mode === '--all' || changed) { taken.push(shot.name); return true; }
        return false;
      });
      /* A record is written with its picture and only then: a page whose
       * words stand keeps the record of the machine that took the picture,
       * so that a number that differs here does not show as a change. */
      for (const shot of shots) {
        if (taken.includes(shot.name)) await writeFile(RECORD + shot.name + '.txt', seen[shot.name]);
      }
    }
  } finally {
    await browser.close();
    server.close();
  }

  if (mode === '--check') {
    for (const s of stale) {
      if (!s.have || s.was === null) {
        console.error(`FAIL docs/guide/${s.name}.png has not been taken`);
        continue;
      }
      const d = firstDifference(s.was, s.now);
      console.error(`FAIL docs/guide/${s.name}.png shows a page that has changed since.\n` +
        `     the picture: ... ${d.was} ...\n     the page:    ... ${d.now} ...`);
    }
    if (stale.length) {
      console.error('\nRetake them with:\n  nox -s guide\nand commit docs/guide and web/guide.');
      process.exit(1);
    }
    console.log(`ok   the guide's ${names.length} screenshots show the pages as they read now`);
    return;
  }

  /* A screenshot of this app is a few dozen flat colours: repacked in a
   * palette it is a third the size, and these go on the device with the app. */
  if (taken.length) {
    execFileSync('python', [REPO + 'web/build_guide.py', '--shrink',
      ...taken.map((name) => PICTURES + name + '.png')], { stdio: ['ignore', 'ignore', 'inherit'] });
  }

  /* a picture or a record whose shot is gone from the list goes with it */
  for (const [dir, ext] of [[PICTURES, '.png'], [RECORD, '.txt']]) {
    for (const file of await readdir(dir)) {
      if (file.endsWith(ext) && !names.includes(file.slice(0, -ext.length))) await rm(dir + file);
    }
  }
  const next = { app: mode === '--all' ? await appDigest() : lock.app, shots: names };
  await writeFile(LOCK, JSON.stringify(next, null, 2) + '\n');
  console.log(taken.length ? `retook ${taken.length} of ${names.length}: ${taken.join(', ')}`
    : `all ${names.length} screenshots already show their pages as they read now`);
  if (mode !== '--all' && next.app !== await appDigest()) {
    console.log('The app has changed since every shot was last retaken; a release needs\n' +
      '  nox -s guide -- --all');
  }
}

await main();

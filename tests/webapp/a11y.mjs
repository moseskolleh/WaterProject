/* axe-core on every page of the browser app (PLAN.md step 9.4).
 *
 * Every page is checked with an empty project, with each of the three
 * samples loaded, and in the light theme with each sample again; then the
 * states that are not a page of their own: a dialog open over a page, and
 * the navigation drawer open on a phone-sized screen. A serious or critical
 * violation fails the run unless ALLOWED below names it, with the reason it
 * is there; an entry that no longer matches anything fails the run too, so
 * the list can only get shorter. Moderate and minor findings (a heading
 * level skipped, content outside a landmark) are counted at the end and do
 * not fail it.
 *
 * axe-core is a test-only tool, installed beside Playwright, in the same
 * command (a second npm install --no-save removes what the first put
 * there), at the version CI pins as AXE_CORE_VERSION in
 * .github/workflows/ci.yml; `nox -s browser` refuses any other:
 *
 *     npm install --no-save playwright@1.56.1 axe-core@4.10.3
 *     node tests/webapp/a11y.mjs
 *
 * What axe cannot decide it reports as "incomplete" (the contrast of text
 * over the contour texture behind the pages, for one), and those are not
 * failures here: this suite holds the app to what axe can show is wrong.
 * The keyboard walkthroughs - the navigation, a dialog's focus trap and
 * focus return, the drawer - are in smoke.mjs.
 */
import { createRequire } from 'node:module';
import { withPage } from './harness.mjs';

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

/* every page the navigation lists, read off the app once it is up, so a
 * page added later is checked without anyone remembering to add it here */
let PAGES = [];
const SAMPLES = ['rokel', 'kuntolo', 'dr_timbo'];

/* The violations allowed to stand, each with why. An entry names the rule
 * and, as regular expressions, the state, the page and the element's
 * selector it covers; a field left out matches anything. None is needed
 * today: every serious and critical violation axe found when this suite was
 * written was fixed instead. */
const ALLOWED = [
  // { rule: 'color-contrast', state: /^light/, page: /^ves$/, target: /\.some-class/,
  //   reason: 'why it cannot be fixed without a decision, and whose' },
];
const used = new Set();

function allowed(state, page, rule, target) {
  const at = ALLOWED.findIndex((a) => a.rule === rule &&
    (!a.state || a.state.test(state)) && (!a.page || a.page.test(page)) &&
    (!a.target || a.target.test(target)));
  if (at >= 0) used.add(at);
  return at >= 0;
}

const minor = new Map();

/* axe over the whole document as it stands: the chrome, the page, any
 * dialog and the toasts. */
async function audit(page, state, key) {
  const found = await page.evaluate(async () => {
    const run = await window.axe.run(document, { resultTypes: ['violations'] });
    return {
      rules: run.passes.length + run.violations.length,
      violations: run.violations.map((v) => ({
        id: v.id, impact: v.impact, help: v.help,
        nodes: v.nodes.map((n) => ({ target: n.target.join(' '), summary: n.failureSummary })),
      })),
    };
  });
  const failing = [];
  for (const v of found.violations) {
    if (v.impact !== 'serious' && v.impact !== 'critical') {
      minor.set(`${v.id} (${v.impact})`, (minor.get(`${v.id} (${v.impact})`) || 0) + v.nodes.length);
      continue;
    }
    for (const n of v.nodes) {
      if (!allowed(state, key, v.id, n.target)) {
        failing.push(`${v.id} [${v.impact}] ${v.help}: ${n.target}\n       ` +
          String(n.summary || '').replace(/\s+/g, ' ').slice(0, 300));
      }
    }
  }
  check(`axe: ${state}: ${key}`, found.rules > 0 && failing.length === 0,
    found.rules > 0 ? failing.slice(0, 8).join('\n     ') + (failing.length > 8
      ? `\n     ... and ${failing.length - 8} more` : '') : 'axe ran no rules');
}

async function everyPage(page, state) {
  for (const key of PAGES) {
    /* goto's promise is the page drawn, with whatever it fetched first */
    await page.evaluate((k) => window.GWT.app.goto(k), key);
    await page.waitForTimeout(150);
    await audit(page, state, key);
  }
}

/* the theme button, pressed until the theme is the one asked for */
async function setTheme(page, theme) {
  const set = await page.evaluate((t) => {
    for (let i = 0; i < 3 && window.GWT.app.store.get('theme') !== t; i += 1) {
      document.querySelector('#top-actions button[title="Switch theme"]').click();
    }
    return window.GWT.app.store.get('theme') === t &&
      document.documentElement.getAttribute('data-theme') === t;
  }, theme);
  check(`the ${theme} theme is on`, set);
}

async function loadSample(page, key) {
  await page.evaluate((k) => window.GWT.app.loadSample(k), key);
  await page.evaluate(() => window.GWT.app.inversionsSettled());
}

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app);
  await page.addScriptTag({ path: AXE });
  const version = await page.evaluate(() => window.axe && window.axe.version);
  console.log(`axe-core ${version}`);
  check('axe-core is loaded into the page', typeof version === 'string', String(version));
  PAGES = await page.evaluate(() => Array.from(document.querySelectorAll('#app-nav .nav-item'))
    .map((b) => b.getAttribute('data-page')));
  const defined = await page.evaluate(() => Object.keys(window.GWT.app.PAGES).sort());
  check(`the navigation lists every page the app has (${PAGES.length})`,
    PAGES.length > 20 && JSON.stringify([...PAGES].sort()) === JSON.stringify(defined),
    JSON.stringify({ PAGES, defined }));

  await everyPage(page, 'empty project');
  for (const sample of SAMPLES) {
    await loadSample(page, sample);
    await everyPage(page, sample);
  }
  await setTheme(page, 'light');
  for (const sample of SAMPLES) {
    await loadSample(page, sample);
    await everyPage(page, 'light, ' + sample);
  }
  await setTheme(page, 'dark');

  /* A dialog open over a page: the confirmation on Settings, and a
   * sounding curve's numbers as a table over the Geophysics page. */
  await loadSample(page, 'rokel');
  for (const [key, open] of [
    ['settings', 'Reset everything'],
    ['ves', 'Table'],
  ]) {
    await page.evaluate((k) => window.GWT.app.goto(k), key);
    await page.waitForTimeout(150);
    const opened = await page.evaluate((label) => {
      const button = Array.from(document.querySelectorAll('#page-host button'))
        .find((b) => b.textContent === label);
      if (button) button.click();
      return !!document.querySelector('.modal-overlay [role="dialog"]');
    }, open);
    check(`a dialog opens from ${key}: ${open}`, opened);
    if (opened) await audit(page, 'dialog open', key);
    await page.keyboard.press('Escape');
  }

  /* The navigation drawer, open on a phone. */
  await page.setViewportSize({ width: 412, height: 915 });
  await page.evaluate(() => window.GWT.app.goto('overview'));
  /* the drawer's visibility follows its slide, 0.22 s */
  await page.waitForTimeout(300);
  await audit(page, 'phone', 'overview');
  await page.click('#nav-toggle');
  await page.waitForTimeout(300);
  await audit(page, 'phone, drawer open', 'overview');
  await page.keyboard.press('Escape');

  ALLOWED.forEach((entry, i) => {
    check(`allow-list entry ${i + 1} (${entry.rule}) still matches something`, used.has(i),
      'nothing matches it any more: take it off the list');
  });
  if (minor.size) {
    console.log('\nmoderate and minor findings, not failed:');
    for (const [rule, n] of [...minor.entries()].sort()) console.log(`  ${rule}: ${n}`);
  }
  check('no console errors', consoleErrors.length === 0, consoleErrors.slice(0, 10).join('\n     '));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

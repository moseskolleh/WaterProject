/* Training: find the fault (PLAN.md step 9.3).
 *
 * The page shows three results the toolkit once got wrong and asks what is
 * wrong with each. Two things are held here. First, that the page keeps its
 * promise: the finding and the fix are not on it until the fault is found,
 * a wrong answer says why and gives nothing away, and what a trainee has
 * found is still found after a reload. Second, that what each exercise says
 * the toolkit does now is what it does: each fix is opened on the worked
 * example it names and read off the page, so a fix the engine words
 * differently one day fails here and not in front of a class.
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

/* the words of the page, as a reader has them */
const words = (page) => page.evaluate(() =>
  document.querySelector('#page-host').textContent.replace(/\s+/g, ' '));

/* the card of one exercise, by the number and title it is headed with */
const card = (page, title) => page.locator('#page-host .card', { hasText: title }).first();

async function serious(page) {
  await page.addScriptTag({ path: AXE });
  return page.evaluate(async () => {
    const run = await window.axe.run(document, { resultTypes: ['violations'] });
    return run.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map((v) => `${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target).join(' | ')}`);
  });
}

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/index.html#/training', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app &&
    document.querySelector('#page-host .training-option'));

  /* --- before any answer ------------------------------------------------- */
  const start = await page.evaluate(() => ({
    nav: (document.querySelector('#app-nav [aria-current="page"]') || {}).textContent || '',
    exercises: document.querySelectorAll('#page-host .training-options').length,
    options: Array.from(document.querySelectorAll('#page-host .training-options'))
      .map((g) => g.querySelectorAll('button:not(:disabled)').length),
    named: Array.from(document.querySelectorAll('#page-host .training-options'))
      .every((g) => g.getAttribute('role') === 'group' &&
        !!document.getElementById(g.getAttribute('aria-labelledby'))),
    progress: document.querySelector('.training-progress').textContent,
    again: Array.from(document.querySelectorAll('#page-host button'))
      .some((b) => b.textContent === 'Start again'),
  }));
  check('training: the page is in the navigation and sets three exercises of four answers each',
    start.nav.trim() === 'Training' && start.exercises === 3 &&
    start.options.join() === '4,4,4' && start.named && start.progress === '0 of 3 faults found' &&
    !start.again, JSON.stringify(start));

  const before = await words(page);
  const GIVEAWAYS = ['The finding', 'What the toolkit does now', 'Schafer', '117 minutes',
    'half-space', 'at least 40 m', '2,900 km', 'read as western'];
  check('training: neither a finding nor a fix is on the page before the fault is found',
    GIVEAWAYS.every((g) => !before.includes(g)), GIVEAWAYS.filter((g) => before.includes(g)).join(', '));
  check('training: the page says it is in the browser app only, in the catalogue\'s words',
    before.includes(await page.evaluate(() => window.GWT.core.phrase('training.browser_only'))));

  /* --- a wrong answer ---------------------------------------------------- */
  const storage = card(page, '1. The 30-minute test');
  await storage.locator('.training-option').nth(0).click();
  const wrong = await page.evaluate(() => {
    const said = document.getElementById('training-storage-said');
    const first = document.querySelector('#page-host .training-option');
    return {
      focused: document.activeElement === said, said: said ? said.textContent : '',
      disabled: first.disabled, marked: first.textContent.includes('not the fault'),
      open: document.querySelectorAll('#page-host .training-options')[0]
        .querySelectorAll('button:not(:disabled)').length,
      progress: document.querySelector('.training-progress').textContent,
    };
  });
  const afterWrong = await words(page);
  check('training: a wrong answer says why it is not the fault and puts the keyboard on that',
    wrong.focused && wrong.said.startsWith('Not the fault.') &&
    wrong.said.includes('what that drawdown was measuring'), JSON.stringify(wrong));
  check('training: a wrong answer cannot be given twice, counts for nothing, and gives nothing away',
    wrong.disabled && wrong.marked && wrong.open === 3 && wrong.progress === '0 of 3 faults found' &&
    GIVEAWAYS.every((g) => !afterWrong.includes(g)), JSON.stringify(wrong));
  const wrongAxe = await serious(page);
  check('training: axe-core finds nothing serious after a wrong answer', !wrongAxe.length,
    wrongAxe.join('\n     '));

  /* --- the right answer -------------------------------------------------- */
  await storage.locator('.training-option').nth(1).click();
  const right = await page.evaluate(() => {
    const said = document.getElementById('training-storage-said');
    const group = document.querySelectorAll('#page-host .training-options')[0];
    return {
      focused: document.activeElement === said, said: said ? said.textContent : '',
      closed: group.querySelectorAll('button:not(:disabled)').length === 0,
      marked: group.querySelectorAll('button')[1].textContent.includes('the fault'),
      progress: document.querySelector('.training-progress').textContent,
      others: ['training-halfspace-said', 'training-longitude-said']
        .filter((id) => document.getElementById(id)).length,
    };
  });
  check('training: the right answer shows the finding and the fix, and how many answers it took',
    right.focused && right.said.includes('Found, at answer 2 of 4.') &&
    right.said.includes('The finding') && right.said.includes('117 minutes') &&
    right.said.includes('What the toolkit does now') && right.said.includes('0.39 m³/h'),
    JSON.stringify(right));
  check('training: a fault found closes its question, counts once, and opens no other exercise',
    right.closed && right.marked && right.progress === '1 of 3 faults found' && right.others === 0,
    JSON.stringify(right));
  const rightAxe = await serious(page);
  check('training: axe-core finds nothing serious with a finding shown', !rightAxe.length,
    rightAxe.join('\n     '));

  /* --- kept, and forgotten when asked ------------------------------------ */
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app &&
    document.querySelector('#page-host .training-option'));
  const kept = await page.evaluate(() => ({
    progress: document.querySelector('.training-progress').textContent,
    said: (document.getElementById('training-storage-said') || {}).textContent || '',
  }));
  check('training: what was found is still found after a reload',
    kept.progress === '1 of 3 faults found' && kept.said.includes('Found, at answer 2 of 4.'),
    JSON.stringify(kept));

  /* a record somebody edited, or another build left, is read for what it
   * can be and no further: an answer that is not one of the exercise's, the
   * right answer filed as a wrong one, an exercise that does not exist */
  await page.evaluate(() => localStorage.setItem('gwt.training.v1', JSON.stringify({
    storage: { wrong: ['z', 'b', 'c', 'c'], found: 'yes' }, nothing: { found: true },
    halfspace: 'found',
  })));
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app &&
    document.querySelector('#page-host .training-option'));
  const odd = await page.evaluate(() => ({
    progress: document.querySelector('.training-progress').textContent,
    open: Array.from(document.querySelectorAll('#page-host .training-options'))
      .map((g) => g.querySelectorAll('button:not(:disabled)').length).join(),
  }));
  check('training: a record that is not as this page writes it is read no further than it can be',
    odd.progress === '0 of 3 faults found' && odd.open === '3,4,4', JSON.stringify(odd));

  await page.getByRole('button', { name: 'Start again' }).click();
  const again = await page.evaluate(() => ({
    progress: document.querySelector('.training-progress').textContent,
    open: Array.from(document.querySelectorAll('#page-host .training-options'))
      .map((g) => g.querySelectorAll('button:not(:disabled)').length).join(),
    stored: localStorage.getItem('gwt.training.v1'),
  }));
  check('training: Start again puts the three exercises back as they were',
    again.progress === '0 of 3 faults found' && again.open === '4,4,4' && again.stored === null,
    JSON.stringify(again));

  /* --- each fix is what the toolkit does --------------------------------- */
  await card(page, '1. The 30-minute test').locator('.training-option').nth(1).click();
  await page.getByRole('button', { name: 'Load the example and open its pumping test' }).click();
  await page.waitForFunction(() => location.hash === '#/pumping' &&
    document.querySelector('#page-host').textContent.includes('Yield recommendation'));
  const pumping = await words(page);
  const PUMPING = ['casing storage controls the drawdown for the first 117 minutes',
    'this test pumped for 30 minutes, entirely inside it',
    'a specific capacity of 0.089 m3/h per m', 'With a 5 inch casing',
    'The Theis fit returns a storativity of 0.18', 'at 21.7 m of residual drawdown',
    'Safe yield0.39 m3/h', 'Indicative, not established', 'below the 240 minutes needed',
    '2.93 m3/h over 32.8 m of drawdown after 30 minutes'];
  check('training, the 30-minute test: the pumping page says what the exercise says it says',
    PUMPING.every((p) => pumping.includes(p)), PUMPING.filter((p) => !pumping.includes(p)).join(' | '));

  await page.evaluate(() => window.GWT.app.goto('training'));
  await card(page, '2. The aquifer 80 m deep').locator('.training-option').nth(1).click();
  await page.getByRole('button', { name: 'Load the example and open its soundings' }).click();
  await page.waitForFunction(() => location.hash === '#/ves' &&
    document.querySelector('#page-host').textContent.includes('Drilling preference'));
  const ves = await words(page);
  const spacing = await page.evaluate(() => window.GWT.app.derived.soundings
    .map((s) => Math.max.apply(null, s.ab2)));
  const VES = ['at least 40 m', 'a minimum: the zone continues below the depth of investigation',
    'Depth to bedrocknot resolved'];
  check('training, the aquifer 80 m deep: the soundings page says what the exercise says it says',
    VES.every((p) => ves.includes(p)), VES.filter((p) => !ves.includes(p)).join(' | '));
  check('training, the aquifer 80 m deep: both soundings were laid out to an AB/2 of 80 m',
    spacing.length === 2 && spacing.every((m) => m === 80), JSON.stringify(spacing));

  await page.evaluate(() => window.GWT.app.goto('training'));
  await card(page, '3. The site 250 km away').locator('.training-option').nth(1).click();
  await page.getByRole('button', { name: 'Open Site & maps and try it' }).click();
  await page.waitForFunction(() => location.hash === '#/site');
  const read = await page.evaluate(() => ({
    typed: window.GWT.core.readLatLon('8.4657, 13.2317'),
    far: window.GWT.core.readLatLon('8.4657, 33.2317'),
    minutes: window.GWT.core.readLatLon('8 27.942, -13 13.902'),
  }));
  check('training, the site 250 km away: an unsigned longitude is read as western, with a note saying so',
    read.typed.lon === -13.2317 && read.typed.lat === 8.4657 &&
    read.typed.code === 'longitude_west_assumed' && read.typed.message.includes('2,900 km'),
    JSON.stringify(read.typed));
  check('training, the site 250 km away: degrees and minutes are read as what they are',
    Math.abs(read.minutes.lat - 8.4657) < 1e-4 && Math.abs(read.minutes.lon + 13.2317) < 1e-4,
    JSON.stringify(read.minutes));

  await page.evaluate(() => window.GWT.app.goto('training'));
  const all = await page.evaluate(() => document.querySelector('.training-progress').textContent);
  check('training: three faults found is three of three', all === '3 of 3 faults found', all);

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n'));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} training checks passed`);
process.exit(failed.length ? 1 : 0);

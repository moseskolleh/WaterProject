/* The pumping test co-pilot (PLAN.md step 2.1), played back at speed.
 *
 * The co-pilot reads the time from one place, GWT.pumpCopilotClock when a
 * test sets it, so these checks drive that clock rather than wait: the Dr
 * Timbo test is pumped for its 30 minutes and recovered for an hour in a
 * few seconds, and the Kuntolo step test for its three hours. What is
 * checked is what PLAN.md asks for:
 *
 *   - Dr Timbo's readings raise "do not stop" (and "still inside casing
 *     storage") at 30 minutes;
 *   - the Kuntolo sheet, with no discharges, cannot be written until every
 *     step carries one or an explicit "not measured" and a reason;
 *   - each warning: the pump intake, a drifting discharge, casing storage;
 *   - the schedule, its sound, and its restart when the pump stops;
 *   - a reload, and a phone that slept, come back to the right minute from
 *     the device clock, with nothing lost;
 *   - the live Cooper-Jacob estimate runs in the engine worker and says
 *     when it is steady;
 *   - the workbook written is read back by this app's own reader, and is
 *     the same, cell for cell, as the copies committed in fixtures/, which
 *     tests/test_pumping_copilot.py reads with the Python reader.
 *
 *     node tests/webapp/copilot.mjs                    # check
 *     node tests/webapp/copilot.mjs --write-fixtures   # rewrite fixtures/
 */
import { chromium } from 'playwright';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { serveDocs } from './harness.mjs';

const WRITE = process.argv.includes('--write-fixtures');
const FIXTURES = new URL('./fixtures/', import.meta.url);

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

/* 08:00 on 3 October 2026 in Freetown, which keeps UTC all year, so the
 * clock times in the fixtures are the same on any machine. */
const START = Date.UTC(2026, 9, 3, 8, 0, 0);
const MIN = 60000;

/* Dr Timbo, as transcribed in examples/data/dr_timbo: a 30-minute constant
 * test at 2.93 m3/h and an hour of recovery. */
const TIMBO_PUMPING = [[1, 13.1], [2, 15.5], [3, 17.41], [4, 18.37], [5, 19.34],
  [10, 27.34], [15, 30.76], [20, 33.34], [25, 37.77], [30, 42.26]];
const TIMBO_RECOVERY = [[1, 42.2], [2, 41.78], [3, 41.39], [4, 41.14], [5, 39.67],
  [10, 38.38], [15, 37.26], [20, 35.26], [25, 35.18], [30, 34.58], [35, 33.85],
  [40, 33.18], [45, 32.55], [50, 31.95], [55, 31.05], [60, 30.38]];

/* Kuntolo, as transcribed in examples/data/kuntolo: three hourly steps on
 * the test's own clock, no discharges, levels below the 60 m intake. */
const KUNTOLO_STEPS = [
  [[1, 10.8], [2, 11.89], [3, 12.3], [4, 12.64], [5, 12.97], [6, 13.23], [7, 13.44],
    [8, 13.6], [9, 13.7], [10, 13.8], [12, 13.91], [14, 14.06], [16, 14.14],
    [18, 14.2], [20, 14.27], [22, 14.34], [24, 14.37], [26, 14.4], [28, 14.44],
    [30, 14.48], [32, 14.51], [34, 14.55], [36, 14.57], [38, 14.61], [40, 14.66],
    [42, 14.68], [44, 14.71], [46, 14.74], [48, 14.78], [50, 14.82], [52, 14.84],
    [55, 14.86], [57, 14.89], [60, 14.96]],
  [[61, 14.98], [62, 14.99], [63, 15.31], [64, 15.54], [65, 15.65], [66, 16.1],
    [67, 16.23], [68, 16.34], [69, 16.42], [70, 16.48], [72, 16.6], [74, 16.68],
    [76, 16.73], [78, 16.8], [80, 16.88], [82, 16.96], [84, 17.03], [86, 17.1],
    [88, 17.23], [90, 17.4], [92, 17.76], [94, 18.04], [96, 18.59], [98, 20.25],
    [100, 21.3], [102, 21.82], [104, 23.1], [106, 28.63], [108, 34.76], [110, 40.41],
    [112, 41.1], [115, 46.65], [117, 48.3], [120, 52.72]],
  [[121, 55.12], [122, 56.88], [123, 57.89], [124, 58.84], [125, 60.02],
    [126, 61.03], [127, 64.25], [128, 66.35], [129, 68.56], [130, 70.26]],
];
const KUNTOLO_RECOVERY = [[1, 67.56], [2, 63.26], [3, 60], [5, 59.5], [10, 57.83],
  [20, 53.94], [30, 50.06], [40, 46.28], [60, 39.49]];

const { server, base } = await serveDocs();
const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const context = await browser.newContext({
  viewport: { width: 412, height: 915 }, timezoneId: 'Africa/Freetown',
  permissions: ['geolocation'],
  geolocation: { latitude: 8.4657, longitude: -13.2317, accuracy: 6 },
});
const page = await context.newPage();
const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));

/* Put the co-pilot's clock under the test's hand, once the page has loaded
 * it. The time is kept in sessionStorage so that it survives a reload, as
 * the device clock does. */
async function wire() {
  await page.waitForFunction(() => window.GWT && window.GWT.app && window.GWT.pumpCopilot,
    null, { timeout: 30000 });
  await page.evaluate(() => {
    window.__t = Number(sessionStorage.getItem('__t'));
    window.GWT.pumpCopilotClock = () => window.__t;
    /* the workbook downloads land here instead of on disk */
    window.__downloads = [];
    const real = window.GWT.support.download;
    window.GWT.support.download = async (name, data) => {
      const bytes = new Uint8Array(await new Response(data).arrayBuffer());
      window.__downloads.push({ name, bytes: Array.from(bytes) });
      void real;
    };
  });
}

/* Move the device clock to `ms` and let the co-pilot see it. */
async function at(ms) {
  await page.evaluate((t) => {
    window.__t = t;
    sessionStorage.setItem('__t', String(t));
    window.GWT.pumpCopilot.tick();
  }, ms);
}

async function redraw() {
  await page.evaluate(() => window.GWT.app.render());
  await page.waitForTimeout(30);
}

async function warnings() {
  return page.evaluate(() => Array.from(document.querySelectorAll('[data-warning]'))
    .map((n) => [n.getAttribute('data-warning'), n.textContent]));
}

function codes(list) { return list.map((w) => w[0]); }

async function setUp(values) {
  await page.evaluate((v) => {
    Object.keys(v).forEach((k) => window.GWT.pumpCopilot.setSetup(k, v[k]));
  }, values);
}

async function click(selector) {
  await page.click(selector);
  await page.waitForTimeout(40);
}

/* The workbook's first sheet as this app's reader sees it, and what the
 * engine's pumping reader makes of it. */
async function readBack(bytes) {
  return page.evaluate(async (b) => {
    const S = window.GWT.support, C = window.GWT.core;
    const sheets = await S.readXlsx(new Uint8Array(b).buffer);
    const test = C.pumpingFromGrid(sheets[0].rows, 'copilot.xlsx');
    return {
      sheets: sheets.map((s) => ({ name: s.name, rows: s.rows })),
      test: {
        type: test.test_type, swl: test.static_water_level_m, pump: test.pump_setting_m,
        depth: test.borehole_depth_m, ref: test.borehole_ref,
        easting: test.site.easting, northing: test.site.northing, zone: test.site.utm_zone,
        steps: test.steps.map((s) => ({ t: Array.from(s.time_min),
          wl: Array.from(s.water_level_m), q: s.discharge_m3_per_h })),
        recoveryT: test.recovery_time_min ? Array.from(test.recovery_time_min) : null,
        recoveryWl: test.recovery_level_m ? Array.from(test.recovery_level_m) : null,
        flags: test.flags.map((f) => f.code),
      },
    };
  }, Array.from(bytes));
}

/* The release in the "Written by" cell moves with every release, and is
 * not what the fixture holds the co-pilot to. */
function comparable(sheets) {
  return JSON.stringify(sheets.map((s) => ({ name: s.name, rows: s.rows.map((row) =>
    row.map((c) => (typeof c === 'string' ? c.replace(/co-pilot \d+\.\d+\.\d+\S*/, 'co-pilot X') : c))) })));
}

async function fixture(name, bytes) {
  const file = new URL(name, FIXTURES);
  if (WRITE) {
    await mkdir(FIXTURES, { recursive: true });
    await writeFile(file, Buffer.from(bytes));
    console.log('wrote ' + fileURLToPath(file));
    return true;
  }
  let committed;
  try { committed = await readFile(file); } catch { return false; }
  const ours = await readBack(bytes);
  const theirs = await readBack(committed);
  return comparable(ours.sheets) === comparable(theirs.sheets);
}

async function lastDownload(count) {
  await page.waitForFunction((n) => window.__downloads.length >= n, count);
  return page.evaluate(() => {
    const d = window.__downloads[window.__downloads.length - 1];
    return d ? { name: d.name, bytes: d.bytes } : null;
  });
}

try {
  await page.goto(base + '/index.html', { waitUntil: 'load' });
  await page.evaluate((t) => sessionStorage.setItem('__t', String(t)), START);
  await page.goto(base + '/index.html#/pumpcopilot', { waitUntil: 'load' });
  await wire();
  await at(START);

  /* ------------------------------------------------------------ setup */
  const empty = await page.evaluate(() => ({
    head: document.querySelector('#page-host h1')?.textContent,
    browserOnly: document.querySelector('#page-host p.muted')?.textContent,
    nav: !!Array.from(document.querySelectorAll('#app-nav .nav-item'))
      .find((n) => n.textContent.includes('Pumping co-pilot')),
    hash: location.hash,
  }));
  check('setup: the page opens at #/pumpcopilot, with a nav entry',
    empty.head === 'Pumping test co-pilot' && empty.nav && empty.hash === '#/pumpcopilot',
    JSON.stringify(empty));
  check('setup: the page says it exists in the browser app only, in the catalogue\'s words',
    /runs in the browser app only/.test(empty.browserOnly || ''), empty.browserOnly);

  await setUp({ community: "Dr. Timbo's Residence", client: 'Dr. Timbo', boreholeRef: 'BH-1',
    operator: 'WiNGiN', district: 'Western Area Rural', casingIn: 5, riserIn: 1.25,
    depthM: 70, pumpSettingM: 67, plannedRate: 2.93, plannedMin: 30 });
  await redraw();
  // one field through the form itself, as the crew types it
  await page.fill('input[data-setup="staticM"]', '9.44');
  await page.dispatchEvent('input[data-setup="staticM"]', 'change');
  await page.waitForTimeout(50);
  const plan = await page.evaluate(() => ({
    swl: window.GWT.pumpCopilot.session().setup.staticM,
    text: document.querySelector('[data-cp="plan"]')?.textContent || '',
    short: document.querySelector('[data-cp="plan-short"]')?.textContent || '',
  }));
  /* 5 inch casing, 1.25 inch riser, 1 m2/day through Logan's 1.22:
   * 693 x (0.127^2 - 0.03175^2) x 1.22 x 24 = 306.8 min, past 240 */
  check('before pumping: the form writes the session', plan.swl === 9.44, String(plan.swl));
  check('before pumping: Schafer\'s period for the cautious range sets "do not stop before 13:06"',
    plan.text.includes('do not stop before 13:06') && plan.text.includes('casing-storage'),
    plan.text);
  check('before pumping: a 30-minute plan is called too short', /shorter than that/.test(plan.short),
    plan.short);

  await click('button:has-text("Record GPS position")');
  await page.waitForFunction(() => !!window.GWT.pumpCopilot.session().gps, null, { timeout: 10000 });
  check('GPS: the position is taken with permission, from a button', true);

  /* ------------------------------------------------------- pumping */
  await click('button:has-text("Start the pump")');
  let live = await page.evaluate(() => ({
    phase: window.GWT.pumpCopilot.session().phase,
    countdown: document.querySelector('[data-cp="countdown"]')?.textContent,
  }));
  check('start: the pump starts on the device clock, first reading due in 30 s',
    live.phase === 'pumping' && live.countdown === '0:30', JSON.stringify(live));

  const beeps0 = await page.evaluate(() => window.GWT.pumpCopilot.beeps());
  await at(START + 0.5 * MIN);
  const due = await page.evaluate(() => ({
    beeps: window.GWT.pumpCopilot.beeps(),
    countdown: document.querySelector('[data-cp="countdown"]')?.textContent,
  }));
  check('schedule: the 0.5-minute reading falls due with a sound',
    due.beeps === beeps0 + 1 && /0.5-minute/.test(due.countdown), JSON.stringify(due));

  const slots = await page.evaluate(() => {
    const P = window.GWT.pumpCopilot;
    const out = [];
    for (let s = 0; out.length < 25; s = P.nextSlot(s)) if (s) out.push(s);
    return out;
  });
  check('schedule: 0.5 to 120 minutes log-spaced, then every 30',
    JSON.stringify(slots) === JSON.stringify([0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15,
      20, 25, 30, 40, 50, 60, 75, 90, 120, 150, 180, 210, 240]), JSON.stringify(slots));

  // the first Dr Timbo reading through the form, 3 s after the beep
  await at(START + 1 * MIN + 3000);
  await page.fill('input[data-cp="level"]', '13.1');
  await page.dispatchEvent('input[data-cp="level"]', 'change');
  await click('button[data-cp="record"]');
  const first = await page.evaluate(() => window.GWT.pumpCopilot.session().readings[0]);
  check('reading: taken 3 s after the 1-minute beep, written at minute 1',
    first && first.min === 1 && first.level === 13.1 && first.scheduled, JSON.stringify(first));

  // the bucket: 20 litres, three timings, averaged into the rate
  await page.fill('input[data-cp="bucket-timings"]', '24.5, 24.6, 24.7');
  await page.dispatchEvent('input[data-cp="bucket-timings"]', 'change');
  await page.waitForTimeout(50);
  await click('button[data-cp="record-bucket"]');
  const q = await page.evaluate(() => window.GWT.pumpCopilot.session().steps[0].discharges[0]);
  check('discharge: 20 L in 24.5, 24.6 and 24.7 s is 2.93 m3/h',
    q && Math.abs(q.rate - 20 / 24.6 * 3.6) < 1e-3 && q.method === 'bucket' &&
    q.timingsS.length === 3, JSON.stringify(q));

  for (const [m, level] of TIMBO_PUMPING.slice(1)) {
    await at(START + m * MIN + 2000);
    await page.evaluate((l) => window.GWT.pumpCopilot.record(l), level);
  }
  await redraw();
  const at30 = await warnings();
  const doNotStop = at30.find((w) => w[0] === 'do_not_stop');
  check('Dr Timbo at 30 minutes: "do not stop"', !!doNotStop && /^Do not stop before 12:00/.test(doNotStop[1]),
    JSON.stringify(at30));
  const storage = at30.find((w) => w[0] === 'casing_storage');
  /* 2.93 m3/h over 32.82 m: 0.0892 m3/h per m, 117 minutes of storage */
  check('Dr Timbo at 30 minutes: still inside casing storage, until about 09:57',
    !!storage && storage[1].includes('until about 09:57'), JSON.stringify(storage));
  check('Dr Timbo at 30 minutes: no intake or drift warning',
    !codes(at30).includes('level_at_intake') && !codes(at30).includes('discharge_drift'),
    JSON.stringify(codes(at30)));
  const readings = await page.evaluate(() => window.GWT.pumpCopilot.session().readings
    .map((r) => [r.min, r.scheduled]));
  check('reading: every Dr Timbo minute is a scheduled one',
    readings.length === 10 && readings.every((r) => r[1]), JSON.stringify(readings));
  await page.waitForFunction(() => document.querySelector('[data-cp="estimate"]')
    ?.getAttribute('data-state'));
  const est30 = await page.evaluate(() => document.querySelector('[data-cp="estimate"]')
    .getAttribute('data-state'));
  check('Dr Timbo at 30 minutes: no Cooper-Jacob estimate inside casing storage',
    est30 === 'storage', est30);
  const chart = await page.evaluate(() => document.querySelectorAll('#page-host svg circle').length);
  check('plot: drawdown against log time, one mark a reading', chart >= 10, String(chart));

  const early = await page.evaluate(() => window.GWT.pumpCopilot.save()
    .then(() => '', (e) => e.message));
  check('workbook: not written while the pump is still running',
    /has not been stopped yet/.test(early), early);

  // stopping early asks first
  await click('button[data-cp="stop"]');
  const asked = await page.evaluate(() => document.querySelector('.modal h3')?.textContent || '');
  check('stop: stopping before the time asks first', /^Stop before 12:00/.test(asked), asked);
  await click('.modal button:has-text("Stop anyway")');

  /* ------------------------------------------------------ recovery */
  const rec = await page.evaluate(() => {
    const P = window.GWT.pumpCopilot, s = P.session();
    return { phase: s.phase, stopped: s.stoppedAt, sched: P.scheduleAt(s, window.__t),
      countdown: document.querySelector('[data-cp="countdown"]')?.textContent };
  });
  check('recovery: the schedule restarts when the pump stops',
    rec.phase === 'recovery' && rec.sched.next === 0.5 &&
    rec.sched.nextAt === rec.stopped + 30000 && rec.countdown === '0:30', JSON.stringify(rec));
  const stopAt = rec.stopped;
  for (const [m, level] of TIMBO_RECOVERY.slice(0, 5)) {
    await at(stopAt + m * MIN);
    await page.evaluate((l) => window.GWT.pumpCopilot.record(l), level);
  }

  /* -------------------------------------------- reload, and a phone asleep */
  const before = await page.evaluate(() => JSON.stringify(window.GWT.pumpCopilot.session()));
  await page.evaluate(() => window.GWT.app.store.flush());
  // the phone sleeps through the 6, 8 and 10-minute readings, then the page reloads
  await page.evaluate((t) => { sessionStorage.setItem('__t', String(t)); }, stopAt + 10.5 * MIN);
  await page.reload({ waitUntil: 'load' });
  await wire();
  await at(stopAt + 10.5 * MIN);
  await redraw();
  const after = await page.evaluate(() => ({
    session: JSON.stringify(window.GWT.pumpCopilot.session()),
    elapsed: document.querySelector('[data-cp="elapsed"]')?.textContent,
    countdown: document.querySelector('[data-cp="countdown"]')?.textContent,
  }));
  check('reload: the live test comes back from IndexedDB exactly', after.session === before,
    after.session.slice(0, 200));
  check('reload: the clock is the device clock, not a timer that stopped',
    /^Recovery 10\.5 min since the pump stopped at 08:30/.test(after.elapsed || '') &&
    /10-minute/.test(after.countdown || ''), JSON.stringify(after.elapsed) + ' ' + after.countdown);
  const slept = await warnings();
  const missed = slept.find((w) => w[0] === 'readings_missed');
  check('phone asleep: the readings it slept through are named, not invented',
    !!missed && missed[1].includes('6, 8-minute readings'), JSON.stringify(missed));

  for (const [m, level] of TIMBO_RECOVERY.slice(5)) {
    await at(stopAt + m * MIN);
    await page.evaluate(([l, mm]) => window.GWT.pumpCopilot.record(l, { min: mm }), [level, m]);
  }
  await redraw();
  await click('button[data-cp="save"]');
  const timbo = await lastDownload(1);
  check('workbook: written once the pump has stopped', !!timbo &&
    timbo.name === 'bh_1_pumping_test_2026-10-03.xlsx', timbo && timbo.name);
  const back = await readBack(timbo.bytes);
  const t = back.test;
  check('workbook: this app\'s reader reads it back as the test that was run',
    t.type === 'constant+recovery' && t.swl === 9.44 && t.pump === 67 && t.depth === 70 &&
    t.ref === 'BH-1' && t.steps.length === 1 &&
    JSON.stringify(t.steps[0].t) === JSON.stringify(TIMBO_PUMPING.map((r) => r[0])) &&
    JSON.stringify(t.steps[0].wl) === JSON.stringify(TIMBO_PUMPING.map((r) => r[1])) &&
    Math.abs(t.steps[0].q - 2.927) < 1e-9 &&
    JSON.stringify(t.recoveryT) === JSON.stringify(TIMBO_RECOVERY.map((r) => r[0])) &&
    JSON.stringify(t.recoveryWl) === JSON.stringify(TIMBO_RECOVERY.map((r) => r[1])),
  JSON.stringify(t));
  check('workbook: the GPS fix is in the header as UTM, zone 28N',
    t.zone === 28 && Math.abs(t.easting - 694800) < 2000 && Math.abs(t.northing - 935900) < 2000,
    `${t.easting} ${t.northing} ${t.zone}`);
  const header = back.sheets[0].rows.map((r) => r.join('|')).join('\n');
  check('workbook: the device clock is in the header',
    header.includes('Device clock, pump started|2026-10-03T08:00:00+00:00') &&
    header.includes('Device clock, pump stopped|2026-10-03T08:30:') &&
    header.includes('Start time|08:00'), header.slice(0, 800));
  check('workbook: a second sheet keeps the co-pilot\'s log',
    back.sheets[1] && back.sheets[1].name === 'Co-pilot log' &&
    back.sheets[1].rows.some((r) => r[3] === 'bucket'), JSON.stringify(back.sheets.map((s) => s.name)));
  check('workbook: the same, cell for cell, as fixtures/copilot_dr_timbo.xlsx',
    await fixture('copilot_dr_timbo.xlsx', timbo.bytes));

  // the sheet becomes the project's pumping test, through the same reader as an upload
  await page.click('button:has-text("Use it as this project")');
  await page.waitForFunction(() => window.GWT.app.store.get('nav') === 'pumping' &&
    window.GWT.app.derived.test && window.GWT.app.recomputeState.running === 0,
  null, { timeout: 60000 });
  const used = await page.evaluate(() => {
    const d = window.GWT.app.derived;
    return { q: d.test.steps[0].discharge_m3_per_h, tc: d.analysis && d.analysis.casing_storage_min };
  });
  check('project: the written sheet is the project\'s pumping test, analysed as any other',
    Math.abs(used.q - 2.927) < 1e-9 && used.tc > 100 && used.tc < 130, JSON.stringify(used));

  /* -------------------------------------------- Kuntolo: no discharges */
  await page.evaluate(() => { window.GWT.pumpCopilot.discard(); window.GWT.app.goto('pumpcopilot'); });
  await page.waitForTimeout(50);
  const K0 = START + 24 * 60 * MIN;
  await at(K0);
  await setUp({ community: 'Kuntoloh', client: 'ACF', boreholeRef: 'KTL-01', operator: 'WiNGiN',
    district: 'Port Loko', testType: 'step', steps: 3, stepLengthMin: 60, casingIn: 5,
    riserIn: 1.25, depthM: 70, pumpSettingM: 60, staticM: 19.28, plannedRate: 1 });
  await page.evaluate(() => window.GWT.pumpCopilot.start());
  let intakeAt = null;
  for (let k = 0; k < KUNTOLO_STEPS.length; k++) {
    if (k) {
      await at(K0 + 60 * k * MIN);
      await page.evaluate(() => window.GWT.pumpCopilot.nextStep(null));
    }
    for (const [m, level] of KUNTOLO_STEPS[k]) {
      await at(K0 + m * MIN);
      await page.evaluate(([l, mm]) => window.GWT.pumpCopilot.record(l, { min: mm }), [level, m]);
      if (intakeAt === null) {
        const ws = await page.evaluate(() => window.GWT.pumpCopilot
          .evaluate(window.GWT.pumpCopilot.session(), window.__t).warnings.map((w) => w.code));
        if (ws.includes('level_at_intake')) intakeAt = m;
      }
    }
  }
  check('Kuntolo: the level at the pump intake is warned of at the first reading below it',
    intakeAt === 125, String(intakeAt));
  await redraw();
  const kw = await warnings();
  check('Kuntolo: the warning is on the page, with the missing discharge',
    codes(kw).includes('level_at_intake') && codes(kw).includes('discharge_missing'),
    JSON.stringify(codes(kw)));
  // opening a sample mid-test replaces the project, not the test in progress
  const kept = await page.evaluate(async () => {
    const before = JSON.stringify(window.GWT.pumpCopilot.session());
    await window.GWT.app.loadSample('rokel');
    const after = JSON.stringify(window.GWT.pumpCopilot.session());
    await window.GWT.app.goto('pumpcopilot');
    return { same: before === after, community: window.GWT.app.store.get('site').community };
  });
  check('a test in progress survives opening another project', kept.same && kept.community !== 'Kuntoloh',
    JSON.stringify(kept));
  await at(K0 + 130 * MIN + 1000);
  await page.evaluate(() => window.GWT.pumpCopilot.stopPump());
  const kStop = await page.evaluate(() => window.GWT.pumpCopilot.session().stoppedAt);
  for (const [m, level] of KUNTOLO_RECOVERY) {
    await at(kStop + m * MIN);
    await page.evaluate(([l, mm]) => window.GWT.pumpCopilot.record(l, { min: mm }), [level, m]);
  }
  await redraw();
  const blocked = await page.evaluate(async () => {
    const P = window.GWT.pumpCopilot;
    let refused = '';
    try { await P.save(); } catch (e) { refused = e.message; }
    return {
      refused, downloads: window.__downloads.length,
      disabled: document.querySelector('button[data-cp="save"]')?.disabled,
      said: document.querySelector('[data-cp="save-blocked"]')?.textContent || '',
    };
  });
  check('Kuntolo: the sheet cannot be written with no discharges',
    /Step 1 has no discharge/.test(blocked.refused) && /Step 3 has no discharge/.test(blocked.refused) &&
    blocked.disabled === true && blocked.downloads === 1 && /cannot be written yet/.test(blocked.said),
    JSON.stringify(blocked));
  const noReason = await page.evaluate(() => {
    try { window.GWT.pumpCopilot.setNotMeasured(0, '  '); return ''; } catch (e) { return e.message; }
  });
  check('Kuntolo: "not measured" needs a reason', /Say why/.test(noReason), noReason);
  // through the form, for step 1 (the recovery page lets the crew pick the step)
  await page.fill('input[data-cp="not-measured-reason"]', 'No bucket on site; the flow meter was not fitted.');
  await page.dispatchEvent('input[data-cp="not-measured-reason"]', 'change');
  await click('button:has-text("Record as not measured")');
  const stillBlocked = await page.evaluate(() => window.GWT.pumpCopilot
    .saveProblems(window.GWT.pumpCopilot.session()));
  check('Kuntolo: one step explained is not enough while two are not',
    stillBlocked.length === 2 && /Step 2/.test(stillBlocked[0]), JSON.stringify(stillBlocked));
  await page.evaluate(() => {
    window.GWT.pumpCopilot.setNotMeasured(1, 'No bucket on site; the flow meter was not fitted.');
    window.GWT.pumpCopilot.setNotMeasured(2, 'No bucket on site; the flow meter was not fitted.');
  });
  await redraw();
  await click('button[data-cp="save"]');
  const kuntolo = await lastDownload(2);
  check('Kuntolo: with a reason for every step, the sheet is written',
    kuntolo && kuntolo.name === 'ktl_01_pumping_test_2026-10-04.xlsx', kuntolo && kuntolo.name);
  const kb = (await readBack(kuntolo.bytes)).test;
  check('Kuntolo: read back as three steps with no discharge, and flagged so',
    kb.type === 'step+recovery' && kb.steps.length === 3 &&
    kb.steps.every((s) => s.q === null) && kb.flags.includes('missing_discharge') &&
    kb.flags.includes('level_below_pump') &&
    JSON.stringify(kb.steps.map((s) => s.t)) ===
      JSON.stringify(KUNTOLO_STEPS.map((st) => st.map((r) => r[0]))),
  JSON.stringify(kb).slice(0, 600));
  const note = (await readBack(kuntolo.bytes)).sheets[0].rows[7] || [];
  check('Kuntolo: the reason is on the sheet itself',
    note[0] === 'Discharge note' && /^Not measured \(step 1: No bucket/.test(note[1] || ''),
    JSON.stringify(note));
  check('workbook: the same, cell for cell, as fixtures/copilot_kuntolo.xlsx',
    await fixture('copilot_kuntolo.xlsx', kuntolo.bytes));

  /* ---------------------------------- a discharge that drifts; a stable T */
  await page.evaluate(() => { window.GWT.pumpCopilot.discard(); window.GWT.app.render(); });
  const D0 = START + 48 * 60 * MIN;
  await at(D0);
  /* a borehole in a 50 m2/day aquifer: Cooper-Jacob drawdown at 5 m3/h,
   * S = 0.001, r = 0.1 m */
  await setUp({ testType: 'constant', casingIn: 5, riserIn: 1.25, depthM: 60, pumpSettingM: 40,
    staticM: 5, plannedRate: 5, plannedMin: 600, boreholeRef: 'SYN-1' });
  await page.evaluate(() => window.GWT.pumpCopilot.start());
  await page.evaluate(() => window.GWT.pumpCopilot.addDischarge(5.0, 'flow meter'));
  const synthetic = (m) => 5 + (5 * 24) / (4 * Math.PI * 50) *
    Math.log(2.25 * 50 * (m / 1440) / (0.1 * 0.1 * 0.001));
  let m = 0;
  while (m < 600) {
    m = await page.evaluate((x) => window.GWT.pumpCopilot.nextSlot(x), m);
    await at(D0 + m * MIN);
    await page.evaluate((l) => window.GWT.pumpCopilot.record(l), Math.round(synthetic(m) * 100) / 100);
    if (m === 20) {
      await page.evaluate(() => window.GWT.pumpCopilot.addDischarge(5.4, 'flow meter'));
      await redraw();
      const dw = await warnings();
      const drift = dw.find((w) => w[0] === 'discharge_drift');
      check('drift: 5.0 to 5.4 m3/h, 8 percent, is warned of', !!drift && /drifted 8\.0 percent/.test(drift[1]),
        JSON.stringify(dw));
      await page.evaluate(() => window.GWT.pumpCopilot.addDischarge(5.0, 'flow meter'));
    }
  }
  await redraw();
  await page.waitForFunction(() => document.querySelector('[data-cp="estimate"]')
    ?.getAttribute('data-state'));
  const stable = await page.evaluate(() => ({
    state: document.querySelector('[data-cp="estimate"]').getAttribute('data-state'),
    text: document.querySelector('[data-cp="estimate"]').textContent,
    modes: window.GWT.engine.history().filter((h) => h.type === 'cooperJacob').map((h) => h.mode),
  }));
  check('estimate: after storage, a steady T says the test can stop at the planned time',
    stable.state === 'fit:stable' && stable.text.includes('T has changed less than 10 percent over ' +
      'the last log cycle. The test can stop at the planned time.'), JSON.stringify(stable));
  check('estimate: the Cooper-Jacob line is the engine\'s, worked out in the worker',
    stable.modes.length > 0 && stable.modes.every((x) => x === 'worker'), JSON.stringify(stable.modes));
  /* the line is fitted at the mean of the step's three rates, 5.0, 5.4 and
   * 5.0 m3/h, so the 50 m2/day comes back scaled by 5.133 / 5 */
  const T = Number((stable.text.match(/T = ([\d.]+)/) || [])[1]);
  const expected = 50 * (15.4 / 3) / 5;
  check('estimate: the synthetic aquifer\'s transmissivity comes back within 2 percent',
    Math.abs(T - expected) / expected < 0.02, `${T} against ${expected}`);

  /* -------------------------------------------------------- offline */
  const sw = await readFile(new URL('../../docs/sw.js', import.meta.url), 'utf-8');
  check('offline: the co-pilot is precached with the app shell', sw.includes("'js/gwt-pump-copilot.js'"));

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n     '));
} catch (e) {
  check('the playback ran to the end', false, e && e.stack);
} finally {
  await browser.close();
  server.close();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} co-pilot checks passed`);
if (failed.length) process.exit(1);

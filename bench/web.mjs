/* Time the browser app the way a field laptop on a phone signal meets it.
 *
 * Each run is a cold load - a fresh browser, an empty cache, no service
 * worker yet - on a throttled profile, followed by what a user does to get a
 * VES interpretation: load the Rokel sample from the Overview, open the
 * Geophysics page, and press "Re-run inversion". Nothing here reaches into
 * the app's internals to start or watch the work: completion is read off the
 * page, so the same script times the inversion on the main thread and in a
 * worker, and will keep timing it whatever moves underneath.
 *
 * The profile:
 *   - CPU: Emulation.setCPUThrottlingRate, rate 4 (a 4x slowdown).
 *   - Network: Network.emulateNetworkConditions with DevTools' "Slow 4G"
 *     preset - 562.5 ms latency, 180,000 bytes/s down (1.6 Mbit/s x 0.9),
 *     84,375 bytes/s up (750 kbit/s x 0.9).
 *   - A 1440 x 900 viewport, the harness's own.
 *
 * What is recorded, per run:
 *   - first paint and first contentful paint, from the Paint Timing entries;
 *   - time to interactive, following Lighthouse: find the first window of
 *     5 s after first contentful paint with no long task (over 50 ms on the
 *     main thread) running in it and never more than two requests in
 *     flight; TTI is the end of the last long task before that window, or
 *     first contentful paint if there was none, and never earlier than the
 *     end of DOMContentLoaded, which Lighthouse also takes as a floor.
 *     Without that floor a page whose scripts are deferred reads as
 *     interactive the moment it paints: two big scripts still downloading
 *     are "at most two requests in flight", and nothing runs until they
 *     have both arrived, more than five seconds later. Requests are the page's
 *     own, as the DevTools protocol's Network events see them, so one still
 *     downloading counts from the moment it is sent. Resource Timing will
 *     not do for this: it lists a request only once it has finished, and a
 *     megabyte script half-way down a slow link would look like a quiet
 *     network. The service worker's precache runs in another target and is
 *     not counted;
 *   - bytes transferred before first paint: the transfer size (headers and
 *     body, as sent) of the document and of every resource whose response
 *     had finished by first paint;
 *   - for the Rokel re-inversion: the wall time from the click to the last
 *     change the page makes to show the result, the longest main-thread task
 *     in that interval, and the blocking time (each long task's excess over
 *     50 ms, summed, as Lighthouse's Total Blocking Time counts it). A long
 *     task is only reported over 50 ms, so a longest task of 0 means none.
 *     The wall time is taken a second time with the CPU slowdown switched
 *     off, because Chromium throttles the page's main thread and nothing
 *     else: asked to throttle the engine worker it answers "Operation is
 *     only supported for pages, not workers". An inversion moved into a
 *     worker therefore runs at the machine's full speed while one on the
 *     main thread runs at a quarter of it, and the throttled wall times of
 *     the two are not like for like. The unthrottled one is.
 *   - for reopening the saved survey: the project saved with the page's Save
 *     project button and opened again with Open project, CPU slowed again,
 *     timed from the file being chosen to the last change the page makes to
 *     show the models, with the longest main-thread task in that interval.
 *   - for autosave (PLAN.md step 1.3): a project of 50 photos and 10
 *     workbooks (tests/webapp/heavy.mjs, about 20.6 MB as JSON) built in a
 *     fresh browser, then the main-thread time of its autosaves, from a
 *     Chromium trace: every main-thread task from the write being asked for
 *     to it being on disk (or refused), clipped to that interval and summed.
 *     The first writes the whole session; each of the next five follows one
 *     typed field, and the median of those is the number. Taken at the 4x
 *     CPU slowdown and again at 1x; the network plays no part.
 *   - for the terrain analysis (PLAN.md step 4.1): the synthetic elevation
 *     tile bench/run.py's terrain group reads, written by the same Python
 *     (bench/terrain_memory.py --write-tile), picked on the Topography and
 *     terrain card of Site & maps as an operator picks a tile, and "Analyse
 *     the terrain" pressed: the wall time from the click to the last change
 *     the page makes to show the four figures, and the longest main-thread
 *     task in that interval. Each press is in a browser of its own, with no
 *     site entered, so the window is centred on the middle of the tile as
 *     run.py's is: the default window, and one near the cap on cells, at
 *     the radius the card offers when asked for 50 km. Taken
 *     with the analysis in the engine worker at full speed, Chromium
 *     slowing no worker (above), and on the page with the CPU slowed 4x,
 *     as a copy opened as a file runs it (GWT.engine.forcePage, the
 *     engine's switch for tests). With the worker, on Linux, also the
 *     memory the press adds to the renderer process, which holds the page
 *     and its worker: the process's high-water mark once the figures are
 *     shown (VmHWM in /proc/PID/status, reset to the resident set through
 *     /proc/PID/clear_refs just before the click) less its resident set
 *     just before the click. The network plays no part.
 *
 * Each measure is the median of the runs (3, or 1 with --quick), written in
 * the same shape as bench/run.py so the two merge into one baseline:
 *
 *   node bench/web.mjs --out web.json
 *   python bench/run.py --from py.json --from web.json --out bench/baseline.json
 *   python bench/run.py --from web.json --compare bench/baseline.json
 *
 * --only PART (repeatable) takes one part of it: load (the cold load, the
 * Rokel re-inversion and the reopening), autosave or terrain.
 */
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { withPage } from '../tests/webapp/harness.mjs';
import { timeAutosaves } from '../tests/webapp/heavy.mjs';

const REPO = fileURLToPath(new URL('..', import.meta.url));
const TOOL = 'bench/web.mjs';

const SLOW_4G = {
  offline: false,
  latency: 562.5,
  downloadThroughput: (1.6 * 1000 * 1000 / 8) * 0.9,
  uploadThroughput: (750 * 1000 / 8) * 0.9,
};
const CPU_SLOWDOWN = 4;
const QUIET_MS = 5000;        // Lighthouse's quiet window
const SETTLED_MS = 2000;      // no change on the page for this long = finished
const PARTS = ['load', 'autosave', 'terrain'];

function parseArgs(argv) {
  const args = { runs: 3, out: null, notes: '', only: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--quick') args.runs = 1;
    else if (a === '--runs') args.runs = Number(argv[++i]);
    else if (a === '--out') args.out = argv[++i];
    else if (a === '--notes') args.notes = argv[++i];
    else if (a === '--only' && PARTS.includes(argv[i + 1])) args.only.push(argv[++i]);
    else throw new Error(`unknown option ${a}; see the header of bench/web.mjs`);
  }
  if (!args.only.length) args.only = PARTS;
  return args;
}

/* Installed before any of the app's own script runs, so the parse and the
 * boot are in the long-task record. */
function instrument() {
  const b = window.__bench = { long: [] };
  const keep = (entries) => entries.forEach((e) =>
    b.long.push({ start: e.startTime, duration: e.duration }));
  try {
    b.observer = new PerformanceObserver((list) => keep(list.getEntries()));
    b.observer.observe({ type: 'longtask', buffered: true });
    // An observer's callback is itself a queued task and may not have run
    // yet when the long tasks are read; this takes what is waiting for it.
    b.flush = () => keep(b.observer.takeRecords());
  } catch (e) { b.unsupported = String(e); b.flush = () => {}; }
}

/* What the TTI needs from the page, read in one task. Because this runs on
 * the main thread, every long task that started before it has finished. */
function timeline() {
  window.__bench.flush();
  const paint = performance.getEntriesByName('first-contentful-paint')[0];
  const nav = performance.getEntriesByType('navigation')[0];
  return { fcp: paint ? paint.startTime : null, now: performance.now(),
    fetchStart: nav ? nav.fetchStart : 0,
    dcl: nav && nav.domContentLoadedEventEnd ? nav.domContentLoadedEventEnd : null,
    long: window.__bench.long };
}

/* Every request the page sends, from the DevTools protocol, in its own
 * monotonic clock (ms); one not yet finished ends at Infinity. data: URLs
 * are not requests on the network and are left out. */
function trackRequests(cdp) {
  const requests = new Map();
  cdp.on('Network.requestWillBeSent', (e) => {
    if (requests.has(e.requestId) || e.request.url.startsWith('data:')) return;
    requests.set(e.requestId, { type: e.type, start: e.timestamp * 1000, end: Infinity });
  });
  const finished = (e) => {
    const r = requests.get(e.requestId);
    if (r) r.end = e.timestamp * 1000;
  };
  cdp.on('Network.loadingFinished', finished);
  cdp.on('Network.loadingFailed', finished);
  return requests;
}

/* Lighthouse's TTI in the page's clock, or null while the quiet window it
 * needs has not yet been seen in full, or DOMContentLoaded has not yet
 * finished. The protocol's clock is put on the page's by the document
 * request, which it sends at the navigation's fetchStart. */
function interactive(page, requests, quietMs) {
  const { fcp, dcl, now, fetchStart, long } = page;
  if (fcp === null || dcl === null) return null;
  const all = [...requests.values()];
  const doc = all.find((r) => r.type === 'Document');
  if (!doc) return null;
  const shift = doc.start - fetchStart;
  const flights = all.map((r) => ({ start: r.start - shift, end: r.end - shift }));
  const inFlight = (t) => flights.filter((r) => r.start <= t && t < r.end).length;
  const ends = long.map((t) => t.start + t.duration);
  // a quiet window can open at first contentful paint, when a long task
  // ends, or when a request finishes
  const opens = [fcp, ...ends, ...flights.map((r) => r.end)]
    .filter((t) => t >= fcp && Number.isFinite(t)).sort((a, b) => a - b);
  for (const start of opens) {
    const end = start + quietMs;
    // judged a second after it closes, so a request sent near its end has
    // reached us from the protocol before it counts as quiet
    if (end > now - 1000) return null;
    if (long.some((t) => t.start < end && t.start + t.duration > start)) continue;
    const points = [start, ...flights.map((r) => r.start).filter((t) => t > start && t < end)];
    if (points.some((t) => inFlight(t) > 2)) continue;
    return Math.max(fcp, dcl, ...ends.filter((e) => e <= start));
  }
  return null;
}

async function timeToInteractive(page, requests) {
  const deadline = Date.now() + 300000;
  for (;;) {
    const tti = interactive(await page.evaluate(timeline), requests, QUIET_MS);
    if (tti !== null) return tti;
    if (Date.now() > deadline) throw new Error('no quiet window within 300 s of loading');
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

function paints() {
  const at = (name) => {
    const e = performance.getEntriesByName(name)[0];
    return e ? e.startTime : null;
  };
  const fp = at('first-paint');
  const nav = performance.getEntriesByType('navigation')[0];
  let bytes = nav ? nav.transferSize : 0;
  for (const r of performance.getEntriesByType('resource')) {
    if (fp !== null && r.responseEnd <= fp) bytes += r.transferSize;
  }
  return { fp, fcp: at('first-contentful-paint'), bytes };
}

/* The page's own signs of work in progress: the busy overlay the app drew
 * over a page while it inverted on the main thread, the work bar it draws
 * while a worker computes, and the Geophysics page's "Inverting" message. */
function busyNow() {
  const host = document.querySelector('#page-host');
  return !!document.querySelector('#work-status .work-bar, #page-host .busy') ||
    (!!host && host.textContent.includes('Inverting the soundings'));
}

/* The Geophysics page showing fitted models: its curves drawn and the
 * button to run it again on offer. */
function modelsShown() {
  const host = document.querySelector('#page-host');
  return !!host && host.querySelectorAll('svg').length >= 2 &&
    Array.from(host.querySelectorAll('button')).some((b) => b.textContent.includes('Re-run inversion'));
}

/* Press "Re-run inversion" on the Geophysics page and time it to the last
 * change the page makes to show the models. The page must be showing them,
 * and idle, when this is called. */
async function reinvert(page) {
  await page.evaluate(`(() => {
    const b = window.__bench, busy = ${busyNow};
    b.changes = []; b.busySeen = false; b.click = null;
    if (b.watch) b.watch.disconnect();
    const watch = b.watch = new MutationObserver(() => {
      b.changes.push(performance.now());
      if (busy()) b.busySeen = true;
    });
    for (const sel of ['#page-host', '#work-status']) {
      const node = document.querySelector(sel);
      if (node) watch.observe(node, { childList: true, subtree: true,
        attributes: true, characterData: true });
    }
    document.addEventListener('click', (e) => { b.click = e.timeStamp; },
      { capture: true, once: true });
  })()`);
  await page.locator('#page-host').getByRole('button', { name: 'Re-run inversion' }).click();
  // finished: the page showed it was working, has stopped showing it, shows
  // the models, and has not changed for SETTLED_MS
  await page.waitForFunction(`(() => {
    const b = window.__bench;
    if (b.click === null || !b.busySeen || (${busyNow})() || !(${modelsShown})()) return false;
    return performance.now() - b.changes[b.changes.length - 1] > ${SETTLED_MS};
  })()`, null, { polling: 250, timeout: 600000 });
  return page.evaluate(() => {
    const b = window.__bench;
    b.flush();
    const end = b.changes[b.changes.length - 1];
    const during = b.long.filter((t) => t.start < end && t.start + t.duration > b.click);
    return {
      wall: end - b.click,
      longest: Math.max(0, ...during.map((t) => t.duration)),
      blocking: during.reduce((sum, t) => sum + Math.max(0, t.duration - 50), 0),
    };
  });
}

/* Save the project with the page's own Save button, then open that file with
 * Open project, and time from the file being chosen to the last change the
 * page makes to show the models. This is reopening a saved survey: with the
 * inversions stored in the project file it runs none, and without them it
 * inverts every sounding again. The page must be showing the models, and
 * idle, when this is called. */
async function reopen(page) {
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('#top-actions').getByRole('button', { name: 'Save project' }).click(),
  ]);
  const saved = await download.path();
  await page.evaluate(`(() => {
    const b = window.__bench;
    b.changes = []; b.chosen = null;
    if (b.watch) b.watch.disconnect();
    const watch = b.watch = new MutationObserver(() => b.changes.push(performance.now()));
    for (const sel of ['#page-host', '#work-status']) {
      const node = document.querySelector(sel);
      if (node) watch.observe(node, { childList: true, subtree: true,
        attributes: true, characterData: true });
    }
    document.addEventListener('change', (e) => { b.chosen = e.timeStamp; },
      { capture: true, once: true });
  })()`);
  const [chooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.locator('#top-actions').getByRole('button', { name: 'Open project' }).click(),
  ]);
  await chooser.setFiles(saved);
  // finished: the file was read, the page shows the models and nothing
  // working, and it has not changed for SETTLED_MS
  await page.waitForFunction(`(() => {
    const b = window.__bench;
    if (b.chosen === null || !b.changes.some((t) => t > b.chosen)) return false;
    if ((${busyNow})() || !(${modelsShown})()) return false;
    return performance.now() - b.changes[b.changes.length - 1] > ${SETTLED_MS};
  })()`, null, { polling: 250, timeout: 600000 });
  return page.evaluate(() => {
    const b = window.__bench;
    b.flush();
    const end = b.changes[b.changes.length - 1];
    const during = b.long.filter((t) => t.start < end && t.start + t.duration > b.chosen);
    return {
      wall: end - b.chosen,
      longest: Math.max(0, ...during.map((t) => t.duration)),
    };
  });
}

async function oneRun(runIndex) {
  return withPage(async (page, base, consoleErrors) => {
    const cdp = await page.context().newCDPSession(page);
    const requests = trackRequests(cdp);
    await cdp.send('Network.enable');
    await cdp.send('Network.emulateNetworkConditions', SLOW_4G);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU_SLOWDOWN });
    await page.addInitScript(instrument);

    // ---- cold load --------------------------------------------------------
    await page.goto(base + '/index.html', { waitUntil: 'load', timeout: 300000 });
    const loadButton = page.getByRole('button', { name: /^Load Rokel/ });
    await loadButton.waitFor({ state: 'visible', timeout: 300000 });
    const tti = await timeToInteractive(page, requests);
    const painted = await page.evaluate(paints);

    // ---- the Rokel sample, on the Geophysics page -------------------------
    await loadButton.click();
    await page.locator('#app-nav').getByRole('button', { name: 'Geophysics (VES)' })
      .click({ timeout: 300000 });
    await page.waitForFunction(
      `(${modelsShown})() && !(${busyNow})()`, null, { polling: 250, timeout: 300000 });
    await page.waitForTimeout(SETTLED_MS);

    // ---- the re-inversion, throttled and then not --------------------------
    const inversion = await reinvert(page);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
    await page.waitForTimeout(SETTLED_MS);
    const unthrottled = await reinvert(page);

    // ---- reopening the saved survey, throttled again -----------------------
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU_SLOWDOWN });
    await page.waitForTimeout(SETTLED_MS);
    const reopened = await reopen(page);
    const errors = consoleErrors.filter((m) => !/favicon/i.test(m));
    console.error(`  run ${runIndex + 1}: first paint ${Math.round(painted.fp)} ms, ` +
      `TTI ${Math.round(tti)} ms, inversion ${Math.round(inversion.wall)} ms, ` +
      `longest task ${Math.round(inversion.longest)} ms, ` +
      `reopened in ${Math.round(reopened.wall)} ms` +
      (errors.length ? `; console errors: ${errors.join(' | ')}` : ''));
    return { ...painted, tti, inversion, unthrottled, reopened, errors };
  });
}

/* The heavy project's autosaves, in a browser of their own, at the 4x CPU
 * slowdown and then at 1x. */
async function autosaveRun() {
  return withPage(async (page, base) => {
    await page.goto(base + '/index.html', { waitUntil: 'load' });
    await page.waitForFunction(() => window.GWT && window.GWT.app &&
      document.querySelector('#page-host .page-head'), null, { timeout: 120000 });
    const middle = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];
    const out = {};
    for (const [name, cpu] of [['slowed', CPU_SLOWDOWN], ['full', 1]]) {
      const t = await timeAutosaves(page, { samples: 5, cpu });
      out[name] = { first: t.first.main, edit: middle(t.edits.map((e) => e.main)),
        stored: t.first.value.ok && t.edits.every((e) => e.value.ok) };
    }
    console.error(`  autosave: ${Math.round(out.slowed.edit)} ms at ${CPU_SLOWDOWN}x, ` +
      `${out.full.edit.toFixed(1)} ms at 1x, first write ${Math.round(out.slowed.first)} ms ` +
      `at ${CPU_SLOWDOWN}x${out.full.stored && out.slowed.stored ? '' : '; REFUSED by storage'}`);
    return out;
  });
}

/* bench/run.py's TERRAIN_TILE: the published name of the tile the synthetic
 * one is laid out as, so that the card takes it for Copernicus GLO-30 as it
 * would the real one, its credit and liability sentence included. */
const TERRAIN_TILE = 'Copernicus_DSM_COG_10_N08_00_W012_00_DEM.tif';
const TERRAIN_CARD = '[data-item="terrain"]';

/* The tile bench/run.py's terrain group reads, written once into a folder
 * of its own by run.py's own writer (through bench/terrain_memory.py), so
 * that the browser is timed on the ground the Python package is. */
function writeTerrainTile() {
  const dir = mkdtempSync(join(os.tmpdir(), 'gwt-bench-'));
  const path = join(dir, TERRAIN_TILE);
  execFileSync(process.env.PYTHON || 'python', ['bench/terrain_memory.py', '--write-tile', path],
    { cwd: REPO, stdio: ['ignore', 'ignore', 'inherit'] });
  return { dir, path };
}

/* The renderer processes of the browser the page is in. Chromium runs a
 * page and its dedicated workers in one. */
async function rendererPids(page) {
  const cdp = await page.context().browser().newBrowserCDPSession();
  try {
    const { processInfo } = await cdp.send('SystemInfo.getProcessInfo');
    return processInfo.filter((p) => p.type === 'renderer').map((p) => p.id);
  } finally {
    await cdp.detach();
  }
}

function statusKb(pid, field) {
  const found = new RegExp(`^${field}:\\s+(\\d+) kB`, 'm')
    .exec(readFileSync(`/proc/${pid}/status`, 'utf8'));
  return found ? Number(found[1]) : NaN;
}

/* Each process's high-water mark reset to its resident set ("5" written to
 * clear_refs), and the resident sets, by process; null where /proc cannot
 * do that (not Linux, or not allowed), and the memory is then not taken. */
function memoryMark(pids) {
  try {
    const marks = new Map();
    for (const pid of pids) {
      writeFileSync(`/proc/${pid}/clear_refs`, '5');
      marks.set(pid, statusKb(pid, 'VmRSS'));
    }
    return marks;
  } catch {
    return null;
  }
}

/* The most any of those processes rose above its resident set at the mark,
 * in bytes, or null. */
function memoryRise(marks) {
  if (!marks) return null;
  try {
    let rise = 0;
    for (const [pid, rss] of marks) rise = Math.max(rise, statusKb(pid, 'VmHWM') - rss);
    return Number.isFinite(rise) ? rise * 1024 : null;
  } catch {
    return null;
  }
}

/* The card's radius, typed as an operator types it; the card takes it when
 * the field is left. */
async function setTerrainRadius(page, km) {
  const input = page.locator(TERRAIN_CARD).getByLabel('Radius of the square shown (km)');
  await input.fill(String(km));
  await input.blur();
}

/* Press "Analyse the terrain" and time it to the last change the page makes
 * to show the four figures. A device that reports 2 GB of memory or less is
 * asked first before a large window, and then the run starts at the answer. */
async function analyseTerrain(page) {
  await page.evaluate(`(() => {
    const b = window.__bench;
    b.changes = []; b.click = null;
    if (b.watch) b.watch.disconnect();
    const watch = b.watch = new MutationObserver(() => b.changes.push(performance.now()));
    for (const sel of ['#page-host', '#work-status']) {
      const node = document.querySelector(sel);
      if (node) watch.observe(node, { childList: true, subtree: true,
        attributes: true, characterData: true });
    }
    document.addEventListener('click', (e) => { b.click = e.timeStamp; }, { capture: true });
  })()`);
  const card = page.locator(TERRAIN_CARD);
  await card.getByRole('button', { name: 'Analyse the terrain' }).click();
  const ask = page.getByRole('button', { name: 'Run it anyway' });
  if (await ask.count()) await ask.click();
  // finished: the page has changed since the click, shows no work under
  // way, shows the four figures (or a refusal, reported below), and has not
  // changed for SETTLED_MS
  await page.waitForFunction(`(() => {
    const b = window.__bench, card = document.querySelector('${TERRAIN_CARD}');
    if (b.click === null || !b.changes.some((t) => t > b.click)) return false;
    if (document.querySelector('#work-status .work-bar')) return false;
    if (Array.from(card.querySelectorAll('p.muted'))
      .some((p) => p.textContent.startsWith('Analysing the terrain.'))) return false;
    if (card.querySelectorAll('figure').length < 4 &&
      !card.querySelector('.btn-row ~ .callout-bad')) return false;
    return performance.now() - b.changes[b.changes.length - 1] > ${SETTLED_MS};
  })()`, null, { polling: 250, timeout: 600000 });
  const timed = await page.evaluate((sel) => {
    const b = window.__bench, host = document.querySelector(sel);
    b.flush();
    const refusal = host.querySelector('.btn-row ~ .callout-bad');
    const end = b.changes[b.changes.length - 1];
    const during = b.long.filter((t) => t.start < end && t.start + t.duration > b.click);
    return {
      refusal: refusal ? refusal.textContent : null,
      wall: end - b.click,
      longest: Math.max(0, ...during.map((t) => t.duration)),
    };
  }, TERRAIN_CARD);
  if (timed.refusal) throw new Error(`the terrain analysis was refused: ${timed.refusal}`);
  return timed;
}

/* One press of "Analyse the terrain" on the tile, in a fresh browser: in the
 * engine worker at full speed, or on the page with the CPU slowed 4x when
 * `onPage`; at the default window, or at the radius the card offers when
 * asked for 50 km, near the cap on cells, when `atCap`. */
async function terrainRun(tile, { onPage = false, atCap = false } = {}) {
  return withPage(async (page, base, consoleErrors) => {
    const cdp = await page.context().newCDPSession(page);
    await page.addInitScript(instrument);
    await page.goto(base + '/index.html#/site/terrain', { waitUntil: 'load', timeout: 120000 });
    const card = page.locator(TERRAIN_CARD);
    await card.locator('.upload-zone').waitFor({ timeout: 120000 });
    if (onPage) await page.evaluate(() => window.GWT.engine.forcePage(true));
    const [chooser] = await Promise.all([page.waitForEvent('filechooser'),
      card.locator('.upload-zone').click()]);
    await chooser.setFiles(tile.path);
    // opened: the button can be pressed, or the file was refused
    await page.waitForFunction((sel) => {
      const host = document.querySelector(sel);
      const go = Array.from(host.querySelectorAll('button'))
        .find((b) => b.textContent === 'Analyse the terrain');
      return host.querySelector('.terrain-file .callout-bad') || (go && !go.disabled);
    }, TERRAIN_CARD, { polling: 100, timeout: 120000 });
    const refused = card.locator('.terrain-file .callout-bad');
    if (await refused.count()) {
      throw new Error(`the tile was refused: ${await refused.textContent()}`);
    }
    let radius = Number(await card.getByLabel('Radius of the square shown (km)').inputValue());
    if (atCap) {
      // the radius the card offers when asked for more than fits, as
      // bench/run.py takes it from the planner
      await setTerrainRadius(page, 50);
      await card.getByRole('button', { name: 'Analyse the terrain' }).click();
      const refusal = card.locator('.btn-row ~ .callout-bad');
      await refusal.waitFor({ timeout: 60000 });
      const fit = /a radius of ([\d.]+) km fits/.exec(await refusal.textContent());
      if (!fit) throw new Error(`no radius offered at 50 km: ${await refusal.textContent()}`);
      radius = Number(fit[1]);
      await setTerrainRadius(page, radius);
    }
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: onPage ? CPU_SLOWDOWN : 1 });
    const marks = onPage ? null : memoryMark(await rendererPids(page));
    const timed = await analyseTerrain(page);
    const memory = memoryRise(marks);
    const errors = consoleErrors.filter((m) => !/favicon/i.test(m));
    return { ...timed, radius, memory, errors };
  });
}

/* The four presses of a run, each in a browser of its own. */
async function terrainRuns(tile) {
  const out = {
    worker: await terrainRun(tile),
    workerCap: await terrainRun(tile, { atCap: true }),
    page: await terrainRun(tile, { onPage: true }),
    pageCap: await terrainRun(tile, { onPage: true, atCap: true }),
  };
  const s = (ms) => `${(ms / 1000).toFixed(2)} s`;
  const mb = (bytes) => (bytes === null ? '' : `, +${Math.round(bytes / 1e6)} MB`);
  const errors = Object.values(out).flatMap((r) => r.errors);
  console.error(`  terrain: in the worker ${s(out.worker.wall)} at ${out.worker.radius} km ` +
    `(longest task ${s(out.worker.longest)}${mb(out.worker.memory)}), ` +
    `${s(out.workerCap.wall)} at the cap, ${out.workerCap.radius} km ` +
    `(longest task ${s(out.workerCap.longest)}${mb(out.workerCap.memory)}); ` +
    `on the page at ${CPU_SLOWDOWN}x ${s(out.page.wall)} and ${s(out.pageCap.wall)}` +
    (errors.length ? `; console errors: ${errors.join(' | ')}` : ''));
  return out;
}

/* Median, interquartile range (quartiles by linear interpolation, as
 * Python's statistics.quantiles(method="inclusive")), min, max. */
function summarise(samples) {
  const s = [...samples].sort((a, b) => a - b);
  const q = (p) => {
    const x = (s.length - 1) * p;
    const lo = Math.floor(x);
    return s[lo] + (s[Math.min(lo + 1, s.length - 1)] - s[lo]) * (x - lo);
  };
  return { median: q(0.5), iqr: q(0.75) - q(0.25), min: s[0], max: s[s.length - 1],
    n: s.length, samples };
}

function git(...args) {
  try {
    return execFileSync('git', args, { cwd: REPO, encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch { return ''; }
}

const args = parseArgs(process.argv.slice(2));
const { chromium } = await import('playwright');
const browser = await chromium.launch({ args: ['--no-sandbox'] });
const chromiumVersion = browser.version();
await browser.close();

console.error(`timing the web app, ${args.runs} cold ${args.runs === 1 ? 'run' : 'runs'}` +
  (args.only.length < PARTS.length ? ` (${args.only.join(', ')} only)` : ''));
const tile = args.only.includes('terrain') ? writeTerrainTile() : null;
const runs = [];
try {
  for (let i = 0; i < args.runs; i += 1) {
    const run = { errors: [] };
    if (args.only.includes('load')) Object.assign(run, await oneRun(i));
    if (args.only.includes('autosave')) run.autosave = await autosaveRun();
    if (tile) {
      run.terrain = await terrainRuns(tile);
      run.errors = run.errors.concat(...Object.values(run.terrain).map((t) => t.errors));
    }
    runs.push(run);
  }
} finally {
  if (tile) rmSync(tile.dir, { recursive: true, force: true });
}

const profile = 'CPU 4x slower, DevTools "Slow 4G" (562.5 ms, 180,000 B/s down, ' +
  '84,375 B/s up), cold: fresh browser and empty cache each run';
const terrainProfile = (onPage) => (onPage ? `CPU ${CPU_SLOWDOWN}x slower, analysed on the page ` +
  '(GWT.engine.forcePage)' : 'CPU at full speed, analysed in the engine worker') +
  '; the synthetic tile of bench/run.py\'s terrain group, no site entered; a fresh browser ' +
  'each press, no network in play';
const pressed = 'click on "Analyse the terrain" to the last change the page makes showing the ' +
  'four figures';
const atCap = 'at the radius the card offers when asked for 50 km, near the cap on cells';
const MEASURES = {
  load: [
    ['first paint', 'ms', (r) => r.fp, 'Paint Timing first-paint'],
    ['first contentful paint', 'ms', (r) => r.fcp, 'Paint Timing first-contentful-paint'],
    ['time to interactive', 'ms', (r) => r.tti,
      'Lighthouse TTI: end of the last long task before the first 5 s window after FCP ' +
      'with no long task in it and at most 2 page requests in flight (DevTools protocol), ' +
      'and no earlier than FCP or the end of DOMContentLoaded'],
    ['bytes before first paint', 'bytes', (r) => r.bytes,
      'Resource Timing transferSize of the document and every response finished by first paint'],
    ['rokel inversion wall time', 'ms', (r) => r.inversion.wall,
      'click on "Re-run inversion" to the last change the page makes showing the models'],
    ['rokel inversion wall time, CPU unthrottled', 'ms', (r) => r.unthrottled.wall,
      'as the wall time above, run again at once with the CPU slowdown off'],
    ['rokel inversion longest main-thread task', 'ms', (r) => r.inversion.longest,
      'longest Long Task overlapping the inversion; 0 = none over 50 ms'],
    ['rokel inversion main-thread blocking time', 'ms', (r) => r.inversion.blocking,
      'sum over Long Tasks overlapping the inversion of (duration - 50 ms)'],
    ['rokel saved project reopen wall time', 'ms', (r) => r.reopened.wall,
      'the Rokel project saved with "Save project" and opened again with "Open project": ' +
      'the file chosen to the last change the page makes showing the models'],
    ['rokel saved project reopen longest main-thread task', 'ms', (r) => r.reopened.longest,
      'longest Long Task overlapping the reopen; 0 = none over 50 ms'],
  ],
  autosave: [
    ['autosave of 50 photos and 10 workbooks, main-thread time', 'ms',
      (r) => r.autosave.slowed.edit,
      'median of 5 autosaves each after one typed field, project from tests/webapp/heavy.mjs ' +
      '(20.6 MB as JSON): main-thread tasks from the write asked for to it stored or refused, ' +
      'from a Chromium trace; CPU 4x slower, no network in play'],
    ['autosave of 50 photos and 10 workbooks, main-thread time, CPU unthrottled', 'ms',
      (r) => r.autosave.full.edit, 'as above at 1x'],
    ['autosave of 50 photos and 10 workbooks, first write, main-thread time', 'ms',
      (r) => r.autosave.slowed.first,
      'as above for the first write, which stores the whole session; CPU 4x slower'],
  ],
  terrain: [
    ['terrain default window wall time, worker', 'ms', (r) => r.terrain.worker.wall,
      `${pressed}; the default window`, terrainProfile(false)],
    ['terrain default window longest main-thread task, worker', 'ms',
      (r) => r.terrain.worker.longest,
      'longest Long Task overlapping the press above; 0 = none over 50 ms', terrainProfile(false)],
    ['terrain default window memory added, worker', 'bytes', (r) => r.terrain.worker.memory,
      'the renderer process\'s high-water mark (VmHWM, reset through clear_refs just before ' +
      'the click) once the figures are shown, less its resident set just before the click; ' +
      'the page and its worker share the process; Linux only', terrainProfile(false)],
    ['terrain window at the cap wall time, worker', 'ms', (r) => r.terrain.workerCap.wall,
      `${pressed}; ${atCap}`, terrainProfile(false)],
    ['terrain window at the cap longest main-thread task, worker', 'ms',
      (r) => r.terrain.workerCap.longest,
      'longest Long Task overlapping the press above; 0 = none over 50 ms', terrainProfile(false)],
    ['terrain window at the cap memory added, worker', 'bytes', (r) => r.terrain.workerCap.memory,
      'as the default window\'s, at the cap', terrainProfile(false)],
    ['terrain default window wall time, on the page', 'ms', (r) => r.terrain.page.wall,
      `${pressed}; the default window`, terrainProfile(true)],
    ['terrain window at the cap wall time, on the page', 'ms', (r) => r.terrain.pageCap.wall,
      `${pressed}; ${atCap}`, terrainProfile(true)],
  ],
};
const measures = PARTS.filter((part) => args.only.includes(part))
  .flatMap((part) => MEASURES[part])
  .filter(([name, , pick]) => {
    // the memory is taken from /proc, on Linux only
    if (runs.every((r) => pick(r) !== null)) return true;
    console.error(`left out, as not measured here: web/${name}`);
    return false;
  })
  .map(([name, unit, pick, what, how = profile]) => ({
    id: `web/${name}`, group: 'web', name, tool: TOOL, unit,
    method: `${what}; ${how}; median of ${runs.length}`,
    ...summarise(runs.map(pick)),
  }));

const doc = {
  schema: 1,
  notes: args.notes,
  runs: [{
    tool: TOOL,
    commit: git('rev-parse', 'HEAD'),
    dirty: git('status', '--porcelain', '--untracked-files=no') !== '',
    timestamp: new Date().toISOString().replace(/\.\d+Z$/, '+00:00'),
    machine: {
      cpu: os.cpus()[0]?.model || '', cpu_count: os.cpus().length,
      os: `${os.type()} ${os.release()} ${os.arch()}`,
      node: process.version, chromium: chromiumVersion,
      load_average: os.loadavg(),
    },
    options: { runs: runs.length, parts: args.only, cpu_slowdown: CPU_SLOWDOWN, network: SLOW_4G,
      viewport: '1440x900', console_errors: runs.flatMap((r) => r.errors),
      autosave_stored: args.only.includes('autosave')
        ? runs.every((r) => r.autosave.slowed.stored && r.autosave.full.stored) : null,
      terrain_radius_km: tile ? { default: runs[0].terrain.worker.radius,
        cap: runs[0].terrain.workerCap.radius } : null },
  }],
  measures,
};

if (args.out) {
  writeFileSync(args.out, JSON.stringify(doc, null, 1) + '\n');
  console.error(`written to ${args.out}`);
}
const fmt = (v, unit) => (unit === 'bytes' ? `${(v / 1e6).toFixed(2)} MB` : `${(v / 1000).toFixed(2)} s`);
for (const m of measures) {
  console.log(`${m.id.padEnd(48)} ${fmt(m.median, m.unit).padStart(9)}  ` +
    `IQR ${fmt(m.iqr, m.unit).padStart(9)}  n=${m.n}`);
}

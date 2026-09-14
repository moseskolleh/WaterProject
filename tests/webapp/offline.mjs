/* The app has to survive losing the network, and has to survive a release.
 *
 * smoke.mjs already proves the worker registers, precaches the shell and
 * lets the app boot with the network switched off. What it does not cover is
 * what happens at the edges, which is where a field device actually gets
 * hurt:
 *
 *   - a file the page loads that nobody added to the precache list
 *   - a deploy that half arrived, leaving an app that looks updated and is
 *     missing a page
 *   - an update swapped in under a tab that is part way through a recompute
 *   - real work - loading a survey, recomputing it - with no network at all,
 *     rather than just a page that renders
 *
 * Each of those is silent. The device works on the bench, in town, on the
 * machine that published it, and fails at a borehole three hours from the
 * nearest road. So each one is a check here.
 *
 * The network is taken away by making the server drop connections rather
 * than by emulating offline mode, which does not reliably reach a service
 * worker's own fetches: a check that quietly still had a network would pass
 * while proving nothing.
 */
import { withPage } from './harness.mjs';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

const WORKER = fileURLToPath(new URL('../../docs/sw.js', import.meta.url));
const source = await readFile(WORKER, 'utf-8');

/* The committed worker, read the way the browser will read it. Parsed rather
 * than recomputed from the shell: the contract here is what is on disk. */
const precache = [...source.match(/var PRECACHE = \[(.*?)\];/s)[1]
  .matchAll(/'([^']+)'/g)].map((m) => m[1]);
const version = source.match(/var VERSION = '([^']+)'/)[1];

/* A worker the browser will treat as a new release: same behaviour, a
 * different identifier. `extra` adds a path to the precache list, to stage a
 * deploy that cannot complete. */
function release(id, extra) {
  let out = source.replace(/var VERSION = '[^']+'/, `var VERSION = '${id}'`);
  if (extra) out = out.replace('var PRECACHE = [', `var PRECACHE = [\n  '${extra}',`);
  return out;
}

/* Both are mutated during the run and read per request, so the page sees
 * whatever is in them at the time it asks. */
const overlay = {};
const network = { down: false };

/* A cross-origin host that resolves nowhere on any machine (RFC 2606), so the
 * pass-through checks below prove what the worker does rather than what the
 * network happens to allow. */
const FOREIGN = 'https://water-point-inventory.invalid/resource.json';

/* Requests this file breaks on purpose. Their console noise is the test
 * working, not the app failing; anything else is a real error. */
const PROVOKED = ['not-in-this-deploy.js', 'never-downloaded.json',
  'water-point-inventory.invalid', 'wasm/index.html', 'ERR_', 'Failed to fetch',
  'Offline support unavailable',
  /* the worker's own answer for a file that was never downloaded; the check
   * above asserts that exact status, so the browser logging it is the point */
  '504 (Offline)'];

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app);

  const installed = await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
    /* ready resolves on an active worker; claiming the page that registered
     * it is a separate step, so wait for the app to actually be controlled */
    for (let i = 0; i < 60 && !navigator.serviceWorker.controller; i += 1) {
      await new Promise((r) => setTimeout(r, 100));
    }
    const reg = await navigator.serviceWorker.getRegistration();
    return {
      scope: reg.scope,
      controlled: !!navigator.serviceWorker.controller,
      caches: await caches.keys(),
    };
  });
  check('install: the committed worker is the one that took control',
    installed.controlled === true &&
    installed.caches.length === 1 && installed.caches[0] === version + '-app',
    JSON.stringify(installed));

  // --- the precache list is the shell, exactly ------------------------------
  // Both directions. A file the page loads and the worker does not know about
  // is a feature that is simply missing on a device installed before it
  // existed - and it works on every machine that already has it in the
  // browser's own cache, which is what makes it so easy to ship.
  const shell = await page.evaluate(async (expected) => {
    const names = await caches.keys();
    const cache = await caches.open(names.find((n) => n.startsWith('gwt-v')));
    const keys = await cache.keys();
    const held = keys.map((r) => new URL(r.url).pathname.replace(/^\//, ''));
    const want = expected.map((p) => (p === './' ? '' : p));
    /* what the page actually pulled off the server to render itself */
    const loaded = performance.getEntriesByType('resource')
      .map((e) => new URL(e.name).pathname.replace(/^\//, ''))
      .filter((p) => !p.startsWith('wasm/') && p !== 'sw.js');
    return {
      uncached: want.filter((p) => !held.includes(p)),
      unlisted: held.filter((p) => !want.includes(p)),
      loadedButNotCached: [...new Set(loaded)].filter((p) => !held.includes(p)),
    };
  }, precache);
  check('shell: every precached path reached the device',
    shell.uncached.length === 0, JSON.stringify(shell.uncached));
  check('shell: nothing is cached that the worker does not list',
    shell.unlisted.length === 0, JSON.stringify(shell.unlisted));
  check('shell: every file the page loaded is precached',
    shell.loadedButNotCached.length === 0,
    JSON.stringify(shell.loadedButNotCached));

  // --- no network at all ----------------------------------------------------
  network.down = true;

  // The launcher opens the scope root, not index.html: a phone that installed
  // the app opens './', so that is the URL that has to work with no signal.
  await page.goto(base + '/', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app, { timeout: 30000 });

  // And not just render: a survey has to load and recompute, because that is
  // what somebody standing at the borehole actually came to do.
  const offlineWork = await page.evaluate(async () => {
    window.GWT.app.loadSample('dr_timbo');
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      const s = window.GWT.app.recomputeState;
      if (s.running === 0 && window.GWT.app.derived.analysis !== null) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    const d = window.GWT.app.derived;
    return {
      analysed: !!d.analysis,
      designed: !!(d.design && d.design.screens.length),
      safe: d.analysis && d.analysis.yield_recommendation.safe_yield_m3_per_h,
    };
  });
  check('no network: a survey still loads, recomputes and designs a borehole',
    offlineWork.analysed && offlineWork.designed && offlineWork.safe > 0,
    JSON.stringify(offlineWork));

  const answers = await page.evaluate(async (FOREIGN) => {
    const out = {};
    /* a file of the app's that genuinely was never downloaded */
    const miss = await fetch('never-downloaded.json');
    out.missStatus = miss.status;
    out.missText = (await miss.text()).slice(0, 40);
    /* the 60 MB Python runtime is passed through, not mirrored, so with no
     * network it fails rather than being quietly served off somebody's phone */
    out.wasm = await fetch('wasm/index.html').then((r) => r.status).catch(() => 'refused');
    /* Somebody else's server is never this worker's to answer. A cross-origin
     * request has to fail the way a cross-origin request fails, rather than
     * come back as the worker's own offline reply served off this device -
     * a stale water point inventory read back from disk is indistinguishable
     * from a live one. The host is a reserved .invalid name (RFC 2606) that
     * resolves nowhere, so what this proves is decided by the worker rather
     * than by whether the machine running the checks has a network: asking
     * the real endpoint would pass here and answer 200 on a runner that can
     * reach it. */
    out.foreign = await fetch(FOREIGN)
      .then(async (r) => 'answered ' + r.status + ': ' + (await r.text()).slice(0, 30))
      .catch(() => 'refused');
    /* and nothing of anybody else's is on the device to serve */
    const names = await caches.keys();
    const cache = await caches.open(names.find((n) => n.startsWith('gwt-v')));
    out.foreignCached = !!(await cache.match(FOREIGN, { ignoreSearch: true }));
    out.wpdxCached = !!(await cache.match(
      'https://data.waterpointdata.org/resource/eqje-vguj.json',
      { ignoreSearch: true }));
    return out;
  }, FOREIGN);
  check('no network: a file never downloaded says so plainly',
    answers.missStatus === 504 && answers.missText.startsWith('Offline, and this file'),
    JSON.stringify(answers));
  check('no network: the WebAssembly runtime is not mirrored onto the device',
    answers.wasm === 'refused', JSON.stringify(answers));
  check('no network: somebody else\'s server is never answered from disk',
    answers.foreign === 'refused' && answers.foreignCached === false &&
    answers.wpdxCached === false, JSON.stringify(answers));

  network.down = false;
  await page.goto(base + '/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.app);

  // --- the running release is read-only -------------------------------------
  // The install handler refuses half a release, but that is worth nothing if
  // an ordinary page load can rewrite the release it is running, one file at
  // a time, from whatever happens to be on the server. That is precisely what
  // a background revalidation that writes back into the versioned cache does:
  // a deploy that is half uploaded becomes the app a file at a time, under the
  // OLD release's identifier, without any install ever succeeding. So: change
  // a file on the server, load the page, and require the release on disk to be
  // exactly what it was.
  const before = await page.evaluate(async (v) => {
    const c = await caches.open(v + '-app');
    const r = await c.match(new URL('js/gwt-core.js', location.href).href);
    return r ? (await r.text()).length : null;
  }, version);

  overlay['/js/gwt-core.js'] = {
    body: '/* a deploy that is still uploading */\n', type: 'application/javascript',
  };
  await page.goto(base + '/index.html', { waitUntil: 'load' });
  await new Promise((r) => setTimeout(r, 800));
  const after = await page.evaluate(async (v) => {
    const c = await caches.open(v + '-app');
    const r = await c.match(new URL('js/gwt-core.js', location.href).href);
    return {
      length: r ? (await r.text()).length : null,
      names: (await caches.keys()).sort(),
    };
  }, version);
  delete overlay['/js/gwt-core.js'];

  check('a page load never rewrites the release it is running',
    before !== null && after.length === before,
    JSON.stringify({ before, after: after.length, names: after.names }));

  // --- a deploy that half arrived ------------------------------------------
  // The release is all of its files or it is none of them. A worker that
  // cannot fetch one of them must fail to install, and the device must keep
  // the release it already had rather than end up with an app that looks
  // updated and is missing a page.
  overlay['/sw.js'] = { body: release('gwt-vbroken0000', 'not-in-this-deploy.js') };
  const broken = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.getRegistration();
    let rejected = false;
    try { await reg.update(); } catch (e) { rejected = true; }
    /* the update may also fail without rejecting; what matters is what is
     * installed afterwards, not how the failure was reported */
    await new Promise((r) => setTimeout(r, 1000));
    const after = await navigator.serviceWorker.getRegistration();
    return {
      rejected,
      waiting: !!(after && after.waiting),
      active: after && after.active ? after.active.scriptURL : null,
      caches: (await caches.keys()).sort(),
    };
  });
  check('half a release: the incomplete deploy never becomes the app',
    broken.waiting === false, JSON.stringify(broken));
  check('half a release: it leaves no trace that it tried',
    broken.caches.every((n) => n.indexOf('gwt-vbroken0000') !== 0) &&
    broken.caches.includes(version + '-app'),
    JSON.stringify(broken.caches));

  const stillWorks = await page.evaluate(async () => {
    const r = await fetch('js/gwt-core.js');
    return { ok: r.ok, size: (await r.text()).length };
  });
  check('half a release: the release it was going to replace still serves',
    stillWorks.ok === true && stillWorks.size > 1000, JSON.stringify(stillWorks));

  // --- a release that did arrive -------------------------------------------
  // It installs, and then it waits. A tab that is open finishes on the
  // release it started with: swapping the engine under a page half way
  // through a recompute is how one app ends up running two releases at once,
  // and the app already tells the user it will be used next time.
  overlay['/sw.js'] = { body: release('gwt-vnextrelease') };
  const update = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.getRegistration();
    await reg.update();
    for (let i = 0; i < 40; i += 1) {
      const r = await navigator.serviceWorker.getRegistration();
      if (r && r.waiting) break;
      await new Promise((res) => setTimeout(res, 100));
    }
    const after = await navigator.serviceWorker.getRegistration();
    return {
      waiting: after && after.waiting ? after.waiting.scriptURL : null,
      controller: navigator.serviceWorker.controller
        ? navigator.serviceWorker.controller.scriptURL : null,
      caches: (await caches.keys()).sort(),
      toast: Array.from(document.querySelectorAll('.toast'))
        .map((n) => n.textContent).join(' | '),
    };
  });
  check('a new release: it installs and waits rather than taking the tab over',
    update.waiting !== null && update.controller !== null, JSON.stringify(update));
  check('a new release: the open tab keeps the release it started with',
    update.caches.includes(version + '-app'), JSON.stringify(update.caches));
  check('a new release: the app says an update is waiting',
    update.toast.includes('next time you open the app'), update.toast);

  // Closing every tab and reopening is what activates it, and that is when
  // the old release is swept. A waiting worker deliberately will not take
  // over while a page it would replace is still open, which is the whole
  // point of not calling skipWaiting.
  const context = page.context();
  await page.close();
  /* the handover happens once the last client controlled by the old worker
   * is gone, so give it that moment before opening the new tab - otherwise
   * the new tab becomes a client of the old worker and holds it open again */
  await new Promise((r) => setTimeout(r, 2000));
  const reopened = await context.newPage();
  await reopened.goto(base + '/index.html', { waitUntil: 'load' });
  await reopened.waitForFunction(() => window.GWT && window.GWT.app);
  const activated = await reopened.evaluate(async () => {
    await navigator.serviceWorker.ready;
    for (let i = 0; i < 60; i += 1) {
      const names = await caches.keys();
      if (names.length === 1 && names[0] === 'gwt-vnextrelease-app') break;
      await new Promise((r) => setTimeout(r, 100));
    }
    return { caches: (await caches.keys()).sort() };
  });
  check('a new release: reopening activates it and drops the one it replaced',
    activated.caches.length === 1 && activated.caches[0] === 'gwt-vnextrelease-app',
    JSON.stringify(activated.caches));

  delete overlay['/sw.js'];
  const unexpected = consoleErrors.filter(
    (line) => !PROVOKED.some((fragment) => line.includes(fragment)));
  check('no console errors beyond the ones these checks provoke',
    unexpected.length === 0, unexpected.slice(0, 10).join('\n     '));
}, { overlay, network });

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

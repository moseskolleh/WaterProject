/* measure.mjs - time the Pyodide engine against the JavaScript one (spike).
 *
 *   python spikes/pyodide-engine/build.py --tarball PATH   # once
 *   node spikes/pyodide-engine/measure.mjs [--reps 3] [--out FILE]
 *
 * Serves docs/ at /app/ and this folder at /spike/ from one local server,
 * with cross-origin isolation on so performance.measureUserAgentSpecificMemory
 * can be read, and drives bench.html in headless Chromium. Every host but
 * 127.0.0.1 is unresolvable for the browser, and once the spike's service
 * worker has precached its files the server drops every connection, so the
 * starts timed after that read their files from Cache Storage only, as an
 * installed app with no signal would.
 *
 * Each repetition, in a fresh browser profile:
 *
 *   precache   register sw.js and let it fetch everything (bytes counted)
 *   cold       server down; start each engine's worker, invert both Rokel
 *              soundings twice - the first Pyodide start this profile has
 *              seen, its files precached and nothing compiled yet
 *   reload     the page reloaded in the same browser: a warm start
 *   restart    the browser closed and opened again on the same profile, still
 *              offline: the start a field device makes each morning; and a
 *              start with numpy alone, to show what scipy costs
 *   page 1x    the same work on the page's own thread, unthrottled
 *   page 4x    the same with DevTools' CPU throttling at 4x, which Chromium
 *              applies to the page's thread and not to a worker (checked
 *              here by timing the JavaScript worker under it as well)
 *
 * plus, each in a fresh profile of its own, a cold start on the page at 4x
 * and the peak memory of each engine alone. The native Python times come
 * from engine.py run under CPython on the same soundings, numpy held to one
 * BLAS thread as bench/run.py holds it.
 */
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile, stat, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { tmpdir, cpus, loadavg } from 'node:os';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { gzipSync, brotliCompressSync, constants as zc } from 'node:zlib';

const HERE = fileURLToPath(new URL('./', import.meta.url));
const REPO = fileURLToPath(new URL('../../', import.meta.url));
const DOCS = join(REPO, 'docs');

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : dflt;
};
const REPS = Number(opt('--reps', 3));
const OUT = opt('--out', join(HERE, 'results.json'));

const TYPES = {
  '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.json': 'application/json', '.wasm': 'application/wasm', '.zip': 'application/zip',
  '.whl': 'application/zip', '.css': 'text/css',
};

/* ------------------------------------------------------------ the server */

const net = { down: false, log: [] };
const server = createServer(async (req, res) => {
  if (net.down) { req.socket.destroy(); return; }
  try {
    const url = new URL(req.url, 'http://localhost');
    const path = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, '');
    let file;
    if (path === '/sw.js') file = join(HERE, 'sw.js');
    else if (path.startsWith('/app/')) file = join(DOCS, path.slice(5));
    else if (path.startsWith('/spike/')) file = join(HERE, path.slice(7));
    else throw new Error('outside');
    if (!(await stat(file)).isFile()) throw new Error('not a file');
    const body = await readFile(file);
    res.writeHead(200, {
      'Content-Type': TYPES[extname(file)] || 'application/octet-stream',
      /* isolation, so the page may measure memory; same-origin throughout */
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
      'Cross-Origin-Resource-Policy': 'same-origin',
      /* nothing warm comes from the HTTP cache: only the service worker's */
      'Cache-Control': 'no-store',
    });
    res.end(body);
    net.log.push({ path, bytes: body.length });
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('not found');
    net.log.push({ path: req.url, bytes: 0, missing: true });
  }
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const BASE = `http://127.0.0.1:${server.address().port}`;

/* ----------------------------------------------------------- the browser */

async function launch(profile) {
  const ctx = await chromium.launchPersistentContext(profile, {
    headless: true,
    viewport: { width: 1280, height: 800 },
    args: ['--no-sandbox', '--disable-dev-shm-usage',
      /* the network is this server and nothing else */
      '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
      /* answer measureUserAgentSpecificMemory at once, not at the next GC */
      '--enable-blink-features=ForceEagerMeasureMemory'],
  });
  const errors = [];
  ctx.on('weberror', (e) => errors.push(String(e.error())));
  return { ctx, errors };
}

async function benchPage(ctx) {
  const page = ctx.pages()[0] || await ctx.newPage();
  page.on('pageerror', (e) => console.error('pageerror:', e.message));
  await page.goto(BASE + '/spike/bench.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.bench && window.GWT && GWT.core);
  return page;
}

/* Register the spike's service worker, wait for its precache, and reload so
 * the page and its workers are controlled by it. */
async function precache(page) {
  const from = net.log.length;
  await page.evaluate(async () => {
    await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    await navigator.serviceWorker.ready;
  });
  const fetched = net.log.slice(from).reduce((s, r) => s + r.bytes, 0);
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => !!navigator.serviceWorker.controller && window.bench);
  const cached = await page.evaluate(() => bench.cachedBytes());
  return { fetched, cached };
}

/* The largest peak resident set of any Chromium renderer now running. A
 * dedicated worker runs in its page's renderer, so this is the tab's peak
 * with its worker in it. Only this script's browser is running. */
function rendererPeakBytes() {
  let peak = 0;
  for (const pid of execFileSync('ps', ['-eo', 'pid=']).toString().trim().split(/\s+/)) {
    try {
      const cmd = readFileSync(`/proc/${pid}/cmdline`, 'utf8');
      if (!cmd.includes('--type=renderer')) continue;
      const m = /VmHWM:\s+(\d+) kB/.exec(readFileSync(`/proc/${pid}/status`, 'utf8'));
      if (m) peak = Math.max(peak, Number(m[1]) * 1024);
    } catch { /* gone */ }
  }
  return peak;
}

async function throttle(page, rate) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate });
  return cdp;
}

/* Both engines in their workers: start, then both soundings twice. */
async function workers(page, which = ['js', 'py']) {
  const out = {};
  for (const engine of which) {
    const start = await page.evaluate((e) => bench.startWorker(e), engine);
    const first = await page.evaluate((e) => bench.invertInWorker(e), engine);
    const second = await page.evaluate((e) => bench.invertInWorker(e), engine);
    await page.evaluate((e) => bench.stopWorker(e), engine);
    out[engine] = { start, first, second };
  }
  return out;
}

async function onPage(page) {
  const js1 = await page.evaluate(() => bench.jsOnPage());
  const js2 = await page.evaluate(() => bench.jsOnPage());
  const pyStart = await page.evaluate(() => bench.pyStartOnPage());
  const py1 = await page.evaluate(() => bench.pyOnPage());
  const py2 = await page.evaluate(() => bench.pyOnPage());
  return { js: { first: js1, second: js2 }, py: { start: pyStart, first: py1, second: py2 } };
}

/* ------------------------------------------------------------- the runs */

const results = {
  machine: { cpus: cpus().length, model: cpus()[0].model, loadavg_before: loadavg(),
    chromium: null, node: process.version },
  manifest: JSON.parse(await readFile(join(HERE, 'vendor', 'manifest.json'), 'utf8')),
  reps: [], cold_page_4x: [], memory: [], native: [], unexpected_requests: [],
};

/* What a host would send compressed, for the record: the cache stores the
 * decoded bodies, so the precache's size on the device is the raw figure. */
results.compressed = {};
for (const f of results.manifest.files) {
  const body = await readFile(join(HERE, 'vendor', f.url));
  results.compressed[f.url] = {
    raw: body.length,
    gzip9: gzipSync(body, { level: 9 }).length,
    brotli11: brotliCompressSync(body, { params: {
      [zc.BROTLI_PARAM_QUALITY]: 11, [zc.BROTLI_PARAM_SIZE_HINT]: body.length } }).length,
  };
}

const profiles = [];
async function freshProfile() {
  const dir = await mkdtemp(join(tmpdir(), 'pyodide-spike-'));
  profiles.push(dir);
  return dir;
}

let soundings = null;

for (let rep = 0; rep < REPS; rep++) {
  console.log(`rep ${rep + 1}/${REPS}`);
  const r = {};
  const profile = await freshProfile();
  net.down = false;
  let { ctx, errors } = await launch(profile);
  let page = await benchPage(ctx);
  results.machine.chromium = ctx.browser() ? ctx.browser().version() : results.machine.chromium;
  if (!soundings) soundings = await page.evaluate(() => bench.soundings());
  r.precache = await precache(page);

  net.down = true;
  r.cold = await workers(page);
  console.log('  cold py start', r.cold.py.start.ms.toFixed(0), 'ms');

  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.bench);
  r.reload = await workers(page);
  console.log('  reload py start', r.reload.py.start.ms.toFixed(0), 'ms');
  await ctx.close();

  ({ ctx, errors } = await launch(profile));
  page = await benchPage(ctx);
  r.restart = await workers(page);
  /* what the start would be with numpy alone, for the record */
  r.restart_numpy_only = await page.evaluate(() => bench.startWorker('py-numpy'));
  await page.evaluate(() => bench.stopWorker('py-numpy'));
  console.log('  restart py start, numpy only', r.restart_numpy_only.ms.toFixed(0), 'ms',
    Object.keys(r.restart_numpy_only.phases).join(' '));
  console.log('  restart py start', r.restart.py.start.ms.toFixed(0), 'ms');

  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.bench);
  r.page1x = await onPage(page);

  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => window.bench);
  const cdp = await throttle(page, 4);
  r.page4x = await onPage(page);
  /* the JavaScript worker under the same page throttling: if Chromium
   * throttled workers this would be about four times its unthrottled time */
  r.worker_under_page_4x = await workers(page, ['js']);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
  r.errors = errors;
  await ctx.close();
  console.log('  page 4x py start', r.page4x.py.start.ms.toFixed(0), 'ms');
  results.reps.push(r);

  /* a cold start on the page at 4x: a fresh profile, precached, offline */
  const p2 = await freshProfile();
  net.down = false;
  ({ ctx, errors } = await launch(p2));
  page = await benchPage(ctx);
  await precache(page);
  net.down = true;
  await throttle(page, 4);
  results.cold_page_4x.push(await onPage(page));
  await ctx.close();
}

/* Peak memory, each engine alone in a fresh browser of its own */
net.down = false;
for (let rep = 0; rep < REPS; rep++) {
  for (const engine of ['js', 'py']) {
    const { ctx } = await launch(await freshProfile());
    const page = await benchPage(ctx);
    const run = (await workers(page, [engine]))[engine];
    /* measured with the worker stopped would miss it: start it again and
     * run once more, then read memory while it is alive */
    await page.evaluate((e) => bench.startWorker(e), engine);
    await page.evaluate((e) => bench.invertInWorker(e), engine);
    const memory = await page.evaluate(() => bench.memory());
    const rss = rendererPeakBytes();
    await ctx.close();
    results.memory.push({ engine, rendererPeakBytes: rss, uaMemory: memory,
      wasmHeapBytes: engine === 'py' ? run.second.at(-1).heapBytes : null });
    console.log(`  memory ${engine}: renderer peak ${(rss / 1e6).toFixed(0)} MB`);
  }
}

/* Native CPython on the same soundings and configuration */
const tmp = await mkdtemp(join(tmpdir(), 'pyodide-spike-native-'));
profiles.push(tmp);
await writeFile(join(tmp, 'soundings.json'), JSON.stringify(soundings));
const env = Object.assign({}, process.env, {
  PYTHONPATH: join(REPO, 'src') + ':' + HERE,
  OPENBLAS_NUM_THREADS: '1', OMP_NUM_THREADS: '1', MKL_NUM_THREADS: '1',
});
for (let rep = 0; rep < REPS; rep++) {
  const out = execFileSync('python', [join(HERE, 'engine.py'), join(tmp, 'soundings.json')],
    { env, maxBuffer: 1 << 26 }).toString();
  results.native.push(JSON.parse(out));
}
results.native_versions = JSON.parse(execFileSync('python', ['-c',
  'import json, sys, numpy, scipy, yaml; print(json.dumps({"python": sys.version.split()[0],' +
  ' "numpy": numpy.__version__, "scipy": scipy.__version__, "pyyaml": yaml.__version__}))'],
{ env }).toString());

results.unexpected_requests = net.log.filter((e) => e.missing).map((e) => e.path);
results.machine.loadavg_after = loadavg();
results.soundings = soundings.map((s) => s.sounding_id);
await writeFile(OUT, JSON.stringify(results) + '\n');
console.log('wrote', OUT);

for (const dir of profiles) await rm(dir, { recursive: true, force: true });
server.close();

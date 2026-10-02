/* A heavy project, and the main-thread time a piece of page work costs.
 *
 * PLAN.md step 1.3 is done when a project with 50 photos and 10 workbooks
 * autosaves in under 50 ms and survives a reload. smoke.mjs holds the app to
 * that and bench/web.mjs records the number; both build the project here so
 * they time the same thing.
 *
 * The photos are real JPEGs drawn on a canvas at the size image-slot.js
 * keeps (1600 px on the long edge, quality 0.82), with seeded noise so each
 * one is different and about as hard to compress as a phone photo. The
 * workbooks are the sample sheets in their roles, so the app still reads
 * the project, and enough more of 150 kB of seeded bytes, under roles the
 * app does not read, to make ten.
 */

/* Runs in the page. Puts the project in the store and resolves to its
 * photo and workbook counts and its size as JSON, in MB. */
export async function buildHeavyProject() {
  const app = window.GWT.app;
  if (!window.GWT.hasBundle('samples')) await window.GWT.load('samples');
  let seed = 1234567;
  const random = () => {
    seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const canvas = document.createElement('canvas');
  canvas.width = 1600; canvas.height = 1200;
  const ctx = canvas.getContext('2d');
  const photo = (i) => {
    const g = ctx.createLinearGradient(0, 0, 1600, 1200);
    g.addColorStop(0, `hsl(${(i * 37) % 360}, 55%, 35%)`);
    g.addColorStop(1, `hsl(${(i * 83) % 360}, 45%, 70%)`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 1600, 1200);
    const img = ctx.getImageData(0, 0, 1600, 1200);
    for (let p = 0; p < img.data.length; p += 4) {
      const n = (random() - 0.5) * 22;
      img.data[p] += n; img.data[p + 1] += n; img.data[p + 2] += n;
    }
    ctx.putImageData(img, 0, 0);
    return { dataUrl: canvas.toDataURL('image/jpeg', 0.82), width: 1600, height: 1200,
      mime: 'image/jpeg', name: `photo-${i}.jpg`, caption: `Photo ${i}` };
  };
  const SLOTS = {
    completion: ['site', 'drilling', 'cuttings', 'development', 'headworks', 'pump'],
    quality: ['sampling', 'appearance', 'field_meter'],
    pumping: ['setup', 'discharge', 'disposal'],
    geophysical: ['survey', 'terrain', 'community'],
    supervision: ['materials', 'installation', 'grouting', 'nonconformance'],
    handover: ['ceremony', 'committee', 'plaque', 'inuse'],
  };
  const photos = {};
  let n = 0;
  for (const [set, keys] of Object.entries(SLOTS)) {
    photos[set] = { __extra: [] };
    for (const key of keys) photos[set][key] = photo(n++);
  }
  while (n < 50) {
    photos.completion.__extra.push({ label: `Extra ${n}`, image: photo(n) });
    n += 1;
  }

  /* every sample sheet but the survey, whose inversion would make a reload
   * a wait for the worker rather than a read of the store */
  const sources = {};
  for (const sample of Object.values(window.GWT.data.samples)) {
    for (const [role, file] of Object.entries(sample.files)) {
      if (role !== 'ves' && !sources[role]) sources[role] = { name: file.name, b64: file.b64 };
    }
  }
  let extra = 0;
  while (Object.keys(sources).length < 10) {
    const bytes = new Uint8Array(150000);
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = (random() * 256) | 0;
    sources[`extra_${++extra}`] = { name: `field-sheet-${extra}.xlsx`,
      b64: window.GWT.support.bytesToBase64(bytes) };
  }

  const state = Object.assign(app.blankState(), { nav: 'overview', photos, sources });
  state.site.project = 'Heavy project';
  app.store.replace(state);
  /* read the sheets as the app would, which fills in the site details they
   * carry, so a reload finds the session it left */
  await app.recompute();
  return {
    photos: n, workbooks: Object.keys(sources).length,
    megabytes: JSON.stringify(state).length / 1e6,
  };
}

/* Build the heavy project in `page` and time its autosaves: the first,
 * which writes the whole session, and then `samples` more, each after one
 * typed field, as the app's own 400 ms autosave would write it. `cpu` is a
 * DevTools CPU slowdown for the timed part. Each is { main, wall, value }
 * (see mainThreadTime), value being whether the write went through and what
 * the storage says it wrote. */
export async function timeAutosaves(page, { samples = 5, cpu = 1 } = {}) {
  const built = await page.evaluate(buildHeavyProject);
  /* the build's own autosave may have gone in already; this makes the
   * first timed write the whole session again */
  await page.evaluate(() => window.GWT.app.store.forget());
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: cpu });
  try {
    const first = await mainThreadTime(page, async () =>
      ({ ok: await window.GWT.app.store.persist(),
        last: window.GWT.app.storage ? window.GWT.app.storage.stats.last : null }));
    const edits = [];
    for (let i = 0; i < samples; i += 1) {
      edits.push(await mainThreadTime(page, async (n) => {
        window.GWT.app.store.set('site.community', 'typed ' + n);
        const ok = await window.GWT.app.store.persist();
        return { ok, last: window.GWT.app.storage ? window.GWT.app.storage.stats.last : null };
      }, i));
      /* past the 400 ms autosave the set() scheduled, which a build without
       * a direct persist() cancelling it would otherwise run inside the
       * next sample */
      await page.waitForTimeout(600);
    }
    return { built, first, edits };
  } finally {
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
    await cdp.detach();
  }
}

/* The main-thread time `fn` (a function run in the page, which may return a
 * promise) takes from its call to its settling: every task the page's main
 * thread ran in that interval, from a Chromium trace, clipped to the
 * interval and summed. Asynchronous work counts only where it runs on the
 * main thread, which is the time a user feels as a stutter. Returns
 * { main, wall, value } with times in ms. */
export async function mainThreadTime(page, fn, arg) {
  const browser = page.context().browser();
  await browser.startTracing(page, { categories: ['blink.user_timing',
    'disabled-by-default-devtools.timeline'] });
  let value, buffer;
  try {
    value = await page.evaluate(async ([source, a]) => {
      const f = new Function(`return (${source})`)();
      performance.mark('gwt-timed-start');
      const out = await f(a);
      performance.mark('gwt-timed-end');
      return out === undefined ? null : out;
    }, [fn.toString(), arg === undefined ? null : arg]);
  } finally {
    buffer = await browser.stopTracing();
  }
  const trace = JSON.parse(buffer.toString());
  const events = trace.traceEvents || trace;
  const start = events.find((e) => e.name === 'gwt-timed-start');
  const end = events.find((e) => e.name === 'gwt-timed-end');
  const tasks = events.filter((e) => e.name === 'RunTask' && e.ph === 'X' &&
    e.pid === start.pid && e.tid === start.tid && e.ts < end.ts && e.ts + e.dur > start.ts)
    .map((e) => [Math.max(e.ts, start.ts), Math.min(e.ts + e.dur, end.ts)])
    .sort((a, b) => a[0] - b[0]);
  let main = 0, reach = -Infinity;
  for (const [a, b] of tasks) {
    const from = Math.max(a, reach);
    if (b > from) main += b - from;
    reach = Math.max(reach, b);
  }
  return { main: main / 1000, wall: (end.ts - start.ts) / 1000, value };
}

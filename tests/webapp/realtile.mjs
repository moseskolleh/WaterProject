/* The real-tile acceptance in the browser (PLAN.md step 4.1): the tile and
 * the window tests/test_real_tile.py reads and analyses, run through the
 * browser's engine in Chromium and held to what the Python one made of them.
 *
 * Local, never in CI, like the pytest: a Copernicus GLO-30 tile is 48 MB
 * and none is committed. Run the pytest first, on the same tile; it writes
 * tests/acceptance/real_tile.json, which names the tile by its size and
 * SHA-256, and this refuses a file written for another:
 *
 *   GWT_DEM_TILE=path/to/n08w012.tif python -m pytest -rP tests/test_real_tile.py
 *   GWT_DEM_TILE=path/to/n08w012.tif node tests/webapp/realtile.mjs
 *
 * The harness serves the tile for the life of the run (its overlay) and the
 * page reads it as it reads a file the operator drops: a Blob, sliced for
 * each range. Held exactly, as the parity suite holds the fixtures: the
 * tile read whole, every block decoded by the browser's own inflate, by a
 * digest of every value and of the centres, and its layout field by field;
 * the window under each of the pytest's names (the tile's own, the one
 * Copernicus gives it, a bare one, and the bare one declared as Copernicus
 * GLO-30): what the file was recognised as, the set's credit and the
 * prompts, the centre, the plan block by block, every read the page made to
 * open the file and to read the window, and the read itself by digests,
 * counts and its read report word for word; and the analysis of the window
 * under the tile's own name, at the default settings and in float32
 * storage, as both apps run it: every layer but the wetness index by its
 * digest, the summary, the drainage lines and their parts field by field,
 * the captions word for word and the GeoJSON to the character. The wetness
 * index passes through a library's logarithm, which may differ from
 * numpy's in the last bit of a float64; stored in float32, that can move a
 * value by one float32 step at most, so 50 of its cells and its least and
 * greatest values are held to one step, its count exactly and its display
 * range, worked out in float64, to 1e-12. Its digest is reported, alike or
 * not. Then the window's lineament candidates (PLAN.md step 4.2), all held
 * exactly: the candidates field by field, the summary, the roses, the
 * captions word for word and their GeoJSON to the character.
 */
import { withPage } from './harness.mjs';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const RECORD = fileURLToPath(new URL('../acceptance/real_tile.json', import.meta.url));

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

const tilePath = process.env.GWT_DEM_TILE;
if (!tilePath) {
  console.error('GWT_DEM_TILE names no tile: set it to the Copernicus GLO-30 tile tests/test_real_tile.py read');
  process.exit(1);
}
let expected;
try {
  expected = JSON.parse(await readFile(RECORD, 'utf8'));
} catch {
  console.error(`${RECORD} cannot be read: run tests/test_real_tile.py on the tile first`);
  process.exit(1);
}
const bytes = await readFile(tilePath);
const sha256 = createHash('sha256').update(bytes).digest('hex');
const tile = expected.tile;
if (basename(tilePath) !== tile.name || bytes.length !== tile.size || sha256 !== tile.sha256) {
  console.error(`${RECORD} was written for ${tile.name} (${tile.size} bytes, SHA-256 ${tile.sha256}), ` +
    `not for ${basename(tilePath)} (${bytes.length} bytes, SHA-256 ${sha256}): run tests/test_real_tile.py ` +
    'on this tile first');
  process.exit(1);
}

/* where two answers first differ: numbers by Object.is, the rest exactly */
const firstDifference = (a, b, path = '') => {
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return `${path}: ${a.length} items, expected ${b.length}`;
    for (let i = 0; i < a.length; i++) {
      const found = firstDifference(a[i], b[i], `${path}[${i}]`);
      if (found) return found;
    }
    return null;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object' && !Array.isArray(a) && !Array.isArray(b)) {
    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])].sort();
    for (const key of keys) {
      const found = firstDifference(a[key], b[key], `${path}.${key}`);
      if (found) return found;
    }
    return null;
  }
  return Object.is(a, b) ? null : `${path}: js ${JSON.stringify(a)}, py ${JSON.stringify(b)}`;
};
/* where two texts first differ, and a little of each from there */
const textDifference = (got, want) => {
  if (typeof got !== 'string') return `js ${JSON.stringify(got)}`;
  let at = 0;
  while (at < got.length && at < want.length && got[at] === want[at]) at += 1;
  return `${got.length} characters, expected ${want.length}; from character ${at}: ` +
    `js ${JSON.stringify(got.slice(at, at + 80))}, py ${JSON.stringify(want.slice(at, at + 80))}`;
};
const pick = (object, keys) => Object.fromEntries(keys.map((key) => [key, object[key]]));
const counted = (n, one, many) => `${n.toLocaleString('en-GB')} ${n === 1 ? one : many}`;

/* how many float32 steps apart two numbers are once stored in float32,
 * through the bits read as integers ordered as the numbers are */
const f32 = new Float32Array(1), u32 = new Uint32Array(f32.buffer);
const ordered = (v) => {
  f32[0] = v;
  return u32[0] & 0x80000000 ? -(u32[0] & 0x7FFFFFFF) : u32[0];
};
const steps = (a, b) => (a === null || b === null ? (a === b ? 0 : Infinity) : Math.abs(ordered(a) - ordered(b)));
const relative = (a, b) => (a === null || b === null ? (a === b ? 0 : Infinity)
  : Math.abs(a - b) / Math.max(1, Math.abs(b)));

const KINDS = Object.keys(expected.windows);
const ask = {
  name: tile.name,
  windows: KINDS.map((kind) => [kind, expected.windows[kind].name, expected.windows[kind].declared]),
  twiAt: expected.analysis.twi.at,
};

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/__engine.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.core && window.GWT.data);

  const got = await page.evaluate(async (ask) => {
    const C = GWT.core;
    /* numbers as the pytest's JSON carries them: NaN as null, the
     * infinities and -0 as strings */
    const number = (v) => (v !== v ? null : v === Infinity ? 'Infinity' : v === -Infinity ? '-Infinity'
      : Object.is(v, -0) ? '-0' : v);
    const clean = (v) => (Array.isArray(v) || ArrayBuffer.isView(v) ? Array.from(v, clean)
      : typeof v === 'number' ? number(v) : v);
    /* float64 little-endian, every NaN the one NaN, signs of zero kept */
    const digest = (values) => {
      const out = new Uint8Array(values.length * 8), view = new DataView(out.buffer);
      for (let i = 0; i < values.length; i++) {
        if (values[i] !== values[i]) {
          view.setUint32(8 * i, 0, true);
          view.setUint32(8 * i + 4, 0x7FF80000, true);
        } else {
          view.setFloat64(8 * i, values[i], true);
        }
      }
      return C.sha256Hex(out);
    };
    const spots = (values, n = 10) =>
      Array.from({ length: n }, (_, k) => number(values[Math.floor(k * (values.length - 1) / (n - 1))]));
    /* a number's float64 bits, big-endian, as 16 hex digits */
    const hex = (v) => {
      const view = new DataView(new ArrayBuffer(8));
      view.setFloat64(0, v);
      let out = '';
      for (let i = 0; i < 8; i++) out += (view.getUint8(i) + 256).toString(16).slice(1);
      return out;
    };
    /* links or parts as one line of JSON with each length by its bits, the
     * text the pytest's _lines_digest hashes */
    const linesDigest = (list) => C.sha256Hex(JSON.stringify(list.map((line) => ({ ...line,
      length_m: hex(line.length_m) }))));
    const seconds = {};
    const timed = async (label, f) => {
      const start = performance.now();
      const out = await f();
      seconds[label] = (performance.now() - start) / 1000;
      return out;
    };

    const blob = await (await fetch('/__realtile.tif')).blob();
    const readAt = async (offset, length) =>
      new Uint8Array(await blob.slice(offset, offset + length).arrayBuffer());

    /* the tile read whole, every block decoded by the browser's own inflate */
    const answer = { settings: C.withConfig(null).terrain };
    {
      const all = new Uint8Array(await blob.arrayBuffer());
      const whole = await timed('whole', () => C.readGeoTiff(all, ask.name));
      answer.whole = { layout: Object.fromEntries(Object.entries(whole.layout).map(([k, v]) => [k, clean(v)])),
        z: [digest(whole.z), spots(whole.z)], x: digest(whole.x), y: digest(whole.y) };
    }

    /* a file opened for its layout as geotiff.open_geotiff opens one: the
     * first 64 KiB, then each range still missing rounded up to 64 KiB, at
     * most 16 rounds */
    const opened = async (name) => {
      const unit = 65536, first = Math.min(blob.size, unit), opening = [[0, first]];
      const chunks = [[0, await readAt(0, first)]];
      for (let round = 0; round <= 16; round++) {
        const found = C.elevationFile(name, blob.size, chunks);
        if (!Array.isArray(found)) return { found, opening };
        if (round === 16) break;
        for (const [offset, length] of found) {
          const n = Math.min(Math.ceil(length / unit) * unit, blob.size - offset);
          chunks.push([offset, await readAt(offset, n)]);
          opening.push([offset, n]);
        }
      }
      throw new Error(`${name}: still missing bytes after 16 rounds`);
    };

    const terrain = C.withConfig(null).terrain;
    const reads = {};
    answer.windows = {};
    for (const [kind, name, declared] of ask.windows) {
      const { found, opening } = await opened(name);
      const credit = C.terrainCredit([found], declared);
      const centre = C.windowCentre(null, null, [found]);
      const plan = C.planElevationWindow([found], centre, terrain.analysis_radius_km, null, null, declared);
      const ranges = C.elevationBlockRanges(plan), blocks = new Array(plan.blocks.length);
      const read = await timed('read ' + kind, async () => {
        for (const r of ranges) {
          const data = await readAt(r.offset, r.length);
          for (const b of r.blocks) {
            const block = plan.blocks[b];
            blocks[b] = data.slice(block.offset - r.offset, block.offset - r.offset + block.length);
          }
        }
        return C.readElevationWindow(plan, blocks, null, null);
      });
      reads[kind] = read;
      const g = read.grid, last = (a) => a[a.length - 1];
      answer.windows[kind] = {
        name, declared,
        file: [found.sourceId, found.notes],
        credit: [credit.label, credit.credit, credit.notice, credit.surface, credit.seaClean],
        prompts: [C.fileNotes(found, declared)],
        centre: [number(centre.lon), number(centre.lat), centre.label, centre.exact, centre.note],
        plan: {
          order: plan.files.map((f) => f.name), sources: plan.sources, offsets: plan.offsets,
          at: [plan.ci, plan.cj, plan.hx, plan.hy, plan.hxs, plan.hys, plan.width, plan.height, plan.tile],
          dx: number(plan.dx), dy: number(plan.dy),
          lons: [digest(plan.lons), number(plan.lons[0]), number(last(plan.lons))],
          lats: [digest(plan.lats), number(plan.lats[0]), number(last(plan.lats))],
          missing: plan.missing, edges: plan.edges.map((e) => [e.missing, e.file, e.row, e.column]),
          blocks: plan.blocks.map((b) => [b.file, b.index, b.offset, b.length, b.rows, b.window, b.edges]),
        },
        opening,
        reads: ranges.map((r) => [r.name, r.offset, r.length]),
        read: {
          z: [digest(g.z), spots(g.z)], reasons: digest(read.reasons), sea: digest(read.assumedSea),
          counts: [read.cells, read.voids, read.uncovered, read.implausible, read.assumed],
          coverage: number(read.coverage), shown: read.shown, notes: read.notes, prompts: read.prompts,
          figure: read.figureCredit, cell: g.cellNote, source: g.sourceId, label: g.label, gridCredit: g.credit,
          notice: read.notice, surface: read.surface, seaClean: g.seaClean, files: g.files,
        },
      };
    }

    /* the window under the tile's own name, analysed as both apps run it:
     * the default settings, float32 storage, the grid's own square shown */
    const read = reads.own;
    const a = await timed('analysis', () => C.analyseTerrain(read.grid, null, null, null));
    const core = a.core;
    const layers = { cls: core.cls, code: core.code, flag: core.flag, raised: core.raised,
      flatRouted: core.flatRouted, stream: a.stream, count: core.count, areaUnits: core.areaUnits,
      filled: a.filled, fillDepth: a.fillDepth, p: a.p, q: a.q, tanb: a.tanb };
    a.hillshades.forEach((layer, j) => { layers['hillshade' + j] = layer; });
    Object.assign(layers, { hillshadeMulti: a.hillshadeMulti, twiArg: a.twiArg, profile: a.profile,
      tangential: a.tangential, dx: core.dx, dy: core.dy, dg: core.dg });
    let count = 0, least = Infinity, most = -Infinity;
    for (const v of a.twi) {
      if (v - v !== 0) continue;
      count += 1;
      if (v < least) least = v;
      if (v > most) most = v;
    }
    const summary = Object.entries(a.summary).filter(([key]) => key !== 'twi_range');
    let seaCells = 0;
    for (const v of core.cls) seaCells += v === 2 ? 1 : 0;
    const geojson = await timed('geojson', () => C.drainageGeoJson(C.terrainCore(a), a.parts, {
      label: read.grid.label, figure_credit: read.figureCredit, notice: read.notice, surface: read.surface,
      area: a.settings.drainage_area_km2, radius: read.plan.radiusKm, margin: read.plan.marginKm,
      centre: read.centre, fill_note_m: a.settings.fill_note_m, sea_clean: read.grid.seaClean,
      sea_cells: seaCells, sea_level_m: a.settings.sea_level_m,
    }));
    answer.analysis = {
      precision: a.twi instanceof Float32Array ? 'float32' : 'float64',
      layers: Object.fromEntries(Object.entries(layers).map(([name, v]) => [name, [digest(v), spots(v)]])),
      twi: { digest: digest(a.twi), at: ask.twiAt, values: ask.twiAt.map((i) => number(a.twi[i])), count,
        min: number(least), max: number(most), range: a.summary.twi_range.map(number) },
      summary: { keys: summary.map(([key]) => key), values: summary.map(([, v]) => number(v)) },
      scalars: [a.unresolved, a.kCells, a.floored, a.zeroFill], shown: Array.from(core.shown),
      fields: { links: Object.keys(a.links[0] || {}), parts: Object.keys(a.parts[0] || {}) },
      links: { digest: linesDigest(a.links), values: a.links.map((line) => clean(Object.values(line))) },
      parts: { digest: linesDigest(a.parts), values: a.parts.map((part) => clean(Object.values(part))) },
      captions: Object.entries(C.terrainCaptions(a, read, read.centre.label)),
      geojson,
    };
    const lin = await timed('lineaments', () => C.lineamentCandidates(a, null, null));
    const linGeojson = C.lineamentGeoJson(lin, read.grid.lons, read.grid.lats, {
      label: read.grid.label, figure_credit: read.figureCredit, notice: read.notice, surface: read.surface,
      radius: read.plan.radiusKm, centre: read.centre,
    });
    answer.lineaments = {
      fields: Object.keys(lin.lineaments[0] || {}),
      summary: { keys: Object.keys(lin.summary), values: Object.values(lin.summary).map(number) },
      values: lin.lineaments.map((l) => [l.id, l.kind, l.start.map(number), l.end.map(number), number(l.length_m),
        number(l.strike_deg), l.pieces, l.cells, l.cut]),
      roses: [lin.roseValleyM.map(number), lin.roseRidgeM.map(number), Array.from(lin.roseValleys),
        Array.from(lin.roseRidges)],
      frame: lin.frame.map(number), shown: Array.from(lin.shown),
      captions: Object.entries(C.lineamentCaptions(lin, read.centre.label)),
      geojson: linGeojson,
    };
    answer.seconds = seconds;
    return answer;
  }, ask);

  check('the browser\'s terrain settings are the pytest\'s', !firstDifference(got.settings, expected.settings),
    firstDifference(got.settings, expected.settings));

  const W = expected.whole;
  check(`the tile read whole in the page: all ${counted(W.layout.offsets.length, 'block', 'blocks')} decoded by ` +
    `the browser's inflate, ${counted(W.layout.width * W.layout.height, 'value', 'values')} Python's to the bit, ` +
    'and the cell centres', !firstDifference(pick(got.whole, ['z', 'x', 'y']), pick(W, ['z', 'x', 'y'])),
  firstDifference(pick(got.whole, ['z', 'x', 'y']), pick(W, ['z', 'x', 'y'])));
  check('the tile\'s layout, field by field', !firstDifference(got.whole.layout, W.layout),
    firstDifference(got.whole.layout, W.layout));

  for (const kind of KINDS) {
    const want = expected.windows[kind], mine = got.windows[kind];
    const name = `${kind} (${want.name}${want.declared[0] === 'detect' ? '' : ', declared ' + want.declared[0]})`;
    for (const [label, members] of [
      ['what the file is, the credit and the prompts', ['file', 'credit', 'prompts']],
      ['the centre and the plan, block by block', ['centre', 'plan']],
      [`the ${counted(want.opening.length, 'read', 'reads')} that opened the file and the ` +
        `${counted(want.reads.length, 'read', 'reads')} of the window`, ['opening', 'reads']],
      ['the window: its heights, reasons, counts and read report', ['read']],
    ]) {
      const found = firstDifference(pick(mine, members), pick(want, members));
      check(`${name} - ${label}`, !found, found);
    }
  }

  const A = expected.analysis, mine = got.analysis;
  check(`the analysis is stored in ${A.precision}, as Python's`, mine.precision === A.precision,
    `js ${mine.precision}`);
  {
    const found = firstDifference(mine.layers, A.layers);
    check(`all ${Object.keys(A.layers).length} layers but the wetness index, by digest and ten cells`, !found, found);
  }
  {
    const found = firstDifference(pick(mine, ['summary', 'scalars', 'shown', 'fields']),
      pick(A, ['summary', 'scalars', 'shown', 'fields']));
    check('the summary, the unresolved flats, the square shown and the fields of a line', !found, found);
  }
  for (const kind of ['links', 'parts']) {
    const found = firstDifference(mine[kind], A[kind]);
    check(`the ${counted(A[kind].values.length, kind === 'links' ? 'drainage line' : 'part',
      kind === 'links' ? 'drainage lines' : 'parts')}, field by field and by digest`, !found, found);
  }
  {
    const found = firstDifference(mine.captions, A.captions);
    check(`the ${A.captions.length} captions, word for word`, !found, found);
  }
  check(`the GeoJSON (${counted(A.geojson.length, 'character', 'characters')}), to the character`,
    mine.geojson === A.geojson, textDifference(mine.geojson, A.geojson));

  /* the wetness index: one float32 step where it is stored in float32 */
  const T = A.twi, t = mine.twi, misses = [];
  const near = A.precision === 'float32' ? (a, b) => steps(a, b) <= 1 : (a, b) => relative(a, b) <= 1e-12;
  let moved = 0;
  if (firstDifference(t.at, T.at)) misses.push('the cells asked for');
  T.values.forEach((v, k) => {
    if (!Object.is(t.values[k], v)) moved += 1;
    if (!near(t.values[k], v)) misses.push(`cell ${T.at[k]}: js ${t.values[k]}, py ${v}`);
  });
  for (const key of ['min', 'max']) if (!near(t[key], T[key])) misses.push(`${key}: js ${t[key]}, py ${T[key]}`);
  if (t.count !== T.count) misses.push(`count: js ${t.count}, py ${T.count}`);
  T.range.forEach((v, k) => {
    if (relative(t.range[k], v) > 1e-12) misses.push(`range[${k}]: js ${t.range[k]}, py ${v}`);
  });
  check(`the wetness index: ${counted(T.count, 'cell', 'cells')} with a value, ${T.values.length} of them, the ` +
    'least and greatest to one float32 step and the display range to 1e-12', misses.length === 0,
  misses.slice(0, 4).join('; '));
  {
    const L = expected.lineaments, lin = got.lineaments;
    const members = ['fields', 'summary', 'values', 'roses', 'frame', 'shown'];
    const found = firstDifference(pick(lin, members), pick(L, members));
    check(`the ${counted(L.values.length, 'lineament candidate', 'lineament candidates')}, field by field, ` +
      'with the summary and the roses', !found, found);
    const said = firstDifference(lin.captions, L.captions);
    check(`the ${L.captions.length} lineament captions, word for word`, !said, said);
    check(`the lineaments' GeoJSON (${counted(L.geojson.length, 'character', 'characters')}), to the character`,
      lin.geojson === L.geojson, textDifference(lin.geojson, L.geojson));
  }
  console.log(`     the wetness index's digest is ${t.digest === T.digest ? 'Python\'s' : 'not Python\'s'}; ` +
    `${moved} of the ${T.values.length} cells held differ from Python's at all`);
  console.log('     seconds in the page: ' + Object.entries(got.seconds)
    .map(([label, s]) => `${label} ${s.toFixed(2)}`).join(', '));

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n     '));
}, { overlay: { '/__realtile.tif': { body: bytes, type: 'image/tiff' } } });

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

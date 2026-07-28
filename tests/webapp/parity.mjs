/* Compare the browser engine against reference values produced by the Python
 * toolkit. Regenerate the references with tests/webapp/make_reference.py.
 */
import { withPage } from './harness.mjs';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const REF = fileURLToPath(new URL('reference.json', import.meta.url));

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

function close(a, b, tol = 1e-6) {
  if (a === null || b === null || a === undefined || b === undefined) return a === b;
  return Math.abs(a - b) <= tol * Math.max(1, Math.abs(b));
}

const reference = JSON.parse(await readFile(REF, 'utf8'));

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/__engine.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.core && window.GWT.data);

  const parsed = await page.evaluate(async () => {
    const S = GWT.support, C = GWT.core, D = GWT.data;
    async function grids(b64) {
      return GWT.support.readXlsx(S.base64ToBytes(b64));
    }
    const out = {};

    const vesSheets = await grids(D.samples.rokel.files.ves.b64);
    out.ves = C.readVesSheets(vesSheets, 'rokel_ves.xlsx').map((s) => ({
      id: s.sounding_id, array: s.array_type,
      ab2: s.ab2, mn: s.mn.map((v) => (isFinite(v) ? v : null)), rho: s.rho_app,
      site: s.site, flags: s.flags.map((f) => [f.level, f.code, f.message]),
    }));

    const drillSheets = await grids(D.samples.dr_timbo.files.drilling.b64);
    const log = C.drillingFromGrid(drillSheets[0].rows, 'dr_timbo_drilling_log.xlsx');
    out.drilling = {
      ref: log.borehole_ref, total: log.total_depth_m, strikes: log.water_strikes_m,
      intervals: log.intervals.map((i) => [i.top_m, i.bottom_m, i.description]),
      site: log.site, flags: log.flags.map((f) => [f.level, f.code, f.message]),
    };

    const wqSheets = await grids(D.samples.dr_timbo.files.quality.b64);
    const sample = C.qualityFromGrid(wqSheets[0].rows, 'dr_timbo_water_quality.xlsx');
    out.quality = {
      id: sample.sample_id, ref: sample.borehole_ref, lab: sample.laboratory,
      results: sample.results.map((r) => [r.parameter, r.value, r.unit, r.below_detection, r.detection_limit]),
      flags: sample.flags.map((f) => [f.level, f.code, f.message]),
    };

    const ptSheets = await grids(D.samples.dr_timbo.files.pumping.b64);
    const test = C.pumpingFromGrid(ptSheets[0].rows, 'dr_timbo_constant_test.xlsx');
    out.pumping = {
      type: test.test_type, swl: test.static_water_level_m,
      depth: test.borehole_depth_m, pump: test.pump_setting_m,
      steps: test.steps.map((s) => ({ n: s.step_number, q: s.discharge_m3_per_h,
        t: s.time_min, wl: s.water_level_m, label: s.label })),
      rec_t: test.recovery_time_min, rec_wl: test.recovery_level_m,
      duration: test.pumping_duration_min,
      flags: test.flags.map((f) => [f.level, f.code, f.message]),
    };

    const stepSheets = await grids(D.samples.kuntolo.files.pumping.b64);
    const stepTest = C.pumpingFromGrid(stepSheets[0].rows, 'kuntolo_step_test.xlsx');
    out.step = {
      type: stepTest.test_type, swl: stepTest.static_water_level_m,
      nsteps: stepTest.steps.length,
      steps: stepTest.steps.map((s) => ({ n: s.step_number, q: s.discharge_m3_per_h,
        npoints: s.time_min.length, tmax: Math.max(...s.time_min) })),
      flags: stepTest.flags.map((f) => [f.level, f.code, f.message]),
    };

    // full analysis chains
    const analysis = C.analysePumpingTest(test);
    out.analysis = {
      T: analysis.transmissivity_m2_per_day,
      cj: analysis.cooper_jacob && analysis.cooper_jacob.transmissivity_m2_per_day,
      rec: analysis.recovery && analysis.recovery.transmissivity_m2_per_day,
      theis: analysis.theis && analysis.theis.transmissivity_m2_per_day,
      safe: analysis.yield_recommendation.safe_yield_m3_per_h,
      low: analysis.yield_recommendation.safe_yield_low_m3_per_h,
      high: analysis.yield_recommendation.safe_yield_high_m3_per_h,
      pump_depth: analysis.yield_recommendation.pump_installation_depth_m,
      range_text: analysis.yield_range_text,
      flags: analysis.flags.map((f) => [f.level, f.code]),
    };

    const assessed = C.assessSample(sample);
    out.assessed = {
      verdict: assessed.verdict,
      health: assessed.health_exceedances.map((r) => r.parameter),
      wqi: assessed.wqi && assessed.wqi.value,
      corros: assessed.corrosivity.classification,
      ionic: assessed.ionic && assessed.ionic.error_percent,
    };

    const design = C.designBorehole({ log: log, staticWaterLevelM: test.static_water_level_m });
    out.design = {
      depth: design.total_depth_m, screens: design.screens.map((s) => [s.top_m, s.bottom_m]),
      gravel: design.gravel_pack, screen_len: design.total_screen_length_m,
    };

    const inverted = C.invertSounding(C.readVesSheets(vesSheets, '')[0]);
    out.inversion = {
      rho: inverted.model.resistivities, h: inverted.model.thicknesses,
      err: inverted.fit_error_percent,
    };
    return out;
  });

  const R = reference;
  // --- VES ---
  check('ves: sounding count', parsed.ves.length === R.ves.length,
    `js ${parsed.ves.length} vs py ${R.ves.length}`);
  parsed.ves.forEach((s, i) => {
    const w = R.ves[i];
    if (!w) return;
    check(`ves[${i}] ${s.id}: id`, s.id === w.id, `js ${s.id} vs py ${w.id}`);
    check(`ves[${i}] ${s.id}: readings`, s.ab2.length === w.ab2.length,
      `js ${s.ab2.length} vs py ${w.ab2.length}`);
    check(`ves[${i}] ${s.id}: ab2`, s.ab2.every((v, k) => close(v, w.ab2[k])),
      JSON.stringify(s.ab2) + ' vs ' + JSON.stringify(w.ab2));
    check(`ves[${i}] ${s.id}: rho`, s.rho.every((v, k) => close(v, w.rho[k])),
      JSON.stringify(s.rho) + ' vs ' + JSON.stringify(w.rho));
    check(`ves[${i}] ${s.id}: mn`, s.mn.every((v, k) => (v === null ? w.mn[k] === null : close(v, w.mn[k]))),
      JSON.stringify(s.mn) + ' vs ' + JSON.stringify(w.mn));
    check(`ves[${i}] ${s.id}: flags`, JSON.stringify(s.flags) === JSON.stringify(w.flags),
      JSON.stringify(s.flags) + '\n     vs ' + JSON.stringify(w.flags));
    check(`ves[${i}] ${s.id}: site`,
      s.site.community === w.site.community && s.site.client === w.site.client &&
      close(s.site.easting, w.site.easting) && close(s.site.northing, w.site.northing),
      JSON.stringify(s.site) + '\n     vs ' + JSON.stringify(w.site));
  });

  // --- drilling ---
  check('drilling: total depth', close(parsed.drilling.total, R.drilling.total),
    `js ${parsed.drilling.total} vs py ${R.drilling.total}`);
  check('drilling: strikes', JSON.stringify(parsed.drilling.strikes) === JSON.stringify(R.drilling.strikes),
    JSON.stringify(parsed.drilling.strikes) + ' vs ' + JSON.stringify(R.drilling.strikes));
  check('drilling: intervals', JSON.stringify(parsed.drilling.intervals) === JSON.stringify(R.drilling.intervals),
    JSON.stringify(parsed.drilling.intervals) + '\n     vs ' + JSON.stringify(R.drilling.intervals));
  check('drilling: flags', JSON.stringify(parsed.drilling.flags) === JSON.stringify(R.drilling.flags),
    JSON.stringify(parsed.drilling.flags) + '\n     vs ' + JSON.stringify(R.drilling.flags));

  // --- water quality ---
  check('quality: sample id', parsed.quality.id === R.quality.id,
    `js ${parsed.quality.id} vs py ${R.quality.id}`);
  check('quality: results', JSON.stringify(parsed.quality.results) === JSON.stringify(R.quality.results),
    JSON.stringify(parsed.quality.results) + '\n     vs ' + JSON.stringify(R.quality.results));

  // --- pumping ---
  check('pumping: type', parsed.pumping.type === R.pumping.type,
    `js ${parsed.pumping.type} vs py ${R.pumping.type}`);
  check('pumping: swl', close(parsed.pumping.swl, R.pumping.swl),
    `js ${parsed.pumping.swl} vs py ${R.pumping.swl}`);
  check('pumping: steps', JSON.stringify(parsed.pumping.steps) === JSON.stringify(R.pumping.steps),
    JSON.stringify(parsed.pumping.steps).slice(0, 400) + '\n     vs ' + JSON.stringify(R.pumping.steps).slice(0, 400));
  check('pumping: recovery times', JSON.stringify(parsed.pumping.rec_t) === JSON.stringify(R.pumping.rec_t),
    JSON.stringify(parsed.pumping.rec_t) + '\n     vs ' + JSON.stringify(R.pumping.rec_t));
  check('pumping: flags', JSON.stringify(parsed.pumping.flags) === JSON.stringify(R.pumping.flags),
    JSON.stringify(parsed.pumping.flags) + '\n     vs ' + JSON.stringify(R.pumping.flags));

  // --- step test ---
  check('step: type', parsed.step.type === R.step.type, `js ${parsed.step.type} vs py ${R.step.type}`);
  check('step: n steps', parsed.step.nsteps === R.step.nsteps, `js ${parsed.step.nsteps} vs py ${R.step.nsteps}`);
  check('step: steps', JSON.stringify(parsed.step.steps) === JSON.stringify(R.step.steps),
    JSON.stringify(parsed.step.steps) + '\n     vs ' + JSON.stringify(R.step.steps));
  check('step: flags', JSON.stringify(parsed.step.flags) === JSON.stringify(R.step.flags),
    JSON.stringify(parsed.step.flags) + '\n     vs ' + JSON.stringify(R.step.flags));

  // --- analyses ---
  ['T', 'cj', 'rec', 'theis', 'safe', 'low', 'high', 'pump_depth'].forEach((k) => {
    check(`analysis: ${k}`, close(parsed.analysis[k], R.analysis[k], 1e-4),
      `js ${parsed.analysis[k]} vs py ${R.analysis[k]}`);
  });
  check('analysis: range text', parsed.analysis.range_text === R.analysis.range_text,
    `js "${parsed.analysis.range_text}" vs py "${R.analysis.range_text}"`);
  check('assessment: verdict', parsed.assessed.verdict === R.assessed.verdict,
    `js "${parsed.assessed.verdict}"\n     py "${R.assessed.verdict}"`);
  check('assessment: wqi', close(parsed.assessed.wqi, R.assessed.wqi),
    `js ${parsed.assessed.wqi} vs py ${R.assessed.wqi}`);
  check('assessment: corrosivity', parsed.assessed.corros === R.assessed.corros,
    `js ${parsed.assessed.corros} vs py ${R.assessed.corros}`);
  check('design: screens', JSON.stringify(parsed.design.screens) === JSON.stringify(R.design.screens),
    JSON.stringify(parsed.design.screens) + ' vs ' + JSON.stringify(R.design.screens));
  check('inversion: rho', parsed.inversion.rho.every((v, i) => close(v, R.inversion.rho[i], 1e-3)),
    JSON.stringify(parsed.inversion.rho) + '\n     vs ' + JSON.stringify(R.inversion.rho));
  check('inversion: h', parsed.inversion.h.every((v, i) => close(v, R.inversion.h[i], 1e-3)),
    JSON.stringify(parsed.inversion.h) + '\n     vs ' + JSON.stringify(R.inversion.h));
  check('inversion: fit error', close(parsed.inversion.err, R.inversion.err, 1e-4),
    `js ${parsed.inversion.err} vs py ${R.inversion.err}`);

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n     '));
}, {});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

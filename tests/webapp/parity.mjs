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

    // the Depth Spine payload: the workspace draws, this decides
    const spine = C.buildSpineView({
      name: 'Dr Timbo', log, analysis, assessment: assessed,
    });
    const spineEdited = C.buildSpineView({
      name: 'Dr Timbo', log, analysis, assessment: assessed,
    }, [[18.0, 30.0]]);
    out.spine = {
      total_depth: spine.section.totalDepth,
      domain: spine.section.domain,
      lithology: spine.section.lithology.map((u) => [u.top, u.base, u.aquifer]),
      strikes: spine.section.waterStrikes,
      segments: spine.section.segments.map((s) => [s.kind, s.top, s.base]),
      levels: spine.section.levels,
      screen_limits: spine.section.screenLimits,
      screens: spine.design.screens.map((s) => [s.top, s.base]),
      total_screen_m: spine.design.totalScreenM,
      screen_share: spine.design.screenShare,
      yield_safe: spine.design.yield.safeYieldM3PerH ?? null,
      yield_range: spine.design.yield.rangeText ?? null,
      yield_pump_depth: spine.design.yield.pumpDepthM ?? null,
      methods: (spine.design.yield.methods || []).map((m) => [m.label, m.transmissivity]),
      design_flags: spine.design.flags.map((f) => [f.level, f.code]),
      cost_direct: spine.costing.directCost,
      cost_total: spine.costing.totalCost,
      cost_price: spine.costing.price,
      cost_per_metre: spine.costing.costPerMetre,
      by_stage: spine.costing.byStage.map((r) => [r.label, r.amount, r.share]),
      quantity_basis: spine.costing.quantityBasis,
      quality_verdict: spine.quality.verdict,
      quality_health: spine.quality.healthExceedances,
      quality_aesthetic: spine.quality.aestheticExceedances,
      quality_ratios: spine.quality.rows.map(
        (r) => [r.parameter, r.ratio, r.limitName, r.limitKind]),
      piper_percent: spine.quality.piper.percent,
      edited_screens: spineEdited.design.screens.map((s) => [s.top, s.base]),
      edited_cost_direct: spineEdited.costing.directCost,
      edited: spineEdited.edited,
    };

    // the portfolio view, over the same summaries the reference uses
    const summaries = [
      { community: 'Rokel', district: 'Port Loko', easting: 235000.0,
        northing: 963000.0, status: 'sited' },
      { community: 'Dr. Timbo', district: 'Western Area Rural',
        easting: 778000.0, northing: 946000.0, utm_zone: 28,
        status: 'Completed - successful', total_depth_m: 45.0,
        safe_yield_m3_per_h: 2.34, water_verdict: 'pass',
        verdict_schema: 2, cost_per_meter_usd: 133.0 },
      { community: 'Kuntoloh', district: 'Western Area Rural',
        status: 'Completed - dry', total_depth_m: 52.0,
        water_verdict: 'aesthetic', cost_per_meter_usd: 151.0 },
    ];
    // the drill-target scorecard, over the real Rokel soundings
    const rokelSoundings = C.readVesSheets(vesSheets, 'rokel_ves.xlsx');
    const rokelInterps = rokelSoundings.map((s) => {
      const inv = C.invertSounding(s);
      return C.interpretModel(s, inv.model);
    });
    out.siting = C.assessSiting(rokelInterps).map((r) => ({
      id: r.sounding_id, rank: r.rank, suitability: r.suitability,
      grade: r.grade, components: r.components, rationale: r.rationale,
    }));

    out.geo = [[8.4657, -13.2317], [8.7043, -11.4084], [7.9560, -11.7400]]
      .map(([lat, lon]) => {
        const utm = C.geographicToUtm(lat, lon);
        return { lat, lon, easting: utm.easting, northing: utm.northing, zone: utm.zone };
      });

    out.distance = [
      [[8.50, -12.01], [8.50, -11.99]],
      [[8.4657, -13.2317], [7.9647, -11.7383]],
      [[8.0, -12.0], [8.0, -12.0]],
    ].map(([a, b]) => ({
      a, b, metres: C.geodesicDistanceM(a[0], a[1], b[0], b[1]),
    }));

    out.statuses = {};
    ['Successful', 'Completed - dry', 'incomplete', 'not completed',
      'unproductive', 'non-productive', 'low productivity', 'in progress',
      'Sited', 'visited', 'qwerty'].forEach((raw) => {
      out.statuses[raw] = C.classifyStatus({ status: raw });
    });

    out.units = [
      [5.0, 'ug/L', 'mg/L'], [5.0, 'ppb', 'mg/L'], [0.5, 'g/L', 'mg/L'],
      [0.185, 'mS/cm', 'uS/cm'], [2.0, 'CFU/mL', 'CFU/100 mL'],
      [2.0, 'L/s', 'm3/h'], [120.0, 'L/min', 'm3/h'], [2.0, 'h', 'min'],
      [5.0, 'gpm', 'm3/h'], [5.0, 'squiggles', 'mg/L'], [5.0, 'mg/L', 'NTU'],
    ].map(([value, from, to]) => ({
      value, from, to, result: C.convertUnit(value, from, to),
    }));

    const panel = [
      { parameter: 'E. coli', value: 0.0, unit: 'CFU/100 mL' },
      { parameter: 'Arsenic', value: 0.001, unit: 'mg/L' },
      { parameter: 'Fluoride', value: 0.3, unit: 'mg/L' },
      { parameter: 'Nitrate (as NO3)', value: 5.0, unit: 'mg/L' },
    ];
    const wq = (...results) => ({ site: { community: 'Ref' }, results, flags: [] });
    const verdictCases = {
      empty: wq(),
      pass: wq(...panel, { parameter: 'pH', value: 7.2, unit: 'pH units' }),
      aesthetic: wq(...panel, { parameter: 'Iron', value: 0.5, unit: 'mg/L' }),
      national_fail: wq(...panel,
        { parameter: 'Aluminium', value: 0.5, unit: 'mg/L' }),
      health_fail: wq(...panel, { parameter: 'Arsenic', value: 0.5, unit: 'mg/L' }),
      micrograms: wq(...panel, { parameter: 'Lead', value: 5.0, unit: 'ug/L' }),
      bad_unit: wq(...panel, { parameter: 'Iron', value: 0.1, unit: 'wibbles' }),
      shallow_dl: wq(...panel, { parameter: 'Cadmium', value: null, unit: 'mg/L',
        detection_limit: 0.05, below_detection: true }),
      unknown_parameter: wq(...panel,
        { parameter: 'Glyphosate', value: 0.4, unit: 'mg/L' }),
    };
    out.verdicts = {};
    Object.keys(verdictCases).forEach((name) => {
      const a = C.assessSample(verdictCases[name]);
      out.verdicts[name] = {
        state: a.verdict_state,
        statuses: a.rows.map((r) => r.status),
        reasons: a.rows.map((r) => r.reason),
        converted: a.rows.map((r) => r.value_in_guideline_unit),
        uncertainties: a.uncertainties,
        missing_essential: a.missing_essential,
        verdict: a.verdict,
      };
    });

    out.spine_quality = C.spineQuality(C.assessSample(wq(
      { parameter: 'Arsenic', value: 5.0, unit: 'ug/L' },
      { parameter: 'Electrical conductivity', value: 3.0, unit: 'mS/cm' },
      { parameter: 'Nitrate (as NO3)', value: 0.1, unit: 'g/L' },
      { parameter: 'Iron', value: 0.1, unit: 'wibbles' },
      { parameter: 'E. coli', value: 0.0, unit: 'CFU/100 mL' },
    ))).rows.map((row) => ({
      parameter: row.parameter, value: row.value, unit: row.unit,
      valueInGuidelineUnit: row.valueInGuidelineUnit,
      guidelineUnit: row.guidelineUnit, status: row.status,
      evaluable: row.evaluable, limitMax: row.limitMax, ratio: row.ratio,
    }));

    out.rounding = [[0.15, 1], [14.05, 1], [2.675, 2], [0.5, 0], [1.5, 0],
      [2.5, 0], [-0.15, 1], [2.34, 2], [2.345, 2], [0.125, 2], [-2.5, 0],
      [45.05, 1], [150.5, 0]]
      .map(([value, digits]) => ({ value, digits, rounded: C.pyRound(value, digits) }));
    out.formatting = [1e6, 1e15, 999999.6, 1e5, 1e7, 1234567, 0.0001, 0.00001,
      2.93, 0.0, 0.005, 1e-7].map((value) => ({ value, text: C.formatG(value) }));

    out.portfolio = {
      rows: C.portfolioRows(summaries),
      points: C.portfolioPoints(summaries).map((p) => [p.label, p.lat, p.lon, p.status]),
      stats: C.portfolioStats(summaries),
      detail: C.portfolioSiteDetail(summaries[1]),
      one_pager: C.portfolioOnePager(summaries[1]),
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

  // --- Depth Spine ---
  const spineExact = ['lithology', 'strikes', 'segments', 'screen_limits',
    'screens', 'methods', 'design_flags', 'by_stage', 'quantity_basis',
    'quality_verdict', 'quality_health', 'quality_aesthetic', 'quality_ratios',
    'piper_percent', 'yield_range', 'edited_screens', 'edited', 'levels'];
  for (const key of spineExact) {
    check(`spine: ${key}`,
      JSON.stringify(parsed.spine[key]) === JSON.stringify(R.spine[key]),
      `js ${JSON.stringify(parsed.spine[key])}\n     py ${JSON.stringify(R.spine[key])}`);
  }
  for (const key of ['total_depth', 'domain', 'total_screen_m', 'screen_share',
    'yield_safe', 'yield_pump_depth', 'cost_direct', 'cost_total', 'cost_price',
    'cost_per_metre', 'edited_cost_direct']) {
    check(`spine: ${key}`, close(parsed.spine[key], R.spine[key], 1e-4),
      `js ${parsed.spine[key]} vs py ${R.spine[key]}`);
  }

  // --- Drill-target suitability ---
  check('siting: same points ranked the same way',
    JSON.stringify(parsed.siting.map((s) => [s.id, s.rank, s.grade])) ===
    JSON.stringify(R.siting.map((s) => [s.id, s.rank, s.grade])),
    JSON.stringify(parsed.siting.map((s) => [s.id, s.rank, s.grade])));
  parsed.siting.forEach((s, i) => {
    check(`siting[${i}] ${s.id}: suitability`,
      close(s.suitability, R.siting[i].suitability, 1e-6),
      `js ${s.suitability} vs py ${R.siting[i].suitability}`);
    // the resistivity-fit component is a geometric mean over the inverted
    // model, so it carries the same BLAS-dependent last digits the inversion
    // does; 1e-6 relative is the tolerance the reference file itself uses
    check(`siting[${i}] ${s.id}: components`,
      Object.keys(s.components).every(
        (k) => close(s.components[k], R.siting[i].components[k], 1e-6)),
      `${JSON.stringify(s.components)}\n     ${JSON.stringify(R.siting[i].components)}`);
    check(`siting[${i}] ${s.id}: rationale`, s.rationale === R.siting[i].rationale,
      `js ${s.rationale}\n     py ${R.siting[i].rationale}`);
  });

  // --- Geographic -> UTM ---
  parsed.geo.forEach((g, i) => {
    check(`geo[${i}]: easting/northing/zone`,
      close(g.easting, R.geo[i].easting, 1e-9) &&
      close(g.northing, R.geo[i].northing, 1e-9) && g.zone === R.geo[i].zone,
      `js ${g.easting}, ${g.northing}, ${g.zone} vs py ${R.geo[i].easting}, ` +
      `${R.geo[i].northing}, ${R.geo[i].zone}`);
  });

  // --- Ground distance ---
  // Both engines have to agree on the same ellipsoidal answer, not merely on
  // a close one: a haversine port against a Vincenty Python would be 2.6 m
  // out on the zone-crossing pair and 89 m out over Freetown to Bo.
  parsed.distance.forEach((d, i) => {
    check(`distance[${i}]: metres`, close(d.metres, R.distance[i].metres, 1e-9),
      `js ${d.metres} vs py ${R.distance[i].metres}`);
  });

  // --- Free-text borehole status ---
  check('statuses', JSON.stringify(parsed.statuses) === JSON.stringify(R.statuses),
    `js ${JSON.stringify(parsed.statuses)}\n     py ${JSON.stringify(R.statuses)}`);

  // --- Unit conversion ---
  parsed.units.forEach((u, i) => {
    const py = R.units[i].result;
    const same = (u.result === null || py === null)
      ? u.result === py : close(u.result, py, 1e-9);
    check(`units[${i}] ${u.value} ${u.from} -> ${u.to}`, same,
      `js ${u.result} vs py ${py}`);
  });

  // --- Water quality verdict ---
  Object.keys(R.verdicts).forEach((name) => {
    const js = parsed.verdicts[name], py = R.verdicts[name];
    check(`verdict ${name}: state`, js.state === py.state,
      `js ${js.state} vs py ${py.state}`);
    for (const key of ['statuses', 'reasons', 'uncertainties',
      'missing_essential', 'verdict']) {
      check(`verdict ${name}: ${key}`,
        JSON.stringify(js[key]) === JSON.stringify(py[key]),
        `js ${JSON.stringify(js[key])}\n     py ${JSON.stringify(py[key])}`);
    }
    check(`verdict ${name}: converted`,
      js.converted.length === py.converted.length &&
      js.converted.every((v, i) => (v === null || py.converted[i] === null)
        ? v === py.converted[i] : close(v, py.converted[i], 1e-9)),
      `js ${JSON.stringify(js.converted)}\n     py ${JSON.stringify(py.converted)}`);
  });

  // --- The Depth Spine's guideline chart, on non-guideline units ---
  // The limit is in the guideline's unit, so the value has to be too. The
  // bundled sample reports everything in the guideline unit, which is why
  // this needed its own case.
  parsed.spine_quality.forEach((row, i) => {
    const py = R.spine_quality[i];
    check(`spine_quality[${i}] ${row.parameter}: status/evaluable`,
      row.status === py.status && row.evaluable === py.evaluable,
      `js ${row.status}/${row.evaluable} vs py ${py.status}/${py.evaluable}`);
    check(`spine_quality[${i}] ${row.parameter}: converted value and ratio`,
      close(row.valueInGuidelineUnit, py.valueInGuidelineUnit, 1e-9) &&
      close(row.ratio, py.ratio, 1e-9) &&
      row.guidelineUnit === py.guidelineUnit,
      `js ${row.valueInGuidelineUnit} ${row.guidelineUnit} ratio ${row.ratio}` +
      ` vs py ${py.valueInGuidelineUnit} ${py.guidelineUnit} ratio ${py.ratio}`);
  });

  // --- round() and %g, which the two languages get wrong differently ---
  parsed.rounding.forEach((r, i) => {
    check(`round(${r.value}, ${r.digits})`, close(r.rounded, R.rounding[i].rounded, 1e-12),
      `js ${r.rounded} vs py ${R.rounding[i].rounded}`);
  });
  parsed.formatting.forEach((f, i) => {
    check(`%g of ${f.value}`, f.text === R.formatting[i].text,
      `js ${f.text} vs py ${R.formatting[i].text}`);
  });

  // --- Portfolio ---
  for (const key of ['rows', 'stats', 'detail', 'one_pager']) {
    check(`portfolio: ${key}`,
      JSON.stringify(parsed.portfolio[key]) === JSON.stringify(R.portfolio[key]),
      `js ${JSON.stringify(parsed.portfolio[key])}\n     py ${JSON.stringify(R.portfolio[key])}`);
  }
  check('portfolio: points',
    parsed.portfolio.points.length === R.portfolio.points.length &&
    parsed.portfolio.points.every((p, i) => p[0] === R.portfolio.points[i][0] &&
      close(p[1], R.portfolio.points[i][1], 1e-9) &&
      close(p[2], R.portfolio.points[i][2], 1e-9) &&
      p[3] === R.portfolio.points[i][3]),
    `js ${JSON.stringify(parsed.portfolio.points)}\n     py ${JSON.stringify(R.portfolio.points)}`);

  // --- The unruled PDF field sheet ---
  // Both readers find this table from word positions rather than from ruling
  // lines, which is the case where the two implementations could most easily
  // drift apart. They read the same bytes, carried in the reference file.
  const pdf = await page.evaluate(async (b64) => {
    try {
      const doc = await GWT.core.extractPdfText(
        GWT.support.base64ToBytes(b64), 'ves_sheet.pdf');
      return {
        kind: doc.document_kind,
        header: doc.header.map((f) => [f.name, f.value]),
        tables: doc.tables.map((t) => ({ columns: t.columns, rows: t.rows })),
        uncertain: doc.uncertain_cells.length,
      };
    } catch (e) { return { error: e.message }; }
  }, R.pdf_sheet.b64);

  check('pdf sheet: the same document kind',
    pdf.kind === R.pdf_sheet.kind, `js ${pdf.kind || pdf.error} py ${R.pdf_sheet.kind}`);
  check('pdf sheet: the same header fields',
    JSON.stringify(pdf.header) === JSON.stringify(R.pdf_sheet.header),
    `js ${JSON.stringify(pdf.header)}\n     py ${JSON.stringify(R.pdf_sheet.header)}`);
  check('pdf sheet: the same table, found without ruling lines',
    JSON.stringify(pdf.tables) === JSON.stringify(R.pdf_sheet.tables),
    `js ${JSON.stringify(pdf.tables)}\n     py ${JSON.stringify(R.pdf_sheet.tables)}`);
  check('pdf sheet: the same cells held back for review',
    pdf.uncertain === R.pdf_sheet.uncertain,
    `js ${pdf.uncertain} py ${R.pdf_sheet.uncertain}`);

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n     '));
}, {});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

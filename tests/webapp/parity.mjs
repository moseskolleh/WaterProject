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
  await page.waitForFunction(() => window.GWT && window.GWT.core && window.GWT.data &&
    window.GWT.docx);

  const parsed = await page.evaluate(async (R_STREAMLIT_YAML) => {
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
      // workstream 3: what the yield is worth, and why each method was or
      // was not adopted
      source: analysis.transmissivity_source,
      qualifies: C.adoptedFit(analysis).qualifies,
      disqualified: Object.keys(analysis.disqualified).sort(),
      casing_storage_min: analysis.casing_storage_min,
      u_check: analysis.cooper_jacob ? analysis.cooper_jacob.u_check : null,
      rec_intercept: analysis.recovery ? analysis.recovery.intercept_m : null,
      rec_intercept_fraction: analysis.recovery ? analysis.recovery.intercept_fraction : null,
      rec_pumping_time: analysis.recovery ? analysis.recovery.pumping_time_min : null,
      theis_S: analysis.theis ? analysis.theis.storativity : null,
      confidence: analysis.yield_recommendation.confidence,
      confidence_reasons: analysis.yield_recommendation.confidence_reasons.slice(),
      confidence_text: analysis.yield_recommendation.confidence_text,
      specific_capacity: analysis.yield_recommendation.specific_capacity_m3hr_per_m,
      specific_capacity_basis: analysis.yield_recommendation.specific_capacity_basis,
      pump_depth_basis: analysis.yield_recommendation.pump_depth_basis,
      deepest_level: analysis.yield_recommendation.deepest_pumping_level_m,
      basis: analysis.yield_recommendation.basis,
      type_text: C.testTypeText(test.test_type),
    };

    // The step test with the discharges an analyst would type in: the first
    // step ends above static and gets no drawdown fit, the recovery is read
    // against an equivalent time, and the two-step Hantush-Bierschenk line
    // says it is exact by construction.
    const stepQ = C.pumpingFromGrid(stepSheets[0].rows, 'kuntolo_step_test.xlsx');
    [1.5, 2.2, 3.0].forEach((q, i) => { stepQ.steps[i].discharge_m3_per_h = q; });
    const stepAnalysis = C.analysePumpingTest(stepQ);
    const stepRec = stepAnalysis.yield_recommendation;
    out.step_analysis = {
      T: stepAnalysis.transmissivity_m2_per_day,
      source: stepAnalysis.transmissivity_source,
      qualifies: C.adoptedFit(stepAnalysis).qualifies,
      cj: stepAnalysis.cooper_jacob ? stepAnalysis.cooper_jacob.transmissivity_m2_per_day : null,
      theis: stepAnalysis.theis ? stepAnalysis.theis.transmissivity_m2_per_day : null,
      rec: stepAnalysis.recovery ? stepAnalysis.recovery.transmissivity_m2_per_day : null,
      rec_pumping_time: stepAnalysis.recovery ? stepAnalysis.recovery.pumping_time_min : null,
      rec_equivalent: stepAnalysis.recovery ? stepAnalysis.recovery.equivalent_time : null,
      B: stepAnalysis.step_test ? stepAnalysis.step_test.aquifer_loss_B : null,
      C: stepAnalysis.step_test ? stepAnalysis.step_test.well_loss_C : null,
      two_point: stepAnalysis.step_test ? stepAnalysis.step_test.two_point : null,
      safe: stepRec.safe_yield_m3_per_h,
      pump_depth: stepRec.pump_installation_depth_m,
      confidence: stepRec.confidence,
      confidence_reasons: stepRec.confidence_reasons.slice(),
      pump_depth_basis: stepRec.pump_depth_basis,
      specific_capacity_basis: stepRec.specific_capacity_basis,
      flags: stepAnalysis.flags.map((f) => [f.level, f.code]),
      type_text: C.testTypeText(stepQ.test_type),
      step_numbers: stepAnalysis.step_test
        ? stepAnalysis.step_test.steps.map((s) => s.step) : null,
    };

    const assessed = C.assessSample(sample);
    out.assessed = {
      verdict: assessed.verdict,
      health: assessed.health_exceedances.map((r) => r.parameter),
      wqi: assessed.wqi && assessed.wqi.value,
      corros: assessed.corrosivity.classification,
      corros_verdict: assessed.corrosivity.verdict,
      corros_materials: assessed.corrosivity.materials_note,
      national: assessed.national_exceedances.map((r) => r.parameter),
      ionic: assessed.ionic && assessed.ionic.error_percent,
    };

    const design = C.designBorehole({
      log: log, staticWaterLevelM: test.static_water_level_m, pumpIntakeM: 52,
    });
    out.design = {
      depth: design.total_depth_m, screens: design.screens.map((s) => [s.top_m, s.bottom_m]),
      gravel: design.gravel_pack, screen_len: design.total_screen_length_m,
      // workstream 4: the log's own words decide the design
      backfill: design.backfill,
      annular_fill: design.annular_fill,
      annulus_mm: design.annulus_mm,
      bore_in: design.borehole_diameter_in,
      as_built: design.as_built,
      construction_note: design.construction_note,
      pump_intake: design.pump_intake_m,
      basis: design.design_basis.slice(),
      flags: design.flags.map((f) => [f.level, f.code]),
      summary_rows: C.designSummaryRows(design).map((r) => [r[0], r[1]]),
      gravel_interval: C.inputsFromDesign(design).gravel_interval_m,
      grout: log.grouting_depth_m,
      installed_screens: log.installed_screens_m.map((s) => [s[0], s[1]]),
      bands: C.lithologyBands(log.intervals).map((b) => [b.top_m, b.bottom_m, b.label]),
      // the seal the drawing shows is the seal the BoQ prices
      seal: design.sanitary_seal,
      cement_bags: C.inputsFromDesign(design).cement_bags,
    };

    const manual = C.resolveCostingInputs(C.costingInputs({ total_depth_m: 60.0, sanitary_seal_m: 30.0 }));
    out.costing_manual = {
      cement_bags: manual.inputs.cement_bags,
      seal_note: manual.assumptions.find((n) => n.indexOf('grout seal') >= 0),
    };

    // The cost summary table a contract is signed on, with and without VAT.
    const costInputs = C.resolveCostingInputs(
      C.costingInputs({ total_depth_m: 60.0 })).inputs;
    out.cost_summary = {
      no_vat: C.costSummaryRows(C.estimateBoreholeCost(costInputs)),
      vat: C.costSummaryRows(
        C.estimateBoreholeCost(costInputs, null, { vatPercent: 15.0 })),
    };

    // The real bytes a Streamlit save produces, parsed by the browser's own
    // YAML reader. Both apps advertise that they read each other's projects.
    let streamlitRead = null, streamlitError = null;
    try { streamlitRead = S.parseYaml(R_STREAMLIT_YAML); }
    catch (e) { streamlitError = String(e && e.message || e); }
    out.streamlit_project_file = {
      error: streamlitError,
      summary: streamlitRead ? streamlitRead.summary : null,
      keys: streamlitRead ? Object.keys(streamlitRead).sort() : null,
    };

    const items = C.loadChecklists();
    const migrated = {};
    const prefixed = C.migrateChecklistResponses({
      'procurement-01': 'chk_procurement-01', 'drilling-03': 'rmk_drilling-03',
      [items[10].item_id]: 'chk_' + items[10].item_id, 'nowhere-99': 'chk_nowhere-99',
    }, items);
    // the Python keys carry a widget prefix; the browser keys the item alone
    Object.keys(prefixed).forEach((k) => { migrated[prefixed[k].slice(0, 4) + k] = prefixed[k]; });
    out.checklists = {
      ids: items.map((i) => [i.item_id, i.legacy_id, i.checklist, i.section, i.critical]),
      legacy: C.legacyItemIds(items),
      migrated: migrated,
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
    const rokelInversions = rokelSoundings.map((s) => C.invertSounding(s));
    const rokelInterps = rokelSoundings.map((s, k) =>
      C.interpretModel(s, rokelInversions[k].model));
    out.siting = C.assessSiting(rokelInterps).map((r) => ({
      id: r.sounding_id, rank: r.rank, suitability: r.suitability,
      grade: r.grade, components: r.components, rationale: r.rationale,
    }));
    // the interpretation itself and the preference table printed from it
    out.interpretations = rokelInterps.map((i) => ({
      id: i.sounding_id, water_zones: i.water_zones,
      max_drilling_depth_m: i.max_drilling_depth_m,
      investigation_depth_m: i.investigation_depth_m,
      max_spacing_m: i.max_spacing_m,
      basement_not_resolved: i.basement_not_resolved,
      confidence: i.confidence, fit_quality: i.fit_quality,
      flags: i.flags.map((f) => [f.level, f.code, f.message]),
      narrative: i.narrative,
    }));
    out.preference = C.drillingPreferenceTable(rokelInterps);

    // The interpretation and report prose over the cases make_reference.py
    // builds as VES_CASES, VES_SHEETS and MODELS_TRIED_CASES: a zone past the
    // depth of investigation, one wholly below it, a margin cut back to it, a
    // dropped last reading, poorly resolved boundaries, a near-tie, an exact
    // tie, two sheets with one sounding number and a Wenner sheet with an MN
    // column. The inputs are written out twice on purpose; they are the
    // contract.
    const SPACINGS = [1, 2, 5, 10, 20, 40, 80];
    const caseInterp = (sid, rho, h, err, hFactor, ab2, rhoApp) => {
      const spacing = ab2 || SPACINGS;
      const extra = { fit_error_percent: err, sounding_id: sid };
      if (hFactor) extra.h_uncertainty_factor = hFactor;
      const sounding = { site: {}, sounding_id: sid, ab2: spacing,
        mn: spacing.map(() => NaN), rho_app: rhoApp || spacing.map(() => 100),
        array_type: 'schlumberger', flags: [] };
      return C.interpretModel(sounding, C.layeredModel(rho, h, extra));
    };
    const vesCases = [
      ['zone past doi', [1000, 100, 5000], [5, 60], 8.0, null, null, null],
      ['zone below doi', [1000, 1500, 100, 5000], [10, 40, 20], 6.0, null,
        [1, 2, 5, 10, 20, 40, 60], null],
      ['margin past doi', [1000, 100, 5000], [5, 33], 5.0, null, null, null],
      ['last reading dropped', [1000, 100], [8], 5.0, null, null,
        [300, 250, 200, 150, 120, 110, 0]],
      ['poorly resolved', [1100, 1600, 47], [1.0, 7.0], 13.3, [3.7, 1.4], null, null],
      ['two poorly resolved', [1100, 1600, 300, 47], [1, 2, 7], 5.0, [3.7, 2.5, 1.1],
        null, null],
      ['thin resistive at 2.5', [1000, 5000, 100], [2.5, 3], 5.0, null, null, null],
    ];
    const cases = {};
    vesCases.forEach(([name, rho, h, err, hFactor, ab2, rhoApp]) => {
      const i = caseInterp(name, rho, h, err, hFactor, ab2, rhoApp);
      const suit = C.assessSiting([i])[0];
      cases[name] = {
        water_zones: i.water_zones, depth_to_basement_m: i.depth_to_basement_m,
        investigation_depth_m: i.investigation_depth_m,
        max_drilling_depth_m: i.max_drilling_depth_m,
        basement_not_resolved: i.basement_not_resolved,
        drilling_depth_capped: i.drilling_depth_capped,
        drilling_depth_text: C.drillingDepthText(i),
        flags: i.flags.map((f) => [f.level, f.code, f.message]),
        narrative: i.narrative, suitability: suit.suitability, rationale: suit.rationale,
      };
    });
    const ranking = (interps) => {
      const suit = C.assessSiting(interps);
      return {
        tie: C.rankingTie(suit), verdict: C.suitabilityVerdict(suit),
        preference: C.drillingPreferenceTable(interps).map((r) =>
          [r['VES Point'], r.Ranking, r['Possible Water Zones (m)']]),
      };
    };
    const vesSheet = (number, array, header, rows) => [
      ['VES FIELD DATA', null, null, null],
      ['Client', 'Ref Client', 'Community', 'Refville'],
      ['Project', 'Geophysical Survey', 'Sounding Number', number],
      ['District', 'Bo', 'Date', '1 Jan 2020'],
      ['Array', array, 'Instrument', 'ABEM'],
      [null, null, null, null],
      header,
    ].concat(rows.map((r, k) => [k + 1].concat(r)));
    const withMn = ['No.', 'AB/2 (m)', 'MN (m)', 'Apparent Resistivity (ohm-m)'];
    const sheets = C.readVesSheets([
      { name: 'W', rows: vesSheet('W 1', 'Wenner', withMn, [[1.5, 1, 300], [3, 1, 280],
        [6, 1, 200], [6, 4, 190], [15, 4, 120], [30, 4, 90]]) },
      { name: 'S3', rows: vesSheet('S 3', 'Schlumberger', withMn, [[10, 1, 400],
        [20, 1, 250], [40, 1, 150], [40, 4, 148], [40, 10, 78], [60, 10, 60]]) },
      { name: 'S3 copy', rows: vesSheet('S 3', 'Schlumberger', withMn, [[10, 1, 410],
        [20, 1, 260], [40, 1, 140], [60, 10, 70]]) },
    ], 'x.xlsx');
    const trialCase = (trials, err) => ({ trials, fit_error_percent: err,
      model: C.layeredModel([300, 100, 150], [3, 30]) });
    const withFactor = Object.assign({}, C.defaultConfig().ves,
      { depth_of_investigation_factor: 0.4 });
    out.ves_text = {
      cases,
      near_tie: ranking([caseInterp('VES 1', [1000, 100, 5000], [5, 20], 9.0),
        caseInterp('VES 2', [1000, 100, 5000], [5, 22], 9.0)]),
      equal: ranking([caseInterp('VES 2', [1000, 100, 5000], [5, 20], 9.0),
        caseInterp('VES 1', [1000, 100, 5000], [5, 20], 9.0)]),
      clear: ranking([caseInterp('VES 1', [300, 1500], [30], 5.0),
        caseInterp('VES 2', [1000, 100, 5000], [5, 20], 5.0)]),
      same_id: ranking([caseInterp('VES 1', [300, 1500], [30], 5.0),
        caseInterp('VES 1', [1000, 100, 5000], [5, 20], 5.0)]),
      rokel_verdict: C.suitabilityVerdict(C.assessSiting(rokelInterps)),
      models_tried: rokelInversions.map((inv) => C.modelsTriedText(inv)).concat([
        trialCase([[2, 4.2], [3, 0.01]], 0.01),
        trialCase([[2, 8.0], [3, 3.5], [4, 2.0]], 3.5),
        trialCase([[2, 15.4], [3, 8.0]], 8.0),
        trialCase([[2, 15.4], [3, 13.3], [4, 13.1]], 13.3),
      ].map((inv) => C.modelsTriedText(inv))),
      poorly_resolved: rokelInversions.map((inv) => C.poorlyResolvedText(inv.model)),
      doi_text: [
        C.depthOfInvestigationText('schlumberger', 80, 40),
        C.depthOfInvestigationText('wenner', 60, 30),
        C.depthOfInvestigationText('wenner', 60, 24, withFactor),
      ],
      sheets: sheets.map((s) => [s.sounding_id, s.array_type,
        s.flags.map((f) => [f.level, f.code, f.message])]),
    };

    // a siting survey with no borehole yet: the design comes from the
    // interpretation alone, which is where the degenerate zone used to put
    // 48 m of screen in an 80 m hole
    const vesOnly = C.designBorehole({ interpretation: rokelInterps[0] });
    out.ves_only_design = {
      depth: vesOnly.total_depth_m,
      screens: vesOnly.screens.map((x) => [x.top_m, x.bottom_m]),
      screen_len: vesOnly.total_screen_length_m,
      basis: vesOnly.design_basis,
    };

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
      // Aluminium used to be this case, on a WHO health value of 0.9 mg/L
      // that WHO does not set. Total coliforms above zero is the real one.
      national_fail: wq(...panel,
        { parameter: 'Total coliforms', value: 5.0, unit: 'CFU/100 mL' }),
      // a count the laboratory saw and did not put a number to, and a
      // ">100" inside its limit: both used to read as "not measured"
      unquantified_count: wq(...panel, { parameter: 'Total coliforms',
        value: null, unit: 'CFU/100 mL', greater_than: 0 }),
      greater_than_inside_limit: wq(...panel, { parameter: 'Sulfate',
        value: null, unit: 'mg/L', greater_than: 100 }),
      health_fail: wq(...panel, { parameter: 'Arsenic', value: 0.5, unit: 'mg/L' }),
      micrograms: wq(...panel, { parameter: 'Lead', value: 5.0, unit: 'ug/L' }),
      bad_unit: wq(...panel, { parameter: 'Iron', value: 0.1, unit: 'wibbles' }),
      shallow_dl: wq(...panel, { parameter: 'Cadmium', value: null, unit: 'mg/L',
        detection_limit: 0.05, below_detection: true }),
      unknown_parameter: wq(...panel,
        { parameter: 'Glyphosate', value: 0.4, unit: 'mg/L' }),
      // the charge balance cannot be computed, and used to say nothing
      no_ionic_balance: wq({ parameter: 'Calcium', value: 40.0, unit: 'mg/L' }),
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
        flags: a.flags.map((f) => [f.level, f.code, f.message]),
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

    // the certification gate, over a project missing one thing at a time
    const located = { community: "Dr. Timbo's", district: 'Western Area Rural',
      easting: 778000.0, northing: 946000.0, utm_zone: 28 };
    const fullProject = {
      site: located, drilling_log: log, pump_analysis: analysis,
      wq_assessment: assessed, borehole_design: design,
    };
    const gateCases = {
      full: [fullProject, {}],
      empty: [{}, {}],
      no_site: [Object.assign({}, fullProject, { site: { community: 'Nowhere' } }), {}],
      no_quality: [Object.assign({}, fullProject, { wq_assessment: null }), {}],
      overridden: [Object.assign({}, fullProject, { wq_assessment: null }), {
        water_quality_panel: { reason: 'lab result awaited', by: 'M. K.' },
        water_quality_evaluable: { reason: 'lab result awaited', by: 'M. K.' },
      }],
      // The demonstration paths, which the two engines have to read the same
      // way: a bundled file whose readings were invented, and a bundled file
      // faithfully transcribed from a real survey. Both hold the report back;
      // only the first says nothing was measured.
      synthetic_source: [Object.assign({}, fullProject, {
        sources: { wq: { sample: 'dr_timbo/dr_timbo_water_quality.xlsx' } },
      }), {}],
      bundled_source: [Object.assign({}, fullProject, {
        sources: { ves: { name: 'rokel_ves.xlsx', b64: 'x',
          sample: 'rokel/rokel_ves.xlsx' } },
      }), {}],
      // A bundled file whose measurements are real but whose blank columns
      // were filled in illustratively. Not blocking - it is a stated
      // assumption, which is the other half of the gate's output.
      reconstructed_source: [Object.assign({}, fullProject, {
        sources: { log: { sample: 'dr_timbo/dr_timbo_drilling_log.xlsx' } },
      }), {}],
      // The same synthetic workbook opened off disk by a script, with no
      // picker marker on it. Invented readings are invented whoever opened
      // the file, so this still fails.
      synthetic_by_name: [Object.assign({}, fullProject, {
        sources: { wq: { name: 'dr_timbo_water_quality.xlsx' } },
      }), {}],
      // But a faithfully transcribed example opened the same way is not a
      // demonstration: a script publishing the Rokel survey under the Rokel
      // name is reporting exactly what it says it is.
      transcribed_by_name: [Object.assign({}, fullProject, {
        sources: { ves: { name: 'rokel_ves.xlsx' } },
      }), {}],
      // An upload of the analyst's own file is not a demonstration, however
      // it is named - the check must not fire on everything with a source.
      own_upload: [Object.assign({}, fullProject, {
        sources: { log: { name: 'kambia_drilling_log.xlsx', b64: 'x' } },
      }), {}],
      // The one case an override is for: publishing the worked example
      // itself, with the reason on the cover.
      demonstration_override: [Object.assign({}, fullProject, {
        sources: { wq: { sample: 'dr_timbo/dr_timbo_water_quality.xlsx' } },
      }), { field_data: { reason: 'published as a worked example', by: 'M. K.' } }],
    };
    out.readiness = {};
    Object.keys(gateCases).forEach((name) => {
      const [state, over] = gateCases[name];
      out.readiness[name] = {};
      ['completion', 'handover', 'quality', 'pumping'].forEach((report) => {
        const r = C.assessReadiness(state, report, over);
        out.readiness[name][report] = {
          state: r.state, summary: r.summary,
          requirements: r.requirements.map((q) => [q.key, q.state, q.detail,
            q.override_reason, q.override_by]),
          assumptions: r.assumptions,
        };
      });
    });

    // The handover works list. Both engines build it from the same records
    // and it is what an interim payment is argued from, so the two have to
    // word it identically; nothing compared them until now.
    out.handover_works = {
      full: window.GWT.docx.handoverWorks({
        log: log, design: design, analysis: analysis, assessment: assessed,
        interpretations: [],
      }),
      sited: window.GWT.docx.handoverWorks({
        log: log, design: design, analysis: analysis, assessment: assessed,
        interpretations: [{ sounding_id: 'VES 1' }],
      }),
      bare: window.GWT.docx.handoverWorks({ log: {}, design: null }),
      no_depth: window.GWT.docx.handoverWorks({
        log: { drilling_method: 'Air rotary (DTH hammer)' }, design: null,
      }),
    };

    out.qr = [];
    ["SL-WAR-8FEEVKQ-T",
      "BOREHOLE SL-WAR-8FEEVKQ-T\nDr. Timbo's (Western Area Rural)\n" +
      "8.48310 N, 13.22940 W\n62.0 m deep, 1.85 m3/h",
      "Kailahun - 10\u00b0 12' 03\" N"].forEach((text) => {
      ['L', 'M', 'Q', 'H'].forEach((ecc) => {
        [null, 0, 5].forEach((mask) => {
          const code = C.qrEncode(text, { ecc, mask });
          out.qr.push({
            text, ecc, mask, version: code.version, size: code.size,
            chosen_mask: code.mask, penalty: C.qrPenalty(code.modules),
            rows: code.modules.map((row) => row.map((c) => (c ? '1' : '0')).join('')),
          });
        });
      });
    });
    out.qr_capacity = [];
    for (let v = 1; v <= C.QR_MAX_VERSION; v++) {
      ['L', 'M', 'Q', 'H'].forEach((ecc) => {
        out.qr_capacity.push({ version: v, ecc, bytes: C.qrCapacityBytes(v, ecc) });
      });
    }

    const sites = [
      { district: 'Western Area Rural', easting: 694912.0, northing: 938150.0, utm_zone: 28 },
      { district: 'Western Area Rural', easting: 694914.0, northing: 938147.0, utm_zone: 28 },
      { district: 'Bo', easting: 790500.0, northing: 875300.0, utm_zone: 28 },
      { district: 'Kailahun', easting: 280400.0, northing: 925600.0, utm_zone: 29 },
      { district: 'Nowhere At All', easting: 694912.0, northing: 938150.0, utm_zone: 28 },
    ];
    out.asset_ids = sites.map((s) => ({
      district: s.district, easting: s.easting, northing: s.northing,
      zone: s.utm_zone, id: C.mintAssetId(s),
    }));
    const timboId = C.mintAssetId(sites[0]);
    out.asset_id_parsing = [timboId, timboId.toLowerCase(),
      timboId.replace(/0/g, 'O'), timboId.replace(/1/g, 'L'), ' ' + timboId + ' ',
      timboId.slice(0, -1) + 'Z', timboId.replace(/-/g, ''),
      'SL-WAR-XXXXXXX-9', 'not an identifier', ''].map((typed) => {
      const v = C.validateAssetId(typed);
      return { typed, parsed: C.parseAssetId(typed), ok: v.ok, reason: v.reason };
    });
    const streams = [
      [{ when: '2020-01-10', kind: 'commissioned', by: 'M. Kolleh' },
        { when: '2023-04-02', kind: 'failure', note: 'rising main parted' }],
      [{ when: '2023-04-02', kind: 'failure', note: 'rising main parted' },
        { when: '2023-05-11', kind: 'repair', note: 'new seals', by: 'A. Bangura',
          photo: 'data:image/jpeg;base64,AAAA' },
        { when: 'not written down', kind: 'inspection' },
        { when: '2099-01-01', kind: 'restored' }],
    ];
    out.asset_events = C.mergeEvents(timboId, streams[0], streams[1]);
    const registryCases = {
      silent: [],
      commissioned: streams[0].slice(0, 1),
      broken: streams[0],
      repaired: streams[0].concat([{ when: '2023-05-11', kind: 'restored' }]),
      sampled: streams[0].slice(0, 1).concat([
        { when: '2023-03-01', kind: 'water_sample' },
        { when: '2024-05-20', kind: 'inspection' }]),
      decommissioned: streams[0].slice(0, 1).concat([
        { when: '2022-08-01', kind: 'decommissioned' }]),
      merged: streams[0].concat(streams[1]),
    };
    const today = '2024-06-01';
    const assets = {};
    Object.keys(registryCases).forEach((name) => {
      assets[name] = {
        asset_id: timboId, community: "Dr. Timbo's",
        district: 'Western Area Rural', easting: 694912.0, northing: 938150.0,
        utm_zone: 28, total_depth_m: 62.0, safe_yield_m3_per_h: 1.85,
        pump_type: 'India Mark II', installed_by: 'WiNGiN',
        events: registryCases[name],
      };
    });
    out.asset_state = {};
    Object.keys(assets).forEach((name) => {
      const st = C.assetState(assets[name], today);
      out.asset_state[name] = {
        function: st.function, label: st.label, since: st.since,
        detail: st.detail, last_inspection: st.last_inspection,
        last_sample: st.last_sample, commissioned: st.commissioned,
        days_out_of_service: st.days_out_of_service,
        due: st.due.map((d) => ({ key: d.key, title: d.title, state: d.state,
          due_on: d.due_on, detail: d.detail })),
        undated_events: st.undated_events,
      };
    });
    out.asset_placard = C.placardLines(assets.commissioned,
      C.assetState(assets.commissioned, today));
    out.asset_qr_payload = C.qrPayload(assets.commissioned);
    out.registry_rows = C.registryRows(Object.keys(assets).map((k) => assets[k]), today);
    out.registry_stats = C.registryStats(Object.keys(assets).map((k) => assets[k]), today);
    out.asset_months = [['2023-08-31', 6], ['2023-12-31', 2], ['2020-02-29', 12],
      ['2023-01-31', 1], ['2023-03-30', 11], ['2024-02-29', 12]]
      .map(([from, months]) => ({ from, months, due: C.addMonths(from, months) }));

    out.seasonal_dates = ['10/05/2018', '25/04/2018', '04/25/2018', '2018-09-14',
      '14 Sept 2018', 'September 2018', 'during the rains', '05/2018', '',
      '31/13/2018', '2018/09/14'].map((text) => {
      const read = C.monthOf(text);
      return { text, month: read.month, note: read.note };
    });
    out.seasonal = {};
    [['august', 8, null], ['may', 5, null], ['september', 9, null],
      ['unknown', null, null], ['wide', 8, 4.5], ['zero', 8, 0.0]]
      .forEach(([label, month, band]) => {
        const r = C.seasonalYield(analysis, null,
          { month, annualRangeM: band });
        out.seasonal[label] = {
          month: r.month, season: r.season, month_note: r.month_note,
          annual_range_m: r.annual_range_m, range_source: r.range_source,
          pending_reason: r.pending_reason,
          design_yield_m3_per_h: r.design_yield_m3_per_h,
          pump_installation_depth_m: r.pump_installation_depth_m,
          dry_season_loss_percent: r.dry_season_loss_percent,
          summary: r.summary,
          scenarios: r.scenarios.map((s) => ({
            key: s.key, title: s.title, decline_m: s.decline_m,
            static_water_level_m: s.static_water_level_m,
            available_drawdown_m: s.available_drawdown_m,
            safe_yield_m3_per_h: s.safe_yield_m3_per_h,
            pump_installation_depth_m: s.pump_installation_depth_m,
            note: s.note,
          })),
        };
      });

    out.wpdx_fields = [['2019-04-02T00:00:00', '12'], ['02/04/2019', 'yes'],
      ['2019', '6 months'], ['', ''], ['not a date', 'seasonal'],
      ['1899-01-01', '14'], ['survey 2024 round 2', 'no']]
      .map(([date, months]) => {
        const [point] = C.parseWpdxRecords([{ lat_deg: 8, lon_deg: -13,
          report_date: date, months_year: months }]);
        return { date, year: point.report_year, months_text: months,
          months: point.months_per_year };
      });
    out.growth_rate = C.intercensalGrowthRate();
    const wp = (functional, year, months) => C.parseWpdxRecords([{
      lat_deg: 8, lon_deg: -13, status_clean: functional ? 'Functional' : 'Non-Functional',
      status_id: functional ? 'Yes' : 'No', water_source_clean: 'Borehole',
      water_tech_clean: 'Hand Pump',
      report_date: year === null ? '' : String(year),
      months_year: months === null ? '' : String(months),
    }])[0];
    const planningPopulation = {
      Bo: 575478.0, Kono: 506100.0, Pujehun: 346461.0, Falaba: 202566.0,
      'Western Area Urban': 1055964.0,
    };
    const planningPoints = {
      Bo: [wp(true, 2024, 12), wp(true, 2010, null), wp(false, 2024, 12)],
      Kono: [wp(true, null, null), wp(true, 2003, 6)],
      Pujehun: [wp(false, 2020, null)],
      'Western Area Urban': [wp(true, 2025, 12), wp(true, 2025, null),
        wp(true, 2019, 4)],
    };
    out.planning = {};
    [['census', 2015, null, null], ['today', 2026, null, null],
      ['slow', 2026, 0.015, null],
      ['districts', 2026, null, { 'Western Area Urban': 0.06, Pujehun: 0.01 }]]
      .forEach(([label, year, rate, rates]) => {
        const r = C.planningRows(planningPopulation, planningPoints,
          { asOfYear: year, rate, rates });
        out.planning[label] = {
          projection: r.projection,
          stats: C.planningStats(r.rows, r.projection),
          rows: r.rows,
        };
      });

    const procContract = (terms) => Object.assign({
      ref: 'WSD/2024/017', contractor: 'WiNGiN', client: 'District Council',
      date: '2024-02-01', retention_percent: 10, retention_cap_percent: 5,
      advance_percent: 0,
      lines: [
        { code: 'MOB', item: 'Mobilisation', unit: 'sum', quantity: 1, rate_usd: 3000 },
        { code: 'DRL-OB', item: 'Drilling, overburden', unit: 'm', quantity: 20, rate_usd: 45 },
        { code: 'DRL-RK', item: 'Drilling, rock', unit: 'm', quantity: 25, rate_usd: 80 },
        { code: 'CAS', item: 'uPVC casing', unit: 'm', quantity: 45, rate_usd: 22 },
      ],
    }, terms || {});
    const m = (code, quantity) => ({ code, quantity });
    const vo = (ref, code, delta, rate, reason, by, item, unit) => ({
      ref, date: '2024-03-04', code, quantity_delta: delta,
      rate_usd: rate === undefined ? null : rate, reason: reason || '',
      authorised_by: by || '', item: item || '', unit: unit || '',
    });
    const procCases = {
      clean: [procContract(), [m('MOB', 1)], [], 1, 0],
      overmeasured: [procContract(), [m('MOB', 1), m('DRL-RK', 42)], [], 1, 0],
      varied: [procContract(), [m('MOB', 1), m('DRL-RK', 42)],
        [vo('VO-1', 'DRL-RK', 17, null, 'deeper water', 'M. Kolleh')], 2, 1500],
      unsigned: [procContract(), [m('GRAVEL', 12)],
        [vo('VO-2', 'CAS', 5)], 1, 0],
      new_item: [procContract(), [m('GRAVEL', 12)],
        [vo('VO-3', 'GRAVEL', 12, null, 'gravel pack', 'M. K.', 'Gravel pack', 'm3')],
        1, 0],
      advance: [procContract({ advance_percent: 20, retention_percent: 5 }),
        [m('MOB', 1), m('DRL-OB', 20), m('DRL-RK', 25), m('CAS', 45)], [], 1, 0],
      overpaid: [procContract({ retention_percent: 0 }), [m('MOB', 1)], [], 2, 5000],
      negatives: [procContract(), [m('CAS', -10)], [], 3, -5],
      repriced: [procContract(), [m('MOB', 1), m('CAS', 45)],
        [vo('VO-4', 'CAS', 0, 26, 'supplier price', 'Engineer')], 1, 0],
      over_omitted: [procContract(), [m('CAS', 10)],
        [vo('VO-5', 'CAS', -60, null, 'redesign', 'Engineer')], 1, 0],
      duplicate: [{ ref: 'DUP', contractor: '', client: '', date: '',
        retention_percent: 10, retention_cap_percent: 5, advance_percent: 0,
        lines: [
          { code: 'CAS', item: 'uPVC casing 6 in', unit: 'm', quantity: 10, rate_usd: 22 },
          { code: 'CAS', item: 'uPVC casing 4 in', unit: 'm', quantity: 10, rate_usd: 22 },
        ] }, [m('CAS', 10)], [], 1, 0],
    };
    out.procurement = {};
    Object.keys(procCases).forEach((label) => {
      const [ct, ms, vs, no, prev] = procCases[label];
      const cert = C.certify(ct, ms, { number: no, date: '2024-04-01',
        variations: vs, previouslyCertifiedUsd: prev });
      out.procurement[label] = {
        certificate: cert,
        summary_rows: C.contractSummaryRows(ct, cert),
      };
    });

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
  }, reference.streamlit_project_file.yaml);

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
  // what the yield is worth, and why each method was or was not adopted:
  // numbers to tolerance, everything else word for word
  const sameValue = (js, py) => {
    if (typeof py === 'number' && typeof js === 'number') return close(js, py, 1e-4);
    if (Array.isArray(py) || (py && typeof py === 'object')) {
      return JSON.stringify(js) === JSON.stringify(py);
    }
    return js === py;
  };
  const describe = (v) => (typeof v === 'string' ? `"${v}"` : JSON.stringify(v));
  ['casing_storage_min', 'rec_intercept', 'rec_intercept_fraction', 'rec_pumping_time',
    'theis_S', 'specific_capacity', 'deepest_level', 'source', 'qualifies',
    'disqualified', 'u_check', 'confidence', 'confidence_reasons', 'confidence_text',
    'specific_capacity_basis', 'pump_depth_basis', 'basis', 'type_text', 'flags',
  ].forEach((k) => {
    check(`analysis: ${k}`, sameValue(parsed.analysis[k], R.analysis[k]),
      `js ${describe(parsed.analysis[k])}\n     py ${describe(R.analysis[k])}`);
  });
  ['T', 'source', 'qualifies', 'cj', 'theis', 'rec', 'rec_pumping_time', 'rec_equivalent',
    'B', 'C', 'two_point', 'safe', 'pump_depth', 'confidence', 'confidence_reasons',
    'pump_depth_basis', 'specific_capacity_basis', 'flags', 'type_text', 'step_numbers',
  ].forEach((k) => {
    check(`step analysis: ${k}`, sameValue(parsed.step_analysis[k], R.step_analysis[k]),
      `js ${describe(parsed.step_analysis[k])}\n     py ${describe(R.step_analysis[k])}`);
  });
  check('assessment: verdict', parsed.assessed.verdict === R.assessed.verdict,
    `js "${parsed.assessed.verdict}"\n     py "${R.assessed.verdict}"`);
  check('assessment: wqi', close(parsed.assessed.wqi, R.assessed.wqi),
    `js ${parsed.assessed.wqi} vs py ${R.assessed.wqi}`);
  check('assessment: corrosivity', parsed.assessed.corros === R.assessed.corros,
    `js ${parsed.assessed.corros} vs py ${R.assessed.corros}`);
  check('assessment: corrosivity verdict',
    parsed.assessed.corros_verdict === R.assessed.corros_verdict,
    `js "${parsed.assessed.corros_verdict}"\n     py "${R.assessed.corros_verdict}"`);
  check('assessment: corrosivity materials note',
    parsed.assessed.corros_materials === R.assessed.corros_materials,
    `js "${parsed.assessed.corros_materials}"\n     py "${R.assessed.corros_materials}"`);
  check('assessment: national exceedances',
    JSON.stringify(parsed.assessed.national) === JSON.stringify(R.assessed.national),
    `js ${JSON.stringify(parsed.assessed.national)} py ${JSON.stringify(R.assessed.national)}`);
  check('design: screens', JSON.stringify(parsed.design.screens) === JSON.stringify(R.design.screens),
    JSON.stringify(parsed.design.screens) + ' vs ' + JSON.stringify(R.design.screens));
  check('design: sanitary seal', JSON.stringify(parsed.design.seal) === JSON.stringify(R.design.seal),
    JSON.stringify(parsed.design.seal) + ' vs ' + JSON.stringify(R.design.seal));
  check('design: cement for the seal', close(parsed.design.cement_bags, R.design.cement_bags),
    `js ${parsed.design.cement_bags} vs py ${R.design.cement_bags}`);
  // workstream 4: the log's own words decide the design, and every document
  // follows it word for word
  for (const [key, label] of [
    ['depth', 'total depth'], ['screen_len', 'total screen length'],
    ['annulus_mm', 'annulus per side'], ['bore_in', 'bore diameter as logged'],
    ['pump_intake', 'pump intake moved into plain casing'],
    ['gravel_interval', 'gravel priced only where it can be placed'],
    ['grout', 'grout depth from the log'],
  ]) {
    check(`design: ${label}`, close(parsed.design[key], R.design[key]),
      `js ${parsed.design[key]} vs py ${R.design[key]}`);
  }
  for (const [key, label] of [
    ['annular_fill', 'annular fill'], ['as_built', 'as built'],
    ['construction_note', 'construction note'],
  ]) {
    check(`design: ${label}`, parsed.design[key] === R.design[key],
      `js ${JSON.stringify(parsed.design[key])}\n     py ${JSON.stringify(R.design[key])}`);
  }
  for (const [key, label] of [
    ['gravel', 'annular fill interval'], ['backfill', 'backfill'],
    ['basis', 'basis sentences, word for word'], ['flags', 'flags'],
    ['summary_rows', 'summary rows, word for word'],
    ['installed_screens', 'installed screens from the log'],
    ['bands', 'lithology bands'],
  ]) {
    check(`design: ${label}`,
      JSON.stringify(parsed.design[key]) === JSON.stringify(R.design[key]),
      `js ${JSON.stringify(parsed.design[key])}\n     py ${JSON.stringify(R.design[key])}`);
  }
  check('costing: a manual estimate prices the seal it is given',
    close(parsed.costing_manual.cement_bags, R.costing_manual.cement_bags) &&
      parsed.costing_manual.seal_note === R.costing_manual.seal_note,
    JSON.stringify(parsed.costing_manual) + ' vs ' + JSON.stringify(R.costing_manual));
  check('checklists: every item id, in order',
    JSON.stringify(parsed.checklists.ids) === JSON.stringify(R.checklists.ids),
    JSON.stringify(parsed.checklists.ids.slice(0, 3)) + ' vs ' + JSON.stringify(R.checklists.ids.slice(0, 3)));
  check('checklists: the positional-to-stable map',
    JSON.stringify(parsed.checklists.legacy) === JSON.stringify(R.checklists.legacy),
    JSON.stringify(parsed.checklists.legacy).slice(0, 200) + ' vs ' + JSON.stringify(R.checklists.legacy).slice(0, 200));
  check('checklists: an old answer lands on the same question',
    JSON.stringify(Object.keys(parsed.checklists.migrated).sort()) ===
      JSON.stringify(Object.keys(R.checklists.migrated).sort()),
    JSON.stringify(parsed.checklists.migrated) + ' vs ' + JSON.stringify(R.checklists.migrated));
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

  // --- The interpretation and the preference table ---
  parsed.interpretations.forEach((s, i) => {
    const ref = R.interpretations[i];
    check(`interpretation[${i}] ${s.id}: zones, depths and flags`,
      JSON.stringify([s.water_zones, s.max_drilling_depth_m, s.investigation_depth_m,
        s.max_spacing_m, s.basement_not_resolved, s.fit_quality, s.flags]) ===
      JSON.stringify([ref.water_zones, ref.max_drilling_depth_m, ref.investigation_depth_m,
        ref.max_spacing_m, ref.basement_not_resolved, ref.fit_quality, ref.flags]),
      `js ${JSON.stringify([s.water_zones, s.max_drilling_depth_m, s.fit_quality, s.flags])}\n     ` +
      `py ${JSON.stringify([ref.water_zones, ref.max_drilling_depth_m, ref.fit_quality, ref.flags])}`);
    check(`interpretation[${i}] ${s.id}: confidence`,
      close(s.confidence, ref.confidence, 1e-6), `js ${s.confidence} vs py ${ref.confidence}`);
    check(`interpretation[${i}] ${s.id}: narrative`, s.narrative === ref.narrative,
      `js ${s.narrative}\n     py ${ref.narrative}`);
  });
  check('preference table: the same rows, word for word',
    JSON.stringify(parsed.preference) === JSON.stringify(R.preference),
    `js ${JSON.stringify(parsed.preference)}\n     py ${JSON.stringify(R.preference)}`);

  // --- Interpretation and report prose past the Rokel pair ---
  // A reference written before this section existed fails here by name
  // rather than stopping every check after it.
  check('ves text: the reference carries the section', !!R.ves_text,
    'regenerate tests/webapp/reference.json with make_reference.py');
  const VT = R.ves_text || { cases: {} };
  Object.keys(VT.cases).forEach((name) => {
    const js = parsed.ves_text.cases[name], py = VT.cases[name];
    ['water_zones', 'depth_to_basement_m', 'investigation_depth_m',
      'max_drilling_depth_m', 'basement_not_resolved', 'drilling_depth_capped',
      'drilling_depth_text', 'flags', 'narrative', 'rationale'].forEach((key) => {
      check(`ves case ${name}: ${key}`,
        JSON.stringify(js[key]) === JSON.stringify(py[key]),
        `js ${JSON.stringify(js[key])}\n     py ${JSON.stringify(py[key])}`);
    });
    check(`ves case ${name}: suitability`, close(js.suitability, py.suitability, 1e-6),
      `js ${js.suitability} vs py ${py.suitability}`);
  });
  ['near_tie', 'equal', 'clear', 'same_id'].filter((name) => VT[name]).forEach((name) => {
    ['tie', 'verdict', 'preference'].forEach((key) => {
      const js = parsed.ves_text[name][key], py = VT[name][key];
      check(`ranking ${name}: ${key}`, JSON.stringify(js) === JSON.stringify(py),
        `js ${JSON.stringify(js)}\n     py ${JSON.stringify(py)}`);
    });
  });
  ['rokel_verdict', 'models_tried', 'poorly_resolved', 'doi_text', 'sheets']
    .filter((key) => key in VT).forEach((key) => {
      const js = parsed.ves_text[key], py = VT[key];
      check(`ves text: ${key}, word for word`, JSON.stringify(js) === JSON.stringify(py),
        `js ${JSON.stringify(js)}\n     py ${JSON.stringify(py)}`);
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

  // --- The certification gate ---
  // A report is what a borehole is handed over on, so both engines have to
  // agree on what it can stand behind, down to the sentence they give the
  // analyst.
  // --- procurement ---
  Object.keys(R.procurement).forEach((label) => {
    const js = parsed.procurement[label].certificate;
    const py = R.procurement[label].certificate;
    check(`procurement ${label}: the money`,
      ['contract_sum_usd', 'variation_usd', 'revised_sum_usd', 'gross_usd',
        'percent_complete', 'retention_usd', 'advance_recovered_usd',
        'net_certified_usd', 'previously_certified_usd', 'due_now_usd',
        'overpaid_usd', 'overmeasure_usd'].every((k) => close(js[k], py[k])) &&
      js.summary === py.summary,
      JSON.stringify(js) + '\n     vs ' + JSON.stringify(py));
    check(`procurement ${label}: the problems, word for word`,
      JSON.stringify(js.problems) === JSON.stringify(py.problems),
      JSON.stringify(js.problems) + '\n     vs ' + JSON.stringify(py.problems));
    check(`procurement ${label}: every valued line`,
      js.lines.length === py.lines.length && js.lines.every((line, i) => {
        const w = py.lines[i];
        return line.code === w.code && line.item === w.item &&
          line.unit === w.unit && line.in_contract === w.in_contract &&
          JSON.stringify(line.variation_refs) === JSON.stringify(w.variation_refs) &&
          ['rate_usd', 'contract_quantity', 'variation_quantity',
            'authorised_quantity', 'measured_quantity', 'payable_quantity',
            'overmeasure_quantity', 'contract_amount_usd',
            'authorised_amount_usd', 'payable_amount_usd',
            'overmeasure_amount_usd', 'percent_complete']
            .every((k) => close(line[k], w[k]));
      }),
      JSON.stringify(js.lines) + '\n     vs ' + JSON.stringify(py.lines));
    check(`procurement ${label}: the head of the certificate`,
      JSON.stringify(parsed.procurement[label].summary_rows) ===
        JSON.stringify(R.procurement[label].summary_rows),
      JSON.stringify(parsed.procurement[label].summary_rows) + '\n     vs ' +
      JSON.stringify(R.procurement[label].summary_rows));
  });

  // --- coverage as a planning figure ---
  parsed.wpdx_fields.forEach((js, i) => {
    const py = R.wpdx_fields[i];
    check(`planning: reading ${JSON.stringify(js.date)} / ${JSON.stringify(js.months_text)}`,
      js.year === py.year && js.months === py.months,
      JSON.stringify(js) + ' vs ' + JSON.stringify(py));
  });
  check('planning: the growth rate is derived the same way',
    close(parsed.growth_rate, R.growth_rate),
    `${parsed.growth_rate} vs ${R.growth_rate}`);
  Object.keys(R.planning).forEach((label) => {
    const js = parsed.planning[label], py = R.planning[label];
    check(`planning ${label}: the projection`,
      js.projection.base_year === py.projection.base_year &&
      js.projection.target_year === py.projection.target_year &&
      js.projection.uniform === py.projection.uniform &&
      close(js.projection.rate, py.projection.rate) &&
      close(js.projection.factor, py.projection.factor) &&
      js.projection.note === py.projection.note,
      JSON.stringify(js.projection) + '\n     vs ' + JSON.stringify(py.projection));
    check(`planning ${label}: the headline figures`,
      Object.keys(py.stats).every((k) => (
        typeof py.stats[k] === 'number'
          ? close(js.stats[k], py.stats[k])
          : JSON.stringify(js.stats[k]) === JSON.stringify(py.stats[k]))),
      JSON.stringify(js.stats) + '\n     vs ' + JSON.stringify(py.stats));
    check(`planning ${label}: every row`,
      js.rows.length === py.rows.length && js.rows.every((row, i) => {
        const w = py.rows[i];
        return row.name === w.name && row.rank === w.rank &&
          row.water_points === w.water_points &&
          row.functional_points === w.functional_points &&
          row.recent_functional_points === w.recent_functional_points &&
          close(row.population, w.population) &&
          close(row.people_per_point, w.people_per_point) &&
          close(row.people_per_recent_point, w.people_per_recent_point) &&
          close(row.staleness_gap_percent, w.staleness_gap_percent) &&
          row.freshness.state === w.freshness.state &&
          row.freshness.detail === w.freshness.detail &&
          close(row.freshness.median_age_years, w.freshness.median_age_years) &&
          row.seasonal.detail === w.seasonal.detail &&
          row.seasonal.is_established === w.seasonal.is_established &&
          close(row.seasonal.people_per_point_low, w.seasonal.people_per_point_low) &&
          close(row.seasonal.people_per_point_high, w.seasonal.people_per_point_high);
      }),
      JSON.stringify(js.rows) + '\n     vs ' + JSON.stringify(py.rows));
  });

  // --- the seasonal yield model ---
  parsed.seasonal_dates.forEach((js, i) => {
    const py = R.seasonal_dates[i];
    check(`seasonal: reading the date ${JSON.stringify(js.text)}`,
      js.month === py.month && js.note === py.note,
      JSON.stringify(js) + '\n     vs ' + JSON.stringify(py));
  });
  Object.keys(R.seasonal).forEach((label) => {
    const js = parsed.seasonal[label], py = R.seasonal[label];
    check(`seasonal ${label}: the headline figures`,
      js.month === py.month && js.season === py.season &&
      js.month_note === py.month_note && js.range_source === py.range_source &&
      close(js.annual_range_m, py.annual_range_m) &&
      close(js.design_yield_m3_per_h, py.design_yield_m3_per_h) &&
      close(js.pump_installation_depth_m, py.pump_installation_depth_m) &&
      close(js.dry_season_loss_percent, py.dry_season_loss_percent) &&
      js.summary === py.summary,
      JSON.stringify(js) + '\n     vs ' + JSON.stringify(py));
    check(`seasonal ${label}: every scenario`,
      js.scenarios.length === py.scenarios.length &&
      js.scenarios.every((s, i) => {
        const w = py.scenarios[i];
        return s.key === w.key && s.title === w.title && s.note === w.note &&
          close(s.decline_m, w.decline_m) &&
          close(s.static_water_level_m, w.static_water_level_m) &&
          close(s.available_drawdown_m, w.available_drawdown_m) &&
          close(s.safe_yield_m3_per_h, w.safe_yield_m3_per_h) &&
          close(s.pump_installation_depth_m, w.pump_installation_depth_m);
      }),
      JSON.stringify(js.scenarios) + '\n     vs ' + JSON.stringify(py.scenarios));
  });

  // --- the QR encoder ---
  // Module for module. A symbol that is wrong in the data region still looks
  // exactly like a QR symbol, so nothing short of every module is a check.
  check('qr: same number of symbols', parsed.qr.length === R.qr.length,
    `js ${parsed.qr.length} vs py ${R.qr.length}`);
  let qrMismatched = 0, qrFirst = '';
  parsed.qr.forEach((js, i) => {
    const py = R.qr[i];
    if (!py) return;
    if (js.version !== py.version || js.size !== py.size ||
        js.chosen_mask !== py.chosen_mask || js.penalty !== py.penalty ||
        js.rows.join('') !== py.rows.join('')) {
      qrMismatched += 1;
      if (!qrFirst) {
        const row = js.rows.findIndex((r, k) => r !== py.rows[k]);
        qrFirst = `${py.ecc}/${py.mask} v${py.version} vs v${js.version}, ` +
          `mask ${js.chosen_mask} vs ${py.chosen_mask}, ` +
          `penalty ${js.penalty} vs ${py.penalty}, first differing row ${row}`;
      }
    }
  });
  check('qr: every module of every symbol matches the toolkit',
    qrMismatched === 0, `${qrMismatched} symbol(s) differ; ${qrFirst}`);
  check('qr: the capacity table matches',
    JSON.stringify(parsed.qr_capacity) === JSON.stringify(R.qr_capacity),
    JSON.stringify(parsed.qr_capacity.filter((r, i) =>
      JSON.stringify(r) !== JSON.stringify(R.qr_capacity[i]))));

  // --- the asset registry ---
  check('registry: identifiers are minted the same way',
    JSON.stringify(parsed.asset_ids) === JSON.stringify(R.asset_ids),
    JSON.stringify(parsed.asset_ids) + '\n     vs ' + JSON.stringify(R.asset_ids));
  parsed.asset_id_parsing.forEach((js, i) => {
    const py = R.asset_id_parsing[i];
    check(`registry: reading ${JSON.stringify(js.typed)}`,
      js.parsed === py.parsed && js.ok === py.ok && js.reason === py.reason,
      JSON.stringify(js) + '\n     vs ' + JSON.stringify(py));
  });
  check('registry: merging two phones gives one history',
    JSON.stringify(parsed.asset_events) === JSON.stringify(R.asset_events),
    JSON.stringify(parsed.asset_events) + '\n     vs ' + JSON.stringify(R.asset_events));
  Object.keys(R.asset_state).forEach((name) => {
    check(`registry: state of the ${name} borehole`,
      JSON.stringify(parsed.asset_state[name]) === JSON.stringify(R.asset_state[name]),
      JSON.stringify(parsed.asset_state[name]) + '\n     vs ' +
      JSON.stringify(R.asset_state[name]));
  });
  check('registry: the placard says the same thing',
    JSON.stringify(parsed.asset_placard) === JSON.stringify(R.asset_placard),
    JSON.stringify(parsed.asset_placard) + '\n     vs ' + JSON.stringify(R.asset_placard));
  check('registry: the symbol carries the same text',
    parsed.asset_qr_payload === R.asset_qr_payload,
    JSON.stringify(parsed.asset_qr_payload) + '\n     vs ' +
    JSON.stringify(R.asset_qr_payload));
  check('registry: the table rows match',
    JSON.stringify(parsed.registry_rows) === JSON.stringify(R.registry_rows),
    JSON.stringify(parsed.registry_rows) + '\n     vs ' + JSON.stringify(R.registry_rows));
  check('registry: the headline counts match',
    Object.keys(R.registry_stats).every((k) => (
      typeof R.registry_stats[k] === 'number'
        ? close(parsed.registry_stats[k], R.registry_stats[k])
        : parsed.registry_stats[k] === R.registry_stats[k])),
    JSON.stringify(parsed.registry_stats) + '\n     vs ' +
    JSON.stringify(R.registry_stats));
  check('registry: a due date never drifts over a short month',
    JSON.stringify(parsed.asset_months) === JSON.stringify(R.asset_months),
    JSON.stringify(parsed.asset_months) + '\n     vs ' + JSON.stringify(R.asset_months));

  check('a Streamlit .yaml project file is readable by the browser at all',
    parsed.streamlit_project_file.error === null,
    String(parsed.streamlit_project_file.error));
  check('a Streamlit .yaml project file reads back the same summary',
    JSON.stringify(parsed.streamlit_project_file.summary) ===
    JSON.stringify(R.streamlit_project_file.summary),
    `js ${JSON.stringify(parsed.streamlit_project_file.summary)}\n     py ${
      JSON.stringify(R.streamlit_project_file.summary)}`);

  Object.keys(R.cost_summary).forEach((name) => {
    check(`cost summary ${name}: the same rows, in the same words`,
      JSON.stringify(parsed.cost_summary[name]) ===
      JSON.stringify(R.cost_summary[name]),
      `js ${JSON.stringify(parsed.cost_summary[name])}\n     py ${
        JSON.stringify(R.cost_summary[name])}`);
  });

  Object.keys(R.handover_works).forEach((name) => {
    check(`handover works ${name}: the same bullets, in the same words`,
      JSON.stringify(parsed.handover_works[name]) ===
      JSON.stringify(R.handover_works[name]),
      `js ${JSON.stringify(parsed.handover_works[name])}\n     py ${
        JSON.stringify(R.handover_works[name])}`);
  });

  Object.keys(R.readiness).forEach((name) => {
    Object.keys(R.readiness[name]).forEach((report) => {
      const js = parsed.readiness[name][report], py = R.readiness[name][report];
      check(`readiness ${name}/${report}: state`, js.state === py.state,
        `js ${js.state} vs py ${py.state}`);
      check(`readiness ${name}/${report}: summary`, js.summary === py.summary,
        `js ${js.summary}\n     py ${py.summary}`);
      check(`readiness ${name}/${report}: requirements`,
        JSON.stringify(js.requirements) === JSON.stringify(py.requirements),
        `js ${JSON.stringify(js.requirements)}\n     py ${JSON.stringify(py.requirements)}`);
      check(`readiness ${name}/${report}: stated assumptions`,
        JSON.stringify(js.assumptions) === JSON.stringify(py.assumptions),
        `js ${JSON.stringify(js.assumptions)}\n     py ${JSON.stringify(py.assumptions)}`);
    });
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

  // --- pumping sheets at the edges ---
  // The two sample sheets are the ordinary case. These are the same sheets
  // with the cells rewritten that each hydraulics defect turned on: a rejected
  // recovery beside fits that are all disqualified, a level below the pump, a
  // hole too shallow for the intake, hourly blocks read every few minutes,
  // step times that restart, short steps inside casing storage. The grid is
  // Python's, so both engines read the same cells.
  const edgeCases = await page.evaluate((grids) => {
    const C = GWT.core;
    const out = {};
    Object.keys(grids).forEach((name) => {
      try {
        const test = C.pumpingFromGrid(JSON.parse(grids[name]), name + '.xlsx');
        const a = C.analysePumpingTest(test);
        const rec = a.yield_recommendation;
        out[name] = {
          steps: test.steps.map((s) => [s.step_number, s.discharge_m3_per_h,
            s.time_min.length, Math.min(...s.time_min), Math.max(...s.time_min)]),
          duration: test.pumping_duration_min,
          source: a.transmissivity_source,
          qualifies: C.adoptedFit(a).qualifies,
          disqualified: Object.keys(a.disqualified).sort(),
          invalid: Object.keys(a.invalid_fits || {}).sort(),
          T: a.transmissivity_m2_per_day,
          safe: rec.safe_yield_m3_per_h,
          range_text: a.yield_range_text,
          pump_depth: rec.pump_installation_depth_m,
          confidence: rec.confidence,
          confidence_reasons: rec.confidence_reasons.slice(),
          pending_reason: rec.pending_reason,
          pump_depth_basis: rec.pump_depth_basis,
          envelope_basis: rec.envelope_basis,
          rec_pumping_time: a.recovery ? a.recovery.pumping_time_min : null,
          step_numbers: a.step_test ? a.step_test.steps.map((s) => s.step) : null,
          flags: a.flags.map((f) => [f.level, f.code, f.message]),
        };
      } catch (e) { out[name] = { error: String(e && e.message || e) }; }
    });
    return out;
  }, Object.fromEntries(Object.entries(R.pumping_cases).map(([k, v]) => [k, v.grid])));
  const sameCase = (js, py) => {
    if (typeof py === 'number' && typeof js === 'number') return close(js, py, 1e-4);
    return JSON.stringify(js) === JSON.stringify(py);
  };
  Object.keys(R.pumping_cases).forEach((name) => {
    const py = R.pumping_cases[name], js = edgeCases[name] || {};
    if (js.error) { check(`pumping case ${name}: runs`, false, js.error); return; }
    Object.keys(py).filter((k) => k !== 'grid').forEach((k) => {
      check(`pumping case ${name}: ${k}`, sameCase(js[k], py[k]),
        `js ${JSON.stringify(js[k])}\n     py ${JSON.stringify(py[k])}`);
    });
  });

  // --- quantities both engines carried but nothing held them to ---
  // Eight groups were collected into the reference and read out of the
  // browser and then never compared, so a divergence in any of them passed
  // every run. A number worth computing twice is worth checking once.
  // The reference is what Python asserts, so a browser object may legitimately
  // carry keys Python never records (the site's country, its UTM zone). Compare
  // the JS value projected onto the Python shape: every field Python states has
  // to match, and a field it does not state is not a divergence.
  const onto = (js, py) => {
    if (Array.isArray(py)) {
      return Array.isArray(js) ? py.map((v, i) => onto(js[i], v)) : js;
    }
    if (py && typeof py === 'object') {
      if (!js || typeof js !== 'object') return js;
      const out = {};
      Object.keys(py).forEach((k) => { out[k] = onto(js[k], py[k]); });
      return out;
    }
    return js;
  };
  const deep = (name, a, b) => check(name, JSON.stringify(onto(a, b)) === JSON.stringify(b),
    `js ${JSON.stringify(onto(a, b)).slice(0, 500)}\n     py ${JSON.stringify(b).slice(0, 500)}`);

  deep('drilling: site fields', parsed.drilling.site, R.drilling.site);
  check('pumping: duration', close(parsed.pumping.duration, R.pumping.duration),
    `js ${parsed.pumping.duration} vs py ${R.pumping.duration}`);
  deep('pumping: recovery levels', parsed.pumping.rec_wl, R.pumping.rec_wl);
  deep('spine: levels', parsed.spine.levels, R.spine.levels);
  deep('spine: piper percentages', parsed.spine.piper_percent, R.spine.piper_percent);
  deep('spine: quantity basis', parsed.spine.quantity_basis, R.spine.quantity_basis);
  deep('portfolio: statistics', parsed.portfolio.stats, R.portfolio.stats);
  deep('planning: census statistics', parsed.planning.census, R.planning.census);

  deep('VES-only design: from the interpretation alone',
    parsed.ves_only_design, R.ves_only_design);

  // --- where a report is set ---
  // The area each report maps, the sentence placing the site, the district
  // the locator lights and the geology paragraph were all worked out in the
  // page with rules of the browser's own, and none of them was held here: a
  // chiefdom window half as wide again as the Python's, no map at all for
  // "Western Area", and "crystalline basement" written over the Bullom sands
  // all passed every run.
  const regional = await page.evaluate((RR) => {
    const C = GWT.core;
    const windowOf = (w) => (w ? [w.lon, w.lat, w.radiusKm, w.label, w.exact] : null);
    const homeOf = (h) => [h.name, h.districts.slice().sort(), h.chiefdoms.slice().sort()];
    return {
      windows: RR.windows.map((c) => {
        const site = { community: 'T', chiefdom: c.chiefdom, district: c.district };
        return { window: windowOf(C.areaWindow(site, null)),
          note: C.areaMapNote(site, null), home: homeOf(C.homeDistrict(site, null)) };
      }),
      positions: RR.positions.map((c) => {
        const site = { community: 'T', chiefdom: '', district: c.district };
        const at = { lat: c.lat, lon: c.lon };
        return { window: windowOf(C.areaWindow(site, at)), note: C.areaMapNote(site, at),
          home: homeOf(C.homeDistrict(site, at)), geology: C.geologyParagraph(site, at) };
      }),
      unplaced_geology: RR.unplaced_geology.map(
        (c) => C.geologyParagraph({ district: c.district }, null)),
      caveats: RR.caveats.map((c) => C.scaleCaveat(c.radius_km, 5000000, c.note)),
      utm_zones: RR.utm_zones.map((c) => C.parseUtmZone(c.value)),
    };
  }, R.regional);
  const sameWindow = (a, b) => (a === null || b === null ? a === b
    : close(a[0], b[0], 1e-9) && close(a[1], b[1], 1e-9) && close(a[2], b[2], 1e-9) &&
      a[3] === b[3] && a[4] === b[4]);
  const windowMisses = R.regional.windows.filter(
    (c, i) => !sameWindow(regional.windows[i].window, c.window));
  check(`regional: every chiefdom and district window (${R.regional.windows.length})`,
    windowMisses.length === 0,
    windowMisses.slice(0, 5).map((c) => JSON.stringify([c.chiefdom, c.district, c.window,
      regional.windows[R.regional.windows.indexOf(c)].window])).join('\n     '));
  const noteMisses = R.regional.windows.filter((c, i) => regional.windows[i].note !== c.note);
  check('regional: the sentence placing a site with no position',
    noteMisses.length === 0,
    noteMisses.slice(0, 3).map((c) => c.note + '\n     vs ' +
      regional.windows[R.regional.windows.indexOf(c)].note).join('\n     '));
  const homeMisses = R.regional.windows.filter((c, i) =>
    JSON.stringify(regional.windows[i].home) !== JSON.stringify(c.home));
  check('regional: the district a locator lights, without a position',
    homeMisses.length === 0,
    homeMisses.slice(0, 3).map((c) => JSON.stringify(c.home) + ' vs ' + JSON.stringify(
      regional.windows[R.regional.windows.indexOf(c)].home)).join('\n     '));
  R.regional.positions.forEach((c, i) => {
    const js = regional.positions[i];
    const label = `regional: a site at ${c.lat.toFixed(4)}, ${c.lon.toFixed(4)} (${c.district})`;
    check(`${label}: window and note`,
      sameWindow(js.window, c.window) && js.note === c.note,
      JSON.stringify([js.window, js.note]) + '\n     vs ' + JSON.stringify([c.window, c.note]));
    check(`${label}: the district its locator lights`,
      JSON.stringify(js.home) === JSON.stringify(c.home),
      JSON.stringify(js.home) + ' vs ' + JSON.stringify(c.home));
    check(`${label}: the geology paragraph`, js.geology === c.geology,
      js.geology + '\n     vs ' + c.geology);
  });
  R.regional.unplaced_geology.forEach((c, i) => {
    check(`regional: the geology paragraph with no position (${JSON.stringify(c.district)})`,
      regional.unplaced_geology[i] === c.geology,
      regional.unplaced_geology[i] + '\n     vs ' + c.geology);
  });
  R.regional.caveats.forEach((c, i) => {
    check(`regional: the scale caveat for a ${c.radius_km} km radius`,
      regional.caveats[i] === c.text, regional.caveats[i] + '\n     vs ' + c.text);
  });
  check('regional: the UTM zone a cell states',
    R.regional.utm_zones.every((c, i) => regional.utm_zones[i] === c.zone),
    JSON.stringify(regional.utm_zones) + '\n     vs ' +
    JSON.stringify(R.regional.utm_zones.map((c) => c.zone)));

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n     '));
}, {});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

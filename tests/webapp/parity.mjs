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
        };
      });
    });

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

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n     '));
}, {});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

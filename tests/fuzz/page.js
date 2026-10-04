/* What the browser engine makes of one generated workbook.
 *
 * Loaded into the bare engine page by engine.mjs. Each summary here has a
 * twin in engines.py that builds the same keys from the Python objects; the
 * two are compared there, with make_reference.py's comparison. A key added on
 * one side and not the other is reported as a divergence, so the two are
 * kept in the same order to make that easy to see.
 */
(function (global) {
  'use strict';

  var C = global.GWT.core, S = global.GWT.support;

  function num(v) {
    return (typeof v === 'number' && !isFinite(v)) ? null : (v === undefined ? null : v);
  }
  function nums(a) { return a ? Array.prototype.map.call(a, num) : null; }
  function flagRows(flags) {
    return (flags || []).map(function (f) {
      return [f.level, f.code, f.message, f.context || ''];
    });
  }
  function site(s) {
    s = s || {};
    return {
      client: s.client || '', project: s.project || '', community: s.community || '',
      chiefdom: s.chiefdom || '', district: s.district || '',
      project_ref: s.project_ref || '', easting: num(s.easting),
      northing: num(s.northing), utm_zone: num(s.utm_zone),
      elevation_m: num(s.elevation_m), date: s.date || '',
      supervisor: s.supervisor || '', contractor: s.contractor || '',
    };
  }
  function failure(e) { return { error: String(e && e.message !== undefined ? e.message : e) }; }

  function ves(sheets, name, options) {
    var skipped = [];
    var soundings = C.readVesSheets(sheets, name, skipped);
    var out = {
      skipped: flagRows(skipped),
      soundings: soundings.map(function (s) {
        return {
          id: s.sounding_id, array: s.array_type, instrument: s.instrument || '',
          ab2: nums(s.ab2), mn: nums(s.mn), rho: nums(s.rho_app),
          site: site(s.site), flags: flagRows(s.flags),
        };
      }),
    };
    if (options.invert) {
      out.inversions = soundings.map(function (s) {
        try {
          var r = C.invertSounding(s);
          return { rho: nums(r.model.resistivities), h: nums(r.model.thicknesses),
            err: num(r.fit_error_percent), converged: !!r.converged };
        } catch (e) { return failure(e); }
      });
    }
    return out;
  }

  function pumping(sheets, name) {
    var test;
    try { test = C.pumpingFromGrid(sheets[0].rows, name); } catch (e) { return failure(e); }
    var out = {
      type: test.test_type, swl: num(test.static_water_level_m),
      depth: num(test.borehole_depth_m), pump: num(test.pump_setting_m),
      step_length: num(test.step_length_min), ref: test.borehole_ref || '',
      steps: test.steps.map(function (s) {
        return { n: s.step_number, q: num(s.discharge_m3_per_h), t: nums(s.time_min),
          wl: nums(s.water_level_m), label: s.label };
      }),
      rec_t: nums(test.recovery_time_min), rec_wl: nums(test.recovery_level_m),
      duration: num(test.pumping_duration_min),
      offsets: C.stepOffsetsMin(test.steps),
      site: site(test.site), flags: flagRows(test.flags),
    };
    try {
      var a = C.analysePumpingTest(test);
      var rec = a.yield_recommendation;
      out.analysis = {
        source: a.transmissivity_source,
        qualifies: C.adoptedFit(a).qualifies,
        disqualified: Object.keys(a.disqualified).sort(),
        invalid: Object.keys(a.invalid_fits || {}).sort(),
        T: num(a.transmissivity_m2_per_day),
        cj: a.cooper_jacob ? num(a.cooper_jacob.transmissivity_m2_per_day) : null,
        theis: a.theis ? num(a.theis.transmissivity_m2_per_day) : null,
        rec: a.recovery ? num(a.recovery.transmissivity_m2_per_day) : null,
        safe: num(rec.safe_yield_m3_per_h),
        range_text: a.yield_range_text,
        pump_depth: num(rec.pump_installation_depth_m),
        confidence: rec.confidence,
        confidence_reasons: rec.confidence_reasons.slice(),
        pending_reason: rec.pending_reason,
        pump_depth_basis: rec.pump_depth_basis,
        envelope_basis: rec.envelope_basis,
        rec_pumping_time: a.recovery ? num(a.recovery.pumping_time_min) : null,
        step_numbers: a.step_test ? a.step_test.steps.map(function (s) { return s.step; }) : null,
        B: a.step_test ? num(a.step_test.aquifer_loss_B) : null,
        C: a.step_test ? num(a.step_test.well_loss_C) : null,
        flags: flagRows(a.flags),
        spread: spread(a),
      };
    } catch (e) { out.analysis = failure(e); }
    return out;
  }

  /* engines.py _spread: PLAN.md step 3.2's bands and regimes, the
   * Papadopulos-Cooper band left out */
  function spread(a) {
    var sp = a.spread, boot = sp ? sp.bootstrap : null, th = a.theis;
    var exact = !!boot && boot.method !== 'papadopulos_cooper';
    return {
      method: boot ? boot.method : null,
      p10: exact ? num(boot.p10) : null,
      p90: exact ? num(boot.p90) : null,
      holds: sp ? !!sp.holds_at_dry_season : null,
      pump: sp ? [num(sp.pump_depth_low_m), num(sp.pump_depth_high_m)] : null,
      regimes: a.diagnostic ? a.diagnostic.regimes.map(function (r) { return r.key; }) : null,
      theis_band: th ? [num(th.transmissivity_low_m2_per_day),
        num(th.transmissivity_high_m2_per_day)] : null,
    };
  }

  function quality(sheets, name) {
    var sample;
    try { sample = C.qualityFromGrid(sheets[0].rows, name); } catch (e) { return failure(e); }
    var out = {
      id: sample.sample_id || '', ref: sample.borehole_ref || '',
      lab: sample.laboratory || '', date: sample.sample_date || '',
      results: sample.results.map(function (r) {
        return [r.parameter, num(r.value), r.unit || '', num(r.detection_limit),
          !!r.below_detection, num(r.greater_than), !!r.greater_than_inclusive,
          r.unreadable || ''];
      }),
      site: site(sample.site), flags: flagRows(sample.flags),
    };
    try {
      var a = C.assessSample(sample);
      out.assessment = {
        verdict: a.verdict,
        health: a.health_exceedances.map(function (r) { return r.parameter; }),
        national: a.national_exceedances.map(function (r) { return r.parameter; }),
        missing: (a.missing_essential || []).slice(),
        rows: a.rows.map(function (r) {
          return [r.parameter, r.status, num(r.value_in_guideline_unit),
            r.guideline_unit || '', !!r.evaluable, r.reason || ''];
        }),
        wqi: a.wqi ? num(a.wqi.value) : null,
        corros: a.corrosivity ? a.corrosivity.classification : null,
        ionic: a.ionic ? num(a.ionic.error_percent) : null,
        flags: flagRows(a.flags),
      };
    } catch (e) { out.assessment = failure(e); }
    return out;
  }

  function drilling(sheets, name, options) {
    var log;
    try { log = C.drillingFromGrid(sheets[0].rows, name); } catch (e) { return failure(e); }
    var out = {
      ref: log.borehole_ref || '', total: num(log.total_depth_m),
      method: log.drilling_method || '', status: log.status || '',
      strikes: nums(log.water_strikes_m), grout: num(log.grouting_depth_m),
      installed: (log.installed_screens_m || []).map(function (s) { return [num(s[0]), num(s[1])]; }),
      intervals: log.intervals.map(function (iv) {
        return [num(iv.top_m), num(iv.bottom_m), iv.description,
          num(iv.penetration_rate_m_per_min), num(iv.bit_diameter_in),
          iv.from_time || '', iv.to_time || ''];
      }),
      site: site(log.site), flags: flagRows(log.flags),
    };
    try {
      var d = C.designBorehole({
        log: log, staticWaterLevelM: options.swl === undefined ? null : options.swl,
        pumpIntakeM: options.pump === undefined ? null : options.pump,
      });
      out.design = {
        rows: C.designSummaryRows(d).map(function (r) { return [r[0], r[1]]; }),
        screens: d.screens.map(function (s) { return [num(s.top_m), num(s.bottom_m)]; }),
        basis: d.design_basis.slice(),
        pump: num(d.pump_intake_m),
        flags: flagRows(d.flags),
      };
    } catch (e) { out.design = failure(e); }
    return out;
  }

  var KINDS = { ves: ves, pumping: pumping, quality: quality, drilling: drilling };

  global.FUZZ = {
    run: async function (kind, name, b64, options) {
      var sheets;
      try { sheets = await S.readXlsx(S.base64ToBytes(b64)); } catch (e) { return failure(e); }
      try { return KINDS[kind](sheets, name, options || {}); } catch (e) { return failure(e); }
    },
  };
})(window);

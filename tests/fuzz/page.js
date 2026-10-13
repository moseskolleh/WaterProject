/* What the browser engine makes of one generated workbook, or of one
 * generated raster, block of one or window of heights.
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

  /* engines.py _deflate: PLAN.md step 4.1's DEFLATE block under the
   * bounded rule, whether it reads and what it gives as strings */
  function deflate(bytes, name, options) {
    var block;
    try {
      block = C.inflateZlib(bytes, options.expected, options.full);
    } catch (e) {
      if (e && e.code) return { verdict: e.code, sha256: null, length: null };
      throw e;
    }
    return { verdict: 'accepted', sha256: C.sha256Hex(block), length: String(block.length) };
  }

  /* SHA-256 of float64 values, little-endian, every NaN 0x7FF8000000000000
   * and the signs of zeros kept */
  function f64Digest(values) {
    var bytes = new Uint8Array(values.length * 8), view = new DataView(bytes.buffer);
    for (var i = 0; i < values.length; i++) {
      if (values[i] !== values[i]) {
        view.setUint32(8 * i, 0, true);
        view.setUint32(8 * i + 4, 0x7FF80000, true);
      } else {
        view.setFloat64(8 * i, values[i], true);
      }
    }
    return C.sha256Hex(bytes);
  }
  /* a number's float64 bits, big-endian, as hex */
  function f64Hex(v) {
    if (v !== v) return '7ff8000000000000';
    var view = new DataView(new ArrayBuffer(8)), out = '';
    view.setFloat64(0, v, false);
    for (var i = 0; i < 8; i++) out += (view.getUint8(i) + 256).toString(16).slice(1);
    return out;
  }
  var LAYOUT_FLOATS = ['x0', 'y0', 'sx', 'sy', 'nodata'];

  /* engines.py _geotiff: PLAN.md step 4.1's whole GeoTIFF through the raw
   * reader, the ranges, the layout or refusal, and the read, every one a
   * string */
  function geotiff(bytes, name, options) {
    var out = { need: null, layout: null, refused: null, values: null, reasons: null, axes: null };
    try {
      var need = C.geotiffLayout(name, bytes.length, [[0, bytes.subarray(0, 16)]]);
      out.need = Array.isArray(need) ? JSON.stringify(need) : 'layout';
    } catch (e) {
      if (!e || !e.ident) throw e;
      out.need = e.ident;
    }
    var layout, read;
    try {
      layout = C.geotiffLayout(name, bytes.length, [[0, bytes]]);
      var fields = {};
      Object.keys(layout).sort().forEach(function (key) {
        var value = layout[key];
        fields[key] = LAYOUT_FLOATS.indexOf(key) >= 0 && value !== null ? f64Hex(value) : value;
      });
      out.layout = JSON.stringify(fields);
      read = C.readGeoTiff(bytes, name);
    } catch (e) {
      if (!e || !e.ident) throw e;
      out.refused = e.ident + ': ' + e.message;
      return out;
    }
    var reasons = new Array(layout.width * layout.height);
    var across = layout.tiled ? Math.ceil(layout.width / layout.blockWidth) : 1;
    C.blockRanges(layout, 0, layout.height, 0, layout.width).forEach(function (range) {
      var block = C.decodeTiffBlock(layout, range[0], bytes.subarray(range[1], range[1] + range[2]), range[3],
        options.bounds);
      var top = Math.floor(range[0] / across) * layout.blockHeight, left = (range[0] % across) * layout.blockWidth;
      for (var r = 0; r < block.rows; r++) {
        for (var c = 0; c < block.cols; c++) {
          reasons[(top + r) * layout.width + left + c] = block.reasons[r * block.cols + c];
        }
      }
    });
    var axes = new Float64Array(read.x.length + read.y.length);
    axes.set(read.x);
    axes.set(read.y, read.x.length);
    out.values = f64Digest(read.z);
    out.reasons = reasons.join('');
    out.axes = f64Digest(axes);
    return out;
  }

  /* engines.py _terrain: PLAN.md step 4.1's whole terrain analysis on one
   * window in float64, every exact quantity a string (each layer by
   * digest, the links and parts by a digest of their JSON with each length
   * by its bits, the GeoJSON by SHA-256 and length, the captions as text,
   * the summary's values by their bits), the wetness index apart */
  function terrain(bytes, name, options) {
    var rows = options.rows, cols = options.cols, n = rows * cols;
    var view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    var number = function (k) { return view.getFloat64(8 * k, true); };
    var z = new Float64Array(n), lons = new Float64Array(cols), lats = new Float64Array(rows), k;
    for (k = 0; k < n; k++) z[k] = number(k);
    for (k = 0; k < cols; k++) lons[k] = number(n + k);
    for (k = 0; k < rows; k++) lats[k] = number(n + cols + k);
    var sea = bytes.slice(8 * (n + cols + rows), 8 * (n + cols + rows) + n);
    var heard = [];
    var a = C.analyseTerrain({ lons: lons, lats: lats, z: z, rows: rows, cols: cols, assumedSea: sea,
      sourceId: options.source_id, seaClean: options.sea_clean, label: options.label },
    { terrain: options.settings }, function (fraction, label) { heard.push([f64Hex(fraction), label]); },
    'float64', options.shown);
    var core = a.core;
    var layers = { cls: core.cls, code: core.code, flag: core.flag, raised: core.raised, flatRouted: core.flatRouted,
      stream: a.stream, count: core.count, areaUnits: core.areaUnits, filled: a.filled, fillDepth: a.fillDepth,
      p: a.p, q: a.q, tanb: a.tanb };
    a.hillshades.forEach(function (layer, j) { layers['hillshade' + j] = layer; });
    Object.assign(layers, { hillshadeMulti: a.hillshadeMulti, twiArg: a.twiArg, profile: a.profile,
      tangential: a.tangential, dx: core.dx, dy: core.dy, dg: core.dg });
    var digests = {};
    Object.keys(layers).forEach(function (key) { digests[key] = f64Digest(layers[key]); });
    var lines = function (found) {
      return C.sha256Hex(JSON.stringify(found.map(function (line) {
        return Object.assign({}, line, { length_m: f64Hex(line.length_m) });
      })));
    };
    var meta = Object.assign({}, options.meta);
    var geojson = C.drainageGeoJson(C.terrainCore(a), a.parts, meta);
    var summary = Object.keys(a.summary).filter(function (key) { return key !== 'twi_range'; });
    var values = {};
    summary.forEach(function (key) { values[key] = f64Hex(a.summary[key]); });
    var twi = a.twi, finite = [];
    for (k = 0; k < twi.length; k++) if (twi[k] - twi[k] === 0) finite.push(k);
    var at = [];
    if (finite.length) {
      for (k = 0; k < 25; k++) {
        var i = finite[Math.floor(k * (finite.length - 1) / 24)];
        if (at.indexOf(i) < 0) at.push(i);
      }
      at.sort(function (x, y) { return x - y; });
    }
    var captions = C.terrainCaptions(a, options.read, options.where);
    return {
      layers: digests, links: lines(a.links), parts: lines(a.parts),
      counts: a.links.length + ' links, ' + a.parts.length + ' parts',
      geojson: C.sha256Hex(geojson) + ' ' + geojson.length,
      captions: Object.keys(captions).map(function (key) { return [key, captions[key]]; }),
      summary_keys: summary.join(' '), summary: values,
      scalars: [a.unresolved, a.kCells, a.floored, a.zeroFill].concat(Array.from(core.shown)).join(' '),
      heard: heard,
      terrain_twi: { at: at.join(','), cells: nums(at.map(function (j) { return twi[j]; })),
        range: nums(a.summary.twi_range) },
    };
  }

  var KINDS = { ves: ves, pumping: pumping, quality: quality, drilling: drilling };
  /* the kinds from rasters.py, handed the file's bytes rather than the
   * sheets of a workbook */
  var FILES = { deflate: deflate, geotiff: geotiff, terrain: terrain };

  global.FUZZ = {
    run: async function (kind, name, b64, options) {
      if (FILES[kind]) {
        try { return FILES[kind](S.base64ToBytes(b64), name, options || {}); } catch (e) { return failure(e); }
      }
      var sheets;
      try { sheets = await S.readXlsx(S.base64ToBytes(b64)); } catch (e) { return failure(e); }
      try { return KINDS[kind](sheets, name, options || {}); } catch (e) { return failure(e); }
    },
  };
})(window);

/* gwt-ves-copilot.js - the VES co-pilot: a sounding checked at the peg, while
 * the crew can still re-measure (PLAN.md step 2.2).
 *
 * Everything the Geophysics page can say about a bad reading it says
 * afterwards, in the office, when the line has been rolled up. The Rokel
 * soundings carry overlap pairs that disagree by 45 to 98 percent; the
 * warning that names them reaches the geophysicist, who can do nothing about
 * them. Here the same checks run as each reading is typed in, at the peg:
 *
 *   - before the survey, the target depth sets how long the line has to be,
 *     by the one depth-of-investigation rule the engines use, and the AB/2
 *     series and MN changes are proposed from it;
 *   - each reading, as V and I or as an apparent resistivity, goes on the
 *     log-log curve at once, with four checks: a rise no layered earth can
 *     make, an overlap pair that disagrees, a potential too small to read,
 *     and a spacing skipped or read twice;
 *   - from eight readings a preview inversion runs in the engine worker, so
 *     the team can see whether basement is in view while the line can still
 *     be extended;
 *   - the output is the standard VES template workbook, which both apps'
 *     readers take as they take any other.
 *
 * The browser app only; the Streamlit app says so on its Geophysics page.
 * The session is a field of the project state, so it is kept in IndexedDB
 * with the rest of the project and survives a reload; opening another
 * project or a sample carries it over (FIELD_SESSIONS in gwt-app.js).
 * Nothing here touches the DOM at load time: a Node sandbox can load this
 * file beside support.js and gwt-core.js and write the workbook
 * (tests/test_ves_copilot.py).
 */
(function (global) {
  'use strict';

  /** @type {GWTNamespace} */
  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support, C = GWT.core;

  /* the field of the project state the session lives in */
  var STATE_KEY = 'vesCopilot';

  /* The AB/2 a crew pegs, in metres: about six to a decade, the usual
   * Schlumberger progression, which spaces the readings evenly on the log
   * axis the curve is read on. The proposal stops at the first spacing long
   * enough for the target depth. */
  var AB2_SERIES = [1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50,
    60, 80, 100, 120, 150, 200, 250, 300, 400, 500];

  /* The potential-electrode spacings MN (full MN, as the sheets record it). */
  var MN_SERIES = [0.4, 1, 2, 5, 10, 20, 40, 100];

  /* MN is never more than a fifth of AB: the exact geometric factor corrects
   * a finite MN, but the Schlumberger reading is meant to approximate the
   * field gradient at the centre, and AB >= 5 MN is the usual field limit
   * for that. */
  var MIN_AB_PER_MN = 5;

  /* The potential at a fixed MN falls roughly as 1/(AB/2)^2, so a crew widens
   * MN before AB has grown past twenty times it, where the potential has
   * fallen some hundredfold from the first reading at that MN. A choice, not
   * a standard: it keeps each MN for about half a decade of AB/2. */
  var MAX_AB_PER_MN = 20;

  /* The smallest potential the instrument reads reliably, in millivolts.
   * A working default, not an instrument specification: the resistivity
   * meters these teams carry resolve microvolts, but self-potential drift
   * and telluric noise of tenths of a millivolt ride on every reading, so
   * below about a millivolt a single reading is mostly noise. Set it from
   * the instrument's manual and the noise on the day. */
  var DEFAULT_MIN_POTENTIAL_MV = 1.0;

  /* How far above the 45-degree line a reading may sit, as a fraction of the
   * resistivity, before the rise is called one no layered earth makes. Over
   * a resistive basement the curve climbs at close to 45 degrees for decades
   * of AB/2, so a bound with no margin calls every second good reading there
   * an error. Two things lift a good reading over the line: the finite MN,
   * which at a fixed MN puts the first spacings of a segment up to about 1
   * percent above it (forward_schlumberger_finite_mn through the proposed
   * plan, two-layer ground with a basement up to 10^4 times the cover), and
   * the reading's own scatter, a few percent each way on a working day. Ten
   * percent covers both, and a misread range or a slipped peg, a factor of
   * two or ten, is far beyond it. */
  var STEEP_RISE_ALLOWANCE = 0.10;

  /* The preview inversion waits for this many readings, and for this long
   * after the last change, so a reading typed in quickly after another does
   * not start a fit that is thrown away at once. */
  var PREVIEW_MIN_READINGS = 8;
  var PREVIEW_DEBOUNCE_MS = 1200;

  /* ------------------------------------------------------------ the plan */

  /** The depth of investigation: the engines' own rule, read from the
   * configuration (VESConfig.depth_of_investigation_factor).
   * @param {any} [cfg] a configuration, or the defaults */
  function doiFactor(cfg) {
    var c = cfg || C.defaultConfig();
    return c.ves.depth_of_investigation_factor;
  }

  /** The AB/2 series and the MN changes for a target depth.
   *
   * The largest AB/2 is the first spacing in the series at which the depth
   * of investigation reaches the target. MN starts at the widest spacing a
   * fifth of the first AB allows and is widened when AB passes twenty times
   * it; at each change the last AB/2 is read again with the new MN, so the
   * two segments overlap at one spacing.
   * @param {number} targetDepth metres
   * @param {any} [cfg]
   */
  function propose(targetDepth, cfg) {
    var ves = (cfg || C.defaultConfig()).ves;
    var factor = doiFactor(cfg);
    /* the engine's own C.depthOfInvestigation decides, not target / factor:
     * a factor that is not a power of two divides with a rounding error, and
     * 30 / 0.3 = 100.00000000000001 would have asked for the next spacing */
    var reaches = function (ab2) { return C.depthOfInvestigation(ab2, ves) >= targetDepth; };
    var capped = !reaches(AB2_SERIES[AB2_SERIES.length - 1]);
    var series = [];
    for (var i = 0; i < AB2_SERIES.length; i++) {
      series.push(AB2_SERIES[i]);
      if (reaches(AB2_SERIES[i])) break;
    }
    var widest = function (ab2) {
      var best = null;
      MN_SERIES.forEach(function (mn) { if (mn * MIN_AB_PER_MN <= 2 * ab2) best = mn; });
      return best === null ? MN_SERIES[0] : best;
    };
    var steps = [];
    var mn = widest(series[0]);
    series.forEach(function (ab2, k) {
      if (k > 0 && 2 * ab2 > MAX_AB_PER_MN * mn) {
        var wider = widest(series[k - 1]);
        if (wider > mn) {
          mn = wider;
          steps.push({ ab2: series[k - 1], mn: mn });
        }
      }
      steps.push({ ab2: ab2, mn: mn });
    });
    var maxAb2 = series[series.length - 1];
    return {
      target_m: targetDepth, factor: factor, max_ab2: maxAb2,
      investigation_m: C.depthOfInvestigation(maxAb2, ves),
      line_m: 2 * maxAb2, capped: capped, steps: steps,
    };
  }

  /** The plan as the text box shows it: one "AB/2 MN" pair a line.
   * @param {Array<{ab2: number, mn: number}>} steps */
  function planText(steps) {
    return steps.map(function (s) { return C.formatG(s.ab2) + '  ' + C.formatG(s.mn); })
      .join('\n');
  }

  /** The plan typed in, or why it cannot be read.
   * @param {string} text */
  function parsePlan(text) {
    var steps = [], bad = [];
    String(text || '').split(/\r?\n/).forEach(function (line, n) {
      var cells = line.trim().split(/[\s,;]+/).filter(Boolean);
      if (!cells.length) return;
      var ab2 = Number(cells[0]), mn = Number(cells[1]);
      if (cells.length !== 2 || !(ab2 > 0) || !(mn > 0) || !(mn / 2 < ab2)) {
        bad.push(n + 1);
        return;
      }
      steps.push({ ab2: ab2, mn: mn });
    });
    return { steps: steps, bad: bad };
  }

  /* ------------------------------------------------------------ readings */

  /** Apparent resistivity from the potential and the current, through the
   * engine's own geometric factor (ves/arrays.py, geometricFactor here).
   * mV over mA is a resistance in ohms.
   * @param {number} ab2 @param {number} mn @param {number} vmV @param {number} imA */
  function rhoFromPotential(ab2, mn, vmV, imA) {
    return C.apparentResistivity('schlumberger', vmV / imA, { ab2: ab2, mn: mn });
  }

  function sameSpacing(a, b) {
    return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
  }

  /** Where a reading sits in the plan: the index of its step, or -1.
   * @param {Array<{ab2: number, mn: number}>} plan @param {{ab2: number, mn: number}} r */
  function planIndex(plan, r) {
    for (var i = 0; i < plan.length; i++) {
      if (sameSpacing(plan[i].ab2, r.ab2) && sameSpacing(plan[i].mn, r.mn)) return i;
    }
    return -1;
  }

  /** The checks each reading raised when it was taken, judged against the
   * readings before it only - what the crew was told at that peg. Each is
   * {code, level, message}; level 'remeasure' means read it again before
   * moving the electrodes, 'check' means look before going on.
   * @param {any} session */
  function review(session) {
    var plan = session.plan || [];
    var readings = session.readings || [];
    var minV = session.min_potential_mV > 0 ? session.min_potential_mV
      : DEFAULT_MIN_POTENTIAL_MV;
    var read = plan.map(function () { return false; });
    var reportedSkip = plan.map(function () { return false; });
    return readings.map(function (r, n) {
      var before = readings.slice(0, n);
      var checks = [];

      /* 1. A rise steeper than 45 degrees, by more than the allowance above.
       * On log-log axes the slope of the Schlumberger apparent resistivity
       * against AB/2 cannot exceed 1 over a horizontally layered earth (with
       * MN vanishingly small): the steepest rise it allows is the
       * ascending branch over an insulating basement, which tends to
       * rho_a = (AB/2) / S, S the conductance of the cover, a line of slope
       * exactly 1 (Koefoed 1979, Geosounding Principles 1; Zohdy, Eaton
       * and Mabey 1974, USGS TWRI 2-D1). A steeper rise is a reading
       * or electrode error - a misread potential, a slipped peg, a current
       * electrode with no contact - or ground that is not layered, and in
       * every case the peg is the place to find out. The pair compared is
       * this reading and the nearest shorter spacing read with the same MN
       * (the later reading, where it was read twice), so a segment shift at
       * an MN change is not taken for a slope. */
      var prev = /** @type {any} */ (null);
      before.forEach(function (p) {
        if (sameSpacing(p.mn, r.mn) && p.ab2 < r.ab2 && (!prev || p.ab2 >= prev.ab2)) prev = p;
      });
      if (prev && prev.rho > 0 && r.rho > 0 &&
          r.rho / prev.rho > (r.ab2 / prev.ab2) * (1 + STEEP_RISE_ALLOWANCE)) {
        var slope = Math.log(r.rho / prev.rho) / Math.log(r.ab2 / prev.ab2);
        checks.push({ code: 'steep_rise', level: 'remeasure',
          message: 'Re-measure now: from AB/2 ' + C.formatG(prev.ab2) + ' m to ' +
            C.formatG(r.ab2) + ' m the curve rises at a slope of ' +
            C.pyFixed(slope, 2) + ' on log-log axes, steeper than the 45 degrees ' +
            'no layered ground can produce, by more than the ' +
            C.pyFixed(STEEP_RISE_ALLOWANCE * 100, 0) + ' percent a good reading ' +
            'may scatter. Check the spacings pegged, the ' +
            'current-electrode contact and the potential read, then take ' +
            'this reading again; if it repeats, re-read AB/2 ' +
            C.formatG(prev.ab2) + ' m as well.' });
      }

      /* 2. The overlap at an MN change: the engine's own test and threshold
       * (C.overlapDiscrepancies, OVERLAP_DISCREPANCY_RATIO), applied to the
       * readings at this AB/2 taken with another MN, the moment the second
       * of the pair is in. */
      var partners = before.filter(function (p) {
        return sameSpacing(p.ab2, r.ab2) && !sameSpacing(p.mn, r.mn);
      });
      if (partners.length) {
        var pair = partners.concat([r]);
        var discrepant = C.overlapDiscrepancies(
          pair.map(function () { return r.ab2; }),
          pair.map(function (p) { return p.rho; }));
        if (discrepant.length) {
          checks.push({ code: 'overlap_discrepancy', level: 'remeasure',
            message: 'Re-measure now: the two readings at this MN change ' +
              'should agree within ' +
              C.pyFixed((C.OVERLAP_DISCREPANCY_RATIO - 1) * 100, 0) + ' percent; ' +
              discrepant.join('; ') + '. Check the potential electrodes at both ' +
              'MN (contact, position) and read AB/2 ' + C.formatG(r.ab2) +
              ' m again with both, before the current electrodes move.' });
        }
      }

      /* 3. A potential too small for the instrument to read reliably. */
      if (r.v_mV !== null && r.v_mV !== undefined && isFinite(r.v_mV) &&
          Math.abs(r.v_mV) < minV) {
        checks.push({ code: 'low_potential', level: 'remeasure',
          message: 'Re-measure now: ' + C.formatG(r.v_mV) + ' mV is below the ' +
            C.formatG(minV) + ' mV this instrument is set to read reliably. ' +
            'Raise the current (water the current electrodes, add electrodes), ' +
            'or widen MN and read this AB/2 again at the old and the new MN.' });
      }

      /* 4. A spacing skipped or read twice. */
      var twice = before.filter(function (p) {
        return sameSpacing(p.ab2, r.ab2) && sameSpacing(p.mn, r.mn);
      });
      if (twice.length) {
        checks.push({ code: 'repeated', level: 'check',
          message: 'AB/2 ' + C.formatG(r.ab2) + ' m with MN ' + C.formatG(r.mn) +
            ' m was already read (' + C.formatG(twice[0].rho) + ' ohm-m). Keep ' +
            'one of the two: a repeat belongs in place of the reading it ' +
            'repeats, not beside it.' });
      }
      if (plan.length) {
        var at = planIndex(plan, r);
        var upTo = at;
        if (at < 0) {
          upTo = 0;
          /* off the plan: what it passed over is every shorter step */
          while (upTo < plan.length && plan[upTo].ab2 < r.ab2) upTo += 1;
        }
        var skipped = [];
        for (var j = 0; j < upTo; j++) {
          if (!read[j] && !reportedSkip[j]) {
            skipped.push(plan[j]);
            reportedSkip[j] = true;
          }
        }
        if (skipped.length) {
          checks.push({ code: 'skipped', level: 'check',
            message: 'Skipped: ' + skipped.map(function (s) {
              return 'AB/2 ' + C.formatG(s.ab2) + ' m at MN ' + C.formatG(s.mn) + ' m';
            }).join(', ') + '. Read ' + (skipped.length > 1 ? 'them' : 'it') +
            ' before the electrodes move on' +
            (skipped.some(function (s, k) {
              var idx = plan.indexOf(s);
              return idx > 0 && sameSpacing(plan[idx - 1].ab2, s.ab2);
            }) ? '; a skipped overlap leaves the MN change with nothing to check it by.'
              : '.') });
        }
        if (at >= 0) read[at] = true;
        else {
          checks.push({ code: 'off_plan', level: 'note',
            message: 'AB/2 ' + C.formatG(r.ab2) + ' m with MN ' + C.formatG(r.mn) +
              ' m is not on the plan.' });
        }
      }
      return checks;
    });
  }

  /** The next step of the plan nobody has read yet, or null.
   * @param {any} session */
  function nextStep(session) {
    var plan = session.plan || [];
    var readings = session.readings || [];
    for (var i = 0; i < plan.length; i++) {
      var step = plan[i];
      var done = readings.some(function (r) {
        return sameSpacing(r.ab2, step.ab2) && sameSpacing(r.mn, step.mn);
      });
      if (!done) {
        return { index: i, ab2: step.ab2, mn: step.mn,
          overlap: i > 0 && sameSpacing(plan[i - 1].ab2, step.ab2) };
      }
    }
    return null;
  }

  /** The readings as the engine takes a sounding.
   * @param {any} session @param {any} [site] */
  function sounding(session, site) {
    var readings = session.readings || [];
    return {
      site: site || {}, sounding_id: session.sounding_id || 'VES 1',
      ab2: readings.map(function (r) { return r.ab2; }),
      mn: readings.map(function (r) { return r.mn; }),
      rho_app: readings.map(function (r) { return r.rho; }),
      array_type: 'schlumberger', instrument: session.instrument || '',
      source: 'VES co-pilot', flags: [],
    };
  }

  /* ------------------------------------------------------------ workbook */

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  /** A device time as the crew's own clock showed it, with its offset from
   * UTC, so the sheet says what the watch said and when that was.
   * @param {string|Date} when */
  function clockText(when) {
    var d = when instanceof Date ? when : new Date(when);
    if (isNaN(d.getTime())) return '';
    var off = -d.getTimezoneOffset();
    var sign = off >= 0 ? '+' : '-';
    off = Math.abs(off);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
      ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds()) +
      ' UTC' + sign + pad2(Math.floor(off / 60)) + ':' + pad2(off % 60);
  }

  /** The standard VES template, as src/groundwater/ingestion/templates.py
   * lays it out (header block in rows 2-8, the table from row 10), with the
   * device clock and the device's GPS fix in row 9 and three columns after
   * the resistivity: the potential and current the resistivity was worked
   * out from, and the time each reading was taken. The extra cells sit
   * where neither reader looks for a value: column C of row 9 is left
   * empty, because a reader that finds no value beside "Instrument" takes
   * the cell beneath it.
   * @param {any} session
   * @param {any} [site] the project's site fields
   * @returns {Array<{name: string, rows: any[][], widths: number[]}>} */
  function workbookSheets(session, site) {
    var s = site || {};
    var readings = session.readings || [];
    var gps = session.gps || null;
    var easting = s.easting, northing = s.northing, zone = '';
    if (gps) {
      var utm = C.geographicToUtm(gps.lat, gps.lon);
      if ((utm.zone === 28 || utm.zone === 29) && utm.hemisphere === 'N') {
        easting = Math.round(utm.easting * 10) / 10;
        northing = Math.round(utm.northing * 10) / 10;
        zone = utm.zone + 'N';
      }
    }
    if (!zone && easting) zone = C.inferZoneForSierraLeone(easting) + 'N';
    var began = session.started_at || (readings.length ? readings[0].at : '');
    var started = began ? new Date(began) : null;
    var date = started && !isNaN(started.getTime())
      ? started.getFullYear() + '-' + pad2(started.getMonth() + 1) + '-' +
        pad2(started.getDate()) : (s.date || '');
    var last = readings.length ? readings[readings.length - 1].at : '';
    var clock = started && !isNaN(started.getTime()) ? 'started ' + clockText(started) +
      (last ? '; last reading ' + clockText(last) : '') : '';
    var fix = gps ? C.pyFixed(gps.lat, 6) + ', ' + C.pyFixed(gps.lon, 6) +
      (gps.accuracy_m !== null && gps.accuracy_m !== undefined
        ? ' (within ' + C.pyFixed(gps.accuracy_m, 0) + ' m)' : '') +
      (gps.at ? ', ' + clockText(gps.at) : '') : 'not taken';
    function val(v) { return v === null || v === undefined ? '' : v; }
    var rows = [
      ['SCHLUMBERGER ARRAY VES FIELD DATA'],
      ['Client', val(s.client), 'Community', val(s.community)],
      ['Project', val(s.project), 'Sounding Number', session.sounding_id || 'VES 1'],
      ['District', val(s.district), 'GPS Coordinate East', val(easting)],
      ['Date', date, 'GPS Coordinate North', val(northing)],
      ['Field Supervisor', val(s.supervisor), 'Elevation (m)', val(s.elevation_m)],
      ['Chiefdom', val(s.chiefdom), 'UTM Zone (28N or 29N)', zone],
      ['Array', 'Schlumberger', 'Instrument', session.instrument || ''],
      ['Device clock', clock, '', '', 'Device GPS (WGS84)', fix],
      ['No.', 'AB/2 (m)', 'MN (m)', 'Apparent Resistivity (ohm-m)',
        'Potential V (mV)', 'Current I (mA)', 'Read at (device clock)'],
    ];
    readings.forEach(function (r, i) {
      rows.push([i + 1, r.ab2, r.mn, r.rho, val(r.v_mV), val(r.i_mA),
        r.at ? clockText(r.at) : '']);
    });
    rows.push([]);
    rows.push(['Notes: MN is the full potential electrode spacing. Written by ' +
      'the VES co-pilot; the apparent resistivity is K x V / I where V and I ' +
      'are given, with K the exact Schlumberger factor.']);
    return [{ name: String(session.sounding_id || 'VES 1').slice(0, 31), rows: rows,
      widths: [22, 16, 22, 28, 22, 34, 28] }];
  }

  /** A session with nothing in it. Its clock starts at the first reading.
   * @param {Date} [now] when it started, if it has */
  function blankSession(now) {
    return {
      sounding_id: 'VES 1', target_m: null, plan: [], readings: [],
      min_potential_mV: DEFAULT_MIN_POTENTIAL_MV, instrument: '',
      started_at: now ? now.toISOString() : null, gps: null,
    };
  }

  /* ================================================================= page */

  /* The preview's state lives here rather than in the project: it is worked
   * out again from the readings whenever it is wanted. */
  var preview = { key: '', status: 'idle', result: null, interp: null,
    resultKey: '', error: '', progress: 0, timer: 0, run: 0 };
  var view = null;

  function app() { return GWT.app; }

  function load() {
    var stored = app().store.get(STATE_KEY);
    return stored && typeof stored === 'object'
      ? JSON.parse(JSON.stringify(stored)) : blankSession();
  }

  function save(session) {
    app().store.set(STATE_KEY, JSON.parse(JSON.stringify(session)));
  }

  function previewKey(session) {
    return JSON.stringify((session.readings || []).map(function (r) {
      return [r.ab2, r.mn, r.rho];
    }));
  }

  /* Start the preview inversion once the readings have settled, replacing
   * any that is running or waiting. */
  function schedulePreview(session) {
    var key = previewKey(session);
    if ((session.readings || []).length < PREVIEW_MIN_READINGS) {
      cancelPreview('idle');
      return;
    }
    /* the same readings again - the page drawn once more - leave the
     * preview as it is: waiting, running, done, failed or stopped */
    if (key === preview.key && preview.status !== 'idle') return;
    /* With no worker - a copy opened from file:// - the fit runs on the page
     * and holds it for some seconds, which after every reading would freeze
     * the form the crew is typing into. There it runs only when asked. */
    if (GWT.engine && GWT.engine.mode() === 'page') {
      clearTimeout(preview.timer);
      preview.run += 1;
      GWT.engine.cancel('previewInvert');
      preview.status = 'manual';
      preview.key = key;
      drawPreview();
      return;
    }
    /* a fit of the readings before this one is stopped now, not when the
     * next starts: its answer would be for a curve that has moved on */
    clearTimeout(preview.timer);
    preview.run += 1;
    if (GWT.engine) GWT.engine.cancel('previewInvert');
    preview.timer = setTimeout(function () { runPreview(load()); }, PREVIEW_DEBOUNCE_MS);
    preview.status = 'waiting';
    preview.key = key;
    drawPreview();
  }

  function runPreview(session) {
    var engine = GWT.engine;
    var run = ++preview.run;
    engine.cancel('previewInvert');
    var cfg = app().config();
    var target = sounding(session);
    var key = preview.key = previewKey(session);
    preview.status = 'running';
    preview.progress = 0;
    preview.error = '';
    drawPreview();
    return engine.previewInvert(target, cfg, {
      onProgress: function (fraction) {
        if (run !== preview.run) return;
        preview.progress = fraction;
        drawPreviewProgress();
      },
    }).then(function (result) {
      if (run !== preview.run) return;
      preview.result = result;
      preview.resultKey = key;
      preview.interp = C.interpretModel(target, result.model, cfg);
      preview.status = 'done';
      drawPreview();
      drawCurve();
    }, function (e) {
      if (run !== preview.run) return;
      if (engine.isCancelled(e)) {
        preview.status = 'stopped';
      } else {
        preview.status = 'failed';
        preview.error = e.message;
      }
      drawPreview();
    });
  }

  /* Stop the preview: the running fit, the one waiting for the readings to
   * settle, or both. The readings are untouched. */
  function cancelPreview(status) {
    clearTimeout(preview.timer);
    preview.run += 1;
    if (GWT.engine) GWT.engine.cancel('previewInvert');
    preview.status = status || 'stopped';
    if (status === 'idle') {
      preview.result = null; preview.interp = null; preview.key = ''; preview.resultKey = '';
    }
    drawPreview();
  }

  /* Another page is drawn: a preview waiting or running is stopped. The
   * engine runs one task at a time, so a fit nobody is looking at would hold
   * the Geophysics page's inversion up behind it. Coming back to the page
   * starts it again from the readings. */
  function leave() {
    view = null;
    if (preview.status === 'waiting' || preview.status === 'running') {
      clearTimeout(preview.timer);
      preview.run += 1;
      if (GWT.engine) GWT.engine.cancel('previewInvert');
      preview.status = 'stopped';
      preview.key = '';
    }
  }

  function el(spec, attrs, children) { return S.el(spec, attrs, children); }

  function field(label, control, hint) { return S.field(label, control, hint); }

  /** The co-pilot's page, for gwt-app.js to draw. */
  function page() {
    var session = load();
    view = {
      plan: el('div'), entry: el('div'), peg: el('div', { 'aria-live': 'polite' }),
      curve: el('div.vc-curve'), preview: el('div', { 'aria-live': 'polite' }),
      readings: el('div'), output: el('div'),
    };
    drawAll();
    /* a reload, or a return to the page, picks the preview up from the
     * readings it was left with */
    schedulePreview(session);
    return [
      el('div.page-head', [
        el('div.crumb', 'Investigation'),
        el('h1', 'VES co-pilot'),
        el('p.lead', 'A Schlumberger sounding checked at the peg, reading by ' +
          'reading, while the crew can still re-measure. It writes the ' +
          'standard VES workbook, which the Geophysics page reads.'),
      ]),
      el('div.callout.callout-info', el('p', C.phrase('ves_copilot.browser_only'))),
      view.plan, view.entry, view.peg, view.curve, view.preview, view.readings,
      view.output,
    ];
  }

  function drawAll() {
    drawPlan(); drawEntry(); drawPeg(); drawCurve(); drawPreview();
    drawReadings(); drawOutput();
  }

  function swap(host, nodes) {
    if (!host) return;
    S.clear(host);
    S.append(host, nodes);
  }

  /* ---- before the survey: target depth, and the plan it gives */
  function drawPlan() {
    var session = load();
    var cfg = app().config();
    var factor = doiFactor(cfg);
    var target = { value: session.target_m };
    var box = /** @type {HTMLTextAreaElement} */ (el('textarea.input.vc-plan', {
      rows: 8, spellcheck: false, 'aria-label': 'AB/2 and MN, one pair a line',
    }));
    box.value = planText(session.plan || []);
    var proposal = session.target_m > 0 ? propose(session.target_m, cfg) : null;
    swap(view && view.plan, S.card('Before the survey', [
      el('p.muted', 'Enter the depth the sounding has to see. A Schlumberger ' +
        'sounding resolves to about ' + C.formatG(factor) + ' of its largest ' +
        'AB/2 (the rule the interpretation uses), so the line is set long ' +
        'enough before any cable is unrolled.'),
      el('div.grid.grid-2', [
        field('Target depth (m)', S.numberInput(session.target_m, function (v) {
          target.value = v;
        }, { min: 1, step: 'any', 'data-vc': 'target' })),
        field('Sounding number', S.textInput(session.sounding_id, function (v) {
          var s = load(); s.sounding_id = String(v || '').trim() || 'VES 1'; save(s);
          drawOutput();
        }, { 'data-vc': 'sounding-id' })),
      ]),
      el('div.btn-row', [
        S.button('Propose the spacings', function () {
          var s = load();
          if (!(target.value > 0)) {
            S.toast('Enter the target depth in metres first.', 'warn');
            return;
          }
          var p = propose(target.value, app().config());
          s.target_m = target.value;
          s.plan = p.steps;
          save(s);
          drawAll();
          schedulePreview(s);
        }, { variant: 'primary' }),
      ]),
      proposal ? el('p', { 'data-vc': 'proposal' }, 'For ' +
        C.formatG(proposal.target_m) + ' m the line runs to AB/2 = ' +
        C.formatG(proposal.max_ab2) + ' m: ' + C.formatG(proposal.line_m) +
        ' m of straight, open ground from one current electrode to the other, ' +
        'centred on the peg, and it resolves to about ' +
        C.formatG(proposal.investigation_m) + ' m.' +
        (proposal.capped ? ' That is as long as the series goes; a deeper ' +
          'target needs a longer line than this plan offers.' : '')) : null,
      field('AB/2 and MN (m), one pair a line; an AB/2 written twice is an MN change',
        box, 'Edit the plan to suit the ground; the checks follow it.'),
      el('div.btn-row', [
        S.button('Use this plan', function () {
          var parsed = parsePlan(box.value);
          if (parsed.bad.length) {
            S.toast('Line ' + S.joinList(parsed.bad.map(String)) + ' of the plan ' +
              'is not "AB/2 MN" with MN/2 under AB/2.', 'error');
            return;
          }
          var s = load(); s.plan = parsed.steps; save(s);
          drawAll();
        }, { variant: 'ghost' }),
      ]),
    ]));
  }

  /* ---- at each reading */
  var replacing = -1;

  function drawEntry() {
    var session = load();
    var next = nextStep(session);
    var editing = replacing >= 0 && replacing < session.readings.length
      ? session.readings[replacing] : null;
    if (!editing) replacing = -1;
    var form = {
      ab2: editing ? editing.ab2 : (next ? next.ab2 : null),
      mn: editing ? editing.mn : (next ? next.mn : null),
      v: null, i: null, rho: null,
    };
    var minV = session.min_potential_mV > 0 ? session.min_potential_mV
      : DEFAULT_MIN_POTENTIAL_MV;
    function num(key, label, attrs) {
      return field(label, S.numberInput(form[key], function (v) { form[key] = v; },
        Object.assign({ step: 'any', 'data-vc': key }, attrs || {})));
    }
    swap(view && view.entry, S.card(editing
      ? 'Re-measure reading ' + (replacing + 1) : 'At the peg', [
      next && !editing ? el('p', { 'data-vc': 'next' }, [
        el('strong', 'Next: AB/2 ' + C.formatG(next.ab2) + ' m, MN ' +
          C.formatG(next.mn) + ' m.'),
        next.overlap ? ' MN change: read this AB/2 again with the new MN ' +
          'before the current electrodes move.' : '',
      ]) : null,
      editing ? el('p.muted', 'This reading replaces reading ' + (replacing + 1) +
        ' (' + C.formatG(editing.rho) + ' ohm-m) where it stands.') : null,
      el('div.grid.grid-2', [
        num('ab2', 'AB/2 (m)', { min: 0 }),
        num('mn', 'MN (m), full spacing', { min: 0 }),
        num('v', 'Potential V (mV)'),
        num('i', 'Current I (mA)', { min: 0 }),
      ]),
      el('p.muted', 'Or, where the instrument shows it, the apparent ' +
        'resistivity itself:'),
      num('rho', 'Apparent resistivity (ohm-m)', { min: 0 }),
      el('div.btn-row', [
        S.button(editing ? 'Replace the reading' : 'Add the reading', function () {
          addReading(form);
        }, { variant: 'primary' }),
        editing ? S.button('Cancel', function () { replacing = -1; drawEntry(); },
          { variant: 'ghost' }) : null,
      ]),
      el('details', [
        el('summary', 'Instrument'),
        el('div.grid.grid-2', [
          field('Smallest potential it reads reliably (mV)',
            S.numberInput(minV, function (v) {
              var s = load();
              s.min_potential_mV = v > 0 ? v : DEFAULT_MIN_POTENTIAL_MV;
              save(s); drawPeg(); drawReadings();
            }, { min: 0, step: 'any', 'data-vc': 'min-potential' }),
            'Default ' + C.formatG(DEFAULT_MIN_POTENTIAL_MV) + ' mV: below about ' +
            'a millivolt, self-potential drift and telluric noise are a large ' +
            'part of a single reading. Set it from the instrument manual.'),
          field('Instrument', S.textInput(session.instrument, function (v) {
            var s = load(); s.instrument = String(v || '').trim(); save(s);
          }, { placeholder: 'Syscal Junior', 'data-vc': 'instrument' })),
        ]),
      ]),
    ]));
  }

  /** Take the reading the form holds: work out its resistivity, add it (or
   * put it in place of the one being re-measured) and run the checks.
   * @param {{ab2: any, mn: any, v: any, i: any, rho: any}} form
   * @param {Date} [now] */
  function addReading(form, now) {
    var ab2 = Number(form.ab2), mn = Number(form.mn);
    if (!(ab2 > 0) || !(mn > 0) || !(mn / 2 < ab2)) {
      S.toast('AB/2 and MN are needed, with MN/2 smaller than AB/2.', 'error');
      return null;
    }
    var hasVI = S.isNum(form.v) && S.isNum(form.i);
    /* a potential typed beside a resistivity the instrument showed is kept,
     * and checked against the instrument's floor, like any other */
    var hasV = S.isNum(form.v), hasI = S.isNum(form.i);
    var rho;
    if (hasVI) {
      if (!(form.i > 0)) {
        S.toast('The current has to be more than zero.', 'error');
        return null;
      }
      rho = rhoFromPotential(ab2, mn, Math.abs(form.v), form.i);
      /* both typed: V and I are what was read, so they decide, but an
       * instrument that disagrees has its own spacings set differently */
      if (S.isNum(form.rho) && form.rho > 0 && Math.abs(form.rho / rho - 1) > 0.05) {
        S.toast('The resistivity typed, ' + C.formatG(form.rho) + ' ohm-m, is not ' +
          'K x V / I = ' + C.formatG(Math.round(rho * 1000) / 1000) + ' ohm-m; the ' +
          'second is kept. Check the AB/2 and MN set on the instrument.', 'warn');
      }
    } else if (S.isNum(form.rho) && form.rho > 0) {
      rho = Number(form.rho);
    } else {
      S.toast('Enter V and I, or the apparent resistivity.', 'error');
      return null;
    }
    var reading = { ab2: ab2, mn: mn, v_mV: hasV ? Number(form.v) : null,
      i_mA: hasI ? Number(form.i) : null,
      rho: Math.round(rho * 1000) / 1000,
      at: (now || new Date()).toISOString() };
    var session = load();
    if (!session.started_at) session.started_at = reading.at;
    var index;
    if (replacing >= 0 && replacing < session.readings.length) {
      session.readings[replacing] = reading;
      index = replacing;
    } else {
      session.readings.push(reading);
      index = session.readings.length - 1;
    }
    replacing = -1;
    save(session);
    drawEntry(); drawPeg(index); drawCurve(); drawReadings(); drawOutput();
    schedulePreview(session);
    return { index: index, checks: review(session)[index] };
  }

  function tone(level) {
    return level === 'remeasure' ? 'bad' : level === 'check' ? 'warn' : 'info';
  }

  /* What the last reading raised, said where the crew looks. */
  function drawPeg(index) {
    var session = load();
    var all = review(session);
    var at = index === undefined ? session.readings.length - 1 : index;
    if (at < 0 || !all[at]) { swap(view && view.peg, null); return; }
    var r = session.readings[at];
    var checks = all[at];
    var bad = checks.some(function (c) { return c.level === 'remeasure'; });
    swap(view && view.peg, el('div.callout.callout-' + (bad ? 'bad'
      : checks.some(function (c) { return c.level === 'check'; }) ? 'warn' : 'ok'),
    { 'data-vc': 'peg' }, [
      el('p', el('strong', 'Reading ' + (at + 1) + ': AB/2 ' + C.formatG(r.ab2) +
        ' m, MN ' + C.formatG(r.mn) + ' m, ' + C.formatG(r.rho) + ' ohm-m.')),
      checks.length ? el('ul', checks.map(function (c) {
        return el('li', { 'data-check': c.code }, c.message);
      })) : el('p', 'No check raised. Move on to the next spacing.'),
      bad ? el('div.btn-row', S.button('Re-measure this reading', function () {
        replacing = at; drawEntry();
      })) : null,
    ]));
  }

  /* ---- the curve: the readings so far, log-log, and the preview's model */
  function drawCurve() {
    var charts = GWT.charts;
    if (!view || !charts) return;
    var session = load();
    var readings = session.readings || [];
    if (!readings.length) {
      swap(view.curve, S.card('Sounding curve', S.empty('The curve starts with ' +
        'the first reading.')));
      return;
    }
    var all = review(session);
    var calc = preview.result && preview.resultKey === previewKey(session)
      ? preview.result : null;
    var xs = readings.map(function (r) { return r.ab2; });
    var ys = readings.map(function (r) { return r.rho; });
    if (calc) ys = ys.concat(calc.rho_calc);
    var plan = session.plan || [];
    if (plan.length) xs = xs.concat([plan[plan.length - 1].ab2]);
    var f = charts.frame({
      width: 720, height: 400, title: 'Sounding curve - ' + (session.sounding_id || 'VES'),
      xLabel: 'AB/2 (m)', yLabel: 'Apparent resistivity (ohm-m)', xLog: true, yLog: true,
      xDomain: charts.padDomain(xs, true), yDomain: charts.padDomain(ys, true),
    });
    var p = f.palette;
    if (calc) {
      f.plot.appendChild(charts.polyline(calc.ab2.map(function (x, i) {
        return [f.fx(x), f.fy(calc.rho_calc[i])];
      }), { stroke: p.secondary, 'stroke-width': 2, 'stroke-dasharray': '6 4' }));
    }
    /* each MN segment joined in field order, so a segment shift reads as one */
    var segments = {};
    readings.forEach(function (r) {
      (segments[r.mn] = segments[r.mn] || []).push(r);
    });
    Object.keys(segments).forEach(function (mn) {
      var pts = segments[mn].slice().sort(function (a, b) { return a.ab2 - b.ab2; });
      f.plot.appendChild(charts.polyline(pts.map(function (r) {
        return [f.fx(r.ab2), f.fy(r.rho)];
      }), { stroke: p.accentSoft, 'stroke-width': 1.2 }));
    });
    var points = [];
    var flagged = false;
    readings.forEach(function (r, i) {
      var bad = all[i].some(function (c) { return c.level === 'remeasure'; });
      if (bad) flagged = true;
      var px = f.fx(r.ab2), py = f.fy(r.rho);
      var mark = charts.marker(px, py, bad ? 'triangle' : 'circle',
        bad ? p.critical : p.accent, p.surface, bad ? 6 : 4.5);
      mark.setAttribute('data-reading', String(i + 1));
      f.plot.appendChild(mark);
      points.push({ px: px, py: py });
    });
    var entries = [{ label: 'Reading', kind: 'circle', colour: p.accent }];
    if (flagged) entries.push({ label: 'Re-measure', kind: 'triangle', colour: p.critical });
    if (calc) entries.push({ label: 'Preview model', kind: 'line', colour: p.secondary, dash: '6 4' });
    charts.legend(f, entries, { avoid: points });
    swap(view.curve, S.card('Sounding curve', f.svg));
  }

  function drawPreviewProgress() {
    if (!view) return;
    var bar = view.preview.querySelector('progress');
    if (bar) /** @type {HTMLProgressElement} */ (bar).value = preview.progress;
  }

  /* ---- the preview inversion */
  function drawPreview() {
    if (!view) return;
    var session = load();
    var n = (session.readings || []).length;
    var nodes = [el('p.muted', 'A preview, not the survey\'s result: a fit ' +
      'of the readings so far, run again after each reading, so the team ' +
      'can see whether basement is in view while the line can still be ' +
      'extended. The Geophysics page interprets the finished workbook.')];
    var status = preview.status;
    if (n < PREVIEW_MIN_READINGS) {
      nodes.push(el('p', { 'data-vc': 'preview-status' }, 'The preview starts at ' +
        PREVIEW_MIN_READINGS + ' readings (' + n + ' so far).'));
    } else if (status === 'waiting' || status === 'running') {
      nodes.push(el('p', { 'data-vc': 'preview-status' }, status === 'waiting'
        ? 'Preview about to start…' : 'Fitting a preview model…'));
      if (status === 'running') {
        nodes.push(el('progress', { max: 1, value: preview.progress }));
      }
      nodes.push(el('div.btn-row', S.button('Stop the preview', function () {
        cancelPreview('stopped');
      }, { variant: 'ghost' })));
    } else if (status === 'manual') {
      nodes.push(el('p', { 'data-vc': 'preview-status' }, 'This copy of the app ' +
        'has no background worker (' + GWT.engine.unavailable() + '), so the fit ' +
        'would hold the page for some seconds after every reading. Run it when ' +
        'there is a pause.'));
      nodes.push(el('div.btn-row', S.button('Run the preview now', function () {
        runPreview(load());
      })));
    } else if (status === 'stopped') {
      nodes.push(el('p', { 'data-vc': 'preview-status' }, 'Preview stopped. The ' +
        'next reading starts it again.'));
      nodes.push(el('div.btn-row', S.button('Run the preview now', function () {
        runPreview(load());
      })));
    } else if (status === 'failed') {
      nodes.push(el('p', { 'data-vc': 'preview-status' }, 'No preview: ' +
        preview.error));
    }
    if (preview.interp && preview.resultKey === previewKey(session)) {
      nodes.push(previewSummary(session, preview.result, preview.interp));
    } else if (preview.interp && status !== 'idle') {
      nodes.push(el('p.muted', 'The last preview was of fewer readings.'));
    }
    swap(view.preview, S.card('Preview inversion', nodes, { className: 'vc-preview' }));
  }

  /** What the preview model says about basement, in a sentence the team
   * can act on at the peg. */
  function previewSummary(session, result, interp) {
    var doi = interp.investigation_depth_m;
    var target = session.target_m;
    var basement = interp.depth_to_basement_m;
    var line;
    if (basement !== null && basement !== undefined) {
      line = 'Preview: basement at about ' + C.fmtNum(basement) + ' m, within ' +
        'the ' + C.fmtNum(doi) + ' m this line resolves so far.';
    } else {
      line = 'Preview: no basement within the ' + C.fmtNum(doi) + ' m this line ' +
        'resolves so far.' + (target > 0 && doi < target
        ? ' Seeing to the ' + C.fmtNum(target) + ' m target needs AB/2 of ' +
          C.fmtNum(target / doiFactor(app().config())) + ' m.'
        : ' Extending the line looks deeper; at ' + C.formatG(doiFactor(app().config())) +
          ' of AB/2, every doubling of AB/2 doubles the depth it sees.');
    }
    var layers = interp.layers.map(function (layer) {
      return [layer.number, C.fmtNum(layer.rho),
        layer.thickness_m === null ? 'half-space' : C.fmtNum(layer.thickness_m),
        C.fmtNum(layer.top_m), layer.unit];
    });
    return el('div', { 'data-vc': 'preview' }, [
      el('p', el('strong', line)),
      el('p.muted', result.model.n_layers + ' layers, fit error ' +
        C.pyFixed(result.fit_error_percent, 1) + ' percent.'),
      /* the engine's own caveats on the model: a poor fit, an open base */
      interp.flags.length ? el('ul.muted', interp.flags.map(function (flag) {
        return el('li', flag.message);
      })) : null,
      S.table(['Layer', 'Resistivity (ohm-m)', 'Thickness (m)', 'Top (m)', 'Reads as'],
        layers),
    ]);
  }

  /* ---- the readings so far, each with what it raised */
  function drawReadings() {
    var session = load();
    var all = review(session);
    var rows = session.readings.map(function (r, i) {
      return { i: i, r: r, checks: all[i] };
    });
    swap(view && view.readings, S.card('Readings', [
      S.table([
        { key: function (row) { return row.i + 1; }, label: 'No.' },
        { key: function (row) { return C.formatG(row.r.ab2); }, label: 'AB/2 (m)', align: 'right' },
        { key: function (row) { return C.formatG(row.r.mn); }, label: 'MN (m)', align: 'right' },
        { key: function (row) { return row.r.v_mV === null ? '' : C.formatG(row.r.v_mV); },
          label: 'V (mV)', align: 'right' },
        { key: function (row) { return row.r.i_mA === null ? '' : C.formatG(row.r.i_mA); },
          label: 'I (mA)', align: 'right' },
        { key: function (row) { return C.formatG(row.r.rho); }, label: 'ohm-m', align: 'right' },
        { key: function (row) {
          return row.checks.length ? row.checks.map(function (c) {
            return S.badge(c.code.replace(/_/g, ' '), tone(c.level));
          }) : S.badge('ok', 'ok');
        }, label: 'At the peg' },
        { key: function (row) {
          return el('div.btn-row', [
            S.button('Re-measure', function () { replacing = row.i; drawEntry(); },
              { variant: 'ghost' }),
            S.button('Delete', function () {
              var s = load(); s.readings.splice(row.i, 1); save(s);
              replacing = -1;
              drawAll(); schedulePreview(s);
            }, { variant: 'ghost' }),
          ]);
        }, label: '' },
      ], rows, { emptyText: 'No readings yet.' }),
    ]));
  }

  /* ---- the workbook */
  function drawOutput() {
    var session = load();
    var gps = session.gps;
    swap(view && view.output, S.card('The workbook', [
      el('p.muted', 'The standard VES template, with the device clock and, if ' +
        'you allow it, the device GPS position in the header. Upload it on the ' +
        'Geophysics page, or keep it with the field sheets.'),
      el('p', { 'data-vc': 'gps' }, gps
        ? 'Position: ' + C.pyFixed(gps.lat, 6) + ', ' + C.pyFixed(gps.lon, 6) +
          (gps.accuracy_m !== null ? ', within ' + C.pyFixed(gps.accuracy_m, 0) + ' m' : '') + '.'
        : 'No position taken yet. Stand at the centre peg to take it.'),
      el('div.btn-row', [
        S.button('Take the GPS position', function () { takePosition(); },
          { variant: 'ghost' }),
        S.button('Download the workbook', function () { downloadWorkbook(); },
          { variant: 'primary', disabled: !session.readings.length }),
        S.button('Start a new sounding', function () {
          if (session.readings.length && !global.confirm('Clear these ' +
            session.readings.length + ' readings? Download the workbook first ' +
            'if it is still wanted.')) return;
          cancelPreview('idle');
          var fresh = blankSession();
          fresh.instrument = session.instrument;
          fresh.min_potential_mV = session.min_potential_mV;
          save(fresh);
          drawAll();
        }, { variant: 'ghost' }),
      ]),
    ]));
  }

  /* The device's own fix, asked for only when the button is pressed: the
   * browser asks the user's permission the first time. */
  function takePosition() {
    var geo = global.navigator && global.navigator.geolocation;
    if (!geo) {
      S.toast('This browser gives no position.', 'warn');
      return Promise.resolve(null);
    }
    return new Promise(function (resolve) {
      geo.getCurrentPosition(function (pos) {
        var s = load();
        s.gps = { lat: pos.coords.latitude, lon: pos.coords.longitude,
          accuracy_m: isFinite(pos.coords.accuracy) ? pos.coords.accuracy : null,
          at: new Date(pos.timestamp || Date.now()).toISOString() };
        save(s);
        drawOutput();
        resolve(s.gps);
      }, function (e) {
        S.toast('No position: ' + (e && e.message ? e.message : 'refused') + '.', 'warn');
        resolve(null);
      }, { enableHighAccuracy: true, timeout: 30000, maximumAge: 60000 });
    });
  }

  async function downloadWorkbook() {
    var session = load();
    var bytes = await S.writeXlsx(workbookSheets(session, app().store.get('site')));
    var name = S.slug(session.sounding_id || 'ves') + '_ves_copilot.xlsx';
    S.download(name, new Blob([bytes]));
    return bytes;
  }

  GWT.vesCopilot = {
    STATE_KEY: STATE_KEY, AB2_SERIES: AB2_SERIES, MN_SERIES: MN_SERIES,
    DEFAULT_MIN_POTENTIAL_MV: DEFAULT_MIN_POTENTIAL_MV,
    PREVIEW_MIN_READINGS: PREVIEW_MIN_READINGS,
    propose: propose, planText: planText, parsePlan: parsePlan,
    rhoFromPotential: rhoFromPotential, review: review, nextStep: nextStep,
    sounding: sounding, workbookSheets: workbookSheets, blankSession: blankSession,
    page: page, leave: leave, addReading: addReading, cancelPreview: cancelPreview,
    runPreview: function () { return runPreview(load()); },
    preview: function () { return preview; },
    takePosition: takePosition, downloadWorkbook: downloadWorkbook,
  };
  (GWT.loadedBundles || (GWT.loadedBundles = {})).vesCopilot = true;
}(typeof window !== 'undefined' ? window : globalThis));

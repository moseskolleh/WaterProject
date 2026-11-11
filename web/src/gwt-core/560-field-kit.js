
  /* ============================================================== field kit
   * groundwater/field_kit.py: the printed sheets and quick cards for a crew
   * with no device (PLAN.md step 2.5), as plain data both engines build the
   * same way; gwt-docx.js fieldKit lays it out. The schedules are the
   * co-pilots' own, written once in src/groundwater/data/field.yaml and
   * emitted as GWT.data.field, which both co-pilots read through
   * fieldSchedules. The sheet code's format is in field_kit.py's notes:
   *
   *   GWT-FK/1|pumping|<project>|<borehole>
   */

  var FIELD_KIT_FORMAT = 'GWT-FK/1';
  var FIELD_KIT_PUMPING = 'pumping';
  /* written out rather than \s, and the only whitespace a field or a code is
   * trimmed of: String.trim() and Python's str.strip() part over a
   * byte-order mark, U+0085 and U+001C to U+001F, which gave the two engines
   * different codes for the same name */
  var FIELD_SPACE = /[ \t\n\r\f\v]+/g;
  var FIELD_ENDS = /^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$/g;

  /** data/field.yaml, shared: read, never changed.
   * @returns {Rec} */
  function fieldSchedules() {
    var field = (GWT.data || {}).field;
    if (!field) {
      throw new Error('gwt-data.js is not loaded, or is stale: it carries the ' +
        'field schedules (src/groundwater/data/field.yaml)');
    }
    return field;
  }

  /** The scheduled reading minutes up to and including untilMin: the
   * log-spaced list, then every late_every_min after its last minute.
   * @param {number} untilMin
   * @returns {number[]} */
  function readingMinutes(untilMin) {
    var pumping = fieldSchedules().pumping;
    var schedule = pumping.schedule_min;
    var out = schedule.filter(function (/** @type {number} */ m) {
      return m <= untilMin + 1e-9;
    });
    for (var late = schedule[schedule.length - 1] + pumping.late_every_min;
      late <= untilMin + 1e-9; late += pumping.late_every_min) {
      out.push(late);
    }
    return out;
  }

  /* the scheduled minute a test of `minutes` reads last */
  function firstReadingAtOrAfter(minutes) {
    var pumping = fieldSchedules().pumping;
    var schedule = pumping.schedule_min;
    for (var i = 0; i < schedule.length; i++) {
      if (schedule[i] >= minutes - 1e-9) return schedule[i];
    }
    var last = schedule[schedule.length - 1], every = pumping.late_every_min;
    return last + every * Math.ceil((minutes - last) / every - 1e-9);
  }

  /** Schafer's casing-storage time at the pumping co-pilot's cautious
   * transmissivity range, through Logan's factor (field_kit.py
   * cautious_storage). low_t_min is the longer time, the one the advice
   * rests on.
   * @param {PumpingConfig} [config]
   * @returns {Rec} */
  function cautiousStorage(config) {
    var cfg = config || defaultConfig().pumping;
    var pumping = fieldSchedules().pumping;
    var tLow = pumping.cautious_t_m2_per_day[0], tHigh = pumping.cautious_t_m2_per_day[1];
    var storage = function (/** @type {number} */ t) {
      return casingStorageMin(t / (pumping.logan_factor * 24), cfg);
    };
    return {
      casing_in: cfg.casing_diameter_in, riser_in: cfg.riser_diameter_in,
      t_low: tLow, t_high: tHigh, low_t_min: storage(tLow), high_t_min: storage(tHigh),
    };
  }

  /** The AB/2 series and the MN changes that reach targetDepth: the VES
   * co-pilot's proposal (field_kit.py ves_survey_plan). MN starts at the
   * widest spacing min_ab_per_mn allows at the first AB and is widened when
   * AB passes max_ab_per_mn times it; at each change the last AB/2 is read
   * again with the new MN.
   * @param {number} targetDepth metres
   * @param {Config} [config]
   * @returns {Rec} */
  function vesSurveyPlan(targetDepth, config) {
    var ves = (config || defaultConfig()).ves;
    var field = fieldSchedules().ves;
    var seriesAll = field.ab2_series_m, mnSeries = field.mn_series_m;
    /* the engine's own rule decides, not target / factor: 30 / 0.3 is
     * 100.00000000000001, which would ask for the next spacing */
    var reaches = function (/** @type {number} */ ab2) {
      return depthOfInvestigation(ab2, ves) >= targetDepth;
    };
    var capped = !reaches(seriesAll[seriesAll.length - 1]);
    /** @type {number[]} */
    var series = [];
    for (var i = 0; i < seriesAll.length; i++) {
      series.push(seriesAll[i]);
      if (reaches(seriesAll[i])) break;
    }
    var widest = function (/** @type {number} */ ab2) {
      /** @type {number|null} */
      var best = null;
      mnSeries.forEach(function (/** @type {number} */ mn) {
        if (mn * field.min_ab_per_mn <= 2 * ab2) best = mn;
      });
      return best === null ? mnSeries[0] : best;
    };
    /** @type {Array<{ab2: number, mn: number}>} */
    var steps = [];
    var mn = widest(series[0]);
    series.forEach(function (ab2, k) {
      if (k > 0 && 2 * ab2 > field.max_ab_per_mn * mn) {
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
      target_m: targetDepth, factor: ves.depth_of_investigation_factor, max_ab2: maxAb2,
      investigation_m: depthOfInvestigation(maxAb2, ves), line_m: 2 * maxAb2,
      capped: capped, steps: steps,
    };
  }

  /* standard gravity, m/s2, in the V-notch equation */
  var GRAVITY = 9.80665;

  /** @param {*} v @returns {v is number} */
  function positiveReading(v) { return isFiniteNum(v) && v > 0; }

  /** The airlift yield of a water strike, in litres per second: the drilling
   * log co-pilot's estimate (field_kit.py airlift_yield). method is 'bucket'
   * (a container of volume_l litres timed filling, timings_s), 'vnotch' (the
   * head over a V-notch plate, head_mm, by the Kindsvater-Shen equation with
   * data/field.yaml's angle and coefficient) or 'none' (not measured, for
   * the reason given). Returns {method, q_l_per_s, basis, flags}; a reading
   * that cannot give a yield throws.
   * @param {string} method
   * @param {{volume_l?: number|null, timings_s?: number[]|null,
   *   head_mm?: number|null, reason?: string}} [options]
   * @returns {{method: string, q_l_per_s: number|null, basis: string,
   *   flags: Array<{code: string, message: string}>}} */
  function airliftYield(method, options) {
    var opts = options || {};
    /** @type {Array<{code: string, message: string}>} */
    var flags = [];
    var q, basis;
    if (method === 'bucket') {
      var times = (opts.timings_s || []).map(Number);
      var volume = opts.volume_l;
      /* each reading a finite number above zero, as field_kit.py asks: an
       * infinite time gave a yield of zero */
      if (!positiveReading(volume) || !times.length || !times.every(positiveReading)) {
        throw new Error('a timed container needs its volume and at least one ' +
          'time, each more than zero');
      }
      var sum = 0;
      times.forEach(function (t) { sum += t; });
      var mean = sum / times.length;
      q = volume / mean;
      basis = phrase('drilling_copilot.airlift_bucket',
        { volume: volume, mean: mean, n: times.length });
    } else if (method === 'vnotch') {
      var head = opts.head_mm;
      if (!positiveReading(head)) {
        throw new Error('a V-notch reading needs the head over the notch, more than zero');
      }
      var drilling = fieldSchedules().drilling;
      var angle = drilling.vnotch_angle_deg, ce = drilling.vnotch_discharge_coefficient;
      var low = drilling.vnotch_head_range_mm[0], high = drilling.vnotch_head_range_mm[1];
      var h = head / 1000;
      q = ce * 8 / 15 * Math.sqrt(2 * GRAVITY) *
        Math.tan((angle / 2) * (Math.PI / 180)) * Math.pow(h, 2.5) * 1000;
      basis = phrase('drilling_copilot.airlift_vnotch',
        { angle: angle, head: head, ce: ce, half: angle / 2 });
      if (!(low <= head && head <= high)) {
        flags.push({ code: 'vnotch_head_outside', message: phrase(
          'drilling_copilot.vnotch_outside', { head: head, low: low, high: high }) });
      }
    } else if (method === 'none') {
      var text = fieldText(opts.reason);
      if (!text) throw new Error('an airlift not measured needs the reason');
      return { method: 'none', q_l_per_s: null,
        basis: phrase('drilling_copilot.airlift_not_measured', { reason: text }),
        flags: flags };
    } else {
      throw new Error('unknown airlift method ' + JSON.stringify(method));
    }
    return { method: method, q_l_per_s: q, basis: basis, flags: flags };
  }

  function fieldText(text) {
    return String(text === null || text === undefined ? '' : text)
      .replace(FIELD_SPACE, ' ').replace(FIELD_ENDS, '');
  }

  /** The text a sheet's QR code carries (field_kit.py's notes say how).
   * @param {string} project
   * @param {string} borehole
   * @param {string} [sheet]
   * @returns {string} */
  function fieldKitPayload(project, borehole, sheet) {
    var escape = function (/** @type {*} */ text) {
      return fieldText(text).replace(/%/g, '%25').replace(/\|/g, '%7C');
    };
    return [FIELD_KIT_FORMAT, sheet || FIELD_KIT_PUMPING, escape(project),
      escape(borehole)].join('|');
  }

  /** The fields of a sheet code, or null for text that is not one. Only
   * version 1 is read.
   * @param {string} text
   * @returns {{format: string, sheet: string, project: string, borehole: string}|null} */
  function parseFieldKitPayload(text) {
    var parts = String(text).replace(FIELD_ENDS, '').split('|');
    if (parts.length !== 4 || parts[0] !== FIELD_KIT_FORMAT || !parts[1]) return null;
    var unescape = function (/** @type {string} */ value) {
      return value.replace(/%(25|7C)/g, function (_, code) { return code === '25' ? '%' : '|'; });
    };
    return { format: parts[0], sheet: parts[1], project: unescape(parts[2]),
      borehole: unescape(parts[3]) };
  }

  /** The project as a sheet code names it: its reference, else its name.
   * @param {Rec} site
   * @returns {string} */
  function projectIdentifier(site) {
    return fieldText(site.project_ref) || fieldText(site.project);
  }

  function gText(value) { return renderText('{v:g}', { v: value }); }

  /* ingestion/templates.py PUMPING_HEADER, PUMPING_COLUMNS and
   * RECOVERY_COLUMNS: the labels the printed sheet shares with the workbook */
  var FIELD_PUMPING_HEADER = ['Community', 'Date', 'Client', 'Length of each step (min)',
    'Test conducted by', 'Start time', 'Borehole Ref. No.', 'Depth of Borehole (m)',
    'Static water level (m)', 'Pump setting (m)', 'Test type (step or constant)',
    'District', 'GPS Coordinate East', 'GPS Coordinate North', 'UTM Zone (28N or 29N)',
    'Elevation (m)'];
  var FIELD_PUMPING_COLUMNS = ['Time (min)', 'Water Level (m)', 'Drawdown (m)'];
  var FIELD_RECOVERY_COLUMNS = ['Time (min)', 'Water Level (m)', 'Recovery (m)'];

  function fieldPumpingBlocks(minutes, planned) {
    var last = Math.max(240, Math.ceil(planned));
    var headings = ['Constant discharge 0-60 min', 'Constant discharge 61-120 min',
      'Constant discharge 121-180 min', 'Constant discharge 181-' + last + ' min'];
    /** @type {number[][]} */
    var groups = [[], [], [], []];
    /* the co-pilot's hourly blocks: a reading belongs to the block whose
     * heading starts at or before it */
    minutes.forEach(function (/** @type {number} */ m) {
      groups[m < 61 ? 0 : m < 121 ? 1 : m < 181 ? 2 : 3].push(m);
    });
    /** @type {Rec[]} */
    var out = [];
    groups.forEach(function (group, i) {
      if (!group.length) return;
      out.push({ caption: headings[i], header: FIELD_PUMPING_COLUMNS.slice(),
        rows: group.map(function (m) { return [gText(m), '', '']; }) });
    });
    return out;
  }

  function fieldSheet(site, project, borehole, plan, notes) {
    var payload = fieldKitPayload(project, borehole);
    /** @type {Rec} */
    var values = {
      'Community': site.community, 'Client': site.client,
      'Test conducted by': site.supervisor, 'Borehole Ref. No.': borehole,
      'Test type (step or constant)': 'constant', 'District': site.district,
    };
    var minutes = readingMinutes(plan.planned_min);
    var steps = [1, 2, 3, 4];
    return {
      borehole: borehole,
      payload: payload,
      title: phrase('field_kit.sheet_title', { borehole: borehole }),
      code: phrase('field_kit.sheet_code', { payload: payload }),
      warning: project ? '' : phrase('field_kit.no_project'),
      header: FIELD_PUMPING_HEADER.map(function (label) {
        return [label, fieldText(own(values, label) ? values[label] : '')];
      }),
      notes: notes,
      discharge_note: phrase('field_kit.discharge'),
      discharge: {
        caption: 'Discharge per step (m3/h)',
        header: steps.map(function (i) { return 'Step ' + i + ' Q'; }),
        rows: [['', '', '', '']],
      },
      bucket: {
        caption: 'Bucket timings',
        header: ['Step', 'Bucket (L)', 'Timing 1 (s)', 'Timing 2 (s)', 'Timing 3 (s)',
          'Q (m3/h)'],
        rows: steps.map(function (i) { return ['Step ' + i, '', '', '', '', '']; }),
      },
      transcribe: phrase('field_kit.transcribe'),
      blocks: fieldPumpingBlocks(minutes, plan.planned_min),
      recovery: { caption: 'Recovery', header: FIELD_RECOVERY_COLUMNS.slice(),
        rows: minutes.map(function (m) { return [gText(m), '', '']; }) },
    };
  }

  function fieldPlan(cfg) {
    var storage = cautiousStorage(cfg);
    var low = storage.low_t_min;
    var constant = Math.max(cfg.min_constant_test_min, low || 0);
    return {
      storage: storage, constant_min: constant,
      first_step_min: Math.max(cfg.min_step_length_min, low || 0),
      step_min: cfg.min_step_length_min,
      planned_min: firstReadingAtOrAfter(constant),
    };
  }

  /* The sheet's sentences, by name, in the order the sheet prints them, as
   * [key, text] pairs. */
  function fieldPumpingNotes(plan, cfg) {
    var storage = plan.storage;
    var pumping = fieldSchedules().pumping;
    /** @type {string[][]} */
    var notes = [];
    if (storage.low_t_min !== null && storage.high_t_min !== null) {
      notes.push(['storage', phrase('field_kit.storage', {
        casing: storage.casing_in, riser: storage.riser_in, low: storage.low_t_min,
        t_low: storage.t_low, high: storage.high_t_min, t_high: storage.t_high })]);
      notes.push(['stop_constant', phrase('field_kit.stop_constant',
        { minutes: plan.constant_min, min_test: cfg.min_constant_test_min })]);
    } else {
      /* a riser as wide as the casing leaves nothing to store */
      notes.push(['stop_constant', phrase('field_kit.stop_constant_no_storage',
        { minutes: plan.constant_min })]);
    }
    notes.push(['stop_step', phrase('field_kit.stop_step',
      { step: plan.step_min, first: plan.first_step_min })]);
    notes.push(['storage_measured', phrase('field_kit.storage_measured')]);
    notes.push(['schedule', phrase('field_kit.schedule', {
      last: pumping.schedule_min[pumping.schedule_min.length - 1],
      every: pumping.late_every_min })]);
    notes.push(['recovery', phrase('field_kit.recovery')]);
    return notes;
  }

  function fieldPumpingCard(notes) {
    var pumping = fieldSchedules().pumping;
    var schedule = pumping.schedule_min.map(gText);
    var rows = [];
    /* seven to a row, so the card stays one card */
    for (var i = 0; i < schedule.length; i += 7) {
      rows.push(schedule.slice(i, i + 7).concat(['', '', '', '', '', '', '']).slice(0, 7));
    }
    var recovery = notes.filter(function (n) { return n[0] === 'recovery'; })[0][1];
    return {
      key: 'pumping',
      title: phrase('field_kit.card_pumping_title'),
      lines: [phrase('field_kit.card_pumping_schedule', { every: pumping.late_every_min }),
        recovery],
      tables: [{ caption: 'Reading minutes', header: [], rows: rows }],
      /* the sheet's own advice, less the sentences about its Time column */
      notes: notes.filter(function (n) { return n[0] !== 'schedule' && n[0] !== 'recovery'; })
        .map(function (n) { return n[1]; }),
    };
  }

  function fieldVesCard(cfg) {
    var field = fieldSchedules().ves;
    var plan = vesSurveyPlan(depthOfInvestigation(
      field.ab2_series_m[field.ab2_series_m.length - 1], cfg.ves), cfg);
    return {
      key: 'ves',
      title: phrase('field_kit.card_ves_title'),
      lines: [phrase('field_kit.card_ves_rule', { factor: plan.factor }),
        phrase('field_kit.card_ves_mn', { min_ratio: field.min_ab_per_mn,
          max_ratio: field.max_ab_per_mn })],
      tables: [{ caption: 'Schlumberger spacings',
        header: ['No.', 'AB/2 (m)', 'MN (m)', 'Depth reached (m)'],
        rows: plan.steps.map(function (/** @type {Rec} */ s, /** @type {number} */ k) {
          return [String(k + 1), gText(s.ab2), gText(s.mn),
            gText(depthOfInvestigation(s.ab2, cfg.ves))];
        }) }],
      notes: [],
    };
  }

  function fieldDoseCard() {
    var grid = fieldSchedules().disinfection_card;
    var header = ['Water column (m)'];
    grid.casing_id_mm.forEach(function (/** @type {number} */ d) {
      header.push(gText(d) + ' mm: L', gText(d) + ' mm: g');
    });
    /** @type {number|null} */
    var hours = null;
    /** @type {number|null} */
    var gramsPerLitre = null;
    var rows = grid.water_column_m.map(function (/** @type {number} */ column) {
      var row = [gText(column)];
      grid.casing_id_mm.forEach(function (/** @type {number} */ d) {
        var dose = disinfectionDose(column, d);
        hours = dose.contact_hours;
        gramsPerLitre = dose.hth_grams / dose.solution_02pct_l;
        row.push(renderText('{v:.1f}', { v: dose.solution_02pct_l }),
          renderText('{v:.0f}', { v: dose.hth_grams }));
      });
      return row;
    });
    return {
      key: 'disinfection',
      title: phrase('field_kit.card_dose_title'),
      lines: [phrase('field_kit.card_dose_rule', { hours: hours }),
        phrase('field_kit.card_dose_solution', { grams: gramsPerLitre }),
        phrase('field_kit.card_dose_volume')],
      tables: [{ caption: phrase('field_kit.card_dose_table'), header: header, rows: rows }],
      notes: [phrase('field_kit.card_dose_basis')],
    };
  }

  /** Everything the field kit prints, as plain data: one pumping test sheet
   * for each borehole named (blank names dropped, repeats printed once) and
   * the three quick cards (field_kit.py field_kit_content).
   * @param {Rec} site the project's header block
   * @param {string[]} boreholes
   * @param {Config} [config]
   * @returns {Rec} */
  function fieldKitContent(site, boreholes, config) {
    var cfg = config || defaultConfig();
    var project = projectIdentifier(site);
    /** @type {string[]} */
    var names = [];
    (boreholes || []).forEach(function (name) {
      var cleaned = fieldText(name);
      if (cleaned && names.indexOf(cleaned) < 0) names.push(cleaned);
    });
    var plan = fieldPlan(cfg.pumping);
    var notes = fieldPumpingNotes(plan, cfg.pumping);
    var noteTexts = notes.map(function (n) { return n[1]; });
    var citations = phraseTable('references.citations');
    return {
      format: FIELD_KIT_FORMAT,
      project: project,
      title: phrase('field_kit.title', { name: project || fieldText(site.community) ||
        'unnamed project' }),
      storage: plan.storage,
      constant_min: plan.constant_min,
      first_step_min: plan.first_step_min,
      planned_min: plan.planned_min,
      sheets: names.map(function (name) {
        return fieldSheet(site, project, name, plan, noteTexts.slice());
      }),
      cards: [fieldPumpingCard(notes), fieldVesCard(cfg), fieldDoseCard()],
      /* the supervision guide the checklist item follows, and WHO, which the
       * dose calculator names (citations.py _REFERENCES_FOR field_kit) */
      references: [citations.rwsn_supervision, citations.who],
    };
  }

  Object.assign(C, {
    FIELD_KIT_FORMAT: FIELD_KIT_FORMAT,
    fieldSchedules: fieldSchedules, readingMinutes: readingMinutes,
    cautiousStorage: cautiousStorage, vesSurveyPlan: vesSurveyPlan, airliftYield: airliftYield,
    fieldKitPayload: fieldKitPayload, parseFieldKitPayload: parseFieldKitPayload,
    projectIdentifier: projectIdentifier, fieldKitContent: fieldKitContent,
  });

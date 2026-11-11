
  /* ================================================================= ledger
   * groundwater/ledger.py (PLAN.md step 5.1). What the survey predicted at
   * each point beside what the borehole drilled there found, kept in the
   * project file and pooled across a portfolio for the calibration of step
   * 5.2. Not the Depth Spine's sign-off ledger (spine.ledger), which records
   * who certified each value of one borehole.
   *
   * One entry for each survey point. Its prediction is kept as it was
   * recorded, and replaced only while the borehole is not drilled;
   * before_outcome says whether it was recorded before drilling, and a new
   * recording never makes it earlier. A ledger takes an identity of its own
   * (project_id) when its first predictions are written into it, and each
   * entry's id carries it, so two projects whose soundings share a name and
   * a place keep their points apart in a portfolio. The outcome
   * is worked out again from the project's completion whenever the project
   * is saved, and attached to the point the borehole was drilled at: the one
   * a person chose, else the nearest within ledger.pair_within_m of the
   * log's position, else the survey's only point. The recommended point is
   * never taken to be the one drilled. Each prediction names the survey team
   * that made it and each outcome the contractor who drilled, for the
   * calibration's hit rates. */

  /** ledger.empty_ledger: no entry and no identity yet.
   * @returns {{drilled: string|null, entries: Rec[], project_id: string|null}} */
  function emptyLedger() {
    return { drilled: null, entries: [], project_id: null };
  }

  function ledgerGiven(v) { return v !== null && v !== undefined; }

  function isRecord(v) { return !!v && typeof v === 'object' && !Array.isArray(v); }

  /* ledger._num: a finite number rounded as Python rounds (not at all for
   * digits null), or null. Only a number is one. */
  function ledgerNum(value, digits) {
    if (typeof value !== 'number' || !isFinite(value)) return null;
    return digits === null ? value : pyRound(value, digits);
  }

  function ledgerBand(band, digits) {
    if (!band) return null;
    return [ledgerNum(band.p10, digits), ledgerNum(band.p50, digits), ledgerNum(band.p90, digits)];
  }

  /* ledger._name: a person's or firm's name as typed, its runs of white
   * space made one space and its ends trimmed; '' for anything but text. The
   * white space is ASCII only, as Python's pattern has it. */
  function ledgerName(value) {
    return typeof value === 'string'
      ? value.replace(/[ \t\n\r\f\v]+/g, ' ').replace(/^ +| +$/g, '') : '';
  }

  function ledgerZone(value) {
    return typeof value === 'number' && Number.isInteger(value) ? value : null;
  }

  /** ledger.point_id: a hash of the point's name, place and position, and of
   * the identity of the ledger it is recorded in, so two copies of one
   * project's file give their points one identifier and two projects whose
   * soundings share a name and a place do not. A ledger with no identity
   * ('') gives the identifier it always did.
   * @param {string} soundingId
   * @param {number|null} easting
   * @param {number|null} northing
   * @param {number|null} utmZone
   * @param {string} [community]
   * @param {string} [district]
   * @param {string} [projectId] the ledger's identity, '' or absent for none
   * @returns {string} */
  function pointId(soundingId, easting, northing, utmZone, community, district, projectId) {
    var e = ledgerNum(easting, 1) === null ? '' : pyFixed(Number(easting), 0);
    var n = ledgerNum(northing, 1) === null ? '' : pyFixed(Number(northing), 0);
    var zone = ledgerZone(utmZone);
    var parts = [String(soundingId || ''), e, n, zone === null ? '' : String(zone),
      String(community || ''), String(district || '')];
    if (projectId) parts.push(String(projectId));
    return sha256Hex(parts.join('\n')).slice(0, 12);
  }

  /* ledger._point_key: a point's identifier with no ledger's identity in
   * it, what tells one point of a survey from another */
  function ledgerPointKey(point) {
    return pointId(point.sounding_id, point.easting, point.northing, point.utm_zone,
      point.community, point.district);
  }

  /* ledger._ledger_identity: the identity a ledger takes when its first
   * predictions are written into it, a hash of the day they were recorded
   * and the points they were recorded at */
  function ledgerIdentity(recordedOn, predictions) {
    /** @type {Object<string, boolean>} */
    var seen = {};
    predictions.forEach(function (item) { seen[ledgerPointKey(item.point)] = true; });
    var keys = Object.keys(seen).sort();
    return sha256Hex(['ledger', String(recordedOn)].concat(keys).join('\n')).slice(0, 12);
  }

  function ledgerOdds(odds) {
    if (!odds) return null;
    return {
      probability: ledgerNum(odds.probability, 3),
      low: ledgerNum(odds.low, 3),
      high: ledgerNum(odds.high, 3),
      prior: ledgerNum(odds.prior, 3),
      effective_n: ledgerNum(odds.effective_n, 3),
      status: String(odds.status || ''),
      matched: String(odds.matched || ''),
      bgs_code: odds.bgs_code || null,
      glg: odds.glg || null,
      success_yield_m3_per_h: ledgerNum(odds.success_yield_m3_per_h, 3),
      calibration: String(odds.calibration || ''),
    };
  }

  /* ledger.SUITABILITY_PARTS: the four parts of the suitability score, in
   * the order the score adds them */
  var SUITABILITY_PARTS = ['aquifer_thickness', 'resistivity_fit', 'overburden', 'basal_fracture'];

  /* the best fit's layers as [top, bottom, resistivity], the half-space's
   * bottom null: what step 5.3 pairs with the log's bands of rock */
  function ledgerLayers(interp) {
    return (interp.layers || []).map(function (layer) {
      return [ledgerNum(layer.top_m, 1), ledgerNum(layer.bottom_m, 1), ledgerNum(layer.rho, 1)];
    });
  }

  /* the suitability score's four parts, each 0 to 1, or null */
  function ledgerSuitability(components) {
    if (!components) return null;
    var out = {};
    for (var k = 0; k < SUITABILITY_PARTS.length; k++) {
      var key = SUITABILITY_PARTS[k];
      out[key] = ledgerNum(components[key], 3);
      if (out[key] === null) return null;
    }
    return out;
  }

  /** ledger.point_prediction: what the survey predicts at one point, as
   * plain numbers. The drilling depth's band is the one the reports print.
   * The layers and the suitability score's parts are what a calibration set
   * (PLAN.md step 5.3) is fitted from.
   * @param {Interpretation} interp
   * @param {Rec|null} range the point's sampled range of models, or null
   * @param {Rec|null} odds the point's chance of a working borehole, or null
   * @param {Config} [config]
   * @param {string} [team] the survey team that made it, '' where none is recorded
   * @param {Rec|null} [suitability] the parts of its suitability score (assessSiting's components), or null
   * @returns {Rec} */
  function pointPrediction(interp, range, odds, config, team, suitability) {
    var cfg = config || defaultConfig();
    var basementBand = null, weatheredBand = null, depthBand = null, unresolved = null;
    if (range) {
      basementBand = quotesBasementBand(range) ? ledgerBand(range.basement_m, 1) : null;
      weatheredBand = ledgerBand(range.weathered_m, 1);
      unresolved = ledgerNum(range.basement_unresolved, 3);
      var spread = depthSpread(range, cfg);
      if (spread) {
        depthBand = [ledgerNum(depthDraw(spread, 0.1), 1), ledgerNum(depthDraw(spread, 0.9), 1)];
      }
    }
    return {
      depth_to_basement_m: ledgerNum(interp.depth_to_basement_m, 1),
      basement_resolved: !interp.basement_not_resolved,
      investigation_depth_m: ledgerNum(interp.investigation_depth_m, 1),
      water_zones_m: (interp.water_zones || []).map(function (z) {
        return [ledgerNum(z[0], 1), ledgerNum(z[1], 1)];
      }),
      water_bearing_m: ledgerNum(interp.aquifer_thickness_m, 1),
      drilling_depth_m: ledgerNum(interp.max_drilling_depth_m, 1),
      drilling_depth_minimum: !!(interp.basement_not_resolved || interp.drilling_depth_capped),
      fit_error_percent: ledgerNum(interp.fit_error_percent, 2),
      range_sampled: !!range,
      basement_band_m: basementBand,
      basement_unresolved_share: unresolved,
      weathered_band_m: weatheredBand,
      drilling_depth_band_m: depthBand,
      odds: ledgerOdds(odds),
      survey_team: ledgerName(team),
      layers: ledgerLayers(interp),
      suitability: ledgerSuitability(suitability || null),
    };
  }

  /** ledger.survey_predictions: each point's place and prediction, in the
   * survey's order. ranges, odds and teams go with interps by position; a
   * point's survey team is the field supervisor its own sheet names, else
   * the project's. siting is what assessSiting returned for interps, each
   * result found by the index it carries, since it comes back ranked.
   * @param {Interpretation[]} interps
   * @param {Array<Rec|null>|null} ranges
   * @param {Array<Rec|null>|null} odds
   * @param {Rec} site the project's site, for its zone, its place and its field supervisor
   * @param {Config} [config]
   * @param {Array<string>|null} [teams] the field supervisor each point's sheet names
   * @param {Array<Rec>|null} [siting] assessSiting's results for interps
   * @returns {Rec[]} */
  function surveyPredictions(interps, ranges, odds, site, config, teams, siting) {
    var where = site || {};
    var zone = ledgerZone(where.utm_zone);
    var community = String(where.community || ''), district = String(where.district || '');
    var supervisor = ledgerName(where.supervisor);
    /** @type {Object<string, Rec>} */
    var parts = {};
    (siting || []).forEach(function (r) {
      if (r.index !== null && r.index !== undefined) parts[r.index] = r.components;
    });
    return interps.map(function (interp, k) {
      var point = {
        sounding_id: String(interp.sounding_id || ''),
        easting: ledgerNum(interp.site_easting, 1),
        northing: ledgerNum(interp.site_northing, 1),
        utm_zone: zone,
        community: community,
        district: district,
      };
      var range = ranges && k < ranges.length ? ranges[k] : null;
      var chance = odds && k < odds.length ? odds[k] : null;
      var team = (teams && k < teams.length ? ledgerName(teams[k]) : '') || supervisor;
      return { point: point,
        prediction: pointPrediction(interp, range || null, chance || null, config, team,
          parts[k] || null) };
    });
  }

  /** ledger.completion_outcome: what the borehole found, or null where the
   * project holds no log. Success is as the odds define it where a pumping
   * test says; without one a hole whose status reads as unsuccessful is a
   * failure and one recorded successful is the driller's word; success_basis
   * says which (tested, recorded_failure, recorded_success). contractor is
   * the project's drilling contractor, which wins over the log's own.
   * @param {DrillingLog|null} log
   * @param {PumpingAnalysis|null} [analysis]
   * @param {Config} [config]
   * @param {string} [contractor]
   * @returns {Rec|null} */
  function completionOutcome(log, analysis, config, contractor) {
    if (!log) return null;
    var cfg = config || defaultConfig();
    var bands = lithologyBands(log.intervals || []);
    var basement = null;
    for (var i = 0; i < bands.length; i++) {
      if (bands[i].key === 'basement') { basement = bands[i].top_m; break; }
    }
    var statusClass = classifyStatusText(log.status || '');
    var rec = analysis ? analysis.yield_recommendation : null;
    var raw = rec ? ledgerNum(rec.safe_yield_m3_per_h, null) : null;
    var safe = ledgerNum(raw, 2);
    var band = null, holds = null;
    var spread = analysis ? analysis.spread : null;
    if (safe !== null && spread && spread.bootstrap) {
      holds = !!spread.holds_at_dry_season;
      if (ledgerGiven(spread.bootstrap.p10) && ledgerGiven(spread.safe_yield_low_m3_per_h)) {
        /* the top is null where the projection gives no upper yield */
        band = [ledgerNum(spread.safe_yield_low_m3_per_h, 2),
          ledgerNum(spread.safe_yield_high_m3_per_h, 2)];
      }
    }
    var threshold = Number(cfg.odds.success_yield_m3_per_h);
    var success = null, basis = null;
    if (raw !== null) {
      /* on the yield as worked out, not as rounded for the file */
      success = raw >= threshold; basis = 'tested';
    } else if (statusClass === 'dry') {
      success = false; basis = 'recorded_failure';
    } else if (statusClass === 'successful') {
      success = true; basis = 'recorded_success';
    }
    var site = log.site || {};
    return {
      borehole_ref: String(log.borehole_ref || ''),
      contractor: ledgerName(contractor) || ledgerName(site.contractor),
      easting: ledgerNum(site.easting, 1),
      northing: ledgerNum(site.northing, 1),
      utm_zone: ledgerZone(site.utm_zone),
      completion_date: String(log.completion_date || ''),
      total_depth_m: ledgerNum(log.total_depth_m, 1),
      status: String(log.status || ''),
      status_class: statusClass,
      basement_m: ledgerNum(basement, 1),
      intervals: bands.map(function (b) {
        return [ledgerNum(b.top_m, 1), ledgerNum(b.bottom_m, 1), b.key];
      }),
      water_strikes_m: (log.water_strikes_m || []).map(function (d) { return ledgerNum(d, 1); }),
      safe_yield_m3_per_h: safe,
      safe_yield_band_m3_per_h: band,
      yield_confidence: safe !== null ? String(rec.confidence) : null,
      holds_at_dry_season: holds,
      success_yield_m3_per_h: ledgerNum(threshold, 3),
      success: success,
      success_basis: basis,
    };
  }

  /** ledger.uses_definition: whether a borehole's success was judged at
   * the definition of success in force (odds.success_yield_m3_per_h), as its
   * outcome records the yield it was judged at. The calibration scores, and
   * a calibration set fits, only the outcomes that were.
   * @param {Rec} outcome
   * @param {Config} [config]
   * @returns {boolean} */
  function usesDefinition(outcome, config) {
    var cfg = config || defaultConfig();
    var judged = outcome.success_yield_m3_per_h;
    return judged !== null && judged !== undefined &&
      Math.abs(judged - pyRound(Number(cfg.odds.success_yield_m3_per_h), 3)) < 1e-9;
  }

  /** ledger.record_predictions: the ledger with the survey's predictions
   * written in, and the ids of the entries that kept the prediction they had
   * (a forecast, recorded before drilling, once the borehole is drilled).
   * The borehole is drilled when outcomeKnown says so, the ledger already
   * holds an outcome, or a person has chosen the point drilled (drilled); a
   * prediction recorded then is marked as recorded after drilling, and one
   * recorded after drilling stays so. A ledger with no entry and no identity
   * takes one from this first recording; a point's entry is found by its id,
   * else by the point itself.
   * @param {Rec|null} ledger
   * @param {Rec[]} predictions what surveyPredictions returned
   * @param {string} recordedOn the date, as YYYY-MM-DD
   * @param {boolean} outcomeKnown whether the project holds a completion now
   * @param {string} toolkit the toolkit's version
   * @returns {{ledger: Rec, kept: string[]}} */
  function recordPredictions(ledger, predictions, recordedOn, outcomeKnown, toolkit) {
    var clean = cleanLedger(ledger);
    var entries = clean.entries.slice();
    var identity = clean.project_id;
    if (identity === null && !entries.length && predictions.length) {
      identity = ledgerIdentity(recordedOn, predictions);
    }
    var known = !!outcomeKnown || clean.drilled !== null ||
      entries.some(function (entry) { return entry.outcome !== null; });
    /** @type {Object<string, number>} */
    var byId = {};
    /** @type {Object<string, number>} */
    var byPoint = {};
    entries.forEach(function (entry, k) {
      if (!own(byId, entry.id)) byId[entry.id] = k;
      var key = ledgerPointKey(entry.point);
      if (!own(byPoint, key)) byPoint[key] = k;
    });
    /** @type {string[]} */
    var kept = [];
    predictions.forEach(function (item) {
      var point = item.point;
      var key = ledgerPointKey(point);
      var pid = pointId(point.sounding_id, point.easting, point.northing, point.utm_zone,
        point.community, point.district, identity || '');
      var k = own(byId, pid) ? byId[pid] : own(byPoint, key) ? byPoint[key] : null;
      var old = k !== null ? entries[k] : null;
      if (old && old.before_outcome && known) { kept.push(old.id); return; }
      var entry = {
        id: old ? old.id : pid,
        point: Object.assign({}, point),
        prediction: item.prediction,
        recorded_on: String(recordedOn),
        before_outcome: !known && (!old || old.before_outcome),
        toolkit: String(toolkit),
        outcome: old ? old.outcome : null,
        pairing: old ? old.pairing : null,
      };
      if (k === null) {
        k = entries.length;
        entries.push(entry);
      } else {
        entries[k] = entry;
      }
      if (!own(byId, entry.id)) byId[entry.id] = k;
      if (!own(byPoint, key)) byPoint[key] = k;
    });
    return { ledger: { drilled: clean.drilled, entries: entries, project_id: identity }, kept: kept };
  }

  function ledgerDistance(point, outcome) {
    if (!ledgerGiven(point.easting) || !ledgerGiven(point.northing) ||
        !ledgerGiven(outcome.easting) || !ledgerGiven(outcome.northing)) {
      return null;
    }
    var aZone = point.utm_zone || inferZoneForSierraLeone(point.easting);
    var bZone = outcome.utm_zone || inferZoneForSierraLeone(outcome.easting);
    return utmDistanceM({ easting: point.easting, northing: point.northing, zone: aZone, hemisphere: 'N' },
      { easting: outcome.easting, northing: outcome.northing, zone: bZone, hemisphere: 'N' });
  }

  /** ledger.pair_drilled: the id of the entry the borehole was drilled at,
   * and how that was decided (chosen, nearest or only); both null where
   * none of these says, or there is no outcome.
   * @param {Rec|null} ledger
   * @param {Rec|null} outcome
   * @param {Config} [config]
   * @returns {{id: string|null, pairing: Rec|null}} */
  function pairDrilled(ledger, outcome, config) {
    var cfg = config || defaultConfig();
    var entries = cleanLedger(ledger).entries;
    if (!outcome || !entries.length) return { id: null, pairing: null };
    var chosen = isRecord(ledger) ? /** @type {Rec} */ (ledger).drilled : null;
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].id === chosen) {
        return { id: chosen,
          pairing: { how: 'chosen', distance_m: ledgerNum(ledgerDistance(entries[i].point, outcome), 1) } };
      }
    }
    /** @type {Rec|null} */
    var best = null;
    /** @type {number|null} */
    var bestD = null;
    for (var j = 0; j < entries.length; j++) {
      var d = ledgerDistance(entries[j].point, outcome);
      if (d !== null && d <= Number(cfg.ledger.pair_within_m) && (bestD === null || d < bestD)) {
        best = entries[j]; bestD = d;
      }
    }
    if (best) return { id: best.id, pairing: { how: 'nearest', distance_m: ledgerNum(bestD, 1) } };
    if (entries.length === 1) {
      return { id: entries[0].id,
        pairing: { how: 'only', distance_m: ledgerNum(ledgerDistance(entries[0].point, outcome), 1) } };
    }
    return { id: null, pairing: null };
  }

  /** ledger.attach_outcome: the ledger with the project's completion on the
   * point it was drilled at and off every other. With no completion
   * (outcome null) the outcomes the ledger has are kept.
   * @param {Rec|null} ledger
   * @param {Rec|null} outcome what completionOutcome returned
   * @param {Config} [config]
   * @returns {Rec} */
  function attachOutcome(ledger, outcome, config) {
    var clean = cleanLedger(ledger);
    if (!outcome) return clean;
    var paired = pairDrilled(clean, outcome, config);
    return {
      drilled: clean.drilled,
      entries: clean.entries.map(function (entry) {
        var drilled = entry.id === paired.id;
        return Object.assign({}, entry, { outcome: drilled ? outcome : null,
          pairing: drilled ? paired.pairing : null });
      }),
      project_id: clean.project_id,
    };
  }

  var LEDGER_PREDICTION_NUMBERS = [['depth_to_basement_m', 1], ['investigation_depth_m', 1],
    ['water_bearing_m', 1], ['drilling_depth_m', 1], ['fit_error_percent', 2],
    ['basement_unresolved_share', 3]];
  var LEDGER_PREDICTION_FLAGS = ['basement_resolved', 'drilling_depth_minimum', 'range_sampled'];
  var LEDGER_PREDICTION_BANDS = [['basement_band_m', 3], ['weathered_band_m', 3],
    ['drilling_depth_band_m', 2]];
  var LEDGER_ODDS_NUMBERS = ['probability', 'low', 'high', 'prior', 'effective_n',
    'success_yield_m3_per_h'];
  var LEDGER_ODDS_TEXTS = ['status', 'matched', 'calibration'];
  var LEDGER_OUTCOME_NUMBERS = [['easting', 1], ['northing', 1], ['total_depth_m', 1],
    ['basement_m', 1], ['safe_yield_m3_per_h', 2], ['success_yield_m3_per_h', 3]];
  var LEDGER_OUTCOME_TEXTS = ['borehole_ref', 'completion_date', 'status'];
  var LEDGER_OUTCOME_KEYS = {
    status_class: ['successful', 'dry', 'sited', 'in_progress', 'other'],
    success_basis: ['tested', 'recorded_failure', 'recorded_success'],
    yield_confidence: ['established', 'indicative'],
  };
  var LEDGER_PAIRINGS = ['chosen', 'nearest', 'only'];

  function ledgerText(value) { return typeof value === 'string' ? value : ''; }

  function ledgerFlag(value) { return typeof value === 'boolean' ? value : null; }

  /* a list of numbers (of length, where one is given), or null */
  function ledgerNumbers(value, length, digits) {
    if (!Array.isArray(value) || (length !== null && value.length !== length)) return null;
    var out = value.map(function (v) { return ledgerNum(v, digits); });
    return out.indexOf(null) >= 0 ? null : out;
  }

  function cleanPrediction(raw) {
    if (!isRecord(raw)) return null;
    /** @type {Rec} */
    var out = {};
    LEDGER_PREDICTION_NUMBERS.forEach(function (pair) {
      out[pair[0]] = ledgerNum(raw[pair[0]], /** @type {number} */ (pair[1]));
    });
    LEDGER_PREDICTION_FLAGS.forEach(function (key) { out[key] = raw[key] === true; });
    out.survey_team = ledgerName(raw.survey_team);
    out.water_zones_m = Array.isArray(raw.water_zones_m)
      ? raw.water_zones_m.map(function (z) { return ledgerNumbers(z, 2, 1); })
        .filter(function (pair) { return pair !== null; })
      : [];
    LEDGER_PREDICTION_BANDS.forEach(function (pair) {
      out[pair[0]] = ledgerNumbers(raw[pair[0]], /** @type {number} */ (pair[1]), 1);
    });
    out.layers = Array.isArray(raw.layers)
      ? raw.layers.filter(function (layer) {
        return Array.isArray(layer) && layer.length === 3 && ledgerNum(layer[0], 1) !== null &&
          ledgerNum(layer[2], 1) !== null && (layer[1] === null || ledgerNum(layer[1], 1) !== null);
      }).map(function (layer) {
        return [ledgerNum(layer[0], 1), ledgerNum(layer[1], 1), ledgerNum(layer[2], 1)];
      })
      : [];
    out.suitability = isRecord(raw.suitability) ? ledgerSuitability(raw.suitability) : null;
    var odds = raw.odds;
    if (isRecord(odds)) {
      /** @type {Rec} */
      var clean = {};
      LEDGER_ODDS_NUMBERS.forEach(function (key) { clean[key] = ledgerNum(odds[key], 3); });
      LEDGER_ODDS_TEXTS.forEach(function (key) { clean[key] = ledgerText(odds[key]); });
      clean.bgs_code = typeof odds.bgs_code === 'string' ? odds.bgs_code : null;
      clean.glg = typeof odds.glg === 'string' ? odds.glg : null;
      out.odds = clean.probability !== null ? clean : null;
    } else {
      out.odds = null;
    }
    return out;
  }

  function cleanOutcome(raw) {
    if (!isRecord(raw)) return null;
    /** @type {Rec} */
    var out = {};
    LEDGER_OUTCOME_NUMBERS.forEach(function (pair) {
      out[pair[0]] = ledgerNum(raw[pair[0]], /** @type {number} */ (pair[1]));
    });
    LEDGER_OUTCOME_TEXTS.forEach(function (key) { out[key] = ledgerText(raw[key]); });
    out.contractor = ledgerName(raw.contractor);
    Object.keys(LEDGER_OUTCOME_KEYS).forEach(function (key) {
      out[key] = LEDGER_OUTCOME_KEYS[key].indexOf(raw[key]) >= 0 ? raw[key] : null;
    });
    out.utm_zone = ledgerZone(raw.utm_zone);
    out.intervals = Array.isArray(raw.intervals)
      ? raw.intervals.filter(function (iv) {
        return Array.isArray(iv) && iv.length === 3 && typeof iv[2] === 'string' &&
          ledgerNum(iv[0], 1) !== null && ledgerNum(iv[1], 1) !== null;
      }).map(function (iv) { return [ledgerNum(iv[0], 1), ledgerNum(iv[1], 1), iv[2]]; })
      : [];
    out.water_strikes_m = Array.isArray(raw.water_strikes_m)
      ? raw.water_strikes_m.map(function (v) { return ledgerNum(v, 1); })
        .filter(function (s) { return s !== null; })
      : [];
    var band = raw.safe_yield_band_m3_per_h;
    out.safe_yield_band_m3_per_h = Array.isArray(band) && band.length === 2 &&
      ledgerNum(band[0], 2) !== null ? [ledgerNum(band[0], 2), ledgerNum(band[1], 2)] : null;
    out.holds_at_dry_season = ledgerFlag(raw.holds_at_dry_season);
    out.success = ledgerFlag(raw.success);
    if (out.success === null) out.success_basis = null;
    return out;
  }

  function cleanPoint(raw) {
    if (!isRecord(raw)) return null;
    return {
      community: ledgerText(raw.community),
      district: ledgerText(raw.district),
      easting: ledgerNum(raw.easting, 1),
      northing: ledgerNum(raw.northing, 1),
      sounding_id: ledgerText(raw.sounding_id),
      utm_zone: ledgerZone(raw.utm_zone),
    };
  }

  /** ledger.clean_ledger: a ledger as read from a file, in the shape the
   * functions here write. A bad entry is left out, a field of the wrong kind
   * is blank, a prediction whose timing is not recorded is taken as recorded
   * after drilling, an id met twice is kept the first time, and the ledger's
   * identity is kept where it is text.
   * @param {*} raw
   * @returns {{drilled: string|null, entries: Rec[], project_id: string|null}} */
  function cleanLedger(raw) {
    if (!isRecord(raw)) return emptyLedger();
    /** @type {Rec[]} */
    var entries = [];
    /** @type {Object<string, boolean>} */
    var seen = {};
    (Array.isArray(raw.entries) ? raw.entries : []).forEach(function (item) {
      if (!isRecord(item) || typeof item.id !== 'string' || !item.id) return;
      var point = cleanPoint(item.point), prediction = cleanPrediction(item.prediction);
      if (point === null || prediction === null || own(seen, item.id)) return;
      seen[item.id] = true;
      var outcome = cleanOutcome(item.outcome);
      var pairing = item.pairing;
      if (outcome === null || !isRecord(pairing) || LEDGER_PAIRINGS.indexOf(pairing.how) < 0) {
        pairing = null;
      } else {
        pairing = { distance_m: ledgerNum(pairing.distance_m, 1), how: pairing.how };
      }
      entries.push({
        before_outcome: item.before_outcome === true,
        id: item.id,
        outcome: outcome,
        pairing: pairing,
        point: point,
        prediction: prediction,
        recorded_on: ledgerText(item.recorded_on),
        toolkit: ledgerText(item.toolkit),
      });
    });
    var drilled = raw.drilled, identity = raw.project_id;
    return { drilled: typeof drilled === 'string' && own(seen, drilled) ? drilled : null,
      entries: entries,
      project_id: typeof identity === 'string' && identity ? identity : null };
  }

  /** ledger.basement_check: how the depth to basement found compares with
   * the predicted band: inside, deeper, shallower, unreached_allowed or
   * no_band; null where the point was not drilled.
   * @param {Rec} prediction
   * @param {Rec|null} outcome
   * @returns {string|null} */
  function basementCheck(prediction, outcome) {
    if (!outcome) return null;
    var band = prediction.basement_band_m;
    if (!band) return 'no_band';
    var low = band[0], high = band[2];
    var found = outcome.basement_m;
    if (found === null || found === undefined) {
      var total = outcome.total_depth_m;
      if (ledgerGiven(total) && total > high) return 'deeper';
      return 'unreached_allowed';
    }
    if (found < low) return 'shallower';
    if (found > high) return 'deeper';
    return 'inside';
  }

  function ledgerDepthList(values) {
    return values.map(function (v) { return fmtNum(v); }).join(', ');
  }

  function ledgerZonesText(prediction) {
    var zones = prediction.water_zones_m;
    if (!zones.length) return phrase('ledger.zones_none');
    var openLast = !prediction.basement_resolved;
    var cells = zones.map(function (z, k) {
      return zoneCell(z[0], z[1], openLast && k === zones.length - 1);
    });
    return phrase('ledger.zones', { zones: cells.join(', ') });
  }

  function ledgerBasementPredicted(prediction) {
    var band = prediction.basement_band_m;
    var d = prediction.depth_to_basement_m;
    if (d === null) {
      if (band) return phrase('ledger.basement_none_band', { low: band[0], high: band[2] });
      return phrase('ledger.basement_none', { doi: prediction.investigation_depth_m || 0.0 });
    }
    if (band) return phrase('ledger.basement_band', { d: d, low: band[0], high: band[2] });
    return phrase('ledger.basement_best', { d: d });
  }

  function ledgerBasementFound(outcome) {
    if (outcome.basement_m !== null) return phrase('ledger.found_basement', { d: outcome.basement_m });
    if (outcome.total_depth_m !== null) {
      return phrase('ledger.found_basement_unreached', { td: outcome.total_depth_m });
    }
    return phrase('ledger.found_basement_no_depth');
  }

  function ledgerDepthPredicted(prediction) {
    var d = prediction.drilling_depth_m || 0.0;
    var depth = phrase(prediction.drilling_depth_minimum ? 'ledger.depth_least' : 'ledger.depth_about',
      { d: d });
    var band = prediction.drilling_depth_band_m;
    if (!band) return depth;
    if (band[0] === band[1]) return phrase('ledger.depth_band_flat', { depth: depth, low: band[0] });
    return phrase('ledger.depth_band', { depth: depth, low: band[0], high: band[1] });
  }

  function ledgerOddsText(prediction) {
    var odds = prediction.odds;
    if (!odds) return phrase('ledger.odds_none');
    return phrase('ledger.odds_short', { p: rangeShare(odds.probability),
      low: rangeShare(odds.low || 0.0), high: rangeShare(odds.high || 0.0) });
  }

  /** ledger.outcome_text: how the borehole turned out, by what says so.
   * @param {Rec|null} outcome
   * @returns {string} */
  function outcomeText(outcome) {
    if (!outcome) return phrase('ledger.not_drilled');
    var basis = outcome.success_basis;
    if (basis === 'tested') {
      if (outcome.success) return phrase('ledger.outcome_success_tested', { y: outcome.safe_yield_m3_per_h });
      return phrase('ledger.outcome_short_tested', { y: outcome.safe_yield_m3_per_h,
        t: outcome.success_yield_m3_per_h || 0.0 });
    }
    if (basis === 'recorded_failure') {
      return phrase('ledger.outcome_failure_recorded', { status: outcome.status });
    }
    if (basis === 'recorded_success') {
      return phrase('ledger.outcome_success_recorded', { status: outcome.status });
    }
    return phrase('ledger.outcome_unknown');
  }

  function ledgerStrikesCheck(prediction, outcome) {
    var strikes = outcome.water_strikes_m;
    var zones = prediction.water_zones_m;
    if (!strikes.length || !zones.length) return '';
    var inside = strikes.filter(function (s) {
      return zones.some(function (z) { return z[0] <= s && s <= z[1]; });
    }).length;
    return phrase('ledger.strikes_in_zones', { k: inside, n: strikes.length });
  }

  /** ledger.entry_header: the four columns of entryRows.
   * @returns {string[]} */
  function entryHeader() {
    return [phrase('ledger.col_quantity'), phrase('ledger.col_predicted'), phrase('ledger.col_found'),
      phrase('ledger.col_check')];
  }

  /** ledger.entry_rows: one point's prediction beside what was found, as
   * rows of four cells: the quantity, predicted, found, and how they compare.
   * @param {Rec} entry
   * @returns {string[][]} */
  function entryRows(entry) {
    var prediction = entry.prediction, outcome = entry.outcome;
    var found, checks;
    if (!outcome) {
      var notDrilled = phrase('ledger.not_drilled');
      found = [notDrilled, notDrilled, notDrilled, notDrilled];
      checks = ['', '', '', ''];
    } else {
      var strikes = outcome.water_strikes_m;
      found = [
        ledgerBasementFound(outcome),
        strikes.length ? phrase('ledger.strikes', { strikes: ledgerDepthList(strikes) })
          : phrase('ledger.strikes_none'),
        outcome.total_depth_m !== null ? phrase('ledger.drilled_to', { td: outcome.total_depth_m })
          : phrase('ledger.drilled_no_depth'),
        outcomeText(outcome),
      ];
      checks = [String(phraseTable('ledger.basement_check')[basementCheck(prediction, outcome) || 'no_band']),
        ledgerStrikesCheck(prediction, outcome), '', ''];
    }
    var labels = [phrase('ledger.row_basement'), phrase('ledger.row_zones'),
      phrase('ledger.row_depth'), phrase('ledger.row_odds')];
    var predicted = [ledgerBasementPredicted(prediction), ledgerZonesText(prediction),
      ledgerDepthPredicted(prediction), ledgerOddsText(prediction)];
    return [0, 1, 2, 3].map(function (k) { return [labels[k], predicted[k], found[k], checks[k]]; });
  }

  /* ledger._facts: how many of an outcome's fields hold something */
  function ledgerFacts(outcome) {
    return Object.keys(outcome).filter(function (key) {
      var v = outcome[key];
      return v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length);
    }).length;
  }

  /* ledger._rank: which of two copies of one entry a pool keeps, the higher
   * first - the one with an outcome, a known success over one not known
   * yet, a tested yield over the driller's recorded status, then one
   * recorded before drilling, then the one with more of its outcome
   * recorded, then the later recording - as a list compared item by item */
  function ledgerRank(entry) {
    var outcome = entry.outcome;
    if (outcome === null) return [false, false, false, entry.before_outcome, 0, entry.recorded_on];
    return [true, outcome.success !== null, outcome.success_basis === 'tested', entry.before_outcome,
      ledgerFacts(outcome), entry.recorded_on];
  }

  function ledgerKind(value) {
    if (value === null || value === undefined) return 0;
    if (typeof value === 'boolean') return 1;
    if (typeof value === 'number') return 2;
    if (typeof value === 'string') return 3;
    if (Array.isArray(value)) return 4;
    return 5;
  }

  /* ledger._order: a fixed order over the plain values a ledger holds, -1,
   * 0 or 1, to choose between two copies nothing else tells apart: nothing
   * first, then false before true, numbers, texts by code point, lists and
   * then mappings item by item, a mapping's items in the order of its keys */
  function ledgerOrder(a, b) {
    var ka = ledgerKind(a), kb = ledgerKind(b);
    if (ka !== kb) return ka < kb ? -1 : 1;
    if (ka === 0) return 0;
    if (ka === 3) return codePointCompare(a, b);
    if (ka === 4) {
      for (var i = 0; i < Math.min(a.length, b.length); i++) {
        var c = ledgerOrder(a[i], b[i]);
        if (c) return c;
      }
      return a.length > b.length ? 1 : a.length < b.length ? -1 : 0;
    }
    if (ka === 5) {
      var pairs = function (m) {
        return Object.keys(m).sort(codePointCompare).map(function (k) { return [k, m[k]]; });
      };
      return ledgerOrder(pairs(a), pairs(b));
    }
    return a > b ? 1 : a < b ? -1 : 0;
  }

  /* ledger._one_borehole: whether outcomes name one borehole, one reference
   * and one completion date in all of them and not both blank */
  function ledgerOneBorehole(outcomes) {
    /** @type {Object<string, boolean>} */
    var names = {};
    outcomes.forEach(function (o) { names[JSON.stringify([o.borehole_ref, o.completion_date])] = true; });
    var keys = Object.keys(names);
    return keys.length === 1 && keys[0] !== JSON.stringify(['', '']);
  }

  /** ledger.pool_ledgers: the entries of many projects' ledgers, each once.
   * An entry found in more than one file is kept once, the copy whose
   * borehole outcome is best established (an outcome over none, a known
   * success over one not known yet, a test over the driller's word), then
   * one recorded before drilling, then the one with more of its outcome
   * recorded, then the later recording; copies alike in all of that are
   * taken in a fixed order of what they hold, so the pool is the same
   * whatever the order of the files. Each kept entry carries the label of
   * the project it came from as project, its ledger's identity as
   * project_id, how many files it was found in as copies, whether those
   * copies hold different outcomes as copies_differ, and whether those
   * different outcomes also fail to name one borehole by one reference and
   * completion date as copies_borehole_differs.
   * @param {Array<Array<*>>} items [project label, ledger] pairs
   * @returns {Rec[]} */
  function poolLedgers(items) {
    /** @type {Object<string, Array<*>>} */
    var kept = {};
    /** @type {Object<string, number>} */
    var copies = {};
    /** @type {Object<string, Rec[]>} */
    var outcomes = {};
    /** @type {string[]} */
    var order = [];
    items.forEach(function (item) {
      var label = item[0], clean = cleanLedger(item[1]);
      clean.entries.forEach(function (entry) {
        var pid = entry.id;
        copies[pid] = (own(copies, pid) ? copies[pid] : 0) + 1;
        if (entry.outcome !== null) {
          if (!own(outcomes, pid)) outcomes[pid] = [];
          var held = outcomes[pid];
          if (!held.some(function (other) { return ledgerOrder(entry.outcome, other) === 0; })) {
            held.push(entry.outcome);
          }
        }
        var mine = [entry, String(label || ''), clean.project_id];
        if (!own(kept, pid)) {
          order.push(pid);
          kept[pid] = mine;
          return;
        }
        var have = kept[pid];
        var c = ledgerOrder(ledgerRank(entry), ledgerRank(have[0]));
        if (c > 0 || (c === 0 && ledgerOrder(mine, have) < 0)) kept[pid] = mine;
      });
    });
    return order.map(function (pid) {
      var held = kept[pid];
      var differ = own(outcomes, pid) && outcomes[pid].length > 1;
      return Object.assign({}, held[0], { project: held[1], project_id: held[2], copies: copies[pid],
        copies_differ: differ, copies_borehole_differs: differ && !ledgerOneBorehole(outcomes[pid]) });
    });
  }

  /** ledger.ledger_counts: the points predicted, the projects they are in
   * (told apart by their ledgers' identities, else by their labels), those
   * drilled, those drilled whose prediction was recorded before, how those
   * drilled turned out, and the points found in more than one file (copies),
   * those whose copies hold different outcomes (copies_differ), of those the
   * ones from ledgers with no identity (copies_unsure), whose copies may be
   * two projects, and of the rest the ones whose outcomes do not name one
   * borehole (copies_borehole_differs), which may be two boreholes.
   * @param {Rec[]} pooled
   * @returns {Rec} */
  function ledgerCounts(pooled) {
    var drilled = pooled.filter(function (e) { return e.outcome !== null; });
    /** @type {Object<string, boolean>} */
    var projects = {};
    pooled.forEach(function (e) {
      projects[e.project_id ? 'id:' + e.project_id : 'label:' + e.project] = true;
    });
    var differ = pooled.filter(function (e) { return e.copies_differ === true; });
    var named = differ.filter(function (e) { return !!e.project_id; });
    return {
      points: pooled.length,
      projects: Object.keys(projects).length,
      drilled: drilled.length,
      forecast: drilled.filter(function (e) { return e.before_outcome; }).length,
      success: drilled.filter(function (e) { return e.outcome.success === true; }).length,
      failure: drilled.filter(function (e) { return e.outcome.success === false; }).length,
      unknown: drilled.filter(function (e) { return e.outcome.success === null; }).length,
      copies: pooled.filter(function (e) { return (e.copies === undefined ? 1 : e.copies) > 1; }).length,
      copies_differ: differ.length,
      copies_unsure: differ.length - named.length,
      copies_borehole_differs: named.filter(function (e) { return e.copies_borehole_differs === true; }).length,
    };
  }

  /** ledger.ledger_summary: what a pooled ledger holds, in a sentence; then,
   * where a point was found in more than one file, the rule that chose the
   * copy counted, and a sentence for the points whose copies disagree: an
   * older record where their ledgers have an identity and their outcomes
   * name one borehole, else the two things it may be.
   * @param {Rec[]} pooled
   * @returns {string} */
  function ledgerSummary(pooled) {
    if (!pooled.length) return phrase('ledger.pool_none');
    var counts = ledgerCounts(pooled);
    var text = phrase('ledger.pool_counts', { points: counts.points, projects: counts.projects,
      drilled: counts.drilled, forecast: counts.forecast });
    if (counts.copies) text += ' ' + phrase('ledger.pool_copies', { copies: counts.copies });
    var differ = counts.copies_differ - counts.copies_unsure - counts.copies_borehole_differs;
    if (differ) text += ' ' + phrase('ledger.pool_copies_differ', { differ: differ });
    if (counts.copies_borehole_differs) {
      text += ' ' + phrase('ledger.pool_copies_borehole', { points: counts.copies_borehole_differs });
    }
    if (counts.copies_unsure) {
      text += ' ' + phrase('ledger.pool_copies_unsure', { unsure: counts.copies_unsure });
    }
    return text;
  }

  /** ledger.ledger_rows: the drilled points of a pooled ledger as a table.
   * @param {Rec[]} pooled
   * @returns {{header: string[], rows: string[][]}} */
  function ledgerRows(pooled) {
    var header = [phrase('ledger.pool_col_project'), phrase('ledger.pool_col_point'),
      phrase('ledger.pool_col_recorded'), phrase('ledger.pool_col_basement'),
      phrase('ledger.pool_col_found'), phrase('ledger.pool_col_check'),
      phrase('ledger.pool_col_odds'), phrase('ledger.pool_col_outcome')];
    var rows = [];
    pooled.forEach(function (entry) {
      var outcome = entry.outcome;
      if (!outcome) return;
      var prediction = entry.prediction;
      rows.push([
        entry.project,
        entry.point.sounding_id,
        phrase(entry.before_outcome ? 'ledger.recorded_before' : 'ledger.recorded_after'),
        ledgerBasementPredicted(prediction),
        ledgerBasementFound(outcome),
        String(phraseTable('ledger.basement_check')[basementCheck(prediction, outcome) || 'no_band']),
        ledgerOddsText(prediction),
        outcomeText(outcome),
      ]);
    });
    return { header: header, rows: rows };
  }

  /* project_io.PROJECT_SCHEMA: 2 from PLAN.md step 5.1, when the file came
   * to carry the ledger, 3 from step 8.1, when it came to carry the issue
   * records of the documents issued from it, and 4 when the ledger came to
   * carry an identity of its own (project_id). Both apps' project files
   * write it. */
  var PROJECT_SCHEMA = 4;

  /* The step from each schema to the next, applied in turn on load: schema
   * 1 had no ledger, so a file of it opens with an empty one, schema 2 no
   * issue records, so a file of it opens with none, and schema 3's ledger
   * no identity, so a file of it keeps its ledger as it is, with none. */
  /** @type {Object<number, function(Rec): Rec>} */
  var PROJECT_MIGRATIONS = {
    1: function (payload) {
      return Object.assign({}, payload, { schema: 2, ledger: emptyLedger() });
    },
    2: function (payload) {
      return Object.assign({}, payload, { schema: 3, issued: [] });
    },
    3: function (payload) {
      return Object.assign({}, payload, { schema: 4 });
    },
  };

  /** project_io.payload_schema: the schema a project file was saved in. A
   * file without one is of schema 1: this app wrote version: 1 until
   * schema 2, and the Python app's first files wrote no schema.
   * @param {Rec} payload
   * @returns {number} */
  function payloadSchema(payload) {
    var schema = payload ? payload.schema : null;
    if (typeof schema !== 'number' || !isFinite(schema) || schema < 1) return 1;
    return Math.trunc(schema);
  }

  /** project_io.migrate_payload: a project file brought up to
   * PROJECT_SCHEMA one schema at a time; a newer file is returned as it is.
   * @param {Rec} payload
   * @returns {Rec} */
  function migratePayload(payload) {
    var schema = payloadSchema(payload);
    var out = payload;
    while (schema < PROJECT_SCHEMA) {
      out = PROJECT_MIGRATIONS[schema](out);
      schema += 1;
    }
    return out;
  }

  Object.assign(C, {
    PROJECT_SCHEMA: PROJECT_SCHEMA, payloadSchema: payloadSchema, migratePayload: migratePayload,
    emptyLedger: emptyLedger, pointId: pointId, pointPrediction: pointPrediction,
    surveyPredictions: surveyPredictions, completionOutcome: completionOutcome,
    recordPredictions: recordPredictions, pairDrilled: pairDrilled, attachOutcome: attachOutcome,
    usesDefinition: usesDefinition,
    cleanLedger: cleanLedger, basementCheck: basementCheck, outcomeText: outcomeText,
    entryHeader: entryHeader, entryRows: entryRows, poolLedgers: poolLedgers, ledgerCounts: ledgerCounts,
    ledgerRows: ledgerRows, ledgerSummary: ledgerSummary,
  });

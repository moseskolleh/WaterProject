
  /* ======================================================= calibration sets
   * groundwater/calibration_sets.py (PLAN.md steps 5.3 and 5.5). The prior
   * table's rates, the resistivity edges of each geology unit and the
   * suitability weights, fitted to the boreholes of a pooled ledger, and
   * adopted by a named person before anything changes. Every fit starts
   * from the provisional default, and uses only sums, products, quotients
   * and square roots, so the two engines agree to the bit. A set file holds
   * counts, not projects, and sets from several organisations are pooled
   * (poolSets); a pooled edge is a mean of logarithms, rounded to 0.1 ohm-m.
   */

  /* calibration_sets.FORMAT and FORMAT_VERSION: what a set file says it is;
   * format 1 (step 5.3) is still read, its ledger ids counted */
  var SET_FORMAT = 'groundwater calibration set';
  var SET_FORMAT_VERSION = 2;
  var SET_READS = [1, 2];
  /* calibration_sets.EDGES: the resistivity edges a set fits, in its order */
  var SET_EDGES = ['clay_max_rho', 'fresh_basement_min_rho'];
  /* the classes of rock under and over each edge */
  var SET_SIDES = {
    clay_max_rho: [['clay'], ['sand', 'weathered', 'fracture']],
    fresh_basement_min_rho: [['clay', 'saprolite', 'sand', 'weathered', 'fracture'], ['basement']],
  };
  var SET_CHANCE_BOUND = 0.0005;
  var SET_RATE_BOUND = 0.0001;
  var SET_STEPS = 20;

  /* the drilled entries whose success is known at the definition in force,
   * and how many drilled entries were left out and why */
  function setJudged(pooled, cfg) {
    var kept = [], unknown = 0, definition = 0;
    pooled.forEach(function (entry) {
      var outcome = entry.outcome;
      if (!outcome) return;
      if (outcome.success === null || outcome.success === undefined) {
        unknown += 1;
      } else if (!usesDefinition(outcome, cfg)) {
        definition += 1;
      } else {
        kept.push(entry);
      }
    });
    return { kept: kept, leftOut: { unknown: unknown, definition: definition } };
  }

  /* how far the survey evidence moved a recorded chance: its odds over the
   * odds of the prior it started from */
  function setFactor(odds) {
    var p = odds.probability, q = odds.prior;
    if (p === null || p === undefined || q === null || q === undefined) return null;
    p = Math.min(Math.max(p, SET_CHANCE_BOUND), 1.0 - SET_CHANCE_BOUND);
    q = Math.min(Math.max(q, SET_CHANCE_BOUND), 1.0 - SET_CHANCE_BOUND);
    return (p / (1.0 - p)) / (q / (1.0 - q));
  }

  /** calibration_sets.evidence_rate: the rate for the ground at which
   * boreholes whose evidence moved their odds by factors would expect
   * successes successes, by a hundred halvings of [0, 1].
   * @param {number[]} factors
   * @param {number} successes
   * @returns {number} */
  function evidenceRate(factors, successes) {
    var lo = 0.0, hi = 1.0;
    for (var i = 0; i < 100; i++) {
      var mid = 0.5 * (lo + hi);
      var expected = 0.0;
      for (var k = 0; k < factors.length; k++) {
        var f = factors[k];
        expected = expected + mid * f / (mid * f + 1.0 - mid);
      }
      if (expected < successes) lo = mid; else hi = mid;
    }
    return 0.5 * (lo + hi);
  }

  /** calibration_sets.fit_prior: the rows of the prior table the boreholes
   * fall in, each fitted where it holds ledger.fit_min_boreholes, and the
   * ids of the boreholes in each fitted row by the row's position.
   * @param {Rec[]} pooled
   * @param {Config} [config]
   * @returns {{rows: Rec[], used: Object<string, string[]>}} */
  function fitPrior(pooled, config) {
    var cfg = config || defaultConfig();
    var rateM3h = Number(cfg.odds.success_yield_m3_per_h);
    var judged = setJudged(pooled, cfg).kept;
    var table = oddsTables().prior;
    /** @type {Object<string, Rec[]>} */
    var members = {};
    judged.forEach(function (entry) {
      var odds = entry.prediction.odds;
      if (!odds || !odds.bgs_code || setFactor(odds) === null) return;
      var row = priorFor(odds.bgs_code, odds.glg, rateM3h, null);
      if (row.matched === 'fallback') return;
      for (var k = 0; k < table.length; k++) {
        if (table[k].bgs_code === row.bgs_code && table[k].glg === row.glg) {
          (members[k] = members[k] || []).push(entry);
          break;
        }
      }
    });
    /** @type {Rec[]} */
    var rows = [];
    /** @type {Object<string, string[]>} */
    var used = {};
    table.forEach(function (base, k) {
      var entries = members[k];
      if (!entries) return;
      /* every fit starts from the provisional table, never the set in force */
      var baseRate = priorFor(base.bgs_code, base.glg !== '*' ? base.glg : null, rateM3h, null).rate;
      var baseN = Number(base.effective_n);
      var m = entries.length;
      var successes = entries.filter(function (e) { return e.outcome.success; }).length;
      var factors = /** @type {number[]} */ (entries.map(function (e) { return setFactor(e.prediction.odds); }));
      /* the count the file holds, so that the rate is the one its counts
       * give, whoever adds them up again (poolSets) */
      var expected = pyRound(m * evidenceRate(factors, successes), 2);
      var fitted = m >= cfg.ledger.fit_min_boreholes;
      var rate = (baseN * baseRate + expected) / (baseN + m);
      if (fitted) used[rows.length] = entries.map(function (e) { return e.id; });
      rows.push({
        bgs_code: base.bgs_code,
        glg: base.glg,
        boreholes: m,
        successes: successes,
        expected: expected,
        base_rate: pyRound(baseRate, 4),
        base_n: baseN,
        fitted: fitted,
        rate: fitted ? Math.min(Math.max(pyRound(rate, 4), SET_RATE_BOUND), 1.0 - SET_RATE_BOUND) : null,
        effective_n: fitted ? baseN + m : null,
      });
    });
    return { rows: rows, used: used };
  }

  /** calibration_sets.layer_class: the class of rock the log gives a layer
   * of the best fit, the one that fills at least half of it down to the
   * log's total depth and the depth of investigation, and at least a metre
   * thick there; null where no class does.
   * @param {Array<number|null>} layer [top, bottom, resistivity]
   * @param {Rec} prediction
   * @param {Rec} outcome
   * @returns {string|null} */
  function layerClass(layer, prediction, outcome) {
    var top = /** @type {number} */ (layer[0]), bottom = layer[1];
    var total = outcome.total_depth_m;
    if (total === null || total === undefined) return null;
    var end = total;
    [bottom, prediction.investigation_depth_m].forEach(function (limit) {
      if (limit !== null && limit !== undefined && limit < end) end = limit;
    });
    var span = end - top;
    if (span < 1.0) return null;
    /** @type {Object<string, number>} */
    var overlap = {};
    /** @type {string[]} */
    var order = [];
    outcome.intervals.forEach(function (iv) {
      var lo = Math.max(iv[0], top), hi = Math.min(iv[1], end);
      if (hi > lo) {
        if (!(iv[2] in overlap)) { overlap[iv[2]] = 0.0; order.push(iv[2]); }
        overlap[iv[2]] = overlap[iv[2]] + (hi - lo);
      }
    });
    /** @type {string|null} */
    var best = null;
    for (var k = 0; k < order.length; k++) {
      if (best === null || overlap[order[k]] > overlap[best]) best = order[k];
    }
    if (best === null || 2.0 * overlap[best] < span) return null;
    return best;
  }

  /* how many layers an edge at value reads as the wrong side: clay at or
   * under clay_max_rho, fresh basement at or over fresh_basement_min_rho */
  function setMisread(edge, value, below, above) {
    var n = 0;
    if (edge === 'clay_max_rho') {
      below.forEach(function (r) { if (r > value) n += 1; });
      above.forEach(function (r) { if (r <= value) n += 1; });
    } else {
      below.forEach(function (r) { if (r >= value) n += 1; });
      above.forEach(function (r) { if (r < value) n += 1; });
    }
    return n;
  }

  /* the edge that misreads the fewest layers, among the edge in force and
   * the geometric midpoints of each two resistivities next to each other
   * between floor and ceiling; a tie goes to the edge nearest the one in
   * force, by ratio, and then to the lower */
  function setBestEdge(edge, base, below, above, floor, ceiling) {
    var seen = {};
    var values = below.concat(above).filter(function (v) {
      if (seen[String(v)]) return false;
      seen[String(v)] = true;
      return true;
    }).sort(function (a, b) { return a - b; });
    var best = base, bestMiss = setMisread(edge, base, below, above), bestRatio = 1.0;
    for (var i = 0; i + 1 < values.length; i++) {
      var c = pyRound(Math.sqrt(values[i] * values[i + 1]), 1);
      if (!(c > floor) || (ceiling !== null && !(c < ceiling))) continue;
      var miss = setMisread(edge, c, below, above);
      var ratio = Math.max(c / base, base / c);
      if (miss < bestMiss || miss === bestMiss && (ratio < bestRatio || ratio === bestRatio && c < best)) {
        best = c; bestMiss = miss; bestRatio = ratio;
      }
    }
    return [best, bestMiss];
  }

  /** calibration_sets.fit_edges: the resistivity edges of each geology unit
   * the boreholes were drilled in, each fitted where fit_min_boreholes
   * boreholes give it a layer and it has layers on both sides, by unit in
   * code-point order, clay first; and the ids behind each fitted edge.
   * @param {Rec[]} pooled
   * @param {Config} [config]
   * @returns {{rows: Rec[], used: Object<string, string[]>}} */
  function fitEdges(pooled, config) {
    var cfg = config || defaultConfig();
    var judged = setJudged(pooled, cfg).kept;
    /** @type {Object<string, Object<string, Array<Array<*>>>>} */
    var sides = {};
    judged.forEach(function (entry) {
      var prediction = entry.prediction, outcome = entry.outcome;
      var odds = prediction.odds;
      if (!odds || !odds.glg) return;
      if (!sides[odds.glg]) {
        sides[odds.glg] = {};
        SET_EDGES.forEach(function (edge) { sides[odds.glg][edge] = [[], [], []]; });
      }
      var unit = sides[odds.glg];
      prediction.layers.forEach(function (layer) {
        var klass = layerClass(layer, prediction, outcome);
        if (klass === null) return;
        SET_EDGES.forEach(function (edge) {
          var held = unit[edge];
          if (SET_SIDES[edge][0].indexOf(klass) >= 0) held[0].push(layer[2]);
          else if (SET_SIDES[edge][1].indexOf(klass) >= 0) held[1].push(layer[2]);
          else return;
          if (held[2].indexOf(entry.id) < 0) held[2].push(entry.id);
        });
      });
    });
    /** @type {Rec[]} */
    var rows = [];
    /** @type {Object<string, string[]>} */
    var used = {};
    var base = { clay_max_rho: Number(cfg.ves.clay_max_rho),
      fresh_basement_min_rho: Number(cfg.ves.fresh_basement_min_rho) };
    var force = inForce(cfg);
    Object.keys(sides).sort(codePointCompare).forEach(function (glg) {
      /* the edges in force here: the configuration's, or the set in force's
       * for the unit */
      var here = Object.assign({}, base, unitEdges(force, glg));
      var clay = here.clay_max_rho;
      SET_EDGES.forEach(function (edge) {
        var held = sides[glg][edge];
        var below = held[0], above = held[1], ids = held[2];
        if (!ids.length) return;
        var fitted = ids.length >= cfg.ledger.fit_min_boreholes && below.length > 0 && above.length > 0;
        var row = { glg: glg, edge: edge, boreholes: ids.length, below: below.length,
          above: above.length, base: here[edge], misread_base: setMisread(edge, here[edge], below, above),
          fitted: fitted, value: null, misread: null };
        if (fitted) {
          var got = edge === 'clay_max_rho'
            ? setBestEdge(edge, here[edge], below, above, 0.0, Number(cfg.ves.fractured_zone_rho[1]))
            : setBestEdge(edge, here[edge], below, above, clay, null);
          if (edge === 'clay_max_rho') clay = got[0];
          row.value = got[0];
          row.misread = got[1];
          used[rows.length] = ids.slice();
        }
        rows.push(row);
      });
    });
    return { rows: rows, used: used };
  }

  /* twice the pairs of a success and a failure the scores rank the right
   * way round, a tie counting once */
  function setPairsRight(successes, failures) {
    var ordered = failures.slice().sort(function (a, b) { return a - b; });
    function bound(x, strict) {
      var lo = 0, hi = ordered.length;
      while (lo < hi) {
        var mid = (lo + hi) >> 1;
        if (strict ? ordered[mid] < x : ordered[mid] <= x) lo = mid + 1; else hi = mid;
      }
      return lo;
    }
    var total = 0;
    successes.forEach(function (s) {
      var lower = bound(s, true);
      total += 2 * lower + (bound(s, false) - lower);
    });
    return total;
  }

  /* weights in twentieths: whole numbers where they fall on the grid, as
   * every fitted set's do, so their scores stay exact */
  function setInTwentieths(weights) {
    return SUITABILITY_PARTS.map(function (key) {
      var k = Number(weights[key]) * SET_STEPS, r = pyRound(k, 0);
      return Math.abs(k - r) < 1e-9 ? r : k;
    });
  }

  function setScores(parts, w) {
    return parts.map(function (p) { return w[0] * p[0] + w[1] * p[1] + w[2] * p[2] + w[3] * p[3]; });
  }

  /** calibration_sets.fit_weights: the suitability score's weights fitted in
   * twentieths to the boreholes whose score's parts were recorded, once
   * fit_weights_min_each succeeded and as many failed; and their ids where
   * they were fitted.
   * @param {Rec[]} pooled
   * @param {Config} [config]
   * @returns {{weights: Rec, used: string[]}} */
  function fitWeights(pooled, config) {
    var cfg = config || defaultConfig();
    var judged = setJudged(pooled, cfg).kept;
    var won = [], lost = [], ids = [];
    judged.forEach(function (entry) {
      var parts = entry.prediction.suitability;
      if (!parts) return;
      var row = SUITABILITY_PARTS.map(function (key) { return pyRound(parts[key] * 1000, 0); });
      (entry.outcome.success ? won : lost).push(row);
      ids.push(entry.id);
    });
    /* the weights in force: the configuration's, or the set in force's */
    var inUse = cfg.ves.suitability_weights;
    var base = setInTwentieths(inUse);
    var pairs = won.length * lost.length;
    /** @type {Rec} */
    var baseTable = {};
    SUITABILITY_PARTS.forEach(function (key) { baseTable[key] = Number(inUse[key]); });
    var minimum = cfg.ledger.fit_weights_min_each;
    /** @type {Rec} */
    var out = {
      successes: won.length,
      failures: lost.length,
      base: baseTable,
      right_base: pairs ? pyRound(setPairsRight(setScores(won, base), setScores(lost, base)) / (2 * pairs), 4)
        : null,
      fitted: won.length >= minimum && lost.length >= minimum,
      value: null,
      right: null,
    };
    if (!out.fitted) return { weights: out, used: [] };
    var best = null, bestRight = -1, bestDistance = 0;
    for (var a = 0; a <= SET_STEPS; a++) {
      for (var b = 0; b <= SET_STEPS - a; b++) {
        for (var c = 0; c <= SET_STEPS - a - b; c++) {
          var w = [a, b, c, SET_STEPS - a - b - c];
          var right = setPairsRight(setScores(won, w), setScores(lost, w));
          var distance = 0;
          for (var k = 0; k < 4; k++) distance += Math.abs(w[k] - base[k]);
          if (right > bestRight || right === bestRight && distance < bestDistance) {
            best = w; bestRight = right; bestDistance = distance;
          }
        }
      }
    }
    /** @type {Rec} */
    var value = {};
    SUITABILITY_PARTS.forEach(function (key, k) { value[key] = /** @type {number[]} */ (best)[k] / SET_STEPS; });
    out.value = value;
    out.right = pyRound(bestRight / (2 * pairs), 4);
    return { weights: out, used: ids };
  }

  /** calibration_sets.default_set: the set the toolkit ships, adopted by
   * no one, issued by no one and so under no licence.
   * @returns {Rec} */
  function defaultSet() {
    return {
      format: SET_FORMAT,
      format_version: SET_FORMAT_VERSION,
      licence: '',
      organisation: '',
      contact: '',
      version: 0,
      fitted_on: '',
      adopted_by: '',
      adopted_on: '',
      replaces: null,
      success_yield_m3_per_h: null,
      boreholes: 0,
      left_out: { unknown: 0, definition: 0 },
      prior: [],
      edges: [],
      weights: null,
      sources: [],
    };
  }

  /** calibration_sets.fit_set: a calibration set fitted to the pooled
   * ledger's boreholes, numbered and adopted by no one yet, to be issued
   * under ledger.set_licence; it counts the boreholes it used and writes no
   * ledger id.
   * @param {Rec[]} pooled
   * @param {string} fittedOn
   * @param {Config} [config]
   * @returns {Rec} */
  function fitSet(pooled, fittedOn, config) {
    var cfg = config || defaultConfig();
    var leftOut = setJudged(pooled, cfg).leftOut;
    var prior = fitPrior(pooled, cfg), edges = fitEdges(pooled, cfg), weights = fitWeights(pooled, cfg);
    /** @type {Object<string, boolean>} */
    var used = {};
    [prior.used, edges.used].forEach(function (byRow) {
      Object.keys(byRow).forEach(function (k) {
        byRow[k].forEach(function (id) { used[id] = true; });
      });
    });
    weights.used.forEach(function (id) { used[id] = true; });
    return Object.assign(defaultSet(), {
      licence: ledgerName(cfg.ledger.set_licence),
      version: null, fitted_on: String(fittedOn),
      success_yield_m3_per_h: pyRound(cfg.odds.success_yield_m3_per_h, 3),
      boreholes: Object.keys(used).length, left_out: leftOut, prior: prior.rows, edges: edges.rows,
      weights: weights.weights,
    });
  }

  /** calibration_sets.adopt_set: candidate adopted by a named person on a
   * date, numbered one after the set in force, which it names as the set it
   * replaces, and issued in the name of organisation with contact, either
   * of which may be blank. A blank name, or a set adopted already, throws
   * the sentence the app shows.
   * @param {Rec} candidate
   * @param {string} adoptedBy
   * @param {string} adoptedOn
   * @param {Rec|null} [inForce]
   * @param {string} [organisation]
   * @param {string} [contact]
   * @returns {Rec} */
  function adoptSet(candidate, adoptedBy, adoptedOn, inForce, organisation, contact) {
    var who = ledgerName(adoptedBy);
    if (!who) throw new Error(phrase('calibration_sets.adopt_unnamed'));
    if (candidate.adopted_by) {
      throw new Error(phrase('calibration_sets.adopt_again', { by: candidate.adopted_by,
        on: candidate.adopted_on }));
    }
    var force = inForce || defaultSet();
    return Object.assign({}, candidate, {
      organisation: ledgerName(organisation),
      contact: ledgerName(contact),
      version: force.version + 1,
      adopted_by: who,
      adopted_on: String(adoptedOn),
      replaces: { version: force.version, fitted_on: force.fitted_on, adopted_by: force.adopted_by,
        adopted_on: force.adopted_on },
    });
  }

  /* calibration_sets._called: a set's name from its number, dates, adopter,
   * count of boreholes and count of sets it pooled */
  function setCalled(version, fittedOn, n, by, on, sets) {
    if (version === 0) return phrase('calibration_sets.name_default');
    if (sets) {
      if (by) {
        return phrase('calibration_sets.name_pooled_adopted', { version: version, fitted_on: fittedOn, k: sets,
          by: by, on: on });
      }
      return phrase('calibration_sets.name_pooled_candidate', { fitted_on: fittedOn, k: sets });
    }
    if (by) {
      return phrase('calibration_sets.name_adopted', { version: version, fitted_on: fittedOn, n: n, by: by,
        on: on });
    }
    return phrase('calibration_sets.name_candidate', { fitted_on: fittedOn, n: n });
  }

  /** calibration_sets.set_name: the set as a report names it; a pooled set
   * by the number of sets it pools.
   * @param {Rec} s
   * @returns {string} */
  function setName(s) {
    return setCalled(s.version, s.fitted_on, s.boreholes, s.adopted_by, s.adopted_on, s.sources.length);
  }

  /** calibration_sets.in_force: the calibration set in force, the
   * configuration's, else the provisional default.
   * @param {Config|null} [config]
   * @returns {Rec} */
  function inForce(config) {
    return config && config.calibration ? config.calibration : defaultSet();
  }

  /** calibration_sets.check_in_force: a set read whole and refused unless it
   * is the provisional default or a named person adopted it.
   * @param {*} raw
   * @returns {Rec} */
  function checkInForce(raw) {
    var s = cleanSet(raw);
    if (s.version === null) throw new Error(phrase('calibration_sets.not_adopted'));
    return s;
  }

  /** calibration_sets.apply_set: a copy of config with the set in force, its
   * suitability weights the set's where it fitted them.
   * @param {Config} config
   * @param {*} raw
   * @returns {Config} */
  function applySet(config, raw) {
    var s = checkInForce(raw);
    var out = JSON.parse(JSON.stringify(config));
    var previous = inForce(config).weights;
    if (s.weights !== null && s.weights.fitted) {
      out.ves.suitability_weights = Object.assign({}, s.weights.value);
    } else if (previous !== null && previous.fitted) {
      out.ves.suitability_weights = Object.assign({}, configDefaults().ves.suitability_weights);
    }
    out.calibration = s.version === 0 ? null : s;
    return out;
  }

  /** calibration_sets.fitted_prior: the set's fitted row for the prior
   * table's row bgsCode and glg ('*' for a class's row), or null; nothing
   * where the set was fitted at another definition of success.
   * @param {Rec} s
   * @param {string} bgsCode
   * @param {string} glg
   * @param {number} successYieldM3h
   * @returns {Rec|null} */
  function fittedPrior(s, bgsCode, glg, successYieldM3h) {
    var judged = s.success_yield_m3_per_h;
    if (judged === null || judged === undefined ||
        !(Math.abs(judged - pyRound(successYieldM3h, 3)) < 1e-9)) return null;
    for (var i = 0; i < s.prior.length; i++) {
      var row = s.prior[i];
      if (row.fitted && row.bgs_code === bgsCode && row.glg === glg) return row;
    }
    return null;
  }

  /** calibration_sets.unit_edges: the resistivity edges the set fitted for a
   * geology unit, by name.
   * @param {Rec} s
   * @param {string|null} glg
   * @returns {Object<string, number>} */
  function unitEdges(s, glg) {
    /** @type {Object<string, number>} */
    var out = {};
    s.edges.forEach(function (row) {
      if (row.fitted && row.glg === glg) out[row.edge] = Number(row.value);
    });
    return out;
  }

  /** calibration_sets.config_for_unit: config with the set in force's edges
   * for a geology unit in its VES settings, or config itself.
   * @param {Config} config
   * @param {string|null} glg
   * @returns {Config} */
  function configForUnit(config, glg) {
    var edges = unitEdges(inForce(config), glg);
    if (!Object.keys(edges).length) return config;
    return Object.assign({}, config, { ves: Object.assign({}, config.ves, edges) });
  }

  /** calibration_sets.config_for_sounding: the configuration a sounding is
   * interpreted with, the set in force's edges for the geology unit under
   * it; config itself, with nothing looked up, where the set fitted none.
   * @param {Config} config
   * @param {Sounding} sounding
   * @param {number|null} [zone]
   * @param {{lat: number, lon: number}|null} [fallback] the site's position
   * @returns {Config} */
  function configForSounding(config, sounding, zone, fallback) {
    if (!inForce(config).edges.some(function (row) { return row.fitted; })) return config;
    var site = sounding.site || {};
    var where = { site_easting: site.easting, site_northing: site.northing };
    var held = zone !== null && zone !== undefined ? zone : (site.utm_zone === undefined ? null : site.utm_zone);
    var ground = groundAt(pointLatLon(/** @type {*} */ (where), held, fallback || null));
    return configForUnit(config, ground[1]);
  }

  /** calibration_sets.set_changes: what the set changes besides the priors,
   * the edges it reads each geology unit by and the suitability weights.
   * @param {Rec} s
   * @returns {string[]} */
  function setChanges(s) {
    /** @type {string[]} */
    var units = [];
    s.edges.forEach(function (row) {
      if (row.fitted && units.indexOf(row.glg) < 0) units.push(row.glg);
    });
    var out = units.sort(codePointCompare).map(function (glg) {
      var edges = unitEdges(s, glg), parts = [];
      if ('clay_max_rho' in edges) parts.push(phrase('calibration_sets.edge_clay', { value: edges.clay_max_rho }));
      if ('fresh_basement_min_rho' in edges) {
        parts.push(phrase('calibration_sets.edge_basement', { value: edges.fresh_basement_min_rho }));
      }
      return phrase('calibration_sets.changes_edges', { version: s.version, glg: glg, edges: parts.join(' and ') });
    });
    if (s.weights !== null && s.weights.fitted) {
      var value = s.weights.value;
      out.push(phrase('calibration_sets.changes_weights', { version: s.version,
        thickness: value.aquifer_thickness, fit: value.resistivity_fit, overburden: value.overburden,
        fracture: value.basal_fracture }));
    }
    return out;
  }

  /** calibration_sets.set_review: what a fitted set holds, before anyone
   * adopts it, set beside the set in force: what it was fitted to and left
   * out, what it fits, and a table each of the priors, the edges and the
   * weights, in force and fitted; config is the one it was fitted with. A
   * pooled set (poolSets) has a table of the sets it pools first, its edges
   * without the misread layers its sources did not carry, and no weights.
   * @param {Rec} candidate
   * @param {Config} [config]
   * @returns {{title: string, summary: string[], tables: Rec[], adoptable: boolean}} */
  function setReview(candidate, config) {
    var cfg = config || defaultConfig();
    var held = inForce(cfg);
    var minimum = Math.trunc(Number(cfg.ledger.fit_min_boreholes));
    var prior = candidate.prior, edges = candidate.edges, weights = candidate.weights;
    /** @type {Rec[]} */
    var sources = candidate.sources;
    var pooled = sources.length > 0;
    var summary = [pooled
      ? phrase('calibration_sets.review_lead_pooled', { k: sources.length,
        rate: candidate.success_yield_m3_per_h || 0.0 })
      : phrase('calibration_sets.review_lead', { n: candidate.boreholes,
        rate: candidate.success_yield_m3_per_h || 0.0 })];
    var left = candidate.left_out;
    if (left.unknown || left.definition) {
      summary.push(phrase('calibration_sets.review_left_out', { unknown: left.unknown,
        definition: left.definition }));
    }
    function fittedCount(rows) { return rows.filter(function (r) { return r.fitted; }).length; }
    summary.push(phrase('calibration_sets.review_fitted', { priors: fittedCount(prior),
      rows: prior.length, edges: fittedCount(edges), edge_rows: edges.length, minimum: minimum }));
    if (pooled) {
      summary.push(phrase('calibration_sets.review_weights_pooled'));
      /** @type {Map<string, number>} */
      var issued = new Map();
      sources.forEach(function (source) {
        if (source.organisation) issued.set(source.organisation, (issued.get(source.organisation) || 0) + 1);
      });
      Array.from(issued.keys()).sort(codePointCompare).forEach(function (name) {
        var n = /** @type {number} */ (issued.get(name));
        if (n > 1) summary.push(phrase('calibration_sets.review_same_organisation', { organisation: name, n: n }));
      });
    } else if (weights !== null && weights.fitted) {
      summary.push(phrase('calibration_sets.review_weights', { right: rangeShare(weights.right),
        pairs: weights.successes * weights.failures,
        right_base: rangeShare(weights.right_base || 0.0) }));
    } else if (weights !== null) {
      summary.push(phrase('calibration_sets.review_weights_few', { successes: weights.successes,
        failures: weights.failures, minimum: Math.trunc(Number(cfg.ledger.fit_weights_min_each)) }));
    }
    var adoptable = prior.concat(edges).some(function (r) { return r.fitted; }) ||
      Boolean(weights !== null && weights.fitted);
    summary.push(phrase('calibration_sets.review_in_force', { name: setName(held) }));
    summary.push(phrase(adoptable ? 'calibration_sets.review_adopt'
      : 'calibration_sets.review_nothing'));
    if (adoptable) {
      summary.push(candidate.licence
        ? phrase('calibration_sets.review_licence', { licence: candidate.licence })
        : phrase('calibration_sets.review_no_licence'));
    }

    /** @type {Rec[]} */
    var tables = [];
    if (pooled) {
      var unnamed = phrase('calibration_sets.cell_not_named');
      tables.push({ key: 'sources', caption: phrase('calibration_sets.sources_caption'),
        header: [
          'calibration_sets.sources_col_organisation', 'calibration_sets.sources_col_set',
          'calibration_sets.sources_col_licence', 'calibration_sets.sources_col_contact'
        ].map(function (id) { return phrase(id); }),
        rows: sources.map(function (source) {
          return [source.organisation || unnamed,
            setCalled(source.version, source.fitted_on, source.boreholes, source.adopted_by, source.adopted_on,
              source.sets),
            source.licence, source.contact || unnamed];
        }) });
    }
    var rate = Number(cfg.odds.success_yield_m3_per_h);
    var calibration = cfg.calibration || null;
    var priorRows = prior.map(function (row) {
      var anyUnit = row.glg === '*';
      var ground = anyUnit ? phrase('calibration_sets.ground_class', { code: row.bgs_code })
        : phrase('calibration_sets.ground_combination', { code: row.bgs_code, glg: row.glg });
      var now = priorFor(row.bgs_code, anyUnit ? null : row.glg, rate, calibration);
      var fitted = row.fitted
        ? phrase('calibration_sets.cell_rate_worth', { p: rangeShare(row.rate), n: row.effective_n })
        : phrase('calibration_sets.cell_too_few', { m: row.boreholes, minimum: minimum });
      return [ground, String(row.boreholes), String(row.successes),
        phrase('calibration_sets.cell_rate', { p: rangeShare(row.base_rate) }),
        phrase('calibration_sets.cell_rate', { p: rangeShare(now.rate) }), fitted];
    });
    tables.push({ key: 'prior', caption: phrase('calibration_sets.prior_caption'),
      header: [
        'calibration_sets.prior_col_ground', 'calibration_sets.prior_col_boreholes',
        'calibration_sets.prior_col_succeeded', 'calibration_sets.prior_col_table',
        'calibration_sets.prior_col_in_force', 'calibration_sets.prior_col_fitted'
      ].map(function (id) { return phrase(id); }),
      rows: priorRows });
    var names = phraseTable('calibration_sets.edge_names');
    tables.push({ key: 'edges', caption: phrase('calibration_sets.edges_caption'),
      header: [
        'calibration_sets.edges_col_unit', 'calibration_sets.edges_col_edge',
        'calibration_sets.edges_col_layers', 'calibration_sets.edges_col_in_force',
        'calibration_sets.edges_col_fitted'
      ].map(function (id) { return phrase(id); }),
      rows: edges.map(function (row) {
        var now, fitted;
        if (pooled) {
          now = phrase('calibration_sets.cell_edge_value', { value: row.base });
          fitted = row.fitted ? phrase('calibration_sets.cell_edge_pooled', { value: row.value, sets: row.sets })
            : !row.sets ? phrase('calibration_sets.cell_edge_pooled_none')
              : row.edge === 'clay_max_rho' ? phrase('calibration_sets.cell_edge_pooled_window')
                : phrase('calibration_sets.cell_edge_pooled_clay');
        } else {
          now = phrase('calibration_sets.cell_edge', { value: row.base, misread: row.misread_base });
          fitted = row.fitted
            ? phrase('calibration_sets.cell_edge', { value: row.value, misread: row.misread })
            : phrase('calibration_sets.cell_edge_too_few', { m: row.boreholes, minimum: minimum });
        }
        return [row.glg, names[row.edge],
          phrase('calibration_sets.cell_layers', { below: row.below, above: row.above }), now, fitted];
      }) });
    if (weights !== null) {
      var parts = phraseTable('calibration_sets.part_names');
      tables.push({ key: 'weights', caption: phrase('calibration_sets.weights_caption'),
        header: [
          'calibration_sets.weights_col_part', 'calibration_sets.weights_col_in_force',
          'calibration_sets.weights_col_fitted'
        ].map(function (id) { return phrase(id); }),
        rows: SUITABILITY_PARTS.map(function (key) {
          return [parts[key], phrase('calibration_sets.cell_weight', { w: weights.base[key] }),
            weights.fitted ? phrase('calibration_sets.cell_weight', { w: weights.value[key] })
              : phrase('calibration_sets.cell_not_fitted')];
        }) });
    }
    return { title: phrase(pooled ? 'calibration_sets.review_title_pooled' : 'calibration_sets.review_title',
      { fitted_on: candidate.fitted_on }),
    summary: summary, tables: tables, adoptable: adoptable };
  }

  /* ---------------------------------------------------------------- pooling */

  /* calibration_sets._FINGERPRINTED: what a set counts and what it pooled,
   * not who adopted it, when, or under which name or licence */
  var SET_FINGERPRINTED = ['format', 'success_yield_m3_per_h', 'boreholes', 'left_out', 'prior', 'edges',
    'weights', 'sources'];

  /** calibration_sets.set_fingerprint: the SHA-256, in hex, of what the set
   * counts, written as its file writes it; the set is read whole first, so
   * a file of format 1 is fingerprinted as format 2 reads it.
   * @param {*} raw
   * @returns {string} */
  function setFingerprint(raw) {
    var s = cleanSet(raw);
    /** @type {Rec} */
    var part = {};
    SET_FINGERPRINTED.forEach(function (key) { part[key] = s[key]; });
    /** @type {string[]} */
    var lines = [];
    setEmit(part, 0, lines);
    return sha256Hex(lines.join('\n') + '\n');
  }

  /* the fingerprints of the set and of every set it holds counts of */
  function setChain(s, fingerprint) {
    /** @type {Object<string, boolean>} */
    var out = {};
    out[fingerprint] = true;
    s.sources.forEach(function (source) {
      out[source.fingerprint] = true;
      source.pools.forEach(function (p) { out[p] = true; });
    });
    return out;
  }

  /* the position of a set's prior row in the provisional table, or -1
   * where the table has no such row or only its even-chance fallback */
  function setTableRow(table, row) {
    for (var k = 0; k < table.length; k++) {
      var r = table[k];
      if (r.bgs_code === row.bgs_code && r.glg === row.glg && r.status !== 'fallback') return k;
    }
    return -1;
  }

  function setCodeOrder(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  /** calibration_sets.pool_sets: the calibration sets (as read from their
   * files) pooled into one, numbered and adopted by no one yet, to be issued
   * under ledger.set_licence. Each set must be read whole, adopted by a
   * named person, issued under that same licence (which may not be blank)
   * and judged at one definition of success; no two may be the same set or
   * hold the counts of one same set;
   * each prior row must start from this toolkit's provisional row. Anything
   * else throws, naming the set by its label (its file, in the apps), else
   * by its place. Each ground's counts are summed and its rate worked out
   * from the provisional row, counted once; each edge is the mean of the
   * logarithms of the sets' fitted edges weighted by the boreholes behind
   * each, rounded to 0.1 ohm-m; the weights are not pooled. The sets are
   * taken in the order of their fingerprints.
   * @param {Array<*>} sets
   * @param {string} pooledOn
   * @param {Config} [config]
   * @param {string[]|null} [labels]
   * @returns {Rec} */
  function poolSets(sets, pooledOn, config, labels) {
    var cfg = config || defaultConfig();
    var names = labels ? labels.map(String)
      : sets.map(function (_, k) { return phrase('calibration_sets.pool_label', { k: k + 1 }); });
    if (sets.length < 2) throw new Error(phrase('calibration_sets.pool_too_few'));
    var licence = ledgerName(cfg.ledger.set_licence);
    if (!licence) throw new Error(phrase('calibration_sets.pool_no_licence'));
    /** @type {Rec[]} */
    var clean = sets.map(function (raw, i) {
      var label = names[i], s;
      try {
        s = cleanSet(raw);
      } catch (e) {
        throw new Error(phrase('calibration_sets.pool_file', { label: label,
          reason: String(/** @type {*} */ (e).message) }));
      }
      if (s.version === 0) throw new Error(phrase('calibration_sets.pool_default', { label: label }));
      if (s.version === null) throw new Error(phrase('calibration_sets.pool_unadopted', { label: label }));
      if (!s.licence) throw new Error(phrase('calibration_sets.pool_unlicensed', { label: label }));
      /* the toolkit cannot read what a licence allows, so it pools only sets
       * issued under the one it issues the pooled set under */
      if (s.licence !== licence) {
        throw new Error(phrase('calibration_sets.pool_other_licence', { label: label, licence: s.licence,
          ours: licence }));
      }
      if (s.success_yield_m3_per_h === null) {
        throw new Error(phrase('calibration_sets.pool_no_definition', { label: label }));
      }
      return s;
    });
    var rateM3h = clean[0].success_yield_m3_per_h;
    clean.slice(1).forEach(function (s, i) {
      if (!(Math.abs(s.success_yield_m3_per_h - rateM3h) < 1e-9)) {
        throw new Error(phrase('calibration_sets.pool_definition', { label: names[i + 1],
          rate: s.success_yield_m3_per_h, first: names[0], first_rate: rateM3h }));
      }
    });
    var prints = clean.map(setFingerprint);
    var chains = clean.map(function (s, i) { return setChain(s, prints[i]); });
    for (var j = 0; j < clean.length; j++) {
      for (var i = 0; i < j; i++) {
        if (prints[i] === prints[j]) {
          throw new Error(phrase('calibration_sets.pool_same', { label: names[j], other: names[i] }));
        }
        var shared = Object.keys(chains[i]).some(function (p) { return chains[j][p] === true; });
        if (shared) throw new Error(phrase('calibration_sets.pool_chain', { label: names[j], other: names[i] }));
      }
    }
    var table = oddsTables().prior;
    function provisional(k) {
      var base = table[k];
      return [priorFor(base.bgs_code, base.glg !== '*' ? base.glg : null, rateM3h, null).rate,
        Number(base.effective_n)];
    }
    clean.forEach(function (s, i) {
      s.prior.forEach(function (row) {
        var k = setTableRow(table, row);
        if (k < 0 || pyRound(provisional(k)[0], 4) !== row.base_rate || provisional(k)[1] !== row.base_n) {
          var ground = row.glg === '*' ? phrase('calibration_sets.ground_class', { code: row.bgs_code })
            : phrase('calibration_sets.ground_combination', { code: row.bgs_code, glg: row.glg });
          throw new Error(phrase('calibration_sets.pool_table', { label: names[i], ground: ground }));
        }
      });
    });

    var order = clean.map(function (_, i) { return i; })
      .sort(function (a, b) { return setCodeOrder(prints[a], prints[b]); });
    /** @type {Object<string, number[]>} */
    var counts = {};
    /* by unit, then by edge; a Map, since a hand-edited unit may be named
     * anything */
    /** @type {Map<string, Map<string, Rec>>} */
    var sides = new Map();
    var left = { unknown: 0, definition: 0 };
    order.forEach(function (i) {
      var s = clean[i];
      left.unknown += s.left_out.unknown;
      left.definition += s.left_out.definition;
      s.prior.forEach(function (row) {
        var k = setTableRow(table, row);
        var held = counts[k] || (counts[k] = [0, 0, 0.0]);
        held[0] += row.boreholes;
        held[1] += row.successes;
        held[2] = held[2] + row.expected;
      });
      s.edges.forEach(function (row) {
        if (!sides.has(row.glg)) sides.set(row.glg, new Map());
        var unit = /** @type {Map<string, Rec>} */ (sides.get(row.glg));
        if (!unit.has(row.edge)) unit.set(row.edge, { all: [0, 0, 0], fit: [0, 0, 0], sets: 0, logs: 0.0, weight: 0 });
        var held = /** @type {Rec} */ (unit.get(row.edge));
        [[held.all, true], [held.fit, row.fitted]].forEach(function (pair) {
          if (!pair[1]) return;
          pair[0][0] += row.boreholes;
          pair[0][1] += row.below;
          pair[0][2] += row.above;
        });
        if (row.fitted) {
          held.sets += 1;
          held.logs = held.logs + row.boreholes * Math.log(row.value);
          held.weight += row.boreholes;
        }
      });
    });

    var minimum = cfg.ledger.fit_min_boreholes;
    var prior = Object.keys(counts).map(Number).sort(function (a, b) { return a - b; }).map(function (k) {
      var base = provisional(k), m = counts[k][0];
      var expected = pyRound(counts[k][2], 2);
      var fitted = m >= minimum;
      var rate = (base[1] * base[0] + expected) / (base[1] + m);
      return {
        bgs_code: table[k].bgs_code, glg: table[k].glg, boreholes: m, successes: counts[k][1],
        expected: expected, base_rate: pyRound(base[0], 4), base_n: base[1], fitted: fitted,
        rate: fitted ? Math.min(Math.max(pyRound(rate, 4), SET_RATE_BOUND), 1.0 - SET_RATE_BOUND) : null,
        effective_n: fitted ? base[1] + m : null,
      };
    });

    /** @type {Rec[]} */
    var edges = [];
    var base = { clay_max_rho: Number(cfg.ves.clay_max_rho),
      fresh_basement_min_rho: Number(cfg.ves.fresh_basement_min_rho) };
    var force = inForce(cfg);
    var ceiling = Number(cfg.ves.fractured_zone_rho[1]);
    Array.from(sides.keys()).sort(codePointCompare).forEach(function (glg) {
      var here = Object.assign({}, base, unitEdges(force, glg));
      var unit = /** @type {Map<string, Rec>} */ (sides.get(glg));
      /* in force, the pooled set replaces the set in force, so a unit whose
       * clay edge it does not fit is read by the configuration's */
      var clay = base.clay_max_rho;
      SET_EDGES.forEach(function (edge) {
        var held = unit.get(edge);
        if (!held) return;
        var value = held.sets ? pyRound(Math.exp(held.logs / held.weight), 1) : null;
        var fitted = value !== null && (edge === 'clay_max_rho' ? value < ceiling : value > clay);
        if (fitted && edge === 'clay_max_rho') clay = /** @type {number} */ (value);
        var n = held.sets ? held.fit : held.all;
        edges.push({ glg: glg, edge: edge, boreholes: n[0], below: n[1], above: n[2], base: here[edge],
          misread_base: null, fitted: fitted, value: fitted ? value : null, misread: null, sets: held.sets });
      });
    });

    var sources = order.map(function (i) {
      var s = clean[i];
      return { organisation: s.organisation, contact: s.contact, licence: s.licence, version: s.version,
        fitted_on: s.fitted_on, adopted_by: s.adopted_by, adopted_on: s.adopted_on, boreholes: s.boreholes,
        sets: s.sources.length, fingerprint: prints[i],
        pools: Object.keys(chains[i]).filter(function (p) { return p !== prints[i]; }).sort(setCodeOrder) };
    });
    return Object.assign(defaultSet(), {
      licence: licence, version: null, fitted_on: String(pooledOn),
      success_yield_m3_per_h: rateM3h, boreholes: null, left_out: left, prior: prior, edges: edges,
      weights: null, sources: sources,
    });
  }

  function setUnreadable(why) {
    return new Error(phrase('calibration_sets.unreadable', { why: why }));
  }

  function setIsInt(v) { return typeof v === 'number' && Number.isInteger(v); }
  function setIsNum(v) { return typeof v === 'number' && isFinite(v); }
  function setText(v) { return typeof v === 'string'; }
  function setCount(v) { return setIsInt(v) && v >= 0; }
  function setPositive(v) { return setIsNum(v) && v > 0; }
  function setRate(v) { return setIsNum(v) && v > 0 && v < 1; }
  function setFlag(v) { return typeof v === 'boolean'; }
  function setMaybe(check) { return function (v) { return v === null || check(v); }; }

  /* raw[key] where check passes it, else the reason the file cannot be
   * read, naming the field */
  function setField(raw, key, check, where) {
    if (!isRecord(raw) || !Object.prototype.hasOwnProperty.call(raw, key) || !check(raw[key])) {
      throw setUnreadable(phrase('calibration_sets.why_field', { field: (where || '') + key }));
    }
    return raw[key];
  }

  function setWeightTable(v) {
    return isRecord(v) && SUITABILITY_PARTS.every(function (key) { return setIsNum(v[key]) && v[key] >= 0; });
  }

  function setCleanWeights(raw) {
    if (raw === null) return null;
    var fitted = setField(raw, 'fitted', setFlag, 'weights.');
    var base = setField(raw, 'base', setWeightTable, 'weights.');
    var value = setField(raw, 'value', fitted ? setWeightTable : setMaybe(setWeightTable), 'weights.');
    if (value !== null) {
      var sum = 0;
      SUITABILITY_PARTS.forEach(function (key) { sum += value[key]; });
      if (Math.abs(sum - 1.0) > 1e-9) throw setUnreadable(phrase('calibration_sets.why_weights'));
    }
    function table(t) {
      /** @type {Rec} */
      var out = {};
      SUITABILITY_PARTS.forEach(function (key) { out[key] = t[key]; });
      return out;
    }
    return {
      successes: setField(raw, 'successes', setCount, 'weights.'),
      failures: setField(raw, 'failures', setCount, 'weights.'),
      base: table(base),
      right_base: setField(raw, 'right_base', setMaybe(setIsNum), 'weights.'),
      fitted: fitted,
      value: value !== null ? table(value) : null,
      right: setField(raw, 'right', fitted ? setIsNum : setMaybe(setIsNum), 'weights.'),
    };
  }

  function setNone(v) { return v === null; }
  /* a SHA-256 in lower-case hex, as setFingerprint writes it */
  function setHex(v) { return typeof v === 'string' && /^[0-9a-f]{64}$/.test(v); }

  /* the boreholes a file of format 1 listed by their ledger ids, checked as
   * that format was and counted: the ids are not kept */
  function setListedBoreholes(raw) {
    var uses = ['prior'].concat(SET_EDGES, ['weights']);
    var listed = setField(raw, 'boreholes', Array.isArray);
    listed.forEach(function (item) {
      setField(item, 'id', function (v) { return typeof v === 'string' && v.length > 0; }, 'boreholes.');
      setField(item, 'success', setFlag, 'boreholes.');
      setField(item, 'forecast', setFlag, 'boreholes.');
      setField(item, 'uses', function (v) {
        return Array.isArray(v) && v.every(function (u) { return uses.indexOf(u) >= 0; });
      }, 'boreholes.');
    });
    return listed.length;
  }

  /* one of a pooled set's sources, read whole */
  function setCleanSource(item) {
    /** @type {Rec} */
    var out = {};
    ['organisation', 'contact', 'licence'].forEach(function (key) {
      out[key] = ledgerName(setField(item, key, setText, 'sources.'));
    });
    out.version = setField(item, 'version', function (v) { return setCount(v) && v > 0; }, 'sources.');
    out.fitted_on = setField(item, 'fitted_on', setText, 'sources.');
    out.adopted_by = ledgerName(setField(item, 'adopted_by', function (v) { return !!ledgerName(v); }, 'sources.'));
    out.adopted_on = setField(item, 'adopted_on', setText, 'sources.');
    out.boreholes = setField(item, 'boreholes', setMaybe(setCount), 'sources.');
    out.sets = setField(item, 'sets', setCount, 'sources.');
    if ((out.boreholes === null) !== (out.sets > 0)) throw setUnreadable(phrase('calibration_sets.why_pooled'));
    out.fingerprint = setField(item, 'fingerprint', setHex, 'sources.');
    out.pools = setField(item, 'pools', function (v) { return Array.isArray(v) && v.every(setHex); },
      'sources.').slice();
    return out;
  }

  /** calibration_sets.clean_set: a set read from a file, in the shape the
   * functions here write, or an Error with the sentence the app shows. A
   * file is read whole or not at all; a file of format 1 is read as format
   * 2, its ledger ids counted and dropped.
   * @param {*} raw
   * @returns {Rec} */
  function cleanSet(raw) {
    if (!isRecord(raw)) throw setUnreadable(phrase('calibration_sets.why_not_mapping'));
    var old = raw.format_version === 1;
    if (raw.format !== SET_FORMAT || !setIsInt(raw.format_version) || SET_READS.indexOf(raw.format_version) < 0) {
      throw setUnreadable(phrase('calibration_sets.why_format', { expected: SET_FORMAT_VERSION }));
    }
    /** @type {Rec} */
    var out = { format: SET_FORMAT, format_version: SET_FORMAT_VERSION };
    ['licence', 'organisation', 'contact'].forEach(function (key) {
      out[key] = old ? '' : ledgerName(setField(raw, key, setText));
    });
    var version = setField(raw, 'version', setMaybe(setCount));
    out.version = version;
    ['fitted_on', 'adopted_by', 'adopted_on'].forEach(function (key) { out[key] = setField(raw, key, setText); });
    out.adopted_by = ledgerName(out.adopted_by);
    if ((version !== null && version > 0) !== !!out.adopted_by) {
      throw setUnreadable(phrase('calibration_sets.why_unadopted'));
    }
    var replaces = setField(raw, 'replaces', function (v) { return v === null || isRecord(v); });
    if (replaces !== null) {
      replaces = {
        version: setField(replaces, 'version', setCount, 'replaces.'),
        fitted_on: setField(replaces, 'fitted_on', setText, 'replaces.'),
        adopted_by: setField(replaces, 'adopted_by', setText, 'replaces.'),
        adopted_on: setField(replaces, 'adopted_on', setText, 'replaces.'),
      };
    }
    out.replaces = replaces;
    out.success_yield_m3_per_h = setField(raw, 'success_yield_m3_per_h', setMaybe(setPositive));
    out.boreholes = old ? setListedBoreholes(raw) : setField(raw, 'boreholes', setMaybe(setCount));
    var left = setField(raw, 'left_out', isRecord);
    out.left_out = { unknown: setField(left, 'unknown', setCount, 'left_out.'),
      definition: setField(left, 'definition', setCount, 'left_out.') };
    /** @type {Rec[]} */
    var sources = old ? [] : setField(raw, 'sources', Array.isArray).map(setCleanSource);
    var pooled = sources.length > 0;
    if ((out.boreholes === null) !== pooled) throw setUnreadable(phrase('calibration_sets.why_pooled'));
    /** @type {Object<string, boolean>} */
    var grounds = {};
    out.prior = setField(raw, 'prior', Array.isArray).map(function (row) {
      var fitted = setField(row, 'fitted', setFlag, 'prior.');
      var clean = {
        bgs_code: setField(row, 'bgs_code', setText, 'prior.'),
        glg: setField(row, 'glg', setText, 'prior.'),
        boreholes: setField(row, 'boreholes', setCount, 'prior.'),
        successes: setField(row, 'successes', setCount, 'prior.'),
        expected: setField(row, 'expected', setIsNum, 'prior.'),
        base_rate: setField(row, 'base_rate', setIsNum, 'prior.'),
        base_n: setField(row, 'base_n', setPositive, 'prior.'),
        fitted: fitted,
        rate: setField(row, 'rate', fitted ? setRate : setMaybe(setRate), 'prior.'),
        effective_n: setField(row, 'effective_n', fitted ? setPositive : setMaybe(setPositive), 'prior.'),
      };
      if (!(clean.boreholes > 0) || clean.successes > clean.boreholes ||
          !(clean.expected >= 0 && clean.expected <= clean.boreholes)) {
        throw setUnreadable(phrase('calibration_sets.why_counts'));
      }
      var key = JSON.stringify([clean.bgs_code, clean.glg]);
      if (grounds[key] === true) {
        throw setUnreadable(phrase('calibration_sets.why_twice_prior', { code: clean.bgs_code, glg: clean.glg }));
      }
      grounds[key] = true;
      return clean;
    });
    /** @type {Object<string, boolean>} */
    var seen = {};
    out.edges = setField(raw, 'edges', Array.isArray).map(function (row) {
      var fitted = setField(row, 'fitted', setFlag, 'edges.');
      /** @type {Rec} */
      var clean = {
        glg: setField(row, 'glg', setText, 'edges.'),
        edge: setField(row, 'edge', function (v) { return SET_EDGES.indexOf(v) >= 0; }, 'edges.'),
        boreholes: setField(row, 'boreholes', setCount, 'edges.'),
        below: setField(row, 'below', setCount, 'edges.'),
        above: setField(row, 'above', setCount, 'edges.'),
        base: setField(row, 'base', setPositive, 'edges.'),
        /* a pooled set's sources did not carry their layers, so it cannot
         * say how many its edges misread */
        misread_base: setField(row, 'misread_base', pooled ? setNone : setCount, 'edges.'),
        fitted: fitted,
        value: setField(row, 'value', fitted ? setPositive : setMaybe(setPositive), 'edges.'),
        misread: setField(row, 'misread', pooled ? setNone : fitted ? setCount : setMaybe(setCount), 'edges.'),
      };
      if (pooled) {
        clean.sets = setField(row, 'sets', function (v) { return setCount(v) && (v > 0 || !fitted); }, 'edges.');
      }
      if (!(clean.boreholes > 0)) throw setUnreadable(phrase('calibration_sets.why_counts'));
      var key = JSON.stringify([clean.glg, clean.edge]);
      if (seen[key] === true) {
        throw setUnreadable(phrase('calibration_sets.why_twice_edge', { glg: clean.glg, edge: clean.edge }));
      }
      seen[key] = true;
      return clean;
    });
    out.weights = setCleanWeights(setField(raw, 'weights', function (v) { return v === null || isRecord(v); }));
    if (pooled && out.weights !== null) throw setUnreadable(phrase('calibration_sets.why_pooled'));
    out.sources = sources;
    return out;
  }

  /* one value as the set file writes it: text in double quotes, a whole
   * number without a point, any other number as the shortest text that
   * reads back to it */
  function setScalar(value) {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (typeof value === 'number') return String(value);
    var out = '', text = String(value);
    for (var i = 0; i < text.length;) {
      /* by code point, as Python reads a string: a lone surrogate is one */
      var code = /** @type {number} */ (text.codePointAt(i));
      var ch = String.fromCodePoint(code);
      i += code > 0xffff ? 2 : 1;
      if (ch === '"' || ch === '\\') {
        out += '\\' + ch;
      } else if (code < 0x20 || code >= 0x7f && code <= 0x9f) {
        out += '\\x' + (code < 16 ? '0' : '') + code.toString(16).toUpperCase();
      } else if (code === 0x2028 || code === 0x2029 || code === 0xfeff || code === 0xfffe ||
          code === 0xffff || code >= 0xd800 && code <= 0xdfff) {
        /* YAML breaks a line at the two separators, and refuses the rest */
        out += '\\u' + ('000' + code.toString(16).toUpperCase()).slice(-4);
      } else {
        out += ch;
      }
    }
    return '"' + out + '"';
  }

  function setEmpty(v) {
    return Array.isArray(v) ? v.length === 0 : isRecord(v) && Object.keys(v).length === 0;
  }

  function setEmit(value, indent, lines) {
    var pad = new Array(indent + 1).join(' ');
    if (!Array.isArray(value)) {
      Object.keys(value).forEach(function (key) {
        var item = value[key];
        if ((Array.isArray(item) || isRecord(item)) && !setEmpty(item)) {
          lines.push(pad + key + ':');
          setEmit(item, indent + 2, lines);
        } else {
          lines.push(pad + key + ': ' + (Array.isArray(item) ? '[]' : isRecord(item) ? '{}' : setScalar(item)));
        }
      });
      return;
    }
    value.forEach(function (item) {
      if (isRecord(item) && !setEmpty(item)) {
        var nested = [];
        setEmit(item, indent + 2, nested);
        lines.push(pad + '- ' + nested[0].slice(indent + 2));
        for (var i = 1; i < nested.length; i++) lines.push(nested[i]);
      } else {
        lines.push(pad + '- ' + setScalar(item));
      }
    });
  }

  /** calibration_sets.set_yaml: the set as its calibration.yaml, byte for
   * byte as the Python engine writes it.
   * @param {Rec} s
   * @returns {string} */
  function setYaml(s) {
    var lines = ['# A calibration set of the groundwater toolkit (PLAN.md steps 5.3 and 5.5).'];
    setEmit(s, 0, lines);
    return lines.join('\n') + '\n';
  }

  Object.assign(C, {
    SET_FORMAT: SET_FORMAT, SET_FORMAT_VERSION: SET_FORMAT_VERSION, SET_EDGES: SET_EDGES,
    SUITABILITY_PARTS: SUITABILITY_PARTS,
    evidenceRate: evidenceRate, fitPrior: fitPrior, layerClass: layerClass, fitEdges: fitEdges,
    fitWeights: fitWeights, defaultSet: defaultSet, fitSet: fitSet, adoptSet: adoptSet,
    setName: setName, cleanSet: cleanSet, setYaml: setYaml,
    inForce: inForce, checkInForce: checkInForce, applySet: applySet, fittedPrior: fittedPrior,
    unitEdges: unitEdges, configForUnit: configForUnit, configForSounding: configForSounding,
    setChanges: setChanges,
    setReview: setReview,
    setFingerprint: setFingerprint, poolSets: poolSets,
  });

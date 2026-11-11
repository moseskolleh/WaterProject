
  /* ============================================================ calibration
   * groundwater/calibration.py (PLAN.md step 5.2). The forecasts in a pooled
   * ledger scored against what was drilled: the depth to basement found
   * against the P10 to P90 band, with the range a calibrated band's count
   * inside falls in nine times in ten; the chance of success by its Brier
   * score beside the prior's, and by a reliability diagram; and the hit rate
   * by geology unit, survey team and contractor. Only predictions recorded
   * before drilling are scored; the hit rates count every drilled point.
   * Below ledger.min_boreholes (ledger.min_group for a hit rate) the report
   * says there are too few boreholes to judge and gives the counts. Every
   * function takes the entries of poolLedgers. */

  /* calibration.BAND_COVERAGE: the share a calibrated P10 to P90 band holds */
  var BAND_COVERAGE = 0.8;
  var CALIBRATION_EXPECTED = [0.05, 0.95];
  var CALIBRATION_GROUPINGS = ['geology', 'team', 'contractor'];
  var CALIBRATION_BASES = ['tested', 'recorded_failure', 'recorded_success'];

  /* a sum taken one value at a time from 0, as utils.sum_in_order takes it */
  function calibrationSum(values) {
    var total = 0.0;
    for (var i = 0; i < values.length; i++) total = total + values[i];
    return total;
  }

  /** calibration.forecast_entries: the drilled entries whose prediction was
   * recorded before drilling, the only ones the band and the odds are
   * scored on.
   * @param {Rec[]} pooled
   * @returns {Rec[]} */
  function forecastEntries(pooled) {
    return pooled.filter(function (e) { return e.outcome !== null && e.before_outcome; });
  }

  /** calibration.binomial_range: the counts out of n that bound a binomial
   * at p, the smallest whose cumulative probability reaches low and the
   * smallest that reaches high, worked out from the most likely count
   * outward by products and quotients, as Python works them.
   * @param {number} n
   * @param {number} p
   * @param {number} [low]
   * @param {number} [high]
   * @returns {number[]} */
  function binomialRange(n, p, low, high) {
    var lowAt = low === undefined ? CALIBRATION_EXPECTED[0] : low;
    var highAt = high === undefined ? CALIBRATION_EXPECTED[1] : high;
    if (n <= 0) return [0, 0];
    var q = 1.0 - p;
    var mode = Math.min(n, Math.floor((n + 1) * p));
    var weights = [];
    for (var i = 0; i <= n; i++) weights.push(0.0);
    weights[mode] = 1.0;
    var k;
    for (k = mode; k < n; k++) weights[k + 1] = weights[k] * (n - k) * p / ((k + 1) * q);
    for (k = mode; k > 0; k--) weights[k - 1] = weights[k] * k * q / ((n - k + 1) * p);
    var total = calibrationSum(weights);
    var lo = n, hi = n, foundLo = false, foundHi = false, cumulative = 0.0;
    for (k = 0; k <= n; k++) {
      cumulative = cumulative + weights[k] / total;
      if (!foundLo && cumulative >= lowAt) { lo = k; foundLo = true; }
      if (!foundHi && cumulative >= highAt) { hi = k; foundHi = true; }
    }
    return [lo, hi];
  }

  /** calibration.depth_scores: the depth to basement found against the
   * predicted band, over the forecasts, with the verdict (too_few,
   * calibrated, narrow or wide), the bias and the mean distance.
   * @param {Rec[]} pooled
   * @param {Config} [config]
   * @returns {Rec} */
  function depthScores(pooled, config) {
    var cfg = config || defaultConfig();
    /** @type {Object<string, number>} */
    var counts = { inside: 0, shallower: 0, deeper: 0, unreached_allowed: 0, no_band: 0 };
    /** @type {Rec[]} */
    var points = [];
    /** @type {number[]} */
    var errors = [];
    forecastEntries(pooled).forEach(function (entry) {
      var prediction = entry.prediction, outcome = entry.outcome;
      var check = basementCheck(prediction, outcome) || 'no_band';
      counts[check] += 1;
      var best = prediction.depth_to_basement_m, found = outcome.basement_m;
      points.push({
        project: entry.project,
        sounding_id: entry.point.sounding_id,
        predicted: best,
        band: prediction.basement_band_m,
        found: found,
        total_depth_m: outcome.total_depth_m,
        check: check,
      });
      if (best !== null && found !== null) errors.push(found - best);
    });
    var judged = counts.inside + counts.shallower + counts.deeper;
    var minimum = Math.trunc(Number(cfg.ledger.min_boreholes));
    var expected = judged ? binomialRange(judged, BAND_COVERAGE) : null;
    var verdict;
    if (judged < minimum || expected === null) verdict = 'too_few';
    else if (counts.inside < expected[0]) verdict = 'narrow';
    else if (counts.inside > expected[1]) verdict = 'wide';
    else verdict = 'calibrated';
    return {
      points: points,
      drilled: points.length,
      judged: judged,
      inside: counts.inside,
      shallower: counts.shallower,
      deeper: counts.deeper,
      unreached: counts.unreached_allowed,
      no_band: counts.no_band,
      minimum: minimum,
      expected: expected,
      verdict: verdict,
      errors: errors.length,
      bias_m: errors.length ? pyRound(calibrationSum(errors) / errors.length, 2) : null,
      mean_abs_m: errors.length ? pyRound(calibrationSum(errors.map(Math.abs)) / errors.length, 2) : null,
    };
  }

  /* the forecast chance of success, or null where none was worked out or a
   * hand-edited file holds one outside 0 to 1 */
  function calibrationChance(prediction) {
    var odds = prediction.odds;
    var p = odds ? odds.probability : null;
    return p !== null && p !== undefined && p >= 0.0 && p <= 1.0 ? p : null;
  }

  function calibrationSquared(p, success) {
    var d = p - (success ? 1.0 : 0.0);
    return d * d;
  }

  /** calibration.odds_scores: the forecast chances of success against the
   * outcomes: the Brier score, the prior's, the skill, the reliability bins
   * and the bases the outcomes rest on. A forecast with no chance, no known
   * outcome, or an outcome judged at another definition of success than the
   * one in force is counted (no_odds, unknown, definition) and not scored.
   * @param {Rec[]} pooled
   * @param {Config} [config]
   * @returns {Rec} */
  function oddsScores(pooled, config) {
    var cfg = config || defaultConfig();
    /** @type {Rec[]} */
    var scored = [];
    var noOdds = 0, unknown = 0, definition = 0;
    forecastEntries(pooled).forEach(function (entry) {
      var p = calibrationChance(entry.prediction);
      var success = entry.outcome.success;
      if (p === null) { noOdds += 1; return; }
      if (success === null) { unknown += 1; return; }
      if (!usesDefinition(entry.outcome, cfg)) { definition += 1; return; }
      var prior = entry.prediction.odds.prior;
      scored.push({
        project: entry.project,
        sounding_id: entry.point.sounding_id,
        p: p,
        prior: prior !== null && prior >= 0.0 && prior <= 1.0 ? prior : null,
        success: success,
        basis: entry.outcome.success_basis,
      });
    });
    var n = scored.length;
    var minimum = Math.trunc(Number(cfg.ledger.min_boreholes));
    var nbins = Math.max(1, Math.trunc(Number(cfg.ledger.reliability_bins)));
    /** @type {Rec[][]} */
    var members = [];
    for (var b = 0; b < nbins; b++) members.push([]);
    scored.forEach(function (s) { members[Math.min(nbins - 1, Math.floor(s.p * nbins))].push(s); });
    var bins = members.map(function (inside, k) {
      var m = inside.length;
      var hits = inside.filter(function (s) { return s.success; }).length;
      return {
        low: pyRound(k / nbins, 3),
        high: pyRound((k + 1) / nbins, 3),
        n: m,
        successes: hits,
        mean_p: m ? pyRound(calibrationSum(inside.map(function (s) { return s.p; })) / m, 3) : null,
        observed: m ? pyRound(hits / m, 3) : null,
      };
    });
    /** @type {number|null} */
    var brier = null;
    /** @type {number|null} */
    var brierPrior = null;
    /** @type {number|null} */
    var skill = null;
    /** @type {number|null} */
    var meanP = null;
    if (n) {
      var raw = calibrationSum(scored.map(function (s) { return calibrationSquared(s.p, s.success); })) / n;
      meanP = pyRound(calibrationSum(scored.map(function (s) { return s.p; })) / n, 3);
      if (scored.every(function (s) { return s.prior !== null; })) {
        var rawPrior = calibrationSum(scored.map(function (s) {
          return calibrationSquared(s.prior, s.success);
        })) / n;
        if (rawPrior > 0.0) skill = pyRound(1.0 - raw / rawPrior, 3);
        brierPrior = pyRound(rawPrior, 4);
      }
      brier = pyRound(raw, 4);
    }
    var successes = scored.filter(function (s) { return s.success; }).length;
    /** @type {Object<string, number>} */
    var bases = {};
    CALIBRATION_BASES.forEach(function (basis) {
      bases[basis] = scored.filter(function (s) { return s.basis === basis; }).length;
    });
    return {
      scored: scored,
      n: n,
      successes: successes,
      failures: n - successes,
      no_odds: noOdds,
      unknown: unknown,
      definition: definition,
      bases: bases,
      minimum: minimum,
      verdict: n < minimum ? 'too_few' : 'scored',
      mean_p: meanP,
      brier: brier,
      brier_prior: brierPrior,
      skill: skill,
      bins: bins,
    };
  }

  /* the group an entry falls in, and whether it names one */
  function calibrationGroup(entry, by) {
    if (by === 'geology') {
      var odds = entry.prediction.odds;
      if (!odds) return [phrase('calibration.not_recorded'), false];
      if (!odds.bgs_code) return [phrase('calibration.geology_no_class'), false];
      if (odds.glg) return [phrase('calibration.geology', { code: odds.bgs_code, glg: odds.glg }), true];
      return [phrase('calibration.geology_class', { code: odds.bgs_code }), true];
    }
    var name = by === 'team' ? entry.prediction.survey_team : entry.outcome.contractor;
    if (name) return [name, true];
    return [phrase('calibration.not_recorded'), false];
  }

  /* two texts compared letter by letter, by code point, as Python compares
   * them (JavaScript's < compares UTF-16 code units, which puts a letter
   * outside the Basic Multilingual Plane before some inside it) */
  function codePointCompare(a, b) {
    var i = 0, j = 0;
    while (i < a.length && j < b.length) {
      var x = /** @type {number} */ (a.codePointAt(i)), y = /** @type {number} */ (b.codePointAt(j));
      if (x !== y) return x < y ? -1 : 1;
      i += x > 0xffff ? 2 : 1;
      j += y > 0xffff ? 2 : 1;
    }
    if (i < a.length) return 1;
    if (j < b.length) return -1;
    return 0;
  }

  /** calibration.hit_rates: the drilled points by geology unit, survey team
   * or contractor, each group with its counts (one judged at another
   * definition of success than the one in force counted as definition, and
   * neither successful nor not), its hit rate (null below ledger.min_group
   * known) and the mean chance forecast over its forecasts with a known
   * outcome at that definition. Named groups first, the most drilled first, then
   * by name; the groups that name none last.
   * @param {Rec[]} pooled
   * @param {string} by geology, team or contractor
   * @param {Config} [config]
   * @returns {Rec[]} */
  function hitRates(pooled, by, config) {
    if (CALIBRATION_GROUPINGS.indexOf(by) < 0) throw new Error('calibration: no hit rate by ' + by);
    var cfg = config || defaultConfig();
    var minimum = Math.trunc(Number(cfg.ledger.min_group));
    /** @type {Map<string, Rec>} */
    var groups = new Map();
    pooled.forEach(function (entry) {
      var outcome = entry.outcome;
      if (!outcome) return;
      var named = calibrationGroup(entry, by);
      var label = /** @type {string} */ (named[0]);
      var group = groups.get(label);
      if (!group) {
        group = { label: label, recorded: named[1], drilled: 0, success: 0, failure: 0, unknown: 0,
          definition: 0, chances: [] };
        groups.set(label, group);
      }
      group.drilled += 1;
      var judged = outcome.success !== null && usesDefinition(outcome, cfg);
      if (outcome.success === null) group.unknown += 1;
      else if (!judged) group.definition += 1;
      else if (outcome.success) group.success += 1;
      else group.failure += 1;
      var p = calibrationChance(entry.prediction);
      if (entry.before_outcome && judged && p !== null) group.chances.push(p);
    });
    /** @type {Rec[]} */
    var out = [];
    groups.forEach(function (group) {
      var known = group.success + group.failure;
      var ps = group.chances;
      out.push({
        label: group.label, recorded: group.recorded, drilled: group.drilled, success: group.success,
        failure: group.failure, unknown: group.unknown, definition: group.definition, known: known,
        rate: known >= minimum && known ? pyRound(group.success / known, 3) : null,
        forecast_n: ps.length,
        forecast_mean: ps.length ? pyRound(calibrationSum(ps) / ps.length, 3) : null,
      });
    });
    out.sort(function (a, b) {
      if (a.recorded !== b.recorded) return a.recorded ? -1 : 1;
      if (a.drilled !== b.drilled) return b.drilled - a.drilled;
      return codePointCompare(a.label, b.label);
    });
    return out;
  }

  /** @returns {{key: string, heading: string, paragraphs: string[], tables: Rec[], figures: Rec[],
   *   bullets: string[]}} */
  function calibrationSection(key, heading) {
    return { key: key, heading: heading, paragraphs: [], tables: [], figures: [], bullets: [] };
  }

  function calibrationDepthSection(depth, pooled) {
    var section = calibrationSection('depth', phrase('calibration.depth_heading'));
    var paragraphs = section.paragraphs;
    paragraphs.push(phrase('calibration.depth_intro'));
    if (!depth.drilled) return section;
    paragraphs.push(phrase('calibration.depth_counts', { drilled: depth.drilled, inside: depth.inside,
      shallower: depth.shallower, deeper: depth.deeper, unreached: depth.unreached, no_band: depth.no_band }));
    if (depth.verdict === 'too_few') {
      paragraphs.push(phrase('calibration.depth_too_few', { judged: depth.judged, minimum: depth.minimum }));
    } else {
      paragraphs.push(phrase('calibration.depth_judged', { inside: depth.inside, judged: depth.judged,
        share: rangeShare(depth.inside / depth.judged), low: depth.expected[0], high: depth.expected[1] }));
      if (depth.verdict === 'calibrated') {
        paragraphs.push(phrase('calibration.depth_calibrated'));
      } else if (depth.verdict === 'narrow') {
        paragraphs.push(phrase('calibration.depth_narrow', { shallower: depth.shallower, deeper: depth.deeper }));
      } else {
        paragraphs.push(phrase('calibration.depth_wide'));
      }
    }
    if (depth.errors) {
      var bias = depth.bias_m;
      if (bias > 0.0) {
        paragraphs.push(phrase('calibration.depth_bias_deeper', { bias: bias, mae: depth.mean_abs_m, n: depth.errors }));
      } else if (bias < 0.0) {
        paragraphs.push(phrase('calibration.depth_bias_shallower',
          { bias: -bias, mae: depth.mean_abs_m, n: depth.errors }));
      } else {
        paragraphs.push(phrase('calibration.depth_bias_none', { mae: depth.mean_abs_m, n: depth.errors }));
      }
    }
    if (depth.points.some(function (p) {
      return (p.predicted !== null || p.band !== null) && (p.found !== null || p.total_depth_m !== null);
    })) {
      section.figures.push({ key: 'depth', caption: phrase('calibration.depth_figure') });
    }
    var checks = phraseTable('ledger.basement_check');
    section.tables.push({
      header: [phrase('ledger.pool_col_project'), phrase('ledger.pool_col_point'),
        phrase('ledger.pool_col_basement'), phrase('ledger.pool_col_found'), phrase('ledger.pool_col_check')],
      rows: forecastEntries(pooled).map(function (entry, k) {
        return [entry.project, entry.point.sounding_id, ledgerBasementPredicted(entry.prediction),
          ledgerBasementFound(entry.outcome), String(checks[depth.points[k].check])];
      }),
      caption: phrase('calibration.depth_table'),
    });
    return section;
  }

  function calibrationPercent(fraction) {
    return phrase('calibration.percent', { p: rangeShare(fraction) });
  }

  function calibrationOddsSection(odds, cfg) {
    var section = calibrationSection('odds', phrase('calibration.odds_heading'));
    var paragraphs = section.paragraphs;
    var rate = Number(cfg.odds.success_yield_m3_per_h);
    paragraphs.push(phrase('calibration.odds_intro', { rate: rate }));
    if (!(odds.n || odds.no_odds || odds.unknown || odds.definition)) return section;
    if (odds.no_odds || odds.unknown) {
      paragraphs.push(phrase('calibration.odds_left_out', { no_odds: odds.no_odds, unknown: odds.unknown }));
    }
    if (odds.definition) {
      paragraphs.push(phrase('calibration.odds_definition', { n: odds.definition, rate: rate }));
    }
    if (odds.verdict === 'too_few') {
      paragraphs.push(phrase('calibration.odds_too_few', { n: odds.n, success: odds.successes,
        failure: odds.failures, minimum: odds.minimum }));
      return section;
    }
    var n = odds.n, bases = odds.bases;
    paragraphs.push(phrase('calibration.odds_bases', { n: n, tested: bases.tested,
      failure: bases.recorded_failure, success: bases.recorded_success }));
    paragraphs.push(phrase('calibration.odds_mean', { p: rangeShare(odds.mean_p), k: odds.successes, n: n,
      share: rangeShare(odds.successes / n) }));
    paragraphs.push(phrase('calibration.odds_brier', { bs: odds.brier }));
    if (odds.brier_prior !== null) {
      var skill = odds.skill;
      if (skill !== null && skill > 0.0) {
        paragraphs.push(phrase('calibration.odds_skill_better', { bs0: odds.brier_prior, skill: rangeShare(skill) }));
      } else if (skill !== null && skill < 0.0) {
        paragraphs.push(phrase('calibration.odds_skill_worse', { bs0: odds.brier_prior, skill: rangeShare(-skill) }));
      } else {
        paragraphs.push(phrase('calibration.odds_skill_same', { bs0: odds.brier_prior }));
      }
    }
    paragraphs.push(phrase('calibration.odds_reliability'));
    section.figures.push({ key: 'reliability',
      caption: phrase('calibration.odds_figure', { width: rangeShare(1.0 / odds.bins.length) }) });
    var none = phrase('calibration.none');
    section.tables.push({
      header: [phrase('calibration.odds_col_band'), phrase('calibration.odds_col_n'),
        phrase('calibration.odds_col_mean'), phrase('calibration.odds_col_found')],
      rows: odds.bins.map(function (b) {
        return [phrase('calibration.odds_band', { low: rangeShare(b.low), high: rangeShare(b.high) }), String(b.n),
          b.n ? calibrationPercent(b.mean_p) : none,
          b.n ? phrase('calibration.odds_found', { k: b.successes, n: b.n, share: rangeShare(b.observed) }) : none];
      }),
      caption: phrase('calibration.odds_table'),
    });
    return section;
  }

  /* each grouping's first column and caption */
  var CALIBRATION_HIT_TABLES = {
    geology: ['calibration.hits_col_geology', 'calibration.hits_geology'],
    team: ['calibration.hits_col_team', 'calibration.hits_team'],
    contractor: ['calibration.hits_col_contractor', 'calibration.hits_contractor'],
  };

  function calibrationHitsSection(pooled, cfg) {
    var section = calibrationSection('hits', phrase('calibration.hits_heading'));
    if (!pooled.some(function (e) { return e.outcome !== null; })) {
      section.paragraphs.push(phrase('calibration.hits_none'));
      return section;
    }
    section.paragraphs.push(phrase('calibration.hits_intro',
      { minimum: Math.trunc(Number(cfg.ledger.min_group)) }));
    var other = pooled.filter(function (e) {
      return e.outcome !== null && e.outcome.success !== null && !usesDefinition(e.outcome, cfg);
    }).length;
    if (other) {
      section.paragraphs.push(phrase('calibration.hits_definition',
        { n: other, rate: Number(cfg.odds.success_yield_m3_per_h) }));
    }
    var tooFew = phrase('calibration.hits_too_few'), notForecast = phrase('calibration.hits_not_forecast');
    CALIBRATION_GROUPINGS.forEach(function (by) {
      var ids = CALIBRATION_HIT_TABLES[by];
      section.tables.push({
        header: [phrase(ids[0]), phrase('calibration.hits_col_drilled'), phrase('calibration.hits_col_success'),
          phrase('calibration.hits_col_failure'), phrase('calibration.hits_col_unknown'),
          phrase('calibration.hits_col_rate'), phrase('calibration.hits_col_forecast')],
        rows: hitRates(pooled, by, cfg).map(function (g) {
          return [g.label, String(g.drilled), String(g.success), String(g.failure),
            String(g.unknown + g.definition),
            g.rate !== null ? calibrationPercent(g.rate) : tooFew,
            g.forecast_mean !== null
              ? phrase('calibration.hits_forecast', { p: rangeShare(g.forecast_mean), n: g.forecast_n })
              : notForecast];
        }),
        caption: phrase(ids[1]),
      });
    });
    return section;
  }

  function calibrationDepthSummary(depth) {
    if (depth.verdict === 'too_few') {
      return phrase('calibration.summary_depth_too_few', { judged: depth.judged, minimum: depth.minimum });
    }
    var values = { inside: depth.inside, judged: depth.judged, share: rangeShare(depth.inside / depth.judged),
      low: depth.expected[0], high: depth.expected[1] };
    if (depth.verdict === 'calibrated') return phrase('calibration.summary_depth_calibrated', values);
    if (depth.verdict === 'narrow') return phrase('calibration.summary_depth_narrow', values);
    return phrase('calibration.summary_depth_wide', values);
  }

  function calibrationOddsSummary(odds) {
    if (odds.verdict === 'too_few') {
      return phrase('calibration.summary_odds_too_few', { n: odds.n, minimum: odds.minimum });
    }
    if (odds.brier_prior === null) {
      return phrase('calibration.summary_odds_no_prior', { bs: odds.brier, n: odds.n });
    }
    return phrase('calibration.summary_odds', { bs: odds.brier, n: odds.n, bs0: odds.brier_prior });
  }

  /** calibration.calibration_content: everything the calibration report
   * says, as plain data the two document writers lay out: the title and
   * subtitle, the cover's rows, the summary, the sections (paragraphs,
   * tables, figures by key and caption, bullets) and the references.
   * @param {Rec[]} pooled the entries of poolLedgers
   * @param {string} [issuedOn] the date the report is issued ('' to leave it off)
   * @param {Config} [config]
   * @returns {Rec} */
  function calibrationContent(pooled, issuedOn, config) {
    var cfg = config || defaultConfig();
    var counts = ledgerCounts(pooled);
    var after = counts.drilled - counts.forecast;
    var depth = depthScores(pooled, cfg);
    var odds = oddsScores(pooled, cfg);
    var rows = [[phrase('calibration.row_projects'), String(counts.projects)],
      [phrase('calibration.row_points'), String(counts.points)],
      [phrase('calibration.row_drilled'), String(counts.drilled)],
      [phrase('calibration.row_forecasts'), String(counts.forecast)]];
    var issued = ledgerName(issuedOn);
    if (issued) rows.push([phrase('calibration.row_issued'), issued]);

    var summary = [ledgerSummary(pooled)];
    if (counts.forecast) summary.push(phrase('calibration.summary_scored', { forecast: counts.forecast }));
    else if (counts.drilled) summary.push(phrase('calibration.summary_nothing'));
    if (counts.forecast) summary.push(calibrationDepthSummary(depth), calibrationOddsSummary(odds));
    if (counts.drilled) {
      summary.push(phrase('calibration.summary_hits', { minimum: Math.trunc(Number(cfg.ledger.min_group)) }));
    }

    var limits = calibrationSection('limits', phrase('calibration.limits_heading'));
    limits.bullets.push(phrase('calibration.limit_files'));
    if (after) limits.bullets.push(phrase('calibration.limit_after', { after: after }));
    limits.bullets.push(phrase('calibration.limit_driller'), phrase('calibration.limit_names'),
      phrase('calibration.limit_minimum', { minimum: Math.trunc(Number(cfg.ledger.min_boreholes)),
        group: Math.trunc(Number(cfg.ledger.min_group)) }),
      phrase('calibration.limit_changes'));
    var citations = phraseTable('references.citations');
    return {
      title: phrase('calibration.title'),
      subtitle: phrase('calibration.subtitle'),
      rows: rows,
      summary: summary,
      sections: [calibrationDepthSection(depth, pooled), calibrationOddsSection(odds, cfg),
        calibrationHitsSection(pooled, cfg), limits],
      references: [citations.brier, citations.murphy_winkler],
    };
  }

  Object.assign(C, {
    BAND_COVERAGE: BAND_COVERAGE, forecastEntries: forecastEntries, binomialRange: binomialRange,
    depthScores: depthScores, oddsScores: oddsScores, hitRates: hitRates,
    calibrationContent: calibrationContent,
  });

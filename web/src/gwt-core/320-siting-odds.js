
  /* ===================================================================== odds
   * siting/odds.py (PLAN.md step 3.3): the chance that a borehole at a VES
   * point yields enough for a handpump through the dry season. A prior from
   * the ground under the point (data/success_prior.csv), times a likelihood
   * ratio for each of three things the survey says, the three weighted by
   * the confidence of the fit (data/success_evidence.yaml); the band is the
   * prior's Beta distribution carried through the same factors. Both
   * engines read the two files as the package parses them (GWT.data.odds),
   * and the numerical pieces are written out alike in both. */

  /** data/success_prior.csv and data/success_evidence.yaml, shared: read,
   * never changed.
   * @returns {Rec} */
  function oddsTables() {
    var odds = (GWT.data || {}).odds;
    if (!odds) {
      throw new Error('gwt-data.js is not loaded, or is stale: it carries the ' +
        'prior and the likelihood ratios (src/groundwater/data/success_*)');
    }
    return odds;
  }

  /* the quantile of the standard normal at 0.75 */
  var Z_QUARTILE = 0.6744897501960817;

  /** The complementary error function, by Abramowitz and Stegun 7.1.26:
   * _erfc in siting/odds.py.
   * @param {number} x
   * @returns {number} */
  function oddsErfc(x) {
    var z = Math.abs(x);
    var t = 1.0 / (1.0 + 0.3275911 * z);
    var poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 +
      t * (-1.453152027 + t * 1.061405429))));
    var tail = poly * Math.exp(-z * z);
    return x >= 0.0 ? tail : 2.0 - tail;
  }

  /** The share of a lognormal spread with quartiles q1 and q3 at or above
   * threshold: lognormal_share_above.
   * @param {number} q1
   * @param {number} q3
   * @param {number} threshold
   * @returns {number} */
  function lognormalShareAbove(q1, q3, threshold) {
    var mu = 0.5 * (Math.log(q1) + Math.log(q3));
    var sigma = (Math.log(q3) - Math.log(q1)) / (2.0 * Z_QUARTILE);
    var z = (Math.log(threshold) - mu) / sigma;
    return 0.5 * oddsErfc(z / Math.sqrt(2.0));
  }

  var LANCZOS = [0.99999999999980993, 676.5203681218851, -1259.1392167224028,
    771.32342877765313, -176.61502916214059, 12.507343278686905,
    -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];

  /** ln Gamma(x) for x > 0, by Lanczos's series: _log_gamma.
   * @param {number} x
   * @returns {number} */
  function logGamma(x) {
    if (x < 0.5) {
      return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - logGamma(1.0 - x);
    }
    x -= 1.0;
    var a = LANCZOS[0];
    var t = x + 7.5;
    for (var i = 1; i < 9; i++) a += LANCZOS[i] / (x + i);
    return 0.5 * Math.log(2.0 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
  }

  /* the incomplete beta function's continued fraction, by the modified
   * Lentz method (DLMF 8.17.22): _beta_fraction */
  function betaFraction(a, b, x) {
    var tiny = 1e-300;
    var qab = a + b, qap = a + 1.0, qam = a - 1.0;
    var c = 1.0;
    var d = 1.0 - qab * x / qap;
    d = 1.0 / (Math.abs(d) >= tiny ? d : tiny);
    var h = d;
    for (var m = 1; m <= 300; m++) {
      var m2 = 2 * m;
      var aa = m * (b - m) * x / ((qam + m2) * (a + m2));
      d = 1.0 + aa * d;
      d = 1.0 / (Math.abs(d) >= tiny ? d : tiny);
      c = 1.0 + aa / c;
      c = Math.abs(c) >= tiny ? c : tiny;
      h *= d * c;
      aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
      d = 1.0 + aa * d;
      d = 1.0 / (Math.abs(d) >= tiny ? d : tiny);
      c = 1.0 + aa / c;
      c = Math.abs(c) >= tiny ? c : tiny;
      var step = d * c;
      h *= step;
      if (Math.abs(step - 1.0) < 1e-15) break;
    }
    return h;
  }

  /** I_x(a, b), the distribution function of a Beta(a, b): regularised_beta.
   * @param {number} a
   * @param {number} b
   * @param {number} x
   * @returns {number} */
  function regularisedBeta(a, b, x) {
    if (x <= 0.0) return 0.0;
    if (x >= 1.0) return 1.0;
    var front = Math.exp(logGamma(a + b) - logGamma(a) - logGamma(b) +
      a * Math.log(x) + b * Math.log(1.0 - x));
    if (x < (a + 1.0) / (a + b + 2.0)) return front * betaFraction(a, b, x) / a;
    return 1.0 - front * betaFraction(b, a, 1.0 - x) / b;
  }

  /** The q quantile of a Beta(a, b), by a hundred halvings: beta_quantile.
   * @param {number} a
   * @param {number} b
   * @param {number} q
   * @returns {number} */
  function betaQuantile(a, b, q) {
    var lo = 0.0, hi = 1.0;
    for (var i = 0; i < 100; i++) {
      var mid = 0.5 * (lo + hi);
      if (regularisedBeta(a, b, mid) < q) lo = mid; else hi = mid;
    }
    return 0.5 * (lo + hi);
  }

  function oddsProbability(odds) { return odds / (1.0 + odds); }
  function oddsOf(p) { return p / (1.0 - p); }

  /* How close to 0 or 1 the prior rate and its percentiles may come: in
   * doubles the 90th percentile of a Beta with a rate near 1 bisects to
   * exactly 1, and its odds are then infinite (_RATE_BOUND, _inside). */
  var ODDS_RATE_BOUND = 1e-6;
  function oddsInside(p) {
    return Math.min(Math.max(p, ODDS_RATE_BOUND), 1.0 - ODDS_RATE_BOUND);
  }

  /** The prior table's row for this ground, and the rate it gives:
   * prior_for. The most specific row wins, and the set in force's fit of it
   * where it fitted one.
   * @param {string|null} bgsCode
   * @param {string|null} glg
   * @param {number} successYieldM3h
   * @param {Rec|null} [calibration] the calibration set in force, or null
   * @returns {Rec} */
  function priorFor(bgsCode, glg, successYieldM3h, calibration) {
    if (!(successYieldM3h > 0.0)) {
      throw new Error('odds.success_yield_m3_per_h must be above zero, not ' +
        String(successYieldM3h));
    }
    var rows = oddsTables().prior;
    function find(code, unit) {
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].bgs_code === code && rows[i].glg === unit) return rows[i];
      }
      return null;
    }
    var row = null, matched = 'fallback';
    if (bgsCode) {
      if (glg) { row = find(bgsCode, glg); matched = 'combination'; }
      if (!row) { row = find(bgsCode, '*'); matched = 'class'; }
    }
    if (!row) { row = find('*', '*'); matched = 'fallback'; }
    if (row.status === 'fallback') matched = 'fallback';
    var rate = row.yield_q1_l_per_s !== null
      ? lognormalShareAbove(row.yield_q1_l_per_s, row.yield_q3_l_per_s,
        successYieldM3h / 3.6)
      : row.rate;
    /* a Beta prior needs a rate strictly inside (0, 1) */
    rate = oddsInside(rate);
    /* the set in force's fit of the row, where it fitted one; a fallback row
     * is never fitted */
    var held = calibration || null;
    var fitted = held && matched !== 'fallback'
      ? fittedPrior(held, row.bgs_code, row.glg, successYieldM3h) : null;
    if (held && fitted) {
      return Object.assign({}, row, { matched: matched, rate: oddsInside(Number(fitted.rate)),
        effective_n: Number(fitted.effective_n), status: 'calibrated', base_rate: rate,
        fitted_boreholes: fitted.boreholes, fitted_successes: fitted.successes,
        set_version: held.version });
    }
    return Object.assign({}, row, { matched: matched, rate: rate });
  }

  /* the first band whose `below` is above value, else the last */
  function oddsBandOf(bands, value) {
    for (var i = 0; i < bands.length; i++) {
      if ('below' in bands[i] && value < bands[i].below) return bands[i];
    }
    return bands[bands.length - 1];
  }

  /* [key, band, value, ratio] for the three survey classes: _survey_evidence */
  function surveyEvidence(interp, range) {
    var table = oddsTables().evidence;
    var out = [];
    if (!range) {
      out.push(['regolith', 'not_sampled', null, 1.0]);
      out.push(['basement', 'not_sampled', null, 1.0]);
    } else {
      var quoted = quotesBasementBand(range);
      if (!quoted) {
        out.push(['regolith', 'not_quoted', null, 1.0]);
      } else {
        var hit = oddsBandOf(table.regolith, range.basement_m.p50);
        out.push(['regolith', hit.key, range.basement_m.p50, Number(hit.lr)]);
      }
      var share = range.basement_unresolved;
      var basement = table.basement;
      var key = !quoted ? 'unresolved'
        : (share <= basement.resolved_max_unresolved_share ? 'resolved' : 'partly');
      out.push(['basement', key, share, Number(basement[key].lr)]);
    }
    var rho = waterZoneRho(interp);
    var resistivity = table.resistivity;
    if (rho === null) {
      out.push(['resistivity', 'none', null, Number(resistivity.none.lr)]);
    } else {
      var band = oddsBandOf(resistivity.bands, rho);
      out.push(['resistivity', band.key, rho, Number(band.lr)]);
    }
    return out;
  }

  /** The chance that a borehole at this point succeeds, with its breakdown:
   * success_odds. range is the point's sampled range of models, or null;
   * bgsCode and glg the BGS class and USGS unit under it, or null.
   * @param {Interpretation} interp
   * @param {Rec|null} range
   * @param {string|null} bgsCode
   * @param {string|null} glg
   * @param {Config} [config]
   * @returns {Rec} */
  function successOdds(interp, range, bgsCode, glg, config) {
    var cfg = config || defaultConfig();
    var tables = oddsTables();
    var rateM3h = Number(cfg.odds.success_yield_m3_per_h);
    var band = oddsPriorBand(bgsCode, glg, rateM3h, cfg.calibration || null);
    var row = band.row, p0 = band.p0, n = band.n;
    var priorLow = band.low, priorHigh = band.high;
    var priorOdds = oddsOf(p0);

    var survey = surveyEvidence(interp, range || null);
    var err = interp.fit_error_percent;
    var fitKey, weight;
    if (err === null || err === undefined || !isFinite(err)) {
      fitKey = 'unknown'; weight = 1.0; err = null;
    } else {
      var hit = oddsBandOf(tables.evidence.fit, err);
      fitKey = hit.key; weight = Number(hit.weight);
    }
    var product = 1.0;
    survey.forEach(function (s) { product *= s[3]; });
    var fitFactor = Math.pow(product, weight - 1.0);

    var evidence = [];
    var odds = priorOdds;
    survey.forEach(function (s) {
      odds *= s[3];
      evidence.push({ key: s[0], band: s[1], value: s[2], factor: s[3],
        after: oddsProbability(odds), weight: null });
    });
    odds *= fitFactor;
    evidence.push({ key: 'fit', band: fitKey, value: err, factor: fitFactor,
      after: oddsProbability(odds), weight: weight });
    var total = product * fitFactor;
    function carried(p) { return oddsProbability(oddsOf(p) * total); }
    return Object.assign({
      sounding_id: interp.sounding_id,
      success_yield_m3_per_h: rateM3h,
      bgs_code: bgsCode || null, glg: glg || null,
      matched: row.matched, status: row.status, basis: row.basis,
      yield_q1_l_per_s: row.yield_q1_l_per_s, yield_q3_l_per_s: row.yield_q3_l_per_s,
      effective_n: n,
      prior: p0, prior_low: priorLow, prior_high: priorHigh, prior_odds: priorOdds,
      evidence: evidence,
      posterior_odds: odds,
      probability: oddsProbability(odds),
      low: carried(priorLow), high: carried(priorHigh),
      range_sampled: !!range,
      calibration: '', calibration_note: '', base_rate: null, fitted_boreholes: null,
      fitted_successes: null, set_version: null,
    }, oddsCalibrationFields(row, inForce(cfg)));
  }

  /* _calibration_fields: the set in force as the reports name it, what else
   * it changes, and what the set fitted the prior to */
  function oddsCalibrationFields(row, held) {
    var pick = function (key) { return row[key] === undefined ? null : row[key]; };
    return { calibration: setName(held), calibration_note: setChanges(held).join(' '),
      base_rate: pick('base_rate'), fitted_boreholes: pick('fitted_boreholes'),
      fitted_successes: pick('fitted_successes'), set_version: pick('set_version') };
  }

  /* The prior table's row for this ground, its rate and effective size, and
   * the 10th and 90th percentiles of its Beta: _prior_band. */
  function oddsPriorBand(bgsCode, glg, rateM3h, calibration) {
    var row = priorFor(bgsCode || null, glg || null, rateM3h, calibration || null);
    var p0 = row.rate, n = row.effective_n;
    var alpha = p0 * n, beta = (1.0 - p0) * n;
    /* held inside (0, 1) as the rate is: a percentile that rounded to
     * exactly 1 carried through the odds after it as NaN */
    return { row: row, p0: p0, n: n, low: oddsInside(betaQuantile(alpha, beta, 0.1)),
      high: oddsInside(betaQuantile(alpha, beta, 0.9)) };
  }

  /** The chance of a working borehole from the ground alone, before any
   * survey: prior_odds. What successOdds returns, with an empty breakdown.
   * @param {string|null} bgsCode
   * @param {string|null} glg
   * @param {Config} [config]
   * @returns {Rec} */
  function priorOdds(bgsCode, glg, config) {
    var cfg = config || defaultConfig();
    var rateM3h = Number(cfg.odds.success_yield_m3_per_h);
    var band = oddsPriorBand(bgsCode, glg, rateM3h, cfg.calibration || null);
    var row = band.row, odds = oddsOf(band.p0);
    return Object.assign({
      sounding_id: '',
      success_yield_m3_per_h: rateM3h,
      bgs_code: bgsCode || null, glg: glg || null,
      matched: row.matched, status: row.status, basis: row.basis,
      yield_q1_l_per_s: row.yield_q1_l_per_s, yield_q3_l_per_s: row.yield_q3_l_per_s,
      effective_n: band.n,
      prior: band.p0, prior_low: band.low, prior_high: band.high, prior_odds: odds,
      evidence: [],
      posterior_odds: odds,
      probability: oddsProbability(odds),
      low: oddsProbability(oddsOf(band.low)), high: oddsProbability(oddsOf(band.high)),
      range_sampled: false,
      calibration: '', calibration_note: '', base_rate: null, fitted_boreholes: null,
      fitted_successes: null, set_version: null,
    }, oddsCalibrationFields(row, inForce(cfg)));
  }

  /** Where the point is: its own easting and northing in zone (or the zone
   * its easting implies), else fallback, the site's position: point_latlon.
   * @param {Interpretation} interp
   * @param {number|null} zone
   * @param {{lat: number, lon: number}|null} fallback
   * @returns {{lat: number, lon: number}|null} */
  function pointLatLon(interp, zone, fallback) {
    var e = interp.site_easting, n = interp.site_northing;
    if (isFiniteNum(e) && isFiniteNum(n)) {
      return utmToGeographic(e, n, zone || inferZoneForSierraLeone(e));
    }
    return fallback || null;
  }

  /** The BGS aquifer class and USGS geology unit under a position:
   * ground_at. [null, null] where there is no position.
   * @param {{lat: number, lon: number}|null} latlon
   * @returns {Array<string|null>} */
  function groundAt(latlon) {
    if (!latlon) return [null, null];
    var aquifer = aquiferUnitAt(latlon.lat, latlon.lon);
    var unit = geologyUnitAt(latlon.lat, latlon.lon);
    return [aquifer ? String((aquifer.properties || {}).code || '') || null : null,
      unit ? String((unit.properties || {}).glg || '') || null : null];
  }

  /** The odds at every point of a survey, in the order given: survey_odds.
   * @param {Interpretation[]} interpretations
   * @param {Array<Rec|null>|null} ranges in lockstep, null where none was sampled
   * @param {number|null} zone the site's UTM zone, if it names one
   * @param {{lat: number, lon: number}|null} fallbackLatLon the site's position
   * @param {Config} [config]
   * @returns {Rec[]} */
  function surveyOdds(interpretations, ranges, zone, fallbackLatLon, config) {
    return (interpretations || []).map(function (interp, i) {
      var ground = groundAt(pointLatLon(interp, zone, fallbackLatLon));
      return successOdds(interp, (ranges || [])[i] || null, ground[0], ground[1], config);
    });
  }

  /** The plan's sentence: odds_headline.
   * @param {Rec} o what successOdds returns
   * @returns {string} */
  function oddsHeadline(o) {
    var status = o.status === 'calibrated'
      ? phrase('odds.status_calibrated', { version: o.set_version })
      : phrase(o.matched === 'fallback' ? 'odds.status_fallback' : 'odds.status_provisional');
    return phrase('odds.headline', { p: rangeShare(o.probability),
      low: rangeShare(o.low), high: rangeShare(o.high), status: status });
  }

  function oddsGround(o) {
    if (o.glg) return phrase('odds.ground', { code: o.bgs_code, glg: o.glg });
    return phrase('odds.ground_no_unit', { code: o.bgs_code });
  }

  /** The prior in a sentence: its rate and band, the ground it is for and
   * what it rests on: odds_prior_text.
   * @param {Rec} o what successOdds or priorOdds returns
   * @returns {string} */
  function oddsPriorText(o) {
    var prior = { p: rangeShare(o.prior), low: rangeShare(o.prior_low),
      high: rangeShare(o.prior_high), n: o.effective_n, basis: o.basis };
    if (o.matched === 'fallback') return phrase('odds.prior_fallback', prior);
    if (o.status === 'calibrated') {
      return phrase(o.matched === 'combination' ? 'odds.prior_fitted_combination'
        : 'odds.prior_fitted_class', Object.assign({ ground: oddsGround(o),
        base: rangeShare(Number(o.base_rate || 0.0)), m: o.fitted_boreholes, k: o.fitted_successes,
        version: o.set_version }, prior));
    }
    return phrase(o.matched === 'combination' ? 'odds.prior_combination'
      : 'odds.prior_class', Object.assign({ ground: oddsGround(o),
      q1: o.yield_q1_l_per_s, q3: o.yield_q3_l_per_s,
      ls: o.success_yield_m3_per_h / 3.6 }, prior));
  }

  /** What is particular to the point: the headline, its prior, and what was
   * left out: odds_point_text.
   * @param {Rec} o what successOdds returns
   * @returns {string[]} */
  function oddsPointText(o) {
    var out = [oddsHeadline(o), oddsPriorText(o)];
    if (!o.range_sampled) out.push(phrase('odds.not_sampled', { sid: o.sounding_id }));
    return out;
  }

  /** What success means and what the odds rest on, the same at every point
   * of a survey: odds_basis_text.
   * @param {Rec} o what successOdds returns
   * @returns {string[]} */
  function oddsBasisText(o) {
    var basis = phrase('odds.basis', { calibration: o.calibration });
    return [phrase('odds.definition', { rate: o.success_yield_m3_per_h,
      ls: o.success_yield_m3_per_h / 3.6 }),
    o.calibration_note ? basis + ' ' + o.calibration_note : basis];
  }

  /** The odds in sentences: odds_text.
   * @param {Rec} o what successOdds returns
   * @returns {string[]} */
  function oddsText(o) {
    var point = oddsPointText(o), basis = oddsBasisText(o);
    return point.slice(0, 1).concat(basis.slice(0, 1), point.slice(1), basis.slice(1));
  }

  /* what the survey found, for the breakdown's second column: _found */
  function oddsFound(e) {
    var missing = phraseTable('odds.found_missing');
    var id = e.key + '_' + e.band;
    if (Object.prototype.hasOwnProperty.call(missing, id)) return String(missing[id]);
    var band = String(phraseTable('odds.bands')[e.band]);
    if (e.key === 'regolith') return phrase('odds.found_regolith', { depth: e.value, band: band });
    if (e.key === 'basement') {
      return phrase('odds.found_basement', { share: rangeShare(e.value), band: band });
    }
    if (e.key === 'resistivity') {
      return phrase('odds.found_resistivity', { rho: e.value, band: band });
    }
    return phrase('odds.found_fit', { err: e.value, band: band, weight: e.weight });
  }

  /** The breakdown table's header: odds_header.
   * @returns {string[]} */
  function oddsHeader() {
    return [phrase('odds.col_evidence'), phrase('odds.col_found'),
      phrase('odds.col_factor'), phrase('odds.col_after')];
  }

  /** The breakdown: the prior, then each piece of evidence with its factor
   * and the chance after it: odds_rows.
   * @param {Rec} o what successOdds returns
   * @returns {string[][]} */
  function oddsRows(o) {
    var labels = phraseTable('odds.rows');
    var rows = [[String(labels.prior), o.bgs_code ? oddsGround(o)
      : phrase('odds.ground_none'), '', rangeShare(o.prior)]];
    o.evidence.forEach(function (/** @type {Rec} */ e) {
      rows.push([String(labels[e.key]), oddsFound(e), pyFixed(e.factor, 2),
        rangeShare(e.after)]);
    });
    return rows;
  }

  /** The odds in a table cell: odds_short.
   * @param {Rec} o what successOdds returns
   * @returns {string} */
  function oddsShort(o) {
    return phrase('odds.short', { p: rangeShare(o.probability), low: rangeShare(o.low),
      high: rangeShare(o.high) });
  }

  /** odds_table_caption.
   * @param {Rec} o what successOdds returns
   * @returns {string} */
  function oddsTableCaption(o) {
    return phrase('odds.table_caption', { sid: o.sounding_id });
  }

  /** The odds as a programme's success rate in percent, 1 to 99:
   * programme_rate.
   * @param {Rec} o what successOdds returns
   * @returns {number} */
  function programmeRate(o) {
    return Math.min(Math.max(pyRound(100.0 * o.probability, 0), 1), 99);
  }

  /** The sentence the Costing pages offer the odds with: programme_offer.
   * @param {Rec} o what successOdds returns
   * @returns {string} */
  function programmeOffer(o) {
    return phrase('odds.programme_offer', { sid: o.sounding_id,
      p: rangeShare(o.probability), low: rangeShare(o.low), high: rangeShare(o.high) });
  }

  Object.assign(C, {
    programmeRate: programmeRate, programmeOffer: programmeOffer,
    oddsTables: oddsTables, lognormalShareAbove: lognormalShareAbove,
    regularisedBeta: regularisedBeta, betaQuantile: betaQuantile,
    priorFor: priorFor, successOdds: successOdds, pointLatLon: pointLatLon,
    groundAt: groundAt, surveyOdds: surveyOdds, oddsHeadline: oddsHeadline,
    oddsText: oddsText, oddsHeader: oddsHeader, oddsRows: oddsRows,
    oddsTableCaption: oddsTableCaption, oddsShort: oddsShort,
    oddsPointText: oddsPointText, oddsBasisText: oddsBasisText,
    priorOdds: priorOdds, oddsPriorText: oddsPriorText,
  });

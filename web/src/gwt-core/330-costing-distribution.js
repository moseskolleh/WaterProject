
  /* ====================================================== cost as a range
   * groundwater/costing/distribution.py (PLAN.md step 3.4). The bill of
   * quantities stays the contract document; this samples the planning
   * figure beside it: every unit rate drawn from the triangle between its
   * minimum, likely and maximum (one draw for each spread group, so rates
   * that share a cause move together), the depth from the range of models
   * at the first-ranked point, and dry holes at the chance of a working
   * borehole there, p: the expected cost per working borehole is the mean
   * completed borehole plus the mean dry attempt for each of the (1 - p) / p
   * dry attempts expected before a working one. The draws come from the range of models' generator and
   * the arithmetic is sums, products, quotients and square roots, which
   * both engines round alike, so the two distributions agree to the bit;
   * every sum is a loop in the same order as Python's.
   */

  var COST_RATES = 0, COST_DEPTH = 1, COST_OUTCOME = 2;
  var COST_CURVE_STEPS = 100;

  /** The triangle's inverse distribution function: triangle_quantile.
   * @param {number} lo
   * @param {number} mode
   * @param {number} hi
   * @param {number} u
   * @returns {number} */
  function triangleQuantile(lo, mode, hi, u) {
    if (hi <= lo) return mode;
    var width = hi - lo;
    if (u < (mode - lo) / width) return lo + Math.sqrt(u * width * (mode - lo));
    return hi - Math.sqrt((1.0 - u) * width * (hi - mode));
  }

  /** The depth to draw from a sampled range of models, or null: depth_spread.
   * @param {Rec|null} range what sampleModelRange returns
   * @param {Config} [config]
   * @returns {Rec|null} */
  function depthSpread(range, config) {
    if (!range || !range.drilling_depth_quantiles_m || !range.drilling_depth_quantiles_m.length) {
      return null;
    }
    var cfg = config || defaultConfig();
    return {
      sounding_id: range.sounding_id,
      quantiles_m: range.drilling_depth_quantiles_m.slice(),
      step_m: cfg.ves.round_drilling_depth_to_m,
      cap_m: range.investigation_depth_m,
    };
  }

  /** The depth with probability u at or below it: DepthSpread.draw.
   * @param {Rec} spread what depthSpread returns
   * @param {number} u
   * @returns {number} */
  function depthDraw(spread, u) {
    var q = spread.quantiles_m;
    var pos = u * (q.length - 1);
    var k = Math.floor(pos);
    var x = k + 1 >= q.length ? q[q.length - 1] : q[k] + (q[k + 1] - q[k]) * (pos - k);
    return Math.min(Math.ceil(x / spread.step_m) * spread.step_m, spread.cap_m);
  }

  function costGiven(v) { return v !== null && v !== undefined; }

  /* The quantities of base (given resolved) for a borehole drilled to depth
   * instead: _at_depth. A length supplied moves with the depth, a length left
   * to a rule of thumb is worked out again, and a gravel pack the design
   * leaves out stays out. */
  function costAtDepth(given, base, depth) {
    if (depth === base.total_depth_m) return base;
    var shift = depth - base.total_depth_m;
    var over = costGiven(given.overburden_m) ? given.overburden_m : defaultOverburdenM(depth);
    var casing = costGiven(given.casing_m) ? Math.max(0.0, given.casing_m + shift)
      : defaultCasingM(depth, base.screen_m || 0.0);
    var gravel;
    if (!costGiven(given.gravel_interval_m)) gravel = defaultGravelIntervalM(depth);
    else if (given.gravel_interval_m === 0) gravel = 0.0;
    else gravel = Math.max(0.0, given.gravel_interval_m + shift);
    /* a rising main taken as long as the hole is as long as the hole drawn */
    var rising = base.rising_main_m;
    if (costGiven(rising) && !costGiven(given.rising_main_m)) rising = depth;
    var r = Object.assign({}, base, {
      total_depth_m: depth, overburden_m: Math.min(over, depth), casing_m: casing,
      gravel_interval_m: gravel,
      crew_days: costGiven(given.crew_days) ? given.crew_days : defaultCrewDays(depth),
      rising_main_m: rising,
    });
    r.bedrock_m = Math.max(0.0, r.total_depth_m - (r.overburden_m || 0.0));
    r.gravel_pack_m3 = annulusVolumeM3(r.borehole_diameter_in, r.casing_diameter_in,
      r.gravel_interval_m || 0.0, 1.3);
    return r;
  }

  /* Each rate's quantity at a depth, or null for a basis the estimate skips;
   * a drawn depth falls on a whole drilling step, so few are worked out. */
  function costQuantities(given, rates) {
    var base = resolveCostingInputs(given).inputs;
    var cache = new Map();
    return {
      base: base,
      at: function (/** @type {number} */ depth) {
        var hit = cache.get(depth);
        if (!hit) {
          var table = quantityTable(costAtDepth(given, base, depth));
          hit = rates.map(function (r) {
            return r.quantity_basis in table ? table[r.quantity_basis] : null;
          });
          cache.set(depth, hit);
        }
        return hit;
      },
    };
  }

  /* One uniform for each spread group, in the order the groups first appear,
   * and each rate read from its own triangle at its group's: _Rates. */
  function costRateDraws(rates) {
    var triangles = rates.map(rateTriangle);
    var order = new Map();
    var group = rates.map(function (r) {
      var key = r.spread_group || '\u0000' + r.code;
      if (!order.has(key)) order.set(key, order.size);
      return order.get(key);
    });
    var groups = order.size;
    return function (/** @type {Rec} */ rng) {
      var us = [];
      for (var i = 0; i < groups; i++) us.push(rng.uniform());
      return triangles.map(function (t, j) { return triangleQuantile(t[0], t[1], t[2], us[group[j]]); });
    };
  }

  /* the contract price with any VAT, in the order CostEstimate works it out */
  function costPrice(direct, overheads, margin, vat) {
    var total = direct + direct * overheads / 100.0;
    var price = total + total * margin / 100.0;
    return price + price * vat / 100.0;
  }

  function costShareAtOrUnder(sorted, value) {
    var limit = value + Math.abs(value) * 1e-12;
    var lo = 0, hi = sorted.length;
    while (lo < hi) {
      var mid = Math.floor((lo + hi) / 2);
      if (sorted[mid] <= limit) lo = mid + 1;
      else hi = mid;
    }
    return lo / sorted.length;
  }

  function costCurve(sorted) {
    var out = [];
    for (var k = 0; k <= COST_CURVE_STEPS; k++) out.push(rangePercentile(sorted, k / COST_CURVE_STEPS));
    return out;
  }

  function costMean(values) {
    var total = 0.0;
    for (var i = 0; i < values.length; i++) total += values[i];
    return total / values.length;
  }

  function costSettings(opts) {
    var cfg = opts.config || defaultConfig();
    var n = Math.trunc(opts.samples === undefined || opts.samples === null
      ? cfg.cost_range.samples : opts.samples);
    if (!(n >= 1)) throw new Error('the cost distribution needs at least one sample');
    var seed = Math.trunc(opts.seed === undefined || opts.seed === null
      ? cfg.cost_range.seed : opts.seed);
    return { n: n, seed: seed };
  }

  function costPct(opts) {
    return {
      overheads_percent: opts.overheadsPercent === undefined ? 15.0 : opts.overheadsPercent,
      margin_percent: opts.marginPercent === undefined ? 20.0 : opts.marginPercent,
      contingency_percent: opts.contingencyPercent === undefined ? 10.0 : opts.contingencyPercent,
      vat_percent: opts.vatPercent === undefined ? 0.0 : opts.vatPercent,
    };
  }

  /** Sample the cost of one borehole: sample_cost. Options as
   * estimateBoreholeCost takes them, plus depth (what depthSpread returns),
   * successProbability (0 to 1], oddsSource, config, samples and seed.
   * @param {Rec} inputs what costingInputs returns
   * @param {Rec[]|null} [rates]
   * @param {Rec} [options]
   * @returns {Rec} */
  function sampleCost(inputs, rates, options) {
    var opts = options || {};
    var p = opts.successProbability === undefined ? 1.0 : opts.successProbability;
    if (!(p > 0.0 && p <= 1.0)) throw new Error('the chance of success must be in (0, 1]');
    var settings = costSettings(opts);
    var catalogue = rates || loadRates();
    var pct = costPct(opts);
    var boq = estimateBoreholeCost(inputs, catalogue, {
      overheadsPercent: pct.overheads_percent, marginPercent: pct.margin_percent,
      contingencyPercent: pct.contingency_percent, vatPercent: pct.vat_percent,
    });
    var quantities = costQuantities(inputs, catalogue);
    var draw = costRateDraws(catalogue);
    var dryLine = catalogue.map(function (r) {
      return DRY_STAGES.indexOf(r.stage) >= 0 && r.quantity_basis !== COST_JOURNEY;
    });
    var depth = opts.depth || null;
    var rateRng = rangeStream(settings.seed, COST_RATES);
    var depthRng = rangeStream(settings.seed, COST_DEPTH);
    var baseDepth = quantities.base.total_depth_m;
    var costs = [], depths = [], dryTotal = 0.0;
    for (var i = 0; i < settings.n; i++) {
      var drawn = draw(rateRng);
      var d = depth ? depthDraw(depth, depthRng.uniform()) : baseDepth;
      var qs = quantities.at(d);
      var direct = 0.0, dry = 0.0;
      for (var j = 0; j < qs.length; j++) {
        if (qs[j] === null) continue;
        var amount = qs[j] * drawn[j];
        direct += amount;
        if (dryLine[j]) dry += amount;
      }
      costs.push(costPrice(direct, pct.overheads_percent, pct.margin_percent, pct.vat_percent));
      depths.push(d);
      dryTotal += costPrice(dry, pct.overheads_percent, pct.margin_percent, pct.vat_percent);
    }
    var mean = costMean(costs);
    var dryMean = dryTotal / settings.n;
    var ordered = costs.slice().sort(function (a, b) { return a - b; });
    depths.sort(function (a, b) { return a - b; });
    return Object.assign({
      samples: settings.n, seed: settings.seed,
      depth_m: baseDepth,
      depth_source: depth ? depth.sounding_id : null,
      depth_p10_m: rangePercentile(depths, 0.1), depth_p90_m: rangePercentile(depths, 0.9),
      success_probability: p,
      odds_source: opts.oddsSource === undefined ? null : opts.oddsSource,
      p50: rangePercentile(ordered, 0.5), p80: rangePercentile(ordered, 0.8), mean: mean,
      expected_per_working: mean + dryMean * ((1.0 - p) / p),
      dry_mean: dryMean,
      boq_usd: boq.price_with_vat_usd, budget_usd: boq.budget_usd,
      boq_share: costShareAtOrUnder(ordered, boq.price_with_vat_usd),
      budget_share: costShareAtOrUnder(ordered, boq.budget_usd),
    }, pct, {
      mean_share: costShareAtOrUnder(ordered, mean),
      curve: costCurve(ordered),
    });
  }

  /** The dry attempts a programme of n working boreholes makes at a chance p
   * of success each, as [the least count kept, the running weights from it]:
   * failures_table, the negative binomial worked outwards from its mode by
   * the ratio of one term to the next.
   * @param {number} n
   * @param {number} p
   * @returns {Array<number|number[]>} */
  function failuresTable(n, p) {
    if (p >= 1.0) return [0, [1.0]];
    var q = 1.0 - p;
    var mode = n > 1 ? Math.floor((n - 1) * q / p) : 0;
    var below = [];
    var w = 1.0, k = mode;
    while (k > 0) {
      w = w * k / ((n + k - 1) * q);
      if (w < 1e-17) break;
      below.push(w);
      k -= 1;
    }
    var weights = below.slice().reverse().concat([1.0]);
    w = 1.0; k = mode;
    for (;;) {
      w = w * (n + k) * q / (k + 1);
      if (w < 1e-17) break;
      weights.push(w);
      k += 1;
    }
    var running = [], total = 0.0;
    for (var i = 0; i < weights.length; i++) {
      total += weights[i];
      running.push(total);
    }
    return [mode - below.length, running];
  }

  function drawFailures(first, running, u) {
    var target = u * running[running.length - 1];
    var lo = 0, hi = running.length - 1;
    while (lo < hi) {
      var mid = Math.floor((lo + hi) / 2);
      if (running[mid] >= target) hi = mid;
      else lo = mid + 1;
    }
    return first + lo;
  }

  /** Sample the cost of a programme: sample_programme_cost. Options as
   * estimateProgrammeCost takes them, plus depth, config, samples and seed.
   * @param {Rec} perWell what costingInputs returns
   * @param {number} nBoreholes
   * @param {Rec} [options]
   * @returns {Rec} */
  function sampleProgrammeCost(perWell, nBoreholes, options) {
    var opts = options || {};
    var catalogue = opts.rates || loadRates();
    var estimate = estimateProgrammeCost(perWell, nBoreholes, Object.assign({}, opts,
      { rates: catalogue }));
    var settings = costSettings(opts);
    var pct = costPct(opts);
    var successRate = opts.successRatePercent === undefined ? 100.0 : opts.successRatePercent;
    var interSiteKm = opts.interSiteDistanceKm === undefined ? 15.0 : opts.interSiteDistanceKm;
    var wellInputs = Object.assign({}, perWell, { mobilisation_distance_km: 0.0 });
    var quantities = costQuantities(wellInputs, catalogue);
    var draw = costRateDraws(catalogue);
    var dryLine = catalogue.map(function (r) { return DRY_STAGES.indexOf(r.stage) >= 0; });
    var journey = catalogue.map(function (r) { return r.quantity_basis === COST_JOURNEY; });
    var table = failuresTable(nBoreholes, successRate / 100.0);
    var first = /** @type {number} */ (table[0]);
    var running = /** @type {number[]} */ (table[1]);
    var depth = opts.depth || null;
    var rateRng = rangeStream(settings.seed, COST_RATES);
    var depthRng = rangeStream(settings.seed, COST_DEPTH);
    var outcomeRng = rangeStream(settings.seed, COST_OUTCOME);
    var baseDepth = quantities.base.total_depth_m;
    var baseKm = 2.0 * perWell.mobilisation_distance_km;
    var totals = [], attempts = [];
    for (var i = 0; i < settings.n; i++) {
      var drawn = draw(rateRng);
      var d = depth ? depthDraw(depth, depthRng.uniform()) : baseDepth;
      var failures = drawFailures(first, running, outcomeRng.uniform());
      var qs = quantities.at(d);
      var well = 0.0, dry = 0.0, kmRate = 0.0;
      for (var j = 0; j < qs.length; j++) {
        if (journey[j]) kmRate += drawn[j];
        if (qs[j] === null) continue;
        var amount = qs[j] * drawn[j];
        well += amount;
        if (dryLine[j]) dry += amount;
      }
      var tried = nBoreholes + failures;
      var transport = kmRate * (baseKm + Math.max(0, tried - 1) * interSiteKm);
      var direct = nBoreholes * well + failures * dry + transport;
      var total = direct * (1 + pct.overheads_percent / 100.0);
      var price = total * (1 + pct.margin_percent / 100.0);
      totals.push(price * (1 + pct.vat_percent / 100.0));
      attempts.push(tried);
    }
    var mean = costMean(totals);
    var ordered = totals.slice().sort(function (a, b) { return a - b; });
    attempts.sort(function (a, b) { return a - b; });
    return {
      n_boreholes: nBoreholes, samples: settings.n, seed: settings.seed,
      success_rate_percent: successRate,
      depth_source: depth ? depth.sounding_id : null,
      p50: rangePercentile(ordered, 0.5), p80: rangePercentile(ordered, 0.8), mean: mean,
      per_working_expected: mean / nBoreholes,
      per_working_p80: rangePercentile(ordered, 0.8) / nBoreholes,
      attempts_p50: Math.ceil(rangePercentile(attempts, 0.5)),
      attempts_p80: Math.ceil(rangePercentile(attempts, 0.8)),
      attempts_planned: estimate.n_attempted,
      estimate_usd: estimate.price_with_vat_usd, budget_usd: estimate.budget_usd,
      estimate_share: costShareAtOrUnder(ordered, estimate.price_with_vat_usd),
      budget_share: costShareAtOrUnder(ordered, estimate.budget_usd),
      contingency_percent: pct.contingency_percent,
      mean_share: costShareAtOrUnder(ordered, mean),
      curve: costCurve(ordered),
    };
  }

  /** US dollars to the dollar with thousands separated, as Python's
   * f"{x:,.0f}" writes them: half to even on the exact value.
   * @param {number} value
   * @returns {string} */
  function costUsd(value) {
    var text = pyFixed(value, 0);
    var sign = text.charAt(0) === '-' ? '-' : '';
    var digits = sign ? text.slice(1) : text;
    return sign + digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  /** The distribution in sentences: cost_range_text.
   * @param {Rec} d what sampleCost returns
   * @returns {string[]} */
  function costRangeText(d) {
    var out = [
      phrase('cost_range.which_is_which'),
      phrase('cost_range.headline', { p50: costUsd(d.p50), p80: costUsd(d.p80),
        n: costUsd(d.samples), boq: costUsd(d.boq_usd), boq_share: rangeShare(d.boq_share) }),
      phrase('cost_range.price_basis', { overheads: d.overheads_percent,
        margin: d.margin_percent, contingency: d.contingency_percent,
        budget: costUsd(d.budget_usd), budget_share: rangeShare(d.budget_share) }),
    ];
    if (d.odds_source === null) {
      out.push(phrase('cost_range.working_no_odds', { mean: costUsd(d.mean) }));
    } else {
      out.push(phrase('cost_range.working', { sid: d.odds_source,
        p: rangeShare(d.success_probability), expected: costUsd(d.expected_per_working),
        dry: costUsd(d.dry_mean) }));
    }
    if (d.depth_source === null) {
      out.push(phrase('cost_range.depth_fixed', { depth: d.depth_m }));
    } else {
      out.push(phrase('cost_range.depth_range', { sid: d.depth_source, p10: d.depth_p10_m,
        p90: d.depth_p90_m, depth: d.depth_m }));
    }
    out.push(phrase('cost_range.basis', { seed: d.seed }));
    return out;
  }

  /** @returns {string[]} */
  function costRangeHeader() {
    return [phrase('cost_range.col_item'), phrase('cost_range.col_usd'),
      phrase('cost_range.col_share')];
  }

  /** The planning figure beside the bill of quantities: cost_range_rows.
   * @param {Rec} d what sampleCost returns
   * @returns {string[][]} */
  function costRangeRows(d) {
    var labels = phraseTable('cost_range.rows');
    var rows = [
      [String(labels.p50), costUsd(d.p50), rangeShare(0.5)],
      [String(labels.p80), costUsd(d.p80), rangeShare(0.8)],
      [String(labels.mean), costUsd(d.mean), rangeShare(d.mean_share)],
      [String(labels.expected), costUsd(d.expected_per_working), ''],
    ];
    rows.push([String(labels.boq), costUsd(d.boq_usd), rangeShare(d.boq_share)]);
    rows.push([String(labels.budget), costUsd(d.budget_usd), rangeShare(d.budget_share)]);
    return rows;
  }

  /** programme_range_text.
   * @param {Rec} d what sampleProgrammeCost returns
   * @returns {string[]} */
  function programmeRangeText(d) {
    return [
      phrase('cost_range.programme_headline', { wells: d.n_boreholes, p50: costUsd(d.p50),
        p80: costUsd(d.p80), n: costUsd(d.samples), estimate: costUsd(d.estimate_usd),
        estimate_share: rangeShare(d.estimate_share), contingency: d.contingency_percent,
        budget: costUsd(d.budget_usd), budget_share: rangeShare(d.budget_share) }),
      phrase('cost_range.programme_working', { expected: costUsd(d.per_working_expected),
        p80_each: costUsd(d.per_working_p80), rate: d.success_rate_percent,
        a50: d.attempts_p50, a80: d.attempts_p80, planned: d.attempts_planned }),
      phrase('cost_range.programme_basis'),
    ];
  }

  /** programme_range_rows.
   * @param {Rec} d what sampleProgrammeCost returns
   * @returns {string[][]} */
  function programmeRangeRows(d) {
    var labels = phraseTable('cost_range.programme_rows');
    return [
      [String(labels.p50), costUsd(d.p50), rangeShare(0.5)],
      [String(labels.p80), costUsd(d.p80), rangeShare(0.8)],
      [String(labels.mean), costUsd(d.mean), rangeShare(d.mean_share)],
      [String(labels.expected), costUsd(d.per_working_expected), ''],
      [String(labels.p80_each), costUsd(d.per_working_p80), ''],
      [String(labels.estimate), costUsd(d.estimate_usd), rangeShare(d.estimate_share)],
      [String(labels.budget), costUsd(d.budget_usd), rangeShare(d.budget_share)],
    ];
  }

  Object.assign(C, {
    triangleQuantile: triangleQuantile, depthSpread: depthSpread, depthDraw: depthDraw,
    sampleCost: sampleCost, failuresTable: failuresTable,
    sampleProgrammeCost: sampleProgrammeCost, costUsd: costUsd,
    costRangeText: costRangeText, costRangeHeader: costRangeHeader,
    costRangeRows: costRangeRows, programmeRangeText: programmeRangeText,
    programmeRangeRows: programmeRangeRows,
  });

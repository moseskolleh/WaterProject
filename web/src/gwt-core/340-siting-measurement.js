
  /* ================================================ one more measurement
   * groundwater/siting/measurement.py (PLAN.md step 3.5): what a second
   * sounding beside the first-ranked point, or a profiling line through it,
   * is worth to the choice of where to drill, as a preposterior analysis
   * anyone can follow on paper. The choice is the point or the alternative
   * (the other surveyed point with the best odds, or an unsurveyed site on
   * the same ground at the prior); what a measurement could read are the
   * bands of success_evidence.yaml, spread among working and dry boreholes
   * as evenly as their ratios allow; the value (EVSI) is the cost of the
   * best choice now less the expected cost of the best choice after it.
   * The module's docstring says each step and why.
   */

  /* the measurements priced, in the order the pages and reports give them */
  var MEASUREMENT_KINDS = ['sounding', 'profiling'];
  /* how far the tilt of the even spread is searched either way: _TILT */
  var MEASUREMENT_TILT = 1.0e4;
  /* _SAME_CHANCE: two chances of a working borehole within this share of
   * each other are the same chance. The choice is taken on the chances, not
   * on the costs worked out from them, which came out a last bit apart
   * either way for two points in the same bands and sent the client to the
   * second-ranked point "at 37 percent, against 37"; a reading whose factor
   * is exactly the threshold fell on the side the last bit of the even
   * spread's exponentials put it, which differs between engines. A tie
   * keeps the choice. */
  var MEASUREMENT_SAME_CHANCE = 1e-9;

  /* _better: whether the chance a is higher than b by more than
   * MEASUREMENT_SAME_CHANCE of it; a tie is not better */
  function measurementBetter(a, b) { return a - b > MEASUREMENT_SAME_CHANCE * b; }

  /** How often each band is seen among dry boreholes and among working
   * ones, from the bands' likelihood ratios alone: the most even spread
   * whose ratios average 1, by the bisection even_spread takes. Null where
   * the ratios are all on one side of 1.
   * @param {number[]} ratios
   * @returns {?{dry: number[], wet: number[]}} */
  function evenSpread(ratios) {
    var lo = Math.min.apply(null, ratios), hi = Math.max.apply(null, ratios);
    if (!(lo < 1.0 && 1.0 < hi)) return null;
    /** @param {number} t */
    function weights(t) {
      var top = t >= 0.0 ? -t * (lo - 1.0) : -t * (hi - 1.0);
      var w = ratios.map(function (r) { return Math.exp(-t * (r - 1.0) - top); });
      var total = 0.0, weighted = 0.0;
      for (var i = 0; i < w.length; i++) {
        total += w[i];
        weighted += w[i] * ratios[i];
      }
      return { w: w, total: total, weighted: weighted };
    }
    var a = -MEASUREMENT_TILT, b = MEASUREMENT_TILT;
    for (var k = 0; k < 200; k++) {
      var mid = 0.5 * (a + b);
      var at = weights(mid);
      if (at.weighted > at.total) a = mid; else b = mid;
    }
    var end = weights(0.5 * (a + b));
    return {
      dry: end.w.map(function (wi) { return wi / end.total; }),
      wet: end.w.map(function (wi, i) { return wi * ratios[i] / end.weighted; }),
    };
  }

  /** The expected cost of a working borehole at a chance q an attempt:
   * step 3.4's expected cost per working borehole.
   * @param {number} completed @param {number} dry @param {number} q */
  function measurementAlternativeUsd(completed, dry, q) {
    return completed + dry * ((1.0 - q) / q);
  }

  /** Drilling at the point first, and then the alternative if it is dry.
   * @param {number} p @param {number} completed @param {number} dry
   * @param {number} alternative */
  function measurementDrillHereUsd(p, completed, dry, alternative) {
    return p * completed + (1.0 - p) * (dry + alternative);
  }

  /** The decision before and after a measurement: preposterior. classes is
   * a list of classes, each a list of [factor, ifSuccess, ifDry]. Each
   * choice is taken on the chances, two within MEASUREMENT_SAME_CHANCE of
   * each other counting as a tie, and a tie keeps the choice.
   * @param {number} p @param {number} q
   * @param {number} completedUsd @param {number} dryUsd
   * @param {number[][][]} classes
   * @returns {Rec} */
  function preposterior(p, q, completedUsd, dryUsd, classes) {
    if (!(p > 0.0 && p < 1.0 && q > 0.0 && q < 1.0)) {
      throw new Error('the chances at the point and the alternative must be in (0, 1)');
    }
    if (!(completedUsd > 0.0 && dryUsd > 0.0)) {
      throw new Error('the completed borehole and the dry attempt must cost more than 0');
    }
    var move = measurementAlternativeUsd(completedUsd, dryUsd, q);
    var here = measurementDrillHereUsd(p, completedUsd, dryUsd, move);
    /* drilling here costs dry x (q - p) / q more than moving, so the choice
     * is the chances' alone; a tie keeps the first-ranked point */
    var stayHere = !measurementBetter(q, p);
    var now = stayHere ? here : move;

    /* every combination of one band from each class, the first outermost */
    /** @type {number[][]} */
    var combined = [[1.0, 1.0]];
    classes.forEach(function (bands) {
      /** @type {number[][]} */
      var next = [];
      combined.forEach(function (c) {
        bands.forEach(function (band) { next.push([c[0] * band[1], c[1] * band[2]]); });
      });
      combined = next;
    });

    var value = 0.0;
    var change = [0.0, 0.0];
    combined.forEach(function (c) {
      var s = c[0], f = c[1];
      var chance = p * s + (1.0 - p) * f;
      if (chance <= 0.0) return;
      var after = p * s / chance;
      /* the reading changes the choice where the chance after it is on the
       * other side of the alternative's, and not where it ties with it */
      var changes = stayHere ? measurementBetter(q, after) : measurementBetter(after, q);
      if (changes) {
        var costHere = measurementDrillHereUsd(after, completedUsd, dryUsd, move);
        var saving = stayHere ? costHere - move : move - costHere;
        value += chance * saving;
        change[0] += chance;
        change[1] += chance * after;
      }
    });
    /* the readings that keep the choice are the rest: a choice nothing
     * changes is kept on a chance of exactly 1 at exactly p */
    var keepChance = Math.max(0.0, 1.0 - change[0]);
    var keepP = keepChance > 0.0
      ? Math.min(Math.max((p - change[1]) / keepChance, 0.0), 1.0) : 0.0;
    var changeP = change[0] > 0.0 ? change[1] / change[0] : 0.0;
    var keepUsd, changeUsd;
    if (stayHere) {
      keepUsd = keepChance ? measurementDrillHereUsd(keepP, completedUsd, dryUsd, move) : 0.0;
      changeUsd = change[0] ? move : 0.0;
    } else {
      keepUsd = keepChance ? move : 0.0;
      changeUsd = change[0]
        ? measurementDrillHereUsd(changeP, completedUsd, dryUsd, move) : 0.0;
    }
    var perfect = now - (p * completedUsd + (1.0 - p) * move);
    return {
      alternative_usd: move, drill_here_usd: here,
      decision_now: stayHere ? 'here' : 'move', now_usd: now,
      threshold: (q / (1.0 - q)) / (p / (1.0 - p)),
      keep_chance: keepChance, keep_probability: keepP, keep_usd: keepUsd,
      change_chance: change[0], change_probability: changeP, change_usd: changeUsd,
      after_usd: now - value, value_usd: value, perfect_usd: perfect,
    };
  }

  /** What one more measurement of kind costs, from data/field.yaml:
   * measurement_cost_usd.
   * @param {string} kind
   * @returns {number} */
  function measurementCostUsd(kind) {
    var costs = fieldSchedules().one_more_measurement;
    if (kind === 'sounding') return Number(costs.sounding_usd);
    if (kind === 'profiling') return Number(costs.profiling_line_usd);
    throw new Error('no measurement of kind ' + kind);
  }

  /** The classes of evidence a measurement reads: _classes.
   * @param {string} kind @param {boolean} rangeSampled
   * @returns {Array<[string, Array<[string[], number]>]>} */
  function measurementClasses(kind, rangeSampled) {
    var table = oddsTables().evidence;
    /** @type {Array<[string, Array<[string[], number]>]>} */
    var out = [];
    if (kind === 'sounding' && rangeSampled) {
      var basement = table.basement;
      /** @type {Array<[string[], number]>} */
      var depth = [];
      table.regolith.forEach(function (/** @type {Rec} */ band) {
        ['resolved', 'partly'].forEach(function (key) {
          depth.push([[band.key, key], Number(band.lr) * Number(basement[key].lr)]);
        });
      });
      /* where no basement is quoted, the depth brings no ratio of its own */
      depth.push([['not_quoted', 'unresolved'], Number(basement.unresolved.lr)]);
      out.push(['depth', depth]);
    }
    var resistivity = table.resistivity;
    /** @type {Array<[string[], number]>} */
    var rho = [[['none'], Number(resistivity.none.lr)]];
    resistivity.bands.forEach(function (/** @type {Rec} */ band) {
      rho.push([[band.key], Number(band.lr)]);
    });
    out.push(['resistivity', rho]);
    return out;
  }

  /** @param {Rec} o @returns {number} */
  function measurementFitWeight(o) {
    for (var i = 0; i < o.evidence.length; i++) {
      var e = o.evidence[i];
      if (e.key === 'fit' && e.weight !== null && e.weight !== undefined) {
        return Number(e.weight);
      }
    }
    return 1.0;
  }

  /** What one more measurement of kind at the point o is worth to the
   * choice between drilling there and at alternative (null for an
   * unsurveyed site on the same ground): measurement_value.
   * @param {Rec} o what successOdds returns
   * @param {?Rec} alternative
   * @param {number} completedUsd the cost distribution's mean
   * @param {number} dryUsd its mean dry attempt
   * @param {string} [kind]
   * @returns {Rec} */
  function measurementValue(o, alternative, completedUsd, dryUsd, kind) {
    var which = kind || 'sounding';
    var cost = measurementCostUsd(which);
    var weight = measurementFitWeight(o);
    var p = o.probability;
    var q = alternative ? alternative.probability : o.prior;
    /** @type {Rec[]} */
    var readings = [];
    /** @type {number[][][]} */
    var classes = [];
    measurementClasses(which, o.range_sampled).forEach(function (cls) {
      var evidence = cls[0], bands = cls[1];
      var factors = bands.map(function (b) { return Math.pow(b[1], weight); });
      var spread = evenSpread(factors);
      /* nothing it reads can move the odds: one reading, a factor of 1 */
      if (spread === null) return;
      var wet = spread.wet, dry = spread.dry;
      classes.push(factors.map(function (f, i) { return [f, wet[i], dry[i]]; }));
      bands.forEach(function (b, i) {
        readings.push({ evidence: evidence, bands: b[0], factor: factors[i],
          if_success: wet[i], if_dry: dry[i], chance: p * wet[i] + (1.0 - p) * dry[i] });
      });
    });
    var worked = preposterior(p, q, completedUsd, dryUsd, classes);
    return Object.assign({
      kind: which, cost_usd: cost, sounding_id: o.sounding_id,
      alternative_id: alternative ? alternative.sounding_id : null,
      probability: p, alternative_probability: q, weight: weight,
      range_sampled: o.range_sampled,
      completed_usd: Number(completedUsd), dry_usd: Number(dryUsd),
    }, worked, { readings: readings });
  }

  /** Every measurement at the survey's first-ranked point: measurement_values.
   * odds is in the interpretations' order and ranking their positions in
   * the order of the ranking. Empty where there is no survey.
   * @param {Rec[]} odds @param {number[]} ranking
   * @param {number} completedUsd @param {number} dryUsd
   * @returns {Rec[]} */
  function measurementValues(odds, ranking, completedUsd, dryUsd) {
    if (!odds || !odds.length || !ranking || !ranking.length) return [];
    var first = odds[ranking[0]];
    /** @type {?Rec} */
    var alternative = null;
    ranking.slice(1).forEach(function (i) {
      if (alternative === null ||
          measurementBetter(odds[i].probability, alternative.probability)) {
        alternative = odds[i];
      }
    });
    return MEASUREMENT_KINDS.map(function (kind) {
      return measurementValue(first, alternative, completedUsd, dryUsd, kind);
    });
  }

  /** @param {Rec} v @returns {string} */
  function measurementWhat(v) {
    return phrase(v.kind === 'sounding' ? 'measurement.what_sounding'
      : 'measurement.what_profiling', { sid: v.sounding_id });
  }

  /** @param {Rec} v @returns {string} */
  function measurementAlternative(v) {
    if (v.alternative_id === null) return phrase('measurement.alternative_unsurveyed');
    return phrase('measurement.alternative_point', { sid: v.alternative_id });
  }

  /** The choice, as a sentence names it.
   * @param {Rec} v @param {boolean} here @returns {string} */
  function measurementDecision(v, here) {
    if (here) return phrase('measurement.decision_here', { sid: v.sounding_id });
    return phrase('measurement.decision_move', { alternative: measurementAlternative(v) });
  }

  /** The choice, as the decision table names it.
   * @param {Rec} v @param {boolean} here @returns {string} */
  function measurementCell(v, here) {
    if (here) return phrase('measurement.cell_here', { sid: v.sounding_id });
    return phrase('measurement.cell_move', { alternative: measurementAlternative(v) });
  }

  /** The plan's sentence: measurement_summary.
   * @param {Rec} v what measurementValue returns
   * @returns {string} */
  function measurementSummary(v) {
    if (v.change_chance === 0.0) {
      return phrase('measurement.zero', { what: measurementWhat(v), sid: v.sounding_id,
        cost: costUsd(v.cost_usd) });
    }
    var verdict = phrase(v.value_usd > v.cost_usd ? 'measurement.verdict_worth'
      : 'measurement.verdict_not_worth');
    return phrase('measurement.headline', { what: measurementWhat(v),
      value: costUsd(v.value_usd), cost: costUsd(v.cost_usd), verdict: verdict });
  }

  /** The value in sentences: measurement_text.
   * @param {Rec} v what measurementValue returns
   * @returns {string[]} */
  function measurementText(v) {
    var out = [measurementSummary(v)];
    out.push(phrase(v.decision_now === 'here' ? 'measurement.now_here'
      : 'measurement.now_move', { sid: v.sounding_id, p: rangeShare(v.probability),
      alternative: measurementAlternative(v), q: rangeShare(v.alternative_probability),
      here: costUsd(v.drill_here_usd), move: costUsd(v.alternative_usd) }));
    if (v.change_chance > 0.0) {
      out.push(phrase(v.decision_now === 'here' ? 'measurement.change_below'
        : 'measurement.change_above', { threshold: v.threshold,
        chance: rangeShare(v.change_chance),
        decision: measurementDecision(v, v.decision_now !== 'here'),
        after: costUsd(v.after_usd), now: costUsd(v.now_usd) }));
    }
    out.push(phrase('measurement.perfect', { sid: v.sounding_id,
      perfect: costUsd(v.perfect_usd) }));
    if (v.kind === 'sounding' && !v.range_sampled) {
      out.push(phrase('measurement.not_sampled', { sid: v.sounding_id }));
    }
    return out;
  }

  /** What every figure rests on: measurement_basis.
   * @param {Rec} v what measurementValue returns
   * @returns {string} */
  function measurementBasis(v) {
    return phrase('measurement.basis', { completed: costUsd(v.completed_usd),
      dry: costUsd(v.dry_usd), weight: v.weight });
  }

  /** @returns {string[]} */
  function measurementReadingHeader() {
    return [phrase('measurement.col_evidence'), phrase('measurement.col_reading'),
      phrase('measurement.col_factor'), phrase('measurement.col_success'),
      phrase('measurement.col_dry'), phrase('measurement.col_chance')];
  }

  /** The lower and upper edge of the band key in a banded list: _edges.
   * @param {Rec[]} bands @param {string} key
   * @returns {Array<?number>} */
  function measurementEdges(bands, key) {
    /** @type {?number} */
    var lower = null;
    for (var i = 0; i < bands.length; i++) {
      var band = bands[i];
      var upper = band.below === undefined || band.below === null ? null : Number(band.below);
      if (band.key === key) return [lower, upper];
      if (upper !== null) lower = upper;
    }
    throw new Error('no band ' + key);
  }

  /** @param {Rec[]} bands @param {string} key @param {string} unit */
  function measurementSpan(bands, key, unit) {
    var edges = measurementEdges(bands, key);
    if (edges[0] === null) return phrase('measurement.span_under', { hi: edges[1], unit: unit });
    if (edges[1] === null) return phrase('measurement.span_over', { lo: edges[0], unit: unit });
    return phrase('measurement.span_between', { lo: edges[0], hi: edges[1], unit: unit });
  }

  /** @param {Rec} r a reading @returns {string} */
  function measurementReadingLabel(r) {
    var table = oddsTables().evidence;
    var names = phraseTable('odds.bands');
    if (r.evidence === 'depth') {
      if (r.bands[0] === 'not_quoted') return phrase('measurement.reading_unresolved');
      return phrase('measurement.reading_depth', {
        span: measurementSpan(table.regolith, r.bands[0], 'm'),
        band: String(names[r.bands[0]]), basement: String(names[r.bands[1]]) });
    }
    if (r.bands[0] === 'none') return phrase('measurement.reading_no_zone');
    return phrase('measurement.reading_resistivity', {
      span: measurementSpan(table.resistivity.bands, r.bands[0], 'ohm-m'),
      band: String(names[r.bands[0]]) });
  }

  /** Every band the measurement could read: measurement_reading_rows.
   * @param {Rec} v what measurementValue returns
   * @returns {string[][]} */
  function measurementReadingRows(v) {
    var labels = phraseTable('measurement.evidence');
    return v.readings.map(function (/** @type {Rec} */ r) {
      return [String(labels[r.evidence]), measurementReadingLabel(r), pyFixed(r.factor, 2),
        rangeShare(r.if_success), rangeShare(r.if_dry), rangeShare(r.chance)];
    });
  }

  /** @param {Rec} v @returns {string[]} */
  function measurementDecisionHeader(v) {
    return ['', phrase('measurement.col_case_chance'),
      phrase('measurement.col_after', { sid: v.sounding_id }),
      phrase('measurement.col_decision'), phrase('measurement.col_usd')];
  }

  /** The choice without the measurement and with it:
   * measurement_decision_rows.
   * @param {Rec} v what measurementValue returns
   * @returns {string[][]} */
  function measurementDecisionRows(v) {
    var labels = phraseTable('measurement.rows');
    var here = v.decision_now === 'here';
    var rows = [[String(labels.now), '', rangeShare(v.probability), measurementCell(v, here),
      costUsd(v.now_usd)]];
    if (v.keep_chance > 0.0) {
      rows.push([String(labels.keep), rangeShare(v.keep_chance),
        rangeShare(v.keep_probability), measurementCell(v, here), costUsd(v.keep_usd)]);
    }
    if (v.change_chance > 0.0) {
      rows.push([String(labels.change), rangeShare(v.change_chance),
        rangeShare(v.change_probability), measurementCell(v, !here),
        costUsd(v.change_usd)]);
    }
    rows.push([String(labels.after), '', '', '', costUsd(v.after_usd)]);
    rows.push([String(labels.value), '', '', '', costUsd(v.value_usd)]);
    rows.push([String(labels.perfect), '', '', '', costUsd(v.perfect_usd)]);
    return rows;
  }

  /** @param {Rec} v @returns {string} */
  function measurementReadingsCaption(v) {
    return phrase('measurement.readings_caption', { sid: v.sounding_id });
  }

  /** @returns {string} */
  function measurementDecisionCaption() {
    return phrase('measurement.decision_caption');
  }

  Object.assign(C, {
    MEASUREMENT_KINDS: MEASUREMENT_KINDS, evenSpread: evenSpread,
    preposterior: preposterior, measurementCostUsd: measurementCostUsd,
    measurementValue: measurementValue, measurementValues: measurementValues,
    measurementSummary: measurementSummary, measurementText: measurementText,
    measurementBasis: measurementBasis, measurementReadingHeader: measurementReadingHeader,
    measurementReadingRows: measurementReadingRows,
    measurementDecisionHeader: measurementDecisionHeader,
    measurementDecisionRows: measurementDecisionRows,
    measurementReadingsCaption: measurementReadingsCaption,
    measurementDecisionCaption: measurementDecisionCaption,
  });

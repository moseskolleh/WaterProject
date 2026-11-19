


  /* ===================================================================
   * The seasonal yield model - a port of groundwater/seasonal.py
   *
   * A pumping test measures one day; the borehole has to supply the village
   * on the worst day, and in Sierra Leone those are months apart. A single
   * wet season recharges the aquifer, the table peaks at the end of it and
   * falls to an annual low in April or May, so the same test means
   * different things depending on when it was run. An ambiguous date is
   * treated as no date: 10/05/2018 is two different ends of the year.
   * =================================================================== */

  var MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];

  /* 0.0 at the annual high, 1.0 at the annual low. */
  var SEASONAL_POSITION = {
    1: 0.35, 2: 0.55, 3: 0.75, 4: 0.95, 5: 1.00, 6: 0.80,
    7: 0.45, 8: 0.15, 9: 0.00, 10: 0.05, 11: 0.15, 12: 0.25
  };

  var SEASON_OF_MONTH = {
    1: 'dry season', 2: 'dry season', 3: 'late dry season',
    4: 'late dry season', 5: 'late dry season', 6: 'early wet season',
    7: 'wet season', 8: 'wet season', 9: 'wet season',
    10: 'late wet season', 11: 'early dry season', 12: 'dry season'
  };

  /* key -> [title, share of the annual range, why it is here] */
  var SEASONAL_SCENARIOS = {
    as_tested: ['As tested', 0.0,
      'The level on the day of the test. Not a design figure: unless the ' +
      'test was run at the end of the dry season the borehole will be lower ' +
      'than this for part of every year.'],
    dry_season: ['End of dry season', 1.0,
      'The normal annual low, which the borehole reaches every year. This is ' +
      'the figure a design should be sized on.'],
    drought: ['Drought year', 1.5,
      'A low deeper than a normal year\'s, for a run of poor rains. The pump ' +
      'has to still be under water here, or the village loses the borehole ' +
      'in exactly the year it is needed most.']
  };

  /**
   * @param {*} text the test's date as written
   * @returns {{month: number|null, note: string}}
   */
  function monthOf(text) {
    var raw = String(text === null || text === undefined ? '' : text).trim();
    if (!raw) return { month: null, note: 'No date is recorded for the test.' };

    /* A month written by name settles it wherever it sits in the text. Only
     * the first word used to be looked at, so "Wed 25/04/2018" and
     * "Date: 14/09/2018" - both perfectly clear - were reported as naming
     * no month at all. */
    var words = raw.match(/[A-Za-z]{3,}/g) || [];
    for (var w = 0; w < words.length; w++) {
      var head = words[w].toLowerCase().slice(0, 3);
      for (var i = 0; i < MONTH_NAMES.length; i++) {
        if (MONTH_NAMES[i].toLowerCase().indexOf(head) === 0) {
          return { month: i + 1, note: '' };
        }
      }
    }

    var parts = (raw.match(/\d+/g) || []).map(Number);
    if (parts.length < 3) {
      if (words.length) {
        return { month: null, note: 'The date ' + pyRepr(raw) +
          ' does not name a month.' };
      }
      return { month: null, note: 'The date ' + pyRepr(raw) +
        ' is not a full date.' };
    }
    if (parts[0] > 31) {
      return parts[1] >= 1 && parts[1] <= 12
        ? { month: parts[1], note: '' }
        : { month: null, note: 'The date ' + pyRepr(raw) + ' has no month in it.' };
    }
    var first = parts[0], second = parts[1];
    if (first > 12 && second >= 1 && second <= 12) return { month: second, note: '' };
    if (second > 12 && first >= 1 && first <= 12) return { month: first, note: '' };
    if (first >= 1 && first <= 12 && second >= 1 && second <= 12) {
      return { month: null, note: 'The date ' + pyRepr(raw) +
        ' could be read either way round: ' + MONTH_NAMES[second - 1] + ' or ' +
        MONTH_NAMES[first - 1] + '. Those are different ends of the year and ' +
        'give different answers, so the season is treated as unknown. Record ' +
        'the month by name, or pick it below.' };
    }
    return { month: null, note: 'The date ' + pyRepr(raw) + ' has no month in it.' };
  }

  /* Python's repr for the strings that appear in these messages, so both
   * engines produce the same sentence rather than one with the other's
   * quoting. Python prefers single quotes unless the text contains one. */
  function pyRepr(text) {
    var body = String(text).replace(/\\/g, '\\\\');
    if (body.indexOf("'") >= 0 && body.indexOf('"') < 0) {
      return '"' + body + '"';
    }
    return "'" + body.replace(/'/g, "\\'") + "'";
  }

  /**
   * @param {number|string|null} [month]
   * @returns {string}
   */
  function seasonOf(month) {
    return month && own(SEASON_OF_MONTH, String(month))
      ? SEASON_OF_MONTH[month] : 'unknown';
  }

  function declineToCome(month, rangeM, factor) {
    var position = month && own(SEASONAL_POSITION, String(month))
      ? SEASONAL_POSITION[month] : 0.0;
    return Math.max(rangeM * (factor - position), 0.0);
  }

  /**
   * @param {Rec} result what seasonalYield returns
   * @param {string} key
   * @returns {Rec|null}
   */
  function seasonalScenario(result, key) {
    var found = null;
    (result.scenarios || []).forEach(function (item) {
      if (item.key === key) found = item;
    });
    return found;
  }

  function seasonalSummary(result) {
    if (result.pending_reason) return result.pending_reason;
    var tested = seasonalScenario(result, 'as_tested');
    var design = seasonalScenario(result, 'dry_season');
    var drought = seasonalScenario(result, 'drought');
    if (!design) return 'The seasonal yield could not be established.';
    var text;
    if (design.safe_yield_m3_per_h === null) {
      /* Not "could not be established": it was, and the answer is that the
       * pump runs dry before the annual low is reached. */
      text = 'No yield at the end of the dry season: the pump would be dry ' +
        'at the dry-season low';
      if (tested && tested.safe_yield_m3_per_h !== null) {
        text += ' (the test itself gave ' +
          formatG(roundSig(tested.safe_yield_m3_per_h, 2), 2) + ' m3/h)';
      }
    } else {
      text = 'Sized on the end of the dry season: ' +
        formatG(roundSig(design.safe_yield_m3_per_h, 2), 2) + ' m3/h';
      if (drought && drought.safe_yield_m3_per_h !== null) {
        text += ', falling to ' + formatG(roundSig(drought.safe_yield_m3_per_h, 2), 2) +
          ' m3/h in a drought year';
      } else if (drought) {
        /* a clause that used to be dropped, which read as if a drought
         * year cost nothing */
        text += ', and the pump would be dry in a drought year';
      }
    }
    if (result.month) {
      text += '. The test was run in ' + MONTH_NAMES[result.month - 1] +
        ', the ' + result.season;
    }
    return text + '.';
  }

  /** options: {month, annualRangeM}
   * @param {PumpingAnalysis|null} analysis
   * @param {PumpingConfig} [config]
   * @param {Rec} [options] month, annualRangeM
   */
  function seasonalYield(analysis, config, options) {
    var opts = options || {};
    var cfg = config || defaultConfig().pumping;
    var test = analysis && analysis.test;
    var recommendation = analysis && analysis.yield_recommendation;

    var month = null, note = '';
    if (opts.month !== undefined && opts.month !== null) {
      var wanted = Number(opts.month);
      if (wanted >= 1 && wanted <= 12) month = wanted;
      else note = pyRepr(String(opts.month)) + ' is not a month.';
    } else {
      var read = monthOf(test && test.site ? test.site.date : '');
      month = read.month;
      note = read.note;
    }

    var band, source;
    if (opts.annualRangeM !== undefined && opts.annualRangeM !== null &&
        Number(opts.annualRangeM) >= 0) {
      band = Number(opts.annualRangeM);
      source = 'measured for this programme';
    } else {
      band = Number(cfg.seasonal_allowance_m);
      source = 'the configured dry-season allowance, not a measurement';
    }

    /** @type {Rec} */
    var result = {
      month: month, season: seasonOf(month), month_note: note,
      annual_range_m: band, range_source: source, scenarios: [],
      pending_reason: ''
    };
    function finish(reason) {
      result.pending_reason = reason;
      result.summary = reason;
      result.is_established = false;
      result.design_yield_m3_per_h = null;
      result.pump_installation_depth_m = null;
      result.dry_season_loss_percent = null;
      return result;
    }
    if (!test || !recommendation) {
      return finish('No pumping test has been analysed, so there is nothing ' +
        'to project through the year.');
    }
    if (recommendation.safe_yield_m3_per_h === null ||
        recommendation.safe_yield_m3_per_h === undefined) {
      return finish(recommendation.pending_reason ||
        'The yield recommendation is pending, so it cannot be projected ' +
        'through the year.');
    }
    var transmissivity = /** @type {PumpingAnalysis} */ (analysis).transmissivity_m2_per_day;
    if (transmissivity === null || transmissivity === undefined) {
      return finish('No transmissivity was fitted, so the seasonal projection ' +
        'has nothing to run on.');
    }

    Object.keys(SEASONAL_SCENARIOS).forEach(function (key) {
      var spec = SEASONAL_SCENARIOS[key];
      var decline = declineToCome(month, band, spec[1]);
      /* the same borehole with its static level lowered: available drawdown,
       * the projection and the pump depth all follow from that one change,
       * so the recommendation is re-run rather than scaled */
      var lowered = Object.assign({}, test, {
        static_water_level_m: test.static_water_level_m + decline
      });
      var variant = Object.assign({}, cfg, { seasonal_allowance_m: 0.0 });
      var trial = recommendYield(lowered, transmissivity, /** @type {PumpingAnalysis} */ (analysis).step_test,
        variant);
      var noteText = spec[2];
      if (key === 'as_tested' && month) {
        noteText += ' The test was run in ' + MONTH_NAMES[month - 1] +
          ', the ' + seasonOf(month) + '.';
      }
      if (key !== 'as_tested' && decline === 0.0 && month) {
        noteText += ' No further decline is reserved: a test run in ' +
          MONTH_NAMES[month - 1] + ' is already at or below this level.';
      }
      if (trial.safe_yield_m3_per_h === null || trial.safe_yield_m3_per_h === undefined) {
        /* the pump would be dry at this level; the table cell is blank, so
         * the note has to carry the reason */
        noteText += ' No yield at this level: ' +
          (trial.pending_reason || 'the projection leaves no usable drawdown') + '.';
      }
      result.scenarios.push({
        key: key, title: spec[0], decline_m: decline,
        static_water_level_m: lowered.static_water_level_m,
        available_drawdown_m: trial.available_drawdown_m,
        safe_yield_m3_per_h: trial.safe_yield_m3_per_h,
        pump_installation_depth_m: trial.pump_installation_depth_m,
        note: noteText
      });
    });

    var design = seasonalScenario(result, 'dry_season');
    var tested = seasonalScenario(result, 'as_tested');
    var depths = result.scenarios.map(function (s) {
      return s.pump_installation_depth_m;
    }).filter(function (d) { return d !== null && d !== undefined; });
    result.is_established = !!(design && design.safe_yield_m3_per_h !== null);
    result.design_yield_m3_per_h = design ? design.safe_yield_m3_per_h : null;
    result.pump_installation_depth_m = depths.length
      ? Math.max.apply(null, depths) : null;
    result.dry_season_loss_percent = null;
    if (tested && design && tested.safe_yield_m3_per_h) {
      /* the dry season takes all of it: the pump is dry at the annual low */
      result.dry_season_loss_percent = design.safe_yield_m3_per_h === null
        ? 100.0
        : (1 - design.safe_yield_m3_per_h / tested.safe_yield_m3_per_h) * 100;
    }
    result.summary = seasonalSummary(result);
    return result;
  }

  Object.assign(C, {
    MONTH_NAMES: MONTH_NAMES, SEASONAL_POSITION: SEASONAL_POSITION,
    SEASONAL_SCENARIOS: SEASONAL_SCENARIOS,
    monthOf: monthOf, seasonOf: seasonOf, seasonalYield: seasonalYield,
    seasonalScenario: seasonalScenario
  });




  /* ===================================================================
   * Coverage as a planning figure - a port of groundwater/planning.py
   *
   * The census is from 2015 and the survey behind each water point is older
   * than it looks, so both halves of "people per functional point" are
   * staler than the phrase suggests. Nothing here hides that: the
   * projection states its year and rate, freshness is measured and
   * reported, and dry-season service is a band rather than a number,
   * because most surveys never asked and silence is not a year-round
   * supply.
   * =================================================================== */

  var CENSUS_YEAR = 2015;
  var CENSUS_TOTAL = 7092113;
  var PREVIOUS_CENSUS_YEAR = 2004;
  var PREVIOUS_CENSUS_TOTAL = 4976871;

  /* Derived rather than quoted, so it can be checked against two published
   * totals. It is higher than recent international projections - the 2004
   * count followed the civil war - so a programme with its own figure
   * should use it instead. */
  function intercensalGrowthRate() {
    return Math.pow(CENSUS_TOTAL / PREVIOUS_CENSUS_TOTAL,
      1 / (CENSUS_YEAR - PREVIOUS_CENSUS_YEAR)) - 1;
  }

  var DEFAULT_GROWTH_RATE = intercensalGrowthRate();

  var FRESH_YEARS = 3, AGEING_YEARS = 7;

  /* the label of a freshness state, from the catalogue (planning.yaml):
   * planning.FRESHNESS_LABELS */
  function freshnessLabel(state) {
    var labels = phraseTable('planning.freshness_label');
    return String(own(labels, state) ? labels[state] : labels.unknown);
  }

  /* the sentence under the label, in the plan year: Freshness.detail */
  function freshnessDetail(f, year) {
    if (f.state === 'later') {
      return phrase('planning.freshness_all_later', { later: f.n_later, points: f.n_points, year: year });
    }
    if (f.state === 'unknown') return phrase('planning.freshness_undated');
    var text = phrase('planning.freshness_dated', { dated: f.n_dated, points: f.n_points,
      year: year, latest: f.latest_year, median: f.median_age_years, recent: f.n_recent,
      fresh: FRESH_YEARS });
    if (f.n_later) text += ' ' + phrase('planning.freshness_later', { later: f.n_later, year: year });
    return text;
  }

  function projectionNote(projection) {
    if (projection.target_year === projection.base_year) {
      return 'Populations are the ' + projection.base_year +
        ' census figures, not projected.';
    }
    var text = 'Populations are projected from the ' + projection.base_year +
      ' census to ' + projection.target_year + ' at ' +
      pyFixed(projection.rate * 100, 2) + '% a year, a factor of ' +
      pyFixed(projection.factor, 3) + '.';
    if (projection.uniform) {
      text += ' The same rate is applied to every district, so the ranking ' +
        'is unchanged by the projection - only the magnitudes move. District ' +
        'rates would change it, and an urban district does not grow at the ' +
        'rural rate.';
    }
    return text;
  }

  /** options: {rate, rates}
   * @param {Record<string, number>} population
   * @param {number|string} toYear
   * @param {Rec} [options] rate, rates
   */
  function projectPopulation(population, toYear, options) {
    var opts = options || {};
    var national = (opts.rate === undefined || opts.rate === null)
      ? DEFAULT_GROWTH_RATE : Number(opts.rate);
    var years = Number(toYear) - CENSUS_YEAR;
    if (years < 0) {
      throw new Error(toYear + ' is before the ' + CENSUS_YEAR + ' census; ' +
        'this projects forward, it does not reconstruct the past');
    }
    var perArea = {};
    Object.keys(opts.rates || {}).forEach(function (key) {
      perArea[String(key).trim().toLowerCase()] = Number(opts.rates[key]);
    });
    var projected = {};
    Object.keys(population).forEach(function (name) {
      var key = String(name).trim().toLowerCase();
      var rate = own(perArea, key) ? perArea[key] : national;
      projected[name] = Number(population[name]) * Math.pow(1 + rate, years);
    });
    var projection = {
      base_year: CENSUS_YEAR, target_year: Number(toYear), rate: national,
      uniform: Object.keys(perArea).length === 0,
      factor: Math.pow(1 + national, years)
    };
    projection.note = projectionNote(projection);
    return { projected: projected, projection: projection };
  }

  /**
   * @param {WaterPoint[]|null} points
   * @param {number} asOfYear
   * @returns {Rec}
   */
  function pointFreshness(points, asOfYear) {
    /* A survey dated after the plan year is evidence about a later year:
     * it is left out of the median and of the recent count, and the detail
     * says how many were (planning.point_freshness). */
    var list = points || [];
    var dated = list.map(function (p) { return p.report_year; })
      .filter(function (y) { return y; }).sort(function (a, b) { return a - b; });
    var years = dated.filter(function (y) { return y <= asOfYear; });
    var later = dated.length - years.length;
    /** @type {Rec} */
    var f;
    if (!years.length) {
      f = { n_points: list.length, n_dated: 0, latest_year: null,
        median_age_years: null, n_recent: 0, n_later: later, state: later ? 'later' : 'unknown' };
    } else {
      var ages = years.map(function (y) { return asOfYear - y; });
      var middle = Math.floor(ages.length / 2);
      var median = ages.length % 2
        ? ages[middle] : (ages[middle - 1] + ages[middle]) / 2;
      var recent = ages.filter(function (a) { return a <= FRESH_YEARS; }).length;
      var state = median <= FRESH_YEARS ? 'fresh'
        : (median <= AGEING_YEARS ? 'ageing' : 'stale');
      f = { n_points: list.length, n_dated: years.length, latest_year: years[years.length - 1],
        median_age_years: median, n_recent: recent, n_later: later, state: state };
    }
    f.label = freshnessLabel(f.state);
    f.detail = freshnessDetail(f, asOfYear);
    return f;
  }

  /** The dry-season band as a planner reads it: best case to worst.
   * people_per_point_high is the kinder end - it credits the points nobody
   * asked about with working all year - so it comes first.
   * @param {Rec} cov what seasonalCoverage returns
   * @returns {string}
   */
  function seasonalBandText(cov) {
    var best = cov.people_per_point_high, worst = cov.people_per_point_low;
    var absent = function (v) { return v === null || v === undefined; };
    if (absent(best) && absent(worst)) return 'n/a';
    if (absent(worst)) return thousandsFixed(best, 0) + ' to no confirmed point';
    if (absent(best) || Math.round(best) === Math.round(worst)) {
      return thousandsFixed(worst, 0);
    }
    return thousandsFixed(best, 0) + ' to ' + thousandsFixed(worst, 0);
  }

  /** A band, not a number: low counts only the points a survey confirmed work
   * all year, high also counts the ones nobody asked about.
   * @param {WaterPoint[]|null} points
   * @param {number} population
   */
  function seasonalCoverage(points, population) {
    var functional = (points || []).filter(function (p) { return p.functional; });
    var yearRound = 0, seasonal = 0;
    functional.forEach(function (p) {
      if (p.months_per_year === null || p.months_per_year === undefined) return;
      if (p.months_per_year >= 12) yearRound += 1; else seasonal += 1;
    });
    var unknown = functional.length - yearRound - seasonal;
    var known = yearRound + seasonal;
    var total = functional.length;
    var detail;
    if (!total) {
      detail = 'There are no functional points here to ask about.';
    } else if (!known) {
      detail = 'No survey recorded how many months of the year these points ' +
        'yield water, so dry-season service cannot be separated from ' +
        'wet-season service. Silence is not a year-round supply.';
    } else {
      detail = yearRound + ' of ' + total + ' functional points are recorded ' +
        'as working all year and ' + seasonal + ' as seasonal' +
        (unknown ? '; ' + unknown + ' were never asked' : '') + '.';
    }
    var cov = {
      n_year_round: yearRound, n_seasonal: seasonal, n_unknown: unknown,
      people_per_point_low: yearRound ? population / yearRound : null,
      people_per_point_high: (yearRound + unknown)
        ? population / (yearRound + unknown) : null,
      is_established: known > 0 && known >= (known + unknown) * 0.5,
      detail: detail
    };
    cov.people_per_point_band = seasonalBandText(cov);
    return cov;
  }

  function stalenessGapPercent(row) {
    if (!row.people_per_point || row.people_per_recent_point === null) return null;
    return (row.people_per_recent_point / row.people_per_point - 1) * 100;
  }

  /** options: {asOfYear, rate, rates}
   * @param {Record<string, number>} population
   * @param {Record<string, WaterPoint[]>|null} pointsByArea
   * @param {Rec} [options] asOfYear, rate, rates
   */
  function planningRows(population, pointsByArea, options) {
    var opts = options || {};
    var asOfYear = Number(opts.asOfYear);
    var out = projectPopulation(population, asOfYear,
      { rate: opts.rate, rates: opts.rates });
    var rows = Object.keys(population).map(function (name) {
      var points = (pointsByArea || {})[name] || [];
      var people = out.projected[name];
      var functional = points.filter(function (p) { return p.functional; });
      /* surveyed in the plan year or the seven before it: a survey after
       * the plan year says nothing about it */
      var recent = functional.filter(function (p) {
        return p.report_year && asOfYear - p.report_year >= 0 &&
          asOfYear - p.report_year <= AGEING_YEARS;
      });
      var row = {
        name: name, census_population: Number(population[name]),
        population: people, water_points: points.length,
        functional_points: functional.length,
        people_per_point: functional.length ? people / functional.length : null,
        recent_functional_points: recent.length,
        people_per_recent_point: recent.length ? people / recent.length : null,
        freshness: pointFreshness(points, asOfYear),
        seasonal: seasonalCoverage(points, people),
        rank: 0
      };
      row.staleness_gap_percent = stalenessGapPercent(row);
      return row;
    });
    rankCoverage(rows);
    return { rows: rows, projection: out.projection };
  }

  /**
   * @param {Rec[]|null} rows what planningRows returns
   * @param {Rec} projection what projectPopulation returns
   */
  function planningStats(rows, projection) {
    var list = rows || [];
    var served = list.filter(function (r) { return r.people_per_point !== null; });
    var worst = /** @type {Rec|null} */ (null);
    served.forEach(function (r) {
      if (!worst || r.people_per_point > worst.people_per_point) worst = r;
    });
    function total(key) {
      return list.reduce(function (a, r) { return a + r[key]; }, 0);
    }
    var people = total('population');
    var functional = total('functional_points');
    var recent = total('recent_functional_points');
    var stale = list.filter(function (r) { return r.freshness.state === 'stale'; });
    return {
      n_areas: list.length,
      as_of_year: projection.target_year,
      projection_note: projection.note,
      population: people,
      census_population: total('census_population'),
      worst_area: list.length ? list[0].name : null,
      worst_people_per_point: list.length ? list[0].people_per_point : null,
      worst_served_area: worst ? worst.name : null,
      worst_served_people_per_point: worst ? worst.people_per_point : null,
      n_no_source: list.filter(function (r) {
        return r.functional_points === 0;
      }).length,
      national_people_per_point: functional ? people / functional : null,
      national_people_per_recent_point: recent ? people / recent : null,
      n_stale_areas: stale.length,
      stale_areas: stale.map(function (r) { return r.name; }),
      n_seasonality_recorded: list.reduce(function (a, r) {
        return a + r.seasonal.n_year_round + r.seasonal.n_seasonal;
      }, 0),
      n_seasonality_unknown: list.reduce(function (a, r) {
        return a + r.seasonal.n_unknown;
      }, 0)
    };
  }

  Object.assign(C, {
    CENSUS_YEAR: CENSUS_YEAR, DEFAULT_GROWTH_RATE: DEFAULT_GROWTH_RATE,
    FRESH_YEARS: FRESH_YEARS, AGEING_YEARS: AGEING_YEARS,
    intercensalGrowthRate: intercensalGrowthRate,
    projectPopulation: projectPopulation, pointFreshness: pointFreshness,
    seasonalCoverage: seasonalCoverage, seasonalBandText: seasonalBandText,
    planningRows: planningRows,
    planningStats: planningStats
  });

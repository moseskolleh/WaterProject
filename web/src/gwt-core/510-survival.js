
  /* ===================================================================
   * How long boreholes keep working - a port of groundwater/survival.py
   * (PLAN.md 7.4)
   *
   * The time from commissioning to the first failure across the boreholes
   * of the register: the Kaplan-Meier estimate with Greenwood's variance and
   * a 95 percent band on the log-log scale, the median and its band, the
   * numbers at risk at stated times, by pump type, contractor and water
   * chemistry, and the log-rank test between groups judged. A borehole that
   * has not failed is censored at the last report of it working, never
   * counted as working after it. The day is an input, never the clock; the
   * words are in text/survival.yaml.
   * =================================================================== */

  var SURVIVAL_GROUPINGS = ['pump_type', 'contractor', 'chemistry'];
  /* survival.DAYS_PER_YEAR, the Julian year, and Z_95, the two-sided 95
   * percent point of the standard normal distribution */
  var DAYS_PER_YEAR = 365.25;
  var Z_95 = 1.959963984540054;
  /* survival._MENDING and _WORKING: records that mend a breakdown, and
   * records that report the borehole working (a report from its plate or by
   * SMS that it is working among them, PLAN.md step 7.1) */
  var SURVIVAL_MENDING = ['repair', 'restored'];
  var SURVIVAL_WORKING = ['commissioned', 'inspection', 'routine_inspection', 'water_sample',
    'reported_working'];
  /* the works the method cites, as reporting/citations.py lists them for
   * "survival" */
  var SURVIVAL_CITED = ['kaplan_meier', 'greenwood', 'kalbfleisch_prentice',
    'brookmeyer_crowley', 'mantel'];

  /* the day of the analysis, as a day number; YYYY-MM-DD and nothing else */
  function survivalDay(asOf) {
    var day = isoDay(asOf);
    if (day === null) throw new Error('survival: the analysis needs the day it is made, as YYYY-MM-DD');
    return day;
  }

  /* the minimum followed and the times at risk, refused as Python refuses
   * them (survival._settings) */
  function survivalSettings(cfg) {
    var section = (cfg || defaultConfig()).survival;
    var minimum = section.min_at_risk;
    if (!(typeof minimum === 'number' && isFinite(minimum) && minimum === Math.floor(minimum) &&
        minimum >= 1)) {
      throw new Error('survival: min_at_risk must be a whole number, 1 or more');
    }
    var stated = section.at_risk_years;
    /** @type {number[]} */
    var years = Array.isArray(stated) ? stated.slice() : [];
    if (!Array.isArray(stated) || years.some(function (value, i) {
      return !(finiteNumber(value) && value >= 0 && (i === 0 || value > years[i - 1]));
    })) {
      throw new Error('survival: at_risk_years must be a list of numbers of years, 0 or ' +
        'more, each larger than the one before');
    }
    return { minimum: minimum, years: years };
  }

  /* times as [days, failed] pairs, refused as Python refuses them
   * (survival._checked) unless each is a record whose days is a number, 0 or
   * more, and whose failed is true or false */
  function survivalTimes(times, where) {
    return times.map(function (t) {
      var days = isRecord(t) ? t.days : null, failed = isRecord(t) ? t.failed : null;
      if (!(finiteNumber(days) && days >= 0 && typeof failed === 'boolean')) {
        throw new Error('survival: ' + where + ' takes times of days, 0 or more, each with ' +
          'whether it failed, true or false');
      }
      return [days, failed];
    });
  }

  /* the distinct times of [days, failed] pairs in order, each with the
   * number at risk there, the number failed and the number censored
   * (survival._sweep) */
  function survivalSweep(pairs) {
    var sorted = pairs.slice().sort(function (a, b) { return a[0] - b[0]; });
    /** @type {number[][]} */
    var out = [];
    var atRisk = pairs.length;
    for (var i = 0; i < sorted.length;) {
      var day = sorted[i][0], failed = 0, censored = 0;
      for (; i < sorted.length && sorted[i][0] === day; i++) {
        if (sorted[i][1]) failed += 1; else censored += 1;
      }
      out.push([day, atRisk, failed, censored]);
      atRisk -= failed + censored;
    }
    return out;
  }

  function roundOrNull(value, digits) {
    return value === null ? null : pyRound(value, digits);
  }

  /** One borehole's time from commissioning to its first failure, or to the
   * day it is censored, read from its history as of asOf
   * (survival.borehole_times).
   * @param {Rec} asset a registry record
   * @param {string} asOf the day, YYYY-MM-DD
   * @returns {Rec}
   */
  function boreholeTimes(asset, asOf) {
    var day = survivalDay(asOf);
    var events = mergeEvents(asset.asset_id, asset.events || []);
    /** @type {Rec} */
    var byDay = {};
    var undated = 0;
    events.forEach(function (event) {
      var when = isoDay(event.when);
      if (when === null) { undated += 1; return; }
      if (when > day) return;
      if (!own(byDay, event.when)) byDay[event.when] = {};
      byDay[event.when][event.kind] = true;
    });
    var days = Object.keys(byDay).sort();
    var commissioned = days.filter(function (when) { return own(byDay[when], 'commissioned'); });
    /** @type {Rec} */
    var out = { asset_id: asset.asset_id, start: null, end: null, days: null, failed: false,
      ends: 'no_commissioning', before_start: 0, undated: undated };
    if (!commissioned.length) return out;
    var start = commissioned[0];
    var startDay = /** @type {number} */ (isoDay(start));
    out.start = start;
    out.before_start = events.filter(function (event) {
      var when = isoDay(event.when);
      return when !== null && when < startDay;
    }).length;
    var last = start, ends = 'commissioning', failed = false;
    for (var i = 0; i < days.length; i++) {
      var when = days[i], kinds = byDay[when];
      if (when < start) continue;
      if (own(kinds, 'failure')) { last = when; ends = 'failure'; failed = true; break; }
      var mended = SURVIVAL_MENDING.filter(function (kind) { return own(kinds, kind); });
      if (mended.length) { last = when; ends = mended[0]; failed = true; break; }
      if (own(kinds, 'decommissioned')) { last = when; ends = 'decommissioned'; break; }
      if (when > start && SURVIVAL_WORKING.some(function (kind) { return own(kinds, kind); })) {
        last = when;
        ends = 'report';
      }
    }
    out.end = last;
    out.days = /** @type {number} */ (isoDay(last)) - startDay;
    out.failed = failed;
    out.ends = ends;
    return out;
  }

  /** The group a record falls in by one of the groupings: its key, its label
   * and whether its record names one (survival.group_value).
   * @param {Rec} asset a registry record
   * @param {string} by pump_type, contractor or chemistry
   * @returns {[string, string, boolean]}
   */
  function groupValue(asset, by) {
    if (by === 'chemistry') {
      var rising = cleanRisingMain(asset.rising_main);
      var state = rising ? rising.chemistry : '';
      var key = state === 'aggressive' || state === 'not_aggressive' ? state : 'unknown';
      return [key, phraseTable('survival.chemistry')[key], key !== 'unknown'];
    }
    if (SURVIVAL_GROUPINGS.indexOf(by) < 0) throw new Error('survival: no grouping by ' + by);
    var name = textField(by === 'pump_type' ? asset.pump_type : asset.installed_by);
    if (!name) return ['', phrase('survival.not_recorded'), false];
    return [foldAscii(name), name, true];
  }

  /* the 95 percent pointwise band on the log-log scale (survival._band):
   * none where the share is 1, nought where it is nought */
  function survivalBand(survival, total) {
    if (survival <= 0.0) return [0.0, 0.0];
    if (survival >= 1.0) return [null, null];
    var spread = Z_95 * Math.sqrt(total) / Math.abs(Math.log(survival));
    return [Math.pow(survival, Math.exp(spread)), Math.pow(survival, Math.exp(-spread))];
  }

  /** The Kaplan-Meier estimate over times, each a days (0 or more) and
   * whether it failed (true or false) (survival.kaplan_meier): the counts,
   * and only with at least minimum followed the steps, the median and the
   * shares at the stated years.
   * @param {Rec[]} times
   * @param {number|null} [minimum] the fewest followed a group is judged on
   * @param {number[]|null} [years] the times stated, in years
   * @returns {Rec}
   */
  function kaplanMeier(times, minimum, years) {
    var settings = minimum == null || years == null ? survivalSettings(null) : null;
    var least = minimum == null ? /** @type {Rec} */ (settings).minimum : minimum;
    var stated = years == null ? /** @type {Rec} */ (settings).years : years;
    var followed = survivalTimes(times, 'kaplan_meier').filter(function (t) {
      return t[1] || t[0] > 0;
    });
    var nFailed = followed.filter(function (t) { return t[1]; }).length;
    /** @type {number|null} */
    var lastDays = null;
    followed.forEach(function (t) { if (lastDays === null || t[0] > lastDays) lastDays = t[0]; });
    /** @type {Rec} */
    var out = {
      n: followed.length,
      n_failed: nFailed,
      n_censored: followed.length - nFailed,
      n_no_time: times.length - followed.length,
      judged: followed.length >= least,
      last_days: lastDays,
      steps: [],
      median: null,
      at_times: [],
    };
    if (!out.judged) return out;
    var survival = 1.0, total = 0.0;
    /** @type {Rec[]} */
    var raw = [];
    survivalSweep(followed).forEach(function (row) {
      var day = row[0], atRisk = row[1], failed = row[2], censored = row[3];
      if (failed) {
        if (failed < atRisk) {
          survival *= (atRisk - failed) / atRisk;
          total += failed / (atRisk * (atRisk - failed));
        } else {
          survival = 0.0;
        }
      }
      var band = survivalBand(survival, total);
      raw.push({ days: day, at_risk: atRisk, failed: failed, censored: censored,
        survival: survival, se: survival * Math.sqrt(total), lower: band[0], upper: band[1] });
    });
    out.steps = raw.map(function (step) {
      return Object.assign({}, step, { survival: pyRound(step.survival, 4),
        se: pyRound(step.se, 4), lower: roundOrNull(step.lower, 4),
        upper: roundOrNull(step.upper, 4) });
    });
    var first = function (key) {
      for (var i = 0; i < raw.length; i++) {
        if (raw[i][key] !== null && raw[i][key] <= 0.5) return raw[i].days;
      }
      return null;
    };
    out.median = { days: first('survival'), lower: first('lower'), upper: first('upper') };
    out.at_times = stated.map(function (year) {
      var threshold = year * DAYS_PER_YEAR;
      var atRisk = followed.filter(function (t) { return t[0] >= threshold; }).length;
      /** @type {Rec} */
      var entry = { years: year, at_risk: atRisk, survival: null, lower: null, upper: null };
      if (threshold <= out.last_days) {
        var before = raw.filter(function (s) { return s.days <= threshold; });
        if (before.length) {
          var step = before[before.length - 1];
          entry.survival = pyRound(step.survival, 4);
          entry.lower = roundOrNull(step.lower, 4);
          entry.upper = roundOrNull(step.upper, 4);
        } else {
          entry.survival = 1.0;
        }
      }
      return entry;
    });
    return out;
  }

  /* the regularised upper incomplete gamma function Q(a, x), by its series
   * below a + 1 and its continued fraction above (survival._gamma_q) */
  function gammaQ(a, x) {
    if (x <= 0.0) return 1.0;
    var front = Math.exp(-x + a * Math.log(x) - logGamma(a));
    var i;
    if (x < a + 1.0) {
      var term = 1.0 / a, total = term, ap = a;
      for (i = 0; i < 1000; i++) {
        ap += 1.0;
        term *= x / ap;
        total += term;
        if (Math.abs(term) < Math.abs(total) * 1e-15) break;
      }
      return Math.max(0.0, 1.0 - total * front);
    }
    var tiny = 1e-300;
    var b = x + 1.0 - a, c = 1.0 / tiny, d = 1.0 / b, h = d;
    for (i = 1; i < 1000; i++) {
      var an = -i * (i - a);
      b += 2.0;
      d = an * d + b;
      d = 1.0 / (Math.abs(d) >= tiny ? d : tiny);
      c = b + an / c;
      c = Math.abs(c) >= tiny ? c : tiny;
      var step = d * c;
      h *= step;
      if (Math.abs(step - 1.0) < 1e-15) break;
    }
    return front * h;
  }

  /** The chance a chi-squared on df degrees of freedom is at least x
   * (survival.chi2_survival).
   * @param {number} x
   * @param {number} df a whole number, 1 or more
   * @returns {number}
   */
  function chi2Survival(x, df) {
    if (!(typeof df === 'number' && isFinite(df) && df === Math.floor(df) && df >= 1)) {
      throw new Error('survival: a chi-squared needs a whole number of degrees of freedom');
    }
    return gammaQ(df / 2.0, x / 2.0);
  }

  /* matrix x = vector by Gaussian elimination with partial pivoting, the
   * first of equal pivots, or null where a pivot is under 1e-10 of the
   * largest diagonal entry (survival._solve) */
  function survivalSolve(matrix, vector) {
    var m = vector.length;
    var rows = vector.map(function (value, i) { return matrix[i].slice(0, m).concat([value]); });
    var scale = 0.0;
    for (var i = 0; i < m; i++) scale = Math.max(scale, Math.abs(rows[i][i]));
    if (!(scale > 0.0)) return null;
    for (var col = 0; col < m; col++) {
      var pivot = col;
      for (var r = col + 1; r < m; r++) {
        if (Math.abs(rows[r][col]) > Math.abs(rows[pivot][col])) pivot = r;
      }
      if (Math.abs(rows[pivot][col]) <= 1e-10 * scale) return null;
      var held = rows[col];
      rows[col] = rows[pivot];
      rows[pivot] = held;
      for (r = col + 1; r < m; r++) {
        var factor = rows[r][col] / rows[col][col];
        for (var c = col; c <= m; c++) rows[r][c] -= factor * rows[col][c];
      }
    }
    var x = vector.map(function () { return 0.0; });
    for (var row = m - 1; row >= 0; row--) {
      var total = rows[row][m];
      for (var k = row + 1; k < m; k++) total -= rows[row][k] * x[k];
      x[row] = total / rows[row][row];
    }
    return x;
  }

  /** The log-rank test across groups, each a list of days (0 or more) and
   * whether it failed (true or false) (survival.log_rank): the failures
   * observed and expected in each group; a group none of whose members was
   * at risk when any failed is left out of the test (its index in
   * not_at_risk), and the chi-squared is on one fewer degrees of freedom
   * than the groups left in, with its p; or, with nothing to compare, the
   * reason: no_failures, one_at_risk or singular.
   * @param {Rec[][]} groups two or more
   * @returns {Rec}
   */
  function logRank(groups) {
    var k = groups.length;
    if (k < 2) throw new Error('survival: a log-rank test needs two groups or more');
    var pairs = groups.map(function (g) { return survivalTimes(g, 'log_rank'); });
    var observed = pairs.map(function (g) {
      return g.filter(function (t) { return t[1]; }).length;
    });
    /** @type {Rec} */
    var out = { observed: observed, expected: null, not_at_risk: [], df: null, chi2: null,
      p: null, reason: null };
    if (!observed.reduce(function (a, b) { return a + b; }, 0)) {
      out.reason = 'no_failures';
      return out;
    }
    /* every group's times together, swept in order: at each time, the
     * number still at risk in each group, then those that leave the risk
     * set there */
    /** @type {number[][]} */
    var all = [];
    pairs.forEach(function (g, i) {
      g.forEach(function (t) { all.push([t[0], i, t[1] ? 1 : 0]); });
    });
    all.sort(function (a, b) { return a[0] - b[0]; });
    var atRisk = pairs.map(function (g) { return g.length; });
    var expected = pairs.map(function () { return 0.0; });
    var variance = pairs.map(function () { return pairs.map(function () { return 0.0; }); });
    var seen = pairs.map(function () { return false; });
    for (var at = 0; at < all.length;) {
      var day = all[at][0];
      var failed = pairs.map(function () { return 0; });
      var leaving = pairs.map(function () { return 0; });
      for (; at < all.length && all[at][0] === day; at++) {
        failed[all[at][1]] += all[at][2];
        leaving[all[at][1]] += 1;
      }
      var d = failed.reduce(function (a, b) { return a + b; }, 0);
      if (d) {
        var n = atRisk.reduce(function (a, b) { return a + b; }, 0);
        for (var i = 0; i < k; i++) {
          expected[i] += d * atRisk[i] / n;
          seen[i] = seen[i] || atRisk[i] > 0;
        }
        if (n > 1) {
          var factor = d * (n - d) / (n - 1);
          for (i = 0; i < k; i++) {
            for (var j = 0; j < k; j++) {
              var delta = i === j ? n : 0;
              variance[i][j] += factor * atRisk[i] * (delta - atRisk[j]) / (n * n);
            }
          }
        }
      }
      for (var g = 0; g < k; g++) atRisk[g] -= leaving[g];
    }
    out.expected = expected.map(function (e) { return pyRound(e, 4); });
    /** @type {number[]} */
    var kept = [];
    seen.forEach(function (yes, i) { if (yes) kept.push(i); else out.not_at_risk.push(i); });
    if (kept.length < 2) {
      out.reason = 'one_at_risk';
      return out;
    }
    var m = kept.length - 1;
    var diff = kept.slice(0, m).map(function (i) { return observed[i] - expected[i]; });
    var solved = survivalSolve(kept.slice(0, m).map(function (i) {
      return kept.slice(0, m).map(function (j) { return variance[i][j]; });
    }), diff);
    if (solved === null) {
      out.reason = 'singular';
      return out;
    }
    var chi2 = 0.0;
    for (var r = 0; r < m; r++) chi2 += diff[r] * solved[r];
    chi2 = Math.max(chi2, 0.0);
    out.df = m;
    out.chi2 = pyRound(chi2, 4);
    out.p = pyRound(chi2Survival(chi2, m), 6);
    return out;
  }

  /* one group's estimate, with its counts (survival._analysis) */
  function survivalGroup(key, label, recorded, rows, minimum, years) {
    var started = rows.filter(function (r) { return r.days !== null; });
    var km = kaplanMeier(started.map(function (r) { return { days: r.days, failed: r.failed }; }),
      minimum, years);
    return Object.assign({ key: key, label: label, recorded: recorded, n_boreholes: rows.length,
      n_no_start: rows.length - started.length }, km);
  }

  /** How long the boreholes of a register keep working, as of asOf
   * (survival.survival_analysis): each borehole's time with its groups, the
   * estimate over them all, and each grouping's groups with the comparison
   * across those judged.
   * @param {Rec[]|null} assets registry records
   * @param {string} asOf the day, YYYY-MM-DD; never read off the clock
   * @param {Config|null} [cfg] a configuration: its survival section
   * @returns {Rec}
   */
  function survivalAnalysis(assets, asOf, cfg) {
    var day = survivalDay(asOf);
    var today = /** @type {string} */ (dayToIso(day));
    var settings = survivalSettings(cfg || null);
    var read = roundRecords(assets);
    var rows = read.records.map(function (asset) {
      var row = boreholeTimes(asset, today);
      row.groups = {};
      SURVIVAL_GROUPINGS.forEach(function (by) {
        var group = groupValue(asset, by);
        row.groups[by] = { key: group[0], label: group[1], recorded: group[2] };
      });
      return row;
    });
    var groupings = SURVIVAL_GROUPINGS.map(function (by) {
      /** @type {Rec} */
      var members = {};
      /** @type {string[]} */
      var order = [];
      rows.forEach(function (row) {
        var group = row.groups[by];
        var ident = (group.recorded ? '1' : '0') + group.key;
        if (!own(members, ident)) {
          members[ident] = { key: group.key, label: group.label, recorded: group.recorded, rows: [] };
          order.push(ident);
        }
        members[ident].rows.push(row);
      });
      var groups = order.map(function (ident) {
        var m = members[ident];
        return survivalGroup(m.key, m.label, m.recorded, m.rows, settings.minimum, settings.years);
      });
      groups.sort(function (a, b) {
        if (a.recorded !== b.recorded) return a.recorded ? -1 : 1;
        if (a.n_boreholes !== b.n_boreholes) return b.n_boreholes - a.n_boreholes;
        return codePointCompare(a.label, b.label);
      });
      var compared = groups.filter(function (g) { return g.recorded && g.judged; });
      /** @type {Rec} */
      var comparison = {
        groups: compared.map(function (g) { return g.label; }),
        left_out: groups.filter(function (g) { return !(g.recorded && g.judged); })
          .map(function (g) { return g.label; }),
      };
      if (compared.length < 2) {
        Object.assign(comparison, { observed: null, expected: null, not_at_risk: [], df: null,
          chi2: null, p: null, reason: 'fewer_than_two' });
      } else {
        Object.assign(comparison, logRank(compared.map(function (g) {
          return members['1' + g.key].rows.filter(function (r) {
            return r.days !== null && (r.failed || r.days > 0);
          }).map(function (r) { return { days: r.days, failed: r.failed }; });
        })));
        comparison.not_at_risk = comparison.not_at_risk.map(function (i) {
          return compared[i].label;
        });
      }
      return { by: by, groups: groups, comparison: comparison };
    });
    var overall = survivalGroup('all', phrase('survival.all'), true, rows, settings.minimum,
      settings.years);
    return {
      as_of: today,
      min_at_risk: settings.minimum,
      at_risk_years: settings.years,
      n_boreholes: rows.length,
      n_merged: read.repeated,
      n_unreadable: read.unreadable,
      n_by_mending: rows.filter(function (r) { return SURVIVAL_MENDING.indexOf(r.ends) >= 0; }).length,
      n_before_start: rows.filter(function (r) { return r.before_start; }).length,
      n_undated: rows.filter(function (r) { return r.undated; }).length,
      boreholes: rows,
      overall: overall,
      groupings: groupings,
    };
  }

  function survivalYears(days) { return days / DAYS_PER_YEAR; }

  /* labels as a list in words: "A", "A and B", "A, B and C" */
  function survivalList(labels) {
    if (labels.length === 1) return labels[0];
    return phrase('survival.list_and', { first: labels.slice(0, -1).join(', '),
      last: labels[labels.length - 1] });
  }

  function survivalMedianText(group) {
    var median = group.median;
    if (median.days === null) {
      return phrase('survival.median_none', { years: survivalYears(group.last_days) });
    }
    if (median.upper === null) {
      return phrase('survival.median_open', { years: survivalYears(median.days),
        lower: survivalYears(median.lower) });
    }
    return phrase('survival.median', { years: survivalYears(median.days),
      lower: survivalYears(median.lower), upper: survivalYears(median.upper) });
  }

  function survivalGroupLine(group, minimum) {
    if (!group.judged) {
      return phrase('survival.too_few', { label: group.label, n: group.n, minimum: minimum,
        failed: group.n_failed, censored: group.n_censored });
    }
    return phrase('survival.group_line', { label: group.label, n: group.n,
      failed: group.n_failed, censored: group.n_censored, median: survivalMedianText(group) });
  }

  function survivalComparisonText(comparison, minimum) {
    /** @type {string[]} */
    var out = [];
    var reason = comparison.reason;
    if (reason === 'fewer_than_two') {
      out.push(phrase('survival.compare_few', { minimum: minimum }));
    } else if (reason === 'no_failures') {
      out.push(phrase('survival.compare_no_failures'));
    } else if (reason === 'one_at_risk') {
      out.push(phrase('survival.compare_one_at_risk'));
    } else if (reason === 'singular') {
      out.push(phrase('survival.compare_singular'));
    } else {
      var named = survivalList(comparison.groups.filter(function (label) {
        return comparison.not_at_risk.indexOf(label) < 0;
      }));
      if (comparison.p < 0.001) {
        out.push(phrase('survival.compared_small', { groups: named, chi2: comparison.chi2,
          df: comparison.df }));
      } else {
        out.push(phrase('survival.compared', { groups: named, chi2: comparison.chi2,
          df: comparison.df, p: comparison.p }));
      }
      out.push(phrase('survival.p_meaning'));
      if (comparison.not_at_risk.length) {
        out.push(phrase('survival.not_at_risk', { groups: survivalList(comparison.not_at_risk) }));
      }
    }
    if (comparison.left_out.length && reason !== 'fewer_than_two') {
      out.push(phrase('survival.left_out', { groups: survivalList(comparison.left_out) }));
    }
    return out;
  }

  /** What the analysis says (survival.survival_text): the summary, the
   * method, the overall estimate and each grouping's lines and comparison,
   * and the works the method cites.
   * @param {Rec} result what survivalAnalysis returns
   * @returns {Rec}
   */
  function survivalText(result) {
    var minimum = result.min_at_risk;
    var overall = result.overall;
    /** @type {string[]} */
    var summary = [];
    var total = result.n_boreholes;
    if (!total) {
      summary.push(phrase('survival.empty'));
    } else if (overall.n) {
      summary.push(phrase('survival.headline', { date: result.as_of, total: total,
        followed: overall.n, failed: overall.n_failed, censored: overall.n_censored }));
    } else {
      summary.push(phrase('survival.none_followed', { date: result.as_of, total: total }));
    }
    if (overall.n_no_time) summary.push(phrase('survival.no_time', { count: overall.n_no_time }));
    if (overall.n_no_start) summary.push(phrase('survival.no_start', { count: overall.n_no_start }));
    if (result.n_by_mending) summary.push(phrase('survival.by_mending', { count: result.n_by_mending }));
    if (result.n_before_start) {
      summary.push(phrase('survival.before_start', { count: result.n_before_start }));
    }
    if (result.n_undated) summary.push(phrase('survival.undated', { count: result.n_undated }));
    if (result.n_merged) summary.push(phrase('rounds.merged', { count: result.n_merged }));
    if (result.n_unreadable) summary.push(phrase('rounds.unreadable', { count: result.n_unreadable }));
    var byWords = phraseTable('survival.by'), intros = phraseTable('survival.by_intro');
    var citations = phraseTable('references.citations');
    return {
      summary: summary,
      method: [phrase('survival.method'), phrase('survival.minimum', { minimum: minimum }),
        phrase('survival.comparison_method')],
      overall: { heading: phrase('survival.all'), lines: [survivalGroupLine(overall, minimum)] },
      groupings: result.groupings.map(function (g) {
        return {
          by: g.by,
          heading: phrase('survival.by_heading', { by: byWords[g.by] }),
          intro: intros[g.by],
          lines: g.groups.map(function (group) { return survivalGroupLine(group, minimum); }),
          comparison: survivalComparisonText(g.comparison, minimum),
        };
      }),
      references: SURVIVAL_CITED.map(function (key) { return citations[key]; }),
    };
  }

  /** The labels of a grouping's table, in order (survival.survival_header).
   * @returns {string[]}
   */
  function survivalHeader() {
    var table = phraseTable('survival.columns');
    return Object.keys(table).map(function (key) { return table[key]; });
  }

  /** Groups as the rows of their table (survival.survival_rows).
   * @param {Rec[]} groups a grouping's groups, or [overall]
   * @returns {string[][]}
   */
  function survivalRows(groups) {
    return groups.map(function (group) {
      var counts = [group.label, String(group.n_boreholes), String(group.n),
        String(group.n_failed), String(group.n_censored)];
      if (!group.judged) return counts.concat([phrase('survival.too_few_cell'), '']);
      var median = group.median;
      if (median.days === null) return counts.concat([phrase('survival.not_reached'), '']);
      var upper = median.upper === null ? phrase('survival.not_reached')
        : phrase('survival.years_cell', { years: survivalYears(median.upper) });
      return counts.concat([phrase('survival.years_cell', { years: survivalYears(median.days) }),
        phrase('survival.band_cell', { lower: phrase('survival.years_cell',
          { years: survivalYears(median.lower) }), upper: upper })]);
    });
  }

  /** The labels of the table of numbers at risk (survival.at_risk_header).
   * @param {Rec} result what survivalAnalysis returns
   * @returns {string[]}
   */
  function atRiskHeader(result) {
    return [phrase('survival.at_risk_group')].concat(result.at_risk_years.map(function (year) {
      return phrase('survival.at_risk_year', { years: year });
    }));
  }

  /** The judged groups' numbers at risk and shares still working at each
   * stated time, a row a group (survival.at_risk_rows).
   * @param {Rec[]} groups
   * @returns {string[][]}
   */
  function atRiskRows(groups) {
    return groups.filter(function (group) { return group.judged; }).map(function (group) {
      return [group.label].concat(group.at_times.map(function (entry) {
        if (entry.survival === null) return phrase('survival.at_risk_beyond', { n: entry.at_risk });
        if (entry.lower === null) {
          return phrase('survival.at_risk_whole', { n: entry.at_risk, pct: 100.0 * entry.survival });
        }
        return phrase('survival.at_risk_cell', { n: entry.at_risk, pct: 100.0 * entry.survival,
          lower: 100.0 * entry.lower, upper: 100.0 * entry.upper });
      }));
    });
  }

  Object.assign(C, {
    SURVIVAL_GROUPINGS: SURVIVAL_GROUPINGS, DAYS_PER_YEAR: DAYS_PER_YEAR,
    boreholeTimes: boreholeTimes, groupValue: groupValue, kaplanMeier: kaplanMeier,
    chi2Survival: chi2Survival, logRank: logRank, survivalAnalysis: survivalAnalysis,
    survivalText: survivalText, survivalHeader: survivalHeader, survivalRows: survivalRows,
    atRiskHeader: atRiskHeader, atRiskRows: atRiskRows
  });

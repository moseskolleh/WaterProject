
  /* ============================================================= hydraulics
   * groundwater/hydraulics/analysis.py.
   *
   * All methods work on non-uniform time series (the sheets record 1, 2, 3 and
   * 5 minute spacings) and on true drawdown recomputed from water level minus
   * static water level - the sheet's own "drawdown" column is the increment
   * between readings and is never used. Internally time is days and discharge
   * is m3/day, so transmissivity comes out in m2/day.
   *
   * 2.303 is written out rather than Math.LN10 (2.302585...) because that is
   * the constant the Python carries and the numbers are compared against it.
   */

  /**
   * @param {number|string|null|undefined} q m3/h
   * @returns {number}
   */
  function requireDischarge(q) {
    /* A rate of zero is not a measurement, and T is proportional to Q. */
    if (q === null || q === undefined) {
      throw new Error('No discharge recorded, so transmissivity cannot be fitted');
    }
    var v = Number(q);
    if (!isFinite(v) || v <= 0) {
      throw new Error('Discharge must be greater than zero to fit an aquifer ' +
        'parameter (got ' + formatG(v) + ' m3/h); check the discharge row on ' +
        'the field sheet');
    }
    return v;
  }

  /** Cooper-Jacob straight line on drawdown against log time.
   * With no explicit window the fit uses the last full log cycle (at least 6
   * points), which is where u is smallest and the approximation holds.
   * @param {ArrayLike<number>} timeMin
   * @param {ArrayLike<number>} drawdownM
   * @param {number} dischargeM3PerH
   * @param {PumpingConfig|null} [config]
   * @param {Rec} [options] fitWindowMin, observationRadiusM, assumedStorativity
   */
  function cooperJacob(timeMin, drawdownM, dischargeM3PerH, config, options) {
    var opts = options || {};
    var cfg = (config || defaultConfig().pumping);
    requireDischarge(dischargeM3PerH);
    var t = [], s = [], i;
    for (i = 0; i < timeMin.length; i++) {
      if (timeMin[i] > 0 && isFinite(drawdownM[i])) {
        t.push(timeMin[i]); s.push(drawdownM[i]);
      }
    }
    if (t.length < 4) throw new Error('Not enough readings for a Cooper-Jacob fit');

    var window = [], fitWindow = opts.fitWindowMin || null;
    if (!fitWindow) {
      var tEnd = arrMax(t);
      var tStart = Math.max(tEnd / 10.0, arrMin(t));
      for (i = 0; i < t.length; i++) if (t[i] >= tStart) window.push(i);
      if (window.length < 6) {
        /* the six latest readings, selected by value: comparing against an
         * argsort rank picked an arbitrary six whenever the sheet's times were
         * not already in order */
        var sorted = t.slice().sort(function (a, b) { return a - b; });
        var threshold = sorted[sorted.length - Math.min(6, t.length)];
        window = [];
        for (i = 0; i < t.length; i++) if (t[i] >= threshold) window.push(i);
      }
      var wt = window.map(function (k) { return t[k]; });
      fitWindow = [arrMin(wt), arrMax(wt)];
    } else {
      for (i = 0; i < t.length; i++) {
        if (t[i] >= fitWindow[0] && t[i] <= fitWindow[1]) window.push(i);
      }
    }

    var fit = lineFit(window.map(function (k) { return Math.log(t[k]) / Math.LN10; }),
                      window.map(function (k) { return s[k]; }));
    /* A window of one level has a slope of zero give or take rounding, and
     * which side of zero the rounding falls differs between this closed form
     * and numpy's lstsq: the same sheet was "flat (0.000 m per log cycle)"
     * here and "does not increase" there. Only a slope clearly below zero is
     * a falling drawdown; one within rounding of it is a flat one. */
    if (fit.slope < -SLOPE_ROUNDING_M) {
      throw new Error('Drawdown does not increase with log time; ' +
        'Cooper-Jacob does not apply');
    }
    /* T is inversely proportional to the slope, so a window whose drawdown
     * moves by less than a dipper reads gave thousands of m2/day with a
     * straight face; a line that does not explain the window is no better.
     * The test is the one the Theis and recovery fits apply, the rise across
     * the readings; it was a fixed 0.02 m per log cycle, which also refused
     * a straight, readable handpump line in an aquifer of a few hundred
     * m2/day. A window on a tail that has flattened after rising is judged
     * in analysePumpingTest (stabilisedTail). */
    var logWindow = window.map(function (k) { return Math.log(t[k]) / Math.LN10; });
    if (fit.slope * (arrMax(logWindow) - arrMin(logWindow)) < READING_RESOLUTION_M) {
      throw new Error(phrase('pumping.cj_unreadable', { start: fitWindow[0],
        end: fitWindow[1], resolution: READING_RESOLUTION_M }));
    }
    if (fit.r2 < cfg.cooper_jacob_min_r2) {
      throw new Error('The straight line explains too little of the window ' +
        formatG(fitWindow[0]) + '-' + formatG(fitWindow[1]) + ' min (R squared ' +
        pyFixed(fit.r2, 3) + ', under ' + formatG(cfg.cooper_jacob_min_r2) +
        '), so Cooper-Jacob does not apply');
    }
    var qDay = dischargeM3PerH * 24.0;
    var T = 2.303 * qDay / (4.0 * Math.PI * fit.slope);
    var t0Min = Math.pow(10, -fit.intercept / fit.slope);

    var storativity = null;
    var obsRadius = opts.observationRadiusM;
    if (obsRadius !== null && obsRadius !== undefined) {
      storativity = 2.25 * T * (t0Min / MIN_PER_DAY) / (obsRadius * obsRadius);
    }

    /* validity: u = r^2 S / (4 T t) at the start of the fit window */
    var rEff = obsRadius ? obsRadius : 0.1;
    var sEff = storativity ? storativity : (opts.assumedStorativity || 1e-3);
    var uStart = rEff * rEff * sEff / (4.0 * T * (fitWindow[0] / MIN_PER_DAY));
    var noObservation = obsRadius === null || obsRadius === undefined;
    var uCheck;
    if (uStart < cfg.cooper_jacob_u_max && noObservation) {
      /* In the pumped well r is the well radius, so u is tiny from the first
       * minute whatever the data look like. The criterion is a distance
       * criterion; it says the straight-line form applies, not that this
       * line is a good one, and the report used to read it as a validation
       * of the fit. */
      uCheck = 'u = ' + expo(uStart, 2) + ' at the start of the fitted window, ' +
        'below the ' + cfg.cooper_jacob_u_max + ' criterion. In the pumped well ' +
        'itself this is a distance criterion met from the first minute; it ' +
        'does not test the fit';
    } else if (uStart < cfg.cooper_jacob_u_max) {
      uCheck = 'u = ' + expo(uStart, 2) + ' at the start of the fitted window, ' +
        'below the ' + cfg.cooper_jacob_u_max + ' criterion; the straight line ' +
        'approximation is valid';
    } else {
      uCheck = 'u = ' + expo(uStart, 2) + ' at the start of the fitted window ' +
        'exceeds ' + cfg.cooper_jacob_u_max + '; early data were excluded or ' +
        'results should be treated with caution';
    }

    return {
      transmissivity_m2_per_day: T,
      slope_m_per_log_cycle: fit.slope,
      intercept_t0_min: t0Min,
      storativity: storativity,
      fit_window_min: fitWindow,
      n_points: window.length,
      r_squared: fit.r2,
      u_check: uCheck,
      discharge_m3_per_h: dischargeM3PerH,
    };
  }

  /* analysis.py THEIS_MAXFEV: the model evaluations a Theis fit may take */
  var THEIS_MAXFEV = 20000;

  /** Least squares fit of the Theis well function s = Q/(4 pi T) W(u),
   * u = r^2 S / (4 T t), in log parameter space so T and S stay positive.
   * The search is a Levenberg-Marquardt that analysis.py _theis_search takes
   * step for step, and polishLog2 finishes it: the two engines used to
   * search each in its own way (scipy's curve_fit there) and agreed to one
   * part in 1e7 or 1e9, which is not close enough for a figure printed
   * beside a rounding or a replicate beside a threshold.
   *
   * A drawdown that does not grow with log time is refused: on a flat
   * record the least squares has no minimum, T runs off towards infinity and
   * S towards zero, and the transmissivity reported is wherever the
   * optimiser stopped - 1282 m2/day here and 2190 in the Python package for
   * the same sheet, both adopted at established confidence. The test is the
   * reading resolution across the whole record, as cooperJacob asks of its
   * late window: a handpump rate in an aquifer of a
   * few hundred m2/day draws down 1 to 2 cm a log cycle, and over three log
   * cycles of readings the curve still returns T to within a few percent. A
   * fit that drives S to the floor is refused for the same reason as a flat
   * record: the drawdown is nearly all an offset the curve does not model,
   * such as well loss.
   * @param {ArrayLike<number>} timeMin
   * @param {ArrayLike<number>} drawdownM
   * @param {number} dischargeM3PerH
   * @param {Rec} [options] radiusM, observationWell
   */
  function theisFit(timeMin, drawdownM, dischargeM3PerH, options) {
    var opts = options || {};
    requireDischarge(dischargeM3PerH);
    var radiusM = opts.radiusM || 0.1;
    var t = [], s = [], i;
    for (i = 0; i < timeMin.length; i++) {
      var td = timeMin[i] / MIN_PER_DAY;
      /* note: unlike Cooper-Jacob, Theis needs s > 0 - a test whose early
       * readings sit above static fits one and not the other */
      if (td > 0 && drawdownM[i] > 0) { t.push(td); s.push(drawdownM[i]); }
    }
    if (t.length < 5) throw new Error('Not enough readings for a Theis fit');
    var logTime = t.map(function (v) { return Math.log10(v); });
    /* the rise itself is not printed: on a flat record it is a few parts in
     * 1e17 either side of zero, and its sign is noise */
    var rise = lineFit(logTime, s).slope * (arrMax(logTime) - arrMin(logTime));
    if (rise < READING_RESOLUTION_M) {
      throw new Error('The drawdown rises by less than ' +
        formatG(READING_RESOLUTION_M) + ' m across the readings, which a dipper ' +
        'cannot tell from a level that holds, so T and S cannot be fitted to ' +
        'it: the aquifer gives this discharge with next to no drawdown, which ' +
        'a higher rate would measure, or recharge holds the level');
    }
    var qDay = dischargeM3PerH * 24.0;
    var calls = 0;

    function model(tt, logT, logS) {
      calls += 1;
      var T = Math.pow(10, logT), S = Math.pow(10, logS);
      var out = new Float64Array(tt.length);
      for (var k = 0; k < tt.length; k++) {
        var u = radiusM * radiusM * S / (4.0 * T * tt[k]);
        out[k] = qDay / (4.0 * Math.PI * T) * exp1(u);
      }
      return out;
    }

    var half = Math.floor(s.length / 2);
    var slope0 = Math.max(
      (s[s.length - 1] - s[half]) /
        Math.max(Math.log(t[t.length - 1] / t[half]) / Math.LN10, 0.3), 0.1);
    var T0 = 2.303 * qDay / (4.0 * Math.PI * slope0);
    var p = [Math.log(Math.max(T0, 1e-2)) / Math.LN10, -3.0];

    /* Levenberg-Marquardt on the two log parameters. */
    function costOf(params) {
      var calc = model(t, params[0], params[1]), c = 0;
      for (var k = 0; k < t.length; k++) {
        var e = calc[k] - s[k];
        c += e * e;
      }
      return c;
    }
    var lam = 1e-3, cost = costOf(p);
    /* Until no step lowers the misfit, within the budget of model
     * evaluations scipy's curve_fit had for this fit in the Python package
     * (maxfev = 20000) and with its refusal when the budget runs out. A cap of 200 iterations
     * used to stop this fit partway down a long valley - a Theis fit of
     * 412 m2/day where scipy reached 430, the Cooper-Jacob value - wherever
     * a large constant offset pushes S towards zero. */
    for (;;) {
      if (calls >= THEIS_MAXFEV) {
        throw new Error('Optimal parameters not found: Number of calls to ' +
          'function has reached maxfev = ' + THEIS_MAXFEV + '.');
      }
      var base = model(t, p[0], p[1]);
      var J = [];
      var h0 = 1e-6 * Math.max(Math.abs(p[0]), 1);
      var h1 = 1e-6 * Math.max(Math.abs(p[1]), 1);
      var f0 = model(t, p[0] + h0, p[1]);
      var f1 = model(t, p[0], p[1] + h1);
      for (var m2 = 0; m2 < t.length; m2++) {
        J.push([(f0[m2] - base[m2]) / h0, (f1[m2] - base[m2]) / h1]);
      }
      var JtJ = [[0, 0], [0, 0]], g = [0, 0];
      for (var r = 0; r < t.length; r++) {
        var res = base[r] - s[r];
        for (var a = 0; a < 2; a++) {
          g[a] += J[r][a] * res;
          for (var b = 0; b < 2; b++) JtJ[a][b] += J[r][a] * J[r][b];
        }
      }
      var stepped = false;
      for (var attempt = 0; attempt < 20; attempt++) {
        var A = [
          [JtJ[0][0] * (1 + lam), JtJ[0][1]],
          [JtJ[1][0], JtJ[1][1] * (1 + lam)],
        ];
        var delta = solveLinear(A, [-g[0], -g[1]]);
        if (!delta) { lam *= 10; continue; }
        var trial = [p[0] + delta[0], p[1] + delta[1]];
        var ct = costOf(trial);
        if (isFinite(ct) && ct < cost) {
          p = trial; cost = ct; lam = Math.max(lam / 10, 1e-12); stepped = true;
          break;
        }
        lam *= 10;
        if (lam > 1e12) break;
      }
      if (!stepped) break;
    }
    /* to the minimum itself, not to where the misfit's rounding hid it */
    p = polishLog2(theisDerivatives(qDay, radiusM), t, s, p, cost)[0];

    var Tfit = Math.pow(10, p[0]), Sfit = Math.pow(10, p[1]);
    if (!(Sfit >= THEIS_STORATIVITY_FLOOR)) {
      /* S is not printed either: it is wherever each optimiser stopped on its
       * way to underflow */
      throw new Error('The Theis fit drives the storativity below ' +
        formatG(THEIS_STORATIVITY_FLOOR) + ': the drawdown is nearly all an ' +
        'offset the Theis curve does not model, such as well loss, so T and S ' +
        'cannot be fitted to it');
    }
    var fitted = model(t, p[0], p[1]), ss = 0;
    for (var k2 = 0; k2 < t.length; k2++) {
      var e2 = fitted[k2] - s[k2];
      ss += e2 * e2;
    }
    /* The covariance analysis.py TheisResult keeps, scaled as curve_fit
     * scales it, and P10 and P90 of T from it. */
    var covariance = covarianceLog2(theisModel(qDay, radiusM), t, s, p);
    var band = logBand(p[0], covariance ? covariance[0][0] : null);
    return {
      transmissivity_m2_per_day: Tfit,
      storativity: Sfit,
      storativity_reliable: !!opts.observationWell,
      rmse_m: Math.sqrt(ss / t.length),
      discharge_m3_per_h: dischargeM3PerH,
      radius_m: radiusM,
      transmissivity_low_m2_per_day: band[0],
      transmissivity_high_m2_per_day: band[1],
      log_covariance: covariance,
    };
  }

  /** Theis recovery on residual drawdown against t/t':
   *   s' = 2.303 Q / (4 pi T) log10(t/t')
   * with t since pumping started and t' since it stopped.
   * @param {ArrayLike<number>} recoveryTimeMin
   * @param {ArrayLike<number>} residualDrawdownM
   * @param {number} pumpingDurationMin
   * @param {number} dischargeM3PerH
   * @param {boolean} [equivalentTime]
   */
  function theisRecovery(recoveryTimeMin, residualDrawdownM, pumpingDurationMin,
                         dischargeM3PerH, equivalentTime) {
    /* pumpingDurationMin is the time t/t' is formed with: after a step test
     * pass the equivalent time from equivalentPumpingTimeMin and say so. */
    requireDischarge(dischargeM3PerH);
    var tp = [], sp = [], i;
    for (i = 0; i < recoveryTimeMin.length; i++) {
      if (recoveryTimeMin[i] > 0 && isFinite(residualDrawdownM[i])) {
        tp.push(recoveryTimeMin[i]); sp.push(residualDrawdownM[i]);
      }
    }
    if (tp.length < 4) throw new Error('Not enough recovery readings');
    var x = tp.map(function (v) {
      return Math.log((pumpingDurationMin + v) / v) / Math.LN10;
    });
    var fit = lineFit(x, sp);
    if (fit.slope < -SLOPE_ROUNDING_M) {
      throw new Error('Residual drawdown does not decrease; check the data');
    }
    /* A recovery that has already finished is flat against log(t/t'), its
     * slope rounding noise, and 2.303 Q / (4 pi slope) turned that into 4e17
     * m2/day here and 6e16 in the Python package. The line is refused when it
     * falls by less than a dipper reads across the recovery readings, as a
     * Theis fit is; a slow but readable recovery, 1.5 cm a log cycle from a
     * handpump in an aquifer of 300 m2/day, still gives its transmissivity. */
    if (fit.slope * (arrMax(x) - arrMin(x)) < READING_RESOLUTION_M) {
      throw new Error('The residual drawdown falls by less than ' +
        formatG(READING_RESOLUTION_M) + ' m across the recovery readings, which ' +
        'a dipper cannot tell from a recovery already complete, so no ' +
        'transmissivity is read from it');
    }
    var qDay = dischargeM3PerH * 24.0;
    var start = arrMax(sp);
    return {
      transmissivity_m2_per_day: 2.303 * qDay / (4.0 * Math.PI * fit.slope),
      slope_m_per_log_cycle: fit.slope,
      n_points: tp.length,
      r_squared: fit.r2,
      discharge_m3_per_h: dischargeM3PerH,
      residual_at_end_m: sp[sp.length - 1],
      /* theory puts the line through the origin at t/t' = 1; the fitted line
       * generally does not, and the figure has to draw the line that was fitted */
      intercept_m: fit.intercept,
      /* the pumping time t/t' was formed with: the pumped duration of a
       * constant test, or the discharge-weighted equivalent time after a
       * step test */
      pumping_time_min: Number(pumpingDurationMin),
      equivalent_time: !!equivalentTime,
      /* |intercept| as a fraction of the residual drawdown the recovery
       * started from; theory says zero, and a large one says the line is not
       * a Theis recovery line */
      intercept_fraction: start > 0 ? Math.abs(fit.intercept) / start : 0.0,
    };
  }

  /* Hantush-Bierschenk step drawdown analysis. Fits s_w = B Q + C Q^2 through
   * the end-of-step drawdowns by regressing s_w/Q on Q, so the SLOPE is C and
   * the INTERCEPT is B. Q is m3/day, so B is day/m2 and C day2/m5.
   * stepNumbers are the sheet's numbers for the steps passed in. A step left
   * out of the fit used to renumber the rest, so the table printed "Step 1 |
   * 2.2 m3/h" beside a test details line saying step 1 ran at 1.5 m3/h.
   * Without them the steps are numbered from one. */
  /* analysis.py SAME_RATE_RTOL: step discharges closer than this,
   * relatively, are one rate written two ways. */
  var SAME_RATE_RTOL = 1e-6;

  /**
   * @param {number[]} stepDischargesM3PerH
   * @param {number[]} stepEndDrawdownsM
   * @param {Array<number|string>|null} [stepNumbers]
   */
  function hantushBierschenk(stepDischargesM3PerH, stepEndDrawdownsM, stepNumbers) {
    var q = stepDischargesM3PerH.map(function (v) { return v * 24.0; });
    var s = stepEndDrawdownsM.slice();
    if (q.length < 2) {
      throw new Error('A step test needs at least two steps with discharge');
    }
    /* Steps pumped at one rate put every point of s/Q against Q on one
     * vertical line, which any B and C fit: this fit returned all aquifer
     * loss and numpy's lstsq its minimum-norm split, and both reported
     * efficiencies. "One rate" is to a part in a million, not to the last
     * bit: 88 L/min converts to 5.279999999999999 m3/h beside a 5.28 typed in
     * m3/h, and that ulp made the line merely near-vertical, no better. */
    var qMax = Math.max.apply(null, q.map(Math.abs));
    if (Math.max.apply(null, q) - Math.min.apply(null, q) <= SAME_RATE_RTOL * qMax) {
      throw new Error('Every step was pumped at ' + formatG(stepDischargesM3PerH[0]) +
        ' m3/h, so the aquifer and well losses cannot be told apart; a step ' +
        'test needs steps at different discharges');
    }
    var sq = s.map(function (v, i) { return v / q[i]; });
    var fit = lineFit(q, sq);
    var C = fit.slope, B = fit.intercept, r2 = fit.r2;
    var fitNote = '';
    if (C < 0) {
      /* negative well loss has no physical meaning; fall back to pure
       * aquifer loss */
      C = 0.0;
      B = arrMean(sq);
      fitNote = 'negative well loss refitted as pure aquifer loss; the ' +
        'efficiencies are 100% by construction and not meaningful';
    }
    if (B < 0) {
      /* Neither has a negative aquifer loss: it made the reported well
       * efficiency negative, which went into the report as the borehole's
       * efficiency. Refit through the origin as pure well loss. */
      B = 0.0;
      var num = 0, den = 0;
      for (var i = 0; i < q.length; i++) { num += s[i]; den += q[i] * q[i]; }
      C = num / den;
      var sqBar = arrMean(sq), ssTot = 0, ssRes = 0;
      for (var j = 0; j < q.length; j++) {
        ssTot += (sq[j] - sqBar) * (sq[j] - sqBar);
        var e = sq[j] - C * q[j];
        ssRes += e * e;
      }
      r2 = (ssTot > 1e-20 * q.length * sqBar * sqBar)
        ? 1.0 - ssRes / ssTot : 1.0;
      fitNote = 'negative aquifer loss refitted as pure well loss; ' +
        'efficiencies are not meaningful';
    }
    var steps = q.map(function (qi, i) {
      var total = B * qi + C * qi * qi;
      return {
        step: stepNumbers ? Number(stepNumbers[i]) : i + 1,
        discharge_m3_per_h: qi / 24.0,
        drawdown_end_m: s[i],
        sw_over_q_day_per_m2: s[i] / qi,
        efficiency_percent: total > 0 ? 100.0 * B * qi / total : 100.0,
      };
    });
    return {
      aquifer_loss_B: B,
      well_loss_C: C,
      steps: steps,
      r_squared: r2,
      fit_note: fitNote,
      /* a line through two points is exact by construction: R squared is
       * 1.000 whatever the data, and B, C and the efficiencies are untested */
      two_point: q.length === 2,
    };
  }

  /** StepTestResult.drawdown_at and efficiency_at, at a rate in m3/day.
   * Functions of the result rather than methods on it, as they are in
   * Python: an analysis has to be plain data to leave the engine worker, and
   * a method is the one thing a structured clone cannot carry.
   * @param {Rec} stepTest what hantushBierschenk returns
   * @param {number} qDay
   * @returns {number}
   */
  function stepDrawdownAt(stepTest, qDay) {
    return stepTest.aquifer_loss_B * qDay + stepTest.well_loss_C * qDay * qDay;
  }

  /**
   * @param {Rec} stepTest what hantushBierschenk returns
   * @param {number} qDay
   * @returns {number}
   */
  function stepEfficiencyAt(stepTest, qDay) {
    var total = stepDrawdownAt(stepTest, qDay);
    return total <= 0 ? 100.0 : 100.0 * stepTest.aquifer_loss_B * qDay / total;
  }

  /* --- yield recommendation ------------------------------------------------
   * The long term yield solves s_proj(Q) = f_avail x s_available, projecting
   * Cooper-Jacob drawdown to the design period with the fitted T (plus well
   * losses when a step test is available). The stated safety factor is then
   * applied. Every input is recorded in `basis` so the recommendation is
   * traceable back to the sheet.
   */

  var METHOD_LABELS = {
    recovery: 'Theis recovery',
    cooper_jacob: 'Cooper-Jacob',
    theis: 'Theis curve fit',
    papadopulos_cooper: 'Papadopulos-Cooper',
  };

  /* Schafer's (1978) casing-storage rule, t_c = 0.6 (dc^2 - dp^2) / (Q/s)
   * minutes with the diameters in inches and Q/s in gpm/ft, restated for
   * diameters in metres and Q/s in m3/h per m: 0.6 x 39.37^2 / 1.342. */
  var CASING_STORAGE_COEFFICIENT = 693.0;

  /* The words for a field sheet's test type token. The sheets say "step" or
   * "constant" and the parser appends "+recovery" when a recovery limb was
   * recorded; a report prints the phrase, never the token. */
  var TEST_TYPE_WORDS = {
    step: 'step drawdown test',
    constant: 'constant discharge test',
  };

  /** "constant+recovery" -> "constant discharge test with recovery"
   * @param {string|null} [testType]
   * @returns {string}
   */
  function testTypeText(testType) {
    var text = String(testType === null || testType === undefined ? '' : testType);
    var plus = text.indexOf('+');
    var base = plus >= 0 ? text.slice(0, plus) : text;
    var tail = plus >= 0 ? text.slice(plus + 1) : '';
    var key = base.trim().toLowerCase();
    var words = Object.prototype.hasOwnProperty.call(TEST_TYPE_WORDS, key)
      ? TEST_TYPE_WORDS[key] : (base.trim() || 'pumping') + ' test';
    return words + (tail ? ' with recovery' : '');
  }

  /* Flags that say the recorded levels cannot all be right: a level above
   * the stated static level, below the bottom of the hole or below the pump
   * intake. A report used to certify "the drawdown and recovery curves are
   * valid" over levels 18 m below the pump intake, and the yield computed
   * from those drawdowns was called established. */
  var LEVEL_FLAGS = ['water_level_above_static', 'level_below_borehole', 'level_below_pump'];

  /* The confidence reason a flagged set of levels gives the yield. */
  var LEVELS_IN_DOUBT_REASON = 'the recorded water levels are inconsistent ' +
    'with the stated static level, pump setting or borehole depth, so the ' +
    'drawdowns the yield is computed from are as recorded and not to be ' +
    'relied on';

  /** True when the sheet's own levels contradict its static level, pump or depth.
   * @param {PumpingTest|null} [test]
   * @returns {boolean}
   */
  function levelsInDoubt(test) {
    return ((test && test.flags) || []).some(function (f) {
      return LEVEL_FLAGS.indexOf(f.code) >= 0;
    });
  }

  /** Python's PumpingTest.has_discharge: any step with a rate. The browser's
   * test object is plain data and its rates are edited after parsing, so this
   * is asked of the steps each time rather than stored.
   * @param {PumpingTest|null} [test]
   * @returns {boolean}
   */
  function hasDischarge(test) {
    return ((test && test.steps) || []).some(function (s) {
      return s.discharge_m3_per_h !== null && s.discharge_m3_per_h !== undefined;
    });
  }

  /* What a two-step Hantush-Bierschenk fit is worth, in the report's words. */
  var TWO_POINT_NOTE = 'The line is fitted through two points, so it is exact ' +
    'by construction: the R squared of 1.000 tests nothing, and B, C and the ' +
    'efficiencies are indicative until a third step is pumped';

  /** [minutes, isEquivalent]: the pumping time a recovery is read against.
   * Theis recovery assumes one rate for the whole pumping time. After a step
   * test the last rate was pumped for the last step only; using the last rate
   * with the total time says the aquifer was stressed harder than it was and
   * biases the transmissivity. The usual correction is the discharge-weighted
   * equivalent time, sum(Q_i dt_i) / Q_last. A constant test, or a step test
   * missing a rate, uses the recorded duration.
   * @param {PumpingTest} test
   * @returns {[number|null, boolean]}
   */
  function equivalentPumpingTimeMin(test) {
    var steps = (test.steps || []).filter(function (s) {
      return s.time_min && s.time_min.length;
    });
    var recorded = test.pumping_duration_min === undefined ? null : test.pumping_duration_min;
    if (!steps.length) return [recorded, false];
    var missingQ = steps.some(function (s) {
      return s.discharge_m3_per_h === null || s.discharge_m3_per_h === undefined;
    });
    if (String(test.test_type || '').indexOf('step') !== 0 || steps.length < 2 || missingQ) {
      return [recorded, false];
    }
    var qLast = Number(steps[steps.length - 1].discharge_m3_per_h);
    var durations = stepDurationsMin(steps)[0];
    var volume = 0.0;
    steps.forEach(function (step, i) {
      volume += Number(step.discharge_m3_per_h) * durations[i];
    });
    if (qLast <= 0 || volume <= 0) return [recorded, false];
    return [volume / qLast, true];
  }

  /** [minutes per step, restarted step numbers]: how long each step pumped.
   * A step's times normally run on from the step before (61, 62 ... after a
   * step ending at 60), and its length is its last reading less that step's.
   * Some sheets count each step from its own start instead, so a step opens
   * at or before the minute the step before it ended; its own last reading is
   * then its length, and the lengths add. Differencing those steps against
   * the step before gave them no length at all: the recovery after such a
   * step test was read against 30 minutes where the steps had pumped 158. A
   * step with no readable time pumped for no measurable time.
   * @param {Rec[]|null} [steps]
   */
  function stepDurationsMin(steps) {
    var durations = [], restarted = [], previousEnd = null;
    (steps || []).forEach(function (step) {
      var finite = (step.time_min || []).filter(function (v) { return isFinite(v); });
      if (!finite.length) { durations.push(0.0); return; }
      var start = arrMin(finite), end = arrMax(finite);
      if (previousEnd !== null && start <= previousEnd) {
        restarted.push(step.step_number);
        durations.push(Math.max(end, 0.0));
      } else {
        durations.push(Math.max(end - (previousEnd || 0.0), 0.0));
      }
      previousEnd = end;
    });
    return [durations, restarted];
  }

  /** The minutes to add to each step's times to put it on the test's clock.
   * Read by the same rule as stepDurationsMin: a step counted from its own
   * start began when the step before it ended, so it moves to there, and a
   * step that runs on from it moves with it. On a sheet whose times run
   * through the test every offset is zero. The recorded duration and the
   * overview used to read the restarted clocks as written, so a test that
   * pumped for 158 minutes was printed as lasting 60 and drawn as three
   * steps stacked on the same hour.
   * @param {Rec[]|null} [steps]
   * @returns {number[]}
   */
  function stepOffsetsMin(steps) {
    var offsets = [], shift = 0.0, previousEnd = null;
    (steps || []).forEach(function (step) {
      var finite = (step.time_min || []).filter(function (v) { return isFinite(v); });
      if (!finite.length) { offsets.push(shift); return; }
      var start = arrMin(finite), end = arrMax(finite);
      if (previousEnd !== null && start <= previousEnd) shift += previousEnd;
      offsets.push(shift);
      previousEnd = end;
    });
    return offsets;
  }

  /** How long casing storage controls the drawdown, in minutes. Early in a
   * test the pump takes water standing in the casing before it takes much
   * from the aquifer, and a drawdown curve read inside that period is the
   * borehole emptying, not the ground responding. A 5 inch casing with a
   * 1.25 inch riser and a specific capacity of 0.09 m3/h per m gives about
   * two hours: a thirty-minute test on such a borehole never leaves the
   * casing.
   * @param {number|null|undefined} specificCapacity m3/h per m
   * @param {PumpingConfig} [config]
   * @returns {number|null}
   */
  function casingStorageMin(specificCapacity, config) {
    var cfg = config || defaultConfig().pumping;
    if (!specificCapacity || specificCapacity <= 0) return null;
    var dc = cfg.casing_diameter_in * 0.0254;
    var dp = cfg.riser_diameter_in * 0.0254;
    var area = dc * dc - dp * dp;
    if (area <= 0) return null;
    return CASING_STORAGE_COEFFICIENT * area / specificCapacity;
  }

  /** config with the casing and riser the field sheet records (analysis.py
   * sheet_config): the casing-storage period, the Papadopulos-Cooper casing
   * radius and the sentences naming the casing all read them from there. A
   * sheet that records one of the two is read with the configuration's
   * other, and where that pair leaves no water between casing and riser the
   * configuration's pair is kept.
   * @param {PumpingTest} test
   * @param {PumpingConfig} [config]
   * @returns {PumpingConfig}
   */
  function sheetConfig(test, config) {
    var cfg = config || defaultConfig().pumping;
    var recorded = {};
    ['casing_diameter_in', 'riser_diameter_in'].forEach(function (key) {
      if (test[key] !== null && test[key] !== undefined) recorded[key] = test[key];
    });
    if (!Object.keys(recorded).length) return cfg;
    var merged = Object.assign({}, cfg, recorded);
    return merged.casing_diameter_in > merged.riser_diameter_in ? merged : cfg;
  }

  /** [start, end, level, earlySlope] where the drawdown has stopped growing,
   * or null (analysis.py stabilised_tail). The readings of the last
   * stabilised_span_log10 log cycles are the tail, and the log cycle before
   * them is what it is held against: the level has stabilised when the
   * tail's fitted line moves by less than a dipper reads across it, and its
   * slope is under stabilised_slope_ratio of the slope before it, which rose
   * by at least a dipper's reading. It was judged on the last three
   * readings, within 5 cm of each other, which an ordinary Theis drawdown
   * read hourly at the end of a 24-hour test met.
   * @param {ArrayLike<number>} timeMin
   * @param {ArrayLike<number>} levelM
   * @param {PumpingConfig} [config]
   * @returns {number[]|null}
   */
  function stabilisedTail(timeMin, levelM, config) {
    var cfg = config || defaultConfig().pumping;
    var t = [], wl = [], i;
    for (i = 0; i < timeMin.length; i++) {
      if (isFinite(timeMin[i]) && isFinite(levelM[i]) && timeMin[i] > 0) {
        t.push(timeMin[i]); wl.push(levelM[i]);
      }
    }
    if (t.length < 6) return null;
    var end = arrMax(t);
    var cut = end / Math.pow(10, cfg.stabilised_span_log10);
    var tailT = [], tailWl = [], beforeT = [], beforeWl = [];
    for (i = 0; i < t.length; i++) {
      var lt = Math.log(t[i]) / Math.LN10;
      if (t[i] >= cut) { tailT.push(lt); tailWl.push(wl[i]); }
      else if (t[i] >= cut / 10.0) { beforeT.push(lt); beforeWl.push(wl[i]); }
    }
    if (tailT.length < 3 || beforeT.length < 3) return null;
    var late = lineFit(tailT, tailWl).slope;
    var early = lineFit(beforeT, beforeWl).slope;
    if (Math.abs(late) * (arrMax(tailT) - arrMin(tailT)) >= READING_RESOLUTION_M) return null;
    if (early * (arrMax(beforeT) - arrMin(beforeT)) < READING_RESOLUTION_M) return null;
    if (late >= cfg.stabilised_slope_ratio * early) return null;
    var held = 0;
    tailWl.forEach(function (v) { held += v; });
    var start = Infinity;
    for (i = 0; i < t.length; i++) if (t[i] >= cut && t[i] < start) start = t[i];
    return [start, end, held / tailWl.length, early];
  }

  /** The deepest water level any pumping step reached, metres below datum.
   * @param {PumpingTest} test
   * @returns {number|null}
   */
  function deepestPumpingLevel(test) {
    var levels = [];
    (test.steps || []).forEach(function (s) {
      var finite = (s.water_level_m || []).filter(function (v) { return isFinite(v); });
      if (finite.length) levels.push(arrMax(finite));
    });
    return levels.length ? arrMax(levels) : null;
  }

  /** The one pump intake depth a report prints, and why. A report with a
   * seasonal projection used to say "install at 39 m" in its recommendation
   * and "set the intake at 40 m" three paragraphs later. The deeper of the
   * two is the depth, everywhere, and the reason travels with it.
   * @param {PumpingAnalysis|null} analysis
   * @param {Rec|null} [seasonal] a seasonal projection
   * @returns {[number|null, string]}
   */
  function pumpIntakeDepth(analysis, seasonal) {
    var rec = analysis ? analysis.yield_recommendation : null;
    var depth = rec ? rec.pump_installation_depth_m : null;
    if (depth === null || depth === undefined) return [null, ''];
    var seasonalDepth = null;
    if (seasonal && seasonal.is_established) {
      seasonalDepth = seasonal.pump_installation_depth_m === undefined
        ? null : seasonal.pump_installation_depth_m;
    }
    if (seasonalDepth !== null && seasonalDepth > depth) {
      return [Number(seasonalDepth),
        'deep enough for the drought-year low in the seasonal projection'];
    }
    if (seasonalDepth !== null) {
      return [Number(depth),
        'which also covers the drought-year low in the seasonal projection'];
    }
    return [Number(depth), ''];
  }

  /** One sentence for a report: what the yield rests on.
   * @param {Rec|null} [rec] a yield recommendation
   * @returns {string}
   */
  function confidenceText(rec) {
    if (!rec || rec.safe_yield_m3_per_h === null || rec.safe_yield_m3_per_h === undefined) {
      return '';
    }
    if (rec.confidence !== 'indicative') {
      return 'The yield is established: the test ran long enough to show the ' +
        "aquifer's late-time behaviour and the adopted transmissivity fit to " +
        'standard.';
    }
    return 'The yield is indicative, not established: ' +
      (rec.confidence_reasons || []).join('; ') +
      '. Confirm it by a longer test or by monitoring the pumping level in ' +
      'service before it is relied on.';
  }

  /* "established" or "indicative" and the sentence, as fields on the
   * recommendation so a report reads them the way Python reads the
   * properties. */
  function settleConfidence(rec) {
    if (!rec.confidence) rec.confidence = 'established';
    if (!rec.confidence_reasons) rec.confidence_reasons = [];
    rec.is_indicative = rec.confidence === 'indicative';
    rec.confidence_text = confidenceText(rec);
    return rec;
  }

  /* Why the pump setting leaves nothing to draw on, in the sheet's numbers. */
  function noUsableDrawdownReason(test, cfg) {
    var swl = test.static_water_level_m;
    var where, gap, reserves, fix;
    if (test.pump_setting_m !== null && test.pump_setting_m !== undefined) {
      where = 'the pump intake at ' + pyFixed(test.pump_setting_m, 1) + ' m';
      gap = test.pump_setting_m - swl;
      reserves = ['the ' + formatG(cfg.pump_submergence_min_m) + ' m submergence margin'];
      fix = 'set the pump deeper';
    } else {
      where = 'the borehole bottom at ' + pyFixed(test.borehole_depth_m, 1) + ' m';
      gap = test.borehole_depth_m - swl;
      reserves = ['the 3 m clearance above the bottom',
        'the ' + formatG(cfg.pump_submergence_min_m) + ' m submergence margin'];
      fix = 'record the pump setting or deepen the borehole';
    }
    if (cfg.seasonal_allowance_m > 0) {
      reserves.push('the ' + formatG(cfg.seasonal_allowance_m) + ' m dry-season reserve');
      fix += ' or reduce the reserve';
    }
    var position = gap >= 0
      ? 'is ' + pyFixed(gap, 1) + ' m below the static level of ' + pyFixed(swl, 1) + ' m'
      : 'is ' + pyFixed(-gap, 1) + ' m above the static level of ' + pyFixed(swl, 1) + ' m';
    var listed = reserves.length === 1 ? reserves[0]
      : reserves.slice(0, -1).join(', ') + ' and ' + reserves[reserves.length - 1];
    return where + ' ' + position + '; after ' + listed +
      ' no usable drawdown remains - ' + fix;
  }

  /**
   * @param {PumpingTest} test
   * @param {number|null|undefined} transmissivity m2/day
   * @param {Rec|null} [stepResult] what hantushBierschenk returns
   * @param {PumpingConfig} [config]
   * @param {Rec} [options] assumedStorativity, effectiveRadiusM, transmissivitySource, noTransmissivityReason
   */
  function recommendYield(test, transmissivity, stepResult, config, options) {
    var opts = options || {};
    var cfg = config || defaultConfig().pumping;
    var assumedStorativity = opts.assumedStorativity === undefined
      ? 1e-3 : opts.assumedStorativity;
    var effectiveRadiusM = opts.effectiveRadiusM === undefined
      ? 0.1 : opts.effectiveRadiusM;
    var swl = test.static_water_level_m;

    var qLast = null, sEnd = null;
    if (test.steps && test.steps.length) {
      var last = test.steps[test.steps.length - 1];
      qLast = last.discharge_m3_per_h;
      if (swl !== null && swl !== undefined) {
        sEnd = last.water_level_m[last.water_level_m.length - 1] - swl;
      }
    }
    var specificCapacity = null, specificCapacityBasis = '';
    if (qLast && sEnd && sEnd > 0) {
      specificCapacity = qLast / sEnd;
      /* a specific capacity is a rate over a drawdown at a time: 0.09 m3/h
       * per m after thirty minutes is not 0.09 after a day, and printed bare
       * to three figures it read as a property of the borehole */
      var lastFinite = (last.time_min || []).filter(function (v) { return isFinite(v); });
      var minutes = lastFinite.length ? arrMax(lastFinite) : null;
      specificCapacityBasis = formatG(qLast) + ' m3/h over ' + pyFixed(sEnd, 1) +
        ' m of drawdown' + (minutes ? ' after ' + formatG(minutes) + ' minutes' : '');
    }
    var deepest = deepestPumpingLevel(test);

    /* available drawdown: static level to pump intake less a submergence margin */
    var available = null;
    if (swl !== null && swl !== undefined &&
        test.pump_setting_m !== null && test.pump_setting_m !== undefined) {
      available = test.pump_setting_m - swl - cfg.pump_submergence_min_m;
    } else if (swl !== null && swl !== undefined &&
               test.borehole_depth_m !== null && test.borehole_depth_m !== undefined) {
      available = test.borehole_depth_m - swl - cfg.pump_submergence_min_m - 3.0;
    }

    /* Reserve the dry-season water-table decline before taking the usable
     * fraction. A test run in the rains sits on a higher static level than the
     * borehole will see at the end of the dry season, so the raw available
     * drawdown would over-state the sustainable yield. */
    /* A zero here is an answer (the intake sits at the submergence margin),
     * not a missing value, so only null is treated as unknown. */
    var usable = available !== null
      ? Math.max(available - cfg.seasonal_allowance_m, 0.0) *
        cfg.available_drawdown_fraction
      : null;

    function pending(reason) {
      return settleConfidence({
        specific_capacity_m3hr_per_m: specificCapacity,
        available_drawdown_m: available,
        usable_drawdown_m: usable,
        projected_drawdown_m: null,
        long_term_yield_m3_per_h: null,
        safe_yield_m3_per_h: null,
        safety_factor: cfg.safety_factor,
        design_period_days: cfg.design_period_days,
        pump_installation_depth_m: null,
        basis: 'Yield recommendation pending: ' + reason + '.',
        pending_reason: reason,
        safe_yield_low_m3_per_h: null,
        safe_yield_high_m3_per_h: null,
        envelope_basis: '',
        confidence: 'established',
        confidence_reasons: [],
        specific_capacity_basis: specificCapacityBasis,
        pump_depth_basis: '',
        deepest_pumping_level_m: deepest,
      });
    }

    if (transmissivity === null || transmissivity === undefined ||
        swl === null || swl === undefined) {
      /* Name what is actually missing: blaming the discharge when it was
       * recorded and the fit simply failed sends the crew back to the field
       * for a number that is already on the sheet. */
      var missing = [];
      if (swl === null || swl === undefined) missing.push('static water level is missing');
      if (transmissivity === null || transmissivity === undefined) {
        var anyQ = (test.steps || []).some(function (s) { return s.discharge_m3_per_h; });
        /* opts.noTransmissivityReason says why, when fits ran and every one
         * was rejected on its own result; a sheet with no pumping readings
         * has no step to carry a rate (analysis.py) */
        missing.push(!(test.steps || []).length ? phrase('pumping.no_readings_pending')
          : anyQ ? (opts.noTransmissivityReason ||
            'transmissivity could not be fitted from the readings')
          : 'discharge is missing on the field sheet');
      }
      return pending(missing.join(' and '));
    }

    /* No drawdown to spend is a finding about the pump setting. It used to
     * come back as a blank recommendation with no reason, which every report
     * then blamed on the discharge. */
    if (usable === null) {
      return pending('neither the pump setting nor the borehole depth is ' +
        'recorded, so the available drawdown cannot be computed');
    }
    if (usable <= 0) return pending(noUsableDrawdownReason(test, cfg));

    var tDesign = cfg.design_period_days;
    var logTerm = Math.log(2.25 * transmissivity * tDesign /
      (effectiveRadiusM * effectiveRadiusM * assumedStorativity)) / Math.LN10;

    /* B Q + C Q^2 is the drawdown at the end of a step, so the projection
     * from a step test runs from the length of a step: the one the sheet
     * states, or the first step's own last reading, as the short-test check
     * reads it. A blank length used to project from the whole test. */
    var tStepMin = pumpedDurationMin(test)[0] || test.pumping_duration_min || 180.0;

    function projectedDrawdown(qM3PerH) {
      var qDay = qM3PerH * 24.0;
      var s = 2.303 * qDay / (4.0 * Math.PI * /** @type {number} */ (transmissivity)) * logTerm;
      if (stepResult) {
        /* B Q + C Q^2 is the drawdown at the step duration; the Cooper-Jacob
         * time projection from step length to design period replaces the
         * plain projection above rather than adding to it. */
        s = stepDrawdownAt(stepResult, qDay);
        s += 2.303 * qDay / (4.0 * Math.PI * /** @type {number} */ (transmissivity)) *
          Math.log(tDesign / (tStepMin / MIN_PER_DAY)) / Math.LN10;
      }
      return s;
    }

    /* Bisect Q so projected drawdown equals the usable drawdown. The bracket
     * starts at nothing, which projects no drawdown: it started at 0.01 m3/h
     * and nothing checked that the root lay above it, so any yield below that
     * came back as 0.01 whatever the transmissivity. */
    var qLo = 0.0, qHi = 200.0;
    if (projectedDrawdown(qHi) <= usable) {
      /* The search would hand back its ceiling as if it were an answer.
       * Either the transmissivity is implausible or the drawdown budget is
       * enormous; in both cases this test does not limit the yield. */
      return pending('the drawdown projection does not limit the yield within ' +
        formatG(qHi) + ' m3/h, so the usable drawdown is not the constraint; ' +
        'check the transmissivity fit before relying on this test');
    }
    for (var it = 0; it < 80; it++) {
      var qMid = 0.5 * (qLo + qHi);
      if (projectedDrawdown(qMid) > usable) qHi = qMid; else qLo = qMid;
    }
    var longTerm = qLo;
    var safe = longTerm / cfg.safety_factor;

    var sAtSafe = projectedDrawdown(safe);
    /* The intake goes where the drawdown the yield was computed on exists.
     * The long-term yield was found by spending the usable drawdown, which
     * was measured down to the test's pump setting; the intake used to be
     * raised to just clear the drawdown at the safe rate instead, which put
     * it 3 m above the level the test itself had reached and spent the
     * safety factor on lifting the pump rather than on the rate. It is now
     * set below the static level plus the dry-season reserve, the usable
     * drawdown and the submergence margin, and never above the deepest
     * level the test drew the water to, with the same submergence under it.
     * That floor is a reading, so it holds only where the readings do: a
     * level the sheet itself shows cannot be right (below the pump, below the
     * bottom of the hole) set a Kuntolo intake at 67 m from a 78.5 m reading
     * in a 70 m hole. The pump cannot have drawn the level below its own
     * setting either, so the floor never goes deeper than the test pump did. */
    var pumpDepth = swl + cfg.seasonal_allowance_m + usable + cfg.pump_submergence_min_m;
    var reached = '';
    var hasPumpSetting = test.pump_setting_m !== null && test.pump_setting_m !== undefined;
    if (deepest !== null && deepest !== undefined && levelsInDoubt(test)) {
      reached = '; the deepest level recorded, ' + pyFixed(deepest, 1) + ' m, is ' +
        'left out because the recorded levels are inconsistent with the stated ' +
        'static level, pump setting or borehole depth';
    } else if (deepest !== null && deepest !== undefined) {
      var floor = deepest + cfg.pump_submergence_min_m;
      var atPump = hasPumpSetting && floor > test.pump_setting_m;
      if (atPump) floor = test.pump_setting_m;
      reached = '; the test itself drew the level to ' + pyFixed(deepest, 1) + ' m' +
        (qLast ? ' at ' + formatG(qLast) + ' m3/h' : '');
      if (floor > pumpDepth) {
        pumpDepth = floor;
        reached += ', which sets the intake' + (atPump
          ? ' at the ' + formatG(test.pump_setting_m) + ' m the test pump was set to'
          : '');
      }
    }
    /* Rounded to the next whole metre down the hole, except where the
     * clearance above the bottom governs: rounding down the hole after the cap
     * put a 45.5 m hole's intake at 43 m, 2.5 m above the bottom, beside text
     * saying it was capped 3 m above. */
    pumpDepth = Math.ceil(pumpDepth);
    var capped = '';
    if (test.borehole_depth_m && pumpDepth > test.borehole_depth_m - 3.0) {
      pumpDepth = Math.floor(test.borehole_depth_m - 3.0);
      capped = ', capped 3 m above the ' + formatG(test.borehole_depth_m) +
        ' m bottom of the borehole';
    }
    var pumpDepthBasis = 'Pump intake at ' + formatG(pumpDepth) + ' m: the static ' +
      'level ' + pyFixed(swl, 1) + ' m plus the ' + formatG(cfg.seasonal_allowance_m) +
      ' m dry-season reserve, the ' + pyFixed(usable, 1) + ' m of drawdown the ' +
      'long-term yield is projected to use and ' +
      formatG(cfg.pump_submergence_min_m) + ' m of submergence' + reached + capped +
      '. The safety factor is kept on the rate, not spent on raising the pump.';

    var method = METHOD_LABELS[opts.transmissivitySource || ''] || '';
    var pct = Math.round(cfg.available_drawdown_fraction * 100) + '%';
    var basis = 'Transmissivity ' + pyFixed(transmissivity, 1) + ' m2/day' +
      (method ? ' from the ' + method + ' fit' : '') +
      '; drawdown projected to ' + pyFixed(tDesign, 0) + ' days with storativity ' +
      'assumed ' + formatG(assumedStorativity) + ' and effective radius ' +
      effectiveRadiusM + ' m; usable drawdown taken as ' + pct + ' of the ' +
      'available drawdown ' + pyFixed(/** @type {number} */ (available), 1) + ' m (static level to pump ' +
      'intake less ' + pyFixed(cfg.pump_submergence_min_m, 0) + ' m submergence), ' +
      'after reserving a ' + pyFixed(cfg.seasonal_allowance_m, 0) + ' m dry-season ' +
      'water-table decline' +
      (stepResult ? '; well losses from the step test are included' : '') +
      '. A safety factor of ' + cfg.safety_factor + ' is applied to the long ' +
      'term yield.';

    return settleConfidence({
      specific_capacity_m3hr_per_m: specificCapacity,
      available_drawdown_m: available,
      usable_drawdown_m: usable,
      projected_drawdown_m: sAtSafe,
      long_term_yield_m3_per_h: longTerm,
      safe_yield_m3_per_h: safe,
      safety_factor: cfg.safety_factor,
      design_period_days: tDesign,
      pump_installation_depth_m: pumpDepth,
      basis: basis,
      pending_reason: '',
      safe_yield_low_m3_per_h: null,
      safe_yield_high_m3_per_h: null,
      envelope_basis: '',
      confidence: 'established',
      confidence_reasons: [],
      specific_capacity_basis: specificCapacityBasis,
      pump_depth_basis: pumpDepthBasis,
      deepest_pumping_level_m: deepest,
    });
  }

  /* Storativity is never resolvable from a single pumped well, the effective
   * radius depends on the gravel pack and development, and the wet-to-dry
   * decline is a regional rule of thumb. The safe yield is proportional to
   * none of them individually but sensitive to all of them, so the honest
   * output is a band. */
  var ENVELOPE_STORATIVITY = [1e-4, 1e-2];
  var ENVELOPE_RADIUS_M = [0.075, 0.15];
  var ENVELOPE_SEASONAL_M = [1.0, 4.0];

  /**
   * @param {PumpingAnalysis} analysis
   * @param {PumpingConfig} [config]
   * @returns {void}
   */
  function attachYieldEnvelope(analysis, config) {
    var cfg = config || defaultConfig().pumping;
    var rec = analysis.yield_recommendation;
    if (!rec || rec.safe_yield_m3_per_h === null) return;

    /* A fit the analysis rejected does not widen the band either: Dr Timbo's
     * "0.39 m3/h (0.28 to 1.2)" took its top from the recovery line it had
     * just refused for missing the origin. The adopted fit stays in even when
     * it is a casing-storage fallback, since the yield itself rests on it. */
    var disqualified = analysis.disqualified || {};
    var adoptedName = adoptedFit(analysis).method;
    var fitted = fittedMethods(analysis)
      .filter(function (f) {
        return f[1].transmissivity_m2_per_day &&
          (!Object.prototype.hasOwnProperty.call(disqualified, f[0]) ||
            f[0] === adoptedName);
      })
      .map(function (f) { return f[1].transmissivity_m2_per_day; });
    if (adoptedName === 'papadopulos_cooper') {
      /* adopted only when every other fit was rejected, so it is the band */
      fitted = [analysis.papadopulos_cooper.transmissivity_m2_per_day];
    }
    if (!fitted.length) return;
    /* when only one method fitted there is no spread to measure, so allow the
     * factor of two that separates methods on a typical basement borehole */
    var tRange = fitted.length > 1
      ? [arrMin(fitted), arrMax(fitted)]
      : [fitted[0] / 1.5, fitted[0] * 1.5];

    var yields = [];
    tRange.forEach(function (transmissivity) {
      ENVELOPE_STORATIVITY.forEach(function (storativity) {
        ENVELOPE_RADIUS_M.forEach(function (radius) {
          ENVELOPE_SEASONAL_M.forEach(function (seasonal) {
            var variant = Object.assign({}, cfg, { seasonal_allowance_m: seasonal });
            var trial = recommendYield(analysis.test, transmissivity,
              analysis.step_test, variant, {
                assumedStorativity: storativity, effectiveRadiusM: radius,
              });
            if (trial.safe_yield_m3_per_h) yields.push(trial.safe_yield_m3_per_h);
          });
        });
      });
    });
    if (!yields.length) return;
    // the central figure is inside its own range (see the Python)
    yields.push(rec.safe_yield_m3_per_h);
    rec.safe_yield_low_m3_per_h = arrMin(yields);
    rec.safe_yield_high_m3_per_h = arrMax(yields);
    rec.envelope_basis = 'Range over transmissivity ' + pyFixed(tRange[0], 1) + '-' +
      pyFixed(tRange[1], 1) + ' m2/day' +
      (fitted.length > 1 ? ' (spread between the fitted methods)' : '') +
      ', storativity ' + formatG(ENVELOPE_STORATIVITY[0]) + '-' +
      formatG(ENVELOPE_STORATIVITY[1]) + ', effective radius ' +
      ENVELOPE_RADIUS_M[0] + '-' + ENVELOPE_RADIUS_M[1] + ' m and a dry-season ' +
      'decline of ' + pyFixed(ENVELOPE_SEASONAL_M[0], 0) + '-' +
      pyFixed(ENVELOPE_SEASONAL_M[1], 0) + ' m. Design to the lower figure where ' +
      'the supply must not fail in a dry year.';
  }

  /** "2.4 m3/h (range over the assumptions, 1.8 to 3.1)": never a bare
   * number for an assumed one, and never a bare range either, beside the
   * bootstrap's P10 to P90 band the decision lines print on the same yield.
   * @param {Rec|null} [rec] a yield recommendation
   * @returns {string}
   */
  function yieldRangeText(rec) {
    if (!rec || rec.safe_yield_m3_per_h === null) return 'pending';
    var value = formatG(roundSig(rec.safe_yield_m3_per_h, 2), 2);
    if (rec.safe_yield_low_m3_per_h === null || rec.safe_yield_high_m3_per_h === null ||
        rec.safe_yield_low_m3_per_h === undefined ||
        rec.safe_yield_high_m3_per_h === undefined) {
      return value + ' m3/h';
    }
    return phrase('decision.yield_envelope', { value: value,
      low: formatG(roundSig(rec.safe_yield_low_m3_per_h, 2), 2),
      high: formatG(roundSig(rec.safe_yield_high_m3_per_h, 2), 2) });
  }

  /* Run every applicable analysis on a parsed pumping test. Methods that need
   * missing inputs are skipped with a flag instead of failing, so partially
   * filled sheets still produce curves and a report skeleton. */
  /* Every method that fitted, in order of preference. */
  function fittedMethods(analysis) {
    return [['recovery', analysis.recovery], ['cooper_jacob', analysis.cooper_jacob],
      ['theis', analysis.theis]].filter(function (f) { return !!f[1]; });
  }

  /** {method, result, qualifies} for the transmissivity the yield rests on.
   * The first method in order of preference whose straight line reaches
   * min_fit_r_squared is adopted, skipping any the analysis disqualified;
   * Theis is a curve fit with no R squared and is always eligible, which
   * keeps it last. When nothing reaches the threshold the best of the poor
   * fits is still adopted (the highest R squared among the straight lines,
   * the curve fit only when it is all there is) so a yield is produced, and
   * qualifies is false so the caller can flag it.
   * The best of the poor fits is taken from the fits nothing disqualified,
   * and only when there are none from the fits disqualified for lying inside
   * the casing-storage period. A fit in invalid_fits is never adopted: the
   * pick used to run over every fit, so a recovery line meeting t/t' = 1 at
   * 60% of its drawdown won on its R squared of 0.99 and the yield rested on
   * the one result the analysis had rejected. When nothing is left the
   * method is null and the yield is pending.
   * @param {PumpingAnalysis} analysis
   */
  function adoptedFit(analysis) {
    var fits = fittedMethods(analysis);
    var disqualified = analysis.disqualified || {};
    var invalid = analysis.invalid_fits || {};
    var has = function (map, key) { return Object.prototype.hasOwnProperty.call(map, key); };
    var minR2 = analysis.min_fit_r_squared === undefined
      ? defaultConfig().pumping.min_fit_r_squared : analysis.min_fit_r_squared;
    for (var i = 0; i < fits.length; i++) {
      if (has(disqualified, fits[i][0])) continue;
      var r2 = fits[i][1].r_squared;
      if (r2 === undefined || r2 === null || r2 >= minR2) {
        return { method: fits[i][0], result: fits[i][1], qualifies: true };
      }
    }
    var pool = fits.filter(function (f) { return !has(disqualified, f[0]); });
    if (!pool.length) {
      /* every fit disqualified: the Papadopulos-Cooper fit, which models the
       * casing storage the others read as aquifer, comes before the
       * casing-storage fallback when it is valid (analysis.py adopted_fit) */
      if (analysis.papadopulos_cooper && !analysis.papadopulos_cooper_invalid) {
        return { method: 'papadopulos_cooper', result: analysis.papadopulos_cooper,
          qualifies: false };
      }
      pool = fits.filter(function (f) { return !has(invalid, f[0]); });
    }
    if (!pool.length) return { method: null, result: null, qualifies: false };
    var score = function (fit) {
      var r = fit[1].r_squared;
      return (r === undefined || r === null || !r) ? -1.0 : r;
    };
    var best = pool[0];
    for (var j = 1; j < pool.length; j++) {
      if (score(pool[j]) > score(best)) best = pool[j];
    }
    return { method: best[0], result: best[1], qualifies: false };
  }

  /** The reason a fitted method was passed over, or an empty string.
   * @param {PumpingAnalysis} analysis
   * @param {string} name 'recovery', 'cooper_jacob' or 'theis'
   * @returns {string}
   */
  function whyNotAdopted(analysis, name) {
    var disqualified = analysis.disqualified || {};
    if (Object.prototype.hasOwnProperty.call(disqualified, name)) {
      return disqualified[name];
    }
    var result = /** @type {Rec|null} */ (null);
    fittedMethods(analysis).forEach(function (f) { if (f[0] === name) result = f[1]; });
    var r2 = result ? result.r_squared : null;
    var minR2 = analysis.min_fit_r_squared === undefined
      ? defaultConfig().pumping.min_fit_r_squared : analysis.min_fit_r_squared;
    if (r2 !== null && r2 !== undefined && r2 < minR2) {
      return 'R squared ' + pyFixed(r2, 3) + ' is below the ' + formatG(minR2) +
        ' standard';
    }
    return '';
  }

  /* [minutes, kind]: how long the aquifer was stressed at one rate. A
   * constant test is judged on the whole pumped duration; a step test on the
   * length of a step. */
  function pumpedDurationMin(test) {
    var finiteMax = function (values) {
      var found = (values || []).filter(function (v) { return isFinite(v); });
      return found.length ? arrMax(found) : null;
    };
    if (String(test.test_type || '').indexOf('step') === 0) {
      var length = test.step_length_min;
      if (!length && test.steps && test.steps.length) {
        length = finiteMax(test.steps[0].time_min);
      }
      return [length || null, 'step'];
    }
    var duration = test.pumping_duration_min;
    if (!duration && test.steps && test.steps.length) {
      var all = [];
      test.steps.forEach(function (s) { all = all.concat(s.time_min || []); });
      duration = finiteMax(all);
    }
    return [duration || null, 'constant'];
  }

  /** options.onProgress(fraction, label), when given, is told as each stage
   * of the analysis begins, so the page can say what it is waiting for. It
   * reads nothing back, so it cannot change the analysis.
   * @param {PumpingTest} test
   * @param {Config|PumpingConfig|null} [config] the whole configuration or its pumping section
   * @param {Rec} [options] observationRadiusM, onProgress
   */
  function analysePumpingTest(test, config, options) {
    var opts = options || {};
    /* the casing and riser the sheet records, where it records them */
    var cfg = sheetConfig(test, (config && config.pumping) ? config.pumping
      : (config || defaultConfig().pumping));
    var observationRadiusM = opts.observationRadiusM;
    var progress = opts.onProgress || function () {};
    /** @type {PumpingAnalysis} */
    var analysis = {
      test: test, cooper_jacob: null, theis: null, recovery: null,
      step_test: null, yield_recommendation: null,
      stabilised_level_m: null, max_drawdown_m: null, flags: [],
      min_fit_r_squared: cfg.min_fit_r_squared,
      /* fits that ran but cannot be adopted, keyed by method, with the
       * reason: a Cooper-Jacob window inside the casing-storage period, a
       * recovery line nowhere near the origin, a Theis storativity no
       * aquifer has */
      disqualified: {},
      /* the disqualified fits whose own result is wrong - a recovery line
       * nowhere near the origin, a storativity no aquifer has - keyed by
       * method with that reason. A fit read inside the casing-storage period
       * is disqualified as well, but its line may be sound, so it can still
       * be adopted as the best of the poor fits; a wrong result never can. */
      invalid_fits: {},
      /* how long casing storage controls the drawdown in this borehole, and
       * the casing and riser diameters it was worked out from */
      casing_storage_min: null,
      casing_diameter_in: cfg.casing_diameter_in, riser_diameter_in: cfg.riser_diameter_in,
      /* the large-diameter fit, adopted only when no other fit can be, and
       * why it is invalid when its storativity is; the Bourdet derivative;
       * the bands (spread.py) */
      papadopulos_cooper: null, papadopulos_cooper_invalid: '',
      diagnostic: null, spread: null,
    };

    /* drop parse-time discharge flags the analyst has since resolved */
    var allHaveQ = (test.steps || []).every(function (s) {
      return s.discharge_m3_per_h !== null && s.discharge_m3_per_h !== undefined;
    });
    var flags = (test.flags || []).filter(function (f) {
      return !(['missing_discharge', 'discharge_ambiguous'].indexOf(f.code) >= 0 &&
        allHaveQ);
    });

    /* A zero or negative rate is a blank the crew wrote a 0 into, not a
     * measurement. Treat it as missing so the pending narrative and the
     * step-test guards below are right. */
    (test.steps || []).forEach(function (step) {
      var q = step.discharge_m3_per_h;
      if (q !== null && q !== undefined && !(Number(q) > 0 && isFinite(Number(q)))) {
        step.discharge_m3_per_h = null;
        flags.push({
          level: 'warning', code: 'invalid_discharge',
          message: 'Discharge recorded as ' + formatG(Number(q)) + ' m3/h, which ' +
            'cannot be a pumping rate; treated as not measured. Enter the ' +
            'bucket-and-stopwatch value to get transmissivity and yield.',
          context: step.label || ('step ' + step.step_number),
        });
      }
    });

    var swl = test.static_water_level_m;
    var hasSwl = swl !== null && swl !== undefined;

    var held = null;
    if (test.steps && test.steps.length && hasSwl) {
      var last = test.steps[test.steps.length - 1];
      analysis.max_drawdown_m = arrMax(last.water_level_m.filter(isFinite)) - swl;
      /* The last step is judged on its own clock, the minutes since it began
       * (analysis.py). */
      var timedSteps = test.steps.filter(function (s) {
        return (s.time_min || []).some(function (v) { return isFinite(v); });
      });
      var lastAt = timedSteps.indexOf(last), began = 0.0;
      if (lastAt > 0) {
        var lastOffsets = stepOffsetsMin(timedSteps);
        var previousStep = timedSteps[lastAt - 1];
        began = arrMax(previousStep.time_min.filter(function (v) { return isFinite(v); })) +
          lastOffsets[lastAt - 1] - lastOffsets[lastAt];
      }
      held = stabilisedTail(last.time_min.map(function (v) { return v - began; }),
        last.water_level_m, cfg);
      if (held) {
        analysis.stabilised_level_m = held[2];
        /* Theis assumes an infinite aquifer whose drawdown never stops
         * growing with log time; a level that has held still is being fed
         * by something, and projecting it to 365 days is the wrong question. */
        flags.push({
          level: 'warning', code: 'drawdown_stabilised',
          message: phrase('pumping.drawdown_stabilised', { level: held[2],
            minutes: test.steps.length > 1
              ? phrase('pumping.stabilised_minutes_step', { start: held[0], end: held[1],
                step: last.step_number })
              : phrase('pumping.stabilised_minutes', { start: held[0], end: held[1] }),
            resolution: READING_RESOLUTION_M, early: held[3] }),
        });
      }
    }

    /* Test length: the yield is projected to the design period on log time,
     * so a short test is extrapolated over several decades of time from a
     * curve that has not yet shown its late-time behaviour. Say how far. */
    var lengthInfo = pumpedDurationMin(test);
    var duration = lengthInfo[0], lengthKind = lengthInfo[1];
    var threshold = lengthKind === 'step' ? cfg.min_step_length_min
      : cfg.min_constant_test_min;
    var shortPrefix = '';
    if (duration !== null && duration > 0 && duration < threshold) {
      var cycles = Math.log(cfg.design_period_days * MIN_PER_DAY / duration) / Math.LN10;
      var what;
      if (lengthKind === 'step') {
        what = 'Each step ran for ' + formatG(duration) + ' minutes';
        shortPrefix = 'Projected from ' + formatG(duration) + '-minute steps';
      } else {
        what = 'The test pumped for ' + formatG(duration) + ' minutes';
        shortPrefix = 'Projected from a ' + formatG(duration) + '-minute test';
      }
      shortPrefix += ' (' + pyFixed(cycles, 1) + ' log cycles to ' +
        formatG(cfg.design_period_days) + ' days); treat as indicative. ';
      flags.push({
        level: 'warning', code: 'short_test',
        message: what + ', below the ' + formatG(threshold) + ' minutes needed ' +
          'to see late-time behaviour; the yield is extrapolated ' +
          pyFixed(cycles, 1) + ' log cycles of time to the ' +
          formatG(cfg.design_period_days) + '-day design period and should be ' +
          'treated as indicative.',
      });
    }

    /* Cooper-Jacob and Theis on the first step: it pumps at a single rate from
     * static conditions, so the single-well solutions apply directly (later
     * steps would need superposition of the earlier rates). */
    progress(0, 'Cooper-Jacob and Theis fits');
    if (hasSwl && test.steps && test.steps.length) {
      var step0 = test.steps[0];
      var q0 = step0.discharge_m3_per_h;
      if (q0 !== null && q0 !== undefined) {
        var t0 = [], s0 = [];
        for (var i = 0; i < step0.time_min.length; i++) {
          var tv = step0.time_min[i] <= 0 ? NaN : step0.time_min[i];
          var sv = step0.water_level_m[i] - swl;
          if (isFinite(tv) && isFinite(sv)) { t0.push(tv); s0.push(sv); }
        }
        /* A step that ends above the stated static level has no drawdown to
         * fit. It used to get a Cooper-Jacob line through negative
         * drawdowns, adopted for the yield at R squared 0.99, while the
         * step-test fit two lines below excluded the same step as a datum
         * error. */
        var sEnd0 = t0.length ? s0[s0.length - 1] : NaN;
        var label0 = step0.label || ('step ' + step0.step_number);
        var keepAny = t0.length > 0;
        if (!(sEnd0 > 0)) {
          flags.push({
            level: 'warning', code: 'first_step_above_static',
            message: label0 + ' ends at ' + (isFinite(sEnd0) ? pyFixed(sEnd0, 2) : 'nan') +
              ' m drawdown, at or above the stated static level of ' +
              pyFixed(swl, 2) + ' m, so no drawdown fit is made on it; check ' +
              'the static level and the datum for that step.',
            context: label0,
          });
          t0 = []; s0 = []; keepAny = false;
        }
        try {
          analysis.cooper_jacob = cooperJacob(t0, s0, q0, cfg,
            { observationRadiusM: observationRadiusM });
        } catch (e) {
          if (keepAny) {
            flags.push({ level: 'warning', code: 'cooper_jacob_failed', message: e.message });
          }
        }
        try {
          analysis.theis = theisFit(t0, s0, q0, {
            observationWell: observationRadiusM !== null && observationRadiusM !== undefined,
            radiusM: observationRadiusM || 0.1,
          });
        } catch (e2) {
          if (keepAny) {
            flags.push({ level: 'warning', code: 'theis_failed', message: e2.message });
          }
        }
        /* The large-diameter fit takes the same readings, the early ones
         * inside casing storage included; a pumped-well solution, so an
         * observation well is left to the others. Its refusals raise no flag
         * (analysis.py). */
        var rc = casingRadiusM(cfg);
        if ((observationRadiusM === null || observationRadiusM === undefined) &&
            rc !== null && keepAny) {
          /* from the readings, not the Theis optimum, as the Python starts */
          try {
            analysis.papadopulos_cooper = papadopulosCooperFit(t0, s0, q0, 0.1, rc);
          } catch (e3) { /* reported beside the fits; nothing to add */ }
        }
      }
    }

    /* Step clocks. A step test whose times restart each step is read with
     * each step's own last reading as its length, and the recorded duration
     * and the overview put each step on the test's clock by the same
     * reading. The reading is the toolkit's, not the sheet's, so it is
     * said. */
    var stepDurations = [], pumpedTotal = 0;
    if (String(test.test_type || '').indexOf('step') === 0) {
      var timed = (test.steps || []).filter(function (s) {
        return s.time_min && s.time_min.length;
      });
      var clocks = stepDurationsMin(timed);
      stepDurations = clocks[0];
      var restarted = clocks[1];
      pumpedTotal = stepDurations.reduce(function (a, b) { return a + b; }, 0);
      if (restarted.length) {
        var latestReading = arrMax(timed.map(function (s) { return arrMax(s.time_min); }));
        if (!isFinite(latestReading)) latestReading = 0;
        var one = restarted.length === 1;
        var names = one ? 'Step ' + restarted[0]
          : 'Steps ' + restarted.slice(0, -1).join(', ') + ' and ' +
            restarted[restarted.length - 1];
        flags.push({
          level: 'warning', code: 'step_time_restarted',
          message: names + (one ? ' opens' : ' open') + ' at or before the ' +
            'minute the step before ' + (one ? 'it' : 'each') + ' ended, so ' +
            (one ? 'its' : 'their') + ' times are read as counted from the ' +
            'start of ' + (one ? 'the' : 'each') + ' step rather than from the ' +
            "start of the test: each step's own last reading is taken as its " +
            'length, and the steps pumped for ' + formatG(pumpedTotal) +
            ' minutes in all' +
            (latestReading
              ? ', not the ' + formatG(latestReading) +
                ' minutes the latest reading gives' : '') +
            '. Check the times on the sheet.',
        });
      }
    }

    /* recovery */
    progress(0.5, 'recovery');
    if (test.recovery_level_m && hasSwl && test.recovery_time_min) {
      var residual = test.recovery_level_m.map(function (v) { return v - swl; });
      /* The recovery is read against the rate pumped when the pump stopped,
       * the last step's; it used to be the latest step with a rate, so a step
       * test with its last rate blank read its recovery against step 3's. */
      var recSteps = test.steps || [];
      var lastStep = recSteps.length ? recSteps[recSteps.length - 1] : null;
      var qRec = lastStep && lastStep.discharge_m3_per_h !== undefined
        ? lastStep.discharge_m3_per_h : null;
      if (qRec === null && lastStep && hasDischarge(test)) {
        flags.push({ level: 'warning', code: 'recovery_rate_missing',
          message: phrase('pumping.recovery_rate_missing',
            { step: 'step ' + lastStep.step_number }),
          context: lastStep.label || ('step ' + lastStep.step_number) });
      }
      var equivalentInfo = equivalentPumpingTimeMin(test);
      var tPump = equivalentInfo[0], equivalent = equivalentInfo[1];
      if (qRec !== null && tPump) {
        try {
          analysis.recovery = theisRecovery(test.recovery_time_min, residual,
            tPump, qRec, equivalent);
        } catch (e3) {
          flags.push({ level: 'warning', code: 'recovery_failed', message: e3.message });
        }
      }
      var recFit = analysis.recovery;
      if (recFit && equivalent) {
        /* the steps' own lengths added up: a sheet whose step times restart
         * has a latest reading that is one step, not the test */
        flags.push({
          level: 'info', code: 'recovery_equivalent_time',
          message: 'The recovery is read against an equivalent pumping time of ' +
            pyFixed(/** @type {number} */ (tPump), 0) + ' minutes at the last rate of ' + formatG(qRec) +
            ' m3/h (the volume pumped over all the steps at that rate), not ' +
            'the ' + formatG(pumpedTotal) + ' minutes the test ran.',
        });
      }
      if (recFit && recFit.intercept_fraction > cfg.recovery_intercept_max_fraction) {
        analysis.disqualified.recovery = "the recovery line meets t/t' = 1 at " +
          pyFixed(recFit.intercept_m, 1) + ' m of residual drawdown, ' +
          pyFixed(recFit.intercept_fraction * 100, 0) + '% of the drawdown the ' +
          'recovery started from, where the method requires zero';
        analysis.invalid_fits.recovery = analysis.disqualified.recovery;
        /* the fraction is of the magnitude the recovery started from; a line
         * meeting the axis below zero printed "37% of the -21.8 m" */
        flags.push({
          level: 'warning', code: 'recovery_intercept',
          message: 'The recovery line does not pass through the origin: it meets ' +
            "t/t' = 1 at " + pyFixed(recFit.intercept_m, 1) + ' m of residual ' +
            'drawdown (' + pyFixed(recFit.intercept_fraction * 100, 0) + '% of the ' +
            pyFixed(Math.abs(recFit.intercept_m) /
              Math.max(recFit.intercept_fraction, 1e-9), 1) +
            ' m the recovery started from), where Theis recovery requires zero. ' +
            'The residual drawdown is dominated by something the method does ' +
            'not model (casing storage, a changing static level or a wrong ' +
            'pumping time), so its transmissivity of ' +
            fmtNum(recFit.transmissivity_m2_per_day) + ' m2/day is reported ' +
            'but not adopted.',
        });
      }
    }

    /* step test */
    progress(0.6, 'step test');
    if (String(test.test_type || '').indexOf('step') === 0 && hasSwl &&
        test.steps.length >= 2) {
      var withQ = test.steps.filter(function (s) {
        return s.discharge_m3_per_h !== null && s.discharge_m3_per_h !== undefined;
      });
      if (withQ.length >= 2) {
        /* A step that ends at or above the static level has no drawdown to
         * divide by: its s/Q is zero or negative, the intercept goes negative
         * and the refit reports a borehole with no aquifer loss and 0%
         * efficiency. A first step ending 4 m above static (a datum anomaly)
         * is what the sheets actually hold. */
        var positive = [];
        withQ.forEach(function (s) {
          var sEnd = s.water_level_m[s.water_level_m.length - 1] - swl;
          var label = s.label || ('step ' + s.step_number);
          if (!(sEnd > 0)) {
            flags.push({
              level: 'warning', code: 'step_negative_drawdown',
              message: label + ' ends at ' + pyFixed(sEnd, 2) + ' m drawdown, at ' +
                'or above the static level, so it is left out of the ' +
                'Hantush-Bierschenk fit; check the static level and the datum ' +
                'for that step.',
              context: label,
            });
          } else {
            positive.push([s.discharge_m3_per_h, sEnd, s.step_number]);
          }
        });
        if (positive.length >= 2) {
          try {
            analysis.step_test = hantushBierschenk(
              positive.map(function (p) { return p[0]; }),
              positive.map(function (p) { return p[1]; }),
              positive.map(function (p) { return p[2]; }));
          } catch (e4) {
            flags.push({ level: 'warning', code: 'step_test_failed', message: e4.message });
          }
        } else {
          flags.push({
            level: 'warning', code: 'step_test_pending',
            message: 'Step test analysis pending: only ' +
              plural(positive.length, 'step') + ' with discharge show ' +
              'positive drawdown, and the fit needs at least two.',
          });
        }
      } else {
        flags.push({
          level: 'warning', code: 'step_test_pending',
          message: 'Step test analysis pending: discharge per step is missing.',
        });
      }
    }

    /* The transmissivity the yield rests on: recovery is least affected by
     * well losses, then Cooper-Jacob, then Theis - but a straight line has
     * to reach min_fit_r_squared to be adopted (Theis is a curve fit with
     * no R squared and is always eligible, which keeps it last). Taking
     * recovery unconditionally adopted a 0.52 m2/day recovery at R squared
     * 0.69 over a 4.3 m2/day Cooper-Jacob at 0.99. */
    /* Casing storage. The drawdown fits are on the first step, so the
     * specific capacity that sets the casing-storage period is that step's
     * end-of-step value. */
    var qFirst = null, sFirst = null;
    if (hasSwl && test.steps && test.steps.length) {
      var firstStep = test.steps[0];
      qFirst = firstStep.discharge_m3_per_h;
      var firstLevels = (firstStep.water_level_m || []).filter(function (v) {
        return isFinite(v);
      });
      sFirst = firstLevels.length ? firstLevels[firstLevels.length - 1] - swl : null;
      if (qFirst && sFirst && sFirst > 0) {
        analysis.casing_storage_min = casingStorageMin(qFirst / sFirst, cfg);
      }
    }
    var tC = analysis.casing_storage_min;
    /* A step test is judged on the length of a step, so its sentences are
     * worded per step: a 3 x 50-minute test used to be "the test pumped for
     * 50 minutes" and "the whole test lies inside" the casing-storage period. */
    var perStep = lengthKind === 'step';
    var inside = [];
    var casingFlag = null;
    if (tC) {
      var cjFit = analysis.cooper_jacob;
      if (cjFit && cjFit.fit_window_min[1] <= tC) {
        analysis.disqualified.cooper_jacob = 'its fitted window ' +
          formatG(cjFit.fit_window_min[0]) + '-' + formatG(cjFit.fit_window_min[1]) +
          ' minutes lies inside the ' + pyFixed(tC, 0) + '-minute casing-storage period';
        inside.push('cooper_jacob');
      } else if (cjFit && cjFit.fit_window_min[0] < tC) {
        flags.push({
          level: 'warning', code: 'casing_storage_window',
          message: 'The Cooper-Jacob window starts at ' +
            formatG(cjFit.fit_window_min[0]) + ' minutes, inside the ' +
            pyFixed(tC, 0) + '-minute casing-storage period; the early part of ' +
            'the line is the borehole emptying.',
        });
      }
      var thFit = analysis.theis;
      if (thFit && duration !== null && duration <= tC) {
        analysis.disqualified.theis = (perStep
          ? 'each ' + formatG(duration) + '-minute step lies inside'
          : 'the whole ' + formatG(duration) + '-minute test lies inside') +
          ' the ' + pyFixed(tC, 0) + '-minute casing-storage period';
        inside.push('theis');
      }
      if (inside.length) {
        /* Worded below, once the adoption is known: the flag said every fit
         * inside the period was "reported but not adopted" while the
         * transmissivity note adopted one of them as the best available. */
        casingFlag = { level: 'warning', code: 'casing_storage', message: '' };
        flags.push(casingFlag);
      }
    }
    var thCheck = analysis.theis;
    if (thCheck && thCheck.storativity > cfg.max_plausible_storativity) {
      var storativityReason = 'its storativity of ' +
        formatG(roundSig(thCheck.storativity, 2), 2) + ' is above ' +
        formatG(cfg.max_plausible_storativity) + ', which no aquifer has';
      if (!Object.prototype.hasOwnProperty.call(analysis.disqualified, 'theis')) {
        analysis.disqualified.theis = storativityReason;
      }
      analysis.invalid_fits.theis = storativityReason;
      flags.push({
        level: 'warning', code: 'storativity_implausible',
        message: 'The Theis fit returns a storativity of ' +
          formatG(roundSig(thCheck.storativity, 2), 2) + '; no aquifer stores more ' +
          'than about ' + formatG(cfg.max_plausible_storativity) + ' of its volume, ' +
          'and a value this size is the casing being emptied, not the aquifer ' +
          'draining. The fit is not adopted.',
      });
    }

    /* A Cooper-Jacob window that takes in a level that has stopped growing
     * reads the flattening as a small slope; judged where the drawdown fits
     * are, so only when the stabilised step is the first (analysis.py). */
    var cjHeld = analysis.cooper_jacob;
    if (held && cjHeld && test.steps.length === 1 && cjHeld.fit_window_min[1] >= held[0]) {
      var heldReason = phrase('pumping.cj_on_stabilised', {
        start: cjHeld.fit_window_min[0], end: cjHeld.fit_window_min[1], tail: held[0] });
      if (!Object.prototype.hasOwnProperty.call(analysis.disqualified, 'cooper_jacob')) {
        analysis.disqualified.cooper_jacob = heldReason;
      }
      analysis.invalid_fits.cooper_jacob = heldReason;
    }

    /* the large-diameter fit is held to a storativity an aquifer can have,
     * and to describing the readings no worse than the Theis curve does
     * without the casing (analysis.py) */
    var pcFit = analysis.papadopulos_cooper, thFit = analysis.theis;
    if (pcFit && pcFit.storativity > cfg.max_plausible_storativity) {
      analysis.papadopulos_cooper_invalid = 'its storativity of ' +
        formatG(roundSig(pcFit.storativity, 2), 2) + ' is above ' +
        formatG(cfg.max_plausible_storativity) + ', which no aquifer has';
    } else if (pcFit && thFit && pcFit.rmse_m > thFit.rmse_m) {
      analysis.papadopulos_cooper_invalid = 'it fits the readings no better than the ' +
        'Theis curve (RMSE ' + formatG(roundSig(pcFit.rmse_m, 3), 3) + ' m against ' +
        formatG(roundSig(thFit.rmse_m, 3), 3) + ' m), so casing storage does not ' +
        'explain them';
    }

    var adopted = adoptedFit(analysis);
    analysis.transmissivity_source = adopted.method;
    analysis.transmissivity_m2_per_day = adopted.result
      ? adopted.result.transmissivity_m2_per_day : null;
    if (casingFlag) {
      var words = { cooper_jacob: 'Cooper-Jacob', theis: 'Theis' };
      var several = inside.length > 1;
      var casingText = 'With a ' + formatG(cfg.casing_diameter_in) + ' inch casing and a ' +
        'specific capacity of ' + formatG(roundSig(qFirst / /** @type {number} */ (sFirst), 2), 2) +
        ' m3/h per m, casing storage controls the drawdown for the first ' +
        pyFixed(tC, 0) + " minutes (Schafer's rule)" +
        (duration !== null && duration <= tC
          ? (perStep ? '; each step pumped for ' : '; this test pumped for ') +
            formatG(duration) + ' minutes, entirely inside it'
          : '') +
        '. The ' + inside.map(function (k) { return words[k]; }).join(' and ') +
        ' fit' + (several ? 's see' : ' sees') +
        ' the borehole emptying rather than the aquifer';
      if (inside.indexOf(adopted.method) >= 0) {
        var others = inside.filter(function (k) { return k !== adopted.method; })
          .map(function (k) { return words[k]; });
        casingText += '. No fit outside that period can be adopted, so the ' +
          words[adopted.method] + ' value is adopted only as the best available' +
          (others.length
            ? ' and the ' + others.join(' and ') + ' value is reported but not adopted'
            : '') + '.';
      } else {
        casingText += ', so ' + (several ? 'their' : 'its') +
          ' transmissivity is reported but not adopted.';
      }
      casingFlag.message = casingText;
    }
    /* Every fit ran and every one was rejected on its own result: the yield
     * is pending, and says why, rather than resting on a rejected line. */
    var rejected = '';
    if (!adopted.result && fittedMethods(analysis).length) {
      rejected = 'no fitted transmissivity can be adopted (' +
        fittedMethods(analysis).map(function (f) {
          return METHOD_LABELS[f[0]] + ' ' + fmtNum(f[1].transmissivity_m2_per_day) +
            ' m2/day, ' + (analysis.invalid_fits[f[0]] || whyNotAdopted(analysis, f[0]));
        }).join('; ') + ')';
    }
    if (adopted.result && !adopted.qualifies) {
      var scored = fittedMethods(analysis).map(function (f) {
        return METHOD_LABELS[f[0]] + ' ' + fmtNum(f[1].transmissivity_m2_per_day) +
          ' m2/day, ' + (whyNotAdopted(analysis, f[0]) || 'usable');
      }).join('; ');
      flags.push({
        level: 'warning', code: 'transmissivity_low_confidence',
        message: 'No method fitted to standard (' + scored + '). The ' +
          METHOD_LABELS[adopted.method] + ' value of ' +
          fmtNum(adopted.result.transmissivity_m2_per_day) + ' m2/day is ' +
          'adopted as the best available, so the yield rests on a fit that ' +
          'does not meet it.',
      });
    }

    progress(0.7, 'yield');
    analysis.yield_recommendation = recommendYield(test,
      analysis.transmissivity_m2_per_day, analysis.step_test, cfg,
      { transmissivitySource: adopted.method, noTransmissivityReason: rejected });
    attachYieldEnvelope(analysis, cfg);
    /* the regime the readings show and the spread of what was adopted; the
     * central figures above are not moved by either */
    analysis.diagnostic = diagnosePumping(analysis, cfg);
    attachSpread(analysis, cfg);
    if (shortPrefix && analysis.yield_recommendation.safe_yield_m3_per_h !== null) {
      analysis.yield_recommendation.basis = shortPrefix +
        analysis.yield_recommendation.basis;
    }
    analysis.yield_range_text = yieldRangeText(analysis.yield_recommendation);

    /* What the yield is worth: one judgement, made here and printed by
     * every report beside the yield. The pumping report used to carry these
     * warnings in its data notes while the completion and handover reports
     * printed the same yield as "successful and sustainable" without them.
     * Levels the sheet itself shows cannot be right come first: a yield
     * computed from them was called established, and the readiness gate
     * certified it. */
    var recommendation = analysis.yield_recommendation;
    var reasons = [];
    if (levelsInDoubt(test)) reasons.push(LEVELS_IN_DOUBT_REASON);
    if (duration !== null && duration > 0 && duration < threshold) {
      reasons.push((perStep ? 'each step ran for ' : 'the test pumped for ') +
        formatG(duration) + ' minutes, below ' +
        'the ' + formatG(threshold) + ' needed to see late-time behaviour, so the ' +
        'yield is extrapolated ' +
        pyFixed(Math.log(cfg.design_period_days * MIN_PER_DAY / duration) / Math.LN10, 1) +
        ' log cycles of time');
    }
    if (tC && duration !== null && duration <= tC) {
      reasons.push((perStep ? 'each step lies inside' : 'the whole test lies inside') +
        ' the ' + pyFixed(tC, 0) + '-minute ' +
        'casing-storage period, so its drawdown is the borehole emptying rather ' +
        'than the aquifer responding');
    }
    if (adopted.result && !adopted.qualifies) {
      reasons.push('no transmissivity method fitted to standard and the ' +
        METHOD_LABELS[adopted.method] + ' value is adopted as the best available');
    }
    if (recommendation.safe_yield_m3_per_h !== null &&
        recommendation.safe_yield_m3_per_h !== undefined && reasons.length) {
      recommendation.confidence = 'indicative';
      recommendation.confidence_reasons = reasons;
    }
    settleConfidence(recommendation);

    analysis.flags = flags;
    return analysis;
  }

  Object.assign(C, {
    requireDischarge: requireDischarge,
    cooperJacob: cooperJacob, theisFit: theisFit, theisRecovery: theisRecovery,
    hantushBierschenk: hantushBierschenk, recommendYield: recommendYield,
    stepDrawdownAt: stepDrawdownAt, stepEfficiencyAt: stepEfficiencyAt,
    attachYieldEnvelope: attachYieldEnvelope, yieldRangeText: yieldRangeText,
    analysePumpingTest: analysePumpingTest,
    METHOD_LABELS: METHOD_LABELS, TEST_TYPE_WORDS: TEST_TYPE_WORDS,
    TWO_POINT_NOTE: TWO_POINT_NOTE,
    CASING_STORAGE_COEFFICIENT: CASING_STORAGE_COEFFICIENT,
    testTypeText: testTypeText, equivalentPumpingTimeMin: equivalentPumpingTimeMin,
    stepDurationsMin: stepDurationsMin, stepOffsetsMin: stepOffsetsMin,
    sheetConfig: sheetConfig, stabilisedTail: stabilisedTail,
    LEVEL_FLAGS: LEVEL_FLAGS,
    levelsInDoubt: levelsInDoubt, hasDischarge: hasDischarge,
    casingStorageMin: casingStorageMin, deepestPumpingLevel: deepestPumpingLevel,
    pumpIntakeDepth: pumpIntakeDepth, confidenceText: confidenceText,
    adoptedFit: adoptedFit, whyNotAdopted: whyNotAdopted,
  });


  /* ============================================================== inversion
   * groundwater/ves/inversion.py. Damped least squares (Levenberg-Marquardt)
   * on the logarithms of resistivity and thickness, misfit on log rho_a.
   * The reported error matches the IPI2Win ERR quantity.
   */

  var RHO_BOUNDS = [0.5, 200000.0];
  var H_BOUNDS = [0.2, 300.0];

  /* Why a fit's iterations stopped (inversion.py STOPS). */
  var STOPS = ['exact fit', 'no improving step', 'iteration cap'];

  /* inversion.py STATIONARY_DECREASE and _STATIONARY_RIDGE: a fit has
   * converged where the Gauss-Newton step from it, over the parameters free
   * to move within the bounds, would lower the sum of squared log residuals
   * by no more than this share of it. A choice, not a standard; the ridge on
   * the scaled unit diagonal is a numerical guard. */
  var STATIONARY_DECREASE = 1e-6;
  var STATIONARY_RIDGE = 1e-12;

  /* inversion.py UNRESOLVED_FACTOR: the largest uncertainty factor
   * reported, which reads as not resolved */
  var UNRESOLVED_FACTOR = 10.0;

  /** inversion.py most_layers: an n-layer model has 2n - 1 parameters, and
   * with as many as there are spacings it passes through every reading
   * whatever the earth, so a model keeps at least one degree of freedom.
   * @param {number} nSpacings distinct spacings
   * @returns {number}
   */
  function mostLayers(nSpacings) {
    return Math.floor(nSpacings / 2);
  }

  function tooManyLayers(n, nSpacings) {
    return phrase('ves.too_many_layers', { layers: n, parameters: 2 * n - 1,
      needed: 2 * n, spacings: nSpacings });
  }

  /* inversion.py _stationary: whether a fit stopped at theta is at a minimum
   * within the bounds. JtJ and g = J'r are from the Jacobian at theta and
   * cost is r'r there. A parameter at a bound the gradient pushes outward
   * is held; over the others the Gauss-Newton step would lower the cost by
   * g'(J'J)^-1 g, solved on normal equations scaled to a unit diagonal. */
  function stationary(theta, JtJ, g, cost, nLayers) {
    if (cost < 1e-10) return true;
    var rLo = Math.log(RHO_BOUNDS[0]), rHi = Math.log(RHO_BOUNDS[1]);
    var hLo = Math.log(H_BOUNDS[0]), hHi = Math.log(H_BOUNDS[1]);
    var free = [];
    for (var i = 0; i < theta.length; i++) {
      var lo = i < nLayers ? rLo : hLo, hi = i < nLayers ? rHi : hHi;
      var held = (theta[i] <= lo && g[i] > 0) || (theta[i] >= hi && g[i] < 0);
      if (!held) free.push(i);
    }
    if (!free.length) return true;
    var k = free.length;
    var scale = free.map(function (a) {
      var sa = Math.sqrt(JtJ[a][a]);
      return sa === 0 ? 1.0 : sa;
    });
    var A = [], b = [];
    for (var r = 0; r < k; r++) {
      var row = [];
      for (var c = 0; c < k; c++) {
        row.push(JtJ[free[r]][free[c]] / (scale[r] * scale[c]) +
          (r === c ? STATIONARY_RIDGE : 0));
      }
      A.push(row);
      b.push(g[free[r]] / scale[r]);
    }
    var step = solveLinear(A, b);
    if (!step) return false;
    var decrease = 0;
    for (var j = 0; j < k; j++) decrease += b[j] * step[j];
    return decrease <= STATIONARY_DECREASE * cost;
  }

  /**
   * @param {ArrayLike<number>} rhoObs
   * @param {ArrayLike<number>} rhoCalc
   * @returns {number}
   */
  function fitErrorPercent(rhoObs, rhoCalc) {
    var s = 0;
    for (var i = 0; i < rhoObs.length; i++) {
      var rel = (rhoCalc[i] - rhoObs[i]) / rhoObs[i];
      s += rel * rel;
    }
    return Math.sqrt(s / rhoObs.length) * 100.0;
  }

  function packTheta(rho, h) {
    var theta = new Float64Array(rho.length + h.length);
    for (var i = 0; i < rho.length; i++) theta[i] = Math.log(rho[i]);
    for (var j = 0; j < h.length; j++) theta[rho.length + j] = Math.log(h[j]);
    return theta;
  }

  function unpackTheta(theta, nLayers) {
    var rho = new Float64Array(nLayers), h = new Float64Array(theta.length - nLayers);
    for (var i = 0; i < nLayers; i++) rho[i] = Math.exp(theta[i]);
    for (var j = nLayers; j < theta.length; j++) h[j - nLayers] = Math.exp(theta[j]);
    return { rho: rho, h: h };
  }

  function clipTheta(theta, nLayers) {
    var out = new Float64Array(theta.length);
    var rLo = Math.log(RHO_BOUNDS[0]), rHi = Math.log(RHO_BOUNDS[1]);
    var hLo = Math.log(H_BOUNDS[0]), hHi = Math.log(H_BOUNDS[1]);
    for (var i = 0; i < theta.length; i++) {
      var lo = i < nLayers ? rLo : hLo, hi = i < nLayers ? rHi : hHi;
      out[i] = theta[i] < lo ? lo : (theta[i] > hi ? hi : theta[i]);
    }
    return out;
  }

  /** onIteration(done, maxIterations), when given, is told after every
   * iteration; it reads nothing back, so it cannot change the fit.
   * iterations counts the iterations run, at most maxIterations, as
   * Python's does; stopped is one of STOPS, and converged whether the
   * returned model passes the stationarity test, which the stop alone does
   * not say.
   * @param {number[]} ab2
   * @param {number[]} rhoApp
   * @param {ArrayLike<number>} rho0
   * @param {ArrayLike<number>} h0
   * @param {string} arrayType
   * @param {number} damping
   * @param {number} maxIterations
   * @param {((done: number, maxIterations: number) => void)|null} [onIteration]
   */
  function invertModel(ab2, rhoApp, rho0, h0, arrayType, damping, maxIterations,
                       onIteration) {
    var nLayers = rho0.length;
    var theta = clipTheta(packTheta(rho0, h0), nLayers);
    var logObs = rhoApp.map(Math.log);
    var m = ab2.length, p = theta.length;

    function residuals(t) {
      var u = unpackTheta(t, nLayers);
      var calc = forwardCurve(u.rho, u.h, ab2, arrayType);
      var res = new Float64Array(m);
      for (var i = 0; i < m; i++) {
        var v = calc[i] > 1e-9 ? calc[i] : 1e-9;
        calc[i] = v;
        res[i] = Math.log(v) - logObs[i];
      }
      return { res: res, calc: calc };
    }

    function costOf(res) {
      var c = 0;
      for (var i = 0; i < res.length; i++) c += res[i] * res[i];
      return c;
    }

    /* the numerical Jacobian in log space at theta, as its normal equations
     * J'J and its gradient J'r */
    function normalEquations(t, r0) {
      var J = [];
      for (var i2 = 0; i2 < m; i2++) J.push(new Float64Array(p));
      var step = 1e-4;
      for (var j = 0; j < p; j++) {
        var tp = Float64Array.from(t);
        tp[j] += step;
        var rp = residuals(tp).res;
        for (var i3 = 0; i3 < m; i3++) J[i3][j] = (rp[i3] - r0[i3]) / step;
      }
      var JtJ = [], g = new Float64Array(p);
      for (var a = 0; a < p; a++) {
        JtJ.push(new Float64Array(p));
        var ga = 0;
        for (var r = 0; r < m; r++) ga += J[r][a] * r0[r];
        g[a] = ga;
      }
      for (var a2 = 0; a2 < p; a2++) {
        for (var b2 = a2; b2 < p; b2++) {
          var s2 = 0;
          for (var r2 = 0; r2 < m; r2++) s2 += J[r2][a2] * J[r2][b2];
          JtJ[a2][b2] = s2;
          JtJ[b2][a2] = s2;
        }
      }
      return { JtJ: JtJ, g: g };
    }

    var cur = residuals(theta);
    var res = cur.res, calc = cur.calc, cost = costOf(res);
    var lam = damping, iterations = 0, stopped = 'iteration cap';
    /** @type {{JtJ: Float64Array[], g: Float64Array}|null} */
    var normal = null;

    /* counted as Python's range() counts: a fit that runs out of iterations
     * reports maxIterations, not one more, which the cache would refuse */
    for (var it = 1; it <= maxIterations; it++) {
      iterations = it;
      normal = normalEquations(theta, res);
      var JtJ = normal.JtJ, g = normal.g;

      var improved = false;
      for (var attempt = 0; attempt < 12; attempt++) {
        var A = JtJ.map(function (row, k) {
          var copy = Array.prototype.slice.call(row);
          copy[k] += lam * Math.max(JtJ[k][k], 1e-8);
          return copy;
        });
        var rhs = new Array(p);
        for (var k2 = 0; k2 < p; k2++) rhs[k2] = -g[k2];
        var delta = solveLinear(A, rhs);
        if (!delta) { lam *= 10; continue; }
        var trialTheta = new Float64Array(p);
        for (var k3 = 0; k3 < p; k3++) trialTheta[k3] = theta[k3] + delta[k3];
        trialTheta = clipTheta(trialTheta, nLayers);
        var trial = residuals(trialTheta);
        var costTrial = costOf(trial.res);
        if (costTrial < cost) {
          theta = trialTheta; res = trial.res; calc = trial.calc; cost = costTrial;
          lam = Math.max(lam / 3.0, 1e-7);
          improved = true;
          break;
        }
        lam *= 10;
        if (lam > 1e8) break;
      }
      /* theta is where the Jacobian was taken */
      if (!improved) { stopped = 'no improving step'; break; }
      if (cost < 1e-10) { stopped = 'exact fit'; break; }
      if (onIteration) onIteration(iterations, maxIterations);
    }

    /* The label, read off the returned point and nothing else, so it moves
     * no fitted number. Only after a step that improved has theta moved
     * since the last Jacobian. */
    if ((stopped === 'iteration cap' && cost >= 1e-10) || !normal) {
      normal = normalEquations(theta, res);
    }
    var converged = stopped === 'exact fit' ||
      stationary(theta, normal.JtJ, normal.g, cost, nLayers);

    var final = unpackTheta(theta, nLayers);
    var err = fitErrorPercent(rhoApp, calc);
    return {
      rho: Array.from(final.rho),
      h: Array.from(final.h),
      calc: Array.from(calc),
      err: err,
      iterations: iterations,
      converged: converged,
      stopped: stopped,
    };
  }

  /** Deterministic starting models read off the smoothed field curve.
   * Thicknesses grow logarithmically over the depth range the spacings cover
   * (depth of investigation taken as AB/2 x depth_factor); two depth-scale
   * variants bracket it.
   * @param {number[]} ab2
   * @param {number[]} rho
   * @param {number} nLayers
   */
  function startingModels(ab2, rho, nLayers) {
    var logAb2 = ab2.map(Math.log), logRho = rho.map(Math.log);
    var starts = [];
    [0.35, 0.7].forEach(function (depthFactor) {
      var zTop = Math.max(ab2[0] * depthFactor, 0.5);
      var zBot = Math.max(ab2[ab2.length - 1] * depthFactor, zTop * 4);
      /* An n-layer model has n-1 interfaces and they must span the whole
       * investigated range; spacing n points and dropping the last puts the
       * deepest starting interface far too shallow. */
      var interfaces = geomspace(zTop, zBot, Math.max(nLayers - 1, 1));
      var tops = [0.0].concat(interfaces);
      var h0 = [];
      for (var i = 1; i < tops.length; i++) {
        h0.push(Math.max(tops[i] - tops[i - 1], 0.3));
      }
      var mids = [];
      for (var j = 0; j < tops.length - 1; j++) {
        mids.push(0.5 * (tops[j] + tops[j + 1]));
      }
      mids.push(interfaces[interfaces.length - 1] * 1.5);
      var rho0 = [];
      for (var k = 0; k < nLayers; k++) {
        var z = mids[k];
        var L = Math.min(Math.max(2.0 * z, ab2[0]), ab2[ab2.length - 1]);
        rho0.push(Math.exp(interp(Math.log(L), logAb2, logRho)));
      }
      starts.push({ rho0: rho0, h0: h0 });
    });
    return starts;
  }

  /** Linearised 1-sigma multiplicative uncertainty per model parameter: the
   * covariance is sigma^2 (J'J)^-1, and because the parameters are logarithms,
   * exp(sigma_i) is the factor on each resistivity and thickness. Factors near
   * 1 are well resolved; large factors mark equivalence and suppression.
   * @param {number[]} ab2
   * @param {number[]} rhoApp
   * @param {ArrayLike<number>} rho
   * @param {ArrayLike<number>} h
   * @param {string} arrayType
   */
  function parameterUncertainty(ab2, rhoApp, rho, h, arrayType) {
    var nLayers = rho.length;
    var theta = packTheta(rho, h);
    var logObs = rhoApp.map(Math.log);
    var m = ab2.length, p = theta.length;

    function residuals(t) {
      var u = unpackTheta(t, nLayers);
      var calc = forwardCurve(u.rho, u.h, ab2, arrayType);
      var res = new Float64Array(m);
      for (var i = 0; i < m; i++) {
        res[i] = Math.log(Math.max(calc[i], 1e-9)) - logObs[i];
      }
      return res;
    }

    var res = residuals(theta);
    var J = [];
    for (var i2 = 0; i2 < m; i2++) J.push(new Float64Array(p));
    var step = 1e-4;
    for (var j = 0; j < p; j++) {
      var tp = Float64Array.from(theta);
      tp[j] += step;
      var rp = residuals(tp);
      for (var i3 = 0; i3 < m; i3++) J[i3][j] = (rp[i3] - res[i3]) / step;
    }
    /* with no more readings than parameters there is no residual variance
     * to scale by: such a model passes through the readings whatever the
     * earth, and nothing about it is resolved */
    if (m <= p) {
      var none = [];
      for (var q = 0; q < p; q++) none.push(UNRESOLVED_FACTOR);
      return { rho: none.slice(0, nLayers), h: none.slice(nLayers) };
    }
    var ss = 0;
    for (var k = 0; k < m; k++) ss += res[k] * res[k];
    var sigma2 = ss / (m - p);
    var JtJ = [];
    for (var a = 0; a < p; a++) {
      JtJ.push(new Array(p));
      for (var b = 0; b < p; b++) {
        var s = 0;
        for (var r = 0; r < m; r++) s += J[r][a] * J[r][b];
        JtJ[a][b] = s;
      }
    }
    var cov = invertMatrix(JtJ);
    if (!cov) {
      /* stand-in for numpy pinv: a light ridge makes it invertible */
      var ridge = JtJ.map(function (row, k2) {
        var copy = row.slice();
        copy[k2] += 1e-8 * Math.max(row[k2], 1);
        return copy;
      });
      cov = invertMatrix(ridge);
    }
    var factors = [];
    for (var d = 0; d < p; d++) {
      var variance = cov ? Math.max(sigma2 * cov[d][d], 0) : Infinity;
      factors.push(Math.min(Math.exp(Math.sqrt(variance)), UNRESOLVED_FACTOR));
    }
    return { rho: factors.slice(0, nLayers), h: factors.slice(nLayers) };
  }

  /** ves/inversion.py inversion_readings: the readings the inversion fits,
   * spliced where the array has segments, sorted by spacing, and only those
   * with a finite, positive spacing and apparent resistivity. The
   * interpretation reads its depth of investigation from the same readings,
   * so a last reading recorded as 0 cannot lend it a depth the model never
   * saw, and a spacing of 0 cannot reach the starting models' logarithms.
   * @param {Sounding} sounding
   * @param {Rec} [options] splice, spliceMode
   */
  function inversionReadings(sounding, options) {
    var opts = options || {};
    var arrayType = sounding.array_type || 'schlumberger';
    var spliced;
    if (opts.splice !== false && arrayType.indexOf('wenner') !== 0) {
      spliced = spliceSegments(sounding, opts.spliceMode || 'merge');
    } else {
      var order = sounding.ab2.map(function (v, k) { return k; })
        .sort(function (a, b) { return sounding.ab2[a] - sounding.ab2[b] || a - b; });
      spliced = {
        ab2: order.map(function (k) { return sounding.ab2[k]; }),
        rho: order.map(function (k) { return sounding.rho_app[k]; }),
        shifts: [1.0],
      };
    }
    var ab2 = [], rho = [];
    for (var i = 0; i < spliced.ab2.length; i++) {
      var value = spliced.rho[i], spacing = spliced.ab2[i];
      if (isFinite(value) && value > 0 && isFinite(spacing) && spacing > 0) {
        ab2.push(spacing); rho.push(value);
      }
    }
    return { ab2: ab2, rho: rho, shifts: spliced.shifts };
  }

  /** Full search: layer count from min_layers to max_layers, two starts each,
   * keeping the simplest model that reaches the target fit.
   *
   * onProgress(fraction, label) is called as each iteration and each trial
   * ends, so the page can show where the inversion has got to. It is the only
   * non-pure part of this, and it reads nothing back, so it cannot change the
   * result. The search stops adding layers once a fit is good enough, so the
   * last fraction reported can fall short of 1.
   * @param {Sounding} sounding
   * @param {Rec} [options] config, nLayers, initialModel, onProgress, splice, spliceMode
   */
  function invertSounding(sounding, options) {
    var opts = options || {};
    var cfg = (opts.config || defaultConfig()).ves;
    var arrayType = sounding.array_type || 'schlumberger';
    var spliced = inversionReadings(sounding, opts);
    var ab2 = spliced.ab2, rhoApp = spliced.rho;
    /* Spacings, not readings: a Wenner sheet is not spliced, so one read
     * twice at each of two spacings passed a count of four and had a
     * two-layer model's three parameters fitted to two points of the curve,
     * where a family of models fits equally well and each engine picked a
     * different one. */
    var spacings = ab2.filter(function (v, k) { return ab2.indexOf(v) === k; });
    if (spacings.length < 4) throw new Error('Not enough readings to invert');
    /* never more layers than the readings can determine (mostLayers); asked
     * for more, by nLayers or initialModel, it refuses */
    var most = mostLayers(spacings.length);
    var asked = opts.initialModel ? opts.initialModel.resistivities.length
      : (opts.nLayers || cfg.min_layers);
    if (asked > most) throw new Error(tooManyLayers(asked, spacings.length));

    /* the iteration hook for trial si of nStarts at layer count li of nCounts */
    function iterationProgress(li, nCounts, si, nStarts, label) {
      if (!opts.onProgress) return null;
      return function (done, maxIterations) {
        opts.onProgress((li + (si + done / maxIterations) / nStarts) / nCounts, label);
      };
    }

    var candidates = [], trials = [];

    if (opts.initialModel) {
      var seeded = invertModel(ab2, rhoApp, opts.initialModel.resistivities,
        opts.initialModel.thicknesses, arrayType, cfg.damping, cfg.max_iterations,
        iterationProgress(0, 1, 0, 1,
          opts.initialModel.resistivities.length + ' layers'));
      candidates.push(seeded);
      trials.push([seeded.rho.length, seeded.err]);
    } else {
      var layerRange = opts.nLayers
        ? [opts.nLayers]
        : (function () {
            var out = [];
            for (var n = cfg.min_layers; n <= Math.min(cfg.max_layers, most); n++) out.push(n);
            return out;
          }());
      for (var li = 0; li < layerRange.length; li++) {
        var n2 = layerRange[li];
        /** startingModels always gives two starts, so this holds a model by the
         * time it is read. @type {any} */
        var bestForN = null;
        var starts = startingModels(ab2, rhoApp, n2);
        for (var si = 0; si < starts.length; si++) {
          var result = invertModel(ab2, rhoApp, starts[si].rho0, starts[si].h0,
            arrayType, cfg.damping, cfg.max_iterations,
            iterationProgress(li, layerRange.length, si, starts.length, n2 + ' layers'));
          if (!bestForN || result.err < bestForN.err) bestForN = result;
          if (opts.onProgress) {
            opts.onProgress((li + (si + 1) / starts.length) / layerRange.length,
              n2 + ' layers');
          }
        }
        candidates.push(bestForN);
        trials.push([n2, bestForN.err]);
        if (!opts.nLayers) {
          /* Stop adding layers once the target is comfortably reached, or when
           * the extra layer no longer helps materially - but the
           * diminishing-returns test only applies once an adequate fit is in
           * hand, so a small gain cannot abandon the search while the fit is
           * still far above target. */
          /* "comfortably" means the noise floor the accept rule uses (a tenth
           * of the target), not half of it: at half, a 4.7% two-layer fit
           * ended the search before the three-layer model that fitted a 15 m
           * aquifer over basement exactly was ever tried */
          if (bestForN.err <= cfg.target_fit_percent / 10.0) break;
          if (trials.length >= 2 &&
              trials[trials.length - 1][1] > 0.9 * trials[trials.length - 2][1] &&
              bestForN.err <= cfg.target_fit_percent) break;
        }
      }
    }

    /* Parsimony. Reaching the target is not enough on its own: a two-layer
     * model can sit just under it while a three-layer one fits the same curve
     * an order of magnitude better and puts basement at 65 m instead of 4 m -
     * the difference between drilling into the aquifer and stopping in the
     * regolith. A simple model is accepted only while no available model more
     * than halves its misfit. */
    var bestErr = Math.min.apply(null, candidates.map(function (c) { return c.err; }));
    var chosen = null, ci;
    for (ci = 0; ci < candidates.length; ci++) {
      var cand = candidates[ci];
      if (cand.err <= cfg.target_fit_percent &&
          (cand.err <= cfg.parsimony_max_error_ratio * Math.max(bestErr, 1e-9) ||
           cand.err <= cfg.target_fit_percent / 10.0)) {
        chosen = cand; break;
      }
    }
    if (!chosen) {
      for (ci = 0; ci < candidates.length; ci++) {
        if (candidates[ci].err <= cfg.parsimony_fallback_ratio * bestErr) {
          chosen = candidates[ci]; break;
        }
      }
    }
    if (!chosen) {
      chosen = candidates.reduce(function (a, b) { return a.err <= b.err ? a : b; });
    }

    return inversionResult(sounding, spliced, chosen, trials);
  }

  /* The result of a search, from the candidate it chose. Shared by
   * invertSounding and restoreInversion, so a result rebuilt from a saved
   * model is put together by the same code as the one the search returned. */
  function inversionResult(sounding, spliced, chosen, trials) {
    var arrayType = sounding.array_type || 'schlumberger';
    var ab2 = spliced.ab2, rhoApp = spliced.rho;
    var uncertainty = parameterUncertainty(ab2, rhoApp, chosen.rho, chosen.h, arrayType);
    return {
      model: layeredModel(chosen.rho, chosen.h, {
        fit_error_percent: chosen.err,
        method: 'damped-lsq',
        sounding_id: sounding.sounding_id || '',
        /* travels with the model so the interpretation can say a boundary
         * is poorly resolved instead of reading the layer count as settled */
        h_uncertainty_factor: uncertainty.h,
      }),
      ab2: ab2,
      /* which array the spacings are: a Wenner sounding's column is the
       * spacing a, and labelling it AB/2 is a wrong label on a figure and
       * in a table a client reads */
      array_type: arrayType,
      rho_obs: rhoApp,
      rho_calc: chosen.calc,
      fit_error_percent: chosen.err,
      n_iterations: chosen.iterations,
      converged: chosen.converged,
      stopped: chosen.stopped,
      trials: trials,
      shifts: spliced.shifts,
      rho_uncertainty_factor: uncertainty.rho,
      h_uncertainty_factor: uncertainty.h,
    };
  }

  /** ves/inversion.py restore_inversion: what invertSounding returned, rebuilt
   * from the model it chose. Only what the search alone can say is taken as
   * given - the model, its iteration count, whether it converged, why it
   * stopped and the layer counts tried. The readings fitted, the model's
   * response, the misfit and the uncertainty factors are worked out again
   * from the sounding, the same way the search does it, so they come out to
   * the last bit.
   * @param {Sounding} sounding
   * @param {Rec} stored an inversion cache record
   */
  function restoreInversion(sounding, stored) {
    var arrayType = sounding.array_type || 'schlumberger';
    var spliced = inversionReadings(sounding);
    var rho = stored.resistivities.slice(), h = stored.thicknesses.slice();
    var calc = forwardCurve(rho, h, spliced.ab2, arrayType);
    var clamped = [];
    for (var i = 0; i < calc.length; i++) clamped.push(calc[i] > 1e-9 ? calc[i] : 1e-9);
    var chosen = { rho: rho, h: h, calc: clamped, err: fitErrorPercent(spliced.rho, clamped),
      iterations: stored.n_iterations, converged: stored.converged,
      stopped: stored.stopped };
    var trials = stored.trials.map(function (t) { return [t[0], t[1]]; });
    return inversionResult(sounding, spliced, chosen, trials);
  }

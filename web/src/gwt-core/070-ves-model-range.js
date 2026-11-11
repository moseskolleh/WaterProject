
  /* ====================================================== range of models
   * ves/model_range.py (PLAN.md step 3.1). One Levenberg-Marquardt fit is one
   * member of a family of models that fit about equally well. The best fit is
   * kept as it is, and this samples the family beside it: Latin hypercube
   * starting models polished by invertModel, an error on every reading (a
   * base percentage plus half the log ratio at each MN overlap, widened to
   * the best model's misfit where that is larger), and a random-walk
   * Metropolis-Hastings sampler over the log-parameters started from the best
   * fits. What each kept model says is read by the interpretation's rules,
   * and P10, P50 and P90 of it are the range.
   *
   * Every random number comes from one 32-bit generator, xoshiro128** seeded
   * by splitmix32, written word for word as the Python one is, and the step
   * is a sum of four uniforms rather than a Gaussian: a Gaussian needs a
   * logarithm, and Math.log and the C library's log differ in the last bit
   * for about one value in fifteen. So both engines draw the same starting
   * models and the same steps, and parity.mjs compares them. */

  var GOLDEN = 0x9E3779B9;
  var SQRT3 = Math.sqrt(3.0);

  function rotl32(x, k) {
    return ((x << k) | (x >>> (32 - k))) >>> 0;
  }

  /** xoshiro128** seeded by splitmix32; stream 0 is the Latin hypercube's and
   * stream c + 1 chain c's, so no part's numbers depend on another's draws.
   * @param {number} seed
   * @param {number} stream
   */
  function rangeStream(seed, stream) {
    var x = (Math.imul(seed >>> 0, GOLDEN) + stream) >>> 0;
    var s = [];
    for (var i = 0; i < 4; i++) {
      x = (x + GOLDEN) >>> 0;
      var z = x;
      z = Math.imul(z ^ (z >>> 16), 0x85EBCA6B) >>> 0;
      z = Math.imul(z ^ (z >>> 13), 0xC2B2AE35) >>> 0;
      s.push((z ^ (z >>> 16)) >>> 0);
    }
    if (!(s[0] || s[1] || s[2] || s[3])) s[0] = 1;  /* the one state xoshiro cannot leave */
    function next() {
      var result = Math.imul(rotl32(Math.imul(s[1], 5) >>> 0, 7), 9) >>> 0;
      var t = (s[1] << 9) >>> 0;
      s[2] = (s[2] ^ s[0]) >>> 0;
      s[3] = (s[3] ^ s[1]) >>> 0;
      s[1] = (s[1] ^ s[2]) >>> 0;
      s[0] = (s[0] ^ s[3]) >>> 0;
      s[2] = (s[2] ^ t) >>> 0;
      s[3] = rotl32(s[3], 11);
      return result;
    }
    function uniform() { return (next() + 0.5) / 4294967296.0; }
    return {
      next: next,
      uniform: uniform,
      /* a whole number from 0 to n - 1: the product is exact below 2^53 */
      below: function (n) { return Math.floor(next() * n / 4294967296); },
      /* Irwin-Hall: zero mean, unit variance, no logarithm */
      symmetric: function () {
        var total = uniform() + uniform();
        total += uniform();
        total += uniform();
        return (total - 2.0) * SQRT3;
      },
    };
  }

  /** n points in the box lo-hi, one in each of n equal slices of every axis.
   * @param {{below: function(number): number, uniform: function(): number}} rng
   * @param {number} nPoints
   * @param {number[]} lo
   * @param {number[]} hi
   * @returns {number[][]}
   */
  function latinHypercube(rng, nPoints, lo, hi) {
    var p = lo.length, points = [], j, k;
    for (k = 0; k < nPoints; k++) points.push(new Array(p).fill(0));
    for (j = 0; j < p; j++) {
      var perm = [];
      for (k = 0; k < nPoints; k++) perm.push(k);
      for (var i = nPoints - 1; i > 0; i--) {
        var pick = rng.below(i + 1);
        var swap = perm[i]; perm[i] = perm[pick]; perm[pick] = swap;
      }
      for (k = 0; k < nPoints; k++) {
        var u = (perm[k] + rng.uniform()) / nPoints;
        points[k][j] = lo[j] + (hi[j] - lo[j]) * u;
      }
    }
    return points;
  }

  /** Linear interpolation between order statistics, as model_range.percentile.
   * @param {number[]} sorted
   * @param {number} q
   * @returns {number}
   */
  function rangePercentile(sorted, q) {
    var pos = q * (sorted.length - 1);
    var lo = Math.floor(pos);
    if (lo + 1 >= sorted.length) return sorted[sorted.length - 1];
    var frac = pos - lo;
    return sorted[lo] + (sorted[lo + 1] - sorted[lo]) * frac;
  }

  function rangeBand(values) {
    if (!values.length) return null;
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    return { p10: rangePercentile(sorted, 0.1), p50: rangePercentile(sorted, 0.5),
      p90: rangePercentile(sorted, 0.9) };
  }

  /** The error of each fitted reading as a log standard deviation: the base
   * percentage, plus half the log ratio at an MN overlap, added in
   * quadrature as two independent errors are. A Wenner sheet has
   * no MN to change, and a spacing it reads twice is two readings the fit
   * sees apart, so only a Schlumberger overlap adds to the error. The splice
   * also leaves as two readings a spacing read twice on a Schlumberger sheet
   * with no MN change recorded, so a spacing ab2 holds more than once was not
   * merged and its error is the base alone.
   * @param {Sounding} sounding
   * @param {number[]} ab2
   * @param {number} basePercent
   * @returns {{sigma: number[], spacings: number[]}}
   */
  function readingErrors(sounding, ab2, basePercent) {
    var base = basePercent / 100.0;
    var at = {};
    if (String(sounding.array_type || '').indexOf('wenner') !== 0) {
      overlapRatios(sounding.ab2, sounding.rho_app).forEach(function (o) { at[o[0]] = o[1]; });
    }
    /** @type {Record<string, number>} */
    var count = {};
    ab2.forEach(function (value) { count[value] = (count[value] || 0) + 1; });
    var sigma = [], spacings = [];
    ab2.forEach(function (value) {
      if (count[value] > 1 || !Object.prototype.hasOwnProperty.call(at, value)) {
        sigma.push(base);
        return;
      }
      var d = 0.5 * Math.log(at[value]);
      sigma.push(Math.sqrt(base * base + d * d));
      spacings.push(value);
    });
    return { sigma: sigma, spacings: spacings };
  }

  /* What one model says, by interpretModel's rules, unrounded:
   * [basement or null, weathered, deepest, interfaces, rho]. */
  function rangeSummary(theta, n, investigation, ves) {
    var rho = [], tops = [0.0], i;
    for (i = 0; i < n; i++) rho.push(Math.exp(theta[i]));
    for (i = n; i < theta.length; i++) tops.push(tops[tops.length - 1] + Math.exp(theta[i]));
    var weathered = 0.0, deepest = null;
    for (i = 0; i < n; i++) {
      var top = tops[i], bottom = i + 1 < n ? tops[i + 1] : Infinity;
      if (unitLabel(rho[i], i === 0, i === n - 1, ves)[1]) {
        var zTop = Math.max(top, VADOSE_M);  /* the top few metres are vadose */
        if (zTop < investigation) {
          var zBottom = Math.min(bottom, investigation);
          if (zBottom - zTop >= 1.0) {
            weathered += zBottom - zTop;
            deepest = zBottom;
          }
        }
      }
    }
    /* resistive ground with nothing conductive below it, by the
     * interpretation's own rule: a layer as resistive as basement over
     * conductive ground is a cover, not a basement found in every model */
    var basement = basementTop(rho, tops, ves);
    if (basement !== null && basement > investigation) basement = null;
    deepest = deepest === null ? investigation : deepest + ves.max_drilling_margin_m;
    return [basement, weathered, deepest, tops.slice(1), rho];
  }

  function rangeChi2(calc, logObs, sigma) {
    var s = 0;
    for (var i = 0; i < calc.length; i++) {
      var r = (Math.log(Math.max(calc[i], 1e-9)) - logObs[i]) / sigma[i];
      s += r * r;
    }
    return s;
  }

  /* M with M M' = H^-1: the inverse of the transpose of H's Cholesky factor,
   * in the loops model_range._cholesky_inverse_t runs. */
  function choleskyInverseT(H) {
    var p = H.length, L = [], M = [], i, j, k, s;
    for (i = 0; i < p; i++) { L.push(new Array(p).fill(0)); M.push(new Array(p).fill(0)); }
    for (j = 0; j < p; j++) {
      s = H[j][j];
      for (k = 0; k < j; k++) s -= L[j][k] * L[j][k];
      L[j][j] = Math.sqrt(Math.max(s, 1e-300));
      for (i = j + 1; i < p; i++) {
        s = H[i][j];
        for (k = 0; k < j; k++) s -= L[i][k] * L[j][k];
        L[i][j] = s / L[j][j];
      }
    }
    for (var c = 0; c < p; c++) {
      for (i = p - 1; i >= 0; i--) {
        s = i === c ? 1.0 : 0.0;
        for (k = i + 1; k < p; k++) s -= L[k][i] * M[k][c];
        M[i][c] = s / L[i][i];
      }
    }
    return M;
  }

  var RANGE_WINDOW = 50;  /* burn-in steps between two adjustments of the step */
  /* the drilling depth is kept at this many equal steps of probability, for
   * the cost distribution to draw from (model_range.DEPTH_QUANTILES) */
  var DEPTH_QUANTILES = 20;
  var RANGE_JACOBIAN_STEP = 1e-4;  /* inversion.py JACOBIAN_STEP, the inversion's own */

  /** The range of models that fit a sounding about as well as its inversion.
   * onProgress(fraction, label), when given, is told how far the work has
   * got; it reads nothing back.
   * @param {Sounding} sounding
   * @param {Rec} inversion what invertSounding returned for it
   * @param {Config} [config]
   * @param {((fraction: number, label: string) => void)|null} [onProgress]
   * @returns {Rec}
   */
  function sampleModelRange(sounding, inversion, config, onProgress) {
    var full = config || defaultConfig();
    var ves = full.ves, opts = full.ves_range;
    var arrayType = sounding.array_type || 'schlumberger';
    var readings = inversionReadings(sounding);
    var ab2 = readings.ab2, rhoApp = readings.rho;
    var logObs = rhoApp.map(Math.log);
    var n = inversion.model.n_layers, p = 2 * n - 1, m = ab2.length, i, j, k;
    var investigation = depthOfInvestigation(arrMax(ab2), ves);
    var errors = readingErrors(sounding, ab2, opts.base_error_percent);
    var sigma = errors.sigma;

    var nStarts = Math.max(Math.trunc(opts.starts), 0);
    var nChains = Math.max(Math.trunc(opts.chains), 1);
    var nSamples = Math.max(Math.trunc(opts.samples), nChains);
    var burnIn = Math.max(Math.trunc(opts.burn_in), 0);
    var lmWeight = 250;  /* about the forward calls one polish takes */
    var totalWork = nStarts * lmWeight + nChains * burnIn + nSamples;
    var done = 0;
    function progress(label) {
      if (onProgress) onProgress(Math.min(done / totalWork, 1.0), label);
    }

    /* the hard bounds (the inversion's) and the hypercube's box */
    var hardLo = [], hardHi = [], boxLo = [], boxHi = [];
    var rhoLo = Math.log(Math.max(RHO_BOUNDS[0], arrMin(rhoApp) / 10.0));
    var rhoHi = Math.log(Math.min(RHO_BOUNDS[1], arrMax(rhoApp) * 10.0));
    /* the depth scales the inversion's own two starting models use */
    var hLo = Math.log(Math.max(H_BOUNDS[0], 0.35 * ab2[0]));
    var hHi = Math.log(Math.min(H_BOUNDS[1], 0.7 * ab2[m - 1]));
    for (j = 0; j < p; j++) {
      var isRho = j < n;
      hardLo.push(Math.log(isRho ? RHO_BOUNDS[0] : H_BOUNDS[0]));
      hardHi.push(Math.log(isRho ? RHO_BOUNDS[1] : H_BOUNDS[1]));
      boxLo.push(isRho ? rhoLo : hLo);
      boxHi.push(isRho ? rhoHi : hHi);
    }

    /* the candidates: the inversion's model and the polished starts */
    var chosen = inversion.model;
    var candidates = [{ theta: Array.from(packTheta(chosen.resistivities, chosen.thicknesses)),
      calc: Array.from(inversion.rho_calc) }];
    var startPoints = latinHypercube(rangeStream(opts.seed, 0), nStarts, boxLo, boxHi);
    var startErrors = [];
    startPoints.forEach(function (point, s) {
      progress('starting model ' + (s + 1) + ' of ' + nStarts);
      var fit = invertModel(ab2, rhoApp, point.slice(0, n).map(Math.exp),
        point.slice(n).map(Math.exp), arrayType, ves.damping, ves.max_iterations);
      candidates.push({ theta: Array.from(packTheta(fit.rho, fit.h)), calc: fit.calc });
      startErrors.push(fit.err);
      done += lmWeight;
    });

    var chi2 = candidates.map(function (c) { return rangeChi2(c.calc, logObs, sigma); });
    /* ranked on the misfit to six figures, the earlier first on a tie: two
     * starts that polish to one minimum differ only in the last digits, and
     * differently in each engine, and the inversion's own model wins */
    var rank = chi2.map(function (c) { return Number(c.toPrecision(6)); });
    var best = 0;
    for (k = 1; k < chi2.length; k++) if (rank[k] < rank[best]) best = k;
    var dof = Math.max(m - p, 1);
    var widen = chi2[best] / dof;
    var scale = widen > 1.0 ? Math.sqrt(widen) : 1.0;
    var sigmaEff = sigma.map(function (v) { return v * scale; });
    var chi2Scaled = chi2.map(function (c) { return c / (scale * scale); });

    /* chains start from the best fits a sample of the posterior could
     * plausibly be: within p + 3 sqrt(2p) of the best in chi-squared */
    var limit = chi2Scaled[best] + p + 3.0 * Math.sqrt(2.0 * p);
    var order = chi2Scaled.map(function (v, idx) { return idx; })
      .sort(function (a, b) { return rank[a] - rank[b] || a - b; });
    var distinct = [];
    for (k = 0; k < order.length; k++) {
      var idx = order[k];
      if (chi2Scaled[idx] > limit) break;
      var fresh = distinct.every(function (other) {
        var far = 0;
        for (var q = 0; q < p; q++) {
          far = Math.max(far, Math.abs(candidates[idx].theta[q] - candidates[other].theta[q]));
        }
        return far >= 0.01;
      });
      if (fresh) distinct.push(idx);
    }

    /* the step, shaped by the linearised covariance at the best fit */
    var thetaBest = candidates[best].theta;
    var resBest = candidates[best].calc.map(function (v, r) {
      return Math.log(Math.max(v, 1e-9)) - logObs[r];
    });
    var J = [];
    for (i = 0; i < m; i++) J.push(new Array(p).fill(0));
    for (j = 0; j < p; j++) {
      var tp = thetaBest.slice();
      tp[j] += RANGE_JACOBIAN_STEP;
      var u0 = unpackTheta(tp, n);
      var calcP = forwardCurve(u0.rho, u0.h, ab2, arrayType);
      for (i = 0; i < m; i++) {
        J[i][j] = (Math.log(Math.max(calcP[i], 1e-9)) - logObs[i] - resBest[i]) / RANGE_JACOBIAN_STEP;
      }
    }
    var H = [];
    for (var a = 0; a < p; a++) {
      H.push(new Array(p).fill(0));
      for (var b = 0; b < p; b++) {
        var sum = 0.0;
        for (i = 0; i < m; i++) sum += (J[i][a] / sigmaEff[i]) * (J[i][b] / sigmaEff[i]);
        H[a][b] = sum;
      }
      /* the flat prior's own spread: a direction the data do not constrain
       * does not ask for an infinite step */
      var width = hardHi[a] - hardLo[a];
      H[a][a] += 12.0 / (width * width);
    }
    var M = choleskyInverseT(H);

    function evaluate(theta) {
      var u = unpackTheta(theta, n);
      var calc = forwardCurve(u.rho, u.h, ab2, arrayType);
      var s = 0;
      for (var r = 0; r < m; r++) {
        calc[r] = Math.max(calc[r], 1e-9);
        var e = (Math.log(calc[r]) - logObs[r]) / sigmaEff[r];
        s += e * e;
      }
      return { calc: Array.from(calc), ll: -0.5 * s };
    }

    /* the chains */
    var kept = [], accepted = [];
    for (var c = 0; c < nChains; c++) {
      var rng = rangeStream(opts.seed, c + 1);
      var theta = candidates[distinct[c % distinct.length]].theta.slice();
      var state = evaluate(theta);
      var summary = rangeSummary(theta, n, investigation, ves);
      var step = 2.38 / Math.sqrt(p);
      var keep = Math.floor(nSamples / nChains) + (c < nSamples % nChains ? 1 : 0);
      var windowHits = 0, hits = 0;
      for (k = 0; k < burnIn + keep; k++) {
        var z = [];
        for (j = 0; j < p; j++) z.push(rng.symmetric());
        var u = rng.uniform();
        var proposal = [], inside = true;
        for (j = 0; j < p; j++) {
          var s = 0.0;
          for (var q2 = j; q2 < p; q2++) s += M[j][q2] * z[q2];
          var v = theta[j] + step * s;
          if (v < hardLo[j] || v > hardHi[j]) inside = false;
          proposal.push(v);
        }
        var moved = false;
        if (inside) {
          var trial = evaluate(proposal);
          var d = trial.ll - state.ll;
          if (d >= 0.0 || u < Math.exp(d)) {
            theta = proposal; state = trial;
            summary = rangeSummary(theta, n, investigation, ves);
            moved = true;
          }
        }
        if (k < burnIn) {
          if (moved) windowHits += 1;
          if ((k + 1) % RANGE_WINDOW === 0) {
            var rate = windowHits / RANGE_WINDOW;
            if (rate < 0.15) step *= 0.7;
            else if (rate > 0.35) step *= 1.4;
            windowHits = 0;
          }
        } else {
          if (moved) hits += 1;
          kept.push([theta, state.calc, summary]);
        }
        done += 1;
        if (done % 200 === 0) progress('chain ' + (c + 1) + ' of ' + nChains);
      }
      accepted.push(hits);
    }

    /* what the kept models say */
    var total = kept.length;
    var basements = [], deepest = [], weathered = [];
    kept.forEach(function (row) {
      if (row[2][0] !== null) basements.push(row[2][0]);
      weathered.push(row[2][1]);
      deepest.push(row[2][2]);
    });
    deepest.sort(function (x, y) { return x - y; });
    var p90 = rangePercentile(deepest, 0.9);
    var stepM = ves.round_drilling_depth_to_m;
    var drill = Math.min(Math.ceil(Math.min(p90, investigation) / stepM) * stepM, investigation);
    var reach = deepest.map(function (d) { return Math.min(d, investigation); });
    var depthQuantiles = [];
    for (k = 0; k <= DEPTH_QUANTILES; k++) {
      depthQuantiles.push(rangePercentile(reach, k / DEPTH_QUANTILES));
    }
    var fanCount = Math.min(Math.max(Math.trunc(opts.fan_models), 0), total);
    var fanAt = [];
    for (k = 0; k < fanCount; k++) fanAt.push(Math.floor(k * total / fanCount));
    var resistivity = [], interfaces = [];
    for (i = 0; i < n; i++) {
      resistivity.push(rangeBand(kept.map(function (row) { return row[2][4][i]; })));
    }
    for (i = 0; i < n - 1; i++) {
      interfaces.push(rangeBand(kept.map(function (row) { return row[2][3][i]; })));
    }
    var bestErr = Infinity;
    candidates.forEach(function (cand) {
      bestErr = Math.min(bestErr, fitErrorPercent(rhoApp, cand.calc));
    });
    progress('done');
    return {
      sounding_id: sounding.sounding_id || '',
      n_layers: n,
      n_samples: total,
      chains: nChains,
      starts: nStarts,
      seed: opts.seed,
      base_error_percent: opts.base_error_percent,
      overlap_spacings: errors.spacings,
      error_scale: scale,
      acceptance: accepted.reduce(function (x, y) { return x + y; }, 0) / total,
      accepted: accepted,
      investigation_depth_m: investigation,
      basement_m: rangeBand(basements),
      basement_unresolved: 1.0 - basements.length / total,
      weathered_m: rangeBand(weathered),
      resistivity: resistivity,
      interface_m: interfaces,
      drilling_depth_m: drill,
      drilling_depth_capped: p90 > investigation,
      chosen_error_percent: inversion.fit_error_percent,
      best_error_percent: bestErr,
      ab2: ab2.slice(),
      fan: fanAt.map(function (at) {
        var u = unpackTheta(kept[at][0], n);
        return [Array.from(u.rho), Array.from(u.h)];
      }),
      fan_curves: fanAt.map(function (at) { return kept[at][1].slice(); }),
      start_points: startPoints,
      start_errors: startErrors,
      drilling_depth_quantiles_m: depthQuantiles,
    };
  }

  /* A depth range for basement is quoted only when at least this share of
   * the models that fit find one (model_range.MIN_RESOLVED_SHARE). */
  var MIN_RESOLVED_SHARE = 0.1;

  /* Whether the sentences and the table quote a depth range for basement
   * (model_range.quoted_basement_band). Compared on the unresolved share,
   * as stored: 400 of 4,000 is exactly a tenth, but 1 - (1 - 0.1) is a last
   * bit under 0.1, and the band was dropped at the very share the rule says
   * to quote it. */
  function quotesBasementBand(r) {
    return r.basement_m !== null && r.basement_unresolved <= 1.0 - MIN_RESOLVED_SHARE;
  }

  /* A share as a whole percentage, never "0" or "100" for one that is not. */
  function rangeShare(fraction) {
    var percent = 100.0 * fraction;
    if (percent > 0.0 && percent < 0.5) return 'under 1';
    if (percent >= 99.5 && percent < 100.0) return 'over 99';
    return pyFixed(percent, 0);
  }

  /** model_range.model_range_text: the range in sentences - basement, the
   * weathered zone, the drilling depth, any better fit the wider search
   * found, and the basis.
   * @param {Rec} r what sampleModelRange returned
   * @returns {string[]}
   */
  function modelRangeText(r) {
    var doi = r.investigation_depth_m, out = [];
    if (!quotesBasementBand(r)) {
      out.push(phrase('ves_range.basement_unresolved',
        { share: rangeShare(r.basement_unresolved), doi: doi }));
    } else if (r.basement_unresolved === 0.0) {
      out.push(phrase('ves_range.basement_always',
        { p10: r.basement_m.p10, p90: r.basement_m.p90 }));
    } else {
      out.push(phrase('ves_range.basement', { p10: r.basement_m.p10, p90: r.basement_m.p90,
        share: rangeShare(r.basement_unresolved) }));
    }
    if (r.weathered_m.p90 < 0.5) {
      out.push(phrase('ves_range.weathered_none'));
    } else {
      out.push(phrase('ves_range.weathered',
        { p10: r.weathered_m.p10, p90: r.weathered_m.p90, doi: doi }));
    }
    if (r.drilling_depth_capped) {
      out.push(phrase('ves_range.drilling_capped', { depth: r.drilling_depth_m, doi: doi }));
    } else {
      out.push(phrase('ves_range.drilling', { depth: r.drilling_depth_m }));
    }
    /* a better fit is worth a sentence only when it is better by more than
     * the search's own noise: a tenth of the misfit */
    if (r.best_error_percent < 0.9 * r.chosen_error_percent) {
      out.push(phrase('ves_range.better_fit', { layers: r.n_layers,
        err: r.best_error_percent, chosen: r.chosen_error_percent }));
    }
    var overlap = r.overlap_spacings.length
      ? phrase('ves_range.basis_overlap', { count: r.overlap_spacings.length,
        spacings: andJoin(r.overlap_spacings.map(function (v) { return fmtNum(v); })) })
      : '';
    var widened = r.error_scale > 1.0
      ? phrase('ves_range.basis_widened', { factor: r.error_scale }) : '';
    out.push(phrase('ves_range.basis', { samples: r.n_samples, layers: r.n_layers,
      chains: r.chains, fits: r.starts + 1, starts: r.starts, base: r.base_error_percent,
      overlap: overlap, widened: widened }));
    return out;
  }

  /** The sentence a figure with the fan adds to its caption.
   * @param {Rec} r what sampleModelRange returned
   * @returns {string}
   */
  function modelRangeCaption(r) {
    return phrase('ves_range.caption', { count: r.fan.length });
  }

  /** model_range.drilling_depth_band: P10 and P90 of the depth each kept
   * model would be drilled to, unrounded, as the figures shade it (PLAN.md
   * step 3.6); null for a range that kept no such depths.
   * @param {Rec|null} r what sampleModelRange returned
   * @returns {number[]|null} */
  function drillingDepthBand(r) {
    var q = r ? r.drilling_depth_quantiles_m : null;
    if (!q || !q.length) return null;
    var last = q.length - 1;
    return [q[Math.floor(last / 10)], q[last - Math.floor(last / 10)]];
  }

  /** model_range.drilling_band_caption.
   * @returns {string} */
  function drillingBandCaption() {
    return phrase('decision.figure_depth_band');
  }

  /** model_range.model_range_rows: a label, then P10, P50 and P90, for depth
   * to basement (where the sentences quote a band for it), the weathered
   * zone, each layer's resistivity and the base of each layer.
   * @param {Rec} r what sampleModelRange returned
   * @returns {string[][]}
   */
  function modelRangeRows(r) {
    function row(label, band) {
      return [label, fmtNum(band.p10), fmtNum(band.p50), fmtNum(band.p90)];
    }
    var out = [];
    if (quotesBasementBand(r)) {
      out.push(row(phrase('ves_range.row_basement'), r.basement_m));
    }
    out.push(row(phrase('ves_range.row_weathered'), r.weathered_m));
    r.resistivity.forEach(function (band, i) {
      out.push(row(phrase('ves_range.row_resistivity', { layer: i + 1 }), band));
    });
    r.interface_m.forEach(function (band, i) {
      out.push(row(phrase('ves_range.row_interface', { layer: i + 1 }), band));
    });
    return out;
  }

  /** @param {Rec} r what sampleModelRange returned
   * @returns {string}
   */
  function modelRangeTableCaption(r) {
    return phrase('ves_range.table_caption', { sid: r.sounding_id });
  }

  Object.assign(C, {
    rangeStream: rangeStream, latinHypercube: latinHypercube,
    rangePercentile: rangePercentile, readingErrors: readingErrors,
    sampleModelRange: sampleModelRange, modelRangeText: modelRangeText,
    modelRangeCaption: modelRangeCaption, modelRangeRows: modelRangeRows,
    drillingDepthBand: drillingDepthBand, drillingBandCaption: drillingBandCaption,
    modelRangeTableCaption: modelRangeTableCaption,
  });

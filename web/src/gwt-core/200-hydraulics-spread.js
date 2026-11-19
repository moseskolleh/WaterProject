
  /* ======================================================= pumping spread
   * hydraulics/spread.py (PLAN.md step 3.2), rule for rule: how far the
   * pumping test results can be trusted. A moving-block bootstrap of the
   * adopted fit's residuals, drawn from mulberry32 so both engines resample
   * the same readings; the Theis fit's covariance; the Bourdet derivative and
   * the flow regime it shows; and the Papadopulos-Cooper large-diameter well,
   * inverted from the Laplace domain by Stehfest's method. The module
   * docstring in spread.py gives the methods and their sources. */

  /* spread.py Z_P90: the standard normal quantile at 0.9 */
  var Z_P90 = 1.2815515655446004;
  var BAND_QUANTILES = [0.1, 0.5, 0.9];
  var STEHFEST_TERMS = 12;
  var LM_MAX_ITERATIONS = 200;
  var LM_RELATIVE_TOLERANCE = 1e-12;
  /* spread.py POLISH_MAX_STEPS and POLISH_MISFIT_SLACK */
  var POLISH_MAX_STEPS = 12;
  var POLISH_MISFIT_SLACK = 1e-9;
  var BOOTSTRAP_MIN_READINGS = 5;

  /** mulberry32: a float in [0, 1) with 32 random bits per call, the same
   * stream spread.py Mulberry32 draws from the same seed.
   * @param {number} seed
   * @returns {{nextFloat: function(): number, nextIndex: function(number): number}}
   */
  function mulberry32(seed) {
    var a = seed >>> 0;
    function nextFloat() {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = Math.imul(a ^ (a >>> 15), a | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    return {
      nextFloat: nextFloat,
      nextIndex: function (count) { return Math.floor(nextFloat() * count); },
    };
  }

  /** numpy's default ("linear") percentile of values at q in [0, 1].
   * @param {number[]} values
   * @param {number} q
   * @returns {number}
   */
  function quantileOf(values, q) {
    var ordered = values.slice().sort(function (a, b) { return a - b; });
    var h = (ordered.length - 1) * q;
    var lo = Math.floor(h);
    var hi = Math.min(lo + 1, ordered.length - 1);
    return ordered[lo] + (h - lo) * (ordered[hi] - ordered[lo]);
  }

  /** The smallest whole number whose cube is at least n, and at least 2.
   * @param {number} n
   * @returns {number}
   */
  function blockLength(n) {
    var length = 1;
    while (length * length * length < n) length += 1;
    return Math.max(2, length);
  }

  /* Blocks of consecutive residuals drawn with replacement, wrapping from the
   * last reading to the first, cut to the residuals' length. */
  function resampleBlocks(rng, residuals, length) {
    var n = residuals.length, out = [];
    while (out.length < n) {
      var start = rng.nextIndex(n);
      for (var j = 0; j < length; j++) out.push(residuals[(start + j) % n]);
    }
    return out.slice(0, n);
  }

  function sumSquares(calc, y) {
    var c = 0;
    for (var k = 0; k < y.length; k++) { var e = calc[k] - y[k]; c += e * e; }
    return c;
  }

  function dot(a, b) {
    var c = 0;
    for (var k = 0; k < a.length; k++) c += a[k] * b[k];
    return c;
  }

  /** [params, cost]: Levenberg-Marquardt on two parameters, the steps
   * spread.py lm_log2 takes, the 2 x 2 system solved by Cramer's rule.
   * @param {function(ArrayLike<number>, number, number): ArrayLike<number>} model
   * @param {ArrayLike<number>} x
   * @param {ArrayLike<number>} y
   * @param {number[]} p0
   * @returns {[number[], number]}
   */
  function lmLog2(model, x, y, p0) {
    var p = [p0[0], p0[1]], lam = 1e-3;
    var base = model(x, p[0], p[1]);
    var cost = sumSquares(base, y);
    for (var it = 0; it < LM_MAX_ITERATIONS; it++) {
      var h0 = 1e-4 * Math.max(Math.abs(p[0]), 1.0);
      var h1 = 1e-4 * Math.max(Math.abs(p[1]), 1.0);
      var f0 = model(x, p[0] + h0, p[1]), f1 = model(x, p[0], p[1] + h1);
      var j0 = [], j1 = [], res = [];
      for (var k = 0; k < y.length; k++) {
        j0.push((f0[k] - base[k]) / h0);
        j1.push((f1[k] - base[k]) / h1);
        res.push(base[k] - y[k]);
      }
      var a00 = dot(j0, j0), a01 = dot(j0, j1), a11 = dot(j1, j1);
      var g0 = dot(j0, res), g1 = dot(j1, res);
      var stepped = false, previous = cost;
      for (var attempt = 0; attempt < 20; attempt++) {
        var d00 = a00 * (1.0 + lam), d11 = a11 * (1.0 + lam);
        var det = d00 * d11 - a01 * a01;
        if (!(isFinite(det) && det !== 0)) { lam *= 10.0; continue; }
        var trial = [p[0] + (-g0 * d11 + g1 * a01) / det,
          p[1] + (-g1 * d00 + g0 * a01) / det];
        var calc = model(x, trial[0], trial[1]);
        var ct = sumSquares(calc, y);
        if (isFinite(ct) && ct < cost) {
          p = trial; cost = ct; base = calc;
          lam = Math.max(lam / 10.0, 1e-12);
          stepped = true;
          break;
        }
        lam *= 10.0;
        if (lam > 1e12) break;
      }
      if (!stepped || previous - cost <= LM_RELATIVE_TOLERANCE * previous) break;
    }
    return [p, cost];
  }

  /** [params, misfit]: a fit finished by Newton steps on its normal
   * equations, from the p and cost a search stopped at (spread.py
   * polish_log2, step for step). A search that stops when no step lowers the
   * misfit stops where the misfit's rounding hides the next step, good to
   * eight figures in the parameters; the gradient is linear in the distance
   * left, so solving J^T J step = -J^T r undamped, with the derivatives in
   * closed form, reaches the minimum to about one part in 1e12. It stops when
   * the step stops shrinking, and is kept only if its misfit is no more than
   * POLISH_MISFIT_SLACK above the search's.
   * @param {function(ArrayLike<number>, number, number): number[][]} derivatives
   *   the curve and its two partial derivatives
   * @param {ArrayLike<number>} x
   * @param {ArrayLike<number>} y
   * @param {number[]} p
   * @param {number} cost
   * @returns {[number[], number]}
   */
  function polishLog2(derivatives, x, y, p, cost) {
    var q = [p[0], p[1]], before = Infinity;
    for (var it = 0; it < POLISH_MAX_STEPS; it++) {
      var d = derivatives(x, q[0], q[1]), res = [];
      for (var k = 0; k < y.length; k++) res.push(d[0][k] - y[k]);
      var a00 = dot(d[1], d[1]), a01 = dot(d[1], d[2]), a11 = dot(d[2], d[2]);
      var g0 = dot(d[1], res), g1 = dot(d[2], res);
      var det = a00 * a11 - a01 * a01;
      if (!(isFinite(det) && det !== 0)) break;
      var step0 = (-g0 * a11 + g1 * a01) / det;
      var step1 = (-g1 * a00 + g0 * a01) / det;
      if (!(isFinite(step0) && isFinite(step1))) break;
      var size = Math.max(Math.abs(step0) / Math.max(Math.abs(q[0]), 1.0),
        Math.abs(step1) / Math.max(Math.abs(q[1]), 1.0));
      if (!(size < before)) break;
      q = [q[0] + step0, q[1] + step1];
      before = size;
    }
    if (q[0] === p[0] && q[1] === p[1]) return [q, cost];
    var finished = sumSquares(derivatives(x, q[0], q[1])[0], y);
    if (isFinite(finished) && finished <= cost * (1.0 + POLISH_MISFIT_SLACK)) {
      return [q, finished];
    }
    return [[p[0], p[1]], cost];
  }

  /** The 2 x 2 covariance of the parameters as curve_fit scales it, with the
   * Jacobian by central differences; null when singular.
   * @param {function(ArrayLike<number>, number, number): ArrayLike<number>} model
   * @param {ArrayLike<number>} x
   * @param {ArrayLike<number>} y
   * @param {number[]} p
   * @returns {number[][]|null}
   */
  function covarianceLog2(model, x, y, p) {
    var n = x.length;
    if (n <= 2) return null;
    var h0 = 1e-5 * Math.max(Math.abs(p[0]), 1.0);
    var h1 = 1e-5 * Math.max(Math.abs(p[1]), 1.0);
    var up0 = model(x, p[0] + h0, p[1]), dn0 = model(x, p[0] - h0, p[1]);
    var up1 = model(x, p[0], p[1] + h1), dn1 = model(x, p[0], p[1] - h1);
    var j0 = [], j1 = [];
    for (var k = 0; k < n; k++) {
      j0.push((up0[k] - dn0[k]) / (2.0 * h0));
      j1.push((up1[k] - dn1[k]) / (2.0 * h1));
    }
    var a00 = dot(j0, j0), a01 = dot(j0, j1), a11 = dot(j1, j1);
    var det = a00 * a11 - a01 * a01;
    if (!(isFinite(det) && det > 0)) return null;
    var scale = sumSquares(model(x, p[0], p[1]), y) / (n - 2);
    return [[a11 / det * scale, -a01 / det * scale],
      [-a01 / det * scale, a00 / det * scale]];
  }

  /** [P10, P90] of a log-normal estimate: 10^(logValue -/+ Z_P90 sigma).
   * @param {number} logValue
   * @param {number|null|undefined} variance
   * @returns {[number|null, number|null]}
   */
  function logBand(logValue, variance) {
    if (variance === null || variance === undefined || !(isFinite(variance) &&
        variance >= 0)) {
      return [null, null];
    }
    var sigma = Math.sqrt(variance);
    return [Math.pow(10, logValue - Z_P90 * sigma), Math.pow(10, logValue + Z_P90 * sigma)];
  }

  /** s(t_day; log10 T, log10 S) for the Theis well function.
   * @param {number} qDay
   * @param {number} radiusM
   */
  function theisModel(qDay, radiusM) {
    return function (tDay, logT, logS) {
      var T = Math.pow(10, logT), S = Math.pow(10, logS), out = [];
      for (var k = 0; k < tDay.length; k++) {
        var u = radiusM * radiusM * S / (4.0 * T * tDay[k]);
        out.push(qDay / (4.0 * Math.PI * T) * exp1(u));
      }
      return out;
    };
  }

  /** [s, ds/d log10 T, ds/d log10 S] of the Theis curve, in closed form
   * (spread.py theis_derivatives): with A = Q / (4 pi T),
   * ds/d ln T = A (exp(-u) - W(u)) and ds/d ln S = -A exp(-u).
   * @param {number} qDay
   * @param {number} radiusM
   * @returns {function(ArrayLike<number>, number, number): number[][]}
   */
  function theisDerivatives(qDay, radiusM) {
    return function (tDay, logT, logS) {
      var T = Math.pow(10, logT), S = Math.pow(10, logS);
      var scale = qDay / (4.0 * Math.PI * T), s = [], dT = [], dS = [];
      for (var k = 0; k < tDay.length; k++) {
        var u = radiusM * radiusM * S / (4.0 * T * tDay[k]);
        var well = exp1(u), decay = Math.exp(-u);
        s.push(scale * well);
        dT.push(Math.LN10 * scale * (decay - well));
        dS.push(-Math.LN10 * scale * decay);
      }
      return [s, dT, dS];
    };
  }

  function factorial(n) {
    var f = 1;
    for (var i = 2; i <= n; i++) f *= i;
    return f;
  }

  /** Stehfest's (1970) coefficients V_1 .. V_n, n even, summed as spread.py
   * sums them.
   * @param {number} n
   * @returns {number[]}
   */
  function stehfestWeights(n) {
    var half = n / 2, weights = [];
    for (var i = 1; i <= n; i++) {
      var total = 0.0;
      for (var k = Math.floor((i + 1) / 2); k <= Math.min(i, half); k++) {
        total += (Math.pow(k, half) * factorial(2 * k)) /
          (factorial(half - k) * factorial(k) * factorial(k - 1) *
            factorial(i - k) * factorial(2 * k - i));
      }
      weights.push((half + i) % 2 === 0 ? total : -total);
    }
    return weights;
  }
  var STEHFEST_WEIGHTS = stehfestWeights(STEHFEST_TERMS);

  /* Cephes' Chebyshev series for the modified Bessel functions, as scipy
   * evaluates k0e and k1e: chbevl, i0 and i1 below 2, and the scaled K0 and
   * K1. The coefficients are Cephes' (Moshier), which scipy carries in xsf,
   * written to the shortest digits that give the same doubles. */
  function chbevl(x, coefs) {
    var b0 = coefs[0], b1 = 0.0, b2 = 0.0;
    for (var i = 1; i < coefs.length; i++) {
      b2 = b1; b1 = b0; b0 = x * b1 - b2 + coefs[i];
    }
    return 0.5 * (b0 - b2);
  }
  var I0_A = [-4.4153416464793395e-18, 3.3307945188222384e-17,
    -2.431279846547955e-16, 1.715391285555133e-15,
    -1.1685332877993451e-14, 7.676185498604936e-14,
    -4.856446783111929e-13, 2.95505266312964e-12,
    -1.726826291441556e-11, 9.675809035373237e-11,
    -5.189795601635263e-10, 2.6598237246823866e-09,
    -1.300025009986248e-08, 6.046995022541919e-08,
    -2.670793853940612e-07, 1.1173875391201037e-06,
    -4.4167383584587505e-06, 1.6448448070728896e-05,
    -5.754195010082104e-05, 0.00018850288509584165,
    -0.0005763755745385824, 0.0016394756169413357,
    -0.004324309995050576, 0.010546460394594998,
    -0.02373741480589947, 0.04930528423967071,
    -0.09490109704804764, 0.17162090152220877,
    -0.3046826723431984, 0.6767952744094761];
  var I1_A = [2.7779141127610464e-18, -2.111421214358166e-17,
    1.5536319577362005e-16, -1.1055969477353862e-15,
    7.600684294735408e-15, -5.042185504727912e-14,
    3.223793365945575e-13, -1.9839743977649436e-12,
    1.1736186298890901e-11, -6.663489723502027e-11,
    3.625590281552117e-10, -1.8872497517228294e-09,
    9.381537386495773e-09, -4.445059128796328e-08,
    2.0032947535521353e-07, -8.568720264695455e-07,
    3.4702513081376785e-06, -1.3273163656039436e-05,
    4.781565107550054e-05, -0.00016176081582589674,
    0.0005122859561685758, -0.0015135724506312532,
    0.004156422944312888, -0.010564084894626197,
    0.024726449030626516, -0.05294598120809499,
    0.1026436586898471, -0.17641651835783406,
    0.25258718644363365];
  var K0_A = [1.374465435613523e-16, 4.25981614279661e-14,
    1.0349695257633842e-11, 1.904516377220209e-09,
    2.5347910790261494e-07, 2.286212103119452e-05,
    0.001264615411446926, 0.0359799365153615,
    0.3442898999246285, -0.5353273932339028];
  var K0_B = [5.300433772686263e-18, -1.6475804301524212e-17,
    5.2103915050390274e-17, -1.678231096805412e-16,
    5.512055978524319e-16, -1.848593377343779e-15,
    6.3400764774050706e-15, -2.2275133269916698e-14,
    8.032890775363575e-14, -2.9800969231727303e-13,
    1.140340588208475e-12, -4.514597883373944e-12,
    1.8559491149547177e-11, -7.957489244477107e-11,
    3.577397281400301e-10, -1.69753450938906e-09,
    8.574034017414225e-09, -4.660489897687948e-08,
    2.766813639445015e-07, -1.8317555227191195e-06,
    1.39498137188765e-05, -0.00012849549581627802,
    0.0015698838857300533, -0.0314481013119645,
    2.4403030820659555];
  var K1_A = [-7.023863479386288e-18, -2.427449850519366e-15,
    -6.666901694199329e-13, -1.4114883926335278e-10,
    -2.213387630734726e-08, -2.4334061415659684e-06,
    -0.0001730288957513052, -0.006975723859639864,
    -0.12261118082265715, -0.3531559607765449,
    1.5253002273389478];
  var K1_B = [-5.756744483665017e-18, 1.7940508731475592e-17,
    -5.689462558442859e-17, 1.838093544366639e-16,
    -6.057047248373319e-16, 2.038703165624334e-15,
    -7.019837090418314e-15, 2.4771544244813043e-14,
    -8.976705182324994e-14, 3.3484196660784293e-13,
    -1.2891739609510289e-12, 5.13963967348173e-12,
    -2.1299678384275683e-11, 9.218315187605006e-11,
    -4.1903547593418965e-10, 2.015049755197033e-09,
    -1.0345762465678097e-08, 5.7410841254500495e-08,
    -3.5019606030878126e-07, 2.406484947837217e-06,
    -1.936197974166083e-05, 0.00019521551847135162,
    -0.002857816859622779, 0.10392373657681724,
    2.7206261904844427];

  /** exp(x) K0(x), as scipy.special.k0e; x > 0.
   * @param {number} x
   * @returns {number}
   */
  function besselK0e(x) {
    if (!(x > 0)) return x === 0 ? Infinity : NaN;
    if (x <= 2.0) {
      var i0 = Math.exp(x) * chbevl(x / 2.0 - 2.0, I0_A);
      return (chbevl(x * x - 2.0, K0_A) - Math.log(0.5 * x) * i0) * Math.exp(x);
    }
    return chbevl(8.0 / x - 2.0, K0_B) / Math.sqrt(x);
  }

  /** exp(x) K1(x), as scipy.special.k1e; x > 0.
   * @param {number} x
   * @returns {number}
   */
  function besselK1e(x) {
    if (!(x > 0)) return x === 0 ? Infinity : NaN;
    if (x <= 2.0) {
      var i1 = chbevl(x / 2.0 - 2.0, I1_A) * x * Math.exp(x);
      return (Math.log(0.5 * x) * i1 + chbevl(x * x - 2.0, K1_A) / x) * Math.exp(x);
    }
    return chbevl(8.0 / x - 2.0, K1_B) / Math.sqrt(x);
  }

  /** Papadopulos-Cooper drawdown in the well, 2 pi T s / Q, at dimensionless
   * time tD for the storage coefficient cD = r_c^2 / (2 r_w^2 S).
   * @param {number} tD
   * @param {number} cD
   * @returns {number}
   */
  function pcDimensionless(tD, cD) {
    var ln2 = Math.log(2.0), total = 0.0;
    for (var i = 1; i <= STEHFEST_WEIGHTS.length; i++) {
      var p = i * ln2 / tD, q = Math.sqrt(p), k0 = besselK0e(q);
      total += STEHFEST_WEIGHTS[i - 1] * (k0 / (p * (q * besselK1e(q) + cD * p * k0)));
    }
    return ln2 / tD * total;
  }

  /** Papadopulos and Cooper's F(u_w, alpha): s_w = Q / (4 pi T) F.
   * @param {number} uW
   * @param {number} alpha
   * @returns {number}
   */
  function pcWellFunction(uW, alpha) {
    return 2.0 * pcDimensionless(1.0 / (4.0 * uW), 1.0 / (2.0 * alpha));
  }

  /** s(t_day; log10 T, log10 S) in a well of large diameter.
   * @param {number} qDay
   * @param {number} radiusM
   * @param {number} casingRadius
   */
  function pcModel(qDay, radiusM, casingRadius) {
    return function (tDay, logT, logS) {
      var T = Math.pow(10, logT), S = Math.pow(10, logS), out = [];
      var cD = casingRadius * casingRadius / (2.0 * radiusM * radiusM * S);
      for (var k = 0; k < tDay.length; k++) {
        var tD = T * tDay[k] / (S * radiusM * radiusM);
        out.push(qDay / (2.0 * Math.PI * T) * pcDimensionless(tD, cD));
      }
      return out;
    };
  }

  /** The radius of the water surface that falls in the casing: the annulus
   * between casing and riser, as Schafer's rule takes it.
   * @param {PumpingConfig} cfg
   * @returns {number|null}
   */
  function casingRadiusM(cfg) {
    var dc = cfg.casing_diameter_in * 0.0254, dp = cfg.riser_diameter_in * 0.0254;
    var area = dc * dc - dp * dp;
    return area > 0 ? Math.sqrt(area) / 2.0 : null;
  }

  /** The large-diameter fit to every reading, casing storage included; the
   * readings and refusals are the Theis fit's.
   * @param {ArrayLike<number>} timeMin
   * @param {ArrayLike<number>} drawdownM
   * @param {number} dischargeM3PerH
   * @param {number} radiusM
   * @param {number} casingRadius
   * @param {number[]|null} [start] [log10 T, log10 S]
   */
  function papadopulosCooperFit(timeMin, drawdownM, dischargeM3PerH, radiusM,
                                casingRadius, start) {
    requireDischarge(dischargeM3PerH);
    var t = [], s = [], i;
    for (i = 0; i < timeMin.length; i++) {
      var td = timeMin[i] / MIN_PER_DAY;
      if (td > 0 && drawdownM[i] > 0) { t.push(td); s.push(drawdownM[i]); }
    }
    if (t.length < 5) throw new Error('Not enough readings for a Papadopulos-Cooper fit');
    var logTime = t.map(function (v) { return Math.log10(v); });
    if (lineFit(logTime, s).slope * (arrMax(logTime) - arrMin(logTime)) <
        READING_RESOLUTION_M) {
      throw new Error('The drawdown rises by less than a dipper reads across the ' +
        'readings, so the large-diameter curve cannot be fitted to it');
    }
    var qDay = Number(dischargeM3PerH) * 24.0;
    var p0 = start;
    if (!p0) {
      var half = Math.floor(s.length / 2);
      var slope0 = Math.max((s[s.length - 1] - s[half]) /
        Math.max(Math.log10(t[t.length - 1] / t[half]), 0.3), 0.1);
      var T0 = 2.303 * qDay / (4.0 * Math.PI * slope0);
      p0 = [Math.log10(Math.max(T0, 1e-2)), -3.0];
    }
    var model = pcModel(qDay, radiusM, casingRadius);
    var fitted = lmLog2(model, t, s, p0), p = fitted[0];
    var T = Math.pow(10, p[0]), S = Math.pow(10, p[1]);
    if (!(isFinite(T) && S >= THEIS_STORATIVITY_FLOOR)) {
      throw new Error('The Papadopulos-Cooper fit drives the storativity to the ' +
        'floor, so T and S cannot be fitted to it');
    }
    var covariance = covarianceLog2(model, t, s, p);
    var band = logBand(p[0], covariance ? covariance[0][0] : null);
    return {
      transmissivity_m2_per_day: T,
      storativity: S,
      storativity_reliable: false,
      rmse_m: Math.sqrt(fitted[1] / t.length),
      discharge_m3_per_h: Number(dischargeM3PerH),
      radius_m: radiusM,
      casing_radius_m: casingRadius,
      alpha: radiusM * radiusM * S / (casingRadius * casingRadius),
      n_points: t.length,
      transmissivity_low_m2_per_day: band[0],
      transmissivity_high_m2_per_day: band[1],
      log_covariance: covariance,
    };
  }

  /* Times (min) and drawdowns of the first step, as the drawdown fits read
   * them. */
  function firstStepSeries(analysis) {
    var test = analysis.test, swl = test.static_water_level_m;
    var t = [], s = [];
    if (swl === null || swl === undefined || !(test.steps || []).length) {
      return { t: t, s: s };
    }
    var step = test.steps[0];
    for (var i = 0; i < step.time_min.length; i++) {
      var tt = step.time_min[i] <= 0 ? NaN : step.time_min[i];
      var ss = step.water_level_m[i] - swl;
      if (isFinite(tt) && isFinite(ss)) { t.push(tt); s.push(ss); }
    }
    return { t: t, s: s };
  }

  /* [slope, intercept] by the closed form, summed left to right as
   * spread.py _line sums them */
  function closedLine(x, y) {
    var n = x.length, sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (var k = 0; k < n; k++) {
      sx += x[k]; sy += y[k]; sxx += x[k] * x[k]; sxy += x[k] * y[k];
    }
    var den = n * sxx - sx * sx;
    var slope = den !== 0 ? (n * sxy - sx * sy) / den : 0.0;
    return [slope, (sy - slope * sx) / n];
  }

  function lineRefit(x, qDay) {
    return function (y) {
      var slope = closedLine(x, y)[0];
      if (!(slope > 0)) return null;
      return 2.303 * qDay / (4.0 * Math.PI * slope);
    };
  }

  /* derivatives: the curve's closed-form partial derivatives, where it has
   * them; the refit is then finished with polishLog2, as the fit it
   * resamples was (spread.py _curve_refit) */
  function curveRefit(model, x, start, derivatives) {
    return function (y) {
      var found = lmLog2(model, x, y, start), p = found[0];
      if (derivatives) p = polishLog2(derivatives, x, y, p, found[1])[0];
      var T = Math.pow(10, p[0]);
      if (!(isFinite(T) && Math.pow(10, p[1]) >= THEIS_STORATIVITY_FLOOR)) return null;
      return T;
    };
  }

  /* {x, y, fitted, refit} for the readings a method was fitted to. */
  function fitSeries(analysis, method) {
    var x = [], y = [], fitted, k;
    if (method === 'cooper_jacob') {
      var cj = analysis.cooper_jacob, series = firstStepSeries(analysis);
      series.t.forEach(function (tt, i) {
        if (tt >= cj.fit_window_min[0] && tt <= cj.fit_window_min[1]) {
          x.push(Math.log10(tt)); y.push(series.s[i]);
        }
      });
      /* the line through these readings, fitted here as spread.py fits it:
       * the intercept time the result keeps underflows to zero on a line that
       * barely rises */
      var line = closedLine(x, y);
      fitted = x.map(function (v) { return line[0] * v + line[1]; });
      return { x: x, y: y, fitted: fitted,
        refit: lineRefit(x, cj.discharge_m3_per_h * 24.0) };
    }
    if (method === 'recovery') {
      var rec = analysis.recovery, test = analysis.test;
      var tp = test.recovery_time_min || [], levels = test.recovery_level_m || [];
      for (k = 0; k < tp.length; k++) {
        var residual = levels[k] - test.static_water_level_m;
        if (tp[k] > 0 && isFinite(residual)) {
          x.push(Math.log10((rec.pumping_time_min + tp[k]) / tp[k]));
          y.push(residual);
        }
      }
      fitted = x.map(function (v) { return rec.slope_m_per_log_cycle * v + rec.intercept_m; });
      return { x: x, y: y, fitted: fitted,
        refit: lineRefit(x, rec.discharge_m3_per_h * 24.0) };
    }
    var first = firstStepSeries(analysis);
    first.t.forEach(function (tt, i) {
      if (tt > 0 && first.s[i] > 0) { x.push(tt / MIN_PER_DAY); y.push(first.s[i]); }
    });
    var result = method === 'theis' ? analysis.theis : analysis.papadopulos_cooper;
    var qDay = result.discharge_m3_per_h * 24.0;
    var model = method === 'theis' ? theisModel(qDay, result.radius_m)
      : pcModel(qDay, result.radius_m, result.casing_radius_m);
    var derivatives = method === 'theis' ? theisDerivatives(qDay, result.radius_m) : null;
    var start = [Math.log10(result.transmissivity_m2_per_day), Math.log10(result.storativity)];
    fitted = model(x, start[0], start[1]);
    return { x: x, y: y, fitted: fitted, refit: curveRefit(model, x, start, derivatives) };
  }

  /** The P10, P50 and P90 of a method's transmissivity under residuals
   * resampled in wrapped blocks (spread.py bootstrap_fit).
   * @param {PumpingAnalysis} analysis
   * @param {string} method
   * @param {PumpingConfig} [config]
   * @returns {Rec}
   */
  function bootstrapFit(analysis, method, config) {
    var cfg = config || defaultConfig().pumping;
    var series = fitSeries(analysis, method);
    var n = series.y.length;
    /** @type {Rec} */
    var out = {
      method: method, replicates: cfg.bootstrap_replicates, failed: 0,
      block_length: blockLength(n), seed: cfg.bootstrap_seed, n_points: n,
      p10: null, p50: null, p90: null, reason: '',
    };
    if (n < BOOTSTRAP_MIN_READINGS) { out.reason = 'too_few'; return out; }
    var residuals = series.y.map(function (v, i) { return v - series.fitted[i]; });
    var mean = 0;
    residuals.forEach(function (r) { mean += r; });
    mean /= n;
    var inflate = Math.sqrt(n / (n - 2.0));
    residuals = residuals.map(function (r) { return (r - mean) * inflate; });
    var rng = mulberry32(cfg.bootstrap_seed), values = [];
    for (var b = 0; b < out.replicates; b++) {
      var draw = resampleBlocks(rng, residuals, out.block_length);
      var value = series.refit(series.fitted.map(function (f, i) { return f + draw[i]; }));
      if (value === null) out.failed += 1; else values.push(value);
    }
    if (values.length * 2 < out.replicates) { out.reason = 'mostly_failed'; return out; }
    out.p10 = quantileOf(values, BAND_QUANTILES[0]);
    out.p50 = quantileOf(values, BAND_QUANTILES[1]);
    out.p90 = quantileOf(values, BAND_QUANTILES[2]);
    return out;
  }

  /** [t, ds/d ln t] by Bourdet's weighted central difference over the nearest
   * neighbours at least lLog10 log cycles away on each side.
   * @param {number[]} timeMin
   * @param {number[]} drawdownM
   * @param {number} lLog10
   * @returns {[number[], number[]]}
   */
  function bourdetDerivative(timeMin, drawdownM, lLog10) {
    var x = timeMin.map(function (v) { return Math.log(v); });
    var gap = lLog10 * Math.log(10.0), outT = [], outD = [];
    for (var i = 0; i < timeMin.length; i++) {
      var left = i - 1;
      while (left >= 0 && x[i] - x[left] < gap) left -= 1;
      var right = i + 1;
      while (right < timeMin.length && x[right] - x[i] < gap) right += 1;
      if (left < 0 || right >= timeMin.length) continue;
      var dx1 = x[i] - x[left], dx2 = x[right] - x[i];
      var d1 = (drawdownM[i] - drawdownM[left]) / dx1;
      var d2 = (drawdownM[right] - drawdownM[i]) / dx2;
      outT.push(timeMin[i]);
      outD.push((d1 * dx2 + d2 * dx1) / (dx1 + dx2));
    }
    return [outT, outD];
  }

  function localSlopes(times, values, window) {
    var lx = times.map(function (t, i) { return values[i] > 0 ? Math.log10(t) : null; });
    var ly = values.map(function (v) { return v > 0 ? Math.log10(v) : null; });
    return lx.map(function (xi) {
      if (xi === null) return null;
      var xs = [], ys = [];
      lx.forEach(function (xj, j) {
        if (xj !== null && Math.abs(xj - xi) <= window / 2.0) { xs.push(xj); ys.push(ly[j]); }
      });
      if (xs.length < 3) return null;
      var n = xs.length, sx = 0, sy = 0, sxx = 0, sxy = 0;
      for (var k = 0; k < n; k++) {
        sx += xs[k]; sy += ys[k]; sxx += xs[k] * xs[k]; sxy += xs[k] * ys[k];
      }
      var den = n * sxx - sx * sx;
      return den > 0 ? (n * sxy - sx * sy) / den : null;
    });
  }

  function slopeClass(m, cfg) {
    if (m === null) return null;
    if (cfg.regime_unit_slope_min <= m && m <= cfg.regime_unit_slope_max) return 'unit';
    if (cfg.regime_half_slope_min <= m && m <= cfg.regime_half_slope_max) return 'half';
    if (Math.abs(m) <= cfg.regime_flat_max) return 'flat';
    if (m <= cfg.regime_falling_max) return 'falling';
    if (m > 0) return 'rising';
    return null;
  }

  /* Name the regimes from runs of one slope class (spread.py
   * classify_regimes). */
  function classifyRegimes(times, slopes, cfg) {
    var runs = [];
    slopes.forEach(function (m, i) {
      var cls = slopeClass(m, cfg);
      if (cls === null) return;
      var last = runs[runs.length - 1];
      if (last && last.cls === cls && last.members[last.members.length - 1] === i - 1) {
        last.members.push(i);
      } else {
        runs.push({ cls: cls, members: [i] });
      }
    });
    var regimes = [], seenFlat = false;
    runs.forEach(function (run) {
      var members = run.members;
      var start = times[members[0]], end = times[members[members.length - 1]];
      if (members.length < 3 || Math.log10(end / start) < cfg.diagnostic_min_span_log10) {
        return;
      }
      var key;
      if (run.cls === 'unit') key = seenFlat ? 'closed_boundary' : 'wellbore_storage';
      else if (run.cls === 'half') key = 'linear_flow';
      else if (run.cls === 'flat') { key = 'radial_flow'; seenFlat = true; }
      else if (run.cls === 'falling') key = seenFlat ? 'recharge_boundary' : 'storage_ending';
      else if (seenFlat) key = 'no_flow_boundary';
      else return;
      regimes.push({
        key: key, start_min: start, end_min: end,
        slope: quantileOf(members.map(function (i) { return slopes[i]; }), 0.5),
        n_points: members.length,
      });
    });
    return regimes;
  }

  /** The Bourdet derivative of the first step and the regimes it shows, or
   * null below five positive drawdowns.
   * @param {PumpingAnalysis} analysis
   * @param {PumpingConfig} [config]
   * @returns {Rec|null}
   */
  function diagnosePumping(analysis, config) {
    var cfg = config || defaultConfig().pumping;
    var series = firstStepSeries(analysis), pairs = [];
    series.t.forEach(function (tt, i) {
      if (tt > 0 && series.s[i] > 0) pairs.push([tt, series.s[i], pairs.length]);
    });
    /* stable by time; a time read twice is one point, the first reading */
    pairs.sort(function (a, b) { return a[0] - b[0] || a[2] - b[2]; });
    var t = [], s = [];
    pairs.forEach(function (pair) {
      if (!t.length || pair[0] > t[t.length - 1]) { t.push(pair[0]); s.push(pair[1]); }
    });
    if (t.length < 5) return null;
    var derivative = bourdetDerivative(t, s, cfg.diagnostic_l_log10);
    var slopes = localSlopes(derivative[0], derivative[1], cfg.diagnostic_window_log10);
    /** @type {Rec} */
    var out = {
      time_min: t, drawdown_m: s,
      derivative_time_min: derivative[0], derivative_m: derivative[1], slopes: slopes,
      l_log10: cfg.diagnostic_l_log10,
      regimes: classifyRegimes(derivative[0], slopes, cfg),
      plateau_transmissivity_m2_per_day: null,
    };
    var q = analysis.test.steps[0].discharge_m3_per_h;
    var radial = out.regimes.filter(function (r) { return r.key === 'radial_flow'; })[0];
    if (radial && q) {
      var plateau = [];
      derivative[0].forEach(function (tt, i) {
        if (tt >= radial.start_min && tt <= radial.end_min && derivative[1][i] > 0) {
          plateau.push(derivative[1][i]);
        }
      });
      if (plateau.length) {
        out.plateau_transmissivity_m2_per_day =
          Number(q) * 24.0 / (4.0 * Math.PI * quantileOf(plateau, 0.5));
      }
    }
    return out;
  }

  /** The slope limits that name each regime, for a hydrogeologist to check.
   * @param {PumpingConfig} [config]
   * @returns {string}
   */
  function diagnosticThresholdsText(config) {
    var cfg = config || defaultConfig().pumping;
    return phrase('pumping.diagnostic_thresholds', {
      unit_min: cfg.regime_unit_slope_min, unit_max: cfg.regime_unit_slope_max,
      half_min: cfg.regime_half_slope_min, half_max: cfg.regime_half_slope_max,
      flat: cfg.regime_flat_max, falling: cfg.regime_falling_max,
      span: cfg.diagnostic_min_span_log10,
    });
  }

  /** One paragraph: the derivative's method and the regimes it names.
   * @param {Rec|null|undefined} diagnostic
   * @returns {string}
   */
  function diagnosticText(diagnostic) {
    if (!diagnostic) return phrase('pumping.diagnostic_none');
    var words = phraseTable('pumping.regimes');
    var spans = diagnostic.regimes.map(function (r) {
      return phrase('pumping.regime_span', { what: words[r.key], start: r.start_min,
        end: r.end_min, slope: r.slope });
    });
    var text = phrase('pumping.diagnostic_method', { l: diagnostic.l_log10 });
    if (!spans.length) return text + ' ' + phrase('pumping.diagnostic_unnamed');
    text += ' ' + phrase('pumping.diagnostic_shows', { spans: spans.join('; ') });
    if (diagnostic.plateau_transmissivity_m2_per_day !== null) {
      text += ' ' + phrase('pumping.diagnostic_plateau',
        { t: diagnostic.plateau_transmissivity_m2_per_day });
    }
    return text;
  }

  /** Bootstrap the adopted fit and turn its band into yield and pump bands;
   * the central figures are the analysis's own and are not moved.
   * @param {PumpingAnalysis} analysis
   * @param {PumpingConfig} [config]
   * @returns {void}
   */
  function attachSpread(analysis, config) {
    var cfg = config || defaultConfig().pumping;
    /** @type {Rec} */
    var spread = {
      bootstrap: null, safe_yield_low_m3_per_h: null, safe_yield_high_m3_per_h: null,
      long_term_low_m3_per_h: null, holds_at_dry_season: false,
      pump_depth_low_m: null, pump_depth_high_m: null,
    };
    analysis.spread = spread;
    var method = adoptedFit(analysis).method;
    var rec = analysis.yield_recommendation;
    if (method === null) return;
    spread.bootstrap = bootstrapFit(analysis, method, cfg);
    if (!rec || rec.safe_yield_m3_per_h === null || rec.safe_yield_m3_per_h === undefined) {
      return;
    }
    var central = rec.safe_yield_m3_per_h, boot = spread.bootstrap;
    if (boot.p10 !== null && boot.p90 !== null) {
      var low = recommendYield(analysis.test, boot.p10, analysis.step_test, cfg);
      var high = recommendYield(analysis.test, boot.p90, analysis.step_test, cfg);
      if (low.safe_yield_m3_per_h !== null) {
        spread.safe_yield_low_m3_per_h = Math.min(low.safe_yield_m3_per_h, central);
        spread.long_term_low_m3_per_h = low.long_term_yield_m3_per_h;
      }
      if (high.safe_yield_m3_per_h !== null) {
        spread.safe_yield_high_m3_per_h = Math.max(high.safe_yield_m3_per_h, central);
      }
      spread.holds_at_dry_season = spread.long_term_low_m3_per_h !== null &&
        spread.long_term_low_m3_per_h >= central;
    }
    var depths = [rec.pump_installation_depth_m];
    ENVELOPE_SEASONAL_M.forEach(function (decline) {
      var variant = Object.assign({}, cfg, { seasonal_allowance_m: decline });
      depths.push(recommendYield(analysis.test, analysis.transmissivity_m2_per_day,
        analysis.step_test, variant).pump_installation_depth_m);
    });
    depths = depths.filter(function (d) { return d !== null && d !== undefined; });
    if (depths.length) {
      spread.pump_depth_low_m = arrMin(depths);
      spread.pump_depth_high_m = arrMax(depths);
    }
  }

  /** The sentences every report and both apps print about the bands.
   * @param {PumpingAnalysis} analysis
   * @param {PumpingConfig} [config]
   * @returns {string[]}
   */
  function spreadParagraphs(analysis, config) {
    var cfg = config || defaultConfig().pumping;
    var spread = analysis.spread;
    if (!spread || !spread.bootstrap) return [];
    var boot = spread.bootstrap, out = [];
    var method = METHOD_LABELS[boot.method];
    if (boot.p10 === null) {
      out.push(phrase('pumping.spread_withheld', { method: method,
        reason: phraseTable('pumping.spread_reasons')[boot.reason] }));
    } else {
      out.push(phrase('pumping.spread_transmissivity', { low: boot.p10, high: boot.p90,
        method: method, replicates: boot.replicates, n: boot.n_points,
        block: boot.block_length }));
      if (boot.failed) out.push(phrase('pumping.spread_failed', { failed: boot.failed }));
    }
    var rec = analysis.yield_recommendation;
    if (rec && rec.safe_yield_m3_per_h !== null && rec.safe_yield_m3_per_h !== undefined &&
        spread.safe_yield_low_m3_per_h !== null) {
      if (spread.safe_yield_high_m3_per_h === null) {
        out.push(phrase('pumping.spread_yield_open', {
          low: spread.safe_yield_low_m3_per_h, reserve: cfg.seasonal_allowance_m }));
      } else {
        out.push(phrase('pumping.spread_yield', { low: spread.safe_yield_low_m3_per_h,
          high: spread.safe_yield_high_m3_per_h, reserve: cfg.seasonal_allowance_m }));
      }
      out.push(phrase(spread.holds_at_dry_season ? 'pumping.spread_holds'
        : 'pumping.spread_does_not_hold', { long_term: spread.long_term_low_m3_per_h,
        rate: rec.safe_yield_m3_per_h }));
    }
    if (spread.pump_depth_low_m !== null) {
      out.push(phrase('pumping.spread_pump', { low: spread.pump_depth_low_m,
        high: spread.pump_depth_high_m, decline_low: ENVELOPE_SEASONAL_M[0],
        decline_high: ENVELOPE_SEASONAL_M[1] }));
    }
    var theis = analysis.theis;
    if (theis && theis.transmissivity_low_m2_per_day !== null &&
        theis.transmissivity_low_m2_per_day !== undefined) {
      out.push(phrase('pumping.theis_covariance', {
        low: theis.transmissivity_low_m2_per_day,
        high: theis.transmissivity_high_m2_per_day }));
    }
    return out;
  }

  /** The large-diameter fit in one paragraph, or an empty string.
   * @param {PumpingAnalysis} analysis
   * @returns {string}
   */
  function papadopulosCooperText(analysis) {
    var pc = analysis.papadopulos_cooper;
    if (!pc) return '';
    var text = phrase('pumping.pc_fit', { t: pc.transmissivity_m2_per_day,
      rc: pc.casing_radius_m, n: pc.n_points, rmse: pc.rmse_m });
    if (analysis.transmissivity_source === 'papadopulos_cooper') {
      return text + ' ' + phrase('pumping.pc_adopted');
    }
    if (analysis.papadopulos_cooper_invalid) {
      return text + ' ' + phrase('pumping.pc_invalid',
        { why: analysis.papadopulos_cooper_invalid });
    }
    return text + ' ' + phrase('pumping.pc_reported');
  }

  /** The completion report's sentence on an established yield, or null:
   * "sustainable" only where the band holds at the dry-season level.
   * @param {Rec|null|undefined} rec a yield recommendation
   * @param {Rec|null|undefined} spread
   * @returns {string|null}
   */
  function sustainableSentence(rec, spread) {
    if (!rec || !rec.safe_yield_m3_per_h) return null;
    if (rec.is_indicative) return null;
    if (spread && spread.holds_at_dry_season) return phrase('pumping.sustainable');
    return phrase('pumping.sustainable_not_held');
  }

  Object.assign(C, {
    mulberry32: mulberry32, quantileOf: quantileOf, blockLength: blockLength,
    lmLog2: lmLog2, polishLog2: polishLog2, covarianceLog2: covarianceLog2,
    theisModel: theisModel, theisDerivatives: theisDerivatives,
    stehfestWeights: stehfestWeights, besselK0e: besselK0e, besselK1e: besselK1e,
    pcWellFunction: pcWellFunction, pcModel: pcModel, casingRadiusM: casingRadiusM,
    papadopulosCooperFit: papadopulosCooperFit, bootstrapFit: bootstrapFit,
    bourdetDerivative: bourdetDerivative, diagnosePumping: diagnosePumping,
    diagnosticText: diagnosticText, diagnosticThresholdsText: diagnosticThresholdsText,
    attachSpread: attachSpread, spreadParagraphs: spreadParagraphs,
    papadopulosCooperText: papadopulosCooperText,
    sustainableSentence: sustainableSentence,
  });


  /* ================================================================== maths */

  var MIN_PER_DAY = 1440.0;

  function isFiniteNum(v) { return typeof v === 'number' && isFinite(v); }

  function arrMin(a) {
    var m = Infinity;
    for (var i = 0; i < a.length; i++) if (a[i] < m) m = a[i];
    return m;
  }
  function arrMax(a) {
    var m = -Infinity;
    for (var i = 0; i < a.length; i++) if (a[i] > m) m = a[i];
    return m;
  }
  function arrMean(a) {
    var s = 0;
    for (var i = 0; i < a.length; i++) s += a[i];
    return a.length ? s / a.length : NaN;
  }

  /* --- Bessel J0 and J1 -----------------------------------------------------
   * Cephes j0 and j1 (Moshier) as xsf carries them (cephes/j0.h and j1.h),
   * which scipy 1.18 and later evaluates as scipy.special.j0 and j1, so the
   * quadrature tables are built from the same values in both engines: these
   * agree with scipy 1.18's to 1.1e-16 out to 2e5, the largest abscissa the
   * tables reach. scipy 1.17 has the same code below x = 10, but above it
   * takes the asymptotic form at cos(x - pi/4) where xsf now takes cos(x)
   * and sin(x) apart; against 1.17 these agree to 3e-16 on [0, 30] and to
   * 1.5e-14 out to 2e5. J1 returns x / 2 below sqrt(eps), as xsf's own
   * source does and neither release yet does, which moves only results
   * below 1.5e-8, where the J1 table never reaches: its lowest node is
   * 2.0e-8. (The J0 table reaches 2e-16, where both give 1.)
   * parity.mjs holds both functions, and their zeros, to scipy. The
   * coefficients are written to the shortest digits that give the same
   * doubles.
   *
   * The rational approximations these replace (Numerical Recipes' bessj0 and
   * bessj1) were good to 5e-9, which is not good enough. The forward model is
   * the top layer's resistivity plus an integral that, under a thin resistive
   * top layer, cancels nearly all of it, so an error in the tables reaches
   * the apparent resistivity multiplied by rho1 / rho_a. The inversion walks
   * such a layer out to 1e5 ohm-m over a sounding of 3 ohm-m, where the old
   * tables put the two engines' forward models 0.1 percent apart and each
   * search stopped somewhere else.
   */

  var SQRT2OPI = 0.7978845608028654;  /* sqrt(2 / pi) */
  var SQRT1OPI = 0.5641895835477563;  /* sqrt(1 / pi) */
  var THPIO4 = 2.356194490192345;     /* 3 pi / 4 */

  /* polynomial with coefficients highest first, and the same with a leading 1 */
  function polevl(x, coef) {
    var ans = coef[0];
    for (var i = 1; i < coef.length; i++) ans = ans * x + coef[i];
    return ans;
  }
  function p1evl(x, coef) {
    var ans = x + coef[0];
    for (var i = 1; i < coef.length; i++) ans = ans * x + coef[i];
    return ans;
  }

  var J0_PP = [0.0007969367292973471, 0.08283523921074408, 1.239533716464143,
    5.447250030587687, 8.74716500199817, 5.303240382353949,
    1.0];
  var J0_PQ = [0.0009244088105588637, 0.08562884743544745, 1.2535274390105895,
    5.470977403304171, 8.761908832370695, 5.306052882353947,
    1.0];
  var J0_QP = [-0.011366383889846916, -1.2825271867050931, -19.553954425773597,
    -93.20601521237683, -177.68116798048806, -147.07750515495118,
    -51.41053267665993, -6.050143506007285];
  var J0_QQ = [64.3178256118178, 856.4300259769806, 3882.4018360540163,
    7240.467741956525, 5930.727011873169, 2062.0933166032783,
    242.0057402402914];
  var J0_DR1 = 5.783185962946784, J0_DR2 = 30.471262343662087;
  var J0_RP = [-4794432209.782018, 1956174919465.5657, -249248344360967.72,
    9708622510473064.0];
  var J0_RQ = [499.563147152651, 173785.4016763747, 48440965.83399621,
    11185553704.535683, 2112775201154.892, 310518229857422.56,
    3.1812195594320496e+16, 1.7108629408104315e+18];

  /**
   * @param {number} x
   * @returns {number}
   */
  function besselJ0(x) {
    var w, z, p, q;
    if (x < 0) x = -x;
    if (x <= 5.0) {
      if (x < 1.0e-5) return 1.0 - x * x / 4.0;
      z = x * x;
      p = (z - J0_DR1) * (z - J0_DR2);
      return p * polevl(z, J0_RP) / p1evl(z, J0_RQ);
    }
    w = 5.0 / x;
    q = 25.0 / (x * x);
    p = polevl(q, J0_PP) / polevl(q, J0_PQ);
    q = polevl(q, J0_QP) / p1evl(q, J0_QQ);
    if (x < 10.0) {
      var xn = x - Math.PI / 4;
      p = p * Math.cos(xn) - w * q * Math.sin(xn);
      return p * SQRT2OPI / Math.sqrt(x);
    }
    p = (p + w * q) * Math.cos(x) + (p - w * q) * Math.sin(x);
    return p * SQRT1OPI / Math.sqrt(x);
  }

  var J1_RP = [-899971225.7055594, 452228297998.19403, -72749424522181.83,
    3682957328638529.0];
  var J1_RQ = [620.8364781180543, 256987.25675774884, 83514679.14319493,
    22151159547.97925, 4749141220799.914, 784369607876235.9,
    8.952223361846274e+16, 5.322786203326801e+18];
  var J1_PP = [0.0007621256162081731, 0.07313970569409176, 1.1271960812968493,
    5.112079511468076, 8.424045901417724, 5.214515986823615,
    1.0];
  var J1_PQ = [0.0005713231280725487, 0.06884559087544954, 1.105142326340617,
    5.073863861286015, 8.399855543276042, 5.209828486823619,
    1.0];
  var J1_QP = [0.05108625947501766, 4.982138729512334, 75.82382841325453,
    366.7796093601508, 710.8563049989261, 597.4896124006136,
    211.68875710057213, 25.207020585802372];
  var J1_QQ = [74.23732770356752, 1056.4488603826283, 4986.410583376536,
    9562.318924047562, 7997.041604473507, 2826.1927851763908,
    336.0936078106983];
  var J1_Z1 = 14.681970642123893, J1_Z2 = 49.2184563216946;

  /**
   * @param {number} x
   * @returns {number}
   */
  function besselJ1(x) {
    var w, z, p, q;
    if (x < 0) return -besselJ1(-x);
    if (x < 1.4901161193847656e-08) return 0.5 * x;  /* below sqrt(eps) */
    if (x <= 5.0) {
      z = x * x;
      w = polevl(z, J1_RP) / p1evl(z, J1_RQ);
      return w * x * (z - J1_Z1) * (z - J1_Z2);
    }
    w = 5.0 / x;
    z = w * w;
    p = polevl(z, J1_PP) / polevl(z, J1_PQ);
    q = polevl(z, J1_QP) / p1evl(z, J1_QQ);
    if (x < 10.0) {
      var xn = x - THPIO4;
      p = p * Math.cos(xn) - w * q * Math.sin(xn);
      return p * SQRT2OPI / Math.sqrt(x);
    }
    var a = Math.SQRT1_2 * (w * q - p), b = Math.SQRT1_2 * (p + w * q);
    return (a * Math.cos(x) + b * Math.sin(x)) * SQRT2OPI / Math.sqrt(x);
  }

  /** Zeros of J0 / J1: McMahon's asymptotic expansion, refined by Newton on
   * the functions above. Every one of the 60,000 of each order the tables can
   * grow to matches scipy.special.jn_zeros to within 1 ulp; they set where
   * the quadrature's panels end and where it stops, so parity.mjs holds a
   * sample of them.
   * @param {number} order 0 or 1
   * @param {number} count
   * @returns {Float64Array}
   */
  function besselZeros(order, count) {
    var out = new Float64Array(count);
    var mu = 4.0 * order * order;
    var deriv = order === 0
      ? function (x) { return -besselJ1(x); }
      : function (x) { return besselJ0(x) - besselJ1(x) / x; };
    var f = order === 0 ? besselJ0 : besselJ1;
    for (var s = 1; s <= count; s++) {
      var beta = (s + 0.5 * order - 0.25) * Math.PI;
      var b8 = 8.0 * beta;
      var x = beta
        - (mu - 1) / b8
        - 4 * (mu - 1) * (7 * mu - 31) / (3 * b8 * b8 * b8)
        - 32 * (mu - 1) * (83 * mu * mu - 982 * mu + 3779) /
          (15 * Math.pow(b8, 5))
        - 64 * (mu - 1) * (6949 * mu * mu * mu - 153855 * mu * mu +
          1585743 * mu - 6277237) / (105 * Math.pow(b8, 7));
      for (var it = 0; it < 8; it++) {
        var d = deriv(x);
        if (!d) break;
        var dx = f(x) / d;
        x -= dx;
        if (Math.abs(dx) < 1e-14 * Math.abs(x)) break;
      }
      out[s - 1] = x;
    }
    return out;
  }

  /* Gauss-Legendre nodes and weights on [-1, 1]. Computed by Newton on the
   * Legendre polynomial, so any order is available; 8 and 10 are the ones the
   * quadrature uses and they are memoised. */
  var _glCache = {};
  /**
   * @param {number} n
   * @returns {{nodes: Float64Array, weights: Float64Array}}
   */
  function gaussLegendre(n) {
    if (_glCache[n]) return _glCache[n];
    var nodes = new Float64Array(n), weights = new Float64Array(n);
    var m = (n + 1) >> 1;
    for (var i = 0; i < m; i++) {
      var z = Math.cos(Math.PI * (i + 0.75) / (n + 0.5));
      var pp = 0, z1;
      do {
        var p1 = 1.0, p2 = 0.0;
        for (var j = 0; j < n; j++) {
          var p3 = p2;
          p2 = p1;
          p1 = ((2.0 * j + 1.0) * z * p2 - j * p3) / (j + 1);
        }
        pp = n * (z * p1 - p2) / (z * z - 1.0);
        z1 = z;
        z = z1 - p1 / pp;
      } while (Math.abs(z - z1) > 1e-15);
      nodes[i] = -z;
      nodes[n - 1 - i] = z;
      weights[i] = 2.0 / ((1.0 - z * z) * pp * pp);
      weights[n - 1 - i] = weights[i];
    }
    _glCache[n] = { nodes: nodes, weights: weights };
    return _glCache[n];
  }

  /* Exponential integral E1(x), the Theis well function W(u).
   * Series below 1, Lentz continued fraction above; ~1e-15 relative. */
  var EULER = 0.5772156649015329;
  /**
   * @param {number} x
   * @returns {number}
   */
  function exp1(x) {
    if (!(x > 0)) return x === 0 ? Infinity : NaN;
    if (x > 700) return 0;
    if (x <= 1.0) {
      var sum = 0.0, term = 1.0;
      for (var k = 1; k <= 60; k++) {
        term *= -x / k;
        sum += -term / k;
        if (Math.abs(term / k) < 1e-17 * Math.abs(sum)) break;
      }
      return -EULER - Math.log(x) + sum;
    }
    var b = x + 1.0, c = 1e300, d = 1.0 / b, h = d;
    for (var i = 1; i <= 200; i++) {
      var an = -i * i;
      b += 2.0;
      d = 1.0 / (an * d + b);
      c = b + an / c;
      var del = c * d;
      h *= del;
      if (Math.abs(del - 1.0) < 1e-16) break;
    }
    return h * Math.exp(-x);
  }

  /* --- small dense linear algebra ----------------------------------------- */

  /** Solve A x = b in place by Gaussian elimination with partial pivoting.
   * Returns null when the system is singular, which the caller treats the way
   * numpy's LinAlgError is treated: raise the damping and retry.
   * @param {number[][]} A
   * @param {ArrayLike<number>} b
   * @returns {number[]|null}
   */
  function solveLinear(A, b) {
    var n = b.length;
    var M = A.map(function (row, i) { return row.slice().concat([b[i]]); });
    for (var col = 0; col < n; col++) {
      var pivot = col;
      for (var r = col + 1; r < n; r++) {
        if (Math.abs(M[r][col]) > Math.abs(M[pivot][col])) pivot = r;
      }
      if (Math.abs(M[pivot][col]) < 1e-14) return null;
      if (pivot !== col) { var t = M[pivot]; M[pivot] = M[col]; M[col] = t; }
      var pv = M[col][col];
      for (var rr = col + 1; rr < n; rr++) {
        var factor = M[rr][col] / pv;
        if (factor === 0) continue;
        for (var cc = col; cc <= n; cc++) M[rr][cc] -= factor * M[col][cc];
      }
    }
    var x = new Array(n);
    for (var i2 = n - 1; i2 >= 0; i2--) {
      var s = M[i2][n];
      for (var j2 = i2 + 1; j2 < n; j2++) s -= M[i2][j2] * x[j2];
      x[i2] = s / M[i2][i2];
    }
    return x;
  }

  /** Inverse via Gauss-Jordan; falls back to a ridge-regularised inverse when
   * singular, standing in for numpy's pinv in the uncertainty estimate.
   * @param {number[][]} A
   * @returns {number[][]|null}
   */
  function invertMatrix(A) {
    var n = A.length;
    var M = A.map(function (row, i) {
      var aug = row.slice();
      for (var j = 0; j < n; j++) aug.push(i === j ? 1 : 0);
      return aug;
    });
    for (var col = 0; col < n; col++) {
      var pivot = col;
      for (var r = col + 1; r < n; r++) {
        if (Math.abs(M[r][col]) > Math.abs(M[pivot][col])) pivot = r;
      }
      if (Math.abs(M[pivot][col]) < 1e-13) return null;
      if (pivot !== col) { var t = M[pivot]; M[pivot] = M[col]; M[col] = t; }
      var pv = M[col][col];
      for (var cc = 0; cc < 2 * n; cc++) M[col][cc] /= pv;
      for (var rr = 0; rr < n; rr++) {
        if (rr === col) continue;
        var factor = M[rr][col];
        if (factor === 0) continue;
        for (var c2 = 0; c2 < 2 * n; c2++) M[rr][c2] -= factor * M[col][c2];
      }
    }
    return M.map(function (row) { return row.slice(n); });
  }

  /* analysis.py SLOPE_ROUNDING_M: a fitted slope this close to zero, in
   * metres per log cycle, is rounding in the fit and not a direction. */
  var SLOPE_ROUNDING_M = 1e-9;

  /* analysis.py READING_RESOLUTION_M: what a dipper reads to. A drawdown
   * whose fitted line moves by less than this across all its readings cannot
   * be told from one that does not move. */
  var READING_RESOLUTION_M = 0.01;

  /* analysis.py THEIS_STORATIVITY_FLOOR: a Theis storativity below this has
   * not been fitted; the optimiser has run down a valley towards underflow. */
  var THEIS_STORATIVITY_FLOOR = 1e-280;

  /** Least squares straight line with r^2, matching numpy lstsq + the r^2 the
   * Python computes alongside it.
   * @param {ArrayLike<number>} x
   * @param {ArrayLike<number>} y
   */
  function lineFit(x, y) {
    var n = x.length;
    var sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (var i = 0; i < n; i++) { sx += x[i]; sy += y[i]; sxx += x[i] * x[i]; sxy += x[i] * y[i]; }
    var den = n * sxx - sx * sx;
    var slope = den === 0 ? 0 : (n * sxy - sx * sy) / den;
    var intercept = (sy - slope * sx) / n;
    var ybar = sy / n, ssTot = 0, ssRes = 0;
    for (var j = 0; j < n; j++) {
      ssTot += (y[j] - ybar) * (y[j] - ybar);
      var e = y[j] - (slope * x[j] + intercept);
      ssRes += e * e;
    }
    /* When y is constant to machine precision, ssTot and ssRes are both
     * rounding noise and their ratio is meaningless - numpy's lstsq and a
     * closed-form fit disagree wildly there. A constant series is fitted
     * perfectly by a constant, so report that rather than a random number. */
    var degenerate = ssTot <= 1e-20 * n * ybar * ybar;
    return {
      slope: slope, intercept: intercept,
      r2: (ssTot > 0 && !degenerate) ? 1.0 - ssRes / ssTot : 1.0,
    };
  }

  /** Linear interpolation on a monotonically increasing xp, numpy.interp
   * semantics: values outside the range clamp to the end points.
   * @param {number} x
   * @param {ArrayLike<number>} xp
   * @param {ArrayLike<number>} fp
   * @returns {number}
   */
  function interp(x, xp, fp) {
    var n = xp.length;
    /* NaN stays NaN, as in numpy, which gives a lone point's value for any x
     * at all; without this a NaN at a repeated first abscissa fell through
     * to fp[0] */
    if (Number.isNaN(x) && n > 1) return x;
    /* strictly below: at the first abscissa itself np.interp reads on to the
     * last point there, so where the first spacing was read twice the
     * inversion's starting model takes the second reading, as Python's does */
    if (x < xp[0]) return fp[0];
    if (x >= xp[n - 1]) return fp[n - 1];
    var lo = 0, hi = n - 1;
    while (hi - lo > 1) {
      var mid = (lo + hi) >> 1;
      if (xp[mid] <= x) lo = mid; else hi = mid;
    }
    var span = xp[hi] - xp[lo];
    if (span === 0) return fp[lo];
    /* at an abscissa itself numpy returns its value, whatever the slope */
    if (xp[lo] === x) return fp[lo];
    /* numpy's order of operations, slope first, so the last bit is numpy's */
    var slope = (fp[hi] - fp[lo]) / span;
    var value = slope * (x - xp[lo]) + fp[lo];
    /* and numpy's fallback where that is NaN, an infinite abscissa or
     * value: from the right-hand point, then the value itself where both
     * ends hold it. Without it a reading at AB/2 = 0, log 0 = -Infinity,
     * made every starting model's top layer NaN. */
    if (Number.isNaN(value)) {
      value = slope * (x - xp[hi]) + fp[hi];
      if (Number.isNaN(value) && fp[lo] === fp[hi]) value = fp[lo];
    }
    return value;
  }

  /**
   * @param {number} a
   * @param {number} b
   * @param {number} n
   * @returns {number[]}
   */
  function geomspace(a, b, n) {
    if (n <= 1) return [a];
    var out = [], la = Math.log(a), lb = Math.log(b);
    for (var i = 0; i < n; i++) out.push(Math.exp(la + (lb - la) * i / (n - 1)));
    return out;
  }

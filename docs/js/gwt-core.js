/* gwt-core.js - the groundwater science engine, in the browser.
 *
 * A direct port of the `groundwater` Python package: the same formulas, the
 * same thresholds, the same deliberate field-data behaviours. Nothing here
 * touches the DOM, so it also runs inside a Web Worker (the VES inversion
 * does) and can be unit-tested headlessly.
 *
 * Units, held to throughout:
 *   depth, thickness, spacing      m
 *   resistivity                    ohm-m
 *   discharge                      m3/h on the sheet, m3/day inside the fits
 *   transmissivity                 m2/day
 *   time                           minutes on the sheet, days inside the fits
 *   concentrations                 mg/L unless the parameter says otherwise
 */
(function (global) {
  'use strict';

  var GWT = global.GWT || (global.GWT = {});
  var C = GWT.core = {};

  /* ================================================================== config
   * groundwater/config.py. Every value is overridable per project, which is
   * what the Settings page edits.
   */

  var DEFAULT_CONFIG = {
    style: {
      accent_color: '#1F5C8B',
      secondary_color: '#C15A2A',
      neutral_color: '#4D4D4D',
      background: '#FFFFFF',
      font_name: 'Calibri',
      base_font_size_pt: 11.0,
      figure_width_in: 6.3,
      organisation: '',
      organisation_details: '',
    },
    ves: {
      max_layers: 4,
      min_layers: 2,
      target_fit_percent: 10.0,
      parsimony_max_error_ratio: 2.0,
      damping: 0.02,
      max_iterations: 60,
      fresh_basement_min_rho: 3000.0,
      fractured_zone_rho: [20.0, 800.0],
      clay_max_rho: 20.0,
      laterite_min_rho: 800.0,
      max_drilling_margin_m: 10.0,
      round_drilling_depth_to_m: 5.0,
    },
    pumping: {
      safety_factor: 1.5,
      design_period_days: 365.0,
      available_drawdown_fraction: 0.7,
      pump_clearance_above_screen_m: 1.0,
      pump_submergence_min_m: 3.0,
      seasonal_allowance_m: 2.0,
      cooper_jacob_u_max: 0.05,
    },
    design: {
      borehole_diameter_in: 6.5,
      casing_diameter_in: 5.0,
      casing_material: 'uPVC',
      screen_slot_mm: 0.75,
      screen_length_default_m: 9.0,
      sanitary_seal_depth_m: 3.0,
      grout_min_depth_m: 15.0,
      gravel_pack_above_top_screen_m: 2.0,
      gravel_pack_material: 'well sorted siliceous gravel, 2-4 mm',
      sump_length_m: 2.0,
      stickup_m: 0.5,
      min_screen_below_swl_m: 5.0,
      apron_note: 'concrete apron with drainage channel and soakaway',
    },
  };

  function defaultConfig() {
    return JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  }

  /* Merge a partial override over the defaults, section by section. */
  function withConfig(overrides) {
    var cfg = defaultConfig();
    if (!overrides) return cfg;
    ['style', 'ves', 'pumping', 'design'].forEach(function (section) {
      var over = overrides[section];
      if (!over) return;
      Object.keys(over).forEach(function (key) {
        if (key in cfg[section] && over[key] !== null && over[key] !== undefined) {
          cfg[section][key] = over[key];
        }
      });
    });
    return cfg;
  }

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
   * Abramowitz & Stegun 9.4 polynomial approximations, |error| < 1e-8 in the
   * small-argument branch and < 1e-8 relative in the asymptotic branch. The
   * quadrature only needs the integrand to ~1e-6, and the forward model is
   * checked against the analytic two-layer image series in the test harness.
   */

  function besselJ0(x) {
    var ax = Math.abs(x), y, z, xx, p, q;
    if (ax < 8.0) {
      y = x * x;
      p = 57568490574.0 + y * (-13362590354.0 + y * (651619640.7 +
          y * (-11214424.18 + y * (77392.33017 + y * (-184.9052456)))));
      q = 57568490411.0 + y * (1029532985.0 + y * (9494680.718 +
          y * (59272.64853 + y * (267.8532712 + y))));
      return p / q;
    }
    z = 8.0 / ax;
    y = z * z;
    xx = ax - 0.785398164;
    p = 1.0 + y * (-0.1098628627e-2 + y * (0.2734510407e-4 +
        y * (-0.2073370639e-5 + y * 0.2093887211e-6)));
    q = -0.1562499995e-1 + y * (0.1430488765e-3 + y * (-0.6911147651e-5 +
        y * (0.7621095161e-6 + y * (-0.934935152e-7))));
    return Math.sqrt(0.636619772 / ax) * (Math.cos(xx) * p - z * Math.sin(xx) * q);
  }

  function besselJ1(x) {
    var ax = Math.abs(x), y, z, xx, p, q, ans;
    if (ax < 8.0) {
      y = x * x;
      p = x * (72362614232.0 + y * (-7895059235.0 + y * (242396853.1 +
          y * (-2972611.439 + y * (15704.48260 + y * (-30.16036606))))));
      q = 144725228442.0 + y * (2300535178.0 + y * (18583304.74 +
          y * (99447.43394 + y * (376.9991397 + y))));
      return p / q;
    }
    z = 8.0 / ax;
    y = z * z;
    xx = ax - 2.356194491;
    p = 1.0 + y * (0.183105e-2 + y * (-0.3516396496e-4 +
        y * (0.2457520174e-5 + y * (-0.240337019e-6))));
    q = 0.04687499995 + y * (-0.2002690873e-3 + y * (0.8449199096e-5 +
        y * (-0.88228987e-6 + y * 0.105787412e-6)));
    ans = Math.sqrt(0.636619772 / ax) * (Math.cos(xx) * p - z * Math.sin(xx) * q);
    return x < 0.0 ? -ans : ans;
  }

  /* Zeros of J0 / J1: McMahon's asymptotic expansion, refined by Newton.
   * Matches scipy.special.jn_zeros to better than 1e-10. */
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

  /* Solve A x = b in place by Gaussian elimination with partial pivoting.
   * Returns null when the system is singular, which the caller treats the way
   * numpy's LinAlgError is treated: raise the damping and retry. */
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

  /* Inverse via Gauss-Jordan; falls back to a ridge-regularised inverse when
   * singular, standing in for numpy's pinv in the uncertainty estimate. */
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

  /* Least squares straight line with r^2, matching numpy lstsq + the r^2 the
   * Python computes alongside it. */
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

  /* Linear interpolation on a monotonically increasing xp, numpy.interp
   * semantics: values outside the range clamp to the end points. */
  function interp(x, xp, fp) {
    var n = xp.length;
    if (x <= xp[0]) return fp[0];
    if (x >= xp[n - 1]) return fp[n - 1];
    var lo = 0, hi = n - 1;
    while (hi - lo > 1) {
      var mid = (lo + hi) >> 1;
      if (xp[mid] <= x) lo = mid; else hi = mid;
    }
    var span = xp[hi] - xp[lo];
    if (span === 0) return fp[lo];
    return fp[lo] + (fp[hi] - fp[lo]) * (x - xp[lo]) / span;
  }

  function geomspace(a, b, n) {
    if (n <= 1) return [a];
    var out = [], la = Math.log(a), lb = Math.log(b);
    for (var i = 0; i < n; i++) out.push(Math.exp(la + (lb - la) * i / (n - 1)));
    return out;
  }

  /* ======================================================== electrode arrays
   * groundwater/ves/arrays.py. mn is always the FULL potential spacing MN,
   * matching the field sheets, not MN/2.
   */

  function geometricFactor(arrayType, spacings) {
    var kind = String(arrayType || '').trim().toLowerCase();
    if (kind.indexOf('schlum') === 0) {
      var L = spacings.ab2, b = spacings.mn / 2.0;
      if (!(b > 0) || !(L > b)) {
        throw new Error('Require 0 < MN/2 < AB/2 for Schlumberger');
      }
      return Math.PI * (L * L - b * b) / (2.0 * b);
    }
    if (kind.indexOf('wenner') === 0) return 2.0 * Math.PI * spacings.a;
    if (kind.indexOf('dipole') === 0) {
      var n = spacings.n;
      return Math.PI * n * (n + 1) * (n + 2) * spacings.a;
    }
    if (kind.indexOf('pole-pole') === 0 || kind.indexOf('pole pole') === 0) {
      return 2.0 * Math.PI * spacings.a;
    }
    throw new Error('Unknown array type: ' + arrayType);
  }

  function apparentResistivity(arrayType, resistanceOhm, spacings) {
    return geometricFactor(arrayType, spacings) * resistanceOhm;
  }

  /* ================================================= 1D layered forward model
   * groundwater/ves/forward.py.
   *
   * rho_a comes from the resistivity transform T(lambda) (Koefoed recurrence)
   * through a Hankel transform, evaluated by direct quadrature on a hybrid
   * logarithmic + linear abscissa after subtracting the half-space asymptote
   * (T -> rho_1 for large lambda), which makes the integrand decay
   * exponentially. No tabulated digital filter coefficients are involved.
   */

  var N_ZEROS = 1200;
  var MAX_ZEROS = 60000;
  var MIN_DECAY_H = 0.02;

  function buildTables(order, nZeros) {
    var zeros = besselZeros(order, nZeros);
    var bessel = order === 0 ? besselJ0 : besselJ1;

    /* section 1: 14 log-spaced panels from 1e-6 to the first zero, GL-8 */
    var gl8 = gaussLegendre(8);
    var edges = geomspace(1e-6, zeros[0], 15);
    var s1n = new Float64Array(14 * 8), s1w = new Float64Array(14 * 8), at = 0;
    for (var p = 0; p < 14; p++) {
      var lo = edges[p], hi = edges[p + 1];
      var mid = 0.5 * (lo + hi), half = 0.5 * (hi - lo);
      for (var k = 0; k < 8; k++) {
        var x = mid + half * gl8.nodes[k];
        s1n[at] = x;
        s1w[at] = half * gl8.weights[k] * bessel(x);
        at++;
      }
    }

    /* section 2: GL-10 between consecutive zeros */
    var gl10 = gaussLegendre(10);
    var nPanels = nZeros - 1;
    var s2n = new Float64Array(nPanels * 10), s2w = new Float64Array(nPanels * 10);
    var ends = new Float64Array(nPanels);
    var prev = zeros[0], idx = 0;
    for (var q = 1; q < nZeros; q++) {
      var top = zeros[q];
      var mid2 = 0.5 * (prev + top), half2 = 0.5 * (top - prev);
      for (var k2 = 0; k2 < 10; k2++) {
        var x2 = mid2 + half2 * gl10.nodes[k2];
        s2n[idx] = x2;
        s2w[idx] = half2 * gl10.weights[k2] * bessel(x2);
        idx++;
      }
      ends[q - 1] = top;
      prev = top;
    }
    return { s1n: s1n, s1w: s1w, s2n: s2n, s2w: s2w, ends: ends };
  }

  var TABLES = {};
  function tableFor(order, xStop) {
    var table = TABLES[order];
    if (!table) {
      table = TABLES[order] = buildTables(order, N_ZEROS);
    }
    if (table.ends[table.ends.length - 1] >= xStop ||
        table.ends.length + 1 >= MAX_ZEROS) {
      return table;
    }
    /* Grow rather than truncate. Cutting the integral part-way through an
     * oscillation of J1 leaves a large spurious residue: at AB/2 = 1000 m over
     * a 0.5 m layer the model returns 574 ohm-m instead of 30, and the
     * inversion does explore thin layers. */
    var needed = Math.min(Math.floor(xStop / Math.PI) + 32, MAX_ZEROS);
    needed = Math.min(Math.max(needed, 2 * (table.ends.length + 1)), MAX_ZEROS);
    table = TABLES[order] = buildTables(order, needed);
    return table;
  }

  function searchSorted(arr, value, upTo) {
    var lo = 0, hi = upTo;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (arr[mid] < value) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  /* T(lambda): stable downward Koefoed/Pekeris recurrence from the half space.
   *   T_n = rho_n
   *   T_i = (T_{i+1} + rho_i tanh(lam h_i)) / (1 + T_{i+1} tanh(lam h_i) / rho_i)
   * Written scalar and branchy on purpose: tanh saturates for lam*h above ~20,
   * which is most of the abscissa, and skipping the call there is most of the
   * inversion's speed. */
  function resistivityTransform(lam, rho, h) {
    var nH = h.length;
    var T = rho[nH];
    for (var i = nH - 1; i >= 0; i--) {
      var z = lam * h[i];
      var th = z > 19 ? 1.0 : (z < -19 ? -1.0 : Math.tanh(z));
      T = (T + rho[i] * th) / (1.0 + T * th / rho[i]);
    }
    return T;
  }

  /* Int_0^inf g(x) J_order(x) dx for smooth g decaying like exp(-x/xDecay). */
  function hankelIntegral(g, order, xDecay) {
    var xStop = 18.0 * Math.max(xDecay, 1.0);
    var t = tableFor(order, xStop);
    var acc = 0.0, i;
    for (i = 0; i < t.s1n.length; i++) acc += g(t.s1n[i]) * t.s1w[i];
    var nPanels = searchSorted(t.ends, xStop, t.ends.length) + 1;
    nPanels = Math.min(Math.max(nPanels, 8), t.ends.length);
    var k = nPanels * 10;
    for (i = 0; i < k; i++) acc += g(t.s2n[i]) * t.s2w[i];
    return acc;
  }

  /* Ideal (gradient, MN -> 0) Schlumberger apparent resistivity. */
  function forwardSchlumberger(rho, h, ab2) {
    var hMin = h.length ? arrMin(h) : 1.0;
    var decayH = 2.0 * Math.max(hMin, MIN_DECAY_H);
    var out = new Float64Array(ab2.length);
    for (var i = 0; i < ab2.length; i++) {
      var L = ab2[i];
      /* substitute x = lambda L: the L^2 prefactor cancels against the 1/L^2
       * from the substitution, leaving
       *   rho_a = rho1 + Int (T(x/L) - rho1) J1(x) x dx */
      var g = (function (LL) {
        return function (x) {
          return (resistivityTransform(x / LL, rho, h) - rho[0]) * x;
        };
      }(L));
      out[i] = rho[0] + hankelIntegral(g, 1, L / decayH);
    }
    return out;
  }

  /* F(r) = Int T(lam) J0(lam r) dlam, the surface potential kernel. */
  function potentialIntegral(rho, h, r, hMin) {
    var g = function (x) { return resistivityTransform(x / r, rho, h) - rho[0]; };
    return (rho[0] + hankelIntegral(g, 0, r / (2.0 * Math.max(hMin, MIN_DECAY_H)))) / r;
  }

  /* What the instrument actually measures at each (AB/2, MN) pair, including
   * the small jumps at segment changes. */
  function forwardSchlumbergerFiniteMn(rho, h, ab2, mn) {
    var hMin = h.length ? arrMin(h) : 1.0;
    var out = new Float64Array(ab2.length);
    for (var i = 0; i < ab2.length; i++) {
      var L = ab2[i], b = mn[i] / 2.0;
      if (!isFinite(b) || b <= 0 || b >= L) {
        out[i] = forwardSchlumberger(rho, h, [L])[0];
        continue;
      }
      var fIn = potentialIntegral(rho, h, L - b, hMin);
      var fOut = potentialIntegral(rho, h, L + b, hMin);
      out[i] = (L * L - b * b) / (2.0 * b) * (fIn - fOut);
    }
    return out;
  }

  function forwardWenner(rho, h, a) {
    var hMin = h.length ? arrMin(h) : 1.0;
    var out = new Float64Array(a.length);
    for (var i = 0; i < a.length; i++) {
      var s = a[i];
      var f1 = potentialIntegral(rho, h, s, hMin);
      var f2 = potentialIntegral(rho, h, 2.0 * s, hMin);
      out[i] = 2.0 * s * (f1 - f2);
    }
    return out;
  }

  function forwardCurve(rho, h, ab2, arrayType) {
    return String(arrayType || '').indexOf('wenner') === 0
      ? forwardWenner(rho, h, ab2)
      : forwardSchlumberger(rho, h, ab2);
  }

  /* Analytic two-layer ideal Schlumberger curve from image theory, used to
   * validate the numerical Hankel evaluation:
   *   rho_a(L) = rho1 [1 + 2 sum_n k^n L^3 / (L^2 + (2 n h)^2)^(3/2)] */
  function twoLayerSchlumbergerSeries(rho1, rho2, h, ab2, nTerms) {
    var terms = nTerms || 4000;
    var k = (rho2 - rho1) / (rho2 + rho1);
    var out = new Float64Array(ab2.length);
    for (var i = 0; i < ab2.length; i++) {
      var L = ab2[i], sum = 0.0, kn = 1.0;
      for (var n = 1; n <= terms; n++) {
        kn *= k;
        var d = L * L + (2.0 * n * h) * (2.0 * n * h);
        sum += kn * L * L * L / (d * Math.sqrt(d));
        if (Math.abs(kn) < 1e-18) break;
      }
      out[i] = rho1 * (1.0 + 2.0 * sum);
    }
    return out;
  }

  /* ======================================================= sounding segments
   * groundwater/ves/splice.py. At MN segment changes the same AB/2 is read
   * with the old and the new MN and the two differ slightly. Both readings are
   * kept in the raw data; "merge" keeps every segment at its measured level
   * and merges duplicate AB/2 by geometric mean, which honours the absolute
   * values of the deep branch that drive the aquifer interpretation.
   */

  /* A new segment starts at each change of MN. A blank MN continues the
   * current segment rather than starting one, so a single missing cell does
   * not inject a spurious one-point segment and an absent MN column does not
   * split every reading into its own. */
  function soundingSegments(sounding) {
    var segments = [], lastMn = null;
    for (var i = 0; i < sounding.ab2.length; i++) {
      var raw = sounding.mn ? sounding.mn[i] : null;
      var blank = raw === null || raw === undefined || !isFinite(raw);
      var newSegment = !segments.length ||
        (!blank && lastMn !== null && raw !== lastMn);
      if (newSegment) segments.push([]);
      segments[segments.length - 1].push(i);
      if (!blank) lastMn = raw;
    }
    return segments;
  }

  function spliceSegments(sounding, mode) {
    var m = mode || 'merge';
    var segments = soundingSegments(sounding);
    var i, j;
    if (segments.length <= 1) {
      var order = sounding.ab2.map(function (v, k) { return k; })
        .sort(function (a, b) { return sounding.ab2[a] - sounding.ab2[b] || a - b; });
      return {
        ab2: order.map(function (k) { return sounding.ab2[k]; }),
        rho: order.map(function (k) { return sounding.rho_app[k]; }),
        shifts: [1.0],
      };
    }

    var shifts;
    if (m === 'merge') {
      shifts = segments.map(function () { return 1.0; });
    } else {
      shifts = [1.0];
      for (i = 1; i < segments.length; i++) {
        var prevIdx = segments[i - 1], curIdx = segments[i];
        var prevAb2 = prevIdx.map(function (k) { return sounding.ab2[k]; });
        var curAb2 = curIdx.map(function (k) { return sounding.ab2[k]; });
        var common = prevAb2.filter(function (v) { return curAb2.indexOf(v) >= 0; })
          .filter(function (v, k, a) { return a.indexOf(v) === k; });
        if (!common.length) { shifts.push(shifts[shifts.length - 1]); continue; }
        var logRatios = common.map(function (value) {
          var rPrev = arrMean(prevIdx.filter(function (k) { return sounding.ab2[k] === value; })
            .map(function (k) { return sounding.rho_app[k]; }));
          var rCur = arrMean(curIdx.filter(function (k) { return sounding.ab2[k] === value; })
            .map(function (k) { return sounding.rho_app[k]; }));
          return Math.log(rPrev / rCur);
        });
        shifts.push(shifts[i - 1] * Math.exp(arrMean(logRatios)));
      }
      if (m === 'last') {
        var anchor = shifts[shifts.length - 1];
        shifts = shifts.map(function (s) { return s / anchor; });
      }
    }

    var ab2All = [], rhoAll = [];
    segments.forEach(function (idx, si) {
      idx.forEach(function (k) {
        ab2All.push(sounding.ab2[k]);
        rhoAll.push(sounding.rho_app[k] * shifts[si]);
      });
    });

    /* merge duplicates by geometric mean */
    var unique = ab2All.slice().sort(function (a, b) { return a - b; })
      .filter(function (v, k, a) { return k === 0 || v !== a[k - 1]; });
    var merged = unique.map(function (u) {
      var logs = [];
      for (var k = 0; k < ab2All.length; k++) {
        if (ab2All[k] === u) logs.push(Math.log(rhoAll[k]));
      }
      return Math.exp(arrMean(logs));
    });
    return { ab2: unique, rho: merged, shifts: shifts };
  }

  /* ============================================================== inversion
   * groundwater/ves/inversion.py. Damped least squares (Levenberg-Marquardt)
   * on the logarithms of resistivity and thickness, misfit on log rho_a.
   * The reported error matches the IPI2Win ERR quantity.
   */

  var RHO_BOUNDS = [0.5, 200000.0];
  var H_BOUNDS = [0.2, 300.0];

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

  function invertModel(ab2, rhoApp, rho0, h0, arrayType, damping, maxIterations) {
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

    var cur = residuals(theta);
    var res = cur.res, calc = cur.calc, cost = costOf(res);
    var lam = damping, iterations = 0, converged = false;

    for (iterations = 1; iterations <= maxIterations; iterations++) {
      /* numerical Jacobian in log space */
      var J = [];
      for (var i2 = 0; i2 < m; i2++) J.push(new Float64Array(p));
      var step = 1e-4;
      for (var j = 0; j < p; j++) {
        var tp = Float64Array.from(theta);
        tp[j] += step;
        var rp = residuals(tp).res;
        for (var i3 = 0; i3 < m; i3++) J[i3][j] = (rp[i3] - res[i3]) / step;
      }

      var JtJ = [], g = new Float64Array(p);
      for (var a = 0; a < p; a++) {
        JtJ.push(new Float64Array(p));
        var ga = 0;
        for (var r = 0; r < m; r++) ga += J[r][a] * res[r];
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
      if (!improved) { converged = true; break; }
      if (cost < 1e-10) { converged = true; break; }
    }

    var final = unpackTheta(theta, nLayers);
    var err = fitErrorPercent(rhoApp, calc);
    return {
      rho: Array.from(final.rho),
      h: Array.from(final.h),
      calc: Array.from(calc),
      err: err,
      iterations: iterations,
      converged: converged,
    };
  }

  /* Deterministic starting models read off the smoothed field curve.
   * Thicknesses grow logarithmically over the depth range the spacings cover
   * (depth of investigation taken as AB/2 x depth_factor); two depth-scale
   * variants bracket it. */
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

  /* Linearised 1-sigma multiplicative uncertainty per model parameter: the
   * covariance is sigma^2 (J'J)^-1, and because the parameters are logarithms,
   * exp(sigma_i) is the factor on each resistivity and thickness. Factors near
   * 1 are well resolved; large factors mark equivalence and suppression. */
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
    var dof = Math.max(m - p, 1);
    var ss = 0;
    for (var k = 0; k < m; k++) ss += res[k] * res[k];
    var sigma2 = ss / dof;
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
      factors.push(Math.min(Math.exp(Math.sqrt(variance)), 10.0));
    }
    return { rho: factors.slice(0, nLayers), h: factors.slice(nLayers) };
  }

  /* Full search: layer count from min_layers to max_layers, two starts each,
   * keeping the simplest model that reaches the target fit.
   *
   * onProgress(fraction, label) is called between trials so the page can show
   * where the inversion has got to; it is the only non-pure part of this. */
  function invertSounding(sounding, options) {
    var opts = options || {};
    var cfg = (opts.config || defaultConfig()).ves;
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

    var ab2 = [], rhoApp = [];
    for (var i = 0; i < spliced.ab2.length; i++) {
      var value = spliced.rho[i];
      if (isFinite(value) && value > 0) { ab2.push(spliced.ab2[i]); rhoApp.push(value); }
    }
    if (ab2.length < 4) throw new Error('Not enough readings to invert');

    var candidates = [], trials = [];

    if (opts.initialModel) {
      var seeded = invertModel(ab2, rhoApp, opts.initialModel.resistivities,
        opts.initialModel.thicknesses, arrayType, cfg.damping, cfg.max_iterations);
      candidates.push(seeded);
      trials.push([seeded.rho.length, seeded.err]);
    } else {
      var layerRange = opts.nLayers
        ? [opts.nLayers]
        : (function () {
            var out = [];
            for (var n = cfg.min_layers; n <= cfg.max_layers; n++) out.push(n);
            return out;
          }());
      for (var li = 0; li < layerRange.length; li++) {
        var n2 = layerRange[li];
        var bestForN = null;
        var starts = startingModels(ab2, rhoApp, n2);
        for (var si = 0; si < starts.length; si++) {
          var result = invertModel(ab2, rhoApp, starts[si].rho0, starts[si].h0,
            arrayType, cfg.damping, cfg.max_iterations);
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
          if (bestForN.err <= cfg.target_fit_percent / 2) break;
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
        if (candidates[ci].err <= 1.15 * bestErr) { chosen = candidates[ci]; break; }
      }
    }
    if (!chosen) {
      chosen = candidates.reduce(function (a, b) { return a.err <= b.err ? a : b; });
    }

    var uncertainty = parameterUncertainty(ab2, rhoApp, chosen.rho, chosen.h, arrayType);
    return {
      model: layeredModel(chosen.rho, chosen.h, {
        fit_error_percent: chosen.err,
        method: 'damped-lsq',
        sounding_id: sounding.sounding_id || '',
      }),
      ab2: ab2,
      rho_obs: rhoApp,
      rho_calc: chosen.calc,
      fit_error_percent: chosen.err,
      n_iterations: chosen.iterations,
      converged: chosen.converged,
      trials: trials,
      shifts: spliced.shifts,
      rho_uncertainty_factor: uncertainty.rho,
      h_uncertainty_factor: uncertainty.h,
    };
  }

  /* A layered model with the derived depth arrays the rest of the code reads. */
  function layeredModel(resistivities, thicknesses, extra) {
    var rho = Array.prototype.slice.call(resistivities);
    var h = Array.prototype.slice.call(thicknesses);
    var tops = [0.0], bottoms = [];
    for (var i = 0; i < h.length; i++) {
      bottoms.push(tops[i] + h[i]);
      tops.push(tops[i] + h[i]);
    }
    bottoms.push(Infinity);
    var model = {
      resistivities: rho,
      thicknesses: h,
      n_layers: rho.length,
      depths_top: tops.slice(0, rho.length),
      depths_bottom: bottoms,
      fit_error_percent: null,
      method: '',
      sounding_id: '',
    };
    return Object.assign(model, extra || {});
  }

  /* =========================================================== curve type
   * groundwater/ves/classify.py
   */

  var TRIPLET = { '10': 'K', '01': 'H', '11': 'A', '00': 'Q' };

  function classifyCurve(model) {
    var rho = model.resistivities;
    if (rho.length < 2) return 'uniform';
    if (rho.length === 2) {
      return rho[1] > rho[0] ? '2-layer ascending' : '2-layer descending';
    }
    var letters = '';
    for (var i = 0; i < rho.length - 2; i++) {
      var up1 = rho[i + 1] > rho[i] ? '1' : '0';
      var up2 = rho[i + 2] > rho[i + 1] ? '1' : '0';
      letters += TRIPLET[up1 + up2];
    }
    return letters;
  }

  var CURVE_DESCRIPTIONS = {
    H: 'a conductive layer between two more resistive layers, the classical ' +
       'signature of a saturated weathered zone above fresh basement',
    K: 'a resistive layer between two more conductive layers, often dry ' +
       'laterite or duricrust over a conductive saprolite',
    A: 'resistivity increasing with depth, typical of progressively less ' +
       'weathered rock towards fresh basement',
    Q: 'resistivity decreasing with depth, typical of deepening weathering ' +
       'or increasing saturation with depth',
  };

  function describeCurveType(curveType) {
    if (curveType.indexOf('2-layer') === 0) {
      if (curveType.indexOf('descending') >= 0) {
        return 'a two layer response with resistivity decreasing at depth, ' +
          'consistent with weathered or fractured, possibly water bearing ' +
          'rock beneath a resistive surface layer';
      }
      return 'a two layer response with resistivity increasing at depth, ' +
        'consistent with more competent rock beneath the surface layer';
    }
    var parts = ['type ' + curveType], seen = [];
    for (var i = 0; i < curveType.length; i++) {
      var letter = curveType.charAt(i);
      if (CURVE_DESCRIPTIONS[letter] && seen.indexOf(letter) < 0) {
        seen.push(letter);
        parts.push(CURVE_DESCRIPTIONS[letter]);
      }
    }
    return parts.join('; ');
  }

  /* ==================================================== interpretation rules
   * groundwater/ves/interpret.py. Targets crystalline basement terrain: a
   * lateritic or clayey cover, saprolite, a weathered/fractured zone that
   * forms the main aquifer, and fresh basement at depth.
   */

  function unitLabel(rho, isTop, isBottom, cfg) {
    var lo = cfg.fractured_zone_rho[0], hi = cfg.fractured_zone_rho[1];
    if (isTop) {
      if (rho >= cfg.laterite_min_rho) return ['dry lateritic topsoil / duricrust', false];
      if (rho >= hi) return ['compact laterite / dry overburden', false];
      if (rho <= cfg.clay_max_rho) return ['clayey topsoil', false];
      return ['topsoil / laterite', false];
    }
    if (rho >= cfg.fresh_basement_min_rho) return ['fresh basement', false];
    if (rho >= hi) {
      if (isBottom) {
        return ['slightly weathered or fractured bedrock (limited water potential)', false];
      }
      return ['compact or dry weathered rock (regolith)', false];
    }
    if (rho <= cfg.clay_max_rho) return ['clay rich saprolite (low permeability)', false];
    if (isBottom) {
      return ['fractured bedrock, low resistivity indicative of groundwater in fractures', true];
    }
    return ['weathered / fractured zone, potentially water bearing when saturated', true];
  }

  function darZarrouk(layers) {
    var s = 0, t = 0;
    layers.forEach(function (layer) {
      if (layer.thickness_m === null || layer.rho <= 0) return;
      s += layer.thickness_m / layer.rho;
      t += layer.thickness_m * layer.rho;
    });
    return { s: s, t: t };
  }

  /* Only the material above the shallowest water-bearing layer counts as
   * protective cover, so a thick or conductive aquifer is not credited as its
   * own contamination barrier. The top comes from the layers, not the reported
   * water zones: those are floored at 3 m by the vadose rule. */
  function coverConductance(layers) {
    var aquiferTop = Infinity;
    layers.forEach(function (layer) {
      if (layer.water_bearing && layer.top_m < aquiferTop) aquiferTop = layer.top_m;
    });
    var s = 0;
    layers.forEach(function (layer) {
      if (layer.thickness_m === null || layer.rho <= 0) return;
      var thickness = Math.max(0.0, Math.min(layer.bottom_m, aquiferTop) - layer.top_m);
      if (thickness > 0) s += thickness / layer.rho;
    });
    return s;
  }

  function protectiveCapacity(s) {
    if (s < 0.1) return 'poor';
    if (s < 0.2) return 'weak';
    if (s < 0.7) return 'moderate';
    if (s < 5.0) return 'good';
    return 'very good';
  }

  function zoneRho(layers, top, bottom) {
    var total = 0, acc = 0;
    layers.forEach(function (layer) {
      var lo = Math.max(layer.top_m, top);
      var hi = Math.min(isFinite(layer.bottom_m) ? layer.bottom_m : bottom, bottom);
      if (hi > lo) { acc += Math.log(layer.rho) * (hi - lo); total += hi - lo; }
    });
    return total > 0 ? Math.exp(acc / total) : 100.0;
  }

  function interpretModel(sounding, model, config) {
    var cfg = (config || defaultConfig()).ves;
    var rho = model.resistivities;
    var tops = model.depths_top, bottoms = model.depths_bottom;
    var n = model.n_layers, i;

    var investigation;
    if (sounding && sounding.ab2 && sounding.ab2.length) {
      investigation = arrMax(sounding.ab2);
    } else if (n > 1) {
      investigation = bottoms[n - 2] * 2 + 20;
    } else {
      /* A bare half space with no sounding carries no depth scale at all;
       * zero is the honest answer - nothing was resolved, nothing recommended. */
      investigation = 0.0;
    }

    var layers = [];
    for (i = 0; i < n; i++) {
      var labelled = unitLabel(rho[i], i === 0, i === n - 1, cfg);
      layers.push({
        number: i + 1,
        rho: rho[i],
        thickness_m: i < n - 1 ? model.thicknesses[i] : null,
        top_m: tops[i],
        bottom_m: bottoms[i],
        unit: labelled[0],
        water_bearing: labelled[1],
      });
    }

    /* water zones: the top few metres are vadose, so a zone starts at 3 m */
    var zones = [];
    layers.forEach(function (layer) {
      if (!layer.water_bearing) return;
      var top = Math.max(layer.top_m, 3.0);
      var bottom = isFinite(layer.bottom_m) ? layer.bottom_m : investigation;
      if (bottom - top >= 1.0) zones.push([pyRound(top), pyRound(bottom)]);
    });
    zones.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var merged = [];
    zones.forEach(function (zone) {
      var last = merged[merged.length - 1];
      if (last && zone[0] <= last[1] + 1) last[1] = Math.max(last[1], zone[1]);
      else merged.push([zone[0], zone[1]]);
    });
    zones = merged;

    var depthToBasement = null;
    for (i = 0; i < layers.length; i++) {
      if (layers[i].rho >= cfg.fresh_basement_min_rho && layers[i].top_m > 0) {
        depthToBasement = layers[i].top_m;
        break;
      }
    }
    if (depthToBasement === null &&
        layers[layers.length - 1].rho >= cfg.fractured_zone_rho[1]) {
      depthToBasement = layers[layers.length - 1].top_m;
    }

    var aquiferThickness = zones.reduce(function (a, z) { return a + (z[1] - z[0]); }, 0);

    /* Recommended maximum drilling depth: deepest target zone plus a margin,
     * never past the depth the sounding actually investigated. Round up to the
     * step and re-apply the cap - rounding after the cap could push the
     * recommendation past the resolved depth. */
    var deepest = zones.length
      ? zones[zones.length - 1][1] + cfg.max_drilling_margin_m
      : investigation;
    var step = cfg.round_drilling_depth_to_m;
    var maxDepth = Math.ceil(Math.min(deepest, investigation) / step) * step;
    maxDepth = Math.min(maxDepth, investigation);

    var score = 0.0;
    zones.forEach(function (zone) {
      var thickness = zone[1] - zone[0];
      var midRho = zoneRho(layers, zone[0], zone[1]);
      var lo = cfg.fractured_zone_rho[0], hi = cfg.fractured_zone_rho[1];
      var centre = Math.sqrt(lo * hi);
      var rhoTerm = 1.0 / (1.0 + Math.abs(Math.log(Math.max(midRho, 1e-3) / centre)));
      score += thickness * rhoTerm;
    });
    if (depthToBasement !== null && depthToBasement < 5 && !zones.length) score *= 0.5;

    var dz = darZarrouk(layers);
    var sCover = coverConductance(layers);
    var interp = {
      sounding_id: model.sounding_id || (sounding ? sounding.sounding_id : '') || '',
      model: model,
      curve_type: classifyCurve(model),
      layers: layers,
      water_zones: zones,
      depth_to_basement_m: depthToBasement,
      aquifer_thickness_m: aquiferThickness,
      max_drilling_depth_m: maxDepth,
      investigation_depth_m: investigation,
      score: score,
      longitudinal_conductance_s: dz.s,
      transverse_resistance_t: dz.t,
      protective_conductance_s: sCover,
      protective_capacity: protectiveCapacity(sCover),
      rank: null,
      site_easting: sounding && sounding.site ? sounding.site.easting : null,
      site_northing: sounding && sounding.site ? sounding.site.northing : null,
      site_elevation_m: sounding && sounding.site ? sounding.site.elevation_m : null,
      flags: [],
    };
    interp.narrative = interpretationNarrative(interp);
    return interp;
  }

  /* groundwater/utils.py fmt_num / round_sig / ordinal. Report prose is
   * compared against the Python output character for character, so the
   * thousands separators and the %g fallback have to match exactly. */

  /* Python's round(): half goes to even, not away from zero. It governs the
   * water-zone bounds and every fmt_num, so the two implementations disagree
   * on exact halves unless this is used. */
  function pyRound(x, digits) {
    var f = Math.pow(10, digits || 0);
    var v = x * f;
    var r = Math.abs(v - Math.trunc(v)) === 0.5
      ? 2 * Math.round(v / 2)
      : Math.round(v);
    return r / f;
  }

  function roundSig(value, sig) {
    if (value === 0 || !isFinite(value)) return value;
    var ndigits = (sig || 3) - 1 - Math.floor(Math.log(Math.abs(value)) / Math.LN10);
    var factor = Math.pow(10, ndigits);
    return Math.round(value * factor) / factor;
  }

  /* Python's "%g": 6 significant digits, trailing zeros stripped, exponential
   * when the exponent falls below -4 or reaches the precision. */
  function formatG(value, precision) {
    var p = precision || 6;
    if (value === 0) return '0';
    var rounded = roundSig(value, p);
    var exp = Math.floor(Math.log(Math.abs(rounded)) / Math.LN10);
    if (exp < -4 || exp >= p) {
      var mant = rounded / Math.pow(10, exp);
      var mstr = mant.toFixed(p - 1).replace(/0+$/, '').replace(/\.$/, '');
      return mstr + 'e' + (exp < 0 ? '-' : '+') +
        String(Math.abs(exp)).padStart(2, '0');
    }
    var out = rounded.toFixed(Math.max(0, p - 1 - exp));
    if (out.indexOf('.') >= 0) out = out.replace(/0+$/, '').replace(/\.$/, '');
    return out;
  }

  /* Python's "%.2e": the exponent is padded to at least two digits, which
   * toExponential does not do. */
  function expo(value, digits) {
    var text = Number(value).toExponential(digits === undefined ? 2 : digits);
    return text.replace(/e([+-])(\d)$/, 'e$10$2');
  }

  function fmtNum(value, sig, unit) {
    if (value === null || value === undefined || typeof value !== 'number' ||
        !isFinite(value)) {
      return 'n/a';
    }
    var v = roundSig(value, sig === undefined ? 3 : sig);
    var text;
    if (Math.abs(v - Math.round(v)) < 1e-9 && Math.abs(v) < 1e15) {
      text = pyRound(v).toLocaleString('en-US');
    } else {
      text = formatG(v);
    }
    return unit ? (text + ' ' + unit).trim() : text;
  }

  function fmtRange(a, b, unit, sep) {
    return (fmtNum(a) + (sep === undefined ? '-' : sep) + fmtNum(b) + ' ' +
      (unit === undefined ? 'm' : unit)).trim();
  }

  function ordinal(n) {
    if (n === null || n === undefined) return '';
    var v = n % 100;
    var suffix = (v >= 10 && v <= 20) ? 'th'
      : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
    return String(n) + suffix;
  }

  function interpretationNarrative(interp) {
    var parts = ['The data at ' + interp.sounding_id + ' resolves a ' +
      interp.model.n_layers + ' layer subsurface (' +
      describeCurveType(interp.curve_type) + ').'];
    interp.layers.forEach(function (layer) {
      var span = layer.thickness_m !== null
        ? 'from ' + fmtNum(layer.top_m) + ' m to ' + fmtNum(layer.bottom_m) +
          ' m (' + fmtNum(layer.thickness_m) + ' m thick)'
        : 'below ' + fmtNum(layer.top_m) + ' m';
      parts.push('Layer ' + layer.number + ' ' + span +
        ' has a resistivity of about ' + fmtNum(layer.rho, 4) +
        ' ohm-m and is interpreted as ' + layer.unit + '.');
    });
    if (interp.water_zones.length) {
      var zonesText = interp.water_zones.map(function (z) {
        return Math.trunc(z[0]) + ' m to ' + Math.trunc(z[1]) + ' m';
      }).join(', ');
      parts.push('The unusually low resistivity within the interpreted fractured ' +
        'or weathered intervals is indicative of pore electrolyte, possibly ' +
        'groundwater. The possible water zones are ' + zonesText + '.');
    } else {
      parts.push('No clearly water bearing low resistivity zone is resolved at ' +
        'this point within the investigated depth.');
    }
    if (interp.depth_to_basement_m !== null) {
      parts.push('The depth to bedrock is estimated at about ' +
        fmtNum(interp.depth_to_basement_m) + ' m.');
    }
    if (interp.longitudinal_conductance_s > 0) {
      var base = 'The Dar-Zarrouk longitudinal conductance of the section is ' +
        fmtNum(interp.longitudinal_conductance_s, 3) + ' siemens and the ' +
        'transverse resistance is ' + fmtNum(interp.transverse_resistance_t) +
        ' ohm m2.';
      if (interp.water_zones.length) {
        base += ' The cover overlying the water bearing zone has a longitudinal ' +
          'conductance of ' + fmtNum(interp.protective_conductance_s, 3) +
          ' siemens, indicating a ' + interp.protective_capacity +
          ' protective capacity against surface contamination.';
      } else {
        base += ' This gives a ' + interp.protective_capacity +
          ' protective capacity against surface contamination.';
      }
      parts.push(base);
    }
    return parts.join(' ');
  }

  /* Ranks in place, 1 = most preferred. Every caller reading `rank` must rank
   * first: an unranked set leaves every rank null and "best" then falls back to
   * whichever sounding happened to be parsed first. */
  function rankInterpretations(interpretations, preferredOrder) {
    var ranked;
    if (preferredOrder && preferredOrder.length) {
      var position = {};
      preferredOrder.forEach(function (sid, i) { position[sid] = i; });
      ranked = interpretations.slice().sort(function (a, b) {
        var pa = position[a.sounding_id] === undefined
          ? preferredOrder.length : position[a.sounding_id];
        var pb = position[b.sounding_id] === undefined
          ? preferredOrder.length : position[b.sounding_id];
        return pa - pb || b.score - a.score;
      });
    } else {
      ranked = interpretations.slice().sort(function (a, b) {
        return b.score - a.score ||
          (a.sounding_id < b.sounding_id ? -1 : a.sounding_id > b.sounding_id ? 1 : 0);
      });
    }
    ranked.forEach(function (interp, i) { interp.rank = i + 1; });
    return ranked;
  }

  function drillingPreferenceTable(interpretations, preferredOrder) {
    rankInterpretations(interpretations, preferredOrder);
    return interpretations.map(function (interp, i) {
      return {
        'No.': i + 1,
        'VES Point': interp.sounding_id,
        Layer: interp.layers.map(function (l) { return String(l.number); }).join('\n'),
        'Thickness (m)': interp.layers.map(function (l) {
          return l.thickness_m !== null ? fmtNum(l.thickness_m) : '';
        }).join('\n'),
        'Depth (m)': interp.layers.map(function (l) {
          return isFinite(l.bottom_m) ? fmtNum(l.bottom_m) : '';
        }).join('\n'),
        'Apparent Resistivity (Ohm-m)': interp.layers.map(function (l) {
          return fmtNum(l.rho, 4);
        }).join('\n'),
        'Possible Water Zones (m)': interp.water_zones.map(function (z) {
          return Math.trunc(z[0]) + '-' + Math.trunc(z[1]);
        }).join('\n') || 'none resolved',
        'Max Drilling Depth (m)': interp.max_drilling_depth_m.toFixed(0) + ' m',
        Ranking: ordinal(interp.rank),
      };
    });
  }

  C.MIN_PER_DAY = MIN_PER_DAY;
  Object.assign(C, {
    defaultConfig: defaultConfig, withConfig: withConfig,
    besselJ0: besselJ0, besselJ1: besselJ1, besselZeros: besselZeros,
    gaussLegendre: gaussLegendre, exp1: exp1,
    solveLinear: solveLinear, invertMatrix: invertMatrix, lineFit: lineFit,
    interp: interp, geomspace: geomspace,
    geometricFactor: geometricFactor, apparentResistivity: apparentResistivity,
    resistivityTransform: resistivityTransform,
    forwardSchlumberger: forwardSchlumberger,
    forwardSchlumbergerFiniteMn: forwardSchlumbergerFiniteMn,
    forwardWenner: forwardWenner, forwardCurve: forwardCurve,
    twoLayerSchlumbergerSeries: twoLayerSchlumbergerSeries,
    soundingSegments: soundingSegments, spliceSegments: spliceSegments,
    fitErrorPercent: fitErrorPercent, invertModel: invertModel,
    invertSounding: invertSounding, layeredModel: layeredModel,
    startingModels: startingModels, parameterUncertainty: parameterUncertainty,
    classifyCurve: classifyCurve, describeCurveType: describeCurveType,
    interpretModel: interpretModel, rankInterpretations: rankInterpretations,
    drillingPreferenceTable: drillingPreferenceTable,
    fmtNum: fmtNum, fmtRange: fmtRange, formatG: formatG,
    roundSig: roundSig, pyRound: pyRound, expo: expo, ordinal: ordinal,
  });

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

  /* Cooper-Jacob straight line on drawdown against log time.
   * With no explicit window the fit uses the last full log cycle (at least 6
   * points), which is where u is smallest and the approximation holds. */
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
    if (fit.slope <= 0) {
      throw new Error('Drawdown does not increase with log time; ' +
        'Cooper-Jacob does not apply');
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
    var uCheck = uStart < cfg.cooper_jacob_u_max
      ? 'u = ' + expo(uStart, 2) + ' at the start of the fitted window, ' +
        'below the ' + cfg.cooper_jacob_u_max + ' criterion; the straight line ' +
        'approximation is valid'
      : 'u = ' + expo(uStart, 2) + ' at the start of the fitted window ' +
        'exceeds ' + cfg.cooper_jacob_u_max + '; early data were excluded or ' +
        'results should be treated with caution';

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

  /* Least squares fit of the Theis well function s = Q/(4 pi T) W(u),
   * u = r^2 S / (4 T t), in log parameter space so T and S stay positive.
   * Levenberg-Marquardt stands in for scipy's curve_fit. */
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
    var qDay = dischargeM3PerH * 24.0;

    function model(tt, logT, logS) {
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
    for (var iter = 0; iter < 200; iter++) {
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

    var Tfit = Math.pow(10, p[0]), Sfit = Math.pow(10, p[1]);
    var fitted = model(t, p[0], p[1]), ss = 0;
    for (var k2 = 0; k2 < t.length; k2++) {
      var e2 = fitted[k2] - s[k2];
      ss += e2 * e2;
    }
    return {
      transmissivity_m2_per_day: Tfit,
      storativity: Sfit,
      storativity_reliable: !!opts.observationWell,
      rmse_m: Math.sqrt(ss / t.length),
      discharge_m3_per_h: dischargeM3PerH,
      radius_m: radiusM,
    };
  }

  /* Theis recovery on residual drawdown against t/t':
   *   s' = 2.303 Q / (4 pi T) log10(t/t')
   * with t since pumping started and t' since it stopped. */
  function theisRecovery(recoveryTimeMin, residualDrawdownM, pumpingDurationMin,
                         dischargeM3PerH) {
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
    if (fit.slope <= 0) {
      throw new Error('Residual drawdown does not decrease; check the data');
    }
    var qDay = dischargeM3PerH * 24.0;
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
    };
  }

  /* Hantush-Bierschenk step drawdown analysis. Fits s_w = B Q + C Q^2 through
   * the end-of-step drawdowns by regressing s_w/Q on Q, so the SLOPE is C and
   * the INTERCEPT is B. Q is m3/day, so B is day/m2 and C day2/m5. */
  function hantushBierschenk(stepDischargesM3PerH, stepEndDrawdownsM) {
    var q = stepDischargesM3PerH.map(function (v) { return v * 24.0; });
    var s = stepEndDrawdownsM.slice();
    if (q.length < 2) {
      throw new Error('A step test needs at least two steps with discharge');
    }
    var sq = s.map(function (v, i) { return v / q[i]; });
    var fit = lineFit(q, sq);
    var C = fit.slope, B = fit.intercept, r2 = fit.r2;
    if (C < 0) {
      /* negative well loss has no physical meaning; fall back to pure
       * aquifer loss */
      C = 0.0;
      B = arrMean(sq);
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
    }
    var steps = q.map(function (qi, i) {
      var total = B * qi + C * qi * qi;
      return {
        step: i + 1,
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
      drawdown_at: function (qDay) { return B * qDay + C * qDay * qDay; },
      efficiency_at: function (qDay) {
        var total = B * qDay + C * qDay * qDay;
        return total <= 0 ? 100.0 : 100.0 * B * qDay / total;
      },
    };
  }

  /* --- yield recommendation ------------------------------------------------
   * The long term yield solves s_proj(Q) = f_avail x s_available, projecting
   * Cooper-Jacob drawdown to the design period with the fitted T (plus well
   * losses when a step test is available). The stated safety factor is then
   * applied. Every input is recorded in `basis` so the recommendation is
   * traceable back to the sheet.
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
    var specificCapacity = (qLast && sEnd && sEnd > 0) ? qLast / sEnd : null;

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
    var usable = available
      ? Math.max(available - cfg.seasonal_allowance_m, 0.0) *
        cfg.available_drawdown_fraction
      : null;

    if (transmissivity === null || transmissivity === undefined ||
        swl === null || swl === undefined) {
      /* Name what is actually missing: blaming the discharge when it was
       * recorded and the fit simply failed sends the crew back to the field
       * for a number that is already on the sheet. */
      var missing = [];
      if (swl === null || swl === undefined) missing.push('static water level is missing');
      if (transmissivity === null || transmissivity === undefined) {
        var anyQ = (test.steps || []).some(function (s) { return s.discharge_m3_per_h; });
        missing.push(anyQ
          ? 'transmissivity could not be fitted from the readings'
          : 'discharge is missing on the field sheet');
      }
      var reason = missing.join(' and ');
      return {
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
      };
    }

    var tDesign = cfg.design_period_days;
    var logTerm = Math.log(2.25 * transmissivity * tDesign /
      (effectiveRadiusM * effectiveRadiusM * assumedStorativity)) / Math.LN10;

    function projectedDrawdown(qM3PerH) {
      var qDay = qM3PerH * 24.0;
      var s = 2.303 * qDay / (4.0 * Math.PI * transmissivity) * logTerm;
      if (stepResult) {
        /* B Q + C Q^2 is the drawdown at the step duration; the Cooper-Jacob
         * time projection from step length to design period replaces the
         * plain projection above rather than adding to it. */
        var tStepMin = test.step_length_min || test.pumping_duration_min || 180.0;
        s = stepResult.drawdown_at(qDay);
        s += 2.303 * qDay / (4.0 * Math.PI * transmissivity) *
          Math.log(tDesign / (tStepMin / MIN_PER_DAY)) / Math.LN10;
      }
      return s;
    }

    var longTerm = null;
    if (usable && usable > 0) {
      var qLo = 0.01, qHi = 200.0;
      for (var it = 0; it < 80; it++) {
        var qMid = 0.5 * (qLo + qHi);
        if (projectedDrawdown(qMid) > usable) qHi = qMid; else qLo = qMid;
      }
      longTerm = qLo;
    }

    var safe = longTerm ? longTerm / cfg.safety_factor : null;

    var pumpDepth = null;
    if (safe !== null) {
      var sAtSafe = projectedDrawdown(safe);
      pumpDepth = swl + sAtSafe + cfg.seasonal_allowance_m + cfg.pump_submergence_min_m;
      if (test.borehole_depth_m) {
        pumpDepth = Math.min(pumpDepth, test.borehole_depth_m - 3.0);
      }
      pumpDepth = Math.ceil(pumpDepth);
    }

    var pct = Math.round(cfg.available_drawdown_fraction * 100) + '%';
    var basis = 'Transmissivity ' + transmissivity.toFixed(1) + ' m2/day; drawdown ' +
      'projected to ' + tDesign.toFixed(0) + ' days with storativity assumed ' +
      formatG(assumedStorativity) + ' and effective radius ' + effectiveRadiusM +
      ' m; usable drawdown taken as ' + pct + ' of the available drawdown' +
      (available
        ? ' ' + available.toFixed(1) + ' m (static level to pump intake less ' +
          cfg.pump_submergence_min_m.toFixed(0) + ' m submergence), after ' +
          'reserving a ' + cfg.seasonal_allowance_m.toFixed(0) + ' m dry-season ' +
          'water-table decline'
        : '') +
      (stepResult ? '; well losses from the step test are included' : '') +
      '. A safety factor of ' + cfg.safety_factor + ' is applied to the long ' +
      'term yield.';

    return {
      specific_capacity_m3hr_per_m: specificCapacity,
      available_drawdown_m: available,
      usable_drawdown_m: usable,
      projected_drawdown_m: safe ? projectedDrawdown(safe) : null,
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
    };
  }

  /* Storativity is never resolvable from a single pumped well, the effective
   * radius depends on the gravel pack and development, and the wet-to-dry
   * decline is a regional rule of thumb. The safe yield is proportional to
   * none of them individually but sensitive to all of them, so the honest
   * output is a band. */
  var ENVELOPE_STORATIVITY = [1e-4, 1e-2];
  var ENVELOPE_RADIUS_M = [0.075, 0.15];
  var ENVELOPE_SEASONAL_M = [1.0, 4.0];

  function attachYieldEnvelope(analysis, config) {
    var cfg = config || defaultConfig().pumping;
    var rec = analysis.yield_recommendation;
    if (!rec || rec.safe_yield_m3_per_h === null) return;

    var fitted = [analysis.recovery, analysis.cooper_jacob, analysis.theis]
      .filter(function (r) { return r && r.transmissivity_m2_per_day; })
      .map(function (r) { return r.transmissivity_m2_per_day; });
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
    rec.safe_yield_low_m3_per_h = arrMin(yields);
    rec.safe_yield_high_m3_per_h = arrMax(yields);
    rec.envelope_basis = 'Range over transmissivity ' + tRange[0].toFixed(1) + '-' +
      tRange[1].toFixed(1) + ' m2/day' +
      (fitted.length > 1 ? ' (spread between the fitted methods)' : '') +
      ', storativity ' + formatG(ENVELOPE_STORATIVITY[0]) + '-' +
      formatG(ENVELOPE_STORATIVITY[1]) + ', effective radius ' +
      ENVELOPE_RADIUS_M[0] + '-' + ENVELOPE_RADIUS_M[1] + ' m and a dry-season ' +
      'decline of ' + ENVELOPE_SEASONAL_M[0].toFixed(0) + '-' +
      ENVELOPE_SEASONAL_M[1].toFixed(0) + ' m. Design to the lower figure where ' +
      'the supply must not fail in a dry year.';
  }

  /* "2.4 m3/h (1.8 to 3.1)" - never a bare number for an assumed one. */
  function yieldRangeText(rec) {
    if (!rec || rec.safe_yield_m3_per_h === null) return 'pending';
    var text = formatG(roundSig(rec.safe_yield_m3_per_h, 2), 2) + ' m3/h';
    if (rec.safe_yield_low_m3_per_h !== null && rec.safe_yield_high_m3_per_h !== null) {
      text += ' (' + formatG(roundSig(rec.safe_yield_low_m3_per_h, 2), 2) + ' to ' +
        formatG(roundSig(rec.safe_yield_high_m3_per_h, 2), 2) + ')';
    }
    return text;
  }

  /* Run every applicable analysis on a parsed pumping test. Methods that need
   * missing inputs are skipped with a flag instead of failing, so partially
   * filled sheets still produce curves and a report skeleton. */
  function analysePumpingTest(test, config, options) {
    var opts = options || {};
    var cfg = (config && config.pumping) ? config.pumping
      : (config || defaultConfig().pumping);
    var observationRadiusM = opts.observationRadiusM;
    var analysis = {
      test: test, cooper_jacob: null, theis: null, recovery: null,
      step_test: null, yield_recommendation: null,
      stabilised_level_m: null, max_drawdown_m: null, flags: [],
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

    if (test.steps && test.steps.length && hasSwl) {
      var last = test.steps[test.steps.length - 1];
      analysis.max_drawdown_m = arrMax(last.water_level_m.filter(isFinite)) - swl;
      var tail = last.water_level_m.slice(-3);
      if (tail.length >= 2 && (arrMax(tail) - arrMin(tail)) <= 0.05) {
        analysis.stabilised_level_m = arrMean(tail);
      }
    }

    /* Cooper-Jacob and Theis on the first step: it pumps at a single rate from
     * static conditions, so the single-well solutions apply directly (later
     * steps would need superposition of the earlier rates). */
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
        try {
          analysis.cooper_jacob = cooperJacob(t0, s0, q0, cfg,
            { observationRadiusM: observationRadiusM });
        } catch (e) {
          flags.push({ level: 'warning', code: 'cooper_jacob_failed', message: e.message });
        }
        try {
          analysis.theis = theisFit(t0, s0, q0, {
            observationWell: observationRadiusM !== null && observationRadiusM !== undefined,
            radiusM: observationRadiusM || 0.1,
          });
        } catch (e2) {
          flags.push({ level: 'warning', code: 'theis_failed', message: e2.message });
        }
      }
    }

    /* recovery */
    if (test.recovery_level_m && hasSwl && test.recovery_time_min) {
      var residual = test.recovery_level_m.map(function (v) { return v - swl; });
      var qRec = null;
      for (var k = test.steps.length - 1; k >= 0; k--) {
        if (test.steps[k].discharge_m3_per_h !== null &&
            test.steps[k].discharge_m3_per_h !== undefined) {
          qRec = test.steps[k].discharge_m3_per_h;
          break;
        }
      }
      if (qRec !== null && test.pumping_duration_min) {
        try {
          analysis.recovery = theisRecovery(test.recovery_time_min, residual,
            test.pumping_duration_min, qRec);
        } catch (e3) {
          flags.push({ level: 'warning', code: 'recovery_failed', message: e3.message });
        }
      }
    }

    /* step test */
    if (String(test.test_type || '').indexOf('step') === 0 && hasSwl &&
        test.steps.length >= 2) {
      var withQ = test.steps.filter(function (s) {
        return s.discharge_m3_per_h !== null && s.discharge_m3_per_h !== undefined;
      });
      if (withQ.length >= 2) {
        try {
          analysis.step_test = hantushBierschenk(
            withQ.map(function (s) { return s.discharge_m3_per_h; }),
            withQ.map(function (s) {
              return s.water_level_m[s.water_level_m.length - 1] - swl;
            }));
        } catch (e4) {
          flags.push({ level: 'warning', code: 'step_test_failed', message: e4.message });
        }
      } else {
        flags.push({
          level: 'warning', code: 'step_test_pending',
          message: 'Step test analysis pending: discharge per step is missing.',
        });
      }
    }

    /* Preferred transmissivity: recovery is least affected by well losses,
     * then Cooper-Jacob, then Theis. */
    analysis.transmissivity_m2_per_day = null;
    [analysis.recovery, analysis.cooper_jacob, analysis.theis].some(function (r) {
      if (r) { analysis.transmissivity_m2_per_day = r.transmissivity_m2_per_day; return true; }
      return false;
    });

    analysis.yield_recommendation = recommendYield(test,
      analysis.transmissivity_m2_per_day, analysis.step_test, cfg);
    attachYieldEnvelope(analysis, cfg);
    analysis.yield_range_text = yieldRangeText(analysis.yield_recommendation);

    analysis.flags = flags;
    return analysis;
  }

  Object.assign(C, {
    requireDischarge: requireDischarge,
    cooperJacob: cooperJacob, theisFit: theisFit, theisRecovery: theisRecovery,
    hantushBierschenk: hantushBierschenk, recommendYield: recommendYield,
    attachYieldEnvelope: attachYieldEnvelope, yieldRangeText: yieldRangeText,
    analysePumpingTest: analysePumpingTest,
  });

  /* ======================================================== water quality
   * groundwater/quality/*. The standards table itself is bundled data
   * (data/who_guidelines.csv, embedded by the build as GWT.data.whoGuidelines),
   * so a client with different national limits edits the table, not the code.
   */

  var RANGE_RE = /^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$/;

  /* A guideline limit: either a maximum or an allowed range like "6.5-8.5". */
  function parseLimit(text) {
    var s = String(text === null || text === undefined ? '' : text).trim();
    if (!s) return null;
    var m = RANGE_RE.exec(s);
    if (m) return { minimum: parseFloat(m[1]), maximum: parseFloat(m[2]) };
    var v = Number(s);
    if (!isFinite(v)) return null;
    return { minimum: null, maximum: v };
  }

  function limitExceededBy(limit, value) {
    if (!limit) return false;
    if (limit.minimum !== null && limit.minimum !== undefined && value < limit.minimum) return true;
    if (limit.maximum !== null && limit.maximum !== undefined && value > limit.maximum) return true;
    return false;
  }

  function limitText(limit) {
    if (!limit) return '';
    if (limit.minimum !== null && limit.minimum !== undefined) {
      return formatG(limit.minimum) + '-' + formatG(limit.maximum);
    }
    if (limit.maximum !== null && limit.maximum !== undefined) return formatG(limit.maximum);
    return '';
  }

  var PARAMETER_ALIASES = {
    ec: 'electrical conductivity',
    conductivity: 'electrical conductivity',
    'total dissolved solids': 'tds',
    hardness: 'total hardness',
    nitrate: 'nitrate (as no3)',
    no3: 'nitrate (as no3)',
    nitrite: 'nitrite (as no2)',
    no2: 'nitrite (as no2)',
    ammonia: 'ammonia (as n)',
    ammonium: 'ammonia (as n)',
    nh3: 'ammonia (as n)',
    nh4: 'ammonia (as n)',
    chromium: 'chromium (total)',
    cr: 'chromium (total)',
    'faecal coliforms': 'e. coli',
    'fecal coliforms': 'e. coli',
    'e.coli': 'e. coli',
    'escherichia coli': 'e. coli',
    coliforms: 'total coliforms',
    sulphate: 'sulfate',
    so4: 'sulfate',
    aluminum: 'aluminium',
  };

  function normaliseParameter(name) {
    var key = String(name || '').trim().toLowerCase().replace(/\s+/g, ' ');
    return PARAMETER_ALIASES[key] || key;
  }

  var _standardsCache = null;
  function loadStandards(rows) {
    var source = rows || (GWT.data && GWT.data.whoGuidelines);
    if (!source) return {};
    if (!rows && _standardsCache) return _standardsCache;
    var table = {};
    source.forEach(function (row) {
      var entry = {
        parameter: row.parameter,
        unit: row.unit || '',
        who_health: parseLimit(row.who_health_gv),
        who_aesthetic: parseLimit(row.who_aesthetic),
        sl_standard: parseLimit(row.sl_standard),
        category: row.category || '',
        note: row.note || '',
      };
      table[normaliseParameter(entry.parameter)] = entry;
    });
    if (!rows) _standardsCache = table;
    return table;
  }

  /* --- ionic balance -------------------------------------------------------
   * 100 x (sum cations - sum anions) / (sum cations + sum anions) in meq/L.
   * Within 5% is normal laboratory practice, 5-10% is flagged for review, and
   * more than 10% means an unreliable analysis or a missing major ion.
   */

  var CATION_MEQ = {
    calcium: 2 / 40.078,
    magnesium: 2 / 24.305,
    sodium: 1 / 22.990,
    potassium: 1 / 39.098,
    iron: 2 / 55.845,
    manganese: 2 / 54.938,
  };
  var ANION_MEQ = {
    chloride: 1 / 35.453,
    sulfate: 2 / 96.06,
    bicarbonate: 1 / 61.017,
    carbonate: 2 / 60.009,
    'nitrate (as no3)': 1 / 62.004,
    fluoride: 1 / 18.998,
  };
  var REQUIRED_CATIONS = ['calcium', 'magnesium', 'sodium'];
  var REQUIRED_ANIONS = ['chloride', 'bicarbonate'];

  /* A result below the detection limit counts as zero; a result with no value
   * at all counts as not measured. */
  function sampleValue(sample, key) {
    var results = sample.results || [];
    for (var i = 0; i < results.length; i++) {
      if (normaliseParameter(results[i].parameter) === key) {
        if (results[i].value !== null && results[i].value !== undefined) {
          return Number(results[i].value);
        }
        return results[i].below_detection ? 0.0 : null;
      }
    }
    return null;
  }

  function ionicBalance(sample) {
    var cations = {}, anions = {};
    Object.keys(CATION_MEQ).forEach(function (key) {
      var v = sampleValue(sample, key);
      if (v !== null) cations[key] = v * CATION_MEQ[key];
    });
    var usedAlk = false;
    Object.keys(ANION_MEQ).forEach(function (key) {
      var v = sampleValue(sample, key);
      if (v !== null) anions[key] = v * ANION_MEQ[key];
    });
    if (!('bicarbonate' in anions)) {
      var alk = sampleValue(sample, 'alkalinity');
      if (alk !== null) {
        /* alkalinity as CaCO3 -> bicarbonate equivalent: meq = mg/L / 50.04 */
        anions.bicarbonate = alk / 50.04;
        usedAlk = true;
      }
    }
    var haveCat = REQUIRED_CATIONS.every(function (k) { return k in cations; });
    var haveAn = REQUIRED_ANIONS.every(function (k) { return k in anions; });
    if (!haveCat || !haveAn) return null;

    var totalCat = 0, totalAn = 0;
    Object.keys(cations).forEach(function (k) { totalCat += cations[k]; });
    Object.keys(anions).forEach(function (k) { totalAn += anions[k]; });
    if (totalCat + totalAn <= 0) return null;
    var error = 100.0 * (totalCat - totalAn) / (totalCat + totalAn);

    var flag = null;
    var signed = (error >= 0 ? '+' : '') + error.toFixed(1);
    if (Math.abs(error) > 10) {
      flag = {
        level: 'error', code: 'ionic_balance',
        message: 'Charge balance error ' + signed + '% exceeds 10%; the ' +
          'analysis is unreliable or a major ion is missing.',
      };
    } else if (Math.abs(error) > 5) {
      flag = {
        level: 'warning', code: 'ionic_balance',
        message: 'Charge balance error ' + signed + '% is between 5% and 10%; ' +
          'review the laboratory analysis.',
      };
    }
    return {
      sum_cations_meq: totalCat, sum_anions_meq: totalAn, error_percent: error,
      cations_meq: cations, anions_meq: anions,
      used_alkalinity_for_bicarbonate: usedAlk, flag: flag,
    };
  }

  /* --- water quality index and health risk --------------------------------- */

  var INTAKE_L_PER_DAY = 2.0;
  var BODY_WEIGHT_KG = 70.0;

  /* oral reference doses, mg/kg/day (EPA IRIS / WHO) */
  var RFD = {
    arsenic: 3.0e-4, fluoride: 0.06, 'nitrate (as no3)': 1.6,
    'nitrite (as no2)': 0.1, manganese: 0.14, lead: 3.5e-3, cadmium: 5.0e-4,
    'chromium (total)': 3.0e-3, uranium: 3.0e-3, nickel: 0.02, copper: 0.04,
    zinc: 0.3, barium: 0.2, selenium: 5.0e-3, antimony: 4.0e-4,
  };
  var CANCER_SLOPE = { arsenic: 1.5 };

  /* The IRIS reference doses for nitrate and nitrite are expressed as
   * nitrogen, but the toolkit records the whole ion. Convert before dividing,
   * else the hazard quotient is overstated by the mass ratio. */
  var AS_NITROGEN_FACTOR = {
    'nitrate (as no3)': 62.004 / 14.007,
    'nitrite (as no2)': 46.005 / 14.007,
  };

  function measuredValues(sample) {
    var values = {};
    (sample.results || []).forEach(function (r) {
      if (r.value !== null && r.value !== undefined) {
        values[normaliseParameter(r.parameter)] = Number(r.value);
      }
    });
    return values;
  }

  function wqiRating(value) {
    if (value <= 50) return 'Excellent';
    if (value <= 100) return 'Good';
    if (value <= 200) return 'Poor';
    if (value <= 300) return 'Very poor';
    return 'Unsuitable for drinking';
  }

  function computeWqi(sample, standardsRows) {
    var table = loadStandards(standardsRows);
    var values = measuredValues(sample);
    var weightSum = 0, weightedQ = 0, contributors = [], n = 0;
    Object.keys(values).forEach(function (key) {
      var entry = table[key];
      if (!entry || entry.category === 'microbiological') return;
      /* Health-based trace toxicants have tiny standards, so 1/s weighting and
       * the value/s sub-index let a single one dominate and drown out the
       * general chemistry this index summarises. They are reported through the
       * separate Hazard Index instead. */
      if (key in RFD) return;
      var limit = entry.who_health || entry.who_aesthetic || entry.sl_standard;
      if (!limit || !limit.maximum || limit.maximum <= 0) return;
      var si = limit.maximum, qi;
      if (key === 'ph') {
        var denom = si - 7.0;
        qi = denom ? 100.0 * Math.abs(values[key] - 7.0) / denom : 0.0;
      } else {
        qi = 100.0 * values[key] / si;
      }
      var wi = 1.0 / si;
      weightSum += wi;
      weightedQ += wi * qi;
      contributors.push([entry.parameter, wi * qi]);
      n += 1;
    });
    if (n < 3 || weightSum <= 0) return null;
    var wqi = weightedQ / weightSum;
    contributors.sort(function (a, b) { return b[1] - a[1]; });
    return {
      value: pyRound(wqi, 1),
      rating: wqiRating(wqi),
      n_parameters: n,
      top_contributors: contributors.slice(0, 3).map(function (kv) {
        return [kv[0], pyRound(kv[1] / weightSum, 1)];
      }),
    };
  }

  function assessHealthRisk(sample) {
    var values = measuredValues(sample);
    var hq = {}, intakeFactor = INTAKE_L_PER_DAY / BODY_WEIGHT_KG;
    Object.keys(RFD).forEach(function (key) {
      if (!(key in values) || RFD[key] <= 0) return;
      var conc = values[key];
      var factor = AS_NITROGEN_FACTOR[key];
      if (factor) conc = conc / factor;
      hq[key] = (conc * intakeFactor) / RFD[key];
    });
    var keys = Object.keys(hq);
    if (!keys.length) return null;
    var hazardIndex = keys.reduce(function (a, k) { return a + hq[k]; }, 0);
    var cancerRisk = null;
    if ('arsenic' in values) {
      cancerRisk = values.arsenic * intakeFactor * CANCER_SLOPE.arsenic;
    }
    var flags = [];
    if (hazardIndex >= 1.0) {
      var worst = keys.reduce(function (a, b) { return hq[a] >= hq[b] ? a : b; });
      flags.push({
        level: 'warning', code: 'hazard_index',
        message: 'Non-carcinogenic Hazard Index ' + hazardIndex.toFixed(1) +
          ' is at or above 1 (dominated by ' + worst + '); chronic ingestion ' +
          'poses a potential health concern.',
      });
    }
    if (cancerRisk !== null && cancerRisk > 1e-4) {
      flags.push({
        level: 'warning', code: 'cancer_risk',
        message: 'Estimated lifetime arsenic cancer risk ' + expo(cancerRisk, 1) +
          ' exceeds the 1e-4 screening level.',
      });
    }
    var rating = hazardIndex < 1.0 ? 'Acceptable (Hazard Index below 1)'
      : (hazardIndex < 4.0 ? 'Elevated (Hazard Index at or above 1)'
                           : 'High (Hazard Index at or above 4)');
    var sortedHq = {};
    keys.sort(function (a, b) { return hq[b] - hq[a]; }).forEach(function (k) {
      sortedHq[k] = pyRound(hq[k], 2);
    });
    return {
      hazard_index: pyRound(hazardIndex, 2), hazard_quotients: sortedHq,
      cancer_risk: cancerRisk, rating: rating, flags: flags,
    };
  }

  /* --- corrosivity ---------------------------------------------------------
   * Soft, low-alkalinity, low-pH water from crystalline basement aquifers is
   * chemically aggressive and corrodes galvanised iron and mild-steel rising
   * mains, a leading cause of premature handpump failure across West Africa.
   * The water can be aggressive even with the pH inside 6.5-8.5, so a pH check
   * alone is not enough.
   */

  var LS_MEQ = {
    chloride: 1 / 35.453, sulfate: 2 / 96.06,
    bicarbonate: 1 / 61.017, carbonate: 2 / 60.009,
  };

  function classifyRsi(rsi) {
    if (rsi < 6.0) return ['Scale-forming', false];
    if (rsi <= 7.0) return ['Balanced (near CaCO3 equilibrium)', false];
    if (rsi <= 8.0) return ['Corrosive', true];
    return ['Strongly corrosive', true];
  }

  function assessCorrosivity(sample) {
    var assessment = {
      lsi: null, rsi: null, aggressive_index: null, larson_skold: null,
      classification: 'Insufficient data', is_aggressive: false,
      verdict: '', materials_note: '', assumptions: [], flags: [],
    };
    var assumptions = assessment.assumptions;

    var ph = sampleValue(sample, 'ph');
    var calcium = sampleValue(sample, 'calcium');
    var alkalinity = sampleValue(sample, 'alkalinity');
    var tds = sampleValue(sample, 'tds');
    var ec = sampleValue(sample, 'electrical conductivity');
    var temp = sampleValue(sample, 'temperature');

    if (tds === null || tds <= 0) {
      if (ec && ec > 0) {
        tds = 0.64 * ec;
        assumptions.push('TDS estimated as 0.64 x EC = ' + tds.toFixed(0) +
          ' mg/L (TDS not reported).');
      } else {
        tds = 250.0;
        assumptions.push('TDS assumed 250 mg/L (neither TDS nor EC reported).');
      }
    }
    if (temp === null || temp <= 0) {
      temp = 25.0;
      assumptions.push('Temperature assumed 25 C (not reported).');
    }

    if (ph === null || calcium === null || alkalinity === null ||
        calcium <= 0 || alkalinity <= 0) {
      assessment.verdict = 'Corrosivity could not be assessed: pH, calcium and ' +
        'alkalinity are all required. Supply them to obtain a materials ' +
        'recommendation.';
      return assessment;
    }

    /* calcium hardness as CaCO3 (Ca mg/L x 100.09/40.08) */
    var caHardness = calcium * 2.497;
    var log10 = function (v) { return Math.log(v) / Math.LN10; };

    /* Langelier: pHs = (9.3 + A + B) - (C + D) */
    var a = (log10(tds) - 1.0) / 10.0;
    var b = -13.12 * log10(temp + 273.15) + 34.55;
    var c = log10(caHardness) - 0.4;
    var d = log10(alkalinity);
    var phS = (9.3 + a + b) - (c + d);
    var lsi = ph - phS;
    var rsi = 2 * phS - ph;
    var ai = ph + log10(alkalinity * caHardness);

    assessment.lsi = pyRound(lsi, 2);
    assessment.rsi = pyRound(rsi, 2);
    assessment.aggressive_index = pyRound(ai, 2);

    /* Larson-Skold (optional): (Cl + SO4) / (HCO3 + CO3) in meq/L */
    var chloride = sampleValue(sample, 'chloride');
    var sulfate = sampleValue(sample, 'sulfate');
    var bicarbonate = sampleValue(sample, 'bicarbonate');
    var carbonate = sampleValue(sample, 'carbonate');
    var hco3Meq = bicarbonate === null
      ? alkalinity / 50.04
      : bicarbonate * LS_MEQ.bicarbonate;
    var co3Meq = (carbonate || 0.0) * LS_MEQ.carbonate;
    if (chloride !== null && sulfate !== null && (hco3Meq + co3Meq) > 0) {
      assessment.larson_skold = pyRound(
        (chloride * LS_MEQ.chloride + sulfate * LS_MEQ.sulfate) / (hco3Meq + co3Meq), 2);
    }

    var classified = classifyRsi(rsi);
    var classification = classified[0], aggressive = classified[1];
    if (lsi < -0.5) aggressive = true;
    if (assessment.aggressive_index !== null && assessment.aggressive_index < 10) {
      aggressive = true;
    }
    /* Keep the class label consistent with the flag and verdict: when the
     * LSI/AI corroboration promotes borderline water to aggressive, the RSI
     * class must not still read "Balanced" beside an "aggressive" verdict. */
    if (aggressive && ['Corrosive', 'Strongly corrosive'].indexOf(classification) < 0) {
      classification = 'Corrosive';
    }
    assessment.classification = classification;
    assessment.is_aggressive = aggressive;

    var signedLsi = (lsi >= 0 ? '+' : '') + lsi.toFixed(1);
    if (aggressive) {
      assessment.verdict = 'The water is chemically aggressive (Ryznar index ' +
        rsi.toFixed(1) + ', Langelier index ' + signedLsi + '). It will corrode ' +
        'metal fittings, and it can be aggressive even though the pH is within ' +
        'the acceptability range, which is typical of soft basement groundwater.';
      assessment.materials_note = 'Specify uPVC or stainless steel (grade 304 or ' +
        '316) for the rising main and pump components, and avoid galvanised iron ' +
        'and mild steel, which corrode rapidly in this water and are a leading ' +
        'cause of premature handpump failure. Inspect the rising main and pump ' +
        'rods for corrosion at each service.';
      if (assessment.larson_skold !== null && assessment.larson_skold > 0.8) {
        assessment.materials_note += ' The Larson-Skold ratio (' +
          assessment.larson_skold.toFixed(1) + ') is elevated, so chloride and ' +
          'sulfate add to the attack on steel.';
      }
      assessment.flags.push({
        level: 'warning', code: 'aggressive_water',
        message: 'Water is chemically aggressive; specify uPVC or stainless ' +
          'rising main and pump components.',
      });
    } else if (classification === 'Scale-forming') {
      assessment.verdict = 'The water tends to deposit calcium carbonate scale ' +
        '(Ryznar index ' + rsi.toFixed(1) + ', Langelier index ' + signedLsi + ').';
      assessment.materials_note = 'Monitor the screen and pump for encrustation ' +
        'and de-scale as needed; corrosion of metal parts is a lesser concern.';
    } else {
      assessment.verdict = 'The water is close to calcium carbonate equilibrium ' +
        '(Ryznar index ' + rsi.toFixed(1) + ', Langelier index ' + signedLsi +
        '); neither strong corrosion nor scaling is expected.';
      assessment.materials_note = 'Standard materials are acceptable; inspect ' +
        'fittings for corrosion during routine maintenance.';
    }
    return assessment;
  }

  /* --- full sample assessment ---------------------------------------------- */

  var STATUS_ORDER = ['exceeds_health', 'exceeds_national', 'exceeds_aesthetic',
    'within_limits', 'below_detection', 'no_guideline', 'not_measured'];

  function nitrateNitriteIndex(sample, table) {
    function valueAndGv(key) {
      var entry = table[key];
      var gv = entry && entry.who_health ? entry.who_health.maximum : null;
      var results = sample.results || [];
      for (var i = 0; i < results.length; i++) {
        if (normaliseParameter(results[i].parameter) === key &&
            results[i].value !== null && results[i].value !== undefined) {
          return [Number(results[i].value), gv];
        }
      }
      return [null, gv];
    }
    var a = valueAndGv('nitrate (as no3)'), b = valueAndGv('nitrite (as no2)');
    if (a[0] === null || b[0] === null || !a[1] || !b[1]) return null;
    return { ratio: a[0] / a[1] + b[0] / b[1], no3: a[0], no2: b[0], gv3: a[1], gv2: b[1] };
  }

  function assessSample(sample, standardsRows) {
    var table = loadStandards(standardsRows);
    var rows = [], flags = (sample.flags || []).slice();

    (sample.results || []).forEach(function (result) {
      var key = normaliseParameter(result.parameter);
      var entry = table[key] || null;
      var status, remark;

      if ((result.value === null || result.value === undefined) && !result.below_detection) {
        status = 'not_measured'; remark = 'no value reported';
      } else if (result.below_detection &&
                 (result.value === null || result.value === undefined)) {
        status = 'below_detection';
        remark = (result.detection_limit !== null && result.detection_limit !== undefined)
          ? 'below detection limit (' + formatG(result.detection_limit) + ')'
          : 'below detection limit';
      } else if (!entry) {
        status = 'no_guideline'; remark = 'parameter not in the standards table';
        flags.push({
          level: 'info', code: 'unknown_parameter',
          message: "No guideline entry for '" + result.parameter + "'; add it " +
            'to the standards CSV if a limit applies.',
        });
      } else {
        var value = Number(result.value);
        var isMicro = String(entry.category || '').trim().toLowerCase() === 'microbiological';
        if (entry.who_health && limitExceededBy(entry.who_health, value)) {
          status = 'exceeds_health';
          remark = 'exceeds the WHO health based guideline (' +
            limitText(entry.who_health) + ')';
        } else if (isMicro && (
            (entry.sl_standard && limitExceededBy(entry.sl_standard, value)) ||
            (entry.who_aesthetic && limitExceededBy(entry.who_aesthetic, value)))) {
          /* A microbiological indicator is a health concern, never an aesthetic
           * one, even when its limit sits in the national column. Otherwise the
           * verdict calls faecally-indicated water "usable for drinking". */
          status = 'exceeds_health';
          var micro = entry.sl_standard || entry.who_aesthetic;
          remark = 'microbiological indicator detected above the limit (' +
            limitText(micro) + '); a health (faecal contamination) concern, ' +
            'not aesthetic';
        } else if (entry.sl_standard && limitExceededBy(entry.sl_standard, value)) {
          if (entry.who_health) {
            /* A national limit stricter than the WHO health value is a
             * compliance failure, not a matter of taste. */
            status = 'exceeds_national';
            remark = 'exceeds the national standard limit (' +
              limitText(entry.sl_standard) + '), which is stricter than the ' +
              'WHO health based guideline (' + limitText(entry.who_health) + ')';
          } else {
            status = 'exceeds_aesthetic';
            remark = 'exceeds the national acceptability limit (' +
              limitText(entry.sl_standard) + ')';
          }
        } else if (entry.who_aesthetic && limitExceededBy(entry.who_aesthetic, value)) {
          status = 'exceeds_aesthetic';
          remark = 'exceeds the WHO acceptability value (' +
            limitText(entry.who_aesthetic) + ')';
        } else if (!(entry.who_health || entry.who_aesthetic || entry.sl_standard)) {
          status = 'no_guideline'; remark = entry.note || 'no guideline value';
        } else {
          status = 'within_limits'; remark = '';
        }
      }

      rows.push({
        parameter: result.parameter,
        value: (result.value === null || result.value === undefined) ? null : Number(result.value),
        unit: result.unit || (entry ? entry.unit : ''),
        below_detection: !!result.below_detection,
        who_health: entry && entry.who_health ? limitText(entry.who_health) : '',
        who_aesthetic: entry && entry.who_aesthetic ? limitText(entry.who_aesthetic) : '',
        sl_standard: entry && entry.sl_standard ? limitText(entry.sl_standard) : '',
        status: status, remark: remark,
      });
    });

    /* WHO combined nitrate + nitrite rule: the sum of the ratio of each to its
     * own guideline value must not exceed 1. A sample can pass both individual
     * checks yet fail this, so it is applied only when neither is individually
     * in exceedance. */
    var combined = nitrateNitriteIndex(sample, table);
    if (combined && combined.ratio > 1.0 &&
        combined.no3 <= combined.gv3 && combined.no2 <= combined.gv2) {
      rows.push({
        parameter: 'Nitrate + nitrite (combined)',
        value: pyRound(combined.ratio, 2), unit: 'ratio', below_detection: false,
        who_health: '<= 1', who_aesthetic: '', sl_standard: '',
        status: 'exceeds_health',
        remark: 'The combined index (' + formatG(combined.no3) + '/' +
          formatG(combined.gv3) + ' + ' + formatG(combined.no2) + '/' +
          formatG(combined.gv2) + ' = ' + combined.ratio.toFixed(2) + ') exceeds ' +
          '1; the WHO combined nitrate and nitrite limit is not met even though ' +
          'each is within its own guideline value.',
      });
      flags.push({
        level: 'warning', code: 'nitrate_nitrite_combined',
        message: 'Combined nitrate + nitrite index exceeds 1 (WHO); treat as a ' +
          'health exceedance.',
      });
    }

    var ionic = ionicBalance(sample);
    if (ionic && ionic.flag) flags.push(ionic.flag);
    var corrosivity = assessCorrosivity(sample);
    flags = flags.concat(corrosivity.flags);
    var wqi = computeWqi(sample, standardsRows);
    var healthRisk = assessHealthRisk(sample);
    if (healthRisk) flags = flags.concat(healthRisk.flags);

    var assessment = {
      sample: sample, rows: rows, ionic: ionic, corrosivity: corrosivity,
      wqi: wqi, health_risk: healthRisk, flags: flags,
    };
    assessment.health_exceedances = rows.filter(function (r) {
      return r.status === 'exceeds_health';
    });
    assessment.national_exceedances = rows.filter(function (r) {
      return r.status === 'exceeds_national';
    });
    assessment.aesthetic_exceedances = rows.filter(function (r) {
      return r.status === 'exceeds_aesthetic' || r.status === 'exceeds_national';
    });
    assessment.verdict = qualityVerdict(assessment);
    return assessment;
  }

  /* One-line suitability statement for the reports. */
  function qualityVerdict(assessment) {
    var health = assessment.health_exceedances;
    var national = assessment.national_exceedances;
    var acceptability = assessment.rows.filter(function (r) {
      return r.status === 'exceeds_aesthetic';
    });
    var names;
    if (health.length) {
      names = health.map(function (r) { return r.parameter; }).join(', ');
      return 'The water does not meet the health based guideline value(s) for: ' +
        names + '. Treatment or an alternative source is required before the ' +
        'water is used for drinking.';
    }
    if (national.length) {
      names = national.map(function (r) { return r.parameter; }).join(', ');
      var extra = acceptability.length
        ? ' Acceptability limits are also exceeded for: ' +
          acceptability.map(function (r) { return r.parameter; }).join(', ') + '.'
        : '';
      return 'The water meets the WHO health based guideline values, but does ' +
        'not comply with the national standard limit(s) for: ' + names + '.' +
        extra + ' Treatment is required before the supply can be accepted ' +
        'against the national standard; check whether the limit exceeded is a ' +
        'health or an acceptability limit.';
    }
    if (acceptability.length) {
      names = acceptability.map(function (r) { return r.parameter; }).join(', ');
      return 'The water meets all health based guideline values. Acceptability ' +
        '(aesthetic) limits are exceeded for: ' + names + '. The water is usable ' +
        'for drinking, although taste, odour or staining complaints may arise; ' +
        'simple treatment is advisable.';
    }
    return 'All measured parameters comply with the WHO guideline values and ' +
      'the national standard limits applied. The water is suitable for drinking ' +
      'on the basis of the parameters tested.';
  }

  /* --- Piper and Stiff geometry --------------------------------------------
   * Returned as plain coordinates so the chart module can draw them and the
   * report module can rasterise the same numbers.
   */

  var SQ3 = Math.sqrt(3.0);

  /* Barycentric (a bottom-left, b bottom-right, c top) to xy. */
  function ternaryXy(a, b, c, origin, size) {
    var total = a + b + c;
    if (total <= 0) return null;
    a /= total; b /= total; c /= total;
    return {
      x: origin[0] + (b + 0.5 * c) * size,
      y: origin[1] + (SQ3 / 2.0) * c * size,
    };
  }

  /* The three Piper points for one sample: cation triangle, anion triangle and
   * the diamond, the latter being the intersection of the +60 degree line
   * through the cation point and the -60 degree line through the anion point. */
  function piperPoints(sample, geometry) {
    var g = geometry || { size: 1.0, gap: 0.18 };
    var size = g.size, gap = g.gap;
    var catOrigin = [0, 0], anOrigin = [size + gap, 0];
    var ionic = ionicBalance(sample);
    if (!ionic) return null;
    var cat = ionic.cations_meq, an = ionic.anions_meq;
    var ca = cat.calcium || 0, mg = cat.magnesium || 0;
    var nak = (cat.sodium || 0) + (cat.potassium || 0);
    var cl = an.chloride || 0, so4 = an.sulfate || 0;
    var hco3 = (an.bicarbonate || 0) + (an.carbonate || 0);

    var pCat = ternaryXy(ca, nak, mg, catOrigin, size);
    var pAn = ternaryXy(hco3, cl, so4, anOrigin, size);
    if (!pCat || !pAn) return null;
    var xd = 0.5 * (pCat.x + pAn.x) + (pAn.y - pCat.y) / (2.0 * SQ3);
    var yd = pCat.y + SQ3 * (xd - pCat.x);
    return {
      cation: pCat, anion: pAn, diamond: { x: xd, y: yd },
      fractions: {
        ca: ca, mg: mg, nak: nak, cl: cl, so4: so4, hco3: hco3,
      },
      facies: piperFacies(ca, mg, nak, cl, so4, hco3),
    };
  }

  /* The dominant-ion name a hydrogeologist would write in the report. */
  function piperFacies(ca, mg, nak, cl, so4, hco3) {
    var catTotal = ca + mg + nak, anTotal = cl + so4 + hco3;
    if (catTotal <= 0 || anTotal <= 0) return '';
    var cations = [['Ca', ca], ['Mg', mg], ['Na+K', nak]]
      .sort(function (a, b) { return b[1] - a[1]; });
    var anions = [['Cl', cl], ['SO4', so4], ['HCO3', hco3]]
      .sort(function (a, b) { return b[1] - a[1]; });
    var catName = cations[0][1] / catTotal >= 0.5 ? cations[0][0] : 'mixed';
    var anName = anions[0][1] / anTotal >= 0.5 ? anions[0][0] : 'mixed';
    if (catName === 'mixed' && anName === 'mixed') return 'mixed water type';
    return catName + '-' + anName + ' water type';
  }

  /* Stiff polygon: Na+K / Ca / Mg on the left, Cl / HCO3 / SO4 on the right. */
  function stiffRows(sample) {
    var ionic = ionicBalance(sample);
    if (!ionic) return null;
    var cat = ionic.cations_meq, an = ionic.anions_meq;
    return [
      { left: (cat.sodium || 0) + (cat.potassium || 0), right: an.chloride || 0,
        leftLabel: 'Na+K', rightLabel: 'Cl' },
      { left: cat.calcium || 0, right: (an.bicarbonate || 0) + (an.carbonate || 0),
        leftLabel: 'Ca', rightLabel: 'HCO3' },
      { left: cat.magnesium || 0, right: an.sulfate || 0,
        leftLabel: 'Mg', rightLabel: 'SO4' },
    ];
  }

  Object.assign(C, {
    parseLimit: parseLimit, limitExceededBy: limitExceededBy, limitText: limitText,
    normaliseParameter: normaliseParameter, loadStandards: loadStandards,
    sampleValue: sampleValue, ionicBalance: ionicBalance,
    computeWqi: computeWqi, assessHealthRisk: assessHealthRisk,
    assessCorrosivity: assessCorrosivity, assessSample: assessSample,
    qualityVerdict: qualityVerdict, STATUS_ORDER: STATUS_ORDER,
    ternaryXy: ternaryXy, piperPoints: piperPoints, piperFacies: piperFacies,
    stiffRows: stiffRows,
  });

  /* ========================================================= borehole design
   * groundwater/design/designer.py. Plain casing from surface, screens against
   * the aquifer zones and below the static level by a margin, a sump below the
   * lowest screen, gravel pack from the bottom to above the top screen,
   * backfill up to the sanitary seal, and cement from surface.
   */

  /* Lithology phrases that mark an interval as a screening target, and phrases
   * that negate it, so "dry, no water struck" is not screened just because it
   * contains the word water. */
  var AQUIFER_WORDS = ['fracture', 'fractured', 'fractures', 'aquifer'];
  var AQUIFER_PHRASES = ['water-bearing', 'water bearing', 'waterbearing',
    'water strike', 'water struck', 'water inflow'];
  var NEGATION_PHRASES = ['no water', 'not reached', 'without water',
    'water table not'];

  function targetZones(log, interpretation, swl, totalDepth, rules) {
    var basis = [], zones = [];
    if (log && log.water_strikes_m && log.water_strikes_m.length) {
      log.water_strikes_m.forEach(function (strike) {
        zones.push([Math.max(strike - 1.0, 0.0), strike + 5.0]);
      });
      basis.push('screens positioned against the water strikes recorded in ' +
        'the drilling log (' + log.water_strikes_m.map(function (w) {
          return formatG(w) + ' m';
        }).join(', ') + ')');
    }
    if (log && log.intervals) {
      log.intervals.forEach(function (interval) {
        var text = String(interval.description || '').toLowerCase();
        if (NEGATION_PHRASES.some(function (n) { return text.indexOf(n) >= 0; })) return;
        var words = text.match(/[a-z]+/g) || [];
        var hit = words.some(function (w) { return AQUIFER_WORDS.indexOf(w) >= 0; }) ||
          AQUIFER_PHRASES.some(function (p) { return text.indexOf(p) >= 0; });
        if (hit) zones.push([interval.top_m, interval.bottom_m]);
      });
    }
    if (!zones.length && interpretation && interpretation.water_zones.length) {
      zones = interpretation.water_zones.map(function (z) { return [z[0], z[1]]; });
      basis.push('screens positioned against the low resistivity zones of the ' +
        'VES interpretation (' + interpretation.water_zones.map(function (z) {
          return Math.trunc(z[0]) + '-' + Math.trunc(z[1]) + ' m';
        }).join(', ') + ')');
    }

    /* clip to the hole, keep below the static level margin, round to 0.5 m */
    var floor = (swl || 0.0) + rules.min_screen_below_swl_m;
    var clipped = [];
    zones.forEach(function (z) {
      var top = Math.ceil(Math.max(z[0], floor) * 2.0) / 2.0;
      var bottom = Math.floor(Math.min(z[1], totalDepth - rules.sump_length_m) * 2.0) / 2.0;
      if (bottom - top >= 1.0) clipped.push([top, bottom]);
    });
    clipped.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var merged = [];
    clipped.forEach(function (zone) {
      var last = merged[merged.length - 1];
      if (last && zone[0] <= last[1] + 1.0) last[1] = Math.max(last[1], zone[1]);
      else merged.push([zone[0], zone[1]]);
    });
    return { zones: merged, basis: basis };
  }

  /* Clean up analyst-supplied screen intervals without silently moving them:
   * anything the clipping actually changed is flagged rather than absorbed,
   * because a screen that has quietly moved is worse than one refused. */
  function analystScreens(screensM, totalDepthM, rules, flags) {
    var sumpTop = totalDepthM - rules.sump_length_m;
    var cleaned = [];
    screensM.map(function (s) { return [Number(s[0]), Number(s[1])]; })
      .sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; })
      .forEach(function (pair) {
        var top = pair[0], bottom = pair[1];
        var clippedTop = Math.max(0.0, Math.min(top, sumpTop));
        var clippedBottom = Math.max(clippedTop, Math.min(bottom, sumpTop));
        if (clippedBottom - clippedTop < 0.5) {
          flags.push({
            level: 'warning', code: 'screen_dropped',
            message: 'A screen interval at ' + formatG(top) + '-' + formatG(bottom) +
              ' m does not fit above the ' + formatG(rules.sump_length_m) +
              ' m sump and was dropped.',
          });
          return;
        }
        if (clippedTop !== top || clippedBottom !== bottom) {
          flags.push({
            level: 'info', code: 'screen_clipped',
            message: 'Screen ' + formatG(top) + '-' + formatG(bottom) +
              ' m was clipped to ' + formatG(clippedTop) + '-' +
              formatG(clippedBottom) + ' m to stay inside the hole and above ' +
              'the sump.',
          });
        }
        var last = cleaned[cleaned.length - 1];
        if (last && clippedTop <= last[1]) last[1] = Math.max(last[1], clippedBottom);
        else cleaned.push([clippedTop, clippedBottom]);
      });
    if (!cleaned.length) throw new Error('no usable screen interval was supplied');
    return {
      screens: cleaned,
      basis: ['screen intervals set by the analyst on the borehole section (' +
        cleaned.map(function (s) {
          return formatG(s[0]) + '-' + formatG(s[1]) + ' m';
        }).join(', ') + ')'],
    };
  }

  function assembleDesign(spec) {
    var screens = spec.screens, rules = spec.rules;
    var totalDepthM = spec.totalDepthM, swl = spec.swl;
    var segments = [], cursor = 0.0;
    var sumpTop = totalDepthM - rules.sump_length_m;
    screens.forEach(function (s) {
      if (s[0] > cursor) segments.push({ top_m: cursor, bottom_m: s[0], kind: 'plain' });
      segments.push({ top_m: s[0], bottom_m: s[1], kind: 'screen' });
      cursor = s[1];
    });
    if (cursor < sumpTop) segments.push({ top_m: cursor, bottom_m: sumpTop, kind: 'plain' });
    segments.push({ top_m: sumpTop, bottom_m: totalDepthM, kind: 'sump' });
    segments.forEach(function (s) { s.length_m = s.bottom_m - s.top_m; });

    var topScreen = screens[0][0];
    var gravelTop = Math.max(topScreen - rules.gravel_pack_above_top_screen_m,
      rules.sanitary_seal_depth_m);
    var gravel = [gravelTop, totalDepthM];
    var seal = [0.0, rules.sanitary_seal_depth_m];
    var backfill = [rules.sanitary_seal_depth_m, gravelTop];

    var basis = spec.basis.concat([
      formatG(rules.casing_diameter_in) + ' inch ' + rules.casing_material +
        ' casing in a ' + formatG(rules.borehole_diameter_in) + ' inch hole',
      'gravel pack (' + rules.gravel_pack_material + ') from ' +
        gravel[0].toFixed(0) + ' m to the bottom, ' +
        formatG(rules.gravel_pack_above_top_screen_m) + ' m above the top screen',
      'cement sanitary seal from surface to ' +
        formatG(rules.sanitary_seal_depth_m) + ' m with ' + rules.apron_note,
      'screens kept at least ' + formatG(rules.min_screen_below_swl_m) +
        ' m below the static water level',
    ]);

    var flags = spec.flags;
    if (swl !== null && swl !== undefined && topScreen < swl) {
      flags.push({
        level: 'warning', code: 'screen_above_swl',
        message: 'The top screen is above the static water level; check the design.',
      });
    }

    var design = {
      total_depth_m: totalDepthM,
      borehole_diameter_in: rules.borehole_diameter_in,
      casing_diameter_in: rules.casing_diameter_in,
      casing_material: rules.casing_material,
      segments: segments,
      gravel_pack: gravel,
      backfill: backfill,
      sanitary_seal: seal,
      stickup_m: rules.stickup_m,
      screen_slot_mm: rules.screen_slot_mm,
      water_strikes_m: spec.log && spec.log.water_strikes_m
        ? spec.log.water_strikes_m.slice() : [],
      static_water_level_m: swl === undefined ? null : swl,
      pump_intake_m: spec.pumpIntakeM === undefined ? null : spec.pumpIntakeM,
      design_basis: basis,
      flags: flags,
    };
    design.screens = segments.filter(function (s) { return s.kind === 'screen'; });
    design.total_screen_length_m = design.screens.reduce(function (a, s) {
      return a + s.length_m;
    }, 0);
    return design;
  }

  function designSummaryRows(design) {
    var rows = [
      ['Total depth', design.total_depth_m.toFixed(0) + ' m'],
      ['Drilled diameter', formatG(design.borehole_diameter_in) + '"'],
      ['Casing', formatG(design.casing_diameter_in) + '" ' + design.casing_material +
        ', stick-up ' + design.stickup_m.toFixed(1) + ' m'],
      ['Screens', design.screens.map(function (s) {
        return s.top_m.toFixed(0) + '-' + s.bottom_m.toFixed(0) + ' m';
      }).join('; ') + ' (slot ' + formatG(design.screen_slot_mm) + ' mm)'],
      ['Gravel pack', design.gravel_pack[0].toFixed(0) + '-' +
        design.gravel_pack[1].toFixed(0) + ' m'],
      ['Backfill', design.backfill[0].toFixed(0) + '-' +
        design.backfill[1].toFixed(0) + ' m'],
      ['Sanitary seal', design.sanitary_seal[0].toFixed(0) + '-' +
        design.sanitary_seal[1].toFixed(0) + ' m cement grout'],
    ];
    if (design.static_water_level_m !== null) {
      rows.push(['Static water level', design.static_water_level_m.toFixed(2) + ' m']);
    }
    if (design.water_strikes_m.length) {
      rows.push(['Water strikes', design.water_strikes_m.map(function (w) {
        return formatG(w) + ' m';
      }).join(', ')]);
    }
    if (design.pump_intake_m !== null && design.pump_intake_m !== undefined) {
      rows.push(['Recommended pump intake', design.pump_intake_m.toFixed(0) + ' m']);
    }
    return rows;
  }

  function designBorehole(options) {
    var opts = options || {};
    var rules = opts.rules || defaultConfig().design;
    var flags = [];
    var log = opts.log || null;
    var interpretation = opts.interpretation || null;
    var totalDepthM = opts.totalDepthM;

    if (totalDepthM === null || totalDepthM === undefined) {
      if (log && log.total_depth_m) totalDepthM = Number(log.total_depth_m);
      else if (interpretation) totalDepthM = Number(interpretation.max_drilling_depth_m);
      else throw new Error('total depth is needed (drilling log or VES interpretation)');
    }
    var swl = opts.staticWaterLevelM;
    if (swl === undefined) swl = null;

    if (opts.screensM && opts.screensM.length) {
      var chosen = analystScreens(opts.screensM, totalDepthM, rules, flags);
      return assembleDesign({
        screens: chosen.screens, basis: chosen.basis, flags: flags,
        totalDepthM: totalDepthM, swl: swl, pumpIntakeM: opts.pumpIntakeM,
        rules: rules, log: log,
      });
    }

    var targeted = targetZones(log, interpretation, swl, totalDepthM, rules);
    var basis = targeted.basis;
    var screens = targeted.zones.map(function (z) { return [z[0], z[1]]; });

    if (!screens.length) {
      /* fall back: screen the bottom third of the hole below the SWL margin */
      var floor = (swl || 0.0) + rules.min_screen_below_swl_m;
      var sumpTop = Math.max(totalDepthM - rules.sump_length_m, 0.0);
      var bottom = sumpTop;
      var top = Math.max(totalDepthM * 2.0 / 3.0, floor);
      if (bottom - top < 3.0) {
        top = Math.max(bottom - rules.screen_length_default_m, floor);
      }
      if (bottom - top < 1.0) {
        /* The static water level margin plus the sump leave no room for a
         * valid screen. Clamp to a positive interval just above the sump so
         * the geometry stays valid and flag it loudly rather than emitting
         * a negative-length screen. */
        top = Math.max(Math.min(bottom - rules.screen_length_default_m, bottom - 1.0), 0.0);
        flags.push({
          level: 'error', code: 'hole_too_shallow',
          message: 'Static water level plus the ' +
            formatG(rules.min_screen_below_swl_m) + ' m minimum screen depth ' +
            'leaves no room for a screen above the sump in this ' +
            formatG(totalDepthM) + ' m hole. Screen placement is a best effort ' +
            'only - deepen the hole or revise the design manually.',
        });
      }
      screens = [[top, bottom]];
      basis.push('no aquifer intervals identified from the data; screens ' +
        'default to the lower third of the hole');
      flags.push({
        level: 'warning', code: 'default_screens',
        message: 'Screen placement fell back to the lower third of the hole; ' +
          'review against the drilling observations.',
      });
    }

    /* trim overall screen length to a sensible share of the hole, keeping the
     * deepest sections, which sit in the main fractured zone */
    var totalScreen = screens.reduce(function (a, s) { return a + (s[1] - s[0]); }, 0);
    if (totalScreen > 0.6 * totalDepthM) {
      var keep = [], budget = 0.6 * totalDepthM;
      for (var i = screens.length - 1; i >= 0; i--) {
        var t = screens[i][0], b = screens[i][1];
        var length = b - t;
        if (budget <= 0) break;
        if (length > budget) { t = b - budget; length = budget; }
        keep.push([t, b]);
        budget -= length;
      }
      screens = keep.sort(function (x, y) { return x[0] - y[0] || x[1] - y[1]; });
      flags.push({
        level: 'info', code: 'screen_trimmed',
        message: 'Total screen length was trimmed to 60 percent of the hole, ' +
          'keeping the deepest aquifer sections.',
      });
    }

    return assembleDesign({
      screens: screens, basis: basis, flags: flags, totalDepthM: totalDepthM,
      swl: swl, pumpIntakeM: opts.pumpIntakeM, rules: rules, log: log,
    });
  }

  /* ================================================================ costing
   * groundwater/costing/*. Follows the RWSN Borehole Costing Model: every line
   * carries a construction stage and a resource category so the same items
   * roll up along both axes, and the contractor's COST is kept distinct from
   * the client's PRICE (cost + overheads + margin).
   */

  var STAGES = ['Siting', 'Mobilisation', 'Drilling', 'Casing', 'Development',
    'Test pumping', 'Water quality', 'Wellhead'];
  var RESOURCE_CATEGORIES = ['equipment', 'labour', 'consumables', 'fuel', 'vehicles'];
  var DEFAULT_EXCHANGE_RATE_SLE_PER_USD = 23.0;
  var DRY_STAGES = ['Siting', 'Mobilisation', 'Drilling'];

  function loadRates(rows) {
    var source = rows || (GWT.data && GWT.data.costItems) || [];
    return source.map(function (row) {
      return {
        code: String(row.code || '').trim(),
        stage: String(row.stage || '').trim(),
        category: String(row.category || '').trim().toLowerCase(),
        item: String(row.item || '').trim(),
        unit: String(row.unit || '').trim(),
        quantity_basis: String(row.quantity_basis || '').trim(),
        unit_cost_usd: Number(row.unit_cost_usd),
        note: String(row.note || '').trim(),
      };
    });
  }

  /* Volume of the borehole/casing annulus; the allowance covers washout and
   * placement losses (1.3 is common for gravel pack ordering). */
  function annulusVolumeM3(boreholeDiameterIn, casingDiameterIn, intervalM, allowance) {
    var toM = 0.0254;
    var dBore = boreholeDiameterIn * toM, dCasing = casingDiameterIn * toM;
    var area = Math.PI / 4.0 * Math.max(0.0, dBore * dBore - dCasing * dCasing);
    return area * Math.max(0.0, intervalM) * (allowance === undefined ? 1.0 : allowance);
  }

  function costingInputs(values) {
    return Object.assign({
      total_depth_m: 0, overburden_m: null, casing_m: null, screen_m: null,
      borehole_diameter_in: 6.5, casing_diameter_in: 5.0,
      gravel_interval_m: null, cement_bags: null, crew_days: null,
      development_hours: 6.0, test_pumping_hours: 30.0,
      mobilisation_distance_km: 0.0, wq_samples: 1, handpumps: 1,
    }, values || {});
  }

  /* Fill missing fields from documented rules of thumb, recording every
   * assumption on the estimate so nothing is hidden. */
  function resolveCostingInputs(inputs) {
    var r = Object.assign({}, inputs);
    var assumptions = [];
    if (r.overburden_m === null || r.overburden_m === undefined) {
      r.overburden_m = Math.min(30.0, 0.5 * r.total_depth_m);
      assumptions.push('Overburden thickness assumed ' + fmtNum(r.overburden_m) +
        ' m (half the total depth, at most 30 m); supply the real split from ' +
        'the drilling log or the VES interpretation.');
    }
    r.overburden_m = Math.min(r.overburden_m, r.total_depth_m);
    if (r.screen_m === null || r.screen_m === undefined) {
      r.screen_m = 9.0;
      assumptions.push('Screen length assumed 9 m (design default).');
    }
    if (r.casing_m === null || r.casing_m === undefined) {
      r.casing_m = Math.max(0.0, r.total_depth_m + 0.5 - r.screen_m);
      assumptions.push('Plain casing length taken as ' + fmtNum(r.casing_m) +
        ' m (total depth plus 0.5 m stick-up minus the screen length).');
    }
    if (r.gravel_interval_m === null || r.gravel_interval_m === undefined) {
      r.gravel_interval_m = Math.max(0.0, r.total_depth_m - 15.0);
      assumptions.push('Gravel packed interval assumed ' +
        fmtNum(r.gravel_interval_m) + ' m (from 15 m below ground to the ' +
        'bottom of the borehole).');
    }
    if (r.cement_bags === null || r.cement_bags === undefined) {
      var sealVolume = annulusVolumeM3(r.borehole_diameter_in, r.casing_diameter_in, 15.0);
      r.cement_bags = Math.max(4.0, Math.ceil(sealVolume * 20.0));
      assumptions.push('Cement estimated at ' + fmtNum(r.cement_bags) +
        ' bags for the grout seal (about 20 bags per cubic metre of annulus).');
    }
    if (r.crew_days === null || r.crew_days === undefined) {
      r.crew_days = Math.ceil(r.total_depth_m / 25.0) + 4;
      assumptions.push('Crew time assumed ' + fmtNum(r.crew_days) + ' days on ' +
        'site (drilling at 25 m per day plus four days for moving, set up, ' +
        'development, testing and completion).');
    }
    r.bedrock_m = Math.max(0.0, r.total_depth_m - (r.overburden_m || 0.0));
    r.gravel_pack_m3 = annulusVolumeM3(r.borehole_diameter_in, r.casing_diameter_in,
      r.gravel_interval_m || 0.0, 1.3);
    return { inputs: r, assumptions: assumptions };
  }

  /* Casing and screen lengths, diameters and the gravel packed interval come
   * straight from the design so the bill of quantities always matches the
   * drawing. */
  function inputsFromDesign(design, options) {
    var opts = options || {};
    var screenM = design.total_screen_length_m;
    return costingInputs({
      total_depth_m: design.total_depth_m,
      overburden_m: opts.overburdenM === undefined ? null : opts.overburdenM,
      casing_m: Math.max(0.0, design.total_depth_m + design.stickup_m - screenM),
      screen_m: screenM,
      borehole_diameter_in: design.borehole_diameter_in,
      casing_diameter_in: design.casing_diameter_in,
      gravel_interval_m: Math.max(0.0, design.gravel_pack[1] - design.gravel_pack[0]),
      mobilisation_distance_km: opts.mobilisationDistanceKm || 0.0,
    });
  }

  function quantityFor(basis, inputs) {
    var table = {
      lump_sum: 1.0,
      per_km_round_trip: 2.0 * inputs.mobilisation_distance_km,
      per_crew_day: inputs.crew_days || 0.0,
      per_m_drilled: inputs.total_depth_m,
      per_m_overburden: inputs.overburden_m || 0.0,
      per_m_bedrock: inputs.bedrock_m,
      per_m_casing: inputs.casing_m || 0.0,
      per_m_screen: inputs.screen_m || 0.0,
      per_m3_gravel: inputs.gravel_pack_m3,
      per_bag_cement: inputs.cement_bags || 0.0,
      per_hour_development: inputs.development_hours,
      per_hour_test: inputs.test_pumping_hours,
      per_sample: Number(inputs.wq_samples),
      per_handpump: Number(inputs.handpumps),
    };
    return basis in table ? table[basis] : null;
  }

  /* Percentage defaults follow the RWSN costing and pricing guidance:
   * overheads on top of direct works cost, then a margin that keeps the
   * business viable; the contingency is a client-side planning allowance,
   * shown separately so the contract price stays honest. */
  function estimateBoreholeCost(inputs, rates, options) {
    var opts = options || {};
    if (inputs.total_depth_m <= 0) throw new Error('total depth must be positive');
    var resolved = resolveCostingInputs(inputs);
    var catalogue = rates || loadRates();
    var items = [], flags = [];

    catalogue.forEach(function (rate) {
      var quantity = quantityFor(rate.quantity_basis, resolved.inputs);
      if (quantity === null) {
        flags.push({
          level: 'warning', code: 'unknown_quantity_basis',
          message: 'Rate ' + rate.code + " uses unknown quantity basis '" +
            rate.quantity_basis + "' and was skipped.",
          context: rate.code,
        });
        return;
      }
      if (quantity <= 0) return;
      items.push({
        code: rate.code, stage: rate.stage, category: rate.category,
        item: rate.item, unit: rate.unit, quantity: quantity,
        unit_cost_usd: rate.unit_cost_usd, note: rate.note,
        amount_usd: quantity * rate.unit_cost_usd,
      });
    });

    if (resolved.inputs.mobilisation_distance_km <= 0) {
      flags.push({
        level: 'info', code: 'no_mobilisation_distance',
        message: 'Mobilisation distance is zero; transport costs are not ' +
          "included. Enter the one way distance from the contractor's base " +
          'to the site.',
      });
    }

    return buildEstimate(items, resolved.inputs, resolved.assumptions, flags, {
      overheads_percent: opts.overheadsPercent === undefined ? 15.0 : opts.overheadsPercent,
      margin_percent: opts.marginPercent === undefined ? 20.0 : opts.marginPercent,
      contingency_percent: opts.contingencyPercent === undefined ? 10.0 : opts.contingencyPercent,
      vat_percent: opts.vatPercent === undefined ? 0.0 : opts.vatPercent,
      exchange_rate_sle_per_usd: opts.exchangeRate === undefined
        ? DEFAULT_EXCHANGE_RATE_SLE_PER_USD : opts.exchangeRate,
    });
  }

  function buildEstimate(items, inputs, assumptions, flags, pct) {
    var direct = items.reduce(function (a, i) { return a + i.amount_usd; }, 0);
    var overheads = direct * pct.overheads_percent / 100.0;
    var totalCost = direct + overheads;
    var margin = totalCost * pct.margin_percent / 100.0;
    var price = totalCost + margin;
    var vat = price * pct.vat_percent / 100.0;
    var priceWithVat = price + vat;
    var contingency = priceWithVat * pct.contingency_percent / 100.0;

    var estimate = Object.assign({
      items: items, inputs: inputs, assumptions: assumptions, flags: flags,
      direct_cost_usd: direct,
      overheads_usd: overheads,
      total_cost_usd: totalCost,
      margin_usd: margin,
      price_usd: price,
      vat_usd: vat,
      price_with_vat_usd: priceWithVat,
      contingency_usd: contingency,
      budget_usd: priceWithVat + contingency,
      cost_per_meter_usd: inputs.total_depth_m ? totalCost / inputs.total_depth_m : 0.0,
    }, pct);

    estimate.in_local = function (usd) { return usd * pct.exchange_rate_sle_per_usd; };
    /* Under a no-water-no-pay contract the price of each successful borehole
     * must carry the cost of the expected failures. */
    estimate.price_per_successful_well_usd = function (successRatePercent) {
      if (!(successRatePercent > 0 && successRatePercent <= 100)) {
        throw new Error('success rate must be in (0, 100]');
      }
      return priceWithVat / (successRatePercent / 100.0);
    };
    estimate.by_stage = function () {
      var totals = {}, order = STAGES.slice();
      STAGES.forEach(function (s) { totals[s] = 0.0; });
      items.forEach(function (i) {
        if (!(i.stage in totals)) { totals[i.stage] = 0.0; order.push(i.stage); }
        totals[i.stage] += i.amount_usd;
      });
      return order.filter(function (s) { return totals[s] > 0; })
        .map(function (s) { return [s, totals[s]]; });
    };
    estimate.by_category = function () {
      var totals = {}, order = RESOURCE_CATEGORIES.slice();
      RESOURCE_CATEGORIES.forEach(function (c) { totals[c] = 0.0; });
      items.forEach(function (i) {
        if (!(i.category in totals)) { totals[i.category] = 0.0; order.push(i.category); }
        totals[i.category] += i.amount_usd;
      });
      return order.filter(function (c) { return totals[c] > 0; })
        .map(function (c) { return [c, totals[c]]; });
    };
    estimate.boq_rows = function () {
      return items.slice().sort(function (a, b) {
        var ia = STAGES.indexOf(a.stage), ib = STAGES.indexOf(b.stage);
        ia = ia < 0 ? 99 : ia; ib = ib < 0 ? 99 : ib;
        return ia - ib || (a.code < b.code ? -1 : a.code > b.code ? 1 : 0);
      }).map(function (i) {
        return {
          Code: i.code, Stage: i.stage, Item: i.item, Unit: i.unit,
          Quantity: pyRound(i.quantity, 2),
          'Rate (USD)': pyRound(i.unit_cost_usd, 2),
          'Amount (USD)': pyRound(i.amount_usd, 2),
        };
      });
    };
    return estimate;
  }

  /* Cost a package of boreholes sharing one mobilisation: mobilise the rig
   * once, move it between nearby sites, and let the successful wells carry the
   * cost of the expected dry holes. A dry attempt only pays for siting, set up
   * and drilling. */
  function estimateProgrammeCost(perWell, nBoreholes, options) {
    var opts = options || {};
    if (nBoreholes < 1) throw new Error('a programme needs at least one borehole');
    var successRate = opts.successRatePercent === undefined ? 100.0 : opts.successRatePercent;
    if (!(successRate > 0 && successRate <= 100)) {
      throw new Error('success rate must be in (0, 100]');
    }
    var catalogue = opts.rates || loadRates();
    var interSiteKm = opts.interSiteDistanceKm === undefined ? 15.0 : opts.interSiteDistanceKm;
    /* Round before the ceiling: 21 wells at 35 percent is exactly 60 attempts,
     * but the division lands on 60.000000000000007 and ceil() then budgets a
     * 61st - a whole phantom dry borehole in the programme cost. */
    var nAttempted = Math.ceil(pyRound(nBoreholes / (successRate / 100.0), 9));

    var wellInputs = Object.assign({}, perWell, { mobilisation_distance_km: 0.0 });
    var well = estimateBoreholeCost(wellInputs, catalogue, {
      overheadsPercent: opts.overheadsPercent, marginPercent: opts.marginPercent,
      contingencyPercent: opts.contingencyPercent, vatPercent: opts.vatPercent,
      exchangeRate: opts.exchangeRate,
    });

    var dryCost = well.by_stage().filter(function (sv) {
      return DRY_STAGES.indexOf(sv[0]) >= 0;
    }).reduce(function (a, sv) { return a + sv[1]; }, 0);

    var kmRate = catalogue.filter(function (r) {
      return r.quantity_basis === 'per_km_round_trip';
    }).reduce(function (a, r) { return a + r.unit_cost_usd; }, 0);
    var transportKm = 2.0 * perWell.mobilisation_distance_km +
      Math.max(0, nAttempted - 1) * interSiteKm;
    var transport = kmRate * transportKm;

    var assumptions = well.assumptions.slice();
    assumptions.push('One rig mobilised once for the package (' +
      formatG(perWell.mobilisation_distance_km) + ' km each way) with ' +
      Math.max(0, nAttempted - 1) + ' inter-site moves of ' +
      formatG(interSiteKm) + ' km on average.');
    if (nAttempted > nBoreholes) {
      assumptions.push((nAttempted - nBoreholes) + ' dry attempt(s) expected at ' +
        formatG(successRate) + '% siting success; a dry attempt pays for ' +
        'siting, set up and drilling only, costed at the full crew time ' +
        '(a conservative allowance).');
    }

    var directCost = nBoreholes * well.direct_cost_usd +
      (nAttempted - nBoreholes) * dryCost + transport;
    var totalCost = directCost * (1 + well.overheads_percent / 100.0);
    var price = totalCost * (1 + well.margin_percent / 100.0);
    var priceWithVat = price * (1 + well.vat_percent / 100.0);

    var programme = {
      n_successful: nBoreholes, n_attempted: nAttempted,
      success_rate_percent: successRate, well_estimate: well,
      dry_attempt_cost_usd: dryCost, transport_cost_usd: transport,
      overheads_percent: well.overheads_percent, margin_percent: well.margin_percent,
      contingency_percent: well.contingency_percent, vat_percent: well.vat_percent,
      exchange_rate_sle_per_usd: well.exchange_rate_sle_per_usd,
      assumptions: assumptions,
      direct_cost_usd: directCost,
      total_cost_usd: totalCost,
      price_usd: price,
      price_with_vat_usd: priceWithVat,
      budget_usd: priceWithVat * (1 + well.contingency_percent / 100.0),
      price_per_successful_well_usd: priceWithVat / nBoreholes,
      dry_attempts_cost_usd: (nAttempted - nBoreholes) * dryCost,
    };
    programme.in_local = function (usd) {
      return usd * well.exchange_rate_sle_per_usd;
    };
    return programme;
  }

  /* ============================================================ supervision
   * groundwater/supervision/*. Checklist content follows RWSN/UNICEF
   * "Supervising Water Well Drilling"; the numeric field checks encode the
   * acceptance criteria a supervisor applies on site.
   */

  var STAGE_TITLES = [
    ['procurement', 'Procurement and contract'],
    ['pre_contract', 'Pre-contract inspection'],
    ['siting', 'Siting'],
    ['mobilisation', 'Mobilisation'],
    ['drilling', 'Drilling'],
    ['design', 'Design and installation'],
    ['development', 'Development and completion'],
    ['demobilisation', 'Demobilisation'],
    ['handover', 'Documentation and handover'],
    ['post_construction', 'Post-construction monitoring'],
  ];
  var STAGE_ORDER = STAGE_TITLES.map(function (s) { return s[0]; });
  var RESPONSE_STATES = ['pending', 'yes', 'no', 'na'];

  function stageTitle(key) {
    for (var i = 0; i < STAGE_TITLES.length; i++) {
      if (STAGE_TITLES[i][0] === key) return STAGE_TITLES[i][1];
    }
    var s = String(key).replace(/_/g, ' ');
    return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
  }

  function loadChecklists(rows) {
    var source = rows || (GWT.data && GWT.data.supervisionChecklists) || [];
    var counters = {};
    return source.map(function (row) {
      var checklist = String(row.checklist || '').trim();
      counters[checklist] = (counters[checklist] || 0) + 1;
      return {
        item_id: checklist + '-' + String(counters[checklist]).padStart(2, '0'),
        checklist: checklist,
        section: String(row.section || '').trim(),
        text: String(row.item || '').trim(),
        critical: String(row.critical || '').trim().toLowerCase() === 'yes',
        guidance: String(row.guidance || '').trim(),
      };
    });
  }

  function loadSeparationDistances(rows) {
    var source = rows || (GWT.data && GWT.data.separationDistances) || [];
    return source.map(function (row) {
      return {
        structure: String(row.structure || '').trim(),
        min_distance_m: Number(row.min_distance_m),
        note: String(row.note || '').trim(),
      };
    });
  }

  function evaluateChecklist(items, responses) {
    var byId = {};
    if (Array.isArray(responses)) {
      responses.forEach(function (r) { byId[r.item_id] = r; });
    } else {
      byId = responses || {};
    }
    var present = {};
    items.forEach(function (i) { present[i.checklist] = true; });
    var stageKeys = STAGE_ORDER.filter(function (k) { return present[k]; });
    Object.keys(present).sort().forEach(function (k) {
      if (stageKeys.indexOf(k) < 0) stageKeys.push(k);
    });

    var stages = [], flags = [];
    stageKeys.forEach(function (key) {
      var stageItems = items.filter(function (i) { return i.checklist === key; });
      var answered = 0, passed = 0, failed = 0, criticalFailed = 0, criticalOpen = 0;
      stageItems.forEach(function (item) {
        var response = byId[item.item_id];
        var status = response ? response.status : 'pending';
        if (RESPONSE_STATES.indexOf(status) < 0) status = 'pending';
        if (status !== 'pending') answered += 1;
        if (status === 'yes' || status === 'na') {
          passed += 1;
        } else if (status === 'no') {
          failed += 1;
          if (item.critical) {
            criticalFailed += 1;
            flags.push({
              level: 'error', code: 'critical_item_failed',
              message: item.text, context: stageTitle(key),
            });
          }
        } else if (item.critical) {
          criticalOpen += 1;
        }
      });
      stages.push({
        stage: key, title: stageTitle(key), total: stageItems.length,
        answered: answered, passed: passed, failed: failed,
        critical_failed: criticalFailed, critical_open: criticalOpen,
        complete: answered === stageItems.length,
        percent: stageItems.length ? 100.0 * answered / stageItems.length : 0.0,
      });
    });

    var total = stages.reduce(function (a, s) { return a + s.total; }, 0);
    var answeredAll = stages.reduce(function (a, s) { return a + s.answered; }, 0);
    var criticalFailures = stages.reduce(function (a, s) { return a + s.critical_failed; }, 0);
    var openCritical = stages.reduce(function (a, s) { return a + s.critical_open; }, 0);
    var verdict;
    if (criticalFailures) {
      verdict = criticalFailures + ' critical item(s) failed; the works should ' +
        'not be accepted until they are resolved.';
    } else if (openCritical) {
      verdict = openCritical + ' critical item(s) still open; complete them ' +
        'before sign off.';
    } else if (answeredAll < total) {
      verdict = 'No critical failures; routine items remain open.';
    } else {
      verdict = 'All checklist items answered with no critical failures.';
    }

    return {
      stages: stages, flags: flags, total: total, answered: answeredAll,
      percent: total ? 100.0 * answeredAll / total : 0.0,
      critical_failures: criticalFailures, critical_open: openCritical,
      verdict: verdict,
    };
  }

  /* --- numeric field acceptance checks ------------------------------------- */

  function fieldCheck(name, passed, measured, limit, message) {
    return {
      name: name, passed: passed, measured: measured, limit: limit,
      message: message,
      status: passed === null ? 'info' : (passed ? 'pass' : 'fail'),
    };
  }

  /* Three 20 litre samples at the end of the pumping test; the settled sand in
   * each must not exceed 10 ppm by volume. */
  function sandContentCheck(samplesCm3, sampleVolumeL) {
    var volume = sampleVolumeL === undefined ? 20.0 : sampleVolumeL;
    var limitCm3 = volume * 1000.0 * 10e-6;
    var worst = samplesCm3 && samplesCm3.length ? arrMax(samplesCm3) : 0.0;
    var has = !!(samplesCm3 && samplesCm3.length);
    var passed = has && worst <= limitCm3;
    return fieldCheck('Sand content', has ? passed : null,
      formatG(worst) + ' cm3 worst of ' + (samplesCm3 || []).length + ' sample(s)',
      formatG(limitCm3) + ' cm3 per ' + formatG(volume) + ' L sample (10 ppm by volume)',
      passed ? 'Sand content acceptable.'
        : 'Excessive sand: check drilling technique, gravel pack and ' +
          "development; a replacement borehole may be at the driller's cost.");
  }

  /* Plumb test: deviation must not exceed two thirds of the casing inner
   * diameter per 30 m of depth. */
  function verticalityCheck(deviationMm, depthM, casingInnerDiameterMm) {
    var allowedMm = (2.0 / 3.0) * casingInnerDiameterMm * (depthM / 30.0);
    var passed = deviationMm <= allowedMm;
    return fieldCheck('Verticality (plumb test)', passed,
      formatG(deviationMm) + ' mm over ' + formatG(depthM) + ' m',
      allowedMm.toFixed(0) + ' mm (two thirds of ' +
        formatG(casingInnerDiameterMm) + ' mm ID per 30 m)',
      passed ? 'Borehole is acceptably straight and vertical.'
        : 'Deviation exceeds the limit; the driller re-drills at own cost.');
  }

  /* Screen entrance velocity rule: open area A >= Q/30 (A in m2, Q in L/s)
   * keeps the entrance velocity below 0.03 m/s. */
  function screenOpenAreaCheck(designYieldLPerS, screenOpenAreaM2) {
    var required = designYieldLPerS / 30.0;
    var passed = screenOpenAreaM2 >= required;
    return fieldCheck('Screen open area', passed,
      formatG(screenOpenAreaM2) + ' m2',
      '>= ' + required.toFixed(3) + ' m2 for Q = ' + formatG(designYieldLPerS) + ' L/s',
      passed ? 'Entrance velocity within 0.03 m/s.'
        : 'Open area too small: turbulent inflow, encrustation and a shortened ' +
          'screen life are likely; use more or larger screen.');
  }

  function specificCapacityCheck(dischargeM3PerH, drawdownM) {
    if (drawdownM <= 0) {
      return fieldCheck('Specific capacity', null, 'n/a',
        '>= 1 m3/h per m for a handpump',
        'Drawdown must be positive to compute specific capacity.');
    }
    var sc = dischargeM3PerH / drawdownM;
    var passed = sc >= 1.0;
    return fieldCheck('Specific capacity', passed, sc.toFixed(2) + ' m3/h per m',
      '>= 1 m3/h per m for a handpump',
      passed ? 'Adequate for a handpump (about 1 m drawdown at 1 m3/h).'
        : 'Below the handpump rule of thumb; review the test data and the pump ' +
          'setting before acceptance.');
  }

  /* Filter pack sizing: pack D50 / aquifer D50 should be 4 to 6. */
  function packAquiferRatioCheck(d50PackMm, d50AquiferMm) {
    if (d50AquiferMm <= 0) {
      return fieldCheck('Pack aquifer ratio', null, 'n/a', '4 to 6',
        'Aquifer D50 must be positive.');
    }
    var ratio = d50PackMm / d50AquiferMm;
    var passed = ratio >= 4.0 && ratio <= 6.0;
    return fieldCheck('Pack aquifer ratio', passed, ratio.toFixed(1),
      '4 to 6 (D50 pack / D50 aquifer)',
      passed ? 'Filter pack correctly sized for the formation.'
        : 'Pack aquifer ratio outside 4 to 6: risk of sand pumping (too coarse) ' +
          'or a choked screen (too fine).');
  }

  /* At least 50 mm all round for placement; a gravel pack needs 70 mm to work
   * as a filter, thinner is only a formation stabiliser. */
  function annularSpaceCheck(boreholeDiameterIn, casingOdMm) {
    var boreholeMm = boreholeDiameterIn * 25.4;
    var annulusMm = (boreholeMm - casingOdMm) / 2.0;
    var passed = annulusMm >= 50.0;
    var note;
    if (annulusMm >= 70.0) {
      note = 'Full gravel pack possible.';
    } else if (passed) {
      note = 'Meets the 50 mm placement minimum, but under 70 mm the annular ' +
        'fill acts as a formation stabiliser rather than a filter pack.';
    } else {
      note = 'Annulus below the 50 mm minimum: gravel is likely to bridge ' +
        'during placement; use a larger bit or smaller casing.';
    }
    return fieldCheck('Annular space', passed, annulusMm.toFixed(0) + ' mm',
      '>= 50 mm (70 mm for a true gravel pack)', note);
  }

  /* Paying per metre invites overstated depths; the daily logs signed by the
   * rig operator and the supervisor are the audit trail. */
  function metresReconciliationCheck(loggedM, claimedM, toleranceM) {
    var tolerance = toleranceM === undefined ? 3.0 : toleranceM;
    var difference = claimedM - loggedM;
    var passed = difference <= tolerance;
    var message;
    if (difference > tolerance) {
      message = 'Invoice claims ' + formatG(difference) + ' m more than the ' +
        'signed daily logs; withhold payment for the unsupported metres and ' +
        'reconcile with the driller.';
    } else if (difference < -tolerance) {
      message = 'Logs record more metres than invoiced; check that the invoice ' +
        'covers all completed work.';
    } else {
      message = 'Invoiced metres are supported by the daily logs.';
    }
    return fieldCheck('Drilled metres reconciliation', passed,
      'logged ' + formatG(loggedM) + ' m, invoiced ' + formatG(claimedM) + ' m',
      'difference within ' + formatG(tolerance) + ' m', message);
  }

  /* Below pH 6.5 galvanised iron risers and rods corrode rapidly, failing
   * within months to two years and shedding iron into the supply. */
  function handpumpCorrosionCheck(ph) {
    var atRisk = ph < 6.5;
    return fieldCheck('Handpump corrosion risk', !atRisk, 'pH ' + formatG(ph),
      '>= 6.5 for galvanised iron components',
      atRisk
        ? 'Corrosive water: specify stainless steel (grade 304/316) or uPVC ' +
          'riser pipes and rods; galvanised iron can fail within months and ' +
          'taint the water with iron.'
        : 'Corrosion risk low; standard components acceptable.');
  }

  /* WHO shock dose: 1 L of 0.2 percent solution per 100 L of well volume gives
   * 20 mg/L; do not pump for at least 4 hours. */
  function disinfectionDose(waterColumnM, casingInnerDiameterMm) {
    var radiusM = casingInnerDiameterMm / 2000.0;
    var volumeL = Math.PI * radiusM * radiusM * Math.max(0.0, waterColumnM) * 1000.0;
    var solutionL = volumeL / 100.0;
    /* 0.2 percent solution = 2 g chlorine per litre; 65 percent HTH carries
     * 0.65 g available chlorine per gram of powder. */
    var hthGrams = solutionL * 2.0 / 0.65;
    return {
      well_volume_l: volumeL, solution_02pct_l: solutionL, hth_grams: hthGrams,
      contact_hours: 4.0,
      summary: 'Well volume about ' + thousandsFixed(volumeL, 0) + ' L: add ' +
        thousandsFixed(solutionL, 1) + ' L of 0.2% chlorine solution (about ' +
        thousandsFixed(hthGrams, 0) + ' g of 65% HTH in that much water) and ' +
        'wait at least 4 hours before pumping.',
    };
  }

  /* Python's "{:,.1f}". */
  function thousandsFixed(value, decimals) {
    return Number(value).toLocaleString('en-US', {
      minimumFractionDigits: decimals, maximumFractionDigits: decimals,
    });
  }

  Object.assign(C, {
    designBorehole: designBorehole, designSummaryRows: designSummaryRows,
    targetZones: targetZones,
    STAGES: STAGES, RESOURCE_CATEGORIES: RESOURCE_CATEGORIES,
    DEFAULT_EXCHANGE_RATE_SLE_PER_USD: DEFAULT_EXCHANGE_RATE_SLE_PER_USD,
    loadRates: loadRates, annulusVolumeM3: annulusVolumeM3,
    costingInputs: costingInputs, resolveCostingInputs: resolveCostingInputs,
    inputsFromDesign: inputsFromDesign, estimateBoreholeCost: estimateBoreholeCost,
    estimateProgrammeCost: estimateProgrammeCost,
    STAGE_TITLES: STAGE_TITLES, STAGE_ORDER: STAGE_ORDER,
    RESPONSE_STATES: RESPONSE_STATES, stageTitle: stageTitle,
    loadChecklists: loadChecklists, loadSeparationDistances: loadSeparationDistances,
    evaluateChecklist: evaluateChecklist,
    sandContentCheck: sandContentCheck, verticalityCheck: verticalityCheck,
    screenOpenAreaCheck: screenOpenAreaCheck,
    specificCapacityCheck: specificCapacityCheck,
    packAquiferRatioCheck: packAquiferRatioCheck,
    annularSpaceCheck: annularSpaceCheck,
    metresReconciliationCheck: metresReconciliationCheck,
    handpumpCorrosionCheck: handpumpCorrosionCheck,
    disinfectionDose: disinfectionDose, thousandsFixed: thousandsFixed,
  });

  /* ============================================================== ingestion
   * groundwater/ingestion/*. Field sheets use a header block of "Label: value"
   * pairs followed by one or more data tables. Labels vary between sheets
   * ("Field Supervisor", "Test conducted by", "Operator"), values sometimes
   * live in the same cell after a colon and sometimes several columns to the
   * right, and numbers may be stored as text with leading zeros.
   *
   * The grid these read is whatever support.readXlsx produced: a ragged array
   * of rows of numbers, strings, Dates and nulls - the same shape openpyxl
   * hands the Python readers.
   */

  function cleanText(value) {
    if (value === null || value === undefined) return '';
    if (value instanceof Date) return formatIsoDate(value);
    return String(value).replace(/\s+/g, ' ').trim();
  }

  function formatIsoDate(d) {
    return d.getUTCFullYear() + '-' +
      String(d.getUTCMonth() + 1).padStart(2, '0') + '-' +
      String(d.getUTCDate()).padStart(2, '0') + ' 00:00:00';
  }

  var NUMBER_RE = /[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?/;

  /* Handles plain numbers, leading zeros ("078.7", GPS "0708958"), appended
   * units ("80m", "19.28M", "2,933lts/hr"), thousands separators and stray
   * whitespace. Returns null when no number can be found. */
  function parseNumber(value, fallback) {
    var dflt = fallback === undefined ? null : fallback;
    if (value === null || value === undefined) return dflt;
    if (typeof value === 'number') return isFinite(value) ? value : dflt;
    if (value instanceof Date) return dflt;
    if (typeof value === 'boolean') return dflt;
    var text = String(value).trim();
    if (!text) return dflt;
    text = text.replace(/,/g, '');
    var m = NUMBER_RE.exec(text);
    return m === null ? dflt : parseFloat(m[0]);
  }

  var INTERVAL_RE = /(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)/i;

  /* Depths are unsigned, so the hyphen is a range separator, never a minus.
   * A date is never an interval: Excel silently turns "5-10" typed into a
   * General cell into 10 May, and reading that as text yielded a 5 to 2026 m
   * interval, which then placed screens and priced casing against a
   * two-kilometre hole. */
  function parseDepthInterval(value) {
    if (value === null || value === undefined || value instanceof Date) return null;
    var m = INTERVAL_RE.exec(String(value));
    if (!m) return null;
    var top = parseFloat(m[1]), bottom = parseFloat(m[2]);
    return bottom < top ? [bottom, top] : [top, bottom];
  }

  /* Canonical header keys and the label patterns that map to them. */
  var LABEL_PATTERNS = {
    client: ['^client\\b'],
    project: ['^project(?!\\s*ref)'],
    project_ref: ['^project\\s*ref', '^geophysics\\s*ref'],
    community: ['^community\\b', '^village\\b', '^location\\b'],
    chiefdom: ['^chiefdom\\b'],
    district: ['^district\\b'],
    sounding_id: ['^sounding\\s*(number|no)', '^ves\\s*(point|number|no)'],
    date: ['^date\\b'],
    supervisor: ['^field\\s*supervisor', '^test\\s*conducted\\s*by', '^operator\\b',
                 '^supervisor\\b'],
    contractor: ['^(drilling\\s*)?contractor\\b'],
    easting: ['^gps\\s*coordinate\\s*east', '^east(ing)?\\b', '^utm\\s*east'],
    northing: ['^gps\\s*coordinate\\s*north', '^north(ing)?\\b', '^utm\\s*north'],
    utm_zone: ['^utm\\s*zone', '^zone\\b'],
    elevation_m: ['^elevation', '^altitude'],
    array_type: ['^array\\b', '^electrode\\s*(array|configuration)'],
    instrument: ['^instrument\\b', '^equipment\\b'],
    borehole_ref: ['^borehole\\s*/?\\s*ref', '^bh\\s*ref', '^borehole\\s*(number|no)'],
    borehole_depth_m: ['^depth\\s*of\\s*borehole', '^borehole\\s*depth',
                       '^total\\s*depth', '^depth\\b'],
    static_water_level_m: ['^static\\s*water\\s*level', '^swl\\b'],
    pump_setting_m: ['^pump\\s*setting', '^pump\\s*installation\\s*depth'],
    step_length_min: ['^length\\s*of\\s*each\\s*step', '^step\\s*length'],
    test_type: ['^test\\s*type'],
    start_time: ['^time\\b', '^start\\s*time'],
    duration: ['^duration'],
    drilling_method: ['^(drilling\\s*)?method\\b'],
    start_date: ['^(drilling\\s*)?start\\s*date'],
    completion_date: ['^compl(etion)?\\.?\\s*date'],
    status: ['^(bh\\s*)?status'],
    sample_id: ['^sample\\s*(id|number|no|ref)'],
    laboratory: ['^lab(oratory)?\\b'],
    sample_date: ['^sample\\s*date', '^date\\s*sampled'],
    grouting_depth_m: ['^grout(ing)?\\b'],
    drill_rig: ['^drill\\s*rig'],
  };

  var COMPILED_LABELS = (function () {
    var out = {};
    Object.keys(LABEL_PATTERNS).forEach(function (key) {
      out[key] = LABEL_PATTERNS[key].map(function (p) { return new RegExp(p, 'i'); });
    });
    return out;
  }());

  var NUMERIC_HEADER_KEYS = ['easting', 'northing', 'elevation_m',
    'borehole_depth_m', 'static_water_level_m', 'pump_setting_m',
    'step_length_min', 'grouting_depth_m'];

  /* Priority is the pattern index within the key's list: 0 is the most
   * specific wording ("Depth of Borehole"), higher numbers are generic
   * fallbacks ("Depth"). A more specific match later in the sheet may
   * overwrite a generic one. */
  function matchLabelPriority(text) {
    var label = cleanText(text).replace(/:+$/, '').trim();
    if (!label) return null;
    var best = null;
    var keys = Object.keys(COMPILED_LABELS);
    for (var i = 0; i < keys.length; i++) {
      var patterns = COMPILED_LABELS[keys[i]];
      for (var p = 0; p < patterns.length; p++) {
        if (patterns[p].test(label)) {
          if (best === null || p < best[1]) {
            if (p === 0) return [keys[i], 0];
            best = [keys[i], p];
          }
          break;
        }
      }
    }
    return best;
  }

  function matchLabel(text) {
    var m = matchLabelPriority(text);
    return m ? m[0] : null;
  }

  /* Split "Community: Kuntoloh" into label and inline value. */
  function splitInlineValue(cellText) {
    var text = cleanText(cellText);
    var idx = text.indexOf(':');
    if (idx >= 0) {
      var value = text.slice(idx + 1).trim();
      return [text.slice(0, idx), value || null];
    }
    return [text, null];
  }

  function extractHeaderFields(grid, maxRows) {
    var limit = maxRows === undefined ? 30 : maxRows;
    var fields = {}, priorities = {};
    for (var r = 0; r < Math.min(limit, grid.length); r++) {
      var row = grid[r] || [];
      for (var c = 0; c < row.length; c++) {
        var cell = row[c];
        if (cell === null || cell === undefined || typeof cell === 'number') continue;
        var split = splitInlineValue(cell instanceof Date ? cleanText(cell) : String(cell));
        var matched = matchLabelPriority(split[0]);
        if (!matched) continue;
        var key = matched[0], priority = matched[1];
        if (key in fields && (priorities[key] === undefined ? 99 : priorities[key]) <= priority) {
          continue;
        }
        var value = split[1];
        if (value === null) {
          for (var cc = c + 1; cc < Math.min(c + 8, row.length); cc++) {
            var nxt = row[cc];
            if (nxt !== null && nxt !== undefined && cleanText(nxt) !== '') {
              /* Stop if the neighbouring cell is itself a label (with or
               * without its own inline value). */
              if (typeof nxt !== 'number') {
                var nxtLabel = splitInlineValue(nxt instanceof Date ? cleanText(nxt) : String(nxt));
                if (matchLabel(nxtLabel[0])) break;
              }
              value = nxt;
              break;
            }
          }
        }
        if (value === null || value === undefined) continue;
        if (NUMERIC_HEADER_KEYS.indexOf(key) >= 0) {
          var number = parseNumber(value);
          if (number !== null) { fields[key] = number; priorities[key] = priority; }
        } else {
          fields[key] = cleanText(value);
          priorities[key] = priority;
        }
      }
    }
    return fields;
  }

  function siteFromFields(fields, source) {
    var zone = fields.utm_zone;
    if (typeof zone === 'string') zone = parseNumber(zone);
    return {
      client: fields.client || '', project: fields.project || '',
      community: fields.community || '', chiefdom: fields.chiefdom || '',
      district: fields.district || '', country: 'Sierra Leone',
      project_ref: fields.project_ref || '',
      easting: fields.easting === undefined ? null : fields.easting,
      northing: fields.northing === undefined ? null : fields.northing,
      utm_zone: zone ? Math.trunc(zone) : null,
      elevation_m: fields.elevation_m === undefined ? null : fields.elevation_m,
      date: fields.date === undefined ? '' : String(fields.date),
      supervisor: fields.supervisor || '', contractor: fields.contractor || '',
      source: source || '',
    };
  }

  function rowText(row) {
    return (row || []).map(function (c) { return cleanText(c).toLowerCase(); });
  }

  /* --- VES sheets ---------------------------------------------------------- */

  var MN_HALF_RE = /mn\s*\/\s*2/;

  function findVesDataHeader(grid) {
    for (var r = 0; r < grid.length; r++) {
      var texts = rowText(grid[r]);
      var cols = {};
      for (var c = 0; c < texts.length; c++) {
        var t = texts[c];
        if (!t) continue;
        if (t.indexOf('ab/2') >= 0 || t === 'ab2' || t.indexOf('ab / 2') >= 0) {
          cols.ab2 = c;
        } else if (t.indexOf('mn') === 0 && MN_HALF_RE.test(t)) {
          /* half-MN first, and tolerant of the spaces a typed header carries:
           * "MN / 2 (m)" does not contain the literal "/2", so it would fall
           * through to the full-MN branch and halve every potential spacing */
          cols.mn_half = c;
        } else if (t.indexOf('mn') === 0) {
          cols.mn = c;
        } else if (t.indexOf('resistivity') >= 0 || t.indexOf('rho') === 0 ||
                   t.indexOf('ohm') >= 0) {
          cols.rho = c;
        } else if (['no.', 'no', 'reading', 'n'].indexOf(t) >= 0) {
          cols.no = c;
        }
      }
      if ('ab2' in cols && 'rho' in cols) return { row: r, cols: cols };
    }
    return null;
  }

  function soundingFromGrid(grid, source, sheetName) {
    var fields = extractHeaderFields(grid);
    var site = siteFromFields(fields, source);
    var located = findVesDataHeader(grid);
    if (!located) return null;
    var cols = located.cols;

    var ab2 = [], mn = [], rho = [], flags = [];
    var mnIsHalf = !('mn' in cols) && ('mn_half' in cols);
    var mnCol = 'mn' in cols ? cols.mn : cols.mn_half;
    var blankRun = 0;

    for (var r = located.row + 1; r < grid.length; r++) {
      var row = grid[r] || [];
      var a = cols.ab2 < row.length ? parseNumber(row[cols.ab2]) : null;
      var rr = cols.rho < row.length ? parseNumber(row[cols.rho]) : null;
      var m = (mnCol !== undefined && mnCol < row.length) ? parseNumber(row[mnCol]) : null;
      if (a === null && rr === null) {
        var fullyBlank = row.every(function (v) {
          return v === null || v === undefined || cleanText(v) === '';
        });
        /* Tolerate an isolated blank spacer row inside the table - field sheets
         * routinely leave one at a Schlumberger MN segment change. Only two
         * consecutive blank rows mark the true end, so the deep branch after a
         * spacer is kept. */
        if (ab2.length && fullyBlank) {
          blankRun += 1;
          if (blankRun >= 2) break;
        }
        continue;
      }
      if (a === null || rr === null) continue;
      blankRun = 0;
      if (m !== null && mnIsHalf) m = 2.0 * m;
      ab2.push(a);
      mn.push(m === null ? NaN : m);
      rho.push(rr);
    }
    if (!ab2.length) return null;

    var soundingId = String(fields.sounding_id || sheetName || 'VES 1') || 'VES 1';
    var sounding = {
      site: site, sounding_id: soundingId,
      ab2: ab2, mn: mn, rho_app: rho,
      array_type: String(fields.array_type || 'schlumberger').trim().toLowerCase() ||
        'schlumberger',
      instrument: fields.instrument || '', source: String(source || ''), flags: [],
    };

    if (rho.some(function (v) { return v <= 0; })) {
      flags.push({ level: 'error', code: 'nonpositive_resistivity',
        message: 'Apparent resistivity values must be positive.', context: soundingId });
    }
    for (var d = 1; d < ab2.length; d++) {
      if (ab2[d] - ab2[d - 1] < 0) {
        flags.push({ level: 'warning', code: 'ab2_not_sorted',
          message: 'AB/2 values are not in increasing order; check the sheet.',
          context: soundingId });
        break;
      }
    }
    for (var k = 0; k < mn.length; k++) {
      if (isFinite(mn[k]) && ab2[k] <= mn[k] / 2) {
        flags.push({ level: 'warning', code: 'mn_exceeds_ab',
          message: 'MN/2 is not smaller than AB/2 for some readings.',
          context: soundingId });
        break;
      }
    }
    var seen = {}, dup = 0;
    ab2.forEach(function (v) { seen[v] = (seen[v] || 0) + 1; });
    Object.keys(seen).forEach(function (v) { if (seen[v] > 1) dup += 1; });
    if (dup) {
      flags.push({ level: 'info', code: 'segment_overlap',
        message: dup + ' AB/2 value(s) repeated with different MN (segment ' +
          'changes); both readings kept.', context: soundingId });
    }
    sounding.flags = flags;
    return sounding;
  }

  /* One worksheet per sounding. */
  function readVesSheets(sheets, source) {
    var out = [];
    sheets.forEach(function (sheet) {
      var sounding = soundingFromGrid(sheet.rows, source || '', sheet.name);
      if (sounding) out.push(sounding);
    });
    return out;
  }

  /* --- drilling logs -------------------------------------------------------- */

  function findLogHeader(grid) {
    for (var r = 0; r < grid.length; r++) {
      var texts = rowText(grid[r]);
      var cols = {};
      for (var c = 0; c < texts.length; c++) {
        var t = texts[c];
        if (!t) continue;
        if ((t.indexOf('depth') >= 0 && t.indexOf('interval') >= 0) ||
            t.indexOf('depth /') === 0) {
          cols.interval = c;
        } else if (t.indexOf('depth') === 0 && !('interval' in cols)) {
          if (!('interval' in cols)) cols.interval = c;
        } else if (t.indexOf('from') === 0) {
          if (!('from_time' in cols)) cols.from_time = c;
        } else if (t.indexOf('to') === 0) {
          if (!('to_time' in cols)) cols.to_time = c;
        } else if (t.indexOf('penetration') >= 0) {
          cols.rate = c;
        } else if (t.indexOf('sample') >= 0 || t.indexOf('litholog') >= 0 ||
                   t.indexOf('description') >= 0) {
          if (!('description' in cols)) cols.description = c;
        } else if (t.indexOf('diameter') >= 0 || t.indexOf('bit') >= 0) {
          if (!('diameter' in cols)) cols.diameter = c;
        } else if (t.indexOf('strike') >= 0) {
          cols.strike = c;
        }
      }
      if ('interval' in cols) return { row: r, cols: cols };
    }
    return null;
  }

  function drillingFromGrid(grid, source) {
    var fields = extractHeaderFields(grid, grid.length);
    var site = siteFromFields(fields, source);
    var flags = [], intervals = [], strikes = [];
    var located = findLogHeader(grid);

    if (located) {
      var cols = located.cols;
      for (var r = located.row + 1; r < grid.length; r++) {
        var row = grid[r] || [];
        var cell = function (key) {
          var c = cols[key];
          return (c !== undefined && c < row.length) ? row[c] : null;
        };
        var rawInterval = cell('interval');
        if (cleanText(rawInterval).toLowerCase().indexOf('note') === 0) continue;
        if (rawInterval instanceof Date) {
          /* Excel turns "5-10" typed into a General cell into 10 May. Losing
           * the row is better than a 5 to 2026 m interval, but the crew has to
           * know a row went missing. */
          flags.push({
            level: 'warning', code: 'interval_read_as_date',
            message: 'Depth interval cell holds the date ' +
              formatDayMonYear(rawInterval) + ' - Excel converts entries like ' +
              '"5-10" into dates. Format the depth column as Text and retype ' +
              'the interval; this row was skipped.',
          });
          continue;
        }
        var interval = parseDepthInterval(rawInterval);
        if (!interval) continue;
        intervals.push({
          top_m: interval[0], bottom_m: interval[1],
          description: cleanText(cell('description')),
          from_time: cleanText(cell('from_time')),
          to_time: cleanText(cell('to_time')),
          penetration_rate_m_per_min: parseNumber(cell('rate')),
          bit_diameter_in: parseNumber(cell('diameter')),
        });
        var strike = parseNumber(cell('strike'));
        if (strike !== null) strikes.push(strike);
      }
    }

    /* Water strikes noted as text lines ("First water strike: 12m") */
    grid.forEach(function (row) {
      (row || []).forEach(function (c) {
        var text = cleanText(c).toLowerCase();
        if (text.indexOf('water strike') >= 0 && text.indexOf('note') !== 0) {
          var value = parseNumber(text.split(':').pop());
          if (value !== null && value > 0 && strikes.indexOf(value) < 0) {
            strikes.push(value);
          }
        }
      });
    });

    var total = fields.borehole_depth_m;
    if ((total === null || total === undefined) && intervals.length) {
      total = arrMax(intervals.map(function (iv) { return iv.bottom_m; }));
    }

    intervals.sort(function (a, b) { return a.top_m - b.top_m; });
    strikes.sort(function (a, b) { return a - b; });

    var log = {
      site: site, borehole_ref: String(fields.borehole_ref || ''),
      total_depth_m: total === undefined ? null : total,
      drilling_method: fields.drilling_method || '',
      intervals: intervals, water_strikes_m: strikes,
      grouting_depth_m: fields.grouting_depth_m === undefined ? null : fields.grouting_depth_m,
      start_date: String(fields.start_date || ''),
      completion_date: String(fields.completion_date || ''),
      status: fields.status || '', source: String(source || ''), flags: [],
    };

    for (var i = 0; i + 1 < intervals.length; i++) {
      var a = intervals[i], b = intervals[i + 1];
      if (b.top_m < a.bottom_m - 1e-9) {
        flags.push({ level: 'warning', code: 'interval_overlap',
          message: 'Depth intervals overlap at ' + formatG(b.top_m) + ' m.' });
      } else if (b.top_m > a.bottom_m + 1e-9) {
        flags.push({ level: 'warning', code: 'interval_gap',
          message: 'Gap in the drilling log between ' + formatG(a.bottom_m) +
            ' m and ' + formatG(b.top_m) + ' m.' });
      }
    }
    if (total && intervals.length &&
        Math.abs(intervals[intervals.length - 1].bottom_m - total) > 1e-6) {
      flags.push({ level: 'warning', code: 'depth_mismatch',
        message: 'Stated total depth ' + formatG(total) + ' m differs from the ' +
          'deepest logged interval ' + formatG(intervals[intervals.length - 1].bottom_m) + ' m.' });
    }
    if (!intervals.length) {
      flags.push({ level: 'error', code: 'no_intervals',
        message: 'No depth intervals found in the log.' });
    }
    var missingDesc = intervals.filter(function (iv) { return !iv.description; }).length;
    if (intervals.length && missingDesc) {
      flags.push({ level: 'info', code: 'missing_lithology',
        message: missingDesc + ' interval(s) have no lithology description.' });
    }
    log.flags = flags;
    return log;
  }

  var MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug',
    'Sep', 'Oct', 'Nov', 'Dec'];
  function formatDayMonYear(d) {
    return String(d.getUTCDate()).padStart(2, '0') + ' ' +
      MONTH_ABBR[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
  }

  /* --- water quality sheets ------------------------------------------------- */

  function findResultsHeader(grid) {
    for (var r = 0; r < grid.length; r++) {
      var texts = rowText(grid[r]);
      var cols = {};
      for (var c = 0; c < texts.length; c++) {
        var t = texts[c];
        if (!t) continue;
        if (t.indexOf('parameter') === 0 || t.indexOf('determinand') === 0) cols.parameter = c;
        else if (t.indexOf('unit') === 0) cols.unit = c;
        else if (t.indexOf('value') === 0 || t.indexOf('result') === 0) cols.value = c;
        else if (t.indexOf('detection') >= 0 || t === 'dl') cols.dl = c;
        else if (t.indexOf('method') === 0) cols.method = c;
      }
      if ('parameter' in cols && 'value' in cols) return { row: r, cols: cols };
    }
    return null;
  }

  function qualityFromGrid(grid, source) {
    var fields = extractHeaderFields(grid);
    var site = siteFromFields(fields, source);
    var flags = [];
    var located = findResultsHeader(grid);
    if (!located) {
      throw new Error('No results table (Parameter/Value) found in ' + (source || 'the sheet'));
    }
    var cols = located.cols, results = [];

    for (var r = located.row + 1; r < grid.length; r++) {
      var row = grid[r] || [];
      var cell = function (key) {
        var c = cols[key];
        return (c !== undefined && c < row.length) ? row[c] : null;
      };
      var parameter = cleanText(cell('parameter'));
      if (!parameter || parameter.toLowerCase().indexOf('note') === 0) continue;
      var rawValue = cell('value');
      var textValue = cleanText(rawValue);
      var belowDetection = textValue.indexOf('<') === 0;
      var value = parseNumber(rawValue);
      var dl = parseNumber(cell('dl'));
      if (belowDetection) {
        /* A "<X" marker means the true concentration is unknown, bounded above
         * by X. The measured value must be cleared so the assessment treats
         * the row as below-detection and never grades it as a real
         * concentration equal to the limit. */
        dl = dl !== null ? dl : value;
        value = null;
      }
      results.push({
        parameter: parameter, value: value, unit: cleanText(cell('unit')),
        detection_limit: dl,
        below_detection: belowDetection || (value === null && dl !== null),
        method: cleanText(cell('method')),
      });
    }

    var sample = {
      site: site, sample_id: String(fields.sample_id || ''),
      borehole_ref: String(fields.borehole_ref || ''),
      sample_date: String(fields.sample_date !== undefined ? fields.sample_date
        : (fields.date || '')),
      laboratory: fields.laboratory || '', results: results,
      source: String(source || ''), flags: [],
    };
    var measured = results.filter(function (r2) {
      return r2.value !== null || r2.below_detection;
    });
    if (!measured.length) {
      flags.push({ level: 'error', code: 'no_results',
        message: 'No measured values found in the sheet.' });
    }
    sample.flags = flags;
    return sample;
  }

  /* --- pumping test sheets --------------------------------------------------
   * The paper layout records readings in side-by-side hourly column groups,
   * each with Time (min), Water Level (m) and Drawdown (m), followed by a
   * Recovery block. The recorded drawdown column is the increment between
   * successive readings, not drawdown below static, so only time and water
   * level are read and true drawdown is always recomputed.
   */

  var DISCHARGE_TEXT_RE = /discharge\s*(?:of|0f)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*m3?\s*\/?\s*h/ig;

  function findGroups(grid) {
    var best = null;
    for (var r = 0; r < grid.length; r++) {
      var texts = rowText(grid[r]);
      var timeCols = [];
      for (var c = 0; c < texts.length; c++) {
        if (texts[c].indexOf('time') === 0) timeCols.push(c);
      }
      if (!timeCols.length) continue;
      var groups = [];
      for (var gi = 0; gi < timeCols.length; gi++) {
        var start = timeCols[gi];
        var end = gi + 1 < timeCols.length ? timeCols[gi + 1] : texts.length;
        var levelCol = null, recoCol = null;
        for (var cc = start + 1; cc < end; cc++) {
          var t = texts[cc];
          if (!t) continue;
          if ((t.indexOf('water') >= 0 || t.indexOf('level') === 0) && levelCol === null) {
            levelCol = cc;
          } else if (t.indexOf('reco') >= 0 && recoCol === null) {
            recoCol = cc;
          }
        }
        if (levelCol === null && recoCol === null) continue;
        if (recoCol !== null && levelCol !== null) {
          if (recoCol - start <= 2) {
            /* Kuntolo style triplet: Time, Water Level, Recovery increment */
            groups.push({ time: start, level: levelCol, kind: 'recovery' });
          } else {
            /* Dr Timbo style: shared time column; recovery column holds levels */
            groups.push({ time: start, level: levelCol, kind: 'pumping' });
            groups.push({ time: start, level: recoCol, kind: 'recovery' });
          }
        } else if (recoCol !== null) {
          groups.push({ time: start, level: recoCol, kind: 'recovery' });
        } else {
          groups.push({ time: start, level: levelCol, kind: 'pumping' });
        }
      }
      if (groups.length && (best === null || groups.length > best.groups.length)) {
        best = { row: r, groups: groups };
      }
    }
    return best;
  }

  function readSeries(grid, headerRow, group) {
    var times = [], levels = [];
    for (var r = headerRow + 1; r < grid.length; r++) {
      var row = grid[r] || [];
      var t = group.time < row.length ? parseNumber(row[group.time]) : null;
      var wl = group.level < row.length ? parseNumber(row[group.level]) : null;
      if (t === null || wl === null) continue;
      times.push(t); levels.push(wl);
    }
    return { times: times, levels: levels };
  }

  function findStepDischarges(grid) {
    var discharges = {};
    grid.forEach(function (row) {
      (row || []).forEach(function (cell, c) {
        var text = cleanText(cell).toLowerCase();
        if (text.indexOf('step') === 0 && text.indexOf('q') >= 0) {
          var num = parseNumber(text.split('q')[0]);
          if (num === null) return;
          for (var cc = c + 1; cc < Math.min(c + 3, row.length); cc++) {
            var val = parseNumber(row[cc]);
            if (val !== null) { discharges[Math.trunc(num)] = val; break; }
          }
        }
      });
    });
    return discharges;
  }

  function dischargeCandidatesFromText(grid) {
    var found = [];
    grid.forEach(function (row) {
      (row || []).forEach(function (cell) {
        if (cell === null || cell === undefined || typeof cell === 'number') return;
        var text = String(cell), m;
        DISCHARGE_TEXT_RE.lastIndex = 0;
        while ((m = DISCHARGE_TEXT_RE.exec(text)) !== null) {
          var value = parseFloat(m[1]);
          if (found.indexOf(value) < 0) found.push(value);
        }
      });
    });
    return found;
  }

  /* Pre-printed text that names a test kind without recording which test was
   * run: the template's own title mentions both, and its constant-discharge
   * column labels sit on every sheet whatever was pumped. Reading either as an
   * answer turned step tests into constant ones. */
  var CONSTANT_COLUMN_LABEL_RE = /constant\s+discharge\s*\d/;

  function sheetTestType(grid) {
    for (var r = 0; r < grid.length; r++) {
      var row = grid[r] || [];
      for (var c = 0; c < row.length; c++) {
        var text = cleanText(row[c]).toLowerCase();
        if (!text) continue;
        var stepWords = text.indexOf('step test') >= 0 || text.indexOf('step drawdown') >= 0;
        var constantWords = text.indexOf('constant discharge') >= 0 ||
          text.indexOf('constant rate') >= 0;
        if (constantWords && text.indexOf('step') >= 0) continue;
        if (stepWords) return 'step';
        if (constantWords && !CONSTANT_COLUMN_LABEL_RE.test(text)) return 'constant';
      }
    }
    return '';
  }

  function pumpingFromGrid(grid, source) {
    var fields = extractHeaderFields(grid, grid.length);
    var site = siteFromFields(fields, source);
    var flags = [];
    var located = findGroups(grid);
    if (!located) {
      throw new Error('No Time/Water Level column groups found in ' + (source || 'the sheet'));
    }

    var pumpingSeries = located.groups.filter(function (g) { return g.kind === 'pumping'; })
      .map(function (g) { return readSeries(grid, located.row, g); })
      .filter(function (s) { return s.times.length; });
    var recoverySeries = located.groups.filter(function (g) { return g.kind === 'recovery'; })
      .map(function (g) { return readSeries(grid, located.row, g); })
      .filter(function (s) { return s.times.length; });

    var testType = String(fields.test_type || '').trim().toLowerCase();
    var stated = !!testType;
    if (!testType) testType = sheetTestType(grid);
    var inferredFromShape = !testType;
    if (!testType) testType = pumpingSeries.length > 1 ? 'step' : 'constant';
    if (inferredFromShape && !stated && pumpingSeries.length > 1) {
      flags.push({
        level: 'info', code: 'test_type_inferred',
        message: 'The test type cell is blank; the ' + pumpingSeries.length +
          ' filled column groups have been read as the steps of a step test. ' +
          'If this was a constant discharge test, write "constant" in the test ' +
          'type cell so the readings are analysed as one series.',
      });
    }

    if (testType.indexOf('constant') === 0 && pumpingSeries.length > 1) {
      /* hourly column groups are one continuous series on constant tests */
      var allT = [], allW = [];
      pumpingSeries.forEach(function (s) {
        allT = allT.concat(s.times); allW = allW.concat(s.levels);
      });
      var order = allT.map(function (v, i) { return i; })
        .sort(function (a, b) { return allT[a] - allT[b] || a - b; });
      pumpingSeries = [{
        times: order.map(function (i) { return allT[i]; }),
        levels: order.map(function (i) { return allW[i]; }),
      }];
    }

    var discharges = findStepDischarges(grid);
    var steps = pumpingSeries.map(function (s, i) {
      return {
        step_number: i + 1, time_min: s.times, water_level_m: s.levels,
        discharge_m3_per_h: discharges[i + 1] === undefined ? null : discharges[i + 1],
        label: pumpingSeries.length > 1 ? ('Step ' + (i + 1)) : 'Pumping phase',
      };
    });

    /* Free-text discharge: use it only when unambiguous. */
    var candidates = dischargeCandidatesFromText(grid);
    var missing = steps.filter(function (s) { return s.discharge_m3_per_h === null; });
    if (candidates.length && missing.length) {
      if (candidates.length === 1 && steps.length === 1) {
        steps[0].discharge_m3_per_h = candidates[0];
        flags.push({ level: 'info', code: 'discharge_from_text',
          message: 'Discharge ' + formatG(candidates[0]) + ' m3/h taken from a ' +
            'text note on the sheet; confirm against the measured value.' });
      } else {
        flags.push({ level: 'warning', code: 'discharge_ambiguous',
          message: 'Discharge mentioned in sheet text (' +
            candidates.map(function (c) { return formatG(c) + ' m3/h'; }).join(', ') +
            ') but not assigned per step; enter values in the template.' });
      }
    }

    var recoveryTime = null, recoveryLevel = null;
    if (recoverySeries.length) {
      recoveryTime = recoverySeries[0].times;
      recoveryLevel = recoverySeries[0].levels;
      testType += '+recovery';
    }

    var swl = fields.static_water_level_m === undefined ? null : fields.static_water_level_m;
    var pumpingDuration = steps.length
      ? arrMax(steps.map(function (s) { return arrMax(s.time_min); })) : null;

    var test = {
      site: site, borehole_ref: String(fields.borehole_ref || ''),
      test_type: testType, static_water_level_m: swl,
      borehole_depth_m: fields.borehole_depth_m === undefined ? null : fields.borehole_depth_m,
      pump_setting_m: fields.pump_setting_m === undefined ? null : fields.pump_setting_m,
      step_length_min: fields.step_length_min === undefined ? null : fields.step_length_min,
      steps: steps, recovery_time_min: recoveryTime, recovery_level_m: recoveryLevel,
      pumping_duration_min: pumpingDuration, source: String(source || ''), flags: [],
    };

    if (swl === null) {
      flags.push({ level: 'error', code: 'missing_static_water_level',
        message: 'Static water level is missing; drawdown cannot be computed.' });
    }
    var missingQ = steps.filter(function (s) { return s.discharge_m3_per_h === null; })
      .map(function (s) { return s.step_number; });
    if (missingQ.length) {
      flags.push({ level: 'warning', code: 'missing_discharge',
        message: 'Discharge not recorded for step(s) ' + missingQ.join(', ') +
          '. Drawdown and recovery curves are produced, but transmissivity and ' +
          'yield results are pending until discharge values are supplied.' });
    }
    if (swl !== null && steps.length) {
      var anyAbove = steps.some(function (s) {
        return s.water_level_m.some(function (v) { return v < swl - 0.01; });
      });
      if (anyAbove) {
        flags.push({ level: 'warning', code: 'water_level_above_static',
          message: 'Some pumping water levels are above the stated static water ' +
            'level, giving negative drawdown. Check the static level and the ' +
            'measuring datum on the sheet.' });
      }
    }
    steps.forEach(function (s) {
      for (var i = 1; i < s.time_min.length; i++) {
        if (s.time_min[i] - s.time_min[i - 1] <= 0) {
          flags.push({ level: 'warning', code: 'time_not_increasing',
            message: 'Times are not strictly increasing in ' + s.label + '.',
            context: s.label });
          break;
        }
      }
    });
    if (test.borehole_depth_m && test.pump_setting_m &&
        test.pump_setting_m > test.borehole_depth_m) {
      flags.push({ level: 'warning', code: 'pump_below_borehole',
        message: 'Pump setting is deeper than the borehole depth.' });
    }
    if (test.borehole_depth_m && steps.length) {
      var maxWl = arrMax(steps.map(function (s) {
        return arrMax(s.water_level_m.filter(isFinite));
      }));
      if (maxWl > test.borehole_depth_m) {
        flags.push({ level: 'warning', code: 'level_below_borehole',
          message: 'Recorded water level ' + maxWl.toFixed(2) + ' m exceeds the ' +
            'stated borehole depth ' + test.borehole_depth_m.toFixed(0) +
            ' m; check the sheet.' });
      }
    }
    test.flags = flags;
    return test;
  }

  Object.assign(C, {
    cleanText: cleanText, parseNumber: parseNumber,
    parseDepthInterval: parseDepthInterval,
    matchLabel: matchLabel, matchLabelPriority: matchLabelPriority,
    splitInlineValue: splitInlineValue, extractHeaderFields: extractHeaderFields,
    siteFromFields: siteFromFields, rowText: rowText,
    soundingFromGrid: soundingFromGrid, readVesSheets: readVesSheets,
    drillingFromGrid: drillingFromGrid, qualityFromGrid: qualityFromGrid,
    pumpingFromGrid: pumpingFromGrid,
    LABEL_PATTERNS: LABEL_PATTERNS,
  });

  /* ========================================================= area analysis
   * groundwater/coverage.py and groundwater/waterpoints.py. Where to drill
   * next, and whether a new borehole is the right answer at all.
   */

  var EARTH_RADIUS_M = 6371000.0;
  var DEFAULT_SEARCH_RADIUS_M = 1000.0;
  var SERVICE_RADIUS_M = 500.0;
  var DRILL_NEW = 'drill_new', ASSESS_REHAB = 'assess_rehab', VERIFY_NEED = 'verify_need';

  /* WPdx+ is served from a Socrata endpoint; the resource id is documented but
   * kept overridable so a future dataset id needs no code change. */
  var WPDX_DOMAIN = 'data.waterpointdata.org';
  var WPDX_RESOURCE = 'eqje-vguj';

  var WPDX_CREDIT = 'Water point data: Water Point Data Exchange (WPdx+), ' +
    'CC BY 4.0. Downloaded from wpdx.org.';
  var POPULATION_CREDIT = 'Population: 2015 Population and Housing Census, ' +
    'Statistics Sierra Leone. Boundaries: geoBoundaries, CC BY 4.0.';

  function haversineM(lat1, lon1, lat2, lon2) {
    var rad = Math.PI / 180;
    var p1 = lat1 * rad, p2 = lat2 * rad;
    var dphi = (lat2 - lat1) * rad, dlam = (lon2 - lon1) * rad;
    var a = Math.sin(dphi / 2) * Math.sin(dphi / 2) +
      Math.cos(p1) * Math.cos(p2) * Math.sin(dlam / 2) * Math.sin(dlam / 2);
    return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
  }

  /* Ray casting on a closed ring. */
  function pointInRing(lon, lat, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if (((yi > lat) !== (yj > lat)) &&
          (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi)) {
        inside = !inside;
      }
    }
    return inside;
  }

  /* Chiefdom polygons, with bounding boxes so the point-in-polygon scan over
   * 166 chiefdoms stays cheap for a few thousand water points. */
  function loadPolygons(layer) {
    var source = layer || (GWT.data && GWT.data.geo && GWT.data.geo.chiefdomBoundaries);
    if (!source) return [];
    return (source.features || []).map(function (feature) {
      var geometry = feature.geometry || {};
      var parts = geometry.type === 'MultiPolygon'
        ? geometry.coordinates : [geometry.coordinates || []];
      var rings = [], holes = [], bboxes = [];
      parts.forEach(function (part) {
        if (!part || !part.length) return;
        var outer = part[0];
        rings.push(outer);
        holes.push(part.slice(1));
        var lons = outer.map(function (c) { return c[0]; });
        var lats = outer.map(function (c) { return c[1]; });
        bboxes.push([arrMin(lons), arrMin(lats), arrMax(lons), arrMax(lats)]);
      });
      return {
        name: (feature.properties || {}).name || '',
        district: (feature.properties || {}).district || '',
        rings: rings, holes: holes, bboxes: bboxes, feature: feature,
      };
    }).filter(function (p) { return p.rings.length; });
  }

  function polyContains(poly, lon, lat) {
    for (var i = 0; i < poly.rings.length; i++) {
      var b = poly.bboxes[i];
      if (lon < b[0] || lon > b[2] || lat < b[1] || lat > b[3]) continue;
      if (!pointInRing(lon, lat, poly.rings[i])) continue;
      var inHole = (poly.holes[i] || []).some(function (hole) {
        return pointInRing(lon, lat, hole);
      });
      if (!inHole) return true;
    }
    return false;
  }

  function chiefdomOfPoint(lat, lon, polys) {
    for (var i = 0; i < polys.length; i++) {
      if (polyContains(polys[i], lon, lat)) return polys[i].name;
    }
    return '';
  }

  function loadDistrictPopulation(rows) {
    var source = rows || (GWT.data && GWT.data.populationDistrict) || [];
    var out = {};
    source.forEach(function (row) {
      out[String(row.district).trim()] = Number(row.population);
    });
    return out;
  }

  function loadChiefdomDistrict(rows) {
    var source = rows || (GWT.data && GWT.data.chiefdomDistrict) || [];
    var out = {};
    source.forEach(function (row) {
      out[String(row.chiefdom).trim()] = String(row.district).trim();
    });
    return out;
  }

  /* Population per chiefdom polygon, aggregated from the census through the
   * crosswalk. District totals are conserved exactly by construction, and the
   * member list drives the reconciliation panel that shows how post-2017
   * chiefdoms fold into the pre-2017 polygons. */
  function chiefdomPopulation(censusRows, crosswalkRows) {
    var census = censusRows || (GWT.data && GWT.data.populationChiefdom) || [];
    var crossSource = crosswalkRows || (GWT.data && GWT.data.censusCrosswalk) || [];
    var crosswalk = {};
    crossSource.forEach(function (row) {
      crosswalk[String(row.district).trim() + '||' + String(row.census_chiefdom).trim()] =
        String(row.gb_chiefdom).trim();
    });
    var population = {}, members = {}, missing = [];
    census.forEach(function (row) {
      var key = String(row.district).trim() + '||' + String(row.chiefdom).trim();
      var gb = crosswalk[key];
      if (gb === undefined) { missing.push(key); return; }
      population[gb] = (population[gb] || 0) + Number(row.population);
      (members[gb] = members[gb] || []).push(String(row.chiefdom).trim());
    });
    if (missing.length) {
      throw new Error(missing.length + ' census chiefdom(s) have no crosswalk ' +
        'row, e.g. ' + missing[0].replace('||', ' / ') +
        '; check data/sl_census_crosswalk.csv');
    }
    return { population: population, members: members };
  }

  function countPointsByChiefdom(points, polys) {
    var counts = {}, unassigned = [];
    points.forEach(function (wp) {
      var chiefdom = chiefdomOfPoint(wp.lat, wp.lon, polys);
      if (!chiefdom) { unassigned.push(wp); return; }
      var bucket = counts[chiefdom] || (counts[chiefdom] = { total: 0, functional: 0 });
      bucket.total += 1;
      if (wp.functional === true) bucket.functional += 1;
    });
    return { counts: counts, unassigned: unassigned };
  }

  function countPointsByDistrict(points, polys, chiefdomDistrict) {
    var counts = {}, unassigned = [];
    points.forEach(function (wp) {
      var chiefdom = chiefdomOfPoint(wp.lat, wp.lon, polys);
      var district = chiefdom ? chiefdomDistrict[chiefdom] : '';
      if (!district) { unassigned.push(wp); return; }
      var bucket = counts[district] || (counts[district] = { total: 0, functional: 0 });
      bucket.total += 1;
      if (wp.functional === true) bucket.functional += 1;
    });
    return { counts: counts, unassigned: unassigned };
  }

  /* Ranking is worst-first: areas with no functional source mapped rank at the
   * very top - unmet need is effectively infinite there - then the rest by
   * descending people-per-functional-point, with population breaking ties. */
  function rankCoverage(rows) {
    rows.sort(function (a, b) {
      var ka = a.people_per_point !== null ? 1 : 0;
      var kb = b.people_per_point !== null ? 1 : 0;
      if (ka !== kb) return ka - kb;
      var pa = a.people_per_point || 0, pb = b.people_per_point || 0;
      if (pa !== pb) return pb - pa;
      return b.population - a.population;
    });
    rows.forEach(function (row, i) { row.rank = i + 1; });
    return rows;
  }

  function coverageRows(population, counts) {
    var rows = Object.keys(population).map(function (name) {
      var bucket = counts[name] || { total: 0, functional: 0 };
      return {
        name: name, district: name, population: population[name],
        water_points: bucket.total, functional_points: bucket.functional,
        people_per_point: bucket.functional > 0
          ? population[name] / bucket.functional : null,
        rank: 0,
      };
    });
    return rankCoverage(rows);
  }

  function chiefdomCoverageRows(population, counts, chiefdomDistrict) {
    var rows = Object.keys(population).map(function (name) {
      var bucket = counts[name] || { total: 0, functional: 0 };
      return {
        name: name, chiefdom: name, district: chiefdomDistrict[name] || '',
        population: population[name], water_points: bucket.total,
        functional_points: bucket.functional,
        people_per_point: bucket.functional > 0
          ? population[name] / bucket.functional : null,
        rank: 0,
      };
    });
    return rankCoverage(rows);
  }

  /* worst_served_* is the highest FINITE people-per-point, reported separately
   * from the ranking because areas with no functional source have an undefined
   * ratio, sort to rank 1 and are counted by n_no_source instead. */
  function coverageStats(rows) {
    var served = rows.filter(function (r) { return r.people_per_point !== null; });
    var worstServed = served.reduce(function (a, b) {
      return (!a || b.people_per_point > a.people_per_point) ? b : a;
    }, null);
    var totalPop = rows.reduce(function (a, r) { return a + r.population; }, 0);
    var totalFunctional = rows.reduce(function (a, r) { return a + r.functional_points; }, 0);
    return {
      n_areas: rows.length,
      worst_area: rows.length ? rows[0].name : null,
      worst_people_per_point: rows.length ? rows[0].people_per_point : null,
      worst_served_area: worstServed ? worstServed.name : null,
      worst_served_people_per_point: worstServed ? worstServed.people_per_point : null,
      n_no_source: rows.filter(function (r) { return r.functional_points === 0; }).length,
      national_people_per_point: totalFunctional ? totalPop / totalFunctional : null,
    };
  }

  /* --- water points --------------------------------------------------------- */

  function wpFirst(record, keys) {
    for (var i = 0; i < keys.length; i++) {
      var variants = [keys[i], '#' + keys[i]];
      for (var v = 0; v < variants.length; v++) {
        if (variants[v] in record) {
          var value = record[variants[v]];
          if (value !== null && value !== undefined && value !== '') return value;
        }
      }
    }
    return null;
  }

  /* status_clean text is authoritative when present; status_id is the
   * fallback. A source that is functional but needs repair still delivers
   * water, so it counts as functional. */
  function functionalFrom(statusText, statusId) {
    var text = String(statusText || '').trim().toLowerCase();
    if (text) {
      if (text.indexOf('non') >= 0 || text.indexOf('not functional') >= 0 ||
          text.indexOf('abandoned') >= 0) {
        return false;
      }
      /* whole word, so "functionality" in "unknown functionality" does not
       * read as functional */
      var words = text.match(/[a-z]+/g) || [];
      if (words.indexOf('functional') >= 0) return true;
    }
    var sid = String(statusId === null || statusId === undefined ? '' : statusId)
      .trim().toLowerCase();
    if (['yes', 'y', 'true', '1'].indexOf(sid) >= 0) return true;
    if (['no', 'n', 'false', '0'].indexOf(sid) >= 0) return false;
    return null;
  }

  /* An improved source is worth rehabilitating; an unprotected well or spring
   * or surface water is not, so it is no alternative to a new borehole.
   *
   * The unimproved test runs first because "unprotected" contains "protected":
   * a Protected Spring is improved, an Unprotected Spring is not, and both
   * have to resolve correctly. Source and technology are read together, since
   * WPDx records "Well" in one column and "Hand Pump" in the other. */
  var UNIMPROVED_WORDS = ['unprotected', 'unimproved', 'open well', 'open dug',
    'surface', 'river', 'stream', 'pond', 'rainwater'];
  var IMPROVED_WORDS = ['borehole', 'tubewell', 'tube well', 'protected',
    'piped', 'hand pump', 'handpump', 'mechani'];

  function improvedSource(source, technology) {
    var text = (String(source || '') + ' ' + String(technology || '')).toLowerCase();
    var i;
    for (i = 0; i < UNIMPROVED_WORDS.length; i++) {
      if (text.indexOf(UNIMPROVED_WORDS[i]) >= 0) return false;
    }
    for (i = 0; i < IMPROVED_WORDS.length; i++) {
      if (text.indexOf(IMPROVED_WORDS[i]) >= 0) return true;
    }
    return false;
  }

  function parseWpdxRecords(records) {
    var out = [];
    (records || []).forEach(function (record) {
      if (!record || typeof record !== 'object') return;
      var lat = Number(wpFirst(record, ['lat_deg', 'latitude', 'lat']));
      var lon = Number(wpFirst(record, ['lon_deg', 'longitude', 'lon']));
      if (!isFinite(lat) || !isFinite(lon)) return;
      var source = String(wpFirst(record, ['water_source_clean', 'water_source',
        'source']) || '');
      var technology = String(wpFirst(record, ['water_tech_clean', 'water_tech',
        'technology']) || '');
      var statusText = String(wpFirst(record, ['status_clean', 'status']) || '');
      var statusId = wpFirst(record, ['status_id', 'status']);
      var year = Number(wpFirst(record, ['install_year', 'installation_year']));
      out.push({
        row_id: String(wpFirst(record, ['row_id', 'wpdx_id', 'objectid']) || ''),
        lat: lat, lon: lon,
        /* the technology stands in when the source column is blank, so a row
         * that only says "Hand Pump" still reads as a point rather than a
         * nameless dot */
        source: source || technology,
        technology: technology,
        status_text: statusText,
        functional: functionalFrom(statusText, statusId),
        improved: improvedSource(source, technology),
        installed: isFinite(year) && year ? Math.round(year) : null,
        adm2: String(wpFirst(record, ['clean_adm2', 'adm2']) || ''),
        name: String(wpFirst(record, ['water_source_description', 'source_name',
          'clean_adm4', 'clean_adm3']) || ''),
        distance_m: null,
      });
    });
    return out;
  }

  /* --- the live Water Point Data Exchange query ------------------------------
   *
   * groundwater/waterpoints.py fetch_water_points, in the browser. A bounding
   * box on the standard lat_deg/lon_deg columns (rather than a Socrata
   * within_circle on a geo column) so the request does not depend on a
   * particular geometry field name; the true radius is applied client side by
   * pointsWithin, exactly as the Python does.
   *
   * The whole call is optional. It is the only thing in this application that
   * touches the network, and it fails soft: offline, blocked by a browser
   * extension or refused by the CDN, the page says so and the CSV upload path
   * still does the whole job. */
  function wpdxUrl(lat, lon, radiusM, options) {
    var opts = options || {};
    var limit = opts.limit || 5000;
    var dlat = radiusM / 111320.0;
    var dlon = radiusM / (111320.0 * Math.max(Math.cos(lat * Math.PI / 180), 1e-6));
    var where = 'lat_deg between ' + (lat - dlat) + ' and ' + (lat + dlat) +
      ' AND lon_deg between ' + (lon - dlon) + ' and ' + (lon + dlon);
    var query = '$where=' + encodeURIComponent(where) +
      '&$limit=' + Math.round(limit) +
      /* $order by the Socrata row id makes a capped result deterministic
       * across runs: a truncated slice is at least the same slice. */
      '&$order=' + encodeURIComponent(':id');
    return 'https://' + (opts.domain || WPDX_DOMAIN) + '/resource/' +
      (opts.resource || WPDX_RESOURCE) + '.json?' + query;
  }

  function WaterPointFetchError(message) {
    var error = new Error(message);
    error.name = 'WaterPointFetchError';
    return error;
  }

  async function fetchWaterPoints(lat, lon, radiusM, options) {
    var opts = options || {};
    var url = wpdxUrl(lat, lon, radiusM || DEFAULT_SEARCH_RADIUS_M, opts);
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = controller
      ? setTimeout(function () { controller.abort(); }, (opts.timeoutS || 30) * 1000)
      : null;
    var response;
    try {
      response = await fetch(url, {
        headers: { Accept: 'application/json' },
        signal: controller ? controller.signal : undefined,
      });
    } catch (e) {
      throw WaterPointFetchError(
        'Could not reach the Water Point Data Exchange (' +
        (e && e.name === 'AbortError' ? 'the request timed out'
          : 'no network route, or the browser blocked the cross-origin request') +
        ').');
    } finally {
      if (timer) clearTimeout(timer);
    }
    if (!response.ok) {
      throw WaterPointFetchError(
        'The Water Point Data Exchange answered ' + response.status + ' ' +
        (response.statusText || '') + '.');
    }
    var data;
    try {
      data = await response.json();
    } catch (e) {
      throw WaterPointFetchError(
        'The Water Point Data Exchange sent something that is not JSON.');
    }
    if (!Array.isArray(data)) {
      throw WaterPointFetchError(
        'Unexpected response from the Water Point Data Exchange ' +
        '(expected a list of records).');
    }
    return data;
  }

  /* Fetch, parse and distance-filter in one call.
   *
   * The query is a bounding box, so it returns the corners of the square as
   * well as the circle the operator asked for. Without this last step a point
   * 1.4 km away lands in a 1 km search: the rehabilitate-or-drill decision
   * re-filters and would ignore it, but the functionality totals and anything
   * built on the stored inventory would silently count it. */
  async function waterPointsNear(lat, lon, radiusM, options) {
    var radius = radiusM || DEFAULT_SEARCH_RADIUS_M;
    var raw = await fetchWaterPoints(lat, lon, radius, options);
    return pointsWithin(parseWpdxRecords(raw), lat, lon, radius);
  }

  function pointsWithin(points, lat, lon, radiusM) {
    var out = [];
    points.forEach(function (point) {
      var distance = haversineM(lat, lon, point.lat, point.lon);
      if (distance <= radiusM) {
        out.push(Object.assign({}, point, { distance_m: distance }));
      }
    });
    out.sort(function (a, b) { return a.distance_m - b.distance_m; });
    return out;
  }

  function functionalitySummary(points) {
    var functional = points.filter(function (p) { return p.functional === true; }).length;
    var nonFunctional = points.filter(function (p) { return p.functional === false; }).length;
    var unknown = points.filter(function (p) { return p.functional === null; }).length;
    var reported = functional + nonFunctional;
    return {
      total: points.length, functional: functional, non_functional: nonFunctional,
      unknown: unknown,
      functional_rate: reported ? (functional / reported * 100.0) : null,
    };
  }

  /* A working improved source inside the service radius means the community
   * may already be served; otherwise a broken improved source nearby is a
   * rehabilitation candidate, usually cheaper than a new borehole; otherwise
   * new construction is justified. */
  function rehabVsDrill(points, lat, lon, options) {
    var opts = options || {};
    var searchRadius = opts.searchRadiusM || DEFAULT_SEARCH_RADIUS_M;
    var serviceRadius = opts.serviceRadiusM || SERVICE_RADIUS_M;
    var nearby = pointsWithin(points, lat, lon, searchRadius);
    var functional = nearby.filter(function (p) { return p.functional === true; });
    var brokenImproved = nearby.filter(function (p) {
      return p.functional === false && p.improved;
    });
    var served = functional.filter(function (p) {
      return p.improved && p.distance_m <= serviceRadius;
    });

    var common = {
      n_nearby: nearby.length, search_radius_m: searchRadius,
      service_radius_m: serviceRadius, summary: functionalitySummary(nearby),
      rehab_candidates: brokenImproved, nearby: nearby,
    };

    if (served.length) {
      var nearest = served[0];
      return Object.assign(common, {
        recommendation: VERIFY_NEED,
        headline: 'A working ' + (nearest.source || 'improved source') +
          ' is already ' + Math.round(nearest.distance_m) + ' m away.',
        rationale: 'An improved, functional source sits inside the ' +
          Math.round(serviceRadius) + ' m service radius, so the site may ' +
          'already be served. Confirm demand (population, queue times, ' +
          'dry-season reliability) before committing to a new borehole.',
      });
    }
    if (brokenImproved.length) {
      var broken = brokenImproved[0];
      return Object.assign(common, {
        recommendation: ASSESS_REHAB,
        headline: 'A non-functional ' + (broken.source || 'improved source') +
          ' lies ' + Math.round(broken.distance_m) + ' m away.',
        rationale: 'Rehabilitating a broken improved source is usually cheaper ' +
          'and faster than a new borehole. Assess why it failed - a dry or ' +
          'collapsed hole is not worth rehabilitating, a failed pump usually is ' +
          '- before deciding.',
      });
    }
    if (!nearby.length) {
      return Object.assign(common, {
        recommendation: DRILL_NEW,
        headline: 'No mapped water point within ' + Math.round(searchRadius) + ' m.',
        rationale: 'No existing water point is mapped near the site, so new ' +
          'construction is likely justified. Field-verify, since the water ' +
          'point inventory is not exhaustive.',
      });
    }
    /* Something is nearby but none of it is a rehabilitation alternative.
     * Which of the two reasons applies matters to the reader, so say the
     * right one rather than assuming distance every time. */
    var nearestWorking = functional[0];
    var note = '';
    if (nearestWorking) {
      note = nearestWorking.distance_m > serviceRadius
        ? ' The nearest working source is ' + Math.round(nearestWorking.distance_m) +
          ' m away, beyond the ' + Math.round(serviceRadius) + ' m service radius.'
        : ' The nearest working source is ' + Math.round(nearestWorking.distance_m) +
          ' m away but is not an improved source suitable for rehabilitation.';
    }
    return Object.assign(common, {
      recommendation: DRILL_NEW,
      headline: 'No rehabilitation candidate nearby.' + note,
      rationale: 'Nearby points are either working but beyond the service ' +
        'radius or not improved sources, so there is no cheaper rehabilitation ' +
        'alternative. New construction is reasonable.' + note,
    });
  }

  Object.assign(C, {
    EARTH_RADIUS_M: EARTH_RADIUS_M,
    DEFAULT_SEARCH_RADIUS_M: DEFAULT_SEARCH_RADIUS_M,
    SERVICE_RADIUS_M: SERVICE_RADIUS_M,
    DRILL_NEW: DRILL_NEW, ASSESS_REHAB: ASSESS_REHAB, VERIFY_NEED: VERIFY_NEED,
    WPDX_CREDIT: WPDX_CREDIT, POPULATION_CREDIT: POPULATION_CREDIT,
    haversineM: haversineM, pointInRing: pointInRing, loadPolygons: loadPolygons,
    polyContains: polyContains, chiefdomOfPoint: chiefdomOfPoint,
    loadDistrictPopulation: loadDistrictPopulation,
    loadChiefdomDistrict: loadChiefdomDistrict,
    chiefdomPopulation: chiefdomPopulation,
    countPointsByChiefdom: countPointsByChiefdom,
    countPointsByDistrict: countPointsByDistrict,
    coverageRows: coverageRows, chiefdomCoverageRows: chiefdomCoverageRows,
    coverageStats: coverageStats,
    parseWpdxRecords: parseWpdxRecords, pointsWithin: pointsWithin,
    functionalitySummary: functionalitySummary, rehabVsDrill: rehabVsDrill,
    functionalFrom: functionalFrom,
    improvedSource: improvedSource,
    WPDX_DOMAIN: WPDX_DOMAIN, WPDX_RESOURCE: WPDX_RESOURCE,
    wpdxUrl: wpdxUrl, fetchWaterPoints: fetchWaterPoints,
    waterPointsNear: waterPointsNear,
  });

  /* ================================================================== geodesy
   * groundwater/geo.py. Sierra Leone straddles UTM zones 28N and 29N; the
   * easting alone identifies the zone, because in-country the valid ranges
   * cannot overlap (zone 28N runs about 620000-800000, zone 29N 200000-500000).
   */

  function inferZoneForSierraLeone(easting) {
    return Number(easting) > 550000 ? 28 : 29;
  }

  function utmZoneFromLon(lon) {
    return Math.floor((lon + 180) / 6) + 1;
  }

  /* WGS84 geographic -> UTM, the Krueger series (Karney 2011, terms to n^4)
   * the package uses, so a pasted position lands on the same metre. */
  var GEO_A = 6378137.0;
  var GEO_F = 1 / 298.257223563;
  var GEO_E = Math.sqrt(GEO_F * (2 - GEO_F));
  var GEO_N = GEO_F / (2 - GEO_F);
  var GEO_K0 = 0.9996;
  var GEO_FALSE_EASTING = 500000.0;
  var GEO_A1 = GEO_A / (1 + GEO_N) *
    (1 + Math.pow(GEO_N, 2) / 4 + Math.pow(GEO_N, 4) / 64);
  var GEO_ALPHA = [
    GEO_N / 2 - 2 * Math.pow(GEO_N, 2) / 3 + 5 * Math.pow(GEO_N, 3) / 16 +
      41 * Math.pow(GEO_N, 4) / 180,
    13 * Math.pow(GEO_N, 2) / 48 - 3 * Math.pow(GEO_N, 3) / 5 +
      557 * Math.pow(GEO_N, 4) / 1440,
    61 * Math.pow(GEO_N, 3) / 240 - 103 * Math.pow(GEO_N, 4) / 140,
    49561 * Math.pow(GEO_N, 4) / 161280,
  ];

  function geographicToUtm(lat, lon, zone) {
    var band = zone || utmZoneFromLon(lon);
    var lam0 = (-183.0 + 6.0 * band) * Math.PI / 180;
    var phi = lat * Math.PI / 180;
    var lam = lon * Math.PI / 180 - lam0;

    var t = Math.tan(phi);
    var sigma = Math.sinh(GEO_E * Math.atanh(GEO_E * t / Math.sqrt(1 + t * t)));
    var tauP = t * Math.sqrt(1 + sigma * sigma) - sigma * Math.sqrt(1 + t * t);

    var xiP = Math.atan2(tauP, Math.cos(lam));
    var etaP = Math.asinh(Math.sin(lam) / Math.hypot(tauP, Math.cos(lam)));

    var xi = xiP, eta = etaP;
    GEO_ALPHA.forEach(function (alpha, index) {
      var j = index + 1;
      xi += alpha * Math.sin(2 * j * xiP) * Math.cosh(2 * j * etaP);
      eta += alpha * Math.cos(2 * j * xiP) * Math.sinh(2 * j * etaP);
    });

    var northing = GEO_K0 * GEO_A1 * xi;
    var hemisphere = 'N';
    if (lat < 0) { northing += 10000000.0; hemisphere = 'S'; }
    return {
      easting: GEO_FALSE_EASTING + GEO_K0 * GEO_A1 * eta,
      northing: northing, zone: band, hemisphere: hemisphere,
    };
  }

  var GEO_E2 = GEO_F * (2 - GEO_F);
  var GEO_BETA = [
    GEO_N / 2 - 2 * Math.pow(GEO_N, 2) / 3 + 37 * Math.pow(GEO_N, 3) / 96 -
      Math.pow(GEO_N, 4) / 360,
    Math.pow(GEO_N, 2) / 48 + Math.pow(GEO_N, 3) / 15 -
      437 * Math.pow(GEO_N, 4) / 1440,
    17 * Math.pow(GEO_N, 3) / 480 - 37 * Math.pow(GEO_N, 4) / 840,
    4397 * Math.pow(GEO_N, 4) / 161280,
  ];

  /* WGS84 UTM -> geographic, the same Krueger inverse the package uses, so a
   * position converted here and a position converted there are the same
   * position rather than two that happen to be close. */
  function utmToGeographic(easting, northing, zone, hemisphere) {
    var y = northing;
    if (String(hemisphere || 'N').toUpperCase().charAt(0) === 'S') y -= 10000000.0;
    var xi = y / (GEO_K0 * GEO_A1);
    var eta = (easting - GEO_FALSE_EASTING) / (GEO_K0 * GEO_A1);

    var xiP = xi, etaP = eta;
    GEO_BETA.forEach(function (beta, index) {
      var j = index + 1;
      xiP -= beta * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta);
      etaP -= beta * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta);
    });

    var tauP = Math.sin(xiP) / Math.hypot(Math.sinh(etaP), Math.cos(xiP));
    var lam = Math.atan2(Math.sinh(etaP), Math.cos(xiP));

    /* invert tau'(tau) by Newton iteration (Karney 2011) */
    var tau = tauP / Math.sqrt(1 - GEO_E2);
    for (var i = 0; i < 10; i++) {
      var sigma = Math.sinh(GEO_E * Math.atanh(GEO_E * tau / Math.sqrt(1 + tau * tau)));
      var fTau = tau * Math.sqrt(1 + sigma * sigma) - sigma * Math.sqrt(1 + tau * tau);
      var dTau = (Math.sqrt((1 + sigma * sigma) * (1 + tau * tau)) - sigma * tau) *
        (1 - GEO_E2) * Math.sqrt(1 + tau * tau) / (1 + (1 - GEO_E2) * tau * tau);
      var delta = (tauP - fTau) / dTau;
      tau += delta;
      if (Math.abs(delta) < 1e-14) break;
    }

    var out = {
      lat: Math.atan(tau) * 180 / Math.PI,
      lon: lam * 180 / Math.PI + (-183.0 + 6.0 * zone),
    };
    return isFinite(out.lat) && isFinite(out.lon) ? out : null;
  }

  Object.assign(C, {
    inferZoneForSierraLeone: inferZoneForSierraLeone,
    utmToGeographic: utmToGeographic, geographicToUtm: geographicToUtm,
    utmZoneFromLon: utmZoneFromLon,
  });

  /* ================================================================== siting
   * groundwater/siting/suitability.py. A transparent drill-target scorecard.
   *
   * Each candidate VES point is scored 0-100 from four components a siting
   * hydrogeologist weighs in crystalline basement terrain: interpreted aquifer
   * thickness, how central the water-zone resistivity sits in the productive
   * window, the weathered profile, and whether a fracture sits at the basement
   * contact. The weights are explicit and a defensible default, not a
   * calibrated model; the upgrade path is to fit them against real drilling
   * outcomes as a programme accumulates them.
   */

  var SUITABILITY_WEIGHTS = {
    aquifer_thickness: 0.35, resistivity_fit: 0.25,
    overburden: 0.20, basal_fracture: 0.20,
  };
  var THICKNESS_TARGET_M = 25.0;

  function suitabilityGrade(score) {
    if (score >= 75) return 'Very good';
    if (score >= 55) return 'Good';
    if (score >= 35) return 'Moderate';
    return 'Poor';
  }

  /* Thickness-weighted geometric mean resistivity across the water zones. */
  function zoneGeomeanRho(interp) {
    var acc = 0.0, total = 0.0;
    interp.water_zones.forEach(function (zone) {
      var top = zone[0], bottom = zone[1];
      interp.layers.forEach(function (layer) {
        var lo = Math.max(layer.top_m, top);
        var hi = Math.min(isFinite(layer.bottom_m) ? layer.bottom_m : bottom, bottom);
        if (hi > lo) {
          acc += Math.log(layer.rho) * (hi - lo);
          total += hi - lo;
        }
      });
    });
    return total > 0 ? Math.exp(acc / total) : null;
  }

  function resistivityFitScore(interp, vesConfig) {
    var mid = zoneGeomeanRho(interp);
    if (mid === null) return 0.0;
    var centre = Math.sqrt(vesConfig.fractured_zone_rho[0] *
      vesConfig.fractured_zone_rho[1]);
    return 1.0 / (1.0 + Math.abs(Math.log(Math.max(mid, 1e-3) / centre)));
  }

  function overburdenScore(interp) {
    var dtb = interp.depth_to_basement_m;
    if (dtb === null || dtb === undefined) return 0.5;   /* unknown: neutral */
    if (dtb < 5) return 0.15;                    /* too thin to store much */
    if (dtb <= 35) return 1.0;                   /* favourable weathering */
    /* deep overburden is still drillable, but the target sits deeper */
    return Math.max(0.4, 1.0 - (dtb - 35) / 60.0);
  }

  function basalFractureScore(interp) {
    var zones = interp.water_zones;
    if (!zones.length) return 0.0;
    var dtb = interp.depth_to_basement_m;
    if (dtb !== null && dtb !== undefined) {
      for (var i = 0; i < zones.length; i++) {
        /* a zone straddling or just above the fresh-basement contact is the
         * highest-yield basement target */
        if ((zones[i][0] <= dtb && dtb <= zones[i][1]) ||
            Math.abs(zones[i][1] - dtb) <= 5.0) {
          return 1.0;
        }
      }
    }
    return 0.5;
  }

  function suitabilityRationale(interp, comp) {
    if (!interp.water_zones.length) {
      return 'No water-bearing zone was resolved within the investigated ' +
        'depth, so the drilling prospect here is weak.';
    }
    var parts = [];
    parts.push('about ' + interp.aquifer_thickness_m.toFixed(0) +
      ' m of interpreted water-bearing thickness' +
      (comp.aquifer_thickness >= 0.7 ? ' (thick)'
        : comp.aquifer_thickness >= 0.4 ? ' (modest)' : ' (thin)'));
    if (comp.resistivity_fit >= 0.6) {
      parts.push('resistivities well within the productive fracture window');
    } else if (comp.resistivity_fit >= 0.35) {
      parts.push('resistivities near the edge of the productive window');
    } else {
      parts.push('resistivities outside the ideal productive window');
    }
    if (comp.basal_fracture >= 1.0) {
      parts.push('a fractured zone at the basement contact');
    }
    if (interp.depth_to_basement_m !== null && interp.depth_to_basement_m !== undefined &&
        comp.overburden < 0.4) {
      parts.push('overburden of about ' + interp.depth_to_basement_m.toFixed(0) +
        ' m that limits the target');
    }
    return 'Driven by ' + parts.join('; ') + '.';
  }

  /* Score and rank candidate VES points, most suitable first (rank 1 = best),
   * so the head of the list is the recommended drilling target. */
  function assessSiting(interpretations, vesConfig) {
    var cfg = vesConfig || defaultConfig().ves;
    var results = (interpretations || []).map(function (interp) {
      var comp = {
        aquifer_thickness: Math.min(interp.aquifer_thickness_m / THICKNESS_TARGET_M, 1.0),
        resistivity_fit: resistivityFitScore(interp, cfg),
        overburden: overburdenScore(interp),
        basal_fracture: basalFractureScore(interp),
      };
      var score = 100.0 * (
        SUITABILITY_WEIGHTS.aquifer_thickness * comp.aquifer_thickness +
        SUITABILITY_WEIGHTS.resistivity_fit * comp.resistivity_fit +
        SUITABILITY_WEIGHTS.overburden * comp.overburden +
        SUITABILITY_WEIGHTS.basal_fracture * comp.basal_fracture);
      return {
        sounding_id: interp.sounding_id,
        suitability: pyRound(score, 1),
        grade: suitabilityGrade(score),
        components: comp,
        rationale: suitabilityRationale(interp, comp),
        easting: interp.site_easting, northing: interp.site_northing,
        rank: null,
      };
    });
    /* highest suitability first, ties broken by sounding id for stability */
    var ranked = results.slice().sort(function (a, b) {
      return b.suitability - a.suitability ||
        (a.sounding_id < b.sounding_id ? -1 : a.sounding_id > b.sounding_id ? 1 : 0);
    });
    ranked.forEach(function (result, i) { result.rank = i + 1; });
    return ranked;
  }

  Object.assign(C, {
    SUITABILITY_WEIGHTS: SUITABILITY_WEIGHTS, assessSiting: assessSiting,
    suitabilityGrade: suitabilityGrade, zoneGeomeanRho: zoneGeomeanRho,
  });

  /* ================================================================ portfolio
   * groundwater/portfolio.py. A water manager oversees many boreholes, not
   * one. Each saved project file carries a small headline summary; this turns
   * a list of those summaries into a comparison table, mapped points coloured
   * by status, and programme statistics.
   */

  var STATUS_COLORS = {
    successful: '#2E7D5B', dry: '#B23A2E', sited: '#17527E', other: '#C1772A',
  };
  var STATUS_LABELS = {
    successful: 'Successful', dry: 'Dry / failed',
    sited: 'Sited (not drilled)', other: 'Other / in progress',
  };

  /* Failure wins over completion. "Completed - dry" describes the works, not
   * the outcome, and "unsuccessful" contains "success" - matching the positive
   * terms first reported failed boreholes as successful ones and inflated the
   * portfolio success rate. */
  function classifyStatus(summary) {
    var raw = String((summary && summary.status) || '').trim().toLowerCase();
    if (!raw) {
      return (summary && (summary.safe_yield_m3_per_h || summary.total_depth_m))
        ? 'sited' : 'other';
    }
    var negative = ['dry', 'fail', 'abandon', 'unsuccess', 'not success', 'no water'];
    for (var i = 0; i < negative.length; i++) {
      if (raw.indexOf(negative[i]) >= 0) return 'dry';
    }
    if (raw.indexOf('success') >= 0 || raw.indexOf('complete') >= 0 ||
        raw.indexOf('productive') >= 0) return 'successful';
    if (raw.indexOf('sit') >= 0) return 'sited';
    return 'other';
  }

  function summaryLatLon(summary) {
    var easting = summary && summary.easting, northing = summary && summary.northing;
    if (!easting || !northing) return null;
    /* the same fallback SiteMetadata.utm uses: a hard-coded zone dropped every
     * zone-less project six degrees off, into the Atlantic and off the map */
    var zone = Number(summary.utm_zone) || inferZoneForSierraLeone(Number(easting));
    try {
      return utmToGeographic(Number(easting), Number(northing), zone);
    } catch (e) { return null; }
  }

  var WATER_VERDICT_SHORT = {
    fail: 'Treat before use', aesthetic: 'Aesthetic only', pass: 'Safe',
  };
  var WATER_VERDICT_LONG = {
    fail: 'Treat before use', aesthetic: 'Aesthetic issues only',
    pass: 'Safe to drink',
  };

  function portfolioRows(summaries) {
    return (summaries || []).map(function (s) {
      var status = classifyStatus(s);
      var verdict = String(s.water_verdict || '').toLowerCase();
      return {
        Community: s.community || '(unnamed)',
        District: s.district || '',
        Status: STATUS_LABELS[status],
        'Depth (m)': s.total_depth_m ? pyRound(Number(s.total_depth_m), 1) : null,
        'Safe yield (m3/h)': s.safe_yield_m3_per_h
          ? pyRound(Number(s.safe_yield_m3_per_h), 2) : null,
        Water: WATER_VERDICT_SHORT[verdict] || '',
        'Cost/m (USD)': s.cost_per_meter_usd
          ? pyRound(Number(s.cost_per_meter_usd), 0) : null,
      };
    });
  }

  function portfolioPoints(summaries) {
    var points = [];
    (summaries || []).forEach(function (s) {
      var latlon = summaryLatLon(s);
      if (!latlon) return;
      points.push({
        label: s.community || 'site', lat: latlon.lat, lon: latlon.lon,
        status: classifyStatus(s),
      });
    });
    return points;
  }

  /* "1. Rokel (Port Loko)" - the index keeps a selector unambiguous when two
   * sites share a community name. */
  function portfolioSiteLabel(summary, index) {
    var community = (summary && summary.community) || '(unnamed site)';
    var district = summary && summary.district;
    var label = district ? community + ' (' + district + ')' : community;
    return index === undefined || index === null
      ? label : (index + 1) + '. ' + label;
  }

  function portfolioSiteDetail(summary) {
    var rows = [];
    function add(label, value) {
      if (value !== null && value !== undefined && value !== '') rows.push([label, value]);
    }
    add('Community', summary.community);
    add('District', summary.district);
    add('Chiefdom', summary.chiefdom);
    add('Status', STATUS_LABELS[classifyStatus(summary)]);
    var latlon = summaryLatLon(summary);
    if (latlon) {
      add('Location', latlon.lat.toFixed(5) + ' N, ' +
        Math.abs(latlon.lon).toFixed(5) + ' W');
    }
    add('Total depth', summary.total_depth_m
      ? Number(summary.total_depth_m).toFixed(1) + ' m' : null);
    add('Safe yield', summary.safe_yield_m3_per_h
      ? Number(summary.safe_yield_m3_per_h).toFixed(2) + ' m3/h' : null);
    add('Water quality',
      WATER_VERDICT_LONG[String(summary.water_verdict || '').toLowerCase()] || null);
    add('Cost per metre', summary.cost_per_meter_usd
      ? '$' + Number(summary.cost_per_meter_usd).toFixed(0) : null);
    return rows;
  }

  function portfolioOnePager(summary) {
    var title = portfolioSiteLabel(summary);
    var header = 'SITE BRIEF - ' + title;
    var lines = [header, new Array(header.length + 1).join('='), ''];
    portfolioSiteDetail(summary).forEach(function (row) {
      var label = row[0] + ':';
      while (label.length < 16) label += ' ';
      lines.push(label + row[1]);
    });
    lines.push('', 'Generated by the Groundwater Investigation Toolkit.');
    return lines.join('\n');
  }

  function portfolioStats(summaries) {
    var list = summaries || [];
    var drilled = list.filter(function (s) { return s.total_depth_m; });
    /* successes are counted over the same population the rate divides by, so
     * the rate can never exceed 100%: a summary classified "successful" but
     * carrying no depth is not a drilled hole */
    var successful = drilled.filter(function (s) {
      return classifyStatus(s) === 'successful';
    }).length;
    var yields = list.filter(function (s) { return s.safe_yield_m3_per_h; })
      .map(function (s) { return Number(s.safe_yield_m3_per_h); });
    var costs = list.filter(function (s) { return s.cost_per_meter_usd; })
      .map(function (s) { return Number(s.cost_per_meter_usd); });
    var verdicts = list.filter(function (s) { return s.water_verdict; })
      .map(function (s) { return String(s.water_verdict).toLowerCase(); });
    var safe = verdicts.filter(function (v) {
      return v === 'pass' || v === 'aesthetic';
    }).length;
    function mean(values) {
      return values.length
        ? values.reduce(function (a, b) { return a + b; }, 0) / values.length : null;
    }
    return {
      n_projects: list.length,
      n_drilled: drilled.length,
      n_successful: successful,
      success_rate: drilled.length ? successful / drilled.length * 100.0 : null,
      mean_safe_yield_m3_per_h: mean(yields),
      mean_cost_per_meter_usd: mean(costs),
      wq_pass_rate: verdicts.length ? safe / verdicts.length * 100.0 : null,
    };
  }

  Object.assign(C, {
    STATUS_COLORS: STATUS_COLORS, STATUS_LABELS: STATUS_LABELS,
    classifyStatus: classifyStatus, summaryLatLon: summaryLatLon,
    portfolioRows: portfolioRows, portfolioPoints: portfolioPoints,
    portfolioSiteLabel: portfolioSiteLabel,
    portfolioSiteDetail: portfolioSiteDetail,
    portfolioOnePager: portfolioOnePager, portfolioStats: portfolioStats,
  });

  /* =============================================================== depth spine
   * groundwater/depth_spine/view.py. The whole borehole on one depth axis.
   *
   * This module decides; the page draws. Every number the workspace shows is
   * computed here by the same functions the reports use, so the section, the
   * rail and the bill of quantities cannot drift from the .docx. The page owns
   * only the depth-to-pixel mapping and the pointer.
   */

  function spineFlag(flag) {
    return {
      level: flag.level, code: flag.code || '',
      message: flag.message || '', context: flag.context || '',
    };
  }

  function spineRound(value, places) {
    if (value === null || value === undefined || !isFinite(value)) return null;
    return pyRound(Number(value), places === undefined ? 2 : places);
  }

  var AQUIFER_HINTS = ['fracture', 'water', 'aquifer'];
  var NOT_AQUIFER = ['no water', 'not reached', 'without water'];

  /* Only for shading the log - screen placement uses targetZones. */
  function looksLikeAquifer(description) {
    var text = String(description || '').toLowerCase();
    var i;
    for (i = 0; i < NOT_AQUIFER.length; i++) {
      if (text.indexOf(NOT_AQUIFER[i]) >= 0) return false;
    }
    for (i = 0; i < AQUIFER_HINTS.length; i++) {
      if (text.indexOf(AQUIFER_HINTS[i]) >= 0) return true;
    }
    return false;
  }

  function spineSection(log, design, analysis, config) {
    var totalDepth = design.total_depth_m;
    /* a little air below the hole so the total-depth line is not on the edge */
    var domain = totalDepth * 1.06;

    var levels = {};
    var swl = design.static_water_level_m;
    if (swl !== null && swl !== undefined) levels.restLevel = spineRound(swl);
    if (analysis) {
      /* The toolkit only calls a level "stabilised" when the last readings
       * agree within 5 cm. When they do not, the honest line to draw is the
       * deepest level reached, labelled as still falling - drawing it as a
       * stabilised pumping level would overstate what the test showed. */
      levels.stabilised = analysis.stabilised_level_m !== null &&
        analysis.stabilised_level_m !== undefined;
      levels.maxDrawdown = spineRound(analysis.max_drawdown_m);
      if (levels.stabilised) {
        levels.pumpingLevel = spineRound(analysis.stabilised_level_m);
      } else if (swl !== null && swl !== undefined &&
                 analysis.max_drawdown_m !== null &&
                 analysis.max_drawdown_m !== undefined) {
        levels.pumpingLevel = spineRound(swl + analysis.max_drawdown_m);
      }
    }
    if (design.pump_intake_m !== null && design.pump_intake_m !== undefined) {
      levels.pumpIntake = spineRound(design.pump_intake_m, 1);
    }

    return {
      totalDepth: totalDepth,
      domain: domain,
      lithology: ((log && log.intervals) || []).map(function (iv) {
        return {
          top: iv.top_m, base: iv.bottom_m, description: iv.description,
          aquifer: looksLikeAquifer(iv.description),
        };
      }),
      waterStrikes: (design.water_strikes_m || []).slice(),
      segments: (design.segments || []).map(function (s) {
        return { kind: s.kind, top: s.top_m, base: s.bottom_m };
      }),
      gravelPack: (design.gravel_pack || []).slice(),
      backfill: (design.backfill || []).slice(),
      sanitarySeal: (design.sanitary_seal || []).slice(),
      levels: levels,
      boreDiameterIn: design.borehole_diameter_in,
      casingDiameterIn: design.casing_diameter_in,
      casingMaterial: design.casing_material,
      slotMm: design.screen_slot_mm,
      stickupM: design.stickup_m,
      drillingMethod: (log && log.drilling_method) || '',
      /* the handles may not move a screen outside this band */
      screenLimits: {
        top: 0.0,
        base: totalDepth - config.design.sump_length_m,
        minLength: 0.5,
      },
    };
  }

  /* Cross-method transmissivity, so agreement is visible rather than claimed. */
  function spineMethods(analysis) {
    var out = [];
    [['Cooper-Jacob', analysis.cooper_jacob], ['Theis', analysis.theis],
      ['Recovery', analysis.recovery]].forEach(function (pair) {
      if (!pair[1]) return;
      out.push({
        label: pair[0],
        transmissivity: spineRound(pair[1].transmissivity_m2_per_day),
      });
    });
    return out;
  }

  function spineDesignDecisions(design, analysis, config) {
    var rules = config.design;
    var yieldBlock = { pending: 'No pumping test loaded for this borehole.' };

    if (analysis && analysis.yield_recommendation) {
      var rec = analysis.yield_recommendation;
      yieldBlock = {
        pending: rec.pending_reason || '',
        safeYieldM3PerH: spineRound(rec.safe_yield_m3_per_h),
        lowM3PerH: spineRound(rec.safe_yield_low_m3_per_h),
        highM3PerH: spineRound(rec.safe_yield_high_m3_per_h),
        rangeText: rec.yield_range_text || yieldRangeText(rec),
        longTermM3PerH: spineRound(rec.long_term_yield_m3_per_h),
        specificCapacity: spineRound(rec.specific_capacity_m3hr_per_m),
        availableDrawdownM: spineRound(rec.available_drawdown_m),
        usableDrawdownM: spineRound(rec.usable_drawdown_m),
        pumpDepthM: spineRound(rec.pump_installation_depth_m, 1),
        safetyFactor: rec.safety_factor,
        designPeriodDays: rec.design_period_days,
        basis: rec.basis,
        envelopeBasis: rec.envelope_basis,
        transmissivity: spineRound(analysis.transmissivity_m2_per_day),
        methods: spineMethods(analysis),
      };
    }

    return {
      yield: yieldBlock,
      screens: (design.screens || []).map(function (s) {
        return { top: s.top_m, base: s.bottom_m };
      }),
      totalScreenM: spineRound(design.total_screen_length_m, 1),
      screenShare: spineRound(
        design.total_screen_length_m / design.total_depth_m * 100, 1),
      slotMm: design.screen_slot_mm,
      rules: {
        sumpLengthM: rules.sump_length_m,
        gravelAboveTopScreenM: rules.gravel_pack_above_top_screen_m,
        sanitarySealDepthM: rules.sanitary_seal_depth_m,
        minScreenBelowSwlM: rules.min_screen_below_swl_m,
        submergenceMinM: config.pumping.pump_submergence_min_m,
        seasonalAllowanceM: config.pumping.seasonal_allowance_m,
      },
      basis: (design.design_basis || []).slice(),
      flags: (design.flags || []).map(spineFlag)
        .concat(analysis ? (analysis.flags || []).map(spineFlag) : []),
    };
  }

  /* The limit a row is judged against, and what kind of limit it is.
   *
   * The strictest applicable maximum binds. Which one it was matters in the
   * report - a national limit exceeded is a compliance failure, an
   * acceptability limit exceeded is a taste complaint - so the name travels
   * with the number. */
  function bindingLimit(row) {
    var candidates = [
      ['WHO health', parseLimit(row.who_health)],
      ['WHO acceptability', parseLimit(row.who_aesthetic)],
      ['national', parseLimit(row.sl_standard)],
    ];
    var best = [null, ''];
    for (var i = 0; i < candidates.length; i++) {
      var name = candidates[i][0], limit = candidates[i][1];
      if (!limit) continue;
      if (limit.minimum !== null && limit.minimum !== undefined) return [limit, name];
      if (limit.maximum === null || limit.maximum === undefined) continue;
      if (!best[0] || limit.maximum < best[0].maximum) best = [limit, name];
    }
    return best;
  }

  /* Cation and anion percentages for the Piper and Stiff plots. Reuses the
   * milliequivalents the ionic balance already worked out, so the diagrams and
   * the balance check can never disagree. */
  function spinePiper(assessment) {
    if (!assessment.ionic) return null;
    var cations = assessment.ionic.cations_meq || {};
    var anions = assessment.ionic.anions_meq || {};
    function total(map) {
      return Object.keys(map).reduce(function (a, k) { return a + (map[k] || 0); }, 0);
    }
    var totalC = total(cations), totalA = total(anions);
    if (totalC <= 0 || totalA <= 0) return null;
    function c(key) { return cations[key] || 0.0; }
    function a(key) { return anions[key] || 0.0; }
    var naK = c('sodium') + c('potassium');
    return {
      meq: {
        ca: spineRound(c('calcium'), 4), mg: spineRound(c('magnesium'), 4),
        naK: spineRound(naK, 4), hco3: spineRound(a('bicarbonate'), 4),
        cl: spineRound(a('chloride'), 4), so4: spineRound(a('sulfate'), 4),
      },
      percent: {
        ca: spineRound(c('calcium') / totalC, 4),
        mg: spineRound(c('magnesium') / totalC, 4),
        naK: spineRound(naK / totalC, 4),
        hco3: spineRound(a('bicarbonate') / totalA, 4),
        cl: spineRound(a('chloride') / totalA, 4),
        so4: spineRound(a('sulfate') / totalA, 4),
      },
    };
  }

  function spineQuality(assessment) {
    var rows = (assessment.rows || []).map(function (r) {
      var pair = bindingLimit(r);
      var limit = pair[0], limitName = pair[1];
      /* the chart plots every determinand as a multiple of its own limit, so
       * the ratio is computed here rather than by parsing limit strings in
       * the page */
      var ratio = null, kind = 'none';
      if (limit) {
        kind = (limit.minimum !== null && limit.minimum !== undefined) ? 'range' : 'max';
        if (r.value !== null && r.value !== undefined && limit.maximum) {
          ratio = Number(r.value) / Number(limit.maximum);
        }
      }
      return {
        parameter: r.parameter, value: spineRound(r.value, 4), unit: r.unit,
        belowDetection: !!r.below_detection,
        whoHealth: r.who_health, whoAesthetic: r.who_aesthetic,
        national: r.sl_standard, status: r.status, remark: r.remark,
        limitKind: kind, limitName: limitName,
        limitMax: limit ? spineRound(limit.maximum, 4) : null,
        limitMin: limit ? spineRound(limit.minimum, 4) : null,
        ratio: spineRound(ratio, 4),
      };
    });

    function roundMap(map) {
      var out = {};
      Object.keys(map || {}).forEach(function (k) { out[k] = spineRound(map[k], 4); });
      return out;
    }

    var ionic = null;
    if (assessment.ionic) {
      var i = assessment.ionic;
      ionic = {
        cationsMeq: spineRound(i.sum_cations_meq, 3),
        anionsMeq: spineRound(i.sum_anions_meq, 3),
        errorPercent: spineRound(i.error_percent, 2),
        cations: roundMap(i.cations_meq), anions: roundMap(i.anions_meq),
        usedAlkalinity: !!i.used_alkalinity_for_bicarbonate,
      };
    }

    var corrosivity = null;
    if (assessment.corrosivity) {
      var cor = assessment.corrosivity;
      corrosivity = {
        lsi: spineRound(cor.lsi), rsi: spineRound(cor.rsi),
        aggressiveIndex: spineRound(cor.aggressive_index),
        larsonSkold: spineRound(cor.larson_skold),
        classification: cor.classification, isAggressive: !!cor.is_aggressive,
        verdict: cor.verdict, materialsNote: cor.materials_note,
        assumptions: (cor.assumptions || []).slice(),
      };
    }

    return {
      sampleId: assessment.sample ? assessment.sample.sample_id : '',
      sampleDate: assessment.sample ? assessment.sample.sample_date : '',
      laboratory: assessment.sample ? assessment.sample.laboratory : '',
      rows: rows,
      verdict: assessment.verdict,
      healthExceedances: (assessment.health_exceedances || [])
        .map(function (r) { return r.parameter; }),
      nationalExceedances: (assessment.national_exceedances || [])
        .map(function (r) { return r.parameter; }),
      aestheticExceedances: (assessment.rows || [])
        .filter(function (r) { return r.status === 'exceeds_aesthetic'; })
        .map(function (r) { return r.parameter; }),
      ionic: ionic,
      piper: spinePiper(assessment),
      corrosivity: corrosivity,
      wqi: assessment.wqi
        ? { value: spineRound(assessment.wqi.value, 1), rating: assessment.wqi.rating }
        : null,
      flags: (assessment.flags || []).map(spineFlag),
    };
  }

  function spineCosting(estimate) {
    var items = (estimate.items || []).map(function (i) {
      return {
        code: i.code, stage: i.stage, category: i.category, item: i.item,
        unit: i.unit, quantity: spineRound(i.quantity, 3),
        unitCost: spineRound(i.unit_cost_usd), amount: spineRound(i.amount_usd),
        note: i.note || '',
      };
    });

    function group(key) {
      var totals = {}, order = [];
      (estimate.items || []).forEach(function (i) {
        if (!(i[key] in totals)) { totals[i[key]] = 0.0; order.push(i[key]); }
        totals[i[key]] += i.amount_usd;
      });
      var direct = estimate.direct_cost_usd || 1.0;
      return order.map(function (label) {
        return {
          label: label, amount: spineRound(totals[label]),
          share: spineRound(totals[label] / direct * 100, 1),
        };
      }).sort(function (a, b) { return b.amount - a.amount; });
    }

    return {
      items: items, byStage: group('stage'), byCategory: group('category'),
      directCost: spineRound(estimate.direct_cost_usd),
      overheads: spineRound(estimate.overheads_usd),
      totalCost: spineRound(estimate.total_cost_usd),
      margin: spineRound(estimate.margin_usd),
      price: spineRound(estimate.price_usd),
      vat: spineRound(estimate.vat_usd),
      costPerMetre: spineRound(estimate.cost_per_meter_usd),
      overheadsPercent: estimate.overheads_percent,
      marginPercent: estimate.margin_percent,
      contingencyPercent: estimate.contingency_percent,
      vatPercent: estimate.vat_percent,
      exchangeRate: estimate.exchange_rate_sle_per_usd,
      assumptions: (estimate.assumptions || []).slice(),
      flags: (estimate.flags || []).map(spineFlag),
      quantityBasis: {
        totalDepthM: estimate.inputs.total_depth_m,
        casingM: spineRound(estimate.inputs.casing_m, 1),
        screenM: spineRound(estimate.inputs.screen_m, 1),
        gravelIntervalM: spineRound(estimate.inputs.gravel_interval_m, 1),
        overburdenM: spineRound(estimate.inputs.overburden_m, 1),
      },
    };
  }

  /* Derive the whole workspace from the analysis objects.
   *
   * ``screensM`` is the analyst's screen placement from the section. Passing it
   * re-runs the design and everything downstream of it - the annulus, the
   * checks and the bill of quantities - so the drawing and the BoQ are always
   * the same design. */
  function buildSpineView(inputs, screensM) {
    var config = inputs.config || defaultConfig();
    var analysis = inputs.analysis || null;
    var log = inputs.log;
    if (!log) throw new Error('the Depth Spine needs a drilling log');
    var swl = null, pumpIntake = null;
    if (analysis) {
      swl = analysis.test ? analysis.test.static_water_level_m : null;
      if (analysis.yield_recommendation) {
        pumpIntake = analysis.yield_recommendation.pump_installation_depth_m;
      }
    }

    var design = designBorehole({
      log: log, staticWaterLevelM: swl, pumpIntakeM: pumpIntake,
      rules: config.design,
      screensM: screensM && screensM.length ? screensM : null,
    });

    var estimate = estimateBoreholeCost(inputsFromDesign(design, {
      mobilisationDistanceKm: inputs.mobilisationDistanceKm || 0.0,
    }));

    var site = log.site || {};
    var latlon = null;
    if (site.easting && site.northing) {
      var zone = Number(site.utm_zone) || inferZoneForSierraLeone(Number(site.easting));
      var ll = utmToGeographic(Number(site.easting), Number(site.northing), zone);
      if (ll) latlon = [ll.lat, ll.lon];
    }

    var payload = {
      project: inputs.name || site.community || 'Borehole',
      site: {
        community: site.community || '', district: site.district || '',
        chiefdom: site.chiefdom || '', client: site.client || '',
        boreholeRef: log.borehole_ref || '', latlon: latlon,
      },
      section: spineSection(log, design, analysis, config),
      design: spineDesignDecisions(design, analysis, config),
      costing: spineCosting(estimate),
      quality: null,
      edited: !!(screensM && screensM.length),
    };

    var assessment = inputs.assessment || null;
    if (!assessment && inputs.quality) assessment = assessSample(inputs.quality);
    if (assessment) payload.quality = spineQuality(assessment);
    return payload;
  }

  Object.assign(C, {
    buildSpineView: buildSpineView, bindingLimit: bindingLimit,
    looksLikeAquifer: looksLikeAquifer,
  });

  /* =============================================================== extraction
   * groundwater/extraction/*. Getting a field sheet that arrived as a scan or
   * a PDF into the same records an uploaded template produces.
   *
   * Whatever the source, the result is header fields plus data tables, each
   * value carrying a confidence in [0, 1]. Values below the review threshold
   * are flagged and highlighted amber in the review workbook rather than
   * silently accepted: an extractor that quietly guesses a digit is worse than
   * no extractor at all.
   *
   * Two paths, as on the server. A PDF that carries a text layer is read
   * directly here - the whole reader is below, because the page must not fetch
   * a PDF library from a CDN. A photographed or image-only sheet has no text
   * to read and goes to the Claude API, which needs a key the operator
   * supplies on the Settings page.
   */

  var REVIEW_THRESHOLD = 0.85;

  var KIND_MARKERS = {
    ves: ['ves', 'schlumberger', 'apparent resistivity', 'sounding'],
    pumping_test: ['pumping test', 'step test', 'constant discharge', 'drawdown'],
    drilling_log: ['drilling', 'borehole log', 'penetration'],
    water_quality: ['water quality', 'laboratory', 'parameter', 'guideline'],
  };

  function guessDocumentKind(text) {
    var lower = String(text || '').toLowerCase();
    var best = 'unknown', bestScore = 0;
    Object.keys(KIND_MARKERS).forEach(function (kind) {
      var score = KIND_MARKERS[kind].filter(function (marker) {
        return lower.indexOf(marker) >= 0;
      }).length;
      if (score > bestScore) { bestScore = score; best = kind; }
    });
    return bestScore > 0 ? best : 'unknown';
  }

  function extractedField(name, value, confidence) {
    var conf = confidence === undefined ? 1.0 : Number(confidence);
    return {
      name: name, value: value, confidence: conf,
      needs_review: conf < REVIEW_THRESHOLD,
    };
  }

  function confidenceForRow(table, index) {
    var list = table.row_confidence || [];
    return index < list.length ? list[index] : 1.0;
  }

  /* Everything a human still has to look at, in the words the review sheet
   * uses. Mirrors ExtractedDocument.review_items. */
  function reviewItems(document) {
    var items = (document.header || []).filter(function (f) { return f.needs_review; })
      .map(function (f) {
        return "header field '" + f.name + "' = '" + f.value + "' (confidence " +
          f.confidence.toFixed(2) + ')';
      });
    (document.uncertain_cells || []).forEach(function (cell) {
      var table = (document.tables || [])[cell.table_index];
      if (!table) return;
      var value = '';
      var row = table.rows[cell.row];
      if (row && cell.column < row.length) value = row[cell.column];
      var column = cell.column < table.columns.length
        ? table.columns[cell.column] : String(cell.column + 1);
      items.push("table '" + table.title + "' row " + (cell.row + 1) +
        ", column '" + column + "' = '" + value + "'" +
        (cell.reason ? ' (' + cell.reason + ')' : ''));
    });
    return items;
  }

  /* --- the PDF text layer ---------------------------------------------------
   *
   * A deliberately small reader: enough of the PDF grammar to pull the text
   * that a generated field sheet carries, and no more. Objects are found by
   * scanning rather than through the cross-reference table, because a sheet
   * that has been through a scanner-printer often has a broken xref while its
   * objects are perfectly readable.
   */

  /* A /FlateDecode stream is zlib-wrapped, but a few writers emit the raw
   * deflate stream without the two-byte header, so try both rather than
   * failing the whole document. Kept local so this module stays free of the
   * DOM support layer. */
  async function inflateStream(bytes) {
    if (typeof DecompressionStream === 'undefined') {
      throw new Error('This browser cannot decompress PDF streams.');
    }
    var formats = ['deflate', 'deflate-raw'];
    for (var i = 0; i < formats.length; i++) {
      try {
        var stream = new Blob([bytes]).stream()
          .pipeThrough(new DecompressionStream(formats[i]));
        return new Uint8Array(await new Response(stream).arrayBuffer());
      } catch (e) {
        if (i === formats.length - 1) throw e;
      }
    }
    return bytes;
  }

  function latin1(bytes) {
    var out = '', chunk = 0x8000;
    for (var i = 0; i < bytes.length; i += chunk) {
      out += String.fromCharCode.apply(
        null, bytes.subarray(i, Math.min(i + chunk, bytes.length)));
    }
    return out;
  }

  /* /Contents 4 0 R, or /Contents [4 0 R 5 0 R] - both are common. */
  function pdfRefs(dict, key) {
    var re = new RegExp('/' + key + '\\s*(\\[[^\\]]*\\]|\\d+\\s+\\d+\\s+R)');
    var m = re.exec(dict);
    if (!m) return [];
    var refs = [];
    var each = /(\d+)\s+(\d+)\s+R/g, hit;
    while ((hit = each.exec(m[1])) !== null) refs.push(Number(hit[1]));
    return refs;
  }

  /* Balanced << >> starting at `from`, so a nested dictionary is not cut in
   * half by the first >> that happens to come along. */
  function pdfDictAt(text, from) {
    var depth = 0, i = from;
    while (i < text.length) {
      if (text.substr(i, 2) === '<<') { depth += 1; i += 2; continue; }
      if (text.substr(i, 2) === '>>') {
        depth -= 1; i += 2;
        if (depth === 0) return text.slice(from, i);
        continue;
      }
      i += 1;
    }
    return text.slice(from);
  }

  async function pdfObjects(bytes) {
    var text = latin1(bytes);
    var objects = {};
    var re = /(\d+)\s+(\d+)\s+obj\b/g, match;
    while ((match = re.exec(text)) !== null) {
      var number = Number(match[1]);
      var bodyStart = match.index + match[0].length;
      var endIndex = text.indexOf('endobj', bodyStart);
      var body = text.slice(bodyStart, endIndex < 0 ? text.length : endIndex);
      var dictStart = body.indexOf('<<');
      var dict = dictStart >= 0 ? pdfDictAt(body, dictStart) : '';
      var entry = { num: number, dict: dict, body: body, stream: null };
      var streamAt = body.indexOf('stream', dict ? dictStart + dict.length : 0);
      if (streamAt >= 0) {
        var dataStart = streamAt + 'stream'.length;
        if (body.charCodeAt(dataStart) === 13) dataStart += 1;
        if (body.charCodeAt(dataStart) === 10) dataStart += 1;
        var dataEnd = body.indexOf('endstream', dataStart);
        if (dataEnd < 0) dataEnd = body.length;
        /* /Length is authoritative when it is a direct number. Without it the
         * end-of-line before `endstream` would be handed to the decompressor
         * as trailing garbage, which is a hard error rather than something it
         * ignores, so trim it.
         *
         * The number must be the whole value: the lookahead requires the next
         * thing to be another key, the end of the dictionary, or nothing. A
         * mere "not an indirect reference" test lets the engine backtrack —
         * "/Length 12 0 R" then matches with (\d+) = "1", and a 435-byte
         * stream is cut to one byte. */
        var declared = /\/Length[ \t\r\n]+(\d+)[ \t\r\n]*(?=\/|>>|$)/.exec(dict);
        if (declared && Number(declared[1]) <= dataEnd - dataStart) {
          dataEnd = dataStart + Number(declared[1]);
        } else {
          while (dataEnd > dataStart &&
                 (body.charCodeAt(dataEnd - 1) === 10 ||
                  body.charCodeAt(dataEnd - 1) === 13)) {
            dataEnd -= 1;
          }
        }
        entry.rawStream = bytes.subarray(
          bodyStart + dataStart, bodyStart + dataEnd);
      }
      objects[number] = entry;
    }
    return objects;
  }

  async function pdfStreamText(entry) {
    if (!entry || !entry.rawStream) return '';
    if (entry.stream !== null) return entry.stream;
    var data = entry.rawStream;
    var filter = entry.dict.indexOf('/FlateDecode') >= 0;
    if (filter) {
      try {
        data = await inflateStream(data);
      } catch (e) {
        entry.stream = '';
        return '';
      }
    } else if (/\/(LZW|RunLength|DCT|CCITTFax|JBIG2|JPX)Decode/.test(entry.dict)) {
      /* an image or a filter this reader does not implement: no text in it */
      entry.stream = '';
      return '';
    }
    entry.stream = latin1(data);
    return entry.stream;
  }

  /* A ToUnicode CMap, reduced to the code -> string map the text needs. */
  function parseToUnicode(cmap) {
    var map = {};
    function decodeHex(hex) {
      var out = '';
      for (var i = 0; i + 3 < hex.length + 1; i += 4) {
        out += String.fromCharCode(parseInt(hex.substr(i, 4), 16));
      }
      return out;
    }
    var charRe = /beginbfchar([\s\S]*?)endbfchar/g, block;
    while ((block = charRe.exec(cmap)) !== null) {
      var pair = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g, hit;
      while ((hit = pair.exec(block[1])) !== null) {
        map[parseInt(hit[1], 16)] = decodeHex(hit[2]);
      }
    }
    var rangeRe = /beginbfrange([\s\S]*?)endbfrange/g;
    while ((block = rangeRe.exec(cmap)) !== null) {
      var simple = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g, span;
      while ((span = simple.exec(block[1])) !== null) {
        var lo = parseInt(span[1], 16), hi = parseInt(span[2], 16);
        var base = parseInt(span[3], 16);
        for (var code = lo; code <= hi && code - lo < 65536; code++) {
          map[code] = String.fromCharCode(base + (code - lo));
        }
      }
    }
    return map;
  }

  /* A PDF string literal: (text) with escapes, or <hex>. */
  function pdfStringBytes(token) {
    var out = [];
    if (token.charAt(0) === '<') {
      var hex = token.slice(1, -1).replace(/[^0-9A-Fa-f]/g, '');
      if (hex.length % 2) hex += '0';
      for (var h = 0; h < hex.length; h += 2) out.push(parseInt(hex.substr(h, 2), 16));
      return out;
    }
    var body = token.slice(1, -1);
    for (var i = 0; i < body.length; i++) {
      var ch = body.charAt(i);
      if (ch !== '\\') { out.push(body.charCodeAt(i)); continue; }
      var next = body.charAt(i + 1);
      var escapes = { n: 10, r: 13, t: 9, b: 8, f: 12, '(': 40, ')': 41, '\\': 92 };
      if (next in escapes) { out.push(escapes[next]); i += 1; continue; }
      if (/[0-7]/.test(next)) {
        var oct = '';
        while (oct.length < 3 && /[0-7]/.test(body.charAt(i + 1))) {
          oct += body.charAt(i + 1); i += 1;
        }
        out.push(parseInt(oct, 8));
        continue;
      }
      if (next === '\n') { i += 1; continue; }   /* line continuation */
      out.push(body.charCodeAt(i + 1)); i += 1;
    }
    return out;
  }

  function decodeWithFont(bytes, font) {
    var text = '', i;
    if (font && font.twoByte) {
      for (i = 0; i + 1 < bytes.length; i += 2) {
        var code = (bytes[i] << 8) | bytes[i + 1];
        text += font.map && code in font.map ? font.map[code]
          : String.fromCharCode(code);
      }
      return text;
    }
    for (i = 0; i < bytes.length; i++) {
      text += font && font.map && bytes[i] in font.map
        ? font.map[bytes[i]] : String.fromCharCode(bytes[i]);
    }
    return text;
  }

  /* Run one page's content stream and collect placed text.
   *
   * Only the text-positioning subset of the operator set is interpreted: the
   * text matrix, the line matrix, the showing operators and the font. That is
   * enough to know where each run of characters landed, which is what turns a
   * stream of glyphs back into lines and columns. */
  function runContentStream(content, fonts) {
    var placed = [];
    var tm = null, tlm = null, font = null, leading = 0, fontSize = 1;
    var stack = [];
    var token = /\/([^\s/<>\[\]()]+)|(\((?:\\.|[^\\()])*\))|(<[0-9A-Fa-f\s]*>)|(\[)|(\])|(-?[\d.]+)|([A-Za-z'"*]+)/g;
    var hit, operands = [], inArray = false, arrayItems = [];

    function place(bytes) {
      if (!tm) return;
      var text = decodeWithFont(bytes, font);
      if (!text) return;
      placed.push({ x: tm[4], y: tm[5], size: fontSize * Math.abs(tm[3] || 1), text: text });
      /* advance crudely: enough to keep separate runs apart, not a metrics
       * engine - the gap test below only needs relative positions */
      tm[4] += text.length * fontSize * 0.5;
    }
    function setMatrix(values) {
      tm = values.slice(); tlm = values.slice();
    }
    function nextLine(tx, ty) {
      if (!tlm) tlm = [1, 0, 0, 1, 0, 0];
      tlm[4] += tx; tlm[5] += ty;
      tm = tlm.slice();
    }

    while ((hit = token.exec(content)) !== null) {
      if (hit[1] !== undefined) {                      /* /Name */
        operands.push({ name: hit[1] });
        continue;
      }
      if (hit[2] !== undefined || hit[3] !== undefined) {    /* string */
        var value = { str: pdfStringBytes(hit[2] !== undefined ? hit[2] : hit[3]) };
        if (inArray) arrayItems.push(value); else operands.push(value);
        continue;
      }
      if (hit[4] !== undefined) { inArray = true; arrayItems = []; continue; }
      if (hit[5] !== undefined) {
        inArray = false; operands.push({ array: arrayItems }); continue;
      }
      if (hit[6] !== undefined) {
        var num = Number(hit[6]);
        if (inArray) arrayItems.push({ num: num }); else operands.push({ num: num });
        continue;
      }
      var op = hit[7];
      var nums = operands.filter(function (o) { return 'num' in o; })
        .map(function (o) { return o.num; });
      switch (op) {
        case 'BT': setMatrix([1, 0, 0, 1, 0, 0]); break;
        case 'ET': tm = null; break;
        case 'q': stack.push({ font: font, size: fontSize }); break;
        case 'Q':
          var saved = stack.pop();
          if (saved) { font = saved.font; fontSize = saved.size; }
          break;
        case 'Tf':
          var named = operands.filter(function (o) { return 'name' in o; });
          if (named.length) font = fonts[named[named.length - 1].name] || null;
          if (nums.length) fontSize = nums[nums.length - 1];
          break;
        case 'TL': if (nums.length) leading = nums[nums.length - 1]; break;
        case 'Td': if (nums.length >= 2) nextLine(nums[0], nums[1]); break;
        case 'TD':
          if (nums.length >= 2) { leading = -nums[1]; nextLine(nums[0], nums[1]); }
          break;
        case 'Tm': if (nums.length >= 6) setMatrix(nums.slice(0, 6)); break;
        case 'T*': nextLine(0, -leading); break;
        case 'Tj': case '\'': case '"':
          if (op !== 'Tj') nextLine(0, -leading);
          var strings = operands.filter(function (o) { return 'str' in o; });
          if (strings.length) place(strings[strings.length - 1].str);
          break;
        case 'TJ':
          var arrays = operands.filter(function (o) { return 'array' in o; });
          if (arrays.length) {
            arrays[arrays.length - 1].array.forEach(function (piece) {
              if ('str' in piece) place(piece.str);
              /* a large negative kern is how PDF writers space words */
              else if ('num' in piece && tm && piece.num < -120) {
                tm[4] += -piece.num / 1000 * fontSize;
                placed.push({ x: tm[4], y: tm[5], size: fontSize, text: ' ' });
              }
            });
          }
          break;
        default: break;
      }
      operands = [];
    }
    return placed;
  }

  /* Glyph runs -> lines of words. Runs land in drawing order, not reading
   * order, so they are grouped by baseline and sorted across the page. */
  function placedToLines(placed) {
    var lines = [];
    placed.forEach(function (run) {
      if (!run.text.trim() && run.text !== ' ') return;
      var tolerance = Math.max(run.size * 0.5, 2);
      var line = null;
      for (var i = 0; i < lines.length; i++) {
        if (Math.abs(lines[i].y - run.y) <= tolerance) { line = lines[i]; break; }
      }
      if (!line) { line = { y: run.y, runs: [] }; lines.push(line); }
      line.runs.push(run);
    });
    lines.sort(function (a, b) { return b.y - a.y; });
    return lines.map(function (line) {
      line.runs.sort(function (a, b) { return a.x - b.x; });
      var words = [], current = null;
      line.runs.forEach(function (run) {
        var gap = current === null ? 0 : run.x - current.end;
        if (current && gap > current.size * 0.28) {
          words.push(current); current = null;
        }
        if (!current) {
          current = { x: run.x, end: run.x, size: run.size || 10, text: '' };
        }
        current.text += run.text;
        current.end = run.x + run.text.length * (run.size || 10) * 0.5;
        current.size = run.size || current.size;
      });
      if (current) words.push(current);
      words = words.map(function (w) {
        return { x: w.x, end: w.end, text: w.text.replace(/\s+/g, ' ').trim() };
      }).filter(function (w) { return w.text; });
      return { y: line.y, words: words };
    }).filter(function (line) { return line.words.length; });
  }

  function lineText(line) {
    var out = '';
    line.words.forEach(function (word, i) {
      if (i === 0) { out += word.text; return; }
      /* three spaces mark a column break, which is what _split_line looks for */
      var gap = word.x - line.words[i - 1].end;
      out += gap > 14 ? '   ' + word.text : ' ' + word.text;
    });
    return out;
  }

  /* Tables, from the layout rather than from ruling lines.
   *
   * pdfplumber finds a table by its drawn rules; that needs the graphics
   * operators and the page's line art. Here the same job is done from word
   * positions: a run of consecutive lines that share a column structure is a
   * table. It finds the tables on a generated field sheet, and it is honest
   * about what it is - the page says so, and every numeric cell that does not
   * parse is flagged for review either way. */
  function tablesFromLines(lines, isHeaderLine) {
    var tables = [];
    var run = [];

    function flush() {
      if (run.length >= 3) {
        var columns = columnPositions(run);
        if (columns.length >= 2) {
          var grid = run.map(function (line) { return toCells(line, columns); });
          var header = grid.shift();
          if (grid.length) tables.push({ columns: header, rows: grid });
        }
      }
      run = [];
    }

    lines.forEach(function (line) {
      /* the header block is a two-column layout too, but its lines are
       * label/value pairs that have already been read as header fields;
       * folding them into the reading table would put "Community: Rokel"
       * where an AB/2 spacing belongs */
      if (line.words.length >= 2 && !(isHeaderLine && isHeaderLine(line))) {
        run.push(line);
      } else {
        flush();
      }
    });
    flush();
    return tables;
  }

  /* Column edges: word start positions that recur down the block. */
  function columnPositions(lines) {
    var starts = [];
    lines.forEach(function (line) {
      line.words.forEach(function (word) { starts.push(word.x); });
    });
    starts.sort(function (a, b) { return a - b; });
    var clusters = [];
    starts.forEach(function (x) {
      var last = clusters[clusters.length - 1];
      if (last && x - last.at <= 8) { last.n += 1; last.at = (last.at + x) / 2; return; }
      clusters.push({ at: x, n: 1 });
    });
    return clusters.filter(function (cluster) {
      return cluster.n >= Math.max(2, Math.floor(lines.length * 0.5));
    }).map(function (cluster) { return cluster.at; });
  }

  function toCells(line, columns) {
    var cells = columns.map(function () { return ''; });
    line.words.forEach(function (word) {
      var index = 0;
      for (var i = 0; i < columns.length; i++) {
        if (word.x >= columns[i] - 8) index = i;
      }
      cells[index] = cells[index] ? cells[index] + ' ' + word.text : word.text;
    });
    return cells;
  }

  var NUMERIC_COLUMN_MARKERS = ['(m)', 'm)', 'ohm', 'rate', 'level', 'depth',
    'time', 'value', 'ab/2', 'mn'];

  /* Numeric columns should parse as numbers; an empty cell in a numeric column
   * and non-numeric junk are both review items. */
  function cellConfidence(cell, column) {
    var lower = String(column || '').toLowerCase();
    var numeric = NUMERIC_COLUMN_MARKERS.some(function (marker) {
      return lower.indexOf(marker) >= 0;
    });
    if (!numeric) return [1.0, ''];
    if (cell === '') return [0.6, 'empty cell in a numeric column'];
    if (parseNumber(cell) === null) return [0.4, 'does not parse as a number'];
    return [1.0, ''];
  }

  function splitHeaderLine(line) {
    return line.split(/\t+|\s{3,}/).filter(function (part) { return part.trim(); });
  }

  async function extractPdfText(bytes, sourceName) {
    var objects = await pdfObjects(bytes);
    var numbers = Object.keys(objects).map(Number).sort(function (a, b) { return a - b; });
    var pages = numbers.map(function (n) { return objects[n]; })
      .filter(function (o) { return /\/Type\s*\/Page\b/.test(o.dict); });
    if (!pages.length) {
      throw new Error('No pages found in that PDF. If it is a photograph or a ' +
        'scan with no text layer, use the AI assisted extraction instead.');
    }

    var header = [], tables = [], uncertain = [], allText = [];
    /* null-prototype: the keys are canonical field names, and a bare object
     * would report "constructor" as already seen */
    var seen = Object.create(null);

    for (var p = 0; p < pages.length; p++) {
      var page = pages[p];
      /* fonts declared for this page, so a ToUnicode CMap can be applied.
       * null-prototype: the names come from the document, and a font called
       * /constructor would otherwise resolve to Object.prototype's. */
      var fonts = Object.create(null);
      var resourceMatch = /\/Font\s*<<([\s\S]*?)>>/.exec(page.dict);
      if (!resourceMatch) {
        var resourceRefs = pdfRefs(page.dict, 'Resources');
        if (resourceRefs.length && objects[resourceRefs[0]]) {
          resourceMatch = /\/Font\s*<<([\s\S]*?)>>/.exec(objects[resourceRefs[0]].dict);
        }
      }
      if (resourceMatch) {
        var fontRe = /\/([^\s/]+)\s+(\d+)\s+\d+\s+R/g, fontHit;
        while ((fontHit = fontRe.exec(resourceMatch[1])) !== null) {
          var fontObject = objects[Number(fontHit[2])];
          if (!fontObject) continue;
          var spec = { twoByte: /\/Type0\b/.test(fontObject.dict), map: null };
          var toUnicode = pdfRefs(fontObject.dict, 'ToUnicode');
          if (toUnicode.length && objects[toUnicode[0]]) {
            spec.map = parseToUnicode(await pdfStreamText(objects[toUnicode[0]]));
          }
          fonts[fontHit[1]] = spec;
        }
      }

      var content = '';
      var contentRefs = pdfRefs(page.dict, 'Contents');
      for (var r = 0; r < contentRefs.length; r++) {
        content += await pdfStreamText(objects[contentRefs[r]]) + '\n';
      }
      if (!content.trim()) continue;

      var lines = placedToLines(runContentStream(content, fonts));
      allText.push(lines.map(lineText).join('\n'));

      /* header labels from text lines ("Community: Rokel   Date: ...") */
      var headerLines = [];
      lines.forEach(function (line) {
        var matched = false;
        splitHeaderLine(lineText(line)).forEach(function (part) {
          var split = splitInlineValue(part);
          var key = matchLabel(split[0]);
          if (!key || !split[1]) return;
          matched = true;
          if (key in seen) return;
          seen[key] = true;
          header.push(extractedField(key, cleanText(split[1]), 0.95));
        });
        if (matched) headerLines.push(line);
      });

      tablesFromLines(lines, function (line) {
        return headerLines.indexOf(line) >= 0;
      }).forEach(function (table) {
        var index = tables.length;
        var confidences = [];
        table.rows.forEach(function (row, rowIndex) {
          var rowConfidence = 1.0;
          row.forEach(function (cell, columnIndex) {
            var judged = cellConfidence(
              cell, columnIndex < table.columns.length ? table.columns[columnIndex] : '');
            if (judged[0] < 1.0) {
              uncertain.push({
                table_index: index, row: rowIndex, column: columnIndex,
                reason: judged[1],
              });
              rowConfidence = Math.min(rowConfidence, judged[0]);
            }
          });
          confidences.push(rowConfidence);
        });
        tables.push({
          title: 'Table ' + (index + 1), columns: table.columns,
          rows: table.rows, row_confidence: confidences,
        });
      });
    }

    var blob = allText.join('\n');
    if (!blob.trim()) {
      throw new Error('That PDF carries no text layer - it is an image of a ' +
        'sheet rather than a typed one. Use the AI assisted extraction instead.');
    }
    return {
      source: sourceName || 'document.pdf',
      document_kind: guessDocumentKind(blob),
      header: header, tables: tables, uncertain_cells: uncertain,
      notes: 'Rule based extraction from the PDF text layer, read in the browser.',
      extractor: 'pdf-text',
      text: blob,
    };
  }

  /* --- the review workbook --------------------------------------------------- */

  function reviewWorkbookSheets(document) {
    var sheets = [];
    var headerRows = [['Field', 'Value', 'Confidence']];
    (document.header || []).forEach(function (field) {
      var flag = field.needs_review;
      headerRows.push([
        { v: field.name, flag: flag },
        { v: field.value, flag: flag },
        { v: pyRound(field.confidence, 2), flag: flag },
      ]);
    });
    sheets.push({ name: 'Header', rows: headerRows, widths: [28, 32, 12] });

    var flagged = {};
    (document.uncertain_cells || []).forEach(function (cell) {
      flagged[cell.table_index + ':' + cell.row + ':' + cell.column] = cell.reason;
    });

    (document.tables || []).forEach(function (table, index) {
      /* the title row is bolded by writeXlsx (row 0); the column headings are
       * row 1 and have to ask, as they do in the openpyxl workbook */
      var rows = [[table.title], table.columns.map(function (column) {
        return { v: column, bold: true };
      })];
      table.rows.forEach(function (row, rowIndex) {
        var lowConfidence = confidenceForRow(table, rowIndex) < REVIEW_THRESHOLD;
        rows.push(row.map(function (cell, columnIndex) {
          var key = index + ':' + rowIndex + ':' + columnIndex;
          return { v: cell, flag: lowConfidence || (key in flagged) };
        }));
      });
      sheets.push({ name: ('Table ' + (index + 1)).slice(0, 31), rows: rows });
    });

    var items = reviewItems(document);
    var reviewRows = [['Items needing manual review']];
    if (items.length) {
      items.forEach(function (item) { reviewRows.push([{ v: item, flag: true }]); });
    } else {
      reviewRows.push(['None: all values extracted with high confidence.']);
    }
    reviewRows.push([]);
    reviewRows.push(['Source: ' + document.source]);
    reviewRows.push(['Extractor: ' + document.extractor]);
    reviewRows.push(['Document kind: ' + document.document_kind]);
    if (document.notes) reviewRows.push(['Notes: ' + document.notes]);
    sheets.push({ name: 'Review', rows: reviewRows, widths: [100] });
    return sheets;
  }

  /* The standard VES template, filled from an extracted VES sheet. Header
   * fields go through the same label patterns the parsers use, so the filled
   * workbook reads back through the normal reader after review. */
  function fillVesTemplateSheets(document, blankRows) {
    if (document.document_kind !== 'ves') {
      throw new Error("Filling the VES template needs a document of kind 'ves'.");
    }
    if (!(document.tables || []).length) {
      throw new Error('No data table was extracted from that sheet.');
    }
    var table = document.tables[0];
    var rows = blankRows.map(function (row) { return (row || []).slice(); });

    /* canonical key -> [row, column] in the template, 0-based */
    var cellMap = {
      client: [1, 1], community: [1, 3],
      project: [2, 1], sounding_id: [2, 3],
      district: [3, 1], chiefdom: [3, 3],
      easting: [4, 1], northing: [4, 3],
      elevation_m: [5, 1], date: [5, 3],
      supervisor: [6, 1], instrument: [6, 3],
    };
    (document.header || []).forEach(function (field) {
      /* The AI path names a field the way the sheet does ("Sounding Number"),
       * which the label patterns resolve. The text-layer path has already
       * resolved it, so its name is the canonical key itself - and a canonical
       * key does not match its own pattern ("sounding_id" is not "sounding
       * number"). Accept both, or the field silently fails to land. */
      var key = field.name in cellMap ? field.name : matchLabel(field.name);
      var target = cellMap[key];
      if (!target) return;
      while (rows.length <= target[0]) rows.push([]);
      rows[target[0]][target[1]] = { v: field.value, flag: field.needs_review };
    });

    var flagged = {};
    (document.uncertain_cells || []).forEach(function (cell) {
      if (cell.table_index === 0) flagged[cell.row + ':' + cell.column] = true;
    });

    function findColumn() {
      var needles = Array.prototype.slice.call(arguments);
      for (var i = 0; i < table.columns.length; i++) {
        var low = String(table.columns[i]).toLowerCase();
        for (var n = 0; n < needles.length; n++) {
          if (low.indexOf(needles[n]) >= 0) return i;
        }
      }
      return null;
    }
    var colAb2 = findColumn('ab/2', 'ab2');
    var colMn = findColumn('mn');
    var colRho = findColumn('resist', 'ohm', 'rho');

    /* the blank template's reading grid starts on the row after the column
     * headings; everything below it is replaced by the extracted readings */
    var firstReading = 9;
    for (var i = 0; i < rows.length; i++) {
      if ((rows[i] || [])[0] === 'No.') { firstReading = i + 1; break; }
    }
    rows.length = firstReading;
    table.rows.forEach(function (row, index) {
      var out = [index + 1, '', '', ''];
      [[colAb2, 1], [colMn, 2], [colRho, 3]].forEach(function (pair) {
        if (pair[0] === null || pair[0] >= row.length) return;
        out[pair[1]] = { v: row[pair[0]], flag: (index + ':' + pair[0]) in flagged };
      });
      rows.push(out);
    });
    return rows;
  }

  /* --- AI assisted extraction ------------------------------------------------
   *
   * The same request the Python ClaudeExtractor makes, sent straight from the
   * page. The key never leaves the browser: there is no server here to hold
   * one, so the operator supplies it on the Settings page and it is stored -
   * clearly labelled - alongside the rest of the local session.
   */

  var EXTRACTION_MODEL = 'claude-opus-5';

  var EXTRACTION_SCHEMA = {
    type: 'object',
    properties: {
      document_kind: {
        type: 'string',
        enum: ['ves', 'pumping_test', 'drilling_log', 'water_quality', 'unknown'],
      },
      header: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            name: { type: 'string' },
            value: { type: 'string' },
            confidence: {
              type: 'number',
              description: '0 to 1; below 0.85 means needs manual review',
            },
          },
          required: ['name', 'value', 'confidence'],
          additionalProperties: false,
        },
      },
      tables: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            title: { type: 'string' },
            columns: { type: 'array', items: { type: 'string' } },
            rows: { type: 'array', items: { type: 'array', items: { type: 'string' } } },
          },
          required: ['title', 'columns', 'rows'],
          additionalProperties: false,
        },
      },
      uncertain_cells: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            table_index: { type: 'integer' },
            row: { type: 'integer' },
            column: { type: 'integer' },
            reason: { type: 'string' },
          },
          required: ['table_index', 'row', 'column', 'reason'],
          additionalProperties: false,
        },
      },
      notes: { type: 'string' },
    },
    required: ['document_kind', 'header', 'tables', 'uncertain_cells', 'notes'],
    additionalProperties: false,
  };

  var EXTRACTION_PROMPT = [
    'You are transcribing a groundwater field data sheet from Sierra Leone',
    '(vertical electrical sounding, pumping test, drilling log or water quality',
    'laboratory sheet).',
    '',
    'Extract:',
    '1. document_kind: which sheet type this is.',
    '2. header: every label/value pair from the header block (community, client,',
    '   district, date, borehole reference, static water level, GPS coordinates,',
    '   elevation, supervisor and so on). Use the label wording from the sheet.',
    '3. tables: every data table, with its column headings and every row, in',
    '   order. Transcribe numbers exactly as written, including leading zeros',
    '   (for example 078.7). Do not invent values for illegible cells; write an',
    '   empty string and flag the cell.',
    '4. uncertain_cells: every table cell you are not fully certain about',
    '   (handwriting hard to read, smudges, ambiguous digits), with a short',
    '   reason. Indices are zero based; row counts data rows only.',
    '5. Give each header field a confidence between 0 and 1. Use values below',
    '   0.85 whenever a reasonable person could read the handwriting differently.',
    '',
    'Accuracy matters more than completeness: flag anything doubtful rather than',
    'guessing silently.',
  ].join('\n');

  function extractionDocumentFrom(payload, source) {
    return {
      source: source,
      document_kind: payload.document_kind || 'unknown',
      header: (payload.header || []).map(function (f) {
        return extractedField(f.name || '', f.value || '',
          f.confidence === undefined ? 0.5 : Number(f.confidence));
      }),
      tables: (payload.tables || []).map(function (t, i) {
        return {
          title: t.title || ('Table ' + (i + 1)),
          columns: (t.columns || []).map(String),
          rows: (t.rows || []).map(function (row) { return (row || []).map(String); }),
          row_confidence: [],
        };
      }),
      uncertain_cells: (payload.uncertain_cells || []).map(function (c) {
        return {
          table_index: Number(c.table_index || 0), row: Number(c.row || 0),
          column: Number(c.column || 0), reason: c.reason || '',
        };
      }),
      notes: payload.notes || '',
      extractor: 'claude',
    };
  }

  async function extractWithClaude(options) {
    var opts = options || {};
    if (!opts.apiKey) {
      throw new Error('No Anthropic API key is set. Add one on the Settings ' +
        'page to use the AI assisted extraction.');
    }
    var isPdf = opts.mediaType === 'application/pdf';
    var block = isPdf
      ? { type: 'document',
        source: { type: 'base64', media_type: 'application/pdf', data: opts.base64 } }
      : { type: 'image',
        source: { type: 'base64', media_type: opts.mediaType, data: opts.base64 } };

    var response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': opts.apiKey,
        'anthropic-version': '2023-06-01',
        /* the documented opt-in for calling the API from a page; without it
         * the browser request is refused outright */
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify({
        model: opts.model || EXTRACTION_MODEL,
        max_tokens: 16000,
        thinking: { type: 'adaptive' },
        output_config: { format: { type: 'json_schema', schema: EXTRACTION_SCHEMA } },
        messages: [{
          role: 'user',
          content: [block, { type: 'text', text: EXTRACTION_PROMPT }],
        }],
      }),
    });

    if (!response.ok) {
      var detail = '';
      try {
        var body = await response.json();
        detail = (body.error && body.error.message) || '';
      } catch (e) { detail = ''; }
      throw new Error('The Claude API answered ' + response.status +
        (detail ? ': ' + detail : '.'));
    }
    var message = await response.json();
    if (message.stop_reason === 'refusal') {
      throw new Error('The extraction request was declined by the model; ' +
        'check the document content.');
    }
    /* a refusal leaves content empty, and hitting the output cap can leave
     * only thinking blocks; either way there is nothing to parse */
    var textBlock = (message.content || []).filter(function (b) {
      return b.type === 'text';
    })[0];
    if (!textBlock) {
      throw new Error('The model returned no transcription (stop reason: ' +
        (message.stop_reason || 'unknown') + '). Try a clearer scan.');
    }
    return extractionDocumentFrom(JSON.parse(textBlock.text), opts.source || 'scan');
  }

  /* --- a pumping test written on a Word field sheet -------------------------
   *
   * groundwater/ingestion/pumping.py read_pumping_docx. Some crews are handed
   * a .docx sheet rather than the workbook, and refusing it means the readings
   * get retyped - which is where transcription errors come from. A .docx is a
   * ZIP holding one XML document, so the whole reader is a parse and two
   * walks: paragraphs give the header block, and the table carrying the most
   * Time/Water Level column groups gives the readings.
   */
  async function readPumpingDocx(bytes, source) {
    var files = await GWT.support.unzip(bytes);
    var xml = files['word/document.xml'];
    if (!xml) {
      throw new Error('That .docx has no word/document.xml; it is not a Word ' +
        'document this reader can open.');
    }
    var doc = new DOMParser().parseFromString(
      new TextDecoder().decode(xml), 'application/xml');
    var W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';

    function textOf(node) {
      var runs = node.getElementsByTagNameNS(W, 't');
      var out = '';
      for (var i = 0; i < runs.length; i++) out += runs[i].textContent;
      return out;
    }

    /* This table's own rows and each row's own cells - walking the element
     * children rather than getElementsByTagName, so a nested table's rows do
     * not appear as extra rows of the table that contains it. */
    function gridOf(table) {
      var grid = [];
      for (var r = 0; r < table.childNodes.length; r++) {
        var row = table.childNodes[r];
        if (row.nodeType !== 1 || row.localName !== 'tr') continue;
        var cells = [];
        for (var c = 0; c < row.childNodes.length; c++) {
          var cell = row.childNodes[c];
          if (cell.nodeType === 1 && cell.localName === 'tc') {
            cells.push(textOf(cell).trim());
          }
        }
        grid.push(cells);
      }
      return grid;
    }

    var body = doc.getElementsByTagNameNS(W, 'body')[0];
    if (!body) throw new Error('That .docx has no document body.');

    /* paragraphs at the top level only: a paragraph inside a table cell is
     * part of that cell, not of the header block */
    var headerGrid = [];
    var tables = [];
    for (var i = 0; i < body.childNodes.length; i++) {
      var node = body.childNodes[i];
      if (node.nodeType !== 1) continue;
      if (node.localName === 'p') {
        var text = textOf(node).trim();
        if (!text) continue;
        headerGrid.push(text.split(/\t+|\s{3,}/).filter(function (part) {
          return part.trim();
        }));
      } else if (node.localName === 'tbl') {
        tables.push(gridOf(node));
      }
    }

    var best = null, bestCount = 0;
    tables.forEach(function (grid) {
      var located = findGroups(grid);
      if (located && located.groups.length > bestCount) {
        best = grid; bestCount = located.groups.length;
      }
    });
    if (!best) {
      throw new Error('No pumping test table was found in ' + (source || 'that .docx') +
        '. The reader looks for a table with Time and Water Level columns.');
    }
    return pumpingFromGrid(headerGrid.concat(best), source || 'field sheet.docx');
  }

  Object.assign(C, {
    readPumpingDocx: readPumpingDocx,
    REVIEW_THRESHOLD: REVIEW_THRESHOLD,
    guessDocumentKind: guessDocumentKind, extractedField: extractedField,
    reviewItems: reviewItems, confidenceForRow: confidenceForRow,
    extractPdfText: extractPdfText, cellConfidence: cellConfidence,
    reviewWorkbookSheets: reviewWorkbookSheets,
    fillVesTemplateSheets: fillVesTemplateSheets,
    extractWithClaude: extractWithClaude,
    extractionDocumentFrom: extractionDocumentFrom,
    EXTRACTION_MODEL: EXTRACTION_MODEL, EXTRACTION_SCHEMA: EXTRACTION_SCHEMA,
    EXTRACTION_PROMPT: EXTRACTION_PROMPT,
  });

  /* __SECTION_MARK__ */
}(typeof window !== 'undefined' ? window : globalThis));


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

  /* Where the quadrature stops (forward.py _cut, which sets the rule out).
   * The integrand is bounded by 2 rho1 exp(-x / d) times the Bessel
   * function, d = r / (2 h1), and no deeper layer slows that decay; stopping
   * n decay lengths out leaves about 2 rho1 exp(-n) sqrt(2 n d / pi), and
   * rho_a is no smaller than the least resistivity. So n solves
   * n = ln(2 rho1 / (CUT_ERROR rho_min)) + 0.5 ln(2 n d / pi), by two
   * fixed-point steps from MIN_CUT_DECAYS. The former cut, 18 decay lengths
   * of the thinnest layer, was 2.7 percent out at 150,000 over 10 ohm-m and
   * put slopes of +-17.7 into the Jacobian where it crossed a Bessel zero. */
  var CUT_ERROR = 1e-8;
  var MIN_CUT_DECAYS = 18.0;

  /** @param {number} decay @param {number} ratio rho1 over the least rho */
  function quadratureCut(decay, ratio) {
    var d = Math.max(decay, 1.0), n = MIN_CUT_DECAYS;
    for (var pass = 0; pass < 2; pass++) {
      n = Math.max(MIN_CUT_DECAYS,
        Math.log(2.0 * ratio / CUT_ERROR) + 0.5 * Math.log(2.0 * n * d / Math.PI));
    }
    return n * d;
  }

  /* the cut at radius r (an AB/2, or a potential electrode's distance) of
   * one model: decay from the top layer, contrast from the least rho */
  function cutFor(r, rho, h) {
    var scale = 2.0 * Math.max(h.length ? h[0] : 1.0, MIN_DECAY_H);
    return quadratureCut(r / scale, rho[0] / arrMin(rho));
  }

  /* Where the J0 table's panels start, and how many share the decades from
   * there to 1e-6 (forward.py _J0_FLOOR, which sets out why). Below x =
   * r / (rho_n S), S the conductance over the basement, the potential
   * integrand is the whole rho_n - rho1, and a Wenner or finite-MN reading
   * carries the piece under the lowest panel whole. One GL-8 panel on
   * (0, 1e-6) left Wenner 1.1e-3 out under 300 m of 0.5 ohm-m on 200,000;
   * inside the inversion's bounds that point is above 1e-14 for any radius
   * over 4 micrometres. The J1 table needs none of this: its integrand
   * carries x J1(x), and on (0, 1e-6) adds less than 2e-19 times the
   * largest resistivity. */
  var J0_FLOOR = 1e-14;
  var J0_LOW_PANELS = 16;

  function buildTables(order, nZeros) {
    var zeros = besselZeros(order, nZeros);
    var bessel = order === 0 ? besselJ0 : besselJ1;

    /* section 1: GL-8 on 14 log-spaced panels from 1e-6 to the first zero,
     * and below them on (0, 1e-6) for J1; for J0, on J0_LOW_PANELS more
     * log-spaced panels down to J0_FLOOR and then on (0, J0_FLOOR) */
    var gl8 = gaussLegendre(8);
    var edges = geomspace(1e-6, zeros[0], 15);
    if (order === 0) {
      edges = geomspace(J0_FLOOR, 1e-6, J0_LOW_PANELS + 1).slice(0, -1).concat(edges);
    }
    edges = [0.0].concat(edges);
    var nS1 = edges.length - 1;
    var s1n = new Float64Array(nS1 * 8), s1w = new Float64Array(nS1 * 8), at = 0;
    for (var p = 0; p < nS1; p++) {
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

  /** T(lambda): stable downward Koefoed/Pekeris recurrence from the half space.
   *   T_n = rho_n
   *   T_i = (T_{i+1} + rho_i tanh(lam h_i)) / (1 + T_{i+1} tanh(lam h_i) / rho_i)
   * Written scalar and branchy on purpose: tanh saturates for lam*h above ~20,
   * which is most of the abscissa, and skipping the call there is most of the
   * inversion's speed.
   * @param {number} lam
   * @param {ArrayLike<number>} rho
   * @param {ArrayLike<number>} h
   * @returns {number}
   */
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

  /* Int_0^inf g(x) J_order(x) dx for smooth g, carried to the first Bessel
   * zero at or past xStop (cutFor). */
  function hankelIntegral(g, order, xStop) {
    var t = tableFor(order, xStop);
    var acc = 0.0, i;
    for (i = 0; i < t.s1n.length; i++) acc += g(t.s1n[i]) * t.s1w[i];
    var nPanels = searchSorted(t.ends, xStop, t.ends.length) + 1;
    nPanels = Math.min(Math.max(nPanels, 8), t.ends.length);
    var k = nPanels * 10;
    for (i = 0; i < k; i++) acc += g(t.s2n[i]) * t.s2w[i];
    return acc;
  }

  /** Ideal (gradient, MN -> 0) Schlumberger apparent resistivity.
   * @param {ArrayLike<number>} rho
   * @param {ArrayLike<number>} h
   * @param {ArrayLike<number>} ab2
   * @returns {Float64Array}
   */
  function forwardSchlumberger(rho, h, ab2) {
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
      out[i] = rho[0] + hankelIntegral(g, 1, cutFor(L, rho, h));
    }
    return out;
  }

  /* F(r) = Int T(lam) J0(lam r) dlam, the surface potential kernel. */
  function potentialIntegral(rho, h, r) {
    var g = function (x) { return resistivityTransform(x / r, rho, h) - rho[0]; };
    return (rho[0] + hankelIntegral(g, 0, cutFor(r, rho, h))) / r;
  }

  /** What the instrument actually measures at each (AB/2, MN) pair, including
   * the small jumps at segment changes.
   * @param {ArrayLike<number>} rho
   * @param {ArrayLike<number>} h
   * @param {ArrayLike<number>} ab2
   * @param {ArrayLike<number>} mn
   * @returns {Float64Array}
   */
  function forwardSchlumbergerFiniteMn(rho, h, ab2, mn) {
    var out = new Float64Array(ab2.length);
    for (var i = 0; i < ab2.length; i++) {
      var L = ab2[i], b = mn[i] / 2.0;
      if (!isFinite(b) || b <= 0 || b >= L) {
        out[i] = forwardSchlumberger(rho, h, [L])[0];
        continue;
      }
      var fIn = potentialIntegral(rho, h, L - b);
      var fOut = potentialIntegral(rho, h, L + b);
      out[i] = (L * L - b * b) / (2.0 * b) * (fIn - fOut);
    }
    return out;
  }

  /**
   * @param {ArrayLike<number>} rho
   * @param {ArrayLike<number>} h
   * @param {ArrayLike<number>} a
   * @returns {Float64Array}
   */
  function forwardWenner(rho, h, a) {
    var out = new Float64Array(a.length);
    for (var i = 0; i < a.length; i++) {
      var s = a[i];
      var f1 = potentialIntegral(rho, h, s);
      var f2 = potentialIntegral(rho, h, 2.0 * s);
      out[i] = 2.0 * s * (f1 - f2);
    }
    return out;
  }

  /**
   * @param {ArrayLike<number>} rho
   * @param {ArrayLike<number>} h
   * @param {ArrayLike<number>} ab2
   * @param {string} [arrayType]
   * @returns {Float64Array}
   */
  function forwardCurve(rho, h, ab2, arrayType) {
    return String(arrayType || '').indexOf('wenner') === 0
      ? forwardWenner(rho, h, ab2)
      : forwardSchlumberger(rho, h, ab2);
  }

  /** Analytic two-layer ideal Schlumberger curve from image theory, used to
   * validate the numerical Hankel evaluation:
   *   rho_a(L) = rho1 [1 + 2 sum_n k^n L^3 / (L^2 + (2 n h)^2)^(3/2)]
   * @param {number} rho1
   * @param {number} rho2
   * @param {number} h
   * @param {ArrayLike<number>} ab2
   * @param {number} [nTerms]
   * @returns {Float64Array}
   */
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

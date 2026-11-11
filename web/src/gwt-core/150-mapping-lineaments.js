
  /* ============================================================ lineaments
   * groundwater/mapping/lineaments.py (PLAN.md step 4.2): straight valleys
   * and ridges found in the shading, and the rose of their strikes. The same
   * steps in the same order, from additions, multiplications, divisions and
   * square roots in a fixed order, sums of whole numbers, and the polynomial
   * sine, cosine and arctangent, so that the two engines give the same
   * candidates to the bit. The Python module says what each step is for and
   * why it is as it is; the comments here say only where the browser's way
   * of writing a step differs from numpy's. */

  var LIN_VALLEY = 1, LIN_RIDGE = -1, LIN_ROSE_BANDS = 18;
  /* what a grid no longer needed is set to, so that the collector can take
   * it before the function returns: an empty array of its type, not null */
  var LIN_DROPPED = new Float64Array(0), LIN_DROPPED_I32 = new Int32Array(0);

  /* Cephes' atan (Moshier), as lineaments.py's _atan_nonnegative, each
   * constant the shortest decimal of the double Cephes' rounds to */
  var LIN_ATAN_P = [-0.8750608600031904, -16.157537187333652, -75.00855792314705,
    -122.88666844901361, -64.85021904942025];
  var LIN_ATAN_Q = [24.858464901423062, 165.02700983169885, 432.88106049129027,
    485.3903996359137, 194.5506571482614];
  var LIN_T3P8 = 2.414213562373095, LIN_MOREBITS = 6.123233995736766e-17;
  var LIN_PIO2 = 1.5707963267948966, LIN_PIO4 = 0.7853981633974483, LIN_R2D = 180.0 / Math.PI;

  function linAtanNonnegative(x) {
    var y, extra;
    if (x > LIN_T3P8) {
      y = LIN_PIO2; x = -1.0 / x; extra = LIN_MOREBITS;
    } else if (x <= 0.66) {
      y = 0.0; extra = 0.0;
    } else {
      y = LIN_PIO4; x = (x - 1.0) / (x + 1.0); extra = 0.5 * LIN_MOREBITS;
    }
    var z = x * x;
    z = z * polevl(z, LIN_ATAN_P) / p1evl(z, LIN_ATAN_Q);
    z = x * z + x;
    return y + (z + extra);
  }

  /** The angle of the point (x, y) from the positive x axis, in degrees
   * from -180 to 180: lineaments.atan2_deg, to the bit. The origin gives 0.
   * @param {number} y
   * @param {number} x
   * @returns {number}
   */
  function atan2Deg(y, x) {
    y = Number(y);
    x = Number(x);
    if (!(isFinite(x) && isFinite(y))) return NaN;
    var ax = Math.abs(x), ay = Math.abs(y), a;
    if (ax === 0 && ay === 0) return 0.0;
    if (ay <= ax) a = linAtanNonnegative(ay / ax);
    else a = LIN_PIO2 - linAtanNonnegative(ax / ay);
    if (x < 0) a = Math.PI - a;
    if (y < 0) a = -a;
    return a * LIN_R2D;
  }

  /** `z` smoothed by `passes` passes of the binomial filter 1-2-1 along each
   * row and then along each column: lineaments.binomial_smooth. A cell takes
   * a value only when the three it is worked from are finite and inside the
   * grid.
   * @param {ArrayLike<number>} z the heights, row by row from the south
   * @param {number} rows
   * @param {number} cols
   * @param {number} passes
   * @returns {Float64Array}
   */
  function binomialSmooth(z, rows, cols, passes) {
    surfaceShape('the heights', z, rows, cols);
    if (!(Number.isInteger(passes) && passes >= 0)) {
      throw new Error('the smoothing passes must be a whole number, 0 or more');
    }
    var n = rows * cols, a = Float64Array.from(z), r, c, i;
    if (passes === 0) return a;
    var b = new Float64Array(n);
    for (var k = 0; k < passes; k++) {
      b.fill(NaN);
      if (cols >= 3) {
        for (r = 0; r < rows; r++) {
          for (c = 1; c < cols - 1; c++) {
            i = r * cols + c;
            b[i] = ((a[i - 1] + 2.0 * a[i]) + a[i + 1]) * 0.25;
          }
        }
      }
      a.fill(NaN);
      if (rows >= 3) {
        for (r = 1; r < rows - 1; r++) {
          for (c = 0; c < cols; c++) {
            i = r * cols + c;
            a[i] = ((b[i - cols] + 2.0 * b[i]) + b[i + cols]) * 0.25;
          }
        }
      }
    }
    return a;
  }

  /* The gradients of the hillshades of zs, one sun at a time in the order
   * given, added up from 0 as a structure tensor: lineaments._edge_tensor */
  function linEdgeTensor(zs, rows, cols, metric, azimuths, alt, zf) {
    var slope = hornGradients(zs, rows, cols, metric), n = rows * cols;
    var txx = new Float64Array(n), tyy = new Float64Array(n), txy = new Float64Array(n);
    for (var k = 0; k < azimuths.length; k++) {
      var shade = hillshadeLayer(slope.p, slope.q, azimuths[k], alt, zf);
      var g = hornGradients(shade, rows, cols, metric), gp = g.p, gq = g.q;
      for (var i = 0; i < n; i++) {
        var gx = gp[i], gy = gq[i];
        txx[i] += gx * gx;
        tyy[i] += gy * gy;
        txy[i] += gx * gy;
      }
    }
    return { txx: txx, tyy: tyy, txy: txy };
  }

  /* The lineament settings, each refused unless it is a finite number in
   * its range, in Python's words: lineaments._settings */
  function linSettings(cfg) {
    var out = {};
    ['lineament_smoothing_m', 'lineament_contrast_km', 'lineament_min_curvature_per_km', 'lineament_turn_deg',
      'lineament_straight_m', 'lineament_piece_m', 'lineament_min_length_m', 'lineament_link_angle_deg', 'lineament_link_offset_m',
      'lineament_link_gap_m'].forEach(function (name) {
      var value = Number(cfg[name]);
      if (!(isFinite(value) && value > 0)) throw new Error('terrain.' + name + ' must be a number above 0');
      out[name] = value;
    });
    var share = Number(cfg.lineament_share);
    if (!(isFinite(share) && share > 0 && share <= 1)) {
      throw new Error('terrain.lineament_share must be above 0 and at most 1');
    }
    out.lineament_share = share;
    ['lineament_turn_deg', 'lineament_link_angle_deg'].forEach(function (name) {
      if (out[name] >= 90) throw new Error('terrain.' + name + ' must be under 90 degrees');
    });
    return out;
  }

  function linEmpty(settings, shown, frame, summary) {
    var zeros = [], none = [];
    for (var k = 0; k < LIN_ROSE_BANDS; k++) {
      zeros.push(0.0);
      none.push(0);
    }
    return { lineaments: [], roseValleyM: zeros, roseRidgeM: zeros.slice(), roseValleys: none,
      roseRidges: none.slice(), frame: frame, shown: shown.slice(), summary: summary, settings: settings };
  }

  /**
   * The lineament candidates of an analysed window:
   * lineaments.lineament_candidates. `cfg` overrides the defaults as
   * analyseTerrain's does; left out, the settings the window was analysed
   * with are used. `progress(fraction, label)` hears the stage start.
   * @param {TerrainAnalysis} analysis what analyseTerrain gives
   * @param {Rec|null} [cfg]
   * @param {((fraction: number, label: string) => void)|null} [progress]
   * @returns {Rec}
   */
  function lineamentCandidates(analysis, cfg, progress) {
    var settings = cfg ? withConfig(cfg).terrain : analysis.settings;
    var s = linSettings(settings);
    var label = phrase('terrain.stage_lineaments');
    if (progress) progress(0.0, label);
    var core = analysis.core, rows = core.rows, cols = core.cols, shown = core.shown;
    var r0 = shown[0], r1 = shown[1], c0 = shown[2], c1 = shown[3];
    var metric = analysis.metric, sqrt = Math.sqrt, abs = Math.abs;
    var mid = Math.min(Math.floor((r0 + r1) / 2), rows - 1);
    var dx0 = metric.dx[mid], dy0 = metric.dy[mid], frame = [dx0, dy0];
    var cell = (dx0 + dy0) * 0.5;
    var ratio = s.lineament_smoothing_m / cell;
    var passes = Math.floor((2.0 * ratio) * ratio + 0.5);
    var half = Math.max(1, Math.floor((s.lineament_contrast_km * 500.0) / cell + 0.5));
    /** @type {Rec} */
    var summary = { passes: passes, contrast_cells: half, centre_cells: 0, kept_cells: 0, lines: 0, pieces: 0,
      candidates: 0, valleys: 0, ridges: 0, linked: 0, length_m: 0.0, threshold: NaN };
    if (rows < 3 || cols < 3) return linEmpty(settings, shown, frame, summary);

    /* the heights the routing worked from, every void blank */
    var n = rows * cols, cls = core.cls, given = analysis.grid.z, z = new Float64Array(n), i, k;
    for (i = 0; i < n; i++) z[i] = cls[i] === ROUTE_VOID ? NaN : given[i] + 0.0;
    var zs = binomialSmooth(z, rows, cols, passes);
    z = LIN_DROPPED;
    var tensor = linEdgeTensor(zs, rows, cols, metric, settings.hillshade_panel_azimuths_deg,
      settings.hillshade_altitude_deg, settings.hillshade_z_factor);
    var txx = tensor.txx, tyy = tensor.tyy, txy = tensor.txy;
    /* the floor on the strength, 2 (k cos alt)^2 for ground bending by k
     * per metre across a line */
    var bendM = s.lineament_min_curvature_per_km / 1000.0;
    var scaled = bendM * sinCosDeg(settings.hillshade_altitude_deg)[1], floor = 2.0 * (scaled * scaled);
    var strength = new Float64Array(n);
    for (i = 0; i < n; i++) strength[i] = txx[i] + tyy[i];

    /* the line cells, the direction across the line at each from its
     * doubled angle, and Canny's thinning; a neighbour beyond the grid
     * reads as NaN, as the NaN border numpy's version pads the grid with */
    var at = function (rr, cc) {
      return rr >= 0 && rr < rows && cc >= 0 && cc < cols ? strength[rr * cols + cc] : NaN;
    };
    var idx = [], nx = [], ny = [], here = [], lined = 0;
    for (i = 0; i < n; i++) {
      var sum = strength[i];
      var ax = txx[i] - tyy[i], ay = txy[i] + txy[i];
      var m2 = ax * ax + ay * ay;
      if (!(cls[i] === ROUTE_LAND && sum >= floor && sum > 0 && m2 > 0)) continue;
      lined += 1;
      var m = sqrt(m2), c2 = ax / m;
      c2 = c2 > 1.0 ? 1.0 : (c2 < -1.0 ? -1.0 : c2);
      var vx = sqrt((1.0 + c2) * 0.5), vy = sqrt((1.0 - c2) * 0.5);
      if (ay < 0) vy = -vy;
      var r = Math.floor(i / cols), c = i - r * cols;
      var anx = abs(vx), any = abs(vy), majorX = anx >= any;
      var sx = vx < 0 ? -1 : 1, sy = vy < 0 ? -1 : 1, frac = majorX ? any / anx : anx / any;
      var aPlus, dPlus, aMinus, dMinus;
      if (majorX) {
        aPlus = at(r, c + sx);
        aMinus = at(r, c - sx);
      } else {
        aPlus = at(r + sy, c);
        aMinus = at(r - sy, c);
      }
      dPlus = at(r + sy, c + sx);
      dMinus = at(r - sy, c - sx);
      var ahead = aPlus + frac * (dPlus - aPlus), behind = aMinus + frac * (dMinus - aMinus);
      if (sum > ahead && sum >= behind) {
        idx.push(i);
        nx.push(vx);
        ny.push(vy);
        here.push(sum);
      }
    }
    tensor.txx = tensor.tyy = tensor.txy = txx = tyy = txy = LIN_DROPPED;
    if (!lined) return linEmpty(settings, shown, frame, summary);
    summary.centre_cells = idx.length;

    /* each weighed against the mean strength around it, from sums over the
     * grid taken along each row and then down each column, as numpy's two
     * cumsums take them */
    var w = cols + 1, total = new Float64Array((rows + 1) * w), counts = new Float64Array((rows + 1) * w);
    for (var rr0 = 0; rr0 < rows; rr0++) {
      var run = 0.0, many = 0;
      for (var cc0 = 0; cc0 < cols; cc0++) {
        var v = strength[rr0 * cols + cc0], finite = v - v === 0;
        run = run + (finite ? v : 0.0);
        many = many + (finite ? 1 : 0);
        total[(rr0 + 1) * w + cc0 + 1] = total[rr0 * w + cc0 + 1] + run;
        counts[(rr0 + 1) * w + cc0 + 1] = counts[rr0 * w + cc0 + 1] + many;
      }
    }
    strength = LIN_DROPPED;
    var relative = new Float64Array(idx.length), inside = [];
    for (k = 0; k < idx.length; k++) {
      i = idx[k];
      var row = Math.floor(i / cols), col = i - row * cols;
      var ra = Math.max(row - half, 0), rb = Math.min(row + half + 1, rows);
      var ca = Math.max(col - half, 0), cb = Math.min(col + half + 1, cols);
      var box = ((total[rb * w + cb] - total[ra * w + cb]) - total[rb * w + ca]) + total[ra * w + ca];
      var number = ((counts[rb * w + cb] - counts[ra * w + cb]) - counts[rb * w + ca]) + counts[ra * w + ca];
      relative[k] = box > 0 ? here[k] / (box / number) : NaN;
      if (row >= r0 && row < r1 && col >= c0 && col < c1) inside.push(relative[k]);
    }
    total = counts = LIN_DROPPED;
    var share = s.lineament_share;
    var threshold = displayRange(inside, 1.0 - share, 1.0 - share)[0];
    summary.threshold = threshold;
    if (!isFinite(threshold)) return linEmpty(settings, shown, frame, summary);

    /* valley or ridge, by the curvature across the line */
    var zAt = function (rr, cc) { return rr >= 0 && rr < rows && cc >= 0 && cc < cols ? zs[rr * cols + cc] : NaN; };
    var kIdx = [], kR = [], kC = [], kNx = [], kNy = [], kKind = [];
    for (k = 0; k < idx.length; k++) {
      if (!(relative[k] >= threshold)) continue;
      i = idx[k];
      var r2 = Math.floor(i / cols), c3 = i - r2 * cols;
      var dxr = metric.dx[r2], dyr = metric.dy[r2], z0 = zs[i], ex = nx[k], ey = ny[k];
      var zxx = ((zAt(r2, c3 + 1) - 2.0 * z0) + zAt(r2, c3 - 1)) / (dxr * dxr);
      var zyy = ((zAt(r2 + 1, c3) - 2.0 * z0) + zAt(r2 - 1, c3)) / (dyr * dyr);
      var zxy = ((zAt(r2 + 1, c3 + 1) - zAt(r2 + 1, c3 - 1)) - (zAt(r2 - 1, c3 + 1) - zAt(r2 - 1, c3 - 1))) /
        ((4.0 * dxr) * dyr);
      var bend = (((zxx * ex) * ex) + (((2.0 * zxy) * ex) * ey)) + ((zyy * ey) * ey);
      var kindK = bend > 0 ? LIN_VALLEY : (bend < 0 ? LIN_RIDGE : 0);
      if (!kindK) continue;
      kIdx.push(i);
      kR.push(r2);
      kC.push(c3);
      kNx.push(ex);
      kNy.push(ey);
      kKind.push(kindK);
    }
    zs = LIN_DROPPED;
    summary.kept_cells = kIdx.length;
    if (!kIdx.length) return linEmpty(settings, shown, frame, summary);

    /* lines: neighbouring cells of one kind whose directions agree, joined
     * by union-find and named by their first cell, as Python names the
     * components scipy finds */
    var count = kIdx.length, where = new Int32Array(n).fill(-1), parent = new Int32Array(count);
    for (k = 0; k < count; k++) {
      where[kIdx[k]] = k;
      parent[k] = k;
    }
    var root = function (a) {
      while (parent[a] !== a) {
        parent[a] = parent[parent[a]];
        a = parent[a];
      }
      return a;
    };
    var cosTurn = sinCosDeg(s.lineament_turn_deg)[1];
    var offsets = [[0, 1], [1, -1], [1, 0], [1, 1]];
    for (k = 0; k < count; k++) {
      for (var o = 0; o < 4; o++) {
        var rn = kR[k] + offsets[o][0], cn = kC[k] + offsets[o][1];
        if (!(rn < rows && cn >= 0 && cn < cols)) continue;
        var j = where[rn * cols + cn];
        if (j < 0) continue;
        if (kKind[k] === kKind[j] && abs(kNx[k] * kNx[j] + kNy[k] * kNy[j]) >= cosTurn) {
          var ra2 = root(k), rb2 = root(j);
          if (ra2 !== rb2) parent[ra2 < rb2 ? rb2 : ra2] = ra2 < rb2 ? ra2 : rb2;
        }
      }
    }
    where = LIN_DROPPED_I32;
    var groupOf = new Int32Array(count).fill(-1);
    /** @type {number[][]} */
    var groups = [];
    for (k = 0; k < count; k++) {
      var top = root(k);
      if (groupOf[top] < 0) {
        groupOf[top] = groups.length;
        groups.push([]);
      }
      groups[groupOf[top]].push(k);
    }
    summary.lines = groups.length;

    /* straight pieces of each line long enough to hold one */
    var shortest = s.lineament_piece_m, pieces = [];
    groups.forEach(function (members) {
      var rMin = Infinity, rMax = -Infinity, cMin = Infinity, cMax = -Infinity;
      members.forEach(function (q) {
        if (kR[q] < rMin) rMin = kR[q];
        if (kR[q] > rMax) rMax = kR[q];
        if (kC[q] < cMin) cMin = kC[q];
        if (kC[q] > cMax) cMax = kC[q];
      });
      var eyM = (rMax - rMin) * dy0, exM = (cMax - cMin) * dx0;
      if (!(sqrt(eyM * eyM + exM * exM) >= shortest)) return;
      linStraightPieces(members.map(function (q) { return kR[q]; }), members.map(function (q) { return kC[q]; }),
        kKind[members[0]], dx0, dy0, s.lineament_straight_m, shortest, pieces);
    });
    summary.pieces = pieces.length;

    /* linked along one line, cut to the square shown */
    var linked = linLink(pieces, s.lineament_link_angle_deg, s.lineament_link_offset_m, s.lineament_link_gap_m);
    var bounds = [(c0 - 0.5) * dx0, (c1 - 0.5) * dx0, (r0 - 0.5) * dy0, (r1 - 0.5) * dy0];
    var out = [];
    linked.forEach(function (item) {
      var clipped = linClip(item.ox, item.oy, item.ux, item.uy, item.lo, item.hi, bounds);
      if (!clipped) return;
      var t0 = clipped[0], t1 = clipped[1], length = t1 - t0;
      if (!(length >= s.lineament_min_length_m)) return;
      var strike = atan2Deg(item.ux, item.uy);
      if (strike < 0) strike = strike + 180.0;
      strike = strike + 0.0;
      out.push({ id: out.length, kind: item.kind === LIN_VALLEY ? 'valley' : 'ridge',
        start: [item.ox + t0 * item.ux, item.oy + t0 * item.uy], end: [item.ox + t1 * item.ux, item.oy + t1 * item.uy],
        length_m: length, strike_deg: strike, pieces: item.pieces, cells: item.cells,
        cut: t0 > item.lo || t1 < item.hi });
    });

    var roseV = [], roseR = [], countV = [], countR = [], totalLength = 0.0, valleys = 0, ridges = 0, many2 = 0;
    for (k = 0; k < LIN_ROSE_BANDS; k++) {
      roseV.push(0.0);
      roseR.push(0.0);
      countV.push(0);
      countR.push(0);
    }
    out.forEach(function (item) {
      var band = Math.min(LIN_ROSE_BANDS - 1, Math.floor(item.strike_deg / 10.0));
      if (item.kind === 'valley') {
        roseV[band] += item.length_m;
        countV[band] += 1;
        valleys += 1;
      } else {
        roseR[band] += item.length_m;
        countR[band] += 1;
        ridges += 1;
      }
      totalLength += item.length_m;
      if (item.pieces > 1) many2 += 1;
    });
    Object.assign(summary, { candidates: out.length, valleys: valleys, ridges: ridges, linked: many2,
      length_m: totalLength });
    if (progress) progress(1.0, label);
    return { lineaments: out, roseValleyM: roseV, roseRidgeM: roseR, roseValleys: countV, roseRidges: countR,
      frame: frame, shown: shown.slice(), summary: summary, settings: settings };
  }

  /* Cut one line into straight pieces: lineaments._straight_pieces. The
   * moments are sums of whole numbers, exact as Numbers; the products of
   * two of them are taken in BigInt, as Python's int takes them, and
   * rounded once to a double. */
  function linStraightPieces(rr, cc, kind, dx0, dy0, tol, shortest, out) {
    var sqrt = Math.sqrt, abs = Math.abs;
    var all = [];
    for (var a = 0; a < rr.length; a++) all.push(a);
    var stack = [all];
    while (stack.length) {
      var sel = /** @type {number[]} */ (stack.pop()), n = sel.length, k, q;
      if (n < 2) continue;
      var sr = 0, sc = 0, srr = 0, scc = 0, src = 0;
      for (k = 0; k < n; k++) {
        q = sel[k];
        var r = rr[q], c = cc[q];
        sr += r;
        sc += c;
        srr += r * r;
        scc += c * c;
        src += r * c;
      }
      var big = BigInt(n);
      var crr = Number(big * BigInt(srr) - BigInt(sr) * BigInt(sr));
      var ccc = Number(big * BigInt(scc) - BigInt(sc) * BigInt(sc));
      var crc = Number(big * BigInt(src) - BigInt(sr) * BigInt(sc));
      var nn = n * n;
      var vyy = ((crr / nn) * dy0) * dy0, vxx = ((ccc / nn) * dx0) * dx0, vxy = ((crc / nn) * dx0) * dy0;
      var my = (sr / n) * dy0, mx = (sc / n) * dx0;
      var halfSum = (vxx + vyy) * 0.5, halfDiff = (vxx - vyy) * 0.5;
      var l1 = halfSum + sqrt(halfDiff * halfDiff + vxy * vxy);
      var ux, uy;
      if (vxx >= vyy) {
        ux = l1 - vyy;
        uy = vxy;
      } else {
        ux = vxy;
        uy = l1 - vxx;
      }
      var norm = sqrt(ux * ux + uy * uy);
      if (!(norm > 0)) continue;
      ux = ux / norm;
      uy = uy / norm;
      var t = new Float64Array(n), off = new Float64Array(n), lo = Infinity, hi = -Infinity, best = -1;
      for (k = 0; k < n; k++) {
        q = sel[k];
        var x = cc[q] * dx0, y = rr[q] * dy0;
        t[k] = (x - mx) * ux + (y - my) * uy;
        off[k] = abs((y - my) * ux - (x - mx) * uy);
        if (t[k] < lo) lo = t[k];
        if (t[k] > hi) hi = t[k];
        if (best < 0 || off[k] > off[best]) best = k;
      }
      if (hi - lo < shortest) continue;
      if (off[best] > tol) {
        var cut = t[best], left = [], right = [];
        var lLo = Infinity, lHi = -Infinity, rLo = Infinity, rHi = -Infinity;
        for (k = 0; k < n; k++) {
          if (t[k] <= cut) {
            left.push(sel[k]);
            if (t[k] < lLo) lLo = t[k];
            if (t[k] > lHi) lHi = t[k];
          } else {
            right.push(sel[k]);
            if (t[k] < rLo) rLo = t[k];
            if (t[k] > rHi) rHi = t[k];
          }
        }
        var spanL = left.length ? lHi - lLo : 0.0, spanR = right.length ? rHi - rLo : 0.0;
        if (spanL >= shortest && spanR >= shortest) {
          stack.push(left);
          stack.push(right);
        } else {
          var near = [];
          for (k = 0; k < n; k++) if (off[k] <= tol) near.push(sel[k]);
          if (near.length) stack.push(near);
        }
        continue;
      }
      var xa = mx + lo * ux, ya = my + lo * uy, xb = mx + hi * ux, yb = my + hi * uy;
      if ((yb - ya) < 0 || ((yb - ya) === 0 && (xb - xa) < 0)) {
        var tx = xa, ty = ya;
        xa = xb;
        ya = yb;
        xb = tx;
        yb = ty;
      }
      out.push([hi - lo, kind, xa, ya, xb, yb, n]);
    }
  }

  /* Link the pieces lying along one line into candidates: lineaments._link.
   * The lesser and the greater of two values are taken by an explicit test,
   * as Python takes them, so that a tie of +0 and -0 goes the same way. */
  function linLink(pieces, angleDeg, offsetM, gapM) {
    var cmp = function (a, b) { return a < b ? -1 : (a > b ? 1 : 0); };
    var order = pieces.slice().sort(function (p, q) {
      return cmp(q[0], p[0]) || cmp(p[1], q[1]) || cmp(p[2], q[2]) || cmp(p[3], q[3]) || cmp(p[4], q[4]) ||
        cmp(p[5], q[5]);
    });
    var sinAngle = sinCosDeg(angleDeg)[0], abs = Math.abs, kept = [];
    order.forEach(function (piece) {
      var length = piece[0], kind = piece[1], xa = piece[2], ya = piece[3], xb = piece[4], yb = piece[5];
      var vx = (xb - xa) / length, vy = (yb - ya) / length;
      for (var j = 0; j < kept.length; j++) {
        var c = kept[j];
        if (c.kind !== kind) continue;
        var cross = abs(c.ux * vy - c.uy * vx);
        var dA = abs((ya - c.oy) * c.ux - (xa - c.ox) * c.uy);
        var dB = abs((yb - c.oy) * c.ux - (xb - c.ox) * c.uy);
        var tA = (xa - c.ox) * c.ux + (ya - c.oy) * c.uy;
        var tB = (xb - c.ox) * c.ux + (yb - c.oy) * c.uy;
        var first = tA <= tB, pLo = first ? tA : tB, pHi = first ? tB : tA;
        if (!(cross <= sinAngle && dA <= offsetM && dB <= offsetM)) continue;
        if ((pLo - c.hi) > gapM || (c.lo - pHi) > gapM) continue;
        if (pLo < c.lo) c.lo = pLo;
        if (pHi > c.hi) c.hi = pHi;
        c.pieces += 1;
        c.cells += piece[6];
        return;
      }
      kept.push({ kind: kind, ox: xa, oy: ya, ux: vx, uy: vy, lo: 0.0, hi: length, pieces: 1, cells: piece[6] });
    });
    return kept;
  }

  /* The span of the line (ox, oy) + t (ux, uy), lo <= t <= hi, inside the
   * rectangle [west, east, south, north], or null: lineaments._clip */
  function linClip(ox, oy, ux, uy, lo, hi, bounds) {
    var t0 = lo, t1 = hi;
    var axes = [[ox, ux, bounds[0], bounds[1]], [oy, uy, bounds[2], bounds[3]]];
    for (var a = 0; a < 2; a++) {
      var origin = axes[a][0], along = axes[a][1], low = axes[a][2], high = axes[a][3];
      if (along === 0) {
        if (origin < low || origin > high) return null;
        continue;
      }
      var ta = (low - origin) / along, tb = (high - origin) / along;
      if (ta > tb) {
        var swap = ta;
        ta = tb;
        tb = swap;
      }
      if (ta > t0) t0 = ta;
      if (tb < t1) t1 = tb;
    }
    if (t1 < t0) return null;
    return [t0, t1];
  }

  /** A point of the window's frame as [longitude, latitude]:
   * lineaments.lineament_lonlat.
   * @param {Rec} result what lineamentCandidates gives
   * @param {ArrayLike<number>} lons the analysed window's column centres
   * @param {ArrayLike<number>} lats its row centres, from the south
   * @param {number[]} point [x, y] in metres
   * @returns {number[]}
   */
  function lineamentLonLat(result, lons, lats, point) {
    var col = point[0] / result.frame[0], row = point[1] / result.frame[1];
    var i = Math.min(Math.max(Math.floor(col), 0), lons.length - 2);
    var j = Math.min(Math.max(Math.floor(row), 0), lats.length - 2);
    return [lons[i] + (col - i) * (lons[i + 1] - lons[i]), lats[j] + (row - j) * (lats[j + 1] - lats[j])];
  }

  function linAzimuths(settings) {
    return andJoin(settings.hillshade_panel_azimuths_deg.map(function (azimuth) {
      return formatG(Number(azimuth)) + '°';
    }));
  }

  /** The titles and captions of the lineament map and its rose:
   * lineaments.lineament_captions.
   * @param {Rec} result what lineamentCandidates gives
   * @param {string} where the place, as the read report names it
   * @returns {Record<string, string>}
   */
  function lineamentCaptions(result, where) {
    var settings = result.settings;
    var common = { length: Number(settings.lineament_min_length_m), smoothing: Number(settings.lineament_smoothing_m),
      azimuths: linAzimuths(settings) };
    var caption = result.lineaments.length
      ? phrase('terrain.caption_lineaments', Object.assign({ valleys: result.summary.valleys,
        ridges: result.summary.ridges }, common))
      : phrase('terrain.caption_lineaments_none', common);
    return {
      title_lineaments: phrase('terrain.title_lineaments', { where: where }),
      title_rose: phrase('terrain.title_rose', { where: where }),
      lineaments: caption,
      rose: phrase('terrain.caption_rose'),
      figure_note: phrase('terrain.figure_note_lineaments'),
      rose_valleys: phrase('terrain.rose_valleys', { count: linSum(result.roseValleys),
        km: linSum(result.roseValleyM) / 1000.0 }),
      rose_ridges: phrase('terrain.rose_ridges', { count: linSum(result.roseRidges),
        km: linSum(result.roseRidgeM) / 1000.0 }),
    };
  }

  /* a sum taken in order from 0, as Python's sum() takes it */
  function linSum(values) {
    var total = 0;
    for (var i = 0; i < values.length; i++) total = total + values[i];
    return total;
  }

  /** The candidates shown as GeoJSON text, byte for byte as
   * lineaments.lineament_geojson writes it.
   * @param {Rec} result what lineamentCandidates gives
   * @param {ArrayLike<number>} lons
   * @param {ArrayLike<number>} lats
   * @param {Rec} meta label, figure_credit, notice, surface, radius and centre, as drainageGeoJson's
   * @returns {string}
   */
  function lineamentGeoJson(result, lons, lats, meta) {
    var settings = result.settings, centre = meta.centre;
    var description = phrase('terrain.lineament_geojson_description', { label: meta.label,
      length: Number(settings.lineament_min_length_m), radius: Number(meta.radius), where: centre.label,
      smoothing: Number(settings.lineament_smoothing_m), azimuths: linAzimuths(settings), surface: meta.surface });
    var out = ['{"type":"FeatureCollection","description":', jsonAscii(description),
      ',"attribution":', jsonAscii(String(meta.figure_credit))];
    if (meta.notice) out.push(',"notice":', jsonAscii(String(meta.notice)));
    out.push(',"min_length_m":' + formatG(Number(settings.lineament_min_length_m)),
      ',"radius_km":' + formatG(Number(meta.radius)),
      ',"centre":[' + pyFixed(Number(centre.lon), 6) + ',' + pyFixed(Number(centre.lat), 6) + '],"features":[');
    result.lineaments.forEach(function (item, t) {
      var a = lineamentLonLat(result, lons, lats, item.start), b = lineamentLonLat(result, lons, lats, item.end);
      out.push((t ? ',' : '') +
        '{"type":"Feature","properties":{"lineament":' + String(item.id) + ',"kind":' + jsonAscii(item.kind) +
        ',"length_m":' + pyFixed(item.length_m, 1) + ',"strike_deg":' + pyFixed(item.strike_deg, 1) +
        ',"pieces":' + String(item.pieces) + ',"cut":' + (item.cut ? 'true' : 'false') +
        '},"geometry":{"type":"LineString","coordinates":[[' + pyFixed(a[0], 6) + ',' + pyFixed(a[1], 6) + '],[' +
        pyFixed(b[0], 6) + ',' + pyFixed(b[1], 6) + ']]}}');
    });
    out.push(']}');
    return out.join('');
  }

  Object.assign(C, {
    atan2Deg: atan2Deg, binomialSmooth: binomialSmooth, lineamentCandidates: lineamentCandidates,
    lineamentLonLat: lineamentLonLat, lineamentCaptions: lineamentCaptions, lineamentGeoJson: lineamentGeoJson,
  });

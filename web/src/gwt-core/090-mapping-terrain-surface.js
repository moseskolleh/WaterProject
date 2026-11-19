
  /* ============================================ Terrain analysis: surface
   * groundwater/mapping/terrain_analysis.py's surface kernels: the slope
   * and shading of the ground (Horn's gradients, one sun, and gdaldem's
   * multidirectional composite), the topographic wetness index, profile
   * and tangential curvature at a stated spacing, and the two numbers the
   * figures are drawn with, the contour interval and a display range.
   *
   * Every value is worked out with + - * / and sqrt alone, written in the
   * order and grouping Python writes it, and every angle goes through
   * sinCosDeg, so that the two engines give the same bits; the wetness
   * index's one log is the only exception, and its display range is chosen
   * on the exact argument for that reason. A clamp writes the literal 0, so
   * no -0 appears and a NaN goes where the rule sends it. Grids are
   * south-first and row-major, as everywhere in the terrain engine (cell
   * i = r*cols + c, north is r + 1), and each row has its own cell size
   * (rowMetric). Everything is synchronous and touches no DOM, for the
   * worker and the Node sandboxes alike. */

  /* the class classifyCells gives a cell of land (0 is a void, 2 sea) */
  var SURFACE_LAND = 1;

  /* x - x is 0 for a finite number alone (NaN and the infinities give
   * NaN). Written out rather than as isFinite because a Node vm sandbox
   * looks a global up through its context at each use, which made these
   * loops some fifty times slower there; Math is fetched once a call for
   * the same reason. */
  function surfaceFinite(x) {
    return x - x === 0;
  }

  /* a grid that is not rows by cols is a caller's mistake, refused here
   * rather than read past its end as NaN */
  function surfaceShape(what, values, rows, cols) {
    if (!(Number.isInteger(rows) && Number.isInteger(cols) && rows >= 0 && cols >= 0) ||
        values.length !== rows * cols) {
      throw new Error(what + ' holds ' + values.length + ' values, not ' + rows + ' by ' + cols);
    }
  }

  /** The slope of the ground at each cell from its eight neighbours, by
   * Horn's (1981) weights: terrain_analysis.horn_gradients. `p` is the rise
   * per metre eastward, `q` the rise per metre northward and `tanb` the
   * tangent of the slope, sqrt(p*p + q*q), all on the heights as they are
   * (not filled), at the cell size of the cell's own row. A cell has them
   * only where it and all eight neighbours lie in the grid and have a
   * finite height, which is GDAL's rule for its edge; anywhere else they
   * are NaN, rather than a slope made up across a gap or beyond the edge,
   * which drew cliffs. A sea cell with a height counts as ground here;
   * assumed sea and voids have no height.
   * @param {Float64Array} zt the working heights in metres, south-first, NaN where there are none
   * @param {number} rows
   * @param {number} cols
   * @param {{dx: ArrayLike<number>, dy: ArrayLike<number>}} metric each row's cell size in metres (rowMetric)
   * @returns {{p: Float64Array, q: Float64Array, tanb: Float64Array}}
   */
  function hornGradients(zt, rows, cols, metric) {
    surfaceShape('the height grid', zt, rows, cols);
    surfaceRows('cell widths', metric.dx, rows);
    surfaceRows('cell heights', metric.dy, rows);
    var sqrt = Math.sqrt, n = rows * cols;
    var p = new Float64Array(n).fill(NaN), q = new Float64Array(n).fill(NaN);
    var tanb = new Float64Array(n).fill(NaN);
    for (var r = 1; r < rows - 1; r++) {
      var ex = 8.0 * metric.dx[r], ey = 8.0 * metric.dy[r];
      var south = (r - 1) * cols, here = r * cols, north = (r + 1) * cols;
      for (var c = 1; c < cols - 1; c++) {
        var zSW = zt[south + c - 1], zS = zt[south + c], zSE = zt[south + c + 1];
        var zW = zt[here + c - 1], zC = zt[here + c], zE = zt[here + c + 1];
        var zNW = zt[north + c - 1], zN = zt[north + c], zNE = zt[north + c + 1];
        if (!(surfaceFinite(zC) && surfaceFinite(zE) && surfaceFinite(zW) && surfaceFinite(zN) && surfaceFinite(zS) &&
              surfaceFinite(zNE) && surfaceFinite(zNW) && surfaceFinite(zSE) && surfaceFinite(zSW))) continue;
        var pc = (((zNE + 2.0 * zE) + zSE) - ((zNW + 2.0 * zW) + zSW)) / ex;
        var qc = (((zNW + 2.0 * zN) + zNE) - ((zSW + 2.0 * zS) + zSE)) / ey;
        p[here + c] = pc;
        q[here + c] = qc;
        tanb[here + c] = sqrt(pc * pc + qc * qc);
      }
    }
    return { p: p, q: q, tanb: tanb };
  }

  /* A metric gives each row its own value, once (rowMetric's arrays for
   * this grid). Both engines refuse one of any other length, which would be
   * read past its end as NaN or belong to another grid. */
  function surfaceRows(what, values, rows) {
    if (values.length !== rows) {
      throw new Error('the metric gives ' + values.length + ' ' + what + ', not one for each of ' + rows + ' rows');
    }
  }

  /* Both engines refuse a least slope that is not a finite positive
   * tangent (NaN included), in the wetness index and the curvatures alike:
   * 0 would divide by 0 on level ground, and an infinite floor would set
   * every wetness argument to 0. */
  function surfaceFloor(floorTan) {
    if (!(floorTan > 0 && floorTan < Infinity)) {
      throw new Error('the least slope must be a finite positive tangent, not ' + floorTan);
    }
  }

  /* p and q must be one grid's, cell for cell */
  function surfacePair(p, q) {
    if (p.length !== q.length) {
      throw new Error('the east slope holds ' + p.length + ' values and the north slope ' + q.length);
    }
  }

  /** Shaded relief under one sun, from 0 (turned away from it) to 1
   * (square to it): terrain_analysis.hillshade_layer, GDAL's Horn
   * hillshade, cos i = (sin alt - cos alt * (P sin az + Q cos az)) /
   * sqrt(1 + P*P + Q*Q) with P = p*zf and Q = q*zf, clamped at 0. A slope
   * facing the sun's azimuth is the brightest. NaN where `p` is NaN (the
   * edge, and beside a gap), never 0, which would draw a gap as shadow.
   * @param {Float64Array} p rise per metre eastward (hornGradients)
   * @param {Float64Array} q rise per metre northward (hornGradients)
   * @param {number} az the sun's azimuth, degrees clockwise from north
   * @param {number} alt the sun's altitude, degrees above the horizon
   * @param {number|null} [zf] the vertical exaggeration, 1 if left out or null
   * @returns {Float64Array}
   */
  function hillshadeLayer(p, q, az, alt, zf) {
    surfacePair(p, q);
    /* null means 1, as a value left out does and as None does in Python,
     * rather than multiplying as 0 */
    var sqrt = Math.sqrt, z = zf === undefined || zf === null ? 1.0 : zf;
    var sunZ = sinCosDeg(az), sZ = sunZ[0], cZ = sunZ[1];
    var sunA = sinCosDeg(alt), sA = sunA[0], cA = sunA[1];
    var out = new Float64Array(p.length).fill(NaN);
    for (var i = 0; i < p.length; i++) {
      var P = p[i] * z;
      if (P !== P) continue;
      var Q = q[i] * z;
      var g = (P * sZ) + (Q * cZ);
      var v = (sA - cA * g) / sqrt((1.0 + P * P) + Q * Q);
      out[i] = v > 0 ? v : 0;
    }
    return out;
  }

  /** Shaded relief lit from several azimuths at once, each sun weighted by
   * how squarely the slope faces across it:
   * terrain_analysis.multidirectional_hillshade. With the azimuths 225,
   * 270, 315 and 360 this is exactly `gdaldem hillshade -multidirectional`,
   * whose fixed weights (p sin az + q cos az)^2 sum to 2(p*p + q*q), so no
   * slope is left dark for facing away from one sun. Flat ground, where
   * every weight is 0, gets sin(alt), as GDAL gives it. The suns are summed
   * in the order given. NaN where `p` is NaN.
   * @param {Float64Array} p rise per metre eastward (hornGradients)
   * @param {Float64Array} q rise per metre northward (hornGradients)
   * @param {ArrayLike<number>} azimuths the suns' azimuths, degrees clockwise from north
   * @param {number} alt the suns' altitude, degrees above the horizon
   * @param {number|null} [zf] the vertical exaggeration, 1 if left out or null
   * @returns {Float64Array}
   */
  function multidirectionalHillshade(p, q, azimuths, alt, zf) {
    surfacePair(p, q);
    var sqrt = Math.sqrt, z = zf === undefined || zf === null ? 1.0 : zf;   // null means 1, as in hillshadeLayer
    var m = azimuths.length, sZ = new Float64Array(m), cZ = new Float64Array(m), k;
    for (k = 0; k < m; k++) {
      var sun = sinCosDeg(azimuths[k]);
      sZ[k] = sun[0];
      cZ[k] = sun[1];
    }
    var sunA = sinCosDeg(alt), sA = sunA[0], cA = sunA[1];
    var out = new Float64Array(p.length).fill(NaN);
    for (var i = 0; i < p.length; i++) {
      var P = p[i] * z;
      if (P !== P) continue;
      var Q = q[i] * z, num = 0.0, den = 0.0;
      for (k = 0; k < m; k++) {
        var g = (P * sZ[k]) + (Q * cZ[k]);
        var s = sA - cA * g;
        s = s > 0 ? s : 0;
        var w = g * g;
        num = num + w * s;
        den = den + w;
      }
      out[i] = den > 0 ? (num / den) / sqrt((1.0 + P * P) + Q * Q) : sA;
    }
    return out;
  }

  /** The topographic wetness index by single-neighbour (D8) routing:
   * terrain_analysis.wetness_index. On each land cell with a slope,
   * arg = a / tan(beta), where a is the specific catchment area in metres
   * (the drainage area over the mean of the row's two cell sides, the
   * width WhiteboxTools takes) and tan(beta) the local slope of the
   * unfilled surface, raised to `floorTan` where it is less, so that the
   * floor of an inland-valley swamp is shown rather than blanked; and
   * twi = log(arg). `arg` is exact in both engines and only the log may
   * differ in its last bit, which is why a display range is chosen on
   * `arg`. `floored` marks the cells whose slope was raised to the floor,
   * so that a summary can count them over any square. NaN on sea, on
   * voids and where `tanb` is NaN.
   * @param {Float64Array} areaUnits each cell's drainage area in 0.01 m^2 (accumulateFlow)
   * @param {Uint8Array} cls each cell's class (classifyCells): 0 void, 1 land, 2 sea
   * @param {Float64Array} tanb the slope's tangent (hornGradients)
   * @param {number} rows
   * @param {number} cols
   * @param {{dx: ArrayLike<number>, dy: ArrayLike<number>}} metric each row's cell size in metres (rowMetric)
   * @param {number} floorTan the least slope tangent used (terrain.flat_tan_slope), finite and above 0
   * @returns {{arg: Float64Array, twi: Float64Array, floored: Uint8Array}}
   */
  function wetnessIndex(areaUnits, cls, tanb, rows, cols, metric, floorTan) {
    surfaceShape('the drainage areas', areaUnits, rows, cols);
    surfaceShape('the cell classes', cls, rows, cols);
    surfaceShape('the slopes', tanb, rows, cols);
    surfaceRows('cell widths', metric.dx, rows);
    surfaceRows('cell heights', metric.dy, rows);
    surfaceFloor(floorTan);
    var log = Math.log, n = rows * cols;
    var arg = new Float64Array(n).fill(NaN), twi = new Float64Array(n).fill(NaN);
    var floored = new Uint8Array(n);
    for (var r = 0; r < rows; r++) {
      var width = (metric.dx[r] + metric.dy[r]) / 2.0;
      for (var i = r * cols; i < (r + 1) * cols; i++) {
        var t = tanb[i];
        if (cls[i] !== SURFACE_LAND || t !== t) continue;
        var a = (areaUnits[i] / 100.0) / width;
        var tb;
        if (t >= floorTan) {
          tb = t;
        } else {
          tb = floorTan;
          floored[i] = 1;
        }
        var x = a / tb;
        arg[i] = x;
        twi[i] = log(x);
      }
    }
    return { arg: arg, twi: twi, floored: floored };
  }

  /** Profile and tangential curvature by Evans and Young's quadratic,
   * fitted to samples `kCells` cells apart: terrain_analysis.curvatures.
   * kCells is `spacingM` over the mean cell side of the middle row,
   * rounded, and at least 1 (3 at 1 arc-second and 90 m, 1 at 3
   * arc-seconds), which brings the noise of a 3 by 3 window at 30 m below
   * the signal without smoothing passes, whose rim grows with each pass.
   * In 1/m, with Florinsky's and Minar's signs (a dome is + and +): profile
   * > 0 where flow speeds up over a convex slope, tangential < 0 where it
   * converges into a hollow. NaN on a cell that is not land, wherever a
   * sample lies outside the grid or has no height, and on ground flatter
   * than `floorTan`, where the slope has no direction.
   * @param {Float64Array} zt the working heights in metres, south-first, NaN where there are none
   * @param {Uint8Array} cls each cell's class (classifyCells): 0 void, 1 land, 2 sea
   * @param {number} rows
   * @param {number} cols
   * @param {{dx: ArrayLike<number>, dy: ArrayLike<number>}} metric each row's cell size in metres (rowMetric)
   * @param {number} spacingM the spacing to sample at, metres (terrain.curvature_spacing_m), finite and above 0
   * @param {number} floorTan the least slope tangent with a direction (terrain.flat_tan_slope), finite and above 0
   * @returns {{profile: Float64Array, tangential: Float64Array, kCells: number}}
   */
  function curvatures(zt, cls, rows, cols, metric, spacingM, floorTan) {
    surfaceShape('the height grid', zt, rows, cols);
    surfaceShape('the cell classes', cls, rows, cols);
    surfaceRows('cell widths', metric.dx, rows);
    surfaceRows('cell heights', metric.dy, rows);
    /* Both engines refuse, rather than fall back to k = 1: a spacing that is
     * not a finite positive number of metres, a grid with no middle row to
     * measure it on, and a spacing so many cells long that k is not finite. */
    if (!(spacingM > 0 && spacingM < Infinity)) {
      throw new Error('the curvature spacing must be a positive number of metres, not ' + spacingM);
    }
    if (!rows) throw new Error('a grid with no rows has no middle row to measure the curvature spacing on');
    var h = Math.floor(rows / 2), cells = spacingM / ((metric.dx[h] + metric.dy[h]) / 2.0) + 0.5;
    if (!surfaceFinite(cells)) {
      throw new Error('a curvature spacing of ' + spacingM + ' m is no finite number of cells');
    }
    surfaceFloor(floorTan);
    var k = Math.max(1, Math.floor(cells));
    var sqrt = Math.sqrt, n = rows * cols, flat = floorTan * floorTan;
    var profile = new Float64Array(n).fill(NaN), tangential = new Float64Array(n).fill(NaN);
    for (var r = k; r < rows - k; r++) {
      var X = k * metric.dx[r], Y = k * metric.dy[r];
      var sixX = 6.0 * X, sixY = 6.0 * Y, xx = (3.0 * X) * X, yy = (3.0 * Y) * Y, xy = (4.0 * X) * Y;
      var south = (r - k) * cols, here = r * cols, north = (r + k) * cols;
      for (var c = k; c < cols - k; c++) {
        if (cls[here + c] !== SURFACE_LAND) continue;
        var z1 = zt[north + c - k], z2 = zt[north + c], z3 = zt[north + c + k];
        var z4 = zt[here + c - k], z5 = zt[here + c], z6 = zt[here + c + k];
        var z7 = zt[south + c - k], z8 = zt[south + c], z9 = zt[south + c + k];
        if (!(surfaceFinite(z1) && surfaceFinite(z2) && surfaceFinite(z3) && surfaceFinite(z4) && surfaceFinite(z5) &&
              surfaceFinite(z6) && surfaceFinite(z7) && surfaceFinite(z8) && surfaceFinite(z9))) continue;
        var p = (((((z3 + z6) + z9) - z1) - z4) - z7) / sixX;
        var q = (((((z1 + z2) + z3) - z7) - z8) - z9) / sixY;
        var rr = ((((((z1 + z3) + z4) + z6) + z7) + z9) - 2.0 * ((z2 + z5) + z8)) / xx;
        var t = ((((((z1 + z2) + z3) + z7) + z8) + z9) - 2.0 * ((z4 + z5) + z6)) / yy;
        var s = (((z3 + z7) - z1) - z9) / xy;
        var g2 = p * p + q * q;
        if (!(g2 >= flat)) continue;
        var w = 1.0 + g2;
        profile[here + c] = -(((p * p) * rr + ((2.0 * p) * q) * s) + (q * q) * t) / (g2 * (w * sqrt(w)));
        tangential[here + c] = -(((q * q) * rr - ((2.0 * p) * q) * s) + (p * p) * t) / (g2 * sqrt(w));
      }
    }
    return { profile: profile, tangential: tangential, kCells: k };
  }

  /** A round contour interval giving about a dozen lines over `relief`
   * metres: terrain_analysis.contour_interval. The largest of 1, 2, 5, 10,
   * 20, 50, ... metres that is no more than (relief/12)*2, and never less
   * than 1; 10 where there is no relief, or none that is finite. The steps
   * are whole numbers made by multiplying whole numbers (BigInt, as
   * Python's int) and each is compared with the limit exactly, as Python
   * compares an int with a float, so the two engines agree at every knife
   * edge, where log10, as the interval was once chosen, can round across a
   * power of ten, and where a double would round a step past 10^22.
   * @param {number} relief the highest finite height less the lowest, metres
   * @returns {number}
   */
  function contourInterval(relief) {
    if (!isFinite(relief) || relief <= 0) return 10.0;
    var limit = (relief / 12.0) * 2.0;
    /* the rule in both engines: exact integer candidates (BigInt here, int
     * in Python), each compared exactly with the double limit, and the
     * answer the double nearest the one chosen */
    var steps = [BigInt(1), BigInt(2), BigInt(5)], ten = BigInt(10);
    var best = BigInt(1), decade = BigInt(1);
    for (;;) {
      for (var m = 0; m < 3; m++) {
        var v = steps[m] * decade;
        if (!(v <= limit)) return Number(best);
        best = v;
      }
      decade = decade * ten;
    }
  }

  /** The `lo` and `hi` fractions of the finite values, by rank:
   * terrain_analysis.display_range. The finite values are sorted ascending
   * and the elements at floor(lo*(n-1)) and floor(hi*(n-1)) are taken as
   * they are, never interpolated, so the two engines choose the same
   * element whatever the values; NaN and the infinities are left out. A
   * zero comes back as +0, because -0 and +0 sort as equals and which of
   * them lands at the index is not fixed. [NaN, NaN] when no value is
   * finite.
   * @param {ArrayLike<number>} values
   * @param {number} lo a fraction from 0 to `hi`
   * @param {number} hi a fraction from `lo` to 1
   * @returns {[number, number]}
   */
  function displayRange(values, lo, hi) {
    /* Both engines refuse fractions out of order or outside 0..1 (NaN
     * included) rather than hand back a range upside down. */
    if (!(lo >= 0 && lo <= hi && hi <= 1)) {
      throw new Error('a display range needs 0 <= lo <= hi <= 1, not ' + lo + ' and ' + hi);
    }
    var n = 0, i;
    for (i = 0; i < values.length; i++) if (typeof values[i] === 'number' && surfaceFinite(values[i])) n++;
    if (!n) return [NaN, NaN];
    var finite = new Float64Array(n);
    n = 0;
    for (i = 0; i < values.length; i++) {
      if (typeof values[i] === 'number' && surfaceFinite(values[i])) finite[n++] = values[i];
    }
    finite.sort();
    /* a zero comes back as +0 in both engines: + 0.0 on the two elements
     * chosen here, on every value before the choice in Python */
    return [finite[Math.floor(lo * (n - 1))] + 0.0, finite[Math.floor(hi * (n - 1))] + 0.0];
  }

  Object.assign(C, {
    hornGradients: hornGradients, hillshadeLayer: hillshadeLayer,
    multidirectionalHillshade: multidirectionalHillshade, wetnessIndex: wetnessIndex, curvatures: curvatures,
    contourInterval: contourInterval, displayRange: displayRange,
  });

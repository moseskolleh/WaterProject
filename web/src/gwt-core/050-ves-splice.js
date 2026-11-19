
  /* ======================================================= sounding segments
   * groundwater/ves/splice.py. At MN segment changes the same AB/2 is read
   * with the old and the new MN and the two differ slightly. Both readings are
   * kept in the raw data; "merge" keeps every segment at its measured level
   * and merges duplicate AB/2 by geometric mean, which honours the absolute
   * values of the deep branch that drive the aquifer interpretation.
   */

  /** A new segment starts at each change of MN. A blank MN continues the
   * current segment rather than starting one, so a single missing cell does
   * not inject a spurious one-point segment and an absent MN column does not
   * split every reading into its own.
   * @param {Sounding} sounding
   * @returns {number[][]}
   */
  function soundingSegments(sounding) {
    /** @type {number[][]} */
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

  /**
   * @param {Sounding} sounding
   * @param {string} [mode] 'merge', 'first' or 'last'
   */
  function spliceSegments(sounding, mode) {
    var m = mode || 'merge';
    var segments = soundingSegments(sounding);
    var i;
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

    /* Merge duplicates by geometric mean, over the readings that can be: a
     * zero or blank at an overlap made the mean 0 or NaN, and the inversion
     * then dropped the spacing with the good reading beside it. A spacing with
     * no usable reading stays NaN, which the inversion leaves out. */
    var unique = ab2All.slice().sort(function (a, b) { return a - b; })
      .filter(function (v, k, a) { return k === 0 || v !== a[k - 1]; });
    var merged = unique.map(function (u) {
      var logs = [];
      for (var k = 0; k < ab2All.length; k++) {
        if (ab2All[k] === u && isFinite(rhoAll[k]) && rhoAll[k] > 0) {
          logs.push(Math.log(rhoAll[k]));
        }
      }
      return logs.length ? Math.exp(arrMean(logs)) : NaN;
    });
    return { ab2: unique, rho: merged, shifts: shifts };
  }

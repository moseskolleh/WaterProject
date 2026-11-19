
  /* =========================================================== survey plan
   * groundwater/mapping/survey.py (PLAN.md step 4.3): profiling lines
   * across the lineament candidates nearest the site, at right angles to
   * them, and the soundings proposed on them, kept the separation distances
   * from what the page maps. The same steps in the same order, from
   * additions, multiplications, divisions, square roots, floors and ceilings
   * and the polynomial sine and cosine, so that the two engines lay the same
   * plan to the bit. The Python module says what each rule is for; the
   * plan's fields keep its names. */

  var SP_BOREHOLE = 'Water supply borehole', SP_DUG_WELL = 'Hand dug well',
    SP_OTHER_WELL = 'Other existing water wells', SP_STREAM = 'Streams and canals and irrigation ditches',
    SP_COAST = 'Coastline';
  var SP_MAPPED = [SP_BOREHOLE, SP_DUG_WELL, SP_OTHER_WELL, SP_STREAM, SP_COAST];
  /** @type {Record<string, string>} */
  var SP_KIND_STRUCTURE = { borehole: SP_BOREHOLE, dug_well: SP_DUG_WELL, other: SP_OTHER_WELL, surface: SP_STREAM };
  /** @type {Record<string, string>} */
  var SP_CLEARED = {};
  SP_CLEARED[SP_BOREHOLE] = 'survey_plan.cleared_borehole';
  SP_CLEARED[SP_DUG_WELL] = 'survey_plan.cleared_dug_well';
  SP_CLEARED[SP_OTHER_WELL] = 'survey_plan.cleared_other';
  SP_CLEARED[SP_STREAM] = 'survey_plan.cleared_stream';
  SP_CLEARED[SP_COAST] = 'survey_plan.cleared_coast';
  var SP_RING_SEGMENTS = 64, SP_OFF_LINE = 'off_line';

  /** What a water point is, for its separation distance: survey.water_point_kind.
   * @param {Rec} point @returns {string} */
  function waterPointKind(point) {
    var text = (String(point.source) + ' ' + String(point.technology)).toLowerCase();
    if (text.indexOf('borehole') >= 0 || text.indexOf('tubewell') >= 0 || text.indexOf('tube well') >= 0) {
      return 'borehole';
    }
    if (text.indexOf('well') >= 0) return 'dug_well';
    if (text.indexOf('surface') >= 0 || text.indexOf('river') >= 0 || text.indexOf('stream') >= 0 ||
      text.indexOf('lake') >= 0 || text.indexOf('pond') >= 0) return 'surface';
    return 'other';
  }

  /** @param {string} name @param {any} value @returns {number} */
  function spPositive(name, value) {
    var v = Number(value);
    if (!(isFinite(v) && v > 0)) throw new Error('terrain.' + name + ' must be a number above 0');
    return v;
  }

  /** The plan's settings, refused in survey._plan_settings's order and words.
   * @param {Rec} cfg the configuration's terrain section @returns {Rec} */
  function spSettings(cfg) {
    var lines = Number(cfg.survey_lines);
    if (!(isFinite(lines) && lines === Math.floor(lines) && lines >= 1)) {
      throw new Error('terrain.survey_lines must be a whole number of 1 or more');
    }
    /** @type {Rec} */
    var out = { survey_lines: lines };
    ['survey_line_m', 'survey_station_m', 'survey_flank_m', 'survey_target_depth_m'].forEach(function (name) {
      out[name] = spPositive(name, cfg[name]);
    });
    var move = Number(cfg.survey_move_m);
    if (!(isFinite(move) && move >= 0 && move < out.survey_flank_m / 2)) {
      throw new Error('terrain.survey_move_m must be 0 or more and under half of terrain.survey_flank_m');
    }
    out.survey_move_m = move;
    var within = Number(cfg.survey_cross_within_deg);
    if (!(isFinite(within) && within >= 0 && within < 90)) {
      throw new Error('terrain.survey_cross_within_deg must be 0 or more and under 90 degrees');
    }
    out.survey_cross_within_deg = within;
    if (out.survey_station_m > out.survey_line_m) {
      throw new Error('terrain.survey_station_m must be no longer than terrain.survey_line_m');
    }
    return out;
  }

  /* where a value lies along cell centres, as a fractional index: the
   * inverse of lineamentLonLat's reading between two centres */
  /** @param {ArrayLike<number>} axis @param {number} value */
  function spAxisPlace(axis, value) {
    var first = axis[0];
    var i = Math.floor((value - first) / (axis[1] - first));
    i = Math.min(Math.max(i, 0), axis.length - 2);
    var lo = axis[i];
    return i + (value - lo) / (axis[i + 1] - lo);
  }

  /** @param {ArrayLike<number>} lons @param {ArrayLike<number>} lats @param {number[]} frame
   * @param {number} lon @param {number} lat @returns {number[]} */
  function spToFrame(lons, lats, frame, lon, lat) {
    return [spAxisPlace(lons, Number(lon)) * frame[0], spAxisPlace(lats, Number(lat)) * frame[1]];
  }

  /** @param {number} ax @param {number} ay @param {number} bx @param {number} by */
  function spDistance(ax, ay, bx, by) {
    var ex = ax - bx, ey = ay - by;
    return Math.sqrt(ex * ex + ey * ey);
  }

  /* the distance from (px, py) to the segment a-b, and its point nearest it */
  /** @param {number} px @param {number} py @param {number[]} a @param {number[]} b @returns {number[]} */
  function spNearestOn(px, py, a, b) {
    var ex = b[0] - a[0], ey = b[1] - a[1];
    var span = ex * ex + ey * ey;
    var t = span > 0 ? ((px - a[0]) * ex + (py - a[1]) * ey) / span : 0;
    t = t < 0 ? 0 : t > 1 ? 1 : t;
    var cx = a[0] + t * ex, cy = a[1] + t * ey;
    return [spDistance(px, py, cx, cy), cx, cy];
  }

  /* the open span of t along a line, origin (ox, oy) and direction (nx, ny),
   * nearer than d to a point, a segment's strip, or a segment */
  /** @returns {number[]|null} */
  function spDiscSpan(/** @type {number} */ ox, /** @type {number} */ oy, /** @type {number} */ nx,
    /** @type {number} */ ny, /** @type {number} */ qx, /** @type {number} */ qy, /** @type {number} */ d) {
    var wx = ox - qx, wy = oy - qy;
    var b = wx * nx + wy * ny;
    var c = (wx * wx + wy * wy) - d * d;
    var disc = b * b - c;
    if (!(disc > 0)) return null;
    var root = Math.sqrt(disc);
    return [-b - root, -b + root];
  }

  /** @param {number} v0 @param {number} v1 @param {number} lo @param {number} hi @returns {number[]|null} */
  function spBetween(v0, v1, lo, hi) {
    if (v1 === 0) return lo < v0 && v0 < hi ? [-Infinity, Infinity] : null;
    var ta = (lo - v0) / v1, tb = (hi - v0) / v1;
    if (ta > tb) {
      var swap = ta;
      ta = tb;
      tb = swap;
    }
    return ta < tb ? [ta, tb] : null;
  }

  /** @returns {number[]|null} */
  function spCapsuleSpan(/** @type {number} */ ox, /** @type {number} */ oy, /** @type {number} */ nx,
    /** @type {number} */ ny, /** @type {number} */ ax, /** @type {number} */ ay, /** @type {number} */ bx,
    /** @type {number} */ by, /** @type {number} */ d) {
    var spans = [spDiscSpan(ox, oy, nx, ny, ax, ay, d), spDiscSpan(ox, oy, nx, ny, bx, by, d)].filter(function (s) {
      return s !== null;
    });
    var ex = bx - ax, ey = by - ay;
    var length = Math.sqrt(ex * ex + ey * ey);
    if (length > 0) {
      var ux = ex / length, uy = ey / length, px = ox - ax, py = oy - ay;
      var along = spBetween(px * ux + py * uy, nx * ux + ny * uy, 0, length);
      var across = spBetween(px * uy - py * ux, nx * uy - ny * ux, -d, d);
      if (along !== null && across !== null) {
        var lo = along[0] > across[0] ? along[0] : across[0];
        var hi = along[1] < across[1] ? along[1] : across[1];
        if (lo < hi) spans.push([lo, hi]);
      }
    }
    if (!spans.length) return null;
    var out = [spans[0][0], spans[0][1]];
    for (var k = 1; k < spans.length; k++) {
      if (spans[k][0] < out[0]) out[0] = spans[k][0];
      if (spans[k][1] > out[1]) out[1] = spans[k][1];
    }
    return out;
  }

  /** @param {any[]} zone @param {number} ox @param {number} oy @param {number} nx @param {number} ny */
  function spZoneSpan(zone, ox, oy, nx, ny) {
    if (zone[0] === 'disc') return spDiscSpan(ox, oy, nx, ny, zone[2], zone[3], zone[4]);
    return spCapsuleSpan(ox, oy, nx, ny, zone[2], zone[3], zone[4], zone[5], zone[6]);
  }

  /** @param {any[][]} spans [lo, hi, structure] @returns {number[][]} */
  function spMerged(spans) {
    /** @type {number[][]} */
    var out = [];
    spans.slice().sort(function (a, b) { return (a[0] - b[0]) || (a[1] - b[1]); }).forEach(function (s) {
      var last = out[out.length - 1];
      if (last && s[0] < last[1]) {
        if (s[1] > last[1]) last[1] = s[1];
      } else {
        out.push([s[0], s[1]]);
      }
    });
    return out;
  }

  /** @param {any[][]} spans @returns {string[]} */
  function spStructures(spans) {
    return SP_MAPPED.filter(function (name) {
      return spans.some(function (s) { return s[2] === name; });
    });
  }

  /* where along p0-p1, as a share of it, the segment a-b crosses it */
  /** @param {number[]} p0 @param {number[]} p1 @param {number[]} a @param {number[]} b @returns {number|null} */
  function spCrossing(p0, p1, a, b) {
    var rx = p1[0] - p0[0], ry = p1[1] - p0[1];
    var qx = b[0] - a[0], qy = b[1] - a[1];
    var den = rx * qy - ry * qx;
    if (den === 0) return null;
    var wx = a[0] - p0[0], wy = a[1] - p0[1];
    var t = (wx * qy - wy * qx) / den;
    var u = (wx * ry - wy * rx) / den;
    return t >= 0 && t <= 1 && u >= 0 && u <= 1 ? t : null;
  }

  /** Station k of a line, in the candidates' frame: survey.line_station.
   * @param {Rec} line @param {number} k @returns {number[]} */
  function lineStation(line, k) {
    var along = k * line.station_m;
    return [line.origin[0] + along * line.direction[0], line.origin[1] + along * line.direction[1]];
  }

  /* a line at right angles to strike through origin, or null where the
   * service radius leaves no room for two stations */
  /** @returns {Rec|null} */
  function spLay(/** @type {number} */ number, /** @type {Rec|null} */ item, /** @type {number[]} */ origin,
    /** @type {number} */ strike, /** @type {number[]} */ site, /** @type {number} */ radius, /** @type {Rec} */ s,
    /** @type {Rec} */ lineaments) {
    var station = s.survey_station_m;
    var bearing = strike < 90 ? strike + 90 : strike - 90;
    var n = sinCosDeg(bearing);
    var wx = origin[0] - site[0], wy = origin[1] - site[1];
    var b = wx * n[0] + wy * n[1];
    var c = (wx * wx + wy * wy) - radius * radius;
    var disc = b * b - c;
    var root = disc > 0 ? Math.sqrt(disc) : 0;
    /* + 0 makes a -0 of ceil or floor a 0, as Python's int is */
    var k1 = Math.ceil((-b - root) / station) + 0, k2 = Math.floor((-b + root) / station) + 0;
    var wanted = Math.floor(s.survey_line_m / station);
    var m = Math.min(wanted, k2 - k1);
    if (m < 1) return null;
    var first = 0 - Math.floor(m / 2);
    if (first < k1) first = k1;
    if (first + m > k2) first = k2 - m;
    var last = first + m, length = m * station;
    var line = {
      id: number, candidate: item ? item.id : null, kind: item ? item.kind : null, strike_deg: strike,
      bearing_deg: bearing, origin: origin, direction: [n[0], n[1]], first: first, last: last, station_m: station,
      length_m: length, crossing_m: (0 - first) * station, crosses: /** @type {number[][]} */ ([]), shortened: m < wanted,
    };
    var start = lineStation(line, first), end = lineStation(line, last);
    lineaments.lineaments.forEach(function (/** @type {Rec} */ other) {
      if (item && other.id === item.id) return;
      var turn = Math.abs(other.strike_deg - strike);
      if (180 - turn < turn) turn = 180 - turn;
      if (turn > s.survey_cross_within_deg) return;
      var t = spCrossing(start, end, other.start, other.end);
      if (t !== null) line.crosses.push([other.id, t * length]);
    });
    return line;
  }

  /* the three soundings of a line across a candidate: [role, t, moved,
   * cleared] each, t along the line from its origin, and those left out */
  /** @param {Rec} line @param {any[][]} zones @param {Rec} s */
  function spSoundings(line, zones, s) {
    var flank = s.survey_flank_m, move = s.survey_move_m;
    var ox = line.origin[0], oy = line.origin[1], nx = line.direction[0], ny = line.direction[1];
    var tStart = line.first * line.station_m, tEnd = line.last * line.station_m;
    /** @type {any[][]} */
    var spans = [];
    zones.forEach(function (zone) {
      var span = spZoneSpan(zone, ox, oy, nx, ny);
      if (span !== null) spans.push([span[0], span[1], zone[1]]);
    });
    var merged = spMerged(spans);
    /** @type {any[][]} */
    var kept = [];
    /** @type {Rec[]} */
    var dropped = [];
    [['flank', 0 - flank], ['crossing', 0], ['flank', flank]].forEach(function (entry) {
      var role = /** @type {string} */ (entry[0]), t0 = /** @type {number} */ (entry[1]);
      if (t0 < tStart || t0 > tEnd) {
        dropped.push({ line: line.id, role: role, at_m: t0 - tStart, reasons: [SP_OFF_LINE] });
        return;
      }
      var inside = spans.filter(function (span) { return span[0] < t0 && t0 < span[1]; });
      var t = t0;
      if (inside.length) {
        var hit = merged.filter(function (span) { return span[0] < t0 && t0 < span[1]; })[0];
        /** @type {number[]} */
        var options = [];
        if (hit[0] >= t0 - move && hit[0] >= tStart) options.push(hit[0]);
        if (hit[1] <= t0 + move && hit[1] <= tEnd) options.push(hit[1]);
        if (!options.length) {
          dropped.push({ line: line.id, role: role, at_m: t0 - tStart, reasons: spStructures(inside) });
          return;
        }
        t = options.length === 1 || t0 - options[0] <= options[1] - t0 ? options[0] : options[1];
      }
      kept.push([role, t, t - t0, spStructures(inside)]);
    });
    return { kept: kept, dropped: dropped };
  }

  /** The survey plan round site, [lon, lat], from the lineament candidates
   * of an analysed window: survey.survey_plan.
   * @param {Rec} lineaments what lineamentCandidates gives
   * @param {Rec} core the analysis's core: its classes, axes and square shown
   * @param {Rec[]} parts the drainage lines shown, as drainageLinks gives them
   * @param {number[]} site [lon, lat]
   * @param {Rec[]|null} [waterPoints] as parseWpdxRecords gives them
   * @param {Rec} [cfg] the configuration's terrain section, the candidates' own by default
   * @param {Rec} [ves] its VES section, which the AB/2 series is planned by
   * @param {Rec[]} [distances] the separation table, the bundled one by default
   * @param {number|null} [searchedM] how far round the site the water points were looked up: a
   *   lookup's radius, less how far the site lies from where it was centred; null where they are
   *   not cut to a circle round the site (an export read whole, the national set)
   * @returns {Rec} */
  function surveyPlan(lineaments, core, parts, site, waterPoints, cfg, ves, distances, searchedM) {
    var settings = cfg || lineaments.settings;
    var s = spSettings(settings);
    var searched = searchedM === undefined || searchedM === null ? null : Number(searchedM);
    if (searched !== null && !(isFinite(searched) && searched >= 0)) {
      throw new Error('the radius the water points were looked up within must be 0 m or more');
    }
    var rows = loadSeparationDistances(distances);
    /** @type {Record<string, number>} */
    var table = {};
    rows.forEach(function (row) { table[row.structure] = Number(row.min_distance_m); });
    var radius = SERVICE_RADIUS_M;
    var frame = [Number(lineaments.frame[0]), Number(lineaments.frame[1])];
    var dx = frame[0], dy = frame[1];
    var lons = core.lons, lats = core.lats;
    var at = spToFrame(lons, lats, frame, site[0], site[1]), sx = at[0], sy = at[1];
    var has = function (/** @type {string} */ name) { return Object.prototype.hasOwnProperty.call(table, name); };

    /** @type {any[][]} */
    var zones = [];
    /** @type {Record<string, number>} */
    var reach = { borehole: 0, dug_well: 0, other: 0, surface: 0, streams: 0, sea: 0 };
    /** @type {any[][]} */
    var rings = [];
    var given = 0;
    (waterPoints || []).forEach(function (point) {
      given += 1;
      var kind = waterPointKind(point), structure = SP_KIND_STRUCTURE[kind];
      if (!has(structure)) return;
      var d = table[structure];
      var q = spToFrame(lons, lats, frame, point.lon, point.lat);
      if (spDistance(q[0], q[1], sx, sy) > radius + d) return;
      zones.push(['disc', structure, q[0], q[1], d]);
      rings.push([q[0], q[1], structure, d]);
      reach[kind] += 1;
    });
    var d, v;
    if (has(SP_STREAM)) {
      d = table[SP_STREAM];
      (parts || []).forEach(function (part) {
        var vertices = part.vertices;
        for (v = 0; v < vertices.length - 1; v++) {
          var a = [vertices[v][1] * dx, vertices[v][0] * dy];
          var b = [vertices[v + 1][1] * dx, vertices[v + 1][0] * dy];
          if (spNearestOn(sx, sy, a, b)[0] > radius + d) continue;
          zones.push(['capsule', SP_STREAM, a[0], a[1], b[0], b[1], d]);
          reach.streams += 1;
        }
      });
    }
    if (has(SP_COAST)) {
      d = table[SP_COAST];
      var cls = core.cls, nRows = core.rows, nCols = core.cols;
      var rLo = Math.max(0, Math.floor((sy - (radius + d)) / dy));
      var rHi = Math.min(nRows - 1, Math.ceil((sy + (radius + d)) / dy));
      var cLo = Math.max(0, Math.floor((sx - (radius + d)) / dx));
      var cHi = Math.min(nCols - 1, Math.ceil((sx + (radius + d)) / dx));
      for (var r = rLo; r <= rHi; r++) {
        for (var c = cLo; c <= cHi; c++) {
          var k = r * nCols + c;
          if (cls[k] !== 2) continue;
          if (!(r === 0 || c === 0 || r === nRows - 1 || c === nCols - 1 || cls[k - nCols] !== 2 ||
            cls[k + nCols] !== 2 || cls[k - 1] !== 2 || cls[k + 1] !== 2)) continue;
          var qx = c * dx, qy = r * dy;
          if (spDistance(qx, qy, sx, sy) > radius + d) continue;
          zones.push(['disc', SP_COAST, qx, qy, d]);
          reach.sea += 1;
        }
      }
    }

    /** @type {any[][]} */
    var near = [];
    lineaments.lineaments.forEach(function (/** @type {Rec} */ item) {
      var hit = spNearestOn(sx, sy, item.start, item.end);
      if (hit[0] <= radius) near.push([hit[0], item, [hit[1], hit[2]]]);
    });
    near.sort(function (a, b) { return (a[0] - b[0]) || (b[1].length_m - a[1].length_m) || (a[1].id - b[1].id); });
    /** @type {Rec[]} */
    var lines = [];
    /** @type {number[][]} */
    var skipped = [];
    for (var e = 0; e < near.length; e++) {
      if (lines.length >= s.survey_lines) break;
      var item = near[e][1];
      var by = lines.filter(function (line) {
        return line.crosses.some(function (/** @type {number[]} */ cr) { return cr[0] === item.id; });
      })[0];
      if (by) {
        skipped.push([item.id, by.id]);
        continue;
      }
      var laid = spLay(lines.length + 1, item, near[e][2], item.strike_deg, [sx, sy], radius, s, lineaments);
      if (laid === null) {
        skipped.push([item.id, 0]);
        continue;
      }
      lines.push(laid);
    }
    var basis = lines.length ? 'candidates' : 'none';
    if (!lines.length && lineaments.lineaments.length) {
      var band = 0, totals = [];
      for (v = 0; v < LIN_ROSE_BANDS; v++) totals.push(lineaments.roseValleyM[v] + lineaments.roseRidgeM[v]);
      for (v = 1; v < LIN_ROSE_BANDS; v++) if (totals[v] > totals[band]) band = v;
      var across = spLay(1, null, [sx, sy], band * 10 + 5, [sx, sy], radius, s, lineaments);
      if (across !== null) {
        lines.push(across);
        basis = 'strike';
      }
    }

    /** @type {Rec[]} */
    var soundings = [];
    /** @type {Rec[]} */
    var dropped = [];
    if (basis === 'candidates') {
      lines.forEach(function (line) {
        var found = spSoundings(line, zones, s), tStart = line.first * line.station_m;
        found.kept.forEach(function (x) {
          var t = x[1];
          soundings.push({
            id: soundings.length + 1, line: line.id, role: x[0], at_m: t - tStart,
            point: [line.origin[0] + t * line.direction[0], line.origin[1] + t * line.direction[1]],
            moved_m: x[2], cleared: x[3], spread_deg: line.strike_deg,
          });
        });
        found.dropped.forEach(function (/** @type {Rec} */ lost) { dropped.push(lost); });
      });
    }

    var shown = core.shown;
    var covered = sx - radius >= (shown[2] - 0.5) * dx && sx + radius <= (shown[3] - 0.5) * dx &&
      sy - radius >= (shown[0] - 0.5) * dy && sy + radius <= (shown[1] - 0.5) * dy;
    /** @type {any[][]} */
    var unmapped = [];
    rows.forEach(function (row) {
      if (SP_MAPPED.indexOf(row.structure) < 0 && unmapped.every(function (u) { return u[0] !== row.structure; })) {
        unmapped.push([row.structure, Number(row.min_distance_m)]);
      }
    });
    /** @type {Record<string, number>} */
    var mapped = {};
    SP_MAPPED.forEach(function (name) { if (has(name)) mapped[name] = table[name]; });
    return {
      site: [sx, sy], site_lonlat: [Number(site[0]), Number(site[1])], radius_m: radius, basis: basis,
      lines: lines, soundings: soundings, dropped: dropped,
      near: near.map(function (entry) { return entry[1].id; }), skipped: skipped, reach: reach, rings: rings,
      water_points: given, distances: mapped, unmapped: unmapped,
      ab2: vesSurveyPlan(s.survey_target_depth_m, { ves: ves || defaultConfig().ves }),
      covered: covered, frame: frame, settings: settings, searched_m: searched,
    };
  }

  /** How far from the site a mapped water point's separation ring can
   * reach a sounding: the service radius and the table's largest distance
   * from a water point, or null where the table keeps none
   * (survey.water_point_reach).
   * @param {Rec} plan what surveyPlan gives
   * @returns {number|null} */
  function waterPointReach(plan) {
    var structures = [SP_BOREHOLE, SP_DUG_WELL, SP_OTHER_WELL, SP_STREAM];
    var reach = -1;
    for (var i = 0; i < structures.length; i++) {
      if (!Object.prototype.hasOwnProperty.call(plan.distances, structures[i])) continue;
      var d = Number(plan.distances[structures[i]]);
      if (reach < 0 || d > reach) reach = d;
    }
    return reach < 0 ? null : Number(plan.radius_m) + reach;
  }

  /* how far the water points were looked up, to the millimetre, and the
   * reach they fell short of, or null where they did not: survey._short_of.
   * To the millimetre, so that a lookup a site's round trip through UTM has
   * put a hair inside its radius is neither short of a reach it met nor
   * said to stop at the metre below. */
  /** @param {Rec} plan @returns {number[]|null} */
  function spShortOf(plan) {
    var reach = waterPointReach(plan);
    if (plan.searched_m === null || plan.searched_m === undefined || reach === null) return null;
    var searched = Math.floor(Number(plan.searched_m) * 1000 + 0.5) / 1000;
    return searched >= reach ? null : [searched, reach];
  }

  /** @param {string} text */
  function spLowerFirst(text) {
    return text.slice(0, 1).toLowerCase() + text.slice(1);
  }

  /** @param {Rec} plan */
  function spKept(plan) {
    /** @type {string[]} */
    var pieces = [];
    [['borehole', 'survey_plan.kept_borehole', SP_BOREHOLE], ['dug_well', 'survey_plan.kept_dug_well', SP_DUG_WELL],
      ['other', 'survey_plan.kept_other', SP_OTHER_WELL], ['surface', 'survey_plan.kept_surface', SP_STREAM]]
      .forEach(function (entry) {
        if (plan.reach[entry[0]]) {
          pieces.push(phrase(entry[1], { distance: plan.distances[entry[2]], count: plan.reach[entry[0]] }));
        }
      });
    if (plan.reach.streams) pieces.push(phrase('survey_plan.kept_streams', { distance: plan.distances[SP_STREAM] }));
    if (plan.reach.sea) pieces.push(phrase('survey_plan.kept_coast', { distance: plan.distances[SP_COAST] }));
    if (!pieces.length) {
      return phrase(spShortOf(plan) !== null ? 'survey_plan.kept_nothing_loaded' : 'survey_plan.kept_nothing');
    }
    return phrase('survey_plan.kept', { kept: andJoin(pieces) });
  }

  /** The plan figure's title, its caption and the note drawn inside it, or
   * for no plan (a site with no GPS fix) the caption alone, saying why:
   * survey.survey_plan_captions.
   * @param {Rec|null} plan what surveyPlan gives @param {string} where
   * @returns {Record<string, string>} */
  function surveyPlanCaptions(plan, where) {
    if (!plan) return { plan: phrase('survey_plan.needs_site', { radius: SERVICE_RADIUS_M }) };
    var s = spSettings(plan.settings), radius = plan.radius_m;
    /** @type {string[]} */
    var parts = [];
    if (plan.basis === 'candidates') {
      parts.push(phrase('survey_plan.lines_candidates', { lines: plan.lines.length, radius: radius,
        length: s.survey_line_m, station: s.survey_station_m }));
      parts.push(phrase('survey_plan.near', { count: plan.near.length }));
      var crossed = plan.skipped.filter(function (/** @type {number[]} */ e) { return e[1] > 0; }).length;
      if (crossed) parts.push(phrase('survey_plan.crossed', { count: crossed }));
      var ab2 = plan.ab2;
      parts.push(phrase('survey_plan.soundings', { count: plan.soundings.length, flank: s.survey_flank_m,
        ab2: Number(ab2.max_ab2), depth: Number(ab2.investigation_m), target: Number(ab2.target_m),
        spread: Number(ab2.line_m) }));
      if (ab2.capped) {
        parts.push(phrase('survey_plan.capped', { ab2: Number(ab2.max_ab2), depth: Number(ab2.investigation_m),
          target: Number(ab2.target_m) }));
      }
      var moved = plan.soundings.filter(function (/** @type {Rec} */ x) { return x.moved_m !== 0; })
        .map(function (/** @type {Rec} */ x) { return Math.abs(x.moved_m); });
      if (moved.length) {
        var most = moved[0];
        for (var k = 1; k < moved.length; k++) if (moved[k] > most) most = moved[k];
        parts.push(phrase('survey_plan.moved', { count: moved.length, most: most }));
      }
      var offLine = function (/** @type {Rec} */ d) { return d.reasons.length === 1 && d.reasons[0] === SP_OFF_LINE; };
      var rings = plan.dropped.filter(function (/** @type {Rec} */ d) { return !offLine(d); }).length;
      if (rings) parts.push(phrase('survey_plan.dropped_rings', { count: rings, move: s.survey_move_m }));
      var short = plan.dropped.filter(offLine).length;
      if (short) parts.push(phrase('survey_plan.dropped_short', { count: short }));
      parts.push(spKept(plan));
      var fell = spShortOf(plan);
      if (fell !== null) {
        /* the whole metres it reached, so that 549.6 m is not printed as the
         * 550 m it fell short of */
        parts.push(phrase('survey_plan.water_points_short', { searched: Math.floor(fell[0]), reach: fell[1] }));
      } else if (plan.water_points === 0 && (plan.searched_m === null || plan.searched_m === undefined)) {
        parts.push(phrase('survey_plan.no_water_points'));
      }
    } else if (plan.basis === 'strike') {
      var line = plan.lines[0];
      parts.push(phrase('survey_plan.lines_strike', { radius: radius, strike: line.strike_deg, length: line.length_m,
        station: line.station_m }));
    } else {
      parts.push(phrase('survey_plan.lines_none'));
    }
    if (plan.basis !== 'none' && plan.unmapped.length) {
      parts.push(phrase('survey_plan.unmapped', { structures: andJoin(plan.unmapped.map(function (/** @type {any[]} */ u) {
        return phrase('survey_plan.unmapped_item', { structure: spLowerFirst(u[0]), distance: u[1] });
      })) }));
    }
    if (!plan.covered) parts.push(phrase('survey_plan.uncovered'));
    return {
      title_plan: phrase('survey_plan.title_plan', { where: where }),
      plan: parts.join(' '),
      plan_note: phrase('survey_plan.figure_note'),
    };
  }

  /* a distance along a line as a station's name has it: Python's g, its
   * whole metres zero-padded to width figures */
  /** @param {number} value @param {number} width */
  function spChainage(value, width) {
    var text = formatG(value), head = text.split('.')[0];
    return '0'.repeat(Math.max(0, width - head.length)) + text;
  }

  /** @param {Rec} line @returns {string[]} */
  function spStationNames(line) {
    var width = formatG(line.length_m).split('.')[0].length, out = [];
    for (var k = line.first; k <= line.last; k++) {
      out.push(phrase('survey_plan.station_name', { line: line.id,
        chainage: spChainage((k - line.first) * line.station_m, width) }));
    }
    return out;
  }

  /** @param {Rec} line */
  function spLineText(line) {
    if (line.candidate === null) {
      return phrase('survey_plan.line_strike', { length: line.length_m, bearing: line.bearing_deg,
        station: line.station_m, strike: line.strike_deg, at: line.crossing_m });
    }
    return phrase('survey_plan.line_candidate', { length: line.length_m, bearing: line.bearing_deg,
      station: line.station_m, kind: line.kind, candidate: line.candidate, at: line.crossing_m });
  }

  /** What a proposed sounding's GPX waypoint, GeoJSON feature and table row
   * say of it: where it lies, any move and its AB/2.
   * @param {Rec} plan @param {Rec} x a sounding @returns {string} */
  function surveySoundingText(plan, x) {
    var line = plan.lines[x.line - 1];
    var out = [x.role === 'crossing'
      ? phrase('survey_plan.sounding_crossing', { kind: line.kind, candidate: line.candidate, at: x.at_m,
        line: line.id })
      : phrase('survey_plan.sounding_flank', { offset: Math.abs(x.at_m - line.crossing_m), kind: line.kind,
        candidate: line.candidate, at: x.at_m, line: line.id })];
    if (x.moved_m !== 0) {
      out.push(phrase('survey_plan.sounding_moved', { moved: Math.abs(x.moved_m),
        cleared: andJoin(x.cleared.map(function (/** @type {string} */ name) { return phrase(SP_CLEARED[name]); })) }));
    }
    out.push(phrase('survey_plan.sounding_spread', { ab2: Number(plan.ab2.max_ab2), spread: Number(plan.ab2.line_m),
      strike: x.spread_deg }));
    return out.join(' ');
  }

  /** @param {any} text */
  function spXml(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /** @param {number} lon @param {number} lat @param {string} name @param {string|null} desc @param {string} kind */
  function spWpt(lon, lat, name, desc, kind) {
    return '<wpt lat="' + pyFixed(lat, 6) + '" lon="' + pyFixed(lon, 6) + '"><name>' + spXml(name) + '</name>' +
      (desc ? '<desc>' + spXml(desc) + '</desc>' : '') + '<type>' + spXml(kind) + '</type></wpt>\n';
  }

  /** The plan as a GPX 1.1 file, byte for byte as survey.survey_plan_gpx writes it.
   * @param {Rec} plan @param {ArrayLike<number>} lons @param {ArrayLike<number>} lats
   * @param {Rec} meta where, label and site_label @returns {string} */
  function surveyPlanGpx(plan, lons, lats, meta) {
    var out = ['<?xml version="1.0" encoding="UTF-8"?>\n',
      '<gpx version="1.1" creator="Groundwater Investigation Toolkit" xmlns="http://www.topografix.com/GPX/1/1">\n',
      '<metadata><name>', spXml(phrase('survey_plan.title_plan', { where: meta.where })), '</name><desc>',
      spXml(phrase('survey_plan.gpx_description', { where: meta.where, label: meta.label })), '</desc></metadata>\n'];
    out.push(spWpt(plan.site_lonlat[0], plan.site_lonlat[1], meta.site_label, null, 'Site'));
    plan.soundings.forEach(function (/** @type {Rec} */ x) {
      var p = lineamentLonLat(plan, lons, lats, x.point);
      out.push(spWpt(p[0], p[1], phrase('survey_plan.ves_name', { n: x.id }), surveySoundingText(plan, x), 'VES'));
    });
    plan.lines.forEach(function (/** @type {Rec} */ line) {
      [['survey_plan.line_start', line.first], ['survey_plan.line_end', line.last]].forEach(function (entry) {
        var p = lineamentLonLat(plan, lons, lats, lineStation(line, /** @type {number} */ (entry[1])));
        out.push(spWpt(p[0], p[1], phrase(/** @type {string} */ (entry[0]), { line: line.id }), null, 'Line end'));
      });
    });
    plan.lines.forEach(function (/** @type {Rec} */ line) {
      out.push('<rte><name>' + spXml(phrase('survey_plan.line_name', { line: line.id })) + '</name><desc>' +
        spXml(spLineText(line)) + '</desc>');
      var names = spStationNames(line);
      for (var k = line.first; k <= line.last; k++) {
        var p = lineamentLonLat(plan, lons, lats, lineStation(line, k));
        out.push('<rtept lat="' + pyFixed(p[1], 6) + '" lon="' + pyFixed(p[0], 6) + '"><name>' +
          spXml(names[k - line.first]) + '</name></rtept>');
      }
      out.push('</rte>\n');
    });
    out.push('</gpx>\n');
    return out.join('');
  }

  /** @param {Rec} plan @param {ArrayLike<number>} lons @param {ArrayLike<number>} lats
   * @param {number} x @param {number} y @param {number} d */
  function spRingText(plan, lons, lats, x, y, d) {
    var points = [];
    for (var k = 0; k < SP_RING_SEGMENTS; k++) {
      var sc = sinCosDeg(360 * k / SP_RING_SEGMENTS);
      var p = lineamentLonLat(plan, lons, lats, [x + d * sc[0], y + d * sc[1]]);
      points.push('[' + pyFixed(p[0], 6) + ',' + pyFixed(p[1], 6) + ']');
    }
    points.push(points[0]);
    return '{"type":"Polygon","coordinates":[[' + points.join(',') + ']]}';
  }

  /** @param {Rec} plan @param {ArrayLike<number>} lons @param {ArrayLike<number>} lats @param {number[]} point */
  function spPointText(plan, lons, lats, point) {
    var p = lineamentLonLat(plan, lons, lats, point);
    return '{"type":"Point","coordinates":[' + pyFixed(p[0], 6) + ',' + pyFixed(p[1], 6) + ']}';
  }

  /** @param {string} properties @param {string} geometry */
  function spFeature(properties, geometry) {
    return '{"type":"Feature","properties":{' + properties + '},"geometry":' + geometry + '}';
  }

  /** The plan as GeoJSON text, byte for byte as survey.survey_plan_geojson writes it.
   * @param {Rec} plan @param {ArrayLike<number>} lons @param {ArrayLike<number>} lats
   * @param {Rec} meta as surveyPlanGpx's @returns {string} */
  function surveyPlanGeoJson(plan, lons, lats, meta) {
    var sx = plan.site[0], sy = plan.site[1];
    var out = ['{"type":"FeatureCollection","description":',
      jsonAscii(phrase('survey_plan.geojson_description', { where: meta.where, label: meta.label,
        radius: plan.radius_m })),
      ',"radius_m":' + formatG(plan.radius_m) + ',"site":[' + pyFixed(plan.site_lonlat[0], 6) + ',' +
      pyFixed(plan.site_lonlat[1], 6) + '],"features":['];
    var features = [spFeature('"layer":"service_radius","radius_m":' + formatG(plan.radius_m),
      spRingText(plan, lons, lats, sx, sy, plan.radius_m))];
    plan.rings.forEach(function (/** @type {any[]} */ ring) {
      features.push(spFeature('"layer":"clearance","structure":' + jsonAscii(ring[2]) + ',"distance_m":' +
        formatG(ring[3]), spRingText(plan, lons, lats, ring[0], ring[1], ring[3])));
    });
    plan.lines.forEach(function (/** @type {Rec} */ line) {
      var a = lineamentLonLat(plan, lons, lats, lineStation(line, line.first));
      var b = lineamentLonLat(plan, lons, lats, lineStation(line, line.last));
      features.push(spFeature('"layer":"line","line":' + String(line.id) + ',"name":' +
        jsonAscii(phrase('survey_plan.line_name', { line: line.id })) + ',"candidate":' +
        (line.candidate === null ? 'null' : String(line.candidate)) + ',"kind":' +
        (line.kind === null ? 'null' : jsonAscii(line.kind)) + ',"strike_deg":' + pyFixed(line.strike_deg, 1) +
        ',"bearing_deg":' + pyFixed(line.bearing_deg, 1) + ',"length_m":' + pyFixed(line.length_m, 1) +
        ',"station_m":' + formatG(line.station_m) + ',"crossing_m":' + pyFixed(line.crossing_m, 1) +
        ',"description":' + jsonAscii(spLineText(line)),
      '{"type":"LineString","coordinates":[[' + pyFixed(a[0], 6) + ',' + pyFixed(a[1], 6) + '],[' +
        pyFixed(b[0], 6) + ',' + pyFixed(b[1], 6) + ']]}'));
    });
    plan.lines.forEach(function (/** @type {Rec} */ line) {
      var names = spStationNames(line);
      for (var k = line.first; k <= line.last; k++) {
        features.push(spFeature('"layer":"station","line":' + String(line.id) + ',"name":' +
          jsonAscii(names[k - line.first]) + ',"chainage_m":' + pyFixed((k - line.first) * line.station_m, 1),
        spPointText(plan, lons, lats, lineStation(line, k))));
      }
    });
    plan.soundings.forEach(function (/** @type {Rec} */ x) {
      features.push(spFeature('"layer":"sounding","name":' + jsonAscii(phrase('survey_plan.ves_name', { n: x.id })) +
        ',"line":' + String(x.line) + ',"role":' + jsonAscii(x.role) + ',"chainage_m":' + pyFixed(x.at_m, 1) +
        ',"moved_m":' + pyFixed(x.moved_m, 1) + ',"ab2_max_m":' + formatG(Number(plan.ab2.max_ab2)) +
        ',"spread_m":' + formatG(Number(plan.ab2.line_m)) + ',"spread_deg":' + pyFixed(x.spread_deg, 1) +
        ',"description":' + jsonAscii(surveySoundingText(plan, x)), spPointText(plan, lons, lats, x.point)));
    });
    out.push(features.join(','), ']}');
    return out.join('');
  }

  Object.assign(C, {
    waterPointKind: waterPointKind, surveyPlan: surveyPlan, surveyPlanCaptions: surveyPlanCaptions,
    surveyPlanGpx: surveyPlanGpx, surveyPlanGeoJson: surveyPlanGeoJson, surveySoundingText: surveySoundingText,
    lineStation: lineStation, waterPointReach: waterPointReach,
  });

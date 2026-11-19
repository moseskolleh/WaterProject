

  /* ============================================================== subsurface
   * groundwater/mapping/subsurface.py and groundwater/mapping/maps.py: the
   * survey's own geometry, and the interpolation the subsurface figures are
   * drawn from.
   *
   * The browser report drew no study-area map, no suitability map and no
   * survey-derived figure at all - no section, no pseudo-section, no
   * subsurface map - while the Python engine drew every one of them
   * (webapp-parity-5). This section is the arithmetic half of closing that:
   * the chainage of each station along the traverse, the gaps too wide to
   * correlate a horizon across, the interpolated surface, and the hull the
   * surface is blanked outside of. Nothing here draws anything.
   *
   * The refusals are as load-bearing as the numbers. Where the Python raises,
   * these return a `reason` string rather than throwing, because
   * reporting/geophysical.py catches ValueError and RuntimeError per figure
   * and keeps the rest of the report: one missing GPS position must not cost
   * the document the other figures. A caller that finds `reason` set draws
   * nothing and prints it, the way the report's "not drawn" list does; a
   * refusal that quietly drew something anyway would be worse than no figure.
   */

  /* mapping/subsurface.py PROTECTIVE_CLASSES: lower bound, upper bound, name,
   * colour. The map, its key and the word in the report all read this one
   * table, so a point's colour and the sentence beside it cannot disagree. */
  /** @type {Array<[number, number, string, string]>} */
  var PROTECTIVE_CLASSES = [
    [0.0, 0.1, 'poor', '#B2182B'],
    [0.1, 0.2, 'weak', '#EF8A62'],
    [0.2, 0.7, 'moderate', '#FDDBC7'],
    [0.7, 5.0, 'good', '#92C5DE'],
    [5.0, Infinity, 'very good', '#2166AC'],
  ];

  var SUBSURFACE_CREDIT = 'Subsurface interpretation from this survey\'s ' +
    'vertical electrical soundings; no external dataset';

  /* subsurface.py CORRELATION_REACH_MULTIPLE. Stations further apart than
   * this many times the depth of investigation have nothing measured between
   * them: no boundary is correlated across such a gap, and a survey with no
   * closer pair gets no section at all. */
  var CORRELATION_REACH_MULTIPLE = 10.0;

  /* subsurface.py TraverseProfile.is_collinear: a tenth of the traverse
   * length is the working rule, which on a 400 m line is 40 m - inside the
   * positional error of a handheld GPS under canopy. */
  var COLLINEAR_STRAIGHTNESS = 0.10;

  /* subsurface.py COINCIDENT_STATION_M: two soundings recorded closer
   * together than this are one station. A metre is well inside the error of
   * a handheld GPS, and no survey pegs two soundings that close on purpose. */
  var COINCIDENT_STATION_M = 1.0;

  /* maps.py points_enclose_an_area's tolerance. */
  var AREA_TOLERANCE = 1e-6;

  /* Math.log10, not Math.log(x) / Math.LN10, which is what formatG's comment
   * is warning about: in V8 that division returns 2.9999999999999996 for a
   * thousand, where Math.log10 and numpy's log10 both return exactly 3. A
   * decade boundary is precisely where these scales are read, and taking the
   * floor of the wrong side of one put the colour bar of a section whose
   * lowest layer was 1,000 ohm-m at 100, a whole decade below the Python's,
   * with every layer drawn in the wrong half of the ramp. */
  function log10Of(value) { return Math.log10(value); }

  /* Python's "{:,.0f}". Rounded through pyRound first, because toLocaleString
   * rounds a tie away from zero where Python rounds it to even, and these
   * numbers are printed inside sentences the two engines are compared on. */
  function commaFixed0(value) {
    return thousandsFixed(pyRound(Number(value), 0), 0);
  }

  /**
   * @param {number} a
   * @param {number} b
   * @param {number} n
   * @returns {number[]}
   */
  function linspace(a, b, n) {
    var out = [], i;
    if (n <= 1) return [a];
    for (i = 0; i < n; i += 1) out.push(a + (b - a) * i / (n - 1));
    return out;
  }

  function diffs(values) {
    var out = [], i;
    for (i = 1; i < values.length; i += 1) out.push(values[i] - values[i - 1]);
    return out;
  }

  function hasPosition(item) {
    return !!item && item.site_easting !== null && item.site_easting !== undefined &&
      item.site_northing !== null && item.site_northing !== undefined;
  }

  /** maps.py to_zone: a recorded position re-expressed in the UTM zone `zone`.
   *
   * Sierra Leone straddles the 28N/29N boundary at 12 degrees W, and a survey
   * on that line can record its soundings in both zones: 829580 E in zone 28
   * and 170420 E in zone 29 are 400 m apart on the ground and 659 km apart as
   * numbers. Every survey-scale figure subtracts eastings, so each sounding is
   * brought into one zone, through its latitude and longitude, before any of
   * them is drawn. The zone a position was recorded in is read off its
   * easting, which in Sierra Leone identifies it.
   * @param {number|string} easting
   * @param {number|string} northing
   * @param {number} zone
   * @returns {number[]}
   */
  function toZone(easting, northing, zone) {
    var own = inferZoneForSierraLeone(Number(easting));
    if (own === zone) return [Number(easting), Number(northing)];
    var geo = utmToGeographic(Number(easting), Number(northing), own);
    if (!geo) return [Number(easting), Number(northing)];
    var utm = geographicToUtm(geo.lat, geo.lon, zone);
    return [utm.easting, utm.northing];
  }

  /** subsurface.py survey_zone: the zone the survey's own figures are drawn
   * in, the first positioned sounding's; null when none carries a position.
   * @param {Interpretation[]|null} interpretations
   * @returns {number|null}
   */
  function surveyZone(interpretations) {
    var first = (interpretations || []).filter(hasPosition)[0];
    return first ? inferZoneForSierraLeone(Number(first.site_easting)) : null;
  }

  /** subsurface.py _positioned: a sounding with no recorded position cannot be
   * put on a map or on a line, and is dropped rather than placed at a guess.
   * The rest are brought into one zone (by default the first positioned
   * sounding's): three soundings 400 m apart either side of 12 W came out as
   * a 660 km map and a "659732 m along" section. A sounding that needed
   * moving is a copy, so the caller's keeps the position it recorded.
   * @param {Interpretation[]|null} interpretations
   * @param {number|null} [zone] the first positioned sounding's when not given
   * @returns {Interpretation[]}
   */
  function positionedSoundings(interpretations, zone) {
    var placed = (interpretations || []).filter(hasPosition);
    var target = (zone === null || zone === undefined) ? surveyZone(placed) : zone;
    return placed.map(function (item) {
      var moved = toZone(item.site_easting, item.site_northing, /** @type {number} */ (target));
      if (moved[0] === Number(item.site_easting) &&
          moved[1] === Number(item.site_northing)) {
        return item;
      }
      return Object.assign({}, item, { site_easting: moved[0], site_northing: moved[1] });
    });
  }

  /* --- the linear algebra numpy would have done ---------------------------
   *
   * Two of the rules below are singular-value tests on an N-by-2 matrix of
   * centred positions: the principal axis the traverse is projected onto, and
   * whether the points enclose any area at all. numpy.linalg.svd is not in
   * the browser, but with two columns the answer is closed form.
   */

  /** Both singular values of the centred positions.
   *
   * Taken from a QR factorisation rather than from the normal matrix: the
   * normal matrix squares the condition number, and the smaller singular
   * value of a nearly straight traverse is exactly the quantity that decides
   * whether a surface is drawn. The re-orthogonalisation is the classic
   * "twice is enough": one pass of Gram-Schmidt loses the residual to
   * cancellation precisely when the second column is nearly parallel to the
   * first, which is the straight-traverse case this test exists for.
   * @param {number[]} x
   * @param {number[]} y
   * @returns {number[]}
   */
  function singularValues2(x, y) {
    var n = x.length, i, r11 = 0.0, r12 = 0.0, r22 = 0.0, correction = 0.0;
    for (i = 0; i < n; i += 1) r11 += x[i] * x[i];
    r11 = Math.sqrt(r11);
    if (r11 === 0.0) {
      for (i = 0; i < n; i += 1) r22 += y[i] * y[i];
      return [Math.sqrt(r22), 0.0];
    }
    var q = [], w = [];
    for (i = 0; i < n; i += 1) q.push(x[i] / r11);
    for (i = 0; i < n; i += 1) r12 += q[i] * y[i];
    for (i = 0; i < n; i += 1) w.push(y[i] - r12 * q[i]);
    for (i = 0; i < n; i += 1) correction += q[i] * w[i];
    for (i = 0; i < n; i += 1) {
      w[i] -= correction * q[i];
      r22 += w[i] * w[i];
    }
    r22 = Math.sqrt(r22);
    r12 += correction;
    /* the singular values of [[r11, r12], [0, r22]], the stable pair: the
     * larger from the sum of the two hypotenuses, the smaller from the
     * determinant, so it is never a difference of two near-equal numbers */
    var big = (Math.sqrt((r11 - r22) * (r11 - r22) + r12 * r12) +
      Math.sqrt((r11 + r22) * (r11 + r22) + r12 * r12)) / 2.0;
    var small = big > 0 ? Math.abs(r11 * r22) / big : 0.0;
    return [big, small];
  }

  /** The first right singular vector of the centred positions: the direction
   * of the best-fit line by total least squares, which is the eigenvector of
   * the 2-by-2 normal matrix for its larger eigenvalue. The direction, unlike
   * the smaller singular value, is well conditioned whenever there is a line
   * to find at all, so the normal matrix is good enough for it.
   * @param {number[]} x
   * @param {number[]} y
   * @returns {number[]}
   */
  function principalAxis(x, y) {
    var sxx = 0.0, sxy = 0.0, syy = 0.0, i;
    for (i = 0; i < x.length; i += 1) {
      sxx += x[i] * x[i];
      sxy += x[i] * y[i];
      syy += y[i] * y[i];
    }
    var half = (sxx + syy) / 2.0;
    var disc = Math.sqrt(Math.max(half * half - (sxx * syy - sxy * sxy), 0.0));
    var larger = half + disc;
    var vx, vy;
    if (sxy !== 0.0) {
      vx = larger - syy;
      vy = sxy;
    } else if (sxx >= syy) {
      vx = 1.0;
      vy = 0.0;
    } else {
      vx = 0.0;
      vy = 1.0;
    }
    var norm = Math.sqrt(vx * vx + vy * vy) || 1.0;
    return [vx / norm, vy / norm];
  }

  /** maps.py points_enclose_an_area.
   *
   * Three pegs on one line - the standard VES layout, and what a
   * tape-and-compass traverse or chainages typed by hand produce exactly -
   * enclose no area. Handed to a triangulation they are a precision error,
   * which in the Python is a RuntimeError that walked past every
   * "except ValueError" between the map and the report and took the whole
   * geophysical report down. The test is the smaller singular value of the
   * centred coordinates against the larger: below the tolerance the points
   * are a line to numerical precision.
   * @param {number[]} eastings
   * @param {number[]} northings
   * @param {number} [tolerance]
   * @returns {boolean}
   */
  function pointsEncloseAnArea(eastings, northings, tolerance) {
    var tol = tolerance === undefined ? AREA_TOLERANCE : tolerance;
    if (eastings.length < 3) return false;
    var ce = arrMean(eastings), cn = arrMean(northings);
    var dx = eastings.map(function (v) { return v - ce; });
    var dy = northings.map(function (v) { return v - cn; });
    var singular = singularValues2(dx, dy);
    if (singular[0] <= 0) return false;
    return singular[1] / singular[0] > tol;
  }

  /* --- the traverse ------------------------------------------------------- */

  /* The east component of a unit direction within a degree of north-south. */
  var NORTH_SOUTH_EAST_COMPONENT = Math.sin(1.0 * Math.PI / 180.0);

  /** A traverse's bearing as a title prints it, to the degree: subsurface.py
   * bearing_text. A line just west of north runs at a bearing just under 360,
   * which is written as 0, the bearing of the line it is within a degree of.
   * @param {number} bearingDeg
   * @returns {string}
   */
  function bearingText(bearingDeg) {
    var text = pyFixed(bearingDeg, 0);
    return text === '360' ? '0' : text;
  }

  /** subsurface.py traverse_profile: the soundings projected onto the best-fit
   * line through their recorded positions.
   *
   * The line is the principal axis of the positions, not the line joining the
   * first and last sounding: a traverse with a dog-leg in the middle has no
   * reason to be summarised by its endpoints, and the endpoints are the two
   * stations most likely to have been added last and placed loosely.
   *
   * Returns `reason` instead of raising when fewer than two soundings carry a
   * position, because every figure built on the traverse is skipped with that
   * reason printed rather than the report ending there.
   * @param {Interpretation[]|null} interpretations
   * @returns {Rec}
   */
  function traverseProfile(interpretations) {
    var all = interpretations || [];
    var positioned = positionedSoundings(all);
    if (positioned.length < 2) {
      return {
        reason: positioned.length + ' of ' + all.length + ' soundings carry a ' +
          'position. A traverse needs at least two: record the GPS position ' +
          'of every sounding on the field sheet.',
      };
    }
    /* positionedSoundings keeps the order it was given, so its k-th sounding
     * is the k-th of those in the list that carry a position */
    var source = [];
    all.forEach(function (item, k) { if (hasPosition(item)) source.push(k); });
    var e = positioned.map(function (item) { return Number(item.site_easting); });
    var n = positioned.map(function (item) { return Number(item.site_northing); });
    var labels = positioned.map(function (item, k) {
      return item.sounding_id || 'VES ' + (k + 1);
    });
    /* A traverse needs stations at distinct places. Soundings all recorded at
     * one position came out as a "0 m along bearing 90 degrees" section, and
     * two sharing a position shrank every column on it to a sliver, one drawn
     * over the other; both are refused, with the reason. */
    var pairs = 0, shared = [], a, b;
    for (a = 0; a < positioned.length; a += 1) {
      for (b = a + 1; b < positioned.length; b += 1) {
        pairs += 1;
        if (Math.hypot(e[a] - e[b], n[a] - n[b]) < COINCIDENT_STATION_M) {
          shared.push(labels[a] + ' and ' + labels[b]);
        }
      }
    }
    if (shared.length === pairs) {
      return {
        reason: 'all ' + positioned.length + ' positioned soundings are recorded ' +
          'at one position, so there is no traverse to draw them along; check the ' +
          'positions against the field notes',
      };
    }
    if (shared.length) {
      return {
        reason: (shared.length === 1 ? 'two soundings share' : 'soundings share') +
          ' one position (less than ' + formatG(COINCIDENT_STATION_M) + ' m apart): ' +
          shared.join('; ') + '. A traverse has one sounding at each station, and a ' +
          'figure along it would draw one on top of the other; check the positions ' +
          'against the field notes',
      };
    }
    var ce = arrMean(e), cn = arrMean(n);
    var dx = e.map(function (v) { return v - ce; });
    var dy = n.map(function (v) { return v - cn; });
    var direction = principalAxis(dx, dy);
    /* The sign of a singular vector is arbitrary, so the same five soundings
     * handed over in a different order came back as a section drawn the other
     * way round - the same ground, mirrored, with the chainages reversed. The
     * line is made to run eastwards, or northwards where it is within a degree
     * of north-south, so a survey has one section rather than two. Only an
     * exactly north-south line used to run northwards: one whose eastings
     * differed by 0.3 m, as a handheld GPS reads the same pegs, ran from the
     * south end, its stations reversed and its title at bearing 180. */
    if (Math.abs(direction[0]) < NORTH_SOUTH_EAST_COMPONENT) {
      if (direction[1] < 0) direction = [-direction[0], -direction[1]];
    } else if (direction[0] < 0) {
      direction = [-direction[0], -direction[1]];
    }
    var normal = [-direction[1], direction[0]];
    var along = [], across = [], k;
    for (k = 0; k < dx.length; k += 1) {
      along.push(dx[k] * direction[0] + dy[k] * direction[1]);
      across.push(dx[k] * normal[0] + dy[k] * normal[1]);
    }
    /* Soundings are returned in order along the line, which is the order a
     * section draws them in. That is not always field order, and where it
     * differs, field order was drawing the section back on itself. */
    var order = along.map(function (value, index) { return index; })
      .sort(function (a, b) { return along[a] - along[b] || a - b; });
    var pick = function (values) {
      return order.map(function (index) { return values[index]; });
    };
    var sortedAlong = pick(along);
    var offset = pick(across);
    var base = arrMin(sortedAlong);
    var chainage = sortedAlong.map(function (v) { return v - base; });
    /* never zero: distinct stations more than a metre apart were required
     * above, and the principal axis runs through the widest spread of them */
    var length = arrMax(chainage);
    var maxOffset = arrMax(offset.map(function (v) { return Math.abs(v); }));
    var bearing = ((Math.atan2(direction[0], direction[1]) * 180.0 / Math.PI) %
      360.0 + 360.0) % 360.0;
    return {
      reason: null,
      labels: pick(labels),
      chainage_m: chainage,
      offset_m: offset,
      max_offset_m: maxOffset,
      /* max offset as a fraction of the traverse length: soundings scattered
       * 300 m either side of a line are not a section, they are a map drawn
       * edge-on, and this says so rather than leaving the figure to imply
       * otherwise */
      straightness: maxOffset / length,
      bearing_deg: bearing,
      eastings: pick(e),
      northings: pick(n),
      is_collinear: maxOffset / length <= COLLINEAR_STRAIGHTNESS,
      length_m: arrMax(chainage) - arrMin(chainage),
      gaps_m: diffs(chainage),
      /* where each station's sounding sits in the list the profile was built
       * from: a figure takes its soundings by this, not by identifier, since
       * two soundings both called "VES 1" drew the second one's model at
       * both stations when the section looked them up by name */
      indices: order.map(function (k) { return source[k]; }),
    };
  }

  /** subsurface.py _wide_gaps: which gaps between neighbouring stations are too
   * wide to correlate a horizon across.
   * @param {Rec|null} profile what traverseProfile returns
   * @param {number} reachM
   * @returns {boolean[]}
   */
  function wideGaps(profile, reachM) {
    if (!profile || profile.reason) return [];
    if (!(reachM > 0) || profile.chainage_m.length < 2) return [];
    return profile.gaps_m.map(function (gap) {
      return gap > reachM * CORRELATION_REACH_MULTIPLE;
    });
  }

  /** subsurface.py _correlation_note: what is not correlated on the section,
   * and why. A sounding sees the ground under it, to a lateral reach of
   * roughly its largest electrode half-spacing; joining a layer boundary
   * across a gap many times that is drawing a line between two points and
   * calling it a horizon.
   * @param {Rec|null} profile what traverseProfile returns
   * @param {number} reachM
   * @param {boolean[]|null} [wide] what wideGaps returns
   * @returns {string}
   */
  function correlationNote(profile, reachM, wide) {
    if (!profile || profile.reason) return '';
    if (!(reachM > 0) || profile.chainage_m.length < 2) return '';
    var flags = wide === undefined || wide === null ? wideGaps(profile, reachM) : wide;
    var any = flags.some(function (flag) { return flag; });
    if (!any) return '';
    var parts = [];
    flags.forEach(function (isWide, k) {
      if (!isWide) return;
      parts.push(profile.labels[k] + ' to ' + profile.labels[k + 1] + ' (' +
        commaFixed0(profile.gaps_m[k]) + ' m, about ' +
        pyFixed(profile.gaps_m[k] / reachM, 0) + ' times the ' +
        commaFixed0(reachM) + ' m the soundings reached)');
    });
    return 'No boundary is correlated across the gap ' + parts.join('; ') +
      ': there is no measurement between those stations, and a dashed line ' +
      'across them would be a proposal drawn as a horizon.';
  }

  /** ves/plots.py _rho_norm: the log colour scale spanning the decades the
   * drawn models occupy. The fixed 10-5,000 ohm-m ramp it replaced coloured
   * 3 ohm-m saline clay the same as 10 ohm-m fresh-water clay and 20,000
   * ohm-m basement the same as 5,000, with nothing on the bar to say it had
   * clipped.
   * @param {LayeredModel[]|null} models
   * @returns {number[]}
   */
  function rhoColourRange(models) {
    var rho = [];
    (models || []).forEach(function (model) {
      (model.resistivities || []).forEach(function (value) {
        if (isFinite(value) && value > 0) rho.push(Number(value));
      });
    });
    if (!rho.length) return [10.0, 5000.0];
    var lo = Math.pow(10, Math.floor(log10Of(arrMin(rho))));
    var hi = Math.pow(10, Math.ceil(log10Of(arrMax(rho))));
    if (hi <= lo) hi = lo * 10;
    return [lo, hi];
  }

  /** subsurface.py geoelectric_section_along_traverse, plus the geometry
   * ves/plots.py plot_geoelectric_section derives from what it is handed.
   *
   * Everything the section needs and nothing it draws: the stations at their
   * surveyed chainage rather than evenly spaced, the depth the figure runs
   * to, how much ground a column stands for, which gaps carry a correlated
   * boundary, the note that says which do not, and the title.
   *
   * options: {title, depthMaxM} - the Python's two overridable arguments.
   * @param {Interpretation[]|null} interpretations
   * @param {Rec} [options] title, depthMaxM
   */
  function geoelectricSectionGeometry(interpretations, options) {
    var opts = options || {};
    var all = interpretations || [];
    var profile = traverseProfile(all);
    if (profile.reason) return { reason: profile.reason, profile: null };
    /* by position in the list, not by identifier: two soundings both called
     * "VES 1" drew the second one's model at both stations */
    var ordered = profile.indices.map(function (k) { return all[k]; });
    /* A column stands for the ground the sounding sampled, which is about its
     * largest electrode half-spacing either side of the peg - not for an equal
     * share of the profile. Two Rokel soundings 20 km apart came out as two
     * columns 8 km wide, which claims each sounding measured 8 km of ground. */
    var reaches = ordered.map(function (item) {
      return Number(item.investigation_depth_m || 0.0);
    });
    var reach = reaches.length ? arrMax(reaches) : 0.0;
    var title = opts.title;
    if (title === undefined || title === null) {
      title = 'Interpreted geoelectric section, ' + pyFixed(profile.length_m, 0) +
        ' m along bearing ' + bearingText(profile.bearing_deg) + ' degrees';
      if (!profile.is_collinear) {
        title += ' (soundings up to ' + pyFixed(profile.max_offset_m, 0) +
          ' m off the line)';
      }
    }
    var depthMax = opts.depthMaxM === undefined || opts.depthMaxM === null
      ? null : Number(opts.depthMaxM);
    if (depthMax === null && reach > 0) {
      /* the section is drawn to the depth the soundings resolve, the same rule
       * as every other figure, and never so shallow that a fitted interface
       * falls off the bottom of it */
      var interfaces = [];
      ordered.forEach(function (item) {
        var model = item.model;
        if (model && model.n_layers > 1) {
          interfaces.push(Number(model.depths_top[model.depths_top.length - 1]));
        }
      });
      var deepest = interfaces.length ? arrMax(interfaces) : 0.0;
      depthMax = Math.max(reach, deepest * 1.2 + 2.0);
    }
    /* A boundary is correlated between two stations only when they are within
     * the correlation rule of each other. Two Rokel soundings 20.7 km apart
     * used to come out as a 60 m section with a dashed horizon joining them: a
     * line between two points in different chiefdoms, called a section. Where
     * no pair of neighbours is within reach there is no section to draw and
     * the caller is told why. */
    var wide = wideGaps(profile, reach);
    if (wide.length && wide.every(function (flag) { return flag; })) {
      var widest = arrMax(profile.gaps_m);
      return {
        reason: 'the soundings are ' + commaFixed0(widest) + ' m apart, about ' +
          pyFixed(widest / reach, 0) + ' times the ' + commaFixed0(reach) +
          ' m they resolve; a section between them would join two measurements ' +
          'with no measurement between, so none is drawn. A section needs ' +
          'stations within a few times the depth of investigation of each other.',
        profile: profile,
      };
    }
    var positions = profile.chainage_m.slice();
    var labels = ordered.map(function (item) { return item.sounding_id || 'VES'; });
    var models = ordered.map(function (item) { return item.model; });
    /* The three lists are read as one column per sounding, so they have to
     * agree. A caller that derives them separately can desynchronise them: a
     * sounding whose identifier the traverse does not share leaves the models
     * one short of the chainages, which draws the section with a sounding
     * silently dropped or the labels off by one - neither visible in the
     * finished figure, and both of which reach a signed survey report. */
    if (positions.length !== models.length || labels.length !== models.length) {
      return {
        reason: models.length + ' soundings need ' + models.length +
          ' positions and ' + models.length + ' labels; got ' + positions.length +
          ' and ' + labels.length,
        profile: profile,
      };
    }
    /* ves/plots.py plot_geoelectric_section: two columns at one chainage are
     * one drawn over the other, and the column width is capped at the
     * narrowest gap, so a repeated position also shrank every other column on
     * the section to a sliver */
    var sortedX = positions.slice().sort(function (p, q) { return p - q; });
    var repeated = [];
    for (var r = 1; r < sortedX.length; r += 1) {
      if (sortedX[r] === sortedX[r - 1] && repeated.indexOf(sortedX[r]) < 0) {
        repeated.push(sortedX[r]);
      }
    }
    if (repeated.length) {
      return {
        reason: 'more than one sounding is placed at ' + repeated.map(function (x) {
          return formatG(x) + ' m';
        }).join(', ') + ' along the profile; a section draws one column at each ' +
          'station, and one would hide the other',
        profile: profile,
      };
    }
    if (depthMax === null) {
      var depths = models.map(function (model) {
        return (model.n_layers > 1
          ? model.depths_top[model.depths_top.length - 1] : 10) * 1.35 + 5;
      });
      depthMax = arrMax(depths);
    }
    var span = (arrMax(positions) - arrMin(positions)) || 100.0;
    var halfWidth;
    if (reach > 0) {
      /* never wider than the ground to the next peg, or the columns overlap
       * and the section reads as one continuous exposure */
      var stepGaps = diffs(positions.slice().sort(function (a, b) { return a - b; }));
      var limit = stepGaps.length ? arrMin(stepGaps) / 2.2 : span;
      halfWidth = Math.max(Math.min(reach, limit), span * 0.004);
    } else {
      halfWidth = span / (models.length * 2.6);
    }
    var correlate = wide.map(function (flag) { return !flag; });
    if (!correlate.length) {
      for (var k = 0; k < Math.max(models.length - 1, 0); k += 1) correlate.push(true);
    }
    if (correlate.length !== Math.max(models.length - 1, 0)) {
      return {
        reason: models.length + ' soundings have ' +
          Math.max(models.length - 1, 0) + ' gaps between them; got ' +
          correlate.length + ' correlation flags',
        profile: profile,
      };
    }
    return {
      reason: null,
      profile: profile,
      interpretations: ordered,
      models: models,
      labels: labels,
      positions_m: positions,
      reach_m: reach,
      depth_max_m: depthMax,
      half_width_m: halfWidth,
      gaps_m: profile.gaps_m,
      wide_gaps: wide,
      correlate: correlate,
      note: correlationNote(profile, reach, wide),
      title: title,
      rho_range: rhoColourRange(models),
      x_label: 'Distance along profile (m)',
      y_label: 'Depth (m)',
      cbar_label: 'Resistivity (ohm-m)',
    };
  }

  /** subsurface.py apparent_resistivity_pseudosection: the measurements
   * themselves, laid out along the traverse, before any inversion has been
   * believed. The vertical axis is AB/2 - the electrode half-spacing - and is
   * left as such rather than converted to a depth, because the pseudo-depth
   * conversions vary with the very layering the figure is drawn to reveal,
   * and calling a measurement geometry a depth is how a pseudo-section starts
   * being read as a cross-section.
   *
   * `profile` places the stations; without one the soundings are laid out in
   * the order given, evenly spaced, and the note says so.
   * @param {Sounding[]|null} soundings
   * @param {Rec|null} [profile] what traverseProfile returns
   */
  function pseudosectionGeometry(soundings, profile) {
    var list = soundings || [];
    /* A profile that failed is not the same as no profile at all, and the
     * difference is a figure. The report builds the traverse first and skips
     * the pseudo-section altogether when that raises, printing its reason;
     * only a caller with no positions to offer passes none and gets the evenly
     * spaced fallback. Treating a failed profile as "no positions recorded"
     * drew an evenly spaced pseudo-section, under a note saying no sounding
     * positions were recorded, for a survey that recorded one - a figure the
     * package refuses to draw, captioned with something untrue. The check
     * comes first because the report's does: the traverse is built before the
     * pseudo-section is attempted, so its reason is the one printed. */
    if (profile && profile.reason) return { reason: profile.reason };
    if (list.length < 2) {
      return {
        reason: 'a pseudo-section needs at least two soundings; got ' +
          list.length,
      };
    }
    var ids = list.map(function (sounding, k) {
      return sounding.sounding_id || 'VES ' + (k + 1);
    });
    var ordered = [], stations = [], xLabel, spacedEvenly;
    if (profile) {
      var parallel = !!(profile.indices && profile.indices.length) &&
        profile.indices.every(function (k, j) {
          return k < list.length && ids[k] === profile.labels[j];
        });
      if (parallel) {
        /* the soundings are the list the profile was built from, so each
         * station takes its own readings by position: two soundings both
         * called "VES 1" drew the second one's readings at both stations
         * when they were looked up by name */
        ordered = profile.indices.map(function (k) { return list[k]; });
        stations = profile.chainage_m.map(Number);
      } else {
        var byId = {};
        list.forEach(function (sounding, k) { byId[ids[k]] = sounding; });
        profile.labels.forEach(function (label, k) {
          if (!own(byId, label)) return;
          ordered.push(byId[label]);
          stations.push(Number(profile.chainage_m[k]));
        });
      }
      xLabel = 'Distance along traverse (m)';
      spacedEvenly = false;
    } else {
      ordered = list.slice();
      stations = ordered.map(function (sounding, k) { return k * 100.0; });
      xLabel = 'Station (evenly spaced; no positions recorded)';
      spacedEvenly = true;
    }
    if (ordered.length < 2) {
      return {
        reason: 'the traverse profile and the soundings share fewer than two ' +
          'sounding identifiers, so the stations cannot be placed',
      };
    }
    var xs = [], ys = [], vs = [];
    ordered.forEach(function (sounding, k) {
      var ab2 = sounding.ab2 || [], rho = sounding.rho_app || [];
      var count = Math.min(ab2.length, rho.length), i;
      for (i = 0; i < count; i += 1) {
        if (!isFinite(ab2[i]) || !isFinite(rho[i]) || rho[i] <= 0) continue;
        xs.push(stations[k]);
        ys.push(Number(ab2[i]));
        vs.push(Number(rho[i]));
      }
    });
    if (vs.length < 4) {
      return {
        reason: vs.length + ' usable readings across ' + ordered.length +
          ' soundings; a pseudo-section needs a curve at each station.',
      };
    }
    /* Colour is interpolated between two stations only when they are within
     * the correlation rule of each other; between a pair further apart there
     * is no measurement, and a continuous banded fill across 20 km reads as a
     * 20 km resistivity cross-section. */
    var maxGap = arrMax(ys) * 0.5 * CORRELATION_REACH_MULTIPLE;
    var uncorrelated = [];
    var k;
    for (k = 0; k < stations.length - 1; k += 1) {
      var gap = stations[k + 1] - stations[k];
      if (gap > maxGap) {
        uncorrelated.push([ordered[k].sounding_id || 'VES',
          ordered[k + 1].sounding_id || 'VES', gap]);
      }
    }
    var vmin = Math.max(arrMin(vs), 1.0);
    var vmax = Math.max(arrMax(vs), vmin * 1.05);
    /* Levels spaced the way the colours are. Asking for a plain level count
     * under a log scale gets evenly spaced levels in ohm-m, which a log ramp
     * then squeezes into two bands: a section spanning 60 to 900 ohm-m came
     * out one flat colour with a stripe through it, and the fill disagreed
     * with the very readings drawn on top of it. */
    var levels = geomspace(vmin, vmax, 14);
    /* a triangulated fill between the readings, in the coordinates the figure
     * is drawn in - station against log AB/2 - with any triangle spanning
     * more ground than the correlation rule allows left out */
    var logY = ys.map(function (v) { return log10Of(v); });
    var triangles = delaunayTriangles(xs, logY).filter(function (tri) {
      var lo = Math.min(xs[tri[0]], xs[tri[1]], xs[tri[2]]);
      var hi = Math.max(xs[tri[0]], xs[tri[1]], xs[tri[2]]);
      return hi - lo <= maxGap;
    });
    /* decade ticks, but only the ones the readings reach: an 80 m spread does
     * not get a 100 m tick */
    var decades = {}, ticks = [];
    logY.forEach(function (value) { decades[pyRound(value, 0)] = true; });
    Object.keys(decades).map(Number).sort(function (a, b) { return a - b; })
      .forEach(function (tick) {
        var spacing = Math.pow(10, tick);
        if (arrMin(ys) / 1.5 <= spacing && spacing <= arrMax(ys) * 1.5) {
          ticks.push([tick, formatG(spacing)]);
        }
      });
    var spacing = spacingName(ordered);
    var notes = [spacingNote(spacing)];
    if (uncorrelated.length) {
      notes.push('No colour is interpolated across ' +
        uncorrelated.map(function (pair) {
          return pair[0] + ' to ' + pair[1] + ' (' + commaFixed0(pair[2]) + ' m)';
        }).join('; ') + ': nothing was measured between those stations.');
    }
    if (spacedEvenly) {
      notes.push('Stations are drawn evenly spaced because no sounding ' +
        'positions were recorded; the horizontal scale is not ground distance.');
    } else if (profile && !profile.reason && !profile.is_collinear) {
      notes.push('The soundings sit up to ' + pyFixed(profile.max_offset_m, 0) +
        ' m off the profile line (' + pyFixed(profile.straightness * 100, 0) +
        '% of its ' + pyFixed(profile.length_m, 0) + ' m length), so this ' +
        'section cuts across the survey rather than along it.');
    }
    return {
      reason: null,
      soundings: ordered,
      labels: ordered.map(function (sounding) {
        return sounding.sounding_id || 'VES';
      }),
      stations_m: stations,
      readings: { x: xs, ab2: ys, log_ab2: logY, rho: vs },
      triangles: triangles,
      max_gap_m: maxGap,
      uncorrelated: uncorrelated,
      range: [vmin, vmax],
      levels: levels,
      ticks: ticks,
      notes: notes,
      note: notes.join('  '),
      spaced_evenly: spacedEvenly,
      title: 'Apparent resistivity pseudo-section along the traverse',
      x_label: xLabel,
      y_label: spacing + ' (m)',
      spacing: spacing,
      cbar_label: 'Apparent resistivity (ohm-m)',
    };
  }

  /** subsurface.py spacing_name: what the soundings' electrode spacing is
   * called. A Wenner sounding is read against the spacing a, and a
   * pseudo-section of Wenner readings labelled "AB/2 (m)" named a spacing
   * nobody set out.
   * @param {Sounding[]|null} soundings
   * @returns {string}
   */
  function spacingName(soundings) {
    var wenner = {};
    (soundings || []).forEach(function (sounding) {
      wenner[String(sounding.array_type || 'schlumberger').indexOf('wenner') === 0] = true;
    });
    if (wenner['true'] && !wenner['false']) return 'a';
    if (wenner['true']) return 'AB/2 or a';
    return 'AB/2';
  }

  /** subsurface.py spacing_note: the pseudo-section's warning that its
   * vertical axis is not a depth.
   * @param {string} name
   * @returns {string}
   */
  function spacingNote(name) {
    if (name === 'a') {
      return 'The Wenner spacing a is the electrode spacing, not a depth: a ' +
        'deeper reading is a wider spread, not a measured horizon.';
    }
    if (name === 'AB/2') {
      return 'AB/2 is the electrode half-spacing, not a depth: a deeper ' +
        'reading is a wider spread, not a measured horizon.';
    }
    return 'AB/2 and a are electrode spacings, not depths: a deeper reading is ' +
      'a wider spread, not a measured horizon.';
  }

  /** reporting/geophysical.py's pseudo-section caption, naming the spacing the
   * readings were taken with.
   * @param {string} spacing
   * @param {Rec|null} [profile]
   * @returns {string}
   */
  function pseudosectionCaption(spacing, profile) {
    var caption = 'Apparent resistivity along the traverse, as measured. Unlike ' +
      'every other section in this report it involves no inversion: each point ' +
      'is a reading at the station and electrode spacing it was taken with. ' +
      ({ 'AB/2': 'AB/2 is that spacing, not a depth.',
        a: 'The Wenner spacing a is that spacing, not a depth.' }[spacing] ||
        'AB/2 and a are those spacings, not depths.') +
      ' Colour is interpolated only between stations within reach of each other.';
    if (profile && !profile.reason && !profile.is_collinear) {
      caption += ' The soundings sit up to ' + pyFixed(profile.max_offset_m, 0) +
        ' m off the profile line, so this section cuts across the survey rather ' +
        'than along it.';
    }
    return caption;
  }

  /* --- the interpolated surface -------------------------------------------
   *
   * scipy's griddata is a Delaunay triangulation, a linear interpolant inside
   * it and a nearest-neighbour fill outside; matplotlib's hull clip then
   * blanks whatever sits outside the ground the survey covered. All three are
   * below, because the browser has none of them.
   */

  /** A Delaunay triangulation of the points, as index triples.
   *
   * Bowyer-Watson, which is enough for the dozens of points a survey has. The
   * coordinates are shifted and scaled by ONE factor for both axes before
   * triangulating: a similarity transform leaves a Delaunay triangulation
   * unchanged, where scaling the axes separately would quietly produce a
   * different triangulation from the Python's - and UTM eastings squared lose
   * the precision the circumcircle test needs.
   * @param {number[]} xs
   * @param {number[]} ys
   * @returns {number[][]}
   */
  function delaunayTriangles(xs, ys) {
    var count = xs.length, i;
    if (count < 3) return [];
    var minX = arrMin(xs), maxX = arrMax(xs);
    var minY = arrMin(ys), maxY = arrMax(ys);
    var scale = Math.max(maxX - minX, maxY - minY) || 1.0;
    var px = [], py = [];
    for (i = 0; i < count; i += 1) {
      px.push((xs[i] - minX) / scale);
      py.push((ys[i] - minY) / scale);
    }
    /* A super-triangle far outside the unit box the points now sit in - far
     * enough to hold every circumcircle those points can generate, which a
     * hundred was not. A traverse with a couple of metres of GPS wobble either
     * side of the line is the commonest survey layout there is, and its
     * triangles have circumcircles hundreds of thousands of times as wide as
     * the traverse itself; every such triangle reached past a super-triangle
     * a hundred units out and was never formed. Three soundings on such a line
     * came back with no triangulation at all, so the map printed "the survey
     * points lie on one line and enclose no area" and drew nothing where the
     * Python drew the surface, and four or more lost the linear interpolant
     * over part of the hull to the nearest-neighbour fill. Measured against
     * qhull on 268 layouts, a hundred disagreed on 78 of them and this agrees
     * on all of them. A surface is only drawn at all above a singular ratio of
     * 1e-6 (pointsEncloseAnArea), whose flattest triangle has a circumcircle
     * of order 1e5 unit boxes, so 1e8 clears it by three orders of magnitude. */
    px.push(-1e8, 1e8, 0.0);
    py.push(-1e8, -1e8, 1e8);
    var triangles = [[count, count + 1, count + 2]];
    for (i = 0; i < count; i += 1) {
      var kept = [], edges = [], t;
      for (t = 0; t < triangles.length; t += 1) {
        if (inCircumcircle(px, py, triangles[t], px[i], py[i])) {
          edges.push([triangles[t][0], triangles[t][1]],
            [triangles[t][1], triangles[t][2]],
            [triangles[t][2], triangles[t][0]]);
        } else {
          kept.push(triangles[t]);
        }
      }
      /* the cavity's boundary is the edges that only one bad triangle had */
      edges.forEach(function (edge, k) {
        var shared = edges.some(function (other, m) {
          return m !== k && other[0] === edge[1] && other[1] === edge[0];
        });
        if (!shared) kept.push([edge[0], edge[1], i]);
      });
      triangles = kept;
    }
    var out = [];
    triangles.forEach(function (tri) {
      if (tri[0] >= count || tri[1] >= count || tri[2] >= count) return;
      var area = (px[tri[1]] - px[tri[0]]) * (py[tri[2]] - py[tri[0]]) -
        (py[tri[1]] - py[tri[0]]) * (px[tri[2]] - px[tri[0]]);
      /* a triangle with no area interpolates nothing and divides by zero */
      if (Math.abs(area) <= 1e-12) return;
      out.push([tri[0], tri[1], tri[2]]);
    });
    return out;
  }

  function inCircumcircle(px, py, tri, x, y) {
    var ax = px[tri[0]] - x, ay = py[tri[0]] - y;
    var bx = px[tri[1]] - x, by = py[tri[1]] - y;
    var cx = px[tri[2]] - x, cy = py[tri[2]] - y;
    var det = (ax * ax + ay * ay) * (bx * cy - cx * by) -
      (bx * bx + by * by) * (ax * cy - cx * ay) +
      (cx * cx + cy * cy) * (ax * by - bx * ay);
    var orientation = (px[tri[1]] - px[tri[0]]) * (py[tri[2]] - py[tri[0]]) -
      (py[tri[1]] - py[tri[0]]) * (px[tri[2]] - px[tri[0]]);
    return orientation >= 0 ? det > 0 : det < 0;
  }

  /** The convex hull of the points, counter-clockwise, by monotone chain.
   * @param {number[]} eastings
   * @param {number[]} northings
   * @returns {number[][]}
   */
  function convexHull(eastings, northings) {
    var order = eastings.map(function (value, index) { return index; })
      .sort(function (a, b) {
        return eastings[a] - eastings[b] || northings[a] - northings[b];
      });
    var cross = function (o, a, b) {
      return (eastings[a] - eastings[o]) * (northings[b] - northings[o]) -
        (northings[a] - northings[o]) * (eastings[b] - eastings[o]);
    };
    var build = function (sequence) {
      var chain = [];
      sequence.forEach(function (index) {
        while (chain.length >= 2 &&
          cross(chain[chain.length - 2], chain[chain.length - 1], index) <= 0) {
          chain.pop();
        }
        chain.push(index);
      });
      chain.pop();
      return chain;
    };
    var lower = build(order);
    var upper = build(order.slice().reverse());
    return lower.concat(upper).map(function (index) {
      return [eastings[index], northings[index]];
    });
  }

  /** The crossing test matplotlib's Path.contains_points uses, written its way
   * on purpose: the divisions of the textbook version answer differently for
   * a grid point sitting exactly on a hull edge, and a square four-peg survey
   * puts a whole diagonal of grid points exactly on one. Multiplying instead
   * of dividing keeps the comparison exact, so the browser blanks the same
   * cells the Python does rather than a line of them more or fewer.
   * @param {number[][]} polygon
   * @param {number} x
   * @param {number} y
   * @returns {boolean}
   */
  function pointInPolygon(polygon, x, y) {
    var inside = false, i;
    var x0 = polygon[polygon.length - 1][0], y0 = polygon[polygon.length - 1][1];
    var above0 = y0 >= y;
    for (i = 0; i < polygon.length; i += 1) {
      var x1 = polygon[i][0], y1 = polygon[i][1];
      var above1 = y1 >= y;
      if (above0 !== above1 &&
        (((y1 - y) * (x0 - x1) >= (x1 - x) * (y0 - y1)) === above1)) {
        inside = !inside;
      }
      above0 = above1;
      x0 = x1;
      y0 = y1;
    }
    return inside;
  }

  /** The grid the surfaces are sampled on: a rectangle of nx by ny points,
   * with the values row-major, z[j * nx + i] for x[i], y[j], and null where
   * nothing is drawn.
   * @param {number} x0
   * @param {number} x1
   * @param {number} y0
   * @param {number} y1
   * @param {number} n
   * @returns {SurfaceGrid}
   */
  function gridFrom(x0, x1, y0, y1, n) {
    return { nx: n, ny: n, x: linspace(x0, x1, n), y: linspace(y0, y1, n), z: null };
  }

  /** maps.py _surface: the interpolated surface, or null when the points
   * cannot support one.
   *
   * The linear interpolant needs a triangulation, which needs an area; the
   * nearest-neighbour fill outside it is what the maps show at the edges. Any
   * triangulation failure is reported as "no surface" rather than as an
   * exception, because the figure is one of several in a report and none of
   * them should cost the document the others.
   * @param {number[]} eastings
   * @param {number[]} northings
   * @param {number[]} values
   * @param {SurfaceGrid} grid
   * @returns {Array<number|null>|null}
   */
  function surfaceGrid(eastings, northings, values, grid) {
    if (!pointsEncloseAnArea(eastings, northings)) return null;
    var z = [], i, j;
    for (i = 0; i < grid.nx * grid.ny; i += 1) z.push(null);
    var triangles;
    try {
      triangles = delaunayTriangles(eastings, northings);
    } catch (err) {
      return null;
    }
    if (!triangles.length) return null;
    var dx = grid.nx > 1 ? (grid.x[grid.nx - 1] - grid.x[0]) / (grid.nx - 1) : 1.0;
    var dy = grid.ny > 1 ? (grid.y[grid.ny - 1] - grid.y[0]) / (grid.ny - 1) : 1.0;
    triangles.forEach(function (tri) {
      var ax = eastings[tri[0]], ay = northings[tri[0]];
      var bx = eastings[tri[1]], by = northings[tri[1]];
      var cx = eastings[tri[2]], cy = northings[tri[2]];
      var det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
      if (det === 0) return;
      var i0 = Math.max(0, Math.ceil((Math.min(ax, bx, cx) - grid.x[0]) / dx));
      var i1 = Math.min(grid.nx - 1,
        Math.floor((Math.max(ax, bx, cx) - grid.x[0]) / dx));
      var j0 = Math.max(0, Math.ceil((Math.min(ay, by, cy) - grid.y[0]) / dy));
      var j1 = Math.min(grid.ny - 1,
        Math.floor((Math.max(ay, by, cy) - grid.y[0]) / dy));
      var gi, gj;
      for (gj = j0; gj <= j1; gj += 1) {
        for (gi = i0; gi <= i1; gi += 1) {
          var x = grid.x[gi], y = grid.y[gj];
          var w0 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / det;
          var w1 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / det;
          var w2 = 1.0 - w0 - w1;
          /* the cell belongs to this triangle when it is inside it, with no
           * tolerance either way: a cell a rounding error outside every
           * triangle is left for the nearest-neighbour fill below, which is
           * what griddata does with the NaN its linear interpolant returns
           * there, and a looser test put a linear value where the Python has
           * the value at the nearest peg */
          if (w0 >= 0 && w1 >= 0 && w2 >= 0) {
            z[gj * grid.nx + gi] = w0 * values[tri[0]] + w1 * values[tri[1]] +
              w2 * values[tri[2]];
          }
        }
      }
    });
    for (j = 0; j < grid.ny; j += 1) {
      for (i = 0; i < grid.nx; i += 1) {
        if (z[j * grid.nx + i] !== null) continue;
        var best = 0, bestD = Infinity, p;
        for (p = 0; p < eastings.length; p += 1) {
          var ex = grid.x[i] - eastings[p], ny2 = grid.y[j] - northings[p];
          var d = ex * ex + ny2 * ny2;
          if (d < bestD) { bestD = d; best = p; }
        }
        z[j * grid.nx + i] = values[best];
      }
    }
    return z;
  }

  /** maps.py _clip_to_surveyed_ground: blank the interpolated surface outside
   * the ground the survey covered.
   *
   * An interpolated resistivity or thickness surface is read as data: a
   * hydrogeologist looking at a contour 400 m from the nearest sounding will
   * site a borehole on it. Outside the hull of the points there is no
   * measurement behind the colour at all - it is the interpolator continuing a
   * trend - so the surface is blanked there rather than drawn in a shade that
   * looks like every other shade on the map. Points that enclose no area have
   * no hull to clip to: that is an ordinary survey, not an error, so the
   * surface stands and the figure says on its own face that the values away
   * from the line are extrapolated.
   * @param {Array<number|null>} z
   * @param {number[]} eastings
   * @param {number[]} northings
   * @param {SurfaceGrid} grid
   */
  function clipToSurveyedGround(z, eastings, northings, grid) {
    var hull = convexHull(eastings, northings);
    if (hull.length < 3) {
      return {
        z: z, clipped: false, hull: null,
        note: 'Surface not clipped: the survey points enclose no area, so ' +
          'values away from them are extrapolated.',
      };
    }
    var masked = [], i, j;
    for (j = 0; j < grid.ny; j += 1) {
      for (i = 0; i < grid.nx; i += 1) {
        masked.push(pointInPolygon(hull, grid.x[i], grid.y[j])
          ? z[j * grid.nx + i] : null);
      }
    }
    return { z: masked, clipped: true, hull: hull, note: '' };
  }

  /** maps.py _no_surface_note: said on the map itself, because a caption can be
   * skipped and a line across the middle of the figure cannot.
   * @param {number} nPoints
   * @returns {string}
   */
  function noSurfaceNote(nPoints) {
    return nPoints >= 3
      ? 'Surface not drawn: the survey points lie on one line and enclose no ' +
        'area, so only the values at the points are shown.'
      : 'Surface not drawn: fewer than three points carry a value.';
  }

  /* The banded levels a filled contour is drawn at.
   *
   * contourf(levels=12) does not draw twelve bands of its own choosing: it
   * asks matplotlib's MaxNLocator for at most thirteen round numbers spanning
   * the data, then keeps the one level below the data and the one above it.
   * The colour bar is labelled with those numbers, so they are not decoration
   * - a browser that picked its own round numbers would print a different
   * scale beside the same map - and the ticker is ported here rather than
   * approximated: its step table runs 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10 times
   * a power of ten, not the shorter list its docstring suggests.
   */
  var LOCATOR_STEPS = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];

  /* ticker._staircase: the step table extended a decade either side. */
  function staircase(steps) {
    var out = [], i;
    for (i = 0; i < steps.length - 1; i += 1) out.push(steps[i] / 10);
    for (i = 0; i < steps.length; i += 1) out.push(steps[i]);
    out.push(10 * steps[1]);
    return out;
  }

  /* floor(log10(x)) without the trap Math.log10 has at exact powers of ten,
   * which formatG documents: the decimal exponent of the shortest round-trip
   * representation is the exponent, exactly. */
  function decimalExponent(value) {
    return Number(Math.abs(value).toExponential().split('e')[1]);
  }

  /* Python's divmod for floats, which is floor division and not truncation:
   * the ticker's tick indices are counted from it, and JS's % keeps the sign
   * of the dividend where Python's keeps the sign of the divisor. */
  function pyDivmod(x, step) {
    var mod = x % step;
    if (mod !== 0 && (mod < 0) !== (step < 0)) mod += step;
    var div = (x - mod) / step;
    var floordiv = 0;
    if (div !== 0) {
      floordiv = Math.floor(div);
      if (div - floordiv > 0.5) floordiv += 1;
    }
    return [floordiv, mod];
  }

  /* ticker._Edge_integer: the tick index either side of a value, with the
   * slop the ticker allows so a value already on a tick does not gain one. */
  function edgeTolerance(step, offset) {
    if (!(Math.abs(offset) > 0)) return 1e-10;
    var digits = log10Of(Math.abs(offset) / step);
    return Math.min(0.4999, Math.max(1e-10, Math.pow(10, digits - 12)));
  }

  function edgeLe(x, step, offset) {
    var parts = pyDivmod(x, step);
    if (Math.abs(parts[1] / step - 1) < edgeTolerance(step, offset)) return parts[0] + 1;
    return parts[0];
  }

  function edgeGe(x, step, offset) {
    var parts = pyDivmod(x, step);
    if (Math.abs(parts[1] / step) < edgeTolerance(step, offset)) return parts[0];
    return parts[0] + 1;
  }

  /* ticker.scale_range. */
  function locatorScaleRange(vmin, vmax, n) {
    var span = Math.abs(vmax - vmin);
    var middle = (vmax + vmin) / 2.0;
    var offset = 0.0;
    if (span > 0 && Math.abs(middle) / span >= 100) {
      offset = Math.pow(10, decimalExponent(middle));
      if (middle < 0) offset = -offset;
    }
    return [Math.pow(10, decimalExponent(span / n)), offset];
  }

  /** ticker.MaxNLocator.tick_values, for the contour's parameters: at most
   * `nbins` intervals, and one tick is enough (min_n_ticks is 1 here, where
   * an axis would want two).
   * @param {number} vmin
   * @param {number} vmax
   * @param {number} nbins
   * @param {number[]} [steps]
   * @param {number} [minTicks]
   * @returns {number[]}
   */
  function locatorTicks(vmin, vmax, nbins, steps, minTicks) {
    var table = steps || LOCATOR_STEPS;
    var wanted = minTicks === undefined ? 1 : minTicks;
    var lo = vmin, hi = vmax;
    /* transforms.nonsingular: a surface with one value everywhere still has
     * to be banded, and a zero-width range would divide by zero below */
    var biggest = Math.max(Math.abs(lo), Math.abs(hi));
    if (hi - lo <= biggest * 1e-14) {
      if (lo === 0 && hi === 0) {
        lo = -1e-13;
        hi = 1e-13;
      } else {
        lo -= 1e-13 * Math.abs(lo);
        hi += 1e-13 * Math.abs(hi);
      }
    }
    var range = locatorScaleRange(lo, hi, nbins);
    var scale = range[0], offset = range[1];
    var shiftedLo = lo - offset, shiftedHi = hi - offset;
    var scaled = staircase(table).map(function (s) { return s * scale; });
    var rawStep = (shiftedHi - shiftedLo) / nbins;
    var istep = scaled.length - 1, i;
    for (i = 0; i < scaled.length; i += 1) {
      if (scaled[i] >= rawStep) { istep = i; break; }
    }
    var ticks = [];
    for (i = istep; i >= 0; i -= 1) {
      var step = scaled[i];
      var base = pyDivmod(shiftedLo, step)[0] * step;
      var low = edgeLe(shiftedLo - base, step, offset);
      var high = edgeGe(shiftedHi - base, step, offset);
      ticks = [];
      var shown = 0, k;
      for (k = low; k <= high; k += 1) {
        var tick = k * step + base;
        ticks.push(tick);
        if (tick <= shiftedHi && tick >= shiftedLo) shown += 1;
      }
      if (shown >= wanted) break;
    }
    return ticks.map(function (tick) { return tick + offset; });
  }

  /** maps.py _format_grid: at most five or six round-numbered grid lines an
   * axis. A seven-digit northing labelled every 25 m printed nine of them on
   * top of one another, which is why the axis asks for round numbers rather
   * than an even division of the extent. An axis wants two ticks where a
   * contour is content with one.
   * @param {number} lo
   * @param {number} hi
   * @returns {number[]}
   */
  function mapGridTicks(lo, hi) {
    return locatorTicks(lo, hi, 5, [1, 2, 2.5, 5, 10], 2);
  }

  /** contour.ContourSet._autolev: the ticks trimmed to one level below the
   * data and one above, unless that leaves fewer than three, in which case
   * the whole set stands.
   * @param {number} vmin
   * @param {number} vmax
   * @param {number} [count]
   * @returns {number[]}
   */
  function contourLevels(vmin, vmax, count) {
    if (!isFinite(vmin) || !isFinite(vmax)) return [];
    var levels = locatorTicks(vmin, vmax, (count || 12) + 1, LOCATOR_STEPS, 1);
    var first = 0, last = levels.length, i;
    for (i = 0; i < levels.length; i += 1) if (levels[i] < vmin) first = i;
    for (i = 0; i < levels.length; i += 1) {
      if (levels[i] > vmax) { last = i + 1; break; }
    }
    if (last - first < 3) {
      first = 0;
      last = levels.length;
    }
    return levels.slice(first, last);
  }

  /** maps.py _extent: the padded ground the map covers.
   * @param {MapPoint[]} points
   * @param {number} [padFrac]
   * @param {number} [minPad]
   * @returns {number[]}
   */
  function mapExtent(points, padFrac, minPad) {
    var frac = padFrac === undefined ? 0.25 : padFrac;
    var floorPad = minPad === undefined ? 150.0 : minPad;
    var e = points.map(function (p) { return p.easting; });
    var n = points.map(function (p) { return p.northing; });
    var padE = Math.max((arrMax(e) - arrMin(e)) * frac, floorPad);
    var padN = Math.max((arrMax(n) - arrMin(n)) * frac, floorPad);
    var pad = Math.max(padE, padN);
    return [arrMin(e) - pad, arrMax(e) + pad, arrMin(n) - pad, arrMax(n) + pad];
  }

  /** maps.py _figsize: a figure shaped like the ground it shows. A fixed
   * height squashed a traverse three times longer than it is wide into a strip
   * a third of the figure tall, beside a colour bar that ran the full height.
   * @param {number} widthIn
   * @param {number} x0
   * @param {number} x1
   * @param {number} y0
   * @param {number} y1
   * @returns {number}
   */
  function mapFigureHeightIn(widthIn, x0, x1, y0, y1) {
    var aspect = (y1 - y0) / Math.max(x1 - x0, 1e-9);
    return Math.min(Math.max(widthIn * 0.82 * aspect + 0.9, 3.4), 6.6);
  }

  /** maps.py _format_grid's axis labels: every map says which UTM zone its
   * metres are in, because two eastings in different zones are not comparable
   * numbers.
   * @param {number|string|null} zone
   * @returns {{x: string, y: string}}
   */
  function mapAxisLabels(zone) {
    return {
      x: 'Easting (m), UTM zone ' + zone + 'N / WGS84',
      y: 'Northing (m)',
    };
  }

  /* --- the subsurface maps ------------------------------------------------ */

  /* subsurface.py subsurface_map_points: one quantity at every sounding that
   * carries a position and a value.
   *
   * Soundings without a position are dropped - they cannot be put on a map -
   * and so are those whose value the interpretation left unset, because a
   * sounding whose curve never reached basement has no depth to basement and
   * plotting a zero there would draw basement at the surface. An aquifer
   * thickness at such a sounding is kept but marked a minimum: the zone runs
   * on below the depth the sounding resolves. */
  var OPEN_ENDED_MINIMA = ['aquifer_thickness_m'];

  /**
   * @param {Interpretation[]|null} interpretations
   * @param {string} attribute
   * @param {number|null} [zone]
   * @returns {MapPoint[]}
   */
  function subsurfaceMapPoints(interpretations, attribute, zone) {
    var points = [];
    positionedSoundings(interpretations, zone).forEach(function (item) {
      var value = own(item, attribute) ? item[attribute] : null;
      if (value === null || value === undefined || !isFinite(Number(value))) return;
      points.push({
        label: item.sounding_id || 'VES',
        easting: Number(item.site_easting),
        northing: Number(item.site_northing),
        value: Number(value),
        kind: 'VES point',
        minimum: OPEN_ENDED_MINIMA.indexOf(attribute) >= 0 &&
          !!item.basement_not_resolved,
      });
    });
    return points;
  }

  /** subsurface.py bedrock_elevation_points: ground level less the depth to
   * basement, which needs both numbers at the same sounding. A survey that
   * recorded no elevations gives an empty list rather than a bedrock surface
   * at sea level, which is what subtracting a depth from nothing amounts to.
   * @param {Interpretation[]|null} interpretations
   * @param {number|null} [zone]
   * @returns {MapPoint[]}
   */
  function bedrockElevationPoints(interpretations, zone) {
    var points = [];
    positionedSoundings(interpretations, zone).forEach(function (item) {
      var ground = item.site_elevation_m;
      var depth = item.depth_to_basement_m;
      if (ground === null || ground === undefined) return;
      if (depth === null || depth === undefined) return;
      points.push({
        label: item.sounding_id || 'VES',
        easting: Number(item.site_easting),
        northing: Number(item.site_northing),
        value: Number(ground) - Number(depth),
        kind: 'VES point',
      });
    });
    return points;
  }

  /** subsurface.py _require_points, as the sentence rather than the exception.
   *
   * The reason used to be the same whatever the shortfall - "record the GPS
   * position of every sounding" - which sent the Rokel reader looking for
   * positions both soundings carried, when what they lacked was a basement
   * the curves never reached. Given the interpretations, the shortfall is
   * split into its causes: the soundings with no position, and `lacking`,
   * the caller's sentence for the positioned ones that have no value.
   * @param {MapPoint[]} points
   * @param {string} what
   * @param {number} [need]
   * @param {Interpretation[]|null} [interpretations]
   * @param {string} [lacking]
   * @returns {string|null}
   */
  function requirePointsReason(points, what, need, interpretations, lacking) {
    var wanted = need === undefined ? 3 : need;
    if (points.length >= wanted) return null;
    var reason = ('aeiou'.indexOf(what.charAt(0)) >= 0 ? 'an' : 'a') + ' ' + what +
      ' needs at least ' + wanted + ' soundings that carry both a position ' +
      'and the value; ' + points.length + ' do.';
    if (interpretations === undefined || interpretations === null) {
      return reason + ' Record the GPS position of every sounding on the field sheet.';
    }
    var total = interpretations.length;
    var placed = interpretations.filter(hasPosition).length;
    if (placed < total) {
      reason += ' ' + (total - placed) + ' of ' + total + ' soundings ' +
        (total - placed === 1 ? 'carries' : 'carry') + ' no recorded position: ' +
        'record the GPS position of every sounding on the field sheet.';
    }
    if (lacking) reason += ' ' + lacking;
    return reason;
  }

  /** subsurface.py _unresolved_basement: the positioned soundings with no
   * basement, and what that costs a map.
   * @param {Interpretation[]|null} interpretations
   * @param {string} quantity
   * @returns {string}
   */
  function unresolvedBasement(interpretations, quantity) {
    var placed = (interpretations || []).filter(hasPosition);
    var missing = placed.filter(function (item) {
      return item.depth_to_basement_m === null || item.depth_to_basement_m === undefined;
    }).length;
    if (!missing) return '';
    return missing + ' of ' + placed.length + ' positioned soundings did not reach ' +
      'basement within the depth they resolve, so they have no ' + quantity + '.';
  }

  /* The sentence a subsurface map's refusal adds for the positioned soundings
   * that carry no value: subsurface.py writes it per map. */
  function subsurfaceLacking(key, interpretations) {
    if (key === 'depth_to_bedrock') {
      return unresolvedBasement(interpretations, 'depth to bedrock');
    }
    if (key === 'bedrock_elevation') {
      var placed = (interpretations || []).filter(hasPosition);
      var unlevelled = placed.filter(function (item) {
        return item.site_elevation_m === null || item.site_elevation_m === undefined;
      }).length;
      return [
        unresolvedBasement(interpretations, 'bedrock elevation'),
        unlevelled ? unlevelled + ' of ' + placed.length + ' positioned soundings ' +
          (unlevelled === 1 ? 'carries' : 'carry') + ' no recorded ground ' +
          'elevation to take the depth from.' : '',
      ].filter(Boolean).join(' ');
    }
    return '';
  }

  /** maps.py _interpolated_map, without the drawing: the grid, the range the
   * colours span, the levels they are banded at and the value at every
   * station - or the reason the Python would have raised instead.
   *
   * options: {logScale, gridN}. gridN defaults to the Python's 220.
   * @param {MapPoint[]|null} points
   * @param {Rec} [options] logScale, gridN
   */
  function interpolatedMapData(points, options) {
    var opts = options || {};
    var valued = (points || []).filter(function (p) {
      return p && p.value !== null && p.value !== undefined;
    });
    if (valued.length < 3) {
      return {
        reason: 'Interpolated maps need at least three points with values; ' +
          'got ' + valued.length + '. Produce a site location map instead.',
      };
    }
    var e = valued.map(function (p) { return Number(p.easting); });
    var n = valued.map(function (p) { return Number(p.northing); });
    var raw = valued.map(function (p) { return Number(p.value); });
    var v = opts.logScale ? raw.map(function (value) { return log10Of(value); }) : raw;
    var pad = Math.max(Math.max(arrMax(e) - arrMin(e), arrMax(n) - arrMin(n)) *
      0.25, 100.0);
    var grid = gridFrom(arrMin(e) - pad, arrMax(e) + pad, arrMin(n) - pad,
      arrMax(n) + pad, opts.gridN || 220);
    var z = surfaceGrid(e, n, v, grid);
    var clipped = false, hull = null, note = '';
    if (z) {
      var clip = clipToSurveyedGround(z, e, n, grid);
      z = clip.z;
      clipped = clip.clipped;
      hull = clip.hull;
      note = clip.note;
    } else {
      /* a line of pegs: the values are printed at the points instead */
      note = noSurfaceNote(valued.length);
    }
    var drawn = [];
    if (z) {
      z.forEach(function (value) { if (value !== null) drawn.push(value); });
    }
    var vmin = drawn.length ? arrMin(drawn) : arrMin(v);
    var vmax = drawn.length ? arrMax(drawn) : arrMax(v);
    var levels = z ? contourLevels(vmin, vmax, 12) : [];
    grid.z = z;
    return {
      reason: null,
      points: valued.map(function (p, k) {
        var text = p.label;
        if (p.minimum) {
          /* a lower bound is said to be one beside its peg whether or not a
           * surface is drawn: the contour there is a floor, and without the
           * words it reads as the value itself */
          text += '\nat least ' + formatG(p.value, 3);
        } else if (!z) {
          /* the value is written beside the peg when no surface carries it */
          text += '\n' + formatG(opts.logScale ? Math.pow(10, v[k]) : p.value, 3);
        }
        return {
          label: p.label, easting: p.easting, northing: p.northing,
          value: p.value, plot_value: v[k], kind: p.kind || 'VES point',
          minimum: !!p.minimum, text: text,
        };
      }),
      grid: z ? grid : null,
      surface: !!z,
      clipped: clipped,
      hull: hull,
      note: note,
      log_scale: !!opts.logScale,
      range: [vmin, vmax],
      data_range: [arrMin(raw), arrMax(raw)],
      levels: levels,
      /* under a log scale the grid holds log10 values and the bar is labelled
       * with the resistivities they stand for */
      level_labels: opts.logScale ? levels.map(function (t) {
        return pyFixed(Math.pow(10, t), 0);
      }) : null,
      extent: [grid.x[0], grid.x[grid.nx - 1], grid.y[0], grid.y[grid.ny - 1]],
    };
  }

  /** subsurface.py _protective_colour.
   * @param {number|null} [conductance]
   * @returns {string}
   */
  function protectiveColour(conductance) {
    if (conductance === null || conductance === undefined) return '#BBBBBB';
    for (var k = 0; k < PROTECTIVE_CLASSES.length; k += 1) {
      if (PROTECTIVE_CLASSES[k][0] <= conductance &&
        conductance < PROTECTIVE_CLASSES[k][1]) {
        return PROTECTIVE_CLASSES[k][3];
      }
    }
    return PROTECTIVE_CLASSES[PROTECTIVE_CLASSES.length - 1][3];
  }

  /** subsurface.py protective_capacity_map, without the drawing.
   *
   * Drawn in classes rather than on a continuous ramp, because the decision
   * this map informs is categorical - is this aquifer protected enough to site
   * a borehole near a latrine or a cattle crossing - and a smooth ramp invites
   * reading a difference between 0.68 and 0.71 siemens that the method does
   * not support. Unlike the other three it draws with one point: the class of
   * a single sounding is still a finding.
   * @param {MapPoint[]|null} points
   * @param {Rec} [options] gridN
   */
  function protectiveCapacityMapData(points, options) {
    var opts = options || {};
    var valued = (points || []).filter(function (p) {
      return p && p.value !== null && p.value !== undefined;
    });
    var short = requirePointsReason(valued, 'protective capacity map', 1);
    if (short) return { reason: short };
    var bounds = PROTECTIVE_CLASSES.map(function (klass) { return klass[0]; });
    /* the top class is unbounded; a banded fill needs a finite ceiling, so use
     * the largest value on this map or the class floor, whichever is bigger */
    bounds.push(Math.max(arrMax(valued.map(function (p) { return Number(p.value); })),
      5.0) * 1.05);
    var extent = mapExtent(valued);
    var grid = gridFrom(extent[0], extent[1], extent[2], extent[3],
      opts.gridN || 200);
    var z = null, clipped = false, hull = null, note = '';
    if (valued.length >= 3) {
      var e = valued.map(function (p) { return Number(p.easting); });
      var n = valued.map(function (p) { return Number(p.northing); });
      var v = valued.map(function (p) { return Number(p.value); });
      z = surfaceGrid(e, n, v, grid);
      if (z) {
        var clip = clipToSurveyedGround(z, e, n, grid);
        z = clip.z;
        clipped = clip.clipped;
        hull = clip.hull;
        note = clip.note;
      } else {
        note = noSurfaceNote(valued.length);
      }
    }
    /* No note below three points, because the Python draws none: this map is
     * the one that draws with a single sounding, so "surface not drawn" is not
     * news there, it is the figure working as intended. The browser printed it
     * anyway, which put a red line under a two-sounding map that the package
     * leaves clean. */
    grid.z = z;
    return {
      reason: null,
      points: valued.map(function (p) {
        return {
          label: p.label, easting: p.easting, northing: p.northing,
          value: p.value, plot_value: p.value, kind: p.kind || 'VES point',
          colour: protectiveColour(p.value),
          text: p.label + '\n' + pyFixed(p.value, 2) + ' S',
        };
      }),
      grid: z ? grid : null,
      surface: !!z,
      clipped: clipped,
      hull: hull,
      note: note,
      classed: true,
      classes: PROTECTIVE_CLASSES,
      levels: bounds,
      range: [bounds[0], bounds[bounds.length - 1]],
      legend_title: 'Longitudinal conductance of the cover',
      legend: PROTECTIVE_CLASSES.map(function (klass) {
        return {
          label: klass[2] + ' (' + formatG(klass[0]) +
            (isFinite(klass[1]) ? '-' + formatG(klass[1]) + ' S)' : '+ S)'),
          colour: klass[3],
        };
      }),
      extent: extent,
    };
  }

  /* The four subsurface maps reporting/geophysical.py plans, in the order it
   * plans them. `name` is the wording that report puts in front of the reason
   * when a figure is not drawn ("depth to bedrock map: ..."), so the browser's
   * list reads the same as the Python's. */
  var SUBSURFACE_MAP_SPECS = [
    {
      key: 'depth_to_bedrock', name: 'depth to bedrock map',
      attribute: 'depth_to_basement_m', title: 'Depth to bedrock',
      cbar_label: 'Depth to bedrock (m)', cmap: 'YlOrBr',
      log_scale: false, classed: false, need: 3,
      what: 'Depth to bedrock across the surveyed ground, from the layered models.',
    },
    {
      key: 'aquifer_thickness', name: 'aquifer thickness map',
      attribute: 'aquifer_thickness_m', title: 'Interpreted aquifer thickness',
      cbar_label: 'Interpreted aquifer thickness (m)', cmap: 'GnBu',
      log_scale: false, classed: false, need: 3,
      what: 'Interpreted thickness of the weathered and fractured zone - the ' +
        'section a borehole is completed in.',
    },
    {
      key: 'bedrock_elevation', name: 'bedrock elevation map',
      attribute: null, title: 'Bedrock surface elevation',
      cbar_label: 'Bedrock surface elevation (m)', cmap: 'terrain',
      log_scale: false, classed: false, need: 3,
      what: 'The bedrock surface as a landform, from the ground elevation ' +
        'recorded at each sounding less its depth to basement. A low in this ' +
        'surface is a buried valley, which basement groundwater drains towards.',
    },
    {
      key: 'protective_capacity', name: 'protective capacity map',
      attribute: 'protective_conductance_s', title: 'Aquifer protective capacity',
      /* no colour bar: this map is drawn in classes, and its key is the
       * legend protectiveCapacityMapData carries */
      cbar_label: null, cmap: null,
      log_scale: false, classed: true, need: 1,
      what: 'Protective capacity of the cover over the aquifer, from the ' +
        'longitudinal conductance of the overlying layers. It rates how well ' +
        'the ground above the aquifer resists downward contamination; it says ' +
        'nothing about yield.',
    },
  ];

  /** reporting/geophysical.py _subsurface_caption: a subsurface map's caption,
   * written from what the map shows. The captions were fixed strings, and
   * "the surface is blanked outside the hull of the soundings" sat under a
   * figure of three collinear soundings that said on its own face "surface
   * not drawn".
   * @param {string} what
   * @param {MapPoint[]} points
   * @returns {{caption: string, surface: boolean}}
   */
  function subsurfaceCaption(what, points) {
    var surface = points.length >= 3 && pointsEncloseAnArea(
      points.map(function (p) { return Number(p.easting); }),
      points.map(function (p) { return Number(p.northing); }));
    var caption = what;
    if (surface) {
      caption += ' The surface is interpolated between the soundings and ' +
        'blanked outside the ground they enclose.';
    } else if (points.length >= 3) {
      caption += ' The soundings lie on one line and enclose no area, so no ' +
        'surface is drawn; the values are printed at the points.';
    } else {
      caption += ' With fewer than three soundings no surface is drawn; each ' +
        'point is coloured by its class.';
    }
    var minima = points.filter(function (p) { return p.minimum; })
      .map(function (p) { return p.label; });
    if (minima.length) {
      caption += ' The value at ' + minima.join(', ') + ' is a minimum, labelled ' +
        '"at least": the sounding did not resolve the base of the zone there.';
    }
    return { caption: caption, surface: surface };
  }

  /**
   * @param {string} key
   * @returns {Rec|null}
   */
  function subsurfaceMapSpec(key) {
    var found = null;
    SUBSURFACE_MAP_SPECS.forEach(function (spec) {
      if (spec.key === key) found = spec;
    });
    return found;
  }

  /** One of the four maps: its points, its surface and its strings, or the
   * reason the Python would have refused to draw it. The refusal is kept per
   * figure, the way the report keeps it: a survey whose curves never reached
   * basement has no depth-to-bedrock map but still has an aquifer thickness
   * map, and one that recorded no elevations has both but no bedrock surface.
   * @param {Interpretation[]|null} interpretations
   * @param {string} key
   * @param {Rec} [options] zone, gridN
   */
  function subsurfaceMapData(interpretations, key, options) {
    var spec = subsurfaceMapSpec(key);
    if (!spec) return { key: key, reason: 'no such subsurface map: ' + key };
    var all = interpretations || [];
    /* every point in the zone the map is labelled in */
    var zone = (options && options.zone !== undefined) ? options.zone : null;
    var points = spec.key === 'bedrock_elevation'
      ? bedrockElevationPoints(all, zone)
      : subsurfaceMapPoints(all, spec.attribute, zone);
    var head = {
      key: spec.key, name: spec.name, title: spec.title,
      cbar_label: spec.cbar_label, cmap: spec.cmap,
      log_scale: spec.log_scale, classed: spec.classed, points: points,
    };
    /* every interpretation, positioned or not, so a refusal can say which
     * soundings lack a position and which lack the value */
    var reason = requirePointsReason(points, spec.name, spec.need, all,
      subsurfaceLacking(spec.key, all));
    /* aquifer_thickness_map: contours through lower bounds were drawn as
     * though they were the thickness, and a reader reads the colour, not the
     * footnote */
    if (!reason && spec.key === 'aquifer_thickness' &&
        points.every(function (p) { return p.minimum; })) {
      reason = 'the water-bearing zone at every one of the ' + points.length +
        ' positioned soundings continues below the depth the sounding resolves, ' +
        'so each thickness is only a minimum; a surface contoured through minima ' +
        'reads as the thickness itself, so none is drawn';
    }
    if (reason) return Object.assign(head, { reason: reason });
    var data = spec.classed
      ? protectiveCapacityMapData(points, options)
      : interpolatedMapData(points, Object.assign({}, options || {},
        { logScale: spec.log_scale }));
    var told = subsurfaceCaption(spec.what, points);
    return Object.assign(head, data, { caption: told.caption, surface_said: told.surface });
  }

  /** reporting/geophysical.py _add_subsurface_figures' own gate, which comes
   * before any of the four maps and before the section: with fewer than two
   * positioned soundings the whole section of the report is skipped - no
   * figure, and no "not drawn" line either, because a survey that recorded one
   * GPS position has nothing to say about the ground between soundings. The
   * protective capacity map is the one that draws from a single sounding, so a
   * report that does not ask this first prints one under a heading the package
   * never writes at all.
   * @param {Interpretation[]|null} interpretations
   * @returns {boolean}
   */
  function subsurfaceFiguresApply(interpretations) {
    return positionedSoundings(interpretations).length >= 2;
  }

  /** All four, in the report's order, each either drawable or carrying its
   * reason. The caller draws the ones with no reason and lists the others as
   * "<name>: <reason>", which is what _add_subsurface_figures does - after
   * subsurfaceFiguresApply, which decides whether the section is written.
   * @param {Interpretation[]|null} interpretations
   * @param {Rec} [options]
   */
  function subsurfaceMapSet(interpretations, options) {
    return SUBSURFACE_MAP_SPECS.map(function (spec) {
      return subsurfaceMapData(interpretations, spec.key, options);
    });
  }

  /* --- the drill-target suitability map ------------------------------------ */

  /** siting/suitability.py suitability_map_points: the scored points that can
   * go on a map, valued by the number the ranking was decided on.
   *
   * A point with no recorded position is dropped rather than placed at a
   * guess. The value is the confidence-weighted score, so the colours on the
   * map and the order in the ranked table cannot tell two different stories
   * about which peg to drill. Every point is in the zone `zone` (by default
   * the first placed point's): a survey on the 28N/29N boundary records its
   * soundings in both, and a map that subtracted the two sets of eastings drew
   * 400 m of ground 660 km wide.
   * @param {Rec[]|null} results what assessSiting returns
   * @param {number|null} [zone]
   * @returns {MapPoint[]}
   */
  function suitabilityMapPoints(results, zone) {
    var points = [], target = (zone === undefined) ? null : zone;
    (results || []).forEach(function (result) {
      if (!result) return;
      if (result.easting === null || result.easting === undefined) return;
      if (result.northing === null || result.northing === undefined) return;
      if (target === null) target = inferZoneForSierraLeone(Number(result.easting));
      var moved = toZone(result.easting, result.northing, target);
      var confidence = (result.confidence === null || result.confidence === undefined)
        ? 1.0 : Number(result.confidence);
      points.push({
        label: String(result.sounding_id),
        easting: moved[0],
        northing: moved[1],
        /* SitingSuitability.weighted, rounded where the Python rounds it */
        value: pyRound(Number(result.suitability) * confidence, 1),
        /* the grade of the suitability before the confidence discount, the
         * one the ranked table prints; the label names it as that grade
         * rather than pairing it with the weighted score, which it does not
         * grade */
        kind: result.grade,
        rank: (result.rank === undefined) ? null : result.rank,
      });
    });
    return points;
  }

  /** The valued points in rank order: what maps.py reads the recommended
   * target and the runner-up off. A point carrying no rank was never ranked
   * and is left out rather than sorted to the front, which is what
   * `if p.rank is not None` does in the Python.
   * @param {MapPoint[]|null} points
   * @returns {MapPoint[]}
   */
  function rankedMapPoints(points) {
    return (points || []).filter(function (p) {
      return p && p.value !== null && p.value !== undefined &&
        p.rank !== null && p.rank !== undefined;
    }).map(function (p, k) {
      return { point: p, index: k };
    }).sort(function (a, b) {
      return a.point.rank - b.point.rank || a.index - b.index;
    }).map(function (entry) {
      return entry.point;
    });
  }

  /** maps.py _suitability_ranking: what the ranking lets a suitability map say
   * about which peg to drill.
   *
   * `tie` is the ranking's own verdict on its two leaders, rankingTie() on
   * the project's ranking_tie_points. The map used to decide it again, three
   * points apart on the rounded values it prints, and a project with a
   * different tie margin got a report calling two points indistinguishable
   * over a map that starred one of them. Left unset it is decided here by
   * the same rule on the points' values, and only between the points ranked
   * first and second.
   *
   * `ranking` is every scored sounding in rank order, placed or not. A
   * recommended point with no recorded position is not on the map at all:
   * the caption used to promise a star over a map with no star on it, naming
   * the runner-up as the target. Left unset, every ranked point is taken to
   * be on the map.
   * @param {MapPoint[]|null} points
   * @param {boolean|null} [tie] what rankingTie decided; decided here when not given
   * @param {string[]|null} [ranking] every scored sounding's label in rank order
   */
  function suitabilityRanking(points, tie, ranking) {
    var ranked = rankedMapPoints(points);
    var order = ranking || ranked.map(function (p) { return p.label; });
    var tied = tie;
    if (tied === undefined || tied === null) {
      /* the gap to the tenth of a point, as tiedLeaders takes it: 64.1 less
       * 61.1 is 2.999999999999993 in doubles, not under 3 */
      tied = ranked.length >= 2 && ranked[0].rank === 1 && ranked[1].rank === 2 &&
        pyRound(Math.abs(Number(ranked[0].value) - Number(ranked[1].value)), 1) <
        defaultConfig().ves.ranking_tie_points;
    }
    tied = !!tied;
    var leaders = order.slice(0, tied ? 2 : 1);
    var onMap = {};
    (points || []).forEach(function (p) { if (p) onMap[p.label] = true; });
    var unplaced = leaders.filter(function (label) { return !own(onMap, label); });
    return {
      tie: tied,
      leaders: leaders,
      unplaced: unplaced,
      recommended: leaders.length && !tied && !unplaced.length ? leaders[0] : null,
    };
  }

  /** maps.py unplaced_text: the sentence a map owes its reader for a leading
   * point it cannot show.
   * @param {string[]} unplaced
   * @param {string} [where]
   * @returns {string}
   */
  function unplacedText(unplaced, where) {
    var on = where || 'this map';
    if (!unplaced.length) return '';
    if (unplaced.length === 1) {
      return unplaced[0] + ' has no recorded position and is not on ' + on + '.';
    }
    return unplaced.join(' and ') + ' have no recorded position and are not on ' +
      on + '.';
  }

  /** maps.py suitability_map_note: the line across the top of a suitability
   * map that has no star.
   * @param {Rec} verdict what suitabilityRanking returns
   * @returns {string}
   */
  function suitabilityMapNote(verdict) {
    if (verdict.tie) {
      var note = verdict.leaders[0] + ' and ' + verdict.leaders[1] + ' are ' +
        'indistinguishable on geophysical grounds; choose between them on ' +
        'access and sanitary distances.';
      if (verdict.unplaced.length) note += ' ' + unplacedText(verdict.unplaced);
      return note;
    }
    if (verdict.unplaced.length) {
      return 'The recommended point, ' + verdict.unplaced[0] + ', has no ' +
        'recorded position and is not on this map.';
    }
    return '';
  }

  /** maps.py suitability_label: what a suitability map writes beside a point.
   * The rank and the weighted score, and the grade named as the grade of the
   * suitability ("38 - Very good" paired a weighted 38 with the grade of a
   * suitability of 75); the grid coordinates too at the recommended target.
   * `compact` is the label of a map too dense for every label in full: the
   * grade line gives way, except at the recommended target.
   * @param {MapPoint} p
   * @param {boolean} [recommended]
   * @param {boolean} [compact]
   * @returns {string}
   */
  function suitabilityLabel(p, recommended, compact) {
    var text = p.label;
    if (p.value !== null && p.value !== undefined) {
      text += '\n' + (p.rank !== null && p.rank !== undefined
        ? 'Rank ' + p.rank + ', ' : '') + 'weighted ' + pyFixed(p.value, 0);
      if (recommended || !compact) text += '\n' + p.kind + ' suitability';
    }
    if (recommended) {
      text += '\nE ' + pyFixed(p.easting, 0) + '  N ' + pyFixed(p.northing, 0);
    }
    return text;
  }

  /** maps.py suitability_map_state: what a suitability map of these points
   * will show, for its caption.
   *
   * A caption used to promise "the interpolated surface is blanked outside
   * the ground the survey covered" over a figure of two dots with no surface
   * on it at all, and "the star is the recommended target" over a map whose
   * recommended point had no position and so no star. The rules are the
   * figure's, so the report asks for them here instead of restating them and
   * drifting. `tie` and `ranking` are the ones the map is drawn with.
   * @param {MapPoint[]|null} points
   * @param {boolean|null} [tie]
   * @param {string[]|null} [ranking]
   */
  function suitabilityMapState(points, tie, ranking) {
    var valued = (points || []).filter(function (p) {
      return p && p.value !== null && p.value !== undefined;
    });
    var e = valued.map(function (p) { return Number(p.easting); });
    var n = valued.map(function (p) { return Number(p.northing); });
    return Object.assign({
      n_points: valued.length,
      surface: valued.length >= 3 && pointsEncloseAnArea(e, n),
    }, suitabilityRanking(points, tie, ranking));
  }

  var SUITABILITY_MAP_CAPTION = 'Drill-target suitability of the surveyed ' +
    'points, coloured by the confidence-weighted score; greener is more ' +
    'suitable. Each point is labelled with its rank and weighted score, and, ' +
    'where the map has room, with the grade of its suitability before the ' +
    'confidence discount, as in the table above.';

  /** reporting/geophysical.py _suitability_block's caption.
   *
   * Each clause is a claim about the figure underneath it: that a star marks
   * the target, or that no star does because the two best points cannot be
   * separated or the best has no position; that the colour between the pegs
   * is interpolated ground, or that there is no colour between them at all.
   * Written from anything but the state the figure was drawn from, a caption
   * promises a reader something the figure does not show, and the reader
   * believes the caption.
   * @param {Rec} state what suitabilityMapState returns
   * @returns {string}
   */
  function suitabilityMapCaption(state) {
    var caption = SUITABILITY_MAP_CAPTION;
    var unplaced = state.unplaced || [];
    if (state.tie) {
      caption += ' The two highest-ranked points cannot be told apart on ' +
        'geophysical grounds, so neither is starred.';
      if (unplaced.length) caption += ' ' + unplacedText(unplaced, 'the map');
    } else if (state.recommended) {
      caption += ' The star is the recommended target, ' + state.recommended +
        ', with its grid coordinates.';
    } else if (unplaced.length) {
      caption += ' The recommended target, ' + unplaced[0] + ', has no recorded ' +
        'position and is not on the map, so no point is starred.';
    }
    if (state.surface) {
      caption += ' The surface between the points is interpolated and blanked ' +
        'outside the ground they enclose.';
    } else if (state.n_points >= 3) {
      caption += ' The points lie on one line and enclose no area, so no ' +
        'surface is interpolated between them.';
    }
    return caption;
  }

  /** maps.py suitability_map without the drawing, plus the caption the report
   * earns from it: the scored pegs, the interpolated surface where the survey
   * supports one, the star on the recommended target and the words that go
   * under the figure.
   *
   * Returns null where reporting/geophysical.py draws no map at all - no
   * scored point, or no scored point carrying a position - because there the
   * Python adds no figure and no line saying one is missing. The subsurface
   * maps list their refusals; this one is silent, and a browser that printed
   * "drill-target map: ..." under this heading would be inventing a sentence
   * the package never writes.
   *
   * options: {results, ves, zone, gridN}. `results` is an assessSiting()
   * scorecard the caller has already built, so the map and the ranked table
   * are scored once and cannot disagree; `ves` is the VESConfig used when it
   * has to score them here, and whose ranking_tie_points decides the tie, as
   * rankingTie() decides it for the text: the map used to pin its own three
   * points on rounded values. `zone` is the zone every point is drawn in,
   * by default the first positioned sounding's.
   * @param {Interpretation[]|null} interpretations
   * @param {Rec} [options] results, ves, zone, gridN
   */
  function suitabilityMapData(interpretations, options) {
    var opts = options || {};
    var ves = opts.ves || defaultConfig().ves;
    var results = opts.results || assessSiting(interpretations, ves);
    if (!results.length) return null;
    var zone = (opts.zone === null || opts.zone === undefined)
      ? surveyZone(interpretations) : opts.zone;
    var points = suitabilityMapPoints(results, zone);
    if (!points.length) return null;
    if (zone === null) zone = inferZoneForSierraLeone(Number(points[0].easting));
    var valued = points.filter(function (p) {
      return p.value !== null && p.value !== undefined;
    });
    var ranking = results.slice().sort(function (a, b) {
      return (a.rank || 99) - (b.rank || 99);
    }).map(function (r) { return String(r.sounding_id); });
    var state = suitabilityMapState(points,
      rankingTie(results, ves.ranking_tie_points) !== '', ranking);
    /* _extent(points), over every point and not only the valued ones: a peg
     * that could not be scored was still surveyed, and a map that frames it
     * out has lost a station the reader walked to. */
    var extent = mapExtent(points);
    var grid = null, clipped = false, hull = null, note = '';
    if (valued.length >= 3) {
      var e = valued.map(function (p) { return Number(p.easting); });
      var n = valued.map(function (p) { return Number(p.northing); });
      var v = valued.map(function (p) { return Number(p.value); });
      /* the surface is gridded over the axes, which are the padded extent,
       * so it fills the frame the way contourf fills the Python's */
      var candidate = gridFrom(extent[0], extent[1], extent[2], extent[3],
        opts.gridN || 200);
      var z = surfaceGrid(e, n, v, candidate);
      if (z) {
        var clip = clipToSurveyedGround(z, e, n, candidate);
        candidate.z = clip.z;
        clipped = clip.clipped;
        hull = clip.hull;
        note = clip.note;
        grid = candidate;
      } else {
        note = noSurfaceNote(valued.length);
      }
    }
    /* Below three valued points there is no note, because the Python writes
     * none: a two-point survey has nothing to interpolate and saying
     * "surface not drawn" over two dots reads as a failure rather than as
     * the figure working as intended. */
    var tie = state.tie;
    var drawn = points.map(function (p) {
      /* the star is the point of this map - somebody walks to that peg and
       * not to the other one - so it is drawn only where the ranking can
       * carry it, and a tie takes it off both points rather than giving it
       * to whichever sorted first */
      var recommended = p.rank === 1 && !tie;
      return {
        label: p.label, easting: p.easting, northing: p.northing,
        value: (p.value === undefined) ? null : p.value, kind: p.kind,
        rank: p.rank, recommended: recommended,
        text: suitabilityLabel(p, recommended, false),
        compact_text: suitabilityLabel(p, recommended, true),
      };
    });
    var seen = {}, legend = [];
    drawn.forEach(function (p) {
      var label = p.recommended ? 'recommended drill target' : 'surveyed point';
      if (own(seen, label)) return;
      seen[label] = true;
      /* the value of the point that registered the entry, so the key can be
       * drawn in that peg's own colour the way a matplotlib legend handle
       * carries the marker it was taken from */
      legend.push({
        label: label, kind: p.recommended ? 'star' : 'circle', value: p.value,
      });
    });
    return {
      reason: null,
      title: 'Drill-target suitability',
      cbar_label: 'Drilling suitability, confidence weighted (0-100)',
      cmap: 'RdYlGn',
      points: drawn,
      legend: legend,
      state: state,
      caption: suitabilityMapCaption(state),
      tie: tie,
      /* said on the figure as well as in the caption, because a reader who
       * sees the pegs and no star has to be told why there is no star: two
       * points the ranking cannot separate, or a recommended point with no
       * position to draw it at */
      tie_note: suitabilityMapNote(state),
      grid: grid,
      surface: !!grid,
      clipped: clipped,
      hull: hull,
      note: note,
      /* np.linspace(0, 100, 11), with vmin and vmax pinned to the ends of the
       * score: the colour of a peg means the same thing on every survey's
       * map, which a scale stretched to each survey's own range would not */
      levels: linspace(0.0, 100.0, 11),
      range: [0.0, 100.0],
      extent: extent,
      zone: zone,
    };
  }

  /* --- the ground surface along the traverse ------------------------------- */

  var GROUND_PROFILE_CAPTION = 'Ground surface along the survey traverse, ' +
    'from the elevation recorded at each sounding.';

  /** reporting/geophysical.py _ground_profile_figure's filter: the soundings
   * that carry a position and a recorded ground level. A position without a
   * level has no height to draw and a level without a position has no
   * chainage to draw it at.
   * @param {Interpretation[]|null} interpretations
   * @returns {Interpretation[]}
   */
  function levelledSoundings(interpretations) {
    return positionedSoundings(interpretations).filter(function (item) {
      return item.site_elevation_m !== null && item.site_elevation_m !== undefined;
    });
  }

  /** ves/plots.py model_depth_m: the depth a figure of one sounding's model is
   * drawn to - the depth of investigation, or deeper where a fitted interface
   * lies below it, because the model shown has to be the model fitted. The
   * curve's model panel ran past the depth of investigation for that reason
   * while the layer column stopped there, so a basement at 61 m under a 50 m
   * depth of investigation was on one figure and not the other, both
   * captioned as drawn to 50 m; the browser's panel used a third rule. One
   * rule now serves every figure of a sounding in both engines.
   * @param {LayeredModel|null} model
   * @param {number|null} [investigationDepthM]
   * @returns {number}
   */
  function modelDepthM(model, investigationDepthM) {
    var tops = (model && model.depths_top) || [];
    var deepest = model && model.n_layers > 1 ? Number(tops[tops.length - 1]) : 0.0;
    return Math.max(Number(investigationDepthM) || 0.0, deepest * 1.2 + 2.0);
  }

  /** reporting/geophysical.py _drawn_depth_text: how deep a figure of one
   * sounding's model is drawn, for its caption.
   * @param {LayeredModel|null} model
   * @param {number|null} [investigationDepthM]
   * @returns {string}
   */
  function drawnDepthText(model, investigationDepthM) {
    var doi = Number(investigationDepthM) || 0.0;
    var drawn = modelDepthM(model, doi);
    if (drawn <= doi) return 'to the depth of investigation (' + fmtNum(doi) + ' m)';
    return 'to ' + fmtNum(drawn) + ' m so that the deepest fitted interface stays ' +
      'on it; the red line marks the depth of investigation (' + fmtNum(doi) +
      ' m), below which the readings do not resolve the model';
  }

  /** reporting/geophysical.py _study_area_caption: the study-area caption,
   * worded from what was overlaid on the map. It used to promise the survey
   * points and a star on the recommended point whatever the map held: over a
   * map with no sounding on it, over a recommended point with no recorded
   * position, and over two points the ranking calls indistinguishable, one of
   * which carried the star. `marked` are the soundings drawn on the map.
   * @param {string} community
   * @param {string[]} marked the soundings drawn on the map
   * @param {string} preferred the recommended point, or ""
   * @param {string[]} leaders
   * @param {boolean} tie
   * @returns {string}
   */
  function studyAreaCaption(community, marked, preferred, leaders, tie) {
    if (!marked.length) {
      return 'Study area at ' + community + ', with its location in Sierra Leone ' +
        'inset. No sounding carries a recorded GPS position, so none is marked on it.';
    }
    var caption = 'Study area at ' + community + ', with the survey points and ' +
      'its location in Sierra Leone inset.';
    if (tie && leaders.length >= 2) {
      caption += ' ' + leaders[0] + ' and ' + leaders[1] + ' cannot be told apart ' +
        'on geophysical grounds, so neither is starred.';
      var missing = leaders.slice(0, 2).filter(function (label) {
        return marked.indexOf(label) < 0;
      });
      if (missing.length) caption += ' ' + unplacedText(missing, 'the map');
    } else if (marked.indexOf(preferred) >= 0) {
      caption += ' The star is the recommended drilling point, ' + preferred + '.';
    } else {
      caption += ' The recommended drilling point, ' + preferred + ', has no ' +
        'recorded position and is not on the map.';
    }
    return caption;
  }

  /** subsurface.py ground_profile_state, and mapping/terrain.py
   * plot_ground_profile as reporting/geophysical.py _ground_profile_figure
   * calls it: the land surface along the traverse, from the survey's own
   * levels, against chainage, under the rules the section follows.
   *
   * Returns null where the Python says nothing - fewer than two soundings
   * carry a position and a level, so there is no profile to be missing - and
   * {reason} where it refuses and lists the refusal among what was not drawn:
   * a traverse that cannot be placed, or levels that are all further apart
   * than CORRELATION_REACH_MULTIPLE times the depth the soundings resolve.
   * Rokel's two levels, 20.7 km apart, were joined by a straight 71 to 68 m
   * slope that the section beside it refused to draw.
   *
   * Every positioned sounding is a station, levelled or not. Only the
   * levelled ones used to be handed over, so a station nobody levelled
   * vanished and the "N of M stations recorded no elevation" note could never
   * be printed. `runs` are the stations the line may join: a gap wider than
   * the reach starts a new run, and no line or fill crosses it.
   * @param {Interpretation[]|null} interpretations
   */
  function groundProfileData(interpretations) {
    var all = interpretations || [];
    if (levelledSoundings(all).length < 2) return null;
    var profile = traverseProfile(all);
    if (profile.reason) return { reason: profile.reason };
    var placed = profile.indices.map(function (k) { return all[k]; });
    var elevation = placed.map(function (item) {
      var value = item.site_elevation_m;
      if (value === null || value === undefined || !isFinite(Number(value))) return null;
      return Number(value);
    });
    var reaches = placed.map(function (item) {
      return Number(item.investigation_depth_m || 0.0);
    });
    var reach = reaches.length ? Math.max(arrMax(reaches), 0.0) : 0.0;
    var maxGap = reach > 0 ? reach * CORRELATION_REACH_MULTIPLE : null;
    var levelled = [];
    profile.labels.forEach(function (label, k) {
      if (elevation[k] !== null) levelled.push([label, profile.chainage_m[k], k]);
    });
    var gaps = [];
    for (var g = 1; g < levelled.length; g += 1) {
      gaps.push([levelled[g - 1][0], levelled[g][0],
        levelled[g][1] - levelled[g - 1][1], g]);
    }
    var openGaps = gaps.filter(function (gap) {
      return maxGap !== null && gap[2] > maxGap;
    });
    if (levelled.length < 2) {
      return {
        reason: levelled.length + ' of ' + placed.length + ' stations carry an ' +
          'elevation. A ground profile needs at least two levelled points; ' +
          'record them on the field sheet.',
      };
    }
    if (openGaps.length === gaps.length) {
      var widest = arrMax(gaps.map(function (gap) { return gap[2]; }));
      return {
        reason: 'the levelled stations are ' + commaFixed0(widest) + ' m apart, ' +
          'about ' + pyFixed(widest / reach, 0) + ' times the ' + commaFixed0(reach) +
          ' m the soundings resolve; a ground line between them would be a ' +
          'straight slope across ground nobody levelled, so none is drawn',
      };
    }
    var runs = [[levelled[0][2]]];
    gaps.forEach(function (gap) {
      if (maxGap !== null && gap[2] > maxGap) runs.push([]);
      runs[runs.length - 1].push(levelled[gap[3]][2]);
    });
    var known = elevation.filter(function (value) { return value !== null; });
    var missing = elevation.length - known.length;
    var stations = profile.labels.map(function (label, k) {
      return {
        label: label,
        chainage_m: profile.chainage_m[k],
        elevation_m: elevation[k],
      };
    });
    var notes = [];
    if (missing) {
      notes.push(missing + ' of ' + elevation.length + ' stations recorded no ' +
        'elevation and are not drawn.');
    }
    if (openGaps.length) {
      notes.push('The line is not drawn across ' + openGaps.map(function (gap) {
        return (gap[0] || 'station') + ' to ' + (gap[1] || 'station') + ' (' +
          commaFixed0(gap[2]) + ' m)';
      }).join('; ') + ': nothing was levelled between those stations.');
    }
    var caption = GROUND_PROFILE_CAPTION;
    if (missing) {
      caption += ' ' + missing + ' of ' + stations.length + ' stations recorded no ' +
        'elevation and are not drawn.';
    }
    if (openGaps.length) {
      caption += ' The line is not drawn across gaps wider than ' +
        commaFixed0(maxGap) + ' m, where nothing was levelled between the stations.';
    }
    return {
      reason: null,
      title: 'Ground surface along the survey traverse',
      x_label: 'Distance along traverse (m)',
      y_label: 'Elevation (m)',
      series_label: 'Levelled at the station',
      caption: caption,
      labels: profile.labels,
      chainage_m: profile.chainage_m,
      elevation_m: elevation,
      stations: stations,
      max_gap_m: maxGap,
      open_gaps: openGaps.map(function (gap) { return [gap[0], gap[1], gap[2]]; }),
      /* station indices, each run a line of its own */
      runs: runs,
      /* fill_between drops to nanmin(elevation) - 2.0: the ground is drawn as
       * a solid, not as a line floating on the axis, and the base is below
       * the lowest level so the lowest station is not drawn on the floor */
      baseline_m: arrMin(known) - 2.0,
      /* a station with no level, and a gap the line does not cross, are both
       * said on the figure: without the words the straight line reads as a
       * slope somebody levelled */
      note: notes.join(' '),
    };
  }

  Object.assign(C, {
    PROTECTIVE_CLASSES: PROTECTIVE_CLASSES,
    SUBSURFACE_CREDIT: SUBSURFACE_CREDIT,
    CORRELATION_REACH_MULTIPLE: CORRELATION_REACH_MULTIPLE,
    COLLINEAR_STRAIGHTNESS: COLLINEAR_STRAIGHTNESS,
    SUBSURFACE_MAP_SPECS: SUBSURFACE_MAP_SPECS,
    subsurfaceMapSpec: subsurfaceMapSpec,
    pointsEncloseAnArea: pointsEncloseAnArea,
    singularValues2: singularValues2, principalAxis: principalAxis,
    traverseProfile: traverseProfile, bearingText: bearingText, wideGaps: wideGaps,
    correlationNote: correlationNote, rhoColourRange: rhoColourRange,
    geoelectricSectionGeometry: geoelectricSectionGeometry,
    pseudosectionGeometry: pseudosectionGeometry,
    delaunayTriangles: delaunayTriangles, convexHull: convexHull,
    pointInPolygon: pointInPolygon, surfaceGrid: surfaceGrid,
    clipToSurveyedGround: clipToSurveyedGround, noSurfaceNote: noSurfaceNote,
    contourLevels: contourLevels, locatorTicks: locatorTicks,
    mapGridTicks: mapGridTicks, gridFrom: gridFrom, linspace: linspace,
    mapExtent: mapExtent, mapFigureHeightIn: mapFigureHeightIn,
    mapAxisLabels: mapAxisLabels,
    subsurfaceMapPoints: subsurfaceMapPoints,
    bedrockElevationPoints: bedrockElevationPoints,
    requirePointsReason: requirePointsReason,
    interpolatedMapData: interpolatedMapData,
    protectiveCapacityMapData: protectiveCapacityMapData,
    protectiveColour: protectiveColour,
    subsurfaceMapData: subsurfaceMapData, subsurfaceMapSet: subsurfaceMapSet,
    subsurfaceFiguresApply: subsurfaceFiguresApply,
    subsurfaceCaption: subsurfaceCaption, unresolvedBasement: unresolvedBasement,
    COINCIDENT_STATION_M: COINCIDENT_STATION_M,
    toZone: toZone, surveyZone: surveyZone, positionedSoundings: positionedSoundings,
    spacingName: spacingName, spacingNote: spacingNote,
    pseudosectionCaption: pseudosectionCaption,
    modelDepthM: modelDepthM, drawnDepthText: drawnDepthText,
    studyAreaCaption: studyAreaCaption,
    SUITABILITY_MAP_CAPTION: SUITABILITY_MAP_CAPTION,
    GROUND_PROFILE_CAPTION: GROUND_PROFILE_CAPTION,
    suitabilityMapPoints: suitabilityMapPoints,
    rankedMapPoints: rankedMapPoints,
    suitabilityRanking: suitabilityRanking, unplacedText: unplacedText,
    suitabilityMapNote: suitabilityMapNote,
    suitabilityMapState: suitabilityMapState, suitabilityLabel: suitabilityLabel,
    suitabilityMapCaption: suitabilityMapCaption,
    suitabilityMapData: suitabilityMapData,
    levelledSoundings: levelledSoundings,
    groundProfileData: groundProfileData,
  });

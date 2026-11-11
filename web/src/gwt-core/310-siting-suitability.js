
  /* ================================================================== siting
   * groundwater/siting/suitability.py. A transparent drill-target scorecard.
   *
   * Each candidate VES point is scored 0-100 from four components a siting
   * hydrogeologist weighs in crystalline basement terrain: interpreted aquifer
   * thickness, how central the water-zone resistivity sits in the productive
   * window, the weathered profile, and whether a fracture sits at the basement
   * contact. The weights are explicit (the VES configuration's
   * suitability_weights, from defaults.json) and a defensible default, not a
   * calibrated model; a calibration set (PLAN.md step 5.3) fits them against
   * the boreholes drilled and puts its own in force once a named person
   * adopts it.
   */

  var THICKNESS_TARGET_M = 25.0;

  /**
   * @param {number} score
   * @returns {string}
   */
  function suitabilityGrade(score) {
    if (score >= 75) return 'Very good';
    if (score >= 55) return 'Good';
    if (score >= 35) return 'Moderate';
    return 'Poor';
  }

  /** siting/suitability.py _water_zone_rho: the thickness-weighted geometric
   * mean resistivity of the water-bearing layers inside the water zones, or
   * null where there are none. Only the water-bearing layers: the zones are
   * rounded to whole metres, so every layer inside a zone took in the slice
   * of dry layer or basement the rounding added, and a 150 ohm-m layer from
   * 5.4 to 14.6 m read 189 ohm-m and ranked behind the same layer from 5.6
   * to 14.4 m. The odds read the water-zone resistivity through this too.
   * The logarithms are relative to the first such layer's resistivity, so a
   * zone of one resistivity reads exactly it.
   * @param {Interpretation} interp
   * @returns {number|null}
   */
  function waterZoneRho(interp) {
    var reference = 0.0, acc = 0.0, total = 0.0;
    interp.water_zones.forEach(function (zone) {
      var top = zone[0], bottom = zone[1];
      interp.layers.forEach(function (layer) {
        if (!layer.water_bearing) return;
        var lo = Math.max(layer.top_m, top);
        var hi = Math.min(isFinite(layer.bottom_m) ? layer.bottom_m : bottom, bottom);
        if (hi > lo) {
          if (total === 0.0) reference = layer.rho;
          acc += Math.log(layer.rho / reference) * (hi - lo);
          total += hi - lo;
        }
      });
    });
    return total > 0 ? reference * Math.exp(acc / total) : null;
  }

  function resistivityFitScore(interp, vesConfig) {
    var mid = waterZoneRho(interp);
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
    var openEnded = !!interp.basement_not_resolved;
    parts.push((openEnded
      ? 'at least ' + pyFixed(interp.aquifer_thickness_m, 0) +
        ' m of interpreted water-bearing thickness, the base of the zone being ' +
        'below the depth the sounding resolves'
      : 'about ' + pyFixed(interp.aquifer_thickness_m, 0) +
        ' m of interpreted water-bearing thickness') +
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
      /* pyFixed, not toFixed: a basement top at 2.5 m is "about 2 m" in the
       * package (half to even) and toFixed printed "about 3 m" */
      parts.push('overburden of about ' + pyFixed(interp.depth_to_basement_m, 0) +
        ' m that limits the target');
    }
    var text = 'Driven by ' + parts.join('; ') + '.';
    var confidence = interp.confidence === undefined ? 1.0 : interp.confidence;
    if (confidence < 1.0) {
      var reasons = [];
      if ((interp.fit_quality || 'ok') !== 'ok') {
        reasons.push('a model fit of ' + pyFixed(interp.fit_error_percent, 1) +
          ' percent (ERR)');
      }
      if (openEnded) reasons.push('a basement the sounding did not reach');
      text += ' Confidence ' + pyFixed(confidence, 2) + ': ' + reasons.join(' and ') +
        ' discount the score before ranking.';
    }
    return text;
  }

  /* A weighted score, or a difference of two, to the 0.0001 it is exact to:
   * _exact. A score to 0.1 times a confidence to 0.001 is a multiple of
   * 0.0001, but in doubles not always the one nearest it (32.0 x 0.85 is
   * 27.2 and 34.0 x 0.8 is 27.200000000000003), so equal scores were ranked
   * by a last bit rather than by sounding id. */
  function weightedExact(weighted) { return pyRound(weighted, 4); }

  /* How far the first point's weighted score is ahead of the second's: _gap */
  function weightedGap(first, second) {
    return weightedExact(first.suitability * first.confidence -
      second.suitability * second.confidence);
  }

  /** siting/suitability.py tied_leaders: the two highest-ranked points when the
   * ranking cannot separate them, else null. One test for the tie sentence,
   * the preference table's "=1st" and the report's summary and conclusions,
   * decided on the gap between the confidence-weighted scores to the tenth
   * of a point the tie sentence prints it to: 64.1 less 61.1 is
   * 2.999999999999993 in doubles and 2.96 prints as 3.0, and both were
   * called "ahead by 3.0 points, within the 3-point margin".
   * @param {Rec[]} results what assessSiting returns
   * @param {number} [withinPoints]
   * @returns {Rec[]|null}
   */
  function tiedLeaders(results, withinPoints) {
    var within = withinPoints === undefined ? 3.0 : withinPoints;
    var ranked = results.slice().sort(function (a, b) {
      return (a.rank === null || a.rank === undefined ? 99 : a.rank) -
        (b.rank === null || b.rank === undefined ? 99 : b.rank);
    });
    if (ranked.length < 2) return null;
    var first = ranked[0], second = ranked[1];
    if (pyRound(Math.abs(weightedGap(first, second)), 1) >= within) return null;
    return [first, second];
  }

  /** One sentence when the top two points cannot be told apart; '' otherwise.
   * @param {Rec[]} results what assessSiting returns
   * @param {number} [withinPoints]
   * @returns {string}
   */
  function rankingTie(results, withinPoints) {
    var within = withinPoints === undefined ? 3.0 : withinPoints;
    var pair = tiedLeaders(results, within);
    if (!pair) return '';
    var first = pair[0], second = pair[1];
    var w1 = first.suitability * first.confidence, w2 = second.suitability * second.confidence;
    /* "by name only" is true only of equal scores; said of 82.3 against 79.5
     * it told the client the order was alphabetical when it was not */
    var gap = weightedGap(first, second);
    var order = gap === 0
      ? first.sounding_id + ' is listed first by name only'
      : first.sounding_id + ' is ahead by ' +
        (pyRound(gap, 1) >= 0.1 ? pyFixed(gap, 1) : 'less than 0.1') +
        ' points, within the ' + formatG(within) + '-point margin the ranking ' +
        'cannot separate';
    return 'Points ' + first.sounding_id + ' and ' + second.sounding_id +
      ' are indistinguishable on geophysical grounds (confidence-weighted suitability ' +
      pyFixed(w1, 1) + ' and ' + pyFixed(w2, 1) + '); ' + order + ', and the choice ' +
      'between them should be made on access, sanitary distances and the ' +
      'community\'s preference.';
  }

  /** siting/suitability.py suitability_verdict: the paragraph under the
   * suitability table, the target or the tie. A tie gives both points'
   * rationale, since the reader is being asked to choose between them.
   * @param {Rec[]|null} results what assessSiting returns
   * @param {number} [withinPoints]
   * @returns {string}
   */
  function suitabilityVerdict(results, withinPoints) {
    if (!results || !results.length) return '';
    var tie = rankingTie(results, withinPoints);
    if (tie) {
      return [tie].concat(/** @type {Rec[]} */ (tiedLeaders(results, withinPoints)).map(function (r) {
        return 'Point ' + r.sounding_id + ': ' + r.rationale;
      })).join(' ');
    }
    var best = results.slice().sort(function (a, b) {
      return (a.rank === null || a.rank === undefined ? 99 : a.rank) -
        (b.rank === null || b.rank === undefined ? 99 : b.rank);
    })[0];
    return 'Point ' + best.sounding_id + ' ranks first (suitability ' +
      pyFixed(best.suitability, 0) + ' out of 100, ' + best.grade.toLowerCase() +
      ', confidence ' + pyFixed(best.confidence, 2) + ') and is the recommended ' +
      'drilling target. ' + best.rationale;
  }

  /** Score and rank candidate VES points, most suitable first (rank 1 = best),
   * so the head of the list is the recommended drilling target.
   * @param {Interpretation[]|null} interpretations
   * @param {VesConfig} [vesConfig]
   * @returns {Rec[]}
   */
  function assessSiting(interpretations, vesConfig) {
    var cfg = vesConfig || defaultConfig().ves;
    /** @type {Rec[]} */
    var results = (interpretations || []).map(function (interp, index) {
      var comp = {
        aquifer_thickness: Math.min(interp.aquifer_thickness_m / THICKNESS_TARGET_M, 1.0),
        resistivity_fit: resistivityFitScore(interp, cfg),
        overburden: overburdenScore(interp),
        basal_fracture: basalFractureScore(interp),
      };
      var weights = cfg.suitability_weights;
      var score = 100.0 * (
        weights.aquifer_thickness * comp.aquifer_thickness +
        weights.resistivity_fit * comp.resistivity_fit +
        weights.overburden * comp.overburden +
        weights.basal_fracture * comp.basal_fracture);
      return {
        sounding_id: interp.sounding_id,
        suitability: pyRound(score, 1),
        grade: suitabilityGrade(score),
        components: comp,
        rationale: suitabilityRationale(interp, comp),
        easting: interp.site_easting, northing: interp.site_northing,
        rank: null,
        confidence: pyRound(interp.confidence === undefined ? 1.0 : interp.confidence, 3),
        /* where the interpretation stood in the list given: a page pairs the
         * row with what else it worked out for the point by this, not by
         * the sounding id, which a sheet copied without renumbering repeats */
        index: index,
      };
    });
    /* rank on the confidence-weighted score, highest first, compared to the
     * 0.0001 it is exact to; equal scores are ranked by sounding id, and a
     * tie is said in words by rankingTie() */
    var ranked = results.slice().sort(function (a, b) {
      return weightedExact(b.suitability * b.confidence) -
        weightedExact(a.suitability * a.confidence) ||
        (a.sounding_id < b.sounding_id ? -1 : a.sounding_id > b.sounding_id ? 1 : 0);
    });
    ranked.forEach(function (result, i) { result.rank = i + 1; });
    return ranked;
  }

  Object.assign(C, {
    assessSiting: assessSiting,
    suitabilityGrade: suitabilityGrade, waterZoneRho: waterZoneRho,
    rankingTie: rankingTie, tiedLeaders: tiedLeaders,
    suitabilityVerdict: suitabilityVerdict,
  });

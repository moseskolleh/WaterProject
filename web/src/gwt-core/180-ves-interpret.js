
  /* ==================================================== interpretation rules
   * groundwater/ves/interpret.py. Targets crystalline basement terrain: a
   * lateritic or clayey cover, saprolite, a weathered/fractured zone that
   * forms the main aquifer, and fresh basement at depth.
   */

  /* The top few metres are taken as unsaturated: a water zone starts no
   * shallower than this (interpret.py VADOSE_M). */
  var VADOSE_M = 3.0;

  /* Whether a layer below the top is conductive ground: one the rules read as
   * water-bearing or clay-rich weathered ground, rather than as compact or dry
   * rock or basement - under both the top of the water-bearing window and the
   * fresh basement edge (interpret.py _conductive). */
  function isConductive(rho, cfg) {
    return rho < cfg.fractured_zone_rho[1] && rho < cfg.fresh_basement_min_rho;
  }

  /* For each layer, whether any deeper layer is conductive ground. */
  function conductiveBelow(rho, cfg) {
    var out = [], seen = false;
    for (var i = rho.length - 1; i >= 0; i--) {
      out[i] = seen;
      seen = seen || isConductive(rho[i], cfg);
    }
    return out;
  }

  /* interpret.py basement_top: the top of fresh basement, or null. Fresh
   * basement is resistive ground with no conductive ground beneath it in the
   * fitted model: the first layer below the surface that reaches the fresh
   * basement edge with nothing conductive under it, else a half-space of
   * 800 ohm-m or more. A layer that reaches the edge over conductive ground
   * is a resistive cover (a duricrust or a dry layer), not bedrock; it used
   * to be taken as basement whatever lay below. The interpretation and the
   * range of models (rangeSummary) both read it from here. */
  function basementTop(rho, tops, cfg) {
    var below = conductiveBelow(rho, cfg);
    for (var i = 0; i < rho.length; i++) {
      if (rho[i] >= cfg.fresh_basement_min_rho && tops[i] > 0 && !below[i]) return tops[i];
    }
    if (rho[rho.length - 1] >= cfg.fractured_zone_rho[1]) return tops[rho.length - 1];
    return null;
  }

  /* overConductive: whether conductive ground lies anywhere below the layer;
   * a layer as resistive as fresh basement over it is a resistive cover. */
  function unitLabel(rho, isTop, isBottom, cfg, overConductive) {
    var hi = cfg.fractured_zone_rho[1];
    if (isTop) {
      if (rho >= cfg.laterite_min_rho) return ['dry lateritic topsoil / duricrust', false];
      if (rho >= hi) return ['compact laterite / dry overburden', false];
      if (rho <= cfg.clay_max_rho) return ['clayey topsoil', false];
      return ['topsoil / laterite', false];
    }
    if (rho >= cfg.fresh_basement_min_rho) {
      if (overConductive) return [phrase('ves.unit_resistive_cover'), false];
      return ['fresh basement', false];
    }
    if (rho >= hi) {
      if (isBottom) {
        return ['slightly weathered or fractured bedrock (limited water potential)', false];
      }
      return ['compact or dry weathered rock (regolith)', false];
    }
    if (rho <= cfg.clay_max_rho) return ['clay rich saprolite (low permeability)', false];
    if (isBottom) {
      /* A conductive half-space is the weathered zone the sounding did not
       * get to the bottom of, not fractured bedrock: fractured fresh basement
       * is hundreds to thousands of ohm-m. */
      return ['weathered or fractured zone, potentially water bearing when ' +
        'saturated; its base is not resolved within the depth of investigation', true];
    }
    return ['weathered / fractured zone, potentially water bearing when saturated', true];
  }

  /** How deep a sounding with this largest AB/2 actually resolves: one rule
   * for the interpretation, every figure and the drilling-depth cap.
   * @param {number} maxSpacing
   * @param {VesConfig} [cfg]
   * @returns {number}
   */
  function depthOfInvestigation(maxSpacing, cfg) {
    var c = cfg || defaultConfig().ves;
    return maxSpacing * c.depth_of_investigation_factor;
  }

  /** 1.0 at or under the target misfit, falling linearly to the floor at the
   * unreliable level and staying there.
   * @param {number|null} [err]
   * @param {VesConfig} [cfg]
   * @returns {number}
   */
  function fitConfidence(err, cfg) {
    var c = cfg || defaultConfig().ves;
    if (err === null || err === undefined) return 1.0;
    var target = c.target_fit_percent;
    var unreliable = Math.max(c.unreliable_fit_percent, target + 1e-9);
    if (err <= target) return 1.0;
    var frac = Math.min((err - target) / (unreliable - target), 1.0);
    return 1.0 - (1.0 - c.fit_confidence_floor) * frac;
  }

  /** "8 m to 40 m", or open-ended "8 m to at least 40 m".
   * @param {number} top
   * @param {number} bottom
   * @param {boolean} [openEnded]
   * @returns {string}
   */
  function zoneText(top, bottom, openEnded) {
    return openEnded
      ? Math.trunc(top) + ' m to at least ' + Math.trunc(bottom) + ' m'
      : Math.trunc(top) + ' m to ' + Math.trunc(bottom) + ' m';
  }

  /**
   * @param {number} top
   * @param {number} bottom
   * @param {boolean} [openEnded]
   * @returns {string}
   */
  function zoneCell(top, bottom, openEnded) {
    return Math.trunc(top) + '-' + Math.trunc(bottom) + (openEnded ? '+' : '');
  }

  /**
   * @param {Interpretation} interp
   * @param {number[]} zone [top, bottom]
   * @returns {boolean}
   */
  function zoneIsOpen(interp, zone) {
    var last = interp.water_zones[interp.water_zones.length - 1];
    return !!interp.basement_not_resolved && last && zone[0] === last[0] && zone[1] === last[1];
  }

  /**
   * @param {Interpretation} interp
   * @returns {string}
   */
  function drillingDepthText(interp) {
    var depth = pyFixed(interp.max_drilling_depth_m, 0) + ' m';
    var minimum = interp.basement_not_resolved || interp.drilling_depth_capped;
    return (minimum ? 'at least ' : 'about ') + depth;
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

  /**
   * @param {Sounding|null} sounding
   * @param {LayeredModel} model
   * @param {Config} [config]
   * @returns {Interpretation}
   */
  function interpretModel(sounding, model, config) {
    var cfg = (config || defaultConfig()).ves;
    var rho = model.resistivities;
    var tops = model.depths_top, bottoms = model.depths_bottom;
    var n = model.n_layers, i;

    var investigation, maxSpacing = null;
    /* the spacings the inversion actually fitted: a reading it dropped (a
     * zero or a blank resistivity) extends no depth the model was fitted to */
    var used = (sounding && sounding.ab2 && sounding.ab2.length)
      ? inversionReadings(sounding).ab2 : [];
    if (used.length) {
      maxSpacing = arrMax(used);
      investigation = depthOfInvestigation(maxSpacing, cfg);
    } else if (n > 1) {
      investigation = bottoms[n - 2] * 2 + 20;
    } else {
      /* A bare half space with no sounding carries no depth scale at all;
       * zero is the honest answer - nothing was resolved, nothing recommended. */
      investigation = 0.0;
    }

    var layers = [];
    var below = conductiveBelow(rho, cfg);
    for (i = 0; i < n; i++) {
      var labelled = unitLabel(rho[i], i === 0, i === n - 1, cfg, below[i]);
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

    /* water zones: the top few metres are vadose, so a zone starts at 3 m.
     * A layer whose modelled base lies below the depth of investigation is
     * open-ended there, as the half-space is: the model put that base where
     * no reading reaches. A water-bearing layer that starts at or below the
     * depth of investigation was never seen at all, so it is no zone, and
     * the narrative says so. One that starts above it, on a sounding too
     * short to see below the vadose allowance, is no zone either, but does
     * not lie below the depth of investigation. */
    var zones = [];
    var basementNotResolved = false;
    var openBase = null, unseenTops = [], vadoseTops = [];
    layers.forEach(function (layer) {
      if (!layer.water_bearing) return;
      var top = Math.max(layer.top_m, VADOSE_M);
      if (top >= investigation) {
        (layer.top_m >= investigation ? unseenTops : vadoseTops).push(layer.top_m);
        return;
      }
      var bottom = Math.min(layer.bottom_m, investigation);
      if (layer.bottom_m > investigation) {
        basementNotResolved = bottom - top >= 1.0;
        openBase = layer.bottom_m;
      }
      if (bottom - top >= 1.0) {
        /* each end rounded half to even, but never to a zone of no
         * thickness: 3.5 to 4.5 m came out "4 m to 4 m", an aquifer of 0 m */
        var zTop = pyRound(top);
        zones.push([zTop, Math.max(pyRound(bottom), zTop + 1)]);
      }
    });
    zones.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var merged = [];
    zones.forEach(function (zone) {
      var last = merged[merged.length - 1];
      if (last && zone[0] <= last[1] + 1) last[1] = Math.max(last[1], zone[1]);
      else merged.push([zone[0], zone[1]]);
    });
    zones = merged;

    /* resistive ground with nothing conductive below it (basementTop); a layer
     * as resistive as basement over conductive ground is a cover */
    var depthToBasement = basementTop(rho, tops, cfg);
    var covers = layers.filter(function (layer, k) {
      return layer.number > 1 && below[k] && layer.rho >= cfg.fresh_basement_min_rho;
    }).map(function (layer) { return layer.number; });
    /* a basement top below the depth of investigation is where the model
     * happened to put it, not a depth the sounding measured */
    var bedrockUnseen = depthToBasement !== null && depthToBasement > investigation;
    if (bedrockUnseen) depthToBasement = null;

    var aquiferThickness = zones.reduce(function (a, z) { return a + (z[1] - z[0]); }, 0);

    /* Recommended maximum drilling depth: deepest target zone plus a margin,
     * never past the depth the sounding actually investigated. Round up to the
     * step and re-apply the cap - rounding after the cap could push the
     * recommendation past the resolved depth. */
    var deepest = zones.length
      ? zones[zones.length - 1][1] + cfg.max_drilling_margin_m
      : investigation;
    /* a depth cut back to the depth of investigation is a minimum, and says
     * so, rather than reading as an estimate */
    var drillingDepthCapped = deepest > investigation;
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

    /* The misfit and the unresolved basement discount the score before any
     * ranking reads it. */
    var err = model.fit_error_percent === undefined ? null : model.fit_error_percent;
    var confidence = fitConfidence(err, cfg);
    if (basementNotResolved) confidence *= cfg.unresolved_basement_confidence;
    score *= confidence;

    var sid = model.sounding_id || (sounding ? sounding.sounding_id : '') || '';
    var flags = [];
    var fitQuality = 'ok';
    if (err !== null && err > cfg.target_fit_percent) {
      var unreliable = err > cfg.unreliable_fit_percent;
      fitQuality = unreliable ? 'unreliable' : 'poor';
      flags.push({ level: 'warning', code: 'poor_fit',
        message: 'The layered model reproduces the readings to ' + pyFixed(err, 1) +
          ' percent (ERR), above the ' + formatG(cfg.target_fit_percent) +
          ' percent target' +
          (unreliable
            ? '; the model does not describe the curve and the layer depths are indicative only.'
            : '; treat the layer depths as approximate.'),
        context: sid });
    }
    if (basementNotResolved) {
      var where = (openBase === null || !isFinite(openBase))
        ? 'is the half-space: the sounding did not reach its base within the ' +
          pyFixed(investigation, 0) + ' m it resolves'
        : 'continues below the ' + pyFixed(investigation, 0) + ' m the sounding ' +
          'resolves: the model puts its base at ' + fmtNum(openBase) + ' m, deeper ' +
          'than the readings reach';
      flags.push({ level: 'info', code: 'basement_not_resolved',
        message: 'The deepest water-bearing layer ' + where + ', so the zone is ' +
          'open-ended, the aquifer thickness is a minimum and the drilling depth ' +
          'is a minimum.',
        context: sid });
    }

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
      flags: flags,
      basement_not_resolved: basementNotResolved,
      drilling_depth_capped: drillingDepthCapped,
      confidence: confidence,
      fit_error_percent: err,
      fit_quality: fitQuality,
      max_spacing_m: maxSpacing,
    };
    interp.narrative = interpretationNarrative(interp, unseenTops, bedrockUnseen,
      vadoseTops, covers);
    return interp;
  }

  /* groundwater/utils.py fmt_num / round_sig / ordinal. Report prose is
   * compared against the Python output character for character, so the
   * thousands separators and the %g fallback have to match exactly. */

  /* |x| * 10^d rounded half to even, worked out exactly, as a BigInt. x is
   * m * 2^k with m and k read from its bits, so nothing is rounded before
   * the one rounding asked for, which is how Python rounds. The decimal
   * text JavaScript offers is itself rounded, and a tail it shows as a tie
   * need not be one: 1.05 is 1.0500000000000000444, which Python rounds to
   * 1.1, but to seventeen digits it reads 1.0500000000000000, and half to
   * even on that made it 1.0 here - and 0.155, just under its tie, 0.16. */
  function exactScaledRound(x, d) {
    var view = new DataView(new ArrayBuffer(8));
    view.setFloat64(0, Math.abs(x));
    var hi = view.getUint32(0), lo = view.getUint32(4);
    var biased = (hi >>> 20) & 0x7ff;
    var m = BigInt(hi & 0xfffff) * BigInt(4294967296) + BigInt(lo);
    var k = -1074;                            // a subnormal
    if (biased) { m += BigInt(4503599627370496); k = biased - 1075; }
    var num = m, den = BigInt(1), fives = BigInt(1);
    for (var i = 0; i < Math.abs(d); i++) fives *= BigInt(5);
    if (d >= 0) num *= fives; else den *= fives;
    if (k + d >= 0) num <<= BigInt(k + d); else den <<= BigInt(-(k + d));
    var q = num / den;
    var twice = (num - q * den) * BigInt(2);
    if (twice > den || (twice === den && q % BigInt(2) === BigInt(1))) q += BigInt(1);
    return q;
  }

  /* |x| rounded exactly to d decimal places (d < 0 rounds to tens,
   * hundreds...), as decimal text. */
  function exactFixedText(x, d) {
    var digits = exactScaledRound(x, d).toString();
    if (d <= 0) return digits === '0' ? '0' : digits + '0'.repeat(-d);
    while (digits.length <= d) digits = '0' + digits;
    return digits.slice(0, -d) + '.' + digits.slice(-d);
  }

  /** Python's "%.Nf": correctly rounded with half-to-even on the exact binary
   * value. Number.prototype.toFixed rounds a tie away from zero instead, so
   * a cost of exactly $150.5/m printed as $151 here and $150 in the package,
   * and the difference reached the downloadable site brief. It is written
   * from the exact value, as Python writes it, so it agrees where toFixed
   * cannot too: "-0" for a negative that rounds to nothing, every digit of
   * a number from 1e21 up, and nan and inf.
   * @param {number} x
   * @param {number} [digits]
   * @returns {string}
   */
  function pyFixed(x, digits) {
    var d = digits || 0;
    var v = Number(x);
    if (v !== v) return 'nan';
    if (!isFinite(v)) return v > 0 ? 'inf' : '-inf';
    var sign = v < 0 || Object.is(v, -0) ? '-' : '';
    /* Within fifteen digits the rounded double prints back as exactly the
     * decimal it was rounded to, and that is three times quicker. */
    if (d <= 15 && Math.abs(v) < 1e15 / Math.pow(10, d)) {
      return sign + Math.abs(pyRound(v, d)).toFixed(d);
    }
    return sign + exactFixedText(v, d);
  }

  /** Python's round(): half goes to even, not away from zero. It governs the
   * water-zone bounds and every fmt_num, so the two implementations disagree
   * on exact halves unless this is used.
   * @param {number} x
   * @param {number} [digits]
   * @returns {number}
   */
  function pyRound(x, digits) {
    var d = digits || 0;
    if (!isFinite(x)) return x;
    /* The usual case is decided on the decimal expansion, which is quick:
     * seventeen significant digits identify a double, and a tail below the
     * cut that does not read as 5 followed by zeros says which way the real
     * value lies, since the real value is within half a unit of the last
     * of those digits. A tail that reads as a tie, a cut too deep for the
     * kept digits to stay an exact integer, a negative cut and a number
     * written with an exponent are rounded on the exact value instead, and
     * read back from the decimal text, as Python reads it back. */
    var text = Math.abs(x).toPrecision(17);
    if (d >= 0 && d <= 22 && text.indexOf('e') < 0) {
      var dot = text.indexOf('.');
      var whole = dot < 0 ? text : text.slice(0, dot);
      var fraction = dot < 0 ? '' : text.slice(dot + 1);
      while (fraction.length < d) fraction += '0';
      var kept = whole + fraction.slice(0, d);
      var tail = fraction.slice(d);
      if (kept.length <= 15 && !/^50*$/.test(tail)) {
        var r = Number(kept) + ((tail && tail.charAt(0) >= '5') ? 1 : 0);
        return (x < 0 ? -r : r) / Math.pow(10, d);
      }
    }
    return Number((x < 0 ? '-' : '') + exactFixedText(x, d));
  }

  /**
   * @param {number} value
   * @param {number} [sig]
   * @returns {number}
   */
  function roundSig(value, sig) {
    if (value === 0 || !isFinite(value)) return value;
    var exp = Number(Math.abs(value).toExponential().split('e')[1]);
    /* Python's round(), not Math.round(): the two disagree on every tie, and
     * a tie is not rare in a table of measurements. fmtNum runs on this, so
     * the disagreement reached the text of the reports. */
    return pyRound(value, (sig || 3) - 1 - exp);
  }

  /** Python's "%g": 6 significant digits, trailing zeros stripped, exponential
   * when the exponent falls below -4 or reaches the precision.
   * @param {number} value
   * @param {number} [precision]
   * @returns {string}
   */
  function formatG(value, precision) {
    var p = precision || 6;
    /* written as Python writes them, sign of a zero included */
    if (value === 0) return Object.is(value, -0) ? '-0' : '0';
    if (value !== value) return 'nan';
    if (!isFinite(value)) return value > 0 ? 'inf' : '-inf';
    /* A subnormal is not put through roundSig: snapping its p-digit decimal
     * back to the nearest subnormal double can cross into the decade below
     * (1.000004e-318 came back as 9.99999e-319). Its exact value has
     * hundreds of significant digits, so toExponential's rounding half up
     * meets no tie, and gives Python's half-even digits. */
    var rounded = Math.abs(value) < 2.2250738585072014e-308 ? value : roundSig(value, p);
    /* Not Math.log10: in V8 Math.log(1e6)/Math.LN10 is 5.999999999999999, so
     * the exponent came out one too low at exact powers of ten and %g chose
     * the fixed form where Python chooses the exponential one. The decimal
     * string carries the exponent exactly; the mantissa and the exponent
     * are both taken from the one p-digit string, because a subnormal's
     * shortest form can lie a decade away from it (the double 1e-320 is
     * 9.99989e-321 to six digits, as Python writes it). */
    var parts = rounded.toExponential(p - 1).split('e');
    var exp = Number(parts[1]);
    if (exp < -4 || exp >= p) {
      /* the mantissa's digits as toExponential writes them, rather than
       * rounded / 10^exp, which is Infinity below 1e-308 */
      var mstr = parts[0].replace(/0+$/, '').replace(/\.$/, '');
      return mstr + 'e' + (exp < 0 ? '-' : '+') +
        String(Math.abs(exp)).padStart(2, '0');
    }
    var out = rounded.toFixed(Math.max(0, p - 1 - exp));
    if (out.indexOf('.') >= 0) out = out.replace(/0+$/, '').replace(/\.$/, '');
    return out;
  }

  /** Python's "%.2e": the exponent is padded to at least two digits, which
   * toExponential does not do.
   * @param {number} value
   * @param {number} [digits]
   * @returns {string}
   */
  function expo(value, digits) {
    var text = Number(value).toExponential(digits === undefined ? 2 : digits);
    return text.replace(/e([+-])(\d)$/, 'e$10$2');
  }

  /**
   * @param {number|null|undefined} value anything else is 'n/a' too
   * @param {number} [sig]
   * @param {string} [unit]
   * @returns {string}
   */
  function fmtNum(value, sig, unit) {
    if (value === null || value === undefined || typeof value !== 'number' ||
        !isFinite(value)) {
      return 'n/a';
    }
    var v = roundSig(value, sig === undefined ? 3 : sig);
    var text;
    if (Math.abs(v - Math.round(v)) < 1e-9 && Math.abs(v) < 1e15) {
      text = (pyRound(v) || 0).toLocaleString('en-US');      // an int: never -0
    } else {
      text = formatG(v);
    }
    return unit ? (text + ' ' + unit).trim() : text;
  }

  /**
   * @param {number|null|undefined} a
   * @param {number|null|undefined} b
   * @param {string} [unit]
   * @param {string} [sep]
   * @returns {string}
   */
  function fmtRange(a, b, unit, sep) {
    return (fmtNum(a) + (sep === undefined ? '-' : sep) + fmtNum(b) + ' ' +
      (unit === undefined ? 'm' : unit)).trim();
  }

  /**
   * @param {number|null} [n]
   * @returns {string}
   */
  function ordinal(n) {
    if (n === null || n === undefined) return '';
    var v = n % 100;
    var suffix = (v >= 10 && v <= 20) ? 'th'
      : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
    return String(n) + suffix;
  }

  /** groundwater/utils.py plural / plural_noun. "1 point", "2 points": the
   * noun agrees with the count. Readiness gates and flags printed "2 step(s)
   * with discharge" and "1 lithological interval(s)", which is a form, not a
   * sentence, and the browser has to say what the package says character for
   * character. The third argument carries a plural that is not just +"s"
   * ("series", "analyses"), as the Python helpers' plural_form does.
   * @param {number} count
   * @param {string} singular
   * @param {string} [pluralForm]
   * @returns {string}
   */
  function plural(count, singular, pluralForm) {
    return String(count) + ' ' + pluralNoun(count, singular, pluralForm);
  }

  /** The noun alone, agreeing with a count the sentence already carries.
   * @param {number} count
   * @param {string} singular
   * @param {string} [pluralForm]
   * @returns {string}
   */
  function pluralNoun(count, singular, pluralForm) {
    return count === 1 ? singular : (pluralForm || singular + 's');
  }

  /* --- the shared words ---------------------------------------------------
   * groundwater/text.py. A sentence both engines write is kept once, in
   * src/groundwater/data/text/*.yaml, which the build emits as
   * GWT.data.text; this is the same renderer as render_text there, rule for
   * rule, and the grammar is documented with it. A number always names its
   * format, because String(5.0) is "5" here and str(5.0) is "5.0" there. */
  var TEXT_TOKEN = new RegExp('\\{\\{|\\}\\}' +
    '|\\{([a-z_][a-z0-9_]*)(?::(num|g|\\.\\d+f|plural:[^{}|]*\\|[^{}|]*))?\\}' +
    '|[{}]', 'g');

  function formatTextValue(name, spec, value) {
    if (spec === undefined) {
      if (typeof value !== 'string') {
        throw new TypeError('text: {' + name + '} takes a string; a number ' +
          'names its format, as {' + name + ':num}');
      }
      return value;
    }
    if (spec.indexOf('plural:') === 0) {
      if (typeof value !== 'number' || !Number.isInteger(value)) {
        throw new TypeError('text: {' + name + ':plural:...} takes a whole count');
      }
      var forms = spec.slice('plural:'.length).split('|');
      return value === 1 ? forms[0] : forms[1];
    }
    if (typeof value !== 'number' && !(spec === 'num' && value === null)) {
      throw new TypeError('text: {' + name + ':' + spec + '} takes a number, not ' +
        JSON.stringify(value));
    }
    if (spec === 'num') return fmtNum(value);
    if (spec === 'g') return formatG(value);
    return pyFixed(value, Number(spec.slice(1, -1)));
  }

  /**
   * @param {string} template
   * @param {Record<string, *>} [values]
   * @returns {string}
   */
  function renderText(template, values) {
    values = values || {};
    var used = {};
    var text = template.replace(TEXT_TOKEN, function (token, name, spec) {
      if (token === '{{' || token === '}}') return token.charAt(0);
      if (name === undefined) {
        throw new Error('text: a lone ' + JSON.stringify(token) + ' in ' +
          JSON.stringify(template) + '; write ' + token + token);
      }
      if (!own(values, name)) {
        throw new Error('text: no value for {' + name + '} in ' + JSON.stringify(template));
      }
      used[name] = true;
      return formatTextValue(name, spec, values[name]);
    });
    var unused = Object.keys(values).filter(function (k) { return !used[k]; });
    if (unused.length) {
      throw new Error('text: ' + JSON.stringify(unused.sort()) + ' are not in ' +
        JSON.stringify(template));
    }
    return text;
  }

  function textEntry(id) {
    var dot = id.indexOf('.');
    var file = ((GWT.data || {}).text || {})[id.slice(0, dot)];
    if (dot < 0 || !file || !own(file, id.slice(dot + 1))) {
      throw new Error('text: no entry ' + JSON.stringify(id) + ' in data/text ' +
        '(is gwt-data.js loaded, and current?)');
    }
    return file[id.slice(dot + 1)];
  }

  /** The sentence id names, with values filled in.
   * @param {string} id
   * @param {Record<string, *>} [values]
   * @returns {string}
   */
  function phrase(id, values) {
    var template = textEntry(id);
    if (typeof template !== 'string') {
      throw new TypeError('text: ' + JSON.stringify(id) + ' is a table; read it with phraseTable');
    }
    return renderText(template, values);
  }

  /** The table id names: literal text, keyed by a value from the data.
   * @param {string} id
   * @returns {Record<string, *>}
   */
  function phraseTable(id) {
    var table = textEntry(id);
    if (typeof table !== 'object' || table === null) {
      throw new TypeError('text: ' + JSON.stringify(id) + ' is a sentence; read it with phrase');
    }
    return table;
  }

  /* ves/interpret.py POORLY_RESOLVED_FACTOR / poorly_resolved_boundaries:
   * [depth, factor] of each boundary whose thickness is known only to within
   * a factor of 2 or worse; empty for a model with no uncertainty. */
  var POORLY_RESOLVED_FACTOR = 2.0;

  /**
   * @param {LayeredModel} model
   * @returns {number[][]}
   */
  function poorlyResolvedBoundaries(model) {
    var factors = model.h_uncertainty_factor;
    if (!factors) return [];
    var out = [];
    Array.prototype.forEach.call(factors, function (f, i) {
      if (f >= POORLY_RESOLVED_FACTOR) out.push([model.depths_bottom[i], f]);
    });
    return out;
  }

  /** "a", "a and b", "a, b and c"
   * @param {string[]} items
   * @returns {string}
   */
  function andJoin(items) {
    return items.length === 1 ? items[0]
      : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
  }

  /* vadoseTops: the tops of the water-bearing layers a sounding too short to
   * see below the vadose allowance does not count; covers: the numbers of the
   * layers as resistive as fresh basement over conductive ground. */
  function interpretationNarrative(interp, unseenTops, bedrockUnseen, vadoseTops, covers) {
    var curve = describeCurveType(interp.curve_type);
    /* "resolves a 3 layer subsurface" over a boundary known only to x/ 3.7
     * claimed a layer the curve does not settle */
    var weak = poorlyResolvedBoundaries(interp.model);
    var opening = weak.length
      ? 'The data at ' + interp.sounding_id + ' are fitted with a ' +
        interp.model.n_layers + ' layer model (' + curve + '), though the ' +
        (weak.length === 1 ? 'boundary' : 'boundaries') + ' at ' +
        andJoin(weak.map(function (w) { return fmtNum(w[0]) + ' m'; })) + ' ' +
        (weak.length === 1 ? 'is' : 'are') + ' poorly resolved, so the layer ' +
        'count is uncertain.'
      : 'The data at ' + interp.sounding_id + ' resolves a ' +
        interp.model.n_layers + ' layer subsurface (' + curve + ').';
    var parts = [opening];
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
        return zoneText(z[0], z[1], zoneIsOpen(interp, z));
      }).join(', ');
      parts.push('The unusually low resistivity within the interpreted fractured ' +
        'or weathered intervals is indicative of pore electrolyte, possibly ' +
        'groundwater. The possible water zones are ' + zonesText + '.');
      if (interp.basement_not_resolved) {
        parts.push('The base of the deepest zone is not resolved: the sounding sees ' +
          'to about ' + fmtNum(interp.investigation_depth_m) + ' m, and the ' +
          'conductive ground continues below that.');
      }
    } else {
      parts.push('No clearly water bearing low resistivity zone is resolved at ' +
        'this point within the investigated depth.');
    }
    if (unseenTops && unseenTops.length) {
      parts.push(phrase('ves.unseen_layers', { n: unseenTops.length,
        tops: andJoin(unseenTops.map(function (t) { return fmtNum(t) + ' m'; })),
        doi: interp.investigation_depth_m }));
    }
    if (vadoseTops && vadoseTops.length) {
      parts.push(phrase('ves.vadose_layers', { n: vadoseTops.length,
        tops: andJoin(vadoseTops.map(function (t) { return fmtNum(t) + ' m'; })),
        vadose: VADOSE_M, doi: interp.investigation_depth_m }));
    }
    if (interp.fit_error_percent !== null && interp.fit_error_percent !== undefined) {
      if (interp.fit_quality === 'unreliable') {
        parts.push('The model reproduces the readings to ' +
          fmtNum(interp.fit_error_percent, 3) + ' percent (ERR), well above the ' +
          'target: it does not describe the curve closely, and the layer depths ' +
          'are indicative only.');
      } else if (interp.fit_quality === 'poor') {
        parts.push('The model reproduces the readings to ' +
          fmtNum(interp.fit_error_percent, 3) + ' percent (ERR), above the ' +
          'target, so the layer depths are approximate.');
      }
    }
    if (covers && covers.length) {
      parts.push(phrase('ves.resistive_cover', { n: covers.length,
        layers: andJoin(covers.map(function (k) { return String(k); })) }));
    }
    if (interp.depth_to_basement_m !== null) {
      parts.push('The depth to bedrock is estimated at about ' +
        fmtNum(interp.depth_to_basement_m) + ' m.');
    } else if (bedrockUnseen) {
      parts.push('The depth to bedrock is not resolved within the depth of ' +
        'investigation (about ' + fmtNum(interp.investigation_depth_m) + ' m).');
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
  /** The one number the points are ranked on: the suitability scorecard's
   * geological score discounted by the interpretation's confidence, so the
   * preference table, the summary and the suitability section agree.
   * @param {Interpretation} interp
   * @param {VesConfig} [cfg]
   * @returns {number}
   */
  function rankingWeight(interp, cfg) {
    var result = C.assessSiting([interp], cfg)[0];
    /* to the 0.0001 it is exact to, as the scorecard ranks it (weightedExact) */
    return weightedExact(result.suitability * result.confidence);
  }

  /**
   * @param {Interpretation[]} interpretations
   * @param {string[]|null} [preferredOrder]
   * @param {VesConfig} [cfg]
   * @returns {Interpretation[]}
   */
  function rankInterpretations(interpretations, preferredOrder, cfg) {
    /* Held beside the interpretation itself, not keyed by its sounding id: a
     * sheet copied without renumbering gives two soundings one id, and a
     * weight looked up by id gave both the last one's, so a point with no
     * water zone could rank first while the suitability table ranked the
     * other. */
    var weight = new Map();
    interpretations.forEach(function (i) { weight.set(i, rankingWeight(i, cfg)); });
    var byId = function (a, b) {
      return a.sounding_id < b.sounding_id ? -1 : a.sounding_id > b.sounding_id ? 1 : 0;
    };
    var ranked;
    if (preferredOrder && preferredOrder.length) {
      var position = {};
      preferredOrder.forEach(function (sid, i) { position[sid] = i; });
      ranked = interpretations.slice().sort(function (a, b) {
        var pa = position[a.sounding_id] === undefined
          ? preferredOrder.length : position[a.sounding_id];
        var pb = position[b.sounding_id] === undefined
          ? preferredOrder.length : position[b.sounding_id];
        return pa - pb || weight.get(b) - weight.get(a) || byId(a, b);
      });
    } else {
      ranked = interpretations.slice().sort(function (a, b) {
        return weight.get(b) - weight.get(a) || byId(a, b);
      });
    }
    ranked.forEach(function (interp, i) { interp.rank = i + 1; });
    return ranked;
  }

  var LAYER_RESISTIVITY_COLUMN = 'Layer resistivity (ohm-m)';

  /**
   * @param {Interpretation[]} interpretations
   * @param {string[]|null} [preferredOrder]
   * @param {VesConfig} [cfg]
   */
  function drillingPreferenceTable(interpretations, preferredOrder, cfg) {
    var c = cfg || defaultConfig().ves;
    var ranked = rankInterpretations(interpretations, preferredOrder, c);
    /* The rows in the order of preference the caption promises; they used to
     * follow the sheets. Two points the ranking cannot separate are both
     * "=1st", by the same test as the tie sentence, unless the analyst has
     * set the order, which is then a judgment and not a score. */
    var tied = [];
    if (!(preferredOrder && preferredOrder.length) && ranked.length >= 2 &&
        C.tiedLeaders(C.assessSiting(interpretations, c), c.ranking_tie_points)) {
      tied = [ranked[0], ranked[1]];
    }
    return ranked.map(function (interp, i) {
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
        'Layer resistivity (ohm-m)': interp.layers.map(function (l) {
          return fmtNum(l.rho, 4);
        }).join('\n'),
        'Possible Water Zones (m)': interp.water_zones.map(function (z) {
          return zoneCell(z[0], z[1], zoneIsOpen(interp, z));
        }).join('\n') || 'none resolved',
        'Max Drilling Depth (m)': drillingDepthText(interp),
        Ranking: tied.indexOf(interp) >= 0 ? '=1st' : ordinal(interp.rank),
      };
    });
  }

  /** reporting/geophysical.py depth_of_investigation_text: how deep the
   * soundings of one array resolve, in the array's own terms. A Wenner
   * sounding's spacing is a, and it used to be reported as a maximum AB/2.
   * @param {string|null|undefined} arrayType
   * @param {number} maxSpacing
   * @param {number} doi
   * @param {VesConfig} [cfg]
   * @returns {string}
   */
  function depthOfInvestigationText(arrayType, maxSpacing, doi, cfg) {
    var c = cfg || defaultConfig().ves;
    var fraction = c.depth_of_investigation_factor;
    var fractionText = Math.abs(fraction - 0.5) < 1e-9 ? 'half' : formatG(fraction) + ' times';
    if (String(arrayType || '').indexOf('wenner') === 0) {
      /* A M N B at equal spacing a: AB = 3a, so AB/2 is 1.5 a */
      return 'A Wenner sounding resolves the ground to roughly ' + fractionText +
        ' its largest electrode spacing a, not to the spacing itself: with a ' +
        'expanded to ' + fmtNum(maxSpacing) + ' m (AB/2 of ' + fmtNum(1.5 * maxSpacing) +
        ' m) the depth of investigation here is about ' + fmtNum(doi) + ' m, and ' +
        'any structure below it is not resolved.';
    }
    return 'A Schlumberger sounding resolves the ground to roughly ' + fractionText +
      ' its largest AB/2, not to the spacing itself: with AB/2 expanded to ' +
      fmtNum(maxSpacing) + ' m the depth of investigation here is about ' +
      fmtNum(doi) + ' m, and any structure below it is not resolved.';
  }

  /** reporting/geophysical.py models_tried_text: what else was tried, so the
   * model in the table is seen as one choice among the candidates.
   * @param {Rec} inversion what invertSounding returns
   * @param {VesConfig} [cfg]
   * @returns {string}
   */
  function modelsTriedText(inversion, cfg) {
    var c = cfg || defaultConfig().ves;
    var trials = (inversion.trials || []).filter(function (t) {
      return t[1] !== null && t[1] !== undefined;
    });
    if (trials.length < 2) return '';
    var tried = trials.map(function (t) {
      return t[0] + ' layers, ' + pyFixed(t[1], 1) + '%';
    }).join('; ');
    var chosen = inversion.model.n_layers;
    var target = c.target_fit_percent;
    var why;
    if (inversion.fit_error_percent <= target) {
      /* "the simplest that reaches the target" was false whenever a simpler
       * model reached it too and was passed over because a richer one more
       * than halved its misfit (the parsimony rule) */
      var simpler = trials.filter(function (t) { return t[0] < chosen && t[1] <= target; })
        .map(function (t) { return t[0]; });
      if (simpler.length) {
        var best = trials.reduce(function (a, b) { return b[1] < a[1] ? b : a; })[0];
        var ratio = c.parsimony_max_error_ratio;
        var cut = Math.abs(ratio - 2.0) < 1e-9 ? 'more than halves'
          : 'cuts by more than a factor of ' + formatG(ratio);
        var one = simpler.length === 1;
        why = 'the ' + andJoin(simpler.map(function (n) { return n + '-layer'; })) + ' ' +
          (one ? 'model also reaches' : 'models also reach') + ' the ' +
          formatG(target) + ' percent target, but ' +
          (best === chosen
            ? 'the ' + chosen + '-layer model ' + cut + ' ' + (one ? 'its' : 'their') +
              ' misfit and is preferred'
            : 'the ' + best + '-layer model ' + cut + ' ' + (one ? 'its' : 'their') +
              ' misfit, and the ' + chosen + '-layer model is the simplest it does ' +
              'not better that far');
      } else {
        why = 'the ' + chosen + '-layer model is the simplest that reaches the ' +
          formatG(target) + ' percent target';
      }
    } else {
      why = 'none reaches the ' + formatG(target) + ' percent target, and the ' +
        chosen + '-layer model is kept as the simplest within ' +
        pyFixed((c.parsimony_fallback_ratio - 1) * 100, 0) + ' percent of the best ' +
        'fit; the alternatives are equally admissible readings of the same curve';
    }
    return 'Models tried: ' + tried + '. Of these ' + why + '.';
  }

  /** reporting/geophysical.py poorly_resolved_text: each boundary whose
   * thickness factor is 2 or more, by the test the narrative softens on.
   * @param {LayeredModel} model
   * @returns {string}
   */
  function poorlyResolvedText(model) {
    var weak = poorlyResolvedBoundaries(model);
    if (!weak.length) return '';
    var one = weak.length === 1;
    return 'The ' + (one ? 'boundary' : 'boundaries') + ' at ' +
      andJoin(weak.map(function (w) { return fmtNum(w[0]) + ' m (x/ ' + pyFixed(w[1], 1) + ')'; })) +
      (one ? ' is' : ' are') + ' poorly resolved: within ' + (one ? 'its' : 'their') +
      ' uncertainty the model collapses to one with ' +
      (one ? 'a layer fewer' : 'fewer layers') + ', so the layer count above is a ' +
      'reading of the curve rather than a property of it.';
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
    inversionReadings: inversionReadings, restoreInversion: restoreInversion,
    mostLayers: mostLayers,
    sha256Hex: sha256Hex, canonicalText: canonicalText,
    inversionEngine: inversionEngine, inversionCacheKey: inversionCacheKey,
    inversionCacheEntry: inversionCacheEntry, inversionFromCache: inversionFromCache,
    startingModels: startingModels, parameterUncertainty: parameterUncertainty,
    classifyCurve: classifyCurve, describeCurveType: describeCurveType,
    interpretModel: interpretModel, rankInterpretations: rankInterpretations,
    drillingPreferenceTable: drillingPreferenceTable,
    depthOfInvestigation: depthOfInvestigation, fitConfidence: fitConfidence,
    zoneText: zoneText, zoneCell: zoneCell, zoneIsOpen: zoneIsOpen,
    drillingDepthText: drillingDepthText, rankingWeight: rankingWeight,
    poorlyResolvedBoundaries: poorlyResolvedBoundaries, andJoin: andJoin,
    depthOfInvestigationText: depthOfInvestigationText,
    modelsTriedText: modelsTriedText, poorlyResolvedText: poorlyResolvedText,
    LAYER_RESISTIVITY_COLUMN: LAYER_RESISTIVITY_COLUMN,
    fmtNum: fmtNum, fmtRange: fmtRange, formatG: formatG,
    roundSig: roundSig, pyRound: pyRound, pyFixed: pyFixed, expo: expo,
    ordinal: ordinal, plural: plural, pluralNoun: pluralNoun,
    renderText: renderText, phrase: phrase, phraseTable: phraseTable,
  });

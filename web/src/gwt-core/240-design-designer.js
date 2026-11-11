
  /* ========================================================= borehole design
   * groundwater/design/designer.py. Plain casing from surface, screens against
   * the aquifer zones and below the static level by a margin, a sump below the
   * lowest screen, gravel pack from the bottom to above the top screen,
   * backfill up to the sanitary seal, and cement from surface.
   */

  /* The annular fill a design carries, decided by the annulus the hole and
   * casing leave: a filter pack needs 70 mm a side, anything can be placed
   * past 50 mm, and under that nothing can be poured without bridging. */
  var ANNULUS_PACK_MIN_MM = 50.0;
  var ANNULUS_FILTER_MIN_MM = 70.0;

  /* How construction was arrived at, printed under every drawing. */
  var DESIGN_NOTE = 'Construction generated from the drilling log by the design ' +
    'rules. The log records no casing string, so this is a design, not an ' +
    'as-built record.';
  var AS_BUILT_NOTE = 'As built: the screens are those recorded as installed on ' +
    'the drilling log; the rest of the string follows the design rules.';

  /** The cement seal: the recorded grout depth, never less than the rule. Dr
   * Timbo's log records grouting to 20 m; the drawing showed a 6 m seal
   * with a screen and a gravel pack inside the grouted interval.
   * @param {DrillingLog|null} log
   * @param {DesignConfig} rules
   * @param {number|null} [totalDepthM]
   * @returns {number}
   */
  function sealDepthFor(log, rules, totalDepthM) {
    var grout = log ? Number(log.grouting_depth_m || 0.0) : 0.0;
    /* A grout recorded at or below the top of the sump cannot be what was
     * placed: it leaves nowhere for a screen, and 70 m in a 60 m hole printed
     * a "0-70 m" seal over "Annular fill 70-60 m". It is held at the top of
     * the sump, and designBorehole flags it as grout_too_deep. */
    var total = totalDepthM;
    if ((total === null || total === undefined) && log && log.total_depth_m) {
      total = Number(log.total_depth_m);
    }
    if (total !== null && total !== undefined) {
      grout = Math.min(grout, Math.max(total - rules.sump_length_m, 0.0));
    }
    return Math.max(rules.sanitary_seal_depth_m, grout);
  }

  /** The shallowest pump intake the pumping test supports: the deepest level
   * the test drew the water to, with the submergence margin under it, the
   * floor the yield recommendation itself never sets the intake above. Null
   * when the test gives no level (designer.pump_intake_floor).
   * @param {Rec|null} recommendation a yield recommendation
   * @param {number} submergenceM
   * @returns {number|null}
   */
  function pumpIntakeFloor(recommendation, submergenceM) {
    var deepest = recommendation ? recommendation.deepest_pumping_level_m : null;
    if (deepest === null || deepest === undefined) return null;
    return Number(deepest) + Number(submergenceM);
  }

  /** The drilled diameter the log records, from its diameter column. The
   * deepest interval with a diameter is the production diameter; a hole
   * reamed wider at the top is logged that way.
   * @param {DrillingLog|null} [log]
   * @returns {number|null}
   */
  function loggedDiameterIn(log) {
    if (!log) return null;
    var deepest = /** @type {Rec|null} */ (null);
    (log.intervals || []).forEach(function (iv) {
      if (!iv.bit_diameter_in) return;
      if (deepest === null || iv.bottom_m > deepest.bottom_m) deepest = iv;
    });
    return deepest === null ? null : Number(deepest.bit_diameter_in);
  }

  /* [fill, material, annulusMm, boreIn]: what the annulus can hold, by the
   * same rule the field checks apply (50 mm per side to place gravel, 70 mm
   * for it to filter), on the diameter the log says was drilled or the
   * rule's (designer._annular_fill). */
  function annularFill(log, rules) {
    var boreIn = loggedDiameterIn(log) || rules.borehole_diameter_in;
    var annulusMm = (boreIn - rules.casing_diameter_in) * 25.4 / 2.0;
    if (annulusMm < ANNULUS_PACK_MIN_MM) return ['none', '', annulusMm, boreIn];
    if (annulusMm < ANNULUS_FILTER_MIN_MM) {
      return ['formation stabiliser', rules.gravel_pack_material, annulusMm, boreIn];
    }
    return ['gravel pack', rules.gravel_pack_material, annulusMm, boreIn];
  }

  /* {floor, sealed, why}: the shallowest depth a designed screen may start
   * at, whether the seal rather than the static water level sets it, and
   * what a sentence calls the seal's part of it (designer._screen_floor).
   * Below the seal, and below the fill the rules put above the top screen:
   * a screen placed at the seal's foot had grout sitting on it, with the
   * pack clamped to the seal and no word said. Moving the screen rather than
   * shortening the pack is a choice (QUESTIONS.md item 24). */
  function screenFloor(log, rules, swl, totalDepth) {
    var seal = sealDepthFor(log, rules, totalDepth);
    var swlFloor = (swl || 0.0) + rules.min_screen_below_swl_m;
    var fill = annularFill(log, rules)[0];
    var pack = fill !== 'none' ? rules.gravel_pack_above_top_screen_m : 0.0;
    var why = pack > 0 ? phrase('design.under_seal', { seal: seal, pack: pack, fill: fill })
      : 'the ' + formatG(seal) + ' m grouted interval';
    return { floor: Math.max(swlFloor, seal + pack), sealed: seal + pack >= swlFloor,
      why: why };
  }

  /**
   * @param {DrillingLog|null} log
   * @param {number} depth
   * @returns {Rec|null}
   */
  function intervalAt(log, depth) {
    if (!log) return null;
    var intervals = log.intervals || [];
    for (var i = 0; i < intervals.length; i++) {
      if (intervals[i].top_m <= depth && depth < intervals[i].bottom_m) return intervals[i];
    }
    return null;
  }

  /* Lithology phrases that mark an interval as a screening target, and phrases
   * that negate it, so "dry, no water struck" is not screened just because it
   * contains the word water. */
  var AQUIFER_WORDS = ['fracture', 'fractured', 'fractures', 'aquifer'];
  var AQUIFER_PHRASES = ['water-bearing', 'water bearing', 'waterbearing',
    'water strike', 'water struck', 'water inflow'];
  var NEGATION_PHRASES = ['no water', 'not reached', 'without water',
    'water table not'];

  /** The basis sentences are written from the zones that survive clipping,
   * not from the candidates: a strike above the static-level floor used to
   * leave "screens positioned against the water strikes (8 m)" in the client
   * document beside "no aquifer intervals identified", and blocked the VES
   * fallback while contributing no screen. Each candidate is kept with what
   * the clip did to it, so placementBasis can say why a zone the log names is
   * screened only in part, or not at all.
   *
   * Returns { zones, targets, excluded, ves }: the merged zones, one target
   * per depth the log names ({ kind: 'strike' | 'zone' | 'interval', label,
   * candidate, clipped, cut }), the sentences that do not depend on
   * what survives (a strike in clay or in the grout, a clayey interval), and
   * the VES sentence when the VES zones were used.
   * @param {DrillingLog|null} log
   * @param {Interpretation|null} interpretation
   * @param {number|null} swl
   * @param {number} totalDepth
   * @param {DesignConfig} rules
   */
  function targetZones(log, interpretation, swl, totalDepth, rules) {
    var seal = sealDepthFor(log, rules, totalDepth);
    var margin = (rules.fracture_zone_margin_m === undefined ||
                  rules.fracture_zone_margin_m === null)
      ? configDefaults().design.fracture_zone_margin_m : rules.fracture_zone_margin_m;
    /* nothing is screened inside the grouted interval, whatever the log says
     * is wet there: the grout is there to keep that water out; nor in the
     * fill the rules put above the top screen */
    var below = screenFloor(log, rules, swl, totalDepth);
    var floor = below.floor;
    var sumpTop = totalDepth - rules.sump_length_m;
    function clipOne(z) {
      var top = Math.ceil(Math.max(z[0], floor) * 2.0) / 2.0;
      var bottom = Math.floor(Math.min(z[1], sumpTop) * 2.0) / 2.0;
      return bottom - top >= 1.0 ? [top, bottom] : null;
    }
    function clip(candidates) {
      return candidates.map(clipOne).filter(function (c) { return c !== null; });
    }
    function target(kind, label, first, candidate) {
      var cut = [];
      if (candidate[0] < floor) {
        cut.push(below.sealed
          ? 'within ' + below.why
          : 'shallower than ' + formatG(floor) + ' m, ' +
            formatG(rules.min_screen_below_swl_m) + ' m below the static water level');
      }
      if (candidate[1] > sumpTop) {
        cut.push(first >= totalDepth
          ? 'below the ' + formatG(totalDepth) + ' m bottom of the hole'
          : 'below the top of the ' + formatG(rules.sump_length_m) + ' m sump, at ' +
            formatG(sumpTop) + ' m');
      }
      return { kind: kind, label: label, candidate: candidate,
        clipped: clipOne(candidate), cut: cut };
    }
    var targets = [], excluded = [];
    if (log) {
      (log.water_strikes_m || []).forEach(function (strike) {
        var host = intervalAt(log, strike);
        var reasons = [];
        if (host && isClayey(host.description)) {
          reasons.push('it is in ' + String(host.description || '').toLowerCase() +
            ', a seepage horizon that is cased and grouted off rather than screened');
        }
        if (strike < seal) {
          reasons.push('it lies within the ' + formatG(seal) + ' m grouted interval');
        }
        if (reasons.length) {
          excluded.push('the ' + formatG(strike) + ' m strike is not screened: ' +
            reasons.join(' and '));
          return;
        }
        targets.push(target('strike', formatG(strike) + ' m', strike,
          [Math.max(strike - 1.0, 0.0), strike + 5.0]));
      });
      (log.intervals || []).forEach(function (interval) {
        var text = String(interval.description || '').toLowerCase();
        /* e.g. "dry, no water struck" is not an aquifer */
        if (NEGATION_PHRASES.some(function (n) { return text.indexOf(n) >= 0; })) return;
        var words = text.match(/[a-z]+/g) || [];
        var hinted = words.some(function (w) { return AQUIFER_WORDS.indexOf(w) >= 0; }) ||
          AQUIFER_PHRASES.some(function (p) { return text.indexOf(p) >= 0; });
        if (!hinted) return;
        if (isClayey(interval.description)) {
          excluded.push('the ' + formatG(interval.top_m) + '-' + formatG(interval.bottom_m) +
            ' m interval is not screened: ' + text + ' is clayey ground');
          return;
        }
        /* "fracture zone 49-52 m" on the 45-50 m row: the zone is the target,
         * with a margin, not the five metres it was logged on. The screens
         * used to cover one metre of that zone and none of the next, which
         * sat behind plain casing. A fracture phrase whose depths cannot be
         * read leaves the row a target as well, rather than leaving it to
         * plain casing. */
        var reading = readFractures(interval.description, interval.top_m, interval.bottom_m);
        reading.ranges.forEach(function (r) {
          targets.push(target('zone', formatG(r[0]) + '-' + formatG(r[1]) + ' m', r[0],
            [r[0] - margin, r[1] + margin]));
        });
        if (reading.unread || !reading.ranges.length) {
          targets.push(target('interval', formatG(interval.top_m) + '-' +
            formatG(interval.bottom_m) + ' m', interval.top_m,
            [interval.top_m, interval.bottom_m]));
        }
      });
    }
    /* one target per thing the log names, however many rows name it */
    var seen = {};
    targets = targets.filter(function (t) {
      var key = t.kind + '|' + t.label;
      if (seen[key]) return false;
      seen[key] = true;
      return true;
    });
    var clipped = targets.filter(function (t) { return t.clipped; })
      .map(function (t) { return t.clipped; });
    var ves = [];
    if (!clipped.length && interpretation && interpretation.water_zones.length) {
      clipped = clip(interpretation.water_zones.map(function (z) { return [z[0], z[1]]; }));
      if (clipped.length) {
        ves.push('screens positioned against the low resistivity zones of the ' +
          'VES interpretation (' + interpretation.water_zones.map(function (z) {
            return Math.trunc(z[0]) + '-' + Math.trunc(z[1]) + ' m';
          }).join(', ') + ')');
      }
    }
    clipped.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var merged = [];
    clipped.forEach(function (zone) {
      var last = merged[merged.length - 1];
      if (last && zone[0] <= last[1] + 1.0) last[1] = Math.max(last[1], zone[1]);
      else merged.push([zone[0], zone[1]]);
    });
    return { zones: merged, targets: targets, excluded: excluded, ves: ves };
  }

  /* The basis sentences, written from the screens that are actually built
   * (designer._placement_basis). A zone clipped by the grout, the sump or the
   * bottom of the hole, or trimmed away with the shallowest screens, used to
   * stay in the basis as "screens positioned against the fracture zones the
   * log names (16-18 m, 49-52 m, 59-62 m), with 1 m of screen either side"
   * beside a single 48-53 m screen. Each target is now described by what
   * covers it: in full, in part with the reason, or not at all with the
   * reason. */
  function placementBasis(found, screens, rules) {
    var margin = (rules.fracture_zone_margin_m === undefined ||
                  rules.fracture_zone_margin_m === null)
      ? configDefaults().design.fracture_zone_margin_m : rules.fracture_zone_margin_m;
    var trimReason = 'the screens were trimmed to 60 percent of the hole, keeping ' +
      'the deepest sections';
    function covered(zone) {
      var pieces = [];
      screens.forEach(function (s) {
        var top = Math.max(zone[0], s[0]), bottom = Math.min(zone[1], s[1]);
        if (bottom > top) pieces.push([top, bottom]);
      });
      if (!pieces.length) return null;
      return [Math.min.apply(null, pieces.map(function (p) { return p[0]; })),
        Math.max.apply(null, pieces.map(function (p) { return p[1]; }))];
    }
    function same(a, b) {
      return a === null ? b === null : (b !== null && a[0] === b[0] && a[1] === b[1]);
    }
    var nouns = { strike: 'strike', zone: 'fracture zone', interval: 'interval' };
    var strikes = [], zones = [], intervals = [], partial = [], dropped = [];
    found.targets.forEach(function (t) {
      var cover = t.clipped ? covered(t.clipped) : null;
      var trimmed = t.clipped !== null && !same(cover, t.clipped);
      var why = [];
      if (t.cut.length && (cover === null || cover[0] > t.candidate[0] ||
                           cover[1] < t.candidate[1])) {
        why.push((cover === null ? 'it lies ' : 'the rest of it lies ') + t.cut.join(' and '));
      }
      if (trimmed) why.push(trimReason);
      if (cover === null) {
        if (why.length) {
          dropped.push('the ' + t.label + ' ' + nouns[t.kind] + ' is not screened: ' +
            why.join('; '));
        }
        return;
      }
      if (t.kind === 'strike') {
        strikes.push(t.label);
      } else if (t.kind === 'interval') {
        intervals.push(t.label);
      } else if (same(cover, [Math.ceil(t.candidate[0] * 2.0) / 2.0,
                              Math.floor(t.candidate[1] * 2.0) / 2.0])) {
        zones.push(t.label);
      } else {
        partial.push('the ' + t.label + ' fracture zone is screened at ' +
          formatG(cover[0]) + '-' + formatG(cover[1]) + ' m, not with ' + formatG(margin) +
          ' m of screen either side: ' +
          (why.length ? why : ['the screen is rounded to the half metre']).join('; '));
      }
    });
    var basis = [];
    if (strikes.length) {
      basis.push('screens positioned against the water strikes recorded in ' +
        'the drilling log (' + strikes.join(', ') + ')');
    }
    if (zones.length) {
      basis.push('screens positioned against the fracture zones the log names (' +
        zones.join(', ') + '), with ' + formatG(margin) + ' m of screen either side');
    }
    if (intervals.length) {
      basis.push('screens positioned against the fractured or water-bearing ' +
        'intervals logged at ' + intervals.join(', '));
    }
    return basis.concat(partial, found.excluded, dropped, found.ves);
  }

  /* Clean up analyst-supplied screen intervals without silently moving them:
   * anything the clipping actually changed is flagged rather than absorbed,
   * because a screen that has quietly moved is worse than one refused.
   *
   * Screens recorded as installed are a record, not a choice: two that meet
   * stay two, and a clip is a warning that reaches the client documents. It
   * used to be an info flag, so "48-54; 54-60 m" in a 60 m hole was printed
   * "Screens (as installed) 48-58 m" without a word. */
  function analystScreens(screensM, totalDepthM, rules, flags, asBuilt) {
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
          if (asBuilt) {
            flags.push({
              level: 'warning', code: 'screen_clipped',
              message: 'The screen recorded as installed at ' + formatG(top) + '-' +
                formatG(bottom) + ' m runs below the top of the ' +
                formatG(rules.sump_length_m) + ' m sump the design rules place at ' +
                formatG(sumpTop) + ' m in this ' + formatG(totalDepthM) +
                ' m hole; it is drawn as ' + formatG(clippedTop) + '-' +
                formatG(clippedBottom) + ' m. Check the record against the hole.',
            });
          } else {
            flags.push({
              level: 'info', code: 'screen_clipped',
              message: 'Screen ' + formatG(top) + '-' + formatG(bottom) +
                ' m was clipped to ' + formatG(clippedTop) + '-' +
                formatG(clippedBottom) + ' m to stay inside the hole and above ' +
                'the sump.',
            });
          }
        }
        var last = cleaned[cleaned.length - 1];
        if (last && (clippedTop < last[1] || (clippedTop === last[1] && !asBuilt))) {
          last[1] = Math.max(last[1], clippedBottom);
        } else {
          cleaned.push([clippedTop, clippedBottom]);
        }
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

  /* Build the casing string and annulus around a set of screen intervals. */
  function assembleDesign(spec) {
    var screens = spec.screens, rules = spec.rules, log = spec.log || null;
    var totalDepthM = spec.totalDepthM, swl = spec.swl;
    var asBuilt = !!spec.asBuilt;
    /** @type {Rec[]} */
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
    var sealDepth = sealDepthFor(log, rules, totalDepthM);
    var flags = spec.flags;
    var grout = log ? Number(log.grouting_depth_m || 0.0) : 0.0;
    if (grout > 0 && grout >= sumpTop) {
      flags.push({
        level: 'error', code: 'grout_too_deep',
        message: 'The drilling log records grouting to ' + formatG(grout) + ' m, at ' +
          'or below the top of the sump at ' + formatG(sumpTop) + ' m in this ' +
          formatG(totalDepthM) + ' m hole, which leaves nowhere below the grout for ' +
          'a screen. The seal is drawn to ' + formatG(sealDepth) + ' m; check the ' +
          'grouting depth on the log.',
      });
    }
    /* A screen inside the grout is sealed off from the water it is there to
     * take. The design never places one there; a screen recorded as
     * installed, or placed by the analyst, can say otherwise, and 15-20 m of
     * an as-built screen inside a 20 m grout used to go unmentioned. */
    screens.forEach(function (s) {
      if (s[0] < sealDepth) {
        var sealed = Math.min(s[1], sealDepth) - s[0];
        flags.push({
          level: 'warning', code: 'screen_in_grout',
          message: (asBuilt ? 'The screen recorded as installed at ' : 'The screen at ') +
            formatG(s[0]) + '-' + formatG(s[1]) + ' m runs inside the ' +
            formatG(sealDepth) + ' m grouted interval, which seals ' + formatG(sealed) +
            ' m of it off' + (asBuilt
              ? '; the record of the grout or of the screen needs checking.' : '.'),
        });
      }
    });
    var rule = rules.gravel_pack_above_top_screen_m;
    /* where the fill's top falls against the top screen: the rule's height,
     * unless the seal holds it lower. Compared to a nanometre, not to the
     * last bit: a screen at 17.4 m under a 15.4 m seal leaves 17.4 - 2 =
     * 15.399999999999999 m, and was flagged short of the 2 m it has; one at
     * 8.3 m under a 7.3 m seal and a 1 m rule left 7.300000000000001 m, and
     * the summary printed "Backfill 7.3-7.3 m" (designer.py). */
    var packTop = topScreen - rule;
    var packHeld = sealDepth - packTop > 1e-9;
    var gravelTop = packTop - sealDepth > 1e-9 ? packTop : sealDepth;
    var margin = packHeld ? pyRound(topScreen - sealDepth, 9) : rule;
    var gravel = [gravelTop, totalDepthM];
    var seal = [0.0, sealDepth];
    var backfill = [sealDepth, gravelTop];

    /* the drilled diameter is what the log says was drilled, not the rule's
     * default; the rule applies when the log records none */
    var diameterSource = loggedDiameterIn(log) ? ' as logged' : '';

    /* The same annulus rule the field checks apply (50 mm per side to place
     * gravel, 70 mm for it to filter). It used to raise a flag that reached
     * no document while the drawing, the summary and the bill of quantities
     * carried a 2-4 mm pack that cannot be poured through 19 mm. The fill
     * now follows the annulus, and every document follows the fill. */
    var annular = annularFill(log, rules);
    var fill = annular[0], material = annular[1], annulusMm = annular[2], boreIn = annular[3];
    if (fill === 'none') {
      flags.push({
        level: 'warning', code: 'thin_annulus',
        message: 'A ' + formatG(rules.casing_diameter_in) + ' inch casing in a ' +
          formatG(boreIn) + ' inch hole leaves ' + pyFixed(annulusMm, 0) +
          ' mm of annulus per side, under the ' + formatG(ANNULUS_PACK_MIN_MM) +
          ' mm needed to place gravel without bridging (' +
          formatG(ANNULUS_FILTER_MIN_MM) + ' mm for a true filter pack), so no ' +
          'gravel pack is drawn or priced and the screen slot must suit the ' +
          'formation; use a larger bit or smaller casing to fit one.',
      });
    } else if (fill === 'formation stabiliser') {
      flags.push({
        level: 'info', code: 'thin_annulus',
        message: 'The ' + pyFixed(annulusMm, 0) + ' mm annulus meets the ' +
          formatG(ANNULUS_PACK_MIN_MM) + ' mm placement minimum but is under ' +
          formatG(ANNULUS_FILTER_MIN_MM) + ' mm, so the annular fill acts as a ' +
          'formation stabiliser rather than a filter pack.',
      });
    }
    if (fill !== 'none' && packHeld) {
      /* The basis said "2 m above the top screen" of a pack the seal held
       * level with it, or 5 m below it round a screen in the grout. */
      flags.push({
        level: 'warning', code: 'gravel_pack_short',
        message: phrase('design.fill_short', { fill: fill, top: gravelTop,
          seal: sealDepth, screen: topScreen, rule: rule, need: sealDepth + rule }),
      });
    }

    var fillSentence;
    if (fill === 'none') {
      fillSentence = 'no gravel pack: the ' + pyFixed(annulusMm, 0) + ' mm annulus ' +
        'between the ' + formatG(rules.casing_diameter_in) + ' inch casing and the ' +
        formatG(boreIn) + ' inch hole is too thin to place one, so the annulus ' +
        'below the seal is left to the formation';
    } else {
      var where = margin > 0 ? 'design.fill_above'
        : (margin < 0 ? 'design.fill_below' : 'design.fill_level');
      /** @type {Rec} */
      var values = { fill: fill, material: material, top: gravel[0] };
      if (margin) values.margin = Math.abs(margin);
      fillSentence = phrase(where, values);
    }
    var sealSentence;
    if (grout > sealDepth) {
      /* held at the top of the sump: not what the log records */
      sealSentence = 'cement grout from surface to ' + formatG(sealDepth) + ' m, the ' +
        'top of the sump, where the drilling log records ' + formatG(grout) +
        ' m (see the design notes), with ' + rules.apron_note;
    } else if (sealDepth > rules.sanitary_seal_depth_m) {
      sealSentence = 'cement grout from surface to ' + formatG(sealDepth) +
        ' m as recorded on the drilling log (the rule\'s minimum is ' +
        formatG(rules.sanitary_seal_depth_m) + ' m), with ' + rules.apron_note;
    } else {
      sealSentence = 'cement sanitary seal from surface to ' + formatG(sealDepth) +
        ' m with ' + rules.apron_note;
    }
    var basis = spec.basis.concat([
      formatG(rules.casing_diameter_in) + ' inch ' + rules.casing_material +
        ' casing in a ' + formatG(boreIn) + ' inch hole' + diameterSource,
      fillSentence,
      sealSentence,
      'screens kept at least ' + formatG(rules.min_screen_below_swl_m) +
        ' m below the static water level',
    ]);

    if (swl !== null && swl !== undefined && topScreen < swl) {
      flags.push({
        level: 'warning', code: 'screen_above_swl',
        message: 'The top screen is above the static water level; check the design.',
      });
    }

    /* A pump intake inside a screen is moved into plain casing, downwards
     * where the string allows it (deeper is more submergence) and upwards
     * otherwise, by the same clearance the pumping rules use. The yield
     * recommendation cannot know where the screens are; the design can. */
    var intake = spec.pumpIntakeM === undefined ? null : spec.pumpIntakeM;
    var intakeFloor = spec.pumpIntakeFloorM === undefined ? null : spec.pumpIntakeFloorM;
    var inScreen = function (depth) {
      return screens.some(function (s) { return s[0] <= depth && depth <= s[1]; });
    };
    var held = '';
    if (intake !== null) {
      var hit = null;
      for (var h = 0; h < screens.length; h++) {
        if (screens[h][0] <= intake && intake <= screens[h][1]) { hit = screens[h]; break; }
      }
      if (hit) {
        var clearance = 1.0;
        var below = hit[1] + clearance, above = hit[0] - clearance;
        var plainBelow = below <= sumpTop && !inScreen(below);
        var plainAbove = above > 0 &&
          (swl === null || swl === undefined || above > swl) && !inScreen(above);
        /* Moving the intake up spends drawdown the yield was worked out on.
         * It goes up only as far as the deepest level the pumping test
         * reached plus the submergence margin, the floor the yield itself
         * holds to: a 40-68 m screen used to lift a 52 m intake to 39 m,
         * above the 42.3 m the test had drawn the water to, which is the
         * intake hydraulics-4 took out of the yield. Without that floor there
         * is nothing to check a shallower setting against. */
        if (plainAbove && !plainBelow) {
          if (intakeFloor === null) {
            held = 'the plain casing above it, at ' + formatG(above) + ' m, cannot ' +
              'be checked against the level the pumping test reached';
          } else if (above < intakeFloor) {
            held = 'the plain casing above it, at ' + formatG(above) + ' m, is ' +
              'shallower than the ' + formatG(intakeFloor) + ' m the pumping test ' +
              'supports (the deepest level it reached with the submergence margin)';
          }
          if (held) plainAbove = false;
        }
        var moved = plainBelow ? below : (plainAbove ? above : null);
        if (moved !== null) {
          var direction = moved > intake ? 'below' : 'above';
          flags.push({
            level: 'info', code: 'pump_intake_moved',
            message: 'The pump intake of ' + formatG(intake) + ' m from the yield ' +
              'recommendation sits inside the ' + formatG(hit[0]) + '-' +
              formatG(hit[1]) + ' m screen; it is set at ' + formatG(moved) + ' m, ' +
              formatG(clearance) + ' m ' + direction + ' that screen in plain ' +
              'casing, so the inflow is not drawn across the pump.',
          });
          basis.push('pump intake at ' + formatG(moved) + ' m, in plain casing ' +
            formatG(clearance) + ' m ' + direction + ' the ' + formatG(hit[0]) + '-' +
            formatG(hit[1]) + ' m screen rather than the ' + formatG(intake) +
            ' m the yield recommendation asked for');
          intake = moved;
        }
      }
    }
    /* a pump intake is written straight through from the caller; it used to
     * be accepted below the hole bottom, inside a screen or above the water */
    if (intake !== null) {
      if (intake > sumpTop) {
        flags.push({
          level: 'error', code: 'pump_intake_below_hole',
          message: 'The pump intake at ' + formatG(intake) + ' m is below the top of ' +
            'the sump at ' + formatG(sumpTop) + ' m in a ' + formatG(totalDepthM) +
            ' m hole; it cannot be set there.',
        });
      } else if (held) {
        flags.push({
          level: 'warning', code: 'pump_intake_in_screen',
          message: 'The pump intake at ' + formatG(intake) + ' m sits inside a ' +
            'screened interval and is kept there: there is no plain casing below ' +
            'that screen above the sump, and ' + held + '. Set the screens so there ' +
            'is plain casing at a depth the test supports, or accept the inflow ' +
            'drawn across the pump.',
        });
      } else if (inScreen(intake)) {
        flags.push({
          level: 'warning', code: 'pump_intake_in_screen',
          message: 'The pump intake at ' + formatG(intake) + ' m sits inside a ' +
            'screened interval; set it in plain casing above or below the screen ' +
            'so the inflow is not drawn across the pump.',
        });
      }
      if (swl !== null && swl !== undefined && intake <= swl) {
        flags.push({
          level: 'error', code: 'pump_intake_above_swl',
          message: 'The pump intake at ' + formatG(intake) + ' m is at or above the ' +
            'static water level of ' + formatG(swl) + ' m; the pump would run dry.',
        });
      }
    }

    var design = {
      total_depth_m: totalDepthM,
      borehole_diameter_in: boreIn,
      casing_diameter_in: rules.casing_diameter_in,
      casing_material: rules.casing_material,
      segments: segments,
      gravel_pack: gravel,
      backfill: backfill,
      sanitary_seal: seal,
      stickup_m: rules.stickup_m,
      screen_slot_mm: rules.screen_slot_mm,
      water_strikes_m: log && log.water_strikes_m ? log.water_strikes_m.slice() : [],
      static_water_level_m: swl === undefined ? null : swl,
      pump_intake_m: intake,
      design_basis: basis,
      flags: flags,
      /* "gravel pack" (a filter pack, 70 mm or more a side), "formation
       * stabiliser" (placeable but too thin to filter) or "none" (an annulus
       * nothing can be poured into). The drawing, the summary and the bill
       * of quantities all read this; a 19 mm annulus used to carry a 2-4 mm
       * pack on every one of them. */
      annular_fill: fill,
      annular_fill_material: material,
      annulus_mm: annulusMm,
      /* true when the screens are the ones recorded as installed on the log */
      as_built: asBuilt,
      construction_note: asBuilt ? AS_BUILT_NOTE : DESIGN_NOTE,
      /* the rising main and its inspection, from the water (step 7.2) */
      rising_main: risingMainChoice(spec.quality || null, rules),
    };
    design.screens = segments.filter(function (s) { return s.kind === 'screen'; });
    design.total_screen_length_m = design.screens.reduce(function (a, s) {
      return a + s.length_m;
    }, 0);
    design.annular_fill_label = annularFillLabel(design);
    return design;
  }

  /** What the annulus below the seal holds, for a drawing or a table.
   * @param {Design} design
   * @returns {string}
   */
  function annularFillLabel(design) {
    var fill = design.annular_fill === undefined ? 'gravel pack' : design.annular_fill;
    var mm = pyFixed(design.annulus_mm || 0.0, 0);
    var material = design.annular_fill_material || '';
    if (fill === 'none') {
      return 'no gravel pack: the ' + mm + ' mm annulus is too thin to place one';
    }
    if (fill === 'formation stabiliser') {
      return 'formation stabiliser (' + material + '); the ' + mm +
        ' mm annulus is too thin for a filter pack';
    }
    return 'gravel pack (' + material + ')';
  }

  /** Depths print as written (14.5, not 14): the table used to round 14.5 m
   * to "14" beside a drawing that said 14.5.
   * @param {Design} design
   * @returns {string[][]}
   */
  function designSummaryRows(design) {
    var rows = [
      ['Total depth', formatG(design.total_depth_m) + ' m'],
      ['Drilled diameter', formatG(design.borehole_diameter_in) + '"'],
      ['Casing', formatG(design.casing_diameter_in) + '" ' + design.casing_material +
        ', stick-up ' + formatG(design.stickup_m) + ' m'],
      ['Screens' + (design.as_built ? ' (as installed)' : ''),
        design.screens.map(function (s) {
          return formatG(s.top_m) + '-' + formatG(s.bottom_m) + ' m';
        }).join('; ') + ' (slot ' + formatG(design.screen_slot_mm) + ' mm)'],
      ['Annular fill', formatG(design.gravel_pack[0]) + '-' +
        formatG(design.gravel_pack[1]) + ' m: ' + annularFillLabel(design)],
      /* the fill can reach the seal, and "Backfill 20-20 m" was printed */
      ['Backfill', design.backfill[1] > design.backfill[0]
        ? formatG(design.backfill[0]) + '-' + formatG(design.backfill[1]) + ' m' : 'none'],
      ['Sanitary seal', formatG(design.sanitary_seal[0]) + '-' +
        formatG(design.sanitary_seal[1]) + ' m cement grout'],
    ];
    if (design.static_water_level_m !== null && design.static_water_level_m !== undefined) {
      rows.push(['Static water level', pyFixed(design.static_water_level_m, 2) + ' m']);
    }
    if (design.water_strikes_m.length) {
      rows.push(['Water strikes', design.water_strikes_m.map(function (w) {
        return formatG(w) + ' m';
      }).join(', ')]);
    }
    if (design.pump_intake_m !== null && design.pump_intake_m !== undefined) {
      rows.push(['Recommended pump intake', formatG(design.pump_intake_m) + ' m']);
    }
    return rows;
  }

  /* --- the rising main (PLAN.md step 7.2) -----------------------------------
   * groundwater/design/materials.py. A galvanised iron rising main and its
   * rods corrode quickly in aggressive water, so the design reads the water
   * quality assessment and says what it specifies for the rising main and how
   * often it is inspected, and why. No second classification is made: the
   * water is aggressive by the corrosivity classification (is_aggressive:
   * Ryznar above 7.0, Langelier below -0.5 or aggressive index below 10) or
   * by the handpump corrosion check's pH rule (below 6.5, RWSN Stop the Rot).
   * With no sample, or one without the indices, the standard material is kept
   * on no chemistry and the shorter inspection interval applies. */

  /** What the water says: CHEMISTRY_STATES in materials.py. */
  var CHEMISTRY_STATES = ['aggressive', 'not_aggressive', 'incomplete', 'none'];
  /** The handpump corrosion check's pH rule: PH_CORROSIVE_BELOW. */
  var PH_CORROSIVE_BELOW = 6.5;

  /* a design rule, or the toolkit's default where the rules carry none (a
   * configuration saved before the rule existed) */
  function designRule(rules, key) {
    var value = rules ? rules[key] : undefined;
    return value === undefined || value === null ? configDefaults().design[key] : value;
  }

  /* two material names are one material, whatever their case and end blanks
   * (_same_material, trimmed as trim_field trims) */
  function sameMaterial(a, b) {
    return trimField(a).toLowerCase() === trimField(b).toLowerCase();
  }

  /* the Langelier index with its sign, to two decimals; nought is "+0.00" */
  function signedIndex(value) {
    return value < 0 ? '-' + pyFixed(-value, 2) : '+' + pyFixed(Math.abs(value), 2);
  }

  /* how the sample is named after "The water sample" (_sample_name) */
  function risingMainSampleName(sample) {
    var ident = trimField(sample.sample_id || '');
    var when = trimField(sample.sample_date || '');
    if (ident && when) return phrase('rising_main.sample_named', { id: ident, date: when });
    if (ident) return phrase('rising_main.sample_undated', { id: ident });
    if (when) return phrase('rising_main.sample_unnamed', { date: when });
    return phrase('rising_main.sample_anonymous');
  }

  /** What the design specifies for the rising main, from the water:
   * rising_main_choice. quality is the water quality assessment (its
   * corrosivity read as it stands), a bare sample (assessed for corrosivity
   * here) or null; rules are the design rules. inspection_months is the named
   * value the service rounds of step 7.3 read.
   * @param {QualityAssessment|QualitySample|null} [quality]
   * @param {DesignConfig} [rules]
   * @returns {Rec}
   */
  function risingMainChoice(quality, rules) {
    var standard = designRule(rules, 'rising_main_material');
    var resistant = designRule(rules, 'aggressive_rising_main_material');
    var usual = designRule(rules, 'rising_main_inspection_months');
    var shorter = designRule(rules, 'aggressive_rising_main_inspection_months');

    var sample = null, corrosivity = null;
    if (quality) {
      if (quality.sample !== undefined && quality.corrosivity !== undefined) {
        sample = quality.sample || null;
        corrosivity = quality.corrosivity || (sample ? assessCorrosivity(sample) : null);
      } else {
        sample = quality;
        corrosivity = assessCorrosivity(sample);
      }
    }
    /** @type {Rec} */
    var out = {
      material: standard, standard: standard, upgraded: false, chemistry: 'none',
      sample: '', ph: null, lsi: null, rsi: null, aggressive_index: null,
      classification: '', by_indices: false, by_ph: false,
      inspection_months: shorter, statement: '',
    };
    var sentences = [];
    if (!sample || !corrosivity) {
      sentences.push(phrase('rising_main.no_sample'));
      sentences.push(phrase('rising_main.kept_unknown', { standard: standard, months: shorter }));
      out.statement = sentences.join(' ');
      return out;
    }

    var name = risingMainSampleName(sample);
    /* the pH the corrosivity indices were computed from, read the same way */
    var ph = sampleValue(sample, 'ph');
    var indexed = ph !== null && corrosivity.lsi !== null && corrosivity.rsi !== null &&
      corrosivity.aggressive_index !== null;
    var byIndices = !!(indexed && corrosivity.is_aggressive);
    var byPh = ph !== null && ph < PH_CORROSIVE_BELOW;
    out.sample = name; out.ph = ph; out.lsi = corrosivity.lsi; out.rsi = corrosivity.rsi;
    out.aggressive_index = corrosivity.aggressive_index;
    out.classification = indexed ? corrosivity.classification : '';
    out.by_indices = byIndices; out.by_ph = byPh;
    /** @type {Rec} */
    var indices = {};
    if (indexed) {
      /* the class as a sentence carries it ("rated strongly corrosive") */
      var cls = corrosivity.classification;
      indices = { rsi: corrosivity.rsi, lsi: signedIndex(corrosivity.lsi),
        ai: corrosivity.aggressive_index,
        classification: cls.charAt(0).toLowerCase() + cls.slice(1) };
    }

    if (byIndices) {
      sentences.push(phrase('rising_main.aggressive', Object.assign({ sample: name }, indices)));
    } else if (byPh) {
      sentences.push(phrase('rising_main.ph_low', { sample: name, ph: phText(ph) }));
      sentences.push(indexed ? phrase('rising_main.ph_low_indices', indices)
        : phrase('rising_main.ph_low_no_indices'));
    } else if (indexed) {
      sentences.push(phrase('rising_main.not_aggressive',
        Object.assign({ sample: name, ph: phText(ph) }, indices)));
    } else {
      sentences.push(phrase('rising_main.no_indices', { sample: name }));
    }

    if (byIndices || byPh) {
      out.chemistry = 'aggressive';
      out.inspection_months = shorter;
      if (sameMaterial(resistant, standard)) {
        sentences.push(phrase('rising_main.same_material', { material: standard, months: shorter }));
      } else {
        out.material = resistant;
        out.upgraded = true;
        sentences.push(phrase('rising_main.specified', { material: resistant,
          standard: standard, months: shorter, usual: usual }));
        sentences.push(phrase('rising_main.alternative'));
      }
    } else if (indexed) {
      out.chemistry = 'not_aggressive';
      out.inspection_months = usual;
      sentences.push(phrase('rising_main.kept', { standard: standard, months: usual }));
    } else {
      out.chemistry = 'incomplete';
      sentences.push(phrase('rising_main.kept_unknown', { standard: standard, months: shorter }));
    }
    out.statement = sentences.join(' ');
    return out;
  }

  /**
   * @param {Rec} [options] rules, log, interpretation, totalDepthM, staticWaterLevelM, screensM, pumpIntakeM, pumpIntakeFloorM, quality (the water quality assessment the rising main is chosen from)
   * @returns {Design}
   */
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

    var asBuilt = false;
    var screensM = opts.screensM;
    if (!(screensM && screensM.length) && log && log.installed_screens_m &&
        log.installed_screens_m.length) {
      /* the sheet records the screens the crew set: those are the screens,
       * and the drawing is an as-built record rather than a design */
      screensM = log.installed_screens_m.map(function (s) { return [s[0], s[1]]; });
      asBuilt = true;
    }
    var intakeFloor = opts.pumpIntakeFloorM === undefined ? null : opts.pumpIntakeFloorM;
    if (screensM && screensM.length) {
      var chosen = analystScreens(screensM, totalDepthM, rules, flags, asBuilt);
      var chosenBasis = chosen.basis;
      if (asBuilt) {
        /* the record as the crew wrote it: where the drawing has had to
         * differ from it, a screen_clipped warning says how */
        chosenBasis = ['screens as installed, recorded on the drilling log (' +
          screensM.map(function (s) { return [Number(s[0]), Number(s[1])]; })
            .sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; })
            .map(function (s) {
              return formatG(s[0]) + '-' + formatG(s[1]) + ' m';
            }).join(', ') + ')'];
      }
      return assembleDesign({
        screens: chosen.screens, basis: chosenBasis, flags: flags,
        totalDepthM: totalDepthM, swl: swl, pumpIntakeM: opts.pumpIntakeM,
        pumpIntakeFloorM: intakeFloor, rules: rules, log: log, asBuilt: asBuilt,
        quality: opts.quality || null,
      });
    }

    var found = targetZones(log, interpretation, swl, totalDepthM, rules);
    var screens = found.zones.map(function (z) { return [z[0], z[1]]; });
    var fallback = [];

    if (!screens.length) {
      /* fall back: screen the bottom third of the hole below the SWL margin,
       * and never inside the grout */
      var below = screenFloor(log, rules, swl, totalDepthM);
      var floor = below.floor;
      var sumpTop = Math.max(totalDepthM - rules.sump_length_m, 0.0);
      var bottom = sumpTop;
      /* rounded to 0.5 m like every other screen top */
      var top = Math.ceil(Math.max(totalDepthM * 2.0 / 3.0, floor) * 2.0) / 2.0;
      if (bottom - top < 3.0) {
        top = Math.max(bottom - rules.screen_length_default_m, floor);
      }
      if (bottom - top < 1.0) {
        /* The static water level margin, or the recorded grout, plus the
         * sump leave no room for a valid screen. Clamp to a positive interval
         * just above the sump so the geometry stays valid and flag it loudly
         * rather than emitting a negative-length screen. The message names
         * whichever of the two is in the way: a grout recorded below the hole
         * was blamed on the static water level. */
        top = Math.max(Math.min(bottom - rules.screen_length_default_m, bottom - 1.0), 0.0);
        var cause = below.sealed
          ? below.why.charAt(0).toUpperCase() + below.why.slice(1)
          : 'Static water level plus the ' + formatG(rules.min_screen_below_swl_m) +
            ' m minimum screen depth';
        flags.push({
          level: 'error', code: 'hole_too_shallow',
          message: cause + ' leaves no room for a screen above the sump in this ' +
            formatG(totalDepthM) + ' m hole. Screen placement is a best effort ' +
            'only - deepen the hole or revise the design manually.',
        });
      }
      screens = [[top, bottom]];
      /* the targets the log names and the design could not screen are listed
       * above this sentence, so it does not say there were none */
      fallback.push((found.targets.length || found.excluded.length
        ? 'none of the aquifer intervals identified from the data can be screened'
        : 'no aquifer intervals identified from the data') +
        '; screens default to the lower third of the hole');
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
      screens: screens, basis: placementBasis(found, screens, rules).concat(fallback),
      flags: flags, totalDepthM: totalDepthM, swl: swl, pumpIntakeM: opts.pumpIntakeM,
      pumpIntakeFloorM: intakeFloor, rules: rules, log: log,
      quality: opts.quality || null,
    });
  }

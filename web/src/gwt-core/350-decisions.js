
  /* ========================================================= decision numbers
   * groundwater/decisions.py (PLAN.md step 3.6). The few numbers a report
   * asks a decision on - the drilling depth, the yield, the pump setting,
   * the chance of a working borehole and the cost - each printed the same
   * way, as its value, its band and what the band rests on, in the words of
   * decision.yaml. Where no band can be given yet the line says why rather
   * than inventing one. The readiness gate reads the same numbers, so a
   * report and the gate over it cannot disagree about which lacks a band.
   * A decision number is a record {key, name, value, band, reason, basis,
   * status}, band null where there is none.
   */

  /** decision_text: the one line every report prints for a decision number.
   * @param {Rec} d a decision number
   * @returns {string} */
  function decisionText(d) {
    var band = d.band !== null ? d.band : phrase('decision.no_band', { reason: d.reason });
    return phrase('decision.line', { name: d.name, value: d.value, band: band,
      basis: d.basis, status: phraseTable('decision.status')[d.status] });
  }

  /** @param {string} key @param {string} name @param {string} value
   * @param {string|null} band @param {string} reason @param {string} basis
   * @param {string} [status]
   * @returns {Rec} */
  function decisionNumber(key, name, value, band, reason, basis, status) {
    return { key: key, name: name, value: value, band: band, reason: reason,
      basis: basis, status: status || 'provisional' };
  }

  /** depth_decision: the best fit's drilling depth, as every report states
   * it, with the band of the depth each sampled model would be drilled to,
   * rounded and cut back as the range's own drilling depth is.
   * @param {Interpretation} interp
   * @param {Rec|null} range the point's range of models, or null
   * @param {Config} [config]
   * @returns {Rec} */
  function depthDecision(interp, range, config) {
    var sid = interp.sounding_id;
    var name = phrase('decision.depth_name', { sid: sid });
    var value = drillingDepthText(interp);
    var spread = depthSpread(range, config);
    if (!spread || !range) {
      return decisionNumber('depth', name, value, null,
        phrase('decision.depth_not_sampled', { sid: sid }),
        phrase('decision.depth_basis_alone'));
    }
    var low = depthDraw(spread, 0.1), high = depthDraw(spread, 0.9);
    var band = low === high ? phrase('decision.depth_band_flat', { low: low })
      : phrase('decision.depth_band', { low: low, high: high });
    return decisionNumber('depth', name, value, band, '',
      phrase('decision.depth_basis', { samples: range.n_samples, step: spread.step_m,
        doi: spread.cap_m }));
  }

  /** yield_decision: the safe yield with step 3.2's band, or null where
   * there is no yield to give.
   * @param {PumpingAnalysis} analysis
   * @param {PumpingConfig} [config]
   * @returns {Rec|null} */
  function yieldDecision(analysis, config) {
    var rec = analysis ? analysis.yield_recommendation : null;
    if (!rec || rec.safe_yield_m3_per_h === null || rec.safe_yield_m3_per_h === undefined) {
      return null;
    }
    var cfg = config || defaultConfig().pumping;
    var name = phrase('decision.yield_name');
    var value = phrase('decision.yield_value', { x: rec.safe_yield_m3_per_h });
    /* "adopted" stands in for a method only on an analysis built by hand */
    var source = analysis.transmissivity_source || '';
    var alone = phrase('decision.yield_basis_alone', {
      method: own(METHOD_LABELS, source) ? METHOD_LABELS[source] : 'adopted',
      reserve: cfg.seasonal_allowance_m });
    var spread = analysis.spread;
    var boot = spread ? spread.bootstrap : null;
    if (!spread || !boot) {
      return decisionNumber('yield', name, value, null,
        phrase('decision.yield_no_spread'), alone);
    }
    if (boot.p10 === null || boot.p10 === undefined) {
      return decisionNumber('yield', name, value, null,
        String(phraseTable('pumping.spread_reasons')[boot.reason]), alone);
    }
    if (spread.safe_yield_low_m3_per_h === null ||
        spread.safe_yield_low_m3_per_h === undefined) {
      return decisionNumber('yield', name, value, null, phrase('decision.yield_no_low'), alone);
    }
    var band = (spread.safe_yield_high_m3_per_h === null ||
        spread.safe_yield_high_m3_per_h === undefined)
      ? phrase('decision.yield_band_open', { low: spread.safe_yield_low_m3_per_h })
      : phrase('decision.yield_band', { low: spread.safe_yield_low_m3_per_h,
        high: spread.safe_yield_high_m3_per_h });
    return decisionNumber('yield', name, value, band, '',
      phrase('decision.yield_basis', { method: METHOD_LABELS[boot.method],
        reserve: cfg.seasonal_allowance_m }));
  }

  /** pump_decision: the pump intake the yield recommendation sets, with the
   * band a dry-season decline moves it over, or null where it sets none.
   * depth is the intake the report prints where that is not the
   * recommendation's, and moved what set it there ('design' or 'seasonal');
   * the band stays the recommendation's, and says so.
   * @param {PumpingAnalysis} analysis
   * @param {number|null} [depth]
   * @param {string|null} [moved]
   * @returns {Rec|null} */
  function pumpDecision(analysis, depth, moved) {
    var rec = analysis ? analysis.yield_recommendation : null;
    var advised = rec ? rec.pump_installation_depth_m : null;
    if (advised === null || advised === undefined) return null;
    var at = advised, basis, bandKey = 'decision.pump_band';
    if (depth === null || depth === undefined || !moved || depth === advised) {
      basis = phrase('decision.pump_basis');
    } else {
      /* the band is the recommendation's, which the printed intake can lie
       * outside, so the band says whose it is */
      at = depth;
      bandKey = 'decision.pump_band_moved';
      basis = phrase('decision.pump_basis_moved', { rec: advised,
        where: String(phraseTable('decision.pump_moved')[moved]) });
    }
    var name = phrase('decision.pump_name');
    var value = phrase('decision.pump_value', { x: at });
    var spread = analysis.spread;
    if (!spread || spread.pump_depth_low_m === null || spread.pump_depth_low_m === undefined) {
      return decisionNumber('pump', name, value, null, phrase('decision.pump_no_spread'), basis);
    }
    return decisionNumber('pump', name, value, phrase(bandKey, {
      decline_low: ENVELOPE_SEASONAL_M[0], decline_high: ENVELOPE_SEASONAL_M[1],
      low: spread.pump_depth_low_m, high: spread.pump_depth_high_m }), '', basis);
  }

  /** odds_decision: the chance of a working borehole at a point, which
   * always has a band, the prior's own carried through the survey's factors.
   * @param {Rec} o what successOdds returns
   * @returns {Rec} */
  function oddsDecision(o) {
    return decisionNumber('odds', phrase('decision.odds_name', { sid: o.sounding_id }),
      phrase('decision.odds_value', { p: rangeShare(o.probability) }),
      phrase('decision.odds_band', { low: rangeShare(o.low), high: rangeShare(o.high) }), '',
      phrase('decision.odds_basis', { n: o.effective_n }),
      o.status === 'calibrated' ? 'calibrated' : 'provisional');
  }

  /** cost_decision: the distribution's P50 with its P10 to P90 and P80, or
   * the bill of quantities with no band where none was sampled; null with
   * neither.
   * @param {Rec|null} d what sampleCost returns
   * @param {Rec|null} [estimate] what estimateBoreholeCost returns
   * @returns {Rec|null} */
  function costDecision(d, estimate) {
    var name = phrase('decision.cost_name');
    if (!d) {
      if (!estimate) return null;
      return decisionNumber('cost', name,
        phrase('decision.cost_value_boq', { boq: costUsd(estimate.price_with_vat_usd) }),
        null, phrase('decision.cost_not_sampled'), phrase('decision.cost_basis_boq'));
    }
    var depth = d.depth_source === null
      ? phrase('decision.cost_depth_fixed', { depth: d.depth_m })
      : phrase('decision.cost_depth_drawn', { sid: d.depth_source });
    /* the curve is the cost at every percent, so a tenth of the way along it
     * and nine tenths are the P10 and P90 of the same sample */
    var last = d.curve.length - 1;
    var tenth = Math.floor(last / 10);
    return decisionNumber('cost', name, phrase('decision.cost_value', { p50: costUsd(d.p50) }),
      phrase('decision.cost_band', { n: costUsd(d.samples), count: d.samples,
        low: costUsd(d.curve[tenth]),
        high: costUsd(d.curve[last - tenth]), p80: costUsd(d.p80) }), '',
      phrase('decision.cost_basis', { depth: depth, boq: costUsd(d.boq_usd) }));
  }

  /* REPORT_DECISIONS: the decision numbers each report asks a decision on.
   * The others decide nothing that has a spread. */
  var REPORT_DECISIONS = {
    geophysical: ['depth', 'odds'],
    pumping: ['yield', 'pump'],
    completion: ['yield', 'pump'],
    handover: ['yield', 'pump'],
    costing: ['cost'],
  };

  /** preferred_index: the position of the point a report recommends, the
   * first-ranked, the earlier of two on one rank, the first where none is.
   * @param {Interpretation[]} interpretations
   * @returns {number|null} */
  function preferredIndex(interpretations) {
    if (!interpretations || !interpretations.length) return null;
    var best = 0;
    interpretations.forEach(function (interp, i) {
      if ((interp.rank || 99) < (interpretations[best].rank || 99)) best = i;
    });
    return best;
  }

  /** recommended_points: the positions of the points a geophysical report
   * recommends drilling, the first-ranked and, where the ranking cannot
   * separate them (tiedLeaders), the second with it: the summary then offers
   * either, so the depth and the odds at both are decision numbers. An order
   * the analyst set is not second-guessed; the caller leaves this out there.
   * @param {Interpretation[]} interpretations
   * @param {Config} [config]
   * @returns {number[]} */
  function recommendedPoints(interpretations, config) {
    var i = preferredIndex(interpretations);
    if (i === null || interpretations.length < 2) return i === null ? [] : [i];
    var ves = (config || defaultConfig()).ves;
    if (!tiedLeaders(assessSiting(interpretations, ves), ves.ranking_tie_points)) return [i];
    return interpretations.map(function (_interp, k) { return k; }).sort(function (a, b) {
      return ((interpretations[a].rank || 99) - (interpretations[b].rank || 99)) || a - b;
    }).slice(0, 2);
  }

  /** decision_numbers: one report's decision numbers, from a project keyed
   * as the readiness gate reads it. A number with nothing to work it out
   * from is left out. The survey's numbers are at state.points, the
   * positions recommendedPoints gives, where the caller has them; the
   * first-ranked point alone otherwise.
   * @param {Rec|null} state
   * @param {string} report
   * @param {Config} [config]
   * @returns {Rec[]} */
  function decisionNumbers(state, report, config) {
    var s = state || {};
    var cfg = config || defaultConfig();
    var wanted = own(REPORT_DECISIONS, report) ? REPORT_DECISIONS[report] : [];
    var out = [];
    var interps = s.interpretations || [];
    var points = s.points;
    if (points === null || points === undefined) {
      var first = preferredIndex(interps);
      points = first === null ? [] : [first];
    }
    var ranges = s.model_ranges || [], odds = s.odds || [];
    points.forEach(function (i) {
      if (wanted.indexOf('depth') >= 0) {
        out.push(depthDecision(interps[i], ranges[i] || null, cfg));
      }
      if (wanted.indexOf('odds') >= 0 && odds[i]) out.push(oddsDecision(odds[i]));
    });
    var analysis = s.pump_analysis;
    if (analysis && wanted.indexOf('yield') >= 0) out.push(yieldDecision(analysis, cfg.pumping));
    if (analysis && wanted.indexOf('pump') >= 0) out.push(pumpDecision(analysis));
    if (wanted.indexOf('cost') >= 0) {
      out.push(costDecision(s.cost_distribution || null, s.cost_estimate || null));
    }
    return out.filter(function (d) { return d !== null; });
  }

  Object.assign(C, {
    decisionText: decisionText, depthDecision: depthDecision, yieldDecision: yieldDecision,
    pumpDecision: pumpDecision, oddsDecision: oddsDecision, costDecision: costDecision,
    REPORT_DECISIONS: REPORT_DECISIONS, preferredIndex: preferredIndex,
    recommendedPoints: recommendedPoints, decisionNumbers: decisionNumbers,
  });


  /* =============================================================== depth spine
   * groundwater/depth_spine/view.py. The whole borehole on one depth axis.
   *
   * This module decides; the page draws. Every number the workspace shows is
   * computed here by the same functions the reports use, so the section, the
   * rail and the bill of quantities cannot drift from the .docx. The page owns
   * only the depth-to-pixel mapping and the pointer.
   */

  function spineFlag(flag) {
    return {
      level: flag.level, code: flag.code || '',
      message: flag.message || '', context: flag.context || '',
    };
  }

  function spineRound(value, places) {
    if (value === null || value === undefined || !isFinite(value)) return null;
    return pyRound(Number(value), places === undefined ? 2 : places);
  }

  var AQUIFER_HINTS = ['fracture', 'water', 'aquifer'];
  var NOT_AQUIFER = ['no water', 'not reached', 'without water'];

  /** Only for shading the log - screen placement uses targetZones.
   * @param {*} description
   * @returns {boolean}
   */
  function looksLikeAquifer(description) {
    var text = String(description || '').toLowerCase();
    var i;
    for (i = 0; i < NOT_AQUIFER.length; i++) {
      if (text.indexOf(NOT_AQUIFER[i]) >= 0) return false;
    }
    for (i = 0; i < AQUIFER_HINTS.length; i++) {
      if (text.indexOf(AQUIFER_HINTS[i]) >= 0) return true;
    }
    return false;
  }

  function spineSection(log, design, analysis, config) {
    var totalDepth = design.total_depth_m;
    /* a little air below the hole so the total-depth line is not on the edge */
    var domain = totalDepth * 1.06;

    var levels = {};
    var swl = design.static_water_level_m;
    if (swl !== null && swl !== undefined) levels.restLevel = spineRound(swl);
    if (analysis) {
      /* The toolkit only calls a level "stabilised" when the last readings
       * agree within 5 cm. When they do not, the honest line to draw is the
       * deepest level reached, labelled as still falling - drawing it as a
       * stabilised pumping level would overstate what the test showed. */
      levels.stabilised = analysis.stabilised_level_m !== null &&
        analysis.stabilised_level_m !== undefined;
      levels.maxDrawdown = spineRound(analysis.max_drawdown_m);
      if (levels.stabilised) {
        levels.pumpingLevel = spineRound(analysis.stabilised_level_m);
      } else if (swl !== null && swl !== undefined &&
                 analysis.max_drawdown_m !== null &&
                 analysis.max_drawdown_m !== undefined) {
        levels.pumpingLevel = spineRound(swl + analysis.max_drawdown_m);
      }
    }
    if (design.pump_intake_m !== null && design.pump_intake_m !== undefined) {
      levels.pumpIntake = spineRound(design.pump_intake_m, 1);
    }

    return {
      totalDepth: totalDepth,
      domain: domain,
      /* One class table for every drawing. Each interval carries the rock it
       * is logged as, and bands carries what the borehole drawing draws: a
       * fracture zone named with its depths is a band of its own wherever
       * those depths fall. The class used to be taken from the whole
       * description, so Dr Timbo's 45-50 m and 55-60 m rows were "Fracture
       * zone" here while the drawing drew them as granite with a zone in and
       * below them. */
      lithology: ((log && log.intervals) || []).map(function (iv) {
        var klass = hostClass(iv.description, iv.top_m, iv.bottom_m);
        return {
          top: iv.top_m, base: iv.bottom_m, description: iv.description,
          aquifer: looksLikeAquifer(iv.description),
          'class': klass.label, colour: klass.colour,
        };
      }),
      bands: lithologyBands((log && log.intervals) || []).map(function (b) {
        return { top: b.top_m, base: b.bottom_m, 'class': b.label, colour: b.colour };
      }),
      waterStrikes: (design.water_strikes_m || []).slice(),
      segments: (design.segments || []).map(function (s) {
        return { kind: s.kind, top: s.top_m, base: s.bottom_m };
      }),
      gravelPack: (design.gravel_pack || []).slice(),
      annularFill: design.annular_fill === undefined ? 'gravel pack' : design.annular_fill,
      backfill: (design.backfill || []).slice(),
      sanitarySeal: (design.sanitary_seal || []).slice(),
      levels: levels,
      boreDiameterIn: design.borehole_diameter_in,
      casingDiameterIn: design.casing_diameter_in,
      casingMaterial: design.casing_material,
      slotMm: design.screen_slot_mm,
      stickupM: design.stickup_m,
      drillingMethod: (log && log.drilling_method) || '',
      /* the handles may not move a screen outside this band */
      screenLimits: {
        top: 0.0,
        base: totalDepth - config.design.sump_length_m,
        minLength: 0.5,
      },
    };
  }

  /* Cross-method transmissivity, so agreement is visible rather than claimed. */
  function spineMethods(analysis) {
    var out = [];
    [['Cooper-Jacob', analysis.cooper_jacob], ['Theis', analysis.theis],
      ['Recovery', analysis.recovery]].forEach(function (pair) {
      if (!pair[1]) return;
      out.push({
        label: pair[0],
        transmissivity: spineRound(pair[1].transmissivity_m2_per_day),
      });
    });
    return out;
  }

  function spineDesignDecisions(design, analysis, config) {
    var rules = config.design;
    var yieldBlock = { pending: 'No pumping test loaded for this borehole.' };

    if (analysis && analysis.yield_recommendation) {
      var rec = analysis.yield_recommendation;
      yieldBlock = {
        pending: rec.pending_reason || '',
        safeYieldM3PerH: spineRound(rec.safe_yield_m3_per_h),
        lowM3PerH: spineRound(rec.safe_yield_low_m3_per_h),
        highM3PerH: spineRound(rec.safe_yield_high_m3_per_h),
        rangeText: rec.yield_range_text || yieldRangeText(rec),
        longTermM3PerH: spineRound(rec.long_term_yield_m3_per_h),
        specificCapacity: spineRound(rec.specific_capacity_m3hr_per_m),
        availableDrawdownM: spineRound(rec.available_drawdown_m),
        usableDrawdownM: spineRound(rec.usable_drawdown_m),
        pumpDepthM: spineRound(rec.pump_installation_depth_m, 1),
        safetyFactor: rec.safety_factor,
        designPeriodDays: rec.design_period_days,
        basis: rec.basis,
        envelopeBasis: rec.envelope_basis,
        transmissivity: spineRound(analysis.transmissivity_m2_per_day),
        methods: spineMethods(analysis),
      };
    }

    return {
      yield: yieldBlock,
      screens: (design.screens || []).map(function (s) {
        return { top: s.top_m, base: s.bottom_m };
      }),
      totalScreenM: spineRound(design.total_screen_length_m, 1),
      screenShare: spineRound(
        design.total_screen_length_m / design.total_depth_m * 100, 1),
      slotMm: design.screen_slot_mm,
      rules: {
        sumpLengthM: rules.sump_length_m,
        gravelAboveTopScreenM: rules.gravel_pack_above_top_screen_m,
        sanitarySealDepthM: rules.sanitary_seal_depth_m,
        minScreenBelowSwlM: rules.min_screen_below_swl_m,
        submergenceMinM: config.pumping.pump_submergence_min_m,
        seasonalAllowanceM: config.pumping.seasonal_allowance_m,
      },
      basis: (design.design_basis || []).slice(),
      flags: (design.flags || []).map(spineFlag)
        .concat(analysis ? (analysis.flags || []).map(spineFlag) : []),
    };
  }

  /** The limit a row is judged against, and what kind of limit it is.
   *
   * The strictest applicable maximum binds. Which one it was matters in the
   * report - a national limit exceeded is a compliance failure, an
   * acceptability limit exceeded is a taste complaint - so the name travels
   * with the number.
   * @param {Rec} row a row of assessSample's table
   * @returns {[Limit|null, string]}
   */
  function bindingLimit(row) {
    /** @type {Array<[string, Limit|null]>} */
    var candidates = [
      ['WHO health', parseLimit(row.who_health)],
      ['WHO acceptability', parseLimit(row.who_aesthetic)],
      ['national', parseLimit(row.sl_standard)],
    ];
    /** @type {[Limit|null, string]} */
    var best = [null, ''];
    for (var i = 0; i < candidates.length; i++) {
      var name = candidates[i][0], limit = candidates[i][1];
      if (!limit) continue;
      if (limit.minimum !== null && limit.minimum !== undefined) return [limit, name];
      if (limit.maximum === null || limit.maximum === undefined) continue;
      if (!best[0] || limit.maximum < best[0].maximum) best = [limit, name];
    }
    return best;
  }

  /* Cation and anion percentages for the Piper and Stiff plots. Reuses the
   * milliequivalents the ionic balance already worked out, so the diagrams and
   * the balance check can never disagree. */
  function spinePiper(assessment) {
    if (!assessment.ionic) return null;
    var cations = assessment.ionic.cations_meq || {};
    var anions = assessment.ionic.anions_meq || {};
    function total(map) {
      return Object.keys(map).reduce(function (a, k) { return a + (map[k] || 0); }, 0);
    }
    var totalC = total(cations), totalA = total(anions);
    if (totalC <= 0 || totalA <= 0) return null;
    function c(key) { return cations[key] || 0.0; }
    function a(key) { return anions[key] || 0.0; }
    var naK = c('sodium') + c('potassium');
    return {
      meq: {
        ca: spineRound(c('calcium'), 4), mg: spineRound(c('magnesium'), 4),
        naK: spineRound(naK, 4), hco3: spineRound(a('bicarbonate'), 4),
        cl: spineRound(a('chloride'), 4), so4: spineRound(a('sulfate'), 4),
      },
      percent: {
        ca: spineRound(c('calcium') / totalC, 4),
        mg: spineRound(c('magnesium') / totalC, 4),
        naK: spineRound(naK / totalC, 4),
        hco3: spineRound(a('bicarbonate') / totalA, 4),
        cl: spineRound(a('chloride') / totalA, 4),
        so4: spineRound(a('sulfate') / totalA, 4),
      },
    };
  }

  /** How far a value sits towards, or past, its binding limit: view.py
   * _limit_ratio. Against a range it is the larger of the value over the top
   * and the bottom over the value, so a value outside the range is past the
   * line on whichever side it falls; the value over the top alone drew the
   * Dr Timbo sample's pH of 5.9 at 0.69 times its 6.5 to 8.5 limit, on the
   * compliant side. A value of zero or less under a range that starts above
   * zero has no ratio.
   * @param {number|null|undefined} value in the guideline's unit
   * @param {Rec} limit
   * @returns {number|null}
   */
  function spineLimitRatio(value, limit) {
    if (value === null || value === undefined || !limit.maximum) return null;
    var ratio = Number(value) / Number(limit.maximum);
    if (limit.minimum) {
      if (value <= 0) return null;
      ratio = Math.max(ratio, Number(limit.minimum) / Number(value));
    }
    return ratio;
  }

  /** @param {QualityAssessment} assessment */
  function spineQuality(assessment) {
    var rows = (assessment.rows || []).map(function (r) {
      var pair = bindingLimit(r);
      var limit = pair[0], limitName = pair[1];
      /* the chart plots every determinand as a multiple of its own limit, so
       * the ratio is computed here rather than by parsing limit strings in
       * the page */
      var ratio = null, kind = 'none';
      if (limit) {
        kind = (limit.minimum !== null && limit.minimum !== undefined) ? 'range' : 'max';
        /* The limit is written in the guideline's unit, so the value has to
         * be on that scale too. Dividing the raw reported number by it drew
         * a compliant ug/L result a thousand times past its line. */
        ratio = spineLimitRatio(r.value_in_guideline_unit, limit);
      }
      return {
        parameter: r.parameter, value: spineRound(r.value, 4), unit: r.unit,
        valueInGuidelineUnit: spineRound(r.value_in_guideline_unit, 4),
        guidelineUnit: r.guideline_unit || '',
        evaluable: r.evaluable !== false,
        reason: r.reason || '',
        belowDetection: !!r.below_detection,
        whoHealth: r.who_health, whoAesthetic: r.who_aesthetic,
        national: r.sl_standard, status: r.status, remark: r.remark,
        limitKind: kind, limitName: limitName,
        limitMax: limit ? spineRound(limit.maximum, 4) : null,
        limitMin: limit ? spineRound(limit.minimum, 4) : null,
        ratio: spineRound(ratio, 4),
      };
    });

    function roundMap(map) {
      var out = {};
      Object.keys(map || {}).forEach(function (k) { out[k] = spineRound(map[k], 4); });
      return out;
    }

    var ionic = null;
    if (assessment.ionic) {
      var i = assessment.ionic;
      ionic = {
        cationsMeq: spineRound(i.sum_cations_meq, 3),
        anionsMeq: spineRound(i.sum_anions_meq, 3),
        errorPercent: spineRound(i.error_percent, 2),
        cations: roundMap(i.cations_meq), anions: roundMap(i.anions_meq),
        usedAlkalinity: !!i.used_alkalinity_for_bicarbonate,
      };
    }

    var corrosivity = null;
    if (assessment.corrosivity) {
      var cor = assessment.corrosivity;
      corrosivity = {
        lsi: spineRound(cor.lsi), rsi: spineRound(cor.rsi),
        aggressiveIndex: spineRound(cor.aggressive_index),
        larsonSkold: spineRound(cor.larson_skold),
        classification: cor.classification, isAggressive: !!cor.is_aggressive,
        verdict: cor.verdict, materialsNote: cor.materials_note,
        assumptions: (cor.assumptions || []).slice(),
      };
    }

    return {
      sampleId: assessment.sample ? assessment.sample.sample_id : '',
      sampleDate: assessment.sample ? assessment.sample.sample_date : '',
      laboratory: assessment.sample ? assessment.sample.laboratory : '',
      rows: rows,
      verdict: assessment.verdict,
      verdictState: assessment.verdict_state,
      uncertainties: (assessment.uncertainties || []).slice(),
      healthExceedances: (assessment.health_exceedances || [])
        .map(function (r) { return r.parameter; }),
      nationalExceedances: (assessment.national_exceedances || [])
        .map(function (r) { return r.parameter; }),
      aestheticExceedances: (assessment.aesthetic_exceedances || [])
        .map(function (r) { return r.parameter; }),
      indeterminate: (assessment.indeterminate_rows || [])
        .map(function (r) { return r.parameter; }),
      ionic: ionic,
      piper: spinePiper(assessment),
      corrosivity: corrosivity,
      wqi: assessment.wqi
        ? { value: spineRound(assessment.wqi.value, 1), rating: assessment.wqi.rating }
        : null,
      flags: (assessment.flags || []).map(spineFlag),
    };
  }

  function spineCosting(estimate) {
    var items = (estimate.items || []).map(function (i) {
      return {
        code: i.code, stage: i.stage, category: i.category, item: i.item,
        unit: i.unit, quantity: spineRound(i.quantity, 3),
        unitCost: spineRound(i.unit_cost_usd), amount: spineRound(i.amount_usd),
        note: i.note || '',
      };
    });

    function group(key) {
      var totals = {}, order = [];
      (estimate.items || []).forEach(function (i) {
        if (!(i[key] in totals)) { totals[i[key]] = 0.0; order.push(i[key]); }
        totals[i[key]] += i.amount_usd;
      });
      var direct = estimate.direct_cost_usd || 1.0;
      return order.map(function (label) {
        return {
          label: label, amount: spineRound(totals[label]),
          share: spineRound(totals[label] / direct * 100, 1),
        };
      }).sort(function (/** @type {Rec} */ a, /** @type {Rec} */ b) {
        return b.amount - a.amount;
      });
    }

    return {
      items: items, byStage: group('stage'), byCategory: group('category'),
      directCost: spineRound(estimate.direct_cost_usd),
      overheads: spineRound(estimate.overheads_usd),
      totalCost: spineRound(estimate.total_cost_usd),
      margin: spineRound(estimate.margin_usd),
      price: spineRound(estimate.price_usd),
      vat: spineRound(estimate.vat_usd),
      costPerMetre: spineRound(estimate.cost_per_meter_usd),
      overheadsPercent: estimate.overheads_percent,
      marginPercent: estimate.margin_percent,
      contingencyPercent: estimate.contingency_percent,
      vatPercent: estimate.vat_percent,
      exchangeRate: estimate.exchange_rate_sle_per_usd,
      assumptions: (estimate.assumptions || []).slice(),
      flags: (estimate.flags || []).map(spineFlag),
      quantityBasis: {
        totalDepthM: estimate.inputs.total_depth_m,
        casingM: spineRound(estimate.inputs.casing_m, 1),
        screenM: spineRound(estimate.inputs.screen_m, 1),
        gravelIntervalM: spineRound(estimate.inputs.gravel_interval_m, 1),
        overburdenM: spineRound(estimate.inputs.overburden_m, 1),
      },
    };
  }

  /** Derive the whole workspace from the analysis objects.
   *
   * ``screensM`` is the analyst's screen placement from the section. Passing it
   * re-runs the design and everything downstream of it - the annulus, the
   * checks and the bill of quantities - so the drawing and the BoQ are always
   * the same design.
   * @param {Rec} inputs config, analysis, log, interpretation, assessment and the rest the workspace reads
   * @param {number[][]|null} [screensM] the analyst's screen placement
   */
  function buildSpineView(inputs, screensM) {
    var config = inputs.config || defaultConfig();
    var analysis = inputs.analysis || null;
    var log = inputs.log;
    if (!log) throw new Error('the Depth Spine needs a drilling log');
    var swl = null, pumpIntake = null, intakeFloor = null;
    if (analysis) {
      swl = analysis.test ? analysis.test.static_water_level_m : null;
      if (analysis.yield_recommendation) {
        pumpIntake = analysis.yield_recommendation.pump_installation_depth_m;
        intakeFloor = pumpIntakeFloor(analysis.yield_recommendation,
          config.pumping.pump_submergence_min_m);
      }
    }

    var assessment = inputs.assessment || null;
    if (!assessment && inputs.quality) assessment = assessSample(inputs.quality);

    var design = designBorehole({
      log: log, staticWaterLevelM: swl, pumpIntakeM: pumpIntake,
      pumpIntakeFloorM: intakeFloor, rules: config.design,
      screensM: screensM && screensM.length ? screensM : null,
      /* the rising main, and so the bill, follow the sample */
      quality: assessment,
    });

    /* The spine's price is signed off by a named person, so it has to be the
     * price the Costing page shows. That means the rates the analyst edited
     * and the overheads, margin, contingency, VAT and exchange rate they set
     * - not the catalogue defaults. Only the quantities differ, and they
     * differ because the screens on the section moved. */
    var money = inputs.costing || {};
    var costInputs = inputsFromDesign(design, {
      mobilisationDistanceKm: inputs.mobilisationDistanceKm || 0.0,
      overburdenM: money.overburdenM,
    });
    if (money.wqSamples !== undefined && money.wqSamples !== null) {
      costInputs.wq_samples = money.wqSamples;
    }
    if (money.handpumps !== undefined && money.handpumps !== null) {
      costInputs.handpumps = money.handpumps;
    }
    /* the Streamlit Costing page sets the pumping hours too (view.py
     * SpineCosting); the browser's leaves them at the defaults */
    if (money.developmentHours !== undefined && money.developmentHours !== null) {
      costInputs.development_hours = money.developmentHours;
    }
    if (money.testPumpingHours !== undefined && money.testPumpingHours !== null) {
      costInputs.test_pumping_hours = money.testPumpingHours;
    }
    var estimate = estimateBoreholeCost(costInputs, money.rates || null, {
      overheadsPercent: money.overheadsPercent,
      marginPercent: money.marginPercent,
      contingencyPercent: money.contingencyPercent,
      vatPercent: money.vatPercent,
      exchangeRate: money.exchangeRate,
    });

    var site = log.site || {};
    var latlon = null;
    if (site.easting && site.northing) {
      var zone = Number(site.utm_zone) || inferZoneForSierraLeone(Number(site.easting));
      var ll = utmToGeographic(Number(site.easting), Number(site.northing), zone);
      if (ll) latlon = [ll.lat, ll.lon];
    }

    /** @type {Rec} */
    var payload = {
      project: inputs.name || site.community || 'Borehole',
      site: {
        community: site.community || '', district: site.district || '',
        chiefdom: site.chiefdom || '', client: site.client || '',
        boreholeRef: log.borehole_ref || '', latlon: latlon,
      },
      section: spineSection(log, design, analysis, config),
      design: spineDesignDecisions(design, analysis, config),
      costing: spineCosting(estimate),
      quality: null,
      edited: !!(screensM && screensM.length),
    };

    if (assessment) payload.quality = spineQuality(assessment);
    return payload;
  }

  Object.assign(C, {
    buildSpineView: buildSpineView, bindingLimit: bindingLimit,
    spineQuality: spineQuality,
    looksLikeAquifer: looksLikeAquifer,
  });


  /* ================================================================ costing
   * groundwater/costing/*. Follows the RWSN Borehole Costing Model: every line
   * carries a construction stage and a resource category so the same items
   * roll up along both axes, and the contractor's COST is kept distinct from
   * the client's PRICE (cost + overheads + margin).
   */

  var STAGES = ['Siting', 'Mobilisation', 'Drilling', 'Casing', 'Development',
    'Test pumping', 'Water quality', 'Wellhead'];
  var RESOURCE_CATEGORIES = ['equipment', 'labour', 'consumables', 'fuel', 'vehicles'];
  var DEFAULT_EXCHANGE_RATE_SLE_PER_USD = 23.0;
  /* the stages an attempt that finds no water still pays for: _DRY_STAGES.
   * The programme estimate, the cost distribution and the risk-loaded price
   * all count a dry attempt so. */
  var DRY_STAGES = ['Siting', 'Mobilisation', 'Drilling'];
  /* The quantity basis that prices a rising main in place of the one the
   * handpump line includes, by material in lower case: RISING_MAIN_BASES in
   * costing/model.py. A material with none, or none in the catalogue, is
   * flagged on the estimate as unpriced. */
  /** @type {Record<string, string>} */
  var RISING_MAIN_BASES = { 'stainless steel': 'per_m_rising_main_stainless_steel' };

  /** @param {string} material */
  function risingMainBasis(material) {
    var key = trimField(material).toLowerCase();
    return own(RISING_MAIN_BASES, key) ? RISING_MAIN_BASES[key] : null;
  }

  /* a dry attempt does not pay this basis: the rig has made the journey */
  var COST_JOURNEY = 'per_km_round_trip';

  /** The rate catalogue: load_rates. min_usd and max_usd are the ends of
   * the triangle the cost distribution draws the rate from, unit_cost_usd
   * its likely value; a blank one is the likely value itself, and a pair
   * that does not bracket it is refused, naming the row.
   * @param {Rec[]|null} [rows] the bundled rates when not given */
  function loadRates(rows) {
    var source = rows || (GWT.data && GWT.data.costItems) || [];
    return source.map(function (row) {
      function bound(key) {
        var text = String(row[key] === undefined || row[key] === null ? '' : row[key]).trim();
        return text ? Number(text) : null;
      }
      var rate = {
        code: String(row.code || '').trim(),
        stage: String(row.stage || '').trim(),
        category: String(row.category || '').trim().toLowerCase(),
        item: String(row.item || '').trim(),
        unit: String(row.unit || '').trim(),
        quantity_basis: String(row.quantity_basis || '').trim(),
        unit_cost_usd: Number(row.unit_cost_usd),
        note: String(row.note || '').trim(),
        min_usd: bound('min_usd'),
        max_usd: bound('max_usd'),
        spread_group: String(row.spread_group || '').trim(),
      };
      var t = rateTriangle(rate);
      if (!(t[0] <= t[1] && t[1] <= t[2])) {
        throw new Error('rate ' + rate.code + ': the minimum ' + formatG(t[0]) +
          ' and maximum ' + formatG(t[2]) + ' must bracket the likely rate ' + formatG(t[1]));
      }
      return rate;
    });
  }

  /** A rate's [minimum, likely, maximum]: RateItem.triangle.
   * @param {Rec} rate
   * @returns {number[]} */
  function rateTriangle(rate) {
    var likely = rate.unit_cost_usd;
    return [rate.min_usd === null || rate.min_usd === undefined ? likely : rate.min_usd,
      likely, rate.max_usd === null || rate.max_usd === undefined ? likely : rate.max_usd];
  }

  /** The rate with its likely value edited and its minimum and maximum
   * scaled by the same factor, so it keeps its relative spread:
   * RateItem.with_likely. A rate that was zero takes no spread.
   * @param {Rec} rate
   * @param {number} value
   * @returns {Rec} */
  function rateWithLikely(rate, value) {
    var t = rateTriangle(rate);
    var v = Number(value);
    if (t[1] === v) return Object.assign({}, rate);
    if (t[1] === 0) return Object.assign({}, rate, { unit_cost_usd: v, min_usd: v, max_usd: v });
    var factor = v / t[1];
    return Object.assign({}, rate, { unit_cost_usd: v, min_usd: t[0] * factor,
      max_usd: t[2] * factor });
  }

  /* The rules of thumb that fill a quantity nobody supplied, as functions of
   * the depth (default_overburden_m and the rest in costing/model.py): the
   * cost distribution applies them again at every depth it draws. */
  /** @param {number} depthM */
  function defaultOverburdenM(depthM) { return Math.min(30.0, 0.5 * depthM); }
  /**
   * @param {number} depthM
   * @param {number} screenM
   */
  function defaultCasingM(depthM, screenM) { return Math.max(0.0, depthM + 0.5 - screenM); }
  /** @param {number} depthM */
  function defaultGravelIntervalM(depthM) { return Math.max(0.0, depthM - 15.0); }
  /** @param {number} depthM */
  function defaultCrewDays(depthM) { return Math.ceil(depthM / 25.0) + 4; }

  /** Volume of the borehole/casing annulus; the allowance covers washout and
   * placement losses (1.3 is common for gravel pack ordering).
   * @param {number} boreholeDiameterIn
   * @param {number} casingDiameterIn
   * @param {number} intervalM
   * @param {number} [allowance]
   * @returns {number}
   */
  function annulusVolumeM3(boreholeDiameterIn, casingDiameterIn, intervalM, allowance) {
    var toM = 0.0254;
    var dBore = boreholeDiameterIn * toM, dCasing = casingDiameterIn * toM;
    var area = Math.PI / 4.0 * Math.max(0.0, dBore * dBore - dCasing * dCasing);
    return area * Math.max(0.0, intervalM) * (allowance === undefined ? 1.0 : allowance);
  }

  /**
   * @param {Rec|null} [values]
   * @returns {Rec}
   */
  function costingInputs(values) {
    return Object.assign({
      total_depth_m: 0, overburden_m: null, casing_m: null, screen_m: null,
      borehole_diameter_in: 6.5, casing_diameter_in: 5.0,
      gravel_interval_m: null, cement_bags: null, crew_days: null,
      /* the seal the cement is worked out for when cement_bags is not
       * given; null means the design rules' default */
      sanitary_seal_m: null,
      development_hours: 6.0, test_pumping_hours: 30.0,
      mobilisation_distance_km: 0.0, wq_samples: 1, handpumps: 1,
      /* the rising main the design specifies in place of the handpump
       * line's, and its length (the pump intake); blank prices the line as
       * it is, and a null length takes the total depth and says so */
      rising_main_material: '', rising_main_m: null,
    }, values || {});
  }

  /* Fill missing fields from documented rules of thumb, recording every
   * assumption on the estimate so nothing is hidden. */
  /* bags of cement for a grout seal over sealM of annulus: about 20 bags per
   * cubic metre, never fewer than four */
  function cementBagsForSeal(boreholeIn, casingIn, sealM) {
    var volume = annulusVolumeM3(boreholeIn, casingIn, sealM);
    return Math.max(4.0, Math.ceil(volume * 20.0));
  }

  /** @param {Rec} inputs what costingInputs returns */
  function resolveCostingInputs(inputs) {
    var r = Object.assign({}, inputs);
    var assumptions = [];
    if (r.overburden_m === null || r.overburden_m === undefined) {
      r.overburden_m = defaultOverburdenM(r.total_depth_m);
      assumptions.push('Overburden thickness assumed ' + fmtNum(r.overburden_m) +
        ' m (half the total depth, at most 30 m); supply the real split from ' +
        'the drilling log or the VES interpretation.');
    }
    r.overburden_m = Math.min(r.overburden_m, r.total_depth_m);
    if (r.screen_m === null || r.screen_m === undefined) {
      r.screen_m = 9.0;
      assumptions.push('Screen length assumed 9 m (design default).');
    }
    if (r.casing_m === null || r.casing_m === undefined) {
      r.casing_m = defaultCasingM(r.total_depth_m, r.screen_m);
      assumptions.push('Plain casing length taken as ' + fmtNum(r.casing_m) +
        ' m (total depth plus 0.5 m stick-up minus the screen length).');
    }
    if (r.gravel_interval_m === null || r.gravel_interval_m === undefined) {
      r.gravel_interval_m = defaultGravelIntervalM(r.total_depth_m);
      assumptions.push('Gravel packed interval assumed ' +
        fmtNum(r.gravel_interval_m) + ' m (from 15 m below ground to the ' +
        'bottom of the borehole).');
    }
    if (r.cement_bags === null || r.cement_bags === undefined) {
      /* the seal the design rules draw, not a 15 m one nobody drew */
      var sealM = (r.sanitary_seal_m === null || r.sanitary_seal_m === undefined)
        ? defaultConfig().design.sanitary_seal_depth_m : r.sanitary_seal_m;
      r.cement_bags = cementBagsForSeal(r.borehole_diameter_in, r.casing_diameter_in, sealM);
      assumptions.push('Cement estimated at ' + fmtNum(r.cement_bags) +
        ' bags for a ' + fmtNum(sealM) + ' m grout seal (about 20 bags per cubic ' +
        'metre of annulus).');
    }
    if (r.crew_days === null || r.crew_days === undefined) {
      r.crew_days = defaultCrewDays(r.total_depth_m);
      assumptions.push('Crew time assumed ' + fmtNum(r.crew_days) + ' days on ' +
        'site (drilling at 25 m per day plus four days for moving, set up, ' +
        'development, testing and completion).');
    }
    if (r.rising_main_material && r.handpumps > 0 &&
        (r.rising_main_m === null || r.rising_main_m === undefined)) {
      r.rising_main_m = r.total_depth_m;
      assumptions.push(phrase('rising_main.length_assumed', { depth: r.rising_main_m }));
    }
    r.bedrock_m = Math.max(0.0, r.total_depth_m - (r.overburden_m || 0.0));
    r.gravel_pack_m3 = annulusVolumeM3(r.borehole_diameter_in, r.casing_diameter_in,
      r.gravel_interval_m || 0.0, 1.3);
    return { inputs: r, assumptions: assumptions };
  }

  /** Casing and screen lengths, diameters and the gravel packed interval come
   * straight from the design so the bill of quantities always matches the
   * drawing.
   * @param {Design} design
   * @param {Rec} [options] overburdenM, mobilisationDistanceKm
   * @returns {Rec}
   */
  function inputsFromDesign(design, options) {
    var opts = options || {};
    var screenM = design.total_screen_length_m;
    /* an annulus too thin to take a pack is priced as none: the bill used
     * to carry gravel the drawing's own flag said could not be placed */
    var packed = (design.annular_fill === undefined ? 'gravel pack'
      : design.annular_fill) !== 'none';
    /* the rising main the water calls for, over the pump intake depth */
    var choice = design.rising_main || {};
    var upgraded = !!choice.upgraded;
    return costingInputs({
      total_depth_m: design.total_depth_m,
      overburden_m: opts.overburdenM === undefined ? null : opts.overburdenM,
      casing_m: Math.max(0.0, design.total_depth_m + design.stickup_m - screenM),
      screen_m: screenM,
      borehole_diameter_in: design.borehole_diameter_in,
      casing_diameter_in: design.casing_diameter_in,
      gravel_interval_m: packed
        ? Math.max(0.0, design.gravel_pack[1] - design.gravel_pack[0]) : 0.0,
      cement_bags: cementBagsForSeal(
        design.borehole_diameter_in, design.casing_diameter_in,
        Math.max(0.0, design.sanitary_seal[1] - design.sanitary_seal[0])
      ),
      mobilisation_distance_km: opts.mobilisationDistanceKm || 0.0,
      rising_main_material: upgraded ? String(choice.material || '') : '',
      rising_main_m: upgraded && design.pump_intake_m !== undefined
        ? design.pump_intake_m : null,
    });
  }

  function quantityFor(basis, inputs) {
    var table = quantityTable(inputs);
    return basis in table ? table[basis] : null;
  }

  /** The quantity of every basis the estimate knows: _quantity_table.
   * @param {Rec} inputs resolved
   * @returns {Object<string, number>} */
  function quantityTable(inputs) {
    var chosen = risingMainBasis(inputs.rising_main_material);
    var rising = (inputs.rising_main_m || 0.0) * Number(inputs.handpumps);
    /** @type {Object<string, number>} */
    var table = {
      lump_sum: 1.0,
      per_km_round_trip: 2.0 * inputs.mobilisation_distance_km,
      per_crew_day: inputs.crew_days || 0.0,
      per_m_drilled: inputs.total_depth_m,
      per_m_overburden: inputs.overburden_m || 0.0,
      per_m_bedrock: inputs.bedrock_m,
      per_m_casing: inputs.casing_m || 0.0,
      per_m_screen: inputs.screen_m || 0.0,
      per_m3_gravel: inputs.gravel_pack_m3,
      per_bag_cement: inputs.cement_bags || 0.0,
      per_hour_development: inputs.development_hours,
      per_hour_test: inputs.test_pumping_hours,
      per_sample: Number(inputs.wq_samples),
      per_handpump: Number(inputs.handpumps),
    };
    Object.keys(RISING_MAIN_BASES).forEach(function (key) {
      var basis = RISING_MAIN_BASES[key];
      table[basis] = basis === chosen ? rising : 0.0;
    });
    return table;
  }

  /** Percentage defaults follow the RWSN costing and pricing guidance:
   * overheads on top of direct works cost, then a margin that keeps the
   * business viable; the contingency is a client-side planning allowance,
   * shown separately so the contract price stays honest.
   * @param {Rec} inputs what costingInputs returns
   * @param {Rec[]|null} [rates] what loadRates returns
   * @param {Rec} [options] overheadsPercent, marginPercent, contingencyPercent, vatPercent, exchangeRate
   */
  function estimateBoreholeCost(inputs, rates, options) {
    var opts = options || {};
    if (inputs.total_depth_m <= 0) throw new Error('total depth must be positive');
    var resolved = resolveCostingInputs(inputs);
    var catalogue = rates || loadRates();
    var items = [], flags = [];

    catalogue.forEach(function (rate) {
      var quantity = quantityFor(rate.quantity_basis, resolved.inputs);
      if (quantity === null) {
        flags.push({
          level: 'warning', code: 'unknown_quantity_basis',
          message: 'Rate ' + rate.code + " uses unknown quantity basis '" +
            rate.quantity_basis + "' and was skipped.",
          context: rate.code,
        });
        return;
      }
      if (quantity <= 0) return;
      items.push({
        code: rate.code, stage: rate.stage, category: rate.category,
        item: rate.item, unit: rate.unit, quantity: quantity,
        unit_cost_usd: rate.unit_cost_usd, note: rate.note,
        /* so that the journey from the base can be told from the other
         * mobilisation lines */
        quantity_basis: rate.quantity_basis,
        amount_usd: quantity * rate.unit_cost_usd,
      });
    });

    var held = resolved.inputs;
    if (held.rising_main_material && held.handpumps > 0 && (held.rising_main_m || 0.0) > 0) {
      var basis = risingMainBasis(held.rising_main_material);
      var priced = basis !== null && catalogue.some(function (rate) {
        return rate.quantity_basis === basis;
      });
      /* fail closed: the bill still carries the handpump line's main */
      if (!priced) {
        flags.push({
          level: 'warning', code: 'rising_main_unpriced',
          message: phrase('rising_main.unpriced', { material: held.rising_main_material }),
        });
      }
    }
    if (resolved.inputs.mobilisation_distance_km <= 0) {
      flags.push({
        level: 'info', code: 'no_mobilisation_distance',
        message: 'Mobilisation distance is zero; transport costs are not ' +
          "included. Enter the one way distance from the contractor's base " +
          'to the site.',
      });
    }

    return buildEstimate(items, resolved.inputs, resolved.assumptions, flags, {
      overheads_percent: opts.overheadsPercent === undefined ? 15.0 : opts.overheadsPercent,
      margin_percent: opts.marginPercent === undefined ? 20.0 : opts.marginPercent,
      contingency_percent: opts.contingencyPercent === undefined ? 10.0 : opts.contingencyPercent,
      vat_percent: opts.vatPercent === undefined ? 0.0 : opts.vatPercent,
      exchange_rate_sle_per_usd: opts.exchangeRate === undefined
        ? DEFAULT_EXCHANGE_RATE_SLE_PER_USD : opts.exchangeRate,
    });
  }

  function buildEstimate(items, inputs, assumptions, flags, pct) {
    var direct = items.reduce(function (a, i) { return a + i.amount_usd; }, 0);
    var overheads = direct * pct.overheads_percent / 100.0;
    var totalCost = direct + overheads;
    var margin = totalCost * pct.margin_percent / 100.0;
    var price = totalCost + margin;
    var vat = price * pct.vat_percent / 100.0;
    var priceWithVat = price + vat;
    var contingency = priceWithVat * pct.contingency_percent / 100.0;

    var estimate = Object.assign({
      items: items, inputs: inputs, assumptions: assumptions, flags: flags,
      direct_cost_usd: direct,
      overheads_usd: overheads,
      total_cost_usd: totalCost,
      margin_usd: margin,
      price_usd: price,
      vat_usd: vat,
      price_with_vat_usd: priceWithVat,
      contingency_usd: contingency,
      budget_usd: priceWithVat + contingency,
      cost_per_meter_usd: inputs.total_depth_m ? totalCost / inputs.total_depth_m : 0.0,
    }, pct);

    /* An attempt that finds no water: its siting, set-up and drilling lines,
     * without the journey from the base, added stage by stage as the
     * programme estimate adds them (dry_attempt_direct_usd), and priced as
     * the borehole is (dry_attempt_price_usd). */
    var dryTotals = DRY_STAGES.map(function (stage) {
      return items.reduce(function (a, i) {
        return i.stage === stage && i.quantity_basis !== COST_JOURNEY ? a + i.amount_usd : a;
      }, 0.0);
    });
    estimate.dry_attempt_direct_usd = dryTotals.reduce(function (a, v) { return a + v; }, 0);
    estimate.dry_attempt_price_usd = costPrice(estimate.dry_attempt_direct_usd,
      pct.overheads_percent, pct.margin_percent, pct.vat_percent);

    estimate.in_local = function (usd) { return usd * pct.exchange_rate_sle_per_usd; };
    /** price_per_successful_well_usd: the risk-loaded price under a no water,
     * no pay contract. The client pays nothing for an attempt that finds no
     * water, so each successful borehole carries the (1 - p) / p attempts
     * expected to fail before it, each at failedAttemptUsd: by default the
     * dry attempt the programme estimate and the cost distribution count.
     * What a failure costs is what has been done to the hole when it is
     * judged, which the contract and the ground decide (RWSN's pricing guide:
     * in mud drilling in sediments, only once the casing and screens are
     * in); the borehole's own price with VAT prices every failure as a whole
     * completed borehole, which is what this returned before (the price over
     * the success rate).
     * @param {number} successRatePercent
     * @param {number|null} [failedAttemptUsd]
     * @returns {number} */
    estimate.price_per_successful_well_usd = function (successRatePercent, failedAttemptUsd) {
      if (!(successRatePercent > 0 && successRatePercent <= 100)) {
        throw new Error('success rate must be in (0, 100]');
      }
      var failed = failedAttemptUsd === undefined || failedAttemptUsd === null
        ? estimate.dry_attempt_price_usd : failedAttemptUsd;
      if (!(typeof failed === 'number' && isFinite(failed) && failed >= 0.0)) {
        throw new Error('the price of a failed attempt must be a number, 0 or more');
      }
      var p = successRatePercent / 100.0;
      return priceWithVat + failed * ((1.0 - p) / p);
    };
    estimate.by_stage = function () {
      var totals = {}, order = STAGES.slice();
      STAGES.forEach(function (s) { totals[s] = 0.0; });
      items.forEach(function (i) {
        if (!(i.stage in totals)) { totals[i.stage] = 0.0; order.push(i.stage); }
        totals[i.stage] += i.amount_usd;
      });
      return order.filter(function (s) { return totals[s] > 0; })
        .map(function (s) { return [s, totals[s]]; });
    };
    estimate.by_category = function () {
      var totals = {}, order = RESOURCE_CATEGORIES.slice();
      RESOURCE_CATEGORIES.forEach(function (c) { totals[c] = 0.0; });
      items.forEach(function (i) {
        if (!(i.category in totals)) { totals[i.category] = 0.0; order.push(i.category); }
        totals[i.category] += i.amount_usd;
      });
      return order.filter(function (c) { return totals[c] > 0; })
        .map(function (c) { return [c, totals[c]]; });
    };
    estimate.boq_rows = function () {
      return items.slice().sort(function (a, b) {
        var ia = STAGES.indexOf(a.stage), ib = STAGES.indexOf(b.stage);
        ia = ia < 0 ? 99 : ia; ib = ib < 0 ? 99 : ib;
        return ia - ib || (a.code < b.code ? -1 : a.code > b.code ? 1 : 0);
      }).map(function (i) {
        return {
          Code: i.code, Stage: i.stage, Item: i.item, Unit: i.unit,
          Quantity: pyRound(i.quantity, 2),
          'Rate (USD)': pyRound(i.unit_cost_usd, 2),
          'Amount (USD)': pyRound(i.amount_usd, 2),
        };
      });
    };
    return estimate;
  }

  /** Cost a package of boreholes sharing one mobilisation: mobilise the rig
   * once, move it between nearby sites, and let the successful wells carry the
   * cost of the expected dry holes. A dry attempt only pays for siting, set up
   * and drilling.
   * @param {Rec} perWell what costingInputs returns, for one borehole
   * @param {number} nBoreholes
   * @param {Rec} [options]
   */
  function estimateProgrammeCost(perWell, nBoreholes, options) {
    var opts = options || {};
    if (nBoreholes < 1) throw new Error('a programme needs at least one borehole');
    var successRate = opts.successRatePercent === undefined ? 100.0 : opts.successRatePercent;
    if (!(successRate > 0 && successRate <= 100)) {
      throw new Error('success rate must be in (0, 100]');
    }
    var catalogue = opts.rates || loadRates();
    var interSiteKm = opts.interSiteDistanceKm === undefined ? 15.0 : opts.interSiteDistanceKm;
    /* Round before the ceiling: 21 wells at 35 percent is exactly 60 attempts,
     * but the division lands on 60.000000000000007 and ceil() then budgets a
     * 61st - a whole phantom dry borehole in the programme cost. */
    var nAttempted = Math.ceil(pyRound(nBoreholes / (successRate / 100.0), 9));

    var wellInputs = Object.assign({}, perWell, { mobilisation_distance_km: 0.0 });
    var well = estimateBoreholeCost(wellInputs, catalogue, {
      overheadsPercent: opts.overheadsPercent, marginPercent: opts.marginPercent,
      contingencyPercent: opts.contingencyPercent, vatPercent: opts.vatPercent,
      exchangeRate: opts.exchangeRate,
    });

    /* the well carries no journey (charged at package level), so this is
     * its siting, set-up and drilling */
    var dryCost = well.dry_attempt_direct_usd;

    var kmRate = catalogue.filter(function (r) {
      return r.quantity_basis === 'per_km_round_trip';
    }).reduce(function (a, r) { return a + r.unit_cost_usd; }, 0);
    var transportKm = 2.0 * perWell.mobilisation_distance_km +
      Math.max(0, nAttempted - 1) * interSiteKm;
    var transport = kmRate * transportKm;

    var assumptions = well.assumptions.slice();
    assumptions.push('One rig mobilised once for the package (' +
      formatG(perWell.mobilisation_distance_km) + ' km each way) with ' +
      Math.max(0, nAttempted - 1) + ' inter-site moves of ' +
      formatG(interSiteKm) + ' km on average.');
    if (nAttempted > nBoreholes) {
      assumptions.push((nAttempted - nBoreholes) + ' dry attempt(s) expected at ' +
        formatG(successRate) + '% siting success; a dry attempt pays for ' +
        'siting, set up and drilling only, costed at the full crew time ' +
        '(a conservative allowance).');
    }

    var directCost = nBoreholes * well.direct_cost_usd +
      (nAttempted - nBoreholes) * dryCost + transport;
    var totalCost = directCost * (1 + well.overheads_percent / 100.0);
    var price = totalCost * (1 + well.margin_percent / 100.0);
    var priceWithVat = price * (1 + well.vat_percent / 100.0);

    var programme = {
      n_successful: nBoreholes, n_attempted: nAttempted,
      success_rate_percent: successRate, well_estimate: well,
      dry_attempt_cost_usd: dryCost, transport_cost_usd: transport,
      overheads_percent: well.overheads_percent, margin_percent: well.margin_percent,
      contingency_percent: well.contingency_percent, vat_percent: well.vat_percent,
      exchange_rate_sle_per_usd: well.exchange_rate_sle_per_usd,
      assumptions: assumptions,
      direct_cost_usd: directCost,
      total_cost_usd: totalCost,
      price_usd: price,
      price_with_vat_usd: priceWithVat,
      budget_usd: priceWithVat * (1 + well.contingency_percent / 100.0),
      price_per_successful_well_usd: priceWithVat / nBoreholes,
      dry_attempts_cost_usd: (nAttempted - nBoreholes) * dryCost,
    };
    programme.in_local = function (usd) {
      return usd * well.exchange_rate_sle_per_usd;
    };
    return programme;
  }

  /* The programme roll-up as a report table. Mirrors
   * ProgrammeEstimate.summary_rows on the Python side, so the package
   * estimate reads the same in either engine's cost report. */
  /** The single-borehole cost summary, the table section 4 of the costing
   * report prints. The browser used to inline eight fixed rows here and had
   * no VAT branch at all, so with VAT set - and the browser offers the input -
   * the document showed a contract price, then a contingency computed on a
   * VAT-inclusive budget, and no line saying where the difference went. The
   * reader could not reconcile the total on the page they were asked to sign.
   * groundwater.costing.model.Estimate.summary_rows is the same table; parity
   * holds the two to the same rows.
   * @param {Rec} estimate what estimateBoreholeCost returns
   * @returns {string[][]}
   */
  function costSummaryRows(estimate) {
    /* costUsd, half to even as Python's f"{x:,.0f}": toLocaleString rounds a
     * half up, and a 4,132.5 direct cost printed 4,133 against 4,132 */
    function pair(usd) {
      return [costUsd(usd), costUsd(estimate.in_local(usd))];
    }
    var rows = [
      ['Direct works cost'].concat(pair(estimate.direct_cost_usd)),
      ['Overheads (' + formatG(estimate.overheads_percent) + '%)']
        .concat(pair(estimate.overheads_usd)),
      ['Total cost'].concat(pair(estimate.total_cost_usd)),
      ['Cost per metre drilled'].concat(pair(estimate.cost_per_meter_usd)),
      ['Margin (' + formatG(estimate.margin_percent) + '%)']
        .concat(pair(estimate.margin_usd)),
      ['Contract price'].concat(pair(estimate.price_usd)),
    ];
    if (estimate.vat_percent) {
      rows.push(['VAT/GST (' + formatG(estimate.vat_percent) + '%)']
        .concat(pair(estimate.vat_usd)));
      rows.push(['Price including VAT'].concat(pair(estimate.price_with_vat_usd)));
    }
    rows.push(['Contingency (' + formatG(estimate.contingency_percent) + '%)']
      .concat(pair(estimate.contingency_usd)));
    rows.push(['Planning budget'].concat(pair(estimate.budget_usd)));
    return rows;
  }

  /**
   * @param {Rec} programme what estimateProgrammeCost returns
   * @returns {string[][]}
   */
  function programmeSummaryRows(programme) {
    /* costUsd: transport at 2.50 USD a km lands on a half for half of all
     * attempt counts, and toLocaleString printed 313 against 312 */
    function pair(usd) {
      return [costUsd(usd), costUsd(programme.in_local(usd))];
    }
    var dry = (programme.n_attempted - programme.n_successful) *
      programme.dry_attempt_cost_usd;
    var rows = [
      ['Successful boreholes required', String(programme.n_successful), ''],
      ['Attempts planned (' + formatG(programme.success_rate_percent) +
        '% success)', String(programme.n_attempted), ''],
      ['Direct works cost'].concat(pair(programme.direct_cost_usd)),
      ['- of which transport and moves'].concat(pair(programme.transport_cost_usd)),
      ['- of which dry attempts'].concat(pair(dry)),
      ['Total cost (overheads ' + formatG(programme.overheads_percent) + '%)']
        .concat(pair(programme.total_cost_usd)),
      ['Contract price (margin ' + formatG(programme.margin_percent) + '%)']
        .concat(pair(programme.price_usd)),
    ];
    if (programme.vat_percent) {
      rows.push(['Price including VAT (' + formatG(programme.vat_percent) + '%)']
        .concat(pair(programme.price_with_vat_usd)));
    }
    rows.push(['Price per successful borehole']
      .concat(pair(programme.price_per_successful_well_usd)));
    rows.push(['Planning budget (contingency ' +
      formatG(programme.contingency_percent) + '%)'].concat(pair(programme.budget_usd)));
    return rows;
  }

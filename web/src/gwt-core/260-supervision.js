
  /* ============================================================ supervision
   * groundwater/supervision/*. Checklist content follows RWSN/UNICEF
   * "Supervising Water Well Drilling"; the numeric field checks encode the
   * acceptance criteria a supervisor applies on site.
   */

  var STAGE_TITLES = [
    ['procurement', 'Procurement and contract'],
    ['pre_contract', 'Pre-contract inspection'],
    ['siting', 'Siting'],
    ['mobilisation', 'Mobilisation'],
    ['drilling', 'Drilling'],
    ['design', 'Design and installation'],
    ['development', 'Development and completion'],
    ['demobilisation', 'Demobilisation'],
    ['handover', 'Documentation and handover'],
    ['post_construction', 'Post-construction monitoring'],
  ];
  var STAGE_ORDER = STAGE_TITLES.map(function (s) { return s[0]; });
  var RESPONSE_STATES = ['pending', 'yes', 'no', 'na'];

  /**
   * @param {string} key
   * @returns {string}
   */
  function stageTitle(key) {
    for (var i = 0; i < STAGE_TITLES.length; i++) {
      if (STAGE_TITLES[i][0] === key) return STAGE_TITLES[i][1];
    }
    var s = String(key).replace(/_/g, ' ');
    return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
  }

  /** @param {Rec[]|null} [rows] the bundled checklists when not given */
  function loadChecklists(rows) {
    var source = rows || (GWT.data && GWT.data.supervisionChecklists) || [];
    var counters = {}, seen = {};
    return source.map(function (row) {
      var checklist = String(row.checklist || '').trim();
      counters[checklist] = (counters[checklist] || 0) + 1;
      var positional = checklist + '-' + String(counters[checklist]).padStart(2, '0');
      /* the CSV's own id when it has one, so a row inserted or reworded never
       * moves anybody's saved answer */
      var itemId = String(row.id || '').trim() || positional;
      if (own(seen, itemId)) throw new Error('checklist id ' + itemId + ' appears twice');
      seen[itemId] = true;
      return {
        item_id: itemId,
        legacy_id: positional,
        checklist: checklist,
        section: String(row.section || '').trim(),
        text: String(row.item || '').trim(),
        critical: String(row.critical || '').trim().toLowerCase() === 'yes',
        guidance: String(row.guidance || '').trim(),
        /* evidenced by a photograph: the CSV's photo column, none without it */
        photo_required: String(row.photo || '').trim().toLowerCase() === 'yes',
      };
    });
  }

  /** positional id -> stable id, for every item whose id changed
   * @param {Rec[]|null} [items] what loadChecklists returns
   * @returns {Record<string, string>}
   */
  function legacyItemIds(items) {
    /** @type {Record<string, string>} */
    var out = {};
    (items || loadChecklists()).forEach(function (item) {
      if (item.legacy_id && item.legacy_id !== item.item_id) out[item.legacy_id] = item.item_id;
    });
    return out;
  }

  /** responses saved before the CSV carried ids are keyed by position; carry
   * them onto the questions they answered. Nothing is guessed: a key that is
   * already stable, or that the current CSV does not know, is left alone.
   * @param {Record<string, *>|null} responses keyed by item id
   * @param {Rec[]|null} [items] what loadChecklists returns
   * @returns {Record<string, *>}
   */
  function migrateChecklistResponses(responses, items) {
    var legacy = legacyItemIds(items);
    var out = {};
    Object.keys(responses || {}).forEach(function (key) {
      var target = own(legacy, key) ? legacy[key] : key;
      if (own(out, target)) return;
      var value = /** @type {Record<string, *>} */ (responses)[key];
      out[target] = (value && typeof value === 'object' && value.item_id === key)
        ? Object.assign({}, value, { item_id: target }) : value;
    });
    return out;
  }

  /** @param {Rec[]|null} [rows] the bundled table when not given */
  function loadSeparationDistances(rows) {
    var source = rows || (GWT.data && GWT.data.separationDistances) || [];
    return source.map(function (row) {
      return {
        structure: String(row.structure || '').trim(),
        min_distance_m: Number(row.min_distance_m),
        note: String(row.note || '').trim(),
      };
    });
  }

  /**
   * @param {Rec[]} items what loadChecklists returns
   * @param {Rec[]|Record<string, Rec>|null} [responses] a list of responses, or responses keyed by item id
   */
  function evaluateChecklist(items, responses) {
    var byId = {};
    if (Array.isArray(responses)) {
      responses.forEach(function (r) { byId[r.item_id] = r; });
    } else {
      byId = responses || {};
    }
    var present = {};
    items.forEach(function (i) { present[i.checklist] = true; });
    var stageKeys = STAGE_ORDER.filter(function (k) { return present[k]; });
    Object.keys(present).sort().forEach(function (k) {
      if (stageKeys.indexOf(k) < 0) stageKeys.push(k);
    });

    var stages = [], flags = [];
    stageKeys.forEach(function (key) {
      var stageItems = items.filter(function (i) { return i.checklist === key; });
      var answered = 0, passed = 0, failed = 0, criticalFailed = 0, criticalOpen = 0;
      stageItems.forEach(function (item) {
        var response = byId[item.item_id];
        var status = response ? response.status : 'pending';
        if (RESPONSE_STATES.indexOf(status) < 0) status = 'pending';
        if (status !== 'pending') answered += 1;
        if (status === 'yes' || status === 'na') {
          passed += 1;
        } else if (status === 'no') {
          failed += 1;
          if (item.critical) {
            criticalFailed += 1;
            flags.push({
              level: 'error', code: 'critical_item_failed',
              message: item.text, context: stageTitle(key),
            });
          }
        } else if (item.critical) {
          criticalOpen += 1;
        }
      });
      stages.push({
        stage: key, title: stageTitle(key), total: stageItems.length,
        answered: answered, passed: passed, failed: failed,
        critical_failed: criticalFailed, critical_open: criticalOpen,
        complete: answered === stageItems.length,
        percent: stageItems.length ? 100.0 * answered / stageItems.length : 0.0,
      });
    });

    var total = stages.reduce(function (a, s) { return a + s.total; }, 0);
    var answeredAll = stages.reduce(function (a, s) { return a + s.answered; }, 0);
    var criticalFailures = stages.reduce(function (a, s) { return a + s.critical_failed; }, 0);
    var openCritical = stages.reduce(function (a, s) { return a + s.critical_open; }, 0);
    var verdict;
    if (criticalFailures) {
      verdict = criticalFailures + ' critical item(s) failed; the works should ' +
        'not be accepted until they are resolved.';
    } else if (openCritical) {
      verdict = openCritical + ' critical item(s) still open; complete them ' +
        'before sign off.';
    } else if (answeredAll < total) {
      verdict = 'No critical failures; routine items remain open.';
    } else {
      verdict = 'All checklist items answered with no critical failures.';
    }

    return {
      stages: stages, flags: flags, total: total, answered: answeredAll,
      percent: total ? 100.0 * answeredAll / total : 0.0,
      critical_failures: criticalFailures, critical_open: openCritical,
      verdict: verdict,
    };
  }

  /* --- numeric field acceptance checks ------------------------------------- */

  function fieldCheck(name, passed, measured, limit, message) {
    return {
      name: name, passed: passed, measured: measured, limit: limit,
      message: message,
      status: passed === null ? 'info' : (passed ? 'pass' : 'fail'),
    };
  }

  /** Three 20 litre samples at the end of the pumping test; the settled sand in
   * each must not exceed 10 ppm by volume.
   * @param {number[]|null} samplesCm3
   * @param {number} [sampleVolumeL]
   */
  function sandContentCheck(samplesCm3, sampleVolumeL) {
    var volume = sampleVolumeL === undefined ? 20.0 : sampleVolumeL;
    var limitCm3 = volume * 1000.0 * 10e-6;
    var worst = samplesCm3 && samplesCm3.length ? arrMax(samplesCm3) : 0.0;
    var has = !!(samplesCm3 && samplesCm3.length);
    var passed = has && worst <= limitCm3;
    return fieldCheck('Sand content', has ? passed : null,
      formatG(worst) + ' cm3 worst of ' + (samplesCm3 || []).length + ' sample(s)',
      formatG(limitCm3) + ' cm3 per ' + formatG(volume) + ' L sample (10 ppm by volume)',
      passed ? 'Sand content acceptable.'
        : 'Excessive sand: check drilling technique, gravel pack and ' +
          "development; a replacement borehole may be at the driller's cost.");
  }

  /** Plumb test: deviation must not exceed two thirds of the casing inner
   * diameter per 30 m of depth.
   * @param {number} deviationMm
   * @param {number} depthM
   * @param {number} casingInnerDiameterMm
   */
  function verticalityCheck(deviationMm, depthM, casingInnerDiameterMm) {
    var allowedMm = (2.0 / 3.0) * casingInnerDiameterMm * (depthM / 30.0);
    var passed = deviationMm <= allowedMm;
    return fieldCheck('Verticality (plumb test)', passed,
      formatG(deviationMm) + ' mm over ' + formatG(depthM) + ' m',
      pyFixed(allowedMm, 0) + ' mm (two thirds of ' +
        formatG(casingInnerDiameterMm) + ' mm ID per 30 m)',
      passed ? 'Borehole is acceptably straight and vertical.'
        : 'Deviation exceeds the limit; the driller re-drills at own cost.');
  }

  /** Screen entrance velocity rule: open area A >= Q/30 (A in m2, Q in L/s)
   * keeps the entrance velocity below 0.03 m/s.
   * @param {number} designYieldLPerS
   * @param {number} screenOpenAreaM2
   */
  function screenOpenAreaCheck(designYieldLPerS, screenOpenAreaM2) {
    var required = designYieldLPerS / 30.0;
    var passed = screenOpenAreaM2 >= required;
    return fieldCheck('Screen open area', passed,
      formatG(screenOpenAreaM2) + ' m2',
      '>= ' + pyFixed(required, 3) + ' m2 for Q = ' + formatG(designYieldLPerS) + ' L/s',
      passed ? 'Entrance velocity within 0.03 m/s.'
        : 'Open area too small: turbulent inflow, encrustation and a shortened ' +
          'screen life are likely; use more or larger screen.');
  }

  /**
   * @param {number} dischargeM3PerH
   * @param {number} drawdownM
   */
  function specificCapacityCheck(dischargeM3PerH, drawdownM) {
    if (drawdownM <= 0) {
      return fieldCheck('Specific capacity', null, 'n/a',
        '>= 1 m3/h per m for a handpump',
        'Drawdown must be positive to compute specific capacity.');
    }
    var sc = dischargeM3PerH / drawdownM;
    var passed = sc >= 1.0;
    return fieldCheck('Specific capacity', passed, pyFixed(sc, 2) + ' m3/h per m',
      '>= 1 m3/h per m for a handpump',
      passed ? 'Adequate for a handpump (about 1 m drawdown at 1 m3/h).'
        : 'Below the handpump rule of thumb; review the test data and the pump ' +
          'setting before acceptance.');
  }

  /** Filter pack sizing: pack D50 / aquifer D50 should be 4 to 6.
   * @param {number} d50PackMm
   * @param {number} d50AquiferMm
   */
  function packAquiferRatioCheck(d50PackMm, d50AquiferMm) {
    if (d50AquiferMm <= 0) {
      return fieldCheck('Pack aquifer ratio', null, 'n/a', '4 to 6',
        'Aquifer D50 must be positive.');
    }
    var ratio = d50PackMm / d50AquiferMm;
    var passed = ratio >= 4.0 && ratio <= 6.0;
    return fieldCheck('Pack aquifer ratio', passed, pyFixed(ratio, 1),
      '4 to 6 (D50 pack / D50 aquifer)',
      passed ? 'Filter pack correctly sized for the formation.'
        : 'Pack aquifer ratio outside 4 to 6: risk of sand pumping (too coarse) ' +
          'or a choked screen (too fine).');
  }

  /** At least 50 mm all round for placement; a gravel pack needs 70 mm to work
   * as a filter, thinner is only a formation stabiliser.
   * @param {number} boreholeDiameterIn
   * @param {number} casingOdMm
   */
  function annularSpaceCheck(boreholeDiameterIn, casingOdMm) {
    var boreholeMm = boreholeDiameterIn * 25.4;
    var annulusMm = (boreholeMm - casingOdMm) / 2.0;
    var passed = annulusMm >= 50.0;
    var note;
    if (annulusMm >= 70.0) {
      note = 'Full gravel pack possible.';
    } else if (passed) {
      note = 'Meets the 50 mm placement minimum, but under 70 mm the annular ' +
        'fill acts as a formation stabiliser rather than a filter pack.';
    } else {
      note = 'Annulus below the 50 mm minimum: gravel is likely to bridge ' +
        'during placement; use a larger bit or smaller casing.';
    }
    return fieldCheck('Annular space', passed, pyFixed(annulusMm, 0) + ' mm',
      '>= 50 mm (70 mm for a true gravel pack)', note);
  }

  /* field_checks.METRES_TOLERANCE_M: how far the invoiced metres may run over
   * the signed daily logs, as the casing reconciliation rule allows 3 m */
  var METRES_TOLERANCE_M = 3.0;

  /** Paying per metre invites overstated depths; the daily logs signed by the
   * rig operator and the supervisor are the audit trail.
   * @param {number} loggedM
   * @param {number} claimedM
   * @param {number} [toleranceM]
   */
  function metresReconciliationCheck(loggedM, claimedM, toleranceM) {
    var tolerance = toleranceM === undefined ? METRES_TOLERANCE_M : toleranceM;
    var difference = claimedM - loggedM;
    var passed = difference <= tolerance;
    var message;
    if (difference > tolerance) {
      message = 'Invoice claims ' + formatG(difference) + ' m more than the ' +
        'signed daily logs; withhold payment for the unsupported metres and ' +
        'reconcile with the driller.';
    } else if (difference < -tolerance) {
      message = 'Logs record more metres than invoiced; check that the invoice ' +
        'covers all completed work.';
    } else {
      message = 'Invoiced metres are supported by the daily logs.';
    }
    return fieldCheck('Drilled metres reconciliation', passed,
      'logged ' + formatG(loggedM) + ' m, invoiced ' + formatG(claimedM) + ' m',
      'difference within ' + formatG(tolerance) + ' m', message);
  }

  /** Below pH 6.5 galvanised iron risers and rods corrode rapidly, failing
   * within months to two years and shedding iron into the supply.
   * @param {number} ph
   */
  function handpumpCorrosionCheck(ph) {
    var atRisk = ph < 6.5;
    return fieldCheck('Handpump corrosion risk', !atRisk, 'pH ' + formatG(ph),
      '>= 6.5 for galvanised iron components',
      atRisk
        ? 'Corrosive water: specify stainless steel (grade 304/316) or uPVC ' +
          'riser pipes and rods; galvanised iron can fail within months and ' +
          'taint the water with iron.'
        : 'Corrosion risk low; standard components acceptable.');
  }

  /** WHO shock dose: 1 L of 0.2 percent solution per 100 L of well volume gives
   * 20 mg/L; do not pump for at least 4 hours.
   * @param {number} waterColumnM
   * @param {number} casingInnerDiameterMm
   */
  function disinfectionDose(waterColumnM, casingInnerDiameterMm) {
    var radiusM = casingInnerDiameterMm / 2000.0;
    var volumeL = Math.PI * radiusM * radiusM * Math.max(0.0, waterColumnM) * 1000.0;
    var solutionL = volumeL / 100.0;
    /* 0.2 percent solution = 2 g chlorine per litre; 65 percent HTH carries
     * 0.65 g available chlorine per gram of powder. */
    var hthGrams = solutionL * 2.0 / 0.65;
    return {
      well_volume_l: volumeL, solution_02pct_l: solutionL, hth_grams: hthGrams,
      contact_hours: 4.0,
      summary: 'Well volume about ' + thousandsFixed(volumeL, 0) + ' L: add ' +
        thousandsFixed(solutionL, 1) + ' L of 0.2% chlorine solution (about ' +
        thousandsFixed(hthGrams, 0) + ' g of 65% HTH in that much water) and ' +
        'wait at least 4 hours before pumping.',
    };
  }

  /** Python's "{:,.1f}".
   * @param {number|string} value
   * @param {number} decimals
   * @returns {string}
   */
  function thousandsFixed(value, decimals) {
    return Number(value).toLocaleString('en-US', {
      minimumFractionDigits: decimals, maximumFractionDigits: decimals,
    });
  }

  Object.assign(C, {
    designBorehole: designBorehole, designSummaryRows: designSummaryRows,
    risingMainChoice: risingMainChoice, CHEMISTRY_STATES: CHEMISTRY_STATES,
    PH_CORROSIVE_BELOW: PH_CORROSIVE_BELOW, RISING_MAIN_BASES: RISING_MAIN_BASES,
    targetZones: targetZones, sealDepthFor: sealDepthFor,
    pumpIntakeFloor: pumpIntakeFloor,
    loggedDiameterIn: loggedDiameterIn, intervalAt: intervalAt,
    annularFillLabel: annularFillLabel,
    DESIGN_NOTE: DESIGN_NOTE, AS_BUILT_NOTE: AS_BUILT_NOTE,
    ANNULUS_PACK_MIN_MM: ANNULUS_PACK_MIN_MM,
    ANNULUS_FILTER_MIN_MM: ANNULUS_FILTER_MIN_MM,
    LITHOLOGY_CLASSES: LITHOLOGY_CLASSES, LITHOLOGY_OTHER: LITHOLOGY_OTHER,
    FRACTURE_PHRASE_RE: FRACTURE_PHRASE_RE, ANY_RANGE_RE: ANY_RANGE_RE,
    CLAYEY_RE: CLAYEY_RE,
    lithologyClass: lithologyClass, isClayey: isClayey,
    fractureRanges: fractureRanges, hostDescription: hostDescription,
    readFractures: readFractures, hostClass: hostClass, lithologyBands: lithologyBands,
    /* the same table under one name, for the drawings */
    lithology: {
      CLASSES: LITHOLOGY_CLASSES, OTHER: LITHOLOGY_OTHER,
      FRACTURE_PHRASE_RE: FRACTURE_PHRASE_RE, ANY_RANGE_RE: ANY_RANGE_RE,
      CLAYEY_RE: CLAYEY_RE, lithologyClass: lithologyClass, isClayey: isClayey,
      fractureRanges: fractureRanges, hostDescription: hostDescription,
      readFractures: readFractures, lithologyBands: lithologyBands,
    },
    STAGES: STAGES, RESOURCE_CATEGORIES: RESOURCE_CATEGORIES,
    DEFAULT_EXCHANGE_RATE_SLE_PER_USD: DEFAULT_EXCHANGE_RATE_SLE_PER_USD,
    loadRates: loadRates, rateTriangle: rateTriangle, rateWithLikely: rateWithLikely,
    annulusVolumeM3: annulusVolumeM3,
    costingInputs: costingInputs, resolveCostingInputs: resolveCostingInputs,
    inputsFromDesign: inputsFromDesign, estimateBoreholeCost: estimateBoreholeCost,
    estimateProgrammeCost: estimateProgrammeCost,
    costSummaryRows: costSummaryRows,
    programmeSummaryRows: programmeSummaryRows,
    STAGE_TITLES: STAGE_TITLES, STAGE_ORDER: STAGE_ORDER,
    RESPONSE_STATES: RESPONSE_STATES, stageTitle: stageTitle,
    loadChecklists: loadChecklists, legacyItemIds: legacyItemIds,
    migrateChecklistResponses: migrateChecklistResponses, loadSeparationDistances: loadSeparationDistances,
    evaluateChecklist: evaluateChecklist,
    sandContentCheck: sandContentCheck, verticalityCheck: verticalityCheck,
    screenOpenAreaCheck: screenOpenAreaCheck,
    specificCapacityCheck: specificCapacityCheck,
    packAquiferRatioCheck: packAquiferRatioCheck,
    annularSpaceCheck: annularSpaceCheck,
    metresReconciliationCheck: metresReconciliationCheck,
    handpumpCorrosionCheck: handpumpCorrosionCheck,
    disinfectionDose: disinfectionDose, thousandsFixed: thousandsFixed,
  });


  /* ------------------------------------------------------------- computation */

  function config() {
    /* the calibration set in force, refused unless a named person adopted
     * it, as a project file's own settings are not */
    var held = store.get('calibration');
    return C.withConfig(held ? Object.assign({}, store.get('config'), { calibration: held })
      : store.get('config'));
  }

  /* Rebuild every derived result from the stored sources. Called after any
   * upload, any manual entry and on load, so what a page shows and what a
   * report contains are always the same computation.
   *
   * The work is done in the engine worker and the page stays live while it
   * runs, so two recomputes can overlap - a discharge typed while a sample is
   * still loading. The newest wins. An older one's requests are cancelled
   * and it commits nothing, and until the newest commits, the page keeps
   * the last complete set of results rather than half of two. */
  async function recompute() {
    var seq = ++recomputeSeq;
    recomputeState.running += 1;
    try {
      await recomputeInner(seq);
    } finally {
      recomputeState.running -= 1;
      recomputeState.generation += 1;
    }
  }

  var recomputeState = { running: 0, generation: 0 };
  var recomputeSeq = 0;

  /* The order the sheets were always read in, which is the order their
   * notices are shown in. */
  var SOURCE_ROLES = ['ves', 'drilling', 'pumping', 'quality'];
  var SOURCE_LABELS = { ves: 'VES sheet', drilling: 'Drilling log',
    pumping: 'Pumping sheet', quality: 'Water quality sheet' };

  async function recomputeInner(seq) {
    var sources = store.get('sources') || {};
    var cfg = config();
    var notices = [];

    /* Whatever an older recompute is still computing is for sources this one
     * is about to replace. A running inversion is left alone until this one
     * has read the soundings: if they are the ones it is inverting, it
     * carries on (adoptInversions). */
    engine.cancel(['recompute', 'analysePumping']);

    /* Reading a workbook or a Word sheet needs DOMParser, which a worker does
     * not have, so the page reads the sheets and the worker derives the rest
     * from what was read. */
    var input = { config: cfg, sources: {},
      manualDischarges: store.get('pumping.manualDischarges') || {} };
    for (var r = 0; r < SOURCE_ROLES.length; r++) {
      var role = SOURCE_ROLES[r], source = sources[role];
      if (!source) continue;
      try {
        var bytes = S.base64ToBytes(source.b64);
        /* the crew is handed a Word field sheet as often as the workbook;
         * refusing it is how readings get retyped, and retyping is where the
         * transcription errors come from */
        input.sources[role] = role === 'pumping' && /\.docx$/i.test(source.name || '')
          ? { name: source.name, test: await C.readPumpingDocx(bytes, source.name) }
          : { name: source.name, sheets: await S.readXlsx(bytes) };
      } catch (e) {
        notices.push([role, SOURCE_LABELS[role] + ': ' + e.message, 'error']);
      }
      if (seq !== recomputeSeq) return;
    }

    var next;
    try {
      next = await engine.recompute(input);
    } catch (e2) {
      if (engine.isCancelled(e2)) return;
      throw e2;
    }
    if (seq !== recomputeSeq) return;

    next.analysis = null;
    next.analysisNote = null;
    if (next.test) {
      var outcome = await analyseTest(next.test, cfg);
      if (seq !== recomputeSeq) return;
      next.test = outcome.test;
      next.analysis = outcome.analysis;
      next.analysisNote = outcome.note;
      if (outcome.error) {
        notices.push(['pumping', 'Pumping sheet: ' + outcome.error.message, 'error']);
      }
    }

    derived.soundings = next.soundings;
    if (next.skippedVesSheets) derived.skippedVesSheets = next.skippedVesSheets;
    var inverting = adoptInversions(cfg);
    derived.log = next.log;
    derived.test = next.test;
    derived.analysis = next.analysis;
    derived.analysisNote = next.analysisNote;
    derived.sample = next.sample;
    derived.assessment = next.assessment;
    notices = notices.concat(next.notices);
    SOURCE_ROLES.forEach(function (role) {
      notices.forEach(function (n) { if (n[0] === role) S.toast(n[1], n[2]); });
    });

    adoptSiteMetadata();
    rebuildDesign();
    rebuildCosting();
    /* the soundings the cache could not answer, inverted without holding up
     * the page, which is drawn again once they are in */
    if (inverting) inverting().then(refresh);
  }

  var ANALYSIS_STOPPED = 'the analysis was stopped before it finished.';

  /* The pumping analysis, shown in the work bar while it runs. Resolves to
   * the test and its analysis, or to the test with no analysis and a note
   * saying why: stopped, or the error the analysis gave (also returned, so
   * it can be announced). Never rejects. */
  async function analyseTest(test, cfg) {
    var job = workBegin('pumping', 'Analysing the pumping test');
    try {
      var analysis = await engine.analysePumping(test, cfg, {
        onProgress: function (fraction, stage) { workProgress(job, fraction, stage); },
      });
      /* the analysis holds its own copy of the test; that copy is the test */
      return { test: analysis.test, analysis: analysis, note: null, error: null };
    } catch (e) {
      var stopped = engine.isCancelled(e);
      return { test: test, analysis: null, note: stopped ? ANALYSIS_STOPPED : e.message,
        error: stopped ? null : e };
    } finally {
      workEnd(job);
    }
  }

  /* Analyse the loaded test again without re-reading any sheet: the Pumping
   * test page's answer to an analysis that was stopped. */
  async function reanalyseTest() {
    var seq = recomputeSeq, test = derived.test;
    if (!test) return;
    engine.cancel('analysePumping');
    var outcome = await analyseTest(test, config());
    /* a recompute since has replaced the test this analysed */
    if (seq !== recomputeSeq || derived.test !== test) return;
    derived.test = outcome.test;
    derived.analysis = outcome.analysis;
    derived.analysisNote = outcome.note;
    if (outcome.error) S.toast('Pumping sheet: ' + outcome.error.message, 'error');
    rebuildDesign();
    rebuildCosting();
  }

  /* The first sheet that carries a header block seeds the project metadata,
   * and later sheets only fill blanks - a typo in one sheet must not overwrite
   * a value the analyst has already corrected. */
  function adoptSiteMetadata() {
    var site = store.get('site');
    var candidates = [derived.log, derived.test, derived.sample]
      .concat(derived.soundings || [])
      .filter(Boolean).map(function (o) { return o.site; }).filter(Boolean);
    var changed = false;
    candidates.forEach(function (source) {
      Object.keys(site).forEach(function (key) {
        var value = source[key];
        var empty = site[key] === '' || site[key] === null || site[key] === undefined;
        if (empty && value !== '' && value !== null && value !== undefined) {
          site[key] = value; changed = true;
        }
      });
    });
    if (changed) store.set('site', site);
  }

  /* The one pump intake depth every document prints (C.pumpIntakeDepth):
   * the deeper of the yield recommendation's and the seasonal projection's,
   * as [depth, why]. The design was fed the yield's depth alone, so the
   * drawing and the completion report gave one depth and the pumping report,
   * built with the seasonal projection, another (hydraulics-6). */
  function recommendedIntake() {
    if (!derived.analysis || !derived.analysis.yield_recommendation) return [null, ''];
    return C.pumpIntakeDepth(derived.analysis, currentSeasonal(derived.analysis));
  }

  function rebuildDesign() {
    derived.design = null;
    var cfg = config();
    var interp = bestInterpretation();
    var swl = derived.test ? derived.test.static_water_level_m : null;
    var custom = store.get('design') || {};
    var totalDepth = custom.totalDepth;
    if (!totalDepth && derived.log && derived.log.total_depth_m) {
      totalDepth = derived.log.total_depth_m;
    }
    if (!totalDepth && interp) totalDepth = interp.max_drilling_depth_m;
    if (!totalDepth) return;
    var rec = derived.analysis ? derived.analysis.yield_recommendation : null;
    try {
      derived.design = C.designBorehole({
        log: derived.log, interpretation: interp,
        staticWaterLevelM: swl === undefined ? null : swl,
        pumpIntakeM: custom.pumpIntake !== null && custom.pumpIntake !== undefined
          ? custom.pumpIntake : recommendedIntake()[0],
        /* the shallowest intake the test supports, whoever chose the depth:
         * the design moves an intake up out of a screen only as far as that */
        pumpIntakeFloorM: rec
          ? C.pumpIntakeFloor(rec, cfg.pumping.pump_submergence_min_m) : null,
        rules: cfg.design, totalDepthM: totalDepth,
        screensM: custom.screens && custom.screens.length ? custom.screens : null,
        /* the rising main follows the Water quality page's sample */
        quality: derived.assessment || null,
      });
    } catch (e) {
      S.toast('Borehole design: ' + e.message, 'warn');
    }
  }

  /* The rate catalogue with the analyst's edits applied. Used by the Costing
   * page and by the Depth Spine, which signs off the number it shows. */
  function costingRates() {
    var overrides = store.get('costing.rateOverrides') || {};
    return C.loadRates().map(function (rate) {
      var override = overrides[rate.code];
      /* an edited rate keeps its relative spread, so the cost distribution
       * is drawn around the rate typed */
      return override === undefined || override === null || override === ''
        ? rate : C.rateWithLikely(rate, Number(override));
    });
  }

  function costingOptions() {
    var costing = store.get('costing');
    return {
      overheadsPercent: costing.overheads, marginPercent: costing.margin,
      contingencyPercent: costing.contingency, vatPercent: costing.vat,
      exchangeRate: costing.exchange,
    };
  }

  function rebuildCosting() {
    derived.estimate = null; derived.programme = null;
    derived.costInputs = null; derived.costRates = null;
    var costing = store.get('costing');
    var inputs;
    if (derived.design) {
      inputs = C.inputsFromDesign(derived.design, {
        mobilisationDistanceKm: costing.mobilisation_km,
        overburdenM: overburdenFromData(),
      });
    } else if (costing.total_depth_m) {
      /* no drawing yet: the diameters and the seal come from the rules the
       * Settings page holds, not from the engine's own defaults */
      var rules = config().design;
      /* with no drawing the rising main still follows the water, priced
       * over the whole depth (the estimate says so) since no intake is drawn */
      var choice = C.risingMainChoice(derived.assessment || null, rules);
      inputs = C.costingInputs({
        total_depth_m: costing.total_depth_m,
        mobilisation_distance_km: costing.mobilisation_km,
        borehole_diameter_in: rules.borehole_diameter_in,
        casing_diameter_in: rules.casing_diameter_in,
        sanitary_seal_m: rules.sanitary_seal_depth_m,
        rising_main_material: choice.upgraded ? choice.material : '',
      });
    } else {
      return;
    }
    inputs.wq_samples = costing.wq_samples;
    inputs.handpumps = costing.handpumps;

    var rates = costingRates();
    try {
      derived.estimate = C.estimateBoreholeCost(inputs, rates, costingOptions());
      /* what the cost distribution samples from, beside the estimate */
      derived.costInputs = inputs; derived.costRates = rates;
      if (costing.programme_n > 1) {
        derived.programme = C.estimateProgrammeCost(inputs, costing.programme_n,
          Object.assign({
            rates: rates, successRatePercent: costing.success_rate,
            interSiteDistanceKm: costing.inter_site_km,
          }, costingOptions()));
      }
    } catch (e) {
      S.toast('Cost estimate: ' + e.message, 'warn');
    }
  }

  /* The weathered zone thickness the cost model wants: from the drilling log's
   * fresh-rock contact when there is one, else the VES depth to basement. */
  function overburdenFromData() {
    if (derived.log && derived.log.intervals && derived.log.intervals.length) {
      for (var i = 0; i < derived.log.intervals.length; i++) {
        if (/fresh|unweathered|competent/i.test(derived.log.intervals[i].description || '')) {
          return derived.log.intervals[i].top_m;
        }
      }
    }
    var interp = bestInterpretation();
    if (interp && interp.depth_to_basement_m !== null) return interp.depth_to_basement_m;
    return null;
  }

  function bestInterpretation() {
    if (!derived.interpretations || !derived.interpretations.length) return null;
    var ranked = derived.interpretations.slice().sort(function (a, b) {
      return (a.rank || 99) - (b.rank || 99);
    });
    return ranked[0];
  }

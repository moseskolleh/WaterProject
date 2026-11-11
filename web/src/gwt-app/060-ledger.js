
  /* --- the ledger of predictions and outcomes (PLAN.md step 5.1) --------- */

  /* The project's ledger with the completion it holds attached to the point
   * it was drilled at; with none, the outcomes the ledger already has. */
  function currentLedger() {
    var cfg = config();
    /* the project's drilling contractor wins over the log's own, as the site
     * details win over every sheet's in the reports' headers */
    return C.attachOutcome(store.get('ledger'),
      C.completionOutcome(derived.log || null, derived.analysis || null, cfg,
        String((store.get('site') || {}).contractor || '')), cfg);
  }

  /* The project's works record (PLAN.md step 6.3): what it records of its
   * contractor's work, for the Portfolio page's contractor scorecards, or
   * null where it records nothing they read. Worked out again from the
   * project whenever it is saved, as the ledger's outcome is. */
  function currentWorks() {
    var cfg = config();
    var responses = store.get('supervision.responses') || {};
    /** @type {Record<string, string>} */
    var answers = {};
    Object.keys(responses).forEach(function (id) {
      var response = responses[id];
      if (response && typeof response.status === 'string') answers[id] = response.status;
    });
    var checks = store.get('supervision.checks') || {};
    var procurement = procurementState();
    return C.worksRecord(store.get('site') || {}, derived.log || null, derived.analysis || null,
      currentLedger(), answers, { logged_m: checks.loggedM, claimed_m: checks.claimedM },
      procurement.contract ? { lines: procurement.contract.lines, variations: procurement.variations,
        due: procurement.due || '' } : null, cfg);
  }

  /* The place a survey's points are recorded under: the project's community
   * and district, each the survey's own where the site details leave it
   * blank, and the survey's zone; and the project's field supervisor, the
   * survey team of a point whose own sheet names none. */
  function ledgerSite() {
    var project = store.get('site') || {};
    var survey = (((derived.soundings || [])[0]) || {}).site || {};
    return { community: project.community || survey.community || '',
      district: project.district || survey.district || '',
      utm_zone: survey.utm_zone || Number(project.utm_zone) || null,
      supervisor: String(project.supervisor || '') };
  }

  /* The field supervisor each point's own sheet names, found by its id as
   * the range sampler finds the sounding. */
  function surveyTeams(interps) {
    var soundings = derived.soundings || [];
    return interps.map(function (interp) {
      var sounding = soundings.filter(function (s) { return s.sounding_id === interp.sounding_id; })[0];
      return sounding && sounding.site ? String(sounding.site.supervisor || '') : '';
    });
  }

  /* Today, as the device's calendar has it. */
  function localDate() {
    var now = new Date();
    var two = function (n) { return (n < 10 ? '0' : '') + n; };
    return now.getFullYear() + '-' + two(now.getMonth() + 1) + '-' + two(now.getDate());
  }

  /* The survey's predictions written into the ledger, as recorded before
   * drilling unless the borehole has been drilled: the project holds a
   * drilling log or a pumping test (a test is run in a drilled hole), the
   * ledger holds an outcome already, or the point drilled has been chosen
   * (recordPredictions reads those two itself). The ids of the points whose
   * forecast was kept as it was made. */
  function recordSurveyPredictions() {
    var interps = derived.interpretations || [];
    if (!interps.length) return [];
    var cfg = config();
    var predictions = C.surveyPredictions(interps, (derived.inversions || []).map(rangeFor),
      surveyOdds(), ledgerSite(), cfg, surveyTeams(interps), C.assessSiting(interps, cfg.ves));
    var got = C.recordPredictions(currentLedger(), predictions, localDate(),
      !!derived.log || !!derived.analysis, (GWT.data || {}).version || '');
    store.set('ledger', got.ledger);
    return got.kept;
  }

  /* How the borehole was matched to the point it was drilled at. */
  var LEDGER_PAIRED = {
    chosen: 'chosen on this page',
    nearest: 'the nearest point recorded, {d} m from the log\'s position',
    only: 'the survey\'s only point',
  };

  function ledgerEntryLabel(entry) {
    return entry.point.sounding_id + ' (recorded ' + entry.recorded_on + ', ' +
      (entry.before_outcome ? 'before' : 'after') + ' drilling)';
  }

  function ledgerCard() {
    var ledger = currentLedger();
    var entries = ledger.entries;
    var body = [
      el('p.muted', C.phrase('ledger.page_intro')),
      el('div.btn-row', [button('Record the survey\'s predictions', function () {
        var n = (derived.interpretations || []).length;
        var kept = recordSurveyPredictions();
        S.toast('Recorded the predictions at ' + n + ' point(s).' + (kept.length
          ? ' ' + kept.length + ' point(s) kept the forecast recorded before drilling.' : ''), 'ok');
        render();
      })]),
    ];
    if (!entries.length) {
      body.push(el('p.muted', 'No prediction is recorded yet.'));
      return card('Predictions and outcomes', body);
    }
    body.push(field('Point drilled', S.selectInput(ledger.drilled || '',
      [{ value: '', label: 'Decide from the drilling log\'s position' }].concat(entries.map(
        function (entry) { return { value: entry.id, label: ledgerEntryLabel(entry) }; })),
      function (value) {
        store.set('ledger', Object.assign({}, store.get('ledger') || {}, { drilled: value || null }));
        render();
      }, { 'data-ledger-drilled': '' })));
    var drilled = entries.filter(function (entry) { return entry.outcome !== null; })[0];
    if (!derived.log && !drilled) {
      body.push(el('p.muted', 'No drilling log is loaded: the outcome is set beside the ' +
        'prediction once it is.'));
    } else if (!drilled) {
      body.push(el('div.callout.callout-warn', el('p', 'The borehole could not be matched to a ' +
        'point: its log has no position near a point recorded. Choose the point drilled above.')));
    } else {
      body.push(el('p', [el('strong', drilled.point.sounding_id), ' - ' +
        LEDGER_PAIRED[drilled.pairing.how].replace('{d}',
          C.fmtNum(drilled.pairing.distance_m || 0.0)) + '.']));
      body.push(S.table(C.entryHeader(), C.entryRows(drilled)));
    }
    body.push(S.table(['Point', 'Recorded', 'When', 'Drilled'], entries.map(function (entry) {
      return [entry.point.sounding_id, entry.recorded_on,
        entry.before_outcome ? 'Before drilling' : 'After drilling', entry.outcome ? 'Yes' : ''];
    })));
    return card('Predictions and outcomes', body);
  }

  /* The planning figure beside the bill of quantities (PLAN.md step 3.4):
   * the estimate's own inputs sampled, the depth drawn from the range at the
   * survey's first-ranked point and dry holes at its odds, and the programme
   * the same way at its typed rate. Kept with the estimate it belongs to and
   * sampled again only when the range, the odds or the programme change, so
   * a page drawn again does not sample it again. */
  var costSpreadsHeld = new WeakMap();

  function costSpreads() {
    var estimate = derived.estimate;
    if (!estimate || !derived.costInputs) return null;
    var survey = firstPointSurvey();
    var p = survey.odds ? survey.odds.probability : null;
    var held = costSpreadsHeld.get(estimate);
    if (held && held.range === survey.range && held.p === p &&
        held.programmeEstimate === derived.programme) {
      return held;
    }
    var cfg = config();
    var depth = C.depthSpread(survey.range, cfg);
    var costing = store.get('costing');
    held = {
      range: survey.range, p: p, programmeEstimate: derived.programme,
      single: C.sampleCost(derived.costInputs, derived.costRates,
        Object.assign({}, costingOptions(), {
          depth: depth, successProbability: p === null ? 1.0 : p,
          oddsSource: survey.odds ? survey.odds.sounding_id : null, config: cfg,
        })),
      programme: derived.programme ? C.sampleProgrammeCost(derived.costInputs,
        costing.programme_n, Object.assign({}, costingOptions(), {
          rates: derived.costRates, successRatePercent: costing.success_rate,
          interSiteDistanceKm: costing.inter_site_km, depth: depth, config: cfg,
        })) : null,
    };
    costSpreadsHeld.set(estimate, held);
    return held;
  }

  /* What one more measurement at the survey's first-ranked point is worth
   * (PLAN.md step 3.5), priced from the cost distribution spread: one for
   * each kind, or none before a survey is inverted. The odds are every
   * point's, so the alternative to the first-ranked point is one of the
   * others. */
  function surveyMeasurements(spread) {
    if (!(derived.interpretations || []).length) return [];
    var ranking = C.assessSiting(derived.interpretations, config().ves)
      .map(function (s) { return s.index; });
    return C.measurementValues(surveyOdds(), ranking, spread.mean, spread.dry_mean);
  }

  /* What one more measurement is worth, on a page: the plan's sentence for
   * each kind, then its other sentences and decision table, what a
   * measurement could read, and the basis, as the reports print them. */
  function measurementNodes(values) {
    var nodes = [el('p.muted', C.phrase('measurement.lead'))];
    if (!values.length) return nodes.concat([el('p', C.phrase('measurement.no_survey'))]);
    values.forEach(function (v) {
      var text = C.measurementText(v);
      nodes.push(el('div.measurement', [
        el('p', el('strong', text[0])),
        el('p', text.slice(1).join(' ')),
        S.table(C.measurementDecisionHeader(v), C.measurementDecisionRows(v)),
        el('p.muted', C.measurementDecisionCaption()),
      ]));
    });
    nodes.push(el('details', [
      el('summary', C.measurementReadingsCaption(values[0])),
      S.table(C.measurementReadingHeader(), C.measurementReadingRows(values[0])),
    ]));
    nodes.push(el('p.muted', C.measurementBasis(values[0])));
    return nodes;
  }

  /* [label, usd] pairs the distribution figures mark */
  function costMarks(spread, programme) {
    var marks = C.phraseTable('cost_range.marks');
    return programme
      ? [[marks.estimate, spread.estimate_usd], [marks.budget, spread.budget_usd]]
      : [[marks.boq, spread.boq_usd], [marks.budget, spread.budget_usd]];
  }

  /* The planning figure on the page: which figure is which first, then the
   * sentences, the table and the curve. */
  function costSpreadNodes(text, rows, chart, caption, filename) {
    var header = C.costRangeHeader();
    return [
      el('div.callout', el('p', text[0])),
    ].concat(text.slice(1).map(function (t) { return el('p', t); })).concat([
      S.table([
        { key: 'item', label: header[0] },
        { key: 'usd', label: header[1], align: 'right' },
        { key: 'share', label: header[2], align: 'right' },
      ], rows.map(function (r) { return { item: r[0], usd: r[1], share: r[2] }; })),
      charts.figure(chart, caption, { filename: filename }),
    ]);
  }

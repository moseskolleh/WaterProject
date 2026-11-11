
  /* --- pumping test --------------------------------------------------------- */

  /* What a fitted method is worth, for the note beside its transmissivity:
   * the reason it was passed over, or that it was adopted only as the best
   * available, or - for the one adopted to standard - the caller's own words
   * (the recovery method's "preferred" used to be printed whether or not
   * the yield rested on it). */
  function methodStatus(analysis, method, adoptedText) {
    var why = C.whyNotAdopted(analysis, method);
    if (analysis.transmissivity_source === method) {
      return why ? ' — adopted as the best available; ' + why : adoptedText;
    }
    return why ? ' — not adopted: ' + why : '';
  }

  PAGES.pumping = function () {
    var nodes = [
      pageHead('Pumping test', 'Cooper-Jacob, Theis and recovery on the same ' +
        'readings, a step drawdown analysis where the test has steps, and a safe ' +
        'yield reported as a range over the assumptions it rests on.'),
      card('Test data', [
        uploadZone('pumping', 'Pumping test sheet (.xlsx or .docx)',
          'The standard workbook, or a Word field sheet: step or constant ' +
          'discharge, with the recovery block',
          '.xlsx,.xls,.docx'),
      ]),
    ];

    if (!derived.test) {
      nodes.push(S.empty('No pumping test loaded. Upload a sheet, or load the ' +
        'Dr Timbo or Kuntoloh sample from the Overview page.',
        button('Overview', function () { goto('overview'); }, { variant: 'ghost' })));
      /* the kit is printed before a test is run, so it is here before one is
       * loaded */
      nodes.push(fieldKitCard());
      return nodes;
    }

    var test = derived.test, analysis = derived.analysis;
    /* #/pumping/<borehole> names the borehole the test was run on; a project
     * holds one test, so the address says which borehole it has to be */
    itemNode(test.borehole_ref, nodes[1]);

    nodes.push(card('Discharge per step', [
      /* what was parsed, in the words a report uses for the test type */
      el('p', 'Parsed ' + C.testTypeText(test.test_type) + ' with ' +
        test.steps.length + ' pumping ' + S.plural(test.steps.length, 'series', 'series') +
        ' and ' + (test.recovery_time_min ? 'a' : 'no') + ' recovery record.'),
      el('p.muted', 'Discharge is often left off the field sheet. Enter the ' +
        'bucket-and-stopwatch figures here and every pending result is computed ' +
        'immediately — the value belongs to the project, not to the file, so it ' +
        'survives a re-upload.'),
      S.table([
        { key: 'label', label: 'Step' },
        { key: 'n', label: 'Readings', align: 'right' },
        { key: 'tmax', label: 'Duration (min)', align: 'right' },
        { key: 'q', label: 'Discharge (m³/h)', align: 'right' },
      ], test.steps.map(function (step) {
        return {
          label: step.label, n: step.time_min.length,
          tmax: C.fmtNum(Math.max.apply(null, step.time_min)),
          q: S.numberInput(step.discharge_m3_per_h, function (value) {
            store.set('pumping.manualDischarges.' + step.step_number, value);
            recompute().then(refresh);
          }, { step: 'any', class: 'input cell cell-narrow',
            'aria-label': 'Discharge (m³/h), ' + step.label }),
        };
      })),
    ]));

    if (!analysis) {
      nodes.push(working('pumping')
        ? S.empty('Analysing the pumping test. The results appear here when the ' +
          'analysis finishes.')
        : S.empty('This test has not been analysed: ' +
          (derived.analysisNote || 'the analysis did not run.'),
          button('Analyse now', function () {
            var analysed = reanalyseTest();
            render();
            analysed.then(refresh);
          })));
      nodes.push(fieldKitCard());
      return nodes;
    }

    if (analysis.flags.length) {
      nodes.push(card('Data checks', [S.checkList(analysis.flags.map(function (f) {
        return { level: f.level, message: f.message, detail: f.context };
      }))]));
    }

    nodes.push(card('Field data', [
      charts.figure(charts.testOverview(test, analysis),
        'Water level through the pumping and recovery phases',
        { filename: 'test_overview' }),
    ]));

    var methodFigures = [];
    /* the flow regime first: it says which model the readings can be read
     * with (PLAN.md step 3.2) */
    var diag = charts.diagnostic(analysis);
    if (diag) methodFigures.push(charts.figure(diag, 'Diagnostic plot (Bourdet derivative)',
      { filename: 'diagnostic' }));
    var cj = charts.cooperJacob(analysis);
    if (cj) methodFigures.push(charts.figure(cj, 'Cooper-Jacob straight line fit',
      { filename: 'cooper_jacob' }));
    var rec = charts.recovery(analysis);
    if (rec) methodFigures.push(charts.figure(rec, 'Theis recovery analysis',
      { filename: 'recovery' }));
    var stepFig = charts.stepTest(analysis);
    if (stepFig) methodFigures.push(charts.figure(stepFig,
      'Step drawdown analysis', { filename: 'step_test' }));

    if (methodFigures.length) {
      nodes.push(card('Analysis', [
        el('div.split', methodFigures),
        S.table([
          { key: 'method', label: 'Method' },
          { key: 'T', label: 'Transmissivity (m²/day)', align: 'right' },
          { key: 'note', label: 'Note' },
        ], [
          analysis.recovery ? {
            method: 'Theis recovery',
            T: S.sig(analysis.recovery.transmissivity_m2_per_day, 4),
            /* "preferred" only when it was in fact adopted to standard */
            note: 'r² = ' + analysis.recovery.r_squared.toFixed(3) +
              methodStatus(analysis, 'recovery',
                ' — least affected by well losses, so preferred'),
          } : null,
          analysis.cooper_jacob ? {
            method: 'Cooper-Jacob',
            T: S.sig(analysis.cooper_jacob.transmissivity_m2_per_day, 4),
            note: analysis.cooper_jacob.u_check +
              methodStatus(analysis, 'cooper_jacob', ''),
          } : null,
          analysis.theis ? {
            method: 'Theis type curve',
            T: S.sig(analysis.theis.transmissivity_m2_per_day, 4),
            note: 'S = ' + S.sig(analysis.theis.storativity, 2) +
              (analysis.theis.storativity_reliable ? ''
                : ' — not resolvable from a single pumped well') +
              methodStatus(analysis, 'theis', ''),
          } : null,
          analysis.papadopulos_cooper ? {
            method: 'Papadopulos-Cooper',
            T: S.sig(analysis.papadopulos_cooper.transmissivity_m2_per_day, 4),
            /* no storativity: the paragraph below says why it is not given,
             * and the Streamlit page and both reports leave it out too */
            note: (analysis.papadopulos_cooper_invalid ||
                C.phraseTable('pumping.pc_status')[
                  analysis.transmissivity_source === 'papadopulos_cooper'
                    ? 'adopted' : 'reported']),
          } : null,
        ].filter(Boolean)),
        el('p.muted', C.diagnosticText(analysis.diagnostic)),
        analysis.diagnostic
          ? el('p.muted', C.diagnosticThresholdsText(config().pumping)) : null,
        analysis.papadopulos_cooper
          ? el('p.muted', C.papadopulosCooperText(analysis)) : null,
        Object.keys(analysis.disqualified || {}).length ? el('p.muted',
          'Not adopted for the yield: ' +
          Object.keys(analysis.disqualified).map(function (k) {
            return C.METHOD_LABELS[k] + ' (' + analysis.disqualified[k] + ')';
          }).join('; ') + '.') : null,
      ]));
    }

    var rec2 = analysis.yield_recommendation;
    var intake = recommendedIntake();
    nodes.push(card('Yield recommendation', [
      rec2.safe_yield_m3_per_h ? S.statRow([
        S.stat('Safe yield', C.yieldRangeText(rec2),
          'range over the assumptions it rests on'),
        S.stat('Long term yield',
          rec2.long_term_yield_m3_per_h.toFixed(2) + ' m³/h',
          'before the ' + rec2.safety_factor + '× safety factor'),
        S.stat('Specific capacity', rec2.specific_capacity_m3hr_per_m
          ? C.formatG(C.roundSig(rec2.specific_capacity_m3hr_per_m, 2), 2) +
            ' m³/h per m' : '—', rec2.specific_capacity_basis || ''),
        /* the depth the reports and the design print, not the day-of-test
         * depth alone */
        S.stat('Pump intake', intake[0] !== null ? intake[0].toFixed(0) + ' m' : '—',
          'below the top of the casing' + (intake[1] ? ', ' + intake[1] : '')),
      ]) : el('div.callout.callout-warn', el('p',
        'Yield recommendation pending: ' + rec2.pending_reason + '.')),
      /* what the yield is worth, beside the number, as every report prints it */
      rec2.safe_yield_m3_per_h
        ? (rec2.is_indicative
          ? el('div.callout.callout-warn', [
            el('p', el('strong', 'Indicative, not established')),
            el('p', rec2.confidence_text)])
          : el('p.muted', rec2.confidence_text))
        : null,
      el('p', rec2.basis),
      rec2.envelope_basis ? el('div.callout', el('p', rec2.envelope_basis)) : null,
      /* the bands from the data themselves, beside the assumptions' range */
      C.spreadParagraphs(analysis, config().pumping).length
        ? el('div.callout', C.spreadParagraphs(analysis, config().pumping)
          .map(function (line) { return el('p', line); })) : null,
      rec2.pump_depth_basis ? el('p.muted', rec2.pump_depth_basis) : null,
      pumpIntakeMovedNote(),
      rec2.safe_yield_m3_per_h ? el('p.muted',
        'At 20 litres per person per day over an eight hour pumping day, the ' +
        'safe yield serves about ' +
        S.thousands(Math.round(rec2.safe_yield_m3_per_h * 1000 * 8 / 20)) +
        ' people — use the lower end of the range where the supply must not ' +
        'fail in a dry year.') : null,
    ]));

    nodes.push(seasonalCard(derived.analysis));
    nodes.push(photoCard('pumping', 'Pumping test photographs'));
    nodes.push(reportCard('Pumping test report', 'pumping',
      'Test details, the full field data tables, each analysis method with its ' +
      'figure, the results summary and the yield recommendation.'));
    nodes.push(fieldKitCard());
    nodes.push(nextStep('Next, assess the water quality.', 'Water quality', 'quality'));
    return nodes;
  };

  /* The month the test was run and the size of the annual swing, and what
   * the yield becomes at the end of the dry season and in a drought year. A
   * test measures one day; the borehole has to supply the village on the
   * worst one, and those are months apart. */
  function seasonalSettings() {
    var stored = store.get('seasonal') || {};
    return {
      month: stored.month === undefined ? null : stored.month,
      rangeM: stored.rangeM === undefined ? null : stored.rangeM,
      touched: !!stored.touched,
    };
  }

  function currentSeasonal(analysis) {
    var chosen = seasonalSettings();
    var cfg = config();
    return C.seasonalYield(analysis, cfg.pumping, {
      month: chosen.touched ? chosen.month : undefined,
      annualRangeM: chosen.rangeM,
    });
  }

  function seasonalCard(analysis) {
    if (!analysis) return null;
    var chosen = seasonalSettings();
    var cfg = config();
    var read = C.monthOf(analysis.test && analysis.test.site
      ? analysis.test.site.date : '');
    var result = currentSeasonal(analysis);
    var months = [{ value: '0', label: 'not known' }].concat(
      C.MONTH_NAMES.map(function (name, i) {
        return { value: String(i + 1), label: name };
      }));
    var nodes = [
      el('p.muted', 'A pumping test measures one day. The borehole has to ' +
        'supply the village on the worst day, and those are months apart: the ' +
        'water table is highest at the end of the rains and lowest in April ' +
        'or May, so when the test was run changes what it proves.'),
      el('div.field-row', [
        field('Month the test was run',
          S.selectInput(String((chosen.touched ? chosen.month : read.month) || 0),
            months, function (v) {
              store.set('seasonal', Object.assign({}, store.get('seasonal') || {},
                { month: Number(v) || null, touched: true }));
              /* the intake the design draws follows the projection */
              rebuildDesign();
              render();
            }), 'Read from the field sheet where it can be'),
        field('Annual water-table swing (m)',
          S.numberInput(chosen.rangeM === null
            ? cfg.pumping.seasonal_allowance_m : chosen.rangeM,
          function (v) {
            store.set('seasonal', Object.assign({}, store.get('seasonal') || {},
              { rangeM: (v === null || v === undefined) ? null : Number(v) }));
            rebuildDesign();
            render();
          }, { min: 0, max: 30, step: 0.5 }),
        'Wet-season high to dry-season low. A single test cannot measure it'),
      ]),
    ];
    if (result.month_note) {
      nodes.push(el('div.callout.callout-warn', el('p', result.month_note)));
    }
    if (!result.is_established) {
      nodes.push(el('p.muted', result.pending_reason ||
        'The seasonal projection is not available for this test.'));
      return card('Through the year', nodes);
    }

    nodes.push(el('p', result.summary));
    nodes.push(S.table(
      ['Scenario', 'Further decline (m)', 'Static level (m)',
        'Available drawdown (m)', 'Safe yield (m3/h)', 'Pump intake (m)'],
      result.scenarios.map(function (sc) {
        return [sc.title, C.pyFixed(sc.decline_m, 1),
          C.fmtNum(sc.static_water_level_m), C.fmtNum(sc.available_drawdown_m),
          C.fmtNum(sc.safe_yield_m3_per_h),
          C.fmtNum(sc.pump_installation_depth_m)];
      })));
    if (result.dry_season_loss_percent > 1) {
      nodes.push(el('div.callout.callout-warn', el('p',
        'By the end of the dry season this borehole yields about ' +
        C.pyFixed(result.dry_season_loss_percent, 0) + '% less than it did on ' +
        'the day of the test. Size the supply on the dry-season figure.')));
    }
    /* the one intake depth, the deeper of the recommendation's and the
     * drought scenario's, with the reason */
    var intake = C.pumpIntakeDepth(analysis, result);
    if (intake[0] !== null) {
      nodes.push(el('div.callout', el('p', 'Set the pump intake at ' +
        C.fmtNum(intake[0]) + ' m below the top of the casing, ' +
        (intake[1] || 'deep enough for the drought case') +
        '. The pump is fitted once, and one that draws air in ' +
        'a bad year loses the village its borehole in the year it is needed ' +
        'most.')));
    }
    nodes.push(S.checkList(result.scenarios.map(function (sc) {
      return { level: 'info', message: sc.title + ' — ' + sc.note };
    })));
    nodes.push(el('p.muted', 'The annual range used is ' +
      C.pyFixed(result.annual_range_m, 1) + ' m — ' + result.range_source +
      '. It is the one number here a single test cannot measure, and every ' +
      'figure in the table moves with it.'));
    return card('Through the year', nodes);
  }

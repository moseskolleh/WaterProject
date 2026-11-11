
  /* --- overview ------------------------------------------------------------- */

  PAGES.overview = function () {
    var samples = GWT.data.samples || {};
    var stages = [
      ['Site', 'site', !!store.get('site.community'), 'Project and location recorded'],
      ['Geophysics', 'ves', pageDone('ves'),
        derived.interpretations ? derived.interpretations.length + ' soundings interpreted'
          : 'No sounding loaded'],
      ['Design', 'design', pageDone('design'),
        derived.design ? C.fmtNum(derived.design.total_screen_length_m) + ' m of screen'
          : 'No design yet'],
      ['Pumping test', 'pumping', pageDone('pumping'),
        derived.analysis && derived.analysis.transmissivity_m2_per_day
          ? 'T = ' + S.sig(derived.analysis.transmissivity_m2_per_day, 3) + ' m²/day'
          : (derived.test ? 'Parsed; results pending' : 'No test loaded')],
      ['Water quality', 'quality', pageDone('quality'),
        derived.assessment
          ? (derived.assessment.health_exceedances.length
            ? derived.assessment.health_exceedances.length + ' health ' +
              S.plural(derived.assessment.health_exceedances.length, 'exceedance')
            : C.VERDICT_LONG[derived.assessment.verdict_state])
          : 'No analysis loaded'],
      ['Cost', 'costing', pageDone('costing'),
        derived.estimate ? S.money(derived.estimate.total_cost_usd, 0) + ' total cost'
          : 'No estimate yet'],
    ];

    return [
      pageHead('Overview', 'The whole borehole lifecycle in one workspace: site ' +
        'the well, design it, test it, sample it, cost it and hand it over. ' +
        'Everything runs in this browser — no data is uploaded anywhere.'),

      derived.analysis || derived.assessment || derived.design
        ? card('Headline results', [
          S.statRow([
            derived.analysis && derived.analysis.transmissivity_m2_per_day
              ? S.stat('Transmissivity',
                S.sig(derived.analysis.transmissivity_m2_per_day, 3) + ' m²/day',
                'preferred method') : null,
            derived.analysis && derived.analysis.yield_recommendation.safe_yield_m3_per_h
              ? S.stat('Safe yield',
                C.yieldRangeText(derived.analysis.yield_recommendation),
                'with the stated range') : null,
            derived.design
              ? S.stat('Total depth', C.fmtNum(derived.design.total_depth_m) + ' m',
                derived.design.screens.length + ' screened ' +
                S.plural(derived.design.screens.length, 'section')) : null,
            derived.assessment && derived.assessment.wqi
              ? S.stat('Water quality index', String(derived.assessment.wqi.value),
                derived.assessment.wqi.rating) : null,
            derived.estimate
              ? S.stat('Cost per metre', S.money(derived.estimate.cost_per_meter_usd, 0),
                'total cost basis') : null,
          ].filter(Boolean)),
        ]) : null,

      card('Progress', [
        el('div.grid.grid-3', stages.map(function (stage) {
          return el('button.stat', {
            type: 'button', style: { cursor: 'pointer', textAlign: 'left' },
            onclick: function () { goto(stage[1]); },
          }, [
            el('span.stat-label', [stage[0], ' ',
              S.badge(stage[2] ? 'done' : 'to do', stage[2] ? 'ok' : null)]),
            el('span.stat-note', stage[3]),
          ]);
        })),
      ], { note: 'Click a stage to go there.' }),

      card('Start from a sample project', [
        el('p.muted', 'Each sample is a real dataset transcribed from a field ' +
          'report, and loads as the original template workbook, so it exercises ' +
          'exactly the same reader an uploaded file does.'),
        el('div.grid.grid-2', Object.keys(samples).map(function (key) {
          var sample = samples[key];
          return el('div.card', [
            el('div.card-body', [
              el('h3', sample.label),
              el('p.muted', sample.note),
              button('Load ' + sample.label.split(' - ')[0], function () {
                loadSample(key);
              }),
            ]),
          ]);
        })),
      ]),

      card('Or start from your own data', [
        el('div.grid.grid-2', [
          uploadZone('ves', 'VES field data (.xlsx)',
            'One worksheet per sounding, AB/2 · MN · apparent resistivity'),
          uploadZone('drilling', 'Drilling log (.xlsx)',
            'Depth intervals with lithology and water strikes'),
          uploadZone('pumping', 'Pumping test (.xlsx or .docx)',
            'Step or constant discharge with recovery',
            '.xlsx,.xls,.docx'),
          uploadZone('quality', 'Water quality results (.xlsx)',
            'Parameter · value · unit from the laboratory'),
        ]),
        el('p.muted', { style: { marginTop: '0.8rem' } },
          'Not sure of the layout? The Templates page has a blank workbook for ' +
          'each of these.'),
      ]),

      installCard(),

      nextStep('New to the toolkit? The guided start walks through one borehole ' +
        'from field sheet to signed report.', 'Guided start', 'guided'),
    ].filter(Boolean);
  };

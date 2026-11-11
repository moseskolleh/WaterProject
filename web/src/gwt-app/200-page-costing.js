
  /* --- costing -------------------------------------------------------------- */

  PAGES.costing = function () {
    var costing = store.get('costing');
    function bindCost(key, rebuild) {
      return function (value) {
        store.set('costing.' + key, value);
        rebuildCosting();
        render();
      };
    }
    var nodes = [
      pageHead('Costing & bill of quantities', 'The RWSN Borehole Costing Model: ' +
        'every line carries a construction stage and a resource category, and the ' +
        "contractor's cost is kept distinct from the client's price."),
      card('Inputs', [
        el('div.field-row', [
          field('Total depth (m)', S.numberInput(
            derived.design ? derived.design.total_depth_m : costing.total_depth_m,
            bindCost('total_depth_m')),
            derived.design ? 'from the borehole design' : 'no design yet'),
          field('Mobilisation, one way (km)',
            S.numberInput(costing.mobilisation_km, bindCost('mobilisation_km'))),
          field('Water quality samples',
            S.numberInput(costing.wq_samples, bindCost('wq_samples'))),
          field('Handpumps', S.numberInput(costing.handpumps, bindCost('handpumps')),
            'set 0 when the pump is a separate contract'),
        ]),
        el('div.field-row', [
          field('Overheads (%)', S.numberInput(costing.overheads, bindCost('overheads'))),
          field('Margin (%)', S.numberInput(costing.margin, bindCost('margin'))),
          field('Contingency (%)', S.numberInput(costing.contingency, bindCost('contingency'))),
          field('VAT / GST (%)', S.numberInput(costing.vat, bindCost('vat'))),
          field('Exchange rate (SLE per US$)',
            S.numberInput(costing.exchange, bindCost('exchange'))),
        ]),
      ]),
    ];

    if (!derived.estimate) {
      nodes.push(S.empty('Enter a total depth (or produce a borehole design) to ' +
        'build the bill of quantities.'));
      return nodes;
    }

    var estimate = derived.estimate;
    nodes.push(card('Cost summary', [
      S.statRow([
        S.stat('Direct works', S.money(estimate.direct_cost_usd, 0)),
        S.stat('Total cost', S.money(estimate.total_cost_usd, 0),
          'including ' + estimate.overheads_percent + '% overheads'),
        S.stat('Cost per metre', S.money(estimate.cost_per_meter_usd, 0)),
        S.stat('Contract price', S.money(estimate.price_usd, 0),
          'with ' + estimate.margin_percent + '% margin'),
        S.stat('Planning budget', S.money(estimate.budget_usd, 0),
          'with ' + estimate.contingency_percent + '% contingency'),
      ]),
      el('div.split', [
        charts.figure(charts.costBreakdown(estimate, { mode: 'stage' }),
          'Direct cost by construction stage', { filename: 'cost_by_stage' }),
        charts.figure(charts.costBreakdown(estimate, { mode: 'category' }),
          'Direct cost by resource category', { filename: 'cost_by_category' }),
      ]),
      estimate.assumptions.length ? el('div', [
        el('h4', 'Assumptions where a figure was not supplied'),
        el('ul', estimate.assumptions.map(function (t) { return el('li.muted', t); })),
      ]) : null,
      estimate.flags.length ? S.checkList(estimate.flags.map(function (f) {
        return { level: f.level, message: f.message };
      })) : null,
    ]));

    var spreads = costSpreads();
    if (spreads) {
      nodes.push(card(C.phrase('cost_range.heading'), costSpreadNodes(
        C.costRangeText(spreads.single), C.costRangeRows(spreads.single),
        charts.costDistribution(spreads.single.curve, costMarks(spreads.single, false),
          { title: C.phraseTable('cost_range.marks').title }),
        C.phrase('cost_range.figure_caption'), 'cost_distribution')));
      /* what one more measurement is worth, beside the odds and the costs
       * it is worked out from (PLAN.md step 3.5) */
      nodes.push(card(C.phrase('measurement.heading'),
        measurementNodes(surveyMeasurements(spreads.single))));
    }

    nodes.push(card('Bill of quantities', [
      S.table([
        { key: 'Code', label: 'Code' }, { key: 'Stage', label: 'Stage' },
        { key: 'Item', label: 'Item' }, { key: 'Unit', label: 'Unit' },
        { key: 'Quantity', label: 'Qty', align: 'right',
          format: function (v) { return S.thousands(v, 2); } },
        { key: 'Rate (USD)', label: 'Rate (US$)', align: 'right',
          format: function (v) { return S.thousands(v, 2); } },
        { key: 'Amount (USD)', label: 'Amount (US$)', align: 'right',
          format: function (v) { return S.thousands(v, 2); } },
      ], estimate.boq_rows()),
      el('div.btn-row', [
        button('Download BoQ (.xlsx)', async function () {
          var rows = estimate.boq_rows();
          var header = Object.keys(rows[0]);
          var sheets = [
            { name: 'BoQ', rows: [header].concat(rows.map(function (r) {
              return header.map(function (h) { return r[h]; });
            })) },
            { name: 'Summary', rows: [['Item', 'US$', 'SLE']].concat([
              ['Direct works cost', estimate.direct_cost_usd, estimate.in_local(estimate.direct_cost_usd)],
              ['Overheads', estimate.overheads_usd, estimate.in_local(estimate.overheads_usd)],
              ['Total cost', estimate.total_cost_usd, estimate.in_local(estimate.total_cost_usd)],
              ['Margin', estimate.margin_usd, estimate.in_local(estimate.margin_usd)],
              ['Contract price', estimate.price_usd, estimate.in_local(estimate.price_usd)],
              ['Contingency', estimate.contingency_usd, estimate.in_local(estimate.contingency_usd)],
              ['Planning budget', estimate.budget_usd, estimate.in_local(estimate.budget_usd)],
            ]) },
          ];
          var bytes = await S.writeXlsx(sheets);
          S.download(S.slug(siteLabel()) + '_boq.xlsx', new Blob([bytes]));
        }, { variant: 'ghost' }),
      ]),
    ]));

    var workingRates = costingRates();
    nodes.push(card('Unit rates', [
      el('p.muted', 'The bundled rates are indicative and must be confirmed ' +
        'against current local prices before the estimate is used in a tender. ' +
        'Edit any rate here; blank restores the catalogue value. The minimum and ' +
        'maximum are what the cost distribution draws the rate between, and move ' +
        'in proportion with an edited rate.'),
      S.table([
        { key: 'code', label: 'Code' }, { key: 'stage', label: 'Stage' },
        { key: 'item', label: 'Item' }, { key: 'unit', label: 'Unit' },
        { key: 'rate', label: 'Rate (US$)', align: 'right' },
        { key: 'min', label: 'Min (US$)', align: 'right' },
        { key: 'max', label: 'Max (US$)', align: 'right' },
      ], C.loadRates().map(function (rate, i) {
        var working = C.rateTriangle(workingRates[i]);
        return {
          code: rate.code, stage: rate.stage, item: rate.item, unit: rate.unit,
          min: S.thousands(working[0], 2), max: S.thousands(working[2], 2),
          rate: S.numberInput(
            (costing.rateOverrides || {})[rate.code] !== undefined
              ? costing.rateOverrides[rate.code] : rate.unit_cost_usd,
            function (value) {
              store.set('costing.rateOverrides.' + rate.code, value);
              rebuildCosting(); render();
            }, { step: 'any', class: 'input cell', style: { maxWidth: '7rem' },
              'aria-label': 'Rate (US$), ' + rate.code + ' ' + rate.item }),
        };
      })),
    ]));

    /* The survey's odds at its first-ranked point are offered beside the
     * typed rate, never put in its place without a click: a programme
     * estimate that moved because a sounding was inverted on another page
     * would change silently. */
    var firstOdds = null;
    if ((derived.interpretations || []).length) {
      /* by position, not id: two points can share an id */
      var first = C.assessSiting(derived.interpretations, config().ves)[0].index;
      firstOdds = surveyOdds()[first] || null;
    }
    var offeredRate = firstOdds ? C.programmeRate(firstOdds) : null;
    nodes.push(card('Programme of works', [
      firstOdds ? el('div.callout', [
        el('p', C.programmeOffer(firstOdds)),
        button(C.phrase('odds.programme_use', { p: offeredRate }), function () {
          bindCost('success_rate')(offeredRate);
        }, { variant: 'ghost' }),
      ]) : null,
      el('div.field-row', [
        field('Successful boreholes required',
          S.numberInput(costing.programme_n, bindCost('programme_n'))),
        field('Siting success rate (%)',
          S.numberInput(costing.success_rate, bindCost('success_rate')),
          'the rest are budgeted as dry attempts'),
        field('Average move between sites (km)',
          S.numberInput(costing.inter_site_km, bindCost('inter_site_km'))),
      ]),
      derived.programme ? el('div', [
        S.statRow([
          S.stat('Attempts planned', String(derived.programme.n_attempted),
            'for ' + derived.programme.n_successful + ' successful boreholes'),
          S.stat('Programme cost', S.money(derived.programme.total_cost_usd, 0)),
          S.stat('Price per borehole',
            S.money(derived.programme.price_per_successful_well_usd, 0),
            'carrying the expected dry attempts'),
          S.stat('Planning budget', S.money(derived.programme.budget_usd, 0)),
        ]),
        charts.figure(charts.programmeGantt(derived.programme),
          'Indicative programme of works', { filename: 'programme' }),
        el('ul', derived.programme.assumptions.map(function (t) {
          return el('li.muted', t);
        })),
      ].concat(spreads && spreads.programme ? [el('h3', C.phrase('cost_range.heading'))]
        .concat(costSpreadNodes(
          [C.phrase('cost_range.which_is_which')].concat(
            C.programmeRangeText(spreads.programme)),
          C.programmeRangeRows(spreads.programme),
          charts.costDistribution(spreads.programme.curve, costMarks(spreads.programme, true),
            { title: C.phraseTable('cost_range.marks').programme_title }),
          C.phrase('cost_range.programme_figure_caption'), 'programme_distribution'))
        : [])) : el('p.muted', 'Set more than one borehole to see the package estimate.'),
    ]));

    nodes.push(reportCard('Cost estimate report', 'costing',
      'Method, the basis of the estimate, the full bill of quantities, the cost ' +
      'and price summary and the exclusions.'));
    nodes.push(nextStep('Next, the supervision checklists.', 'Supervision', 'supervision'));
    return nodes;
  };

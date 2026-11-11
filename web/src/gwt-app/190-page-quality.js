
  /* --- water quality -------------------------------------------------------- */

  /* The sentence that says what the Piper and Stiff diagrams show: the water
   * type, the milliequivalent percentages behind it and what that composition
   * means for where the water came from. Null without a complete major-ion
   * analysis, because there is then no facies to name. */
  function faciesSentence(sample) {
    var facies = sample ? C.faciesOf(sample) : null;
    return facies ? el('p', facies.sentence) : null;
  }

  PAGES.quality = function () {
    var nodes = [
      pageHead('Water quality', 'Laboratory results against WHO and national ' +
        'limits, a charge balance check on the analysis itself, corrosivity and ' +
        'a materials recommendation, and the hydrochemical facies diagrams.'),
      card('Laboratory results', [
        uploadZone('quality', 'Water quality results (.xlsx)',
          'Parameter · value · unit, with "<0.01" for below-detection results'),
      ]),
    ];

    if (!derived.assessment) {
      nodes.push(S.empty('No water quality analysis loaded.',
        button('Overview', function () { goto('overview'); }, { variant: 'ghost' })));
      return nodes;
    }

    var a = derived.assessment;
    var toneFor = {
      /* A national exceedance is a compliance failure, not a taste problem,
       * so it reads as badly as a health one. A row that could not be graded
       * is its own thing: a question, not a finding. */
      exceeds_health: 'row-bad', exceeds_national: 'row-bad',
      exceeds_aesthetic: 'row-warn', indeterminate: 'row-info',
      within_limits: '',
    };

    nodes.push(card('Verdict', [
      el('div.callout.callout-' + C.VERDICT_TONE[a.verdict_state], [
        el('p', el('strong', C.VERDICT_LONG[a.verdict_state])),
        el('p', a.verdict),
      ]),
      S.statRow([
        a.wqi ? S.stat('Water quality index', String(a.wqi.value), a.wqi.rating) : null,
        a.health_risk ? S.stat('Hazard index', String(a.health_risk.hazard_index),
          a.health_risk.rating) : null,
        a.ionic ? S.stat('Ionic balance', a.ionic.error_percent.toFixed(1) + '%',
          Math.abs(a.ionic.error_percent) <= 5 ? 'within normal laboratory practice'
            : 'review the analysis') : null,
        a.corrosivity && a.corrosivity.rsi !== null
          ? S.stat('Corrosivity', a.corrosivity.classification,
            'Ryznar ' + a.corrosivity.rsi) : null,
      ].filter(Boolean)),
      a.flags.length ? S.checkList(a.flags.map(function (f) {
        return { level: f.level, message: f.message };
      })) : null,
    ]));

    nodes.push(card('Results against guideline values', [
      S.table([
        { key: 'parameter', label: 'Parameter' },
        { key: 'value', label: 'Result', align: 'right',
          format: function (v, row) {
            return v === null ? (row.below_detection ? '< DL' : '—') : C.fmtNum(v, 4);
          } },
        { key: 'unit', label: 'Unit' },
        { key: 'who_health', label: 'WHO health' },
        { key: 'sl_standard', label: 'National' },
        { key: 'status', label: 'Status',
          format: function (v) {
            var tone = (v === 'exceeds_health' || v === 'exceeds_national') ? 'bad'
              : (v === 'within_limits' ? 'ok'
                : (v === 'exceeds_aesthetic' ? 'warn'
                  : (v === 'indeterminate' ? 'info' : null)));
            return S.badge(docx.statusLabel(v), tone);
          } },
        { key: 'remark', label: 'Remark' },
      ], a.rows, { rowClass: function (row) { return toneFor[row.status] || ''; } }),
      provisionalStandardsNote(),
    ].filter(Boolean)));

    if (a.ionic) {
      nodes.push(card('Ionic balance', [
        el('p', 'Cations sum to ' + a.ionic.sum_cations_meq.toFixed(2) +
          ' meq/L and anions to ' + a.ionic.sum_anions_meq.toFixed(2) +
          ' meq/L, a charge balance error of ' + a.ionic.error_percent.toFixed(1) +
          '%. Errors within 5% are normal laboratory practice; 5 to 10% warrants ' +
          'review; more than 10% means an unreliable analysis or a missing ' +
          'major ion.' + (a.ionic.used_alkalinity_for_bicarbonate
            ? ' Bicarbonate was derived from the reported alkalinity.' : '')),
      ]));
    }

    if (a.corrosivity && a.corrosivity.rsi !== null) {
      nodes.push(card('Corrosivity and materials', [
        el('div.callout' + (a.corrosivity.is_aggressive ? '.callout-warn' : '.callout-ok'),
          el('p', a.corrosivity.verdict)),
        S.table([
          { key: 'index', label: 'Index' }, { key: 'value', label: 'Value', align: 'right' },
        ], [
          { index: 'Langelier Saturation Index (LSI)', value: a.corrosivity.lsi },
          { index: 'Ryznar Stability Index (RSI)', value: a.corrosivity.rsi },
          { index: 'Aggressive Index (AI)', value: a.corrosivity.aggressive_index },
          { index: 'Larson-Skold ratio', value: a.corrosivity.larson_skold },
        ]),
        el('p', a.corrosivity.materials_note),
        a.corrosivity.assumptions.length
          ? el('ul', a.corrosivity.assumptions.map(function (t) { return el('li.muted', t); }))
          : null,
      ]));
    }

    var piperNode = charts.piper([derived.sample]);
    var stiffNode = charts.stiff(derived.sample);
    if (piperNode || stiffNode) {
      nodes.push(card('Hydrochemical facies', [
        faciesSentence(derived.sample),
        el('div.split', [
          piperNode ? charts.figure(piperNode, 'Piper trilinear diagram',
            { filename: 'piper' }) : null,
          stiffNode ? charts.figure(stiffNode, 'Stiff diagram',
            { filename: 'stiff' }) : null,
        ]),
      ].filter(Boolean)));
    }

    nodes.push(photoCard('quality', 'Sampling photographs'));
    nodes.push(reportCard('Water quality report', 'quality',
      'Sample details, the full comparison table, the ionic balance, corrosivity ' +
      'and materials, the facies diagrams and the recommendations.'));
    nodes.push(nextStep('Next, cost the works.', 'Costing & BoQ', 'costing'));
    return nodes;
  };

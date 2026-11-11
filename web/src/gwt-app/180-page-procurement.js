
  /* --- procurement ----------------------------------------------------------
   * A bill of quantities is an estimate until somebody signs it. Afterwards
   * the money leaks in three places: work measured that nobody authorised,
   * work paid for twice, and retention nobody tracked. All three are shown
   * here rather than netted away.
   * ---------------------------------------------------------------------- */

  function procurementState() {
    return Object.assign({ contract: null, measured: {}, variations: [],
      number: 1, date: '', previous: 0, due: '' }, store.get('procurement') || {});
  }

  function saveProcurement(patch) {
    store.set('procurement', Object.assign(procurementState(), patch));
    render();
  }

  PAGES.procurement = function () {
    var state = procurementState();
    var nodes = [
      pageHead('Procurement', 'A bill of quantities is an estimate until ' +
        'somebody signs it, and a contract afterwards. This page tracks what ' +
        'was measured against what was authorised, records the variation ' +
        'orders that move the line, and produces the interim payment ' +
        'certificate. Work that was done but nobody authorised is shown and ' +
        'withheld — not because it was unnecessary, but because paying for ' +
        'it is a decision somebody signs.'),
    ];

    if (!state.contract) {
      nodes.push(card('Award the contract', [
        el('p.muted', 'The cost estimate is not a contract until it is ' +
          'awarded. Freezing it here means the certificate is measured ' +
          'against the frozen copy, so a later change to the design cannot ' +
          'move what was signed.'),
        !derived.estimate
          ? S.empty('No cost estimate yet.',
            button('Costing & BoQ', function () { goto('costing'); },
              { variant: 'ghost' }))
          : el('div', [
            el('div.field-row', [
              field('Contract reference', S.textInput(
                store.get('procurement.ref', ''), function (v) {
                  store.set('procurement.ref', String(v).trim());
                }, { placeholder: 'WSD/2024/017' }), ''),
              field('Retention (%)', S.numberInput(
                store.get('procurement.retention', 10), function (v) {
                  store.set('procurement.retention', v === null ? 10 : Number(v));
                }, { min: 0, max: 25, step: 0.5 }), ''),
              field('Advance (%)', S.numberInput(
                store.get('procurement.advance', 0), function (v) {
                  store.set('procurement.advance', v === null ? 0 : Number(v));
                }, { min: 0, max: 50, step: 5 }), ''),
            ]),
            el('div.btn-row', [
              button('Award this estimate as the contract', function () {
                var site = store.get('site') || {};
                saveProcurement({
                  contract: C.contractFromEstimate(derived.estimate,
                    store.get('procurement.ref', '') || '(unreferenced)', {
                      contractor: site.contractor || '', client: site.client || '',
                      retention_percent: store.get('procurement.retention', 10),
                      advance_percent: store.get('procurement.advance', 0),
                    }),
                  measured: {}, variations: [], number: 1, previous: 0,
                });
                S.toast('Contract frozen.', 'ok');
              }),
            ]),
          ]),
      ]));
      return nodes;
    }

    var contract = state.contract;
    var measurements = contract.lines.map(function (line) {
      return { code: line.code,
        quantity: Number(state.measured[line.code] || 0) };
    }).concat(Object.keys(state.measured).filter(function (code) {
      return !contract.lines.some(function (l) { return l.code === code; });
    }).map(function (code) {
      return { code: code, quantity: Number(state.measured[code] || 0) };
    }));
    var certificate = C.certify(contract, measurements, {
      number: state.number, date: state.date, variations: state.variations,
      previouslyCertifiedUsd: state.previous,
    });

    var due = String(state.due || '');
    nodes.push(card('Contract', [
      S.statRow([
        S.stat('Reference', contract.ref),
        S.stat('Contract sum', C.money0(certificate.contract_sum_usd)),
        S.stat('Revised sum', C.money0(certificate.revised_sum_usd),
          'contract plus variations'),
        S.stat('Progress', certificate.percent_complete === null ? '—'
          : C.pyFixed(certificate.percent_complete, 0) + '%',
        'of the revised sum'),
      ]),
      /* the contract's completion date as any extension of time leaves it,
       * which the Portfolio page's contractor scorecards set the drilling
       * log's completion date against (PLAN.md step 6.3) */
      field(C.phrase('scorecards.page_due'), S.textInput(due, function (v) {
        saveProcurement({ due: String(v).trim() });
      }, { placeholder: '2024-06-30', 'data-procurement': 'due' }), C.phrase('scorecards.page_due_help')),
      due && C.isoDay(due) === null
        ? el('div.callout.callout-warn', el('p', C.phrase('scorecards.page_due_unread'))) : null,
      el('div.btn-row', [
        button('Start again from the estimate', function () {
          saveProcurement({ contract: null, measured: {}, variations: [] });
        }, { variant: 'ghost' }),
      ]),
    ].filter(Boolean)));

    nodes.push(card('Measured to date', [
      el('p.muted', 'Cumulative quantities, not increments: this is ' +
        'everything done so far on each line. The certificate works out what ' +
        'is new.'),
      S.table([
        { key: 'code', label: 'Code' },
        { key: 'item', label: 'Item' },
        { key: 'unit', label: 'Unit' },
        { key: 'contract_quantity', label: 'Contract', align: 'right' },
        { key: 'authorised_quantity', label: 'Authorised', align: 'right' },
        { key: 'measured_quantity', label: 'Measured to date', align: 'right',
          format: function (value, row) {
            return S.numberInput(state.measured[row.code] || 0, function (v) {
              var next = Object.assign({}, procurementState().measured);
              next[row.code] = v === null ? 0 : Number(v);
              saveProcurement({ measured: next });
            }, { min: 0, step: 1 });
          } },
        { key: 'payable_amount_usd', label: 'Payable', align: 'right',
          format: function (v) { return C.money0(v); } },
      ], certificate.lines),
    ]));

    nodes.push(variationCard(state, certificate));
    nodes.push(certificateCard(state, contract, certificate));
    return nodes;
  };

  function variationCard(state, certificate) {
    var draft = { ref: '', code: '', quantity_delta: 0, rate_usd: null,
      reason: '', authorised_by: '',
      date: new Date().toISOString().slice(0, 10) };
    var codes = state.contract.lines.map(function (line) {
      return { value: line.code, label: line.code + ' — ' + line.item };
    });
    var nodes = [
      el('p.muted', 'A variation is what makes extra work payable. It needs a ' +
        'reason and a name: an unsigned variation is a request, not an ' +
        'instruction.'),
    ];
    if (state.variations.length) {
      nodes.push(S.table(['Reference', 'Date', 'Code', 'Quantity', 'New rate',
        'Reason', 'Authorised by'],
      state.variations.map(function (v) {
        return [v.ref, v.date, v.code,
          (v.quantity_delta > 0 ? '+' : '') + C.formatG(v.quantity_delta),
          v.rate_usd === null || v.rate_usd === undefined ? '—'
            : C.money0(v.rate_usd),
          v.reason || '', v.authorised_by || ''];
      })));
    }
    nodes.push(el('div.field-row', [
      field('Reference', S.textInput('', function (v) {
        draft.ref = String(v).trim();
      }, { placeholder: 'VO-1' }), ''),
      field('Line', S.selectInput('', [{ value: '', label: 'choose a line' }]
        .concat(codes), function (v) { draft.code = v; }), ''),
      field('Quantity change', S.numberInput(0, function (v) {
        draft.quantity_delta = v === null ? 0 : Number(v);
      }, { step: 1 }), 'negative to omit work'),
      field('New rate (USD)', S.numberInput(null, function (v) {
        draft.rate_usd = (v === null || v === undefined) ? null : Number(v);
      }, { min: 0, step: 1 }), 'leave blank to keep the contract rate'),
    ]));
    nodes.push(el('div.field-row', [
      field('Reason', S.textInput('', function (v) { draft.reason = String(v); },
        { placeholder: 'Why the work changed' }), ''),
      field('Authorised by', S.textInput('', function (v) {
        draft.authorised_by = String(v).trim();
      }, { placeholder: 'Name' }), ''),
    ]));
    nodes.push(el('div.btn-row', [
      button('Record the variation', function () {
        if (!draft.ref || !draft.code) {
          S.toast('A variation needs a reference and a line.', 'warn');
          return;
        }
        saveProcurement({
          variations: procurementState().variations.concat([draft]),
        });
        S.toast('Recorded.', 'ok');
      }, { variant: 'ghost' }),
    ]));
    return card('Variation orders', nodes);
  }

  function certificateCard(state, contract, certificate) {
    var nodes = [
      el('div.field-row', [
        field('Certificate number', S.numberInput(state.number, function (v) {
          saveProcurement({ number: Math.max(Number(v) || 1, 1) });
        }, { min: 1, step: 1 }), ''),
        field('Date', S.textInput(state.date, function (v) {
          saveProcurement({ date: String(v).trim() });
        }, { placeholder: 'YYYY-MM-DD' }), ''),
        field('Previously certified (USD)',
          S.numberInput(state.previous, function (v) {
            saveProcurement({ previous: v === null ? 0 : Number(v) });
          }, { min: 0, step: 100 }),
        'leave this at zero on a later certificate and the work is paid for twice'),
      ]),
    ];
    if (certificate.problems.length) {
      nodes.push(S.checkList(certificate.problems.map(function (message) {
        return { level: 'warning', message: message };
      })));
    }
    nodes.push(el('div.callout.callout-' +
      (certificate.overmeasure_usd ? 'warn' : 'ok'),
    el('p', certificate.summary)));
    if (certificate.overmeasure_usd) {
      nodes.push(el('div.callout.callout-bad', el('p',
        C.money0(certificate.overmeasure_usd) + ' of work has been measured ' +
        'but not authorised, so it is not certified here. Record a variation ' +
        'order against those lines and it becomes payable on the next ' +
        'certificate.')));
    }
    nodes.push(S.table(['', ' '], C.contractSummaryRows(contract, certificate)));
    nodes.push(el('div.btn-row', [
      button('Interim payment certificate (.docx)', async function (event) {
        var host = event.target.closest('.card');
        var issued = null;
        charts.usePrintPalette(true);
        try {
          await S.withBusy(host, 'Building the certificate…', async function () {
            var builder = await GWT.docx.paymentCertificate({
              style: config().style, contract: contract,
              certificate: certificate, signOff: signOffFor('costing'),
              /* a certificate makes no claim about the water, so it is not
               * held back by the costing gate's design requirements */
              readiness: reportReadiness('procurement'),
              areaNote: areaNote(), areaMaps: await areaFigures(false),
              issue: issueFor('procurement'),
            });
            var name = 'IPC_' + certificate.number + '.docx';
            var bytes = await builder.build();
            S.download(name, bytes);
            issued = recordIssue(builder.record, name, bytes);
          });
          S.toast('Certificate ready.' + codeWords(issued), 'ok');
        } catch (err) {
          S.toast('Could not build the certificate: ' + err.message, 'error');
        } finally {
          charts.usePrintPalette(false);
        }
      }),
    ]));
    return card('Certificate', nodes);
  }

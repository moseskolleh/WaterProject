
  /* --- supervision ---------------------------------------------------------- */

  PAGES.supervision = function () {
    var items = C.loadChecklists();
    var responses = store.get('supervision.responses') || {};
    var evaluation = C.evaluateChecklist(items, responses);
    var checks = store.get('supervision.checks') || {};

    function bindCheck(key) {
      return function (value) {
        store.set('supervision.checks.' + key, value);
        render();
      };
    }

    var fieldChecks = [];
    if (S.isNum(checks.sand1) || S.isNum(checks.sand2) || S.isNum(checks.sand3)) {
      fieldChecks.push(C.sandContentCheck(
        [checks.sand1, checks.sand2, checks.sand3].filter(S.isNum)));
    }
    if (S.isNum(checks.deviation) && S.isNum(checks.plumbDepth) && S.isNum(checks.casingId)) {
      fieldChecks.push(C.verticalityCheck(checks.deviation, checks.plumbDepth, checks.casingId));
    }
    if (S.isNum(checks.designYield) && S.isNum(checks.openArea)) {
      fieldChecks.push(C.screenOpenAreaCheck(checks.designYield, checks.openArea));
    }
    if (derived.analysis && derived.analysis.yield_recommendation.specific_capacity_m3hr_per_m) {
      var last = derived.test.steps[derived.test.steps.length - 1];
      fieldChecks.push(C.specificCapacityCheck(last.discharge_m3_per_h || 0,
        derived.analysis.max_drawdown_m || 0));
    }
    if (S.isNum(checks.d50pack) && S.isNum(checks.d50aquifer)) {
      fieldChecks.push(C.packAquiferRatioCheck(checks.d50pack, checks.d50aquifer));
    }
    if (S.isNum(checks.casingOd) && derived.design) {
      fieldChecks.push(C.annularSpaceCheck(derived.design.borehole_diameter_in, checks.casingOd));
    }
    if (S.isNum(checks.loggedM) && S.isNum(checks.claimedM)) {
      fieldChecks.push(C.metresReconciliationCheck(checks.loggedM, checks.claimedM));
    }
    var ph = derived.sample ? C.sampleValue(derived.sample, 'ph') : null;
    if (ph !== null) fieldChecks.push(C.handpumpCorrosionCheck(ph));

    var dose = (S.isNum(checks.waterColumn) && S.isNum(checks.casingId))
      ? C.disinfectionDose(checks.waterColumn, checks.casingId) : null;

    var nodes = [
      pageHead('Supervision', 'The stage checklists from the RWSN and UNICEF ' +
        'supervision guidance, plus the numeric acceptance checks a supervisor ' +
        'applies on site.'),
      card('Progress', [
        el('div.callout' + (evaluation.critical_failures ? '.callout-bad'
          : (evaluation.critical_open ? '.callout-warn' : '.callout-ok')),
          el('p', evaluation.verdict)),
        S.statRow([
          S.stat('Answered', evaluation.answered + ' / ' + evaluation.total,
            evaluation.percent.toFixed(0) + '% complete'),
          S.stat('Critical failures', String(evaluation.critical_failures),
            'stop acceptance until resolved'),
          S.stat('Critical still open', String(evaluation.critical_open)),
        ]),
      ]),
    ];

    evaluation.stages.forEach(function (stage) {
      var stageItems = items.filter(function (i) { return i.checklist === stage.stage; });
      nodes.push(card(stage.title + ' — ' + stage.answered + '/' + stage.total, [
        S.table([
          { key: 'section', label: 'Section' },
          { key: 'text', label: 'Requirement' },
          { key: 'critical', label: 'Critical',
            format: function (v) { return v ? S.badge('critical', 'warn') : ''; } },
          { key: 'answer', label: 'Answer' },
          { key: 'remark', label: 'Remark' },
        ], stageItems.map(function (item) {
          var response = responses[item.item_id] || {};
          /* Read the other half of the response back out of the store rather
           * than out of this closure. The remark field does not re-render on
           * every keystroke, so the captured `response` is stale the moment
           * anything has been typed - and writing it back discarded whatever
           * the supervisor had just written. */
          function update(patch) {
            var current = store.get('supervision.responses.' + item.item_id) || {};
            store.set('supervision.responses.' + item.item_id, {
              item_id: item.item_id,
              status: patch.status !== undefined ? patch.status
                : (current.status || 'pending'),
              remark: patch.remark !== undefined ? patch.remark
                : (current.remark || ''),
            });
          }
          return {
            section: item.section, text: item.text, critical: item.critical,
            status: response.status || 'pending',
            answer: S.selectInput(response.status || 'pending',
              [{ value: 'pending', label: '—' }, { value: 'yes', label: 'Yes' },
               { value: 'no', label: 'No' }, { value: 'na', label: 'N/A' }],
              function (value) {
                update({ status: value });
                render();
              }, { class: 'input cell cell-narrow',
                'aria-label': 'Answer: ' + item.text }),
            remark: S.textInput(response.remark || '', function (value) {
              update({ remark: value });
            }, { class: 'input cell', 'aria-label': 'Remark: ' + item.text }),
          };
        }), {
          /* a failed item is the reason the page exists, so it is marked */
          rowClass: function (row) {
            return row.status === 'no' ? 'row-bad' : '';
          },
        }),
      ]));
    });

    nodes.push(card('Field acceptance checks', [
      el('div.grid.grid-3', [
        el('div', [
          el('h4', 'Sand content'),
          field('Sample 1 (cm³)', S.numberInput(checks.sand1, bindCheck('sand1'))),
          field('Sample 2 (cm³)', S.numberInput(checks.sand2, bindCheck('sand2'))),
          field('Sample 3 (cm³)', S.numberInput(checks.sand3, bindCheck('sand3'))),
        ]),
        el('div', [
          el('h4', 'Verticality'),
          field('Deviation (mm)', S.numberInput(checks.deviation, bindCheck('deviation'))),
          field('Depth (m)', S.numberInput(checks.plumbDepth, bindCheck('plumbDepth'))),
          field('Casing inner diameter (mm)',
            S.numberInput(checks.casingId, bindCheck('casingId'))),
        ]),
        el('div', [
          el('h4', 'Screen and pack'),
          field('Design yield (L/s)', S.numberInput(checks.designYield, bindCheck('designYield'))),
          field('Screen open area (m²)', S.numberInput(checks.openArea, bindCheck('openArea'))),
          field('Casing outer diameter (mm)',
            S.numberInput(checks.casingOd, bindCheck('casingOd'))),
        ]),
        el('div', [
          el('h4', 'Filter pack'),
          field('Pack D50 (mm)', S.numberInput(checks.d50pack, bindCheck('d50pack'))),
          field('Aquifer D50 (mm)', S.numberInput(checks.d50aquifer, bindCheck('d50aquifer'))),
        ]),
        el('div', [
          el('h4', 'Drilled metres'),
          field('Logged (m)', S.numberInput(checks.loggedM, bindCheck('loggedM'))),
          field('Invoiced (m)', S.numberInput(checks.claimedM, bindCheck('claimedM'))),
        ]),
        el('div', [
          el('h4', 'Disinfection'),
          field('Water column (m)', S.numberInput(checks.waterColumn, bindCheck('waterColumn'))),
          dose ? el('p.muted', dose.summary) : el('p.muted',
            'Enter the water column and the casing inner diameter for the dose.'),
        ]),
      ]),
      fieldChecks.length ? S.table([
        { key: 'name', label: 'Check' },
        { key: 'measured', label: 'Measured' },
        { key: 'limit', label: 'Acceptance limit' },
        { key: 'status', label: 'Result',
          format: function (v) {
            return S.badge(v, v === 'pass' ? 'ok' : (v === 'fail' ? 'bad' : null));
          } },
        { key: 'message', label: 'Note' },
      ], fieldChecks, {
        rowClass: function (row) {
          return row.status === 'fail' ? 'row-bad' : (row.status === 'pass' ? 'row-ok' : '');
        },
      }) : el('p.muted', 'Enter measurements above to run the acceptance checks.'),
    ]));

    nodes.push(card('Minimum separation distances', [
      S.table([
        { key: 'structure', label: 'Structure' },
        { key: 'min_distance_m', label: 'Minimum distance (m)', align: 'right' },
        { key: 'note', label: 'Note' },
      ], C.loadSeparationDistances()),
    ]));

    nodes.push(card('Site notes and instructions', [
      el('p.muted', 'What was said on site: an instruction to the driller, a ' +
        'deviation agreed, a delay and its reason. Each line is printed in ' +
        'the supervision record under its own heading, which is the only ' +
        'place the written instruction survives the job.'),
      S.editableTable([
        { key: 'note', label: 'Note' },
      ], (store.get('supervision.notes') || []).map(function (note) {
        return { note: note };
      }), function (rows) {
        store.set('supervision.notes', rows
          .map(function (r) { return String(r.note || '').trim(); })
          .filter(Boolean));
      }, { addLabel: '+ Add a note' }),
    ]));

    var required = evidenceCard(items, responses);
    if (required) nodes.push(required);
    nodes.push(photoCard('supervision', 'Supervision photographs'));
    nodes.push(reportCard('Supervision record', 'supervision',
      'The summary, the full checklist record stage by stage, the field ' +
      'acceptance checks and the sign-off block.', { fieldChecks: fieldChecks }));
    nodes.push(nextStep('Finally, hand the borehole over.', 'Handover', 'handover'));
    return nodes;
  };

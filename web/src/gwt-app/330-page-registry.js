
  /* --- the asset registry --------------------------------------------------
   * A drilling project ends; the borehole does not. Everything on this page
   * is about the second twenty years: a stable identifier, an append-only
   * history recorded at the wellhead with no signal, and what that history
   * says is true today. Nothing is assumed working.
   * ---------------------------------------------------------------------- */

  /* The symbol as a PNG data URL, drawn on a canvas rather than through the
   * toolkit's own PNG writer: the browser already has an encoder, and the
   * bytes only have to be a valid image - the modules themselves are what
   * parity holds to the Python side. */
  function qrDataUrl(text, options) {
    var opts = options || {};
    var code = C.qrEncode(text, { ecc: opts.ecc || 'H' });
    var scale = opts.scale || 8, border = opts.border === undefined ? 4 : opts.border;
    var size = (code.size + 2 * border) * scale;
    var canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = '#000000';
    for (var row = 0; row < code.size; row++) {
      for (var col = 0; col < code.size; col++) {
        if (code.modules[row][col]) {
          ctx.fillRect((col + border) * scale, (row + border) * scale, scale, scale);
        }
      }
    }
    return { dataUrl: canvas.toDataURL('image/png'), mime: 'image/png',
      width: size, height: size };
  }

  /* The stored record if there is one, otherwise a draft from the project.
   * A draft carries no events: a borehole is commissioned by somebody
   * deciding it is, on a day, not by opening a page. Either carries the
   * rising main of the project's design as the design now stands, whose
   * interval the routine inspection is due by (PLAN.md step 7.3). */
  function currentAsset() {
    var stored = store.get('asset');
    var record = (stored ? C.assetFromDict(stored) : null) || C.assetFromProject(projectState());
    return record ? C.assetWithRisingMain(record, derived.design ? derived.design.rising_main
      : null) : null;
  }

  function saveAsset(asset) {
    store.set('asset', asset);
    render();
  }

  PAGES.registry = function () {
    var asset = mergeQueuedReports(currentAsset());
    var nodes = [
      pageHead('Asset registry', 'A drilling project ends; the borehole does ' +
        'not. This page holds the other half: a stable identifier that ' +
        'outlives the project file, the maintenance history recorded against ' +
        'it, and what that history says is true today. Nothing here is ' +
        'assumed — a borehole nobody has reported on is not working, it is ' +
        'unknown.'),
    ];

    if (!asset) {
      var placed = store.get('site') || {};
      /* degrees in the two boxes: said in the words the gate uses, rather
       * than that the project has no position */
      var degrees = C.degreesInUtmBoxes(placed.easting, placed.northing);
      nodes.push(card('This borehole', [
        el('div.callout.callout-warn', el('p', degrees
          ? degrees + ' The Site page converts them.'
          : 'This project has no recorded ' +
          'position yet, so it cannot be given an identifier — there would be ' +
          'nothing to find the borehole by. Enter the GPS position on the ' +
          'Site page.')),
        el('div.btn-row', [button('Go to the site page', function () {
          goto('site');
        }, { variant: 'ghost' })]),
      ]));
    } else {
      var state = C.assetState(asset, null, C.serviceSchedule(config()));
      var tone = state.function === 'functional' ? 'ok'
        : (state.function === 'non_functional' ? 'bad' : 'warn');
      nodes.push(itemNode(asset.asset_id, card('This borehole', [
        el('p.asset-id', asset.asset_id),
        el('p.muted', 'The identifier is derived from the position, so two ' +
          'teams at the same wellhead with no connection between them arrive ' +
          'at the same one. The last character is an ISO 7064 MOD 37,36 check ' +
          'character: it catches every single mistyped character and almost ' +
          'every transposition of two adjacent ones.'),
        C.isLegacyAssetId(asset.asset_id)
          ? el('div.callout.callout-warn', el('p', C.validateAssetId(asset.asset_id).reason))
          : null,
        S.statRow([
          S.stat('Status', state.label),
          S.stat('Last sanitary inspection', state.last_inspection || 'never'),
          S.stat('Last routine inspection', state.last_routine_inspection || 'never'),
          S.stat('Last sampled', state.last_sample || 'never'),
          S.stat('Records', String((asset.events || []).length)),
        ]),
        el('div.callout.callout-' + tone, el('p', state.detail)),
        state.days_out_of_service === null || state.days_out_of_service === undefined
          ? null
          : el('p', el('strong', 'Out of service for ' +
            state.days_out_of_service + ' days. Every day counted here is a ' +
            'day the community went back to whatever they used before.')),
        S.checkList(state.due.map(function (item) {
          return {
            level: item.state === 'overdue' ? 'error'
              : (item.state === 'unknown' ? 'warning' : 'info'),
            message: item.detail,
          };
        })),
        /* the routine inspection's interval is the one that differs from
         * borehole to borehole: it follows the design's rising main */
        el('p.muted.rounds-interval', state.due.filter(function (item) {
          return item.key === 'routine_inspection';
        }).map(function (item) {
          return C.phrase('rounds.interval_line', { title: item.title, basis: item.basis });
        }).join(' ')),
        mechanicField(asset),
        pumpField(asset),
        el('div.btn-row', [button('Report on this borehole', function () {
          goto('report', asset.asset_id);
        }, { variant: 'ghost' })]),
      ])));
      if (derived.reportsMerged && derived.reportsMerged.asset_id === asset.asset_id) {
        nodes.push(el('div.callout.callout-ok.reports-merged', el('p',
          derived.reportsMerged.added + ' ' + S.plural(derived.reportsMerged.added, 'report') +
          ' waiting on this phone ' + (derived.reportsMerged.added === 1 ? 'was' : 'were') +
          ' added to this borehole’s history.')));
      }

      var draft = { when: new Date().toISOString().slice(0, 10),
        kind: 'inspection', note: '', by: '', photo: '' };
      nodes.push(card('Record what happened', [
        el('p.muted', 'The history is append-only: a mistake is corrected by ' +
          'recording the correction, so both stay visible. Events are ' +
          'identified by their content, so the same visit written down on two ' +
          'phones merges into one when the project files meet.'),
        el('div.field-row', [
          field('Date', S.textInput(draft.when, function (v) {
            draft.when = String(v).trim();
          }, { placeholder: 'YYYY-MM-DD' }), ''),
          field('What happened', S.selectInput(draft.kind,
            Object.keys(C.EVENT_KINDS).map(function (k) {
              return { value: k, label: C.EVENT_KINDS[k][0] };
            }), function (v) { draft.kind = v; }), ''),
          field('Recorded by', S.textInput('', function (v) {
            draft.by = String(v).trim();
          }, { placeholder: 'Name' }), ''),
        ]),
        field('Note', S.textInput('', function (v) { draft.note = String(v); },
          { placeholder: 'What was found or done' }), ''),
        el('div.btn-row', [
          button('Add to the history', function () {
            if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.when)) {
              S.toast('The date should be written YYYY-MM-DD.', 'warn');
              return;
            }
            var next = Object.assign({}, asset, {
              events: C.mergeEvents(asset.asset_id, asset.events || [], [draft]),
            });
            saveAsset(next);
            S.toast('Recorded.', 'ok');
          }),
        ]),
      ]));

      nodes.push(sanitaryCard(asset));

      if ((asset.events || []).length) {
        nodes.push(card('History', [
          S.table(['Date', 'Event', 'Note', 'Recorded by'],
            asset.events.map(function (e) {
              return [e.when || '(no date)', C.eventLabel(e.kind), e.note || '',
                e.by || ''];
            })),
        ]));
      }

      /* the documents issued about the borehole, which its record keeps
       * (PLAN.md step 8.1) */
      if ((asset.documents || []).length) {
        var readinessWords = C.phraseTable('verification.readiness_words');
        nodes.push(card('Documents issued', [
          el('p.muted', C.phrase('verification.registry_documents')),
          S.table(['Code', 'Document', 'Issued on', 'Readiness'], asset.documents.map(function (r) {
            return [r.code, r.title, r.issued_on, readinessWords[r.readiness]];
          })),
        ]));
      }

      var address = String(config().service.report_url || '');
      var refused = C.checkReportUrl(address);
      nodes.push(card('For the headworks', [
        el('p.muted', 'The plate carries the identifier, the symbol and the ' +
          'facts that do not go out of date.'),
        field('Report address', S.textInput(address, function (v) {
          store.set('config.service.report_url', C.trimField(v));
          render();
        }, { placeholder: 'https://', 'data-report': 'address' }),
        C.phrase('fault_reports.address_help')),
        refused ? el('div.callout.callout-bad.report-address', el('p', refused)) : null,
        el('div.qr-preview', {
          html: C.qrSvg(C.qrEncode(C.qrPayload(asset, refused ? '' : address), { ecc: 'H' }),
            { scale: 3, border: 4 }),
        }),
        el('div.btn-row', [
          button('Identification plate (.docx)', async function (event) {
            await buildAssetDoc('placard', asset, event.target);
          }, { disabled: !!refused }),
          button('Asset record (.docx)', async function (event) {
            await buildAssetDoc('record', asset, event.target);
          }, { variant: 'ghost' }),
        ]),
      ]));
    }

    nodes.push(card('Look up an identifier', [
      el('p.muted', 'Read off a headworks plate. I and L are read as 1, O as ' +
        '0 and U as V, because those are reading mistakes rather than ' +
        'different codes — but a failing check character is refused, since a ' +
        'wrong identifier attaches a repair to somebody else’s borehole.'),
      field('Identifier', S.textInput(store.get('registry.lookup', ''),
        function (v) { store.set('registry.lookup', String(v).trim()); render(); },
        { placeholder: 'SL-WAR-8FEEVKQ-E' }), ''),
      lookupResult(store.get('registry.lookup', '')),
    ]));

    nodes.push(reportsCard(asset));
    nodes.push(registryCard());
    nodes.push(roundsCard(asset));
    nodes.push(survivalCard(asset));
    return nodes;
  };

  /* The pump type and the contractor named on this borehole's record, by
   * which the time to the first failure is grouped (PLAN.md step 7.4).
   * Named here, they travel in the project file. */
  function pumpField(asset) {
    var draft = { pump: asset.pump_type || '', by: asset.installed_by || '' };
    return el('div', [
      el('div.field-row', [
        field('Pump type', S.textInput(draft.pump, function (v) {
          draft.pump = String(v);
        }, { placeholder: 'India Mark II', 'data-survival': 'pump' }),
        'The pump installed, as the handover names it. The curves of how long boreholes ' +
        'keep working are grouped by it.'),
        field('Installed by', S.textInput(draft.by, function (v) {
          draft.by = String(v);
        }, { placeholder: 'Contractor', 'data-survival': 'contractor' }),
        'The contractor who drilled and installed it: the site details’ contractor when ' +
        'the record was drafted, and what is saved here after that.'),
      ]),
      el('div.btn-row', [button('Save the pump and contractor', function () {
        saveAsset(Object.assign({}, asset, { events: asset.events || [],
          pump_type: C.trimField(draft.pump), installed_by: C.trimField(draft.by) }));
        S.toast('Saved on the borehole’s record.', 'ok');
      }, { variant: 'ghost' })]),
    ]);
  }

  /* How long the boreholes keep working (PLAN.md step 7.4): the time from
   * commissioning to the first failure across this borehole and the
   * register, over them all and by pump type, contractor and water
   * chemistry, each as a curve with its band and a table. The day is the
   * page's input, today unless another is written; the engine never reads
   * the clock. */
  function survivalCard(asset) {
    var today = new Date().toISOString().slice(0, 10);
    var when = store.get('survival.date', '') || today;
    var nodes = [
      el('p.muted', C.phrase('survival.intro') + ' The Streamlit app has the same curves ' +
        'on its Asset registry page.'),
      el('div.field-row', [
        field('Analysed as of', S.textInput(when, function (v) {
          store.set('survival.date', String(v).trim());
          render();
        }, { placeholder: 'YYYY-MM-DD', 'data-survival': 'date' }), ''),
      ]),
    ];
    if (C.isoDay(when) === null) {
      nodes.push(el('div.callout.callout-warn', el('p', 'The date should be written ' +
        'YYYY-MM-DD.')));
      return card(C.phrase('survival.heading'), nodes);
    }
    /* this borehole first, so its record, kept in step with the design,
     * is the one read where the register holds the same borehole */
    var assets = (asset ? [asset] : []).concat(registerAssets());
    var result = C.survivalAnalysis(assets, when, config());
    var words = C.survivalText(result);
    nodes.push(el('div.survival-summary', words.summary.map(function (line) {
      return el('p', line);
    })));
    if (!result.n_boreholes) return card(C.phrase('survival.heading'), nodes);
    var sections = [{ by: null, told: words.overall, groups: [result.overall], comparison: [] }]
      .concat(result.groupings.map(function (g, i) {
        return { by: g.by, told: words.groupings[i], groups: g.groups,
          comparison: words.groupings[i].comparison };
      }));
    sections.forEach(function (section) {
      nodes.push(el('h3.survival-group', section.told.heading));
      if (section.by) nodes.push(el('p.muted', section.told.intro));
      if (section.groups.some(function (g) { return g.judged; })) {
        var title = section.by ? C.phrase('survival.figure_by',
          { by: C.phraseTable('survival.by')[section.by] }) : C.phrase('survival.figure_all');
        nodes.push(charts.figure(charts.survivalCurves(section.groups, { title: title }), '',
          { filename: 'survival_' + (section.by || 'all') }));
      }
      section.told.lines.forEach(function (line) { nodes.push(el('p.survival-line', line)); });
      nodes.push(S.table(C.survivalHeader(), C.survivalRows(section.groups)));
      var risk = C.atRiskRows(section.groups);
      if (risk.length) nodes.push(S.table(C.atRiskHeader(result), risk));
      section.comparison.forEach(function (line) {
        nodes.push(el('p.muted.survival-comparison', line));
      });
    });
    nodes.push(el('p.muted', C.phrase('survival.figure_caption')));
    nodes.push(el('p.muted', C.phrase('survival.at_risk_caption')));
    words.method.forEach(function (line) { nodes.push(el('p.muted', line)); });
    nodes.push(el('h3', 'References'));
    nodes.push(el('ul.survival-references', words.references.map(function (ref) {
      return el('li', ref);
    })));
    return card(C.phrase('survival.heading'), nodes);
  }

  /* The area mechanic named on this borehole's record, whose service round
   * it is on (PLAN.md step 7.3). Named here, it travels in the project file;
   * a borehole with none named goes to the mechanic named for its chiefdom
   * on the rounds below. */
  function mechanicField(asset) {
    var draft = { name: asset.area_mechanic || '' };
    return el('div', [
      el('div.field-row', [
        field('Area mechanic', S.textInput(draft.name, function (v) {
          draft.name = String(v);
        }, { placeholder: 'Area mechanic', 'data-rounds': 'mechanic' }),
        asset.area_mechanic ? 'Named on this borehole’s record.'
          : 'None named on the record; the rounds look the chiefdom up.'),
      ]),
      el('div.btn-row', [button('Name the area mechanic', function () {
        var next = Object.assign({}, asset, { events: asset.events || [] });
        var name = C.trimField(draft.name);
        if (name) next.area_mechanic = name; else delete next.area_mechanic;
        saveAsset(next);
        S.toast(name ? 'Area mechanic named.' : 'Area mechanic cleared.', 'ok');
      }, { variant: 'ghost' })]),
    ]);
  }

  /* The service rounds (PLAN.md step 7.3): what is due on a day at this
   * borehole and at every borehole in the register above, grouped by area
   * mechanic and put in order, with the round sheets to print. The day is
   * the page's input, today unless another is written; the engine never
   * reads the clock. */
  function roundsCard(asset) {
    var today = new Date().toISOString().slice(0, 10);
    var when = store.get('rounds.date', '') || today;
    var text = store.get('rounds.mechanics', '');
    var parsed = C.parseAreaMechanics(text);
    var box = /** @type {HTMLTextAreaElement} */ (el('textarea.input', {
      rows: 3, 'data-rounds': 'chiefdoms',
      placeholder: 'One chiefdom a line: the chiefdom, a colon and the mechanic’s name',
    }));
    box.value = text;
    box.addEventListener('change', function () {
      store.set('rounds.mechanics', box.value);
      render();
    });
    var nodes = [
      el('p.muted', 'What is due on the day below, at this borehole and at every ' +
        'borehole in the register above: the sanitary inspection, the routine ' +
        'inspection of the pump and rising main, and the water quality sample. ' +
        'Each borehole goes to the area mechanic named on its record, else to the ' +
        'one named for its chiefdom here. The Streamlit app has the same rounds ' +
        'on its Asset registry page.'),
      el('div.field-row', [
        field('Round drawn up on', S.textInput(when, function (v) {
          store.set('rounds.date', String(v).trim());
          render();
        }, { placeholder: 'YYYY-MM-DD', 'data-rounds': 'date' }), ''),
      ]),
      field('Area mechanics by chiefdom', box, ''),
    ];
    parsed.skipped.forEach(function (line) {
      nodes.push(el('div.callout.callout-warn', el('p', line)));
    });
    if (C.isoDay(when) === null) {
      nodes.push(el('div.callout.callout-warn', el('p', 'The date should be written ' +
        'YYYY-MM-DD.')));
      return card('Service rounds', nodes);
    }
    /* this borehole first, so its record, kept in step with the design,
     * is the one read where the register holds the same borehole */
    var assets = (asset ? [asset] : []).concat(registerAssets());
    /* the round sheet says what a scan of each plate begins with, which
     * follows the report address: one the registry refuses is said here
     * and no sheet is printed until it is put right (PLAN.md step 7.1) */
    var address = String(config().service.report_url || '');
    var refused = C.checkReportUrl(address);
    if (refused) nodes.push(el('div.callout.callout-bad.rounds-address', el('p', refused)));
    var result = C.serviceRounds(assets, when, C.serviceSchedule(config()), parsed.entries,
      refused ? '' : address);
    var words = C.roundsText(result);
    nodes.push(el('div.rounds-summary', words.summary.map(function (line) {
      return el('p', line);
    })));
    result.rounds.forEach(function (one) {
      var lines = C.roundText(one);
      nodes.push(el('h3.round-name', lines[0]));
      lines.slice(1).forEach(function (line) { nodes.push(el('p.muted', line)); });
      nodes.push(S.table(C.roundHeader(), C.roundRows(one)));
    });
    if (result.rounds.length) {
      nodes.push(el('p.muted', words.method));
      nodes.push(el('p.muted', words.intervals));
    }
    nodes.push(el('div.btn-row', [button('Round sheets (.docx)', async function (event) {
      await buildRoundSheet(result, event.target);
    }, { disabled: !result.n_boreholes || !!refused })]));
    return card('Service rounds', nodes);
  }

  async function buildRoundSheet(result, node) {
    var host = node ? node.closest('.card') : $('#page-host');
    var issued = null;
    try {
      await S.withBusy(host, 'Building the round sheets…', async function () {
        await need(REPORT_BUNDLES);
        var builder = await GWT.docx.roundSheet({ style: config().style, rounds: result,
          issue: issueFor('rounds', { files: derived.registryFiles || [] }) });
        var name = 'rounds_' + result.as_of + '.docx';
        var bytes = await builder.build();
        S.download(name, bytes);
        issued = recordIssue(builder.record, name, bytes);
      });
      S.toast('Document ready.' + codeWords(issued), 'ok');
    } catch (err) {
      S.toast('Could not build the document: ' + err.message, 'error');
    }
  }

  /* The WHO form for a borehole with a handpump, and the risk statement that
   * reads the latest inspection with the E. coli count of the water quality
   * sample on show (PLAN.md step 7.5). An inspection is recorded against the
   * borehole like any other visit, so it is saved with the project and
   * merges by content when two phones meet. */
  function sanitaryCard(asset) {
    var today = new Date().toISOString().slice(0, 10);
    var risk = C.sanitaryRisk(asset, today, derived.assessment || null);
    var words = C.phraseTable('sanitary.answer');
    var questions = C.formQuestions();
    var draft = { when: today, by: '', note: '',
      answers: questions.map(function () { return '-'; }) };
    var tone = risk.action === 'urgent' ? 'bad'
      : (risk.action === 'higher' ? 'warn' : 'info');
    var choices = ['-', 'Y', 'N'].map(function (k) { return { value: k, label: words[k] }; });
    return card(C.phrase('sanitary.heading'), [
      risk.action ? S.statRow([S.stat('Action priority',
        C.phraseTable('sanitary.priority_short')[risk.action])]) : null,
      el('div.callout.callout-' + tone, el('p.sanitary-statement', risk.statement)),
      risk.inspection ? el('p.muted', C.phrase('sanitary.form_caption',
        { when: risk.inspection.label })) : null,
      risk.inspection ? S.table([C.phrase('sanitary.col_number'),
        C.phrase('sanitary.col_question'), C.phrase('sanitary.col_answer')],
      C.formRows(risk.inspection.answers, risk.inspection.form)) : null,
      el('p.muted', C.phrase('sanitary.basis')),
      el('h3', 'Record a sanitary inspection'),
      el('p.muted', 'Answer each question as found at the wellhead: yes where ' +
        'the risk is present. A question left unanswered is not counted as a ' +
        'no, so an incomplete form gives a range of scores. The Streamlit app ' +
        'has the same form on its Asset registry page.'),
      el('div.field-row', [
        field('Date of the inspection', S.textInput(draft.when, function (v) {
          draft.when = String(v).trim();
        }, { placeholder: 'YYYY-MM-DD', 'data-sanitary': 'when' }), ''),
        field('Inspected by', S.textInput('', function (v) {
          draft.by = String(v).trim();
        }, { placeholder: 'Inspector' }), ''),
      ]),
    ].concat(questions.map(function (question, i) {
      return field((i + 1) + '. ' + question, S.selectInput('-', choices, function (v) {
        draft.answers[i] = v;
      }, { 'data-sanitary': 'q' + (i + 1) }), '');
    })).concat([
      field('Note', S.textInput('', function (v) { draft.note = String(v); },
        { placeholder: 'Anything else seen' }), ''),
      el('div.btn-row', [
        button('Record the inspection', function () {
          if (C.isoDay(draft.when) === null) {
            S.toast('The date should be written YYYY-MM-DD.', 'warn');
            return;
          }
          var next = Object.assign({}, asset, {
            events: C.mergeEvents(asset.asset_id, asset.events || [],
              [C.inspectionEvent(draft.when, draft.answers.join(''), draft.by,
                draft.note)]),
          });
          saveAsset(next);
          S.toast('Recorded.', 'ok');
        }),
      ]),
    ]));
  }

  function lookupResult(typed) {
    if (!typed) return null;
    var verdict = C.validateAssetId(typed);
    /* one read with the legacy check character is valid, and said */
    return el('div.callout.callout-' + (verdict.ok ? (verdict.legacy ? 'warn' : 'ok') : 'bad'),
      verdict.ok
        ? [el('p', 'That is a valid identifier: ' + verdict.assetId),
          verdict.reason ? el('p', verdict.reason) : null]
        : el('p', verdict.reason));
  }

  function registryCard() {
    var assets = registerAssets();
    var nodes = [
      el('p.muted', 'Drop in saved project files to see the whole register: ' +
        'what is working, what is not, and what is overdue a visit. A file ' +
        'only carries an asset record once its borehole has an identifier.'),
      el('div.btn-row', [
        button('Add project files', async function () {
          var list = await S.pickFile('.json,.gwt,.yaml,.yml', true);
          if (!list || !list.length) return;
          var loaded = (derived.registry || []).slice();
          /* the files, by their hashes, which a round sheet drawn from the
           * register is issued from (PLAN.md step 8.1) */
          var files = (derived.registryFiles || []).slice();
          var skipped = 0;
          for (var i = 0; i < list.length; i++) {
            try {
              var text = await S.readFile(list[i], 'text');
              var record = assetFromProjectFile(list[i].name, text);
              if (record) {
                loaded.push(record);
                files.push(projectFileEvidence(list[i].name, text));
              } else {
                skipped += 1;
              }
            } catch (e) { skipped += 1; }
          }
          derived.registry = loaded;
          derived.registryFiles = files;
          S.toast(loaded.length + ' ' + S.plural(loaded.length, 'borehole') +
            ' in the register' + (skipped ? ', ' + skipped + ' skipped' : '') + '.',
          skipped ? 'warn' : 'ok');
          render();
        }),
        assets.length ? button('Clear', function () {
          derived.registry = [];
          derived.registryFiles = [];
          render();
        }, { variant: 'ghost' }) : null,
      ].filter(Boolean)),
    ];
    if (!assets.length) {
      nodes.push(el('p.muted', 'Nothing loaded yet.'));
      return card('Many boreholes', nodes);
    }
    var stats = C.registryStats(assets, null, C.serviceSchedule(config()));
    nodes.push(S.statRow([
      S.stat('Boreholes', String(stats.n_assets)),
      S.stat('Working', String(stats.n_functional)),
      S.stat('Not working', String(stats.n_non_functional)),
      S.stat('Condition unknown', String(stats.n_unknown)),
    ]));
    if (stats.functionality_rate !== null) {
      nodes.push(el('p', el('strong', 'Functionality rate: ' +
        C.pyFixed(stats.functionality_rate, 0) + '%')));
      nodes.push(el('p.muted', 'Over the boreholes whose condition is ' +
        'actually known. A rate computed over silence is the number that ' +
        'makes these registers untrustworthy.'));
    }
    if (stats.n_unknown) {
      nodes.push(el('div.callout.callout-warn', el('p', stats.n_unknown +
        ' ' + S.plural(stats.n_unknown, 'borehole') +
        (stats.n_unknown === 1 ? ' has' : ' have') +
        ' nothing recorded against ' +
        (stats.n_unknown === 1 ? 'it' : 'them') + ' at all. That is not ' +
        'the same as nothing having happened to ' +
        (stats.n_unknown === 1 ? 'it.' : 'them.'))));
    }
    if (stats.n_overdue_inspection + stats.n_overdue_routine + stats.n_overdue_sample) {
      nodes.push(el('p', stats.n_overdue_inspection + ' overdue a sanitary ' +
        'inspection, ' + stats.n_overdue_routine + ' overdue a routine inspection, ' +
        stats.n_overdue_sample + ' overdue a water quality sample.'));
    }
    var rows = C.registryRows(assets, null, C.serviceSchedule(config()));
    nodes.push(S.table(Object.keys(rows[0]), rows.map(function (row) {
      return Object.keys(row).map(function (key) { return String(row[key]); });
    })));
    return card('Many boreholes', nodes);
  }

  function assetFromProjectFile(name, text) {
    var payload = /\.ya?ml$/i.test(name) ? S.parseYaml(text) : JSON.parse(text);
    if (!payload || typeof payload !== 'object') return null;
    /* the Streamlit file carries it under "asset"; this app's own under
     * state.asset, because that is where its store keeps it */
    var raw = payload.asset ||
      (payload.state && typeof payload.state === 'object' ? payload.state.asset : null);
    return C.assetFromDict(raw || {});
  }

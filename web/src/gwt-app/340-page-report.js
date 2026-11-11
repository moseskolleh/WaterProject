
  /* --- reports from the plate and by SMS (PLAN.md step 7.1) ----------------
   * A plate printed with the report address set carries a link to
   * #/report/<identifier> here. A report made on that page waits in this
   * browser's queue (reports.queue, kept in IndexedDB with the rest of the
   * session and carried across projects, as the calibration in force is)
   * until the Asset registry page is opened on the borehole it names, when
   * it is merged into that borehole's history by the registry's own rule. A
   * mechanic can carry the queue to whoever holds that borehole's project as
   * a small file. SMS messages and such a file are imported on the Asset
   * registry page; a report by SMS that the registry reads only with a note
   * waits in reports.held until a person confirms it.
   * ---------------------------------------------------------------------- */

  /* what the report page holds while it is being filled in */
  var reportDraft = null;

  /* the list kept under path, its entries that are records: a session from a
   * hand-edited or damaged store reads as an empty queue, not as a page
   * that cannot be drawn */
  function reportList(path) {
    var list = store.get(path);
    return Array.isArray(list) ? list.filter(function (r) {
      return r !== null && typeof r === 'object' && !Array.isArray(r);
    }) : [];
  }
  function reportQueue() { return reportList('reports.queue'); }
  function heldReports() { return reportList('reports.held'); }

  /* An identifier to show the shape of one, its check character worked out
   * rather than typed, so it stays right if the calculation is corrected. */
  function exampleAssetId() {
    return 'SL-WAR-8FEEVKQ-' + C.checkCharacter('SL-WAR-8FEEVKQ');
  }

  /* One queued report is told from another by its borehole and the
   * identifier the registry gives its record, so the same report queued
   * twice is kept once, the copy with a photograph if one has it. */
  function reportKey(r) {
    return r.asset_id + '|' + C.eventId(r.asset_id, r.when, r.kind, r.note, r.by);
  }

  function keepReports(path, records) {
    var list = reportList(path);
    /** @type {Object<string, number>} */
    var at = {};
    list.forEach(function (r, i) { at[reportKey(r)] = i; });
    var added = 0;
    records.forEach(function (r) {
      var key = reportKey(r);
      if (!Object.prototype.hasOwnProperty.call(at, key)) {
        at[key] = list.length;
        list.push(r);
        added += 1;
      } else if (!list[at[key]].photo && r.photo) {
        list[at[key]] = r;
      }
    });
    store.set(path, list);
    return added;
  }

  /* The registry page opened on a borehole: the reports waiting for it are
   * merged into its history and leave the queue; the rest stay. */
  function mergeQueuedReports(asset) {
    if (!asset) return asset;
    var queue = reportQueue();
    var mine = queue.filter(function (r) { return r.asset_id === asset.asset_id; });
    if (!mine.length) return asset;
    var merged = C.mergeReports([asset], mine);
    var record = merged.assets[0];
    store.set('asset', record);
    store.set('reports.queue', queue.filter(function (r) { return r.asset_id !== asset.asset_id; }));
    /* a report already in the history leaves the queue and adds nothing */
    if (merged.added) derived.reportsMerged = { asset_id: asset.asset_id, added: merged.added };
    return C.assetWithRisingMain(record, derived.design ? derived.design.rising_main : null);
  }

  /* The register of Many boreholes, with the reports waiting on this phone
   * shown in the histories of the boreholes they name. The project files
   * are not changed: a report reaches a borehole's own record when its
   * project is opened here. */
  function registerAssets() {
    var register = derived.registry || [];
    var queue = reportQueue();
    return queue.length && register.length ? C.mergeReports(register, queue).assets : register;
  }

  function reportTable(records) {
    return S.table(['Borehole', 'Day', 'Says', 'Note', 'By', 'Photograph'],
      records.map(function (r) {
        return [r.asset_id, r.when, C.phraseTable('fault_reports.choices')[r.choice] || '',
          r.note || '', r.by || '', r.photo ? 'yes' : ''];
      }));
  }

  function exportReports() {
    var queue = reportQueue();
    S.download('borehole-reports.json', JSON.stringify(C.reportsFile(queue), null, 1),
      'application/json');
    S.toast(queue.length + ' ' + S.plural(queue.length, 'report') + ' written to ' +
      'borehole-reports.json. They stay on this phone until their boreholes’ records ' +
      'are opened here, or until they are cleared.', 'ok');
  }

  /* The queue emptied by a person, once the file has gone to whoever holds
   * the boreholes' records: asked first, since nothing else keeps them. */
  function clearReports() {
    var n = reportQueue().length;
    var asked = S.modal('Clear the reports waiting?', el('p', n + ' ' + S.plural(n, 'report') +
      ' on this phone will be deleted. Nothing else keeps ' + (n === 1 ? 'it' : 'them') +
      ' until ' + (n === 1 ? 'it reaches its borehole’s' : 'they reach their boreholes’') +
      ' records, so export the file first and see it arrive.'), [
      button('Clear', function () {
        store.set('reports.queue', []);
        /* closed through its own close(), which hands the keyboard back to
         * the page, before the toast a dialog still open could keep from
         * being heard */
        asked.close();
        S.toast('The reports waiting on this phone were cleared.', 'ok');
        render();
      }, { variant: 'danger' }),
    ]);
  }

  PAGES.report = function () {
    var typed = route.item || '';
    var verdict = typed ? C.validateAssetId(typed) : null;
    var nodes = [
      pageHead('Report on a borehole', 'Say whether a borehole is working, broken, ' +
        'slow, or giving water that tastes or looks wrong. The report waits on this ' +
        'phone, with no network needed, until the borehole’s record is opened on the ' +
        'Asset registry page here, or the reports are carried as a file to whoever ' +
        'holds it.'),
      el('p.muted.reports-browser-only', C.phrase('fault_reports.browser_only')),
    ];
    var open = currentAsset();
    /* The card is the item the address names, whatever was typed into it:
     * this page needs no project, so an identifier the project open here
     * does not hold is not "nothing here" (showItem) but a report to make,
     * or a mistyped identifier, which lookupResult says. */
    nodes.push(itemNode(typed, card('The borehole', [
      field('Identifier on the plate', S.textInput(typed, function (v) {
        goto('report', String(v).trim());
      }, { placeholder: exampleAssetId(), 'data-report': 'identifier' }),
      'Quote it in full, the last character included: it is a check character, and ' +
      'it is what stops a report being recorded against another village’s borehole.'),
      lookupResult(typed),
      verdict && verdict.ok && open && open.asset_id === verdict.assetId
        ? el('p.muted', 'This is the borehole of the project open here: ' +
          C.assetLabel(open) + ', on record as ' +
          C.assetState(open, null, C.serviceSchedule(config())).label.toLowerCase() + '.')
        : null,
    ])));
    if (verdict && verdict.ok) nodes.push(reportForm(String(verdict.assetId)));
    var queue = reportQueue();
    nodes.push(card('Reports waiting on this phone', queue.length ? [
      reportTable(queue),
      el('div.btn-row', [
        button('Export the reports (.json)', exportReports),
        button('Open the Asset registry', function () { goto('registry'); },
          { variant: 'ghost' }),
        button('Clear the reports waiting', clearReports, { variant: 'ghost' }),
      ]),
      el('p.muted', 'A report is merged into its borehole’s history when the Asset ' +
        'registry page is opened here on that borehole’s project. For a borehole whose ' +
        'project is elsewhere, export the reports and import the file on the Asset ' +
        'registry page of either app where it is kept.'),
    ] : [el('p.muted', 'None.')]));
    return nodes;
  };

  function reportForm(assetId) {
    if (!reportDraft || reportDraft.asset_id !== assetId) {
      reportDraft = { asset_id: assetId, choice: '', when: new Date().toISOString().slice(0, 10),
        by: '', note: '', photo: null };
    }
    var draft = reportDraft;
    var choices = C.phraseTable('fault_reports.choices');
    return card('What is the matter', [
      el('div.btn-row.report-choices', C.REPORT_CHOICES.map(function (choice) {
        return el('button.btn' + (draft.choice === choice ? '' : '.btn-ghost'), {
          type: 'button', 'data-choice': choice,
          'aria-pressed': draft.choice === choice ? 'true' : 'false',
          onclick: function () { draft.choice = choice; render(); },
        }, choices[choice]);
      })),
      el('div.field-row', [
        field('Day', S.textInput(draft.when, function (v) { draft.when = String(v).trim(); },
          { placeholder: 'YYYY-MM-DD', 'data-report': 'when' }), ''),
        field('Your name', S.textInput(draft.by, function (v) { draft.by = String(v); },
          { placeholder: 'Optional', 'data-report': 'by' }), ''),
      ]),
      field('Note', S.textInput(draft.note, function (v) { draft.note = String(v); },
        { placeholder: 'Optional: what was seen', 'data-report': 'note' }), ''),
      GWT.imageSlot.create({
        key: 'report', label: 'Photograph (optional)', value: draft.photo,
        askPosition: askPhotoPosition,
        onChange: function (v) { draft.photo = v; },
      }),
      photoPositionToggle(),
      el('div.btn-row', [button('Save the report', function () {
        var photo = draft.photo || {};
        var record = C.reportRecord(assetId, draft.choice, draft.when, draft.note, draft.by,
          photo.dataUrl || '', photo.provenance || null);
        if (record.status !== 'accepted') {
          S.toast(record.reason, 'warn', 8000);
          return;
        }
        keepReports('reports.queue', [record]);
        reportDraft = null;
        S.toast('Saved on this phone. ' + reportQueue().length + ' ' +
          S.plural(reportQueue().length, 'report') + ' waiting.', 'ok');
        render();
      })]),
    ]);
  }

  /* The registry page's card for reports: what waits on this phone, the
   * import of SMS messages and of a phone's file of reports, what the last
   * import made of each line, and the reports held for a person to confirm. */
  function reportsCard(asset) {
    var queue = reportQueue(), held = heldReports();
    var elsewhere = queue.filter(function (r) { return !asset || r.asset_id !== asset.asset_id; });
    var registered = {};
    (derived.registry || []).forEach(function (a) { registered[a.asset_id] = true; });
    var shown = elsewhere.filter(function (r) {
      return Object.prototype.hasOwnProperty.call(registered, r.asset_id);
    }).length;
    var nodes = [
      el('p.muted', C.phrase('fault_reports.browser_only')),
      el('p.muted', C.smsFormat()),
      el('div.field-row', [
        field('Day received', S.textInput(
          store.get('reports.receivedOn', ''), function (v) {
            store.set('reports.receivedOn', String(v).trim());
          }, { placeholder: 'YYYY-MM-DD', 'data-report': 'received-on' }),
        C.phrase('fault_reports.received_on_help')),
      ]),
      el('div.btn-row', [
        button('Import SMS messages or a file of reports', importReports),
        queue.length ? button('Export the reports waiting (.json)', exportReports,
          { variant: 'ghost' }) : null,
        queue.length ? button('Clear the reports waiting', clearReports,
          { variant: 'ghost' }) : null,
        button('Report on a borehole', function () {
          goto('report', asset ? asset.asset_id : '');
        }, { variant: 'ghost' }),
      ].filter(Boolean)),
    ];
    if (elsewhere.length) {
      nodes.push(el('p.reports-waiting', elsewhere.length + ' ' +
        S.plural(elsewhere.length, 'report') + ' on this phone ' +
        (elsewhere.length === 1 ? 'names a borehole' : 'name boreholes') +
        ' whose project is not open here' +
        (shown ? '; ' + shown + ' of them ' + (shown === 1 ? 'is' : 'are') +
          ' shown in Many boreholes below, whose files are not changed' : '') +
        '. They wait until the project is opened here, or the file is exported.'));
    }
    var last = derived.reportImport;
    if (last && last.length) {
      nodes.push(el('p.reports-summary', C.importSummary(last)));
      nodes.push(S.table(C.reportHeader(), C.reportRows(last)));
    }
    if (held.length) {
      nodes.push(el('h3', C.phraseTable('fault_reports.outcome').held));
      held.forEach(function (r, i) {
        nodes.push(el('div.callout.callout-warn.report-held', [
          el('p', [el('strong', r.asset_id + ', ' + r.when + ': '),
            C.phraseTable('fault_reports.choices')[r.choice] + (r.note ? ' (' + r.note + ')' : '') +
            ', ' + r.by + '.']),
          el('p', r.reason),
          el('div.btn-row', [
            button(C.phrase('fault_reports.confirm'), function () {
              keepReports('reports.queue', [C.confirmReport(r)]);
              store.set('reports.held', heldReports().filter(function (x, j) { return j !== i; }));
              render();
            }),
            button('Discard', function () {
              store.set('reports.held', heldReports().filter(function (x, j) { return j !== i; }));
              render();
            }, { variant: 'ghost' }),
          ]),
        ]));
      });
    }
    return card(C.phrase('fault_reports.heading'), nodes);
  }

  /* SMS messages (any text file, one a line) or a file of reports (.json):
   * each read, what it accepted queued, what it held kept for a person,
   * and the lot shown, refusals and their reasons included. */
  async function importReports() {
    var list = await S.pickFile('.txt,.csv,.json,text/plain,application/json', true);
    if (!list || !list.length) return;
    var records = [];
    for (var i = 0; i < list.length; i++) {
      var text = String(await S.readFile(list[i], 'text'));
      if (/\.json$/i.test(list[i].name)) {
        try {
          records = records.concat(C.readReportsFile(JSON.parse(text)));
        } catch (e) {
          S.toast(list[i].name + ': ' + C.phrase('fault_reports.file_refused'), 'error', 8000);
        }
      } else {
        records = records.concat(C.readSmsLines(text, store.get('reports.receivedOn', '')));
      }
    }
    keepReports('reports.queue', records.filter(function (r) { return r.status === 'accepted'; }));
    keepReports('reports.held', records.filter(function (r) { return r.status === 'held'; }));
    derived.reportImport = records;
    S.toast(C.importSummary(records), 'ok', 8000);
    render();
  }

  async function buildAssetDoc(kind, asset, node) {
    var host = node ? node.closest('.card') : $('#page-host');
    var issued = null;
    charts.usePrintPalette(true);
    try {
      await S.withBusy(host, 'Building the document…', async function () {
        await need(REPORT_BUNDLES);
        var cfg = config();
        var context = {
          style: cfg.style, asset: asset,
          state: C.assetState(asset, null, C.serviceSchedule(cfg)),
          /* a plate on the headworks makes no claim about the water, so it is
           * not held back for want of a laboratory panel */
          readiness: reportReadiness(kind === 'placard' ? 'placard' : 'asset'),
          /* only the plate carries the symbol, so only the plate is held to
           * the report address it links to (PLAN.md step 7.1) */
          symbol: kind === 'placard'
            ? qrDataUrl(C.qrPayload(asset, cfg.service.report_url), { ecc: 'H', scale: 8 })
            : null,
          reportUrl: cfg.service.report_url,
        };
        if (kind !== 'placard') {
          /* the record is what a district water office reads before sending a
           * repair team, so it says where to send it */
          context.areaNote = await areaNoteFor(asset);
          context.areaMaps = await areaFiguresFor(asset);
          /* the sample whose E. coli count the sanitary risk reads */
          context.assessment = derived.assessment || null;
        }
        context.issue = issueFor(kind === 'placard' ? 'placard' : 'asset');
        var builder = kind === 'placard'
          ? await GWT.docx.assetPlacard(context)
          : await GWT.docx.assetRecordReport(context);
        var bytes = await builder.build();
        var name = (kind === 'placard' ? 'placard_' : 'asset_') + asset.asset_id + '.docx';
        S.download(name, bytes);
        issued = recordIssue(builder.record, name, bytes);
      });
      S.toast('Document ready.' + codeWords(issued), 'ok');
    } catch (err) {
      S.toast('Could not build the document: ' + err.message, 'error');
    } finally {
      charts.usePrintPalette(false);
    }
  }


  /* --- verify a document (PLAN.md step 8.1) --------------------------------
   * Whether the toolkit issued a .docx, whether it has changed since, whether
   * it was certifiable or provisional, and which evidence it was issued from
   * (C.verifyDocument), worked out here with no network. It is checked
   * against the issue records of the project open here and of any project
   * files added, either app's; with none, it says it cannot confirm the
   * document was issued. Nothing on the page is saved with the project. */
  var verifySession = { name: '', bytes: null, files: [], typed: '', bundleName: '',
    bundle: /** @type {Uint8Array|null} */ (null) };

  function verifyRecords() {
    var held = C.issueRecordsOf({ issued: store.get('issued') || [], asset: store.get('asset') });
    verifySession.files.forEach(function (file) { held = held.concat(file.records); });
    var records = C.cleanIssueRecords(held);
    /* none held and no file added: nothing was given to check against */
    return records.length || verifySession.files.length ? records : null;
  }

  function verifyResultCard(report) {
    var questions = C.phraseTable('verification.questions');
    var tone = report.verdict === 'verified' ? 'ok' : (report.verdict === 'unconfirmed' ? 'warn' : 'bad');
    var nodes = [el('div.callout.callout-' + tone, [
      el('p', el('strong', report.lines[0])),
      verifySession.name ? el('p.muted', verifySession.name) : null,
    ])];
    ['issued', 'changed', 'readiness', 'evidence'].forEach(function (key) {
      if (!report.answers[key]) return;
      nodes.push(el('h3', questions[key]));
      nodes.push(el('p', report.answers[key]));
    });
    if (report.facts) {
      nodes.push(el('p.muted', report.lines[report.lines.length - 1]));
      if (report.facts.evidence.length) {
        nodes.push(S.table(['Evidence file', 'What it is', 'SHA-256'],
          report.facts.evidence.map(function (f) { return [f.name, f.what, el('code', f.sha256)]; })));
      }
    }
    if (report.code) {
      nodes.push(S.table(['', ' '], [['Document code', report.code],
        ['Hash of its manifest (SHA-256)', el('code', report.sha256)]]));
    }
    return card('What can be said of it', nodes);
  }

  /* what can be said of an evidence bundle (PLAN.md step 8.3), file by file */
  function bundleResultCard(report) {
    var tone = report.verdict === 'verified' ? 'ok' : (report.verdict === 'unconfirmed' ? 'warn' : 'bad');
    var states = C.phraseTable('bundle.file_states'), confirmed = C.phraseTable('bundle.confirmed_words');
    var nodes = [el('div.callout.callout-' + tone, [
      el('p', el('strong', report.lines[0])),
      verifySession.bundleName ? el('p.muted', verifySession.bundleName) : null,
    ])];
    report.lines.slice(1).forEach(function (line) { nodes.push(el('p', line)); });
    if (report.files.length) {
      nodes.push(S.table(['File', 'What it is', 'State', 'What confirms it', 'Listed by'],
        report.files.map(function (f) {
          return [f.path, f.what, states[f.state], confirmed[f.confirmed], f.listed_by.join('; ')];
        })));
    }
    if (report.sha256) nodes.push(el('p.muted', C.phrase('bundle.hash_line', { sha256: report.sha256 })));
    return card('What can be said of the bundle', nodes);
  }

  PAGES.verify = function () {
    var records = verifyRecords();
    var nodes = [pageHead('Verify a document', C.phrase('verification.page_lead'))];
    nodes.push(card('The document', [
      el('p.muted', C.phrase('verification.document_lead')),
      el('div.btn-row', [
        button('Choose a document (.docx)', async function () {
          var file = await S.pickFile('.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document');
          if (!file) return;
          try {
            verifySession.bytes = new Uint8Array(/** @type {ArrayBuffer} */ (await S.readFile(file)));
            verifySession.name = file.name;
          } catch (e) {
            S.toast('Could not read the file: ' + e.message, 'error');
            return;
          }
          render();
        }),
        verifySession.bytes ? button('Clear', function () {
          verifySession.bytes = null;
          verifySession.name = '';
          render();
        }, { variant: 'ghost' }) : null,
      ]),
    ]));
    if (verifySession.bytes) nodes.push(verifyResultCard(C.verifyDocument(verifySession.bytes, records)));

    nodes.push(card('Verify a bundle', [
      el('p.muted', C.phrase('bundle.verify_lead')),
      el('div.btn-row', [
        button('Choose a bundle (.zip)', async function () {
          var file = await S.pickFile('.zip,application/zip');
          if (!file) return;
          try {
            verifySession.bundle = new Uint8Array(/** @type {ArrayBuffer} */ (await S.readFile(file)));
            verifySession.bundleName = file.name;
          } catch (e) {
            S.toast('Could not read the file: ' + e.message, 'error');
            return;
          }
          render();
        }),
        verifySession.bundle ? button('Clear', function () {
          verifySession.bundle = null;
          verifySession.bundleName = '';
          render();
        }, { variant: 'ghost' }) : null,
      ]),
    ]));
    if (verifySession.bundle) nodes.push(bundleResultCard(C.verifyEvidenceBundle(verifySession.bundle, records)));

    var issued = C.cleanIssueRecords(store.get('issued') || []);
    var readinessWords = C.phraseTable('verification.readiness_words');
    nodes.push(card('Issue records', [
      el('p', records ? C.phrase('verification.page_records', { n: records.length })
        : C.phrase('verification.page_no_records')),
      el('div.btn-row', [
        button('Add project files', async function () {
          var list = await S.pickFile('.json,.gwt,.yaml,.yml', true);
          if (!list || !list.length) return;
          var skipped = 0;
          for (var i = 0; i < list.length; i++) {
            try {
              var text = await S.readFile(list[i], 'text');
              var payload = /\.ya?ml$/i.test(list[i].name) ? S.parseYaml(text) : JSON.parse(text);
              if (!payload || typeof payload !== 'object') throw new Error('not a project file');
              verifySession.files.push({ name: list[i].name, records: C.issueRecordsOf(payload) });
            } catch (e) { skipped += 1; }
          }
          if (skipped) S.toast(skipped + ' ' + S.plural(skipped, 'file') + ' could not be read.', 'warn');
          render();
        }),
        verifySession.files.length ? button('Clear the files', function () {
          verifySession.files = [];
          render();
        }, { variant: 'ghost' }) : null,
      ]),
      verifySession.files.length ? S.table(['Project file', 'Issue records'],
        verifySession.files.map(function (f) { return [f.name, String(f.records.length)]; })) : null,
      el('h3', 'Issued from this project'),
      S.table(['Code', 'Document', 'Issued on', 'Readiness', 'SHA-256'], issued.map(function (r) {
        return [r.code, r.title, r.issued_on, readinessWords[r.readiness], el('code', r.sha256.slice(0, 16) + '…')];
      }), { emptyText: C.phrase('verification.none_issued') }),
    ]));

    var lookup = verifySession.typed ? C.lookupCode(verifySession.typed, records || []) : null;
    nodes.push(card('Look up a code', [
      el('p.muted', C.phrase('verification.lookup_lead')),
      field('Document code', S.textInput(verifySession.typed, function (v) {
        verifySession.typed = String(v).trim();
        render();
      }, { placeholder: '0A1B-2C3D-5' }), ''),
      lookup ? el('div.callout.callout-' + (lookup.records.length ? 'ok' : 'warn'),
        lookup.lines.map(function (line) { return el('p', line); })) : null,
    ]));
    return nodes;
  };

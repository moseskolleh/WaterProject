
  /* --- the evidence bundle (PLAN.md step 8.3) ------------------------------
   * One archive for the borehole (C.buildEvidenceBundle): the sheets the
   * project holds, as they were uploaded; the documents built in this
   * session, the latest of each, and any issued earlier that are added
   * here; the figures each document embeds; the issue records; and a
   * manifest.json of every file's SHA-256, with a README saying how to check
   * it. Made on this device's day, with the calibration set in force. The
   * Streamlit Handover page has the same section. */
  var bundleSession = { added: /** @type {Array<{name: string, bytes: Uint8Array}>} */ ([]) };

  function projectRecords() {
    return C.issueRecordsOf({ issued: store.get('issued') || [], asset: store.get('asset') });
  }

  /* the documents built in this session that a borehole's bundle carries:
   * those whose issue record the project holds (so a document built before
   * another project was opened stays out), not the calibration report or
   * the round sheets, which are about many boreholes
   * (shared.session_documents is the twin) */
  function bundleDocuments() {
    var held = Object.create(null);
    projectRecords().forEach(function (r) { held[r.sha256] = true; });
    return Object.keys(issuedThisSession).sort().map(function (name) { return issuedThisSession[name]; })
      .filter(function (doc) { return C.PROGRAMME_KINDS.indexOf(doc.kind) < 0 && held[doc.sha256] === true; });
  }

  function evidenceBundle() {
    var kinds = C.phraseTable('verification.evidence_kinds');
    var sources = store.get('sources') || {};
    /** @type {Array<*>} */
    var files = [];
    SOURCE_ROLES.forEach(function (role) {
      var source = sources[role];
      if (source && source.b64) {
        files.push({ folder: 'raw', name: source.name || role, data: S.base64ToBytes(source.b64), what: kinds[role] });
      }
    });
    /** @type {Array<{name: string, bytes: Uint8Array}>} */
    var documents = [];
    documents = documents.concat(bundleDocuments(), bundleSession.added);
    documents.forEach(function (doc) {
      files.push({ folder: 'reports', name: doc.name, data: doc.bytes });
      files = files.concat(C.documentFigures(doc.name, doc.bytes));
    });
    var site = store.get('site') || {};
    var stored = store.get('asset');
    var asset = stored ? C.assetFromDict(stored) : null;
    return C.buildEvidenceBundle(site.community || site.project || '', files, {
      borehole: asset ? asset.asset_id : '', madeOn: issueToday(),
      calibration: C.calibrationFacts(config().calibration || null), records: projectRecords() });
  }

  function bundleCard() {
    var held = bundleDocuments();
    var rows = held.map(function (doc) { return [doc.name, 'built in this session']; })
      .concat(bundleSession.added.map(function (doc) { return [doc.name, 'added here']; }));
    return card('Evidence bundle', [
      el('p.muted', C.phrase('bundle.page_lead')),
      el('p.muted', held.length ? C.phrase('bundle.page_documents') : C.phrase('bundle.page_no_documents')),
      rows.length ? S.table(['Document', 'From'], rows) : null,
      el('div.btn-row', [
        button('Add documents issued earlier (.docx)', async function () {
          var list = await S.pickFile('.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            true);
          if (!list || !list.length) return;
          for (var i = 0; i < list.length; i++) {
            try {
              bundleSession.added.push({ name: list[i].name,
                bytes: new Uint8Array(/** @type {ArrayBuffer} */ (await S.readFile(list[i]))) });
            } catch (e) {
              S.toast('Could not read ' + list[i].name + ': ' + e.message, 'error');
            }
          }
          render();
        }, { variant: 'ghost' }),
        bundleSession.added.length ? button('Clear the added documents', function () {
          bundleSession.added = [];
          render();
        }, { variant: 'ghost' }) : null,
        button('Download evidence bundle', function () {
          var built;
          try {
            built = evidenceBundle();
          } catch (e) {
            S.toast(String(e && e.message || e), 'error');
            return;
          }
          var name = 'Evidence_Bundle_' + S.slug(siteLabel()) + '.zip';
          S.download(name, new Blob([built.bytes], { type: 'application/zip' }));
          S.toast('Saved ' + name + '. ' + C.phrase('bundle.built', { files: built.facts.files.length,
            documents: built.facts.documents.length, sha256: built.sha256 }), 'ok');
        }),
      ]),
    ]);
  }

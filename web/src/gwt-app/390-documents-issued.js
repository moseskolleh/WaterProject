
  /* --- documents issued (PLAN.md step 8.1) ---------------------------------
   * Every document this app writes is sealed (gwt-docx.js). It is issued on
   * this device's day, as an input: the engine never reads the clock. A
   * document about the borehole is issued from every file the project holds
   * and the photographs it embeds, each listed by its SHA-256; the others
   * from the files they are drawn from (the project files pooled or in the
   * register), or from none. Its issue record goes into the project, which
   * saves it at the top of the project file, and, for a document about the
   * borehole, into its asset record where one is stored; a record stored
   * later starts from the project's, as the draft carries them. */
  function issueToday() {
    return localDate();
  }

  /* a photograph by the SHA-256 of the file as it arrived, which its
   * provenance record holds; one attached before records existed, by the
   * bytes the project keeps */
  function photoEvidence(photo) {
    var what = C.phraseTable('verification.evidence_kinds').photo;
    var name = photo.name || photo.caption || photo.label || '';
    var held = photo.provenance && photo.provenance.sha256;
    if (typeof held === 'string' && /^[0-9a-f]{64}$/.test(held)) {
      return { what: what, name: name, sha256: held };
    }
    return C.evidenceEntry(what, name, S.base64ToBytes(photo.dataUrl));
  }

  /* a project file pooled on the Portfolio page or read into the register */
  function projectFileEvidence(name, text) {
    return C.evidenceEntry(C.phraseTable('verification.evidence_kinds').project, name,
      new TextEncoder().encode(text));
  }

  /* What a document of this kind is issued on and from: options.photos are
   * the photographs it embeds, options.files more evidence entries. */
  function issueFor(kind, options) {
    var opts = options || {};
    var kinds = C.phraseTable('verification.evidence_kinds');
    var evidence = [];
    if (C.BOREHOLE_KINDS.indexOf(kind) >= 0) {
      var sources = store.get('sources') || {};
      SOURCE_ROLES.forEach(function (role) {
        var source = sources[role];
        if (source && source.b64) {
          evidence.push(C.evidenceEntry(kinds[role], source.name || role, S.base64ToBytes(source.b64)));
        }
      });
    }
    (opts.photos || []).forEach(function (photo) {
      if (photo && photo.dataUrl) evidence.push(photoEvidence(photo));
    });
    return { issued_on: issueToday(), evidence: evidence.concat(opts.files || []),
      calibration: config().calibration || null };
  }

  /* the photographs a report of this kind embeds, as buildReport embeds
   * them: on the supervision record, those attached to the checklist's
   * items, then the page's photo plate */
  function reportPhotos(kind) {
    /** @type {Array<*>} */
    var photos = [];
    if (kind === 'supervision') {
      var evidence = store.get('supervision.evidence') || {};
      C.loadChecklists().forEach(function (item) {
        var photo = evidence[item.item_id];
        if (photo && photo.dataUrl) photos.push(photo);
      });
    }
    return photos.concat(GWT.imageSlot ? GWT.imageSlot.collect(store.get('photos.' + kind), kind) : []);
  }

  /* what a toast says of a document built: its code */
  function codeWords(record) {
    return record ? ' ' + C.phrase('verification.cover_code', { code: record.code }) + '.' : '';
  }

  function savedWords(filename, record) {
    return 'Saved ' + filename + '.' + codeWords(record);
  }

  /* The documents built in this session, the latest under each file name,
   * for the evidence bundle (PLAN.md step 8.3). Held in memory only: a
   * project file does not carry them, so after a reload the documents
   * issued earlier are added on the Handover page. */
  /** @type {Object<string, {name: string, bytes: Uint8Array, kind: string, sha256: string}>} */
  var issuedThisSession = Object.create(null);

  /* the issue record of a document just built, kept, with the document
   * itself for this session's bundle; returns the record */
  function recordIssue(record, name, bytes) {
    if (!record) return null;
    if (name && bytes) {
      issuedThisSession[name] = { name: name, bytes: new Uint8Array(bytes), kind: record.kind,
        sha256: record.sha256 };
    }
    store.set('issued', C.cleanIssueRecords((store.get('issued') || []).concat([record])));
    var stored = store.get('asset');
    var asset = stored && C.BOREHOLE_KINDS.indexOf(record.kind) >= 0 ? C.assetFromDict(stored) : null;
    if (asset) {
      asset.documents = C.cleanIssueRecords((asset.documents || []).concat([record]));
      store.set('asset', asset);
    }
    return record;
  }

  function reportReadiness(kind) {
    var state = projectState();
    /* What the report's decision numbers are read from (PLAN.md step 3.6),
     * worked out only for the report that prints them: the odds read the
     * map layers, and the cost distribution is sampled. The pumping numbers
     * come with the analysis already in the state. */
    if (kind === 'geophysical' && (derived.interpretations || []).length) {
      state.interpretations = derived.interpretations;
      state.model_ranges = (derived.inversions || []).map(rangeFor);
      state.odds = surveyOdds();
      /* at both points where the report offers two it cannot separate; an
       * order the analyst set names one, as the report does */
      state.points = (store.get('ves.preferredOrder') || []).length ? null
        : C.recommendedPoints(derived.interpretations, config());
    }
    if (kind === 'costing') {
      var costed = costSpreads();
      state.cost_distribution = costed ? costed.single : null;
    }
    return C.assessReadiness(state, kind,
      (store.get('overrides') || {})[kind] || {});
  }

  /* Deliberately never disables the button. An analyst who needs an interim
   * document will produce one either way; what matters is that the document
   * says what it rests on. */
  function readinessPanel(kind) {
    var readiness = reportReadiness(kind);
    if (readiness.state === 'ready') {
      return el('div.callout.callout-ok', el('p', readiness.summary));
    }
    var tone = readiness.state === 'ready_with_overrides' ? 'warn' : 'bad';
    var items = readiness.unmet.map(function (req) {
      return { level: 'error', message: req.title + ' — ' + req.detail };
    }).concat(readiness.overridden.map(function (req) {
      var who = req.override_by ? ' (' + req.override_by + ')' : '';
      return { level: 'warning', message: req.title + ' — overridden' + who +
        ': ' + (req.override_reason || 'no reason recorded') };
    }));
    var nodes = [
      el('div.callout.callout-' + tone, el('p', readiness.summary)),
      S.checkList(items),
    ];
    if (readiness.unmet.length) {
      nodes.push(el('p.muted', 'The report will still be produced, stamped ' +
        'PROVISIONAL and listing these items. To issue it as an interim ' +
        'document instead, record who is issuing it and why.'));
      var by = '', why = '';
      nodes.push(field('Issued by',
        S.textInput('', function (v) { by = String(v).trim(); },
          { placeholder: 'Name' }), ''));
      nodes.push(field('Reason',
        S.textInput('', function (v) { why = String(v).trim(); },
          { placeholder: 'Why this is being issued now' }), ''));
      nodes.push(el('div.btn-row', [
        button('Record override', function () {
          /* A named issuer is the whole point of an override: it is somebody's
           * authority standing in for the missing evidence, and an unsigned
           * one is nobody's. */
          if (!by || !why) {
            S.toast('An override needs who is issuing the report and why.',
              'warn');
            return;
          }
          var all = Object.assign({}, store.get('overrides') || {});
          var forKind = {};
          readiness.unmet.forEach(function (req) {
            forKind[req.key] = { reason: why, by: by };
          });
          all[kind] = forKind;
          store.set('overrides', all);
          render();
        }, { variant: 'ghost' }),
      ]));
    }
    if (readiness.overridden.length) {
      nodes.push(el('div.btn-row', [
        button('Clear overrides', function () {
          var all = Object.assign({}, store.get('overrides') || {});
          delete all[kind];
          store.set('overrides', all);
          render();
        }, { variant: 'ghost' }),
      ]));
    }
    if (readiness.assumptions.length) {
      nodes.push(el('p.muted', 'Assumptions carried into this report: ' +
        readiness.assumptions.join('; ')));
    }
    return el('div', nodes.filter(Boolean));
  }

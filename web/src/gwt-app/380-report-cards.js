
  /* ------------------------------------------------------------ report cards */

  function photoCard(setName, title) {
    var values = store.get('photos.' + setName) || {};
    return card(title, [
      GWT.imageSlot.gallery(setName, values, function (next) {
        store.set('photos.' + setName, next);
      }, { askPosition: askPhotoPosition }),
      photoPositionToggle(),
    ], { note: 'Photos stay on this machine and travel inside the project file.' });
  }

  function askPhotoPosition() { return !!store.get('photoPosition'); }

  /* A photograph's position comes from its own EXIF where it has one. Some
   * phones' browsers strip that before a page sees the file, so this device
   * can be asked instead, and the record says which it was. Off until it is
   * ticked: the browser asks for permission the first time. */
  function photoPositionToggle() {
    return el('div', [
      S.checkboxInput(store.get('photoPosition'),
        'Ask this device for its position when a photograph carries none',
        function (v) { store.set('photoPosition', !!v); }),
      el('p.muted', 'Each photograph keeps its capture time, its position and ' +
        'the SHA-256 of the file as attached, with where each came from.'),
    ]);
  }

  /* One photo slot for each checklist item that needs a photograph (the
   * CSV's photo column), bound to supervision.evidence. */
  function evidenceCard(items, responses) {
    var wanted = items.filter(function (item) { return item.photo_required; });
    if (!wanted.length) return null;
    var evidence = store.get('supervision.evidence') || {};
    return card('Photographs the checklist requires', [
      el('p.muted', 'The supervision record is held back until each of these ' +
        'items has a photograph, or is answered N/A. Only presence is ' +
        'checked: whether the photograph shows the work done well is for ' +
        'the supervisor to judge.'),
      el('div.img-grid', wanted.map(function (item) {
        var na = (responses[item.item_id] || {}).status === 'na';
        return GWT.imageSlot.create({
          key: item.item_id,
          label: C.stageTitle(item.checklist) + ': ' + item.section +
            (na ? ' (answered N/A)' : ''),
          hint: item.text,
          value: evidence[item.item_id] || null,
          askPosition: askPhotoPosition,
          onChange: function (v) {
            var had = !!(store.get('supervision.evidence') || {})[item.item_id];
            if (v) store.set('supervision.evidence.' + item.item_id, v);
            else store.remove('supervision.evidence.' + item.item_id);
            /* a photograph arriving or going moves the gate on this page; a
             * caption being typed does not, and redrawing would lose focus */
            if (had !== !!v) render();
          },
        });
      })),
      photoPositionToggle(),
    ], { note: 'Photos stay on this machine and travel inside the project file.' });
  }

  /* Which Depth Spine decisions belong in which report.
   *
   * The sign-off card tells the analyst what accepting writes to; this is the
   * other half of that promise. A design decision certifies the yield and the
   * construction, so it belongs in the completion and pumping-test reports; a
   * quality decision certifies the verdict the handover carries; a costing
   * decision certifies the price. */
  var SIGN_OFF_REPORTS = {
    completion: [['design', 'Design and safe yield']],
    pumping: [['design', 'Design and safe yield']],
    quality: [['quality', 'Water quality verdict']],
    handover: [['design', 'Design and safe yield'],
      ['quality', 'Water quality verdict']],
    costing: [['costing', 'Price to client']],
  };

  function signOffFor(kind) {
    var ledger = spineLedger();
    return (SIGN_OFF_REPORTS[kind] || []).map(function (pair) {
      var record = ledger[pair[0]];
      return record ? Object.assign({ label: pair[1] }, record) : null;
    }).filter(Boolean);
  }

  /* Build and download a report, rasterising the on-screen figures so the
   * document carries exactly the figures the page shows. */
  /* The session, keyed as the readiness model expects it. */
  function projectState() {
    return {
      site: store.get('site'),
      /* the files this project was built from, so the gate can tell a report
       * drawn from the bundled examples from one drawn from this site's work */
      sources: store.get('sources') || {},
      drilling_log: derived.log,
      pump_analysis: derived.analysis,
      wq_assessment: derived.assessment,
      borehole_design: derived.design,
      cost_estimate: derived.estimate,
      /* the answers and the photographs, for the photo evidence the
       * supervision record needs */
      supervision: {
        responses: store.get('supervision.responses') || {},
        evidence: store.get('supervision.evidence') || {},
      },
      /* the documents issued from the project, which the draft asset record
       * carries (PLAN.md step 8.1) */
      issued: store.get('issued') || [],
    };
  }

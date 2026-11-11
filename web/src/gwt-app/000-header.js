/* gwt-app.js - the workspace: navigation, state and every page.
 *
 * One project lives in the store at a time, and the pages follow the lifecycle
 * of a real borehole: site the well, design it, drill it, test it, sample it,
 * cost it, supervise it, hand it over. Each page ends with a route to the next
 * step so a field team is never left wondering what to do with a result.
 *
 * Nothing leaves the browser. Uploaded sheets are parsed in the page, results
 * are held in memory and mirrored to IndexedDB (gwt-store.js), and the project
 * file the user downloads is the copy that is theirs to keep and share.
 */
(function (global) {
  'use strict';

  /** @type {GWTNamespace} */
  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support, C = GWT.core, charts = GWT.charts, docx = GWT.docx;
  var engine = GWT.engine;

  /* The scripts the first screen does without, fetched by GWT.load (in
   * gwt-data.js) the first time a page or a report needs them, relative to
   * this file. The Overview a phone opens on draws no figure and builds no
   * document, and on a slow link these were seconds of download and parsing
   * between the user and a page that answers. web/build_offline.py
   * precaches every file a GWT.bundles assignment names. */
  GWT.bundles = Object.assign(GWT.bundles || {}, {
    charts: 'gwt-charts.js', geolibre: 'gwt-geolibre.js',
    imageSlot: 'image-slot.js', docx: 'gwt-docx.js',
    pumpCopilot: 'gwt-pump-copilot.js',
    vesCopilot: 'gwt-ves-copilot.js',
    drillCopilot: 'gwt-drill-copilot.js',
  });

  /* What a working page draws with: the map layers, the figures, the map
   * export and the photo slots. A report adds the document writer. */
  var VIEW_BUNDLES = ['geo', 'charts', 'geolibre', 'imageSlot'];
  var REPORT_BUNDLES = VIEW_BUNDLES.concat(['docx']);

  function hasBundles(names) {
    return names.every(function (name) { return GWT.hasBundle(name); });
  }

  /* A promise that every named bundle has run, with the modules they define
   * bound to the names this file uses for them. */
  function need(names) {
    return Promise.all(names.map(function (name) { return GWT.load(name); }))
      .then(bindModules);
  }

  /* Whoever loaded them, the modules are read from GWT, where each bundle
   * puts its own. */
  function bindModules() {
    charts = GWT.charts;
    docx = GWT.docx;
  }
  var el = S.el, $ = S.$, card = S.card, button = S.button, field = S.field;

  /* where an earlier build mirrored the whole session, as one string; read
   * once by gwt-store.js, moved across and removed */
  var STORE_KEY = 'gwt.project.v1';

  /** @type {Array<[string, string[][]]>} */
  var NAV_GROUPS = [
    ['Project', [
      ['overview', 'Overview'],
      ['guided', 'Guided start'],
      ['site', 'Site & maps'],
      ['verify', 'Verify a document'],
    ]],
    ['Investigation', [
      ['ves', 'Geophysics (VES)'],
      ['vescopilot', 'VES co-pilot'],
      ['design', 'Borehole design'],
      ['drillcopilot', 'Drilling co-pilot'],
      ['spine', 'Depth Spine'],
      ['extract', 'Scanned sheets'],
    ]],
    ['Testing', [
      ['pumping', 'Pumping test'],
      ['pumpcopilot', 'Pumping co-pilot'],
      ['quality', 'Water quality'],
    ]],
    ['Delivery', [
      ['costing', 'Costing & BoQ'],
      ['procurement', 'Procurement'],
      ['supervision', 'Supervision'],
      ['handover', 'Handover'],
      ['templates', 'Templates'],
    ]],
    ['Area analysis', [
      ['waterpoints', 'Water points'],
      ['coverage', 'Coverage gap'],
      ['portfolio', 'Portfolio'],
      ['registry', 'Asset registry'],
      ['report', 'Report on a borehole'],
    ]],
    ['', [
      ['settings', 'Settings'],
      ['about', 'About & method'],
    ]],
  ];

  function blankState() {
    return {
      nav: 'overview',
      site: {
        client: '', project: '', community: '', chiefdom: '', district: '',
        project_ref: '', easting: null, northing: null, elevation_m: null,
        date: '', supervisor: '', contractor: '', country: 'Sierra Leone',
      },
      config: {},
      /* the calibration set in force in this browser (PLAN.md step 5.3),
       * null for the provisional default: see keepBrowserState */
      calibration: null,
      /* reports from plates and by SMS waiting on this phone, and those held
       * for a person to confirm (PLAN.md step 7.1): see keepBrowserState */
      reports: { queue: [], held: [] },
      sources: {},
      ves: { preferredOrder: [] },
      pumping: { manualDischarges: {} },
      design: { screens: null, totalDepth: null, pumpIntake: null },
      costing: {
        mobilisation_km: 0, wq_samples: 1, handpumps: 1,
        overheads: 15, margin: 20, contingency: 10, vat: 0,
        exchange: 23, programme_n: 1, success_rate: 100, inter_site_km: 15,
        rateOverrides: {},
      },
      /* evidence: the photograph each checklist item that needs one has,
       * keyed by item id, as a photo slot keeps it */
      supervision: { responses: {}, notes: [], checks: {}, evidence: {} },
      handover: { committee: [], notes: [], date: '', pumpType: '', tariffNote: '' },
      photos: {},
      /* ask this device for its position when a photograph carries none */
      photoPosition: false,
      coverage: { level: 'district' },
      waterpoints: { radius: 1000 },
      spine: { stage: 'design', ledger: {}, signatory: '' },
      extraction: { model: '' },
      /* per report kind: { requirementKey: {reason, by} } */
      overrides: {},
      asset: null,
      seasonal: {},
      /* due: the contract's completion date, for the contractor scorecards */
      procurement: { contract: null, measured: {}, variations: [],
        number: 1, date: '', previous: 0, due: '' },
      theme: 'dark',
      /* the soundings' inversions, keyed by what they were computed from
       * (C.inversionCacheKey), so reopening a survey does not invert it
       * again. A cache the app may use and may throw away, never a result:
       * see runInversions. */
      inversionCache: {},
      /* the survey's predictions beside what the borehole found (PLAN.md
       * step 5.1): C.cleanLedger's shape. The project file carries it at its
       * top level, as the Python app's file does, so either app's portfolio
       * can pool it. */
      ledger: { drilled: null, entries: [], project_id: null },
      /* the issue record of every document issued from the project (PLAN.md
       * step 8.1), C.cleanIssueRecords's shape, likewise at the top of the
       * project file */
      issued: [],
    };
  }

  /* Autosave is a mirror of the session into the browser's storage, and it is
   * the only thing standing between a browser refresh and a lost day of
   * fieldwork. It fails silently by design - quota is finite and photos are
   * large - so the failure has to be said out loud, and it has to keep being
   * said until the user has a project file on disk. */
  function renderAutosaveBanner(broken, kept, elsewhere) {
    var host = document.getElementById('autosave-banner');
    if (!host) return;
    S.clear(host);
    if (!broken) return;
    /* A second tab on the same browser would otherwise save over the first
     * record by record, and the copy on disk would be a session neither of
     * them had. Only one tab saves (gwt-store.js), and this is what the
     * other one says. */
    if (elsewhere) {
      S.append(host, el('div.callout.callout-bad', [
        el('p', el('strong', 'Another tab is saving this project')),
        el('p', 'The toolkit is open in another tab or window of this ' +
          'browser, and that one is keeping the saved copy. Nothing entered ' +
          'in this tab is saved: refreshing or closing it loses that. Carry ' +
          'on in the other tab, or continue here - this tab then opens the ' +
          'copy the other one saved, and the other stops saving.'),
        el('div.btn-row', [
          button('Continue here', continueHere),
          button('Save project', saveProject, { variant: 'ghost' }),
        ]),
      ]));
      return;
    }
    /* Two failures wear the same red banner and call for different urgency:
     * losing the last few minutes, or losing the whole day. Saying the first
     * when it is the second promises a backup that is not there, on exactly
     * the browsers - a private window, a tablet whose storage was full before
     * the app opened - where the user most needs to be told to save a file. */
    S.append(host, el('div.callout.callout-bad', [
      el('p', el('strong', kept ? 'Autosave has stopped'
        : 'Nothing is being autosaved')),
      el('p', kept
        ? 'This browser will not take a new copy of the session — usually ' +
          'because its storage is full, often from photographs. The copy it ' +
          'already had is still there, but it stops here: anything entered ' +
          'from now on is in this tab only, and refreshing or closing it ' +
          'loses that. Save a project file now.'
        : 'This browser has not managed to store the session even once — its ' +
          'storage is full, or switched off, as it is in a private window. ' +
          'There is no copy to go back to: everything entered so far is in ' +
          'this tab only, and refreshing or closing it loses all of it. Save ' +
          'a project file now, before anything else.'),
      button('Save project', saveProject),
    ]));
  }

  /* The inversion cache is the one part of the session that can always be
   * worked out again, so the storage keeps it apart and lets it be refused
   * for want of room without that stopping the rest being kept; a refresh
   * then inverts the survey once more. */
  var storage = GWT.storage.create({
    /* another tab took the saving over: the next write is refused, and the
     * banner says so; this makes it say so now */
    onLost: function () { store.persist(); },
  });

  var store = S.createStore(blankState(), {
    storage: storage,
    onPersistError: function (e, kept) {
      var elsewhere = !!e && e.name === 'OpenElsewhereError';
      renderAutosaveBanner(true, kept, elsewhere);
      S.toast(elsewhere ? 'Another tab is saving this project; this one is not.'
        : kept ? 'Autosave has stopped — save a project file now.'
          : 'Nothing has been autosaved — save a project file now.',
        'error', 12000);
    },
    onPersistRecovered: function () {
      renderAutosaveBanner(false);
      S.toast('Autosave is working again.', 'ok');
    },
  });

  /* The API key is deliberately NOT part of the persisted state.
   *
   * It used to be, and the store mirrored the whole state into localStorage
   * on every change - so the key sat unencrypted on disk, survived closing the
   * tab, closing the browser and handing the laptop to the next person, and
   * was readable by anything with script access to this origin. It now lives
   * here, in memory for this tab, and reaches storage only if the user asks
   * for it and then only sessionStorage, which the browser drops when the tab
   * closes. That removes durability at rest and cross-restart exposure; it is
   * not, and is not claimed to be, a defence against script running in this
   * page. */
  var CREDENTIAL_KEY = 'gwt.credential.v1';
  var credential = { key: '', remember: false };

  function getApiKey() {
    return credential.key;
  }

  function setApiKey(value, remember) {
    credential.key = String(value || '').trim();
    credential.remember = !!remember;
    try {
      if (credential.remember && credential.key) {
        sessionStorage.setItem(CREDENTIAL_KEY, credential.key);
      } else {
        sessionStorage.removeItem(CREDENTIAL_KEY);
      }
    } catch (e) { /* private modes throw; the key simply stays in memory */ }
  }

  function forgetApiKey() {
    credential = { key: '', remember: false };
    try { sessionStorage.removeItem(CREDENTIAL_KEY); } catch (e) { /* ignore */ }
    /* sweep any copy left in long-term storage by an earlier build */
    try {
      var raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        var saved = JSON.parse(raw);
        if (saved && saved.extraction && saved.extraction.apiKey) {
          delete saved.extraction.apiKey;
          localStorage.setItem(STORE_KEY, JSON.stringify(saved));
        }
      }
    } catch (e) { /* ignore */ }
  }

  function restoreApiKey() {
    try {
      var value = sessionStorage.getItem(CREDENTIAL_KEY);
      if (value) credential = { key: value, remember: true };
    } catch (e) { /* ignore */ }
  }

  /* Derived results are recomputed rather than persisted: they are large,
   * they are cheap to rebuild, and a stale analysis beside fresh data is the
   * one thing a report must never contain. The inversions are the exception
   * that is not cheap, and the state keeps them only as a cache keyed by
   * everything they were computed from, so a stale one cannot be found. */
  var derived = {
    soundings: null, inversions: null, interpretations: null,
    log: null, test: null, analysis: null, sample: null, assessment: null,
    /* why a test that is loaded has no analysis: stopped, or what it said */
    analysisNote: null,
    design: null, estimate: null, programme: null,
    /* the estimate's inputs and rates, which the cost distribution samples */
    costInputs: null, costRates: null,
    /* brought in by hand rather than computed from the sources: an area
     * inventory, other projects' summaries, an extracted scan */
    waterPoints: null, waterPointsSource: null, waterPointsCapped: false,
    waterPointsSkipped: null,
    /* the radius and centre of the site lookup the water points came from,
     * or null where they are not cut to a circle round the site (a CSV, the
     * national pull): the desk study and the rehabilitate-or-drill call
     * speak of the radius searched, not the box's value since */
    waterPointsRadius: null, waterPointsCentre: null,
    portfolio: null, extraction: null,
    /* the ledgers of the portfolio's files, by the index of their summaries */
    portfolioLedgers: null,
    /* and their works records (PLAN.md step 6.3), null for a file with none */
    portfolioWorks: null,
    /* a calibration set fitted on the Portfolio page and under review: the
     * set and what it was fitted from (calibrationSetsCard) */
    calibrationCandidate: null,
    /* a calibration set pooled from other organisations' files and under
     * review: the set and the set in force it was pooled beside */
    calibrationPooled: null,
    /* the reports of the last import on the Asset registry page, and how
     * many waiting on this phone the page last merged into a borehole's
     * history (PLAN.md step 7.1) */
    reportImport: null, reportsMerged: null,
  };
